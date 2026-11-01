"""The floor plan (``05 Floor Plan/floor-plan.json``): grids, stories and the members placed on them.

It is the layout of the building, owned and written by Part 5 only. Grid lines are IFC's
``IfcGridAxis``, stories ``IfcBuildingStorey`` levels (an elevation; a story's height is the
distance to the next one), and every member is an instance of an object type from
``04 Objects/objects.json``. Members are placed on the grid ("column at A-1", "beam from A-1 to
B-1") with optional offsets, so moving a grid line moves everything on it.

Downstream parts read it and never write it: the building model (``06 BIM/bim.json``, see
:mod:`saengine.library.bim`) is generated from it.

Units are fixed SI: positions, elevations and offsets in mm, rotations in degrees.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from saengine.library.labels import field_title
from saengine.library.materials import Id
from saengine.library.modifiers import (
    BeamCorbels,
    DesignOverwrites,
    FrameModifiers,
    ShellModifiers,
)
from saengine.library.objects import ObjectLibrary

SCHEMA_ID = "saengine.floorPlan/1"

Label = Annotated[str, Field(pattern=r"^[A-Za-z0-9.'-]+$", min_length=1, max_length=8)]
Mm = Annotated[float, Field(description="[mm]")]


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class GridLine(_Model):
    """One grid line (IfcGridAxis): X lines are vertical in plan, Y lines horizontal."""

    label: Label
    position: Mm = Field(description="Distance from the origin along the axis [mm].")


class Grids(_Model):
    x: list[GridLine] = Field(
        default_factory=list,
        title="X grid lines",
        description="Lines at x = position, labelled A, B, C, ...",
    )
    y: list[GridLine] = Field(
        default_factory=list,
        title="Y grid lines",
        description="Lines at y = position, labelled 1, 2, 3, ...",
    )

    @model_validator(mode="after")
    def _distinct(self) -> Grids:
        labels = [g.label for g in self.x + self.y]
        duplicates = sorted({label for label in labels if labels.count(label) > 1})
        if duplicates:
            raise ValueError(
                f"grid labels must be unique across both axes: {', '.join(duplicates)}"
            )
        for axis, lines in (("X", self.x), ("Y", self.y)):
            positions = [g.position for g in lines]
            if len(set(positions)) != len(positions):
                raise ValueError(f"two {axis} grid lines are at the same position")
        return self


class Story(_Model):
    """A building level (IfcBuildingStorey); its height is the distance to the next level up."""

    id: Id
    name: str = Field(min_length=1)
    elevation: Mm = Field(description="Level of the top of the floor [mm].")
    similarTo: Id | None = Field(
        default=None,
        title="Similar to",
        description="A typical floor: the story whose plan this one repeats (ETABS's similar "
        "stories). The floor plan copies every edit to the master and its similar stories; "
        "their members are still written out on each story.",
    )


class GridPoint(_Model):
    """A grid intersection, optionally offset; follows the grid lines when they move."""

    x: Label = Field(description="X grid line label, e.g. A.")
    y: Label = Field(description="Y grid line label, e.g. 1.")
    dx: Mm = Field(default=0, title="Offset X")
    dy: Mm = Field(default=0, title="Offset Y")


class _Placed(_Model):
    id: Id
    type: Id = Field(title="Object type", description="Object type id from 04 Objects.")


class PlacedColumn(_Placed):
    at: GridPoint
    base: Id = Field(description="Story the column starts at.")
    top: Id = Field(description="Story the column ends at.")
    rotation: float = Field(default=0, description="Rotation of the section about its axis [°].")
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


class PlacedBeam(_Placed):
    story: Id
    start: GridPoint
    end: GridPoint
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
    corbels: BeamCorbels | None = Field(
        default=None,
        title="Corbels",
        description="Corbels under the beam's ends, designed by the default pack's Part 6 Sec 6.4.7.",
    )


class PlacedWall(_Placed):
    base: Id
    top: Id
    start: GridPoint
    end: GridPoint
    modifiers: ShellModifiers | None = Field(
        default=None,
        title="Stiffness modifiers",
        description="Factors on the analysis shell stiffness, mass and weight (empty: the "
        "code's cracked factors for concrete and masonry, else 1).",
    )


class PlacedSlab(_Placed):
    story: Id
    boundary: list[GridPoint] = Field(
        min_length=3, description="Corners, in order around the slab."
    )
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


class PlacedFooting(_Placed):
    story: Id = Field(description="Story whose level is the top of the footing.")
    at: GridPoint
    rotation: float = Field(default=0, description="[°]")


class Underlay(_Model):
    """An architect's drawing shown, greyed and read-only, under one story's plan.

    A PDF shows one page's vector linework (``saengine.library.pdf_underlay``) in paper mm, so its
    ``scale`` is the drawing's scale (100 for 1:100), set by calibrating two points against a
    known length on the floor plan."""

    story: Id = Field(description="Story whose plan shows the drawing.")
    file: str = Field(
        min_length=1,
        pattern=r"\.([dD]([xX][fF]|[wW][gG])|[pP][dD][fF])$",
        description="DXF, DWG or PDF file, relative to the 05 Floor Plan folder.",
    )
    page: int = Field(default=1, ge=1, description="A PDF's page shown (from 1).")
    dx: Mm = Field(default=0, title="Offset X", description="Where the drawing's origin goes [mm].")
    dy: Mm = Field(default=0, title="Offset Y", description="[mm]")
    scale: float = Field(
        default=1, gt=0, description="Drawing units to mm, e.g. 1000 for a drawing in metres."
    )
    rotation: float = Field(default=0, description="[°]")
    visible: bool = True
    locked: bool = Field(
        default=False,
        description="Locked: moving, rotating and calibrating the underlay are turned off.",
    )

    @field_validator("file")
    @classmethod
    def _inside_project(cls, value: str) -> str:
        parts = value.replace("\\", "/").split("/")
        if value.startswith(("/", "\\")) or ":" in value or ".." in parts:
            raise ValueError("the file must be inside the 05 Floor Plan folder (a relative path)")
        return value


class Tower(_Model):
    """One tower of a building with several towers on a common podium: the plan region whose
    floors above the podium move on their own (a rigid diaphragm per tower and storey) and whose
    drift, period and base shear are checked on their own (``saengine.fem.towers``)."""

    id: Id
    name: str = Field(min_length=1)
    boundary: list[GridPoint] = Field(
        min_length=3,
        description="Corners of the tower's plan region, in order around it; the floors inside "
        "it above the podium belong to the tower.",
    )


# Object kinds each member may use.
_ALLOWED_KINDS = {
    "columns": ("column",),
    "beams": ("beam",),
    "walls": ("wall",),
    "slabs": ("slab",),
    "footings": ("footing", "pileCap"),
}


class FloorPlan(_Model):
    schema_: Literal["saengine.floorPlan/1"] = Field(default=SCHEMA_ID, alias="schema")
    grids: Grids = Field(default_factory=Grids)
    stories: list[Story] = Field(default_factory=list)
    columns: list[PlacedColumn] = Field(default_factory=list)
    beams: list[PlacedBeam] = Field(default_factory=list)
    walls: list[PlacedWall] = Field(default_factory=list)
    slabs: list[PlacedSlab] = Field(default_factory=list)
    footings: list[PlacedFooting] = Field(default_factory=list)
    underlays: list[Underlay] = Field(
        default_factory=list, description="Architects' drawings under the story plans."
    )
    podiumTop: Id | None = Field(
        default=None,
        title="Podium top",
        description="Several towers on one podium: the story at the top of the podium. The "
        "floors above it are split into the towers.",
    )
    towers: list[Tower] = Field(
        default_factory=list,
        description="The towers above the podium, each a plan region (needs a podium top).",
    )

    def members(self) -> list[tuple[str, _Placed]]:
        return [(group, m) for group in _ALLOWED_KINDS for m in getattr(self, group)]

    @model_validator(mode="after")
    def _references(self) -> FloorPlan:
        story_ids = [s.id for s in self.stories]
        if len(set(story_ids)) != len(story_ids):
            raise ValueError("story ids must be unique")
        if len({s.elevation for s in self.stories}) != len(self.stories):
            raise ValueError("two stories are at the same elevation")
        member_ids = [m.id for _, m in self.members()]
        duplicates = sorted({i for i in member_ids if member_ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate member ids: {', '.join(duplicates)}")

        for s in self.stories:
            if s.similarTo is None:
                continue
            master = next((m for m in self.stories if m.id == s.similarTo), None)
            if master is None:
                raise ValueError(f"story {s.id}: no story '{s.similarTo}' to be similar to")
            if master.id == s.id:
                raise ValueError(f"story {s.id} cannot be similar to itself")
            if master.similarTo is not None:
                raise ValueError(
                    f"story {s.id} is similar to {master.id}, which is itself similar to "
                    f"{master.similarTo}; make it similar to {master.similarTo}"
                )

        x_labels = {g.label for g in self.grids.x}
        y_labels = {g.label for g in self.grids.y}
        elevation = {s.id: s.elevation for s in self.stories}

        def point(member: _Placed, p: GridPoint) -> None:
            if p.x not in x_labels:
                raise ValueError(f"{member.id}: no X grid line '{p.x}'")
            if p.y not in y_labels:
                raise ValueError(f"{member.id}: no Y grid line '{p.y}'")

        def story(member: _Placed, story_id: str) -> None:
            if story_id not in elevation:
                raise ValueError(f"{member.id}: no story '{story_id}'")

        if self.podiumTop is not None and self.podiumTop not in elevation:
            raise ValueError(f"podium top: no story '{self.podiumTop}'")
        if self.towers and self.podiumTop is None:
            raise ValueError("towers need a podium top story")
        tower_ids = [t.id for t in self.towers]
        if len(set(tower_ids)) != len(tower_ids):
            raise ValueError("tower ids must be unique")
        for tower in self.towers:
            for corner in tower.boundary:
                if corner.x not in x_labels:
                    raise ValueError(f"tower {tower.id}: no X grid line '{corner.x}'")
                if corner.y not in y_labels:
                    raise ValueError(f"tower {tower.id}: no Y grid line '{corner.y}'")

        for underlay in self.underlays:
            if underlay.story not in elevation:
                raise ValueError(f"underlay {underlay.file}: no story '{underlay.story}'")
        underlay_stories = [u.story for u in self.underlays]
        if len(set(underlay_stories)) != len(underlay_stories):
            raise ValueError("each story can have one underlay")

        for _, member in self.members():
            for field in ("story", "base", "top"):
                if hasattr(member, field):
                    story(member, getattr(member, field))
            for field in ("at", "start", "end"):
                if hasattr(member, field):
                    point(member, getattr(member, field))
            for corner in getattr(member, "boundary", []):
                point(member, corner)
            if hasattr(member, "base") and elevation[member.base] >= elevation[member.top]:
                raise ValueError(f"{member.id}: its top story must be above its base story")
        return self

    def check_objects(self, objects: ObjectLibrary) -> list[str]:
        """Problems with object-type references, which span files."""
        kinds = {o.id: o.kind for o in objects.objects}
        problems = []
        for group, member in self.members():
            kind = kinds.get(member.type)
            if kind is None:
                problems.append(f"{member.id}: unknown object type '{member.type}'")
            elif kind not in _ALLOWED_KINDS[group]:
                problems.append(
                    f"{member.id}: object type '{member.type}' is a {kind}, not a {group[:-1]}"
                )
        return problems
