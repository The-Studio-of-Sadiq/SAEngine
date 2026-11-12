"""Floor plan helpers of the actions: grid points by their labels, storeys and their families
(typical floors), the next free member id. The rules are the floor plan editor's
(``floorPlanEdits.ts``, ``floorPlanTypical.ts``): ids are the group's letter and the lowest free
number (C1, B1, W1, S1, F1); a column or wall rises to a storey from the one below; a storey with
``similarTo`` repeats its master's plan, so an edit on one storey of a family is made on all.
"""

from __future__ import annotations

import itertools
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from saengine.actions.errors import refuse

GROUPS = ("columns", "beams", "walls", "slabs", "footings")
#: The groups a storey's plan owns (footings belong to 9 Substructure).
PLAN_GROUPS = ("columns", "beams", "walls", "slabs")
ID_PREFIX = {"columns": "C", "beams": "B", "walls": "W", "slabs": "S", "footings": "F"}
#: Groups whose members rise from the storey below to their own storey.
RISING = ("columns", "walls")
#: The object kinds a group's members may use.
KINDS = {
    "columns": ("column",),
    "beams": ("beam",),
    "walls": ("wall",),
    "slabs": ("slab",),
    "footings": ("footing", "pileCap"),
}


class GridPointIn(BaseModel):
    """A grid intersection by its line labels, optionally offset [mm]."""

    model_config = ConfigDict(extra="forbid")
    x: str = Field(description="X grid line label, e.g. A.")
    y: str = Field(description="Y grid line label, e.g. 1.")
    dx: float = 0
    dy: float = 0


#: A grid point: "A-1" (or "A/1"), or {"x": "A", "y": "1", "dx": 0, "dy": 0}.
PointRef = str | GridPointIn
Storeys = Literal["all"] | list[str]


def members(plan: dict[str, Any], group: str) -> list[dict[str, Any]]:
    return [m for m in plan.get(group) or [] if isinstance(m, dict)]


def next_id(plan: dict[str, Any], group: str, taken: set[str] | None = None) -> str:
    """The next free id of ``group``: its letter and the lowest unused number."""
    used = {m.get("id") for g in GROUPS for m in members(plan, g)} | (taken or set())
    for n in itertools.count(1):
        candidate = f"{ID_PREFIX[group]}{n}"
        if candidate not in used:
            return candidate
    raise AssertionError  # pragma: no cover


def find_member(plan: dict[str, Any], member_id: str) -> tuple[str, dict[str, Any]]:
    for group in GROUPS:
        for m in members(plan, group):
            if m.get("id") == member_id:
                return group, m
    refuse(f"There is no member '{member_id}' in the floor plan.", "ids", member_id)
    raise AssertionError  # pragma: no cover


# ── storeys ──


def stories(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """The storeys, lowest first."""
    found = [s for s in plan.get("stories") or [] if isinstance(s, dict)]
    return sorted(found, key=lambda s: float(s.get("elevation", 0)))


def story_ids(plan: dict[str, Any]) -> list[str]:
    return [s["id"] for s in stories(plan)]


def check_story(plan: dict[str, Any], story_id: str, field: str = "storeys") -> None:
    if story_id not in story_ids(plan):
        known = ", ".join(story_ids(plan)) or "none yet (storeys.set)"
        refuse(f"There is no storey '{story_id}' (the storeys: {known}).", field, story_id)


def below(plan: dict[str, Any], story_id: str) -> str | None:
    ids = story_ids(plan)
    index = ids.index(story_id)
    return ids[index - 1] if index > 0 else None


def master_of(plan: dict[str, Any], story_id: str) -> str | None:
    ids = set(story_ids(plan))
    for s in stories(plan):
        if s["id"] == story_id:
            similar = s.get("similarTo")
            return similar if similar in ids and similar != story_id else None
    return None


def family(plan: dict[str, Any], story_id: str) -> list[str]:
    """The storey's family, lowest first: its master and the storeys similar to it."""
    master = master_of(plan, story_id) or story_id
    return [i for i in story_ids(plan) if i == master or master_of(plan, i) == master]


def resolve_storeys(plan: dict[str, Any], wanted: Storeys, field: str = "storeys") -> list[str]:
    """The storeys asked for ("all": every storey above the lowest), each with its typical
    family, lowest first; a column or wall on a storey rises from the one below."""
    ids = story_ids(plan)
    if len(ids) < 2:
        refuse("The floor plan needs at least two storeys first (storeys.set).", field, wanted)
    if wanted == "all":
        chosen = ids[1:]
    else:
        if not wanted:
            refuse('Give the storeys (or "all").', field, wanted)
        for s in wanted:
            check_story(plan, s, field)
        chosen = list(wanted)
    out = {f for s in chosen for f in family(plan, s)}
    return [i for i in ids if i in out]


# ── grids ──


def grid_lines(plan: dict[str, Any], axis: str) -> list[dict[str, Any]]:
    lines = [g for g in (plan.get("grids") or {}).get(axis) or [] if isinstance(g, dict)]
    return sorted(lines, key=lambda g: float(g.get("position", 0)))


def labels(plan: dict[str, Any], axis: str) -> list[str]:
    return [g["label"] for g in grid_lines(plan, axis)]


def point(plan: dict[str, Any], ref: PointRef, field: str = "points") -> dict[str, Any]:
    """A grid point of the floor plan from "A-1", "A/1" or {x, y, dx, dy}."""
    xs, ys = labels(plan, "x"), labels(plan, "y")
    if not xs or not ys:
        refuse("The floor plan needs grid lines on both axes first (grid.set).", field, ref)
    if isinstance(ref, GridPointIn):
        x, y, dx, dy = ref.x, ref.y, ref.dx, ref.dy
    elif isinstance(ref, dict):
        x, y = str(ref.get("x")), str(ref.get("y"))
        dx, dy = float(ref.get("dx") or 0), float(ref.get("dy") or 0)
    else:
        text = str(ref).strip()
        x = y = None
        for sep in ("/", "-", " "):
            for i, ch in enumerate(text):
                if ch == sep and text[:i] in xs and text[i + 1 :] in ys:
                    x, y = text[:i], text[i + 1 :]
                    break
            if x is not None:
                break
        if x is None:
            for i in range(1, len(text)):  # "A1"
                if text[:i] in xs and text[i:] in ys:
                    x, y = text[:i], text[i:]
                    break
        if x is None:
            refuse(
                f"'{text}' is not a grid point: write it as X-Y with the labels of the grid "
                f"(X lines {', '.join(xs)}; Y lines {', '.join(ys)}), e.g. {xs[0]}-{ys[0]}.",
                field,
                ref,
            )
        dx = dy = 0.0
    if x not in xs:
        refuse(f"There is no X grid line '{x}' (X lines {', '.join(xs)}).", field, ref)
    if y not in ys:
        refuse(f"There is no Y grid line '{y}' (Y lines {', '.join(ys)}).", field, ref)
    return {"x": x, "y": y, "dx": dx, "dy": dy}


def all_points(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"x": x, "y": y, "dx": 0, "dy": 0} for x in labels(plan, "x") for y in labels(plan, "y")
    ]


def where(plan: dict[str, Any], p: dict[str, Any]) -> tuple[float, float]:
    """The plan position [mm] of a grid point."""
    xs = {g["label"]: float(g["position"]) for g in grid_lines(plan, "x")}
    ys = {g["label"]: float(g["position"]) for g in grid_lines(plan, "y")}
    return xs[p["x"]] + float(p.get("dx") or 0), ys[p["y"]] + float(p.get("dy") or 0)


def key(p: Any) -> str:
    if not isinstance(p, dict):
        return "?"
    return f"{p.get('x')}/{p.get('y')}/{float(p.get('dx') or 0):g}/{float(p.get('dy') or 0):g}"


def label(p: dict[str, Any]) -> str:
    offset = f" (+{p.get('dx', 0):g}, +{p.get('dy', 0):g})" if p.get("dx") or p.get("dy") else ""
    return f"{p['x']}-{p['y']}{offset}"


def place_key(group: str, member: dict[str, Any]) -> str:
    """Where a member is, independent of its storey and id."""
    if group in ("columns", "footings"):
        return key(member.get("at"))
    if group == "slabs":
        return " ".join(sorted(key(p) for p in member.get("boundary") or []))
    return " ".join(sorted((key(member.get("start")), key(member.get("end")))))


def story_of(plan: dict[str, Any], group: str, member: dict[str, Any]) -> str | None:
    """The storey whose plan ``member`` is on (a column or wall rising one storey: its top)."""
    if group in RISING:
        top = member.get("top")
        return top if top in story_ids(plan) and on_story(plan, group, member, top) else None
    return member.get("story")


def twins(plan: dict[str, Any], group: str, member: dict[str, Any]) -> list[dict[str, Any]]:
    """The members at the same place on the other storeys of ``member``'s typical family (the
    floor plan editor makes every edit on the whole family)."""
    story = story_of(plan, group, member)
    if story is None or group not in PLAN_GROUPS:
        return []
    others = [s for s in family(plan, story) if s != story]
    where = place_key(group, member)
    return [
        m
        for m in members(plan, group)
        if m is not member
        and place_key(group, m) == where
        and any(on_story(plan, group, m, s) for s in others)
    ]


def on_story(plan: dict[str, Any], group: str, member: dict[str, Any], story_id: str) -> bool:
    """Whether ``member`` is on the plan of ``story_id`` alone (a column or wall rising one
    storey to it; a beam, slab or footing at it)."""
    if group in RISING:
        return member.get("top") == story_id and member.get("base") == below(plan, story_id)
    return member.get("story") == story_id


def uses_story(member: dict[str, Any], story_id: str) -> bool:
    return story_id in (member.get("story"), member.get("base"), member.get("top"))


def uses_label(member: dict[str, Any], axis: str, line: str) -> bool:
    points = [member.get(k) for k in ("at", "start", "end")] + list(member.get("boundary") or [])
    return any(isinstance(p, dict) and p.get(axis) == line for p in points)


# ── object types ──


def check_type(view: Any, type_id: str, group: str, field: str = "type") -> None:
    """``type_id`` is an object type of 04 Objects of a kind ``group``'s members may use."""
    from saengine.actions.paths import OBJECTS

    objects = view.read(OBJECTS, {"objects": []})
    kinds = {o.get("id"): o.get("kind") for o in objects.get("objects") or []}
    allowed = KINDS[group]
    if type_id not in kinds:
        usable = [i for i, k in kinds.items() if k in allowed]
        refuse(
            f"There is no object type '{type_id}' in 04 Objects"
            + (
                f" (the {group}' types: {', '.join(usable)})."
                if usable
                else f": add one first (type.{allowed[0]}.add)."
            ),
            field,
            type_id,
        )
    if kinds[type_id] not in allowed:
        refuse(
            f"Object type '{type_id}' is a {kinds[type_id]}, not a {allowed[0]}.", field, type_id
        )
