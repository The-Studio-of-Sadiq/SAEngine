"""STAAD.Pro (.std) import: the reader's commands, the project it builds, and a round trip through
the analysis (base reactions equal to the gravity loads carried over)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from saengine.fem.derive import derive_fem
from saengine.importers.staad import import_staad, read_staad_text
from saengine.library.bim import BuildingModel
from saengine.library.floorplan import FloorPlan
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import ProjectSettings

DATA = Path(__file__).parent / "data" / "import"
FRAME = DATA / "frame.std"


def entries(report: dict, group: str) -> dict[str, dict]:
    return {e["what"]: e for e in report[group]}


def test_reads_the_frame() -> None:
    model = read_staad_text(FRAME.read_text(encoding="utf-8"), FRAME.name)
    # REPEAT ALL 2 0 3.2 0 repeats the four base joints twice, numbered on by 4.
    assert len(model.joints) == 12
    # STAAD's Y is up: (x, y, z) -> (x, -z, y) in mm.
    assert model.joints["7"].tolist() == pytest.approx([6000, -5000, 3200])
    assert model.joints["12"].tolist() == pytest.approx([0, -5000, 6400])
    # 1 1 5 4: members 1..4 from joints 1..4 to 5..8.
    frames = {f.id: f for f in model.frames}
    assert (frames["3"].i, frames["3"].j) == ("3", "7")
    assert (frames["8"].i, frames["8"].j) == ("8", "12")
    assert frames["17"].section == "SHS100X100X5" and frames["17"].material == "STEEL"
    assert frames["1"].section == "R400x600" and frames["9"].section == "R300x500"
    assert [a.id for a in model.areas] == ["101", "102"]
    assert model.area_sections["SH150"].thickness == pytest.approx(150)
    conc = model.materials["CONC25"]
    assert conc.E == pytest.approx(23500) and conc.fc == pytest.approx(25)
    assert conc.density == pytest.approx(23.5616e3 / 9.80665)
    assert model.supports["1"] == (True,) * 6
    assert {k: c.kind for k, c in model.cases.items()} == {"1": "D", "2": "L", "3": "W"}
    assert model.cases["1"].selfweight == 1
    assert model.combinations[2] == ("6 1.2D+1.0L+1.6WX", {"1": 1.2, "2": 1.0, "3": 1.6})


def test_generation_units_and_supports() -> None:
    text = """STAAD SPACE
SET Z UP
UNIT MMS NEWTON
JOINT COORDINATES
1 0 0 0 3 8000 0 0
UNIT METER KN
4 0 0 4; 5 4 0 4; 6 8 0 4
MEMBER INCIDENCES
1 1 4 3
4 4 5 5
UNIT MMS
MEMBER PROPERTY
1 TO 3 PRIS YD 400 ZD 400
4 5 TABLE ST W12X26
UNIT METER
CONSTANTS
E 2.0E8 MEMB 4 5
DENSITY 78.5 MEMB 4 5
MATERIAL CONCRETE MEMB 1 TO 3
SUPPORTS
1 PINNED
2 3 FIXED BUT MX MY
LOAD 1 DEAD
SELFWEIGHT Z -1
MEMBER LOAD
4 UNI GZ -10
5 CON GZ -20 2
LOAD COMB 2
1 1.5
"""
    model = read_staad_text(text)
    # Joints 1..3 generated between (0, 0, 0) and (8000, 0, 0) mm; 4..6 in metres after UNIT.
    assert model.joints["2"].tolist() == pytest.approx([4000, 0, 0])
    assert model.joints["6"].tolist() == pytest.approx([8000, 0, 4000])
    frames = {f.id: f for f in model.frames}
    assert (frames["2"].i, frames["2"].j) == ("2", "5")
    assert (frames["5"].i, frames["5"].j) == ("5", "6")
    # Each UNIT line applies to what follows it: the property line is in mm.
    assert model.sections["R400x400"].profile.xDim == pytest.approx(400)
    w = model.sections["W12X26"]
    # From FreeCAD's profile table: the real depth (12.22 in), not the nominal 12 in.
    assert w.approximation == "from the FreeCAD profile table, root radius ignored"
    assert (w.profile.overallWidth, w.profile.overallDepth) == (164.846, 310.388)
    steel = model.materials[frames["4"].material]
    assert steel.E == pytest.approx(200_000) and steel.density == pytest.approx(78.5e3 / 9.80665)
    assert model.supports["1"] == (True, True, True, False, False, False)
    assert model.supports["3"] == (True, True, True, False, False, True)
    loads = model.cases["1"].loads
    assert loads[0].kind == "uniform" and loads[0].value.tolist() == pytest.approx([0, 0, -10e3])
    assert loads[1].kind == "point" and loads[1].value.tolist() == pytest.approx([0, 0, -20e3])
    assert model.combinations == [("2 Combination 2", {"1": 1.5})]


def test_builds_a_valid_project(tmp_path: Path) -> None:
    project = import_staad(FRAME)
    assert project.problems() == []
    report = project.report.to_dict()
    assert report["imported"]["columns"] == 8
    assert report["imported"]["beams"] == 8
    assert report["imported"]["braces"] == 1
    assert report["imported"]["slabs"] == 2
    assert report["imported"]["stories"] == 3
    # 17 START MY MZ: released at one end only, which SAEngine does not express (reported).
    assert entries(report, "approximated")[
        "bending releases at one end only not expressed (member continuous there)"
    ]["examples"] == ["17"]
    # Dead: the member load (5 kN/m over 6 m) has no place in SAEngine; the slab pressures do.
    assert report["loads"]["notCarriedKN"]["D"] == pytest.approx(30)
    assert report["loads"]["carriedKN"]["D"] == pytest.approx(1.5 * 60)
    loads = {a.id: a for a in project.settings.areaLoads}
    assert (loads["FL"].finish, loads["FL"].live) == (1.5, 2.0)
    assert (loads["RF"].finish, loads["RF"].live) == (1.5, 1.0)
    combos = {c.name: c for c in project.settings.combinations}
    # The live case loads the roof too, which is SAEngine's roof live Lr: Lr gets L's factor.
    assert (combos["5 1.2D+1.6L"].D, combos["5 1.2D+1.6L"].L) == (1.2, 1.6)
    assert combos["5 1.2D+1.6L"].Lr == 1.6
    assert combos["6 1.2D+1.0L+1.6WX"].WX == 1.6

    written = project.write(tmp_path)
    assert (tmp_path / "import-report.json") in written
    MaterialLibrary.model_validate_json(
        (tmp_path / "03 Materials/materials.json").read_text("utf-8")
    )
    ObjectLibrary.model_validate_json((tmp_path / "04 Objects/objects.json").read_text("utf-8"))
    FloorPlan.model_validate_json((tmp_path / "05 Floor Plan/floor-plan.json").read_text("utf-8"))
    BuildingModel.model_validate_json((tmp_path / "06 BIM/bim.json").read_text("utf-8"))
    ProjectSettings.model_validate_json(
        (tmp_path / "02 Project Settings/project-settings.json").read_text("utf-8")
    )


def run(project: dict, tmp: Path, cases: list[int]) -> dict:
    from opensees_studio.services.result_store import load_manifest, load_results

    model = tmp / "model.osmodel"
    model.write_text(json.dumps(project), encoding="utf-8")
    out = tmp / "model.results"
    done = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model), "--cases"]
        + [str(c) for c in cases]
        + ["--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return {e["case_id"]: load_results(e, out) for e in load_manifest(out)["cases"]}


def base_reaction(results: dict, case: int) -> float:
    """The total vertical base reaction [kN] of a case."""
    return float(sum(np.asarray(r[-1])[2] for r in results[case].node_reaction.values())) / 1e3


def test_round_trip_base_reactions_equal_the_gravity_loads(tmp_path: Path) -> None:
    """Import -> derive -> analyse: the base reactions are the file's self-weight and slab
    pressures (the loads SAEngine carries over), within 0.5 %."""
    project = import_staad(FRAME)
    d = derive_fem(project.bim, project.objects, project.materials, project.settings)
    unit_weight = 23.5616  # kN/m³, from the file
    concrete = (
        8 * 0.4 * 0.6 * 3.2  # columns
        + 2 * (2 * 6 + 2 * 5) * 0.3 * 0.5  # beams
        + 2 * 6 * 5 * 0.15  # slabs
    )
    brace = (4 * 100 * 5 - 4 * 5 * 5) * 1e-6 * math.hypot(6, 3.2) * 76.8195  # STAAD's STEEL
    dead = concrete * unit_weight + brace
    results = run(d.project, tmp_path, [1, 2, 3, 4])  # D, SD, L, Lr
    assert base_reaction(results, 1) == pytest.approx(dead, rel=0.005)
    assert base_reaction(results, 2) == pytest.approx(1.5 * 60, rel=0.005)
    assert base_reaction(results, 3) == pytest.approx(2.0 * 30, rel=0.005)
    assert base_reaction(results, 4) == pytest.approx(1.0 * 30, rel=0.005)


def test_section_names_with_dimensions() -> None:
    from saengine.importers.neutral import named_profile
    from saengine.library import objects as o

    shs, note = named_profile("SHS100X100X5")
    assert isinstance(shs, o.RectangleHollowProfile) and note is None
    assert (shs.xDim, shs.yDim, shs.wallThickness) == (100, 100, 5)
    hss, _ = named_profile("HSS6X6X1/4")
    assert hss.xDim == pytest.approx(152.4) and hss.wallThickness == pytest.approx(6.35)
    chs, _ = named_profile("CHS114.3X6")
    assert isinstance(chs, o.CircleHollowProfile) and chs.radius == pytest.approx(57.15)
    angle, _ = named_profile("L75X75X6")
    assert isinstance(angle, o.LShapeProfile) and angle.thickness == 6
    ub, note = named_profile("UB305X165X40")
    assert isinstance(ub, o.IShapeProfile) and ub.overallWidth == 165 and note
    # Sections of SAEngine's steel table by the programs' compact names.
    ismb, note = named_profile("ISMB300")
    assert isinstance(ismb, o.IShapeProfile) and ismb.overallDepth == 300 and note is None
    hea, note = named_profile("HE200A")
    assert isinstance(hea, o.IShapeProfile) and hea.overallWidth == 200 and note is None
    other, note = named_profile("XB300")
    assert other.overallDepth == 300 and "placeholder" in (note or "")


# A one-story 6 m x 5 m beam-and-column frame with no plates, its slab loads as FLOOR LOAD
# (the usual STAAD frame model), and lateral cases with no loads of their own (generated
# seismic and wind loads are not read).
NO_PLATES = """STAAD SPACE
UNIT METER KN
JOINT COORDINATES
1 0 0 0; 2 6 0 0; 3 6 0 5; 4 0 0 5
5 0 3 0; 6 6 3 0; 7 6 3 5; 8 0 3 5
MEMBER INCIDENCES
1 1 5; 2 2 6; 3 3 7; 4 4 8
5 5 6; 6 6 7; 7 7 8; 8 8 5
9 1 6
MEMBER PROPERTY
1 TO 8 PRIS YD 0.4 ZD 0.4
9 TABLE ST L40404
CONSTANTS
MATERIAL CONCRETE MEMB 1 TO 8
MATERIAL STEEL MEMB 9
SUPPORTS
1 TO 4 FIXED
LOAD 1 LOADTYPE DEAD TITLE DL
FLOOR LOAD
YRANGE 2.9 3.1 FLOAD -4 GY
LOAD 2 LOADTYPE LIVE TITLE LL
FLOOR LOAD
YRANGE 2.9 3.1 FLOAD -3 XRANGE 0 3 ZRANGE 0 5 GY
LOAD 3 LOADTYPE SEISMIC TITLE EQX
LOAD 4 LOADTYPE SEISMIC TITLE EQZ
LOAD 5 LOADTYPE WIND TITLE WL-X
LOAD 6 LOADTYPE WIND TITLE WL -Z
LOAD COMBINATION 7 1.2D+EQX
1 1.2 3 1.0
LOAD COMBINATION 8 1.2D+EQZ
1 1.2 4 1.0
LOAD COMBINATION 9 1.2D+WLX
1 1.2 5 1.6
LOAD COMBINATION 10 1.2D-WLZ
1 1.2 6 1.6
"""


def test_floor_loads_without_plates_are_reported_with_their_totals() -> None:
    from saengine.importers.neutral import build

    project = build(read_staad_text(NO_PLATES, "noplates.std"))
    assert project.problems() == []
    report = project.report.to_dict()
    # 4 kN/m² over the 6 x 5 m bay, and 3 kN/m² over its half within XRANGE 0..3 m.
    assert report["loads"]["notCarriedKN"]["D"] == pytest.approx(120)
    assert report["loads"]["notCarriedKN"]["L"] == pytest.approx(45)
    assert not report["loads"]["carriedKN"]
    skipped = entries(report, "skipped")
    assert any(k.startswith("floor loads on levels with no slabs") for k in skipped)
    approximated = entries(report, "approximated")
    assert not any(k.startswith("floor loads applied to the slabs") for k in approximated)


def test_lateral_cases_named_in_y_up_axes() -> None:
    from saengine.importers.neutral import build, direction_from_name

    y_up = {"X": ("X", 1.0), "Z": ("Y", -1.0)}
    assert direction_from_name("EQX", y_up) == ("X", 1.0)
    assert direction_from_name("WL-X", y_up) == ("X", 1.0)  # 'WL in X', not -X
    assert direction_from_name("WL -X", y_up) == ("X", -1.0)
    assert direction_from_name("EQ(-Z)", y_up) == ("Y", 1.0)
    assert direction_from_name("WIND Z DIR", y_up) == ("Y", -1.0)  # STAAD +Z is SAEngine -Y
    assert direction_from_name("EQY") == ("Y", 1.0)  # Z up: Y is horizontal
    assert direction_from_name("EQY", y_up) is None  # Y up: Y is vertical
    combos = {c.name: c for c in build(read_staad_text(NO_PLATES)).settings.combinations}
    assert combos["7 1.2D+EQX"].EX == 1.0 and not combos["7 1.2D+EQX"].EY
    assert combos["8 1.2D+EQZ"].EY == -1.0 and not combos["8 1.2D+EQZ"].EX
    assert combos["9 1.2D+WLX"].WX == 1.6
    assert combos["10 1.2D-WLZ"].WY == 1.6


def test_compact_and_unreadable_section_names() -> None:
    from saengine.importers.neutral import build, named_profile
    from saengine.library import objects as o

    angle, note = named_profile("L40404")  # STAAD's L4x4x1/4
    assert isinstance(angle, o.LShapeProfile) and note
    assert (angle.depth, angle.width, angle.thickness) == pytest.approx((101.6, 101.6, 6.35))
    for name in ("C10X20", "MC10X8", "BEAM"):
        profile, why = named_profile(name)
        assert profile is None and why, name
    # STAAD's compact metric names: 114 x 3.0 mm pipe, 100 x 50 x 5.0 mm tube.
    pipe, _ = named_profile("PIP1143.0")
    assert (pipe.radius, pipe.wallThickness) == pytest.approx((57, 3))
    tube, _ = named_profile("TUB100505.0")
    assert (tube.yDim, tube.xDim, tube.wallThickness) == pytest.approx((100, 50, 5))
    text = NO_PLATES.replace("9 TABLE ST L40404", "9 TABLE ST C10X20")
    project = build(read_staad_text(text))
    report = project.report.to_dict()
    assert report["imported"].get("braces", 0) == 0
    assert entries(report, "skipped")["frame members without a section that could be read"][
        "examples"
    ] == ["9"]
