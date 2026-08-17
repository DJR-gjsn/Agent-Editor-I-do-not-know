@echo off
chcp 65001 >nul
cd /d "%~dp0"

title Agent Editor Server

echo ============================================
echo   Agent Editor V0.1 - Server Launcher
echo ============================================
echo.

rem -- check port 5000 --
netstat -ano | findstr ":5000" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [OK] Server is already running on http://localhost:5000
    start "" "http://localhost:5000"
    echo.
    echo Press any key to close this window...
    pause >nul
    exit /b 0
)

echo [..] Starting server, browser will open in 2 seconds...
start /b cmd /c "timeout /t 2 /nobreak >nul & start "" http://localhost:5000"

python server.py

echo.
echo Server stopped. Press any key to close...
pause >nul