/* yf2_decode.c —— Yolo-FastestV2 头部解码实现。
 * 数值语义逐行对应 model/tools/yf2_model.py 的 decode_scale()/nms()
 * 与 ptq_export.py golden 段的头部拼装, 见 yf2_decode.h 顶部说明。
 *
 * 实现纪律:
 *  - 逐像素解码算术使用 float(IEEE 单精度逐运算舍入, 对应 numpy float32 逐运算);
 *  - 候选框坐标/分数以 double 存储, NMS 全程 double(对应 python float64);
 *  - 排序使用带原始序号决平的稳定排序, 复现 python sorted 的稳定性;
 *  - 不做任何 malloc/文件 IO, 可直接编入裸机固件。
 */
#include "yf2_decode.h"

#include <math.h>
#include <string.h>

/* Yolo-FastestV2 官方 anchor(与 yf2_model.ANCHORS 一致, double = python float64) */
const double yf2_dec_anchors[12] = {
    12.64, 19.39, 37.88, 51.48, 55.71, 138.31,
    126.91, 78.23, 131.57, 214.55, 279.92, 258.87};

/* ---------------- 内部: 稳定排序(分数降序, 同分按原始顺序) ---------------- */

typedef struct {
    yf2_box_t box;
    int idx; /* 原始顺序, 决平用 */
} sort_item_t;

static void merge_sort_stable(sort_item_t *a, sort_item_t *tmp, int n)
{
    int mid, i, j, k;
    if (n < 2)
        return;
    mid = n / 2;
    merge_sort_stable(a, tmp, mid);
    merge_sort_stable(a + mid, tmp, n - mid);
    i = 0;
    j = mid;
    k = 0;
    while (i < mid && j < n) {
        /* 分数大者优先; 完全相等时原始序号小者优先(= python 稳定排序) */
        if (a[i].box.score > a[j].box.score ||
            (a[i].box.score == a[j].box.score && a[i].idx < a[j].idx))
            tmp[k++] = a[i++];
        else
            tmp[k++] = a[j++];
    }
    while (i < mid)
        tmp[k++] = a[i++];
    while (j < n)
        tmp[k++] = a[j++];
    for (i = 0; i < n; i++)
        a[i] = tmp[i];
}

/* ---------------- 解码核(float 特征路径) ---------------- */

int yf2_decode_scale_feat(const float *feat, int H, int W, int stride,
                          const double *anchors, double conf,
                          yf2_box_t *out, int max_out)
{
    /* python: cls_off = 4*NUM_ANCHOR + NUM_ANCHOR */
    const int cls_off = 4 * YF2_DEC_NUM_ANCHOR + YF2_DEC_NUM_ANCHOR; /* 15 */
    const int anchor_base = (stride / 16 - 1) * YF2_DEC_NUM_ANCHOR * 2;
    int h, w, b, cnt = 0;

    for (h = 0; h < H; h++) {
        for (w = 0; w < W; w++) {
            const float *v = feat + ((long)h * W + w) * YF2_DEC_FEAT_CH;
            for (b = 0; b < YF2_DEC_NUM_ANCHOR; b++) {
                /* python: score = float(obj[b] * cls[0]) —— float32 乘法后升 float64 */
                float s32 = v[cls_off + 0] *
                            v[4 * YF2_DEC_NUM_ANCHOR + b];
                double score = (double)s32;
                double bcx, bcy, bw, bh;
                float t;
                int ai;
                if (score <= conf || cnt >= max_out)
                    continue;
                /* python: float((v[b*4+0]*2.0 - 0.5) + w) * stride
                 *   —— 括号内为 float32 逐运算, float() 后乘 stride 在 float64 */
                t = (v[b * 4 + 0] * 2.0f - 0.5f) + (float)w;
                bcx = (double)t * (double)stride;
                t = (v[b * 4 + 1] * 2.0f - 0.5f) + (float)h;
                bcy = (double)t * (double)stride;
                /* python: float(v[b*4+2]*2.0) ** 2 * anchors[ai]
                 *   —— float32(2v) 升 float64 后平方、乘 anchor 均在 float64 */
                t = v[b * 4 + 2] * 2.0f;
                ai = anchor_base + b * 2;
                bw = (double)t * (double)t * anchors[ai];
                t = v[b * 4 + 3] * 2.0f;
                bh = (double)t * (double)t * anchors[ai + 1];
                out[cnt].x1 = bcx - 0.5 * bw;
                out[cnt].y1 = bcy - 0.5 * bh;
                out[cnt].x2 = bcx + 0.5 * bw;
                out[cnt].y2 = bcy + 0.5 * bh;
                out[cnt].score = score;
                out[cnt].cate = 0; /* person = 类 0 */
                cnt++;
            }
        }
    }
    return cnt;
}

/* ---------------- int8 板端路径: 拼装 float 特征 ---------------- */

int yf2_decode_scale_int8(const yf2_head_scale_in_t *in, const double *anchors,
                          double conf, float *feat_scratch,
                          yf2_box_t *out, int max_out)
{
    const int H = in->H, W = in->W;
    const int n_px = H * W;
    int px, cnt;

    /* 逐像素拼装 [H][W][95] = sigmoid(box12) | sigmoid(obj3) | softmax(cls80),
     * 与 ptq_export.py golden 段 concat([fbox, fobj, fcls], axis=3) 同构 */
    for (px = 0; px < n_px; px++) {
        float *dst = feat_scratch + (long)px * YF2_DEC_FEAT_CH;
        int i;
        /* box12: sigmoid((q - zp) * s), 与 python 1/(1+exp(-x)) 同式 */
        for (i = 0; i < 12; i++) {
            float x = ((float)in->box_q[px * 12 + i] - (float)in->box_zp) *
                      in->box_s;
            dst[i] = 1.0f / (1.0f + expf(-x));
        }
        for (i = 0; i < 3; i++) {
            float x = ((float)in->obj_q[px * 3 + i] - (float)in->obj_zp) *
                      in->obj_s;
            dst[12 + i] = 1.0f / (1.0f + expf(-x));
        }
        {
            /* softmax: 减最大值后指数归一(python softmax 同构) */
            float c80[YF2_DEC_NUM_CAT];
            float cmax = -3.40282347e+38f;
            float esum = 0.0f;
            for (i = 0; i < YF2_DEC_NUM_CAT; i++) {
                float v = ((float)in->cls_q[px * YF2_DEC_NUM_CAT + i] -
                           (float)in->cls_zp) * in->cls_s;
                c80[i] = v;
                if (v > cmax)
                    cmax = v;
            }
            for (i = 0; i < YF2_DEC_NUM_CAT; i++) {
                c80[i] = expf(c80[i] - cmax);
                esum += c80[i];
            }
            for (i = 0; i < YF2_DEC_NUM_CAT; i++)
                dst[15 + i] = c80[i] / esum;
        }
    }

    cnt = yf2_decode_scale_feat(feat_scratch, H, W, in->stride, anchors, conf,
                                out, max_out);
    return cnt;
}

/* ---------------- NMS(与 python nms 逐运算一致) ---------------- */

int yf2_nms(yf2_box_t *boxes, int n, double iou_thr,
            yf2_box_t *keep, int max_keep)
{
    /* 就地稳定排序(分数降序, 同分保持原始顺序 = python sorted 稳定语义) */
    static sort_item_t items[YF2_DEC_MAX_RAW_BOXES];
    static sort_item_t tmp[YF2_DEC_MAX_RAW_BOXES];
    int i, j, m = 0;

    if (n > YF2_DEC_MAX_RAW_BOXES)
        n = YF2_DEC_MAX_RAW_BOXES;
    for (i = 0; i < n; i++) {
        items[i].box = boxes[i];
        items[i].idx = i;
    }
    merge_sort_stable(items, tmp, n);
    for (i = 0; i < n; i++)
        boxes[i] = items[i].box;

    for (i = 0; i < n; i++) {
        int ok = 1;
        for (j = 0; j < m; j++) {
            /* python: ix = max(0.0, min(b[2],k[2]) - max(b[0],k[0])) */
            double ix = fmin(boxes[i].x2, keep[j].x2) -
                        fmax(boxes[i].x1, keep[j].x1);
            double iy = fmin(boxes[i].y2, keep[j].y2) -
                        fmax(boxes[i].y1, keep[j].y1);
            if (ix < 0.0)
                ix = 0.0;
            if (iy < 0.0)
                iy = 0.0;
            {
                double inter = ix * iy;
                double ua = (boxes[i].x2 - boxes[i].x1) *
                                (boxes[i].y2 - boxes[i].y1) +
                            (keep[j].x2 - keep[j].x1) *
                                (keep[j].y2 - keep[j].y1) - inter;
                if (ua > 0.0 && inter / ua > iou_thr &&
                    boxes[i].cate == keep[j].cate) {
                    ok = 0;
                    break;
                }
            }
        }
        if (ok) {
            if (m >= max_keep)
                break;
            keep[m++] = boxes[i];
        }
    }
    return m;
}
