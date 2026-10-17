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

Group = Literal["earthwork", "concrete", "masonry", "reinforcement", "formwork", "steel"]
Unit = Literal["m3", "m2", "kg"]

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
}

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
    "solid": "solid blocks",
}

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

    def items(self) -> list[BoqItem]:
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
                        BreakdownEntry(element=e, story=s, detail=d, quantity=round(q, 3))
                        for (e, s, d), q in line.amounts.items()
                    ],
                )
            )
        return items


def _kind_order(kind: str) -> int:
    return list(KINDS).index(kind) if kind in KINDS else len(KINDS)


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


class _Measure:
    def __init__(
        self,
        building: BuildingModel,
        objects: ObjectLibrary,
        materials: MaterialLibrary,
        substructure: Substructure | None = None,
        ground_level: float = 0.0,
    ) -> None:
        self.building = building
        self.substructure = substructure
        self.ground_level = ground_level
        self.drawn_footings: list[str] = []
        self.types = {t.id: t for t in objects.objects}
        self.materials = {m.id: m for m in materials.materials}
        self.bill = _Bill()
        self.notes: list[str] = []
        self.unreinforced: dict[str, list[str]] = {}
        self.bad_rebar: set[str] = set()
        self.sections: dict[str, Polygon] = {}
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
        self, element: str, material: Material, kind: str, mass: float, story: str | None
    ) -> None:
        self.bill.add(
            "steel",
            (material.id, _kind_order(kind)),
            f"Structural steel {material.id} in {KINDS.get(kind, kind)}",
            "kg",
            element,
            mass,
            story=story,
            material=material.id,
            kind=kind,
        )

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
        section = self.section(object_type)
        if material.category == Category.STEEL:
            density = material.mechanical.density or STEEL_DENSITY
            mass = count * section.area * MM2 * length * MM * density
            self.steel(element, material, kind, mass, story)
            return
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
    ) -> None:
        """``runs``: the length of the vertical and of the horizontal bars [mm]."""
        reinforcement = object_type.reinforcement
        if reinforcement is None:
            self.no_bars(object_type, element)
            return
        for detail, mesh, run in (
            ("vertical", reinforcement.vertical, runs[0]),
            ("horizontal", reinforcement.horizontal, runs[1]),
        ):
            if mesh is not None:
                total = reinforcement.layers * mesh_length(area, mesh.spacing, run, mesh.dia)
                self.rebar(element, reinforcement.material, mesh.dia, total, story, detail)

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
    ) -> None:
        """A wall of face ``area`` [mm²]; ``less``: its concrete [mm³] and formwork [mm²] within
        slabs."""
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
            self.wall_bars(element, object_type, area, runs, story)

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
                        self.wall(e.id, t, area, (height, length), story, less)
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
        drop = float(t.waistThickness) * math.hypot(riser, going) / going
        foot = drop * going / riser
        points = [(0.0, 0.0)]
        for i in range(n):
            points += [(i * going, (i + 1) * riser), ((i + 1) * going, (i + 1) * riser)]
        points += [(n * going, n * riser - drop), (min(foot, n * going), 0.0)]
        width = float(t.flightWidth)
        story = stair.base
        self.concrete(stair.id, material, "staircase", Polygon(points).area * width, story)
        slope = math.hypot(n * going, rise)
        self.formwork(stair.id, "staircase", slope * width, story, "soffit")
        self.formwork(stair.id, "staircase", n * riser * width, story, "risers")
        reinforcement = t.reinforcement
        if reinforcement is None:
            self.no_bars(t, stair.id)
            return
        for detail, mesh, run in (
            ("main", reinforcement.main, slope),
            ("distribution", reinforcement.distribution, width),
        ):
            total = mesh_length(slope * width, mesh.spacing, run, mesh.dia)
            self.rebar(stair.id, reinforcement.material, mesh.dia, total, story, detail)

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

    def finish(self) -> list[str]:
        notes = [*CONVENTIONS]
        if self.substructure is not None and (
            self.substructure.foundations or self.substructure.tieBeams
        ):
            notes += FOUNDATION_CONVENTIONS
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


def bill_of_quantities(
    building: BuildingModel,
    objects: ObjectLibrary,
    materials: MaterialLibrary,
    source: BoqSource | None = None,
    substructure: Substructure | None = None,
    ground_level: float = 0.0,
) -> BillOfQuantities:
    """The bill of quantities of ``building``. With ``substructure`` (the project's
    ``substructure.json`` once it is no longer the placeholder, see
    :func:`saengine.substructure.handover.authoritative_substructure`) the foundations are
    measured from it, with their earthwork dug from ``ground_level`` [mm], and the footings of
    the building model are not; without it the building model's footings are measured."""
    measure = _Measure(building, objects, materials, substructure, ground_level)
    measure.run()
    return BillOfQuantities(
        source=source or BoqSource(), items=measure.bill.items(), notes=measure.finish()
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
) -> dict[str, Any]:
    """The ``10 BOQ/boq.json`` document (JSON-ready) measured from the files' texts:
    ``substructure_text`` (``09 Substructure/substructure.json``) and ``settings_text`` (the
    ground level of the earthwork) are optional. Their stamps are recorded when given (for the
    settings, the stamp of their ground level only, and only when the substructure's
    foundations are measured: nothing else in the bill depends on them).

    Raises ``pydantic.ValidationError`` (a ``ValueError``) when a file is not valid.
    """
    substructure, ground = _inputs(substructure_text, settings_text)
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
            settings=ground_level_stamp(ground) if settings_text and earthwork else None,
        ),
        substructure,
        ground,
    )
    return document.model_dump(mode="json", by_alias=True, exclude_none=True)


def compute_boq_text(
    bim_text: str,
    objects_text: str,
    materials_text: str,
    substructure_text: str | None = None,
    settings_text: str | None = None,
) -> dict[str, Any]:
    """For the RPC handler: ``{"text", "notes"}`` (the file's text), or ``{"problems"}`` when an
    input has errors."""
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
    document = compute_boq(bim_text, objects_text, materials_text, substructure_text, settings_text)
    return {
        "text": json.dumps(document, indent="\t", ensure_ascii=False) + "\n",
        "notes": document["notes"],
    }
