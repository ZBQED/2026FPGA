# PYNQ Evidence Audit

- 用途：Overlay、PS资源、黄金输出、资源时序、完整延迟、多分支汇合、交付核验。
- 安装：在含skill/的工程根执行`python skill/install.py`，自动准备依赖并自检。
- 输入：目标文件、进程/服务、参考数组、报告、分支契约或相对计数CSV。
- 输出：JSON、SHA-256、失败原因和验证边界，不生成日历标记。
- 验证：PYNQ-Z2只读证据摘录、Windows软件自检、合成正反例与真实报告解析。
- 边界：不加载位流或采集硬件数据；其他板卡、其他系统运行与完整应用效果需独立验证。
- 音频：输入、特征、扩类与触发核验见 [音频工作流](references/audio_pipeline.md)。
- 入口：[SKILL.md](SKILL.md)、[工作流](references/workflow.md)、[验证](references/validation.md)。
