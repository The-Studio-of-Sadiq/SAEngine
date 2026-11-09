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
from saengine.library.modifiers import (  # noqa: F401 - MomentMagnifiers: for the editors
    BuiltUpMember,
    Corbel,
    DesignOverwrites,
    FrameModifiers,
    MomentMagnifiers,
    ShellModifiers,
)

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


class CShapeProfile(_Model):
    """IfcCShapeProfileDef: a cold-formed lipped channel (alpha 9 C12). ``depth`` and ``width``
    are overall, ``girth`` the overall lip length, ``wallThickness`` the sheet thickness."""

    shape: Literal["C"] = "C"
    depth: Length
    width: Length
    wallThickness: Length
    girth: Length
    internalFilletRadius: float = Field(default=0, ge=0, description="[mm]")


class ZShapeProfile(_Model):
    """A cold-formed lipped Z (alpha 9 C12; the lips of IfcCShapeProfileDef on the flanges of an
    IfcZShapeProfileDef, exported as an arbitrary profile): equal flanges ``width`` each side of
    the web, overall ``depth``, overall lip length ``girth``, sheet ``wallThickness``."""

    shape: Literal["Z"] = "Z"
    depth: Length
    width: Length
    wallThickness: Length
    girth: Length
    internalFilletRadius: float = Field(default=0, ge=0, description="[mm]")


class DesignedProfile(_Model):
    """A section drawn in the Section Designer (``04 Objects/sections/<section>.json``, see
    :mod:`saengine.library.section_designer`): L/T/C columns, core walls, built-up steel; IFC
    IfcArbitraryProfileDefWithVoids."""

    shape: Literal["designed"] = "designed"
    section: Id = Field(description="Id of the designed section (04 Objects/sections).")


Profile = Annotated[
    RectangleProfile
    | CircleProfile
    | RectangleHollowProfile
    | CircleHollowProfile
    | IShapeProfile
    | TShapeProfile
    | LShapeProfile
    | UShapeProfile
    | CShapeProfile
    | ZShapeProfile
    | DesignedProfile,
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
    (the default pack's Part 6 Sec 8.3.4.3, 8.3.5.4, 8.3.9.2, 8.3.10.4, 8.3.10.5)."""

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
    """Hoops or ties over the lap splices (the default pack's Part 6 Sec 8.3.4.2(b), Figure 6.8.8)."""

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
    splice: SpliceZone | None = Field(default=None, title="Lap splices")


SeismicRole = Literal["auto", "lateral", "gravity"]
OmegaCombinations = Literal["auto", "transfer", "collector", "none"]


def _role() -> SeismicRole:
    return Field(
        default="auto",
        title="Seismic role",
        description="Part of the seismic force-resisting system (lateral) or not (gravity, the default pack's "
        "Sec 8.3.12); auto: by the structural system.",
    )


def _omega() -> OmegaCombinations:
    return Field(
        default="auto",
        title="Ω0 combinations",
        description="Overstrength combinations (the default pack's Sec 2.5.5.6, 2.5.13.4): transfer members "
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


class ChordBars(_Model):
    """Continuous bars along a slab's free edges (the floor's edges without an edge beam), lapped
    as tension bars, that carry the diaphragm chord force with the slab's own bars parallel to
    the edge within the edge strip (:mod:`saengine.design.diaphragms`)."""

    count: int = Field(gt=0, description="Bars along each free edge (top and bottom together).")
    dia: Length


class PlanarReinforcement(_Model):
    """Bottom/top layers in the member's local x and y (slabs, footings, pile caps)."""

    material: Id
    cover: Length
    bottomX: BarMesh | None = None
    bottomY: BarMesh | None = None
    topX: BarMesh | None = None
    topY: BarMesh | None = None
    chordBars: ChordBars | None = Field(
        default=None,
        title="Chord bars",
        description="Slabs: extra bars along every free edge of the floor (no edge beam), as "
        "the diaphragm chord; empty: none (the slab's own bars in the edge strip count).",
    )


class PunchingReinforcement(_Model):
    """Shear reinforcement for punching around each column of a flat slab or footing: headed
    shear studs (the default pack's Part 6 Sec 6.4.10.5) or stirrups (6.4.10.3), in peripheral lines
    parallel to the column faces (:mod:`saengine.design.punching`). Checked only where the
    concrete alone is not enough."""

    kind: Literal["studs", "stirrups"] = Field(
        default="studs",
        description="Headed shear studs (6.4.10.5) or stirrup legs (6.4.10.3, d >= 150 mm).",
        json_schema_extra={"enumDescriptions": ["Headed shear studs", "Stirrups"]},
    )
    dia: Length = Field(default=12, description="Stud shank or stirrup bar diameter [mm].")
    perLine: int = Field(
        default=8,
        ge=4,
        title="Per line",
        description="Studs (or stirrup legs) on one peripheral line round the column.",
    )
    lines: int = Field(default=4, ge=1, description="Peripheral lines out from the column.")
    firstLine: Length = Field(
        default=50,
        title="First line",
        description="Distance of the first line from the column face [mm] (at most d/2).",
    )
    spacing: Length = Field(description="Between the lines [mm] (at most 0.75 d or 0.5 d).")
    fyt: float | None = Field(
        default=None,
        gt=0,
        description="Yield strength [MPa]; empty: 350 for studs, the slab bars' (at most 420) "
        "for stirrups.",
    )


class DropPanel(_Model):
    """A thickening of a flat slab under every column it sits on (the default pack's Part 6 Sec 6.5;
    ACI 318-19 8.2.4): a rectangle centred on the column, in the column's axes."""

    depth: Length = Field(
        description="Projection below the slab's soffit [mm] (at least a quarter of the slab "
        "thickness to count as a drop panel)."
    )
    length: Length = Field(
        description="Plan dimension along the column's local x [mm] (at least a sixth of the "
        "span each way from the column's centre line)."
    )
    width: Length = Field(description="Plan dimension along the column's local y [mm].")


class ColumnCapital(_Model):
    """A flared column head under the slab (or under its drop panel) at every column the slab
    sits on: square in plan, widening from the column to ``size`` over ``depth`` (the default pack (BNBC 2020)
    Part 6 Sec 6.5; ACI 318-11 13.1.2: only the part inside a 90° cone or pyramid from the
    column counts)."""

    size: Length = Field(
        description="Plan dimension of the capital where it meets the slab or drop panel [mm]."
    )
    depth: Length = Field(description="Depth of the flare below the slab or drop panel [mm].")


class SlabRibs(_Model):
    """Ribs under the slab: a ribbed (one-way joist) slab, or a waffle slab with ribs both ways
    (the default pack's Part 6 joist construction; ACI 318-19 9.8.1). The slab's thickness is then the
    topping over the ribs."""

    direction: Literal["x", "y", "both"] = Field(
        default="both",
        description="Ribs along the slab's local x, along y (ribbed), or both ways (waffle).",
        json_schema_extra={
            "enumDescriptions": ["Ribs along x (ribbed)", "Ribs along y (ribbed)", "Waffle"]
        },
    )
    width: Length = Field(default=125, description="Width of a rib's web [mm] (at least 100).")
    depth: Length = Field(
        default=300,
        description="Depth of a rib below the topping [mm] (at most 3.5 times its width).",
    )
    spacing: Length = Field(
        default=750,
        description="Centre-to-centre spacing of the ribs [mm] (clear spacing at most 750).",
    )


class BoundaryHoops(_Model):
    """Hoops and crossties of a wall's boundary element (the default pack's Part 6 Sec 8.3.6.6(d)(iii),
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
    """Bars at each end of a wall: a boundary element of a special structural wall (the default pack (BNBC 2020)
    Part 6 Sec 8.3.6.6), or end bars with ties; the same at both ends."""

    length: Length = Field(description="From the wall's end [mm].")
    count: int = Field(gt=0, description="Vertical bars per end, in two rows along the faces.")
    dia: Length
    hoop: BoundaryHoops | None = Field(default=None, title="Hoops")


class CouplingGroupHoops(_Model):
    """Hoops around one group of a coupling beam's diagonal bars (the default pack's Part 6 Sec
    8.3.6.7(d)(iii)): two legs each way, crossties added where the leg spacing needs them."""

    dia: Length = 10
    spacing: Length = Field(default=100, description="Spacing along the diagonal bars [mm].")
    width: Length | None = Field(
        default=None,
        description="Out-to-out parallel to the wall's thickness [mm]; none: the room inside "
        "the wall's curtains.",
    )
    depth: Length | None = Field(
        default=None,
        description="Out-to-out along the other sides [mm]; none: from the group's bars in two "
        "layers.",
    )


class CouplingDiagonal(_Model):
    """One of the two groups of diagonal bars of the coupling beams (spandrels over openings) of
    a special structural wall (the default pack's Part 6 Sec 8.3.6.7)."""

    count: int = Field(ge=4, description="Bars per group (at least four, 8.3.6.7(d)(ii)).")
    dia: Length
    angle: float | None = Field(
        default=None,
        gt=0,
        lt=90,
        description="Angle to the beam's axis [°]; none: from the depth and span.",
    )
    hoop: BoundaryHoops | None = Field(
        default=None,
        title="Hoops",
        description="Hoops and crossties over the whole coupling beam section (the default "
        "pack's Part 6 Sec 8.3.6.7(d)(iv)), the same over every spandrel of the type: legs across counted "
        "down the beam's depth, legs along (vertical) counted across the thickness; none: not "
        "entered.",
    )
    groupHoop: CouplingGroupHoops | None = Field(
        default=None,
        title="Hoops around each group",
        description="Hoops around each group of diagonal bars (the default pack's Part 6 Sec "
        "8.3.6.7(d)(iii)), the alternative to hoops over the whole section; checked when no "
        "hoops over the section are entered. None: not entered.",
    )
    longitudinal: BarMesh | None = Field(
        default=None,
        title="Longitudinal bars",
        description="Longitudinal bars along each face of the coupling beams, at this spacing "
        "down the depth (the bars the hoop legs engage, 8.3.6.7(d)(iv), or the perimeter bars "
        "of (d)(iii)), developed into the piers; none: the wall's horizontal web bars.",
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
    pierHoop: BoundaryHoops | None = Field(
        default=None,
        title="Wall pier hoops",
        description="Hoops and crossties of the wall piers (narrow piers beside openings of "
        "special walls, the default pack's Part 6 Sec 8.3.6.8), the same in every wall pier of "
        "the type, over its clear height and beyond it above and below, in addition to the web "
        "bars: legs across counted along the pier's length, legs along counted across the "
        "thickness; none: not entered.",
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
# Checked by saengine.design.steel_connections (the default pack's Part 6 Sec 10.10); the models live
# here so the beam and brace types can carry them.

BoltDiameter = Literal[16, 20, 22, 24, 27, 30, 36]
BoltGrade = Literal["A307", "A325N", "A325X", "A490N", "A490X", "4.6", "8.8", "10.9"]


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
    slipCritical: Literal["none", "serviceability", "strength"] = Field(
        default="none",
        title="Slip-critical",
        description="Bearing-type (none), or pretensioned bolts designed against slip as a "
        "serviceability limit (standard holes, slots across the load) or at the required "
        "strength (oversized holes, slots along the load).",
        json_schema_extra={
            "enumDescriptions": ["Bearing-type", "Slip: serviceability", "Slip: strength"]
        },
    )
    surfaceClass: Literal["A", "B"] = Field(
        default="A",
        title="Faying surface",
        description="Slip-critical: class A (clean mill scale, class A coatings, galvanized "
        "and roughened) or B (blast-cleaned, class B coatings).",
    )
    holeType: Literal["standard", "oversized", "shortSlot", "longSlot"] = Field(
        default="standard",
        title="Holes",
        description="Hole type of the slip-critical plies (bearing-type connections use "
        "standard holes).",
    )


class FinPlateConnection(_Bolted):
    """Single (fin) plate welded to the support, one line of bolts through the beam web."""

    type: Literal["finPlate"] = "finPlate"
    boltLineOffset: float = Field(
        default=60, gt=0, description="Support face (weld) to the bolt line, a [mm]."
    )
    supportSection: str | None = Field(
        default=None,
        description="A rectangular HSS column the plate is welded to (steel sections table), "
        "for the HSS wall check of a plate along its axis; none: an open section or a wall.",
    )
    supportMaterial: str | None = Field(
        default=None, description="03 Materials id of the HSS support; none: the beam's material."
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


class FlangePlateConnection(_Bolted):
    """Bolted flange-plate moment connection of a beam to a column flange: a plate on each beam
    flange, welded to the column and bolted to the flange (``rows`` bolts in each of ``lines``
    lines), and a fin plate on the web for the shear. The beam end is kept rigid in the
    analysis. ``plateThickness`` is the flange plates'; ``edgeDistance`` sets their width."""

    type: Literal["flangePlate"] = "flangePlate"
    lines: int = Field(default=2, ge=2, le=4, description="Bolt lines along each flange plate.")
    gauge: float = Field(default=100, gt=0, description="Between the bolt lines [mm].")
    setback: float = Field(
        default=15, ge=0, description="Column face to the beam end (the plate's free length) [mm]."
    )
    plateWeld: Literal["cjp", "fillet"] = Field(
        default="cjp",
        description="Flange plates to the column: complete-joint-penetration groove welds "
        "(matching filler) or fillet welds on both faces.",
    )
    webRows: int = Field(default=3, ge=1, le=20, description="Bolts in the web fin plate.")
    webPlateThickness: float = Field(default=10, gt=0, description="Web fin plate [mm].")
    webBoltLineOffset: float = Field(
        default=60, gt=0, description="Column face to the web bolt line [mm]."
    )
    columnSection: str | None = Field(
        default=None,
        description="The supporting column's section (steel sections table), for the column "
        "flange, web and panel zone checks; none: the column side is not checked.",
    )
    columnMaterial: str | None = Field(
        default=None, description="03 Materials id of the column; none: the beam's material."
    )
    columnStiffeners: bool = Field(
        default=False,
        description="A pair of transverse stiffeners (continuity plates) opposite each beam "
        "flange, designed for the force the column flange and web cannot take.",
    )
    stiffenerWidth: float = Field(
        default=0, ge=0, description="Width of each stiffener [mm]; 0: the beam flange's reach."
    )
    stiffenerThickness: float = Field(
        default=0, ge=0, description="Stiffener thickness [mm]; 0: the flange plate's."
    )
    doublerThickness: float = Field(
        default=0, ge=0, description="Web doubler plate on the panel zone [mm]; 0: none."
    )
    doubleSided: bool = Field(
        default=False,
        description="Beams on both column flanges at this level (the web takes a pair of "
        "compressive forces: web compression buckling).",
    )
    columnEndDistance: float | None = Field(
        default=None,
        ge=0,
        description="Column end (top) to the beam flange [mm], for the reduced strengths near "
        "a member end; none: far from the end.",
    )
    columnAxialRatio: float = Field(
        default=0,
        ge=0,
        le=1,
        description="Column axial force Pr / Py at the joint, for the panel zone strength.",
    )
    panelZoneInAnalysis: bool = Field(
        default=False,
        description="The analysis includes the plastic panel-zone deformation (frame "
        "stability), which allows the higher panel zone strength.",
    )
    columnUtilisation: float = Field(
        default=0,
        ge=0,
        le=1,
        description="HSS columns: chord utilisation U (axial and bending) at the joint, for the "
        "chord stress factor Qf (column in compression).",
    )


class HssJointConnection(_Model):
    """A welded HSS-to-HSS truss joint at the brace end: the brace (the branch) welded to an
    HSS chord, both round or both rectangular. Checked for the brace axial forces."""

    type: Literal["hssJoint"] = "hssJoint"
    chordSection: str | None = Field(
        default=None, description="The chord's section (steel sections table)."
    )
    chordMaterial: str | None = Field(
        default=None, description="03 Materials id of the chord; none: the brace's material."
    )
    joint: Literal["TY", "X", "K", "KOverlap"] = Field(
        default="K",
        description="T or Y (one branch), X (branches on both faces), K (two branches, gapped) "
        "or overlapped K (this brace overlaps the other branch).",
        json_schema_extra={"enumDescriptions": ["T or Y", "Cross (X)", "Gapped K", "Overlapped K"]},
    )
    angle: float = Field(default=45, ge=30, le=90, description="Branch to chord angle θ [°].")
    gap: float = Field(default=20, ge=0, description="K joints: gap between the branches [mm].")
    overlap: float = Field(
        default=50,
        ge=0,
        le=100,
        description="Overlapped K joints: overlap Ov = q / p [%] (q the overlap length on the "
        "chord face, p the brace's projected length).",
    )
    overlappedSection: str | None = Field(
        default=None,
        description="Overlapped K joints: the other (overlapped, thru) branch's section; none: "
        "this brace's section.",
    )
    overlappedMaterial: str | None = Field(
        default=None, description="03 Materials id of the overlapped branch; none: the brace's."
    )
    chordCompression: bool = Field(default=True, description="Chord in compression at the joint.")
    chordUtilisation: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Chord utilisation U at the joint (axial and bending), for the chord "
        "stress factor Qf.",
    )
    plateMaterial: str | None = Field(default=None, description="Not used (no plates).")


class HssMomentConnection(_Model):
    """A welded HSS-to-HSS moment connection at the beam ends: the beam (the branch) welded to
    an HSS column (the chord) that passes through, both round or both rectangular. Checked for
    the beam's axial force and its in-plane and out-of-plane end moments; the ends are kept
    rigid in the analysis."""

    type: Literal["hssMoment"] = "hssMoment"
    chordSection: str | None = Field(
        default=None, description="The column's (chord's) section (steel sections table)."
    )
    chordMaterial: str | None = Field(
        default=None, description="03 Materials id of the chord; none: the beam's material."
    )
    joint: Literal["T", "X"] = Field(
        default="T",
        description="T or Y (one beam at the chord) or cross (beams on opposite faces).",
        json_schema_extra={"enumDescriptions": ["T or Y", "Cross (X)"]},
    )
    angle: float = Field(
        default=90, ge=30, le=90, description="Branch to chord angle θ [°] (rectangular: 90)."
    )
    chordCompression: bool = Field(default=True, description="Chord in compression at the joint.")
    chordUtilisation: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Chord utilisation U at the joint (axial and bending), for Qf.",
    )
    distortionPrevented: bool = Field(
        default=False,
        description="Rectangular T joints: chord distortion prevented by other means (no "
        "distortional check).",
    )
    plateMaterial: str | None = Field(default=None, description="Not used (no plates).")


SteelConnection = Annotated[
    FinPlateConnection
    | EndPlateConnection
    | BraceGussetConnection
    | FlangePlateConnection
    | HssJointConnection
    | HssMomentConnection,
    Field(discriminator="type"),
]


class SteelSplice(_Bolted):
    """Bolted cover-plate splice of an I-section beam or column: a plate on the outside of each
    flange (``rows`` bolts in each of ``lines`` lines on each side of the joint) and a plate on
    each side of the web (``webRows`` bolts on each side). Checked for the member's forces at
    the splice. ``plateThickness`` is the flange plates'; ``edgeDistance`` sets their width."""

    type: Literal["coverPlate"] = "coverPlate"
    distance: float = Field(
        default=1000, gt=0, description="Splice position from the member's lower (first) end [mm]."
    )
    lines: int = Field(default=2, ge=2, le=4, description="Bolt lines along each flange plate.")
    gauge: float = Field(default=100, gt=0, description="Between the bolt lines [mm].")
    gap: float = Field(default=10, ge=0, description="Between the member ends [mm].")
    webRows: int = Field(default=2, ge=1, le=20, description="Web bolts on each side.")
    webPitch: float = Field(default=70, gt=0, description="Web bolt spacing [mm].")
    webEndDistance: float = Field(default=35, gt=0, description="Web plate edge to bolt [mm].")
    webPlateThickness: float = Field(default=8, gt=0, description="Each web plate [mm].")
    finishedToBear: bool = Field(
        default=True,
        description="Columns: the ends are finished to bear, so compression passes by bearing "
        "and the plates carry the tension and the moment.",
    )


AnchorDiameter = Literal[16, 20, 24, 30, 36]

AnchorKind = Literal[
    "headedBolt",
    "headedStud",
    "hookedBolt",
    "undercut",
    "torqueControlled",
    "displacementControlled",
]


class AnchorConcrete(_Model):
    """The concrete side of a group of anchors (a base plate's anchor rods, an embedded plate's
    studs): checked by :mod:`saengine.design.anchors` for steel, concrete breakout, pullout,
    side-face blowout and pryout under the code pack's anchoring rules."""

    kind: AnchorKind = Field(
        default="headedBolt",
        description="Cast-in headed bolt, headed stud or hooked (J/L) bolt, or a post-installed "
        "undercut, torque-controlled or displacement-controlled expansion anchor.",
    )
    category: Literal[1, 2, 3] = Field(
        default=1,
        description="Post-installed anchors: the installation category of the product's "
        "qualification tests (1: low sensitivity to installation).",
    )
    embedment: float = Field(default=300, gt=0, description="Effective embedment depth hef [mm].")
    headBearingArea: float | None = Field(
        default=None,
        gt=0,
        description="Net bearing area of the head or nut Abrg [mm²]; none: estimated from a "
        "hex nut of the rod.",
    )
    hookExtension: float | None = Field(
        default=None,
        gt=0,
        description="Hooked bolts: the hook extension eh past the bend [mm]; none: 4.5 da.",
    )
    pulloutStrength: float | None = Field(
        default=None,
        gt=0,
        description="Post-installed anchors: the pullout strength Np of the product's tests "
        "[kN]; none: pullout not checked.",
    )
    memberThickness: float | None = Field(
        default=None,
        gt=0,
        description="Thickness ha of the concrete member (pedestal or footing depth) [mm]; "
        "none: deep.",
    )
    edgeN: float | None = Field(
        default=None,
        gt=0,
        description="Plate centre to the concrete edges along N, both sides [mm]; none: half "
        "the concrete support's length (far without one).",
    )
    edgeB: float | None = Field(
        default=None,
        gt=0,
        description="Plate centre to the concrete edges along B, both sides [mm]; none: half "
        "the concrete support's width (far without one).",
    )
    cracked: bool = Field(
        default=True, description="The concrete may crack at service loads (the usual case)."
    )
    supplementaryReinforcement: bool = Field(
        default=False,
        description="Supplementary reinforcement restrains the breakout (Condition A).",
    )
    shearEdgeReinforcement: Literal["none", "edgeBar", "edgeBarStirrups"] = Field(
        default="none",
        description="Cracked concrete: an edge bar of 13 mm or more between the anchors and the "
        "edge, and whether stirrups enclose it.",
    )
    anchorReinforcementTension: float = Field(
        default=0,
        ge=0,
        description="Area of anchor reinforcement developed both sides of the tension "
        "breakout [mm²]; 0: none (the breakout is checked).",
    )
    anchorReinforcementShear: float = Field(
        default=0,
        ge=0,
        description="Area of anchor reinforcement for the shear breakout [mm²]; 0: none.",
    )
    anchorReinforcementFy: float = Field(
        default=415, gt=0, description="Yield strength of the anchor reinforcement [MPa]."
    )
    lightweightFactor: float = Field(
        default=1.0, gt=0, le=1, description="λ of lightweight concrete (1: normal weight)."
    )
    groutPad: bool = Field(default=True, description="The plate sits on a built-up grout pad.")
    torqued: bool = Field(default=False, description="Cast-in anchors that will be torqued.")
    ductile: bool = Field(
        default=True,
        description="The anchor steel is ductile (elongation >= 14 % and area reduction "
        ">= 30 %; mild steel rods are).",
    )
    welded: bool = Field(
        default=False, description="Cast-in anchors welded to the attachment (embedded plates)."
    )
    cover: float = Field(
        default=40,
        gt=0,
        description="Specified cover of the reinforcement [mm]: the least edge distance of "
        "untorqued cast-in anchors.",
    )
    seismicDesign: Literal["ductileSteel", "yieldingAttachment", "reducedStrength", "studWall"] = (
        Field(
            default="ductileSteel",
            description="Earthquake combinations in the categories the code names: the steel "
            "of a ductile anchor governs (checked), the attachment yields first (stated), or the "
            "reduced design strength (stud bearing walls: their own factor).",
        )
    )


class ColumnBasePlate(_Model):
    """Base plate of a steel column on concrete, with anchor rods. Checked for the column's
    forces at a support: bearing on the concrete (with the base moment), the anchor rods'
    tension from uplift and moment, their steel and their anchorage in the concrete, and the
    welds."""

    type: Literal["basePlate"] = "basePlate"
    length: float = Field(default=400, gt=0, description="Along the column depth, N [mm].")
    width: float = Field(default=300, gt=0, description="Across, B [mm].")
    thickness: float = Field(default=25, gt=0, description="[mm]")
    plateMaterial: str | None = Field(
        default=None, description="03 Materials id; none: the column's material."
    )
    concreteStrength: float = Field(
        default=25, gt=0, description="f'c of the pedestal or footing under the plate [MPa]."
    )
    supportLength: float | None = Field(
        default=None, gt=0, description="Concrete top under the plate, along N [mm]; none: N."
    )
    supportWidth: float | None = Field(
        default=None, gt=0, description="Concrete top under the plate, along B [mm]; none: B."
    )
    anchors: int = Field(default=4, ge=2, le=16, description="Anchor rods.")
    anchorDiameter: AnchorDiameter = Field(default=20, description="[mm]")
    anchorFu: float = Field(
        default=400, gt=0, description="Anchor rod tensile strength Fu [MPa] (400: grade 36)."
    )
    threadsExcluded: bool = Field(
        default=False, description="Threads excluded from the shear plane."
    )
    weldSize: float = Field(default=8, gt=0, description="Column-to-plate fillet weld leg [mm].")
    electrode: float = Field(default=480, gt=0, description="FEXX [MPa].")
    anchorFy: float = Field(
        default=250, gt=0, description="Anchor rod yield strength [MPa] (250: grade 36)."
    )
    anchorEdge: float = Field(
        default=50,
        gt=0,
        description="Plate edge to the anchor rod centres [mm]: the rods stand in two rows "
        "across B at ±(N/2 - this), spread evenly across B within ±(B/2 - this).",
    )
    anchorage: AnchorConcrete = Field(
        default_factory=AnchorConcrete,
        title="Anchorage in concrete",
        description="The anchor rods in the concrete: embedment, edges, cracking, reinforcement.",
    )


class HssCapPlate(_Model):
    """A cap plate on the top of a rectangular HSS column carrying a beam (or a bearing plate)
    that bears on it: the column walls under the concentrated axial force."""

    type: Literal["capPlate"] = "capPlate"
    thickness: float = Field(default=20, gt=0, description="Cap plate thickness tp [mm].")
    bearingLength: float = Field(
        default=150,
        gt=0,
        description="Bearing length N of the load on the cap plate, across the column [mm].",
    )


# ──────────────────────────── steel-concrete composite members ────────────────────────────
# Checked by saengine.design.steel.composite under the code pack's ``composite`` table: a steel
# beam acting with the slab through shear connectors, a steel column encased in concrete or a
# concrete-filled HSS. The deck and stud data are the product's (the code gives the limits).


class CompositeDeck(_Model):
    """The formed steel deck under the slab (none: a solid slab)."""

    orientation: Literal["perpendicular", "parallel"] = Field(
        default="perpendicular",
        description="The deck ribs run across the beam or along it.",
        json_schema_extra={"enumDescriptions": ["Across the beam", "Along the beam"]},
    )
    ribHeight: float = Field(default=50, gt=0, description="Nominal rib height hr [mm].")
    ribWidth: float = Field(
        default=150,
        gt=0,
        description="Average width of the concrete rib or haunch wr [mm] (no more than the "
        "least clear width near the top of the deck).",
    )
    ribPitch: float = Field(default=300, gt=0, description="Centres of the ribs [mm].")
    weight: float = Field(default=0.1, ge=0, description="Self weight of the deck [kN/m²].")
    anchorageSpacing: float | None = Field(
        default=None, gt=0, description="Deck anchored to the beams at these centres [mm]."
    )


class ShearConnectors(_Model):
    """The shear connectors on the top flange: headed studs (or hot-rolled channels)."""

    kind: Literal["stud", "channel"] = Field(
        default="stud",
        json_schema_extra={"enumDescriptions": ["Headed stud", "Hot-rolled channel"]},
    )
    diameter: float = Field(default=19, gt=0, description="Stud shank diameter [mm].")
    height: float = Field(default=100, gt=0, description="Stud length after welding [mm].")
    fu: float = Field(
        default=450, gt=0, description="Specified tensile strength of the studs Fu [MPa]."
    )
    perRow: int = Field(
        default=1, ge=1, le=4, description="Studs side by side in a row (or in one deck rib)."
    )
    transverseSpacing: float | None = Field(
        default=None, gt=0, description="Centres of the studs of a row [mm]."
    )
    spacing: float | None = Field(
        default=None,
        gt=0,
        description="Rows along the beam at these centres [mm]; none: the least number of rows "
        "that carries the moment is designed (at the rib pitch on a perpendicular deck).",
    )
    eMidHeight: float | None = Field(
        default=None,
        gt=0,
        title="e mid-ht",
        description="Stud shank to the deck web at mid-height of the rib, in the stud's load "
        "direction [mm]; none: the weak position.",
    )
    overWeb: bool = Field(default=True, description="The studs stand over the beam web.")
    channelFlange: float = Field(default=8, gt=0, description="Channel flange thickness [mm].")
    channelWeb: float = Field(default=5, gt=0, description="Channel web thickness [mm].")
    channelLength: float = Field(default=100, gt=0, description="Channel length Lc [mm].")


class SlabShrinkage(_Model):
    """The inputs of the shrinkage deflection of a simply supported composite beam."""

    freeStrain: float = Field(gt=0, lt=0.01, description="Free shrinkage strain εf [-].")
    coefficient: float = Field(
        gt=0, description="Empirical coefficient c matching theory with tests [-]."
    )
    aging: float = Field(gt=0, le=1, description="Aging coefficient χ [-].")
    creep: float = Field(ge=0, description="Creep coefficient φ [-].")


class SlabTransverseBars(_Model):
    """The slab bars across a composite beam that carry the slab's longitudinal shear (alpha 9
    P8, the pack's ``composite.beam.longitudinalShear``)."""

    top: float = Field(default=0, ge=0, description="Top bars across the beam [mm²/m].")
    bottom: float = Field(default=0, ge=0, description="Bottom bars across the beam [mm²/m].")
    fy: float = Field(default=500, gt=0, description="Their yield strength [MPa].")


class CompositeBeam(_Model):
    """A steel beam acting with the concrete slab through shear connectors."""

    type: Literal["compositeBeam"] = "compositeBeam"
    concrete: Id = Field(description="03 Materials id of the slab concrete.")
    slabThickness: float = Field(
        default=130, gt=0, description="Total slab depth tc, to the top of the deck [mm]."
    )
    deck: CompositeDeck | None = Field(
        default_factory=CompositeDeck, description="The formed steel deck; none: a solid slab."
    )
    spacingLeft: float | None = Field(
        default=3000, gt=0, description="To the next beam on the left [mm]; none: no beam."
    )
    spacingRight: float | None = Field(
        default=3000, gt=0, description="To the next beam on the right [mm]; none: no beam."
    )
    edgeLeft: float | None = Field(
        default=None, gt=0, description="To the slab edge on the left [mm]; none: no edge."
    )
    edgeRight: float | None = Field(
        default=None, gt=0, description="To the slab edge on the right [mm]; none: no edge."
    )
    connectors: ShearConnectors = Field(default_factory=ShearConnectors)
    shored: bool = Field(
        default=False, description="Temporary shores carry the wet concrete (else the steel)."
    )
    constructionLive: float = Field(
        default=0,
        ge=0,
        description="Erection load on the wet slab during the construction [kN/m²].",
    )
    slabBars: float | None = Field(
        default=None,
        gt=0,
        description="Developed longitudinal bars in the effective width over the supports "
        "[mm²]; none: negative flexure on the steel alone.",
    )
    slabBarFy: float = Field(default=415, gt=0, description="fy of the slab bars [MPa].")
    sustainedLive: float = Field(
        default=0, ge=0, le=1, description="Share of the live load that is long-term [-]."
    )
    shrinkage: SlabShrinkage | None = Field(
        default=None, description="The shrinkage deflection's inputs; none: not computed."
    )
    embeddedEnds: bool = Field(
        default=False,
        description="The beam ends are embedded in reinforced concrete columns or walls.",
    )
    transverseBars: SlabTransverseBars | None = Field(
        default=None,
        title="Transverse bars",
        description="The slab bars across the beam for the longitudinal shear (where the code "
        "pack checks it); none: the bars needed are reported.",
    )


class CompositeColumn(_Model):
    """A steel column encased in reinforced concrete, or a concrete-filled HSS."""

    type: Literal["compositeColumn"] = "compositeColumn"
    form: Literal["encased", "filled"] = Field(
        default="encased",
        json_schema_extra={"enumDescriptions": ["Encased in concrete", "Concrete-filled HSS"]},
    )
    concrete: Id = Field(description="03 Materials id of the concrete.")
    width: float = Field(
        default=500, gt=0, description="Encased: concrete width across the flanges [mm]."
    )
    depth: float = Field(
        default=500, gt=0, description="Encased: concrete depth along the web [mm]."
    )
    bars: int = Field(default=4, ge=0, description="Longitudinal bars (4 at the corners).")
    barDiameter: float = Field(default=20, gt=0, description="[mm]")
    barFy: float = Field(default=415, gt=0, description="fy of the bars [MPa].")
    cover: float = Field(default=40, gt=0, description="Clear cover to the ties [mm].")
    tieDiameter: float = Field(default=10, gt=0, description="[mm]")
    tieSpacing: float = Field(default=200, gt=0, description="[mm]")
    loadApplied: Literal["steel", "concrete", "bearing"] = Field(
        default="steel",
        description="Where the floor's force enters the column.",
        json_schema_extra={
            "enumDescriptions": [
                "To the steel (studs transfer the concrete's share)",
                "To the concrete (studs transfer the steel's share)",
                "Bearing on the concrete",
            ]
        },
    )
    bearingArea: float | None = Field(
        default=None, gt=0, description="Bearing: the loaded concrete area [mm²]."
    )
    transferForce: float | None = Field(
        default=None,
        gt=0,
        description="The force the floor brings into the column at a connection [kN]; none: "
        "the column's largest compression (conservative).",
    )
    studDiameter: float = Field(default=19, gt=0, description="Transfer studs [mm].")
    studFu: float = Field(default=450, gt=0, description="Transfer studs' Fu [MPa].")
    studSpacing: float = Field(default=300, gt=0, description="Transfer studs' centres [mm].")
    studFaces: int = Field(
        default=2, ge=1, le=4, description="Faces of the steel shape with transfer studs."
    )


# Checked by saengine.design.timber (permissible stress design of the code pack's ``timber``
# table); the models live here so the beam, column and brace types can carry them.


class TimberNotch(_Model):
    """A notch at the member's supports (both ends)."""

    face: Literal["tension", "compression"] = Field(
        default="tension", description="Tension (bottom) or compression (top) face."
    )
    depth: Length = Field(description="Depth of the notch D2 [mm].")
    length: Length = Field(
        description="Inner edge of the support to the far edge of the notch, e [mm]."
    )


class TimberSpaced(_Model):
    """A spaced column: ``pieces`` members of the type's profile, packed apart and connected
    at the ends (and between)."""

    pieces: int = Field(default=2, ge=2, le=4)
    connectors: Literal["end20", "end10to20"] = Field(
        default="end20",
        description="Centroid of the end fasteners at S/20 from the end, or S/10 to S/20.",
        json_schema_extra={"enumDescriptions": ["At S/20 from the end", "S/10 to S/20"]},
    )


class TimberMember(_Model):
    """Design data of a timber beam, column or brace beyond its section and material."""

    brittleFinishes: bool = Field(
        default=False,
        description="Supports brittle finishes (gypsum ceilings, slates, tiles, asbestos "
        "sheets): the stricter deflection limit.",
    )
    freeEnd: Literal["none", "start", "end"] = Field(
        default="none",
        description="A cantilever: the end that is free (deflection of the free length).",
        json_schema_extra={"enumDescriptions": ["Supported at both ends", "Start", "End"]},
    )
    bearingLength: float | None = Field(
        default=None,
        gt=0,
        description="Bearing length at each end support [mm]; none: not checked.",
    )
    notch: TimberNotch | None = None
    restraintSpacing: float | None = Field(
        default=None,
        gt=0,
        description="Lateral restraints against twisting [mm]; none: only at the ends.",
    )
    diagonalLoading: bool = Field(
        default=False, description="Square section loaded in the direction of its diagonal."
    )
    spaced: TimberSpaced | None = None
    repetitive: bool = Field(
        default=False,
        description="One of three or more members at most 610 mm apart joined by "
        "a load-distributing floor or roof (the repetitive member factor of a code pack that "
        "designs timber by reference design values).",
    )


class _TimberJointBase(_Model):
    joint: Literal["node", "lengthening"] = Field(
        default="node",
        description="Node (members meeting) or lengthening (splice) joint at each end.",
        json_schema_extra={"enumDescriptions": ["Node joint", "Lengthening joint"]},
    )
    count: int = Field(default=4, ge=1, le=200, description="Fasteners at each end.")


class TimberNailedJoint(_TimberJointBase):
    """Common wire nails in double shear through splice or gusset plates on both faces."""

    type: Literal["nails"] = "nails"
    size: Literal["3.55", "4", "5"] = Field(default="3.55", description="Shank diameter [mm].")
    temporary: bool = Field(default=False, description="Temporary structure.")
    clenched: bool = Field(default=False, description="Points clenched across the grain.")
    sideThickness: Length = Field(default=25, description="Each splice or gusset plate [mm].")
    endDistance: Length = Field(default=50, description="[mm]")
    spacing: Length = Field(default=40, description="Along the grain [mm].")
    edgeDistance: Length = Field(default=20, description="[mm]")
    rowSpacing: Length = Field(default=20, description="Between rows, across the grain [mm].")
    species: str | None = Field(
        default=None, description="Species of the nail table; none: the member's."
    )


class TimberBoltedJoint(_TimberJointBase):
    """Bolts through the member and wooden splice plates."""

    type: Literal["bolts"] = "bolts"
    diameter: Literal[6, 10, 12, 16, 20, 22, 25] = Field(default=16, description="[mm]")
    shear: Literal["double", "single"] = "double"
    mainThickness: float | None = Field(
        default=None, gt=0, description="Main member t' [mm]; none: the member's width."
    )
    sideThickness: Length = Field(default=40, description="Each side member [mm].")
    rows: int = Field(default=2, ge=1, le=20, description="Rows of bolts.")
    spacing: Length = Field(default=64, description="Bolts in a row [mm].")
    rowSpacing: Length = Field(default=40, description="Between rows [mm].")
    endDistance: Length = Field(default=112, description="[mm]")
    edgeDistance: Length = Field(default=40, description="[mm]")
    hardwood: bool = Field(default=True, description="Hardwood (else softwood): end distance.")


class TimberSplitRingJoint(_TimberJointBase):
    """Metallic split-ring connectors with a bolt each."""

    type: Literal["splitRing"] = "splitRing"
    diameter: Length = Field(default=100, description="Ring diameter [mm].")
    mainThickness: float | None = Field(
        default=None, gt=0, description="[mm]; none: the member's width."
    )
    sideThickness: Length = Field(default=38, description="[mm]")
    edgeDistance: Length = Field(default=100, description="Loaded edge [mm].")
    endDistance: Length = Field(default=175, description="[mm]")


class TimberDiscDowelJoint(_TimberJointBase):
    """Hardwood disc-dowels with a mild steel bolt each."""

    type: Literal["discDowel"] = "discDowel"
    diameter: Length = Field(default=100, description="Mid diameter d [mm].")
    thickness: Length = Field(default=30, description="t [mm].")
    edgeClearance: Length = Field(default=15, description="[mm]")
    endClearance: Length = Field(default=100, description="[mm]")
    species: str | None = Field(
        default=None, description="Species of the dowels; none: the member's timber."
    )


TimberJoint = Annotated[
    TimberNailedJoint | TimberBoltedJoint | TimberSplitRingJoint | TimberDiscDowelJoint,
    Field(discriminator="type"),
]


# B39: checked by saengine.design.bamboo and saengine.design.ferrocement (the code pack's
# ``bamboo`` and ``ferrocement`` tables); here so the beam, column and brace types carry them.


class BambooJoint(_Model):
    """The joint at both ends of a bamboo member: its kind and fastening as the code describes
    them, with the capacity found by full-scale tests."""

    kind: Literal[
        "lap",
        "butt",
        "sleeve",
        "scarf",
        "saddle",
        "tenon",
        "crossOver",
        "angled",
        "gusset",
        "insert",
    ] = Field(
        default="gusset",
        json_schema_extra={
            "enumDescriptions": [
                "Lap",
                "Butt with side plates",
                "Sleeve or insert",
                "Scarf",
                "Saddle (bearing butt)",
                "Tenon",
                "Cross-over",
                "Angled",
                "Gusset plates",
                "End inserts or band clamps",
            ]
        },
    )
    fastening: Literal["lashing", "wireBound", "pinAndWire", "fishPlate", "horned"] = Field(
        default="fishPlate",
        json_schema_extra={
            "enumDescriptions": [
                "Wire lashing",
                "Wire bound",
                "Pins and wire",
                "Fish or gusset plates",
                "Horned",
            ]
        },
    )
    testedCapacity: float | None = Field(
        default=None,
        gt=0,
        title="Tested capacity",
        description="Safe axial load of the joint from full-scale tests [kN]; none: not "
        "checked (the code requires the tests).",
    )


class BambooMember(_Model):
    """Design data of a bamboo beam, column or brace beyond its culm (a hollow or solid circle
    profile) and material."""

    culms: int = Field(
        default=1,
        ge=1,
        le=12,
        description="Culms tied together as a bundle column (each takes its share; no "
        "composite action).",
    )
    truss: bool = Field(
        default=False,
        description="A truss member: the axial forces of compression and of the joints "
        "increased as the code requires.",
    )
    joint: BambooJoint | None = Field(default=None, description="None: the joints not checked.")


class FerrocementBars(_Model):
    """Skeletal bars along the member at mid-thickness."""

    diameter: Length = Field(default=6)
    spacing: Length = Field(default=100, description="Centres across the width [mm].")


class FerrocementMember(_Model):
    """The mesh layers of a ferrocement member (a rectangle profile: width × thickness)."""

    mesh: Literal["wovenSquare", "weldedSquare", "hexagonal", "expanded"] = Field(
        default="wovenSquare",
        json_schema_extra={
            "enumDescriptions": ["Woven square", "Welded square", "Hexagonal", "Expanded metal"]
        },
    )
    layers: int = Field(default=4, ge=1, le=40, description="Mesh layers through the thickness.")
    wireDiameter: Length = Field(
        default=1.0, description="Wire diameter, or the sheet thickness of expanded metal [mm]."
    )
    spacing: Length | None = Field(
        default=13,
        description="Square or rectangular mesh: centres of the wires along the member [mm].",
    )
    spacingTransverse: Length | None = Field(
        default=None, description="Rectangular mesh: centres of the wires across [mm]."
    )
    meshWeight: float | None = Field(
        default=None,
        gt=0,
        description="Hexagonal and expanded mesh: weight per layer and unit area [N/m²].",
    )
    direction: Literal["longitudinal", "transverse", "diagonal"] = Field(
        default="longitudinal",
        description="The mesh's roll direction relative to the member's span.",
        json_schema_extra={"enumDescriptions": ["Along the span", "Across the span", "At 45°"]},
    )
    cover: Length | None = Field(
        default=None, description="Clear cover to the first layer [mm]; none: the least."
    )
    fy: float | None = Field(
        default=None, gt=0, description="Yield strength from tests [MPa]; none: the code's."
    )
    bars: FerrocementBars | None = None
    exposure: Literal["noncorrosive", "corrosive", "waterRetaining"] = Field(
        default="noncorrosive",
        json_schema_extra={
            "enumDescriptions": ["Noncorrosive", "Corrosive", "Water or liquid retaining"]
        },
    )
    fatigueCycles: Literal["none", "oneMillion", "twoMillion"] = Field(
        default="none",
        title="Fatigue",
        json_schema_extra={"enumDescriptions": ["Not checked", "1 million", "2 million"]},
    )


# ─────────────────────────── masonry walls: confinement and anchor bolts ───────────────────────────


class ConfiningElement(_Model):
    """A tie column or tie beam of a confined masonry wall: cast-in-place RC after the masonry
    is built (checked by :mod:`saengine.design.confined_masonry`)."""

    width: Length | None = Field(
        default=None, description="Across the wall [mm]; empty: the wall's thickness."
    )
    depth: Length = Field(
        default=200,
        description="In the plane of the wall [mm]: along it for a tie column, vertical for a "
        "tie beam.",
    )
    count: int = Field(default=4, ge=2, description="Longitudinal bars.")
    dia: Length = Field(default=12, description="Longitudinal bar diameter [mm].")
    tieDia: Length = Field(default=6, title="Tie diameter", description="[mm]")
    tieSpacing: Length = Field(default=150, title="Tie spacing", description="[mm]")
    endTieSpacing: Length | None = Field(
        default=100,
        title="End-zone tie spacing",
        description="Tie columns: at the top and bottom of each storey [mm]; empty: as the rest.",
    )


class WallConfinement(_Model):
    """A confined masonry wall: tie columns at the wall's ends, beside the larger openings and
    within long walls, and a tie beam at every floor, placed by the code pack's rules."""

    concrete: Id = Field(description="Concrete of the tie columns and tie beams.")
    rebar: Id = Field(description="Reinforcement of the tie columns and tie beams.")
    cover: Length = Field(default=25, description="Clear cover to the ties [mm].")
    tieColumn: ConfiningElement = Field(default_factory=ConfiningElement, title="Tie columns")
    tieBeam: ConfiningElement = Field(default_factory=ConfiningElement, title="Tie beams")
    toothed: bool = Field(
        default=True,
        description="Toothed edges at the tie columns; False: steel dowels in the bed joints.",
    )


class MasonryAnchorBolts(_Model):
    """The anchor bolts that tie a masonry wall to each floor or roof (checked by
    :mod:`saengine.design.masonry_anchors` against the wall's anchorage force)."""

    kind: Literal["headed", "plate", "bent"] = Field(
        default="headed", description="Headed, plate or bent-bar (J or L) anchor bolts."
    )
    placement: Literal["face", "top"] = Field(
        default="face",
        description="In the face of the wall (the anchorage force is tension: a ledger) or in "
        "its top (the anchorage force is shear: a sill or bearing plate).",
    )
    dia: Length = Field(default=16, description="[mm]")
    embedment: Length = Field(default=150, description="Effective embedment lb [mm].")
    edge: Length = Field(default=100, description="Edge distance lbe [mm].")
    spacing: Length = Field(default=600, description="Along the wall [mm].")
    fy: Length = Field(default=250, title="Bolt fy", description="[MPa]")
    shearPerMetre: float = Field(
        default=0.0,
        ge=0,
        title="Other load per metre",
        description="Load at right angles to the anchorage force [kN/m]: gravity on a ledger or "
        "diaphragm shear on a sill.",
    )


# ─────────────────────────── seismic isolators (B37, saengine.fem.isolation) ───────────────────────────


class IsolatorPropertyModification(_Model):
    """Alpha 9 P6: property modification factors λ of an isolator type (the ageing and
    environment, the prototype test and the specification tolerance factors on Qd and Kd).
    The code pack combines them into the lower- and upper-bound factors (its
    ``isolation.propertyModification``); they replace the two bound factors of the isolator.
    Enter the manufacturer's values."""

    aeMax: float = Field(
        default=1.0, ge=1, title="λae,max", description="Ageing and environment, upper bound."
    )
    aeMin: float = Field(
        default=1.0,
        gt=0,
        le=1,
        title="λae,min",
        description="Ageing and environment, lower bound.",
    )
    testMax: float = Field(
        default=1.0,
        ge=1,
        title="λtest,max",
        description="Prototype tests (heating, rate of loading, scragging), upper bound.",
    )
    testMin: float = Field(
        default=1.0, gt=0, le=1, title="λtest,min", description="Prototype tests, lower bound."
    )
    specMax: float = Field(
        default=1.0,
        ge=1,
        title="λspec,max",
        description="Permissible variation of the production units from the nominal values, "
        "upper bound.",
    )
    specMin: float = Field(
        default=1.0,
        gt=0,
        le=1,
        title="λspec,min",
        description="Permissible variation of the production units, lower bound.",
    )


#: Isolator kinds whose curve may come from a friction coefficient and a radius (sliding).
SLIDING_ISOLATORS = ("slidingPendulum", "tripleFrictionPendulum", "flatSlider")


class SeismicIsolator(_Model):
    """A seismic isolator under a column's base, by its bilinear force-displacement curve from
    the prototype tests: the effective stiffness (secant) and the effective damping (from the
    loop area) at any displacement follow from it. The values here are only a starting point:
    enter the tested values of the units used."""

    kind: Literal[
        "leadRubber",
        "elastomeric",
        "slidingPendulum",
        "other",
        "highDampingRubber",
        "tripleFrictionPendulum",
        "flatSlider",
    ] = Field(
        default="leadRubber",
        description="The isolator type: lead-rubber, (low-damping) elastomeric, single friction "
        "pendulum, other, high-damping rubber, triple friction pendulum, flat slider. The curve "
        "below is what the linear analysis uses; the nonlinear time history takes the type's "
        "element (Bouc-Wen bearing, friction pendulum, flat slider).",
        json_schema_extra={
            "enumDescriptions": [
                "Lead-rubber bearing (LRB)",
                "Elastomeric bearing",
                "Friction pendulum, single (FPS)",
                "Other",
                "High-damping rubber bearing (HDRB)",
                "Friction pendulum, triple",
                "Flat slider",
            ]
        },
    )
    characteristicStrength: float = Field(
        default=60,
        ge=0,
        description="Qd: the force at zero displacement of the bilinear loop [kN] (lead core "
        "yield, or the friction force of a sliding unit).",
    )
    postYieldStiffness: float = Field(
        default=800, gt=0, description="Kd: the stiffness after yield [kN/m]."
    )
    yieldDisplacement: float = Field(
        default=15, gt=0, description="Dy: the displacement at yield [mm]."
    )
    verticalStiffness: float = Field(
        default=1.0e6, gt=0, description="Kv: the axial stiffness of the unit [kN/m]."
    )
    lowerBoundFactor: float = Field(
        default=1.0,
        gt=0,
        le=1,
        description="Factor on Qd and Kd for the lower-bound properties over the building's "
        "life (displacements); 1: no variation entered.",
    )
    upperBoundFactor: float = Field(
        default=1.0,
        ge=1,
        description="Factor on Qd and Kd for the upper-bound properties over the building's "
        "life (forces); 1: no variation entered.",
    )
    displacementCapacity: float | None = Field(
        default=None,
        gt=0,
        description="The largest displacement the unit takes (or a restraint allows) [mm]; "
        "none: not checked against the total maximum displacement.",
    )
    verticalCapacity: float | None = Field(
        default=None,
        gt=0,
        description="The tested vertical load the unit is stable under at the total maximum "
        "displacement [kN]; none: not entered.",
    )
    activationForce: float | None = Field(
        default=None,
        gt=0,
        description="The force that fully activates the unit (yield, break-away friction or a "
        "sacrificial wind restraint) [kN]; none: Qd + Kd·Dy.",
    )
    testVerticalLoad: float | None = Field(
        default=None,
        gt=0,
        description="Vertical load of the prototype tests (average dead load plus half the "
        "live load on the units of this type) [kN]; none: the seismic weight per unit.",
    )
    # ── alpha 9 P6 ──
    frictionCoefficient: float | None = Field(
        default=None,
        gt=0,
        lt=1,
        title="Friction coefficient μ",
        description="Sliding isolators: the friction coefficient of the sliding surface; with "
        "it Qd = μ·P and Kd = P / R under the unit's vertical load P (the test vertical load, "
        "else the seismic weight per unit). None: Qd and Kd as entered.",
    )
    radius: float | None = Field(
        default=None,
        gt=0,
        title="Effective radius R",
        description="Friction pendulums: the effective radius of curvature of the sliding "
        "surface [mm] (a triple pendulum: its equivalent single radius); none on a flat slider.",
    )
    propertyModification: IsolatorPropertyModification | None = Field(
        default=None,
        title="Property modification factors λ",
        description="The λ factors of the type; the code pack combines them into the lower- and "
        "upper-bound factors, which then replace the two bound factors above. None: the bound "
        "factors as entered.",
    )


# ─────────────── alpha 9 L1: precast pieces (checked by saengine.design.precast) ───────────────

#: The precast element of each object kind (a type's ``precast.element`` must be one of them).
PRECAST_ELEMENTS: dict[str, tuple[str, ...]] = {
    "slab": ("hollowCore", "doubleTee"),
    "beam": ("beam",),
    "column": ("column",),
    "wall": ("wallPanel",),
}


class PrecastInsert(_Model):
    """A cast-in insert of a precast piece: a lifting anchor or an erection insert."""

    position: float = Field(
        ge=0,
        description="Along the piece from its start (a column, a wall panel: from its bottom) "
        "[mm].",
    )
    offset: float = Field(default=0, description="Across the piece from its centre line [mm].")
    use: Literal["lifting", "erection", "both"] = Field(
        default="both",
        description="Lifting from the mould and handling, erection only, or both.",
        json_schema_extra={"enumDescriptions": ["Lifting and handling", "Erection", "Both"]},
    )
    workingLoad: float = Field(
        gt=0,
        title="Working load limit",
        description="The insert's rated working load (the maker's, at the safety factor of its "
        "rating) [kN].",
    )
    ultimateLoad: float | None = Field(
        default=None,
        gt=0,
        title="Ultimate load",
        description="Its tested ultimate load in this concrete [kN]; given: the code pack's "
        "safety factor on it is checked too.",
    )
    name: str | None = Field(default=None, description="Product or type, for the drawings.")


class PrecastCorbel(_Model):
    """A corbel cast with a precast column (designed with the code pack's corbel method)."""

    face: Literal["+x", "-x", "+y", "-y"] = Field(
        description="The column face it projects from (local axes of the column's profile)."
    )
    height: float = Field(
        gt=0, description="From the column piece's bottom to the corbel's bearing face [mm]."
    )
    corbel: Corbel


class PrecastConnection(_Model):
    """A connection of a precast piece to what supports it or to the piece next to it."""

    id: Id
    kind: Literal["bearing", "dowel", "corbelBearing", "weldedPlate"] = Field(
        description="Bearing on a support (seat, ledge or wall), dowels across the joint, the "
        "bearing on a corbel of the column (its corbel by ``corbel``), or a welded plate "
        "connection (embedded plates joined by a fillet-welded plate or bar).",
        json_schema_extra={
            "enumDescriptions": ["Bearing", "Dowels", "Bearing on a corbel", "Welded plate"]
        },
    )
    at: Literal["start", "end", "both", "base", "top"] = Field(
        default="both",
        description="Which end of the piece (a column or a wall panel: its base or top).",
    )
    bearingLength: float | None = Field(
        default=None,
        gt=0,
        title="Bearing length",
        description="The seating detailed: from the support's edge to the piece's end [mm].",
    )
    bearingWidth: float | None = Field(
        default=None,
        gt=0,
        title="Bearing width",
        description="Width of the bearing (pad) across the piece [mm]; empty: the piece's.",
    )
    bedding: Literal["dry", "bedded"] = Field(
        default="bedded",
        description="Dry: the piece on the bare support; bedded: on mortar, a pad or a strip.",
        json_schema_extra={"enumDescriptions": ["Dry", "Bedded (mortar or pad)"]},
    )
    support: Literal["precast", "castInSitu", "steel", "masonry"] = Field(
        default="precast",
        description="What the piece sits on (the tolerances and the ineffective edges of "
        "the code pack's bearing method).",
        json_schema_extra={
            "enumDescriptions": ["Precast concrete", "Cast in situ concrete", "Steel", "Masonry"]
        },
    )
    endBars: Literal["continuous", "straight", "exposed", "loops"] = Field(
        default="straight",
        title="Bars at the end",
        description="How the piece's bars end over the support: continuous over it, straight "
        "bars or horizontal loops near the end, tendons or bars exposed at the end, vertical "
        "loops.",
        json_schema_extra={
            "enumDescriptions": [
                "Continuous over the support",
                "Straight bars or horizontal loops",
                "Exposed at the end",
                "Vertical loops",
            ]
        },
    )
    dowels: int = Field(default=0, ge=0, description="Dowels across the joint.")
    dowelDia: float | None = Field(default=None, gt=0, title="Dowel diameter", description="[mm]")
    dowelMaterial: Id | None = Field(
        default=None,
        title="Dowel material",
        description="Rebar or steel of 03 Materials; empty: the piece's reinforcement material.",
    )
    eccentricity: float = Field(
        default=0,
        ge=0,
        description="Dowels: where the shear acts from the joint face (a soft bearing pad) [mm].",
    )
    surface: Literal["roughened", "notRoughened", "monolithic"] = Field(
        default="roughened",
        description="Dowels: the joint's surface (the code pack's shear transfer across it).",
        json_schema_extra={"enumDescriptions": ["Roughened", "Not roughened", "Monolithic"]},
    )
    corbel: int | None = Field(
        default=None,
        ge=0,
        description="Bearing on a corbel: the index (from 0) of the supporting column type's "
        "corbel; the corbel is designed for this connection's shear.",
    )
    corbelType: Id | None = Field(
        default=None,
        title="Corbel column type",
        description="Bearing on a corbel: the precast column type whose corbel carries the piece.",
    )
    weldSize: float | None = Field(
        default=None, gt=0, title="Weld size", description="Welded plate: fillet weld leg [mm]."
    )
    weldLength: float | None = Field(
        default=None,
        gt=0,
        title="Weld length",
        description="Welded plate: total effective fillet weld length [mm].",
    )
    electrode: float = Field(default=480, gt=0, description="Welded plate: FEXX [MPa].")
    shear: float | None = Field(
        default=None,
        ge=0,
        description="Factored shear (the vertical reaction of a bearing) [kN]; empty: from the "
        "piece's weight and the floor's loads by the code pack's gravity combinations.",
    )
    tension: float | None = Field(
        default=None,
        ge=0,
        description="Factored horizontal tension on the joint [kN]; empty: the code pack's "
        "share of the shear (restraint, shrinkage).",
    )


class PrecastPiece(_Model):
    """A precast concrete piece (alpha 9 L1): the type is cast in a factory, lifted from its
    mould, stored, transported and erected, then connected. The checks of every stage, its
    connections and its shop drawing follow from this; the analysis takes the type as it
    takes any other of its kind."""

    element: Literal["hollowCore", "doubleTee", "beam", "column", "wallPanel"] = Field(
        description="Hollow-core or double-tee floor units (slab types), a beam, a column or a "
        "wall panel.",
        json_schema_extra={
            "enumDescriptions": [
                "Hollow-core slab units",
                "Double-tee units",
                "Precast beam",
                "Precast column",
                "Wall panel",
            ]
        },
    )
    mark: str | None = Field(
        default=None,
        description="Piece mark prefix on the drawings; empty: the object type's id.",
    )
    unitWidth: float | None = Field(
        default=None,
        gt=0,
        title="Unit width",
        description="Floor units: the nominal width of one unit [mm] (hollow-core 1200, double "
        "tee 2400 when empty). Wall panels: the largest panel width [mm] (empty: one panel "
        "per wall).",
    )
    spanDirection: Literal["x", "y"] = Field(
        default="x",
        title="Span direction",
        description="Floor units: the direction they span in plan.",
    )
    cores: int | None = Field(
        default=None, ge=0, description="Hollow-core: the number of cores in one unit."
    )
    coreDiameter: float | None = Field(
        default=None, gt=0, title="Core diameter", description="Hollow-core: [mm]."
    )
    flangeThickness: float | None = Field(
        default=None, gt=0, title="Flange thickness", description="Double tee: [mm]."
    )
    stemWidth: float | None = Field(
        default=None, gt=0, title="Stem width", description="Double tee: mean stem width [mm]."
    )
    stemSpacing: float | None = Field(
        default=None,
        gt=0,
        title="Stem spacing",
        description="Double tee: centre to centre of the two stems [mm] (empty: half the width).",
    )
    topping: float = Field(
        default=0,
        ge=0,
        description="Floor units: cast-in-place structural topping over them [mm] (on the piece "
        "in service, not while it is handled).",
    )
    facing: float = Field(
        default=0,
        ge=0,
        description="Sandwich wall panels: the outer (non-structural) wythe [mm]; 0: a solid "
        "panel.",
    )
    insulation: float = Field(
        default=0, ge=0, description="Sandwich wall panels: the insulation between wythes [mm]."
    )
    length: float | None = Field(
        default=None,
        gt=0,
        description="The piece's length [mm]; empty: from the building model (each element).",
    )
    stripStrength: float | None = Field(
        default=None,
        gt=0,
        title="Strength at stripping",
        description="f'ci when lifted from the mould [MPa]; empty: the code pack's share of "
        "the specified strength.",
    )
    mouldFinish: Literal["flatRemovable", "flatFalseJoints", "fluted", "sculptured"] = Field(
        default="flatRemovable",
        title="Mould and finish",
        description="How the piece leaves its mould (the code pack's form suction and "
        "impact multipliers at stripping).",
        json_schema_extra={
            "enumDescriptions": [
                "Flat, removable side forms",
                "Flat with false joints",
                "Fluted, proper draft",
                "Sculptured",
            ]
        },
    )
    rigging: Literal["twoPoint", "fourPointEqualised", "fourPointRigid"] = Field(
        default="twoPoint",
        description="How it is lifted: two points, four points with equalising sheaves, four "
        "points without them (the code pack's inserts taken to carry the load).",
        json_schema_extra={
            "enumDescriptions": [
                "Two points",
                "Four points, equalised",
                "Four points, not equalised",
            ]
        },
    )
    slingAngle: float = Field(
        default=60,
        gt=0,
        le=90,
        title="Sling angle",
        description="Of the slings from the horizontal [°] (90: a vertical lift with a beam).",
    )
    supports: list[float] = Field(
        default_factory=list,
        description="Where it rests in storage and on the truck, from its start [mm]; empty: "
        "at its lifting inserts.",
    )
    inserts: list[PrecastInsert] = Field(default_factory=list)
    corbels: list[PrecastCorbel] = Field(
        default_factory=list, description="Columns: the corbels cast with the piece."
    )
    connections: list[PrecastConnection] = Field(default_factory=list)
    superimposedDead: float | None = Field(
        default=None,
        ge=0,
        title="Superimposed dead load",
        description="Supported by the piece [kN/m² on floor units, kN/m on beams]; empty: floor "
        "units take their slab's area load, beams none.",
    )
    live: float | None = Field(
        default=None,
        ge=0,
        description="Live load on the piece [kN/m² on floor units, kN/m on beams]; empty: floor "
        "units take their slab's area load, beams none.",
    )
    erectionWind: float | None = Field(
        default=None,
        ge=0,
        title="Erection wind",
        description="Wind pressure while it stands unconnected [kPa]; empty: the code pack's.",
    )
    baseMoment: float | None = Field(
        default=None,
        gt=0,
        title="Temporary base moment",
        description="Columns: the moment the temporary base (shims, bolts, socket wedges) takes "
        "before it is grouted [kN·m]; empty: the free-standing stability is not checked.",
    )
    braceCapacity: float | None = Field(
        default=None,
        gt=0,
        title="Brace capacity",
        description="Wall panels: the working capacity of each of the two temporary braces "
        "[kN]; empty: only the brace force is given.",
    )
    braceHeight: float | None = Field(
        default=None,
        gt=0,
        title="Brace height",
        description="Wall panels: where the braces attach above its base [mm]; empty: 2/3 of "
        "its height.",
    )


# ─────────────────────────────────── object types ───────────────────────────────────


class _ObjectBase(_Model):
    id: Id
    name: str = Field(min_length=1)
    material: Id
    description: str | None = None


#: Member uses of the deflection limits (the code pack's serviceability table names the span
#: divisors of each; a use the pack does not list is not checked).
DEFLECTION_USES = (
    "floor",
    "roofPlasterCeiling",
    "roofOtherCeiling",
    "roofNoCeiling",
    "wallBrittle",
    "wallFlexible",
    "farm",
    "greenhouse",
    "metalSheeting",
    "metalRoofSecondary",
    "metalWallSecondary",
)


class MemberServiceability(_Model):
    """What the deflection limits of a steel beam follow (serviceability, B9)."""

    use: Literal[DEFLECTION_USES] | None = Field(  # type: ignore[valid-type]
        default=None,
        title="Member use",
        description="The use whose deflection limits apply; none: the code pack's default use.",
        json_schema_extra={
            "enumDescriptions": [
                "Floor member",
                "Roof member supporting a plaster ceiling",
                "Roof member supporting a non-plaster ceiling",
                "Roof member not supporting a ceiling",
                "Wall member, brittle finishes",
                "Wall member, flexible finishes",
                "Farm building",
                "Greenhouse",
                "Formed metal roofing or siding",
                "Purlin under formed metal roofing",
                "Girt under formed metal siding",
            ]
        },
    )
    freeEnd: Literal["none", "start", "end"] = Field(
        default="none",
        title="Cantilever",
        description="A cantilever: the end that is free (its span for the limits is the "
        "multiple of its length the code pack gives).",
        json_schema_extra={"enumDescriptions": ["Supported at both ends", "Start", "End"]},
    )


class CompositeTopping(_Model):
    """A concrete beam built in two placements (a precast or first-cast stem and a
    cast-in-place part over it) that act as one: the contact surface and its ties."""

    toppingThickness: float = Field(
        gt=0,
        title="Cast-in-place thickness",
        description="Least dimension of the part cast on top [mm] (the ties' spacing).",
    )
    surface: Literal["roughened", "smooth"] = Field(
        default="roughened",
        description="Contact surface clean and intentionally roughened, or not roughened.",
    )
    ties: bool = Field(
        default=True, description="The stirrups run into the top part as ties across the surface."
    )
    contactWidth: float | None = Field(
        default=None, gt=0, title="Contact width", description="[mm]; none: the beam's width."
    )
    tension: bool = Field(
        default=False, description="Tension across the contact surface (shear only with ties)."
    )


class Beam(_ObjectBase):
    kind: Literal["beam"] = "beam"
    profile: Profile
    reinforcement: LinearReinforcement | None = None
    seismicRole: SeismicRole = _role()
    omegaCombinations: OmegaCombinations = _omega()
    connection: SteelConnection | None = Field(
        default=None,
        description="Steel beams: the connection at both ends (fin plate or shear end plate: "
        "simple, the ends pinned in the analysis; flange plates or a welded HSS moment "
        "connection: the ends kept rigid); none: not checked.",
    )
    splice: SteelSplice | None = Field(
        default=None, description="Steel I-beams: a bolted cover-plate splice; none: no splice."
    )
    timber: TimberMember | None = Field(
        default=None,
        description="Timber members: bearing, notches, restraints, cantilever, spaced column; "
        "none: the defaults.",
    )
    timberJoint: TimberJoint | None = Field(
        default=None,
        title="Timber joint",
        description="Timber members: the nailed, bolted, split-ring or disc-dowel joint at both "
        "ends; none: not checked.",
    )
    bamboo: BambooMember | None = Field(
        default=None, description="Bamboo members: bundle, truss member, joints (B39)."
    )
    ferrocement: FerrocementMember | None = Field(
        default=None, description="Ferrocement members: the mesh layers (B39)."
    )
    serviceability: MemberServiceability | None = Field(
        default=None,
        title="Deflection limits",
        description="Steel beams: the member use the deflection limits follow and a "
        "cantilever's free end; none: the code pack's default use, supported at both ends.",
    )
    composite: CompositeBeam | None = Field(
        default=None,
        description="Steel beams: acting with the slab through shear connectors; none: the "
        "steel alone.",
    )
    compositeTopping: CompositeTopping | None = Field(
        default=None,
        title="Composite concrete",
        description="Concrete beams cast in two placements acting as one (a precast stem with "
        "a cast-in-place top): the horizontal shear at the contact surface is checked; none: "
        "cast in one piece.",
    )
    precast: PrecastPiece | None = Field(
        default=None,
        description="A precast concrete piece (alpha 9 L1): its element, inserts, corbels and "
        "connections; the handling, erection and connection checks, its shop drawing and its "
        "piece schedule follow; none: cast in place.",
    )
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


class Column(_ObjectBase):
    kind: Literal["column"] = "column"
    profile: Profile
    reinforcement: LinearReinforcement | None = None
    seismicRole: SeismicRole = _role()
    omegaCombinations: OmegaCombinations = _omega()
    splice: SteelSplice | None = Field(
        default=None,
        description="Steel I-columns: a bolted cover-plate splice; none: no splice.",
    )
    basePlate: ColumnBasePlate | None = Field(
        default=None,
        description="Steel columns: the base plate and anchor rods where the column stands on "
        "a support; none: not checked.",
    )
    capPlate: HssCapPlate | None = Field(
        default=None,
        title="Cap plate",
        description="Rectangular HSS columns: a cap plate at the top carrying a beam that "
        "bears on it; none: not checked.",
    )
    composite: CompositeColumn | None = Field(
        default=None,
        description="Steel columns: encased in reinforced concrete or a concrete-filled HSS; "
        "none: the steel alone.",
    )
    timber: TimberMember | None = Field(
        default=None,
        description="Timber members: bearing, notches, restraints, cantilever, spaced column; "
        "none: the defaults.",
    )
    timberJoint: TimberJoint | None = Field(
        default=None,
        title="Timber joint",
        description="Timber members: the nailed, bolted, split-ring or disc-dowel joint at both "
        "ends; none: not checked.",
    )
    bamboo: BambooMember | None = Field(
        default=None, description="Bamboo members: bundle, truss member, joints (B39)."
    )
    ferrocement: FerrocementMember | None = Field(
        default=None, description="Ferrocement members: the mesh layers (B39)."
    )
    precast: PrecastPiece | None = Field(
        default=None,
        description="A precast concrete piece (alpha 9 L1): its element, inserts, corbels and "
        "connections; the handling, erection and connection checks, its shop drawing and its "
        "piece schedule follow; none: cast in place.",
    )
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
    isolator: SeismicIsolator | None = Field(
        default=None,
        title="Seismic isolator",
        description="An isolator under the base of each column of this type that stands on a "
        "support: the analysis puts the column on it and designs the isolated building "
        "(08 FEM); none: a fixed base.",
    )


# ─────────────── B38: buckling-restrained braces and steel plate shear walls ───────────────
# Checked by saengine.design.steel.seismic_braced and seismic_walls (the code pack's
# steelSeismic table).


class BucklingRestrainedBrace(_Model):
    """The steel core of a buckling-restrained brace and its qualifying test results."""

    type: Literal["bucklingRestrained"] = "bucklingRestrained"
    coreArea: float = Field(gt=0, description="Net area of the steel core Asc [mm²].")
    beta: float = Field(
        gt=0,
        title="β (compression adjustment)",
        description="Largest compression / tension force of the qualifying tests at twice the "
        "design storey drift (at least the code pack's least β).",
    )
    omega: float = Field(
        gt=0,
        title="ω (strain hardening)",
        description="Largest tension force of the qualifying tests / Fysc Asc of the specimen.",
    )
    couponFy: bool = Field(
        default=False,
        title="Fysc from a coupon test",
        description="The core's yield stress is a coupon test's: Ry is not applied.",
    )


class SteelPlateWall(_Model):
    """Concrete encasing the steel plate of a composite plate shear wall."""

    type: Literal["steelPlateWall"] = "steelPlateWall"
    concrete: Literal["none", "oneSide", "bothSides"] = Field(
        default="none",
        json_schema_extra={"enumDescriptions": ["No concrete", "One side", "Both sides"]},
    )
    concreteMaterial: Id | None = Field(
        default=None, description="03 Materials id of the concrete; none: no concrete."
    )
    concreteThickness: float = Field(
        default=100, gt=0, description="Concrete on each encased side [mm]."
    )
    barRatio: float = Field(
        default=0.0025, ge=0, description="Bars in the concrete each way, As / Ac [-]."
    )
    barSpacing: float = Field(default=300, gt=0, description="Between the bars [mm].")
    connectors: bool = Field(
        default=True,
        description="Headed studs or other connectors tie the plate to the concrete.",
    )


# ─────────────── alpha 9 P6: supplemental dampers in braces (saengine.fem.dampers) ───────────────


class SupplementalDamper(_Model):
    """A damping device in each brace of this type (a damper brace): the brace carries the
    device between its two ends. Velocity-dependent (viscous F = C·v^α, viscoelastic) or
    displacement-dependent (metallic yielding, such as a buckling-restrained brace used as a
    damper, and friction). Enter the manufacturer's values."""

    kind: Literal["viscous", "viscoelastic", "metallic", "friction"] = Field(
        default="viscous",
        json_schema_extra={
            "enumDescriptions": [
                "Fluid viscous damper (F = C·v^α)",
                "Viscoelastic damper",
                "Metallic yielding damper",
                "Friction damper",
            ]
        },
    )
    coefficient: float | None = Field(
        default=None,
        gt=0,
        title="Damping coefficient C",
        description="Viscous dampers: C of F = C·v^α [kN·(s/m)^α].",
    )
    exponent: float = Field(
        default=1.0,
        gt=0,
        le=2,
        title="Velocity exponent α",
        description="Viscous dampers: α of F = C·v^α (1: linear).",
    )
    storageStiffness: float | None = Field(
        default=None,
        gt=0,
        title="Storage stiffness K′",
        description="Viscoelastic dampers: the in-phase stiffness at the building's "
        "fundamental frequency [kN/m].",
    )
    lossStiffness: float | None = Field(
        default=None,
        gt=0,
        title="Loss stiffness K″",
        description="Viscoelastic dampers: the out-of-phase stiffness at that frequency [kN/m] "
        "(C = K″/ω).",
    )
    yieldForce: float | None = Field(
        default=None,
        gt=0,
        title="Yield or slip force",
        description="Metallic dampers: the yield force; friction dampers: the slip force [kN].",
    )
    initialStiffness: float | None = Field(
        default=None,
        gt=0,
        title="Initial stiffness",
        description="Metallic and friction dampers: the elastic (stick) stiffness of the device "
        "with its brace [kN/m]; none: the brace's axial stiffness EA/L.",
    )
    postYieldRatio: float = Field(
        default=0.02,
        ge=0,
        lt=1,
        title="Post-yield stiffness ratio",
        description="Metallic dampers: the stiffness after yield over the initial stiffness.",
    )
    strokeCapacity: float | None = Field(
        default=None,
        gt=0,
        title="Stroke capacity",
        description="The largest deformation the device takes [mm]; none: not checked.",
    )
    forceCapacity: float | None = Field(
        default=None,
        gt=0,
        title="Force capacity",
        description="The largest force the device and its connections take [kN]; none: not "
        "checked.",
    )

    @model_validator(mode="after")
    def _values_of_the_kind(self) -> SupplementalDamper:
        needs = {
            "viscous": ("coefficient",),
            "viscoelastic": ("storageStiffness", "lossStiffness"),
            "metallic": ("yieldForce",),
            "friction": ("yieldForce",),
        }[self.kind]
        missing = [name for name in needs if getattr(self, name) is None]
        if missing:
            raise ValueError(f"a {self.kind} damper needs {', '.join(missing)}")
        return self


class Brace(_ObjectBase):
    """Bracing and truss members."""

    kind: Literal["brace"] = "brace"
    profile: Profile
    connection: SteelConnection | None = Field(
        default=None,
        description="Steel braces: the bolted gusset or the welded HSS truss joint at both "
        "ends; none: not checked.",
    )
    tensionOnly: bool = Field(
        default=False,
        title="Tension only",
        description="Rods and slender angles that buckle at a negligible load: each load "
        "combination releases the members it would compress, and they are designed for "
        "tension alone.",
    )
    restrained: BucklingRestrainedBrace | None = Field(  # B38
        default=None,
        title="Buckling-restrained",
        description="Steel braces of buckling-restrained braced frames: the core and the test "
        "results; none: a conventional brace.",
    )
    damper: SupplementalDamper | None = Field(  # alpha 9 P6
        default=None,
        title="Damper",
        description="A damping device in each brace of this type (viscous, viscoelastic, "
        "metallic or friction): the analysis models it, works out the added damping and the "
        "damped design forces by the code pack (08 FEM); none: a plain brace.",
    )
    timber: TimberMember | None = Field(
        default=None,
        description="Timber members: bearing, notches, restraints, cantilever, spaced column; "
        "none: the defaults.",
    )
    timberJoint: TimberJoint | None = Field(
        default=None,
        title="Timber joint",
        description="Timber members: the nailed, bolted, split-ring or disc-dowel joint at both "
        "ends; none: not checked.",
    )
    bamboo: BambooMember | None = Field(
        default=None, description="Bamboo members: bundle, truss member, joints (B39)."
    )
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


class CompositeSlabDeck(_Model):
    """Alpha 9 P8: the profiled steel deck of a composite slab spanning one way along its ribs
    (:mod:`saengine.design.composite_slab`, the code pack's ``compositeSlab``). The geometry is
    the product's (or a generic profile's); the deck's section values are computed from it
    unless the manufacturer's are given. The longitudinal shear needs the deck's test values
    (m and k, or τu,Rk)."""

    profile: str | None = Field(
        default=None,
        description="A generic profile of saengine.design.composite_slab.DECK_PROFILES (its "
        "geometry replaces the one below); none: the geometry below.",
    )
    direction: Literal["x", "y"] = Field(
        default="x", description="The ribs (and the slab's span) along the slab's local x or y."
    )
    span: float | None = Field(
        default=None,
        gt=0,
        description="Span of the deck between its supports [mm]; none: the slab's extent along "
        "the ribs.",
    )
    spans: int = Field(
        default=1,
        ge=1,
        description="Spans the deck sheet is continuous over while the concrete is wet (the "
        "composite slab is designed as simply supported).",
    )
    propped: bool = Field(
        default=False, description="Props carry the wet concrete (else the deck)."
    )
    ribHeight: float = Field(default=60, gt=0, description="Height of the deck hp [mm].")
    pitch: float = Field(default=300, gt=0, description="Centres of the ribs [mm].")
    ribTopWidth: float = Field(
        default=180, gt=0, description="Width of a concrete rib at the top of the deck [mm]."
    )
    ribBottomWidth: float = Field(
        default=120, gt=0, description="Width of a concrete rib at its bottom [mm]."
    )
    thickness: float = Field(
        default=0.9, gt=0, lt=5, description="Design (core) thickness of the sheet [mm]."
    )
    fyp: float = Field(default=350, gt=0, description="Yield strength of the deck [MPa].")
    E: float = Field(default=210000, gt=0, description="Modulus of the deck [MPa].")
    m: float | None = Field(
        default=None, gt=0, description="m of the shear bond from the deck's tests [N/mm²]."
    )
    k: float | None = Field(
        default=None, ge=0, description="k of the shear bond from the deck's tests [N/mm²]."
    )
    tauU: float | None = Field(
        default=None,
        gt=0,
        title="τu,Rk",
        description="Longitudinal shear strength of the partial connection method from the "
        "deck's tests [N/mm²].",
    )
    momentResistance: float | None = Field(
        default=None,
        gt=0,
        description="The deck's design sagging resistance per metre width (its effective "
        "section) from the manufacturer [kN·m/m]; none: the gross section's (reported).",
    )
    hoggingResistance: float | None = Field(
        default=None,
        gt=0,
        description="The deck's design resistance over an inner support [kN·m/m] (continuous "
        "sheets); none: the sagging one.",
    )
    inertia: float | None = Field(
        default=None,
        gt=0,
        description="The deck's effective second moment of area per metre [mm⁴/m]; none: the "
        "gross section's.",
    )
    area: float | None = Field(
        default=None, gt=0, description="Ap per metre [mm²/m]; none: from the geometry."
    )
    centroid: float | None = Field(
        default=None,
        gt=0,
        description="e, the deck's centroid above its bottom [mm]; none: from the geometry.",
    )
    plasticMoment: float | None = Field(
        default=None,
        gt=0,
        description="Mpa, the deck's plastic moment per metre at its design strength "
        "[kN·m/m]; none: from the geometry.",
    )
    weight: float | None = Field(
        default=None, ge=0, description="Self weight of the deck [kN/m²]; none: from the steel."
    )
    beamFlange: bool = Field(
        default=False,
        description="The slab is the flange of composite beams (its least depths are larger).",
    )


class Slab(_ObjectBase):
    kind: Literal["slab"] = "slab"
    thickness: Length = Field(description="[mm]; with ribs: the topping over them.")
    system: Literal["oneWay", "twoWay", "flat"] = "twoWay"
    reinforcement: PlanarReinforcement | None = None
    ribs: SlabRibs | None = Field(
        default=None,
        description="Ribs under the slab: ribbed (one way) or waffle (both ways); empty: solid. "
        "Bottom bars are given per metre width and placed in the ribs.",
    )
    dropPanel: DropPanel | None = Field(
        default=None,
        title="Drop panel",
        description="Thickening under every column of a flat slab (on a waffle slab: the "
        "solid head); empty: none.",
    )
    capital: ColumnCapital | None = Field(
        default=None,
        title="Column capital",
        description="Flared head of every column under a flat slab; empty: none.",
    )
    punchingReinforcement: PunchingReinforcement | None = Field(
        default=None,
        title="Punching reinforcement",
        description="Studs or stirrups round the columns of a flat slab, checked where the "
        "concrete alone is not enough (empty: none).",
    )
    precast: PrecastPiece | None = Field(
        default=None,
        description="A precast concrete piece (alpha 9 L1): its element, inserts, corbels and "
        "connections; the handling, erection and connection checks, its shop drawing and its "
        "piece schedule follow; none: cast in place.",
    )
    modifiers: ShellModifiers | None = Field(
        default=None,
        title="Stiffness modifiers",
        description="Factors on the analysis shell stiffness, mass and weight (empty: the "
        "code's cracked factors for concrete and masonry, else 1).",
    )
    compositeDeck: CompositeSlabDeck | None = Field(
        default=None,
        title="Composite deck",
        description="A composite slab on profiled steel deck (thickness: the overall depth, "
        "over the ribs); empty: a concrete slab.",
    )


class GradeBeamWall(_Model):
    """A wall designed as a grade beam spanning between its supports (footings, pile caps)."""

    span: float | None = Field(
        default=None,
        gt=0,
        description="Clear span between the supports [mm]; none: the wall's length.",
    )
    continuous: bool = Field(
        default=False,
        description="Continuous over its supports (top bars over them); else simply supported.",
    )
    bottomBars: int = Field(default=2, ge=0, title="Bottom bars")
    bottomDia: float = Field(default=16, gt=0, title="Bottom bar size", description="[mm]")
    topBars: int = Field(default=2, ge=0, title="Top bars")
    topDia: float = Field(default=16, gt=0, title="Top bar size", description="[mm]")


class Wall(_ObjectBase):
    kind: Literal["wall"] = "wall"
    thickness: Length
    structural: bool = Field(
        default=True, description="False for partition/infill walls that carry no lateral load."
    )
    reinforcement: WallReinforcement | None = None
    braced: bool = Field(
        default=True,
        description="Braced top and bottom against lateral translation (the default pack's 6.6.5.2).",
    )
    restrainedEnds: bool = Field(
        default=True,
        title="Restrained ends",
        description="Restrained against rotation at one or both ends (the default pack's 6.6.5.2).",
    )
    basement: bool = Field(
        default=False,
        description="Exterior basement or foundation wall (the default pack's 6.6.3.4, 6.6.5.3).",
    )
    precast: PrecastPiece | None = Field(
        default=None,
        description="A precast concrete piece (alpha 9 L1): its element, inserts, corbels and "
        "connections; the handling, erection and connection checks, its shop drawing and its "
        "piece schedule follow; none: cast in place.",
    )
    modifiers: ShellModifiers | None = Field(
        default=None,
        title="Stiffness modifiers",
        description="Factors on the analysis shell stiffness, mass and weight (empty: the "
        "code's cracked factors for concrete and masonry, else 1).",
    )
    gradeBeam: GradeBeamWall | None = Field(
        default=None,
        title="Grade beam",
        description="The wall also spans as a grade beam between its supports: top and bottom "
        "bars for the moment and its vertical bars for the shear (the code pack's walls as "
        "grade beams); none: not a grade beam.",
    )
    # B34: masonry walls.
    masonryMethod: Literal["allowableStress", "strength"] | None = Field(
        default=None,
        title="Masonry design method",
        description="Masonry walls: the code pack's method (empty) or one it permits in lieu of "
        "it (strength design of reinforced slender walls and shear walls).",
        json_schema_extra={"enumDescriptions": ["Allowable stress design", "Strength design"]},
    )
    confinement: WallConfinement | None = Field(
        default=None,
        title="Confined masonry",
        description="Masonry walls confined by RC tie columns and tie beams; empty: not confined.",
    )
    anchorBolts: MasonryAnchorBolts | None = Field(
        default=None,
        title="Anchor bolts",
        description="Masonry walls: the bolts anchoring the wall to each floor or roof.",
    )
    # B38: steel plate shear walls.
    plateWall: SteelPlateWall | None = Field(
        default=None,
        title="Steel plate wall",
        description="Steel walls (a steel material; the thickness is the web plate's): the "
        "concrete encasing the plate of a composite plate shear wall; none: a steel plate "
        "shear wall without concrete.",
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
        description="How the flights span (the default pack's Part 6 Sec 6.7.1.1 (a)-(d)).",
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
    builtIntoWall: bool = Field(
        default=False,
        title="Built into walls",
        description="Flights and landings built into the walls at their sides (by the code "
        "pack's least embedment): a strip off the loaded width, a wider effective breadth.",
    )
    openWell: bool = Field(
        default=False,
        title="Open well",
        description="A dog-legged stair with an open well: the load where the flight and "
        "landing spans cross is shared between them.",
    )
    stringerBeams: bool = Field(
        default=False,
        title="Stringer beams",
        description="The steps span across the flight between stringer beams at its sides "
        "(the stringers' forces are reported for their design as beams).",
    )
    special: Literal["none", "freeStanding", "sawtooth", "helicoidal"] = Field(
        default="none",
        title="Special stair",
        description="A special stair by the code pack's methods: free-standing (dog-legged, "
        "landing unsupported), sawtooth (slabless) or helicoidal; none: a waist-slab stair.",
    )
    riserThickness: float | None = Field(
        default=None,
        gt=0,
        title="Riser thickness",
        description="Sawtooth stairs [mm]; none: the waist.",
    )
    innerRadius: float | None = Field(
        default=None, ge=0, title="Inner radius", description="Helicoidal stairs [mm]."
    )
    outerRadius: float | None = Field(
        default=None, gt=0, title="Outer radius", description="Helicoidal stairs [mm]."
    )
    planAngle: float | None = Field(
        default=None,
        gt=0,
        le=360,
        title="Plan angle",
        description="Helicoidal stairs: the total angle the helix subtends in plan [°].",
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
            precast = getattr(o, "precast", None)  # Alpha 9 L1
            if precast is not None and precast.element not in PRECAST_ELEMENTS.get(o.kind, ()):
                allowed = ", ".join(PRECAST_ELEMENTS.get(o.kind, ())) or "none"
                raise ValueError(
                    f"'{o.id}': a {o.kind} type cannot be a precast {precast.element} "
                    f"(allowed: {allowed})"
                )
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
            confinement = getattr(o, "confinement", None)
            if confinement is not None:  # B34: confined masonry
                for mid, category in (
                    (confinement.concrete, Category.CONCRETE),
                    (confinement.rebar, Category.REBAR),
                ):
                    found = materials.get(mid)
                    if found is None or found.category != category:
                        problems.append(
                            f"{o.id}: confinement material '{mid}' is not a {category.value}"
                        )
        return problems
