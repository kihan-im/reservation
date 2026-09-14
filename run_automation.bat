@echo off
REM Windows 시스템 기본 경로(System32) 강제 확보 (환경변수 PATH 누락 방지)
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0\;%PATH%"

REM 일반적인 사용자 Python 설치 경로 자동 탐색 및 PATH 보강
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PATH=%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%PATH%"
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PATH=%LocalAppData%\Programs\Python\Python311;%LocalAppData%\Programs\Python\Python311\Scripts;%PATH%"
if exist "%LocalAppData%\Programs\Python\Python310\python.exe" set "PATH=%LocalAppData%\Programs\Python\Python310;%LocalAppData%\Programs\Python\Python310\Scripts;%PATH%"
if exist "%ProgramFiles%\Python312\python.exe" set "PATH=%ProgramFiles%\Python312;%ProgramFiles%\Python312\Scripts;%PATH%"
if exist "%ProgramFiles%\Python311\python.exe" set "PATH=%ProgramFiles%\Python311;%ProgramFiles%\Python311\Scripts;%PATH%"
if exist "%ProgramFiles%\Python310\python.exe" set "PATH=%ProgramFiles%\Python310;%ProgramFiles%\Python310\Scripts;%PATH%"

chcp 65001 > nul
title COSMAX eBiz Auto Login & Session Keeper

echo ===================================================
echo COSMAX eBiz 자동 로그인 및 10시 입고예약 프로그램
echo ===================================================
echo.

cd /d "%~dp0"

REM 1. 가상환경 venv 활성화 스크립트 존재 확인
if exist "venv\Scripts\activate.bat" goto :ACTIVATE_VENV

REM 가상환경이 없으면 새로 생성
echo [INFO] Python 가상환경(venv)을 최초 1회 생성합니다...
python --version >nul 2>&1
if %errorlevel% neq 0 goto :NO_PYTHON

python -m venv venv
if %errorlevel% neq 0 goto :VENV_CREATE_FAIL

echo [INFO] 가상환경 활성화 및 필수 패키지 설치 중...
call venv\Scripts\activate.bat
pip install -r requirements.txt
playwright install chromium
goto :CHECK_CONFIG

:ACTIVATE_VENV
call venv\Scripts\activate.bat
goto :CHECK_CONFIG

:NO_PYTHON
echo.
echo ===================================================
echo [오류] Python이 시스템에 설치되어 있지 않거나 PATH에 없습니다.
echo https://www.python.org 에서 파이썬 설치 시
echo [Add python.exe to PATH] 옵션을 반드시 체크해 주세요.
echo ===================================================
echo.
pause
exit /b 1

:VENV_CREATE_FAIL
echo.
echo ===================================================
echo [오류] Python 가상환경(venv) 생성에 실패하였습니다.
echo Python 설치 상태 및 권한을 확인해 주세요.
echo ===================================================
echo.
pause
exit /b 1

:CHECK_CONFIG
if exist "config.json" goto :RUN_SCRIPT

echo.
echo ===================================================
echo [안내] config.json 설정 파일이 없습니다.
echo 최초 1회 계정 설정 마법사를 실행합니다.
echo ===================================================
echo.
python src\setup_account.py

if exist "config.json" goto :RUN_SCRIPT

echo.
echo [오류] 계정 정보가 설정되지 않아 프로그램을 종료합니다.
echo.
pause
exit /b 1

:RUN_SCRIPT
echo.
echo ===================================================
echo [INFO] COSMAX 입고예약 자동화 스크립트를 실행합니다.
echo ===================================================
echo.

python main.py %*
set EXIT_CODE=%errorlevel%

echo.
echo ===================================================
echo [INFO] 실행이 완료되었습니다. (종료 코드: %EXIT_CODE%)
echo ===================================================
echo.

REM 스케줄러 무인 실행 인자(--no-pause) 포함 여부 안전 검사
echo "%*" | findstr /i "\--no-pause" >nul
if %errorlevel% equ 0 goto :SCHEDULER_EXIT

:MANUAL_EXIT
echo [안내] 아무 키나 누르면 창이 닫힙니다...
pause > nul
exit /b %EXIT_CODE%

:SCHEDULER_EXIT
echo [안내] 60초 후 창이 자동으로 닫힙니다... [아무 키나 누르면 즉시 닫힘]
timeout /t 60 > nul
exit /b %EXIT_CODE%
