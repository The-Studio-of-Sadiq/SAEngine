"""Section capacity by fibre integration (saengine.library.section_capacity): moment-curvature
against hand values, the plastic interaction of steel sections, and the M-M contours."""

from __future__ import annotations

import math

import numpy as np
import pytest
from test_section_designer import MATERIALS, rect, section

from saengine.library import section_capacity as sc
from saengine.library import section_designer as sd

FY_PLATE = 250.0  # A36 of the Section Designer tests
FC = 30.0
E_C = 25_700.0
FY_BAR = 420.0
E_S = 200_000.0


# ─────────────────────────────────────── materials ───────────────────────────────────────


def test_hognestad_curve():
    """f = f''c (2 ε/ε0 - (ε/ε0)²), f''c = 0.85 f'c (BNBC 2020 Part 6 Sec 6.2.2), ε0 = 2 f''c / Ec
    (Hognestad 1951; Park and Paulay 1975 Sec 2.1.3); 0.85 f''c at 0.0038."""
    fpp = 0.85 * FC
    eps0 = 2 * fpp / E_C
    fc, ec, fr = np.array([FC]), np.array([E_C]), np.array([0.62 * math.sqrt(FC)])
    at = lambda e: float(sc.concrete_stress(np.array([e]), fc, ec, fr, True)[0])
    assert at(eps0) == pytest.approx(fpp)
    assert at(eps0 / 2) == pytest.approx(fpp * 0.75)
    assert at(0.0038) == pytest.approx(0.85 * fpp)
    # Tension: linear to fr = 0.62 √f'c (BNBC 2020 Part 6 Eq. 6.6.3), then cracked.
    crack = 0.62 * math.sqrt(FC) / E_C
    assert at(-0.5 * crack) == pytest.approx(-0.5 * 0.62 * math.sqrt(FC))
    assert at(-1.01 * crack) == 0.0
    assert float(sc.concrete_stress(np.array([-0.5 * crack]), fc, ec, fr, False)[0]) == 0.0


def test_steel_elastic_plastic():
    fy, es = np.array([FY_BAR]), np.array([E_S])
    assert float(sc.steel_stress(np.array([0.001]), fy, es)[0]) == pytest.approx(200.0)
    assert float(sc.steel_stress(np.array([0.01]), fy, es)[0]) == FY_BAR
    assert float(sc.steel_stress(np.array([-0.01]), fy, es)[0]) == -FY_BAR


def test_fibres_area_and_displaced_concrete():
    s = section(rect(0, 0, 300, 500), bars=[(150, 50, 20)])
    f = sc.fibres(s, MATERIALS)
    bar = math.pi * 100
    assert f.area[f.concrete].sum() == pytest.approx(300 * 500 - bar, rel=1e-9)
    assert f.area[f.steel].sum() == pytest.approx(bar)
    assert (f.cx, f.cy) == pytest.approx((150, 250))


# ─────────────────────────────────── moment-curvature ───────────────────────────────────


def test_steel_plate_yield_and_plastic_moment():
    """A 100 x 200 plate of fy 250 about x: first yield at My = fy b h² / 6 = 166.7 kN·m and
    κy = 2 εy / h; the curve tends to Mp = fy b h² / 4 = 250 kN·m."""
    s = section(rect(0, 0, 100, 200), material="A36")
    r = sc.moment_curvature(s, MATERIALS, steel_limit=0.05)
    assert r["end"] == "steel"
    assert r["yield"]["M"] == pytest.approx(FY_PLATE * 100 * 200**2 / 6, rel=0.01)
    assert r["yield"]["kappa"] == pytest.approx(2 * FY_PLATE / E_S / 200, rel=0.01)
    assert r["ultimate"]["M"] == pytest.approx(FY_PLATE * 100 * 200**2 / 4, rel=0.01)
    assert r["EIeff"] == pytest.approx(E_S * 100 * 200**3 / 12, rel=0.02)
    # The limit strain 0.05 at the extreme fibre: κu = 0.05 / 100.
    assert r["ultimate"]["kappa"] == pytest.approx(0.05 / 100, rel=0.01)
    assert r["ductility"] > 20


def test_rc_beam_against_hand_values():
    """300 x 500, 3 Ø20 at d = 450, f'c 30, fy 420, no axial force.

    - cracking: Mcr = fr I / yt of the transformed section > fr Ig / yt of the gross one
      (42.4 kN·m, BNBC 2020 Part 6 Eqs. 6.6.2-6.6.3);
    - first yield: the cracked elastic section, k = √(2 n ρ + (n ρ)²) - n ρ, j = 1 - k / 3,
      My = As fy j d = 161.5 kN·m, κy = εy / (d (1 - k)) = 6.48e-6 / mm (the parabola, softer
      than linear, gives slightly less moment and more curvature);
    - ultimate: εcu = 0.003 (BNBC 2020 Part 6 Sec 6.2.2) at about the stress-block strength
      Mn = As fy (d - a / 2) = 167.9 kN·m."""
    s = section(rect(0, 0, 300, 500), bars=[(60, 50, 20), (150, 50, 20), (240, 50, 20)])
    r = sc.moment_curvature(s, MATERIALS)
    assert r["end"] == "concrete"
    gross = 0.62 * math.sqrt(FC) * 300 * 500**3 / 12 / 250
    assert gross < r["cracking"]["M"] < 1.15 * gross
    as_ = 3 * math.pi * 100
    n, rho, d = E_S / E_C, as_ / (300 * 450), 450
    k = math.sqrt(2 * n * rho + (n * rho) ** 2) - n * rho
    my = as_ * FY_BAR * (1 - k / 3) * d
    assert r["yield"]["M"] == pytest.approx(my, rel=0.02)
    assert r["yield"]["kappa"] == pytest.approx(FY_BAR / E_S / (d * (1 - k)), rel=0.05)
    a = as_ * FY_BAR / (0.85 * FC * 300)
    assert r["ultimate"]["M"] == pytest.approx(as_ * FY_BAR * (d - a / 2), rel=0.02)
    assert r["ultimate"]["epsC"] == pytest.approx(0.003, rel=1e-3)
    assert r["ductility"] > 4


def test_compression_lowers_ductility_and_bottom_flips_sign():
    s = section(
        rect(0, 0, 400, 400),
        bars=[(x, y, 20) for x in (60, 200, 340) for y in (60, 340)],
    )
    free = sc.moment_curvature(s, MATERIALS, axial=0.0)
    loaded = sc.moment_curvature(s, MATERIALS, axial=1_000e3)
    assert loaded["ultimate"]["M"] > free["ultimate"]["M"]  # below the balance point
    assert loaded["ductility"] < free["ductility"]
    bottom = sc.moment_curvature(s, MATERIALS, axial=0.0, theta=math.pi)
    assert bottom["ultimate"]["M"] == pytest.approx(free["ultimate"]["M"], rel=0.01)
    assert bottom["ultimate"]["Mx"] == pytest.approx(-free["ultimate"]["Mx"], rel=0.01)


def test_axial_force_beyond_the_section():
    s = section(rect(0, 0, 300, 300), bars=[(50, 50, 16), (250, 250, 16)])
    with pytest.raises(sd.SectionError):
        sc.moment_curvature(s, MATERIALS, axial=1e9)


def test_equal_energy_bilinear():
    """A curve that is already elastic-perfectly plastic is its own idealisation."""
    k = 10.0
    kappa = [0.0, 1.0, 2.0, 5.0]
    moment = [0.0, 10.0, 10.0, 10.0]
    mn, ky = sc.equal_energy_bilinear(kappa, moment, k)
    assert (mn, ky) == pytest.approx((10.0, 1.0))


# ─────────────────────────────── plastic interaction (steel) ───────────────────────────────


def test_plastic_plate_interaction():
    """Rectangle b x h: Py = fy b h; at P = 0, Mp = fy b h² / 4; at P = Py / 2 the plastic
    neutral axis is h / 4 off centre, M = Mp (1 - (P/Py)²) (rectangle yield surface)."""
    s = section(rect(0, 0, 100, 200), material="A36")
    plastic = sc.PlasticSection(s, MATERIALS)
    py = FY_PLATE * 100 * 200
    mp = FY_PLATE * 100 * 200**2 / 4
    assert plastic.squash == pytest.approx(py)
    diagram = plastic.uniaxial("x")
    assert max(p["M"] for p in diagram["points"]) == pytest.approx(mp, rel=0.01)
    contour = plastic.contour(py / 2)
    mx = max(abs(row["Mx"]) for row in contour)
    assert mx == pytest.approx(mp * (1 - 0.25), rel=0.02)
    # φ of the pack's steel table (BNBC 2020 Part 6 Chapter 10): 0.9.
    assert diagram["phiPnMax"] == pytest.approx(0.9 * py)
    assert plastic.contour(1.01 * py) is None


def test_plastic_rejects_concrete():
    s = section(rect(0, 0, 300, 300), bars=[(50, 50, 16)])
    with pytest.raises(sd.SectionError):
        sc.PlasticSection(s, MATERIALS)


# ─────────────────────────────────────── analyse ───────────────────────────────────────


def test_analyse_steel_section_gets_plastic_capacity():
    s = section(rect(0, 0, 100, 200), material="A36")
    text = s.model_dump_json(by_alias=True)
    result = sd.analyse(text, MATERIALS.model_dump_json(), contour_at=0.0)
    assert result["capacityKind"] == "plastic"
    assert "uniaxial" in result and result["contour"]["points"]


def test_analyse_rc_contour_and_curve():
    s = section(
        rect(0, 0, 400, 400),
        bars=[(x, y, 20) for x in (60, 200, 340) for y in (60, 340)],
    )
    text = s.model_dump_json(by_alias=True)
    result = sd.analyse(
        text,
        MATERIALS.model_dump_json(),
        capacity=False,
        moment_curvature={"axial": 500e3, "theta": 0.0},
        contour_at=500e3,
    )
    assert result["capacityKind"] == "rc"
    assert result["momentCurvature"]["ultimate"]["M"] > 0
    points = result["contour"]["points"]
    # Symmetric bars: the contour reaches about the same φMx on both sides.
    mx = [row["phiMx"] for row in points]
    assert max(mx) == pytest.approx(-min(mx), rel=0.02)
