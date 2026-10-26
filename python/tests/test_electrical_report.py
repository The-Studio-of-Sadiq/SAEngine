"""The electrical report of a project on disk, its proposals and checks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.electrical.report import (
    electrical_equipment,
    electrical_openings,
    electrical_propose_equipment,
    electrical_report,
    electrical_results,
)
from saengine.library.mep import MEP_FILE, MepModel, parse
from saengine.verification.cases.electrical import (
    eight_storey,
    eight_storey_bim,
    eight_storey_electrical,
    eight_storey_objects,
)


def _project(root: Path, electrical: dict, **mep: object) -> Path:
    (root / "07 MEP").mkdir(parents=True)
    (root / "06 BIM").mkdir()
    (root / "04 Objects").mkdir()
    data = {"schema": "saengine.mep/1", **mep, "electrical": electrical}
    (root / MEP_FILE).write_text(json.dumps(data), encoding="utf-8")
    (root / "06 BIM/bim.json").write_text(eight_storey_bim().model_dump_json(by_alias=True))
    (root / "04 Objects/objects.json").write_text(eight_storey_objects().model_dump_json())
    return root


def test_report_from_files(tmp_path: Path) -> None:
    root = _project(tmp_path, eight_storey_electrical())
    report = electrical_report(root)
    assert not report["problems"]
    assert report["demand"]["connected"] == pytest.approx(401.0)
    assert report["supply"]["transformers"]["rating"] == 400
    assert report["openingsProposed"] == len(report["openings"]) == 11
    names = {c["name"]: c for c in report["checks"]}
    assert names["Transformer capacity"]["ok"]
    assert not names["Electrical shafts"]["ok"]  # 8 storeys: a shaft is required
    assert json.dumps(report)  # JSON-safe
    assert [p["id"] for p in electrical_propose_equipment(root)][:1] == ["TX1"]
    assert len(electrical_openings(root)) == 11


def test_openings_already_in_mep_are_not_proposed_again(tmp_path: Path) -> None:
    existing = [{"id": "X1", "host": "S-L1", "kind": "opening", "shape": "rectangle",
                 "width": 500, "height": 500, "position": {"x": 15000, "y": 7500}},
                {"id": "PE-CT1-BY-L4-6000-5000", "host": "BY-L4-6000-5000", "kind": "opening",
                 "shape": "rectangle", "width": 400, "height": 200,
                 "position": {"distance": 2500, "elevation": 250}}]  # fmt: skip
    root = _project(tmp_path, eight_storey_electrical(), openings=existing)
    ids = {o["id"] for o in electrical_openings(root)}
    assert "PE-ER1-L1" not in ids and "PE-CT1-BY-L4-6000-5000" not in ids
    assert len(ids) == 9


def test_invalid_and_missing_sections(tmp_path: Path) -> None:
    (tmp_path / "07 MEP").mkdir()
    (tmp_path / MEP_FILE).write_text('{"schema": "saengine.mep/1", "electrical": {"x": 1}}')
    assert "not valid" in electrical_report(tmp_path)["problems"][0]
    mep = parse('{"schema": "saengine.mep/1"}')
    assert mep.electrical is None
    assert electrical_results(mep)["notes"] == ["07 MEP has no electrical section"]


def test_references_and_room_checks() -> None:
    electrical = eight_storey_electrical()
    electrical["equipment"] = [
        {"id": "TX1", "kind": "transformer", "story": "GF", "x": 3000, "y": 3000,
         "rating": 400},
        {"id": "TX2", "kind": "transformer", "story": "GF", "x": 5000, "y": 3000,
         "rating": 400},
        {"id": "G1", "kind": "generator", "story": "L2", "x": 20000, "y": 3000, "rating": 200},
        {"id": "BAD", "kind": "ups", "story": "NOPE", "x": 0, "y": 0},
    ]  # fmt: skip
    electrical["rooms"] = [{"id": "SS", "kind": "substation", "story": "GF",
                            "outline": [[1000, 1000], [9000, 1000], [9000, 6000],
                                        [1000, 6000]]}]  # fmt: skip
    mep = MepModel.model_validate({"schema": "saengine.mep/1", "electrical": electrical})
    r = electrical_results(mep, eight_storey_bim(), eight_storey_objects())
    assert "BAD: no story 'NOPE'" in r["problems"]
    checks = {c["name"]: c for c in r["checks"]}
    # Two 400 kVA units 1550 mm long, centres 2 m apart: 450 mm < 1.5 m.
    assert not checks["TX1-TX2 spacing"]["ok"]
    assert checks["TX1-TX2 spacing"]["capacity"] == pytest.approx(450.0)
    assert not checks["G1 location"]["ok"]  # generator above the ground floor
    assert checks["SS area"]["capacity"] == pytest.approx(40.0)
    assert checks["SS area"]["demand"] == 100  # Table 8.1.23, 2 x 400 kVA
    assert not checks["SS area"]["ok"]
    # TX1 1550 x 1050 at (3000, 3000): 2225 - 1000 = 1225 mm to the west wall < 1.25 m.
    assert checks["TX1 clearance to the walls"]["capacity"] == pytest.approx(1225.0)
    assert not checks["TX1 clearance to the walls"]["ok"]
    # Entered transformers: no transformer proposed.
    assert not [p for p in r["equipment"] if p["kind"] == "transformer"]


def test_generator_and_substation_basement_rules() -> None:
    from saengine.electrical.rooms import basement_level, room_checks
    from saengine.plumbing.building import Building

    # Ground at +7.0 m: GF (0.0) is the second basement, L1 (3.5) the first, L2 the ground floor.
    building = Building.of(eight_storey_bim(), ground=7000)
    assert [basement_level(s, building) for s in ("GF", "L1", "L2")] == [2, 1, 0]
    equipment = [
        {"id": "G1", "kind": "generator", "story": "GF", "x": 20000, "y": 3000},
        {"id": "G2", "kind": "generator", "story": "L1", "x": 20000, "y": 3000},
        {"id": "TX1", "kind": "transformer", "story": "L1", "x": 3000, "y": 3000},
    ]

    def checks(voltage: str) -> dict:
        electrical = {**eight_storey_electrical(), "supply": {"voltage": voltage}}
        mep = MepModel.model_validate({"schema": "saengine.mep/1", "electrical": electrical})
        out = room_checks(mep.electrical, equipment, building, {}, set())
        return {c["name"]: c for c in out["checks"]}

    c = checks("11kV")
    assert not c["G1 location"]["ok"] and "basement 2" in c["G1 location"]["note"]
    assert c["G2 location"]["ok"]  # the first basement (preferably avoided)
    assert not c["TX1 location"]["ok"] and "11 kV/0.4 kV" in c["TX1 location"]["note"]
    c = checks("33kV")
    assert c["TX1 location"]["ok"] and "may be considered" in c["TX1 location"]["note"]


def test_fuel_is_contents_transformer_oil_dead_load() -> None:
    from saengine.electrical.supply import oil_weight
    from saengine.library.mep import Equipment

    electrical = eight_storey_electrical()
    electrical["equipment"] = [
        {"id": "TX1", "kind": "transformer", "story": "GF", "x": 3000, "y": 3000, "rating": 400},
        {"id": "FT1", "kind": "fuelTank", "story": "GF", "x": 25000, "y": 3000, "length": 750,
         "width": 750, "height": 1000, "operatingWeight": 3.3, "emptyWeight": 0.6},
    ]  # fmt: skip
    mep = MepModel.model_validate({"schema": "saengine.mep/1", "electrical": electrical})
    items = {i["id"]: i for i in electrical_equipment(mep)[0]}
    # 400 kVA: 17.7 kN with 550 l of oil at 880 kg/m³ = 4.75 kN -> 13.0 kN empty. The oil is
    # always there, part of the equipment: the transformer loads as dead load whole (BNBC 2020
    # Part 6 Sec 2.1.4 D, Sec 2.2.6); the diesel is a fluid of controllable height, F.
    assert oil_weight(550) == pytest.approx(0.55 * 880 * 9.81 / 1000)
    assert "emptyWeight" not in items["EQ-TX1"]
    assert items["EQ-TX1"]["operatingWeight"] == pytest.approx(17.7)
    assert items["EQ-FT1"]["emptyWeight"] == pytest.approx(0.6)
    assert all(Equipment.model_validate(i) for i in items.values())
    # The proposed fuel tank keeps its steel weight apart from the diesel.
    mep, bim, objects = eight_storey()
    proposals = {p["id"]: p for p in electrical_results(mep, bim, objects)["equipment"]}
    ft = proposals["FT1"]
    assert 0 < ft["emptyWeight"] < ft["operatingWeight"]
    assert 0 < proposals["TX1"]["emptyWeight"] < proposals["TX1"]["operatingWeight"]


def test_equipment_for_the_analysis_loads() -> None:
    electrical = eight_storey_electrical()
    electrical["equipment"] = [
        {"id": "TX1", "kind": "transformer", "story": "GF", "x": 3000, "y": 3000, "rating": 400},
        {"id": "G1", "kind": "generator", "story": "GF", "x": 20000, "y": 3000, "rating": 200},
        {"id": "LT1", "kind": "lvPanel", "story": "GF", "x": 9000, "y": 3000, "rating": 630,
         "equipment": "EQX"},
    ]  # fmt: skip
    data = {"schema": "saengine.mep/1", "electrical": electrical, "equipment": [
        {"id": "EQX", "kind": "other", "story": "GF", "x": 9000, "y": 3000, "length": 2000,
         "width": 1000, "operatingWeight": 12},
        {"id": "EQG", "kind": "generator", "story": "GF", "x": 20000, "y": 3000, "length": 3000,
         "width": 1200, "operatingWeight": 30},
    ]}  # fmt: skip
    items, notes = electrical_equipment(MepModel.model_validate(data))
    assert [i["id"] for i in items] == ["EQ-TX1"]  # LT1 linked, G1 under EQG
    assert items[0]["kind"] == "transformer"
    assert items[0]["operatingWeight"] == pytest.approx(1800 * 9.81 / 1000, 0.01)
    g1 = (
        "G1: stands where equipment EQG is; its weight is taken as EQG's (link them in 07 MEP, "
        "or delete EQG)"
    )
    assert notes == [g1, "LT1: its weight is that of equipment EQX"]


def test_mep_without_electrical_still_parses() -> None:
    mep, _, _ = eight_storey()
    again = MepModel.model_validate(mep.model_dump(mode="json", by_alias=True, exclude_none=True))
    assert again.electrical == mep.electrical
    with pytest.raises(ValueError, match="duplicate electrical ids"):
        MepModel.model_validate({"schema": "saengine.mep/1", "electrical": {
            "motors": [{"id": "A", "power": 1}], "trays": [
                {"id": "A", "story": "L1", "path": [[0, 0], [1, 0]], "width": 100}]}})  # fmt: skip


def test_summary_follows_the_supply_entered_and_flags_oversizing() -> None:
    # E9: an 11 kV supply with a 100 kVA transformer and a 50 kVA generator for a tiny load.
    from types import SimpleNamespace

    from saengine.electrical.report import _generator_line, _substation_line

    supply = SimpleNamespace(voltage="11kV")
    tx = SimpleNamespace(rating=100)
    line = _substation_line(False, supply, {}, [tx], 100.0, {"kva": 9.0})
    assert "No substation" not in line
    assert "oversized" in line and "0.4 kV supply would do" in line
    gen = {"kva": 50.0, "required": 1.0, "fuel": 86.0, "fuelHours": 8.0}
    line = _generator_line(gen, {"kw": 0.5}, [SimpleNamespace(rating=50)])
    assert line.count("50 kVA") == 1 and "entered" in line and "oversized" in line
    assert _substation_line(False, SimpleNamespace(voltage="0.4kV"), {}, [], 0.0, {"kva": 9.0})
