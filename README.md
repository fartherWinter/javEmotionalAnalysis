# 知语 · Windows 本地聊天分析助手

PySide6 原生桌面软件：CipherTalk 读取微信单聊 → Laya 结构化判断 → 用户配置的模型生成三条回复。支持联系人档案、证据可追溯的确认式记忆；仅复制，不自动发送。

0.2.0：复用本地模型进程、中文意图问题、可跳过实验性判断、候选可编辑、自动查找已准备的依赖。首次加载后本机实测本地判断约 0.5 秒；真实微信和生成接口的全链路仍需本机配置后验收。

双击解压目录内的 `JevLocalAssistant.exe`，无需浏览器和主程序 Python 环境。CipherTalk、Node 与 Laya 模型作为外部依赖单独准备。

- [桌面使用说明](docs/桌面使用说明.md)
- [实现与验收边界](docs/实现与验收.md)
- [实测结果](docs/验收结果.md)

开发：`uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt`，随后运行 `launch_desktop.py`。测试和打包命令见使用说明。
