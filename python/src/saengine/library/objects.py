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


class TransverseZone(_Model):
    """The end zones of a beam or column where the seismic detailing asks for closer hoops
    (BNBC 2020 Part 6 Sec 8.3.4.3, 8.3.5.4, 8.3.9.2, 8.3.10.4, 8.3.10.5)."""

    spacing: Length = Field(description="Hoop or tie spacing within the zone (so) [mm].")
    length: float | None = Field(
        default=None,
        gt=0,
        description="Zone length from each joint face (lo) [mm]; none: the length the code "
        "requires.",
    )
    first: float | None = Field(
        default=None, gt=0, description="First hoop or tie from the joint face [mm]."
    )


class SpliceZone(_Model):
    """Hoops or ties over the lap splices (BNBC 2020 Part 6 Sec 8.3.4.2(b), Figure 6.8.8)."""

    spacing: Length = Field(description="Spacing over the lap splices [mm].")


class Transverse(_Model):
    type: Literal["stirrup", "tie", "spiral"]
    dia: Length
    spacing: Length = Field(
        description="Spacing outside the end zones (all along without zones) [mm]."
    )
    legs: int = Field(default=2, ge=1)
    legsX: int | None = Field(
        default=None,
        ge=1,
        title="Legs along x",
        description="Column ties: legs running along the profile's x, counted down its depth "
        "(none: as many as legs, which run along y).",
    )
    zone: TransverseZone | None = Field(
        default=None,
        title="End zones",
        description="Closer hoops or ties at the member ends (seismic detailing); none: one "
        "spacing all along.",
    )
    splice: SpliceZone | None = Field(default=None, title="Over lap splices")


SeismicRole = Literal["auto", "lateral", "gravity"]
OmegaCombinations = Literal["auto", "transfer", "collector", "none"]


def _role() -> SeismicRole:
    return Field(
        default="auto",
        title="Seismic role",
        description="Part of the seismic force-resisting system (lateral) or not (gravity, BNBC "
        "Sec 8.3.12); auto: by the structural system.",
    )


def _omega() -> OmegaCombinations:
    return Field(
        default="auto",
        title="Ω0 combinations",
        description="Overstrength combinations (BNBC Sec 2.5.5.6, 2.5.13.4): transfer members "
        "under discontinuous columns or walls, collectors; auto: transfer members are found.",
    )


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


class BoundaryHoops(_Model):
    """Hoops and crossties of a wall's boundary element (BNBC 2020 Part 6 Sec 8.3.6.6(d)(iii),
    8.3.5.4), or its end ties (8.3.6.6(e)(i))."""

    dia: Length = 10
    spacing: Length = Field(default=100, description="Vertical spacing [mm].")
    legsAcross: int = Field(
        default=2,
        ge=2,
        title="Legs across",
        description="Legs running across the thickness, counted along the length.",
    )
    legsAlong: int = Field(
        default=2,
        ge=2,
        title="Legs along",
        description="Legs running along the length, counted across the thickness.",
    )


class WallBoundary(_Model):
    """Bars at each end of a wall: a boundary element of a special structural wall (BNBC 2020
    Part 6 Sec 8.3.6.6), or end bars with ties; the same at both ends."""

    length: Length = Field(description="From the wall's end [mm].")
    count: int = Field(gt=0, description="Vertical bars per end, in two rows along the faces.")
    dia: Length
    hoop: BoundaryHoops | None = Field(default=None, title="Hoops")


class CouplingDiagonal(_Model):
    """One of the two groups of diagonal bars of the coupling beams (spandrels over openings) of
    a special structural wall (BNBC 2020 Part 6 Sec 8.3.6.7)."""

    count: int = Field(ge=4, description="Bars per group (at least four, 8.3.6.7(d)(ii)).")
    dia: Length
    angle: float | None = Field(
        default=None,
        gt=0,
        lt=90,
        description="Angle to the beam's axis [°]; none: from the depth and span.",
    )


class WallReinforcement(_Model):
    material: Id
    cover: Length
    vertical: BarMesh | None = None
    horizontal: BarMesh | None = None
    layers: Literal[1, 2] = 2
    boundary: WallBoundary | None = Field(
        default=None,
        title="End bars",
        description="Boundary elements or end bars with ties at each end of the wall; none: "
        "the web bars only.",
    )
    diagonal: CouplingDiagonal | None = Field(
        default=None,
        title="Coupling beam diagonals",
        description="Diagonal bars of the spandrels between piers (special walls).",
    )


class StairReinforcement(_Model):
    material: Id
    cover: Length
    main: BarMesh
    distribution: BarMesh
    top: BarMesh | None = Field(
        default=None, description="Top bars over ends entered as continuous; none: no top bars."
    )
    landing: BarMesh | None = Field(
        default=None,
        description="Main bars of landings spanning across the flights; none: the main mesh.",
    )


# ───────────────────────────── simple steel connections ─────────────────────────────
# Checked by saengine.design.steel_connections (BNBC 2020 Part 6 Sec 10.10); the models live
# here so the beam and brace types can carry them.

BoltDiameter = Literal[16, 20, 22, 24, 27, 30, 36]
BoltGrade = Literal["A307", "A325N", "A325X", "A490N", "A490X", "8.8", "10.9"]


class _Bolted(_Model):
    boltGrade: BoltGrade = Field(default="A325N", description="Table 6.10.10 grade.")
    boltDiameter: BoltDiameter = Field(default=20, description="[mm]")
    rows: int = Field(default=3, ge=1, le=20, description="Bolts in a line.")
    pitch: float = Field(default=70, gt=0, description="Bolt spacing along the line [mm].")
    endDistance: float = Field(
        default=35, gt=0, description="Last bolt to the plate edge, along the line [mm]."
    )
    edgeDistance: float = Field(
        default=35, gt=0, description="Bolt line to the plate edge, across the line [mm]."
    )
    plateThickness: float = Field(default=10, gt=0, description="[mm]")
    plateMaterial: str | None = Field(
        default=None, description="03 Materials id; none: the member's material."
    )
    weldSize: float = Field(default=6, gt=0, description="Fillet weld leg [mm].")
    electrode: float = Field(default=480, gt=0, description="FEXX [MPa] (E70XX ~ 480).")
    shearedEdges: bool = Field(
        default=False, description="Sheared plate edges (else rolled or thermally cut)."
    )


class FinPlateConnection(_Bolted):
    """Single (fin) plate welded to the support, one line of bolts through the beam web."""

    type: Literal["finPlate"] = "finPlate"
    boltLineOffset: float = Field(
        default=60, gt=0, description="Support face (weld) to the bolt line, a [mm]."
    )


class EndPlateConnection(_Bolted):
    """Shear end plate welded to the beam web, two lines of bolts to the support."""

    type: Literal["endPlate"] = "endPlate"
    gauge: float = Field(default=90, gt=0, description="Between the two bolt lines [mm].")
    supportThickness: float | None = Field(
        default=None, gt=0, description="Support flange/plate [mm]; none: the end plate."
    )


class BraceGussetConnection(_Bolted):
    """Brace end bolted to a gusset plate welded to the frame."""

    type: Literal["gusset"] = "gusset"
    lines: int = Field(default=2, ge=1, le=4, description="Bolt lines across the brace.")
    gauge: float = Field(default=60, gt=0, description="Between bolt lines [mm].")
    shearPlanes: int = Field(default=1, ge=1, le=2)
    tabThickness: float | None = Field(
        default=None, gt=0, description="Brace tab plate [mm] (hollow, I braces); none: gusset."
    )
    tabWelds: int = Field(default=4, ge=2, le=4, description="Fillet welds of the tab.")
    tabWeldLength: float = Field(default=150, gt=0, description="[mm]")
    gussetWeldLength: float = Field(
        default=300, gt=0, description="Gusset-to-frame weld, each side [mm]."
    )
    gussetFreeLength: float = Field(
        default=150, gt=0, description="Unbraced gusset length beyond the bolts [mm]."
    )
    gussetK: float = Field(default=0.65, gt=0, description="Gusset buckling K.")


SteelConnection = Annotated[
    FinPlateConnection | EndPlateConnection | BraceGussetConnection,
    Field(discriminator="type"),
]


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
    seismicRole: SeismicRole = _role()
    omegaCombinations: OmegaCombinations = _omega()
    connection: SteelConnection | None = Field(
        default=None,
        description="Steel beams: the simple shear connection at both ends (fin plate or end "
        "plate); none: not checked.",
    )


class Column(_ObjectBase):
    kind: Literal["column"] = "column"
    profile: Profile
    reinforcement: LinearReinforcement | None = None
    seismicRole: SeismicRole = _role()
    omegaCombinations: OmegaCombinations = _omega()


class Brace(_ObjectBase):
    """Bracing and truss members."""

    kind: Literal["brace"] = "brace"
    profile: Profile
    connection: SteelConnection | None = Field(
        default=None,
        description="Steel braces: the bolted gusset connection at both ends; none: not checked.",
    )


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
    braced: bool = Field(
        default=True,
        description="Braced top and bottom against lateral translation (BNBC 6.6.5.2).",
    )
    restrainedEnds: bool = Field(
        default=True,
        title="Restrained ends",
        description="Restrained against rotation at one or both ends (BNBC 6.6.5.2).",
    )
    basement: bool = Field(
        default=False,
        description="Exterior basement or foundation wall (BNBC 6.6.3.4, 6.6.5.3).",
    )


class Staircase(_ObjectBase):
    """Waist-slab staircase: a straight flight, or two flights with a half landing."""

    kind: Literal["staircase"] = "staircase"
    waistThickness: Length
    riser: Length
    tread: Length
    flightWidth: Length
    reinforcement: StairReinforcement | None = None
    arrangement: Literal["straight", "dogLegged"] = Field(
        default="straight",
        description="One flight from story to story, or two with a half landing between them.",
    )
    spanning: Literal["betweenBeams", "landingEdges", "withLandings", "landingsThreeSides"] = Field(
        default="betweenBeams",
        description="How the flights span (BNBC 2020 Part 6 Sec 6.7.1.1 (a)-(d)).",
    )
    landingLength: float | None = Field(
        default=None,
        gt=0,
        title="Landing length",
        description="Landing depth along the travel [mm]; none: the flight width.",
    )
    landingThickness: float | None = Field(
        default=None, gt=0, title="Landing thickness", description="[mm]; none: the waist."
    )
    supportWidth: float = Field(
        default=250,
        ge=0,
        title="Support width",
        description="Width of the supporting beams or walls [mm].",
    )
    bottomEnd: Literal["simple", "continuous"] = Field(default="simple", title="Bottom end")
    topEnd: Literal["simple", "continuous"] = Field(default="simple", title="Top end")
    wellWidth: float = Field(
        default=0,
        ge=0,
        title="Well width",
        description="Gap between the flights of a dog-legged stair [mm].",
    )
    headroom: float | None = Field(
        default=None, gt=0, description="Clear headroom provided [mm]; none: not checked."
    )


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
