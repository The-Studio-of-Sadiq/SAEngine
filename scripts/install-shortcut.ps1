# Creates Desktop and Start Menu shortcuts that start the SAEngine development build
# through run-saengine.ps1 (no console window). Re-run after moving the repository.
$ErrorActionPreference = 'Stop'

$saengineRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $PSScriptRoot 'run-saengine.ps1'
$icon = Join-Path $saengineRoot 'workbench\resources\win32\code.ico'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

$targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'SAEngine.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'SAEngine.lnk')
)

$shell = New-Object -ComObject WScript.Shell
foreach ($path in $targets) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $powershell
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
    $shortcut.WorkingDirectory = $saengineRoot
    $shortcut.IconLocation = "$icon,0"
    $shortcut.Description = 'SAEngine structural engineering workbench'
    $shortcut.WindowStyle = 7  # minimized, so the launcher's console never flashes
    $shortcut.Save()
    Write-Host "Created $path"
}
