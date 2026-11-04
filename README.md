# FPGA医疗手语交流系统

面向医疗服务中的手语与语音交流，系统以三块FPGA开发板完成卷积加速、双手关键点和TCN时序推理，并组织同帧显示、触摸确认、音频意图和业务信息输出。领航者主控板采集图像、处理Palm/Body输出头并显示；启明星承担YOLO-FastestV2、一路Hand与TCN；PYNQ-Z2承担另一路Hand与音频。PC提供Palm/Body前段、部分后处理、运行组织和监控界面。

## 发布内容

这是开源源码发行包，包含自主程序、自训部署参数、测试参考、8个演示视频和可复用PYNQ技能。厂商IP源码、板端预编译文件、系统SDK及未确认分发授权的YOLO-FastestV2预训练参数作为外部输入管理，详见[external_assets.md](external_assets.md)。安装主机软件和运行监控UI无需导入这些目标板文件；整机推理和完整硬件重建需先配齐对应输入。

| 路径 | 内容 |
|---|---|
| src/ | HLS、板端驱动、ARM整数算子、Qt界面、音频与协同程序源码 |
| runtime/ | 三板连接、同帧调度、模型参数与运行入口 |
| host_monitor/ | 监控服务和原有HTML/CSS/JavaScript页面 |
| data/ | 自训模型、固定输入、黄金参考和演示视频 |
| build/、sim/ | 构建入口、仿真、自检及外部输入导入工具 |
| board/ | 部署配置、历史运行证据及构建结果索引 |
| skill/ | 通用PYNQ工作流、模板、验证脚本和故障定位方法 |
| LICENSE、licenses/ | 自主代码许可证及第三方许可原文 |
| third_party_notices.md | 第三方组件、保留版权及发布边界 |
| model_and_data_license.md、compliance/ | 模型/素材权限说明、文件许可映射与摘要 |

## 安装与启动

使用Windows x64和Python 3.12 x64，解压至可写数据盘。首次安装从Python包源取得固定版本依赖；虚拟环境、缓存与日志写入工程目录。

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1 -Python python
.venv/Scripts/python.exe -B host_monitor/launch_monitor.py
```

浏览器访问`http://127.0.0.1:8765`。连接环境变量见[runtime/README.md](runtime/README.md)。监控界面显示三板状态、温度、网络速率、同帧骨架、识别事件及音频数值，不另起神经网络或打开摄像头。

## 源码检查与板端复现

```powershell
python -B build/verify_package.py
python -B build/check_external_assets.py --group all
python -B skill/pynq-evidence-audit/scripts/run.py test
```

源码检查核验全部文件摘要、许可证覆盖、Python/JSON语法、界面与仿真引用；外部输入单独列明。取得对应授权的板卡支持文件、预训练参数和目标构建产物后，按external_assets.md导入，再串行执行：

```powershell
.venv/Scripts/python.exe -B runtime/run.py fixed
.venv/Scripts/python.exe -B runtime/run.py tcn
.venv/Scripts/python.exe -B runtime/run.py hand
```

实时模式为`runtime/run.py live`，读取已有共享摄像头帧。构建所需Vivado/Vitis、Linux/PYNQ基础系统及目标工具链由各官方发行方提供。构建说明见[build/README.md](build/README.md)。

## 许可证

自主软件、HLS与自训参数采用MIT；Linux驱动采用GPL-2.0-only；PaddleDetection派生文件保留Apache-2.0；文档、演示视频与图像样本采用CC-BY-4.0。第三方原许可与版权声明优先适用于相应文件，逐文件范围见compliance/file_licenses.json。许可证不覆盖外部输入，也不把COCO图片、MediaPipe标注工具或YOLO-FastestV2权重统归为项目自有资产。

重新打包公开源码时使用`python -B build/package_public.py --output <工程外的ZIP路径>`。打包器仅收录公开摘要清单，已导入的厂商文件和本地缓存不会混入发布包。发布授权依据见[publisher_authorization.md](publisher_authorization.md)。


## 最新报告与协作材料

系统报告：[Word](report/design/system_report.docx)、[PDF](report/design/system_report.pdf)。
大模型协作记录：[16项协作与工程依据](report/collaboration/development_record.md)。
三板Vivado截图、资源时序报告及完整原始板测记录见[报告目录](report/README.md)。
