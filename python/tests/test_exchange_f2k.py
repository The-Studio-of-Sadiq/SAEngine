"""Tests for SAFE (.f2k) export and import (alpha 9 L12)."""

from __future__ import annotations

import pytest
from test_exchange_exports import FIXED, two_bay_frame

from saengine.exporters.analytical import (
    AnalyticalModel,
    Diaphragm,
    ExchangeReport,
    LoadCase,
    Material,
    Member,
    Node,
    Plate,
    PlateSection,
    Section,
)
from saengine.exporters.exchange import FORMATS as EXPORT_FORMATS
from saengine.exporters.f2k import write_f2k
from saengine.exporters.s2k import write_s2k
from saengine.importers.project import FORMATS as IMPORT_FORMATS
from saengine.importers.safe import read_safe_text
from saengine.importers.sap2000 import tables


def slab_on_columns() -> AnalyticalModel:
    m = AnalyticalModel(name="SlabBay")
    coords = [(0.0, 0.0), (8.0, 0.0), (8.0, 6.0), (0.0, 6.0)]
    for k, (x, y) in enumerate(coords, start=1):
        m.nodes[k] = Node(k, (x, y, 0.0), FIXED)
        m.nodes[k + 4] = Node(k + 4, (x, y, 3.5))
    m.materials["C30"] = Material("C30", "concrete", 30e9, 0.2, 2400.0, fc=30e6)
    m.sections["COL40"] = Section(
        "COL40", "C30", "rectangle", {"xDim": 0.4, "yDim": 0.4}, 0.16, 0.002133, 0.002133, 0.0036
    )
    m.sections["BR20"] = Section(
        "BR20", "C30", "rectangle", {"xDim": 0.2, "yDim": 0.2}, 0.04, 0.000133, 0.000133, 0.00022
    )
    m.plate_sections["SL200"] = PlateSection("SL200", "C30", 0.2, "slab")
    m.members = [
        Member(f"C{k}", k, k + 4, "COL40", kind="column", source=f"C{k}") for k in range(1, 5)
    ] + [Member("BR1", 1, 6, "BR20", kind="brace", source="BR1")]
    m.plates = [Plate("P1", [5, 6, 7, 8], "SL200", source="S1")]
    m.grids = [("X", "A", 0.0), ("X", "B", 8.0), ("Y", "1", 0.0), ("Y", "2", 6.0)]
    m.diaphragms = [Diaphragm("D1", 5, [6, 7, 8])]
    m.masses = {k: [1000.0, 1000.0, 0.0, 0.0, 0.0, 0.0] for k in range(5, 9)}
    m.modes = 3
    m.cases = [
        LoadCase("D", "D", nodal={5: [0.0, 0.0, -10_000.0, 0, 0, 0]}),
    ]
    m.combinations = [("1.4D", {"D": 1.4})]
    return m


def test_f2k_registered_and_s2k_unchanged() -> None:
    assert "f2k" in EXPORT_FORMATS
    assert EXPORT_FORMATS["f2k"].extension == ".f2k"
    assert EXPORT_FORMATS["f2k"].folder == "F2K"
    assert IMPORT_FORMATS[".f2k"] == "safe"
    assert IMPORT_FORMATS[".$f2"] == "safe"
    # Existing s2k keys never contain spaces, so _record keeps s2k output unquoted on keys.
    s2k_text = write_s2k(two_bay_frame())
    assert 'TABLE:  "PROGRAM CONTROL"' in s2k_text
    assert 'ProgramName=SAP2000   CurrUnits="KN, m, C"   ModelName=TwoBay' in s2k_text
    assert '"ProgramName"=' not in s2k_text


def test_f2k_text_of_two_bay_frame() -> None:
    text = write_f2k(two_bay_frame())
    lines = [line.strip() for line in text.splitlines()]
    expected = [
        'TABLE:  "PROGRAM CONTROL"',
        'ProgramName=SAFE   Version=23.1.0   ProgLevel=Standard   CurrUnits="KN, m, C"   ModelName=TwoBay',
        'UniqueName=2   "Is Auto Point"=No   IsSpecial=No   X=6   Y=0   Z=0',
        "UniqueName=1   UX=Yes   UY=Yes   UZ=Yes   RX=Yes   RY=Yes   RZ=Yes",
        "Material=C25   Type=Concrete   SymType=Isotropic",
        "Material=C25   Fc=25000",
        'Name=COL   Material=C25   Depth=0.4   Width=0.3   "Section Type"=Column',
        'Name=BEAM   Material=C25   Depth=0.5   Width=0.3   "Section Type"=Beam',
        "UniqueName=C1   UniquePtI=1   UniquePtJ=4",
        "UniqueName=B2   UniquePtI=5   UniquePtJ=6",
        'UniqueName=C1   Shape="Concrete Rectangular"   "Auto Select List"=N.A.   "Section Property"=COL',
        "UniqueName=C1   Angle=90",
        'Name=D   "Is Auto Load"=No   Type=Dead   "Self Weight Multiplier"=0',
        'Name=WX   "Is Auto Load"=No   Type=Wind   "Self Weight Multiplier"=0',
        'Name=D   "Initial Condition"=Unstressed   "Load Type"=Load   "Load Name"=D   "Load SF"=1',
        'UniqueName=4   "Load Pattern"=WX   FX=15   FY=0   FZ=0   MX=0   MY=0   MZ=0',
        (
            'UniqueName=B1   "Load Pattern"=D   Direction=Z   "Distribution Type"=Relative   '
            '"Relative Distance A"=0   "Relative Distance B"=1   "Load A"=-20   "Load B"=-20'
        ),
        'Name=1.2D+1.6L   Type="Linear Add"   "Is Auto"=No   "Load Name"=D   SF=1.2',
        'Name=1.2D+1.6L   "Load Name"=L   SF=1.6',
        "END TABLE DATA",
    ]
    for line in expected:
        assert line in lines, line
    assert not any(line.startswith("UniqueName=B1   Angle=") for line in lines)


def test_f2k_slab_strips_and_skipped_items() -> None:
    report = ExchangeReport("SAFE text (.f2k)", ".f2k")
    text = write_f2k(slab_on_columns(), report)
    parsed = tables(text)

    assert len(parsed["SLAB PROPERTY DEFINITIONS"]) == 1
    assert parsed["SLAB PROPERTY DEFINITIONS"][0]["Slab Thickness"] == "0.2"
    assert len(parsed["FLOOR OBJECT CONNECTIVITY"]) == 1
    assert parsed["FLOOR OBJECT CONNECTIVITY"][0]["Unique Name"] == "P1"
    assert len(parsed["COLUMN OBJECT CONNECTIVITY"]) == 4
    assert "BEAM OBJECT CONNECTIVITY" not in parsed

    strips = parsed["STRIP OBJECT CONNECTIVITY"]
    # 2 Y grids -> 2 Layer A strips along X (widths 3 m); 2 X grids -> 2 Layer B strips along Y (widths 4 m)
    assert len(strips) == 4
    layer_a = [s for s in strips if s["Layer"] == "A"]
    layer_b = [s for s in strips if s["Layer"] == "B"]
    assert len(layer_a) == 2 and len(layer_b) == 2
    assert float(layer_a[0]["Start Width Left"]) == pytest.approx(3.0)
    assert float(layer_b[0]["Start Width Right"]) == pytest.approx(4.0)

    # 8 structural nodes + 8 special strip endpoints
    pts = parsed["POINT OBJECT CONNECTIVITY"]
    assert sum(1 for p in pts if p["IsSpecial"] == "No") == 8
    assert sum(1 for p in pts if p["IsSpecial"] == "Yes") == 8

    skipped_text = " ".join(item["what"] for item in report.skipped)
    assert "braces" in skipped_text
    assert "diaphragms" in skipped_text
    assert "masses" in skipped_text
    assert "modal" in skipped_text
    assert report.imported["designStrips"] == 4


def test_safe_v12_inline_dialect() -> None:
    v12_text = """File inline_v12.f2k

TABLE:  "PROGRAM CONTROL"
   ProgramName=SAFE   Version=12.3.2   CurrUnits="KN, m, C"

TABLE:  "MATERIAL PROPERTIES 01 - GENERAL"
   Material=C30   Type=Concrete   SymType=Isotropic

TABLE:  "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES"
   Material=C30   UnitWeight=24   UnitMass=2.447   E1=25000000   G12=10416667   U12=0.2

TABLE:  "MATERIAL PROPERTIES 03B - CONCRETE DATA"
   Material=C30   Fc=30000

TABLE:  "SLAB PROPERTIES 01 - GENERAL"
   Slab=S25   Type=Slab   MatProp=C30

TABLE:  "SLAB PROPERTIES 02 - SOLID SLABS"
   Slab=S25   Type=Slab   MatProp=C30   Thickness=0.25   Ortho=No

TABLE:  "COLUMN PROPERTIES 01 - GENERAL"
   Column=C40   Type=Rectangular   MatProp=C30   SecDim2=0.4   SecDim3=0.4

TABLE:  "OBJ GEOM - POINT COORDINATES"
   Point=1   GlobalX=0   GlobalY=0   GlobalZ=0
   Point=2   GlobalX=6   GlobalY=0   GlobalZ=0
   Point=3   GlobalX=6   GlobalY=5   GlobalZ=0
   Point=4   GlobalX=0   GlobalY=5   GlobalZ=0
   Point=5   GlobalX=0   GlobalY=0   GlobalZ=-3
   Point=6   GlobalX=6   GlobalY=0   GlobalZ=-3
   Point=7   GlobalX=6   GlobalY=5   GlobalZ=-3
   Point=8   GlobalX=0   GlobalY=5   GlobalZ=-3

TABLE:  "OBJ GEOM - LINES 01 - GENERAL"
   Line=C1   PointI=5   PointJ=1   LineType=Column   Length=3
   Line=C2   PointI=6   PointJ=2   LineType=Column   Length=3
   Line=C3   PointI=7   PointJ=3   LineType=Column   Length=3
   Line=C4   PointI=8   PointJ=4   LineType=Column   Length=3

TABLE:  "OBJ GEOM - AREAS 01 - GENERAL"
   Area=A1   NumPoints=4   Point1=1   Point2=2   Point3=3   Point4=4

TABLE:  "SLAB PROPERTY ASSIGNMENTS"
   Area=A1   SlabProp=S25

TABLE:  "COLUMN PROPERTY ASSIGNMENTS"
   Line=C1   ColProp=C40
   Line=C2   ColProp=C40
   Line=C3   ColProp=C40
   Line=C4   ColProp=C40

TABLE:  "LOAD PATTERNS"
   LoadPat=DEAD   Type=DEAD   SelfWtMult=1
   LoadPat=LIVE   Type=LIVE   SelfWtMult=0

TABLE:  "LOAD CASES 01 - GENERAL"
   LoadCase=DEAD   Type=LinStatic
   LoadCase=LIVE   Type=LinStatic

TABLE:  "LOAD CASES 02 - STATIC"
   LoadCase=DEAD   LoadPat=DEAD   SF=1
   LoadCase=LIVE   LoadPat=LIVE   SF=1

TABLE:  "LOAD COMBINATIONS"
   Combo=ULS   Load=DEAD   SF=1.4   Type="Linear Add"
   Combo=ULS   Load=LIVE   SF=1.7

TABLE:  "LOAD ASSIGNMENTS - SURFACE LOADS"
   Area=A1   LoadPat=LIVE   Dir=Gravity   UnifLoad=4

TABLE:  "LOAD ASSIGNMENTS - POINT LOADS"
   Point=3   LoadPat=LIVE   Fgrav=25   Mx=0   My=0

END TABLE DATA
"""
    model = read_safe_text(v12_text, "v12.f2k")
    assert len(model.joints) == 8
    assert model.joints["6"].tolist() == pytest.approx([6000.0, 0.0, -3000.0])
    assert len(model.frames) == 4
    assert len(model.areas) == 1
    assert model.area_sections["S25"].thickness == pytest.approx(250.0)
    assert model.sections["C40"].profile.xDim == pytest.approx(400.0)
    # Implicit far-end column supports at points 5..8
    assert set(model.supports) == {"5", "6", "7", "8"}
    assert model.supports["5"] == FIXED
    assert any("far ends fixed" in a["what"] for a in model.report.approximated)
    live_loads = model.cases["LIVE"].loads
    assert any(ld.kind == "pressure" and ld.value[2] == pytest.approx(-4000.0) for ld in live_loads)
    assert any(ld.kind == "joint" and ld.value[2] == pytest.approx(-25_000.0) for ld in live_loads)
    assert model.combinations == [("ULS", {"DEAD": 1.4, "LIVE": 1.7})]


def test_safe_v20_quoted_keys_and_strip_inline() -> None:
    v20_text = """File inline_v20.f2k

TABLE:  "PROGRAM CONTROL"
   ProgramName=SAFE   Version=20.1.0   CurrUnits="KN, m, C"

TABLE:  "MATERIAL PROPERTIES - GENERAL"
   Material=C25   Type=Concrete   SymType=Isotropic

TABLE:  "MATERIAL PROPERTIES - BASIC MECHANICAL PROPERTIES"
   Material=C25   DensityType=Weight   UnitWeight=24   UnitMass=2.447   E1=25000000   G12=10416667   U12=0.2

TABLE:  "SLAB PROPERTY DEFINITIONS"
   Name=SLAB20   "Modeling Type"=Shell-Thick   "Property Type"=Slab   Material=C25   "Slab Thickness"=0.2

TABLE:  "POINT OBJECT CONNECTIVITY"
   UniqueName=1   "Is Auto Point"=No   IsSpecial=No   X=0   Y=0   Z=3.5
   UniqueName=2   "Is Auto Point"=No   IsSpecial=No   X=6   Y=0   Z=3.5
   UniqueName=3   "Is Auto Point"=No   IsSpecial=No   X=6   Y=5   Z=3.5
   UniqueName=4   "Is Auto Point"=No   IsSpecial=No   X=0   Y=5   Z=3.5
   UniqueName=5   "Is Auto Point"=No   IsSpecial=Yes   X=0   Y=2.5   Z=3.5
   UniqueName=6   "Is Auto Point"=No   IsSpecial=Yes   X=6   Y=2.5   Z=3.5

TABLE:  "FLOOR OBJECT CONNECTIVITY"
   "Unique Name"=F1   UniquePt1=1   UniquePt2=2   UniquePt3=3   UniquePt4=4

TABLE:  "AREA ASSIGNMENTS - SECTION PROPERTIES"
   UniqueName=F1   "Section Property"=SLAB20   "Property Type"=Slab

TABLE:  "STRIP OBJECT CONNECTIVITY"
   Name=CSA1   "Number Segments"=1   "Strip Start Point"=5   "Segment End Point"=6   "Start Width Left"=2.5   "Start Width Right"=2.5   "End Width Left"=2.5   "End Width Right"=2.5   "Auto Widen"=No   Layer=A

TABLE:  "JOINT ASSIGNMENTS - RESTRAINTS"
   UniqueName=1   UX=Yes   UY=Yes   UZ=Yes   RX=No   RY=No   RZ=No

TABLE:  "LOAD PATTERN DEFINITIONS"
   Name=LIVE   "Is Auto Load"=No   Type=Live   "Self Weight Multiplier"=0

TABLE:  "AREA LOAD ASSIGNMENTS - UNIFORM"
   UniqueName=F1   "Load Pattern"=LIVE   Direction=Gravity   Load=5

END TABLE DATA
"""
    model = read_safe_text(v20_text, "v20.f2k")
    # Strip-only points 5 and 6 are excluded from structural joints
    assert set(model.joints) == {"1", "2", "3", "4"}
    assert model.area_sections["SLAB20"].thickness == pytest.approx(200.0)
    assert model.supports["1"] == (True, True, True, False, False, False)
    assert model.cases["LIVE"].loads[0].value.tolist() == pytest.approx([0.0, 0.0, -5000.0])
    assert any("design strips" in s["what"] for s in model.report.skipped)


def test_f2k_export_reads_back_into_saengine() -> None:
    model = read_safe_text(write_f2k(two_bay_frame()), "TwoBay.f2k")
    assert len(model.joints) == 6
    assert sorted(f.id for f in model.frames) == ["B1", "B2", "C1", "C2", "C3"]
    assert model.sections["BEAM"].profile.yDim == pytest.approx(500)
    assert model.sections["BEAM"].profile.xDim == pytest.approx(300)
    assert model.supports["1"] == FIXED
    assert model.materials["C25"].fc == pytest.approx(25)
    dead = model.cases["D"]
    assert dead.kind == "D"
    total = sum(load.value[2] * 6000 / 1000 for load in dead.loads if load.kind == "uniform")
    assert total == pytest.approx(-240_000)
    assert model.combinations == [("1.2D+1.6L", {"D": 1.2, "L": 1.6})]

    slab_back = read_safe_text(write_f2k(slab_on_columns()), "SlabBay.f2k")
    # Braces skipped, strip-only points pruned: 8 joints, 4 columns, 1 slab
    assert len(slab_back.joints) == 8
    assert len(slab_back.frames) == 4
    assert len(slab_back.areas) == 1
    assert slab_back.area_sections["SL200"].thickness == pytest.approx(200.0)
    assert slab_back.combinations == [("1.4D", {"D": 1.4})]
