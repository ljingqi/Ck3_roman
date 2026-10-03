# v97 快照取证：HEAD 对照（8610dbd + 旧对照表）与改后各一份，供 snapdiff 比对。
# 用法：pwsh -File tools\tests\v97_snap_all.ps1
$ErrorActionPreference = "Stop"
$root = "D:\Roman"
Set-Location $root

Write-Host "=== 1) 暂存新表，换上 v97 之前的对照表 ==="
Copy-Item "$root\data\localization.json" "$root\data\localization.json.v97" -Force
Copy-Item "$root\data\localization.json.pre_v97" "$root\data\localization.json" -Force

try {
    Write-Host "=== 2) HEAD(8610dbd) 对照快照 d1(963) ==="
    & "$root\tools\py.ps1" "$root\tools\tests\snap_at_head.py" 洪氏2 67172818 963.1.1 1 --name=v97_head_d1 --ref=8610dbd
    Write-Host "=== 3) HEAD(8610dbd) 对照快照 d3(983) ==="
    & "$root\tools\py.ps1" "$root\tools\tests\snap_at_head.py" 洪氏2 67172818 983.1.1 3 --name=v97_head_d3 --ref=8610dbd
}
finally {
    Write-Host "=== 4) 还原 v97 新表 ==="
    Copy-Item "$root\data\localization.json.v97" "$root\data\localization.json" -Force
}

Write-Host "=== 5) 改后快照 d1(963) ==="
& "$root\tools\py.ps1" "$root\tools\tests\snap.py" 洪氏2 67172818 963.1.1 1 --name=v97_d1
Write-Host "=== 6) 改后快照 d3(983) ==="
& "$root\tools\py.ps1" "$root\tools\tests\snap.py" 洪氏2 67172818 983.1.1 3 --name=v97_d3
Write-Host "=== DONE ==="
