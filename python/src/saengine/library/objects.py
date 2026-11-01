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
    splice: SpliceZone | None = Field(default=None, title="Lap splices")


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


class PunchingReinforcement(_Model):
    """Shear reinforcement for punching around each column of a flat slab or footing: headed
    shear studs (BNBC 2020 Part 6 Sec 6.4.10.5) or stirrups (6.4.10.3), in peripheral lines
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
    """A thickening of a flat slab under every column it sits on (BNBC 2020 Part 6 Sec 6.5;
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
    sits on: square in plan, widening from the column to ``size`` over ``depth`` (BNBC 2020
    Part 6 Sec 6.5; ACI 318-11 13.1.2: only the part inside a 90° cone or pyramid from the
    column counts)."""

    size: Length = Field(
        description="Plan dimension of the capital where it meets the slab or drop panel [mm]."
    )
    depth: Length = Field(description="Depth of the flare below the slab or drop panel [mm].")


class SlabRibs(_Model):
    """Ribs under the slab: a ribbed (one-way joist) slab, or a waffle slab with ribs both ways
    (BNBC 2020 Part 6 joist construction; ACI 318-19 9.8.1). The slab's thickness is then the
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
    modifiers: ShellModifiers | None = Field(
        default=None,
        title="Stiffness modifiers",
        description="Factors on the analysis shell stiffness, mass and weight (empty: the "
        "code's cracked factors for concrete and masonry, else 1).",
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
