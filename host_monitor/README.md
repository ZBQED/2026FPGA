# 上位机监控

页面包含系统总览、板卡状态、骨架与识别结果、网络和音频状态。使用Python HTTP服务及HTML/CSS/JavaScript，无需Node.js。页面样式与布局保持原版，数据源接入当前三板FPGA程序。

## 启动

先执行根目录setup.ps1，并按runtime/README.md设置三板连接环境变量。

```powershell
.venv/Scripts/python.exe -B host_monitor/launch_monitor.py
```

浏览器访问`http://127.0.0.1:8765`，也可运行`host_monitor/open_monitor.pyw`打开Edge独立窗口。更换端口使用`--port 8767`。停止服务：

```powershell
.venv/Scripts/python.exe -B host_monitor/stop_monitor.py
```

## 数据与运行

固定输入或实时推理通过`runtime/run.py`启动。协调器写入当前会话身份；Nav在同帧显示完成后发布数值快照，服务按会话、进程身份和有效期读取。人体17点、每手21点、人物框和TCN事件均由该链路提供。固定输入模式有独立标识；停止后保留最后一帧并标明状态。

温度与网络速率来自板端系统计数器，功率只接受有效传感器或带采样时刻的外接表数据。音频页面读取当前板端包络和意图状态。缺少数据时显示空值；输入与推理帧率分别由采集序号和发布序号计算。

服务仅绑定127.0.0.1。监控程序读取状态，不启动神经网络或重新打开物理摄像头；推理任务由runtime入口组织。运行日志、服务凭证与浏览器缓存写入本目录runtime/。

| 文件 | 用途 |
|---|---|
| server.py | HTTP/API与三板状态采集 |
| pipeline_source.py | 当前三板同帧数据适配 |
| audio_stream.py | 音频数值状态读取 |
| web/ | 页面、样式、脚本与API字段说明 |
| config/speech_intents.json | 医疗语音意图映射 |
