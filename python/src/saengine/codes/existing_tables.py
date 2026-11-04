"""Table model of the assessment and retrofit of existing buildings (alpha 9 track P4).

The pack's ``existing`` table holds the values and method ids of
:mod:`saengine.fem.existing_building`; a pack without it does not assess existing buildings
(the project's ``analysis.existingBuilding`` is then reported as not covered):

- ``knowledge``: the knowledge levels with their knowledge factor κ on the capacities (ASCE 41
  type) and their confidence factor CF on the strengths (EN 1998-3 type), and the procedures
  each level permits;
- ``strengths``: how the as-built strengths follow from the tests (mean, lower bound = mean -
  k·σ, the expected / lower-bound factors of strengths taken from the drawings) and which value
  the analysis model, the deformation-controlled (ductile) and the force-controlled (brittle)
  checks use;
- ``linear``: the linear procedure, method ``mFactor`` (deformation-controlled actions m·κ·QCE
  against QUD with the unreduced seismic forces times C1·C2·Cm, force-controlled κ·QCL against
  QUF) or ``chordRotation`` (ductile members' chord rotation from the linear analysis against
  θy and shares of θum, brittle members' shear against the cyclic shear strength);
- ``nonlinear``: what the assessment changes in the pushover hinges of the pack's ``pushover``
  table (κ on the limits, CF on the strengths of θum, the shear check);
- ``shear``: the shear strength of existing members by method ``columnDuctility`` (ACI 318 for
  beams, the column equation with the ductility factor k) or ``cyclicDegradation`` (the cyclic
  shear strength degrading with the plastic ductility);
- ``jacketing``: the monolithic factors of concrete jackets;
- ``frp``: externally bonded FRP by method ``aci440`` or ``en1998`` (confinement, shear, flexure);
- ``tier1``: a screening checklist (statements the engineer answers C / NC / N/A / U).

Every number is the pack's; the pack's VERIFY.md gives each value's source.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from saengine.codes.tables import (
    ChordRotationCapacity,
    HazardLevel,
    HingeAssignment,
    HingeRow,
    PerformanceLevel,
    Positive,
    Share,
    TableModel,
    _Group,
    _Row,
)


class KnowledgeLevel(_Row):
    """One knowledge level: how much is known of the building as built."""

    id: str = Field(description="Short id (minimum, usual, KL1 ...).")
    label: str = Field(default="", description="Shown in the settings and the results.")
    capacityFactor: Share = Field(
        default=1.0, description="Knowledge factor κ on the component capacities (1: none)."
    )
    confidenceFactor: float = Field(
        default=1.0, ge=1.0, description="Confidence factor CF the strengths are divided by."
    )
    procedures: list[Literal["linear", "nonlinear"]] = Field(
        default_factory=lambda: ["linear", "nonlinear"],
        description="The procedures this level permits.",
    )
    note: str = ""


class StrengthUse(_Row):
    """Which strength of the materials a use takes."""

    value: Literal["expected", "lowerBound", "mean"] = Field(
        description="expected: the mean of the tests (else the specified × the expected "
        "factor); lowerBound: mean - k·σ (else the specified × the lower-bound factor); mean: "
        "the mean of the tests (else the specified)."
    )
    divideByConfidence: bool = Field(
        default=False, description="Divide by the knowledge level's confidence factor CF."
    )
    concreteDivisor: Positive = Field(
        default=1.0, description="A further divisor on the concrete strength (γc of brittle)."
    )
    steelDivisor: Positive = Field(
        default=1.0, description="A further divisor on the steel strength (γs of brittle)."
    )


class Strengths(_Group):
    """The as-built strengths from the tests or the drawings."""

    analysis: StrengthUse = Field(description="The analysis model's materials.")
    deformation: StrengthUse = Field(
        description="The capacities of deformation-controlled (ductile) actions."
    )
    force: StrengthUse = Field(description="The capacities of force-controlled (brittle) actions.")
    lowerBoundSigma: float = Field(
        ge=0, description="The lower bound from tests: mean - this × the standard deviation."
    )
    expectedFactors: dict[str, Positive] = Field(
        description="Expected over lower-bound strength without tests, by material kind "
        "(concrete, rebar, steel)."
    )
    lowerBoundFactors: dict[str, Positive] = Field(
        default_factory=dict,
        description="Lower-bound over specified strength without tests, by kind (empty: 1).",
    )
    covLimit: Share | None = Field(
        default=None,
        description="A coefficient of variation of the tests above this asks for more tests.",
    )
    minTests: int = Field(default=1, ge=1, description="Fewer tests of a material: a note.")
    calibrated: list[str] = Field(
        default_factory=lambda: ["core", "tensile"],
        description="Test kinds that count as they are; the others (rebound, ultrasonic pulse "
        "velocity) count only with a calibration factor to cores.",
    )


class C1C2Band(_Row):
    """C1·C2 of the linear procedure for periods up to ``periodTo``: ``values`` [[m from, C1·C2],
    ...] by the largest m-factor of the members, in rising order."""

    periodTo: Positive | None = Field(default=None, description="[s]; empty: any longer period.")
    values: list[tuple[float, Positive]] = Field(min_length=1)


class YieldRotation(_Row):
    """θy = φy·LV/3 + a·(1 + b·h/LV) + c·φy·db·fy/√fc (MPa), φy = ``curvature``·(fy/Es)/h."""

    curvature: Positive = Field(description="φy·h/εy of a rectangular section.")
    shear: float = Field(ge=0, description="a: the shear deformation term.")
    shearDepth: float = Field(ge=0, description="b: its dependence on h/LV.")
    slip: float = Field(ge=0, description="c: the bar slip term.")


class MFactorComponent(_Row):
    """The m-factors of one kind of component: rows as the pushover hinge tables'
    (:class:`saengine.codes.tables.HingeRow`), ``limits`` the m per performance level."""

    variables: list[str] = Field(default_factory=list, description="Numeric variables.")
    rows: list[HingeRow] = Field(min_length=1)
    note: str = ""


class LinearAssessment(_Row):
    """The linear procedure of the assessment."""

    method: Literal["mFactor", "chordRotation"]
    levels: list[PerformanceLevel] = Field(min_length=1)
    hazards: list[HazardLevel] = Field(
        min_length=1,
        description="Hazard levels checked, the first the main one; spectrumScale: the "
        "hazard's spectrum over the design spectrum of the analysis.",
    )
    c1c2: list[C1C2Band] = Field(
        default_factory=list, description="mFactor: C1·C2 by period and largest m (empty: 1)."
    )
    massFactor: Positive = Field(default=1.0, description="Cm on the seismic forces.")
    gravityUpper: Positive = Field(description="QG = this × (QD + liveShare·QL).")
    gravityLower: Positive = Field(description="QG = this × QD.")
    liveShare: float = Field(ge=0, le=1, description="Share of the live load in QG.")
    forceDivisor: Positive = Field(
        default=1.0, description="J of the force-controlled demands QUF = QG ± QE/(C1·C2·J)."
    )
    biaxialExponent: Positive = Field(
        default=1.0,
        description="Columns in two-way bending: (DCRx^α + DCRy^α)^(1/α) with this α.",
    )
    variables: HingeAssignment | None = Field(
        default=None, description="mFactor: the values the table variables are worked out with."
    )
    mFactors: dict[str, MFactorComponent] = Field(
        default_factory=dict,
        description="mFactor: by component (rcBeam, rcColumn, steelBeam, steelColumn).",
    )
    chordRotation: ChordRotationCapacity | None = Field(
        default=None, description="chordRotation: θum of the members."
    )
    yieldRotation: YieldRotation | None = Field(
        default=None, description="chordRotation: θy of the members."
    )
    note: str = ""

    @model_validator(mode="after")
    def _method_values(self) -> LinearAssessment:
        if self.method == "mFactor" and (self.variables is None or not self.mFactors):
            raise ValueError("method mFactor needs variables and mFactors")
        if self.method == "chordRotation" and (
            self.chordRotation is None or self.yieldRotation is None
        ):
            raise ValueError("method chordRotation needs chordRotation and yieldRotation")
        return self


class NonlinearAssessment(_Row):
    """What the assessment changes in the pushover hinges (``pushover.hinges``)."""

    capacityFactor: bool = Field(description="κ multiplies the hinges' deformation limits.")
    confidenceFactor: bool = Field(
        description="θum with the strengths divided by CF (chordRotationCapacity hinges)."
    )
    shearCheck: bool = Field(
        default=False, description="Check the hinges' shear against the pack's shear method."
    )
    note: str = ""


class ShearCapacity(_Row):
    """The shear strength of existing members (MPa, N, mm)."""

    method: Literal["columnDuctility", "cyclicDegradation"]
    # columnDuctility: beams Vc = beamConcrete·λ·√fc·b·d + Av·fyt·d/s; columns
    # V = k·λ·[Av·fyt·d/s + columnConcrete·√fc/(M/Vd)·√(1 + N/(columnAxial·√fc·Ag))·share·Ag].
    beamConcrete: Positive | None = None
    columnConcrete: Positive | None = None
    columnAxial: Positive | None = None
    columnArea: Share | None = None
    shearSpan: tuple[Positive, Positive] | None = Field(
        default=None, description="The range M/Vd is taken within."
    )
    ductility: list[tuple[Positive, Share]] = Field(
        default_factory=list,
        description="k by the displacement ductility demand [[μ, k], ...], linear between.",
    )
    lightweight: Share = Field(default=1.0, description="λ.")
    # cyclicDegradation: V = 1/γel·[(h - x)/(2LV)·min(N, axialShare·Ac·fc) + (1 - degradation·
    # min(ductilityCap, μpl))·(rhoFactor·max(rhoMin, 100ρtot)·(1 - spanFactor·min(spanCap,
    # LV/h))·√fc·Ac + Vw)], Vw = ρw·bw·z·fyw (MN, m in the code; N, mm here).
    gammaEl: Positive | None = None
    axialShare: Share | None = None
    degradation: float | None = Field(default=None, ge=0)
    ductilityCap: Positive | None = None
    rhoFactor: Positive | None = None
    rhoMin: float | None = Field(default=None, ge=0)
    spanFactor: float | None = Field(default=None, ge=0)
    spanCap: Positive | None = None
    note: str = ""

    @model_validator(mode="after")
    def _method_values(self) -> ShearCapacity:
        needed = {
            "columnDuctility": (
                "beamConcrete",
                "columnConcrete",
                "columnAxial",
                "columnArea",
                "shearSpan",
            ),
            "cyclicDegradation": (
                "gammaEl",
                "axialShare",
                "degradation",
                "ductilityCap",
                "rhoFactor",
                "rhoMin",
                "spanFactor",
                "spanCap",
            ),
        }[self.method]
        missing = [k for k in needed if getattr(self, k) is None]
        if missing:
            raise ValueError(f"method {self.method} needs " + ", ".join(missing))
        return self


class Jacketing(_Row):
    """Concrete jackets taken as monolithic members: the jacketed member's values times these."""

    strengthFactor: Positive = Field(description="On the flexural strength.")
    yieldFactor: Positive = Field(description="On the yield chord rotation θy.")
    ultimateFactor: Positive = Field(description="On the ultimate chord rotation θum.")
    shearFactor: Positive = Field(description="On the shear strength.")
    note: str = ""


class FrpConfinement(_Group):
    """FRP wraps confining a column. aci440: fl = 2·Ef·n·tf·εfe/D, f'cc = f'c + ψf·k·κa·fl,
    εccu = εc'·(a + b·κb·(fl/f'c)·(εfe/εc')^e) ≤ strainCap, εfe = κε·εfu; en1998: the term
    α·ρf·ff,e/fc added to the confinement exponent of θum, ff,e = Ef·κε·εfu."""

    strainShare: Share = Field(description="κε: εfe = κε·εfu.")
    psi: Share | None = Field(default=None, description="aci440: ψf of the confinement.")
    strength: Positive | None = Field(default=None, description="aci440: k of f'cc.")
    minRatio: float | None = Field(
        default=None, ge=0, description="aci440: fl/f'c below this: no confinement counted."
    )
    strainBase: Positive | None = Field(default=None, description="aci440: a of εccu.")
    strainCoefficient: Positive | None = Field(default=None, description="aci440: b of εccu.")
    strainExponent: Positive | None = Field(default=None, description="aci440: e of εccu.")
    strainCap: Positive | None = Field(default=None, description="aci440: largest εccu.")
    peakStrain: Positive | None = Field(
        default=None, description="aci440: εc' of unconfined concrete."
    )
    rotationFactor: float | None = Field(
        default=None, ge=0, description="en1998: α of the term in the exponent of θum."
    )


class FrpShear(_Group):
    """FRP shear strengthening: Vf = ψf·Afv·ffe·dfv/sf (aci440) or 0.9·d·ffe·2·n·tf·wf/sf
    (en1998), ffe = εfe·Ef."""

    psiFull: Share = Field(description="ψf of full wraps.")
    psiPartial: Share = Field(description="ψf of U-wraps and two sides.")
    strainFull: Positive = Field(description="εfe of full wraps (at most strainShare·εfu).")
    strainShare: Share = Field(description="εfe ≤ this × εfu.")
    bondLength: Positive | None = Field(
        default=None, description="aci440: Le = this/(n·tf·Ef)^bondExponent [mm]."
    )
    bondExponent: Positive | None = None
    bondStrength: Positive | None = Field(default=None, description="aci440: k1 = (f'c/this)^⅔.")
    bondStrain: Positive | None = Field(
        default=None, description="aci440: κv = k1·k2·Le/(this·εfu)."
    )
    limitShare: Positive | None = Field(
        default=None, description="Vs + Vf ≤ this·√f'c·b·d (empty: no limit)."
    )


class FrpFlexure(_Group):
    """FRP flexural strengthening: the laminate's strain at most the debonding strain
    εfd = k·√(f'c/(n·Ef·tf)) ≤ share·εfu, its force times ψf."""

    psi: Share
    debonding: Positive
    debondingShare: Share


class FrpRules(_Row):
    """Externally bonded FRP (MPa, mm)."""

    method: Literal["aci440", "en1998"]
    environment: dict[str, dict[str, Share]] = Field(
        description="CE by fibre (carbon, glass, aramid) and exposure (interior, exterior, "
        "aggressive): εfu = CE·εfu*."
    )
    confinement: FrpConfinement
    shear: FrpShear
    flexure: FrpFlexure | None = Field(default=None, description="Empty: not covered.")
    note: str = ""

    @model_validator(mode="after")
    def _method_values(self) -> FrpRules:
        c, s = self.confinement, self.shear
        if self.method == "aci440":
            needed = [
                ("confinement", k)
                for k in (
                    "psi",
                    "strength",
                    "minRatio",
                    "strainBase",
                    "strainCoefficient",
                    "strainExponent",
                    "strainCap",
                    "peakStrain",
                )
                if getattr(c, k) is None
            ]
            needed += [
                ("shear", k)
                for k in ("bondLength", "bondExponent", "bondStrength", "bondStrain")
                if getattr(s, k) is None
            ]
        else:
            needed = [("confinement", "rotationFactor")] if c.rotationFactor is None else []
        if needed:
            raise ValueError(
                f"method {self.method} needs " + ", ".join(f"{g}.{k}" for g, k in needed)
            )
        return self


class Tier1Item(_Row):
    """One statement of the screening checklist."""

    id: str
    label: str
    group: str = Field(default="", description="Building system, foundation, ...")


class ExistingTable(TableModel):
    """The assessment and retrofit of existing buildings (:mod:`saengine.fem.existing_building`)."""

    knowledge: list[KnowledgeLevel] = Field(min_length=1)
    defaultKnowledge: str = Field(description="The level of a project that chooses none.")
    strengths: Strengths
    linear: LinearAssessment
    nonlinear: NonlinearAssessment
    shear: ShearCapacity
    jacketing: Jacketing
    frp: FrpRules
    tier1: list[Tier1Item] = Field(default_factory=list)
    basis: str = Field(
        default="",
        description="How the results name the basis (e.g. 'SAEngine practice, ASCE 41 basis').",
    )
    note: str = ""

    @model_validator(mode="after")
    def _default_level(self) -> ExistingTable:
        if self.defaultKnowledge not in {k.id for k in self.knowledge}:
            raise ValueError(f"defaultKnowledge '{self.defaultKnowledge}' is not a level")
        return self
