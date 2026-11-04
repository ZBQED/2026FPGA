#ifndef GESTURE_I8_CLIENT_H
#define GESTURE_I8_CLIENT_H
#include "i8_math.h"
#include <array>
#include <mutex>
#include <memory>
#include <vector>
#include <chrono>
#include <stdexcept>
namespace gesture_i8_pruned {
struct InputView {
 const int8_t* pointer;size_t length;
 InputView(const int8_t* p,size_t n):pointer(p),length(n){}
 InputView(const std::vector<int8_t>& v):pointer(v.data()),length(v.size()){}
 const int8_t* data()const{return pointer;}size_t size()const{return length;}
};
struct OutputView {
 int8_t* pointer;size_t length;int8_t** resident_result=nullptr;
 OutputView(int8_t* p,size_t n):pointer(p),length(n){}
 static OutputView Resident(int8_t** result,size_t n){OutputView v(nullptr,n);v.resident_result=result;return v;}
 explicit operator bool()const{return (pointer||resident_result)&&length;}
 int8_t* data()const{return pointer;}size_t size()const{return length;}
 void resize(size_t n){if((!pointer&&!resident_result)||n!=length)throw std::invalid_argument("Exact fixed output view length required");}
 void clear(){pointer=nullptr;length=0;}
};
inline uint64_t CopyNow(){return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
class Device final {
 public:
  Device();~Device();Device(const Device&)=delete;Device& operator=(const Device&)=delete;
  uint64_t Run(const std::vector<int8_t>& input,const std::vector<int8_t>& weights,const Config& config,std::vector<int32_t>* output);
  uint64_t RunInt8(InputView,const std::vector<int8_t>&,const Config&,const std::vector<int32_t>&,std::vector<int8_t>*);
  uint64_t RunPrelu(InputView,const std::vector<int8_t>&,const Config&,const std::vector<int32_t>&,std::vector<int8_t>*);
  uint64_t RunInt8Into(InputView,const std::vector<int8_t>&,const Config&,const std::vector<int32_t>&,OutputView);
  uint64_t RunPreluInto(InputView,const std::vector<int8_t>&,const Config&,const std::vector<int32_t>&,OutputView);
  std::array<uint64_t,12> LastCopyStats();
  std::array<uint64_t,4> Stats();
 private:
  int fd_=-1;void* mapping_=nullptr;int pid_=0;bool poisoned_=false;bool int8_ready_=false;bool prelu_ready_=false;
  std::unique_ptr<std::mutex> mutex_{new std::mutex};std::array<uint64_t,4> stats_{};std::array<uint64_t,12> last_copy_{};
#ifdef GPI8_CLIENT_TEST_ONLY
  friend struct DeviceTestHooks;
#endif
};
}
#endif
