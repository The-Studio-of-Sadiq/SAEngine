"""Indian Standards pack, concrete and foundations (alpha 9 track C8): IS 456:2000, IS 13920:2016,
IS 6403 and IS 2911 values and methods pinned with their clauses, the default pack unchanged,
and a small generated building designed under the pack.

The expected numbers are worked by hand from the values of the pack's VERIFY.md.
"""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.library.objects import RectangleProfile

PACK = "is-codes"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def is_pack():
    pack = registry.load(PACK)
    with code_context.using(pack):
        yield pack


def _beam(fc=25.0, fy=415.0, b=300.0, h=500.0, bottom=3, top=2, dia=16.0, cover=40.0):
    from saengine.design.rc import Bar, RcSection, bar_area

    y = h / 2 - cover - dia / 2
    xs = lambda n: [
        (-b / 2 + cover + dia / 2) + k * (b - 2 * cover - dia) / (n - 1) for k in range(n)
    ]
    bars = [Bar(x, -y, bar_area(dia), dia) for x in xs(bottom)] + [
        Bar(x, y, bar_area(dia), dia) for x in xs(top)
    ]
    return RcSection(RectangleProfile(xDim=b, yDim=h), tuple(bars), fc, fy)


def test_pack_covers_concrete_and_keeps_the_default_pack():
    found = registry.validate(registry.BUILTIN_DIR / PACK)
    assert not [p for p in found.problems if p.severity == "error"], found.problems
    pack = registry.load(PACK)
    assert all(pack.has(t) for t in ("concreteMethods", "concrete", "foundations"))
    from saengine.design import ductile_detailing, tabulated_shear
    from saengine.design.rc import flexure, shear

    with code_context.using(registry.load("bnbc2020")):
        # BNBC keeps the strength design: no tabulated methods, φ = 0.9 on flexure.
        assert tabulated_shear.rules() is None and ductile_detailing.rules() is None
        assert flexure(_beam(), False).phi == pytest.approx(0.9)
        assert shear(_beam(), 8.0, 2, 150.0).notes is None


def test_design_strengths_and_flexure(is_pack):
    # IS 456 38.1, Annex G: Mu = 0.87 fy Ast (d - 0.42 xu), xu = 0.87 fy Ast / (0.36 fck b).
    from saengine.design import design_strength
    from saengine.design.rc import flexure

    assert design_strength.fcd(25.0) == pytest.approx(0.67 * 25 / 1.5)
    assert design_strength.fyd(415.0) == pytest.approx(415 / 1.15)
    assert design_strength.strength_class(25.0) == "M25"
    section = _beam()
    ast = 3 * math.pi * 16**2 / 4
    d = 500 - 40 - 8
    xu = 415 / 1.15 * ast / (0.36 * 25 * 300)
    expected = 415 / 1.15 * ast * (d - 0.42 * xu)
    result = flexure(section, False)
    assert result.phi == 1.0
    # The compression bars help a little: within 2 % of the singly reinforced closed form.
    assert result.phi_mn == pytest.approx(expected, rel=0.02)


def test_axial_cap_and_minimum_eccentricity(is_pack):
    # IS 456 39.3: Pu = 0.4 fck Ac + 0.67 fy Asc; 25.4: emin = l/500 + D/30 >= 20 mm.
    from saengine.design import design_strength

    section = _beam(b=400, h=400, bottom=3, top=3, dia=20)
    asc = section.steel_area
    assert section.phi_pn_max == pytest.approx(0.4 * 25 * (400 * 400 - asc) + 0.67 * 415 * asc)
    assert design_strength.eccentricity(400.0, 5000.0) == pytest.approx(5000 / 500 + 400 / 30)
    assert design_strength.eccentricity(300.0, 0.0) == pytest.approx(20.0)


def test_shear_by_the_table(is_pack):
    # IS 456 Table 19: M25, pt 0.50 % -> 0.49 MPa; 0.75 % -> 0.57 MPa; Table 20: 3.1 MPa;
    # 40.4: Vus = 0.87 fy Asv d / sv; 26.5.1.6: Asv >= 0.4 b sv / (0.87 fy).
    from saengine.design import tabulated_shear
    from saengine.design.rc import shear

    assert tabulated_shear.tau_c(25.0, 0.5) == pytest.approx(0.49)
    assert tabulated_shear.tau_c(25.0, 0.625) == pytest.approx(0.53)
    assert tabulated_shear.tau_c(20.0, 3.5) == pytest.approx(0.82)
    assert tabulated_shear.tau_c_max(30.0) == pytest.approx(3.5)
    assert tabulated_shear.slab_factor(200.0) == pytest.approx(1.20)
    section = _beam()
    d = 500 - 40 - 8
    pt = 100 * 2 * math.pi * 16**2 / 4 / (300 * d)  # the face with fewer bars (top, 2)
    res = shear(section, 8.0, 2, 150.0)
    asv = 2 * math.pi * 8**2 / 4
    assert res.vc == pytest.approx(tabulated_shear.tau_c(25.0, pt) * 300 * d)
    assert res.phi_vn == pytest.approx(res.vc + 415 / 1.15 * asv * d / 150)
    assert res.av_min == pytest.approx(0.4 * 300 * 150 / (415 / 1.15))
    assert res.av_min_threshold == pytest.approx(0.5 * res.vc)


def test_torsion_and_punching(is_pack):
    # IS 456 41.3.1 Ve = Vu + 1.6 T/b; 41.4.2 Mt = T (1 + D/b)/1.7; 31.6.3.1 ks τc.
    from saengine.design import tabulated_shear
    from saengine.design.rc import flexure

    section = _beam()
    caps = {h: flexure(section, h) for h in (False, True)}
    rows = tabulated_shear.torsion_rows(
        section, 40.0, (8.0, 2, 150.0), [(10e6, 50e3, -40e6, "1.5(D + L)", "B1")], caps
    )
    ve = next(r for r in rows if r["name"].startswith("Torsion: equivalent shear"))
    assert ve["demand"] == pytest.approx((50e3 + 1.6 * 10e6 / 300) / 1e3, abs=0.01)
    me = next(r for r in rows if r["name"].startswith("Torsion: equivalent moment"))
    assert me["demand"] == pytest.approx((40e6 + 10e6 * (1 + 500 / 300) / 1.7) / 1e6, abs=0.01)
    # βc = 300/600 -> ks = 1.0; τc = 0.25 √25 = 1.25 MPa; βc = 0.25 -> ks 0.75.
    assert tabulated_shear.punching_stress(25.0, 300, 600) == pytest.approx(1.25)
    assert tabulated_shear.punching_stress(25.0, 150, 600) == pytest.approx(0.75 * 1.25)


def test_columns_additional_moment_and_load_contour(is_pack):
    # IS 456 39.6: Puz = 0.45 fck Ac + 0.75 fy Asc, αn 1.0 at Pu/Puz <= 0.2 to 2.0 at >= 0.8.
    from saengine.design import additional_moment

    section = _beam(b=400, h=400, bottom=3, top=3, dia=20)
    puz = additional_moment.puz(section)
    asc = section.steel_area
    assert puz == pytest.approx(0.45 * 25 * (400 * 400 - asc) + 0.75 * 415 * asc)
    assert additional_moment.alpha_n(0.1 * puz, puz) == pytest.approx(1.0)
    assert additional_moment.alpha_n(0.5 * puz, puz) == pytest.approx(1.5)
    assert additional_moment.alpha_n(0.9 * puz, puz) == pytest.approx(2.0)
    # 39.7.1: Ma = Pu D/2000 (lex/D)² with k = 1 at Pb.
    r = additional_moment.rules()
    ma = additional_moment._additional(1000e3, 400.0, 6000.0, puz, puz / 2, r.slenderness)
    k = (puz - 1000e3) / (puz - puz / 2)
    assert ma == pytest.approx(1000e3 * 400 / 2000 * 15**2 * min(k, 1.0))


def test_span_depth_and_annex_c(is_pack):
    # IS 456 23.2.1: 26 continuous × kt; Annex C: Ieff between Ir and Igr; acs = k3 ψcs l².
    from saengine.design import span_depth_factors as sdf

    ratio, _ = sdf.allowed_ratio(6000.0, "continuous", 1.0, 0.0, 415.0)
    kt = 1 / (0.225 + 0.00322 * 0.58 * 415 - 0.625 * math.log10(1 / 1.0))
    assert ratio == pytest.approx(26 * min(kt, 2.0))
    long, _ = sdf.allowed_ratio(12000.0, "simple", 0.5, 0.0, 415.0)
    assert long == pytest.approx(20 * 10 / 12 * sdf.tension_factor(0.5, 415.0))
    assert sdf.compression_factor(1.0) == pytest.approx(1.25)
    assert sdf.effective_inertia(1e9, 3e9, 60e6, 100e6, 400, 450, 150) == pytest.approx(
        1e9 / (1.2 - 0.6 * (400 / 450) * (1 - 150 / 450))
    )
    assert sdf.effective_inertia(1e9, 3e9, 10e6, 100e6, 400, 450, 150) == 1e9  # at least Ir
    k4 = min(0.72 * 0.5 / math.sqrt(0.5), 1.0)
    assert sdf.shrinkage_deflection(6000.0, 500.0, 0.5, 0.0, "simple") == pytest.approx(
        0.125 * k4 * 0.0003 / 500 * 6000**2
    )
    assert sdf.creep_coefficient() == pytest.approx(1.6)


def test_cover_durability_bond_and_limits(is_pack):
    # Table 16 moderate 30 mm, columns 40 mm (26.4.2.1); 26.2.1: Ld = φ 0.87 fy / (4 τbd),
    # τbd M25 1.4 × 1.6; laps max(Ld, 30 φ).
    from saengine.design import member_limits

    assert member_limits.nominal_cover(16.0) == pytest.approx(30.0)
    assert member_limits.nominal_cover(20.0, "column") == pytest.approx(40.0)
    ld = member_limits.development_length(16.0, 415.0, 25.0)
    assert ld == pytest.approx(16 * 415 / 1.15 / (4 * 1.4 * 1.6))
    assert member_limits.lap_length(16.0, 415.0, 25.0) == pytest.approx(max(ld, 30 * 16))
    assert member_limits.lap_length(40.0, 415.0, 25.0) is None
    rows = member_limits.beam_rows(_beam(), None, {}, 25.0)
    names = {r["name"].split(" (")[0]: r for r in rows}
    least = names["Least tension steel, bottom"]
    assert least["demand"] == pytest.approx(0.85 / 415 * 300 * (500 - 48), abs=0.01)
    assert not names["Nominal cover"]["ok"]  # 25 mm < 30 mm (moderate)


def test_two_way_panel_coefficients(is_pack):
    # Annex D Table 26, interior panel ly/lx 1.5: αx -0.053 / +0.041, αy 0.032 / 0.024.
    from saengine.design import panel_coefficients

    found = panel_coefficients.moments(1.5, 2, 2)
    assert (found["shortNegative"], found["shortPositive"]) == pytest.approx((0.053, 0.041))
    assert (found["longNegative"], found["longPositive"]) == (0.032, 0.024)
    edge = panel_coefficients.moments(1.25, 0, 0)
    assert edge["shortNegative"] is None and edge["shortPositive"] == pytest.approx(0.0755)
    # 31.4.3.3 end span with αc = 1: 0.75 - 0.10/2, 0.63 - 0.28/2, 0.65/2.
    shares = panel_coefficients.end_span_shares(1.0)
    assert shares == pytest.approx((0.70, 0.49, 0.325))


def test_bearing_capacity_factors(is_pack):
    # IS 6403: φ 30°: Nq 18.40, Nc 30.14, Nγ 22.40; square 1.3, 1.2, 0.8; dq = 1 + 0.1 Df/B √Nφ.
    from saengine.soil.bearing import ultimate

    r = ultimate(0.0, 30.0, 36.0, 18.0, 2.0, 2.0, 2.0)
    assert (r["Nq"], r["Nc"], r["Ngamma"]) == pytest.approx((18.40, 30.14, 22.40), abs=0.01)
    assert (r["sq"], r["sgamma"]) == (1.2, 0.8)
    root = math.tan(math.radians(60))
    assert r["dq"] == pytest.approx(1 + 0.1 * 1.0 * root)
    qnu = 36 * 17.40 * 1.2 * r["dq"] + 0.5 * 18 * 2 * 22.40 * 0.8 * r["dq"]
    assert r["qu"] - 36.0 == pytest.approx(qnu, rel=1e-3)
    # Undrained: Nc 5.14, sc 1 + 0.2 B/L, dc 1 + 0.2 Df/B.
    u = ultimate(50.0, 0.0, 36.0, 18.0, 2.0, 4.0, 2.0)
    assert u["qu"] - 36.0 == pytest.approx(50 * 5.14 * 1.1 * 1.2)


def test_ductile_detailing_values(is_pack):
    # IS 13920:2016: ρmin = 0.24 √fck / fy, hoops min(d/4, 8 db, 100 mm), Ash 0.18 / 0.05,
    # strong column 1.4, joints 1.5 / 1.2 / 1.0 √fck Aej.
    from saengine.design import ductile_detailing

    r = ductile_detailing.rules()
    assert (r.beams.rhoMinRoot, r.beams.hoopSpacing) == (0.24, (0.25, 8, 100))
    assert (r.columns.ash, r.columns.strongColumn) == ((0.18, 0.05), 1.4)
    assert r.joints.gamma == {"4": 1.5, "3": 1.2, "other": 1.0}


def test_generated_building_is_designed_under_the_pack(tmp_path):
    import json
    from pathlib import Path

    from saengine.pipeline.run_all import run_all
    from saengine.project.new_building import create_building

    spec = {
        "name": "IS Concrete",
        "gridsX": [5000],
        "gridsY": [4000],
        "storyCount": 1,
        "typicalHeight": 3000,
        "system": "rcFrame",
        "codePack": PACK,
        "lateralSizing": "gravity",
    }
    root = Path(create_building(spec, tmp_path)["root"])
    result = run_all(root, steps=["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    # Design Reinforcement (its verification takes the pack's checks), applied, then the checks.
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
    report = json.loads(
        (root / "08 FEM/model.results/design-report.json").read_text(encoding="utf-8")
    )["result"]
    assert any("Limit state design" in line for line in report["method"])
    names = {c["name"] for e in report["elements"] for c in e.get("checks", [])}
    assert any(n.startswith("Least tension steel, bottom (") for n in names), sorted(names)
    assert any(n.startswith("Neutral axis depth") for n in names)
    assert any(n.startswith("Deflection: span / effective depth") for n in names)
    # Delhi (zone IV): the IS 13920 rows in place of the parent's Sec 8.3 rows.
    assert any(n.startswith("Detailing: Hoop spacing in lo") for n in names), sorted(names)
    assert not any("8.3.5" in n for n in names)
