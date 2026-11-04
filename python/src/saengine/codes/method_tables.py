"""Table models of the concrete and geotechnical design methods a pack chooses by id.

``concreteMethods`` holds the values of the partial-factor design of reinforced concrete
(design strengths fcd = αcc fck / γc and fyd = fyk / γs, the stress block by strength class,
the variable strut inclination shear method, torsion by the thin-walled section, punching on
a control perimeter, the stress, crack width and span/depth checks, cover by exposure and
structural class, anchorage and laps by the design bond stress, member steel limits) and the
curvature-ductility detailing of earthquake-resistant members by ductility class. A pack
without the table keeps the strength design with φ (``materials``, ``factors``,
``concrete``): the default pack's results do not change.

``geotechnicalMethods`` holds the partial factor sets of geotechnical design (actions A,
soil parameters M, resistances R), the design approaches that combine them, the bearing
resistance by the factored general equation, sliding, and the correlation factors ξ of pile
resistance from static load tests and ground tests.

The methods are in :mod:`saengine.design.design_strength`,
:mod:`saengine.design.strut_shear`, :mod:`saengine.design.perimeter_punching`,
:mod:`saengine.design.crack_control`, :mod:`saengine.design.bar_rules`,
:mod:`saengine.design.curvature_ductility` and
:mod:`saengine.substructure.limit_state_geotechnics`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from saengine.codes.tables import Positive, Share, TableModel, WallShearAmplification, _Group

# ───────────────────────────── concreteMethods ─────────────────────────────


class PowerRelation(_Group):
    """A strength-class relation: ``base`` up to ``highFrom`` MPa, above it
    ``highBase + highCoefficient · term^highExponent`` (the term set by the method)."""

    base: float
    highBase: float | None = None
    highCoefficient: float = 0.0
    highExponent: float = 1.0
    #: The reference of the term ((top - fck)/100, (fck - highFrom), ...): its use is the method's.
    top: float | None = None
    divisor: float | None = None
    # Alpha 9 C23 (HK CoP Concrete 2013 6.1.2.4: 0.9 x up to C45, 0.8 x to C70, 0.72 x to
    # C100): the value by strength band in place of base and the high relation.
    steps: list[tuple[Positive, float]] | None = Field(
        default=None,
        description="(fck up to [MPa], value) bands: the value of the first band holding fck, "
        "the last band's above; empty: base and the high relation.",
    )


class StrengthRelations(_Group):
    """Coefficients of the relations of concrete properties to fck (method
    ``strengthClassRelations``); strains in per mille."""

    highFrom: Positive = Field(
        description="fck [MPa] above which the high-strength relations apply."
    )
    fcmIncrement: float = Field(ge=0, description="fcm = fck + increment [MPa].")
    fctmCoefficient: Positive = Field(
        description="fctm = coefficient fck^exponent (fck <= highFrom)."
    )
    fctmExponent: Positive
    fctmHighCoefficient: Positive = Field(description="fctm = c ln(1 + fcm / divisor) above.")
    fctmHighDivisor: Positive
    fctkShares: tuple[Positive, Positive] = Field(description="fctk,0.05 and fctk,0.95 / fctm.")
    ecmCoefficient: Positive = Field(description="Ecm = c (fcm / divisor)^exponent [MPa].")
    ecmDivisor: Positive
    ecmExponent: Positive
    # Alpha 9 C10 (BS 8110-2 7.2: Ec = 20 + 0.2 fcu GPa): Ecm = offset + c (fcm / divisor)^e.
    ecmOffset: float = Field(default=0.0, ge=0, description="Ecm = offset + ... [MPa].")
    epsC2: PowerRelation
    epsCu2: PowerRelation
    n: PowerRelation
    epsC3: PowerRelation
    epsCu3: PowerRelation
    eta: PowerRelation
    lam: PowerRelation = Field(alias="lambda")


class UltimateRules(_Group):
    """Flexure and axial force by design strengths (method ``partialFactors``)."""

    method: Literal["partialFactors"] = "partialFactors"
    # Alpha 9 C25 (SP 63.13330.2018 6.1.20-6.1.22, 8.1.20-8.1.30: the nonlinear deformation
    # model): "bilinear" (fcd from εc3 to εcu3, linear below) and "trilinear" (0.6 fcd at
    # 0.6 fcd / Ecm, fcd from εc2 to εcu2) diagrams, integrated over the section's mesh.
    stressBlock: Literal["rectangular", "parabolaRectangle", "bilinear", "trilinear"] = (
        "rectangular"
    )
    gammaC: Positive
    gammaS: Positive
    gammaCAccidental: Positive | None = None
    gammaSAccidental: Positive | None = None
    alphaCC: Share
    alphaCT: Share
    # Alpha 9 C15: a National Annex's αcc for shear and the other phenomena (UK NA to BS EN
    # 1992-1-1 3.1.6(1): 0.85 flexure and axial, 1.0 others); None: alphaCC everywhere.
    alphaCCShear: Share | None = Field(
        default=None, description="αcc of fcd in shear, torsion and punching (none: alphaCC)."
    )
    steelE: Positive = Field(description="Es [MPa].")
    strengthClasses: list[tuple[Positive, Positive]] = Field(
        description="(fck, fck,cube) [MPa] of the strength classes."
    )
    relations: StrengthRelations
    eccentricityDivisor: Positive = Field(description="e0 = h / divisor, at least eccentricityMin.")
    eccentricityMin: float = Field(ge=0, description="[mm] (C10: 0 allowed)")
    pureCompressionStrain: Literal["epsC2", "epsC3"] = Field(
        default="epsC2", description="The strain limit of a section under axial compression."
    )
    #: Alpha 9 C5b: (k1, k2) of the redistribution rule δ >= k1 + k2 xu/d; with δ = 1 the
    #: limit xu/d <= (1 - k1)/k2 of slabs and stairs designed from the elastic analysis.
    neutralAxisLimit: tuple[Share, Positive] | None = None
    # Alpha 9 C23 (HK CoP Concrete 2013 6.1.2.4(c): x <= 0.5 d up to C45, 0.4 d to C70, 0.33 d
    # to C100): the limit by strength band, where the grade is known, before neutralAxisLimit.
    neutralAxisSteps: list[tuple[Positive, Share]] | None = Field(
        default=None,
        description="(fck up to [MPa], xu/d at most) bands, the last band's above; empty: "
        "neutralAxisLimit.",
    )
    # C8 (IS 456): grade names, the axial cap by shares of fck and fy, e0 with the length.
    gradePrefix: str | None = Field(
        default=None, description="Grades named prefix + fck ('M25'); none: 'C fck/fck,cube'."
    )
    # Alpha 9 C25 (SP 63.13330.2018 6.1.4: the class B by the cube strength).
    cubePrefix: str | None = Field(
        default=None,
        description="Classes named prefix + fck,cube ('B25') where gradePrefix is not given; "
        "none: 'C fck/fck,cube'.",
    )
    axialShares: tuple[Positive, Positive] | None = Field(
        default=None,
        description="NRd = a fck Ac + b fy As in place of the stress block's (none: that).",
    )
    eccentricityLengthDivisor: Positive | None = Field(
        default=None, description="e0 = l / this + h / eccentricityDivisor (none: h only)."
    )
    # Alpha 9 C10 (BS 8110-1 3.8.2.4: emin = 0.05 h, at most 20 mm).
    eccentricityMax: Positive | None = Field(
        default=None, description="e0 at most this [mm] (none: no cap)."
    )
    # Alpha 9 C20b (GB 50010 Table 4.2.3-1 type: the design yield strength tabulated by bar
    # grade, HRB400 360 MPa, in place of fyk / γs).
    designYields: list[tuple[Positive, Positive]] | None = Field(
        default=None,
        description="(fyk [MPa], fy design [MPa]) by bar grade: fyd of a bar of that fyk; "
        "other grades fyk / γs (none: fyk / γs for every grade).",
    )
    axialYieldShare: Positive | None = Field(
        default=None,
        description="The axial cap's steel term = this × fyd (the design yield by grade) in "
        "place of axialShares[1] × fyk (none: axialShares).",
    )
    # Alpha 9 C25 (SP 63.13330.2018 Tables 6.7, 6.8, 6.11: Rb, Rbt and Eb tabulated by the
    # class, rounded in the code, in place of αcc fck / γc, αct fctk,0.05 / γc and the Ecm fit).
    designStrengths: list[tuple[Positive, Positive, Positive, Positive]] | None = Field(
        default=None,
        description="(fck, fcd, fctd, Ecm) [MPa] by strength class: fcd = alphaCC × this fcd, "
        "fctd = alphaCT × this fctd and Ecm of a concrete of that fck; other grades the "
        "relations (none: the relations for every grade).",
    )


class StrutShearRules(_Group):
    """Shear by the variable strut inclination method (method ``variableStrut``)."""

    method: Literal["variableStrut"] = "variableStrut"
    crdcCoefficient: Positive = Field(description="CRd,c = coefficient / γc.")
    k1: Positive = Field(description="k1 of the axial stress σcp.")
    sizeReference: Positive = Field(description="k = 1 + √(reference / d) [mm].")
    sizeMax: Positive = Field(description="k at most.")
    rhoLMax: Share = Field(description="ρl at most.")
    vminCoefficient: Positive = Field(description="vmin = c k^1.5 √fck.")
    sigmaCpShare: Share = Field(description="σcp at most this × fcd.")
    cotTheta: tuple[Positive, Positive] = Field(description="Least and largest cot θ.")
    nuCoefficient: Positive = Field(description="ν1 = c (1 - fck / divisor).")
    nuDivisor: Positive
    # Alpha 9 C15: a National Annex's cap of ν1 (DIN EN 1992-1-1/NA: ν1 = 0.75 ν2, ν2 <= 1).
    nuMax: Share | None = Field(default=None, description="ν1 at most (none: no cap).")
    alphaCw: Positive
    leverArmShare: Share = Field(description="z = share × d.")
    rhoWMinCoefficient: Positive = Field(description="ρw,min = c √fck / fyk.")
    spacingShare: Share = Field(description="sl,max = share × d (vertical links).")
    legSpacingShare: Share = Field(description="st,max = share × d, at most legSpacingMax.")
    legSpacingMax: Positive = Field(description="[mm]")
    linkShare: Share = Field(description="Share of the shear reinforcement as links at least.")


class StrutTorsionRules(_Group):
    """Torsion by the thin-walled closed section (method ``thinWalledVariableStrut``)."""

    method: Literal["thinWalledVariableStrut"] = "thinWalledVariableStrut"
    coverShare: Positive = Field(description="tef at least this × the distance to the bar axis.")
    spacingDivisor: Positive = Field(description="Torsion links at most u / divisor apart.")
    spacingMax: Positive = Field(description="[mm], also at most the least dimension.")
    longitudinalSpacingMax: Positive = Field(description="[mm]")


class PunchingRules(_Group):
    """Punching on the basic control perimeter (method ``controlPerimeter``)."""

    method: Literal["controlPerimeter"] = "controlPerimeter"
    perimeterDistance: Positive = Field(description="u1 at this × d from the loaded area.")
    beta: dict[str, Positive] = Field(description="β by column position (interior, edge, corner).")
    crdcCoefficient: Positive
    k1: Positive
    sizeReference: Positive
    sizeMax: Positive
    rhoLMax: Share
    vminCoefficient: Positive
    vmaxShare: Positive = Field(description="vRd,max = share × ν fcd at the column face.")
    concreteShare: Share = Field(description="vRd,cs = share × vRd,c + the reinforcement term.")
    reinforcementCoefficient: Positive = Field(
        description="1.5 (d / sr) Asw fywd,ef sinα / (u1 d)."
    )
    fywdEfBase: Positive = Field(description="fywd,ef = base + slope × d [MPa].")
    fywdEfSlope: Positive
    outerDistance: Positive = Field(description="Outermost perimeter at most this × d inside uout.")


class ServiceStressRules(_Group):
    """Stress limits under the service combinations."""

    k1: Share = Field(description="σc at most k1 fck, characteristic, exposure XD, XF, XS.")
    k2: Share = Field(description="σc at most k2 fck, quasi-permanent, for linear creep.")
    k3: Share = Field(description="σs at most k3 fyk, characteristic.")
    k4: Positive = Field(description="σs at most k4 fyk, imposed deformation.")
    k1Exposures: list[str] = Field(default_factory=list)
    #: Alpha 9 C5b: ids of the pack's service combinations (``combinations.service``) of the
    #: quasi-permanent and characteristic combinations.
    quasiPermanent: str | None = None
    characteristic: str | None = None


class CrackRules(_Group):
    """Crack control: wmax by exposure class, minimum steel and the direct calculation
    (method ``directWidth``)."""

    method: Literal["directWidth"] = "directWidth"
    wmax: dict[str, Positive] = Field(description="wmax [mm] by exposure class (quasi-permanent).")
    kcBending: Share
    kcTension: Share
    kThin: Share = Field(description="k for h <= thinDepth.")
    kThick: Share = Field(description="k for h >= thickDepth (linear between).")
    thinDepth: Positive
    thickDepth: Positive
    k1Bond: Positive = Field(description="k1 of high bond bars.")
    k2Bending: Positive
    k2Tension: Positive
    k3: Positive
    k4: Positive
    ktShort: Share
    ktLong: Share
    strainFloor: Share = Field(description="εsm - εcm at least this × σs / Es.")
    effectiveDepthShare: Positive = Field(description="hc,ef = min(share (h - d), (h - x)/3, h/2).")
    wideSpacingFactor: Positive = Field(
        description="Bars over 5 (c + φ/2) apart: sr,max = factor (h - x)."
    )
    wideSpacingLimit: Positive = Field(description="The spacing limit is this × (c + φ/2).")


class SpanDepthRules(_Group):
    """Deflection by span/depth ratios with K factors (method ``spanDepthK``)."""

    method: Literal["spanDepthK"] = "spanDepthK"
    k: dict[str, Positive] = Field(description="K by structural system.")
    base: Positive
    lowCoefficient: Positive
    lowPowerCoefficient: Positive
    highCompressionShare: Positive
    referenceRatioCoefficient: Positive = Field(description="ρ0 = c √fck.")
    stressReference: Positive = Field(description="Factor 310 / σs.")
    stressSteel: Positive = Field(description="310 / σs = this / (fyk As,req / As,prov).")
    flangeRatio: Positive = Field(description="beff / bw above this: × flangeFactor.")
    flangeFactor: Share
    longSpan: Positive = Field(description="[mm] beams and slabs longer: × longSpan / l.")
    longFlatSpan: Positive = Field(description="[mm] flat slabs longer: × longFlatSpan / l.")


class CoverRules(_Group):
    """Nominal cover from the exposure and structural classes (method ``exposureClass``)."""

    method: Literal["exposureClass"] = "exposureClass"
    structuralClass: int = Field(ge=1, le=6, description="Default structural class (S1-S6).")
    durability: dict[str, list[Positive]] = Field(
        description="cmin,dur [mm] by exposure group, for structural classes S1 to S6."
    )
    exposureGroups: dict[str, str] = Field(
        description="Exposure class -> its group of 'durability'."
    )
    strengthReduction: dict[str, Positive] = Field(
        description="fck from which the structural class drops by one, by exposure class."
    )
    longLifeIncrease: int = Field(ge=0, description="Classes added for a 100-year design life.")
    slabReduction: int = Field(ge=0, description="Classes taken off for slab geometry.")
    deviation: Positive = Field(description="Δcdev [mm].")
    minimum: Positive = Field(description="cmin at least [mm].")
    largeAggregate: Positive = Field(description="cmin,b + aggregateIncrease above this size [mm].")
    aggregateIncrease: Positive


class AnchorageRules(_Group):
    """Anchorage and lap lengths from the design bond stress (method ``bondStress``)."""

    method: Literal["bondStress"] = "bondStress"
    bondCoefficient: Positive = Field(description="fbd = coefficient η1 η2 fctd.")
    eta1Poor: Share
    largeBar: Positive = Field(description="η2 = (bend - φ)/100 above this [mm].")
    largeBarBend: Positive
    fckCap: Positive = Field(description="fctd taken at most at this fck [MPa].")
    hookAlpha: Share = Field(description="α1 of bent bars when cd > hookCover × φ.")
    hookCover: Positive
    coverAlphaSlope: Positive = Field(description="α2 = 1 - slope (cd - φ)/φ, in [low, 1].")
    coverAlphaLow: Share
    minTension: tuple[Share, Positive, Positive] = Field(
        description="lb,min in tension: max(share lb,rqd, n φ, mm)."
    )
    minCompression: tuple[Share, Positive, Positive]
    lapMin: tuple[Share, Positive, Positive] = Field(
        description="l0,min: max(share α6 lb,rqd, n φ, mm)."
    )
    lapAlpha6: list[tuple[Share, Positive]] = Field(
        description="(share of bars lapped at most, α6)."
    )


class MemberSteelRules(_Group):
    """Least and largest steel of beams, slabs, columns and walls."""

    beamMinCoefficient: Positive = Field(description="As,min = c fctm / fyk bt d ...")
    beamMinRatio: Share = Field(description="... at least ratio bt d.")
    beamMaxRatio: Share = Field(description="As,max = ratio Ac.")
    slabMaxSpacing: tuple[Positive, Positive] = Field(description="Principal: n h, at most mm.")
    slabSecondaryShare: Share
    slabSecondarySpacing: tuple[Positive, Positive]
    columnMinDia: Positive
    columnMinAxialShare: Share = Field(description="As,min = share NEd / fyd ...")
    columnMinRatio: Share = Field(description="... at least ratio Ac.")
    columnMaxRatio: Share
    columnMaxRatioLaps: Share
    linkMinDia: Positive
    linkDiaShare: Share = Field(description="Links at least share × the largest bar.")
    linkSpacing: tuple[Positive, Positive] = Field(description="min(n φmin, b, mm).")
    linkSpacingReduction: Share = Field(description="× near beams and slabs and at laps.")
    restrainedDistance: Positive = Field(description="Bars within this [mm] of a restrained bar.")
    wallVerticalMin: Share
    wallVerticalMax: Share
    wallVerticalSpacing: tuple[Positive, Positive]
    wallHorizontalShare: Share
    wallHorizontalMin: Share
    wallHorizontalSpacing: Positive


class DuctilityClassRules(_Group):
    """The detailing of one ductility class (DCM or DCH) of earthquake-resistant concrete."""

    fckMin: Positive
    gammaRdBeam: Positive = Field(description="γRd of the beams' capacity design shear.")
    gammaRdColumn: Positive = Field(description="γRd of the columns' capacity design shear.")
    gammaRdJoint: Positive | None = None
    strongColumn: Positive = Field(description="ΣMRc >= factor ΣMRb.")
    beamCritical: Positive = Field(description="lcr = factor × hw.")
    beamHoops: tuple[Positive, Positive, Positive, Positive] = Field(
        description="s <= min(hw / a, b dbw, c mm, d dbL)."
    )
    beamFirstHoop: Positive = Field(description="[mm] from the column face.")
    hoopMinDia: Positive
    beamRhoMinCoefficient: Positive = Field(description="ρmin = c fctm / fyk.")
    beamRhoMaxCoefficient: Positive = Field(description="ρmax = ρ' + c / (μφ εsy,d) fcd / fyd.")
    beamCompressionShare: Share = Field(description="As' >= share As in critical regions.")
    beamContinuousBars: int = Field(ge=0, description="Bars along the beam, top and bottom (DCH).")
    beamContinuousDia: Positive | None = None
    nuMax: Share = Field(description="νd = NEd / (Ac fcd) at most.")
    columnRho: tuple[Share, Share]
    columnCritical: tuple[Positive, Positive, Positive] = Field(
        description="lcr = max(a hc, lcl / b, c mm)."
    )
    columnHoops: tuple[Positive, Positive, Positive] = Field(
        description="s <= min(b0 / a, b mm, c dbL)."
    )
    columnRestrained: Positive = Field(description="Restrained bars at most this apart [mm].")
    columnMinDimension: Positive | None = None
    omegaBase: Positive = Field(description="ωwd at least at the column base.")
    omegaOther: Positive | None = Field(default=None, description="ωwd at least elsewhere.")
    confinementCoefficient: Positive = Field(description="α ωwd >= c μφ νd εsy,d bc/b0 - offset.")
    confinementOffset: Positive
    classBFactor: Positive | None = Field(
        default=None, description="μφ × factor with class B steel in critical regions."
    )
    jointEtaCoefficient: Positive | None = None
    jointEtaDivisor: Positive | None = None
    jointExteriorShare: Share | None = None
    wallCritical: tuple[Positive, Positive] = Field(description="hcr = max(lw, hw / b) (a: × lw).")
    wallBoundaryLength: tuple[Share, Positive] = Field(description="lc >= max(a lw, b bw).")
    wallBoundaryRho: Share
    wallOmega: Positive
    wallThickness: tuple[Positive, Positive] = Field(description="bw >= max(mm, hs / n).")
    wallShearFactor: Positive = Field(
        description="ε of the walls' design shear (DCM; DCH minimum)."
    )
    couplingSpanRatio: Positive = Field(description="Diagonal bars unless l/h >= this.")
    couplingDiagonalMin: int = Field(ge=1)


class SeismicConcreteRules(_Group):
    """Curvature-ductility detailing (method ``curvatureDuctility``)."""

    method: Literal["curvatureDuctility"] = "curvatureDuctility"
    classes: dict[str, DuctilityClassRules] = Field(description="By ductility class: DCM, DCH.")
    frameClasses: dict[str, str] = Field(
        description="The seismic systems' 'frame' level -> ductility class (special -> DCH ...)."
    )


class SlendernessRules(_Group):
    """Column slenderness by the slenderness limit and the nominal curvature method (method
    ``nominalCurvature``; alpha 9 C5b)."""

    method: Literal["nominalCurvature"] = "nominalCurvature"
    limitCoefficient: Positive = Field(description="λlim = coefficient A B C / √n.")
    creepShare: Positive = Field(
        description="A = 1 / (1 + share φef) (A taken 1/(1 + share φef) from the given φef)."
    )
    mechanicalShare: Positive = Field(description="B = √(1 + share ω).")
    momentRatioBase: Positive = Field(description="C = base - rm.")
    unbracedRatio: float = Field(description="rm of unbraced members and transverse loads.")
    creepCoefficient: float = Field(
        ge=0, description="φ(∞, t0) of the columns (SAEngine practice, overridable)."
    )
    sustainedShare: Share = Field(
        description="M0Eqp / M0Ed when the analysis gives no sustained share (φef = φ × share)."
    )
    curvatureDepthShare: Positive = Field(description="1/r0 = εyd / (share d).")
    curvatureDistribution: Positive = Field(description="e2 = (1/r) l0² / c.")
    balancedAxial: Positive = Field(description="nbal of Kr.")
    betaBase: Positive = Field(description="β = base + fck / fckDivisor - λ / lambdaDivisor.")
    betaFckDivisor: Positive
    betaLambdaDivisor: Positive
    equivalentMoment: tuple[Share, Share, Share] = Field(
        description="M0e = a M02 + b M01 >= c M02 (braced members)."
    )
    curvatureShareEnd: Share = Field(description="MEd >= M01 + share M2 (braced members).")


class ExposureClass(_Group):
    name: str
    fckMin: Positive | None = Field(default=None, description="Indicative least fck [MPa].")


# ─────────── Alpha 9 C8: the working-to-limit-state methods of tabulated codes (IS 456) ───────────
# Groups a pack picks by their method id (the same group names as above where the idea is the
# same: shear, torsion, punching, deflection, cracking, cover, anchorage, seismic), and the
# groups no other method has yet (memberLimits, columns, twoWaySlabs, flatSlabs, walls,
# footings). The modules: saengine.design.tabulated_shear, additional_moment, span_depth_factors,
# member_limits, panel_coefficients, ductile_detailing.


class DepthFactor(_Group):
    """A depth factor on the tabulated τc: (reference / d)^exponent, at least ``min``."""

    reference: Positive = Field(description="[mm]")
    exponent: Positive
    min: Positive = 1.0


class InclinedSectionRule(_Group):
    """Alpha 9 C25: shear of beams by the inclined section (SP 63.13330.2018 8.1.31-8.1.34
    type, :func:`saengine.design.tabulated_shear.inclined_resistance`): Q <= Qb + Qsw at the
    projection c of the inclined section that gives the least, c from h0 to ``spanRange``[1]
    h0; Qb = concreteFactor fctd b h0² / c within ``concreteRange`` × fctd b h0; Qsw =
    stirrupFactor qsw c0, c0 = min(c, stirrupSpan h0), qsw = fyd,w Asw / sw; the links count
    where qsw >= stirrupMin fctd b, below it fctd b is taken as qsw / stirrupMin; the strut
    Q <= strutFactor fcd b h0."""

    method: Literal["qbQsw"] = "qbQsw"
    concreteFactor: Positive = Field(description="φb2 of Qb = φb2 fctd b h0² / c.")
    concreteRange: tuple[Positive, Positive] = Field(description="Qb within (a, b) fctd b h0.")
    stirrupFactor: Positive = Field(description="φsw of Qsw = φsw qsw c0.")
    stirrupSpan: Positive = Field(description="c0 at most this × h0.")
    spanRange: tuple[Positive, Positive] = Field(description="c within (a, b) × h0.")
    stirrupMin: Share = Field(description="qsw >= this × fctd b for the links to count fully.")
    strutFactor: Share = Field(description="φb1 of Q <= φb1 fcd b h0.")


class TabulatedShearRules(_Group):
    """Shear by a design shear strength of concrete tabulated by the tension steel ratio and the
    grade (method ``tabulatedStress``): τc from ``tauC`` (rows by ``steelRatios`` [%], columns
    by ``grades`` [MPa], linear between, the end values outside), τv = Vu / (b d) at most
    ``maxStress`` by grade, the stirrups Vus = (1/γs) fy Asv d / sv, the least stirrups
    Asv / (b sv) >= ``minStirrupStress`` / ((1/γs) fy)."""

    method: Literal["tabulatedStress"] = "tabulatedStress"
    grades: list[Positive] = Field(min_length=1)
    steelRatios: list[Positive] = Field(min_length=2, description="pt = 100 As / (b d) [%].")
    tauC: list[list[Positive]] = Field(description="τc [MPa], a row per steel ratio.")
    maxStress: list[Positive] = Field(description="τc,max [MPa] by grade.")
    minStirrupStress: Positive = Field(description="Asv fy,d / (b sv) at least this [MPa].")
    fyMax: Positive = Field(description="fy of stirrups taken at most this [MPa].")
    spacing: tuple[Share, Positive] = Field(description="sv <= min(share d, mm).")
    slabDepths: list[tuple[Positive, Positive]] = Field(
        default_factory=list, description="(overall depth [mm], k) of solid slabs, k τc."
    )
    enhancement: Positive = Field(
        default=2.0, description="τc × enhancement d / av within d of a support face."
    )
    # Alpha 9 C9b: members in axial compression (columns), τc × δ.
    axialFactor: float | None = Field(
        default=None,
        description="δ = 1 + axialFactor Pu / (Ag fck) on τc of columns (none: δ = 1).",
    )
    axialMax: Positive | None = Field(default=None, description="δ at most this.")
    # Alpha 9 C10 (BS 8110-1 Table 3.8): τc × (reference / d)^exponent, at least min, every member.
    depthFactor: DepthFactor | None = Field(
        default=None, description="τc × (reference / d)^exponent >= min (none: 1)."
    )
    # Alpha 9 C25 (SP 63.13330.2018 6.2.10 Table 6.15: Rsw = 0.8 Rs, at most 300 MPa).
    stirrupYieldShare: Share | None = Field(
        default=None, description="fyd of stirrups × this (none: fyd)."
    )
    stirrupYieldMax: Positive | None = Field(
        default=None, description="fyd of stirrups at most this [MPa] (none: no cap)."
    )
    # Alpha 9 C25 (SP 63.13330.2018 8.1.31-8.1.34): beams by the inclined section, Q <= Qb + Qsw.
    inclinedSection: InclinedSectionRule | None = Field(
        default=None,
        description="Beam shear by the inclined section Qb + Qsw at the worst c (none: τc b d + "
        "Vus).",
    )


class EquivalentTorsionRules(_Group):
    """Torsion by the equivalent shear and moment (method ``equivalentShear``): Ve = Vu +
    shearFactor Tu / b, Me1 = Mu + Tu (1 + D/b) / momentDivisor; links Asv = Tu sv / (b1 d1
    fyd) + Vu sv / (depthDivisor d1 fyd), at least (τve - τc) b sv / fyd."""

    method: Literal["equivalentShear"] = "equivalentShear"
    shearFactor: Positive
    momentDivisor: Positive
    depthDivisor: Positive
    spacingDivisor: Positive = Field(description="Links at most (x1 + y1) / divisor apart.")
    spacingMax: Positive = Field(description="[mm], also at most x1.")


class RootStressPunchingRules(_Group):
    """Punching by a shear stress on a perimeter (method ``rootStress``): τc = coefficient √fck
    times ks = ratioBase + βc <= 1 at perimeterDistance × d from the loaded area; with shear
    reinforcement τv <= reinforcedMax τc and the steel for Vu - concreteShare Vc."""

    method: Literal["rootStress"] = "rootStress"
    perimeterDistance: Positive
    coefficient: Positive
    ratioBase: Positive
    reinforcedMax: Positive
    concreteShare: Share
    # Alpha 9 C20b (GB 50010 6.5.1 type: Fl <= 0.7 βh ft η um h0): τc = coefficient × fctd × βh
    # × η in place of coefficient √fck × ks, η = min(ks, η2), ks = ratioBase + ratioFactor βc
    # <= 1, η2 = a + αs d / (b b0) (``locationTerm``, αs 40 / 30 / 20 by the column's
    # position), βh by the depth (``depthFactors``, linear between, the end values outside).
    strength: Literal["root", "tensile"] = Field(
        default="root", description="root: coefficient √fck; tensile: coefficient fctd."
    )
    ratioFactor: Positive = Field(default=1.0, description="ks = ratioBase + this × βc <= 1.")
    locationTerm: tuple[Positive, Positive] | None = Field(
        default=None, description="(a, b): η2 = a + αs d / (b b0) (none: not used)."
    )
    depthFactors: list[tuple[Positive, Positive]] = Field(
        default_factory=list, description="(depth [mm], βh), linear between (empty: 1)."
    )


class SpanDepthFactorRules(_Group):
    """Deflection by basic span/effective depth ratios with modification factors (method
    ``spanDepthModification``), and the calculated deflection (``calculated``)."""

    method: Literal["spanDepthModification"] = "spanDepthModification"
    basic: dict[str, Positive] = Field(description="By support: cantilever, simple, continuous.")
    longSpan: Positive = Field(description="[mm] beyond it × longSpan / l (not cantilevers).")
    tension: tuple[float, float, float, Positive] = Field(
        description="(a, b, c, max): kt = 1 / (a + b fs - c log10(1 / pt)) (pt in %), a fit of the "
        "tension steel curve, at most max; fs = stressShare fy As,req / As,prov."
    )
    stressShare: Share
    # Alpha 9 C10 (BS 8110-1 Table 3.10): kt = a + (b - fs) / (c (d0 + M/bd²)) <= max.
    tensionMoment: tuple[Positive, Positive, Positive, float, Positive] | None = Field(
        default=None,
        description="(a, b, c, d0, max) of kt = a + (b - fs) / (c (d0 + M / b d²)) in place of "
        "``tension`` (M / b d² from pt at fy / γs and z = leverArm d); none: ``tension``.",
    )
    leverArm: Share = Field(default=0.9, description="z / d of M / b d² (tensionMoment).")
    compression: tuple[Positive, Positive] = Field(
        description="(a, max): kc = 1 + pc / (a + pc), at most max (pc in %)."
    )
    flange: list[tuple[Share, Positive]] = Field(description="(bw / bf, kf), linear between.")
    flatSlabFactor: Share = Field(default=1.0, description="× for flat slabs.")
    flangeT: tuple[Positive, Positive] = Field(
        description="T-beams: bf = l / a + bw + b Df (the flange of the modification factor)."
    )
    flangeL: tuple[Positive, Positive] = Field(description="L-beams: bf = l / a + bw + b Df.")
    shrinkageStrain: Positive
    shrinkageK3: dict[str, Positive] = Field(description="k3 by support.")
    shrinkageK4: list[tuple[Positive, Positive]] = Field(
        description="(pt - pc from [%], coefficient) of k4 = c (pt - pc)/√pt <= 1."
    )
    creep: list[tuple[Positive, Positive]] = Field(description="(age at loading [days], θ).")
    loadingAge: Positive = Field(description="Age at loading [days] taken.")
    ruptureCoefficient: Positive = Field(description="fcr = c √fck.")
    limitTotal: Positive = Field(description="Final deflection at most span / this.")
    limitAfter: Positive = Field(description="After partitions: span / this ...")
    limitAfterMax: Positive = Field(description="... and at most this [mm].")


class CrackWidthRules(_Group):
    """Crack width from the strain at the surface and the distance to the nearest bar (method
    ``strainSpacing``): Wcr = 3 acr εm / (1 + 2 (acr - cmin) / (h - x))."""

    method: Literal["strainSpacing"] = "strainSpacing"
    width: dict[str, Positive] = Field(description="Wmax [mm] by exposure condition.")
    stiffeningDivisor: Positive = Field(description="εm = ε1 - b (h-x)(a'-x) / (div Es As (d-x)).")
    tankWidth: Positive | None = Field(default=None, description="Liquid-retaining [mm].")


class ExposureCondition(_Group):
    cover: Positive = Field(description="Nominal cover [mm].")
    # Alpha 9 C20b (GB 50010 3.5.3: no least cement content): none, not stated.
    cement: Positive | None = Field(default=None, description="Least cement content [kg/m³].")
    waterCement: Share = Field(description="Largest free water-cement ratio.")
    grade: Positive = Field(description="Least grade fck [MPa].")
    # Alpha 9 C20b (GB 50010 Table 8.2.1: beams and columns take more cover than slabs and
    # walls): the cover of beams and columns; none: ``cover`` for every member.
    beamCover: Positive | None = Field(
        default=None, description="Nominal cover of beams and columns [mm] (none: cover)."
    )


class ExposureConditionRules(_Group):
    """Cover and mix limits by exposure condition (method ``exposureCondition``)."""

    method: Literal["exposureCondition"] = "exposureCondition"
    conditions: dict[str, ExposureCondition]
    columnCover: Positive = Field(description="Longitudinal bars of columns at least [mm].")
    footingCover: Positive = Field(description="Footings at least [mm].")
    smallBarReduction: tuple[float, float] = Field(
        description="(mm less, bars up to mm) in the mildest condition."
    )
    gradeReduction: tuple[Positive, Positive] = Field(
        description="(mm less, from fck) in the conditions named in gradeReductionConditions."
    )
    gradeReductionConditions: list[str] = Field(default_factory=list)


class BondTableRules(_Group):
    """Development length Ld = φ σs / (4 τbd) by the design bond stress by grade (method
    ``bondStressTable``) and the laps."""

    method: Literal["bondStressTable"] = "bondStressTable"
    grades: list[Positive]
    bond: list[Positive] = Field(description="τbd [MPa] of plain bars in tension by grade.")
    deformedFactor: Positive
    compressionFactor: Positive
    lapTension: Positive = Field(description="Laps in flexural tension: max(Ld, n φ).")
    lapCompression: Positive = Field(description="Laps in compression: max(Ld,c, n φ).")
    lapDirectTension: Positive = Field(description="Laps in direct tension: max(x Ld, n φ).")
    lapLargeBar: Positive = Field(description="No laps of bars larger than this [mm].")
    # Alpha 9 C20b (GB 50010 8.3.1-8.3.2, 8.4.4, 11.1.7 type): la = ζa lab at least minLength,
    # ζa of large bars, laps ll = ζl la by the share of bars lapped at one section (at least
    # lapMinLength), and the seismic la,E = ζa,E la with ζa,E the seismic grade's "anchorage"
    # factor (:mod:`saengine.design.seismic_grades`).
    minLength: Positive | None = Field(
        default=None, description="Ld at least this [mm] (none: no floor)."
    )
    largeBarFactor: tuple[Positive, Positive] | None = Field(
        default=None, description="(bars above [mm], ζa): Ld × ζa of the larger bars."
    )
    lapFactors: list[tuple[Share, Positive]] | None = Field(
        default=None,
        description="(share of bars lapped at a section up to, ζl): laps ll = ζl Ld in flexural "
        "tension in place of max(Ld, lapTension φ); the first row taken (none: lapTension).",
    )
    lapMinLength: Positive | None = Field(
        default=None, description="Laps at least this [mm] (none: no floor)."
    )
    columnLapShare: Share | None = Field(
        default=None,
        description="The share of the bars lapped at one section taken for columns (beams: "
        "the first lapFactors row's).",
    )


class MemberLimitRules(_Group):
    """Least and largest steel and the bar rules of beams, slabs and columns of codes that give
    them as ratios (beams As/(b d) >= beamMin / fy ...)."""

    beamMin: Positive = Field(description="As / (b d) >= beamMin / fy.")
    beamMax: Share = Field(description="As (and As') at most this × b D.")
    sideFaceDepth: Positive = Field(description="[mm] deeper webs: side face steel.")
    sideFaceShare: Share = Field(description="× the web area, both faces together.")
    sideFaceSpacing: Positive = Field(description="[mm] at most, and at most the web width.")
    slabMin: tuple[Share, Share] = Field(description="Of b D: deformed bars, plain (mild) bars.")
    plainFy: Positive = Field(description="fy [MPa] at most of plain (mild) bars.")
    slabBarShare: Share = Field(description="Slab bars at most this × D.")
    slabSpacing: tuple[Positive, Positive] = Field(description="Main bars: min(n d, mm).")
    slabDistributionSpacing: tuple[Positive, Positive]
    columnRho: tuple[Share, Share]
    columnBars: tuple[int, int] = Field(description="(rectangular, circular) at least.")
    columnBarDia: Positive
    tieDiaShare: Share = Field(description="Ties at least share × the largest bar ...")
    tieDiaMin: Positive = Field(description="... and this [mm].")
    tiePitch: tuple[Positive, Positive] = Field(description="min(least dimension, n φ, mm).")
    neutralAxisStrain: float = Field(
        ge=0, description="xu,max: the bars' strain at least fyd/Es + this (limiting depth)."
    )
    # Alpha 9 C20b (GB 50010 8.5.1 type: ρmin = max(0.20 %, 45 ft/fy) of beams and slabs, on
    # b h): with beamMinRatio the least steel is max(beamMinRatio, beamMinTensile fctd/fyd) b h
    # in place of beamMin / fy b d.
    beamMinRatio: Share | None = Field(
        default=None, description="As/(b h) at least this (none: beamMin / fy on b d)."
    )
    beamMinTensile: Positive | None = Field(
        default=None, description="With beamMinRatio: As/(b h) also at least this × fctd/fyd."
    )
    slabMinTensile: Positive | None = Field(
        default=None, description="Slabs: As/(b D) also at least this × fctd/fyd (none)."
    )
    sideFaceEach: bool = Field(
        default=False, description="sideFaceShare is of each face (else both faces together)."
    )


class EndMomentSlendernessRule(_Group):
    """Alpha 9 C20b: slender columns by the end moments (method ``endMomentMagnifier``, GB
    50010 6.2.3-6.2.4 type, :mod:`saengine.design.end_moment_magnifier`): M = Cm ηns M2 >= M2
    with Cm = cmBase + cmRatio M1/M2 >= cmMin, ηns = 1 + (lc/h)² ζc / (divisor (M2/N + ea)/h0),
    ζc = zetaShare fcd A / N <= 1; not needed where M1/M2 <= exemptRatio, N/(fcd A) <=
    exemptAxial and lc/i <= a - b M1/M2 (``exemptSlenderness``)."""

    method: Literal["endMomentMagnifier"]
    cmBase: Positive
    cmRatio: Positive
    cmMin: Share
    divisor: Positive
    zetaShare: Positive
    exemptRatio: Share
    exemptAxial: Share
    exemptSlenderness: tuple[Positive, Positive]


class SlendernessRule(_Group):
    method: Literal["additionalMoment"] = "additionalMoment"
    limit: Positive = Field(description="Short when lex / D is at most this.")
    divisor: Positive = Field(description="Ma = Pu D / divisor (lex / D)².")
    maxRatio: Positive = Field(description="lex / D at most this (unsupported length).")
    # Alpha 9 C10 (BS 8110-1 3.8.1.3: 15 braced, 10 unbraced).
    unbracedLimit: Positive | None = Field(
        default=None, description="Short in a sway storey up to this (none: ``limit``)."
    )


class BiaxialRule(_Group):
    method: Literal["loadContour", "surface"] = "loadContour"
    # Alpha 9 C20b: not read by the ``surface`` method (may be left out there).
    alphaN: list[tuple[Share, Positive]] = Field(
        default_factory=list, description="(Pu / Puz, αn), linear between (loadContour)."
    )
    puzShares: tuple[Positive, Positive] | None = Field(
        default=None, description="Puz = a fck Ac + b fy Asc (loadContour)."
    )


class ColumnMethodRules(_Group):
    """Columns: slenderness (``additionalMoment``, alpha 9 C20b ``endMomentMagnifier``) and
    biaxial bending (``loadContour``, or the interaction ``surface``)."""

    slenderness: SlendernessRule | EndMomentSlendernessRule
    biaxial: BiaxialRule


class PanelCase(_Group):
    name: str
    shortNegative: list[Positive] | None = None
    shortPositive: list[Positive]
    longNegative: Positive | None = None
    longPositive: Positive


class TwoWaySlabRules(_Group):
    """Two-way slabs on beams by moment coefficients by edge case (method
    ``restrainedPanel``): M = α w lx² per unit width."""

    method: Literal["restrainedPanel"] = "restrainedPanel"
    ratios: list[Positive] = Field(description="ly / lx of the coefficient columns.")
    cases: dict[str, PanelCase]
    simpleRatios: list[Positive]
    simpleShort: list[Positive]
    simpleLong: list[Positive]
    middleStrip: Share = Field(description="Middle strip share of the width.")
    torsionShare: Share = Field(description="Corner steel: × the largest midspan steel ...")
    torsionLength: Share = Field(description="... over this × lx each way.")
    torsionOneEdgeShare: Share = Field(description="× that where one edge is continuous.")


class FlatSlabRules(_Group):
    """Flat slabs by the direct design method with the end span shares by the column
    stiffness ratio αc (method ``columnStiffness``)."""

    method: Literal["columnStiffness"] = "columnStiffness"
    interiorNegative: tuple[Positive, Positive] = Field(description="a - b / (1 + 1/αc).")
    positive: tuple[Positive, Positive] = Field(description="a - b / (1 + 1/αc).")
    exteriorNegative: Positive = Field(description="a / (1 + 1/αc).")
    columnStrip: tuple[Share, Share, Share] = Field(
        description="Column strip share: interior negative, exterior negative, positive."
    )
    minThickness: Positive


class WallMethodRules(_Group):
    """Walls by the empirical eccentricity method and the shear by the aspect ratio (methods
    ``eccentricityEmpirical`` and ``aspectRatioShear``)."""

    method: Literal["eccentricityEmpirical"] = "eccentricityEmpirical"
    axialFactor: Positive = Field(description="Puw = f (t - a e - 2 ea) fck Lw.")
    eccentricityFactor: Positive
    additionalDivisor: Positive = Field(description="ea = Hwe² / (divisor t).")
    minEccentricityShare: Share = Field(description="e at least this × t.")
    slendernessMax: Positive = Field(description="Hwe / t at most.")
    minThickness: Positive
    shearK1: Positive = Field(description="τcw = (intercept - αw) K1 √fck for αw <= 1.")
    shearIntercept: Positive
    shearK2: Positive = Field(description="αw > 1: also K2 fck (αw + 1)/(αw - 1).")
    shearMaxShare: Share = Field(description="τv at most this × fck.")
    depthShare: Share = Field(description="d = share × Lw.")
    vertical: tuple[Share, Share] = Field(description="Least ρ: deformed small bars, others.")
    horizontal: tuple[Share, Share]
    smallBarMax: Positive
    spacing: tuple[Positive, Positive] = Field(description="min(n t, mm).")


class FootingMethodRules(_Group):
    """Footings: the edge thickness, the bearing of the column on the footing."""

    edgeThickness: Positive
    pileEdgeThickness: Positive
    bearingFactor: Positive = Field(description="Bearing stress factor × fck ...")
    bearingRatioMax: Positive = Field(description="... × √(A1/A2) at most this.")


class DuctileBeamRules(_Group):
    minWidth: Positive
    minRatio: Share
    depthShare: Share = Field(description="D at most this × the clear span.")
    minBars: int = Field(ge=1)
    minBarDia: Positive
    rhoMinRoot: Positive = Field(description="ρ >= c √fck / fy.")
    rhoMax: Share
    positiveShare: Share = Field(description="Bottom >= share × top at the joint face.")
    anyShare: Share = Field(description="Any section >= share × the most at the faces.")
    hoopZoneDepths: Positive = Field(description="Close hoops over this × d from the faces.")
    hoopSpacing: tuple[Share, Positive, Positive] = Field(description="min(a d, b db, mm).")
    firstHoop: Positive
    elsewhereShare: Share = Field(description="Elsewhere at most this × d.")
    hoopMinDia: Positive
    overstrength: Positive = Field(description="Capacity shear: × the moment capacities.")
    # Alpha 9 C18c (NZS 3101 9.4.? / AS 3600 App C type: the plastic hinge region set on the
    # member depth D, not d).
    hoopZoneOnDepth: bool = Field(
        default=False, description="The close hoops' zone is hoopZoneDepths × D (else × d)."
    )


class DuctileColumnRules(_Group):
    axialShare: Share = Field(description="Members with Pu > share fck Ag are columns.")
    minDimension: Positive
    minRatio: Share
    rho: tuple[Share, Share]
    strongColumn: Positive
    confinedLength: tuple[Positive, Positive, Positive] = Field(
        description="lo >= max(a D, clear / b, mm)."
    )
    confinedSpacing: tuple[Share, Positive, Positive] = Field(
        description="min(a × least dimension, b db, mm)."
    )
    ash: tuple[Positive, Positive] = Field(description="Ash/(s h) >= max(a (Ag/Ak - 1), b) fck/fy.")
    spiral: tuple[Positive, Positive] = Field(description="Same, circular hoops (× Dk).")
    hxMax: Positive
    outsideShare: Share = Field(description="Outside lo: at most share × least dimension.")
    lapHoopSpacing: Positive
    # Alpha 9 C18c: the NZS 3101 type confinement and the capacity design of columns.
    ashForm: Literal["areaRatio", "axialLoad"] = Field(
        default="areaRatio",
        description="areaRatio: Ash/(s h) >= max(a (Ag/Ak - 1), b) fck/fy (``ash``); axialLoad: "
        "Ash/(s h) = (a - ρt m)/b (Ag/Ac) (f'c/fyt) N*/(φ f'c Ag) - c (``ashAxial``).",
    )
    ashAxial: tuple[Positive, Positive, float, Share] | None = Field(
        default=None,
        description="(a, b, c, φ) of the axialLoad form, m = fy / (0.85 f'c) (``ash`` then only "
        "sizes the hoops of Design Reinforcement).",
    )
    confinedByAxial: list[tuple[Positive, Positive]] = Field(
        default_factory=list,
        description="lo = a × D by N*/(φ f'c Ag): (axial share up to, a) rows, the first that "
        "holds; empty: ``confinedLength`` alone (else the larger of both).",
    )
    capacityShear: Positive | None = Field(
        default=None,
        description="V*col = this × (Mn,top + Mn,bottom) / the clear height (Mn the column's "
        "largest nominal moment over the earthquake axial forces); none: not checked.",
    )


class DuctileJointRules(_Group):
    gamma: dict[str, Positive] = Field(description="Vj <= γ √fck Aej by confinement.")
    overstrength: Positive
    widthShare: Share = Field(description="bj = min(bb + share × hc, bc).")
    # Alpha 9 C18c (NZS 3101 15.4 type).
    stressLimit: tuple[Share, Positive] | None = Field(
        default=None,
        description="vjh at most min(a f'c, b MPa) in place of γ √fck (none: the γ form).",
    )
    reinforcementShare: Share | None = Field(
        default=None,
        description="Horizontal joint hoops Ajh >= share × Vjh / fyh (none: not checked).",
    )


class DuctileWallRules(_Group):
    minThickness: Positive
    rhoMin: Share
    twoCurtainThickness: Positive
    twoCurtainRoot: Positive = Field(description="Or τv > c √fck.")
    barDiaShare: Share
    spacing: tuple[Positive, Positive, Positive] = Field(description="min(lw / a, b t, mm).")
    boundaryStress: Share = Field(description="Boundary elements where σ > share fck ...")
    boundaryStop: Share = Field(description="... until σ < this × fck.")
    couplingRoot: Positive = Field(description="Diagonal bars where τv > c (ls/D) √fck ...")
    couplingSpanRatio: Positive = Field(description="... and ls / D below this.")
    # Alpha 9 C18c (NZS 3101 11.4 type): the ductile walls' design shear, boundary
    # confinement and the diagonal bars' φ under the capacity-factor basis.
    shearAmplification: WallShearAmplification | None = Field(
        default=None,
        description="The design shear V = Ωv ωv V* of the earthquake combinations (overstrength "
        "and dynamic magnification); none: the factored shear.",
    )
    boundaryAsh: tuple[Positive, Positive] | None = Field(
        default=None,
        description="Boundary hoops Ash/(s h) >= max(a (Ag/Ac - 1), b) f'c/fyt of the boundary "
        "element (none: flagged only).",
    )
    boundaryLength: tuple[Share, Share] | None = Field(
        default=None,
        description="The confined end at least max(a lw, b × the stress block's c) [share of "
        "lw, of the elastic compression depth] (none: not checked).",
    )
    couplingPhi: Share | None = Field(
        default=None, description="φ of the diagonal bars 2 Asd fy sin α (capacity-factor basis)."
    )


class DuctileLevelRules(_Group):
    """Alpha 9 C18c: the groups of one frame level (detailing level) that differ from the
    method's own (limited and moderately ductile frames under codes with several)."""

    beams: DuctileBeamRules | None = None
    columns: DuctileColumnRules | None = None
    joints: DuctileJointRules | None = None
    walls: DuctileWallRules | None = None


class DuctileDetailingRules(_Group):
    """Ductile detailing of moment frames and walls by prescriptive limits (method
    ``ductileDetailing``)."""

    method: Literal["ductileDetailing"] = "ductileDetailing"
    frames: list[str] = Field(description="The seismic systems' frame levels it applies to.")
    beams: DuctileBeamRules
    columns: DuctileColumnRules
    joints: DuctileJointRules
    walls: DuctileWallRules
    # Alpha 9 C18c (AS 3600 / NZS 3101 type).
    basis: Literal["designStrength", "capacityFactor"] = Field(
        default="designStrength",
        description="designStrength: the resistances on fcd, fyd (the pack's partial factors); "
        "capacityFactor: nominal strengths with the strength design's φ (packs without partial "
        "factors).",
    )
    levels: dict[str, DuctileLevelRules] = Field(
        default_factory=dict,
        description="Per frame level of ``frames``: the groups that differ (the others the "
        "method's own, which Design Reinforcement sizes by).",
    )


# ───────── Alpha 9 C5c: the rest of the partial-factor members and their detailing ─────────


class StressFieldRules(_Group):
    """Strut-and-tie models of deep beams, corbels and pile caps on the design strengths
    (method ``designStressLimits``, :mod:`saengine.design.stress_fields`): struts σRd,max =
    ``strutUncracked`` fcd without transverse tension, ``strutCracked`` ν' fcd in cracked
    zones; nodes ``nodeCCC`` / ``nodeCCT`` / ``nodeCTT`` × ν' fcd, ν' = 1 - fck / ``nuDivisor``;
    ties As fyd; the deep beams' web mesh and the corbels' tie, strut angle and links."""

    method: Literal["designStressLimits"] = "designStressLimits"
    nuDivisor: Positive | None = Field(
        default=None, description="ν' = 1 - fck / divisor (alpha 9 C18c: none, ν' = 1)."
    )
    strutUncracked: Positive = Field(description="σRd,max = share × fcd (no transverse tension).")
    strutCracked: Positive = Field(description="σRd,max = share × ν' fcd (cracked zones).")
    nodeCCC: Positive = Field(description="k1 of C-C-C nodes (× ν' fcd).")
    nodeCCT: Positive = Field(description="k2 of C-C-T nodes (× ν' fcd).")
    nodeCTT: Positive = Field(description="k3 of C-T-T nodes (× ν' fcd).")
    minAngle: Positive = Field(description="Least angle between a strut and a tie [°].")
    tieArm: Share = Field(description="The deep members' tie lever arm z = share × d.")
    deepSpanRatio: Positive = Field(description="A beam span is deep when l / h is below this.")
    deepMeshRatio: Share = Field(description="Web mesh As,dbmin = ratio × Ac, each face and way.")
    deepMeshMin: Positive = Field(description="... and at least this [mm²/m], each face and way.")
    deepMeshSpacing: tuple[Positive, Positive] = Field(
        description="Mesh bars at most min(n × b, mm) apart."
    )
    corbelLeverShare: Share = Field(description="Corbel z0 = share × d.")
    corbelTanTheta: tuple[Positive, Positive] = Field(description="tan θ of the corbel's strut.")
    corbelShortShare: Share = Field(
        description="ac <= share × hc: horizontal links; above it, vertical links."
    )
    corbelHorizontalLinks: Share = Field(description="ΣAs,lnk >= k1 As,main (horizontal links).")
    corbelVerticalLinks: Share = Field(description="ΣAs,lnk >= k2 FEd / fyd (vertical links).")
    corbelHorizontalForce: float = Field(
        ge=0, description="HEd at least share × FEd where none is given (SAEngine practice)."
    )
    # Alpha 9 C18c (AS 3600:2018 Chapter 7 type): the strengths on f'c and fsy with capacity
    # reduction factors in place of fcd and fyd (packs without partial factors).
    basis: Literal["designStrength", "capacityFactor"] = Field(
        default="designStrength",
        description="designStrength: fcd and fyd; capacityFactor: phiStrut concreteShare f'c "
        "and phiTie fsy.",
    )
    phiStrut: Share | None = Field(default=None, description="φst of struts and nodes.")
    phiTie: Share | None = Field(default=None, description="φ of ties.")
    concreteShare: Share | None = Field(
        default=None, description="The struts' and nodes' strength × f'c (capacityFactor)."
    )
    bottleStrut: tuple[Positive, Share, Share] | None = Field(
        default=None,
        description="(a, least, most): a cracked (bottle-shaped) strut's βs = 1 / (1 + a cot² θ) "
        "within the range, θ the strut-tie angle, in place of ``strutCracked``.",
    )


class InterfaceShearRules(_Group):
    """Shear at the interface between concretes cast at different times (method
    ``interfaceShear``): vRdi = c fctd + μ σn + ρ fyd μ <= ``limitShare`` ν fcd (c = 0 under
    net tension); c and μ by surface."""

    method: Literal["interfaceShear"] = "interfaceShear"
    surfaces: dict[str, tuple[float, Positive]] = Field(
        description="(c, μ) by surface: verySmooth, smooth, rough, indented."
    )
    surfaceMap: dict[str, str] = Field(
        description="SAEngine's surface names (monolithic, roughened, ...) -> the pack's."
    )
    limitShare: Share = Field(description="vRdi at most share × ν fcd.")


class TieForceRules(_Group):
    """Tying systems for accidental situations (method ``tieForces``): peripheral, internal
    and column ties of cast-in-place floors, the bars at fyk (γs of the accidental situation)."""

    method: Literal["tieForces"] = "tieForces"
    peripheralPerLength: Positive = Field(description="Ftie,per = q1 li [kN/m].")
    peripheralMin: Positive = Field(description="... at least q2 [kN].")
    internalPerLength: Positive = Field(description="Ftie,int = q3 (l1 + l2)/2 [kN/m].")
    internalMin: Positive = Field(description="... at least q4 [kN].")
    columnMin: Positive = Field(description="Edge columns and walls tied for Ftie,col [kN].")
    facadePerLength: Positive = Field(description="Ftie,fac [kN/m of facade].")


class FootingPunchingRules(_Group):
    """Punching of footings and pile caps (method ``reducedPerimeter``): control perimeters
    within ``searchDistance`` d, vRd = CRd,c k (100 ρ fck)^(1/3) 2d/a >= vmin 2d/a, the soil
    pressure inside deducted; the moment by k of c1/c2."""

    method: Literal["reducedPerimeter"] = "reducedPerimeter"
    searchDistance: Positive = Field(description="Perimeters up to this × d from the column.")
    steps: int = Field(ge=2, description="Perimeters tried between d/steps and the limit.")
    momentK: list[tuple[Positive, Share]] = Field(
        description="(c1/c2, k) of the moment transferred by shear, linear between."
    )
    pileInsideShare: Share = Field(
        description="Pile caps: piles within the perimeter by the share of their area inside."
    )


class WallSlendernessRules(_Group):
    """Walls out of their plane (method ``columnAnalogy``): the wall strip as a column, l0 =
    β lw, λ against λlim of the pack's slenderness method; beyond it the nominal curvature
    method; the out-of-plane moment at least NEd e0."""

    method: Literal["columnAnalogy"] = "columnAnalogy"
    effectiveLength: dict[str, Positive] = Field(
        description="β by the wall's restraint: braced (both floors), cantilever."
    )
    stripWidth: Positive = Field(description="Strip width of the check [mm].")


class DetailingRules(_Group):
    """Bends, hooks, compression laps and column splices (method ``barShapes``)."""

    method: Literal["barShapes"] = "barShapes"
    mandrel: list[tuple[Positive, Positive]] = Field(
        description="(bar diameter up to [mm], φm,min / φ) of bars and links."
    )
    bendTail: tuple[Positive, float] = Field(
        description="Bends and hooks of main bars: straight past the bend at least n φ, mm."
    )
    link135: tuple[Positive, Positive] = Field(description="Links' 135° hooks: n φ, mm.")
    link90: tuple[Positive, Positive] = Field(description="Links' 90° bends: n φ, mm.")
    compressionLapEnd: Positive = Field(
        description="Compression laps: a transverse bar outside each end within n φ."
    )
    columnLapShare: Share = Field(
        description="Column bars lapped at one section (α6 of that share)."
    )


def chosen(table: Any, group: str, method: str) -> Any | None:
    """The table's group ``group`` when it is the method ``method`` (else None): the group a
    module of that method reads (C5 and C8 share the group names, by method id)."""
    found = getattr(table, group, None) if table is not None else None
    if found is None:
        return None
    return found if getattr(found, "method", method) == method else None


# ── Alpha 9 C9b: deep beams by the lever arm and corbels by the tie at the root (IS 456 type) ──


class LeverArm(_Group):
    """z = coefficient (l + depthFactor D) for 1 <= l/D <= the deep limit, shortShare × l
    below l/D = 1."""

    coefficient: Positive
    depthFactor: Positive
    shortShare: Positive


class DeepBeamHogging(_Group):
    """The tension steel over the supports of continuous deep beams: a share a (l/D - b) of
    it within ``topZone`` D of the tension face, the rest within ``middleZone`` D each side of
    the mid-depth; at l/D up to ``evenRatio`` spread evenly over ``evenZone`` D."""

    topShare: tuple[Positive, float] = Field(description="(a, b): share = a (l/D - b), 0-1.")
    topZone: Share = Field(description="The top zone's depth / D.")
    middleZone: Share = Field(description="Half the middle zone's depth / D (about mid-depth).")
    evenRatio: Positive = Field(description="At l/D up to this the steel is spread evenly.")
    evenZone: Share = Field(description="... over this × D from the tension face.")


class LeverArmDeepBeamRules(_Group):
    """Deep beams by the lever arm method (method ``leverArm``): a span is deep when l / D is
    below ``spanRatio`` (simply supported or continuous), l the smaller of the centre-to-centre
    span and ``clearFactor`` × the clear span; the tension steel for Mu = fyd As z within
    ``tensionZone`` (a D - b l) of the soffit; the side face steel at least the walls' least
    ratios at most the walls' spacing."""

    method: Literal["leverArm"] = "leverArm"
    spanRatio: dict[str, Positive] = Field(description="l/D below this: deep, by support.")
    clearFactor: Positive = Field(description="l at most this × the clear span.")
    leverArm: dict[str, LeverArm] = Field(description="By support: simple, continuous.")
    tensionZone: tuple[Positive, float] = Field(description="(a, b): the zone a D - b l deep.")
    # Alpha 9 C12: the support (hogging) steel of continuous deep beams; empty: not checked.
    hogging: DeepBeamHogging | None = None


class TieCorbelRules(_Group):
    """Corbels by the tie at the root (method ``rootTie``): av / d at most ``spanRatio``, the
    outer edge at least ``edgeDepth`` × the depth at the face, the tie for Vu av + Nuc (h - d)
    by the design strengths with Nuc at least ``tensionShare`` Vu, shear at the face by the
    tabulated τc enhanced by ``enhancement`` d / av (at most τc,max) with the horizontal links,
    the links Ah at least ``tiesShare`` As within ``tiesDepth`` d of the main bars, the bearing
    at most ``bearing`` × fck."""

    method: Literal["rootTie"] = "rootTie"
    spanRatio: Positive
    edgeDepth: Share
    tensionShare: Share
    tiesShare: Share
    tiesDepth: Share
    bearing: Positive


class CompressionFieldGeneral(_Group):
    """The general variant's constants: β = g1 / (1 + g2 εx) × g3 / (g4 + sze), θ = t1 + t2 εx
    [°], sze = c1 dv / (c2 + ag) at least c3 dv without the least links, else
    ``stirrupSpacingParameter`` [mm]."""

    beta: tuple[Positive, Positive, Positive, Positive]
    theta: tuple[Positive, Positive]
    crackSpacing: tuple[Positive, Positive, Positive]
    stirrupSpacingParameter: Positive


class CompressionFieldShearRules(_Group):
    """Alpha 9 C17: shear by the compression field method with β and θ (method
    ``compressionField``, CSA A23.3-19 11.3 type, :mod:`saengine.design.compression_field_shear`):
    material resistance factors on each term, dv = max(a d, b h)."""

    method: Literal["compressionField"]
    variant: Literal["simplified", "general"] = "simplified"
    phiC: Share = Field(description="φc on the concrete term.")
    phiS: Share = Field(description="φs on the links.")
    depthShares: tuple[Share, Share] = Field(description="dv = max(a d, b h).")
    rootMax: Positive = Field(description="√f'c at most [MPa].")
    betaWithStirrups: Positive = Field(description="β with at least Av,min (simplified).")
    betaNoStirrups: tuple[Positive, Positive] = Field(
        description="β = a / (b + dv) without Av,min (simplified)."
    )
    # Alpha 9 C18 (AS 3600:2018 8.2.4.3: kv = 200 / (1000 + 1.3 dv) <= 0.10).
    betaNoStirrupsMax: Positive | None = Field(
        default=None, description="β without Av,min at most this (simplified); empty: no cap."
    )
    thetaDeg: Positive = Field(description="θ [°] (simplified).")
    general: CompressionFieldGeneral
    strainLimits: tuple[float, Positive] = Field(description="εx within (least, largest).")
    aggregate: Positive = Field(description="ag [mm] of sze where the project gives none.")
    vrMaxShare: Share = Field(description="Vr at most share φc f'c bw dv.")
    minCoefficient: Positive = Field(description="Av,min = c √f'c bw s / fy.")
    fyMax: Positive = Field(description="fy of the links at most [MPa].")
    simplifiedFyMax: Positive = Field(
        description="The simplified variant holds for fy of the bars up to this [MPa]."
    )
    spacing: tuple[Share, Positive] = Field(description="s <= min(share dv, mm).")
    closeSpacing: tuple[Share, Positive] = Field(
        description="s <= min(share dv, mm) where Vf > closeShare λ φc f'c bw dv."
    )
    closeShare: Share


# ── Alpha 9 C18b: punching, torsion and walls by the forms of AS 3600:2018 (9.3, 8.3, 11) ──


class MomentTransferPunchingRules(_Group):
    """Punching by Vuo = u dom fcv reduced for the unbalanced moment (method
    ``momentTransfer``, :mod:`saengine.design.moment_punching`)."""

    method: Literal["momentTransfer"]
    coefficient: Positive = Field(description="fcv = c (1 + 2/βh) √f'c ...")
    maxCoefficient: Positive = Field(description="... at most this × √f'c.")
    momentDivisor: Positive = Field(description="Vu = Vuo / (1 + u M*v / (divisor V* a dom)).")
    rootMax: Positive | None = Field(default=None, description="√f'c at most [MPa] (none: no cap).")


class TorsionInteractionRules(_Group):
    """Torsion of beams by the cracking torque and the interaction with shear (method
    ``torsionInteraction``, :mod:`saengine.design.torsion_interaction`)."""

    method: Literal["torsionInteraction"]
    torsionModulus: Positive = Field(description="Jt = c x² y of a rectangle (x the short side).")
    crackingCoefficient: Positive = Field(description="Tuc = c Jt √f'c.")
    neglectShare: Share = Field(description="T* below share × φ Tuc: torsion neglected.")
    plainInteraction: Positive = Field(
        description="T*/(φ Tuc) + V*/(φ Vuc) up to this: no torsion reinforcement."
    )
    maxCoefficient: Positive = Field(description="Tu.max = c f'c Jt.")
    crushingInteraction: Positive = Field(description="T*/(φ Tu.max) + V*/(φ Vu.max) at most this.")
    cotTheta: Positive = Field(description="cot θv of the links' and bars' terms.")
    linkSpacing: tuple[Share, Positive] = Field(
        description="Closed links at most min(share ut, mm) apart."
    )
    fyMax: Positive = Field(description="fsy.f of the links at most [MPa].")


class SimplifiedWallRules(_Group):
    """Walls by the simplified method (method ``simplifiedWall``,
    :mod:`saengine.design.simplified_walls`): the axial strength per unit length
    φNu = φ (tw - a e - 2 ea) k f'c, ea = Hwe² / (divisor tw), and the in-plane shear by the
    aspect ratio Hw/Lw."""

    method: Literal["simplifiedWall"]
    phi: Share = Field(description="φ of the axial strength.")
    strengthShare: Share = Field(description="k of k f'c.")
    eccentricityFactor: Positive = Field(description="a of a e.")
    additionalDivisor: Positive = Field(description="ea = Hwe² / (divisor tw).")
    minEccentricityShare: Share = Field(description="e at least this × tw.")
    slendernessMax: Positive = Field(description="Hwe / tw at most.")
    restrainedK: Share = Field(description="k of Hwe = k Hw for a wall restrained at both ends.")
    shearDepthShare: Share = Field(description="The shear area 0.8 Lw tw: the share.")
    squatShear: tuple[Positive, Positive] = Field(
        description="Hw/Lw <= 1: Vuc = (a - b Hw/Lw) √f'c × the area."
    )
    slenderShear: tuple[Positive, Positive] = Field(
        description="Hw/Lw > 1: also (a + b / (Hw/Lw - 1)) √f'c × the area ..."
    )
    shearLeast: Positive = Field(description="... at least this √f'c × the area.")
    shearMaxShare: Share = Field(description="Vu at most this × f'c × the area.")
    phiShear: Share = Field(description="φ of the shear.")


# ── Alpha 9 C20b: torsion, cracks, deflection and walls of the GB 50010 type ──


class PlasticTorsionRules(_Group):
    """Torsion of beams on the plastic torsional modulus Wt = b² (3h - b) / 6 (method
    ``plasticModulus``, :mod:`saengine.design.plastic_torsion`): the section V/(b h0) + T/(share
    Wt) at most τc,max of the shear group; no calculation where V/(b h0) + T/Wt <= plainLimit
    fctd; else T <= concreteShare βt fctd Wt + steelFactor √ζ fyv Ast1 Acor / s and V <=
    (shearBase - βt) shearConcrete fctd b h0 + fyv Asv h0 / s with βt = a / (1 + b V Wt / (T b
    h0)) in betaTRange, the longitudinal Astl = ζ fyv Ast1 ucor / (fy s)."""

    method: Literal["plasticModulus"]
    sectionWtShare: Share = Field(description="V/(b h0) + T/(share Wt) <= τc,max.")
    plainLimit: Positive = Field(description="V/(b h0) + T/Wt <= this × fctd: no calculation.")
    concreteShare: Positive = Field(description="Tc = this βt fctd Wt.")
    steelFactor: Positive = Field(description="Ts = this √ζ fyv Ast1 Acor / s.")
    zeta: Positive = Field(description="ζ taken for the design (Astl fy s / (Ast1 fyv ucor)).")
    zetaRange: tuple[Positive, Positive] = Field(description="ζ within (low, high).")
    betaT: tuple[Positive, Positive] = Field(description="βt = a / (1 + b V Wt / (T b h0)).")
    betaTRange: tuple[Share, Share] = Field(description="βt within (low, high).")
    shearBase: Positive = Field(description="Vc = (base - βt) shearConcrete fctd b h0.")
    shearConcrete: Positive
    minLinks: Positive = Field(description="Asv/(b s) at least this × fctd / fyv.")
    minLongitudinal: tuple[Positive, Positive] = Field(
        description="(a, cap): Astl/(b h) at least a √(T/(V b)) fctd/fy, T/(V b) at most cap."
    )


class TensionStiffeningCrackRules(_Group):
    """Crack width with the strain non-uniformity ψ of the bars between cracks (method
    ``effectiveTensionRatio``, :mod:`saengine.design.tension_stiffening`): wmax = αcr ψ σs/Es
    (coverFactor cs + barFactor deq / ρte), ψ = a - b ftk / (ρte σs) in (low, high), ρte = As /
    (areaShare b h) at least rhoTeMin, σs = Mq / (leverArm h0 As), cs within coverRange, Mq of
    the quasi-permanent loads (liveShare of the live load)."""

    method: Literal["effectiveTensionRatio"]
    width: dict[str, Positive] = Field(description="wlim [mm] by exposure (environment) class.")
    memberFactor: Positive = Field(description="αcr of members in bending.")
    coverFactor: Positive
    barFactor: Positive
    coverRange: tuple[Positive, Positive] = Field(description="cs within (low, high) [mm].")
    areaShare: Share = Field(description="Ate = this × b h.")
    rhoTeMin: Share
    psi: tuple[Positive, Positive, Share, Positive] = Field(
        description="(a, b, low, high): ψ = a - b ftk / (ρte σs) within (low, high)."
    )
    leverArm: Share = Field(description="σs = M / (this h0 As).")
    liveShare: Share = Field(description="ψq: the live load's share in Mq.")


class LongTermStiffnessRules(_Group):
    """Deflection by the long-term stiffness B = Bs / θ (method ``longTermStiffness``,
    :mod:`saengine.design.tension_stiffening`): Bs = Es As h0² / (psiFactor ψ + offset +
    ratioFactor αE ρ / (1 + flangeFactor γf')), θ = a - (a - b) ρ'/ρ (``theta``), the analysis's
    deflection under Mq scaled from its E I to B; at most l0 / divisor by the span
    (``limits``), cantilevers on l0 = cantileverFactor × their length."""

    method: Literal["longTermStiffness"]
    psiFactor: Positive
    offset: Positive
    ratioFactor: Positive
    flangeFactor: Positive
    theta: tuple[Positive, Positive] = Field(description="θ at ρ' = 0 and at ρ' = ρ.")
    limits: list[tuple[Positive | None, Positive]] = Field(
        min_length=1, description="(l0 up to [mm], divisor): the first row holding (none: any)."
    )
    cantileverFactor: Positive
    areaShare: Share = Field(description="Ate = this × b h (ψ).")
    rhoTeMin: Share
    psi: tuple[Positive, Positive, Share, Positive] = Field(
        description="(a, b, low, high): ψ = a - b ftk / (ρte σs) within (low, high)."
    )
    leverArm: Share = Field(description="σs = M / (this h0 As).")
    liveShare: Share = Field(description="ψq: the live load's share in Mq.")


class ShearSpanWallRules(_Group):
    """In-plane shear of walls by the shear span ratio λ = M / (V h0) (method
    ``shearSpanRatio``, :mod:`saengine.design.shear_span_walls`): V <= 1/(λ - lambdaOffset)
    (a fctd t h0 + b N Aw/A) + c fyv Ash h0 / sv with (a, b, c) ``terms`` (``seismicTerms`` in
    the earthquake combinations), λ within lambdaRange, N at most axialShare fcd t lw, the
    section V <= sectionShare fcd t h0, h0 = depthShare lw; the web steel ρ at least webMin."""

    method: Literal["shearSpanRatio"]
    terms: tuple[Positive, Positive, Positive]
    seismicTerms: tuple[Positive, Positive, Positive] | None = None
    lambdaOffset: Positive
    lambdaRange: tuple[Positive, Positive]
    axialShare: Share
    sectionShare: Share
    depthShare: Share
    webMin: Share


# ── Alpha 9 C18c: slender columns and anchorage by the forms of AS 3600:2018 (10.4, 13) ──


class BucklingMagnifierRules(_Group):
    """Slender columns by the moment magnifier with Nc from the balanced moment (method
    ``bucklingMagnifier``, :mod:`saengine.design.buckling_magnifier`)."""

    method: Literal["bucklingMagnifier"]
    bracedLimit: Positive = Field(description="Braced columns short up to Le/r = this.")
    unbracedLimit: Positive = Field(description="Unbraced columns short up to Le/r = this.")
    kmBase: Positive = Field(description="km = base + slope M1/M2 (positive single curvature).")
    kmSlope: float
    kmMin: Share = Field(description="km at least this.")
    stiffnessCoefficient: Positive = Field(description="Nc = (π²/Le²) c do φ Mub / (1 + βd).")
    phiBuckling: Share = Field(description="φ of Nc.")
    minEccentricityShare: Share = Field(description="M* at least N* × share D.")
    slendernessMax: Positive = Field(description="Le/r above this: not covered.")
    ultimateStrain: Positive | None = Field(
        default=None, description="εcu of the balanced point (none: the pack's)."
    )


class DevelopmentFactorRules(_Group):
    """Development and laps of deformed bars by the basic length and the factors k1-k3
    (method ``developmentFactors``, :mod:`saengine.design.development_factors`)."""

    method: Literal["developmentFactors"]
    coefficient: Positive = Field(description="Lsy.tb = c k1 k3 fsy db / (k2 √f'c).")
    minCoefficient: Positive = Field(description="... at least this × fsy k1 db.")
    topFactor: Positive = Field(description="k1 of top bars ...")
    topDepth: Positive = Field(description="... with more than this [mm] of concrete below.")
    barFactor: tuple[Positive, Positive] = Field(description="k2 = (a - db) / b.")
    coverFactor: tuple[Positive, Share, Share] = Field(
        description="k3 = 1 - c (cd - db)/db within (least, most)."
    )
    fcMax: Positive = Field(description="f'c of √f'c at most [MPa].")
    hookShare: Share = Field(description="Hooks and cogs: this × Lsy.tb.")
    compression: tuple[Positive, Positive, Positive] = Field(
        description="Lsy.c = a fsy db / √f'c >= b fsy db and mm."
    )
    lapFactor: Positive = Field(description="Tension laps: this × Lsy.t ...")
    lapMinCoefficient: Positive = Field(description="... at least this × k1 db.")
    compressionLap: tuple[Positive, Positive] = Field(
        description="Compression laps: Lsy.c at least n db and mm."
    )


class ConcreteMethodsTable(TableModel):
    """Partial-factor design of reinforced concrete and its detailing (see the module notes)."""

    ultimate: UltimateRules | None = None
    # C8: a group is one method of those its id names (C5's or C8's); alpha 9 C17 the
    # compression field method.
    shear: StrutShearRules | TabulatedShearRules | CompressionFieldShearRules | None = None
    # Alpha 9 C18b: torsionInteraction, momentTransfer (AS 3600 8.3, 9.3 type).
    # Alpha 9 C20b: plasticModulus (GB 50010 6.4 type).
    torsion: (
        StrutTorsionRules
        | EquivalentTorsionRules
        | TorsionInteractionRules
        | PlasticTorsionRules
        | None
    ) = None
    punching: PunchingRules | RootStressPunchingRules | MomentTransferPunchingRules | None = None
    serviceStress: ServiceStressRules | None = None
    # Alpha 9 C20b: effectiveTensionRatio and longTermStiffness (GB 50010 7.1, 7.2 type).
    cracking: CrackRules | CrackWidthRules | TensionStiffeningCrackRules | None = None
    deflection: SpanDepthRules | SpanDepthFactorRules | LongTermStiffnessRules | None = None
    cover: CoverRules | ExposureConditionRules | None = None
    # Alpha 9 C18c: developmentFactors (AS 3600 13.1 type).
    anchorage: AnchorageRules | BondTableRules | DevelopmentFactorRules | None = None
    memberSteel: MemberSteelRules | None = None
    exposureClasses: dict[str, ExposureClass] = Field(default_factory=dict)
    defaultExposure: str | None = None
    # Alpha 9 C5b; C18c bucklingMagnifier (AS 3600 10.4 type).
    slenderness: SlendernessRules | BucklingMagnifierRules | None = None
    parentMethods: list[str] = Field(
        default_factory=list,
        description="Areas (saengine.design.method_selection) a project designs by the default "
        "method instead of the pack's (an override).",
    )
    seismic: SeismicConcreteRules | DuctileDetailingRules | None = None
    # C8: the groups of the tabulated (IS 456 type) methods with no C5 counterpart.
    memberLimits: MemberLimitRules | None = None
    columns: ColumnMethodRules | None = None
    twoWaySlabs: TwoWaySlabRules | None = None
    flatSlabs: FlatSlabRules | None = None
    walls: WallMethodRules | None = None
    footings: FootingMethodRules | None = None
    # Alpha 9 C5c: the deep members, interfaces, ties, footings' punching, slender walls and
    # the bar shapes on the design strengths.
    strutAndTie: StressFieldRules | None = None
    interfaceShear: InterfaceShearRules | None = None
    ties: TieForceRules | None = None
    footingPunching: FootingPunchingRules | None = None
    wallSlenderness: WallSlendernessRules | None = None
    barShapes: DetailingRules | None = None
    # Alpha 9 C9b.
    deepBeams: LeverArmDeepBeamRules | None = None
    corbels: TieCorbelRules | None = None
    # Alpha 9 C18b: walls by the simplified method (AS 3600 11.5, 11.6 type).
    simplifiedWalls: SimplifiedWallRules | None = None
    # Alpha 9 C20b: wall shear by the shear span ratio (GB 50010 6.3.21, 11.7.4 type).
    shearSpanWalls: ShearSpanWallRules | None = None


# ───────────────────────────── geotechnicalMethods ─────────────────────────────


class ActionSet(_Group):
    permanentUnfavourable: Positive
    permanentFavourable: Positive
    variableUnfavourable: Positive


class MaterialSet(_Group):
    tanPhi: Positive
    cohesion: Positive
    undrained: Positive
    unconfined: Positive
    weight: Positive


class SpreadResistanceSet(_Group):
    bearing: Positive
    sliding: Positive
    earth: Positive


class PileResistanceSet(_Group):
    base: Positive
    shaft: Positive
    total: Positive
    tension: Positive


class DesignApproachCombination(_Group):
    actions: str
    materials: str
    resistances: str
    pileMaterials: str | None = Field(default=None, description="Sets of piles if different.")
    pileResistances: str | None = None
    structuralActions: str | None = Field(
        default=None, description="Actions on the structure if different (DA3: A1)."
    )


class BearingRules(_Group):
    """Bearing resistance by the general equation on effective dimensions (method
    ``effectiveArea``)."""

    method: Literal["effectiveArea"] = "effectiveArea"
    nGammaFactor: Positive = Field(description="Nγ = factor (Nq - 1) tan φ'.")
    gammaShape: Positive = Field(description="sγ = 1 - c B'/L'.")
    undrainedShape: Positive = Field(description="sc = 1 + c B'/L' (undrained).")


class SlidingRules(_Group):
    method: Literal["interfaceFriction"] = "interfaceFriction"
    castInPlace: Share = Field(description="δ = share × φ'cv,d for concrete cast against soil.")
    precast: Share
    undrainedShare: Share = Field(description="Rd <= share Vd where water can reach the interface.")


class CorrelationFactors(_Group):
    """ξ by the number of tests (rows (n, ξa, ξb), n ascending)."""

    loadTests: list[tuple[Positive, Positive, Positive]] = Field(description="(n, ξ1, ξ2).")
    groundTests: list[tuple[Positive, Positive, Positive]] = Field(description="(n, ξ3, ξ4).")
    stiffDivisor: Positive = Field(description="ξ ÷ this for stiff structures (ξ1 >= 1).")


class FootingRules(_Group):
    """How spread footings take the soil's strength when the bearing is by limit states (alpha
    9 C5b): the characteristic soil parameters of the founding layer, the drained or undrained
    case, and what the project's footing takes as the characteristic actions."""

    drained: Literal["auto", "drained", "undrained"] = Field(
        default="auto",
        description="auto: undrained where the founding layer gives cu and no φ', both checked "
        "where it gives both.",
    )
    castInPlace: bool = Field(default=True, description="Footings cast against the soil.")
    waterAtInterface: bool = Field(
        default=True, description="Water can reach the base (undrained sliding limit)."
    )
    phiCvShare: Share = Field(
        default=1.0, description="φ'cv,k = share × φ'k where the soil gives no φ'cv."
    )


class EquilibriumSet(_Group):
    """Alpha 9 C5c: the partial factors of static equilibrium (EQU) for overturning."""

    permanentDestabilising: Positive
    permanentStabilising: Positive
    variableDestabilising: Positive


class RetainingRules(_Group):
    """Alpha 9 C5c: retaining walls by limit states (method ``limitStates``,
    :mod:`saengine.substructure.limit_state_retaining`): the earth pressure with the design
    angle of shearing resistance of each combination's M set, sliding, bearing (the base's
    effective width) and overturning by EQU."""

    method: Literal["limitStates"] = "limitStates"
    castInPlace: bool = Field(default=True, description="Base cast against the soil.")


class GeotechnicalMethodsTable(TableModel):
    """Limit state geotechnical design (see the module notes)."""

    designApproach: str = Field(description="The design approach in force (an id of 'approaches').")
    actions: dict[str, ActionSet]
    materials: dict[str, MaterialSet]
    spreadResistances: dict[str, SpreadResistanceSet]
    pileResistances: dict[str, dict[str, PileResistanceSet]] = Field(
        description="By pile kind (driven, bored, cfa), the R sets."
    )
    approaches: dict[str, list[DesignApproachCombination]]
    bearing: BearingRules | None = None
    sliding: SlidingRules | None = None
    correlation: CorrelationFactors | None = None
    # Alpha 9 C5b.
    footings: FootingRules | None = None
    # Alpha 9 C5c.
    equilibrium: EquilibriumSet | None = None
    retaining: RetainingRules | None = None
    parentMethods: list[str] = Field(
        default_factory=list,
        description="Areas (bearing, sliding, piles) a project designs by the default method "
        "instead of the pack's (an override).",
    )
