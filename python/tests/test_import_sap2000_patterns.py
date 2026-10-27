"""SAP2000 (.s2k) import: the patterns of real files, in small synthetic files written from the
documented table layout (releases, property modifiers, library shapes by name, section-designer
and nonprismatic sections, column bars, local and projected frame loads, offsets and insertion
points, springs, constraints, links and solids, auto lateral loads)."""

from __future__ import annotations

import numpy as np
import pytest

from saengine.importers.neutral import build
from saengine.importers.sap2000 import read_sap2000_text

FRAME = """TABLE:  "PROGRAM CONTROL"
   ProgramName=SAP2000   Version=25.0.0   CurrUnits="KN, m, C"
TABLE:  "JOINT COORDINATES"
   Joint=1   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=0   Z=0
   Joint=2   CoordSys=GLOBAL   CoordType=Cartesian   XorR=6   Y=0   Z=0
   Joint=3   CoordSys=GLOBAL   CoordType=Cartesian   XorR=6   Y=5   Z=0
   Joint=4   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=5   Z=0
   Joint=5   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=0   Z=3.2
   Joint=6   CoordSys=GLOBAL   CoordType=Cartesian   XorR=6   Y=0   Z=3.2
   Joint=7   CoordSys=GLOBAL   CoordType=Cartesian   XorR=6   Y=5   Z=3.2
   Joint=8   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=5   Z=3.2
TABLE:  "CONNECTIVITY - FRAME"
   Frame=C1   JointI=1   JointJ=5   IsCurved=No
   Frame=C2   JointI=2   JointJ=6   IsCurved=No
   Frame=C3   JointI=3   JointJ=7   IsCurved=No
   Frame=C4   JointI=4   JointJ=8   IsCurved=No
   Frame=B1   JointI=5   JointJ=6   IsCurved=No
   Frame=B2   JointI=6   JointJ=7   IsCurved=No
   Frame=B3   JointI=7   JointJ=8   IsCurved=No
   Frame=B4   JointI=8   JointJ=5   IsCurved=No
   Frame=K1   JointI=1   JointJ=6   IsCurved=No
   Frame=K2   JointI=2   JointJ=7   IsCurved=No
   Frame=T1   JointI=4   JointJ=7   IsCurved=No
TABLE:  "CONNECTIVITY - AREA"
   Area=F1   NumJoints=4   Joint1=5   Joint2=6   Joint3=7   Joint4=8
TABLE:  "MATERIAL PROPERTIES 01 - GENERAL"
   Material=C30   Type=Concrete
   Material=A992   Type=Steel
   Material=B500   Type=Rebar
TABLE:  "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES"
   Material=C30   UnitWeight=24   E1=26000000   U12=0.2
   Material=A992   UnitWeight=76.97   E1=200000000   U12=0.3
   Material=B500   UnitWeight=76.97   E1=200000000   U12=0.3
TABLE:  "MATERIAL PROPERTIES 03A - STEEL DATA"
   Material=A992   Fy=345000   Fu=450000
TABLE:  "MATERIAL PROPERTIES 03B - CONCRETE DATA"
   Material=C30   Fc=30000
TABLE:  "MATERIAL PROPERTIES 03E - REBAR DATA"
   Material=B500   Fy=500000   Fu=550000
TABLE:  "FRAME SECTION PROPERTIES 01 - GENERAL"
   SectionName=COL400X600   Material=C30   Shape=Rectangular   t3=0.6   t2=0.4   I3Mod=1   I2Mod=1
   SectionName=BM300X500   Material=C30   Shape=Rectangular   t3=0.5   t2=0.3   I3Mod=1
   SectionName=W14X90   Material=A992   Shape="I/Wide Flange"   t3=0   t2=0   tf=0   tw=0 _
        FromFile=Yes   FileName=AISC15.xml   SectInFile=W14X90
   SectionName=SD1   Material=A992   Shape="SD Section"   Area=0.006   I33=0.0002
   SectionName=NP1   Material=A992   Shape=Nonprismatic
TABLE:  "FRAME SECTION PROPERTIES 02 - CONCRETE COLUMN"
   SectionName=COL400X600   RebarMatL=B500   RebarMatC=B500   ReinfConfig=Rectangular _
        LatReinf=Ties   Cover=0.04   NumBars3Dir=4   NumBars2Dir=3   BarSizeL=20d   BarSizeC=10d _
        SpacingC=0.15   NumCBars2=2   NumCBars3=3   ReinfType=Check
TABLE:  "FRAME SECTION PROPERTIES 03 - CONCRETE BEAM"
   SectionName=BM300X500   RebarMatL=B500   RebarMatC=B500   TopCover=0.05   BotCover=0.05
TABLE:  "FRAME SECTION ASSIGNMENTS"
   Frame=C1   SectionType=Rectangular   AnalSect=COL400X600   MatProp=Default
   Frame=C2   SectionType=Rectangular   AnalSect=COL400X600   MatProp=Default
   Frame=C3   SectionType=Rectangular   AnalSect=COL400X600   MatProp=Default
   Frame=C4   SectionType=Rectangular   AnalSect=COL400X600   MatProp=Default
   Frame=B1   SectionType=Rectangular   AnalSect=BM300X500   MatProp=Default
   Frame=B2   SectionType=Rectangular   AnalSect=BM300X500   MatProp=Default
   Frame=B3   SectionType=Rectangular   AnalSect=BM300X500   MatProp=Default
   Frame=B4   SectionType=Rectangular   AnalSect=BM300X500   MatProp=Default
   Frame=K1   SectionType="I/Wide Flange"   AnalSect=W14X90   MatProp=Default
   Frame=K2   SectionType="SD Section"   AnalSect=SD1   MatProp=Default
   Frame=T1   SectionType=Nonprismatic   AnalSect=NP1   MatProp=Default
TABLE:  "FRAME LOCAL AXES ASSIGNMENTS 1 - TYPICAL"
   Frame=C1   Angle=90
TABLE:  "FRAME RELEASE ASSIGNMENTS 1 - GENERAL"
   Frame=K1   PI=No   V2I=No   V3I=No   TI=No   M2I=Yes   M3I=Yes   PJ=No   V2J=No   V3J=No _
        TJ=No   M2J=Yes   M3J=Yes   PartialFix=No
   Frame=B4   PI=No   V2I=No   V3I=No   TI=Yes   M2I=No   M3I=Yes   PJ=No   V2J=No   V3J=No _
        TJ=No   M2J=No   M3J=No   PartialFix=Yes
TABLE:  "FRAME OFFSET ALONG LENGTH ASSIGNMENTS"
   Frame=B1   LengthType=User   OffsetI=0.2   OffsetJ=0.2   RigidFact=0.5
   Frame=B2   LengthType=User   OffsetI=0   OffsetJ=0   RigidFact=0
TABLE:  "FRAME INSERTION POINT ASSIGNMENTS"
   Frame=B1   CardinalPt="8 (Top Center)"   Mirror2=No   StiffTransform=Yes   CoordSys=Local _
        JtOffI1=0   JtOffI2=0   JtOffI3=0   JtOffJ1=0   JtOffJ2=0   JtOffJ3=0
   Frame=C2   CardinalPt="1 (Bottom Left)"   Mirror2=No   StiffTransform=Yes   CoordSys=Local _
        JtOffI1=0   JtOffI2=0   JtOffI3=0.1   JtOffJ1=0   JtOffJ2=0   JtOffJ3=0
TABLE:  "FRAME PROPERTY MODIFIERS"
   Frame=C1   AMod=1   A2Mod=1   A3Mod=1   JMod=1   I2Mod=0.7   I3Mod=0.7   MMod=1   WMod=1
   Frame=C2   AMod=1   A2Mod=1   A3Mod=1   JMod=1   I2Mod=0.7   I3Mod=0.7   MMod=1   WMod=1
   Frame=C3   AMod=1   A2Mod=1   A3Mod=1   JMod=1   I2Mod=0.7   I3Mod=0.7   MMod=1   WMod=1
   Frame=C4   AMod=1   A2Mod=1   A3Mod=1   JMod=1   I2Mod=0.7   I3Mod=0.7   MMod=1   WMod=1
   Frame=B1   AMod=1   A2Mod=1   A3Mod=1   JMod=0.1   I2Mod=1   I3Mod=0.35   MMod=1   WMod=1
   Frame=B2   AMod=1   A2Mod=1   A3Mod=1   JMod=1   I2Mod=1   I3Mod=0.35   MMod=1   WMod=1
   Frame=B3   AMod=1   A2Mod=1   A3Mod=1   JMod=1   I2Mod=1   I3Mod=0.5   MMod=1   WMod=1
   Frame=B4   AMod=1   A2Mod=1   A3Mod=1   JMod=1   I2Mod=1   I3Mod=0.35   MMod=1   WMod=1
TABLE:  "AREA SECTION PROPERTIES"
   Section=SLAB150   Material=C30   AreaType=Shell   Type=Shell-Thin   Thickness=0.15 _
        BendThick=0.15   M11Mod=1   M22Mod=1
TABLE:  "AREA SECTION ASSIGNMENTS"
   Area=F1   Section=SLAB150
TABLE:  "AREA STIFFNESS MODIFIERS"
   Area=F1   f11=1   f22=1   f12=1   m11=1   m22=1   m12=1   v13=1   v23=1   MMod=1   WMod=1 _
        M11Mod=0.25   M22Mod=0.25
TABLE:  "JOINT RESTRAINT ASSIGNMENTS"
   Joint=1   U1=Yes   U2=Yes   U3=Yes   R1=Yes   R2=Yes   R3=Yes
   Joint=2   U1=Yes   U2=Yes   U3=Yes   R1=Yes   R2=Yes   R3=Yes
   Joint=3   U1=Yes   U2=Yes   U3=Yes   R1=Yes   R2=Yes   R3=Yes
   Joint=4   U1=Yes   U2=Yes   U3=Yes   R1=Yes   R2=Yes   R3=Yes
TABLE:  "JOINT CONSTRAINT ASSIGNMENTS"
   Joint=5   Constraint=DIAPH1   Type=Diaphragm
   Joint=6   Constraint=DIAPH1   Type=Diaphragm
TABLE:  "CONNECTIVITY - LINK"
   Link=L1   JointI=3   JointJ=7
TABLE:  "CONNECTIVITY - SOLID"
   Solid=S1   Joint1=1   Joint2=2   Joint3=3   Joint4=4   Joint5=5   Joint6=6   Joint7=7   Joint8=8
TABLE:  "LOAD PATTERN DEFINITIONS"
   LoadPat=DEAD   DesignType=Dead   SelfWtMult=1
   LoadPat=WINDX   DesignType=Wind   SelfWtMult=0   AutoLoad="ASCE7-16"
   LoadPat=PUSH   DesignType=Other   SelfWtMult=0
TABLE:  "FRAME LOADS - DISTRIBUTED"
   Frame=C1   LoadPat=PUSH   CoordSys=Local   Type=Force   Dir=2   DistType=RelDist _
        RelDistA=0   RelDistB=1   FOverLA=2   FOverLB=2
   Frame=K1   LoadPat=DEAD   CoordSys=GLOBAL   Type=Force   Dir="Gravity Projected" _
        DistType=RelDist   RelDistA=0   RelDistB=1   FOverLA=1   FOverLB=1
"""


def entries(report: dict, group: str) -> dict[str, dict]:
    return {e["what"]: e for e in report[group]}


@pytest.fixture(scope="module")
def model():  # type: ignore[no-untyped-def]
    return read_sap2000_text(FRAME, "patterns.s2k")


@pytest.fixture(scope="module")
def project(model):  # type: ignore[no-untyped-def]
    return build(model, "patterns")


@pytest.fixture(scope="module")
def report(project) -> dict:  # type: ignore[no-untyped-def]
    return project.report.to_dict()


def test_releases(model, report) -> None:  # type: ignore[no-untyped-def]
    frames = {f.id: f for f in model.frames}
    assert frames["K1"].releases == (frozenset({"M2", "M3"}),) * 2
    assert frames["B4"].releases == (frozenset({"T", "M3"}), frozenset())
    approximated = entries(report, "approximated")
    assert approximated["partial fixity springs at released ends taken as full releases"][
        "examples"
    ] == ["B4"]
    assert approximated["bending releases at one end only not expressed (member continuous there)"][
        "examples"
    ] == ["B4"]


def test_pinned_steel_brace_gets_a_simple_connection(project) -> None:  # type: ignore[no-untyped-def]
    brace = next(o for o in project.objects.objects if o.kind == "brace" and "W14X90" in o.name)
    assert "pinned" in brace.name and brace.connection is not None


def test_library_shape_by_name_and_other_sections(model, report) -> None:  # type: ignore[no-untyped-def]
    w = model.sections["W14X90"]
    assert w.profile.overallDepth == pytest.approx(356.108)  # from the profile table
    sd = model.sections["SD1"].profile
    assert sd.xDim * sd.yDim == pytest.approx(6000)  # the same area (mm²)
    assert "NP1" not in model.sections
    skipped = entries(report, "skipped")
    assert skipped["nonprismatic (tapered) frame sections"]["examples"] == ["NP1"]


def test_property_modifiers_as_cracked_sections(project, report) -> None:  # type: ignore[no-untyped-def]
    analysis = project.settings.analysis
    assert (analysis.stiffness, analysis.crackedFor, analysis.wallsCracked) == ("aci", "all", False)
    approximated = entries(report, "approximated")
    assert approximated["membrane, axial, shear and torsion modifiers not applied"]["examples"] == [
        "B1 (J 0.1)"
    ]
    assert approximated[
        "property modifiers SAEngine cannot apply member by member (its cracked section factors "
        "apply)"
    ]["examples"] == ["B3 (I33 0.5)"]


def test_no_modifiers_warns_about_cracked_sections() -> None:
    start = FRAME.index('TABLE:  "FRAME PROPERTY MODIFIERS"')
    text = FRAME[:start] + FRAME[FRAME.index('TABLE:  "AREA SECTION PROPERTIES"') :]
    text = text.replace("M11Mod=0.25   M22Mod=0.25", "M11Mod=1   M22Mod=1")
    report = build(read_sap2000_text(text)).report
    assert any(w.startswith("The file has no property modifiers") for w in report.warnings)


def test_column_bars_and_rebar_material(model, project, report) -> None:  # type: ignore[no-untyped-def]
    bars = model.sections["COL400X600"].column_reinforcement
    assert bars["cover"] == 40 and bars["material"] == "B500"
    assert bars["longitudinal"] == [{"position": "perimeter", "count": 10, "dia": 20}]
    assert bars["transverse"] == {"type": "tie", "dia": 10, "spacing": 150, "legs": 3, "legsX": 2}
    assert model.rebars["B500"].fy == pytest.approx(500)
    column = next(o for o in project.objects.objects if o.kind == "column")
    assert column.reinforcement.longitudinal[0].count == 10
    rebar = next(m for m in project.materials.materials if m.name == "B500")
    assert rebar.category == "rebar"
    assert "beam bars left to SAEngine's design (the file gives covers)" in entries(
        report, "approximated"
    )


def test_local_and_projected_frame_loads(model) -> None:  # type: ignore[no-untyped-def]
    push = model.cases["PUSH"].loads[0]
    # A column's local 2 is +X at angle 0; at 90 it is +Y.
    assert push.value.tolist() == pytest.approx([0, 2000, 0])
    dead = model.cases["DEAD"].loads[0]
    # 1 kN/m on the 6 m plan projection of the 6.8 m brace: 6 kN in all.
    length = float(np.hypot(6000, 3200))
    assert dead.value[2] * (dead.length or length) / 1e6 == pytest.approx(-6)


def test_offsets_insertion_points_and_other_objects(report) -> None:  # type: ignore[no-untyped-def]
    approximated = entries(report, "approximated")
    offsets = approximated[
        "end length offsets and rigid-zone factors ignored (members run joint to joint)"
    ]
    assert [e.split()[0] for e in offsets["examples"]] == ["B1"]
    points = approximated["insertion points (cardinal points) other than the centroid ignored"]
    assert points["examples"] == ["C2 (1 (Bottom Left))"]  # B1 at its top centre is fine
    assert approximated["joint offsets of members ignored"]["examples"] == ["C2"]
    assert approximated[
        "joint constraints (diaphragms, bodies) not imported: SAEngine makes its own rigid floor "
        "diaphragms"
    ]["examples"] == ["DIAPH1"]
    skipped = entries(report, "skipped")
    assert skipped["link elements not imported"]["examples"] == ["L1"]
    assert skipped["solid elements not imported"]["examples"] == ["S1"]
    # Auto lateral loads are SAEngine's own (BNBC 2020): listed as replaced, not skipped.
    replaced = {e["key"]: e for e in report["replaced"]}
    assert replaced["loads.lateral.generated"]["examples"] == ["WINDX (ASCE7-16)"]
    assert not any(k == "tables not read" for k in skipped)


def test_springs_without_restraints_are_an_error() -> None:
    text = """TABLE:  "PROGRAM CONTROL"
   CurrUnits="KN, m, C"
TABLE:  "JOINT COORDINATES"
   Joint=1   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=0   Z=0
   Joint=2   CoordSys=GLOBAL   CoordType=Cartesian   XorR=0   Y=0   Z=3
   Joint=3   CoordSys=GLOBAL   CoordType=Cartesian   XorR=5   Y=0   Z=0
   Joint=4   CoordSys=GLOBAL   CoordType=Cartesian   XorR=5   Y=0   Z=3
TABLE:  "CONNECTIVITY - FRAME"
   Frame=1   JointI=1   JointJ=2
   Frame=2   JointI=3   JointJ=4
   Frame=3   JointI=2   JointJ=4
TABLE:  "MATERIAL PROPERTIES 01 - GENERAL"
   Material=C30   Type=Concrete
TABLE:  "MATERIAL PROPERTIES 02 - BASIC MECHANICAL PROPERTIES"
   Material=C30   UnitWeight=24   E1=26000000   U12=0.2
TABLE:  "FRAME SECTION PROPERTIES 01 - GENERAL"
   SectionName=R   Material=C30   Shape=Rectangular   t3=0.4   t2=0.4
TABLE:  "FRAME SECTION ASSIGNMENTS"
   Frame=1   AnalSect=R
   Frame=2   AnalSect=R
   Frame=3   AnalSect=R
TABLE:  "JOINT SPRING ASSIGNMENTS 1 - UNCOUPLED"
   Joint=1   CoordSys=GLOBAL   U1=1000   U2=1000   U3=50000   R1=0   R2=0   R3=0
   Joint=3   CoordSys=GLOBAL   U1=1000   U2=1000   U3=50000   R1=0   R2=0   R3=0
"""
    model = read_sap2000_text(text)
    assert model.springs == 2 and model.supports == {}
    report = build(model).report
    assert report.errors and "2 point springs" in report.errors[0]
