# 三板运行与复现

## 环境

主机使用Windows x64、Python 3.12 x64。根目录setup.ps1从Python包源安装固定版本依赖。完整推理先按../external_assets.md配齐runtime组；软件监控可直接启动。三板通过有线网络互通，使用匹配的Linux/PYNQ基础系统：

| 板卡 | 基础环境 |
|---|---|
| Nav | Linux 5.4.0-xilinx-v2020.2，Qt/DRM、128MB CMA、FP32加速设备及共享摄像头发布服务 |
| Q | Linux 5.4.0-xilinx-v2020.2，PYNQ与原推理待机服务 |
| P | Linux 6.6.10-xilinx-v2024.1-g3c0eca68c652，PYNQ及音频待机服务 |

板端系统和厂商工具按各开发板的系统安装流程配置。运行时会读取启动身份、设备版本和占用状态，再建立独立执行目录；完成后恢复原服务。

## 连接

地址：Nav 192.168.1.10，Q 192.168.1.30，P 192.168.1.20。默认通过Nav中转Q/P的SSH。known_hosts绑定设备公钥；更换板卡后，通过可信串口或管理通道核验公钥并更新该文件。

```powershell
$env:MGD_NAVIGATOR_PASSWORD='<Nav SSH密码>'
$env:MGD_QIMING_PASSWORD='<Q SSH及sudo密码>'
$env:MGD_PYNQ_PASSWORD='<P SSH及sudo密码>'
```

私钥方式设置MGD_NAVIGATOR_KEY、MGD_QIMING_KEY、MGD_PYNQ_KEY。Q/P账户配置免密sudo后，可分别设置MGD_QIMING_NOPASSWD=1、MGD_PYNQ_NOPASSWD=1。Q/P可由主机直达时设置MGD_DIRECT_SSH=1。不同账户使用MGD_NAVIGATOR_USER、MGD_QIMING_USER、MGD_PYNQ_USER。

## 模式

```powershell
.venv/Scripts/python.exe -B runtime/run.py fixed
.venv/Scripts/python.exe -B runtime/run.py tcn
.venv/Scripts/python.exe -B runtime/run.py hand
.venv/Scripts/python.exe -B runtime/run.py live
```

| 模式 | 输入与检查 |
|---|---|
| fixed | 固定双手图像24帧，检查推理、帧身份、显示扫描及恢复 |
| tcn | 363帧点位回放，比较类别、整数logits、概率及5个事件 |
| hand | P板3组黄金输入、每组3次，逐层比对并恢复音频 |
| live | 读取约1分钟共享实时图像，按原阈值与时序门运行 |
| restore | 读取当前P板恢复身份并保存快照 |

推理模式串行运行，上位机监控可并行。实时模式复用已有共享图像。输出写入project/runs/；每次单独记录输入范围、PL执行次数、同帧延迟和恢复结果。已有验证记录和当前启动身份分别保存，固定输入与实时结果分别统计。

project/与workbuddy_21/构成运行时相对布局；原始清单中的本地路径由sitecustomize.py解析，无需建立原电脑盘符。q_host_ready.template.json为只读配置模板，运行入口生成本机绑定。摄像头、手势类别、量化表、权重及确认门由该布局内的模型和接口约束。

## Nav一次性启动文件

将包内新位流、匹配内核和一次性U-Boot脚本复制至Nav的独立SD子目录：

```powershell
.venv/Scripts/python.exe -B runtime/stage_nav_boot.py
```

脚本校验每个文件并输出串口启动命令。串口进入U-Boot后执行输出命令，即使用该组位流与内核启动。脚本不覆盖BOOT.BIN、boot.scr、image.ub或保存的环境；再次按默认启动流程启动会返回原配置。匹配Nav驱动的源码和重建套件见build/README.md。

运行结果写入project/runs。发布结果按工作负载保留最快通过记录，见board/verification_summary.json。
