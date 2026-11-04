# GitHub综合与取舍

参考项目按固定提交标识，文件指纹见 [upstream_sources.json](../evidence/upstream_sources.json)。以下记录方法来源、采用范围和验证边界。

| 来源 | 读取与吸收 | 本包落实 | 未照搬的边界 |
|---|---|---|---|
| [Xilinx/ross-ai-assistant](https://github.com/Xilinx/ross-ai-assistant/tree/dce0fb90611b144dd529490359b51cea5d0d5596)，MIT | vivado-revision-control的工程来源/重建意识；timing-methodology的约束问题定位；hls-run-flow区分csim/csynth/cosim/impl | M04报告检查、P4/P6提示词、实验模板、分阶段验收 | 不搬其完整技能/子代理/MCP依赖，不按“目录存在”判阶段通过，不默认选第一个工程配置 |
| [Xilinx/PYNQ](https://github.com/Xilinx/PYNQ/tree/d90670c69f7b71ea1a5d23aaa3e0ec713ff5fa9f)，BSD-3-Clause | 实读pynq/lib/dma.py、pynq/buffer.py：缓冲地址、同步、完成和模式选择 | 接口契约、F15及DMA诊断步骤 | 不装/升级生产PYNQ，不复制位流，不把上游版本功能推定为用户安装版 |
| [cathalmccabe/PYNQ_tutorials](https://github.com/cathalmccabe/PYNQ_tutorials/tree/f4a11dc92ef855dab0bf98af9de9c8af4fb70a18)，BSD-3-Clause | 实读README/许可，作为DMA、HLS AXIS、m_axi与新Overlay学习入口 | 把接口类型区分和换板替换项写进工作流 | 采用README、许可及接口类型说明作为学习入口 |

## 文档与实现差异

[PYNQ DMA文档](https://pynq.readthedocs.io/en/latest/pynq_libraries/dma.html) 的说明仍写simple模式；固定提交的 [dma.py](https://github.com/Xilinx/PYNQ/blob/d90670c69f7b71ea1a5d23aaa3e0ec713ff5fa9f/pynq/lib/dma.py) 含 `_SDMAChannel`、`_SGDMAChannel`，按`c_include_sg`选择，且有cyclic限制。因此本包没有把“仅支持simple”作为所有PYNQ版本的规则，而要求核对安装版本、HWH参数、IP和驱动。

该源码的简单传输路径已有发送flush、完成后接收invalidate；自写驱动仍需承担相应同步。`wait()`不是通用的带超时API，不能凭等待函数名假设有超时保护。缓冲释放与硬件空闲分别确认。本条验证方式为固定提交源码核对。

## 归属与验证

工程观察、外部方法和验证结果分别标注。外部项目的功能、性能与测试记录不作为本技能包的计时成果。

未将第三方源码整段纳入交付，所以本包不直接继承/改写上述仓库的许可证。团队正式公开时应确定自身材料许可；如果后续复制上游代码，则保留对应MIT/BSD版权与许可文本。原始指纹便于复核，不代表本包验证了整个上游仓库。
