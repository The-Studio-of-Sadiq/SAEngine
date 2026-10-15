"""The building model (06 BIM/bim.json), generated from the floor plan."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from saengine.library import BuildingModel, FloorPlan, ObjectLibrary, default_floor_plan
from saengine.library.bim import generate, source_stamp
from saengine.library.check import check_library
from saengine.rpc.handlers import generate_building

PLAN = FloorPlan.model_validate(
    {
        **default_floor_plan().model_dump(mode="json", by_alias=True),
        "columns": [
            {"id": "C1", "type": "COL", "at": {"x": "A", "y": "1"}, "base": "BASE", "top": "L1"},
            {
                "id": "C2",
                "type": "COL",
                "at": {"x": "B", "y": "2", "dx": 100},
                "base": "BASE",
                "top": "L1",
                "rotation": 90,
            },
        ],
        "beams": [
            {
                "id": "B1",
                "type": "BM",
                "story": "L1",
                "start": {"x": "A", "y": "1"},
                "end": {"x": "B", "y": "1"},
            }
        ],
        "slabs": [
            {
                "id": "S1",
                "type": "SL",
                "story": "L1",
                "boundary": [{"x": "A", "y": "1"}, {"x": "B", "y": "1"}, {"x": "B", "y": "2"}],
            }
        ],
        "footings": [{"id": "F1", "type": "FT", "story": "BASE", "at": {"x": "A", "y": "1"}}],
    }
)


def test_default_is_empty_and_unbuilt() -> None:
    model = BuildingModel()
    assert (model.source, model.stories, model.elements) == (None, [], [])
    assert model.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "schema": "saengine.bim/2",
        "stories": [],
        "elements": [],
        "additions": {"slabOpenings": [], "wallOpenings": [], "stairs": [], "members": []},
        "supports": [],
    }


def test_generation_resolves_the_grid_and_story_levels() -> None:
    model = generate(PLAN, "stamp")
    dump = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert dump["source"] == {"floorPlan": "stamp"}
    assert [s["id"] for s in dump["stories"]] == ["BASE", "L1"]
    assert dump["elements"] == [
        {
            "id": "C1",
            "type": "COL",
            "source": "C1",
            "kind": "column",
            "position": [0.0, 0.0],
            "bottom": 0.0,
            "top": 3200.0,
            "rotation": 0.0,
        },
        {
            "id": "C2",
            "type": "COL",
            "source": "C2",
            "kind": "column",
            "position": [6100.0, 5000.0],
            "bottom": 0.0,
            "top": 3200.0,
            "rotation": 90.0,
        },
        {
            "id": "B1",
            "type": "BM",
            "source": "B1",
            "kind": "beam",
            "start": [0.0, 0.0],
            "end": [6000.0, 0.0],
            "elevation": 3200.0,
        },
        {
            "id": "S1",
            "type": "SL",
            "source": "S1",
            "kind": "slab",
            "boundary": [[0.0, 0.0], [6000.0, 0.0], [6000.0, 5000.0]],
            "elevation": 3200.0,
        },
        {
            "id": "F1",
            "type": "FT",
            "source": "F1",
            "kind": "footing",
            "position": [0.0, 0.0],
            "elevation": 0.0,
            "rotation": 0.0,
        },
    ]


def test_regeneration_replaces_generated_elements_and_keeps_the_models_own() -> None:
    own = {"id": "X1", "type": "COL", "kind": "column", "position": [1, 1], "bottom": 0, "top": 1}
    previous = BuildingModel.model_validate(
        {
            "elements": [
                own,
                {
                    "id": "OLD",
                    "type": "COL",
                    "source": "OLD",
                    "kind": "column",
                    "position": [9, 9],
                    "bottom": 0,
                    "top": 1,
                },
            ]
        }
    )
    model = generate(PLAN, "s2", previous)
    assert [e.id for e in model.elements] == ["C1", "C2", "B1", "S1", "F1", "X1"]
    clash = BuildingModel.model_validate({"elements": [{**own, "id": "C1"}]})
    with pytest.raises(ValueError, match="use ids of floor-plan members: C1"):
        generate(PLAN, "s3", clash)


@pytest.mark.parametrize(
    ("elements", "message"),
    [
        (
            [{"id": "A", "type": "T", "kind": "column", "position": [0, 0], "bottom": 3, "top": 1}],
            "top must be above its bottom",
        ),
        (
            [
                {"id": "A", "type": "T", "kind": "footing", "position": [0, 0], "elevation": 0},
                {"id": "A", "type": "T", "kind": "footing", "position": [1, 0], "elevation": 0},
            ],
            "duplicate element ids: A",
        ),
    ],
)
def test_rules(elements: list, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        BuildingModel.model_validate({"elements": elements})


def test_stamp_ignores_line_endings() -> None:
    assert source_stamp("a\r\nb\n") == source_stamp("a\nb\n")
    # The workbench's stamp of the same text must match (its test uses this digest too).
    assert source_stamp('{"schema": "é"}\r\n') == "15e949281f1007c264631f2230d308c121022828"


def test_generate_handler() -> None:
    text = json.dumps(PLAN.model_dump(mode="json", by_alias=True), indent="\t")
    result = generate_building(text, json.dumps({"schema": 1, "part": "bim"}))
    model = BuildingModel.model_validate_json(result["text"])
    assert model.source is not None and model.source.floorPlan == source_stamp(text)
    assert len(model.elements) == 5

    broken = json.loads(text)
    broken["columns"][0]["at"]["x"] = "Z"
    assert generate_building(json.dumps(broken), None) == {
        "problems": ["Floor plan: C1: no X grid line 'Z'"]
    }


def test_check_reports_element_types() -> None:
    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "COL",
                    "name": "Column",
                    "kind": "column",
                    "material": "C24.1",
                    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
                },
                {
                    "id": "BM",
                    "name": "Beam",
                    "kind": "beam",
                    "material": "C24.1",
                    "profile": {"shape": "rectangle", "xDim": 250, "yDim": 450},
                },
            ]
        }
    )
    text = generate(PLAN, "s").model_dump_json(by_alias=True)
    assert [p["message"] for p in check_library("bim", text, objects.model_dump_json())] == [
        "S1: unknown object type 'SL'",
        "F1: unknown object type 'FT'",
    ]
