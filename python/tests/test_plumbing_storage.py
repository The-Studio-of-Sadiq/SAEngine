"""Water storage (BNBC 2020 Part 8 Sec 5.9, Tables 8.5.2-8.5.3, Part 4 Table 4.4.1)."""

from __future__ import annotations

import pytest

from saengine.library.bim import BuildingModel
from saengine.library.mep import MepModel, PlumbingTank
from saengine.plumbing.building import Building
from saengine.plumbing.storage import (
    dimensions,
    fire_reserve,
    tank_drain,
    tank_overflow,
    volumes,
    water_weight,
)
from saengine.verification.cases.plumbing import six_storey


def test_volumes_of_the_six_storey_building() -> None:
    mep, bim = six_storey()
    vol = volumes(mep.plumbing, Building.of(bim), 18000)
    # Sec 5.9.1.2(c): roof tank 1/2 x 18 m³, reservoir 1 x 18 m³; top floor 15 m < 33 m.
    assert vol["fireReserve"] == 0
    assert vol["overhead"] == pytest.approx(9.0)
    assert vol["underground"] == pytest.approx(18.0)


def test_fire_reserve_of_a_tall_building() -> None:
    stories = [{"id": f"L{i}", "name": f"L{i}", "elevation": 3000 * i} for i in range(13)]
    bim = BuildingModel.model_validate({"stories": stories})
    mep = MepModel.model_validate({"plumbing": {"stories": [{"story": "L12", "population": 20}]}})
    reserve, notes = fire_reserve(mep.plumbing, Building.of(bim))
    # L12 at 36 m > 33 m (Part 3 Sec 2.4.4); A3 flats: light hazard-I, standpipe 1000 l/min
    # (Part 4 Table 4.4.1) for 1 hour = 60 m³.
    assert reserve == pytest.approx(60.0)
    assert any("Table 4.4.1" in n for n in notes)
    vol = volumes(mep.plumbing, Building.of(bim), 3600)
    assert vol["overhead"] == pytest.approx(1.8 + 60)
    assert vol["underground"] == pytest.approx(3.6 + 60)
    # Table 4.4.1 note **: one riser serves 1000 m². A 50 x 30 m floor (1500 m²) needs two:
    # 2 x 1000 l/min x 60 min = 120 m³.
    big = BuildingModel.model_validate({
        "stories": stories,
        "elements": [{"id": "S12", "type": "SL150", "kind": "slab", "elevation": 36000,
                      "boundary": [[0, 0], [50000, 0], [50000, 30000], [0, 30000]]}],
    })  # fmt: skip
    reserve, notes = fire_reserve(mep.plumbing, Building.of(big))
    assert reserve == pytest.approx(120.0)
    assert any("2 riser(s)" in n for n in notes)
    entered = MepModel.model_validate({"plumbing": {"supply": {"fireReserve": 25}}})
    assert fire_reserve(entered.plumbing, Building())[0] == 25


def test_drain_and_overflow_pipes() -> None:
    # Table 8.5.2 (p1042).
    assert tank_drain(2800) == 25
    assert tank_drain(9000) == 50
    assert tank_drain(18000) == 63
    assert tank_drain(30000) == 100
    # Table 8.5.3 (p1042).
    assert tank_overflow(41.25) == 50
    assert tank_overflow(600) == 75
    assert tank_overflow(4000) == 200


def test_proposed_dimensions() -> None:
    # 9 m³ at 1.5 m: 6 m² in two square compartments: W = sqrt(3) = 1.732 -> 1.75 m,
    # L = 6 / 1.75 + the 200 mm partition (1.8 m high / 12, at least 200) = 3.63 -> 3.65 m.
    dims = dimensions(9.0, "overhead")
    assert (dims["width"], dims["length"], dims["waterDepth"]) == (1750, 3650, 1500)
    assert dims["compartments"] == 2 and dims["freeboard"] == 300
    assert dims["volume"] >= 9.0
    # Length and width given: the depth follows, the 200 mm partition taking its share of the
    # plan: 9 m³ / ((3 - 0.2) x 2) = 1.607 -> 1.61 m.
    tank = PlumbingTank(id="T", kind="overhead", x=0, y=0, length=3000, width=2000)
    dims = dimensions(9.0, "overhead", tank)
    assert dims["waterDepth"] == pytest.approx(1610)
    assert dims["volume"] == pytest.approx(2.8 * 2.0 * 1.61)
    assert water_weight(dims) == pytest.approx(2.8 * 2.0 * 1.61 * 9.81)
    single = dimensions(9.0, "overhead", PlumbingTank(id="T", kind="overhead", x=0, y=0,
                                                      compartments=1))  # fmt: skip
    assert single["notes"]
