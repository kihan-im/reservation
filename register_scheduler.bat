@echo off
chcp 65001 > nul
title COSMAX 작업 스케줄러 등록 마법사

echo =======================================================
echo COSMAX eBiz 평일 오전 09:50 작업 스케줄러 등록
echo =======================================================
echo.

REM 1. 관리자 권한 확인
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [오류] 관리자 권한이 필요합니다.
    echo 이 배치 파일을 마우스 우클릭한 후 [관리자 권한으로 실행]을 선택해 주세요.
    echo.
    pause
    exit /b 1
)

cd /d "%~dp0"
set SCRIPT_PATH=%~dp0run_automation.bat
set TASK_NAME=CosmaxAutoReservation

echo [1/2] 기존 동일 스케줄러 작업 확인 및 정리...
schtasks /query /tn "%TASK_NAME%" >nul 2>&1
if %errorlevel% equ 0 (
    echo 기존에 등록된 %TASK_NAME% 작업을 갱신합니다.
    schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
)

echo [2/2] 매주 평일(월~금) 오전 09:50 자동 실행 작업 등록 중...
schtasks /create /tn "%TASK_NAME%" /tr "\"%SCRIPT_PATH%\" --headless --no-pause" /sc weekly /d MON,TUE,WED,THU,FRI /st 09:50 /ru "%USERNAME%" /it /f

if %errorlevel% equ 0 (
    echo [설정] 대화형 콘솔 표시 및 무인 자동 복구 고급 설정 적용 중...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive; $settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; Set-ScheduledTask -TaskName '%TASK_NAME%' -Principal $principal -Settings $settings -ErrorAction SilentlyContinue" >nul 2>&1

    echo.
    echo =======================================================
    echo [성공] Windows 작업 스케줄러 등록이 완료되었습니다!
    echo =======================================================
    echo.
    echo * 등록된 작업 이름: %TASK_NAME%
    echo * 실행 주기: 매주 월, 화, 수, 목, 금 (주말 제외)
    echo * 실행 시간: 오전 09:50:00 (10:00 예약 오픈 전 자동 대기)
    echo * 실행 모드: 브라우저는 백그라운드, 콘솔 창은 실시간 화면 표시
    echo * 무인 자동 복구: 실행 실패 시 1분 간격 최대 3회 자동 다시 시작 활성화
    echo * 절전 해제 옵션: 컴퓨터를 깨워 이 작업 실행 활성화
    echo * 놓친 작업 보상: 09:50 이후 PC 부팅 시 즉시 자동 실행 (StartWhenAvailable) 활성화
    echo * 주말 및 법정 공휴일(설날, 추석 등)은 프로그램이 스스로 감지하여 자동 스킵합니다.
    echo.
) else (
    echo.
    echo [오류] 스케줄러 등록에 실패하였습니다. 권한이나 설정을 확인해 주세요.
    echo.
)

pause
