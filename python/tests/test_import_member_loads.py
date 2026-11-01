"""Member and joint loads of imported models, and the import report's shared wording.

The importers put the file's member loads (uniform, trapezoidal, point) and joint loads of
gravity cases onto the floor-plan beams and columns as SAEngine member loads
(``05 Floor Plan/loads.json``), list the wind and earthquake loads as replaced by SAEngine's own
(not lost), and word the report's shared items the same with a key. The models are the
synthetic files of tests/data/import, with loads added here.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from saengine.fem.member_loads import member_loads
from saengine.importers.common import ITEMS, ImportReport, ProjectBuilder, file_combinations
from saengine.importers.etabs import read_e2k
from saengine.importers.neutral import build
from saengine.importers.sap2000 import read_sap2000_text
from saengine.importers.staad import read_staad_text
from saengine.library import line_loads as ll

DATA = Path(__file__).parent / "data" / "import"


def keyed(report: dict, group: str) -> dict[str, dict]:
    return {e["key"]: e for e in report[group] if "key" in e}


def loads_of(project) -> list[tuple]:  # type: ignore[no-untyped-def]
    return [
        (m.member, m.story, m.kind, m.case, m.value, getattr(m, "distance", None))
        for m in project.member_loads.loads
    ]


# ── ETABS ──

ETABS_LOADS = """$ POINT OBJECT LOADS
  POINTLOAD  "5"  "Story2"  TYPE "FORCE"  LC "Live"  FZ -20
  POINTLOAD  "1"  "Base"  TYPE "FORCE"  LC "SDL"  FZ -7
  POINTLOAD  "2"  "Story1"  TYPE "FORCE"  LC "EQX"  FX 12

$ FRAME OBJECT LOADS
  LINELOAD  "B3"  "Story1"  TYPE "UNIFF"  DIR "GRAV"  LC "SDL"  FVAL 10
  LINELOAD  "B1"  "Story1"  TYPE "TRAPF"  DIR "GRAV"  LC "SDL"  FSTART 4  FEND 4  RDSTART 0.25  RDEND 0.75
  LINELOAD  "B2"  "Story2"  TYPE "TRAPF"  DIR "GRAV"  LC "Live"  FSTART 0  FEND 6  RDSTART 0  RDEND 1
  LINELOAD  "B6"  "Story1"  TYPE "POINTF"  DIR "GRAV"  LC "Live"  FVAL 15  RDIST 0.4
  LINELOAD  "C1"  "Story1"  TYPE "UNIFF"  DIR "GRAV"  LC "SDL"  FVAL 2
  LINELOAD  "D1"  "Story1"  TYPE "UNIFF"  DIR "GRAV"  LC "SDL"  FVAL 1
  LINELOAD  "B4"  "Story1"  TYPE "UNIFF"  DIR "X"  LC "EQX"  FVAL 3

$ SHELL OBJECT LOADS"""


@pytest.fixture(scope="module")
def etabs():  # type: ignore[no-untyped-def]
    text = (DATA / "two_story_frame.e2k").read_text(encoding="utf-8")
    start, end = text.index("$ POINT OBJECT LOADS"), text.index("$ SHELL OBJECT LOADS")
    return read_e2k("loads.e2k", text=text[:start] + ETABS_LOADS + text[end + 20 :])


def test_etabs_member_and_joint_loads_go_onto_beams_and_columns(etabs) -> None:  # type: ignore[no-untyped-def]
    assert etabs.problems() == []
    assert loads_of(etabs) == [
        ("B3-Story1", "Story1", "line", "SD", 10, None),
        # 4 kN/m over the middle half of the 6 m beam: 12 kN at its middle.
        ("B1-Story1", "Story1", "point", "SD", 12, 3000),
        # 0 to 6 kN/m along the whole beam: its mean.
        ("B2-Story2", "Story2", "line", "L", 3, None),
        ("B6-Story1", "Story1", "point", "L", 15, 2000),  # 0.4 of 5 m
        ("C5-Story2", "Story2", "point", "L", 20, None),  # at the top of the column below
    ]
    assert all(m.thisStoryOnly for m in etabs.member_loads.loads)
    report = etabs.report.to_dict()
    approximated = keyed(report, "approximated")
    assert approximated["loads.member.partial"]["examples"] == ["B1-Story1 SDL"]
    assert approximated["loads.member.varying"]["examples"] == ["B2-Story2 Live"]
    # The analysis finds every beam and column the loads are on.
    found = member_loads(etabs.bim, etabs.member_loads)
    assert found.notes == []
    assert found.totals() == pytest.approx({"SD": 60 + 12, "L": 3 * 6 + 15 + 20})


def test_etabs_loads_with_no_place_are_reported_with_totals(etabs) -> None:  # type: ignore[no-untyped-def]
    report = etabs.report.to_dict()
    skipped = keyed(report, "skipped")
    assert skipped["loads.member.notOnBeam"]["examples"] == ["C1-Story1 SDL", "D1-Story1 SDL"]
    assert skipped["loads.joint.support"]["examples"] == ["1-Base SDL"]
    brace = math.hypot(6, 3.5)
    # The column's 2 kN/m over 3.5 m, the brace's 1 kN/m and the 7 kN at a support.
    assert report["loads"]["notCarriedKN"] == pytest.approx({"D": 7 + 7 + brace}, abs=1e-3)


def test_etabs_lateral_loads_are_replaced_not_lost(etabs) -> None:  # type: ignore[no-untyped-def]
    report = etabs.report.to_dict()
    replaced = keyed(report, "replaced")
    assert replaced["loads.lateral.joint"]["examples"] == ["2-Story1 EQX"]
    assert replaced["loads.lateral.member"]["examples"] == ["B4-Story1 EQX"]
    assert replaced["loads.lateral.cases"]["examples"] == ["EQX", "EQY"]
    assert report["loads"]["replacedKN"] == pytest.approx({"EX": 12 + 3 * 6})
    assert "EX" not in report["loads"]["notCarriedKN"]
    assert not any(e.get("key", "").startswith("loads.lateral") for e in report["skipped"])
    assert any(
        w.startswith("Wind and earthquake loads of the file (EX 30 kN)")
        for w in etabs.report.warnings
    )


def test_etabs_writes_the_member_loads_file(etabs, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    written = etabs.write(tmp_path)
    path = tmp_path / ll.LOADS_FILE
    assert path in written
    loads = ll.parse(path.read_text(encoding="utf-8"))
    assert len(loads.loads) == 5 and loads.wallTypes  # the code pack's brick walls kept
    assert ll.check(loads, etabs.floor_plan) == []
    report = json.loads((tmp_path / "import-report.json").read_text(encoding="utf-8"))
    assert (report["imported"]["memberLineLoads"], report["imported"]["memberPointLoads"]) == (2, 3)


def test_etabs_report_counts_stories_without_the_base(etabs) -> None:  # type: ignore[no-untyped-def]
    assert [s.id for s in etabs.floor_plan.stories] == ["Base", "Story1", "Story2"]
    assert etabs.report.to_dict()["imported"]["stories"] == 2


def test_no_fluid_factor_without_fluid_loads(etabs) -> None:  # type: ignore[no-untyped-def]
    combos = file_combinations(etabs.settings.combinations)
    # 1.4D: SAEngine's own default would give F = D (1.4); the file has no fluid loads.
    assert (combos["U1"].D, combos["U1"].F) == (1.4, 0.0)
    assert all(c.F == 0 for c in combos.values())
    noted = keyed(etabs.report.to_dict(), "approximated")["combinations.noFluid"]
    assert noted["examples"] == ["U1", "U2", "U3"]


def test_default_area_loads_are_named_as_saengine_defaults(etabs) -> None:  # type: ignore[no-untyped-def]
    names = {a.id: a.name for a in etabs.settings.areaLoads}
    assert names == {
        "FL": "Floors (imported)",
        "ST": "Stairs (SAEngine default)",
        "RF": "Roof (imported)",
    }
    noted = keyed(etabs.report.to_dict(), "approximated")["settings.defaultAreaLoads"]
    assert noted["examples"] == ["Stairs"]


# ── SAP2000 and STAAD.Pro ──


def sap2000_project():  # type: ignore[no-untyped-def]
    text = (DATA / "frame.s2k").read_text(encoding="utf-8")
    full = "RelDistA=0   RelDistB=1   AbsDistA=0   AbsDistB=6   FOverLA=5   FOverLB=5"
    assert full in text
    text = text.replace(full, "RelDistA=0.5   RelDistB=1   FOverLA=4   FOverLB=4")
    text = text.replace(
        'TABLE:  "JOINT LOADS - FORCE"',
        'TABLE:  "FRAME LOADS - POINT"\n'
        "   Frame=9   LoadPat=LIVE   CoordSys=GLOBAL   Type=Force   Dir=Gravity   "
        "DistType=RelDist   RelDist=0.25   AbsDist=1.5   Force=8\n\n"
        'TABLE:  "JOINT LOADS - FORCE"',
    )
    return build(read_sap2000_text(text, "loads.s2k"))


def staad_project():  # type: ignore[no-untyped-def]
    text = (DATA / "frame.std").read_text(encoding="utf-8")
    text = text.replace("9 UNI GY -5\n", "9 UNI GY -4 3 6\n")
    text = text.replace(
        "JOINT LOAD\n10 FY -10\n", "MEMBER LOAD\n9 CON GY -8 1.5\nJOINT LOAD\n10 FY -10\n"
    )
    return build(read_staad_text(text, "loads.std"))


@pytest.mark.parametrize("make", [sap2000_project, staad_project], ids=["sap2000", "staad"])
def test_frame_programs_place_partial_and_point_loads(make) -> None:  # type: ignore[no-untyped-def]
    project = make()
    assert project.problems() == []
    loads = sorted(loads_of(project), key=lambda m: (m[0], m[3]))
    assert loads == [
        ("6", "Level-2", "point", "L", 10, None),  # the joint load, on the column below
        ("9", "Level-1", "point", "L", 8, 1500),  # a point load 1.5 m along the beam
        ("9", "Level-1", "point", "SD", 12, 4500),  # 4 kN/m over the beam's second half
    ]
    found = member_loads(project.bim, project.member_loads)
    assert found.notes == []
    points = sorted((p.case, round(p.at[0], 3)) for p in found.points)
    assert points == [("L", 1.5), ("L", 6.0), ("SD", 4.5)]  # x [m] along the beam from x = 0
    report = project.report.to_dict()
    assert keyed(report, "approximated")["loads.member.partial"]["count"] == 1
    assert report["loads"]["notCarriedKN"] == {}
    assert report["imported"]["stories"] == 2


@pytest.mark.parametrize("make", [sap2000_project, staad_project], ids=["sap2000", "staad"])
def test_frame_programs_word_lateral_loads_the_same(make) -> None:  # type: ignore[no-untyped-def]
    report = make().report.to_dict()
    replaced = keyed(report, "replaced")
    assert replaced["loads.lateral.joint"]["what"] == ITEMS["loads.lateral.joint"][1]
    assert set(report["loads"]["replacedKN"]) <= {"WX", "WY"}
    assert not set(report["loads"]["notCarriedKN"]) & {"WX", "WY", "EX", "EY"}
    assert all(c.F == 0 for c in file_combinations(make().settings.combinations).values())


def test_envelope_combinations_share_their_wording() -> None:
    etabs = read_e2k(DATA / "two_story_frame.e2k").report.to_dict()
    sap = sap2000_project().report.to_dict()
    for report in (etabs, sap):
        item = keyed(report, "skipped")["combinations.envelope"]
        assert item["what"] == "envelope, SRSS and absolute combinations"


# ── the builder's rules ──


def small_frame() -> ProjectBuilder:
    """Two columns 6 m apart, 3 m high, and the beam over them."""
    builder = ProjectBuilder("Loads", ImportReport("Test"))
    builder.add_material("C25", "concrete", E=23500, density=2400, fc=25)
    builder.add_frame_section("C400", "C25", {"shape": "rectangle", "xDim": 400, "yDim": 400})
    builder.add_frame_section("B300", "C25", {"shape": "rectangle", "xDim": 300, "yDim": 500})
    builder.add_story("Base", 0)
    builder.add_story("L1", 3000)
    builder.add_grid("x", "A", 0)
    builder.add_grid("x", "B", 6000)
    builder.add_grid("y", "1", 0)
    builder.add_frame("CA", "C400", (0, 0, 0), (0, 0, 3000))
    builder.add_frame("CB", "C400", (6000, 0, 0), (6000, 0, 3000))
    builder.add_frame("B1", "B300", (0, 0, 3000), (6000, 0, 3000))
    for x in (0, 6000):
        builder.add_support((x, 0, 0), (True,) * 6)
    return builder


def test_builder_places_joint_loads_and_reports_the_rest() -> None:
    builder = small_frame()
    builder.add_joint_load((3000, 0, 3000), "L", (0, 0, -5), "mid-span")
    builder.add_joint_load((0, 0, 3000), "Lr", (1, 0, -4), "corner")
    builder.add_joint_load((9000, 0, 3000), "D", (0, 0, -2), "outside")
    builder.add_member_load("B1", None, (0, 0, -1), example="no case")
    builder.add_member_load("B1", "F", (0, 0, -2), example="tank")
    builder.add_member_load("gone", "D", (0, 0, -1), length=1000, example="not imported")
    builder.add_member_load("B1", "L", (0, 0, -3), start=-100, length=7000, example="clamped")
    project = builder.build()
    assert loads_of(project) == [
        ("B1", "L1", "line", "SD", 2, None),  # fluid: superimposed dead (D factors)
        ("B1", "L1", "line", "L", 3, None),  # a load past the beam's ends: the whole beam
        ("B1", "L1", "point", "L", 5, 3000),  # no column below: on the beam there
        ("CA", "L1", "point", "Lr", 4, None),
    ]
    report = project.report.to_dict()
    approximated = keyed(report, "approximated")
    assert approximated["loads.joint.onBeam"]["examples"] == ["mid-span"]
    assert approximated["loads.horizontal"]["examples"] == ["corner"]
    assert approximated["loads.fluid"]["examples"] == ["tank"]
    skipped = keyed(report, "skipped")
    assert skipped["loads.joint.noMember"]["examples"] == ["outside"]
    assert skipped["loads.noCase.member"]["examples"] == ["no case"]
    assert skipped["loads.member.notImported"]["examples"] == ["not imported"]
    assert report["loads"]["notCarriedKN"] == pytest.approx({"D": 2 + 1, "other": 6})
    assert project.problems() == []


def test_builder_writes_no_loads_file_without_loads() -> None:
    project = small_frame().build()
    assert project.member_loads is None
    assert ll.LOADS_FILE not in project.texts


def test_builder_keeps_the_file_fluid_factors() -> None:
    builder = small_frame()
    builder.add_combination("tank", {"D": 1.2, "F": 1.2, "L": 1.6})
    builder.add_combination("dry", {"D": 1.4})
    combos = file_combinations(builder.build().settings.combinations)
    assert (combos["tank"].F, combos["dry"].F) == (1.2, 0.0)  # as in the file
