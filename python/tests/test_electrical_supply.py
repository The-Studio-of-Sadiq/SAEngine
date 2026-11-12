"""Standby generator, fuel, UPS and the typical equipment (BNBC 2020 Part 8 Sec 1.3.19)."""

from __future__ import annotations

import pytest

from saengine.electrical import tables as T
from saengine.electrical.supply import (
    capacitor_kvar,
    fuel_tank,
    generator,
    generator_area,
    lift_standby_required,
    typical_generator,
    typical_transformer,
    ups,
)
from saengine.verification.cases.electrical import results


def test_generator_and_fuel_of_the_eight_storey_office() -> None:
    gen = results()["supply"]["generator"]
    # Lifts 30 + pumps 11 + 0.25 x 360 = 131 kW; 131 / 0.8 = 163.75 kVA -> 200 kVA.
    assert gen["essential"]["kw"] == pytest.approx(131.0)
    assert gen["kva"] == 200
    assert gen["kw"] == pytest.approx(160.0)
    assert gen["fuel"] == pytest.approx(160 * 8 * 0.27)
    tank = gen["tank"]
    assert tank["volume"] == pytest.approx(0.3456 * 1.1)
    assert tank["fuelWeight"] == pytest.approx(0.3456 * 840 * 9.81 / 1000)
    assert gen["roomArea"] == 48  # Table 8.1.24, the 1 x 300 kW row


def test_fuel_tank_steel_and_size() -> None:
    tank = fuel_tank(1000.0)
    assert tank["height"] == 1000.0
    assert tank["length"] == 1050.0  # sqrt(1.1 m³ / 1 m) = 1049 mm -> 1050
    surface = 2 * 1.05**2 + 4 * 1.05 * 1.0
    assert tank["emptyWeight"] == pytest.approx(surface * 0.005 * 78.5)


def test_generator_table_and_lifts_rule() -> None:
    assert generator_area(25) == (20, "1 x 25 kW")
    assert generator_area(301) == (56, "1 x 500 kW")
    assert generator_area(501) is None
    assert generator(0)["kva"] is None
    assert generator(1300)["note"]  # beyond the largest set listed
    assert not lift_standby_required(10, 31.9, False)
    assert lift_standby_required(11, 30, False)
    assert lift_standby_required(8, 32.5, False)
    assert lift_standby_required(3, 10, True)


def test_ups_capacitor_and_typical_units() -> None:
    u = ups(18.0)
    assert u["kva"] == 20 and u["autonomy"] == 15
    assert u["energy"] == pytest.approx(18 * 15 / 60 / 0.9)
    assert ups(None) is None
    assert capacitor_kvar(100, 0.85) == pytest.approx(100 * (0.6197 - 0.3287), abs=0.05)
    assert capacitor_kvar(100, 0.97) == 0
    tx = typical_transformer(400)
    assert tx["oil"] == 550 and tx["operatingWeight"] == pytest.approx(1800 * 9.81 / 1000, 0.01)
    assert typical_transformer(400, "dry")["oil"] == 0
    assert typical_generator(163)["length"] == T.GENERATOR_SETS[200][0]


def test_proposed_equipment_is_typical_and_vibrating() -> None:
    proposals = {p["id"]: p for p in results()["equipment"]}
    assert {"TX1", "HT1", "LT1", "GEN1", "FT1"} <= set(proposals)
    assert proposals["GEN1"]["vibrating"] is True
    assert all(p["sized"] and "(typical)" in p["name"] for p in proposals.values())
    assert proposals["TX1"]["story"] == "GF"
    assert proposals["LT1"]["rating"] == round(400 * 1000 / (3**0.5 * 400))
