"""The architecture (``05 Floor Plan/architecture.json``): walls, doors, windows and rooms.

The architect's layer of the building, drawn on the floor plan's grids and stories: masonry and
partition walls of layered wall types, doors and windows hosted in them, and rooms found from
the walls around a picked point (with room separators where there is no wall). It is physical
only: it never adds stiffness to the analysis. Its loads (the walls' weight, the rooms'
finishes and occupancy live loads) are derived from it when the analysis model is derived
(:mod:`saengine.fem.architecture_loads`), and the bill of quantities measures its brickwork,
plaster, finishes, doors and windows (:mod:`saengine.boq.architecture`).

Kept simple on purpose (no Revit clone): door and window types are fixed parametric styles (no
family editor), a wall is one type over its height (no stacked walls), and there are no phases,
design options or worksets.

Units: mm for coordinates, lengths and levels; kN/m³ for unit weights. Plan coordinates are
global (the floor plan's); a story is a floor-plan story id. A wall's ``path`` is its location
line (the wall type's); a door's or window's ``offset`` is the distance along the wall's centre
line from its start to the opening's centre.
"""

from __future__ import annotations

import itertools
import json
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.labels import field_title
from saengine.library.materials import Id

SCHEMA_ID = "saengine.architecture/1"
ARCHITECTURE_FILE = "05 Floor Plan/architecture.json"

Length = Annotated[float, Field(gt=0, description="[mm]")]
Mm = Annotated[float, Field(description="[mm]")]
Point2 = Annotated[list[float], Field(min_length=2, max_length=2, description="[x, y] in mm.")]
UnitWeight = Annotated[float, Field(ge=0, description="[kN/m³]")]

#: How far a wall's centre line runs past its ends when rooms are found [mm], at least: walls
#: drawn to the face of another wall (as Revit joins them) still close a room.
JOIN_REACH = 1.0


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


# ───────────────────────────── types ─────────────────────────────


class WallLayer(_Model):
    """One layer of a wall type, from the wall's left face to its right (seen along its path)."""

    material: str = Field(min_length=1, description="e.g. Brick, Cement plaster.")
    thickness: Length
    unitWeight: UnitWeight = Field(title="Unit weight")


class WallType(_Model):
    id: Id
    name: str = Field(min_length=1)
    layers: list[WallLayer] = Field(min_length=1)
    locationLine: Literal["center", "left", "right"] = Field(
        default="center",
        title="Location line",
        description="What a wall's path runs along: its centre, or its left or right face "
        "(seen walking from the path's start to its end).",
        json_schema_extra={"enumDescriptions": ["Wall centre", "Left face", "Right face"]},
    )

    @property
    def thickness(self) -> float:
        return sum(layer.thickness for layer in self.layers)

    @property
    def weight(self) -> float:
        """Weight per wall area [kN/m²]."""
        return sum(layer.thickness / 1000 * layer.unitWeight for layer in self.layers)


class DoorType(_Model):
    """A door of a fixed parametric style (no family editor)."""

    id: Id
    name: str = Field(min_length=1)
    style: Literal["single", "double", "sliding"] = Field(
        default="single",
        json_schema_extra={"enumDescriptions": ["Single swing", "Double swing", "Sliding"]},
    )
    width: Length = Field(description="Clear opening width [mm].")
    height: Length = Field(description="Clear opening height [mm].")
    frame: Length = Field(default=50, description="Frame width [mm].")


class WindowType(_Model):
    """A window of a fixed parametric style (no family editor)."""

    id: Id
    name: str = Field(min_length=1)
    style: Literal["fixed", "casement", "sliding"] = Field(
        default="sliding",
        json_schema_extra={"enumDescriptions": ["Fixed", "Casement", "Sliding"]},
    )
    width: Length
    height: Length
    sill: Mm = Field(default=900, ge=0, description="Sill height above the floor [mm].")
    frame: Length = Field(default=50, description="Frame width [mm].")


class FinishType(_Model):
    id: Id
    name: str = Field(min_length=1)
    kind: Literal["floor", "wall", "ceiling"] = Field(
        json_schema_extra={"enumDescriptions": ["Floor finish", "Wall finish", "Ceiling finish"]}
    )
    thickness: Length
    unitWeight: UnitWeight = Field(title="Unit weight")
    sunkFilling: Mm | None = Field(
        default=None,
        ge=0,
        title="Sunk filling",
        description="Filling of a sunk slab under the finish in wet rooms (toilets, kitchens) "
        "[mm]; its weight is added to the finish there.",
    )
    sunkUnitWeight: UnitWeight = Field(
        default=16.0,
        title="Filling unit weight",
        description="Of the sunk slab's filling [kN/m³] (16: brick-bat filling, an SAEngine "
        "choice; enter yours).",
    )


# ───────────────────────────── instances ─────────────────────────────


class ArchWall(_Model):
    id: Id
    type: Id = Field(title="Wall type")
    base: Id = Field(description="Story the wall stands on.")
    top: Id | None = Field(
        default=None,
        description="Story the wall rises to (empty: the next story up, or its height).",
    )
    height: Length | None = Field(
        default=None, description="Height above its base [mm], instead of a top story."
    )
    baseOffset: Mm = Field(default=0, title="Base offset", description="Above the base story [mm].")
    path: list[Point2] = Field(min_length=2, description="The location line, point by point.")
    structuralRef: Id | None = Field(
        default=None,
        title="Sits on",
        description="The floor-plan beam or wall it stands on (informative: no stiffness).",
    )


class Door(_Model):
    id: Id
    type: Id = Field(title="Door type")
    wall: Id = Field(title="Host wall")
    offset: Mm = Field(ge=0, description="Along the wall from its start to the centre [mm].")
    flip: bool = Field(default=False, description="Swings to the other side.")


class Window(_Model):
    id: Id
    type: Id = Field(title="Window type")
    wall: Id = Field(title="Host wall")
    offset: Mm = Field(ge=0, description="Along the wall from its start to the centre [mm].")
    sill: Mm | None = Field(
        default=None, ge=0, description="Sill height [mm] (empty: the window type's)."
    )


class Room(_Model):
    id: Id
    story: Id
    point: Point2 = Field(description="A point inside the room; its walls are found around it.")
    name: str = Field(default="Room", min_length=1)
    number: str = ""
    occupancy: str | None = Field(
        default=None, description="Area use from the code pack (e.g. BNBC's), for its loads."
    )
    floorFinish: Id | None = Field(default=None, title="Floor finish")
    wallFinish: Id | None = Field(default=None, title="Wall finish")
    ceilingFinish: Id | None = Field(default=None, title="Ceiling finish")
    wet: bool = Field(default=False, description="Toilet, kitchen or other wet area.")


class RoomSeparator(_Model):
    """A line that bounds rooms where there is no wall (an open plan's kitchen and dining)."""

    id: Id
    story: Id
    start: Point2
    end: Point2


DrawingRole = Literal["walls", "doors", "windows", "rooms", "ignore"]
DrawingUnit = Literal["mm", "cm", "m", "ft", "in"]


class DrawingImport(_Model):
    """An import of an architect's DWG/DXF onto one story: the layer mapping and placement used
    (offered again next time) and the items it made (replaced when the same file is imported onto
    the same story again)."""

    file: str = Field(min_length=1, description="The drawing (relative to the project folder).")
    story: Id
    layers: dict[str, DrawingRole] = Field(
        default_factory=dict, description="What each layer of the drawing holds."
    )
    unit: DrawingUnit = Field(default="mm", description="The drawing's unit.")
    base: Point2 = Field(
        default_factory=lambda: [0.0, 0.0],
        description="The drawing's point placed at `at` [drawing units].",
    )
    at: Point2 = Field(default_factory=lambda: [0.0, 0.0], description="[x, y] in mm.")
    rotation: float = Field(default=0, description="[°], counter-clockwise about `at`.")
    items: list[Id] = Field(default_factory=list, description="The walls, doors, ... it made.")


class Architecture(_Model):
    schema_: Literal["saengine.architecture/1"] = Field(default=SCHEMA_ID, alias="schema")
    wallTypes: list[WallType] = Field(default_factory=list, title="Wall types")
    doorTypes: list[DoorType] = Field(default_factory=list, title="Door types")
    windowTypes: list[WindowType] = Field(default_factory=list, title="Window types")
    finishTypes: list[FinishType] = Field(default_factory=list, title="Finish types")
    walls: list[ArchWall] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    rooms: list[Room] = Field(default_factory=list)
    separators: list[RoomSeparator] = Field(default_factory=list, title="Room separators")
    imports: list[DrawingImport] = Field(
        default_factory=list,
        title="Drawing imports",
        description="Architects' DWG/DXF drawings imported, to import them again.",
    )

    def instances(self) -> list[Any]:
        return [*self.walls, *self.doors, *self.windows, *self.rooms, *self.separators]

    @model_validator(mode="after")
    def _references(self) -> Architecture:
        for name, items in (
            ("wall type", self.wallTypes),
            ("door type", self.doorTypes),
            ("window type", self.windowTypes),
            ("finish type", self.finishTypes),
        ):
            ids = [t.id for t in items]
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate {name} ids: {', '.join(duplicates)}")
        ids = [i.id for i in self.instances()]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate ids: {', '.join(duplicates)}")

        wall_types = {t.id for t in self.wallTypes}
        walls = {w.id for w in self.walls}
        for wall in self.walls:
            if wall.type not in wall_types:
                raise ValueError(f"{wall.id}: no wall type '{wall.type}'")
            if wall.top is not None and wall.height is not None:
                raise ValueError(f"{wall.id}: give a top story or a height, not both")
            if _length(wall.path) <= 0:
                raise ValueError(f"{wall.id}: its path has no length")
        for openings, types, kind in (
            (self.doors, {t.id for t in self.doorTypes}, "door"),
            (self.windows, {t.id for t in self.windowTypes}, "window"),
        ):
            for opening in openings:
                if opening.type not in types:
                    raise ValueError(f"{opening.id}: no {kind} type '{opening.type}'")
                if opening.wall not in walls:
                    raise ValueError(f"{opening.id}: no wall '{opening.wall}' to sit in")
        finishes = {t.id: t.kind for t in self.finishTypes}
        for room in self.rooms:
            for field, kind in (
                ("floorFinish", "floor"),
                ("wallFinish", "wall"),
                ("ceilingFinish", "ceiling"),
            ):
                finish = getattr(room, field)
                if finish is None:
                    continue
                if finish not in finishes:
                    raise ValueError(f"{room.id}: no finish type '{finish}'")
                if finishes[finish] != kind:
                    raise ValueError(f"{room.id}: '{finish}' is a {finishes[finish]} finish")
        return self


def default_architecture() -> Architecture:
    """Common Bangladeshi practice: 250 mm brick outer walls, 125 mm partitions, both plastered;
    the doors and windows of a typical flat; tiles, plaster and paint."""
    plaster = {"material": "Cement plaster", "unitWeight": 20.4}
    brick = {"material": "Brick", "unitWeight": 18.85}
    return Architecture.model_validate(
        {
            "wallTypes": [
                {
                    "id": "BW250",
                    "name": "Brick wall 250 mm, plastered",
                    "layers": [
                        {**plaster, "thickness": 12},
                        {**brick, "thickness": 250},
                        {**plaster, "thickness": 12},
                    ],
                },
                {
                    "id": "BW125",
                    "name": "Brick partition 125 mm, plastered",
                    "layers": [
                        {**plaster, "thickness": 12},
                        {**brick, "thickness": 125},
                        {**plaster, "thickness": 12},
                    ],
                },
            ],
            "doorTypes": [
                {"id": "D1", "name": "Main door", "style": "single", "width": 1000, "height": 2100},
                {"id": "D2", "name": "Room door", "style": "single", "width": 900, "height": 2100},
                {
                    "id": "D3",
                    "name": "Toilet door",
                    "style": "single",
                    "width": 750,
                    "height": 2100,
                },
                {
                    "id": "DD",
                    "name": "Double door",
                    "style": "double",
                    "width": 1500,
                    "height": 2100,
                },
            ],
            "windowTypes": [
                {"id": "W1", "name": "Window", "style": "sliding", "width": 1500, "height": 1500},
                {
                    "id": "W2",
                    "name": "Small window",
                    "style": "sliding",
                    "width": 1200,
                    "height": 1200,
                },
                {
                    "id": "V1",
                    "name": "Ventilator",
                    "style": "fixed",
                    "width": 600,
                    "height": 450,
                    "sill": 1650,
                },
            ],
            "finishTypes": [
                {
                    "id": "TILE",
                    "name": "Floor tiles on mortar",
                    "kind": "floor",
                    "thickness": 40,
                    "unitWeight": 21,
                },
                {
                    "id": "PLASTER",
                    "name": "Plaster and paint",
                    "kind": "wall",
                    "thickness": 12,
                    "unitWeight": 20.4,
                },
                {
                    "id": "CEIL",
                    "name": "Ceiling plaster",
                    "kind": "ceiling",
                    "thickness": 6,
                    "unitWeight": 20.4,
                },
            ],
        }
    )


def is_placeholder(data: Any) -> bool:
    return isinstance(data, dict) and data.get("schema") != SCHEMA_ID and "part" in data


def parse(text: str | None) -> Architecture:
    """The architecture of a file's text; the default types for a missing or empty file.
    Raises ``ValueError`` (pydantic's ``ValidationError``) for an invalid file."""
    if not text or not text.strip():
        return default_architecture()
    data = json.loads(text)
    if is_placeholder(data):
        return default_architecture()
    return Architecture.model_validate(data)


# ───────────────────────────── geometry ─────────────────────────────


def _length(points: list[list[float]]) -> float:
    return sum(math.dist(a, b) for a, b in itertools.pairwise(points))


def offset_path(points: list[list[float]], distance: float) -> list[tuple[float, float]]:
    """``points`` moved ``distance`` to the left (seen along the path), with mitred corners (a
    closed path is mitred where it closes too)."""
    if not distance:
        return [(float(x), float(y)) for x, y in points]
    normals = []
    for (x1, y1), (x2, y2) in itertools.pairwise(points):
        length = math.hypot(x2 - x1, y2 - y1) or 1.0
        normals.append((-(y2 - y1) / length, (x2 - x1) / length))
    closed = len(points) > 3 and math.dist(points[0], points[-1]) < 1e-6
    result = []
    for i, (x, y) in enumerate(points):
        end = i == 0 or i == len(points) - 1
        if end and not closed:
            nx, ny = normals[0] if i == 0 else normals[-1]
            result.append((x + nx * distance, y + ny * distance))
            continue
        (ax, ay), (bx, by) = (normals[-1], normals[0]) if end else (normals[i - 1], normals[i])
        mx, my = ax + bx, ay + by
        dot = mx * ax + my * ay
        scale = distance / dot if abs(dot) > 1e-9 else distance
        result.append((x + mx * scale, y + my * scale))
    return result


def centre_line(wall: ArchWall, wall_type: WallType) -> list[tuple[float, float]]:
    """The wall's centre line from its path (its type's location line)."""
    half = wall_type.thickness / 2
    shift = {"center": 0.0, "left": -half, "right": half}[wall_type.locationLine]
    return offset_path(wall.path, shift)


def point_along(
    points: list[tuple[float, float]], offset: float
) -> tuple[tuple[float, float], tuple[float, float]]:
    """The point ``offset`` along a polyline and its direction (unit vector) there."""
    remaining = max(0.0, offset)
    segments = list(itertools.pairwise(points))
    for i, ((x1, y1), (x2, y2)) in enumerate(segments):
        length = math.hypot(x2 - x1, y2 - y1)
        if remaining <= length or i == len(segments) - 1:
            t = min(remaining, length) / length if length else 0.0
            direction = ((x2 - x1) / length, (y2 - y1) / length) if length else (1.0, 0.0)
            return (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t), direction
        remaining -= length
    return (points[0][0], points[0][1]), (1.0, 0.0)


def wall_levels(wall: ArchWall, elevations: dict[str, float]) -> tuple[float, float] | None:
    """The wall's bottom and top [mm], or None when its stories are not in ``elevations``."""
    if wall.base not in elevations:
        return None
    bottom = elevations[wall.base] + wall.baseOffset
    if wall.height is not None:
        return bottom, bottom + wall.height
    if wall.top is not None:
        if wall.top not in elevations:
            return None
        return bottom, elevations[wall.top]
    above = sorted(e for e in elevations.values() if e > elevations[wall.base])
    return (bottom, above[0]) if above else None


def opening_size(arch: Architecture, opening: Door | Window) -> tuple[float, float, float]:
    """Width, height and sill [mm] of a door (sill 0) or window."""
    if isinstance(opening, Door):
        door = next(t for t in arch.doorTypes if t.id == opening.type)
        return door.width, door.height, 0.0
    window = next(t for t in arch.windowTypes if t.id == opening.type)
    return window.width, window.height, window.sill if opening.sill is None else opening.sill


def walls_on_story(
    arch: Architecture, story: str, elevations: dict[str, float]
) -> list[tuple[ArchWall, WallType]]:
    """The walls standing on ``story`` or rising through it."""
    if story not in elevations:
        return []
    level = elevations[story]
    types = {t.id: t for t in arch.wallTypes}
    result = []
    for wall in arch.walls:
        levels = wall_levels(wall, elevations)
        if levels is None:
            continue
        bottom, top = levels
        if wall.base == story or bottom - 1e-6 <= level < top - 1e-6:
            result.append((wall, types[wall.type]))
    return result


def room_boundary(
    arch: Architecture, room: Room, elevations: dict[str, float]
) -> tuple[Any, Any] | None:
    """The room around its point: the face of the wall centre lines and separators that holds it
    (shapely ``polygonize``), and the same less the walls (its net floor). None when the point is
    not enclosed."""
    from shapely.geometry import LineString, Point
    from shapely.ops import polygonize, unary_union

    walls = walls_on_story(arch, room.story, elevations)
    reach = max([JOIN_REACH, *(t.thickness / 2 + JOIN_REACH for _, t in walls)])
    lines = []
    footprints = []
    for wall, wall_type in walls:
        centre = centre_line(wall, wall_type)
        lines.append(LineString(_extended(centre, reach)))
        footprints.append(
            LineString(centre).buffer(wall_type.thickness / 2, cap_style="flat", join_style="mitre")
        )
    lines += [LineString([s.start, s.end]) for s in arch.separators if s.story == room.story]
    if not lines:
        return None
    point = Point(room.point)
    faces = [f for f in polygonize(unary_union(lines)) if f.contains(point)]
    if not faces:
        return None
    face = min(faces, key=lambda f: f.area)
    net = face.difference(unary_union(footprints)) if footprints else face
    if net.geom_type == "MultiPolygon":
        net = next(
            (g for g in net.geoms if g.contains(point)), max(net.geoms, key=lambda g: g.area)
        )
    if net.is_empty:
        return None
    return face, net


def _extended(points: list[tuple[float, float]], reach: float) -> list[tuple[float, float]]:
    """A polyline run ``reach`` past both ends."""

    def past(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
        length = math.dist(a, b) or 1.0
        return (b[0] + (b[0] - a[0]) / length * reach, b[1] + (b[1] - a[1]) / length * reach)

    return (
        [past(points[1], points[0]), *points[1:-1], past(points[-2], points[-1])]
        if len(points) > 2
        else [past(points[1], points[0]), past(points[0], points[1])]
    )


def check(arch: Architecture, floor_plan: Any = None) -> list[str]:
    """Problems with what the architecture refers to in the floor plan, and openings that do not
    fit their walls."""
    problems: list[str] = []
    elevations = {s.id: s.elevation for s in floor_plan.stories} if floor_plan is not None else None
    types = {t.id: t for t in arch.wallTypes}
    walls = {w.id: w for w in arch.walls}
    if elevations is not None:
        members = {m.id for _, m in floor_plan.members()}
        for wall in arch.walls:
            for story in (wall.base, wall.top):
                if story is not None and story not in elevations:
                    problems.append(f"{wall.id}: no story '{story}'")
            if wall_levels(wall, elevations) is None and wall.base in elevations:
                problems.append(f"{wall.id}: no story above to rise to; give its height")
            if wall.structuralRef is not None and wall.structuralRef not in members:
                problems.append(f"{wall.id}: no floor-plan member '{wall.structuralRef}'")
        for item in [*arch.rooms, *arch.separators]:
            if item.story not in elevations:
                problems.append(f"{item.id}: no story '{item.story}'")
        for room in arch.rooms:
            if room.story in elevations and room_boundary(arch, room, elevations) is None:
                problems.append(f"{room.id}: its point is not enclosed by walls or separators")
    for opening in [*arch.doors, *arch.windows]:
        wall = walls[opening.wall]
        length = _length(centre_line(wall, types[wall.type]))
        width = opening_size(arch, opening)[0]
        if opening.offset - width / 2 < -1e-6 or opening.offset + width / 2 > length + 1e-6:
            problems.append(f"{opening.id}: does not fit in wall {wall.id}")
    return problems
