"""The building model (06 BIM/bim.json)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from saengine.library import BuildingModel, ObjectLibrary, default_building_model
from saengine.library.check import check_library


def model(**sections: object) -> dict:
    return {**default_building_model().model_dump(mode="json", by_alias=True), **sections}


def column(
    id_: str = "C-A1", at: tuple[str, str] = ("A", "1"), base: str = "BASE", top: str = "L1"
) -> dict:
    return {"id": id_, "type": "C1", "at": {"x": at[0], "y": at[1]}, "base": base, "top": top}


OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            {
                "id": "C1",
                "name": "Column",
                "kind": "column",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
            },
            {
                "id": "B1",
                "name": "Beam",
                "kind": "beam",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 250, "yDim": 450},
            },
        ]
    }
)


def test_default_model_is_valid_and_round_trips() -> None:
    default = default_building_model()
    assert BuildingModel.model_validate(default.model_dump(mode="json", by_alias=True)) == default
    assert [g.label for g in default.grids.x + default.grids.y] == ["A", "B", "1", "2"]
    assert [(s.id, s.elevation) for s in default.stories] == [("BASE", 0), ("L1", 3200)]


def test_members_on_the_grid() -> None:
    placed = BuildingModel.model_validate(
        model(
            columns=[column()],
            beams=[
                {
                    "id": "B-A1-B1",
                    "type": "B1",
                    "story": "L1",
                    "start": {"x": "A", "y": "1"},
                    "end": {"x": "B", "y": "1", "dx": -200},
                }
            ],
        )
    )
    assert placed.check_objects(OBJECTS) == []


@pytest.mark.parametrize(
    ("sections", "message"),
    [
        ({"columns": [column(at=("Z", "1"))]}, "no X grid line 'Z'"),
        ({"columns": [column(at=("A", "9"))]}, "no Y grid line '9'"),
        ({"columns": [column(top="L9")]}, "no story 'L9'"),
        ({"columns": [column(base="L1", top="BASE")]}, "top story must be above its base story"),
        ({"columns": [column(), column()]}, "duplicate member ids: C-A1"),
        (
            {"grids": {"x": [{"label": "A", "position": 0}], "y": [{"label": "A", "position": 0}]}},
            "unique across both axes: A",
        ),
        (
            {
                "grids": {
                    "x": [{"label": "A", "position": 0}, {"label": "B", "position": 0}],
                    "y": [],
                }
            },
            "two X grid lines are at the same position",
        ),
        (
            {
                "stories": [
                    {"id": "S", "name": "a", "elevation": 0},
                    {"id": "T", "name": "b", "elevation": 0},
                ]
            },
            "same elevation",
        ),
    ],
)
def test_rules(sections: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        BuildingModel.model_validate(model(**sections))


def test_check_reports_member_types_and_rules() -> None:
    data = model(
        columns=[
            column(),
            {**column("C-B1", at=("B", "1")), "type": "B1"},
            {**column("C-A2", at=("A", "2")), "type": "X9"},
        ]
    )
    objects = OBJECTS.model_dump_json(by_alias=True)
    assert [p["message"] for p in check_library("bim", json.dumps(data), objects)] == [
        "C-B1: object type 'B1' is a beam, not a column",
        "C-A2: unknown object type 'X9'",
    ]
    broken = {
        **model(stories=[{"id": "BASE", "name": "Base", "elevation": 0}]),
        "columns": [column()],
    }
    assert [p["message"] for p in check_library("bim", json.dumps(broken))] == [
        "C-A1: no story 'L1'"
    ]
