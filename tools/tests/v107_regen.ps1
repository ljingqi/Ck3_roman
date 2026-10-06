# v107 end-to-end regeneration (洪氏2 / 耀国·缯松, pid 135480)
#   ① 亲属词领属者感知：诸子行迹里的「孩子的妹妹是桑莎」应变成「孩子的母亲是桑莎」
#   ② 子女行改「儿子：/女儿：」带头 + 逐人一行
# Old drafts are backed up to output\洪氏2\_v107_before\ first.
# ASCII-only -like patterns on purpose: this script is UTF-8 without a BOM and `powershell -File`
# (5.1) decodes non-ASCII literals as GBK, which silently turns a folder name into mojibake.
$ErrorActionPreference = "Continue"
Set-Location D:\Roman

New-Item -ItemType Directory -Force -Path "output\洪氏2\_v107_before" | Out-Null
$targets = Get-ChildItem "output\洪氏2" -Filter "*.md" |
    Where-Object { $_.Name -like "*1003*" }
foreach ($t in $targets) {
    Copy-Item -LiteralPath $t.FullName -Destination (Join-Path "output\洪氏2\_v107_before" $t.Name) -Force
    Write-Host ("backup " + $t.Name)
}

Write-Host "=== 第2个十年 (1030) ==="
& tools\py.ps1 pipeline.py bio 135480 --decade 2
Write-Host "=== 第3个十年 (1040) ==="
& tools\py.ps1 pipeline.py bio 135480 --decade 3
Write-Host "=== 第4个十年 (1050) ==="
& tools\py.ps1 pipeline.py bio 135480 --decade 4
Write-Host "=== 第5个十年 (1060) ==="
& tools\py.ps1 pipeline.py bio 135480 --decade 5
Write-Host "=== 第6个十年 (1070) ==="
& tools\py.ps1 pipeline.py bio 135480 --decade 6
Write-Host "=== 终传 (1075.9.8) ==="
& tools\py.ps1 pipeline.py bio 135480
Write-Host "=== DONE ==="
Get-ChildItem "output\洪氏2" -Filter "*1003*.md" | Select-Object Name, Length, LastWriteTime
