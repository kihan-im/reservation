@echo off
setlocal
REM Keep Windows system tools available even when PATH is incomplete.
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0\;%PATH%"

REM Add common Python installation directories to PATH.
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
set "SETUP_ACCOUNT=0"
set "RUN_ARGS=%*"
for %%A in (%*) do if /i "%%~A"=="--no-pause" set "NO_PAUSE=1"
for %%A in (%*) do if /i "%%~A"=="--install-only" set "INSTALL_ONLY=1"

if "%~1"=="" goto :MENU
if /i "%~1"=="--setup-account" set "SETUP_ACCOUNT=1"
if /i "%~1"=="--register-scheduler" goto :REGISTER
if /i "%~1"=="--unregister-scheduler" goto :UNREGISTER
goto :CHECK_ENV

:MENU
echo ===================================================
echo COSMAX eBiz - Select a task
echo ===================================================
echo 1. Install / repair environment
echo 2. Set up account
echo 3. Check configuration
echo 4. Test with browser - NO SAVE
echo 5. Run reservation - maximized window, SAVES DATA
echo 6. Register / update weekday schedule
echo 7. Remove schedule
echo 0. Exit
choice /c 12345670 /n /m "Select a number: "
if errorlevel 255 goto :END
if errorlevel 8 exit /b 0
if errorlevel 7 goto :UNREGISTER
if errorlevel 6 goto :REGISTER
if errorlevel 5 (
    set "RUN_ARGS=--headful"
    goto :CHECK_ENV
)
if errorlevel 4 (
    set "RUN_ARGS=--headful --force --dry-run"
    goto :CHECK_ENV
)
if errorlevel 3 (
    set "RUN_ARGS=--check-config"
    goto :CHECK_ENV
)
if errorlevel 2 (
    set "SETUP_ACCOUNT=1"
    goto :CHECK_ENV
)
if errorlevel 1 (
    set "INSTALL_ONLY=1"
    goto :INSTALL
)
goto :END

:REGISTER
set "SCHEDULER_ACTION=Register"
set "SCHEDULER_HEADFUL="
for %%A in (%*) do if /i "%%~A"=="--headful" set "SCHEDULER_HEADFUL=-Headful"
goto :SCHEDULER
:UNREGISTER
set "SCHEDULER_ACTION=Unregister"
:SCHEDULER
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_scheduler.ps1" -Action %SCHEDULER_ACTION% %SCHEDULER_HEADFUL%
set "EXIT_CODE=%errorlevel%"
goto :END

:CHECK_ENV
if "%INSTALL_ONLY%"=="1" goto :INSTALL
if not exist "venv\Scripts\python.exe" goto :INSTALL
if not exist "venv\requirements.installed.txt" goto :INSTALL
fc /b requirements.txt venv\requirements.installed.txt >nul 2>&1
if errorlevel 1 goto :INSTALL
goto :READY

:INSTALL
if "%NO_PAUSE%"=="1" (
    echo [ERROR] Setup required. Run run_automation.bat --install-only manually.
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
    echo [OK] Environment installed. No reservation was submitted.
    goto :END
)
if "%SETUP_ACCOUNT%"=="1" goto :SETUP_ACCOUNT
if exist "config.json" goto :RUN
if "%NO_PAUSE%"=="1" (
    echo [ERROR] Missing config.json. Run run_automation.bat --setup-account first.
    goto :END
)
venv\Scripts\python.exe src\setup_account.py
if errorlevel 1 goto :END
if not exist "config.json" goto :END

:RUN
venv\Scripts\python.exe main.py %RUN_ARGS%
set "EXIT_CODE=%errorlevel%"
goto :END

:SETUP_ACCOUNT
if "%NO_PAUSE%"=="1" (
    echo [ERROR] Account setup requires input. Run without --no-pause.
    goto :END
)
venv\Scripts\python.exe src\setup_account.py
set "EXIT_CODE=%errorlevel%"
goto :END

:INSTALL_FAIL
echo [ERROR] Installation failed. Fix the error above and retry with --install-only.

:END
echo [EXIT] Code: %EXIT_CODE%
if "%NO_PAUSE%"=="0" pause
exit /b %EXIT_CODE%
