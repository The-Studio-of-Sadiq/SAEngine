"""Table models of the steel methods of alpha 9 track C12 that a pack chooses by id (the
pattern of :mod:`saengine.codes.limit_state_tables`: each group names its method).

Groups of the limit state steel table (``steelLimitState``):

- ``torsion`` (method ``elasticStresses``): torsion of members by the elastic stresses of St.
  Venant and warping torsion against the yield criterion (:mod:`saengine.design.steel.
  torsion_stresses`);
- ``bracing`` (methods ``equivalentImperfection`` and ``forceShare``): the forces of the
  stability bracing of columns and beam compression flanges (:mod:`saengine.design.steel.
  bracing_forces`);
- ``columnSide`` (methods ``effectiveWidth`` and ``dispersion``): a column's web and flange
  under the concentrated flange forces of a beam (:mod:`saengine.design.steel.column_side`);
- ``hssJoints`` (method ``chordFace``): welded hollow section truss joints (:mod:`saengine.
  design.steel.hss_chord_face`).

The links of eccentrically braced frames are a group of the dissipative seismic method
(``steelLimitState.seismic.links``, :mod:`saengine.design.steel.dissipative_links`).

Tables of their own: ``coldFormed`` (cold-formed members, :mod:`saengine.design.steel.
cold_formed`) and ``steelFire`` (steel members in fire, :mod:`saengine.design.steel.fire`).

Every number is the pack's; the pack's VERIFY.md gives each clause.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from saengine.codes.tables import Positive, Share, TableModel, _Group

# ─────────────────────────────── steelLimitState groups ───────────────────────────────


class SteelTorsionStresses(_Group):
    """Torsion of members by elastic stresses (method ``elasticStresses``): the St. Venant and
    warping stresses of the twist along the member (open sections; hollow sections by Bredt's
    shear flow T / (2 A0 t)) added to the stresses of the other forces, checked by the yield
    criterion (σ / (fy / γ))² + 3 (τ / (fy / γ))² <= 1 at the critical points, and the shear
    resistance reduced for the torsional shear stress."""

    method: Literal["elasticStresses"] = "elasticStresses"
    gamma: Positive = Field(description="γ of the resistances (fy / γ).")
    criterion: Positive = Field(
        default=3.0, description="(σ/fd)² + this (τ/fd)² <= 1 (the yield criterion)."
    )
    shearReductionOpen: Positive = Field(
        description="I and H sections: Vpl,T = √(1 - τt / (this fy / (√3 γ))) Vpl."
    )
    neglect: Share = Field(
        description="Torsion is checked when T exceeds this share of the St. Venant torsional "
        "resistance (else neglected)."
    )
    clauses: dict[str, str] = Field(default_factory=dict)


class SteelBracingForces(_Group):
    """The forces the stability bracing must carry.

    ``equivalentImperfection``: the equivalent stabilising force q = Σ NEd 8 (e0 + δq) / L² of
    a bracing system restraining ``m`` members, e0 = αm L / ``bowDivisor``, αm = √(0.5 (1 + 1 /
    m)), δq the bracing deflection (taken at its limit L / ``deflectionDivisor``); beams with
    NEd = MEd / h of the compression flange; the force at a splice or brace point αm NEd /
    ``spliceDivisor``.

    ``forceShare``: each lateral restraint carries ``share`` of the largest force in the
    compression flange of a beam (or of the axial compression of a column)."""

    method: Literal["equivalentImperfection", "forceShare"]
    members: int = Field(default=1, ge=1, description="m: members restrained by one system.")
    bowDivisor: Positive | None = Field(default=None, description="e0 = αm L / this.")
    deflectionDivisor: Positive | None = Field(
        default=None, description="δq taken as L / this (the bracing's deflection limit)."
    )
    spliceDivisor: Positive | None = Field(
        default=None, description="Force at a splice or brace point αm NEd / this."
    )
    share: Share | None = Field(default=None, description="forceShare: restraint force share.")
    clauses: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _complete(self) -> SteelBracingForces:
        if self.method == "equivalentImperfection" and None in (
            self.bowDivisor,
            self.deflectionDivisor,
            self.spliceDivisor,
        ):
            raise ValueError(
                "equivalentImperfection needs bowDivisor, deflectionDivisor, spliceDivisor"
            )
        if self.method == "forceShare" and self.share is None:
            raise ValueError("forceShare needs share")
        return self


class SteelColumnSide(_Group):
    """A column under a beam's concentrated flange forces.

    ``effectiveWidth``: the column web in transverse compression and tension on the effective
    width beff = tfb + 2√2 a + 5 (tfc + s) (s the root radius) with ω of the web shear, kwc of
    the longitudinal stress and ρ of the web's plate buckling; the column flange in transverse
    bending of a welded joint beff = twc + 2 s + ``flangeSpread`` k tfc; the web panel in shear
    ``panelShare`` fy Avc / (√3 γ).

    ``dispersion``: web bearing (b1 + n2) tw fyw / γ with n2 the dispersion through the flange
    and root at 1 : ``bearingSlope``; web buckling (b1 + n1) tw fcd, n1 the dispersion to the
    web's mid-depth at 45° and fcd of the buckling curve ``bucklingCurve`` at λ = ``webSlenderness``
    d / tw; the panel as web shear Av fy / (√3 γ)."""

    method: Literal["effectiveWidth", "dispersion"]
    gamma: Positive = Field(description="γ of yielding (γM0 / γm0).")
    gammaBuckling: Positive | None = Field(default=None, description="γ of buckling.")
    flangeSpread: Positive | None = Field(default=None, description="beff,fc: this k tfc.")
    panelShare: Share | None = Field(default=None, description="Vwp = this fy Avc / (√3 γ).")
    stressLimit: Share | None = Field(
        default=None, description="kwc = 1 while σcom,Ed <= this fy, else 1.7 - σ / fy."
    )
    bearingSlope: Positive | None = Field(default=None, description="n2 = this (tf + r).")
    webSlenderness: Positive | None = Field(default=None, description="λ = this d / tw.")
    bucklingCurve: Literal["a", "b", "c", "d"] | None = None
    alpha: dict[str, Positive] = Field(
        default_factory=dict, description="Imperfection factors of the buckling curves."
    )
    clauses: dict[str, str] = Field(default_factory=dict)


class SteelHssChordFace(_Group):
    """Welded hollow section truss joints by the chord face (method ``chordFace``): CHS chord
    face failure of T/Y, X and gapped K joints with kp and kg, punching shear; RHS chord face
    failure (β <= ``rhsFaceBeta``) with kn, punching shear and brace failure; within the limits
    of validity."""

    method: Literal["chordFace"] = "chordFace"
    gamma: Positive = Field(description="γM5.")
    chsT: tuple[Positive, Positive] = Field(description="T/Y: γ^0.2 kp fy t² (a + b β²) / sinθ.")
    chsX: tuple[Positive, Positive] = Field(description="X: kp fy t² a / ((1 - b β) sinθ).")
    chsK: tuple[Positive, Positive] = Field(description="K: kg kp fy t² (a + b d1/d0) / sinθ.")
    kgFactors: tuple[Positive, Positive, Positive, Positive] = Field(
        description="kg = γ^0.2 (1 + a γ^b / (1 + exp(c g/t0 - d)))."
    )
    kp: Positive = Field(description="kp = 1 - this np (1 + np) (chord in compression).")
    rhsFaceBeta: Share = Field(description="RHS chord face failure while β <= this.")
    rhsK: Positive = Field(description="RHS K: this kn fy t² √γ (b1 + b2 + h1 + h2) / (4 b0).")
    kn: tuple[Positive, Positive] = Field(description="kn = a - b n / β <= 1 (compression).")
    effectiveWidth: Positive = Field(description="beff = this / (b0/t0) (fy0 t0 / fyi ti) bi.")
    limits: dict[str, float] = Field(
        description="Limits of validity: chsBetaMin, chsBetaMax, chsRatioMax (2γ), chsBraceMax "
        "(di/ti), rhsBetaMin, rhsRatioMax (b0/t0), rhsBraceMax (bi/ti)."
    )
    clauses: dict[str, str] = Field(default_factory=dict)


class DissipativeLinks(_Group):
    """The links of eccentrically braced frames (``steelLimitState.seismic.links``): Vp,link =
    (fy / √3) tw (d - tf), Mp,link = fy b tf (d - tf); short e < ``short`` Mp/Vp, long e >
    ``long`` Mp/Vp; the rotation θp at most ``rotationShort`` (short) to ``rotationLong``
    (long, linear between); with NEd / Npl above ``axialLimit`` the reduced Vp,link,r and
    Mp,link,r and the length limit by R; Ω = ``omegaFactor`` Vp,link / VEd (short) or Mp,link
    / MEd (long and intermediate)."""

    short: Positive
    long: Positive
    rotationShort: Positive
    rotationLong: Positive
    axialLimit: Share
    lengthRatio: Positive = Field(description="R = NEd tw (d - 2tf) / (VEd A) limit.")
    lengthA: Positive = Field(description="e <= (a - b R) short Mp/Vp when R >= lengthRatio.")
    lengthB: Positive
    omegaFactor: Positive
    clauses: dict[str, str] = Field(default_factory=dict)


# ───────────────────────────────────── coldFormed ─────────────────────────────────────


class ColdFormedEffectiveWidth(_Group):
    """Effective widths of the plate elements.

    ``winter``: ρ = (1 - a/λ)/λ for λ > b, λ = c / √k (w/t) √(f/E) (``factors`` [a, b, c]).
    ``plateSlenderness``: λp = (b/t) / (c ε √kσ), internal ρ = (λp - a (3 + ψ)) / λp²,
    outstand ρ = (λp - b) / λp² (``factors`` [a, b, c, εref]).
    ``limitingWidth``: (w/t)lim = a / √f; above it be/t = b / √f (1 - c / ((w/t) √f)), f in
    the unit of ``stressUnit`` [MPa per unit] (``factors`` [a, b, c])."""

    method: Literal["winter", "plateSlenderness", "limitingWidth"]
    factors: list[float] = Field(min_length=3)
    kInternal: Positive = Field(description="k (kσ) of a stiffened element in compression.")
    kOutstand: Positive = Field(description="k of an unstiffened (outstand) element.")
    stressUnit: Positive = Field(default=1.0, description="MPa per unit of f (limitingWidth).")


class ColdFormedDistortional(_Group):
    """Distortional buckling of the lipped flanges. The critical stress of every method: the
    edge stiffener (flange share and lip) as a strut on the elastic spring K of the web and
    flange plates, σcr,d = 2 √(K E Is) / As.

    ``reductionCurve``: χd = 1 for λd <= a, b - c λd up to λd < d, else e / λd (``factors``).
    ``directStrength``: compression Pn = Py for λd <= a, else (1 - b (Pcr/Py)^c)(Pcr/Py)^c Py;
    flexure Mn = My for λd <= d, else (1 - e (Mcr/My)^f)(Mcr/My)^f My (``factors`` [a..f]).
    ``lipAdequacy``: the lip at least dmin = a t ⁶√((w/t)² - b / fy) and at least c t (f in
    ``stressUnit``); a lip shorter than that leaves the flange unstiffened."""

    method: Literal["reductionCurve", "directStrength", "lipAdequacy"]
    factors: list[float] = Field(min_length=3)
    poisson: Positive = Field(default=0.3)
    stressUnit: Positive = Field(default=1.0, description="MPa per unit (lipAdequacy).")


class ColdFormedResistance(_Group):
    """Member resistances. ``format``: ``lrfd`` (φ Rn), ``partialFactors`` (R / γ) or
    ``allowableStress`` (permissible stresses against the working forces, the factored ones over
    ``loadFactor``). ``factors``: φ (lrfd) or γ (partialFactors) by ``tension``,
    ``compression``, ``flexure``, ``shear``; ``allowableStress``: the safety factors' inverse
    shares ``tension``, ``flexure``, ``shear`` (× fy) and ``compression`` (12/23)."""

    format: Literal["lrfd", "partialFactors", "allowableStress"]
    factors: dict[str, Positive]
    loadFactor: Positive = Field(default=1.0, description="allowableStress: factored / working.")
    bucklingCurve: Literal["aisc", "a", "b", "c", "d", "allowable"] = Field(
        description="Flexural buckling: the 0.658^λ² / 0.877 curve (aisc), an imperfection "
        "curve (a-d) or the parabola of the permissible stress (allowable)."
    )
    alpha: dict[str, Positive] = Field(default_factory=dict)
    interaction: Literal["linear", "power", "amplified"] = Field(
        description="linear: P/Pa + Mx/Max + My/May <= 1; power: (N/Nb)^e + (M/Mb)^e <= 1; "
        "amplified: fa/Fa + Cm fb / ((1 - fa/F'e) Fb) <= 1."
    )
    exponent: Positive = Field(default=1.0, description="power: the exponent.")
    shearLimits: tuple[Positive, Positive] = Field(
        description="Web shear: yielding while h/t <= a √(E kv / fy), inelastic up to b √(...)."
    )
    shearYield: Positive = Field(description="Fv = this fy while yielding.")


class ColdFormedTable(TableModel):
    """Cold-formed steel members of lipped channels and lipped Z sections (module
    :mod:`saengine.design.steel.cold_formed`): the effective widths of their plates,
    distortional buckling, the member resistances in tension, compression, flexure, shear and
    combined, every value the pack's."""

    method: Literal["effectiveSection"] = "effectiveSection"
    E: Positive = Field(description="Modulus of elasticity [MPa].")
    G: Positive = Field(description="Shear modulus [MPa].")
    effectiveWidth: ColdFormedEffectiveWidth
    distortional: ColdFormedDistortional
    resistance: ColdFormedResistance
    thicknessMax: Positive = Field(description="Largest wall thickness covered [mm].")
    widthRatioMax: dict[str, Positive] = Field(
        description="Largest w/t of the web, flange and lip ('web', 'flange', 'lip')."
    )


# ───────────────────────────────────── steelFire ─────────────────────────────────────


class SteelFireRetention(_Group):
    """Strength and stiffness of steel at temperature θ [°C].

    ``tabulated``: ky,θ and kE,θ at the temperatures ``points`` (linear between).
    ``formula``: ky = 1 to ``yieldFlat`` °C, then (``yieldZero`` - θ) / ``yieldSpan``; kE = 1 +
    θ / (``modulusA`` ln(θ / ``modulusB``)) to ``modulusSplit`` °C, then ``modulusC`` (1 - θ /
    1000) / (θ - ``modulusD``)."""

    method: Literal["tabulated", "formula"]
    points: list[tuple[float, float, float]] = Field(
        default_factory=list, description="tabulated: [θ °C, ky, kE] rows, rising θ."
    )
    yieldFlat: Positive | None = None
    yieldZero: Positive | None = None
    yieldSpan: Positive | None = None
    modulusA: Positive | None = None
    modulusB: Positive | None = None
    modulusSplit: Positive | None = None
    modulusC: Positive | None = None
    modulusD: Positive | None = None

    @model_validator(mode="after")
    def _complete(self) -> SteelFireRetention:
        if self.method == "tabulated" and len(self.points) < 2:
            raise ValueError("tabulated retention needs at least two points")
        if self.method == "formula" and None in (
            self.yieldFlat, self.yieldZero, self.yieldSpan, self.modulusA, self.modulusB,
            self.modulusSplit, self.modulusC, self.modulusD,
        ):  # fmt: skip
            raise ValueError("formula retention needs every yield and modulus constant")
        return self


class SteelFireCritical(_Group):
    """The critical (limiting) temperature at the load ratio μ0.

    ``eurocode``: θcr = a ln(1 / (b μ0^c) - 1) + d (``factors`` [a, b, c, d]);
    ``linear``: θl = a - b μ0 (``factors`` [a, b]);
    ``inverseRetention``: the temperature at which ky,θ = μ0."""

    method: Literal["eurocode", "linear", "inverseRetention"]
    factors: list[float] = Field(default_factory=list)
    floor: float = Field(default=20.0, description="Lowest critical temperature reported [°C].")


class SteelFireHeating(_Group):
    """Steel temperature in the standard fire by the lumped heat capacity of the section:
    unprotected Δθ = ksh (Am/V) hnet Δt / (ca ρa), protected by the insulation's λp, cp, ρp,
    dp; the gas by θg = 20 + a log10(b t + 1) (t in minutes, ``curve`` [a, b])."""

    method: Literal["lumpedCapacitance"] = "lumpedCapacitance"
    curve: tuple[Positive, Positive]
    convection: Positive = Field(description="αc [W/m²K].")
    emissivity: Share = Field(description="εm of the steel surface (× εf of the fire).")
    fireEmissivity: Share = Field(default=1.0)
    specificHeat: Positive = Field(description="ca [J/kgK] (constant).")
    density: Positive = Field(description="ρa [kg/m³].")
    shadow: bool = Field(
        description="I-sections: the shadow effect ksh = shadowFactor [Am/V]b / [Am/V] (else 1)."
    )
    shadowFactor: Positive = Field(default=1.0, description="ksh = this [Am/V]b / [Am/V].")
    step: Positive = Field(default=5.0, description="Δt [s].")


class SteelFireProtection(_Group):
    """The fire protection of the steel members (a project value; thickness 0: unprotected)."""

    thickness: float = Field(default=0.0, ge=0, description="dp [mm].")
    conductivity: Positive = Field(default=0.12, description="λp [W/mK].")
    specificHeat: Positive = Field(default=1200.0, description="cp [J/kgK].")
    density: Positive = Field(default=300.0, description="ρp [kg/m³].")
    encasement: Literal["contour", "box"] = "contour"


class SteelFireTable(TableModel):
    """Steel members in the standard fire by the simple method (module :mod:`saengine.design.
    steel.fire`): the steel temperature at the member's fire rating, the critical temperature
    at its load ratio μ0 = ``loadRatio`` × the ambient utilisation, and compression members by
    their buckling resistance at temperature."""

    retention: SteelFireRetention
    critical: SteelFireCritical
    heating: SteelFireHeating
    protection: SteelFireProtection = Field(default_factory=SteelFireProtection)
    loadRatio: Share = Field(description="ηfi: the fire design forces over the ambient ones.")
    compression: Literal["eurocode", "aisc", "critical"] = Field(
        description="Compression members: χfi with α = a √(235/fy) (eurocode), 0.42^√(Fy(T)/"
        "Fe(T)) (aisc) or the critical temperature (critical)."
    )
    alphaFactor: Positive = Field(default=0.65, description="eurocode: α = this √(235 / fy).")
    aiscBase: Positive = Field(default=0.42, description="aisc: Fn = this^√(Fy(T)/Fe(T)) Fy(T).")
    gammaFire: Positive = Field(default=1.0, description="γM,fi (or 1/φ in fire).")
