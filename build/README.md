# 工程重建

本源码发行版的厂商IP、SDK和预编译目标文件采用外部输入方式，先按../external_assets.md配齐hardware/runtime组。src/hls保留自主HLS源码，生成IP需安装Vivado/Vitis；build/sdk/drm保留有原许可的开发头，目标libdrm由系统提供。

## 三板FPGA

使用Vivado/Vitis 2024.2，输出放新的英文短路径，三板重任务串行执行。build_board.tcl完成综合、布局布线、时序与DRC检查，再导出BIT/HWH/XSA。

```powershell
vivado -mode batch -nojournal -log E:/fpga_build/q.log -source build/build_board.tcl -tclargs q E:/fpga_build/q
vivado -mode batch -nojournal -log E:/fpga_build/p.log -source build/build_board.tcl -tclargs p E:/fpga_build/p
vivado -mode batch -nojournal -log E:/fpga_build/nav.log -source build/build_board.tcl -tclargs nav E:/fpga_build/nav
```

第四个可选参数为已布线参考DCP。整板源码仍重新综合。HLS入口：

```powershell
$env:HLS_OUT='E:/fpga_build/i8_hls'
vitis-run --mode hls --tcl build/build_hls.tcl
$env:HLS_OUT_NAV='E:/fpga_build/nav_hls'
vitis-run --mode hls --tcl build/build_hls_nav.tcl
```

## ARM原生算子与界面

使用ARMv7 Cortex-A9、NEON、hard-float工具链及匹配glibc 2.30/libstdc++运行环境。build_arm.py支持native、display、tcn、qt、camera。参数分别指向工具链bin、目标sysroot、目标运行库和新的工程外输出目录。

```powershell
python build/build_arm.py native --compiler-dir <工具链bin> --sysroot <目标sysroot> --runtime-libs <目标运行库> --output <新输出目录>
python build/build_arm.py display --compiler-dir <工具链bin> --sysroot <目标sysroot> --runtime-libs <目标运行库> --drm-sdk build/sdk/drm --output <新输出目录>
```

Qt与camera使用相同基础参数。Qt头文件和运行库需匹配目标板；修改界面后重新生成moc/rcc，bindings.json约束生成输入。Linux本机原生库可用build_native.sh。

普通TFLite后端使用TensorFlow 2.11.0源码与build/nav_fp32/CMakeLists.txt，配合ARM交叉CMake工具链构建。设置GESTURE_TENSORFLOW_SOURCE指向TensorFlow源码；使用GCC13配GCC9头时设置GESTURE_CPP9_INCLUDE。TCN的--tf-source、--tf-dependencies分别指向同版本TensorFlow及flatbuffers/gemmlowp/abseil目录；--backend-library指向刚构建的普通libgesture_tflite_pl.so，默认采用artifacts/arm中的同名库。

```powershell
python build/build_arm.py tcn --compiler-dir <工具链bin> --sysroot <目标sysroot> --runtime-libs <目标运行库> --tf-source <TensorFlow源码> --tf-dependencies <依赖目录> --backend-library <普通后端so> --output <新输出目录>
```

## Linux驱动

Q/P使用对应目标内核构建树：

```sh
make -C src/drivers/q kernel_src=/path/to/q/kernel cross_compile=
make -C src/drivers/p kernel_src=/path/to/p/kernel cross_compile= CC=gcc-12
```

Nav模块构建使用目标Linux 5.4 SDK、配套配置与导入符号CRC。SDK压缩包由合法取得的目标输入提供；本包保留配置与来源索引。在ARM Linux构建机上：

```sh
mkdir -p /data/nav_kernel
tar -xzf build/sdk/nav/nav_module_sdk.tar.gz -C /data/nav_kernel
KERNEL_BUILD=/data/nav_kernel CROSS_COMPILE= CC=gcc-9 sh build/build_nav_driver.sh /data/new_nav_module
```

交叉构建时设置CROSS_COMPILE为ARM前缀，CC为对应编译器。该套件用于本工程Nav外部模块，不是完整内核发行包；更换内核应使用新目标的配置、生成头与符号表。provenance.json记录来源及39项导入CRC校验。驱动部署与位流、设备树和内核版本配套。

## 显示数值复核

将sim/display/verify_display.py、golden.json及新编译的显示库放在匹配的ARM Linux环境执行：

```sh
python3 verify_display.py --library ./liblive_integer_frame.so --golden ./golden.json --output ./display_result.json --drm
```

省略--drm只执行像素与整数变换检查。源码、构建产物与运行验证分开记录于artifacts、reports和../board/outputs。
