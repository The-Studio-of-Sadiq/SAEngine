"""soil/earthPressure: the profile's σv and u columns (found blank in the Alpha 2 walkthrough)."""

from __future__ import annotations

from pathlib import Path

import pytest

from saengine.rpc.u6d_handlers import soil_earth_pressure


def test_profile_reports_vertical_stress_and_pore_pressure(tmp_path: Path) -> None:
    # No boreholes: the entered φ' = 30° and γ = 18 kN/m³ apply, no surcharge, dry.
    # At z = 4 m: σv = 18 × 4 = 72 kPa, u = 0; Ka = tan²(30°) = 1/3, so σa = 72 / 3 = 24 kPa.
    out = soil_earth_pressure(str(tmp_path), depth_m=4.0, surcharge_kpa=0.0, phi_deg=30.0)
    last = out["profile"][-1]
    assert last["z"] == pytest.approx(4.0)
    assert last["sigmaV"] == pytest.approx(72.0, rel=0.01)
    assert last["u"] == pytest.approx(0.0, abs=0.01)
    assert last["active"] == pytest.approx(24.0, rel=0.01)


def test_profile_pore_pressure_below_the_water_table(tmp_path: Path) -> None:
    # Water table at 1 m: at z = 4 m, u = 9.81 × 3 = 29.4 kPa, and σv = σ'v + u > u.
    out = soil_earth_pressure(
        str(tmp_path), depth_m=4.0, surcharge_kpa=0.0, phi_deg=30.0, water_table_m=1.0
    )
    last = out["profile"][-1]
    assert last["u"] == pytest.approx(29.4, rel=0.02)
    assert last["sigmaV"] > last["u"]
