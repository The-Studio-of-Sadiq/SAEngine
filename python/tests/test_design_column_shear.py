"""Column shear with the axial force (saengine.design.column_shear) against hand calculations
to BNBC 2020 Part 6 Sec 6.4 (Eqs. 6.6.50, 6.6.54, 6.6.56; pp. 923-926)."""

from __future__ import annotations

import math

import pytest

from saengine.design.column_shear import column_shear_checks, concrete_shear, shear_axes
from saengine.design.rc import section_of
from saengine.library.objects import (
    BarGroup,
    CircleProfile,
    LinearReinforcement,
    RectangleProfile,
    Transverse,
)

TIES = Transverse(type="tie", dia=10, spacing=150, legs=2)


def gravity_column():
    """400 x 400, 8 Ø20 (3 a face), 40 mm clear cover to Ø10 ties at 150 mm, f'c 25, fy 420."""
    reinforcement = LinearReinforcement(
        material="rebar",
        cover=40,
        longitudinal=[BarGroup(position="perimeter", count=8, dia=20)],
        transverse=TIES,
    )
    return section_of(RectangleProfile(xDim=400, yDim=400), reinforcement, 25, 420)


def test_gravity_column_shear_capacity_with_axial_compression() -> None:
    section = gravity_column()
    axes = {a.axis: a for a in shear_axes(section, TIES)}
    # Far bars at 200 - 40 - 10 - 10 = 140 mm from the centre: d = 200 + 140 = 340 mm.
    assert axes["y"].bw == 400 and axes["y"].d == pytest.approx(340.0)
    assert axes["y"].av == pytest.approx(2 * math.pi * 10**2 / 4)
    nu, ag = 1000e3, 400 * 400
    vc = 0.17 * (1 + nu / (14 * ag)) * 5 * 400 * 340  # Eq. 6.6.50: 167.2 kN
    assert vc == pytest.approx(167_207, abs=1)
    assert concrete_shear(nu, ag, 400, 340, 25) == pytest.approx(vc)
    vs = 2 * math.pi * 25 * 420 * 340 / 150  # Av fyt d / s: 149.5 kN
    phi_vn = 0.75 * (vc + vs)  # 237.6 kN
    rows = column_shear_checks(
        section, TIES, [(nu, 0.0, 200e3, "1.2D+1.6L", "C1 at 0.00 L")], phi=0.75, fyt_max=420
    )
    along_y = next(r for r in rows if r["name"] == "Column shear along y")
    assert along_y["capacity"] == pytest.approx(phi_vn / 1e3, abs=0.01)
    assert along_y["demand"] == pytest.approx(200.0)
    assert along_y["ok"] and "1 + Nu/14Ag" in along_y["note"]
    # Vu > φVc: the tie spacing limit d/2 = 170 mm applies and 150 mm passes.
    spacing = next(
        r for r in rows if r["name"] == "Column shear along y: tie spacing (Sec 6.4.3.4)"
    )
    assert spacing["capacity"] == pytest.approx(170.0) and spacing["ok"]


def test_axial_tension_reduces_vc_to_zero() -> None:
    ag = 400 * 400
    # Eq. 6.6.54: 0.17 (1 + 0.29 Nu/Ag): Nu = -200 kN -> 1 - 0.3625 = 0.6375
    assert concrete_shear(-200e3, ag, 400, 340, 25) == pytest.approx(
        0.17 * (1 - 0.29 * 200e3 / ag) * 5 * 400 * 340
    )
    assert concrete_shear(-1000e3, ag, 400, 340, 25) == 0.0


def test_governing_point_uses_the_simultaneous_axial_force() -> None:
    section = gravity_column()
    points = [(2000e3, 0.0, 150e3, "A", ""), (100e3, 0.0, 150e3, "B", "")]
    rows = column_shear_checks(section, TIES, points, phi=0.75, fyt_max=420)
    along_y = next(r for r in rows if r["name"] == "Column shear along y")
    assert along_y["combination"] == "B"  # less compression: smaller Vc


def test_circular_column_uses_08d_and_two_hoop_areas() -> None:
    hoops = Transverse(type="spiral", dia=10, spacing=75, legs=2)
    reinforcement = LinearReinforcement(
        material="rebar",
        cover=40,
        longitudinal=[BarGroup(position="perimeter", count=8, dia=20)],
        transverse=hoops,
    )
    section = section_of(CircleProfile(radius=250), reinforcement, 30, 420)
    (part,) = shear_axes(section, hoops)
    assert part.bw == 500 and part.d == pytest.approx(400.0)
    assert part.av == pytest.approx(2 * math.pi * 25)
    rows = column_shear_checks(section, hoops, [(0.0, 60e3, 80e3, "C", "")], phi=0.75, fyt_max=420)
    assert rows[0]["demand"] == pytest.approx(100.0)  # √(60² + 80²)


def test_tie_spacing_checked_at_every_point_not_only_the_governing_one() -> None:
    """Ties Ø10 2-leg at 300 mm. A: Pu 3000 kN, Vy 165 kN governs Vu/φVn but has Vu < φVc
    (Vc = 115.6 x (1 + 3000e3/(14 x 160000)) = 270.4 kN, φVc = 202.8 kN). B: Pu 0, Vy 90 kN:
    Vc = 0.17 x 5 x 400 x 340 = 115.6 kN, φVc = 86.7 kN < 90 kN, so s <= d/2 = 170 mm applies
    (Vu/φ - Vc = 4.4 kN, far below 0.33 √f'c bw d = 224.4 kN) and 300 mm fails under B."""
    ties = Transverse(type="tie", dia=10, spacing=300, legs=2)
    section = gravity_column()
    points = [(3000e3, 0.0, 165e3, "A", "C1 at 0.00 L"), (0.0, 0.0, 90e3, "B", "C1 at 1.00 L")]
    rows = column_shear_checks(section, ties, points, phi=0.75, fyt_max=420)
    along_y = next(r for r in rows if r["name"] == "Column shear along y")
    assert along_y["combination"] == "A"
    phi_vc_b = 0.75 * 0.17 * 5 * 400 * 340
    assert phi_vc_b == pytest.approx(86_700)
    spacing = next(
        r for r in rows if r["name"] == "Column shear along y: tie spacing (Sec 6.4.3.4)"
    )
    assert spacing["combination"] == "B" and "1.00 L" in spacing["note"]
    assert spacing["demand"] == 300 and spacing["capacity"] == pytest.approx(170.0)
    assert not spacing["ok"]
    # Av = 157 mm² >= Av,min = 0.35 x 400 x 300 / 420 = 100 mm²: no minimum-ties row.
    assert not any("Av,min" in r["name"] for r in rows)


def test_minimum_ties_flag_found_at_a_non_governing_point() -> None:
    """Ø6 2-leg at 300 mm: Av = 56.5 mm² < Av,min = 100 mm². A (Pu 3000 kN, Vy 100 kN)
    is below 0.5 φVc = 101.4 kN; B (Pu 0, Vy 50 kN) is above 0.5 φVc = 43.35 kN."""
    ties = Transverse(type="tie", dia=6, spacing=300, legs=2)
    section = gravity_column()
    points = [(3000e3, 0.0, 100e3, "A", ""), (0.0, 0.0, 50e3, "B", "")]
    rows = column_shear_checks(section, ties, points, phi=0.75, fyt_max=420)
    flag = next(r for r in rows if r["name"].startswith("Column shear along y: minimum ties"))
    assert flag["combination"] == "B"
    assert flag["demand"] == pytest.approx(100.0) and flag["capacity"] == pytest.approx(
        2 * math.pi * 9, abs=0.01
    )
