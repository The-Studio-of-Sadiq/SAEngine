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


def _model(elements: list, additions: dict | None = None) -> BuildingModel:
    return BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
            ],
            "elements": elements,
            "additions": additions or {},
        }
    )


WALL = {
    "id": "W1",
    "kind": "wall",
    "type": "W",
    "start": [0, 0],
    "end": [5000, 0],
    "bottom": 0,
    "top": 3000,
}
SLAB = {
    "id": "S1",
    "kind": "slab",
    "type": "S",
    "boundary": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]],
    "elevation": 3000,
}


def test_openings_must_fit_their_host() -> None:
    model = _model(
        [WALL, SLAB],
        {
            "wallOpenings": [
                {
                    "id": "D1",
                    "host": "W1",
                    "offset": 4800,
                    "sill": 0,
                    "width": 1000,
                    "height": 2200,
                },
                {
                    "id": "D2",
                    "host": "W1",
                    "offset": 500,
                    "sill": 900,
                    "width": 900,
                    "height": 2400,
                },
                {"id": "D3", "host": "W1", "offset": 500, "sill": 0, "width": 900, "height": 2100},
            ],
            "slabOpenings": [
                {"id": "O1", "host": "S1", "x": 6000, "y": 1000, "xDim": 500, "yDim": 500},
                {"id": "O2", "host": "S1", "x": 2500, "y": 2000, "xDim": 500, "yDim": 500},
            ],
        },
    )
    problems = model.check_additions()
    assert any(p.startswith("D1: it runs past the end of wall W1") for p in problems)
    assert any(p.startswith("D2: it is taller than wall W1") for p in problems)
    assert any(p.startswith("O1: its centre (6000, 1000) is outside slab S1") for p in problems)
    assert not any(p.startswith(("D3", "O2")) for p in problems)


def test_model_checks_duplicates_and_unsupported_beams() -> None:
    column = {"kind": "column", "type": "C", "position": [0, 0], "bottom": 0, "top": 3000}
    beam = {"kind": "beam", "type": "B", "elevation": 3000}
    model = _model(
        [
            {**column, "id": "C1"},
            {**column, "id": "C2"},  # on top of C1
            {**beam, "id": "B1", "start": [0, 0], "end": [5000, 0]},  # a cantilever: accepted
            {**beam, "id": "B2", "start": [2500, 0], "end": [2500, 4000]},  # rests on B1
            {**beam, "id": "B3", "start": [9000, 9000], "end": [12000, 9000]},  # floating
        ]
    )
    assert model.check_model() == [
        "C2: it is drawn on top of C1 (same kind and place)",
        "B3: neither end rests on a column, wall or beam (an unsupported beam)",
    ]
