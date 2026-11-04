#ifndef QIMING_REVIEW_ONLY_OWNER_BROKER_H
#define QIMING_REVIEW_ONLY_OWNER_BROKER_H
// Candidate core only. Never creates Device, opens /dev, loads a model, or binds
// a listener. The existing native model SHA/op guards remain upstream intact.
#include <array>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>
#include <chrono>
#include <type_traits>
#include "raw_policy.h"
#include "i8_client.h"
#include "prelu_policy.h"
#include "sha256.h"
#include <unordered_map>
#include <cstring>
#include "tcn_owner_policy.h"

namespace qiming_owner_candidate {
using Config=std::array<uint32_t,32>;
using Counters=std::array<uint64_t,4>; // jobs, ns, input+weight+config bytes, raw bytes
enum class Profile { PosePruned5=0, PersonConv242=1, HandFullI8=2, PalmFullI8=3, HandLiteI8=4, PalmLiteI8=5, PalmLitePreluPL=6, TCNPrimary16=7, TCNRoof16=8 };
struct Status {Counters counters{{0,0,0,0}};uint64_t invocations=0;bool failed=false;};
struct Spec {int node;Config config;};
inline const char* identity(Profile p) {
  switch(p) {
    case Profile::TCNPrimary16:case Profile::TCNRoof16:return qiming_tcn_fixed::Identity(int(p)-7);
    case Profile::PalmLitePreluPL:return qiming_raw::ModelSHA(6);
    case Profile::HandLiteI8:return qiming_raw::ModelSHA(4);
    case Profile::PalmLiteI8:return qiming_raw::ModelSHA(5);
    case Profile::HandFullI8:return qiming_raw::ModelSHA(2);
    case Profile::PalmFullI8:return qiming_raw::ModelSHA(3);
    case Profile::PosePruned5:return "e9a5c5cb17f736fafd4c2ec1da3b3d331d6edbe8a0d32395855aeb2cdfd64b9f";
    case Profile::PersonConv242:return "b43d4c5e1ea6c1f010db0c156ac8e8df4d133ac3509f898d22f53b9e010373e9";
  }
  throw std::invalid_argument("Unknown explicit profile");
}
inline std::vector<Spec> specs(Profile p) {
  if(p==Profile::TCNPrimary16||p==Profile::TCNRoof16){std::vector<Spec> result;for(int i=0;i<16;i++)result.push_back({i,qiming_tcn_fixed::Find(int(p)-7,i%8)->config});return result;}
  if(p==Profile::PalmLitePreluPL){std::vector<Spec> result;for(const auto& j:qiming_prelu_fixed::kJobs)result.push_back({j.node,j.config});return result;}
  if(p==Profile::HandFullI8||p==Profile::PalmFullI8||p==Profile::HandLiteI8||p==Profile::PalmLiteI8){size_t n;auto* source=qiming_raw::Specs(int(p),&n);std::vector<Spec> result;for(size_t i=0;i<n;++i)result.push_back({source[i].node,source[i].config});return result;}
  if(p==Profile::PersonConv242)return {{242,{{0x3849504b,2,0,0,12,12,288,12,12,72,1,1,1,1,0,0,
      0xffffff80u,0,0,0,5184,2592,5184,0,0,0,0,0,0,0,0,0}}}};
  if(p!=Profile::PosePruned5)throw std::invalid_argument("Unknown explicit profile");
  const int nodes[]={145,151,155,161,171};std::vector<Spec> result;
  for(int i=0;i<5;i++) {
    bool expand=(i==0||i==2);uint32_t ci=expand?144:864,co=expand?864:144;
    Config c{{0x3849504b,2,0,0,8,8,ci,8,8,co,1,1,1,1,0,0,0,0,0,0,
        64*ci/8,144*864/8,64*co*4/8,0,0,0,0,0,0,0,0,0}};
    result.push_back({nodes[i],c});
  }
  return result;
}

template<class Device> class OwnerBroker {
 public:
  class Invocation;
  // Caller injects one already acquired lease. No Device constructor here.
  OwnerBroker(std::shared_ptr<Device> lease,std::function<uint64_t()> process_token)
      :lease_(std::move(lease)),process_token_(std::move(process_token)),owner_(process_token_()) {
    if(!lease_)throw std::invalid_argument("Explicit existing single lease required");
    copy_trace_.reserve(300);
    for(int p=2;p<=6;++p){if(p==6){for(const auto& j:qiming_prelu_fixed::kJobs)copy_trace_.emplace((uint64_t(p)<<32)|uint32_t(j.node),std::array<uint64_t,12>{});}
      else{size_t n;auto* fixed=qiming_raw::Specs(p,&n);for(size_t i=0;i<n;++i)copy_trace_.emplace((uint64_t(p)<<32)|uint32_t(fixed[i].node),std::array<uint64_t,12>{});}}
    for(int p=7;p<9;p++)for(int node=0;node<16;node++)copy_trace_.emplace((uint64_t(p)<<32)|uint32_t(node),std::array<uint64_t,12>{});
  }
  OwnerBroker(const OwnerBroker&)=delete;OwnerBroker& operator=(const OwnerBroker&)=delete;
  std::unique_ptr<Invocation> Begin(Profile p,const std::string& model_sha) {
    // Reject identity before taking a transaction or touching any profile state.
    if(model_sha!=identity(p))throw std::invalid_argument("Exact profile/model SHA mismatch");
    if(process_token_()!=owner_)throw std::runtime_error("Owner cannot cross fork/process");
    return std::unique_ptr<Invocation>(new Invocation(*this,p));
  }
  Status Stats(Profile p) {
    identity(p);if(process_token_()!=owner_)throw std::runtime_error("Foreign owner stats");
    std::lock_guard<std::mutex> lock(mutex_);return status_[static_cast<int>(p)];
  }
  bool Quarantined() {std::lock_guard<std::mutex> lock(mutex_);return quarantined_;}
  void RegisterPalmPreluParams(int node,std::vector<int32_t> params){
    if(process_token_()!=owner_)throw std::runtime_error("Foreign parameter registration");
    const auto* job=qiming_prelu_fixed::FindJob(node);
    if(!job||params.size()*4!=size_t(job->config[23])*8||GesturePrunedSHA256(params.data(),params.size()*4)!=job->param_sha)throw std::invalid_argument("Immutable original post plus exact LUT SHA required at startup");
    std::lock_guard<std::mutex> lock(mutex_);auto it=palm_prelu_params_.find(node);
    if(it!=palm_prelu_params_.end()){if(it->second!=params)throw std::invalid_argument("Immutable Palm payload already registered");return;}
    palm_prelu_params_.emplace(node,std::move(params));
  }
  std::array<uint64_t,12> CopyStats(Profile p,int node){identity(p);if(process_token_()!=owner_)throw std::runtime_error("Foreign copy stats");std::lock_guard<std::mutex> lock(mutex_);return copy_trace_.at((uint64_t(int(p))<<32)|uint32_t(node));}
  const void* LeaseIdentityForHostAudit() const {return lease_.get();}

  void RegisterTCNFixed(Profile p,int ordinal,const Config& config,const std::vector<int8_t>& weights,const std::vector<int32_t>& params){
    const int profile=int(p)-7;const auto* job=qiming_tcn_fixed::Find(profile,ordinal);
    if(process_token_()!=owner_||!job||config!=job->config||weights.size()!=job->weight_bytes||params.size()*4!=size_t(job->config[23])*8||
       GesturePrunedSHA256(weights.data(),weights.size())!=job->weight_sha||GesturePrunedSHA256(params.data(),params.size()*4)!=job->post_sha)
      throw std::invalid_argument("Exact fixed TCN config/weight/post SHA registration required");
    std::lock_guard<std::mutex> lock(mutex_);
    if(quarantined_||status_[int(p)].failed)throw std::runtime_error("Failed shared TCN owner cannot register");
    const uint64_t key=(uint64_t(int(p))<<32)|uint32_t(ordinal);auto it=tcn_payloads_.find(key);
    if(it!=tcn_payloads_.end()){if(it->second.weights!=weights||it->second.params!=params)throw std::invalid_argument("Immutable TCN registration differs");return;}
    tcn_payloads_.emplace(key,TCNPayload{weights,params});
  }

  class Invocation {
   public:
    Invocation(const Invocation&)=delete;Invocation& operator=(const Invocation&)=delete;
    ~Invocation(){if(!complete_)owner_.status_[index_].failed=true;}
    uint64_t Run(int node,const std::vector<int8_t>& input,const std::vector<int8_t>& weights,const Config& config,std::vector<int32_t>* output){return RunTyped<int32_t>(node,input,weights,config,nullptr,output);}
    uint64_t RunInt8(int node,gesture_i8_pruned::InputView input,const std::vector<int8_t>& weights,const Config& config,const std::vector<int32_t>& params,std::vector<int8_t>* output){return RunTyped<int8_t>(node,input,weights,config,&params,output);}
    uint64_t RunPalmPrelu(int node,gesture_i8_pruned::InputView input,const std::vector<int8_t>& weights,const Config& config,std::vector<int8_t>* output){
      if(output)output->clear();
      if(profile_!=Profile::PalmLitePreluPL||complete_||owner_.status_[index_].failed||owner_.quarantined_)throw std::runtime_error("Active explicit Palm PL-PReLU invocation required");
      try{
        if(owner_.process_token_()!=owner_.owner_||std::chrono::steady_clock::now()-started_>std::chrono::seconds(60))throw std::runtime_error("Same-process bounded Palm invocation required");
        size_t selected=specs_.size();for(size_t i=0;i<specs_.size();++i)if(specs_[i].node==node&&!visited_[i]){selected=i;break;}
        if(!output||selected>=specs_.size()||config!=specs_[selected].config)throw std::invalid_argument("Fixed Palm PL job/config once per invocation required");
        const auto& c=specs_[selected].config;auto param=owner_.palm_prelu_params_.find(node);
        if(param==owner_.palm_prelu_params_.end())throw std::runtime_error("Startup SHA-verified immutable Palm parameters required");
        const auto& payload=param->second;
        const size_t ni=size_t(c[4])*c[5]*c[6],no=size_t(c[7])*c[8]*c[9],nw=c[3]==2?0:size_t(c[9])*c[10]*c[11]*(c[2]==0?c[6]:1);
        if(input.size()!=ni||weights.size()!=nw||payload.size()*4!=size_t(c[23])*8)throw std::invalid_argument("Exact fixed Palm payload lengths required");
        uint64_t elapsed=0;std::vector<int8_t> private_output;
        try{
          if(c[3]==2||c[24])elapsed=owner_.lease_->RunPrelu(input,weights,c,payload,&private_output);
          else elapsed=owner_.lease_->RunInt8(input,weights,c,payload,&private_output);
          if(!elapsed||private_output.size()!=no)throw std::runtime_error("Invalid complete Palm PL output");
        }catch(...){owner_.quarantined_=true;throw;}
        Counters delta{{1,elapsed,uint64_t(ni+nw+payload.size()*4+128),uint64_t(no)}};
        for(size_t i=0;i<4;++i){owner_.status_[index_].counters[i]+=delta[i];pending_[i]+=delta[i];}
        output->swap(private_output);visited_[selected]=true;output_widths_[selected]=1;++ordinal_;return elapsed;
      }catch(...){owner_.status_[index_].failed=true;if(output)output->clear();throw;}
    }

uint64_t RunPalmPreluInto(int node,gesture_i8_pruned::InputView input,const std::vector<int8_t>& weights,const Config& config,gesture_i8_pruned::OutputView output){
      
      if(profile_!=Profile::PalmLitePreluPL||complete_||owner_.status_[index_].failed||owner_.quarantined_)throw std::runtime_error("Active explicit Palm PL-PReLU invocation required");
      try{
        if(owner_.process_token_()!=owner_.owner_||std::chrono::steady_clock::now()-started_>std::chrono::seconds(60))throw std::runtime_error("Same-process bounded Palm invocation required");
        size_t selected=specs_.size();for(size_t i=0;i<specs_.size();++i)if(specs_[i].node==node&&!visited_[i]){selected=i;break;}
        if(!output||selected>=specs_.size()||config!=specs_[selected].config)throw std::invalid_argument("Fixed Palm PL job/config once per invocation required");
        const auto& c=specs_[selected].config;auto param=owner_.palm_prelu_params_.find(node);
        if(param==owner_.palm_prelu_params_.end())throw std::runtime_error("Startup SHA-verified immutable Palm parameters required");
        const auto& payload=param->second;
        const size_t ni=size_t(c[4])*c[5]*c[6],no=size_t(c[7])*c[8]*c[9],nw=c[3]==2?0:size_t(c[9])*c[10]*c[11]*(c[2]==0?c[6]:1);
        if(input.size()!=ni||weights.size()!=nw||payload.size()*4!=size_t(c[23])*8)throw std::invalid_argument("Exact fixed Palm payload lengths required");
        uint64_t elapsed=0;gesture_i8_pruned::OutputView private_output=output;
        try{
          if(c[3]==2||c[24])elapsed=owner_.lease_->RunPreluInto(input,weights,c,payload,private_output);
          else elapsed=owner_.lease_->RunInt8Into(input,weights,c,payload,private_output);
          owner_.RecordCopy(profile_,node);
          if(!elapsed||private_output.size()!=no)throw std::runtime_error("Invalid complete Palm PL output");
        }catch(...){owner_.quarantined_=true;throw;}
        Counters delta{{1,elapsed,uint64_t(ni+nw+payload.size()*4+128),uint64_t(no)}};
        for(size_t i=0;i<4;++i){owner_.status_[index_].counters[i]+=delta[i];pending_[i]+=delta[i];}
        (void)private_output;visited_[selected]=true;output_widths_[selected]=1;++ordinal_;return elapsed;
      }catch(...){owner_.status_[index_].failed=true;throw;}
    }
    uint64_t RunInt8Into(int node,gesture_i8_pruned::InputView input,const std::vector<int8_t>& weights,const Config& config,const std::vector<int32_t>& params,gesture_i8_pruned::OutputView output){return RunTypedInto<int8_t>(node,input,weights,config,&params,output);}
    template<class T,class Input> uint64_t RunTypedInto(int node,const Input& input,const std::vector<int8_t>& weights,
                 const Config& config,const std::vector<int32_t>* params,gesture_i8_pruned::OutputView output) {
      
      if(complete_||owner_.status_[index_].failed||owner_.quarantined_)
        throw std::runtime_error("Inactive/failed invocation; no output or retry");
      try {
        if(profile_==Profile::PalmLitePreluPL)throw std::invalid_argument("Profile6 requires explicit fixed Palm PL submit");
        if(owner_.process_token_()!=owner_.owner_)throw std::runtime_error("Foreign owner call");
        if((profile_==Profile::HandFullI8||profile_==Profile::PalmFullI8||profile_==Profile::HandLiteI8||profile_==Profile::PalmLiteI8)&&std::chrono::steady_clock::now()-started_>std::chrono::seconds(60))throw std::runtime_error("Whole RAW candidate deadline reached between completed device RUNs");
        size_t selected=ordinal_;
        if(profile_==Profile::HandFullI8||profile_==Profile::PalmFullI8||profile_==Profile::HandLiteI8||profile_==Profile::PalmLiteI8){selected=specs_.size();for(size_t i=0;i<specs_.size();++i)if(specs_[i].node==node&&!visited_[i]){selected=i;break;}}
        if(!output||selected>=specs_.size()||node!=specs_[selected].node)
          throw std::invalid_argument("Exact fixed profile node once per invocation required");
        if constexpr(std::is_same<T,int32_t>::value){if((profile_==Profile::HandLiteI8||profile_==Profile::PalmLiteI8)&&!(profile_==Profile::HandLiteI8&&node==64))throw std::invalid_argument("Lite RAW permitted only for fixed Hand world FC64 integer VRSHL post");}
        Config allowed=specs_[selected].config;
        if constexpr(std::is_same<T,int8_t>::value){
          if(profile_!=Profile::HandFullI8&&profile_!=Profile::PalmFullI8&&profile_!=Profile::HandLiteI8&&profile_!=Profile::PalmLiteI8)throw std::invalid_argument("INT8 output only for explicit fixed Hand/Palm");
          size_t count;const auto* fixed=qiming_raw::Specs(int(profile_),&count);const qiming_raw::Spec* found=nullptr;
          for(size_t i=0;i<count;i++)if(fixed[i].node==node)found=&fixed[i];
          if(!found||!params||params->size()!=size_t(allowed[9])*4)throw std::invalid_argument("INT8 fixed post profile missing");
          for(size_t i=0;i<allowed[9];i++)if((*params)[i*4+1]!=found->multipliers[i]||(*params)[i*4+2]!=found->shifts[i]||(*params)[i*4+3])throw std::invalid_argument("INT8 immutable multiplier/shift differs");
          allowed[3]=1;allowed[17]=uint32_t(found->zero);allowed[18]=uint32_t(found->amin);allowed[19]=uint32_t(found->amax);allowed[22]=(uint64_t(allowed[7])*allowed[8]*allowed[9]+7)/8;allowed[23]=allowed[9]*2;output_bytes_=1;
        }
        for(size_t i=0;i<config.size();i++) {
          if(profile_==Profile::PosePruned5&&i==16) {
            const int64_t z=config[i]<=0x7fffffffu?int64_t(config[i]):int64_t(config[i])-4294967296LL;
            if(z< -128||z>127)throw std::invalid_argument("Exact signed INT8 input zero range");
          } else if(config[i]!=allowed[i])throw std::invalid_argument("Exact profile shape/mode/capacity contract");
        }
        const size_t ni=size_t(allowed[4])*allowed[5]*allowed[6];
        const size_t nw=size_t(allowed[9])*allowed[10]*allowed[11]*(allowed[2]==0?allowed[6]:1);
        const size_t no=size_t(allowed[7])*allowed[8]*allowed[9];
        if(input.size()!=ni||weights.size()!=nw)throw std::invalid_argument("Exact profile tensor lengths");
        gesture_i8_pruned::OutputView private_output=output;
        uint64_t elapsed=0;
        try {
          // This is the only call into the injected device. Existing Device
          // retains ABI/info, coherent spans, canary and read-only guards.
          if constexpr(std::is_same<T,int8_t>::value)elapsed=owner_.lease_->RunInt8Into(input,weights,config,*params,private_output);
          else elapsed=owner_.lease_->Run(input,weights,config,&private_output);
          owner_.RecordCopy(profile_,node);
          if(!elapsed||private_output.size()!=no)throw std::runtime_error("Invalid device completion");
        } catch(...) {owner_.quarantined_=true;throw;}
        Counters delta{{1,elapsed,uint64_t(ni+nw+128+(params?params->size()*4:0)),uint64_t(no*sizeof(T))}};
        for(size_t i=0;i<4;i++) {owner_.status_[index_].counters[i]+=delta[i];pending_[i]+=delta[i];}
        (void)private_output;visited_[selected]=true;output_widths_[selected]=sizeof(T);++ordinal_;return elapsed;
      } catch(...) {owner_.status_[index_].failed=true;throw;}
    }
    template<class T,class Input> uint64_t RunTyped(int node,const Input& input,const std::vector<int8_t>& weights,
                 const Config& config,const std::vector<int32_t>* params,std::vector<T>* output) {
      if(output)output->clear();
      if(complete_||owner_.status_[index_].failed||owner_.quarantined_)
        throw std::runtime_error("Inactive/failed invocation; no output or retry");
      try {
        if(profile_==Profile::PalmLitePreluPL)throw std::invalid_argument("Profile6 requires explicit fixed Palm PL submit");
        if(owner_.process_token_()!=owner_.owner_)throw std::runtime_error("Foreign owner call");
        if((profile_==Profile::HandFullI8||profile_==Profile::PalmFullI8||profile_==Profile::HandLiteI8||profile_==Profile::PalmLiteI8)&&std::chrono::steady_clock::now()-started_>std::chrono::seconds(60))throw std::runtime_error("Whole RAW candidate deadline reached between completed device RUNs");
        size_t selected=ordinal_;
        if(profile_==Profile::HandFullI8||profile_==Profile::PalmFullI8||profile_==Profile::HandLiteI8||profile_==Profile::PalmLiteI8){selected=specs_.size();for(size_t i=0;i<specs_.size();++i)if(specs_[i].node==node&&!visited_[i]){selected=i;break;}}
        if(!output||selected>=specs_.size()||node!=specs_[selected].node)
          throw std::invalid_argument("Exact fixed profile node once per invocation required");
        if constexpr(std::is_same<T,int32_t>::value){if((profile_==Profile::HandLiteI8||profile_==Profile::PalmLiteI8)&&!(profile_==Profile::HandLiteI8&&node==64))throw std::invalid_argument("Lite RAW permitted only for fixed Hand world FC64 integer VRSHL post");}
        Config allowed=specs_[selected].config;
        if constexpr(std::is_same<T,int8_t>::value){
          if(profile_!=Profile::HandFullI8&&profile_!=Profile::PalmFullI8&&profile_!=Profile::HandLiteI8&&profile_!=Profile::PalmLiteI8)throw std::invalid_argument("INT8 output only for explicit fixed Hand/Palm");
          size_t count;const auto* fixed=qiming_raw::Specs(int(profile_),&count);const qiming_raw::Spec* found=nullptr;
          for(size_t i=0;i<count;i++)if(fixed[i].node==node)found=&fixed[i];
          if(!found||!params||params->size()!=size_t(allowed[9])*4)throw std::invalid_argument("INT8 fixed post profile missing");
          for(size_t i=0;i<allowed[9];i++)if((*params)[i*4+1]!=found->multipliers[i]||(*params)[i*4+2]!=found->shifts[i]||(*params)[i*4+3])throw std::invalid_argument("INT8 immutable multiplier/shift differs");
          allowed[3]=1;allowed[17]=uint32_t(found->zero);allowed[18]=uint32_t(found->amin);allowed[19]=uint32_t(found->amax);allowed[22]=(uint64_t(allowed[7])*allowed[8]*allowed[9]+7)/8;allowed[23]=allowed[9]*2;output_bytes_=1;
        }
        for(size_t i=0;i<config.size();i++) {
          if(profile_==Profile::PosePruned5&&i==16) {
            const int64_t z=config[i]<=0x7fffffffu?int64_t(config[i]):int64_t(config[i])-4294967296LL;
            if(z< -128||z>127)throw std::invalid_argument("Exact signed INT8 input zero range");
          } else if(config[i]!=allowed[i])throw std::invalid_argument("Exact profile shape/mode/capacity contract");
        }
        const size_t ni=size_t(allowed[4])*allowed[5]*allowed[6];
        const size_t nw=size_t(allowed[9])*allowed[10]*allowed[11]*(allowed[2]==0?allowed[6]:1);
        const size_t no=size_t(allowed[7])*allowed[8]*allowed[9];
        if(input.size()!=ni||weights.size()!=nw)throw std::invalid_argument("Exact profile tensor lengths");
        std::vector<T> private_output;
        uint64_t elapsed=0;
        try {
          // This is the only call into the injected device. Existing Device
          // retains ABI/info, coherent spans, canary and read-only guards.
          if constexpr(std::is_same<T,int8_t>::value)elapsed=owner_.lease_->RunInt8(input,weights,config,*params,&private_output);
          else elapsed=owner_.lease_->Run(input,weights,config,&private_output);
          if(!elapsed||private_output.size()!=no)throw std::runtime_error("Invalid device completion");
        } catch(...) {owner_.quarantined_=true;throw;}
        Counters delta{{1,elapsed,uint64_t(ni+nw+128+(params?params->size()*4:0)),uint64_t(no*sizeof(T))}};
        for(size_t i=0;i<4;i++) {owner_.status_[index_].counters[i]+=delta[i];pending_[i]+=delta[i];}
        output->swap(private_output);visited_[selected]=true;output_widths_[selected]=sizeof(T);++ordinal_;return elapsed;
      } catch(...) {owner_.status_[index_].failed=true;if(output)output->clear();throw;}
    }
    uint64_t RunTCNInto(int ordinal,gesture_i8_pruned::InputView input,gesture_i8_pruned::OutputView output){
      try{
        if((profile_!=Profile::TCNPrimary16&&profile_!=Profile::TCNRoof16)||complete_||owner_.status_[index_].failed||owner_.quarantined_)
          throw std::runtime_error("Active fixed shared TCN invocation required");
        if(owner_.process_token_()!=owner_.owner_||std::chrono::steady_clock::now()-started_>std::chrono::seconds(60))throw std::runtime_error("Same-process bounded TCN word required");
        if(ordinal<0||ordinal>=16||size_t(ordinal)!=ordinal_)throw std::invalid_argument("TCN exact sixteen-job ordinal sequence required");
        const auto* job=qiming_tcn_fixed::Find(int(profile_)-7,ordinal%8);
        const uint64_t key=(uint64_t(index_)<<32)|uint32_t(ordinal%8);auto found=owner_.tcn_payloads_.find(key);
        if(!job||found==owner_.tcn_payloads_.end()||!input.data()||input.size()!=job->input_bytes||!output||output.size()!=job->output_bytes)
          throw std::invalid_argument("Registered fixed TCN payload and exact typed spans required");
        uint64_t elapsed=0;
        try{
          elapsed=owner_.lease_->RunInt8Into(input,found->second.weights,job->config,found->second.params,output);
          owner_.RecordCopy(profile_,ordinal);
          if(!elapsed)throw std::runtime_error("Invalid fixed TCN device completion");
        }catch(...){owner_.quarantined_=true;throw;}
        Counters delta{{1,elapsed,uint64_t(job->input_bytes+job->weight_bytes+128+found->second.params.size()*4),uint64_t(job->output_bytes)}};
        for(size_t i=0;i<4;i++){owner_.status_[index_].counters[i]+=delta[i];pending_[i]+=delta[i];}
        visited_[ordinal]=true;output_widths_[ordinal]=1;++ordinal_;return elapsed;
      }catch(...){owner_.status_[index_].failed=true;throw;}
    }

    void Commit() {
      if(complete_||owner_.status_[index_].failed||owner_.quarantined_)throw std::runtime_error("Cannot commit failed invocation");
      uint64_t jobs=specs_.size(),input=0,output=0;
      for(size_t index=0;index<specs_.size();index++){const auto& c=specs_[index].config;const unsigned width=output_widths_[index];if(width!=1&&width!=4)throw std::runtime_error("Completed fixed node width required");uint64_t nw=(profile_==Profile::PalmLitePreluPL&&c[3]==2)?0:uint64_t(c[9])*c[10]*c[11]*(c[2]==0?c[6]:1);uint64_t params=profile_==Profile::PalmLitePreluPL?uint64_t(c[23])*8:(width==1?uint64_t(c[9])*16:0);input+=uint64_t(c[4])*c[5]*c[6]+nw+128+params;output+=uint64_t(c[7])*c[8]*c[9]*width;}
      if(ordinal_!=specs_.size()||pending_[0]!=jobs||pending_[1]==0||pending_[2]!=input||pending_[3]!=output) {
        owner_.status_[index_].failed=true;throw std::runtime_error("Exact whole-invocation counters required");
      }
      ++owner_.status_[index_].invocations;complete_=true;
      // Keep the mutex until the Invocation object is destroyed. Native code
      // must take its final stats/output snapshot before that boundary.
    }
    Counters Delta() const{return pending_;}
   private:
    friend class OwnerBroker;
    Invocation(OwnerBroker& owner,Profile p):owner_(owner),profile_(p),index_(static_cast<int>(p)),
        lock_(owner.mutex_),specs_(specs(p)),visited_(specs_.size(),false),output_widths_(specs_.size(),0) {
      if(owner_.status_[index_].failed||owner_.quarantined_)throw std::runtime_error("Profile/device quarantined");
    }
    OwnerBroker& owner_;Profile profile_;int index_;std::unique_lock<std::mutex> lock_;
    std::chrono::steady_clock::time_point started_=std::chrono::steady_clock::now();std::vector<Spec> specs_;std::vector<bool> visited_;std::vector<unsigned> output_widths_;size_t ordinal_=0;unsigned output_bytes_=4;bool complete_=false;Counters pending_{{0,0,0,0}};
  };
 private:
  void RecordCopy(Profile p,int node){auto values=lease_->LastCopyStats();auto& row=copy_trace_.at((uint64_t(int(p))<<32)|uint32_t(node));++row[0];for(size_t i=1;i<row.size();++i)row[i]+=values[i];}
  std::unordered_map<uint64_t,std::array<uint64_t,12>> copy_trace_;
  std::shared_ptr<Device> lease_;std::function<uint64_t()> process_token_;uint64_t owner_;
  std::mutex mutex_;Status status_[9];std::unordered_map<int,std::vector<int32_t>> palm_prelu_params_;struct TCNPayload {std::vector<int8_t> weights;std::vector<int32_t> params;};std::unordered_map<uint64_t,TCNPayload> tcn_payloads_;bool quarantined_=false;
};
}
#endif
