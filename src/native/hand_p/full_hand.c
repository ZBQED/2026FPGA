#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <arm_neon.h>
#include "gesture_pl_add_abi.h"
#ifndef GPI8_FEATURE_ADD_CHANNELS
#define GPI8_FEATURE_ADD_CHANNELS 0u
#endif

struct fh_op {
    uint32_t kind,a,b,out,n,channels,hw,float_params,ih,iw,oh,ow,cache,a_bytes,b_bytes;
    int32_t zx,zy,zo;
    int64_t m1,m2;
    float scalar;
    uint32_t cfg[32],offsets[4];
};
#include "hand_plan.h"
#ifndef FH_REQUIRES_ADD
#define FH_REQUIRES_ADD 0u
#endif
#ifndef FH_CACHE_PS
#define FH_CACHE_PS 0u
#endif
static int device=-1;
static uint8_t *pool,*mapping;
static uint8_t *ps_pool;
static int owned_fd;
static uint32_t pool_base;
static pid_t owner_pid;
static int8_t *scratch;
static uint8_t *trace;
static int trace_valid;
static uint64_t profile[sizeof(FH_OPS)/sizeof(FH_OPS[0])*2];
static inline void *ps_input(uint32_t offset,uint32_t bytes,void *fallback){
    if(FH_CACHE_PS)return ps_pool+offset;
    memcpy(fallback,pool+offset,bytes);return fallback;
}
static inline void *ps_output(uint32_t offset,void *fallback){return FH_CACHE_PS?ps_pool+offset:fallback;}
static inline void ps_commit(uint32_t offset,const void *value,uint32_t bytes){if(!FH_CACHE_PS)memcpy(pool+offset,value,bytes);}
static uint64_t ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000u+t.tv_nsec;}
static int8_t clamp(int64_t v){return v < -128 ? -128 : v > 127 ? 127 : (int8_t)v;}
/* VFPv3 uses FPSCR rounding; fh_run requires nearest-even. */
static inline int32_t round_double(double v){
    int32_t result;__asm__("vcvtr.s32.f64 %0, %P1":"=t"(result):"w"(v));return result;
}
/* Bilinear INT8: |value/denominator| <= 128. Correct the float estimate exactly. */
static inline int32_t resize_round(int32_t value,int32_t denominator,float inverse){
    int32_t positive=value<0?-value:value,q=(int32_t)((float)positive*inverse),r=positive-q*denominator;
    if(r<0){--q;r+=denominator;}else if(r>=denominator){++q;r-=denominator;}
    if(r>denominator-r||(r==denominator-r&&(q&1)))++q;
    return value<0?-q:q;
}
static int64_t nearest_even(int64_t value,int64_t denominator){
    int64_t positive=value<0?-value:value,q=positive/denominator,r=positive%denominator;
    if(r>denominator-r || (r==denominator-r && (q&1)))++q;
    return value<0?-q:q;
}
static inline int32x4_t add4v(int32x4_t a,int32x4_t b,int32x4_t m1,int32x4_t m2,int32_t zero){
    int64x2_t p0=vmull_s32(vget_low_s32(a),vget_low_s32(m1));
    int64x2_t p1=vmull_s32(vget_high_s32(a),vget_high_s32(m1));
    p0=vmlal_s32(p0,vget_low_s32(b),vget_low_s32(m2));
    p1=vmlal_s32(p1,vget_high_s32(b),vget_high_s32(m2));
    int32x4_t q=vcombine_s32(vshrn_n_s64(p0,24),vshrn_n_s64(p1,24));
    uint32x4_t rem=vandq_u32(vcombine_u32(vmovn_u64(vreinterpretq_u64_s64(p0)),vmovn_u64(vreinterpretq_u64_s64(p1))),vdupq_n_u32(0xffffff));
    uint32x4_t half=vdupq_n_u32(0x800000),one=vdupq_n_u32(1);
    uint32x4_t odd=vceqq_u32(vandq_u32(vreinterpretq_u32_s32(q),one),one);
    uint32x4_t increment=vandq_u32(vorrq_u32(vcgtq_u32(rem,half),vandq_u32(vceqq_u32(rem,half),odd)),one);
    return vaddq_s32(vaddq_s32(q,vreinterpretq_s32_u32(increment)),vdupq_n_s32(zero));
}
static inline int32x4_t add4(int32x4_t a,int32x4_t b,int32_t m1,int32_t m2,int32_t zero){return add4v(a,b,vdupq_n_s32(m1),vdupq_n_s32(m2),zero);}
static void add_neon(const int8_t *restrict a,const int8_t *restrict b,int8_t *restrict out,const struct fh_op *restrict o){
    uint32_t i=0;
    if(o->m1<=INT32_MAX&&o->m2<=INT32_MAX){
        for(;i+8<=o->n;i+=8){
            int16x8_t al=vsubq_s16(vmovl_s8(vld1_s8(a+i)),vdupq_n_s16(o->zx));
            int16x8_t bl=vsubq_s16(vmovl_s8(vld1_s8(b+i)),vdupq_n_s16(o->zy));
            int32x4_t r0=add4(vmovl_s16(vget_low_s16(al)),vmovl_s16(vget_low_s16(bl)),o->m1,o->m2,o->zo);
            int16x4_t low=vqmovn_s32(r0);
            int32x4_t r1=add4(vmovl_s16(vget_high_s16(al)),vmovl_s16(vget_high_s16(bl)),o->m1,o->m2,o->zo);
            vst1_s8(out+i,vqmovn_s16(vcombine_s16(low,vqmovn_s32(r1))));
        }
    }
    for(;i<o->n;++i)out[i]=clamp(nearest_even(((int32_t)a[i]-o->zx)*o->m1+((int32_t)b[i]-o->zy)*o->m2,1LL<<24)+o->zo);
}
static void add_channels(const int8_t *a,const int8_t *b,int8_t *out,const int32_t *table,const struct fh_op *o){
    for(uint32_t p=0;p<o->hw;++p){
        uint32_t c=0,base=p*o->channels;
        for(;c+8<=o->channels;c+=8){
            int16x8_t x=vmovl_s8(vld1_s8(a+base+c)),y=vmovl_s8(vld1_s8(b+base+c));
            int32x4x2_t m0=vld2q_s32(table+2*c),m1=vld2q_s32(table+2*c+8);
            int32x4_t r0=add4v(vmovl_s16(vget_low_s16(x)),vmovl_s16(vget_low_s16(y)),m0.val[0],m0.val[1],0);
            int32x4_t r1=add4v(vmovl_s16(vget_high_s16(x)),vmovl_s16(vget_high_s16(y)),m1.val[0],m1.val[1],0);
            int8x8_t value=vqmovn_s16(vcombine_s16(vqmovn_s32(r0),vqmovn_s32(r1)));
            vst1_s8(out+base+c,vmax_s8(value,vdup_n_s8(o->zx)));
        }
        for(;c<o->channels;++c){int8_t v=clamp(nearest_even((int64_t)a[base+c]*table[2*c]+(int64_t)b[base+c]*table[2*c+1],INT64_C(1)<<24));out[base+c]=v<o->zx?o->zx:v;}
    }
}
static inline int64x2_t affine_round(int64x2_t product,int64x2_t shift){
    int64x2_t one=vdupq_n_s64(1),negative=vsubq_s64(vdupq_n_s64(0),shift);
    int64x2_t odd=vandq_s64(vshlq_s64(product,negative),one);
    int64x2_t half=vshlq_s64(one,vsubq_s64(shift,one));
    return vshlq_s64(vaddq_s64(product,vaddq_s64(vsubq_s64(half,one),odd)),negative);
}
static inline int32x4_t affine4(const int32_t *input,const int32_t *table,uint32_t channels,uint32_t c){
    const int64_t *bias=(const int64_t *)(table+channels*4);
    int32x4_t a=vminq_s32(vmaxq_s32(vld1q_s32(input),vld1q_s32(table+channels+c)),vld1q_s32(table+channels*2+c));
    int32x4_t m=vld1q_s32(table+c),s=vld1q_s32(table+channels*3+c);
    int64x2_t low=vaddq_s64(vmull_s32(vget_low_s32(a),vget_low_s32(m)),vld1q_s64(bias+c));
    int64x2_t high=vaddq_s64(vmull_s32(vget_high_s32(a),vget_high_s32(m)),vld1q_s64(bias+c+2));
    return vcombine_s32(vmovn_s64(affine_round(low,vmovl_s32(vget_low_s32(s)))),vmovn_s64(affine_round(high,vmovl_s32(vget_high_s32(s)))));
}
int fh_profile(uint64_t *values,uint32_t elements){
    if(elements!=sizeof(profile)/sizeof(profile[0]))return -EINVAL;
    memcpy(values,profile,sizeof(profile));return 0;
}
int fh_close(void){
    if(mapping){munmap(mapping,GPI8_POOL_BYTES);mapping=NULL;pool=NULL;}
    if(device>=0&&owned_fd)close(device);
    device=-1;owned_fd=0;pool_base=0;owner_pid=0;
    free(scratch);scratch=NULL;free(trace);trace=NULL;free(ps_pool);ps_pool=NULL;trace_valid=0;return 0;
}
int fh_trace(int enabled){
    if(!pool)return -EINVAL;
    trace_valid=0;
    if(!enabled){free(trace);trace=NULL;return 0;}
    if(!trace)trace=malloc(FH_TRACE_BYTES);
    return trace?0:-ENOMEM;
}
int fh_copy_tensor(uint32_t index,void *target,uint32_t bytes){
    if(!pool||index>=sizeof(FH_OPS)/sizeof(FH_OPS[0]))return -EINVAL;
    const struct fh_op *o=&FH_OPS[index];
    if(o->kind!=1||bytes!=o->n*(o->cfg[3]?1u:4u))return -EINVAL;
    if(!trace||!trace_valid)return -ENODATA;
    memcpy(target,trace+FH_TRACE_OFFSETS[index],bytes);return 0;
}
static int initialize(const char *weights,int parent_fd,uint32_t base){
    if(device>=0)return -EBUSY;
    struct gpi8_info info;int input=-1;size_t done=0;
    owned_fd=parent_fd<0;pool_base=base;owner_pid=getpid();
    if((uint64_t)pool_base+FH_POOL_USED>GPI8_POOL_BYTES){errno=EOVERFLOW;goto failed;}
    device=owned_fd?open("/dev/gesture-i8-pl0",O_RDWR|O_CLOEXEC):parent_fd;
    if(device<0)goto failed;
    if(ioctl(device,FH_REQUIRES_ADD?GPI8_IOCTL_INFO_ADD:FH_REQUIRES_PRELU?GPI8_IOCTL_INFO_PRELU:GPI8_IOCTL_INFO_INT8,&info)||info.magic!=GPI8_MAGIC||info.abi!=(FH_REQUIRES_ADD?GPI8_ABI_ADD:FH_REQUIRES_PRELU?4u:3u)||info.pool_bytes!=GPI8_POOL_BYTES||info.features!=(FH_REQUIRES_ADD?(63u|GPI8_FEATURE_ADD_CHANNELS):FH_REQUIRES_PRELU?31u:15u)){errno=EPROTO;goto failed;}
    mapping=mmap(NULL,GPI8_POOL_BYTES,PROT_READ|PROT_WRITE,MAP_SHARED,device,0);
    if(mapping==MAP_FAILED){mapping=NULL;goto failed;}
    pool=mapping+pool_base;
    scratch=malloc(FH_SCRATCH_BYTES*3u);
    if(!scratch)goto failed;
    input=open(weights,O_RDONLY|O_CLOEXEC);
    if(input<0)goto failed;
    /* All constant weights/post tables are staged once; no per-layer weight copies. */
    while(done<FH_BLOB_BYTES){ssize_t n=read(input,pool+done,FH_BLOB_BYTES-done);if(n<=0){errno=EIO;goto failed;}done+=(size_t)n;}
    for(size_t i=0;i<sizeof(FH_GUARDS)/sizeof(FH_GUARDS[0]);++i)memset(pool+FH_GUARDS[i],0xa5,64);
    if(FH_CACHE_PS){
        ps_pool=malloc(FH_POOL_USED);if(!ps_pool)goto failed;
        memcpy(ps_pool,pool,FH_BLOB_BYTES);
        for(size_t i=0;i<sizeof(FH_GUARDS)/sizeof(FH_GUARDS[0]);++i)memset(ps_pool+FH_GUARDS[i],0xa5,64);
    }
    close(input);return 0;
failed:
    {int saved=errno?errno:EIO;if(input>=0)close(input);fh_close();return -saved;}
}
int fh_open(const char *weights){return initialize(weights,-1,0);}
/* Borrow this process's explicit TCN owner. Never open, duplicate or close its FD. */
int fh_attach(int parent_fd,const char *weights){return parent_fd<0?-EINVAL:initialize(weights,parent_fd,7u<<20);}
/* The caller allocates disjoint, guarded model regions under one device owner. */
int fh_attach_at(int parent_fd,const char *weights,uint32_t base){
    return parent_fd<0||(base&63u)?-EINVAL:initialize(weights,parent_fd,base);
}
int fh_run(const int8_t *input,uint32_t input_bytes,float *heads,uint32_t head_values,uint64_t stats[8]){
    if(device<0||!pool||getpid()!=owner_pid||input_bytes!=FH_INPUT_ELEMENTS||head_values!=FH_TOTAL_OUTPUT_VALUES)return -EINVAL;
    if(fegetround()!=FE_TONEAREST)return -EINVAL;
    trace_valid=0;
    memset(stats,0,8*sizeof(*stats));memset(profile,0,sizeof(profile));uint64_t start=ns(),t=start;
    memcpy(pool+FH_INPUT_OFFSET,input,input_bytes);stats[3]=ns()-t;
    for(size_t index=0;index<sizeof(FH_OPS)/sizeof(FH_OPS[0]);++index){
        const struct fh_op *o=&FH_OPS[index];t=ns();
        if(o->kind==1){
            uint64_t copy_ns=0;
            if(FH_CACHE_PS&&(o->cache&12)){
                if(o->cache&4)memcpy(pool+o->offsets[0],ps_pool+o->offsets[0],o->a_bytes);
                if(o->cache&8)memcpy(pool+o->offsets[1],ps_pool+o->offsets[1],o->b_bytes);
                copy_ns=ns()-t;stats[4]+=copy_ns;
            }
            struct gpi8_job job;memset(&job,0,sizeof(job));
            memcpy(job.offset,o->offsets,sizeof(job.offset));memcpy(job.config,o->cfg,sizeof(job.config));job.timeout_ms=10000;
            for(unsigned j=0;j<4;++j)if((j!=2||o->cfg[3])&&(j!=1||o->cfg[3]!=2))job.offset[j]+=pool_base;
            int rc=ioctl(device,o->cfg[3]==3?GPI8_IOCTL_RUN_ADD:(o->cfg[3]==2||o->cfg[24])?GPI8_IOCTL_RUN_PRELU:o->cfg[3]?GPI8_IOCTL_RUN_INT8:GPI8_IOCTL_RUN,&job);
            profile[index*2]=ns()-t;profile[index*2+1]=job.elapsed_ns;
            stats[1]+=profile[index*2]-copy_ns;stats[2]+=job.elapsed_ns;
            if(rc||job.result){stats[7]=index+1;return rc?-errno:-EIO;}
            ++stats[0];
            if(!o->cfg[3]&&o->float_params){
                int32_t *acc=(int32_t *)(pool+o->offsets[3]);float *out=(float *)acc;
                const float *p=(const float *)(pool+o->float_params);
                for(uint32_t i=0;i<o->n;++i){int32_t v=acc[i];uint32_t c=i%o->cfg[9];out[i]=(float)v*p[c*2]+p[c*2+1];}
            }
            if(trace)memcpy(trace+FH_TRACE_OFFSETS[index],pool+o->offsets[3],o->n*(o->cfg[3]?1u:4u));
            continue;
        }
        {
        uint8_t *device_pool=pool;uint8_t *pool=FH_CACHE_PS?ps_pool:device_pool;
        if(FH_CACHE_PS&&(o->cache&1))memcpy(pool+o->a,device_pool+o->a,o->a_bytes);
        if(FH_CACHE_PS&&(o->cache&2))memcpy(pool+o->b,device_pool+o->b,o->b_bytes);
        if(o->kind==2){
            const int8_t *a=ps_input(o->a,o->n,scratch),*b=ps_input(o->b,o->n,scratch+FH_SCRATCH_BYTES);
            int8_t *out=ps_output(o->out,scratch+2*FH_SCRATCH_BYTES);
            add_neon(a,b,out,o);
            ps_commit(o->out,out,o->n);
        }else if(o->kind==3){
            int8_t *out=ps_output(o->out,scratch+FH_SCRATCH_BYTES);const int8_t *a=ps_input(o->a,o->n,scratch);
            for(uint32_t c=0;c<o->channels;++c){
                int32_t sum=0;for(uint32_t p=0;p<o->hw;++p)sum+=(int32_t)a[p*o->channels+c]-o->zx;
                out[c]=clamp(nearest_even(sum*o->m1,(int64_t)o->hw<<24)+o->zo);
            }
            ps_commit(o->out,out,o->channels);
        }else if(o->kind==4||o->kind==5){
            const float *a=(const float *)(pool+o->a);float *out=(float *)(pool+o->out);
            for(uint32_t i=0;i<o->n;++i)out[i]=o->kind==4?1.f/(1.f+expf(-a[i])):a[i]/o->scalar;
        }else if(o->kind==6){
            memcpy(pool+o->out,pool+o->a,o->n);
        }else if(o->kind==7||o->kind==8){
            int8_t *out=ps_output(o->out,scratch+FH_SCRATCH_BYTES);const int8_t *data=ps_input(o->a,o->n,scratch);
            for(uint32_t y=0;y<o->oh;++y)for(uint32_t x=0;x<o->ow;++x){
                uint32_t y0,y1,x0,x1,fy=0,fx=0;
                if(o->kind==7){y0=y*2;y1=y0+1;x0=x*2;x1=x0+1;}
                else{
                    y0=y?(y-1)/2:0;y1=y?(y-1)/2+1:0;if(y1>=o->ih)y1=o->ih-1;
                    x0=x?(x-1)/2:0;x1=x?(x-1)/2+1:0;if(x1>=o->iw)x1=o->iw-1;
                    fy=(y&1)?1:3;fx=(x&1)?1:3;
                }
                uint32_t c=0;
                for(;c+8<=o->channels;c+=8){
                    int8x8_t a=vld1_s8(data+(y0*o->iw+x0)*o->channels+c),b=vld1_s8(data+(y0*o->iw+x1)*o->channels+c);
                    int8x8_t d=vld1_s8(data+(y1*o->iw+x0)*o->channels+c),e=vld1_s8(data+(y1*o->iw+x1)*o->channels+c),value;
                    if(o->kind==7)value=vmax_s8(vmax_s8(a,b),vmax_s8(d,e));
                    else{
                        int16x8_t upper=vmlaq_n_s16(vmulq_n_s16(vmovl_s8(a),4-(int)fx),vmovl_s8(b),fx);
                        int16x8_t lower=vmlaq_n_s16(vmulq_n_s16(vmovl_s8(d),4-(int)fx),vmovl_s8(e),fx);
                        int16x8_t sum=vmlaq_n_s16(vmulq_n_s16(upper,4-(int)fy),lower,fy),q=vshrq_n_s16(sum,4);
                        uint16x8_t rem=vandq_u16(vreinterpretq_u16_s16(sum),vdupq_n_u16(15)),one=vdupq_n_u16(1),half=vdupq_n_u16(8);
                        uint16x8_t odd=vceqq_u16(vandq_u16(vreinterpretq_u16_s16(q),one),one);
                        uint16x8_t inc=vandq_u16(vorrq_u16(vcgtq_u16(rem,half),vandq_u16(vceqq_u16(rem,half),odd)),one);
                        value=vmovn_s16(vaddq_s16(q,vreinterpretq_s16_u16(inc)));
                    }
                    vst1_s8(out+(y*o->ow+x)*o->channels+c,value);
                }
                for(;c<o->channels;++c){
                    int a=data[(y0*o->iw+x0)*o->channels+c],b=data[(y0*o->iw+x1)*o->channels+c];
                    int d=data[(y1*o->iw+x0)*o->channels+c],e=data[(y1*o->iw+x1)*o->channels+c];
                    int v;
                    if(o->kind==7){v=a>b?a:b;if(d>v)v=d;if(e>v)v=e;}
                    else v=(int)nearest_even((a*(4-(int)fx)+b*(int)fx)*(4-(int)fy)+(d*(4-(int)fx)+e*(int)fx)*(int)fy,16);
                    out[(y*o->ow+x)*o->channels+c]=(int8_t)v;
                }
            }
            ps_commit(o->out,out,o->oh*o->ow*o->channels);
        }else if(o->kind==9){
            int8_t *out=ps_output(o->out,scratch+FH_SCRATCH_BYTES);const int8_t *a=ps_input(o->a,o->hw*o->channels,scratch);
            memset(out,(unsigned char)o->zo,o->hw*o->n);
            for(uint32_t p=0;p<o->hw;++p)memcpy(out+p*o->n,a+p*o->channels,o->channels);
            ps_commit(o->out,out,o->hw*o->n);
        }else if(o->kind==10){
            int8_t *out=ps_output(o->out,scratch+FH_SCRATCH_BYTES);const int8_t *a=ps_input(o->a,o->n,scratch);
            uint32_t half=o->channels/2;
            for(uint32_t p=0;p<o->hw;++p){
                const int8_t *src=a+p*o->channels;int8_t *dst=out+p*o->channels;uint32_t c=0;
                for(;c+8<=half;c+=8){int8x8x2_t v=vzip_s8(vld1_s8(src+c),vld1_s8(src+half+c));vst1_s8(dst+2*c,v.val[0]);vst1_s8(dst+2*c+8,v.val[1]);}
                for(;c<half;++c){dst[2*c]=src[c];dst[2*c+1]=src[half+c];}
            }
            ps_commit(o->out,out,o->n);
        }else if(o->kind==11){
            int8_t *out=ps_output(o->out,scratch+FH_SCRATCH_BYTES);const int8_t *a=ps_input(o->a,o->hw*o->channels,scratch);
            uint32_t stride=o->ow?o->ow:o->n;if(stride<o->n)return -EINVAL;
            if(o->zy&&((o->zx|o->n|o->channels)&1))return -EINVAL;
            for(uint32_t p=0;p<o->hw;++p){
                const int8_t *src=a+p*o->channels;int8_t *dst=out+p*stride;
                if(stride>o->n)memset(dst+o->n,0,stride-o->n);
                if(!o->zy){memcpy(dst,src+o->zx,o->n);continue;}
                uint32_t c=0,half=o->channels/2;
                for(;c+16<=o->n;c+=16){
                    int8x8x2_t v;v.val[0]=vld1_s8(src+(o->zx+c)/2);v.val[1]=vld1_s8(src+half+(o->zx+c)/2);vst2_s8(dst+c,v);
                }
                for(;c<o->n;++c)dst[c]=src[((o->zx+c)&1)*half+(o->zx+c)/2];
            }
            ps_commit(o->out,out,o->hw*stride);
        }else if(o->kind==12){
            int8_t table[512],*out=ps_output(o->out,scratch+2*FH_SCRATCH_BYTES);
            const int8_t *a=ps_input(o->a,o->hw*o->channels,scratch),*b=ps_input(o->b,o->hw*o->n,scratch+FH_SCRATCH_BYTES);
            memcpy(table,pool+o->float_params,sizeof(table));
            int identity=1;for(unsigned i=0;i<512;++i)if(table[i]!=(int8_t)i){identity=0;break;}
            for(uint32_t p=0;p<o->hw;++p){
                int8_t *dst=out+p*(o->channels+o->n);
                if(identity){memcpy(dst,a+p*o->channels,o->channels);memcpy(dst+o->channels,b+p*o->n,o->n);continue;}
                for(uint32_t c=0;c<o->channels;++c)dst[c]=table[(uint8_t)a[p*o->channels+c]];
                for(uint32_t c=0;c<o->n;++c)dst[o->channels+c]=table[256+(uint8_t)b[p*o->n+c]];
            }
            ps_commit(o->out,out,o->hw*(o->channels+o->n));
        }else if(o->kind==13||o->kind==14){
            int8_t *out=ps_output(o->out,scratch+FH_SCRATCH_BYTES);const int8_t *source=ps_input(o->a,o->n,scratch);
            int32_t denominator=(o->oh-1)*(o->ow-1);float inverse=o->kind==14?1.f/denominator:0.f;
            for(uint32_t y=0;y<o->oh;++y)for(uint32_t x=0;x<o->ow;++x){
                int8_t *dst=out+(y*o->ow+x)*o->channels;
                if(o->kind==13){memcpy(dst,source+((y*o->ih/o->oh)*o->iw+x*o->iw/o->ow)*o->channels,o->channels);continue;}
                uint32_t dy=o->oh-1,dx=o->ow-1,yn=y*(o->ih-1),xn=x*(o->iw-1),y0=yn/dy,x0=xn/dx,fy=yn%dy,fx=xn%dx;
                uint32_t y1=y0+1<o->ih?y0+1:y0,x1=x0+1<o->iw?x0+1:x0;
                for(uint32_t c=0;c<o->channels;++c){
                    int32_t a=source[(y0*o->iw+x0)*o->channels+c],b=source[(y0*o->iw+x1)*o->channels+c];
                    int32_t d=source[(y1*o->iw+x0)*o->channels+c],e=source[(y1*o->iw+x1)*o->channels+c];
                    int32_t value=(a*(int32_t)(dx-fx)+b*(int32_t)fx)*(int32_t)(dy-fy)+(d*(int32_t)(dx-fx)+e*(int32_t)fx)*(int32_t)fy;
                    dst[c]=(int8_t)resize_round(value,denominator,inverse);
                }
            }
            ps_commit(o->out,out,o->oh*o->ow*o->channels);
        }else if(o->kind==15){
            int64_t table[2304];int8_t *out=scratch+FH_SCRATCH_BYTES;
            if(o->channels>1152)return -EINVAL;
            memcpy(table,pool+o->float_params,o->channels*2*sizeof(int64_t));memcpy(scratch,pool+o->a,o->n*sizeof(int32_t));
            const int32_t *a=(const int32_t *)scratch;
            for(uint32_t p=0;p<o->hw;++p)for(uint32_t c=0;c<o->channels;++c){
                uint32_t i=p*o->channels+c;int64_t v=nearest_even(((int64_t)a[i]+table[c*2])*table[c*2+1],INT64_C(1)<<24)+o->zo;
                out[i]=(int8_t)(v<o->zx?o->zx:v>o->zy?o->zy:v);
            }
            memcpy(pool+o->out,out,o->n);
        }else if(o->kind==16){
            int8_t table[256],*out=ps_output(o->out,scratch+FH_SCRATCH_BYTES);const int8_t *a=ps_input(o->a,o->n,scratch);memcpy(table,pool+o->float_params,sizeof(table));
            int relu=1;for(int v=-128;v<128;++v)if(table[(uint8_t)v]!=(v>0?v:0)){relu=0;break;}
            uint32_t i=0;if(relu)for(;i+16<=o->n;i+=16)vst1q_s8(out+i,vmaxq_s8(vld1q_s8(a+i),vdupq_n_s8(0)));
            for(;i<o->n;++i)out[i]=table[(uint8_t)a[i]];
            ps_commit(o->out,out,o->n);
        }else if(o->kind==17){
            int32_t table[2304];int8_t *out=ps_output(o->out,scratch+2*FH_SCRATCH_BYTES);
            if(o->channels>1152)return -EINVAL;
            const int8_t *a=ps_input(o->a,o->n,scratch),*b=ps_input(o->b,o->n,scratch+FH_SCRATCH_BYTES);
            memcpy(table,pool+o->float_params,o->channels*2*sizeof(int32_t));
            add_channels(a,b,out,table,o);ps_commit(o->out,out,o->n);
        }else if(o->kind==20){
            const int32_t *a=ps_input(o->a,o->n*sizeof(int32_t),scratch),*table=(const int32_t *)(pool+o->float_params);
            int8_t *out=ps_output(o->out,scratch+2*FH_SCRATCH_BYTES);
            if(o->channels%8)return -EINVAL;
            for(uint32_t p=0;p<o->hw;++p)for(uint32_t c=0;c<o->channels;c+=8){
                uint32_t at=p*o->channels+c;
                int32x4_t low=affine4(a+at,table,o->channels,c),high=affine4(a+at+4,table,o->channels,c+4);
                int8x8_t value=vqmovn_s16(vcombine_s16(vqmovn_s32(low),vqmovn_s32(high)));
                vst1_s8(out+at,vmin_s8(vmax_s8(value,vdup_n_s8(o->zx)),vdup_n_s8(o->zy)));
            }
            ps_commit(o->out,out,o->n);
        }else if(o->kind==18||o->kind==19){
            double table[2304];int8_t *out=ps_output(o->out,scratch+2*FH_SCRATCH_BYTES);
            if(o->channels>1152)return -EINVAL;
            memcpy(table,pool+o->float_params,o->channels*2*sizeof(double));
            const int8_t *a=ps_input(o->a,o->n*(o->kind==18?sizeof(int32_t):1u),scratch);
            const int8_t *b=o->kind==19?ps_input(o->b,o->n,scratch+FH_SCRATCH_BYTES):NULL;
            for(uint32_t p=0;p<o->hw;++p)for(uint32_t c=0;c<o->channels;++c){
                uint32_t i=p*o->channels+c;
                double v=o->kind==18?(double)((const int32_t *)a)[i]*table[2*c]+table[2*c+1]:(double)a[i]*table[2*c]+(double)b[i]*table[2*c+1];
                out[i]=(int8_t)(v<=o->zx?o->zx:v>=o->zy?o->zy:round_double(v));
            }
            ps_commit(o->out,out,o->n);
        }else return -ENOTSUP;
        }
        profile[index*2]=ns()-t;stats[4]+=profile[index*2];
    }
    t=ns();
    for(size_t i=0;i<sizeof(FH_GUARDS)/sizeof(FH_GUARDS[0]);++i){
        uint64_t guard[8];memcpy(guard,pool+FH_GUARDS[i],64);
        for(unsigned k=0;k<8;++k)if(guard[k]!=UINT64_C(0xa5a5a5a5a5a5a5a5)){stats[7]=sizeof(FH_OPS)/sizeof(FH_OPS[0])+1;return -EIO;}
        if(FH_CACHE_PS){
            memcpy(guard,ps_pool+FH_GUARDS[i],64);
            for(unsigned k=0;k<8;++k)if(guard[k]!=UINT64_C(0xa5a5a5a5a5a5a5a5)){stats[7]=sizeof(FH_OPS)/sizeof(FH_OPS[0])+1;return -EIO;}
        }
    }
    stats[4]+=ns()-t;
    t=ns();uint32_t at=0;
    for(unsigned i=0;i<sizeof(FH_OUTPUT_VALUES)/sizeof(FH_OUTPUT_VALUES[0]);++i){
        const uint8_t *source=pool;
#if FH_CACHE_PS
        if(FH_OUTPUT_CACHED[i])source=ps_pool;
#endif
        memcpy(heads+at,source+FH_OUTPUT_OFFSETS[i],FH_OUTPUT_VALUES[i]*sizeof(float));at+=FH_OUTPUT_VALUES[i];
    }
    stats[5]=ns()-t;stats[6]=ns()-start;
    trace_valid=trace!=NULL;
    return stats[0]==FH_PL_JOBS?0:-EPROTO;
}
