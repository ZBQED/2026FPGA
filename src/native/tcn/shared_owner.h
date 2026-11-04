#ifndef QIMING_SHARED_PERSON_OWNER_H
#define QIMING_SHARED_PERSON_OWNER_H
#include "i8_client.h"
#include "owner_broker.h"
#include <memory>
namespace qiming_shared {
using Profile=qiming_owner_candidate::Profile;
using Broker=qiming_owner_candidate::OwnerBroker<gesture_i8_pruned::Device>;
class SharedOwner;
class Call {
 public:
  Call(SharedOwner&,Profile);~Call();void Commit();
  Call(const Call&)=delete;Call& operator=(const Call&)=delete;
 private:
  friend class SharedOwner;friend int RunPersonRaw(const int8_t*,const int8_t*,int32_t*);
  SharedOwner& owner_;Profile profile_;std::unique_ptr<Broker::Invocation> transaction_;
};
class SharedOwner {
 public:
  explicit SharedOwner(std::shared_ptr<gesture_i8_pruned::Device>);
  std::unique_ptr<Call> Begin(Profile);
  uint64_t RunPose(int,const std::vector<int8_t>&,const std::vector<int8_t>&,
                   const gesture_i8_pruned::Config&,std::vector<int32_t>*);
  uint64_t RunRaw(Profile,int,const std::vector<int8_t>&,const std::vector<int8_t>&,const gesture_i8_pruned::Config&,std::vector<int32_t>*);
  uint64_t RunInt8(Profile,int,gesture_i8_pruned::InputView,const std::vector<int8_t>&,const gesture_i8_pruned::Config&,const std::vector<int32_t>&,std::vector<int8_t>*);
  void RegisterPalmPreluParams(int,std::vector<int32_t>);
  uint64_t RunPalmPrelu(int,gesture_i8_pruned::InputView,const std::vector<int8_t>&,const gesture_i8_pruned::Config&,std::vector<int8_t>*);
  uint64_t RunInt8Into(Profile,int,gesture_i8_pruned::InputView,const std::vector<int8_t>&,const gesture_i8_pruned::Config&,const std::vector<int32_t>&,gesture_i8_pruned::OutputView);
  uint64_t RunPalmPreluInto(int,gesture_i8_pruned::InputView,const std::vector<int8_t>&,const gesture_i8_pruned::Config&,gesture_i8_pruned::OutputView);
  std::array<uint64_t,12> CopyStats(Profile,int);
  std::array<uint64_t,4> PoseStats();
  qiming_owner_candidate::Status Stats(Profile);
  bool Quarantined();
  void RegisterTCNFixed(Profile,int,const gesture_i8_pruned::Config&,const std::vector<int8_t>&,const std::vector<int32_t>&);
  uint64_t RunTCNInto(int,gesture_i8_pruned::InputView,gesture_i8_pruned::OutputView);
 private:
  friend class Call;friend int RunPersonRaw(const int8_t*,const int8_t*,int32_t*);
  Broker broker_;
};
std::shared_ptr<SharedOwner> RequireExplicitOwner();
std::shared_ptr<SharedOwner> OwnerFromExplicitHandle(void*);
int RunPersonRaw(const int8_t*,const int8_t*,int32_t*);
}
extern "C" {
void* gpo_owner_open();
int gpo_owner_close(void*);
const char* gpo_owner_error();
int gpo_owner_stats(void*,int,uint64_t out[7]);
int gpo_person_infer(void*,const char* profile,const char* weights_sha,
                     const char* net_sha,const uint8_t*,int,int,void*,int,int*);
}
#endif
