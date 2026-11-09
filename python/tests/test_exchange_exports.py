"""Alpha 9 L12: the exchange exports (.s2k, .std, SAF, SDNF, CIS/2), checked on a two-bay frame
against constructed expectations and read back by SAEngine's own readers.

The frame: three columns 300 x 400 (C1-C3, 3.5 m) and two beams 300 x 500 (B1, B2, 6 m bays), C25,
fixed bases; D: 20 kN/m down on the beams, L: 10 kN/m down on the beams, WX: 15 kN at the left
top joint; one combination 1.2D + 1.6L. The expectations are written out by hand below, not
taken from the writers. These formats' acceptance by other programs is not verified (docs/
exchange.md); these tests pin what SAEngine writes and that SAEngine reads it back.
"""

from __future__ import annotations

import math

import pytest

from saengine.exporters.analytical import (
    AnalyticalModel,
    LoadCase,
    Material,
    Member,
    Node,
    Section,
    from_osmodel,
    local_axes,
    physical_members,
)
from saengine.exporters.cis2 import write_cis2
from saengine.exporters.s2k import write_s2k
from saengine.exporters.saf import read_saf, saf_rows, write_saf
from saengine.exporters.sdnf import write_sdnf
from saengine.exporters.std import write_std

FIXED = (True,) * 6


def two_bay_frame() -> AnalyticalModel:
    m = AnalyticalModel(name="TwoBay")
    for k, x in enumerate((0.0, 6.0, 12.0), start=1):
        m.nodes[k] = Node(k, (x, 0.0, 0.0), FIXED)
        m.nodes[k + 3] = Node(k + 3, (x, 0.0, 3.5))
    m.materials["C25"] = Material("C25", "concrete", 25e9, 0.2, 2400.0, fc=25e6)
    m.sections["COL"] = Section(
        "COL", "C25", "rectangle", {"xDim": 0.3, "yDim": 0.4}, 0.12, 0.0016, 0.0009, 0.0018
    )
    m.sections["BEAM"] = Section(
        "BEAM", "C25", "rectangle", {"xDim": 0.3, "yDim": 0.5}, 0.15, 0.003125, 0.001125, 0.0028
    )
    m.members = [
        Member("C1", 1, 4, "COL", kind="column", source="C1"),
        Member("C2", 2, 5, "COL", kind="column", source="C2"),
        Member("C3", 3, 6, "COL", kind="column", source="C3"),
        Member("B1", 4, 5, "BEAM", kind="beam", source="B1"),
        Member("B2", 5, 6, "BEAM", kind="beam", source="B2"),
    ]
    m.cases = [
        LoadCase("D", "D", uniform={"B1": [0, 0, -20000.0], "B2": [0, 0, -20000.0]}),
        LoadCase("L", "L", uniform={"B1": [0, 0, -10000.0], "B2": [0, 0, -10000.0]}),
        LoadCase("WX", "W", nodal={4: [15000.0, 0, 0, 0, 0, 0]}),
    ]
    m.combinations = [("1.2D+1.6L", {"D": 1.2, "L": 1.6})]
    return m


# ─────────────────────────────────────────── .s2k ───────────────────────────────────────────


def test_s2k_text_of_the_two_bay_frame() -> None:
    text = write_s2k(two_bay_frame())
    lines = [line.strip() for line in text.splitlines()]
    expected = [
        'TABLE:  "PROGRAM CONTROL"',
        'ProgramName=SAP2000   CurrUnits="KN, m, C"   ModelName=TwoBay',
        (
            "Joint=2   CoordSys=GLOBAL   CoordType=Cartesian   XorR=6   Y=0   Z=0   SpecialJt=No   "
            "GlobalX=6   GlobalY=0   GlobalZ=0"
        ),
        "Joint=1   U1=Yes   U2=Yes   U3=Yes   R1=Yes   R2=Yes   R3=Yes",
        "Material=C25   Type=Concrete   SymType=Isotropic",
        "Material=C25   Fc=25000",
        (
            "SectionName=COL   Material=C25   Shape=Rectangular   t3=0.4   t2=0.3   Area=0.12   "
            "TorsConst=0.0018   I33=0.0016   I22=0.0009"
        ),
        "Frame=B2   JointI=5   JointJ=6   IsCurved=No",
        "Frame=C1   AutoSelect=N.A.   AnalSect=COL   MatProp=Default",
        # A column's depth lies along Y: 90° from the default local 2 (+X).
        "Frame=C1   Angle=90   AdvanceAxes=No",
        "LoadPat=D   DesignType=Dead   SelfWtMult=0",
        "LoadPat=WX   DesignType=Wind   SelfWtMult=0   AutoLoad=None",
        "Joint=4   LoadPat=WX   CoordSys=GLOBAL   F1=15   F2=0   F3=0   M1=0   M2=0   M3=0",
        (
            "Frame=B1   LoadPat=D   CoordSys=GLOBAL   Type=Force   Dir=Z   DistType=RelDist   "
            "RelDistA=0   RelDistB=1   FOverLA=-20   FOverLB=-20"
        ),
        (
            'ComboName=1.2D+1.6L   ComboType="Linear Add"   CaseType="Linear Static"   CaseName=D   '
            "ScaleFactor=1.2"
        ),
        'ComboName=1.2D+1.6L   CaseType="Linear Static"   CaseName=L   ScaleFactor=1.6',
        "END TABLE DATA",
    ]
    for line in expected:
        assert line in lines, line
    # Beams keep the default axes: no angle.
    assert not any(line.startswith("Frame=B1   Angle=") for line in lines)


def test_s2k_reads_back_into_saengine() -> None:
    from saengine.importers.sap2000 import read_sap2000_text

    model = read_sap2000_text(write_s2k(two_bay_frame()), "TwoBay.s2k")
    assert len(model.joints) == 6
    assert sorted(f.id for f in model.frames) == ["B1", "B2", "C1", "C2", "C3"]
    assert model.sections["BEAM"].profile.yDim == pytest.approx(500)
    assert model.sections["BEAM"].profile.xDim == pytest.approx(300)
    assert model.supports["1"] == FIXED
    assert model.materials["C25"].fc == pytest.approx(25)
    dead = model.cases["D"]
    assert dead.kind == "D"
    total = sum(load.value[2] * 6000 / 1000 for load in dead.loads if load.kind == "uniform")
    assert total == pytest.approx(-240_000)  # 2 x 6 m x 20 kN/m, in N
    assert model.combinations == [("1.2D+1.6L", {"D": 1.2, "L": 1.6})]


# ─────────────────────────────────────────── .std ───────────────────────────────────────────


def test_std_text_of_the_two_bay_frame() -> None:
    lines = [line.strip() for line in write_std(two_bay_frame()).splitlines()]
    for line in (
        "STAAD SPACE",
        "SET Z UP",
        "UNIT METER KN",
        "1 0 0 0;",
        "6 12 0 3.5;",
        "1 1 4;",
        "5 5 6;",
        "ISOTROPIC C25",
        "E 25000000",
        "POISSON 0.2",
        "TYPE CONCRETE",
        "1 TO 3 PRIS YD 0.4 ZD 0.3",
        "4 5 PRIS YD 0.5 ZD 0.3",
        "MATERIAL C25 MEMB 1 TO 5",
        "1 FIXED",
        "LOAD 1 LOADTYPE Dead TITLE D",
        "4 UNI GZ -20",
        "LOAD 3 LOADTYPE Wind TITLE WX",
        "4 FX 15",
        "LOAD COMBINATION 4 1.2D+1.6L",
        "1 1.2 2 1.6",
        "PERFORM ANALYSIS",
        "FINISH",
    ):
        assert line in lines, line
    # Density as a unit weight [kN/m³]: 2400 kg/m³ x 9.80665.
    density = next(line for line in lines if line.startswith("DENSITY "))
    assert float(density.split()[1]) == pytest.approx(2400 * 9.80665 / 1000)


def test_std_reads_back_into_saengine() -> None:
    from saengine.importers.staad import read_staad_text

    model = read_staad_text(write_std(two_bay_frame()), "TwoBay.std")
    assert len(model.joints) == 6
    assert len(model.frames) == 5
    zs = sorted({round(float(p[2])) for p in model.joints.values()})
    assert zs == [0, 3500]  # Z up kept (mm)
    assert len(model.supports) == 3


# ─────────────────────────────────────────── SAF ───────────────────────────────────────────


def test_saf_rows_of_the_two_bay_frame() -> None:
    rows = saf_rows(two_bay_frame())
    assert rows["StructuralMaterial"][0][:7] == [
        "C25",
        "Concrete",
        "C25",
        2400.0,
        25000.0,
        pytest.approx(25000 / 2.4),
        0.2,
    ]
    assert ["COL", "C25", "Parametric", "Rectangle", "400;300"] == rows["StructuralCrossSection"][
        0
    ][:5]
    assert ["N4", 0.0, 0.0, 3.5] in rows["StructuralPointConnection"]
    beam = next(r for r in rows["StructuralCurveMember"] if r[0] == "B1")
    assert beam[:8] == ["B1", "Beam", "BEAM", "N4;N5", "Line", "N4", "N5", 6.0]
    assert ["Sn1", "Fixed", "N1", *(["Rigid"] * 6)] in rows["StructuralPointSupport"]
    assert [
        "WX-P1",
        "Force",
        "X",
        "In node",
        "N4",
        15.0,
        "WX",
        "Global",
    ] in rows["StructuralPointAction"]
    line = next(r for r in rows["StructuralCurveAction"] if r[3] == "B1" and r[8] == "D")
    assert line[4:8] == ["Z", "Uniform", -20.0, -20.0]
    assert rows["StructuralLoadCombination"] == [
        ["1.2D+1.6L", "1.2D+1.6L", "ULS", "Linear add", "D", 1.2, "L", 1.6]
    ]


def test_saf_round_trip(tmp_path) -> None:
    path = write_saf(two_bay_frame(), tmp_path / "TwoBay.xlsx")
    model = read_saf(path)
    assert len(model.joints) == 6
    assert sorted(f.id for f in model.frames) == ["B1", "B2", "C1", "C2", "C3"]
    assert model.sections["COL"].profile.yDim == pytest.approx(400)
    assert model.sections["COL"].profile.xDim == pytest.approx(300)
    assert model.supports["N2"] == FIXED
    assert model.cases["D"].kind == "D"
    assert model.combinations == [("1.2D+1.6L", {"D": 1.2, "L": 1.6})]
    wind = model.cases["WX"].loads
    assert len(wind) == 1 and wind[0].value[0] == pytest.approx(15000)


# ─────────────────────────────────────────── SDNF ───────────────────────────────────────────


def steel_frame() -> AnalyticalModel:
    m = two_bay_frame()
    m.materials["S275"] = Material("S275", "steel", 200e9, 0.3, 7850.0, fy=275e6, fu=430e6)
    m.sections["IPE300"] = Section(
        "IPE300",
        "S275",
        "I",
        {
            "overallWidth": 0.15,
            "overallDepth": 0.3,
            "webThickness": 0.0071,
            "flangeThickness": 0.0107,
        },
        5.38e-3,
        8.356e-5,
        6.04e-6,
        2.01e-7,
        designation="IPE300",
    )
    # A steel beam on the top split at mid-span by the analysis mesh: one piece in SDNF.
    m.nodes[7] = Node(7, (3.0, 0.0, 3.5))
    m.members = [mem for mem in m.members if mem.kind == "column"] + [
        Member(
            "S1",
            4,
            7,
            "IPE300",
            kind="beam",
            source="S1",
            releases=(frozenset({"M2", "M3"}), frozenset()),
        ),
        Member(
            "S1#2",
            7,
            5,
            "IPE300",
            kind="beam",
            source="S1",
            releases=(frozenset(), frozenset({"M2", "M3"})),
        ),
    ]
    return m


def test_physical_members_join_the_split_beam() -> None:
    pieces = {p.id: p for p in physical_members(steel_frame())}
    s1 = pieces["S1"]
    assert s1.start == (0.0, 0.0, 3.5) and s1.end == (6.0, 0.0, 3.5)
    assert s1.parts == ["S1", "S1#2"]
    assert s1.releases == (frozenset({"M2", "M3"}), frozenset({"M2", "M3"}))


def test_sdnf_text_of_the_steel_beam() -> None:
    from datetime import datetime

    text = write_sdnf(steel_frame(), when=datetime(2026, 11, 9, 10, 30))
    lines = text.split("\r\n")
    assert lines[0] == "Packet 00"
    assert lines[1] == '"SAEngine" "TwoBay" "2026-11-09" "10:30:00" 3.0 "Millimeters"'
    k = lines.index("Packet 10")
    assert lines[k + 1] == "1"  # the concrete columns are left out
    assert lines[k + 2] == '"S1" "10" 0 "Beam" "Beam" "S1" "S275" "IPE300" 0'
    assert lines[k + 3] == "0 0 3500 6000 0 3500"
    assert lines[k + 4] == "0 0 1"  # the web (depth) vertical
    assert lines[k + 6] == '"FFFFRR" "FFFFRR"'
    assert lines[lines.index("Packet 20") + 1] == "0"


# ─────────────────────────────────────────── CIS/2 ───────────────────────────────────────────


def test_cis2_file_of_the_two_bay_frame() -> None:
    text = write_cis2(two_bay_frame())
    assert text.startswith("ISO-10303-21;\nHEADER;")
    assert "FILE_SCHEMA(('STRUCTURAL_FRAME_SCHEMA'));" in text
    assert text.rstrip().endswith("END-ISO-10303-21;")
    assert text.count("=NODE(") == 6
    assert text.count("=ELEMENT_CURVE_SIMPLE(") == 5
    assert text.count("=BOUNDARY_CONDITION_LOGICAL(") == 3
    assert text.count("=LOAD_ELEMENT_DISTRIBUTED_CURVE_LINE(") == 4
    assert "=SECTION_PROFILE_RECTANGLE('COL',0.4,0.3);" in text


# ─────────────────────────────────────── from the osmodel ───────────────────────────────────────


def test_local_axes_follow_the_runner() -> None:
    _, y, z = local_axes((0, 0, 0), (6, 0, 0))
    assert list(z) == pytest.approx([0, 0, 1])
    assert list(y) == pytest.approx([0, 1, 0])
    _x, y, z = local_axes((0, 0, 0), (0, 0, 3))
    assert list(z) == pytest.approx([1, 0, 0])
    assert list(y) == pytest.approx([0, -1, 0])


def test_from_osmodel_merges_pins_and_turns_loads_global() -> None:
    from types import SimpleNamespace as NS

    osmodel = {
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
            {"id": 2, "coords": [0, 0, 3]},
            {"id": 3, "coords": [6, 0, 3]},
            {"id": 4, "coords": [0, 0, 3]},  # the twin of node 2 at the beam's pinned end
        ],
        "sections": [
            {
                "id": 1,
                "name": "B1 beam",
                "type": "ElasticSection",
                "E": 2e11,
                "A": 0.01,
                "Iz": 1e-5,
                "Iy": 8e-5,
                "G": 8e10,
                "J": 1e-7,
            },
        ],
        "elements": [
            {"id": 1, "name": "C", "type": "ElasticBeamColumn", "nodes": [1, 2], "section_id": 1},
            {"id": 2, "name": "B", "type": "ElasticBeamColumn", "nodes": [4, 3], "section_id": 1},
            {"id": 3, "name": "B/pin", "type": "ZeroLength", "nodes": [2, 4]},
        ],
        "load_patterns": [
            {
                "id": 1,
                "name": "D",
                "nodal_loads": [],
                "element_loads": [{"element_id": 2, "wx": 0, "wy": 0, "wz": -5000}],
            },
        ],
        "analyses": [],
    }
    objects = NS(objects=[NS(id="B1", material="S275", kind="beam", profile=None)])
    materials = NS(
        materials=[
            NS(
                id="S275",
                category="steel",
                mechanical=NS(E=200000, nu=0.3, density=7850),
                steel=NS(fy=275, fu=430),
                concrete=None,
            )
        ]
    )
    model = from_osmodel(osmodel, objects, materials)
    beam = next(m for m in model.members if m.id == "B")
    assert beam.i == 2  # node 4 merged into node 2
    assert beam.releases[0] == frozenset({"M2", "M3"})
    assert model.cases[0].uniform["B"] == pytest.approx([0, 0, -5000])
    # The beam section's major inertia is the derived Iy (a horizontal member).
    assert model.sections["B1_beam"].I33 == pytest.approx(8e-5)
    assert model.materials["S275"].fy == pytest.approx(275e6)
    assert math.isclose(model.length(beam), 6.0)
