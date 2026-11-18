"""Drafting actions (05 Floor Plan): 2D lines, polylines, arcs and circles stored in per-storey
DXF files ("05 Floor Plan/drafting/<storyId>.dxf") for layout, underlay tracing and converting
into members."""

from __future__ import annotations

from typing import Any

from pydantic import Field, TypeAdapter, ValidationError

from saengine.actions.catalogue import _plan as P
from saengine.actions.catalogue._util import Params
from saengine.actions.errors import ActionError, refuse
from saengine.actions.paths import FLOOR_PLAN
from saengine.actions.registry import action
from saengine.actions.result import ActionResult, Problem
from saengine.actions.view import ProjectView
from saengine.library.drafting_dxf import (
    drafting_path,
    entity_summary,
    new_document,
    shape_to_entities,
)
from saengine.library.drafting_dxf import (
    read as read_dxf,
)
from saengine.library.drafting_dxf import (
    write as write_dxf,
)
from saengine.library.floorplan import DraftShape

_DRAFT_ADAPTER = TypeAdapter(DraftShape)


def migrate_floor_plan_drafting(view: ProjectView) -> int:
    """Migrates any drafting from floor-plan.json into per-storey DXF files."""
    if not view.has(FLOOR_PLAN):
        return 0
    plan = view.part(FLOOR_PLAN)
    drafts = plan.get("drafting")
    if not drafts or not isinstance(drafts, list):
        if "drafting" in plan:
            del plan["drafting"]
            view.put(FLOOR_PLAN, plan)
        return 0

    docs: dict[str, Any] = {}
    for draft in drafts:
        if not isinstance(draft, dict):
            continue
        story = draft.get("story")
        if not story:
            continue
        path = drafting_path(story)
        if path not in docs:
            if view.has(path):
                docs[path] = read_dxf(view.read(path))
            else:
                docs[path] = new_document()
        msp = docs[path].modelspace()
        shape_to_entities(msp, draft)

    for path, doc in docs.items():
        view.put(path, write_dxf(doc))

    del plan["drafting"]
    view.put(FLOOR_PLAN, plan)
    return len(drafts)


class DraftingMigrateParams(Params):
    pass


@action(
    "drafting.migrate",
    summary="Migrate floor plan drafting from floor-plan.json to per-storey DXF files.",
    params=DraftingMigrateParams,
    parts=("floorPlan",),
    kind="edit",
    example={},
)
def drafting_migrate(view: ProjectView, p: DraftingMigrateParams) -> ActionResult:
    count = migrate_floor_plan_drafting(view)
    if count:
        return ActionResult(message=f"Migrated {count} draft shapes to DXF.")
    return ActionResult(message="No drafting to migrate.")


class DraftingAddParams(Params):
    shapes: list[dict[str, Any]] = Field(
        min_length=1,
        description="Draft shapes to add ({kind, story, ...}, id optional).",
    )


@action(
    "drafting.add",
    summary="Add 2D drafting geometry (lines, polylines, arcs, circles) to the storey's DXF.",
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
    migrate_floor_plan_drafting(view)
    plan = view.read(FLOOR_PLAN, {})
    docs: dict[str, Any] = {}
    created: list[str] = []

    for i, shape in enumerate(p.shapes):
        story = shape.get("story")
        if not story:
            refuse("A story is required for each draft shape.", f"shapes.{i}.story", story)
        P.check_story(plan, story, f"shapes.{i}.story")

        shape_data = {**shape, "id": shape.get("id") or "D1"}
        try:
            _DRAFT_ADAPTER.validate_python(shape_data)
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

        path = drafting_path(story)
        if path not in docs:
            if view.has(path):
                docs[path] = read_dxf(view.read(path))
            else:
                docs[path] = new_document()

        msp = docs[path].modelspace()
        entities = shape_to_entities(msp, shape)
        for e in entities:
            created.append(e.dxf.handle)

    for path, doc in docs.items():
        view.put(path, write_dxf(doc))

    return ActionResult(message=f"Added {', '.join(created)}.", created=created)


class DraftingDeleteParams(Params):
    ids: list[str] = Field(min_length=1, description="Draft shape handles to delete.")
    story: str = Field(description="Story whose draft shapes to delete.")


@action(
    "drafting.delete",
    summary="Delete 2D drafting shapes by their handles on a storey.",
    params=DraftingDeleteParams,
    parts=("floorPlan",),
    kind="edit",
    example={"ids": ["2F"], "story": "L1"},
)
def drafting_delete(view: ProjectView, p: DraftingDeleteParams) -> ActionResult:
    migrate_floor_plan_drafting(view)
    plan = view.read(FLOOR_PLAN, {})
    P.check_story(plan, p.story, "story")

    path = drafting_path(p.story)
    if not view.has(path):
        known = "none"
        names = ", ".join(f"'{i}'" for i in p.ids)
        refuse(
            f"There is no draft shape {names} (the draft shapes: {known})."
            if len(p.ids) > 1
            else f"There is no draft shape '{p.ids[0]}' (the draft shapes: {known}).",
            "ids",
            p.ids[0] if len(p.ids) == 1 else p.ids,
        )

    doc = read_dxf(view.read(path))
    msp = doc.modelspace()
    existing = {e.dxf.handle: e for e in msp}

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

    for i in p.ids:
        msp.delete_entity(existing[i])

    view.put(path, write_dxf(doc))
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
    migrate_floor_plan_drafting(view)
    plan = view.read(FLOOR_PLAN, {})
    if p.story is not None:
        P.check_story(plan, p.story, "story")
        stories = [p.story]
    else:
        stories = [s["id"] for s in plan.get("stories", []) if isinstance(s, dict) and "id" in s]

    drafts: list[dict[str, Any]] = []
    for story in stories:
        path = drafting_path(story)
        if not view.has(path):
            continue
        doc = read_dxf(view.read(path))
        msp = doc.modelspace()
        for e in msp:
            drafts.append(entity_summary(e, story=story))

    count = len(drafts)
    return ActionResult(
        message=f"{count} draft shape{'s' if count != 1 else ''}.",
        data=drafts,
    )
