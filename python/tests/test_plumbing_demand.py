"""Plumbing demand (BNBC 2020 Part 8 Sec 5.5-5.6, Tables 8.5.1, 8.5.5, 8.O.1): hand checks on
the synthetic six-storey residential building of ``verification.cases.plumbing``."""

from __future__ import annotations

import pytest

from saengine.library.mep import Fixtures, MepModel
from saengine.plumbing import tables as T
from saengine.plumbing.building import Building
from saengine.plumbing.demand import (
    daily_demand,
    drainage_units,
    hunter_flow,
    lpcd,
    peak_hourly,
    supply_units,
)
from saengine.verification.cases.plumbing import FLOOR, six_storey


def test_table_851_rows_are_transcribed() -> None:
    # Table 8.5.1(a) p1034: y1 moderate apartment 180 / 135; A1 single family 260 / 200.
    assert lpcd("residentialFlat")[0] == 180
    assert lpcd("residentialFlat", "restricted")[0] == 135
    assert lpcd("singleFamily")[0] == 260
    # Table 8.5.1(d) p1036: E1 offices 45 / 30, D1 big hospitals 450 / 250, A5 hotel 300.
    assert lpcd("office")[0] == 45 and lpcd("office", "restricted")[0] == 30
    assert lpcd("hospitalLarge")[0] == 450
    assert lpcd("hotel")[0] == 300
    # p1037: M2 fences, tanks and towers: only restricted, 3.
    value, _, notes = lpcd("tanksTowers")
    assert value == 3 and notes


def test_daily_demand_of_the_six_storey_building() -> None:
    mep, bim = six_storey()
    demand = daily_demand(mep.plumbing, Building.of(bim))
    # 5 floors x 4 kitchen sinks (dwellings) x 5 persons (Sec 5.6.3) = 100 persons.
    assert demand["population"] == pytest.approx(100)
    # 100 x 180 lpcd = 18 000 l/day.
    assert demand["daily"] == pytest.approx(18000)
    # Eq 8.5.1: 18 000 / 16 h x 2.2 = 2475 l/h.
    assert demand["peakHourly"] == pytest.approx(2475)
    assert peak_hourly(16000) == pytest.approx(2200)


def test_population_entered_or_from_office_area() -> None:
    mep = MepModel.model_validate(
        {"plumbing": {"stories": [{"story": "L1", "occupancy": "office"}]}}
    )
    bim = six_storey()[1]
    demand = daily_demand(mep.plumbing, Building.of(bim))
    # 14 x 10 m = 140 m² / 7.4 m² per person (Sec 5.6.4) x 45 lpcd.
    assert demand["population"] == pytest.approx(140 / 7.4)
    assert demand["daily"] == pytest.approx(140 / 7.4 * 45)
    unknown = MepModel.model_validate(
        {"plumbing": {"stories": [{"story": "L1", "occupancy": "school"}]}}
    )
    result = daily_demand(unknown.plumbing, Building())
    assert result["population"] == 0
    assert any("give its population" in n for n in result["notes"])


def test_supply_units_of_a_flat() -> None:
    flat = Fixtures(wc=2, basin=2, shower=2, kitchenSink=1)
    units, minimum, _ = supply_units(flat, "total")
    # Table 8.O.1: WC flush tank 5, shower head 4, kitchen sink 2; Table 8.5.4: basin 1.
    assert units == pytest.approx(2 * 5 + 2 * 1 + 2 * 4 + 2)
    # Table 8.5.6: water closet (flush tank) and wash basin need 19 mm.
    assert minimum == 19
    cold, _, _ = supply_units(flat, "cold")
    assert cold == pytest.approx(2 * 5 + 2 * 0.75 + 2 * 3 + 1.5)
    valves, _, _ = supply_units(Fixtures(wc=1), "total", flush_valves=True)
    assert valves == 10


def test_drainage_units() -> None:
    floor = Fixtures(**FLOOR)
    soil, outlet, _ = drainage_units(floor, "soil")
    assert soil == 8 * 3 and outlet == 100  # Table 8.6.12 WC tank 3; Table 8.6.2 WC 100 mm
    waste, outlet, _ = drainage_units(floor, "waste")
    assert waste == 8 * 1 + 8 * 2 + 4 * 2 and outlet == 40
    assert drainage_units(Fixtures(washingMachine=1))[0] == 3  # Table 8.6.13, 50 mm trap


def test_hunter_flow_interpolates_table_855() -> None:
    assert hunter_flow(20) == pytest.approx(56.6)
    assert hunter_flow(440) == pytest.approx(396.4 + 0.4 * (472.9 - 396.4))
    assert hunter_flow(440, flush_valves=True) == pytest.approx(481.4 + 0.4 * (538.0 - 481.4))
    assert hunter_flow(10) == pytest.approx(56.6 / 2)
    assert hunter_flow(1000) == pytest.approx(795.7)
    assert hunter_flow(0) == 0
    assert len(T.HUNTER) == 20
