"""Tests and hand-calculation verifications for Revit-parity package R7:
1. Lighting design (lumen method, grid layout, HVAC & electrical demand feedback)
2. Individual sprinkler head placement, RoomGraph branch/cross-main routing, pipe schedule & hydraulics
3. Fire alarm device layout (smoke/heat detectors, MCPs, sounders, panel) and battery sizing
4. Domestic hot water heater sizing and recirculation loop hydraulics
5. Fuel gas (natural gas / LPG) and medical gas piping sizing
"""

from __future__ import annotations

import math

import pytest
from shapely.geometry import box

from saengine.boq.quantities import compute_boq
from saengine.drawings.sheets import mep as mep_sheets
from saengine.drawings.sheets.model import Building as DrawBuilding
from saengine.drawings.sheets.model import Level, PlanSlab
from saengine.electrical.demand import demand as electrical_demand
from saengine.electrical.lighting import (
    lighting_design,
    lumen_method,
    room_index,
    utilisation_factor,
)
from saengine.electrical.report import electrical_results
from saengine.electrical.rooms import lighting_room_loads
from saengine.fire import network as fire_net
from saengine.fire.alarm import alarm_layout, battery_calculation, detector_kind
from saengine.fire.report import fire_results
from saengine.fire.sprinklers import layout_story_sprinklers, place_room_sprinklers, schedule_size
from saengine.hvac.gains import room_gains
from saengine.hvac.geometry import zones as hvac_zones
from saengine.hvac.report import hvac_results
from saengine.library import default_material_library, default_object_library
from saengine.library.architecture import Architecture
from saengine.library.bim import BuildingModel
from saengine.library.ifc import export_ifc
from saengine.library.mep import MepModel
from saengine.mep.rooms import room_inputs
from saengine.plumbing.building import Building
from saengine.plumbing.gas import (
    gas_results,
    medical_gas_flow,
    medical_gas_results,
    pole_drop_kpa,
    pole_flow_m3h,
    size_gas_pipe,
    size_medical_gas_pipe,
)
from saengine.plumbing.hot_water import heater_sizing, recirculation_loop
from saengine.plumbing.report import plumbing_results


def _sample_bim() -> BuildingModel:
    return BuildingModel.model_validate(
        {
            "stories": [
                {"id": "GF", "name": "Ground", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3200},
                {"id": "ROOF", "name": "Roof", "elevation": 6400},
            ],
            "elements": [
                {
                    "id": "S-L1",
                    "type": "SL150",
                    "kind": "slab",
                    "elevation": 3200,
                    "boundary": [[0, 0], [10000, 0], [10000, 8000], [0, 8000]],
                },
                {
                    "id": "S-ROOF",
                    "type": "SL150",
                    "kind": "slab",
                    "elevation": 6400,
                    "boundary": [[0, 0], [10000, 0], [10000, 8000], [0, 8000]],
                },
            ],
        }
    )


def _sample_arch() -> Architecture:
    # 10 x 8 m floor on GF: 6x5 m Office + 4x5 m Kitchen + 10x3 m Corridor
    lines = [
        ([0, 0], [10000, 0]),
        ([10000, 0], [10000, 8000]),
        ([10000, 8000], [0, 8000]),
        ([0, 8000], [0, 0]),
        ([0, 3000], [10000, 3000]),
        ([6000, 3000], [6000, 8000]),
    ]
    return Architecture.model_validate(
        {
            "wallTypes": [
                {
                    "id": "WT1",
                    "name": "Brick 125",
                    "layers": [{"material": "Brick", "thickness": 125, "unitWeight": 19}],
                }
            ],
            "doorTypes": [{"id": "D1", "name": "Exit 1000x2100", "width": 1000, "height": 2100}],
            "walls": [{"id": "W-S", "type": "WT1", "base": "GF", "path": [[0, 0], [10000, 0]]}],
            "doors": [{"id": "DR-EXIT", "type": "D1", "wall": "W-S", "offset": 5000}],
            "separators": [
                {"id": f"SEP{i}", "story": "GF", "start": a, "end": b}
                for i, (a, b) in enumerate(lines[1:], 1)
            ],
            "rooms": [
                {
                    "id": "RM-COR",
                    "story": "GF",
                    "name": "Corridor",
                    "point": [5000, 1500],
                    "occupancy": "corridorAbove",
                },
                {
                    "id": "RM-OFF",
                    "story": "GF",
                    "name": "Office",
                    "point": [3000, 5500],
                    "occupancy": "office",
                },
                {
                    "id": "RM-KIT",
                    "story": "GF",
                    "name": "Kitchen",
                    "point": [8000, 5500],
                    "occupancy": "office",
                    "wet": True,
                },
            ],
        }
    )


# ─────────────────────────────── 1. Lighting design ───────────────────────────────


def test_lumen_method_office_by_hand() -> None:
    # Hand verification:
    # 6 x 5 m office, 3.0 m ceiling, 0.85 m work plane -> Hm = 3.0 - 0.85 = 2.15 m
    # Room index K = (6 * 5) / (2.15 * (6 + 5)) = 30 / 23.65 = 1.2685 -> 1.27
    # Target 500 lx, luminaire 3600 lm, UF 0.6, MF 0.8:
    # N_exact = 500 * 30 / (3600 * 0.6 * 0.8) = 15000 / 1728 = 8.6806 -> 9 luminaires
    # Achieved E = 9 * 3600 * 0.6 * 0.8 / 30 = 518.4 lx
    # LPD = 9 * 36 W / 30 m^2 = 10.8 W/m^2
    k = room_index(6.0, 5.0, 2.15)
    assert k == pytest.approx(30.0 / (2.15 * 11.0))
    assert round(k, 2) == 1.27

    res = lumen_method(
        6.0,
        5.0,
        ceiling_height_m=3.0,
        work_plane_m=0.85,
        target_lux=500.0,
        luminaire_type="ledPanel600",
        lumens=3600.0,
        watts=36.0,
        uf=0.6,
        mf=0.8,
    )
    assert res["roomIndex"] == pytest.approx(1.2685, abs=1e-3)
    assert res["requiredExact"] == pytest.approx(500.0 * 30.0 / (3600.0 * 0.6 * 0.8), rel=1e-3)
    assert res["requiredCount"] == 9
    assert res["count"] == 9
    assert (res["nx"], res["ny"]) == (3, 3)
    assert res["spacingX"] <= res["maxSpacingM"]
    assert res["spacingY"] <= res["maxSpacingM"]
    assert res["achievedLux"] == pytest.approx(9 * 3600 * 0.6 * 0.8 / 30.0, abs=0.1)
    assert res["lpd"] == pytest.approx(9 * 36.0 / 30.0)


def test_lighting_uf_table_and_mep_feedback() -> None:
    # At K=1.25 and 70/50/20 reflectance, UF table gives 0.60
    assert utilisation_factor(1.25, "70/50/20") == pytest.approx(0.60)
    bim = _sample_bim()
    arch = _sample_arch()
    mep = MepModel.model_validate(
        {
            "electrical": {
                "lighting": {"enabled": True, "luminaireType": "ledPanel600"},
                "stories": [{"story": "GF", "use": "office"}],
            },
            "hvac": {"stories": [{"story": "GF", "use": "officeSpace"}]},
        }
    )
    rooms = room_inputs(arch, bim, mep.plumbing)
    design = lighting_design(mep, Building.of(bim), rooms)
    assert design["stories"]["GF"]["count"] > 0
    assert design["stories"]["GF"]["lpd"] > 0
    assert len(design["circuits"]) >= 1

    # Hand off to electrical/rooms.py and electrical/demand.py
    loads = lighting_room_loads(mep, Building.of(bim), rooms)
    gf_lpd = loads["GF"]["lpd"]
    dem = electrical_demand(mep.electrical, Building.of(bim), mep, lighting_loads=loads)
    assert dem["stories"][0]["lighting"] == pytest.approx(gf_lpd)

    # Feed LPD back to HVAC gains (with Table 3.4.5 kept as fallback when lighting_lpd=None)
    zoning = hvac_zones(Building.of(bim), mep.hvac)
    gf_zone = zoning.zones[0]
    g_fallback = room_gains(gf_zone, mep.hvac, rooms.story("GF").hvac_groups())
    assert g_fallback.lighting == pytest.approx(9.0)
    g_designed = room_gains(gf_zone, mep.hvac, rooms.story("GF").hvac_groups(), lighting_lpd=gf_lpd)
    assert g_designed.lighting == pytest.approx(gf_lpd)

    # Hvac report picks up lighting LPD when luminaires are stored in mep.json
    mep_with_lums = MepModel.model_validate(
        {
            "electrical": {
                "stories": [{"story": "GF", "use": "office"}],
                "luminaires": [
                    {
                        k: v
                        for k, v in lum.items()
                        if k
                        in (
                            "id",
                            "type",
                            "story",
                            "room",
                            "x",
                            "y",
                            "z",
                            "watts",
                            "lumens",
                            "circuit",
                            "sized",
                        )
                    }
                    for lum in design["luminaires"]
                ],
            },
            "hvac": {"stories": [{"story": "GF", "use": "officeSpace"}]},
        }
    )
    hvac_rep = hvac_results(mep_with_lums, bim, use_energyplus=False, rooms=rooms)
    assert any("from lighting design" in s for s in hvac_rep["zones"][0]["sources"])
    elec_rep = electrical_results(mep_with_lums, bim)
    assert elec_rep["lighting"]["GF"]["lpd"] == pytest.approx(gf_lpd, rel=0.05)


# ─────────────────────────────── 2. Sprinklers ───────────────────────────────


def test_sprinkler_room_grid_by_hand() -> None:
    # Hand verification:
    # Light hazard room 10 x 8 m (80 m^2), max 21 m^2 per head, max spacing 4.6 m:
    # Minimum head count >= ceil(80 / 21) = 4
    # Grid along X (10 m): ceil(10 / 4.6) = 3 -> sx = 3.333 m <= 4.6 m (wall dist = 1.667 m <= 2.3 m)
    # Grid along Y (8 m): ceil(8 / 4.6) = 2 -> sy = 4.0 m <= 4.6 m (wall dist = 2.0 m <= 2.3 m)
    # 3 x 2 = 6 heads >= 4; per head = 80 / 6 = 13.33 m^2 <= 21 m^2
    poly = box(0.0, 0.0, 10000.0, 8000.0)
    res = place_room_sprinklers(poly, "lightI", max_area=21.0, max_spacing=4.6)
    assert res["count"] >= math.ceil(80.0 / 21.0)
    assert res["count"] == 6
    assert res["sx"] <= 4.6 and res["sy"] <= 4.6
    assert res["perHead"] <= 21.0
    for x, y in res["heads"]:
        assert 0.0 < x < 10000.0 and 0.0 < y < 8000.0


def test_sprinkler_placed_network_routing_and_hydraulics() -> None:
    bim = _sample_bim()
    arch = _sample_arch()
    mep = MepModel.model_validate(
        {
            "fire": {
                "stories": [{"story": "GF", "occupancy": "office", "sprinklered": True}],
                "risers": [
                    {
                        "id": "SPR1",
                        "system": "sprinkler",
                        "x": 500.0,
                        "y": 1500.0,
                        "fromStory": "GF",
                        "toStory": "L1",
                    }
                ],
            }
        }
    )
    rooms = room_inputs(arch, bim, mep.plumbing)
    gf_rooms = rooms.story("GF").rooms
    lay = layout_story_sprinklers(
        "GF",
        (500.0, 1500.0),
        gf_rooms,
        None,
        "lightI",
        "beams",
        "steel",
    )
    assert lay["headCount"] >= 4
    assert any(p["kind"] == "crossMain" for p in lay["pipes"])
    assert any(p["kind"] == "branch" for p in lay["pipes"])
    assert lay["mainSize"] == schedule_size(lay["headCount"], "lightI", "steel")

    # Verify full fire_results runs EPANET hydraulic calc on the placed network
    rep = fire_results(mep, bim, default_object_library(), rooms=rooms, arch=arch)
    assert rep["sprinklerLayout"] is not None
    assert rep["hydraulics"]["sprinkler"]["heads"] >= 1
    assert (
        rep["hydraulics"]["sprinkler"]["least"] >= rep["hydraulics"]["sprinkler"]["headFlow"] - 0.5
    )

    # Verify placed network directly
    net = fire_net.Net(material="steel")
    net.node("PUMP", 0.0)
    takeoff = net.node("TO", 3.0)
    net.pipe("M", "PUMP", takeoff, 5.0, 100)
    remote = fire_net.placed_sprinkler_network(
        net, takeoff, (0.5, 1.5), 3.0, lay["heads"], lay["pipes"], 4
    )
    assert len(remote) == 4
    sol = fire_net.emitter_head(net, remote, 60.0, {})
    assert min(sol["flow"][n] for n in remote) == pytest.approx(60.0, rel=0.02)


# ─────────────────────────────── 3. Fire alarm ───────────────────────────────


def test_fire_alarm_battery_by_hand() -> None:
    # Hand verification:
    # standby 0.25 A * 24 h = 6.00 Ah
    # alarm   1.50 A * 0.5 h (30 min) = 0.75 Ah
    # unfactored = 6.75 Ah
    # with 1.25 ageing factor: 6.75 * 1.25 = 8.4375 -> 8.44 Ah -> recommended 12.0 Ah
    bat = battery_calculation(0.25, 1.5, standby_hours=24.0, alarm_minutes=30.0, ageing_factor=1.25)
    assert bat["standbyAh"] == pytest.approx(6.0)
    assert bat["alarmAh"] == pytest.approx(0.75)
    assert bat["unfactoredAh"] == pytest.approx(6.75)
    assert bat["requiredAh"] == pytest.approx(8.44)
    assert bat["recommendedAh"] == 12.0


def test_fire_alarm_device_layout() -> None:
    bim = _sample_bim()
    arch = _sample_arch()
    mep = MepModel.model_validate(
        {"fire": {"detection": True, "stories": [{"story": "GF", "occupancy": "office"}]}}
    )
    rooms = room_inputs(arch, bim, mep.plumbing)
    assert detector_kind("Kitchen") == "heat"
    assert detector_kind("Office") == "smoke"

    out = alarm_layout(mep, Building.of(bim), rooms, arch, stories=[{"story": "GF", "area": 80.0}])
    kinds = {d["kind"] for d in out["devices"]}
    assert {"smokeDetector", "heatDetector", "callPoint", "sounder", "panel"} <= kinds
    # Kitchen gets heat detector, Office and Corridor get smoke detectors
    kit_devs = [d for d in out["devices"] if d.get("room") == "RM-KIT"]
    off_devs = [d for d in out["devices"] if d.get("room") == "RM-OFF"]
    assert all(d["kind"] == "heatDetector" for d in kit_devs)
    assert all(d["kind"] == "smokeDetector" for d in off_devs)
    assert out["battery"]["requiredAh"] > 0


# ─────────────────────────────── 4. Hot water ───────────────────────────────


def test_hot_water_storage_and_recirculation_by_hand() -> None:
    # Hand verification:
    # Peak demand = 400 L/h, cold 15 C, storage 60 C (dT = 45 K),
    # peak_hours = 1.0 h, usable_fraction = 0.70, storage_factor = 1.25
    # R = 400 * 1.0 / (1.0 + 1.25 * 0.70) = 400 / 1.875 = 213.333 L/h
    # V_storage = 1.25 * 213.333 = 266.667 L
    # Balance check: V_storage * 0.70 + R * 1.0 = 186.667 + 213.333 = 400.0 L
    # Power = (213.333 / 3600) * 4.186 * 45 = 11.163 kW
    hw = heater_sizing(
        400.0,
        occupancy="residentialFlat",
        cold_temp_c=15.0,
        storage_temp_c=60.0,
        peak_hours=1.0,
        usable_fraction=0.70,
        storage_factor=1.25,
    )
    assert hw["recoveryRateLph"] == pytest.approx(400.0 / 1.875, rel=1e-3)
    assert hw["storageVolumeL"] == pytest.approx(1.25 * 400.0 / 1.875, rel=1e-3)
    assert hw["powerKw"] == pytest.approx((400.0 / 1.875) / 3600.0 * 4.186 * 45.0, abs=0.05)

    # Recirculation loop: 50 m * 15 W/m = 750 W = 0.75 kW; dT_return = 5 K
    # flow = (0.75 / (4.186 * 5)) * 60 = 2.150 L/min
    rec = recirculation_loop(50.0, heat_loss_w_per_m=15.0, return_drop_c=5.0, material="PPR")
    assert rec["heatLossW"] == pytest.approx(750.0)
    assert rec["flowLpm"] == pytest.approx((0.75 / (4.186 * 5.0)) * 60.0, abs=0.02)
    assert rec["pipeDiameterMm"] >= 13

    mep = MepModel.model_validate(
        {
            "plumbing": {
                "stories": [
                    {
                        "story": "GF",
                        "occupancy": "residentialFlat",
                        "fixtures": {"shower": 4, "kitchenSink": 2, "basin": 4},
                    }
                ],
                "hotWater": {"enabled": True, "loopLengthM": 60.0},
            }
        }
    )
    rep = plumbing_results(mep, _sample_bim())
    assert rep["hotWater"] is not None
    assert rep["hotWater"]["heater"]["storageVolumeL"] > 0
    assert rep["hotWater"]["recirculation"]["flowLpm"] > 0


# ─────────────────────────────── 5. Gas & medical gas ───────────────────────────────


def test_gas_pipe_sizing_by_hand() -> None:
    # Hand verification by Pole's formula from bnbc2020 pack:
    # Q [m3/h] = 0.0071 * sqrt(dP_mbar * d_mm^5 / (S * L_m))
    # Natural gas (S = 0.60), Q = 4.0 m3/h, L = 20 m, allowable dP = 0.10 kPa (1.0 mbar),
    # fitting_factor = 1.0 (straight pipe):
    # Required d_min = ((4.0 / 0.0071)^2 * 0.60 * 20.0 / 1.0)**(1/5) = 20.71 mm
    # From pack pipes: DN15 (15.8 mm) fails, DN20 (21.6 mm) gives:
    # dP_mbar = (4.0 / 0.0071)^2 * 0.60 * 20 / 21.6^5 = 317401.3 * 12 / 4701849.8 = 0.810 mbar = 0.081 kPa
    d_req = (((4.0 / 0.0071) ** 2) * 0.60 * 20.0 / 1.0) ** (1 / 5)
    assert d_req == pytest.approx(20.71, abs=0.02)
    assert pole_flow_m3h(0.10, 21.6, 0.60, 20.0) > 4.0
    expected_dp = ((4.0 / 0.0071) ** 2) * 0.60 * 20.0 / (21.6**5) / 10.0
    assert pole_drop_kpa(4.0, 21.6, 0.60, 20.0) == pytest.approx(expected_dp, rel=1e-4)

    sized = size_gas_pipe(4.0, 20.0, fuel="naturalGas", max_drop_kpa=0.10, fitting_factor=1.0)
    assert sized["nominal"] == 20
    assert sized["dropKpa"] == pytest.approx(expected_dp, abs=1e-4)
    assert sized["ok"]


def test_lpg_basement_check_and_medical_gas() -> None:
    bim = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "B1", "name": "Basement 1", "elevation": -3000},
                {"id": "GF", "name": "Ground", "elevation": 0},
            ],
            "elements": [],
        }
    )
    mep = MepModel.model_validate(
        {
            "gas": {
                "fuel": "lpg",
                "meter": {"id": "GM1", "story": "B1", "x": 1000, "y": 1000, "ventilated": False},
                "appliances": [{"id": "A1", "kind": "commercialRange", "story": "GF", "count": 2}],
                "pipes": [{"id": "GP1", "story": "GF", "path": [[0, 0], [15000, 0]]}],
            },
            "medicalGas": {
                "rooms": [
                    {"room": "OT1", "kind": "operatingRoom", "beds": 2},
                    {"room": "W1", "kind": "hospitalWard", "beds": 10},
                ],
                "pipes": [{"id": "MG1", "gas": "O2", "story": "GF", "path": [[0, 0], [20000, 0]]}],
            },
        }
    )
    g = gas_results(mep, Building.of(bim, ground=0.0))
    assert g["connectedKw"] == pytest.approx(60.0)
    assert g["diversityFactor"] == 0.85
    assert not g["checks"][0]["ok"]  # LPG in basement fails

    # Medical gas: 2*2 + 10*1 = 14 O2 outlets
    o2 = medical_gas_flow("O2", 14)
    assert o2["flowLpm"] == pytest.approx(10.0 + 13 * 6.0 * 0.5)
    mg = medical_gas_results(mep)
    assert mg["systems"]["O2"]["outlets"] == 14
    assert mg["pipes"][0]["diameter"] is not None
    assert size_medical_gas_pipe("O2", 49.0)["velocityMs"] <= 10.0


# ─────────────────────────────── End-to-end BOQ / Drawings / IFC ───────────────────────────────


def test_r7_elements_in_drawings_boq_and_ifc() -> None:
    bim = _sample_bim()
    mep = MepModel.model_validate(
        {
            "electrical": {
                "luminaires": [
                    {"id": "LUM-1", "type": "ledPanel600", "story": "GF", "x": 1500, "y": 1500}
                ]
            },
            "fire": {
                "sprinklerHeads": [{"id": "SH-1", "story": "GF", "x": 2000, "y": 2000}],
                "sprinklerPipes": [
                    {
                        "id": "SP-1",
                        "story": "GF",
                        "kind": "branch",
                        "path": [[500, 2000], [2000, 2000]],
                        "diameter": 25,
                    }
                ],
                "alarmDevices": [
                    {"id": "FA-1", "kind": "smokeDetector", "story": "GF", "x": 3000, "y": 3000}
                ],
            },
            "plumbing": {
                "hotWater": {
                    "enabled": True,
                    "heater": {"id": "HWH1", "story": "GF", "x": 4000, "y": 4000, "volumeL": 300},
                }
            },
            "gas": {
                "fuel": "naturalGas",
                "meter": {"id": "GM1", "story": "GF", "x": 500, "y": 500},
                "pipes": [
                    {"id": "GP1", "story": "GF", "path": [[500, 500], [5500, 500]], "diameter": 20}
                ],
            },
            "medicalGas": {
                "outlets": [{"id": "MGO1", "gas": "O2", "story": "GF", "x": 6000, "y": 4000}],
                "pipes": [
                    {
                        "id": "MGP1",
                        "gas": "O2",
                        "story": "GF",
                        "path": [[500, 4000], [6000, 4000]],
                        "diameter": 15,
                    }
                ],
            },
        }
    )

    # Drawings
    db = DrawBuilding(
        levels=[Level("GF", "GF", 0), Level("L1", "L1", 3200)],
        slabs=[PlanSlab("S-GF", "S-GF", [[0, 0], [10000, 0], [10000, 8000], [0, 8000]], 150, 0)],
    )
    items = mep_sheets.items_by_level(mep_sheets.MepDrawing(mep), db)
    marks = {i.mark for i in items["GF"]}
    assert any("LUM-1" in m for m in marks)
    assert any("SH-1" in m for m in marks)
    assert any("FA-1" in m for m in marks)
    assert any("HWH1" in m for m in marks)
    assert any("GM1" in m for m in marks)
    assert any("MGO1" in m for m in marks)

    # BOQ
    bill = compute_boq(
        bim.model_dump_json(by_alias=True),
        default_object_library().model_dump_json(),
        default_material_library().model_dump_json(),
        mep_text=mep.model_dump_json(by_alias=True),
    )
    descs = {i["description"] for i in bill["items"]}
    assert "Luminaires: ledPanel600" in descs
    assert "Hot water storage heater / calorifier" in descs
    assert any("Gas pipes" in d for d in descs)
    assert any("Medical gas" in d for d in descs)

    # IFC
    _, ids, _ = export_ifc(
        bim,
        default_object_library(),
        default_material_library(),
        mep=mep,
    )
    for eid in ("LUM-1", "SH-1", "SP-1", "FA-1", "GP1", "MGP1"):
        assert eid in ids
