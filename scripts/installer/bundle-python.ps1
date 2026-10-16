<#
.SYNOPSIS
    Builds the self-contained Python that ships with the SAEngine installer.

.DESCRIPTION
    1. Downloads the pinned python-build-standalone CPython 3.12 (x64, install_only_stripped)
       into the cache folder and checks its SHA-256.
    2. Extracts it into <WorkDir>\python (a fresh copy every run).
    3. Installs opensees-studio (headless, no GUI extras) and saengine from copies of their
       git-tracked sources (untracked files never ship; the source tree gets no build/ or
       egg-info folders), with every dependency pinned by scripts\installer\constraints.txt,
       and fails when a tracked data file (a template) was not installed.
    4. Removes what the runtime never uses (tests, __pycache__, IDLE, Tk, ensurepip), isolates
       the interpreter from the user's environment (python312._pth, no user site-packages) and
       precompiles the bytecode with unchecked hashes, so Python never writes into the
       install folder.
    5. Imports every backend module from the result, fails if a GUI package slipped in, and
       checks that PYTHONHOME, PYTHONPATH and a user site-packages cannot shadow the bundle.

    The result is <WorkDir>\python\python.exe. build-installer.ps1 copies it to
    <app>\resources\python.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$WorkDir,
    [switch]$NoPrecompile
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# python-build-standalone release pin. Bump all three together; the hash is the one published
# next to the asset (<asset>.sha256) on https://github.com/astral-sh/python-build-standalone.
$PbsRelease = '20250409'
$PbsAsset = 'cpython-3.12.10+20250409-x86_64-pc-windows-msvc-install_only_stripped.tar.gz'
$PbsSha256 = '08670ab68f041481b8127b2ea27e01ddf56131e61fcf845f489024fddcd3deec'
$PbsUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/$PbsRelease/$($PbsAsset.Replace('+', '%2B'))"

function Invoke-Checked {
    param([string]$FilePath, [string[]]$Arguments, [string]$What)
    # Windows PowerShell turns a native command's stderr into terminating errors under 'Stop'
    # when the output is redirected; the exit code is what decides here.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $FilePath @Arguments
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed (exit code $LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Remove-Tree {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

$cacheDir = Join-Path $WorkDir 'cache'
$pythonDir = Join-Path $WorkDir 'python'
$sourceDir = Join-Path $WorkDir 'src'
$constraints = Join-Path $PSScriptRoot 'constraints.txt'
$null = New-Item -ItemType Directory -Path $cacheDir -Force

# 1. Download and verify.
$archive = Join-Path $cacheDir $PbsAsset
if (-not (Test-Path -LiteralPath $archive)) {
    Write-Host "Downloading $PbsUrl"
    $partial = "$archive.partial"
    $ProgressPreference = 'SilentlyContinue'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $PbsUrl -OutFile $partial -UseBasicParsing
    Move-Item -LiteralPath $partial -Destination $archive -Force
}
$actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $PbsSha256) {
    Remove-Item -LiteralPath $archive -Force
    throw "SHA-256 mismatch for $PbsAsset (expected $PbsSha256, got $actual). The download was deleted; run again."
}
Write-Host "Verified $PbsAsset ($PbsSha256)"

# 2. Fresh extraction: the archive holds a single python\ folder.
Remove-Tree $pythonDir
Invoke-Checked 'tar.exe' @('-xzf', $archive, '-C', $WorkDir) 'Extracting Python'
$python = Join-Path $pythonDir 'python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "The Python archive did not contain python\python.exe."
}
# Isolated (-I): ignore PYTHONPATH, PYTHONHOME and the user site folder of the build machine.
$py = @('-I')

# 3. Copies of the two local projects, without tests, caches or editable-install metadata.
Remove-Tree $sourceDir
$projects = @(
    @{ Name = 'opensees-studio'; From = (Join-Path $RepoRoot 'third_party\opensees-studio'); Files = @('pyproject.toml', 'README.md', 'LICENSE') },
    @{ Name = 'saengine'; From = (Join-Path $RepoRoot 'python'); Files = @('pyproject.toml') }
)
$installTargets = @()
$dataFiles = @()
foreach ($project in $projects) {
    $target = Join-Path $sourceDir $project.Name
    $null = New-Item -ItemType Directory -Path $target -Force
    foreach ($file in $project.Files) {
        Copy-Item -LiteralPath (Join-Path $project.From $file) -Destination $target
    }
    # Only the files git tracks (in their working-tree state), so an untracked module never
    # ships: what is installed is what the commit in the source offer holds, plus any
    # uncommitted edits (which build-installer.ps1 marks in the version).
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $tracked = @(& git -C $project.From ls-files -- src 2>$null)
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    if ($code -ne 0 -or $tracked.Count -eq 0) {
        throw "git ls-files found no tracked sources in $($project.From)\src (exit code $code)."
    }
    $copied = 0
    foreach ($relative in $tracked) {
        $from = Join-Path $project.From $relative
        if (-not (Test-Path -LiteralPath $from -PathType Leaf)) { continue }  # deleted, not committed
        $to = Join-Path $target $relative
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $to) -Force
        Copy-Item -LiteralPath $from -Destination $to
        $copied++
        # Files the runtime reads next to the code (templates): pyproject package-data must ship them.
        $leaf = Split-Path -Leaf $relative
        if ($leaf -notmatch '\.(py|pyi|md|txt)$' -and -not $leaf.StartsWith('.')) {
            $dataFiles += [pscustomobject]@{ Project = $project.Name; Relative = ($relative -replace '^src/', '') }
        }
    }
    Write-Host "$($project.Name): $copied tracked source files"
    $installTargets += $target
}
$global:LASTEXITCODE = 0

Write-Host 'Installing the SAEngine backend into the bundled Python'
Invoke-Checked $python ($py + @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location',
        '--no-compile', '--only-binary', ':all:', '--no-binary', 'saengine,opensees-studio',
        '-c', $constraints) + $installTargets) 'pip install'
Invoke-Checked $python ($py + @('-m', 'pip', 'check', '--disable-pip-version-check')) 'pip check'
$sitePackages = Join-Path $pythonDir 'Lib\site-packages'
$missingData = @($dataFiles | Where-Object { -not (Test-Path -LiteralPath (Join-Path $sitePackages $_.Relative)) })
if ($missingData.Count -gt 0) {
    $list = ($missingData | ForEach-Object { "$($_.Project): src/$($_.Relative)" }) -join "`n  - "
    throw "These tracked data files were not installed, so the code that reads them would fail at runtime. Add them to [tool.setuptools.package-data] in the project's pyproject.toml:`n  - $list"
}

# 4. Prune. Directory names under site-packages that only hold test suites or examples.
$lib = Join-Path $pythonDir 'Lib'
foreach ($dir in @('test', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', 'lib2to3\tests')) {
    Remove-Tree (Join-Path $lib $dir)
}
foreach ($dir in @('tcl', 'include', 'libs')) {
    Remove-Tree (Join-Path $pythonDir $dir)
}
# gmsh's wheel adds its C import library, Julia binding and CMake files next to the DLL, and
# widgetsnbextension adds Jupyter front-end assets; none is used at runtime. share\doc\gmsh (its
# licence and credits) stays.
foreach ($dir in @('share\jupyter', 'share\man', 'share\gmsh')) {
    Remove-Tree (Join-Path $pythonDir $dir)
}
foreach ($file in @('DLLs\_tkinter.pyd', 'DLLs\tcl86t.dll', 'DLLs\tk86t.dll', 'Lib\turtle.py', 'Lib\gmsh.dll.lib', 'Lib\gmsh.jl')) {
    $path = Join-Path $pythonDir $file
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
}
Get-ChildItem -LiteralPath $sitePackages -Directory -Recurse -Force |
    Where-Object { $_.Name -in @('tests', '__pycache__') -and $_.FullName -notmatch '\\pip\\' } |
    Sort-Object { $_.FullName.Length } -Descending |
    ForEach-Object { Remove-Tree $_.FullName }
Get-ChildItem -LiteralPath $pythonDir -Directory -Recurse -Force -Filter '__pycache__' |
    ForEach-Object { Remove-Tree $_.FullName }
# -Filter, not -Include: Windows PowerShell ignores -Include together with -LiteralPath.
Get-ChildItem -LiteralPath $pythonDir -Recurse -Force -File -Filter '*.pdb' | Remove-Item -Force

# Isolation. The workbench starts this python.exe without -I and passes its own environment on,
# so a user's PYTHONHOME or PYTHONPATH (set by GIS or other Python software) or their per-user
# site-packages (pip install --user into %APPDATA%\Python\Python312) would override the bundle.
# A python312._pth file next to python312.dll fixes sys.path to the listed folders and ignores
# PYTHONHOME, PYTHONPATH and the other PYTHON* path settings (PYTHONIOENCODING and
# PYTHONUNBUFFERED, which the workbench sets, still apply). There is deliberately no
# 'import site' line: the site module would add the user site-packages again (it is a frozen
# module in 3.12, so Lib\site.py cannot be patched), and site-packages is listed here directly.
# Without site, .pth files in site-packages are not processed; none of the pinned packages
# ships one, and the check below stops the build if one ever does.
$pth = @('python312.zip', 'DLLs', 'Lib', '.', 'Lib\site-packages')
Set-Content -LiteralPath (Join-Path $pythonDir 'python312._pth') -Value $pth -Encoding ascii
$pthFiles = @(Get-ChildItem -LiteralPath $sitePackages -Filter '*.pth' -File -Force)
if ($pthFiles.Count -gt 0) {
    throw "site-packages contains .pth files ($($pthFiles.Name -join ', ')), which the isolated bundle (no site module) does not process. Check what they do and add their paths to python312._pth in bundle-python.ps1."
}

if (-not $NoPrecompile) {
    Write-Host 'Precompiling bytecode'
    # unchecked-hash: the .pyc files stay valid whatever timestamps the installer gives the
    # sources, so Python never needs to write __pycache__ into the install folder. A handful of
    # files that are not Python 3 (template fragments in some packages) fail to compile; that is
    # expected, so the exit code is not checked here and the import check below decides.
    & $python -I -m compileall -q -j 0 --invalidation-mode unchecked-hash $lib | Out-Null
}

# 5. Verify: every backend module imports and no GUI package slipped in. (A script file, not
# -c: Windows PowerShell strips the double quotes of arguments passed to native programs.)
# -B: the check must not leave __pycache__ folders behind.
Invoke-Checked $python ($py + @('-B', (Join-Path $PSScriptRoot 'smoke_model.py'), '--imports-only')) 'Backend import check'

$size = (Get-ChildItem -LiteralPath $pythonDir -Recurse -File -Force | Measure-Object -Property Length -Sum).Sum
Write-Host ("Bundled Python ready: {0} ({1:N0} MB)" -f $python, ($size / 1MB))
