/* Host entry point around A's unchanged integer reference operators/weights.
 * This is CPU inference, not an FPGA accelerator or a replacement model. */
#include "yf2_core.h"
#include "yf2_preproc.h"
#include <stdlib.h>
#include <math.h>

void network_video_service(void) {}

__declspec(dllexport) int a_yf2_detect(const unsigned char *bgr, int width, int height, double *out, int capacity) {
    static int8_t *workspace;
    static int8_t input[YF2_IN_W * YF2_IN_H * 3];
    static float feat0[12 * 12 * YF2_DEC_FEAT_CH], feat1[6 * 6 * YF2_DEC_FEAT_CH];
    static yf2_box_t raw[2048], keep[32];
    yf2_head_scale_in_t s16, s32;
    if (!bgr || !out || width <= 0 || height <= 0 || capacity < 1) return -1;
    if (!workspace) workspace = calloc(1, YF2_BUF_TOTAL);
    if (!workspace) return -1;
    if (yf2_preproc_bgr888_to_q(bgr, width, height, YF2_LAYERS[0].s_in, YF2_LAYERS[0].zp_in, input)) return -1;
    yf2_core_run(workspace, input);
    yf2_core_head_scale(workspace, feat0, feat1, &s16, &s32);
    int n = yf2_decode_scale_int8(&s16, yf2_dec_anchors, 0.4, feat0, raw, 2048);
    n += yf2_decode_scale_int8(&s32, yf2_dec_anchors, 0.4, feat1, raw + n, 2048 - n);
    n = yf2_nms(raw, n, 0.45, keep, 32);
    int valid = 0;
    for (int i = 0; i < n && valid < capacity; ++i) {
        const yf2_box_t b = keep[i];
        if (!isfinite(b.score) || b.score < 0.4 || b.score > 1.0 ||
            !isfinite(b.x1) || !isfinite(b.x2) || !isfinite(b.y1) || !isfinite(b.y2) ||
            b.x2 - b.x1 < 4 || b.y2 - b.y1 < 4) continue;
        out[valid * 5] = fmax(0, b.x1) * 800.0 / YF2_IN_W;
        out[valid * 5 + 1] = fmax(0, b.y1) * 480.0 / YF2_IN_H;
        out[valid * 5 + 2] = fmin(YF2_IN_W - 1, b.x2) * 800.0 / YF2_IN_W;
        out[valid * 5 + 3] = fmin(YF2_IN_H - 1, b.y2) * 480.0 / YF2_IN_H;
        out[valid * 5 + 4] = b.score;
        ++valid;
    }
    return valid;
}
