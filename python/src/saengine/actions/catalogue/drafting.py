"""Drafting actions (05 Floor Plan): 2D lines, polylines, arcs and circles for layout,
underlay tracing and converting into members."""

from __future__ import annotations

import copy
import itertools
from typing import Any

from pydantic import Field, TypeAdapter, ValidationError

from saengine.actions.catalogue import _plan as P
from saengine.actions.catalogue._util import Params
from saengine.actions.errors import ActionError, refuse
from saengine.actions.paths import FLOOR_PLAN
from saengine.actions.registry import action
from saengine.actions.result import ActionResult, Problem
from saengine.actions.view import ProjectView
from saengine.library.floorplan import DraftShape

_DRAFT_ADAPTER = TypeAdapter(DraftShape)


def _plan(view: ProjectView) -> dict[str, Any]:
    plan = view.part(FLOOR_PLAN)
    plan.setdefault("drafting", [])
    return plan


def _next_draft_id(plan: dict[str, Any], taken: set[str]) -> str:
    used = (
        {m.get("id") for g in P.GROUPS for m in P.members(plan, g)}
        | {d.get("id") for d in plan.get("drafting", []) if isinstance(d, dict)}
        | taken
    )
    for n in itertools.count(1):
        candidate = f"D{n}"
        if candidate not in used:
            return candidate
    raise AssertionError  # pragma: no cover


class DraftingAddParams(Params):
    shapes: list[dict[str, Any]] = Field(
        min_length=1,
        description="Draft shapes to add ({kind, story, ...}, id optional).",
    )


@action(
    "drafting.add",
    summary="Add 2D drafting geometry (lines, polylines, arcs, circles) to the floor plan.",
    params=DraftingAddParams,
    parts=("floorPlan",),
    kind="edit",
    example={
        "shapes": [
            {
                "kind": "line",
                "story": "L1",
                "start": [0, 0],
                "end": [5000, 0],
            }
        ]
    },
)
def drafting_add(view: ProjectView, p: DraftingAddParams) -> ActionResult:
    plan = _plan(view)
    taken: set[str] = set()
    new_drafts: list[dict[str, Any]] = []
    created: list[str] = []

    for i, shape in enumerate(p.shapes):
        story = shape.get("story")
        if not story:
            refuse("A story is required for each draft shape.", f"shapes.{i}.story", story)
        P.check_story(plan, story, f"shapes.{i}.story")

        raw_id = shape.get("id")
        if raw_id:
            shape_id = str(raw_id)
            existing_ids = (
                {m.get("id") for g in P.GROUPS for m in P.members(plan, g)}
                | {d.get("id") for d in plan.get("drafting", []) if isinstance(d, dict)}
                | taken
            )
            if shape_id in existing_ids:
                refuse(
                    f"Draft id '{shape_id}' clashes with an existing draft or member id.",
                    f"shapes.{i}.id",
                    shape_id,
                )
            taken.add(shape_id)
        else:
            shape_id = _next_draft_id(plan, taken)
            taken.add(shape_id)

        shape_data = {**shape, "id": shape_id}
        try:
            draft_obj = _DRAFT_ADAPTER.validate_python(shape_data)
        except ValidationError as error:
            problems = [
                Problem(
                    field=f"shapes.{i}." + ".".join(str(loc) for loc in e["loc"]),
                    value=e.get("input") if not isinstance(e.get("input"), dict | list) else None,
                    reason=e["msg"].removeprefix("Value error, "),
                )
                for e in error.errors()
            ]
            raise ActionError(
                f"Draft shape is not valid: {problems[0].reason}",
                problems,
            ) from error

        dumped = draft_obj.model_dump(mode="json", by_alias=True)
        new_drafts.append(dumped)
        created.append(shape_id)

    plan["drafting"].extend(new_drafts)
    view.put(FLOOR_PLAN, plan)
    return ActionResult(message=f"Added {', '.join(created)}.", created=created)


class DraftingDeleteParams(Params):
    ids: list[str] = Field(min_length=1, description="Draft shape ids to delete.")


@action(
    "drafting.delete",
    summary="Delete 2D drafting shapes by their ids.",
    params=DraftingDeleteParams,
    parts=("floorPlan",),
    kind="edit",
    example={"ids": ["D1"]},
)
def drafting_delete(view: ProjectView, p: DraftingDeleteParams) -> ActionResult:
    plan = _plan(view)
    existing = {d.get("id"): d for d in plan.get("drafting", []) if isinstance(d, dict)}
    unknown = [i for i in p.ids if i not in existing]
    if unknown:
        known = ", ".join(sorted(existing)) or "none"
        names = ", ".join(f"'{i}'" for i in unknown)
        refuse(
            f"There is no draft shape {names} (the draft shapes: {known})."
            if len(unknown) > 1
            else f"There is no draft shape '{unknown[0]}' (the draft shapes: {known}).",
            "ids",
            unknown[0] if len(unknown) == 1 else unknown,
        )
    to_delete = set(p.ids)
    plan["drafting"] = [d for d in plan.get("drafting", []) if d.get("id") not in to_delete]
    view.put(FLOOR_PLAN, plan)
    return ActionResult(message=f"Deleted {', '.join(p.ids)}.")


class DraftingListParams(Params):
    story: str | None = Field(default=None, description="Only the draft shapes on this story.")


@action(
    "drafting.list",
    summary="The floor plan's 2D draft shapes, all or of one story.",
    params=DraftingListParams,
    parts=("floorPlan",),
    kind="query",
    example={"story": "L1"},
)
def drafting_list(view: ProjectView, p: DraftingListParams) -> ActionResult:
    plan = view.read(FLOOR_PLAN, {})
    if p.story is not None:
        P.check_story(plan, p.story, "story")
    drafts = [d for d in plan.get("drafting", []) if isinstance(d, dict)]
    if p.story is not None:
        drafts = [d for d in drafts if d.get("story") == p.story]
    count = len(drafts)
    return ActionResult(
        message=f"{count} draft shape{'s' if count != 1 else ''}.",
        data=copy.deepcopy(drafts),
    )
