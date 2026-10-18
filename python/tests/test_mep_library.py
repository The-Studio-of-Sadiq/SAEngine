"""The MEP model (07 MEP/mep.json): parsing, validation and references."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from saengine.library.bim import BuildingModel
from saengine.library.mep import SCHEMA_ID, MepModel, check, is_placeholder, parse

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"

FULL = {
    "schema": "saengine.mep/1",
    "equipment": [
        {
            "id": "EQ1",
            "name": "Overhead water tank",
            "kind": "tank",
            "story": "L3",
            "x": 3000,
            "y": 2500,
            "length": 2000,
            "width": 1500,
            "height": 1500,
            "operatingWeight": 60,
            "emptyWeight": 8,
            "rotation": 0,
            "loadAs": "area",
            "plinth": {"height": 150, "material": "C20.7"},
        }
    ],
    "openings": [
        {
            "id": "OP1",
            "host": "B1",
            "kind": "sleeve",
            "shape": "circle",
            "diameter": 150,
            "position": {"distance": 3000, "elevation": 250},
            "service": "DN150 drain",
        },
        {
            "id": "OP2",
            "host": "S1",
            "kind": "opening",
            "shape": "rectangle",
            "width": 400,
            "height": 300,
            "position": {"x": 2000, "y": 2000},
        },
    ],
    "shafts": [
        {
            "id": "SH1",
            "outline": [[1000, 1000], [2000, 1000], [2000, 1800], [1000, 1800]],
            "fromStory": "BASE",
            "toStory": "L3",
            "service": "Plumbing riser",
        }
    ],
    "ifcModels": [{"path": "07 MEP/plumbing.ifc", "discipline": "plumbing", "visible": True}],
}


def test_placeholder_and_empty_files_are_an_empty_model() -> None:
    # The placeholder a new project gets (inline: the sample's own mep.json now has content).
    placeholder = '{\n  "schema": 1,\n  "part": "mep"\n}\n'
    assert is_placeholder(json.loads(placeholder))
    assert parse(placeholder) == MepModel()
    assert parse("") == MepModel() and parse(None) == MepModel()


def test_round_trip() -> None:
    mep = parse(json.dumps(FULL))
    assert mep.schema_ == SCHEMA_ID
    assert mep.equipment[0].plinth.height == 150
    assert mep.openings[0].size == (150, 150)
    assert mep.openings[1].size == (400, 300)
    assert mep.contentsAs == "fluid"
    again = MepModel.model_validate(mep.model_dump(mode="json", by_alias=True))
    assert again == mep


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["openings"][0].pop("diameter"),
        lambda d: d["openings"][1].pop("height"),
        lambda d: d["openings"][0].update(position={"distance": 3000}),
        lambda d: d["equipment"][0].update(emptyWeight=80),
        lambda d: d["shafts"][0].update(id="EQ1"),
        lambda d: d["equipment"][0].update(kind="boiler"),
        lambda d: d.update(schema="saengine.mep/2"),
    ],
)
def test_invalid_files_are_rejected(change) -> None:
    data = json.loads(json.dumps(FULL))
    change(data)
    with pytest.raises(ValidationError):
        MepModel.model_validate(data)


def test_references_to_the_building_model() -> None:
    building = BuildingModel.model_validate_json(
        (SAMPLE / "06 BIM" / "bim.json").read_text(encoding="utf-8")
    )
    assert check(parse(json.dumps(FULL)), building) == []
    data = json.loads(json.dumps(FULL))
    data["equipment"][0]["story"] = "ROOF"
    data["openings"][0]["host"] = "C1"
    data["openings"][1]["position"] = {"distance": 1, "elevation": 1}
    data["shafts"][0]["toStory"] = "BASE"
    problems = check(MepModel.model_validate(data), building)
    assert problems == [
        "EQ1: no story 'ROOF'",
        "OP1: there is no beam, slab or wall 'C1'",
        "OP2: a slab opening needs x and y",
        "SH1: its top story must be above the story it starts at",
    ]
