# 许可证适用范围

| 组件 | 适用范围 |
|---|---|
| 自主Python/C/C++/HLS及自训参数 | MIT，见LICENSE和licenses/mit.txt |
| Linux外部驱动 | 保留GPL-2.0条款、源码和构建入口 |
| PaddleDetection派生代码 | Apache-2.0，保留作者版权与修改说明 |
| 文档、视频、图像、项目波形及截图 | 对应文件的CC-BY-4.0范围 |
| TensorFlow和TFLite依赖源码 | 各上游原许可；归档内保留LICENSE/COPYING等文件 |
| 厂商RTL/IP、SDK、内核/系统和预编译组件 | 原组件条款及发布方确认的分发权限；不改为自主MIT |
| Python wheel及附属组件 | 原发行方许可与第三方通知，见licenses/dependencies |

compliance/file_licenses.json逐文件区分自主许可与LicenseRef-Original-Component-Terms。后者指向组件自带的原条款，项目许可证不增加第三方材料的权利。compliance/bundled_inputs.json给出工程组件摘要；build/dependencies/manifest.json给出源码/SDK归档及成员摘要。
