"""The architecture (``05 Floor Plan/architecture.json``): walls, doors, windows and rooms,
curtain walls, roofs, ceilings, ramps and railings.

The architect's layer of the building, drawn on the floor plan's grids and stories: masonry and
partition walls of layered wall types, doors and windows hosted in them, and rooms found from
the walls around a picked point (with room separators where there is no wall). It is physical
only: it never adds stiffness to the analysis. Its loads (the walls' weight, the rooms'
finishes and occupancy live loads) are derived from it when the analysis model is derived
(:mod:`saengine.fem.architecture_loads`), and the bill of quantities measures its brickwork,
plaster, finishes, doors, windows, roofs, ceilings and curtain walls
(:mod:`saengine.boq.architecture`).

Curtain walls carry grid layout rules (fixed distance, fixed number, max spacing), panel types
(glazed, solid, door) with per-panel overrides, and mullion types; footprint roofs support
per-edge slopes (hip, gable, shed, mansard, flat with drainage slope) via a straight skeleton
with overhangs; ceilings track type, height above level, grid patterns, openings and the
ceiling void depth under the structure above. They are physical only too: their weights load
what carries them.

Kept simple on purpose (no Revit clone): door and window types are fixed parametric styles (no
family editor), a wall is one type over its height (no stacked walls), and there are no
worksets.

Units: mm for coordinates, lengths and levels; kN/m³ for unit weights. Plan coordinates are
global (the floor plan's); a story is a floor-plan story id. A wall's ``path`` is its location
line (the wall type's); a door's or window's ``offset`` is the distance along the wall's centre
line from its start to the opening's centre.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.components import ComponentInstance, ComponentType, starter_component_types
from saengine.library.labels import field_title
from saengine.library.massing import ConceptualMass, InPlaceElement
from saengine.library.materials import Id

if TYPE_CHECKING:
    from saengine.library.roof_geometry import RoofGeometry

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
    leafCount: int | None = Field(
        default=None, ge=1, le=4, title="Leaf count", description="Number of door leaves/panels."
    )
    swing: Literal["left", "right", "both", "none"] | None = Field(
        default=None,
        title="Swing",
        description="Hinge side or swing direction (left, right, both for double, none for sliding).",
    )
    sill: Mm = Field(default=0, ge=0, description="Threshold/sill height above floor [mm].")
    lintel: Length | None = Field(
        default=None, description="Optional lintel depth above the door [mm]."
    )

    @property
    def resolved_leaf_count(self) -> int:
        if self.leafCount is not None:
            return self.leafCount
        return 2 if self.style in ("double", "sliding") else 1

    @property
    def resolved_swing(self) -> str:
        if self.swing is not None:
            return self.swing
        return {"single": "left", "double": "both", "sliding": "none"}[self.style]


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
    leafCount: int | None = Field(
        default=None, ge=1, le=6, title="Leaf count", description="Number of sashes/panels."
    )
    swing: Literal["inward", "outward", "left", "right", "none"] | None = Field(
        default=None,
        title="Swing",
        description="Opening direction (inward, outward, left, right, or none for fixed).",
    )
    lintel: Length | None = Field(
        default=None, description="Optional lintel depth above the window [mm]."
    )

    @property
    def resolved_leaf_count(self) -> int:
        if self.leafCount is not None:
            return self.leafCount
        return 2 if self.style == "sliding" else 1

    @property
    def resolved_swing(self) -> str:
        if self.swing is not None:
            return self.swing
        return {"fixed": "none", "casement": "outward", "sliding": "none"}[self.style]


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


GridLayout = Literal["fixedDistance", "fixedNumber", "maxSpacing", "none"]
PanelKind = Literal["glazed", "solid", "door"]
CeilingKind = Literal["gypsum", "grid", "plaster", "timber", "metal", "other"]


class CurtainGridRule(_Model):
    """Rule dividing a curtain wall along its length or height."""

    layout: GridLayout = Field(
        default="fixedDistance",
        description="How grid divisions are placed: fixedDistance, fixedNumber, maxSpacing, or none.",
    )
    spacing: Length | None = Field(
        default=None,
        description="Target or maximum spacing [mm] (for fixedDistance and maxSpacing).",
    )
    count: int | None = Field(
        default=None,
        ge=0,
        description="Number of interior grid lines (for fixedNumber; 2 lines give 3 divisions).",
    )

    @model_validator(mode="after")
    def _validate_rule(self) -> CurtainGridRule:
        if self.layout in ("fixedDistance", "maxSpacing") and self.spacing is None:
            raise ValueError(f"curtain grid layout '{self.layout}' requires spacing")
        if self.layout == "fixedNumber" and self.count is None:
            raise ValueError("curtain grid layout 'fixedNumber' requires count")
        return self


class CurtainPanelType(_Model):
    """A curtain wall infill panel type (glazed, solid spandrel/cladding, or door panel)."""

    id: Id
    name: str = Field(min_length=1)
    kind: PanelKind = Field(default="glazed")
    material: str = Field(default="Glass", min_length=1)
    thickness: Length = Field(default=12, description="Panel thickness [mm].")
    unitWeight: UnitWeight | None = Field(
        default=None,
        title="Unit weight",
        description="Material unit weight [kN/m³] (used when weight is not given).",
    )
    weight: float | None = Field(
        default=None,
        ge=0,
        description="Explicit panel weight per m² [kN/m²] (overrides thickness × unitWeight).",
    )

    @property
    def area_weight(self) -> float:
        """Weight per m² of panel [kN/m²]."""
        if self.weight is not None:
            return self.weight
        density = self.unitWeight if self.unitWeight is not None else (25.0 if self.kind == "glazed" else 20.0)
        return self.thickness / 1000 * density


class CurtainMullionType(_Model):
    """A curtain wall vertical mullion or horizontal transom profile."""

    id: Id
    name: str = Field(min_length=1)
    width: Length = Field(default=50, description="Face width along the wall [mm].")
    depth: Length = Field(default=150, description="Profile depth across the wall [mm].")
    wallThickness: Length | None = Field(
        default=None,
        title="Wall thickness",
        description="Hollow extrusion wall thickness [mm] (omit for solid or explicit weight).",
    )
    material: str = Field(default="Aluminium", min_length=1)
    unitWeight: UnitWeight = Field(default=27.0, title="Unit weight")
    weightPerMetre: float | None = Field(
        default=None,
        ge=0,
        title="Weight per metre",
        description="Explicit weight per metre run [kN/m] (overrides profile section × unit weight).",
    )

    @property
    def linear_weight(self) -> float:
        """Weight per metre run [kN/m]."""
        if self.weightPerMetre is not None:
            return self.weightPerMetre
        if self.wallThickness is not None and 2 * self.wallThickness < min(self.width, self.depth):
            area_mm2 = self.width * self.depth - (self.width - 2 * self.wallThickness) * (
                self.depth - 2 * self.wallThickness
            )
        else:
            area_mm2 = self.width * self.depth
        return area_mm2 / 1e6 * self.unitWeight


class CurtainWallType(_Model):
    """Glazing on a grid of mullions (vertical) and transoms (horizontal).

    Supports either a simple weight per m² (``glassThickness × glassUnitWeight + frameWeight``)
    or explicit grid rules, panel types and mullion profile types (panels + mullions weights).
    """

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
    verticalGrid: CurtainGridRule | None = Field(
        default=None,
        title="Vertical grid",
        description="Rule dividing the curtain wall along its length into panel columns.",
    )
    horizontalGrid: CurtainGridRule | None = Field(
        default=None,
        title="Horizontal grid",
        description="Rule dividing the curtain wall up its height into panel rows.",
    )
    panelType: Id | None = Field(
        default=None,
        title="Default panel type",
        description="Default curtain panel type id from curtainPanelTypes.",
    )
    verticalMullion: Id | None = Field(
        default=None,
        title="Vertical mullion type",
        description="Mullion type id for vertical grid mullions.",
    )
    horizontalMullion: Id | None = Field(
        default=None,
        title="Horizontal mullion type",
        description="Mullion type id for horizontal transoms.",
    )
    borderMullion: Id | None = Field(
        default=None,
        title="Border mullion type",
        description="Optional mullion type id for perimeter mullions.",
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
        """Nominal weight per wall area [kN/m²] when panel/mullion types are not set."""
        return self.glassThickness / 1000 * self.glassUnitWeight + self.frameWeight


class CeilingType(_Model):
    """A false/suspended or applied ceiling type (gypsum board, grid tiles, plaster, etc.)."""

    id: Id
    name: str = Field(min_length=1)
    kind: CeilingKind = Field(default="gypsum")
    thickness: Length = Field(default=12.5, description="Ceiling board or tile thickness [mm].")
    weight: float = Field(default=0.15, ge=0, description="Weight per m² [kN/m²].")
    gridX: Length | None = Field(
        default=None, title="Grid X", description="Tile grid module along X [mm] (e.g. 600)."
    )
    gridY: Length | None = Field(
        default=None, title="Grid Y", description="Tile grid module along Y [mm] (e.g. 600)."
    )


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
        default=None,
        description="Area use from the code pack (e.g. the default pack's), for its loads.",
    )
    floorFinish: Id | None = Field(default=None, title="Floor finish")
    wallFinish: Id | None = Field(default=None, title="Wall finish")
    ceilingFinish: Id | None = Field(default=None, title="Ceiling finish")
    wet: bool = Field(default=False, description="Toilet, kitchen or other wet area.")


class CurtainPanelOverride(_Model):
    """Override the infill panel type at a specific grid cell of a curtain wall."""

    segment: int = Field(default=0, ge=0, description="0-based path segment index.")
    column: int = Field(ge=0, description="0-based column index along the segment.")
    row: int = Field(ge=0, description="0-based row index from the bottom up.")
    panelType: Id = Field(title="Panel type")


class CurtainWall(ArchWall):
    """A curtain wall: as a wall (its base, top or height, and path), of a curtain wall type
    (``type``); doors and windows are not hosted in it (its glazing is its own)."""

    type: Id = Field(title="Curtain wall type")
    panelOverrides: list[CurtainPanelOverride] = Field(
        default_factory=list,
        title="Panel overrides",
        description="Per-panel overrides by (segment, column, row).",
    )


class Roof(_Model):
    """A roof over a plan outline on a story: flat, drainage-sloped, single-pitch, or a
    footprint roof with per-edge slopes (hip, gable, shed, mansard) and overhangs."""

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
        description="Area use from the code pack for its live load (e.g. the default pack's roof uses).",
    )
    edgeSlopes: list[float | None] | None = Field(
        default=None,
        title="Edge slopes",
        description="Slope [°] per outline edge (0 or null: non-sloping gable edge).",
    )
    overhang: Mm = Field(
        default=0,
        ge=0,
        description="Uniform horizontal eaves overhang outside the outline [mm].",
    )
    edgeOverhangs: list[Mm] | None = Field(
        default=None,
        title="Edge overhangs",
        description="Per-edge horizontal eaves overhang [mm] (overrides overhang).",
    )
    upperSlope: float | None = Field(
        default=None,
        ge=0,
        lt=90,
        title="Upper slope",
        description="Second (upper) slope [°] above breakHeight for a mansard roof.",
    )
    breakHeight: Length | None = Field(
        default=None,
        title="Break height",
        description="Height above eaves [mm] where a mansard roof changes to upperSlope.",
    )
    drainageSlope: float = Field(
        default=0,
        ge=0,
        lt=45,
        title="Drainage slope",
        description="Small fall [°] on a flat roof towards direction.",
    )
    thickness: Length | None = Field(
        default=None,
        description="Optional thickness override [mm] (defaults to the roof type's thickness).",
    )

    @model_validator(mode="after")
    def _validate_roof(self) -> Roof:
        n = (
            len(self.outline) - 1
            if len(self.outline) > 3 and math.dist(self.outline[0], self.outline[-1]) < 1e-6
            else len(self.outline)
        )
        if self.edgeSlopes is not None:
            if len(self.edgeSlopes) != n:
                raise ValueError(
                    f"{self.id}: edgeSlopes length ({len(self.edgeSlopes)}) must match outline edges ({n})"
                )
            for s in self.edgeSlopes:
                if s is not None and not (0.0 <= s < 90.0):
                    raise ValueError(f"{self.id}: edge slope {s} must be in [0, 90)")
        if self.edgeOverhangs is not None:
            if len(self.edgeOverhangs) != n:
                raise ValueError(
                    f"{self.id}: edgeOverhangs length ({len(self.edgeOverhangs)}) must match outline edges ({n})"
                )
            for oh in self.edgeOverhangs:
                if oh < 0:
                    raise ValueError(f"{self.id}: edge overhang {oh} must be >= 0")
        if self.upperSlope is not None and self.breakHeight is None:
            raise ValueError(f"{self.id}: upperSlope requires breakHeight")
        return self


class CeilingOpening(_Model):
    """An opening cut into a ceiling (e.g. for an access hatch, atrium or shaft)."""

    id: Id | None = None
    outline: list[Point2] = Field(min_length=3, description="Opening boundary [mm].")


class Ceiling(_Model):
    """A ceiling element hosted in a room or drawn by a closed plan outline at ``height`` above
    its story's level."""

    id: Id
    type: Id = Field(title="Ceiling type")
    story: Id = Field(description="Story the ceiling belongs to.")
    height: Length = Field(
        default=2700,
        description="Clear height of the ceiling soffit above the story level [mm].",
    )
    room: Id | None = Field(default=None, description="Host room id (instead of outline).")
    outline: list[Point2] | None = Field(
        default=None, min_length=3, description="Plan outline [mm] (instead of room)."
    )
    gridRotation: float = Field(default=0, title="Grid rotation", description="Tile grid angle [°].")
    gridOrigin: Point2 | None = Field(
        default=None, title="Grid origin", description="Optional origin point for tile grid [mm]."
    )
    openings: list[CeilingOpening] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_boundary(self) -> Ceiling:
        if (self.room is None) == (self.outline is None):
            raise ValueError(f"{self.id}: give either a room or an outline, not both")
        return self


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
    curtainPanelTypes: list[CurtainPanelType] = Field(
        default_factory=list, title="Curtain panel types"
    )
    curtainMullionTypes: list[CurtainMullionType] = Field(
        default_factory=list, title="Curtain mullion types"
    )
    ceilingTypes: list[CeilingType] = Field(default_factory=list, title="Ceiling types")
    roofTypes: list[RoofType] = Field(default_factory=list, title="Roof types")
    railingTypes: list[RailingType] = Field(default_factory=list, title="Railing types")
    componentTypes: list[ComponentType] = Field(
        default_factory=list, title="Component types"
    )
    walls: list[ArchWall] = Field(default_factory=list)
    doors: list[Door] = Field(default_factory=list)
    windows: list[Window] = Field(default_factory=list)
    rooms: list[Room] = Field(default_factory=list)
    separators: list[RoomSeparator] = Field(default_factory=list, title="Room separators")
    curtainWalls: list[CurtainWall] = Field(default_factory=list, title="Curtain walls")
    ceilings: list[Ceiling] = Field(default_factory=list)
    roofs: list[Roof] = Field(default_factory=list)
    ramps: list[Ramp] = Field(default_factory=list)
    railings: list[Railing] = Field(default_factory=list)
    components: list[ComponentInstance] = Field(default_factory=list)
    masses: list[ConceptualMass] = Field(default_factory=list)
    inPlaceElements: list[InPlaceElement] = Field(
        default_factory=list, title="In-place elements"
    )
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
            *self.ceilings,
            *self.roofs,
            *self.ramps,
            *self.railings,
            *self.components,
            *self.masses,
            *self.inPlaceElements,
        ]

    @model_validator(mode="after")
    def _references(self) -> Architecture:
        for name, items in (
            ("wall type", self.wallTypes),
            ("door type", self.doorTypes),
            ("window type", self.windowTypes),
            ("finish type", self.finishTypes),
            ("curtain wall type", self.curtainWallTypes),
            ("curtain panel type", self.curtainPanelTypes),
            ("curtain mullion type", self.curtainMullionTypes),
            ("ceiling type", self.ceilingTypes),
            ("roof type", self.roofTypes),
            ("railing type", self.railingTypes),
            ("component type", self.componentTypes),
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
        panel_types = {t.id for t in self.curtainPanelTypes}
        mullion_types = {t.id for t in self.curtainMullionTypes}
        for cw_type in self.curtainWallTypes:
            if cw_type.panelType is not None and cw_type.panelType not in panel_types:
                raise ValueError(f"{cw_type.id}: no curtain panel type '{cw_type.panelType}'")
            for m_field in ("verticalMullion", "horizontalMullion", "borderMullion"):
                m_id = getattr(cw_type, m_field)
                if m_id is not None and m_id not in mullion_types:
                    raise ValueError(f"{cw_type.id}: no curtain mullion type '{m_id}'")
        curtain_types = {t.id for t in self.curtainWallTypes}
        for curtain in self.curtainWalls:
            if curtain.type not in curtain_types:
                raise ValueError(f"{curtain.id}: no curtain wall type '{curtain.type}'")
            if curtain.top is not None and curtain.height is not None:
                raise ValueError(f"{curtain.id}: give a top story or a height, not both")
            if _length(curtain.path) <= 0:
                raise ValueError(f"{curtain.id}: its path has no length")
            for ov in curtain.panelOverrides:
                if ov.panelType not in panel_types:
                    raise ValueError(f"{curtain.id}: no curtain panel type '{ov.panelType}'")
        ceiling_types = {t.id for t in self.ceilingTypes}
        room_ids = {r.id for r in self.rooms}
        for ceiling in self.ceilings:
            if ceiling.type not in ceiling_types:
                raise ValueError(f"{ceiling.id}: no ceiling type '{ceiling.type}'")
            if ceiling.room is not None and ceiling.room not in room_ids:
                raise ValueError(f"{ceiling.id}: no room '{ceiling.room}'")
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
        component_types = {t.id for t in self.componentTypes}
        for comp in self.components:
            if comp.type not in component_types:
                raise ValueError(f"{comp.id}: no component type '{comp.type}'")
            if comp.hostRoom is not None and comp.hostRoom not in room_ids:
                raise ValueError(f"{comp.id}: no host room '{comp.hostRoom}'")
        for elem in self.inPlaceElements:
            if elem.hostRoom is not None and elem.hostRoom not in room_ids:
                raise ValueError(f"{elem.id}: no host room '{elem.hostRoom}'")
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
            "curtainPanelTypes": [
                {
                    "id": "CP-GLZ",
                    "name": "Double glazed unit 24 mm",
                    "kind": "glazed",
                    "material": "Glass",
                    "thickness": 12,
                    "unitWeight": 25.0,
                },
                {
                    "id": "CP-SOL",
                    "name": "Insulated aluminium spandrel panel",
                    "kind": "solid",
                    "material": "Spandrel",
                    "thickness": 25,
                    "unitWeight": 20.0,
                },
                {
                    "id": "CP-DOOR",
                    "name": "Curtain wall glazed door leaf",
                    "kind": "door",
                    "material": "Glass + Aluminium",
                    "thickness": 45,
                    "weight": 0.45,
                },
            ],
            "curtainMullionTypes": [
                {
                    "id": "CM-50x150",
                    "name": "Aluminium mullion 50x150 mm",
                    "width": 50,
                    "depth": 150,
                    "wallThickness": 3,
                    "material": "Aluminium",
                    "unitWeight": 27.0,
                },
                {
                    "id": "CM-50x100",
                    "name": "Aluminium transom 50x100 mm",
                    "width": 50,
                    "depth": 100,
                    "wallThickness": 3,
                    "material": "Aluminium",
                    "unitWeight": 27.0,
                },
            ],
            "ceilingTypes": [
                {
                    "id": "CL1",
                    "name": "Gypsum board ceiling 12.5 mm",
                    "kind": "gypsum",
                    "thickness": 12.5,
                    "weight": 0.15,
                },
                {
                    "id": "CL2",
                    "name": "Acoustic grid ceiling 600x600 mm",
                    "kind": "grid",
                    "thickness": 15,
                    "weight": 0.12,
                    "gridX": 600,
                    "gridY": 600,
                },
                {
                    "id": "CL3",
                    "name": "Acoustic grid ceiling 600x1200 mm",
                    "kind": "grid",
                    "thickness": 15,
                    "weight": 0.12,
                    "gridX": 600,
                    "gridY": 1200,
                },
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
            "componentTypes": [
                t.model_dump(mode="json", by_alias=True, exclude_none=True)
                for t in starter_component_types()
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


def roof_geometry(roof: Roof) -> RoofGeometry:
    """The roof's 3D faces, ridge/hip/valley/eaves lines, and plan/sloped areas."""
    from saengine.library.roof_geometry import compute_roof_geometry

    return compute_roof_geometry(roof)


def roof_polygon(roof: Roof) -> Any:
    """The roof's outer plan outline including overhangs (shapely, mm), made valid."""
    from shapely.geometry import Polygon

    from saengine.library.roof_geometry import effective_outline

    polygon = Polygon(effective_outline(roof))
    return polygon if polygon.is_valid else polygon.buffer(0)


def roof_area(roof: Roof) -> tuple[float, float]:
    """The roof's plan area and its surface area along the slope [mm²]."""
    geom = roof_geometry(roof)
    return geom.plan_area, geom.sloped_area


# ───────────────────────────── ceilings & void ─────────────────────────────


def ceiling_polygon(arch: Architecture, ceiling: Ceiling, elevations: dict[str, float]) -> Any | None:
    """The ceiling's net horizontal polygon [mm] (room net floor or outline, less openings)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    base: Any = None
    if ceiling.room is not None:
        room = next((r for r in arch.rooms if r.id == ceiling.room), None)
        if room is None:
            return None
        found = room_boundary(arch, room, elevations)
        if found is None:
            return None
        base = found[1]
    elif ceiling.outline is not None:
        poly = Polygon(ceiling.outline)
        base = poly if poly.is_valid else poly.buffer(0)
    if base is None or base.is_empty or base.area <= 0:
        return None
    if ceiling.openings:
        cuts = []
        for op in ceiling.openings:
            op_poly = Polygon(op.outline)
            if not op_poly.is_valid:
                op_poly = op_poly.buffer(0)
            if not op_poly.is_empty and op_poly.area > 0:
                cuts.append(op_poly)
        if cuts:
            base = base.difference(unary_union(cuts))
    return None if base.is_empty or base.area <= 0 else base


def ceiling_area(arch: Architecture, ceiling: Ceiling, elevations: dict[str, float]) -> float:
    """The ceiling's net plan area [mm²]."""
    poly = ceiling_polygon(arch, ceiling, elevations)
    return float(poly.area) if poly is not None else 0.0


def ceiling_grid_lines(
    polygon: Any,
    grid_x: float,
    grid_y: float,
    rotation: float = 0.0,
    origin: tuple[float, float] | None = None,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Clipped ceiling grid lines inside ``polygon`` at spacing ``(grid_x, grid_y)`` [mm]."""
    from shapely.geometry import LineString

    if polygon is None or polygon.is_empty or grid_x <= 0 or grid_y <= 0:
        return []
    ox, oy = origin if origin is not None else (polygon.bounds[0], polygon.bounds[1])
    rad = math.radians(rotation)
    ux, uy = math.cos(rad), math.sin(rad)
    vx, vy = -uy, ux
    minx, miny, maxx, maxy = polygon.bounds
    corners = [(minx - ox, miny - oy), (maxx - ox, miny - oy), (maxx - ox, maxy - oy), (minx - ox, maxy - oy)]
    u_vals = [dx * ux + dy * uy for dx, dy in corners]
    v_vals = [dx * vx + dy * vy for dx, dy in corners]
    u_min, u_max = min(u_vals), max(u_vals)
    v_min, v_max = min(v_vals), max(v_vals)

    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []

    def add_clipped(geom: Any) -> None:
        if geom.is_empty:
            return
        if geom.geom_type == "LineString":
            coords = list(geom.coords)
            if len(coords) >= 2 and math.dist(coords[0], coords[-1]) > 1e-3:
                segments.append(((float(coords[0][0]), float(coords[0][1])), (float(coords[-1][0]), float(coords[-1][1]))))
        elif hasattr(geom, "geoms"):
            for part in geom.geoms:
                add_clipped(part)

    k0 = math.ceil(u_min / grid_x - 1e-9)
    k1 = math.floor(u_max / grid_x + 1e-9)
    for k in range(k0, min(k1 + 1, k0 + 500)):
        u = k * grid_x
        p0 = (ox + u * ux + (v_min - 10) * vx, oy + u * uy + (v_min - 10) * vy)
        p1 = (ox + u * ux + (v_max + 10) * vx, oy + u * uy + (v_max + 10) * vy)
        add_clipped(polygon.intersection(LineString([p0, p1])))

    j0 = math.ceil(v_min / grid_y - 1e-9)
    j1 = math.floor(v_max / grid_y + 1e-9)
    for j in range(j0, min(j1 + 1, j0 + 500)):
        v = j * grid_y
        p0 = (ox + (u_min - 10) * ux + v * vx, oy + (u_min - 10) * uy + v * vy)
        p1 = (ox + (u_max + 10) * ux + v * vx, oy + (u_max + 10) * uy + v * vy)
        add_clipped(polygon.intersection(LineString([p0, p1])))

    return segments


@dataclass(frozen=True)
class CeilingVoidCheck:
    """Clearance above a ceiling to the structural soffit (slab and beams) above [mm]."""

    ceiling_id: str
    story: str
    room_id: str | None
    ceiling_height: float
    structure_soffit: float
    void_depth: float
    beam_soffit: float | None = None
    void_under_beams: float | None = None

    def fits(self, service_depth: float, clearance: float = 0.0, under_beams: bool = False) -> bool:
        """Whether a duct or tray of ``service_depth`` (+ ``clearance``) fits in the void."""
        available = (
            self.void_under_beams
            if under_beams and self.void_under_beams is not None
            else self.void_depth
        )
        return available >= service_depth + clearance - 1e-6

    def margin(self, service_depth: float, clearance: float = 0.0, under_beams: bool = False) -> float:
        """Remaining headroom [mm] (negative when the service clashes with the ceiling)."""
        available = (
            self.void_under_beams
            if under_beams and self.void_under_beams is not None
            else self.void_depth
        )
        return available - (service_depth + clearance)

    def check_service(
        self,
        service_depth: float,
        clearance: float = 0.0,
        name: str = "service",
        under_beams: bool = False,
    ) -> dict[str, Any]:
        """Structured void check result for MEP coordination."""
        avail = (
            self.void_under_beams
            if under_beams and self.void_under_beams is not None
            else self.void_depth
        )
        gap = self.margin(service_depth, clearance, under_beams=under_beams)
        return {
            "ceiling": self.ceiling_id,
            "story": self.story,
            "room": self.room_id,
            "service": name,
            "serviceDepth": round(service_depth, 1),
            "clearance": round(clearance, 1),
            "voidDepth": round(avail, 1),
            "slabVoidDepth": round(self.void_depth, 1),
            "beamVoidDepth": round(self.void_under_beams, 1)
            if self.void_under_beams is not None
            else None,
            "margin": round(gap, 1),
            "ok": gap >= -1e-6,
        }


def _element_depth(profile: Any) -> float:
    for attr in ("yDim", "overallDepth", "depth"):
        val = getattr(profile, attr, None)
        if val:
            return float(val)
    rad = getattr(profile, "radius", None)
    return 2.0 * float(rad) if rad else 0.0


def _element_width(profile: Any) -> float:
    for attr in ("xDim", "overallWidth", "width"):
        val = getattr(profile, attr, None)
        if val:
            return float(val)
    rad = getattr(profile, "radius", None)
    return 2.0 * float(rad) if rad else 0.0


def ceiling_void_check(
    arch: Architecture,
    building: Any,
    objects: Any,
    target: Room | str | tuple[float, float] | list[float],
    story: str | None = None,
) -> CeilingVoidCheck | None:
    """Compute the ceiling void check object for ``target`` (a Room, room/ceiling id, or [x, y] point).

    ``void_depth = (next_story_elevation - slab_thickness - story_elevation) - ceiling.height``.
    Returns ``None`` when there is no ceiling or no structural floor level above.
    """
    from shapely.geometry import LineString, Point, Polygon

    from saengine.library.bim import BeamElement, SlabElement

    elevations = {s.id: float(s.elevation) for s in building.stories}
    types = {t.id: t for t in getattr(objects, "objects", [])}

    room_obj: Room | None = None
    ceiling: Ceiling | None = None
    query_pt: Point | None = None

    if isinstance(target, Room):
        room_obj = target
        story = room_obj.story
        query_pt = Point(room_obj.point)
    elif isinstance(target, str):
        room_obj = next((r for r in arch.rooms if r.id == target), None)
        if room_obj is not None:
            story = room_obj.story
            query_pt = Point(room_obj.point)
        else:
            ceiling = next((c for c in arch.ceilings if c.id == target), None)
            if ceiling is not None:
                story = ceiling.story
                if ceiling.room:
                    room_obj = next((r for r in arch.rooms if r.id == ceiling.room), None)
                    if room_obj is not None:
                        query_pt = Point(room_obj.point)
    else:
        query_pt = Point(float(target[0]), float(target[1]))

    if ceiling is None and room_obj is not None:
        ceiling = next((c for c in arch.ceilings if c.room == room_obj.id), None)
    if ceiling is None and query_pt is not None:
        for cand in arch.ceilings:
            if story is not None and cand.story != story:
                continue
            poly = ceiling_polygon(arch, cand, elevations)
            if poly is not None and poly.buffer(1.0).covers(query_pt):
                ceiling = cand
                story = cand.story
                if cand.room and room_obj is None:
                    room_obj = next((r for r in arch.rooms if r.id == cand.room), None)
                break
    if ceiling is None or ceiling.story not in elevations:
        return None

    poly = ceiling_polygon(arch, ceiling, elevations)
    if query_pt is None:
        if poly is None:
            return None
        query_pt = poly.representative_point()

    z_floor = elevations[ceiling.story]
    above = sorted(z for z in elevations.values() if z > z_floor + 1.0)
    if not above:
        return None
    z_above = above[0]

    slab_thickness = 0.0
    for el in building.elements:
        if isinstance(el, SlabElement) and abs(float(el.elevation) - z_above) < 1.0:
            slab_poly = Polygon(el.boundary)
            if slab_poly.buffer(1.0).covers(query_pt):
                t = float(getattr(types.get(el.type), "thickness", 0.0) or 0.0)
                slab_thickness = max(slab_thickness, t)

    structure_soffit = (z_above - slab_thickness) - z_floor
    void_depth = structure_soffit - float(ceiling.height)

    beam_depths: list[float] = []
    inner_zone = poly.buffer(-1.0) if poly is not None and poly.area > 100.0 else None
    for el in building.elements:
        if isinstance(el, BeamElement) and abs(float(el.elevation) - z_above) < 1.0:
            prof = getattr(types.get(el.type), "profile", None)
            depth = _element_depth(prof)
            if depth <= 0:
                continue
            width = _element_width(prof)
            line = LineString([el.start, el.end])
            if isinstance(target, (tuple, list)):
                if line.buffer(max(width / 2, 1.0)).covers(query_pt):
                    beam_depths.append(depth)
            elif inner_zone is not None and not inner_zone.is_empty:
                if line.intersection(inner_zone).length > 1.0:
                    beam_depths.append(depth)
            elif line.buffer(max(width / 2, 1.0)).covers(query_pt):
                beam_depths.append(depth)

    beam_soffit = (z_above - max(beam_depths) - z_floor) if beam_depths else None
    void_under_beams = (beam_soffit - float(ceiling.height)) if beam_soffit is not None else None
    return CeilingVoidCheck(
        ceiling_id=ceiling.id,
        story=ceiling.story,
        room_id=room_obj.id if room_obj is not None else ceiling.room,
        ceiling_height=float(ceiling.height),
        structure_soffit=structure_soffit,
        void_depth=void_depth,
        beam_soffit=beam_soffit,
        void_under_beams=void_under_beams,
    )


def ceiling_void(
    arch: Architecture,
    building: Any,
    objects: Any,
    target: Room | str | tuple[float, float] | list[float],
    story: str | None = None,
) -> float | None:
    """Clear ceiling void depth [mm] (structure soffit above minus ceiling height) for a room,
    ceiling id, or plan point ``[x, y]``."""
    check_obj = ceiling_void_check(arch, building, objects, target, story=story)
    return check_obj.void_depth if check_obj is not None else None


# ───────────────────────────── curtain wall grid ─────────────────────────────


def grid_divisions(
    length: float, rule: CurtainGridRule | None, fallback_spacing: float = 1500.0
) -> list[float]:
    """Grid division coordinates along ``[0, length]`` [mm] for a curtain grid rule."""
    if length <= 0:
        return [0.0]
    if rule is None:
        layout: GridLayout = "fixedDistance"
        spacing: float | None = fallback_spacing
        count: int | None = None
    else:
        layout, spacing, count = rule.layout, rule.spacing, rule.count

    if layout == "none":
        return [0.0, float(length)]
    if layout == "fixedNumber":
        n_divs = max(1, (count or 0) + 1)
        return [float(length) * k / n_divs for k in range(n_divs + 1)]
    if layout == "maxSpacing":
        step = spacing or fallback_spacing
        n_divs = max(1, math.ceil((length - 1e-6) / step))
        return [float(length) * k / n_divs for k in range(n_divs + 1)]
    # fixedDistance
    step = spacing or fallback_spacing
    pts = [0.0]
    pos = step
    while pos < length - 1e-6:
        pts.append(float(pos))
        pos += step
    pts.append(float(length))
    return pts


@dataclass(frozen=True)
class CurtainPanel:
    """One rectangular panel cell of a curtain wall."""

    segment: int
    column: int
    row: int
    panel_type_id: str
    kind: PanelKind
    material: str
    thickness: float
    area_weight: float
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    width: float
    height: float
    direction: tuple[float, float]

    @property
    def weight(self) -> float:
        """Total panel weight [kN]."""
        return (self.width / 1000.0) * (self.height / 1000.0) * self.area_weight


@dataclass(frozen=True)
class CurtainMullion:
    """One vertical mullion or horizontal transom member of a curtain wall."""

    orientation: Literal["vertical", "horizontal"]
    segment: int
    index: int
    mullion_type_id: str
    material: str
    width: float
    depth: float
    linear_weight: float
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    direction: tuple[float, float]
    length: float

    @property
    def weight(self) -> float:
        """Total mullion weight [kN]."""
        return (self.length / 1000.0) * self.linear_weight


@dataclass(frozen=True)
class CurtainWallLayout:
    """Resolved grid, panels, mullions, weights and line load of a curtain wall."""

    panels: tuple[CurtainPanel, ...]
    mullions: tuple[CurtainMullion, ...]
    columns: int
    rows: int
    length: float
    height: float
    area_m2: float
    panels_weight: float
    mullions_weight: float
    total_weight: float
    weight_per_m2: float
    line_load: float
    depth: float
    detailed: bool


def curtain_wall_layout(
    arch: Architecture,
    curtain: CurtainWall,
    elevations: dict[str, float] | None = None,
) -> CurtainWallLayout | None:
    """Resolve grid divisions, panels, mullions, and detailed weight for ``curtain``."""
    cw_type = next((t for t in arch.curtainWallTypes if t.id == curtain.type), None)
    if cw_type is None:
        return None
    if elevations is not None:
        levels = wall_levels(curtain, elevations)
        if levels is None:
            return None
        bottom, top = levels
    elif curtain.height is not None:
        bottom = float(curtain.baseOffset)
        top = bottom + float(curtain.height)
    else:
        return None

    height = top - bottom
    if height <= 0:
        return None

    panel_types = {t.id: t for t in arch.curtainPanelTypes}
    mullion_types = {t.id: t for t in arch.curtainMullionTypes}
    default_panel = panel_types.get(cw_type.panelType) if cw_type.panelType else None
    v_mullion = mullion_types.get(cw_type.verticalMullion) if cw_type.verticalMullion else None
    h_mullion = (
        mullion_types.get(cw_type.horizontalMullion) if cw_type.horizontalMullion else None
    )
    b_mullion = mullion_types.get(cw_type.borderMullion) if cw_type.borderMullion else None
    overrides = {(ov.segment, ov.column, ov.row): ov.panelType for ov in curtain.panelOverrides}

    has_panel_types = default_panel is not None or bool(overrides)
    has_mullion_types = any(m is not None for m in (v_mullion, h_mullion, b_mullion))
    detailed = has_panel_types or has_mullion_types

    fallback_panel_weight = cw_type.glassThickness / 1000.0 * cw_type.glassUnitWeight
    z_divs = grid_divisions(height, cw_type.horizontalGrid, cw_type.transomSpacing)
    rows = len(z_divs) - 1

    panels: list[CurtainPanel] = []
    mullions: list[CurtainMullion] = []
    total_length = 0.0
    total_cols = 0

    segments = [
        (a, b) for a, b in itertools.pairwise(curtain.path) if math.dist(a, b) > 1e-6
    ]
    for seg_idx, (a, b) in enumerate(segments):
        seg_len = math.dist(a, b)
        total_length += seg_len
        dx, dy = (b[0] - a[0]) / seg_len, (b[1] - a[1]) / seg_len
        u_divs = grid_divisions(seg_len, cw_type.verticalGrid, cw_type.mullionSpacing)
        cols = len(u_divs) - 1
        total_cols += cols

        for r in range(rows):
            z0, z1 = bottom + z_divs[r], bottom + z_divs[r + 1]
            cell_h = z1 - z0
            for c in range(cols):
                u0, u1 = u_divs[c], u_divs[c + 1]
                cell_w = u1 - u0
                ov_id = overrides.get((seg_idx, c, r))
                ptype = panel_types.get(ov_id) if ov_id else default_panel
                p_start = (a[0] + dx * u0, a[1] + dy * u0, z0)
                p_end = (a[0] + dx * u1, a[1] + dy * u1, z0)
                panels.append(
                    CurtainPanel(
                        segment=seg_idx,
                        column=c,
                        row=r,
                        panel_type_id=ptype.id if ptype else cw_type.id,
                        kind=ptype.kind if ptype else "glazed",
                        material=ptype.material if ptype else "Glass",
                        thickness=float(ptype.thickness if ptype else cw_type.glassThickness),
                        area_weight=ptype.area_weight if ptype else fallback_panel_weight,
                        start=p_start,
                        end=p_end,
                        width=cell_w,
                        height=cell_h,
                        direction=(dx, dy),
                    )
                )

        # Vertical mullions (skip shared start post on subsequent segments)
        start_col = 0 if seg_idx == 0 else 1
        for k in range(start_col, len(u_divs)):
            u = u_divs[k]
            is_border = (seg_idx == 0 and k == 0) or (
                seg_idx == len(segments) - 1 and k == len(u_divs) - 1
            )
            mtype = (b_mullion if is_border and b_mullion is not None else v_mullion)
            px, py = a[0] + dx * u, a[1] + dy * u
            mullions.append(
                CurtainMullion(
                    orientation="vertical",
                    segment=seg_idx,
                    index=k,
                    mullion_type_id=mtype.id if mtype else cw_type.id,
                    material=mtype.material if mtype else "Aluminium",
                    width=float(mtype.width if mtype else 50.0),
                    depth=float(mtype.depth if mtype else cw_type.depth),
                    linear_weight=mtype.linear_weight if mtype else 0.0,
                    start=(px, py, bottom),
                    end=(px, py, top),
                    direction=(dx, dy),
                    length=height,
                )
            )

        # Horizontal transoms
        for r_idx, z_rel in enumerate(z_divs):
            is_border = r_idx == 0 or r_idx == len(z_divs) - 1
            mtype = (b_mullion if is_border and b_mullion is not None else h_mullion)
            z_abs = bottom + z_rel
            mullions.append(
                CurtainMullion(
                    orientation="horizontal",
                    segment=seg_idx,
                    index=r_idx,
                    mullion_type_id=mtype.id if mtype else cw_type.id,
                    material=mtype.material if mtype else "Aluminium",
                    width=float(mtype.width if mtype else 50.0),
                    depth=float(mtype.depth if mtype else cw_type.depth),
                    linear_weight=mtype.linear_weight if mtype else 0.0,
                    start=(float(a[0]), float(a[1]), z_abs),
                    end=(float(b[0]), float(b[1]), z_abs),
                    direction=(dx, dy),
                    length=seg_len,
                )
            )

    if total_length <= 0:
        return None

    area_m2 = (total_length / 1000.0) * (height / 1000.0)
    panels_weight = sum(p.weight for p in panels)
    if has_mullion_types:
        mullions_weight = sum(m.weight for m in mullions)
    else:
        mullions_weight = cw_type.frameWeight * area_m2

    if detailed:
        total_weight = panels_weight + mullions_weight
    else:
        total_weight = cw_type.weight * area_m2
        panels_weight = fallback_panel_weight * area_m2
        mullions_weight = cw_type.frameWeight * area_m2

    weight_per_m2 = total_weight / area_m2 if area_m2 > 0 else cw_type.weight
    line_load = total_weight / (total_length / 1000.0)
    depths = [cw_type.depth, *(m.depth for m in mullions if has_mullion_types)]
    return CurtainWallLayout(
        panels=tuple(panels),
        mullions=tuple(mullions),
        columns=total_cols,
        rows=rows,
        length=total_length,
        height=height,
        area_m2=area_m2,
        panels_weight=panels_weight,
        mullions_weight=mullions_weight,
        total_weight=total_weight,
        weight_per_m2=weight_per_m2,
        line_load=line_load,
        depth=max(depths),
        detailed=detailed,
    )


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
        for item in [*arch.roofs, *arch.ramps, *arch.ceilings, *arch.components, *arch.inPlaceElements]:
            if item.story not in elevations:
                problems.append(f"{item.id}: no story '{item.story}'")
        for ceiling in arch.ceilings:
            if ceiling.story in elevations and ceiling_polygon(arch, ceiling, elevations) is None:
                problems.append(f"{ceiling.id}: its room or outline has no area")
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
