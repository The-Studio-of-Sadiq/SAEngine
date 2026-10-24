"""The floor plan (05 Floor Plan/floor-plan.json)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from saengine.library import FloorPlan, ObjectLibrary, default_floor_plan
from saengine.library.check import check_library


def model(**sections: object) -> dict:
    return {**default_floor_plan().model_dump(mode="json", by_alias=True), **sections}


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
    default = default_floor_plan()
    assert FloorPlan.model_validate(default.model_dump(mode="json", by_alias=True)) == default
    assert [g.label for g in default.grids.x + default.grids.y] == ["A", "B", "1", "2"]
    assert [(s.id, s.elevation) for s in default.stories] == [("BASE", 0), ("L1", 3200)]


def test_members_on_the_grid() -> None:
    placed = FloorPlan.model_validate(
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
        FloorPlan.model_validate(model(**sections))


def test_check_reports_member_types_and_rules() -> None:
    data = model(
        columns=[
            column(),
            {**column("C-B1", at=("B", "1")), "type": "B1"},
            {**column("C-A2", at=("A", "2")), "type": "X9"},
        ]
    )
    objects = OBJECTS.model_dump_json(by_alias=True)
    assert [p["message"] for p in check_library("floorPlan", json.dumps(data), objects)] == [
        "C-B1: object type 'B1' is a beam, not a column",
        "C-A2: unknown object type 'X9'",
    ]
    broken = {
        **model(stories=[{"id": "BASE", "name": "Base", "elevation": 0}]),
        "columns": [column()],
    }
    assert [p["message"] for p in check_library("floorPlan", json.dumps(broken))] == [
        "C-A1: no story 'L1'"
    ]


def test_underlays() -> None:
    plan = FloorPlan.model_validate(
        model(underlays=[{"story": "L1", "file": "Underlays/architect L1.DXF", "scale": 1000}])
    )
    assert (plan.underlays[0].dx, plan.underlays[0].visible) == (0, True)
    for underlays, message in [
        ([{"story": "L9", "file": "a.dxf"}], "no story 'L9'"),
        ([{"story": "L1", "file": "a.dxf"}, {"story": "L1", "file": "b.dxf"}], "one underlay"),
        ([{"story": "L1", "file": "../outside.dxf"}], "inside the 05 Floor Plan folder"),
        ([{"story": "L1", "file": "C:/plans/a.dxf"}], "inside the 05 Floor Plan folder"),
        ([{"story": "L1", "file": "plan.dwg"}], "should match pattern"),
    ]:
        with pytest.raises(ValidationError, match=message):
            FloorPlan.model_validate(model(underlays=underlays))


STORIES = [
    {"id": "BASE", "name": "Base", "elevation": 0},
    {"id": "L1", "name": "Level 1", "elevation": 3200},
    {"id": "L2", "name": "Level 2", "elevation": 6400},
    {"id": "L3", "name": "Level 3", "elevation": 9600, "similarTo": "L2"},
    {"id": "L4", "name": "Level 4", "elevation": 12800, "similarTo": "L2"},
]


def test_typical_floors() -> None:
    plan = FloorPlan.model_validate(model(stories=STORIES))
    assert [s.similarTo for s in plan.stories] == [None, None, None, "L2", "L2"]
    dumped = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "similarTo" not in dumped["stories"][2] and dumped["stories"][3]["similarTo"] == "L2"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"similarTo": "L9"}, "story L3: no story 'L9' to be similar to"),
        ({"similarTo": "L3"}, "story L3 cannot be similar to itself"),
    ],
)
def test_typical_floor_rules(change: dict, message: str) -> None:
    stories = [dict(s) for s in STORIES]
    stories[3].update(change)
    with pytest.raises(ValidationError, match=message):
        FloorPlan.model_validate(model(stories=stories))


def test_typical_floors_do_not_chain() -> None:
    stories = [dict(s) for s in STORIES]
    stories[4]["similarTo"] = "L3"
    with pytest.raises(ValidationError, match="L4 is similar to L3, which is itself similar to L2"):
        FloorPlan.model_validate(model(stories=stories))
