@echo off
chcp 936 >nul
title CK3 记忆素材库 - 重建对照表
cd /d "%~dp0"
echo.
echo 正在扫描游戏与 Mod 目录, 重建全部对照表 (data\*.json)。
echo 建表期间请勿关闭窗口; 完成后本窗口会停留。
echo.
python pipeline.py build-tables
echo.
echo 说明: 只有游戏升级、或勾选/取消 Mod 之后才需要跑这一下。
echo       平时启动监控不再自动建表。
echo.
echo 程序已退出，按任意键关闭窗口。
pause >nul
