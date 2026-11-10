"""Floor vibration: the modal mass of a continuous slab over the bays its mode spreads over
(decision 2026-11-10, "Floor vibration modal mass over several bays")."""

from __future__ import annotations

import numpy as np
import pytest

from saengine.codes import tables
from saengine.codes.practice_tables import FloorVibrationTable, ModalSpread
from saengine.fem import floor_vibration as fv

assert tables.TABLE_MODELS["floorVibration"] is FloorVibrationTable


def _grid(xs: list[float], ys: list[float]) -> np.ndarray:
    """Column nodes at every grid intersection (z = 0)."""
    return np.array([(x, y, 0.0) for x in xs for y in ys])


def _walk_case() -> tuple:
    rules = fv.table()
    residential = rules.occupancies["residential"]
    # 150 mm RC slab, 1.5 kN/m² superimposed dead load, the residential service live load.
    w = 2400 * 9.81 * 0.15 / 1e3 + 1.5 + residential.serviceLive
    return rules, residential, w


def test_default_pack_has_the_spread() -> None:
    spread = fv.table().responseFactor.spread
    assert spread is not None
    assert (spread.adjacentShare, spread.maxBays, spread.minimumSpanRatio) == (0.5, 4, 0.7)


def test_single_bay_keeps_the_one_bay_mass() -> None:
    rules, residential, w = _walk_case()
    supports = _grid([0.0, 6.0], [0.0, 5.0])
    bays = fv.continuous_bays(np.array([3.0, 2.5, 0.0]), supports, rules.responseFactor.spread)
    assert bays == (1, 1)
    found = fv.check_panel("responseFactor", 15.0, w, 30.0, 6.0, residential, rules, bays)
    zeta = rules.responseFactor.damping[rules.defaultFitOut]
    one_bay = fv.response_factor(15.0, w * 1e3 / fv.G * 30.0, 6.0, zeta, rules.responseFactor)
    assert found["value"] == pytest.approx(one_bay["R"])
    assert "effective bays" not in found["how"]
    # The default argument is the one bay too (callers without a model).
    plain = fv.check_panel("responseFactor", 15.0, w, 30.0, 6.0, residential, rules)
    assert plain["value"] == pytest.approx(found["value"])


def test_continuous_floor_counts_its_bays() -> None:
    rules, residential, w = _walk_case()
    spread = rules.responseFactor.spread
    supports = _grid([0.0, 6.0, 12.0, 18.0], [0.0, 5.0, 10.0])
    # Every panel of the 3 x 2 floor (corner and middle) sees the whole run.
    for point in ((3.0, 2.5), (9.0, 7.5), (15.0, 2.5)):
        assert fv.continuous_bays(np.array([*point, 0.0]), supports, spread) == (3, 2)
    one = fv.check_panel("responseFactor", 15.0, w, 30.0, 6.0, residential, rules)
    many = fv.check_panel("responseFactor", 15.0, w, 30.0, 6.0, residential, rules, (3, 2))
    # M × (1 + 0.5·2) × (1 + 0.5·1) = 3 × the one-bay mass; R ∝ 1/M.
    assert many["value"] == pytest.approx(one["value"] / 3.0)
    assert one["value"] > residential.responseLimit >= many["value"]
    assert "2.00 × 1.50 (effective bays of 3 × 2 continuous)" in many["how"]


def test_free_edges_short_bays_and_cap_end_the_run() -> None:
    spread = fv.table().responseFactor.spread
    # A 2 m bay (< 0.7 × 6 m) ends the run on that side; 6 bays each way are capped at 4.
    supports = _grid([0.0, 2.0, 8.0, 14.0], [0.0, 5.0])
    assert fv.continuous_bays(np.array([5.0, 2.5, 0.0]), supports, spread) == (2, 1)
    wide = _grid([6.0 * i for i in range(7)], [5.0 * i for i in range(7)])
    assert fv.continuous_bays(np.array([15.0, 12.5, 0.0]), wide, spread) == (6, 6)
    assert fv.effective_bays(6, spread) == pytest.approx(1 + 0.5 * 3)
    # The row only: an L-shaped floor's bays beyond the panel's row of supports do not count.
    ell = np.vstack([_grid([0.0, 6.0], [0.0, 5.0, 10.0]), _grid([12.0, 18.0], [5.0, 10.0])])
    assert fv.continuous_bays(np.array([3.0, 2.5, 0.0]), ell, spread) == (1, 2)
    assert fv.continuous_bays(np.array([3.0, 7.5, 0.0]), ell, spread) == (3, 2)


def test_pack_parameters_are_respected() -> None:
    rules, residential, w = _walk_case()
    data = rules.model_dump()
    data["responseFactor"]["spread"] = {"adjacentShare": 1.0, "maxBays": 2, "minimumSpanRatio": 0.5}
    own = FloorVibrationTable.model_validate(data)
    assert isinstance(own.responseFactor.spread, ModalSpread)
    one = fv.check_panel("responseFactor", 15.0, w, 30.0, 6.0, residential, rules)
    found = fv.check_panel("responseFactor", 15.0, w, 30.0, 6.0, residential, own, (3, 2))
    # 1 + 1·(min(3, 2) - 1) = 2 in X, 2 in Y.
    assert found["value"] == pytest.approx(one["value"] / 4.0)
    # A pack without a spread keeps the one-bay mass whatever the floor.
    data["responseFactor"]["spread"] = None
    none = FloorVibrationTable.model_validate(data)
    supports = _grid([0.0, 6.0, 12.0, 18.0], [0.0, 5.0, 10.0])
    assert fv.continuous_bays(np.array([3.0, 2.5, 0.0]), supports, None) == (1, 1)
    plain = fv.check_panel("responseFactor", 15.0, w, 30.0, 6.0, residential, none, (3, 2))
    assert plain["value"] == pytest.approx(one["value"])
    with pytest.raises(ValueError):
        data["responseFactor"]["spread"] = {
            "adjacentShare": 1.5,
            "maxBays": 2,
            "minimumSpanRatio": 0.5,
        }
        FloorVibrationTable.model_validate(data)
