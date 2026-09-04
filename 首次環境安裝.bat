@echo off
chcp 65001 >nul
title 首次環境自動配置
cd /d "%~dp0"
echo ========================================================
echo   正在為正式筆電配置 Python 依賴環境...
echo ========================================================
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo ========================================================
echo   環境配置完成！現在可雙擊 [啟動監測系統.bat] 運行。
echo ========================================================
pause
