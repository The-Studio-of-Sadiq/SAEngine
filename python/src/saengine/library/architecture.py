"""The architecture (``05 Floor Plan/architecture.json``): walls, doors, windows and rooms,
curtain walls, roofs, ramps and railings.

The architect's layer of the building, drawn on the floor plan's grids and stories: masonry and
partition walls of layered wall types, doors and windows hosted in them, and rooms found from
the walls around a picked point (with room separators where there is no wall). It is physical
only: it never adds stiffness to the analysis. Its loads (the walls' weight, the rooms'
finishes and occupancy live loads) are derived from it when the analysis model is derived
(:mod:`saengine.fem.architecture_loads`), and the bill of quantities measures its brickwork,
plaster, finishes, doors and windows (:mod:`saengine.boq.architecture`).

The extras (track T46) follow the same rules: a curtain wall is a wall of glazing on a mullion
grid (its weight per m² as a type, no panel families); a roof is a covering of layers over a plan
outline, flat or of one pitch (a gable is two roofs); a ramp is a straight built-up ramp on a
floor (a turning ramp is several, with landings); a railing is a guard or handrail along a path,
of a weight per metre. They are physical only too: their weights load what carries them.

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
#: What a ramp serves; the code pack's ramp rules are kept by these ids.
RampKind = Literal["walkway", "accessible", "exit", "vehicle", "parking"]

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


class CurtainWallType(_Model):
    """Glazing on a grid of mullions (vertical) and transoms (horizontal), as one weight per m².

    The weight is the glass's (thickness × unit weight) plus the frame's, per m² of wall; the
    frame's 0.15 kN/m² default is an SAEngine choice for aluminium framing (enter the
    supplier's). BNBC 2020 Part 6 Sec 2.2 takes dead loads as the actual weights of the
    materials; glass's 25 kN/m³ is its usual density (2,500 kg/m³)."""

    id: Id
    name: str = Field(min_length=1)
    glassThickness: Length = Field(
        default=12, title="Glass thickness", description="Of all the panes together [mm]."
    )
    glassUnitWeight: UnitWeight = Field(default=25.0, title="Glass unit weight")
    frameWeight: float = Field(
        default=0.15,
        ge=0,
        title="Frame weight",
        description="Mullions, transoms and fixings per m² of wall [kN/m²].",
    )
    depth: Length = Field(default=150, description="Of the mullions, across the wall [mm].")
    mullionSpacing: Length = Field(
        default=1500, title="Mullion spacing", description="Between vertical mullions [mm]."
    )
    transomSpacing: Length = Field(
        default=1500, title="Transom spacing", description="Between horizontal transoms [mm]."
    )

    @property
    def thickness(self) -> float:
        """Across the wall [mm]: the mullions' depth."""
        return self.depth

    @property
    def locationLine(self) -> str:
        """A curtain wall's path is its centre line."""
        return "center"

    @property
    def weight(self) -> float:
        """Weight per wall area [kN/m²]."""
        return self.glassThickness / 1000 * self.glassUnitWeight + self.frameWeight


class RoofType(_Model):
    """A roof covering: layers over the roof slab or deck, top down (terracing, screed,
    waterproofing, tiles), each a thickness and unit weight."""

    id: Id
    name: str = Field(min_length=1)
    layers: list[WallLayer] = Field(min_length=1)

    @property
    def thickness(self) -> float:
        return sum(layer.thickness for layer in self.layers)

    @property
    def weight(self) -> float:
        """Weight per m² of roof surface (along its slope) [kN/m²]."""
        return sum(layer.thickness / 1000 * layer.unitWeight for layer in self.layers)


class RailingType(_Model):
    """A guard or handrail: its height and weight per metre (posts, rails and infill).

    The 0.3 kN/m default is an SAEngine choice for a steel railing; enter yours."""

    id: Id
    name: str = Field(min_length=1)
    height: Length = Field(default=1000, description="Top of rail above the floor [mm].")
    weight: float = Field(default=0.3, ge=0, description="Per metre run [kN/m].")
    width: Length = Field(default=50, description="Across the railing, drawn [mm].")
    postSpacing: Length = Field(default=1200, title="Post spacing", description="[mm].")

    @property
    def thickness(self) -> float:
        return self.width

    @property
    def locationLine(self) -> str:
        return "center"


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
    component: str | None = Field(
        default=None,
        title="Seismic component",
        description="Its row of the code pack's nonstructural component table (e.g. "
        "exteriorWall, parapetBracedAbove); empty: by its position (a wall with no story above "
        "is a parapet, other walls interior partitions, curtain walls exterior wall elements).",
    )
    essential: bool = Field(
        default=False,
        description="Must function after an earthquake, holds hazardous materials, or is needed "
        "for the continued operation of an essential facility: the code pack's higher component "
        "importance factor.",
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


class CurtainWall(ArchWall):
    """A curtain wall: as a wall (its base, top or height, and path), of a curtain wall type
    (``type``); doors and windows are not hosted in it (its glazing is its own)."""

    type: Id = Field(title="Curtain wall type")


class Roof(_Model):
    """A roof covering over a plan outline on a story (the roof slab's level): flat, or of one
    pitch rising ``slope`` degrees towards ``direction``."""

    id: Id
    type: Id = Field(title="Roof type")
    story: Id = Field(description="The level the roof covers (its slab's story).")
    outline: list[Point2] = Field(min_length=3, description="The roof's plan outline [mm].")
    baseOffset: Mm = Field(default=0, title="Base offset", description="Above the story [mm].")
    slope: float = Field(default=0, ge=0, lt=90, description="Pitch [°] (0: a flat roof).")
    direction: float = Field(
        default=90,
        description="Plan direction it rises towards [°], anticlockwise from x (pitched only).",
    )
    occupancy: str | None = Field(
        default=None,
        description="Area use from the code pack for its live load (e.g. BNBC's roof uses).",
    )


class Ramp(_Model):
    """A straight ramp built up on a floor, from ``start`` (low end) to ``end`` (high end)."""

    id: Id
    story: Id
    start: Point2 = Field(description="Centre of the low end [mm].")
    end: Point2 = Field(description="Centre of the high end [mm].")
    width: Length = Field(default=1500, description="[mm].")
    rise: Mm = Field(default=0, ge=0, description="Height gained from start to end [mm].")
    finish: Id | None = Field(default=None, title="Floor finish")
    fillUnitWeight: UnitWeight = Field(
        default=16.0,
        title="Fill unit weight",
        description="Of the filling under the ramp [kN/m³] (16: brick-bat filling, an SAEngine "
        "choice; 0 for a ramp on its own structure).",
    )
    occupancy: str | None = Field(
        default=None, description="Area use from the code pack, for its live load."
    )
    kind: RampKind = Field(
        default="walkway",
        description="What the ramp serves, for the code pack's ramp checks: walkway (walkers), "
        "accessible (an accessible route for persons with disabilities), exit (a means of "
        "escape), vehicle (a carriageway ramp between levels), parking (stalls along the ramp).",
    )
    lanes: int = Field(default=1, ge=1, le=2, description="Traffic lanes (vehicle ramps).")
    transitions: bool = Field(
        default=False,
        description="Vehicle ramps: transition slopes at both ends (at the share of the main "
        "slope the code pack names), which allow a steeper main slope.",
    )


class Railing(_Model):
    """A railing along a path on a story (a balcony's guard, a stair's or ramp's handrail)."""

    id: Id
    type: Id = Field(title="Railing type")
    base: Id = Field(description="Story it stands on.")
    baseOffset: Mm = Field(default=0, title="Base offset", description="Above the story [mm].")
    path: list[Point2] = Field(min_length=2, description="Along the railing, point by point.")


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
    curtainWallTypes: list[CurtainWallType] = Field(
        default_factory=list, title="Curtain wall types"
    )
    roofTypes: list[RoofType] = Field(default_factory=list, title="Roof types")
    railingTypes: list[RailingType] = Field(default_factory=list, title="Railing types")
    walls: list[ArchWall] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    rooms: list[Room] = Field(default_factory=list)
    separators: list[RoomSeparator] = Field(default_factory=list, title="Room separators")
    curtainWalls: list[CurtainWall] = Field(default_factory=list, title="Curtain walls")
    roofs: list[Roof] = Field(default_factory=list)
    ramps: list[Ramp] = Field(default_factory=list)
    railings: list[Railing] = Field(default_factory=list)
    imports: list[DrawingImport] = Field(
        default_factory=list,
        title="Drawing imports",
        description="Architects' DWG/DXF drawings imported, to import them again.",
    )

    def instances(self) -> list[Any]:
        return [
            *self.walls,
            *self.doors,
            *self.windows,
            *self.rooms,
            *self.separators,
            *self.curtainWalls,
            *self.roofs,
            *self.ramps,
            *self.railings,
        ]

    @model_validator(mode="after")
    def _references(self) -> Architecture:
        for name, items in (
            ("wall type", self.wallTypes),
            ("door type", self.doorTypes),
            ("window type", self.windowTypes),
            ("finish type", self.finishTypes),
            ("curtain wall type", self.curtainWallTypes),
            ("roof type", self.roofTypes),
            ("railing type", self.railingTypes),
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
        curtain_types = {t.id for t in self.curtainWallTypes}
        for curtain in self.curtainWalls:
            if curtain.type not in curtain_types:
                raise ValueError(f"{curtain.id}: no curtain wall type '{curtain.type}'")
            if curtain.top is not None and curtain.height is not None:
                raise ValueError(f"{curtain.id}: give a top story or a height, not both")
            if _length(curtain.path) <= 0:
                raise ValueError(f"{curtain.id}: its path has no length")
        roof_types = {t.id for t in self.roofTypes}
        for roof in self.roofs:
            if roof.type not in roof_types:
                raise ValueError(f"{roof.id}: no roof type '{roof.type}'")
        railing_types = {t.id for t in self.railingTypes}
        for railing in self.railings:
            if railing.type not in railing_types:
                raise ValueError(f"{railing.id}: no railing type '{railing.type}'")
            if _length(railing.path) <= 0:
                raise ValueError(f"{railing.id}: its path has no length")
        for ramp in self.ramps:
            if math.dist(ramp.start, ramp.end) <= 0:
                raise ValueError(f"{ramp.id}: it has no length")
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
        for ramp in self.ramps:
            if ramp.finish is not None and finishes.get(ramp.finish) != "floor":
                raise ValueError(f"{ramp.id}: no floor finish '{ramp.finish}'")
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
            "curtainWallTypes": [
                {"id": "CW1", "name": "Aluminium curtain wall, double glazed"},
            ],
            "roofTypes": [
                {
                    "id": "RF1",
                    "name": "Lime terracing with brick tiles",
                    "layers": [
                        {"material": "Brick tiles", "thickness": 40, "unitWeight": 18.85},
                        {"material": "Lime terracing", "thickness": 75, "unitWeight": 18.85},
                    ],
                },
                {
                    "id": "RF2",
                    "name": "Screed and waterproofing",
                    "layers": [
                        {"material": "Cement screed", "thickness": 40, "unitWeight": 20.4},
                        {"material": "Waterproofing membrane", "thickness": 5, "unitWeight": 12},
                    ],
                },
            ],
            "railingTypes": [
                {"id": "RL1", "name": "Steel railing", "height": 1000, "weight": 0.3},
                {
                    "id": "RL2",
                    "name": "Glass balustrade",
                    "height": 1100,
                    "weight": 0.5,
                    "width": 20,
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


def railing_as_wall(railing: Railing, railing_type: RailingType) -> ArchWall:
    """A railing as a wall of its type's height (its pieces and loads are found as a wall's)."""
    return ArchWall(
        id=railing.id,
        type=railing.type,
        base=railing.base,
        height=railing_type.height,
        baseOffset=railing.baseOffset,
        path=railing.path,
    )


def roof_polygon(roof: Roof) -> Any:
    """The roof's plan outline (shapely, mm), made valid."""
    from shapely.geometry import Polygon

    polygon = Polygon(roof.outline)
    return polygon if polygon.is_valid else polygon.buffer(0)


def roof_area(roof: Roof) -> tuple[float, float]:
    """The roof's plan area and its surface along the slope [mm²]."""
    plan = roof_polygon(roof).area
    return plan, plan / math.cos(math.radians(roof.slope))


def ramp_length(ramp: Ramp) -> float:
    """Along the slope [mm]."""
    return math.hypot(math.dist(ramp.start, ramp.end), ramp.rise)


def ramp_gradient(ramp: Ramp) -> float:
    """Rise over run (0.0833 is 1 in 12)."""
    run = math.dist(ramp.start, ramp.end)
    return ramp.rise / run if run else 0.0


def ramp_polygon(ramp: Ramp) -> Any:
    """The ramp's plan footprint (shapely, mm): its centre line widened to both sides."""
    from shapely.geometry import LineString

    return LineString([ramp.start, ramp.end]).buffer(ramp.width / 2, cap_style="flat")


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
    arch: Architecture, story: str, elevations: dict[str, float], curtain: bool = False
) -> list[tuple[ArchWall, Any]]:
    """The walls standing on ``story`` or rising through it (with ``curtain``, the curtain walls
    too, with their curtain wall types)."""
    if story not in elevations:
        return []
    level = elevations[story]
    wall_types: dict[str, Any] = {t.id: t for t in arch.wallTypes}
    curtain_types: dict[str, Any] = {t.id: t for t in arch.curtainWallTypes}
    candidates: list[tuple[ArchWall, dict[str, Any]]] = [(w, wall_types) for w in arch.walls]
    if curtain:
        candidates += [(c, curtain_types) for c in arch.curtainWalls]
    result = []
    for wall, types in candidates:
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

    # Curtain walls bound rooms as walls do (a glazed facade closes the rooms behind it).
    walls = walls_on_story(arch, room.story, elevations, curtain=True)
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
        for curtain in arch.curtainWalls:
            for story in (curtain.base, curtain.top):
                if story is not None and story not in elevations:
                    problems.append(f"{curtain.id}: no story '{story}'")
            if wall_levels(curtain, elevations) is None and curtain.base in elevations:
                problems.append(f"{curtain.id}: no story above to rise to; give its height")
        for item in [*arch.roofs, *arch.ramps]:
            if item.story not in elevations:
                problems.append(f"{item.id}: no story '{item.story}'")
        for railing in arch.railings:
            if railing.base not in elevations:
                problems.append(f"{railing.id}: no story '{railing.base}'")
    for roof in arch.roofs:
        if roof_polygon(roof).area <= 0:
            problems.append(f"{roof.id}: its outline has no area")
    for opening in [*arch.doors, *arch.windows]:
        wall = walls[opening.wall]
        length = _length(centre_line(wall, types[wall.type]))
        width = opening_size(arch, opening)[0]
        if opening.offset - width / 2 < -1e-6 or opening.offset + width / 2 > length + 1e-6:
            problems.append(f"{opening.id}: does not fit in wall {wall.id}")
    return problems
