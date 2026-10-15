"""The building model (``06 BIM/bim.json``): the 3D building, derived from the floor plan.

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

SCHEMA_ID = "saengine.bim/2"

Point2 = Annotated[list[float], Field(min_length=2, max_length=2, description="[x, y] in mm.")]
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

    floorPlan: str = Field(title="Floor plan", description="Stamp of floor-plan.json.")


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


Element = Annotated[
    ColumnElement | BeamElement | WallElement | SlabElement | FootingElement,
    Field(discriminator="kind"),
]

# Object kinds each element may use.
_ALLOWED_KINDS = {
    "column": ("column",),
    "beam": ("beam",),
    "wall": ("wall",),
    "slab": ("slab",),
    "footing": ("footing", "pileCap"),
}


class BuildingModel(_Model):
    schema_: Literal["saengine.bim/2"] = Field(default=SCHEMA_ID, alias="schema")
    source: SourceStamps | None = Field(
        default=None, description="The floor plan revision the model was generated from."
    )
    stories: list[Story] = Field(default_factory=list)
    elements: list[Element] = Field(default_factory=list)

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

    def check_objects(self, objects: ObjectLibrary) -> list[str]:
        """Problems with object-type references, which span files."""
        kinds = {o.id: o.kind for o in objects.objects}
        problems = []
        for e in self.elements:
            kind = kinds.get(e.type)
            if kind is None:
                problems.append(f"{e.id}: unknown object type '{e.type}'")
            elif kind not in _ALLOWED_KINDS[e.kind]:
                problems.append(f"{e.id}: object type '{e.type}' is a {kind}, not a {e.kind}")
        return problems


def generate(plan: FloorPlan, stamp: str, previous: BuildingModel | None = None) -> BuildingModel:
    """The building model of ``plan`` (whose text has stamp ``stamp``).

    Elements generated earlier are replaced; elements that belong to the building model itself
    (no ``source``) are kept from ``previous``.
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
    )
