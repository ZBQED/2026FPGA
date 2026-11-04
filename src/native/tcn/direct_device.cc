#include "i8_client.h"
#include <algorithm>
#include <cerrno>
#include <cstring>
#include <cstdlib>
#include <string>
#include <unistd.h>
namespace gesture_i8_pruned {
static std::runtime_error DirectError(const char* what){return std::runtime_error(std::string(what)+": "+std::strerror(errno));}
static bool ChainLayout(InputView x,void* mapping,const uint64_t sizes[4],gpi8p_job& job,std::vector<std::pair<size_t,size_t>>& guards){
 const size_t slot0=64,slot1=(2u<<20)+192;
 const uintptr_t offset=reinterpret_cast<uintptr_t>(x.data())-reinterpret_cast<uintptr_t>(mapping);
 const bool resident=offset==slot0||offset==slot1;
 job.offset[0]=resident?offset:slot0;
 job.offset[1]=sizes[1]?(4u<<20)+512:0;
 job.offset[2]=(6u<<20)+768;
 job.offset[3]=job.offset[0]==slot0?slot1:slot0;
 guards={{0,64}};
 for(int k=0;k<4;k++)if(sizes[k])guards.emplace_back(job.offset[k]+sizes[k],job.offset[k]+sizes[k]+64);
 return resident;
}
uint64_t Device::RunInt8Into(InputView x,const std::vector<int8_t>& w,const Config& c,const std::vector<int32_t>& params,OutputView output){
 if(getpid()!=pid_)throw std::runtime_error("INT8 device cannot cross fork");
 std::lock_guard<std::mutex> lock(*mutex_);
 last_copy_.fill(0);uint64_t layout_begin=CopyNow(),phase=0,guard_begin=0;
 if(fd_<0||poisoned_)throw std::runtime_error("Closed/quarantined INT8 client");
 if(!int8_ready_){gpi8p_info info{};if(ioctl(fd_,GPI8_IOCTL_INFO_INT8,&info)||info.magic!=GPI8_MAGIC||info.abi!=GPI8_ABI_INT8||info.features!=15)throw std::runtime_error("Explicit INT8 output extension not loaded");int8_ready_=true;}
 const uint64_t ni=uint64_t(c[4])*c[5]*c[6],nw=uint64_t(c[9])*c[10]*c[11]*(c[2]==0?c[6]:1),no=uint64_t(c[7])*c[8]*c[9];
 if(!output||x.size()!=ni||w.size()!=nw||params.size()!=size_t(c[9])*4)throw std::invalid_argument("Exact INT8 output tensor/parameter lengths required");
 gpi8p_job job{};std::copy(c.begin(),c.end(),job.config);job.timeout_ms=30000;
 uint64_t sizes[4]={(ni+7)&~uint64_t(7),(nw+7)&~uint64_t(7),uint64_t(c[9])*16,(no+7)&~uint64_t(7)},cursor=64;
 std::vector<std::pair<size_t,size_t>> guards{{0,64}};
 const bool resident_input=ChainLayout(x,mapping_,sizes,job,guards);
 uint64_t checked[4];if(cursor>GPI8_POOL_BYTES||gpi8p_validate_int8(&job,GPI8_POOL_BYTES,checked))throw std::invalid_argument("Invalid INT8 output coherent layout");
 output.resize(no);auto* memory=static_cast<unsigned char*>(mapping_);
 last_copy_[5]+=CopyNow()-layout_begin;phase=CopyNow();
 if(!resident_input)std::memcpy(memory+job.offset[0],x.data(),x.size());std::memset(memory+job.offset[0]+ni,0,sizes[0]-ni);
 last_copy_[1]+=CopyNow()-phase;phase=CopyNow();
 std::memcpy(memory+job.offset[1],w.data(),w.size());std::memset(memory+job.offset[1]+nw,0,sizes[1]-nw);
 last_copy_[2]+=CopyNow()-phase;phase=CopyNow();
 std::memcpy(memory+job.offset[2],params.data(),sizes[2]);
 last_copy_[3]+=CopyNow()-phase;phase=CopyNow();
 for(auto range:guards)std::memset(memory+range.first,0xa5,range.second-range.first);
 last_copy_[5]+=CopyNow()-phase;const gpi8p_job submitted=job;__sync_synchronize();
 try{
  phase=CopyNow();
  if(ioctl(fd_,GPI8_IOCTL_RUN_INT8,&job))throw DirectError("Actual INT8 output RUN failed");
  last_copy_[7]+=CopyNow()-phase;guard_begin=CopyNow();
  __sync_synchronize();if(job.result||!job.elapsed_ns||std::memcmp(job.config,submitted.config,sizeof(job.config))||std::memcmp(job.offset,submitted.offset,sizeof(job.offset))||job.timeout_ms!=submitted.timeout_ms||job.reserved[0]||job.reserved[1])throw std::runtime_error("INT8 output completion failed");
  for(auto range:guards)for(size_t k=range.first;k<range.second;k++)if(memory[k]!=0xa5)throw std::runtime_error("INT8 output DMA boundary corruption");
  for(size_t k=no;k<sizes[3];k++)if(memory[job.offset[3]+k])throw std::runtime_error("INT8 output nonzero tail");
  last_copy_[6]+=CopyNow()-guard_begin;phase=CopyNow();
  if(output.resident_result)*output.resident_result=reinterpret_cast<int8_t*>(memory+job.offset[3]);
  else std::memcpy(output.data(),memory+job.offset[3],no);
  last_copy_[4]+=CopyNow()-phase;last_copy_[0]=1;last_copy_[8]=ni;last_copy_[9]=nw;last_copy_[10]=params.size()*4;last_copy_[11]=no;
 }catch(...){poisoned_=true;throw;}
 stats_[0]++;stats_[1]+=job.elapsed_ns;stats_[2]+=ni+nw+params.size()*4+128;stats_[3]+=no;return job.elapsed_ns;
}
uint64_t Device::RunPreluInto(InputView x,const std::vector<int8_t>& weights,const Config& c,const std::vector<int32_t>& params,OutputView output){
 if(getpid()!=pid_)throw std::runtime_error("PReLU device cannot cross fork");
 std::lock_guard<std::mutex> lock(*mutex_);
 last_copy_.fill(0);uint64_t layout_begin=CopyNow(),phase=0,guard_begin=0;
 if(fd_<0||poisoned_)throw std::runtime_error("Closed/quarantined PReLU device");
 if(!prelu_ready_){
  gpi8p_info info{};
  if(ioctl(fd_,GPI8_IOCTL_INFO_PRELU,&info)||info.magic!=GPI8_MAGIC||info.abi!=GPI8_ABI_PRELU||info.features!=31||
   info.pool_bytes!=GPI8_POOL_BYTES||info.config_words!=32||info.max_tensor_elements!=GPI8_MAX_TENSOR||info.max_weight_elements!=GPI8_MAX_WEIGHTS||
   info.max_channels!=GPI8_MAX_CHANNELS||info.max_dimension!=GPI8_MAX_DIM||info.reserved[0]||info.reserved[1]||info.reserved[2])
   throw std::runtime_error("Explicit ABI4/features31 PReLU/fusion capability required");
  prelu_ready_=true;
 }
 const uint64_t ni=uint64_t(c[4])*c[5]*c[6],no=uint64_t(c[7])*c[8]*c[9];
 const uint64_t nw=c[3]==2?0:uint64_t(c[9])*c[10]*c[11]*(c[2]==0?c[6]:1);
 const uint64_t np=uint64_t(c[23])*8;
 if(!output||!x.data()||x.size()!=ni||weights.size()!=nw||params.size()*4!=np)throw std::invalid_argument("Exact PReLU tensor/parameter spans required");
 gpi8p_job job{};std::copy(c.begin(),c.end(),job.config);job.timeout_ms=30000;
 uint64_t sizes[4]={(ni+7)&~uint64_t(7),(nw+7)&~uint64_t(7),np,(no+7)&~uint64_t(7)},cursor=64;
 std::vector<std::pair<size_t,size_t>> guards{{0,64}};
 const bool resident_input=ChainLayout(x,mapping_,sizes,job,guards);
 uint64_t checked[4];
 if(cursor>GPI8_POOL_BYTES||gpi8p_validate_prelu(&job,GPI8_POOL_BYTES,checked)||!std::equal(sizes,sizes+4,checked))throw std::invalid_argument("PReLU/fusion ABI4 coherent layout rejected");
 output.resize(no);auto* memory=static_cast<unsigned char*>(mapping_);
 last_copy_[5]+=CopyNow()-layout_begin;phase=CopyNow();
 if(!resident_input)std::memcpy(memory+job.offset[0],x.data(),ni);std::memset(memory+job.offset[0]+ni,0,sizes[0]-ni);
 last_copy_[1]+=CopyNow()-phase;phase=CopyNow();
 if(nw){std::memcpy(memory+job.offset[1],weights.data(),nw);std::memset(memory+job.offset[1]+nw,0,sizes[1]-nw);}
 last_copy_[2]+=CopyNow()-phase;phase=CopyNow();
 std::memcpy(memory+job.offset[2],params.data(),np);last_copy_[3]+=CopyNow()-phase;phase=CopyNow();std::memset(memory+job.offset[3]+no,0x7f,sizes[3]-no);
 for(auto range:guards)std::memset(memory+range.first,0xa5,range.second-range.first);
 last_copy_[5]+=CopyNow()-phase;const gpi8p_job submitted=job;__sync_synchronize();
 try{
  phase=CopyNow();
  if(ioctl(fd_,GPI8_IOCTL_RUN_PRELU,&job))throw std::runtime_error(std::string("Actual ABI4 PReLU/fusion RUN failed: ")+std::strerror(errno));
  last_copy_[7]+=CopyNow()-phase;guard_begin=CopyNow();
  __sync_synchronize();
  if(job.result||!job.elapsed_ns||std::memcmp(job.config,submitted.config,sizeof(job.config))||std::memcmp(job.offset,submitted.offset,sizeof(job.offset))||
   job.timeout_ms!=submitted.timeout_ms||job.reserved[0]||job.reserved[1])throw std::runtime_error("PReLU/fusion completion metadata changed");
  for(auto range:guards)for(size_t i=range.first;i<range.second;++i)if(memory[i]!=0xa5)throw std::runtime_error("PReLU/fusion DMA canary changed");
  const char* diagnostic=std::getenv("GQ_PRELU_VALIDATE_READONLY");
  if(diagnostic&&diagnostic[0]=='1'&&diagnostic[1]=='\0'&&(std::memcmp(memory+job.offset[0],x.data(),ni)||(nw&&std::memcmp(memory+job.offset[1],weights.data(),nw))||std::memcmp(memory+job.offset[2],params.data(),np)))
   throw std::runtime_error("PReLU/fusion read-only DMA payload changed");
  for(size_t i=ni;i<sizes[0];++i)if(memory[job.offset[0]+i])throw std::runtime_error("PReLU input padding changed");
  for(size_t i=nw;i<sizes[1];++i)if(memory[job.offset[1]+i])throw std::runtime_error("PReLU weight padding changed");
  for(size_t i=no;i<sizes[3];++i)if(memory[job.offset[3]+i])throw std::runtime_error("PReLU output tail not zero");
  last_copy_[6]+=CopyNow()-guard_begin;phase=CopyNow();
  if(output.resident_result)*output.resident_result=reinterpret_cast<int8_t*>(memory+job.offset[3]);
  else std::memcpy(output.data(),memory+job.offset[3],no);
  last_copy_[4]+=CopyNow()-phase;last_copy_[0]=1;last_copy_[8]=ni;last_copy_[9]=nw;last_copy_[10]=params.size()*4;last_copy_[11]=no;
 }catch(...){poisoned_=true;output.clear();throw;}
 ++stats_[0];stats_[1]+=job.elapsed_ns;stats_[2]+=ni+nw+np+128;stats_[3]+=no;
 return job.elapsed_ns; // START write -> DONE polling confirmation, includes polling granularity.
}
std::array<uint64_t,12> Device::LastCopyStats(){if(getpid()!=pid_)throw std::runtime_error("Foreign copy stats");std::lock_guard<std::mutex> lock(*mutex_);return last_copy_;}
}
