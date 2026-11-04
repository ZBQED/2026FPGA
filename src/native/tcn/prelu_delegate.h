#pragma once
#include "tensorflow/lite/c/common.h"
TfLiteDelegate* qprelu_delegate_create(const char* asset_root);
int qprelu_delegate_stats(TfLiteDelegate*,uint64_t out[4]);
int qprelu_delegate_layer_stats(TfLiteDelegate*,int ordinal,int* node,uint64_t out[8]);
int qprelu_delegate_job_info(TfLiteDelegate*,int ordinal,int out[8]);
