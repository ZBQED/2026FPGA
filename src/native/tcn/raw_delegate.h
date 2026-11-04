#pragma once
#include "tensorflow/lite/c/common.h"
TfLiteDelegate* qraw_delegate_create(int profile);
int qraw_delegate_stats(TfLiteDelegate*,uint64_t out[4]);
int qraw_delegate_layer_stats(TfLiteDelegate*,int ordinal,int* node,uint64_t out[8]);
