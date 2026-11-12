"""Electrical demand and supply sizing (BNBC 2020 Part 8 Sec 1.3.2, 1.3.18), by hand on the
synthetic eight-storey office of the verification pack."""

from __future__ import annotations

import math

import pytest

from saengine.electrical import tables as T
from saengine.electrical.demand import demand, hvac_loads
from saengine.electrical.supply import substation_area, substation_required, transformers
from saengine.library.mep import MepModel
from saengine.plumbing.building import Building
from saengine.verification.cases.electrical import (
    eight_storey,
    eight_storey_bim,
    eight_storey_electrical,
)


def _mep(**changes) -> MepModel:
    electrical = {**eight_storey_electrical(), **changes}
    return MepModel.model_validate({"schema": "saengine.mep/1", "electrical": electrical})


def test_demand_of_the_eight_storey_office() -> None:
    mep, bim, _ = eight_storey()
    d = demand(mep.electrical, Building.of(bim))
    # 8 floors x 600 m² x 75 W/m² (Table 8.1.17, office, A/C) + lifts 2 x 15 + pumps 2 x 5.5.
    assert d["storiesKw"] == pytest.approx(360.0)
    assert d["motorsKw"] == pytest.approx(41.0)
    assert d["connected"] == pytest.approx(401.0)
    assert d["maximumDemand"] == pytest.approx(0.8 * 401.0)
    assert d["kva"] == pytest.approx(0.8 * 401.0 / 0.85)
    assert d["current"] == pytest.approx(0.8 * 401.0 / 0.85 * 1000 / (math.sqrt(3) * 400))
    first = d["stories"][0]
    assert first["area"] == pytest.approx(600.0)
    assert first["density"] == 75
    assert first["demand"] == pytest.approx(0.8 * 45.0)


def test_entered_loads_below_the_minimum_density_are_raised() -> None:
    stories = [{"story": "L1", "use": "office", "lighting": 10, "power": 8}]
    mep = _mep(stories=stories, motors=[])
    d = demand(mep.electrical, Building.of(eight_storey_bim()))
    s = d["stories"][0]
    assert s["density"] == 28  # non-A/C office minimum
    assert "below the minimum" in s["notes"][0]
    stories = [{"story": "L1", "use": "office", "lighting": 15, "power": 40, "other": 12}]
    d = demand(_mep(stories=stories, motors=[]).electrical, Building.of(eight_storey_bim()))
    assert d["connected"] == pytest.approx(55 * 600 / 1000 + 12)


def test_hvac_plant_replaces_the_ac_column() -> None:
    mep = _mep(motors=[])
    hvac = [{"id": "CH1", "kind": "chiller", "story": "ROOF", "kw": 100.0, "note": "entered"}]
    d = demand(mep.electrical, Building.of(eight_storey_bim()), hvac=hvac)
    assert d["stories"][0]["density"] == 28
    assert d["connected"] == pytest.approx(8 * 600 * 28 / 1000 + 100.0)


def test_only_the_stories_a_cooling_source_serves_leave_the_ac_column() -> None:
    mep = _mep(motors=[])
    building = Building.of(eight_storey_bim())
    # A fan is no cooling source: every story keeps 75 W/m², the fan adds 1.0 x 1.5 kW.
    fan = [{"id": "EF1", "kind": "exhaustFan", "story": "ROOF", "kw": 1.5, "note": "e"}]
    d = demand(mep.electrical, building, hvac=fan)
    assert d["storiesKw"] == pytest.approx(360.0)
    assert d["connected"] == pytest.approx(361.5)
    # AHUs and FCUs (chilled water from elsewhere) do not carry the cooling either.
    ahu = [{"id": "AH1", "kind": "ahu", "story": "L1", "kw": 5.0, "note": "e"}]
    assert demand(mep.electrical, building, hvac=ahu)["storiesKw"] == pytest.approx(360.0)
    # A VRF outdoor unit serving L1 and L2: those two at 28 W/m², the other six at 75.
    vrf = [{"id": "V1", "kind": "vrfOutdoor", "story": "ROOF", "kw": 30.0, "note": "e",
            "serves": ["L1", "L2"]}]  # fmt: skip
    d = demand(mep.electrical, building, hvac=vrf)
    density = {s["story"]: s["density"] for s in d["stories"]}
    assert density["L1"] == density["L2"] == 28
    assert density["GF"] == density["L7"] == 75
    assert d["storiesKw"] == pytest.approx((2 * 28 + 6 * 75) * 600 / 1000)
    # Without serves a split unit cools only its own story (and a note asks for serves).
    split = [{"id": "SP1", "kind": "splitOutdoor", "story": "L3", "kw": 4.0, "note": "e"}]
    d = demand(mep.electrical, building, hvac=split)
    assert d["storiesKw"] == pytest.approx((28 + 7 * 75) * 600 / 1000)
    assert any("SP1: no 'serves'" in n for n in d["notes"])
    # A cooling source with no load (no capacity) never moves a story.
    none = [{"id": "CH9", "kind": "chiller", "story": "ROOF", "kw": 0.0, "note": "e"}]
    assert demand(mep.electrical, building, hvac=none)["storiesKw"] == pytest.approx(360.0)


def test_hvac_plant_from_mep_json_serves() -> None:
    raw = eight_storey_electrical()
    data = {"schema": "saengine.mep/1", "electrical": {**raw, "motors": []}, "hvac": {
        "system": "vrf",
        "plant": [{"id": "V1", "kind": "vrfOutdoor", "story": "ROOF", "x": 5000, "y": 5000,
                   "capacity": 35.0, "serves": ["L1"]}]}}  # fmt: skip
    mep = MepModel.model_validate(data)
    loads = hvac_loads(mep)
    assert loads[0]["serves"] == ["L1"] and loads[0]["kw"] == pytest.approx(10.0)
    d = demand(mep.electrical, Building.of(eight_storey_bim()), mep)
    assert d["storiesKw"] == pytest.approx((28 + 7 * 75) * 600 / 1000)
    assert d["connected"] == pytest.approx(d["storiesKw"] + 10.0)


def test_hvac_loads_from_a_raw_hvac_section() -> None:
    raw = {"hvac": {"plant": [
        {"id": "CH1", "kind": "chiller", "capacity": 600},
        {"id": "CT1", "kind": "coolingTower", "capacity": 700},
        {"id": "EF1", "kind": "exhaustFan", "capacity": 2},
        {"id": "AH1", "kind": "ahu", "capacity": 100, "power": 7.5},
    ]}}  # fmt: skip
    loads = {h["id"]: h["kw"] for h in hvac_loads(raw)}
    assert loads["CH1"] == pytest.approx(600 / 5.0)  # water cooled: there is a tower
    assert loads["CT1"] == pytest.approx(7.0)
    assert loads["EF1"] == pytest.approx(3.0)
    assert loads["AH1"] == pytest.approx(7.5)
    assert hvac_loads({}) == []


def test_transformer_pick_and_table_8_1_23() -> None:
    tx = transformers(377.4)
    assert (tx["count"], tx["rating"]) == (1, 400)
    assert (tx["transformerArea"], tx["substationArea"]) == (13, 48)
    tx = transformers(2100)
    assert tx["count"] == 2 and tx["rating"] == 1250
    assert transformers(1200, count=2)["rating"] == 630
    assert substation_area(2, 630) == (26, 100, "2 x 630")
    assert substation_area(1, 630) is None  # Table 8.1.23 has no 1 x 630 row
    assert substation_required(50.0) and not substation_required(49.9)
    assert T.SUBSTATION_KW == 50


def test_stories_without_a_row_take_the_building_use() -> None:
    # E1: only one story entered; the other seven below the roof drew nothing before.
    stories = [{"story": "L1", "use": "office"}]
    mep = _mep(stories=stories, motors=[])
    building = Building.of(eight_storey_bim())
    d = demand(mep.electrical, building, default_use="residenceMulti")
    rows = {s["story"]: s for s in d["stories"]}
    assert len(rows) == 8 and "ROOF" not in rows
    assert rows["L1"]["use"] == "office" and rows["L1"]["useSource"] == "entered"
    assert rows["GF"]["use"] == "residenceMulti"
    assert rows["GF"]["useSource"] == "02 Project Settings building use"
    assert d["storiesKw"] == pytest.approx((28 + 7 * 20) * 600 / 1000)
    assert any("02 Project Settings" in n for n in d["notes"])
    # Without a building use, the old rule: the missing stories draw nothing, with a note.
    d = demand(mep.electrical, building)
    assert len(d["stories"]) == 1
    assert any("draw nothing" in n for n in d["notes"])


def test_a_row_without_its_own_use_takes_the_building_use() -> None:
    mep = _mep(stories=[{"story": "L1", "lighting": 8}], motors=[])
    d = demand(mep.electrical, Building.of(eight_storey_bim()), default_use="residenceMulti")
    l1 = next(s for s in d["stories"] if s["story"] == "L1")
    assert l1["use"] == "residenceMulti"


def test_blank_power_takes_the_rest_of_the_table_density() -> None:
    # Lighting 10 entered, power blank: power and sockets = 28 - 10 = 18 W/m² (Table 8.1.17).
    mep = _mep(stories=[{"story": "L1", "use": "office", "lighting": 10}], motors=[])
    s = demand(mep.electrical, Building.of(eight_storey_bim()))["stories"][0]
    assert s["lighting"] == 10 and s["power"] == 18 and s["density"] == 28
    parts = {p["part"]: p for p in s["breakdown"]}
    assert parts["power"]["kw"] == pytest.approx(18 * 600 / 1000)
    assert "Table 8.1.17" in parts["power"]["source"]
    assert not s["notes"]
    # Lighting at or above the table total: power cannot be inferred, the engineer is told.
    mep = _mep(stories=[{"story": "L1", "use": "office", "lighting": 30}], motors=[])
    s = demand(mep.electrical, Building.of(eight_storey_bim()))["stories"][0]
    assert s["power"] == 0 and s["density"] == 30
    assert "power and socket-outlet" in s["notes"][0]


def test_the_breakdown_adds_up_to_the_connected_load() -> None:
    building = Building.of(eight_storey_bim())
    cases = [
        {"story": "L1", "use": "office", "airConditioned": True},
        {"story": "L1", "use": "office", "airConditioned": True, "lighting": 12, "power": 30},
        {"story": "L1", "use": "school", "lighting": 4, "power": 2, "other": 7},
        {"story": "L1", "use": "hospital", "power": 50},
    ]
    for row in cases:
        s = demand(_mep(stories=[row], motors=[]).electrical, building)["stories"][0]
        assert sum(p["kw"] for p in s["breakdown"]) == pytest.approx(s["connected"]), row
    s = demand(_mep(stories=[cases[0]], motors=[]).electrical, building)["stories"][0]
    parts = {p["part"]: p["density"] for p in s["breakdown"]}
    assert parts == {"lightingAndPower": 28, "airConditioning": 47}
