"""STAAD.Pro (.std) import: the command-language patterns of real files, each in a small synthetic
file (abbreviations, REPEAT rules, generated meshes, groups, physical members, reference and repeat
loads, releases, beta angles, springs and STAAD's compact section names)."""

from __future__ import annotations

import numpy as np
import pytest

from saengine.importers.neutral import build, named_profile
from saengine.importers.staad import read_staad_text
from saengine.library import objects as o


def entries(report: dict, group: str) -> dict[str, dict]:
    return {e["what"]: e for e in report[group]}


def total(case, model) -> np.ndarray:
    """The total force [kN] of a case's joint, point and uniform loads."""
    lengths = {
        f.id: float(np.linalg.norm(model.joints[f.j] - model.joints[f.i])) for f in model.frames
    }
    out = np.zeros(3)
    for load in case.loads:
        if load.kind in ("joint", "point"):
            out += load.value / 1e3
        elif load.kind == "uniform":
            out += load.value * (load.length or lengths[load.target]) / 1e6
    return out


PORTAL = """STAAD SPACE
UNITS FEET KIP
JOINT COORD
1 0 0 0; 2 0 12 0; 3 20 12 0; 4 20 0 0
MEMB INCI
1 1 2; 2 2 3; 3 3 4
UNIT INCH
MEMB PROP
1 3 PR YD 12 ZD 12
2 PRIS YD 24 ZD 12
UNIT FT
CONSTANT
E CONCRETE ALL
DENSITY CONCRETE ALL
SUPP
1 4 FIXED
LOAD 1 DEAD
SELF Y -1.0
MEMB LOAD
2 UNI GY -2.0
LOAD 2 WIND
JOINT LOAD
2 FX 5.0
CALCULATE RAYLEIGH FREQUENCY
"""


def test_abbreviated_commands_and_units() -> None:
    model = read_staad_text(PORTAL)
    # UNITS FEET KIP: lengths in feet, forces in kip (a missed UNITS line left kN and m).
    assert model.joints["3"].tolist() == pytest.approx([6096, 0, 3657.6])
    frames = {f.id: f for f in model.frames}
    assert frames["1"].section == "R304.8x304.8"  # PR = PRISMATIC, in inches
    assert frames["2"].section == "R304.8x609.6"
    dead = model.cases["1"]
    assert dead.selfweight == 1.0  # SELF Y -1.0
    # MEMB LOAD: 2 kip/ft down over the 20 ft beam.
    assert total(dead, model)[2] == pytest.approx(-2 * 20 * 4.4482216, rel=1e-6)
    assert total(model.cases["2"], model)[0] == pytest.approx(5 * 4.4482216, rel=1e-6)


def test_repeat_takes_the_last_row() -> None:
    # A tank-wall pattern: each REPEAT repeats the previous row (5 joints), not all of them.
    text = """STAAD SPACE
UNIT METER KN
JOINT COORDINATES
1 0. 0. 0. 5 0. 20. 0.
REPEAT 4 5. 0. 0.
REPEAT 4 0. 0. 5.
REPEAT 4 -5. 0. 0.
REPEAT 3 0. 0. -5.
"""
    model = read_staad_text(text)
    assert len(model.joints) == 80
    # Joint 26 starts the second REPEAT: one 5 m step in Z from the row at X = 20 m.
    assert model.joints["26"].tolist() == pytest.approx([20000, -5000, 0])


def test_repeat_all_back_to_the_last_one_followed_by_new_data() -> None:
    text = """STAAD SPACE
UNIT METER KN
JOINT COORDINATES
1 0 0 0 ; 2 0 3.5 0 ; 3 0 5.3 0 ; 4 0 7 0
REPEAT ALL 1 9.5 0 0
REPEAT ALL 1 0 0 3
17 1.8 7 0 ; 18 4.6 7 0 ; 19 7.6 7 0
REPEAT ALL 1 0 0 3
"""
    model = read_staad_text(text)
    # 4 -> 8 -> 16 (the second REPEAT ALL repeats all 8), + 3 -> 22 (the third repeats 17-19).
    assert len(model.joints) == 22
    assert model.joints["16"].tolist() == pytest.approx([9500, -3000, 7000])
    assert model.joints["22"].tolist() == pytest.approx([7600, -3000, 7000])


def test_member_and_element_repeat() -> None:
    text = """STAAD SPACE
UNIT METER KN
JOINT COORDINATES
1 0 0 0 4 3 0 0
REP 3 0 0 1
MEMBER INCIDENCES
1 1 2 3
REPEAT 2 3 4
ELEMENT INCIDENCES SHELL
101 1 5 6 2 TO 103
REPEAT 2 3 4
"""
    model = read_staad_text(text)
    assert len(model.joints) == 16
    frames = {f.id: (f.i, f.j) for f in model.frames}
    assert frames["4"] == ("5", "6") and frames["9"] == ("11", "12")
    plates = {a.id: a.joints for a in model.areas}
    assert len(plates) == 9 and plates["109"] == ["11", "15", "16", "12"]


def test_generated_mesh_and_groups() -> None:
    text = """STAAD SPACE
UNIT METER KN
JOINT COORDINATES
1 0 0 0; 2 4 0 0; 3 4 0 4; 4 0 0 4
MEMBER INCIDENCES
1 1 2; 2 2 3; 3 3 4; 4 4 1
DEFINE MESH
A JOINT 1
B JOINT 2
C JOINT 3
D JOINT 4
GENERATE ELEMENT
MESH ABCD 2 2
START GROUP DEFINITION
MEMBER
_EDGE 1 TO 4
ELEMENT
_SLAB 5 TO 8
END GROUP DEFINITION
MEMBER PROPERTY
_EDGE PRIS YD 0.4 ZD 0.3
ELEMENT PROPERTY
_SLAB THICKNESS 0.2
"""
    model = read_staad_text(text)
    # 2 x 2 quadrilaterals numbered on from the members; their corners shared with joints 1-4.
    assert sorted(a.id for a in model.areas) == ["5", "6", "7", "8"]
    assert len(model.joints) == 9
    assert all(f.section == "R300x400" for f in model.frames)
    assert model.area_sections["SH200"].thickness == pytest.approx(200)
    assert {a.section for a in model.areas} == {"SH200"}


PHYSICAL = """STAAD SPACE
UNIT METER KN
JOINT COORDINATES
1 0 0 0; 2 0 3 0; 3 3 3 0; 4 6 3 0; 5 6 0 0
MEMBER INCIDENCES
1 1 2; 2 2 3; 3 3 4; 4 4 5
DEFINE PMEMBER
1 PMEMBER 1
2 3 PMEMBER 2
4 PMEMBER 3
PMEMBER PROPERTY
1 3 PRIS YD 0.3 ZD 0.3
2 PRIS YD 0.5 ZD 0.3
PMEMBER CONSTANTS
MATERIAL CONCRETE LIST ALL
SUPPORTS
1 5 FIXED
DEFINE REFERENCE LOADS
LOAD R1 LOADTYPE Dead TITLE "DEAD LOAD"
PMEMBER LOAD
2 UNI GY -10
2 TRAP GY 0 -6 0 6
END DEFINE REFERENCE LOADS
LOAD 3 LOADTYPE Dead TITLE "LOAD CASE 1"
REFERENCE LOAD
R1 1.0
SELFWEIGHT Y -1
LOAD 4 TITLE FACTORED
REPEAT LOAD
3 1.5
"""


def test_physical_members_reference_and_repeat_loads() -> None:
    model = read_staad_text(PHYSICAL)
    frames = {f.id: f for f in model.frames}
    assert frames["2"].section == frames["3"].section == "R300x500"
    assert frames["1"].section == "R300x300" and frames["1"].material == "CONCRETE"
    dead = model.cases["3"]
    assert dead.kind == "D" and dead.selfweight == 1.0
    # 10 kN/m over the 6 m physical member, plus a 0 -> 6 kN/m ramp: 60 + 18 kN, split
    # between its two members (the ramp's halves: 4.5 and 13.5 kN).
    assert total(dead, model)[2] == pytest.approx(-78)
    on: dict[str, float] = {}
    for load in dead.loads:
        on[load.target] = on.get(load.target, 0.0) + load.value[2] * load.length / 1e6
    assert on == pytest.approx({"2": -34.5, "3": -43.5})
    factored = model.cases["4"]
    assert factored.kind == "D" and factored.selfweight == pytest.approx(1.5)
    assert total(factored, model)[2] == pytest.approx(-117)
    assert "R1" not in model.cases  # reference loads are not cases of their own


def test_releases_truss_and_beta() -> None:
    text = """STAAD SPACE
UNIT METER KN
JOINT COORDINATES
1 0 0 0; 2 0 3 0; 3 5 3 0; 4 5 0 0
MEMBER INCIDENCES
1 1 2; 2 2 3; 3 3 4; 4 1 3
MEMBER PROPERTY
1 3 PRIS YD 0.6 ZD 0.3
2 PRIS YD 0.5 ZD 0.3
4 TABLE ST L40404
CONSTANTS
MATERIAL CONCRETE MEMB 1 TO 3
MATERIAL STEEL MEMB 4
BETA 90 MEMB 3
MEMBER RELEASE
2 BOTH MY MZ
1 END MP 0.99
MEMBER TRUSS
4
"""
    model = read_staad_text(text)
    frames = {f.id: f for f in model.frames}
    assert frames["2"].releases == (frozenset({"M2", "M3"}),) * 2
    assert frames["4"].releases == (frozenset({"M2", "M3"}),) * 2  # truss: pinned
    assert frames["1"].releases[1] == frozenset({"T", "M2", "M3"})  # 99 % partial release
    # Y up: a column's depth (local y) lies along global X at beta 0 (angle 0 for a symmetric
    # section), along global Y at beta 90.
    assert frames["1"].rotation == 0.0 and frames["3"].rotation == pytest.approx(90)
    report = build(model).report.to_dict()
    approximated = entries(report, "approximated")
    assert approximated["truss members analysed as frame members pinned at both ends"][
        "examples"
    ] == ["4"]
    assert "partial moment releases of half or more taken as full releases" in approximated
    assert approximated["bending releases at one end only not expressed (member continuous there)"][
        "examples"
    ] == ["1"]


def test_z_up_column_axes() -> None:
    text = """STAAD SPACE
SET Z UP
UNIT METER KN
JOINT COORDINATES
1 0 0 0; 2 0 0 3
MEMBER INCIDENCES
1 1 2
MEMBER PROPERTY
1 PRIS YD 0.6 ZD 0.3
"""
    # SET Z UP: a vertical member's local y along global Y, so its depth along Y (angle 90).
    assert read_staad_text(text).frames[0].rotation == pytest.approx(90)


def test_local_and_projected_member_loads() -> None:
    text = """STAAD SPACE
UNIT METER KN
JOINT COORDINATES
1 0 0 0; 2 0 4 0; 3 3 4 0
MEMBER INCIDENCES
1 1 2; 2 1 3
MEMBER PROPERTY
1 2 PRIS YD 0.4 ZD 0.4
LOAD 1 LOADTYPE WIND TITLE WL X
MEMBER LOAD
1 UNI Y -2
LOAD 2 LOADTYPE LIVE TITLE LL
MEMBER LOAD
2 UNI PY -10
"""
    model = read_staad_text(text)
    # Local y of a column (Y up) is global -X: a load of -2 kN/m in it pushes along +X.
    assert total(model.cases["1"], model).tolist() == pytest.approx([8, 0, 0])
    # PY over the 5 m sloped member acts on its 3 m plan projection.
    assert total(model.cases["2"], model).tolist() == pytest.approx([0, 0, -30])


def test_unknown_lines_keep_the_load_case_open() -> None:
    text = """STAAD SPACE
UNIT METER KN
JOINT COORDINATES
1 0 0 0; 2 0 3 0
MEMBER INCIDENCES
1 1 2
MEMBER PROPERTY
1 PRIS YD 0.4 ZD 0.4
LOAD 1
IBC LOAD X 0.75
SELFWEIGHT Y -1.0
JOINT LOAD
2 FY -10
"""
    model = read_staad_text(text)
    case = model.cases["1"]
    assert case.selfweight == 1.0 and total(case, model)[2] == pytest.approx(-10)
    skipped = entries(model.report.to_dict(), "skipped")
    assert any(k.startswith("generated wind, seismic") for k in skipped)


def test_spring_supports_are_reported() -> None:
    text = """STAAD SPACE
UNIT METER KN
JOINT COORDINATES
1 0 0 0; 2 4 0 0; 3 4 0 4; 4 0 0 4; 5 0 3 0
MEMBER INCIDENCES
1 1 5
ELEMENT INCIDENCES
2 1 2 3 4
MEMBER PROPERTY
1 PRIS YD 0.4 ZD 0.4
ELEMENT PROPERTY
2 THICKNESS 0.3
CONSTANTS
MATERIAL CONCRETE ALL
SUPPORTS
1 TO 4 ELASTIC MAT DIRECTION YONLY SUBGRADE 5000
"""
    model = read_staad_text(text)
    assert model.supports == {} and model.springs == 4
    report = build(model).report.to_dict()
    assert any("4 point springs could not be imported" in e for e in report["errors"])
    assert any(k.startswith("soil springs generated by STAAD") for k in entries(report, "skipped"))


@pytest.mark.parametrize(
    ("name", "kind", "dims"),
    [
        ("L606012", o.LShapeProfile, (152.4, 152.4, 19.05)),  # 6.0 x 6.0 x 12/16 in
        ("L40355", o.LShapeProfile, (101.6, 88.9, 7.9375)),  # 4.0 x 3.5 x 5/16 in
        ("PIPS30", o.CircleHollowProfile, (44.45, 5.4864)),  # 3 in standard pipe
        ("PIPX20", o.CircleHollowProfile, (30.1625, 5.5372)),  # 2 in extra strong
        ("PIP4066.3", o.CircleHollowProfile, (203.0, 6.3)),
        ("HSSP10X0.5", o.CircleHollowProfile, (127.0, 12.7)),
        ("HSST12X10X0.5", o.RectangleHollowProfile, (254.0, 304.8, 12.7)),
        ("TUB25025010.0", o.RectangleHollowProfile, (250.0, 250.0, 10.0)),
        ("TUB70506", o.RectangleHollowProfile, (127.0, 177.8, 9.525)),
        ("A125X125X8", o.LShapeProfile, (125.0, 125.0, 8.0)),
    ],
)
def test_staad_section_names(name: str, kind: type, dims: tuple[float, ...]) -> None:
    profile, _ = named_profile(name)
    assert isinstance(profile, kind)
    values = {
        o.LShapeProfile: lambda p: (p.depth, p.width, p.thickness),
        o.CircleHollowProfile: lambda p: (p.radius, p.wallThickness),
        o.RectangleHollowProfile: lambda p: (p.xDim, p.yDim, p.wallThickness),
    }[kind](profile)
    assert values == pytest.approx(dims, rel=1e-4)


def test_no_placeholder_beam_for_other_families() -> None:
    # A timber name and an unknown channel are left out (reported), never a placeholder I-beam.
    for name in ("DFL_NO1_10X16_BM", "C12X25", "MC10X8"):
        profile, why = named_profile(name)
        assert profile is None and why, name
