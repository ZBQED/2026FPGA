// Fixed integer TCN: every Conv/FC dispatches through v11 Device, including
// dilation2/4 via integer im2col. Non-MAC Add and small boundaries stay integer.
#include "i8_client.h"
#include "shared_owner.h"
#include "sha256.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <climits>
#include <cstring>
#include <cstdlib>
#include <fcntl.h>
#include <fstream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>
#include <sys/file.h>
#include <unistd.h>
#include "tensorflow/lite/interpreter.h"
#include "tensorflow/lite/model_builder.h"
#include "tensorflow/lite/builtin_ops.h"
#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/kernels/register.h"
extern "C" int tcni_normalize(int,const int16_t*,const uint8_t*,int,int8_t*);
extern "C" int tcni_pool(int,const int8_t*,const uint8_t*,int,int8_t*);
extern "C" int tcni_finalize(int,const int8_t*,const int8_t*,int16_t*,uint16_t*);
namespace {
using Config=gesture_i8_pruned::Config;
struct Spec {
 int node,input,weight,bias,output,ci,kw,dilation,positions,co,activation,padding,fc;
 Config config;const int32_t* post;
};
struct ModelSpec {const char* path[2];const char* sha[2];const Spec* specs[2];int count[2];int features;};
#include "tcn_policy.inc"
uint64_t Now(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
thread_local std::string error;
struct Runtime;
struct Op {
 Runtime* runtime;const Spec* spec;TfLiteNode* node;int graph,fixed_ordinal=-1;std::vector<int8_t> input,weight,result;std::vector<int32_t> post,raw;
 std::array<uint64_t,8> stats{};
};
thread_local std::unordered_map<TfLiteNode*,Op*> current_ops;
struct Graph {
 std::vector<char> bytes;std::unique_ptr<tflite::FlatBufferModel> model;std::unique_ptr<tflite::Interpreter> interpreter;std::vector<std::unique_ptr<Op>> ops;
 ~Graph(){for(auto& op:ops)current_ops.erase(op->node);}
};
struct Runtime {
 int profile,pid=getpid(),lock=-1;bool hardware=false,failed=false,fc_vrshl=false;std::thread::id thread=std::this_thread::get_id();std::mutex mutex;
 Graph graphs[2];std::unique_ptr<gesture_i8_pruned::Device> device;std::shared_ptr<qiming_shared::SharedOwner> shared_owner;int shared_ordinal=0;std::array<uint64_t,12> stats{};
 ~Runtime(){device.reset();if(lock>=0)close(lock);}
};
Runtime* Checked(void* h){auto* r=static_cast<Runtime*>(h);if(!r||r->pid!=getpid()||r->thread!=std::this_thread::get_id())throw std::runtime_error("TCN handle requires its creating process/thread");return r;}
int32_t Multiply(int32_t value,int32_t multiplier,int shift,bool vrshl){
 if(shift>0||shift< -31)throw std::runtime_error("Fixed post shift outside v11 contract");
 const int64_t product=int64_t(value)*multiplier,nudge=product>=0?(int64_t(1)<<30):1-(int64_t(1)<<30);int32_t high=int32_t((product+nudge)/(int64_t(1)<<31));int right=-shift;
 if(!right)return high;if(vrshl)return int32_t((int64_t(high)+(int64_t(1)<<(right-1)))>>right);
 const uint32_t mask=(uint32_t(1)<<right)-1,remainder=uint32_t(high)&mask,threshold=(mask>>1)+(high<0?1u:0u);return (high>>right)+(remainder>threshold);
}
void Build(Runtime*,const std::string&,int);
void Invoke(Graph&,const int8_t*,int8_t*);
}
extern "C" const char* gtcn_error(){return error.c_str();}
extern "C" void* gtcn_open(const char* root,int profile,int hardware){
 try{
  if(!root||profile<0||profile>1||(hardware!=0&&hardware!=1))throw std::invalid_argument("Fixed root/profile and explicit CPU0 or PL1 required");
  auto r=std::make_unique<Runtime>();r->profile=profile;r->hardware=hardware;
  Build(r.get(),root,0);Build(r.get(),root,1);
  if(hardware){r->lock=open("/run/lock/gesture-qiming-pl.lock",O_RDWR|O_CREAT|O_CLOEXEC,0600);if(r->lock<0||flock(r->lock,LOCK_EX|LOCK_NB))throw std::runtime_error("TCN needs sole existing device owner lock; stop original Pose in controlled window first");r->device=std::make_unique<gesture_i8_pruned::Device>();}
  error.clear();return r.release();
 }catch(const std::exception& e){error=e.what();return nullptr;}
}
extern "C" uint32_t gtcn_shared_api_version(){return 0x00010000u;}
extern "C" void* gtcn_open_shared(void* owner_handle,const char* root,int profile){
 try{
  if(!owner_handle||!root||profile<0||profile>1)throw std::invalid_argument("Explicit existing owner, assets and fixed TCN profile required");
  auto r=std::make_unique<Runtime>();r->profile=profile;r->hardware=true;
  r->shared_owner=qiming_shared::OwnerFromExplicitHandle(owner_handle);
  Build(r.get(),root,0);Build(r.get(),root,1);
  error.clear();return r.release();
 }catch(const std::exception& e){error=e.what();return nullptr;}
}
extern "C" int gtcn_shared_owner_stats(void* handle,uint64_t out[7]){
 try{auto* r=Checked(handle);if(!out||!r->shared_owner)throw std::invalid_argument("Shared TCN handle required");
  auto p=static_cast<qiming_shared::Profile>(7+r->profile);auto st=r->shared_owner->Stats(p);
  for(int i=0;i<4;i++)out[i]=st.counters[i];out[4]=st.invocations;out[5]=st.failed;out[6]=r->shared_owner->Quarantined();return 0;
 }catch(const std::exception& e){error=e.what();return -1;}
}
extern "C" int gtcn_close(void* handle){
 try{auto* r=Checked(handle);int status=r->failed?-1:0;delete r;return status;}catch(const std::exception& e){error=e.what();return -1;}
}
extern "C" int gtcn_set_fc_vrshl(void* handle,int enabled){
 try{auto* r=Checked(handle);if((enabled!=0&&enabled!=1)||r->stats[4]||r->failed||(r->shared_owner&&enabled))throw std::runtime_error("Choose explicit FC contract before first word");r->fc_vrshl=enabled;return 0;}catch(const std::exception& e){error=e.what();return -1;}
}
extern "C" int gtcn_infer(void* handle,const int16_t* values,uint64_t value_count,const uint8_t* mask,uint64_t mask_count,int16_t logits[27],uint16_t prob[27]){
 Runtime* r=nullptr;
 try{
  r=Checked(handle);std::lock_guard<std::mutex> lock(r->mutex);if(r->failed)throw std::runtime_error("Failed TCN instance: no retry");
  const int f=model_specs[r->profile].features,phases=r->profile?4:1;
  if(!values||!mask||!logits||!prob||value_count!=uint64_t(32*f)||mask_count!=uint64_t(32*f))throw std::invalid_argument("Exact INT16 values and UINT8 mask counts required");
  const uint64_t begin=Now();int8_t normalized[32*224],h[32*64],pooled[256],heads[2][27];
  std::unique_ptr<qiming_shared::Call> shared_call;
  if(r->shared_owner){r->shared_ordinal=0;shared_call=r->shared_owner->Begin(static_cast<qiming_shared::Profile>(7+r->profile));}
  for(int orientation=0;orientation<2;orientation++){
   uint64_t stamp=Now();int rc=tcni_normalize(r->profile,values,mask,orientation,normalized);if(rc)throw std::runtime_error("Invalid source word/mask in integer normalization");r->stats[9]+=Now()-stamp;
   stamp=Now();Invoke(r->graphs[0],normalized,h);r->stats[10]+=Now()-stamp;
   stamp=Now();if(tcni_pool(r->profile,h,mask,orientation,pooled))throw std::runtime_error("Integer masked pool failed");r->stats[9]+=Now()-stamp;
   if(r->graphs[1].interpreter->tensor(r->graphs[1].interpreter->inputs()[0])->bytes!=size_t(64*phases))throw std::runtime_error("Fixed pooled tensor size mismatch");
   stamp=Now();Invoke(r->graphs[1],pooled,heads[orientation]);r->stats[11]+=Now()-stamp;
  }
  uint64_t stamp=Now();int best=tcni_finalize(r->profile,heads[0],heads[1],logits,prob);if(best<0)throw std::runtime_error("Integer final classifier failed");r->stats[9]+=Now()-stamp;if(shared_call){if(r->shared_ordinal!=16)throw std::runtime_error("Shared TCN word did not complete sixteen jobs");shared_call->Commit();}r->stats[4]++;r->stats[5]+=Now()-begin;return best;
 }catch(const std::exception& e){if(r)r->failed=true;error=e.what();return -1;}
}
extern "C" int gtcn_stats(void* handle,uint64_t out[12]){
 try{auto* r=Checked(handle);if(!out)throw std::invalid_argument("Statistics output required");std::copy(r->stats.begin(),r->stats.end(),out);if(r->device){auto d=r->device->Stats();std::copy(d.begin(),d.end(),out);}return 0;}catch(const std::exception& e){error=e.what();return -1;}
}
extern "C" int gtcn_layer_stats(void* handle,int ordinal,int* graph,int* node,uint64_t out[8]){
 try{auto* r=Checked(handle);if(!out||!graph||!node||!r->hardware||ordinal<0||ordinal>=8)throw std::invalid_argument("PL layer ordinal0..7 required");const auto& op=*r->graphs[ordinal==7?1:0].ops[ordinal==7?0:ordinal];*graph=op.graph;*node=op.spec->node;std::copy(op.stats.begin(),op.stats.end(),out);return 0;}catch(const std::exception& e){error=e.what();return -1;}
}
namespace {
TfLiteStatus InvokeMAC(TfLiteContext* c,TfLiteNode* node){
 try{
  Op& op=*current_ops.at(node);Runtime& r=*op.runtime;const Spec& s=*op.spec;if(r.failed||(!r.device&&!r.shared_owner))throw std::runtime_error("TCN device unavailable; no CPU fallback");
  const uint64_t begin=Now();const auto* x=c->tensors[s.input].data.int8;auto* y=c->tensors[s.output].data.int8;if(!x||!y)throw std::runtime_error("Typed TCN tensor unavailable");
  const int packed=s.ci*s.kw;op.input.resize(size_t(s.positions)*packed);int8_t zero=int8_t(int32_t(s.config[16]));
  // k-major/channel-minor matches the original OHWI weight layout exactly.
  for(int t=0;t<s.positions;t++)for(int k=0;k<s.kw;k++){
   int source=t+(k-s.kw/2)*s.dilation;auto* target=op.input.data()+(t*s.kw+k)*s.ci;
   if(source<0||source>=s.positions)std::fill(target,target+s.ci,zero);else std::memcpy(target,x+source*s.ci,s.ci);
  }
  const uint64_t packed_at=Now();uint64_t elapsed=0;
  if(r.shared_owner){
   if(r.shared_ordinal<0||r.shared_ordinal>=16||r.shared_ordinal%8!=op.fixed_ordinal)throw std::runtime_error("Fixed TCN interpreter/job order differs");
   op.result.resize(size_t(s.positions)*s.co);
   elapsed=r.shared_owner->RunTCNInto(r.shared_ordinal,gesture_i8_pruned::InputView(op.input),gesture_i8_pruned::OutputView(op.result.data(),op.result.size()));
   ++r.shared_ordinal;r.stats[0]++;r.stats[1]+=elapsed;r.stats[2]+=op.input.size()+op.weight.size()+op.post.size()*4+128;r.stats[3]+=op.result.size();
  }else if(s.fc&&r.fc_vrshl){
   Config raw=s.config;raw[3]=0;raw[17]=raw[18]=raw[19]=raw[23]=0;raw[22]=(uint64_t(s.positions)*s.co*4+7)/8;
   elapsed=r.device->Run(op.input,op.weight,raw,&op.raw);op.result.resize(size_t(s.positions)*s.co);
   for(size_t i=0;i<op.result.size();i++){int ch=i%s.co;int64_t acc=int64_t(op.raw[i])+op.post[ch*4];if(acc<INT32_MIN||acc>INT32_MAX)throw std::overflow_error("FC acc+bias outside int32");int64_t q=int64_t(Multiply(int32_t(acc),op.post[ch*4+1],op.post[ch*4+2],true))+int32_t(s.config[17]);op.result[i]=int8_t(std::max<int64_t>(int32_t(s.config[18]),std::min<int64_t>(int32_t(s.config[19]),q)));}
  }else elapsed=r.device->RunInt8(op.input,op.weight,s.config,op.post,&op.result);
  const uint64_t hardware_at=Now();std::memcpy(y,op.result.data(),op.result.size());const uint64_t end=Now();
  op.stats[0]++;op.stats[1]+=elapsed;op.stats[2]+=end-begin;op.stats[3]+=packed_at-begin;op.stats[4]+=hardware_at-packed_at;op.stats[5]+=end-hardware_at;
  r.stats[6]+=packed_at-begin;r.stats[7]+=hardware_at-packed_at;r.stats[8]+=end-hardware_at;
  if(const char* prefix=std::getenv("GTCN_CAPTURE")){std::string tag=std::string(prefix)+"/p"+std::to_string(r.profile)+"_g"+std::to_string(op.graph)+"_n"+std::to_string(s.node);std::ofstream fi(tag+".input.i8",std::ios::binary);fi.write(reinterpret_cast<const char*>(x),c->tensors[s.input].bytes);std::ofstream fo(tag+".output.i8",std::ios::binary);fo.write(reinterpret_cast<const char*>(y),op.result.size());}
  return kTfLiteOk;
 }catch(const std::exception& e){error=e.what();if(c&&c->ReportError)c->ReportError(c,"TCN fixed integer PL: %s",e.what());return kTfLiteError;}
}
void Build(Runtime* r,const std::string& root,int index){
 Graph& g=r->graphs[index];const auto& ms=model_specs[r->profile];std::ifstream f(root+"/"+ms.path[index],std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("Read fixed TCN model");auto length=f.tellg();if(length<=0||length>4*1024*1024)throw std::runtime_error("Fixed model byte limit");g.bytes.resize(size_t(length));f.seekg(0);if(!f.read(g.bytes.data(),length))throw std::runtime_error("Incomplete TCN model");
 if(GesturePrunedSHA256(g.bytes.data(),g.bytes.size())!=ms.sha[index])throw std::runtime_error("TCN model SHA mismatch");g.model=tflite::FlatBufferModel::BuildFromBuffer(g.bytes.data(),g.bytes.size());if(!g.model)throw std::runtime_error("Build fixed TCN model");
 tflite::ops::builtin::BuiltinOpResolverWithoutDefaultDelegates resolver;if(tflite::InterpreterBuilder(*g.model,resolver)(&g.interpreter)!=kTfLiteOk||g.interpreter->SetNumThreads(1)!=kTfLiteOk||g.interpreter->AllocateTensors()!=kTfLiteOk)throw std::runtime_error("Allocate INT8 TCN graph");
 if(g.interpreter->inputs().size()!=1||g.interpreter->outputs().size()!=1||g.interpreter->tensor(g.interpreter->inputs()[0])->type!=kTfLiteInt8||g.interpreter->tensor(g.interpreter->outputs()[0])->type!=kTfLiteInt8)throw std::runtime_error("TCN public INT8 contract");
 if(!r->hardware)return;
 for(int i=0;i<ms.count[index];i++){
  const Spec* s=ms.specs[index]+i;auto* entry=g.interpreter->node_and_registration(s->node);if(!entry||entry->second.builtin_code!=(s->fc?kTfLiteBuiltinFullyConnected:kTfLiteBuiltinConv2d))throw std::runtime_error("Fixed MAC ordinal/type mismatch");auto& node=const_cast<TfLiteNode&>(entry->first);
  if(!node.inputs||node.inputs->size!=3||node.inputs->data[0]!=s->input||node.inputs->data[1]!=s->weight||node.inputs->data[2]!=s->bias||!node.outputs||node.outputs->size!=1||node.outputs->data[0]!=s->output)throw std::runtime_error("Fixed MAC tensor IDs mismatch");
  auto* x=g.interpreter->tensor(s->input);auto* w=g.interpreter->tensor(s->weight);auto* b=g.interpreter->tensor(s->bias);auto* y=g.interpreter->tensor(s->output);
  if(x->type!=kTfLiteInt8||w->type!=kTfLiteInt8||b->type!=kTfLiteInt32||y->type!=kTfLiteInt8||x->bytes!=size_t(s->positions)*s->ci||w->bytes!=size_t(s->co)*s->ci*s->kw||b->bytes!=size_t(s->co)*4||y->bytes!=size_t(s->positions)*s->co)throw std::runtime_error("Fixed MAC dtype/span mismatch");
  if(s->fc){auto* p=static_cast<TfLiteFullyConnectedParams*>(node.builtin_data);if(int(p->activation)!=s->activation)throw std::runtime_error("FC activation mismatch");}
  else{auto* p=static_cast<TfLiteConvParams*>(node.builtin_data);if(p->stride_width!=1||p->stride_height!=1||p->dilation_height_factor!=1||p->dilation_width_factor!=s->dilation||int(p->activation)!=s->activation||int(p->padding)!=s->padding+1)throw std::runtime_error("Conv options mismatch");}
  auto op=std::make_unique<Op>();op->runtime=r;op->spec=s;op->node=&node;op->graph=index;op->weight.assign(w->data.int8,w->data.int8+w->bytes);op->post.assign(s->post,s->post+s->co*4);
  for(int ch=0;ch<s->co;ch++)if(b->data.i32[ch]!=op->post[ch*4])throw std::runtime_error("Fixed bias mismatch");
  op->fixed_ordinal=index?7:i;
  if(r->shared_owner)r->shared_owner->RegisterTCNFixed(static_cast<qiming_shared::Profile>(7+r->profile),op->fixed_ordinal,s->config,op->weight,op->post);
  current_ops[&node]=op.get();const_cast<TfLiteRegistration&>(entry->second).invoke=InvokeMAC;g.ops.push_back(std::move(op));
 }
}
void Invoke(Graph& g,const int8_t* input,int8_t* output){auto* x=g.interpreter->tensor(g.interpreter->inputs()[0]);auto* y=g.interpreter->tensor(g.interpreter->outputs()[0]);std::memcpy(x->data.int8,input,x->bytes);if(g.interpreter->Invoke()!=kTfLiteOk)throw std::runtime_error("Fixed integer graph Invoke failed: "+error);std::memcpy(output,y->data.int8,y->bytes);}
}
