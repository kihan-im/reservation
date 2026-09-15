@echo off
setlocal
REM Windows 시스템 기본 경로(System32) 강제 확보 (환경변수 PATH 누락 방지)
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0\;%PATH%"

REM 일반적인 사용자 Python 설치 경로 자동 탐색 및 PATH 보강
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PATH=%LocalAppData%\Programs\Python\Python312;%LocalAppData%\Programs\Python\Python312\Scripts;%PATH%"
if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PATH=%LocalAppData%\Programs\Python\Python311;%LocalAppData%\Programs\Python\Python311\Scripts;%PATH%"
if exist "%LocalAppData%\Programs\Python\Python310\python.exe" set "PATH=%LocalAppData%\Programs\Python\Python310;%LocalAppData%\Programs\Python\Python310\Scripts;%PATH%"
if exist "%ProgramFiles%\Python312\python.exe" set "PATH=%ProgramFiles%\Python312;%ProgramFiles%\Python312\Scripts;%PATH%"
if exist "%ProgramFiles%\Python311\python.exe" set "PATH=%ProgramFiles%\Python311;%ProgramFiles%\Python311\Scripts;%PATH%"
if exist "%ProgramFiles%\Python310\python.exe" set "PATH=%ProgramFiles%\Python310;%ProgramFiles%\Python310\Scripts;%PATH%"

if exist "%LocalAppData%\Programs\Python\Python313\python.exe" set "PATH=%LocalAppData%\Programs\Python\Python313;%PATH%"
chcp 65001 >nul
cd /d "%~dp0"
set "NO_PAUSE=0"
set "INSTALL_ONLY=0"
set "EXIT_CODE=1"
for %%A in (%*) do if /i "%%~A"=="--no-pause" set "NO_PAUSE=1"
for %%A in (%*) do if /i "%%~A"=="--install-only" set "INSTALL_ONLY=1"

if "%INSTALL_ONLY%"=="1" goto :INSTALL
if not exist "venv\Scripts\python.exe" goto :INSTALL
if not exist "venv\requirements.installed.txt" goto :INSTALL
fc /b requirements.txt venv\requirements.installed.txt >nul 2>&1
if errorlevel 1 goto :INSTALL
goto :READY

:INSTALL
if "%NO_PAUSE%"=="1" (
    echo [오류] 실행 환경 설치가 필요합니다. 수동으로 run_automation.bat --install-only 를 실행하세요.
    goto :END
)
if exist "venv\Scripts\python.exe" goto :PACKAGES
python -m venv venv
if errorlevel 1 goto :INSTALL_FAIL
:PACKAGES
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto :INSTALL_FAIL
venv\Scripts\python.exe -m pip check
if errorlevel 1 goto :INSTALL_FAIL
venv\Scripts\python.exe -m playwright install chromium
if errorlevel 1 goto :INSTALL_FAIL
copy /y requirements.txt venv\requirements.installed.txt >nul
if errorlevel 1 goto :INSTALL_FAIL

:READY
if "%INSTALL_ONLY%"=="1" (
    set "EXIT_CODE=0"
    echo [완료] 실행 환경 설치 완료. 예약은 실행하지 않았습니다.
    goto :END
)
if exist "config.json" goto :RUN
if "%NO_PAUSE%"=="1" (
    echo [오류] config.json이 없습니다. setup_account.bat으로 먼저 설정하세요.
    goto :END
)
venv\Scripts\python.exe src\setup_account.py
if errorlevel 1 goto :END
if not exist "config.json" goto :END

:RUN
venv\Scripts\python.exe main.py %*
set "EXIT_CODE=%errorlevel%"
goto :END

:INSTALL_FAIL
echo [오류] 실행 환경 설치 실패. 위 오류를 해결한 뒤 --install-only로 재시도하세요.

:END
echo [종료] 코드: %EXIT_CODE%
if "%NO_PAUSE%"=="0" pause
exit /b %EXIT_CODE%
