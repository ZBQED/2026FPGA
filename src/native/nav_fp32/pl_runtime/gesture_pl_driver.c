// SPDX-License-Identifier: GPL-2.0
/* One isolated CNN accelerator. No userspace /dev/mem or arbitrary DMA target. */
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/dma-mapping.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/gpio/consumer.h>
#include <linux/mutex.h>
#include <linux/kref.h>
#include <linux/mm.h>
#include <linux/ktime.h>
#include <linux/delay.h>
#include <linux/of.h>
#include <linux/slab.h>
#include <linux/atomic.h>
#include "gesture_pl_abi.h"
/* Generated from the HLS IP register header; no guessed register addresses. */
#include "gesture_pl_registers.h"

#define GP_POOL_BYTES (32u*1024u*1024u)
/* Remains set across device-tree removal/recreation. A timed-out module pins
 * itself, so only a controlled reboot can release this quarantine. */
static atomic_t gp_quarantined=ATOMIC_INIT(0);
struct gp_device {
    struct device *dev;
    struct miscdevice misc;
    void __iomem *regs;
    void *pool, *configuration;
    dma_addr_t pool_dma, config_dma;
    struct gpio_desc *reset;
    struct mutex lock;
    struct kref refs;
    bool dead, fd_open, leased, faulted;
    unsigned mappings;
};
static void gp_free(struct kref *ref)
{
    struct gp_device *g=container_of(ref, struct gp_device, refs);
    if(g->configuration) dma_free_coherent(g->dev,PAGE_SIZE,g->configuration,g->config_dma);
    if(g->pool) dma_free_coherent(g->dev,GP_POOL_BYTES,g->pool,g->pool_dma);
    put_device(g->dev);
    kfree(g);
}
static void gp_reset(struct gp_device *g)
{
    /* DT GPIO_ACTIVE_LOW: logical 1 drives physical 0 to assert ap_rst_n. */
    gpiod_set_value_cansleep(g->reset,1);
    usleep_range(10,50);
    gpiod_set_value_cansleep(g->reset,0);
    usleep_range(10,50);
}
static int gp_open(struct inode *inode, struct file *file)
{
    struct gp_device *g=container_of(file->private_data,struct gp_device,misc);
    int status=0;
    mutex_lock(&g->lock);
    if(g->dead) status=-ENODEV;
    else if(g->leased) status=-EBUSY;
    else {g->leased=g->fd_open=true; kref_get(&g->refs); file->private_data=g;}
    mutex_unlock(&g->lock);
    return status;
}
static int gp_release(struct inode *inode, struct file *file)
{
    struct gp_device *g=file->private_data;
    mutex_lock(&g->lock);
    g->fd_open=false;
    if(!g->mappings) g->leased=false;
    mutex_unlock(&g->lock);
    kref_put(&g->refs,gp_free);
    return 0;
}
static void gp_vma_open(struct vm_area_struct *vma)
{
    struct gp_device *g=vma->vm_private_data;
    mutex_lock(&g->lock); ++g->mappings; kref_get(&g->refs); mutex_unlock(&g->lock);
}
static void gp_vma_close(struct vm_area_struct *vma)
{
    struct gp_device *g=vma->vm_private_data;
    mutex_lock(&g->lock);
    --g->mappings;
    if(!g->mappings && !g->fd_open) g->leased=false;
    mutex_unlock(&g->lock);
    kref_put(&g->refs,gp_free);
}
static const struct vm_operations_struct gp_vm_ops={.open=gp_vma_open,.close=gp_vma_close};
static int gp_mmap(struct file *file,struct vm_area_struct *vma)
{
    struct gp_device *g=file->private_data;
    int status;
    if(vma->vm_pgoff || vma->vm_end-vma->vm_start!=GP_POOL_BYTES) return -EINVAL;
    mutex_lock(&g->lock);
    if(g->dead) {mutex_unlock(&g->lock); return -ENODEV;}
    status=dma_mmap_coherent(g->dev,vma,g->pool,g->pool_dma,GP_POOL_BYTES);
    if(!status) {
        vma->vm_flags|=VM_DONTEXPAND|VM_DONTDUMP;
        vma->vm_ops=&gp_vm_ops; vma->vm_private_data=g;
        ++g->mappings; kref_get(&g->refs);
    }
    mutex_unlock(&g->lock);
    return status;
}
static void gp_pointer(struct gp_device *g,unsigned reg,dma_addr_t address)
{
    writel(lower_32_bits(address),g->regs+reg);
    writel(upper_32_bits(address),g->regs+reg+4);
}
static long gp_ioctl(struct file *file,unsigned command,unsigned long argument)
{
    struct gp_device *g=file->private_data;
    struct gp_job job;
    gp_u64 sizes[4];
    u32 control;
    u64 started;
    int status=0;
    if(command==GP_IOCTL_INFO) {
        struct gp_info info={GP_ABI,GP_POOL_BYTES,GP_CONFIG_WORDS,GP_MAX_FLOATS,GP_MAX_CHANNELS,GP_MAX_DIM,{0,0}};
        return copy_to_user((void __user *)argument,&info,sizeof(info))?-EFAULT:0;
    }
    if(command!=GP_IOCTL_RUN) return -ENOTTY;
    if(copy_from_user(&job,(void __user *)argument,sizeof(job))) return -EFAULT;
    if(gp_validate(&job,GP_POOL_BYTES,sizes)) return -EINVAL;
    if(mutex_lock_interruptible(&g->lock)) return -ERESTARTSYS;
    if(g->dead) {status=-ENODEV; goto unlock;}
    if(g->faulted) {status=-EIO; goto unlock;}
    control=readl(g->regs+GP_REG_CONTROL);
    if(!(control&4)) {status=-EBUSY; goto unlock;} /* Never reset in-flight AXI. */
    /* Config is in a separate kernel-only coherent allocation. Mapped data
     * cannot alter dimensions or pointer ranges after validation. */
    memcpy(g->configuration,job.config,sizeof(job.config));
    gp_pointer(g,GP_REG_INPUT,g->pool_dma+job.offset[0]);
    gp_pointer(g,GP_REG_WEIGHTS,g->pool_dma+job.offset[1]);
    gp_pointer(g,GP_REG_BIAS,g->pool_dma+job.offset[2]);
    gp_pointer(g,GP_REG_OUTPUT,g->pool_dma+job.offset[3]);
    gp_pointer(g,GP_REG_CONFIG,g->config_dma);
    dma_wmb();
    started=ktime_get_ns();
    writel(1,g->regs+GP_REG_CONTROL);
    status=readl_poll_timeout(g->regs+GP_REG_CONTROL,control,control&2,10,job.timeout_ms*1000u);
    job.elapsed_ns=ktime_get_ns()-started;
    if(status) {
        /* Outstanding AXI traffic may still exist. Do not reset the master or
         * reuse/free its buffers. Pin module+pool until a controlled reboot. */
        g->faulted=true; atomic_set(&gp_quarantined,1);
        kref_get(&g->refs); __module_get(THIS_MODULE);
        job.result=-ETIMEDOUT;
        dev_err(g->dev,"DMA timeout: quarantined pool; controlled reboot required\n");
    }
    else {dma_rmb(); job.result=(s32)readl(g->regs+GP_REG_RESULT); if(job.result) status=-EIO;}
    if(copy_to_user((void __user *)argument,&job,sizeof(job))) status=-EFAULT;
unlock:
    mutex_unlock(&g->lock);
    return status;
}
static const struct file_operations gp_fops={.owner=THIS_MODULE,.open=gp_open,
    .release=gp_release,.unlocked_ioctl=gp_ioctl,.compat_ioctl=gp_ioctl,
    .mmap=gp_mmap,.llseek=no_llseek};
static int gp_probe(struct platform_device *pdev)
{
    struct gp_device *g;
    struct resource *resource;
    int status;
    if(atomic_read(&gp_quarantined)) return -EIO;
    g=kzalloc(sizeof(*g),GFP_KERNEL); if(!g) return -ENOMEM;
    g->dev=get_device(&pdev->dev); mutex_init(&g->lock); kref_init(&g->refs);
    resource=platform_get_resource(pdev,IORESOURCE_MEM,0);
    g->regs=devm_ioremap_resource(&pdev->dev,resource);
    if(IS_ERR(g->regs)) {status=PTR_ERR(g->regs); goto failed;}
    g->reset=devm_gpiod_get(&pdev->dev,"reset",GPIOD_OUT_HIGH);
    if(IS_ERR(g->reset)) {status=PTR_ERR(g->reset); goto failed;}
    status=dma_set_mask_and_coherent(&pdev->dev,DMA_BIT_MASK(32)); if(status) goto failed;
    g->pool=dma_alloc_coherent(g->dev,GP_POOL_BYTES,&g->pool_dma,GFP_KERNEL);
    g->configuration=dma_alloc_coherent(g->dev,PAGE_SIZE,&g->config_dma,GFP_KERNEL);
    if(!g->pool || !g->configuration) {status=-ENOMEM; goto failed;}
    memset(g->pool,0,GP_POOL_BYTES); memset(g->configuration,0,PAGE_SIZE);
    gp_reset(g);
    g->misc.minor=MISC_DYNAMIC_MINOR; g->misc.name="gesture-pl0";
    g->misc.fops=&gp_fops; g->misc.parent=&pdev->dev; g->misc.mode=0600;
    status=misc_register(&g->misc); if(status) goto failed;
    platform_set_drvdata(pdev,g);
    dev_info(g->dev,"FP32 keypoint accelerator ABI1, coherent pool %u bytes\n",GP_POOL_BYTES);
    return 0;
failed:
    kref_put(&g->refs,gp_free); return status;
}
static int gp_remove(struct platform_device *pdev)
{
    struct gp_device *g=platform_get_drvdata(pdev);
    misc_deregister(&g->misc);
    mutex_lock(&g->lock); g->dead=true;
    if(!g->faulted) gpiod_set_value_cansleep(g->reset,1);
    mutex_unlock(&g->lock);
    kref_put(&g->refs,gp_free); return 0;
}
static const struct of_device_id gp_match[]={{.compatible="gesture,keypoint-conv-f32-v1"},{}};
MODULE_DEVICE_TABLE(of,gp_match);
static struct platform_driver gp_driver={.probe=gp_probe,.remove=gp_remove,
    .driver={.name="gesture-keypoint-pl",.of_match_table=gp_match,
             .suppress_bind_attrs=true}};
module_platform_driver(gp_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Bounded coherent-DMA runtime for gesture keypoint HLS accelerator");
