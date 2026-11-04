"""Eurocodes pack, concrete and foundations (alpha 9 track C5): EN 1992-1-1, EN 1998-1 Section 5
and EN 1997-1 values and methods, pinned with their clauses, and the default pack unchanged.

The expected numbers are worked by hand from the recommended values (see the pack's VERIFY.md).
"""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.library.objects import RectangleProfile


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def ec():
    pack = registry.load("eurocodes")
    with code_context.using(pack):
        yield pack


def _beam(fc=30.0, fy=500.0, b=300.0, h=500.0, bottom=3, top=2, dia=20.0, cover=40.0):
    from saengine.design.rc import Bar, RcSection, bar_area

    y = h / 2 - cover - dia / 2
    xs = lambda n: [
        (-b / 2 + cover + dia / 2) + k * (b - 2 * cover - dia) / (n - 1) for k in range(n)
    ]
    bars = [Bar(x, -y, bar_area(dia), dia) for x in xs(bottom)] + [
        Bar(x, y, bar_area(dia), dia) for x in xs(top)
    ]
    return RcSection(RectangleProfile(xDim=b, yDim=h), tuple(bars), fc, fy)


# ───────────────────────────── the pack ─────────────────────────────


def test_pack_covers_concrete_and_foundation_methods():
    pack = registry.load("eurocodes")
    assert pack.broken == {}
    assert pack.provided_by("concreteMethods") == "eurocodes"
    assert pack.provided_by("geotechnicalMethods") == "eurocodes"
    default = registry.load("bnbc2020")
    assert not default.has("concreteMethods") and not default.has("geotechnicalMethods")


def test_default_pack_keeps_the_strength_design():
    from saengine.design import design_strength, rc

    with code_context.using(registry.load("bnbc2020")):
        assert not design_strength.partial_factors()
        assert rc.phi_axial_flexure(0.01, 420.0) == 0.9
        s = _beam(fc=28.0, fy=420.0)
        assert s.p0 == pytest.approx(0.85 * 28 * (s.gross_area - s.steel_area) + 420 * s.steel_area)
        assert s.phi_pn_max == pytest.approx(0.80 * 0.65 * s.p0)
        assert rc.shear(s, 10, 2, 150).notes is None


# ───────────────────────────── EN 1992-1-1 materials ─────────────────────────────


def test_strength_class_properties(ec):
    from saengine.design import design_strength as ds

    p = ds.properties(30.0)
    assert p.fcm == 38.0  # Table 3.1
    assert p.fctm == pytest.approx(0.30 * 30 ** (2 / 3), rel=1e-6)  # 2.90
    assert p.fctk005 == pytest.approx(0.7 * p.fctm)
    assert p.ecm == pytest.approx(22000 * 3.8**0.3)  # 32.8 GPa
    assert (p.eps_c2, p.eps_cu2, p.n, p.eps_c3, p.eps_cu3) == pytest.approx(
        (0.002, 0.0035, 2.0, 0.00175, 0.0035)
    )
    assert (p.eta, p.lam) == (1.0, 0.8)  # 3.1.7(3)
    high = ds.properties(70.0)
    assert high.fctm == pytest.approx(2.12 * math.log(1 + 78 / 10))  # 4.61
    assert high.eps_cu2 == pytest.approx((2.6 + 35 * 0.2**4) / 1e3)  # 2.66 ‰
    assert high.n == pytest.approx(1.4 + 23.4 * 0.2**4)
    assert high.eps_c3 == pytest.approx((1.75 + 0.55 * 20 / 40) / 1e3)
    assert high.eta == pytest.approx(0.9) and high.lam == pytest.approx(0.75)
    assert ds.fcd(30.0) == pytest.approx(20.0)  # αcc 1.0, γc 1.5
    assert ds.fyd(500.0) == pytest.approx(434.78, rel=1e-4)  # γs 1.15
    assert ds.fctd(30.0) == pytest.approx(0.7 * p.fctm / 1.5)
    assert ds.strength_class(30.0) == "C30/37"


def test_section_flexure_by_the_rectangular_block(ec):
    from saengine.design import rc

    s = _beam()  # 3 Ø20 bottom, C30/37, B500
    f = rc.flexure(s, hogging=False)
    assert f.phi == 1.0
    # Hand check, tension bars yielding, top bars in compression ignored for a lower bound:
    # x = As fyd / (λ η fcd b), M = As fyd (d - λ x / 2).
    a_s = 3 * math.pi * 100
    d = 500 - 40 - 10
    x = a_s * 434.78 / (0.8 * 20.0 * 300)
    m_lower = a_s * 434.78 * (d - 0.4 * x)
    assert f.mn == pytest.approx(m_lower, rel=0.03)
    assert rc.eps_cu(30.0) == 0.0035


def test_axial_resistance_and_minimum_eccentricity(ec):
    from saengine.design import design_strength as ds

    s = _beam(b=400, h=400, bottom=3, top=3)
    ast = s.steel_area
    # NRd = η fcd (Ac - As) + min(fyd, Es εc2) As = 20 (Ac - As) + 400 As (6.1(5)).
    assert s.phi_pn_max == pytest.approx(20.0 * (160000 - ast) + 400.0 * ast)
    assert ds.eccentricity(400) == 20.0  # h/30 = 13.3 < 20 mm (6.1(4))
    assert ds.eccentricity(900) == 30.0
    assert ds.minimum_moment(1e6, 400) == 2e7


def test_shear_by_the_variable_strut(ec):
    from saengine.design import rc, strut_shear

    s = _beam()
    r = strut_shear.rules()
    d = 450.0
    k = 1 + math.sqrt(200 / d)
    rho = 2 * math.pi * 100 / (300 * d)  # the face with fewer bars (2 Ø20 top)
    vrdc = max(0.12 * k * (100 * rho * 30) ** (1 / 3), 0.035 * k**1.5 * math.sqrt(30)) * 300 * d
    assert strut_shear.concrete_resistance(300, d, rho, 30.0, 0.0, r) == pytest.approx(vrdc)
    out = rc.shear(s, 10, 2, 200)
    assert out.vc == pytest.approx(vrdc)
    asw = 2 * math.pi * 25
    z = 0.9 * d
    nu1 = 0.6 * (1 - 30 / 250)
    omega = asw * 434.78 / (200 * 300 * nu1 * 20)
    cot = min(2.5, max(1.0, math.sqrt(1 / omega - 1)))  # 2.5 here
    assert out.cot_theta == pytest.approx(cot, rel=1e-4)
    vrds = asw / 200 * z * 434.78 * cot
    assert out.vs == pytest.approx(min(vrds, 300 * z * nu1 * 20 / (cot + 1 / cot)), rel=1e-4)
    assert out.phi_vn == pytest.approx(max(vrdc, out.vs))
    # ρw,min = 0.08 √fck / fyk (9.5N): Ø10 legs at 200 pass, Ø6 at 300 do not.
    assert out.with_min_stirrups
    weak = rc.shear(s, 6, 2, 300)
    assert not weak.with_min_stirrups and weak.av_min_threshold == 0.0
    assert strut_shear.min_link_ratio(30, 500) == pytest.approx(0.08 * math.sqrt(30) / 500)
    assert strut_shear.max_link_spacing(450) == pytest.approx(337.5)  # 0.75 d (9.6N)


def test_torsion_thin_walled(ec):
    from saengine.design import strut_shear

    t = strut_shear.torsion(300, 500, 50, 30.0, 500.0, ted=20e6, cot_theta=1.0)
    tef = max(150000 / 1600, 100)  # A/u = 93.75 < 2 × 50
    assert t.tef == pytest.approx(tef)
    ak = (300 - tef) * (500 - tef)
    nu = 0.6 * (1 - 30 / 250)
    assert t.trd_max == pytest.approx(2 * nu * 20 * ak * tef * 0.5)  # 6.30 at θ = 45°
    assert t.links_per_spacing == pytest.approx(20e6 / (2 * ak * 434.78), rel=1e-4)


def test_punching_on_the_basic_perimeter(ec):
    from saengine.design import perimeter_punching as pp

    out = pp.punching(500e3, 200, 400, 400, 30.0, 0.01, "interior")
    u1 = 4 * 400 + 2 * math.pi * 400
    assert out.u1 == pytest.approx(u1)
    assert out.beta == 1.15  # Fig 6.21N
    k = 2.0
    vrdc = max(0.12 * k * (100 * 0.01 * 30) ** (1 / 3), 0.035 * k**1.5 * math.sqrt(30))
    assert out.v_rdc == pytest.approx(vrdc)
    assert out.v_ed == pytest.approx(1.15 * 500e3 / (u1 * 200))
    assert out.v_rdmax == pytest.approx(0.4 * 0.6 * (1 - 30 / 250) * 20)


def test_service_stresses_cracks_and_span_depth(ec):
    from saengine.design import crack_control as cc

    lim = cc.stress_limits(30, 500, "XD1")
    assert lim["concreteCharacteristic"] == 18.0 and lim["concreteQuasiPermanent"] == 13.5
    assert lim["steel"] == 400.0  # 0.8 fyk (7.2(5))
    assert "concreteCharacteristic" not in cc.stress_limits(30, 500, "XC1")
    assert cc.wmax("XC3") == 0.3 and cc.wmax("XC1") == 0.4  # Table 7.1N
    # As,min = kc k fctm Act / fyk, h = 500: k = 1 - 0.35 × 200 / 500.
    k = 1.0 - 0.35 * 200 / 500
    fctm = 0.30 * 30 ** (2 / 3)
    assert cc.min_crack_steel(300, 500, 30, 500) == pytest.approx(0.4 * k * fctm * 300 * 250 / 500)
    w = cc.crack_width(300, 500, 450, 942.5, 20, 40, 100e6, 30)
    assert 0.1 < w.wk < 0.4
    assert w.sr_max == pytest.approx(3.4 * 40 + 0.8 * 0.5 * 0.425 * 20 / w.rho_eff)
    # 7.16a with ρ = 0.5 % at C30: ρ0 = 0.548 %.
    rho0 = 1e-3 * math.sqrt(30)
    ratio = (
        11 + 1.5 * math.sqrt(30) * rho0 / 0.005 + 3.2 * math.sqrt(30) * (rho0 / 0.005 - 1) ** 1.5
    )
    assert cc.span_depth_limit("simplySupported", 0.005, 0.0, 30) == pytest.approx(ratio)
    assert cc.span_depth_limit("endSpan", 0.005, 0.0, 30) == pytest.approx(1.3 * ratio)
    assert cc.span_depth_limit("interiorSpan", 0.005, 0.0, 30, span=10000) == pytest.approx(
        1.5 * ratio * 0.7
    )


def test_cover_anchorage_and_laps(ec):
    from saengine.design import bar_rules as br

    # S4, XC3: cmin,dur 25; C35/45 drops a class (Table 4.3N): 20; + Δcdev 10.
    assert br.nominal_cover(["XC3"], 16, 30)["cnom"] == 35.0
    assert br.nominal_cover(["XC3"], 16, 35)["cnom"] == 30.0
    assert br.nominal_cover(["XC3", "XD1"], 16, 30)["cmin"] == 35.0
    assert br.nominal_cover(["XC1"], 25, 30)["cmin"] == 25.0  # cmin,b = φ governs
    assert br.nominal_cover(["XC3"], 16, 30, design_life=100)["cminDur"] == 35.0  # S6
    fctd = 0.7 * 0.30 * 30 ** (2 / 3) / 1.5
    assert br.bond_strength(30, 16) == pytest.approx(2.25 * fctd)  # 8.4.2
    assert br.bond_strength(30, 16, good_bond=False) == pytest.approx(0.7 * 2.25 * fctd)
    lb = 16 / 4 * 434.78 / (2.25 * fctd)
    assert br.basic_length(16, 434.78, 30) == pytest.approx(lb, rel=1e-4)
    a = br.anchorage_length(16, 30, 500)
    assert a["lbd"] == pytest.approx(lb, rel=1e-4)
    lap = br.lap_length(16, 30, 500, lapped_share=1.0)
    assert lap["alpha6"] == 1.5 and lap["l0"] == pytest.approx(1.5 * lb, rel=1e-4)
    assert br.lap_alpha6(0.25) == 1.0 and br.lap_alpha6(0.5) == 1.4


def test_member_steel_limits(ec):
    from saengine.design import bar_rules as br

    fctm = 0.30 * 30 ** (2 / 3)
    assert br.beam_min_steel(300, 450, 30, 500) == pytest.approx(0.26 * fctm / 500 * 300 * 450)
    assert br.beam_min_steel(300, 450, 12, 500) == pytest.approx(0.0013 * 300 * 450)
    assert br.column_min_steel(2e6, 160000, 500) == pytest.approx(max(0.1 * 2e6 * 1.15 / 500, 320))
    assert br.column_link_spacing(16, 300) == 300.0 and br.column_link_spacing(25, 600) == 400.0
    rows = br.beam_rows(_beam())
    assert {r["name"] for r in rows} >= {"Least tension steel, bottom", "Largest steel"}
    assert all(r["ok"] for r in rows)


# ───────────────────────────── EN 1998-1 Section 5 ─────────────────────────────


def test_ductility_classes(ec):
    from saengine.design import curvature_ductility as cd

    assert cd.ductility_class("special") == "DCH" and cd.ductility_class("intermediate") == "DCM"
    assert cd.ductility_class("ordinary") is None
    assert cd.curvature_ductility(3.9, 0.8, 0.5) == pytest.approx(6.8)  # 2 q0 - 1
    assert cd.curvature_ductility(3.9, 0.25, 0.5) == pytest.approx(1 + 2 * 2.9 * 2)
    assert cd.curvature_ductility(5.85, 0.8, 0.5, "DCH", class_b=True) == pytest.approx(1.5 * 10.7)
    assert cd.beam_hoop_spacing(500, 8, 20, "DCM") == 125.0  # hw/4
    assert cd.beam_hoop_spacing(700, 8, 16, "DCH") == 96.0  # 6 dbL
    assert cd.column_hoop_spacing(320, 20, "DCM") == 160.0  # b0/2
    assert cd.column_hoop_spacing(320, 20, "DCH") == 106.66666666666667  # b0/3
    assert cd.column_critical_length(400, 2600, "DCM") == 450.0
    assert cd.column_critical_length(500, 2600, "DCH") == 750.0
    assert cd.class_rules("DCH").gammaRdBeam == 1.2 and cd.class_rules("DCM").gammaRdColumn == 1.1
    assert cd.strong_column(130.0, 100.0, "DCM") == pytest.approx(1.0)
    eta = 0.6 * (1 - 30 / 250)
    assert cd.joint_shear_resistance(30, 0.2, 400, 400) == pytest.approx(
        eta * 20 * math.sqrt(1 - 0.2 / eta) * 160000
    )
    assert cd.confinement(6.8, 0.3, 434.78 / 2e5, 320, 320, "DCM") == pytest.approx(
        30 * 6.8 * 0.3 * 434.78 / 2e5 - 0.035
    )
    assert cd.wall_critical_height(4000, 30000, "DCM") == 5000.0


# ───────────────────────────── EN 1997-1 ─────────────────────────────


def test_design_approaches_and_factor_sets(ec):
    from saengine.substructure import limit_state_geotechnics as lg

    assert lg.rules().designApproach == "DA1"
    c1, c2 = lg.combinations()
    assert (c1.actions, c1.materials, c1.resistances) == ("A1", "M1", "R1")
    assert (c2.actions, c2.materials, c2.pileResistances) == ("A2", "M2", "R4")
    assert lg.combinations("DA2")[0].resistances == "R2"
    assert lg.combinations("DA3")[0].structuralActions == "A1"
    assert lg.design_actions(100, 50, "A1") == 210.0
    assert lg.design_actions(100, 50, "A2") == 165.0
    p = lg.design_parameters(30.0, 5.0, 50.0, 18.0, "M2")
    assert math.tan(math.radians(p.phi)) == pytest.approx(math.tan(math.radians(30)) / 1.25)
    assert (p.c, p.cu) == (4.0, pytest.approx(50 / 1.4))


def test_bearing_resistance_annex_d(ec):
    from saengine.substructure import limit_state_geotechnics as lg

    p = lg.design_parameters(30.0, 0.0, None, 18.0, "M1")
    out = lg.bearing_resistance(2.0, 2.0, p, q=18.0, v=1000.0)
    nq = math.exp(math.pi * math.tan(math.radians(30))) * math.tan(math.radians(60)) ** 2
    assert out["Nq"] == pytest.approx(nq)  # 18.40
    assert out["Ngamma"] == pytest.approx(2 * (nq - 1) * math.tan(math.radians(30)))  # 20.09
    sq = 1 + math.sin(math.radians(30))
    assert out["sq"] == pytest.approx(sq) and out["sgamma"] == pytest.approx(0.7)
    expect = 18 * nq * sq + 0.5 * 18 * 2.0 * out["Ngamma"] * 0.7
    assert out["q"] == pytest.approx(expect)
    und = lg.bearing_resistance(2.0, 2.0, lg.design_parameters(0, 0, 60.0, 18.0, "M1"), 18.0,
                                drained=False)  # fmt: skip
    assert und["q"] == pytest.approx((math.pi + 2) * 60 * 1.2 + 18)
    assert lg.bearing_design(1400.0, "R2") == pytest.approx(1000.0)
    assert lg.sliding_resistance(500, "R2", phi_cv=30) == pytest.approx(
        500 * math.tan(math.radians(30)) / 1.1
    )
    assert lg.sliding_resistance(500, "R1", area=4.0, cu=50, water_at_interface=True) == 200.0


def test_pile_resistance_with_correlation_factors(ec):
    from saengine.substructure import limit_state_geotechnics as lg

    assert lg.correlation_factors(1) == (1.4, 1.4)
    assert lg.correlation_factors(2) == (1.3, 1.2)
    assert lg.correlation_factors(6) == (1.0, 1.0)
    assert lg.correlation_factors(3, load_tests=False) == (1.33, 1.23)
    assert lg.correlation_factors(6, load_tests=False) == pytest.approx((1.28, 1.135))
    assert lg.pile_resistance_from_tests([2000, 2400]) == pytest.approx(min(2200 / 1.3, 2000 / 1.2))
    rk = 1692.3
    assert lg.pile_design_resistance(rk, "bored", "R1") == pytest.approx(rk / 1.15)
    assert lg.pile_design_resistance(rk, "bored", "R4") == pytest.approx(rk / 1.5)
    assert lg.pile_design_resistance(rk, "driven", "R4", "tension") == pytest.approx(rk / 1.6)
    summary = lg.load_test_summary(
        [{"kind": "compression", "group": False, "ultimate": 2000.0},
         {"kind": "compression", "group": False, "ultimate": 2400.0}], "bored"
    )  # fmt: skip
    assert summary["Rck"] == pytest.approx(1666.7, abs=0.1)
    assert summary["Rcd"] == {"DA1-C1": pytest.approx(1449.3, abs=0.1),
                              "DA1-C2": pytest.approx(1111.1, abs=0.1)}  # fmt: skip
    with code_context.using(registry.load("bnbc2020")):
        assert lg.load_test_summary([{"kind": "compression", "ultimate": 1.0}], "bored") is None


# ───────────────────────────── a small building ─────────────────────────────


def test_generated_building_is_designed_under_the_pack(tmp_path):
    import json
    from pathlib import Path

    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building

    spec = {
        "name": "EC Concrete",
        "gridsX": [5000],
        "gridsY": [4000],
        "storyCount": 1,
        "typicalHeight": 3000,
        "system": "rcFrame",
        "codePack": "eurocodes",
        "zoneCoefficient": 0.1,
        "windSpeed": 25.0,
        "windExposure": "II",
        "siteClass": "SC",
        "siteClassSource": "entered",
        "lateralSizing": "gravity",
    }
    root = Path(create_building(spec, tmp_path)["root"])
    result = run_all(root, steps=["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    # Design Reinforcement (its sizing is the parent's), applied, then the design checks.
    from saengine.rpc import handlers

    with code_context.project(root):
        proposal = handlers.design_proposal(
            str(root / "08 FEM/model.results"), str(root / "08 FEM/model.osmodel")
        )
    objects_path, bim_path = root / "04 Objects/objects.json", root / "06 BIM/bim.json"
    applied = handlers.design_apply_proposal(
        objects_path.read_text(encoding="utf-8"), bim_path.read_text(encoding="utf-8"), proposal
    )
    objects_path.write_text(applied["objectsText"], encoding="utf-8")
    bim_path.write_text(applied["bimText"], encoding="utf-8")
    result = run_all(root, steps=["derive", "analysis", "design"])
    assert result.steps[-1].status in ("ok", "warning"), [s.message for s in result.steps]
    found = list((root / "08 FEM/model.results").glob("design*.json"))
    texts = " ".join(p.read_text(encoding="utf-8") for p in found)
    assert "fcd =" in texts, [s.message for s in result.steps]
    assert "VRd,c" in texts
    assert "Least tension steel" in texts
    report = json.loads(
        (root / "08 FEM/model.results/design-report.json").read_text(encoding="utf-8")
    )["result"]
    # The method states the partial factors; the members carry the pack's rows.
    assert any("partial factors" in line for line in report["method"])
    names = {c["name"] for e in report["elements"] for c in e.get("checks", [])}
    assert {"Least tension steel, bottom", "Least column steel", "Shear along x"} <= names
    # The generator's frame is the DCH system: the curvature-ductility rows are there.
    assert any(n.startswith("Hoop spacing in critical regions (DCH)") for n in names)
