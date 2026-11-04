#ifndef GESTURE_PL_ABI_H
#define GESTURE_PL_ABI_H
/* Userspace/kernel ABI: offsets into a coherent pool, never physical addresses. */
#ifdef __KERNEL__
#include <linux/types.h>
#include <linux/ioctl.h>
typedef __u32 gp_u32;
typedef __s32 gp_i32;
typedef __u64 gp_u64;
#else
#include <stdint.h>
#include <sys/ioctl.h>
typedef uint32_t gp_u32;
typedef int32_t gp_i32;
typedef uint64_t gp_u64;
#endif

enum { GP_ABI=1, GP_CONFIG_WORDS=17, GP_MAX_FLOATS=2097152,
       GP_MAX_WEIGHT_FLOATS=1048576, GP_MAX_CHANNELS=1152, GP_MAX_DIM=512 };
struct gp_info {
    gp_u32 abi, pool_bytes, config_words, max_tensor_floats;
    gp_u32 max_channels, max_dimension, reserved[2];
};
struct gp_job {
    gp_u32 offset[4]; /* input, weights, bias, output; must not overlap */
    gp_i32 config[GP_CONFIG_WORDS]; /* keypoint_conv.h ABI 1, immutable during DMA */
    gp_u32 timeout_ms;
    gp_i32 result;
    gp_u32 reserved;
    gp_u64 elapsed_ns;
};
#define GP_IOCTL_INFO _IOR('G', 0x70, struct gp_info)
#define GP_IOCTL_RUN _IOWR('G', 0x71, struct gp_job)

/* Validate before any register write. Returns 0 success, -1 unsupported shape,
 * -2 pool bounds/alignment/overlap. Shared by kernel and host contract tests. */
static inline int gp_validate(const struct gp_job *j, gp_u32 pool, gp_u64 size[4])
{
    const gp_i32 *c=j->config;
    gp_u64 pixels, red, weights;
    int a,b;
    if (c[0]!=GP_ABI || (c[1]!=0 && c[1]!=1) || c[2]<1 || c[2]>GP_MAX_DIM ||
        c[3]<1 || c[3]>GP_MAX_DIM || c[4]<1 || c[4]>GP_MAX_CHANNELS ||
        c[5]<1 || c[5]>GP_MAX_DIM || c[6]<1 || c[6]>GP_MAX_DIM ||
        c[7]<1 || c[7]>GP_MAX_CHANNELS ||
        (c[8]!=1 && c[8]!=2 && c[8]!=3 && c[8]!=5) ||
        (c[9]!=1 && c[9]!=2 && c[9]!=3 && c[9]!=5) ||
        (c[10]!=1 && c[10]!=2) || (c[11]!=1 && c[11]!=2) ||
        c[12]<0 || c[12]>=c[8] || c[13]<0 || c[13]>=c[9] ||
        (c[14]!=0 && c[14]!=1 && c[14]!=6) || c[15]<0 || c[16]<0 ||
        j->timeout_ms<1 || j->timeout_ms>30000) return -1;
    pixels=(gp_u64)c[5]*c[6];
    red=(gp_u64)c[8]*c[9]*c[4];
    if ((gp_u64)c[15]+c[16]>pixels || (c[1]==0 && red>1152) ||
        (c[1]==1 && c[7]!=c[4])) return -1;
    weights=c[1]==0 ? red*c[7] : red;
    size[0]=(gp_u64)c[2]*c[3]*c[4]*4;
    size[1]=weights*4;
    size[2]=(gp_u64)c[7]*4;
    size[3]=pixels*c[7]*4;
    if (size[0]>GP_MAX_FLOATS*4u || size[1]>GP_MAX_WEIGHT_FLOATS*4u ||
        size[3]>GP_MAX_FLOATS*4u) return -1;
    for (a=0;a<4;++a) {
        if ((j->offset[a]&3u) || (gp_u64)j->offset[a]+size[a]>pool) return -2;
        for (b=0;b<a;++b)
            if (j->offset[a] < (gp_u64)j->offset[b]+size[b] &&
                j->offset[b] < (gp_u64)j->offset[a]+size[a]) return -2;
    }
    return 0;
}
#endif
