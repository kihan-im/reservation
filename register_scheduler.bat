@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_scheduler.ps1"
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" echo [오류] 스케줄러 등록 또는 검증 실패. 위 오류를 확인하세요.
pause
exit /b %EXIT_CODE%
