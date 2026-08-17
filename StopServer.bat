@echo off
chcp 65001 >nul
cd /d "%~dp0"

title Agent Editor - Stop Server

echo ============================================
echo   Agent Editor - Stop Server
echo ============================================
echo.

set "FOUND="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    set "FOUND=%%a"
    goto :kill
)

echo [..] No server found on port 5000.
echo.
pause
exit /b 0

:kill
echo [OK] Found process PID %FOUND% listening on port 5000
taskkill /F /PID %FOUND% >nul 2>&1
rem -- re-check port after kill --
netstat -ano | findstr ":5000" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [OK] Server stopped.
) else (
    echo [X] Could not stop PID %FOUND%.
    echo     Try closing the server window, or run this script as Administrator.
)
echo.
pause