<#
.SYNOPSIS
    Collects the source archives of the copyleft components that the installer ships as binaries.

.DESCRIPTION
    gmsh (GPL-2.0+), ifcopenshell and cytriangle (LGPL-3.0), web-ifc (MPL-2.0) and, when the
    build bundles it, LibreCAD (GPL-2.0) with its Qt 5 DLLs (LGPL-3.0) ship as compiled
    binaries. Their licences require the distributor to make the corresponding source
    available: build-installer.ps1 puts these archives in a folder next to the setup, and they
    are published from the same place as the setup (see docs\install\README.md).

    The archives are listed in scripts\installer\copyleft-sources.json with pinned SHA-256
    hashes. Each is downloaded once into <CacheDir> and checked. The script fails when a pinned
    version differs from the version that ships (constraints.txt, the fem-viewer's web-ifc), so
    a dependency upgrade cannot silently leave an outdated source archive.

    Entries with "component": "librecad" are collected only with -LibreCADManifest
    (resources\librecad\SAENGINE-BUNDLE.json, written by librecad_bundle.py): LibreCAD's own
    source, and the Qt source archive of every Qt module whose DLLs the bundle ships. The script
    fails when the bundle's LibreCAD or Qt version differs from the pinned one, or when it ships
    a Qt module that has no entry. An entry whose sha256 is null is not pinned yet: it is refused
    unless -AllowUnpinned is given; then it is downloaded, its hash is printed (pin it) and
    recorded in README.txt.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$CacheDir,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$LibreCADManifest,
    [switch]$AllowUnpinned
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'copyleft-sources.json') -Raw | ConvertFrom-Json
$constraints = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'constraints.txt')
$webIfc = Get-Content -LiteralPath (Join-Path $RepoRoot 'packages\fem-viewer\node_modules\web-ifc\package.json') -Raw | ConvertFrom-Json

# What actually ships, by name.
$shipped = @{ 'web-ifc' = $webIfc.version }
foreach ($line in $constraints) {
    if ($line -match '^([A-Za-z0-9_.\-]+)==(\S+)$') { $shipped[$Matches[1].ToLowerInvariant()] = $Matches[2] }
}
# Optional components: what the build bundled, from their bundle manifests.
$components = @{}
$qtModules = @()
if ($LibreCADManifest) {
    $bundle = Get-Content -LiteralPath $LibreCADManifest -Raw | ConvertFrom-Json
    $components['librecad'] = $true
    $shipped['librecad'] = $bundle.version
    $qtModules = @($bundle.qt_modules)
    if ($qtModules.Count -gt 0 -and -not $bundle.qt_version) {
        throw "$LibreCADManifest has no Qt version (librecad_bundle.py could not read the version resource of Qt$($bundle.qt_major)Core.dll), so the Qt source archives cannot be matched."
    }
    foreach ($module in $qtModules) {
        $shipped["qt-$module"] = $bundle.qt_version
        if (-not ($manifest.sources | Where-Object { $_.PSObject.Properties.Name -contains 'qt_module' -and $_.qt_module -eq $module })) {
            throw "LibreCAD ships Qt module $module, which copyleft-sources.json has no source entry for. Add one (name qt-$module, qt_module $module)."
        }
    }
}
$unpinned = @()

$null = New-Item -ItemType Directory -Path $CacheDir -Force
if (Test-Path -LiteralPath $OutDir) { Remove-Item -LiteralPath $OutDir -Recurse -Force }
$null = New-Item -ItemType Directory -Path $OutDir -Force
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$lines = @(
    'Source code of the copyleft components in the SAEngine installer',
    '',
    'The SAEngine installer ships these components as compiled binaries. These are the upstream',
    'source archives of exactly those versions, published next to the setup as the licences require.',
    'SAEngine''s own source: see THIRD_PARTY_NOTICES.txt in the installation folder.',
    ''
)
foreach ($source in $manifest.sources) {
    $properties = $source.PSObject.Properties.Name
    if ($properties -contains 'component') {
        if (-not $components.ContainsKey($source.component)) { continue }
        if ($properties -contains 'qt_module' -and $source.qt_module -notin $qtModules) { continue }
    }
    $actualVersion = $shipped[$source.name.ToLowerInvariant()]
    if ($actualVersion -ne $source.version) {
        throw "copyleft-sources.json pins $($source.name) $($source.version), but $actualVersion ships. Update the entry (version, url, file, sha256)."
    }
    $archive = Join-Path $CacheDir $source.file
    if (-not (Test-Path -LiteralPath $archive)) {
        Write-Host "Downloading $($source.url)"
        $partial = "$archive.partial"
        Invoke-WebRequest -Uri $source.url -OutFile $partial -UseBasicParsing
        Move-Item -LiteralPath $partial -Destination $archive -Force
    }
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not $source.sha256) {
        if (-not $AllowUnpinned) {
            Remove-Item -LiteralPath $archive -Force
            throw "copyleft-sources.json has no sha256 for $($source.file) yet (it hashes to $hash). Pin it, or run with -AllowUnpinned."
        }
        Write-Warning "$($source.file) is not pinned: sha256 $hash. Add it to copyleft-sources.json."
        if ($env:GITHUB_ACTIONS) { Write-Host "::warning::Pin $($source.name) in scripts/installer/copyleft-sources.json: sha256 $hash" }
        $unpinned += $source.name
    } elseif ($hash -ne $source.sha256) {
        Remove-Item -LiteralPath $archive -Force
        throw "SHA-256 mismatch for $($source.file) (expected $($source.sha256), got $hash). The download was deleted; run again."
    }
    Copy-Item -LiteralPath $archive -Destination (Join-Path $OutDir $source.file)
    $lines += @(
        "$($source.name) $($source.version) ($($source.license))",
        "  ships in: $($source.ships)",
        "  archive:  $($source.file)",
        "  from:     $($source.url)",
        "  sha256:   $hash$(if (-not $source.sha256) { ' (not pinned in this build: recorded as downloaded)' })",
        ''
    )
    Write-Host "Verified $($source.file)"
}
Set-Content -LiteralPath (Join-Path $OutDir 'README.txt') -Value $lines -Encoding utf8
$size = (Get-ChildItem -LiteralPath $OutDir -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("Copyleft sources ready: {0} ({1:N0} MB)" -f $OutDir, ($size / 1MB))
if ($unpinned.Count -gt 0) { Write-Warning "Not pinned: $($unpinned -join ', ')." }
