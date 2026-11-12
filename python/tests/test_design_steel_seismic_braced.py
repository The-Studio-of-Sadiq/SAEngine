"""B38: steel seismic provisions, part B: braced frames, plate walls and composite seismic
members (the code pack's ``steelSeismic`` table, BNBC 2020 Part 6 Sec 10.20.13-10.20.17,
Appendix P, Sec 13.5)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from saengine.codes.tables import builtin_table
from saengine.design.steel import seismic_braced as sb
from saengine.design.steel import seismic_composite as scm
from saengine.design.steel import seismic_walls as sw

T = builtin_table("steelSeismic")


def _settings(system="steelScbf", r=None):
    return SimpleNamespace(
        seismic=SimpleNamespace(
            system=system, r=r, systemY=None, otherSystems=[], otherSystemsY=[]
        ),
        analysis=SimpleNamespace(responseSpectrum=True, endOffsets=False, rigidZoneFactor=0.0),
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ the pack's values (with clauses) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_pack_values():
    c = T.concentric["scbf"]
    # Sec 10.20.13.2.1: KL/r â‰¤ 4 âˆš(E/Fy), up to 200 with the column exception.
    assert (c.slenderness, c.slendernessMax) == (4.0, 200)
    # Sec 10.20.13.2.3: 30 % to 70 % in tension, lines within 10 % of the building.
    assert (c.tensionShareMin, c.tensionShareMax, c.lineOffset) == (0.3, 0.7, 0.1)
    # Sec 10.20.13.2.5: stitches 0.4 (0.75 without shear) of KL/r, at least two.
    assert (c.stitchRatio, c.stitchRatioNoShear, c.stitchesMin) == (0.4, 0.75, 2)
    # Sec 10.20.13.3.2-3: 1.1 Ry Mp and 1.1 Ry Pn; Sec 10.20.13.4.1: 0.3 Pn; 10.20.13.4.2: no K.
    assert (c.connectionFlexure, c.connectionCompression, c.postBuckling) == (1.1, 1.1, 0.3)
    assert c.kBracing is False and T.concentric["ocbf"].kBracing is True
    # Sec 10.20.13.5, 10.20.13.6: splices 50 %, protected middle quarter.
    assert (c.spliceFlexureShare, c.protectedMiddle) == (0.5, 0.25)
    # Sec 10.20.14.2: OCBF KL/r â‰¤ 4 âˆš(E/Fy) only in K, V, inverted-V.
    o = T.concentric["ocbf"]
    assert o.slenderness == 4.0 and o.slendernessChevronOnly and o.filledHssExempt
    e = T.eccentric
    # Sec 10.20.15.2.2: Ï†v 0.90, Vp = 0.6 Fy Aw, 2 Mp / e, 0.15 Py, Eqs 6.10.303-6.10.306.
    assert (e.phi, e.shearYield, e.flexureShear, e.axialLimit, e.mpaFactor) == (
        0.9, 0.6, 2.0, 0.15, 1.18,
    )  # fmt: skip
    assert (e.lengthRatio, e.lengthA, e.lengthB, e.shortLink) == (0.3, 1.15, 0.5, 1.6)
    # Sec 10.20.15.2.3: 0.08 rad to 1.6 Mp/Vp, 0.02 rad from 2.6 Mp/Vp.
    assert (e.rotationShort, e.rotationLong, e.longLink) == (0.08, 0.02, 2.6)
    # Sec 10.20.15.3: stiffeners.
    assert (e.endStiffenerThickness, e.stiffenerThicknessMin, e.twoSidedDepth) == (0.75, 10, 635)
    assert (e.spacingShort, e.spacingLong, e.spacingDepthDivisor, e.flexuralLink) == (
        30, 52, 5, 5.0,
    )  # fmt: skip
    # Sec 10.20.15.5-10.20.15.8: 0.06, 1.25, 1.1, 1.1.
    assert (e.braceStrength, e.braceFactor, e.beamFactor, e.columnFactor) == (
        0.06, 1.25, 1.1, 1.1,
    )  # fmt: skip
    b = T.restrained
    # Sec 10.20.16: Ï† 0.90, 1.1 Ã— adjusted compression, Î² â‰¥ 1, 2 Ã— drift, 50 mm plates.
    assert (b.phi, b.connectionFactor, b.betaMin, b.testDrift, b.coreToughness) == (
        0.9, 1.1, 1.0, 2.0, 50,
    )  # fmt: skip
    w = T.plateWalls
    # Sec 10.20.17, Eqs 6.10.307-6.10.308.
    assert (w.phi, w.shearCoefficient, w.angleCoefficient) == (0.9, 0.42, 360)
    assert (w.aspectMin, w.aspectMax, w.inertiaCoefficient, w.hbeBracing) == (
        0.8, 2.5, 0.00307, 0.086,
    )  # fmt: skip
    cs = T.compositeSeismic
    # Sec 13.5.4.2: 17 MPa least, 69 / 28 MPa for the strength; Sec 13.5.5.3: 4 % steel.
    assert (cs.concreteMin, cs.concreteMaxNormal, cs.concreteMaxLight) == (17, 69, 28)
    assert (cs.steelShareMin, cs.shearPhi, cs.connectorSpacingMax) == (0.04, 0.75, 406)
    assert cs.special.ashCoefficient == 0.09 and cs.beamStrain == 1700
    assert (cs.plateWall.shearCoefficient, cs.plateWall.ratioMin) == (0.6, 0.0025)
    assert (cs.plateWall.concreteBothSides, cs.plateWall.concreteOneSide) == (100, 200)
    assert T.sources["linkShear"].startswith("Sec 10.20.15.2.2")
    assert T.sources["compositeWall"].startswith("Sec 13.5.6")


def test_appendix_p_systems():
    s = builtin_table("seismic")
    # Appendix P Table 6.P.1 (part 2 p. 590).
    rows = {
        "steelBrbf": (7.0, 2.0, 5.5, 48.0),
        "steelSpsw": (7.0, 2.0, 6.0, 48.0),
        "steelBrbfMoment": (8.0, 2.5, 5.0, 48.0),
        "steelDualSmfBrbf": (8.0, 2.5, 5.0, None),
        "steelDualSmfSpsw": (8.0, 2.5, 6.5, None),
    }
    for key, (r, omega, cd, d) in rows.items():
        row = s.systems[key]
        assert (row.R, row.Omega0, row.Cd, row.heightLimits["D"]) == (r, omega, cd, d)
        assert row.row.startswith("P.3") and not row.concrete
    # Table 6.P.2: Cr 0.03 (ft) = 0.0731 (m), x 0.75.
    pc = s.periodCoefficients["bucklingRestrainedBracedFrame"]
    assert (pc.Ct, pc.m) == (0.0731, 0.75)
    assert 0.03 * 3.2808**0.75 == pytest.approx(0.0731, abs=1e-4)
    assert T.bracedSystems["steelBrbf"] == "brbf" and T.bracedSystems["steelSpsw"] == "spsw"
    # Sec 10.20.15.7: EBF with moment connections away from the links: OMF connections.
    assert T.systems["steelEbfMoment"] == "omf"


def test_braced_provisions():
    found = sb.braced_provisions(_settings("steelScbf"), T)
    assert found.applies and found.kinds == ["scbf"] and found.r == 6.0
    assert sb.braced_provisions(_settings("steelOcbf"), T).kinds == ["ocbf"]  # R 3.25 > 3
    assert not sb.braced_provisions(_settings("steelOcbf", r=3.0), T).applies
    assert not sb.braced_provisions(_settings("steelSmf"), T).applies
    assert sb.braced_provisions(_settings("steelDualSmfEbf"), T).kinds == ["ebf"]


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ concentric braces â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_brace_slenderness():
    limit = 4 * math.sqrt(200_000 / 345)  # 96.3
    rows, slender = sb.brace_slenderness_checks(90, 345, 200_000, "scbf", False, T)
    assert rows[0]["capacity"] == pytest.approx(limit, abs=1e-3) and not slender
    rows, slender = sb.brace_slenderness_checks(150, 345, 200_000, "scbf", False, T)
    assert slender and rows[0]["capacity"] == 200 and rows[0]["ok"]
    assert sb.brace_slenderness_checks(150, 345, 200_000, "ocbf", False, T) == ([], False)
    rows, _ = sb.brace_slenderness_checks(150, 345, 200_000, "ocbf", True, T)
    assert not rows[0]["ok"]  # OCBF V brace: no exception


def test_concentric_forces_and_chevron():
    f = sb.concentric_forces(1.4, 345, 5000, 1_000_000, 50e6, "scbf", T)
    assert f.tension == pytest.approx(1.4 * 345 * 5000)  # Ry Fy Ag
    assert f.connection_compression == pytest.approx(1.1 * 1.4 * 1e6)  # 1.1 Ry Pn
    assert f.connection_moment == pytest.approx(1.1 * 1.4 * 50e6)  # 1.1 Ry Mp
    assert f.beam_compression == pytest.approx(0.3e6)  # 0.3 Pn
    ang = math.atan2(3200, 3000)
    q, mq = sb.chevron_demand([(f.tension, ang)], [(f.beam_compression, ang)], 3000, 3000)
    assert q == pytest.approx((f.tension - 0.3e6) * math.sin(ang))
    assert mq == pytest.approx(q * 6000 / 4)


def test_tension_share_and_stitches():
    ok, bad = sb.BraceLine("a", 1.0, 1.0, ["A", "B"]), sb.BraceLine("b", 0.8, 0.2, ["C", "D"])
    rows = sb.tension_share_checks([ok, bad], T)
    assert rows[0]["ok"] and not rows[1]["ok"]
    row = sb.stitch_check(600, 20, 100, True, "scbf", T)[0]
    assert (row["demand"], row["capacity"]) == (30, 40)  # l/r â‰¤ 0.4 KL/r


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ EBF links â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _link(**kw):
    base = {
        "id": "L",
        "e": 800,
        "d": 400,
        "tf": 16,
        "tw": 10,
        "bf": 200,
        "area": 10_000,
        "z": 1.5e6,
        "fy": 345,
        "ry": 1.1,
        "span": 6000,
        "height": 3600,
        "angle": math.atan2(3600, 2600),
    }
    base.update(kw)
    return sb.Link(**base)


def test_link_shear_and_rotation():
    st = sb.link_strength(_link(), T)
    vp = 0.6 * 345 * (400 - 32) * 10
    assert st["Vp"] == pytest.approx(vp) and st["Vn"] == pytest.approx(vp)
    assert st["ratio"] == pytest.approx(800 / (345 * 1.5e6 / vp))
    assert sb.rotation_limit(1.0, T) == 0.08 and sb.rotation_limit(3.0, T) == 0.02
    assert sb.rotation_limit(2.1, T) == pytest.approx(0.05)
    assert sb.link_rotation(_link(), 0.02) == pytest.approx(6000 / 800 * 0.02)
    rows, summary = sb.link_checks(_link(vu=500e3), 0.02, T)
    shear = next(r for r in rows if r["name"] == "Seismic: link shear")
    assert shear["capacity"] == pytest.approx(0.9 * vp / 1e3, abs=1e-3)
    rotation = next(r for r in rows if r["name"] == "Seismic: link rotation angle")
    assert not rotation["ok"] and summary["rotationLimit"] == 0.08


def test_link_axial_eqs_303_306():
    link = _link(pu=0.3 * 345 * 10_000, vu=500e3)
    st = sb.link_strength(link, T)
    vp, mp = st["Vp"], 345 * 1.5e6
    assert st["Vpa"] == pytest.approx(vp * math.sqrt(1 - 0.3**2))  # Eq 6.10.303
    assert st["Mpa"] == pytest.approx(1.18 * mp * 0.7)  # Eq 6.10.304
    assert st["Vn"] == pytest.approx(min(st["Vpa"], 2 * st["Mpa"] / 800))
    rho = link.pu / link.vu
    aw_ag = (400 - 32) * 10 / 10_000
    assert st["lengthMax"] == pytest.approx((1.15 - 0.5 * rho * aw_ag) * 1.6 * mp / vp)  # 6.10.305


def test_ebf_demands():
    link = _link()
    d = sb.ebf_demands(link, 700e3, T)
    assert d["brace"] == pytest.approx(1.25 * 1.1 * 700e3 / math.sin(link.angle))
    assert d["beamMoment"] == pytest.approx(1.1 * 1.1 * 700e3 * 800 / 2)
    assert d["column"] == pytest.approx(1.1 * 1.1 * 700e3)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ buckling-restrained braces â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_restrained_strengths():
    brb = SimpleNamespace(coreArea=3000, beta=1.1, omega=1.3, couponFy=False)
    f = sb.restrained_strengths(brb, 250, 1.3, T)
    assert f.tension == pytest.approx(1.3 * 1.3 * 750e3)  # Ï‰ Ry Pysc
    assert f.compression == pytest.approx(1.1 * 1.3 * 1.3 * 750e3)  # Î² Ï‰ Ry Pysc
    assert f.connection_tension == pytest.approx(1.1 * f.compression)
    coupon = sb.restrained_strengths(
        SimpleNamespace(**{**vars(brb), "couponFy": True}), 250, 1.3, T
    )
    assert coupon.tension == pytest.approx(1.3 * 750e3)
    rows = sb.restrained_checks(SimpleNamespace(**{**vars(brb), "beta": 0.9}), 250, 600e3, T)
    assert rows[0]["capacity"] == pytest.approx(0.9 * 750)
    assert not rows[1]["ok"]  # Î² < 1


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ plate shear walls â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def test_web_angle_and_shear():
    alpha = sw.web_angle(5, 6000, 3600, 1e4, 2e4, 4e8, T)
    num = 1 + 5 * 6000 / (2 * 2e4)
    den = 1 + 5 * 3600 * (1 / 1e4 + 3600**3 / (360 * 4e8 * 6000))
    assert math.tan(alpha) ** 4 == pytest.approx(num / den)  # Eq 6.10.308
    assert sw.web_shear(345, 5, 5600, alpha, T) == pytest.approx(
        0.42 * 345 * 5 * 5600 * math.sin(2 * alpha)
    )  # Eq 6.10.307
    assert sw.vbe_inertia_required(5, 3600, 6000, T) == pytest.approx(0.00307 * 5 * 3600**4 / 6000)


def test_plate_wall_element():
    from saengine.library.bim import BeamElement, ColumnElement, WallElement
    from saengine.verification.cases.common import MATERIALS, objects

    w = {
        "shape": "I",
        "overallWidth": 300,
        "overallDepth": 300,
        "webThickness": 10,
        "flangeThickness": 15,
    }
    types = objects(
        {"id": "COL", "name": "VBE", "kind": "column", "material": "A992", "profile": w},
        {"id": "BM", "name": "HBE", "kind": "beam", "material": "A992", "profile": w},
        {"id": "PW", "name": "Plate", "kind": "wall", "material": "A992", "thickness": 5},
    )
    by_type = {t.id: t for t in types.objects}
    building = SimpleNamespace(
        elements=[
            ColumnElement(id="C1", type="COL", position=(0, 0), bottom=0, top=3600),
            ColumnElement(id="C2", type="COL", position=(6000, 0), bottom=0, top=3600),
            BeamElement(id="B1", type="BM", start=(0, 0), end=(6000, 0), elevation=3600),
            WallElement(id="W1", type="PW", start=(0, 0), end=(6000, 0), bottom=0, top=3600),
        ],
        additions=None,
    )
    mats = {m.id: m for m in MATERIALS.materials}
    wall = building.elements[3]
    sections = {"W1": [{"cuts": {"bottom": {"1.2D+1.0EX": {"V2": 800.0}}}}]}
    found, _notes = sw.design_plate_walls(
        [(wall, by_type["PW"], mats["A992"])], sections, building, by_type, mats,
        _settings("steelSpsw"),
    )  # fmt: skip
    e = found[0]
    assert e["wallType"] == "steelPlate" and e["plateWall"]["special"]
    assert e["plateWall"]["vbe"] == ["C1", "C2"] and e["plateWall"]["hbe"]["top"] == "B1"
    shear = next(c for c in e["checks"] if c["name"] == "Seismic: plate wall web shear")
    assert shear["demand"] == 800.0
    names = {c["name"] for c in e["checks"]}
    assert "Seismic: panel aspect ratio L/h" in names
    assert "Seismic: VBE C1 stiffness" in names


def test_composite_wall():
    pw = SimpleNamespace(
        concrete="bothSides", concreteThickness=100, barRatio=0.0025, barSpacing=300,
        connectors=True,
    )  # fmt: skip
    rows, phi_vn = sw.composite_wall_checks(pw, 10, 5000, 345, 1e6, 0.0, 30, T)
    assert phi_vn == pytest.approx(0.9 * 0.6 * 10 * 5000 * 345)  # Eq 6.13.28
    one = SimpleNamespace(**{**vars(pw), "concrete": "oneSide"})
    rows, phi_vn = sw.composite_wall_checks(one, 10, 5000, 345, 1e6, 2e6, 30, T)
    assert phi_vn == pytest.approx(0.9 * 2e6)  # 100 < 200 mm on one side: not stiffened
    assert not next(r for r in rows if "thickness" in r["name"])["ok"]


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ composite seismic â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _encased(**kw):
    base = {
        "width": 500,
        "depth": 500,
        "bars": 8,
        "barDiameter": 20,
        "barFy": 415,
        "cover": 40,
        "tieDiameter": 10,
        "tieSpacing": 100,
        "loadApplied": "steel",
        "studSpacing": 300,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_composite_levels_and_ties():
    assert scm.level_of(["omf", "scbf"], T) == "special"
    assert scm.level_of(["imf"], T) == "intermediate"
    col = _encased()
    assert scm.tie_spacing_limit(col, "ordinary", False, T) == 250  # min(250, 320, 480)
    assert scm.tie_spacing_limit(col, "intermediate", False, T) == 160  # 8 db
    assert scm.tie_spacing_limit(col, "special", False, T) == 120  # 6 db
    assert scm.tie_spacing_limit(col, "special", True, T) == 102  # C-SMF confined
    # Eq 6.13.27.
    ash = scm.ash_required(400, 100, 345, 10_000, 10e6, 30, 415, T)
    assert ash == pytest.approx(0.09 * 400 * 100 * (1 - 345 * 10_000 / 10e6) * 30 / 415)


def test_composite_concrete_limits():
    rows = scm.concrete_checks(80, False, T)
    assert rows[0]["ok"] and not rows[1]["ok"]  # 80 > 69 MPa
    assert not scm.concrete_checks(30, True, T)[1]["ok"]  # lightweight > 28 MPa
    assert not scm.concrete_checks(15, False, T)[0]["ok"]  # < 17 MPa


def test_filled_wall_thickness():
    dims = {"B": 200, "H": 200, "b": 180, "h": 180, "t": 6}
    shape = SimpleNamespace(family="rhs", area=200 * 200 - 188 * 188, dims=dims)
    steel = SimpleNamespace(fy=345, e=200_000)
    rows = scm.filled_column_checks(SimpleNamespace(), shape, steel, True, T)
    wall = next(r for r in rows if r["name"].startswith("Seismic: filled HSS wall thickness"))
    assert wall["demand"] == pytest.approx(180 * math.sqrt(345 / (2 * 200_000)), abs=1e-3)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ integration: braced bays â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _run_bay(tmp_path, system, beams, braces):
    from saengine.design import steel_design
    from saengine.design.check import _demands
    from saengine.design.steel import seismic as ss
    from saengine.library.settings import LoadCombination
    from saengine.verification.cases.common import (
        MATERIALS,
        derive,
        node_at,
        objects,
        point,
        run_model,
        settings,
        structure,
    )
    from saengine.verification.cases.common import building as building_of

    w = {
        "shape": "I",
        "overallWidth": 254,
        "overallDepth": 254,
        "webThickness": 8.6,
        "flangeThickness": 14.2,
    }
    types = objects(
        {"id": "COL", "name": "W col", "kind": "column", "material": "A992", "profile": w},
        {"id": "BM", "name": "W beam", "kind": "beam", "material": "A992", "profile": w},
        {"id": "BR", "name": "W brace", "kind": "brace", "material": "A992", "profile": w},
    )
    members = [
        {"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3200)},
        {"id": "C2", "type": "COL", "start": point(6000, 0, 0), "end": point(6000, 0, 3200)},
    ]
    members += [
        {"id": i, "type": "BM", "start": point(a, 0, 3200), "end": point(b, 0, 3200)}
        for i, a, b in beams
    ]
    members += [{"id": i, "type": "BR", "start": point(*p), "end": point(*q)} for i, p, q in braces]
    model = structure(
        members=members,
        supports=[{"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}],
    )
    building = building_of(model)
    s = settings(system=system)
    project = derive(building, types, MATERIALS, s).project
    top = node_at(project, (0, 0, 3.2))
    wx = next(p for p in project["load_patterns"] if p["name"] == "WX")
    wx["nodal_loads"] = [{"node_id": top, "forces": [100e3, 0, 0, 0, 0, 0]}]
    static = [a["id"] for a in project["analyses"] if a["type"] == "Static"]
    _, out, _ = run_model(project, tmp_path, static)
    s = s.model_copy(
        update={
            "combinations": [
                LoadCombination(name="1.2D", D=1.2),
                LoadCombination(name="1.2D+1.0WX", D=1.2, WX=1.0),
            ]
        }
    )
    combinations, pieces, _, _ = _demands(project, out, s)
    by_type = {t.id: t for t in types.objects}
    mats = {m.id: m for m in MATERIALS.materials}
    found_members = []
    for element in building.elements:
        t = by_type[element.type]
        entry, _ = steel_design.design_member(
            element.id, t.kind, t, mats[t.material], mats, pieces[element.id], combinations,
            False, project,
        )  # fmt: skip
        found_members.append(
            ss.SteelMember(
                element.id, t.kind, element, t, mats[t.material], pieces[element.id], False, entry
            )
        )
    found = sb.apply(project, building, by_type, mats, found_members, combinations, [], s)
    return found, {m.id: m.entry for m in found_members}


def test_inverted_v_scbf_bay(tmp_path):
    found, entries = _run_bay(
        tmp_path,
        "steelScbf",
        [("B1", 0, 3000), ("B2", 3000, 6000)],
        [("D1", (0, 0, 0), (3000, 0, 3200)), ("D2", (6000, 0, 0), (3000, 0, 3200))],
    )
    assert found["applies"] and found["kinds"] == ["scbf"]
    assert found["chevrons"] and set(found["chevrons"][0]["braces"]) == {"D1", "D2"}
    beam = entries[found["chevrons"][0]["beam"]]
    name = "Seismic: V-braced beam with the unbalanced brace force"
    assert any(c["name"] == name for c in beam["checks"])
    assert any("slenderness" in c["name"] for c in entries["D1"]["checks"])
    assert found["braces"]["D1"]["kind"] == "scbf"
    # One line of bracing, braces in opposite directions: 50 % in tension.
    line = found["checks"][0]
    assert line["name"].startswith("Seismic: lateral force distribution") and line["ok"]


def test_split_k_ebf_bay(tmp_path):
    found, entries = _run_bay(
        tmp_path,
        "steelEbf",
        [("B1", 0, 2500), ("LK", 2500, 3500), ("B3", 3500, 6000)],
        [("D1", (0, 0, 0), (2500, 0, 3200)), ("D2", (6000, 0, 0), (3500, 0, 3200))],
    )
    assert found["applies"] and found["kinds"] == ["ebf"]
    link = found["links"][0]
    assert link["id"] == "LK" and link["e"] == 1000 and not link["atColumn"]
    names = {c["name"] for c in entries["LK"]["checks"]}
    assert {"Seismic: link shear", "Seismic: link rotation angle"} <= names
    assert found["braces"]["D1"]["kind"] == "ebf"
    brace = "Seismic: diagonal brace at the link's strength"
    assert any(c["name"] == brace for c in entries["D1"]["checks"])
    assert any(c["name"].startswith("Seismic: column at the") for c in entries["C1"]["checks"])
