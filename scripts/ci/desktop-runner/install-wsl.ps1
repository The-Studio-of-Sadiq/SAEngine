# Step 1 on the desktop (Windows 10/11, PowerShell as Administrator): WSL2 with Ubuntu 24.04 for
# SAEngine's self-hosted CI runner, and a logon task that keeps WSL running so the runner stays
# online. Restart Windows when it asks, then open "Ubuntu 24.04" once to create the Linux user.
# Details: docs/ci-desktop-runner.md
$ErrorActionPreference = 'Stop'
$distro = 'Ubuntu-24.04'

if (-not (wsl.exe -l -q 2>$null | Where-Object { ($_ -replace "`0", '').Trim() -eq $distro })) {
	wsl.exe --install -d $distro
	Write-Host "WSL and $distro are installing. Restart Windows if asked, open '$distro' from the Start menu once to create your Linux user, then run this script again."
	exit 0
}
wsl.exe --set-default-version 2 | Out-Null

# WSL stops its VM when no Windows process uses it; this task keeps one process alive from logon,
# so the runner services inside keep running.
$action = New-ScheduledTaskAction -Execute 'wsl.exe' -Argument "-d $distro -- sleep infinity"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'SAEngine WSL keep-alive' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName 'SAEngine WSL keep-alive'
Write-Host "WSL ($distro) is ready and kept alive at logon. Next: run setup-runner.sh inside Ubuntu (docs/ci-desktop-runner.md)."
