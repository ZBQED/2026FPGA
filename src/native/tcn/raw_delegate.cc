// Whole fixed INT8 graph candidate. MACs use the existing shared RAW owner;
// MAC+bias+integer post use PL INT8 output; non-MAC integer builtins use PS.
#include "raw_delegate.h"
#include "raw_policy.h"
#include "shared_owner.h"
#include <algorithm>
#include <chrono>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <fstream>
#include <cstdlib>
#include <unordered_map>
#include <unordered_set>
#include "tensorflow/lite/builtin_ops.h"
#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/delegates/utils/simple_delegate.h"

namespace qiming_raw { namespace {
using Trace=std::unordered_map<int,std::array<uint64_t,8>>;
// TensorFlow Lite/gemmlowp default two-rounding integer quantization contract.
// Keep this explicit so the candidate also builds against the deployed minimal
// TF2.11 headers; board golden comparison checks the actual runtime contract.
int32_t Multiply(int32_t x,int32_t multiplier,int shift,bool neon_dw5){
  const int left=std::max(shift,0),right=std::max(-shift,0);
  int64_t expanded=int64_t(x)*(int64_t(1)<<left);
  if(expanded<INT32_MIN||expanded>INT32_MAX)throw std::overflow_error("TFLite left shift outside int32");
  int64_t product=expanded*multiplier;
  int64_t nudge=product>=0?(int64_t(1)<<30):1-(int64_t(1)<<30);
  int32_t high=int32_t((product+nudge)/(int64_t(1)<<31));
  if(right==0)return high;
  // Deployed A9 TFLite's generic 5x5 depthwise NEON path uses VRSHL for
  // the second stage: exact negative halves round toward positive infinity.
  // Its 3x3 and ordinary Conv/FC kernels use the gemmlowp sign correction.
  if(neon_dw5)return int32_t((int64_t(high)+(int64_t(1)<<(right-1)))>>right);
  const uint32_t mask=(uint32_t(1)<<right)-1,remainder=uint32_t(high)&mask;
  const uint32_t threshold=(mask>>1)+(high<0?1u:0u);
  return (high>>right)+(remainder>threshold?1:0);
}
uint64_t Now(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
TfLiteStatus Fail(TfLiteContext* c,const char* s){if(c&&c->ReportError)c->ReportError(c,"Qiming whole INT8 RAW: %s",s);return kTfLiteError;}
const TfLiteTensor* Tensor(TfLiteContext* c,int id){return id>=0&&size_t(id)<c->tensors_size?&c->tensors[id]:nullptr;}
bool Bytes(TfLiteContext* c,int id,TfLiteType type,size_t bytes){auto* t=Tensor(c,id);return t&&t->type==type&&t->bytes==bytes;}
bool CheckTensors(TfLiteContext* c,const Spec& s){auto span=gesture_i8_pruned::Validate(s.config);return Bytes(c,s.input,kTfLiteInt8,span.input)&&Bytes(c,s.weight,kTfLiteInt8,span.weights)&&Bytes(c,s.output,kTfLiteInt8,span.output)&&Bytes(c,s.bias,kTfLiteInt32,s.config[9]*4);}
bool Check(TfLiteContext* c,const TfLiteRegistration* r,const TfLiteNode* n,const Spec& s){
  const int kind=s.kind==0?kTfLiteBuiltinConv2d:s.kind==1?kTfLiteBuiltinDepthwiseConv2d:kTfLiteBuiltinFullyConnected;
  if(!r||r->builtin_code!=kind||!n||!n->builtin_data||!n->inputs||!n->outputs||n->inputs->size!=3||n->outputs->size!=1)return false;
  if(n->inputs->data[0]!=s.input||n->inputs->data[1]!=s.weight||n->inputs->data[2]!=s.bias||n->outputs->data[0]!=s.output||!CheckTensors(c,s))return false;
  if(s.kind==0){auto* p=static_cast<const TfLiteConvParams*>(n->builtin_data);return p->stride_height==int(s.config[12])&&p->stride_width==int(s.config[13])&&p->dilation_height_factor==1&&p->dilation_width_factor==1&&int(p->activation)==s.activation;}
  if(s.kind==1){auto* p=static_cast<const TfLiteDepthwiseConvParams*>(n->builtin_data);return p->depth_multiplier==1&&p->stride_height==int(s.config[12])&&p->stride_width==int(s.config[13])&&p->dilation_height_factor==1&&p->dilation_width_factor==1&&int(p->activation)==s.activation;}
  return int(static_cast<const TfLiteFullyConnectedParams*>(n->builtin_data)->activation)==s.activation;
}
const Spec* Find(int p,int node){size_t n;auto* specs=Specs(p,&n);for(size_t i=0;i<n;++i)if(specs[i].node==node)return specs+i;return nullptr;}
class Kernel final:public tflite::SimpleDelegateKernelInterface {
 public:
  Kernel(int profile,std::shared_ptr<qiming_shared::SharedOwner> owner,std::shared_ptr<Trace> trace):profile_(profile),owner_(std::move(owner)),trace_(std::move(trace)){}
  TfLiteStatus Init(TfLiteContext* c,const TfLiteDelegateParams* p) override {
    try{std::unordered_set<int> boundary;for(int i=0;i<p->output_tensors->size;++i)boundary.insert(p->output_tensors->data[i]);
      for(int i=0;i<p->nodes_to_replace->size;++i){int node=p->nodes_to_replace->data[i];auto* s=Find(profile_,node);TfLiteNode* n=nullptr;TfLiteRegistration* r=nullptr;
        if(!s||c->GetNodeAndRegistration(c,node,&n,&r)!=kTfLiteOk||!Check(c,r,n,*s))throw std::runtime_error("Exact fixed graph node/type/options differ");
        jobs_.push_back(s);if(!boundary.count(s->output))internal_.emplace(s->output,std::vector<int8_t>());}
      for(size_t j=0;j+1<jobs_.size();j++){auto* a=jobs_[j];auto* b=jobs_[j+1];size_t uses=0;for(auto* n:jobs_)if(n->input==a->output)++uses;if(internal_.count(a->output)&&b->input==a->output&&uses==1)chain_.insert(a->output);}
      return kTfLiteOk;
    }catch(const std::exception& e){return Fail(c,e.what());}
  }
  TfLiteStatus Prepare(TfLiteContext* c,TfLiteNode*) override {
    try{for(auto* s:jobs_){if(!CheckTensors(c,*s))throw std::runtime_error("Fixed graph tensor changed");auto span=gesture_i8_pruned::Validate(s->config);
      auto it=internal_.find(s->output);if(it!=internal_.end())it->second.resize(span.output);
      auto* weight=Tensor(c,s->weight);auto* bias=Tensor(c,s->bias);if(!weight->data.int8||!bias->data.i32)throw std::runtime_error("Constant weight/bias unavailable");
      weights_[s->node]=std::vector<int8_t>(weight->data.int8,weight->data.int8+span.weights);
      auto& p=params_[s->node];p.resize(size_t(s->config[9])*4);
      for(size_t ch=0;ch<s->config[9];ch++){p[ch*4]=bias->data.i32[ch];p[ch*4+1]=s->multipliers[ch];p[ch*4+2]=s->shifts[ch];p[ch*4+3]=0;}
      auto config=s->config;config[3]=1;config[17]=uint32_t(s->zero);config[18]=uint32_t(s->amin);config[19]=uint32_t(s->amax);config[22]=(span.output+7)/8;config[23]=s->config[9]*2;configs_[s->node]=config;
      }
      return kTfLiteOk;
    }catch(const std::exception& e){return Fail(c,e.what());}
  }
  TfLiteStatus Eval(TfLiteContext* c,TfLiteNode*) override {
    try{resident_.clear();for(auto* s:jobs_){uint64_t begin=Now(),stamp;auto& stats=trace_->at(s->node);auto span=gesture_i8_pruned::Validate(s->config);auto* x=Data(c,s->input);auto* y=Data(c,s->output);auto* bias=Tensor(c,s->bias)->data.i32;
      if(!x||!y||!bias)throw std::runtime_error("Fixed graph tensor unavailable");
      stamp=Now();gesture_i8_pruned::InputView input_view(x,span.input);stats[5]+=Now()-stamp;stamp=Now();
      if(profile_==4&&s->node==64){
        std::vector<int8_t> raw_input(x,x+span.input);
        stats[2]+=owner_->RunRaw(static_cast<qiming_shared::Profile>(profile_),s->node,raw_input,weights_.at(s->node),s->config,&raw_);++stats[1];stats[6]+=Now()-stamp;stamp=Now();
        // Actual A9 FC64 first divergence: all input bytes exact, only negative
        // half-way second rounding differs. Keep MAC in PL RAW and use the
        // measured integer VRSHL contract for this 63-element final head.
        for(size_t i=0;i<span.output;i++){size_t ch=i%s->config[9];int64_t acc=int64_t(raw_[i])+bias[ch];if(acc<INT32_MIN||acc>INT32_MAX)throw std::overflow_error("FC64 integer acc+bias");int32_t value=Multiply(int32_t(acc),s->multipliers[ch],s->shifts[ch],true)+s->zero;y[i]=int8_t(std::max(s->amin,std::min(s->amax,value)));}
      }else{
      auto output=chain_.count(s->output)?gesture_i8_pruned::OutputView::Resident(&resident_[s->output],span.output):gesture_i8_pruned::OutputView(y,span.output);
      stats[2]+=owner_->RunInt8Into(static_cast<qiming_shared::Profile>(profile_),s->node,input_view,weights_.at(s->node),configs_.at(s->node),params_.at(s->node),output);++stats[1];stats[6]+=Now()-stamp;stamp=Now();
      // Device copies the complete guarded payload once into this cached tensor.
      }
      stats[7]+=Now()-stamp;++stats[0];stats[3]+=Now()-begin;
      if(const char* prefix=std::getenv("GQ_RAW_CAPTURE")){std::ofstream input_file(std::string(prefix)+"/input_node_"+std::to_string(s->node)+".i8",std::ios::binary);input_file.write(reinterpret_cast<const char*>(x),span.input);std::ofstream f(std::string(prefix)+"/raw_node_"+std::to_string(s->node)+".i8",std::ios::binary);f.write(reinterpret_cast<const char*>(y),span.output);}
    }return kTfLiteOk;
    }catch(const std::exception& e){return Fail(c,e.what());}
  }
 private:
  int8_t* Data(TfLiteContext* c,int id){auto r=resident_.find(id);if(r!=resident_.end()&&r->second)return r->second;auto it=internal_.find(id);if(it!=internal_.end())return it->second.data();auto* t=Tensor(c,id);return t?t->data.int8:nullptr;}
  std::unordered_set<int> chain_;std::unordered_map<int,int8_t*> resident_;
  int profile_;std::shared_ptr<qiming_shared::SharedOwner> owner_;std::shared_ptr<Trace> trace_;
  std::vector<const Spec*> jobs_;std::unordered_map<int,std::vector<int8_t>> internal_,weights_;std::vector<int8_t> result_;std::vector<int32_t> raw_;std::unordered_map<int,std::vector<int32_t>> params_;std::unordered_map<int,gesture_i8_pruned::Config> configs_;
};
class Delegate final:public tflite::SimpleDelegateInterface {
 public:
  explicit Delegate(int profile):profile_(profile){}
  TfLiteStatus Initialize(TfLiteContext* c) override {
    try{size_t count;auto* specs=Specs(profile_,&count);for(size_t i=0;i<count;++i){auto& s=specs[i];TfLiteNode* n=nullptr;TfLiteRegistration* r=nullptr;
      if(c->GetNodeAndRegistration(c,s.node,&n,&r)!=kTfLiteOk||!Check(c,r,n,s))throw std::runtime_error("Full fixed Hand/Palm allowlist mismatch");supported_.insert(n);trace_->emplace(s.node,std::array<uint64_t,8>{});}
      owner_=qiming_shared::RequireExplicitOwner();return kTfLiteOk;
    }catch(const std::exception& e){return Fail(c,e.what());}
  }
  bool IsNodeSupportedByDelegate(const TfLiteRegistration*,const TfLiteNode* n,TfLiteContext*)const override{return supported_.count(n)!=0;}
  const char* Name()const override{return "Qiming-ABI3-whole-PL-INT8-output";}
  std::unique_ptr<tflite::SimpleDelegateKernelInterface> CreateDelegateKernelInterface() override{return std::make_unique<Kernel>(profile_,owner_,trace_);}
  Options DelegateOptions()const override{return Options{};}
  void Stats(uint64_t out[4]){auto stats=owner_->Stats(static_cast<qiming_shared::Profile>(profile_));std::copy(stats.counters.begin(),stats.counters.end(),out);}
  void LayerStats(int ordinal,int* node,uint64_t out[8]){size_t n;auto* specs=Specs(profile_,&n);if(ordinal<0||size_t(ordinal)>=n)throw std::out_of_range("Raw layer ordinal");*node=specs[ordinal].node;auto values=trace_->at(*node);std::copy(values.begin(),values.end(),out);}
 private:
  int profile_;std::shared_ptr<qiming_shared::SharedOwner> owner_;std::unordered_set<const TfLiteNode*> supported_;std::shared_ptr<Trace> trace_{std::make_shared<Trace>()};
};
}}
TfLiteDelegate* qraw_delegate_create(int p){if(p!=2&&p!=3&&p!=4&&p!=5)return nullptr;return tflite::TfLiteDelegateFactory::CreateSimpleDelegate(std::make_unique<qiming_raw::Delegate>(p));}
int qraw_delegate_stats(TfLiteDelegate* d,uint64_t out[4]){try{if(!d||!d->data_||!out)return -1;static_cast<qiming_raw::Delegate*>(d->data_)->Stats(out);return 0;}catch(...){return -1;}}
int qraw_delegate_layer_stats(TfLiteDelegate* d,int ordinal,int* node,uint64_t out[8]){try{if(!d||!d->data_||!out||!node)return -1;static_cast<qiming_raw::Delegate*>(d->data_)->LayerStats(ordinal,node,out);return 0;}catch(...){return -1;}}
