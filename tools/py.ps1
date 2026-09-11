# tools\py.ps1 — 以 UTF-8 输出运行 Python（参数原样转发）
#
# 用法：& D:\Roman\tools\py.ps1 localization.py mods
#       & D:\Roman\tools\py.ps1 experiments\verify_zhou.py
#
# 说明：点源同级 enc.ps1 统一控制台/Python 编码（见 enc.ps1 顶部的根因说明），
#       从而免去「中文乱码 → 落文件 → 再读一遍」的往返。$LASTEXITCODE 原样透出。

. "$PSScriptRoot\enc.ps1"
& python @args
