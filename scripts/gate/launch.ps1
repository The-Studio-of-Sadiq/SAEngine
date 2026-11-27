# Launches a SAEngine dev window from this checkout for the release-gate walkthrough (#292),
# with its own profile and a CDP port, so it can be driven by scripts/gate/cdp.js only
# (never the real mouse or keyboard). See docs/perf/release-gates.md.
#
#   powershell -File scripts/gate/launch.ps1 [-GateDir <folder>] [-Port 9347] [-Python <python.exe>]
param(
	[string]$GateDir = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'saengine-walk-gate'),
	[int]$Port = 9347,
	[string]$Python = ''
)
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workbench = Join-Path $repo 'workbench'
$userData = Join-Path $GateDir 'ud'
$settings = Join-Path $userData 'User\settings.json'
if (-not (Test-Path $settings)) {
	New-Item -ItemType Directory -Force (Split-Path $settings) | Out-Null
	if (-not $Python) { $Python = Join-Path $repo '.venv\Scripts\python.exe' }
	# Custom dialogs and the simple file picker: native OS dialogs are invisible to CDP.
	@{
		'window.dialogStyle' = 'custom'
		'files.simpleDialog.enable' = $true
		'saengine.python.path' = ($Python -replace '\\', '/')
		'workbench.startupEditor' = 'none'
		'update.mode' = 'none'
		'telemetry.telemetryLevel' = 'off'
		'window.restoreWindows' = 'none'
	} | ConvertTo-Json | Set-Content -Encoding utf8 $settings
}
$env:PYTHONPATH = "$repo\python\src;$repo\third_party\opensees-studio\src"
$env:NODE_ENV = 'development'
$env:VSCODE_DEV = '1'
$env:VSCODE_CLI = '1'
$env:VSCODE_SKIP_PRELAUNCH = '1'
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
$exe = Join-Path $workbench '.build\electron\SAEngine.exe'
$arguments = @(
	"`"$workbench`"",
	"--user-data-dir=`"$userData`"",
	"--extensions-dir=`"$(Join-Path $GateDir 'ext')`"",
	"--remote-debugging-port=$Port",
	'--disable-extension=vscode.vscode-api-tests',
	'--disable-features=CalculateNativeWinOcclusion',
	'--disable-backgrounding-occluded-windows',
	'--disable-renderer-backgrounding',
	'--new-window'
)
$p = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $workbench -PassThru
$p.Id
