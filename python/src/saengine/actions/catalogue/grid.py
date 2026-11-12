"""Grid and storey actions (05 Floor Plan): the grid lines, the storeys and typical floors.
Spacings and storey heights are checked by the floor plan's guardrails (the same limits as the
New Project wizard and the floor plan editor); members follow their grid lines and storeys, so a
line or storey that members stand on is removed only when asked to remove them too."""

from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from saengine.actions.catalogue import _plan as P
from saengine.actions.catalogue._util import Params, fmt
from saengine.actions.errors import refuse
from saengine.actions.paths import FLOOR_PLAN, LOADS
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView


def _plan(view: ProjectView) -> dict[str, Any]:
    plan = view.part(FLOOR_PLAN)
    plan.setdefault("grids", {}).setdefault("x", [])
    plan["grids"].setdefault("y", [])
    plan.setdefault("stories", [])
    return plan


def _axis_label(axis: str, index: int) -> str:
    from saengine.library.generator import letters

    return letters(index) if axis == "x" else str(index + 1)


def _free_label(plan: dict[str, Any], axis: str) -> str:
    used = set(P.labels(plan, "x")) | set(P.labels(plan, "y"))
    index = 0
    while _axis_label(axis, index) in used:
        index += 1
    return _axis_label(axis, index)


def _remove_members(
    view: ProjectView, plan: dict[str, Any], doomed: list[tuple[str, dict[str, Any]]]
) -> list[str]:
    """Removes ``doomed`` (group, member) from ``plan`` and the member loads on them."""
    ids = {m["id"] for _, m in doomed}
    for group in P.GROUPS:
        plan[group] = [m for m in P.members(plan, group) if m.get("id") not in ids]
    loads = view.read(LOADS, None)
    if isinstance(loads, dict) and loads.get("loads"):
        kept = [x for x in loads["loads"] if x.get("member") not in ids]
        if len(kept) != len(loads["loads"]):
            view.put(LOADS, {**loads, "loads": kept})
    return sorted(ids)


# ── grid ──


class GridLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    position: float = Field(description="[mm] from the origin.")


class GridSetParams(Params):
    x: list[float] | list[GridLineIn] = Field(
        description="X lines (vertical in plan, labelled A, B, ...): the spacings between them "
        "[mm], or the lines as {label, position}."
    )
    y: list[float] | list[GridLineIn] = Field(
        description="Y lines (labelled 1, 2, ...): the spacings [mm], or {label, position}."
    )
    origin: list[float] = Field(
        default=[0, 0], min_length=2, max_length=2, description="Position of the first lines [mm]."
    )


def _lines(axis: str, value: list[Any], start: float) -> list[dict[str, Any]]:
    if value and isinstance(value[0], GridLineIn):
        return [{"label": g.label, "position": g.position} for g in value]
    positions = [start]
    for spacing in value:
        positions.append(positions[-1] + float(spacing))
    return [{"label": _axis_label(axis, i), "position": pos} for i, pos in enumerate(positions)]


@action(
    "grid.set",
    summary="Set the whole grid: the X and Y lines by their spacings (or labels and positions).",
    params=GridSetParams,
    parts=("floorPlan",),
    kind="edit",
    example={"x": [5000, 5000, 5000], "y": [4000, 4000]},
)
def grid_set(view: ProjectView, p: GridSetParams) -> ActionResult:
    plan = _plan(view)
    for name, value in (("x", p.x), ("y", p.y)):
        if not value:
            refuse(f"Give the {name.upper()} spacings or lines.", name, value)
        if not isinstance(value[0], GridLineIn) and any(s <= 0 for s in value):
            refuse(f"The {name.upper()} spacings must be positive [mm].", name, value)
    x = _lines("x", p.x, p.origin[0])
    y = _lines("y", p.y, p.origin[1])
    new_x, new_y = {g["label"] for g in x}, {g["label"] for g in y}
    stranded = [
        m["id"]
        for g in P.GROUPS
        for m in P.members(plan, g)
        if any(
            isinstance(pt, dict) and (pt.get("x") not in new_x or pt.get("y") not in new_y)
            for pt in [m.get(k) for k in ("at", "start", "end")] + list(m.get("boundary") or [])
        )
    ]
    if stranded:
        refuse(
            f"Members stand on grid lines the new grid does not have: {', '.join(stranded[:10])}"
            + (" ..." if len(stranded) > 10 else "")
            + ". Keep their labels, or delete the members first (member.delete).",
            "x",
            None,
        )
    plan["grids"] = {"x": x, "y": y}
    view.put(FLOOR_PLAN, plan)
    return ActionResult(
        message=f"Grid set: X {', '.join(g['label'] for g in x)}; Y "
        f"{', '.join(g['label'] for g in y)}.",
        created=[g["label"] for g in x + y],
    )


class LineAddParams(Params):
    axis: Literal["x", "y"]
    position: float = Field(description="[mm] from the origin.")
    label: str | None = Field(default=None, description="Default: the next free label.")


@action(
    "grid.line.add",
    summary="Add a grid line on the X or Y axis at a position.",
    params=LineAddParams,
    parts=("floorPlan",),
    kind="edit",
    example={"axis": "x", "position": 20000},
)
def grid_line_add(view: ProjectView, p: LineAddParams) -> ActionResult:
    plan = _plan(view)
    label = p.label or _free_label(plan, p.axis)
    if label in P.labels(plan, "x") + P.labels(plan, "y"):
        refuse(f"There is a grid line '{label}' already.", "label", label)
    lines = plan["grids"][p.axis]
    lines.append({"label": label, "position": p.position})
    lines.sort(key=lambda g: float(g["position"]))
    view.put(FLOOR_PLAN, plan)
    return ActionResult(
        message=f"Grid line {label} added at {fmt(p.position)} mm ({p.axis.upper()}).",
        created=[label],
    )


class LineMoveParams(Params):
    label: str
    position: float | None = Field(default=None, description="New position [mm].")
    by: float | None = Field(default=None, description="Or: move by this much [mm].")


def _find_line(plan: dict[str, Any], label: str) -> tuple[str, dict[str, Any]]:
    for axis in ("x", "y"):
        for g in plan["grids"][axis]:
            if g.get("label") == label:
                return axis, g
    known = ", ".join(P.labels(plan, "x") + P.labels(plan, "y")) or "none yet"
    refuse(f"There is no grid line '{label}' (the lines: {known}).", "label", label)
    raise AssertionError  # pragma: no cover


@action(
    "grid.line.move",
    summary="Move a grid line to a position (or by a distance); members on it move with it.",
    params=LineMoveParams,
    parts=("floorPlan",),
    kind="edit",
    example={"label": "B", "position": 5500},
)
def grid_line_move(view: ProjectView, p: LineMoveParams) -> ActionResult:
    if (p.position is None) == (p.by is None):
        refuse("Give either the new position or by how much to move it.", "position", None)
    plan = _plan(view)
    axis, line = _find_line(plan, p.label)
    old = float(line["position"])
    line["position"] = p.position if p.position is not None else old + (p.by or 0)
    plan["grids"][axis].sort(key=lambda g: float(g["position"]))
    view.put(FLOOR_PLAN, plan)
    return ActionResult(
        message=f"Grid line {p.label} moved from {fmt(old)} to {fmt(line['position'])} mm."
    )


class LineDeleteParams(Params):
    label: str
    deleteMembers: bool = Field(
        default=False,
        description="Also delete the members on the line (else refused when there are any).",
    )


@action(
    "grid.line.delete",
    summary="Delete a grid line (with the members on it only when deleteMembers is true).",
    params=LineDeleteParams,
    parts=("floorPlan", "loads"),
    kind="edit",
    example={"label": "D"},
)
def grid_line_delete(view: ProjectView, p: LineDeleteParams) -> ActionResult:
    plan = _plan(view)
    axis, _line = _find_line(plan, p.label)
    on = [(g, m) for g in P.GROUPS for m in P.members(plan, g) if P.uses_label(m, axis, p.label)]
    for tower in plan.get("towers") or []:
        if any(c.get(axis) == p.label for c in tower.get("boundary") or []):
            refuse(f"Tower {tower.get('id')} uses grid line {p.label}.", "label", p.label)
    removed: list[str] = []
    if on:
        if not p.deleteMembers:
            refuse(
                f"{len(on)} members stand on grid line {p.label} "
                f"({', '.join(m['id'] for _, m in on[:8])}{' ...' if len(on) > 8 else ''}): "
                "give deleteMembers: true to delete them with it.",
                "deleteMembers",
                False,
            )
        removed = _remove_members(view, plan, on)
    plan["grids"][axis] = [g for g in plan["grids"][axis] if g.get("label") != p.label]
    view.put(FLOOR_PLAN, plan)
    extra = f" and {len(removed)} members on it" if removed else ""
    return ActionResult(message=f"Grid line {p.label} deleted{extra}.")


# ── storeys ──


class StoreyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, description="Default: Level n.")
    height: float = Field(description="Height of the storey below this level [mm].")
    id: str | None = Field(default=None, description="Default: Ln.")


class StoreysSetParams(Params):
    storeys: list[StoreyIn] | None = Field(
        default=None, description="The storeys from the bottom, each with its height [mm]."
    )
    count: int | None = Field(default=None, ge=1, description="Or: this many storeys ...")
    height: float | None = Field(default=None, description="... of this height [mm] ...")
    groundHeight: float | None = Field(
        default=None, description="... the lowest of this height (default: height)."
    )
    baseElevation: float = Field(default=0, description="Level of the base [mm].")
    baseName: str = "Base"
    typical: bool = Field(
        default=False,
        description="Storeys above the second level are similar to the second (typical "
        "floors, as the New Project wizard makes them).",
    )


def _storey_list(p: StoreysSetParams) -> list[StoreyIn]:
    if p.storeys is not None:
        if p.count is not None:
            refuse("Give either the storeys or count and height.", "count", p.count)
        return p.storeys
    if p.count is None or p.height is None:
        refuse("Give the storeys, or count and height [mm].", "storeys", None)
    assert p.count is not None and p.height is not None
    return [
        StoreyIn(height=(p.groundHeight or p.height) if i == 0 else p.height)
        for i in range(p.count)
    ]


@action(
    "storeys.set",
    summary="Set all the storeys: a base level and the storeys above it with their heights.",
    params=StoreysSetParams,
    parts=("floorPlan",),
    kind="edit",
    example={"count": 3, "height": 3000, "typical": True},
)
def storeys_set(view: ProjectView, p: StoreysSetParams) -> ActionResult:
    from saengine.library.guardrails import building_problems

    wanted = _storey_list(p)
    for problem in building_problems(
        [5000.0], [5000.0], [s.height for s in wanted], storeys=len(wanted)
    ):
        if problem[1] == "error":
            refuse(problem[2], "storeys", [s.height for s in wanted])
    plan = _plan(view)
    stories = [{"id": "BASE", "name": p.baseName, "elevation": p.baseElevation}]
    level = p.baseElevation
    for i, s in enumerate(wanted):
        level += s.height
        stories.append(
            {"id": s.id or f"L{i + 1}", "name": s.name or f"Level {i + 1}", "elevation": level}
        )
    if p.typical and len(stories) > 3:
        for s in stories[3:]:
            s["similarTo"] = stories[2]["id"]
    ids = {s["id"] for s in stories}
    stranded = [
        m["id"]
        for g in P.GROUPS
        for m in P.members(plan, g)
        if any(k in m and m[k] not in ids for k in ("story", "base", "top"))
    ]
    if stranded:
        refuse(
            "Members are on storeys the new list does not have: "
            + ", ".join(stranded[:10])
            + (" ..." if len(stranded) > 10 else "")
            + ". Keep those storey ids, or delete the members first.",
            "storeys",
            None,
        )
    plan["stories"] = stories
    view.put(FLOOR_PLAN, plan)
    return ActionResult(
        message=f"{len(stories) - 1} storeys above {p.baseName} set; top at "
        f"{fmt(stories[-1]['elevation'])} mm.",
        created=[s["id"] for s in stories],
    )


class StoreyAddParams(Params):
    height: float = Field(description="Height of the new storey [mm].")
    name: str | None = None
    id: str | None = None
    above: str | None = Field(
        default=None,
        description="Insert above this storey (the ones higher up move up); default: on top.",
    )


@action(
    "storey.add",
    summary="Add a storey on top (or above a given storey, lifting the ones above it).",
    params=StoreyAddParams,
    parts=("floorPlan",),
    kind="edit",
    example={"height": 3000, "name": "Roof"},
)
def storey_add(view: ProjectView, p: StoreyAddParams) -> ActionResult:
    plan = _plan(view)
    stories = P.stories(plan)
    if not stories:
        refuse("There are no storeys yet: use storeys.set first.", "above", p.above)
    below_id = p.above or stories[-1]["id"]
    P.check_story(plan, below_id, "above")
    index = [s["id"] for s in stories].index(below_id)
    elevation = float(stories[index]["elevation"]) + p.height
    for s in stories[index + 1 :]:
        s["elevation"] = float(s["elevation"]) + p.height
    used = {s["id"] for s in stories}
    new_id = p.id or next(f"L{n}" for n in range(1, 10_000) if f"L{n}" not in used)
    if new_id in used:
        refuse(f"There is a storey '{new_id}' already.", "id", new_id)
    entry = {"id": new_id, "name": p.name or f"Level {len(stories)}", "elevation": elevation}
    stories.insert(index + 1, entry)
    plan["stories"] = stories
    view.put(FLOOR_PLAN, plan)
    return ActionResult(
        message=f"Storey {entry['name']} ({new_id}) added at {fmt(elevation)} mm.",
        created=[new_id],
    )


class StoreyDeleteParams(Params):
    id: str
    deleteMembers: bool = Field(
        default=False, description="Also delete the members on it (else refused when there are)."
    )


@action(
    "storey.delete",
    summary="Delete a storey; the storeys above come down by its height. Members on it are "
    "deleted only when deleteMembers is true.",
    params=StoreyDeleteParams,
    parts=("floorPlan", "loads"),
    kind="edit",
    example={"id": "L3"},
)
def storey_delete(view: ProjectView, p: StoreyDeleteParams) -> ActionResult:
    plan = _plan(view)
    P.check_story(plan, p.id, "id")
    stories = P.stories(plan)
    ids = [s["id"] for s in stories]
    index = ids.index(p.id)
    on = [(g, m) for g in P.GROUPS for m in P.members(plan, g) if P.uses_story(m, p.id)]
    similar = [s["id"] for s in stories if s.get("similarTo") == p.id]
    removed: list[str] = []
    if on:
        if not p.deleteMembers:
            refuse(
                f"{len(on)} members are on storey {p.id} "
                f"({', '.join(m['id'] for _, m in on[:8])}{' ...' if len(on) > 8 else ''}): "
                "give deleteMembers: true to delete them with it.",
                "deleteMembers",
                False,
            )
        removed = _remove_members(view, plan, on)
    drop = float(stories[index]["elevation"]) - (
        float(stories[index - 1]["elevation"]) if index > 0 else float(stories[index]["elevation"])
    )
    for s in stories[index + 1 :]:
        s["elevation"] = float(s["elevation"]) - drop
    stories.pop(index)
    if similar:  # the first storey similar to it becomes their master
        new_master = similar[0]
        for s in stories:
            if s["id"] == new_master:
                s.pop("similarTo", None)
            elif s.get("similarTo") == p.id:
                s["similarTo"] = new_master
    plan["stories"] = stories
    if plan.get("podiumTop") == p.id:
        plan.pop("podiumTop")
    view.put(FLOOR_PLAN, plan)
    extra = f" with {len(removed)} members" if removed else ""
    return ActionResult(message=f"Storey {p.id} deleted{extra}.")


class StoreyHeightParams(Params):
    id: str = Field(description="The storey whose height (from the storey below) changes.")
    height: float = Field(description="New height [mm].")


@action(
    "storey.height",
    summary="Change a storey's height (the distance from the storey below); the ones above move.",
    params=StoreyHeightParams,
    parts=("floorPlan",),
    kind="edit",
    example={"id": "L1", "height": 3600},
)
def storey_height(view: ProjectView, p: StoreyHeightParams) -> ActionResult:
    plan = _plan(view)
    P.check_story(plan, p.id, "id")
    stories = P.stories(plan)
    index = [s["id"] for s in stories].index(p.id)
    if index == 0:
        refuse(f"{p.id} is the lowest level: it has no storey below to measure from.", "id", p.id)
    if p.height <= 0:
        refuse("A storey height is positive [mm].", "height", p.height)
    change = float(stories[index - 1]["elevation"]) + p.height - float(stories[index]["elevation"])
    for s in stories[index:]:
        s["elevation"] = float(s["elevation"]) + change
    plan["stories"] = stories
    view.put(FLOOR_PLAN, plan)
    return ActionResult(message=f"Storey {p.id} is {fmt(p.height)} mm high now.")


class TypicalParams(Params):
    master: str = Field(description="The storey whose plan the others repeat.")
    storeys: list[str] = Field(min_length=1, description="The storeys made similar to it.")
    copy_: bool = Field(
        default=True,
        alias="copy",
        description="Replace their columns, beams, walls and slabs with copies of the master's.",
    )


@action(
    "storey.typical",
    summary="Make storeys typical floors of a master storey (similarTo): their plan becomes a "
    "copy of the master's, and later edits on one are made on all.",
    params=TypicalParams,
    parts=("floorPlan", "loads"),
    kind="edit",
    example={"master": "L2", "storeys": ["L3"]},
)
def storey_typical(view: ProjectView, p: TypicalParams) -> ActionResult:
    plan = _plan(view)
    P.check_story(plan, p.master, "master")
    if P.master_of(plan, p.master):
        refuse(
            f"{p.master} is itself similar to {P.master_of(plan, p.master)}: choose that one.",
            "master",
            p.master,
        )
    for s in p.storeys:
        P.check_story(plan, s)
        if s == p.master:
            refuse(f"Storey {s} cannot be similar to itself.", "storeys", s)
        if P.below(plan, s) is None:
            refuse(f"{s} is the lowest level: it has no plan of its own.", "storeys", s)
    for s in plan["stories"]:
        if s["id"] in p.storeys:
            s["similarTo"] = p.master
    created: list[str] = []
    if p.copy_:
        doomed = [
            (g, m)
            for g in P.PLAN_GROUPS
            for m in P.members(plan, g)
            if any(P.on_story(plan, g, m, s) for s in p.storeys)
        ]
        _remove_members(view, plan, doomed)
        taken: set[str] = set()
        for group in P.PLAN_GROUPS:
            for m in [m for m in P.members(plan, group) if P.on_story(plan, group, m, p.master)]:
                for s in p.storeys:
                    twin = copy.deepcopy(m)
                    twin["id"] = P.next_id(plan, group, taken)
                    taken.add(twin["id"])
                    if group in P.RISING:
                        twin["top"], twin["base"] = s, P.below(plan, s)
                    else:
                        twin["story"] = s
                    plan.setdefault(group, []).append(twin)
                    created.append(twin["id"])
    view.put(FLOOR_PLAN, plan)
    return ActionResult(
        message=f"{', '.join(p.storeys)} similar to {p.master}"
        + (f"; {len(created)} members copied from it" if created else "")
        + ".",
        created=created,
    )
