"""Revit-parity R6 HVAC tests: room-by-room cooling loads, heating loads, duct pressure drop /
fan static pressure / static regain / velocity reduction / noise flags, and duct auto-routing.

Every numerical benchmark is verified by hand in comments. EnergyPlus is NOT executed.
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from shapely.geometry import box

from saengine.hvac import air
from saengine.hvac import energyplus as EP
from saengine.hvac import fallback as F
from saengine.hvac import tables as T
from saengine.hvac.constructions import envelope as envelope_choice
from saengine.hvac.gains import ZoneGains, design_conditions
from saengine.hvac.geometry import Surface, ThermalZone, Window
from saengine.hvac.report import hvac_results
from saengine.hvac.routing import auto_route_ducts
from saengine.library import architecture as arch_lib
from saengine.library.bim import BuildingModel
from saengine.library.mep import Duct, MepModel
from saengine.mep.rooms import room_inputs
from saengine.mep.routing import BeamLine, RoomGraph, RoomPlace


def _corridor_arch_and_bim() -> tuple[Any, BuildingModel]:
    """20 x 8 m single-storey building (GF 0 to ROOF 3000) with a 2 m south corridor and 3
    office rooms along the north side:

        y 8000 +--------+--------+--------+
               |   R1   |   R2   |   R3   |
               | (6x6m) | (7x6m) | (7x6m) |
        y 2000 +--------+--------+--------+
               |        Corridor C        |
             0 +--------------------------+
               0       6000    13000    20000
    """
    outline = [[0, 0], [20000, 0], [20000, 8000], [0, 8000]]
    bim = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "GF", "name": "GF", "elevation": 0},
                {"id": "ROOF", "name": "ROOF", "elevation": 3000},
            ],
            "elements": [
                {
                    "id": "S-ROOF",
                    "type": "SL150",
                    "kind": "slab",
                    "elevation": 3000,
                    "boundary": outline,
                }
            ],
        }
    )
    lines = [
        ([0, 0], [20000, 0]),
        ([20000, 0], [20000, 8000]),
        ([20000, 8000], [0, 8000]),
        ([0, 8000], [0, 0]),
        ([0, 2000], [20000, 2000]),
        ([6000, 2000], [6000, 8000]),
        ([13000, 2000], [13000, 8000]),
    ]
    rooms = [
        {"id": "C", "name": "Corridor", "point": [10000, 1000], "occupancy": "corridorAbove"},
        {"id": "R1", "name": "Office 1", "point": [3000, 5000], "occupancy": "office"},
        {"id": "R2", "name": "Office 2", "point": [9500, 5000], "occupancy": "office"},
        {"id": "R3", "name": "Office 3", "point": [16500, 5000], "occupancy": "office"},
    ]
    arch = arch_lib.Architecture.model_validate(
        {
            "separators": [
                {"id": f"S{k}", "story": "GF", "start": a, "end": b}
                for k, (a, b) in enumerate(lines)
            ],
            "rooms": [{"story": "GF", **r} for r in rooms],
        }
    )
    return arch, bim


# ───────────────────────── 1. Room-by-room cooling loads + EnergyPlus model ─────────────────────────


def test_per_room_cooling_loads_sum_within_per_storey_total() -> None:
    """Per-room cooling loads sum to within the per-storey fallback total.

    Difference explanation:
    1) When a story has both East and West glazing, the per-storey block load takes max(E, W)
       solar because East and West peak at different hours, whereas summing individual room peak
       loads includes both the East-facing room's peak and the West-facing room's peak
       (difference = min(E_solar, W_solar)).
    2) When glazing is only on N/S facades (no E/W split) and story glazing WWR is explicit,
       exterior wall areas, roof areas, internal gains, and outdoor air sum identically, so the
       per-room cooling sum matches the per-storey total to < 0.5 %.
    """
    arch, bim = _corridor_arch_and_bim()
    rooms = room_inputs(arch, bim)

    # Case A: N & S glazing only -> sum of room loads matches per-storey load directly.
    mep_ns = MepModel.model_validate(
        {
            "hvac": {
                "stories": [
                    {
                        "story": "GF",
                        "use": "officeSpace",
                        "glazing": {"N": 0.3, "E": 0.0, "S": 0.3, "W": 0.0},
                    }
                ]
            }
        }
    )
    per_room = hvac_results(mep_ns, bim, "dhaka", use_energyplus=False, rooms=rooms, zoning="room")
    per_story = hvac_results(
        mep_ns, bim, "dhaka", use_energyplus=False, rooms=rooms, zoning="story"
    )
    assert len(per_room["zones"]) == 4
    assert len(per_story["zones"]) == 1
    assert per_room["total"] == pytest.approx(per_story["total"], rel=5e-3)
    assert per_room["sensible"] == pytest.approx(per_story["sensible"], rel=5e-3)
    assert per_room["latent"] == pytest.approx(per_story["latent"], rel=5e-3)
    assert per_room["airflow"] == pytest.approx(per_story["airflow"], rel=5e-3)

    # Case B: E & W glazing included -> sum of room peaks exceeds per-storey block peak by
    # min(E_solar, W_solar) because E (morning) and W (afternoon) peak at different times.
    mep_ew = MepModel.model_validate(
        {
            "hvac": {
                "stories": [
                    {
                        "story": "GF",
                        "use": "officeSpace",
                        "glazing": {"N": 0.2, "E": 0.3, "S": 0.2, "W": 0.3},
                    }
                ]
            }
        }
    )
    r_ew = hvac_results(mep_ew, bim, "dhaka", use_energyplus=False, rooms=rooms, zoning="room")
    s_ew = hvac_results(mep_ew, bim, "dhaka", use_energyplus=False, rooms=rooms, zoning="story")
    # West facade of R1 = 6 m x 3 m = 18 m², 30 % glass = 5.4 m²; East facade of R3 = 5.4 m².
    # Corridor C (2 m x 3 m) has both E and W walls, so its own block load takes max(E, W) = 1.8 m².
    # Thus sum(room peaks) - story block = 5.4 * 0.819 * 500 / 1000 = 2.2113 kW.
    expected_ew_diff = 5.4 * 0.819 * 500.0 / 1000.0
    assert (r_ew["total"] - s_ew["total"]) == pytest.approx(expected_ew_diff, abs=0.02)


def test_energyplus_epjson_has_room_zones_and_heating_setpoint() -> None:
    """Verify EP.build generates one EnergyPlus Zone per room with proper heating setpoint
    (20 °C, not -50 °C) and a WinterDesignDay, without invoking EnergyPlus."""
    arch, bim = _corridor_arch_and_bim()
    rooms = room_inputs(arch, bim)
    mep = MepModel.model_validate({"hvac": {"stories": [{"story": "GF", "use": "officeSpace"}]}})
    from saengine.hvac.gains import single_room_gains
    from saengine.hvac.geometry import zones as make_zones
    from saengine.plumbing.building import Building

    zoning = make_zones(Building.of(bim), mep.hvac, rooms=rooms, by_room=True, arch=arch)
    assert len(zoning.zones) == 4
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
    )
    ep = model.epjson
    assert len(ep["Zone"]) == 4
    assert "Heating 01-21" in ep["SizingPeriod:DesignDay"]
    assert ep["SizingPeriod:DesignDay"]["Heating 01-21"]["day_type"] == "WinterDesignDay"
    for stat in ep["ThermostatSetpoint:DualSetpoint"].values():
        assert stat["heating_setpoint_temperature_schedule_name"] == "Constant 20"
        assert "-50" not in stat["heating_setpoint_temperature_schedule_name"]
    # Interzone wall surfaces between R1/R2/R3/C are paired cleanly
    surfs = ep["BuildingSurface:Detailed"]
    interzone = [s for s in surfs.values() if s["outside_boundary_condition"] == "Surface"]
    assert len(interzone) > 0
    for s in interzone:
        assert s["outside_boundary_condition_object"] in surfs


# ───────────────────────── 2. Heating loads (hand calculation + climates) ─────────────────────────


def test_heating_load_single_room_by_hand() -> None:
    """Hand calculation:
    Room 5 x 4 x 3 m (area = 20 m², volume = 60 m³).
    One 5 m external wall (area = 5 x 3 = 15 m²), U_wall = 2.0 W/m²K,
    with 2 m² window U_win = 5.8 W/m²K (net opaque wall = 15 - 2 = 13 m²).
    ΔT = 20 K (indoor 20 °C, outdoor 0 °C), 0.5 ACH infiltration, no outdoor ventilation.

    Q by hand = (2.0 * (15 - 2) + 5.8 * 2) * 20 + 0.33 * 0.5 * 60 * 20
              = (26.0 + 11.6) * 20 + 198.0
              = 752.0 + 198.0 = 950.0 W = 0.950 kW.
    (Using standard air rho*cp/3600 = 1.204 * 1.006 / 3.6 = 0.33645 gives 752 + 201.87 = 953.87 W.)
    """
    mep = MepModel.model_validate(
        {
            "hvac": {
                "design": {
                    "heatingOutdoorDB": 0.0,
                    "heatingIndoorDB": 20.0,
                    "infiltrationACH": 0.5,
                },
                "envelope": {"uWall": 2.0, "uGlazing": 5.8},
            }
        }
    )
    env = envelope_choice(mep.hvac.envelope)
    design = design_conditions(mep.hvac, "dhaka")
    win = Window("W1", [(0, 0, 2), (0, 0, 1), (2, 0, 1), (2, 0, 2)], width=2.0, height=1.0)
    wall = Surface(
        "ExtWall",
        "Wall",
        "Wall",
        "Outdoors",
        [(0, 0, 3), (0, 0, 0), (5, 0, 0), (5, 0, 3)],
        area=15.0,
        facade="S",
        windows=[win],
    )
    zone = ThermalZone("Z1", "GF", 0.0, 3.0, box(0, 0, 5, 4), True, None, surfaces=[wall])
    g = ZoneGains(
        "officeSpace",
        0.0,
        0.0,
        0.0,
        130.0,
        0.0,
        0.0,
        None,
        24.0,
        60.0,
        heatingIndoorDB=20.0,
    )
    res = F.heating_load(zone, g, env, design, include_ventilation=False)
    q_hand_w = (2.0 * (15.0 - 2.0) + 5.8 * 2.0) * 20.0 + 0.33 * 0.5 * 60.0 * 20.0
    assert q_hand_w == pytest.approx(950.0)
    assert res["conduction"] * 1000.0 == pytest.approx(752.0, rel=1e-6)
    assert res["total"] * 1000.0 == pytest.approx(q_hand_w, rel=0.005)
    assert res["airflow"] > 0

    # Dhaka winter default (11 °C) vs colder climate (-5 °C): colder climate scales proportionally.
    dhaka_design = design_conditions(MepModel.model_validate({"hvac": {}}).hvac, "dhaka")
    cold_design = design_conditions(
        MepModel.model_validate({"hvac": {"design": {"heatingOutdoorDB": -5.0}}}).hvac, "dhaka"
    )
    res_dhaka = F.heating_load(zone, g, env, dhaka_design, include_ventilation=False)
    res_cold = F.heating_load(zone, g, env, cold_design, include_ventilation=False)
    assert 0 < res_dhaka["total"] < res_cold["total"]
    assert res_cold["total"] / res_dhaka["total"] == pytest.approx(
        (20 - (-5)) / (20 - 11), rel=1e-6
    )


# ───────────────────────── 3. Duct pressure, fittings, critical path, sizing ─────────────────────────


def test_darcy_friction_400mm_duct_by_hand_colebrook() -> None:
    """Hand Colebrook verification:
    400 mm round duct, v = 5.0 m/s, L = 20 m, galvanised steel ε = 0.09 mm,
    ρ = 1.2 kg/m³, μ = 1.81e-5 Pa·s:
      d = 0.4 m
      A = π * 0.4² / 4 = 0.125663706 m²
      Q = 5.0 * A = 0.62831853 m³/s
      Re = 1.2 * 5.0 * 0.4 / 1.81e-5 = 132,596.685
      ε/D = 0.09 / 400 = 0.000225
      Colebrook: 1/√f = -2 log10(0.000225/3.7 + 2.51/(Re √f)) -> f = 0.0182874
      Pv = 0.5 * 1.2 * 5² = 15.0 Pa
      Δp/L = f / d * Pv = 0.0182874 / 0.4 * 15.0 = 0.68578 Pa/m
      Δp(20 m) = 20 * 0.68578 = 13.716 Pa.
    """
    d_mm = 400.0
    v = 5.0
    flow = v * math.pi * (d_mm / 1000.0) ** 2 / 4.0
    # Solve Colebrook explicitly by fixed-point iteration in the test as independent reference
    re = 1.2 * v * 0.4 / 1.81e-5
    ed = 0.09 / 400.0
    f = 0.02
    for _ in range(30):
        f = 1.0 / (-2.0 * math.log10(ed / 3.7 + 2.51 / (re * math.sqrt(f)))) ** 2
    dp_per_m_hand = (f / 0.4) * (0.5 * 1.2 * v * v)
    dp_20m_hand = 20.0 * dp_per_m_hand
    assert dp_20m_hand == pytest.approx(13.716, abs=0.02)

    grad = air.friction_gradient(flow, d_mm, material="galvanisedSteel")
    assert grad == pytest.approx(dp_per_m_hand, rel=1e-4)
    assert grad * 20.0 == pytest.approx(dp_20m_hand, rel=1e-4)

    # Higher roughness (flexible duct ε = 3.0 mm) produces higher friction than galvanised steel.
    assert air.friction_gradient(flow, d_mm, material="flexible") > grad


def test_elbow_fitting_loss_by_hand() -> None:
    """90° smooth elbow C = 0.3 at v = 5 m/s -> Δp = 0.3 * 0.5 * 1.2 * 25 = 4.5 Pa."""
    assert T.fitting_c("elbow_90_radius") == pytest.approx(0.3)
    res_tbl = air.fitting_loss("elbow_90_radius", 5.0)
    res_num = air.fitting_loss(0.3, 5.0)
    assert res_tbl["dp"] == pytest.approx(4.5, rel=1e-9)
    assert res_num["dp"] == pytest.approx(4.5, rel=1e-9)


def test_critical_path_3_branch_tree_sums_correctly() -> None:
    """Critical path of a 3-branch duct tree sums segment friction + fitting losses accurately
    and computes Fan Static Pressure = Critical Total Pressure - Fan Velocity Pressure."""
    q1, q2, q3 = 0.20, 0.30, 0.15
    q_trunk = q1 + q2 + q3
    tree = [
        {
            "id": "T",
            "parent": None,
            "flow": q_trunk,
            "length": 10.0,
            "size": {"shape": "round", "diameter": 400},
            "fittings": ["damper_open"],
        },
        {
            "id": "B1",
            "parent": "T",
            "flow": q1,
            "length": 12.0,
            "size": {"shape": "round", "diameter": 250},
            "fittings": ["tee_branch", "elbow_90_radius", "diffuser"],
        },
        {
            "id": "B2",
            "parent": "T",
            "flow": q2,
            "length": 25.0,
            "size": {"shape": "round", "diameter": 250},
            "fittings": ["tee_main", "elbow_90_radius", "diffuser"],
        },
        {
            "id": "B3",
            "parent": "T",
            "flow": q3,
            "length": 8.0,
            "size": {"shape": "round", "diameter": 200},
            "fittings": ["tee_branch", "diffuser"],
        },
    ]
    net = air.duct_network_pressure(tree)
    segs = {s["id"]: s for s in net["segments"]}
    p_b1 = segs["T"]["totalLoss"] + segs["B1"]["totalLoss"]
    p_b2 = segs["T"]["totalLoss"] + segs["B2"]["totalLoss"]
    p_b3 = segs["T"]["totalLoss"] + segs["B3"]["totalLoss"]
    assert p_b2 > p_b1 and p_b2 > p_b3
    assert net["criticalPath"] == ["T", "B2"]
    assert net["criticalTotalPressure"] == pytest.approx(p_b2, rel=1e-9)
    assert net["fanVelocityPressure"] == pytest.approx(segs["T"]["velocityPressure"], rel=1e-9)
    assert net["fanStaticPressure"] == pytest.approx(p_b2 - segs["T"]["velocityPressure"], rel=1e-9)
    by_leaf = {p["leaf"]: p for p in net["paths"]}
    assert by_leaf["B1"]["balancingExcess"] == pytest.approx(p_b2 - p_b1, rel=1e-9)


def test_static_regain_gives_decreasing_velocities_and_noise_flags() -> None:
    """Static regain sizing decelerates airflow downstream (v_trunk > v_mid > v_branch),
    and high velocities trigger noise velocity flags."""
    tree = [
        {"id": "T", "parent": None, "flow": 1.8, "length": 10.0, "role": "main"},
        {"id": "M1", "parent": "T", "flow": 1.1, "length": 10.0, "role": "branch"},
        {"id": "B1", "parent": "M1", "flow": 0.5, "length": 10.0, "role": "runout"},
    ]
    sized = air.size_duct_network(tree, system="supply", shape="round", method="staticRegain")
    v = {d["id"]: d["sizing"]["velocity"] for d in sized["ducts"]}
    assert v["T"] > v["M1"] > v["B1"]

    # Velocity reduction sizing & noise flag check
    vr = air.size_duct(0.6, "supply", "rect", method="velocityReduction", role="runout")
    assert vr["velocity"] <= 4.0 + 1e-9
    assert vr["noiseOk"] is True
    noisy = air.check_duct(
        0.6, {"shape": "rect", "width": 300, "height": 200}, "supply", role="runout"
    )
    assert noisy["velocity"] == pytest.approx(10.0)
    assert noisy["noiseOk"] is False
    assert "noise velocity limit exceeded" in noisy["noiseFlag"]


# ───────────────────────── 4. Duct auto-routing (RoomGraph + beam penalties) ─────────────────────────


def test_auto_route_3_room_corridor_graph_shortest_total_length() -> None:
    """Auto-route on a 3-room corridor graph reaches every room with the shortest total length.

    Layout (mm):
      Corridor C: x=0..12000, y=0..2000 (preferred)
      R1: x=0..4000,    y=2000..6000  (centre (2000, 4000))
      R2: x=4000..8000, y=2000..6000  (centre (6000, 4000))
      R3: x=8000..12000,y=2000..6000  (centre (10000, 4000))
      AHU at (500, 1000) in the corridor.

    Shortest corridor spine tree by hand:
      Trunk along y=1000: (500,1000) -> (2000,1000) -> (6000,1000) -> (10000,1000) = 9.5 m
      3 branches: (x,1000) -> (x,2000) -> (x,4000) = 3.0 m each x 3 = 9.0 m
      Total shortest length = 9.5 + 9.0 = 18.5 m.
    """
    places = [
        RoomPlace("C", box(0, 0, 12000, 2000), preferred=True),
        RoomPlace("R1", box(0, 2000, 4000, 6000), preferred=False),
        RoomPlace("R2", box(4000, 2000, 8000, 6000), preferred=False),
        RoomPlace("R3", box(8000, 2000, 12000, 6000), preferred=False),
    ]
    flows = {"R1": 0.20, "R2": 0.25, "R3": 0.15}
    routed = auto_route_ducts("GF", (500.0, 1000.0), flows, places)
    assert routed["totalLength"] == pytest.approx(18.5, abs=0.01)
    served = {d["room"] for d in routed["ducts"] if d.get("room")}
    assert served == {"R1", "R2", "R3"}
    assert routed["pressure"]["fanStaticPressure"] > 0
    assert routed["ceilingVoid"] is None  # architecture.ceiling_void absent -> skipped cleanly
    # Every routed segment validates as a 07 MEP Duct model (compatible with sizing & drawings)
    for d in routed["ducts"]:
        Duct.model_validate(d)


def test_auto_route_beam_penalty_avoids_beam_crossing() -> None:
    """When two corridor routes exist and one crosses a beam, beam_penalty picks the beam-free
    corridor route."""
    places = [
        RoomPlace("C1", box(0, 0, 4000, 4000), preferred=True),  # start here
        RoomPlace(
            "C_N", box(4000, 2000, 8000, 4000), preferred=True
        ),  # north corridor (beam crosses)
        RoomPlace("C_S", box(4000, 0, 8000, 2000), preferred=True),  # south corridor (clear)
        RoomPlace("R1", box(8000, 0, 12000, 4000), preferred=False),  # target room
    ]
    beam = BeamLine("B_N", (6000, 2000), (6000, 4000), top=3000, depth=600)
    graph = RoomGraph(places, beams=[beam], beam_penalty=20000.0, spine=True)
    routed = auto_route_ducts("GF", (1000.0, 2000.0), {"R1": 0.3}, graph)
    assert routed["beamsCrossed"] == []
    # Path goes through C_S (y ~ 1000) rather than C_N (y ~ 3000)
    all_y = [pt[1] for d in routed["ducts"] for pt in d["path"]]
    assert any(y <= 1500 for y in all_y)


def test_auto_route_ceiling_void_hook_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """If architecture.ceiling_void exists, auto_route_ducts checks and constrains duct height."""
    arch, bim = _corridor_arch_and_bim()
    rooms = room_inputs(arch, bim)
    monkeypatch.setattr(arch_lib, "ceiling_void", lambda a, s: 350.0, raising=False)
    routed = auto_route_ducts(
        "GF", (1000.0, 1000.0), {"R1": 0.4, "R2": 0.4, "R3": 0.4}, rooms, bim=bim, arch=arch
    )
    assert routed["ceilingVoid"] == pytest.approx(350.0)
    for d in routed["ducts"]:
        # 350 - 2*25 (insulation) - 50 (margin) = 250 mm max duct height
        assert d["height"] <= 250.0
