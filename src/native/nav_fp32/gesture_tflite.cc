#include <cstring>
#include <cstdlib>
#include <cstdint>
#include <memory>
#include <string>
#include "tensorflow/lite/interpreter.h"
#include "tensorflow/lite/kernels/register.h"
#include "tensorflow/lite/model_builder.h"
#ifdef GESTURE_USE_XNNPACK
#include "tensorflow/lite/delegates/xnnpack/xnnpack_delegate.h"
#endif
#ifdef GESTURE_USE_PL
#include "pl_delegate.h"
#include "gesture_pl_client.h"
#endif

struct Runtime {
  std::unique_ptr<tflite::FlatBufferModel> model;
#ifdef GESTURE_USE_XNNPACK
  // Interpreter must be destroyed before the delegate, and both before model.
  std::unique_ptr<TfLiteDelegate, void (*)(TfLiteDelegate *)> delegate{nullptr, TfLiteXNNPackDelegateDelete};
#endif
#ifdef GESTURE_USE_PL
  std::unique_ptr<TfLiteDelegate, void (*)(TfLiteDelegate *)> delegate{nullptr, gp_tflite_delegate_delete};
#endif
  std::unique_ptr<tflite::Interpreter> interpreter;
};
static thread_local std::string last_error;
extern "C" {
const char *gtf_error() { return last_error.c_str(); }
void *gtf_open(const char *path, int threads) {
  auto runtime = std::make_unique<Runtime>();
  runtime->model = tflite::FlatBufferModel::BuildFromFile(path);
  if (!runtime->model) { last_error = "Cannot load TFLite model"; return nullptr; }
  tflite::ops::builtin::BuiltinOpResolverWithoutDefaultDelegates resolver;
  if (tflite::InterpreterBuilder(*runtime->model, resolver)(&runtime->interpreter) != kTfLiteOk) {
    last_error = "Cannot build TFLite interpreter"; return nullptr;
  }
  runtime->interpreter->SetNumThreads(threads > 0 ? threads : 1);
#ifdef GESTURE_USE_XNNPACK
  auto options = TfLiteXNNPackDelegateOptionsDefault();
  options.num_threads = threads > 0 ? threads : 1;
  options.flags &= ~TFLITE_XNNPACK_DELEGATE_FLAG_FORCE_FP16;
  runtime->delegate.reset(TfLiteXNNPackDelegateCreate(&options));
  if (!runtime->delegate || runtime->interpreter->ModifyGraphWithDelegate(runtime->delegate.get()) != kTfLiteOk) {
    last_error = "Cannot apply Cortex-A9 XNNPACK delegate"; return nullptr;
  }
#endif
#ifdef GESTURE_USE_PL
  runtime->delegate.reset(gp_tflite_delegate_create(std::getenv("GESTURE_PL_DEVICE")));
  if (!runtime->delegate) { last_error = gp_tflite_delegate_error(); return nullptr; }
  if (runtime->interpreter->ModifyGraphWithDelegate(runtime->delegate.get()) != kTfLiteOk) {
    last_error = std::string("Cannot apply PL delegate: ") + gp_tflite_delegate_error(); return nullptr;
  }
  int pl_partitions = 0;
  for (int index : runtime->interpreter->execution_plan()) {
    auto *entry = runtime->interpreter->node_and_registration(index);
    if (entry && entry->first.delegate == runtime->delegate.get()) ++pl_partitions;
  }
  if (!pl_partitions) { last_error = "No supported Conv2D/DepthwiseConv2D nodes delegated to PL"; return nullptr; }
#endif
  if (runtime->interpreter->AllocateTensors() != kTfLiteOk) {
    last_error = "Cannot allocate tensors"; return nullptr;
  }
  last_error.clear();
  return runtime.release();
}
void gtf_close(void *handle) { delete static_cast<Runtime *>(handle); }
const char *gtf_backend() {
#ifdef GESTURE_USE_PL
  return gp_backend_name();
#elif defined(GESTURE_USE_XNNPACK)
  return "xnnpack-cortex-a9-neon-vfpv3";
#else
  return "builtin-cortex-a9-neon-vfpv3";
#endif
}
int gtf_delegate_partitions(void *handle) {
  int count = 0;
#if defined(GESTURE_USE_XNNPACK) || defined(GESTURE_USE_PL)
  auto *r = static_cast<Runtime *>(handle);
  for (int index : r->interpreter->execution_plan()) {
    auto *entry = r->interpreter->node_and_registration(index);
    if (entry && entry->first.delegate == r->delegate.get()) ++count;
  }
#endif
  return count;
}
int gtf_pl_stats(void *handle, uint64_t out[4]) {
  if (!handle || !out) return -1;
#ifdef GESTURE_USE_PL
  return gp_tflite_delegate_stats(static_cast<Runtime *>(handle)->delegate.get(), out);
#else
  std::memset(out, 0, 4 * sizeof(uint64_t));
  return 0;
#endif
}
int gtf_count(void *handle, int output) {
  auto &i = static_cast<Runtime *>(handle)->interpreter;
  return output ? i->outputs().size() : i->inputs().size();
}
const TfLiteTensor *get_tensor(void *handle, int output, int ordinal) {
  auto &i = static_cast<Runtime *>(handle)->interpreter;
  const auto &ids = output ? i->outputs() : i->inputs();
  if (ordinal < 0 || static_cast<size_t>(ordinal) >= ids.size()) return nullptr;
  return i->tensor(ids[ordinal]);
}
int gtf_type(void *handle, int output, int ordinal) {
  const auto *t = get_tensor(handle, output, ordinal); return t ? t->type : -1;
}
int gtf_rank(void *handle, int output, int ordinal) {
  const auto *t = get_tensor(handle, output, ordinal); return t ? t->dims->size : -1;
}
int gtf_dim(void *handle, int output, int ordinal, int axis) {
  const auto *t = get_tensor(handle, output, ordinal);
  return t && axis >= 0 && axis < t->dims->size ? t->dims->data[axis] : -1;
}
int gtf_bytes(void *handle, int output, int ordinal) {
  const auto *t = get_tensor(handle, output, ordinal); return t ? t->bytes : -1;
}
const char *gtf_name(void *handle, int output, int ordinal) {
  const auto *t = get_tensor(handle, output, ordinal); return t && t->name ? t->name : "";
}
int gtf_input(void *handle, int ordinal, const void *data, int bytes) {
  const auto *t = get_tensor(handle, 0, ordinal);
  if (!t || bytes < 0 || static_cast<size_t>(bytes) != t->bytes) { last_error = "Input byte size mismatch"; return -1; }
  std::memcpy(t->data.raw, data, bytes); return 0;
}
int gtf_invoke(void *handle) {
  if (static_cast<Runtime *>(handle)->interpreter->Invoke() != kTfLiteOk) {
#ifdef GESTURE_USE_PL
    last_error = std::string("PL invoke failed: ") + gp_tflite_delegate_error();
#else
    last_error = "Invoke failed";
#endif
    return -1;
  }
  return 0;
}
int gtf_output(void *handle, int ordinal, void *data, int bytes) {
  const auto *t = get_tensor(handle, 1, ordinal);
  if (!t || bytes < 0 || static_cast<size_t>(bytes) != t->bytes) { last_error = "Output byte size mismatch"; return -1; }
  std::memcpy(data, t->data.raw, bytes); return 0;
}
}
