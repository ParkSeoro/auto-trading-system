@echo off
REM ============================================================
REM  Crypto Auto-Trading System - Windows Installer
REM  대상 경로 예시: C:\Users\psr15\Desktop\crypto
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ================================================================
echo   Crypto Auto-Trading System - Installation
echo   설치 경로: %CD%
echo ================================================================
echo.

REM ---- 1. Python 확인 ---------------------------------------------
echo [1/5] Python 설치 확인 중...
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Python이 설치되어 있지 않습니다.
    echo.
    echo   1^) https://www.python.org/downloads/ 에서 Python 3.10 이상을 다운로드 후 설치하세요.
    echo   2^) 설치 시 반드시 "Add python.exe to PATH" 옵션을 체크하세요.
    echo   3^) 설치 후 이 창을 닫고 install.bat 을 다시 실행하세요.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PY_VER=%%i
echo     - Python !PY_VER! 발견.

REM ---- 2. 가상환경 생성 -------------------------------------------
echo.
echo [2/5] 가상환경(.venv) 생성...
if exist ".venv\Scripts\python.exe" (
    echo     - 기존 가상환경 사용.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] 가상환경 생성 실패.
        pause
        exit /b 1
    )
    echo     - .venv 생성 완료.
)

REM ---- 3. pip 업그레이드 & 의존성 설치 ----------------------------
echo.
echo [3/5] pip 업그레이드 및 라이브러리 설치 (수 분 소요)...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] 패키지 설치 실패. 인터넷 연결 및 방화벽을 확인하세요.
    pause
    exit /b 1
)

REM ---- 4. .env 파일 준비 ------------------------------------------
echo.
echo [4/5] .env 설정 파일 준비...
if exist ".env" (
    echo     - 기존 .env 유지.
) else (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo     - .env.example 을 복사해 .env 를 생성했습니다.
        echo     - 메모장 등으로 .env 를 열어 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 를 입력하세요.
    ) else (
        echo     - .env.example 없음. 수동 생성 필요.
    )
)

REM ---- 5. 빠른 자체 테스트 ----------------------------------------
echo.
echo [5/5] 설치 확인 테스트 실행...
call ".venv\Scripts\python.exe" -m pytest -q 2>nul
if errorlevel 1 (
    echo.
    echo [WARN] 일부 테스트가 실패했습니다. 의존성은 설치되었으나 동작 확인 필요.
) else (
    echo     - 전체 테스트 통과.
)

echo.
echo ================================================================
echo   설치 완료!
echo.
echo   다음 단계:
echo     1^) 메모장으로 .env 파일을 열어 업비트 API 키 입력 (라이브 거래 시만 필요)
echo     2^) start.bat 을 실행하여 메뉴에서 페이퍼 트레이딩 / 백테스트를 선택
echo.
echo   또는 개별 실행:
echo     - run_paper.bat     : 가상자본으로 안전한 모의 거래
echo     - run_backtest.bat  : 과거 데이터로 전략 백테스트
echo     - run_live.bat      : 실제 업비트 거래 (주의!)
echo     - run_tests.bat     : 단위 테스트 실행
echo ================================================================
echo.
pause
endlocal
