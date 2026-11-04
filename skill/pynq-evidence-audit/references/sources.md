# 技术来源与提炼依据

## 规范依据

AMD自主选题指南的3.3.2、3.3.5.2、3.3.5.3和3.3.5.4分别对应通用PYNQ、技能包、提炼与协作记录、目录规范。指南与输入技能归档以SHA-256标识，见 [provenance.json](../evidence/provenance.json)，不作为安装依赖。

## 工程观察

- 音频输入兼容、后台资源占用、Overlay元数据与PS资源误判：形成F01-F09及只读采样工具。
- 算子一致与整链/语义分别核验、局部耗时远小于完整后端、BRAM接近上限：形成F10-F13及独立的质量、资源、速度检查。
- 文件完整但路径、解释器、设备ABI与恢复输入不匹配：形成F14及可安装、相对路径交付。
- 多板双区域处理、模型变体和预处理身份、关键点接时序分类的分布变化：形成F16-F18及多分支契约和视觉工作流。

原始证据使用内容指纹追溯。公开包只保存通用方法和脱敏测量摘要，不依赖原工程目录、模型、板卡口令或业务类别。

## 官方接口与公开项目

- [PYNQ缓冲](https://pynq.readthedocs.io/en/latest/pynq_libraries/allocate.html)：连续内存与缓存同步。
- [PYNQ DMA](https://pynq.readthedocs.io/en/latest/pynq_libraries/dma.html)：AXIS、TLAST与驱动调用示例，模式能力须按安装源码核对。
- [Linux proc](https://docs.kernel.org/filesystems/proc.html)：CPU/进程/内存采样口径。
- [NumPy load](https://numpy.org/doc/stable/reference/generated/numpy.load.html)、[isclose](https://numpy.org/doc/stable/reference/generated/numpy.isclose.html)：数组加载和误差准则。
- [Agent Skills与安装](https://learn.chatgpt.com/docs/build-skills)：SKILL.md及工程级技能目录。

GitHub固定提交、许可证及采用范围见 [upstream_review.md](upstream_review.md)。公开方法与工程经验分别注明；任何外部项目成绩均不计为本技能的计时结果。

本版Skill审查的真实需求、答复节选和反例修正过程见 [development_record.md](development_record.md)。混合类型比较和安装失败回收的回归见evidence/revision_validation.json；该记录不冒充另一板卡或陌生团队的计时。
