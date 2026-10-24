# Copyright (c) SAEngine contributors. All rights reserved. Licensed under the AGPL-3.0-only license.
#
# Helpers for driving the licensed commercial analysis program through its public .NET API, hidden.
# Dot-sourced by etabs_run.ps1. Local only: never in CI, never the GUI, one instance at a time.

$global:LogStart = Get-Date
function L([string]$t) {
  $line = "[{0,5:N0} s] {1}" -f ((Get-Date) - $global:LogStart).TotalSeconds, $t
  if ($null -ne $global:RunLog) { [void]$global:RunLog.Add($line) }
  Write-Host $line
}
function Check($ret, [string]$what) { if ($ret -ne 0) { L "WARN ret=$ret : $what" } }

function Test-CI {
  foreach ($v in @("CI", "GITHUB_ACTIONS", "TF_BUILD", "BUILD_BUILDID", "JENKINS_URL", "GITLAB_CI")) {
    if ([Environment]::GetEnvironmentVariable($v)) { return $v }
  }
  return $null
}

# Refuses to run in CI, without the program installed, or while another instance runs (the licence
# allows one at a time).
function Assert-CanRun([string]$EtabsDir) {
  $ci = Test-CI
  if ($ci) { throw "refusing to run: this harness never runs in CI ($ci is set)" }
  if (-not (Test-Path (Join-Path $EtabsDir "ETABSv1.dll"))) { throw "refusing to run: no licensed analysis program at $EtabsDir (ETABSv1.dll missing)" }
  if (Get-Process -Name "ETABS" -ErrorAction SilentlyContinue) { throw "refusing to run: an instance is already running (the licence allows one at a time)" }
}

function Start-Etabs([string]$EtabsDir) {
  [void][Reflection.Assembly]::LoadFrom((Join-Path $EtabsDir "ETABSv1.dll"))
  $helper = New-Object ETABSv1.Helper
  $global:etabs = $helper.CreateObjectProgID("CSI.ETABS.API.ETABSObject")
  [void]$global:etabs.ApplicationStart()
  [void]$global:etabs.Hide()
  return $global:etabs.SapModel
}

function Stop-Etabs {
  if ($global:etabs) { try { [void]$global:etabs.ApplicationExit($false) } catch { L "ApplicationExit: $($_.Exception.Message)" }; $global:etabs = $null }
}

# Edits one field of every row of an editable database table, applies it and returns the log line.
function Edit-Table($m, [string]$key, [string]$field, [string]$value) {
  $tv = 0; [string[]]$fk = @(); $nr = 0; [string[]]$td = @()
  $r = $m.DatabaseTables.GetTableForEditingArray($key, "", [ref]$tv, [ref]$fk, [ref]$nr, [ref]$td)
  if ($r -ne 0) { return "get $key failed ($r)" }
  $nf = $fk.Count; $io = [Array]::IndexOf($fk, $field)
  if ($io -lt 0) { [void]$m.DatabaseTables.CancelTableEditing(); return "no field $field in $key" }
  for ($q = 0; $q -lt $nr; $q++) { $td[$q * $nf + $io] = $value }
  $r = $m.DatabaseTables.SetTableForEditingArray($key, [ref]$tv, [ref]$fk, $nr, [ref]$td)
  if ($r -ne 0) { [void]$m.DatabaseTables.CancelTableEditing(); return "set $key failed ($r)" }
  $fe = 0; $ne = 0; $nw = 0; $ni = 0; $il = ""
  $r = $m.DatabaseTables.ApplyEditedTables($true, [ref]$fe, [ref]$ne, [ref]$nw, [ref]$ni, [ref]$il)
  return "edit $key.$field=$value rows=$nr ret=$r fatal=$fe errors=$ne warnings=$nw"
}

function Get-FrameRows($m, [string]$name) {
  $n = 0; [string[]]$ob = @(); [double[]]$os = @(); [string[]]$el = @(); [double[]]$es = @(); [string[]]$lc = @(); [string[]]$st = @(); [double[]]$sn = @()
  [double[]]$P = @(); [double[]]$V2 = @(); [double[]]$V3 = @(); [double[]]$Tq = @(); [double[]]$M2 = @(); [double[]]$M3 = @()
  $ret = $m.Results.FrameForce($name, [ETABSv1.eItemTypeElm]::ObjectElm, [ref]$n, [ref]$ob, [ref]$os, [ref]$el, [ref]$es, [ref]$lc, [ref]$st, [ref]$sn, [ref]$P, [ref]$V2, [ref]$V3, [ref]$Tq, [ref]$M2, [ref]$M3)
  if ($ret -ne 0) { L "FrameForce $name ret=$ret" }
  return @(for ($i = 0; $i -lt $n; $i++) { [ordered]@{ case = $lc[$i]; sta = $os[$i]; P = $P[$i]; V2 = $V2[$i]; V3 = $V3[$i]; T = $Tq[$i]; M2 = $M2[$i]; M3 = $M3[$i] } })
}

# Results of the cases of one run: modal, base reactions, the probed frames and the storey tables.
function Get-Results($m, [string[]]$cases, $probes) {
  $R = [ordered]@{ cases = $cases }
  [void]$m.Results.Setup.DeselectAllCasesAndCombosForOutput()
  foreach ($c in $cases) { [void]$m.Results.Setup.SetCaseSelectedForOutput($c, $true) }
  if ($cases -contains "Modal") {
    $n = 0; [string[]]$lc = @(); [string[]]$st = @(); [double[]]$sn = @(); [double[]]$T = @(); [double[]]$ux = @(); [double[]]$uy = @(); [double[]]$uz = @(); [double[]]$sux = @(); [double[]]$suy = @(); [double[]]$suz = @(); [double[]]$rx = @(); [double[]]$ry = @(); [double[]]$rz = @(); [double[]]$srx = @(); [double[]]$sry = @(); [double[]]$srz = @()
    [void]$m.Results.ModalParticipatingMassRatios([ref]$n, [ref]$lc, [ref]$st, [ref]$sn, [ref]$T, [ref]$ux, [ref]$uy, [ref]$uz, [ref]$sux, [ref]$suy, [ref]$suz, [ref]$rx, [ref]$ry, [ref]$rz, [ref]$srx, [ref]$sry, [ref]$srz)
    $R.modal = @(for ($i = 0; $i -lt $n; $i++) { [ordered]@{ mode = $sn[$i]; T = $T[$i]; UX = $ux[$i]; UY = $uy[$i]; RZ = $rz[$i]; SumUX = $sux[$i]; SumUY = $suy[$i] } })
  }
  $n = 0; [string[]]$lc = @(); [string[]]$st = @(); [double[]]$sn = @(); [double[]]$fx = @(); [double[]]$fy = @(); [double[]]$fz = @(); [double[]]$mx = @(); [double[]]$my = @(); [double[]]$mz = @(); $gx = 0.0; $gy = 0.0; $gz = 0.0
  [void]$m.Results.BaseReact([ref]$n, [ref]$lc, [ref]$st, [ref]$sn, [ref]$fx, [ref]$fy, [ref]$fz, [ref]$mx, [ref]$my, [ref]$mz, [ref]$gx, [ref]$gy, [ref]$gz)
  $R.base = @(for ($i = 0; $i -lt $n; $i++) { [ordered]@{ case = $lc[$i]; step = $sn[$i]; FX = $fx[$i]; FY = $fy[$i]; FZ = $fz[$i]; MX = $mx[$i]; MY = $my[$i]; MZ = $mz[$i] } })
  $R.frames = [ordered]@{}
  foreach ($p in $probes) {
    $first = Get-FrameRows $m $p.first
    $last = if ($p.last -eq $p.first) { $first } else { Get-FrameRows $m $p.last }
    $R.frames[$p.label] = [ordered]@{ first = $first; last = $last; lastStart = $p.lastStart }
  }
  [string[]]$sel = $cases
  [void]$m.DatabaseTables.SetLoadCasesSelectedForDisplay([ref]$sel)
  $R.tables = [ordered]@{}
  foreach ($k in @("Story Forces", "Diaphragm Center Of Mass Displacements", "Mass Summary by Story", "Load Pattern Definitions - Auto Seismic - User Coefficient", "Auto Seismic - User Coefficients")) {
    [string[]]$fl = @(); $v = 0; $csv = ""
    $ret = $m.DatabaseTables.GetTableForDisplayCSVString($k, [ref]$fl, "", [ref]$v, [ref]$csv, ",")
    $R.tables[$k] = [ordered]@{ ret = $ret; csv = $csv }
  }
  return $R
}
