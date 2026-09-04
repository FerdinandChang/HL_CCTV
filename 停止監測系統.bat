@echo off
chcp 65001 >nul
title 停止路污監測系統
cd /d "%~dp0"
echo 正在停止花蓮營建路污監測系統服務 (Port 8088)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8088') do (
    taskkill /f /pid %%a >nul 2>&1
)
taskkill /f /im ffmpeg.exe >nul 2>&1
echo 系統已完全停止！
timeout /t 2 >nul
