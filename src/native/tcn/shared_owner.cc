#include "shared_owner.h"
#include "person/yf2/yf2_decode.h"
#include <cstring>
#include <mutex>
#include <unistd.h>
#include <stdexcept>
extern "C" int yf2_pc_infer(const uint8_t*,int,int,yf2_box_t*,int);
namespace qiming_shared {
namespace {
std::mutex owner_mutex;
std::weak_ptr<SharedOwner> process_owner;
thread_local Call* active_call=nullptr;
thread_local std::string error;
const int library_pid=getpid();
struct OwnerHandle {int pid=getpid();std::shared_ptr<SharedOwner> owner;bool person_failed=false;std::mutex person_mutex;};
OwnerHandle* Checked(void* ptr) {
  auto* h=static_cast<OwnerHandle*>(ptr);
  if(!h||h->pid!=getpid()||library_pid!=getpid())throw std::runtime_error("Explicit same-process owner required");
  return h;
}
}
SharedOwner::SharedOwner(std::shared_ptr<gesture_i8_pruned::Device> device)
  :broker_(std::move(device),[]{return uint64_t(getpid());}){}
std::shared_ptr<SharedOwner> OwnerFromExplicitHandle(void* p){return Checked(p)->owner;}
std::shared_ptr<SharedOwner> RequireExplicitOwner() {
  if(library_pid!=getpid())throw std::runtime_error("No owner initialization across fork");
  std::lock_guard<std::mutex> lock(owner_mutex);auto owner=process_owner.lock();
  if(!owner)throw std::runtime_error("Explicit gpo_owner_open required before any interpreter");
  return owner;
}
std::unique_ptr<Call> SharedOwner::Begin(Profile p) {
  if(active_call)throw std::runtime_error("Nested owner invocation forbidden");
  return std::unique_ptr<Call>(new Call(*this,p));
}
Call::Call(SharedOwner& owner,Profile p):owner_(owner),profile_(p) {
  if(active_call)throw std::runtime_error("Nested owner invocation forbidden");
  transaction_=owner_.broker_.Begin(p,qiming_owner_candidate::identity(p));active_call=this;
}
Call::~Call(){active_call=nullptr;}
void Call::Commit(){transaction_->Commit();}
uint64_t SharedOwner::RunPose(int node,const std::vector<int8_t>& x,const std::vector<int8_t>& w,
                            const gesture_i8_pruned::Config& c,std::vector<int32_t>* output) {
  if(!active_call||&active_call->owner_!=this||active_call->profile_!=Profile::PosePruned5)
    throw std::runtime_error("Pose kernel requires explicit owning invocation");
  return active_call->transaction_->Run(node,x,w,c,output);
}
uint64_t SharedOwner::RunRaw(Profile p,int node,const std::vector<int8_t>& x,const std::vector<int8_t>& w,const gesture_i8_pruned::Config& c,std::vector<int32_t>* out){
  if(!active_call||&active_call->owner_!=this||active_call->profile_!=p||(p!=Profile::HandFullI8&&p!=Profile::PalmFullI8&&p!=Profile::HandLiteI8))throw std::runtime_error("Exact same-owner Hand/Palm invocation required");
  return active_call->transaction_->Run(node,x,w,c,out);
}
uint64_t SharedOwner::RunInt8(Profile p,int node,gesture_i8_pruned::InputView x,const std::vector<int8_t>& w,const gesture_i8_pruned::Config& c,const std::vector<int32_t>& params,std::vector<int8_t>* out){
 if(!active_call||&active_call->owner_!=this||active_call->profile_!=p)throw std::runtime_error("Exact same-owner INT8 invocation required");
 return active_call->transaction_->RunInt8(node,x,w,c,params,out);
}
void SharedOwner::RegisterPalmPreluParams(int node,std::vector<int32_t> params){if(active_call)throw std::runtime_error("Palm parameters registered only outside invocation");broker_.RegisterPalmPreluParams(node,std::move(params));}
uint64_t SharedOwner::RunPalmPrelu(int node,gesture_i8_pruned::InputView input,const std::vector<int8_t>& weights,const gesture_i8_pruned::Config& config,std::vector<int8_t>* output){
 if(!active_call||&active_call->owner_!=this||active_call->profile_!=Profile::PalmLitePreluPL)throw std::runtime_error("Exact same-owner profile6 invocation required");return active_call->transaction_->RunPalmPrelu(node,input,weights,config,output);
}
uint64_t SharedOwner::RunInt8Into(Profile p,int node,gesture_i8_pruned::InputView x,const std::vector<int8_t>& w,const gesture_i8_pruned::Config& c,const std::vector<int32_t>& params,gesture_i8_pruned::OutputView out){if(!active_call||&active_call->owner_!=this||active_call->profile_!=p)throw std::runtime_error("Exact owning output-view invocation required");return active_call->transaction_->RunInt8Into(node,x,w,c,params,out);}
uint64_t SharedOwner::RunPalmPreluInto(int node,gesture_i8_pruned::InputView x,const std::vector<int8_t>& w,const gesture_i8_pruned::Config& c,gesture_i8_pruned::OutputView out){if(!active_call||&active_call->owner_!=this||active_call->profile_!=Profile::PalmLitePreluPL)throw std::runtime_error("Exact profile6 output-view invocation required");return active_call->transaction_->RunPalmPreluInto(node,x,w,c,out);}
std::array<uint64_t,12> SharedOwner::CopyStats(Profile p,int node){return broker_.CopyStats(p,node);}
std::array<uint64_t,4> SharedOwner::PoseStats(){return broker_.Stats(Profile::PosePruned5).counters;}
qiming_owner_candidate::Status SharedOwner::Stats(Profile p){return broker_.Stats(p);}
bool SharedOwner::Quarantined(){return broker_.Quarantined();}
void SharedOwner::RegisterTCNFixed(Profile p,int ordinal,const gesture_i8_pruned::Config& config,const std::vector<int8_t>& weights,const std::vector<int32_t>& params){
 if(active_call)throw std::runtime_error("TCN registration only outside active invocation");broker_.RegisterTCNFixed(p,ordinal,config,weights,params);
}
uint64_t SharedOwner::RunTCNInto(int ordinal,gesture_i8_pruned::InputView input,gesture_i8_pruned::OutputView output){
 if(!active_call||&active_call->owner_!=this||(active_call->profile_!=Profile::TCNPrimary16&&active_call->profile_!=Profile::TCNRoof16))throw std::runtime_error("Same-owner fixed TCN word invocation required");
 return active_call->transaction_->RunTCNInto(ordinal,input,output);
}

int RunPersonRaw(const int8_t* x,const int8_t* w,int32_t* output) {
  try {
    if(!x||!w||!output||!active_call||active_call->profile_!=Profile::PersonConv242)
      throw std::runtime_error("Person kernel requires explicit owning invocation");
    const auto spec=qiming_owner_candidate::specs(Profile::PersonConv242)[0];
    std::vector<int8_t> inputs(x,x+41472),weights(w,w+20736);std::vector<int32_t> raw;
    active_call->transaction_->Run(242,inputs,weights,spec.config,&raw);
    std::memcpy(output,raw.data(),41472);return 0;
  }catch(const std::exception& e){error=e.what();return -1;}
}
}
extern "C" int yf2_owner_conv242_raw(const int8_t* x,const int8_t* w,int32_t* output){return qiming_shared::RunPersonRaw(x,w,output);}
extern "C" const char* gpo_owner_error(){return qiming_shared::error.c_str();}
extern "C" void* gpo_owner_open() {
  using namespace qiming_shared;
  try {
    if(library_pid!=getpid())throw std::runtime_error("Owner creation across fork forbidden");
    std::lock_guard<std::mutex> lock(owner_mutex);
    if(!process_owner.expired())throw std::runtime_error("One explicit owner/lease only");
    auto handle=std::make_unique<OwnerHandle>();
    // The sole Device construction in the new library. Original Device guards
    // and implementation are compiled unchanged and injected into the broker.
    handle->owner=std::make_shared<SharedOwner>(std::make_shared<gesture_i8_pruned::Device>());
    process_owner=handle->owner;error.clear();return handle.release();
  }catch(const std::exception& e){error=e.what();return nullptr;}
}
extern "C" int gpo_owner_close(void* p) {
  try {delete qiming_shared::Checked(p);return 0;}
  catch(const std::exception& e){qiming_shared::error=e.what();return -1;}
}
extern "C" int gpo_owner_stats(void* p,int which,uint64_t out[7]) {
  using namespace qiming_shared;
  try {
    auto* h=Checked(p);if(!out||(which<0||which>6))throw std::invalid_argument("Explicit profile stats required");
    auto s=h->owner->Stats(static_cast<Profile>(which));
    for(int i=0;i<4;i++)out[i]=s.counters[i];out[4]=s.invocations;out[5]=s.failed;out[6]=h->owner->Quarantined();return 0;
  }catch(const std::exception& e){error=e.what();return -1;}
}
extern "C" int gpo_person_infer(void* p,const char* profile,const char* weights_sha,
 const char* net_sha,const uint8_t* bgr,int width,int height,void* output,int capacity,int* count) {
  using namespace qiming_shared;
  // No partial/stale output is exposed. Full-network workspace is serial because
  // the Person invocation holds the owner transaction from preprocessing onward.
  if(count)*count=0;
  if(output&&capacity==32)std::memset(output,0,sizeof(yf2_box_t)*32);
  try {
    auto* h=Checked(p);std::lock_guard<std::mutex> person_lock(h->person_mutex);
    if(!profile||std::strcmp(profile,"v4_person_yf2_conv242_acc32_v1")||!weights_sha||
       std::strcmp(weights_sha,qiming_owner_candidate::identity(Profile::PersonConv242))||!net_sha||
       std::strcmp(net_sha,"a7350ed1fc222568d319cf1c35b29b1bbef99f5bfc0976f836b08e8bd518fca5")||
       !bgr||!output||!count||width!=640||height!=480||capacity!=32)
      throw std::invalid_argument("Exact v4 Person model/profile/input/output contract required");
    std::memset(output,0,sizeof(yf2_box_t)*32);
    if(h->person_failed)throw std::runtime_error("Failed Person handle; no retry");
    h->person_failed=true;auto call=h->owner->Begin(Profile::PersonConv242);
    yf2_box_t boxes[32]{};int n=yf2_pc_infer(bgr,width,height,boxes,32);
    if(n<0||n>32)throw std::runtime_error("Person network/kernel failed; no CPU fallback");
    call->Commit();std::memcpy(output,boxes,sizeof(yf2_box_t)*size_t(n));*count=n;h->person_failed=false;return 0;
  }catch(const std::exception& e){error=e.what();return -1;}
}
