// ==============================================================
// Vitis HLS - High-Level Synthesis from C, C++ and OpenCL v2024.2 (64-bit)
// Tool Version Limit: 2024.11
// Copyright 1986-2022 Xilinx, Inc. All Rights Reserved.
// Copyright 2022-2024 Advanced Micro Devices, Inc. All Rights Reserved.
// 
// ==============================================================
/***************************** Include Files *********************************/
#include "xkeypoint_conv_f32.h"

/************************** Function Implementation *************************/
#ifndef __linux__
int XKeypoint_conv_f32_CfgInitialize(XKeypoint_conv_f32 *InstancePtr, XKeypoint_conv_f32_Config *ConfigPtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(ConfigPtr != NULL);

    InstancePtr->Control_BaseAddress = ConfigPtr->Control_BaseAddress;
    InstancePtr->IsReady = XIL_COMPONENT_IS_READY;

    return XST_SUCCESS;
}
#endif

void XKeypoint_conv_f32_Start(XKeypoint_conv_f32 *InstancePtr) {
    u32 Data;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_AP_CTRL) & 0x80;
    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_AP_CTRL, Data | 0x01);
}

u32 XKeypoint_conv_f32_IsDone(XKeypoint_conv_f32 *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_AP_CTRL);
    return (Data >> 1) & 0x1;
}

u32 XKeypoint_conv_f32_IsIdle(XKeypoint_conv_f32 *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_AP_CTRL);
    return (Data >> 2) & 0x1;
}

u32 XKeypoint_conv_f32_IsReady(XKeypoint_conv_f32 *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_AP_CTRL);
    // check ap_start to see if the pcore is ready for next input
    return !(Data & 0x1);
}

void XKeypoint_conv_f32_EnableAutoRestart(XKeypoint_conv_f32 *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_AP_CTRL, 0x80);
}

void XKeypoint_conv_f32_DisableAutoRestart(XKeypoint_conv_f32 *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_AP_CTRL, 0);
}

u32 XKeypoint_conv_f32_Get_return(XKeypoint_conv_f32 *InstancePtr) {
    u32 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_AP_RETURN);
    return Data;
}
void XKeypoint_conv_f32_Set_input_r(XKeypoint_conv_f32 *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_INPUT_R_DATA, (u32)(Data));
    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_INPUT_R_DATA + 4, (u32)(Data >> 32));
}

u64 XKeypoint_conv_f32_Get_input_r(XKeypoint_conv_f32 *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_INPUT_R_DATA);
    Data += (u64)XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_INPUT_R_DATA + 4) << 32;
    return Data;
}

void XKeypoint_conv_f32_Set_weights(XKeypoint_conv_f32 *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_WEIGHTS_DATA, (u32)(Data));
    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_WEIGHTS_DATA + 4, (u32)(Data >> 32));
}

u64 XKeypoint_conv_f32_Get_weights(XKeypoint_conv_f32 *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_WEIGHTS_DATA);
    Data += (u64)XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_WEIGHTS_DATA + 4) << 32;
    return Data;
}

void XKeypoint_conv_f32_Set_bias(XKeypoint_conv_f32 *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_BIAS_DATA, (u32)(Data));
    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_BIAS_DATA + 4, (u32)(Data >> 32));
}

u64 XKeypoint_conv_f32_Get_bias(XKeypoint_conv_f32 *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_BIAS_DATA);
    Data += (u64)XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_BIAS_DATA + 4) << 32;
    return Data;
}

void XKeypoint_conv_f32_Set_output_r(XKeypoint_conv_f32 *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_OUTPUT_R_DATA, (u32)(Data));
    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_OUTPUT_R_DATA + 4, (u32)(Data >> 32));
}

u64 XKeypoint_conv_f32_Get_output_r(XKeypoint_conv_f32 *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_OUTPUT_R_DATA);
    Data += (u64)XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_OUTPUT_R_DATA + 4) << 32;
    return Data;
}

void XKeypoint_conv_f32_Set_config_r(XKeypoint_conv_f32 *InstancePtr, u64 Data) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_CONFIG_R_DATA, (u32)(Data));
    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_CONFIG_R_DATA + 4, (u32)(Data >> 32));
}

u64 XKeypoint_conv_f32_Get_config_r(XKeypoint_conv_f32 *InstancePtr) {
    u64 Data;

    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Data = XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_CONFIG_R_DATA);
    Data += (u64)XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_CONFIG_R_DATA + 4) << 32;
    return Data;
}

void XKeypoint_conv_f32_InterruptGlobalEnable(XKeypoint_conv_f32 *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_GIE, 1);
}

void XKeypoint_conv_f32_InterruptGlobalDisable(XKeypoint_conv_f32 *InstancePtr) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_GIE, 0);
}

void XKeypoint_conv_f32_InterruptEnable(XKeypoint_conv_f32 *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_IER);
    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_IER, Register | Mask);
}

void XKeypoint_conv_f32_InterruptDisable(XKeypoint_conv_f32 *InstancePtr, u32 Mask) {
    u32 Register;

    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    Register =  XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_IER);
    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_IER, Register & (~Mask));
}

void XKeypoint_conv_f32_InterruptClear(XKeypoint_conv_f32 *InstancePtr, u32 Mask) {
    Xil_AssertVoid(InstancePtr != NULL);
    Xil_AssertVoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    XKeypoint_conv_f32_WriteReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_ISR, Mask);
}

u32 XKeypoint_conv_f32_InterruptGetEnabled(XKeypoint_conv_f32 *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_IER);
}

u32 XKeypoint_conv_f32_InterruptGetStatus(XKeypoint_conv_f32 *InstancePtr) {
    Xil_AssertNonvoid(InstancePtr != NULL);
    Xil_AssertNonvoid(InstancePtr->IsReady == XIL_COMPONENT_IS_READY);

    return XKeypoint_conv_f32_ReadReg(InstancePtr->Control_BaseAddress, XKEYPOINT_CONV_F32_CONTROL_ADDR_ISR);
}

