@echo off
REM ============================================================
REM  Crypto Auto-Trading System - Windows Installer
REM  Example path: C:\Users\psr15\Desktop\crypto
REM ============================================================

chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ================================================================
echo   Crypto Auto-Trading System - Installation
echo   Path: %CD%
echo ================================================================
echo.

REM ---- 1. Check Python --------------------------------------------
echo [1/5] Checking Python installation...
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Python is not installed.
    echo.
    echo   1^) Download Python 3.10+ from https://www.python.org/downloads/
    echo   2^) During install, CHECK the box "Add python.exe to PATH"
    echo   3^) Close this window and run install.bat again
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
echo     - Python !PY_VER! found.

REM ---- 2. Create venv ---------------------------------------------
echo.
echo [2/5] Creating virtual environment (.venv)...
if exist ".venv\Scripts\python.exe" (
    echo     - Existing venv reused.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create venv.
        pause
        exit /b 1
    )
    echo     - .venv created.
)

REM ---- 3. Upgrade pip and install deps ----------------------------
echo.
echo [3/5] Upgrading pip and installing dependencies...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Package install failed. Check internet/firewall.
    pause
    exit /b 1
)

REM ---- 4. Prepare .env --------------------------------------------
echo.
echo [4/5] Preparing .env config file...
if exist ".env" (
    echo     - Existing .env kept.
) else (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo     - Copied .env.example to .env
        echo     - Open .env in Notepad and set UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY
    ) else (
        echo     - No .env.example found. Create manually.
    )
)

REM ---- 5. Smoke test ----------------------------------------------
echo.
echo [5/5] Running test suite...
call ".venv\Scripts\python.exe" -m pytest -q 2>nul
if errorlevel 1 (
    echo.
    echo [WARN] Some tests failed. Dependencies installed but check output.
) else (
    echo     - All tests passed.
)

echo.
echo ================================================================
echo   Installation complete!
echo.
echo   Next steps:
echo     1^) (Live trading only^) Edit .env and set Upbit API keys
echo     2^) Double-click start.bat for an interactive menu
echo.
echo   Or run directly:
echo     run_paper.bat     - Paper (simulated) trading, safe
echo     run_backtest.bat  - Backtest strategies on history
echo     run_live.bat      - LIVE trading (real funds!)
echo     run_tests.bat     - Run unit tests
echo ================================================================
echo.
pause
endlocal
