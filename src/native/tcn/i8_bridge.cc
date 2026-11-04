#include "i8_delegate.h"
#include "shared_owner.h"
#include "raw_delegate.h"
#include "prelu_delegate.h"
#include "prelu_policy.h"
#include "raw_policy.h"
#include "tensorflow/lite/interpreter_options.h"
#include <cstdlib>
#include "generated_policy.h"
#include "sha256.h"
#include "prune_graph.h"
#include <algorithm>
#include <cstring>
#include <fstream>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>
#include <unordered_map>
#include <chrono>
#include "tensorflow/lite/builtin_ops.h"
#include <unistd.h>
#include "tensorflow/lite/interpreter.h"
#include "tensorflow/lite/kernels/register.h"
#include "tensorflow/lite/model_builder.h"
#include "prelu_lut.h"
#include "hand_mean_integer.h"
#include "palm_resize_integer.h"
namespace gesture_i8_pruned_bridge {
thread_local std::string error;
const int library_owner_pid=getpid();
struct OpProfile {int id,kind;TfLiteStatus (*invoke)(TfLiteContext*,TfLiteNode*);uint64_t calls=0,ns=0;const TfLiteNode* node;};
thread_local std::unordered_map<const TfLiteNode*,OpProfile*> profiled_ops;
TfLiteStatus ProfileInvoke(TfLiteContext* context,TfLiteNode* node){auto* p=profiled_ops.at(node);auto begin=std::chrono::steady_clock::now();auto status=p->invoke(context,node);p->ns+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-begin).count();++p->calls;return status;}
struct Runtime {
  bool force_prelu_lut=false;bool mean58_integer=false;bool palm_resize_neon=false;
  std::vector<std::unique_ptr<PreluLut>> prelu_luts;
  std::vector<std::unique_ptr<OpProfile>> op_profile;
  ~Runtime(){for(auto& p:op_profile)profiled_ops.erase(p->node);for(auto& p:prelu_luts)prelu_ops.erase(p->node);}
  std::shared_ptr<qiming_shared::SharedOwner> hardware_owner;
  int owner=getpid(),bits=0,selected=0,raw_profile=0;bool pruned=false;bool invoked=false,failed=false;std::vector<bool> input_ready;std::mutex mutex;
  std::vector<char> bytes;std::unique_ptr<tflite::FlatBufferModel> model;
  std::unique_ptr<TfLiteDelegate,void(*)(TfLiteDelegate*)> delegate{nullptr,gpi8p_delegate_delete};
  std::unique_ptr<tflite::Interpreter> interpreter; // Destroy before delegate/model/bytes.
};
std::string PreluAssetRoot(const char* path){std::string value(path);auto slash=value.find_last_of('/');if(slash==std::string::npos)throw std::invalid_argument("Absolute model subdirectory required");value.resize(slash);slash=value.find_last_of('/');if(slash==std::string::npos)throw std::invalid_argument("Pinned model root required");return value.substr(0,slash)+"/luts";}
Runtime* Checked(void* p){auto* r=static_cast<Runtime*>(p);if(!r)throw std::invalid_argument("Null runtime");
  if(r->owner!=getpid())throw std::runtime_error("Runtime cannot be used or destroyed across fork");return r;}
const TfLiteTensor* Tensor(Runtime* r,int output,int ordinal){
  if(output!=0&&output!=1)throw std::invalid_argument("Input/output selector must be0/1");
  const auto& ids=output?r->interpreter->outputs():r->interpreter->inputs();
  if(ordinal<0||size_t(ordinal)>=ids.size())throw std::out_of_range("Tensor ordinal");return r->interpreter->tensor(ids[ordinal]);}
int Fail(const std::exception& e){error=e.what();return -1;}
}
extern "C" const char* gpi8p_error(){return gesture_i8_pruned_bridge::error.c_str();}
extern "C" void* gpi8p_open(const char* path,int threads,const char* policy){
  using namespace gesture_i8_pruned_bridge;
  try{
    if(getpid()!=library_owner_pid)throw std::runtime_error("Library cannot initialize after fork; exec a fresh process");
    if(!path||!policy||(threads!=1&&threads!=2))throw std::invalid_argument("Explicit model/policy and1or2 threads required");
    auto r=std::make_unique<Runtime>();r->hardware_owner=qiming_shared::RequireExplicitOwner();
    if(!std::strcmp(policy,"fp32")){r->bits=0;r->selected=0;}
    else if(!std::strcmp(policy,"pruned_fp32")){r->bits=0;r->selected=0;r->pruned=true;}
    else if(!std::strcmp(policy,"pruned5_i8")){r->bits=8;r->selected=gesture_i8_pruned::kSelectedCount;r->pruned=true;
      if(r->selected!=5)throw std::runtime_error("Nonempty reviewed selection required");}
    else if(!std::strcmp(policy,"hand_full_i8_raw")||!std::strcmp(policy,"hand_full_i8_cpu")){r->raw_profile=2;r->bits=!std::strcmp(policy,"hand_full_i8_raw")?8:0;r->selected=r->bits?50:0;}
    else if(!std::strcmp(policy,"palm_full_i8_raw")||!std::strcmp(policy,"palm_full_i8_cpu")){r->raw_profile=3;r->bits=!std::strcmp(policy,"palm_full_i8_raw")?8:0;r->selected=r->bits?63:0;}
    else if(!std::strcmp(policy,"hand_lite_i8_hw")||!std::strcmp(policy,"hand_lite_i8_cpu")){r->raw_profile=4;r->bits=!std::strcmp(policy,"hand_lite_i8_hw")?8:0;r->selected=r->bits?51:0;}
    else if(!std::strcmp(policy,"palm_lite_i8_hw")||!std::strcmp(policy,"palm_lite_i8_cpu")){r->bits=!std::strcmp(policy,"palm_lite_i8_hw")?8:0;r->raw_profile=r->bits?6:5;r->selected=r->bits?qiming_prelu_fixed::kSelectedCount:0;}
    else if(!std::strcmp(policy,"palm_lite_i8_lut_cpu")){r->raw_profile=5;r->bits=0;r->selected=0;r->force_prelu_lut=true;}
    else throw std::invalid_argument("Unknown explicit pruned per-model policy");
    std::ifstream f(path,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("Cannot read original model");
    auto size=f.tellg();if(size<=0||size>64*1024*1024)throw std::runtime_error("Model size outside fixed original range");
    r->bytes.resize(size_t(size));f.seekg(0);if(!f.read(r->bytes.data(),size))throw std::runtime_error("Incomplete model read");
    const std::string sha=GesturePrunedSHA256(r->bytes.data(),r->bytes.size());
    bool known=false;for(const char* value:gesture_i8_pruned::kOriginalModelSHAs)known=known||sha==value;
    if(r->raw_profile?sha!=qiming_raw::ModelSHA(r->raw_profile):(!known||(r->pruned&&sha!=gesture_i8_pruned::kOriginalPoseSHA)||(!r->pruned&&sha==gesture_i8_pruned::kOriginalPoseSHA)))
      throw std::runtime_error("Original model SHA/explicit pruned policy mismatch");
    r->model=tflite::FlatBufferModel::BuildFromBuffer(r->bytes.data(),r->bytes.size());
    if(!r->model)throw std::runtime_error("Cannot load exact original model");
    tflite::ops::builtin::BuiltinOpResolverWithoutDefaultDelegates resolver;
    if(tflite::InterpreterBuilder(*r->model,resolver)(&r->interpreter)!=kTfLiteOk)throw std::runtime_error("Cannot build interpreter");
    if(r->raw_profile&&std::getenv("GQ_RAW_CAPTURE")){tflite::InterpreterOptions options;options.SetPreserveAllTensors();if(r->interpreter->ApplyOptions(&options)!=kTfLiteOk)throw std::runtime_error("Explicit debug tensor preservation failed");}
    if(r->interpreter->SetNumThreads(threads)!=kTfLiteOk)throw std::runtime_error("SetNumThreads failed");
    if(r->pruned){gesture_i8_pruned::ApplyPrunedGraph(*r->interpreter);gesture_i8_pruned::ValidateSelectedSpecs();}
    if(r->bits){r->delegate.reset(r->raw_profile==6?qprelu_delegate_create(PreluAssetRoot(path).c_str()):r->raw_profile?qraw_delegate_create(r->raw_profile):gpi8p_delegate_create(r->bits));
      if(!r->delegate||r->interpreter->ModifyGraphWithDelegate(r->delegate.get())!=kTfLiteOk)
        throw std::runtime_error(std::string("Explicit INT8 delegate preparation failed: ")+gpi8p_delegate_error());
      std::vector<int> delegated;
      for(int index:r->interpreter->execution_plan()){const auto* entry=r->interpreter->node_and_registration(index);
        if(entry&&entry->first.delegate==r->delegate.get()){
          const auto* params=static_cast<const TfLiteDelegateParams*>(entry->first.builtin_data);
          if(!params||!params->nodes_to_replace)throw std::runtime_error("Invalid delegated partition metadata");
          for(int i=0;i<params->nodes_to_replace->size;++i)delegated.push_back(params->nodes_to_replace->data[i]);}}
      std::sort(delegated.begin(),delegated.end());
      std::vector<int> expected;if(r->raw_profile==6)expected=qiming_prelu_fixed::SelectedNodes();else if(r->raw_profile){size_t n;auto* specs=qiming_raw::Specs(r->raw_profile,&n);for(size_t i=0;i<n;++i)expected.push_back(specs[i].node);std::sort(expected.begin(),expected.end());}else expected=gesture_i8_pruned::SelectedNodeIDs();
      if(delegated!=expected)throw std::runtime_error("Delegated original-node identity differs from reviewed selection");}
    if(r->interpreter->AllocateTensors()!=kTfLiteOk)throw std::runtime_error("Cannot allocate original graph tensors");
    if(r->pruned)gesture_i8_pruned::ValidatePublicTensors(*r->interpreter);
    if(r->raw_profile>=4){for(int id:r->interpreter->inputs())if(r->interpreter->tensor(id)->type!=kTfLiteInt8)throw std::runtime_error("Lite INT8 input contract");for(int id:r->interpreter->outputs())if(r->interpreter->tensor(id)->type!=kTfLiteInt8)throw std::runtime_error("Lite INT8 output contract");}
    r->input_ready.resize(r->interpreter->inputs().size(),false);
    if(r->raw_profile==5&&(r->bits||r->force_prelu_lut)){
      for(int id:r->interpreter->execution_plan()){auto* entry=r->interpreter->node_and_registration(id);if(entry->second.builtin_code!=kTfLiteBuiltinPrelu)continue;
        auto p=MakePreluLut(*r->interpreter,id);if(const char* directory=std::getenv("GQ_PRELU_LUT_EXPORT_DIR"))ExportPreluLut(*p,directory);
        prelu_ops[p->node]=p.get();const_cast<TfLiteRegistration&>(entry->second).invoke=PreluLookup;r->prelu_luts.push_back(std::move(p));}
      if(r->prelu_luts.size()!=26)throw std::runtime_error("Exact Palm26 PReLU LUT coverage required");
    }
    if(r->raw_profile==4){hand_mean_integer::Install(*r->interpreter);r->mean58_integer=true;}
    if(r->raw_profile==6){palm_resize_integer::Install(*r->interpreter);r->palm_resize_neon=true;}
    if(std::getenv("GQ_PROFILE_NONMAC")){for(int id:r->interpreter->execution_plan()){auto* entry=r->interpreter->node_and_registration(id);if(entry->second.builtin_code==kTfLiteBuiltinDelegate||!entry->second.invoke)continue;auto p=std::make_unique<OpProfile>();p->id=id;p->kind=entry->second.builtin_code;p->invoke=entry->second.invoke;p->node=&entry->first;profiled_ops[p->node]=p.get();const_cast<TfLiteRegistration&>(entry->second).invoke=ProfileInvoke;r->op_profile.push_back(std::move(p));}}
    error.clear();return r.release();
  }catch(const std::exception& e){Fail(e);return nullptr;}
}
extern "C" void gpi8p_close(void* handle){
  auto* r=static_cast<gesture_i8_pruned_bridge::Runtime*>(handle);if(!r)return;
  // No copied TFLite/mutex destruction after fork; process teardown reclaims
  // this child's references. No use/retry is supported in the forked child.
  if(r->owner!=getpid()){gesture_i8_pruned_bridge::error="Forked runtime close ignored; child must exit";return;}delete r;
}
extern "C" int gpi8p_count(void* h,int output){try{auto* r=gesture_i8_pruned_bridge::Checked(h);std::lock_guard<std::mutex> lock(r->mutex);
  if(output!=0&&output!=1)throw std::invalid_argument("Invalid tensor selector");return output?r->interpreter->outputs().size():r->interpreter->inputs().size();}catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_tensor_info(void* h,int output,int ordinal,int* type,int* rank,int dims[8],uint64_t* bytes){
  try{auto* r=gesture_i8_pruned_bridge::Checked(h);std::lock_guard<std::mutex> lock(r->mutex);if(!type||!rank||!dims||!bytes)throw std::invalid_argument("Null tensor metadata");
    const auto* t=gesture_i8_pruned_bridge::Tensor(r,output,ordinal);if(!t||!t->dims||t->dims->size>8)throw std::runtime_error("Invalid tensor metadata");
    *type=int(t->type);*rank=t->dims->size;*bytes=t->bytes;std::fill(dims,dims+8,0);std::copy(t->dims->data,t->dims->data+*rank,dims);return 0;
  }catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_input(void* h,int ordinal,const void* data,uint64_t bytes){
  try{auto* r=gesture_i8_pruned_bridge::Checked(h);std::lock_guard<std::mutex> lock(r->mutex);r->invoked=false;const auto* t=gesture_i8_pruned_bridge::Tensor(r,0,ordinal);
    if(!data||!t||bytes!=t->bytes||!t->data.raw)throw std::invalid_argument("Exact input byte count required");std::memcpy(t->data.raw,data,size_t(bytes));r->input_ready.at(ordinal)=true;return 0;
  }catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_invoke(void* h){
  try{auto* r=gesture_i8_pruned_bridge::Checked(h);std::lock_guard<std::mutex> lock(r->mutex);r->invoked=false;
    if(r->failed)throw std::runtime_error("Failed runtime quarantined; no retry");
    r->failed=true;
    if(std::find(r->input_ready.begin(),r->input_ready.end(),false)!=r->input_ready.end())throw std::runtime_error("All original input tensors must be supplied before invocation");
    auto transaction=r->bits?r->hardware_owner->Begin(r->raw_profile?static_cast<qiming_shared::Profile>(r->raw_profile):qiming_shared::Profile::PosePruned5):nullptr;
    if(r->interpreter->Invoke()!=kTfLiteOk)throw std::runtime_error(std::string("Inference failed; no CPU fallback: ")+gpi8p_delegate_error());
    if(transaction)transaction->Commit();
    r->invoked=true;r->failed=false;return 0;
  }catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_output(void* h,int ordinal,void* data,uint64_t bytes){
  try{auto* r=gesture_i8_pruned_bridge::Checked(h);std::lock_guard<std::mutex> lock(r->mutex);
    if(!r->invoked)throw std::runtime_error("Output unavailable before successful invocation");const auto* t=gesture_i8_pruned_bridge::Tensor(r,1,ordinal);
    if(!data||!t||bytes!=t->bytes||!t->data.raw)throw std::invalid_argument("Exact output byte count required");std::memcpy(data,t->data.raw,size_t(bytes));return 0;
  }catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_policy_info(void* h,int* bits,int* nodes,int* passes){
  try{auto* r=gesture_i8_pruned_bridge::Checked(h);if(!bits||!nodes||!passes)throw std::invalid_argument("Null policy metadata");
    *bits=r->bits;*nodes=r->selected;*passes=r->raw_profile==6?qiming_prelu_fixed::kJobCount:r->bits==16?r->selected*4:r->selected;return 0;
  }catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_hardware_stats(void* h,uint64_t out[4]){
  try{auto* r=gesture_i8_pruned_bridge::Checked(h);if(!out)throw std::invalid_argument("Null statistics");std::lock_guard<std::mutex> lock(r->mutex);
    if(!r->delegate){std::fill(out,out+4,0);return 0;}return r->raw_profile==6?qprelu_delegate_stats(r->delegate.get(),out):r->raw_profile?qraw_delegate_stats(r->delegate.get(),out):gpi8p_delegate_stats(r->delegate.get(),out);
  }catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_layer_stats(void* h,int ordinal,int* node,uint64_t out[8]){
  try{auto* r=gesture_i8_pruned_bridge::Checked(h);std::lock_guard<std::mutex> lock(r->mutex);
    if(!r->delegate||!node||!out)throw std::invalid_argument("Layer statistics require explicit hardware policy");
    if(r->raw_profile==6?qprelu_delegate_layer_stats(r->delegate.get(),ordinal,node,out):r->raw_profile?qraw_delegate_layer_stats(r->delegate.get(),ordinal,node,out):gpi8p_delegate_layer_stats(r->delegate.get(),ordinal,node,out))throw std::runtime_error(gpi8p_delegate_error());return 0;
  }catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}

extern "C" int gpi8p_tensor_id(void* h,int output,int ordinal){
  try{auto* r=gesture_i8_pruned_bridge::Checked(h);std::lock_guard<std::mutex> lock(r->mutex);
    gesture_i8_pruned_bridge::Tensor(r,output,ordinal);
    return (output?r->interpreter->outputs():r->interpreter->inputs()).at(ordinal);
  }catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}

extern "C" int gpi8p_debug_tensor(void* h,int id,void* output,uint64_t bytes){
  try{auto* r=gesture_i8_pruned_bridge::Checked(h);if(!r->raw_profile||!std::getenv("GQ_RAW_CAPTURE")||!r->invoked||id<0||id>=r->interpreter->tensors_size())throw std::runtime_error("Explicit debug snapshot required");
    auto* tensor=r->interpreter->tensor(id);if(!output||!tensor||!tensor->data.raw||bytes!=tensor->bytes)throw std::runtime_error("Exact debug tensor bytes required");std::memcpy(output,tensor->data.raw,size_t(bytes));return 0;
  }catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}
}

extern "C" int gpi8p_tensor_quantization(void* h,int output,int ordinal,float* scale,int* zero){
 try{auto* r=gesture_i8_pruned_bridge::Checked(h);std::lock_guard<std::mutex> lock(r->mutex);const auto* t=gesture_i8_pruned_bridge::Tensor(r,output,ordinal);if(!scale||!zero||!t||t->type!=kTfLiteInt8||!(t->params.scale>0))throw std::invalid_argument("INT8 quantization metadata required");*scale=t->params.scale;*zero=t->params.zero_point;return 0;}catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_input_i8(void* h,int ordinal,const int8_t* x,uint64_t bytes){
 try{auto* r=gesture_i8_pruned_bridge::Checked(h);if(gesture_i8_pruned_bridge::Tensor(r,0,ordinal)->type!=kTfLiteInt8)throw std::invalid_argument("Typed INT8 input required");return gpi8p_input(h,ordinal,x,bytes);}catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_output_i8(void* h,int ordinal,int8_t* x,uint64_t bytes){
 try{auto* r=gesture_i8_pruned_bridge::Checked(h);if(gesture_i8_pruned_bridge::Tensor(r,1,ordinal)->type!=kTfLiteInt8)throw std::invalid_argument("Typed INT8 output required");return gpi8p_output(h,ordinal,x,bytes);}catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_op_count(void* h){try{return gesture_i8_pruned_bridge::Checked(h)->op_profile.size();}catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_op_stats(void* h,int ordinal,int* node,int* kind,uint64_t out[2]){try{auto* r=gesture_i8_pruned_bridge::Checked(h);const auto& p=*r->op_profile.at(ordinal);if(!node||!kind||!out)throw std::invalid_argument("Op profile output required");*node=p.id;*kind=p.kind;out[0]=p.calls;out[1]=p.ns;return 0;}catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}

extern "C" int gpi8p_prelu_count(void* h){try{return gesture_i8_pruned_bridge::Checked(h)->prelu_luts.size();}catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_prelu_stats(void* h,int ordinal,int ids[4],uint64_t out[6]){try{auto* r=gesture_i8_pruned_bridge::Checked(h);const auto& p=*r->prelu_luts.at(ordinal);if(!ids||!out)throw std::invalid_argument("PReLU LUT metadata output required");ids[0]=p.id;ids[1]=p.input;ids[2]=p.alpha;ids[3]=p.output;out[0]=p.channels;out[1]=p.pixels;out[2]=p.lut.size();out[3]=p.generator_calls;out[4]=p.generator_ns;out[5]=p.lookup_calls;return 0;}catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}

extern "C" int gpi8p_plprelu_job_count(void* h){try{auto* r=gesture_i8_pruned_bridge::Checked(h);return r->raw_profile==6?qiming_prelu_fixed::kJobCount:0;}catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
extern "C" int gpi8p_plprelu_job_info(void* h,int ordinal,int out[8]){try{auto* r=gesture_i8_pruned_bridge::Checked(h);if(r->raw_profile!=6||!r->delegate)throw std::invalid_argument("Explicit profile6 required");return qprelu_delegate_job_info(r->delegate.get(),ordinal,out);}catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}

extern "C" int gpi8p_layer_copy_stats(void* h,int ordinal,int* node,uint64_t out[12]){try{auto* r=gesture_i8_pruned_bridge::Checked(h);std::lock_guard<std::mutex> lock(r->mutex);if(!node||!out||!r->raw_profile)throw std::invalid_argument("Fixed raw profile copy stats required");if(r->raw_profile==6){if(ordinal<0||size_t(ordinal)>=qiming_prelu_fixed::kJobCount)throw std::out_of_range("Copy job ordinal");*node=qiming_prelu_fixed::kJobs[ordinal].node;}else{size_t n;auto* s=qiming_raw::Specs(r->raw_profile,&n);if(ordinal<0||size_t(ordinal)>=n)throw std::out_of_range("Copy layer ordinal");*node=s[ordinal].node;}auto data=r->hardware_owner->CopyStats(static_cast<qiming_shared::Profile>(r->raw_profile),*node);std::copy(data.begin(),data.end(),out);return 0;}catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}

extern "C" int gpi8p_mean_lut_info(void* h,uint64_t out[6]){
 try{auto* r=gesture_i8_pruned_bridge::Checked(h);if(!out)throw std::invalid_argument("Mean metadata output required");
 out[0]=r->mean58_integer?1:0;out[1]=58;out[2]=49;out[3]=672;out[4]=12496;
 out[5]=hand_mean_integer::mean_calls.load(std::memory_order_relaxed);return 0;
 }catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}

extern "C" int gpi8p_resize_neon_info(void* h,uint64_t out[8]){
 try{auto* r=gesture_i8_pruned_bridge::Checked(h);if(!out)throw std::invalid_argument("Resize info output required");
 out[0]=r->palm_resize_neon?1:0;out[1]=85;out[2]=101;
 out[3]=palm_resize_integer::resize85_calls.load(std::memory_order_relaxed);out[4]=palm_resize_integer::resize101_calls.load(std::memory_order_relaxed);
 out[5]=6;out[6]=12;out[7]=256;return 0;
 }catch(const std::exception& e){return gesture_i8_pruned_bridge::Fail(e);}}
