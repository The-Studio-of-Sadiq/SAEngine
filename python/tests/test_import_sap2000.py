"""SAP2000 (.s2k) import: the tables it reads, the project it builds, and a round trip through the
analysis (base reactions equal to the gravity loads carried over)."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from saengine.fem.derive import derive_fem
from saengine.importers.sap2000 import import_sap2000, read_sap2000_text, tables

DATA = Path(__file__).parent / "data" / "import"
FRAME = DATA / "frame.s2k"


def entries(report: dict, group: str) -> dict[str, dict]:
    return {e["what"]: e for e in report[group]}


def test_tables_with_quotes_and_continued_lines() -> None:
    t = tables(FRAME.read_text(encoding="utf-8"))
    assert t["PROGRAM CONTROL"][0]["CurrUnits"] == "KN, m, C"
    column = t["FRAME SECTION PROPERTIES 01 - GENERAL"][0]
    assert column["SectionName"] == "COL400X600" and column["I33"] == "0.0072"  # continued line
    assert t["FRAME SECTION PROPERTIES 01 - GENERAL"][2]["Shape"] == "I/Wide Flange"


def test_reads_the_frame() -> None:
    model = read_sap2000_text(FRAME.read_text(encoding="utf-8"), FRAME.name)
    assert len(model.joints) == 12 and len(model.frames) == 17 and len(model.areas) == 2
    assert model.joints["11"].tolist() == pytest.approx([6000, 5000, 6400])
    w = model.sections["W200X46"].profile
    assert (w.overallDepth, w.flangeThickness, w.webThickness) == pytest.approx((203, 11, 7.2))
    steel = model.materials["A992Fy50"]
    assert steel.kind == "steel" and steel.fy == pytest.approx(344.7379)
    assert model.materials["C25"].fc == pytest.approx(25)
    assert "A615Gr60" not in model.materials  # rebar: not a member material
    assert model.supports["4"] == (True, True, True, False, False, False)
    kinds = {k: c.kind for k, c in model.cases.items()}
    assert kinds == {"DEAD": "D", "SDEAD": "SD", "LIVE": "L", "ROOFLIVE": "Lr", "WINDY": "W"}
    combos = dict(model.combinations)
    # DWIND = 1.2 GRAV + 1.6 WINDY with GRAV = DEAD + SDEAD: expanded onto the patterns.
    assert combos["DWIND"] == pytest.approx({"DEAD": 1.2, "SDEAD": 1.2, "WINDY": 1.6})
    assert "ENV" not in combos


def test_units_kip_ft() -> None:
    text = """TABLE:  "PROGRAM CONTROL"
   ProgramName=SAP2000   CurrUnits="Kip, ft, F"
TABLE:  "JOINT COORDINATES"
   Joint=1   CoordSys=GLOBAL   CoordType=Cartesian   XorR=10   Y=0   Z=12
TABLE:  "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES"
   Material=4000Psi   UnitWeight=0.15   E1=519119.5   U12=0.2
TABLE:  "MATERIAL PROPERTIES 03B - CONCRETE DATA"
   Material=4000Psi   Fc=576
TABLE:  "FRAME SECTION PROPERTIES 01 - GENERAL"
   SectionName=B12X24   Material=4000Psi   Shape=Rectangular   t3=2   t2=1
TABLE:  "LOAD PATTERN DEFINITIONS"
   LoadPat=LIVE   DesignType=Live   SelfWtMult=0
TABLE:  "JOINT LOADS - FORCE"
   Joint=1   LoadPat=LIVE   CoordSys=GLOBAL   F1=0   F2=0   F3=-10
"""
    model = read_sap2000_text(text)
    assert model.joints["1"].tolist() == pytest.approx([3048, 0, 3657.6])
    concrete = model.materials["4000Psi"]
    assert concrete.fc == pytest.approx(27.58, rel=1e-3)  # 4 ksi
    assert concrete.E == pytest.approx(24855.6, rel=1e-3)
    assert concrete.density == pytest.approx(2402.8, rel=1e-3)  # 150 pcf
    assert model.sections["B12X24"].profile.yDim == pytest.approx(609.6)
    assert model.cases["LIVE"].loads[0].value[2] == pytest.approx(-44482.2, rel=1e-6)


def test_builds_a_valid_project(tmp_path: Path) -> None:
    project = import_sap2000(FRAME)
    assert project.problems() == []
    report = project.report.to_dict()
    assert report["source"]["units"] == "KN, m, C"
    assert report["imported"]["columns"] == 8 and report["imported"]["braces"] == 1
    assert {b.fixity for b in project.bim.supports} == {"pinned"}  # pinned bases stay pinned
    assert entries(report, "skipped")["envelope, SRSS and absolute combinations"]["key"] == (
        "combinations.envelope"
    )
    # The member load (5 kN/m over 6 m) and the joint load (10 kN) are member loads now; the
    # wind joint load is replaced by SAEngine's own wind, not lost.
    assert report["loads"]["notCarriedKN"] == {}
    assert report["loads"]["replacedByBnbcKN"] == pytest.approx({"WY": 4})
    assert report["loads"]["carriedKN"]["D"] == pytest.approx(1.5 * 60 + 30)
    assert [(m.member, m.kind, m.case, m.value) for m in project.member_loads.loads] == [
        ("9", "line", "SD", 5),
        ("6", "point", "L", 10),
    ]
    assert report["imported"]["stories"] == 2
    combos = {c.name: c for c in project.settings.combinations}
    assert (combos["DSTL2"].D, combos["DSTL2"].L, combos["DSTL2"].Lr) == (1.2, 1.6, 0.5)
    # The wind case pushes in -Y: SAEngine's WY with the factor's sign turned.
    assert combos["DWIND"].WY == -1.6 and combos["DWIND"].D == 1.2
    types = {t.id: t for t in project.objects.objects}
    assert types["W200X46"].kind == "brace"
    # A column's depth (t3) lies along global X at angle 0: the rectangle turned to it.
    assert (types["COL400X600"].profile.xDim, types["COL400X600"].profile.yDim) == (600, 400)
    project.write(tmp_path)
    assert (tmp_path / "06 BIM" / "bim.json").exists()


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
    """Import -> derive -> analyse: the base reactions are the file's self-weight and area loads
    (the loads SAEngine carries over), within 0.5 %."""
    project = import_sap2000(FRAME)
    d = derive_fem(project.bim, project.objects, project.materials, project.settings)
    concrete = 8 * 0.4 * 0.6 * 3.2 + 2 * 22 * 0.3 * 0.5 + 2 * 30 * 0.15  # m³
    w_area = (2 * 203 * 11 + (203 - 2 * 11) * 7.2) * 1e-6  # m²
    dead = concrete * 23.5616 + w_area * math.hypot(6, 3.2) * 76.9729
    results = run(d.project, tmp_path, [1, 2, 3, 4])  # D, SD, L, Lr
    assert base_reaction(results, 1) == pytest.approx(dead, rel=0.005)
    assert base_reaction(results, 2) == pytest.approx(1.5 * 60, rel=0.005)
    assert base_reaction(results, 3) == pytest.approx(2.0 * 30, rel=0.005)
    assert base_reaction(results, 4) == pytest.approx(1.0 * 30, rel=0.005)


def test_area_loads_uniform_to_frame() -> None:
    from saengine.importers.neutral import build

    text = FRAME.read_text(encoding="utf-8")
    # Area 2 becomes a null area (no section): its 3 kN/m² 'uniform to frame' load is not
    # carried, with its total; on the slab (area 1) the same load is carried by the slab.
    text = text.replace("   Area=2   Section=SLAB150   MatProp=Default\n", "")
    text += """
TABLE:  "AREA LOADS - UNIFORM TO FRAME"
   Area=1   LoadPat=SDEAD   CoordSys=GLOBAL   Dir=Gravity   UnifLoad=3   DistType="Two way"
   Area=2   LoadPat=SDEAD   CoordSys=GLOBAL   Dir=Gravity   UnifLoad=3   DistType="Two way"
"""
    model = read_sap2000_text(text, "toframe.s2k")
    project = build(model)
    report = project.report.to_dict()
    assert not any(
        "uniform to frame" in e["what"] and "table" in e["what"] for e in report["skipped"]
    )
    skipped = entries(report, "skipped")
    key = next(k for k in skipped if k.startswith("area loads 'uniform to frame' on areas"))
    assert skipped[key]["examples"] == ["SDEAD: 2"]
    # Not carried: over area 2 (30 m²) its 3 kN/m² uniform to frame and its 1.5 kN/m² uniform
    # (on an area that is no longer a slab); the 30 kN dead member load is a member load.
    assert report["loads"]["notCarriedKN"]["D"] == pytest.approx(3 * 30 + 1.5 * 30)
    assert any(
        e["what"].startswith("area loads 'uniform to frame' applied to the slab")
        for e in report["approximated"]
    )
