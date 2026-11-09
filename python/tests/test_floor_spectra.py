"""Alpha 9 L5: floor response spectra: broadening, the direct spectrum-to-spectrum method and the
components' forces from them (written 2026-11-05, not run yet: the test pass is next).

Note: the time-history method reads a run's HDF5 results; it is covered by the end-to-end pass."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

from saengine.fem import floor_spectra as fs


def test_broadening_widens_a_peak_by_15_percent() -> None:
    t = np.geomspace(0.05, 2.0, 200)
    sa = np.where(np.abs(t - 0.5) < 0.01, 1.0, 0.2)
    out = fs.broaden(t, sa, 0.15)
    assert out[np.argmin(np.abs(t - 0.44))] == pytest.approx(1.0)  # 0.5 within 0.44 (1 ± 0.15)
    assert out[np.argmin(np.abs(t - 0.57))] == pytest.approx(1.0)
    assert out[np.argmin(np.abs(t - 0.70))] == pytest.approx(0.2, abs=0.05)
    assert np.all(out >= sa - 1e-12)


def test_peak_factor_davenport() -> None:
    # λ0 = 1, λ2 = (2π)²: ν = 2 per second; over 20 s, n = 40
    p = fs.peak_factor((1.0, 0.0, (2 * math.pi) ** 2), 20.0)
    root = math.sqrt(2 * math.log(40))
    assert p == pytest.approx(root + 0.5772 / root)


def test_floor_transfer_limits() -> None:
    w = np.array([1e-3, 1e4])
    h = fs.floor_transfer(w, [10.0], [1.0], 0.05)
    assert h[0] == pytest.approx(1.0, abs=1e-6)  # rigid at low frequency: the ground motion
    assert h[1] == pytest.approx(0.0, abs=1e-4)  # Σ Γφ = 1: filtered out far above the mode


def test_rigid_floor_follows_the_ground_spectrum() -> None:
    periods = np.geomspace(0.05, 3.0, 40)
    ground = np.array([0.4 if t < 0.6 else 0.4 * 0.6 / t for t in periods])
    floor = fs.direct_floor_spectrum(periods, ground, [], [], 0.05, 0.05, 20.0, 8)
    middle = slice(5, 30)
    assert np.allclose(floor[middle], ground[middle], rtol=0.2)


def test_one_mode_amplifies_at_its_period() -> None:
    periods = np.geomspace(0.05, 3.0, 60)
    ground = np.full(len(periods), 0.3)
    t1 = 0.8
    floor = fs.direct_floor_spectrum(
        periods, ground, [2 * math.pi / t1], [1.3], 0.05, 0.05, 20.0, 6
    )
    peak = periods[int(np.argmax(floor))]
    assert peak == pytest.approx(t1, rel=0.15)
    assert floor.max() > 2 * ground.max()


def test_components_take_the_floor_spectrum(tmp_path: Path) -> None:
    (tmp_path / "08 FEM").mkdir()
    found = {
        "available": True,
        "componentDamping": 0.05,
        "periods": [0.02, 0.06, 0.5, 2.0],
        "floors": [
            {"z": 3.0, "direction": "X", "damping": 0.05, "sa": [0.5, 0.5, 1.5, 0.3]},
            {"z": 6.0, "direction": "X", "damping": 0.05, "sa": [0.8, 0.8, 2.0, 0.4]},
        ],
    }
    (tmp_path / "08 FEM" / fs.FILE).write_text(json.dumps(found), encoding="utf-8")
    rule = NS(
        componentDamping=0.05,
        components=NS(rigidPeriod=0.06, flexibleAlpha=1.0, divideByR=True, bounds=True),
        sources={},
        source="test",
    )
    pack = NS(has=lambda name: True, table=lambda name: rule)
    settings = NS(analysis=NS(floorSpectra=NS(useForComponents=True)))
    rigid = {
        "z": 6000.0,
        "alpha": 1.0,
        "Wc": 10.0,
        "Ic": 1.0,
        "R": 2.5,
        "lower": 0.1,
        "upper": 50.0,
        "Fc": 1.0,
        "design": 1.0,
        "factor": 1.0,
        "perMetre": 2.0,
    }
    flexible = {**rigid, "z": 3100.0, "alpha": 2.5}
    notes = fs.apply_to_components(tmp_path, [rigid, flexible], NS(base=0.0), pack, settings)
    assert rigid["Fc"] == pytest.approx(0.8 * 10 / 2.5)  # Sa at 0.06 s on the 6 m floor
    assert rigid["perMetre"] == pytest.approx(2.0 * rigid["design"])
    assert flexible["Fc"] == pytest.approx(1.5 * 10 / 2.5)  # the 3 m floor's peak
    assert "2 components" in notes[0]


def test_components_unchanged_unless_asked(tmp_path: Path) -> None:
    row = {"Fc": 1.0, "design": 1.0}
    settings = NS(analysis=NS(floorSpectra=None))
    assert fs.apply_to_components(tmp_path, [row], NS(base=0.0), None, settings) == []
    assert row == {"Fc": 1.0, "design": 1.0}
