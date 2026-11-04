# 第三方组件与许可

本目录保留原文件版权、SPDX和原组件条款。自主代码按根LICENSE许可，第三方组件按各自条款使用。

| 组件 | 材料与条款 |
|---|---|
| AMD/Xilinx及板卡支持RTL/IP | src/rtl、sim/design内保留原声明，目标BIT/HWH/XSA与对应工程配套 |
| Linux驱动与模块SDK | src/drivers源码、构建入口、匹配SDK及模块；保留GPL标识及原系统条款 |
| TensorFlow Lite 2.11 | Apache-2.0及原附属条款，完整源码和原LICENSE位于本地依赖归档 |
| Abseil、Eigen、FlatBuffers、gemmlowp、ruy等 | build/dependencies归档保留各自上游许可证 |
| ARM glibc、libstdc++、Qt和目标SDK | 保留系统/运行库原许可；源码接口、构建输入及目标版本一并固定 |
| PaddleDetection关键点处理 | Apache-2.0，保留PaddlePaddle版权和工程修改说明 |
| MediaPipe辅助标注 | 标注工具的原条款与自录素材的公开范围分别适用 |
| YOLO-FastestV2参数 | 参数按发布方确认的分发范围提供，不用其他YOLO项目的许可证替代 |
| Python依赖及附属组件 | licenses/dependencies保留原许可和ThirdPartyNotices，install/wheels保留固定发行文件 |

COCO原始训练图像不属于自录素材；数据集、模型参数、标注工具和工程代码分别采用其相应许可。项目生成的波形、截图及测试输入由文件清单追溯，工具和IP的原有权利不因生成验证资料而改变。
