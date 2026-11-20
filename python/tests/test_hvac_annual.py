"""R10 annual energy simulation (epJSON, schedules, meters, EUI) and envelope compliance tests.

All tests are self-contained and do NOT invoke EnergyPlus.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from saengine.hvac import energyplus as EP
from saengine.hvac import tables as T
from saengine.hvac.compliance import building_wwr, check_envelope_compliance
from saengine.hvac.constructions import envelope as envelope_choice
from saengine.hvac.gains import design_conditions, single_room_gains, zone_gains
from saengine.hvac.geometry import zones as make_zones
from saengine.hvac.report import hvac_results
from saengine.library import architecture as arch_lib
from saengine.library.bim import BuildingModel
from saengine.library.mep import MepModel
from saengine.mep.rooms import room_inputs
from saengine.plumbing.building import Building


def _box_bim(w_mm: float = 20000.0, d_mm: float = 10000.0, h_mm: float = 3000.0) -> BuildingModel:
    outline = [[0.0, 0.0], [w_mm, 0.0], [w_mm, d_mm], [0.0, d_mm]]
    return BuildingModel.model_validate(
        {
            "stories": [
                {"id": "GF", "name": "GF", "elevation": 0.0},
                {"id": "ROOF", "name": "ROOF", "elevation": h_mm},
            ],
            "elements": [
                {
                    "id": "S-ROOF",
                    "type": "SL150",
                    "kind": "slab",
                    "elevation": h_mm,
                    "boundary": outline,
                }
            ],
        }
    )


def _two_room_arch_and_bim() -> tuple[arch_lib.Architecture, BuildingModel]:
    outline = [[0.0, 0.0], [20000.0, 0.0], [20000.0, 10000.0], [0.0, 10000.0]]
    bim = _box_bim(20000.0, 10000.0, 3000.0)
    lines = [
        ([0.0, 0.0], [20000.0, 0.0]),
        ([20000.0, 0.0], [20000.0, 10000.0]),
        ([20000.0, 10000.0], [0.0, 10000.0]),
        ([0.0, 10000.0], [0.0, 0.0]),
        ([10000.0, 0.0], [10000.0, 10000.0]),
    ]
    arch = arch_lib.Architecture.model_validate(
        {
            "separators": [
                {"id": f"S{i}", "story": "GF", "start": a, "end": b}
                for i, (a, b) in enumerate(lines)
            ],
            "rooms": [
                {
                    "story": "GF",
                    "id": "R1",
                    "name": "Office",
                    "point": [5000.0, 5000.0],
                    "occupancy": "office",
                },
                {
                    "story": "GF",
                    "id": "R2",
                    "name": "Cafeteria",
                    "point": [15000.0, 5000.0],
                    "occupancy": "dining",
                },
            ],
        }
    )
    assert len(outline) == 4
    return arch, bim


def test_annual_epjson_has_run_period_zone_schedules_and_meters() -> None:
    arch, bim = _two_room_arch_and_bim()
    rooms = room_inputs(arch, bim)
    mep = MepModel.model_validate(
        {"hvac": {"system": "vrf", "stories": [{"story": "GF", "use": "officeSpace"}]}}
    )
    zoning = make_zones(Building.of(bim), mep.hvac, rooms=rooms, by_room=True, arch=arch)
    story_rooms = rooms.story("GF")
    room_by_id = {r.id: r for r in story_rooms.rooms}
    gains = {
        z.name: single_room_gains(z, room_by_id[z.room], mep.hvac, story_rooms)
        for z in zoning.zones
    }
    model = EP.build(
        zoning.zones,
        gains,
        envelope_choice(mep.hvac.envelope),
        design_conditions(mep.hvac, "dhaka"),
        annual=True,
        system=mep.hvac.system,
    )
    ep = model.epjson
    assert model.annual is True
    assert (
        ep["SimulationControl"]["SimulationControl 1"][
            "run_simulation_for_weather_file_run_periods"
        ]
        == "Yes"
    )
    rp = ep["RunPeriod"]["Annual"]
    assert (rp["begin_month"], rp["begin_day_of_month"]) == (1, 1)
    assert (rp["end_month"], rp["end_day_of_month"]) == (12, 31)

    compacts = ep["Schedule:Compact"]
    for z in zoning.zones:
        occ = f"{z.name} occupancy schedule"
        lgt = f"{z.name} lighting schedule"
        eqp = f"{z.name} equipment schedule"
        assert occ in compacts and lgt in compacts and eqp in compacts
        assert ep["People"][f"{z.name} people"]["number_of_people_schedule_name"] == occ
        assert ep["Lights"][f"{z.name} lights"]["schedule_name"] == lgt
        assert ep["ElectricEquipment"][f"{z.name} equipment"]["schedule_name"] == eqp

    meters = {m["key_name"] for m in ep["Output:Meter"].values()}
    assert {
        "Electricity:Facility",
        "InteriorLights:Electricity",
        "InteriorEquipment:Electricity",
        "Cooling:EnergyTransfer",
        "Heating:EnergyTransfer",
    } <= meters


def test_annual_run_missing_epw_gives_clear_message(tmp_path: Path) -> None:
    bim = _box_bim()
    mep = MepModel.model_validate({"hvac": {"stories": [{"story": "GF"}]}})
    zoning = make_zones(Building.of(bim), mep.hvac)
    gains = {z.name: zone_gains(z, mep.hvac) for z in zoning.zones}
    model = EP.build(
        zoning.zones,
        gains,
        envelope_choice(mep.hvac.envelope),
        design_conditions(mep.hvac, "dhaka"),
        annual=True,
    )
    fake_exe = tmp_path / EP.EXE
    fake_exe.write_text("", encoding="utf-8")

    with pytest.raises(EP.EnergyPlusError, match="EPW weather file"):
        EP.run(model, fake_exe, epw=None)
    with pytest.raises(EP.EnergyPlusError, match="not found"):
        EP.run(model, fake_exe, epw=tmp_path / "missing.epw")

    rep = hvac_results(mep, bim, "dhaka", use_energyplus=False, annual=True, epw=None)
    assert any("EPW weather file" in p for p in rep["problems"])


def test_envelope_compliance_wall_u_pass_and_fail() -> None:
    bim = _box_bim()
    mep_fail = MepModel.model_validate(
        {
            "hvac": {
                "envelope": {"uWall": 2.0, "uRoof": 0.3, "uGlazing": 2.8, "shgc": 0.25},
                "stories": [{"story": "GF", "glazing": {"N": 0.2, "E": 0.2, "S": 0.2, "W": 0.2}}],
            }
        }
    )
    zoning = make_zones(Building.of(bim), mep_fail.hvac)
    res_fail = check_envelope_compliance(envelope_choice(mep_fail.hvac.envelope), zoning.zones)
    by_param_fail = {c["parameter"]: c for c in res_fail["checks"]}
    assert by_param_fail["uWall"]["limit"] == pytest.approx(0.6)
    assert by_param_fail["uWall"]["passed"] is False
    assert res_fail["passed"] is False

    mep_pass = MepModel.model_validate(
        {
            "hvac": {
                "envelope": {"uWall": 0.5, "uRoof": 0.3, "uGlazing": 2.8, "shgc": 0.25},
                "stories": [{"story": "GF", "glazing": {"N": 0.2, "E": 0.2, "S": 0.2, "W": 0.2}}],
            }
        }
    )
    res_pass = check_envelope_compliance(envelope_choice(mep_pass.hvac.envelope), zoning.zones)
    by_param_pass = {c["parameter"]: c for c in res_pass["checks"]}
    assert by_param_pass["uWall"]["passed"] is True
    assert res_pass["passed"] is True

    rep = hvac_results(mep_pass, bim, "dhaka", use_energyplus=False)
    assert rep["envelopeCompliance"]["passed"] is True
    assert len(rep["envelopeCompliance"]["checks"]) == 5


def test_wwr_computed_by_hand_for_fixture_building() -> None:
    """20 m x 10 m x 3 m building:
    North & South walls: 2 * 20 * 3 = 120 m² at WWR = 0.30 -> 36 m² window
    East  & West  walls: 2 * 10 * 3 =  60 m² at WWR = 0.20 -> 12 m² window
    Total wall area = 180 m², total window area = 48 m², WWR = 48 / 180 = 0.266667.
    """
    bim = _box_bim(20000.0, 10000.0, 3000.0)
    mep = MepModel.model_validate(
        {
            "hvac": {
                "stories": [
                    {"story": "GF", "glazing": {"N": 0.30, "S": 0.30, "E": 0.20, "W": 0.20}}
                ]
            }
        }
    )
    zoning = make_zones(Building.of(bim), mep.hvac)
    info = building_wwr(zoning.zones)
    assert info["wallArea"] == pytest.approx(180.0)
    assert info["windowArea"] == pytest.approx(48.0)
    assert info["wwr"] == pytest.approx(48.0 / 180.0, rel=1e-6)
    assert info["byFacade"]["N"]["wwr"] == pytest.approx(0.30)
    assert info["byFacade"]["E"]["wwr"] == pytest.approx(0.20)


def test_eui_computed_by_hand_on_fake_results_table(tmp_path: Path) -> None:
    """Fake results table -> EUI = total / area by hand (both ideal-loads and VRF COP)."""
    fake_table = {
        "heatingKwh": 1200.0,
        "coolingKwh": 14000.0,
        "lightingKwh": 3600.0,
        "equipmentKwh": 5200.0,
        "unmetHeatingHours": 1.5,
        "unmetCoolingHours": 4.5,
    }
    area = 400.0

    # Ideal loads (COP = 1.0): total = 1200 + 14000 + 3600 + 5200 = 24000 kWh -> EUI = 60.0 kWh/m²·yr
    ideal = EP.annual_summary_from_tables(fake_table, area, system="idealLoads")
    assert ideal["totalKwh"] == pytest.approx(24000.0)
    assert ideal["euiKwhM2Yr"] == pytest.approx(24000.0 / 400.0)
    assert ideal["unmetHours"] == {"heating": 1.5, "cooling": 4.5, "total": 6.0}

    # VRF (cooling COP = 3.5, heating COP = 3.2):
    # cooling elec = 14000 / 3.5 = 4000 kWh; heating elec = 1200 / 3.2 = 375 kWh
    # total = 375 + 4000 + 3600 + 5200 = 13175 kWh -> EUI = 13175 / 400 = 32.9375 -> 32.94 kWh/m²·yr
    vrf = EP.annual_summary_from_tables(fake_table, area, system="vrf")
    assert vrf["coolingKwh"] == pytest.approx(4000.0)
    assert vrf["heatingKwh"] == pytest.approx(375.0)
    assert vrf["totalKwh"] == pytest.approx(13175.0)
    assert vrf["euiKwhM2Yr"] == pytest.approx(round(13175.0 / 400.0, 2))

    # Also verify read_annual_results on a synthetic eplusout.sql SQLite database
    sql_path = tmp_path / "eplusout.sql"
    con = sqlite3.connect(str(sql_path))
    con.execute(
        "CREATE TABLE ReportDataDictionary (ReportDataDictionaryIndex INT, IsMeter INT, Name TEXT)"
    )
    con.execute("CREATE TABLE Time (TimeIndex INT, WarmupFlag INT)")
    con.execute(
        "CREATE TABLE ReportData (ReportDataDictionaryIndex INT, TimeIndex INT, Value REAL)"
    )
    con.execute(
        "CREATE TABLE TabularDataWithStrings (ReportName TEXT, TableName TEXT, RowName TEXT, ColumnName TEXT, Value TEXT)"
    )
    con.execute("INSERT INTO Time VALUES (1, 0)")
    kwh_to_j = 3_600_000.0
    for idx, (name, kwh) in enumerate(
        [
            ("Cooling:EnergyTransfer", 14000.0),
            ("Heating:EnergyTransfer", 1200.0),
            ("InteriorLights:Electricity", 3600.0),
            ("InteriorEquipment:Electricity", 5200.0),
        ],
        1,
    ):
        con.execute("INSERT INTO ReportDataDictionary VALUES (?, 1, ?)", (idx, name))
        con.execute("INSERT INTO ReportData VALUES (?, 1, ?)", (idx, kwh * kwh_to_j))
    con.execute(
        "INSERT INTO TabularDataWithStrings VALUES ('SystemSummary', 'Time Setpoint Not Met', 'Facility', 'During Heating', '2.0')"
    )
    con.execute(
        "INSERT INTO TabularDataWithStrings VALUES ('SystemSummary', 'Time Setpoint Not Met', 'Facility', 'During Cooling', '3.0')"
    )
    con.commit()
    con.close()

    model = EP.Model(epjson={}, systems={}, annual=True, system="idealLoads")
    parsed = EP.read_annual_results(sql_path, model, area)
    assert parsed["totalKwh"] == pytest.approx(24000.0)
    assert parsed["euiKwhM2Yr"] == pytest.approx(60.0)
    assert parsed["unmetHours"] == {"heating": 2.0, "cooling": 3.0, "total": 5.0}
    assert json.loads(json.dumps(parsed))["euiKwhM2Yr"] == 60.0
    assert T.envelope_limits().uWallMax == pytest.approx(0.6)
