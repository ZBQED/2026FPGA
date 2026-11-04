/* Linux RAW ACC32 adapter. Original YOLO weights, graph and rounding retained.
 * Each convolution runs on PL; an error aborts, with no CPU fallback.
 */
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include "gesture_pl_i8_abi.h"
static int yp_fd=-1,yp_owns,yp_enabled;
static uint8_t *yp_map;
static uint32_t yp_base,yp_used,yp_guards[YF2_N_LAYERS+2],yp_ng;
static struct gpi8_job yp_jobs[YF2_N_LAYERS];
static int32_t *yp_bias[YF2_N_LAYERS],*yp_raw;
static uint64_t yp_stats[7];
static uint64_t yp_ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000u+t.tv_nsec;}
static uint32_t yp_align(uint32_t v){return (v+63u)&~63u;}
static int yp_region(uint32_t bytes,uint32_t *out){
    uint32_t span=yp_align(bytes);uint64_t end=(uint64_t)yp_used+span+64;
    if(end>GPI8_POOL_BYTES-yp_base||yp_ng>=YF2_N_LAYERS+2)return -EOVERFLOW;
    *out=yp_base+yp_used;yp_guards[yp_ng++]=*out+span;yp_used=(uint32_t)end;
    memset(yp_map+*out,0,span);memset(yp_map+*out+span,0xa5,64);return 0;
}
int yf2_fpga_guards(void){
    if(!yp_map)return -EINVAL;
    for(uint32_t i=0;i<yp_ng;++i)for(int j=0;j<64;++j)if(yp_map[yp_guards[i]+j]!=0xa5)return -EFAULT;
    return 0;
}
int yf2_fpga_close(void){
    yp_enabled=0;if(yp_map)munmap(yp_map,GPI8_POOL_BYTES);yp_map=NULL;
    if(yp_fd>=0&&yp_owns)close(yp_fd);yp_fd=-1;yp_owns=0;
    free(yp_raw);yp_raw=NULL;
    for(int i=0;i<YF2_N_LAYERS;++i){free(yp_bias[i]);yp_bias[i]=NULL;}
    yp_ng=yp_used=yp_base=0;return 0;
}
int yf2_fpga_enable(int enabled){if(enabled&&yp_fd<0)return -EBADF;yp_enabled=!!enabled;return 0;}
int yf2_fpga_stats(uint64_t *out){memcpy(out,yp_stats,sizeof(yp_stats));return 7;}
int yf2_fpga_pool_used(void){return (int)yp_used;}
int yf2_fpga_open_at(int parent,uint32_t base){
    if(yp_fd>=0)return -EBUSY;
    if(base&63u||base>=GPI8_POOL_BYTES||parent<-1)return -EINVAL;
    yp_base=base;yp_owns=parent<0;yp_fd=yp_owns?open("/dev/gesture-i8-pl0",O_RDWR|O_CLOEXEC):parent;
    if(yp_fd<0)return -errno;
    int rc=-EPROTO;struct gpi8_info info;
    if(ioctl(yp_fd,GPI8_IOCTL_INFO,&info)||info.magic!=GPI8_MAGIC||info.abi!=GPI8_ABI||info.features!=7||info.pool_bytes!=GPI8_POOL_BYTES)goto failed;
    yp_map=mmap(NULL,GPI8_POOL_BYTES,PROT_READ|PROT_WRITE,MAP_SHARED,yp_fd,0);
    if(yp_map==MAP_FAILED){yp_map=NULL;rc=-errno;goto failed;}
    /* PYNQ also requires a leading 64-byte fence; retain the stricter layout. */
    yp_used=64;yp_ng=1;yp_guards[0]=yp_base;memset(yp_map+yp_base,0xa5,64);
    uint32_t ni=0,no=0,input,output;
    for(int i=0;i<YF2_N_LAYERS;++i){const yf2_layer_t *l=YF2_LAYERS+i;if(l->type!=1&&l->type!=2)continue;
        uint32_t a=(uint32_t)l->h_in*l->w_in*l->c_in,b=(uint32_t)l->h_out*l->w_out*l->c_out;
        if(a>ni)ni=a;if(b>no)no=b;
    }
    if((rc=yp_region(ni,&input))||(rc=yp_region(no*4,&output)))goto failed;
    yp_raw=malloc(no*4);if(!yp_raw){rc=-ENOMEM;goto failed;}
    memset(yp_jobs,0,sizeof(yp_jobs));memset(yp_stats,0,sizeof(yp_stats));
    for(int i=0;i<YF2_N_LAYERS;++i){
        const yf2_layer_t *l=YF2_LAYERS+i;if(l->type!=1&&l->type!=2)continue;
        int dw=l->type==2,k=l->k,ci=l->c_in,co=l->c_out;
        uint32_t nw=(uint32_t)k*k*(dw?co:co*ci),wo;
        if((rc=yp_region(nw,&wo)))goto failed;
        yp_bias[i]=malloc(co*4);if(!yp_bias[i]){rc=-ENOMEM;goto failed;}
        const int8_t *w=YF2_W_PTRS[l->widx];int8_t *packed=(int8_t*)yp_map+wo;
        const int32_t *bias=YF2_BIAS_PTRS[l->widx],*m=YF2_M_PTRS[l->widx],*sh=YF2_SHIFT_PTRS[l->widx];
        for(int o=0;o<co;++o){int64_t sum=0,absolute=0;
            for(int y=0;y<k;++y)for(int x=0;x<k;++x)for(int c=0;c<(dw?1:ci);++c){
                int8_t value=w[dw?(o*k+y)*k+x:((o*ci+c)*k+y)*k+x];
                packed[dw?(y*k+x)*co+o:((o*k+y)*k+x)*ci+c]=value;sum+=value;absolute+=abs((int)value);
            }
            int64_t b=bias[o]+(int64_t)l->zp_in*sum,bound=llabs(b)+255*absolute;
            if(bound>INT32_MAX||m[o]<0||sh[o]<1||sh[o]>62||((bound*m[o]+(INT64_C(1)<<(sh[o]-1)))>>sh[o])>INT32_MAX-128){rc=-ERANGE;goto failed;}
            yp_bias[i][o]=(int32_t)b;
        }
        struct gpi8_job *j=yp_jobs+i;uint32_t *c=j->config;
        j->offset[0]=input;j->offset[1]=wo;j->offset[3]=output;j->timeout_ms=10000;
        uint32_t values[]={GPI8_MAGIC,GPI8_ABI,(uint32_t)dw,0,l->h_in,l->w_in,l->c_in,l->h_out,l->w_out,l->c_out,l->k,l->k,l->stride,l->stride,l->pad,l->pad,(uint32_t)l->zp_in,0,0,0};
        memcpy(c,values,sizeof(values));c[20]=((uint32_t)l->h_in*l->w_in*l->c_in+7)/8;c[21]=(nw+7)/8;c[22]=((uint32_t)l->h_out*l->w_out*l->c_out*4+7)/8;
        uint64_t sizes[4];if(gpi8_validate(j,GPI8_POOL_BYTES,sizes)){rc=-EINVAL;goto failed;}
    }
    yp_enabled=1;return yf2_fpga_guards();
failed:yf2_fpga_close();return rc;
}
static int32x4_t yp_quant4(const int32_t *a,const int32_t *b,const int32_t *m,const int32_t *sh,int zp){
    int32x4_t x=vaddq_s32(vld1q_s32(a),vld1q_s32(b)),mult=vld1q_s32(m),shift=vld1q_s32(sh);
    int64x2_t sl=vmovl_s32(vget_low_s32(shift)),su=vmovl_s32(vget_high_s32(shift)),one=vdupq_n_s64(1),zero=vdupq_n_s64(0);
    int64x2_t lo=vmull_s32(vget_low_s32(x),vget_low_s32(mult)),hi=vmull_s32(vget_high_s32(x),vget_high_s32(mult));
    lo=vshlq_s64(vaddq_s64(lo,vshlq_s64(one,vsubq_s64(sl,one))),vsubq_s64(zero,sl));
    hi=vshlq_s64(vaddq_s64(hi,vshlq_s64(one,vsubq_s64(su,one))),vsubq_s64(zero,su));
    return vaddq_s32(vcombine_s32(vmovn_s64(lo),vmovn_s64(hi)),vdupq_n_s32(zp));
}
static int yf2_fpga_conv(int8_t *buf,const yf2_layer_t *l){
    if(!yp_enabled||!yp_map)return -EBADF;
    int index=(int)(l-YF2_LAYERS);if(index<0||index>=YF2_N_LAYERS)return -EINVAL;
    struct gpi8_job j=yp_jobs[index];uint32_t ni=(uint32_t)l->h_in*l->w_in*l->c_in,no=(uint32_t)l->h_out*l->w_out*l->c_out;
    uint64_t t=yp_ns();memcpy(yp_map+j.offset[0],buf+l->in_off,ni);yp_stats[2]+=yp_ns()-t;
    uint32_t it=j.offset[0]+j.config[20]*8,ot=j.offset[3]+j.config[22]*8;
    memset(yp_map+it,0xa5,64);memset(yp_map+ot,0xa5,64);
    t=yp_ns();int rc=ioctl(yp_fd,GPI8_IOCTL_RUN,&j);yp_stats[1]+=j.elapsed_ns;yp_stats[5]+=yp_ns()-t;
    if(rc||j.result){yp_stats[6]=index+1;return rc?-errno:-EIO;}++yp_stats[0];
    uint64_t fences[16];memcpy(fences,yp_map+it,64);memcpy(fences+8,yp_map+ot,64);
    for(int n=0;n<16;++n)if(fences[n]!=UINT64_C(0xa5a5a5a5a5a5a5a5)){yp_stats[6]=index+1;return -EFAULT;}
    t=yp_ns();memcpy(yp_raw,yp_map+j.offset[3],no*4);yp_stats[3]+=yp_ns()-t;
    t=yp_ns();const int32_t *b=yp_bias[index],*m=YF2_M_PTRS[l->widx],*sh=YF2_SHIFT_PTRS[l->widx];int8_t *out=buf+l->out_off;
    for(uint32_t p=0;p<(uint32_t)l->h_out*l->w_out;++p){int c=0;uint32_t base=p*l->c_out;
        for(;c+8<=l->c_out;c+=8){
            int32x4_t lo=yp_quant4(yp_raw+base+c,b+c,m+c,sh+c,l->zp_out),hi=yp_quant4(yp_raw+base+c+4,b+c+4,m+c+4,sh+c+4,l->zp_out);
            int8x8_t v=vqmovn_s16(vcombine_s16(vqmovn_s32(lo),vqmovn_s32(hi)));
            if(l->relu)v=vmax_s8(v,vdup_n_s8((int8_t)l->zp_out));vst1_s8(out+base+c,v);
        }
        for(;c<l->c_out;++c)out[base+c]=(int8_t)requant((int64_t)yp_raw[base+c]+b[c],m[c],sh[c],l->zp_out,l->relu);
    }
    yp_stats[4]+=yp_ns()-t;return 0;
}
