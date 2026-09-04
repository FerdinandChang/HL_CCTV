@echo off
chcp 65001 >nul
title 花蓮營建路污辨識系統 - 現場邊緣監控節點
cd /d "%~dp0"

echo ========================================================
echo   花蓮營建路污辨識系統 (HL_CCTV) - 現場監控節點啟動中
echo ========================================================

:: 1. 檢查並清理殘留 Port 8088 進程
echo [1/3] 正在檢查服務連接埠 (Port 8088)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8088') do (
    taskkill /f /pid %%a >nul 2>&1
)

:: 2. 尋找可用之 Python 直譯器 (優先支援獨立便攜 runtime，次選系統 Python)
echo [2/3] 正在載入 AI 模型與影像分析服務...
if exist "runtime\python.exe" (
    set "PY_EXEC=runtime\python.exe"
) else (
    set "PY_EXEC=python"
)

:: 啟動 Uvicorn 後端 (非阻塞啟動)
start "HL_CCTV_Backend" /b %PY_EXEC% -m uvicorn backend.main:app --host 0.0.0.0 --port 8088

:: 等待服務完全就緒
timeout /t 3 /nobreak >nul

:: 3. 呼叫瀏覽器以原生 App 模式啟動全螢幕儀表板
echo [3/3] 正在開啟監控儀表板...
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --app=http://localhost:8088
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --app=http://localhost:8088
) else if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app=http://localhost:8088
) else if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files\Microsoft\Edge\Application\msedge.exe" --app=http://localhost:8088
) else (
    start http://localhost:8088
)

echo.
echo ========================================================
echo   系統已成功啟動！
echo   - 儀表板網址: http://localhost:8088
echo   - 結束請關閉此視窗或雙擊 [停止監測系統.bat]
echo ========================================================
echo.
pause
