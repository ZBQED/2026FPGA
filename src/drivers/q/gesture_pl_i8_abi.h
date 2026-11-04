#ifndef GESTURE_PL_I8_ABI_H
#define GESTURE_PL_I8_ABI_H
/* Independent Linux ABI2. Offsets refer only to the driver's coherent pool;
 * userspace never supplies physical addresses. RAW mode has no bias/activation.
 * Input/weights int8; output int32. All spans are rounded to eight bytes.
 * The mapped data must not be modified while RUN is in progress. */
#ifdef __KERNEL__
#include <linux/types.h>
#include <linux/ioctl.h>
typedef __u32 gpi8_u32;
typedef __s32 gpi8_i32;
typedef __u64 gpi8_u64;
#else
#include <stdint.h>
#ifndef _WIN32
#include <sys/ioctl.h>
#endif
typedef uint32_t gpi8_u32;
typedef int32_t gpi8_i32;
typedef uint64_t gpi8_u64;
#endif

enum { GPI8_MAGIC=0x3849504bU, GPI8_ABI=2, GPI8_CONFIG_WORDS=32,
       GPI8_POOL_BYTES=16u*1024u*1024u, GPI8_MAX_TENSOR=2097152,
       GPI8_MAX_WEIGHTS=1048576, GPI8_MAX_CHANNELS=1152, GPI8_MAX_DIM=512,
       GPI8_FEATURE_RAW_ACC32=1, GPI8_FEATURE_FATAL_QUARANTINE=2,
       GPI8_FEATURE_PROBE_BAD_MAGIC=4 };
struct gpi8_info {
    gpi8_u32 magic, abi, pool_bytes, config_words;
    gpi8_u32 max_tensor_elements, max_weight_elements, max_channels, max_dimension;
    gpi8_u32 features, reserved[3];
};
struct gpi8_job {
    gpi8_u32 offset[4]; /* input, OHWI/1HWCO weights, unused params=0, output */
    gpi8_u32 config[GPI8_CONFIG_WORDS]; /* immutable kernel copy before starting */
    gpi8_u32 timeout_ms;
    gpi8_i32 result; /* hardware return or negative errno; output only */
    gpi8_u32 reserved[2];
    gpi8_u64 elapsed_ns; /* output only; whole submitted hardware transaction */
};
#ifdef _WIN32
/* Linux asm-generic ioctl encoding, for host layout/contract tests only. */
#define GPI8_IOCTL_INFO (0x80000000u | ((gpi8_u32)sizeof(struct gpi8_info)<<16) | ('I'<<8) | 0x80u)
#define GPI8_IOCTL_RUN (0xc0000000u | ((gpi8_u32)sizeof(struct gpi8_job)<<16) | ('I'<<8) | 0x81u)
#else
#define GPI8_IOCTL_INFO _IOR('I', 0x80, struct gpi8_info)
#define GPI8_IOCTL_RUN _IOWR('I', 0x81, struct gpi8_job)
#endif

/* Validate before touching any control register. -1: ABI/shape/canonical RAW
 * fields, -2: capacity or DMA range, -3: explicitly unsupported INT8 output.
 * HLS accepts capacities >= required; this driver deliberately requires exact
 * rounded lengths to prevent a caller from claiming a larger mapped span.
 * Config: magic,ABI,op,mode,HI,WI,CI,HO,WO,CO,KH,KW,SH,SW,PT,PL,zx,
 *         output_zp,act_min,act_max,input/W/output/params word64 counts,8 zeros.
 */
static inline int gpi8_validate(const struct gpi8_job *j, gpi8_u32 pool,
                                gpi8_u64 size[4])
{
    const gpi8_u32 *c=j->config;
    gpi8_u64 ni,no,nw,red;
    int a,b;
    if(c[0]!=GPI8_MAGIC || c[1]!=GPI8_ABI) return -1;
    if(c[3]!=0) return -3;
    if(c[2]>1 || c[4]<1 || c[4]>GPI8_MAX_DIM || c[5]<1 || c[5]>GPI8_MAX_DIM ||
       c[6]<1 || c[6]>GPI8_MAX_CHANNELS || c[7]<1 || c[7]>GPI8_MAX_DIM ||
       c[8]<1 || c[8]>GPI8_MAX_DIM || c[9]<1 || c[9]>GPI8_MAX_CHANNELS ||
       c[10]<1 || c[10]>5 || c[11]<1 || c[11]>5 ||
       c[12]<1 || c[12]>2 || c[13]<1 || c[13]>2 || c[14]>=c[10] || c[15]>=c[11] ||
       (gpi8_i32)c[16]<-128 || (gpi8_i32)c[16]>127 ||
       c[17]!=0 || c[18]!=0 || c[19]!=0 || c[23]!=0 ||
       j->offset[2]!=0 || j->reserved[0] || j->reserved[1] ||
       j->timeout_ms<1 || j->timeout_ms>30000) return -1;
    for(a=24;a<32;++a) if(c[a]) return -1;
    if(c[2]==1 && c[6]!=c[9]) return -1;
    ni=(gpi8_u64)c[4]*c[5]*c[6]; no=(gpi8_u64)c[7]*c[8]*c[9];
    red=(gpi8_u64)c[10]*c[11]*c[6]; nw=c[2]==0?red*c[9]:red;
    if(ni>GPI8_MAX_TENSOR || no>GPI8_MAX_TENSOR || nw>GPI8_MAX_WEIGHTS) return -1;
    size[0]=(ni+7u)&~(gpi8_u64)7;
    size[1]=(nw+7u)&~(gpi8_u64)7;
    size[2]=0;
    size[3]=(no*4u+7u)&~(gpi8_u64)7;
    if(c[20]!=size[0]/8 || c[21]!=size[1]/8 || c[22]!=size[3]/8) return -2;
    for(a=0;a<4;++a) {
        if(!size[a]) continue;
        if((j->offset[a]&7u) || (gpi8_u64)j->offset[a]+size[a]>pool) return -2;
        for(b=0;b<a;++b) {
            if(size[b] && j->offset[a]<(gpi8_u64)j->offset[b]+size[b] &&
               j->offset[b]<(gpi8_u64)j->offset[a]+size[a]) return -2;
        }
    }
    return 0;
}
/* Independent extension query/submit. Old INFO2/7 and RAW RUN are unchanged. */
#define GPI8_IOCTL_INFO_INT8 (GPI8_IOCTL_INFO+2u)
#define GPI8_IOCTL_RUN_INT8 (GPI8_IOCTL_RUN+2u)
#define GPI8_ABI_INT8 3u
#define GPI8_FEATURE_INT8_OUTPUT 8u

static inline int gpi8_validate_int8(const struct gpi8_job *j, gpi8_u32 pool,
                                gpi8_u64 size[4])
{
    const gpi8_u32 *c=j->config;
    gpi8_u64 ni,no,nw,red;
    int a,b;
    if(c[0]!=GPI8_MAGIC || c[1]!=GPI8_ABI) return -1;
    if(c[3]!=1) return -3;
    if(c[2]>1 || c[4]<1 || c[4]>GPI8_MAX_DIM || c[5]<1 || c[5]>GPI8_MAX_DIM ||
       c[6]<1 || c[6]>GPI8_MAX_CHANNELS || c[7]<1 || c[7]>GPI8_MAX_DIM ||
       c[8]<1 || c[8]>GPI8_MAX_DIM || c[9]<1 || c[9]>GPI8_MAX_CHANNELS ||
       c[10]<1 || c[10]>5 || c[11]<1 || c[11]>5 ||
       c[12]<1 || c[12]>2 || c[13]<1 || c[13]>2 || c[14]>=c[10] || c[15]>=c[11] ||
       (gpi8_i32)c[16]<-128 || (gpi8_i32)c[16]>127 ||
       (gpi8_i32)c[17]<-128 || (gpi8_i32)c[17]>127 || (gpi8_i32)c[18]<-128 || (gpi8_i32)c[19]>127 || (gpi8_i32)c[18]>(gpi8_i32)c[19] || c[23]!=2*c[9] ||
       j->reserved[0] || j->reserved[1] ||
       j->timeout_ms<1 || j->timeout_ms>30000) return -1;
    for(a=24;a<32;++a) if(c[a]) return -1;
    if(c[2]==1 && c[6]!=c[9]) return -1;
    ni=(gpi8_u64)c[4]*c[5]*c[6]; no=(gpi8_u64)c[7]*c[8]*c[9];
    red=(gpi8_u64)c[10]*c[11]*c[6]; nw=c[2]==0?red*c[9]:red;
    if(ni>GPI8_MAX_TENSOR || no>GPI8_MAX_TENSOR || nw>GPI8_MAX_WEIGHTS) return -1;
    size[0]=(ni+7u)&~(gpi8_u64)7;
    size[1]=(nw+7u)&~(gpi8_u64)7;
    size[2]=(gpi8_u64)c[9]*16;
    size[3]=(no+7u)&~(gpi8_u64)7;
    if(c[20]!=size[0]/8 || c[21]!=size[1]/8 || c[22]!=size[3]/8) return -2;
    for(a=0;a<4;++a) {
        if(!size[a]) continue;
        if((j->offset[a]&7u) || (gpi8_u64)j->offset[a]+size[a]>pool) return -2;
        for(b=0;b<a;++b) {
            if(size[b] && j->offset[a]<(gpi8_u64)j->offset[b]+size[b] &&
               j->offset[b]<(gpi8_u64)j->offset[a]+size[a]) return -2;
        }
    }
    return 0;
}

/* Explicit LUT/fusion capability. I:82/83 keeps its original ABI3/features15
 * and must reject cfg24!=0. I:84/85 is only advertised by the new driver/core. */
#define GPI8_IOCTL_INFO_PRELU (GPI8_IOCTL_INFO+4u)
#define GPI8_IOCTL_RUN_PRELU (GPI8_IOCTL_RUN+4u)
#define GPI8_ABI_PRELU 4u
#define GPI8_FEATURE_PRELU_LUT 16u
#define GPI8_MAX_PRELU_CHANNELS 256u
static inline int gpi8_validate_prelu(const struct gpi8_job *j,gpi8_u32 pool,gpi8_u64 size[4])
{
 const gpi8_u32 *c=j->config;gpi8_u64 n;int a,b,status;
 if(pool!=GPI8_POOL_BYTES||c[0]!=GPI8_MAGIC||c[1]!=GPI8_ABI||j->reserved[0]||j->reserved[1]||j->timeout_ms<1||j->timeout_ms>30000)return -1;
 if(c[3]==1){
  struct gpi8_job base=*j;
  if(c[24]!=1||!c[9]||c[9]>GPI8_MAX_PRELU_CHANNELS||c[23]!=34*c[9])return -1;
  base.config[24]=0;base.config[23]=2*c[9];
  status=gpi8_validate_int8(&base,pool,size);if(status)return status;
  size[2]=(gpi8_u64)c[9]*34u*8u;
 }else if(c[3]==2){
  if(c[2]!=0||c[4]<1||c[4]>GPI8_MAX_DIM||c[5]<1||c[5]>GPI8_MAX_DIM||!c[6]||c[6]>GPI8_MAX_PRELU_CHANNELS||
     c[7]!=c[4]||c[8]!=c[5]||c[9]!=c[6]||c[10]!=1||c[11]!=1||c[12]!=1||c[13]!=1||
     c[14]||c[15]||c[16]||c[17]||c[18]||c[19]||c[21]||j->offset[1])return -1;
  for(a=24;a<32;++a)if(c[a])return -1;
  n=(gpi8_u64)c[4]*c[5]*c[6];if(n>GPI8_MAX_TENSOR)return -1;
  size[0]=(n+7u)&~(gpi8_u64)7;size[1]=0;size[2]=(gpi8_u64)c[6]*256u;size[3]=size[0];
  if(c[20]!=size[0]/8||c[22]!=size[3]/8||c[23]!=size[2]/8)return -2;
 }else return -3;
 for(a=0;a<4;++a){
  if(!size[a])continue;
  if((j->offset[a]&7u)||(gpi8_u64)j->offset[a]+size[a]>pool)return -2;
  for(b=0;b<a;++b)if(size[b]&&j->offset[a]<(gpi8_u64)j->offset[b]+size[b]&&j->offset[b]<(gpi8_u64)j->offset[a]+size[a])return -2;
 }
 return 0;
}

#endif
