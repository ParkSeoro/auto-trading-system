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

set PY=".venv\Scripts\python.exe"

REM --- Ensure web deps are present (auto-install if missing) ---
%PY% -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [INFO] Web dependencies missing. Installing fastapi / uvicorn ...
    echo.
    call %PY% -m pip install --upgrade pip >nul
    call %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERROR] Install failed. Check your internet connection and retry.
        pause
        exit /b 1
    )
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
call %PY% -m scripts.run_web --host %HOST% --port %PORT%
pause
