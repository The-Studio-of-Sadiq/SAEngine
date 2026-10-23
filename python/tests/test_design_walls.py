"""RC wall and coupling beam design (BNBC 2020 Part 6 Sec 6.6, 6.4.8, 8.3.6), checked against
hand calculations on synthetic walls. Units: mm, MPa, N, N·mm."""

from __future__ import annotations

import math

import pytest

from saengine.design import walls as W
from saengine.design.rc import InteractionSurface, bar_area
from saengine.library.objects import BarMesh, WallReinforcement

FC, FY = 28.0, 420.0
ROOT = math.sqrt(FC)


def _forces(*rows: tuple[float, float, float], m2: float = 0.0) -> list[W.PierForces]:
    """(P kN, V2 kN, M3 kN·m) rows."""
    return W.pier_forces(
        [
            {"combination": f"C{k}", "P": p, "V2": v, "M3": m, "M2": m2}
            for k, (p, v, m) in enumerate(rows, 1)
        ],
        1e3,
        1e6,
    )


def _row(design: W.WallDesign, start: str) -> dict:
    found = [c for c in design.checks if c["name"].startswith(start)]
    assert found, [c["name"] for c in design.checks]
    return found[0]


# ─────────────────────────────── minimum steel, αc, Vn ───────────────────────────────


def test_minimum_ratios_by_bar_and_grade():
    # 6.6.3.2 / 6.6.3.3: bars <= 16 mm with fy >= 420 MPa: 0.0012 / 0.0020, others 0.0015 /
    # 0.0025.
    assert W.minimum_ratios(12, 10, 420) == (0.0012, 0.0020)
    assert W.minimum_ratios(16, 16, 500) == (0.0012, 0.0020)
    assert W.minimum_ratios(20, 12, 420) == (0.0015, 0.0020)
    assert W.minimum_ratios(12, 20, 420) == (0.0012, 0.0025)
    assert W.minimum_ratios(12, 12, 400) == (0.0015, 0.0025)


@pytest.mark.parametrize(
    ("aspect", "alpha"), [(1.0, 0.25), (1.5, 0.25), (1.75, 0.21), (2.0, 0.17), (3.0, 0.17)]
)
def test_alpha_c(aspect, alpha):
    assert W.alpha_c(aspect) == pytest.approx(alpha)


def test_special_vn_squat_and_slender():
    # Acv = 4000 x 250 = 1e6 mm², f'c = 30, ρt = 0.0025, fy = 420.
    # Squat, hw/lw = 1: Vn = 1e6 (0.25 √30 + 0.0025 x 420) = 1e6 (1.369306 + 1.05) = 2419.31 kN.
    # Slender, hw/lw = 3: 1e6 (0.17 √30 + 1.05) = 1e6 (0.931128 + 1.05) = 1981.13 kN.
    # Limit 0.83 Acw √f'c = 0.83 x 1e6 x 5.477226 = 4546.1 kN.
    squat = W.WallGeometry(4000, 250, 4000, 3000)
    slender = W.WallGeometry(4000, 250, 12000, 3000)
    a = W.special_vn(squat, 0.0025, 30.0, 420.0)
    b = W.special_vn(slender, 0.0025, 30.0, 420.0)
    assert a["alpha"] == 0.25 and b["alpha"] == 0.17
    assert a["vn"] == pytest.approx(2419.306e3, rel=1e-5)
    assert b["vn"] == pytest.approx(1981.128e3, rel=1e-5)
    assert a["vmax"] == pytest.approx(4546.098e3, rel=1e-5)
    # The segment's larger hw/lw governs (8.3.6.4(b)).
    seg = W.WallGeometry(4000, 250, 4000, 3000, segment_ratio=2.5)
    assert W.special_vn(seg, 0.0025, 30.0, 420.0)["alpha"] == 0.17


def test_ordinary_wall_shear_detailed_vc():
    # lw = 3000, h = 200, d = 0.8 lw = 2400; Nu = 1000 kN, Vu = 500 kN, Mu = 1500 kN·m.
    # Simplified: 0.17 √28 x 200 x 2400 = 431.785 kN.
    # Eq. 6.6.68: 0.27 √28 x 200 x 2400 + 1e6 x 2400 / (4 x 3000) = 685.778 + 200 = 885.778 kN.
    # Eq. 6.6.69: Mu/Vu - lw/2 = 3000 - 1500 = 1500; [0.05 √28 + 3000 (0.1 √28 + 0.2 x 1e6 /
    # (3000 x 200)) / 1500] x 200 x 2400 = (0.264575 + 1.724967) x 480000 = 954.980 kN.
    # Vc = min(885.778, 954.980) = 885.778 kN (above the simplified value).
    # Vs = 2 x 78.54 x 420 x 2400 / 200 = 791.681 kN; Vn = 1677.459 kN <= 0.83 √28 h d = 2108.1.
    g = W.WallGeometry(3000, 200, 9000, 3000)
    f = _forces((1000, 500, 1500))[0]
    vc, how = W.wall_vc(g, f, FC)
    assert vc == pytest.approx(885.778e3, rel=1e-5)
    assert "6.6.68" in how
    bars = W.WallBars(25, 12, 200, 10, 200, 2)
    vn = W.wall_vn(g, bars, f, FC, FY)
    assert vn["vs"] == pytest.approx(791.681e3, rel=1e-5)
    assert vn["vn"] == pytest.approx(1677.459e3, rel=1e-5)
    assert vn["vmax"] == pytest.approx(2108.137e3, rel=1e-5)
    # In tension (Nu = -300 kN): Eq. 6.6.54 0.17 (1 + 0.29 x (-3e5) / 6e5) √28 x 200 x 2400
    # = 0.855 x 431.785 = 369.176 kN; Eq. 6.6.68 = 685.778 - 60 = 625.778, Eq. 6.6.69: (0.264575
    # + 3000 (0.529150 - 0.1) / 1500) x 480000 = 538.980 kN: detailed 538.980 kN governs.
    t = _forces((-300, 500, 1500))[0]
    assert W.wall_vc(g, t, FC)[0] == pytest.approx(538.980e3, rel=1e-5)
    # Eq. 6.6.69 does not apply when Mu/Vu - lw/2 <= 0: Eq. 6.6.68 only.
    low = _forces((1000, 500, 500))[0]
    assert W.wall_vc(g, low, FC)[0] == pytest.approx(885.778e3, rel=1e-5)


def test_shear_row_and_utilisation():
    g = W.WallGeometry(3000, 200, 9000, 3000)
    bars = W.WallBars(25, 12, 200, 10, 200, 2)
    d = W.wall_checks(g, bars, _forces((1000, 500, 1500)), FC, FY)
    row = _row(d, "In-plane shear (6.4.8)")
    assert row["capacity"] == pytest.approx(0.75 * 1677.459, abs=0.01)
    assert row["utilisation"] == pytest.approx(500 / (0.75 * 1677.459), abs=1e-3)


# ─────────────────────────────── layers, spacing, curtains ───────────────────────────────


def test_two_layers_above_250_mm_and_spacing():
    g = W.WallGeometry(3000, 300, 9000, 3000)
    one = W.WallBars(25, 16, 300, 12, 300, 1)
    d = W.wall_checks(g, one, _forces((500, 50, 100)), FC, FY)
    assert not _row(d, "Two layers")["ok"]
    # min(3 t, 450): 900 -> 450 mm.
    wide = W.WallBars(25, 16, 475, 12, 300, 2)
    d = W.wall_checks(g, wide, _forces((500, 50, 100)), FC, FY)
    assert not _row(d, "Vertical bar spacing")["ok"]
    assert _row(d, "Vertical bar spacing")["capacity"] == 450
    # Basement walls are exempt from the two layers (6.6.3.4).
    base = W.WallGeometry(3000, 300, 9000, 3000, basement=True)
    d = W.wall_checks(base, one, _forces((500, 50, 100)), FC, FY)
    assert not [c for c in d.checks if c["name"].startswith("Two layers")]


def test_shear_reinforcement_rules_when_vu_above_half_phi_vc():
    # lw = 3000, h = 200, P = 1000 kN: φVc = 0.75 x 885.778 = 664.3 kN; Vu = 400 kN > 0.5 φVc:
    # ρt >= 0.0025 (6.4.8.9.2), s <= min(lw/5, 3h, 450) = 450 (6.4.8.9.3).
    g = W.WallGeometry(3000, 200, 9000, 3000)
    light = W.WallBars(25, 10, 300, 10, 300, 2)  # ρ = 2 x 78.54 / (200 x 300) = 0.00262
    d = W.wall_checks(g, light, _forces((1000, 400, 1500)), FC, FY)
    assert "6.4.8.9" in _row(d, "Horizontal web ratio")["name"]
    assert _row(d, "Horizontal web ratio")["demand"] == pytest.approx(0.25)
    # Vu = 150 kN, Mu/Vu = 10 m: Eq. 6.6.69 (0.264575 + 3000 x 0.862484 / 8500) x 480000 =
    # 273.11 kN < 0.17 √f'c h d = 431.785 kN, which governs: 0.5 φVc = 161.9 kN > 150 kN.
    d2 = W.wall_checks(g, light, _forces((1000, 150, 1500)), FC, FY)
    assert "6.6.3.2" in _row(d2, "Horizontal web ratio")["name"]
    assert _row(d2, "Horizontal web ratio")["demand"] == pytest.approx(0.20)


def test_special_minimum_steel_and_two_curtains():
    # Acv = 4000 x 250 = 1e6, √28 = 5.291503: 0.083 Acv √f'c = 439.19 kN, 0.17 Acv √f'c =
    # 899.56 kN.
    g = W.WallGeometry(4000, 250, 12000, 3000)
    one = W.WallBars(25, 12, 200, 10, 200, 1)  # ρ = 113.1 / (250 x 200) = 0.00226
    low = W.wall_checks(g, one, _forces((2000, 400, 2000)), FC, FY, special=True, drift=0.007)
    # Vu <= 0.083 Acv √f'c: the 6.6.3 values (bars <= 16 mm, fy 420: 0.0012 / 0.0020).
    assert _row(low, "Vertical web ratio")["demand"] == pytest.approx(0.12)
    assert _row(low, "Horizontal web ratio")["demand"] == pytest.approx(0.20)
    assert _row(low, "Two curtains")["ok"]
    mid = W.wall_checks(g, one, _forces((2000, 800, 2000)), FC, FY, special=True, drift=0.007)
    assert _row(mid, "Vertical web ratio")["demand"] == pytest.approx(0.25)
    assert not _row(mid, "Vertical web ratio")["ok"]
    assert _row(mid, "Two curtains")["ok"]  # 800 <= 899.56 kN
    high = W.wall_checks(g, one, _forces((2000, 950, 2000)), FC, FY, special=True, drift=0.007)
    assert not _row(high, "Two curtains")["ok"]
    # ρl >= ρt where hw/lw <= 2 (8.3.6.4(c)).
    squat = W.WallGeometry(4000, 250, 6000, 3000)
    bars = W.WallBars(25, 10, 300, 12, 150, 2)
    d = W.wall_checks(squat, bars, _forces((2000, 800, 2000)), FC, FY, special=True, drift=0.007)
    assert not _row(d, "ρl >= ρt")["ok"]


# ─────────────────────────────── axial force and flexure ───────────────────────────────


def _hand_section() -> tuple[W.WallGeometry, W.WallBars]:
    # lw = 1000, t = 200, cover 25, Ø10 horizontal, Ø12 vertical @ 200 in two layers: the end
    # bars at 500 - 25 - 10 - 6 = 459 mm, 918 mm over ceil(918/200) = 5 pitches of 183.6 mm:
    # y = ±459, ±275.4, ±91.8, a pair (2 x 113.097 = 226.195 mm²) at each.
    return W.WallGeometry(1000, 200, 3000, 3000), W.WallBars(25, 12, 200, 10, 200, 2)


def test_section_layout():
    g, b = _hand_section()
    s = W.pier_section(g, b, FC, FY)
    ys = sorted({round(bar.y, 1) for bar in s.bars})
    assert ys == [-459.0, -275.4, -91.8, 91.8, 275.4, 459.0]
    assert {round(bar.x) for bar in s.bars} == {-59, 59}
    assert s.profile.xDim == 200 and s.profile.yDim == 1000


def test_pm_point_by_hand():
    # c = 300 mm, f'c = 28 (β1 = 0.85, a = 255), fy = 420, Es = 200 000 (εy = 0.0021).
    # Depths of the bar pairs from the compression fibre: 41, 224.6, 408.2, 591.8, 775.4, 959.
    # ε = 0.003 (300 - d) / 300: 0.00259 (yields, 420), 0.000754 (150.8), -0.001082 (-216.4),
    # -0.002918, -0.004754, -0.006590 (all -420); the two in the block less 0.85 f'c = 23.8.
    # Concrete 0.85 x 28 x 200 x 255 = 1 213 800 N at 127.5 mm from the fibre.
    depth = [41.0, 224.6, 408.2, 591.8, 775.4, 959.0]
    area = 2 * bar_area(12)
    pn, mn = 0.85 * FC * 200 * 255, 0.85 * FC * 200 * 255 * (500 - 127.5)
    for d in depth:
        stress = max(-FY, min(FY, 200_000 * 0.003 * (300 - d) / 300))
        if d < 255:
            stress -= 0.85 * FC
        pn += stress * area
        mn += stress * area * (500 - d)
    assert pn == pytest.approx(998.19e3, rel=1e-4)  # 998.19 kN
    assert mn == pytest.approx(575.18e6, rel=1e-4)  # 575.18 kN·m
    g, b = _hand_section()
    pier = W.PierInteraction(W.pier_section(g, b, FC, FY))
    p, m, eps = pier.actions("M3", 1, 300.0)
    assert float(p[0]) == pytest.approx(pn, rel=1e-6)
    assert float(m[0]) == pytest.approx(mn, rel=1e-6)
    assert float(eps[0]) == pytest.approx(0.003 * (959 - 300) / 300, rel=1e-6)
    # The neutral axis at Pn = 998.19 kN is back at c = 300 (Mn 575.18 kN·m).
    mn2, c = pier.nominal(pn, "M3", 1)
    assert c == pytest.approx(300.0, rel=1e-5)
    assert mn2 == pytest.approx(mn, rel=1e-5)
    # φ: εt = 0.00659 >= εty + 0.003: 0.90; φMn at φPn = 0.9 x 998.19 kN is 0.9 x 575.18.
    assert pier.capacity(0.9 * pn, "M3", 1) == pytest.approx(0.9 * mn, rel=2e-3)


def test_pier_interaction_matches_concreteproperties():
    """The rectangle's strain compatibility agrees with rc.py's concreteproperties analysis of
    the same section (nominal Mn and c at Pn = Pu, both axes), and its φ-factored diagram
    with rc.InteractionSurface (which interpolates between meridians, inside the contour)."""
    g, b = _hand_section()
    s = W.pier_section(g, b, FC, FY)
    pier = W.PierInteraction(s)
    for pu in (-200e3, 0.0, 500e3, 1500e3, 2500e3):
        for axis, theta, comp in (("M3", 0.0, "m_x"), ("M2", math.pi / 2, "m_y")):
            r = s.analysis.ultimate_bending_capacity(theta=theta, n=pu)
            mn, c = pier.nominal(pu, axis)
            assert mn == pytest.approx(abs(getattr(r, comp)), rel=1e-4), (pu, axis)
            assert c == pytest.approx(r.d_n, rel=1e-4), (pu, axis)
    # The coarse surface (meridians 15 degrees apart, chords between them) lies up to 3 % inside.
    surface = InteractionSurface(s, coarse=True)
    for pu in (0.0, 1500e3):
        assert pier.capacity(pu, "M3") == pytest.approx(surface.moment_capacity(pu, 0.0), rel=0.03)
    assert s.phi_pn_max == pytest.approx(0.8 * 0.65 * s.p0)


def test_biaxial_linear_contour_is_conservative():
    g, b = _hand_section()
    s = W.pier_section(g, b, FC, FY)
    pier = W.PierInteraction(s)
    m3, m2 = pier.capacity(800e3, "M3") * 0.6, pier.capacity(800e3, "M2") * 0.3
    r = pier.check(800e3, m3, m2)
    assert r.utilisation == pytest.approx(0.9, rel=1e-6)
    exact = InteractionSurface(s, coarse=True).check(800e3, m3, m2)
    assert exact.utilisation <= r.utilisation


# ─────────────────────────────── boundary elements ───────────────────────────────


def test_displacement_trigger_and_length():
    # Eq. 6.8.10: lw / (600 δu/hw), δu/hw >= 0.007.
    assert W.displacement_trigger(3000, 0.01) == pytest.approx(500.0)
    assert W.displacement_trigger(3000, 0.005) == pytest.approx(3000 / 4.2)
    # 8.3.6.6(d)(i): max(c - 0.1 lw, c/2).
    assert W.boundary_length(300, 1000) == pytest.approx(200)
    assert W.boundary_length(300, 3000) == pytest.approx(150)


def test_boundary_by_displacement():
    # The hand section at Pu = 998.19 kN has c = 300 mm; lw = 1000: trigger 1000 / (600 x
    # 0.007) = 238 mm (required); with δu/hw = 0.006 -> 0.007 as well; at δu/hw = 0.005 ...
    # still 0.007. A trigger above c: δu/hw = 0.005 is floored, so use a longer wall below.
    g, b = _hand_section()
    s = W.pier_section(g, b, FC, FY)
    f = W.pier_forces([{"P": 998.19, "V2": 100, "M3": 300}], 1e3, 1e6)
    need = W.boundary_need(g, s, f, FC, FY, b, drift=0.007)
    assert need.method == "displacement"
    assert need.c == pytest.approx(300.0, abs=0.5)
    assert need.required
    assert need.length == 200.0  # max(300 - 100, 150) = 200, a multiple of 50
    # Height above the critical section >= max(lw, Mu / 4Vu) = max(1000, 300e6 / 4e5 = 750).
    assert need.height == pytest.approx(1000.0)
    # At Pu = 0 the neutral axis is shallow: c < 238 mm, not required.
    f0 = W.pier_forces([{"P": 0, "V2": 100, "M3": 300}], 1e3, 1e6)
    assert not W.boundary_need(g, s, f0, FC, FY, b, drift=0.007).required


def test_boundary_by_stress():
    # lw = 3000, t = 200: Pu/Ag + Mu (lw/2)/I = 1.5e6/6e5 + 3e9 x 1500 / (200 x 3000³/12)
    # = 2.5 + 10.0 = 12.5 MPa > 0.2 x 28 = 5.6 MPa: required.
    g = W.WallGeometry(3000, 200, 15000, 3000, continuous=False)
    assert W.extreme_stress(g, 1.5e6, 3e9) == pytest.approx(12.5)
    b = W.WallBars(25, 12, 200, 10, 200, 2)
    s = W.pier_section(g, b, FC, FY)
    f = W.pier_forces([{"P": 1500, "V2": 600, "M3": 3000}], 1e3, 1e6)
    need = W.boundary_need(g, s, f, FC, FY, b, drift=0.01)
    assert need.method == "stress"  # not continuous: 8.3.6.6(c)
    assert need.required and need.stress == pytest.approx(12.5)
    small = W.pier_forces([{"P": 1500, "V2": 100, "M3": 500}], 1e3, 1e6)
    # 2.5 + 500e6 x 1500 / 4.5e11 = 4.17 MPa <= 5.6.
    assert not W.boundary_need(g, s, small, FC, FY, b).required


def test_boundary_hoops_and_rows():
    # BE 300 x 200, cover 25: bc = 275 along the length, 150 across; Ash/s = 0.09 bc f'c/fyt
    # = 1.65 and 0.90 mm²/mm (Eq. 6.8.8). Ø10 hoops, 2 legs each way (hx = 275 <= 350): s from
    # Ash 157.08/1.65 = 95.2 mm; limits min(200/3, 6 x 12, so = 100 + 75/3 = 125) = 66.7 -> 50.
    p = W.propose_boundary(300, 200, 25, FC, FY, 12.0)
    assert (p.hoop_dia, p.hoop_spacing, p.legs_across, p.legs_along) == (10.0, 50.0, 2, 2)
    g = W.WallGeometry(3000, 200, 15000, 3000)
    # c is about 612 mm at Pu = 1500 kN: length >= c - 0.1 lw = 312 mm; 350 provided.
    be = W.Boundary(350, 6, 20, 10, 50, 2, 2)
    b = W.WallBars(25, 12, 200, 10, 200, 2, be)
    d = W.wall_checks(
        g, b, _forces((1500, 600, 3000), (400, -600, -3000)), FC, FY, special=True, drift=0.01
    )
    assert _row(d, "Boundary element length")["ok"]
    ash = _row(d, "Boundary Ash, bc along the length")
    # c with the boundary bars (612 mm): max(c - 0.1 lw, c/2) = c - 300.
    section = W.pier_section(g, b, FC, FY)
    c = W.PierInteraction(section).nominal(1500e3, "M3")[1]
    assert _row(d, "Boundary element length")["demand"] == pytest.approx(c - 300, abs=0.01)
    assert ash["demand"] == pytest.approx(0.09 * 325 * 28 / 420 * 50, abs=0.01)
    assert ash["capacity"] == pytest.approx(2 * bar_area(10), abs=0.01)
    # Without a boundary element in the type: the row fails.
    plain = W.WallBars(25, 12, 200, 10, 200, 2)
    d = W.wall_checks(g, plain, _forces((1500, 600, 3000)), FC, FY, special=True, drift=0.01)
    assert not _row(d, "Boundary element provided")["ok"]


def test_end_ties_when_rho_at_boundary_high():
    # No boundary element required, boundary ρ = 2 x 314.16 / (200 x 150) = 0.0209 > 2.8/420.
    # Stress method: 200e3 / 6e5 + 200e6 x 1500 / 4.5e11 = 1.0 MPa <= 5.6 MPa.
    g = W.WallGeometry(3000, 200, 15000, 3000, continuous=False)
    b = W.WallBars(25, 20, 150, 10, 200, 2)
    s = W.pier_section(g, b, FC, FY)
    f = W.pier_forces([{"P": 200, "V2": 100, "M3": 200}], 1e3, 1e6)
    need = W.boundary_need(g, s, f, FC, FY, b)
    assert not need.required and need.ties and need.ties_spacing == 200.0


# ─────────────────────────────── coupling beams ───────────────────────────────


def test_coupling_beam_diagonal():
    # ln = 1000, h = 600, bw = 300: Acw = 180 000, 0.33 Acw √28 = 314.32 kN; ln/h = 1.67 < 2,
    # Vu = 500 kN > 314.32: diagonals required. 4 Ø25 per group (1963.5 mm²), α = atan(400 /
    # 1000) = 21.80°, sin α = 0.371391: Vn = 2 x 1963.5 x 420 x 0.371391 = 612.56 kN <= 0.83
    # Acw √28 = 790.56 kN; φ = 0.85: 520.68 kN.
    alpha = math.atan(400 / 1000)
    cb = W.coupling_beam_checks(
        1000, 600, 300, 500e3, FC, FY, diagonal=W.Diagonal(4, 25, angle=alpha)
    )
    assert cb.mode == "diagonal"
    row = cb.checks[0]
    assert row["capacity"] == pytest.approx(0.85 * 612.56, abs=0.05)
    assert row["ok"]
    # Avd required = Vu / (φ 2 fy sin α) = 500e3 / (0.85 x 2 x 420 x 0.371391) = 1885.6 mm².
    assert cb.avd_required == pytest.approx(1885.6, rel=1e-4)
    assert cb.proposal is not None and cb.proposal.area() >= cb.avd_required
    assert W.coupling_beam_checks(3000, 600, 300, 500e3, FC, FY).mode == "flexural"
    assert W.coupling_beam_checks(1800, 600, 300, 500e3, FC, FY).mode == "either"
    assert W.coupling_beam_checks(1000, 600, 300, 200e3, FC, FY).mode == "either"


# ─────────────────────────────── inputs and design mode ───────────────────────────────


def test_inputs():
    reinf = WallReinforcement(
        material="rebar",
        cover=25,
        vertical=BarMesh(dia=12, spacing=200),
        horizontal=BarMesh(dia=10, spacing=250),
        layers=2,
    )
    b = W.wall_bars(reinf)
    assert b is not None and b.rho_l(200) == pytest.approx(2 * bar_area(12) / (200 * 200))
    assert b.boundary is None
    dict_bars = W.wall_bars(
        {
            "cover": 25,
            "vertical": {"dia": 12, "spacing": 200},
            "horizontal": {"dia": 10, "spacing": 200},
            "boundary": {
                "length": 400,
                "count": 8,
                "dia": 20,
                "hoop": {"dia": 10, "spacing": 75, "legsAcross": 3},
            },
        }
    )
    assert dict_bars is not None and dict_bars.boundary == W.Boundary(400, 8, 20, 10, 75, 3, 2)
    assert W.wall_bars({"cover": 25, "vertical": None, "horizontal": None}) is None
    # Tension-positive rows and units.
    f = W.pier_forces([{"P": 100, "V2": 1, "M3": 2}], 1e3, 1e6, tension_positive=True)[0]
    assert (f.P, f.V2, f.M3) == (-100e3, 1e3, 2e6)
    pier = {
        "pier": "W1 P1",
        "lw": 3000,
        "tw": 200,
        "bottom": 0,
        "top": 3200,
        "cuts": {
            "bottom": {"1.2D+1.0EX": {"P": 900, "V2": 200, "V3": 1, "T": 0, "M2": 2, "M3": 800}}
        },
    }
    rows = W.pier_rows(pier, earthquake=["other"])
    assert rows[0].P == 900e3 and rows[0].M3 == 800e6 and not rows[0].earthquake
    assert rows[0].where == "W1 P1 bottom"
    g = W.geometry_of(pier, 12800)
    assert (g.length, g.thickness, g.height, g.clear_height) == (3000, 200, 12800, 3200)
    scope = {"applies": {"8.3.6": {"applies": True}}}
    assert W.special_applies(scope) and not W.special_applies(scope, structural=False)
    assert not W.special_applies({"applies": {"8.3.6": {"applies": False}}})


def test_empirical_capacity():
    # φPn = 0.55 x 0.65 x 28 x 600 000 x [1 - (0.8 x 3000 / (32 x 200))²] = 6006 kN x 0.859375
    # = 5161.41 kN.
    g = W.WallGeometry(3000, 200, 9000, 3000)
    assert W.empirical_capacity(g, FC) == pytest.approx(5161.41e3, rel=1e-6)
    unbraced = W.WallGeometry(3000, 200, 9000, 3000, braced=False)
    assert W.empirical_capacity(unbraced, FC) == pytest.approx(
        0.55 * 0.65 * 28 * 6e5 * (1 - (2 * 3000 / 6400) ** 2)
    )


def test_wall_need_meshes_and_end_bars():
    # An ordinary 200 mm wall with little shear: one layer, the 6.6.3 minimums: Ø10 at
    # 1000 x 78.54 / (0.0012 x 200 x 1000) = 327 -> min(3t = 600, 450) cap: 325 mm vertical.
    g = W.WallGeometry(3000, 200, 9000, 3000)
    n = W.wall_need(g, _forces((500, 50, 100)), FC, FY)
    assert n.layers == 1
    assert n.vertical == W.Mesh(10.0, 325.0)
    assert n.rho_l >= 0.0012 and n.rho_t >= 0.0020
    # A special wall with high moment: end bars and a boundary element are proposed and pass.
    forces = _forces((1500, 600, 3500), (400, -600, -3500))
    n = W.wall_need(g, forces, FC, FY, special=True, drift=0.01, search=True)
    assert n.layers == 2 and n.end_bars is not None
    bars = W.WallBars(
        25,
        n.vertical.dia,
        n.vertical.spacing,
        n.horizontal.dia,
        n.horizontal.spacing,
        2,
        n.end_bars,
    )
    d = W.wall_checks(g, bars, forces, FC, FY, special=True, drift=0.01)
    assert _row(d, "Axial force and bending")["ok"]
    assert all(c["ok"] for c in d.checks if not c["flag"]), [
        (c["name"], c["utilisation"]) for c in d.checks if not c["ok"]
    ]


# ─────────────────────────────── review regressions ───────────────────────────────


def test_special_shear_phi_is_the_walls_over_all_combinations():
    # lw 4000, t 250, hw 12000 (αc 0.17), Ø10 @ 200 in two layers: ρt = 2 x 78.54 / (250 x 200)
    # = 0.0031416; Vn = 1e6 (0.17 √28 + 0.0031416 x 420) = 1e6 (0.899556 + 1.319469) = 2219.03 kN.
    # B (Vu 1480, Mu 3000) has Vu Mn/Mu far above Vn: φ = 0.60 for the wall (6.2.3.3(a)), also
    # when A (more shear, Mu 30000: Vu Mn/Mu below Vn) is added. Governing Vu = 1500 kN:
    # 1500 / (0.60 x 2219.03) = 1.1266.
    g = W.WallGeometry(4000, 250, 12000, 3000)
    b = W.WallBars(25, 12, 200, 10, 200, 2)
    vn = 1e6 * (0.17 * ROOT + 2 * bar_area(10) / (250 * 200) * 420)
    assert vn == pytest.approx(2219.03e3, rel=1e-5)
    one = W.wall_checks(g, b, _forces((1000, 1480, 3000)), FC, FY, special=True, drift=0.007)
    both = W.wall_checks(
        g, b, _forces((1000, 1500, 30000), (1000, 1480, 3000)), FC, FY, special=True, drift=0.007
    )
    r1, r2 = _row(one, "In-plane shear"), _row(both, "In-plane shear")
    assert r1["utilisation"] == pytest.approx(1480e3 / (0.60 * vn), abs=1e-3)
    assert r2["utilisation"] == pytest.approx(1500e3 / (0.60 * vn), abs=1e-3)
    assert not r1["ok"] and not r2["ok"]
    assert r2["utilisation"] >= r1["utilisation"]


def test_end_tie_spacing_is_checked():
    # As above (no boundary element: 1.0 MPa <= 5.6 MPa), end bars 6 Ø20 over 300 mm: ρ = 6 x
    # 314.16 / (200 x 300) = 0.0314 > 2.8/420 = 0.00667: ties at <= 200 mm (8.3.6.6(e)(i)).
    g = W.WallGeometry(3000, 200, 15000, 3000, continuous=False)
    f = _forces((200, 100, 200))
    for spacing, ok in ((300.0, False), (200.0, True)):
        b = W.WallBars(25, 12, 200, 10, 200, 2, W.Boundary(300, 6, 20, 10, spacing))
        d = W.wall_checks(g, b, f, FC, FY, special=True)
        row = _row(d, "End tie spacing")
        assert not row["flag"] and row["ok"] is ok
        assert (row["demand"], row["capacity"]) == (spacing, 200.0)
    # No end bars or ties in the type where the web ratio is above 2.8/fy: fails.
    web = W.WallBars(25, 20, 150, 10, 200, 2)
    assert not _row(W.wall_checks(g, web, f, FC, FY, special=True), "End ties where")["ok"]


def test_boundary_height_from_the_governing_row_at_the_base():
    # Same Pu and Mu, one row with almost no shear: the height stays max(lw, Mu/4Vu) of the
    # governing row (largest c, then largest Vu) = max(1000, 300e6 / 4e5 = 750) = 1000 mm, not
    # 300e6 / (4 x 500) = 150 m.
    g, b = _hand_section()
    s = W.pier_section(g, b, FC, FY)
    f = W.pier_forces(
        [{"P": 998.19, "V2": 100, "M3": 300}, {"P": 998.19, "V2": 0.5, "M3": 300}], 1e3, 1e6
    )
    need = W.boundary_need(g, s, f, FC, FY, b, drift=0.007)
    assert need.required and need.height == pytest.approx(1000.0)
    # Only the bottom cut is the critical section: a top-cut row with a larger Mu/4Vu is ignored
    # (Mu 1200 kN·m, Vu 100 kN at the base: 1200e6 / 4e5 = 3000 mm, capped by hw = 3000).
    rows = [
        W.PierForces("C1", 998.19e3, 100e3, 1200e6, where="P1 bottom"),
        W.PierForces("C2", 998.19e3, 1e3, 300e6, where="P1 top"),
    ]
    need = W.boundary_need(g, s, rows, FC, FY, b, drift=0.007)
    assert need.height == pytest.approx(3000.0)
    # The trigger depth is reported: 1000 / (600 x 0.007) = 238.1 mm.
    assert need.trigger == pytest.approx(1000 / 4.2)
    d = W.wall_checks(g, b, f, FC, FY, special=True, drift=0.007)
    row = _row(d, "Boundary elements: c >=")
    assert row["capacity"] == pytest.approx(1000 / 4.2, abs=0.05)
    assert "238 mm" in row["note"]


def test_eq_6_6_71_with_the_provided_rho_t():
    # lw 3000, hw 4500 (hw/lw 1.5), t 200, Nu 0, Vu 1400 kN, Mu 1000 kN·m, d = 2400.
    # Vc = max(0.17 √28 h d = 431.79, Eq. 6.6.68: 0.27 √28 h d = 685.78) kN (Eq. 6.6.69 not
    # applicable: Mu/Vu - lw/2 < 0). ρt required = (1400/0.75 - 685.78) e3 / (420 x 2400 x 200)
    # = 0.0058575. Provided 2 Ø12 @ 140: ρt = 0.0080784. Eq. 6.6.71: 0.0025 + 0.5 (2.5 - 1.5)
    # (0.0080784 - 0.0025) = 0.0052892 < 0.0058575: ρl >= 0.529 %.
    g = W.WallGeometry(3000, 200, 4500, 3000)
    b = W.WallBars(25, 12, 200, 12, 140, 2)
    d = W.wall_checks(g, b, _forces((0, 1400, 1000)), FC, FY)
    assert _row(d, "Vertical web ratio")["demand"] == pytest.approx(0.52892, abs=0.005)
    assert W.rho_l_eq71(g, 0.0080784, 0.0058575) == pytest.approx(0.0052892, rel=1e-4)
    # Not more than the required ρt: with ρt provided 0.012, 0.0025 + 0.5 x 0.0095 = 0.00725 is
    # capped at 0.0058575.
    assert W.rho_l_eq71(g, 0.012, 0.0058575) == pytest.approx(0.0058575)


def test_wall_need_warns_when_ordinary_shear_exceeds_the_limit():
    # lw 1500, t 150: φ 0.83 √28 h d = 0.75 x 0.83 x 5.2915 x 150 x 1200 = 592.9 kN < 1200 kN.
    g = W.WallGeometry(1500, 150, 9000, 3000)
    n = W.wall_need(g, _forces((500, 1200, 300)), FC, FY, search=True)
    assert any("6.4.8.3" in note and "593 kN" in note for note in n.notes), n.notes
