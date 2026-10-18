<#
.SYNOPSIS
    Builds the SAEngine Windows x64 user installer (beta): dist\SAEngine-x64-user-setup-<version>.exe

.DESCRIPTION
    One command for the whole chain, safe to run again:
      1. Checks the prerequisites (Node, the workbench's node_modules, Inno Setup from the
         'innosetup' npm package, the built viewer bundles, tar, disk space).
      2. Builds the minified win32-x64 app with Code - OSS's own gulp tasks
         (vscode-win32-x64-min, vscode-win32-x64-inno-updater) into <repo>\VSCode-win32-x64.
         scripts\installer\gulp-packaging-fixes.cjs is preloaded so the build packages the
         @saengine viewer bundles and the locally compiled Copilot extension (see that file).
      3. Builds the bundled CPython 3.12 with the SAEngine backend
         (scripts\installer\bundle-python.ps1) and copies it to
         VSCode-win32-x64\resources\python, where the workbench looks for it. With
         -EnergyPlusDir, copies the minimal EnergyPlus version 26.2.0 runtime (the program, its
         DLLs, Energy+.idd, Energy+.schema.epJSON and its LICENSE.txt, about 62 MB) to
         VSCode-win32-x64\resources\energyplus, where the backend looks for it, and checks it
         with a design-day run (scripts\installer\energyplus_runtime.py).
      4. Writes THIRD_PARTY_NOTICES.txt (the viewer bundles' npm packages and the Python
         packages with their licences, the AGPL source offer, the copyleft source offer) and
         LICENSE.txt (AGPL-3.0) into the app folder, and collects the source archives of the
         copyleft binaries (scripts\installer\fetch-sources.ps1) into
         dist\SAEngine-<version>-third-party-sources, to be published next to the setup.
      5. Runs Inno Setup (gulp vscode-win32-x64-user-setup) and copies the setup to
         dist\SAEngine-x64-user-setup-<version>.exe with a .sha256 file next to it.
      6. Prints sizes and timings.

    Docs: docs\install\README.md

.PARAMETER Version
    SAEngine version in the setup file name and THIRD_PARTY_NOTICES. Defaults to x.y.z when HEAD
    is a clean release (a v<x.y.z> tag, or a commit titled 'v<x.y.z>'); otherwise
    x.y.(z+1)-dev.<commits since that release>, with '.local' appended when there are
    uncommitted or untracked files (for example 0.0.26-dev.3.local). With no release in the
    history: the saengine package version (python\pyproject.toml), plus '-dev' when not clean.
    Windows' Installed apps list and About keep showing the Code - OSS version of
    workbench\package.json, which Inno Setup takes from there.

.PARAMETER SkipAppBuild
    Reuse the existing VSCode-win32-x64 folder (steps 3 to 6 only).

.PARAMETER SkipPython
    Reuse the bundled Python already in workbench\.build\saengine-installer\python.

.PARAMETER SkipSetup
    Stop after the app folder is complete (no Inno Setup run).

.PARAMETER RefreshConstraints
    Regenerate scripts\installer\constraints.txt from the development .venv first.

.PARAMETER NoPrecompile
    Ship the bundled Python without precompiled bytecode (smaller setup, slower first run).

.PARAMETER EnergyPlusDir
    The extracted EnergyPlus 26.2.0 distribution for Windows x64 (the folder with energyplus.exe),
    from which the minimal runtime for the HVAC cooling loads is bundled. Defaults to the
    SAENGINE_ENERGYPLUS_DIR environment variable. Optional: without it the app is built without
    EnergyPlus and the HVAC loads fall back to SAEngine's documented estimate.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build-installer.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\build-installer.ps1 -SkipAppBuild -Version 0.0.25-beta
#>
[CmdletBinding()]
param(
    [string]$Version,
    [switch]$SkipAppBuild,
    [switch]$SkipPython,
    [switch]$SkipSetup,
    [switch]$RefreshConstraints,
    [switch]$NoPrecompile,
    [string]$EnergyPlusDir = $env:SAENGINE_ENERGYPLUS_DIR
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot
$workbench = Join-Path $repoRoot 'workbench'
$installerScripts = Join-Path $PSScriptRoot 'installer'
# Fixed by the Code - OSS build: gulp writes the packaged app next to the workbench folder.
$appDir = Join-Path $repoRoot 'VSCode-win32-x64'
$workDir = Join-Path $workbench '.build\saengine-installer'
$distDir = Join-Path $repoRoot 'dist'
$setupDir = Join-Path $workbench '.build\win32-x64\user-setup'
$timings = [ordered]@{}
$total = [Diagnostics.Stopwatch]::StartNew()

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Native {
    param([string]$FilePath, [string[]]$Arguments, [string]$What, [string]$WorkingDirectory = $repoRoot)
    # Native stderr must not become a terminating error (Windows PowerShell); the exit code decides.
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
    if ($code -ne 0) {
        throw "$What failed (exit code $code)."
    }
}

function Invoke-Gulp {
    param([string]$Task)
    $started = [Diagnostics.Stopwatch]::StartNew()
    $previousOptions = $env:NODE_OPTIONS
    # Forward slashes: NODE_OPTIONS treats a backslash inside quotes as an escape character.
    $preload = (Join-Path $installerScripts 'gulp-packaging-fixes.cjs').Replace('\', '/')
    $env:NODE_OPTIONS = "--require `"$preload`""
    try {
        Invoke-Native 'npm.cmd' @('run', 'gulp', '--', $Task) "gulp $Task" $workbench
    } finally {
        $env:NODE_OPTIONS = $previousOptions
    }
    $timings["gulp $Task"] = $started.Elapsed
}

function Get-FolderSize([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }
    $sum = (Get-ChildItem -LiteralPath $Path -Recurse -File -Force | Measure-Object -Property Length -Sum).Sum
    if ($sum) { return [long]$sum } else { return 0 }
}

function Format-Size([long]$Bytes) {
    return '{0:N0} MB' -f ($Bytes / 1MB)
}

function Remove-Tree([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

# --- 1. Prerequisites ------------------------------------------------------------------------
Write-Step 'Checking prerequisites'
$problems = @()
if ([Environment]::OSVersion.Platform -ne 'Win32NT' -or -not [Environment]::Is64BitOperatingSystem) {
    $problems += 'The installer is built on 64-bit Windows.'
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    $problems += 'Node.js is not on PATH (use the version in workbench\.nvmrc).'
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    $problems += 'npm is not on PATH.'
}
if (-not (Get-Command tar.exe -ErrorAction SilentlyContinue)) {
    $problems += 'tar.exe (part of Windows 10 1803 and later) is not on PATH.'
}
if (-not (Test-Path (Join-Path $workbench 'node_modules\gulp'))) {
    $problems += "The workbench dependencies are not installed: run 'npm install' in $workbench."
}
$iscc = Join-Path $workbench 'node_modules\innosetup\bin\ISCC.exe'
if (-not (Test-Path $iscc)) {
    $problems += "Inno Setup is missing ($iscc). It comes with the workbench devDependency 'innosetup': run 'npm install' in $workbench."
}
foreach ($bundle in @('packages\fem-viewer\dist\fem-viewer.js', 'packages\fem-viewer\dist\fragments-worker.mjs', 'packages\cad-editor\dist\cad-editor.js')) {
    if (-not (Test-Path (Join-Path $repoRoot $bundle))) {
        $package = ($bundle -split '\\')[1]
        $problems += "$bundle is missing: run 'npm install' and 'npm run build' in packages\$package."
    }
}
if (-not $SkipPython -and -not (Test-Path (Join-Path $repoRoot 'third_party\opensees-studio\pyproject.toml'))) {
    $problems += 'third_party\opensees-studio is empty: run git submodule update --init.'
}
# The win32 packaging step runs signtool.exe (to strip signatures before stamping version
# resources), so it must be on PATH: take the newest x64 one of the Windows SDK if it is not.
if (-not $SkipAppBuild -and -not (Get-Command signtool.exe -ErrorAction SilentlyContinue)) {
    $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
    $signtool = Get-ChildItem -Path $kits -Filter 'signtool.exe' -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Directory.Name -eq 'x64' } | Sort-Object { $_.Directory.Parent.Name } -Descending | Select-Object -First 1
    if ($signtool) {
        $env:PATH = "$($signtool.DirectoryName);$env:PATH"
        Write-Host "Using $($signtool.FullName)"
    } else {
        $problems += "signtool.exe is not on PATH and no Windows SDK was found in ${kits}: install the Windows SDK's 'Signing Tools for Desktop Apps'."
    }
}
$devPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
if ($RefreshConstraints -and -not (Test-Path $devPython)) {
    $problems += "-RefreshConstraints needs the development .venv ($devPython)."
}
$drive = (Get-Item $repoRoot).PSDrive
if ($drive.Free -lt 15GB) {
    $problems += ('Less than 15 GB free on {0}: ({1:N1} GB). The build needs about 10 GB.' -f $drive.Name, ($drive.Free / 1GB))
}
if ($problems.Count -gt 0) {
    throw ("Cannot build the installer:`n  - " + ($problems -join "`n  - "))
}
$memory = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
if ($memory -lt 16GB - 1GB) {
    Write-Warning ('{0:N0} GB of RAM: the minified build (gulp runs with an 8 GB heap) may run out of memory.' -f ($memory / 1GB))
}
$packageJson = Get-Content (Join-Path $workbench 'package.json') -Raw | ConvertFrom-Json
$product = Get-Content (Join-Path $workbench 'product.json') -Raw | ConvertFrom-Json
# Uncommitted changes, untracked files included: bundle-python.ps1 ships only git-tracked backend
# files, but the app build compiles whatever is in workbench\ and packages\. The build outputs
# themselves (until .gitignore lists them) do not count.
$ErrorActionPreference = 'Continue'
$dirty = @(& git -C $repoRoot status --porcelain --untracked-files=all -- . ':(exclude)VSCode-win32-x64' ':(exclude)dist' 2>$null)
$ErrorActionPreference = 'Stop'
$global:LASTEXITCODE = 0
if (-not $Version) {
    # SAEngine's own release number, not Code - OSS's package.json version (which Inno Setup
    # records as the installed version and About shows, and which only package.json can change).
    # Releases are commits titled 'v<x.y.z>' (or v<x.y.z> tags). A clean release commit gives
    # x.y.z. Anything else is a pre-release of the NEXT patch version, so it sorts after the
    # release it builds on and before the next one: x.y.(z+1)-dev.<commits since the release>,
    # plus '.local' when the working tree has uncommitted changes. Without any release in the
    # history, the saengine Python package version is used.
    # 'Continue': in Windows PowerShell, git's stderr ("No names found") would otherwise stop the script.
    $ErrorActionPreference = 'Continue'
    $tag = (& git -C $repoRoot describe --tags --abbrev=0 --match 'v[0-9]*' 2>$null)
    $history = @(& git -C $repoRoot log --format='%H %s' -n 1000 2>$null)
    $ErrorActionPreference = 'Stop'
    $global:LASTEXITCODE = 0
    $release = $null
    $since = 0
    if ($tag -match '^v([0-9]+)\.([0-9]+)\.([0-9]+)$') {
        $release = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3])
        $since = [int](& git -C $repoRoot rev-list --count "$tag..HEAD")
    } else {
        for ($i = 0; $i -lt $history.Count; $i++) {
            if ($history[$i] -match '^[0-9a-f]{40} v([0-9]+)\.([0-9]+)\.([0-9]+)\s*$') {
                $release = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3])
                $since = $i
                break
            }
        }
    }
    if ($release) {
        if ($since -eq 0 -and $dirty.Count -eq 0) {
            $Version = '{0}.{1}.{2}' -f $release[0], $release[1], $release[2]
        } else {
            $Version = '{0}.{1}.{2}-dev.{3}' -f $release[0], $release[1], ($release[2] + 1), $since
        }
    } else {
        $pyproject = Get-Content (Join-Path $repoRoot 'python\pyproject.toml') -Raw
        if ($pyproject -match '(?m)^version\s*=\s*"([^"]+)"') { $Version = $Matches[1] } else { $Version = $packageJson.version }
        if ($dirty.Count -gt 0) { $Version = "$Version-dev" }
    }
    if ($dirty.Count -gt 0 -and $release) { $Version = "$Version.local" }
}
if ($dirty.Count -gt 0) {
    Write-Warning ("The working tree has {0} uncommitted or untracked file(s), for example '{1}': the source offer points at a commit that does not contain them. Commit first for a release build." -f $dirty.Count, $dirty[0].Trim())
}
if ($Version -notmatch '^[0-9A-Za-z.\-]+$') {
    throw "Version '$Version' may only contain letters, digits, dots and hyphens."
}
$fullCommit = (& git -C $repoRoot rev-parse HEAD 2>$null)
if ($fullCommit -notmatch '^[0-9a-f]{40}$') {
    throw "Cannot read the git commit of $repoRoot. The build stamps it into product.json."
}
$commit = $fullCommit.Substring(0, 10)
# The Code - OSS build reads the commit from workbench\.git, which does not exist here (the git
# repository is the parent folder). Without a commit in product.json the packaged app believes
# it runs from sources (isBuilt is false): it loads node_modules instead of node_modules.asar
# and looks for the repository .venv instead of the bundled Python. CI passes it in
# BUILD_SOURCEVERSION; gulp-packaging-fixes.cjs sets that from SAENGINE_BUILD_COMMIT for the
# gulp process only (the Copilot extension's build treats it as "CI" and rewrites its
# package.json in the source tree).
$env:SAENGINE_BUILD_COMMIT = $fullCommit
Write-Host "SAEngine $Version (commit $commit), product $($product.nameLong), app folder $appDir"

if ($RefreshConstraints) {
    Write-Step 'Refreshing constraints.txt from the development .venv'
    $constraintsFile = Join-Path $installerScripts 'constraints.txt'
    $header = (Get-Content $constraintsFile | Where-Object { $_ -like '#*' })
    $frozen = & $devPython -m pip freeze --exclude-editable --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'pip freeze failed.' }
    Set-Content -Path $constraintsFile -Value (@($header) + @($frozen)) -Encoding ascii
}

# --- 2. The minified app ---------------------------------------------------------------------
if (-not $SkipAppBuild) {
    Write-Step 'Building the minified win32-x64 app (gulp vscode-win32-x64-min, 10-20 minutes)'
    Invoke-Gulp 'vscode-win32-x64-min'
    Invoke-Gulp 'vscode-win32-x64-inno-updater'
}
$exe = Join-Path $appDir "$($product.nameShort).exe"
$appRoot = Join-Path $appDir 'resources\app'
if (-not (Test-Path $exe) -or -not (Test-Path (Join-Path $appRoot 'out\main.js'))) {
    throw "The packaged app is missing or incomplete ($exe). Run without -SkipAppBuild."
}
$packagedProduct = Get-Content (Join-Path $appRoot 'product.json') -Raw | ConvertFrom-Json
if (-not ($packagedProduct.PSObject.Properties.Name -contains 'commit') -or -not $packagedProduct.commit) {
    throw "The packaged product.json has no commit, so the app would run as if from sources. Rebuild without -SkipAppBuild."
}
if (-not (Test-Path (Join-Path $appDir 'tools\inno_updater.exe'))) {
    Invoke-Gulp 'vscode-win32-x64-inno-updater'
}
Write-Step 'Trimming the built-in Copilot extension to its VSIX contents'
# A local build packages the Copilot extension compiled from sources with ALL of its production
# node_modules (build/lib/extensions.ts packageCopilotExtensionStream; CI downloads the VSIX
# instead). dist\extension.js is an esbuild bundle, and the VSIX (extensions\copilot\.vscodeignore:
# '**' then a whitelist) ships only @github/copilot and @vscode/copilot-typescript-server-plugin
# from node_modules. The rest is about 250 MB that is never loaded, and its nested
# @opentelemetry paths (over 200 characters) break the install: Inno Setup fails with
# "MoveFile failed; code 3" once the install folder plus the path exceeds MAX_PATH (260).
$copilotModules = Join-Path $appRoot 'extensions\copilot\node_modules'
if (Test-Path -LiteralPath $copilotModules) {
    $keep = @('@github\copilot', '@vscode\copilot-typescript-server-plugin')
    foreach ($entry in Get-ChildItem -LiteralPath $copilotModules -Directory -Force) {
        if ($entry.Name.StartsWith('@')) {
            foreach ($scoped in Get-ChildItem -LiteralPath $entry.FullName -Directory -Force) {
                if ("$($entry.Name)\$($scoped.Name)" -notin $keep) { Remove-Tree $scoped.FullName }
            }
            if (-not (Get-ChildItem -LiteralPath $entry.FullName -Force)) { Remove-Tree $entry.FullName }
        } else {
            Remove-Tree $entry.FullName
        }
    }
    Get-ChildItem -LiteralPath $copilotModules -File -Force | Remove-Item -Force
    foreach ($required in $keep) {
        if (-not (Test-Path -LiteralPath (Join-Path $copilotModules "$required\package.json"))) {
            Write-Warning "extensions\copilot\node_modules\$required is missing from the packaged app."
        }
    }
}
# The default install folder is %LOCALAPPDATA%\Programs\SAEngine (41 characters plus the user
# name). Keep every path inside the app short enough for a 30-character user name.
$appPrefix = $appDir.Length + 1
$longest = Get-ChildItem -LiteralPath $appDir -Recurse -File -Force |
    Sort-Object { $_.FullName.Length } -Descending | Select-Object -First 1
$longestRelative = $longest.FullName.Length - $appPrefix
Write-Host "Longest path inside the app: $longestRelative characters ($($longest.FullName.Substring($appPrefix)))"
if ($longestRelative -gt 185) {
    throw "A path inside the app is $longestRelative characters long; installs into %LOCALAPPDATA%\Programs\SAEngine would exceed MAX_PATH for longer user names. Prune it before building the setup."
}

Write-Step 'Checking that the packaged app contains the SAEngine viewer bundles'
Invoke-Native 'node' @((Join-Path $installerScripts 'check-asar.mjs'), (Join-Path $appRoot 'node_modules.asar'),
    '@saengine/fem-viewer/dist/fem-viewer.js', '@saengine/fem-viewer/dist/fragments-worker.mjs',
    '@saengine/cad-editor/dist/cad-editor.js') 'Viewer bundle check' $workbench

# --- 3. Bundled Python -----------------------------------------------------------------------
$bundledPython = Join-Path $workDir 'python'
if (-not $SkipPython -or -not (Test-Path (Join-Path $bundledPython 'python.exe'))) {
    Write-Step 'Building the bundled Python (CPython 3.12 + SAEngine backend)'
    $started = [Diagnostics.Stopwatch]::StartNew()
    $bundleArgs = @{ RepoRoot = $repoRoot; WorkDir = $workDir }
    if ($NoPrecompile) { $bundleArgs['NoPrecompile'] = $true }
    & (Join-Path $installerScripts 'bundle-python.ps1') @bundleArgs
    $timings['bundled Python'] = $started.Elapsed
}
Write-Step 'Copying the bundled Python into the app'
$appPython = Join-Path $appDir 'resources\python'
Remove-Tree $appPython
& robocopy.exe $bundledPython $appPython /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copying the bundled Python failed (robocopy exit code $LASTEXITCODE)." }
$global:LASTEXITCODE = 0

# EnergyPlus version 26.2.0 for the HVAC cooling loads: a separate program the backend runs, never
# linked. Optional: without it the loads are SAEngine's estimate.
$appEnergyPlus = Join-Path $appDir 'resources\energyplus'
Remove-Tree $appEnergyPlus
if ($EnergyPlusDir) {
    Write-Step 'Copying the minimal EnergyPlus version 26.2.0 runtime into the app'
    $started = [Diagnostics.Stopwatch]::StartNew()
    Invoke-Native (Join-Path $appPython 'python.exe') @('-I', '-B', (Join-Path $installerScripts 'energyplus_runtime.py'),
        '--source', $EnergyPlusDir, '--dest', $appEnergyPlus, '--check') 'Bundling EnergyPlus'
    $timings['EnergyPlus runtime'] = $started.Elapsed
} else {
    Write-Host 'EnergyPlus is not bundled (no -EnergyPlusDir or SAENGINE_ENERGYPLUS_DIR): the HVAC loads will be the estimate.'
}

# --- 4. Notices ------------------------------------------------------------------------------
Write-Step 'Writing THIRD_PARTY_NOTICES.txt and LICENSE.txt'
$sourcesName = "$($product.nameShort)-$Version-third-party-sources"
Copy-Item -LiteralPath (Join-Path $repoRoot 'LICENSE') -Destination (Join-Path $appDir 'LICENSE.txt') -Force
Invoke-Native (Join-Path $appPython 'python.exe') @('-I', '-B', (Join-Path $installerScripts 'write_notices.py'),
    '--out', (Join-Path $appDir 'THIRD_PARTY_NOTICES.txt'), '--version', $Version, '--commit', $commit,
    '--python-license', (Join-Path $appPython 'LICENSE.txt'),
    '--js-package', (Join-Path $repoRoot 'packages\fem-viewer'), '--js-package', (Join-Path $repoRoot 'packages\cad-editor'),
    '--copyleft-sources', (Join-Path $installerScripts 'copyleft-sources.json'), '--sources-name', $sourcesName,
    '--energyplus', $appEnergyPlus) 'Writing the notices'

Write-Step 'Collecting the source archives of the copyleft binaries'
$sourcesDir = Join-Path $distDir $sourcesName
$started = [Diagnostics.Stopwatch]::StartNew()
& (Join-Path $installerScripts 'fetch-sources.ps1') -RepoRoot $repoRoot -CacheDir (Join-Path $workDir 'cache\sources') -OutDir $sourcesDir
$timings['copyleft sources'] = $started.Elapsed

# --- 5. Inno Setup ---------------------------------------------------------------------------
$setupFile = $null
if (-not $SkipSetup) {
    Write-Step 'Building the user setup with Inno Setup (gulp vscode-win32-x64-user-setup, several minutes)'
    Invoke-Gulp 'vscode-win32-x64-user-setup'
    $built = Get-ChildItem -LiteralPath $setupDir -Filter '*.exe' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $built) { throw "Inno Setup produced no setup in $setupDir." }
    $null = New-Item -ItemType Directory -Path $distDir -Force
    $setupFile = Join-Path $distDir "$($product.nameShort)-x64-user-setup-$Version.exe"
    Copy-Item -LiteralPath $built.FullName -Destination $setupFile -Force
    $hash = (Get-FileHash -LiteralPath $setupFile -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -Path "$setupFile.sha256" -Value "$hash *$(Split-Path -Leaf $setupFile)" -Encoding ascii
}

# --- 6. Summary ------------------------------------------------------------------------------
Write-Step 'Done'
$rows = @(
    [pscustomobject]@{ Item = 'App folder (VSCode-win32-x64)'; Size = Format-Size (Get-FolderSize $appDir) },
    [pscustomobject]@{ Item = '  of which resources\app'; Size = Format-Size (Get-FolderSize $appRoot) },
    [pscustomobject]@{ Item = '  of which resources\python'; Size = Format-Size (Get-FolderSize $appPython) }
)
if (Test-Path $appEnergyPlus) {
    $rows += [pscustomobject]@{ Item = '  of which resources\energyplus'; Size = Format-Size (Get-FolderSize $appEnergyPlus) }
}
if ($setupFile) {
    $rows += [pscustomobject]@{ Item = (Split-Path -Leaf $setupFile); Size = Format-Size (Get-Item $setupFile).Length }
}
$rows += [pscustomobject]@{ Item = "$sourcesName\ (publish next to the setup)"; Size = Format-Size (Get-FolderSize $sourcesDir) }
$rows | Format-Table -AutoSize | Out-String | Write-Host
foreach ($key in $timings.Keys) {
    Write-Host ('{0,-40} {1:hh\:mm\:ss}' -f $key, $timings[$key])
}
Write-Host ('{0,-40} {1:hh\:mm\:ss}' -f 'total', $total.Elapsed)
if ($setupFile) {
    Write-Host "Setup: $setupFile"
    Write-Host "SHA-256: $hash"
}
