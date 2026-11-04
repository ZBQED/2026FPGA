// Fixed original Palm graph: 53 MACs +26 PReLUs, 3 fused and 23 standalone.
// All PReLU arithmetic is PL. Add/Resize and other integer builtins remain PS.
#include "prelu_delegate.h"
#include "prelu_policy.h"
#include "shared_owner.h"
#include "raw_policy.h"
#include "sha256.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cstring>
#include <fstream>
#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "tensorflow/lite/builtin_ops.h"
#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/delegates/utils/simple_delegate.h"
namespace qiming_prelu_fixed { namespace {
using Trace=std::unordered_map<int,std::array<uint64_t,8>>;
uint64_t Now(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
TfLiteStatus Fail(TfLiteContext* c,const char* message){if(c&&c->ReportError)c->ReportError(c,"Fixed Palm PL PReLU: %s",message);return kTfLiteError;}
const TfLiteTensor* Tensor(TfLiteContext* c,int id){return id>=0&&size_t(id)<c->tensors_size?&c->tensors[id]:nullptr;}
bool Bytes(TfLiteContext* c,int id,TfLiteType type,size_t bytes){auto* t=Tensor(c,id);return t&&t->type==type&&t->bytes==bytes;}
const qiming_raw::Spec* Mac(int node){size_t count;auto* specs=qiming_raw::Specs(5,&count);for(size_t i=0;i<count;++i)if(specs[i].node==node)return specs+i;return nullptr;}
bool MacTensors(TfLiteContext* c,const qiming_raw::Spec& s){auto span=gesture_i8_pruned::Validate(s.config);return Bytes(c,s.input,kTfLiteInt8,span.input)&&Bytes(c,s.weight,kTfLiteInt8,span.weights)&&Bytes(c,s.bias,kTfLiteInt32,s.config[9]*4)&&Bytes(c,s.output,kTfLiteInt8,span.output);}
bool LutTensors(TfLiteContext* c,const Lut& s){return Bytes(c,s.input,kTfLiteInt8,s.elements)&&Bytes(c,s.alpha,kTfLiteInt8,s.channels)&&Bytes(c,s.output,kTfLiteInt8,s.elements);}
bool CheckMac(TfLiteContext* c,int node){
 auto* s=Mac(node);TfLiteNode* n=nullptr;TfLiteRegistration* r=nullptr;
 if(!s||c->GetNodeAndRegistration(c,node,&n,&r)!=kTfLiteOk||!n||!r||!n->builtin_data||!n->inputs||!n->outputs||n->inputs->size!=3||n->outputs->size!=1)return false;
 const int kind=s->kind==0?kTfLiteBuiltinConv2d:s->kind==1?kTfLiteBuiltinDepthwiseConv2d:kTfLiteBuiltinFullyConnected;
 auto span=gesture_i8_pruned::Validate(s->config);
 if(r->builtin_code!=kind||n->inputs->data[0]!=s->input||n->inputs->data[1]!=s->weight||n->inputs->data[2]!=s->bias||n->outputs->data[0]!=s->output||
  !Bytes(c,s->input,kTfLiteInt8,span.input)||!Bytes(c,s->weight,kTfLiteInt8,span.weights)||!Bytes(c,s->bias,kTfLiteInt32,s->config[9]*4)||!Bytes(c,s->output,kTfLiteInt8,span.output))return false;
 if(s->kind==0){auto* p=static_cast<const TfLiteConvParams*>(n->builtin_data);return p->stride_height==int(s->config[12])&&p->stride_width==int(s->config[13])&&p->dilation_height_factor==1&&p->dilation_width_factor==1&&int(p->activation)==s->activation;}
 if(s->kind==1){auto* p=static_cast<const TfLiteDepthwiseConvParams*>(n->builtin_data);return p->depth_multiplier==1&&p->stride_height==int(s->config[12])&&p->stride_width==int(s->config[13])&&p->dilation_height_factor==1&&p->dilation_width_factor==1&&int(p->activation)==s->activation;}
 return int(static_cast<const TfLiteFullyConnectedParams*>(n->builtin_data)->activation)==s->activation;
}
bool CheckLut(TfLiteContext* c,const Lut& s){
 TfLiteNode* n=nullptr;TfLiteRegistration* r=nullptr;
 if(c->GetNodeAndRegistration(c,s.node,&n,&r)!=kTfLiteOk||!n||!r||r->builtin_code!=kTfLiteBuiltinPrelu||!n->inputs||!n->outputs||n->inputs->size!=2||n->outputs->size!=1)return false;
 return n->inputs->data[0]==s.input&&n->inputs->data[1]==s.alpha&&n->outputs->data[0]==s.output&&Bytes(c,s.input,kTfLiteInt8,s.elements)&&Bytes(c,s.alpha,kTfLiteInt8,s.channels)&&Bytes(c,s.output,kTfLiteInt8,s.elements);
}
std::vector<uint8_t> ReadLut(const std::string& root,const Lut& spec){
 std::ifstream file(root+"/"+spec.file,std::ios::binary|std::ios::ate);if(!file||file.tellg()!=std::streamoff(spec.channels*256))throw std::runtime_error("Exact fixed LUT file size required");
 std::vector<uint8_t> bytes(spec.channels*256);file.seekg(0);if(!file.read(reinterpret_cast<char*>(bytes.data()),bytes.size())||GesturePrunedSHA256(bytes.data(),bytes.size())!=spec.sha)throw std::runtime_error("Immutable A9-exact PReLU LUT SHA mismatch");return bytes;
}
class Kernel final:public tflite::SimpleDelegateKernelInterface {
 public:
  Kernel(std::shared_ptr<qiming_shared::SharedOwner> owner,std::shared_ptr<Trace> trace,std::string root):owner_(std::move(owner)),trace_(std::move(trace)),root_(std::move(root)){}
  TfLiteStatus Init(TfLiteContext* c,const TfLiteDelegateParams* params)override{
   try{
    std::unordered_set<int> selected,boundary;
    for(int i=0;i<params->nodes_to_replace->size;++i)selected.insert(params->nodes_to_replace->data[i]);
    for(int i=0;i<params->output_tensors->size;++i)boundary.insert(params->output_tensors->data[i]);
    for(int i=0;i<params->nodes_to_replace->size;++i){int node=params->nodes_to_replace->data[i];auto* job=FindJob(node);
     if(!job){auto* lut=FindLut(node);if(!lut||!lut->fused)throw std::runtime_error("Unexpected selected PReLU node");continue;}
     if(job->kind==1&&!selected.count(job->prelu))throw std::runtime_error("Fused Conv/PReLU must share one delegate partition");
     jobs_.push_back(job);if(!boundary.count(job->output))internal_.emplace(job->output,std::vector<int8_t>());
    }
    for(size_t j=0;j+1<jobs_.size();j++){auto* a=jobs_[j];auto* b=jobs_[j+1];size_t uses=0;for(auto* n:jobs_)if(n->input==a->output)++uses;if(internal_.count(a->output)&&b->input==a->output&&uses==1)chain_.insert(a->output);}
    return kTfLiteOk;
   }catch(const std::exception& e){return Fail(c,e.what());}
  }
  TfLiteStatus Prepare(TfLiteContext* c,TfLiteNode*)override{
   try{for(auto* job:jobs_){
     const auto& cfg=job->config;const size_t ni=size_t(cfg[4])*cfg[5]*cfg[6],no=size_t(cfg[7])*cfg[8]*cfg[9];
     if(!Bytes(c,job->input,kTfLiteInt8,ni)||!Bytes(c,job->output,kTfLiteInt8,no))throw std::runtime_error("Fixed PL tensor span changed");
     auto it=internal_.find(job->output);if(it!=internal_.end())it->second.resize(no);
     std::vector<int32_t> payload(size_t(cfg[23])*2,0);auto& weights=weights_[job->node];
     if(job->kind!=2){
      // Registration/topology/options were checked in Delegate::Initialize.
      // Prepare receives a restricted context; only inspect tensors here.
      auto* s=Mac(job->node);if(!s||!MacTensors(c,*s))throw std::runtime_error("Original fixed MAC tensors changed");
      auto* w=Tensor(c,s->weight);auto* b=Tensor(c,s->bias);auto span=gesture_i8_pruned::Validate(s->config);
      if(!w->data.int8||!b->data.i32)throw std::runtime_error("MAC constants unavailable");weights.assign(w->data.int8,w->data.int8+span.weights);
      for(size_t ch=0;ch<cfg[9];++ch){payload[ch*4]=b->data.i32[ch];payload[ch*4+1]=s->multipliers[ch];payload[ch*4+2]=s->shifts[ch];}
     }
     if(job->kind){auto* spec=FindLut(job->prelu);if(!spec||!LutTensors(c,*spec))throw std::runtime_error("Fixed PReLU tensors changed");auto bytes=ReadLut(root_,*spec);
      size_t offset=job->kind==1?size_t(cfg[9])*16:0;std::memcpy(reinterpret_cast<uint8_t*>(payload.data())+offset,bytes.data(),bytes.size());}
     owner_->RegisterPalmPreluParams(job->node,std::move(payload));
    }return kTfLiteOk;
   }catch(const std::exception& e){return Fail(c,e.what());}
  }
  TfLiteStatus Eval(TfLiteContext* c,TfLiteNode*)override{
   try{resident_.clear();for(auto* job:jobs_){uint64_t begin=Now(),stamp;auto& row=trace_->at(job->node);const auto& cfg=job->config;
     const size_t ni=size_t(cfg[4])*cfg[5]*cfg[6],no=size_t(cfg[7])*cfg[8]*cfg[9];auto* x=Data(c,job->input);auto* y=Data(c,job->output);
     if(!x||!y)throw std::runtime_error("PL PReLU tensor data unavailable");stamp=Now();gesture_i8_pruned::InputView input(x,ni);row[5]+=Now()-stamp;stamp=Now();
     auto output=chain_.count(job->output)?gesture_i8_pruned::OutputView::Resident(&resident_[job->output],no):gesture_i8_pruned::OutputView(y,no);
     row[2]+=owner_->RunPalmPreluInto(job->node,input,weights_.at(job->node),cfg,output);++row[1];row[6]+=Now()-stamp;stamp=Now();
     // No second cached-vector to tensor copy.
     row[7]+=Now()-stamp;++row[0];row[3]+=Now()-begin;
    }return kTfLiteOk;
   }catch(const std::exception& e){return Fail(c,e.what());}
  }
 private:
  int8_t* Data(TfLiteContext* c,int id){auto r=resident_.find(id);if(r!=resident_.end()&&r->second)return r->second;auto it=internal_.find(id);if(it!=internal_.end())return it->second.data();auto* t=Tensor(c,id);return t?t->data.int8:nullptr;}
  std::shared_ptr<qiming_shared::SharedOwner> owner_;std::shared_ptr<Trace> trace_;std::string root_;
  std::unordered_set<int> chain_;std::unordered_map<int,int8_t*> resident_;
  std::vector<const Job*> jobs_;std::unordered_map<int,std::vector<int8_t>> internal_,weights_;std::vector<int8_t> result_;
};
class Delegate final:public tflite::SimpleDelegateInterface {
 public:
  explicit Delegate(std::string root):root_(std::move(root)){}
  TfLiteStatus Initialize(TfLiteContext* c)override{
   try{
    for(int node:SelectedNodes()){TfLiteNode* n=nullptr;TfLiteRegistration* r=nullptr;
     bool valid=FindLut(node)?CheckLut(c,*FindLut(node)):CheckMac(c,node);
     if(!valid||c->GetNodeAndRegistration(c,node,&n,&r)!=kTfLiteOk)throw std::runtime_error("Exact Palm MAC/PReLU allowlist differs");supported_.insert(n);}
    TfLiteIntArray* plan=nullptr;if(c->GetExecutionPlan(c,&plan)!=kTfLiteOk||!plan)throw std::runtime_error("Original graph plan required");
    for(const auto& lut:kLuts)if(lut.fused){int consumers=0;for(int i=0;i<plan->size;++i){TfLiteNode* n=nullptr;TfLiteRegistration* r=nullptr;if(c->GetNodeAndRegistration(c,plan->data[i],&n,&r)!=kTfLiteOk||!n||!n->inputs)throw std::runtime_error("Original consumer graph unavailable");
      for(int j=0;j<n->inputs->size;++j)if(n->inputs->data[j]==lut.input){if(plan->data[i]!=lut.node)throw std::runtime_error("Conv output has another consumer; cannot fuse");++consumers;}}
     if(consumers!=1)throw std::runtime_error("Exactly one original Conv-to-PReLU consumer required");}
    for(const auto& job:kJobs)trace_->emplace(job.node,std::array<uint64_t,8>{});owner_=qiming_shared::RequireExplicitOwner();return kTfLiteOk;
   }catch(const std::exception& e){return Fail(c,e.what());}
  }
  bool IsNodeSupportedByDelegate(const TfLiteRegistration*,const TfLiteNode* node,TfLiteContext*)const override{return supported_.count(node)!=0;}
  const char* Name()const override{return "Palm-fixed-53MAC-26PLPReLU-3fused-23standalone";}
  std::unique_ptr<tflite::SimpleDelegateKernelInterface> CreateDelegateKernelInterface()override{return std::make_unique<Kernel>(owner_,trace_,root_);}
  Options DelegateOptions()const override{return Options{};}
  void Stats(uint64_t out[4]){auto s=owner_->Stats(qiming_shared::Profile::PalmLitePreluPL);std::copy(s.counters.begin(),s.counters.end(),out);}
  void LayerStats(int ordinal,int* node,uint64_t out[8]){if(ordinal<0||size_t(ordinal)>=kJobCount)throw std::out_of_range("PL job ordinal");*node=kJobs[ordinal].node;auto values=trace_->at(*node);std::copy(values.begin(),values.end(),out);}
 private:std::string root_;std::shared_ptr<qiming_shared::SharedOwner> owner_;std::shared_ptr<Trace> trace_{std::make_shared<Trace>()};std::unordered_set<const TfLiteNode*> supported_;
};
}}
TfLiteDelegate* qprelu_delegate_create(const char* root){return root?tflite::TfLiteDelegateFactory::CreateSimpleDelegate(std::make_unique<qiming_prelu_fixed::Delegate>(root)):nullptr;}
int qprelu_delegate_stats(TfLiteDelegate* d,uint64_t out[4]){try{if(!d||!d->data_||!out)return -1;static_cast<qiming_prelu_fixed::Delegate*>(d->data_)->Stats(out);return 0;}catch(...){return -1;}}
int qprelu_delegate_layer_stats(TfLiteDelegate* d,int ordinal,int* node,uint64_t out[8]){try{if(!d||!d->data_||!out||!node)return -1;static_cast<qiming_prelu_fixed::Delegate*>(d->data_)->LayerStats(ordinal,node,out);return 0;}catch(...){return -1;}}
int qprelu_delegate_job_info(TfLiteDelegate*,int ordinal,int out[8]){if(!out||ordinal<0||size_t(ordinal)>=qiming_prelu_fixed::kJobCount)return -1;const auto& j=qiming_prelu_fixed::kJobs[ordinal];int v[8]={j.node,j.kind,j.prelu,j.input,j.output,int(j.config[3]),int(j.config[24]),int(j.config[9])};std::copy(v,v+8,out);return 0;}
