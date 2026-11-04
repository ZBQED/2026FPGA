#ifndef KEYPOINT_CONV_H
#define KEYPOINT_CONV_H
/* ABI 1: all tensors float32, little endian. N=1, input/output NHWC.
 * Conv weights OHWI; depthwise weights 1,H,W,C (depth multiplier one).
 * All pointers are separate non-overlapping DMA ranges. output is the full NHWC
 * tensor; only [START, START+COUNT) flattened output pixels are written.
 * A zero COUNT is a legal no-op. Bias is required, use zero values if absent.
 * Return 0 success; -1 invalid config. Validation occurs before tensor access.
 * Float accumulation follows kernel_h, kernel_w, input_c order; bias is added
 * after products, matching TFLite reference arithmetic order. No quantization.
 */
enum KeypointConfig {
    KP_ABI=0, KP_MODE, KP_IH, KP_IW, KP_IC, KP_OH, KP_OW, KP_OC,
    KP_KH, KP_KW, KP_SH, KP_SW, KP_PAD_TOP, KP_PAD_LEFT,
    KP_ACTIVATION, KP_START, KP_COUNT, KP_CONFIG_WORDS
};
enum { KP_ABI_VERSION=1, KP_CONV=0, KP_DEPTHWISE=1,
       KP_NONE=0, KP_RELU=1, KP_RELU6=6,
       KP_MAX_CHANNELS=1152, KP_MAX_REDUCTION=1152,
       KP_MAX_TENSOR_FLOATS=2097152, KP_MAX_WEIGHT_FLOATS=1048576,
       KP_PIXELS=8, KP_LANES=8 };
#ifdef __cplusplus
extern "C" {
#endif
int keypoint_conv_f32(const float *input, const float *weights,
                      const float *bias, float *output, const int *config);
#ifdef __cplusplus
}
#endif
#endif
