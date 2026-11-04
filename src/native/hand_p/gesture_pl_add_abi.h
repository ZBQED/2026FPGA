#ifndef GESTURE_PL_ADD_ABI_H
#define GESTURE_PL_ADD_ABI_H
#include "gesture_pl_i8_abi.h"
#define GPI8_IOCTL_INFO_ADD (GPI8_IOCTL_INFO+6u)
#define GPI8_IOCTL_RUN_ADD (GPI8_IOCTL_RUN+6u)
#define GPI8_ABI_ADD 5u
#define GPI8_FEATURE_ADD_Q24 32u
/* Explicit mode3: two INT8 tensors, 512 signed Q24 table entries and output.
 * Each table entry must be in [-2^48,+2^48], validated again in the driver.
 * Existing RAW/INT8/PReLU ioctl contracts stay unchanged and reject mode3. */
static inline int gpi8_validate_add(const struct gpi8_job *j,gpi8_u32 pool,gpi8_u64 size[4])
{
 const gpi8_u32 *c=j->config;gpi8_u64 n;int a,b;
 if(pool!=GPI8_POOL_BYTES||c[0]!=GPI8_MAGIC||c[1]!=GPI8_ABI||c[2]||c[3]!=3||
    j->reserved[0]||j->reserved[1]||j->timeout_ms<1||j->timeout_ms>30000)return -1;
 if(c[4]<1||c[4]>GPI8_MAX_DIM||c[5]<1||c[5]>GPI8_MAX_DIM||c[6]<1||c[6]>GPI8_MAX_CHANNELS||
    c[7]!=c[4]||c[8]!=c[5]||c[9]!=c[6]||c[10]!=1||c[11]!=1||c[12]!=1||c[13]!=1||
    c[14]||c[15]||c[16]||(gpi8_i32)c[17]<-128||(gpi8_i32)c[17]>127||
    (gpi8_i32)c[18]<-128||(gpi8_i32)c[19]>127||(gpi8_i32)c[18]>(gpi8_i32)c[19])return -1;
 for(a=24;a<32;++a)if(c[a])return -1;
 n=(gpi8_u64)c[4]*c[5]*c[6];if(n>GPI8_MAX_TENSOR)return -1;
 size[0]=size[1]=size[3]=(n+7u)&~(gpi8_u64)7;size[2]=512u*8u;
 if(c[20]!=size[0]/8||c[21]!=size[1]/8||c[22]!=size[3]/8||c[23]!=512)return -2;
 for(a=0;a<4;++a){
  if((j->offset[a]&7u)||j->offset[a]<64||(gpi8_u64)j->offset[a]+size[a]+64u>pool)return -2;
  for(b=0;b<a;++b)if((gpi8_u64)j->offset[a]<(gpi8_u64)j->offset[b]+size[b]+64u&&
                     (gpi8_u64)j->offset[b]<(gpi8_u64)j->offset[a]+size[a]+64u)return -2;
 }
 return 0;
}
#endif
