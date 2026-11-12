"""Member actions (05 Floor Plan): columns, beams, slabs and walls placed on the grid, changed,
deleted and copied to other storeys, by the floor plan editor's rules (``floorPlanEdits.ts``): a
column or wall rises to its storey from the one below; a member is not placed twice at the same
place on a storey; an edit on a typical floor is made on its whole family (``similarTo``)."""

from __future__ import annotations

import copy
import itertools
from typing import Any, Literal

from pydantic import Field

from saengine.actions.catalogue import _plan as P
from saengine.actions.catalogue._util import Params
from saengine.actions.errors import refuse
from saengine.actions.paths import FLOOR_PLAN, LOADS
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView

STOREYS_HELP = (
    'The storeys (ids), or "all" (every storey above the lowest); a typical floor brings its '
    "whole family."
)


def _plan(view: ProjectView) -> dict[str, Any]:
    plan = view.part(FLOOR_PLAN)
    for group in P.GROUPS:
        plan.setdefault(group, [])
    return plan


def _placed(plan: dict[str, Any], group: str, story: str) -> set[str]:
    return {
        P.place_key(group, m) for m in P.members(plan, group) if P.on_story(plan, group, m, story)
    }


def _add(
    plan: dict[str, Any], group: str, story: str, member: dict[str, Any], taken: set[str]
) -> str:
    member_id = P.next_id(plan, group, taken)
    taken.add(member_id)
    if group in P.RISING:
        member = {"base": P.below(plan, story), "top": story, **member}
    else:
        member = {"story": story, **member}
    plan[group].append({"id": member_id, **member})
    return member_id


def _result(group: str, created: list[str], skipped: list[str], stories: list[str]) -> ActionResult:
    message = f"{len(created)} {group} placed on {', '.join(stories)}"
    warnings = []
    if skipped:
        message += f"; {len(skipped)} places had one already"
        warnings.append(
            f"{group.capitalize()} already there (not placed again): "
            + ", ".join(skipped[:12])
            + (" ..." if len(skipped) > 12 else "")
        )
    return ActionResult(message=message + ".", created=created, warnings=warnings)


# ── columns ──


class ColumnsParams(Params):
    type: str = Field(description="Column object type id (04 Objects).")
    points: Literal["all"] | list[P.PointRef] = Field(
        default="all", description='Grid points ("A-1" or {x, y, dx, dy}), or "all".'
    )
    storeys: P.Storeys = Field(default="all", description=STOREYS_HELP)
    rotation: float = Field(default=0, description="Rotation of the section [°].")


@action(
    "columns.place",
    summary="Place columns at grid points (a list, or all) on storeys; each rises from the "
    "storey below.",
    params=ColumnsParams,
    parts=("floorPlan",),
    kind="edit",
    example={"type": "C400x400", "points": "all", "storeys": "all"},
)
def columns_place(view: ProjectView, p: ColumnsParams) -> ActionResult:
    plan = _plan(view)
    P.check_type(view, p.type, "columns")
    stories = P.resolve_storeys(plan, p.storeys)
    points = P.all_points(plan) if p.points == "all" else [P.point(plan, r) for r in p.points]
    created, skipped, taken = [], [], set()
    for story in stories:
        if P.below(plan, story) is None:
            refuse(
                f"Columns rise to a storey from the one below; {story} is the lowest.",
                "storeys",
                story,
            )
        there = _placed(plan, "columns", story)
        for pt in points:
            if P.key(pt) in there:
                if p.points != "all":
                    refuse(
                        f"There is a column at {P.label(pt)} on {story} already.",
                        "points",
                        P.label(pt),
                    )
                skipped.append(f"{P.label(pt)} on {story}")
                continue
            created.append(
                _add(
                    plan,
                    "columns",
                    story,
                    {"type": p.type, "at": pt, "rotation": p.rotation},
                    taken,
                )
            )
            there.add(P.key(pt))
    view.put(FLOOR_PLAN, plan)
    return _result("columns", created, skipped, stories)


# ── beams and walls ──


class LinearParams(Params):
    type: str = Field(description="Object type id (04 Objects).")
    between: Literal["all"] | list[list[P.PointRef]] = Field(
        default="all",
        description='Pairs of grid points [["A-1", "B-1"], ...], or "all": between every two '
        "neighbouring intersections along every grid line.",
    )
    lines: list[str] | None = Field(
        default=None, description='With "all": only along these grid lines (labels).'
    )
    storeys: P.Storeys = Field(default="all", description=STOREYS_HELP)


def _segments(plan: dict[str, Any], p: LinearParams) -> list[tuple[dict, dict]]:
    if p.between != "all":
        out = []
        for pair in p.between:
            if len(pair) != 2:
                refuse("Each item of between is two grid points.", "between", pair)
            a, b = P.point(plan, pair[0], "between"), P.point(plan, pair[1], "between")
            if P.where(plan, a) == P.where(plan, b):
                refuse(f"{P.label(a)} and {P.label(b)} are the same point.", "between", pair)
            out.append((a, b))
        return out
    xs, ys = P.labels(plan, "x"), P.labels(plan, "y")
    known = set(xs) | set(ys)
    for line in p.lines or []:
        if line not in known:
            refuse(f"There is no grid line '{line}'.", "lines", line)
    wanted = set(p.lines) if p.lines else known
    out = []
    for y in ys:  # along the Y lines (in X)
        if y in wanted:
            for a, b in itertools.pairwise(xs):
                out.append(({"x": a, "y": y, "dx": 0, "dy": 0}, {"x": b, "y": y, "dx": 0, "dy": 0}))
    for x in xs:
        if x in wanted:
            for a, b in itertools.pairwise(ys):
                out.append(({"x": x, "y": a, "dx": 0, "dy": 0}, {"x": x, "y": b, "dx": 0, "dy": 0}))
    return out


def _place_linear(view: ProjectView, p: LinearParams, group: str) -> ActionResult:
    plan = _plan(view)
    P.check_type(view, p.type, group)
    stories = P.resolve_storeys(plan, p.storeys)
    segments = _segments(plan, p)
    created, skipped, taken = [], [], set()
    noun = group[:-1]
    for story in stories:
        if group in P.RISING and P.below(plan, story) is None:
            refuse(
                f"Walls rise to a storey from the one below; {story} is the lowest.",
                "storeys",
                story,
            )
        there = _placed(plan, group, story)
        for a, b in segments:
            k = P.place_key(group, {"start": a, "end": b})
            what = f"{P.label(a)} to {P.label(b)} on {story}"
            if k in there:
                if p.between != "all":
                    refuse(f"There is a {noun} from {what} already.", "between", what)
                skipped.append(what)
                continue
            created.append(_add(plan, group, story, {"type": p.type, "start": a, "end": b}, taken))
            there.add(k)
    view.put(FLOOR_PLAN, plan)
    return _result(group, created, skipped, stories)


@action(
    "beams.place",
    summary="Place beams between grid points (pairs, or all along the grid lines) on storeys.",
    params=LinearParams,
    parts=("floorPlan",),
    kind="edit",
    example={"type": "B250x450", "between": "all", "storeys": "all"},
)
def beams_place(view: ProjectView, p: LinearParams) -> ActionResult:
    return _place_linear(view, p, "beams")


@action(
    "walls.place",
    summary="Place walls between grid points on storeys; each rises from the storey below.",
    params=LinearParams,
    parts=("floorPlan",),
    kind="edit",
    example={"type": "W200", "between": [["A-1", "B-1"]], "storeys": ["L1"]},
)
def walls_place(view: ProjectView, p: LinearParams) -> ActionResult:
    return _place_linear(view, p, "walls")


# ── slabs ──


class SlabsParams(Params):
    type: str = Field(description="Slab object type id (04 Objects).")
    panels: Literal["all"] | list[P.PointRef | list[P.PointRef]] = Field(
        default="all",
        description='The bays by their lower-left grid point ("A-1": the bay A-B, 1-2), or '
        'corner lists (at least 3 points in order), or "all".',
    )
    storeys: P.Storeys = Field(default="all", description=STOREYS_HELP)
    areaLoad: str | None = Field(
        default=None,
        description="Area load id of 02 Project Settings; none: the floor's or roof's.",
    )


def _bay(plan: dict[str, Any], corner: dict[str, Any]) -> list[dict[str, Any]]:
    xs, ys = P.labels(plan, "x"), P.labels(plan, "y")
    i, j = xs.index(corner["x"]), ys.index(corner["y"])
    if i + 1 >= len(xs) or j + 1 >= len(ys):
        refuse(
            f"{P.label(corner)} is on the last grid line: name a bay by its lower-left corner.",
            "panels",
            P.label(corner),
        )
    x0, x1, y0, y1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
    return [{"x": x, "y": y, "dx": 0, "dy": 0} for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]


@action(
    "slabs.place",
    summary="Place slabs in grid bays (by their lower-left point, corner lists, or all) on storeys.",
    params=SlabsParams,
    parts=("floorPlan",),
    kind="edit",
    example={"type": "S125", "panels": "all", "storeys": "all"},
)
def slabs_place(view: ProjectView, p: SlabsParams) -> ActionResult:
    plan = _plan(view)
    P.check_type(view, p.type, "slabs")
    if p.areaLoad is not None:
        from saengine.actions.paths import SETTINGS

        ids = [a.get("id") for a in (view.read(SETTINGS, {}).get("areaLoads") or [])]
        if p.areaLoad not in ids:
            refuse(
                f"There is no area load '{p.areaLoad}' (the area loads: {', '.join(ids)}).",
                "areaLoad",
                p.areaLoad,
            )
    stories = P.resolve_storeys(plan, p.storeys)
    if p.panels == "all":
        xs, ys = P.labels(plan, "x"), P.labels(plan, "y")
        boundaries = [_bay(plan, {"x": x, "y": y}) for x in xs[:-1] for y in ys[:-1]]
    else:
        boundaries = []
        for panel in p.panels:
            if isinstance(panel, list):
                if len(panel) < 3:
                    refuse("A slab's corner list has at least 3 points.", "panels", panel)
                boundaries.append([P.point(plan, r, "panels") for r in panel])
            else:
                boundaries.append(_bay(plan, P.point(plan, panel, "panels")))
    created, skipped, taken = [], [], set()
    for story in stories:
        there = _placed(plan, "slabs", story)
        for boundary in boundaries:
            k = P.place_key("slabs", {"boundary": boundary})
            what = f"{'/'.join(P.label(b) for b in boundary)} on {story}"
            if k in there:
                if p.panels != "all":
                    refuse(f"There is a slab in {what} already.", "panels", what)
                skipped.append(what)
                continue
            member: dict[str, Any] = {"type": p.type, "boundary": boundary}
            if p.areaLoad:
                member["areaLoad"] = p.areaLoad
            created.append(_add(plan, "slabs", story, member, taken))
            there.add(k)
    view.put(FLOOR_PLAN, plan)
    return _result("slabs", created, skipped, stories)


# ── change, delete, copy ──


class MemberSetParams(Params):
    ids: list[str] = Field(min_length=1, description="Member ids.")
    type: str | None = Field(default=None, description="Another object type of its kind.")
    rotation: float | None = Field(default=None, description="Columns, footings [°].")
    dx: float | None = Field(default=None, description="Columns: offset from the grid point [mm].")
    dy: float | None = Field(default=None, description="Columns: offset [mm].")
    base: str | None = Field(default=None, description="Columns, walls: the storey it starts at.")
    top: str | None = Field(default=None, description="Columns, walls: the storey it ends at.")
    story: str | None = Field(default=None, description="Beams, slabs: its storey.")
    areaLoad: str | None = Field(default=None, description="Slabs: area load id.")
    thisStoreyOnly: bool = Field(
        default=False,
        description="On a typical floor: change only these members, not their twins on the "
        "family's other storeys (type, rotation, offsets and area load follow the family).",
    )


@action(
    "member.set",
    summary="Change members: object type, rotation, offsets, storeys (base/top or story), a "
    "slab's area load; on a typical floor the family's twins follow.",
    params=MemberSetParams,
    parts=("floorPlan",),
    kind="edit",
    example={"ids": ["C1"], "type": "C450x450", "rotation": 90},
)
def member_set(view: ProjectView, p: MemberSetParams) -> ActionResult:
    plan = _plan(view)
    changes = p.model_dump(exclude={"ids", "thisStoreyOnly"}, exclude_none=True)
    if not changes:
        refuse(
            "Give what to change (type, rotation, dx, dy, base, top, story, areaLoad).", "", None
        )
    for s in ("base", "top", "story"):
        if s in changes:
            P.check_story(plan, changes[s], s)
    shared = {k: v for k, v in changes.items() if k not in ("base", "top", "story")}
    followed: list[str] = []
    for member_id in p.ids:
        group, m = P.find_member(plan, member_id)
        allowed = {
            "columns": {"type", "rotation", "dx", "dy", "base", "top"},
            "walls": {"type", "base", "top"},
            "beams": {"type", "story"},
            "slabs": {"type", "story", "areaLoad"},
            "footings": {"type", "rotation", "story", "dx", "dy"},
        }[group]
        wrong = sorted(set(changes) - allowed)
        if wrong:
            refuse(
                f"{member_id} is a {group[:-1]}: it has no {', '.join(wrong)}.",
                wrong[0],
                changes[wrong[0]],
            )
        if "type" in changes:
            P.check_type(view, changes["type"], group)
        others = [] if p.thisStoreyOnly or not shared else P.twins(plan, group, m)
        for target, values in [(m, changes)] + [(t, shared) for t in others]:
            for field, value in values.items():
                if field in ("dx", "dy"):
                    target["at"][field] = value
                else:
                    target[field] = value
        followed += [t["id"] for t in others if t["id"] not in p.ids]
    view.put(FLOOR_PLAN, plan)
    said = ", ".join(f"{k} {v}" for k, v in changes.items())
    also = f" (and their twins on the typical floors: {', '.join(followed)})" if followed else ""
    return ActionResult(message=f"{', '.join(p.ids)}: {said}{also}.")


class MemberDeleteParams(Params):
    ids: list[str] = Field(min_length=1, description="Member ids.")
    thisStoreyOnly: bool = Field(
        default=False,
        description="On a typical floor: delete only these, not their twins on the family's "
        "other storeys.",
    )


@action(
    "member.delete",
    summary="Delete members (and the member loads on them); on a typical floor their twins on "
    "the family's other storeys too.",
    params=MemberDeleteParams,
    parts=("floorPlan", "loads"),
    kind="edit",
    example={"ids": ["B3"]},
)
def member_delete(view: ProjectView, p: MemberDeleteParams) -> ActionResult:
    plan = _plan(view)
    ids = set(p.ids)
    for member_id in p.ids:
        group, m = P.find_member(plan, member_id)
        if not p.thisStoreyOnly:
            ids |= {t["id"] for t in P.twins(plan, group, m)}
    for group in P.GROUPS:
        plan[group] = [m for m in P.members(plan, group) if m.get("id") not in ids]
    view.put(FLOOR_PLAN, plan)
    warnings = []
    loads = view.read(LOADS, None)
    if isinstance(loads, dict) and loads.get("loads"):
        kept = [x for x in loads["loads"] if x.get("member") not in ids]
        if len(kept) != len(loads["loads"]):
            view.put(LOADS, {**loads, "loads": kept})
            warnings.append(f"{len(loads['loads']) - len(kept)} member loads on them deleted too.")
    extra = sorted(ids - set(p.ids))
    also = f" (and their twins on the typical floors: {', '.join(extra)})" if extra else ""
    return ActionResult(message=f"Deleted {', '.join(p.ids)}{also}.", warnings=warnings)


class CopyParams(Params):
    source: str = Field(alias="from", description="The storey to copy from.")
    to: list[str] = Field(min_length=1, description="The storeys to copy to.")
    groups: list[Literal["columns", "beams", "walls", "slabs"]] = Field(
        default=["columns", "beams", "walls", "slabs"], description="Which members."
    )


@action(
    "members.copy_to_storeys",
    summary="Copy a storey's columns, beams, walls and slabs to other storeys (places that have "
    "one already are left as they are).",
    params=CopyParams,
    parts=("floorPlan",),
    kind="edit",
    example={"from": "L1", "to": ["L2", "L3"]},
)
def members_copy(view: ProjectView, p: CopyParams) -> ActionResult:
    plan = _plan(view)
    P.check_story(plan, p.source, "from")
    targets = P.resolve_storeys(plan, p.to, "to")
    created, skipped, taken = [], [], set()
    for group in p.groups:
        sources = [m for m in P.members(plan, group) if P.on_story(plan, group, m, p.source)]
        for story in targets:
            if story == p.source:
                continue
            if group in P.RISING and P.below(plan, story) is None:
                refuse(
                    f"{group.capitalize()} rise from the storey below; {story} is the lowest.",
                    "to",
                    story,
                )
            there = _placed(plan, group, story)
            for m in sources:
                k = P.place_key(group, m)
                if k in there:
                    skipped.append(f"{m['id']} on {story}")
                    continue
                twin = copy.deepcopy(
                    {k2: v for k2, v in m.items() if k2 not in ("id", "story", "base", "top")}
                )
                created.append(_add(plan, group, story, twin, taken))
                there.add(k)
    view.put(FLOOR_PLAN, plan)
    result = _result("members", created, skipped, targets)
    result.message = result.message.replace("placed", f"copied from {p.source}")
    return result
