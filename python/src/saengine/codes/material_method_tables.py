"""Table models of the partial-factor methods of steel, composite, timber, masonry and
aluminium design that a pack chooses by id (alpha 9 C6).

The groups plug into the existing tables (a pack without them keeps the default pack's
methods, unchanged):

- ``steelLimitState.memberResistance`` (method ``crossSectionClasses``, a group of the limit
  state steel table of :mod:`saengine.codes.limit_state_tables`): members by cross-section classes, design resistances with γM and the
  buckling curves with their imperfection factors, lateral-torsional buckling by χLT and the
  interaction factors of the combined checks (:mod:`saengine.design.steel.buckling_curves`);
- ``steelLimitState.connections`` (``method = "partialFactors"``): bolts, bearing, welds and
  block tearing by design resistances with γM2 (:mod:`saengine.design.steel.joint_resistances`);
- ``steelStability.notional.swayImperfection``: the global sway imperfection φ = φ0 αh αm in
  place of a fixed notional coefficient (:mod:`saengine.fem.notional_loads`);
- ``steelLimitState.seismic`` (``method = "dissipativeZones"``): capacity design of dissipative steel frames by the overstrength
  factor, the ductility class's section classes and the brace slenderness limits
  (:mod:`saengine.design.steel.seismic_dissipative`);
- ``composite.partialFactors``: shear connectors by PRd with γV, the secant modulus Ecm, the
  least degree of shear connection, columns by χ of the buckling curves
  (:mod:`saengine.design.steel.composite`);
- ``timber.method = "partialFactors"`` with ``timber.limitState``: strength classes, kmod,
  γM, kdef, ksys and the member checks of limit state design
  (:mod:`saengine.design.timber.limit_state`);
- ``masonry.method = "partialFactors"`` with ``masonry.partialFactors``: fk = K fb^α fm^β,
  γM, the capacity reduction Φ and the shear strength fvk (:mod:`saengine.design.
  masonry_partial_factors`);
- the ``aluminium`` table: alloys with f0, fu, the heat-affected zone and the buckling class,
  γM1, γM2 and the member checks (:mod:`saengine.design.aluminium`).

Every number is the pack's; the method notes and VERIFY.md of the pack give each clause.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from saengine.codes.tables import Positive, Share, TableModel, _Group

# ───────────────────────────── steel members (buckling curves) ─────────────────────────────


class SteelClassLimits(_Group):
    """c/t limits of the cross-section classes 1, 2, 3, as multiples of ε = √(ref / fy)."""

    epsilonReference: Positive = Field(description="ε = √(this / fy).")
    internalCompression: tuple[Positive, Positive, Positive] = Field(
        description="Internal parts in compression: c/t <= [class 1, 2, 3] ε."
    )
    internalBending: tuple[Positive, Positive, Positive] = Field(
        description="Internal parts in bending: c/t <= [class 1, 2, 3] ε."
    )
    webClass1: tuple[Positive, Positive, Positive, Positive] = Field(
        description="Bending and compression, class 1: α > 0.5: a ε / (b α - c), else d ε / α."
    )
    webClass2: tuple[Positive, Positive, Positive, Positive] = Field(
        description="Bending and compression, class 2 (as webClass1)."
    )
    webClass3: tuple[Positive, Positive, Positive, Positive] = Field(
        description="Bending and compression, class 3: ψ > -1: a ε / (b + c ψ), else "
        "d ε (1 - ψ) √(-ψ)."
    )
    outstandCompression: tuple[Positive, Positive, Positive] = Field(
        description="Outstand flanges in compression: c/t <= [class 1, 2, 3] ε."
    )
    tubes: tuple[Positive, Positive, Positive] = Field(
        description="Tubular sections: d/t <= [class 1, 2, 3] ε²."
    )
    angle: tuple[Positive, Positive] = Field(
        description="Angles, class 3: h/t <= a ε and (b + h) / (2 t) <= b ε."
    )


class SteelPlateBuckling(_Group):
    """Effective widths of class 4 plates: ρ by the plate slenderness λ̄p = (b/t) / (factor ε
    √kσ)."""

    plateFactor: Positive = Field(description="λ̄p = (b/t) / (this ε √kσ).")
    internal: tuple[Positive, Positive] = Field(
        description="Internal elements: ρ = (λ̄p - a (b + ψ)) / λ̄p² <= 1: [a, b]."
    )
    internalLimit: tuple[Positive, Positive] = Field(
        description="ρ = 1 while λ̄p <= a + √(b - c ψ): [a, b] with c = internal[0]."
    )
    outstand: Positive = Field(description="Outstands: ρ = (λ̄p - this) / λ̄p² <= 1.")
    outstandLimit: Positive = Field(description="ρ = 1 while λ̄p <= this.")
    kSigmaUniform: Positive = Field(description="kσ of an internal element, ψ = 1.")
    kSigmaBending: Positive = Field(description="kσ of an internal element, ψ = -1.")
    kSigmaPositive: tuple[Positive, Positive] = Field(
        description="kσ = a / (b + ψ) for 1 > ψ > 0: [a, b]."
    )
    kSigmaNegative: tuple[Positive, Positive, Positive] = Field(
        description="kσ = a - b ψ + c ψ² for 0 > ψ > -1: [a, b, c]."
    )
    kSigmaOutstand: Positive = Field(description="kσ of an outstand in uniform compression.")
    kSigmaOutstandTip: Positive = Field(
        description="kσ of an outstand, the tip in compression and the root at zero stress."
    )


class SteelCurveRow(_Group):
    """One row of the selection of buckling curves: the shape family and its conditions, and
    the curve about each axis (``y`` the major, ``z`` the minor), for the high-strength steels
    from ``highFrom`` their own curves."""

    family: Literal[
        "rolledI", "weldedI", "hotHollow", "coldHollow", "channel", "tee", "angle", "solid"
    ]
    depthWidthAbove: float | None = Field(default=None, description="h/b above this ...")
    depthWidthMax: float | None = Field(default=None, description="... or at most this.")
    flangeMax: float | None = Field(default=None, description="tf at most this [mm] ...")
    flangeAbove: float | None = Field(default=None, description="... or above this [mm].")
    y: str = Field(description="Curve of buckling about the major axis.")
    z: str = Field(description="Curve of buckling about the minor axis.")
    yHigh: str | None = Field(default=None, description="High-strength steel, major axis.")
    zHigh: str | None = Field(default=None, description="High-strength steel, minor axis.")


class SteelLtbCurveRow(_Group):
    """A lateral-torsional buckling curve by family and h/b."""

    family: Literal["rolledI", "weldedI", "other"]
    depthWidthMax: float | None = Field(default=None, description="h/b at most this.")
    curve: str


class SteelLateralTorsional(_Group):
    """Lateral-torsional buckling: the general case or the rolled (and equivalent welded) case,
    Mcr by the C1 formula (load at the shear centre, k = kw = 1, C1 from the moment diagram of
    the segment), and the factor f of the moment distribution."""

    method: Literal["general", "rolled"] = Field(
        description="``general``: χLT by the curves of the general case; ``rolled``: with "
        "λ̄LT,0 and β."
    )
    general: list[SteelLtbCurveRow] = Field(min_length=1)
    rolled: list[SteelLtbCurveRow] = Field(min_length=1)
    plateauGeneral: Positive = Field(description="λ̄LT,0 of the general case.")
    plateauRolled: Positive = Field(description="λ̄LT,0 of the rolled case.")
    beta: Positive = Field(description="β of the rolled case.")
    c1Max: Positive = Field(description="C1 from the moment diagram at most this.")
    modification: Literal["none", "inverseRootC1"] = Field(
        default="none",
        description="f of χLT,mod: ``none`` (f = 1), ``inverseRootC1`` (kc = 1 / √C1).",
    )
    fA: Positive = Field(default=0.5, description="f = 1 - a (1 - kc) [1 - 2 (λ̄LT - b)²]: a.")
    fB: Positive = Field(default=0.8, description="... b.")


class SteelInteractionB(_Group):
    """Annex B: the interaction factors kyy, kyz, kzy, kzz by the method's alternative 2."""

    cmMin: Positive = Field(description="Cm at least this.")
    plasticYY: tuple[Positive, Positive] = Field(
        description="Class 1, 2: kyy = Cmy (1 + (λ̄y - a) nY) <= Cmy (1 + b nY): [a, b]."
    )
    plasticZZ: tuple[Positive, Positive, Positive] = Field(
        description="Class 1, 2 I-sections: kzz = Cmz (1 + (a λ̄z - b) nZ) <= Cmz (1 + c nZ)."
    )
    plasticYZ: Positive = Field(description="Class 1, 2: kyz = this kzz.")
    plasticZY: Positive = Field(description="Class 1, 2, no torsional deformation: kzy = this kyy.")
    plasticZYTorsional: tuple[Positive, Positive] = Field(
        description="Class 1, 2, torsional deformation: kzy = 1 - a λ̄z nZ / (CmLT - b) >= "
        "1 - a nZ / (CmLT - b): [a, b] (λ̄z >= 0.4)."
    )
    elasticYY: tuple[Positive, Positive] = Field(
        description="Class 3, 4: kyy = Cmy (1 + a λ̄y nY) <= Cmy (1 + b nY)."
    )
    elasticYZ: Positive = Field(description="Class 3, 4: kyz = this kzz.")
    elasticZY: Positive = Field(description="Class 3, 4, no torsional deformation: kzy = this kyy.")
    elasticZYTorsional: tuple[Positive, Positive] = Field(
        description="Class 3, 4, torsional deformation: kzy = 1 - a λ̄z nZ / (CmLT - b) >= ..."
    )


class SteelInteractionA(_Group):
    """Annex A: the interaction factors by μ, w, Cij and the equivalent moment factors Cmi,0."""

    cm0: tuple[float, float, float, float] = Field(
        description="Cmi,0 = a + b ψ + c (ψ - d) NEd / Ncr,i (a linear moment diagram)."
    )
    wMax: Positive = Field(description="wy, wz = Wpl / Wel at most this.")
    elasticShare: Positive = Field(description="0.6 √(wz/wy) of kyz and kzy (class 1, 2).")
    cyy: tuple[Positive, Positive] = Field(description="Cyy: 2 - (a / w) Cm² λ̄max - (b / w) ...")
    cyz: tuple[Positive, Positive] = Field(description="Cyz: 2 - a Cm² λ̄max² / w^b.")
    bLT: Positive = Field(description="bLT = this aLT λ̄0² ...")
    cLT: tuple[Positive, Positive] = Field(description="cLT = a aLT λ̄0² / (b + λ̄z⁴) ...")
    dLT: tuple[Positive, Positive] = Field(description="dLT = a aLT λ̄0 / (b + λ̄z⁴) ...")
    eLT: tuple[Positive, Positive] = Field(description="eLT = a aLT λ̄0 / (b + λ̄z⁴) ...")
    lateralLimit: Positive = Field(
        description="λ̄0 <= this √C1 [(1 - NEd/Ncr,z)(1 - NEd/Ncr,TF)]^(1/4): no LTB."
    )


class SteelInteraction(_Group):
    method: Literal["annexB", "annexA"] = Field(
        description="The interaction factors: ``annexB`` (alternative method 2) or ``annexA`` "
        "(alternative method 1)."
    )
    annexB: SteelInteractionB
    annexA: SteelInteractionA | None = None


class SteelShearResistance(_Group):
    """Plastic shear resistance and shear buckling of webs."""

    eta: Positive = Field(description="η of the shear area and of the shear buckling limit.")
    bucklingLimit: Positive = Field(description="Webs with hw/tw > this ε / η buckle in shear.")
    plateFactor: Positive = Field(description="λ̄w = hw / (this t ε √kτ).")
    kTau: Positive = Field(description="kτ of a web without intermediate stiffeners.")
    chiW: Positive = Field(description="χw = this / λ̄w (non-rigid end post) ...")
    reductionFrom: Share = Field(description="VEd above this × Vpl,Rd reduces the moment.")


class SteelGlobalAnalysis(_Group):
    """When the global analysis must be of second order: αcr below ``firstOrder``; below
    ``amplified`` the sway amplification of a first-order analysis is not permitted."""

    firstOrder: Positive = Field(description="αcr >= this: first-order analysis suffices.")
    amplified: Positive = Field(description="αcr >= this: amplified first-order analysis.")


class SteelMemberResistance(_Group):
    """Alpha 9 C6, ``steelLimitState.memberResistance`` (method ``crossSectionClasses``): the
    member checks by design resistances (R / γM), cross-section classes 1-4, buckling curves and
    interaction factors."""

    method: Literal["crossSectionClasses"] = "crossSectionClasses"
    gammaM0: Positive = Field(description="Resistance of cross-sections.")
    gammaM1: Positive = Field(description="Resistance of members to instability.")
    gammaM2: Positive = Field(description="Resistance of cross-sections in tension to fracture.")
    modulus: Positive = Field(description="E [MPa] of the calculations.")
    shearModulus: Positive = Field(description="G [MPa] of the calculations.")
    netTension: Share = Field(description="Nu,Rd = this × Anet fu / γM2.")
    thickPlates: list[tuple[Positive, Positive, Positive]] = Field(
        default_factory=list,
        description="[nominal fy, thickness above which [mm], fy there [MPa]] (the lower yield "
        "strength of thick plates).",
    )
    classes: SteelClassLimits
    plates: SteelPlateBuckling
    imperfection: dict[str, Positive] = Field(
        min_length=1, description="α of the buckling curves by name."
    )
    plateau: Positive = Field(description="Φ = 0.5 [1 + α (λ̄ - this) + λ̄²].")
    highFrom: Positive = Field(description="fy from which the high-strength curves apply [MPa].")
    curves: list[SteelCurveRow] = Field(min_length=1)
    lateralTorsional: SteelLateralTorsional
    interaction: SteelInteraction
    shear: SteelShearResistance
    globalAnalysis: SteelGlobalAnalysis


# ───────────────────────────── steel joints (partial factors) ─────────────────────────────


class SteelJointBolt(_Group):
    fyb: Positive = Field(description="Nominal yield strength [MPa].")
    fub: Positive = Field(description="Nominal ultimate tensile strength [MPa].")
    alphaV: Share = Field(description="αv of the shear resistance (shear plane through threads).")


class SteelJointBearing(_Group):
    """Fb,Rd = k1 αb fu d t / γM2."""

    endDistance: Positive = Field(description="αd = e1 / (this d0) of end bolts ...")
    innerPitch: Positive = Field(description="... = p1 / (this d0) - innerOffset of inner bolts.")
    innerOffset: Positive
    k1Max: Positive = Field(description="k1 at most this (edge distance e2 >= the limit).")


class SteelJointWeld(_Group):
    method: Literal["simplified", "directional"] = Field(
        description="``simplified``: fvw,d = fu / (√3 βw γM2) on the throat; ``directional``: "
        "the stresses on the throat checked against fu / (βw γM2) and 0.9 fu / γM2."
    )
    betaW: list[tuple[Positive, Share]] = Field(
        min_length=1, description="[fu of the parent up to [MPa], βw] in ascending order."
    )
    perpendicularShare: Share = Field(description="σ⊥ <= this fu / γM2 (directional).")


class SteelJointSlip(_Group):
    """Fs,Rd = ks n μ (Fp,C - reduction Ft,Ed) / γM3, Fp,C = preload fub As."""

    preload: Share = Field(description="Fp,C = this fub As.")
    mu: dict[str, Positive] = Field(description="μ by the type's surface class.")
    ks: dict[str, Positive] = Field(description="ks by the type's hole type.")
    gammaM3: dict[str, Positive] = Field(description="γM3 by 'strength', 'serviceability'.")
    tensionReduction: Positive = Field(description="Fp,C less this × Ft,Ed under tension.")


class SteelJointResistances(_Group):
    """Alpha 9 C6, ``steelLimitState.connections``: bolts, bearing, welds and block tearing by design
    resistances with γM2 (``method`` its id)."""

    method: Literal["partialFactors"] = "partialFactors"
    gammaM0: Positive
    gammaM2: Positive
    bolts: dict[str, SteelJointBolt] = Field(min_length=1, description="Bolt classes.")
    gradeOf: dict[str, str] = Field(
        default_factory=dict, description="Other grade names taken as a bolt class of ``bolts``."
    )
    tensileArea: dict[int, Positive] = Field(description="As [mm²] by bolt diameter [mm].")
    k2: Share = Field(description="Ft,Rd = k2 fub As / γM2.")
    combinedTension: Positive = Field(description="Fv/Fv,Rd + Ft / (this Ft,Rd) <= 1.")
    bearing: SteelJointBearing
    weld: SteelJointWeld
    blockShear: Positive = Field(description="Veff = fu Ant / γM2 + fy Anv / (√3 γM0) × this.")
    slip: SteelJointSlip | None = None


# ───────────────────────────── sway imperfection (global analysis) ─────────────────────────


class SwayImperfection(_Group):
    """φ = φ0 αh αm: αh = 2 / √h within [heightMin, 1], αm = √(0.5 (1 + 1/m)) (m taken as 1:
    the conservative value, SAEngine practice). The equivalent horizontal forces φ × the
    vertical loads in every combination."""

    phi0: Positive = Field(description="Basic value φ0.")
    heightFactor: Positive = Field(description="αh = this / √h, h the height [m] ...")
    heightMin: Share = Field(description="... at least this ...")
    heightMax: Positive = Field(description="... and at most this.")
    everyCombination: bool = Field(
        default=True, description="Applied in every combination (else gravity-only)."
    )
    clause: str = ""


# ───────────────────────────── seismic: dissipative steel frames ─────────────────────────────


class DissipativeFrame(_Group):
    """One frame kind: the class of the dissipative zones by ductility class, the brace
    slenderness, the overstrength of the non-dissipative members."""

    kind: Literal["moment", "concentric", "eccentric"]
    ductility: Literal["DCL", "DCM", "DCH"]
    classMax: int = Field(ge=1, le=3, description="Least section class of dissipative members.")
    braceSlenderness: tuple[float, float] | None = Field(
        default=None, description="[least, largest] λ̄ of diagonal braces (X bracing)."
    )
    linkShear: Positive | None = Field(
        default=None, description="Short links: e <= this Mp,link / Vp,link."
    )


class SteelDissipative(_Group):
    """Alpha 9 C6, ``steelLimitState.seismic``: capacity design of dissipative steel frames by
    the overstrength ratio Ω of the dissipative members and γov."""

    method: Literal["dissipativeZones"] = "dissipativeZones"
    gammaOv: Positive = Field(description="Material overstrength factor γov.")
    capacityFactor: Positive = Field(
        description="Non-dissipative members: NEd = NEd,G + this γov Ω NEd,E (and M, V)."
    )
    beamShear: Share = Field(description="MRF beams: VEd / Vpl,Rd at most this.")
    beamAxial: Share = Field(description="MRF beams: NEd / Npl,Rd at most this.")
    columnShear: Share = Field(description="MRF columns: VEd / Vpl,Rd at most this.")
    strongColumn: Positive = Field(description="ΣMRc >= this ΣMRb at the joints.")
    braceOmegaSpread: Positive = Field(
        description="Braces: Ωmax at most this × Ωmin (homogeneous dissipative behaviour)."
    )
    systems: dict[str, DissipativeFrame] = Field(
        min_length=1, description="Structural system id -> its frame kind and ductility class."
    )
    clauses: dict[str, str] = Field(default_factory=dict)


# ───────────────────────────── composite members (EN-type) ─────────────────────────────


class CompositePartialFactors(_Group):
    """Alpha 9 C6, ``composite.partialFactors``: the partial factors of composite members and
    the methods of the shear connectors, the concrete modulus, the degree of connection and
    the columns' buckling."""

    method: Literal["partialFactors"] = "partialFactors"
    gammaA: Positive = Field(description="Structural steel (γM0).")
    gammaC: Positive
    gammaS: Positive
    gammaV: Positive
    studSteel: Share = Field(description="PRd = this fu π d²/4 / γV ...")
    studConcrete: Positive = Field(description="... or this α d² √(fck Ecm) / γV.")
    studAspect: tuple[Positive, Positive] = Field(
        description="α = 0.2 (hsc/d + 1) for a <= hsc/d <= b, else 1: [a, b]."
    )
    studFuMax: Positive = Field(description="fu of the stud at most this [MPa].")
    transverseRibs: tuple[Positive, Positive] = Field(
        description="kt = a / √nr (b0/hp) (hsc/hp - 1), a = [one stud, two studs] ..."
    )
    transverseMax: tuple[Share, Share] = Field(description="... kt at most [nr = 1, nr = 2].")
    parallelRibs: Positive = Field(description="kl = this (b0/hp)(hsc/hp - 1) <= 1.")
    modulus: tuple[Positive, Positive, Positive] = Field(
        description="Ecm = a (fcm / b)^c [MPa], fcm = fck + increment."
    )
    fcmIncrement: Positive
    minimumConnection: tuple[Positive, Positive, Positive, Share] = Field(
        description="η >= 1 - (a / fy)(b - c Le), at least d (equal flanges, Le <= 25 m)."
    )
    columnCurves: dict[str, str] = Field(
        description="Buckling curve by column: encasedMajor, encasedMinor, filled."
    )
    imperfection: dict[str, Positive] = Field(
        description="Member imperfection e0 = L / this by column (encasedMajor, encasedMinor, "
        "filled)."
    )
    secondOrderStiffness: tuple[Positive, Positive] = Field(
        description="(EI)eff,II = a (Ea Ia + Es Is + b Ecm Ic): [a, b]."
    )
    beta: tuple[Positive, Positive, Positive] = Field(
        description="β of the end moments = a + b ψ >= c (the imperfection's β = 1)."
    )
    alphaM: list[tuple[Positive, Share]] = Field(
        min_length=1, description="[fy up to [MPa], αM] of MEd <= αM μd Mpl,Rd."
    )


# ───────────────────────────── timber (limit state design) ─────────────────────────────


class TimberStrengthClass(_Group):
    """Characteristic values of a strength class [MPa; E and G in GPa; kg/m³]."""

    fmk: Positive
    ft0k: Positive
    ft90k: Positive
    fc0k: Positive
    fc90k: Positive
    fvk: Positive
    E0mean: Positive
    E005: Positive
    Gmean: Positive
    rhok: Positive
    kind: Literal["solid", "glulam"]


class TimberLimitState(_Group):
    """Alpha 9 C6, ``timber.method = "partialFactors"``: limit state design of timber members
    by the strength classes, kmod by service class and load duration, γM, kdef and the member
    checks (bending, shear, axial, combined, buckling, lateral-torsional stability)."""

    classes: dict[str, TimberStrengthClass] = Field(min_length=1)
    gammaM: dict[str, Positive] = Field(description="γM by kind (solid, glulam).")
    kmod: dict[str, dict[str, Positive]] = Field(
        description="kmod by kind -> service class (1, 2, 3) and load duration -> value: keys "
        "'<service class>.<duration>'."
    )
    kdef: dict[str, dict[str, Positive]] = Field(description="kdef by kind -> service class.")
    durations: dict[str, str] = Field(
        description="Analysis case code -> load-duration class (permanent, long, medium, short, "
        "instantaneous); a case not listed: permanent (the conservative class)."
    )
    durationOrder: list[str] = Field(
        min_length=1, description="Load-duration classes from the longest to the shortest."
    )
    defaultClass: str = Field(description="Strength class when the material names none.")
    defaultServiceClass: Literal["1", "2", "3"] = "1"
    kcr: dict[str, Share] = Field(description="kcr of the shear width by kind.")
    depthFactor: dict[str, tuple[Positive, Positive, Positive]] = Field(
        description="kh = min((reference / h)^exponent, max) by kind: [reference, exponent, max]."
    )
    km: Share = Field(description="km of rectangular sections (biaxial bending).")
    betaC: dict[str, Share] = Field(description="βc of the straightness by kind.")
    relativeSlenderness: Share = Field(description="λrel,m <= this: kcrit = 1 ...")
    lateralTorsional: tuple[Positive, Positive, Positive] = Field(
        description="kcrit = a - b λrel,m up to c, then 1 / λrel,m²."
    )
    columnPlateau: Share = Field(description="λrel <= this: no buckling reduction.")
    criticalBending: Positive = Field(
        description="σm,crit = this b² E0,05 / (h lef) (rectangular softwood)."
    )
    clauses: dict[str, str] = Field(default_factory=dict)


# ───────────────────────────── masonry (partial factors) ─────────────────────────────


class MasonryUnitGroup(_Group):
    """K, α, β of fk = K fb^α fm^β for one unit group and mortar kind."""

    K: Positive
    alpha: Positive
    beta: Positive


class MasonryPartialFactors(_Group):
    """Alpha 9 C6, ``masonry.method = "partialFactors"``: unreinforced (and reinforced) walls by
    the characteristic compressive strength fk, γM, the capacity reduction Φ at the top,
    bottom and mid-height and the shear strength fvk."""

    gammaM: Positive = Field(description="γM of masonry (class of execution as the pack sets).")
    gammaS: Positive = Field(description="γS of reinforcing steel.")
    unitGroups: dict[str, MasonryUnitGroup] = Field(
        description="K, α, β by '<unit kind>.<group>' (clay.1, concrete.2 ...)."
    )
    groupOf: dict[str, str] = Field(
        description="Unit group by the material's units (solid, hollow): SAEngine practice."
    )
    defaultMortar: Positive = Field(
        description="fm [MPa] when the material's mortar grade is not known (the safe side)."
    )
    shapeFactor: Positive = Field(
        default=1.0, description="fb = this × the unit's mean compressive strength (δ)."
    )
    fbMax: Positive = Field(description="fb taken at most this [MPa] ...")
    fmMax: Positive = Field(description="... fm at most this, and at most fmShare fb.")
    fmShare: Positive
    fvk0: dict[str, list[tuple[float, Positive]]] = Field(
        description="fvk0 [MPa] by unit kind: [[mortar fm from [MPa], fvk0], ...] ascending."
    )
    shearCompression: Share = Field(description="fvk = fvk0 + this σd ...")
    shearMax: Share = Field(description="... <= this fb.")
    eccentricityMin: Share = Field(description="ei >= this t.")
    heightEccentricity: Positive = Field(description="einit = hef / this.")
    endReduction: Positive = Field(description="Φi = 1 - this ei / t.")
    slendernessMax: Positive = Field(description="hef / tef at most this.")
    restraint: dict[str, Positive] = Field(
        description="ρn of the effective height: 'braced' (restrained top and bottom), "
        "'unbraced' (a free top)."
    )
    creep: Positive = Field(description="φ∞ of ek = 0.002 φ∞ (hef/tef) √(t em).")
    creepFrom: Positive = Field(description="ek = 0 while hef/tef <= this.")
    elasticModulus: Positive = Field(description="E = this fk.")
    stressBlock: tuple[Positive, Positive] = Field(
        description="Reinforced: the rectangular block fd over a x: [a, ε_mu (per mille)]."
    )
    clauses: dict[str, str] = Field(default_factory=dict)


# ───────────────────────────── aluminium (EN 1999 type) ─────────────────────────────


class AluminiumAlloy(_Group):
    """One alloy and temper: f0, fu by product and thickness, the heat-affected zone and the
    buckling class."""

    label: str
    f0: Positive = Field(description="0.2 % proof strength [MPa].")
    fu: Positive = Field(description="Ultimate tensile strength [MPa].")
    thicknessMax: Positive | None = Field(default=None, description="Up to this thickness [mm].")
    rhoHazProof: Share = Field(description="ρo,haz = fo,haz / fo.")
    rhoHazUltimate: Share = Field(description="ρu,haz = fu,haz / fu.")
    bucklingClass: Literal["A", "B"]


class AluminiumClassLimits(_Group):
    """β/ε limits [class 1, class 2, class 3] by element and buckling class (ε = √(ref/f0))."""

    epsilonReference: Positive
    internal: dict[str, tuple[Positive, Positive, Positive]]
    outstand: dict[str, tuple[Positive, Positive, Positive]]


class AluminiumLocalBuckling(_Group):
    """ρc = C1 / (β/ε) - C2 / (β/ε)² of class 4 elements by element and buckling class."""

    internal: dict[str, tuple[Positive, Positive]]
    outstand: dict[str, tuple[Positive, Positive]]


class AluminiumBuckling(_Group):
    """α and λ̄0 of flexural buckling by buckling class; of lateral-torsional buckling by the
    section class."""

    flexural: dict[str, tuple[Positive, float]]
    lateralTorsional: dict[str, tuple[Positive, float]]
    interaction: tuple[Positive, Positive, Positive] = Field(
        description="Exponents ξ of the combined checks: [axial (major), axial (minor), "
        "bending] (the conservative values)."
    )


class AluminiumTable(TableModel):
    """Alpha 9 C6: aluminium members (EN 1999 type): the alloys, γM1, γM2, the cross-section
    classes, the local and flexural buckling and the combined checks."""

    method: Literal["partialFactors"] = "partialFactors"
    gammaM1: Positive
    gammaM2: Positive
    modulus: Positive = Field(description="E [MPa].")
    shearModulus: Positive = Field(description="G [MPa].")
    density: Positive = Field(description="[kg/m³].")
    alloys: dict[str, AluminiumAlloy] = Field(min_length=1)
    classes: AluminiumClassLimits
    localBuckling: AluminiumLocalBuckling
    buckling: AluminiumBuckling
    netTension: Share = Field(description="Nu,Rd = this Anet fu / γM2.")
    shearSlenderness: Positive = Field(description="hw/tw <= this ε: no shear buckling.")
    clauses: dict[str, str] = Field(default_factory=dict)
