@echo off
REM ============================================================
REM  Launch the web dashboard (http://localhost:8787)
REM ============================================================
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] Not installed. Run install.bat first.
    pause
    exit /b 1
)

set HOST=%1
if "%HOST%"=="" set HOST=127.0.0.1
set PORT=%2
if "%PORT%"=="" set PORT=8787

echo.
echo ================================================================
echo   Crypto Trading Web Dashboard
echo   Open in browser:  http://%HOST%:%PORT%
echo   Press Ctrl+C to stop.
echo ================================================================
echo.

start "" "http://%HOST%:%PORT%"
call ".venv\Scripts\python.exe" -m scripts.run_web --host %HOST% --port %PORT%
pause
