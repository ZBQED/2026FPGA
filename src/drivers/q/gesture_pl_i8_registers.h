#ifndef GESTURE_PL_I8_REGISTERS_H
#define GESTURE_PL_I8_REGISTERS_H
/* Exact xkeypoint_conv_i8_hw.h from gesture.local:hls:keypoint_conv_i8:2.0.
 * Same offsets as ABI1 do not imply compatibility: config and tensors differ. */
#define GPI8_REG_CONTROL 0x00
#define GPI8_REG_GIE     0x04
#define GPI8_REG_IER     0x08
#define GPI8_REG_ISR     0x0c
#define GPI8_REG_RESULT  0x10
#define GPI8_REG_INPUT   0x18
#define GPI8_REG_WEIGHTS 0x24
#define GPI8_REG_PARAMS  0x30
#define GPI8_REG_OUTPUT  0x3c
#define GPI8_REG_CONFIG  0x48
#define GPI8_REG_SPAN    0x50
#endif
