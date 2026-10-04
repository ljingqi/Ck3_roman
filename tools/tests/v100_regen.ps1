# v100 端到端重生成（洪氏2 · 洪思忠/尼各老，pid 67172818）
# 三问的落地都要在成稿上可见：① 官职与绰号回滚为直接相连；②《礼仪志》第三板块改为
# 「纪事·大公会议与教宗诏书」；③ 伊斯兰国名改取家族名并加政体门（行政制 e_arabia 用
# 头衔名「阿拉伯帝国」）。旧稿先备份到 output\洪氏2\_v100_before\，便于逐段对照。
$ErrorActionPreference = "Continue"
Set-Location D:\Roman

New-Item -ItemType Directory -Force -Path "output\洪氏2\_v100_before" | Out-Null
$targets = @(
    "尼各老(917)_终传_999_07_07.md",
    "洪思忠(917)_传记_第1个十年_963_01_01.md",
    "洪思忠(917)_传记_第2个十年_973_01_01.md",
    "尼各老(917)_传记_第3个十年_983_01_01.md",
    "尼各老(917)_传记_第4个十年_993_01_01.md"
)
foreach ($f in $targets) {
    $src = Join-Path "output\洪氏2" $f
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination "output\洪氏2\_v100_before\$f" -Force
        Write-Host "备份 $f"
    }
}

Write-Host "=== 洪思忠 第1个十年 (963，时代熔件) ==="
& tools\py.ps1 pipeline.py bio 67172818 --decade 1
Write-Host "=== 洪思忠 第2个十年 (973，时代熔件) ==="
& tools\py.ps1 pipeline.py bio 67172818 --decade 2
Write-Host "=== 洪思忠 第3个十年 (983，时代熔件) ==="
& tools\py.ps1 pipeline.py bio 67172818 --decade 3
Write-Host "=== 洪思忠 第4个十年 (993，时代熔件) ==="
& tools\py.ps1 pipeline.py bio 67172818 --decade 4
Write-Host "=== 洪思忠/尼各老 终传 (999.7.7) ==="
& tools\py.ps1 pipeline.py bio 67172818
Write-Host "=== DONE ==="
Get-ChildItem "output\洪氏2" -Filter "*917*.md" | Select-Object Name, Length, LastWriteTime
