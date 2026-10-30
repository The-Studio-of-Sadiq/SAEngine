<#
.SYNOPSIS
    Installs an SAEngine setup silently into a temporary folder and tests it without the
    repository's .venv.

.DESCRIPTION
    1. Runs the setup with /VERYSILENT into -InstallDir, without the PATH, file-association,
       desktop-icon and run-after-install tasks; checks the bin shims (saengine.cmd, the
       command line; saengine-app.cmd, the window launcher) and, when bundled, LibreCAD with
       its licences and LibreDWG's dwg2dxf (it runs, and the backend finds it). Runs "bin\saengine.cmd --help" when the backend has saengine.cli.
       When the setup has optional components: runs it again with /TYPE=compact (they are
       removed, the backend reports them missing) and with /COMPONENTS= (they are back).
    2. With the bundled resources\python\python.exe, from a folder outside the repository and
       with a hostile Python environment (PYTHONHOME pointing nowhere, PYTHONPATH and a user
       site-packages that shadow numpy): checks the isolation, imports the backend, makes the JSON-RPC
       round trip the workbench makes (saengine/info, project/validate), derives a one-bay
       frame project and analyses it with python -m opensees_studio.run
       (scripts\installer\smoke_model.py).
    3. Starts the installed SAEngine.exe on that project with a throw-away user-data folder and
       checks over the DevTools protocol that the workbench renders, the FEM viewer bundle
       loads from node_modules.asar and "Check Python Runtime" finds the bundled Python
       (scripts\installer\smoke-app.mjs).
    4. Uninstalls silently and checks the folder is gone (unless -KeepInstall).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\installer\smoke-test.ps1
#>
[CmdletBinding()]
param(
    [string]$Setup,
    [string]$InstallDir = (Join-Path ([IO.Path]::GetTempPath()) 'SAEngine-smoke\install'),
    [int]$DebugPort = 9339,
    [switch]$KeepInstall
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$workbench = Join-Path $repoRoot 'workbench'
$smokeRoot = Split-Path -Parent $InstallDir
$project = Join-Path $smokeRoot 'Smoke Project'
$userData = Join-Path $smokeRoot 'user-data'
$extensions = Join-Path $smokeRoot 'extensions'
$results = [ordered]@{}

if (-not $Setup) {
    $latest = Get-ChildItem -Path (Join-Path $repoRoot 'dist') -Filter 'SAEngine-x64-user-setup-*.exe' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { throw 'No setup in dist\: run scripts\build-installer.ps1 first, or pass -Setup.' }
    $Setup = $latest.FullName
}
if (Test-Path -LiteralPath $smokeRoot) {
    try {
        Remove-Item -LiteralPath $smokeRoot -Recurse -Force -ErrorAction Stop
    } catch {
        # The git extension creates its askpass folder in the user-data folder with an ACL the
        # user cannot delete through; a leftover of an earlier run must not stop this one.
        Write-Warning "Could not clean $smokeRoot completely ($($_.Exception.Message)); using fresh subfolders."
        foreach ($path in @($InstallDir, $project)) {
            if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
        }
    }
}
# A fresh user-data folder per run (see above).
$userData = Join-Path $smokeRoot ('user-data-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
$null = New-Item -ItemType Directory -Path $smokeRoot -Force

function Measure-Step([string]$Name, [scriptblock]$Body) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    & $Body
    $results[$Name] = $watch.Elapsed
    Write-Host ('ok      {0} ({1:N1} s)' -f $Name, $watch.Elapsed.TotalSeconds) -ForegroundColor Green
}

function Invoke-Native([string]$FilePath, [string[]]$Arguments, [string]$What, [string]$WorkingDirectory) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) { throw "$What failed (exit code $code)." }
}

Write-Host "Setup:   $Setup ($('{0:N0} MB' -f ((Get-Item $Setup).Length / 1MB)))"
Write-Host "Install: $InstallDir"

# 1. Silent install.
Measure-Step 'silent install' {
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$InstallDir`"",
        '/MERGETASKS="!runcode,!addtopath,!associatewithfiles,!desktopicon"', "/LOG=`"$(Join-Path $smokeRoot 'setup.log')`"")
    $process = Start-Process -FilePath $Setup -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -ne 0) { throw "The setup exited with $($process.ExitCode); see $smokeRoot\setup.log." }
    foreach ($file in @('SAEngine.exe', 'resources\app\out\main.js', 'resources\python\python.exe', 'THIRD_PARTY_NOTICES.txt', 'LICENSE.txt',
            'bin\saengine.cmd', 'bin\saengine-app.cmd')) {
        if (-not (Test-Path (Join-Path $InstallDir $file))) { throw "The installation lacks $file." }
    }
    # LibreCAD, when this build bundles it: the program, its Qt platform plug-in and its licences.
    $libreCAD = Join-Path $InstallDir 'resources\librecad'
    if (Test-Path (Join-Path $libreCAD 'SAENGINE-BUNDLE.json')) {
        $bundle = Get-Content (Join-Path $libreCAD 'SAENGINE-BUNDLE.json') -Raw | ConvertFrom-Json
        foreach ($file in @('LibreCAD.exe', 'platforms\qwindows.dll') + @($bundle.licenses)) {
            if (-not (Test-Path (Join-Path $libreCAD $file))) { throw "The LibreCAD bundle lacks $file." }
        }
        if ((Get-Content (Join-Path $InstallDir 'THIRD_PARTY_NOTICES.txt') -Raw) -notmatch 'LibreCAD') {
            throw 'THIRD_PARTY_NOTICES.txt does not name the bundled LibreCAD.'
        }
        Write-Host "LibreCAD $($bundle.version) (Qt $($bundle.qt_version)) is bundled."
    }
    # GNU LibreDWG, when this build bundles it: dwg2dxf runs, and the backend finds it there.
    $libreDWG = Join-Path $InstallDir 'resources\libredwg'
    if (Test-Path (Join-Path $libreDWG 'SAENGINE-BUNDLE.json')) {
        $bundle = Get-Content (Join-Path $libreDWG 'SAENGINE-BUNDLE.json') -Raw | ConvertFrom-Json
        foreach ($file in @('dwg2dxf.exe', 'libredwg-0.dll') + @($bundle.licenses)) {
            if (-not (Test-Path (Join-Path $libreDWG $file))) { throw "The LibreDWG bundle lacks $file." }
        }
        $answer = & (Join-Path $libreDWG 'dwg2dxf.exe') --version
        if ($LASTEXITCODE -ne 0 -or "$answer" -notmatch "dwg2dxf $([regex]::Escape($bundle.version))") {
            throw "The bundled dwg2dxf answered '$answer' (exit code $LASTEXITCODE)."
        }
        $found = & (Join-Path $InstallDir 'resources\python\python.exe') -I -c 'from saengine.library.dwg import find_converter; print(find_converter())'
        if (-not "$found".Trim().EndsWith('resources\libredwg\dwg2dxf.exe', [StringComparison]::OrdinalIgnoreCase)) {
            throw "The backend finds '$found' instead of the bundled dwg2dxf."
        }
        if ((Get-Content (Join-Path $InstallDir 'THIRD_PARTY_NOTICES.txt') -Raw) -notmatch 'GNU LibreDWG') {
            throw 'THIRD_PARTY_NOTICES.txt does not name the bundled GNU LibreDWG.'
        }
        Write-Host "GNU LibreDWG $($bundle.version) is bundled."
    }
}

# The setup's optional components (code.iss [Components]), when this build has any: running the
# setup again as Compact removes them, and with /COMPONENTS= (what the app's Add Component...
# passes) adds them back; the backend reports each state (components/list).
$componentFolders = [ordered]@{ energyplus = 'resources\energyplus'; librecad = 'resources\librecad'; libredwg = 'resources\libredwg' }
$components = @($componentFolders.Keys | Where-Object { Test-Path (Join-Path $InstallDir $componentFolders[$_]) })
if ($components.Count -gt 0) {
    function Invoke-Setup([string[]]$Extra, [string]$Log) {
        $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$InstallDir`"", "/LOG=`"$(Join-Path $smokeRoot $Log)`"") + $Extra
        $process = Start-Process -FilePath $Setup -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "The setup ($($Extra -join ' ')) exited with $($process.ExitCode); see $smokeRoot\$Log." }
    }
    function Get-BackendComponents {
        $text = & (Join-Path $InstallDir 'resources\python\python.exe') -I -c 'import json; from saengine.rpc.handlers import installer_components as c; print(json.dumps(c()))'
        return "$text" | ConvertFrom-Json
    }
    Measure-Step "components: Compact removes $($components -join ', '), /COMPONENTS= adds them back" {
        $state = Get-BackendComponents
        foreach ($name in @('energyplus', 'libredwg')) {
            if ($components -contains $name -and $state.$name.state -ne 'installed') { throw "The backend reports $name as '$($state.$name.state)' in a Full install." }
        }
        Invoke-Setup @('/TYPE=compact', '/MERGETASKS="!runcode"') 'setup-compact.log'
        foreach ($name in $components) {
            if (Test-Path (Join-Path $InstallDir $componentFolders[$name])) { throw "The Compact install kept $($componentFolders[$name])." }
        }
        if (-not (Test-Path (Join-Path $InstallDir 'resources\python\python.exe'))) { throw 'The Compact install lacks the bundled Python.' }
        $state = Get-BackendComponents
        foreach ($name in @('energyplus', 'libredwg')) {
            if ($state.$name.state -eq 'installed') { throw "The backend still reports $name as installed after the Compact install." }
        }
        Invoke-Setup @("/COMPONENTS=$($components -join ',')", '/MERGETASKS="!runcode"') 'setup-components.log'
        foreach ($name in $components) {
            if (-not (Test-Path (Join-Path $InstallDir $componentFolders[$name]))) { throw "/COMPONENTS= did not add $($componentFolders[$name])." }
        }
    }
}

# The saengine command line shim (bin\saengine.cmd -> python -m saengine.cli), when the bundled
# backend has the command line.
$cliPackage = Join-Path $InstallDir 'resources\python\Lib\site-packages\saengine\cli'
if (Test-Path $cliPackage) {
    Measure-Step 'saengine command line (bin\saengine.cmd --help)' {
        Invoke-Native (Join-Path $InstallDir 'bin\saengine.cmd') @('--help') 'saengine --help' $smokeRoot
    }
}

# 2. The bundled Python, as the workbench runs it: no -I, nothing from the repository on PATH,
# and a hostile Python environment that the bundle must ignore: PYTHONHOME pointing nowhere,
# PYTHONPATH and a per-user site-packages holding a numpy that fails to import, a VIRTUAL_ENV.
$python = Join-Path $InstallDir 'resources\python\python.exe'
$hostile = Join-Path $smokeRoot 'hostile-env'
$shadowPath = Join-Path $hostile 'pythonpath\numpy'
$shadowUser = Join-Path $hostile 'user\Python\Python312\site-packages\numpy'
foreach ($folder in @($shadowPath, $shadowUser)) {
    $null = New-Item -ItemType Directory -Path $folder -Force
    Set-Content -LiteralPath (Join-Path $folder '__init__.py') -Value "raise ImportError('shadow numpy from $($folder.Replace('\', '/')) was imported')" -Encoding ascii
}
$saved = @{}
$hostileValues = @{
    PYTHONPATH = (Join-Path $hostile 'pythonpath')
    PYTHONHOME = (Join-Path $hostile 'no-such-home')
    PYTHONUSERBASE = (Join-Path $hostile 'user\Python')
    VIRTUAL_ENV = (Join-Path $hostile 'venv')
    PYTHONSTARTUP = $null
    PYTHONNOUSERSITE = $null
}
foreach ($name in $hostileValues.Keys) {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name)
    [Environment]::SetEnvironmentVariable($name, $hostileValues[$name])
}
$savedPath = $env:PATH
$env:PATH = ($env:PATH -split ';' | Where-Object { $_ -and $_ -notlike "$repoRoot*" }) -join ';'
try {
    Measure-Step 'bundled Python: backend imports, JSON-RPC, analysis' {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'smoke_model.py') -Destination $smokeRoot
        Invoke-Native $python @('-B', (Join-Path $smokeRoot 'smoke_model.py'), '--work', $project) 'smoke_model.py' $smokeRoot
    }
} finally {
    $env:PATH = $savedPath
    foreach ($name in $saved.Keys) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
}

# 3. The installed app.
Measure-Step 'installed app: workbench, FEM viewer bundle, Check Python Runtime' {
    $exe = Join-Path $InstallDir 'SAEngine.exe'
    $appArgs = @("`"$project`"", "--user-data-dir=`"$userData`"", "--extensions-dir=`"$extensions`"",
        '--skip-welcome', '--skip-release-notes', '--disable-workspace-trust', "--remote-debugging-port=$DebugPort")
    $app = Start-Process -FilePath $exe -ArgumentList $appArgs -PassThru
    try {
        Invoke-Native 'node' @((Join-Path $PSScriptRoot 'smoke-app.mjs'), "$DebugPort", $InstallDir) 'smoke-app.mjs' $workbench
    } finally {
        Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $exe } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        $null = $app.WaitForExit(15000)
        Start-Sleep -Seconds 2
    }
}

# 4. Uninstall.
if (-not $KeepInstall) {
    Measure-Step 'silent uninstall' {
        $uninstaller = Join-Path $InstallDir 'unins000.exe'
        $process = Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "The uninstaller exited with $($process.ExitCode)." }
        # The uninstaller finishes in a copy of itself; give it a moment.
        $deadline = (Get-Date).AddSeconds(60)
        while ((Test-Path (Join-Path $InstallDir 'SAEngine.exe')) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 1 }
        $left = @(Get-ChildItem -LiteralPath $InstallDir -Recurse -Force -ErrorAction SilentlyContinue)
        if ($left.Count -gt 0) {
            Write-Warning "$($left.Count) file(s) left in $InstallDir after uninstalling, for example $($left[0].FullName)"
        }
    }
}

Write-Host ''
Write-Host 'SMOKE TEST PASSED' -ForegroundColor Green
foreach ($key in $results.Keys) { Write-Host ('{0,-70} {1,8:N1} s' -f $key, $results[$key].TotalSeconds) }
