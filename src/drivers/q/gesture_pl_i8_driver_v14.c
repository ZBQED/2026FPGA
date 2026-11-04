// SPDX-License-Identifier: GPL-2.0
/* Independent RAW INT8 accelerator driver. No arbitrary physical DMA targets.
 * Local draft: matching target-kernel build and actual hardware tests pending.
 * A trusted loader must verify bit/HWH and own the PL lifecycle before binding.
 */
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
#include "gesture_pl_i8_abi.h"
#include "gesture_pl_i8_registers.h"

/* Sticky across DT removal/recreation. A DMA timeout also pins the module,
 * preventing unload/reload from clearing the quarantine. Only reboot releases.
 */
static atomic_t gpi8_quarantined=ATOMIC_INIT(0);
struct gpi8_device {
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
static void gpi8_free(struct kref *ref)
{
    struct gpi8_device *g=container_of(ref,struct gpi8_device,refs);
    if(g->configuration) dma_free_coherent(g->dev,PAGE_SIZE,g->configuration,g->config_dma);
    if(g->pool) dma_free_coherent(g->dev,GPI8_POOL_BYTES,g->pool,g->pool_dma);
    put_device(g->dev);
    kfree(g);
}
/* Must be called with the device mutex, or before exposing the device. */
static void gpi8_quarantine(struct gpi8_device *g)
{
    if(g->faulted) return;
    g->faulted=true;
    atomic_set(&gpi8_quarantined,1);
    kref_get(&g->refs);
    __module_get(THIS_MODULE);
    dev_err(g->dev,"DMA timeout: module and coherent buffers quarantined until reboot\n");
}
static void gpi8_pointer(struct gpi8_device *g,unsigned reg,dma_addr_t address)
{
    writel(lower_32_bits(address),g->regs+reg);
    writel(upper_32_bits(address),g->regs+reg+4);
}
static int gpi8_open(struct inode *inode,struct file *file)
{
    struct gpi8_device *g=container_of(file->private_data,struct gpi8_device,misc);
    int status=0;
    mutex_lock(&g->lock);
    if(g->dead) status=-ENODEV;
    else if(g->faulted) status=-EIO;
    else if(g->leased) status=-EBUSY;
    else {g->leased=g->fd_open=true; kref_get(&g->refs); file->private_data=g;}
    mutex_unlock(&g->lock);
    return status;
}
static int gpi8_release(struct inode *inode,struct file *file)
{
    struct gpi8_device *g=file->private_data;
    mutex_lock(&g->lock);
    g->fd_open=false;
    if(!g->mappings) g->leased=false;
    mutex_unlock(&g->lock);
    /* A surviving VMA keeps its own reference and exclusive lease. fork() is
     * tracked by vm_open; close(fd) cannot enable another process over it. */
    kref_put(&g->refs,gpi8_free);
    return 0;
}
static void gpi8_vma_open(struct vm_area_struct *vma)
{
    struct gpi8_device *g=vma->vm_private_data;
    mutex_lock(&g->lock); ++g->mappings; kref_get(&g->refs); mutex_unlock(&g->lock);
}
static void gpi8_vma_close(struct vm_area_struct *vma)
{
    struct gpi8_device *g=vma->vm_private_data;
    mutex_lock(&g->lock);
    --g->mappings;
    if(!g->mappings && !g->fd_open) g->leased=false;
    mutex_unlock(&g->lock);
    kref_put(&g->refs,gpi8_free);
}
static const struct vm_operations_struct gpi8_vm_ops={.open=gpi8_vma_open,.close=gpi8_vma_close};
static int gpi8_mmap(struct file *file,struct vm_area_struct *vma)
{
    struct gpi8_device *g=file->private_data;
    int status;
    if(vma->vm_pgoff || vma->vm_end-vma->vm_start!=GPI8_POOL_BYTES ||
       !(vma->vm_flags&VM_SHARED) || (vma->vm_flags&VM_EXEC)) return -EINVAL;
    mutex_lock(&g->lock);
    if(g->dead || g->faulted) {status=g->dead?-ENODEV:-EIO; goto done;}
    status=dma_mmap_coherent(g->dev,vma,g->pool,g->pool_dma,GPI8_POOL_BYTES);
    if(!status) {
        vma->vm_flags|=VM_DONTEXPAND|VM_DONTDUMP;
        vma->vm_flags&=~VM_MAYEXEC;
        vma->vm_ops=&gpi8_vm_ops; vma->vm_private_data=g;
        ++g->mappings; kref_get(&g->refs);
    }
done:
    mutex_unlock(&g->lock);
    return status;
}
static long gpi8_ioctl(struct file *file,unsigned command,unsigned long argument)
{
    struct gpi8_device *g=file->private_data;
    struct gpi8_job job;
    gpi8_u64 sizes[4];
    u32 control;
    u64 started;
    int status=0;
    if(command==GPI8_IOCTL_INFO || command==GPI8_IOCTL_INFO_INT8 || command==GPI8_IOCTL_INFO_PRELU) {
        struct gpi8_info info={GPI8_MAGIC,GPI8_ABI,GPI8_POOL_BYTES,GPI8_CONFIG_WORDS,
            GPI8_MAX_TENSOR,GPI8_MAX_WEIGHTS,GPI8_MAX_CHANNELS,GPI8_MAX_DIM,
            GPI8_FEATURE_RAW_ACC32|GPI8_FEATURE_FATAL_QUARANTINE|GPI8_FEATURE_PROBE_BAD_MAGIC,{0,0,0}};
        if(command==GPI8_IOCTL_INFO_INT8){info.abi=GPI8_ABI_INT8;info.features|=GPI8_FEATURE_INT8_OUTPUT;}
        if(command==GPI8_IOCTL_INFO_PRELU){info.abi=GPI8_ABI_PRELU;info.features|=GPI8_FEATURE_INT8_OUTPUT|GPI8_FEATURE_PRELU_LUT;}
        mutex_lock(&g->lock);
        status=g->dead?-ENODEV:g->faulted?-EIO:0;
        mutex_unlock(&g->lock);
        if(status) return status;
        return copy_to_user((void __user *)argument,&info,sizeof(info))?-EFAULT:0;
    }
    if(command!=GPI8_IOCTL_RUN && command!=GPI8_IOCTL_RUN_INT8 && command!=GPI8_IOCTL_RUN_PRELU) return -ENOTTY;
    if(copy_from_user(&job,(void __user *)argument,sizeof(job))) return -EFAULT;
    status=command==GPI8_IOCTL_RUN_PRELU?gpi8_validate_prelu(&job,GPI8_POOL_BYTES,sizes):command==GPI8_IOCTL_RUN_INT8?gpi8_validate_int8(&job,GPI8_POOL_BYTES,sizes):gpi8_validate(&job,GPI8_POOL_BYTES,sizes);
    if(status) return status==-3?-EOPNOTSUPP:-EINVAL;
    if(mutex_lock_interruptible(&g->lock)) return -ERESTARTSYS;
    if(g->dead) {status=-ENODEV; goto unlock;}
    if(g->faulted) {status=-EIO; goto unlock;}
    if(command==GPI8_IOCTL_RUN_INT8 || (command==GPI8_IOCTL_RUN_PRELU&&job.config[3]==1)) {
        const s32 *params=(const s32 *)((u8 *)g->pool+job.offset[2]);
        u32 channel;
        for(channel=0;channel<job.config[9];channel++)
            if(params[channel*4+1]<0 || params[channel*4+2]<-31 || params[channel*4+2]>0 || params[channel*4+3]){status=-EINVAL;goto unlock;}
    }
    control=readl(g->regs+GPI8_REG_CONTROL);
    if(!(control&4)) {status=-EBUSY; goto unlock;}
    memcpy(g->configuration,job.config,sizeof(job.config));
    gpi8_pointer(g,GPI8_REG_INPUT,g->pool_dma+job.offset[0]);
    gpi8_pointer(g,GPI8_REG_WEIGHTS,g->pool_dma+job.offset[1]);
    /* RAW does not dereference params; supply a valid bounded address anyway. */
    gpi8_pointer(g,GPI8_REG_PARAMS,g->pool_dma+(command!=GPI8_IOCTL_RUN?job.offset[2]:0));
    gpi8_pointer(g,GPI8_REG_OUTPUT,g->pool_dma+job.offset[3]);
    gpi8_pointer(g,GPI8_REG_CONFIG,g->config_dma);
    dma_wmb();
    started=ktime_get_ns();
    writel(1,g->regs+GPI8_REG_CONTROL);
    status=readl_poll_timeout(g->regs+GPI8_REG_CONTROL,control,control&2,10,job.timeout_ms*1000u);
    job.elapsed_ns=ktime_get_ns()-started;
    if(status) {gpi8_quarantine(g); job.result=-ETIMEDOUT;}
    else {
        dma_rmb(); job.result=(s32)readl(g->regs+GPI8_REG_RESULT);
        if(job.result) status=-EIO;
    }
    if(copy_to_user((void __user *)argument,&job,sizeof(job))) status=-EFAULT;
unlock:
    mutex_unlock(&g->lock);
    return status;
}
static const struct file_operations gpi8_fops={.owner=THIS_MODULE,.open=gpi8_open,
    .release=gpi8_release,.unlocked_ioctl=gpi8_ioctl,.compat_ioctl=gpi8_ioctl,
    .mmap=gpi8_mmap,.llseek=no_llseek};

/* This rejection transaction distinguishes this core from the known ABI1
 * core at identical register offsets (ABI2 returns 1; ABI1 returns -1).
 * It is NOT a cryptographic bitstream identity test. The loader must verify
 * the exact ABI2 bit/HWH hashes and fresh-boot/exclusive-PL ownership first.
 * Config is all zero so the expected core returns before reading tensors.
 */
static int gpi8_probe_identity(struct gpi8_device *g)
{
    u32 control,result;
    int status;
    gpi8_pointer(g,GPI8_REG_INPUT,g->pool_dma);
    gpi8_pointer(g,GPI8_REG_WEIGHTS,g->pool_dma+8);
    gpi8_pointer(g,GPI8_REG_PARAMS,g->pool_dma+16);
    gpi8_pointer(g,GPI8_REG_OUTPUT,g->pool_dma+24);
    gpi8_pointer(g,GPI8_REG_CONFIG,g->config_dma);
    writel(0,g->regs+GPI8_REG_GIE); writel(0,g->regs+GPI8_REG_IER);
    dma_wmb(); writel(1,g->regs+GPI8_REG_CONTROL);
    status=readl_poll_timeout(g->regs+GPI8_REG_CONTROL,control,control&2,10,100000);
    if(status) {gpi8_quarantine(g); return status;}
    dma_rmb(); result=readl(g->regs+GPI8_REG_RESULT);
    if(result!=1) {
        dev_err(g->dev,"ABI2 identity rejection returned 0x%x, expected 1\n",result);
        return -ENODEV;
    }
    return 0;
}

/* Rejected-capacity mode2 probe does not read tensors or write output. This
 * distinguishes the known old core (UNSUPPORTED=4) from mode2-capable core
 * (BAD_CAPACITY=3). Loader bit/HWH SHA verification remains mandatory. */
static int gpi8_probe_prelu(struct gpi8_device *g)
{
 u32 *c=g->configuration,control,result;int status;
 memset(c,0,PAGE_SIZE);c[0]=GPI8_MAGIC;c[1]=GPI8_ABI;c[3]=2;
 c[4]=c[5]=c[6]=c[7]=c[8]=c[9]=c[10]=c[11]=c[12]=c[13]=1;
 dma_wmb();writel(1,g->regs+GPI8_REG_CONTROL);
 status=readl_poll_timeout(g->regs+GPI8_REG_CONTROL,control,control&2,10,100000);
 if(status){gpi8_quarantine(g);return status;}
 dma_rmb();result=readl(g->regs+GPI8_REG_RESULT);
 if(result!=3){dev_err(g->dev,"PReLU mode2 rejected-capacity probe returned %u, expected 3\n",result);return -ENODEV;}
 memset(c,0,PAGE_SIZE);return 0;
}

static int gpi8_probe(struct platform_device *pdev)
{
    struct gpi8_device *g;
    struct resource *resource;
    int status;
    BUILD_BUG_ON(sizeof(struct gpi8_info)!=48);
    BUILD_BUG_ON(sizeof(struct gpi8_job)!=168);
    BUILD_BUG_ON(offsetof(struct gpi8_job,elapsed_ns)!=160);
    if(atomic_read(&gpi8_quarantined)) return -EIO;
    g=kzalloc(sizeof(*g),GFP_KERNEL); if(!g) return -ENOMEM;
    g->dev=get_device(&pdev->dev); mutex_init(&g->lock); kref_init(&g->refs);
    resource=platform_get_resource(pdev,IORESOURCE_MEM,0);
    if(!resource || resource_size(resource)<GPI8_REG_SPAN) {status=-EINVAL; goto failed;}
    g->regs=devm_ioremap_resource(&pdev->dev,resource);
    if(IS_ERR(g->regs)) {status=PTR_ERR(g->regs); goto failed;}
    /* The HLS AXI-Lite slave shares ap_rst_n. Reading it while reset is
     * asserted can stall the PS bus. Establish the independent GPIO as a
     * DEASSERTED output FIRST; active-low logical0 is physical ap_rst_n=1.
     * The fresh-boot-only overlay already initializes that same output1.
     * Xilinx 5.4 GPIO lacks get_direction, so do not require that optional
     * callback. This cannot assert reset over a running master, and GPIO
     * acquisition defers until its controller is ready.
     */
    g->reset=devm_gpiod_get(&pdev->dev,"reset",GPIOD_OUT_LOW);
    if(IS_ERR(g->reset)) {status=PTR_ERR(g->reset); goto failed;}
    status=gpiod_get_value_cansleep(g->reset);
    if(status<0) goto failed;
    if(status!=0) {status=-EBUSY; goto failed;}
    /* Never assert reset over an active master. A trusted fresh-boot loader
     * may bind only after the downloaded, clocked core reports idle. */
    if(!(readl(g->regs+GPI8_REG_CONTROL)&4)) {status=-EBUSY; goto failed;}
    status=dma_set_mask_and_coherent(&pdev->dev,DMA_BIT_MASK(32)); if(status) goto failed;
    g->pool=dma_alloc_coherent(g->dev,GPI8_POOL_BYTES,&g->pool_dma,GFP_KERNEL);
    g->configuration=dma_alloc_coherent(g->dev,PAGE_SIZE,&g->config_dma,GFP_KERNEL);
    if(!g->pool || !g->configuration) {status=-ENOMEM; goto failed;}
    memset(g->pool,0,GPI8_POOL_BYTES); memset(g->configuration,0,PAGE_SIZE);
    /* GPIO_ACTIVE_LOW means logical 1 asserts physical ap_rst_n=0. */
    status=gpiod_direction_output(g->reset,1); if(status) goto failed;
    usleep_range(10,50); gpiod_set_value_cansleep(g->reset,0); usleep_range(10,50);
    if(!(readl(g->regs+GPI8_REG_CONTROL)&4)) {status=-EBUSY; goto failed;}
    status=gpi8_probe_identity(g); if(status) goto failed;
    status=gpi8_probe_prelu(g); if(status) goto failed;
    g->misc.minor=MISC_DYNAMIC_MINOR; g->misc.name="gesture-i8-pl0";
    g->misc.fops=&gpi8_fops; g->misc.parent=&pdev->dev; g->misc.mode=0600;
    status=misc_register(&g->misc); if(status) goto failed;
    platform_set_drvdata(pdev,g);
    dev_info(g->dev,"INT8 RAW accumulator ABI2, coherent pool %u bytes\n",GPI8_POOL_BYTES);
    return 0;
failed:
    kref_put(&g->refs,gpi8_free); return status;
}
static int gpi8_remove(struct platform_device *pdev)
{
    struct gpi8_device *g=platform_get_drvdata(pdev);
    misc_deregister(&g->misc);
    mutex_lock(&g->lock); g->dead=true;
    if(!g->faulted) gpiod_set_value_cansleep(g->reset,1);
    mutex_unlock(&g->lock);
    kref_put(&g->refs,gpi8_free);
    return 0;
}
static const struct of_device_id gpi8_match[]={{.compatible="gesture,keypoint-conv-i8-v2"},{}};
MODULE_DEVICE_TABLE(of,gpi8_match);
static struct platform_driver gpi8_driver={.probe=gpi8_probe,.remove=gpi8_remove,
    .driver={.name="gesture-keypoint-i8-pl",.of_match_table=gpi8_match,.suppress_bind_attrs=true}};
module_platform_driver(gpi8_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("ABI2 RAW, ABI3 INT8 and explicit ABI4 PReLU/fusion bounded coherent-DMA runtime");
