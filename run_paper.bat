@echo off
REM Paper (simulated) trading - virtual capital, safe
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] Not installed. Run install.bat first.
    pause
    exit /b 1
)

set MARKETS=%1
if "%MARKETS%"=="" set MARKETS=KRW-BTC

set STRATEGY=%2
if "%STRATEGY%"=="" set STRATEGY=ensemble

set TIMEFRAME=%3
if "%TIMEFRAME%"=="" set TIMEFRAME=1d

echo.
echo === PAPER TRADING ===
echo   Markets  : %MARKETS%
echo   Strategy : %STRATEGY%
echo   Timeframe: %TIMEFRAME%
echo   (Press Ctrl+C to stop)
echo.

call ".venv\Scripts\python.exe" -m scripts.run_bot --mode paper --markets %MARKETS% --strategy %STRATEGY% --timeframe %TIMEFRAME%
pause
