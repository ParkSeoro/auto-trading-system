@echo off
REM Paper (모의) 트레이딩 - 가상자본, 안전
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] 설치되지 않았습니다. install.bat 을 먼저 실행하세요.
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
echo === 페이퍼 트레이딩 시작 ===
echo   마켓    : %MARKETS%
echo   전략    : %STRATEGY%
echo   타임프레임: %TIMEFRAME%
echo   (Ctrl+C 로 중단)
echo.

call ".venv\Scripts\python.exe" -m scripts.run_bot --mode paper --markets %MARKETS% --strategy %STRATEGY% --timeframe %TIMEFRAME%
pause
