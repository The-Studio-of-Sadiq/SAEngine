"""The patterns real ETABS 22 exports use, each reproduced in a small synthetic e2k model.

The model (written by hand for these tests, N and mm): two stories (L1 at 3200 mm, L2 at
6200 mm) on grids A-B (0, 6000) and 1-2 (0, 5000); 400x600 columns with their bars as a pattern
and the area of one bar; two floor slabs at L1 with different superimposed dead loads (one a
tank) and a roof slab; a wall on grid B round a door, drawn as ETABS draws it (two full-height
panels and a lintel panel whose lower corners sit below the story); a library steel beam pinned
at both ends; property modifiers, offsets, a fluid pattern, point and frame loads, a mass source,
a user-coefficient seismic definition and a pier label.
"""

from __future__ import annotations

import pytest

from saengine.importers.etabs import read_e2k
from saengine.importers.neutral import estimated_i_shape, named_profile
from saengine.importers.project import section_lookup_noted
from saengine.importers.shapes import ProfileTable, shape_key, table_lookup

MODEL = """
$ PROGRAM INFORMATION
  PROGRAM  "ETABS"  VERSION "22.5.0"
$ CONTROLS
  UNITS  "N"  "MM"  "C"
$ STORIES - IN SEQUENCE FROM TOP
  STORY "L2"  HEIGHT 3000
  STORY "L1"  HEIGHT 3200
  STORY "Base"  ELEV 0
$ GRIDS
  GRIDSYSTEM "G1"  TYPE "CARTESIAN"
  GRID "G1"  LABEL "A"  DIR "X"  COORD 0
  GRID "G1"  LABEL "B"  DIR "X"  COORD 6000
  GRID "G1"  LABEL "1"  DIR "Y"  COORD 0
  GRID "G1"  LABEL "2"  DIR "Y"  COORD 5000
$ MATERIAL PROPERTIES
  MATERIAL  "C30"  TYPE "Concrete"  WEIGHTPERVOLUME 2.35E-05
  MATERIAL  "C30"  SYMTYPE "Isotropic"  E 25000  U 0.2  A 0.0000099
  MATERIAL  "C30"  FC 30
  MATERIAL  "B420"  TYPE "Rebar"  WEIGHTPERVOLUME 7.7E-05
  MATERIAL  "B420"  SYMTYPE "Uniaxial"  E 200000  A 0.0000117
  MATERIAL  "B420"  FY 420  FU 620
  MATERIAL  "A992"  TYPE "Steel"  WEIGHTPERVOLUME 7.7E-05
  MATERIAL  "A992"  SYMTYPE "Isotropic"  E 200000  U 0.3  A 0.0000117
  MATERIAL  "A992"  FY 345  FU 450
$ FRAME SECTIONS
  FRAMESECTION  "C400x600"  MATERIAL "C30"  SHAPE "Concrete Rectangular"  D 600  B 400
  FRAMESECTION  "B300x500"  MATERIAL "C30"  SHAPE "Concrete Rectangular"  D 500  B 300
  FRAMESECTION  "W14X500"  MATERIAL "A992"  SHAPE "W14X500"  FILE "AISC14"
  FRAMESECTION  "W14X90"  MATERIAL "A992"  SHAPE "W14X90"
  FRAMESECTION  "UserI"  MATERIAL "A992"  SHAPE "Steel I/Wide Flange"  D 400  B 200  TF 12  TW 8
$ CONCRETE SECTIONS
  CONCRETESECTION  "C400x600"  LONGBARMATERIAL "B420"  CONFINEBARMATERIAL "B420"  TYPE "Column"  PATTERN "R-4-3"  TRANSREINF "TIES"  DESIGNCHECK "CHECK"  COVER 40 LONGBARAREA 314.159 CONFINEBARAREA 78.54 CONFINEBARSPACING 150 NUMCONFINEBARS3 3 NUMCONFINEBARS2 2
$ SHELL PROPERTIES
  SHELLPROP  "S150"  PROPTYPE  "Slab"  MATERIAL "C30"  MODELINGTYPE "ShellThin"  SLABTYPE "Slab"  SLABTHICKNESS 150
  SHELLPROP  "W200"  PROPTYPE  "Wall"  MATERIAL "C30"  MODELINGTYPE "ShellThin"  WALLTHICKNESS 200
$ POINT COORDINATES
  POINT "1"  0 0
  POINT "2"  6000 0
  POINT "3"  6000 5000
  POINT "4"  0 5000
  POINT "5"  3000 0
  POINT "6"  3000 5000
  POINT "7"  6000 1000
  POINT "8"  6000 2000
  POINT "9"  6000 1000 1100
  POINT "10"  6000 2000 1100
  POINT "11"  0 2500 1600
$ LINE CONNECTIVITIES
  LINE  "C1"  COLUMN  "1"  "1"  1
  LINE  "C2"  COLUMN  "2"  "2"  1
  LINE  "C3"  COLUMN  "3"  "3"  1
  LINE  "C4"  COLUMN  "4"  "4"  1
  LINE  "B1"  BEAM  "1"  "2"  0
  LINE  "B2"  BEAM  "4"  "3"  0
  LINE  "B3"  BEAM  "1"  "4"  0
  LINE  "B4"  BEAM  "5"  "6"  0
  LINE  "S1"  BEAM  "4"  "3"  0
  LINE  "K1"  BEAM  "1"  "11"  0
$ AREA CONNECTIVITIES
  AREA "F1"  FLOOR  4  "1"  "5"  "6"  "4"  0  0  0  0
  AREA "F2"  FLOOR  4  "5"  "2"  "3"  "6"  0  0  0  0
  AREA "R1"  FLOOR  4  "1"  "2"  "3"  "4"  0  0  0  0
  AREA "W1"  PANEL  4  "2"  "7"  "7"  "2"  1  1  0  0
  AREA "W2"  PANEL  4  "8"  "3"  "3"  "8"  1  1  0  0
  AREA "W3"  PANEL  4  "9"  "10"  "8"  "7"  0  0  0  0
$ POINT ASSIGNS
  POINTASSIGN  "1"  "Base"  RESTRAINT "UX UY UZ"
  POINTASSIGN  "2"  "Base"  RESTRAINT "UX UY UZ RX RY RZ"
  POINTASSIGN  "3"  "Base"  RESTRAINT "UX UY UZ RX RY RZ"
  POINTASSIGN  "4"  "Base"  DIAPH "D1"
$ LINE ASSIGNS
  LINEASSIGN  "C1"  "L1"  SECTION "C400x600"  PROPMODI22 0.7 PROPMODI33 0.7
  LINEASSIGN  "C2"  "L1"  SECTION "C400x600"  PROPMODI22 0.7 PROPMODI33 0.7
  LINEASSIGN  "C3"  "L1"  SECTION "C400x600"  PROPMODI22 0.7 PROPMODI33 0.7
  LINEASSIGN  "C4"  "L1"  SECTION "C400x600"  PROPMODI22 0.7 PROPMODI33 0.7
  LINEASSIGN  "C1"  "L2"  SECTION "C400x600"  PROPMODI22 0.7 PROPMODI33 0.7
  LINEASSIGN  "C2"  "L2"  SECTION "C400x600"  PROPMODI22 0.7 PROPMODI33 0.7
  LINEASSIGN  "C3"  "L2"  SECTION "C400x600"  PROPMODI22 0.7 PROPMODI33 0.7
  LINEASSIGN  "C4"  "L2"  SECTION "C400x600"  PROPMODI22 0.7 PROPMODI33 0.7
  LINEASSIGN  "B1"  "L1"  SECTION "B300x500"  PROPMODI33 0.35 PROPMODT 0.1 LENGTHOFFI 200 LENGTHOFFJ 0 RIGIDZONE 0.5 CARDINALPT 2
  LINEASSIGN  "B2"  "L1"  SECTION "B300x500"  PROPMODI33 0.35 RELEASE "M3I"LENGTHOFFI 0 LENGTHOFFJ 0 CARDINALPT 8
  LINEASSIGN  "B3"  "L1"  SECTION "B300x500"  PROPMODI33 0.35
  LINEASSIGN  "B4"  "L1"  SECTION "B300x500"  PROPMODI33 0.35
  LINEASSIGN  "S1"  "L2"  SECTION "W14X90"  RELEASE "PINNED"
  LINEASSIGN  "K1"  "L1"  SECTION "UserI"
$ AREA ASSIGNS
  AREAASSIGN  "F1"  "L1"  SECTION "S150"  PROPMODM11 0.25 PROPMODM22 0.25 PROPMODM12 0.25
  AREAASSIGN  "F2"  "L1"  SECTION "S150"  PROPMODM11 0.25 PROPMODM22 0.25 PROPMODM12 0.25
  AREAASSIGN  "R1"  "L2"  SECTION "S150"  PROPMODM11 0.25 PROPMODM22 0.25 PROPMODM12 0.25
  AREAASSIGN  "W1"  "L1"  SECTION "W200"  PROPMODF11 0.7 PROPMODM11 0.7 PROPMODM22 0.7 PIER "P1"
  AREAASSIGN  "W2"  "L1"  SECTION "W200"  PROPMODF11 0.7 PROPMODM11 0.7 PROPMODM22 0.7 PIER "P1"
  AREAASSIGN  "W3"  "L1"  SECTION "W200"  PROPMODF11 0.7 PROPMODM11 0.7 PROPMODM22 0.7 PIER "P1"
$ LOAD PATTERNS
  LOADPATTERN "Dead"  TYPE  "Dead"  SELFWEIGHT  1
  LOADPATTERN "SD"  TYPE  "Super Dead"  SELFWEIGHT  0
  LOADPATTERN "Live"  TYPE  "Live"  SELFWEIGHT  0
  LOADPATTERN "F"  TYPE  "Other"  SELFWEIGHT  0
  LOADPATTERN "A"  TYPE  "Other"  SELFWEIGHT  0
  LOADPATTERN "EX"  TYPE  "Seismic"  SELFWEIGHT  0
  SEISMIC "EX"  "User Coefficient"    DIR "X"    TOPSTORY "L2"    BOTTOMSTORY "Base"    SHEARCOEFF 0.05625  HEIGHTEXPONENT 1
$ MASS SOURCE
  MASSSOURCE  "MsSrc1"    INCLUDEELEMENTS "Yes"    INCLUDEADDEDMASS "Yes"    INCLUDELOADS "Yes"    LUMPATSTORIES "Yes"    ISDEFAULT "Yes"
  MASSSOURCELOAD  "MsSrc1"  "SD"  1
  MASSSOURCELOAD  "MsSrc1"  "Live"  0.5
$ POINT OBJECT LOADS
  POINTLOAD  "3"  "L1"  TYPE "FORCE"  LC "Live"  FZ -20000
$ FRAME OBJECT LOADS
  LINELOAD  "B1"  "L1"  TYPE "UNIFF"  DIR "GRAV"  LC "SD"  FVAL 10
$ SHELL OBJECT LOADS
  AREALOAD  "F1"  "L1"  TYPE "UNIFF"  DIR "GRAV"  LC "SD"  FVAL 0.0015
  AREALOAD  "F2"  "L1"  TYPE "UNIFF"  DIR "GRAV"  LC "SD"  FVAL 0.0284
  AREALOAD  "F2"  "L1"  TYPE "UNIFF"  DIR "GRAV"  LC "F"  FVAL 0.01
  AREALOAD  "F1"  "L1"  TYPE "UNIFF"  DIR "GRAV"  LC "Live"  FVAL 0.002
  AREALOAD  "F2"  "L1"  TYPE "UNIFF"  DIR "GRAV"  LC "Live"  FVAL 0.002
  AREALOAD  "R1"  "L2"  TYPE "UNIFF"  DIR "GRAV"  LC "SD"  FVAL 0.001
$ LOAD COMBINATIONS
  COMBO "U1"  TYPE "Linear Add"
  COMBO "U1"  LOADCASE "Dead"  SF 1.4
  COMBO "U1"  LOADCASE "SD"  SF 1.4
  COMBO "U1"  LOADCASE "F"  SF 1.4
  COMBO "U2"  TYPE "Linear Add"
  COMBO "U2"  LOADCASE "Dead"  SF 1.2
  COMBO "U2"  LOADCASE "SD"  SF 1.2
  COMBO "U2"  LOADCASE "F"  SF 1.2
  COMBO "U2"  LOADCASE "Live"  SF 1.6
  COMBO "U2"  LOADCASE "A"  SF 1
"""


@pytest.fixture(scope="module")
def project():  # type: ignore[no-untyped-def]
    return read_e2k("patterns.e2k", text=MODEL, section_lookup=section_lookup_noted)


def _approximated(project) -> dict[str, dict]:  # type: ignore[no-untyped-def]
    return {a["what"]: a for a in project.report.approximated}


def _skipped(project) -> dict[str, dict]:  # type: ignore[no-untyped-def]
    return {a["what"]: a for a in project.report.skipped}


def test_imports_into_valid_parts(project) -> None:  # type: ignore[no-untyped-def]
    assert project.problems() == []
    assert project.report.errors == []


# ── 1, 2: library shapes ──


@pytest.mark.parametrize("name", ["W8X125", "W10X196", "W12X282", "W14X426", "W14X730", "W21X809"])
def test_heavy_w_shapes_never_crash(name: str) -> None:
    profile, note = named_profile(name)
    assert profile is not None and note is not None and note.endswith("check")
    assert 0 < profile.webThickness < profile.flangeThickness <= profile.overallDepth / 8 + 1e-9


def test_estimated_i_shape_is_bounded_and_monotonic() -> None:
    previous = None
    for mass in range(20, 1300, 10):
        p = estimated_i_shape(355.6, float(mass), 368.8)
        area = (
            2 * p.overallWidth * p.flangeThickness
            + (p.overallDepth - 2 * p.flangeThickness) * p.webThickness
        )
        assert area == pytest.approx(mass / 7850 * 1e6, rel=1e-9)
        assert p.flangeThickness <= p.overallDepth / 8 + 1e-9
        if previous is not None:
            assert p.webThickness >= previous.webThickness - 1e-9
            assert p.overallDepth >= previous.overallDepth - 1e-9
        previous = p


def test_library_shapes_by_name_and_user_shapes_exactly(project) -> None:  # type: ignore[no-untyped-def]
    approximated = _approximated(project)
    estimated = approximated[
        "database sections (AISC14): estimated from the designation (depth and mass) — check"
    ]
    assert set(estimated["examples"]) >= {"W14X500", "W14X90"}  # FILE named on the first only
    user = next(o for o in project.objects.objects if o.id == "UserI")
    assert (user.profile.overallDepth, user.profile.flangeThickness) == (400, 12)


def test_profile_table_lookup() -> None:
    csv = [
        "# Category,Name,class,dimensions",
        "American Wide Flange,W14x90,H,368.808,356.108,11.176,18.034",
        "IS Beam,ISHB150(1),H,150,150,5.4,9",
        "IS Beam,ISHB150(2),H,150,150,8.4,9",
        "IS Beam,ISMB300,H,140,300,7.5,12.4",
        "UB,UB305x165x40,H,165,303.4,6,10.2",
        "IS Angle,ISA50x50x5,L,50,50,5",
        "broken,row",
    ]
    table = ProfileTable.parse(csv, "a test table")
    lookup = table_lookup(table, fallback=section_lookup_noted)
    w, note = lookup("W14X90")  # type: ignore[misc]
    assert (w["overallWidth"], w["overallDepth"]) == (368.808, 356.108)
    assert note == "from a test table, root radius ignored"
    ishb, note = lookup("ISHB150")  # type: ignore[misc]
    assert ishb["webThickness"] == 5.4 and "first variant" in note
    assert lookup("ISMB 300")[0]["overallDepth"] == 300  # type: ignore[index]
    assert lookup("UB305X165X40")[0]["overallWidth"] == 165  # type: ignore[index]
    assert lookup("ISA50X50X5")[0]["shape"] == "L"  # type: ignore[index]
    estimate, note = lookup("W14X145")  # type: ignore[misc]
    assert estimate["shape"] == "I" and note.endswith("check")
    assert shape_key("HE200A") == shape_key("HEA 200")


# ── 3: points below their story ──


def test_point_offsets_below_the_story(project) -> None:  # type: ignore[no-untyped-def]
    sloped = next(m for m in project.bim.additions.members if m.id == "K1-L1")
    assert (sloped.z1, sloped.z2) == (3200, 1600)


# ── 4: property modifiers ──


def test_property_modifiers_as_cracked_sections(project) -> None:  # type: ignore[no-untyped-def]
    analysis = project.settings.analysis
    assert (analysis.stiffness, analysis.crackedFor, analysis.wallsCracked) == ("aci", "all", False)
    examples = _approximated(project)["membrane, axial, shear and torsion modifiers not applied"]
    assert any(e.startswith("B1-L1 (T 0.1)") for e in examples["examples"])


# ── 5, 6: releases and offsets ──


def test_releases_and_offsets(project) -> None:  # type: ignore[no-untyped-def]
    steel = next(o for o in project.objects.objects if o.id == "W14X90-pinned")
    assert steel.kind == "beam" and steel.connection.type == "finPlate"
    beam = next(b for b in project.floor_plan.beams if b.id == "S1-L2")
    assert beam.type == "W14X90-pinned"
    approximated = _approximated(project)
    assert approximated["bending releases at one end only not expressed (member continuous there)"][
        "examples"
    ] == ["B2-L1 (M3I)"]
    assert "end length offsets ignored (SAEngine has no rigid end zones yet)" in approximated
    assert "rigid-zone factors ignored (SAEngine has no rigid end zones yet)" in approximated
    points = approximated["insertion points (cardinal points) other than the centroid ignored"]
    assert points["examples"] == ["B1-L1 (2)"]  # B2's top centre (8) is SAEngine's own


# ── 7: walls round openings ──


def test_wall_panels_round_a_door(project) -> None:  # type: ignore[no-untyped-def]
    (wall,) = project.floor_plan.walls
    assert (wall.base, wall.top, wall.start.x, wall.start.y, wall.end.y) == (
        "Base",
        "L1",
        "B",
        "1",
        "2",
    )
    (door,) = project.bim.additions.wallOpenings
    assert (door.host, door.offset, door.sill, door.width, door.height) == (
        wall.id,
        1000,
        0,
        1000,
        2100,
    )
    assert not any("wall panels" in what for what in _skipped(project))


# ── 8, 9: loads per slab and fluid loads ──


def test_slab_loads_stay_per_slab(project) -> None:  # type: ignore[no-untyped-def]
    loads = {a.id: a for a in project.settings.areaLoads}
    slabs = {s.id: s for s in project.floor_plan.slabs}
    # The floor load is the plain slab's; the tank slab has its own (SD 28.4 + fluid 10).
    assert (loads["FL"].finish, loads["FL"].live) == (1.5, 2.0)
    assert slabs["F1-L1"].areaLoad is None
    own = loads[slabs["F2-L1"].areaLoad]
    assert (own.finish, own.live) == (pytest.approx(38.4), 2.0)
    assert loads["RF"].finish == 1.0
    bim = {e.id: e for e in project.bim.elements}
    assert bim["F2-L1"].areaLoad == slabs["F2-L1"].areaLoad
    assert project.report.carried["D"] == pytest.approx(15 * 1.5 + 15 * 38.4 + 30 * 1.0)


def test_slab_loads_reach_the_analysis(project) -> None:  # type: ignore[no-untyped-def]
    from saengine.fem.derive import derive_fem

    settings = project.settings.model_copy(deep=True)
    settings.analysis.slabs = "shells"
    d = derive_fem(project.bim, project.objects, project.materials, settings, {"bim": "x"})
    sd = next(p for p in d.project["load_patterns"] if p["name"] == "SD")
    total = -sum(load["forces"][2] for load in sd["nodal_loads"]) / 1000
    assert total == pytest.approx(15 * 1.5 + 15 * 38.4 + 30 * 1.0, rel=1e-6)


def test_fluid_pattern_and_combinations(project) -> None:  # type: ignore[no-untyped-def]
    combos = {c.name: c for c in project.settings.combinations}
    assert (combos["U1"].D, combos["U1"].F) == (1.4, 1.4)
    assert (combos["U2"].D, combos["U2"].F, combos["U2"].L) == (1.2, 1.2, 1.6)
    approximated = _approximated(project)
    assert "fluid area loads applied as superimposed dead load (D factors)" in approximated
    assert "combination terms of patterns SAEngine has no case for dropped" in approximated  # A


# ── 10: point and frame loads ──


def test_point_and_frame_loads_are_reported_with_totals(project) -> None:  # type: ignore[no-untyped-def]
    assert project.report.not_carried["D"] == pytest.approx(60)  # 10 kN/m over 6 m
    assert project.report.not_carried["L"] == pytest.approx(20)
    assert any(
        w.startswith("Loads of the file not carried over (D 60 kN, L 20 kN")
        for w in project.report.warnings
    )


# ── 11, 12: supports and springs ──


def test_supports(project) -> None:  # type: ignore[no-untyped-def]
    # Point 1 is pinned (a column base): a pinned support frees its rotations. Point 2 and 3
    # are fixed and lie on the wall's base. Column C4 stands on a free point: SAEngine fixes it.
    assert [(s.at, s.fixity) for s in project.bim.supports] == [([0, 0, 0], "pinned")]
    free = _approximated(project)[
        "column bases the file leaves free, fixed by SAEngine (it fixes the columns and walls of "
        "the lowest story)"
    ]
    assert free["examples"] == ["C4-L1"]


def test_springs_without_supports_are_an_error() -> None:
    text = MODEL.replace('RESTRAINT "UX UY UZ RX RY RZ"', 'SPRINGPROP "PSpr1"').replace(
        'RESTRAINT "UX UY UZ"', 'SPRINGPROP "PSpr1"'
    )
    project = read_e2k("springs.e2k", text=text, section_lookup=section_lookup_noted)
    assert project.report.errors and "3 point springs" in project.report.errors[0]
    assert project.report.warnings[0].startswith("Error: ")
    assert project.report.to_dict()["errors"] == project.report.errors


# ── 13: column bars as a pattern ──


def test_column_bars_from_a_pattern(project) -> None:  # type: ignore[no-untyped-def]
    column = next(o for o in project.objects.objects if o.id == "C400x600")
    bars = column.reinforcement
    assert bars.cover == 40
    assert (bars.longitudinal[0].count, bars.longitudinal[0].dia) == (10, 20)  # 2(4 + 3) - 4
    assert (bars.transverse.dia, bars.transverse.spacing) == (10, 150)
    assert (bars.transverse.legs, bars.transverse.legsX) == (3, 2)


# ── 14: piers, mass source, seismic definitions ──


def test_piers_mass_source_and_seismic_are_reported(project) -> None:  # type: ignore[no-untyped-def]
    assert _skipped(project)["pier labels not read (SAEngine groups and designs its walls itself)"][
        "examples"
    ] == ["P1"]
    approximated = _approximated(project)
    mass = approximated["mass source differs from SAEngine's seismic weight (D + SD + 0.25 L)"]
    assert mass["examples"] == [
        "MsSrc1: L × 0.5 (SAEngine 0.25); lumped at the stories (SAEngine keeps it at the nodes)"
    ]
    seismic = approximated[
        "auto seismic definitions replaced by SAEngine's BNBC 2020 loads (02 Project Settings)"
    ]
    assert seismic["examples"] == ["EX: User Coefficient, C 0.05625, k 1"]
