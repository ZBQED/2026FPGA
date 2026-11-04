# 工程重建

所有命令在工程根目录执行；输入使用本目录，输出使用build_output/，不同重任务串行执行。

## 本地ARM构建输入

```powershell
python -B build/unpack_dependencies.py
python -B build/unpack_dependencies.py --verify
```

三个归档分别提供ARM/Qt sysroot与目标运行库、TensorFlow 2.11源码、九项TFLite依赖。解压内容位于.cache/build_dependencies，manifest.json按归档及成员固定SHA-256。无需原电脑的SDK或TensorFlow目录。

```powershell
python -B build/reproduce.py native --vitis-root <Vitis安装目录>
python -B build/reproduce.py display --vitis-root <Vitis安装目录>
python -B build/reproduce.py qt --vitis-root <Vitis安装目录>
python -B build/reproduce.py camera --vitis-root <Vitis安装目录>
python -B build/reproduce.py tcn --vitis-root <Vitis安装目录>
python -B build/reproduce.py backend --vitis-root <Vitis安装目录>
```

采用Vitis 2024.2的ARM Linux GCC、Cortex-A9/NEON/hard-float目标、包内glibc 2.30与GCC9 C++头。backend使用本地FetchContent源码，禁止联网下载；默认两任务编译，可用--jobs调整。--configure-only用于检查backend配置。build_arm.py保留显式参数入口，build/reproduce.py负责绑定包内输入与输出路径。

## 三板FPGA

在已加载Vivado 2024.2环境的PowerShell中：

```powershell
New-Item -ItemType Directory -Force build_output
vivado -mode batch -nojournal -log build_output/q.log -source build/build_board.tcl -tclargs q build_output/q
vivado -mode batch -nojournal -log build_output/p.log -source build/build_board.tcl -tclargs p build_output/p
vivado -mode batch -nojournal -log build_output/nav.log -source build/build_board.tcl -tclargs nav build_output/nav
```

源文件、IP仓库、BD与约束均由工程根目录解析。入口完成综合、布局布线、建立/保持/脉宽与DRC检查，并导出BIT/HWH/XSA。可选第三参数为本地已布线DCP。

## HLS

```powershell
$env:HLS_OUT=(Join-Path (Get-Location) 'build_output/hls_i8')
vitis-run --mode hls --tcl build/build_hls.tcl
$env:HLS_OUT_NAV=(Join-Path (Get-Location) 'build_output/hls_nav')
vitis-run --mode hls --tcl build/build_hls_nav.tcl
```

两个输出目录使用新的位置；FP32入口同时执行包内固定样本的C仿真。

## Linux驱动

在对应目标Linux/PYNQ系统、匹配的内核模块构建环境中，Q/P分别执行：

```sh
make -C src/drivers/q kernel_src=/usr/src/kernel cross_compile=
make -C src/drivers/p kernel_src=/usr/src/kernel cross_compile= CC=gcc-12
```

内核构建环境属于目标系统SDK，需与目标uname、配置及符号CRC一致。Nav使用包内匹配SDK：

```sh
mkdir -p build_output/kernel_nav
tar -xzf build/sdk/nav/nav_module_sdk.tar.gz -C build_output/kernel_nav
KERNEL_BUILD="$PWD/build_output/kernel_nav" CC=gcc-9 sh build/build_nav_driver.sh "$PWD/build_output/nav_driver"
```

该SDK覆盖Nav模块所需配置、生成头和39项导入CRC，部署时与包内Nav位流、内核和设备树配套。目标系统的Python/PYNQ、内核构建工具及AMD工具按对应平台安装。

## 数值与显示

在匹配ARM环境执行sim/display/verify_display.py，指定包内黄金参考和显示库；--drm同时核对DRM扫描回执。RTL和通用数值工具见sim/README.md。
