/* yf2_core.c —— Yolo-FastestV2 int8 整网(裸机适配版)。
 *
 * 源出 sw/ref/yf2_ref.c(ALL EXACT 权威版本): 层算式逐字保留, 仅做机械适配:
 *   - BUF(malloc) → 调用方传入的工作区基址(板端 = 固定 DDR 0x02200000)
 *   - 去 main()/文件 IO/逐层 dump/调试监视
 *   - 头部解码移交给 yf2_decode.c(经 PC 验证与 python 逐位一致)
 * 若改动任何算式, 必须先改 sw/ref/yf2_ref.c 并重跑 verify_ref.py 保持 ALL EXACT。
 */
#include "yf2_core.h"
#include "yf2_weights.h"
#include "yf2_wptr.h"

#if defined(__arm__) && defined(YF2_BAREMETAL_HLS)
#include "yf2_hls.h"
#define YF2_M5_HLS 1 /* M5: conv 下 PL(仅板端编译; PC 数值权威路径不受影响) */
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#ifdef __ARM_NEON
#include <arm_neon.h>
#endif

/* ---------------- 以下算式与 yf2_ref.c 逐字一致 ---------------- */

static int32_t requant(int64_t acc, int32_t M, int32_t sh,
                       int32_t zp, int relu)
{
    int64_t q = (acc * (int64_t)M + ((int64_t)1 << (sh - 1))) >> sh;
    q += zp;
    if (relu && q < zp)
        q = zp;
    if (q < -128)
        q = -128;
    if (q > 127)
        q = 127;
    return (int32_t)q;
}

#include "yf2_fpga.inc"

static void conv2d(int8_t *BUF, const yf2_layer_t *L)
{
    const int8_t *W = YF2_W_PTRS[L->widx];
    const int32_t *B = YF2_BIAS_PTRS[L->widx];
    const int32_t *M = YF2_M_PTRS[L->widx];
    const int32_t *SH = YF2_SHIFT_PTRS[L->widx];
    const int8_t *in = BUF + L->in_off;
    int8_t *out = BUF + L->out_off;
    int K = L->k, ST = L->stride, PD = L->pad;
    int dw = (L->type == 2);

    for (int oy = 0; oy < L->h_out; oy++) {
        for (int ox = 0; ox < L->w_out; ox++) {
            for (int o = 0; o < L->c_out; o++) {
                int64_t acc = B[o];
                if (!dw) {
                    for (int ci = 0; ci < L->c_in; ci++) {
                        for (int ky = 0; ky < K; ky++) {
                            int iy = oy * ST - PD + ky;
                            for (int kx = 0; kx < K; kx++) {
                                int ix = ox * ST - PD + kx;
                                /* 越界 = zp_in(real 0), 与 bias_adj 校正一致 */
                                int8_t v =
                                    (iy < 0 || iy >= L->h_in || ix < 0 ||
                                     ix >= L->w_in)
                                        ? (int8_t)L->zp_in
                                        : in[(iy * L->w_in + ix) * L->c_in +
                                             ci];
                                int8_t wq = W[((o * L->c_in + ci) * K + ky) *
                                                  K + kx];
                                acc += (int64_t)v * wq;
                            }
                        }
                    }
                } else { /* depthwise: 输入通道 = 输出通道 */
                    for (int ky = 0; ky < K; ky++) {
                        int iy = oy * ST - PD + ky;
                        for (int kx = 0; kx < K; kx++) {
                            int ix = ox * ST - PD + kx;
                            int8_t v =
                                (iy < 0 || iy >= L->h_in || ix < 0 ||
                                 ix >= L->w_in)
                                    ? (int8_t)L->zp_in
                                    : in[(iy * L->w_in + ix) * L->c_in + o];
                            int8_t wq = W[(o * K + ky) * K + kx];
                            acc += (int64_t)v * wq;
                        }
                    }
                }
                out[(oy * L->w_out + ox) * L->c_out + o] =
                    (int8_t)requant(acc, M[o], SH[o], L->zp_out, L->relu);
            }
        }
    }
}

static void maxpool(int8_t *BUF, const yf2_layer_t *L)
{
    const int8_t *in = BUF + L->in_off;
    int8_t *out = BUF + L->out_off;
    int K = L->k, ST = L->stride;
#ifdef __ARM_NEON
    if ((L->c_in & 7) == 0) {
        for (int oy = 0; oy < L->h_out; oy++) {
            for (int ox = 0; ox < L->w_out; ox++) {
                for (int c = 0; c < L->c_in; c += 8) {
                    int8x8_t m = vdup_n_s8(-128);
                    for (int ky = 0; ky < K; ky++) {
                        for (int kx = 0; kx < K; kx++) {
                            int iy = oy * ST + ky, ix = ox * ST + kx;
                            int8x8_t v = iy >= L->h_in || ix >= L->w_in
                                ? vdup_n_s8((int8_t)L->zp_in)
                                : vld1_s8(in + (iy * L->w_in + ix) * L->c_in + c);
                            m = vmax_s8(m, v);
                        }
                    }
                    vst1_s8(out + (oy * L->w_out + ox) * L->c_out + c, m);
                }
            }
        }
        return;
    }
#endif
    /* SAME-upper: 顶/左不补, 底/右补 zp_in(real 0) */
    for (int oy = 0; oy < L->h_out; oy++) {
        for (int ox = 0; ox < L->w_out; ox++) {
            for (int c = 0; c < L->c_in; c++) {
                int m = -128;
                for (int ky = 0; ky < K; ky++) {
                    int iy = oy * ST + ky;
                    for (int kx = 0; kx < K; kx++) {
                        int ix = ox * ST + kx;
                        int8_t v = (iy >= L->h_in || ix >= L->w_in)
                                       ? (int8_t)L->zp_in
                                       : in[(iy * L->w_in + ix) *
                                                L->c_in + c];
                        if (v > m)
                            m = v;
                    }
                }
                out[(oy * L->w_out + ox) * L->c_out + c] = (int8_t)m;
            }
        }
    }
}

static void shuffle_ch(int8_t *BUF, const yf2_layer_t *L)
{
    const int8_t *in = BUF + L->in_off;
    int8_t *out = BUF + L->out_off;
    int groups = L->k, channels = L->c_in, half = channels / groups;
    for (int px = 0; px < L->h_in * L->w_in; ++px) {
        const int8_t *a = in + px * channels;
        int8_t *b = out + px * channels;
#ifdef __ARM_NEON
        if (groups == 2) {
            int c = 0;
            for (; c + 16 <= half; c += 16) {
                int8x16x2_t v = vld2q_s8(a + c * 2);
                vst1q_s8(b + c, v.val[0]);
                vst1q_s8(b + half + c, v.val[1]);
            }
            for (; c < half; ++c) { b[c] = a[c*2]; b[half+c] = a[c*2+1]; }
            continue;
        }
#endif
        for (int group = 0; group < groups; ++group)
            for (int c = 0; c < half; ++c) b[group*half+c] = a[c*groups+group];
    }
}

static void slice_copy(int8_t *BUF, const yf2_layer_t *L)
{
    /* NHWC 通道切半: out0 = in[0:C/2], out2 = in[C/2:C] (逐像素跨步) */
    const int8_t *in = BUF + L->in_off;
    int8_t *o0 = BUF + L->out_off;
    int8_t *o1 = BUF + L->out2_off;
    int ch = L->c_in / 2;
    int n = L->h_in * L->w_in;
    for (int px = 0; px < n; px++) {
        for (int c = 0; c < ch; c++) {
            o0[px * ch + c] = in[px * L->c_in + c];
            if (o1)
                o1[px * ch + c] = in[px * L->c_in + ch + c];
        }
    }
}

static void interp2x(int8_t *BUF, const yf2_layer_t *L)
{
    const int8_t *in = BUF + L->in_off;
    int8_t *out = BUF + L->out_off;
    int sc = L->k;
    for (int y = 0; y < L->h_out; y++)
        for (int x = 0; x < L->w_out; x++)
            memcpy(out + ((y * L->w_out + x) * L->c_out),
                   in + (((y / sc) * L->w_in + (x / sc)) * L->c_in),
                   L->c_in);
}

static void concat_requant(int8_t *BUF, const yf2_layer_t *L)
{
    int8_t lut0[256], lut1[256];
    for (int v = -128; v < 128; v++) {
        float f0 = ((float)v - (float)L->zp_in) * L->s_in;
        float f1 = ((float)v - (float)L->zp_in2) * L->s_in2;
        int q0 = (int)rintf(f0 / L->s_out) + L->zp_out;
        int q1 = (int)rintf(f1 / L->s_out) + L->zp_out;
        lut0[v + 128] = (int8_t)(q0 < -128 ? -128 : q0 > 127 ? 127 : q0);
        lut1[v + 128] = (int8_t)(q1 < -128 ? -128 : q1 > 127 ? 127 : q1);
    }
    const int8_t *in0 = BUF + L->in_off;
    const int8_t *in1 = BUF + L->in2_off;
    int8_t *out = BUF + L->out_off;
    int c0 = L->c_in;         /* 支路 0 通道数 */
    int c1 = L->c_out - c0;   /* 支路 1 通道数 */
    int n = L->h_out * L->w_out;
    for (int px = 0; px < n; px++) {
        for (int c = 0; c < c0; c++) {
            /* 与 numpy float32 弱标量提升语义一致 */
            out[px * L->c_out + c] = lut0[(int)in0[px * c0 + c] + 128];
        }
        for (int c = 0; c < c1; c++) {
            out[px * L->c_out + c0 + c] = lut1[(int)in1[px * c1 + c] + 128];
        }
    }
}

const yf2_layer_t *yf2_core_layer(const char *name)
{
    for (int i = 0; i < YF2_N_LAYERS; i++)
        if (strcmp(YF2_LAYERS[i].name, name) == 0)
            return &YF2_LAYERS[i];
    return NULL;
}

/* ---------------- 裸机入口 ---------------- */

int yf2_core_run(int8_t *ws, const int8_t *input_q)
{
    int8_t *BUF = ws;
    memcpy(BUF + YF2_IN_OFF, input_q,
           (size_t)YF2_IN_H * YF2_IN_W * YF2_IN_C);

    for (int i = 0; i < YF2_N_LAYERS; i++) {
        const yf2_layer_t *L = &YF2_LAYERS[i];
        switch (L->type) {
        case 1:
        case 2:
#ifdef YF2_M5_HLS
            /* M5: conv/depthwise 优先走 HLS IP, 超时/异常自动回退 PS conv2d
             * (数值逐位一致, 切换只影响耗时) */
            if (yf2_hls_conv(L, BUF,
                             YF2_W_PTRS[L->widx], YF2_BIAS_PTRS[L->widx],
                             YF2_M_PTRS[L->widx], YF2_SHIFT_PTRS[L->widx]) == 0)
                break;
#endif
            if (yp_enabled) { int rc=yf2_fpga_conv(BUF,L); if(rc)return rc; }
            else conv2d(BUF, L);
            break;
        case 3:
            maxpool(BUF, L);
            break;
        case 4:
            concat_requant(BUF, L);
            break;
        case 5:
            shuffle_ch(BUF, L);
            break;
        case 7:
            interp2x(BUF, L);
            break;
        case 6:
            slice_copy(BUF, L);
            break;
        case 8: /* split/permute/softmax: 别名或解码端处理 */
        default:
            break;
        }
    }
    return 0;
}

void yf2_core_head_scale(const int8_t *ws, float *feat0, float *feat1,
                         yf2_head_scale_in_t *s16, yf2_head_scale_in_t *s32)
{
    const yf2_layer_t *lb1 = yf2_core_layer("Conv_256");
    const yf2_layer_t *lo1 = yf2_core_layer("Conv_257");
    const yf2_layer_t *lc1 = yf2_core_layer("Conv_258");
    const yf2_layer_t *lb2 = yf2_core_layer("Conv_259");
    const yf2_layer_t *lo2 = yf2_core_layer("Conv_260");
    const yf2_layer_t *lc2 = yf2_core_layer("Conv_261");

    s16->H = lb1->h_out; s16->W = lb1->w_out; s16->stride = 16;
    s16->box_q = ws + lb1->out_off;
    s16->obj_q = ws + lo1->out_off;
    s16->cls_q = ws + lc1->out_off;
    s16->box_s = lb1->s_out; s16->box_zp = lb1->zp_out;
    s16->obj_s = lo1->s_out; s16->obj_zp = lo1->zp_out;
    s16->cls_s = lc1->s_out; s16->cls_zp = lc1->zp_out;

    s32->H = lb2->h_out; s32->W = lb2->w_out; s32->stride = 32;
    s32->box_q = ws + lb2->out_off;
    s32->obj_q = ws + lo2->out_off;
    s32->cls_q = ws + lc2->out_off;
    s32->box_s = lb2->s_out; s32->box_zp = lb2->zp_out;
    s32->obj_s = lo2->s_out; s32->obj_zp = lo2->zp_out;
    s32->cls_s = lc2->s_out; s32->cls_zp = lc2->zp_out;
    (void)feat0;
    (void)feat1;
}
