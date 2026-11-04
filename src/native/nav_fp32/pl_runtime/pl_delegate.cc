#include "pl_delegate.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <limits>
#include <memory>
#include <mutex>
#include <new>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "tensorflow/lite/builtin_ops.h"
#include "tensorflow/lite/c/builtin_op_data.h"
#include "tensorflow/lite/delegates/utils/simple_delegate.h"
#include "keypoint_conv.h"
#include "gesture_pl_client.h"

namespace {
thread_local std::string last_error;
struct Device {
  void *handle = nullptr;
  std::string path;
  ~Device() { if (handle) gp_close_device(handle); }
};
std::mutex shared_device_mutex;
std::weak_ptr<Device> shared_device;
struct Job {
  int input = -1, weights = -1, bias = -1, output = -1;
  std::array<int, KP_CONFIG_WORDS> config{};
  std::array<size_t, 4> floats{};
  std::vector<float> zero_bias;
};

const TfLiteTensor *Tensor(TfLiteContext *ctx, int index) {
  return index >= 0 && static_cast<size_t>(index) < ctx->tensors_size
      ? &ctx->tensors[index] : nullptr;
}
bool Shape(const TfLiteTensor *t, int rank, size_t *elements) {
  if (!t || t->type != kTfLiteFloat32 || !t->dims || t->dims->size != rank) return false;
  size_t count = 1;
  for (int i = 0; i < rank; ++i) {
    if (t->dims->data[i] <= 0 || count > SIZE_MAX / static_cast<size_t>(t->dims->data[i])) return false;
    count *= t->dims->data[i];
  }
  if (count > SIZE_MAX / sizeof(float) || t->bytes != count * sizeof(float)) return false;
  *elements = count;
  return true;
}
bool KernelSize(int k) { return k == 1 || k == 2 || k == 3 || k == 5; }
bool BuildJob(const TfLiteRegistration *reg, const TfLiteNode *node, TfLiteContext *ctx, Job *job) {
  if (!reg || !node || !node->builtin_data || !node->inputs || !node->outputs ||
      (node->inputs->size != 2 && node->inputs->size != 3) || node->outputs->size != 1) return false;
  const bool depthwise = reg->builtin_code == kTfLiteBuiltinDepthwiseConv2d;
  if (!depthwise && reg->builtin_code != kTfLiteBuiltinConv2d) return false;
  job->input = node->inputs->data[0];
  job->weights = node->inputs->data[1];
  job->bias = node->inputs->size == 3 ? node->inputs->data[2] : -1;
  job->output = node->outputs->data[0];
  const auto *x = Tensor(ctx, job->input), *w = Tensor(ctx, job->weights), *y = Tensor(ctx, job->output);
  if (!Shape(x, 4, &job->floats[0]) || !Shape(w, 4, &job->floats[1]) || !Shape(y, 4, &job->floats[3]) ||
      x->dims->data[0] != 1 || y->dims->data[0] != 1) return false;
  auto &c = job->config;
  c[KP_ABI] = KP_ABI_VERSION;
  c[KP_MODE] = depthwise ? KP_DEPTHWISE : KP_CONV;
  c[KP_IH] = x->dims->data[1]; c[KP_IW] = x->dims->data[2]; c[KP_IC] = x->dims->data[3];
  c[KP_OH] = y->dims->data[1]; c[KP_OW] = y->dims->data[2]; c[KP_OC] = y->dims->data[3];
  c[KP_KH] = w->dims->data[1]; c[KP_KW] = w->dims->data[2];
  if (!KernelSize(c[KP_KH]) || !KernelSize(c[KP_KW]) || c[KP_IH] > 512 || c[KP_IW] > 512 ||
      c[KP_OH] > 512 || c[KP_OW] > 512 || c[KP_IC] > KP_MAX_CHANNELS || c[KP_OC] > KP_MAX_CHANNELS ||
      job->floats[0] > KP_MAX_TENSOR_FLOATS || job->floats[3] > KP_MAX_TENSOR_FLOATS ||
      job->floats[1] > KP_MAX_WEIGHT_FLOATS) return false;
  TfLitePadding padding;
  TfLiteFusedActivation activation;
  if (depthwise) {
    const auto *p = static_cast<const TfLiteDepthwiseConvParams *>(node->builtin_data);
    if (p->depth_multiplier != 1 || p->dilation_height_factor != 1 || p->dilation_width_factor != 1 ||
        c[KP_IC] != c[KP_OC] || w->dims->data[0] != 1 || w->dims->data[3] != c[KP_OC]) return false;
    c[KP_SH] = p->stride_height; c[KP_SW] = p->stride_width;
    padding = p->padding; activation = p->activation;
  } else {
    const auto *p = static_cast<const TfLiteConvParams *>(node->builtin_data);
    if (p->dilation_height_factor != 1 || p->dilation_width_factor != 1 ||
        w->dims->data[0] != c[KP_OC] || w->dims->data[3] != c[KP_IC] ||
        c[KP_KH] * c[KP_KW] * c[KP_IC] > KP_MAX_REDUCTION) return false;
    c[KP_SH] = p->stride_height; c[KP_SW] = p->stride_width;
    padding = p->padding; activation = p->activation;
  }
  if ((c[KP_SH] != 1 && c[KP_SH] != 2) || (c[KP_SW] != 1 && c[KP_SW] != 2)) return false;
  if (activation == kTfLiteActNone) c[KP_ACTIVATION] = KP_NONE;
  else if (activation == kTfLiteActRelu) c[KP_ACTIVATION] = KP_RELU;
  else if (activation == kTfLiteActRelu6) c[KP_ACTIVATION] = KP_RELU6;
  else return false;
  for (int axis = 0; axis < 2; ++axis) {
    const int input = c[KP_IH + axis], output = c[KP_OH + axis];
    const int kernel = c[KP_KH + axis], stride = c[KP_SH + axis];
    int expected = 0, pad = 0;
    if (padding == kTfLitePaddingSame) {
      expected = (input + stride - 1) / stride;
      pad = std::max(0, (output - 1) * stride + kernel - input) / 2;
    } else if (padding == kTfLitePaddingValid) {
      expected = std::max(0, (input - kernel + stride) / stride);
    } else return false;
    if (output != expected || pad > 4) return false;
    c[KP_PAD_TOP + axis] = pad;
  }
  job->floats[2] = c[KP_OC];
  if (job->bias >= 0) {
    size_t bias_floats = 0;
    if (!Shape(Tensor(ctx, job->bias), 1, &bias_floats) || bias_floats != job->floats[2]) return false;
  }
  c[KP_START] = 0; c[KP_COUNT] = c[KP_OH] * c[KP_OW];
  return true;
}

TfLiteStatus Fail(TfLiteContext *ctx, const char *message) {
  last_error = message ? message : "PL runtime failed without an error message";
  if (ctx && ctx->ReportError) ctx->ReportError(ctx, "Gesture PL: %s", last_error.c_str());
  return kTfLiteError;
}

class Kernel final : public tflite::SimpleDelegateKernelInterface {
 public:
  explicit Kernel(std::shared_ptr<Device> device) : device_(std::move(device)) {}
  TfLiteStatus Init(TfLiteContext *ctx, const TfLiteDelegateParams *params) override {
    try {
      std::unordered_set<int> boundary;
      for (int i = 0; i < params->output_tensors->size; ++i) boundary.insert(params->output_tensors->data[i]);
      for (int i = 0; i < params->nodes_to_replace->size; ++i) {
        TfLiteNode *node = nullptr; TfLiteRegistration *reg = nullptr;
        if (ctx->GetNodeAndRegistration(ctx, params->nodes_to_replace->data[i], &node, &reg) != kTfLiteOk)
          return Fail(ctx, "Cannot inspect delegated node");
        Job job;
        if (!BuildJob(reg, node, ctx, &job)) return Fail(ctx, "Delegated node shape or parameters changed");
        if (!boundary.count(job.output)) internal_.emplace(job.output, std::vector<float>());
        jobs_.push_back(std::move(job));
      }
      return kTfLiteOk;
    } catch (const std::bad_alloc &) { return Fail(ctx, "Cannot allocate PL partition metadata"); }
  }
  TfLiteStatus Prepare(TfLiteContext *ctx, TfLiteNode *) override {
    try {
      for (auto &job : jobs_) {
        const int ids[4] = {job.input, job.weights, job.bias, job.output};
        for (int i = 0; i < 4; ++i) {
          if (ids[i] < 0 && i == 2) continue;
          const auto *t = Tensor(ctx, ids[i]);
          if (!t || t->type != kTfLiteFloat32 || t->bytes != job.floats[i] * sizeof(float))
            return Fail(ctx, "Dynamic tensor size is unsupported by PL delegate");
        }
        auto internal = internal_.find(job.output);
        if (internal != internal_.end()) internal->second.resize(job.floats[3]);
        if (job.bias < 0) job.zero_bias.assign(job.floats[2], 0.0f);
      }
      return kTfLiteOk;
    } catch (const std::bad_alloc &) { return Fail(ctx, "Cannot allocate PL partition intermediate tensors"); }
  }
  TfLiteStatus Eval(TfLiteContext *ctx, TfLiteNode *) override {
    for (auto &job : jobs_) {
      const float *x = Data(ctx, job.input), *w = Data(ctx, job.weights);
      const float *b = job.bias < 0 ? job.zero_bias.data() : Data(ctx, job.bias);
      float *y = Data(ctx, job.output);
      if (!x || !w || !b || !y) return Fail(ctx, "PL partition boundary tensor is not allocated");
      if (gp_run(device_->handle, x, w, b, y, job.config.data()) != 0) return Fail(ctx, gp_last_error());
    }
    return kTfLiteOk;
  }
 private:
  float *Data(TfLiteContext *ctx, int id) {
    auto it = internal_.find(id);
    if (it != internal_.end()) return it->second.data();
    const auto *t = Tensor(ctx, id);
    return t ? t->data.f : nullptr;
  }
  std::shared_ptr<Device> device_;
  std::vector<Job> jobs_;
  std::unordered_map<int, std::vector<float>> internal_;
};

class Delegate final : public tflite::SimpleDelegateInterface {
 public:
  explicit Delegate(std::shared_ptr<Device> device) : device_(std::move(device)) {}
  bool IsNodeSupportedByDelegate(const TfLiteRegistration *r, const TfLiteNode *n, TfLiteContext *c) const override {
    Job job;
    return BuildJob(r, n, c, &job);
  }
  TfLiteStatus Initialize(TfLiteContext *ctx) override {
    return device_ && device_->handle ? kTfLiteOk : Fail(ctx, "PL device is not open");
  }
  const char *Name() const override {
#ifdef GESTURE_PL_EMULATION
    return "GesturePL-C-simulation-NOT-HARDWARE";
#else
    return "GesturePL-keypoint-conv-ABI1";
#endif
  }
  std::unique_ptr<tflite::SimpleDelegateKernelInterface> CreateDelegateKernelInterface() override {
    return std::make_unique<Kernel>(device_);
  }
  Options DelegateOptions() const override { return Options{}; }
  void Stats(uint64_t out[4]) const { gp_get_stats(device_->handle, out); }
 private:
  std::shared_ptr<Device> device_;
};
}  // namespace

extern "C" TfLiteDelegate *gp_tflite_delegate_create(const char *path) {
  try {
    std::lock_guard<std::mutex> lock(shared_device_mutex);
    const std::string device_path = path && *path ? path : "/dev/gesture-pl0";
    auto device = shared_device.lock();
    if (device && device->path != device_path) {
      last_error = "A different PL device is already open in this process"; return nullptr;
    }
    if (!device) {
      device = std::make_shared<Device>();
      device->path = device_path;
      device->handle = gp_open_device(device_path.c_str());
      if (!device->handle) { last_error = gp_last_error(); return nullptr; }
      shared_device = device;
    }
    auto result = tflite::TfLiteDelegateFactory::CreateSimpleDelegate(std::make_unique<Delegate>(device));
    last_error.clear();
    return result;
  } catch (const std::bad_alloc &) { last_error = "Cannot allocate PL delegate"; return nullptr; }
}
extern "C" void gp_tflite_delegate_delete(TfLiteDelegate *delegate) {
  tflite::TfLiteDelegateFactory::DeleteSimpleDelegate(delegate);
}
extern "C" const char *gp_tflite_delegate_error(void) { return last_error.c_str(); }
extern "C" int gp_tflite_delegate_stats(TfLiteDelegate *delegate, uint64_t out[4]) {
  if (!delegate || !out || !delegate->data_) return -1;
  static_cast<Delegate *>(delegate->data_)->Stats(out);
  return 0;
}
