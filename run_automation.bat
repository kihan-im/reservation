@echo off
REM Windows 시스템 기본 경로(System32) 강제 확보 (환경변수 PATH 누락 방지)
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0\;%PATH%"

chcp 65001 > nul
title COSMAX eBiz Auto Login & Session Keeper

echo ===================================================
echo COSMAX eBiz 자동 로그인 및 10시 입고예약 프로그램
echo ===================================================
echo.

cd /d "%~dp0"

REM 1. 가상환경(venv) 존재 여부 검사
if not exist "venv" (
    echo [INFO] Python 가상환경(venv)을 최초 1회 생성합니다...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Python이 설치되어 있지 않거나 PATH에 등록되어 있지 않습니다.
        pause
        exit /b 1
    )
    echo [INFO] 가상환경 활성화 및 필수 패키지 설치 중...
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
    playwright install chromium
) else (
    call venv\Scripts\activate.bat
)

REM 2. 설정 파일(config.json) 존재 여부 검사
if not exist "config.json" (
    echo.
    echo ===================================================
    echo [안내] config.json 파일이 없습니다.
    echo 최초 1회 계정(아이디/비밀번호) 설정 마법사를 실행합니다.
    echo ===================================================
    python src\setup_account.py
    if not exist "config.json" (
        echo [오류] 계정 정보가 설정되지 않아 프로그램을 종료합니다.
        pause
        exit /b 1
    )
)

echo.
echo ===================================================
echo [INFO] COSMAX 입고예약 자동화 스크립트를 실행합니다.
echo ===================================================

REM 3. 스크립트 실행 (전달된 모든 인자 전달)
python main.py %*

set EXIT_CODE=%errorlevel%

echo.
echo ===================================================
echo [INFO] 실행이 완료되었습니다. (종료 코드: %EXIT_CODE%)
echo ===================================================

REM 3. 인자에 --no-pause 가 포함되어 있거나 비대화형 스케줄러 실행 시 pause 생략
set NO_PAUSE=0
for %%x in (%*) do (
    if "%%~x"=="--no-pause" set NO_PAUSE=1
)

if "%NO_PAUSE%"=="0" (
    echo [안내] 아무 키나 누르면 창이 닫힙니다...
    pause > nul
) else (
    echo [안내] 60초 후 창이 자동으로 닫힙니다... [아무 키나 누르면 즉시 닫힘]
    timeout /t 60 > nul
)
