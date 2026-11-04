/* yf2_preproc.c —— 实现见 yf2_preproc.h 顶部说明。
 * 数值语义 = cv2.INTER_LINEAR 8U 定点(OpenCV 5.x resize.cpp 逐位还原)
 * + ptq_export.py 输入量化路径, 未经允许不得改动任何算式。 */
#include "yf2_preproc.h"

#include <math.h>
#include <string.h>

/* 每轴系数表: 352 个目的坐标 */
typedef struct {
    int32_t ofs[YF2_PREPROC_IN_W];       /* floor((d+0.5)*scale-0.5) */
    int32_t w0[YF2_PREPROC_IN_W];        /* rint((1-frac)*2048) */
    int32_t w1[YF2_PREPROC_IN_W];        /* rint(frac*2048) */
} yf2_preproc_axis_t;

/* 水平两行 + 垂直合并用的中间缓冲(精确 int, 11-bit 系数域) */
static int32_t hbuf0[YF2_PREPROC_IN_W * YF2_PREPROC_IN_C];
static int32_t hbuf1[YF2_PREPROC_IN_W * YF2_PREPROC_IN_C];

/* 水平语义: 边界夹取(fx=0 且 ofs 归到 0/src-1) —— OpenCV dx 循环原样 */
static void preproc_axis_h(int src_n, int dst_n, yf2_preproc_axis_t *t)
{
    /* OpenCV: double scale = 1./inv_scale_x, inv_scale_x = (double)dst/src */
    double scale = 1.0 / ((double)dst_n / (double)src_n);
    for (int d = 0; d < dst_n; d++) {
        float f = (float)(((double)d + 0.5) * scale - 0.5);
        int32_t s = (int32_t)floorf(f);      /* cvFloor */
        float fr = f - (float)s;             /* float32 域减法 */
        if (s < 0) {
            fr = 0.0f;                       /* cv2: fx=0, sx=0 */
            s = 0;
        }
        if (s >= src_n - 1) {
            fr = 0.0f;                       /* cv2: fx=0, sx=src-1 */
            s = src_n - 1;
        }
        t->ofs[d] = s;
        t->w1[d] = (int32_t)rintf(fr * 2048.0f);          /* cvRound 半偶 */
        t->w0[d] = (int32_t)rintf((1.0f - fr) * 2048.0f);
    }
}

/* 垂直语义: 不夹取(OpenCV dy 循环无边界处理, sy 可为 -1/src_n) ——
 * 行索引由调用方 clip, 权值保持未夹取 frac */
static void preproc_axis_v(int src_n, int dst_n, yf2_preproc_axis_t *t)
{
    double scale = 1.0 / ((double)dst_n / (double)src_n);
    for (int d = 0; d < dst_n; d++) {
        float f = (float)(((double)d + 0.5) * scale - 0.5);
        int32_t s = (int32_t)floorf(f);
        float fr = f - (float)s;
        t->ofs[d] = s;                       /* 未夹取! */
        t->w1[d] = (int32_t)rintf(fr * 2048.0f);
        t->w0[d] = (int32_t)rintf((1.0f - fr) * 2048.0f);
    }
}

static int32_t clipi(int32_t v, int32_t lo, int32_t hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

int yf2_preproc_bgr888_to_q_dbg(const uint8_t *frame, int fw, int fh,
                                float s_in, int32_t zp_in,
                                int8_t *out_q, uint8_t *dbg_u8)
{
    yf2_preproc_axis_t ax, ay;
    if (!frame || !out_q || fw <= 0 || fh <= 0)
        return -1;

    preproc_axis_h(fw, YF2_PREPROC_IN_W, &ax);
    preproc_axis_v(fh, YF2_PREPROC_IN_H, &ay);
    /* Evaluate the exact float rounding once per possible resized byte. */
    int8_t quant[256];
    for (int v = 0; v < 256; v++) {
        float xn = (float)v / 255.0f;
        int32_t q = (int32_t)rintf(xn / s_in) + zp_in;
        quant[v] = (int8_t)clipi(q, -128, 127);
    }

    for (int dy = 0; dy < YF2_PREPROC_IN_H; dy++) {
        /* 垂直两行(行索引 clip, 权值未夹取 —— OpenCV invoker clip(x,0,H)语义) */
        int32_t r0 = clipi(ay.ofs[dy], 0, fh - 1);
        int32_t r1 = clipi(ay.ofs[dy] + 1, 0, fh - 1);
        const uint8_t *row0 = frame + (size_t)r0 * fw * 3;
        const uint8_t *row1 = frame + (size_t)r1 * fw * 3;
        int32_t b0 = ay.w0[dy], b1 = ay.w1[dy];

        /* 水平: 两源行各算一次(精确 int) */
        for (int dx = 0; dx < YF2_PREPROC_IN_W; dx++) {
            int32_t c0 = ax.ofs[dx];         /* 已夹取, 恒在 [0,fw-1] */
            int32_t c1 = clipi(c0 + 1, 0, fw - 1); /* 权值在边界已归零 */
            int32_t wa0 = ax.w0[dx], wa1 = ax.w1[dx];
            int32_t *d0 = hbuf0 + dx * 3;
            int32_t *d1 = hbuf1 + dx * 3;
            const uint8_t *p0 = row0 + (size_t)c0 * 3;
            const uint8_t *q0 = row0 + (size_t)c1 * 3;
            const uint8_t *p1 = row1 + (size_t)c0 * 3;
            const uint8_t *q1 = row1 + (size_t)c1 * 3;
            for (int c = 0; c < 3; c++) {
                d0[c] = p0[c] * wa0 + q0[c] * wa1;
                d1[c] = p1[c] * wa0 + q1[c] * wa1;
            }
        }

        /* 垂直合并 + 量化: out = ((b0*(h0>>4))>>16 + (b1*(h1>>4))>>16 + 2)>>2 */
        int8_t *o = out_q + (size_t)dy * YF2_PREPROC_IN_W * 3;
        uint8_t *u8 = dbg_u8 ? dbg_u8 + (size_t)dy * YF2_PREPROC_IN_W * 3
                             : NULL;
        for (int dx = 0; dx < YF2_PREPROC_IN_W; dx++) {
            const int32_t *g0 = hbuf0 + dx * 3;
            const int32_t *g1 = hbuf1 + dx * 3;
            for (int c = 0; c < 3; c++) {
                int32_t v = ((b0 * (g0[c] >> 4)) >> 16) +
                            ((b1 * (g1[c] >> 4)) >> 16);
                v = (v + 2) >> 2;
                if (v < 0)
                    v = 0;
                else if (v > 255)
                    v = 255;
                if (u8)
                    u8[dx * 3 + c] = (uint8_t)v;
                /* 量化: x=(float)v/255 → rint(x/s_in)+zp, clip —— 与
                 * np.rint(x/s_in) 半偶舍入逐运算一致 */
                o[dx * 3 + c] = quant[v];
            }
        }
    }
    return 0;
}

int yf2_preproc_bgr888_to_q(const uint8_t *frame, int fw, int fh,
                            float s_in, int32_t zp_in, int8_t *out_q)
{
    return yf2_preproc_bgr888_to_q_dbg(frame, fw, fh, s_in, zp_in, out_q,
                                       NULL);
}
