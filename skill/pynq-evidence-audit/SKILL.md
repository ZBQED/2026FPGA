---
name: pynq-evidence-audit
description: Verify PYNQ Overlay identity, PS resources, golden outputs, Vivado reports, complete-frame latency, multi-board branch fusion and handoff integrity. Use for PYNQ bring-up, audio, vision or sensor pipelines, performance diagnosis and reproducible handoff. Does not load bitstreams or certify task accuracy.
metadata:
  version: "0.5.0"
---

# PYNQ Evidence Audit

将接手、调试和优化结论转为可复查证据。PYNQ-Z2为已记录的实板对象，不是默认目标；题目、板卡、模型、地址与授权以目标工程为准。

## 安装与入口

发布包通过`python skill/install.py --project <工程目录>`安装。优先使用`python scripts/run.py <工具> ...`，统一入口自动选择安装依赖环境。无安装环境时可使用满足requirements的Python独立调用脚本。报告使用相对计数、版本和内容指纹，不添加日历字段。

## 选择相关工具

先读 [workflow.md](references/workflow.md) 对应小节，不必执行全部工具：

- Overlay版本/IP或PS CPU/RSS：`scripts/collect_evidence.py`，只读，显式PID/服务和窗口。
- 黄金输出：`scripts/compare_arrays.py`；先确认同输入、布局、单位、量化与容限。
- Vivado资源/时序：`scripts/check_reports.py`，英文全设计报告，保留未约束/脉宽问题。
- 同帧完整延迟：`scripts/check_latency.py`；确认采集点、显示完成点、单一时钟域。
- 多板/多区域汇合：`scripts/check_pipeline.py`；检查帧、ROI、分支、模型、预处理与输出约定。
- 交付文件身份：`scripts/check_manifest.py`；文件校验不替代构建复现。
- 初次使用：`scripts/run_demo.py`，纯离线合成数据，正反例预期不同退出码。

音频输入、特征一致性、扩类与触发验收用 [audio_pipeline.md](references/audio_pipeline.md)；软硬件划分/优化用 [prompts.md](references/prompts.md)；视觉、量化、双区域和时序分类接入用 [vision_pipeline.md](references/vision_pipeline.md)；故障触发查 [failure_patterns.md](references/failure_patterns.md)。模板在 `templates/`，按任务选用。

源码绑定与替代实现判断读[source_provenance.md](references/source_provenance.md)；陌生工程复现和耗时记录选择读[experiment_reproduction.md](references/experiment_reproduction.md)。

## 执行与判断

1. 明确通过条件及文件/数据/计时边界。已有授权和证据足够时直接推进，不反复提问。
2. 绑定输入、原始记录和预期值。无可信哈希仅能建立身份；loaded-state是软件记录，不是硬件回读。
3. 使用相关工具，保留JSON与退出码。针对具体失败修正，不放宽阈值或丢弃失败样本制造通过。
4. 分清仿真、数值一致、功能、资源时序、完整速度和恢复结果，不能相互替代。
5. 历史实板、本机合成、新模板分别标注；见 [validation.md](references/validation.md)。

脚本只读取目标文件/系统状态并写新报告。主动硬件实验须识别资源拥有者、字节契约、有限运行时间和恢复方法；本技能不隐含停服务、换位流或打开摄像头/音频的授权。

LUT/FF/BRAM/DSP取对应报告，CPU/DDR/HWH模块数不是PL利用率。跨板不能复用位流；跨主机单调时钟不能直接相减；显示API返回不等于显示完成。

## 输出

给出工具、输入来源、结果路径、通过/失败原因、效果和适用边界。按需填 [experiment_report.md](templates/experiment_report.md)。不虚构对话、准确率、收益、兼容性或评分。官方与GitHub来源见 [sources.md](references/sources.md)。
