"""Tests for 2D drafting geometry on the floor plan."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from saengine.library import FloorPlan, default_floor_plan
from saengine.library.floorplan import (
    DraftArc,
    DraftCircle,
    DraftLine,
    DraftPolyline,
)


def model(**sections: object) -> dict:
    return {**default_floor_plan().model_dump(mode="json", by_alias=True), **sections}


def test_valid_shapes_of_every_kind_round_trip() -> None:
    shapes = [
        {
            "kind": "line",
            "id": "D1",
            "story": "L1",
            "start": [0.0, 0.0],
            "end": [6000.0, 5000.0],
        },
        {
            "kind": "polyline",
            "id": "D2",
            "story": "L1",
            "points": [[0.0, 0.0], [500.0, 1000.0]],
            "closed": False,
            "layer": "SURVEY",
        },
        {
            "kind": "polyline",
            "id": "D3",
            "story": "L1",
            "points": [[0.0, 0.0], [1000.0, 0.0], [1000.0, 500.0], [0.0, 500.0]],
            "closed": True,
        },
        {
            "kind": "arc",
            "id": "D4",
            "story": "BASE",
            "center": [3000.0, 2500.0],
            "radius": 500.0,
            "startAngle": 0.0,
            "endAngle": 90.0,
        },
        {
            "kind": "circle",
            "id": "D5",
            "story": "L1",
            "center": [1000.0, 1000.0],
            "radius": 250.0,
            "layer": "OUTLINE",
        },
    ]

    plan = FloorPlan.model_validate(model(drafting=shapes))
    assert len(plan.drafting) == 5

    assert isinstance(plan.drafting[0], DraftLine)
    assert plan.drafting[0].layer == "DRAFT"
    assert plan.drafting[0].start == [0.0, 0.0]
    assert plan.drafting[0].end == [6000.0, 5000.0]

    assert isinstance(plan.drafting[1], DraftPolyline)
    assert plan.drafting[1].layer == "SURVEY"
    assert plan.drafting[1].closed is False
    assert len(plan.drafting[1].points) == 2

    assert isinstance(plan.drafting[2], DraftPolyline)
    assert plan.drafting[2].closed is True
    assert len(plan.drafting[2].points) == 4

    assert isinstance(plan.drafting[3], DraftArc)
    assert plan.drafting[3].radius == 500.0
    assert plan.drafting[3].startAngle == 0.0
    assert plan.drafting[3].endAngle == 90.0

    assert isinstance(plan.drafting[4], DraftCircle)
    assert plan.drafting[4].radius == 250.0
    assert plan.drafting[4].layer == "OUTLINE"

    dumped = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    restored = FloorPlan.model_validate(dumped)
    assert restored == plan


def test_bad_story_refused() -> None:
    with pytest.raises(ValidationError, match="draft D1: no story 'L9'"):
        FloorPlan.model_validate(
            model(
                drafting=[
                    {
                        "kind": "line",
                        "id": "D1",
                        "story": "L9",
                        "start": [0, 0],
                        "end": [100, 100],
                    }
                ]
            )
        )


def test_duplicate_id_refused() -> None:
    with pytest.raises(ValidationError, match="duplicate draft ids: D1"):
        FloorPlan.model_validate(
            model(
                drafting=[
                    {
                        "kind": "line",
                        "id": "D1",
                        "story": "L1",
                        "start": [0, 0],
                        "end": [100, 100],
                    },
                    {
                        "kind": "circle",
                        "id": "D1",
                        "story": "L1",
                        "center": [0, 0],
                        "radius": 50,
                    },
                ]
            )
        )


def test_draft_id_equal_to_member_id_refused() -> None:
    with pytest.raises(ValidationError, match="draft ids clash with member ids: C1"):
        FloorPlan.model_validate(
            model(
                columns=[
                    {
                        "id": "C1",
                        "type": "C1",
                        "at": {"x": "A", "y": "1"},
                        "base": "BASE",
                        "top": "L1",
                    }
                ],
                drafting=[
                    {
                        "kind": "line",
                        "id": "C1",
                        "story": "L1",
                        "start": [0, 0],
                        "end": [100, 100],
                    }
                ],
            )
        )


@pytest.mark.parametrize(
    "invalid_coord",
    [float("nan"), float("inf"), float("-inf")],
)
def test_non_finite_coordinate_refused(invalid_coord: float) -> None:
    with pytest.raises(ValidationError, match="Input should be a finite number"):
        FloorPlan.model_validate(
            model(
                drafting=[
                    {
                        "kind": "line",
                        "id": "D1",
                        "story": "L1",
                        "start": [invalid_coord, 0.0],
                        "end": [100.0, 100.0],
                    }
                ]
            )
        )

    with pytest.raises(ValidationError, match="Input should be a finite number"):
        FloorPlan.model_validate(
            model(
                drafting=[
                    {
                        "kind": "polyline",
                        "id": "D2",
                        "story": "L1",
                        "points": [[0.0, 0.0], [0.0, invalid_coord]],
                    }
                ]
            )
        )

    with pytest.raises(ValidationError, match="Input should be a finite number"):
        FloorPlan.model_validate(
            model(
                drafting=[
                    {
                        "kind": "circle",
                        "id": "D3",
                        "story": "L1",
                        "center": [invalid_coord, 0.0],
                        "radius": 50.0,
                    }
                ]
            )
        )

    with pytest.raises(ValidationError, match="Input should be a finite number"):
        FloorPlan.model_validate(
            model(
                drafting=[
                    {
                        "kind": "arc",
                        "id": "D4",
                        "story": "L1",
                        "center": [0.0, 0.0],
                        "radius": 50.0,
                        "startAngle": invalid_coord,
                        "endAngle": 90.0,
                    }
                ]
            )
        )


def test_closed_polyline_with_2_points_refused() -> None:
    with pytest.raises(
        ValidationError, match="draft D1: a closed polyline needs at least 3 points"
    ):
        FloorPlan.model_validate(
            model(
                drafting=[
                    {
                        "kind": "polyline",
                        "id": "D1",
                        "story": "L1",
                        "points": [[0, 0], [100, 100]],
                        "closed": True,
                    }
                ]
            )
        )

    # 2 points is valid when open
    valid_open = FloorPlan.model_validate(
        model(
            drafting=[
                {
                    "kind": "polyline",
                    "id": "D1",
                    "story": "L1",
                    "points": [[0, 0], [100, 100]],
                    "closed": False,
                }
            ]
        )
    )
    assert len(valid_open.drafting) == 1


def test_polyline_with_less_than_2_points_refused() -> None:
    with pytest.raises(ValidationError):
        FloorPlan.model_validate(
            model(
                drafting=[
                    {
                        "kind": "polyline",
                        "id": "D1",
                        "story": "L1",
                        "points": [[0, 0]],
                    }
                ]
            )
        )


def test_radius_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        FloorPlan.model_validate(
            model(
                drafting=[
                    {
                        "kind": "circle",
                        "id": "D1",
                        "story": "L1",
                        "center": [0, 0],
                        "radius": 0,
                    }
                ]
            )
        )
    with pytest.raises(ValidationError):
        FloorPlan.model_validate(
            model(
                drafting=[
                    {
                        "kind": "arc",
                        "id": "D1",
                        "story": "L1",
                        "center": [0, 0],
                        "radius": -10,
                        "startAngle": 0,
                        "endAngle": 90,
                    }
                ]
            )
        )


def test_old_plan_without_drafting_still_validates() -> None:
    raw = model()
    raw.pop("drafting", None)
    assert "drafting" not in raw
    plan = FloorPlan.model_validate(raw)
    assert plan.drafting == []

    # Dumping with exclude_defaults does not add the drafting key
    dumped_exclude = plan.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    assert "drafting" not in dumped_exclude
