# v97 端到端重生成：洪思忠 d1(963) / d3(983) / 洪天贵福 终传(952)
$ErrorActionPreference = "Continue"
Set-Location D:\Roman

Write-Host "=== 洪思忠 第1个十年 (963) ==="
& tools\py.ps1 pipeline.py bio 67172818 --decade 1

Write-Host "=== 洪思忠 第3个十年 (983) ==="
& tools\py.ps1 pipeline.py bio 67172818 --decade 3

Write-Host "=== 洪天贵福 终传 (952) ==="
& tools\py.ps1 pipeline.py bio 44503

Write-Host "=== DONE ==="
