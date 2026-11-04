#include "i8_delegate.h"
#include "i8_client.h"
#include "shared_owner.h"
#include "generated_policy.h"
#include <algorithm>
#include <chrono>
#include <cstring>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include "tensorflow/lite/builtin_ops.h"
#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/delegates/utils/simple_delegate.h"
namespace gesture_i8_pruned { namespace {
thread_local std::string error;
TfLiteStatus Fail(TfLiteContext* c,const char* message){error=message?message:"INT8 delegate failure";if(c&&c->ReportError)c->ReportError(c,"GestureI8: %s",error.c_str());return kTfLiteError;}
const TfLiteTensor* Tensor(TfLiteContext* c,int id){return id>=0&&size_t(id)<c->tensors_size?&c->tensors[id]:nullptr;}
bool Shape(const TfLiteTensor* t,std::initializer_list<int> dims){
  if(!t||t->type!=kTfLiteFloat32||!t->dims||size_t(t->dims->size)!=dims.size())return false;
  size_t n=1;int k=0;for(int d:dims){if(t->dims->data[k++]!=d)return false;n*=d;}return t->bytes==n*4;
}
bool CheckTensors(TfLiteContext* c,const Spec& s){
  const auto& a=s.config;
  return Shape(Tensor(c,s.input),{1,int(a[4]),int(a[5]),int(a[6])})&&
    Shape(Tensor(c,s.weight),{int(a[9]),1,1,int(a[6])})&&Shape(Tensor(c,s.bias),{int(a[9])})&&
    Shape(Tensor(c,s.output),{1,int(a[7]),int(a[8]),int(a[9])});
}
bool Check(TfLiteContext* c,const TfLiteRegistration* r,const TfLiteNode* n,const Spec& s){
  if(!r||r->builtin_code!=kTfLiteBuiltinConv2d||!n||!n->builtin_data||!n->inputs||!n->outputs||n->inputs->size!=3||n->outputs->size!=1)return false;
  if(n->inputs->data[0]!=s.input||n->inputs->data[1]!=s.weight||n->inputs->data[2]!=s.bias||n->outputs->data[0]!=s.output)return false;
  const auto& a=s.config;const auto* p=static_cast<const TfLiteConvParams*>(n->builtin_data);
  if(p->stride_height!=int(a[12])||p->stride_width!=int(a[13])||p->dilation_height_factor!=1||p->dilation_width_factor!=1||int(p->activation)!=s.activation)return false;
  if(p->padding!=kTfLitePaddingSame&&p->padding!=kTfLitePaddingValid)return false;
  // Selected pointwise nodes have identical SAME/VALID geometry; no spatial padding.
  if(a[10]!=1||a[11]!=1||a[14]||a[15])return false;
  return CheckTensors(c,s);
}
const Spec* Find(int index,int bits){for(const auto& s:kSpecs)if(s.node==index&&(bits==16||s.allow_i8))return &s;return nullptr;}
struct Job {const Spec* spec=nullptr;bool ready=false;Weights q8;BalancedWeights q16;};
using LayerCounters=std::unordered_map<int,std::array<uint64_t,8>>;
uint64_t Now(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
class Kernel final:public tflite::SimpleDelegateKernelInterface {
 public:
  Kernel(std::shared_ptr<qiming_shared::SharedOwner> device,int bits,std::shared_ptr<LayerCounters> trace):device_(std::move(device)),bits_(bits),trace_(std::move(trace)){}
  TfLiteStatus Init(TfLiteContext* c,const TfLiteDelegateParams* params) override {
    try{std::unordered_set<int> boundary;for(int i=0;i<params->output_tensors->size;++i)boundary.insert(params->output_tensors->data[i]);
      for(int i=0;i<params->nodes_to_replace->size;++i){int id=params->nodes_to_replace->data[i];const Spec* s=Find(id,bits_);
        TfLiteNode* n=nullptr;TfLiteRegistration* r=nullptr;
        if(!s||c->GetNodeAndRegistration(c,id,&n,&r)!=kTfLiteOk||!Check(c,r,n,*s))return Fail(c,"Partition differs from exact original-op allowlist");
        if(!boundary.count(s->output))internal_.emplace(s->output,std::vector<float>());Job job;job.spec=s;jobs_.push_back(std::move(job));}
      return kTfLiteOk;
    }catch(const std::exception& e){return Fail(c,e.what());}
  }
  TfLiteStatus Prepare(TfLiteContext* c,TfLiteNode*) override {
    // TF2.11 restores kernel context before Prepare: GetNodeAndRegistration is
    // delegate-scope only. Init already validated immutable original node/options.
    // Recheck current tensors directly; do not retain node or tensor pointers.
    try{for(auto& j:jobs_){const Spec& s=*j.spec;
        if(!CheckTensors(c,s))return Fail(c,"Dynamic tensor shape/type change unsupported");
        auto it=internal_.find(s.output);if(it!=internal_.end())it->second.resize(Validate(s.config).output);}
      return kTfLiteOk;
    }catch(const std::exception& e){return Fail(c,e.what());}
  }
  TfLiteStatus Eval(TfLiteContext* c,TfLiteNode*) override {
    try{for(auto& j:jobs_){const uint64_t started=Now();const Spec& s=*j.spec;Config cfg=s.config;Span span=Validate(cfg);auto& stats=trace_->at(s.node);
        const float* x=Data(c,s.input);const float* w=Data(c,s.weight);const float* bias=Data(c,s.bias);float* y=Data(c,s.output);
        if(!x||!w||!bias||!y)return Fail(c,"Unallocated original tensor");
        uint64_t stamp=Now();if(!j.ready){if(bits_==8)j.q8=QuantizeWeights(w,cfg);else j.q16=QuantizeWeights16(w,cfg);j.ready=true;stats[4]+=Now()-stamp;}
        stamp=Now();
        if(bits_==8){auto p=QuantizeInput(x,span.input,&xh_);cfg[16]=uint32_t(int32_t(p.zero));stats[5]+=Now()-stamp;
          stamp=Now();stats[2]+=device_->RunPose(s.node,xh_,j.q8.values,cfg,&raw_);++stats[1];stats[6]+=Now()-stamp;
          stamp=Now();Dequantize(raw_.data(),raw_.size(),cfg[9],p.scale,j.q8.scales.data(),bias,s.activation,y);stats[7]+=Now()-stamp;
        }else{auto p=QuantizeInput16(x,span.input,&xh_,&xl_);cfg[16]=0;combined_.resize(span.output);stats[5]+=Now()-stamp;
          stamp=Now();stats[2]+=device_->RunPose(s.node,xh_,j.q16.high,cfg,&raw_);++stats[1];for(size_t i=0;i<raw_.size();++i)combined_[i]=int64_t(raw_[i])*65536;
          stats[2]+=device_->RunPose(s.node,xh_,j.q16.low,cfg,&raw_);++stats[1];for(size_t i=0;i<raw_.size();++i)combined_[i]+=int64_t(raw_[i])*256;
          stats[2]+=device_->RunPose(s.node,xl_,j.q16.high,cfg,&raw_);++stats[1];for(size_t i=0;i<raw_.size();++i)combined_[i]+=int64_t(raw_[i])*256;
          stats[2]+=device_->RunPose(s.node,xl_,j.q16.low,cfg,&raw_);++stats[1];for(size_t i=0;i<raw_.size();++i)combined_[i]+=int64_t(raw_[i]);stats[6]+=Now()-stamp;
          stamp=Now();Dequantize64(combined_.data(),combined_.size(),cfg[9],p.scale,j.q16.scales.data(),bias,s.activation,y);stats[7]+=Now()-stamp;}
        ++stats[0];stats[3]+=Now()-started;
      }return kTfLiteOk;
    }catch(const std::exception& e){return Fail(c,e.what());}
  }
 private:
  float* Data(TfLiteContext* c,int id){auto it=internal_.find(id);if(it!=internal_.end())return it->second.data();const auto* t=Tensor(c,id);return t?t->data.f:nullptr;}
  std::shared_ptr<qiming_shared::SharedOwner> device_;int bits_;std::vector<Job> jobs_;std::unordered_map<int,std::vector<float>> internal_;
  std::vector<int8_t> xh_,xl_;std::vector<int32_t> raw_;std::vector<int64_t> combined_;
  std::shared_ptr<LayerCounters> trace_;
};
class Delegate final:public tflite::SimpleDelegateInterface {
 public:
  explicit Delegate(int bits):bits_(bits){}
  TfLiteStatus Initialize(TfLiteContext* c) override {
    try{for(const auto& s:kSpecs){if(bits_==8&&!s.allow_i8)continue;TfLiteNode* n=nullptr;TfLiteRegistration* r=nullptr;
        if(c->GetNodeAndRegistration(c,s.node,&n,&r)!=kTfLiteOk||!Check(c,r,n,s))return Fail(c,"Original Pose node/tensor contract mismatch");supported_.insert(n);trace_->emplace(s.node,std::array<uint64_t,8>{});}
      device_=qiming_shared::RequireExplicitOwner();return kTfLiteOk;
    }catch(const std::exception& e){return Fail(c,e.what());}
  }
  bool IsNodeSupportedByDelegate(const TfLiteRegistration*,const TfLiteNode* n,TfLiteContext*)const override{return supported_.count(n)!=0;}
  const char* Name()const override{return "Gesture-ABI2-pruned5-INT8";}
  std::unique_ptr<tflite::SimpleDelegateKernelInterface> CreateDelegateKernelInterface()override{return std::make_unique<Kernel>(device_,bits_,trace_);}
  Options DelegateOptions()const override{return Options{};}
  void Stats(uint64_t out[4]){auto stats=device_->PoseStats();std::copy(stats.begin(),stats.end(),out);}
  void LayerStats(int ordinal,int* node,uint64_t out[8]){if(ordinal<0)throw std::out_of_range("Layer ordinal");for(const auto& s:kSpecs){if(bits_==8&&!s.allow_i8)continue;
    if(ordinal--==0){*node=s.node;const auto& values=trace_->at(s.node);std::copy(values.begin(),values.end(),out);return;}}throw std::out_of_range("Layer ordinal");}
 private:int bits_;std::shared_ptr<qiming_shared::SharedOwner> device_;std::unordered_set<const TfLiteNode*> supported_;std::shared_ptr<LayerCounters> trace_{std::make_shared<LayerCounters>()};
};
}}
extern "C" TfLiteDelegate* gpi8p_delegate_create(int bits){try{if(bits!=8)throw std::invalid_argument("Explicit pruned selected INT8 policy required");return tflite::TfLiteDelegateFactory::CreateSimpleDelegate(std::make_unique<gesture_i8_pruned::Delegate>(bits));}catch(const std::exception& e){gesture_i8_pruned::error=e.what();return nullptr;}}
extern "C" void gpi8p_delegate_delete(TfLiteDelegate* d){tflite::TfLiteDelegateFactory::DeleteSimpleDelegate(d);}
extern "C" const char* gpi8p_delegate_error(){return gesture_i8_pruned::error.c_str();}
extern "C" int gpi8p_delegate_stats(TfLiteDelegate* d,uint64_t out[4]){try{if(!d||!out||!d->data_)return -1;static_cast<gesture_i8_pruned::Delegate*>(d->data_)->Stats(out);return 0;}catch(const std::exception& e){gesture_i8_pruned::error=e.what();return -1;}}
extern "C" int gpi8p_delegate_layer_stats(TfLiteDelegate* d,int ordinal,int* node,uint64_t out[8]){try{if(!d||!out||!node||!d->data_)return -1;static_cast<gesture_i8_pruned::Delegate*>(d->data_)->LayerStats(ordinal,node,out);return 0;}catch(const std::exception& e){gesture_i8_pruned::error=e.what();return -1;}}
