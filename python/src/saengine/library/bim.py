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
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.floorplan import FloorPlan, GridPoint, Story
from saengine.library.labels import field_title
from saengine.library.materials import Id
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


class BeamElement(_Element):
    """A beam with its top at ``elevation`` (the level of the story it supports)."""

    kind: Literal["beam"] = "beam"
    start: Point2
    end: Point2
    elevation: Mm = Field(description="Elevation of the top [mm].")


class WallElement(_Element):
    kind: Literal["wall"] = "wall"
    start: Point2
    end: Point2
    bottom: Mm = Field(description="[mm]")
    top: Mm = Field(description="[mm]")


class SlabElement(_Element):
    kind: Literal["slab"] = "slab"
    boundary: list[Point2] = Field(min_length=3)
    elevation: Mm = Field(description="Elevation of the top [mm].")


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
    | AreaElement,
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


class Additions(_Model):
    """Elements the building model adds to what it is built from; rebuilding keeps them."""

    slabOpenings: list[SlabOpening] = Field(default_factory=list, title="Slab openings")
    wallOpenings: list[WallOpening] = Field(default_factory=list, title="Wall openings")
    stairs: list[Stair] = Field(default_factory=list)
    members: list[InclinedMember] = Field(default_factory=list, title="Inclined members")

    def all(self) -> list[SlabOpening | WallOpening | Stair | InclinedMember]:
        return [*self.slabOpenings, *self.wallOpenings, *self.stairs, *self.members]


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
        for stair in self.additions.stairs:
            missing = [s for s in (stair.base, stair.top) if s not in stories]
            if missing:
                problems.append(f"{stair.id}: no story '{missing[0]}'")
            elif stories[stair.base] >= stories[stair.top]:
                problems.append(f"{stair.id}: its top story must be above its base story")
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
