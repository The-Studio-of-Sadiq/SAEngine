"""Load actions: area loads (02 Project Settings, assigned to slabs on the floor plan) and member
loads (``05 Floor Plan/loads.json``: line, point and wall loads on beams and columns,
:mod:`saengine.library.line_loads`). Wall types and their weights come from the code pack's dead
loads; values are checked by the loads model and the member load guardrails."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from saengine.actions.catalogue import _plan as P
from saengine.actions.catalogue._util import Params, fmt
from saengine.actions.errors import refuse
from saengine.actions.paths import FLOOR_PLAN, LOADS, SETTINGS
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView

Case = Literal["D", "SD", "L", "Lr"]


# ── area loads ──


class AreaParams(Params):
    id: str | None = Field(
        default=None,
        description="The area load to set (e.g. FL floors, RF roof); a new id makes a new one. "
        "Default: a new area load AL<n> when storeys or slabs are given.",
    )
    storeys: P.Storeys | None = Field(
        default=None, description="Assign it to every slab of these storeys."
    )
    slabs: list[str] | None = Field(default=None, description="Or: to these slabs (ids).")
    name: str | None = None
    use: str | None = Field(default=None, description="Area use (one of the pack's).")
    SD: float | None = Field(default=None, description="Superimposed dead load (finish) [kN/m²].")
    L: float | None = Field(default=None, description="Live load [kN/m²].")
    Lr: float | None = Field(
        default=None, description="Roof live load [kN/m²] (an area load of roof use)."
    )
    partitions: float | None = Field(default=None, description="Partition allowance [kN/m²].")


@action(
    "load.area.set",
    summary="Set an area load (SD, L or Lr, partitions) and assign it to the slabs of storeys "
    "or to slabs; without a target it changes the area load itself (e.g. FL, RF).",
    params=AreaParams,
    parts=("settings", "floorPlan"),
    kind="edit",
    example={"id": "FL", "SD": 1.5, "L": 2.0},
)
def load_area_set(view: ProjectView, p: AreaParams) -> ActionResult:
    from saengine.codes import context as code_context

    if p.L is not None and p.Lr is not None:
        refuse(
            "Give L (a floor) or Lr (a roof), not both: an area load has one live load.", "Lr", p.Lr
        )
    settings = view.part(SETTINGS)
    areas = settings.setdefault("areaLoads", [])
    target = p.storeys is not None or p.slabs is not None
    area_id = p.id
    if area_id is None:
        if not target:
            refuse("Give the area load's id, or the storeys or slabs to load.", "id", None)
        n = 1
        while any(a.get("id") == f"AL{n}" for a in areas):
            n += 1
        area_id = f"AL{n}"
    area = next((a for a in areas if a.get("id") == area_id), None)
    created = []
    if area is None:
        pack = code_context.current()
        uses = pack.table("areaLoads").uses if pack.has("areaLoads") else {}
        use = p.use or ("roof" if p.Lr is not None else "residential")
        live = p.Lr if p.Lr is not None else p.L
        if live is None:
            if use not in uses:
                refuse(f"Give the live load: the code pack has no area use '{use}'.", "L", None)
            live = float(uses[use].live)
        area = {"id": area_id, "name": p.name or area_id, "use": use, "live": live}
        areas.append(area)
        created.append(area_id)
    if p.name:
        area["name"] = p.name
    if p.use:
        area["use"] = p.use
    if p.L is not None:
        area["live"] = p.L
    if p.Lr is not None:
        area["live"] = p.Lr
        area.setdefault("use", "roof")
    if p.SD is not None:
        area["finish"] = p.SD
    if p.partitions is not None:
        area["partitions"] = p.partitions
    view.put(SETTINGS, settings)
    assigned: list[str] = []
    if target:
        plan = view.part(FLOOR_PLAN)
        slabs = P.members(plan, "slabs")
        if p.slabs is not None:
            known = {s["id"] for s in slabs}
            for slab_id in p.slabs:
                if slab_id not in known:
                    refuse(f"There is no slab '{slab_id}'.", "slabs", slab_id)
            chosen = set(p.slabs)
        else:
            stories = P.resolve_storeys(plan, p.storeys or "all")
            chosen = {s["id"] for s in slabs if s.get("story") in stories}
        for s in slabs:
            if s["id"] in chosen:
                s["areaLoad"] = area_id
                assigned.append(s["id"])
        if not assigned:
            refuse("There are no slabs to load there (slabs.place first).", "storeys", p.storeys)
        view.put(FLOOR_PLAN, plan)
    values = ", ".join(
        f"{k} {fmt(v)} kN/m²"
        for k, v in (
            ("SD", area.get("finish")),
            ("live", area.get("live")),
            ("partitions", area.get("partitions")),
        )
        if v is not None
    )
    message = f"Area load {area_id} ({area.get('use')}): {values}"
    if assigned:
        message += f"; on {len(assigned)} slabs"
    return ActionResult(message=message + ".", created=created)


# ── member loads ──


def _loads(view: ProjectView) -> dict[str, Any]:
    data = view.part(LOADS, None)
    if not isinstance(data, dict):
        from saengine.library.line_loads import default_loads

        data = default_loads().model_dump(mode="json", by_alias=True, exclude_none=True)
    data.setdefault("loads", [])
    data.setdefault("wallTypes", [])
    return data


def _next_load_id(data: dict[str, Any], prefix: str, taken: set[str]) -> str:
    used = {x.get("id") for x in data.get("loads") or []} | taken
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    taken.add(f"{prefix}{n}")
    return f"{prefix}{n}"


def _beams(view: ProjectView, ids: list[str]) -> list[dict[str, Any]]:
    plan = view.read(FLOOR_PLAN)
    found = []
    for beam_id in ids:
        group, member = P.find_member(plan, beam_id)
        if group != "beams":
            refuse(
                f"{beam_id} is a {group[:-1]}, not a beam: line loads go on beams.",
                "beams",
                beam_id,
            )
        found.append(member)
    return found


def _beam_ids(view: ProjectView, beams: list[str] | None, storeys: Any) -> list[str]:
    if beams:
        return beams
    if storeys is None:
        refuse("Give the beams (ids) or the storeys whose beams to load.", "beams", None)
    plan = view.read(FLOOR_PLAN)
    # A load on a typical floor applies to its whole family (line_loads.stories_of): one storey
    # of each family is loaded, else the family would carry it twice.
    stories = {P.family(plan, s)[0] for s in P.resolve_storeys(plan, storeys)}
    ids = [b["id"] for b in P.members(plan, "beams") if b.get("story") in stories]
    if not ids:
        refuse("There are no beams on those storeys (beams.place first).", "storeys", storeys)
    return ids


class LineParams(Params):
    beams: list[str] | None = Field(default=None, description="Beam ids.")
    storeys: P.Storeys | None = Field(default=None, description="Or: every beam of these storeys.")
    value: float = Field(description="Uniform load [kN/m, down].")
    case: Case = Field(default="SD", description="Load case: D, SD, L or Lr.")
    thisStoryOnly: bool = Field(
        default=False, description="On a typical floor: only this storey, not its family."
    )
    note: str = ""


@action(
    "load.line.add",
    summary="Add a uniform line load [kN/m] on beams (by id, or every beam of storeys).",
    params=LineParams,
    parts=("loads",),
    kind="edit",
    example={"beams": ["B1"], "value": 5, "case": "SD"},
)
def load_line_add(view: ProjectView, p: LineParams) -> ActionResult:
    data = _loads(view)
    created: list[str] = []
    taken: set[str] = set()
    for beam in _beams(view, _beam_ids(view, p.beams, p.storeys)):
        load_id = _next_load_id(data, "LL", taken)
        data["loads"].append(
            {
                "id": load_id,
                "kind": "line",
                "story": beam["story"],
                "member": beam["id"],
                "case": p.case,
                "value": p.value,
                "thisStoryOnly": p.thisStoryOnly,
                "note": p.note,
            }
        )
        created.append(load_id)
    view.put(LOADS, data)
    return ActionResult(
        message=f"{fmt(p.value)} kN/m ({p.case}) on {len(created)} beams.", created=created
    )


class PointParams(Params):
    member: str = Field(description="A beam id (with distance) or a column id (a joint load).")
    value: float = Field(description="[kN, down]")
    distance: float | None = Field(default=None, description="Beams: from its start [mm].")
    story: str | None = Field(
        default=None, description="Columns: the storey of the joint (default: the column's top)."
    )
    case: Case = "SD"
    thisStoryOnly: bool = False
    note: str = ""


@action(
    "load.point.add",
    summary="Add a point load [kN] on a beam (at a distance from its start) or at a column's joint.",
    params=PointParams,
    parts=("loads",),
    kind="edit",
    example={"member": "B1", "value": 20, "distance": 2500, "case": "L"},
)
def load_point_add(view: ProjectView, p: PointParams) -> ActionResult:
    plan = view.read(FLOOR_PLAN)
    group, member = P.find_member(plan, p.member)
    if group == "beams":
        if p.distance is None:
            refuse(
                "A point load on a beam needs its distance from the beam's start [mm].",
                "distance",
                None,
            )
        story = member["story"]
        a, b = P.where(plan, member["start"]), P.where(plan, member["end"])
        length = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        if p.distance > length + 1e-6:
            refuse(
                f"{fmt(p.distance)} mm is beyond the end of {p.member} ({fmt(round(length))} mm "
                "long).",
                "distance",
                p.distance,
            )
    elif group == "columns":
        if p.distance is not None:
            refuse("A joint load on a column has no distance.", "distance", p.distance)
        story = p.story or member["top"]
        P.check_story(plan, story, "story")
    else:
        refuse(
            f"{p.member} is a {group[:-1]}: point loads go on beams and columns.",
            "member",
            p.member,
        )
        raise AssertionError  # pragma: no cover
    data = _loads(view)
    load_id = _next_load_id(data, "PL", set())
    entry: dict[str, Any] = {
        "id": load_id,
        "kind": "point",
        "story": story,
        "member": p.member,
        "case": p.case,
        "value": p.value,
        "thisStoryOnly": p.thisStoryOnly,
        "note": p.note,
    }
    if p.distance is not None:
        entry["distance"] = p.distance
    data["loads"].append(entry)
    view.put(LOADS, data)
    return ActionResult(message=f"{fmt(p.value)} kN ({p.case}) on {p.member}.", created=[load_id])


class WallParams(Params):
    beams: list[str] | None = Field(default=None, description="Beam ids the walls stand on.")
    storeys: P.Storeys | None = Field(default=None, description="Or: every beam of these storeys.")
    wallType: str | None = Field(
        default=None,
        description="Wall type id of loads.json (the pack's masonry walls); default: the first.",
    )
    height: float | None = Field(
        default=None, description="Wall height [mm]; none: worked out per storey (auto)."
    )
    openings: float = Field(default=0, description="Doors and windows, % of the wall's face.")
    skipRoof: bool = Field(default=False, description="Auto height: no parapet on the top storey.")
    thisStoryOnly: bool = False


@action(
    "load.wall.add",
    summary="Add masonry wall loads on beams: a wall type of the pack's dead loads with its "
    "height (or the storey height less the beam above) and openings.",
    params=WallParams,
    parts=("loads",),
    kind="edit",
    example={"storeys": "all", "openings": 20},
)
def load_wall_add(view: ProjectView, p: WallParams) -> ActionResult:
    data = _loads(view)
    types = [w.get("id") for w in data["wallTypes"]]
    wall_type = p.wallType or (types[0] if types else None)
    if wall_type is None:
        refuse(
            "There are no wall types in loads.json: the code pack gives none; add one.",
            "wallType",
            None,
        )
    if wall_type not in types:
        refuse(
            f"There is no wall type '{wall_type}' (the wall types: {', '.join(types)}).",
            "wallType",
            wall_type,
        )
    auto = p.height is None
    plan = view.read(FLOOR_PLAN)
    created: list[str] = []
    taken: set[str] = set()
    for beam in _beams(view, _beam_ids(view, p.beams, p.storeys)):
        height = p.height
        if height is None:  # the storey height it was entered on (auto works it out per storey)
            ids = P.story_ids(plan)
            index = ids.index(beam["story"])
            levels = {s["id"]: float(s["elevation"]) for s in P.stories(plan)}
            upper = ids[index + 1] if index + 1 < len(ids) else None
            height = (levels[upper] - levels[beam["story"]]) if upper else 1000.0
        wall: dict[str, Any] = {"type": wall_type, "height": height, "openings": p.openings}
        if auto:
            wall["auto"] = True
            wall["skipRoof"] = p.skipRoof
        load_id = _next_load_id(data, "LL", taken)
        data["loads"].append(
            {
                "id": load_id,
                "kind": "line",
                "story": beam["story"],
                "member": beam["id"],
                "case": "SD",
                "wall": wall,
                "thisStoryOnly": p.thisStoryOnly,
                "note": "",
            }
        )
        created.append(load_id)
    view.put(LOADS, data)
    how = "its height per storey" if auto else f"{fmt(p.height or 0)} mm high"
    return ActionResult(
        message=f"Wall loads ({wall_type}, {how}, {fmt(p.openings)} % openings) on "
        f"{len(created)} beams.",
        created=created,
    )
