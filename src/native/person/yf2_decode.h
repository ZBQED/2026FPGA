/* yf2_decode.h —— Yolo-FastestV2 头部解码(sigmoid/softmax/anchor 解码/置信度过滤/NMS)。
 *
 * 数值语义与 model/tools/yf2_model.py 的 decode_scale()/nms() 严格一致:
 *   - 特征布局 [H][W][95] = sigmoid(box12) | sigmoid(obj3) | softmax(cls80)
 *     (int8 输入路径由 yf2_decode_head_int8 先做 反量化+sigmoid+softmax 拼装,
 *      与 ptq_export.py golden 段的头部拼装逐运算对应)
 *   - person = 类 0; score = obj[b] * cls[0]; score <= conf 的候选直接丢弃
 *   - anchor 索引: ai = (stride/16 - 1) * 6 + b * 2  (stride 16 → anchors[0..5],
 *     stride 32 → anchors[6..11]; 本网络为 2 个输出尺度)
 *   - 框: bcx = ((2*tx-0.5) + w) * stride; bw = (2*tw)^2 * anchor_w (无边界裁剪)
 *   - NMS: 按分数稳定排序(同分保持原始顺序, 与 python sorted 稳定语义一致),
 *     IoU = inter/union > thr 且同类 → 抑制
 *
 * 精度策略: 拼装/解码的逐像素算术用 float(逐运算舍入, 对应 numpy float32 逐运算),
 * 候选框存储与 NMS 用 double(对应 python boxes 列表中的 float 值, NMS 全程 float64),
 * 因此 float 特征输入路径与 python 参考按位一致; int8 路径仅 expf/softmax 求和
 * 与 numpy 的 transcendental 实现存在 <=1ulp float32 差异(实测见 decode_verify.log)。
 *
 * PC 验证: gcc -O2 -ffp-contract=off 编译, 见 test_decode.c / test_decode_cmp.py。
 * 编译注意: 请勿使用 -ffast-math(破坏 IEEE 逐运算舍入语义);
 * 建议 -ffp-contract=off 禁止 FMA 收缩, 保证与 python 参考逐运算一致。
 */
#ifndef YF2_DECODE_H_
#define YF2_DECODE_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define YF2_DEC_NUM_ANCHOR 3
#define YF2_DEC_NUM_CAT    80
/* 每像素通道数 = box12 | obj3 | cls80 */
#define YF2_DEC_FEAT_CH \
    (4 * YF2_DEC_NUM_ANCHOR + YF2_DEC_NUM_ANCHOR + YF2_DEC_NUM_CAT) /* 95 */

/* 单次 NMS 允许的最大原始候选数(两尺度合计上限:
 * 22*22*3 + 11*11*3 = 1815, 取 2048 留裕量)。yf2_nms 内部据此分配排序缓冲。 */
#define YF2_DEC_MAX_RAW_BOXES 2048

/* Yolo-FastestV2 官方 anchor(w,h 交错), 数值与 yf2_model.ANCHORS 完全一致。
 * 用 double 存储: python 解码中 anchor 以 float64 参与运算。 */
extern const double yf2_dec_anchors[12];

/* 候选框。坐标为 352x352 网络输入域(float64 存储, 与 python 解码输出一致);
 * cate 恒为 0(person), 仅为与 python nms 的类别抑制语义对齐而保留。 */
typedef struct {
    double x1, y1, x2, y2;
    double score;
    int cate;
} yf2_box_t;

/* int8 头部单尺度输入(板端路径): 三个 1x1 卷积分支的 NHWC int8 缓冲 */
typedef struct {
    const int8_t *box_q;  /* [H*W*12] */
    const int8_t *obj_q;  /* [H*W*3]  */
    const int8_t *cls_q;  /* [H*W*80] */
    int H, W;             /* 该尺度网格尺寸 */
    int stride;           /* 16 或 32 */
    float box_s, obj_s, cls_s;      /* 各分支输出 scale */
    int32_t box_zp, obj_zp, cls_zp; /* 各分支输出 zero point */
} yf2_head_scale_in_t;

/* float 特征路径: feat 为 [H][W][95] float32, sigmoid/softmax 已施加
 * (与 golden 的 feat_794.npy / feat_796.npy 同构)。
 * anchors: 12 个 double(w,h 交错), 顺序与 yf2_model.ANCHORS 完全一致
 * (可直接传 yf2_dec_anchors)。
 * conf: 置信度阈值(score <= conf 丢弃)。返回写入 out 的候选数(上限 max_out)。 */
int yf2_decode_scale_feat(const float *feat, int H, int W, int stride,
                          const double *anchors, double conf,
                          yf2_box_t *out, int max_out);

/* int8 板端路径: 反量化 + sigmoid + softmax 拼装 [H][W][95] 后走同一解码核。
 * feat_scratch: 调用方提供 H*W*YF2_DEC_FEAT_CH 个 float 的暂存区
 * (板端放在静态区, 模块内部不做 malloc)。返回候选数(上限 max_out)。 */
int yf2_decode_scale_int8(const yf2_head_scale_in_t *in, const double *anchors,
                          double conf, float *feat_scratch,
                          yf2_box_t *out, int max_out);

/* NMS: 对 boxes 按分数稳定降序排序(就地修改), 顺序扫描保留。
 * iou_thr: 与 python nms(boxes, iou_thr) 一致(默认 0.25)。
 * 返回保留数(写入 keep, 上限 max_keep)。 */
int yf2_nms(yf2_box_t *boxes, int n, double iou_thr,
            yf2_box_t *keep, int max_keep);

#ifdef __cplusplus
}
#endif

#endif /* YF2_DECODE_H_ */
