"""Septic tank and soak well (BNBC 2020 Part 8 Sec 6.9.12-6.9.15, Appendix S, Tables
8.6.8-8.6.10)."""

from __future__ import annotations

import pytest

from saengine.library.mep import MepModel, PlumbingTank
from saengine.library.soil import SoilReport
from saengine.plumbing.building import Building
from saengine.plumbing.septic import (
    allowance,
    separations,
    septic_tank,
    soak_well,
    soil_percolation,
    volume,
)
from saengine.verification.cases.plumbing import six_storey


def test_septic_tank_of_the_six_storey_building() -> None:
    mep, bim = six_storey()
    tank = septic_tank(mep.plumbing, Building.of(bim))
    # Eq 8.S.1: 100 x 120 x 1 + 100 x 40 x 1 = 16 000 l.
    assert tank["persons"] == 100 and tank["flow"] == 120
    assert tank["volume"] == pytest.approx(16000)
    # D = (16 / 3)^(1/3) = 1.747 -> 1.75 m; B = sqrt(16 / (3 x 1.75)) = 1.746 -> 1.75 m;
    # L = 3 B = 5.25 m; two chambers above 3000 l, inlet 2/3 L = 3.5 m.
    assert (tank["waterDepth"], tank["width"], tank["length"]) == (1750, 1750, 5250)
    assert tank["compartments"] == 2 and tank["inletLength"] == pytest.approx(3500)
    assert tank["count"] == 1


def test_minimum_volume_and_many_users() -> None:
    assert volume(5, 120, 1, 1) == 2000  # Sec 6.9.12.8
    mep = MepModel.model_validate({"plumbing": {"stories": [{"story": "L1", "population": 450}]}})
    tank = septic_tank(mep.plumbing, Building())
    # 450 residential users > 300: an Imhoff tank shall be used (Sec 6.9.13.2), no septic tank.
    assert tank["imhoff"] and tank["count"] == 0 and tank["residential"] == 450
    users_check = next(c for c in tank["checks"] if c[0] == "Residential users of a septic tank")
    assert users_check[1:3] == (450, 300)
    # Other occupancies: BNBC sets no cap, SAEngine splits into tanks of at most 300 users.
    shops = MepModel.model_validate(
        {"plumbing": {"stories": [{"story": "L1", "occupancy": "office", "population": 900}]}}
    )
    split = septic_tank(shops.plumbing, Building())
    assert not split["imhoff"] and split["persons"] == 450 and split["count"] == 2
    office = MepModel.model_validate(
        {"plumbing": {"stories": [{"story": "L1", "occupancy": "office", "population": 100}]}}
    )
    # Table 8.S.1 (xi): office staff x 0.5 at 120 lpcd.
    assert septic_tank(office.plumbing, Building())["persons"] == pytest.approx(50)


def test_soak_well() -> None:
    septic = {"volume": 16000.0, "daily": 12000.0}
    tank = PlumbingTank(id="SW", kind="soakWell", x=0, y=0, diameter=2000, percolation=5)
    well = soak_well(septic, tank)
    # Table 8.6.10, 5 min: 128 l/m²/day; 12 000 / 128 = 93.75 m² of wall; capacity 2 x 16 m³.
    assert well["allowance"] == 128 and well["area"] == pytest.approx(93.75)
    assert well["capacity"] == pytest.approx(32.0)
    # 93.75 / (pi x 2) = 14.9 m of depth, at most 6 m each: 3 wells of 5.0 m.
    assert well["count"] == 3 and well["waterDepth"] == 5000
    assert allowance(2) == 172 and allowance(30) == 44 and allowance(61) is None


def test_soak_well_from_the_soil_report() -> None:
    soil = SoilReport.model_validate({
        "boreholes": [{
            "id": "BH-1", "waterTable": 1500,
            "layers": [
                {"top": 0, "bottom": 1500, "soilType": "fill"},
                {"top": 1500, "bottom": 6000, "soilType": "clay", "uscs": "CL"},
            ],
        }],
    })  # fmt: skip
    rate, water_table, note = soil_percolation(soil)
    assert rate == 60 and water_table == 1500 and "BH-1" in note
    well = soak_well({"volume": 16000.0, "daily": 12000.0}, None, soil)
    # The water table at 1.5 m leaves no depth (bottom 1 m above it, Sec 6.9.15.4).
    assert not well["ok"]
    sand = SoilReport.model_validate({
        "boreholes": [{"id": "B", "layers": [{"top": 0, "bottom": 4000, "soilType": "sand",
                                              "uscs": "SM"}]}],
    })  # fmt: skip
    assert soil_percolation(sand)[0] == 10  # silty sand


def test_separations() -> None:
    mep, bim = six_storey()
    building = Building.of(bim)
    dims = {"T2": {"length": 4200, "width": 2150}, "T3": {"length": 5250, "width": 1750}}
    checks = {c["name"]: c for c in separations(mep.plumbing, building, dims)}
    # T3 (11 m, -15 m), 5.25 x 1.75 m: its top edge at y = -14.125 m, the building at 0.
    assert checks["T3 to building"]["capacity"] == pytest.approx(14.125)
    assert checks["T3 to T2"]["ok"]  # 7.5 m from a reservoir, Table 8.6.9
    # T4 (Ø2 m at y = -22 m) to the reservoir T2: Table 8.6.8 well 15 m.
    assert checks["T4 to T2"]["demand"] == 15
    near = mep.plumbing.model_copy(update={"tanks": [
        t.model_copy(update={"y": -2000}) if t.id == "T3" else t for t in mep.plumbing.tanks
    ]})  # fmt: skip
    checks = {c["name"]: c for c in separations(near, building, dims)}
    assert not checks["T3 to T2"]["ok"]


def test_septic_tank_under_the_building_fails_the_separation() -> None:
    # Table 8.6.8 (p1106) / 8.6.9 (p1108): 1.5 m from the building; a tank inside the 14 x 10 m
    # footprint is 0 m from it.
    mep, bim = six_storey()
    data = mep.plumbing.model_dump(mode="json", exclude_none=True)
    for t in data["tanks"]:
        if t["id"] == "T3":
            t.update({"x": 7000, "y": 5000, "length": 5250, "width": 1750})
    model = MepModel.model_validate({"plumbing": data}).plumbing
    checks = {c["name"]: c for c in separations(model, Building.of(bim), {})}
    assert checks["T3 to building"]["capacity"] == 0 and not checks["T3 to building"]["ok"]
