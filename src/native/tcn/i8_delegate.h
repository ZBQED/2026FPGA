#ifndef GESTURE_I8_DELEGATE_H
#define GESTURE_I8_DELEGATE_H
#include <cstdint>
#include "tensorflow/lite/c/common.h"
extern "C" TfLiteDelegate* gpi8p_delegate_create(int bits);
extern "C" void gpi8p_delegate_delete(TfLiteDelegate* delegate);
extern "C" const char* gpi8p_delegate_error();
extern "C" int gpi8p_delegate_stats(TfLiteDelegate* delegate,uint64_t out[4]);
extern "C" int gpi8p_delegate_layer_stats(TfLiteDelegate*,int ordinal,int* node,uint64_t out[8]);
#endif
