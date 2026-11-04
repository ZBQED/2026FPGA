/* yf2_core.h —— Yolo-FastestV2 整网 int8 推理(PS 路径, M4)。
 *
 * 与 sw/ref/yf2_ref.c 的关系: 本文件是 yf2_ref.c 的裸机适配副本 ——
 * 层算式(requant/conv2d/maxpool/shuffle/slice/interp/concat)逐字保留,
 * 仅做机械适配: malloc→固定 DDR 工作区、去文件 IO/调试监视、main→yf2_core_run。
 * 数值权威版本仍是 sw/ref/yf2_ref.c(verify_ref.py ALL EXACT 的对象)。
 *
 * 工作区布局 = yf2_net.h 的 YF2_LAYERS(in_off/out_off), 总量 YF2_BUF_TOTAL
 * 实时 192 网络占 1,750,972 B。当前内存映射:
 *   0x01000000  帧缓存 x3 (VDMA)
 *   0x03600000  检测快照 800x480x3
 *   0x02100000  int8 输入缓冲 192x192x3
 *   0x02200000  网络工作区 YF2_BUF_TOTAL
 *   0x03200000  PL 输出暂存；权重在 ELF .rodata
 */
#ifndef YF2_CORE_H_
#define YF2_CORE_H_

#include <stdint.h>
#include "yf2_decode.h"
#include "yf2_net.h"

#ifdef __cplusplus
extern "C" {
#endif

/* 固定 DDR 地址(相对 DDR 基址 0x00000000, 见 docs/01_集成方案.md) */
#define YF2_SNAPSHOT_ADDR   0x03600000u
#define YF2_INPUTQ_ADDR     0x02100000u
#define YF2_WORKSPACE_ADDR  0x02200000u
#define YF2_WORKSPACE_BYTES ((uint32_t)YF2_BUF_TOTAL)

/* 整网前向: 把 input_q(YF2_IN_H*YF2_IN_W*3 int8 NHWC) 拷入工作区后逐层执行。
 * ws: 工作区基址(板端传 (int8_t*)YF2_WORKSPACE_ADDR; PC 测试可传 malloc)。
 * 返回 0 成功。 */
int yf2_core_run(int8_t *ws, const int8_t *input_q);

/* 头部两尺度 int8 元信息 → yf2_decode 解码入参(指针指向 ws 内)。
 * feat_scratch0/1: 调用方提供的解码拼装缓冲(22*22*95 / 11*11*95 float)。 */
void yf2_core_head_scale(const int8_t *ws, float *feat0, float *feat1,
                         yf2_head_scale_in_t *s16, yf2_head_scale_in_t *s32);

/* 按 find_layer 语义取层指针(诊断用) */
const yf2_layer_t *yf2_core_layer(const char *name);

#ifdef __cplusplus
}
#endif
#endif /* YF2_CORE_H_ */
