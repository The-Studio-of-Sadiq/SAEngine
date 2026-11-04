"""Table models of the limit state steel, masonry and composite methods a pack chooses by id
(alpha 9 C9, the pattern of :mod:`saengine.codes.method_tables`: each group names its method).

``steelLimitState`` holds steel members, connections and seismic frames by limit state design
with partial safety factors on the materials and buckling curves (IS 800:2007 is the first pack
to use it; EN 1993-1-1 is the same method family). The module is
:mod:`saengine.design.steel.limit_state`. A pack without the table designs steel by its
``steel`` table (LRFD with φ, the default pack): the default pack's results do not change.

The masonry method ``basicStress`` and the tabulated composite connectors of the same track
are groups of the ``masonry`` and ``composite`` tables (:mod:`saengine.codes.tables`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from saengine.codes.material_method_tables import (
    SteelDissipative,
    SteelJointResistances,
)
from saengine.codes.material_method_tables import SteelMemberResistance as MemberResistance
from saengine.codes.steel_remainder_tables import (  # alpha 9 C12
    SteelBracingForces,
    SteelColumnSide,
    SteelHssChordFace,
    SteelTorsionStresses,
)
from saengine.codes.tables import Positive, Share, TableModel, _Group

# ───────────────────────────────────── steelLimitState ─────────────────────────────────────


class SteelPartialFactors(_Group):
    """Partial safety factors of the materials (design resistance = characteristic / γ)."""

    gammaM0: Positive = Field(description="γm0: resistance governed by yielding or buckling.")
    gammaM1: Positive = Field(description="γm1: resistance governed by the ultimate stress.")
    gammaMb: Positive = Field(description="γmb: bolts of bearing type connections.")
    gammaMf: Positive = Field(description="γmf: slip of friction grip bolts at the ultimate load.")
    gammaMfService: Positive = Field(description="γmf: slip designed at the service load.")
    gammaMw: Positive = Field(description="γmw: welds, shop fabrication.")
    gammaMwField: Positive = Field(description="γmw: welds, field fabrication.")


class ClassLimits(_Group):
    """Width-thickness limits of one element in units of ε (``squared``: of ε², circular hollow
    sections): plastic (class 1), compact (class 2), semi-compact (class 3); above them slender.
    None: the class has no limit of its own for the element (the next one applies)."""

    plastic: Positive | None = None
    compact: Positive | None = None
    semiCompact: Positive
    squared: bool = False


class SteelClassification(_Group):
    """Section classification by width-thickness limits in ε = √(referenceFy / fy) (method
    ``epsilonLimits``)."""

    method: Literal["epsilonLimits"] = "epsilonLimits"
    referenceFy: Positive = Field(description="ε = √(referenceFy / fy) [MPa].")
    outstandRolled: ClassLimits = Field(description="Outstand of a compression flange, rolled.")
    outstandWelded: ClassLimits = Field(description="Outstand of a compression flange, welded.")
    internalFlange: ClassLimits = Field(description="Internal element of a flange in bending.")
    internalAxial: Positive = Field(description="Internal element in axial compression (class 3).")
    web: ClassLimits = Field(description="Web, neutral axis at mid-depth (d/tw).")
    webAxial: Positive = Field(description="Web in axial compression, class 3 (and the floor).")
    webAxialFactors: tuple[float, float, float] = Field(
        description="With axial compression the web limits ÷ (1 + k r), k for the plastic, "
        "compact and semi-compact limits (r: the axial stress over the design yield stress), "
        "at least webAxial."
    )
    channelWeb: ClassLimits = Field(description="Web of a channel.")
    angleBending: ClassLimits = Field(description="Angle legs b/t and d/t in bending.")
    angleAxial: tuple[Positive, Positive] = Field(
        description="Angle in axial compression, class 3: b/t and d/t, (b + d)/t."
    )
    teeStem: ClassLimits = Field(description="Stem of a tee, D/tf.")
    circularBending: ClassLimits = Field(description="Circular hollow section D/t in bending (ε²).")
    circularAxial: Positive = Field(description="Circular hollow section D/t in axial (ε²).")


class BucklingCurveRule(_Group):
    """The buckling curves of a shape family about its major and minor axes."""

    major: str
    minor: str


class ModifiedSlenderness(_Group):
    """Alpha 9 C18: the member slenderness reduction factor αc of the curves by αb (AS 4100
    6.3.3, NZS 3404 6.3.3 type): λn = (KL/r) √kf √(fy / referenceFy), αa = a1 (λn - a2) /
    (λn² - a3 λn + a4), λ = λn + αa αb, η = e1 (λ - e2) >= 0, ξ = ((λ/s)² + 1 + η) / (2 (λ/s)²),
    αc = ξ [1 - √(1 - (s / (ξ λ))²)] <= 1; kf the effective over the gross area."""

    referenceFy: Positive
    alphaA: tuple[Positive, Positive, Positive, Positive] = Field(description="(a1, a2, a3, a4).")
    eta: tuple[Positive, Positive] = Field(description="(e1, e2).")
    scale: Positive = Field(description="s.")
    alphaB: dict[str, float] = Field(description="αb by curve id (the curves' names).")


class SteelCompression(_Group):
    """Flexural buckling by buckling curves (method ``bucklingCurves``): fcd = χ fy / γm0, χ =
    1 / (φ + √(φ² - λ²)) ≤ 1, φ = 0.5 [1 + α (λ - plateau) + λ²], λ = √(fy / fcc), fcc = π² E /
    (KL/r)². Alpha 9 C18: with ``slendernessReduction`` χ is the αc of those curves instead
    (``alpha`` and ``plateau`` are then not read)."""

    method: Literal["bucklingCurves"] = "bucklingCurves"
    alpha: dict[str, Positive] = Field(
        default_factory=dict, description="Imperfection factor α by curve (a, b, c, d)."
    )
    plateau: Positive = Field(default=0.2, description="λ0 of the plateau (χ = 1 below it).")
    slendernessReduction: ModifiedSlenderness | None = None
    rolledI: list[tuple[float, Positive, str, str]] = Field(
        description="Rolled I and H sections: (h/bf above, tf up to [mm], major curve, minor "
        "curve); the first row that matches."
    )
    weldedI: list[tuple[Positive, str, str]] = Field(
        description="Welded I sections: (tf up to [mm], major curve, minor curve)."
    )
    families: dict[str, BucklingCurveRule] = Field(
        description="The other families: channel, tee, angle, rhs, chs, bar, round."
    )
    angleConstants: dict[str, tuple[float, float, float]] = Field(
        description="Single angles: (k1, k2, k3) of λe = √(k1 + k2 λvv² + k3 λφ²) by end condition."
    )
    angleCondition: str = Field(description="The end condition taken (an id of angleConstants).")
    angleCurve: str = Field(description="The buckling curve of single angles on λe.")
    # Alpha 9 C10 (BS 5950-1:2000 Annex C): the Perry factor η = a (λ - λ0) / 1000 on the
    # slenderness KL/r, read as α = a π √(E / fy) / 1000 on the relative slenderness.
    robertson: bool = Field(
        default=False,
        description="``alpha`` holds Robertson constants a: α = a π √(E / fy) / 1000.",
    )


class SteelTension(_Group):
    """Tension (method ``yieldRupture``): yielding of the gross section Ag fy / γm0, rupture of
    the net section ``ruptureShare`` An fu / γm1; single angles α An fu / γm1 by their bolts."""

    method: Literal["yieldRupture"] = "yieldRupture"
    ruptureShare: Share = Field(description="Tdn = share × An fu / γm1 (plates, whole sections).")
    angleAlpha: list[tuple[int, Share]] = Field(
        description="Single angles: (bolts up to, α) of Tdn = α An fu / γm1; above the last row "
        "its α."
    )
    angleBolts: int = Field(ge=1, description="The bolts taken in a single angle's end.")


class LtbSlenderness(_Group):
    """Alpha 9 C18: the slenderness reduction factor αs of lateral-torsional buckling."""

    share: Positive
    offset: Positive


class SteelFlexure(_Group):
    """Flexure (method ``elasticCriticalMoment``): laterally supported Md = βb Zp fy / γm0 ≤
    ``elasticCap`` Ze fy / γm0; lateral-torsional buckling Md = βb Zp χLT fy / γm0 with λLT =
    √(βb Zp fy / Mcr) and Mcr of the member."""

    method: Literal["elasticCriticalMoment"] = "elasticCriticalMoment"
    elasticCap: Positive = Field(description="Md at most this × Ze fy / γm0 (simple spans).")
    elasticCapCantilever: Positive = Field(description="The same of cantilevers.")
    alphaLT: dict[str, Positive] = Field(description="αLT: rolled, welded.")
    ltbPlateau: Positive = Field(description="No lateral-torsional buckling while λLT ≤ this.")
    ltbBase: Positive = Field(description="λ0 of φLT = 0.5 [1 + αLT (λLT - λ0) + λLT²].")
    highShare: Share = Field(description="High shear above this × Vd (the reduced Mdv).")
    # Alpha 9 C10 (BS 5950-1:2000 Annex B.2.2): ηLT = αLT (λLT - λL0) / 1000.
    robertson: bool = Field(
        default=False,
        description="``alphaLT`` holds BS type constants: α = αLT π √(E / fy) / 1000.",
    )
    # Alpha 9 C18 (AS 4100 5.6.1.1, NZS 3404 5.6.1.1): Mb = αm αs Ms <= Ms.
    slendernessReduction: LtbSlenderness | None = Field(
        default=None,
        description="Lateral-torsional buckling by αs = share [√((Ms/Mo)² + offset) - Ms/Mo] "
        "with Mo at c1 = 1 and αm = c1 (empty: χLT of λLT).",
    )


class SteelShear(_Group):
    """Shear (method ``postCritical``): Vd = Av fyw / (√3 γm0); above ``bucklingLimit`` ε the
    web's shear buckling by the simple post-critical method, Vcr = Av τb."""

    method: Literal["postCritical"] = "postCritical"
    bucklingLimit: Positive = Field(description="d/tw above this × ε (unstiffened): buckling.")
    poisson: Share = Field(description="μ of τcr,e = kv π² E / (12 (1 - μ²) (d/tw)²).")
    kvUnstiffened: Positive = Field(description="kv with transverse stiffeners at supports only.")
    kvStiffened: tuple[Positive, Positive] = Field(
        description="(a, b): kv = a + b / (c/d)² for c/d < 1, b + a / (c/d)² for c/d ≥ 1."
    )
    lambdaLimits: tuple[Positive, Positive] = Field(
        description="λw: τb = fyw/√3 up to the first, (1 - slope (λw - first)) fyw/√3 up to the "
        "second, fyw / (√3 λw²) above."
    )
    lambdaSlope: Positive = Field(description="The slope of the middle range.")
    # Alpha 9 C10 (BS 5950-1:2000 4.2.3: Pv = 0.6 py Av).
    yieldShare: Positive | None = Field(
        default=None, description="Shear yield stress = share × fy (none: fy / √3)."
    )


class SteelInteraction(_Group):
    """Combined forces (method ``sectionMember``): the section by the plastic interaction of
    plastic and compact I sections (``plastic``) or linearly; members in compression by the
    factors Ky, Kz and KLT on the equivalent uniform moments Cm."""

    method: Literal["sectionMember"] = "sectionMember"
    plastic: bool = Field(description="Plastic and compact I sections by Mnd (else linear).")
    alphaMinor: Positive = Field(description="α1 = c n, at least 1 (I sections).")
    alphaMajor: Positive = Field(description="α2 (I sections).")
    flangeShare: Share = Field(description="a = (A - 2 b tf) / A at most this.")
    majorReduction: Share = Field(description="Mndz = Mdz (1 - n) / (1 - share a) ≤ Mdz.")
    minorShare: Share = Field(description="Equation (b): this × Ky Cmy My / Mdy.")
    kCap: float = Field(ge=0, description="Ky, Kz at most 1 + cap × n (C10: 0 allowed).")
    ltbFactor: float = Field(ge=0, description="KLT = 1 - f λLT ny / (CmLT - offset).")
    ltbOffset: Positive
    cmMin: Share = Field(description="Cm at least this.")
    tensionPsi: float = Field(
        ge=0, le=1, description="ψ of Meff = M - ψ T Zec / A (T and M varying independently)."
    )


class SteelSlendernessLimits(_Group):
    compression: Positive = Field(description="KL/r of members carrying compression at most.")
    tension: Positive = Field(description="L/r of members always in tension at most.")


class BoltGradeStrength(_Group):
    fub: Positive = Field(description="Ultimate tensile stress of the bolt [MPa].")
    fyb: Positive = Field(description="Yield stress of the bolt [MPa].")
    pretensioned: bool = Field(description="May be used as a friction grip bolt.")


class SteelBoltRules(_Group):
    """Bolts (method ``partialFactorBolts``): shear fub / (√3 γmb) Anb per plane (the threads in
    every plane), bearing ``bearingFactor`` kb d t fu / γmb, tension ``tensionShare`` fub An /
    γmb ≤ fyb Asb γmb / γm0 / γmb, the interaction (V/Vd)² + (T/Td)² ≤ 1; friction grip slip
    μf ne Kh F0 / γmf with F0 = proofShare fub Anb; long joints βlj."""

    method: Literal["partialFactorBolts"] = "partialFactorBolts"
    grades: dict[str, BoltGradeStrength]
    aliases: dict[str, str] = Field(default_factory=dict, description="Other names -> grade.")
    netShare: Share = Field(description="Anb = share × the shank area (at the threads).")
    tensionShare: Share = Field(description="Tnb = share × fub An.")
    bearingFactor: Positive = Field(description="Vnpb = factor × kb d t fu.")
    bearingEnd: Positive = Field(description="kb ≤ e / (this × d0).")
    bearingPitch: tuple[Positive, Share] = Field(description="kb ≤ p / (a d0) - b.")
    proofShare: Share = Field(description="F0 = share × fub Anb.")
    slipMu: dict[str, Positive] = Field(description="μf by the connection's surface class.")
    holeKh: dict[str, Positive] = Field(description="Kh by the connection's hole type.")
    longJoint: tuple[Positive, Positive, Positive, Share] = Field(
        description="(a, b, c, least): βlj = a - b lj / d for lj > c d, at least the least."
    )


class SteelWeldRules(_Group):
    """Fillet welds (method ``throatShear``): fwd = fu / (√3 γmw) on the throat share × size."""

    method: Literal["throatShear"] = "throatShear"
    throatShare: Share
    field: bool = Field(description="Field welds (γmw field) by default.")


class SteelConnectionRules(_Group):
    """The connection strengths of the limit state method, in the shared connection checks
    (:mod:`saengine.design.steel_connections`)."""

    bolts: SteelBoltRules
    welds: SteelWeldRules
    blockShear: tuple[Share, Share] = Field(
        description="Tdb rupture term shares (net tension, net shear)."
    )
    parentCode: str = Field(
        default="",
        description="Put before a parent clause the steel table's connections.references do "
        "not map (the notes name the parent's rule).",
    )


class SteelCapacityFactorBolt(_Group):
    """Alpha 9 C18c: a bolt grade of the capacity-factor connections."""

    fuf: Positive = Field(description="The bolt's tensile strength [MPa].")
    pretensioned: bool = Field(default=False, description="May be fully tensioned (TB, TF).")


class SteelCapacityFactorJoints(_Group):
    """Alpha 9 C18c, ``steelLimitState.connections`` (method ``capacityFactorJoints``, the
    AS 4100:2020 Chapter 9 form; :mod:`saengine.design.steel.capacity_factor_joints`): bolts in
    shear ``φ shearShare fuf kr Ac`` (Ac the core area with the threads in the shear plane,
    ``coreShare`` Ao), in tension ``φ As fuf``, combined ``(V/φVf)² + (N/φNtf)² <= 1``, the ply
    in bearing ``φ bearingFactor df tp fup`` and tear-out ``φ ae tp fup``, friction
    ``φ μ nei Nti kh``, block shear on the parts' fy and fu with ``phiBlock``, fillet welds
    ``φ weldShare fuw tt kr``."""

    method: Literal["capacityFactorJoints"]
    phiBolt: Share = Field(description="φ of bolts in shear and tension.")
    shearShare: Positive = Field(description="Vf = φ share fuf kr Ac.")
    coreShare: Share = Field(description="Ac / Ao (the threads in the shear plane).")
    tensileArea: dict[int, Positive] = Field(
        default_factory=dict, description="As [mm²] by bolt diameter (0.78 Ao otherwise)."
    )
    grades: dict[str, SteelCapacityFactorBolt]
    gradeOf: dict[str, str] = Field(
        default_factory=dict, description="Other grade names taken as a grade of ``grades``."
    )
    longJoint: tuple[Positive, Positive, Positive, Positive, Share] = Field(
        description="kr: 1 up to l1 [mm], a - lj / b up to l2, the least above: (l1, l2, a, b, "
        "least)."
    )
    phiPly: Share = Field(description="φ of the ply in bearing and tear-out.")
    bearingFactor: Positive = Field(description="Vb = φ factor df tp fup.")
    phiSlip: Share
    slipMu: Positive = Field(description="μ of the faying surfaces (the code's default).")
    holeKh: dict[str, Positive] = Field(description="kh by hole type (standard, oversize, ...).")
    pretension: dict[int, Positive] = Field(description="Nti [kN] by bolt diameter.")
    phiBlock: Share
    phiWeld: Share = Field(description="φ of the fillet welds (the weld category's).")
    weldShare: Positive = Field(description="φvw = φ share fuw tt kr.")
    fuw: Positive = Field(description="The weld metal's strength [MPa].")
    throatShare: Share = Field(description="tt = share × the leg.")


class SeismicFrameRules(_Group):
    """The rules of one steel seismic frame kind (None or empty: not required)."""

    braceSlenderness: Positive | None = Field(default=None, description="KL/r of braces at most.")
    braceCompressionShare: Share | None = Field(
        default=None, description="Brace compression at most this × Pd."
    )
    tensionShare: tuple[Share, Share] | None = Field(
        default=None, description="Each brace line: its tension braces' share of the shear."
    )
    kBracing: bool = Field(default=True, description="K bracing permitted.")
    plasticMembers: list[str] = Field(
        default_factory=list, description="Member kinds whose sections must be plastic."
    )
    connectionMoment: Positive | None = Field(
        default=None, description="Beam-to-column connections designed for this × Mp (a flag)."
    )
    strongColumn: Positive | None = Field(
        default=None, description="ΣMpc ≥ this × ΣMpb at each joint."
    )
    driftAngle: Positive | None = Field(
        default=None, description="Connection rotation capacity [rad] (a flag)."
    )
    note: str = ""


class SteelSeismicRules(_Group):
    """Steel seismic frames by prescriptive member and joint rules (method
    ``prescriptiveFrames``), the columns under the amplified seismic load."""

    method: Literal["prescriptiveFrames"] = "prescriptiveFrames"
    systems: dict[str, str] = Field(description="Structural system id -> frame kind.")
    frames: dict[str, SeismicFrameRules]
    columnAmplified: bool = Field(description="Columns' axial strength under the Ω0 combinations.")
    rAbove: float = Field(ge=0, description="The rules apply when R is above this.")


class SteelLimitStateTable(TableModel):
    """Steel by limit state design with partial safety factors and buckling curves (module
    :mod:`saengine.design.steel.limit_state`)."""

    # Alpha 9 C6: the member groups below are those of the method of C9; a pack whose members
    # follow the method ``crossSectionClasses`` (``memberResistance``) needs none of them.
    partialFactors: SteelPartialFactors | None = None
    classification: SteelClassification | None = None
    compression: SteelCompression | None = None
    tension: SteelTension | None = None
    flexure: SteelFlexure | None = None
    shear: SteelShear | None = None
    interaction: SteelInteraction | None = None
    slenderness: SteelSlendernessLimits | None = None
    shearModulus: Positive | None = Field(default=None, description="G [MPa].")
    welded: bool = Field(default=False, description="Members taken as welded (else rolled).")
    nominalHollowWall: bool = Field(
        default=True, description="Hollow sections on the nominal wall (no ERW reduction)."
    )
    #: Alpha 9 C6: the members by cross-section classes 1-4 (effective widths), the buckling
    #: curves incl. a0, the lateral-torsional buckling cases and Annex A / B interaction
    #: factors (saengine.design.steel.buckling_curves).
    memberResistance: MemberResistance | None = None
    #: The connection strengths: bolts by C9's rules (``partialFactorBolts``) or (alpha 9 C6)
    #: bolts, bearing, welds and block tearing with γM2 (``partialFactors``,
    #: saengine.design.steel.joint_resistances).
    #: Alpha 9 C18c: or the capacity-factor joints (``capacityFactorJoints``, AS 4100 Ch 9).
    connections: SteelConnectionRules | SteelJointResistances | SteelCapacityFactorJoints | None = (
        None
    )
    #: The seismic frames: prescriptive rules (``prescriptiveFrames``) or (alpha 9 C6) the
    #: capacity design of dissipative frames (``dissipativeZones``,
    #: saengine.design.steel.seismic_dissipative).
    seismic: SteelSeismicRules | SteelDissipative | None = None
    #: Alpha 9 C12 (saengine.codes.steel_remainder_tables): torsion by elastic stresses, the
    #: stability bracing forces, the column side under flange forces, hollow section joints.
    torsion: SteelTorsionStresses | None = None
    bracing: SteelBracingForces | None = None
    columnSide: SteelColumnSide | None = None
    hssJoints: SteelHssChordFace | None = None
    #: Alpha 9 C10 (BS 5950-1:2000 Table 9): the design strength by thickness, per grade (the
    #: nominal fy of the material, e.g. "275"): (thickness up to [mm], py) rows; a member's fy
    #: is the row of its thickest element (flange of I and channel sections). Empty: fy.
    designStrength: dict[str, list[tuple[Positive, Positive]]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _members(self) -> SteelLimitStateTable:
        if self.memberResistance is None:
            missing = [
                k
                for k in (
                    "partialFactors", "classification", "compression", "tension", "flexure",
                    "shear", "interaction", "slenderness", "shearModulus",
                )
                if getattr(self, k) is None
            ]  # fmt: skip
            if missing:
                raise ValueError(
                    f"the limit state members need {', '.join(missing)} (or memberResistance)"
                )
        return self
