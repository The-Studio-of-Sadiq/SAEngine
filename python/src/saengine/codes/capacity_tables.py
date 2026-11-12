"""Table models of the allowable stress design of members and of the required horizontal
capacity of storeys (alpha 9 track C19).

``allowableStress`` (method ``elasticSection``, :mod:`saengine.design.allowable_stress`): the
members are checked under the pack's allowable stress combinations (``combinations.allowable``)
against long-term or short-term allowable stresses, the combination rows listed in
``longTerm`` taking the long-term ones. Reinforced concrete: the cracked elastic section with
the modular ratio n (no concrete in tension), the allowable concrete stress a share of the
design strength Fc, the bars' allowable stresses by grade (``rebar.grades``, smaller for large
bars), the allowable shear b j (α fs + share wft (pw - offset)) with α = numerator / (M/(Q d) +
1) within its bounds. Structural steel: the allowable tension F / divisor, shear over √3,
compression by the parabola and elastic branches of the slenderness ratio over the limit
slenderness Λ = √(π² E / (share F)), bending by the larger of the two lateral-torsional
buckling forms; short-term values the long-term ones × ``shortFactor``.

``horizontalCapacity`` (method ``requiredCapacity``, :mod:`saengine.fem.horizontal_capacity`):
each storey's horizontal capacity Qu (read from a pushover at the storey drift ratio
``capacityDrift``, or the largest before it) against the required capacity Qun = Ds Fes Qud,
Qud the storey shear of the seismic force at the ultimate standard shear coefficient
(``designSpectrum.shearCoefficient.ultimateCoefficient``), Ds by the structure's material, the
rank of its members and the share βu of the walls or braces (``ds``), Fes = Fs Fe from the
stiffness ratio Rs and the eccentricity ratio Re (``shapeFactors``); the member ranks by the
pack's limits (``memberRanks``: reinforced concrete columns and beams by h0/D, σ0/Fc, pt and
τu/Fc, steel by the width-thickness ratios) and the mean shear strength of concrete members
(``shearStrength``).

A pack without the tables does not cover the checks; every number is the pack's.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from saengine.codes.tables import Positive, Share, TableModel, _Group

# ───────────────────────────── allowableStress ─────────────────────────────


class ConcreteAllowable(_Group):
    """The allowable stresses of concrete as shares of the design strength Fc [MPa]."""

    longShare: Share = Field(description="Long-term allowable compression = share × Fc.")
    shortShare: Share = Field(description="Short-term allowable compression = share × Fc.")
    shearShare: Positive = Field(
        description="Long-term allowable shear fs = min(share Fc, offset + slope Fc)."
    )
    shearOffset: float = Field(ge=0, description="[MPa]")
    shearSlope: float = Field(ge=0)
    shortShearFactor: Positive = Field(description="Short-term fs = this × the long-term fs.")
    modularRatio: Positive = Field(description="n = Es / Ec of the elastic section.")
    leverArm: Share = Field(description="j = share × d.")


class RebarGrade(_Group):
    """A bar grade's allowable stresses [MPa]."""

    fy: Positive = Field(description="The grade's standard yield strength F (to find the grade).")
    long: Positive = Field(description="Long-term tension and compression of main bars.")
    longLarge: Positive | None = Field(
        default=None, description="Long-term of bars of largeFrom and above (empty: long)."
    )
    short: Positive = Field(description="Short-term tension and compression of main bars.")
    shearLong: Positive = Field(description="Long-term wft of shear reinforcement.")
    shearShort: Positive = Field(description="Short-term wft of shear reinforcement.")


class RebarAllowable(_Group):
    grades: dict[str, RebarGrade] = Field(min_length=1)
    largeFrom: Positive = Field(description="Bars of this diameter [mm] and above are large.")


class ShearAllowable(_Group):
    """The allowable shear of beams and columns: Qa = b j (α fs + share wft (pw - offset)),
    α = numerator / (M/(Q d) + 1) within [alphaMin, alphaMax]; long-term without the bars
    (``longWithBars`` false)."""

    alphaNumerator: Positive
    alphaMin: Positive
    beamAlphaMax: Positive
    columnAlphaMax: Positive
    reinforcementShare: Positive
    pwOffset: float = Field(ge=0)
    pwMax: Share
    longWithBars: bool = False


class SteelCompression(_Group):
    """Λ = √(π² E / (limitShare F)); λ ≤ Λ: fc = (1 - parabola (λ/Λ)²) F / ν, ν = nuBase +
    nuSlope (λ/Λ)²; λ > Λ: fc = elastic F / (λ/Λ)²."""

    limitShare: Share
    parabola: Share
    nuBase: Positive
    nuSlope: float = Field(ge=0)
    elastic: Share


class SteelBending(_Group):
    """fb (long-term) the larger of F (base - slope (lb/i)² / (C Λ²)) and flangeConstant /
    (lb h / Af) [MPa], at most the allowable tension; C = momentGradient (1.0: uniform moment,
    on the safe side)."""

    base: Positive
    slope: Positive
    flangeConstant: Positive
    momentGradient: Positive = 1.0


class SteelAllowable(_Group):
    longDivisor: Positive = Field(description="Long-term allowable tension ft = F / divisor.")
    shortFactor: Positive = Field(description="Short-term = this × long-term.")
    shearDivisor: Positive = Field(description="fs = ft / divisor (√3).")
    modulus: Positive = Field(description="E [MPa].")
    compression: SteelCompression
    bending: SteelBending


class AllowableStressTable(TableModel):
    """Allowable stress design of members (``elasticSection``): see the module notes."""

    method: Literal["elasticSection"] = "elasticSection"
    longTerm: list[str] = Field(
        description="Ids of the allowable stress combination rows checked with the long-term "
        "allowable stresses; the others take the short-term ones."
    )
    concrete: ConcreteAllowable
    rebar: RebarAllowable
    shear: ShearAllowable
    steel: SteelAllowable | None = None


# ───────────────────────────── horizontalCapacity ─────────────────────────────


class DsBand(_Group):
    """Ds of a member rank: (βu up to, Ds) bands, the last band's above."""

    bands: list[tuple[float, Positive]] = Field(min_length=1)


class DsMaterial(_Group):
    ranks: dict[str, DsBand] = Field(min_length=1)


class ShapeFactors(_Group):
    """Fs of the stiffness ratio Rs and Fe of the eccentricity ratio Re: (ratio, factor) points,
    linear between, the end values outside; ``rsLimit``, ``reLimit`` the primary design's
    limits (Rs at least, Re at most)."""

    stiffness: list[tuple[float, Positive]] = Field(min_length=1)
    eccentricity: list[tuple[float, Positive]] = Field(min_length=1)
    rsLimit: Positive
    reLimit: Positive


class ColumnRankLimits(_Group):
    """A reinforced concrete column's rank limits (each the most the rank allows; empty: no
    limit): h0/D at least, σ0/Fc, pt and τu/Fc at most."""

    clearRatio: float | None = Field(default=None, gt=0, description="h0 / D at least.")
    axialRatio: float | None = Field(default=None, gt=0, description="σ0 / Fc at most.")
    tensionRatio: float | None = Field(default=None, gt=0, description="pt [%] at most.")
    shearRatio: float | None = Field(default=None, gt=0, description="τu / Fc at most.")


class BeamRankLimits(_Group):
    shearRatio: float | None = Field(default=None, gt=0, description="τu / Fc at most.")


class SteelRankLimits(_Group):
    """Width-thickness ratios at most, × √(reference / F)."""

    flange: float | None = Field(default=None, gt=0)
    web: float | None = Field(default=None, gt=0)
    tube: float | None = Field(default=None, gt=0, description="Box: B/t at most.")
    pipe: float | None = Field(
        default=None, gt=0, description="Pipe: D/t at most × reference / F (not the root)."
    )


class MemberRanks(_Group):
    """The ranks in order (best first) and their limits; a member meeting none takes the
    last rank."""

    order: list[str] = Field(min_length=2)
    columns: dict[str, ColumnRankLimits] = Field(default_factory=dict)
    beams: dict[str, BeamRankLimits] = Field(default_factory=dict)
    steelColumns: dict[str, SteelRankLimits] = Field(default_factory=dict)
    steelBeams: dict[str, SteelRankLimits] = Field(default_factory=dict)
    steelReference: Positive = Field(default=235.0, description="F of the ratios [MPa].")
    shearFailureRank: str | None = Field(
        default=None,
        description="The rank of a concrete member whose mean shear strength is below the "
        "shear at its flexural strength (shear failure); empty: the last rank.",
    )


class ShearStrength(_Group):
    """The mean shear strength of a concrete member (``meanEmpirical``): Qsu = {coefficient
    pt^ptExponent (Fc + offset) / (M/(Q d) + spanOffset) + bars √(pw σwy) + axial σ0} b j, pt
    in %, M/(Q d) within ``spanRange``, pw at most ``pwMax``; the flexural strengths Mu = beam
    at σy d (beams) and column at σy D + axialShare N D (1 - N / (b D Fc)) (columns), σy =
    yieldFactor × the bars' F."""

    method: Literal["meanEmpirical"] = "meanEmpirical"
    coefficient: Positive
    ptExponent: Positive
    offset: float
    spanOffset: float = Field(ge=0)
    spanRange: tuple[Positive, Positive]
    bars: Positive
    axial: float = Field(ge=0)
    pwMax: Share
    beam: Positive
    column: Positive
    axialShare: Positive
    yieldFactor: Positive = 1.0


class CapacitySystem(_Group):
    """A seismic system's material for Ds and its share βu of walls or braces."""

    material: str
    betaU: float = Field(ge=0, le=1)


class HorizontalCapacityTable(TableModel):
    """The required horizontal capacity of storeys (``requiredCapacity``): see the module
    notes."""

    method: Literal["requiredCapacity"] = "requiredCapacity"
    capacityDrift: Positive = Field(
        description="Qu is read at this storey drift ratio (or the largest storey shear before it)."
    )
    ds: dict[str, DsMaterial] = Field(min_length=1)
    systems: dict[str, CapacitySystem] = Field(default_factory=dict)
    defaultSystem: CapacitySystem
    defaultRank: str = Field(description="The rank where the members' ranks are not known.")
    shapeFactors: ShapeFactors
    memberRanks: MemberRanks | None = None
    shearStrength: ShearStrength | None = None

    @model_validator(mode="after")
    def _ranks(self) -> HorizontalCapacityTable:
        for name, material in self.ds.items():
            if self.defaultRank not in material.ranks:
                raise ValueError(f"ds.{name}: no rank '{self.defaultRank}' (defaultRank)")
        if self.memberRanks is not None and self.defaultRank not in self.memberRanks.order:
            raise ValueError(f"defaultRank '{self.defaultRank}' is not in memberRanks.order")
        return self
