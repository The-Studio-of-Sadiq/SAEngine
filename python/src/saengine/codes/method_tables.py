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

from typing import Literal

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
    fcmIncrement: Positive = Field(description="fcm = fck + increment [MPa].")
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


class ExposureClass(_Group):
    name: str
    fckMin: Positive | None = Field(default=None, description="Indicative least fck [MPa].")


class ConcreteMethodsTable(TableModel):
    """Partial-factor design of reinforced concrete and its detailing (see the module notes)."""

    ultimate: UltimateRules | None = None
    shear: StrutShearRules | None = None
    torsion: StrutTorsionRules | None = None
    punching: PunchingRules | None = None
    serviceStress: ServiceStressRules | None = None
    cracking: CrackRules | None = None
    deflection: SpanDepthRules | None = None
    cover: CoverRules | None = None
    anchorage: AnchorageRules | None = None
    memberSteel: MemberSteelRules | None = None
    exposureClasses: dict[str, ExposureClass] = Field(default_factory=dict)
    defaultExposure: str | None = None
    seismic: SeismicConcreteRules | None = None


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
