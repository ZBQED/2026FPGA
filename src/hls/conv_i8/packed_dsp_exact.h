// Next-core arithmetic candidate only. No runtime/device/firmware mutation.
// One 25x9 DSP produces two exact signed9 x signed8 products sharing x.
#pragma once
#ifdef GQ_PACKED_HOST_TEST
#include <cstdint>
struct GQProducts {int32_t first,second;};
struct GQProductsA11 {int32_t first,second;};
// Signed11 x two signed7. Full two's-complement ranges are supported;
// Body's symmetric calibration clips are a strict subset of these ranges.
inline GQProductsA11 gq_a11_w7_pair(int x,int w0,int w1) {
  const int64_t packed=(w0&127)+int64_t(w1)*262144;
  const int64_t product=packed*x;
  const int32_t high=int32_t((product+131072)>>18);
  const int32_t low=int32_t(product-int64_t(high)*262144)-(w0<0?128*x:0);
  return {low,high};
}
inline GQProducts gq_conv_pair(int x,int w0,int w1) {
  const int64_t a=(w0&255)+int64_t(w1)*131072;
  const int64_t product=a*x;
  const int32_t hi=int32_t((product+65536)>>17);
  const int32_t low=int32_t(product-int64_t(hi)*131072)-(w0<0?256*x:0);
  return {low,hi};
}
inline GQProducts gq_dw_pixels(int q0,int q1,int weight,int zx) {
  const int64_t a=(q0&255)+int64_t(q1)*65536;
  const int64_t product=a*weight;
  const int32_t hi=int32_t((product+32768)>>16);
  const int32_t lo=int32_t(product-int64_t(hi)*65536)-(q0<0?256*weight:0);
  const int32_t correction=zx*weight;
  return {lo-correction,hi-correction};
}
#else
#include <ap_int.h>
struct GQProducts {ap_int<17> first,second;};
// +65536 at x=-1024,w=-64 needs18 signed bits even though x*w is11x7.
struct GQProductsA11 {ap_int<18> first,second;};
inline GQProductsA11 gq_a11_w7_pair(ap_int<11> x,ap_int<7> w0,ap_int<7> w1) {
#pragma HLS INLINE
  ap_int<25> packed=(ap_int<25>(w1)<<18)+ap_uint<7>(w0);
  ap_int<36> product=packed*x;
#pragma HLS BIND_OP variable=product op=mul impl=dsp latency=3
  ap_int<18> high=(product+ap_int<36>(131072))>>18;
  ap_int<19> low=product-(ap_int<36>(high)<<18);
  if(w0<0)low-=ap_int<19>(x)<<7;
  return {ap_int<18>(low),high};
}
inline GQProducts gq_conv_pair(ap_int<9> x,ap_int<8> w0,ap_int<8> w1) {
#pragma HLS INLINE
  ap_int<25> packed=(ap_int<25>(w1)<<17)+ap_uint<8>(w0);
  ap_int<34> product=packed*x;
#pragma HLS BIND_OP variable=product op=mul impl=dsp latency=3
  ap_int<17> high=(product+ap_int<34>(65536))>>17;
  ap_int<18> low=product-(ap_int<34>(high)<<17);
  if(w0<0)low-=ap_int<18>(x)<<8;
  return {ap_int<17>(low),high};
}
// Depthwise shares weight between adjacent spatial pixels. Qx remains signed8;
// move -zx*weight to an exact per-pair correction so packed operands fit25x18.
inline GQProducts gq_dw_pixels(ap_int<8> q0,ap_int<8> q1,ap_int<8> w,ap_int<9> zx) {
#pragma HLS INLINE
  ap_int<24> packed=(ap_int<24>(q1)<<16)+ap_uint<8>(q0);
  ap_int<32> product=packed*w;
#pragma HLS BIND_OP variable=product op=mul impl=dsp latency=3
  ap_int<16> high=(product+ap_int<32>(32768))>>16;
  ap_int<17> low=product-(ap_int<32>(high)<<16);
  if(q0<0)low-=ap_int<17>(w)<<8;
  ap_int<17> correction=zx*w;
#pragma HLS BIND_OP variable=correction op=mul impl=fabric latency=2
  return {ap_int<17>(low-correction),ap_int<17>(high-correction)};
}
#endif
