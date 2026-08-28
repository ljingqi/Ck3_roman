@echo off
chcp 936 >nul
title CK3 记忆素材库监控（新档）
cd /d "%~dp0"
python pipeline.py watch
echo.
echo 程序已退出，按任意键关闭窗口。
pause >nul