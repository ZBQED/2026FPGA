#ifndef GESTURE_PL_TFLITE_DELEGATE_H_
#define GESTURE_PL_TFLITE_DELEGATE_H_
#include <stdint.h>
#include "tensorflow/lite/c/common.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Creation opens the actual device. A missing device is an explicit error. */
TfLiteDelegate *gp_tflite_delegate_create(const char *device);
void gp_tflite_delegate_delete(TfLiteDelegate *delegate);
const char *gp_tflite_delegate_error(void);
/* jobs, hardware elapsed ns, copied input bytes, copied output bytes. */
int gp_tflite_delegate_stats(TfLiteDelegate *delegate, uint64_t out[4]);
#ifdef __cplusplus
}
#endif
#endif
