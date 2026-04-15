@echo off
REM ============================================================
REM  LIVE trading - real money!
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

if not exist ".env" (
    echo [ERROR] No .env file. Set API keys first.
    pause
    exit /b 1
)

echo.
echo ================================================================
echo   [WARNING] LIVE mode
echo   Real orders will be placed on your exchange account.
echo   Current exchange is set by EXCHANGE in .env
echo     EXCHANGE=bithumb  (default) uses BITHUMB_API_KEY / BITHUMB_SECRET_KEY
echo     EXCHANGE=upbit             uses UPBIT_ACCESS_KEY  / UPBIT_SECRET_KEY
echo ================================================================
echo.
set /p CONFIRM=  Are you sure? (type YES to proceed):
if not "%CONFIRM%"=="YES" (
    echo Cancelled.
    pause
    exit /b 0
)

set MARKETS=%1
if "%MARKETS%"=="" set MARKETS=KRW-BTC

set STRATEGY=%2
if "%STRATEGY%"=="" set STRATEGY=volatility_breakout

echo.
echo === LIVE TRADING === (Press Ctrl+C for safe shutdown)
echo   Markets  : %MARKETS%
echo   Strategy : %STRATEGY%
echo.

call ".venv\Scripts\python.exe" -m scripts.run_bot --mode live --markets %MARKETS% --strategy %STRATEGY%
pause
