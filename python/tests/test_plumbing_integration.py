"""The plumbing of 7 MEP wired through the project: the RPC report (sizing, tank designs,
hydraulics, missing sleeves), the overhead tank's loads in the analysis model (never counted
twice), the bill of quantities, the IFC and the report chapter, on a copy of the shipped sample.

The sample's plumbing (synthetic): an office ground floor, a cold-water riser and a soil stack in
shaft SH1, the overhead tank T1 on the roof slab of Level 1 (inside 2200 x 1700 mm in two
compartments, 1400 mm of water, 150 mm walls, partition and base, 125 mm roof, C20.7), an
underground reservoir UGR1 west of the building and a septic tank SEP1 east of it. The soil is the synthetic uniform sand of test_integration_e56.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import ifcopenshell
import pytest

from saengine.library.mep import MepModel, parse
from saengine.mep.loads import plumbing_tank_equipment
from saengine.plumbing.project import DESIGNS_FILE, full_report, missing_sleeves, read_designs
from saengine.rpc import handlers

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"
SOIL = {
    "schema": "saengine.soilReport/1",
    "boreholes": [
        {
            "id": "BH1",
            "x": 6500,
            "y": 2500,
            "depth": 30000,
            "layers": [
                {
                    "top": 0,
                    "bottom": 30000,
                    "description": "Uniform medium dense sand (synthetic)",
                    "soilType": "sand",
                    "unitWeight": 18.0,
                }
            ],
            "spt": [{"depth": 1500 * k, "N": 10} for k in range(1, 21)],
        }
    ],
}

# T1 by hand (m): inside 2.2 x 1.7, 1.4 water + 0.25 freeboard = 1.65 high, walls, partition and
# base 0.15, roof 0.125; outside 2.5 x 2.0; the partition (1.7 x 0.15) inside the inside length.
T1_CONCRETE = (2 * (2.2 + 0.15) + 2 * (1.7 + 0.15) + 1.7) * 0.15 * 1.65 + 2.5 * 2.0 * (0.15 + 0.125)
T1_EMPTY = T1_CONCRETE * 24.0 + 2.5 * 2.0 * 1.0  # 24 kN/m³ and the 1 kPa roof finish
T1_WATER = (2.2 - 0.15) * 1.7 * 1.4 * 9.81


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sample(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("plumbing") / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    (root / "01 Soil Report" / "soil-report.json").write_text(json.dumps(SOIL), encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def report(sample: Path) -> dict:
    return handlers.plumbing_report(str(sample))


def test_the_report_joins_the_sizing_the_tank_designs_and_the_hydraulics(
    sample: Path, report: dict
) -> None:
    assert report["problems"] == []
    json.dumps(report, allow_nan=False)  # JSON the workbench can parse
    assert [t["id"] for t in report["tankDesigns"]] == ["T1", "UGR1", "SEP1"]
    assert not [d for d in report["tankDesigns"] if "error" in d]
    t1 = report["tankDesigns"][0]
    assert t1["quantities"]["concrete"] == pytest.approx(T1_CONCRETE, abs=0.01)
    assert t1["supportLoads"]["empty"] == pytest.approx(T1_EMPTY, abs=0.1)
    assert t1["supportLoads"]["water"] == pytest.approx(T1_WATER, abs=0.1)
    assert sum(t1["quantities"]["byDiameter"].values()) == pytest.approx(
        t1["quantities"]["reinforcement"], abs=1.0
    )
    # Both pipes run in the shaft: no sleeve is missing, and the check says so.
    assert report["sleeves"] == [] and report["sleevesProposed"] == 0
    (sleeves,) = [c for c in report["checks"] if c["name"] == "Sleeves for the risers and stacks"]
    assert sleeves["ok"]
    floors = {f["story"] for f in report["hydraulics"]["floors"]}
    assert floors == {"BASE"}
    # The storage check and the tank design hold the same water: UGR1 3.0 x 2.0 x 1.8 less its
    # 200 mm partition (2.0 x 0.2 x 1.8) = 10.08 m³; T1 (2.2 - 0.15) x 1.7 x 1.4 = 4.879 m³.
    provided = {t["id"]: t["provided"] for t in report["storage"]["tanks"]}
    assert provided == pytest.approx({"T1": 4.879, "UGR1": 10.08})
    names = {c["name"]: c for c in report["checks"]}
    assert names["T1 compartments"]["ok"] and names["UGR1 compartments"]["ok"]
    # The main fills the reservoir and the pump the roof tank (BNBC Sec 5.8.3): that the main
    # cannot reach the roof tank is reported, not a failing check.
    hydraulic = [c["name"] for c in report["hydraulics"]["checks"]]
    assert "City main fills the underground reservoir" in hydraulic
    assert not any(n.startswith("City main fills the roof") for n in hydraulic)
    assert report["hydraulics"]["mains"]["roofTank"]["applies"] is False
    assert report["hydraulics"]["pump"]["flow"] > 0
    assert set(report["sources"]) == {"mep", "bim", "soil", "materials", "settings"}
    # The designs are kept: the next report reads them instead of running OpenSees again.
    assert len(read_designs(sample)) == 3
    again = full_report(sample, hydraulics=False)
    assert again["tankDesigns"] == report["tankDesigns"]


def test_rpc_proposals_occupancies_and_bad_input(sample: Path) -> None:
    tanks = handlers.plumbing_size_tanks(str(sample))
    # The user's three, and the soak well the sand lets the septic tank drain to.
    assert [(t["id"], t["kind"]) for t in tanks["tanks"]][3:] == [("SW1", "soakWell")]
    assert [t["id"] for t in tanks["tanks"]][:3] == ["T1", "UGR1", "SEP1"]
    assert handlers.plumbing_sleeves(str(sample))["openings"] == []
    occupancies = {o["key"]: o for o in handlers.plumbing_occupancies()["occupancies"]}
    assert occupancies["residentialFlat"]["lpcd"] == 180
    assert occupancies["hotel"]["unit"] == "bed"
    assert handlers.plumbing_report(str(sample), mep_text="{")["problems"]
    assert handlers.plumbing_size_tanks(str(sample), mep_text="{")["problems"]


def test_missing_sleeves_are_those_no_opening_gives() -> None:
    mep = MepModel.model_validate(
        {
            "openings": [
                {
                    "id": "MY1",
                    "host": "S2",
                    "kind": "sleeve",
                    "shape": "circle",
                    "diameter": 150,
                    "position": {"x": 8000, "y": 1000},
                },
            ],
        }
    )
    proposed = [
        {"id": "PS-R2-L1", "host": "S2", "kind": "sleeve", "shape": "circle", "diameter": 125,
         "position": {"x": 8040, "y": 1000}},  # inside MY1 (75 mm radius)
        {"id": "PS-R3-L1", "host": "S2", "kind": "sleeve", "shape": "circle", "diameter": 125,
         "position": {"x": 8100, "y": 1000}},  # outside it
        {"id": "PS-R4-L1", "host": "S1", "kind": "sleeve", "shape": "circle", "diameter": 125,
         "position": {"x": 8000, "y": 1000}},  # another slab
    ]  # fmt: skip
    assert [s["id"] for s in missing_sleeves(mep, proposed)] == ["PS-R3-L1", "PS-R4-L1"]


def test_a_riser_outside_the_shaft_needs_a_sleeve(sample: Path, tmp_path: Path) -> None:
    mep = json.loads(_read(sample, "07 MEP/mep.json"))
    riser = mep["plumbing"]["risers"][0]
    riser.pop("shaft")
    riser["x"], riser["y"] = 8000, 1000  # on S2, clear of SH1
    text = json.dumps(mep)
    sleeves = handlers.plumbing_sleeves(str(sample), text)["openings"]
    assert [(s["id"], s["host"]) for s in sleeves] == [("PS-R1-L1", "S2")]
    report = full_report(sample, text, designs=False, hydraulics=False)
    (check,) = [c for c in report["checks"] if c["name"] == "Sleeves for the risers and stacks"]
    assert not check["ok"] and check["demand"] == 1
    # Once the editor has added it, it is no longer missing.
    mep["openings"].append(sleeves[0])
    assert handlers.plumbing_sleeves(str(sample), json.dumps(mep))["openings"] == []


def test_the_overhead_tank_loads_the_model_once(sample: Path) -> None:
    mep = parse(_read(sample, "07 MEP/mep.json"))
    (equipment,), notes = plumbing_tank_equipment(mep)
    assert equipment.kind == "tank" and equipment.story == "L1"
    assert equipment.emptyWeight == pytest.approx(T1_EMPTY, abs=0.1)
    assert equipment.operatingWeight - equipment.emptyWeight == pytest.approx(T1_WATER, abs=0.1)
    assert (equipment.length, equipment.width) == (2500, 2000)
    assert "T1: overhead tank" in notes[0]

    # Linked to an equipment tank, or standing where one is: that equipment carries it.
    tank = {"id": "EQ1", "kind": "tank", "story": "L1", "x": 9500, "y": 2500, "length": 2500,
            "width": 2000, "operatingWeight": 140, "emptyWeight": 88}  # fmt: skip
    data = json.loads(_read(sample, "07 MEP/mep.json"))
    data["equipment"] = [tank]
    assert plumbing_tank_equipment(MepModel.model_validate(data))[0] == []
    data["plumbing"]["tanks"][0]["equipment"] = "EQ1"
    linked, notes = plumbing_tank_equipment(MepModel.model_validate(data))
    assert linked == [] and "linked" in notes[0]
    # Without a water depth it cannot load the model yet.
    data = json.loads(_read(sample, "07 MEP/mep.json"))
    del data["plumbing"]["tanks"][0]["waterDepth"]
    assert plumbing_tank_equipment(MepModel.model_validate(data))[0] == []
    # Without its story (the library accepts it; the editor flags it) it is left out with a note,
    # and neither the derivation nor the MEP report fails.
    data = json.loads(_read(sample, "07 MEP/mep.json"))
    del data["plumbing"]["tanks"][0]["story"]
    none, notes = plumbing_tank_equipment(MepModel.model_validate(data))
    assert none == [] and "T1: an overhead tank with no story" in notes[0]
    assert handlers.mep_report(str(sample), json.dumps(data))["problems"] == []


def test_the_tank_weight_follows_its_construction(sample: Path) -> None:
    data = json.loads(_read(sample, "07 MEP/mep.json"))

    def empty(**tank: object) -> tuple[float, float]:
        data["plumbing"]["tanks"][0].update(tank)
        (item,), _ = plumbing_tank_equipment(MepModel.model_validate(data))
        return item.emptyWeight, item.operatingWeight - item.emptyWeight

    assert empty(construction="rc") == pytest.approx((T1_EMPTY, T1_WATER), abs=0.1)
    # Masonry: the walls and partition as burnt clay brick work, 19.1 kN/m³ (BNBC Table 6.2.2),
    # the base and roof concrete.
    walls = (2 * (2.2 + 0.15) + 2 * (1.7 + 0.15) + 1.7) * 0.15 * 1.65
    masonry = walls * 19.1 + (T1_CONCRETE - walls) * 24.0 + 2.5 * 2.0 * 1.0
    assert empty(construction="masonry") == pytest.approx((masonry, T1_WATER), abs=0.1)
    # Prefab: its own weight is the maker's; nil until entered.
    assert empty(construction="prefab")[0] < 0.1
    assert empty(construction="prefab", emptyWeight=2.5) == pytest.approx((2.5, T1_WATER), abs=0.1)


def test_the_linked_equipment_must_carry_the_designed_weight(sample: Path, report: dict) -> None:
    from saengine.plumbing.project import linked_weight_checks

    data = json.loads(_read(sample, "07 MEP/mep.json"))
    data["equipment"] = [
        {"id": "EQ1", "kind": "tank", "story": "L1", "x": 9500, "y": 2500, "length": 2500,
         "width": 2000, "operatingWeight": 60, "emptyWeight": 8},
    ]  # fmt: skip
    data["plumbing"]["tanks"][0]["equipment"] = "EQ1"
    (check,) = linked_weight_checks(MepModel.model_validate(data), report["tankDesigns"])
    assert check["name"] == "T1 weight in the analysis (EQ1)" and not check["ok"]
    assert check["demand"] == pytest.approx(T1_EMPTY + T1_WATER, abs=0.2)
    data["equipment"][0].update(operatingWeight=150, emptyWeight=100)
    (check,) = linked_weight_checks(MepModel.model_validate(data), report["tankDesigns"])
    assert check["ok"]


def test_the_derivation_takes_the_tank_as_sd_and_f(sample: Path) -> None:
    def derive(mep_text: str) -> dict:
        result = handlers.derive_fem(
            _read(sample, "06 BIM/bim.json"),
            _read(sample, "04 Objects/objects.json"),
            _read(sample, "03 Materials/materials.json"),
            _read(sample, "02 Project Settings/project-settings.json"),
            str(sample / "08 FEM"),
            mep_text=mep_text,
        )
        assert "text" in result, result.get("problems")
        return result

    def vertical(project: dict, case: str) -> float:
        pattern = next((p for p in project["load_patterns"] if p["name"] == case), None)
        return -sum(n["forces"][2] for n in pattern["nodal_loads"]) / 1e3 if pattern else 0.0

    text = _read(sample, "07 MEP/mep.json")
    with_tank = derive(text)
    project = json.loads(with_tank["text"])
    assert vertical(project, "F") == pytest.approx(T1_WATER, abs=0.1)
    # Without its tanks (the shaft still cut) the SD differs by the tank's empty weight.
    data = json.loads(text)
    data["plumbing"]["tanks"] = data["plumbing"]["tanks"][1:]
    without = json.loads(derive(json.dumps(data))["text"])
    assert vertical(project, "SD") - vertical(without, "SD") == pytest.approx(T1_EMPTY, abs=0.1)
    assert any("T1: overhead tank" in n for n in with_tank["notes"])
    from saengine.fem.derive import mep_stamp

    assert f"mep={mep_stamp(text)}" in project["meta"]["description"]


def test_mep_stamp_of_the_plumbing_tanks_matches_the_workbench() -> None:
    """The same text and stamp are in femDerivationBar.test.ts (mepModelStamp): an overhead tank
    is part of the stamp, a ground tank is not."""
    from saengine.fem.derive import mep_stamp

    text = (
        '{"schema": "saengine.mep/1", "equipment": [], "plumbing": {"stories": [{"story": '
        '"L1"}], "tanks": [{"id": "T1", "kind": "overhead", "story": "L3", "x": 9500, "y": '
        '2500.5, "length": 2200}, {"id": "SEP1", "kind": "septic", "x": 1, "y": 2}]}}'
    )
    assert mep_stamp(text) == "9f99e0976f7ef4f8b747aba3e8cb4e054ea1c3ed"
    assert mep_stamp(text.replace("2500.5", "2600")) != mep_stamp(text)
    assert mep_stamp(text.replace('"x": 1,', '"x": 5,')) == mep_stamp(text)
    # Without overhead tanks the stamp is the one of the equipment, openings and shafts alone.
    assert mep_stamp('{"schema": "saengine.mep/1", "equipment": []}') == (
        "93870af7da97116c102a976ef591387cb469432b"
    )


def test_bill_ifc_and_report_chapter(sample: Path, report: dict) -> None:
    assert (sample / DESIGNS_FILE).exists()  # written by the report above
    texts = [
        _read(sample, p)
        for p in (
            "06 BIM/bim.json",
            "04 Objects/objects.json",
            "03 Materials/materials.json",
            "09 Substructure/substructure.json",
            "02 Project Settings/project-settings.json",
            "07 MEP/mep.json",
        )
    ]
    boq = json.loads(handlers.compute_boq(*texts, str(sample))["text"])
    items = {i["description"]: i for i in boq["items"]}
    assert items["Concrete C24.1 in water and septic tanks"]["quantity"] == pytest.approx(
        T1_CONCRETE, abs=1e-3
    )
    # UGR1 (2.35 m deep, 4.6 x 3.6 m with its toe and working space) and SEP1 (1.7 m, 4.6 x 2.2)
    assert items["Excavation for ground tanks"]["quantity"] == pytest.approx(
        2.35 * 4.6 * 3.6 + 1.7 * 4.6 * 2.2, abs=1e-2
    )
    assert items["Pipes, cold water, Ø50 mm PPR"]["quantity"] == pytest.approx(3.2)
    assert items["Pipes, soil, Ø100 mm uPVC"]["quantity"] == pytest.approx(3.2)
    assert items["Sanitary fixtures: water closets"]["quantity"] == 2
    assert items["Sanitary fixtures: kitchen sinks"]["quantity"] == 1
    bars = sum(
        e["quantity"]
        for i in boq["items"]
        if i["group"] == "reinforcement"
        for e in i["breakdown"]
        if e.get("detail") == "tank design"
    )
    designed = sum(d["quantities"]["reinforcement"] for d in report["tankDesigns"])
    assert bars == pytest.approx(designed, rel=0.01)
    # Without the project folder the bars are not measured, and the bill says so.
    bare = json.loads(handlers.compute_boq(*texts)["text"])
    assert any("T1: its bars are not measured" in n for n in bare["notes"])

    ifc = handlers.building_ifc(*texts[:3], "Sample", mep_text=texts[5])
    path = sample.parent / "plumbing.ifc"
    path.write_text(ifc["text"], encoding="utf-8")
    model = ifcopenshell.open(str(path))
    tanks = {t.Tag: t for t in model.by_type("IfcTank")}
    assert sorted(tanks) == ["SEP1", "T1", "UGR1"]

    def profile(product: object) -> tuple[float, float]:
        item = product.Representation.Representations[0].Items[0]
        return round(item.SweptArea.XDim), round(item.SweptArea.YDim)  # mm

    # As designed and billed: outside = inside + 2 walls (the partition inside), UGR1's base with
    # its 300 mm toe as its own slab.
    assert profile(tanks["T1"]) == (2500, 2000)
    assert profile(tanks["UGR1"]) == (3400, 2400)
    (base,) = [s for s in model.by_type("IfcSlab") if s.Tag == "UGR1-base"]
    assert profile(base) == (4000, 3000)
    pipes = {p.Tag: p for p in model.by_type("IfcPipeSegment")}
    assert sorted(pipes) == ["R1", "SS1"] and pipes["R1"].Description == "DN50 coldWater PPR"
    assert ifc["skipped"] == []

    from saengine.report.build import _Parts, _plumbing

    chapter = _plumbing(_Parts(sample, []))
    assert chapter["available"] and not chapter["problem"]
    assert [d["id"] for d in chapter["designs"]] == ["T1", "UGR1", "SEP1"]
    assert [row[0] for row in chapter["stories"]] == ["BASE"]
    assert chapter["failed"] == sum(chapter["checkFails"]) + sum(
        d.get("failed", 0) for d in chapter["designs"]
    )
    assert all(math.isfinite(float(row[1].replace(",", ""))) for row in chapter["checks"]
               if row[1] != "–")  # fmt: skip
