# Copyright (c) SAEngine contributors. All rights reserved. Licensed under the AGPL-3.0-only license.
#
# Builds a model in the licensed commercial analysis program through its public .NET API, hidden,
# runs it and writes its results as JSON. Called by compare.ps1; local only, never in CI.
#
#   -InputJson  mirror_input.json or native_input.json (sae_export.py)
#   -OutputJson where the results go
#   -WorkDir    where the program's model files are saved (scratch; never the repository)
#
# Rules: one instance at a time, the API only (never the GUI), always ApplicationExit in finally.
param(
  [Parameter(Mandatory = $true)][string]$InputJson,
  [Parameter(Mandatory = $true)][string]$OutputJson,
  [Parameter(Mandatory = $true)][string]$WorkDir,
  [string]$EtabsDir = "C:\Program Files\Computers and Structures\ETABS 22"
)
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\etabs_lib.ps1"

$PidFile = "$OutputJson.pid"
if (Test-Path $PidFile) { Remove-Item -Force $PidFile }
# a refusal exits 2 (Write-Error would end the script with 1 under ErrorActionPreference Stop)
try { Assert-CanRun $EtabsDir } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 2 }
[void][Reflection.Assembly]::LoadFrom((Join-Path $EtabsDir "ETABSv1.dll"))
$in = Get-Content $InputJson -Raw | ConvertFrom-Json
$mode = $in.mode
New-Item -ItemType Directory -Force $WorkDir | Out-Null
$global:RunLog = New-Object System.Collections.ArrayList
$OBJ = [ETABSv1.eItemType]::Objects
$t0 = Get-Date

function Set-StoriesAndGrid($m) {
  $n = @($in.stories).Count
  if ($n -lt 1) { throw "the model has no storeys above its base" }
  $h1 = [double]$in.stories[0].height
  Check ($m.File.NewGridOnly($n, $h1, $h1, 2, 2, 1.0, 1.0)) "new grid"
  [string[]]$sn = @($in.stories | ForEach-Object { [string]$_.name })
  [double[]]$sh = @($in.stories | ForEach-Object { [double]$_.height })
  [bool[]]$ms = @($in.stories | ForEach-Object { $true })
  [string[]]$sim = @($in.stories | ForEach-Object { "None" })
  [bool[]]$sp = @($in.stories | ForEach-Object { $false })
  [double[]]$sph = @($in.stories | ForEach-Object { 0.0 })
  [int[]]$col = @($in.stories | ForEach-Object { 0 })
  Check ($m.Story.SetStories_2([double]$in.base, $n, [ref]$sn, [ref]$sh, [ref]$ms, [ref]$sim, [ref]$sp, [ref]$sph, [ref]$col)) "storeys"
}

function Add-LoadPatterns($m, [string[]]$names, [bool]$selfWeight) {
  $types = @{ D = "Dead"; DW = "Dead"; SD = "SuperDead"; L = "Live"; Lr = "Rooflive"; F = "Other"; EX = "Quake"; EY = "Quake"; WX = "Wind"; WY = "Wind" }
  [void]$m.LoadPatterns.SetSelfWTMultiplier("Dead", 0)
  foreach ($k in $names) {
    $t = if ($types.ContainsKey($k)) { $types[$k] } else { "Other" }
    $sw = if ($selfWeight -and $k -eq "D") { 1.0 } else { 0.0 }
    Check ($m.LoadPatterns.Add($k, [ETABSv1.eLoadPatternType]::$t, $sw, $true)) "pattern $k"
  }
}

# ----------------------------- mirror: SAEngine's analysis model, node by node -----------------------------
function Build-Mirror($m) {
  Set-StoriesAndGrid $m
  # one material per (E, nu), no weight and no mass (SAEngine applies them as loads and joint masses)
  $mats = @{}
  function Mat($E, $nu) {
    $key = "{0:G6}/{1:G4}" -f $E, $nu
    if (-not $mats.ContainsKey($key)) {
      $name = "MAT$($mats.Count + 1)"
      $t = if ($E -gt 1.0e8) { [ETABSv1.eMatType]::Steel } else { [ETABSv1.eMatType]::Concrete }
      Check ($m.PropMaterial.SetMaterial($name, $t, -1, "", "")) "material"
      Check ($m.PropMaterial.SetMPIsotropic($name, [double]$E, [double]$nu, 1e-5, 0)) "E"
      Check ($m.PropMaterial.SetWeightAndMass($name, 1, 0.0, 0)) "w"
      Check ($m.PropMaterial.SetWeightAndMass($name, 2, 0.0, 0)) "m"
      $mats[$key] = $name
    }
    return $mats[$key]
  }
  foreach ($f in $in.frame_sections) {
    $nu = [Math]::Max(0.0, [Math]::Min(0.49, $f.E / (2 * $f.G) - 1))
    $t3 = [Math]::Sqrt(12 * $f.I33 / $f.A); $t2 = [Math]::Sqrt(12 * $f.I22 / $f.A)
    # As2 = As3 = 0: no shear deformation (OpenSees elasticBeamColumn is Euler-Bernoulli)
    Check ($m.PropFrame.SetGeneral($f.name, (Mat $f.E $nu), $t3, $t2, $f.A, 0, 0, $f.J, $f.I22, $f.I33, $f.I22 / ($t2 / 2), $f.I33 / ($t3 / 2), 0, 0, 0, 0, -1, "", "")) "section $($f.name)"
  }
  foreach ($a in $in.shell_sections) {
    $mat = Mat $a.E $a.nu
    if ($a.wall) { Check ($m.PropArea.SetWall($a.name, [ETABSv1.eWallPropType]::Specified, [ETABSv1.eShellType]::ShellThick, $mat, $a.h, -1, "", "")) "wall $($a.name)" }
    else { Check ($m.PropArea.SetSlab($a.name, [ETABSv1.eSlabType]::Slab, [ETABSv1.eShellType]::ShellThick, $mat, $a.h, -1, "", "")) "slab $($a.name)" }
  }
  foreach ($n in $in.nodes) {
    $nm = ""
    Check ($m.PointObj.AddCartesian([double]$n.xyz[0], [double]$n.xyz[1], [double]$n.xyz[2], [ref]$nm, "N$($n.id)", "Global", $true, 0)) "point $($n.id)"
    if ($nm -ne "N$($n.id)") { L "point name N$($n.id) became $nm" }
    if ($n.restraint -contains $true) { [bool[]]$r = @($n.restraint | ForEach-Object { [bool]$_ }); Check ($m.PointObj.SetRestraint("N$($n.id)", [ref]$r, $OBJ)) "restraint" }
    $mass = @($n.mass | ForEach-Object { [double]$_ })
    if (($mass | Measure-Object -Sum).Sum -gt 0) { [double[]]$mm = $mass; Check ($m.PointObj.SetMass("N$($n.id)", [ref]$mm, $OBJ, $false, $true)) "mass" }
  }
  L "points added"
  foreach ($f in $in.frames) {
    $nm = ""
    Check ($m.FrameObj.AddByPoint("N$($f.i)", "N$($f.j)", [ref]$nm, $f.sec, $f.name)) "frame $($f.name)"
    # SAEngine's local axes (a skewed column's vecxz, a sloped member in a vertical YZ plane)
    if ($f.angle -and [Math]::Abs([double]$f.angle) -gt 1e-6) { Check ($m.FrameObj.SetLocalAxes($f.name, [double]$f.angle, $OBJ)) "angle $($f.name)" }
    if ($f.offsets) {
      $o = @($f.offsets | ForEach-Object { [double]$_ })
      $l1 = [Math]::Sqrt($o[0] * $o[0] + $o[1] * $o[1] + $o[2] * $o[2]); $l2 = [Math]::Sqrt($o[3] * $o[3] + $o[4] * $o[4] + $o[5] * $o[5])
      Check ($m.FrameObj.SetEndLengthOffset($f.name, $false, $l1, $l2, 1.0, $OBJ)) "rigid offsets"
    } else { Check ($m.FrameObj.SetEndLengthOffset($f.name, $false, 0, 0, 0, $OBJ)) "no offsets" }
    if ($f.relI -or $f.relJ) {
      [bool[]]$ii = @($false, $false, $false, $false, $false, $false); [bool[]]$jj = @($false, $false, $false, $false, $false, $false)
      foreach ($d in @($f.relI)) { if ($d) { $ii[[int]$d - 1] = $true } }
      foreach ($d in @($f.relJ)) { if ($d) { $jj[[int]$d - 1] = $true } }
      if ($ii[3] -and $jj[3]) { $ii[3] = $false }  # torsion released at one end only
      [double[]]$z1 = @(0, 0, 0, 0, 0, 0); [double[]]$z2 = @(0, 0, 0, 0, 0, 0)
      Check ($m.FrameObj.SetReleases($f.name, [ref]$ii, [ref]$jj, [ref]$z1, [ref]$z2, $OBJ)) "releases $($f.name)"
    }
  }
  foreach ($k in $in.links) {
    [bool[]]$dof = @($true, (-not $k.pinned), (-not $k.pinned), (-not $k.pinned), (-not $k.pinned), (-not $k.pinned))
    [bool[]]$fix = @($false, $false, $false, $false, $false, $false)
    [double[]]$ke = @($k.k | ForEach-Object { [double]$_ }); [double[]]$ce = @(0, 0, 0, 0, 0, 0)
    Check ($m.PropLink.SetLinear("P$($k.name)", [ref]$dof, [ref]$fix, [ref]$ke, [ref]$ce, 0, 0, $false, $false, "", "")) "link property"
    $ln = ""; Check ($m.LinkObj.AddByPoint("N$($k.i)", "N$($k.j)", [ref]$ln, $false, "P$($k.name)", $k.name)) "link $($k.name)"
  }
  L "frames and links added"
  foreach ($a in $in.shells) {
    $nm = ""; [string[]]$pts = @($a.nodes | ForEach-Object { "N$_" })
    Check ($m.AreaObj.AddByPoint($pts.Count, [ref]$pts, [ref]$nm, $a.sec, $a.name)) "area $($a.name)"
  }
  $k = 0
  foreach ($d in $in.diaphragms) {
    [void]$m.Diaphragm.SetDiaphragm($d.name, $false)  # D1 exists already: ret 1
    foreach ($p in $d.nodes) { Check ($m.PointObj.SetDiaphragm("N$p", [ETABSv1.eDiaphragmOption]::DefinedDiaphragm, $d.name)) "point diaphragm" }
    $k++
  }
  # mass source: the joint masses only, lumped as given (the other program's lumping off)
  $ie = $false; $ia = $true; $il = $false; [string[]]$lp = @(); [double[]]$sf = @()
  Check ($m.PropMaterial.SetMassSource_1([ref]$ie, [ref]$ia, [ref]$il, 0, [ref]$lp, [ref]$sf)) "mass source"
  L (Edit-Table $m "Mass Source Definition" "LumpMass" "No")
  $names = @($in.loads.PSObject.Properties.Name)
  Add-LoadPatterns $m $names $false
  foreach ($p in $names) {
    foreach ($x in $in.loads.$p) { [double[]]$lv = @($x.f | ForEach-Object { [double]$_ }); Check ($m.PointObj.SetLoadForce("N$($x.node)", $p, [ref]$lv, $false, "Global", $OBJ)) "load $p" }
    foreach ($x in $in.elem_loads.$p) {
      if ($x.frame -like "LK*") {
        # a link takes no span load: half to each end
        foreach ($e in $x.ends) { [double[]]$lv = @(($x.g[0] * $x.length / 2), ($x.g[1] * $x.length / 2), ($x.g[2] * $x.length / 2), 0, 0, 0); Check ($m.PointObj.SetLoadForce("N$e", $p, [ref]$lv, $false, "Global", $OBJ)) "link load" }
        continue
      }
      # over the flexible length only: SAEngine already put the rigid zones' share on the joints
      $d0 = if ($null -ne $x.d0) { [double]$x.d0 } else { 0.0 }; $d1 = if ($null -ne $x.d1) { [double]$x.d1 } else { 1.0 }
      for ($d = 0; $d -lt 3; $d++) { $g = [double]$x.g[$d]; if ([Math]::Abs($g) -gt 1e-12) { Check ($m.FrameObj.SetLoadDistributed($x.frame, $p, 1, 4 + $d, $d0, $d1, $g, $g, "Global", $true, $false, $OBJ)) "span load" } }
    }
  }
  # the mesh is SAEngine's: no automatic floor or wall meshing
  L (Edit-Table $m "Area Assignments - Floor Auto Mesh Options" "MeshOption" "No Auto Mesh")
  L (Edit-Table $m "Analysis Options - Automatic Rectangular Mesh Options for Walls" "MaxMeshSize" "100")
}

# ----------------------------- native: the physical model, drawn the program's way -----------------------------
function Build-Native($m) {
  Set-StoriesAndGrid $m
  foreach ($x in $in.materials) {
    $t = switch ($x.type) { "steel" { [ETABSv1.eMatType]::Steel } "concrete" { [ETABSv1.eMatType]::Concrete } default { [ETABSv1.eMatType]::NoDesign } }
    Check ($m.PropMaterial.SetMaterial($x.name, $t, -1, "", "")) "material $($x.name)"
    Check ($m.PropMaterial.SetMPIsotropic($x.name, [double]$x.E, [double]$x.nu, 1e-5, 0)) "E"
    Check ($m.PropMaterial.SetWeightAndMass($x.name, 1, [double]$x.w, 0)) "weight"
  }
  foreach ($s in $in.frame_sections) {
    if ($s.shape -eq "rect") { Check ($m.PropFrame.SetRectangle($s.name, $s.mat, [double]$s.t3, [double]$s.t2, -1, "", "")) "rectangle $($s.name)" }
    else {
      $t3 = [Math]::Sqrt(12 * $s.I33 / $s.A); $t2 = [Math]::Sqrt(12 * $s.I22 / $s.A)
      Check ($m.PropFrame.SetGeneral($s.name, $s.mat, $t3, $t2, $s.A, 0, 0, $s.J, $s.I22, $s.I33, $s.I22 / ($t2 / 2), $s.I33 / ($t3 / 2), 0, 0, 0, 0, -1, "", "")) "general $($s.name)"
    }
  }
  foreach ($s in $in.area_sections) {
    if ($s.kind -eq "wall") { Check ($m.PropArea.SetWall($s.name, [ETABSv1.eWallPropType]::Specified, [ETABSv1.eShellType]::ShellThin, $s.mat, [double]$s.t, -1, "", "")) "wall $($s.name)" }
    else { Check ($m.PropArea.SetSlab($s.name, [ETABSv1.eSlabType]::Slab, ([ETABSv1.eShellType][string]$s.shell), $s.mat, [double]$s.t, -1, "", "")) "slab $($s.name)" }
  }
  foreach ($f in $in.frames) {
    $nm = ""
    Check ($m.FrameObj.AddByCoord([double]$f.i[0], [double]$f.i[1], [double]$f.i[2], [double]$f.j[0], [double]$f.j[1], [double]$f.j[2], [ref]$nm, $f.sec, $f.name, "Global")) "frame $($f.name)"
    if ($nm -ne $f.name) { L "frame $($f.name) became $nm" }
    if ([double]$f.angle -ne 0) { Check ($m.FrameObj.SetLocalAxes($nm, [double]$f.angle, $OBJ)) "angle $($f.name)" }
    # SAEngine's rigid end zones (D3): automatic end offsets with the same rigid-zone factor
    if ($null -ne $in.rigidZoneFactor) { Check ($m.FrameObj.SetEndLengthOffset($nm, $true, 0, 0, [double]$in.rigidZoneFactor, $OBJ)) "end offsets $($f.name)" }
    if ($f.pinned) {
      [bool[]]$ii = @($false, $false, $false, $false, $true, $true); [bool[]]$jj = @($false, $false, $false, $true, $true, $true)
      [double[]]$z1 = @(0, 0, 0, 0, 0, 0); [double[]]$z2 = @(0, 0, 0, 0, 0, 0)
      Check ($m.FrameObj.SetReleases($nm, [ref]$ii, [ref]$jj, [ref]$z1, [ref]$z2, $OBJ)) "pinned $($f.name)"
    }
  }
  foreach ($k in $in.links) {
    [bool[]]$dof = @($true, $false, $false, $false, $false, $false); [bool[]]$fix = @($false, $false, $false, $false, $false, $false)
    [double[]]$ke = @($k.k | ForEach-Object { [double]$_ }); [double[]]$ce = @(0, 0, 0, 0, 0, 0)
    Check ($m.PropLink.SetLinear("P$($k.name)", [ref]$dof, [ref]$fix, [ref]$ke, [ref]$ce, 0, 0, $false, $false, "", "")) "link property"
    $p1 = ""; $p2 = ""
    Check ($m.PointObj.AddCartesian([double]$k.i[0], [double]$k.i[1], [double]$k.i[2], [ref]$p1, "", "Global", $false, 0)) "link point"
    Check ($m.PointObj.AddCartesian([double]$k.j[0], [double]$k.j[1], [double]$k.j[2], [ref]$p2, "", "Global", $false, 0)) "link point"
    $ln = ""; Check ($m.LinkObj.AddByPoint($p1, $p2, [ref]$ln, $false, "P$($k.name)", $k.name)) "link $($k.name)"
  }
  if ($null -ne $in.rigidZoneFactor) {
    # the API ignores the factor of automatic offsets: set it in the assignments table
    L (Edit-TableField $m "Frame Assignments - End Length Offsets" "Rigid|RZ" ("{0:G6}" -f [double]$in.rigidZoneFactor))
  }
  $diaphragm = $false
  foreach ($a in $in.areas) {
    [double[]]$xs = @($a.pts | ForEach-Object { [double]$_[0] }); [double[]]$ys = @($a.pts | ForEach-Object { [double]$_[1] }); [double[]]$zs = @($a.pts | ForEach-Object { [double]$_[2] })
    $nm = ""; Check ($m.AreaObj.AddByCoord($xs.Count, [ref]$xs, [ref]$ys, [ref]$zs, [ref]$nm, $a.sec, $a.name, "Global")) "area $($a.name)"
    $a | Add-Member -NotePropertyName etabs -NotePropertyValue $nm -Force
    foreach ($o in $a.openings) {
      [double[]]$ox = @($o | ForEach-Object { [double]$_[0] }); [double[]]$oy = @($o | ForEach-Object { [double]$_[1] }); [double[]]$oz = @($o | ForEach-Object { [double]$_[2] })
      $on = ""; Check ($m.AreaObj.AddByCoord($ox.Count, [ref]$ox, [ref]$oy, [ref]$oz, [ref]$on, $a.sec, "", "Global")) "opening"
      Check ($m.AreaObj.SetOpening($on, $true, $OBJ)) "opening $($a.name)"
    }
    if ($a.diaphragm) {
      if (-not $diaphragm) { [void]$m.Diaphragm.SetDiaphragm("D1", $false); $diaphragm = $true }
      Check ($m.AreaObj.SetDiaphragm($nm, "D1")) "diaphragm $($a.name)"
    }
  }
  foreach ($r in $in.restraints) {
    $pn = ""; Check ($m.PointObj.AddCartesian([double]$r.xyz[0], [double]$r.xyz[1], [double]$r.xyz[2], [ref]$pn, "", "Global", $false, 0)) "support point"
    [bool[]]$rv = @($r.r | ForEach-Object { [bool]$_ }); Check ($m.PointObj.SetRestraint($pn, [ref]$rv, $OBJ)) "support"
  }
  Add-LoadPatterns $m @("D", "DW", "SD", "L", "Lr", "F", "EX", "EY") $true
  foreach ($a in $in.areas) {
    foreach ($p in $a.loads.PSObject.Properties) {
      if ([double]$p.Value -ne 0) { Check ($m.AreaObj.SetLoadUniform($a.etabs, $p.Name, [double]$p.Value, 10, $false, "Global", $OBJ)) "area load $($a.name) $($p.Name)" }
    }
  }
  foreach ($x in $in.frame_loads) {
    Check ($m.FrameObj.SetLoadDistributed($x.frame, $x.case, 1, 10, [double]$x.d0, [double]$x.d1, [double]$x.w, [double]$x.w, "Global", $true, $false, $OBJ)) "line load $($x.frame)"
  }
  foreach ($x in $in.point_loads) {
    $pn = ""; Check ($m.PointObj.AddCartesian([double]$x.xyz[0], [double]$x.xyz[1], [double]$x.xyz[2], [ref]$pn, "", "Global", $false, 0)) "load point"
    [double[]]$lv = @(0, 0, [double]$x.fz, 0, 0, 0); Check ($m.PointObj.SetLoadForce($pn, $x.case, [ref]$lv, $false, "Global", $OBJ)) "point load $($x.source)"
  }
  # mass source: element self mass + the load patterns with SAEngine's seismic shares
  $ie = $true; $ia = $true; $il = $true
  [string[]]$lp = @($in.mass_source.patterns.PSObject.Properties.Name)
  [double[]]$sf = @($in.mass_source.patterns.PSObject.Properties | ForEach-Object { [double]$_.Value })
  Check ($m.PropMaterial.SetMassSource_1([ref]$ie, [ref]$ia, [ref]$il, $lp.Count, [ref]$lp, [ref]$sf)) "mass source"
  # static earthquake: user coefficient C = SAEngine's Sa, exponent k, no eccentricity
  $v = 0; $nf = 0; [string[]]$k2 = @(); [string[]]$fn = @(); [string[]]$d = @(); [string[]]$u = @(); [bool[]]$imp = @()
  [void]$m.DatabaseTables.GetAllFieldsInTable("Load Pattern Definitions - Auto Seismic - User Coefficient", [ref]$v, [ref]$nf, [ref]$k2, [ref]$fn, [ref]$d, [ref]$u, [ref]$imp)
  [string[]]$td = @()
  foreach ($pat in @("EX", "EY")) {
    $row = @{ Name = $pat; IsAuto = "No"; XDir = $(if ($pat -eq "EX") { "Yes" } else { "No" }); XDirPlusE = "No"; XDirMinusE = "No"; YDir = $(if ($pat -eq "EY") { "Yes" } else { "No" }); YDirPlusE = "No"; YDirMinusE = "No"; EccRatio = "0"; TopStory = [string]$in.seismic.top; BotStory = "Base"; OverStory = ""; OverDiaph = ""; OverEcc = ""; C = ("{0:G10}" -f [double]$in.seismic.C); K = ("{0:G6}" -f [double]$in.seismic.K) }
    foreach ($f in $k2) { $td += [string]$row[$f] }
  }
  $tv = $v; [string[]]$fk = $k2
  Check ($m.DatabaseTables.SetTableForEditingArray("Load Pattern Definitions - Auto Seismic - User Coefficient", [ref]$tv, [ref]$fk, 2, [ref]$td)) "seismic table"
  $fe = 0; $ne = 0; $nw = 0; $ni = 0; $il2 = ""
  Check ($m.DatabaseTables.ApplyEditedTables($true, [ref]$fe, [ref]$ne, [ref]$nw, [ref]$ni, [ref]$il2)) "seismic apply"
  L "auto seismic C=$($in.seismic.C) K=$($in.seismic.K): fatal=$fe errors=$ne warnings=$nw"
  if ($fe -gt 0 -or $ne -gt 0) { L $il2 }
}

function Set-Modifiers($m, $group) {
  if ($mode -eq "mirror") {
    $mods = $group.modifiers
    foreach ($f in $in.frames) {
      [double[]]$mv = if ($mods.PSObject.Properties.Name -contains $f.sec) { @($mods.($f.sec) | ForEach-Object { [double]$_ }) } else { @(1, 1, 1, 1, 1, 1, 1, 1) }
      Check ($m.FrameObj.SetModifiers($f.name, [ref]$mv, $OBJ)) "frame modifiers"
    }
    foreach ($a in $in.shells) {
      [double[]]$mv = if ($mods.PSObject.Properties.Name -contains $a.sec) { @($mods.($a.sec) | ForEach-Object { [double]$_ }) } else { @(1, 1, 1, 1, 1, 1, 1, 1, 1, 1) }
      Check ($m.AreaObj.SetModifiers($a.name, [ref]$mv, $OBJ)) "area modifiers"
    }
  } else {
    $fm = $in.modifiers.frames; $am = $in.modifiers.areas
    foreach ($f in $in.frames) {
      [double[]]$mv = if ($group.cracked -and ($fm.PSObject.Properties.Name -contains $f.sec)) { @($fm.($f.sec) | ForEach-Object { [double]$_ }) } else { @(1, 1, 1, 1, 1, 1, 1, 1) }
      Check ($m.FrameObj.SetModifiers($f.name, [ref]$mv, $OBJ)) "frame modifiers"
    }
    foreach ($a in $in.areas) {
      [double[]]$mv = if ($group.cracked -and ($am.PSObject.Properties.Name -contains $a.sec)) { @($am.($a.sec) | ForEach-Object { [double]$_ }) } else { @(1, 1, 1, 1, 1, 1, 1, 1, 1, 1) }
      Check ($m.AreaObj.SetModifiers($a.etabs, [ref]$mv, $OBJ)) "area modifiers"
    }
  }
}

$out = [ordered]@{ program = "commercial"; mode = $mode; runs = @(); log = $global:RunLog }
try {
  $m = Start-Etabs $EtabsDir
  # the process this run started: the only one the caller may stop if the run dies
  if ($global:EtabsPid) { Set-Content -Encoding ascii -Path $PidFile -Value "$($global:EtabsPid) $($global:EtabsStart.ToString('o'))" }
  L "program started (hidden, pid $($global:EtabsPid))"
  Check ($m.InitializeNewModel([ETABSv1.eUnits]::kN_m_C)) "new model"
  if ($mode -eq "mirror") { Build-Mirror $m } else { Build-Native $m }
  Check ($m.LoadCases.ModalEigen.SetCase("Modal")) "modal case"
  Check ($m.LoadCases.ModalEigen.SetNumberModes("Modal", [int]$in.modal, 1)) "modes"
  L ("built in {0:N0} s" -f ((Get-Date) - $t0).TotalSeconds)
  $k = 0
  foreach ($g in $in.groups) {
    $k++
    if ($k -gt 1) { Check ($m.SetModelIsLocked($false)) "unlock" }
    Set-Modifiers $m $g
    L "run ${k}: modifiers set"
    $file = Join-Path $WorkDir "$mode-run$k.edb"
    Check ($m.File.Save($file)) "save"
    L "run ${k}: saved"
    Check ($m.Analyze.RunAnalysis()) "run $k"
    $cases = @($g.patterns | ForEach-Object { [string]$_ })
    if ($g.modal) { $cases += "Modal" }
    L ("run $k ($($cases -join ',')) analysed; analysis model {0} area / {1} line / {2} point elements" -f $m.AreaElm.Count(), $m.LineElm.Count(), $m.PointElm.Count())
    $r = Get-Results $m $cases $in.probes
    L "run ${k}: results read"
    $r.cracked = [bool]$(if ($mode -eq "mirror") { @($g.modifiers.PSObject.Properties).Count -gt 0 } else { $g.cracked })
    $r.patterns = @($g.patterns); $r.modal_run = [bool]$g.modal
    $out.runs += $r
  }
} catch {
  L "FAILED: $($_.Exception.Message) at $($_.InvocationInfo.PositionMessage)"
  $out.error = $_.Exception.Message
} finally {
  Stop-Etabs
  # wait for the run's own process to close; stop it (and only it) if ApplicationExit did not
  if ($global:EtabsPid) {
    $deadline = (Get-Date).AddSeconds(60)
    while ((Get-Process -Id $global:EtabsPid -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
    if (Get-Process -Id $global:EtabsPid -ErrorAction SilentlyContinue) { L (Stop-OwnEtabs $PidFile) }
  }
  $out.seconds = ((Get-Date) - $t0).TotalSeconds
  $out | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $OutputJson
}
if ($out.error) { exit 3 }
