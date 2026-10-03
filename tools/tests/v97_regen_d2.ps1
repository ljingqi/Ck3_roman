# v97 端到端：洪思忠 第2个十年 (973) —— 与 d1/d3 同步命名（改后展示名为教名）
Set-Location D:\Roman
Copy-Item -LiteralPath "output\洪氏2\洪思忠(917)_传记_第2个十年_973_01_01.md" `
          -Destination "output\洪氏2\_v97_before\洪思忠(917)_传记_第2个十年_973_01_01.md" -Force
& tools\py.ps1 pipeline.py bio 67172818 --decade 2
Write-Host "=== DONE ==="
