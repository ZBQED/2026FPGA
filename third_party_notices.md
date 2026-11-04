# 第三方许可与版权说明

本发行包的自主软件按根目录LICENSE（MIT）发布。第三方内容按各自原许可保留，不因位于同一工程而重新授予MIT。license_scope.md及compliance/file_licenses.json给出具体文件范围。

| 组件 | 许可及处理 | 来源 |
|---|---|---|
| Linux外部驱动源码 | GPL-2.0-only；保留SPDX和MODULE_LICENSE，提供完整工程驱动源码与构建入口；不分发内核镜像或模块SDK二进制 | https://github.com/Xilinx/linux-xlnx |
| PaddleDetection关键点预/后处理 | Apache-2.0；保留PaddlePaddle作者版权；各派生文件注明项目修改 | https://github.com/PaddlePaddle/PaddleDetection |
| libdrm开发头 | 保留文件内原始许可、版权与免责条款；不分发libdrm预编译共享库 | https://gitlab.freedesktop.org/mesa/drm |
| TensorFlow Lite 2.11接口与构建依赖 | Apache-2.0；上游完整LICENSE（含Caffe条款）置于licenses/upstream；运行库由目标环境构建 | https://github.com/tensorflow/tensorflow/tree/v2.11.0 |
| MediaPipe辅助标注 | Apache-2.0；作为训练标注工具列明，不以其许可证替代自录素材的公开授权 | https://github.com/google-ai-edge/mediapipe |
| PYNQ基础环境 | BSD-3-Clause及上游第三方许可；基础系统和原厂IP由官方提供 | https://github.com/Xilinx/PYNQ |
| Python依赖 | 原始发行方提供；固定版本、原许可与第三方通知分别保存在runtime/requirements-pc.txt及licenses/dependencies | https://pypi.org/ |

PaddleDetection派生文件及修改标识见compliance/upstream_modifications.json。Python依赖包含NumPy、OpenCV、ONNX Runtime、Paramiko、cryptography、bcrypt、PyNaCl、psutil、cffi、protobuf、flatbuffers、packaging、pycparser与six；组合许可、附属组件和版权原文不做删节。依赖二进制不随本源码包分发，由安装器向原发行渠道获取。

## 不随开源包分发的材料

YOLO-FastestV2上游仓库未提供明确的许可证文件，其公开许可请求仍可查阅：[上游仓库](https://github.com/dog-qiuqiu/Yolo-FastestV2)、[许可问题](https://github.com/dog-qiuqiu/Yolo-FastestV2/issues/50)。原预训练参数、包含该参数的C头文件及目标共享库不随本源码包分发。网络架构名称、输入尺寸及接口数据不作为预训练权重的分发授权。

含正点原子版权的教学RTL、Xilinx/AMD专有声明的原厂RTL、Vitis生成IP、目标位流、系统镜像及SDK预编译文件，由具备相应许可的环境获取或重建。厂商授权不等同于MIT开源许可。不得仅添加本项目LICENSE便将这些内容重新发布为MIT。

COCO训练图片不随包分发。其标注与各原图的条款应分别遵循[COCO官方条款](https://cocodataset.org/#termsofuse)，不能将标注许可自动套用到所有图片。

外部文件清单、摘要及获取方式见external_assets.md与compliance/external_assets.json；这些文件不计入本源码包的许可覆盖范围。
