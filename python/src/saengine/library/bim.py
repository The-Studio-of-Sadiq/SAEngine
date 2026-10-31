"""The building model (``06 BIM/bim.json``): the 3D building, derived from Part 5.

Buildings are generated from the floor plan (story by story); special structures from the
structural model (``05 Structural Model/structure.json``, :func:`generate_from_structure`),
whose members, areas and supports become ``member`` and ``area`` elements and ``supports``.


Parts own their files: the floor plan (Part 5) owns the layout, and this model is *generated*
from it (:func:`generate`), never edited into it. Every generated element keeps the id of the
floor-plan member it comes from (``source``), with its position resolved to absolute
coordinates, the way IFC places elements. Elements without a ``source`` belong to the building
model itself (openings, stairs, sloped members, ... as Part 6 grows); regenerating keeps them.

``source`` at the top records the floor plan revision the model was built from (a stamp of its
text), so the editor can tell when the floor plan has changed since and offer to update. The
model is only regenerated when the engineer asks.

Units are fixed SI: coordinates and elevations in mm, rotations in degrees.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.floorplan import FloorPlan, GridPoint, Story
from saengine.library.labels import field_title
from saengine.library.materials import Id
from saengine.library.modifiers import DesignOverwrites, FrameModifiers, ShellModifiers
from saengine.library.objects import ObjectLibrary
from saengine.library.structure import StructuralModel

SCHEMA_ID = "saengine.bim/2"

Point2 = Annotated[list[float], Field(min_length=2, max_length=2, description="[x, y] in mm.")]
Point3 = Annotated[list[float], Field(min_length=3, max_length=3, description="[x, y, z] in mm.")]
Mm = Annotated[float, Field(description="[mm]")]


def source_stamp(text: str) -> str:
    """The stamp of an upstream file: SHA-1 of its text with line endings normalised.

    The workbench computes the same stamp to tell whether the file changed since.
    """
    return hashlib.sha1(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def ground_level_stamp(ground_level: float) -> str:
    """The stamp of the finished ground level [mm] (to the micrometre), the only value of the
    project settings the bill of quantities depends on. The workbench computes the same
    (``groundLevelStamp`` in partSources.ts), so other settings edits leave the bill current."""
    return source_stamp(f"groundLevel={math.floor(ground_level * 1000 + 0.5)}")


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class SourceStamps(_Model):
    """The upstream revisions the model was built from."""

    floorPlan: str | None = Field(
        default=None, title="Floor plan", description="Stamp of floor-plan.json."
    )
    structure: str | None = Field(
        default=None, title="Structural model", description="Stamp of structure.json."
    )


class _Element(_Model):
    id: Id
    type: Id = Field(title="Object type", description="Object type id from 04 Objects.")
    source: Id | None = Field(
        default=None,
        title="Floor plan member",
        description="The floor-plan member this element is generated from; none for elements "
        "that belong to the building model itself.",
    )


class ColumnElement(_Element):
    kind: Literal["column"] = "column"
    position: Point2
    bottom: Mm = Field(description="Elevation of the bottom [mm].")
    top: Mm = Field(description="Elevation of the top [mm].")
    rotation: float = Field(default=0, description="[°]")
    modifiers: FrameModifiers | None = Field(
        default=None,
        title="Stiffness modifiers",
        description="Factors on the analysis section properties (empty: the code's cracked "
        "factors for concrete and masonry, else 1).",
    )
    designOverwrites: DesignOverwrites | None = Field(
        default=None,
        title="Design overwrites",
        description="k, unbraced lengths and framing for the design (empty: automatic).",
    )


class BeamElement(_Element):
    """A beam with its top at ``elevation`` (the level of the story it supports)."""

    kind: Literal["beam"] = "beam"
    start: Point2
    end: Point2
    elevation: Mm = Field(description="Elevation of the top [mm].")
    modifiers: FrameModifiers | None = Field(
        default=None,
        title="Stiffness modifiers",
        description="Factors on the analysis section properties (empty: the code's cracked "
        "factors for concrete and masonry, else 1).",
    )
    designOverwrites: DesignOverwrites | None = Field(
        default=None,
        title="Design overwrites",
        description="k, unbraced lengths and framing for the design (empty: automatic).",
    )


class WallElement(_Element):
    kind: Literal["wall"] = "wall"
    start: Point2
    end: Point2
    bottom: Mm = Field(description="[mm]")
    top: Mm = Field(description="[mm]")
    modifiers: ShellModifiers | None = Field(
        default=None,
        title="Stiffness modifiers",
        description="Factors on the analysis shell stiffness, mass and weight (empty: the "
        "code's cracked factors for concrete and masonry, else 1).",
    )


class SlabElement(_Element):
    kind: Literal["slab"] = "slab"
    boundary: list[Point2] = Field(min_length=3)
    elevation: Mm = Field(description="Elevation of the top [mm].")
    areaLoad: Id | None = Field(
        default=None,
        title="Area load",
        description="Area load from 02 Project Settings; none: the floor or roof load there.",
    )
    modifiers: ShellModifiers | None = Field(
        default=None,
        title="Stiffness modifiers",
        description="Factors on the analysis shell stiffness, mass and weight (empty: the "
        "code's cracked factors for concrete and masonry, else 1).",
    )


class FootingElement(_Element):
    """A footing or pile cap with its top at ``elevation``."""

    kind: Literal["footing"] = "footing"
    position: Point2
    elevation: Mm = Field(description="Elevation of the top [mm].")
    rotation: float = Field(default=0, description="[°]")


class MemberElement(_Element):
    """A straight member between two points in space (special structures)."""

    kind: Literal["member"] = "member"
    start: Point3
    end: Point3
    rotation: float = Field(default=0, description="About the member's axis [°].")


class AreaElement(_Element):
    """A planar slab, wall or shell panel bounded by a polygon in space (special structures);
    the polygon is its mid-surface."""

    kind: Literal["area"] = "area"
    outline: list[Point3] = Field(min_length=3)
    openings: list[list[Point3]] = Field(default_factory=list)
    areaLoad: Id | None = Field(
        default=None, title="Area load", description="Area load from 02 Project Settings."
    )


class BlockElement(_Element):
    """A solid block (special structures): a flat outline extruded along its normal by
    ``thickness``."""

    kind: Literal["block"] = "block"
    outline: list[Point3] = Field(min_length=3)
    thickness: Mm
    supported: bool = Field(default=False, description="Held on its outline face.")


class BimSupport(_Model):
    """A support of a special structure: fixed, or pinned (translations only)."""

    id: Id
    at: Point3
    fixity: Literal["fixed", "pinned"] = "fixed"


Element = Annotated[
    ColumnElement
    | BeamElement
    | WallElement
    | SlabElement
    | FootingElement
    | MemberElement
    | AreaElement
    | BlockElement,
    Field(discriminator="kind"),
]

# Object kinds each element may use.
_ALLOWED_KINDS = {
    "column": ("column",),
    "beam": ("beam",),
    "wall": ("wall",),
    "slab": ("slab",),
    "footing": ("footing", "pileCap"),
    "member": ("beam", "column", "brace"),
    "area": ("slab", "wall"),
    "block": ("solid",),
}


# ───────────────────────── additions: what the building model adds itself ─────────────────────────

Length = Annotated[float, Field(gt=0, description="[mm]")]


class SlabOpening(_Model):
    """A rectangular hole through a slab (shafts, stair wells, ducts)."""

    id: Id
    host: Id = Field(title="Slab", description="Id of the slab element it cuts.")
    x: Mm = Field(description="Centre of the opening [mm].")
    y: Mm = Field(description="[mm]")
    xDim: Length = Field(title="Size X")
    yDim: Length = Field(title="Size Y")
    rotation: float = Field(default=0, description="[°]")


class WallOpening(_Model):
    """A door or window hole through a wall."""

    id: Id
    host: Id = Field(title="Wall", description="Id of the wall element it cuts.")
    offset: Mm = Field(ge=0, description="From the wall's start to the opening's near edge [mm].")
    sill: Mm = Field(
        default=0, ge=0, description="Height of the bottom above the wall's bottom [mm]."
    )
    width: Length
    height: Length


class Stair(_Model):
    """A straight waist-slab flight between two stories."""

    id: Id
    type: Id = Field(title="Object type", description="Staircase type from 04 Objects.")
    base: Id = Field(description="Story the flight starts at.")
    top: Id = Field(description="Story the flight arrives at.")
    x: Mm = Field(description="Foot of the flight, centre of its width [mm].")
    y: Mm = Field(description="[mm]")
    direction: float = Field(
        default=0, description="Direction the flight rises in, from the X axis [°]."
    )


class InclinedMember(_Model):
    """A brace, sloped beam or raking column between two points in space."""

    id: Id
    type: Id = Field(title="Object type", description="Brace, beam or column type from 04 Objects.")
    x1: Mm = Field(title="Start X")
    y1: Mm = Field(title="Start Y")
    z1: Mm = Field(title="Start Z", description="Elevation [mm].")
    x2: Mm = Field(title="End X")
    y2: Mm = Field(title="End Y")
    z2: Mm = Field(title="End Z", description="Elevation [mm].")

    @model_validator(mode="after")
    def _length(self) -> InclinedMember:
        if (self.x1, self.y1, self.z1) == (self.x2, self.y2, self.z2):
            raise ValueError(f"{self.id}: its start and end are the same point")
        return self


class TendonPoint(_Model):
    """A point of a tendon's profile: the height of the strands' centroid (CGS) above the
    slab's soffit at a distance along the tendon."""

    at: float = Field(ge=0, description="Distance from the tendon's start [mm].")
    height: Length = Field(description="Height of the CGS above the soffit [mm].")


class SlabTendon(_Model):
    """A group of post-tensioning tendons in a slab (saengine.design.prestress): banded (the
    tendons together in a band over a column line) or distributed (spread evenly over the
    strip they serve), straight in plan from ``start`` to ``end``. The profile's high points
    (the local highest heights) are taken as the supports of the strip the tendons design."""

    id: Id
    host: Id = Field(title="Slab", description="Id of the slab element the tendons are in.")
    layout: Literal["banded", "distributed"] = Field(
        default="banded",
        json_schema_extra={"enumDescriptions": ["Banded over a column line", "Distributed"]},
    )
    x1: Mm = Field(title="Start X", description="Plan position of the tendons' start [mm].")
    y1: Mm = Field(title="Start Y")
    x2: Mm = Field(title="End X")
    y2: Mm = Field(title="End Y")
    width: Length = Field(
        description="Width of the slab strip the tendons serve [mm] (a band: the column strip "
        "it stands for; distributed: the width they are spread over)."
    )
    count: int = Field(default=4, ge=1, description="Tendons in the group.")
    strands: int = Field(default=1, ge=1, description="Strands per tendon.")
    strandArea: Length = Field(
        default=98.7,
        title="Strand area",
        description="Area of one strand [mm²] (12.7 mm seven-wire strand: 98.7).",
    )
    fpu: Length = Field(
        default=1860, description="Tensile strength of the strand [MPa] (supplier's value)."
    )
    fpy: Length | None = Field(
        default=None, description="Yield strength [MPa]; empty: 0.9 fpu (low-relaxation strand)."
    )
    ep: Length = Field(
        default=195_000, title="Ep", description="Modulus of the strand [MPa] (supplier's value)."
    )
    jacking: float = Field(
        default=0.80,
        gt=0,
        le=0.94,
        description="Jacking stress / fpu (at most 0.80 fpu and 0.94 fpy).",
    )
    bonded: bool = Field(default=False, description="Grouted (bonded) tendons; else unbonded.")
    stressedAt: Literal["start", "end", "both"] = Field(
        default="start", title="Stressed at", description="The live end(s)."
    )
    wobble: float = Field(
        default=0.0033,
        ge=0,
        title="Wobble K",
        description="Wobble coefficient [1/m] (supplier's value).",
    )
    friction: float = Field(
        default=0.07,
        ge=0,
        title="Curvature friction μ",
        description="Curvature friction coefficient (supplier's value).",
    )
    anchorSet: float = Field(
        default=6, ge=0, title="Anchor set", description="Draw-in at the live end [mm]."
    )
    longTermLoss: float = Field(
        ge=0,
        title="Long-term loss",
        description="Loss of stress from creep, shrinkage and relaxation [MPa], worked out by "
        "the engineer (the automatic time-step method is planned).",
    )
    transferStrength: float | None = Field(
        default=None,
        gt=0,
        title="f'ci",
        description="Concrete strength at stressing [MPa]; empty: transfer not checked.",
    )
    profile: list[TendonPoint] = Field(
        min_length=3,
        description="CGS heights along the tendon, from the start: high over the supports, "
        "low in the spans (parabolic between them).",
    )

    @model_validator(mode="after")
    def _profile(self) -> SlabTendon:
        stations = [p.at for p in self.profile]
        if any(b <= a for a, b in pairwise(stations)):
            raise ValueError(f"{self.id}: the profile's distances must increase")
        if (self.x1, self.y1) == (self.x2, self.y2):
            raise ValueError(f"{self.id}: its start and end are the same point")
        return self


class Additions(_Model):
    """Elements the building model adds to what it is built from; rebuilding keeps them."""

    slabOpenings: list[SlabOpening] = Field(default_factory=list, title="Slab openings")
    wallOpenings: list[WallOpening] = Field(default_factory=list, title="Wall openings")
    stairs: list[Stair] = Field(default_factory=list)
    members: list[InclinedMember] = Field(default_factory=list, title="Inclined members")
    slabTendons: list[SlabTendon] = Field(
        default_factory=list, title="Slab tendons", description="Post-tensioning tendons."
    )

    def all(self) -> list[SlabOpening | WallOpening | Stair | InclinedMember | SlabTendon]:
        return [
            *self.slabOpenings,
            *self.wallOpenings,
            *self.stairs,
            *self.members,
            *self.slabTendons,
        ]


#: Tolerance of the model checks [mm].
_TOLERANCE = 1.0


def _inside(x: float, y: float, polygon: list[list[float]]) -> bool:
    """Whether (x, y) is inside ``polygon`` (even-odd rule)."""
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _on_segment(point: list[float], a: list[float], b: list[float]) -> bool:
    """Whether ``point`` lies on segment ``a``-``b`` (within the check tolerance)."""
    length = math.dist(a, b)
    if length == 0:
        return math.dist(point, a) <= _TOLERANCE
    t = ((point[0] - a[0]) * (b[0] - a[0]) + (point[1] - a[1]) * (b[1] - a[1])) / length**2
    if t < -_TOLERANCE / length or t > 1 + _TOLERANCE / length:
        return False
    foot = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return math.dist(point, foot) <= _TOLERANCE


def _placement_key(e: Any) -> tuple[Any, ...] | None:
    """Where an element is, for finding one drawn twice (rounded to the millimetre)."""

    def r(values: list[float]) -> tuple[float, ...]:
        return tuple(round(v) for v in values)

    if isinstance(e, ColumnElement):
        return ("column", r(e.position), round(e.bottom), round(e.top))
    if isinstance(e, BeamElement | WallElement):
        ends = sorted([r(e.start), r(e.end)])
        level = (round(e.elevation),) if isinstance(e, BeamElement) else (round(e.bottom),)
        return (e.kind, *ends, *level)
    if isinstance(e, SlabElement):
        return ("slab", tuple(sorted(r(p) for p in e.boundary)), round(e.elevation))
    if isinstance(e, FootingElement):
        return ("footing", r(e.position), round(e.elevation))
    return None


class BuildingModel(_Model):
    schema_: Literal["saengine.bim/2"] = Field(default=SCHEMA_ID, alias="schema")
    source: SourceStamps | None = Field(
        default=None, description="The floor plan revision the model was generated from."
    )
    stories: list[Story] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)
    additions: Additions = Field(default_factory=Additions)
    supports: list[BimSupport] = Field(
        default_factory=list, description="Supports of a special structure."
    )

    @model_validator(mode="after")
    def _references(self) -> BuildingModel:
        ids = [e.id for e in self.elements]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate element ids: {', '.join(duplicates)}")
        if len({s.id for s in self.stories}) != len(self.stories):
            raise ValueError("story ids must be unique")
        for e in self.elements:
            if e.kind in ("column", "wall") and e.bottom >= e.top:
                raise ValueError(f"{e.id}: its top must be above its bottom")
        return self

    def check_additions(self) -> list[str]:
        """Problems with what the additions refer to.

        These are reported, not rejected: the floor plan may drop a host or a story the
        additions use, and rebuilding from it must still work.
        """
        kinds = {e.id: e.kind for e in self.elements}
        stories = {s.id: s.elevation for s in self.stories}
        problems = []
        ids = [a.id for a in self.additions.all()]
        for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
            problems.append(f"{duplicate}: two additions use this id")
        for clash in sorted({i for i in ids if i in kinds}):
            problems.append(f"{clash}: an element from the floor plan already uses this id")
        for opening, kind in [
            *((o, "slab") for o in self.additions.slabOpenings),
            *((o, "wall") for o in self.additions.wallOpenings),
        ]:
            if kinds.get(opening.host) != kind:
                problems.append(f"{opening.id}: there is no {kind} '{opening.host}' to cut")
        hosts = {e.id: e for e in self.elements}
        for wall_opening in self.additions.wallOpenings:
            wall = hosts.get(wall_opening.host)
            if not isinstance(wall, WallElement):
                continue
            length = math.dist(wall.start, wall.end)
            end = wall_opening.offset + wall_opening.width
            if end > length + _TOLERANCE:
                problems.append(
                    f"{wall_opening.id}: it runs past the end of wall {wall.id} "
                    f"(offset {wall_opening.offset:g} + width {wall_opening.width:g} = {end:g} mm, "
                    f"the wall is {length:g} mm long)"
                )
            height = wall.top - wall.bottom
            if wall_opening.sill + wall_opening.height > height + _TOLERANCE:
                problems.append(
                    f"{wall_opening.id}: it is taller than wall {wall.id} "
                    f"(sill {wall_opening.sill:g} + height {wall_opening.height:g} mm, "
                    f"the wall is {height:g} mm high)"
                )
        for slab_opening in self.additions.slabOpenings:
            slab = hosts.get(slab_opening.host)
            if not isinstance(slab, SlabElement):
                continue
            if not _inside(slab_opening.x, slab_opening.y, slab.boundary):
                problems.append(
                    f"{slab_opening.id}: its centre ({slab_opening.x:g}, {slab_opening.y:g}) "
                    f"is outside slab {slab.id}"
                )
        for tendon in self.additions.slabTendons:
            slab = hosts.get(tendon.host)
            if not isinstance(slab, SlabElement):
                problems.append(f"{tendon.id}: there is no slab '{tendon.host}' to stress")
                continue
            length = math.dist((tendon.x1, tendon.y1), (tendon.x2, tendon.y2))
            if tendon.profile[-1].at > length + _TOLERANCE:
                problems.append(
                    f"{tendon.id}: its profile runs to {tendon.profile[-1].at:g} mm, past its "
                    f"length of {length:.0f} mm"
                )
        for stair in self.additions.stairs:
            missing = [s for s in (stair.base, stair.top) if s not in stories]
            if missing:
                problems.append(f"{stair.id}: no story '{missing[0]}'")
            elif stories[stair.base] >= stories[stair.top]:
                problems.append(f"{stair.id}: its top story must be above its base story")
        return problems

    def check_model(self) -> list[str]:
        """Model checks: elements drawn twice, and beams that rest on nothing at either end.

        A beam end is supported on a column, a wall or another beam at its level; a beam with
        one supported end is a cantilever and is accepted.
        """
        problems = []
        seen: dict[tuple[Any, ...], str] = {}
        for e in self.elements:
            key = _placement_key(e)
            if key is None:
                continue
            if key in seen:
                problems.append(f"{e.id}: it is drawn on top of {seen[key]} (same kind and place)")
            else:
                seen[key] = e.id
        columns = [e for e in self.elements if isinstance(e, ColumnElement)]
        walls = [e for e in self.elements if isinstance(e, WallElement)]
        beams = [e for e in self.elements if isinstance(e, BeamElement)]

        def supported(point: list[float], level: float, beam: BeamElement) -> bool:
            for c in columns:
                if c.bottom < level <= c.top + _TOLERANCE and math.dist(point, c.position) <= 1:
                    return True
            for w in walls:
                if w.bottom < level <= w.top + _TOLERANCE and _on_segment(point, w.start, w.end):
                    return True
            return any(
                other is not beam
                and abs(other.elevation - level) <= _TOLERANCE
                and _on_segment(point, other.start, other.end)
                for other in beams
            )

        for b in beams:
            if not supported(b.start, b.elevation, b) and not supported(b.end, b.elevation, b):
                problems.append(
                    f"{b.id}: neither end rests on a column, wall or beam (an unsupported beam)"
                )
        return problems

    def check_objects(self, objects: ObjectLibrary) -> list[str]:
        """Problems with object-type references, which span files."""
        kinds = {o.id: o.kind for o in objects.objects}
        problems = []
        for stair in self.additions.stairs:
            if kinds.get(stair.type) != "staircase":
                problems.append(f"{stair.id}: '{stair.type}' is not a staircase type")
        for member in self.additions.members:
            if kinds.get(member.type) not in ("brace", "beam", "column"):
                problems.append(f"{member.id}: '{member.type}' is not a brace, beam or column type")
        for e in self.elements:
            kind = kinds.get(e.type)
            if kind is None:
                problems.append(f"{e.id}: unknown object type '{e.type}'")
            elif kind not in _ALLOWED_KINDS[e.kind]:
                problems.append(f"{e.id}: object type '{e.type}' is a {kind}, not a {e.kind}")
        return problems


def generate(plan: FloorPlan, stamp: str, previous: BuildingModel | None = None) -> BuildingModel:
    """The building model of ``plan`` (whose text has stamp ``stamp``).

    Elements generated earlier are replaced; the building model's own additions (and elements
    without a ``source``, from before additions existed) are kept from ``previous``.
    """
    x = {g.label: g.position for g in plan.grids.x}
    y = {g.label: g.position for g in plan.grids.y}
    level = {s.id: s.elevation for s in plan.stories}

    def at(p: GridPoint) -> list[float]:
        return [x[p.x] + p.dx, y[p.y] + p.dy]

    elements: list[ColumnElement | BeamElement | WallElement | SlabElement | FootingElement] = []
    for c in plan.columns:
        elements.append(
            ColumnElement(
                id=c.id,
                type=c.type,
                source=c.id,
                position=at(c.at),
                bottom=level[c.base],
                top=level[c.top],
                rotation=c.rotation,
                modifiers=c.modifiers,
                designOverwrites=c.designOverwrites,
            )
        )
    for b in plan.beams:
        elements.append(
            BeamElement(
                id=b.id,
                type=b.type,
                source=b.id,
                start=at(b.start),
                end=at(b.end),
                elevation=level[b.story],
                modifiers=b.modifiers,
                designOverwrites=b.designOverwrites,
            )
        )
    for w in plan.walls:
        elements.append(
            WallElement(
                id=w.id,
                type=w.type,
                source=w.id,
                start=at(w.start),
                end=at(w.end),
                bottom=level[w.base],
                top=level[w.top],
                modifiers=w.modifiers,
            )
        )
    for s in plan.slabs:
        elements.append(
            SlabElement(
                id=s.id,
                type=s.type,
                source=s.id,
                boundary=[at(p) for p in s.boundary],
                elevation=level[s.story],
                areaLoad=s.areaLoad,
                modifiers=s.modifiers,
            )
        )
    for f in plan.footings:
        elements.append(
            FootingElement(
                id=f.id,
                type=f.type,
                source=f.id,
                position=at(f.at),
                elevation=level[f.story],
                rotation=f.rotation,
            )
        )
    own = [e for e in (previous.elements if previous else []) if e.source is None]
    taken = {e.id for e in elements}
    clashes = [e.id for e in own if e.id in taken]
    if clashes:
        raise ValueError(
            f"building-model elements use ids of floor-plan members: {', '.join(clashes)}"
        )
    return BuildingModel(
        source=SourceStamps(floorPlan=stamp),
        stories=[s.model_copy() for s in plan.stories],
        elements=[*elements, *own],
        additions=previous.additions.model_copy(deep=True) if previous else Additions(),
        supports=[s.model_copy() for s in previous.supports] if previous else [],
    )


def generate_from_structure(
    structure: StructuralModel, stamp: str, previous: BuildingModel | None = None
) -> BuildingModel:
    """The building model of a special structure (whose ``structure.json`` has stamp ``stamp``).

    Members and areas become ``member`` and ``area`` elements, supports are carried over, and the
    levels of the first grid system with any become the stories. The building model's own
    additions are kept from ``previous``.
    """
    levels = next((g.z for g in structure.grids if g.z), [])
    elements: list[Element] = [
        MemberElement(
            id=m.id,
            type=m.type,
            source=m.id,
            start=[m.start.x, m.start.y, m.start.z],
            end=[m.end.x, m.end.y, m.end.z],
            rotation=m.rotation,
        )
        for m in structure.members
    ]
    elements += [
        AreaElement(
            id=a.id,
            type=a.type,
            source=a.id,
            outline=[[p.x, p.y, p.z] for p in a.outline],
            openings=[[[p.x, p.y, p.z] for p in o.outline] for o in a.openings],
            areaLoad=a.areaLoad,
        )
        for a in structure.areas
    ]
    elements += [
        BlockElement(
            id=b.id,
            type=b.type,
            source=b.id,
            outline=[[p.x, p.y, p.z] for p in b.outline],
            thickness=b.thickness,
            supported=b.supported,
        )
        for b in structure.blocks
    ]
    own = [e for e in (previous.elements if previous else []) if e.source is None]
    return BuildingModel(
        source=SourceStamps(structure=stamp),
        stories=[Story(id=g.label, name=f"Level {g.label}", elevation=g.position) for g in levels],
        elements=[*elements, *own],
        additions=previous.additions.model_copy(deep=True) if previous else Additions(),
        supports=[
            BimSupport(id=s.id, at=[s.at.x, s.at.y, s.at.z], fixity=s.fixity)
            for s in structure.supports
        ],
    )


# ─────────────────────────────── foundations of 9 Substructure ───────────────────────────────
#
# Since Part 9, footings are placed in 9 Substructure, not in the floor plan: the foundations of
# ``09 Substructure/substructure.json`` are the building's foundation elements in the IFC and in
# the bill of quantities. :func:`foundation_solids` turns them into solids beside the building
# model's own elements; ``bim.json`` itself never stores them.


@dataclass(frozen=True)
class FoundationSolid:
    """A footing, pile cap or raft of 9 Substructure as a vertical prism."""

    id: str
    #: isolated | combined | strip | pileCap | raft
    type: str
    #: Plan outline [(x, y), ...] mm, counter-clockwise.
    outline: list[tuple[float, float]]
    bottom: float
    top: float
    material: str | None
    reinforcement: Any
    #: The run [mm] of the bars along the foundation's local x and y.
    runs: tuple[float, float]
    #: Centre, rotation [°], length and width of a rectangular foundation (not strips, rafts).
    center: tuple[float, float] | None = None
    rotation: float = 0.0
    length: float = 0.0
    width: float = 0.0

    @property
    def thickness(self) -> float:
        return self.top - self.bottom


@dataclass(frozen=True)
class PileSolid:
    """One pile of a pile cap, its head at the cap's underside."""

    id: str
    cap: str
    pile_type: str
    kind: str  # bored | driven
    x: float
    y: float
    head: float
    length: float
    diameter: float
    material: str
    reinforcement: Any


@dataclass(frozen=True)
class TieBeamSolid:
    """A tie beam: its axis from the centre of one foundation to the other's (``start``,
    ``end``), the clear pieces of it between their faces (``clear``), its top at ``level``."""

    id: str
    type: str
    start: tuple[float, float]
    end: tuple[float, float]
    clear: list[tuple[tuple[float, float], tuple[float, float]]]
    level: float

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def clear_length(self) -> float:
        return sum(math.dist(a, b) for a, b in self.clear)


@dataclass
class FoundationSolids:
    foundations: list[FoundationSolid] = field(default_factory=list)
    piles: list[PileSolid] = field(default_factory=list)
    ties: list[TieBeamSolid] = field(default_factory=list)
    #: Foundations and tie beams that could not be placed, with why.
    notes: list[str] = field(default_factory=list)


def _counter_clockwise(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    area = sum(
        a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1], strict=True)
    )
    return points if area >= 0 else points[::-1]


def foundation_solids(
    substructure: Any, building: BuildingModel, ground_level: float
) -> FoundationSolids:
    """The foundations, piles and tie beams of ``substructure`` (a
    :class:`~saengine.library.substructure.Substructure`) as solids. A foundation without a
    founding level founds 1.5 m below ``ground_level``
    (:meth:`~saengine.library.substructure.Foundation.founding_level`); one without a centre sits
    at the centroid of its columns."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union

    solids = FoundationSolids()
    positions: dict[str, tuple[float, float]] = {}
    for e in building.elements:
        if isinstance(e, ColumnElement):
            positions[e.id] = (e.position[0], e.position[1])
        elif isinstance(e, WallElement):
            positions[e.id] = ((e.start[0] + e.end[0]) / 2, (e.start[1] + e.end[1]) / 2)
    pile_types = {p.id: p for p in substructure.pileTypes}
    #: The cap of each capped pile and the level of its head (the cap's underside).
    heads: dict[str, tuple[str, float]] = {}
    plans: dict[str, Any] = {}
    centers: dict[str, tuple[float, float]] = {}
    for f in substructure.foundations:
        bottom = f.founding_level(ground_level)
        top = bottom + float(f.thickness or 0)
        if f.type in ("isolated", "combined", "pileCap"):
            if f.center is not None:
                cx, cy = float(f.center[0]), float(f.center[1])
            else:
                known = [positions[c] for c in f.columns if c in positions]
                if not known:
                    solids.notes.append(f"{f.id}: no centre, and none of its columns is in 6 BIM")
                    continue
                cx = sum(p[0] for p in known) / len(known)
                cy = sum(p[1] for p in known) / len(known)
            length, width = float(f.length or 0), float(f.width or 0)
            angle = math.radians(f.rotation)
            ux, uy = math.cos(angle), math.sin(angle)

            def at(u: float, v: float) -> tuple[float, float]:
                return (cx + u * ux - v * uy, cy + u * uy + v * ux)  # noqa: B023

            outline = [at(su * length / 2, sv * width / 2) for su, sv in _CORNERS]
            solids.foundations.append(
                FoundationSolid(
                    id=f.id,
                    type=f.type,
                    outline=outline,
                    bottom=bottom,
                    top=top,
                    material=f.material,
                    reinforcement=f.reinforcement,
                    runs=(length, width),
                    center=(cx, cy),
                    rotation=f.rotation,
                    length=length,
                    width=width,
                )
            )
            centers[f.id] = (cx, cy)
            plans[f.id] = Polygon(outline)
            for placed in substructure.cap_piles(f) if f.type == "pileCap" else []:
                heads[placed.id] = (f.id, bottom)
            continue
        if f.type == "strip":
            path = LineString([(float(p[0]), float(p[1])) for p in f.path or []])
            plan = path.buffer(float(f.width or 0) / 2, cap_style="flat", join_style="mitre")
            runs = (path.length, float(f.width or 0))
        else:  # raft
            plan = Polygon([(float(p[0]), float(p[1])) for p in f.outline or []])
            xmin, ymin, xmax, ymax = plan.bounds
            runs = (xmax - xmin, ymax - ymin)
        outline = _counter_clockwise([(float(x), float(y)) for x, y, *_ in plan.exterior.coords])
        outline = outline[:-1] if outline[0] == outline[-1] else outline
        solids.foundations.append(
            FoundationSolid(
                id=f.id,
                type=f.type,
                outline=outline,
                bottom=bottom,
                top=top,
                material=f.material,
                reinforcement=f.reinforcement,
                runs=runs,
            )
        )
        polygon = Polygon(outline)
        centers[f.id] = (polygon.centroid.x, polygon.centroid.y)
        plans[f.id] = polygon
    # Every pile placed in plan: under its cap (head at the cap's underside), or, not yet under
    # one, with its head at the default founding level (it is still built and measured).
    default_head = ground_level - 1500.0
    for placed in substructure.piles:
        pile = pile_types.get(placed.type)
        if pile is None:
            continue
        cap, head = heads.get(placed.id, (placed.id, default_head))
        if placed.id not in heads:
            solids.notes.append(f"{placed.id}: the pile is under no pile cap")
        solids.piles.append(
            PileSolid(
                id=placed.id,
                cap=cap,
                pile_type=pile.id,
                kind=pile.kind,
                x=float(placed.position[0]),
                y=float(placed.position[1]),
                head=head,
                length=pile.length,
                diameter=pile.diameter,
                material=pile.material,
                reinforcement=pile.reinforcement,
            )
        )
    tops = {s.id: s.top for s in solids.foundations}
    for tie in substructure.tieBeams:
        ends = (tie.from_, tie.to)
        if not all(end in centers for end in ends):
            solids.notes.append(f"{tie.id}: one of its foundations could not be placed")
            continue
        start, end = centers[tie.from_], centers[tie.to]
        clear = LineString([start, end]).difference(unary_union([plans[tie.from_], plans[tie.to]]))
        pieces = [
            (
                (float(g.coords[0][0]), float(g.coords[0][1])),
                (float(g.coords[-1][0]), float(g.coords[-1][1])),
            )
            for g in getattr(clear, "geoms", [clear])
            if not g.is_empty and g.length > 1
        ]
        level = tie.level if tie.level is not None else min(tops[e] for e in ends)
        solids.ties.append(TieBeamSolid(tie.id, tie.type, start, end, pieces, level))
    return solids


_CORNERS = ((-1, -1), (1, -1), (1, 1), (-1, 1))
