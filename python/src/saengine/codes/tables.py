"""The data tables of a code pack: one pydantic model per table.

A code pack (:mod:`saengine.codes`) keeps the reference data and the plain-number factors of a
design code in ``data/<table>.json`` files; this module defines what each table holds, so a pack
is validated (and its JSON Schema generated) from the same models the program reads. The models
cover what SAEngine uses today with the BNBC 2020 pack and are kept general enough for other
codes: combinations are named lists of ``{load case: factor}`` by category, a structural system
row is ``{R, Ω0, Cd, height limits by Seismic Design Category}``, and so on.

Every table accepts:

- ``source``: the clause (and page) the table comes from, as text;
- ``sources``: clause references of single entries or fields, ``{"<key>": "<clause>"}``;
- keys starting with ``$`` (``$schema``, ``$comment``, ``$replace`` ...): read by the pack loader
  (inheritance), ignored by the models.

Formulas stay in Python; a pack only changes the numbers (see ``docs/code-packs.md``).

Registration: :data:`TABLE_MODELS` maps a table name to its model; the registry
(:mod:`saengine.codes.registry`) registers them with :func:`register_all`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The folder of the built-in packs.
PACKS_DIR = Path(__file__).parent / "packs"


class TableModel(BaseModel):
    """Base of every table: the common ``source``/``sources`` fields, ``$`` keys dropped."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str = Field(default="", description="Clause (and page) the table comes from.")
    sources: dict[str, str] = Field(
        default_factory=dict, description="Clause references of single entries: {key: clause}."
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_dollar_keys(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if not str(k).startswith("$")}
        return data


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: str | None = Field(default=None, description="Clause (and page) of this row.")


# ───────────────────────────────────────── site / hazard ─────────────────────────────────────────


class Location(_Row):
    name: str
    zone: int = Field(description="Seismic zone (index into zoneCoefficients).")
    windSpeed: float = Field(gt=0, description="Basic wind speed V [m/s].")


class LocationsTable(TableModel):
    """Towns with their seismic zone and basic wind speed."""

    locations: dict[str, Location]


class ZoneCoefficientsTable(TableModel):
    """Seismic zone coefficient Z (peak ground acceleration in g) by zone."""

    zones: dict[int, float]


class OccupancyCategory(_Row):
    description: str
    seismicImportance: float = Field(gt=0)
    windImportance: float = Field(gt=0)


class OccupancyCategoriesTable(TableModel):
    """Occupancy (risk) categories of buildings with their importance factors."""

    categories: dict[str, OccupancyCategory]


class AreaUse(_Row):
    name: str
    live: float = Field(ge=0, description="Minimum uniformly distributed live load [kN/m²].")


class AreaLoadsTable(TableModel):
    """Minimum live loads by use of the floor area."""

    uses: dict[str, AreaUse]


class WallTypeRow(_Row):
    id: str
    name: str
    thickness: float = Field(gt=0, description="Masonry thickness [mm].")
    masonry: str = Field(description="Key into 'masonry'.")
    plaster: float = Field(default=0, ge=0, description="Plaster on each face [mm].")
    plasterFaces: int = Field(default=2, ge=0, le=2)
    plasterKind: str = Field(default="cement", description="Key into 'plaster'.")


class DeadLoadsTable(TableModel):
    """Unit weights of masonry and plaster [kN/m³] and the default wall types of member loads
    (line loads of walls on beams, :mod:`saengine.library.line_loads`)."""

    masonry: dict[str, float]
    plaster: dict[str, float]
    wallTypes: list[WallTypeRow] = Field(default_factory=list)

    @model_validator(mode="after")
    def _keys(self) -> DeadLoadsTable:
        for row in self.wallTypes:
            if row.masonry not in self.masonry:
                raise ValueError(f"wall type {row.id}: no masonry '{row.masonry}'")
            if row.plasterKind not in self.plaster:
                raise ValueError(f"wall type {row.id}: no plaster '{row.plasterKind}'")
        return self


# ───────────────────────────────────────── combinations ─────────────────────────────────────────


class Combination(_Row):
    name: str
    #: Load case kind -> factor. Kinds: D (incl. SD), L, Lr, W, E, F, T, H, R, ... ("W" and "E"
    #: expand to the plan directions and signs in the program).
    factors: dict[str, float]


class CombinationsTable(TableModel):
    """Load cases and load combinations by category."""

    loadCases: dict[str, str] = Field(description="Load case id -> title.")
    strength: list[Combination] = Field(description="Strength (LRFD/USD) combinations.")
    service: list[Combination] = Field(default_factory=list)
    temperature: list[Combination] = Field(
        default_factory=list, description="Strength combinations with T (rise +, fall -)."
    )
    gravity: list[Combination] = Field(
        default_factory=list, description="The strength combinations with gravity loads only."
    )
    seismicDeadUpper: float = Field(
        description="D factor of the strength combination with E and L (before + Ev)."
    )
    seismicDeadLower: float = Field(
        description="D factor of the strength combination with E and no L (before - Ev)."
    )
    overstrength: str = Field(
        default="",
        description="How Em applies: text for the report (Ω0 from the seismic systems table).",
    )


# ─────────────────────────────────────────── seismic ───────────────────────────────────────────


class SiteClass(_Row):
    description: str
    S: float = Field(gt=0, description="Soil factor.")
    TB: float = Field(ge=0)
    TC: float = Field(ge=0)
    TD: float = Field(ge=0)


class StructuralSystem(_Row):
    name: str
    R: float = Field(gt=0)
    Omega0: float = Field(gt=0)
    Cd: float = Field(gt=0)
    row: str = Field(default="", description="Row of the code's system table.")
    #: Height limit [m] by Seismic Design Category: null no limit, 0 not permitted.
    heightLimits: dict[str, float | None] = Field(default_factory=dict)
    frame: Literal["special", "intermediate", "ordinary"] | None = None
    specialWalls: bool = False
    concrete: bool = True
    momentFrame: bool = False
    periodFamily: str | None = None


class PeriodCoefficient(_Row):
    Ct: float = Field(gt=0)
    m: float = Field(gt=0)


class DesignCategories(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Occupancy category -> column group of the table (e.g. "I-III", "IV").
    occupancyGroups: dict[str, str]
    #: Site class -> group -> Seismic Design Category for each zone, in zone order.
    bySiteClass: dict[str, dict[str, list[str]]]
    #: Site classes read from another row (e.g. S1, S2 -> SE).
    aliases: dict[str, str] = Field(default_factory=dict)


class SeismicTable(TableModel):
    """Site classes, spectrum, systems, SDC and the plain numbers of the seismic analysis."""

    siteClasses: dict[str, SiteClass]
    systems: dict[str, StructuralSystem]
    periodCoefficients: dict[str, PeriodCoefficient]
    designCategories: DesignCategories
    requiredDetailing: dict[str, Literal["special", "intermediate", "ordinary"]]
    allowableDrift: dict[str, float] = Field(description="Δa/hsx by occupancy category.")
    dampingEta: float = 1.0
    liveShare: float = Field(description="Share of the floor live load in the seismic weight.")
    heavyLiveLimit: float | None = Field(
        default=None,
        ge=0,
        description="Live loads above this [kN/m²] count in the seismic weight with "
        "heavyLiveShare (empty: every live load with liveShare).",
    )
    heavyLiveShare: float | None = Field(
        default=None, ge=0, le=1, description="Share of a heavy live load in the seismic weight."
    )
    periodUpperFactor: float | None = Field(
        default=None,
        gt=1,
        description="A period from the structure's properties is at most this times the "
        "approximate period Ta (empty: 1.4).",
    )
    minimumScale: float = Field(description="Least share of the static base shear for RS.")
    accidentalEccentricity: float
    orthogonalShare: float
    massParticipation: float
    torsionIrregular: float
    torsionExtreme: float
    torsionAmplificationMax: float
    pgaFactor: float = Field(description="a_h = pgaFactor · Z · S.")
    verticalFactor: float = Field(description="Ev = verticalFactor · a_h · D.")


# ───────────────────────────────────────────── wind ─────────────────────────────────────────────


class Exposure(_Row):
    description: str
    alpha: float = Field(gt=0)
    zg: float = Field(gt=0, description="Gradient height [m].")


class WindDesignCasesRow(_Row):
    """The design wind load cases of the main wind-force resisting system (BNBC 2020 Part 6
    Sec 2.4.11.3 and Figure 6.2.9): read by :func:`saengine.fem.loads.wind_design_cases`."""

    partial: float = Field(gt=0, le=1, description="Case 2: share of the pressure with torsion.")
    eccentricity: float = Field(ge=0, description="Case 2 and 4: e / B.")
    simultaneous: float = Field(gt=0, le=1, description="Case 3: share of each direction.")
    simultaneousTorsional: float = Field(
        gt=0, le=1, description="Case 4: share of each direction with both torsions."
    )
    exemptHeight: float = Field(gt=0, description="Exception: one-storey height limit h [m].")


class WindTable(TableModel):
    exposures: dict[str, Exposure]
    directionality: float = Field(description="Kd for buildings.")
    topographic: float = Field(description="Kzt (flat terrain).")
    gust: float = Field(description="G of a rigid building.")
    cpWindward: float
    #: (L/B, Cp) points of the leeward wall coefficient.
    cpLeeward: list[tuple[float, float]]
    designCases: WindDesignCasesRow | None = Field(
        default=None,
        description="Factors of the design wind load cases 2-4 (torsional, simultaneous); "
        "None: Case 1 only.",
    )


# ─────────────────────────────────────── materials, factors ───────────────────────────────────────


class MaterialsTable(TableModel):
    concreteStrain: float = Field(description="εcu at the extreme compression fibre.")
    steelE: float = Field(description="Es of reinforcement [MPa].")
    steelShearModulus: float = Field(description="G of structural steel [MPa].")
    seismicFcMin: float
    lightweightFcMax: float
    lightweightDensity: float
    seismicRebarFy: list[float] = Field(description="Permitted fy of seismic reinforcement.")
    seismicRebarFyMax: float
    gradeTolerance: float
    fyActualMargin: float
    fyRetestMargin: float
    fuFyMin: float


class _Group(BaseModel):
    """A group of named numbers inside a table, read as ``group.key`` or ``group["key"]``.

    Every key the program reads is a required field with bounds, so a pack with a missing key, a
    wrong type or a nonsense value is rejected when it loads (and listed as a problem), not in the
    middle of a design run. Unknown keys are refused (a typo would otherwise be ignored silently),
    except in the φ groups, which accept further factors (for hooks) checked as 0 < φ <= 1."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def __getitem__(self, key: str) -> Any:
        if key in type(self).model_fields:
            return getattr(self, key)
        extra = self.__pydantic_extra__ or {}
        if key in extra:
            return extra[key]
        raise KeyError(key)

    def __contains__(self, key: object) -> bool:
        return key in type(self).model_fields or key in (self.__pydantic_extra__ or {})

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self) -> list[str]:
        return [*type(self).model_fields, *(self.__pydantic_extra__ or {})]

    def items(self) -> list[tuple[str, Any]]:
        return [(k, self[k]) for k in self.keys()]

    def values(self) -> list[Any]:
        return [self[k] for k in self.keys()]


#: A strength reduction factor φ, a share or a ratio: 0 < x <= 1.
Phi = Annotated[float, Field(gt=0, le=1)]
Share = Annotated[float, Field(gt=0, le=1)]
#: A positive length, stress or count.
Positive = Annotated[float, Field(gt=0)]
#: A steel ratio ρ (0 < ρ < 1).
Rho = Annotated[float, Field(gt=0, lt=1)]


def _ordered_pair(value: tuple[float, float], what: str) -> tuple[float, float]:
    if value[0] > value[1]:
        raise ValueError(f"{what}: the first value must not exceed the second")
    return value


class ConcretePhi(_Group):
    """φ of reinforced concrete (extra keys allowed for hooks, also 0 < φ <= 1)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)
    __pydantic_extra__: dict[str, Phi] = Field(init=False)  # type: ignore[assignment]

    tension: Phi = Field(description="Tension-controlled sections.")
    compressionTied: Phi = Field(description="Compression-controlled, tied.")
    compressionSpiral: Phi = Field(description="Compression-controlled, spiral.")
    shear: Phi = Field(description="Shear and torsion.")
    punching: Phi = Field(description="Two-way (punching) shear.")
    shearSeismic: Phi = Field(description="Shear of members whose nominal shear is not governed.")
    diagonalCoupling: Phi = Field(description="Diagonally reinforced coupling beams.")
    joint: Phi = Field(description="Beam-column joints of special moment frames.")
    strutAndTie: Phi = Field(description="Strut-and-tie models.")
    stiffnessReduction: Phi = Field(description="φK of the slender column moment magnifier.")


class FactorsTable(TableModel):
    """Strength reduction factors φ."""

    phi: ConcretePhi


# ──────────────────────────────────────── concrete, detailing ────────────────────────────────────────


class BarDiameters(_Group):
    """Bar size sets [mm] by use (extra sets allowed)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)
    __pydantic_extra__: dict[str, list[Positive]] = Field(init=False)  # type: ignore[assignment]

    all: list[Positive] = Field(min_length=1)
    main: list[Positive] = Field(min_length=1)
    column: list[Positive] = Field(min_length=1)
    slab: list[Positive] = Field(min_length=1)
    stirrup: list[Positive] = Field(min_length=1)
    wall: list[Positive] = Field(min_length=1)
    boundary: list[Positive] = Field(min_length=1)
    hoop: list[Positive] = Field(min_length=1)
    lintel: list[Positive] = Field(min_length=1)


class Covers(_Group):
    """Assumed clear covers [mm] by element."""

    lintel: Positive
    stair: Positive
    pileCap: Positive


class CrackedStiffness(_Group):
    """Cracked-section stiffness factors (share of the gross moment of inertia)."""

    column: Share
    beam: Share
    plate: Share
    wall: Share


class SlenderLimits(_Group):
    """Slender column limits (moment magnifier method)."""

    nonswayQ: Positive = Field(
        description="Stability index Q at or below which a storey is nonsway."
    )
    swayLimit: Positive = Field(description="k·lu/r below which a sway column is short.")
    nonswayCap: Positive = Field(description="Upper cap of the nonsway k·lu/r limit.")
    kluRMax: Positive = Field(description="k·lu/r above which second-order analysis is required.")
    deltaSMax: float = Field(ge=1, description="δs above which second-order analysis is required.")
    momentRatioMax: float = Field(ge=1, description="M2 (2nd order)/M2 (1st order) limit.")


class WallSteel(_Group):
    """Minimum steel and spacing of structural walls."""

    rhoSmallBars: tuple[Rho, Rho] = Field(description="(vertical, horizontal) ρ, small bars.")
    rhoOtherBars: tuple[Rho, Rho] = Field(description="(vertical, horizontal) ρ, other bars.")
    smallBarMax: Positive = Field(description="Largest bar [mm] counted as a small bar.")
    smallBarFy: Positive = Field(description="Least fy [MPa] of the small-bar ratios.")
    rhoShear: Rho = Field(description="Least ρ of special walls (both ways).")
    twoLayerThickness: Positive = Field(description="Thickness [mm] from which two layers apply.")
    spacingMax: Positive = Field(description="Largest bar spacing [mm].")


class TorsionLimits(_Group):
    """Limits and choices of the torsion design of beams (BNBC 2020 Part 6 Sec 6.4.4)."""

    theta: float = Field(ge=30, le=60, description="Angle θ of the compression diagonals [°].")
    aoShare: Share = Field(description="Ao / Aoh.")
    spacingMax: Positive = Field(description="Largest spacing of closed stirrups [mm].")
    perimeterDivisor: Positive = Field(description="s <= ph / this.")
    longitudinalSpacingMax: Positive = Field(description="Longitudinal bars apart at most [mm].")
    longitudinalDiaRatio: Positive = Field(description="Longitudinal bar diameter >= this × s.")
    longitudinalDiaMin: Positive = Field(description="[mm]")
    fyMax: Positive = Field(description="Largest fy, fyt of torsion steel [MPa].")


class DeflectionLimitsGroup(_Group):
    """Span divisors of the computed deflection limits, ξ and the cantilever thickness divisors
    (BNBC 2020 Part 6 Sec 6.2.5)."""

    liveFloor: Positive = Field(description="Floors: immediate live-load deflection <= l/this.")
    liveRoof: Positive = Field(description="Flat roofs: immediate live-load deflection.")
    attachedSensitive: Positive = Field(
        description="After attachment, elements likely to be damaged: l/this."
    )
    attachedInsensitive: Positive = Field(
        description="After attachment, elements not likely to be damaged: l/this."
    )
    xi: dict[float, Positive] = Field(min_length=1, description="Months -> ξ.")
    cantileverBeam: Positive = Field(description="Least beam depth of a cantilever: l/this.")
    cantileverSlab: Positive = Field(description="Least slab thickness of a cantilever: l/this.")


class ConcreteTable(TableModel):
    barDiameters: BarDiameters = Field(description="Bar size sets [mm] by use.")
    spacingStep: float
    minSlabSpacing: float
    minStirrupSpacing: float
    columnRho: tuple[float, float]
    beamRatioMax: float
    slabStrainMin: float
    fytShearMax: float
    slendernessLimit: float
    #: fy -> (exterior without edge beams, exterior with edge beams, interior) divisors of ln.
    twoWayThickness: dict[float, tuple[float, float, float]]
    oneWaySlabThickness: tuple[float, float, float]
    beamThickness: tuple[float, float, float]
    cover: Covers = Field(description="Assumed covers [mm] by element.")
    crackedStiffness: CrackedStiffness
    slender: SlenderLimits
    walls: WallSteel
    torsion: TorsionLimits | None = Field(
        default=None, description="Torsion design of beams (saengine.design.torsion)."
    )
    deflection: DeflectionLimitsGroup | None = Field(
        default=None, description="Deflection limits (saengine.design.deflection)."
    )

    @model_validator(mode="after")
    def _check_ratios(self) -> ConcreteTable:
        _ordered_pair(self.columnRho, "columnRho")
        return self


class SpecialFrames(_Group):
    """Plain-number limits of special moment frame members."""

    axialShare: Share = Field(description="Pu/(Ag·f'c) above which a member is a column.")
    beamRhoMax: Rho
    columnRho: tuple[Rho, Rho] = Field(description="(least, largest) ρ of columns.")
    beamMinWidth: Positive = Field(description="[mm]")
    beamMinRatio: Share = Field(description="Least width/depth of beams.")
    columnMinDimension: Positive = Field(description="[mm]")
    columnMinRatio: Share = Field(description="Least short/long side of columns.")
    fytConfinementMax: Positive = Field(description="Largest fyt of confinement [MPa].")
    hxMax: Positive = Field(description="Largest hx [mm].")
    unsupportedClear: Positive = Field(description="[mm]")
    beamFirstHoop: Positive = Field(description="First hoop from the column face [mm].")

    @model_validator(mode="after")
    def _check(self) -> SpecialFrames:
        _ordered_pair(self.columnRho, "columnRho")
        return self


#: γ keys of the joint shear strength the program reads.
JOINT_GAMMA_KEYS = ("4", "3", "opposite", "other")


class Joints(_Group):
    """Plain numbers of special moment frame beam-column joints."""

    probableStress: float = Field(ge=1, description="Probable stress factor of bars (1.25 fy).")
    strongColumnRatio: float = Field(ge=1, description="ΣMnc/ΣMnb least.")
    axialLimit: Share
    #: γ by confinement: "4" and "3" faces confined, "opposite", "other".
    gamma: dict[str, Positive]
    vcZeroAxial: Share

    @model_validator(mode="after")
    def _check(self) -> Joints:
        missing = [k for k in JOINT_GAMMA_KEYS if k not in self.gamma]
        if missing:
            raise ValueError(f"gamma: missing {', '.join(missing)}")
        return self


class SpecialWalls(_Group):
    """Plain numbers of special structural walls."""

    relaxedShare: Share
    twoCurtainShare: Share
    driftMin: Share
    stressRequired: Share = Field(description="Boundary elements required above · f'c.")
    stressStop: Share = Field(description="Boundary elements may stop below · f'c.")
    fytConfinementMax: Positive
    hxMax: Positive

    @model_validator(mode="after")
    def _check(self) -> SpecialWalls:
        if self.stressStop > self.stressRequired:
            raise ValueError("stressStop must not exceed stressRequired")
        return self


class LintelLimits(_Group):
    minBearing: Positive = Field(description="[mm]")
    bearing: Positive = Field(description="[mm]")
    deflectionRatio: Positive = Field(description="span / deflection limit")
    probable: float = Field(ge=1)


class DetailingTable(TableModel):
    special: SpecialFrames
    joints: Joints
    walls: SpecialWalls
    lintels: LintelLimits


class SteelPhi(_Group):
    """φ of structural steel (extra keys allowed for hooks, also 0 < φ <= 1)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)
    __pydantic_extra__: dict[str, Phi] = Field(init=False)  # type: ignore[assignment]

    tensionYield: Phi
    tensionRupture: Phi
    compression: Phi
    flexure: Phi
    shear: Phi
    bolt: Phi
    bearing: Phi
    blockShear: Phi
    weld: Phi
    plateFlexure: Phi


class SteelSlenderness(_Group):
    compression: Positive = Field(description="KL/r limit of compression members.")
    tension: Positive = Field(description="L/r limit of tension members.")


class SteelTable(TableModel):
    phi: SteelPhi
    slenderness: SteelSlenderness
    netAreaMax: Share


class StrutAndTie(_Group):
    tieArm: Share = Field(description="Lever arm of the tie as a share of the effective depth.")
    betaCCC: Share = Field(description="βn of a C-C-C node.")
    betaCCT: Share = Field(description="βn of a C-C-T node.")


class FoundationsTable(TableModel):
    pileSafety: dict[str, tuple[float, float, float, float]]
    pileControls: list[str]
    partialSkin: float
    partialBase: float
    sptSafety: float
    noLoadTestSafety: float
    loadTestSafety: float
    strutAndTie: StrutAndTie


class TwoWayTables(BaseModel):
    """BNBC Tables 6.6.8-6.6.11: one row per span ratio m = la/lb (ascending), nine cases per
    row (None: no negative moment, that direction's edges discontinuous)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ratios: list[Positive] = Field(min_length=2)
    #: case -> [continuous long edges, continuous short edges]
    cases: dict[str, tuple[int, int]]
    negativeA: list[list[float | None]]
    negativeB: list[list[float | None]]
    deadA: list[list[float]]
    deadB: list[list[float]]
    liveA: list[list[float]]
    liveB: list[list[float]]
    loadA: list[list[float]]
    loadB: list[list[float]]

    @model_validator(mode="after")
    def _check_shape(self) -> TwoWayTables:
        if self.ratios != sorted(self.ratios):
            raise ValueError("ratios must ascend")
        for name in (
            "negativeA",
            "negativeB",
            "deadA",
            "deadB",
            "liveA",
            "liveB",
            "loadA",
            "loadB",
        ):
            rows = getattr(self, name)
            if len(rows) != len(self.ratios) or any(len(r) != len(self.cases) for r in rows):
                raise ValueError(f"{name}: one row per ratio, one value per case")
        return self


class TwoWayLimits(_Group):
    maxSpanRatio: Positive = Field(description="Longer/shorter centre-to-centre span (6.5.8.2.2).")
    beamDepthRatio: Positive = Field(description="Least beam depth / slab thickness (6.5.8.2.1).")
    alphaRatioMin: Positive = Field(description="Least αf1 l2/l1 (6.5.8.2.3).")


class OneWayTable(BaseModel):
    """BNBC 6.1.4.3: M = w ln² / divisor; shear 1.15 w ln / 2 at the first interior support."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    positive: dict[str, Positive]  # endUnrestrained, endIntegral, interior
    negative: dict[str, Positive]  # firstInteriorTwoSpans, firstInteriorMoreSpans, ...
    shortSpanMax: Positive
    spanRatioMax: float = Field(ge=1)
    liveToDeadMax: Positive
    shearFirstInterior: float = Field(ge=1)


class SlabCoefficientsTable(TableModel):
    twoWay: TwoWayTables
    twoWayLimits: TwoWayLimits
    oneWay: OneWayTable
    #: [times h, at most mm] per rule: twoWay, oneWay, temperature.
    maxSpacing: dict[str, tuple[Positive, Positive]]
    brickAggregateFactor: float = Field(ge=1)
    discontinuousEdgeShare: Share = Field(
        description="SAEngine practice, not a BNBC clause: top bars at a discontinuous edge "
        "for this share of the positive moment."
    )


#: Table name -> model.
TABLE_MODELS: dict[str, type[TableModel]] = {
    "locations": LocationsTable,
    "zoneCoefficients": ZoneCoefficientsTable,
    "occupancyCategories": OccupancyCategoriesTable,
    "areaLoads": AreaLoadsTable,
    "deadLoads": DeadLoadsTable,
    "combinations": CombinationsTable,
    "seismic": SeismicTable,
    "wind": WindTable,
    "materials": MaterialsTable,
    "factors": FactorsTable,
    "concrete": ConcreteTable,
    "detailing": DetailingTable,
    "steel": SteelTable,
    "foundations": FoundationsTable,
    "slabCoefficients": SlabCoefficientsTable,
}


#: Merge keys of the tables' lists (path -> key, :mod:`saengine.codes.merge`): a pack that
#: extends another changes one combination by naming it, the others are kept.
MERGE_KEYS: dict[str, dict[str, str]] = {
    "combinations": {
        "strength": "name",
        "service": "name",
        "temperature": "name",
        "gravity": "name",
    },
    "deadLoads": {"wallTypes": "id"},
}


def register_all(register: Callable[..., Any]) -> None:
    """Register every table model with ``register(name, model, merge_keys)`` (the registry's)."""
    for name, model in TABLE_MODELS.items():
        register(name, model, MERGE_KEYS.get(name))


def validate_table(name: str, data: Any) -> Any:
    """``data`` of table ``name`` validated by its model; unknown tables pass through."""
    model = TABLE_MODELS.get(name)
    return model.model_validate(data) if model is not None else data


def table_schema(name: str) -> dict[str, Any]:
    """The JSON Schema of a table."""
    return TABLE_MODELS[name].model_json_schema()


@cache
def builtin_table(name: str, pack_id: str = "bnbc2020") -> Any:
    """Table ``name`` of a built-in root pack (no inheritance), validated; read once.

    :mod:`saengine.library.bnbc` reads the BNBC pack through this, without the registry, so the
    library modules import nothing of the pack machinery (no import cycles)."""
    path = PACKS_DIR / pack_id / "data" / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "$data" in raw:
        raw = raw["$data"]
    return validate_table(name, raw)


@cache
def builtin_manifest(pack_id: str = "bnbc2020") -> dict[str, Any]:
    return json.loads((PACKS_DIR / pack_id / "pack.json").read_text(encoding="utf-8"))


def _register_with_registry() -> None:
    try:
        from saengine.codes.registry import register
    except ImportError:  # the registry is optional for the readers of the built-in pack
        return
    register_all(register)


_register_with_registry()
