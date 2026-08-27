@echo off
rem 新档监控: 只处理本程序启动后保存的新存档
cd /d %~dp0
python pipeline.py watch
pause
