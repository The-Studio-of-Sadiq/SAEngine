"""The plumbing report of a project on disk: API, proposals in 07 MEP format, sleeves."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from saengine.library.mep import MEP_FILE, MepModel, Opening, PlumbingTank, parse
from saengine.plumbing.report import (
    overhead_equipment,
    plumbing_report,
    plumbing_size_tanks,
    plumbing_sleeves,
)
from saengine.plumbing.sleeves import outside_diameter, sleeve_diameter
from saengine.verification.cases.plumbing import six_storey, six_storey_plumbing

SAMPLE = Path(__file__).parents[2] / "workbench/resources/saengine/samples/Sample Frame"


def _project(tmp_path: Path) -> Path:
    mep, bim = six_storey()
    (tmp_path / "06 BIM").mkdir()
    (tmp_path / "07 MEP").mkdir()
    (tmp_path / "06 BIM/bim.json").write_text(bim.model_dump_json(by_alias=True))
    (tmp_path / MEP_FILE).write_text(mep.model_dump_json(by_alias=True, exclude_none=True))
    return tmp_path


def test_report_of_the_six_storey_building(tmp_path: Path) -> None:
    report = plumbing_report(_project(tmp_path))
    assert report["problems"] == []
    assert report["demand"]["daily"] == pytest.approx(18000)
    assert report["storage"]["overhead"] == pytest.approx(9)
    risers = {r["id"]: r for r in report["risers"]}
    assert set(risers) == {"R1", "R2", "S1", "S2", "W1", "W2", "V1", "P1", "RW1", "RW2"}
    assert risers["R1"]["diameter"] == 100 and risers["S1"]["diameter"] == 100
    assert risers["RW1"]["diameter"] == 65
    assert report["septic"]["volume"] == pytest.approx(16000)
    for check in report["checks"]:
        assert set(check) == {"name", "demand", "capacity", "unit", "utilisation", "ok", "note"}
    # Flagged since walkthrough 2 (not checked before): T1, the verification case's 9 m³
    # overhead tank, stands in the middle of a roof panel without beams under it (N-E1); the
    # proposed soak wells take an 18 m run of ground beside the 14 m wide building (N-E6).
    failing = {c["name"]: c for c in report["checks"] if not c["ok"]}
    assert set(failing) == {"T1 support", "Soak wells' ground"}, failing
    assert "kPa over its footprint" in failing["T1 support"]["note"]
    assert failing["Soak wells' ground"]["demand"] == pytest.approx(18.0)
    json.dumps(report)  # serialisable for the RPC


def test_proposed_tanks_are_valid_07_mep_tanks(tmp_path: Path) -> None:
    tanks = plumbing_size_tanks(_project(tmp_path))
    by_id = {t["id"]: t for t in tanks}
    for t in tanks:
        PlumbingTank.model_validate(t)
        assert t["sized"]
    assert by_id["T1"]["length"] == 3650 and by_id["T1"]["width"] == 1750
    assert by_id["T3"]["kind"] == "septic" and by_id["T3"]["length"] == 5250
    assert [t["id"] for t in tanks if t["kind"] == "soakWell"] == ["T4", "SW1", "SW2"]
    # The proposals go back into 07 MEP as they are.
    data = six_storey_plumbing()
    data["tanks"] = tanks
    MepModel.model_validate({"plumbing": data})
    equipment = overhead_equipment(by_id["T1"])
    # (3.65 less its 150 mm partition) x 1.75 x 1.5 m of water = 90.1 kN, plus the 150 mm
    # concrete shell this estimate takes.
    water = (3.65 - 0.15) * 1.75 * 1.5 * 9.81
    assert equipment["operatingWeight"] - equipment["emptyWeight"] == pytest.approx(water, abs=0.1)
    assert equipment["kind"] == "tank" and equipment["story"] == "ROOF"


def test_sleeves(tmp_path: Path) -> None:
    sleeves = plumbing_sleeves(_project(tmp_path))
    by_id = {s["id"]: s for s in sleeves}
    for s in sleeves:
        Opening.model_validate(s)
    # R1 crosses L1 ... ROOF; through the roof slab it is a 100 mm uPVC pipe, 110 mm outside:
    # 110 + 50 = 160 -> 200 mm sleeve, hosted by the roof slab.
    roof = by_id["PS-R1-ROOF"]
    assert roof["host"] == "S-ROOF" and roof["diameter"] == 200
    assert roof["position"] == {"x": 3000.0, "y": 5000.0}
    assert by_id["PS-R1-L1"]["diameter"] == 80  # 19 mm, 25 OD + 50 = 75 -> 80
    assert sum(1 for s in sleeves if s["id"].startswith("PS-S1-")) == 6
    assert sleeve_diameter(100, "GI") == 200 and outside_diameter(100, "GI") == 114.3


def test_risers_in_a_shaft_need_no_sleeves(tmp_path: Path) -> None:
    root = _project(tmp_path)
    mep = parse((root / MEP_FILE).read_text())
    data = json.loads(mep.model_dump_json(by_alias=True, exclude_none=True))
    data["shafts"] = [{"id": "SH1", "outline": [[2500, 3000], [4000, 3000], [4000, 5500],
                                                [2500, 5500]], "fromStory": "GF",
                       "toStory": "ROOF"}]  # fmt: skip
    for r in data["plumbing"]["risers"]:
        if r["id"] in ("R1", "S1", "W1", "V1"):
            r["shaft"] = "SH1"
    text = json.dumps(data)
    sleeves = plumbing_sleeves(root, text)
    assert not any(s["id"].startswith(("PS-R1-", "PS-S1-", "PS-V1-")) for s in sleeves)
    report = plumbing_report(root, text)
    shaft = next(c for c in report["checks"] if c["name"] == "Shaft SH1 area")
    # R1 110 + S1 110 + W1 110 + V1 75 (outside) each + 100 mm, squared, in 1.5 x 2.5 m.
    need = 3 * 0.21**2 + 0.175**2
    assert shaft["demand"] == pytest.approx(need) and shaft["capacity"] == pytest.approx(3.75)
    assert shaft["ok"]


def test_old_files_and_sample(tmp_path: Path) -> None:
    root = tmp_path / "sample"
    shutil.copytree(SAMPLE, root)
    # An old file: the sample's 7 MEP without its plumbing (the sample's own plumbing is
    # tested in test_plumbing_integration.py).
    old = json.loads((root / MEP_FILE).read_text(encoding="utf-8"))
    del old["plumbing"]
    (root / MEP_FILE).write_text(json.dumps(old), encoding="utf-8")
    report = plumbing_report(root)
    assert report["notes"] == ["07 MEP has no plumbing section"]
    assert report["tanks"] == [] and report["sleeves"] == []
    broken = plumbing_report(root, '{"schema": "saengine.mep/1", "plumbing": {"x": 1}}')
    assert broken["problems"] and "not valid" in broken["problems"][0]
    # Without 06 BIM the sizing still runs on the stories' order.
    (tmp_path / "bare" / "07 MEP").mkdir(parents=True)
    mep, _ = six_storey()
    (tmp_path / "bare" / MEP_FILE).write_text(mep.model_dump_json(by_alias=True))
    bare = plumbing_report(tmp_path / "bare")
    assert bare["demand"]["daily"] == pytest.approx(18000)
    assert bare["sleeves"] == []


@pytest.mark.parametrize(
    "plumbing",
    [
        {},
        {
            "stories": [
                {"story": "L1", "occupancy": "residentialFlat", "fixtures": {"wc": 2, "basin": 2}}
            ]
        },
    ],
)
def test_zero_demand_does_not_fail(tmp_path: Path, plumbing: dict) -> None:
    root = _project(tmp_path)
    (root / MEP_FILE).write_text(json.dumps({"plumbing": plumbing}))
    report = plumbing_report(root)
    assert report["problems"] == []
    assert report["demand"]["daily"] == 0 and report["tanks"] == []
    assert any("daily demand is zero" in n for n in report["notes"])
    json.dumps(report)


def test_up_feed_proposes_no_roof_tank() -> None:
    from saengine.plumbing.report import plumbing_results

    mep, bim = six_storey()
    data = mep.plumbing.model_dump(mode="json", exclude_none=True)
    data["tanks"] = [t for t in data["tanks"] if t["id"] != "T1"]
    # Down-feed (default): the roof tank OHT1 is proposed and R1 is sized as down-feed.
    down = plumbing_results(MepModel.model_validate({"plumbing": data}), bim)
    assert "OHT1" in [t["id"] for t in down["tanks"]]
    assert all("up-feed" not in n for r in down["risers"] if r["id"] == "R1" for n in r["notes"])
    data["supply"]["feed"] = "up"
    up = plumbing_results(MepModel.model_validate({"plumbing": data}), bim)
    assert all(t["kind"] != "overhead" for t in up["tanks"])
    assert any("up-feed" in n for n in up["notes"])


def test_overhead_equipment_needs_a_story_and_dimensions() -> None:
    tank = {"id": "T1", "x": 0, "y": 0, "length": 3000, "width": 2000, "waterDepth": 1500}
    assert overhead_equipment(tank) is None
    assert overhead_equipment({**tank, "story": "ROOF", "waterDepth": None}) is None
    assert overhead_equipment({**tank, "story": "ROOF"})["kind"] == "tank"


def test_ground_defaults_to_zero_with_a_basement() -> None:
    from saengine.library.bim import BuildingModel
    from saengine.plumbing.report import plumbing_results

    mep, bim = six_storey()
    data = bim.model_dump(mode="json", by_alias=True)
    data["stories"].insert(0, {"id": "B1", "name": "B1", "elevation": -3000})
    heads = plumbing_results(mep, BuildingModel.model_validate(data))["storage"]["heads"]
    # L1 (+3 m) to L5 (+15 m) above the ground at 0, not above the basement floor.
    assert heads["highestFixtureLevel"] == pytest.approx(15.0)
    assert heads["lowestFixtureLevel"] == pytest.approx(3.0)
