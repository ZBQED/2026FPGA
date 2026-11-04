#ifndef FIXED_PALM_RESIZE_NEON_H
#define FIXED_PALM_RESIZE_NEON_H
#include <arm_neon.h>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/interpreter.h"
#include "tensorflow/lite/builtin_ops.h"
namespace palm_resize_integer {
static std::atomic<uint32_t> resize85_calls{0},resize101_calls{0};
struct Axis {int lo,hi,wl,wh;};
static Axis Axis2x(int p,int n){
  // Original AB10 coordinate is512*p-256. All weights divisible by256.
  const int u=2*p-1;int lo=u/4;if(lo<0)lo=0;int hi=(u+3)/4;if(hi>=n)hi=n-1;
  if(lo==hi)return {lo,hi,4,0}; // Identical edge pointers cancel the signed weights exactly.
  const int f=u-lo*4;return {lo,hi,4-f,f};
}
static int16x8_t Round16(int16x8_t sum){
  // Exact original signed ties-away division: (v+(v>0?8:-8))/16,
  // implemented without negative arithmetic-shift rounding ambiguity.
  int16x8_t mag=vshrq_n_s16(vaddq_s16(vabsq_s16(sum),vdupq_n_s16(8)),4);
  return vbslq_s16(vcltq_s16(sum,vdupq_n_s16(0)),vnegq_s16(mag),mag);
}
__attribute__((noinline)) static TfLiteStatus Eval(TfLiteContext* ctx,TfLiteNode* node){
  if(!ctx||!node||!node->inputs||node->inputs->size!=2||!node->outputs||node->outputs->size!=1)return kTfLiteError;
  const int source=node->inputs->data[0],dest=node->outputs->data[0];
  const int n=(source==205&&dest==206)?6:(source==217&&dest==222)?12:0;
  if(!n)return kTfLiteError;
  const auto& in=ctx->tensors[source];auto& out=ctx->tensors[dest];
  if(in.type!=kTfLiteInt8||out.type!=kTfLiteInt8||in.bytes!=size_t(n*n*256)||out.bytes!=size_t(n*n*1024)||!in.data.int8||!out.data.int8)return kTfLiteError;
  const int width=n*2;
  for(int y=0;y<width;++y){const Axis ay=Axis2x(y,n);
    for(int x=0;x<width;++x){const Axis ax=Axis2x(x,n);
      const int8_t* p00=in.data.int8+(ay.lo*n+ax.lo)*256;
      const int8_t* p01=in.data.int8+(ay.lo*n+ax.hi)*256;
      const int8_t* p10=in.data.int8+(ay.hi*n+ax.lo)*256;
      const int8_t* p11=in.data.int8+(ay.hi*n+ax.hi)*256;
      int8_t* target=out.data.int8+(y*width+x)*256;
      const int16_t w00=ay.wl*ax.wl,w01=ay.wl*ax.wh,w10=ay.wh*ax.wl,w11=ay.wh*ax.wh;
      for(int c=0;c<256;c+=16){
        int8x16_t a=vld1q_s8(p00+c),b=vld1q_s8(p01+c),d=vld1q_s8(p10+c),e=vld1q_s8(p11+c);
        int16x8_t lo=vmulq_n_s16(vmovl_s8(vget_low_s8(a)),w00);
        lo=vmlaq_n_s16(lo,vmovl_s8(vget_low_s8(b)),w01);lo=vmlaq_n_s16(lo,vmovl_s8(vget_low_s8(d)),w10);lo=vmlaq_n_s16(lo,vmovl_s8(vget_low_s8(e)),w11);
        int16x8_t hi=vmulq_n_s16(vmovl_s8(vget_high_s8(a)),w00);
        hi=vmlaq_n_s16(hi,vmovl_s8(vget_high_s8(b)),w01);hi=vmlaq_n_s16(hi,vmovl_s8(vget_high_s8(d)),w10);hi=vmlaq_n_s16(hi,vmovl_s8(vget_high_s8(e)),w11);
        vst1q_s8(target+c,vcombine_s8(vqmovn_s16(Round16(lo)),vqmovn_s16(Round16(hi))));
      }
    }
  }
  (n==6?resize85_calls:resize101_calls).fetch_add(1,std::memory_order_relaxed);return kTfLiteOk;
}
static void Install(tflite::Interpreter& model){
  for(int id:{85,101}){
    auto* entry=model.node_and_registration(id);const int n=id==85?6:12;const int source=id==85?205:217,dest=id==85?206:222,axis=id==85?4:3;
    if(!entry||entry->second.builtin_code!=kTfLiteBuiltinResizeBilinear)throw std::runtime_error("Fixed Palm Resize node required");
    const auto& node=entry->first;auto* opts=static_cast<const TfLiteResizeBilinearParams*>(node.builtin_data);
    auto* x=model.tensor(source);auto* y=model.tensor(dest);auto* a=model.tensor(axis);
    uint32_t xs=0,ys=0;if(x&&y){std::memcpy(&xs,&x->params.scale,4);std::memcpy(&ys,&y->params.scale,4);}
    if(!opts||opts->align_corners||!opts->half_pixel_centers||!node.inputs||node.inputs->size!=2||node.inputs->data[0]!=source||node.inputs->data[1]!=axis||!node.outputs||node.outputs->size!=1||node.outputs->data[0]!=dest||
      !x||!y||!a||x->type!=kTfLiteInt8||y->type!=kTfLiteInt8||a->type!=kTfLiteInt32||a->bytes!=8||!a->data.i32||a->data.i32[0]!=2*n||a->data.i32[1]!=2*n||
      x->bytes!=size_t(n*n*256)||y->bytes!=size_t(n*n*1024)||xs!=ys||x->params.zero_point!=y->params.zero_point)
        throw std::runtime_error("Fixed Palm INT8 half-pixel2x Resize contract differs");
    const_cast<TfLiteRegistration&>(entry->second).invoke=Eval;
  }
}
}
#endif
