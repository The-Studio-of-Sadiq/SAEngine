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

from saengine.codes.tables import Positive, Share, TableModel, _Group

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
    stressBlock: Literal["rectangular", "parabolaRectangle"] = "rectangular"
    gammaC: Positive
    gammaS: Positive
    gammaCAccidental: Positive | None = None
    gammaSAccidental: Positive | None = None
    alphaCC: Share
    alphaCT: Share
    steelE: Positive = Field(description="Es [MPa].")
    strengthClasses: list[tuple[Positive, Positive]] = Field(
        description="(fck, fck,cube) [MPa] of the strength classes."
    )
    relations: StrengthRelations
    eccentricityDivisor: Positive = Field(description="e0 = h / divisor, at least eccentricityMin.")
    eccentricityMin: Positive = Field(description="[mm]")
    pureCompressionStrain: Literal["epsC2", "epsC3"] = Field(
        default="epsC2", description="The strain limit of a section under axial compression."
    )
    #: Alpha 9 C5b: (k1, k2) of the redistribution rule δ >= k1 + k2 xu/d; with δ = 1 the
    #: limit xu/d <= (1 - k1)/k2 of slabs and stairs designed from the elastic analysis.
    neutralAxisLimit: tuple[Share, Positive] | None = None
    # C8 (IS 456): grade names, the axial cap by shares of fck and fy, e0 with the length.
    gradePrefix: str | None = Field(
        default=None, description="Grades named prefix + fck ('M25'); none: 'C fck/fck,cube'."
    )
    axialShares: tuple[Positive, Positive] | None = Field(
        default=None,
        description="NRd = a fck Ac + b fy As in place of the stress block's (none: that).",
    )
    eccentricityLengthDivisor: Positive | None = Field(
        default=None, description="e0 = l / this + h / eccentricityDivisor (none: h only)."
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
    cement: Positive = Field(description="Least cement content [kg/m³].")
    waterCement: Share = Field(description="Largest free water-cement ratio.")
    grade: Positive = Field(description="Least grade fck [MPa].")


class ExposureConditionRules(_Group):
    """Cover and mix limits by exposure condition (method ``exposureCondition``)."""

    method: Literal["exposureCondition"] = "exposureCondition"
    conditions: dict[str, ExposureCondition]
    columnCover: Positive = Field(description="Longitudinal bars of columns at least [mm].")
    footingCover: Positive = Field(description="Footings at least [mm].")
    smallBarReduction: tuple[Positive, Positive] = Field(
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
    neutralAxisStrain: Positive = Field(
        description="xu,max: the bars' strain at least fyd/Es + this (limiting depth)."
    )


class SlendernessRule(_Group):
    method: Literal["additionalMoment"] = "additionalMoment"
    limit: Positive = Field(description="Short when lex / D is at most this.")
    divisor: Positive = Field(description="Ma = Pu D / divisor (lex / D)².")
    maxRatio: Positive = Field(description="lex / D at most this (unsupported length).")


class BiaxialRule(_Group):
    method: Literal["loadContour", "surface"] = "loadContour"
    alphaN: list[tuple[Share, Positive]] = Field(description="(Pu / Puz, αn), linear between.")
    puzShares: tuple[Positive, Positive] = Field(description="Puz = a fck Ac + b fy Asc.")


class ColumnMethodRules(_Group):
    """Columns: slenderness (``additionalMoment``) and biaxial bending (``loadContour``, or
    the interaction ``surface``)."""

    slenderness: SlendernessRule
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


class DuctileJointRules(_Group):
    gamma: dict[str, Positive] = Field(description="Vj <= γ √fck Aej by confinement.")
    overstrength: Positive
    widthShare: Share = Field(description="bj = min(bb + share × hc, bc).")


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


class DuctileDetailingRules(_Group):
    """Ductile detailing of moment frames and walls by prescriptive limits (method
    ``ductileDetailing``)."""

    method: Literal["ductileDetailing"] = "ductileDetailing"
    frames: list[str] = Field(description="The seismic systems' frame levels it applies to.")
    beams: DuctileBeamRules
    columns: DuctileColumnRules
    joints: DuctileJointRules
    walls: DuctileWallRules


# ───────── Alpha 9 C5c: the rest of the partial-factor members and their detailing ─────────


class StressFieldRules(_Group):
    """Strut-and-tie models of deep beams, corbels and pile caps on the design strengths
    (method ``designStressLimits``, :mod:`saengine.design.stress_fields`): struts σRd,max =
    ``strutUncracked`` fcd without transverse tension, ``strutCracked`` ν' fcd in cracked
    zones; nodes ``nodeCCC`` / ``nodeCCT`` / ``nodeCTT`` × ν' fcd, ν' = 1 - fck / ``nuDivisor``;
    ties As fyd; the deep beams' web mesh and the corbels' tie, strut angle and links."""

    method: Literal["designStressLimits"] = "designStressLimits"
    nuDivisor: Positive = Field(description="ν' = 1 - fck / divisor.")
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


class ConcreteMethodsTable(TableModel):
    """Partial-factor design of reinforced concrete and its detailing (see the module notes)."""

    ultimate: UltimateRules | None = None
    # C8: a group is one method of those its id names (C5's or C8's).
    shear: StrutShearRules | TabulatedShearRules | None = None
    torsion: StrutTorsionRules | EquivalentTorsionRules | None = None
    punching: PunchingRules | RootStressPunchingRules | None = None
    serviceStress: ServiceStressRules | None = None
    cracking: CrackRules | CrackWidthRules | None = None
    deflection: SpanDepthRules | SpanDepthFactorRules | None = None
    cover: CoverRules | ExposureConditionRules | None = None
    anchorage: AnchorageRules | BondTableRules | None = None
    memberSteel: MemberSteelRules | None = None
    exposureClasses: dict[str, ExposureClass] = Field(default_factory=dict)
    defaultExposure: str | None = None
    # Alpha 9 C5b.
    slenderness: SlendernessRules | None = None
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
