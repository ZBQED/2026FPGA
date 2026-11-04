# 关键仿真与验证

仿真使用的厂商与工具生成RTL属于hardware外部输入，先按../external_assets.md取得相应授权并导入。Python通用技能测试和数值参考生成可直接运行。

## 复现

使用Python 3.10+及Vivado 2024.2。从工程根目录串行运行，各次输出选新的工程外目录：

```powershell
python -B sim/run_sim.py ov5640 --output E:/fpga_verify/ov5640 --vivado-bin E:/vivado2024.2/Vivado/2024.2/bin
python -B sim/run_sim.py ethernet --output E:/fpga_verify/ethernet --vivado-bin E:/vivado2024.2/Vivado/2024.2/bin
python -B sim/run_sim.py p_audio --output E:/fpga_verify/p_audio --vivado-bin E:/vivado2024.2/Vivado/2024.2/bin
python -B sim/run_sim.py video --output E:/fpga_verify/video --vivado-bin E:/vivado2024.2/Vivado/2024.2/bin
python -B sim/run_sim.py core --output E:/fpga_verify/core --vivado-bin E:/vivado2024.2/Vivado/2024.2/bin
```

Vivado在PATH中时可省略`--vivado-bin`。脚本从包内复制源码、内存初始化与冻结激励到新目录后执行xelab/xsim，按自校验PASS标记与进程退出码判定；不会连接板卡。`--check-only`只检查项目文件引用闭包。

| 用例 | 检查对象 | 已有实仿结果 |
|---|---|---|
| ov5640 | 帧预热、行帧有效、RGB565到RGB888 | 10帧预热，3有效帧/9行/72像素逐值通过 |
| ethernet | RGMII DDR收发、低高半字节、帧间空闲 | 3帧，收发各104B，208个半字节，12空闲周期 |
| p_audio | I2S左右声道、24bit边界、串行独立解码、ready清除 | 8立体声对，16接收样本、16独立解码、8清除检查 |
| video | AXI视频输入、背压及像素顺序 | 3帧72像素，119次停顿、108个下游暂停周期 |
| core | PW、DW、TCN型卷积；AXI读写与输出守卫 | 3组共312B输出与独立整数参考完全一致 |

`results/reproduction_20261104`是本交付脚本重新仿真的日志与结果。`results/<case>`保存原始WDB/VCD和对应日志，`screenshots`保留报告采用的8张Vivado截图，`wave_config`给出整体和细节视图。GUI截图对应原始波形，不是软件绘制的信号示意图。

## 打开波形

```powershell
vivado -mode gui -source sim/open_wave.tcl -tclargs core overview
vivado -mode gui -source sim/open_wave.tcl -tclargs core detail
```

支持`core`、`ov5640`、`ethernet`、`p_audio`及`overview/detail`；video可以在Vivado中直接打开`results/video/video.wdb`选取信号。截图保留较少关键信号，整体与局部各一幅。


## 技能验证

```powershell
python -B skill/pynq-evidence-audit/scripts/run.py test
python -B skill/pynq-evidence-audit/scripts/run.py demo --output-dir E:/fpga_verify/skill_demo
python -B skill/pynq-evidence-audit/scripts/check_manifest.py verify skill skill/files_sha256.json --strict
```

技能演示里的小型位流/硬件描述是验证工具的合成输入，位于`results/skill_validation/demo`；它们不是上板文件。演示包含故意损坏输入的负例，程序正确拒绝才算通过。
