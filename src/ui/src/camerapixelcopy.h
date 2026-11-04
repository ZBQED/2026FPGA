#ifndef MEDCOMM_CAMERA_PIXEL_COPY_H
#define MEDCOMM_CAMERA_PIXEL_COPY_H

#ifdef __ARM_NEON
#include <arm_neon.h>
#endif

/* Private destination and a read-only shared-slot source must be disjoint.
 * The caller checks slotSequence after this function, before publishing dst.
 * Same RGB888 pixels as memcpy followed by the existing in-place R/B swap.
 */
static inline void medcomm_copy_bgr_to_rgb(unsigned char *dst,
                                            const unsigned char *src,
                                            unsigned pixel_count) {
    unsigned pixel = 0;
#ifdef __ARM_NEON
    for (; pixel + 16 <= pixel_count; pixel += 16) {
        uint8x16x3_t channels = vld3q_u8(src + pixel * 3);
        const uint8x16_t red = channels.val[0];
        channels.val[0] = channels.val[2]; channels.val[2] = red;
        vst3q_u8(dst + pixel * 3, channels);
    }
#endif
    for (; pixel < pixel_count; ++pixel) {
        dst[pixel * 3] = src[pixel * 3 + 2];
        dst[pixel * 3 + 1] = src[pixel * 3 + 1];
        dst[pixel * 3 + 2] = src[pixel * 3];
    }
}
#endif
