#include "i8_client.h"
#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
namespace gesture_i8_pruned {
static std::runtime_error Error(const char* what) {return std::runtime_error(std::string(what)+": "+std::strerror(errno));}
Device::Device() {
  static_assert(sizeof(gpi8p_info)==48 && sizeof(gpi8p_job)==168 && offsetof(gpi8p_job,elapsed_ns)==160,"ABI2 layout");
  pid_=getpid();fd_=open("/dev/gesture-i8-pl0",O_RDWR|O_CLOEXEC|O_NOFOLLOW);
  if(fd_<0)throw Error("Open independent INT8 device");
  try {struct stat st{};if(fstat(fd_,&st)||!S_ISCHR(st.st_mode))throw std::runtime_error("INT8 device is not character device");
    gpi8p_info info{};if(ioctl(fd_,GPI8_IOCTL_INFO,&info))throw Error("Read INT8 ABI info");
    if(info.magic!=GPI8_MAGIC||info.abi!=2||info.pool_bytes!=GPI8_POOL_BYTES||info.config_words!=32||
       info.max_tensor_elements!=GPI8_MAX_TENSOR||info.max_weight_elements!=GPI8_MAX_WEIGHTS||
       info.max_channels!=1152||info.max_dimension!=512||info.features!=7||
       info.reserved[0]||info.reserved[1]||info.reserved[2])throw std::runtime_error("Unexpected INT8 ABI/features");
    mapping_=mmap(nullptr,GPI8_POOL_BYTES,PROT_READ|PROT_WRITE,MAP_SHARED,fd_,0);
    if(mapping_==MAP_FAILED){mapping_=nullptr;throw Error("Map coherent pool");}
  }catch(...){close(fd_);fd_=-1;throw;}
}
Device::~Device(){
  // After fork, the inherited mutex may be permanently owned by a vanished
  // thread. Release only this child's FD/VMA references, never ioctl or lock.
  // The parent's independently retained references keep its DMA lease alive.
  if(getpid()!=pid_){mutex_.release();if(mapping_)munmap(mapping_,GPI8_POOL_BYTES);if(fd_>=0)close(fd_);return;}
  std::lock_guard<std::mutex> lock(*mutex_);if(mapping_)munmap(mapping_,GPI8_POOL_BYTES);if(fd_>=0)close(fd_);
}
uint64_t Device::Run(const std::vector<int8_t>& x,const std::vector<int8_t>& w,const Config& original,std::vector<int32_t>* output) {
  if(getpid()!=pid_)throw std::runtime_error("INT8 device cannot cross fork");
  std::lock_guard<std::mutex> lock(*mutex_);
  if(fd_<0||poisoned_)throw std::runtime_error("Closed/quarantined INT8 client; no retry/fallback");
  const Config c=original;const Span span=Validate(c);
  if(!output||x.size()!=span.input||w.size()!=span.weights)throw std::invalid_argument("Exact signed INT8 tensor lengths required");
  gpi8p_job job{};std::copy(c.begin(),c.end(),job.config);job.timeout_ms=30000;
  uint64_t cursor=64;std::vector<std::pair<size_t,size_t>> guards{{0,64}};
  for(int i:{0,1,3}){job.offset[i]=cursor;cursor+=span.bytes[i];guards.emplace_back(cursor,cursor+64);cursor+=64;}
  uint64_t checked[4];if(cursor>GPI8_POOL_BYTES||gpi8p_validate(&job,GPI8_POOL_BYTES,checked))throw std::invalid_argument("Invalid coherent layout");
  auto* memory=static_cast<unsigned char*>(mapping_);
  output->resize(span.output); // Allocation must succeed before actual hardware begins.
  std::memcpy(memory+job.offset[0],x.data(),x.size());std::memset(memory+job.offset[0]+x.size(),0,span.bytes[0]-x.size());
  std::memcpy(memory+job.offset[1],w.data(),w.size());std::memset(memory+job.offset[1]+w.size(),0,span.bytes[1]-w.size());
  std::memset(memory+job.offset[3],0x7f,span.bytes[3]);
  for(auto p:guards)std::memset(memory+p.first,0xa5,p.second-p.first);
  const gpi8p_job submitted=job;
  try {
    if(ioctl(fd_,GPI8_IOCTL_RUN,&job))throw Error("Actual INT8 hardware RUN failed");
    if(job.result!=0||job.elapsed_ns==0||std::memcmp(job.offset,submitted.offset,sizeof(job.offset))||
       std::memcmp(job.config,submitted.config,sizeof(job.config))||job.reserved[0]||job.reserved[1]||job.timeout_ms!=submitted.timeout_ms)
      throw std::runtime_error("Invalid actual hardware completion");
    for(auto p:guards)for(size_t i=p.first;i<p.second;++i)if(memory[i]!=0xa5)throw std::runtime_error("DMA canary corruption");
    if(std::memcmp(memory+job.offset[0],x.data(),x.size())||std::memcmp(memory+job.offset[1],w.data(),w.size()))
      throw std::runtime_error("Read-only DMA input/weight changed");
    for(size_t i=x.size();i<span.bytes[0];++i)if(memory[job.offset[0]+i])throw std::runtime_error("Read-only input tail changed");
    for(size_t i=w.size();i<span.bytes[1];++i)if(memory[job.offset[1]+i])throw std::runtime_error("Read-only weight tail changed");
    // 0x7f7f7f7f exceeds the worst possible ABI2 RAW magnitude
    // 5*5*1152*255*128=940032000. It cannot be a valid accumulator.
    for(size_t i=span.output*4;i<span.bytes[3];++i)if(memory[job.offset[3]+i])throw std::runtime_error("Nonzero output tail padding");
    // Snapshot the complete DMA payload once. Check every poison word in this
    // private cached vector before returning it to the delegate. On failure the
    // device is poisoned and Eval returns error, so no partial output is used.
    std::memcpy(output->data(),memory+job.offset[3],span.output*4);
    for(size_t i=0;i<span.output;++i)if((*output)[i]==0x7f7f7f7f)
      throw std::runtime_error("Hardware left an output word unwritten");
  }catch(...){poisoned_=true;throw;}
  ++stats_[0];stats_[1]+=job.elapsed_ns;stats_[2]+=x.size()+w.size()+128;stats_[3]+=span.output*4;
  return job.elapsed_ns;
}

uint64_t Device::RunInt8(InputView x,const std::vector<int8_t>& w,const Config& c,const std::vector<int32_t>& params,std::vector<int8_t>* output){
 if(getpid()!=pid_)throw std::runtime_error("INT8 device cannot cross fork");
 std::lock_guard<std::mutex> lock(*mutex_);
 if(fd_<0||poisoned_)throw std::runtime_error("Closed/quarantined INT8 client");
 if(!int8_ready_){gpi8p_info info{};if(ioctl(fd_,GPI8_IOCTL_INFO_INT8,&info)||info.magic!=GPI8_MAGIC||info.abi!=GPI8_ABI_INT8||info.features!=15)throw std::runtime_error("Explicit INT8 output extension not loaded");int8_ready_=true;}
 const uint64_t ni=uint64_t(c[4])*c[5]*c[6],nw=uint64_t(c[9])*c[10]*c[11]*(c[2]==0?c[6]:1),no=uint64_t(c[7])*c[8]*c[9];
 if(!output||x.size()!=ni||w.size()!=nw||params.size()!=size_t(c[9])*4)throw std::invalid_argument("Exact INT8 output tensor/parameter lengths required");
 gpi8p_job job{};std::copy(c.begin(),c.end(),job.config);job.timeout_ms=30000;
 uint64_t sizes[4]={(ni+7)&~uint64_t(7),(nw+7)&~uint64_t(7),uint64_t(c[9])*16,(no+7)&~uint64_t(7)},cursor=64;
 std::vector<std::pair<size_t,size_t>> guards{{0,64}};
 for(int k=0;k<4;k++){job.offset[k]=uint32_t(cursor);cursor+=sizes[k];guards.emplace_back(cursor,cursor+64);cursor+=64;}
 uint64_t checked[4];if(cursor>GPI8_POOL_BYTES||gpi8p_validate_int8(&job,GPI8_POOL_BYTES,checked))throw std::invalid_argument("Invalid INT8 output coherent layout");
 output->resize(no);auto* memory=static_cast<unsigned char*>(mapping_);
 std::memcpy(memory+job.offset[0],x.data(),x.size());std::memset(memory+job.offset[0]+ni,0,sizes[0]-ni);
 std::memcpy(memory+job.offset[1],w.data(),w.size());std::memset(memory+job.offset[1]+nw,0,sizes[1]-nw);
 std::memcpy(memory+job.offset[2],params.data(),sizes[2]);
 for(auto range:guards)std::memset(memory+range.first,0xa5,range.second-range.first);
 __sync_synchronize();
 try{
  if(ioctl(fd_,GPI8_IOCTL_RUN_INT8,&job))throw Error("Actual INT8 output RUN failed");
  __sync_synchronize();if(job.result||!job.elapsed_ns)throw std::runtime_error("INT8 output completion failed");
  for(auto range:guards)for(size_t k=range.first;k<range.second;k++)if(memory[k]!=0xa5)throw std::runtime_error("INT8 output DMA boundary corruption");
  for(size_t k=no;k<sizes[3];k++)if(memory[job.offset[3]+k])throw std::runtime_error("INT8 output nonzero tail");
  std::memcpy(output->data(),memory+job.offset[3],no);
 }catch(...){poisoned_=true;throw;}
 stats_[0]++;stats_[1]+=job.elapsed_ns;stats_[2]+=ni+nw+params.size()*4+128;stats_[3]+=no;return job.elapsed_ns;
}

std::array<uint64_t,4> Device::Stats(){if(getpid()!=pid_)throw std::runtime_error("Forked INT8 client");std::lock_guard<std::mutex> lock(*mutex_);return stats_;}
}
