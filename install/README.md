# 主机依赖安装

根目录setup.ps1从Python包源安装runtime/requirements-pc.txt中固定的14项依赖。Python依赖及其自带的第三方组件由原发行方分发；许可原文和通知保留在licenses/dependencies，机器清单为compliance/python_dependencies.json。

安装要求Python3.12 x64和网络连接，环境、下载缓存及临时文件保存在工程目录。目标板的授权输入与主机依赖分别配置。
