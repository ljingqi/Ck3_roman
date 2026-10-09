@echo off
chcp 936 >nul
title CK3 记忆素材库封档总评
cd /d "%~dp0"
python pipeline.py epilogue
echo.
echo 程序已退出，按任意键关闭窗口。
pause >nul
