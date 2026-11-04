#pragma once
#include <stdint.h>
enum {KPI8_MAGIC=0x3849504bU,KPI8_ABI=2,KPI8_CONFIG_WORDS=32};
enum {KPI8_CONV=0,KPI8_DEPTHWISE=1,KPI8_OUT_ACC32=0,KPI8_OUT_INT8=1,KPI8_OUT_PRELU_LUT=2};
enum {KPI8_OK=0,KPI8_BAD_ABI=1,KPI8_BAD_CONFIG=2,KPI8_BAD_CAPACITY=3,KPI8_UNSUPPORTED=4};
// NHWC int8 input, OHWI/1HWCO int8 weight; RAW mode0 is unchanged.
// New explicitly selected mode1: signed int32 bias/M/shift/reserved=0 perOC,
// 16B each, M>=0, shift[-31,0]. Original TFLite Q31 two-rounding arithmetic;
// DW5x5 second divide uses deployed VRSHL negative-half rule. cfg17 outputzero,
// cfg18/19 int8 activation clamp, cfg23 >=2*CO uint64 parameter words.
// Old driver must continue rejecting mode1; new capability needs explicit host
// policy/driver review. No service or firmware switch is part of this source.
extern "C" uint32_t keypoint_conv_i8(const uint64_t*,const uint64_t*,const uint64_t*,uint64_t*,const uint64_t*);

// Explicit extension: mode2 uses params C*32 u64 table words, no weights.
// mode1 with cfg24=1 fuses PReLU after original requant/clamp: C<=256,
// params original 2*C u64 followed by C*32 LUT words; cfg23=34*C.
// cfg24=0 preserves original mode0/mode1. cfg25..31 always zero.
