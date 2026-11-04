#ifndef FIXED_HAND_MEAN_INTEGER_H
#define FIXED_HAND_MEAN_INTEGER_H
#include <atomic>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/interpreter.h"
#include "tensorflow/lite/builtin_ops.h"
namespace hand_mean_integer {
#include "hand_mean_sum_lut.h"
static std::atomic<uint32_t> mean_calls{0};
static uint32_t Bits(const float& value){uint32_t bits;std::memcpy(&bits,&value,4);return bits;}
// Deliberately noinline so the actual ARM hot function can be disassembled.
__attribute__((noinline)) static TfLiteStatus Eval(TfLiteContext* c,TfLiteNode* n){
  if(!c||!n||!n->inputs||n->inputs->size!=2||!n->outputs||n->outputs->size!=1)return kTfLiteError;
  const TfLiteTensor& x=c->tensors[n->inputs->data[0]];TfLiteTensor& y=c->tensors[n->outputs->data[0]];
  if(x.type!=kTfLiteInt8||y.type!=kTfLiteInt8||x.bytes!=32928||y.bytes!=672||!x.data.int8||!y.data.int8)return kTfLiteError;
  for(int channel=0;channel<672;++channel){
    int32_t sum=0;
    for(int position=0;position<49;++position)sum+=x.data.int8[position*672+channel];
    if(sum<kMeanSumMinimum||sum>kMeanSumMaximum)return kTfLiteError;
    y.data.int8[channel]=kHandMeanSumLut[sum-kMeanSumMinimum];
  }
  mean_calls.fetch_add(1,std::memory_order_relaxed);return kTfLiteOk;
}
static void Install(tflite::Interpreter& interpreter){
  auto* entry=interpreter.node_and_registration(58);
  if(!entry||entry->second.builtin_code!=kTfLiteBuiltinMean)throw std::runtime_error("Fixed Hand58 MEAN required");
  const auto& node=entry->first;
  if(!node.inputs||node.inputs->size!=2||node.inputs->data[0]!=161||node.inputs->data[1]!=1||!node.outputs||node.outputs->size!=1||node.outputs->data[0]!=162)
    throw std::runtime_error("Fixed Hand58 tensor IDs required");
  auto* params=static_cast<const TfLiteReducerParams*>(node.builtin_data);
  auto* x=interpreter.tensor(161);auto* y=interpreter.tensor(162);auto* axis=interpreter.tensor(1);
  if(!params||params->keep_dims||!x||!y||!axis||x->type!=kTfLiteInt8||y->type!=kTfLiteInt8||axis->type!=kTfLiteInt32||axis->bytes!=8||
     !axis->data.i32||axis->data.i32[0]!=1||axis->data.i32[1]!=2||
     !x->dims||x->dims->size!=4||x->dims->data[0]!=1||x->dims->data[1]!=7||x->dims->data[2]!=7||x->dims->data[3]!=672||
     !y->dims||y->dims->size!=2||y->dims->data[0]!=1||y->dims->data[1]!=672||
     x->params.zero_point!=-128||y->params.zero_point!=-128||Bits(x->params.scale)!=kMeanInputScaleBits||Bits(y->params.scale)!=kMeanOutputScaleBits)
    throw std::runtime_error("Fixed Hand58 shape/axis/scale/zp contract differs");
  const_cast<TfLiteRegistration&>(entry->second).invoke=Eval;
}
}
#endif
