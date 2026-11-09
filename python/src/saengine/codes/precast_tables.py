"""Table model of precast concrete pieces (alpha 9 L1): ``precast``.

What a code (or a pack's chosen practice) gives for precast members and their connections,
read by :mod:`saengine.design.precast`; this module holds no numbers:

- ``bearing``: the seating of a piece on its support, by method id: ``spanRatio`` (the
  ACI 318 / BNBC 2020 form: at least ln / ``spanDivisor`` and the least length of the member
  class, the pad set back from an unarmoured edge, the bearing stress on the concrete) or
  ``netBearing`` (the EN 1992-1-1 10.9.5.2 form: a = a1 + a2 + a3 + √(Δa2² + Δa3²) with the
  bearing strength fRd and the tabulated least lengths and ineffective edges);
- ``dowel``: dowels across a joint, by method id: ``shearFriction`` (the pack's shear transfer
  across the joint, :func:`saengine.design.rc_detailing.shear_friction`) or ``dowelAction``
  (the fib Bulletin 43 / Engström form F = α0 αe Φ² √(fcd fyd) / γRd, the eccentricity of the
  load reducing αe);
- ``corbel`` and ``weldedPlate``: the method ids of the existing corbel design
  (:func:`saengine.design.corbels.corbel_checks`) and fillet welds
  (:func:`saengine.design.steel_connections.fillet_capacity_per_mm`) that the connections use;
- ``tension``: the least horizontal tension on a bearing as a share of its shear;
- ``integrity``: structural integrity ties (method ``tieForces``: diaphragm connections per
  metre, columns' tension per gross area, panel ties; large-panel bearing wall buildings);
- ``handling``: stripping, yard, transport and erection multipliers, the strength at stripping,
  the allowed concrete tension while handled (c · f'ci^n / safety), the inserts carrying the
  load per rigging, the insert safety factor;
- ``erection``: the wind on a piece standing unconnected, the safety against overturning and
  the lateral stability of a hanging member (method ``hangingBeam``, Mast 1989/1993: FS =
  yr / (zo + ei) against the least).

Every number is the pack's; its VERIFY.md gives each value's source.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from saengine.codes.tables import Positive, Share, TableModel, _Group

# ─────────────────────────────── bearing ───────────────────────────────


class SpanRatioBearing(_Group):
    """``spanRatio``: the seating at least ln / spanDivisor and ``minimum[class]`` (classes
    ``slab``: solid or hollow-core slabs; ``stemmed``: beams and stemmed members), the pad set
    back ``padSetback`` from an unarmoured edge; the bearing stress Vu <= φ ``stressFactor``
    f'c A1 (φ: the pack's factors ``phi.bearing``)."""

    method: Literal["spanRatio"] = "spanRatio"
    spanDivisor: Positive = Field(description="The seating at least ln / this.")
    minimum: dict[str, Positive] = Field(
        min_length=1, description="Least seating by member class (slab, stemmed) [mm]."
    )
    padSetback: float = Field(
        ge=0, description="Bearing pads set back from an unarmoured edge [mm]."
    )
    stressFactor: Positive = Field(description="Bearing strength = this × f'c × A1.")


class NetBearing(_Group):
    """``netBearing``: a = a1 + a2 + a3 + √(Δa2² + Δa3²) (EN 1992-1-1 10.9.5.2 form).

    a1 = FEd / (b1 fRd), fRd = ``strength[bedding]`` × fcd, at least ``a1Minimum[support]`` by
    the relative bearing stress σEd/fcd (three columns: up to ``stressBands[0]``, up to
    ``stressBands[1]``, above); a2 the ineffective edge of the support (``a2[material
    + "." + support]``, same three columns); a3 the ineffective end of the piece
    (``a3[endBars + "." + support]``, [linear, concentrated]); Δa2 = ``supportTolerance
    [material]`` (l / divisor + add, clamped between min and max), Δa3 = ln / ``memberTolerance``.
    ``support``: "linear" (floor units on a line support), "ribbed" (ribbed floors, purlins),
    "concentrated" (beams)."""

    method: Literal["netBearing"] = "netBearing"
    strength: dict[str, Share] = Field(description="fRd / fcd by bedding (dry, bedded).")
    stressBands: tuple[Share, Share] = Field(description="σEd/fcd band limits.")
    a1Minimum: dict[str, tuple[Positive, Positive, Positive]] = Field(
        description="Least a1 by support kind (linear, ribbed, concentrated) and band [mm]."
    )
    a2: dict[str, tuple[float, float, float]] = Field(
        description="Ineffective support edge by '<material>.<linear|concentrated>' and band "
        "[mm] (materials: steel, concreteHigh (C30 and above), concreteLow, masonry)."
    )
    highStrength: Positive = Field(
        description="fck at and above which the support is 'concreteHigh' [MPa]."
    )
    a3: dict[str, tuple[float, float]] = Field(
        description="Ineffective end of the piece by its bars at the end (continuous, "
        "straight, exposed, loops): [linear, concentrated] [mm]."
    )
    a3CoverAtLeast: list[str] = Field(
        default_factory=list,
        description="End details whose a3 is at least the end cover (straight).",
    )
    supportTolerance: dict[str, tuple[Positive, float, float, float]] = Field(
        description="Δa2 by support material (precast or steel, castInSitu or masonry): "
        "(span divisor, added, least, largest) [mm]."
    )
    memberTolerance: Positive = Field(description="Δa3 = ln / this.")


Bearing = Annotated[SpanRatioBearing | NetBearing, Field(discriminator="method")]


# ─────────────────────────────── dowels ───────────────────────────────


class ShearFrictionDowels(_Group):
    """``shearFriction``: the dowels' area across the joint as shear-friction steel by the
    pack's shear transfer (detailing ``shearFriction`` or the concreteMethods interface shear)."""

    method: Literal["shearFriction"] = "shearFriction"


class DowelAction(_Group):
    """``dowelAction``: F = α0 αe Φ² √(fcd fyd) / γRd per dowel, αe = √(1 + (ε α0 e/Φ)²) − ε
    α0 e/Φ, ε = ``epsilon`` √(fcd/fyd), fcd = f'c / gammaC, fyd = fy / gammaS; at most the
    dowel's shear yield ``shearYield`` × fyd × As."""

    method: Literal["dowelAction"] = "dowelAction"
    alpha0: Positive = Field(description="α0 of the dowel action.")
    epsilon: Positive = Field(description="ε = this × √(fcd / fyd) (eccentricity).")
    gammaRd: Positive = Field(description="γRd of the dowel action.")
    gammaC: Positive = Field(description="Partial factor of concrete.")
    gammaS: Positive = Field(description="Partial factor of steel.")
    shearYield: Positive = Field(description="Shear yield of the bar = this × fyd × As.")


Dowel = Annotated[ShearFrictionDowels | DowelAction, Field(discriminator="method")]


class Connections(_Group):
    """The connection methods of the pack (methods of other modules by id)."""

    corbel: Literal["corbel"] | None = Field(
        default="corbel", description="Bearing on a corbel: the pack's corbel design."
    )
    weldedPlate: Literal["filletWeld"] | None = Field(
        default="filletWeld", description="Welded plates: the pack's fillet weld strength."
    )
    tensionShare: float = Field(
        ge=0,
        description="Least horizontal tension on a bearing as a share of its shear (restraint "
        "of shrinkage, creep and temperature) when none is entered.",
    )


# ─────────────────────────────── integrity ───────────────────────────────


class IntegrityTies(_Group):
    """``tieForces``: the least strengths of the ties of a precast structure."""

    method: Literal["tieForces"] = "tieForces"
    diaphragm: Positive = Field(
        description="Connections of floor diaphragms to the members they brace [kN/m]."
    )
    columnTension: Positive = Field(
        description="A column's nominal tension at its horizontal joints = this × Ag [N/mm²]."
    )
    panelTies: int = Field(ge=1, description="Ties per wall panel.")
    panelTieForce: Positive = Field(description="Nominal strength of each panel tie [kN].")
    bearingWallStoreys: int = Field(
        ge=1, description="Large-panel bearing wall buildings of this many storeys and more."
    )
    floorTies: Positive = Field(description="Their floor ties [kN/m of width or length].")
    floorTieSpacing: Positive = Field(description="Longitudinal floor ties apart at most [mm].")
    perimeterTie: Positive = Field(description="The perimeter tie [kN].")
    perimeterEdge: Positive = Field(description="Within this of the floor's edge [mm].")
    verticalTies: Positive = Field(description="Vertical ties in the walls [kN/m].")


# ─────────────────────────────── handling ───────────────────────────────


class ConcreteTension(_Group):
    """The tension allowed while a piece is handled: coefficient × f'ci^exponent / safety."""

    coefficient: Positive
    exponent: Positive
    safety: Positive


class Handling(_Group):
    """Equivalent static multipliers on the piece's weight and the handling rules."""

    stripping: dict[str, Positive] = Field(
        min_length=1,
        description="Form suction and impact at stripping by mould and finish (flatRemovable, "
        "flatFalseJoints, fluted, sculptured).",
    )
    yard: Positive = Field(description="Yard handling and storage.")
    transport: Positive = Field(description="Travel on the truck.")
    erection: Positive = Field(description="Erection.")
    stripShare: Share = Field(
        description="f'ci at stripping as a share of f'c when the piece gives none."
    )
    tension: ConcreteTension
    inserts: dict[str, Positive] = Field(
        description="Inserts taken to carry the load by rigging (twoPoint, fourPointEqualised, "
        "fourPointRigid)."
    )
    insertSafety: Positive = Field(
        description="Least ratio of an insert's ultimate load to its load (when one is given)."
    )


class HangingBeam(_Group):
    """``hangingBeam``: lateral stability of a member hanging from its lifting inserts."""

    method: Literal["hangingBeam"] = "hangingBeam"
    safety: Positive = Field(description="Least FS = yr / (zo + ei).")
    sweepDivisor: Positive = Field(description="Sweep tolerance = length / this.")
    insertTolerance: float = Field(ge=0, description="Lateral placing tolerance [mm].")


class Erection(_Group):
    """Pieces standing before their connections are made."""

    windPressure: float = Field(ge=0, description="Wind on a piece while erected [kPa].")
    overturningSafety: Positive = Field(
        description="Least ratio of the temporary base or brace capacity to its demand."
    )
    hanging: HangingBeam | None = None


class PrecastTable(TableModel):
    """Precast concrete pieces and their connections (see the module notes). A group left out
    is not covered: its checks say so."""

    bearing: Bearing | None = None
    dowel: Dowel | None = None
    connections: Connections
    integrity: IntegrityTies | None = None
    handling: Handling | None = None
    erection: Erection | None = None
