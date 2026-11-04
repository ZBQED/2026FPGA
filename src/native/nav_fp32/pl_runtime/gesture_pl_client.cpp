#include "gesture_pl_client.h"
#include "gesture_pl_abi.h"
#include <cerrno>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#ifdef GESTURE_PL_EMULATION
#include "../pl_keypoints/keypoint_conv.h"
#else
#include <fcntl.h>
#include <sys/mman.h>
#include <unistd.h>
#endif
static thread_local std::string error;
struct Device {
    std::mutex mutex;
    gp_info info{};
    int fd=-1;
    unsigned char *pool=nullptr;
    bool faulted=false;
    uint64_t stats[4]{};
};
static uint32_t align64(uint64_t size) {return (uint32_t)((size+63)&~uint64_t(63));}
extern "C" {
const char *gp_last_error() {return error.c_str();}
const char *gp_backend_name() {
#ifdef GESTURE_PL_EMULATION
    return "hls_c_emulation_no_fpga";
#else
    return "zynq_pl_coherent_dma";
#endif
}
void *gp_open_device(const char *path) {
    auto d=std::unique_ptr<Device>(new Device);
#ifdef GESTURE_PL_EMULATION
    d->info={GP_ABI,32u*1024u*1024u,GP_CONFIG_WORDS,GP_MAX_FLOATS,GP_MAX_CHANNELS,GP_MAX_DIM,{0,0}};
#else
    d->fd=open(path?path:"/dev/gesture-pl0",O_RDWR|O_CLOEXEC);
    if(d->fd<0) {error="Cannot open PL device: "+std::string(strerror(errno)); return nullptr;}
    if(ioctl(d->fd,GP_IOCTL_INFO,&d->info)<0 || d->info.abi!=GP_ABI ||
       d->info.config_words!=GP_CONFIG_WORDS || d->info.pool_bytes<1024*1024) {
        error="PL device ABI/info mismatch"; close(d->fd); return nullptr;
    }
    void *p=mmap(nullptr,d->info.pool_bytes,PROT_READ|PROT_WRITE,MAP_SHARED,d->fd,0);
    if(p==MAP_FAILED) {error="PL mmap failed: "+std::string(strerror(errno)); close(d->fd); return nullptr;}
    d->pool=static_cast<unsigned char*>(p);
#endif
    error.clear(); return d.release();
}
void gp_close_device(void *handle) {
    if(!handle) return;
    auto *d=static_cast<Device*>(handle);
#ifndef GESTURE_PL_EMULATION
    if(d->pool) munmap(d->pool,d->info.pool_bytes);
    if(d->fd>=0) close(d->fd);
#endif
    delete d;
}
int gp_run(void *handle,const float *input,const float *weights,
           const float *bias,float *output,const int *config) {
    if(!handle||!input||!weights||!bias||!output||!config) {error="Null PL request";return -1;}
    auto *d=static_cast<Device*>(handle);
    std::lock_guard<std::mutex> lock(d->mutex);
    if(d->faulted) {error="PL device quarantined after failed transaction";return -1;}
    gp_job j{}; memcpy(j.config,config,sizeof(j.config)); j.timeout_ms=30000;
    gp_u64 sizes[4]{};
    /* First validate dimensions with disjoint temporary ranges. Compute sizes
     * without trusting unbounded signed products from model parameters. */
    j.offset[0]=0; j.offset[1]=8u*1024u*1024u;
    j.offset[2]=12u*1024u*1024u; j.offset[3]=13u*1024u*1024u;
    if(gp_validate(&j,d->info.pool_bytes,sizes)) {error="Unsupported PL dimensions";return -1;}
    j.offset[1]=align64(sizes[0]);
    j.offset[2]=align64((uint64_t)j.offset[1]+sizes[1]);
    j.offset[3]=align64((uint64_t)j.offset[2]+sizes[2]);
    if(gp_validate(&j,d->info.pool_bytes,sizes)) {error="PL buffers exceed coherent pool";return -1;}
    if(!j.config[16]) {error.clear();return 0;}
#ifdef GESTURE_PL_EMULATION
    int status=keypoint_conv_f32(input,weights,bias,output,j.config);
    if(status) {error="HLS C emulation rejected request";return -1;}
#else
    memcpy(d->pool+j.offset[0],input,sizes[0]);
    memcpy(d->pool+j.offset[1],weights,sizes[1]);
    memcpy(d->pool+j.offset[2],bias,sizes[2]);
    if(ioctl(d->fd,GP_IOCTL_RUN,&j)<0 || j.result) {
        d->faulted=true;
        error="PL ioctl failed: "+std::string(strerror(errno))+"; no automatic CPU substitution";
        return -1;
    }
    const uint64_t begin=uint64_t(j.config[15])*j.config[7]*sizeof(float);
    const uint64_t bytes=uint64_t(j.config[16])*j.config[7]*sizeof(float);
    memcpy(reinterpret_cast<unsigned char*>(output)+begin,d->pool+j.offset[3]+begin,bytes);
    ++d->stats[0]; d->stats[1]+=j.elapsed_ns;
    d->stats[2]+=sizes[0]+sizes[1]+sizes[2]; d->stats[3]+=bytes;
#endif
    error.clear();return 0;
}
void gp_get_stats(void *handle,uint64_t result[4]) {
    if(!handle||!result) return;
    auto *d=static_cast<Device*>(handle); std::lock_guard<std::mutex> lock(d->mutex);
    memcpy(result,d->stats,sizeof(d->stats));
}
}
