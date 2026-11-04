// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
#ifndef __linux__

#include "xstatus.h"
#ifdef SDT
#include "xparameters.h"
#endif
#include "xkeypoint_conv_f32.h"

extern XKeypoint_conv_f32_Config XKeypoint_conv_f32_ConfigTable[];

#ifdef SDT
XKeypoint_conv_f32_Config *XKeypoint_conv_f32_LookupConfig(UINTPTR BaseAddress) {
	XKeypoint_conv_f32_Config *ConfigPtr = NULL;

	int Index;

	for (Index = (u32)0x0; XKeypoint_conv_f32_ConfigTable[Index].Name != NULL; Index++) {
		if (!BaseAddress || XKeypoint_conv_f32_ConfigTable[Index].Control_BaseAddress == BaseAddress) {
			ConfigPtr = &XKeypoint_conv_f32_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XKeypoint_conv_f32_Initialize(XKeypoint_conv_f32 *InstancePtr, UINTPTR BaseAddress) {
	XKeypoint_conv_f32_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XKeypoint_conv_f32_LookupConfig(BaseAddress);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XKeypoint_conv_f32_CfgInitialize(InstancePtr, ConfigPtr);
}
#else
XKeypoint_conv_f32_Config *XKeypoint_conv_f32_LookupConfig(u16 DeviceId) {
	XKeypoint_conv_f32_Config *ConfigPtr = NULL;

	int Index;

	for (Index = 0; Index < XPAR_XKEYPOINT_CONV_F32_NUM_INSTANCES; Index++) {
		if (XKeypoint_conv_f32_ConfigTable[Index].DeviceId == DeviceId) {
			ConfigPtr = &XKeypoint_conv_f32_ConfigTable[Index];
			break;
		}
	}

	return ConfigPtr;
}

int XKeypoint_conv_f32_Initialize(XKeypoint_conv_f32 *InstancePtr, u16 DeviceId) {
	XKeypoint_conv_f32_Config *ConfigPtr;

	Xil_AssertNonvoid(InstancePtr != NULL);

	ConfigPtr = XKeypoint_conv_f32_LookupConfig(DeviceId);
	if (ConfigPtr == NULL) {
		InstancePtr->IsReady = 0;
		return (XST_DEVICE_NOT_FOUND);
	}

	return XKeypoint_conv_f32_CfgInitialize(InstancePtr, ConfigPtr);
}
#endif

#endif

