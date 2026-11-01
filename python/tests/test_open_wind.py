"""Wind on open structures by force coefficients (BNBC 2020 Part 6 Sec 2.4, other structures:
the values of ASCE 7-05 Figures 6-22 and 6-23; saengine.fem.open_wind)."""

from __future__ import annotations

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.fem import open_wind as ow
from saengine.library.objects import CircleHollowProfile, IShapeProfile


def _table():
    return code_context.table("wind").openStructures


def test_lattice_coefficients_by_solidity():
    t = _table()
    assert ow.lattice_cf(t, 0.05) == 2.0
    assert ow.lattice_cf(t, 0.2) == 1.8
    assert ow.lattice_cf(t, 0.5) == 1.6
    # Rounded members: D√qz up to 2.5 ft·√psf (5.27 m·√Pa) and above.
    assert ow.lattice_cf(t, 0.2, rounded=True, d_sqrt_qz=1.0) == 1.3
    assert ow.lattice_cf(t, 0.2, rounded=True, d_sqrt_qz=10.0) == 0.9
    assert ow.FT_SQRT_PSF * 2.5 == pytest.approx(5.27, abs=0.01)


def test_trussed_tower_coefficients():
    t = _table()
    e = 0.2
    square = 4.0 * e * e - 5.9 * e + 4.0
    assert ow.tower_cf(t, e, "square") == pytest.approx(square)
    assert ow.tower_cf(t, e, "triangular") == pytest.approx(3.4 * e * e - 4.7 * e + 3.4)
    assert ow.tower_cf(t, e, "square", diagonal=True) == pytest.approx(square * (1 + 0.75 * e))
    assert ow.tower_cf(t, e, "square", rounded=True) == pytest.approx(
        square * (0.51 * e * e + 0.57)
    )


def test_outer_width_of_profiles():
    i = IShapeProfile(overallWidth=150, overallDepth=300, webThickness=7, flangeThickness=10)
    assert ow.outer_width(i) == 300
    assert ow.outer_width(CircleHollowProfile(radius=50, wallThickness=4)) == 100


def test_member_load_is_qz_g_cf_d():
    column = ow.WindMember(0, np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 10.0]), 0.2)
    result = ow.open_structure_wind([column], lambda z: 1000.0, 0.85, _table(), solidity=0.05)
    ((index, vector),) = result.loads["WX"]
    # w = qz G Cf d = 1000 × 0.85 × 2.0 × 0.2 = 340 N/m along +X.
    assert index == 0 and vector == pytest.approx([340.0, 0.0, 0.0])
    assert result.summary["WX"]["force_kN"] == pytest.approx(3.4)


def test_member_along_the_wind_takes_none_and_solidity_is_computed():
    along = ow.WindMember(0, np.array([0.0, 0.0, 5.0]), np.array([4.0, 0.0, 5.0]), 0.2)
    post = ow.WindMember(1, np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 5.0]), 0.2)
    post2 = ow.WindMember(2, np.array([0.0, 4.0, 0.0]), np.array([0.0, 4.0, 5.0]), 0.2)
    result = ow.open_structure_wind([along, post, post2], lambda z: 500.0, 0.85, _table())
    assert {i for i, _ in result.loads["WX"]} == {1, 2}
    # Facing X: two posts 0.2 × 5 over the outline 4 × 5 → ε = 0.1 → Cf 1.8.
    assert result.summary["WX"]["solidity"] == pytest.approx(0.1)
    assert result.summary["WX"]["Cf"] == 1.8
