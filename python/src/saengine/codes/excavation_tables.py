"""Table model of excavation support and shoring (alpha 9 track P1).

The pack's ``excavationSupport`` table holds the method ids and the values of the staged
analysis of an excavation's embedded wall and of its supports
(:mod:`saengine.substructure.excavation_support`); a pack without it does not analyse staged
excavations (the embedded wall's limit equilibrium of the ``embeddedWalls`` table, alpha 9 P7,
still runs). The default pack's BNBC 2020 asks for retained excavation sides and names sheet
piles with tie-back anchors (Part 6 Sec 3.12, 3.16) without a method: every method and value
there is SAEngine practice, and the report says so.

- ``analysis``: ``subgradeReaction``, the wall a beam on elastic-plastic soil springs per metre
  run (subgrade reaction, bounded by the active and passive pressures of each side), stage by
  stage; ``analyses``: the strengths of the soil (``characteristic``, or ``design`` by the
  ``embeddedWalls`` method's partial factors) and the factor on the effects of each run;
- ``earthPressure``: Rankine or Coulomb active and passive coefficients with the wall friction
  δ/φ' of each side, the least equivalent fluid pressure behind, the strip loads of adjoining
  footings (Boussinesq) times a factor;
- ``subgrade``: the modulus of subgrade reaction (``schmitt``: kh = a Eoed^(4/3) / EI^(1/3);
  ``tabulated``: by φ' and cu), the soil modulus correlations, the stiffness of reinforced
  concrete walls, the passive width of soldier piles;
- ``struts``: temperature, self weight, effective length and the waler coefficients;
- ``anchors``: the standard's factors on the tendon and the grout-ground bond (temporary and
  permanent), the proof and lock-off loads, the least free and fixed lengths, the bond
  stresses;
- ``heave``: the basal heave of a soft base (``bjerrumEide``) and the piping at the toe
  (``harrExit``), each with its factor of safety; ``deflectionShare`` the reported limit of the
  wall's deflection (share of the excavation depth).

Every number is the pack's; the pack's VERIFY.md gives each value's source.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from saengine.codes.tables import Positive, Share, TableModel, _Group, _Row


class SupportAnalysis(_Row):
    """One run of the staged analysis: the soil's strengths and the factor on its effects."""

    name: str = Field(description="Shown in the report, e.g. 'Characteristic × 1.6'.")
    strengths: Literal["characteristic", "design"] = Field(
        description="characteristic: the soil as given; design: the strengths divided by the "
        "embeddedWalls method's partial factors (its materials set)."
    )
    effectFactor: Positive | None = Field(
        default=None,
        description="On the moments, shears and support forces of the run; empty: the pack's "
        "factor on earth pressure (foundations.retainingWall.hFactor or γG of A1).",
    )


class SupportEarthPressure(_Group):
    """The earth pressures of the staged analysis (horizontal components)."""

    activeMethod: Literal["rankine", "coulomb"]
    passiveMethod: Literal["rankine", "coulomb"]
    activeFriction: float = Field(ge=0, le=1, description="δ / φ' behind the wall (active).")
    passiveFriction: float = Field(ge=0, le=1, description="δ / φ' in front (passive).")
    minimumFluid: float = Field(
        ge=0, description="Least active pressure behind = this × z [kN/m³] (cohesive soil)."
    )
    stripLoad: Literal["boussinesq"] = "boussinesq"
    stripFactor: Positive = Field(description="On the elastic strip-load pressure.")


class SupportSubgrade(_Group):
    """The modulus of subgrade reaction kh of the soil springs."""

    method: Literal["schmitt", "tabulated"]
    schmittCoefficient: Positive = Field(description="a of kh = a Eoed^(4/3) / EI^(1/3).")
    poisson: float = Field(ge=0, lt=0.5, description="ν: Eoed = E (1-ν) / ((1+ν)(1-2ν)).")
    granularModulus: list[tuple[float, float]] = Field(
        min_length=1, description="(φ' [°], E [MPa]) of granular soil, linear between."
    )
    cohesiveModulus: Positive = Field(description="E = this × cu of cohesive soil.")
    tabulatedGranular: list[tuple[float, float]] = Field(
        min_length=1, description="tabulated: (φ' [°], kh [MN/m³]), linear between."
    )
    tabulatedCohesive: Positive = Field(description="tabulated: kh = this × cu [1/m].")
    concreteStiffness: Share = Field(description="EI of reinforced concrete walls × this.")
    soldierPassiveWidth: Positive = Field(
        description="Soldier piles: below the dig level the soil acts on this × the flange "
        "width (at most the spacing)."
    )


class SupportStruts(_Group):
    """Struts, rakers and walers (steel)."""

    temperatureRange: float = Field(ge=0, description="ΔT of the strut [°C].")
    temperatureRestraint: float = Field(
        ge=0, le=1, description="Share of the free expansion the wall and soil restrain."
    )
    expansion: Positive = Field(description="Coefficient of thermal expansion [1/°C].")
    temperatureFactor: float = Field(ge=0, description="Load factor on the temperature force.")
    selfWeightFactor: Positive = Field(description="Load factor on the strut's self weight.")
    effectiveLength: Positive = Field(description="K of the strut's buckling length.")
    symmetricShare: Share = Field(
        description="Share of a strut's length that shortens under the wall's push (0.5: a "
        "symmetric excavation, the strut's middle stays put)."
    )
    walerMoment: Positive = Field(description="Waler M = this × w s² (continuous over props).")
    walerShear: Positive = Field(description="Waler V = this × w s.")


class SupportAnchors(_Group):
    """Ground anchors: the standard's factors, test and lock-off loads and bond stresses."""

    standard: str = Field(description="Shown in the report, e.g. 'BS 8081'.")
    tendonFactor: Positive = Field(description="Temporary: working load ≤ fpk A / this.")
    groundFactor: Positive = Field(description="Temporary: π D L τ ≥ this × working load.")
    permanentTendonFactor: Positive
    permanentGroundFactor: Positive
    proofFactor: Positive = Field(description="Temporary: proof (acceptance) load / working.")
    permanentProofFactor: Positive
    lockOffShare: Positive = Field(description="Lock-off load / working load.")
    testTendonLimit: Share = Field(description="Proof load ≤ this × fpk A.")
    freeLengthMin: Positive = Field(description="Least free (tendon) length [m].")
    fixedLengthMin: Positive = Field(description="Least fixed (bond) length [m].")
    fixedLengthMax: Positive = Field(description="Longest fixed length counted [m].")
    wedgeClearance: float = Field(ge=0, description="Beyond the active wedge: this × H ...")
    wedgeClearanceMin: float = Field(ge=0, description="... at least this [m].")
    groutDiameter: Positive = Field(description="Of the fixed length when none is given [mm].")
    bondGranular: list[tuple[float, float]] = Field(
        min_length=1, description="(φ' [°], ultimate grout-ground bond τ [kPa]), linear between."
    )
    bondCohesive: Share = Field(description="Cohesive soil: τ = this × cu ...")
    bondCohesiveMax: Positive = Field(description="... at most this [kPa].")
    stiffnessLength: Share = Field(
        description="Apparent free length = free length + this × fixed length (stiffness)."
    )


class SupportHeave(_Group):
    """The base of the excavation: basal heave of a soft base, piping at the toe."""

    basal: Literal["bjerrumEide"] = "bjerrumEide"
    basalFactor: Positive = Field(description="Least factor of safety on basal heave.")
    basalNcMax: Positive = Field(description="Nc of a deep square excavation (H/B ≥ 2.5).")
    piping: Literal["harrExit"] = "harrExit"
    pipingFactor: Positive = Field(description="icr / iexit at least this.")


class ExcavationSupportTable(TableModel):
    """Staged analysis of embedded walls and the design of their supports (see the module)."""

    analysis: Literal["subgradeReaction"]
    analyses: list[SupportAnalysis] = Field(min_length=1)
    earthPressure: SupportEarthPressure
    subgrade: SupportSubgrade
    struts: SupportStruts
    anchors: SupportAnchors
    heave: SupportHeave
    deflectionShare: Share = Field(description="Reported deflection limit: this × H.")

    @model_validator(mode="after")
    def _lengths(self) -> ExcavationSupportTable:
        if self.anchors.fixedLengthMin > self.anchors.fixedLengthMax:
            raise ValueError("excavationSupport: anchors.fixedLengthMin > fixedLengthMax")
        return self


__all__ = [
    "ExcavationSupportTable",
    "SupportAnalysis",
    "SupportAnchors",
    "SupportEarthPressure",
    "SupportHeave",
    "SupportStruts",
    "SupportSubgrade",
]
