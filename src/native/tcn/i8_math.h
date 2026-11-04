#ifndef GESTURE_I8_MATH_H
#define GESTURE_I8_MATH_H
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>
#include "gesture_pl_i8_abi.h"
namespace gesture_i8_pruned {
using Config=std::array<uint32_t,32>;
struct Span { size_t input=0,weights=0,output=0; std::array<uint64_t,4> bytes{}; };
struct ActivationRange { double scale=0,lo=0,hi=0; int zero=0; uint64_t clipped=0; };
struct Weights { std::vector<int8_t> values; std::vector<double> scales; };
struct BalancedWeights { std::vector<int8_t> high,low; std::vector<double> scales; };
Span Validate(const Config& config);
ActivationRange QuantizeInput(const float *input,size_t count,std::vector<int8_t>* result);
Weights QuantizeWeights(const float *input,const Config& config);
void BalancedSplit(int32_t q,int8_t* high,int8_t* low);
ActivationRange QuantizeInput16(const float* input,size_t count,std::vector<int8_t>* high,std::vector<int8_t>* low);
BalancedWeights QuantizeWeights16(const float* input,const Config& config);
void Dequantize(const int32_t* input,size_t count,int channels,double sx,const double *sw,
                const float *bias,int activation,float *output);
void Dequantize64(const int64_t* input,size_t count,int channels,double sx,const double* sw,
                  const float* bias,int activation,float* output);
#ifdef GPI8_MATH_TEST_ONLY
void RawReference(const int8_t *input,const int8_t *weights,const Config& config,int32_t *output);
#endif
}
#endif
