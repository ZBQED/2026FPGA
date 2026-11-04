# 使用、边界与失效条件

## 环境

- 本包统一使用 Python 3.9+。collect_evidence.py 和新增报告/延迟/清单工具只用标准库；文件分析不要求安装 PYNQ、NumPy 或 Vivado。
- Linux 资源采样：需要可读 /proc；--service 还需要 systemctl 和查看服务的权限。脚本不会自行 sudo。
- compare_arrays.py：Python 3.9+、NumPy。加载 NPY/NPZ 时固定 allow_pickle=False。
- 远程传输和认证由使用者管理；技能脚本不带 SSH 凭据、不自动扫描网段、不使用固定地址。

所有文件、服务名、进程和阈值均为显式输入，示例参数应替换为目标工程配置。安装后的统一入口为`python scripts/run.py`，可使用collect、compare、reports、latency、pipeline、manifest、demo和test子命令。

## 文件与 Overlay 核验

仅文件分析，适合电脑和离线副本：

    python scripts/collect_evidence.py --bit /path/design.bit --hwh /path/design.hwh --require-ip axi_dma --samples 0 --output identity.json

--require-ip 接受完整 MODTYPE 或 VLNV 的精确字符串，可多次传入。它验证 HWH 声明里出现该类型，不验证驱动调用成功、DMA 连线或设备真正工作。

如有可信校验清单，额外传入 --expected-bit-sha256 与 --expected-hwh-sha256。两参数分别要求 64 位十六进制 SHA-256；不能把 PYNQ 状态里的另一种哈希算法标识直接拿来比较。

--state 只在使用者提供明确 loaded-state JSON 路径时读取，验证 bitfile_name 路径是否与当前目标一致。不改状态文件，不把状态记录当作硬件配置帧回读。

## 资源与现有服务

在板端 Linux 执行：

    python3 scripts/collect_evidence.py --service my-app.service --bit /path/design.bit --hwh /path/design.hwh --samples 12 --interval 1 --output runtime.json

不使用 systemd 时可传 --pid 代替 --service。若两者同时给出，PID 必须一致。脚本只查询 systemctl show；不使用 start/stop/restart/disable。

--samples 是采样间隔数，因此 N 个间隔通常有 N+1 个原始快照。默认 6 个间隔、每间隔请求 0.25 秒；计算使用经过的单调时间。区间内摘要均保留原始计数，不虚构精度。

CPU 字段：system_cpu_percent 按所有逻辑 CPU 合计 100%；process_cpu_percent_one_core 按单逻辑 CPU 100%，可以超过 100%；process_cpu_percent_machine 再除逻辑 CPU 数。瞬时采样不保证捕获短时尖峰。

VmRSS 包含共享驻留页；VmHWM 为进程生命周期高水位，不能称为这次推理独有峰值；VmSize 是虚拟地址空间。整机压力应结合 MemAvailable，不把 CMA 再叠加一次。

当应用没有真正进入推理时，工具采到的是采集/待机状态，不会因为“调用采样工具”就自动变成推理资源测试。测试两进程并行时必须分别标明。

## 黄金参考比较

确认参考与数组来自相同输入、预处理、形状、布局、单位及阶段。容限由算法决定，示例值不是通用及格线：

    python scripts/compare_arrays.py reference.npy actual.npy --atol 0.000001 --rtol 0.00001 --output comparison.json

NPZ 输入需双方都是 NPZ，并用 --key 明确选择一个同名数组。两个脚本只写用户指定的新输出文件；已存在输出不会覆盖。返回码 0 代表当前请求的检查通过，2 代表不匹配、检查问题或参数错误。

新增 `first_mismatch_index` 输出首个不匹配的数组坐标。脚本不自动重排、反量化或修正单位。参考应覆盖零/最大值、饱和边界、随机样本和连续不同输入，避免仅重复同一缓存。

比较准则：abs(actual-reference) <= atol + rtol*abs(reference)，所有元素同时满足才通过。浮点比较允许 dtype 不同，但须由使用者确认类型转换本身符合契约。精确整数比较可设两个容限均为 0。整数与浮点混合时使用精确有理数计算差值与容限，避免平台 longdouble 精度不足造成误通过；该路径逐元素执行，超大数组建议由使用者先明确统一 dtype/量化契约，再分块核验，不得为通过而丢弃有效位。

## 失效或不能下结论的情况

| 条件 | 处理 |
|---|---|
| 文件缺失、权限不足或 XML 损坏 | issues_found，保留已完成部分；修复输入后重试，不补零 |
| HWH IP 缺失、哈希不符 | 不通过；先查版本与来源，不自动更换 bitstream |
| BIT/HWH 同名也无可信来源 | 只记录身份；同名不证明同一次构建 |
| 非 Linux 请求 /proc 采样 | 明确报问题；--samples 0 仅文件模式仍可用 |
| 进程退出或 PID 复用、服务重启 | 当前窗口不作为同一进程稳定测量；不静默合并 |
| 没有 Vivado 对应实现报告 | PL 利用率 not_measured；不从 HWH/文件大小估算 |
| 数组形状不同、空、对象、复数、NaN/Inf | 比较失败；不广播、不忽略非有限值 |
| 输入超大且资源不足 | 缩小合理验证数据或单独设计分块测试；此版不是超大数组流式比较工具 |
| 输入文件或生产配置在外部变化 | 解释证据边界并重测；采集工具不主动回滚用户改动 |

## 如何向陌生队伍交付

交付整个技能目录、Python/NumPy 依赖、示例命令、原始 JSON 和失败说明。单独复制一段结论不构成可复用技能。输出路径和主机时钟应在报告中注明，公开前去除不必要的个人路径和业务数据。

## Vivado 资源与时序报告

在目标已布线设计中设置新输出目录，然后 `source templates/export_reports.tcl`。该Tcl仅是导出模板，当前未在Vivado执行。也可使用已留存、对应同一次构建的报告。

```text
python scripts/check_reports.py --utilization /data/run/utilization.rpt --timing /data/run/timing.rpt --max-percent 90 --output report_check.json
```

支持英文全设计 `report_utilization` 的 Slice/CLB LUTs、Slice/CLB Registers、Block RAM Tile、DSPs 行及 `report_timing_summary -delay_type min_max -report_unconstrained` 的12列总表、check_timing节。读取报告内容量，BRAM按Tile计数，半块可为0.5，不能将RAMB18和RAMB36直接相加。重复资源行只在数值一致时接受。

`--max-percent` 是使用者事先确定的统一资源预算，本例90不是通用标准。脚本验证 Routed 阶段、设计与基本器件名，检查setup/hold/pulse slack及失败端点、未约束/异常check_timing计数。无法识别、表缺失、没有有效端点均失败。带有需要豁免的异步/复位I/O也会标失败，交由具体约束审查；不自动豁免。

同名设计和近似器件名不是同一次构建的证明；速度等级、工具版本、XDC、DCP、bit与报告仍须由构建清单绑定。DRC、CDC、布线完成度、时钟例外正确性需另审。仅支持上述字段格式，不宣称支持所有Vivado版本/系列。

## 同帧采集到显示的延迟

```text
python scripts/check_latency.py /data/run/frames.csv --expected-frames 1000 --limit-ms 120 --output latency.json
```

参数1000和120都是示例。按本题目标填写，判定为**每个完整帧严格小于限值**，等于也失败；同时输出mean/p50/p95/p99/max。百分位用nearest-rank，小样本不等于稳定性能。

CSV表头固定为：

```csv
run_id,frame_id,clock_id,capture_ns,result_ns,display_ns,status,display_evidence
```

- 每行是采集窗口内的一帧，frame_id唯一。run_id、clock_id非空且全表一致；capture_ns/result_ns/display_ns均为相对窗口起点的整数纳秒计数，顺序为capture≤result≤display，不填写日历值。
- `capture_ns` 是本题约定的输入采集点，`result_ns` 是该帧完整计算结果，`display_ns` 是结果呈现事件或同一测量系统捕捉的显示事件；不能填写提交调用返回时间。
- `display_evidence` 可填 `presentation_feedback`（显示栈提供的呈现完成反馈）或 `external_probe`（外部测量）；必须另记具体机制和精度。两者仍不自动证明屏幕光学响应，光学目标须外部探头计时。
- `status=ok` 才是完整帧；失败/丢帧仍保留行，status写error/dropped，时间可空。存在失败或丢帧则严格验收失败。
- `--expected-frames` 来自采集器独立计数，不能为了通过改成成功帧数。预热在窗口外单独记录；完整窗口不静默跳帧。脚本能查行数，不能发现记录者同时篡改总数。
- 多板PS的perf_counter不能直接相减。可在一个协调端计同帧起终点，或用同一外部采集时基。若依赖跨机同步，先另证同步误差，本版不计算该误差。
- `display_throughput_fps` 用完成事件跨度计算，是观测吞吐，不能当成单帧延迟的倒数。

本脚本校验已采集记录，不生成显示事件，也不证明输入CSV真实。

## 可迁移交付清单

```text
python scripts/check_manifest.py create /data/project /data/project_manifest.json
python scripts/check_manifest.py verify /data/copied_project /data/project_manifest.json --strict
```

创建时遍历指定根目录，记录相对路径、大小、SHA-256；清单放根外最清楚，也允许放根内并排除清单本身。严格验证额外检查未列文件。不存在/改变/额外文件均失败，拒绝路径越界与符号链接。对会变化的日志/缓存不要建立冻结清单；仅冻结交付树，生成报告另存新目录。

这是完整性检查，不验证下载者身份、数据授权或重建确定性。完整复现还需源码、RTL/XDC/IP/BD导出、初始化数据、工具版本、明确命令和一次从零执行证据，见实验模板。

## 通用PYNQ接口与DMA注意点

填 `templates/interface_contract.json`，所有null按工程填写。里面的向量增益仅为与题目无关的示例，不是已实现的硬件IP。

先分清AXI-Lite寄存器、IP直接m_axi访问内存、AXI DMA流传输三种路径，不把任意DDR主口当成DMA。核对dtype/字节数、对齐、DRE、DMA长度字段、AXIS位宽、TLAST/TKEEP、复位/时钟与start/done协议。

使用PYNQ连续缓冲；明确谁负责PS→PL同步及PL→PS同步。核验的上游驱动在相应传输/等待路径执行flush/invalidate，自写MMIO/驱动则应独立实现正确顺序。不要笼统叠加同步动作，也不能省掉所需同步。超时后保留仍可能被硬件访问的缓冲，先按驱动确认停止/复位和空闲，再释放；不能只杀Python线程或释放内存当作硬件停止。

DMA模式由HWH参数和安装版本决定；上游源码与教程可能有差异，见 [upstream_review.md](upstream_review.md)。本包不提供通用DMA实板入口，具体位流与协议需由目标工程验证。

## 多板与双区域汇合

复制examples/pipeline_contract.json，替换每个分支的model_sha256、preprocess_sha256和output_contract。分支名可自由设定；每个采集帧须包含全部声明分支。记录使用examples/pipeline_results.csv的列，运行：

```text
python scripts/run.py pipeline --contract pipeline_contract.json --results branch_results.csv --expected-frames 100
```

缺分支、失败分支、重复结果、旧ROI、不同原始输入、模型/预处理/输出约定不符均返回2。成功返回0仅表示记录的身份与完整性匹配。完整质量与板上执行需要另有证据，详见 [vision_pipeline.md](vision_pipeline.md)。

## 音频输入和模型扩类

按需阅读 [audio_pipeline.md](audio_pipeline.md)，填写 [audio_contract.json](../templates/audio_contract.json)。该文件是待由目标项目填写的契约模板，不是硬件配置，也不是已经通过的验收记录。
