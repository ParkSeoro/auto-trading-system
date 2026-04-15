@echo off
REM ============================================================
REM  Crypto Auto-Trading System - Interactive Menu
REM ============================================================

chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [!] Virtual env missing. Run install.bat first.
    echo.
    pause
    exit /b 1
)

:menu
cls
echo.
echo ================================================================
echo   Crypto Auto-Trading System
echo ================================================================
echo.
echo   [1] Paper trading (virtual capital, safe)
echo   [2] Backtest (historical data)
echo   [3] LIVE trading (real money!)
echo   [4] Run unit tests
echo   [5] Edit .env (API keys)
echo   [0] Exit
echo.
set /p choice=  Select:

if "%choice%"=="1" goto paper
if "%choice%"=="2" goto backtest
if "%choice%"=="3" goto live
if "%choice%"=="4" goto tests
if "%choice%"=="5" goto editenv
if "%choice%"=="0" goto end
goto menu

:paper
cls
echo.
echo --- Paper trading setup ---
set /p markets=  Markets (e.g. KRW-BTC,KRW-ETH) [default: KRW-BTC]:
if "!markets!"=="" set markets=KRW-BTC
set /p strategy=  Strategy (volatility_breakout/rsi_mean_reversion/bollinger_breakout/grid/ensemble) [default: ensemble]:
if "!strategy!"=="" set strategy=ensemble
set /p timeframe=  Timeframe (1m/5m/15m/30m/1h/4h/1d) [default: 1d]:
if "!timeframe!"=="" set timeframe=1d
echo.
echo Running: python -m scripts.run_bot --mode paper --markets !markets! --strategy !strategy! --timeframe !timeframe!
echo (Press Ctrl+C to stop)
echo.
call ".venv\Scripts\python.exe" -m scripts.run_bot --mode paper --markets !markets! --strategy !strategy! --timeframe !timeframe!
pause
goto menu

:backtest
cls
echo.
echo --- Backtest setup ---
set /p market=  Market [default: KRW-BTC]:
if "!market!"=="" set market=KRW-BTC
set /p strategy=  Strategy [default: volatility_breakout]:
if "!strategy!"=="" set strategy=volatility_breakout
set /p count=  Number of candles [default: 500]:
if "!count!"=="" set count=500
set /p capital=  Starting capital KRW [default: 1000000]:
if "!capital!"=="" set capital=1000000
echo.
call ".venv\Scripts\python.exe" -m scripts.run_backtest --market !market! --strategy !strategy! --count !count! --capital !capital!
pause
goto menu

:live
cls
echo.
echo ================================================================
echo   [WARNING] LIVE mode - real Upbit account funds will be used.
echo ================================================================
echo.
if not exist ".env" (
    echo [ERROR] No .env file. Set API keys first (menu option 5^).
    pause
    goto menu
)
set /p confirm=  Are you sure? (type YES to proceed):
if not "!confirm!"=="YES" (
    echo Cancelled.
    pause
    goto menu
)
set /p markets=  Markets [default: KRW-BTC]:
if "!markets!"=="" set markets=KRW-BTC
set /p strategy=  Strategy [default: volatility_breakout]:
if "!strategy!"=="" set strategy=volatility_breakout
echo.
call ".venv\Scripts\python.exe" -m scripts.run_bot --mode live --markets !markets! --strategy !strategy!
pause
goto menu

:tests
cls
echo.
call ".venv\Scripts\python.exe" -m pytest -v
pause
goto menu

:editenv
if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
    )
)
notepad ".env"
goto menu

:end
echo.
echo Bye.
endlocal
