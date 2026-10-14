$ErrorActionPreference = 'Stop'

$saengineRoot = Split-Path -Parent $PSScriptRoot
$codeRoot = Join-Path $saengineRoot 'workbench'
$product = Get-Content (Join-Path $codeRoot 'product.json') -Raw | ConvertFrom-Json
$electronDirectory = Join-Path $codeRoot '.build\electron'
$appExecutable = Join-Path $electronDirectory "$($product.nameShort).exe"
$iconPath = Join-Path $codeRoot 'resources\win32\code.ico'
$rcedit = Join-Path $codeRoot 'node_modules\rcedit\bin\rcedit.exe'
$productPath = Join-Path $codeRoot 'product.json'

if (-not (Test-Path (Join-Path $codeRoot 'out\main.js'))) {
    throw "Code - OSS is not compiled. Install its dependencies and compile it from $codeRoot first."
}

if (-not (Test-Path $iconPath)) {
    throw "The SAEngine application icon is missing: $iconPath"
}
if (-not (Test-Path $rcedit)) {
    throw "The Windows icon editor is missing: $rcedit"
}

$createdExecutable = -not (Test-Path $appExecutable)
if ($createdExecutable) {
    $cachedElectron = Join-Path $electronDirectory 'Code - OSS.exe'
    if (-not (Test-Path $cachedElectron)) {
        throw "The Code - OSS Electron runtime is missing from $electronDirectory. Build the Code - OSS checkout first."
    }
    Copy-Item -LiteralPath $cachedElectron -Destination $appExecutable
}

$appModified = (Get-Item -LiteralPath $appExecutable).LastWriteTimeUtc
$brandingModified = @(
    (Get-Item -LiteralPath $iconPath).LastWriteTimeUtc,
    (Get-Item -LiteralPath $productPath).LastWriteTimeUtc
) | Measure-Object -Maximum
$needsBrandingUpdate = $createdExecutable -or $brandingModified.Maximum -gt $appModified
if ($needsBrandingUpdate) {
    $runningApp = Get-CimInstance Win32_Process -Filter "name = '$($product.nameShort).exe'" |
        Where-Object { $_.ExecutablePath -eq $appExecutable }
    if ($runningApp) {
        throw "Close the existing SAEngine window before refreshing its application branding."
    }

    $iconProcess = Start-Process -FilePath $rcedit `
        -ArgumentList @(
            "`"$appExecutable`"",
            '--set-icon',
            "`"$iconPath`"",
            '--set-version-string',
            'ProductName',
            $product.nameLong,
            '--set-version-string',
            'FileDescription',
            '"SAEngine structural engineering workbench"',
            '--set-version-string',
            'OriginalFilename',
            "$($product.nameShort).exe"
        ) `
        -Wait -PassThru -NoNewWindow
    if ($iconProcess.ExitCode -ne 0) {
        throw "Could not apply the SAEngine icon to $appExecutable (rcedit exit code $($iconProcess.ExitCode))."
    }
}

$userDataPath = Join-Path $env:APPDATA 'SAEngine'
$null = New-Item -ItemType Directory -Path $userDataPath -Force
# Default location offered for new projects.
$projectsPath = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'SAEngine Projects'
$null = New-Item -ItemType Directory -Path $projectsPath -Force
# No folder argument: SAEngine reopens the last project, or shows its start window.
$arguments = @(
    '.',
    "--user-data-dir=`"$userDataPath`""
)

$env:NODE_ENV = 'development'
$env:VSCODE_DEV = '1'
$env:VSCODE_CLI = '1'
$env:VSCODE_SKIP_PRELAUNCH = '1'

$process = Start-Process -FilePath $appExecutable `
    -ArgumentList $arguments `
    -WorkingDirectory $codeRoot `
    -PassThru
Write-Host "Started $($product.nameLong) (PID $($process.Id))."
