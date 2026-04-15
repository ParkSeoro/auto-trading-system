@echo off
REM 백테스트 실행
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] 설치되지 않았습니다. install.bat 을 먼저 실행하세요.
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
echo === 백테스트 실행 ===
echo   마켓    : %MARKET%
echo   전략    : %STRATEGY%
echo   캔들 수 : %COUNT%
echo   자본    : %CAPITAL% KRW
echo.

call ".venv\Scripts\python.exe" -m scripts.run_backtest --market %MARKET% --strategy %STRATEGY% --count %COUNT% --capital %CAPITAL%
pause
