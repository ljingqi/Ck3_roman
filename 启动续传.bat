@echo off
rem 旧档续传: 补录当前战役新档后进入监控
cd /d %~dp0
python pipeline.py continue
pause
