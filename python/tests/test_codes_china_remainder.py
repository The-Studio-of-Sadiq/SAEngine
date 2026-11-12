"""The Chinese pack's remainder (``china-gb``, alpha 9 track C20b): GB 50010 design yields by
bar grade, torsion on Wt with βt, punching 0.7 βh ft η um h0, crack widths and the long-term
stiffness, cover by environment class, la / laE and the laps, slender columns by Cm ηns, walls
by the shear span ratio; the seismic grade's factors and γRE in the member design; the
vertical earthquake and the top force δn; GB 50017 bolts and fillet welds and the seismic steel
by grade; GB 50007 fa and the layer-wise settlement with ψs. The generic methods are off in
every other pack (the default pack's results do not change).

The values are those of the pack's ``VERIFY.md`` (C20b rows); a test failing here after a
value is changed there says the pack and its verification list disagree. Not run when written
(owner, 2026-11-05): the test pass is the next week's.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

CN = "china-gb"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    """No pack of the machine's user folder takes part."""
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


@pytest.fixture
def cn():
    loaded = registry.load(CN)
    with code_context.using(loaded):
        yield loaded


def _beam(fc=20.1, fy=400.0, b=300.0, h=500.0, bottom=3, top=2, dia=16.0, cover=35.0):
    from saengine.design.rc import Bar, RcSection, bar_area
    from saengine.library.objects import RectangleProfile

    y = h / 2 - cover - dia / 2
    xs = lambda n: [
        (-b / 2 + cover + dia / 2) + k * (b - 2 * cover - dia) / (n - 1) for k in range(n)
    ]
    bars = [Bar(x, -y, bar_area(dia), dia) for x in xs(bottom)] + [
        Bar(x, y, bar_area(dia), dia) for x in xs(top)
    ]
    return RcSection(RectangleProfile(xDim=b, yDim=h), tuple(bars), fc, fy)


def test_pack_is_still_valid():
    found = registry.validate(registry.BUILTIN_DIR / CN)
    assert not [p for p in found.problems if p.severity == "error"], found.problems


# ───────────────────────────── design yields ─────────────────────────────


def test_design_yield_by_bar_grade(cn):
    from saengine.design import design_strength as ds
    from saengine.design import tabulated_shear as ts

    # GB 50010 Table 4.2.3-1: HPB300 270, HRB335 300, HRB400 360, HRB500 435.
    assert ds.fyd(300.0) == pytest.approx(270.0)
    assert ds.fyd(335.0) == pytest.approx(300.0)
    assert ds.fyd(400.0) == pytest.approx(360.0)
    assert ds.fyd(500.0) == pytest.approx(435.0)
    assert ds.fyd(450.0) == pytest.approx(450.0 / 1.15)  # a grade outside the table
    # Stirrups at most 360 MPa design (fyMax 400 -> 360).
    assert ts.stirrup_yield(500.0) == pytest.approx(360.0)
    # 6.2.15: the steel term 0.9 fy' As'.
    n = ds.axial_resistance(20.1, 400.0, 2e5, 1e5, 2000.0)
    assert n == pytest.approx(0.642857 * 20.1 * 1e5 + 0.9 * 360.0 * 2000.0)


def test_default_and_is_packs_keep_their_yields():
    from saengine.design import design_strength as ds
    from saengine.design import tabulated_shear as ts

    with code_context.using(registry.load("is-codes")):
        assert ds.fyd(415.0) == pytest.approx(415.0 / 1.15)
        assert ts.stirrup_yield(415.0) == pytest.approx(min(415.0, ts.rules().fyMax) / 1.15)
        p = ts.punching_rules()
        assert ts.punching_stress(25.0, 400, 600) == pytest.approx(
            min(1.0, p.ratioBase + 400 / 600) * p.coefficient * math.sqrt(25.0)
        )
    with code_context.using(registry.load("bnbc2020")):
        assert not ds.partial_factors()


# ───────────────────────────── torsion, punching ─────────────────────────────


def test_torsion_plastic_modulus_and_beta_t(cn):
    from saengine.design import plastic_torsion as pt

    r = pt.rules()
    assert r is not None and r.method == "plasticModulus"
    # 6.4.3: Wt = b²(3h - b)/6.
    assert pt.plastic_modulus(300, 500) == pytest.approx(300**2 * (1500 - 300) / 6)
    wt = pt.plastic_modulus(300, 500)
    # 6.4.8: βt = 1.5 / (1 + 0.5 V Wt / (T b h0)), within 0.5-1.0.
    t, v, b, h0 = 20e6, 100e3, 300.0, 457.0
    expected = 1.5 / (1 + 0.5 * v * wt / (t * b * h0))
    assert pt.beta_t(t, v, wt, b, h0, r) == pytest.approx(min(max(expected, 0.5), 1.0))
    rows = pt.torsion_rows(_beam(), 35.0, (8.0, 2, 150.0), [(30e6, 120e3, 50e6, "c1", "mid")])
    names = [row["name"] for row in rows]
    assert any(n.startswith("Torsion: section") for n in names)
    assert any(n.startswith("Torsion: closed links") for n in names)
    assert any(n.startswith("Torsion: longitudinal steel") for n in names)


def test_punching_tensile_form(cn):
    from saengine.design import design_strength as ds
    from saengine.design import tabulated_shear as ts

    ft = ds.fctd(20.1)
    # 6.5.1: 0.7 βh ft η um h0; η1 = 0.4 + 1.2/βs <= 1 (a square column: 1.0), η2 = 0.5 + αs
    # h0 / (4 um): an interior column (αs 40) with a long perimeter governs by η2.
    assert ts.punching_stress(20.1, 400, 400, 200.0, 2400.0, 40.0) == pytest.approx(0.7 * ft)
    eta2 = 0.5 + 40 * 200.0 / (4 * 8000.0)
    assert ts.punching_stress(20.1, 400, 400, 200.0, 8000.0, 40.0) == pytest.approx(0.7 * ft * eta2)
    # βh 1.0 to 800 mm, 0.9 at 2000 mm, linear between.
    assert ts.punching_depth_factor(1400.0) == pytest.approx(0.95)
    # A column with long / short = 3: η1 = 0.4 + 1.2/3 = 0.8.
    assert ts.punching_stress(20.1, 300, 900, 200.0, 2400.0, 40.0) == pytest.approx(0.7 * ft * 0.8)


# ───────────────────────────── cover, anchorage, member steel ─────────────────────────────


def test_cover_by_environment_class(cn):
    from saengine.design import member_limits as ml

    # Table 8.2.1, class 一: slabs 15, beams and columns 20 mm (+ 5 mm at C25 and below).
    assert ml.exposure()[0] == "一"
    assert ml.nominal_cover(12.0, "slab", 20.1) == pytest.approx(15.0)
    assert ml.nominal_cover(16.0, "beam", 20.1) == pytest.approx(20.0)
    assert ml.nominal_cover(16.0, "beam", 16.7) == pytest.approx(25.0)
    assert ml.nominal_cover(25.0, "column", 20.1) == pytest.approx(25.0)  # at least d
    assert ml.nominal_cover(16.0, "footing", 20.1) == pytest.approx(40.0)  # 8.2.2


def test_anchorage_and_laps(cn):
    from saengine.design import member_limits as ml

    # 8.3.1: lab = 0.14 fy d / ft (ribbed), ft of C30 1.43, fy 360.
    la = ml.development_length(20.0, 400.0, 20.1)
    assert la == pytest.approx(0.14 * 360.0 / 1.43 * 20.0, rel=3e-3)
    # 8.3.2: ζa 1.10 above 25 mm.
    la28 = ml.development_length(28.0, 400.0, 20.1)
    assert la28 == pytest.approx(1.1 * 0.14 * 360.0 / 1.43 * 28.0, rel=3e-3)
    # 11.1.7: laE = ζaE la (grade 一, 二: 1.15).
    assert ml.development_length(20.0, 400.0, 20.1, seismic=1.15) == pytest.approx(1.15 * la)
    # 8.4.4: ll = ζl la, 1.2 at 25 %, 1.4 at 50 % (columns), at least 300 mm.
    assert ml.lap_length(20.0, 400.0, 20.1) == pytest.approx(1.2 * la)
    assert ml.lap_length(20.0, 400.0, 20.1, share=0.5) == pytest.approx(1.4 * la)
    assert ml.lap_length(8.0, 400.0, 50.2) == pytest.approx(300.0)


def test_beam_least_steel_on_b_h(cn):
    from saengine.design import design_strength as ds
    from saengine.design import member_limits as ml

    section = _beam(bottom=2, dia=12.0)
    rows = ml.beam_rows(section, None, {}, 35.0)
    least = next(r for r in rows if r["name"].startswith("Least tension steel, bottom"))
    ratio = max(0.002, 0.45 * ds.fctd(20.1) / 360.0)  # 8.5.1
    assert least["demand"] == pytest.approx(ratio * 300 * 500, abs=0.01)


# ───────────────────────────── cracks, deflection ─────────────────────────────


def test_crack_width_with_psi(cn):
    from saengine.design import design_strength as ds
    from saengine.design import tension_stiffening as tsf

    section = _beam()
    mq = 80e6
    w, _how = tsf.crack_width(section, mq, False)
    h0 = section.effective_depth(top=False)
    area = sum(b.area for b in section.bars if b.y < 0)
    rho_te = max(area / (0.5 * 300 * 500), 0.01)
    sigma = mq / (0.87 * h0 * area)
    ftk = ds.properties(20.1).fctk005
    psi = min(max(1.1 - 0.65 * ftk / (rho_te * sigma), 0.2), 1.0)
    expected = 1.9 * psi * sigma / section.es * (1.9 * 35.0 + 0.08 * 16.0 / rho_te)  # 7.1.2
    assert w == pytest.approx(expected, rel=1e-6)


def test_long_term_stiffness(cn):
    from saengine.design import tension_stiffening as tsf

    section = _beam(top=0)
    ec = 30000.0
    b_long, _note = tsf.stiffness(section, 60e6, False, ec)
    area, _rho_te, _sigma, psi = tsf.steel_terms(section, 60e6, False, tsf.deflection_rules())
    h0 = section.effective_depth(top=False)
    rho = area / (300 * h0)
    bs = section.es * area * h0**2 / (1.15 * psi + 0.2 + 6 * section.es / ec * rho)  # 7.2.3
    assert b_long == pytest.approx(bs / 2.0)  # θ = 2.0 without compression steel (7.2.5)
    assert tsf.limit_divisor(6000) == 200 and tsf.limit_divisor(8000) == 250  # Table 3.4.3
    assert tsf.limit_divisor(12000) == 300


# ───────────────────────────── slender columns, walls ─────────────────────────────


def test_end_moment_magnifier(cn):
    from saengine.design import end_moment_magnifier as em

    s = em.rules()
    assert s is not None
    radius = 400 / math.sqrt(12)
    m, cm, eta, exempt = em.magnified(50e6, 100e6, 1e6, 4000, 400, 360, 160000, 14.3, radius, s)
    assert not exempt
    assert cm == pytest.approx(0.85)  # 6.2.4: 0.7 + 0.3 M1/M2
    zeta = min(0.5 * 14.3 * 160000 / 1e6, 1.0)
    expected = 1 + (4000 / 400) ** 2 * zeta / (1300 * (100e6 / 1e6 + 20) / 360)
    assert eta == pytest.approx(expected)
    assert m == pytest.approx(cm * eta * 100e6)
    # 6.2.3: double curvature, short and lightly loaded: not needed.
    m, _cm, _eta, exempt = em.magnified(-50e6, 100e6, 5e5, 2500, 400, 360, 160000, 14.3, radius, s)
    assert exempt and m == pytest.approx(100e6)


def test_wall_shear_by_shear_span_ratio(cn):
    from saengine.design import design_strength as ds
    from saengine.design import shear_span_walls as ssw

    t, lw, fc, fy, rho_h = 200.0, 3000.0, 20.1, 400.0, 0.0025
    v, m, n = 600e3, 3.6e9, 2000e3
    vu, lam, cap = ssw.resistance(v, m, n, t, lw, fc, fy, rho_h, False)
    h0 = 0.9 * lw
    lam_e = min(max(m / (v * h0), 1.5), 2.2)
    axial = min(n, 0.2 * ds.fcd(fc, shear=True) * t * lw)
    expected = (0.5 * ds.fctd(fc) * t * h0 + 0.13 * axial) / (lam_e - 0.5) + 360.0 * rho_h * t * h0
    assert lam == pytest.approx(lam_e)
    assert vu == pytest.approx(expected)  # 6.3.21
    assert cap == pytest.approx(0.25 * ds.fcd(fc, shear=True) * t * h0)  # 6.3.20


# ───────────────────────────── the seismic grade in the design ─────────────────────────────


def test_grade_factors_and_gamma_re_on_the_forces(cn):
    from saengine.design import seismic_grades as sg
    from saengine.fem.two_level_seismic import seismic_grade

    grade = seismic_grade("rcFrame", 20.0, 4, "II")  # frame-2
    token = sg._GRADE.set(grade)
    try:
        eta, gamma = sg._vectors("column", False)
        # GB 50011 6.2.2 / 6.2.5: ηc 1.5, ηvc 1.3 (× ηc); Table 5.4.2 γRE 0.80 / 0.85.
        assert eta[4] == pytest.approx(1.5) and eta[1] == pytest.approx(1.5 * 1.3)
        assert gamma[0] == pytest.approx(0.8) and gamma[1] == pytest.approx(0.85)
        beam_eta, beam_gamma = sg._vectors("beam", False)
        assert beam_eta[2] == pytest.approx(1.2) and beam_gamma[5] == pytest.approx(0.75)
        steel_eta, steel_gamma = sg._vectors("column", True)
        assert np.allclose(steel_eta, 1.0) and np.allclose(steel_gamma, 0.8)
        forces = np.array([[100.0, 10.0, 0.0, 0.0, 50.0, 20.0]])
        sway = np.array([[20.0, 6.0, 0.0, 0.0, 30.0, 10.0]])
        piece = SimpleNamespace(
            forces=[forces, forces], sway=[sway, sway], sustained=None, live=None, roof=None
        )
        sg._scale(piece, [1], eta, gamma)
        assert np.allclose(piece.forces[0], forces)  # not an earthquake combination
        assert np.allclose(piece.forces[1], (forces + (eta - 1) * sway) * gamma)
        assert np.allclose(piece.sway[1], eta * sway * gamma)
        assert sg.factor("anchorage") == pytest.approx(1.15)  # GB 50010 11.1.7
        assert sg.detailing().beamEndDepth == pytest.approx(0.35)  # 6.3.3, grade 二
    finally:
        sg._GRADE.reset(token)


def test_wall_forces_by_grade(cn):
    from saengine.design import seismic_grades as sg
    from saengine.design.walls import PierForces
    from saengine.fem.two_level_seismic import seismic_grade

    token = sg._GRADE.set(seismic_grade("rcWall", 60.0, 4, "II"))  # dual-2, ηvw 1.4
    try:
        quake = PierForces("E", 1000.0, 100.0, 5000.0, 10.0, 0.0, True)
        plain = PierForces("G", 1000.0, 100.0, 5000.0, 10.0, 0.0, False)
        out, note = sg.wall_forces([quake, plain])
        assert out[0].V2 == pytest.approx(100.0 * 1.4 * 0.85)  # 6.2.8, Table 5.4.2
        assert out[0].P == pytest.approx(1000.0 * 0.85)
        assert out[1] == plain and note
    finally:
        sg._GRADE.reset(token)


def test_default_pack_has_no_grade_design():
    from saengine.design import seismic_grades as sg

    with code_context.using(registry.load("bnbc2020")):
        assert sg.rule() is None
        assert sg.apply({}, ["c"], {"factors": [{"EX": 1.0}]}, [], {}, {}) == []
        forces = [SimpleNamespace(earthquake=True, V2=1.0)]
        assert sg.wall_forces(forces) == (forces, None)


# ───────────────────────────── vertical earthquake, δn ─────────────────────────────


def test_top_force_delta_n(cn):
    from saengine.fem import loads as fl

    top = cn.table("seismic").lateralForce.topForce
    tc = cn.table("seismic").siteClasses["II"].TC
    v = 1000.0
    # Table 5.2.1: T1 > 1.4 Tg: δn = 0.08 T1 + 0.07 / 0.01 / -0.02 by Tg.
    offset = 0.07 if tc <= 0.35 else 0.01 if tc <= 0.55 else -0.02
    assert fl.top_force(top, 1.5, v, "II") == pytest.approx((0.08 * 1.5 + offset) * v)
    assert fl.top_force(top, 1.3 * tc, v, "II") is None  # T1 <= 1.4 Tg
    levels = [(3.0, 100.0), (6.0, 100.0), (9.0, 100.0)]
    forces = fl.vertical_distribution(levels, v, 1.5, "II")
    assert sum(forces) == pytest.approx(v)
    assert forces[-1] > v * 3 / 6  # the top takes Gi Hi share plus ΔFn


def test_vertical_earthquake_by_gravity_share(cn, monkeypatch):
    import saengine.library.settings as library_settings
    from saengine.fem.seismic_design import _gravity_share_terms

    rule = cn.table("seismic").verticalComponent
    settings = SimpleNamespace()
    monkeypatch.setattr(library_settings, "derived", lambda _s: {"zone": 4})
    found = _gravity_share_terms(settings, rule)
    # GB 50011 5.3.3: 10 % of the gravity load at 8 (0.20g), γEv 0.5.
    assert found["applies"] and found["coefficient"] == pytest.approx(0.5 * 0.10)
    monkeypatch.setattr(library_settings, "derived", lambda _s: {"zone": 2})
    assert not _gravity_share_terms(settings, rule)["applies"]


# ───────────────────────────── steel ─────────────────────────────


def test_gb50017_bolts_and_welds(cn):
    from saengine.design.steel import limit_state as ls

    # Table 4.4.6: 8.8 (bearing type) fv 250 MPa on the shank; ft 400 on An.
    assert ls.bolt_shear("8.8", 20.0, 1) == pytest.approx(250.0 * math.pi * 20.0**2 / 4)
    tdb, _note = ls.bolt_tension("8.8", 20.0)
    assert tdb == pytest.approx(400.0 * 0.78 * math.pi * 20.0**2 / 4)
    # 11.4.1: Nc = d t fc, fc = 0.82 fu.
    assert ls.bearing(20.0, 10.0, 470.0, math.inf, 22.0, None) == pytest.approx(
        0.82 * 20 * 10 * 470
    )
    # Table 4.4.5: E50 ffw 200 on 0.7 hf.
    assert ls.fillet_per_mm(6.0, 490.0) == pytest.approx(0.7 * 6.0 * 200.0)
    assert ls.fillet_per_mm(6.0, 420.0) == pytest.approx(0.7 * 6.0 * 160.0)


def test_steel_seismic_rules_by_grade(cn):
    from saengine.design import seismic_grades as sg
    from saengine.design.steel import limit_state as ls
    from saengine.fem.two_level_seismic import seismic_grade
    from saengine.library.settings import default_project_settings

    settings = default_project_settings("Project", code_pack=CN)
    settings = settings.model_copy(
        update={"seismic": settings.seismic.model_copy(update={"system": "steelFrame"})}
    )
    token = sg._GRADE.set(seismic_grade("steelFrame", 60.0, 4, "II"))  # > 50 m, 8: steel-2
    try:
        frames = ls.seismic_frames(settings)
        assert list(frames) == ["grade-2"]
        assert ls.seismic_rules().frames["grade-2"].strongColumn == pytest.approx(1.1)
    finally:
        sg._GRADE.reset(token)


# ───────────────────────────── foundations ─────────────────────────────


def test_gb50007_width_depth_correction(cn):
    from saengine.soil import characteristic_bearing as cb

    # 5.2.4: fa = fak + ηb γ (b - 3) + ηd γm (d - 0.5), clay 0.3 / 1.6, γ 18.
    fa, _note = cb.corrected(150.0, 4.0, 2.0)
    assert fa == pytest.approx(150.0 + 0.3 * 18 * 1.0 + 1.6 * 18 * 1.5)
    assert cb.corrected(150.0, 2.0, 0.3)[0] == pytest.approx(150.0)  # b < 3, d < 0.5
    assert cb.corrected(150.0, 8.0, 0.5)[0] == pytest.approx(150.0 + 0.3 * 18 * 3.0)  # b <= 6


def test_gb50007_layerwise_coefficients(cn):
    from saengine.soil import characteristic_bearing as cb

    # Boussinesq corner of a square at z = 2 × its side: σz/p 0.0840 (Appendix K, l/b 1, z/b 2).
    assert cb.corner_coefficient(1.0, 1.0, 2.0) == pytest.approx(0.0840, abs=5e-4)
    assert cb.corner_coefficient(1.0, 1.0, 0.0) == pytest.approx(0.25)
    assert cb.mean_coefficient(2.0, 2.0, 1e-6) == pytest.approx(1.0, abs=1e-3)
    # Table 5.3.5: ψs 1.3 at Ēs 4.0, 1.0 at 7.0 (p0 >= fak), linear between.
    assert cb._psi(cb.settlement_rule(), 5.5) == pytest.approx(1.15)


def test_default_pack_keeps_its_foundations():
    from saengine.soil import characteristic_bearing as cb

    with code_context.using(registry.load("bnbc2020")):
        assert cb.correction_rule() is None and cb.settlement_rule() is None
        assert cb.corrected(150.0, 4.0, 2.0) is None
