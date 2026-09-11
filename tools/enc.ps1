# tools\enc.ps1 — 统一 UTF-8 输出（开发工具链用，非产品代码）
#
# 根因（实测 2026-09-11）：
#   Python 子进程的中文按 **cp936** 写出（管道模式下用 locale 编码），而 DSH 侧的
#   pwsh 捕获按 **UTF-8** 解码 → 每次中文输出都变 `����`。于是「跑一遍 → 落文件 →
#   再 read 一次」成了常态，白白翻倍工具调用。
#   实测对照：python 默认 = 乱码；PYTHONIOENCODING=utf-8 或 python -X utf8 = 正常；
#   cmd + chcp 65001 **无效**（chcp 只改控制台代码页，不改管道下 Python 的编码）。
#
# 用法：在命令开头点源本文件，或直接用 tools\py.ps1 跑 Python：
#   . D:\Roman\tools\enc.ps1 ; python localization.py mods
#   & D:\Roman\tools\py.ps1 localization.py mods
#
# 注意：只在**开发/工具链**侧设置。产品入口（启动监控.bat，chcp 936）保持 GBK 输出，
# 见技能 utf8-gbk-encoding —— 不要把 PYTHONIOENCODING 写死进项目代码。

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
