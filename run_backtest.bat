@echo off
REM Run a backtest
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] Not installed. Run install.bat first.
    pause
    exit /b 1
)

set MARKET=%1
if "%MARKET%"=="" set MARKET=KRW-BTC

set STRATEGY=%2
if "%STRATEGY%"=="" set STRATEGY=volatility_breakout

set COUNT=%3
if "%COUNT%"=="" set COUNT=500

set CAPITAL=%4
if "%CAPITAL%"=="" set CAPITAL=1000000

echo.
echo === BACKTEST ===
echo   Market   : %MARKET%
echo   Strategy : %STRATEGY%
echo   Candles  : %COUNT%
echo   Capital  : %CAPITAL% KRW
echo.

call ".venv\Scripts\python.exe" -m scripts.run_backtest --market %MARKET% --strategy %STRATEGY% --count %COUNT% --capital %CAPITAL%
pause
