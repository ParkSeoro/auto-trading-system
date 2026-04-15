@echo off
REM 단위 테스트 실행
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] 설치되지 않았습니다. install.bat 을 먼저 실행하세요.
    pause
    exit /b 1
)

call ".venv\Scripts\python.exe" -m pytest -v
pause
