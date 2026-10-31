"""Post-tensioned slabs (saengine.design.prestress): tendon forces, load balancing, hyperstatic
moments and the BNBC 2020 Part 6 Chapter 9 / ACI 318-11 Chapter 18 checks."""

from __future__ import annotations

import math

import numpy as np
import pytest

from saengine.design import prestress
from saengine.library.bim import SlabTendon
from saengine.library.templates import TEMPLATES

#: Two 8 m spans, CGS 125 mm at the ends, 40 mm low, 210 mm over the middle support.
POINTS = [(0.0, 125.0), (3600.0, 40.0), (8000.0, 210.0), (12400.0, 40.0), (16000.0, 125.0)]


def _tendon(**changes) -> SlabTendon:
    return SlabTendon(**{**TEMPLATES["SlabTendon"], **changes})


def test_parabola_has_its_vertex_at_the_low_point():
    piece = prestress.Segment(0, 4000, 200, 50)
    assert piece.height(4000) == 50
    assert piece.slope(4000) == 0
    assert piece.height(0) == 200
    assert piece.curvature == pytest.approx(2 * 150 / 4000**2)


def test_supports_are_the_ends_and_the_interior_high_points():
    assert prestress.supports(POINTS) == [0.0, 8000.0, 16000.0]


def test_balancing_loads_are_in_equilibrium():
    model, pieces = prestress.strip_model(POINTS)
    distributed, nodal, _ = prestress.balancing_loads(pieces, model, 1e6, 250)
    assert distributed @ np.diff(model.stations) + nodal.sum() == pytest.approx(0, abs=1e-6)


def test_continuous_beam_moment_over_the_middle_support():
    """Two equal spans under w: -w l² / 8 over the middle support."""
    model, _ = prestress.strip_model(POINTS)
    moments = model.moments(np.full(len(model.stations) - 1, -10.0))
    middle = int(np.argmin(np.abs(model.stations - 8000)))
    assert moments[middle] == pytest.approx(-10 * 8000**2 / 8, rel=1e-6)


def test_hyperstatic_moment_is_linear_between_supports():
    """M2 = M_bal + P e is zero at the end supports and linear between supports (ACI 318-11
    18.10.3)."""
    model, pieces = prestress.strip_model(POINTS)
    force = 1e6
    total = model.moments(*prestress.balancing_loads(pieces, model, force, 250))
    heights = np.array(
        [next(p for p in pieces if p.x0 <= x <= p.x1).height(x) for x in model.stations]
    )
    m2 = total + force * (125 - heights)
    assert m2[0] == pytest.approx(0, abs=1e-3)
    at = [float(np.interp(x, model.stations, m2)) for x in (0, 4000, 8000)]
    assert at[1] == pytest.approx((at[0] + at[2]) / 2, rel=1e-6)


def test_friction_force():
    """ACI 318-11 18.6.2.1: P = Pj e^-(K x + μ α) on a straight tendon (α = 0)."""
    pieces = prestress.segments([(0, 125), (10000, 125)])
    stations = np.array([0.0, 5000.0, 10000.0])
    force = prestress.friction_forces(1e6, pieces, stations, 0.0033, 0.07, "start")
    assert force[-1] == pytest.approx(1e6 * math.exp(-0.0033 * 10), rel=1e-9)


def test_anchor_set_balances_the_draw_in():
    """The area of the force lost to the draw-in is Δ Ep Aps."""
    stations = np.linspace(0, 20000, 401)
    force = 1e6 * (1 - 1e-5 * stations)  # 10 N/mm of friction
    after, length = prestress.anchor_set(force, stations, 6, 195_000, 500, "start")
    lost = np.trapezoid(force - after, stations)
    assert lost == pytest.approx(6 * 195_000 * 500, rel=2e-3)
    # Linear friction p: x_set = √(Δ Ep Aps / p).
    assert length == pytest.approx(math.sqrt(6 * 195_000 * 500 / 10), rel=1e-2)


def test_unbonded_stress_at_strength():
    """ACI 318-11 18.7.2: fse + 70 + f'c / (100 ρp) <= fpy, fse + 420; above span/depth 35,
    / (300 ρp) <= fse + 210."""
    fps = prestress.stress_at_strength(1100, 1860, 1674, 35, 0.002, 30, False)
    assert fps == pytest.approx(1100 + 70 + 35 / 0.2)
    slender = prestress.stress_at_strength(1100, 1860, 1674, 35, 0.002, 40, False)
    assert slender == pytest.approx(1100 + 70 + 35 / 0.6)
    capped = prestress.stress_at_strength(1100, 1860, 1674, 35, 0.0002, 30, False)
    assert capped == pytest.approx(1100 + 420)


def test_bonded_stress_at_strength():
    """ACI 318-11 18.7.2 (a), γp = 0.28: fpu (1 - γp / β1 ρp fpu / f'c)."""
    fps = prestress.stress_at_strength(1100, 1860, 1674, 28, 0.003, 30, True)
    assert fps == pytest.approx(1860 * (1 - 0.28 / 0.85 * 0.003 * 1860 / 28))


def test_punching_with_prestress():
    """ACI 318-11 11.11.2.2: βp √f'c + 0.3 fpc, βp <= 0.29; fpc 0.9-3.5 MPa."""
    vc = prestress.punching_vc(35, 200, 4000, 40, 1.5)
    assert vc == pytest.approx(0.29 * math.sqrt(35) + 0.45)
    small = prestress.punching_vc(35, 100, 6000, 40, 1.5)
    assert small == pytest.approx(0.083 * (1.5 + 40 * 100 / 6000) * math.sqrt(35) + 0.45)
    assert prestress.punching_vc(35, 200, 4000, 40, 0.5) is None


def test_tendon_design_checks_are_named_and_cited():
    design = prestress.tendon_design(
        _tendon(transferStrength=25),
        250,
        35,
        420,
        prestress.StripLoads(0.006, 0.0015, 0.003),
        400,
        600,
        215,
        215,
        True,
    )
    names = {c["name"] for c in design.checks}
    assert {
        "PT PT1: stress at the anchors after transfer",
        "PT PT1: transfer compression",
        "PT PT1: service tension",
        "PT PT1: flexural strength",
        "PT PT1: average precompression",
    } <= names
    assert design.precompression == pytest.approx(
        float(np.mean(design.forces.effective)) / (4000 * 250)
    )
