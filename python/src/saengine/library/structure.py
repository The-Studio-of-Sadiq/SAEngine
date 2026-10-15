"""The structural model (``05 Structural Model/structure.json``) of a special structure.

Projects of the type "special structure" (airport roofs, stadiums, towers, industrial plants,
containment buildings, bridges...) are not laid out story by story on a floor plan: the
engineer draws the structure in 3D. This file is that drawing, owned and written by Part 5
only, the way ``floor-plan.json`` is for buildings:

- grid systems to draw on: rectangular (X, Y, Z lines) and cylindrical (radii, angles, Z);
- members (beams, columns, braces, truss bars...) between two points in space;
- areas (slabs, walls, shells, roof panels) bounded by a planar polygon, with openings;
- blocks (dam sections, massive foundations, piers): a planar polygon extruded, as volumes;
- supports, where the structure meets the ground (or the substructure, Part 9).

Every member and area is an instance of an object type from ``04 Objects/objects.json``.
Downstream parts read it and never write it: the building model (``06 BIM/bim.json``) is
generated from it (:func:`saengine.library.bim.generate_from_structure`), and the analysis model
from that.

Units are fixed SI: coordinates in mm, angles in degrees; Z is up.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.floorplan import GridLine
from saengine.library.labels import field_title
from saengine.library.materials import Id
from saengine.library.objects import ObjectLibrary

SCHEMA_ID = "saengine.structure/1"

Mm = Annotated[float, Field(description="[mm]")]

#: Points closer than this are the same point; areas flatter than this are planar [mm].
TOLERANCE = 1.0


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class Point(_Model):
    """A point in space [mm]."""

    x: Mm
    y: Mm
    z: Mm = Field(description="Elevation [mm].")

    @model_validator(mode="before")
    @classmethod
    def _from_sequence(cls, value: object) -> object:
        """Scripts may write a point as ``(x, y, z)``."""
        if isinstance(value, list | tuple | np.ndarray) and len(value) == 3:
            return {"x": float(value[0]), "y": float(value[1]), "z": float(value[2])}
        return value

    def array(self) -> np.ndarray:
        return np.array([self.x, self.y, self.z], dtype=float)


class AngleLine(_Model):
    """A radial grid line of a cylindrical grid, at an angle from its X axis."""

    label: Annotated[str, Field(pattern=r"^[A-Za-z0-9.'-]+$", min_length=1, max_length=8)]
    angle: float = Field(description="Counter-clockwise from the grid's X axis [°].")


class CartesianGrid(_Model):
    """A rectangular grid system: lines along X, Y and Z (levels)."""

    kind: Literal["cartesian"] = "cartesian"
    id: Id
    name: str = ""
    origin: Point = Field(default_factory=lambda: Point(x=0, y=0, z=0))
    rotation: float = Field(default=0, description="Rotation of the grid in plan [°].")
    x: list[GridLine] = Field(default_factory=list, title="X lines")
    y: list[GridLine] = Field(default_factory=list, title="Y lines")
    z: list[GridLine] = Field(default_factory=list, title="Levels", description="Z lines.")


class CylindricalGrid(_Model):
    """A cylindrical grid system for domes, round terminals and towers: rings, radial lines
    and levels around a vertical axis through its origin."""

    kind: Literal["cylindrical"] = "cylindrical"
    id: Id
    name: str = ""
    origin: Point = Field(default_factory=lambda: Point(x=0, y=0, z=0))
    radii: list[GridLine] = Field(
        default_factory=list, title="Rings", description="Circles at radius = position [mm]."
    )
    angles: list[AngleLine] = Field(default_factory=list, title="Radial lines")
    z: list[GridLine] = Field(default_factory=list, title="Levels", description="Z lines.")


Grid = Annotated[CartesianGrid | CylindricalGrid, Field(discriminator="kind")]


class Member(_Model):
    """A straight member between two points: beam, column, brace or truss bar."""

    id: Id
    type: Id = Field(title="Object type", description="Beam, column or brace type from 04 Objects.")
    start: Point
    end: Point
    rotation: float = Field(
        default=0, description="Rotation of the section about the member's axis [°]."
    )

    @model_validator(mode="after")
    def _length(self) -> Member:
        if np.linalg.norm(self.end.array() - self.start.array()) < TOLERANCE:
            raise ValueError(f"{self.id}: its start and end are the same point")
        return self


class Opening(_Model):
    """A hole through an area, bounded by a polygon in the area's plane."""

    outline: list[Point] = Field(min_length=3)


class Area(_Model):
    """A planar area: slab, wall or shell panel, bounded by a polygon (its mid-surface)."""

    id: Id
    type: Id = Field(title="Object type", description="Slab or wall type from 04 Objects.")
    outline: list[Point] = Field(min_length=3)
    openings: list[Opening] = Field(default_factory=list)
    areaLoad: Id | None = Field(
        default=None,
        title="Area load",
        description="Area load from 02 Project Settings carried by the area (floors and roofs); "
        "none for walls and panels with self-weight only.",
    )

    @model_validator(mode="after")
    def _planar(self) -> Area:
        if plane_of([p.array() for p in self.outline]) is None:
            raise ValueError(f"{self.id}: its outline is not a flat polygon")
        return self


class Block(_Model):
    """A solid block: a flat outline extruded by its thickness, analysed as a volume. The block
    grows from its outline along the outline's normal: towards the side from which its corners
    turn counter-clockwise."""

    id: Id
    type: Id = Field(title="Object type", description="Solid type from 04 Objects.")
    outline: list[Point] = Field(min_length=3)
    thickness: Annotated[float, Field(gt=0, description="[mm]")]
    supported: bool = Field(
        default=False,
        description="Held on its outline face, as on rock or a rigid base (all of the face's "
        "points are held in every direction).",
    )

    @model_validator(mode="after")
    def _planar(self) -> Block:
        if plane_of([p.array() for p in self.outline]) is None:
            raise ValueError(f"{self.id}: its outline is not a flat polygon")
        return self

    def extrusion(self) -> np.ndarray:
        """The vector the outline is extruded along [mm]."""
        plane = plane_of([p.array() for p in self.outline])
        assert plane is not None
        return plane[1] * self.thickness


class Support(_Model):
    """Where the structure is held: a fixed or pinned support at a point."""

    id: Id
    at: Point
    fixity: Literal["fixed", "pinned"] = Field(
        default="fixed",
        description="Fixed holds translations and rotations, pinned the translations only.",
    )


class StructuralModel(_Model):
    schema_: Literal["saengine.structure/1"] = Field(default=SCHEMA_ID, alias="schema")
    grids: list[Grid] = Field(default_factory=list, title="Grid systems")
    members: list[Member] = Field(default_factory=list)
    areas: list[Area] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    supports: list[Support] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> StructuralModel:
        for label, items in (
            ("grid", self.grids),
            ("element", [*self.members, *self.areas, *self.blocks]),
            ("support", self.supports),
        ):
            ids = [i.id for i in items]
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate {label} ids: {', '.join(duplicates)}")
        return self

    def check_objects(self, objects: ObjectLibrary) -> list[str]:
        """Problems with object-type references, which span files."""
        kinds = {o.id: o.kind for o in objects.objects}
        problems = []
        for member in self.members:
            if kinds.get(member.type) not in ("beam", "column", "brace"):
                problems.append(f"{member.id}: '{member.type}' is not a beam, column or brace type")
        for area in self.areas:
            if kinds.get(area.type) not in ("slab", "wall"):
                problems.append(f"{area.id}: '{area.type}' is not a slab or wall type")
        for block in self.blocks:
            if kinds.get(block.type) != "solid":
                problems.append(f"{block.id}: '{block.type}' is not a solid type")
        return problems


def plane_of(points: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray] | None:
    """(a point, the unit normal) of the plane through ``points``, or None when they are not a
    flat polygon (fewer than three non-collinear points, or one off the plane)."""
    origin = points[0]
    normal = np.zeros(3)
    for a, b in zip(points, points[1:] + points[:1], strict=True):
        normal += np.cross(a - origin, b - origin)  # Newell's method, robust for any polygon
    size = float(np.linalg.norm(normal))
    if size < TOLERANCE**2:
        return None
    normal /= size
    if any(abs(float((p - origin) @ normal)) > TOLERANCE for p in points):
        return None
    return origin, normal


def default_structural_model() -> StructuralModel:
    """A rectangular grid of one 6 m x 5 m bay and two levels, nothing drawn yet."""

    def lines(labels: str, step: float, count: int) -> list[GridLine]:
        return [GridLine(label=labels[i], position=i * step) for i in range(count)]

    return StructuralModel(
        grids=[
            CartesianGrid(
                id="G1",
                name="Main grid",
                x=lines("ABCDEFGH", 6000, 2),
                y=lines("12345678", 5000, 2),
                z=[GridLine(label="Z0", position=0), GridLine(label="Z1", position=4000)],
            )
        ]
    )


def grid_points(grid: CartesianGrid | CylindricalGrid) -> list[np.ndarray]:
    """Every intersection of a grid's lines, in global coordinates [mm]."""
    origin = grid.origin.array()
    result = []
    if isinstance(grid, CartesianGrid):
        angle = math.radians(grid.rotation)
        ux = np.array([math.cos(angle), math.sin(angle), 0.0])
        uy = np.array([-math.sin(angle), math.cos(angle), 0.0])
        for gz in grid.z:
            for gx in grid.x:
                for gy in grid.y:
                    result.append(
                        origin + gx.position * ux + gy.position * uy + [0, 0, gz.position]
                    )
    else:
        for gz in grid.z:
            result.append(origin + [0, 0, gz.position])
            for ring in grid.radii:
                for line in grid.angles:
                    a = math.radians(line.angle)
                    result.append(
                        origin
                        + [ring.position * math.cos(a), ring.position * math.sin(a), gz.position]
                    )
    return result
