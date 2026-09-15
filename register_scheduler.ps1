param (
    [ValidateSet('Register', 'Unregister')]
    [string]$Action = 'Register'
)

$ErrorActionPreference = 'Stop'
try {
    if ($Action -eq 'Unregister') {
        # Enumerate tasks so an absent task is distinct from permission/service errors.
        $task = Get-ScheduledTask | Where-Object { $_.TaskPath -eq '\' -and $_.TaskName -eq 'CosmaxAutoReservation' }
        if ($task) {
            Unregister-ScheduledTask -TaskName 'CosmaxAutoReservation' -TaskPath '\' -Confirm:$false
            Write-Host '[OK] CosmaxAutoReservation removed.'
        } else {
            Write-Host '[OK] CosmaxAutoReservation is not registered.'
        }
        exit 0
    }
    $python = Join-Path $PSScriptRoot 'venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { throw 'Run run_automation.bat --install-only first.' }
    if (-not (Test-Path (Join-Path $PSScriptRoot 'config.json'))) { throw 'config.json is missing.' }
    $installed = Join-Path $PSScriptRoot 'venv\requirements.installed.txt'
    if (-not (Test-Path $installed)) { throw 'Run run_automation.bat --install-only first.' }
    if ((Get-FileHash $installed).Hash -ne (Get-FileHash (Join-Path $PSScriptRoot 'requirements.txt')).Hash) {
        throw 'Dependencies changed. Run run_automation.bat --install-only first.'
    }
    & $python (Join-Path $PSScriptRoot 'main.py') --check-config
    if ($LASTEXITCODE -ne 0) { throw 'Configuration check failed.' }
    $script = Join-Path $PSScriptRoot 'run_automation.bat'
    $arguments = '/d /c ""' + $script + '" --headless --no-pause"'
    $action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument $arguments -WorkingDirectory $PSScriptRoot
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '09:50'
    $principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    # Avoid delayed or repeated submissions after a missed run. Python retries preparation before target time.
    $settings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask -TaskName 'CosmaxAutoReservation' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    $task = Get-ScheduledTask -TaskName 'CosmaxAutoReservation'
    if ($task.Actions.Arguments -ne $arguments) { throw 'Registered action does not match.' }
    Write-Host '[OK] CosmaxAutoReservation: weekdays 09:50. Windows login and Korea time zone required.'
    exit 0
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
