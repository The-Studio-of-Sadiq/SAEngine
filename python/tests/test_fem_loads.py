"""BNBC 2020 equivalent static loads and slab load distribution."""

from __future__ import annotations

import pytest

from saengine.fem.loads import (
    approximate_period,
    design_acceleration,
    normalized_spectrum,
    slab_edge_loads,
    velocity_pressure,
    vertical_distribution,
    wind_level_forces,
)


def test_period_and_spectrum() -> None:
    # RC moment frame 3 storeys, 9.6 m: T = 0.0466 * 9.6^0.9.
    assert approximate_period(9.6, "rcImf") == pytest.approx(0.0466 * 9.6**0.9)
    # Site class SD: plateau 2.5·S = 3.375 between TB 0.2 and TC 0.8 s; descending branch after.
    assert normalized_spectrum(0.5, "SD") == pytest.approx(3.375)
    assert normalized_spectrum(1.6, "SD") == pytest.approx(3.375 * 0.8 / 1.6)
    assert normalized_spectrum(0.0, "SD") == pytest.approx(1.35)
    # Sa = 2/3 · Z·I/R · Cs: Dhaka (Z 0.20), I 1.0, R 5 on the SD plateau.
    assert design_acceleration(0.5, "SD", 0.20, 1.0, 5.0) == pytest.approx(2 / 3 * 0.2 / 5 * 3.375)


def test_vertical_distribution() -> None:
    forces = vertical_distribution([(3.2, 1000.0), (6.4, 1000.0)], 300.0, 0.4)
    assert forces == pytest.approx([100.0, 200.0])  # k = 1: proportional to height
    assert sum(vertical_distribution([(3, 500), (6, 400), (9, 300)], 120.0, 1.5)) == pytest.approx(
        120.0
    )


def test_wind() -> None:
    # qz at 10 m, exposure B (open terrain): 0.000613·Kz·Kd·V²·I with Kz = 2.01·(10/274.32)^(2/9.5).
    kz = 2.01 * (10 / 274.32) ** (2 / 9.5)
    assert velocity_pressure(10, 65.7, "B", 1.0) == pytest.approx(0.000613 * kz * 0.85 * 65.7**2)
    forces = wind_level_forces(
        [3.2, 6.4], width=13.0, depth=5.0, speed=65.7, exposure="A", importance=1.0
    )
    assert (
        len(forces) == 2 and forces[0] > forces[1] > 0
    )  # the lower level takes the larger wall area


def test_slab_edge_loads() -> None:
    rect = [(0, 0), (6, 0), (6, 5), (0, 5)]
    loads = slab_edge_loads(rect, 10.0, "twoWay")
    # lx 5, ly 6: long edges w·lx(2ly-lx)/4 / ly, short edges w·lx²/4 / lx.
    assert [round(e.load, 4) for e in loads] == [
        round(10 * 5 * 7 / 4 / 6, 4),
        12.5,
        round(10 * 5 * 7 / 4 / 6, 4),
        12.5,
    ]
    assert sum(e.load * length for e, length in zip(loads, [6, 5, 6, 5])) == pytest.approx(10 * 30)
    one_way = slab_edge_loads(rect, 10.0, "oneWay")
    assert [e.load for e in one_way] == pytest.approx([25.0, 0.0, 25.0, 0.0])
    triangle = slab_edge_loads([(0, 0), (4, 0), (0, 3)], 10.0, "twoWay")
    assert sum(e.load * length for e, length in zip(triangle, [4, 5, 3])) == pytest.approx(10 * 6)
