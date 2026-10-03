# v98 端到端重生成：洪思忠 d1(963) / d2(973) / d3(983) —— 走新的「按时代渲染」路径。
# 先把现有三篇（含 984 档旧稿）备份到 _v98_before，便于逐段对照。
$ErrorActionPreference = "Continue"
Set-Location D:\Roman

New-Item -ItemType Directory -Force -Path "output\洪氏2\_v98_before" | Out-Null
foreach ($f in @("尼各老(917)_传记_第1个十年_963_01_01.md",
                 "尼各老(917)_传记_第2个十年_973_01_01.md",
                 "尼各老(917)_传记_第3个十年_983_01_01.md")) {
    $src = Join-Path "output\洪氏2" $f
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination "output\洪氏2\_v98_before\$f" -Force
        Write-Host "备份 $f"
    }
}

Write-Host "=== 洪思忠 第1个十年 (963，时代熔件 melt_963) ==="
& tools\py.ps1 pipeline.py bio 67172818 --decade 1
Write-Host "=== 洪思忠 第2个十年 (973，时代熔件 melt_973) ==="
& tools\py.ps1 pipeline.py bio 67172818 --decade 2
Write-Host "=== 洪思忠 第3个十年 (983，时代熔件 melt_983) ==="
& tools\py.ps1 pipeline.py bio 67172818 --decade 3
Write-Host "=== DONE ==="
Get-ChildItem "output\洪氏2" -Filter "*917*_传记_*.md" | Select-Object Name, Length, LastWriteTime
