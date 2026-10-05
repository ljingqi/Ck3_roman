# v104 端到端重生成（洪氏2 · 耀国·洪堡，pid 135480）
# 六问的落地要在成稿上可见：
#   ① 改礼前的定夺回到教会纪事（1014/1021…）② 1057.9.1 核心教义写出内容（天主教主流礼仪）
#   ③ 1056.1.25 世俗型会议写出傀儡（教宗酒鬼玛尔定）④ 1059.12.5 会议写出地点（圣地亚哥）
#   ⑤ 儿子写成「耀国·耀国松」⑥ 家室材料分句 + roster 分组 + 兼链（含官职）
# 旧稿备份到 output\洪氏2\_v104_before\。
$ErrorActionPreference = "Continue"
Set-Location D:\Roman

New-Item -ItemType Directory -Force -Path "output\洪氏2\_v104_before" | Out-Null
# ASCII-only matching on purpose: this script is UTF-8 without a BOM, and `powershell -File` (5.1)
# decodes non-ASCII literals as GBK, which silently turns 「洪氏2」 into a stray mojibake folder.
$targets = Get-ChildItem "output\洪氏2" -Filter "*.md" |
    Where-Object { $_.Name -like "*1003*" -and $_.Name -like "*洪堡*" }
foreach ($t in $targets) {
    Copy-Item -LiteralPath $t.FullName -Destination (Join-Path "output\洪氏2\_v104_before" $t.Name) -Force
    Write-Host ("备份 " + $t.Name)
}

Write-Host "=== 耀国 第4个十年 (1050，改礼前口径) ==="
& tools\py.ps1 pipeline.py bio 135480 --decade 4
Write-Host "=== 耀国 第5个十年 (1060) ==="
& tools\py.ps1 pipeline.py bio 135480 --decade 5
Write-Host "=== 耀国 第6个十年 (1070) ==="
& tools\py.ps1 pipeline.py bio 135480 --decade 6
Write-Host "=== 耀国 终传 (1075.9.8) ==="
& tools\py.ps1 pipeline.py bio 135480
Write-Host "=== DONE ==="
Get-ChildItem "output\洪氏2" -Filter "*1003*.md" | Select-Object Name, Length, LastWriteTime
