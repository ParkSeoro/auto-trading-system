@echo off
REM ============================================================
REM  Offline AI evolution (genetic strategy tuning)
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

set MARKET=%1
if "%MARKET%"=="" set MARKET=KRW-BTC
set COUNT=%2
if "%COUNT%"=="" set COUNT=800
set GENERATIONS=%3
if "%GENERATIONS%"=="" set GENERATIONS=8

echo.
echo === AI strategy evolution ===
echo   Market       : %MARKET%
echo   Bars         : %COUNT%
echo   Generations  : %GENERATIONS%
echo.

call ".venv\Scripts\python.exe" -m scripts.run_evolve --market %MARKET% --count %COUNT% --generations %GENERATIONS%
pause
