@echo off
REM ============================================================
REM  Crypto Auto-Trading System - Interactive Menu
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [!] 가상환경이 없습니다. 먼저 install.bat 을 실행하세요.
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
echo   [1] 페이퍼 트레이딩 시작 (가상자본, 안전)
echo   [2] 백테스트 실행 (과거 데이터)
echo   [3] 실거래 시작 (주의: 실제 자금 사용)
echo   [4] 단위 테스트 실행
echo   [5] .env 파일 열어 API 키 설정
echo   [0] 종료
echo.
set /p choice=  선택:

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
echo --- 페이퍼 트레이딩 설정 ---
set /p markets=  마켓 (예: KRW-BTC,KRW-ETH) [기본: KRW-BTC]:
if "!markets!"=="" set markets=KRW-BTC
set /p strategy=  전략 (volatility_breakout/rsi_mean_reversion/bollinger_breakout/grid/ensemble) [기본: ensemble]:
if "!strategy!"=="" set strategy=ensemble
set /p timeframe=  시간봉 (1m/5m/15m/30m/1h/4h/1d) [기본: 1d]:
if "!timeframe!"=="" set timeframe=1d
echo.
echo 실행: python -m scripts.run_bot --mode paper --markets !markets! --strategy !strategy! --timeframe !timeframe!
echo (Ctrl+C로 중단)
echo.
call ".venv\Scripts\python.exe" -m scripts.run_bot --mode paper --markets !markets! --strategy !strategy! --timeframe !timeframe!
pause
goto menu

:backtest
cls
echo.
echo --- 백테스트 설정 ---
set /p market=  마켓 [기본: KRW-BTC]:
if "!market!"=="" set market=KRW-BTC
set /p strategy=  전략 [기본: volatility_breakout]:
if "!strategy!"=="" set strategy=volatility_breakout
set /p count=  가져올 캔들 수 [기본: 500]:
if "!count!"=="" set count=500
set /p capital=  시작 자본 KRW [기본: 1000000]:
if "!capital!"=="" set capital=1000000
echo.
call ".venv\Scripts\python.exe" -m scripts.run_backtest --market !market! --strategy !strategy! --count !count! --capital !capital!
pause
goto menu

:live
cls
echo.
echo ================================================================
echo   [경고] 실거래 모드 - 실제 업비트 계정의 자금이 사용됩니다.
echo ================================================================
echo.
if not exist ".env" (
    echo [ERROR] .env 파일이 없습니다. 먼저 API 키를 설정하세요 (메뉴 5번^).
    pause
    goto menu
)
set /p confirm=  정말 실거래로 진입하시겠습니까? (YES 입력 시 진행):
if not "!confirm!"=="YES" (
    echo 취소됨.
    pause
    goto menu
)
set /p markets=  마켓 [기본: KRW-BTC]:
if "!markets!"=="" set markets=KRW-BTC
set /p strategy=  전략 [기본: volatility_breakout]:
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
echo 종료합니다.
endlocal
