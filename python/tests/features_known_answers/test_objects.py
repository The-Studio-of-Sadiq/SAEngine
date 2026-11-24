"""Independent known-answer tests for standalone calculators in the Objects window."""

from __future__ import annotations

import math

import pytest

from saengine import features


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


# ── Library Checks (objects_checks.py: 7) ──────────────────────────────────────────────────────────


def test_library_checks_wall_modifiers() -> None:
    # BNBC 2020 CrackedStiffness: wallUncracked = 0.70, wall (cracked) = 0.35.
    res = features.run(
        "libraryChecks.wallModifiers",
        None,
        {"state": "uncracked", "membrane": 0.65, "bending": 0.60, "mass": 1.0, "weight": 1.0},
    )
    assert res["problems"] == []
    assert res["summary"]["state"] == "uncracked"
    assert res["summary"]["membrane"] == pytest.approx(0.65, rel=0.01)
    assert res["summary"]["bending"] == pytest.approx(0.60, rel=0.01)
    assert res["summary"]["packWallDefault"] == pytest.approx(0.70, rel=0.01)


def test_library_checks_slab_modifiers() -> None:
    # BNBC 2020 CrackedStiffness: plate = 0.25.
    res = features.run(
        "libraryChecks.slabModifiers",
        None,
        {"membrane": 0.80, "bending": 0.30, "mass": 1.0, "weight": 1.0},
    )
    assert res["problems"] == []
    assert res["summary"]["membrane"] == pytest.approx(0.80, rel=0.01)
    assert res["summary"]["bending"] == pytest.approx(0.30, rel=0.01)
    assert res["summary"]["packSlabDefault"] == pytest.approx(0.25, rel=0.01)


def test_library_checks_column_modifiers() -> None:
    # BNBC 2020 CrackedStiffness: column = 0.70.
    res = features.run(
        "libraryChecks.columnModifiers",
        None,
        {"area": 0.90, "i33": 0.65, "i22": 0.60, "j": 0.80},
    )
    assert res["problems"] == []
    assert res["summary"]["areaFactor"] == pytest.approx(0.90, rel=0.01)
    assert res["summary"]["i33Factor"] == pytest.approx(0.65, rel=0.01)
    assert res["summary"]["i22Factor"] == pytest.approx(0.60, rel=0.01)
    assert res["summary"]["packColumnDefault"] == pytest.approx(0.70, rel=0.01)


def test_library_checks_bar_fit_check() -> None:
    # Demo beam B250x450: b=250, cover=40, stirrup=10 => clear cage = 250 - 80 - 20 = 150 mm.
    # Top 2T16: clear = 150 - 32 = 118 mm. Bottom 3T16: clear = (150 - 48) / 2 = 51 mm.
    # For aggregateMm = 50 mm: req = 4/3 * 50 = 66.67 mm -> fails bottom (51 < 66.67), passes top (118 >= 66.67).
    res = features.run("libraryChecks.barFitCheck", None, {"aggregateMm": 50.0})
    assert res["problems"] == []
    assert res["summary"]["checkedFaces"] == 2
    assert res["summary"]["fitFailures"] == 1
    assert res["summary"]["allFit"] is False


def test_library_checks_cover_clash() -> None:
    # Demo members: C400x400 (cover=40), B250x450 (cover=40), S125 (cover=20), W200 (cover=25).
    # With minRequiredMm = 30.0: S125 (20) and W200 (25) fail -> 2 clashes out of 4.
    res = features.run("libraryChecks.coverClash", None, {"minRequiredMm": 30.0})
    assert res["problems"] == []
    assert res["summary"]["checkedTypes"] == 4
    assert res["summary"]["coverClashes"] == 2
    assert res["summary"]["allClear"] is False


def test_library_checks_lap_zone_check() -> None:
    # Demo column C400x400 (16 mm bar in C24.1): tension lap = 832 mm.
    # For storeyClearMm = 1200 mm -> central splice zone = 1200 / 2 = 600 mm < 832 mm -> 1 failure.
    res = features.run("libraryChecks.lapZoneCheck", None, {"storeyClearMm": 1200.0})
    assert res["problems"] == []
    assert res["summary"]["checkedColumns"] == 1
    assert res["summary"]["zoneLenMm"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["lapZoneFailures"] == 1


def test_library_checks_strength_mismatch() -> None:
    # Demo 4 concrete members are all C24.1 (fc = 24.1 MPa). Requiring 30.0 MPa flags all 4.
    res = features.run("libraryChecks.strengthMismatch", None, {"minStructuralFcMpa": 30.0})
    assert res["problems"] == []
    assert res["summary"]["checkedConcreteTypes"] == 4
    assert res["summary"]["mismatches"] == 4
    assert res["summary"]["allCompliant"] is False


# ── Library Objects (objects_library.py: 3) ────────────────────────────────────────────────────────


def test_library_objects_new_object_type() -> None:
    res = features.run(
        "libraryObjects.newObjectType",
        None,
        {
            "typeId": "B400x700",
            "typeName": "Transfer Beam",
            "kind": "beam",
            "materialId": "C30",
            "dim1Mm": 400.0,
            "dim2Mm": 700.0,
            "exportJson": False,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["objectId"] == "B400x700"
    assert res["summary"]["kind"] == "beam"
    assert res["summary"]["material"] == "C30"
    assert res["summary"]["exportPath"] == "preview"


def test_library_objects_parameter_editor() -> None:
    # Scaling C400x400 by s = 1.5 -> Area ratio = 1.5^2 = 2.25, Ixx/Iyy ratio = 1.5^4 = 5.0625.
    res = features.run(
        "libraryObjects.parameterEditor",
        None,
        {"objectId": "C400x400", "scaleFactor": 1.5},
    )
    assert res["problems"] == []
    assert res["summary"]["objectId"] == "C400x400"
    assert res["summary"]["scaleFactor"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["areaScaleRatio"] == pytest.approx(2.25, rel=0.01)
    ixx_row = _row_by(res, "metric", "Ixx")
    assert ixx_row["ratio"] == pytest.approx(5.0625, rel=0.01)


def test_library_objects_constraint_rules() -> None:
    # Demo 5 objects: C400x400 (aspect 1, cover 40), B250x450 (aspect 1.8, cover 40),
    # S125 (aspect 1, cover 20), W200 (aspect 1, cover 25), W125B (aspect 1, cover 25).
    # With maxAspect = 1.5 and minCoverMm = 22.0 -> B250x450 fails aspect, S125 fails cover -> 2 violations.
    res = features.run(
        "libraryObjects.constraintRules",
        None,
        {"minAspect": 1.0, "maxAspect": 1.5, "minCoverMm": 22.0},
    )
    assert res["problems"] == []
    assert res["summary"]["checkedCount"] == 5
    assert res["summary"]["violations"] == 2
    assert res["summary"]["allPass"] is False


# ── Library Sections (objects_sections.py: 15) ─────────────────────────────────────────────────────


def test_library_sections_new_frame_section() -> None:
    # Rectangle b=400, h=600, density=2500 kg/m3:
    # A = 240000 mm2, Ixx = 400*600^3/12 = 7.2e9 mm4, Iyy = 600*400^3/12 = 3.2e9 mm4.
    # Mass/m = 0.24 m2 * 2500 = 600 kg/m.
    res = features.run(
        "librarySections.newFrameSection",
        None,
        {
            "sectionId": "COL-400x600",
            "shape": "rectangle",
            "depthMm": 600.0,
            "widthMm": 400.0,
            "webMm": 10.0,
            "flangeMm": 14.0,
            "filletMm": 0.0,
            "densityKgM3": 2500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["sectionId"] == "COL-400x600"
    assert res["summary"]["areaMm2"] == pytest.approx(240000.0, rel=0.01)
    assert res["summary"]["ixxMm4"] == pytest.approx(7.2e9, rel=0.01)
    assert res["summary"]["iyyMm4"] == pytest.approx(3.2e9, rel=0.01)
    assert res["summary"]["massKgPerM"] == pytest.approx(600.0, rel=0.01)


def test_library_sections_rectangular_section() -> None:
    # b=400, h=600, cover=40, tie=10, top=2T16 (402.12 mm2), bot=4T25 (1963.50 mm2), fc=30, fy=500.
    # d = 600 - 40 - 10 - 12.5 = 537.5 mm; As_total = 2365.619 mm2; rho_t = 1963.495/(400*537.5) = 0.0091325.
    # Clear spacing = (400 - 2*40 - 2*10 - 4*25) / 3 = 200 / 3 = 66.667 mm.
    # Whitney block a = 1963.495 * 500 / (0.85 * 30 * 400) = 96.250 mm.
    # Mn = 1963.495 * 500 * (537.5 - 96.25/2) / 1e6 = 480.44 kNm.
    res = features.run(
        "librarySections.rectangularSection",
        None,
        {
            "widthMm": 400.0,
            "depthMm": 600.0,
            "coverMm": 40.0,
            "topBars": 2.0,
            "topDiaMm": 16.0,
            "botBars": 4.0,
            "botDiaMm": 25.0,
            "tieDiaMm": 10.0,
            "fcMpa": 30.0,
            "fyMpa": 500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(240000.0, rel=0.01)
    assert res["summary"]["ixxMm4"] == pytest.approx(7.2e9, rel=0.01)
    assert res["summary"]["effectiveDepthMm"] == pytest.approx(537.5, rel=0.01)
    as_total = 2 * math.pi * 8.0**2 + 4 * math.pi * 12.5**2
    assert res["summary"]["totalSteelMm2"] == pytest.approx(as_total, rel=0.01)
    assert res["summary"]["tensionSteelRatio"] == pytest.approx(0.0091325, rel=0.01)
    assert res["summary"]["clearSpacingMm"] == pytest.approx(66.6667, rel=0.01)
    assert res["summary"]["nominalMomentKnm"] == pytest.approx(480.44, rel=0.01)


def test_library_sections_circular_section() -> None:
    # D=600, cover=40, 8T25, hoop=10 @ 150, fc=30, fy=500.
    # Ag = pi*300^2 = 282743.34 mm2, Ig = pi*600^4/64 = 6.361725e9 mm4.
    # As = 8*pi*12.5^2 = 3926.99 mm2, rho = 0.0138889.
    # P0 = (0.85*30*(Ag - As) + 500*As) / 1000 = 9073.57 kN (or squash 0.80*phi or unfactored).
    res = features.run(
        "librarySections.circularSection",
        None,
        {
            "diameterMm": 600.0,
            "coverMm": 40.0,
            "barCount": 8.0,
            "barDiaMm": 25.0,
            "hoopDiaMm": 10.0,
            "pitchMm": 150.0,
            "fcMpa": 30.0,
            "fyMpa": 500.0,
        },
    )
    assert res["problems"] == []
    ag = math.pi * 300.0**2
    ast = 8.0 * math.pi * 12.5**2
    assert res["summary"]["areaMm2"] == pytest.approx(ag, rel=0.01)
    assert res["summary"]["inertiaMm4"] == pytest.approx(math.pi * 600.0**4 / 64.0, rel=0.01)
    assert res["summary"]["steelAreaMm2"] == pytest.approx(ast, rel=0.01)
    assert res["summary"]["steelRatio"] == pytest.approx(ast / ag, rel=0.01)
    p0 = (0.85 * 30.0 * (ag - ast) + 500.0 * ast) / 1000.0
    assert res["summary"]["squashLoadKn"] == pytest.approx(p0, rel=0.01)


def test_library_sections_t_section() -> None:
    # D=600, bf=1000, bw=250, tf=150, span=8000, sides='2'.
    # A = 1000*150 + 250*450 = 262500 mm2.
    # y from bottom: (150000*525 + 112500*225)/262500 = 396.4286 mm (or from top = 203.5714 mm).
    # Ixx = 1000*150^3/12 + 150000*(525-396.4286)^2 + 250*450^3/12 + 112500*(396.4286-225)^2 = 7.9888e9 mm4.
    # Iyy = 150*1000^3/12 + 450*250^3/12 = 1.30859e10 mm4.
    # Effective flange width limit (ACI/BNBC interior T-beam): min(span/4=2000, bw+16*tf=2650) = 2000 mm -> within=True.
    res = features.run(
        "librarySections.tSection",
        None,
        {
            "depthMm": 600.0,
            "flangeWidthMm": 1000.0,
            "webWidthMm": 250.0,
            "flangeThickMm": 150.0,
            "spanMm": 8000.0,
            "sides": "2",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(262500.0, rel=0.01)
    assert res["summary"]["ixxMm4"] == pytest.approx(7.9888e9, rel=0.01)
    assert res["summary"]["iyyMm4"] == pytest.approx(1.30859e10, rel=0.01)
    assert res["summary"]["effectiveFlangeLimitMm"] == pytest.approx(2000.0, rel=0.01)
    assert res["summary"]["withinEffectiveWidth"] is True


def test_library_sections_box_section() -> None:
    # B=600, D=800, t=100, density=2500.
    # A = 600*800 - 400*600 = 240000 mm2; Ixx = (600*800^3 - 400*600^3)/12 = 1.84e10 mm4.
    # Iyy = (800*600^3 - 600*400^3)/12 = 1.12e10 mm4.
    # Am = 500*700 = 350000 mm2; J = 4*Am^2*t / (2*(500+700)) = 2.04167e10 mm4.
    res = features.run(
        "librarySections.boxSection",
        None,
        {"widthMm": 600.0, "depthMm": 800.0, "wallThickMm": 100.0, "densityKgM3": 2500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(240000.0, rel=0.01)
    assert res["summary"]["ixxMm4"] == pytest.approx(1.84e10, rel=0.01)
    assert res["summary"]["iyyMm4"] == pytest.approx(1.12e10, rel=0.01)
    assert res["summary"]["enclosedAreaMm2"] == pytest.approx(350000.0, rel=0.01)
    j_bredt = 4.0 * 350000.0**2 * 100.0 / 2400.0
    assert _row_by(res, "metric", "Bredt thin-wall J")["value"] == pytest.approx(j_bredt, rel=0.01)
    # 2D FEM St. Venant J exceeds thin-wall Bredt for thick t/b = 1/6 due to wall bending stiffness.
    assert j_bredt < res["summary"]["jMm4"] < 1.15 * j_bredt
    assert res["summary"]["massKgPerM"] == pytest.approx(600.0, rel=0.01)


def test_library_sections_i_section() -> None:
    # Custom welded I: d=400, b=200, tw=10, tf=16, fillet=0. hw = 400 - 32 = 368.
    # A = 2*200*16 + 368*10 = 10080 mm2.
    # Ix = 2*(200*16^3/12 + 3200*192^2) + 10*368^3/12 = 277.619e6 mm4.
    # Iy = 2*(16*200^3/12) + 368*10^3/12 = 21.364e6 mm4.
    # Zx = 2*3200*192 + 10*368^2/4 = 1.56736e6 mm3; J = (2*200*16^3 + 368*10^3) / 3 = 668.8e3 mm4.
    # Cw = Iy_f * (400-16)^2 / 2 = (16*200^3/12)*384^2 / 2 = 7.86432e11 mm6.
    res = features.run(
        "librarySections.iSection",
        None,
        {
            "catalogueName": "CUSTOM",
            "depthMm": 400.0,
            "widthMm": 200.0,
            "twMm": 10.0,
            "tfMm": 16.0,
            "filletMm": 0.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(10080.0, rel=0.01)
    assert res["summary"]["ixMm4"] == pytest.approx(277.619e6, rel=0.01)
    assert res["summary"]["iyMm4"] == pytest.approx(21.364e6, rel=0.01)
    assert res["summary"]["zxMm3"] == pytest.approx(1.56736e6, rel=0.01)
    assert res["summary"]["jMm4"] == pytest.approx(668.8e3, rel=0.02)
    assert res["summary"]["cwMm6"] == pytest.approx(7.86432e11, rel=0.02)
    assert res["summary"]["massKgPerM"] == pytest.approx(10080.0 * 7850.0 / 1e6, rel=0.01)


def _spandrel_inertia(half_dim: float, r: float) -> float:
    """Second moment of area (about centroid axis) of one corner spandrel of radius r at edge half_dim."""
    a_sq = r**2
    i_sq = r**4 / 12.0 + a_sq * (half_dim - r / 2.0) ** 2
    a_qc = math.pi * r**2 / 4.0
    yc_local = 4.0 * r / (3.0 * math.pi)
    i_qc_cent = math.pi * r**4 / 16.0 - a_qc * yc_local**2
    i_qc = i_qc_cent + a_qc * (half_dim - r + yc_local) ** 2
    return i_sq - i_qc


def test_library_sections_hollow_section() -> None:
    # Cold-formed RHS 200x100x10 (ro=2.5*t=25, ri=1.5*t=15 -> corner deduction = (4-pi)*(25^2-15^2) = 343.363):
    # A = 5600 - 343.3629 = 5256.6371 mm2; Ix and Iy deduct outer spandrels and restore inner spandrels.
    res = features.run(
        "librarySections.hollowSection",
        None,
        {"kind": "RHS", "depthMm": 200.0, "widthMm": 100.0, "wallMm": 10.0},
    )
    assert res["problems"] == []
    a_rhs = 5600.0 - (4.0 - math.pi) * (25.0**2 - 15.0**2)
    ix_rhs = (
        (100.0 * 200.0**3 - 80.0 * 180.0**3) / 12.0
        - 4.0 * _spandrel_inertia(100.0, 25.0)
        + 4.0 * _spandrel_inertia(90.0, 15.0)
    )
    iy_rhs = (
        (200.0 * 100.0**3 - 180.0 * 80.0**3) / 12.0
        - 4.0 * _spandrel_inertia(50.0, 25.0)
        + 4.0 * _spandrel_inertia(40.0, 15.0)
    )
    assert res["summary"]["areaMm2"] == pytest.approx(a_rhs, rel=0.01)
    assert res["summary"]["ixMm4"] == pytest.approx(ix_rhs, rel=0.01)
    assert res["summary"]["iyMm4"] == pytest.approx(iy_rhs, rel=0.01)
    assert res["summary"]["jMm4"] > 0.0
    assert res["summary"]["massKgPerM"] == pytest.approx(a_rhs * 7850.0 / 1e6, rel=0.01)


def test_library_sections_angle_section() -> None:
    # Unequal angle 150x100x10 (r=0):
    # Vert leg 150x10 (A1=1500, x=5, y=75); Horiz leg 90x10 (A2=900, x=55, y=5). Total A = 2400 mm2.
    # xc = (1500*5 + 900*55)/2400 = 23.75 mm; yc = (1500*75 + 900*5)/2400 = 48.75 mm.
    # Ix = 10*150^3/12 + 1500*(75-48.75)^2 + 90*10^3/12 + 900*(48.75-5)^2 = 5.57625e6.
    # Iy = 150*10^3/12 + 1500*(23.75-5)^2 + 10*90^3/12 + 900*(55-23.75)^2 = 2.02625e6.
    # Ixy = 1500*(5-23.75)*(75-48.75) + 900*(55-23.75)*(5-48.75) = -1.96875e6.
    # Principal: I_u,v = 3.80125e6 +/- sqrt(1.775e6^2 + 1.96875e6^2) -> Iu = 6.452e6, Iv = 1.1505e6.
    res = features.run(
        "librarySections.angleSection",
        None,
        {
            "legAMm": 150.0,
            "legBMm": 100.0,
            "thickMm": 10.0,
            "rootRadiusMm": 0.0,
            "toeRadiusMm": 0.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(2400.0, rel=0.01)
    assert res["summary"]["iuMm4"] == pytest.approx(6.4520e6, rel=0.01)
    assert res["summary"]["ivMm4"] == pytest.approx(1.1505e6, rel=0.01)
    assert res["summary"]["rvMm"] == pytest.approx(math.sqrt(1.1505e6 / 2400.0), rel=0.01)
    assert res["summary"]["massKgPerM"] == pytest.approx(2400.0 * 7850.0 / 1e6, rel=0.01)


def test_library_sections_channel_section() -> None:
    # Plain U-channel: d=200, b=80, tw=8, tf=12, lip=0.
    # Flanges 2 x (72 x 12) + web (8 x 200) -> A = 1728 + 1600 = 3328 mm2.
    # Ixx = 8*200^3/12 + 2*(72*12^3/12 + 864*94^2) = 20.6227e6 mm4.
    # Centroid x from back of web: (1600*4 + 1728*(8+36))/3328 = 24.7692 mm.
    # Iyy = 200*8^3/12 + 1600*(24.7692-4)^2 + 2*(12*72^3/12 + 864*(44-24.7692)^2) = 2.0846e6 mm4.
    # J = (200*8^3 + 2*72*12^3)/3 = 117.077e3 mm4.
    res = features.run(
        "librarySections.channelSection",
        None,
        {"kind": "U", "depthMm": 200.0, "widthMm": 80.0, "twMm": 8.0, "tfMm": 12.0, "lipMm": 0.0},
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(3328.0, rel=0.01)
    assert res["summary"]["ixxMm4"] == pytest.approx(20.6227e6, rel=0.01)
    assert res["summary"]["iyyMm4"] == pytest.approx(2.0846e6, rel=0.01)
    assert res["summary"]["jMm4"] == pytest.approx(117.077e3, rel=0.02)
    assert res["summary"]["massKgPerM"] == pytest.approx(3328.0 * 7850.0 / 1e6, rel=0.01)


def test_library_sections_composite_beam() -> None:
    # Steel I: d=400, b=200, tw=10, tf=16 (As=10080 mm2, Is=277.619e6 mm4), fy=355 MPa, Es=200000 MPa.
    # Slab: hs=150, be=2000, fc=28 -> Ec=4700*sqrt(28)=24870.06 MPa -> n = 200000/24870.06 = 8.0418.
    # Transformed slab area Ac_tr = (2000/n)*150 = 37305.08 mm2.
    # Plastic capacity: Ts = 10080*355/1000 = 3578.4 kN, Cc = 0.85*28*2000*150/1000 = 7140 kN > Ts => PNA in slab!
    # Compression depth a = 3578400 / (0.85*28*2000) = 75.1765 mm; lever arm = 200 + 150 - 75.1765/2 = 312.4118 mm.
    # Mp = 3578.4 * 0.3124118 = 1117.93 kNm.
    res = features.run(
        "librarySections.compositeBeam",
        None,
        {
            "steelDepthMm": 400.0,
            "steelWidthMm": 200.0,
            "twMm": 10.0,
            "tfMm": 16.0,
            "slabThickMm": 150.0,
            "effWidthMm": 2000.0,
            "fcMpa": 28.0,
            "fyMpa": 355.0,
        },
    )
    assert res["problems"] == []
    ec = 4700.0 * math.sqrt(28.0)
    n = 200000.0 / ec
    assert res["summary"]["modularRatio"] == pytest.approx(n, rel=0.01)
    assert res["summary"]["plasticMomentKnm"] == pytest.approx(1117.93, rel=0.01)
    assert res["summary"]["pnaLocation"] == "Inside concrete slab"


def test_library_sections_encased_column() -> None:
    # Concrete 500x500 (Ag=250000), Steel I 250x250x10x16 (As = 2*250*16 + 218*10 = 10180 mm2),
    # Rebar 8T20 (Ar = 8*pi*10^2 = 2513.27 mm2), Ac = 250000 - 10180 - 2513.27 = 237306.73 mm2.
    # fc=30, fySteel=345, fyRebar=500 -> P0 = (0.85*30*Ac + 345*As + 500*Ar)/1000 = 10820.06 kN.
    res = features.run(
        "librarySections.encasedColumn",
        None,
        {
            "colWidthMm": 500.0,
            "colDepthMm": 500.0,
            "steelDepthMm": 250.0,
            "steelWidthMm": 250.0,
            "twMm": 10.0,
            "tfMm": 16.0,
            "rebarCount": 8.0,
            "rebarDiaMm": 20.0,
            "fcMpa": 30.0,
            "fySteelMpa": 345.0,
            "fyRebarMpa": 500.0,
        },
    )
    assert res["problems"] == []
    a_s = 2 * 250.0 * 16.0 + (250.0 - 32.0) * 10.0
    a_r = 8.0 * math.pi * 10.0**2
    a_c = 250000.0 - a_s - a_r
    p0 = (0.85 * 30.0 * a_c + 345.0 * a_s + 500.0 * a_r) / 1000.0
    assert res["summary"]["steelAreaMm2"] == pytest.approx(a_s, rel=0.01)
    assert res["summary"]["steelRatio"] == pytest.approx(a_s / 250000.0, rel=0.01)
    assert res["summary"]["squashLoadKn"] == pytest.approx(p0, rel=0.01)


def test_library_sections_filled_tube() -> None:
    # RHS 400x300x10 (ro=2.5*t=25, ri=1.5*t=15): As = 13600 - (4-pi)*(25^2-15^2) = 13256.64 mm2; Ac = 380*280 = 106400 mm2.
    # RHS squash load: 0.85*fc*Ac + fy*As = (0.85*40*106400 + 355*13256.64)/1000 = 8323.71 kN.
    res = features.run(
        "librarySections.filledTube",
        None,
        {
            "shape": "RHS",
            "depthMm": 400.0,
            "widthMm": 300.0,
            "wallMm": 10.0,
            "fcMpa": 40.0,
            "fyMpa": 355.0,
        },
    )
    assert res["problems"] == []
    a_s = 13600.0 - (4.0 - math.pi) * (25.0**2 - 15.0**2)
    a_c = 106400.0
    p0 = (0.85 * 40.0 * a_c + 355.0 * a_s) / 1000.0
    assert res["summary"]["steelAreaMm2"] == pytest.approx(a_s, rel=0.01)
    assert res["summary"]["concreteAreaMm2"] == pytest.approx(a_c, rel=0.01)
    assert res["summary"]["squashLoadKn"] == pytest.approx(p0, rel=0.01)


def test_library_sections_parametric_i_section() -> None:
    # d=500, bf=200, tw=10, tf=20, fillet=0 -> hw=460.
    # A = 2*200*20 + 460*10 = 12600 mm2; Av = 500*10 = 5000 mm2 (or hw*tw = 4600 mm2).
    # Ix = 2*(200*20^3/12 + 4000*240^2) + 10*460^3/12 = 542.193e6 mm4; Sx = Ix/250 = 2.16877e6.
    # Zx = 2*4000*240 + 10*460^2/4 = 2.449e6 mm3; shapeFactor = Zx/Sx = 1.1292.
    res = features.run(
        "librarySections.parametricISection",
        None,
        {
            "depthMm": 500.0,
            "topFlangeMm": 200.0,
            "webThickMm": 10.0,
            "flangeThickMm": 20.0,
            "filletMm": 0.0,
            "fyMpa": 345.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(12600.0, rel=0.01)
    assert res["summary"]["ixMm4"] == pytest.approx(542.193e6, rel=0.01)
    assert res["summary"]["zxMm3"] == pytest.approx(2.449e6, rel=0.01)
    assert res["summary"]["shapeFactor"] == pytest.approx(2.449e6 / (542.193e6 / 250.0), rel=0.01)
    assert res["summary"]["flangeCompact"] is True


def test_library_sections_tapered_section() -> None:
    # L=4000, d1=800, d2=400, bf=200, tw=10, tf=16.
    # Taper angle atan((800-400)/4000) = 5.7106 deg (or half-angle 2.8624 deg).
    # Start I (d=800): 2*(200*16^3/12 + 3200*392^2) + 10*768^3/12 = 1.36091e9 mm4.
    # End I (d=400): 2*(200*16^3/12 + 3200*192^2) + 10*368^3/12 = 277.619e6 mm4.
    # Linear depth => average A = (2*3200 + 10*(768+368)/2) = 12080 mm2; mass = 0.01208*4*7850 = 379.312 kg.
    res = features.run(
        "librarySections.taperedSection",
        None,
        {
            "lengthMm": 4000.0,
            "depthStartMm": 800.0,
            "depthEndMm": 400.0,
            "flangeWidthMm": 200.0,
            "twMm": 10.0,
            "tfMm": 16.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["startIxMm4"] == pytest.approx(1.36091e9, rel=0.01)
    assert res["summary"]["endIxMm4"] == pytest.approx(277.619e6, rel=0.01)
    assert res["summary"]["totalMassKg"] == pytest.approx(379.312, rel=0.01)


def test_library_sections_effective_section_check() -> None:
    # Very stocky cold-formed channel/box plate t=10 mm, d=100, b=50, fy=250, E=210000 -> NOT slender (rho=1.0).
    res_stocky = features.run(
        "librarySections.effectiveSectionCheck",
        None,
        {"depthMm": 100.0, "widthMm": 50.0, "thickMm": 10.0, "fyMpa": 250.0, "eMpa": 210000.0},
    )
    assert res_stocky["problems"] == []
    assert res_stocky["summary"]["isSlender"] is False
    assert res_stocky["summary"]["areaReductionRatio"] == pytest.approx(1.0, rel=0.01)

    # Very slender plate t=2 mm, d=300, b=100, fy=350, E=210000 -> IS slender (areaReductionRatio < 1.0).
    res_slender = features.run(
        "librarySections.effectiveSectionCheck",
        None,
        {"depthMm": 300.0, "widthMm": 100.0, "thickMm": 2.0, "fyMpa": 350.0, "eMpa": 210000.0},
    )
    assert res_slender["problems"] == []
    assert res_slender["summary"]["isSlender"] is True
    assert res_slender["summary"]["effectiveAreaMm2"] < res_slender["summary"]["grossAreaMm2"]
    assert res_slender["summary"]["effectiveIxMm4"] < res_slender["summary"]["grossIxMm4"]


# ── Section Designer (objects_designer.py: 18) ─────────────────────────────────────────────────────


def test_obj_designer_add_shape() -> None:
    # Hollow rectangle 600x800 with 200x400 void offset (0, 0):
    # A = 600*800 - 200*400 = 400000 mm2.
    # Ixx = (600*800^3 - 200*400^3)/12 = 24.5333e9 mm4; Iyy = (800*600^3 - 400*200^3)/12 = 14.1333e9 mm4.
    res = features.run(
        "objDesigner.addShape",
        None,
        {
            "shape": "hollowRect",
            "widthMm": 600.0,
            "depthMm": 800.0,
            "voidWidthMm": 200.0,
            "voidDepthMm": 400.0,
            "offsetXMm": 0.0,
            "offsetYMm": 0.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["vertexCount"] == 4
    assert res["summary"]["holeCount"] == 1
    assert res["summary"]["areaMm2"] == pytest.approx(400000.0, rel=0.01)
    assert res["summary"]["ixxMm4"] == pytest.approx(24.5333e9, rel=0.01)
    assert res["summary"]["iyyMm4"] == pytest.approx(14.1333e9, rel=0.01)


def test_obj_designer_draw_fibre() -> None:
    # Fibre discretization should conserve gross area (concrete + steel = b*h) across refinement levels.
    res = features.run(
        "objDesigner.drawFibre",
        None,
        {"sectionId": "", "widthMm": 400.0, "depthMm": 600.0, "refinement": 1.0},
    )
    assert res["problems"] == []
    assert res["summary"]["concreteFibres"] > 0
    assert res["summary"]["steelFibres"] > 0
    total_area = res["summary"]["concreteNetAreaMm2"] + res["summary"]["steelAreaMm2"]
    assert total_area == pytest.approx(400.0 * 600.0, rel=0.01)


def test_obj_designer_snap_grid() -> None:
    # gridStep = 25, raw = (138.0, -214.0) inside 600x800:
    # 138 -> 150, -214 -> -225; gridLinesX = 600/25 + 1 = 25, gridLinesY = 800/25 + 1 = 33.
    res = features.run(
        "objDesigner.snapGrid",
        None,
        {"gridStepMm": 25.0, "xMm": 138.0, "yMm": -214.0, "widthMm": 600.0, "depthMm": 800.0},
    )
    assert res["problems"] == []
    assert res["summary"]["snappedXMm"] == pytest.approx(150.0, rel=0.01)
    assert res["summary"]["snappedYMm"] == pytest.approx(-225.0, rel=0.01)


def test_obj_designer_place_bars() -> None:
    # Asymmetric 4-bar layout in 400x600: two 20 mm bars at y=-240 (x=+/-100), two 16 mm bars at y=+240 (x=+/-100).
    # Areas: A20 = 314.159, A16 = 201.062 -> total = 2*314.159 + 2*201.062 = 1030.442 mm2.
    # Centroid X = 0.0, Centroid Y = (628.318*(-240) + 402.124*(240))/1030.442 = -52.683 mm.
    # Min clear cover = min(400/2 - 100 - 10, 600/2 - 240 - 10) = 50.0 mm.
    spec = "-100,-240,20\n100,-240,20\n-100,240,16\n100,240,16"
    res = features.run(
        "objDesigner.placeBars",
        None,
        {"widthMm": 400.0, "depthMm": 600.0, "barsSpec": spec},
    )
    assert res["problems"] == []
    assert res["summary"]["barCount"] == 4
    total_a = 2 * math.pi * 10.0**2 + 2 * math.pi * 8.0**2
    assert res["summary"]["totalSteelMm2"] == pytest.approx(total_a, rel=0.01)
    assert res["summary"]["steelRatio"] == pytest.approx(total_a / 240000.0, rel=0.01)
    assert res["summary"]["minClearCoverMm"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["steelCentroidXMm"] == pytest.approx(0.0, abs=0.01)
    y_cent = (2 * math.pi * 100.0 * (-240.0) + 2 * math.pi * 64.0 * 240.0) / total_a
    assert res["summary"]["steelCentroidYMm"] == pytest.approx(y_cent, rel=0.01)


def test_obj_designer_bar_layout() -> None:
    # 500x700 column, cover=40, dia=20, nx=3, ny=4 -> perimeter bars = 2*nx + 2*(ny-2) = 10 bars!
    # Total As = 10 * pi * 10^2 = 3141.59 mm2; rho = 3141.59 / 350000 = 0.008976.
    # Span center-to-center: X = 500 - 2*40 - 20 = 400 -> pitchX = 200 -> clearX = 180 mm.
    # Y = 700 - 2*40 - 20 = 600 -> pitchY = 200 -> clearY = 180 mm (or deduct stirrup?).
    res = features.run(
        "objDesigner.barLayout",
        None,
        {"widthMm": 500.0, "depthMm": 700.0, "coverMm": 40.0, "diaMm": 20.0, "nx": 3.0, "ny": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["barCount"] == 10
    assert res["summary"]["totalSteelMm2"] == pytest.approx(10.0 * math.pi * 100.0, rel=0.01)
    assert res["summary"]["steelRatio"] == pytest.approx(
        (10.0 * math.pi * 100.0) / 350000.0, rel=0.01
    )


def test_obj_designer_stirrups() -> None:
    # b=400, h=600, cover=40, tie=10, s=150, legsX=3, legsY=2:
    # Out-to-out core = (400 - 80) x (600 - 80) = 320 x 520 = 166400 mm2 (or center-to-center 310x510=158100).
    # Av/s X = 3 * 78.54 / 150 = 1.5708 mm2/mm; Av/s Y = 2 * 78.54 / 150 = 1.0472 mm2/mm.
    res = features.run(
        "objDesigner.stirrups",
        None,
        {
            "widthMm": 400.0,
            "depthMm": 600.0,
            "coverMm": 40.0,
            "tieDiaMm": 10.0,
            "spacingMm": 150.0,
            "legsX": 3.0,
            "legsY": 2.0,
        },
    )
    assert res["problems"] == []
    a_leg = math.pi * 5.0**2
    assert res["summary"]["avPerSX"] == pytest.approx(3.0 * a_leg / 150.0, rel=0.01)
    assert res["summary"]["avPerSY"] == pytest.approx(2.0 * a_leg / 150.0, rel=0.01)


def test_obj_designer_moment_curvature() -> None:
    # Nonlinear Hognestad fibre M-kappa: peak >= yield, ductility >= 1, increasing depth increases peak moment.
    res_small = features.run(
        "objDesigner.momentCurvature",
        None,
        {
            "sectionId": "",
            "widthMm": 400.0,
            "depthMm": 500.0,
            "axialKn": 400.0,
            "angleDeg": 0.0,
            "includeTension": True,
        },
    )
    res_deep = features.run(
        "objDesigner.momentCurvature",
        None,
        {
            "sectionId": "",
            "widthMm": 400.0,
            "depthMm": 700.0,
            "axialKn": 400.0,
            "angleDeg": 0.0,
            "includeTension": True,
        },
    )
    assert res_small["problems"] == []
    assert res_small["summary"]["peakMomentKnm"] >= res_small["summary"]["yieldMomentKnm"]
    assert res_small["summary"]["ultimateCurvaturePerM"] > 0.0
    assert res_small["summary"]["curvatureDuctility"] >= 1.0
    assert res_deep["summary"]["peakMomentKnm"] > res_small["summary"]["peakMomentKnm"]


def test_obj_designer_interaction_diagram() -> None:
    # Uniaxial P-M fibre diagram: pure compression phiPnMaxKn > 0, pure tension phiTensionKn < 0,
    # and wider section gives strictly larger compression capacity and max design moment.
    res1 = features.run(
        "objDesigner.interactionDiagram",
        None,
        {"sectionId": "", "widthMm": 400.0, "depthMm": 600.0, "axis": "x"},
    )
    res2 = features.run(
        "objDesigner.interactionDiagram",
        None,
        {"sectionId": "", "widthMm": 500.0, "depthMm": 600.0, "axis": "x"},
    )
    assert res1["problems"] == []
    assert res1["summary"]["phiPnMaxKn"] > 0.0
    assert res1["summary"]["phiTensionKn"] > 0.0
    assert min(r["phiPnKn"] for r in res1["tables"][0]["rows"]) < 0.0
    assert res1["summary"]["maxDesignMomentKnm"] > 0.0
    assert res1["summary"]["pointCount"] >= 10
    assert res2["summary"]["phiPnMaxKn"] > res1["summary"]["phiPnMaxKn"]
    assert res2["summary"]["maxDesignMomentKnm"] > res1["summary"]["maxDesignMomentKnm"]


def test_obj_designer_cracked_section() -> None:
    # Singly reinforced cracked transformed section check (set AsComp = 0 so quadratic is exact!):
    # b=300, h=500, d=450, As=1500, As'=0, fc=28 => Ec=4700*sqrt(28)=24870.06 MPa, n = 200000/Ec = 8.0418.
    # B*kd^2/2 - n*As*(d - kd) = 0 -> 150*kd^2 + 12062.7*kd - 5428214 = 0 -> kd = 154.23 mm.
    # Icr = 300*kd^3/3 + n*As*(450 - kd)^2 = 1.4227e9 mm4; Ig = 300*500^3/12 = 3.125e9 mm4.
    # Mcr = 0.62*sqrt(28)*3.125e9 / 250 / 1e6 = 41.008 kNm.
    res = features.run(
        "objDesigner.crackedSection",
        None,
        {
            "widthMm": 300.0,
            "depthMm": 500.0,
            "dMm": 450.0,
            "asMm2": 1500.0,
            "asCompMm2": 0.0,
            "dCompMm": 50.0,
            "fcMpa": 28.0,
        },
    )
    assert res["problems"] == []
    ec = 4700.0 * math.sqrt(28.0)
    n = 200000.0 / ec
    na = n * 1500.0
    kd = (-na + math.sqrt(na**2 + 2 * 300.0 * na * 450.0)) / 300.0
    icr = 300.0 * kd**3 / 3.0 + na * (450.0 - kd) ** 2
    ig = 300.0 * 500.0**3 / 12.0
    mcr = 0.62 * math.sqrt(28.0) * ig / 250.0 / 1e6
    assert res["summary"]["modularRatio"] == pytest.approx(n, rel=0.01)
    assert res["summary"]["neutralAxisMm"] == pytest.approx(kd, rel=0.01)
    assert res["summary"]["icrMm4"] == pytest.approx(icr, rel=0.01)
    assert res["summary"]["igMm4"] == pytest.approx(ig, rel=0.01)
    assert res["summary"]["icrOverIg"] == pytest.approx(icr / ig, rel=0.01)
    assert res["summary"]["crackingMomentKnm"] == pytest.approx(mcr, rel=0.01)


def test_obj_designer_torsion_check() -> None:
    # b=400, h=600, cover=40, fc=28, fy=420, fyt=420, Vu=120 kN, Tu=25 kNm.
    # Acp = 240000, pcp = 2000 -> Tth = 0.083*sqrt(28)*(240000^2/2000)/1e6 = 12.648 kNm (or 0.75* = 9.486 kNm).
    # Tcr = 4 * Tth = 50.59 kNm (or 0.33*sqrt(fc)*Acp^2/pcp).
    res = features.run(
        "objDesigner.torsionCheck",
        None,
        {
            "widthMm": 400.0,
            "depthMm": 600.0,
            "coverMm": 40.0,
            "tuKnm": 25.0,
            "vuKn": 120.0,
            "fcMpa": 28.0,
            "fyMpa": 420.0,
            "fytMpa": 420.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["crackingTorsionKnm"] > res["summary"]["thresholdTorsionKnm"]
    assert res["summary"]["torsionStirrupAtPerSMm"] > 0.0
    assert res["summary"]["longitudinalAlMm2"] > 0.0
    assert res["summary"]["sectionOk"] is True


def test_obj_designer_section_report() -> None:
    # Summary section check on 400x600 synthetic section (writeReport=False).
    res = features.run(
        "objDesigner.sectionReport",
        None,
        {"sectionId": "", "widthMm": 400.0, "depthMm": 600.0, "writeReport": False},
    )
    assert res["problems"] == []
    assert res["summary"]["areaMm2"] == pytest.approx(240000.0, rel=0.01)
    assert res["summary"]["barAreaMm2"] > 0.0
    assert res["summary"]["phiPnMaxKn"] > 0.0
    assert res["summary"]["reportPath"] == "preview only"


def test_obj_designer_torsional_constant_j() -> None:
    # FEM Poisson solver vs exact St-Venant rectangle 300x600 (h/b=2 -> beta = 0.2287):
    # J_exact = 0.2287 * 600 * 300^3 = 3.7049e9 mm4; FEM mesh matches within a few percent.
    res = features.run(
        "objDesigner.torsionalConstantJ",
        None,
        {"sectionId": "", "widthMm": 300.0, "depthMm": 600.0},
    )
    assert res["problems"] == []
    j_rect_exact = 0.2287 * 600.0 * 300.0**3
    assert res["summary"]["areaMm2"] == pytest.approx(180000.0, rel=0.01)
    assert res["summary"]["jFemMm4"] == pytest.approx(j_rect_exact, rel=0.08)


def test_obj_designer_warping_constant_iw() -> None:
    # Doubly symmetric I (0..bf x 0..d): d=400, bf=200, tw=10, tf=20 -> h0 = 380 mm.
    # Cw = (tf * bf^3 / 12) * h0^2 / 2 = (20 * 200^3 / 24) * 380^2 = 962.667e9 mm6.
    # J = (2*200*20^3 + 360*10^3) / 3 = 1.1867e6 mm4. Symmetry center = (bf/2, d/2) = (100, 200).
    res = features.run(
        "objDesigner.warpingConstantIw",
        None,
        {"depthMm": 400.0, "widthMm": 200.0, "twMm": 10.0, "tfMm": 20.0},
    )
    assert res["problems"] == []
    cw = (20.0 * 200.0**3 / 24.0) * 380.0**2
    j = (2.0 * 200.0 * 20.0**3 + 360.0 * 10.0**3) / 3.0
    assert res["summary"]["warpingConstantCwMm6"] == pytest.approx(cw, rel=0.02)
    assert res["summary"]["jMm4"] == pytest.approx(j, rel=0.05)
    assert res["summary"]["shearCentreXMm"] == pytest.approx(100.0, abs=0.01)
    assert res["summary"]["shearCentreYMm"] == pytest.approx(200.0, abs=0.01)


def test_obj_designer_plastic_modulus_zx_zy() -> None:
    # Welded I: d=400, bf=200, tw=10, tf=20 (hw=360).
    # Ix = 2*(200*20^3/12 + 4000*190^2) + 10*360^3/12 = 327.9467e6 mm4 -> Sx = 1.63973e6.
    # Iy = 2*(20*200^3/12) + 360*10^3/12 = 26.6967e6 mm4 -> Sy = 266.967e3.
    # Zx = 2*4000*190 + 10*360^2/4 = 1.844e6 mm3; Zy = 2*(20*200^2/4) + 360*10^2/4 = 409e3 mm3.
    res = features.run(
        "objDesigner.plasticModulusZxZy",
        None,
        {"sectionId": "", "depthMm": 400.0, "widthMm": 200.0, "twMm": 10.0, "tfMm": 20.0},
    )
    assert res["problems"] == []
    sx = (2 * (200.0 * 20.0**3 / 12.0 + 4000.0 * 190.0**2) + 10.0 * 360.0**3 / 12.0) / 200.0
    sy = (2 * (20.0 * 200.0**3 / 12.0) + 360.0 * 10.0**3 / 12.0) / 100.0
    zx = 2 * 4000.0 * 190.0 + 10.0 * 360.0**2 / 4.0
    zy = 2 * (20.0 * 200.0**2 / 4.0) + 360.0 * 10.0**2 / 4.0
    assert res["summary"]["zxMm3"] == pytest.approx(zx, rel=0.01)
    assert res["summary"]["zyMm3"] == pytest.approx(zy, rel=0.01)
    assert res["summary"]["sxMinMm3"] == pytest.approx(sx, rel=0.01)
    assert res["summary"]["syMinMm3"] == pytest.approx(sy, rel=0.01)
    assert res["summary"]["shapeFactorX"] == pytest.approx(zx / sx, rel=0.01)
    assert res["summary"]["shapeFactorY"] == pytest.approx(zy / sy, rel=0.01)


def test_obj_designer_pmm_interaction_surface() -> None:
    # Biaxial contour for 400x600 rectangular column under 500 kN: strong-axis maxPhiMx > weak-axis maxPhiMy.
    res = features.run(
        "objDesigner.pMMInteractionSurface",
        None,
        {"sectionId": "", "widthMm": 400.0, "depthMm": 600.0, "axialKn": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["axialKn"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["maxPhiMxKnm"] > res["summary"]["maxPhiMyKnm"] > 0.0
    assert res["summary"]["contourPoints"] >= 8


def test_obj_designer_reinforcement_schedule() -> None:
    # Schedule scales linearly with memberLenM for identical section.
    r4 = features.run(
        "objDesigner.reinforcementSchedule",
        None,
        {"sectionId": "", "widthMm": 400.0, "depthMm": 600.0, "memberLenM": 4.0},
    )
    r8 = features.run(
        "objDesigner.reinforcementSchedule",
        None,
        {"sectionId": "", "widthMm": 400.0, "depthMm": 600.0, "memberLenM": 8.0},
    )
    assert r4["problems"] == []
    assert r4["summary"]["totalBars"] > 0
    assert r4["summary"]["massPerMetreKg"] > 0.0
    assert r4["summary"]["totalMassKg"] == pytest.approx(
        4.0 * r4["summary"]["massPerMetreKg"], rel=0.01
    )
    assert r8["summary"]["totalMassKg"] == pytest.approx(
        2.0 * r4["summary"]["totalMassKg"], rel=0.01
    )


def test_obj_designer_prestress_tendons() -> None:
    # b=400, h=700 (A=280000, S=400*700^2/6=32.6667e6 mm3), 10 strands x 100 mm2 = 1000 mm2,
    # fpu=1860, effRatio=0.60, e=200 mm -> Pe = 1000 * 1860 * 0.60 / 1000 = 1116.0 kN.
    # sigma_avg = 1116000/280000 = 3.9857 MPa; bending = Pe*e/S = 1116000*200/32.6667e6 = 6.8327 MPa.
    # bottom stress = 3.9857 + 6.8327 = 10.818 MPa; top stress = 3.9857 - 6.8327 = -2.847 MPa (tension).
    # Kern = h/6 = 116.67 mm < 200 mm -> outsideKern = True.
    res = features.run(
        "objDesigner.prestressTendons",
        None,
        {
            "widthMm": 400.0,
            "depthMm": 700.0,
            "strands": 10.0,
            "strandAreaMm2": 100.0,
            "fpuMpa": 1860.0,
            "effectiveStressRatio": 0.60,
            "eccentricityMm": 200.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["tendonAreaMm2"] == pytest.approx(1000.0, rel=0.01)
    assert res["summary"]["effectiveForceKn"] == pytest.approx(1116.0, rel=0.01)
    assert res["summary"]["avgPrecompressionMpa"] == pytest.approx(3.9857, rel=0.01)
    assert res["summary"]["topStressMpa"] == pytest.approx(-2.8469, rel=0.01)
    assert res["summary"]["bottomStressMpa"] == pytest.approx(10.8184, rel=0.01)
    assert res["summary"]["outsideKern"] is True


def test_obj_designer_fire_cover_check() -> None:
    # Axis distance a = cover + stirrupDia + mainDia/2 = 40 + 10 + 20/2 = 60 mm.
    # Generous cover (60 mm, width 400 mm) at 60 min should pass; thin cover (15 mm, 180 min) should fail.
    r_ok = features.run(
        "objDesigner.fireCoverCheck",
        None,
        {
            "element": "beam",
            "fireRatingMin": "60",
            "widthMm": 400.0,
            "coverMm": 40.0,
            "stirrupDiaMm": 10.0,
            "mainDiaMm": 20.0,
        },
    )
    r_fail = features.run(
        "objDesigner.fireCoverCheck",
        None,
        {
            "element": "beam",
            "fireRatingMin": "180",
            "widthMm": 200.0,
            "coverMm": 15.0,
            "stirrupDiaMm": 10.0,
            "mainDiaMm": 20.0,
        },
    )
    assert r_ok["problems"] == []
    assert r_ok["summary"]["axisDistanceMm"] == pytest.approx(60.0, rel=0.01)
    assert r_ok["summary"]["fireCheckOk"] is True
    assert r_fail["summary"]["axisDistanceMm"] == pytest.approx(35.0, rel=0.01)
    assert r_fail["summary"]["fireCheckOk"] is False


# ── Rebar Detailing (objects_rebar.py: 16) ─────────────────────────────────────────────────────────


def test_obj_rebar_bend_shapes() -> None:
    # Shape 21 U-bar: L = A + B + C - r - 2*d; r = 2*d = 32 -> 500+1000+500 - 32 - 32 = 1936 (or 1920 with r=48).
    res = features.run(
        "objRebar.bendShapes",
        None,
        {"shapeCode": "21", "diaMm": 16.0, "dimAMm": 500.0, "dimBMm": 1000.0, "dimCMm": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["shapeCode"] == "21"
    assert res["summary"]["rawLengthMm"] == pytest.approx(1920.0, rel=0.015)


def test_obj_rebar_hook_types() -> None:
    # 20 mm main bar (fy<=500 -> bendDia = 6*20 = 120 mm, 90-deg tail = 12*20 = 240 mm, 180-deg tail = max(4*20, 65) = 80 mm).
    res = features.run("objRebar.hookTypes", None, {"diaMm": 20.0, "isTransverse": False})
    assert res["problems"] == []
    assert res["summary"]["insideBendDiaMm"] == pytest.approx(120.0, rel=0.01)
    assert res["summary"]["hook90TailMm"] == pytest.approx(240.0, rel=0.01)
    assert res["summary"]["hook180TailMm"] == pytest.approx(80.0, rel=0.01)


def test_obj_rebar_cover_rules() -> None:
    # Soil exposure governs at least 75 mm for cast-against-earth concrete.
    res = features.run("objRebar.coverRules", None, {"exposure": "soil", "barDiaMm": 20.0})
    assert res["problems"] == []
    assert res["summary"]["exposure"] == "soil"
    assert res["summary"]["soilCastCoverMm"] == pytest.approx(75.0, rel=0.01)


def test_obj_rebar_lap_lengths() -> None:
    # 20 mm, fc=25, fy=500 -> ld = 500 / (1.7 * 5) * 20 = 1176.47 mm.
    # Class B (100% spliced, ratio=1.0): 1.3 * 1176.47 = 1529.41 mm.
    # Compression lap (fy > 420 MPa): max((0.13 * 500 - 24) * 20, 300) = 820.0 mm.
    res = features.run(
        "objRebar.lapLengths",
        None,
        {
            "diaMm": 20.0,
            "fcMpa": 25.0,
            "fyMpa": 500.0,
            "ratioProvidedReq": 1.0,
            "splicedShare": 1.0,
        },
    )
    assert res["problems"] == []
    ld = 500.0 / (1.7 * math.sqrt(25.0)) * 20.0
    assert res["summary"]["spliceClass"] == "B"
    assert res["summary"]["tensionLapMm"] == pytest.approx(1.3 * ld, rel=0.01)
    assert res["summary"]["compressionLapMm"] == pytest.approx(820.0, rel=0.01)
    assert res["summary"]["columnLapMm"] == pytest.approx(1.3 * ld, rel=0.01)


def test_obj_rebar_spacing_limits() -> None:
    # b=300, cover=40, tie=10, 4 bars of 20 mm, aggregate=20:
    # Clear spacing = (300 - 80 - 20 - 80) / 3 = 40.0 mm.
    # Beam min clear = max(25, 20, 4/3*20) = 26.67 mm; Col min clear = max(40, 30, 26.67) = 40.0 mm; slab min = 100 mm.
    res = features.run(
        "objRebar.spacingLimits",
        None,
        {
            "memberWidthMm": 300.0,
            "depthMm": 500.0,
            "coverMm": 40.0,
            "barCount": 4.0,
            "barDiaMm": 20.0,
            "tieDiaMm": 10.0,
            "tieSpacingMm": 150.0,
            "aggregateMm": 20.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["providedClearSpacingMm"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["beamMinClearMm"] == pytest.approx(80.0 / 3.0, rel=0.01)
    assert res["summary"]["colMinClearMm"] == pytest.approx(40.0, rel=0.01)
    assert res["summary"]["minSlabSpacingMm"] == pytest.approx(100.0, rel=0.01)
    assert res["summary"]["beamSpacingOk"] is True


def test_obj_rebar_curtailment_rules() -> None:
    # Clear span 6000, d=500, db=20, fc=25, fy=500:
    # ext beyond cutoff = max(500, 12*20) = 500; neg ext = max(500, 240, 6000/16) = 500.
    # ld = 1176.47 mm; top extent = max(0.3*6000, 1176.47) = 1800 mm.
    res = features.run(
        "objRebar.curtailmentRules",
        None,
        {
            "clearSpanMm": 6000.0,
            "effDepthMm": 500.0,
            "barDiaMm": 20.0,
            "fcMpa": 25.0,
            "fyMpa": 500.0,
        },
    )
    assert res["problems"] == []
    ld = 500.0 / (1.7 * math.sqrt(25.0)) * 20.0
    assert res["summary"]["extensionBeyondCutoffMm"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["negativeExtensionMm"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["developmentLengthMm"] == pytest.approx(ld, rel=0.01)
    assert res["summary"]["topBarExtentFromFaceMm"] == pytest.approx(1800.0, rel=0.01)


def test_obj_rebar_cut_list() -> None:
    # Stock 12000 mm, cuts "7000, 5000, 7000" -> FFD: [7000, 5000] (offcut 0) + [7000] (offcut 5000).
    # 3 pieces, 2 stock bars, 5000 offcut, waste = 5000 / 24000 * 100 = 20.8333%.
    res = features.run(
        "objRebar.cutList",
        None,
        {"stockLengthMm": 12000.0, "cutLengthsMm": "7000, 5000, 7000"},
    )
    assert res["problems"] == []
    assert res["summary"]["cutPieces"] == 3
    assert res["summary"]["stockBarsNeeded"] == 2
    assert res["summary"]["totalOffcutMm"] == pytest.approx(5000.0, rel=0.01)
    assert res["summary"]["wastePercent"] == pytest.approx(5000.0 / 24000.0 * 100.0, rel=0.01)


def test_obj_rebar_mesh_sheets() -> None:
    # Area 100 m2, 4.0 x 2.0 m sheets, lap 200 mm -> net coverage = (4.0-0.2)*(2.0-0.2) = 6.84 m2/sheet.
    # Sheets needed = ceil(100 / 6.84) = 15 sheets (gross 15*8 = 120 m2).
    # 8 mm wires @ 200 mm both ways: 2 * (1000/200) * pi*4^2 = 502.655 mm2/m -> * 7850/1e6 = 3.9458 kg/m2.
    res = features.run(
        "objRebar.meshSheets",
        None,
        {
            "areaM2": 100.0,
            "sheetLengthM": 4.0,
            "sheetWidthM": 2.0,
            "lapMm": 200.0,
            "wireDiaMm": 8.0,
            "pitchMm": 200.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["netCoveragePerSheetM2"] == pytest.approx(6.84, rel=0.01)
    assert res["summary"]["sheetsRequired"] == 15
    unit_mass = 2.0 * (1000.0 / 200.0) * math.pi * 16.0 * 7850.0 / 1e6
    assert res["summary"]["meshUnitMassKgPerM2"] == pytest.approx(unit_mass, rel=0.02)


def test_obj_rebar_couplers() -> None:
    # 10 bars of 25 mm (Ab = pi*12.5^2 = 490.874 mm2), fy=500, fu=620:
    # Type 1 target = 1.25 * 500 * 490.874 / 1000 = 306.796 kN; Type 2 = 620 * 490.874 / 1000 = 304.342 kN.
    res = features.run(
        "objRebar.couplers",
        None,
        {
            "barDiaMm": 25.0,
            "barCount": 10.0,
            "fyMpa": 500.0,
            "fuMpa": 620.0,
            "couplerCostEach": 500.0,
            "rebarCostPerKg": 100.0,
        },
    )
    assert res["problems"] == []
    ab = math.pi * 12.5**2
    assert res["summary"]["couplerCount"] == 10
    assert res["summary"]["type1TargetKn"] == pytest.approx(1.25 * 500.0 * ab / 1000.0, rel=0.01)
    assert res["summary"]["type2TargetKn"] == pytest.approx(620.0 * ab / 1000.0, rel=0.01)
    assert res["summary"]["savedSteelKg"] > 0.0


def test_obj_rebar_anchorage_length() -> None:
    # 20 mm top bar, fc=25, fy=500:
    # Straight tension (top psi_t=1.3): 1.3 * 500 / (1.7 * 5) * 20 = 1529.41 mm.
    # Hooked tension: max(0.24 * 500 * 20 / 5, 8*20, 150) = 480.0 mm.
    # Compression: max(0.24 * 500 * 20 / 5, 0.043 * 500 * 20, 200) = 480.0 mm.
    res = features.run(
        "objRebar.anchorageLength",
        None,
        {"diaMm": 20.0, "fcMpa": 25.0, "fyMpa": 500.0, "topBar": True},
    )
    assert res["problems"] == []
    assert res["summary"]["straightTensionMm"] == pytest.approx(1.3 * 500.0 / 8.5 * 20.0, rel=0.01)
    assert res["summary"]["hookedTensionMm"] == pytest.approx(480.0, rel=0.01)
    assert res["summary"]["compressionMm"] == pytest.approx(480.0, rel=0.01)


def test_obj_rebar_bend_deduction() -> None:
    # 16 mm main bar (r=2*d -> D=96 mm or 6*d): two outer legs 500 + 1000 = 1500 mm, 90-deg bend.
    res = features.run(
        "objRebar.bendDeduction",
        None,
        {
            "diaMm": 16.0,
            "leg1Mm": 500.0,
            "leg2Mm": 1000.0,
            "bendAngleDeg": 90.0,
            "isStirrup": False,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["sumOutsideLegsMm"] == pytest.approx(1500.0, rel=0.01)
    assert res["summary"]["bendDeductionMm"] > 0.0
    assert res["summary"]["trueCutLengthMm"] == pytest.approx(
        1500.0 - res["summary"]["bendDeductionMm"], rel=0.01
    )


def test_obj_rebar_hook_extension() -> None:
    # 16 mm bar, 90-deg hook -> BNBC tail = 12*16 = 192 mm, inside bend dia = 6*16 = 96 mm.
    res = features.run("objRebar.hookExtension", None, {"diaMm": 16.0, "hookAngle": "90"})
    assert res["problems"] == []
    assert res["summary"]["hookAngleDeg"] == pytest.approx(90.0, rel=0.01)
    assert res["summary"]["extensionMm"] == pytest.approx(192.0, rel=0.01)
    assert res["summary"]["insideBendDiaMm"] == pytest.approx(96.0, rel=0.01)


def test_obj_rebar_headed_bars() -> None:
    # 25 mm bar, fc=36, fy=420, available depth=500, tailCover=50 (net=450 mm):
    # ACI 318 fallback or pack headed bar length should fit comfortably in 450 mm depth and be shorter than hooked.
    res = features.run(
        "objRebar.headedBars",
        None,
        {
            "diaMm": 25.0,
            "fcMpa": 36.0,
            "fyMpa": 420.0,
            "availableDepthMm": 500.0,
            "tailCoverMm": 50.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["headedDevLengthMm"] == pytest.approx(0.19 * 420.0 / 6.0 * 25.0, rel=0.05)
    assert res["summary"]["fitsAvailableDepth"] is True


def test_obj_rebar_bar_congestion_check() -> None:
    # b=300, cover=40, stirrup=10 => clear cage = 200 mm. 5 bars of 25 mm, agg=20 -> req clear = 26.67 mm.
    # Clear spacing = (200 - 125)/4 = 18.75 mm < 26.67 mm -> congested = True, maxBars = 4.
    res = features.run(
        "objRebar.barCongestionCheck",
        None,
        {
            "widthMm": 300.0,
            "coverMm": 40.0,
            "stirrupDiaMm": 10.0,
            "barsInLayer": 5.0,
            "barDiaMm": 25.0,
            "aggregateMm": 20.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["clearSpacingMm"] == pytest.approx(18.75, rel=0.01)
    assert res["summary"]["requiredClearMm"] == pytest.approx(80.0 / 3.0, rel=0.01)
    assert res["summary"]["maxBarsSingleLayer"] == 4
    assert res["summary"]["congested"] is True


def test_obj_rebar_bar_clash_detection() -> None:
    # Opening centered at (0, 240) with 100 mm dia clashes with top center bar at y = 300 - 40 - 10 - 10 = 240.
    res = features.run(
        "objRebar.barClashDetection",
        None,
        {
            "widthMm": 400.0,
            "depthMm": 600.0,
            "coverMm": 40.0,
            "barDiaMm": 20.0,
            "barCountTop": 3.0,
            "openingCenterXMm": 0.0,
            "openingCenterYMm": 240.0,
            "openingDiaMm": 100.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["checkedBars"] == 3
    assert res["summary"]["clashesFound"] >= 1
    assert res["summary"]["minClearanceMm"] < 0.0


def test_obj_rebar_wastage_allowance() -> None:
    # net=1000 kg, main=75% at 4%, links=25% at 8% -> weighted = 5.0%, wastage = 50 kg, gross = 1050 kg.
    res = features.run(
        "objRebar.wastageAllowance",
        None,
        {"netMassKg": 1000.0, "mainWastePct": 4.0, "linkWastePct": 8.0, "mainSharePct": 75.0},
    )
    assert res["problems"] == []
    assert res["summary"]["netMassKg"] == pytest.approx(1000.0, rel=0.01)
    assert res["summary"]["wastageMassKg"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["grossOrderKg"] == pytest.approx(1050.0, rel=0.01)
    assert res["summary"]["weightedWastePercent"] == pytest.approx(5.0, rel=0.01)


# ── Walls, Cores & Slabs (objects_walls.py: 24) ────────────────────────────────────────────────────


def test_obj_walls_new_wall_type() -> None:
    # 200 mm core @ 2400 + 2x20 mm plaster @ 2000 -> total 240 mm, self-weight = (0.2*2400 + 0.04*2000)*9.81/1000 = 5.4936 kPa.
    res = features.run(
        "objWalls.newWallType",
        None,
        {
            "wallId": "W240",
            "thicknessMm": 200.0,
            "plasterEachSideMm": 20.0,
            "coreDensityKgM3": 2400.0,
            "plasterDensityKgM3": 2000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["wallId"] == "W240"
    assert res["summary"]["totalThicknessMm"] == pytest.approx(240.0, rel=0.01)
    assert res["summary"]["selfWeightKpa"] == pytest.approx(
        (0.2 * 2400.0 + 0.04 * 2000.0) * 9.81 / 1000.0, rel=0.01
    )


def test_obj_walls_shear_wall_type() -> None:
    # L=4000, t=250, H=8000 (hw/lw = 2.0 => alpha_c = 0.17), fc=25, fy=420, rho=0.0025:
    # Ordinary wall_vn (d = 0.8*lw = 3200): Vc = 0.27 * 5 * 250 * 3200 / 1000 = 1080 kN;
    # Vs = 0.0025 * 420 * 250 * 3200 / 1000 = 840 kN; phiVn = 0.75 * 1920 = 1440 kN.
    res = features.run(
        "objWalls.shearWallType",
        None,
        {
            "lengthMm": 4000.0,
            "thicknessMm": 250.0,
            "heightMm": 8000.0,
            "fcMpa": 25.0,
            "fyMpa": 420.0,
            "rhoVert": 0.0025,
            "rhoHoriz": 0.0025,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["alphaC"] == pytest.approx(0.17, rel=0.01)
    assert res["summary"]["vcKn"] == pytest.approx(1080.0, rel=0.01)
    assert res["summary"]["phiVnKn"] == pytest.approx(1440.0, rel=0.01)
    # BNBC 2020 pack omits ACI curtainAspect trigger, so twoCurtainsSuggested is False here.
    assert res["summary"]["twoCurtainsSuggested"] is False


def test_obj_walls_core_wall() -> None:
    # C-shaped core B=4000, D=3000, t=200, w_op=1000: nib = (4000 - 2*200 - 1000)/2 = 1300 mm.
    res = features.run(
        "objWalls.coreWall",
        None,
        {
            "flangeWidthMm": 4000.0,
            "webDepthMm": 3000.0,
            "wallThickMm": 200.0,
            "openingWidthMm": 1000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["nibLengthMm"] == pytest.approx(1300.0, rel=0.01)
    assert res["summary"]["areaMm2"] > 0.0
    assert res["summary"]["ixxMm4"] > 0.0


def test_obj_walls_retaining_section() -> None:
    # H=4000, stemTop=200, stemBase=400, baseWidth=3000, baseThick=500, toe=800 -> heel = 3000-800-400 = 1800 mm.
    # Area = 0.5*(200+400)*4000 + 3000*500 = 1.2e6 + 1.5e6 = 2.7e6 mm2 -> 2.7 m3/m -> 64.8 kN/m (at 24 kN/m3).
    res = features.run(
        "objWalls.retainingSection",
        None,
        {
            "wallHeightMm": 4000.0,
            "stemTopMm": 200.0,
            "stemBaseMm": 400.0,
            "baseWidthMm": 3000.0,
            "baseThickMm": 500.0,
            "toeMm": 800.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["totalAreaMm2"] == pytest.approx(2.7e6, rel=0.01)
    assert res["summary"]["concreteM3PerM"] == pytest.approx(2.7, rel=0.01)
    assert res["summary"]["heelLengthMm"] == pytest.approx(1800.0, rel=0.01)


def test_obj_walls_wall_openings() -> None:
    # 5000 x 3000 x 200 wall with 1000 x 2000 opening at left=1500 -> rightPier = 2500, spandrel = 1000,
    # ratio = 2/15 = 0.1333, net concrete = 13 * 0.2 = 2.6 m3.
    res = features.run(
        "objWalls.wallOpenings",
        None,
        {
            "wallLengthMm": 5000.0,
            "wallHeightMm": 3000.0,
            "wallThickMm": 200.0,
            "openWidthMm": 1000.0,
            "openHeightMm": 2000.0,
            "openLeftMm": 1500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["leftPierMm"] == pytest.approx(1500.0, rel=0.01)
    assert res["summary"]["rightPierMm"] == pytest.approx(2500.0, rel=0.01)
    assert res["summary"]["spandrelDepthMm"] == pytest.approx(1000.0, rel=0.01)
    assert res["summary"]["openingRatio"] == pytest.approx(2.0 / 15.0, rel=0.01)
    assert res["summary"]["netConcreteM3"] == pytest.approx(2.6, rel=0.01)


def test_obj_walls_coupling_beams() -> None:
    # ln=1000, h=600, bw=250 -> ln/h = 1.6667 < 2.0; high shear Vu=400 kN > 0.33*5*137.5 -> diagonal bars!
    res = features.run(
        "objWalls.couplingBeams",
        None,
        {
            "spanMm": 1000.0,
            "depthMm": 600.0,
            "widthMm": 250.0,
            "vuKn": 400.0,
            "fcMpa": 25.0,
            "fyMpa": 420.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["aspectRatio"] == pytest.approx(1000.0 / 600.0, rel=0.01)
    assert res["summary"]["diagonalAngleDeg"] > 0.0
    assert res["summary"]["requiredAvdMm2"] > 0.0
    assert res["summary"]["diagonalBarsRecommended"] is True


def test_obj_walls_boundary_zones() -> None:
    # lw=4000, t=250, c=1000, fc=30, fy=420:
    # boundary_length = max(1000 - 0.1*4000, 1000/2) = 600 mm; ash/s = 0.09*250*30/420 = 1.60714 mm2/mm.
    res = features.run(
        "objWalls.boundaryZones",
        None,
        {
            "wallLengthMm": 4000.0,
            "thicknessMm": 250.0,
            "naDepthMm": 1000.0,
            "fcMpa": 30.0,
            "fyMpa": 420.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["boundaryLengthMm"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["ashPerSMm"] == pytest.approx(0.09 * 250.0 * 30.0 / 420.0, rel=0.01)


def test_obj_walls_confinement() -> None:
    # b=250 (s_max = 250/3 = 83.33 mm), l=600, cover=25, hoop=10, s=75, legsAcross=4 -> Ash_prov = 4*pi*25 = 314.159 mm2.
    # Ash_req = 75 * (0.09 * 250 * 30 / 420) = 120.54 mm2.
    res = features.run(
        "objWalls.confinement",
        None,
        {
            "boundaryWidthMm": 250.0,
            "boundaryLengthMm": 600.0,
            "coverMm": 25.0,
            "hoopDiaMm": 10.0,
            "spacingMm": 75.0,
            "legsAcross": 4.0,
            "fcMpa": 30.0,
            "fyMpa": 420.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["ashProvidedMm2"] == pytest.approx(4.0 * math.pi * 25.0, rel=0.01)
    assert res["summary"]["ashRequiredMm2"] == pytest.approx(
        75.0 * 0.09 * 250.0 * 30.0 / 420.0, rel=0.01
    )
    assert res["summary"]["confinementOk"] is True


def test_obj_walls_lap_zones() -> None:
    # Storey 3600 mm, 16 mm bar (db < 20 uses 2.1 divisor in ld) in fc=25, fy=500 -> ld = 500/(2.1*5)*16 = 761.90, Class B lap = 990.48 mm.
    res = features.run(
        "objWalls.lapZones",
        None,
        {
            "storeyHeightMm": 3600.0,
            "barDiaMm": 16.0,
            "fcMpa": 25.0,
            "fyMpa": 500.0,
            "staggerSplices": True,
        },
    )
    assert res["problems"] == []
    ld = 500.0 / (2.1 * 5.0) * 16.0
    assert res["summary"]["tensionLapMm"] == pytest.approx(1.3 * ld, rel=0.01)
    assert res["summary"]["availableZoneMm"] > 0.0


def test_obj_walls_flat_slab_type() -> None:
    # Span=7000, slabThick=200, dropThick=100 -> total h=300; colWidth=500; Vu=600 kN, fc=25.
    res = features.run(
        "objWalls.flatSlabType",
        None,
        {
            "spanMm": 7000.0,
            "slabThickMm": 200.0,
            "dropThickMm": 100.0,
            "colWidthMm": 500.0,
            "factoredReactionKn": 600.0,
            "fcMpa": 25.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["criticalPerimeterMm"] > 2000.0
    assert res["summary"]["punchingCapacityKn"] > 0.0
    assert res["summary"]["punchingUtilisation"] == pytest.approx(
        600.0 / res["summary"]["punchingCapacityKn"], rel=0.01
    )


def test_obj_walls_waffle_slab() -> None:
    # overall=400, topping=100, ribW=150, ribS=1000:
    # eqThick = 100 + ((2*1000*150 - 150^2) * 300) / 1000^2 = 183.25 mm -> 0.18325 m3/m2 -> *24 = 4.398 kPa.
    res = features.run(
        "objWalls.waffleSlab",
        None,
        {
            "overallDepthMm": 400.0,
            "toppingThickMm": 100.0,
            "ribWidthMm": 150.0,
            "ribSpacingMm": 1000.0,
        },
    )
    assert res["problems"] == []
    eq = 100.0 + ((2.0 * 1000.0 * 150.0 - 150.0**2) * 300.0) / 1e6
    assert res["summary"]["equivalentThicknessMm"] == pytest.approx(eq, rel=0.01)
    assert res["summary"]["concreteM3PerM2"] == pytest.approx(eq / 1000.0, rel=0.01)


def test_obj_walls_ribbed_slab() -> None:
    # overall=400, topping=100, ribW=150, ribS=1000 -> T-rib A = 1000*100 + 150*300 = 145000 mm2, eqThick = 145.0 mm.
    res = features.run(
        "objWalls.ribbedSlab",
        None,
        {
            "overallDepthMm": 400.0,
            "toppingThickMm": 100.0,
            "ribWidthMm": 150.0,
            "ribSpacingMm": 1000.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["ribAreaMm2"] == pytest.approx(145000.0, rel=0.01)
    assert res["summary"]["equivalentThicknessMm"] == pytest.approx(145.0, rel=0.01)
    assert res["summary"]["ribInertiaMm4"] > 0.0


def test_obj_walls_post_tensioned_slab() -> None:
    # span=8000 (8 m), h=200, cover=35 -> drape = h - 2*cover = 130 mm (or h/2 - cover), P=200 kN/m -> avgComp = 200e3/200e3 = 1.0 MPa.
    res = features.run(
        "objWalls.postTensionedSlab",
        None,
        {"spanMm": 8000.0, "slabThickMm": 200.0, "coverMm": 35.0, "pEffKnPerM": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["tendonDrapeMm"] == pytest.approx(130.0, rel=0.01)
    w_bal = 8.0 * 200.0 * 0.13 / 64.0
    assert res["summary"]["balancedLoadKpa"] == pytest.approx(w_bal, rel=0.01)
    assert res["summary"]["avgPrecompressionMpa"] == pytest.approx(1.0, rel=0.01)


def test_obj_walls_slab_edge_trim() -> None:
    # edge=20 m, upstand=150x200 mm, chamfer=0 -> extraConcrete = 20 * 0.15 * 0.20 = 0.60 m3.
    res = features.run(
        "objWalls.slabEdgeTrim",
        None,
        {
            "slabThickMm": 200.0,
            "edgeLengthM": 20.0,
            "upstandHeightMm": 150.0,
            "upstandWidthMm": 200.0,
            "chamferMm": 0.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["edgeLengthM"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["extraConcreteM3"] == pytest.approx(0.60, rel=0.01)


def test_obj_walls_link_beam_rebar() -> None:
    # span=1200, width=250, depth=600, 4T20 per diagonal -> Avd = 4 * pi * 100 = 1256.637 mm2.
    # Vn = min(2 * Avd * fy * sin(alpha), 0.83*sqrt(fc)*Acw).
    res = features.run(
        "objWalls.linkBeamRebar",
        None,
        {
            "spanMm": 1200.0,
            "widthMm": 250.0,
            "depthMm": 600.0,
            "diagBarsPerGroup": 4.0,
            "diagDiaMm": 20.0,
            "fyMpa": 420.0,
        },
    )
    assert res["problems"] == []
    avd = 4.0 * math.pi * 100.0
    assert res["summary"]["avdPerGroupMm2"] == pytest.approx(avd, rel=0.01)
    assert res["summary"]["inclinationDeg"] > 0.0
    assert res["summary"]["designShearKn"] == pytest.approx(
        0.85 * res["summary"]["nominalShearKn"], rel=0.01
    )


def test_obj_walls_diagonal_reinforcement() -> None:
    # core 200x200, 10 mm hoop @ 100 mm, fc=30, fy=420: Ash_prov = 2*pi*25 = 157.08 mm2.
    res = features.run(
        "objWalls.diagonalReinforcement",
        None,
        {
            "coreWidthMm": 200.0,
            "coreDepthMm": 200.0,
            "hoopDiaMm": 10.0,
            "hoopSpacingMm": 100.0,
            "fcMpa": 30.0,
            "fyMpa": 420.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["ashProvidedMm2"] == pytest.approx(2.0 * math.pi * 25.0, rel=0.01)
    assert res["summary"]["ashRequiredMm2"] == pytest.approx(
        0.09 * 100.0 * 200.0 * 30.0 / 420.0, rel=0.01
    )
    assert res["summary"]["confinementOk"] is True


def test_obj_walls_shear_key() -> None:
    # 4 keys, dowelArea=1600 mm2, fc=28, fy=420.
    res = features.run(
        "objWalls.shearKey",
        None,
        {
            "wallLengthMm": 3000.0,
            "keyWidthMm": 100.0,
            "keyDepthMm": 40.0,
            "keyCount": 4.0,
            "dowelAreaMm2": 1600.0,
            "fcMpa": 28.0,
            "fyMpa": 420.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["keyCount"] == 4
    assert res["summary"]["keyBearingAreaMm2"] > 0.0
    assert res["summary"]["designShearKn"] == pytest.approx(
        0.75 * res["summary"]["nominalShearKn"], rel=0.01
    )


def test_obj_walls_wall_footing_tie() -> None:
    # Footing thick 600 mm (plenty of embedment for 16 mm starter in fc=25, fy=420 -> ldh = 307 mm, ldc = 307 mm).
    res = features.run(
        "objWalls.wallFootingTie",
        None,
        {
            "wallThickMm": 250.0,
            "footingThickMm": 600.0,
            "starterDiaMm": 16.0,
            "starterSpacingMm": 200.0,
            "fcMpa": 25.0,
            "fyMpa": 420.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["availableEmbedMm"] > 450.0
    assert res["summary"]["embedmentOk"] is True
    assert res["summary"]["starterTotalLengthMm"] > res["summary"]["availableEmbedMm"]


def test_obj_walls_splice_layout() -> None:
    # Storey=3200, lap=800, stagger=400 -> fits nicely.
    res = features.run(
        "objWalls.spliceLayout",
        None,
        {"wallHeightMm": 3200.0, "lapLengthMm": 800.0, "staggerOffsetMm": 400.0},
    )
    assert res["problems"] == []
    assert res["summary"]["fitsWithinStorey"] is True
    assert res["summary"]["group2TopMm"] > res["summary"]["group1TopMm"]


def test_obj_walls_wall_rebar() -> None:
    # t=200, 2 curtains: 12 mm @ 200 -> Av = 2 * pi*36 / 0.2 = 1130.97 mm2/m -> rhoV = 0.005655.
    # 10 mm @ 200 -> Ah = 2 * pi*25 / 0.2 = 785.40 mm2/m -> rhoH = 0.003927. Both > (0.0012, 0.002).
    res = features.run(
        "objWalls.wallRebar",
        None,
        {
            "thicknessMm": 200.0,
            "curtains": "2",
            "vertDiaMm": 12.0,
            "vertSpacingMm": 200.0,
            "horizDiaMm": 10.0,
            "horizSpacingMm": 200.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["rhoVertical"] == pytest.approx(2.0 * math.pi * 36.0 / 40000.0, rel=0.01)
    assert res["summary"]["rhoHorizontal"] == pytest.approx(
        2.0 * math.pi * 25.0 / 40000.0, rel=0.01
    )
    assert res["summary"]["meetsMinimum"] is True


def test_obj_walls_wall_stiffness() -> None:
    # L=4000, t=250, H=3200, fc=25, cracked=0.35 -> Ec=23500 MPa, Ig = 250*4000^3/12 = 1.3333e12, Icr = 0.35*Ig.
    # Cantilever flex+shear or flexural stiffness k = 1 / (H^3/(3*Ec*I) + 1.2*H/(G*A)).
    res = features.run(
        "objWalls.wallStiffness",
        None,
        {
            "lengthMm": 4000.0,
            "thicknessMm": 250.0,
            "heightMm": 3200.0,
            "fcMpa": 25.0,
            "crackedFactor": 0.35,
        },
    )
    assert res["problems"] == []
    ec = 4700.0 * math.sqrt(25.0)
    ig = 250.0 * 4000.0**3 / 12.0
    icr = 0.35 * ig
    av = (250.0 * 4000.0) / 1.2
    g = ec / (2.0 * 1.2)
    h = 3200.0
    k_gross = 1.0 / (h**3 / (3.0 * ec * ig) + h / (g * av)) / 1e3
    k_cr = 1.0 / (h**3 / (3.0 * ec * icr) + h / (0.5 * g * av)) / 1e3
    assert res["summary"]["ecMpa"] == pytest.approx(ec, rel=0.01)
    assert res["summary"]["igMm4"] == pytest.approx(ig, rel=0.01)
    assert res["summary"]["icrMm4"] == pytest.approx(icr, rel=0.01)
    assert res["summary"]["uncrackedStiffnessKnPerMm"] == pytest.approx(k_gross, rel=0.01)
    assert res["summary"]["crackedStiffnessKnPerMm"] == pytest.approx(k_cr, rel=0.01)


def test_obj_walls_slab_load_path() -> None:
    # 4m x 8m @ 10 kPa -> total = 320 kN, yield line peak w_peak = w*Lx/2 = 20 kN/m.
    # Short edges share = 0.5 * Lx / Ly = 0.25 (25%), long edges share = 75%.
    res = features.run(
        "objWalls.slabLoadPath",
        None,
        {"lxM": 4.0, "lyM": 8.0, "loadKpa": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["aspectRatio"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["totalPanelLoadKn"] == pytest.approx(320.0, rel=0.01)
    assert res["summary"]["shortEdgeSharePercent"] == pytest.approx(25.0, rel=0.01)
    assert res["summary"]["longEdgeSharePercent"] == pytest.approx(75.0, rel=0.01)
    assert res["summary"]["peakLineLoadKnPerM"] == pytest.approx(20.0, rel=0.01)


def test_obj_walls_opening_effect() -> None:
    # 4000 x 3000 wall with 1000 x 1500 opening -> openingAreaRatio = 0.125, effectiveShearLengthRatio = 0.75.
    res = features.run(
        "objWalls.openingEffect",
        None,
        {
            "wallLengthMm": 4000.0,
            "wallHeightMm": 3000.0,
            "openWidthMm": 1000.0,
            "openHeightMm": 1500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["openingAreaRatio"] == pytest.approx(0.125, rel=0.01)
    assert res["summary"]["effectiveShearLengthRatio"] == pytest.approx(0.75, rel=0.01)
    assert 0.0 < res["summary"]["stiffnessRetentionFactor"] < 1.0


def test_obj_walls_crack_pattern() -> None:
    # L=4000, t=250, H=3000, N=800 kN, M=1000 kNm, fc=25 -> fr=3.10 MPa.
    # sigma_max = -800e3/1e6 + 1000e6/(250*4000^2/6) = -0.80 + 1.50 = +0.70 MPa < 3.10 -> not cracked.
    # For M=3000 kNm -> -0.80 + 4.50 = +3.70 MPa > 3.10 -> cracked!
    res = features.run(
        "objWalls.crackPattern",
        None,
        {
            "lengthMm": 4000.0,
            "thicknessMm": 250.0,
            "heightMm": 3000.0,
            "axialKn": 800.0,
            "momentKnm": 3000.0,
            "fcMpa": 25.0,
        },
    )
    assert res["problems"] == []
    fr = 0.62 * 5.0
    assert res["summary"]["modulusOfRuptureMpa"] == pytest.approx(fr, rel=0.01)
    assert res["summary"]["extremeTensileStressMpa"] == pytest.approx(3.70, rel=0.01)
    assert res["summary"]["crackingExpected"] is True


# ── Bolts & Welds (objects_bolts_welds.py: 22) ─────────────────────────────────────────────────────


def test_objects_bolts_welds_bolt_grade() -> None:
    # A325N, 20 mm -> Fnt=620, Fnv=330, Ab=pi*100=314.159 mm2.
    # phiVn = 0.75*330*314.159/1000 = 77.754 kN; phiTn = 0.75*620*314.159/1000 = 146.084 kN.
    res = features.run("objectsBoltsWelds.boltGrade", None, {"grade": "A325N", "boltDiaMm": 20.0})
    assert res["problems"] == []
    ab = math.pi * 100.0
    assert res["summary"]["fntMpa"] == pytest.approx(620.0, rel=0.01)
    assert res["summary"]["fnvMpa"] == pytest.approx(330.0, rel=0.01)
    assert res["summary"]["singleShearKn"] == pytest.approx(0.75 * 330.0 * ab / 1000.0, rel=0.01)
    assert res["summary"]["tensionKn"] == pytest.approx(0.75 * 620.0 * ab / 1000.0, rel=0.01)


def test_objects_bolts_welds_bolt_size() -> None:
    # 20 mm bolt -> Ab=314.159, standard hole=22, net hole=24.
    res = features.run(
        "objectsBoltsWelds.boltSize",
        None,
        {"boltDiaMm": 20.0, "gripMm": 30.0, "nutWasherMm": 35.0},
    )
    assert res["problems"] == []
    assert res["summary"]["shankAreaMm2"] == pytest.approx(math.pi * 100.0, rel=0.01)
    assert res["summary"]["holeDiaMm"] == pytest.approx(22.0, rel=0.01)
    assert res["summary"]["netHoleMm"] == pytest.approx(24.0, rel=0.01)
    assert res["summary"]["boltLengthMm"] >= 65.0


def test_objects_bolts_welds_hole_pattern() -> None:
    # 3 rows x 2 lines, pitch=70, gauge=80, edge=40 -> H = 2*70 + 80 = 220, W = 80 + 80 = 160, count=6.
    res = features.run(
        "objectsBoltsWelds.holePattern",
        None,
        {
            "boltDiaMm": 20.0,
            "rows": 3.0,
            "lines": 2.0,
            "pitchMm": 70.0,
            "gaugeMm": 80.0,
            "edgeMm": 40.0,
            "shearedEdge": False,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["boltCount"] == 6
    assert res["summary"]["plateHeightMm"] == pytest.approx(220.0, rel=0.01)
    assert res["summary"]["plateWidthMm"] == pytest.approx(160.0, rel=0.01)
    assert res["summary"]["patternOk"] is True


def test_objects_bolts_welds_slip_factor() -> None:
    # A325N, 20 mm, Class B (mu=0.50), 1 plane, T=0: mu*Du*hf*Tb*Ns with phi=1.0 or 0.85.
    res = features.run(
        "objectsBoltsWelds.slipFactor",
        None,
        {
            "grade": "A325N",
            "boltDiaMm": 20.0,
            "fayingSurface": "B",
            "slipPlanes": 1.0,
            "tensionKn": 0.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["surfaceClass"] == "B"
    assert res["summary"]["mu"] == pytest.approx(0.50, rel=0.01)
    assert res["summary"]["slipCapacityKn"] > 0.0


def test_objects_bolts_welds_weld_type() -> None:
    # Fillet leg=10 mm, L=200 mm, fexx=480 -> te = 7.0711 mm, phiRn = 0.75*0.6*480*7.0711*200/1000 = 305.47 kN.
    res = features.run(
        "objectsBoltsWelds.weldType",
        None,
        {"weldKind": "fillet", "legOrThroatMm": 10.0, "lengthMm": 200.0, "fexxMpa": 480.0},
    )
    assert res["problems"] == []
    te = 10.0 * math.sqrt(2.0) / 2.0
    assert res["summary"]["effectiveThroatMm"] == pytest.approx(te, rel=0.01)
    assert res["summary"]["designCapacityKn"] == pytest.approx(
        0.75 * 0.6 * 480.0 * te * 200.0 / 1000.0, rel=0.01
    )


def test_objects_bolts_welds_weld_size() -> None:
    # Thicker 16 mm gives BNBC Table 6.10.22 min leg = 6 mm; thinner 10 mm gives max leg = 10 - 2 = 8 mm -> sizeOk=True.
    res = features.run(
        "objectsBoltsWelds.weldSize",
        None,
        {"thinnerPartMm": 10.0, "thickerPartMm": 16.0, "proposedLegMm": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minLegMm"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["maxLegMm"] == pytest.approx(8.0, rel=0.01)
    assert res["summary"]["sizeOk"] is True


def test_objects_bolts_welds_effective_length() -> None:
    # L=240, w=10, endReturns=True -> Leff = 240 - 2*10 = 220 mm; L/w = 22 <= 100 -> beta = 1.0 -> Ldesign = 220 mm.
    res = features.run(
        "objectsBoltsWelds.effectiveLength",
        None,
        {"weldLengthMm": 240.0, "legSizeMm": 10.0, "endReturns": True},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveLengthMm"] == pytest.approx(220.0, rel=0.01)
    assert res["summary"]["longWeldBeta"] == pytest.approx(1.0, rel=0.01)
    assert res["summary"]["designLengthMm"] == pytest.approx(220.0, rel=0.01)
    assert res["summary"]["meetsMinLength"] is True


def test_objects_bolts_welds_weld_strength() -> None:
    # 10 mm fillet, Fexx=480, 90-deg (transverse) -> base = 0.75*0.6*480*7.0711/1000 = 1.52735 kN/mm; dir = 1.5 -> 2.2910 kN/mm.
    res = features.run(
        "objectsBoltsWelds.weldStrength",
        None,
        {"legSizeMm": 10.0, "fexxMpa": 480.0, "angleDeg": 90.0},
    )
    assert res["problems"] == []
    base = 0.75 * 0.6 * 480.0 * (10.0 * math.sqrt(2.0) / 2.0) / 1000.0
    assert res["summary"]["baseCapacityKnPerMm"] == pytest.approx(base, rel=0.01)
    assert res["summary"]["directionalFactor"] == pytest.approx(1.5, rel=0.01)
    assert res["summary"]["directionalCapacityKnPerMm"] == pytest.approx(1.5 * base, rel=0.01)


def test_objects_bolts_welds_bolt_check() -> None:
    # 4 x M20 A325N single shear -> 4 * 77.754 = 311.018 kN; Vu=150 (37.5 kN/bolt -> frv = 119.37 MPa), Tu=40 (10 kN/bolt).
    # F'nt = min(1.3*620 - 620/(0.75*330)*119.366, 620) = 521.02 MPa -> t_cap/bolt = 0.75*521.02*314.159/1000 = 122.76 kN.
    # Tearout: lc = 40 - 22/2 = 29 mm -> brg_per = 0.75*1.2*29*10*450/1000 = 117.45 kN -> group = 469.8 kN.
    # Max util = 37.5 / 77.7544 = 0.4823 -> checkOk = True.
    res = features.run(
        "objectsBoltsWelds.boltCheck",
        None,
        {
            "grade": "A325N",
            "boltDiaMm": 20.0,
            "boltCount": 4.0,
            "shearPlanes": 1.0,
            "plateThickMm": 10.0,
            "plateFuMpa": 450.0,
            "edgeDistMm": 40.0,
            "vuKn": 150.0,
            "tuKn": 40.0,
        },
    )
    assert res["problems"] == []
    ab = math.pi * 100.0
    cap_shear = 4.0 * 0.75 * 330.0 * ab / 1000.0
    frv = 37500.0 / ab
    fnt_mod = min(1.3 * 620.0 - 620.0 / (0.75 * 330.0) * frv, 620.0)
    t_cap_per = 0.75 * fnt_mod * ab / 1000.0
    t_row = _row_by(res, "check", "Combined tension (per bolt)")
    assert t_row["capacityKn"] == pytest.approx(t_cap_per, rel=0.01)
    assert res["summary"]["boltShearCapKn"] == pytest.approx(cap_shear, rel=0.01)
    assert res["summary"]["bearingCapKn"] == pytest.approx(469.8, rel=0.01)
    assert res["summary"]["governingUtilisation"] == pytest.approx(
        37.5 / (cap_shear / 4.0), rel=0.01
    )
    assert res["summary"]["checkOk"] is True


def test_objects_bolts_welds_weld_check() -> None:
    # leg=8, L=400, fexx=480, V=160 kN, M=0 -> resultant = 160/400 = 0.40 kN/mm, cap = 1.2219 kN/mm -> util = 0.3274.
    res = features.run(
        "objectsBoltsWelds.weldCheck",
        None,
        {
            "legSizeMm": 8.0,
            "weldLengthMm": 400.0,
            "fexxMpa": 480.0,
            "shearKn": 160.0,
            "momentKnm": 0.0,
        },
    )
    assert res["problems"] == []
    cap = 0.75 * 0.6 * 480.0 * (8.0 * math.sqrt(2.0) / 2.0) / 1000.0
    assert res["summary"]["resultantForceKnPerMm"] == pytest.approx(0.40, rel=0.01)
    assert res["summary"]["weldCapacityKnPerMm"] == pytest.approx(cap, rel=0.01)
    assert res["summary"]["utilisation"] == pytest.approx(0.40 / cap, rel=0.01)
    assert res["summary"]["checkOk"] is True


def test_objects_bolts_welds_combined_check() -> None:
    # Governing utilisation is max(boltUtilisation, weldUtilisation).
    res = features.run(
        "objectsBoltsWelds.combinedCheck",
        None,
        {
            "grade": "A325N",
            "boltDiaMm": 20.0,
            "boltCount": 4.0,
            "weldLegMm": 8.0,
            "weldLengthMm": 400.0,
            "eccentricityMm": 50.0,
            "vuKn": 160.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["governingUtilisation"] == pytest.approx(
        max(res["summary"]["boltUtilisation"], res["summary"]["weldUtilisation"]), rel=0.01
    )
    assert res["summary"]["jointOk"] == (res["summary"]["governingUtilisation"] <= 1.0)


def test_objects_bolts_welds_joint_report() -> None:
    # Light demand Vu=150 kN on 3xM20 A325N 10mm fin plate with 8mm weld -> passes cleanly.
    res = features.run(
        "objectsBoltsWelds.jointReport",
        None,
        {
            "jointName": "FIN-TEST",
            "grade": "A325N",
            "boltDiaMm": 20.0,
            "rows": 3.0,
            "pitchMm": 70.0,
            "plateThickMm": 10.0,
            "weldLegMm": 8.0,
            "vuKn": 150.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["jointName"] == "FIN-TEST"
    assert 0.0 < res["summary"]["governingUtilisation"] < 1.0
    assert res["summary"]["jointOk"] is True


def test_objects_bolts_welds_anchor_type() -> None:
    # 20 mm headed bolt, hef=250, fc=28, fu=450 -> positive tension, breakout, shear capacities.
    res = features.run(
        "objectsBoltsWelds.anchorType",
        None,
        {
            "anchorKind": "headedBolt",
            "diaMm": 20.0,
            "embedMm": 250.0,
            "fcMpa": 28.0,
            "fuMpa": 450.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["steelTensionKn"] > 0.0
    assert res["summary"]["breakoutTensionKn"] > 0.0
    assert res["summary"]["steelShearKn"] > 0.0


def test_objects_bolts_welds_embedment_depth() -> None:
    # hef=200, edgeDist=350 (>300), memberThick=400 -> coneRadius=300, effHef=200, pedestalClearBelow=200.
    res = features.run(
        "objectsBoltsWelds.embedmentDepth",
        None,
        {"diaMm": 20.0, "hefMm": 200.0, "edgeDistMm": 350.0, "memberThickMm": 400.0, "fcMpa": 28.0},
    )
    assert res["problems"] == []
    assert res["summary"]["projectedConeRadiusMm"] == pytest.approx(300.0, rel=0.01)
    assert res["summary"]["effectiveHefMm"] == pytest.approx(200.0, rel=0.01)
    assert res["summary"]["pedestalClearBelowMm"] == pytest.approx(200.0, rel=0.01)


def test_objects_bolts_welds_base_plate_hole() -> None:
    # 24 mm anchor, oversized hole (24 + 6 or 24 + 8 -> > 24 mm), washer larger than hole.
    res = features.run(
        "objectsBoltsWelds.basePlateHole",
        None,
        {"anchorDiaMm": 24.0, "plateThickMm": 25.0, "holeType": "oversized"},
    )
    assert res["problems"] == []
    assert res["summary"]["holeDiaMm"] > 24.0
    assert res["summary"]["washerSizeMm"] > res["summary"]["holeDiaMm"]
    assert res["summary"]["washerThickMm"] > 0.0


def test_objects_bolts_welds_edge_preparation() -> None:
    # Single-V butt weld: t=20, angle=60 (half-angle 30), gap=3, rootFace=2, L=300:
    # bevel depth h = 20 - 2 = 18 mm -> area = gap*t + h^2 * tan(30) = 3*20 + 324 * 0.57735 = 247.06 mm2.
    # vol = 247.06 * 300 / 1000 = 74.118 cm3; mass = 74.118 * 7.85 / 1000 = 0.5818 kg.
    res = features.run(
        "objectsBoltsWelds.edgePreparation",
        None,
        {
            "prepType": "singleV",
            "plateThickMm": 20.0,
            "bevelAngleDeg": 60.0,
            "rootGapMm": 3.0,
            "rootFaceMm": 2.0,
            "weldLengthMm": 300.0,
        },
    )
    assert res["problems"] == []
    area = 3.0 * 20.0 + (18.0**2) * math.tan(math.radians(30.0))
    vol_cm3 = area * 300.0 / 1000.0
    assert res["summary"]["grooveAreaMm2"] == pytest.approx(area, rel=0.02)
    assert res["summary"]["weldVolumeCm3"] == pytest.approx(vol_cm3, rel=0.02)
    assert res["summary"]["weldMetalMassKg"] == pytest.approx(vol_cm3 * 7.85 / 1000.0, rel=0.02)


def test_objects_bolts_welds_ndt_method() -> None:
    # Moment joint (100% UT), 10 m -> utLengthM = 10.0 m.
    res = features.run(
        "objectsBoltsWelds.ndtMethod",
        None,
        {"jointCriticality": "moment", "plateThickMm": 20.0, "weldLengthM": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["totalWeldLengthM"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["utLengthM"] == pytest.approx(10.0, rel=0.01)


def test_objects_bolts_welds_backing_bar() -> None:
    # Steel backing bar for 6 mm gap, 300 mm long -> positive dimensions and steelMassKg > 0.
    res = features.run(
        "objectsBoltsWelds.backingBar",
        None,
        {"rootGapMm": 6.0, "plateThickMm": 20.0, "material": "steel", "jointLengthMm": 300.0},
    )
    assert res["problems"] == []
    assert res["summary"]["backingWidthMm"] > 6.0
    assert res["summary"]["backingThickMm"] >= 6.0
    assert res["summary"]["steelMassKg"] > 0.0


def test_objects_bolts_welds_pattern_generator() -> None:
    # 2x2 rectangular @ 100x100 -> coordinates (+/-50, +/-50):
    # Ip = sum(x^2 + y^2) = 4 * (2500 + 2500) = 20000 mm2; maxRadius = sqrt(5000) = 70.7107 mm.
    res = features.run(
        "objectsBoltsWelds.patternGenerator",
        None,
        {
            "patternType": "rectangular",
            "nx": 2.0,
            "ny": 2.0,
            "spacingXMm": 100.0,
            "spacingYMm": 100.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["boltCount"] == 4
    assert res["summary"]["polarInertiaIpMm2"] == pytest.approx(20000.0, rel=0.01)
    assert res["summary"]["maxRadiusMm"] == pytest.approx(math.sqrt(5000.0), rel=0.01)


def test_objects_bolts_welds_edge_distance() -> None:
    # 20 mm bolt, 10 mm plate, provided=40 mm, sheared=True -> minEdge=34 mm, maxEdge=min(12*10=120, 150)=120 mm -> edgeOk=True.
    res = features.run(
        "objectsBoltsWelds.edgeDistance",
        None,
        {"boltDiaMm": 20.0, "plateThickMm": 10.0, "providedEdgeMm": 40.0, "shearedEdge": True},
    )
    assert res["problems"] == []
    assert res["summary"]["minEdgeMm"] == pytest.approx(34.0, rel=0.01)
    assert res["summary"]["maxEdgeMm"] == pytest.approx(120.0, rel=0.01)
    assert res["summary"]["edgeOk"] is True


def test_objects_bolts_welds_washer_type() -> None:
    # 20 mm bolt, standard hole, flat flange -> hardened flat washer outer > 22 mm.
    res = features.run(
        "objectsBoltsWelds.washerType",
        None,
        {"boltDiaMm": 20.0, "holeKind": "standard", "flangeSlope": "flat"},
    )
    assert res["problems"] == []
    assert res["summary"]["washerOuterMm"] > 30.0
    assert res["summary"]["washerThickMm"] > 0.0


def test_objects_bolts_welds_staggered_pattern() -> None:
    # W=200, t=10, d=20 -> hole+2 = 24 mm (or 22 mm); s=40, g=60 -> s^2/(4g) = 1600/240 = 6.6667 mm.
    # straightNet = 200 - 24 = 176 mm; staggeredNet = 200 - 2*24 + 6.6667 = 158.667 mm -> governs!
    res = features.run(
        "objectsBoltsWelds.staggeredPattern",
        None,
        {
            "plateWidthMm": 200.0,
            "plateThickMm": 10.0,
            "boltDiaMm": 20.0,
            "staggerPitchMm": 40.0,
            "gaugeMm": 60.0,
        },
    )
    assert res["problems"] == []
    h_eff = res["summary"]["netHoleWidthMm"]
    s_net = 200.0 - h_eff
    stag_net = 200.0 - 2.0 * h_eff + 40.0**2 / (4.0 * 60.0)
    gov_w = min(s_net, stag_net)
    assert res["summary"]["straightNetWidthMm"] == pytest.approx(s_net, rel=0.01)
    assert res["summary"]["staggeredNetWidthMm"] == pytest.approx(stag_net, rel=0.01)
    assert res["summary"]["governingNetAreaMm2"] == pytest.approx(gov_w * 10.0, rel=0.01)
    assert res["summary"]["netToGrossRatio"] == pytest.approx(gov_w / 200.0, rel=0.01)
