// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef XKEYPOINT_CONV_F32_H
#define XKEYPOINT_CONV_F32_H

#ifdef __cplusplus
extern "C" {
#endif

/***************************** Include Files *********************************/
#ifndef __linux__
#include "xil_types.h"
#include "xil_assert.h"
#include "xstatus.h"
#include "xil_io.h"
#else
#include <stdint.h>
#include <assert.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <stddef.h>
#endif
#include "xkeypoint_conv_f32_hw.h"

/**************************** Type Definitions ******************************/
#ifdef __linux__
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
#else
typedef struct {
#ifdef SDT
    char *Name;
#else
    u16 DeviceId;
#endif
    u64 Control_BaseAddress;
} XKeypoint_conv_f32_Config;
#endif

typedef struct {
    u64 Control_BaseAddress;
    u32 IsReady;
} XKeypoint_conv_f32;

typedef u32 word_type;

/***************** Macros (Inline Functions) Definitions *********************/
#ifndef __linux__
#define XKeypoint_conv_f32_WriteReg(BaseAddress, RegOffset, Data) \
    Xil_Out32((BaseAddress) + (RegOffset), (u32)(Data))
#define XKeypoint_conv_f32_ReadReg(BaseAddress, RegOffset) \
    Xil_In32((BaseAddress) + (RegOffset))
#else
#define XKeypoint_conv_f32_WriteReg(BaseAddress, RegOffset, Data) \
    *(volatile u32*)((BaseAddress) + (RegOffset)) = (u32)(Data)
#define XKeypoint_conv_f32_ReadReg(BaseAddress, RegOffset) \
    *(volatile u32*)((BaseAddress) + (RegOffset))

#define Xil_AssertVoid(expr)    assert(expr)
#define Xil_AssertNonvoid(expr) assert(expr)

#define XST_SUCCESS             0
#define XST_DEVICE_NOT_FOUND    2
#define XST_OPEN_DEVICE_FAILED  3
#define XIL_COMPONENT_IS_READY  1
#endif

/************************** Function Prototypes *****************************/
#ifndef __linux__
#ifdef SDT
int XKeypoint_conv_f32_Initialize(XKeypoint_conv_f32 *InstancePtr, UINTPTR BaseAddress);
XKeypoint_conv_f32_Config* XKeypoint_conv_f32_LookupConfig(UINTPTR BaseAddress);
#else
int XKeypoint_conv_f32_Initialize(XKeypoint_conv_f32 *InstancePtr, u16 DeviceId);
XKeypoint_conv_f32_Config* XKeypoint_conv_f32_LookupConfig(u16 DeviceId);
#endif
int XKeypoint_conv_f32_CfgInitialize(XKeypoint_conv_f32 *InstancePtr, XKeypoint_conv_f32_Config *ConfigPtr);
#else
int XKeypoint_conv_f32_Initialize(XKeypoint_conv_f32 *InstancePtr, const char* InstanceName);
int XKeypoint_conv_f32_Release(XKeypoint_conv_f32 *InstancePtr);
#endif

void XKeypoint_conv_f32_Start(XKeypoint_conv_f32 *InstancePtr);
u32 XKeypoint_conv_f32_IsDone(XKeypoint_conv_f32 *InstancePtr);
u32 XKeypoint_conv_f32_IsIdle(XKeypoint_conv_f32 *InstancePtr);
u32 XKeypoint_conv_f32_IsReady(XKeypoint_conv_f32 *InstancePtr);
void XKeypoint_conv_f32_EnableAutoRestart(XKeypoint_conv_f32 *InstancePtr);
void XKeypoint_conv_f32_DisableAutoRestart(XKeypoint_conv_f32 *InstancePtr);
u32 XKeypoint_conv_f32_Get_return(XKeypoint_conv_f32 *InstancePtr);

void XKeypoint_conv_f32_Set_input_r(XKeypoint_conv_f32 *InstancePtr, u64 Data);
u64 XKeypoint_conv_f32_Get_input_r(XKeypoint_conv_f32 *InstancePtr);
void XKeypoint_conv_f32_Set_weights(XKeypoint_conv_f32 *InstancePtr, u64 Data);
u64 XKeypoint_conv_f32_Get_weights(XKeypoint_conv_f32 *InstancePtr);
void XKeypoint_conv_f32_Set_bias(XKeypoint_conv_f32 *InstancePtr, u64 Data);
u64 XKeypoint_conv_f32_Get_bias(XKeypoint_conv_f32 *InstancePtr);
void XKeypoint_conv_f32_Set_output_r(XKeypoint_conv_f32 *InstancePtr, u64 Data);
u64 XKeypoint_conv_f32_Get_output_r(XKeypoint_conv_f32 *InstancePtr);
void XKeypoint_conv_f32_Set_config_r(XKeypoint_conv_f32 *InstancePtr, u64 Data);
u64 XKeypoint_conv_f32_Get_config_r(XKeypoint_conv_f32 *InstancePtr);

void XKeypoint_conv_f32_InterruptGlobalEnable(XKeypoint_conv_f32 *InstancePtr);
void XKeypoint_conv_f32_InterruptGlobalDisable(XKeypoint_conv_f32 *InstancePtr);
void XKeypoint_conv_f32_InterruptEnable(XKeypoint_conv_f32 *InstancePtr, u32 Mask);
void XKeypoint_conv_f32_InterruptDisable(XKeypoint_conv_f32 *InstancePtr, u32 Mask);
void XKeypoint_conv_f32_InterruptClear(XKeypoint_conv_f32 *InstancePtr, u32 Mask);
u32 XKeypoint_conv_f32_InterruptGetEnabled(XKeypoint_conv_f32 *InstancePtr);
u32 XKeypoint_conv_f32_InterruptGetStatus(XKeypoint_conv_f32 *InstancePtr);

#ifdef __cplusplus
}
#endif

#endif
