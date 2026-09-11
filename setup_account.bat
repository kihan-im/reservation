@echo off
chcp 65001 > nul
title COSMAX eBiz 계정 설정 마법사

cd /d "%~dp0"

echo ===================================================
echo COSMAX eBiz 계정 및 환경설정 마법사
echo ===================================================
echo.

REM 1. 파이썬 실행 바이너리 확인 (가상환경 우선, 없으면 시스템 파이썬)
if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=venv\Scripts\python.exe"
) else (
    set "PYTHON_CMD=python"
)

%PYTHON_CMD% --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] Python이 설치되어 있지 않거나 환경변수 PATH에 등록되어 있지 않습니다.
    echo run_automation.bat 을 먼저 1회 실행하거나 Python을 설치해 주세요.
    echo.
    pause
    exit /b 1
)

REM 2. 마법사 스크립트 실행
%PYTHON_CMD% src\setup_account.py

echo.
echo [안내] 아무 키나 누르면 창이 닫힙니다...
pause > nul
