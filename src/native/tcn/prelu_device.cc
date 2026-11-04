#include "i8_client.h"
#include <algorithm>
#include <cerrno>
#include <cstring>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <unistd.h>
namespace gesture_i8_pruned {
uint64_t Device::RunPrelu(InputView x,const std::vector<int8_t>& weights,const Config& c,const std::vector<int32_t>& params,std::vector<int8_t>* output){
 if(getpid()!=pid_)throw std::runtime_error("PReLU device cannot cross fork");
 std::lock_guard<std::mutex> lock(*mutex_);
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
 for(int index=0;index<4;++index){if(!sizes[index])continue;job.offset[index]=uint32_t(cursor);cursor+=sizes[index];guards.emplace_back(cursor,cursor+64);cursor+=64;}
 uint64_t checked[4];
 if(cursor>GPI8_POOL_BYTES||gpi8p_validate_prelu(&job,GPI8_POOL_BYTES,checked)||!std::equal(sizes,sizes+4,checked))throw std::invalid_argument("PReLU/fusion ABI4 coherent layout rejected");
 output->resize(no);auto* memory=static_cast<unsigned char*>(mapping_);
 std::memcpy(memory+job.offset[0],x.data(),ni);std::memset(memory+job.offset[0]+ni,0,sizes[0]-ni);
 if(nw){std::memcpy(memory+job.offset[1],weights.data(),nw);std::memset(memory+job.offset[1]+nw,0,sizes[1]-nw);}
 std::memcpy(memory+job.offset[2],params.data(),np);std::memset(memory+job.offset[3],0x7f,sizes[3]);
 for(auto range:guards)std::memset(memory+range.first,0xa5,range.second-range.first);
 const gpi8p_job submitted=job;__sync_synchronize();
 try{
  if(ioctl(fd_,GPI8_IOCTL_RUN_PRELU,&job))throw std::runtime_error(std::string("Actual ABI4 PReLU/fusion RUN failed: ")+std::strerror(errno));
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
  std::memcpy(output->data(),memory+job.offset[3],no);
 }catch(...){poisoned_=true;output->clear();throw;}
 ++stats_[0];stats_[1]+=job.elapsed_ns;stats_[2]+=ni+nw+np+128;stats_[3]+=no;
 return job.elapsed_ns; // START write -> DONE polling confirmation, includes polling granularity.
}
}
