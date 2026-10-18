"""Sanitary drainage (BNBC 2020 Part 8 Sec 6.10, Tables 8.6.12-8.6.16)."""

from __future__ import annotations

from saengine.plumbing.building import Building
from saengine.plumbing.drainage import (
    branch_size,
    building_drains,
    drain_size,
    soil_stack,
    stack_size,
    vent_size,
    vent_stack,
)
from saengine.verification.cases.plumbing import six_storey


def test_table_8614() -> None:
    # Up to three storeys: "one stack of 3 storeys": 75 mm takes 30, 100 mm 240.
    assert stack_size(30, 10, 3, 0) == 75
    assert stack_size(31, 10, 3, 0) == 100
    # More than three: the total and the per-storey limit: 75 mm 60 / 16.
    assert stack_size(60, 16, 5, 0) == 75
    assert stack_size(60, 17, 5, 0) == 100
    assert stack_size(60, 12, 5, 100) == 100  # a water closet's 100 mm outlet
    assert branch_size(20, 0) == 75 and branch_size(21, 0) == 100


def test_stacks_of_the_six_storey_building() -> None:
    mep, bim = six_storey()
    building = Building.of(bim)
    risers = {r.id: r for r in mep.plumbing.risers}
    s1 = soil_stack(risers["S1"], mep.plumbing, building)
    # 4 WC x 3 = 12 units a floor (8 WC shared by S1, S2), 5 floors = 60; 100 mm for the WC.
    assert s1["units"] == 60 and s1["maxStoreyUnits"] == 12 and s1["storeys"] == 5
    assert s1["diameter"] == 100 and s1["ok"]
    w1 = soil_stack(risers["W1"], mep.plumbing, building)
    # 4 basins x 1 + 4 showers x 2 + 2 sinks x 2 = 16 a floor, 80 in all: 75 mm takes 60.
    assert w1["units"] == 80 and w1["diameter"] == 100
    small = soil_stack(risers["S1"].model_copy(update={"diameter": 75}), mep.plumbing, building)
    assert not small["ok"]
    vent = vent_stack(risers["V1"], [s1, w1], mep.plumbing, building)
    # Table 8.6.16, 100 mm stack, 140 units row: 65 mm vent reaches 19.5 m >= 18 m.
    assert vent["vents"] == "S1" and vent["length"] == 18.0
    assert vent["diameter"] == 65


def test_vent_and_building_drain() -> None:
    assert vent_size(100, 60, 18) == 65
    assert vent_size(100, 60, 20) == 75
    assert vent_size(100, 600, 10) is None  # beyond the 540-unit row
    # Table 8.6.15: 100 mm at 1/100 takes 180 units, at 1/200 nothing.
    assert drain_size(180, 0.01) == (100, 0.01)
    assert drain_size(181, 0.01) == (150, 0.01)
    assert drain_size(180, 0.005)[0] == 200
    assert drain_size(10, 0.004) == (None, None)
    mep, _ = six_storey()
    drains = {d["name"]: d for d in building_drains(mep.plumbing)}
    # Septic disposal: soil (120) and sullage (160) apart (Sec 6.9.12.4).
    assert drains["soil"]["units"] == 120 and drains["soil"]["diameter"] == 100
    assert drains["waste"]["units"] == 160 and drains["waste"]["diameter"] == 100
