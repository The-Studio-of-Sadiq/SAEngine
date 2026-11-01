"""Line and point loads on members (``05 Floor Plan/loads.json``): brick walls on beams and the like.

Bangladeshi buildings carry 125 mm and 250 mm brick walls on the beams of every floor, parapets
on the roof beams and water tanks on beams. The engineer enters them on the floor plan as

- a **line load** along a whole beam: a wall type × height (kN/m = the wall's weight per m² ×
  its height, less an openings percentage) or an explicit kN/m;
- a **point load** (kN) on a beam, at a distance from its start, or at a joint (a column at the
  story's level).

Loads are kept in a file of their own beside the floor plan rather than in ``floor-plan.json``:
the floor plan is the geometry (its schema forbids extra fields and every downstream part reads
it), while these loads change often and are read by the analysis model alone. A project without
the file has no member loads, so older projects stay valid unchanged.

Every load names the member it is on (a floor-plan beam, or a column for a joint load) and the
story it was entered on. Typical floors (``similarTo``): a load on any story of a family applies
to the beam at the same place on every story of that family, as members follow the typical
floor; ``thisStoryOnly`` keeps it to its own story. The analysis model applies loads through the
building model (:mod:`saengine.fem.member_loads`), so the places are compared there.

Units: mm for heights and distances, kN/m for line loads, kN for point loads, kN/m³ for unit
weights (the code's tables give kN/m² per thickness; see :func:`default_wall_types`).
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator

from saengine.library.labels import field_title
from saengine.library.materials import Id

SCHEMA_ID = "saengine.memberLoads/1"
LOADS_FILE = "05 Floor Plan/loads.json"

#: Gravity load cases a member load can go to (the analysis model's, saengine.fem.derive.CASES).
LoadCase = Literal["D", "SD", "L", "Lr"]
LOAD_CASES: dict[str, str] = {
    "D": "Dead",
    "SD": "Superimposed dead",
    "L": "Live",
    "Lr": "Roof live",
}

Mm = Annotated[float, Field(description="[mm]")]


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class WallType(_Model):
    """A masonry wall with its plaster: its weight per m² of wall face."""

    id: Id
    name: str = Field(min_length=1)
    thickness: float = Field(gt=0, description="Masonry thickness, without plaster [mm].")
    unitWeight: float = Field(
        gt=0, title="Masonry unit weight", description="Of the masonry [kN/m³]."
    )
    plaster: float = Field(default=0, ge=0, description="Plaster thickness on each face [mm].")
    plasterFaces: int = Field(default=2, ge=0, le=2, title="Plastered faces")
    plasterUnitWeight: float = Field(default=23.0, ge=0, description="[kN/m³]")

    def weight_per_area(self) -> float:
        """kN/m² of wall face: masonry plus plaster."""
        return (
            self.unitWeight * self.thickness
            + self.plasterUnitWeight * self.plaster * self.plasterFaces
        ) / 1000


#: A parapet on a roof beam (no story above) [mm].
PARAPET_HEIGHT = 1000.0


class WallLoad(_Model):
    """A wall standing on the beam: its type, height and openings."""

    type: Id = Field(title="Wall type")
    height: float = Field(
        gt=0,
        description="Height of the wall on the beam [mm]; with ``auto``, its height on the beam "
        "and story it was entered on.",
    )
    auto: bool = Field(
        default=False,
        title="Height per story",
        description="The height is worked out on each beam and story it applies to: the story "
        "height above less the depth of the beam above (else of the loaded beam), and a parapet "
        "on the top story. Typical floors of different heights get their own walls.",
    )
    skipRoof: bool = Field(
        default=False,
        title="None on the top story",
        description="With ``auto``: no wall on the top story, instead of a parapet.",
    )
    openings: float = Field(
        default=0,
        ge=0,
        lt=100,
        description="Doors and windows, as a percentage of the wall's face; the load is reduced "
        "by it.",
    )


class _Load(_Model):
    id: Id
    story: Id = Field(description="Story the load was entered on.")
    member: Id = Field(description="Floor-plan beam (or, for a joint load, column) it is on.")
    case: LoadCase = Field(default="SD", title="Load case")
    thisStoryOnly: bool = Field(
        default=False,
        title="This story only",
        description="On a typical floor: only on this story, not on the stories like it.",
    )
    note: str = ""


class LineLoad(_Load):
    """A uniform load along a whole beam: from a wall, or an explicit value."""

    kind: Literal["line"] = "line"
    wall: WallLoad | None = None
    value: float | None = Field(
        default=None, description="Explicit load [kN/m, down]; none: from the wall."
    )

    @model_validator(mode="after")
    def _one_source(self) -> LineLoad:
        if (self.wall is None) == (self.value is None):
            raise ValueError(f"{self.id}: give either a wall or a value in kN/m")
        return self


class PointLoad(_Load):
    """A concentrated load on a beam at ``distance`` from its start, or at a column's joint."""

    kind: Literal["point"] = "point"
    value: float = Field(description="[kN, down]")
    distance: Mm | None = Field(
        default=None,
        ge=0,
        description="From the beam's start [mm]; none for a joint load on a column.",
    )


def _kind(value: Any) -> str:
    """A load's kind; a line load when the file leaves it out."""
    if isinstance(value, dict):
        return value.get("kind", "line")
    return getattr(value, "kind", "line")


MemberLoad = Annotated[
    Annotated[LineLoad, Tag("line")] | Annotated[PointLoad, Tag("point")], Discriminator(_kind)
]


class MemberLoads(_Model):
    schema_: Literal["saengine.memberLoads/1"] = Field(default=SCHEMA_ID, alias="schema")
    wallTypes: list[WallType] = Field(default_factory=list, title="Wall types")
    loads: list[MemberLoad] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references(self) -> MemberLoads:
        for what, ids in (
            ("wall type", [w.id for w in self.wallTypes]),
            ("load", [load.id for load in self.loads]),
        ):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate {what} ids: {', '.join(duplicates)}")
        known = {w.id for w in self.wallTypes}
        for load in self.loads:
            if isinstance(load, LineLoad) and load.wall and load.wall.type not in known:
                raise ValueError(f"{load.id}: no wall type '{load.wall.type}'")
        return self

    def wall_type(self, type_id: str) -> WallType | None:
        return next((w for w in self.wallTypes if w.id == type_id), None)


# ── wall weights from the code pack ──


def _dead_loads_table() -> dict[str, Any]:
    """The code pack's ``deadLoads`` table as plain data (the default pack's Part 6 Sec 2.2.4, Table
    6.2.2, pp. 530-531, in the default pack); empty when the pack has none (no default wall
    types: the engineer enters them)."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    if pack.has("deadLoads"):
        data = pack.data("deadLoads")
        return data if isinstance(data, dict) else {}
    return {}


def default_wall_types() -> list[WallType]:
    """The wall types a new loads file starts with, from the code pack (default pack: 125 mm and
    250 mm burnt-clay brick walls with 12.5 mm cement plaster on both faces)."""
    table = _dead_loads_table()
    masonry = table.get("masonry", {})
    plaster = table.get("plaster", {})
    types = []
    for row in table.get("wallTypes", []):
        types.append(
            WallType(
                id=row["id"],
                name=row["name"],
                thickness=row["thickness"],
                unitWeight=masonry[row.get("masonry", "burntClayBrick")],
                plaster=row.get("plaster", 0),
                plasterFaces=row.get("plasterFaces", 2),
                plasterUnitWeight=plaster.get(row.get("plasterKind", "cement"), 23.0),
            )
        )
    return types


def default_loads() -> MemberLoads:
    return MemberLoads(wallTypes=default_wall_types())


def parse(text: str | None) -> MemberLoads:
    """The member loads of a file's text; none for a missing or empty file. Raises
    ``ValueError`` (pydantic's ``ValidationError``) for an invalid file."""
    if not text or not text.strip():
        return MemberLoads()
    return MemberLoads.model_validate(json.loads(text))


# ── values ──


def wall_line_load(wall_type: WallType, height: float, openings: float = 0.0) -> float:
    """kN/m of a wall of ``height`` mm on a beam, ``openings`` % of its face left out."""
    return wall_type.weight_per_area() * height / 1000 * (1 - openings / 100)


def auto_height(
    wall: WallLoad,
    story_height: float | None,
    depth: float | None,
    entered: float | None = None,
) -> float | None:
    """The height [mm] of an ``auto`` wall on a beam: ``story_height`` (to the story above; None
    on the top story) less ``depth`` (of the beam above it, else of the loaded beam). On the top
    story a parapet, or none (None) with ``skipRoof``. Without a depth, the entered height
    changed by as much as the story's height differs from ``entered``, the height of the story
    it was entered on.

    A wall not ``auto`` keeps its height everywhere."""
    if not wall.auto:
        return wall.height
    if story_height is None:
        return None if wall.skipRoof else PARAPET_HEIGHT
    if depth is None:
        if entered is None:
            return wall.height
        depth = entered - wall.height
    height = story_height - depth
    if height <= 0:
        return None if wall.skipRoof else PARAPET_HEIGHT
    return height


def line_value(
    load: LineLoad, loads: MemberLoads, height: float | None = None, *, parapet: bool = False
) -> float:
    """kN/m of a line load (0 for a wall of an unknown type, which validation forbids); a wall
    ``height`` other than its own (an ``auto`` wall's on another story). A ``parapet`` (an
    ``auto`` wall on the top story) has no openings."""
    if load.value is not None:
        return load.value
    assert load.wall is not None
    wall_type = loads.wall_type(load.wall.type)
    if wall_type is None:
        return 0.0
    used = load.wall.height if height is None else height
    return wall_line_load(wall_type, used, 0.0 if parapet else load.wall.openings)


def describe(load: LineLoad | PointLoad, loads: MemberLoads) -> str:
    """How the load was formed, for lists and reports: "BW250 × 2.75 m − 20 % = 11.77 kN/m"."""
    if isinstance(load, PointLoad):
        where = f" at {load.distance:g} mm" if load.distance is not None else " at the joint"
        return f"{load.value:g} kN{where}"
    if load.wall is None:
        return f"{load.value:g} kN/m"
    reduction = f" − {load.wall.openings:g} %" if load.wall.openings else ""
    per_story = " (height per story)" if load.wall.auto else ""
    return (
        f"{load.wall.type} × {load.wall.height / 1000:g} m{reduction} = "
        f"{line_value(load, loads):.2f} kN/m{per_story}"
    )


# ── typical floors ──


def families(stories: list[Any]) -> dict[str, list[str]]:
    """Story id -> the stories of its typical-floor family (itself alone when it has none).
    ``stories``: objects with ``id`` and ``similarTo`` (floor-plan or building-model stories)."""
    ids = {s.id for s in stories}
    master_of = {
        s.id: (s.similarTo if getattr(s, "similarTo", None) in ids else s.id) for s in stories
    }
    members: dict[str, list[str]] = {}
    for s in stories:
        members.setdefault(master_of[s.id], []).append(s.id)
    return {s.id: members[master_of[s.id]] for s in stories}


def stories_of(load: LineLoad | PointLoad, stories: list[Any]) -> list[str]:
    """The stories ``load`` applies to: its family's, or its own with ``thisStoryOnly``."""
    if load.thisStoryOnly:
        return [load.story]
    return families(stories).get(load.story, [load.story])


def check(loads: MemberLoads, plan: Any) -> list[str]:
    """Problems with what the loads refer to in the floor plan (``FloorPlan``)."""
    stories = {s.id for s in plan.stories}
    beams = {b.id: b for b in plan.beams}
    columns = {c.id: c for c in plan.columns}
    problems = []
    for load in loads.loads:
        if load.story not in stories:
            problems.append(f"{load.id}: no story '{load.story}'")
            continue
        if load.member in beams:
            if beams[load.member].story != load.story:
                problems.append(f"{load.id}: beam {load.member} is not on story {load.story}")
        elif load.member in columns and isinstance(load, PointLoad):
            column = columns[load.member]
            levels = {s.id: s.elevation for s in plan.stories}
            if not levels[column.base] < levels[load.story] <= levels[column.top]:
                problems.append(f"{load.id}: column {load.member} does not reach {load.story}")
        else:
            what = "beam or column" if isinstance(load, PointLoad) else "beam"
            problems.append(f"{load.id}: no {what} '{load.member}'")
    return problems
