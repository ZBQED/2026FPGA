/* yf2_preproc.h —— 真机帧 → int8 网络输入 预处理(缩放 + 量化)。
 *
 * 输入: VDMA S2MM 帧缓存中的 RGB888 帧(BGR 字节序, 见下)。
 *   DDR 像素字节序: mem[3i+0]=B, mem[3i+1]=G, mem[3i+2]=R ——
 *   依据: ov5640_capture_data.v 输出 vid_data={R,G,B}(bit23..16=R),
 *   AXI 总线小端写入 → 最低字节 = tdata[7:0] = B。与 cv2.imread 的 BGR
 *   布局一致, 通道序无需交换。
 * 输出: 352x352x3 int8 NHWC(BGR 通道序, 与 yf2_net.h 输入布局一致)。
 *
 * 缩放算法 = cv2.INTER_LINEAR 8U 定点实现的逐位复现
 * (从 OpenCV 5.x resize.cpp 还原, 221 张校准图 + 真机帧逐位验证,
 *  见 sw/ref/cv2_resize_probe.py 与 preproc_verify.log):
 *   fx = (float)((dx+0.5)*scale - 0.5), scale = 1./((double)dst/src)
 *   sx = floorf(fx); fx -= sx
 *   水平边界夹取: sx<0 → fx=0,sx=0; sx>=sw-1 → fx=0,sx=sw-1
 *   a0 = rintf((1-fx)*2048), a1 = rintf(fx*2048)      (cvRound 半偶舍入)
 *   水平(精确 int): h = S[sx*3+c]*a0 + S[(sx+1)*3+c]*a1
 *   垂直: fy/sy 不夹取(OpenCV 垂直无边界 clamp), 行索引 clip 到 [0,h-1]:
 *     b0 = rintf((1-fy)*2048), b1 = rintf(fy*2048)
 *     out = ((b0*(h0>>4))>>16 + (b1*(h1>>4))>>16 + 2) >> 2   (逐级截断)
 * 量化(与 ptq_export/verify_ref 输入路径逐运算一致):
 *   xn = (float)px / 255.0f
 *   q  = rintf(xn / s_in) + zp_in, clip [-128,127]
 *
 * 本模块无 malloc/文件 IO; 内部静态工作区 ~8.5KB(非可重入, 裸机单线程使用)。
 */
#ifndef YF2_PREPROC_H_
#define YF2_PREPROC_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifndef YF2_PREPROC_IN_W
#define YF2_PREPROC_IN_W 352
#endif
#ifndef YF2_PREPROC_IN_H
#define YF2_PREPROC_IN_H 352
#endif
#define YF2_PREPROC_IN_C 3

/* 主入口: BGR888 帧(fw*fh*3 字节) → int8 NHWC 352x352x3。
 * s_in/zp_in 取自 yf2_net.h 输入层(YF2_LAYERS[0].s_in / zp_in),
 * 由调用方传入以保持本模块与网络表解耦。
 * 返回 0 成功; -1 参数非法。 */
int yf2_preproc_bgr888_to_q(const uint8_t *frame, int fw, int fh,
                            float s_in, int32_t zp_in,
                            int8_t *out_q /* [352*352*3] */);

/* 调试口: 同上, 额外导出量化前的 uint8 缩放结果(352*352*3, BGR),
 * 用于 PC 端与 cv2.resize 逐位比对。可为 NULL。 */
int yf2_preproc_bgr888_to_q_dbg(const uint8_t *frame, int fw, int fh,
                                float s_in, int32_t zp_in,
                                int8_t *out_q, uint8_t *dbg_u8);

#ifdef __cplusplus
}
#endif

#endif /* YF2_PREPROC_H_ */
