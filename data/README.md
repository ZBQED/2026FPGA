# 测试数据与参考结果

`models`是当前源码需要的部署参数和模型。`test_inputs/fixed_frame.bin`是最快固定帧运行使用的800×480 BGR888原始字节，长度1,152,000；SHA256为`ee74c843cc3574d9875dfe3c320dd830686dfe9ff5f0eeef5c73176396a52caa`。图像由既有640像素宽输入两侧各补80黑像素组成，不缩放。

`test_inputs/nav_heads/*.npz`保存Palm/Body输出头的输入、权重、偏置、配置与期望输出；部署用NPZ位于`models/nav_heads`，二者用途不同。

`test_inputs/core/case*_mem.hex`是AXI内存初始内容；`reference/core/case*_expected.hex`是独立计算的期望输出；`reference/core/cases.json`记录形状、输出长度和SHA。三组PW/DW/TCN用例均与独立整数参考一致。内存按64bit小端字记录。

```powershell
python -B sim/make_core_vectors.py E:/fpga_verify/core_vectors
```

脚本可独立重算冻结向量，不需要原训练工程或板卡。

| 文件 | 输入与参考 |
|---|---|
| reference/hand_fixture.npz | 3×224×224×3 INT8输入与3×44 FP32原始输出头 |
| reference/body_fixture.npz | 3×256×192×3 INT8输入与3×52224 FP32输出头 |
| reference/tcn_seven_words.npz | 7条冻结输入、主模型/专家输出、标签与固定组摘要 |
| reference/tcn_torch_golden.npz | 7×192×32输入与7×27 PyTorch参考logits |
| reference/tcn_primary_input.npz | 32×96有效值和掩码 |
| reference/tcn_primary_golden.json | 固定主模型参考结果 |

数值验证应匹配模型版本、量化配置和输出维度；原始手部44维输出是模型输出头，21点的业务解码与有效性规则由运行源码执行。
