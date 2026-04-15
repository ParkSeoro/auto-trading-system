@echo off
REM ============================================================
REM  실거래 모드 - 주의: 실제 자금 사용
REM ============================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] 설치되지 않았습니다. install.bat 을 먼저 실행하세요.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [ERROR] .env 파일이 없습니다. API 키 설정 후 다시 실행하세요.
    pause
    exit /b 1
)

echo.
echo ================================================================
echo   [경고] 실거래 모드
echo   업비트 실제 계정의 KRW/암호화폐로 주문이 전송됩니다.
echo ================================================================
echo.
set /p CONFIRM=  정말 진행하시겠습니까? (YES 입력 시 실행):
if not "%CONFIRM%"=="YES" (
    echo 취소되었습니다.
    pause
    exit /b 0
)

set MARKETS=%1
if "%MARKETS%"=="" set MARKETS=KRW-BTC

set STRATEGY=%2
if "%STRATEGY%"=="" set STRATEGY=volatility_breakout

echo.
echo === LIVE 트레이딩 시작 === (Ctrl+C 로 안전 종료)
echo   마켓 : %MARKETS%
echo   전략 : %STRATEGY%
echo.

call ".venv\Scripts\python.exe" -m scripts.run_bot --mode live --markets %MARKETS% --strategy %STRATEGY%
pause
