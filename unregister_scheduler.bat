@echo off
REM Windows 시스템 기본 경로(System32) 강제 확보 (환경변수 PATH 누락 방지)
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0\;%PATH%"

chcp 65001 > nul
title COSMAX 작업 스케줄러 등록 해제

echo =======================================================
echo COSMAX eBiz 작업 스케줄러 등록 해제
echo =======================================================
echo.

REM 관리자 권한 확인
"%SystemRoot%\System32\net.exe" session >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] 관리자 권한이 필요합니다.
    echo 이 배치 파일을 마우스 우클릭한 후 [관리자 권한으로 실행]을 선택해 주세요.
    echo.
    pause
    exit /b 1
)

set TASK_NAME=CosmaxAutoReservation

echo [진행] 등록된 스케줄러(%TASK_NAME%) 삭제 중...
"%SystemRoot%\System32\schtasks.exe" /delete /tn "%TASK_NAME%" /f >nul 2>&1

if %errorlevel% equ 0 (
    echo.
    echo [성공] %TASK_NAME% 작업 스케줄러가 성공적으로 삭제되었습니다.
    echo.
) else (
    echo.
    echo [안내] 등록된 %TASK_NAME% 작업이 없거나 이미 삭제되었습니다.
    echo.
)

pause
