# Copyright (c) SAEngine contributors. All rights reserved. Licensed under the AGPL-3.0-only license.
#
# Cross-checks a SAEngine project against a licensed commercial analysis program (local only).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\etabs_compare\compare.ps1 `
#       -Project "<project folder>" -Out "<output folder>" [-Mode mirror|native|both] [-Members C4,B1]
#
# 1. copies the project into <Out>\work (the original is never touched) and runs SAEngine headless on
#    the copy (saengine run-all --steps derive analysis);
# 2. exports SAEngine's results and the model to send (sae_export.py);
# 3. builds the same model in the reference program through its .NET API, hidden, runs it and reads its
#    results (etabs_run.ps1);
# 4. compares them (compare.py): <Out>\<mode>\report.md and results.json, PASS/FLAG per quantity.
#
# Refuses to run in CI, without the program installed or while an instance of it is running.
param(
  [Parameter(Mandatory = $true)][string]$Project,
  [Parameter(Mandatory = $true)][string]$Out,
  [ValidateSet("mirror", "native", "both")][string]$Mode = "both",
  [string]$Members = "",
  [string]$Python = "",
  [string]$EtabsDir = "C:\Program Files\Computers and Structures\ETABS 22",
  [switch]$SkipSaengine
)
$ErrorActionPreference = "Continue"  # native tools report through their exit codes
. "$PSScriptRoot\etabs_lib.ps1"

$ci = Test-CI
if ($ci) { Write-Error "refusing to run: this harness never runs in CI ($ci is set)"; exit 2 }
if (-not (Test-Path (Join-Path $EtabsDir "ETABSv1.dll"))) { Write-Error "refusing to run: no licensed analysis program at $EtabsDir"; exit 2 }
if (Get-Process -Name "ETABS" -ErrorAction SilentlyContinue) { Write-Error "refusing to run: an instance is already running (one at a time)"; exit 2 }

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $Python) { $Python = Join-Path $repo ".venv\Scripts\python.exe" }
$src = (Resolve-Path $Project).Path
if ($src -like "*.saengine") { $src = Split-Path $src -Parent }
New-Item -ItemType Directory -Force $Out | Out-Null
$Out = (Resolve-Path $Out).Path
if ($Out.StartsWith($repo, [StringComparison]::OrdinalIgnoreCase)) { Write-Error "refusing to write into the repository: choose -Out outside $repo"; exit 2 }
$name = Split-Path $src -Leaf
$work = Join-Path $Out "work\$name"
$data = Join-Path $Out "data"
New-Item -ItemType Directory -Force $data | Out-Null

if (-not $SkipSaengine) {
  if (Test-Path $work) { Remove-Item -Recurse -Force $work }
  New-Item -ItemType Directory -Force (Split-Path $work -Parent) | Out-Null
  Copy-Item -Recurse $src $work
  # the copy derives and analyses afresh
  foreach ($f in @("08 FEM\model.osmodel", "08 FEM\model.results")) { $p = Join-Path $work $f; if (Test-Path $p) { Remove-Item -Recurse -Force $p } }
  & $Python (Join-Path $PSScriptRoot "sae_export.py") --project $work --out $data --members $Members
  if ($LASTEXITCODE -ne 0) { Write-Error "SAEngine export failed ($LASTEXITCODE)"; exit 3 }
}

$modes = if ($Mode -eq "both") { @("mirror", "native") } else { @($Mode) }
$date = Get-Date -Format "yyyy-MM-dd HH:mm"
$status = 0
foreach ($md in $modes) {
  $dir = Join-Path $Out $md
  New-Item -ItemType Directory -Force $dir | Out-Null
  $ref = Join-Path $data "reference_$md.json"
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "etabs_run.ps1") -InputJson (Join-Path $data "${md}_input.json") -OutputJson $ref -WorkDir (Join-Path $Out "models\$md") -EtabsDir $EtabsDir
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "the reference run ($md) reported an error; see $ref"; $status = 3
    # a run that died without closing the program: stop only the program's own process
    Get-Process -Name "ETABS" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  }
  & $Python (Join-Path $PSScriptRoot "compare.py") --saengine (Join-Path $data "saengine.json") --reference $ref --input (Join-Path $data "${md}_input.json") --out $dir --project $name --date $date
  if ($LASTEXITCODE -ne 0) { $status = 3 }
  Write-Host "report: $(Join-Path $dir 'report.md')"
}
exit $status
