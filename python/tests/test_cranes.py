"""Crane runway loads (BNBC 2020 Part 6 Sec 2.3, crane loads = ASCE 7-05 Sec 4.10) and the
moving-load statics of the runway beams (saengine.fem.cranes)."""

from __future__ import annotations

import pytest

from saengine.codes import context as code_context
from saengine.fem import cranes
from saengine.library.settings import CraneRunway


def _crane(**changes: object) -> CraneRunway:
    values: dict[str, object] = {
        "id": "CR1",
        "kind": "pendantOperated",
        "capacity": 100.0,
        "bridgeWeight": 80.0,
        "trolleyWeight": 15.0,
        "span": 20000.0,
        "hookApproach": 1000.0,
        "wheels": 2,
        "wheelBase": 3000.0,
        "runwaySpan": 6000.0,
    }
    return CraneRunway.model_validate({**values, **changes})


def test_code_pack_crane_factors():
    table = code_context.table("cranes")
    # Vertical impact 25 % (powered monorail, cab and remote bridge), 10 % pendant, 0 % hand.
    assert table.impact["cabOperated"] == 0.25 and table.impact["monorail"] == 0.25
    assert table.impact["pendantOperated"] == 0.10 and table.impact["handGeared"] == 0.0
    assert table.lateral == 0.20 and table.longitudinal == 0.10


def test_wheel_loads_of_a_pendant_crane():
    loads = cranes.wheel_loads(_crane())
    # Rail near the trolley: 80/2 + (100 + 15)(20 - 1)/20 = 149.25 kN on two wheels.
    assert loads.static_max == pytest.approx(149.25 / 2)
    assert loads.static_min == pytest.approx((40 + 115 * 1 / 20) / 2)
    assert loads.vertical == pytest.approx(149.25 / 2 * 1.10)
    # Lateral: 20 % of (100 + 15), half on each runway, over two wheels.
    assert loads.lateral == pytest.approx(0.20 * 115 / 2 / 2)
    # Longitudinal: 10 % of the maximum wheel loads on the rail.
    assert loads.longitudinal == pytest.approx(0.10 * 149.25)


def test_moving_wheel_pair_on_a_simple_span():
    # Two equal loads a apart on a span L (a < 0.586 L): M = P (L - a/2)² / (2L).
    p, a, span = 10.0, 3.0, 6.0
    assert cranes.max_moment(p, 2, a, span) == pytest.approx(
        p * (span - a / 2) ** 2 / (2 * span), rel=2e-3
    )
    # End shear: the leading wheel at the support, the other a inside.
    assert cranes.max_shear(p, 2, a, span) == pytest.approx(p * (1 + (span - a) / span))
    # Column between two spans: one wheel over it, the other a away.
    assert cranes.max_reaction(p, 2, a, span) == pytest.approx(p * (1 + (span - a) / span))
    # One wheel: P L / 4.
    assert cranes.max_moment(p, 1, 0.0, span) == pytest.approx(p * span / 4, rel=1e-3)


def test_crane_summary_without_a_beam_type():
    rows, notes = cranes.crane_summary([_crane()], {}, {})
    assert rows[0]["wheelWithImpact_kN"] == pytest.approx(82.09, abs=0.01)
    assert "runwayBeam" not in rows[0] and "Sec 2.3" in notes[0]
