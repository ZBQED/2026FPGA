# FPGA医疗手语交流系统

系统以领航者主控板、启明星加速板和PYNQ-Z2组成三板计算平台，完成图像采集、人物检测、人体与双手关键点、TCN时序分类、音频意图、触摸交互及同帧显示。核心卷积、双手关键点网络和TCN由FPGA加速；板端ARM负责几何处理、特征整理、任务调度和设备控制。PC承担Palm/Body前段、部分后处理、运行组织与上位机监控。

人物检测采用COCO体系下的YOLO-FastestV2，输入192×192、INT8、仅保留人物类别。掌部、手部和人体模型采用自录10余万张图像，经MediaPipe辅助标注后训练的权重。模型、量化表、左右手身份和时序类别映射随部署文件固定。

## 项目结构

| 路径 | 内容 |
|---|---|
| setup.ps1、install/ | Windows/Python安装入口、14项离线依赖及摘要校验 |
| src/ | RTL/IP、HLS、Linux驱动、ARM算子、Qt界面、音频与协同源码 |
| runtime/ | 三板连接、模型与权重、同帧推理及恢复入口 |
| host_monitor/ | 上位机服务、监控页面和三板数据适配 |
| board/ | BIT/HWH、驱动、运行库、设备树、启动文件及运行记录 |
| build/ | Vivado/HLS/ARM构建入口、目标SDK、构建结果和资源时序报告 |
| build/dependencies/ | ARM sysroot、Qt头/运行库、TensorFlow和TFLite依赖源码归档 |
| data/ | 部署模型、固定输入、黄金参考及8个演示视频 |
| sim/ | 卷积、摄像头、以太网、音频、视频及显示验证，含波形和截图 |
| skill/ | 可独立复用的PYNQ工作流、工程模板、校验脚本和故障定位规则 |
| licenses/、compliance/ | 原许可证、逐文件许可范围、组件摘要和发布依据 |
| files.sha256 | 工程完整性清单 |

运行所需的模型、权重、位流、驱动、运行库及主机依赖均位于本目录。ARM源码构建使用build/dependencies中的本地归档，构建脚本按项目位置解析路径，无需其他工程目录。解压依赖写入.cache/，重建结果写入build_output/。

## 环境

主机使用Windows x64、Python 3.12 x64。FPGA/HLS重建使用Vivado/Vitis 2024.2；ARM交叉构建使用该版本自带的Cortex-A9 Linux工具链。

| 板卡 | 系统与任务 |
|---|---|
| Nav | Linux 5.4.0-xilinx-v2020.2；共享摄像头发布、Qt/DRM与FP32加速设备 |
| Q | Linux 5.4.0-xilinx-v2020.2、PYNQ；人物检测、一路Hand和TCN |
| P | Linux 6.6.10-xilinx-v2024.1-g3c0eca68c652、PYNQ；另一路Hand与音频服务 |

三板基础系统、内核及设备服务按对应板卡环境配置。Python和AMD工具属于平台安装条件；工程数据及构建输入由本目录提供。

## 离线安装与检查

从工程根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Python python
.venv/Scripts/python.exe -B build/verify_package.py
.venv/Scripts/python.exe -B board/check_reproduction.py
```

安装器先检查工程摘要，再校验14项离线wheel并创建本目录的.venv。依赖从install/wheels安装，缓存和日志保存在工程目录。

## 三板运行

默认有线网络地址为Nav 192.168.1.10、Q 192.168.1.30、P 192.168.1.20。SSH凭据由环境变量提供：

```powershell
$env:MGD_NAVIGATOR_PASSWORD='<Nav密码>'
$env:MGD_QIMING_PASSWORD='<Q密码>'
$env:MGD_PYNQ_PASSWORD='<P密码>'
.venv/Scripts/python.exe -B runtime/run.py fixed
.venv/Scripts/python.exe -B runtime/run.py tcn
.venv/Scripts/python.exe -B runtime/run.py hand
```

fixed运行固定双手输入并核对同帧显示与资源恢复；tcn回放363帧点位，比较整数结果与5个事件；hand执行手部黄金输入并恢复音频。实时模式为runtime/run.py live，读取板端已有共享摄像头帧。各推理模式串行运行。私钥连接、启动身份及恢复流程见[runtime/README.md](runtime/README.md)。

## 上位机

```powershell
.venv/Scripts/python.exe -B host_monitor/launch_monitor.py
```

浏览器访问http://127.0.0.1:8765。界面显示三板在线、温度、通信速率、同帧骨架、识别事件及音频数值。停止监控使用host_monitor/stop_monitor.py。监控可与一条板端推理任务同时运行。

## 本目录重建

```powershell
.venv/Scripts/python.exe -B build/unpack_dependencies.py
.venv/Scripts/python.exe -B build/reproduce.py display --vitis-root <Vitis安装目录>
.venv/Scripts/python.exe -B build/reproduce.py qt --vitis-root <Vitis安装目录>
.venv/Scripts/python.exe -B build/reproduce.py tcn --vitis-root <Vitis安装目录>
```

reproduce.py还提供native、camera和backend。backend从本地TensorFlow/TFLite源码构建普通后端；--configure-only执行离线配置。输出位于build_output/对应组件。三板FPGA、HLS和目标Linux驱动的命令见[build/README.md](build/README.md)。

## 验证与通用PYNQ技能

```powershell
.venv/Scripts/python.exe -B skill/pynq-evidence-audit/scripts/run.py test
```

仿真与波形查看见[sim/README.md](sim/README.md)。运行结果按工作负载保留最快通过记录，数值与恢复证据由board/verification_summary.json索引。通用技能位于[skill/](skill/README.md)，每项说明适用范围、使用方法、验证效果、失败观察和失效条件。

## 许可证

自主代码、HLS与自训参数按MIT提供；Linux驱动保留GPL-2.0；PaddleDetection派生文件保留Apache-2.0；文档、视频、图像及项目生成波形保留相应CC-BY-4.0说明。厂商IP、SDK、系统文件和第三方组件沿用各自原条款。根目录LICENSE的适用范围及逐文件映射见[license_scope.md](license_scope.md)和compliance/file_licenses.json。

## 工程报告与完整原始记录

报告：[Word](report/design/system_report.docx)、[PDF](report/design/system_report.pdf)。固定视觉、TCN回放及手部验证的完整原始JSON见[报告目录](report/README.md)。
