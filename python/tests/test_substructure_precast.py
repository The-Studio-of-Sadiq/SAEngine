"""Part 9 driven precast piles: the square section, handling moments and least bars, by hand.

A 400 mm square pile 12 m long in 2400 kg/m³ concrete weighs w = 2400 × 9.80665 × 0.16 =
3.766 kN/m; the handling moments are the statics of a uniform beam lifted at two points or
pitched from one.
"""

from __future__ import annotations

import math

import pytest

from saengine.library.objects import BarGroup, LinearReinforcement, Transverse
from saengine.substructure import piles, precast

UNIT_WEIGHT = 2400 * 9.80665e-9  # N/mm³


def _bars(count: int = 8, dia: float = 16) -> LinearReinforcement:
    return LinearReinforcement(
        material="B420",
        cover=40,
        longitudinal=[BarGroup(position="perimeter", count=count, dia=dia)],
        transverse=Transverse(type="tie", dia=8, spacing=150),
    )


def test_driven_pile_is_square_in_capacity() -> None:
    # Bored Ø400: perimeter π × 400, area π × 400² / 4; driven 400 square: 1600 and 160 000.
    assert piles.section_shape("bored", 400) == pytest.approx((math.pi * 400, math.pi * 4e4))
    assert piles.section_shape("driven", 400) == (1600, 160000)


def test_handling_moments_two_point_and_one_point() -> None:
    # Two points at 0.207 L: M = 0.0214 × 3.766 × 12² = 11.60 kN·m;
    # one point at 0.293 L: M = 0.0429 × 3.766 × 12² = 23.26 kN·m (without impact).
    out = precast.handling_moments(400, 12000, UNIT_WEIGHT)
    assert out["twoPoint"] / 1e6 == pytest.approx(11.60, abs=0.01)
    assert out["onePoint"] / 1e6 == pytest.approx(23.26, abs=0.01)


def test_cracking_moment_of_a_square() -> None:
    # Mcr = 0.62 √25 × 400³ / 6 = 33.07 kN·m (ACI 318-19 19.2.3.1).
    assert precast.cracking_moment(400, 25) / 1e6 == pytest.approx(33.07, abs=0.01)


def test_handling_checks_apply_impact() -> None:
    checks = precast.handling_checks(400, 12000, 30, 420, _bars(), UNIT_WEIGHT)
    names = [c["name"] for c in checks]
    assert names == [
        "Pile handling, lifted at two points",
        "Pile handling, pitched from one point",
        "Pile handling, cracking",
    ]
    # 1.5 × 23.26 = 34.89 kN·m pitched from one point.
    assert checks[1]["demand"] == pytest.approx(34.89, abs=0.01)
    assert checks[2]["flag"]


def test_unreinforced_precast_pile_cannot_be_handled() -> None:
    checks = precast.handling_checks(400, 12000, 30, 420, None, UNIT_WEIGHT)
    assert not checks[0]["ok"]


def test_least_bars_of_a_precast_pile() -> None:
    # 1 % of 400² = 1600 mm²: 8Ø16 = 1608 mm² passes, 4Ø16 = 804 mm² fails.
    assert precast.reinforcement_checks(400, _bars(8, 16))[0]["ok"]
    assert not precast.reinforcement_checks(400, _bars(4, 16))[0]["ok"]
