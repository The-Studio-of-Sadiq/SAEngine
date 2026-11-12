"""B9: serviceability through the bnbc2020 pack: storey drift and sway under the service wind
(Part 6 Sec 1.5.6.1(a), 1.5.6.2, Sec 2.7.5), member deflection limits (Sec 1.2.5 Table 6.1.2)
and the overturning stability of the whole building (Sec 1.5.5, 1.8.4)."""

from __future__ import annotations

import numpy as np
import pytest

from saengine.codes import context as code_context
from saengine.design.steel.members import deflection_checks
from saengine.fem import serviceability as sv
from saengine.fem.combinations import service_combinations


def _table():
    return code_context.table("serviceability")


def test_pack_values_sec_1_5_6_and_table_6_1_2():
    t = _table()
    # Sec 1.5.6.1(a), pp. 499-500
    assert t.storeyDrift.periodSplit == 0.7
    assert t.storeyDrift.shortPeriod == 0.005
    assert t.storeyDrift.longPeriod == 0.004
    assert t.storeyDrift.unreinforcedMasonry == 0.0025
    # Sec 1.5.6.2, p. 500: H/500
    assert t.sway.ratio == pytest.approx(1 / 500)
    # Table 6.1.2, p. 482 (columns L, W, D + L) and note a
    uses = t.deflection.uses
    assert (uses["roofPlasterCeiling"].live, uses["roofPlasterCeiling"].wind) == (360, 360)
    assert uses["roofPlasterCeiling"].deadLive == 240
    assert (uses["roofOtherCeiling"].live, uses["roofOtherCeiling"].deadLive) == (240, 180)
    assert (uses["roofNoCeiling"].live, uses["roofNoCeiling"].deadLive) == (180, 120)
    assert (uses["floor"].live, uses["floor"].wind, uses["floor"].deadLive) == (360, None, 240)
    assert uses["wallBrittle"].wind == 240 and uses["wallFlexible"].wind == 120
    assert uses["farm"].deadLive == 180 and uses["greenhouse"].deadLive == 120
    assert uses["metalSheeting"].deadLive == 60
    assert uses["metalRoofSecondary"].live == 150
    assert uses["metalWallSecondary"].wind == 90
    assert t.deflection.cantileverSpan == 2.0  # note c
    # Sec 1.8.4, p. 507: overturning ≤ 2/3 of the dead load resisting moment
    assert t.overturning.factorOfSafety == 1.5


def test_service_combinations_sec_2_7_5():
    rows = {r.id: r for r in code_context.table("combinations").service}
    assert rows["1"].factors == {"D": 1.0, "L": 1.0, "Lr": 1.0}
    assert rows["2"].factors == {"D": 1.0, "L": 0.5}
    assert rows["3"].factors == {"D": 1.0, "L": 0.5, "W": 0.7}
    wind = service_combinations({"D", "SD", "L", "WX", "WY"}, "3")
    assert len(wind) == 4  # ±WX, ±WY
    _name, factors, _row = wind[0]
    assert factors == {"D": 1.0, "SD": 1.0, "L": 0.5, "WX": 0.7}


def test_storey_drift_limit_by_period():
    assert sv.storey_drift_limit(0.5)[0] == 0.005
    assert sv.storey_drift_limit(0.7)[0] == 0.004
    assert sv.storey_drift_limit(1.2)[0] == 0.004
    assert sv.storey_drift_limit(None)[0] == 0.004
    assert sv.storey_drift_limit(0.3, unreinforced_masonry=True)[0] == 0.0025


def test_sway_basis_is_h_over_500_at_0_7w():
    ratio, factor, _clause = sv.sway_basis()
    assert ratio == pytest.approx(0.002)
    assert factor == pytest.approx(0.7)


def test_base_shear_periods():
    summary = {"periodUsed_s": 0.9, "seismic": {"EY": {"period_s": 0.6}}}
    assert sv.base_shear_periods(summary) == {"X": 0.9, "Y": 0.6}
    assert sv.base_shear_periods({}) == {"X": None, "Y": None}


def test_overturning_eq_6_1_1_and_factor_of_safety():
    levels = [0.0, 3.0, 6.0]
    forces = np.array([0.0, 10e3, 20e3])
    assert sv.base_overturning(forces, levels) == pytest.approx(10e3 * 3 + 20e3 * 6)
    # Two supports 10 m apart, 100 kN each: about either edge 100 kN × 10 m = 1000 kN·m.
    supports = [(0.0, 0.0, 100e3), (10.0, 0.0, 100e3)]
    assert sv.resisting_moment(supports, 0) == pytest.approx(1000e3)
    out = sv.overturning_checks({"WX": forces}, levels, supports)
    (row,) = out["rows"]
    assert row["factor"] == pytest.approx(1000e3 / 150e3)
    assert row["required"] == 1.5 and row["ok"]
    out = sv.overturning_checks({"EX": forces * 6}, levels, supports)
    assert not out["rows"][0]["ok"]  # 1000 / 900 < 1.5


def _beam(deflection_mid: dict[str, float], length: float = 6.0):
    s = np.array([0.0, length / 2, length])
    axis = np.array([1.0, 0.0, 0.0])
    profiles = {}
    for case, d in deflection_mid.items():
        moved = np.zeros((3, 3))
        moved[1, 1 if case.startswith("W") else 2] = -d
        profiles[case] = moved
    return s, axis, profiles


def test_steel_floor_beam_deflection_table_6_1_2():
    s, axis, profiles = _beam({"D": 0.010, "L": 0.010})
    rows = {r["name"]: r for r in deflection_checks(s, axis, profiles)}
    live = rows["Deflection: live load ≤ l/360"]
    assert live["capacity"] == pytest.approx(6000 / 360, abs=0.01)
    assert live["demand"] == pytest.approx(10.0)
    assert live["ok"]
    total = rows["Deflection: dead + live load ≤ l/240"]
    assert total["capacity"] == pytest.approx(25.0)
    assert total["demand"] == pytest.approx(20.0)
    assert not any("wind" in n for n in rows)  # floors have no W limit


def test_girt_wind_limit_and_cantilever_span():
    s, axis, profiles = _beam({"D": 0.0, "WX": 0.080})
    (row,) = deflection_checks(s, axis, profiles, "metalWallSecondary")
    assert row["capacity"] == pytest.approx(6000 / 90, abs=0.01)
    assert not row["ok"]
    s, axis, profiles = _beam({"D": 0.0, "L": 0.010}, length=2.0)
    profiles["L"][2, 2] = -0.010  # the free end
    rows = deflection_checks(s, axis, profiles, "floor", "end")
    live = next(r for r in rows if "live load ≤" in r["name"])
    assert live["capacity"] == pytest.approx(2 * 2000 / 360, abs=0.01)  # note c: l = 2 × length


def test_wind_checks_drift_and_sway():
    nodes = [
        {"id": 1, "coords": [0, 0, 0], "restraint": [1] * 6},
        {"id": 2, "coords": [0, 0, 3]},
        {"id": 3, "coords": [0, 0, 6]},
    ]
    project = {"nodes": nodes, "elements": []}
    index = {1: 0, 2: 1, 3: 2}
    wx = np.zeros((3, 6))
    wx[1, 0], wx[2, 0] = 0.010, 0.025  # under 1.0 WX
    arrays = {"D": np.zeros((3, 6)), "WX": wx}
    out = sv.wind_checks(project, arrays, index, [0.0, 3.0, 6.0], {"X": 0.5, "Y": 0.5})
    drift = [r for r in out["drift"] if r["direction"] == "X"]
    top = max(drift, key=lambda r: r["drift"])
    assert top["drift"] == pytest.approx(0.7 * 0.015 / 3)
    assert top["limit"] == 0.005 and top["ok"]
    sway = max(out["sway"], key=lambda r: r["ratio"])
    assert sway["ratio"] == pytest.approx(0.7 * 0.025 / 6)
    assert sway["limit"] == pytest.approx(0.002) and not sway["ok"]
