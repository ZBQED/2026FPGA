# 外部输入与目标板复现

主机监控UI、通用PYNQ技能、源码检查和模型数据可直接安装使用。完整三板推理与Vivado重建还需要与目标板匹配的硬件和软件输入。

| 类别 | 获取方式 |
|---|---|
| Vivado/Vitis与基础IP | 从AMD官方安装，按各自许可使用；自主HLS源码位于src/hls，构建入口位于build/ |
| 原厂音频、摄像头、以太网与显示支持RTL | 从开发板原厂支持资料、已授权BSP或原作者获取；保留其原有条款 |
| BIT/HWH/XSA、驱动和ARM库 | 在匹配工具链、目标内核和授权板卡工程中构建；TensorFlow依赖按build/README.md准备 |
| Linux/PYNQ基础系统与SDK | 使用对应开发板的官方系统；Nav/Q为Linux5.4，P为Linux6.6，保持原部署接口 |
| YOLO-FastestV2预训练参数 | 向相应权利方取得再分发/使用授权，或提供有明确授权且经过相同数值与接口验证的参数；本包不自动下载该上游权重 |

固定接口复现所用的文件名、长度、SHA256和外部原因全部列在compliance/external_assets.json。单纯更名或删除版权头不会取得公开许可。

## 导入已有授权输入

工具从合法取得的目录或ZIP按相对布局读取，每个文件须匹配清单摘要；缺件或摘要不符时不写入，已有修改文件不覆盖。先执行预检查：

```powershell
python -B build/import_external_assets.py --source <已授权输入目录或ZIP> --group all --dry-run
python -B build/import_external_assets.py --source <已授权输入目录或ZIP> --group all
python -B build/check_external_assets.py --group all --require
```

runtime组用于目标板部署与模型调用，hardware组用于原工程硬件重建。归档文档和Python依赖二进制不由该工具导入。导入只恢复本地工程输入，不授予这些材料的公开分发权，也不把它们加入开源发布的文件清单。

使用本地新构建产物时，先做对应黄金参考、设备版本和目标板检查，再绑定新摘要。源码包内的历史构建/运行记录保持原有适用范围，不替代新硬件或新权重的验证。

## 上游入口

- [AMD Vivado](https://www.amd.com/en/products/software/adaptive-socs-and-fpgas/vivado.html)
- [PYNQ](https://github.com/Xilinx/PYNQ)
- [Linux Xilinx](https://github.com/Xilinx/linux-xlnx)
- [TensorFlow 2.11](https://github.com/tensorflow/tensorflow/tree/v2.11.0)
- [YOLO-FastestV2许可请求](https://github.com/dog-qiuqiu/Yolo-FastestV2/issues/50)
