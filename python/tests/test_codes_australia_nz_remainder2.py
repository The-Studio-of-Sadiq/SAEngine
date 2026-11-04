"""The second remainder of the Australian and New Zealand packs (alpha 9 track C18c): AS 3600
slender columns (10.4), anchorage and laps (13.1, 13.2), strut-and-tie with φst and βs
(Chapters 7, 12), the walls' least steel (11.7) and the Clause 14 / Appendix C detailing; NZS
3101 ductile detailing with Appendix D capacity design, ductile walls, coupling beams and joints
(Chapter 15); NZS 3404 Section 12 member categories; AS 4100 Chapter 9 connections; Design
Reinforcement's torsion links. The default pack and the other packs keep none of these methods.

The values are those of the packs' ``VERIFY.md`` (entries C18c-*).
"""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

AU, NZ = "australia-as", "newzealand-nzs"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def au():
    loaded = registry.load(AU)
    with code_context.using(loaded):
        yield loaded


@pytest.fixture
def nz():
    loaded = registry.load(NZ)
    with code_context.using(loaded):
        yield loaded


def _column(fc=40.0, fy=500.0, b=400.0, h=400.0, dia=20.0, cover=40.0):
    from saengine.design.rc import Bar, RcSection, bar_area
    from saengine.library.objects import RectangleProfile

    y = h / 2 - cover - dia / 2
    x = b / 2 - cover - dia / 2
    bars = [Bar(sx * x, sy * y, bar_area(dia), dia) for sx in (-1, 1) for sy in (-1, 1)]
    return RcSection(RectangleProfile(xDim=b, yDim=h), tuple(bars), fc, fy)


# ───────────────────────────── packs and methods by id ─────────────────────────────


def test_the_packs_load_without_problems():
    for pack_id in (AU, NZ):
        loaded = registry.load(pack_id)
        errors = [p for p in getattr(loaded, "problems", []) if p.severity == "error"]
        assert errors == []


def test_default_pack_has_none_of_the_methods():
    from saengine.design import (
        buckling_magnifier,
        development_factors,
        ductile_detailing,
        stress_fields,
    )
    from saengine.design.steel import capacity_factor_joints

    with code_context.using(registry.load("bnbc2020")):
        assert buckling_magnifier.rules() is None
        assert development_factors.rules() is None
        assert stress_fields.rules() is None
        assert ductile_detailing.rules() is None
        assert not capacity_factor_joints.active()


def test_is_and_eurocode_packs_keep_their_methods():
    from saengine.design import ductile_detailing, stress_fields

    with code_context.using(registry.load("is-codes")):
        r = ductile_detailing.rules()
        assert r is not None and r.basis == "designStrength" and r.levels == {}
        assert ductile_detailing.rules_for("special") is r
    with code_context.using(registry.load("eurocodes")):
        s = stress_fields.rules()
        assert s is not None and s.basis == "designStrength" and s.bottleStrut is None


def test_au_methods_by_id(au):
    from saengine.design import (
        buckling_magnifier,
        development_factors,
        ductile_detailing,
        stress_fields,
    )
    from saengine.design.steel import capacity_factor_joints

    assert buckling_magnifier.rules().method == "bucklingMagnifier"
    assert development_factors.rules().method == "developmentFactors"
    assert stress_fields.rules().basis == "capacityFactor"
    r = ductile_detailing.rules()
    assert r.basis == "capacityFactor" and r.frames == ["intermediate", "special"]
    assert capacity_factor_joints.active()


def test_nz_methods_by_id(nz):
    from saengine.design import buckling_magnifier, development_factors, ductile_detailing

    # NZS 3101's concreteMethods replace the Australian pack's: the AS 3600 slenderness and
    # anchorage are not inherited; the ductile detailing is NZ's own.
    assert buckling_magnifier.rules() is None
    assert development_factors.rules() is None
    r = ductile_detailing.rules()
    assert r.columns.ashForm == "axialLoad" and r.joints.stressLimit == (0.2, 10.0)


# ───────────────────────────── AS 3600 10.4 slender columns ─────────────────────────────


def test_km_and_least_moment(au):
    from saengine.design import buckling_magnifier as bm

    r = bm.rules()
    assert bm.km_factor(-1.0, False, r) == pytest.approx(0.4)  # double curvature: km >= 0.4
    assert bm.km_factor(1.0, False, r) == pytest.approx(1.0)
    assert bm.km_factor(0.0, True, r) == 1.0
    short = bm.magnify(1e6, 1e6, 1e6, False, False, 3000.0, 120.0, 400.0, None, 0.5)
    assert not short["slender"]  # Le/r = 25: short braced
    assert short["med"] == pytest.approx(max(1e6, 1e6 * 0.05 * 400.0))


def test_balanced_point_and_nc(au):
    from saengine.design import buckling_magnifier as bm

    section = _column()
    mub, do = bm.balanced(section, "x", 400.0)
    assert do == pytest.approx(400 / 2 + 400 / 2 - 40 - 10)
    assert mub > 0
    nc = bm.buckling_load(mub, do, 6000.0, 0.5, bm.rules())
    assert nc == pytest.approx(math.pi**2 / 6000.0**2 * 182 * do * 0.6 * mub / 1.5)


def test_slender_braced_and_unbraced(au):
    from saengine.design import buckling_magnifier as bm

    point = bm.balanced(_column(), "x", 400.0)
    braced = bm.magnify(1.5e6, 40e6, 40e6, False, False, 6000.0, 120.0, 400.0, point, 0.5)
    assert braced["slender"] and braced["km"] == pytest.approx(1.0)
    assert braced["db"] == pytest.approx(1 / (1 - 1.5e6 / braced["nc"]))
    unbraced = bm.magnify(1.5e6, 40e6, -40e6, True, False, 6000.0, 120.0, 400.0, point, 0.5, 1.6)
    assert unbraced["limit"] == 22.0 and unbraced["delta"] == pytest.approx(
        max(unbraced["db"], 1.6)
    )


# ───────────────────────────── AS 3600 13.1, 13.2 anchorage and laps ─────────────────────────


def test_lsy_tb(au):
    from saengine.design import development_factors as dfac

    found = dfac.tension_length(20.0, 500.0, 32.0)
    k2 = (132 - 20) / 100
    assert found["k2"] == pytest.approx(k2) and found["k3"] == 1.0 and found["k1"] == 1.0
    basic = 0.5 * 500 * 20 / (k2 * math.sqrt(32))
    assert found["length"] == pytest.approx(max(basic, 0.058 * 500 * 20))
    top = dfac.tension_length(20.0, 500.0, 32.0, top=True)
    assert top["k1"] == 1.3
    covered = dfac.tension_length(20.0, 500.0, 32.0, cd=60.0)
    assert covered["k3"] == pytest.approx(0.7)  # 1 - 0.15 (60 - 20)/20 = 0.7
    assert dfac.tension_length(20.0, 500.0, 80.0)["length"] == pytest.approx(
        max(0.5 * 500 * 20 / (k2 * math.sqrt(65)), 0.058 * 500 * 20)
    )


def test_laps_hooks_compression(au):
    from saengine.design import development_factors as dfac
    from saengine.drawings import detailing

    ld = dfac.tension_length(16.0, 500.0, 32.0)["length"]
    assert dfac.lap_tension(16.0, 500.0, 32.0)["lap"] == pytest.approx(max(1.25 * ld, 29 * 16))
    assert dfac.hook_length(16.0, 500.0, 32.0)["length"] == pytest.approx(0.5 * ld)
    lsc = max(0.22 * 500 * 16 / math.sqrt(32), 0.0435 * 500 * 16, 200)
    assert dfac.compression_length(16.0, 500.0, 32.0)["length"] == pytest.approx(lsc)
    assert dfac.lap_compression(16.0, 500.0, 32.0)["lap"] == pytest.approx(max(lsc, 40 * 16, 300))
    # The bar detailing reads the pack's method, with its own clause (no BNBC number).
    rule = detailing.development_tension(16.0, 500.0, 32.0)
    assert rule.value == pytest.approx(ld) and "AS 3600" in rule.clause
    assert detailing.lap_tension(16.0, 500.0, 32.0).value == pytest.approx(max(1.25 * ld, 464))


# ───────────────────────────── AS 3600 Chapter 7 strut-and-tie ─────────────────────────────


def test_struts_nodes_ties(au):
    from saengine.design import stress_fields as sf

    fc = 40.0
    assert sf.strut_strength(fc, cracked=False) == pytest.approx(1.0 * 0.6 * 0.9 * fc)
    theta = math.radians(45)
    beta = 1 / (1 + 0.66)
    assert sf.bottle_beta(theta) == pytest.approx(beta)
    assert sf.strut_strength(fc, True, theta) == pytest.approx(beta * 0.6 * 0.9 * fc)
    assert sf.bottle_beta(math.radians(20)) == pytest.approx(
        max(1 / (1 + 0.66 / math.tan(math.radians(20)) ** 2), 0.3)
    )
    assert sf.node_strength(fc, "CCT") == pytest.approx(0.8 * 0.6 * 0.9 * fc)
    assert sf.tie_capacity(1000.0, 500.0) == pytest.approx(0.8 * 1000 * 500)
    assert sf.nu_prime(fc) == 1.0


# ───────────────────────────── walls (11.7, 11.3.11) ─────────────────────────────


def test_wall_steel_au_nz():
    from saengine.design import walls

    with code_context.using(registry.load(AU)):
        assert walls.least_ratios("rhoOtherBars") == (0.0015, 0.0025)
        assert walls.spacing_thickness() == 2.5 and walls.steel_limit("spacingMax") == 350.0
        assert walls.spacing_text("min(3t, 450 mm)", "t") == "min(2.5t, 350 mm)"
    with code_context.using(registry.load(NZ)):
        assert walls.least_ratios("rhoOtherBars") == (0.0014, 0.0014)
        assert walls.spacing_thickness() == 3.0
    with code_context.using(registry.load("bnbc2020")):
        assert walls.spacing_thickness() == 3.0
        assert walls.spacing_text("min(3t, 450 mm)", "t") == "min(3t, 450 mm)"


# ───────────────────────────── NZS 3101 ductile detailing ─────────────────────────────


def test_nz_levels(nz):
    from saengine.design import ductile_detailing as dd

    ductile, limited = dd.rules_for("special"), dd.rules_for("intermediate")
    assert ductile.columns.strongColumn == 1.9 and limited.columns.strongColumn == 1.47
    assert ductile.beams.hoopSpacing == (0.25, 6.0, 150.0)
    assert limited.beams.hoopSpacing == (0.25, 10.0, 200.0)
    assert limited.joints is ductile.joints  # not given by the level: the method's own
    assert dd.capacity_factor() and dd.design_yield(500.0) == pytest.approx(0.85 * 500)


def test_nz_wall_shear_magnification(nz):
    from types import SimpleNamespace

    from saengine.design import ductile_detailing as dd
    from saengine.design import walls

    rule = dd.rules_for("special").walls.shearAmplification
    wall = SimpleNamespace(length=5000.0, height=30000.0, clear_height=3000.0)
    factor, _how = walls.shear_amplification(wall, rule)
    # 10 storeys: ωv = 1.3 + 10/30 = 1.633, × φo,w 1.47
    assert factor == pytest.approx(1.47 * (1.3 + 10 / 30))
    low = SimpleNamespace(length=5000.0, height=12000.0, clear_height=3000.0)
    assert walls.shear_amplification(low, rule)[0] == pytest.approx(1.47 * (0.9 + 4 / 10))


# ───────────────────────────── AS 4100 Chapter 9 connections ─────────────────────────────


def test_bolts_and_welds(au):
    from saengine.design import steel_connections as sc

    ao = math.pi * 20**2 / 4
    assert sc.bolt_shear_capacity("8.8", 20.0) == pytest.approx(0.8 * 0.62 * 830 * 0.716 * ao)
    assert sc.bolt_shear_capacity("A325N", 20.0) == pytest.approx(0.8 * 0.62 * 830 * 0.716 * ao)
    full, _ = sc.bolt_tension_capacity("8.8", 20.0)
    assert full == pytest.approx(0.8 * 245 * 830)
    assert sc.bearing_capacity(20.0, 10.0, 430.0, math.inf) == pytest.approx(
        0.9 * 3.2 * 20 * 10 * 430
    )
    assert sc.bearing_capacity(20.0, 10.0, 430.0, 20.0) == pytest.approx(0.9 * 30 * 10 * 430)
    assert sc.fillet_capacity_per_mm(6.0, 480.0) == pytest.approx(0.8 * 0.6 * 490 * 0.707 * 6)
    assert sc.long_joint_factor(800.0, False) == pytest.approx(1.075 - 800 / 4000)
    assert sc.long_joint_factor(2000.0, False) == 0.75
    assert sc.hole_diameter(20.0) == 22.0 and sc.min_spacing(20.0) == 50.0


def test_nz_inherits_the_connections_and_has_section_12(nz):
    from saengine.design.steel import capacity_factor_joints, limit_state

    assert capacity_factor_joints.active()
    sr = limit_state.seismic_rules()
    assert sr.systems["steelSmf"] == "category1"
    assert sr.frames["category1"].connectionMoment == 1.25


# ───────────────────────────── clauses: no BNBC leak ─────────────────────────────


def test_clauses_are_the_packs(au):
    for key in ("slenderness", "anchorage", "laps", "strutAndTie", "seismicBeams", "seismicJoints"):
        text = code_context.cite("concreteMethods", key)
        assert text.startswith("AS 3600") and "BNBC" not in text
    from saengine.design.walls import ref

    assert "BNBC" not in ref("spacing") and "11.7.3" in ref("spacing")


def test_nz_clauses(nz):
    for key in ("seismicColumns", "seismicJoints", "capacityDesign", "seismicWalls"):
        text = code_context.cite("concreteMethods", key)
        assert text.startswith("NZS 3101") and "AS 3600" not in text
