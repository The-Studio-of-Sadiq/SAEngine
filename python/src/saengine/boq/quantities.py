"""The bill of quantities (``10 BOQ/boq.json``), measured from the building model (Part 10).

Part 10 never authors geometry: it measures ``06 BIM/bim.json`` with the object types of
``04 Objects`` and the materials of ``03 Materials``, and records the stamps of the three texts it
was measured from (``source``), so its editor can tell when they have changed since.

Items are grouped as concrete (m³, per material and element kind, with subtotals per story),
masonry (m³), reinforcement (kg, per rebar material and bar diameter), formwork (m², per element
kind) and structural steel (kg, per material and element kind). Every item keeps a breakdown by
element id. Units: the building model is in mm; quantities are in m, m², m³ and kg.

Measurement rules (stated in the document's notes too):

- concrete: slabs are measured over their whole outline and full thickness, less openings
  (clipped to the outline). Beams are measured between the faces of the columns they meet (at
  their ends, along their length, and at a column whose bottom is at the beam's top: a plinth or
  grade beam), and below the slab: the part of a beam, column or wall inside a slab's depth is the
  slab's. Columns run their full height less that slab depth; walls their whole length less wall
  openings (clipped to the wall). Nothing else is deducted where members meet (beam/beam,
  wall/column joints); special-structure members run node to node;
- longitudinal bars run the member's full length (beams centreline to centreline, into the
  columns) with a lap of 40 bar diameters at every joint between 12 m stock bars (a bar of
  12 m or less has none, 12 to 24 m one, ...). Stirrups and ties are measured at their centre
  line plus two 135° hooks of 10 diameters each, ``length / spacing + 1`` of them over the
  beam's clear span or the column's height; legs beyond two are cross-ties across the section
  depth. Meshes of slabs, walls, footings and stairs are ``area / spacing`` of bar per
  layer and direction, with the same laps. Bar mass is ``d² / 162`` kg/m (7850 kg/m³);
- formwork is the cast faces: beam sides and soffit, column perimeter by height, slab soffit and
  edges, wall faces, footing and block sides, stair soffit and risers. A face cast against another
  member is not formed: the slab soffit over beams, columns and walls, beam/column/wall faces
  within a slab's depth where the slab lies against them, and slab edges over beams, columns and
  walls;
- steel members weigh their profile area by their centreline length by the material's density.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from saengine.library import objects as o
from saengine.library.bim import (
    AreaElement,
    BeamElement,
    BlockElement,
    BuildingModel,
    ColumnElement,
    FootingElement,
    MemberElement,
    PileSolid,
    SlabElement,
    WallElement,
    foundation_solids,
    ground_level_stamp,
    source_stamp,
)
from saengine.library.labels import field_title
from saengine.library.materials import Category, Id, Material, MaterialLibrary
from saengine.library.objects import ObjectLibrary
from saengine.library.sections import profile_geometry
from saengine.library.substructure import Substructure

SCHEMA_ID = "saengine.boq/1"

STOCK_LENGTH = 12_000.0  # mm: one lap for every full stock length of bar
LAP = 40  # lap length [bar diameters]
HOOK = 10  # extension of a 135° hook [bar diameters]
STEEL_DENSITY = 7850.0  # kg/m³, for a steel material that gives none
TOLERANCE = 1.0  # mm
PROBE = 1.0  # mm: how far beside a face to look for the member cast against it

MM = 1e-3  # m per mm
MM2 = 1e-6  # m² per mm²
MM3 = 1e-9  # m³ per mm³

Group = Literal[
    "earthwork", "concrete", "masonry", "reinforcement", "formwork", "steel", "mep", "materials"
]
Unit = Literal["m3", "m2", "kg", "nr", "m", "cft", "bag", "l"]

#: The materials take-off of the concrete and the masonry's mortar (estimating practice in
#: Bangladesh and South Asia, not BNBC values): the dry volume of a nominal mix's ingredients
#: per m³ of wet concrete or mortar, the wet mortar in a m³ of brickwork, the loose bulk
#: densities that turn cement into kg and a design mix's sand and stone into volumes, the bag.
DRY_VOLUME_CONCRETE = 1.54
DRY_VOLUME_MORTAR = 1.30
BRICKWORK_WET_MORTAR = 0.23  # m³ of wet mortar per m³ of brickwork
CEMENT_DENSITY = 1440.0  # kg/m³
SAND_DENSITY = 1600.0  # kg/m³, loose
STONE_DENSITY = 1450.0  # kg/m³, loose stone chips
CEMENT_BAG = 50.0  # kg
CFT = 35.3147  # cubic feet per m³

#: The nominal mix assumed for a concrete with no mix in 03 Materials (cement : sand : stone by
#: volume), by f'c [MPa]: the nominal mixes of IS 456:2000 Table 9 (M10 1:3:6, M15 1:2:4, M20
#: 1:1.5:3), the richest one above M20, where a design mix is the practice. Estimating practice,
#: not BNBC values: enter the mix in 03 Materials to replace it.
ASSUMED_MIXES: tuple[tuple[float, tuple[float, float, float]], ...] = (
    (12.0, (1.0, 3.0, 6.0)),
    (17.0, (1.0, 2.0, 4.0)),
    (math.inf, (1.0, 1.5, 3.0)),
)

#: Earthwork and blinding of the foundations of 9 Substructure [mm].
WORKING_SPACE = 300.0  # around a foundation or tie beam, each side, to the excavation's face
BLINDING = 75.0  # lean concrete under foundations and tie beams
BLINDING_PROJECTION = 75.0  # of the blinding beyond the foundation's edges

#: Groups in the order of the bill, with the letter of their item codes.
GROUPS: dict[str, str] = {
    "earthwork": "E",
    "concrete": "C",
    "masonry": "M",
    "reinforcement": "R",
    "formwork": "F",
    "steel": "S",
    "mep": "P",
    "materials": "MT",
}

#: The measurement of the materials take-off, added when there is any.
MATERIALS_CONVENTIONS = [
    (
        "Materials: cement in kg (and in 50 kg bags), sand and stone chips in cft (1 m³ = "
        f"{CFT:g} cft) and water in litres, taken off the concrete and the masonry's mortar by "
        "the mixes in 03 Materials. A nominal mix (cement : sand : stone by volume) is shared out "
        f"of its dry volume, {DRY_VOLUME_CONCRETE:g} × the wet volume for concrete and "
        f"{DRY_VOLUME_MORTAR:g} × for mortar; brickwork takes {BRICKWORK_WET_MORTAR:g} m³ of wet "
        f"mortar per m³. Cement weighs {CEMENT_DENSITY:g} kg/m³ loose. A design mix gives kg per "
        f"m³; its sand and stone are turned into volumes at {SAND_DENSITY:g} and "
        f"{STONE_DENSITY:g} kg/m³ loose. Water from the water/cement ratio. These are estimating "
        "practice values, not BNBC values; no wastage is added, and bags are not rounded up."
    ),
]

#: Object kinds in the order of the bill, with their plural names for descriptions.
KINDS: dict[str, str] = {
    "excavation": "excavation",
    "backfill": "backfill",
    "blinding": "blinding",
    "footing": "footings",
    "pileCap": "pile caps",
    "pile": "piles",
    "raft": "rafts",
    "tieBeam": "tie beams",
    "column": "columns",
    "wall": "walls",
    "beam": "beams",
    "brace": "braces",
    "slab": "slabs",
    "staircase": "stairs",
    "lintel": "lintels",
    "solid": "solid blocks",
    "plinth": "equipment plinths",
    "tank": "water and septic tanks",
}

#: The note on a tank whose bars wait for its design (the workbench's Run All measures the bill
#: again once the plumbing report has designed the tanks: ``awaitsTankDesigns`` in boqDocument.ts).
TANK_BARS_PENDING = "its bars are not measured: it has no current design"

#: The measurement of the plumbing of 7 MEP, added when it has any tanks, risers or fixtures.
PLUMBING_CONVENTIONS = [
    (
        "Plumbing of 7 MEP: reinforced concrete tanks (overhead, underground, septic, rainwater) "
        "by their walls, partitions, base (with its toe) and roof at the thicknesses entered, "
        "else those the tank design proposes; formwork to their inside and outside faces, the "
        "base's edges and the roof's soffit; their bars by diameter from the tank's last design "
        "(the bars per m² of each panel + 10 % for laps), measured once the plumbing report has "
        "designed them. Ground tanks are dug with 300 mm working space each side. Soak wells and "
        "masonry or prefabricated tanks are not measured. Risers and stacks are measured "
        "vertically from the story they start at to their top story, at their entered or sized "
        "base diameter (branches and fittings are not measured); fixtures are counted by kind."
    ),
]

#: The measurement of the HVAC and electrical services of 7 MEP, added when there are any.
SERVICES_CONVENTIONS = [
    (
        "HVAC and electrical of 7 MEP, for the structure's coordination: ducts by system and "
        "size, measured along their plan path (risers vertically from the story they start at "
        "to their top story; ducts with no size entered are not measured); cable trays by width "
        "and side height along their path; rising mains (busbars, cable risers) vertically by "
        "size; plant and electrical equipment counted by kind (their weights are in the "
        "analysis, their bases are not measured). Lightning protection with the columns' "
        "reinforcement as down conductors: per down-conductor column a bonding terminal at the "
        "roof and an earth terminal at the base (welded to the continuous bars) and an earth "
        "inspection box recess, counted (number)."
    ),
]

#: The measurement of the MEP coordination items of 7 MEP, added when there are any.
MEP_CONVENTIONS = [
    (
        "Equipment plinths of 7 MEP: concrete of their footprint by their height, formwork to "
        "their four sides (no reinforcement measured). Sleeves and openings through beams, slabs "
        "and walls are counted by host kind and size (number), for the services' coordination; "
        "their concrete is not deducted (it is small), and the slab openings cut by shafts are "
        "not counted."
    ),
]

CONVENTIONS = [
    (
        "Concrete: slabs are measured over their whole outline and full thickness, less openings. "
        "Beams are measured between the faces of the columns they meet and below the slab: the part "
        "of a beam, column or wall within a slab's depth is measured with the slab. Columns run "
        "their full height and walls their whole length (less wall openings), each less that slab "
        "depth. Nothing else is deducted where members meet (beam/beam and wall/column joints); "
        "special-structure members are measured node to node and their areas over their whole "
        "outline, with no deduction where they meet."
    ),
    (
        "Longitudinal bars run the member's full length (beams centreline to centreline) with a lap "
        "of 40 bar diameters at every joint between 12 m stock lengths. Stirrups and ties are "
        "measured at their centre line plus two 135° hooks of 10 diameters, length / spacing + 1 of "
        "them. Meshes are area / spacing of bar per layer and direction. Bends, anchorages, chairs "
        "and wastage are not included; bar mass is d²/162 kg/m."
    ),
    (
        "Formwork is measured to the cast faces: beam sides and soffit, column perimeter by height, "
        "slab soffit and edges, wall faces, footing sides. Faces cast against another member are "
        "not formed (slab soffit over beams, columns and walls; their faces within the slab's "
        "depth; slab edges over them); nothing else is deducted where members meet."
    ),
]

#: The measurement of the foundations of 9 Substructure, added to the notes when there are any.
FOUNDATION_CONVENTIONS = [
    (
        "Foundations are measured from 9 Substructure (the footings of the building model are "
        "not): footings, pile caps and rafts over their plan by their thickness, formwork to "
        "their sides (and a raft's edges), bars as meshes over the plan. Piles: concrete of the "
        "full length below the cap (bored piles round, driven piles square of the given size), "
        "bars as for columns, moulds of driven precast piles on three faces (cast flat). Tie "
        "beams: concrete and stirrups between the faces of the foundations they tie, "
        "longitudinal bars centre to centre of the foundations, formwork to their two sides."
    ),
    (
        f"Earthwork: each foundation and tie beam is dug with vertical sides "
        f"{WORKING_SPACE:g} mm beyond its edges (working space), from the finished ground of "
        f"Project Settings → Foundation down to the underside of the blinding; where pits "
        f"overlap the overlap is measured once (each element's share scaled to suit). Blinding "
        f"(lean concrete) {BLINDING:g} mm thick, {BLINDING_PROJECTION:g} mm beyond the edges of "
        "foundations and tie beams. Backfill is the excavation less the foundations, tie beams "
        "and blinding below the ground; column stubs and pedestals below the ground are not "
        "deducted. No battered sides, dewatering, shoring, disposal of surplus spoil or bored "
        "pile spoil are measured."
    ),
]


def bar_mass(dia: float) -> float:
    """Mass of a bar [kg/m] of diameter ``dia`` [mm] (7850 kg/m³)."""
    return dia * dia / 162


def bar_length(length: float, dia: float) -> float:
    """A bar of ``length`` [mm] with a lap of 40 d at every joint between 12 m stock bars [mm]:
    none up to 12 m, one up to 24 m, ..."""
    joints = max(math.ceil(length / STOCK_LENGTH - 1e-9) - 1, 0)
    return length + joints * LAP * dia


def mesh_length(area: float, spacing: float, run: float, dia: float) -> float:
    """Total bar length [mm] of one mesh layer in one direction: ``area / spacing`` of bars that
    run ``run`` mm each, with their laps."""
    if area <= 0 or run <= 0:
        return 0.0
    return area / spacing * bar_length(run, dia) / run


def transverse_length(section: Polygon, cover: float, bars: o.Transverse, length: float) -> float:
    """Total length [mm] of the stirrups, ties or spiral of a section over ``length`` [mm]."""
    inner = section.buffer(-(cover + bars.dia / 2), join_style="mitre")
    if isinstance(inner, MultiPolygon):
        inner = max(inner.geoms, key=lambda p: p.area)
    if inner.is_empty or length <= 0:
        return 0.0
    loop = inner.exterior.length
    if bars.type == "spiral":
        return length / bars.spacing * math.hypot(loop, bars.spacing)
    count = math.floor(length / bars.spacing + 1e-9) + 1
    hooks = 2 * HOOK * bars.dia
    _, ymin, _, ymax = inner.bounds
    tie = ymax - ymin + hooks
    one = (loop + hooks if bars.legs >= 2 else tie) + max(bars.legs - 2, 0) * tie
    return count * one


# ─────────────────────────────────── the document ───────────────────────────────────


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class BoqSource(_Model):
    """The upstream revisions the bill was measured from (stamps of their texts)."""

    bim: str | None = Field(default=None, title="Building model", description="Stamp of bim.json.")
    objects: str | None = Field(
        default=None, title="Object types", description="Stamp of objects.json."
    )
    materials: str | None = Field(
        default=None, title="Materials", description="Stamp of materials.json."
    )
    substructure: str | None = Field(
        default=None, title="Substructure", description="Stamp of substructure.json."
    )
    mep: str | None = Field(default=None, title="MEP", description="Stamp of mep.json.")
    settings: str | None = Field(
        default=None,
        title="Project settings",
        description="Stamp of the ground level of project-settings.json, the only setting the "
        "bill depends on (the earthwork is dug from it): other settings edits leave it current.",
    )


class BreakdownEntry(_Model):
    """The share of one element in an item."""

    element: str
    story: Id | None = None
    detail: str | None = Field(
        default=None, description="Which part of the element: longitudinal bars, soffit, ..."
    )
    quantity: float


class BoqItem(_Model):
    code: str
    group: Group
    description: str
    quantity: float
    unit: Unit
    material: Id | None = None
    kind: str | None = Field(default=None, description="Object kind measured (column, beam, ...).")
    diameter: float | None = Field(default=None, description="Bar diameter [mm].")
    byStory: dict[str, float] = Field(default_factory=dict, title="By story")
    breakdown: list[BreakdownEntry] = Field(default_factory=list)


class BillOfQuantities(_Model):
    schema_: Literal["saengine.boq/1"] = Field(default=SCHEMA_ID, alias="schema")
    source: BoqSource = Field(default_factory=BoqSource)
    items: list[BoqItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    problems: list[str] = Field(
        default_factory=list,
        description="What the bill could not measure (no bars on a type, a tank not designed, "
        "a mortar with no mix, ...): while there are any the bill is incomplete.",
    )

    def total(self, group: str, unit: str | None = None) -> float:
        return sum(i.quantity for i in self.items if i.group == group and unit in (None, i.unit))


# ─────────────────────────────────── measuring ───────────────────────────────────


@dataclass
class _Line:
    group: str
    description: str
    unit: str
    order: tuple[Any, ...]
    material: str | None
    kind: str | None
    diameter: float | None
    amounts: dict[tuple[str, str | None, str | None], float] = field(default_factory=dict)


class _Bill:
    def __init__(self) -> None:
        self.lines: dict[tuple[Any, ...], _Line] = {}

    def add(
        self,
        group: str,
        key: tuple[Any, ...],
        description: str,
        unit: str,
        element: str,
        quantity: float,
        *,
        story: str | None = None,
        detail: str | None = None,
        material: str | None = None,
        kind: str | None = None,
        diameter: float | None = None,
    ) -> None:
        if quantity <= 0:
            return
        line = self.lines.get((group, *key))
        if line is None:
            line = self.lines[(group, *key)] = _Line(
                group, description, unit, key, material, kind, diameter
            )
        at = (element, story, detail)
        line.amounts[at] = line.amounts.get(at, 0.0) + quantity

    def items(self, types: dict[str, str] | None = None) -> list[BoqItem]:
        """The items of the bill; ``types``: the object type of each element id, the detail of
        its breakdown entries that have none (the section it was measured with)."""
        types = types or {}
        groups = list(GROUPS)
        lines = sorted(self.lines.values(), key=lambda li: (groups.index(li.group), li.order))
        items = []
        numbers: dict[str, int] = {}
        for line in lines:
            numbers[line.group] = numbers.get(line.group, 0) + 1
            stories: dict[str, float] = {}
            for (_, story, _), amount in line.amounts.items():
                if story is not None:
                    stories[story] = stories.get(story, 0.0) + amount
            items.append(
                BoqItem(
                    code=f"{GROUPS[line.group]}.{numbers[line.group]:02d}",
                    group=line.group,  # type: ignore[arg-type]
                    description=line.description,
                    quantity=round(sum(line.amounts.values()), 3),
                    unit=line.unit,  # type: ignore[arg-type]
                    material=line.material,
                    kind=line.kind,
                    diameter=line.diameter,
                    byStory={s: round(q, 3) for s, q in stories.items()},
                    breakdown=[
                        BreakdownEntry(
                            element=e,
                            story=s,
                            detail=d if d is not None or e not in types else f"type {types[e]}",
                            quantity=round(q, 3),
                        )
                        for (e, s, d), q in line.amounts.items()
                    ],
                )
            )
        return items


def _kind_order(kind: str) -> int:
    return list(KINDS).index(kind) if kind in KINDS else len(KINDS)


def _profile_label(profile: Any) -> str:
    """A steel profile that is not a table section, by its dimensions [mm]."""
    p = profile.model_dump() if hasattr(profile, "model_dump") else dict(profile)
    match p.get("shape"):
        case "I":
            dims = (p["overallDepth"], p["overallWidth"], p["webThickness"], p["flangeThickness"])
        case "U":
            dims = (p["depth"], p["flangeWidth"], p["webThickness"], p["flangeThickness"])
        case "L":
            dims = (p["depth"], p["width"], p["thickness"])
        case "rectangleHollow":
            dims = (p["yDim"], p["xDim"], p["wallThickness"])
        case "circleHollow":
            dims = (2 * p["radius"], p["wallThickness"])
        case _:
            return str(p.get("shape"))
    return f"{p['shape']} " + "x".join(f"{d:g}" for d in dims)


def _perimeter(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1).sum())


def _area_3d(points: np.ndarray) -> float:
    """Area of a flat polygon in space [mm²] (Newell's method)."""
    origin = points[0]
    normal = np.zeros(3)
    for a, b in zip(points, np.roll(points, -1, axis=0), strict=True):
        normal += np.cross(a - origin, b - origin)
    return float(np.linalg.norm(normal)) / 2


def _span(points: np.ndarray) -> float:
    """The largest distance between two corners of a polygon [mm]: the run of its bars."""
    return float(max(np.linalg.norm(a - b) for a in points for b in points))


def _overlap(bottom: float, top: float, other_bottom: float, other_top: float) -> float:
    """How far two elevation ranges overlap [mm]."""
    return max(0.0, min(top, other_top) - max(bottom, other_bottom))


def _segments(geometry: BaseGeometry) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """The straight segments of the lines in ``geometry``."""
    if geometry.is_empty:
        return []
    if hasattr(geometry, "geoms"):
        return [s for g in geometry.geoms for s in _segments(g)]
    if geometry.geom_type not in ("LineString", "LinearRing"):
        return []
    coords = [(float(x), float(y)) for x, y, *_ in geometry.coords]
    return list(itertools.pairwise(coords))


def _covered(lines: BaseGeometry, owner: BaseGeometry, region: BaseGeometry) -> float:
    """The length [mm] of the faces ``lines`` of ``owner`` that ``region`` lies against: their
    pieces inside or on ``region`` whose outer side (away from ``owner``) is in ``region``."""
    total = 0.0
    for (ax, ay), (bx, by) in _segments(lines.intersection(region)):
        length = math.hypot(bx - ax, by - ay)
        if length < TOLERANCE:
            continue
        nx, ny = -(by - ay) / length, (bx - ax) / length
        mx, my = (ax + bx) / 2, (ay + by) / 2
        probe = Point(mx + nx * PROBE, my + ny * PROBE)
        if owner.contains(probe):
            probe = Point(mx - nx * PROBE, my - ny * PROBE)
        if region.contains(probe):
            total += length
    return total


def wall_piers(length: float, height: float, openings: list[Any]) -> int:
    """The piers of a wall ``length`` by ``height`` [mm]: its solid lengths between the openings
    that split it (taller than saengine.design.wall_forces.MIN_OPENING of its height, as the
    wall forces split it), at least 1."""
    from saengine.design.wall_forces import MIN_OPENING

    cuts = sorted(
        (max(float(w.offset), 0.0), min(float(w.offset + w.width), length))
        for w in openings
        if min(float(w.sill + w.height), height) - max(float(w.sill), 0.0)
        >= MIN_OPENING * height - 1e-6
    )
    piers, at = 0, 0.0
    for start, end in cuts:
        if end <= start:
            continue
        if start > at + 1e-6:
            piers += 1
        at = max(at, end)
    if length > at + 1e-6:
        piers += 1
    return max(piers, 1)


def _rectangle(start: list[float], end: list[float], width: float) -> Polygon:
    """The plan of a straight member of ``width`` from ``start`` to ``end``."""
    return LineString([start, end]).buffer(width / 2, cap_style="flat")


def _faces(start: list[float], end: list[float], width: float) -> BaseGeometry:
    """The two side lines of a straight member of ``width``."""
    axis = LineString([start, end])
    return unary_union([axis.offset_curve(width / 2), axis.offset_curve(-width / 2)])


@dataclass
class _Plate:
    """A slab as the members under and through it see it: its plan net of openings and its
    elevation range, with the plans of the members in its depth (``supports``)."""

    polygon: BaseGeometry
    bottom: float
    top: float
    supports: list[BaseGeometry] = field(default_factory=list)
    under: list[BaseGeometry] = field(default_factory=list)


def _noun(label: str) -> str:
    """A label inside a description: its first letter lower case, unless it starts an
    abbreviation ("VRF outdoor unit", "UPS")."""
    return label if label[1:2].isupper() else label[:1].lower() + label[1:]


class _Measure:
    def __init__(
        self,
        building: BuildingModel,
        objects: ObjectLibrary,
        materials: MaterialLibrary,
        substructure: Substructure | None = None,
        ground_level: float = 0.0,
        mep: Any = None,
    ) -> None:
        self.building = building
        self.mep = mep
        self.substructure = substructure
        self.ground_level = ground_level
        self.drawn_footings: list[str] = []
        self.types = {t.id: t for t in objects.objects}
        self.materials = {m.id: m for m in materials.materials}
        self.library = materials
        self.bill = _Bill()
        self.notes: list[str] = []
        self.unreinforced: dict[str, list[str]] = {}
        self.bad_rebar: set[str] = set()
        self.sections: dict[str, Polygon] = {}
        self.steel_sections: dict[str, tuple[str | None, float]] = {}
        self.footprints: list[tuple[float, float, BaseGeometry]] = []
        self.plates: dict[str, _Plate] = {}

    # ── lookups ──

    def story_at(self, elevation: float) -> str | None:
        return next(
            (s.id for s in self.building.stories if abs(s.elevation - elevation) < TOLERANCE),
            None,
        )

    def section(self, object_type: Any) -> Polygon:
        """The object type's profile as a polygon about its centroid [mm]."""
        if object_type.id not in self.sections:
            polygon = profile_geometry(object_type.profile).geom
            c = polygon.centroid
            self.sections[object_type.id] = affinity.translate(polygon, -c.x, -c.y)
        return self.sections[object_type.id]

    def object_type(self, element_id: str, type_id: str, kinds: tuple[type, ...], what: str) -> Any:
        object_type = self.types.get(type_id)
        if object_type is None:
            self.notes.append(
                f"{element_id}: object type '{type_id}' is not in 04 Objects; not measured."
            )
            return None
        if not isinstance(object_type, kinds):
            self.notes.append(
                f"{element_id}: object type '{type_id}' is a {object_type.kind}, not a {what}; "
                "not measured."
            )
            return None
        return object_type

    def material(self, element_id: str, object_type: Any) -> Material | None:
        material = self.materials.get(object_type.material)
        if material is None:
            self.notes.append(
                f"{element_id}: material '{object_type.material}' of object type "
                f"'{object_type.id}' is not in 03 Materials; not measured."
            )
        return material

    # ── items ──

    def concrete(
        self, element: str, material: Material, kind: str, volume: float, story: str | None
    ) -> None:
        group = "masonry" if material.category == Category.MASONRY else "concrete"
        noun = "Masonry" if group == "masonry" else "Concrete"
        self.bill.add(
            group,
            (_kind_order(kind), material.id),
            f"{noun} {material.id} in {KINDS.get(kind, kind)}",
            "m3",
            element,
            volume * MM3,
            story=story,
            material=material.id,
            kind=kind,
        )

    def formwork(
        self, element: str, kind: str, area: float, story: str | None, detail: str
    ) -> None:
        self.bill.add(
            "formwork",
            (_kind_order(kind),),
            f"Formwork to {KINDS.get(kind, kind)}",
            "m2",
            element,
            area * MM2,
            story=story,
            detail=detail,
            kind=kind,
        )

    def steel(
        self,
        element: str,
        material: Material,
        kind: str,
        mass: float,
        story: str | None,
        section: str | None = None,
        per_metre: float | None = None,
        detail: str | None = None,
    ) -> None:
        """Structural steel [kg], one line per material, element kind and section."""
        what = f"{section} ({per_metre:.1f} kg/m)" if section and per_metre else section
        self.bill.add(
            "steel",
            (material.id, _kind_order(kind), section or ""),
            f"Structural steel {material.id}"
            + (f", {what}" if what else "")
            + f" in {KINDS.get(kind, kind)}",
            "kg",
            element,
            mass,
            story=story,
            detail=detail,
            material=material.id,
            kind=kind,
        )

    def steel_section(self, object_type: Any) -> tuple[str | None, float]:
        """The steel member type's section name (the table's, else the profile's dimensions)
        and its nominal area [mm²]."""
        key = f"steel:{object_type.id}"
        if key not in self.steel_sections:
            from saengine.library.steel_sections import section_of_profile

            try:
                s = section_of_profile(object_type.profile)
            except (TypeError, ValueError, KeyError):
                self.steel_sections[key] = (None, self.section(object_type).area)
            else:
                name = s.name if s.name != "custom" else _profile_label(object_type.profile)
                self.steel_sections[key] = (name, s.A)
        return self.steel_sections[key]

    def rebar(
        self,
        element: str,
        material_id: str,
        dia: float,
        length: float,
        story: str | None,
        detail: str,
    ) -> None:
        bars = self.materials.get(material_id)
        if (bars is None or bars.category != Category.REBAR) and material_id not in self.bad_rebar:
            self.bad_rebar.add(material_id)
            self.notes.append(
                f"Reinforcement material '{material_id}' is not a rebar material in 03 Materials; "
                "its bars are listed under that id."
            )
        self.bill.add(
            "reinforcement",
            (material_id, dia),
            f"Reinforcement {material_id}, {dia:g} mm bars",
            "kg",
            element,
            length * MM * bar_mass(dia),
            story=story,
            detail=detail,
            material=material_id,
            diameter=dia,
        )

    def no_bars(self, object_type: Any, element: str) -> None:
        self.unreinforced.setdefault(object_type.id, []).append(element)

    # ── members ──

    def linear(
        self,
        element: str,
        object_type: Any,
        length: float,
        clear: float,
        story: str | None,
        *,
        count: int = 1,
        formwork: bool = True,
        kind: str | None = None,
        less: tuple[float, float] = (0.0, 0.0),
        spans: tuple[float, ...] = (),
    ) -> None:
        """A beam, column, brace or pile: ``length`` node to node, ``clear`` between supports
        (in ``spans``, when there are several, each with its own stirrups); ``less``: the
        concrete [mm³] and formwork [mm²] within slabs, measured with them."""
        kind = kind or object_type.kind
        material = self.material(element, object_type)
        if material is None:
            return
        if material.category == Category.STEEL:
            # Integrator glue: structural steel by section, kg/m (the table section's nominal
            # area, saengine.library.steel_sections) × the centreline length.
            density = material.mechanical.density or STEEL_DENSITY
            label, area = self.steel_section(object_type)
            per_metre = area * MM2 * density
            mass = count * per_metre * length * MM
            detail = f"{count * length * MM:.2f} m × {per_metre:.2f} kg/m"
            self.steel(element, material, kind, mass, story, label, per_metre, detail)
            return
        section = self.section(object_type)
        if material.category not in (Category.CONCRETE, Category.MASONRY):
            self.notes.append(
                f"{element}: members of {material.category.value} ('{material.id}') are not "
                "measured."
            )
            return
        volume = max(count * section.area * clear - less[0], 0.0)
        self.concrete(element, material, kind, volume, story)
        if material.category != Category.CONCRETE:
            return
        if formwork:
            perimeter = section.exterior.length
            if kind == "column":
                area = max(count * perimeter * clear - less[1], 0.0)
                self.formwork(element, kind, area, story, "sides")
            else:
                xmin, _, xmax, _ = section.bounds
                exposed = perimeter - (xmax - xmin)  # all but the top
                area = max(count * exposed * clear - less[1], 0.0)
                self.formwork(element, kind, area, story, "sides and soffit")
        reinforcement = getattr(object_type, "reinforcement", None)
        if reinforcement is None:
            self.no_bars(object_type, element)
            return
        for bars in reinforcement.longitudinal:
            total = count * bars.count * bar_length(length, bars.dia)
            self.rebar(element, reinforcement.material, bars.dia, total, story, "longitudinal")
        transverse = reinforcement.transverse
        if transverse is not None:
            total = count * sum(
                transverse_length(section, reinforcement.cover, transverse, span)
                for span in (spans or (clear,))
            )
            self.rebar(
                element, reinforcement.material, transverse.dia, total, story, f"{transverse.type}s"
            )

    def columns_at(self, bottom: float, top: float) -> BaseGeometry:
        """The plans of the columns a beam from ``bottom`` to ``top`` meets: those through its
        depth, and those standing on it (a plinth or grade beam at a column's bottom)."""
        return unary_union(
            [f for b, t, f in self.footprints if b - TOLERANCE <= top and t > bottom + TOLERANCE]
        )

    def in_slabs(
        self,
        plan: BaseGeometry,
        faces: BaseGeometry,
        owner: BaseGeometry,
        bottom: float,
        top: float,
    ) -> tuple[float, float]:
        """The concrete [mm³] and formwork [mm²] of a member of ``plan`` from ``bottom`` to ``top``
        that lie within slabs (measured with the slabs), and record the member under each slab.
        ``faces``: the member's formed side lines; ``owner``: its whole plan."""
        volume = form = 0.0
        for plate in self.plates.values():
            depth = _overlap(bottom, top, plate.bottom, plate.top)
            if depth <= TOLERANCE or not plan.intersects(plate.polygon):
                continue
            volume += plan.intersection(plate.polygon).area * depth
            form += _covered(faces, owner, plate.polygon) * depth
            plate.supports.append(plan)
            if bottom < plate.bottom - TOLERANCE:
                plate.under.append(plan)
        return volume, form

    # ── planar members ──

    def planar_bars(
        self,
        element: str,
        object_type: Any,
        area: float,
        runs: tuple[float, float],
        story: str | None,
    ) -> None:
        reinforcement = object_type.reinforcement
        if reinforcement is None:
            self.no_bars(object_type, element)
            return
        layers = [
            ("bottom X", reinforcement.bottomX, runs[0]),
            ("bottom Y", reinforcement.bottomY, runs[1]),
            ("top X", reinforcement.topX, runs[0]),
            ("top Y", reinforcement.topY, runs[1]),
        ]
        for detail, mesh, run in layers:
            if mesh is not None:
                total = mesh_length(area, mesh.spacing, run, mesh.dia)
                self.rebar(element, reinforcement.material, mesh.dia, total, story, detail)

    def wall_bars(
        self,
        element: str,
        object_type: o.Wall,
        area: float,
        runs: tuple[float, float],
        story: str | None,
        piers: int = 1,
    ) -> None:
        """``runs``: the length of the vertical and of the horizontal bars [mm]; ``piers``: the
        piers the openings split the wall into (end bars at both ends of each, as the design
        lays them out, saengine.design.walls.pier_section)."""
        reinforcement = object_type.reinforcement
        if reinforcement is None:
            self.no_bars(object_type, element)
            return
        boundary = getattr(reinforcement, "boundary", None)
        # End bars replace the vertical web bars over their length at each end.
        ends = 2 * piers * boundary.length * runs[0] if boundary is not None else 0.0
        for detail, mesh, run, face in (
            ("vertical", reinforcement.vertical, runs[0], max(area - ends, 0.0)),
            ("horizontal", reinforcement.horizontal, runs[1], area),
        ):
            if mesh is not None:
                total = reinforcement.layers * mesh_length(face, mesh.spacing, run, mesh.dia)
                self.rebar(element, reinforcement.material, mesh.dia, total, story, detail)
        if boundary is not None and runs[0] > 0:
            # Integrator glue: the end bars and their hoops (saengine.design.walls), both ends
            # of every pier.
            total = 2 * piers * boundary.count * bar_length(runs[0], boundary.dia)
            self.rebar(element, reinforcement.material, boundary.dia, total, story, "end bars")
            hoop = boundary.hoop
            if hoop is not None:
                cover = float(reinforcement.cover)
                across = float(object_type.thickness) - 2 * cover + 2 * HOOK * hoop.dia
                along = float(boundary.length) - cover + 2 * HOOK * hoop.dia
                one = hoop.legsAcross * across + hoop.legsAlong * along
                count = math.floor(runs[0] / hoop.spacing + 1e-9) + 1
                total = 2 * piers * count * one
                self.rebar(element, reinforcement.material, hoop.dia, total, story, "end hoops")

    def slab(
        self,
        element: str,
        object_type: o.Slab,
        area: float,
        soffit: float,
        edges: float,
        runs: tuple[float, float],
        story: str | None,
    ) -> None:
        """A slab of ``area`` [mm²]; ``soffit`` [mm²] and ``edges`` [mm] are its formed parts."""
        material = self.material(element, object_type)
        if material is None:
            return
        if material.category not in (Category.CONCRETE, Category.MASONRY):
            self.notes.append(f"{element}: slabs of {material.category.value} are not measured.")
            return
        self.concrete(element, material, "slab", area * object_type.thickness, story)
        if material.category != Category.CONCRETE:
            return
        self.formwork(element, "slab", soffit, story, "soffit")
        self.formwork(element, "slab", edges * object_type.thickness, story, "edges")
        self.planar_bars(element, object_type, area, runs, story)

    def wall(
        self,
        element: str,
        object_type: o.Wall,
        area: float,
        runs: tuple[float, float],
        story: str | None,
        less: tuple[float, float] = (0.0, 0.0),
        piers: int = 1,
    ) -> None:
        """A wall of face ``area`` [mm²]; ``less``: its concrete [mm³] and formwork [mm²] within
        slabs; ``piers``: see :meth:`wall_bars`."""
        material = self.material(element, object_type)
        if material is None:
            return
        if material.category not in (Category.CONCRETE, Category.MASONRY):
            self.notes.append(f"{element}: walls of {material.category.value} are not measured.")
            return
        volume = max(area * object_type.thickness - less[0], 0.0)
        self.concrete(element, material, "wall", volume, story)
        if material.category == Category.CONCRETE:
            self.formwork(element, "wall", max(2 * area - less[1], 0.0), story, "both faces")
            self.wall_bars(element, object_type, area, runs, story, piers)

    # ── the building model ──

    def run(self) -> None:
        building = self.building
        for e in building.elements:
            if isinstance(e, ColumnElement):
                t = self.types.get(e.type)
                if isinstance(t, o.Column):
                    shape = affinity.rotate(self.section(t), e.rotation, origin=(0, 0))
                    shape = affinity.translate(shape, *e.position)
                    self.footprints.append((e.bottom, e.top, shape))

        wall_openings: dict[str, list[Any]] = {}
        for w in building.additions.wallOpenings:
            wall_openings.setdefault(w.host, []).append(w)
        slab_openings: dict[str, list[Any]] = {}
        for s in building.additions.slabOpenings:
            slab_openings.setdefault(s.host, []).append(s)

        slabs: list[tuple[SlabElement, o.Slab]] = []
        for e in building.elements:
            if isinstance(e, SlabElement):
                t = self.object_type(e.id, e.type, (o.Slab,), "slab")
                if t:
                    slabs.append((e, t))
                    material = self.materials.get(t.material)
                    if material and material.category in (Category.CONCRETE, Category.MASONRY):
                        plan = self.slab_plan(e, slab_openings.get(e.id, []))
                        top = e.elevation
                        self.plates[e.id] = _Plate(plan, top - t.thickness, top)

        for e in building.elements:
            match e:
                case ColumnElement():
                    t = self.object_type(e.id, e.type, (o.Column,), "column")
                    if t:
                        height = e.top - e.bottom
                        plan = affinity.rotate(self.section(t), e.rotation, origin=(0, 0))
                        plan = affinity.translate(plan, *e.position)
                        less = self.in_slabs(plan, plan.exterior, plan, e.bottom, e.top)
                        story = self.story_at(e.top)
                        self.linear(e.id, t, height, height, story, less=less)
                case BeamElement():
                    t = self.object_type(e.id, e.type, (o.Beam,), "beam")
                    if t:
                        self.beam(e, t)
                case WallElement():
                    t = self.object_type(e.id, e.type, (o.Wall,), "wall")
                    if t:
                        length, height = math.dist(e.start, e.end), e.top - e.bottom
                        face = box(0, 0, length, height)
                        holes = unary_union(
                            [
                                box(w.offset, w.sill, w.offset + w.width, w.sill + w.height)
                                for w in wall_openings.get(e.id, [])
                            ]
                        )
                        area = face.difference(holes).area
                        plan = _rectangle(e.start, e.end, t.thickness)
                        faces = _faces(e.start, e.end, t.thickness)
                        less = self.in_slabs(plan, faces, plan, e.bottom, e.top)
                        story = self.story_at(e.top)
                        piers = wall_piers(length, height, wall_openings.get(e.id, []))
                        self.wall(e.id, t, area, (height, length), story, less, piers)
                case FootingElement() if self.substructure is not None:
                    self.drawn_footings.append(e.id)  # 9 Substructure has the foundations
                case FootingElement():
                    t = self.object_type(e.id, e.type, (o.Footing, o.PileCap), "footing")
                    if t:
                        self.footing(e.id, t, self.story_at(e.elevation))
                case MemberElement():
                    t = self.object_type(e.id, e.type, (o.Beam, o.Column, o.Brace), "member")
                    if t:
                        length = math.dist(e.start, e.end)
                        self.linear(e.id, t, length, length, None)
                case AreaElement():
                    t = self.object_type(e.id, e.type, (o.Slab, o.Wall), "slab or wall")
                    if t:
                        self.area(e, t)
                case BlockElement():
                    t = self.object_type(e.id, e.type, (o.Solid,), "solid")
                    if t:
                        self.block(e, t)

        # Slabs last, once the members cast against them are known.
        for e, t in slabs:
            self.building_slab(e, t, slab_openings.get(e.id, []))

        for member in building.additions.members:
            t = self.object_type(member.id, member.type, (o.Beam, o.Column, o.Brace), "member")
            if t:
                start = (member.x1, member.y1, member.z1)
                end = (member.x2, member.y2, member.z2)
                length = math.dist(start, end)
                self.linear(member.id, t, length, length, None)
        for stair in building.additions.stairs:
            t = self.object_type(stair.id, stair.type, (o.Staircase,), "staircase")
            if t:
                self.stair(stair, t)
        self.lintels()
        self.slab_studs(slabs)
        if self.substructure is not None:
            self.foundations(self.substructure)

    @staticmethod
    def slab_plan(e: SlabElement, openings: list[Any]) -> BaseGeometry:
        """The slab's plan less its openings (each clipped to the slab by the difference)."""
        holes = [
            affinity.translate(
                affinity.rotate(
                    box(-s.xDim / 2, -s.yDim / 2, s.xDim / 2, s.yDim / 2), s.rotation, origin=(0, 0)
                ),
                s.x,
                s.y,
            )
            for s in openings
        ]
        outline = Polygon(e.boundary).buffer(0)
        return outline.difference(unary_union(holes)) if holes else outline

    def beam(self, e: BeamElement, t: o.Beam) -> None:
        """A beam between the faces of the columns it meets, below the slabs over it."""
        xmin, ymin, xmax, ymax = self.section(t).bounds
        width, depth = xmax - xmin, ymax - ymin
        bottom, top = e.elevation - depth, e.elevation
        columns = self.columns_at(bottom, top)
        length = math.dist(e.start, e.end)
        clear_axis = LineString([e.start, e.end]).difference(columns) if length else LineString()
        spans = tuple(s.length for s in getattr(clear_axis, "geoms", [clear_axis]))
        clear = clear_axis.length
        whole = _rectangle(e.start, e.end, width) if length else Polygon()
        plan = whole.difference(columns)
        faces = _faces(e.start, e.end, width).difference(columns) if length else LineString()
        less = self.in_slabs(plan, faces, whole, bottom, top)
        story = self.story_at(e.elevation)
        self.linear(e.id, t, length, clear, story, less=less, spans=spans)

    def building_slab(self, e: SlabElement, t: o.Slab, openings: list[Any]) -> None:
        """A slab over its whole outline less openings; its soffit is formed except over the
        members under it, its edges except where they lie over a member."""
        plate = self.plates.get(e.id)
        plan = plate.polygon if plate else self.slab_plan(e, openings)
        area = plan.area
        soffit, edges = area, plan.boundary.length
        if plate:
            soffit -= plan.intersection(unary_union(plate.under)).area if plate.under else 0.0
            if plate.supports:
                edges = plan.boundary.difference(
                    unary_union(plate.supports).buffer(TOLERANCE)
                ).length
        outline = np.array(e.boundary, dtype=float)
        runs = (float(np.ptp(outline[:, 0])), float(np.ptp(outline[:, 1])))
        self.slab(e.id, t, area, max(soffit, 0.0), edges, runs, self.story_at(e.elevation))

    def footing(self, element: str, t: o.Footing | o.PileCap, story: str | None) -> None:
        material = self.material(element, t)
        if material is None:
            return
        if material.category != Category.CONCRETE:
            self.notes.append(f"{element}: footings of {material.category.value} are not measured.")
            return
        kind = t.kind
        self.concrete(element, material, kind, t.length * t.width * t.thickness, story)
        self.formwork(element, kind, 2 * (t.length + t.width) * t.thickness, story, "sides")
        self.planar_bars(element, t, t.length * t.width, (t.length, t.width), story)
        if isinstance(t, o.PileCap) and t.pileCount and not t.pile:
            self.notes.append(
                f"{element}: pile cap type '{t.id}' has {t.pileCount} piles but no pile type; "
                "its piles are not measured."
            )
        elif isinstance(t, o.PileCap) and t.pile and t.pileCount:
            pile = self.types.get(t.pile)
            if not isinstance(pile, o.Pile):
                self.notes.append(
                    f"{element}: pile type '{t.pile}' of pile cap type '{t.id}' is not a pile in "
                    "04 Objects; its piles are not measured."
                )
            else:
                self.linear(
                    element,
                    pile,
                    pile.length,
                    pile.length,
                    story,
                    count=t.pileCount,
                    formwork=False,
                    kind="pile",
                )

    def area(self, e: AreaElement, t: o.Slab | o.Wall) -> None:
        outline = np.array(e.outline, dtype=float)
        area = _area_3d(outline)
        perimeter = _perimeter(outline)
        for opening in e.openings:
            hole = np.array(opening, dtype=float)
            area -= _area_3d(hole)
            perimeter += _perimeter(hole)
        area = max(area, 0.0)
        span = _span(outline)
        if isinstance(t, o.Slab):
            self.slab(e.id, t, area, area, perimeter, (span, span), None)
        else:
            self.wall(e.id, t, area, (span, span), None)

    def block(self, e: BlockElement, t: o.Solid) -> None:
        material = self.material(e.id, t)
        if material is None:
            return
        if material.category not in (Category.CONCRETE, Category.MASONRY):
            self.notes.append(f"{e.id}: blocks of {material.category.value} are not measured.")
            return
        outline = np.array(e.outline, dtype=float)
        self.concrete(e.id, material, "solid", _area_3d(outline) * e.thickness, None)
        if material.category == Category.CONCRETE:
            self.formwork(e.id, "solid", _perimeter(outline) * e.thickness, None, "sides")

    def stair(self, stair: Any, t: o.Staircase) -> None:
        """A waist-slab flight, shaped as the IFC export shapes it (``saengine.library.ifc``)."""
        levels = {s.id: s.elevation for s in self.building.stories}
        if stair.base not in levels or stair.top not in levels:
            return  # reported by check_additions
        rise = levels[stair.top] - levels[stair.base]
        material = self.material(stair.id, t)
        if rise <= 0 or material is None:
            return
        if material.category != Category.CONCRETE:
            self.notes.append(f"{stair.id}: stairs of {material.category.value} are not measured.")
            return
        n = max(1, round(rise / t.riser))
        riser, going = rise / n, float(t.tread)
        width = float(t.flightWidth)
        story = stair.base
        # A straight stair is one flight; a dog-legged one two flights of ceil(n/2) and
        # floor(n/2) risers with a half landing between them (as saengine.design.stairs).
        dog_legged = getattr(t, "arrangement", "straight") == "dogLegged" and n >= 2
        flights = [(n + 1) // 2, n // 2] if dog_legged else [n]
        slope = 0.0
        for k in flights:
            drop = float(t.waistThickness) * math.hypot(riser, going) / going
            foot = drop * going / riser
            points = [(0.0, 0.0)]
            for i in range(k):
                points += [(i * going, (i + 1) * riser), ((i + 1) * going, (i + 1) * riser)]
            points += [(k * going, k * riser - drop), (min(foot, k * going), 0.0)]
            self.concrete(stair.id, material, "staircase", Polygon(points).area * width, story)
            slope += math.hypot(k * going, k * riser)
        self.formwork(stair.id, "staircase", slope * width, story, "soffit")
        self.formwork(stair.id, "staircase", n * riser * width, story, "risers")
        landing_area = 0.0
        if dog_legged:
            depth = float(t.landingLength or width)
            span = 2 * width + float(getattr(t, "wellWidth", 0.0) or 0.0)
            thick = float(t.landingThickness or t.waistThickness)
            landing_area = depth * span
            self.concrete(stair.id, material, "staircase", landing_area * thick, story)
            self.formwork(stair.id, "staircase", landing_area, story, "landing soffit")
        reinforcement = t.reinforcement
        if reinforcement is None:
            self.no_bars(t, stair.id)
            return
        layers = [
            ("main", reinforcement.main, slope, slope * width),
            ("distribution", reinforcement.distribution, width, slope * width),
        ]
        if getattr(reinforcement, "top", None) is not None:
            # Top bars over continuous ends: a quarter of the flight from each such end.
            ends = (t.bottomEnd == "continuous") + (t.topEnd == "continuous")
            run = slope / 4
            layers.append(("top", reinforcement.top, run, ends * run * width))
        if landing_area > 0:
            landing = getattr(reinforcement, "landing", None) or reinforcement.main
            layers += [
                ("landing", landing, landing_area / depth, landing_area),
                ("landing distribution", reinforcement.distribution, depth, landing_area),
            ]
        for detail, mesh, run, area in layers:
            total = mesh_length(area, mesh.spacing, run, mesh.dia)
            if total > 0:
                self.rebar(stair.id, reinforcement.material, mesh.dia, total, story, detail)

    # ── lintels and punching reinforcement (integrator glue) ──

    def lintels(self) -> None:
        """The lintels over the openings of masonry and partition walls, sized and reinforced
        as :func:`saengine.design.lintels.lintels_of` designs them (the default gravity
        combinations): concrete b h (clear + 2 bearings), soffit and side formwork, the bars
        over that length, links at their spacing."""
        if not self.building.additions.wallOpenings:
            return
        from saengine.design import lintels as lintel_design

        try:
            found = lintel_design.lintels_of(
                self.building,
                self.types,
                self.materials,
                None,
                concrete=self.library.default_concrete(),
                steel=self.library.default_rebar(),
            )
        except (ValueError, KeyError, AttributeError, TypeError, ArithmeticError) as error:
            self.notes.append(f"Lintels not measured: {error}.")
            return
        walls = {e.id: e for e in self.building.elements if isinstance(e, WallElement)}
        for lintel in found["elements"]:
            material = self.materials.get(lintel["concrete"])
            if material is None:
                continue
            host = walls.get(lintel.get("host"))
            story = self.story_at(host.bottom) if host is not None else None
            length = float(lintel["clear"]) + 2 * lintel_design.BEARING
            b, h = float(lintel["b"]), float(lintel["h"])
            self.concrete(lintel["id"], material, "lintel", b * h * length, story)
            self.formwork(lintel["id"], "lintel", float(lintel["clear"]) * b, story, "soffit")
            self.formwork(lintel["id"], "lintel", 2 * h * length, story, "sides")
            bars = lintel.get("bars") or {}
            for detail in ("bottom", "top"):
                group = bars.get(detail)
                if group:
                    count, dia = int(group[0]), float(group[1])
                    total = count * bar_length(length - 2 * lintel_design.COVER, dia)
                    self.rebar(lintel["id"], lintel["steel"], dia, total, story, detail)
            links = bars.get("stirrups")
            if links:
                legs, dia, spacing = int(links[0]), float(links[1]), float(links[2])
                n = math.floor((length - 2 * lintel_design.COVER) / spacing) + 1
                inner_b = b - 2 * lintel_design.COVER
                inner_h = h - 2 * lintel_design.COVER
                each = 2 * (inner_b + inner_h) + (legs - 2) * inner_h + 20 * dia
                self.rebar(lintel["id"], lintel["steel"], dia, n * each, story, "links")
        if found["elements"]:
            self.notes.append(
                f"Lintels: {len(found['elements'])} over openings in masonry and partition "
                "walls, as designed with the default gravity combinations; the masonry is not "
                "reduced by their volume."
            )

    def studs(
        self,
        element: str,
        given: Any,
        thickness: float,
        cover: float,
        columns: int,
        material_id: str,
        story: str | None,
    ) -> None:
        """Punching studs or stirrup legs round ``columns`` columns (``given`` an
        ``objects.PunchingReinforcement``), measured as bars of the member's depth less the
        covers (stirrups: two legs and the bends per pair)."""
        if not given or columns <= 0:
            return
        height = max(thickness - 2 * cover, 0.0)
        count = int(given.perLine) * int(given.lines) * columns
        if given.kind == "studs":
            each, detail = height, "headed shear studs"
        else:
            each, detail = height + 10 * float(given.dia), "punching stirrup legs"
        self.rebar(element, material_id, float(given.dia), count * each, story, detail)

    def slab_studs(self, slabs: list[tuple[Any, Any]]) -> None:
        """The punching studs or stirrups of flat slab types round each column under them."""
        columns = [e for e in self.building.elements if isinstance(e, ColumnElement)]
        for e, t in slabs:
            given = getattr(t, "punchingReinforcement", None)
            if given is None or t.reinforcement is None:
                continue
            outline = Polygon([(float(x), float(y)) for x, y in e.boundary])
            under = [
                c
                for c in columns
                if abs(float(c.top) - float(e.elevation)) < TOLERANCE + 1
                and outline.buffer(1.0).contains(Point(float(c.position[0]), float(c.position[1])))
            ]
            self.studs(
                e.id,
                given,
                float(t.thickness),
                float(t.reinforcement.cover),
                len(under),
                t.reinforcement.material,
                self.story_at(e.elevation),
            )

    # ── the foundations of 9 Substructure ──

    def foundations(self, substructure: Substructure) -> None:
        """Footings, pile caps, rafts, piles and tie beams of 9 Substructure, with their
        excavation, blinding and backfill (see :data:`FOUNDATION_CONVENTIONS`)."""
        solids = foundation_solids(substructure, self.building, self.ground_level)
        self.notes += [f"9 Substructure: {n}; not measured." for n in solids.notes]
        stories = sorted(self.building.stories, key=lambda s: s.elevation)
        story = stories[0].id if stories else None
        ground = self.ground_level
        pits: list[tuple[str, BaseGeometry, float]] = []  # (element, plan, bottom of the pit)
        below: dict[str, float] = {}  # concrete below the ground [mm³], by element

        def blinding(element: str, plan: BaseGeometry, bottom: float) -> None:
            pad = plan.buffer(BLINDING_PROJECTION, join_style="mitre")
            volume = pad.area * BLINDING
            self.bill.add(
                "concrete",
                (_kind_order("blinding"), ""),
                f"Lean concrete (blinding) under foundations, {BLINDING:g} mm",
                "m3",
                element,
                volume * MM3,
                story=story,
                kind="blinding",
            )
            pits.append(
                (element, plan.buffer(WORKING_SPACE, join_style="mitre"), bottom - BLINDING)
            )
            if bottom - BLINDING < ground:
                below[element] = below.get(element, 0.0) + volume * min(
                    1.0, (ground - bottom + BLINDING) / BLINDING
                )

        by_id = {f.id: f for f in substructure.foundations}
        for f in solids.foundations:
            plan = Polygon(f.outline)
            kind = {"pileCap": "pileCap", "raft": "raft"}.get(f.type, "footing")
            material = self.materials.get(f.material or "")
            blinding(f.id, plan, f.bottom)
            if material is None or material.category != Category.CONCRETE:
                self.notes.append(
                    f"{f.id}: its material '{f.material}' is not a concrete of 03 Materials; its "
                    "concrete, formwork and bars are not measured."
                )
                continue
            self.concrete(f.id, material, kind, plan.area * f.thickness, story)
            below[f.id] = below.get(f.id, 0.0) + plan.area * max(0.0, min(f.top, ground) - f.bottom)
            self.formwork(f.id, kind, plan.exterior.length * f.thickness, story, "sides")
            reinforcement = f.reinforcement
            if reinforcement is None:
                self.notes.append(f"{f.id}: no reinforcement; no bars are measured.")
                continue
            for detail, mesh, run in (
                ("bottom X", reinforcement.bottomX, f.runs[0]),
                ("bottom Y", reinforcement.bottomY, f.runs[1]),
                ("top X", reinforcement.topX, f.runs[0]),
                ("top Y", reinforcement.topY, f.runs[1]),
            ):
                if mesh is not None:
                    total = mesh_length(plan.area, mesh.spacing, run, mesh.dia)
                    self.rebar(f.id, reinforcement.material, mesh.dia, total, story, detail)
            own = by_id.get(f.id)
            if own is not None and getattr(own, "punchingReinforcement", None) is not None:
                self.studs(
                    f.id,
                    own.punchingReinforcement,
                    f.thickness,
                    float(reinforcement.cover),
                    max(len(own.columns), 1),
                    reinforcement.material,
                    story,
                )

        for pile in solids.piles:
            self.pile(pile, story)

        for tie in solids.ties:
            t = self.object_type(tie.id, tie.type, (o.Beam,), "beam")
            if t is None or not tie.clear:
                continue
            spans = tuple(math.dist(a, b) for a, b in tie.clear)
            self.linear(
                tie.id,
                t,
                tie.length,
                tie.clear_length,
                story,
                formwork=False,
                kind="tieBeam",
                spans=spans,
            )
            xmin, ymin, xmax, ymax = self.section(t).bounds
            width, depth = xmax - xmin, ymax - ymin
            material = self.materials.get(t.material)
            if material is not None and material.category == Category.CONCRETE:
                self.formwork(tie.id, "tieBeam", 2 * depth * tie.clear_length, story, "sides")
            bottom = tie.level - depth
            for a, b in tie.clear:
                plan = _rectangle(list(a), list(b), width)
                blinding(tie.id, plan, bottom)
                below[tie.id] = (
                    below.get(tie.id, 0.0)
                    + self.section(t).area
                    * math.dist(a, b)
                    * max(0.0, min(tie.level, ground) - bottom)
                    / depth
                )

        self.earthwork(pits, below, story)

    def pile(self, pile: PileSolid, story: str | None) -> None:
        """One pile: concrete, bars, and the moulds of a driven precast pile."""
        material = self.materials.get(pile.material)
        if material is None or material.category != Category.CONCRETE:
            self.notes.append(
                f"{pile.id}: its material '{pile.material}' is not a concrete of 03 Materials; "
                "it is not measured."
            )
            return
        d = pile.diameter
        square = pile.kind == "driven"
        section = box(-d / 2, -d / 2, d / 2, d / 2) if square else Point(0, 0).buffer(d / 2, 64)
        area = d * d if square else math.pi * d * d / 4
        self.concrete(pile.cap, material, "pile", area * pile.length, story)
        if square:
            self.formwork(pile.cap, "pile", 3 * d * pile.length, story, "precast moulds")
        reinforcement = pile.reinforcement
        if reinforcement is None:
            self.notes.append(f"{pile.id}: pile type '{pile.pile_type}' has no reinforcement.")
            return
        for bars in reinforcement.longitudinal:
            total = bars.count * bar_length(pile.length, bars.dia)
            self.rebar(pile.cap, reinforcement.material, bars.dia, total, story, "pile bars")
        transverse = reinforcement.transverse
        if transverse is not None:
            total = transverse_length(section, reinforcement.cover, transverse, pile.length)
            self.rebar(pile.cap, reinforcement.material, transverse.dia, total, story, "pile ties")

    def earthwork(
        self,
        pits: list[tuple[str, BaseGeometry, float]],
        below: dict[str, float],
        story: str | None,
    ) -> None:
        """Excavation of ``pits`` (vertical sides, overlaps once) and the backfill around what
        is ``below`` the ground in them."""
        ground = self.ground_level
        pits = [p for p in pits if p[2] < ground - TOLERANCE]
        if not pits:
            return
        levels = sorted({bottom for _, _, bottom in pits}) + [ground]
        total = 0.0
        for low, high in itertools.pairwise(levels):
            active = [plan for _, plan, bottom in pits if bottom <= low + 1e-9]
            total += unary_union(active).area * (high - low)
        own: dict[str, float] = {}
        for element, plan, bottom in pits:
            own[element] = own.get(element, 0.0) + plan.area * (ground - bottom)
        scale = total / sum(own.values())
        for element, volume in own.items():
            dug = volume * scale
            self.bill.add(
                "earthwork",
                (_kind_order("excavation"),),
                "Excavation for foundations",
                "m3",
                element,
                dug * MM3,
                story=story,
                kind="excavation",
            )
            self.bill.add(
                "earthwork",
                (_kind_order("backfill"),),
                "Backfill around foundations",
                "m3",
                element,
                max(dug - below.get(element, 0.0), 0.0) * MM3,
                story=story,
                kind="backfill",
            )

    def measure_mep(self) -> None:
        """The plinths of the equipment, and the sleeves and openings counted by size."""
        mep = self.mep
        if mep is None:
            return
        for item in mep.equipment:
            plinth = item.plinth
            if plinth is None or plinth.height <= 0:
                continue
            material = self.materials.get(plinth.material)
            if material is None:
                self.notes.append(
                    f"{item.id}: its plinth's material '{plinth.material}' is not in 3 Materials; "
                    "not measured"
                )
                continue
            self.concrete(
                item.id, material, "plinth", item.length * item.width * plinth.height, item.story
            )
            self.formwork(
                item.id,
                "plinth",
                2 * (item.length + item.width) * plinth.height,
                item.story,
                "sides",
            )
        kinds = {e.id: e.kind for e in self.building.elements}
        elevation = {e.id: getattr(e, "elevation", None) for e in self.building.elements}
        nouns = {"beam": "beams", "slab": "slabs", "wall": "walls"}
        for opening in mep.openings:
            host = kinds.get(opening.host)
            if host not in nouns:
                continue
            width, height = opening.size
            size = f"Ø{width:g} mm" if opening.shape == "circle" else f"{width:g} x {height:g} mm"
            what = "Sleeves" if opening.kind == "sleeve" else "Openings"
            at = elevation.get(opening.host)
            self.bill.add(
                "mep",
                (list(nouns).index(host), opening.kind, opening.shape, width, height),
                f"{what} {size} through {nouns[host]}",
                "nr",
                opening.id,
                1.0,
                story=self.story_at(at) if at is not None else None,
                detail=opening.service or None,
                kind=opening.kind,
            )

    def measure_plumbing(self, designs: dict[str, Any] | None = None) -> None:
        """The plumbing's RC tanks (concrete, formwork, bars from their last design, the
        ground tanks' excavation), risers and stacks by system and diameter [m], and the
        fixtures by kind. ``designs``: the cached tank designs
        (:func:`saengine.plumbing.project.read_designs`)."""
        mep = self.mep
        plumbing = getattr(mep, "plumbing", None)
        if plumbing is None or not (plumbing.tanks or plumbing.risers or plumbing.stories):
            return
        from saengine.library.mep import PLUMBING_SYSTEMS, TANK_KINDS, Fixtures
        from saengine.plumbing.project import _with_proposals, pipe_runs, tank_stamp
        from saengine.plumbing.report import plumbing_results
        from saengine.plumbing.tanks import TankContext, tank_spec, volumes

        self.plumbing_measured = True
        try:
            report: dict[str, Any] | None = plumbing_results(
                mep, self.building, None, self.ground_level
            )
        except Exception as error:  # noqa: BLE001 - the rest of the bill still measures
            report = None
            self.notes.append(f"Plumbing: the sizing failed ({error}); sized pipes not measured")
        proposals = {str(t.get("id")): t for t in (report or {}).get("tanks") or []}
        latest = {
            (entry.get("id"), entry.get("tank")): entry.get("result") or {}
            for entry in (designs or {}).values()
            if isinstance(entry, dict)
        }
        context = TankContext(materials=self.materials, rebar=self.library.default_rebar())
        for tank in plumbing.tanks:
            if tank.kind == "soakWell" or tank.construction != "rc":
                self.notes.append(
                    f"{tank.id}: {TANK_KINDS[tank.kind].lower()}"
                    f"{'' if tank.construction == 'rc' else f' ({tank.construction})'} is not "
                    "measured"
                )
                continue
            data = _with_proposals(tank.model_dump(mode="json", exclude_none=True), proposals)
            try:
                spec = tank_spec(data, context)
            except ValueError as error:
                self.notes.append(f"{tank.id}: not measured: {error}")
                continue
            v = volumes(spec)
            material = self.materials[spec.concrete]
            story = tank.story
            self.concrete(tank.id, material, "tank", v["concrete"] / MM3, story)
            self.formwork(tank.id, "tank", v["formwork"] / MM2, story, "inside and outside faces")
            if spec.ground:
                depth = spec.height + spec.base + (spec.roof or 0.0) - spec.top_level  # m
                width = spec.width + 2 * spec.wall + 2 * spec.toe + 2 * WORKING_SPACE * MM
                length = spec.length + 2 * spec.wall + 2 * spec.toe + 2 * WORKING_SPACE * MM
                self.bill.add(
                    "earthwork",
                    (_kind_order("excavation"), "tank"),
                    "Excavation for ground tanks",
                    "m3",
                    tank.id,
                    max(depth, 0.0) * width * length,
                    detail=TANK_KINDS[tank.kind],
                    kind="excavation",
                )
            design = latest.get((tank.id, tank_stamp(data)))
            bars = (design.get("quantities") or {}).get("byDiameter") if design else None
            if not bars:
                self.notes.append(
                    f"{tank.id}: {TANK_BARS_PENDING} (open the Plumbing results of 7 MEP, or Run "
                    "All, to design the tanks)"
                )
                continue
            for dia_text, mass in bars.items():
                dia = float(dia_text)
                self.bill.add(
                    "reinforcement",
                    (spec.rebar, dia),
                    f"Reinforcement {spec.rebar}, {dia:g} mm bars",
                    "kg",
                    tank.id,
                    float(mass),
                    story=story,
                    detail="tank design",
                    material=spec.rebar,
                    diameter=dia,
                )
        for run in pipe_runs(mep, self.building, report):
            if not run["diameter"]:
                self.notes.append(f"{run['id']}: no diameter (entered or sized); not measured")
                continue
            d, material = run["diameter"], run["material"]
            label = PLUMBING_SYSTEMS.get(run["system"], run["system"]).lower()
            noun = label.removesuffix(" riser").removesuffix(" stack").removesuffix(" leader")
            self.bill.add(
                "mep",
                (10, "pipe", run["system"], material or "", d),
                f"Pipes, {noun}, Ø{d:g} mm" + (f" {material}" if material else ""),
                "m",
                run["id"],
                run["length"],
                story=run["story"],
                detail=label,
                kind="pipe",
                diameter=d,
            )
        titles = {k: f.title for k, f in Fixtures.model_fields.items() if k != "other"}
        for entry in plumbing.stories:
            fixtures = entry.fixtures
            for key, title in titles.items():
                count = getattr(fixtures, key)
                if count:
                    self.bill.add(
                        "mep",
                        (20, "fixture", list(titles).index(key)),
                        f"Sanitary fixtures: {(title or key).lower()}",
                        "nr",
                        entry.story,
                        float(count),
                        story=entry.story,
                        kind="fixture",
                    )
            for other in fixtures.other:
                if other.count:
                    self.bill.add(
                        "mep",
                        (20, "fixture", len(titles), other.name),
                        f"Sanitary fixtures: {other.name}",
                        "nr",
                        entry.story,
                        float(other.count),
                        story=entry.story,
                        kind="fixture",
                    )

    def measure_services(self) -> None:
        """The HVAC ducts and plant, the electrical trays, risers and equipment, and the
        lightning protection's bonding points (:data:`SERVICES_CONVENTIONS`)."""
        mep = self.mep
        hvac = getattr(mep, "hvac", None)
        electrical = getattr(mep, "electrical", None)
        if hvac is None and electrical is None:
            return
        from saengine.mep.routing import path_length

        levels = {s.id: s.elevation for s in self.building.stories}
        self.services_measured = True

        def vertical(item_id: str, low: str, high: str) -> float:
            if low not in levels or high not in levels:
                self.notes.append(f"{item_id}: unknown story; its riser is not measured")
                return 0.0
            return max(levels[high] - levels[low], 0.0) / 1000.0

        if hvac is not None:
            from saengine.library.mep import DUCT_SYSTEMS, HVAC_PLANT_KINDS

            for duct in hvac.ducts:
                if duct.shape == "round" and duct.diameter:
                    size, dims = f"Ø{duct.diameter:g} mm", (duct.diameter, 0.0)
                elif duct.shape == "rect" and duct.width and duct.height:
                    size, dims = f"{duct.width:g} x {duct.height:g} mm", (duct.width, duct.height)
                else:
                    self.notes.append(f"{duct.id}: no duct size entered; not measured")
                    continue
                if duct.riser is not None:
                    length = vertical(duct.id, duct.riser.fromStory, duct.riser.toStory)
                    story = duct.riser.fromStory
                else:
                    length, story = path_length(duct.path) / 1000.0, duct.story
                system = DUCT_SYSTEMS.get(duct.system, duct.system)
                self.bill.add(
                    "mep",
                    (30, "duct", duct.system, duct.shape, *dims),
                    f"Ducts, {_noun(system)}, {size}",
                    "m",
                    duct.id,
                    length,
                    story=story,
                    detail="riser" if duct.riser is not None else None,
                    kind="duct",
                )
            for plant in hvac.plant:
                label = HVAC_PLANT_KINDS.get(plant.kind, plant.kind)
                self.bill.add(
                    "mep",
                    (40, "plant", plant.kind),
                    f"HVAC plant: {_noun(label)}",
                    "nr",
                    plant.id,
                    1.0,
                    story=plant.story,
                    kind="plant",
                )
        if electrical is None:
            return
        from saengine.library.mep import ELECTRICAL_EQUIPMENT_KINDS, ELECTRICAL_RISER_KINDS

        for tray in electrical.trays:
            self.bill.add(
                "mep",
                (50, "tray", tray.width, tray.height),
                f"Cable trays {tray.width:g} x {tray.height:g} mm",
                "m",
                tray.id,
                path_length(tray.path) / 1000.0,
                story=tray.story,
                kind="tray",
            )
        sized: dict[str, Any] = {}
        lightning: dict[str, Any] | None = None
        try:
            from types import SimpleNamespace

            from saengine.electrical.report import electrical_results

            objects = SimpleNamespace(objects=list(self.types.values()))
            report = electrical_results(mep, self.building, objects, self.ground_level)
            sized = {r.get("id"): r for r in report.get("risers", []) if isinstance(r, dict)}
            lightning = report.get("lightning")
        except Exception as error:  # noqa: BLE001 - the rest of the bill is still measured
            self.notes.append(f"electrical: not sized ({error}); risers by their entered size")
        for riser in electrical.risers:
            width = riser.width or (sized.get(riser.id) or {}).get("width")
            depth = riser.depth or (sized.get(riser.id) or {}).get("depth")
            label = ELECTRICAL_RISER_KINDS.get(riser.kind, riser.kind)
            size = f" {width:g} x {depth:g} mm" if width and depth else ""
            self.bill.add(
                "mep",
                (55, "riser", riser.kind, width or 0.0, depth or 0.0),
                f"Rising mains: {_noun(label)}{size}",
                "m",
                riser.id,
                vertical(riser.id, riser.fromStory, riser.toStory),
                story=riser.fromStory,
                kind="riser",
            )
        for item in electrical.equipment:
            label = ELECTRICAL_EQUIPMENT_KINDS.get(item.kind, item.kind)
            self.bill.add(
                "mep",
                (60, "equipment", item.kind),
                f"Electrical equipment: {_noun(label)}",
                "nr",
                item.id,
                1.0,
                story=item.story,
                kind="equipment",
            )
        conductors = (lightning or {}).get("downConductors") or []
        if lightning and lightning.get("enabled") and conductors:
            natural = electrical.lightning is None or (
                electrical.lightning.downConductors == "structuralRebar"
            )
            for dc in conductors:
                column = (dc.get("columns") or [dc.get("id")])[0]
                if natural:
                    self.bill.add(
                        "mep",
                        (70, "bonding"),
                        "Lightning: bonding terminals welded to the column bars (roof and base)",
                        "nr",
                        str(column),
                        2.0,
                        kind="bonding",
                    )
                self.bill.add(
                    "mep",
                    (71, "inspection"),
                    "Lightning: earth inspection box recesses",
                    "nr",
                    str(column),
                    1.0,
                    kind="bonding",
                )

    def mix_quantities(self, mix: Any, volume: float, dry_factor: float) -> dict[str, float]:
        """Cement [kg], sand and stone [m³] and water [l] in ``volume`` [m³] of wet concrete or
        mortar of ``mix`` (a nominal mix shared out of ``dry_factor`` × the volume)."""
        if mix.method == "design":
            out = {
                "cement": mix.cement * volume,
                "sand": mix.fineAggregate * volume / SAND_DENSITY,
                "water": mix.water * volume,
            }
            if mix.coarseAggregate:
                out["stone"] = mix.coarseAggregate * volume / STONE_DENSITY
            return out
        dry = volume * dry_factor
        parts = sum(mix.ratio)
        cement = dry * mix.ratio[0] / parts * CEMENT_DENSITY
        out = {"cement": cement, "sand": dry * mix.ratio[1] / parts}
        if len(mix.ratio) == 3:
            out["stone"] = dry * mix.ratio[2] / parts
        if mix.waterCement:
            out["water"] = mix.waterCement * cement  # kg of water = litres
        return out

    def measure_materials(self) -> None:
        """The materials take-off of the concrete and masonry lines (:data:`MATERIALS_CONVENTIONS`):
        per element, so the items keep their breakdown and their quantities by story."""
        lines = [
            line
            for line in list(self.bill.lines.values())
            if line.group in ("concrete", "masonry") and line.unit == "m3" and line.material
        ]
        missing: dict[str, str] = {}
        assumed: dict[str, str] = {}
        # An assumed mix uses the cement of the project's own mixes (the most common type), so
        # its cement joins theirs on one line instead of a second, untyped one.
        mixes = [getattr(m, "composition", None) for m in self.materials.values()]
        types = [t for t in (getattr(mix, "cementType", None) for mix in mixes) if t]
        project_cement = max(sorted(set(types)), key=types.count) if types else None
        for line in lines:
            material = self.materials.get(line.material or "")
            if material is None:
                continue
            if line.group == "masonry":
                mortar_id = material.masonry.mortar if material.masonry else None
                mortar = self.materials.get(mortar_id or "")
                if mortar is None or mortar.composition is None:
                    missing[material.id] = f"masonry {material.id}: its mortar " + (
                        f"{mortar_id} has no mix" if mortar_id else "is not named"
                    )
                    continue
                mix, share, factor = mortar.composition, BRICKWORK_WET_MORTAR, DRY_VOLUME_MORTAR
                cement_type = mix.cementType
            else:
                mix = material.composition
                if mix is None:
                    mix = assumed_mix(material).model_copy(update={"cementType": project_cement})
                    ratio = ":".join(f"{r:g}" for r in mix.ratio)
                    assumed[material.id] = (
                        f"concrete {material.id} has no mix: {ratio} assumed "
                        f"(f'c {_fc(material):g} MPa)"
                    )
                share, factor = 1.0, DRY_VOLUME_CONCRETE
                cement_type = mix.cementType
            cement = f"Cement{f' ({cement_type})' if cement_type else ''}"
            items = {
                "cement": ((1, cement_type or ""), f"{cement}", "kg", 1.0),
                "bags": ((2, cement_type or ""), f"{cement} in {CEMENT_BAG:g} kg bags", "bag", 1 / CEMENT_BAG),
                "sand": ((3,), "Sand (fine aggregate)", "cft", CFT),
                "stone": ((4,), "Stone chips (coarse aggregate)", "cft", CFT),
                "water": ((5,), "Water", "l", 1.0),
            }  # fmt: skip
            for (element, story, _), volume in line.amounts.items():
                amounts = self.mix_quantities(mix, volume * share, factor)
                amounts["bags"] = amounts["cement"]
                for key, amount in amounts.items():
                    order, description, unit, scale = items[key]
                    self.bill.add(
                        "materials",
                        order,
                        description,
                        unit,
                        element,
                        amount * scale,
                        story=story,
                        detail=line.description,
                        kind=key,
                    )
        if assumed:
            self.notes.append(
                "Materials: "
                + "; ".join(assumed[k] for k in sorted(assumed))
                + ", a nominal mix of IS 456:2000 Table 9 by strength, no water (enter the mix "
                "in 03 Materials to replace it)."
            )
        if missing:
            self.missing_mixes = [missing[k] for k in sorted(missing)]
            self.notes.append(
                "Materials: "
                + "; ".join(self.missing_mixes)
                + ", so no cement, sand or stone is taken off for it (add the mix in 03 Materials)."
            )
        self.materials_measured = any(
            line.group == "materials" for line in self.bill.lines.values()
        )

    def finish(self) -> list[str]:
        notes = [*CONVENTIONS]
        if self.substructure is not None and (
            self.substructure.foundations or self.substructure.tieBeams
        ):
            notes += FOUNDATION_CONVENTIONS
        if self.mep is not None and (
            self.mep.openings or any(e.plinth for e in self.mep.equipment)
        ):
            notes += MEP_CONVENTIONS
        if getattr(self, "plumbing_measured", False):
            notes += PLUMBING_CONVENTIONS
        if getattr(self, "services_measured", False):
            notes += SERVICES_CONVENTIONS
        if getattr(self, "fire_measured", False):
            from saengine.fire.boq import FIRE_CONVENTIONS

            notes += FIRE_CONVENTIONS
        if getattr(self, "materials_measured", False):
            notes += MATERIALS_CONVENTIONS
        notes += [*self.building.check_additions(), *self.notes]
        if self.drawn_footings:
            notes.append(
                f"Footings drawn in the building model ({', '.join(self.drawn_footings)}) are not "
                "measured: the foundations are those of 9 Substructure."
            )
        for type_id, elements in self.unreinforced.items():
            t = self.types[type_id]
            notes.append(
                f"Object type '{type_id}' ({t.name}) has no reinforcement; no bars are measured "
                f"for {', '.join(elements)}."
            )
        return notes

    def problems(self) -> list[str]:
        """What the bill could not measure, short, for the editor's warning rows and the part's
        status (the notes keep the details)."""
        out = []
        if self.unreinforced:
            types = sorted(self.unreinforced)
            count = sum(len(v) for v in self.unreinforced.values())
            out.append(
                f"No reinforcement measured for {count} element(s) of {len(types)} object type(s) "
                f"with no bars ({', '.join(types[:6])}{', ...' if len(types) > 6 else ''}): "
                "Design Reinforcement in 8 FEM proposes them (tick a slab type to include it), "
                "or enter them in 04 Objects."
            )
        for text in getattr(self, "missing_mixes", []):
            out.append(f"No cement or sand for {text} (add the mix in 03 Materials).")
        out += [
            n for n in self.notes if TANK_BARS_PENDING in n or n.rstrip().endswith("not measured.")
        ]
        return out


def _fc(material: Material) -> float:
    return material.concrete.fc if material.concrete is not None else 0.0


def assumed_mix(material: Material) -> Any:
    """The nominal mix taken off a concrete with no mix in 03 Materials (:data:`ASSUMED_MIXES`)."""
    from saengine.library.materials import NominalMix

    fc = _fc(material)
    ratio = next(r for limit, r in ASSUMED_MIXES if fc <= limit + 1e-9)
    return NominalMix(ratio=list(ratio))


def bill_of_quantities(
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary,
    source: BoqSource | None = None,
    substructure: Substructure | None = None,
    ground_level: float = 0.0,
    mep: Any = None,
    tank_designs: dict[str, Any] | None = None,
) -> BillOfQuantities:
    """The bill of quantities of ``building``. With ``substructure`` (the project's
    ``substructure.json`` once it is no longer the placeholder, see
    :func:`saengine.substructure.handover.authoritative_substructure`) the foundations are
    measured from it, with their earthwork dug from ``ground_level`` [mm], and the footings of
    the building model are not; without it the building model's footings are measured.
    ``tank_designs``: the plumbing tanks' last designs (their bars,
    :func:`saengine.plumbing.project.read_designs`)."""
    measure = _Measure(building, objects, materials, substructure, ground_level, mep)
    measure.run()
    measure.measure_mep()
    measure.measure_plumbing(tank_designs)
    measure.measure_services()
    from saengine.fire.boq import measure_fire

    measure.fire_measured = measure_fire(measure, tank_designs)
    measure.measure_materials()
    notes = measure.finish()
    return BillOfQuantities(
        source=source or BoqSource(),
        items=measure.bill.items({e.id: e.type for e in building.elements if e.type}),
        notes=notes,
        problems=measure.problems(),
    )


def _inputs(
    substructure_text: str | None, settings_text: str | None
) -> tuple[Substructure | None, float]:
    """The substructure that is the source of the foundations (None: the building model's
    footings are) and the finished ground level."""
    from saengine.library.settings import ProjectSettings
    from saengine.substructure.handover import authoritative_substructure

    substructure = authoritative_substructure(substructure_text)
    ground = 0.0
    if settings_text:
        ground = ProjectSettings.model_validate_json(settings_text).foundation.groundLevel
    return substructure, ground


def compute_boq(
    bim_text: str,
    objects_text: str,
    materials_text: str,
    substructure_text: str | None = None,
    settings_text: str | None = None,
    mep_text: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    """The ``10 BOQ/boq.json`` document (JSON-ready) measured from the files' texts:
    ``substructure_text`` (``09 Substructure/substructure.json``), ``settings_text`` (the
    ground level of the earthwork) and ``mep_text`` (``07 MEP/mep.json``: plinths, sleeves and
    openings, the plumbing's tanks, pipes and fixtures) are optional. Their stamps are recorded
    when given (for the settings, the stamp of their ground level only, and only when the
    substructure's foundations are measured: nothing else in the bill depends on them).
    ``project_root``: the project folder, where the plumbing tanks' last designs (their bars)
    are read from.

    Raises ``pydantic.ValidationError`` (a ``ValueError``) when a file is not valid.
    """
    from saengine.library.mep import parse as parse_mep

    substructure, ground = _inputs(substructure_text, settings_text)
    mep = parse_mep(mep_text) if mep_text is not None else None
    designs = None
    if project_root and mep is not None and (mep.plumbing is not None or mep.fire is not None):
        from saengine.fire.report import read_fire_designs
        from saengine.plumbing.project import read_designs

        designs = {**read_designs(project_root), **read_fire_designs(project_root)}
    earthwork = substructure is not None and bool(substructure.foundations or substructure.tieBeams)
    document = bill_of_quantities(
        BuildingModel.model_validate_json(bim_text),
        ObjectLibrary.model_validate_json(objects_text),
        MaterialLibrary.model_validate_json(materials_text),
        BoqSource(
            bim=source_stamp(bim_text),
            objects=source_stamp(objects_text),
            materials=source_stamp(materials_text),
            substructure=source_stamp(substructure_text) if substructure_text is not None else None,
            mep=source_stamp(mep_text) if mep_text is not None else None,
            settings=ground_level_stamp(ground) if settings_text and earthwork else None,
        ),
        substructure,
        ground,
        mep,
        designs,
    )
    _with_bar_schedule(
        document,
        {
            "bim": bim_text,
            "objects": objects_text,
            "materials": materials_text,
            "settings": settings_text,
            "substructure": substructure_text,
        },
        project_root,
    )
    return document.model_dump(mode="json", by_alias=True, exclude_none=True)


def _with_bar_schedule(
    document: BillOfQuantities, texts: dict[str, str | None], project_root: str | None = None
) -> None:
    """The bar bending schedule of the drawings in the bill (:mod:`saengine.boq.schedule`): its
    reconciliation in the notes, or, with Project Settings' ``drawings.boqReinforcement``
    "bbs", its bars in place of the measured ones (``project_root``: with the marks and the kept
    design of the drawings, :func:`saengine.boq.schedule.schedule_of`)."""
    from saengine.boq.schedule import reconcile_notes, schedule_of, take_from_schedule
    from saengine.library.settings import ProjectSettings

    take = False
    if texts.get("settings"):
        try:
            settings = ProjectSettings.model_validate_json(texts["settings"] or "")
            take = settings.drawings.boqReinforcement == "bbs"
        except ValueError:
            take = False
    if not take and not any(i.group == "reinforcement" for i in document.items):
        return
    schedule, notes = schedule_of(texts, project_root)
    if schedule is None or not schedule.rows:
        document.notes += notes
        return
    kept = take_from_schedule(document, schedule) if take else None
    document.notes += reconcile_notes(document, schedule, kept)


def compute_boq_text(
    bim_text: str,
    objects_text: str,
    materials_text: str,
    substructure_text: str | None = None,
    settings_text: str | None = None,
    mep_text: str | None = None,
    project_root: str | None = None,
) -> dict[str, Any]:
    """For the RPC handler: ``{"text", "notes"}`` (the file's text), or ``{"problems"}`` when an
    input has errors."""
    from saengine.library.mep import parse as parse_mep

    try:
        parse_mep(mep_text)
    except ValueError as exc:
        return {"problems": [f"MEP: {str(exc).strip().splitlines()[0]}"]}
    from saengine.library.settings import ProjectSettings
    from saengine.library.substructure import Substructure as SubstructureModel

    checks: list[tuple[Any, str | None, str]] = [
        (BuildingModel, bim_text, "Building model"),
        (ObjectLibrary, objects_text, "Object types"),
        (MaterialLibrary, materials_text, "Materials"),
        (ProjectSettings, settings_text or None, "Project settings"),
    ]
    try:
        _inputs(substructure_text, None)
    except ValidationError:
        checks.append((SubstructureModel, substructure_text, "Substructure"))
    except ValueError as exc:  # not JSON
        return {"problems": [f"Substructure: {exc}"]}
    for model, text, label in checks:
        if text is None:
            continue
        try:
            model.model_validate_json(text)
        except ValidationError as exc:
            problems = []
            for e in exc.errors():
                path = ".".join(str(p) for p in e["loc"])
                message = e["msg"].removeprefix("Value error, ")
                problems.append(f"{label}: {path}: {message}" if path else f"{label}: {message}")
            return {"problems": problems}
    document = compute_boq(
        bim_text,
        objects_text,
        materials_text,
        substructure_text,
        settings_text,
        mep_text,
        project_root,
    )
    return {
        "text": json.dumps(document, indent="\t", ensure_ascii=False) + "\n",
        "notes": document["notes"],
    }
