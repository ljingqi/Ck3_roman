# v102 end-to-end regeneration (洪氏2 · 缯 pid 16878235, 审礼 pid 16879059)
# The three reported defects plus the name-order fix have to be visible in the prose:
#   1) the protagonist reads 缯·洪堡 (not 缯·仁德) and his elder brother 洪审礼 (not 审礼·仁德);
#   2) the kinship material states the father's child count, the number of mothers and the
#      birth rank, so no line can read "母亲八人";
#   3) the 【瘟疫】 block is gone.
# The old pieces are backed up to output\洪氏2\_v102_before\ first.
$ErrorActionPreference = "Continue"
Set-Location D:\Roman

New-Item -ItemType Directory -Force -Path "output\洪氏2\_v102_before" | Out-Null
$targets = @(
    "缯·仁德(954)_终传_1009_06_26.md",
    "洪审礼(955)_终传_1000_06_04.md"
)
foreach ($f in $targets) {
    $src = Join-Path "output\洪氏2" $f
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination "output\洪氏2\_v102_before\$f" -Force
        Write-Host "backed up $f"
    }
}

Write-Host "=== 缯 终传 (1009.6.26) ==="
& tools\py.ps1 pipeline.py bio 16878235
Write-Host "=== 洪审礼 终传 (1000.6.4) ==="
& tools\py.ps1 pipeline.py bio 16879059
Write-Host "=== DONE ==="
Get-ChildItem "output\洪氏2" -Filter "*.md" | Select-Object Name, Length, LastWriteTime
