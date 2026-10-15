"""Structural object types of a project (``04 Objects/objects.json``).

An object type is a reusable definition, like a Revit family type or an IFC ``IfcBeamType``:
"B1 250x450 with 3T20 bottom". Floor plans, the BIM model and the FEM model place
instances of these types.

Units are fixed SI: lengths and bar diameters in mm. Cross-section profiles use the IFC
profile definitions and parameter names (``IfcRectangleProfileDef.XDim`` becomes ``xDim``,
``IfcIShapeProfileDef.OverallDepth`` becomes ``overallDepth``, ...), so every profile maps
1:1 onto IFC and onto sectionproperties for section properties.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.labels import field_title
from saengine.library.materials import Category, Id, MaterialLibrary

SCHEMA_ID = "saengine.objects/1"

Length = Annotated[float, Field(gt=0, description="[mm]")]


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


# ─────────────────────────── profiles (IFC profile definitions) ───────────────────────────


class RectangleProfile(_Model):
    """IfcRectangleProfileDef: xDim is the width, yDim the depth."""

    shape: Literal["rectangle"] = "rectangle"
    xDim: Length
    yDim: Length


class CircleProfile(_Model):
    """IfcCircleProfileDef."""

    shape: Literal["circle"] = "circle"
    radius: Length


class RectangleHollowProfile(_Model):
    """IfcRectangleHollowProfileDef (box, RHS/SHS)."""

    shape: Literal["rectangleHollow"] = "rectangleHollow"
    xDim: Length
    yDim: Length
    wallThickness: Length
    outerFilletRadius: float = Field(default=0, ge=0, description="[mm]")


class CircleHollowProfile(_Model):
    """IfcCircleHollowProfileDef (pipe, CHS)."""

    shape: Literal["circleHollow"] = "circleHollow"
    radius: Length
    wallThickness: Length


class IShapeProfile(_Model):
    """IfcIShapeProfileDef (W, HE, IPE, built-up I)."""

    shape: Literal["I"] = "I"
    overallWidth: Length
    overallDepth: Length
    webThickness: Length
    flangeThickness: Length
    filletRadius: float = Field(default=0, ge=0, description="[mm]")


class TShapeProfile(_Model):
    """IfcTShapeProfileDef."""

    shape: Literal["T"] = "T"
    depth: Length
    flangeWidth: Length
    webThickness: Length
    flangeThickness: Length
    filletRadius: float = Field(default=0, ge=0, description="[mm]")


class LShapeProfile(_Model):
    """IfcLShapeProfileDef (angle)."""

    shape: Literal["L"] = "L"
    depth: Length
    width: Length
    thickness: Length
    filletRadius: float = Field(default=0, ge=0, description="[mm]")
    edgeRadius: float = Field(default=0, ge=0, description="[mm]")


class UShapeProfile(_Model):
    """IfcUShapeProfileDef (channel)."""

    shape: Literal["U"] = "U"
    depth: Length
    flangeWidth: Length
    webThickness: Length
    flangeThickness: Length
    filletRadius: float = Field(default=0, ge=0, description="[mm]")


Profile = Annotated[
    RectangleProfile
    | CircleProfile
    | RectangleHollowProfile
    | CircleHollowProfile
    | IShapeProfile
    | TShapeProfile
    | LShapeProfile
    | UShapeProfile,
    Field(discriminator="shape"),
]

# ─────────────────────────────────── reinforcement ───────────────────────────────────


class BarGroup(_Model):
    """Longitudinal bars of a linear member."""

    position: Literal["top", "bottom", "sides", "perimeter"] = Field(
        description="top/bottom/sides for beams, perimeter for columns and piles."
    )
    count: int = Field(gt=0)
    dia: Length


class Transverse(_Model):
    type: Literal["stirrup", "tie", "spiral"]
    dia: Length
    spacing: Length
    legs: int = Field(default=2, ge=1)


class LinearReinforcement(_Model):
    material: Id
    cover: Length = Field(description="Clear cover to the transverse bars [mm].")
    longitudinal: list[BarGroup] = Field(default_factory=list)
    transverse: Transverse | None = None


class BarMesh(_Model):
    """One layer of bars in one direction of a planar member."""

    dia: Length
    spacing: Length


class PlanarReinforcement(_Model):
    """Bottom/top layers in the member's local x and y (slabs, footings, pile caps)."""

    material: Id
    cover: Length
    bottomX: BarMesh | None = None
    bottomY: BarMesh | None = None
    topX: BarMesh | None = None
    topY: BarMesh | None = None


class WallReinforcement(_Model):
    material: Id
    cover: Length
    vertical: BarMesh | None = None
    horizontal: BarMesh | None = None
    layers: Literal[1, 2] = 2


class StairReinforcement(_Model):
    material: Id
    cover: Length
    main: BarMesh
    distribution: BarMesh


# ─────────────────────────────────── object types ───────────────────────────────────


class _ObjectBase(_Model):
    id: Id
    name: str = Field(min_length=1)
    material: Id
    description: str | None = None


class Beam(_ObjectBase):
    kind: Literal["beam"] = "beam"
    profile: Profile
    reinforcement: LinearReinforcement | None = None


class Column(_ObjectBase):
    kind: Literal["column"] = "column"
    profile: Profile
    reinforcement: LinearReinforcement | None = None


class Brace(_ObjectBase):
    """Bracing and truss members."""

    kind: Literal["brace"] = "brace"
    profile: Profile


class Slab(_ObjectBase):
    kind: Literal["slab"] = "slab"
    thickness: Length
    system: Literal["oneWay", "twoWay", "flat"] = "twoWay"
    reinforcement: PlanarReinforcement | None = None


class Wall(_ObjectBase):
    kind: Literal["wall"] = "wall"
    thickness: Length
    structural: bool = Field(
        default=True, description="False for partition/infill walls that carry no lateral load."
    )
    reinforcement: WallReinforcement | None = None


class Staircase(_ObjectBase):
    """Waist-slab staircase flight."""

    kind: Literal["staircase"] = "staircase"
    waistThickness: Length
    riser: Length
    tread: Length
    flightWidth: Length
    reinforcement: StairReinforcement | None = None


class Footing(_ObjectBase):
    kind: Literal["footing"] = "footing"
    footingType: Literal["isolated", "combined", "strip"] = "isolated"
    length: Length = Field(description="Plan dimension along local x [mm].")
    width: Length = Field(description="Plan dimension along local y [mm].")
    thickness: Length
    reinforcement: PlanarReinforcement | None = None


class PileCap(_ObjectBase):
    kind: Literal["pileCap"] = "pileCap"
    length: Length
    width: Length
    thickness: Length
    pile: Id | None = Field(default=None, description="Id of the pile type under the cap.")
    pileCount: int | None = Field(default=None, ge=1)
    reinforcement: PlanarReinforcement | None = None


class Pile(_ObjectBase):
    kind: Literal["pile"] = "pile"
    pileType: Literal["bored", "driven", "precast"]
    profile: Profile
    length: Length
    reinforcement: LinearReinforcement | None = None


class Solid(_ObjectBase):
    """The material of solid blocks of special structures (dam sections, massive foundations,
    piers, thick containment walls), analysed as volumes."""

    kind: Literal["solid"] = "solid"


ObjectType = Annotated[
    Beam | Column | Brace | Slab | Wall | Staircase | Footing | PileCap | Pile | Solid,
    Field(discriminator="kind"),
]


class ObjectLibrary(_Model):
    schema_: Literal["saengine.objects/1"] = Field(default=SCHEMA_ID, alias="schema")
    objects: list[ObjectType] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> ObjectLibrary:
        ids = [o.id for o in self.objects]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate object ids: {', '.join(duplicates)}")
        piles = {o.id for o in self.objects if isinstance(o, Pile)}
        for o in self.objects:
            if isinstance(o, PileCap) and o.pile and o.pile not in piles:
                raise ValueError(f"pile cap '{o.id}' refers to unknown pile type '{o.pile}'")
        return self

    def check_materials(self, materials: MaterialLibrary) -> list[str]:
        """Problems with material references, which span the two files."""
        problems: list[str] = []
        for o in self.objects:
            if materials.get(o.material) is None:
                problems.append(f"{o.id}: unknown material '{o.material}'")
            reinforcement = getattr(o, "reinforcement", None)
            if reinforcement is not None:
                bars = materials.get(reinforcement.material)
                if bars is None:
                    problems.append(
                        f"{o.id}: unknown reinforcement material '{reinforcement.material}'"
                    )
                elif bars.category != Category.REBAR:
                    problems.append(f"{o.id}: reinforcement material '{bars.id}' is not rebar")
        return problems
