"""Architectural components (furniture, casework, plumbing fixtures, equipment, generic)
for ``05 Floor Plan/architecture.json``.

SAEngine uses parametric component types with defaults (no family editor): each
:class:`ComponentType` defines a category, overall dimensions (width, depth, height in mm),
weight (kg), material, optional 2D plan symbol primitives, 3D representation (box, cylinder, or
extrusion), and default parameters. Instances (:class:`ComponentInstance`) are placed on a
story at a plan point with rotation and optional mirroring, with automatic host-room detection.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.labels import field_title
from saengine.library.materials import Id

if TYPE_CHECKING:
    from saengine.library.architecture import Architecture

Length = Annotated[float, Field(gt=0, description="[mm]")]
Mm = Annotated[float, Field(description="[mm]")]
Point2 = Annotated[list[float], Field(min_length=2, max_length=2, description="[x, y] in mm.")]

ComponentCategory = Literal["furniture", "casework", "plumbingFixture", "equipment", "generic"]
ComponentIfcClass = Literal[
    "IfcFurniture",
    "IfcSanitaryTerminal",
    "IfcFlowTerminal",
    "IfcBuildingElementProxy",
]
ParameterValue = float | str | bool

_DEFAULT_IFC_CLASS: dict[str, ComponentIfcClass] = {
    "furniture": "IfcFurniture",
    "casework": "IfcFurniture",
    "plumbingFixture": "IfcSanitaryTerminal",
    "equipment": "IfcFlowTerminal",
    "generic": "IfcBuildingElementProxy",
}

#: Standard gravity acceleration [m/s²] to convert kg mass to kN weight.
_G_KN_PER_KG = 9.80665 / 1000.0


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


# ───────────────────────────── 2D symbol primitives ─────────────────────────────


class SymbolLine(_Model):
    """A line segment in the component's local plan coordinates (mm, origin at centre)."""

    kind: Literal["line"] = "line"
    start: Point2
    end: Point2


class SymbolRect(_Model):
    """An axis-aligned rectangle centred at ``(x, y)`` in local plan coordinates (mm)."""

    kind: Literal["rect"] = "rect"
    x: float = 0.0
    y: float = 0.0
    width: Length
    depth: Length


class SymbolCircle(_Model):
    """A circle in local plan coordinates (mm)."""

    kind: Literal["circle"] = "circle"
    center: Point2 = Field(default_factory=lambda: [0.0, 0.0])
    radius: Length


class SymbolPolyline(_Model):
    """A polyline (open or closed) in local plan coordinates (mm)."""

    kind: Literal["polyline"] = "polyline"
    points: list[Point2] = Field(min_length=2)
    closed: bool = False


SymbolPrimitive = Annotated[
    SymbolLine | SymbolRect | SymbolCircle | SymbolPolyline,
    Field(discriminator="kind"),
]


# ───────────────────────────── component types & instances ─────────────────────────────


class ComponentType(_Model):
    """Parametric component type definition (no family editor)."""

    id: Id
    name: str = Field(min_length=1)
    category: ComponentCategory = "furniture"
    width: Length = Field(description="Overall plan X extent [mm].")
    depth: Length = Field(description="Overall plan Y extent [mm].")
    height: Length = Field(description="Overall Z height [mm].")
    weight: float = Field(default=0.0, ge=0, description="Mass [kg].")
    material: str = Field(default="", description="Primary material description.")
    symbol2d: list[SymbolPrimitive] = Field(
        default_factory=list,
        title="2D plan symbol",
        description="Simple outline primitives in local mm (origin at centre).",
    )
    representation3d: Literal["box", "cylinder", "extrusion"] = Field(
        default="box",
        title="3D representation",
        description="Simple 3D solid representation used in BIM/IFC export.",
    )
    extrusionOutline: list[Point2] | None = Field(
        default=None,
        title="Extrusion outline",
        description="Plan outline [mm] in local coordinates when representation3d is extrusion.",
    )
    parameters: dict[str, ParameterValue] = Field(
        default_factory=dict,
        description="Default parametric attributes (type properties).",
    )
    ifcClass: ComponentIfcClass | None = Field(
        default=None,
        title="IFC class",
        description="Override default IFC class for this component's category.",
    )
    ifcPredefinedType: str | None = Field(
        default=None,
        title="IFC predefined type",
        description="Optional IFC4 PredefinedType (e.g. BED, CHAIR, TOILETPAN).",
    )

    @model_validator(mode="after")
    def _check_extrusion(self) -> ComponentType:
        if self.representation3d == "extrusion" and (
            not self.extrusionOutline or len(self.extrusionOutline) < 3
        ):
            raise ValueError(
                f"{self.id}: representation3d 'extrusion' requires extrusionOutline with at least 3 points"
            )
        return self

    def resolved_ifc_class(self) -> ComponentIfcClass:
        return self.ifcClass or _DEFAULT_IFC_CLASS[self.category]

    @property
    def weight_kn(self) -> float:
        """Weight force [kN]."""
        return self.weight * _G_KN_PER_KG


class ComponentInstance(_Model):
    """A placed instance of a :class:`ComponentType` on a story."""

    id: Id
    type: Id = Field(title="Component type")
    story: Id
    point: Point2 = Field(description="Insertion centre [x, y] in mm.")
    rotation: float = Field(default=0.0, description="Plan rotation CCW [°].")
    mirrored: bool = Field(default=False, description="Mirrored across local Y axis before rotation.")
    elevation: Mm = Field(default=0.0, description="Offset above the story level [mm].")
    hostRoom: Id | None = Field(
        default=None,
        title="Host room",
        description="Id of the room enclosing this component.",
    )
    parameters: dict[str, ParameterValue] = Field(
        default_factory=dict,
        description="Instance parameter overrides.",
    )


# ───────────────────────────── starter library ─────────────────────────────


def starter_component_types() -> list[ComponentType]:
    """Original parametric starter library of common furniture, casework, plumbing fixtures,
    and equipment with typical metric sizes, weights, and 2D plan symbols."""
    items: list[dict[str, Any]] = [
        {
            "id": "BED-DBL",
            "name": "Double bed",
            "category": "furniture",
            "width": 2000,
            "depth": 1600,
            "height": 550,
            "weight": 65.0,
            "material": "Timber / fabric",
            "ifcPredefinedType": "BED",
            "parameters": {"headboardHeight": 1000, "sizeLabel": "Queen/Double"},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 2000, "depth": 1600},
                {"kind": "rect", "x": -750, "y": -380, "width": 360, "depth": 620},
                {"kind": "rect", "x": -750, "y": 380, "width": 360, "depth": 620},
                {"kind": "line", "start": [-450, -800], "end": [-450, 800]},
            ],
        },
        {
            "id": "BED-SGL",
            "name": "Single bed",
            "category": "furniture",
            "width": 2000,
            "depth": 1000,
            "height": 550,
            "weight": 40.0,
            "material": "Timber / fabric",
            "ifcPredefinedType": "BED",
            "parameters": {"headboardHeight": 950, "sizeLabel": "Single"},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 2000, "depth": 1000},
                {"kind": "rect", "x": -750, "y": 0, "width": 360, "depth": 620},
                {"kind": "line", "start": [-450, -500], "end": [-450, 500]},
            ],
        },
        {
            "id": "SOFA-3",
            "name": "3-seat sofa",
            "category": "furniture",
            "width": 2100,
            "depth": 900,
            "height": 850,
            "weight": 55.0,
            "material": "Fabric / timber",
            "ifcPredefinedType": "SOFA",
            "parameters": {"seats": 3},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 2100, "depth": 900},
                {"kind": "line", "start": [-900, -250], "end": [900, -250]},
                {"kind": "line", "start": [-900, -250], "end": [-900, 450]},
                {"kind": "line", "start": [900, -250], "end": [900, 450]},
                {"kind": "line", "start": [-300, -250], "end": [-300, 450]},
                {"kind": "line", "start": [300, -250], "end": [300, 450]},
            ],
        },
        {
            "id": "TABLE-DIN",
            "name": "Dining table",
            "category": "furniture",
            "width": 1800,
            "depth": 900,
            "height": 750,
            "weight": 45.0,
            "material": "Timber",
            "ifcPredefinedType": "TABLE",
            "parameters": {"seats": 6},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 1800, "depth": 900},
                {"kind": "rect", "x": 0, "y": 0, "width": 1680, "depth": 780},
            ],
        },
        {
            "id": "WARDROBE",
            "name": "Wardrobe",
            "category": "casework",
            "width": 1800,
            "depth": 600,
            "height": 2100,
            "weight": 95.0,
            "material": "Engineered wood",
            "ifcPredefinedType": "USERDEFINED",
            "parameters": {"doors": 3, "mount": "floor"},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 1800, "depth": 600},
                {"kind": "line", "start": [-900, -300], "end": [900, 300]},
                {"kind": "line", "start": [-900, 300], "end": [900, -300]},
            ],
        },
        {
            "id": "CAB-BASE",
            "name": "Kitchen cabinet run (base)",
            "category": "casework",
            "width": 1800,
            "depth": 600,
            "height": 850,
            "weight": 60.0,
            "material": "Engineered wood / stone",
            "ifcPredefinedType": "USERDEFINED",
            "parameters": {"mount": "floor", "counterThickness": 30},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 1800, "depth": 600},
                {"kind": "line", "start": [-300, -300], "end": [-300, 300]},
                {"kind": "line", "start": [300, -300], "end": [300, 300]},
            ],
        },
        {
            "id": "CAB-WALL",
            "name": "Kitchen cabinet run (wall)",
            "category": "casework",
            "width": 1800,
            "depth": 350,
            "height": 720,
            "weight": 35.0,
            "material": "Engineered wood",
            "ifcPredefinedType": "USERDEFINED",
            "parameters": {"mount": "wall", "mountingHeight": 1450},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 1800, "depth": 350},
                {"kind": "line", "start": [-900, 0], "end": [900, 0]},
            ],
        },
        {
            "id": "WC",
            "name": "Water closet (WC)",
            "category": "plumbingFixture",
            "width": 380,
            "depth": 680,
            "height": 760,
            "weight": 32.0,
            "material": "Vitreous china",
            "ifcPredefinedType": "TOILETPAN",
            "parameters": {"fixtureUnits": 3.0, "flushLitres": 6.0},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 240, "width": 380, "depth": 200},
                {"kind": "circle", "center": [0, -100], "radius": 175},
            ],
        },
        {
            "id": "BASIN",
            "name": "Wash basin",
            "category": "plumbingFixture",
            "width": 550,
            "depth": 450,
            "height": 850,
            "weight": 18.0,
            "material": "Vitreous china",
            "ifcPredefinedType": "WASHHANDBASIN",
            "parameters": {"fixtureUnits": 1.0},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 550, "depth": 450},
                {"kind": "circle", "center": [0, -20], "radius": 150},
            ],
        },
        {
            "id": "SINK",
            "name": "Kitchen sink",
            "category": "plumbingFixture",
            "width": 1000,
            "depth": 500,
            "height": 850,
            "weight": 15.0,
            "material": "Stainless steel",
            "ifcPredefinedType": "SINK",
            "parameters": {"fixtureUnits": 2.0, "bowls": 1},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 1000, "depth": 500},
                {"kind": "rect", "x": -210, "y": 0, "width": 440, "depth": 380},
                {"kind": "circle", "center": [-210, 0], "radius": 25},
            ],
        },
        {
            "id": "SHOWER",
            "name": "Shower tray",
            "category": "plumbingFixture",
            "width": 900,
            "depth": 900,
            "height": 120,
            "weight": 28.0,
            "material": "Acrylic / ceramic",
            "ifcPredefinedType": "SHOWER",
            "parameters": {"fixtureUnits": 2.0},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 900, "depth": 900},
                {"kind": "line", "start": [-450, -450], "end": [450, 450]},
                {"kind": "line", "start": [-450, 450], "end": [450, -450]},
                {"kind": "circle", "center": [0, 0], "radius": 35},
            ],
        },
        {
            "id": "DESK",
            "name": "Office desk",
            "category": "furniture",
            "width": 1400,
            "depth": 700,
            "height": 750,
            "weight": 32.0,
            "material": "Engineered wood / steel",
            "ifcPredefinedType": "DESK",
            "parameters": {"cableTray": True},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 1400, "depth": 700},
                {"kind": "line", "start": [-550, -350], "end": [-550, 350]},
                {"kind": "line", "start": [550, -350], "end": [550, 350]},
            ],
        },
        {
            "id": "CHAIR",
            "name": "Chair",
            "category": "furniture",
            "width": 500,
            "depth": 500,
            "height": 850,
            "weight": 7.0,
            "material": "Timber / fabric",
            "ifcPredefinedType": "CHAIR",
            "parameters": {"seatHeight": 450},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 500, "depth": 500},
                {"kind": "line", "start": [-250, 170], "end": [250, 170]},
            ],
        },
        {
            "id": "SHELF",
            "name": "Shelving unit",
            "category": "casework",
            "width": 1200,
            "depth": 350,
            "height": 1800,
            "weight": 40.0,
            "material": "Steel / timber",
            "ifcPredefinedType": "SHELF",
            "parameters": {"shelves": 5},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 1200, "depth": 350},
                {"kind": "line", "start": [-600, -175], "end": [600, 175]},
            ],
        },
        {
            "id": "AC-IDU",
            "name": "AC indoor unit",
            "category": "equipment",
            "width": 900,
            "depth": 220,
            "height": 300,
            "weight": 14.0,
            "material": "ABS / metal",
            "parameters": {"mount": "wall", "mountingHeight": 2200, "coolingKw": 5.2},
            "symbol2d": [
                {"kind": "rect", "x": 0, "y": 0, "width": 900, "depth": 220},
                {"kind": "line", "start": [-400, -60], "end": [400, -60]},
            ],
        },
        {
            "id": "WH-ELEC",
            "name": "Water heater",
            "category": "equipment",
            "width": 450,
            "depth": 450,
            "height": 700,
            "weight": 55.0,
            "material": "Enamelled steel",
            "representation3d": "cylinder",
            "parameters": {"capacityLitres": 50, "powerKw": 2.0},
            "symbol2d": [
                {"kind": "circle", "center": [0, 0], "radius": 225},
                {"kind": "circle", "center": [0, 0], "radius": 60},
            ],
        },
    ]
    return [ComponentType.model_validate(item) for item in items]


# ───────────────────────────── placement, mirror, array & room detection ─────────────────────────────


def transform_point(
    local_xy: Sequence[float],
    origin: Sequence[float],
    rotation: float = 0.0,
    mirrored: bool = False,
) -> tuple[float, float]:
    """Transform a local 2D point (mm) to global plan coordinates (mirror X, rotate CCW, translate)."""
    lx = -float(local_xy[0]) if mirrored else float(local_xy[0])
    ly = float(local_xy[1])
    rad = math.radians(rotation)
    c, s = math.cos(rad), math.sin(rad)
    return (float(origin[0]) + lx * c - ly * s, float(origin[1]) + lx * s + ly * c)


def component_footprint_2d(
    comp: ComponentInstance, comp_type: ComponentType
) -> list[tuple[float, float]]:
    """The component's bounding-box footprint corners in global plan coordinates [mm]."""
    hw, hd = comp_type.width / 2.0, comp_type.depth / 2.0
    corners = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    return [transform_point(pt, comp.point, comp.rotation, comp.mirrored) for pt in corners]


def detect_host_room(
    arch: Architecture,
    story: str,
    point: Sequence[float],
    elevations: dict[str, float],
) -> str | None:
    """Find the room on ``story`` enclosing ``point`` [x, y] (mm); None when outside any room."""
    from shapely.geometry import Point

    from saengine.library.architecture import room_boundary

    if story not in elevations:
        return None
    pt = Point(float(point[0]), float(point[1]))
    for room in arch.rooms:
        if room.story != story:
            continue
        found = room_boundary(arch, room, elevations)
        if found is None:
            continue
        face, net = found
        if net.covers(pt) or face.covers(pt):
            return room.id
    return None


def next_component_id(arch: Architecture, prefix: str = "C") -> str:
    """Next unused instance id across the architecture."""
    used = {item.id for item in arch.instances()}
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def place_component(
    arch: Architecture,
    type_id: str,
    story: str,
    point: Sequence[float],
    elevations: dict[str, float] | None = None,
    *,
    rotation: float = 0.0,
    mirrored: bool = False,
    elevation: float = 0.0,
    id: str | None = None,
    parameters: dict[str, ParameterValue] | None = None,
) -> tuple[Architecture, ComponentInstance]:
    """Place a component of ``type_id`` on ``story`` at ``point``; detects ``hostRoom`` when
    ``elevations`` is provided."""
    if not any(t.id == type_id for t in arch.componentTypes):
        raise ValueError(f"no component type '{type_id}'")
    comp_id = id or next_component_id(arch)
    host_room = detect_host_room(arch, story, point, elevations) if elevations is not None else None
    instance = ComponentInstance(
        id=comp_id,
        type=type_id,
        story=story,
        point=[float(point[0]), float(point[1])],
        rotation=float(rotation),
        mirrored=mirrored,
        elevation=float(elevation),
        hostRoom=host_room,
        parameters=dict(parameters or {}),
    )
    updated = arch.model_copy(update={"components": [*arch.components, instance]})
    updated = type(arch).model_validate(updated.model_dump(by_alias=True))
    return updated, instance


def mirror_component(
    arch: Architecture,
    component_id: str,
    axis_start: Sequence[float],
    axis_end: Sequence[float],
    elevations: dict[str, float] | None = None,
    *,
    copy: bool = False,
) -> tuple[Architecture, ComponentInstance]:
    """Mirror component ``component_id`` across line ``axis_start``→``axis_end`` (in place or as
    a new copy when ``copy=True``)."""
    ax0, ay0 = float(axis_start[0]), float(axis_start[1])
    ax1, ay1 = float(axis_end[0]), float(axis_end[1])
    dx, dy = ax1 - ax0, ay1 - ay0
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-9:
        raise ValueError("mirror axis needs two distinct points")

    source = next((c for c in arch.components if c.id == component_id), None)
    if source is None:
        raise ValueError(f"no component '{component_id}'")

    px, py = source.point[0] - ax0, source.point[1] - ay0
    dot = (px * dx + py * dy) / length_sq
    proj_x, proj_y = ax0 + dot * dx, ay0 + dot * dy
    new_pt = [2.0 * proj_x - source.point[0], 2.0 * proj_y - source.point[1]]

    axis_angle = math.degrees(math.atan2(dy, dx))
    new_rot = (2.0 * axis_angle - source.rotation) % 360.0
    host_room = (
        detect_host_room(arch, source.story, new_pt, elevations)
        if elevations is not None
        else source.hostRoom
    )
    mirrored_inst = source.model_copy(
        update={
            "id": next_component_id(arch) if copy else source.id,
            "point": new_pt,
            "rotation": round(new_rot, 6),
            "mirrored": not source.mirrored,
            "hostRoom": host_room,
        }
    )
    if copy:
        comps = [*arch.components, mirrored_inst]
    else:
        comps = [mirrored_inst if c.id == component_id else c for c in arch.components]
    updated = type(arch).model_validate(
        arch.model_copy(update={"components": comps}).model_dump(by_alias=True)
    )
    return updated, mirrored_inst


def array_component(
    arch: Architecture,
    component_id: str,
    *,
    count: int | None = None,
    dx: float = 0.0,
    dy: float = 0.0,
    rows: int = 1,
    cols: int = 1,
    row_spacing: float = 0.0,
    col_spacing: float = 0.0,
    elevations: dict[str, float] | None = None,
) -> tuple[Architecture, list[ComponentInstance]]:
    """Create linear (``count`` copies stepped by ``dx, dy``) or rectangular (``rows × cols``)
    copies of ``component_id``, keeping the original in place."""
    source = next((c for c in arch.components if c.id == component_id), None)
    if source is None:
        raise ValueError(f"no component '{component_id}'")

    offsets: list[tuple[float, float]] = []
    if count is not None:
        if count < 2:
            raise ValueError("linear array count must be at least 2")
        offsets = [(i * dx, i * dy) for i in range(1, count)]
    else:
        if rows < 1 or cols < 1 or (rows == 1 and cols == 1):
            raise ValueError("rectangular array needs rows * cols >= 2")
        for r in range(rows):
            for c in range(cols):
                if r == 0 and c == 0:
                    continue
                offsets.append((c * col_spacing, r * row_spacing))

    current = arch
    created: list[ComponentInstance] = []
    for ox, oy in offsets:
        pt = [source.point[0] + ox, source.point[1] + oy]
        current, inst = place_component(
            current,
            source.type,
            source.story,
            pt,
            elevations,
            rotation=source.rotation,
            mirrored=source.mirrored,
            elevation=source.elevation,
            parameters=source.parameters,
        )
        created.append(inst)
    return current, created


# ───────────────────────────── schedules & BOQ ─────────────────────────────


def resolve_component_room(
    arch: Architecture,
    comp: ComponentInstance,
    elevations: dict[str, float] | None = None,
) -> str | None:
    """The room id hosting ``comp`` (stored ``hostRoom`` if valid, else detected when
    ``elevations`` is provided)."""
    room_ids = {r.id for r in arch.rooms if r.story == comp.story}
    if comp.hostRoom and comp.hostRoom in room_ids:
        return comp.hostRoom
    if elevations is not None:
        return detect_host_room(arch, comp.story, comp.point, elevations)
    return None


def component_schedule(
    arch: Architecture, elevations: dict[str, float] | None = None
) -> dict[str, Any]:
    """Schedule of components counted by type per room and per storey (plus in-place elements)."""
    types = {t.id: t for t in arch.componentTypes}
    rooms = {r.id: r for r in arch.rooms}
    by_type: dict[str, dict[str, Any]] = {}
    by_room: dict[str, dict[str, Any]] = {
        r.id: {
            "room": r.id,
            "name": r.name,
            "number": r.number,
            "story": r.story,
            "counts": {},
            "totalCount": 0,
            "totalWeight_kg": 0.0,
        }
        for r in arch.rooms
    }
    by_story: dict[str, dict[str, Any]] = {}
    unassigned_counts: dict[str, int] = {}
    unassigned_total = 0
    total_count = 0
    total_weight = 0.0

    for comp in arch.components:
        ctype = types[comp.type]
        room_id = resolve_component_room(arch, comp, elevations)
        total_count += 1
        total_weight += ctype.weight

        trow = by_type.setdefault(
            ctype.id,
            {
                "type": ctype.id,
                "name": ctype.name,
                "category": ctype.category,
                "width": ctype.width,
                "depth": ctype.depth,
                "height": ctype.height,
                "weight_kg": ctype.weight,
                "count": 0,
                "totalWeight_kg": 0.0,
                "byStory": {},
                "byRoom": {},
            },
        )
        trow["count"] += 1
        trow["totalWeight_kg"] = round(trow["totalWeight_kg"] + ctype.weight, 3)
        trow["byStory"][comp.story] = trow["byStory"].get(comp.story, 0) + 1
        if room_id:
            trow["byRoom"][room_id] = trow["byRoom"].get(room_id, 0) + 1

        srow = by_story.setdefault(
            comp.story, {"counts": {}, "totalCount": 0, "totalWeight_kg": 0.0}
        )
        srow["counts"][ctype.id] = srow["counts"].get(ctype.id, 0) + 1
        srow["totalCount"] += 1
        srow["totalWeight_kg"] = round(srow["totalWeight_kg"] + ctype.weight, 3)

        if room_id and room_id in by_room:
            rrow = by_room[room_id]
            rrow["counts"][ctype.id] = rrow["counts"].get(ctype.id, 0) + 1
            rrow["totalCount"] += 1
            rrow["totalWeight_kg"] = round(rrow["totalWeight_kg"] + ctype.weight, 3)
        else:
            unassigned_counts[ctype.id] = unassigned_counts.get(ctype.id, 0) + 1
            unassigned_total += 1

    in_place = []
    for elem in arch.inPlaceElements:
        room_id = elem.hostRoom if elem.hostRoom in rooms else None
        in_place.append(
            {
                "id": elem.id,
                "name": elem.name,
                "category": elem.category,
                "story": elem.story,
                "room": room_id,
                "weight_kg": elem.weight,
            }
        )
        total_weight += elem.weight

    return {
        "byType": list(by_type.values()),
        "byRoom": by_room,
        "byStory": by_story,
        "unassigned": {"counts": unassigned_counts, "totalCount": unassigned_total},
        "inPlace": in_place,
        "totalCount": total_count,
        "totalWeight_kg": round(total_weight, 3),
    }


def measure_components(measure: Any, arch: Architecture, building: Any) -> None:
    """Add components and in-place elements to the BOQ ``furniture`` group from the schedule."""
    elevations = {s.id: s.elevation for s in building.stories} if building is not None else {}
    types = {t.id: t for t in arch.componentTypes}
    rooms = {r.id: r for r in arch.rooms}
    bill = measure.bill
    for comp in arch.components:
        ctype = types.get(comp.type)
        if ctype is None:
            continue
        room_id = resolve_component_room(arch, comp, elevations)
        room = rooms.get(room_id) if room_id else None
        room_label = (
            f"{room.id} ({room.name})"
            if room and room.name
            else (room.id if room else "Unassigned")
        )
        bill.add(
            "furniture",
            (1, ctype.category, ctype.id),
            f"Component {ctype.id}: {ctype.name}, {ctype.width:g} × {ctype.depth:g} × "
            f"{ctype.height:g} mm",
            "nr",
            comp.id,
            1.0,
            story=comp.story,
            detail=room_label,
            kind=ctype.category,
        )
    for elem in arch.inPlaceElements:
        room = rooms.get(elem.hostRoom) if elem.hostRoom else None
        room_label = (
            f"{room.id} ({room.name})"
            if room and room.name
            else (room.id if room else "Unassigned")
        )
        bill.add(
            "furniture",
            (2, elem.category, elem.id),
            f"In-place {elem.id}: {elem.name} ({elem.category})",
            "nr",
            elem.id,
            1.0,
            story=elem.story,
            detail=room_label,
            kind=elem.category,
        )


# ───────────────────────────── structural load handling ─────────────────────────────


def explicit_furnishings_allowed() -> bool:
    """Whether the active code pack allows furniture/furnishings to be modelled explicitly as SD."""
    from saengine.codes import context as code_context

    pack = code_context.current()
    if not pack.has("areaLoads"):
        return False
    rule = pack.table("areaLoads").partitions
    return bool(getattr(rule, "explicitFurnishings", False)) if rule is not None else False


def component_loads(arch: Architecture, building: Any, out: Any, mode: str = "architecture") -> None:
    """Record component weights on ``out.component_rows``; apply as SD loads on slabs only when
    the active code pack sets ``areaLoads.partitions.explicitFurnishings`` to True."""
    if not arch.components and not arch.inPlaceElements:
        return
    from shapely.geometry import Point, Polygon

    from saengine.fem.architecture_loads import LEVEL, ComponentLoad
    from saengine.library.bim import SlabElement

    elevations = {s.id: s.elevation for s in building.stories}
    slabs = [
        (e, Polygon(e.boundary))
        for e in building.elements
        if isinstance(e, SlabElement) and len(e.boundary) >= 3
    ]
    types = {t.id: t for t in arch.componentTypes}
    allowed = explicit_furnishings_allowed() and mode != "allowance"
    applied_any = False
    reported_only = False

    def handle_item(
        item_id: str,
        type_id: str,
        category: str,
        story: str,
        xy: Sequence[float],
        weight_kg: float,
        room_id: str | None,
    ) -> None:
        nonlocal applied_any, reported_only
        weight_kn = weight_kg * _G_KN_PER_KG
        can_apply = allowed and weight_kn > 0 and story in elevations
        slab_id: str | None = None
        if can_apply:
            z = elevations[story]
            pt = Point(float(xy[0]), float(xy[1]))
            slab = next(
                (sl for sl, poly in slabs if abs(sl.elevation - z) < LEVEL and poly.covers(pt)),
                None,
            )
            if slab is not None:
                slab_id = slab.id
                out.component_loads.append(
                    ComponentLoad(
                        source=item_id,
                        slab=slab.id,
                        x=float(xy[0]) * 1e-3,
                        y=float(xy[1]) * 1e-3,
                        force=weight_kn * 1e3,
                        case="SD",
                    )
                )
                applied_any = True
            else:
                out.notes.append(
                    f"{item_id}: no slab under it on {story}; its {weight_kn:.3f} kN is not applied"
                )
                can_apply = False
        elif weight_kn > 0 and not allowed:
            reported_only = True
        out.component_rows.append(
            {
                "id": item_id,
                "type": type_id,
                "category": category,
                "story": story,
                "room": room_id,
                "slab": slab_id,
                "weight_kg": round(weight_kg, 3),
                "weight_kN": round(weight_kn, 4),
                "applied": bool(slab_id),
            }
        )

    for comp in arch.components:
        ctype = types[comp.type]
        room_id = resolve_component_room(arch, comp, elevations)
        handle_item(
            comp.id, ctype.id, ctype.category, comp.story, comp.point, ctype.weight, room_id
        )
    for elem in arch.inPlaceElements:
        from saengine.library.massing import in_place_anchor

        anchor = in_place_anchor(elem)
        room_id = elem.hostRoom or detect_host_room(arch, elem.story, anchor, elevations)
        handle_item(
            elem.id, "inPlace", elem.category, elem.story, anchor, elem.weight, room_id
        )

    if reported_only and not applied_any:
        out.notes.append(
            "Components: weights are report-only (the active code pack models furnishings within occupancy live loads)."
        )


# ───────────────────────────── IFC export ─────────────────────────────


def _component_pset_props(
    ctype: ComponentType, comp: ComponentInstance
) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "TypeId": ctype.id,
        "TypeName": ctype.name,
        "Category": ctype.category,
        "Width_mm": float(ctype.width),
        "Depth_mm": float(ctype.depth),
        "Height_mm": float(ctype.height),
        "Weight_kg": float(ctype.weight),
        "Material": ctype.material,
    }
    for key, val in {**ctype.parameters, **comp.parameters}.items():
        if key not in merged:
            merged[key] = val
    return merged


def _build_component_profile(w: Any, ctype: ComponentType, mirrored: bool, name: str) -> Any:
    from saengine.library.ifc import _SI

    if ctype.representation3d == "cylinder":
        profile = w.run("profile.add_parameterized_profile", w.file, ifc_class="IfcCircleProfileDef")
        profile.Radius = float(min(ctype.width, ctype.depth) / 2.0)
        return profile
    if ctype.representation3d == "extrusion" and ctype.extrusionOutline:
        pts = [
            ((-float(x) if mirrored else float(x)) * _SI, float(y) * _SI)
            for x, y in ctype.extrusionOutline
        ]
        if mirrored:
            pts.reverse()
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        return w.run("profile.add_arbitrary_profile", w.file, profile=pts, name=name)
    return w.rectangle(ctype.width, ctype.depth)


def export_components_ifc(
    w: Any,
    arch: Architecture,
    elevations: dict[str, float],
    storeys: dict[str, Any],
    storey_at: Any,
    ids: dict[str, str],
    skipped: list[str],
    pset: Any,
) -> None:
    """Export components as IfcFurniture / IfcSanitaryTerminal / IfcFlowTerminal /
    IfcBuildingElementProxy with type & instance property sets."""
    from saengine.library.ifc import _placement, _rotation

    types = {t.id: t for t in arch.componentTypes}
    ifc_types: dict[str, Any] = {}
    _TYPE_CLASS = {
        "IfcFurniture": "IfcFurnitureType",
        "IfcSanitaryTerminal": "IfcSanitaryTerminalType",
        "IfcBuildingElementProxy": "IfcBuildingElementProxyType",
    }

    for comp in arch.components:
        if comp.story not in elevations:
            skipped.append(f"{comp.id}: no story '{comp.story}'")
            continue
        ctype = types[comp.type]
        ifc_class = ctype.resolved_ifc_class()
        predefined = (
            None
            if ifc_class == "IfcFlowTerminal"
            else (ctype.ifcPredefinedType or "USERDEFINED")
        )
        product = w.entity(ifc_class, comp.id, f"arch:{comp.id}", predefined)
        product.Tag = comp.id
        product.ObjectType = ctype.id
        product.Description = ctype.name

        profile = _build_component_profile(w, ctype, comp.mirrored, comp.id)
        w.extrusion(product, profile, ctype.height, None)
        z = elevations[comp.story] + comp.elevation
        w.place(
            product,
            _placement(
                (float(comp.point[0]), float(comp.point[1]), z),
                _rotation(comp.rotation),
                (0.0, 0.0, 1.0),
            ),
        )
        w.run(
            "spatial.assign_container",
            w.file,
            products=[product],
            relating_structure=storeys.get(comp.story) or storey_at(z),
        )

        type_class = _TYPE_CLASS.get(ifc_class)
        if type_class is not None:
            type_key = f"comp:{ctype.id}"
            if type_key not in ifc_types:
                ent = w.entity(type_class, ctype.id, f"archtype:{type_key}", predefined)
                ent.Description = ctype.name
                t_props = w.run("pset.add_pset", w.file, product=ent, name="SAEngine_Component")
                w.run(
                    "pset.edit_pset",
                    w.file,
                    pset=t_props,
                    properties={
                        "TypeId": ctype.id,
                        "TypeName": ctype.name,
                        "Category": ctype.category,
                        "Width_mm": float(ctype.width),
                        "Depth_mm": float(ctype.depth),
                        "Height_mm": float(ctype.height),
                        "Weight_kg": float(ctype.weight),
                        "Material": ctype.material,
                        **ctype.parameters,
                    },
                )
                ifc_types[type_key] = ent
            w.run(
                "type.assign_type",
                w.file,
                related_objects=[product],
                relating_type=ifc_types[type_key],
                should_map_representations=False,
            )

        comp_props = w.run("pset.add_pset", w.file, product=product, name="SAEngine_Component")
        w.run("pset.edit_pset", w.file, pset=comp_props, properties=_component_pset_props(ctype, comp))
        pset(
            product,
            {
                "Id": comp.id,
                "Type": ctype.id,
                "Category": ctype.category,
                "HostRoom": comp.hostRoom or "",
                "Rotation": float(comp.rotation),
                "Mirrored": bool(comp.mirrored),
                "Weight_kg": float(ctype.weight),
            },
        )
        ids[comp.id] = product.GlobalId
