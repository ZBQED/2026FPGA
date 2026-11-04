# 通用 PYNQ 开发核验技能包

## 用途

面向PYNQ图像、音频、传感器、控制和自定义加速器工程，提供可安装的AI技能、校验脚本、案例模板与故障排查方法。模型、类别、阈值、板卡地址和板卡专属位流均不作为安装依赖。

## 安装与调用

环境要求：Python 3.9或更新版本、可写的工程目录，以及可访问Python包源的网络。安装器自动创建隔离环境并安装兼容的NumPy二进制包。Linux可能需要系统提供的venv组件；没有兼容二进制包的平台会明确报错。PYNQ框架和Vivado仅在对应板端/硬件任务中需要，离线工具不依赖它们。

在包含`skill/`的工程根目录执行：

```text
python skill/install.py
```

安装到其他工程：

```text
python skill/install.py --project <目标工程目录>
```

安装器完成发布文件核验、技能复制、依赖环境准备和自动测试。默认位置为目标工程的`.agents/skills/pynq-evidence-audit/`，临时下载位于目标目录附近，不改全局Python环境。目标已存在时返回明确错误，不覆盖已有修改。安装中途出现可捕获的异常或键盘中断时，只回收本次创建的目标目录，之后可重试；系统断电或强制杀进程无法运行回收代码，须核对残留目录来源后由使用者处理。其他支持SKILL.md的客户端可通过`--skills-dir <技能父目录>`指定位置；识别方式以对应客户端为准。

Codex在该工程中可调用`$pynq-evidence-audit`。若未显示，重新打开客户端。安装方式依据 [官方技能说明](https://learn.chatgpt.com/docs/build-skills)。

无需AI客户端也可调用工具。进入已安装的`pynq-evidence-audit/`后运行：

```text
python scripts/run.py demo --output-dir <尚不存在的输出目录>
python scripts/run.py test
python scripts/run.py compare reference.npy actual.npy --atol 0 --rtol 0
```

统一入口自动使用安装器准备的Python环境，无需手动激活。`demo`包含11步合成示例，其中4步预期失败，用于检查工具能否拒绝错误输入。工程的输入、参数与退出码见 [工作流](pynq-evidence-audit/references/workflow.md)。

## 技能项目

验证类别：H为PYNQ-Z2只读实板记录；L为Windows离线测试；R为真实工程报告离线解析；T为模板或方法。详见 [验证范围](pynq-evidence-audit/references/validation.md)。

| 项目 | 适用范围与用法 | 已验证效果 | 失效条件 | 经验来源 |
|---|---|---|---|---|
| M01 Overlay身份 | 接手/升级；`run.py collect --bit ... --hwh ... --samples 0` | H检查完成；L检出错哈希、缺IP、损坏XML | 没有可信预期值只能记录身份；元数据不能证明当前硬件功能 | F03/F04/F06：资源占用冲突、文件名误导、资源口径混淆 |
| M02 PS资源 | 运行中的Linux应用；collect显式传`--pid`或`--service` | H保留CPU/RSS与服务前后状态；L核验PID复用和CPU口径 | 非Linux、权限不足、进程变化失败；待机采样不代表推理峰值 | F07/F09：并发负载混算、采样窗口混用 |
| M03 黄金参考 | 相同输入的PL/PS输出；`run.py compare` | L检出整数及混合整数/浮点差1、形状/非有限值异常，给出首个错误坐标 | 单位/布局/量化语义须先约定；数值一致不等于识别准确率 | F08/F10：重复样本和分阶段证据混用 |
| M04 资源时序 | 英文Vivado全设计报告；`run.py reports` | L覆盖资源超限、hold/pulse、缺约束；R保留真实I/O约束问题 | 未知表格式失败；需另审DRC/CDC、完整约束及位流来源 | F06/F12/F13：资源估错、BRAM紧张、综合通过但实现失败 |
| M05 完整延迟 | 同帧采集至显示的相对计数；`run.py latency` | L检出漏/重复/失败帧、跨时钟域、只有显示提交、严格上限失败 | 显示完成需外部证据；不能把核耗时当整链 | F11：局部计时掩盖调度、传输和显示开销 |
| M06 多板结果汇合 | 双区域、关键点与上下文分支；`run.py pipeline` | L检出错帧、旧ROI、缺分支、不同输入、模型/预处理/输出约定不符 | 记录必须由运行器产生；不验证业务语义或板上执行真实性 | F16/F17：双区域串用、模型和预处理版本漂移 |
| M07 工程交接 | 冻结/复制交付树；`run.py manifest create/verify` | L检出同大小改动、缺件、多件、路径越界 | 文件一致不等于构建成功；不提供作者身份认证 | F14：包内文件完整但环境/路径/恢复输入缺失 |

## 音频与模型扩展

音频项目按需阅读 [音频工作流](pynq-evidence-audit/references/audio_pipeline.md)，填写通用音频契约。它将输入选择、PCM解释、特征一致性、旧新类别回归、拒识集合、自动触发和业务通信分开核验。接口、采样率、窗口、词表、类别数、阈值和服务名均由目标工程提供，不默认某一耳麦、某块板或某套模型。

## 项目经验的通用化

[视觉与多板工作流](pynq-evidence-audit/references/vision_pipeline.md)强化以下可迁移部分：

- 同一原始帧派生多个ROI，多板结果按帧和分支汇合，拒绝旧结果及缺失分支。
- 模型、预处理、量化参数和输出约定分别绑定，防止不同精度或模型变体混用。
- ROI裁剪、缩放、填充、镜像与关键点坐标逆变换形成明确接口。
- 逐层数值、关键点质量、时序分类语义、完整显示延迟分别验收。
- 按真实资源余量、通信量和调用次数选择并行、复用与常驻调度。

这些规则同样适用于双路图像、多个传感器或音频分支，不包含医疗词表、专属权重、固定地址或固定板卡分工。

## 迁移边界

更换板卡时重新提供目标器件、镜像/PYNQ版本、BIT/HWH、IP名称、接口契约和实现报告。位流必须为目标板构建；资源容量从报告读取。已留存实板证据仅覆盖PYNQ-Z2，其他板卡按目标器件和接口重新配置。安装成功只说明技能和依赖可用，不代表硬件工程已经部署。

## 目录

```text
skill/
  README.md
  install.py
  files_sha256.json
  pynq-evidence-audit/
    SKILL.md
    scripts/
    examples/
    templates/
    references/
    tests/
    evidence/
```

脚本、模板、案例与说明均使用相对路径。性能核验使用相对计数和耗时；软件验证记录绑定代码哈希与环境。

## 参赛要求与来源

[要求对照](pynq-evidence-audit/references/submission_requirements.md)逐项列出技能包条款、对应文件和证据范围。工程的源码、重建、板测、设计报告与完整协作记录属于作品提交物，需要与技能包一并提供。

技术来源及第三方采用范围见 [sources.md](pynq-evidence-audit/references/sources.md) 和 [upstream_review.md](pynq-evidence-audit/references/upstream_review.md)。历史测量仅以脱敏摘录保存，原文件指纹用于追溯；不将摘要标成未经改动的原始日志。

## 发布文件校验

在`skill/`目录执行：

```text
python pynq-evidence-audit/scripts/check_manifest.py verify . files_sha256.json --strict
```

新报告保存到发布目录之外。校验清单保证文件完整性，不提供第三方签名认证。

## 源码溯源与实验复现

| 项目 | 适用与使用 | 已验证效果 | 失效条件与提炼观察 |
|---|---|---|---|
| M09 源码溯源 | 对照source_provenance.md，填写source_provenance.json；用manifest冻结源码与输出身份 | 现有清单回归可检出改动、缺件、多件和越界 | 仅凭同名文件或内核版本不能绑定源码；原实现与替代实现须分清 |
| M10 复现指南与模板 | 按experiment_reproduction.md填写reproduction_plan.json与reproduction_result.md | 沿用63项工具回归及11步离线示例 | 输入、模型、计时终点、共享资源与恢复身份不一致时重新固定契约 |

版本0.5.0补充上述两项，校验工具接口保持兼容。方法、模板和运行结果分开说明。

## 提示词与工程模板

M08提供软硬件划分、接口固定、量化比较、回归与恢复模板。按references/prompts.md选择流程；配套工具的离线示例已通过。输入、单位、目标接口与评价条件须先定义，数值比较再按对应契约执行。
