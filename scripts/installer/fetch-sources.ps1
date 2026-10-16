<#
.SYNOPSIS
    Collects the source archives of the copyleft components that the installer ships as binaries.

.DESCRIPTION
    gmsh (GPL-2.0+), ifcopenshell and cytriangle (LGPL-3.0) and web-ifc (MPL-2.0) ship as
    compiled binaries. Their licences require the distributor to make the corresponding source
    available: build-installer.ps1 puts these archives in a folder next to the setup, and they
    are published from the same place as the setup (see docs\install\README.md).

    The archives are listed in scripts\installer\copyleft-sources.json with pinned SHA-256
    hashes. Each is downloaded once into <CacheDir> and checked. The script fails when a pinned
    version differs from the version that ships (constraints.txt, the fem-viewer's web-ifc), so
    a dependency upgrade cannot silently leave an outdated source archive.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][string]$CacheDir,
    [Parameter(Mandatory = $true)][string]$OutDir
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
    if ($hash -ne $source.sha256) {
        Remove-Item -LiteralPath $archive -Force
        throw "SHA-256 mismatch for $($source.file) (expected $($source.sha256), got $hash). The download was deleted; run again."
    }
    Copy-Item -LiteralPath $archive -Destination (Join-Path $OutDir $source.file)
    $lines += @(
        "$($source.name) $($source.version) ($($source.license))",
        "  ships in: $($source.ships)",
        "  archive:  $($source.file)",
        "  from:     $($source.url)",
        "  sha256:   $hash",
        ''
    )
    Write-Host "Verified $($source.file)"
}
Set-Content -LiteralPath (Join-Path $OutDir 'README.txt') -Value $lines -Encoding utf8
$size = (Get-ChildItem -LiteralPath $OutDir -File | Measure-Object -Property Length -Sum).Sum
Write-Host ("Copyleft sources ready: {0} ({1:N0} MB)" -f $OutDir, ($size / 1MB))
