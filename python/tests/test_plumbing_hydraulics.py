"""Water-supply hydraulics (saengine.plumbing.hydraulics) against hand calculations.

Synthetic buildings: storeys 3 m apart unless stated, flats with flush tanks, uPVC risers
(Hazen-Williams C = 150). Hand Hazen-Williams in SI: hf = 10.67 L Q^1.852 / (C^1.852 D^4.87).
"""

from __future__ import annotations

import json
import math
import time

import pytest

from saengine.plumbing.hydraulics import (
    MAX_HEAD,
    fitting_length,
    floor_units,
    hazen_williams_loss,
    probable_demand,
    size_for_flow,
    velocity_limit,
    water_hydraulics,
)

G = 9.80665


def hw(q: float, d: float, length: float, c: float) -> float:
    """Textbook SI Hazen-Williams (10.67, 4.87): the hand reference."""
    return 10.67 * length * q**1.852 / (c**1.852 * d**4.87)


def building(n: int, h: float = 3000.0) -> dict:
    return {
        "stories": [{"id": f"L{i}", "name": f"Level {i}", "elevation": i * h} for i in range(n + 1)]
    }


FLAT = {"wc": 4, "basin": 4, "shower": 3, "kitchenSink": 2, "washingMachine": 1}


def tower(n: int, **supply) -> dict:
    """``n`` floors of flats (L0..L{n-1}) under a roof tank on L{n}, one riser, a reservoir."""
    return {
        "supply": {"source": "mains", "mainsHead": 8.0, **supply},
        "stories": [
            {"story": f"L{i}", "occupancy": "residentialFlat", "fixtures": FLAT} for i in range(n)
        ],
        "risers": [
            {
                "id": "R1",
                "system": "coldWater",
                "x": 5000,
                "y": 5000,
                "fromStory": "L0",
                "toStory": f"L{n - 1}",
                "material": "uPVC",
            }
        ],
        "tanks": [
            {
                "id": "OHT",
                "kind": "overhead",
                "story": f"L{n}",
                "x": 6000,
                "y": 5000,
                "length": 4000,
                "width": 3000,
                "waterDepth": 1500,
                "freeboard": 300,
                "base": 200,
            },
            {
                "id": "UGR",
                "kind": "underground",
                "story": None,
                "x": 2000,
                "y": 2000,
                "length": 5000,
                "width": 4000,
                "waterDepth": 2000,
                "topLevel": 150,
            },
        ],
    }


# ───────────────────────────────────── BNBC data ─────────────────────────────────────


def test_table_8_5_5_interpolation():
    # rows of BNBC Table 8.5.5: 20 -> 56.6, 40 -> 93.4 L/min (flush tanks)
    assert probable_demand(20) == pytest.approx(56.6)
    assert probable_demand(30) == pytest.approx((56.6 + 93.4) / 2)
    assert probable_demand(30, flush_valves=True) == pytest.approx((133.1 + 178.4) / 2)
    assert probable_demand(1000) == pytest.approx(795.7)
    # below 20 units: in proportion, at least the largest fixture's flow
    assert probable_demand(10) == pytest.approx(28.3)
    assert probable_demand(1, least=11.4) == pytest.approx(11.4)
    assert probable_demand(0) == 0.0


def test_floor_units_by_hand():
    # Table 8.O.1 (total): 4 WC x 5 + 3 showers x 4 + 2 kitchen sinks x 2; Table 8.5.4: 4
    # basins x 1, 1 washing machine x 3
    units, least, shower, minimum = floor_units({"fixtures": FLAT})
    assert units == pytest.approx(20 + 4 + 12 + 4 + 3)
    assert least == pytest.approx(11.4)  # Table 8.5.6: WC flush tank, shower head
    assert shower
    assert minimum == 19  # Table 8.5.6: WC flush tank, wash basin
    # flush valves: WC 10 (Table 8.O.1), at least 132 L/min and Ø25 (Table 8.5.6)
    units, least, shower, minimum = floor_units(
        {
            "fixtures": {
                "wc": 2,
                "basin": 2,
                "other": [{"name": "tap", "supplyUnits": 1, "count": 3}],
            }
        },
        flush_valves=True,
    )
    assert units == pytest.approx(2 * 10 + 2 * 1 + 3)
    assert least == pytest.approx(132.0)
    assert not shower and minimum == 25
    # cold units only (where there are hot-water risers): 4 x 5 + 4 x 0.75 + 3 x 3 + 2 x 1.5
    # + 2.25
    units, *_ = floor_units({"fixtures": FLAT}, column="cold")
    assert units == pytest.approx(20 + 3 + 9 + 3 + 2.25)
    # urinals: Table 8.5.6 pedestal urinal 56.8 L/min (flush tank and flushometer valve)
    for flush in (False, True):
        _, least, _, _ = floor_units({"fixtures": {"urinal": 2}}, flush_valves=flush)
        assert least == pytest.approx(56.8)


def test_velocity_limits_and_sizing():
    # Sec 5.10.1(c)(ii) as the plumbing sizing reads it: 13 mm 0.30 ... 50 mm 0.60, linear
    assert velocity_limit(25) == pytest.approx(0.30 + 12 / 37 * 0.30)
    assert velocity_limit(80) == pytest.approx(0.78)
    assert velocity_limit(150) == pytest.approx(1.15)
    # 1 L/s: Ø38 gives 0.88 m/s > 0.50; Ø50 0.51 m/s <= 0.60 and 0.60 m/100 m <= 1.6
    assert size_for_flow(0.001) == 50.0
    # Tables 8.O.2: at 50 mm an elbow 1.53 m, a gate valve 0.70 m, a branch tee 3.05 m
    assert fitting_length(50, {"elbow": 2, "gate": 1, "teeBranch": 1}) == pytest.approx(6.81)
    assert fitting_length(44, {"elbow": 1}) == pytest.approx((1.22 + 1.53) / 2)


# ───────────────────────────── a single pipe: WNTR vs hand ─────────────────────────────


def test_single_vertical_pipe_wntr_against_hazen_williams():
    from saengine.plumbing.hydraulics import _new_network, _solve

    q, d, length, c = 0.002, 0.040, 30.0, 150.0
    wn = _new_network()
    wn.add_reservoir("T", base_head=30.0)
    wn.add_junction("J", base_demand=q, elevation=0.0)
    wn.add_pipe("P", "T", "J", length=length, diameter=d, roughness=c)
    res = _solve(wn)
    loss = 30.0 - float(res.node["head"].iloc[0]["J"])
    hand = hw(q, d, length, c)
    assert loss == pytest.approx(hand, rel=0.005)
    assert hazen_williams_loss(q, d, length, c) == pytest.approx(hand, rel=0.005)
    # static: the pressure head at J is the 30 m drop less the friction
    assert float(res.node["pressure"].iloc[0]["J"]) == pytest.approx(30.0 - hand, rel=0.005)
    assert float(res.link["velocity"].iloc[0]["P"]) == pytest.approx(
        q / (math.pi * d**2 / 4), rel=1e-3
    )


def test_one_floor_under_a_tank_by_hand():
    # tank on L1 (10 m), base 200, water 1000: minimum level 10.2 + 0.05 = 10.25 m;
    # L0: 4 WC = 20 units -> 56.6 L/min; riser Ø25 at the tank; fixture 1 m above L0
    plumbing = {
        "stories": [{"story": "L0", "occupancy": "residentialFlat", "fixtures": {"wc": 4}}],
        "risers": [
            {
                "id": "R1",
                "system": "coldWater",
                "x": 0,
                "y": 0,
                "fromStory": "L0",
                "toStory": "L1",
                "diameter": 25,
            }
        ],
        "tanks": [
            {
                "id": "T",
                "kind": "overhead",
                "story": "L1",
                "x": 0,
                "y": 0,
                "length": 2000,
                "width": 2000,
                "waterDepth": 1000,
                "base": 200,
            }
        ],
    }
    r = water_hydraulics(building=building(1, 10000), mep={"plumbing": plumbing})
    assert not r["problems"]
    q = 56.6 / 60000
    c = 150.0
    header = 0.1 + 2 * 0.79 + 0.31  # Tables 8.O.2 at 25 mm: 2 elbows, a gate valve
    riser = 10.2 + 0.52  # tank bottom to L0, a run tee
    # branch sized for 0.6 m/s: 0.943 L/s needs 44.7 mm -> 50 mm; 10 m + 1 m rise + branch
    # tee 3.05 + gate 0.70 + 4 elbows 4 x 1.53
    branch = 10 + 1.0 + 3.05 + 0.70 + 4 * 1.53
    loss = hw(q, 0.025, header + riser, c) + hw(q, 0.050, branch, c)
    floor = r["floors"][0]
    assert floor["branchDiameter"] == 50
    assert floor["flow"] == pytest.approx(q * 1000, rel=1e-4)
    assert floor["head"] == pytest.approx(10.25 - loss - 1.0, rel=0.005)
    assert floor["takeoffHead"] == pytest.approx(10.25 - hw(q, 0.025, header + riser, c), rel=0.005)
    assert floor["velocity"] == pytest.approx(q / (math.pi * 0.025**2 / 4), rel=1e-3)
    assert floor["staticHead"] == pytest.approx(10.2 + 1.0)
    assert floor["ok"]
    # 1.92 m/s in Ø25 exceeds the 0.6 m/s of Sec 5.10.1(c)(ii)
    velocity = [c for c in r["checks"] if c["name"].startswith("Velocity in R1 at")]
    assert velocity and not velocity[0]["ok"]


# ───────────────────────────── floors, static heads, zones ─────────────────────────────


def test_static_head_per_floor_and_top_floors_short():
    r = water_hydraulics(building=building(10), mep={"plumbing": tower(10)})
    assert not r["problems"]
    # full water level: L10 30 m + base 0.2 + water 1.5 = 31.7 m
    full = 31.7
    floors = {f["story"]: f for f in r["floors"]}
    for i in range(10):
        f = floors[f"L{i}"]
        assert f["staticHead"] == pytest.approx(full - 3.0 * i)
        assert f["required"] == pytest.approx(55 / 9.80665, rel=1e-4)
    # heads rise down the riser by about a storey each (less the riser friction)
    heads = [floors[f"L{i}"]["head"] for i in range(10)]
    assert all(b > a for a, b in zip(heads[1:], heads[:-1], strict=True))
    # top floor: the shower 2 m above L9 is 0.75 m below the minimum water level (30.25 m)
    assert floors["L9"]["fixtureElevation"] == pytest.approx(29.0)
    assert not floors["L9"]["pressureOk"]
    assert floors["L0"]["pressureOk"]
    assert any("raise the tank OHT" in n for n in r["notes"])
    assert r["zones"] == []


def test_twenty_storeys_need_a_zone_break():
    r = water_hydraulics(building=building(20), mep={"plumbing": tower(20)})
    # full water level 60 + 0.2 + 1.5 = 61.7 m: the floors below 61.7 - 35 = 26.7 m (L8 at
    # 24 m and down) see more than 35 m
    floors = {f["story"]: f for f in r["floors"]}
    for i in range(20):
        assert floors[f"L{i}"]["staticOk"] == (61.7 - 3.0 * i <= MAX_HEAD)
    assert not floors["L8"]["staticOk"] and floors["L9"]["staticOk"]
    zones = r["zones"]
    assert len(zones) == 2
    assert zones[0]["stories"][-1] == "L9"
    assert zones[1]["stories"][0] == "L8"
    # the second zone's source: above the static minimum at L8 (24 + 2 m shower + 5.61 m),
    # by the friction of its own riser and branch; its top water level 1.45 m higher (the roof
    # tank's draw-down 61.7 - 60.25)
    second = zones[1]
    assert second["sourceLevel"] > 24 + 2.0 + 55 / 9.80665 + 0.05
    assert second["fullLevel"] == pytest.approx(second["sourceLevel"] + 1.45)
    assert second["tankBottom"] == pytest.approx(second["sourceLevel"] - 0.05)
    assert 0 <= second["minMargin"] < 0.01  # rounded up to 10 mm
    for z in zones:
        assert z["maxStaticHead"] <= MAX_HEAD + 1e-6
    # build the proposed intermediate tank and split the riser: every floor of the lower zone
    # then has the Table 8.5.6 pressure and at most 35 m of static head
    plumbing = tower(20)
    plumbing["risers"][0]["fromStory"] = "L9"
    plumbing["risers"].append(
        dict(plumbing["risers"][0], id="R2", fromStory="L0", toStory=second["stories"][0])
    )
    plumbing["tanks"].append(
        {
            "id": "IT",
            "kind": "overhead",
            "story": second["standsOn"],
            "x": 5000,
            "y": 5000,
            "length": 3000,
            "width": 3000,
            "waterDepth": 1500,
            "base": second["base"],
        }
    )
    again = water_hydraulics(building=building(20), mep={"plumbing": plumbing})
    lower = [f for f in again["floors"] if f["riser"] == "R2"]
    assert [f["story"] for f in lower] == second["stories"]
    assert all(f["pressureOk"] and f["staticOk"] for f in lower)
    assert lower[0]["head"] == pytest.approx(lower[0]["required"], abs=0.02)
    assert again["risers"][1]["fullLevel"] == pytest.approx(second["fullLevel"])
    assert again["zones"] == []
    assert any("pressure zones" in n for n in r["notes"])
    static = [c for c in r["checks"] if c["name"].startswith("Static head") and not c["ok"]]
    assert len(static) == 9  # L0..L8


# ─────────────────────────────────────── the pump ───────────────────────────────────────


def test_pump_total_dynamic_head_by_hand():
    plumbing = tower(5, pumpHours=6)
    plumbing["tanks"][0].update({"x": 10000, "y": 5000})
    plumbing["tanks"][1].update({"x": 0, "y": 0, "topLevel": 0, "roof": 150, "freeboard": 300})
    plumbing["risers"].append(
        {
            "id": "PM",
            "system": "pumpMain",
            "x": 0,
            "y": 5000,
            "fromStory": "L0",
            "toStory": "L5",
            "diameter": 50,
            "material": "GI",
        }
    )
    result = water_hydraulics(building=building(5), mep={"plumbing": plumbing})
    pump = result["pump"]
    # flow as the plumbing sizing's delivery pump: 5 floors x 2 flats x 5 persons x 180 lpcd
    # (Table 8.5.1(a) y1) = 9 m³/day in the 6 pumping hours given
    q = 9.0 / (6 * 3600)
    assert pump["daily"] == pytest.approx(9.0)
    assert pump["flow"] == pytest.approx(q * 1000, rel=1e-4)
    # reservoir bottom: 0 - roof 0.15 - freeboard 0.3 - water 2.0 = -2.45 m; inlet: 15 + 0.2 +
    # 1.5 + 0.3 = 17.0 m
    static = 17.0 - (-2.45)
    assert pump["staticLift"] == pytest.approx(static)
    # 15 m horizontal + 19.45 m vertical + check 6.10 + 2 gates 0.70 + 4 elbows 1.53 (Ø50)
    length = 15 + static + 6.10 + 2 * 0.70 + 4 * 1.53
    assert pump["equivalentLength"] == pytest.approx(length)
    hf = hw(q, 0.050, length, 120.0)  # GI
    v = q / (math.pi * 0.05**2 / 4)
    tdh = static + hf + v**2 / (2 * G) + 1.0
    assert pump["friction"] == pytest.approx(hf, rel=0.01)
    assert pump["velocity"] == pytest.approx(v, rel=1e-3)
    assert pump["tdh"] == pytest.approx(tdh, rel=0.002)
    assert pump["shaftPower"] == pytest.approx(1000 * G * q * tdh / 0.6 / 1000, rel=0.002)
    # 0.21 m/s in Ø50 is within 0.6 m/s
    check = next(c for c in result["checks"] if c["name"].startswith("Velocity in the pump"))
    assert check["ok"]


def test_pump_flow_is_the_peak_hourly_demand():
    # BNBC Sec 5.9.1.2(c)(ii): delivery pump = peak hourly demand; Eq 8.5.1: 9000 L/day / 16 h
    # x 2.2 = 1237.5 L/h
    pump = water_hydraulics(building=building(5), mep={"plumbing": tower(5)})["pump"]
    assert pump["flowM3h"] == pytest.approx(9.0 / 16 * 2.2, rel=1e-4)
    assert pump["pumpingHours"] == pytest.approx(16 / 2.2, rel=1e-3)  # BNBC: about 7-8 h
    assert "peak hourly demand" in pump["flowBasis"]
    # without a daily demand: twice the overhead volume (Sec 5.9.1.2(c)(i)), at its peak hour
    plumbing = tower(5)
    plumbing["stories"] = [dict(e, occupancy="hospital") for e in plumbing["stories"]]
    r = water_hydraulics(building=building(5), mep={"plumbing": plumbing})
    # OHT: no compartments given, so two (Sec 5.9.2.1) with a 200 mm partition taking its share
    # of the plan, as in the tank design: (4.0 - 0.2) x 3.0 x 1.5 = 17.1 m³
    assert r["pump"]["flowM3h"] == pytest.approx(2 * 17.1 / 16 * 2.2, rel=1e-4)
    assert any("twice the overhead tank volume" in n for n in r["notes"])
    # a given flow
    r = water_hydraulics(
        building=building(5), mep={"plumbing": tower(5)}, options={"pumpFlow": 60.0}
    )
    assert r["pump"]["flow"] == pytest.approx(1.0)


def test_tank_zero_base_is_kept():
    # a prefab tank set on the roof slab: base 0, outlet 50 mm above L3 (9 m)
    plumbing = tower(3)
    plumbing["tanks"][0]["base"] = 0
    r = water_hydraulics(building=building(3), mep={"plumbing": plumbing})
    assert r["risers"][0]["sourceLevel"] == pytest.approx(9.05)
    assert r["risers"][0]["fullLevel"] == pytest.approx(10.5)


# ─────────────────────────────────────── the main ───────────────────────────────────────


def test_city_main_checks():
    r = water_hydraulics(building=building(5), mep={"plumbing": tower(5, mainsHead=8.0)})
    mains = r["mains"]
    required = 55 / 9.80665
    # reservoir inlet at 0.15 - 0.15 = 0: needs 5.61 m; 8 m reaches it
    assert mains["reservoir"]["ok"]
    assert mains["reservoir"]["required"] == pytest.approx(required, rel=1e-4)
    # directly: L0 at 1 m (8 - 1 = 7 >= 5.61), L1 at 4 m (8 - 4 = 4 < 5.61)
    assert mains["directFloors"] == ["L0"]
    # roof tank inlet 15 + 0.2 + 1.5 + 0.3 = 17 m: out of reach
    assert not mains["roofTank"]["ok"]
    # with the reservoir and its pump (BNBC Sec 5.8.3) the main need not reach the roof tank or
    # feed the floors directly: reported, not checked
    assert mains["system"] == "reservoirAndPump" and mains["roofTank"]["applies"] is False
    names = [c["name"] for c in r["checks"]]
    assert "City main fills the underground reservoir" in names
    assert not any("roof tank" in n or "directly" in n for n in names if n.startswith("City"))
    # without a reservoir the roof tank must be filled by the main (Sec 5.8.2): a failing check
    plumbing = tower(5, mainsHead=8.0)
    plumbing["tanks"] = [t for t in plumbing["tanks"] if t["kind"] != "underground"]
    r = water_hydraulics(building=building(5), mep={"plumbing": plumbing})
    roof = next(c for c in r["checks"] if c["name"].startswith("City main fills the roof"))
    assert not roof["ok"] and r["mains"]["roofTank"]["applies"] is True
    r = water_hydraulics(building=building(5), mep={"plumbing": tower(5, mainsHead=None)})
    assert any("mains" in p or "main" in p for p in r["problems"])


def test_mains_fed_up_feed_without_a_roof_tank():
    plumbing = tower(3, mainsHead=20.0)
    plumbing["tanks"] = []
    r = water_hydraulics(building=building(3), mep={"plumbing": plumbing})
    assert not r["problems"]
    floors = {f["story"]: f for f in r["floors"]}
    # up feed from the main at 20 m: static head at L2's take-off 20 - 6 = 14 m
    assert floors["L2"]["staticHead"] == pytest.approx(14.0)
    assert floors["L0"]["head"] > floors["L2"]["head"]


# ─────────────────────────────── robustness and the API ───────────────────────────────


def test_old_mep_without_plumbing():
    r = water_hydraulics(building=building(3), mep={"schema": "saengine.mep/1", "equipment": []})
    assert r["floors"] == [] and r["problems"]


def test_riser_assumed_at_the_tank_and_project_folder(tmp_path):
    plumbing = tower(4)
    plumbing["risers"] = []
    (tmp_path / "06 BIM").mkdir()
    (tmp_path / "07 MEP").mkdir()
    (tmp_path / "02 Project Settings").mkdir()
    (tmp_path / "06 BIM" / "bim.json").write_text(json.dumps(building(4)), encoding="utf-8")
    (tmp_path / "07 MEP" / "mep.json").write_text(
        json.dumps({"schema": "saengine.mep/1", "plumbing": plumbing}), encoding="utf-8"
    )
    (tmp_path / "02 Project Settings" / "project-settings.json").write_text(
        json.dumps({"foundation": {"groundLevel": 0}}), encoding="utf-8"
    )
    r = water_hydraulics(tmp_path)
    assert [f["story"] for f in r["floors"]] == ["L3", "L2", "L1", "L0"]
    assert r["risers"][0]["id"] == "R-auto"
    assert any("assumed" in n for n in r["notes"])
    json.dumps(r)  # plain JSON for the RPC


def test_thirty_floors_fast():
    water_hydraulics(building=building(2), mep={"plumbing": tower(2)})  # import WNTR once
    plumbing = tower(30)
    plumbing["risers"].append(dict(plumbing["risers"][0], id="R2", x=15000))
    start = time.perf_counter()
    r = water_hydraulics(building=building(30), mep={"plumbing": plumbing})
    assert time.perf_counter() - start < 2.0
    assert len(r["floors"]) == 60
    # two risers share each floor's units
    assert r["floors"][0]["units"] == pytest.approx(43 / 2)
    assert len(r["zones"]) >= 4
