"""Fire protection of 7 MEP (BNBC 2020 Part 4): the occupancy rules, hand checks of the water,
the sprinkler demand and the hydraulics, the report, the loads, the bill and the sample."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from saengine.fire import tables as T
from saengine.fire.network import Net, fixed_head, size_for, velocity
from saengine.fire.report import fire_equipment, fire_report, fire_results
from saengine.fire.requirements import requirements
from saengine.fire.sprinklers import floor_sprinklers, hand_demand, schedule_size
from saengine.fire.summary import fire_failures, fire_summary_file, has_fire
from saengine.fire.supply import demand, pump_rating, pumps, standpipe_flow, support_loads
from saengine.library.mep import MEP_FILE, FireBuilding, MepModel
from saengine.plumbing.hydraulics import hazen_williams_loss
from saengine.verification.cases.fire import (
    high_rise,
    high_rise_bim,
    high_rise_fire,
    high_rise_objects,
)

SAMPLE = Path(__file__).parents[2] / "workbench/resources/saengine/samples/Sample Frame"


def _status(stories: list[dict[str, Any]], **kw: Any) -> dict[str, str]:
    options = {"height": 10.0, "storeys": 3, "top_occupied": 6.0, "building": FireBuilding(),
               "hydrant_choice": None, "detection_choice": None, **kw}  # fmt: skip
    rows = [{"undivided": s["area"], "level": 0.0, "sprinklered": None, **s} for s in stories]
    result = requirements(rows, **options)
    return {s["system"]: s["status"] for s in result["systems"]}


# ─────────────────────────────── occupancy rules (Part 4 Chapter 5) ───────────────────────────────


def test_flats_need_hydrants_only_when_high_rise() -> None:
    low = _status([{"story": "L1", "occupancy": "residentialFlat", "area": 400}])
    assert low["hydrant"] == "notRequired" and low["manualAlarm"] == "notRequired"
    high = _status([{"story": "L1", "occupancy": "residentialFlat", "area": 400}],
                   storeys=12, top_occupied=36.0)  # fmt: skip
    assert high["hydrant"] == "required" and high["manualAlarm"] == "required"  # Sec 5.3.2(b)


def test_dwelling_over_500_m2_alarm_and_extinguishers() -> None:
    small = _status([{"story": "GF", "occupancy": "singleFamily", "area": 450}])
    big = _status([{"story": "GF", "occupancy": "singleFamily", "area": 300},
                   {"story": "L1", "occupancy": "singleFamily", "area": 300}])  # fmt: skip
    assert small["manualAlarm"] == "notRequired"
    assert big["manualAlarm"] == "required" and big["extinguishers"] == "required"  # 5.3.1(b)


def test_office_extinguishers_or_hydrants_by_the_choice() -> None:
    rows = [{"story": "GF", "occupancy": "office", "area": 300}]
    plain = _status(rows, storeys=2)
    assert plain["extinguishers"] == "required" and plain["hydrant"] == "notRequired"  # 5.7(i)
    chosen = _status(rows, storeys=2, hydrant_choice=True)
    assert chosen["hydrant"] == "required"
    three = _status(rows, storeys=3)
    assert three["manualAlarm"] == "required"  # 5.7(ii): over 2 storeys


def test_underground_mercantile_needs_sprinklers() -> None:
    rows = [{"story": "B1", "occupancy": "largeShop", "area": 800, "level": -3.5},
            {"story": "GF", "occupancy": "largeShop", "area": 400, "undivided": 400}]  # fmt: skip
    status = _status(rows)
    assert status["sprinklers"] == "required" and status["automaticAlarm"] == "required"
    assert status["hydrant"] == "required"  # 5.8.2(ii): B1's 800 m² undivided over 500 m²


def test_moderate_industry_and_hazardous() -> None:
    small = _status([{"story": "GF", "occupancy": "industryModerate", "area": 700}])
    big = _status([{"story": "GF", "occupancy": "industryModerate", "area": 900}])
    assert small["hydrant"] == "notRequired" and big["hydrant"] == "required"  # 5.9.2(o)-(p)
    j = _status([{"story": "GF", "occupancy": "hazardChemical", "area": 200}])
    assert j["special"] == "required" and j["automaticAlarm"] == "required"  # 5.12


def test_fire_protection_plan() -> None:
    rows = [{"story": "GF", "occupancy": "shop", "area": 1000, "undivided": 1000, "level": 0.0,
             "sprinklered": None}]  # fmt: skip
    result = requirements(rows, height=4, storeys=1, top_occupied=0, building=FireBuilding(),
                          hydrant_choice=None, detection_choice=None)  # fmt: skip
    assert result["firePlan"]["required"]  # 5.1.6(d): mercantile over 930 m²
    assert "p346" in result["firePlan"]["reasons"][0]


# ─────────────────────────────── hand checks ───────────────────────────────


def test_reservoir_volume_by_hand() -> None:
    # light hazard-II, two standpipes and sprinklers, 60 m high: 62 min (Table 4.4.1)
    result = demand("lightII", 60.0, 2, True, True, 1500.0)
    flow = 1900 + 1000 + max(1900, 1500)
    assert result["flow"] == pytest.approx(flow)
    assert result["duration"] == 62
    assert result["volume"] == pytest.approx(flow * 62 / 1000)
    # standpipes alone: at most eight more counted (Sec 4.2.3.2)
    assert standpipe_flow("ordinaryI", 12)[0] == pytest.approx(1900 + 8 * 1000)


def test_sprinkler_demand_by_hand() -> None:
    hand = hand_demand("ordinaryII")
    assert hand["total"] == pytest.approx(8.1 * 139 + 946)
    floor = floor_sprinklers(600.0, "ordinaryI", "beams", (30.0, 20.0))
    assert floor["heads"] == 54  # 600 / 12.1 = 49.6; a 3.48 m grid over 30 x 20 m: 9 x 6
    assert floor["designHeads"] == math.ceil(139 / (600 / 54))
    assert schedule_size(54, "ordinaryI") == 88  # Table 4.4.5: 65 heads on 88 mm
    assert schedule_size(101, "lightI") == 100  # light hazard: no limit on 100 mm


def test_epanet_against_hazen_williams_by_hand() -> None:
    # two pipes in series, 1500 l/min: 80 m of 100 mm then 20 m of 75 mm steel, C 120
    q = 1500 / 60000
    hand = hazen_williams_loss(q, 0.1023, 80.0, 120.0) + hazen_williams_loss(q, 0.0779, 20.0, 120.0)
    net = Net(material="steel")
    for name in ("PUMP", "A", "B"):
        net.node(name, 0.0)
    net.pipe("P1", "PUMP", "A", 80.0, 100)
    net.pipe("P2", "A", "B", 20.0, 75)
    net.demands["B"] = 1500.0
    sol = fixed_head(net, {"B": 0.0})
    assert sol["head"] == pytest.approx(hand, rel=0.005)
    assert velocity(1500, 100) == pytest.approx(q / (math.pi * 0.1023**2 / 4))
    assert size_for(1500) == 88  # 75 mm: 5.2 m/s over the 5 m/s limit


def test_pumps_and_supports() -> None:
    assert pump_rating(2000)["rating"] == 2839 and pump_rating(2000)["discharge"] == 150
    assert pump_rating(9000)["count"] == 2
    sets = pumps(2000, 20.0, "diesel")
    main = sets[0]
    assert main["head"] == 27.8 and main["head"] * 9.807 >= T.PUMP_MIN_NET  # 272 kPa net
    assert sets[2]["duty"] == "jockey" and sets[2]["flow"] == pytest.approx(28.4)
    rows = support_loads({100: "riser", 50: "hanger"}, 3.5)
    hanger = next(r for r in rows if r["kind"] == "hanger")
    w = 5.4 + 1000 * math.pi * 0.0525**2 / 4
    assert hanger["load"] == pytest.approx((5 * w * 5 + 110) * 9.80665 / 1000, abs=0.005)


# ─────────────────────────────── the report ───────────────────────────────


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    mep, bim, objects = high_rise()
    return fire_results(mep, bim, objects)


def test_high_rise_report(report: dict[str, Any]) -> None:
    assert report["requirements"]["highRise"]
    assert report["demand"]["volume"] == pytest.approx(report["demand"]["flow"] * 75 / 1000)
    hyd = report["hydraulics"]
    assert hyd["governing"] == "combined"
    assert hyd["standpipe"]["outlets"][0]["pressure"] == pytest.approx(300.0, abs=0.5)
    assert hyd["sprinkler"]["least"] == pytest.approx(hyd["sprinkler"]["headFlow"], rel=0.01)
    assert hyd["flow"] == pytest.approx(report["demand"]["flow"])
    names = {c["name"]: c for c in report["checks"]}
    assert names["Standpipe risers"]["ok"] and not names["Fire reservoir"]["ok"]
    assert "p325" in names["Main fire pump"]["clause"]
    assert [p["duty"] for p in report["proposals"]["pumps"]] == ["main", "standby", "jockey"]
    assert report["proposals"]["tanks"][0]["kind"] == "underground"
    # sleeves: two risers through 11 floors each; the L3 main through three beams
    slab = [o for o in report["openings"] if o["id"].startswith("FS-")]
    beam = [o for o in report["openings"] if o["id"].startswith("FB-")]
    assert len(slab) == 22 and len(beam) == 3
    assert {s["kind"] for s in report["supports"]} == {"hanger", "support"}
    assert json.dumps(report)  # JSON-safe


def test_suction_lift_and_pump_room(report: dict[str, Any]) -> None:
    fire = high_rise_fire()
    fire["tanks"] = [{"id": "FT1", "kind": "underground", "x": -5000, "y": 12000,
                      "length": 16000, "width": 10000, "waterDepth": 2700, "freeboard": 300,
                      "construction": "rc", "topLevel": 150}]  # fmt: skip
    fire["pumps"] = [{"id": "FP1", "duty": "main", "story": "B1", "x": -5000, "y": 3000,
                      "flow": 5677, "head": 80}]  # fmt: skip
    fire["pumpRoom"]["outline"] = [[-10000, 0], [-1000, 0], [-1000, 7500], [-10000, 7500]]
    mep = MepModel.model_validate({"fire": fire})
    r = fire_results(mep, high_rise_bim(), high_rise_objects())
    names = {c["name"]: c for c in r["checks"]}
    assert names["Fire reservoir"]["ok"]
    assert names["FP1 duty"]["ok"] and names["Fire pump room"]["ok"]
    # water down to 150 - 125 - 300 - 2700 = -2975 mm; pump centre at -3.0 m: flooded
    assert names["No static suction lift"]["ok"]
    assert not names["Secondary (standby) fire pump"]["ok"]
    loads, notes = fire_equipment(mep)
    assert [e["id"] for e in loads] == ["EQ-FP1"] and loads[0]["vibrating"]
    assert any("ground tank" in n for n in notes)


def test_overhead_fire_tank_loads_the_structure_once() -> None:
    from saengine.mep.loads import services_by_discipline

    fire = high_rise_fire()
    fire["tanks"] = [{"id": "FT9", "kind": "overhead", "story": "ROOF", "x": 15000, "y": 10000,
                      "length": 4000, "width": 3000, "waterDepth": 1500, "freeboard": 300,
                      "construction": "rc", "walls": 200, "base": 200, "roof": 125}]  # fmt: skip
    mep = MepModel.model_validate({"fire": fire})
    groups, _ = services_by_discipline(mep)
    tank = groups["fire"]["FT9"]
    water = (4.0 - 0.2) * 3.0 * 1.5 * 9.81  # two compartments: the partition takes its share
    assert tank.operatingWeight - (tank.emptyWeight or 0) == pytest.approx(water, rel=0.01)
    # linked to an equipment of 07 MEP: left to it
    fire["tanks"][0]["equipment"] = "E1"
    mep = MepModel.model_validate({"fire": fire, "equipment": [
        {"id": "E1", "kind": "tank", "story": "ROOF", "x": 15000, "y": 10000, "length": 4400,
         "width": 3400, "operatingWeight": 300}]})  # fmt: skip
    groups, _ = services_by_discipline(mep)
    assert "FT9" not in groups["fire"]


def test_report_from_files_summary_and_bill(tmp_path: Path) -> None:
    from saengine.boq.quantities import compute_boq
    from saengine.library import default_material_library

    (tmp_path / "07 MEP").mkdir(parents=True)
    (tmp_path / "06 BIM").mkdir()
    (tmp_path / "04 Objects").mkdir()
    document = {"schema": "saengine.mep/1", "fire": high_rise_fire()}
    (tmp_path / MEP_FILE).write_text(json.dumps(document), encoding="utf-8")
    bim = high_rise_bim().model_dump_json(by_alias=True)
    objects = high_rise_objects().model_dump_json()
    (tmp_path / "06 BIM/bim.json").write_text(bim)
    (tmp_path / "04 Objects/objects.json").write_text(objects)
    result = fire_report(tmp_path, designs=False)
    assert not result["problems"]
    assert result["openingsProposed"] == len(result["openings"]) == 25
    assert has_fire(document)
    summary = fire_summary_file(document, result)
    assert summary["failed"] == fire_failures(result) > 0
    assert summary["openingsToAdd"] == 25
    materials = default_material_library().model_dump_json()
    bill = compute_boq(bim, objects, materials, mep_text=json.dumps(document))
    lines = {i["description"]: i for i in bill["items"] if i["group"] == "mep"}
    assert lines["Sprinkler heads, K80 standard spray"]["quantity"] == 54
    assert any(d.startswith("Fire pipes, black steel, DN150") for d in lines)
    assert any("Fire protection of 7 MEP" in n for n in bill["notes"])


def test_chapter(tmp_path: Path) -> None:
    from saengine.fire.chapter import fire_chapter

    (tmp_path / "07 MEP").mkdir(parents=True)
    (tmp_path / "06 BIM").mkdir()
    document = {"schema": "saengine.mep/1", "fire": high_rise_fire()}
    (tmp_path / MEP_FILE).write_text(json.dumps(document), encoding="utf-8")
    (tmp_path / "06 BIM/bim.json").write_text(high_rise_bim().model_dump_json(by_alias=True))
    chapter = fire_chapter(tmp_path, MepModel.model_validate(document), {})
    assert chapter["available"] and chapter["failed"] > 0
    assert chapter["systems"][3][1] == "required"  # hydrant
    assert len(chapter["checks"][0]) == 7


# ─────────────────────────────── the sample ───────────────────────────────


def test_sample_gets_extinguishers_only_and_no_new_loads() -> None:
    from saengine.library.mep import parse
    from saengine.mep.loads import services_equipment

    result = fire_report(SAMPLE, designs=False)
    assert not result["problems"]
    status = {s["system"]: s["status"] for s in result["requirements"]["systems"]}
    assert status["extinguishers"] == "required"  # Sec 5.7(i): extinguishers or hydrants
    assert status["hydrant"] == status["manualAlarm"] == "notRequired"
    assert result["stories"][0]["extinguishers"] == 1
    assert result["checks"] == []
    mep = parse((SAMPLE / MEP_FILE).read_text(encoding="utf-8"))
    without = mep.model_copy(update={"fire": None})
    assert [e.id for e in services_equipment(mep)[0]] == [
        e.id for e in services_equipment(without)[0]
    ]
