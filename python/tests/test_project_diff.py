"""Tests for saengine.project.diff: semantic differences per part, in an engineer's words."""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import pytest

from saengine.project import diff
from saengine.project.diff import diff_file, diff_part, diff_values, part_for_path

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"


def load(relative: str) -> dict:
    return json.loads((SAMPLE / relative).read_text(encoding="utf-8"))


def whats(changes: list[dict]) -> list[str]:
    return [c["what"] for c in changes]


# A synthetic soil report (not a real client's).
SOIL = {
    "schema": "saengine.soilReport/1",
    "report": {"title": "Synthetic site", "consultant": "Test Geotech"},
    "groundLevel": 0,
    "boreholes": [
        {
            "id": "BH-1",
            "x": 0,
            "y": 0,
            "waterTable": 1500,
            "depth": 15000,
            "layers": [
                {"top": 0, "bottom": 3000, "soilType": "clay", "cu": 20, "unitWeight": 17.5},
                {"top": 3000, "bottom": 15000, "soilType": "sand", "phi": 30},
            ],
            "spt": [{"depth": 1500, "N": 4}, {"depth": 3000, "N": 7}, {"depth": 6000, "N": 11}],
        },
        {
            "id": "BH-2",
            "x": 12000,
            "y": 0,
            "waterTable": 1800,
            "depth": 15000,
            "layers": [{"top": 0, "bottom": 15000, "soilType": "silt", "phi": 28}],
            "spt": [{"depth": 3000, "N": 6}, {"depth": 6000, "N": 12}],
        },
    ],
}


def test_floor_plan_members_grids_and_slabs():
    before = load("05 Floor Plan/floor-plan.json")
    after = copy.deepcopy(before)
    after["beams"][0]["type"] = "B300x600"
    after["columns"] = [c for c in after["columns"] if c["id"] != "C3"]
    after["columns"].append(dict(before["columns"][0], id="C9"))
    after["grids"]["x"][1]["position"] = 6500
    after["slabs"][0]["thickness"] = 175
    changes = diff_values("floorPlan", before, after)
    assert whats(changes) == [
        "Grid line B: position 6000 → 6500 mm",
        "Column C9 added (C400x600)",
        "Column C3 removed (C400x600)",
        "Beam B1: section B300x500 → B300x600",
        "Slab S1: thickness set to 175 mm",
    ]
    assert [(c["kind"], c["id"]) for c in changes] == [
        ("changed", "B"),
        ("added", "C9"),
        ("removed", "C3"),
        ("changed", "B1"),
        ("added", "S1"),
    ]
    beam = changes[3]
    assert (beam["before"], beam["after"], beam["path"]) == (
        "B300x500",
        "B300x600",
        "beams[B1].type",
    )


def test_reordered_items_are_not_changes():
    before = load("05 Floor Plan/floor-plan.json")
    after = copy.deepcopy(before)
    after["columns"].reverse()
    after["beams"].insert(0, after["beams"].pop())
    assert diff_values("floorPlan", before, after) == []


def test_materials_strength():
    before = load("03 Materials/materials.json")
    after = copy.deepcopy(before)
    after["materials"][0]["concrete"]["fc"] = 24.1
    assert whats(diff_values("materials", before, after)) == ["Concrete C20.7: f'c 20.7 → 24.1 MPa"]


def test_objects_sections_and_reinforcement():
    before = load("04 Objects/objects.json")
    after = copy.deepcopy(before)
    after["objects"][0]["profile"]["xDim"] = 450
    after["objects"][0]["reinforcement"]["longitudinal"][0]["count"] = 12
    texts = whats(diff_values("objects", before, after))
    assert texts[0] == "Column type C400x600: profile width 400 → 450 mm"
    assert texts[1].startswith("Column type C400x600 reinforcement longitudinal perimeter")
    assert texts[1].endswith("10 → 12")


def test_settings_location_zone_combinations_and_loads():
    before = load("02 Project Settings/project-settings.json")
    after = copy.deepcopy(before)
    after["site"]["location"] = "chattogram"
    after["combinations"].append(dict(before["combinations"][0], name="1.2D+1.6L"))
    after["areaLoads"][0]["live"] = 3
    texts = whats(diff_values("settings", before, after))
    assert texts == [
        "Site location dhaka → chattogram (seismic zone 2 → 3)",
        "Area load FL: live 2.4 → 3 kN/m²",
        "Load combination 1.2D+1.6L added",
    ]


def test_soil_spt_and_layers():
    after = copy.deepcopy(SOIL)
    after["boreholes"][1]["spt"][1]["N"] = 9
    after["boreholes"][0]["layers"][0]["cu"] = 25
    after["boreholes"][0]["spt"].append({"depth": 9000, "N": 15})
    changes = diff_values("soil", SOIL, after)
    assert whats(changes) == [
        "BH-1 layer at 0 m: undrained shear strength cu 20 → 25 kPa",
        "BH-1 SPT at 9 m added",
        "BH-2 SPT at 6 m: N 12 → 9 blows/300 mm",
    ]
    assert changes[2]["id"] == "BH-2/6000"


def test_soil_borehole_added_and_water_table():
    after = copy.deepcopy(SOIL)
    after["boreholes"][0]["waterTable"] = 2000
    after["boreholes"].append(dict(SOIL["boreholes"][1], id="BH-3"))
    texts = whats(diff_values("soil", SOIL, after))
    assert texts[0].startswith("BH-1: water table") and texts[0].endswith("1500 → 2000 mm")
    assert texts[1] == "BH-3 added"


def test_substructure_foundation():
    before = load("09 Substructure/substructure.json")
    after = copy.deepcopy(before)
    after["foundations"][0]["thickness"] = 600
    after["foundations"][0]["reinforcement"]["bottomX"]["spacing"] = 125
    after["tieBeams"].append({"id": "TB1", "from": "F1", "to": "F2", "width": 250, "depth": 400})
    texts = whats(diff_values("substructure", before, after))
    assert texts[:2] == [
        "Foundation F1: thickness 500 → 600 mm",
        "Foundation F1: reinforcement bottom layer, X spacing 150 → 125 mm",
    ]
    assert texts[2] == "Tie beam TB1 added"


def test_mep_equipment_tanks_and_plant():
    before = load("07 MEP/mep.json")
    after = copy.deepcopy(before)
    after["plumbing"]["tanks"][0]["waterDepth"] = 1600
    after["hvac"]["plant"] = after["hvac"]["plant"][1:]
    after["equipment"].append(
        {
            "id": "GEN1",
            "kind": "generator",
            "story": "BASE",
            "x": 0,
            "y": 0,
            "length": 3000,
            "width": 1200,
            "height": 1800,
        }
    )
    changes = diff_values("mep", before, after)
    texts = whats(changes)
    assert texts[0] == "Equipment GEN1 added"
    assert texts[1].startswith("Tank T1: water depth") and texts[1].endswith("1400 → 1600 mm")
    assert texts[2] == "HVAC plant ODU1 removed"


def test_bim_ignores_source_revision():
    before = load("06 BIM/bim.json")
    after = copy.deepcopy(before)
    after["source"] = {"floorPlan": "0" * 40}
    assert diff_values("bim", before, after) == []
    after["elements"][0]["top"] = 3500
    assert whats(diff_values("bim", before, after)) == ["Column C1: top 3200 → 3500 mm"]


def test_structure_members():
    before = {
        "schema": "saengine.structure/1",
        "members": [
            {"id": "M1", "kind": "beam", "type": "B300x500", "start": "N1", "end": "N2"},
            {"id": "M2", "kind": "column", "type": "C400x400", "start": "N2", "end": "N3"},
        ],
    }
    after = copy.deepcopy(before)
    after["members"][0]["type"] = "B300x600"
    del after["members"][1]
    assert whats(diff_values("structure", before, after)) == [
        "Beam M1: section B300x500 → B300x600",
        "Column M2 removed (C400x400)",
    ]


def test_boq_quantity_unit():
    before = load("10 BOQ/boq.json")
    after = copy.deepcopy(before)
    after["items"][0]["quantity"] = 4.2
    texts = whats(diff_values("boq", before, after))
    assert texts[0] == "BOQ item E.01: quantity 3.14 → 4.2 m3"


def test_invalid_json_falls_back_to_text_summary():
    changes = diff_file("floorPlan", "05 Floor Plan/floor-plan.json", b'{"a": 1}', b'{"a": 2,,}\n')
    assert len(changes) == 1
    assert changes[0]["what"].startswith("floor-plan.json is not valid JSON; text:")
    assert changes[0]["lines"] == ['- {"a": 1}', '+ {"a": 2,,}']


def test_deeply_nested_json_falls_back_instead_of_failing():
    # 5000 levels: Windows' parser gives up (RecursionError -> text summary); Linux parses it
    # and summarises the content. Either way there is one change and no crash.
    deep = b"[" * 5000 + b"]" * 5000
    changes = diff_file("materials", "03 Materials/materials.json", b'{"a": 1}', deep)
    assert len(changes) == 1 and changes[0]["kind"] == "changed"


def test_json_too_deep_to_parse_gets_the_text_summary(monkeypatch: pytest.MonkeyPatch):
    def too_deep(text: str) -> object:
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(diff.json, "loads", too_deep)
    changes = diff_file("materials", "03 Materials/materials.json", b'{"a": 1}', b'{"a": 2}')
    assert len(changes) == 1 and changes[0]["kind"] == "changed"
    assert changes[0]["what"].startswith("materials.json")


def test_files_added_removed_binary_and_formatting():
    assert whats(diff_file("exports", "11 Exports/report.pdf", None, b"%PDF")) == [
        "PDF report.pdf added"
    ]
    assert whats(diff_file("exports", "11 Exports/plan.dxf", b"0\nSECTION\n", None)) == [
        "Drawing plan.dxf removed"
    ]
    assert whats(diff_file("exports", "11 Exports/report.pdf", b"%PDF-1", b"%PDF-2")) == [
        "PDF report.pdf modified"
    ]
    assert whats(
        diff_file("materials", "03 Materials/materials.json", b'{"a":1}', b'{\n\t"a": 1\n}')
    ) == ["materials.json: formatting only"]
    text = diff_file("floorPlan", "05 Floor Plan/plan.dxf", b"0\nA\n", b"0\nB\n")
    assert text[0]["what"] == "Drawing plan.dxf modified (1 line added, 1 removed)"


def test_diff_part_orders_main_file_first_and_summarises():
    before = load("05 Floor Plan/floor-plan.json")
    after = copy.deepcopy(before)
    after["beams"][0]["type"] = "B300x600"
    result = diff_part(
        "floorPlan",
        [
            ("05 Floor Plan/Underlays/a.dxf", None, b"0\n"),
            ("05 Floor Plan/floor-plan.json", json.dumps(before), json.dumps(after)),
        ],
    )
    assert result["part"] == "floorPlan" and result["title"] == "Floor Plan"
    assert [c["file"] for c in result["changes"]] == [
        "05 Floor Plan/floor-plan.json",
        "05 Floor Plan/Underlays/a.dxf",
    ]
    assert result["summary"] == "2 changes: Beam B1 changed; Drawing a.dxf added"
    assert diff_part("soil", [])["summary"] == "No changes"


def test_part_for_path():
    assert part_for_path("01 Soil Report/soil-report.json").id == "soil"
    assert part_for_path("05 Structural Model/structure.json").id == "structure"
    assert part_for_path("Sample Frame.saengine").id == "project"
    assert part_for_path("Notes/x.txt").id == "Notes"


def test_stable_ordering():
    before = load("05 Floor Plan/floor-plan.json")
    after = copy.deepcopy(before)
    for beam in after["beams"]:
        beam["type"] = "B250x450"
    first = diff_values("floorPlan", before, after)
    assert first == diff_values("floorPlan", copy.deepcopy(before), copy.deepcopy(after))
    assert [c["id"] for c in first] == [b["id"] for b in after["beams"]]


@pytest.mark.parametrize("changed", [500, 5000])
def test_five_thousand_elements_under_a_second(changed: int):
    before = {
        "schema": "saengine.floorPlan/1",
        "stories": [{"id": "L1", "elevation": 3000}],
        "beams": [
            {
                "id": f"B{i}",
                "type": "B300x500",
                "story": "L1",
                "start": {"x": "A", "y": str(i)},
                "end": {"x": "B", "y": str(i)},
            }
            for i in range(5000)
        ],
    }
    after = copy.deepcopy(before)
    for beam in after["beams"][:changed]:
        beam["type"] = "B300x600"
    text_b, text_a = json.dumps(before), json.dumps(after)
    diff_values("floorPlan", {}, {})  # load the schema outside the timing
    start = time.perf_counter()
    changes = diff_file("floorPlan", "05 Floor Plan/floor-plan.json", text_b, text_a)
    elapsed = time.perf_counter() - start
    assert len(changes) == changed
    assert elapsed < 1.0, f"{elapsed:.2f} s"


def test_large_repetitive_text_is_fast_and_counted_right():
    # A DXF-like export: short, highly repetitive lines, every 7th line changed.
    codes = ["0", "LINE", "8", "S-BEAM", "10", "20", "11", "21"]
    before = [codes[i % 8] if i % 2 == 0 else f"{(i * 37) % 1000}.5" for i in range(120_000)]
    after = [line + "1" if i % 7 == 0 else line for i, line in enumerate(before)]
    start = time.perf_counter()
    changes = diff_file(
        "exports",
        "11 Exports/Drawing plan.dxf",
        "\n".join(before).encode(),
        "\n".join(after).encode(),
    )
    elapsed = time.perf_counter() - start
    changed = len(range(0, 120_000, 7))
    assert changes[0]["what"] == (
        f"Drawing Drawing plan.dxf modified (about {changed} lines added, {changed} removed)"
    )
    assert elapsed < 1.0, f"{elapsed:.2f} s"
    # A small edit keeps the exact, ordered comparison.
    small = diff_file("exports", "11 Exports/notes.txt", b"a\nb\nc\nd\n", b"a\nB\nc\nd\ne\n")
    assert small[0]["what"] == "File notes.txt modified (2 lines added, 1 removed)"
    assert small[0]["lines"] == ["- b", "+ B", "+ e"]
