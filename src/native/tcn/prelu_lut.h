#pragma once
// Startup exhausts the deployed A9 INT8 builtin, including its actual rounding.
// Per-frame execution only reads INT8 input, performs byte lookup, writes INT8.
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#include "tensorflow/lite/builtin_ops.h"
#include "tensorflow/lite/core/subgraph.h"
#include "tensorflow/lite/interpreter.h"
namespace gesture_i8_pruned_bridge {
struct PreluLut {
 int id,input,alpha,output,channels;size_t pixels;
 const TfLiteNode* node;
 TfLiteStatus (*original)(TfLiteContext*,TfLiteNode*);
 std::vector<int8_t> lut;
 uint64_t generator_calls=0,generator_ns=0,lookup_calls=0;
};
thread_local std::unordered_map<const TfLiteNode*,PreluLut*> prelu_ops;
inline TfLiteStatus PreluLookup(TfLiteContext* context,TfLiteNode* node){
 auto* p=prelu_ops.at(node);
 const auto* input=&context->tensors[p->input];auto* output=&context->tensors[p->output];
 const auto* x=reinterpret_cast<const uint8_t*>(input->data.int8);auto* y=output->data.int8;
 const int8_t* table=p->lut.data();const int channels=p->channels;
 for(size_t pixel=0;pixel<p->pixels;++pixel){
  // NHWC channel stride is explicit. No division/modulo, scales, float, or MAC.
  for(int channel=0;channel<channels;++channel)y[channel]=table[size_t(channel)*256+x[channel]];
  x+=channels;y+=channels;
 }
 ++p->lookup_calls;return kTfLiteOk;
}
inline std::unique_ptr<PreluLut> MakePreluLut(tflite::Interpreter& interpreter,int id){
 auto* entry=interpreter.node_and_registration(id);const auto& node=entry->first;
 if(entry->second.builtin_code!=kTfLiteBuiltinPrelu||!entry->second.invoke||!node.inputs||node.inputs->size!=2||!node.outputs||node.outputs->size!=1)
  throw std::invalid_argument("Fixed PReLU node/options required");
 const int input=node.inputs->data[0],alpha=node.inputs->data[1],output=node.outputs->data[0];
 auto* x=interpreter.tensor(input);auto* a=interpreter.tensor(alpha);auto* y=interpreter.tensor(output);
 if(x->type!=kTfLiteInt8||a->type!=kTfLiteInt8||y->type!=kTfLiteInt8||!x->dims||x->dims->size!=4||x->bytes!=y->bytes||!x->data.int8||!a->data.int8||!y->data.int8)
  throw std::invalid_argument("Fixed contiguous INT8 NHWC PReLU required");
 const int channels=x->dims->data[3];
 if(channels<=0||a->bytes!=size_t(channels)||x->bytes%channels||!x->bytes)
  throw std::invalid_argument("PReLU alpha must have one immutable INT8 per channel");
 auto p=std::make_unique<PreluLut>();p->id=id;p->input=input;p->alpha=alpha;p->output=output;p->channels=channels;p->pixels=x->bytes/channels;p->node=&node;p->original=entry->second.invoke;p->lut.resize(size_t(channels)*256);
 std::vector<int8_t> saved_input(x->data.int8,x->data.int8+x->bytes),saved_output(y->data.int8,y->data.int8+y->bytes);
 auto* context=interpreter.primary_subgraph().context();auto* mutable_node=const_cast<TfLiteNode*>(&node);
 const auto begin=std::chrono::steady_clock::now();
 try{
  for(size_t base=0;base<256;base+=p->pixels){
   for(size_t pixel=0;pixel<p->pixels;++pixel)std::memset(x->data.int8+pixel*channels,int((base+pixel)&255),channels);
   if(p->original(context,mutable_node)!=kTfLiteOk)throw std::runtime_error("Original integer PReLU LUT generator failed");
   ++p->generator_calls;
   for(size_t pixel=0;pixel<std::min<size_t>(p->pixels,256-base);++pixel)
    for(int channel=0;channel<channels;++channel)p->lut[size_t(channel)*256+base+pixel]=y->data.int8[pixel*channels+channel];
  }
 }catch(...){std::memcpy(x->data.int8,saved_input.data(),x->bytes);std::memcpy(y->data.int8,saved_output.data(),y->bytes);throw;}
 std::memcpy(x->data.int8,saved_input.data(),x->bytes);std::memcpy(y->data.int8,saved_output.data(),y->bytes);
 p->generator_ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-begin).count();
 return p;
}
inline void ExportPreluLut(const PreluLut& p,const char* directory){
 std::string path=std::string(directory)+"/palm_prelu_node_"+std::to_string(p.id)+".lut";
 std::ofstream file(path,std::ios::binary);if(!file||!file.write(reinterpret_cast<const char*>(p.lut.data()),p.lut.size()))throw std::runtime_error("Cannot export exact integer PReLU LUT");
}
}
