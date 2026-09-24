@echo off
REM ASCII-only launcher: avoids PowerShell 5.1 mangling non-BOM UTF-8 scripts.
REM Self-elevates once (one UAC prompt), then runs the fix script.
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix_bat_label.ps1"
