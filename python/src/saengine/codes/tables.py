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
    allowable: list[Combination] = Field(
        default_factory=list,
        description="Allowable stress design (ASD) combinations, for the materials designed by "
        "permissible stresses (timber).",
    )
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
    masonry: bool = Field(
        default=False, description="A masonry system: its walls are designed as masonry."
    )
    momentFrame: bool = False
    periodFamily: str | None = None
    group: str | None = Field(
        default=None, description="Group of the code's system table (bearingWall, dualSpecial...)."
    )
    dual: bool = Field(default=False, description="A dual system (one row of the table).")
    note: str | None = None


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


class SiteSpecificStudy(BaseModel):
    """Site classes the code gives no spectrum for: they need a site-specific study."""

    model_config = ConfigDict(extra="forbid")

    classes: list[str] = Field(default_factory=list)
    #: The class whose row of the category table is assumed meanwhile.
    assumedClass: str | None = None
    clause: str = ""
    #: Text of the warning; {classes}, {code}, {clause}, {used} and {assumed} are filled in.
    warning: str = ""


class DriftLimit(_Row):
    """A row of the allowable storey drift table; the first row whose conditions hold applies
    (a condition left empty always holds), else ``allowableDrift``."""

    id: str
    label: str
    masonry: bool | None = Field(default=None, description="The system is a masonry one.")
    cantileverWalls: bool | None = Field(
        default=None, description="The walls are cantilevered from the base (no coupling)."
    )
    maxStoreys: int | None = Field(default=None, gt=0)
    driftTolerantFinishes: bool | None = Field(
        default=None,
        description="Interior walls, partitions, ceilings and exterior walls designed to "
        "accommodate the storey drift.",
    )
    limits: dict[str, float] = Field(description="Δa/hsx by occupancy category.")


class DampingCorrection(BaseModel):
    """The spectrum's damping correction η(ξ). ``squareRoot``: η = √(numerator / (offset +
    100ξ)), at least ``minimum``; ``none``: η = dampingEta."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["none", "squareRoot"] = "none"
    referenceDamping: float = Field(default=0.05, gt=0, lt=1)
    numerator: float = 10.0
    offset: float = 5.0
    minimum: float = 0.0


class SystemCombination(BaseModel):
    """How the values of several systems in one direction combine: "min" or "max"."""

    model_config = ConfigDict(extra="forbid")

    R: Literal["min", "max"] = "min"
    Cd: Literal["min", "max"] = "max"
    Omega0: Literal["min", "max"] = "max"
    heightLimit: Literal["min", "max"] = "min"


class Separation(BaseModel):
    """Separation from adjacent structures: the gap to the property line is at least
    ``propertyLineFactor``·δ; between units of one property the ``sameProperty`` combination
    ("srss" or "sum") of the two δ; times ``equalFloorLevelsFactor`` where the floors align."""

    model_config = ConfigDict(extra="forbid")

    propertyLineFactor: float = Field(default=1.0, gt=0)
    sameProperty: Literal["srss", "sum"] = "srss"
    equalFloorLevelsFactor: float = Field(default=1.0, gt=0, le=1)


class DiaphragmDeflection(BaseModel):
    """In-plane diaphragm deflection limit [mm]; empty: the code gives no number (the
    permissible deflection of the attached elements, which the engineer enters)."""

    model_config = ConfigDict(extra="forbid")

    limit: float | None = Field(default=None, gt=0)


class SeismicTable(TableModel):
    """Site classes, spectrum, systems, SDC and the plain numbers of the seismic analysis."""

    siteClasses: dict[str, SiteClass]
    systems: dict[str, StructuralSystem]
    periodCoefficients: dict[str, PeriodCoefficient]
    designCategories: DesignCategories
    requiredDetailing: dict[str, Literal["special", "intermediate", "ordinary"]]
    allowableDrift: dict[str, float] = Field(description="Δa/hsx by occupancy category.")
    allowableDriftLabel: str = Field(default="", description="The structures allowableDrift is for.")
    driftLimits: list[DriftLimit] = Field(
        default_factory=list, description="Rows of the drift table before allowableDrift."
    )
    driftRedundancyCategories: list[str] = Field(
        default_factory=list,
        description="Seismic Design Categories where the drift limit of systems of moment "
        "frames only is divided by the redundancy factor ρ.",
    )
    siteSpecificStudy: SiteSpecificStudy = Field(default_factory=SiteSpecificStudy)
    dampingEta: float = 1.0
    dampingCorrection: DampingCorrection = Field(default_factory=DampingCorrection)
    systemCombination: SystemCombination = Field(default_factory=SystemCombination)
    separation: Separation = Field(default_factory=Separation)
    diaphragmDeflection: DiaphragmDeflection = Field(default_factory=DiaphragmDeflection)
    clauses: dict[str, str] = Field(
        default_factory=dict, description="Clause references of the seismic results, by key."
    )
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
    # The terrain constants of the gust-effect factor (BNBC 2020 Part 6 Table 6.2.10); None: a
    # pack without them gives rigid buildings only.
    c: float | None = Field(default=None, gt=0, description="Turbulence intensity factor c.")
    l: float | None = Field(default=None, gt=0, description="Integral length scale ℓ [m].")
    epsilonBar: float | None = Field(default=None, gt=0, description="Integral length ε̄.")
    alphaBar: float | None = Field(default=None, gt=0, description="Mean-speed power ᾱ.")
    bBar: float | None = Field(default=None, gt=0, description="Mean-speed factor b̄.")
    zmin: float | None = Field(default=None, gt=0, description="z_min of z̄ [m].")


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


class FlexibleGustRow(_Row):
    """The gust-effect factor Gf of a flexible or dynamically sensitive building (BNBC 2020 Part 6
    Sec 2.4.8.2): read by :func:`saengine.fem.loads.flexible_gust_factor`."""

    frequencyLimit: float = Field(gt=0, description="A building below n1 [Hz] is flexible.")
    gQ: float = Field(gt=0, description="Peak factor of the background response gQ.")
    gv: float = Field(gt=0, description="Peak factor of the wind response gv.")
    heightFactor: float = Field(gt=0, description="z̄ = heightFactor · h.")
    lead: float = Field(gt=0, description="The factor before the fraction (0.925).")
    damping: float = Field(gt=0, lt=1, description="Damping ratio β of a concrete building.")


class CladdingCurve(_Row):
    """One external pressure coefficient (GCp) of components and cladding: ``gcp1`` at an
    effective wind area up to ``area1`` [m²], ``gcp2`` from ``area2``, linear in log A between."""

    surface: Literal["wall", "roof"]
    zone: str
    sign: Literal["positive", "negative"]
    area1: float = Field(gt=0)
    gcp1: float
    area2: float = Field(gt=0)
    gcp2: float


class CladdingTable(_Row):
    """Components and cladding (BNBC 2020 Part 6 Sec 2.4.11.5): the (GCp) curves of walls and
    flat roofs (θ ≤ 10°) of low-rise (h ≤ ``lowRiseHeight``) and taller buildings, the internal
    pressure coefficients and the edge-zone width a."""

    lowRiseHeight: float = Field(gt=0, description="h [m] up to which the low-rise curves hold.")
    lowRise: list[CladdingCurve]
    highRise: list[CladdingCurve]
    lowRiseWallFactor: float = Field(
        gt=0, le=1, description="Factor on the low-rise wall (GCp) for a roof θ ≤ 10°."
    )
    internal: dict[str, float] = Field(description="(GCpi) magnitude by enclosure.")
    edgeFraction: float = Field(gt=0, description="a ≤ edgeFraction · least plan dimension.")
    edgeHeightFraction: float = Field(gt=0, description="Low-rise: a ≤ this · h.")
    edgeMinFraction: float = Field(gt=0, description="a ≥ this · least plan dimension.")
    edgeMin: float = Field(gt=0, description="a ≥ this [m].")
    parapetCorner: float = Field(
        gt=0, description="A parapet this high [m] or more turns roof zone 3 into zone 2."
    )


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
    flexible: FlexibleGustRow | None = Field(
        default=None, description="Gf of flexible buildings; None: rigid G only."
    )
    cladding: CladdingTable | None = Field(
        default=None, description="Components and cladding pressures; None: not computed."
    )
    openStructures: OpenStructuresTable | None = Field(
        default=None,
        description="Force coefficients of open structures (lattice frameworks, trussed "
        "towers); None: special structures get no wind.",
    )


class LatticeCfRow(_Row):
    """Force coefficient Cf of an open sign or lattice framework up to a solidity ratio ε: by
    member shape, flat-sided or rounded (small and large D√qz)."""

    solidityMax: float = Field(gt=0, le=1, description="Row holds for ε below this.")
    flat: float = Field(gt=0, description="Cf, flat-sided members.")
    roundSmall: float = Field(gt=0, description="Cf, rounded members, D√qz up to the limit.")
    roundLarge: float = Field(gt=0, description="Cf, rounded members, D√qz above the limit.")


class TowerCf(_Row):
    """Cf = a·ε² + b·ε + c of a trussed tower's face."""

    a: float
    b: float
    c: float


class OpenStructuresTable(_Row):
    """Design wind loads on other structures, F = qz·G·Cf·Af (BNBC 2020 Part 6 Sec 2.4, the
    provisions of ASCE 7-05 Sec 6.5.15 and Figures 6-22, 6-23): open signs and lattice
    frameworks, and trussed towers."""

    lattice: list[LatticeCfRow] = Field(min_length=1)
    roundLimit: float = Field(
        gt=0, description="D√qz limit between the rounded-member columns, in ft·√psf."
    )
    squareTower: TowerCf
    triangularTower: TowerCf
    diagonalFactor: tuple[float, float] = Field(
        description="Square tower, wind on the diagonal: Cf × (1 + k·ε), at most the cap."
    )
    roundTower: TowerCf = Field(
        description="Factor on Cf of a tower of rounded members (a·ε² + b·ε + c), at most 1."
    )


# ─────────────────────────────────────── crane loads ───────────────────────────────────────


class CranesTable(TableModel):
    """Crane loads (BNBC 2020 Part 6 Sec 2.3, crane loads, the provisions of ASCE 7-05 Sec
    4.10): the vertical impact by kind of crane, the lateral force on the runway beams and the
    longitudinal force."""

    impact: dict[str, float] = Field(
        description="Vertical impact: share of the maximum wheel loads added, by crane kind."
    )
    lateral: float = Field(
        gt=0, description="Lateral force: share of the rated capacity plus hoist and trolley."
    )
    longitudinal: float = Field(gt=0, description="Longitudinal force: share of the wheel loads.")


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
    """Bar size sets [mm] by use (extra sets allowed; an extra set keeps its sizes as printed,
    integers or decimals: 9 Substructure's minimum mesh is written as given)."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)
    __pydantic_extra__: dict[  # type: ignore[assignment]
        str, list[Annotated[int, Field(gt=0)] | Annotated[float, Field(gt=0)]]
    ] = Field(init=False)

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
    plate: Share = Field(description="Flat plates and flat slabs.")
    wall: Share = Field(description="Cracked walls.")
    wallUncracked: Share | None = Field(
        default=None,
        description="Walls taken as uncracked (Project Settings > Analysis > Walls cracked off); "
        "the column factor when not given.",
    )


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


class PrestressLimits(_Group):
    """Prestressed slabs (BNBC 2020 Part 6 Chapter 9; ACI 318-11 Chapter 18): stress limits as
    multiples of f'ci, f'c or √f'c [MPa], the stress in unbonded tendons at nominal strength,
    the bonded reinforcement, precompression and tendon spacing, and punching with
    prestress."""

    jackingFpu: Share = Field(description="Jacking stress <= this × fpu.")
    jackingFpy: Share = Field(description="Jacking stress <= this × fpy.")
    anchorFpu: Share = Field(
        description="At the anchors immediately after transfer: stress <= this × fpu."
    )
    transferCompression: Positive = Field(description="At transfer: compression <= this f'ci.")
    transferTension: Positive = Field(description="At transfer: tension <= this √f'ci.")
    transferTensionEnds: Positive = Field(
        description="At transfer, at the ends of simply supported members: this √f'ci."
    )
    sustainedCompression: Positive = Field(
        description="Service, sustained load: compression <= this f'c."
    )
    totalCompression: Positive = Field(description="Service, total load: compression <= this f'c.")
    tensionTwoWay: Positive = Field(description="Two-way slabs, service tension <= this √f'c.")
    tensionClassU: Positive = Field(description="Class U (uncracked) tension <= this √f'c.")
    unbondedAdd: Positive = Field(description="Unbonded fps = fse + this + f'c / (k ρp) [MPa].")
    unbondedSpanDepth: Positive = Field(description="Span / depth dividing the two expressions.")
    unbondedK: tuple[Positive, Positive] = Field(description="k up to and above the span/depth.")
    unbondedCap: tuple[Positive, Positive] = Field(
        description="fps <= fse + this [MPa], up to and above the span/depth."
    )
    gammaP: Positive = Field(description="γp of bonded fps (fpy / fpu >= 0.9).")
    bondedNegative: Positive = Field(
        description="Two-way slabs: bonded top bars over the columns As >= this Acf."
    )
    bondedPositiveTension: Positive = Field(
        description="Two-way slabs: bonded bottom bars needed when tension > this √f'c."
    )
    bondedPositiveStress: Share = Field(description="As = Nc / (this × fy).")
    bondedOneWay: Positive = Field(description="Unbonded one-way: As >= this × Act.")
    minPrecompression: Positive = Field(description="Average precompression >= this [MPa].")
    spacingThickness: Positive = Field(description="Distributed tendons apart <= this × h.")
    spacingMax: Positive = Field(description="... and <= this [mm].")
    punchingBetaMax: Positive = Field(description="βp <= this.")
    punchingBetaA: Positive = Field(description="βp = this (1.5 + αs d / b0).")
    punchingFpc: Positive = Field(description="vc adds this × fpc.")
    punchingFpcRange: tuple[Positive, Positive] = Field(
        description="fpc each way within this range [MPa] for the expression to apply."
    )
    punchingRootMax: Positive = Field(description="√f'c <= this [MPa] in the expression.")


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
    #: The same with drop panels (BNBC 2020 Table 6.6.3's right-hand columns).
    twoWayThicknessDrop: dict[float, tuple[float, float, float]] | None = None
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
    prestress: PrestressLimits | None = Field(
        default=None, description="Prestressed slabs (saengine.design.prestress)."
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


class BarSpacing(_Group):
    """Least clear spacing of parallel bars (the 3D rebar cages' congestion check)."""

    layerMin: Positive = Field(description="Bars in a layer: at least this clear [mm].")
    layerDb: Positive = Field(description="Bars in a layer: at least this many db clear.")
    betweenLayers: Positive = Field(description="Between layers of bars, clear [mm].")
    columnMin: Positive = Field(description="Column bars: at least this clear [mm].")
    columnDb: Positive = Field(description="Column bars: at least this many db clear.")


class DetailingTable(TableModel):
    special: SpecialFrames
    joints: Joints
    walls: SpecialWalls
    lintels: LintelLimits
    #: None in a pack that gives no bar spacing limits: the congestion check is then skipped.
    spacing: BarSpacing | None = None


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
    betaCTT: Share = Field(default=0.6, description="βn of a C-T-T node.")
    betaPrism: Share = Field(default=1.0, description="βs of a prism-shaped strut.")
    betaBottle: Share = Field(
        default=0.75, description="βs of a bottle-shaped strut with distributed web steel."
    )
    betaBottlePlain: Share = Field(
        default=0.6, description="βs of a bottle-shaped strut without distributed web steel."
    )
    minAngle: Positive = Field(
        default=25.0, lt=90, description="Least angle between a strut and a tie [degrees]."
    )
    webRatio: Rho = Field(
        default=0.003,
        description="Distributed web steel ratio that confines a bottle-shaped strut.",
    )


class RetainingWallFactors(_Group):
    sliding: float = Field(default=1.5, ge=1, description="Least factor of safety on sliding.")
    overturning: float = Field(
        default=1.5, ge=1, description="Least factor of safety on overturning."
    )
    seismic: float = Field(
        default=1.1, ge=1, description="Least factor on sliding and overturning with earthquake."
    )
    passive: float = Field(
        default=2.0, ge=1, description="Factor of safety on the passive resistance in front."
    )
    flotation: float = Field(
        default=1.1, ge=1, description="Least factor of safety against flotation (uplift)."
    )
    baseFriction: Share = Field(
        default=2 / 3, description="Base friction angle as a share of φ' (tan δb, δb = r φ')."
    )
    adhesion: Share = Field(
        default=0.5, description="Base adhesion as a share of cu on a clay without φ'."
    )
    hFactor: float = Field(
        default=1.6, gt=0, description="Load factor on the lateral earth pressure H."
    )
    yieldingKh: Share = Field(
        default=0.5,
        description="kh of a wall free to yield as a share of the peak ground acceleration.",
    )


class FoundationsTable(TableModel):
    pileSafety: dict[str, tuple[float, float, float, float]]
    pileControls: list[str]
    partialSkin: float
    partialBase: float
    sptSafety: float
    noLoadTestSafety: float
    loadTestSafety: float
    strutAndTie: StrutAndTie
    retainingWall: RetainingWallFactors = Field(
        default_factory=RetainingWallFactors,
        description="Stability factors and load factors of retaining and basement walls.",
    )


class DeepBeam(_Group):
    spanRatio: Positive = Field(
        description="Clear span over depth at or below which a beam is deep."
    )
    loadDistance: Positive = Field(
        description="Concentrated loads within this many depths of a support make a beam deep."
    )
    shearLimit: Positive = Field(description="Vn at most this × √f'c bw d [MPa^0.5].")
    verticalRatio: Rho = Field(description="Least vertical web steel Av / (bw s).")
    horizontalRatio: Rho = Field(description="Least horizontal web steel Avh / (bw s2).")
    spacingDepth: Positive = Field(description="Web steel spacing at most d over this.")
    spacingMax: Positive = Field(description="Web steel spacing at most this [mm].")


class Corbel(_Group):
    spanRatio: Positive = Field(description="Largest shear span over depth av / d.")
    tensionShare: Share = Field(description="Least horizontal tension Nuc over Vu.")
    tensionMaxShare: Positive = Field(description="Largest horizontal tension Nuc over Vu.")
    friction: Positive = Field(description="μ of concrete cast monolithically (× λ).")
    shearCoefficient: Share = Field(description="Vn at most this × f'c bw d.")
    shearIntercept: Positive = Field(description="Vn at most (this + slope f'c) bw d [MPa].")
    shearSlope: Share = Field(description="Slope of the second Vn limit.")
    shearStressMax: Positive = Field(description="Vn at most this × bw d [MPa].")
    minSteel: Share = Field(description="Least As / (b d) over f'c / fy.")
    tiesShare: Share = Field(description="Closed ties Ah at least this × (As - An).")
    tiesDepth: Share = Field(description="Closed ties within this share of d next to As.")
    edgeDepth: Share = Field(description="Depth at the outer edge at least this × d.")


class Diaphragm(_Group):
    forceMin: Positive = Field(description="Fpx at least this × SDS I wpx.")
    forceMax: Positive = Field(description="Fpx at most this × SDS I wpx.")
    plateau: Positive = Field(description="SDS over the peak ground acceleration (2/3) Z S.")
    collectorCategories: list[str] = Field(
        description="Seismic Design Categories whose collectors take the Ω0 forces."
    )
    irregularIncrease: Positive = Field(
        description="Factor on the connection forces of irregular buildings."
    )


class TransferTable(TableModel):
    """Deep beams and transfer girders, corbels and brackets, diaphragm chords and collectors
    (BNBC 2020 Part 6 Sec 6.4.6, 6.4.7, 2.5.5.6)."""

    deepBeam: DeepBeam
    corbel: Corbel
    diaphragm: Diaphragm


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


# ───────────────────────────────────── building services ─────────────────────────────────────
# The services tables keep the numbers as the code prints them: an integer stays an integer (a
# report prints 260 lpcd, not 260.0), a decimal stays a decimal.

#: A number as printed (integer or decimal), positive or at least zero.
Num = Annotated[int, Field()] | Annotated[float, Field()]
PosNum = Annotated[int, Field(gt=0)] | Annotated[float, Field(gt=0)]
NonNegNum = Annotated[int, Field(ge=0)] | Annotated[float, Field(ge=0)]


class _Services(TableModel):
    """A services table: ``pages`` names where each clause is (clause id -> "BNBC 2020 Part 8
    Table 8.5.5 (p1046)"), which the program cites in its reports."""

    pages: dict[str, str] = Field(default_factory=dict, description="Clause id -> citation.")


class WaterOccupancy(_Row):
    label: str
    table: str = Field(description='The table the row is in, e.g. "8.5.1(a)".')
    row: str = Field(description="The row's category as printed.")
    full: NonNegNum | None = Field(description="lpcd, full facility; null where printed '---'.")
    restricted: NonNegNum | None = Field(description="lpcd, restricted facility.")
    group: str = Field(description="Part 3 occupancy group.")
    unit: Literal["person", "bed", "seat"] = "person"


class SizeStep(_Row):
    upTo: PosNum | None = Field(description="Upper bound of the step; null: above the last.")
    diameter: PosNum


class VelocityLimit(_Row):
    diameter: PosNum
    velocity: PosNum = Field(description="[m/s]")


class HunterRow(_Row):
    units: PosNum = Field(description="Fixture units.")
    tank: PosNum = Field(description="Flow with flush tanks [l/min].")
    valve: PosNum = Field(description="Flow with flush valves [l/min].")


class SupplyUnitsRow(_Row):
    cold: NonNegNum
    hot: NonNegNum
    total: NonNegNum
    minimum: Annotated[int, Field(ge=0)] = Field(description="Minimum supply pipe [mm].")


class DrainageUnitsRow(_Row):
    units: NonNegNum
    outlet: Annotated[int, Field(ge=0)] = Field(description="Minimum waste outlet [mm].")
    soil: bool = Field(description="A soil appliance (to a soil stack).")


class TrapUnits(_Row):
    diameter: PosNum
    units: PosNum


class StackRow(_Row):
    diameter: PosNum
    branch: PosNum = Field(description="Any horizontal fixture branch.")
    threeStoreys: PosNum | None = Field(description="One stack of 3 storeys or 3 intervals.")
    stackTotal: PosNum | None = Field(description="More than 3 storeys: total for the stack.")
    storeyTotal: PosNum | None = Field(description="More than 3 storeys: total at one storey.")


class BuildingDrainRow(_Row):
    diameter: PosNum
    units: list[PosNum | None] = Field(description="Fixture units by slope (drainSlopes).")


class VentRow(_Row):
    diameter: PosNum
    units: PosNum = Field(description="Fixture units connected.")
    lengths: dict[int, PosNum] = Field(description="Vent diameter -> maximum length [m].")


class BranchVentRow(_Row):
    diameter: PosNum
    slope: PosNum = Field(description="[mm/m]")
    lengths: dict[int, PosNum | None] = Field(
        description="Vent diameter -> maximum length [m]; null: no limit (NL)."
    )


class SepticTank(_Group):
    minVolume: PosNum = Field(description="[l]")
    minWidth: PosNum = Field(description="[mm]")
    minDepth: PosNum = Field(description="Liquid depth [mm].")
    lengthRatio: tuple[PosNum, PosNum] = Field(description="Length: at least, at most (widths).")
    maxUsers: PosNum
    sludge: PosNum = Field(description="[l/capita/year]")
    clearance: PosNum = Field(description="Liquid level to the cover slab [mm].")
    retention: PosNum = Field(description="[day]")
    desludging: PosNum = Field(description="[year]")
    twoChambers: PosNum = Field(description="Two chambers above this volume [l].")
    inletFraction: Share
    coverLive: PosNum = Field(description="Cover design live load [kPa].")
    flowCity: PosNum = Field(description="Waste water of groups A, C, D [lpcd].")
    flowOther: PosNum = Field(description="Waste water of other groups [lpcd].")


class Reduction(_Row):
    factor: Share


class AbsorptionRow(_Row):
    rate: PosNum = Field(description="Percolation [min / 25 mm], upper bound.")
    trench: PosNum = Field(description="Trench bottom [l/m²/day].")
    pit: PosNum = Field(description="Seepage pit wall [l/m²/day].")


class LeaderRow(_Row):
    diameter: PosNum
    area: PosNum = Field(description="Maximum projected roof area [m²].")
    flow: PosNum = Field(description="[l/min]")


class SlopedPipeRow(_Row):
    diameter: PosNum
    slopes: dict[int, tuple[PosNum, PosNum]] = Field(
        description="Slope [mm/m] -> (area m², flow l/min)."
    )


class PlumbingTable(_Services):
    """BNBC 2020 Part 8 Chapters 5-7: water supply, drainage, rainwater; and SAEngine's pipe
    data where the code is silent (marked in ``sources``)."""

    occupancies: dict[str, WaterOccupancy]
    familySize: Annotated[int, Field(gt=0)]
    officeAreaPerPerson: PosNum
    roofTankFraction: PosNum
    reservoirFraction: PosNum
    fireReserveHours: NonNegNum
    consumptionHours: PosNum
    peakFactor: PosNum
    tankDrain: list[SizeStep]
    tankOverflow: list[SizeStep]
    velocityLimits: list[VelocityLimit]
    maxHeadLoss: PosNum
    supplyDiameters: list[PosNum]
    flowPressureTank: PosNum
    flowPressureValve: PosNum
    maxStaticHead: PosNum
    highRise: PosNum
    hunter: list[HunterRow]
    supplyUnits: dict[str, SupplyUnitsRow]
    drainageUnits: dict[str, DrainageUnitsRow]
    trapUnits: list[TrapUnits]
    stacks: list[StackRow]
    drainSlopes: list[PosNum]
    buildingDrains: list[BuildingDrainRow]
    ventStacks: list[VentRow]
    branchVents: list[BranchVentRow]
    drainVelocity: tuple[PosNum, PosNum, PosNum] = Field(
        description="Least, self-cleansing and largest velocity [m/s]."
    )
    septic: SepticTank
    septicReduction: dict[str, Reduction]
    disposalDistances: dict[str, dict[str, NonNegNum | None]]
    treatmentTankDistances: dict[str, NonNegNum]
    absorption: list[AbsorptionRow]
    seepageCapacityFactor: PosNum
    seepageAboveWaterTable: NonNegNum
    percolationBySoil: dict[str, PosNum]
    tableRainfall: PosNum
    defaultRainfall: PosNum
    harvestPlot: PosNum
    harvestDays: dict[str, Annotated[int, Field(gt=0)]]
    leaders: list[LeaderRow]
    gutters: list[SlopedPipeRow]
    stormDrains: list[SlopedPipeRow]
    minStormDrain: PosNum
    outsideDiameter: dict[str, dict[int, PosNum]]
    hazenC: dict[str, PosNum]
    sleeveClearance: NonNegNum
    sleeveSizes: list[PosNum]
    shaftClearance: NonNegNum
    wetRoomKinds: dict[str, str]
    roomFixtures: dict[str, dict[str, Annotated[int, Field(ge=0)]]]

    @model_validator(mode="after")
    def _keys(self) -> PlumbingTable:
        for name in ("septicReduction",):
            for key in getattr(self, name):
                if key not in self.occupancies:
                    raise ValueError(f"{name}: no occupancy '{key}'")
        for kind, fixtures in self.roomFixtures.items():
            if kind not in self.wetRoomKinds:
                raise ValueError(f"roomFixtures: no wet room kind '{kind}'")
            for fixture in fixtures:
                if fixture not in self.supplyUnits:
                    raise ValueError(f"roomFixtures.{kind}: no fixture '{fixture}'")
        return self


class Station(_Row):
    """A row of Table 8.2.2: outside design conditions for summer [°C]."""

    name: str
    cooling: dict[str, tuple[Num, Num]] = Field(
        description="Level (0.4, 1, 2 %) -> (DB, mean coincident WB): the cooling load."
    )
    evaporation: dict[str, tuple[Num, Num]] = Field(
        description="Level -> (WB, mean coincident DB): cooling towers, evaporative equipment."
    )
    range: Num = Field(description="Mean daily range of the dry bulb.")
    latitude: Num = Field(ge=-90, le=90, description="[°N]")
    longitude: Num = Field(ge=-180, le=180, description="[°E]")


class InsideRow(_Row):
    """A row of Table 8.2.1: acceptable inside design conditions for summer."""

    label: str
    db: tuple[Num, Num] = Field(description="Dry bulb range [°C].")
    rh: tuple[Num, Num] | None = Field(description="Relative humidity range [%]; null: '--'.")


class VentilationRow(_Row):
    """A row of Table 8.2.3; null where the table prints '-'."""

    label: str
    group: str
    perPerson: NonNegNum | None = Field(description="Outdoor air per person [l/s].")
    perArea: NonNegNum | None = Field(description="Outdoor air per floor area [l/s per m²].")
    density: NonNegNum | None = Field(description="Persons per 100 m² (note a).")
    exhaust: NonNegNum | None = Field(default=None, description="[l/s per m²]")
    exhaustNote: str = Field(default="", description="An exhaust given otherwise (per room).")
    ach: NonNegNum | None = Field(default=None, description="Air changes per hour.")
    inside: int | None = Field(default=None, description="Row of 'inside' that applies.")


class LeastWindowShare(_Group):
    """Sec 4.5.1.2(a)-(c): the least window area as a share of the external wall, by the room's
    depth [m]."""

    shallowDepth: PosNum = Field(description="Rooms less deep than this take 'shallow'.")
    deepDepth: PosNum = Field(description="Rooms deeper than this take 'deep'.")
    shallow: Share
    medium: Share
    deep: Share


class HvacTable(_Services):
    """BNBC 2020 Part 8 Chapter 2 (air-conditioning) and Part 3 Chapter 4 (energy); SAEngine's
    stated assumptions where the code is silent (marked in ``sources``, listed in
    ``assumptions`` for the report)."""

    stations: dict[str, Station]
    defaultStation: str = Field(description="The station of a project without a site location.")
    designLevel: str = Field(description="The Table 8.2.2 level for cooling (Sec 2.12.2.1).")
    designMonths: list[Annotated[int, Field(ge=1, le=12)]]
    indoorDb: Num
    maxIndoorOutdoorDifference: PosNum
    settingsStation: dict[str, str] = Field(description="Project Settings location -> station.")
    inside: dict[int, InsideRow]
    ventilation: dict[str, VentilationRow]
    lpd: dict[str, PosNum] = Field(description="Table 3.4.5 [W/m²].")
    groupLpd: dict[str, str] = Field(description="Ventilation group -> row of 'lpd'.")
    shgcByWwr: dict[int, tuple[PosNum, PosNum]] = Field(
        description="Window-to-wall ratio [%] -> (SHGC, SC) limit."
    )
    overhangA: dict[float, NonNegNum] = Field(description="Projection factor -> correction A.")
    overhangFactor: PosNum
    leastWindowShare: LeastWindowShare
    equipment: dict[str, NonNegNum] = Field(description="Ventilation group -> [W/m²].")
    equipmentDefault: NonNegNum
    activity: dict[str, PosNum] = Field(description="Ventilation group -> heat per person [W].")
    activityDefault: PosNum
    supplyAirTemperature: Num
    supplyAirHumidity: PosNum
    designWindSpeed: NonNegNum
    siteElevation: Num
    timeZone: Num = Field(description="Hours from UTC.")
    assumptions: list[str]

    @model_validator(mode="after")
    def _keys(self) -> HvacTable:
        if self.defaultStation not in self.stations:
            raise ValueError(f"defaultStation: no station '{self.defaultStation}'")
        if not any(self.designLevel in s.cooling for s in self.stations.values()):
            raise ValueError(f"designLevel: no station has the level '{self.designLevel}'")
        for location, station in self.settingsStation.items():
            if station not in self.stations:
                raise ValueError(f"settingsStation.{location}: no station '{station}'")
        for key, row in self.ventilation.items():
            if row.inside is not None and row.inside not in self.inside:
                raise ValueError(f"ventilation.{key}: no inside row {row.inside}")
        for group, row in self.groupLpd.items():
            if row not in self.lpd:
                raise ValueError(f"groupLpd.{group}: no lpd row '{row}'")
        return self


class ElectricalUse(_Row):
    """A row of Table 8.1.17: the minimum unit load [W/m²]."""

    label: str
    nonAc: NonNegNum
    ac: NonNegNum | None = Field(description="With air conditioning; null: the table gives none.")
    lightningA: PosNum = Field(description="Table 8.1.27(a) index A of the row's kind.")
    lightningC: PosNum = Field(description="Table 8.1.27(b) index C of the row's kind.")


class SubstationArea(_Row):
    number: Annotated[int, Field(gt=0)] = Field(description="Number of transformers.")
    kva: PosNum
    transformerArea: PosNum = Field(description="[m²]")
    totalArea: PosNum = Field(description="With HT and LT panels, without generators [m²].")


class IndexRow(_Row):
    label: str
    index: PosNum


class IndexStep(_Row):
    upTo: PosNum
    index: PosNum


class IecLevel(_Row):
    sphere: PosNum = Field(description="Rolling sphere radius [m].")
    mesh: PosNum = Field(description="Mesh size [m].")
    downSpacing: PosNum = Field(description="Typical down-conductor spacing [m].")


class TransformerUnit(_Row):
    length: PosNum
    width: PosNum
    height: PosNum
    mass: PosNum = Field(description="[kg]")
    oil: PosNum = Field(description="[litres]")


class GeneratorSet(_Row):
    length: PosNum
    width: PosNum
    height: PosNum
    mass: PosNum = Field(description="[kg]")


class Busbar(_Row):
    width: PosNum
    depth: PosNum
    mass: PosNum = Field(description="[kg/m]")


class CableOd(_Row):
    amps: PosNum
    od: PosNum = Field(description="Outside diameter [mm].")


class Panel(_Row):
    width: PosNum
    depth: PosNum
    height: PosNum
    mass: PosNum = Field(description="[kg]")
    kvar: PosNum | None = Field(default=None, description="A capacitor bank's kvar.")


class LtPanel(_Group):
    section: PosNum = Field(description="Section width [mm].")
    depth: PosNum
    height: PosNum
    massPerM: PosNum = Field(description="[kg/m]")
    ampsPerSection: PosNum = Field(description="Amperes per section beyond the incomer.")


class ElectricalTable(_Services):
    """BNBC 2020 Part 8 Chapter 1 (electrical services) and Sec 4.2.1 (lifts); typical equipment
    data for the first layout and SAEngine practice where the code is silent (marked in
    ``sources``)."""

    uses: dict[str, ElectricalUse]
    loadFactor: Share
    substationKw: PosNum
    powerFactor: Share
    ltVoltage: PosNum
    substationHeight: tuple[PosNum, PosNum]
    transformerClearance: dict[str, PosNum]
    transformerSpacing: dict[str, PosNum]
    soakPitOil: PosNum
    substationAreas: list[SubstationArea]
    transformerSizes: list[PosNum]
    transformerMax: PosNum
    generatorClearance: PosNum
    generatorSpacing: PosNum
    generatorAreas: dict[int, PosNum] = Field(description="Capacity [kW] -> room area [m²].")
    generatorSizes: list[PosNum]
    generatorPf: Share
    fuelRate: PosNum
    fuelHours: PosNum
    essentialShare: Share
    dieselDensity: PosNum
    transformerOilDensity: PosNum
    liftStoreys: Annotated[int, Field(gt=0)]
    liftHeight: PosNum
    liftStandbyStoreys: Annotated[int, Field(gt=0)]
    liftStandbyHeight: PosNum
    shaftStoreys: Annotated[int, Field(gt=0)]
    shaftHeight: PosNum
    shaftSize: tuple[PosNum, PosNum]
    shaftArea: PosNum
    cableRiserStoreys: Annotated[int, Field(gt=0)]
    cableRiserArea: PosNum
    busbarStoreys: Annotated[int, Field(gt=0)]
    cableSpacing: PosNum
    busbarRange: tuple[PosNum, PosNum]
    openingClearance: NonNegNum
    trayClearance: NonNegNum
    openingStep: PosNum
    trayHeadroom: NonNegNum
    trayFill: Share
    trayWidths: list[PosNum]
    systemEarthOhm: PosNum
    electrodeSpacing: PosNum
    earthPit: PosNum
    lightningEarthOhm: dict[str, PosNum]
    construction: dict[str, IndexRow]
    structureUse: dict[str, IndexRow]
    contents: dict[str, IndexRow]
    isolation: dict[str, IndexRow]
    terrain: dict[str, IndexRow]
    heightIndex: list[IndexStep]
    thunderIndex: list[IndexStep]
    thunderOver: PosNum
    thunderDefault: PosNum
    marginalRisk: PosNum
    alwaysHeight: PosNum
    spikeArea: PosNum
    spikeHeight: PosNum
    roofConductorReach: PosNum
    downSingleArea: PosNum
    downFirstArea: PosNum
    downStepArea: PosNum
    downPerimeter: PosNum
    testBoxHeight: PosNum
    lightningSizes: dict[str, str]
    iecLevels: dict[str, IecLevel]
    rebarOhm: PosNum
    transformerOil: dict[int, TransformerUnit] = Field(description="kVA -> unit.")
    dryMass: PosNum
    generatorSets: dict[int | float, GeneratorSet] = Field(description="kVA -> set.")
    busbars: dict[int, Busbar] = Field(description="Rating [A] -> trunking.")
    cableOd: list[CableOd]
    ltPanel: LtPanel
    htPanel: Panel
    capacitorPanel: Panel
    targetPf: Share
    upsKgPerKva: PosNum
    batteryKgPerKwh: PosNum
    upsAutonomyMin: PosNum
    tankPlate: PosNum
    steelWeight: PosNum


class FireFlow(_Row):
    sprinkler: PosNum = Field(description="[l/min]")
    standpipe: PosNum = Field(description="Standpipe and hose [l/min].")


class PumpRating(_Row):
    rating: PosNum = Field(description="[l/min]")
    pipe: PosNum = Field(description="Minimum discharge pipe [mm].")


class PipeSchedule(_Row):
    size: PosNum = Field(description="Nominal size [mm].")
    light: PosNum | None = Field(description="Heads, light hazard; null: no limit.")
    ordinary: PosNum | None
    extra: PosNum | None


class Extinguisher(_Group):
    perUnit: PosNum = Field(description="Area per unit of A rating [m²].")
    rating: PosNum = Field(description="The smallest rating.")
    max: PosNum = Field(description="The largest area per extinguisher [m²].")


class FireTable(_Services):
    """BNBC 2020 Part 4 (fire protection): flows, durations, pressures, pump ratings, pipe
    schedules, sprinkler spacing; the NFPA values the code leaves out (from memory, marked in
    ``sources``) and SAEngine's pipe and pump assumptions."""

    highRiseHeight: PosNum = Field(description="[m]")
    highRiseStoreys: Annotated[int, Field(gt=0)]
    tallHeight: PosNum = Field(description="[m]")
    hazardOrder: list[str] = Field(description="Table 4.4.1's hazard classes, least first.")
    hazardLabels: dict[str, str]
    flows: dict[str, FireFlow] = Field(description="Hazard -> flows (one riser, riserArea).")
    riserArea: PosNum = Field(description="[m²]")
    hazardOfGroup: dict[str, str] = Field(
        description="Part 3 occupancy group (or its letter) -> hazard class."
    )
    durationHeights: tuple[PosNum, PosNum] = Field(description="[m]")
    durations: dict[str, tuple[PosNum, PosNum, PosNum]] = Field(description="[min] by height.")
    additionalStandpipeFlow: PosNum
    maxAdditionalStandpipes: Annotated[int, Field(ge=0)]
    hosePressure: dict[str, PosNum] = Field(description="[kPa]")
    combinedPressure: PosNum
    maxPressure: PosNum
    prvPressure: PosNum
    gravityHeight: dict[str, PosNum] = Field(description="[m]")
    hoseSize: dict[str, PosNum] = Field(description="[mm]")
    hoseLength: PosNum
    outletHeight: PosNum
    wetRiserMin: PosNum
    supportExtra: NonNegNum = Field(description="[kg]")
    hangerFactor: PosNum
    hangerSpacing: PosNum = Field(description="[m]")
    testStandpipe: PosNum = Field(description="[kPa]")
    testSprinkler: PosNum = Field(description="[kPa]")
    pumpMinNet: PosNum = Field(description="[kPa]")
    pumpRatings: list[PumpRating]
    steelSchedule: list[PipeSchedule]
    copperSchedule: list[PipeSchedule]
    riserFloorArea: dict[str, PosNum] = Field(description="[m²]")
    coverage: dict[str, dict[str, tuple[PosNum, PosNum]]] = Field(
        description="Construction -> hazard family -> (area m², spacing m)."
    )
    densityArea: dict[str, tuple[PosNum, PosNum]] = Field(
        description="Hazard -> (density l/min/m², design area m²)."
    )
    hoseAllowance: dict[str, tuple[PosNum, PosNum]] = Field(description="(l/min, min)")
    kFactor: PosNum
    minHeadPressure: PosNum = Field(description="[kPa]")
    designAreaLength: PosNum
    jockeyShare: Share
    jockeyAbove: PosNum = Field(description="[kPa]")
    overloadFlow: PosNum
    overloadHead: Share
    extinguisher: dict[str, Extinguisher]
    extinguisherTravel: PosNum = Field(description="[m]")
    extinguisherSmallFloor: PosNum = Field(description="[m²]")
    detectorArea: PosNum = Field(description="[m²]")
    callPointArea: PosNum = Field(description="[m²]")
    steelBore: dict[int, PosNum] = Field(description="Nominal size -> inside diameter [mm].")
    copperBore: dict[int, PosNum]
    hazenC: dict[str, PosNum]
    steelMass: dict[int, PosNum] = Field(description="Nominal size -> [kg/m].")
    maxVelocity: PosNum = Field(description="[m/s]")
    pumpEfficiency: Share
    jockeyEfficiency: Share
    motorSizes: list[PosNum] = Field(description="[kW]")
    pumpClearance: NonNegNum = Field(description="[m]")
    controllerStrip: NonNegNum = Field(description="[m]")
    pumpCentre: NonNegNum = Field(description="[m]")

    @model_validator(mode="after")
    def _keys(self) -> FireTable:
        for hazard in self.hazardOrder:
            if hazard not in self.flows or hazard not in self.durations:
                raise ValueError(f"hazardOrder: '{hazard}' needs flows and durations")
        for group, hazard in self.hazardOfGroup.items():
            if hazard not in self.flows:
                raise ValueError(f"hazardOfGroup.{group}: no hazard '{hazard}'")
        return self


class RolledSection(_Row):
    designation: PosNum = Field(description="The size in the name, e.g. 300 of IPE 300.")
    h: PosNum = Field(description="Depth [mm].")
    b: PosNum = Field(description="Flange width [mm].")
    tw: PosNum = Field(description="Web thickness [mm].")
    tf: PosNum = Field(description="Flange thickness (mean, for tapered flanges) [mm].")
    r: NonNegNum = Field(description="Root radius [mm].")


class RolledFamily(_Row):
    """A family of rolled I sections or channels; ``source`` names the standard."""

    shape: Literal["I", "U"]
    sections: list[RolledSection] = Field(min_length=1)


class AngleSection(_Row):
    leg: PosNum = Field(description="[mm]")
    t: PosNum = Field(description="Thickness [mm].")
    r1: NonNegNum = Field(description="Root radius [mm].")


class AngleFamily(_Row):
    """Equal angles; the toe radius is ``toeRadiusShare`` of the root radius."""

    toeRadiusShare: NonNegNum
    sections: list[AngleSection] = Field(min_length=1)


class BoxSize(_Row):
    h: PosNum
    b: PosNum


class WallRange(_Group):
    """Walls rolled for a hollow section: those whose slenderness (the smaller side or the
    diameter over the wall) is within [minRatio, maxRatio]."""

    walls: list[PosNum] = Field(min_length=1)
    minRatio: PosNum
    maxRatio: PosNum


class HollowFamilies(_Row):
    """Cold-formed hollow sections by size; ``source`` names the standard."""

    shs: list[PosNum] = Field(description="Square sizes [mm].")
    rhs: list[BoxSize] = Field(description="Rectangular sizes [mm].")
    chs: list[PosNum] = Field(description="Outside diameters [mm].")
    boxWalls: WallRange
    chsWalls: WallRange


class SteelSectionsTable(TableModel):
    """The standard table of rolled and hollow steel sections SAEngine designs with: the
    nominal dimensions of each family, as its standard publishes them (``source`` of each
    family); the properties are computed from them (:mod:`saengine.library.steel_sections`)."""

    density: PosNum = Field(description="Mass density of the steel [kg/m³].")
    families: list[str] = Field(description="The families, in the order the workbench lists them.")
    shapeFamilies: dict[str, list[str]] = Field(
        description="Profile shape -> the families a member of it can be redesigned into."
    )
    rolled: dict[str, RolledFamily]
    angles: AngleFamily
    hollow: HollowFamilies
    notes: list[str] = Field(default_factory=list, description="Shown with the table.")

    @model_validator(mode="after")
    def _keys(self) -> SteelSectionsTable:
        known = {*self.rolled, "L", "SHS", "RHS", "CHS"}
        for family in self.families:
            if family not in known:
                raise ValueError(f"families: no family '{family}'")
        for shape, families in self.shapeFamilies.items():
            for family in families:
                if family not in self.families:
                    raise ValueError(f"shapeFamilies.{shape}: no family '{family}'")
        return self


class LiveElementFactors(_Group):
    interiorColumn: Positive
    exteriorColumn: Positive = Field(description="Exterior columns without cantilever slabs.")
    edgeColumnCantilever: Positive = Field(description="Edge columns with cantilever slabs.")
    cornerColumnCantilever: Positive = Field(description="Corner columns with cantilever slabs.")
    interiorBeam: Positive
    edgeBeam: Positive = Field(description="Edge beams without cantilever slabs.")
    other: Positive = Field(description="All other members (one-way slabs, cantilevers ...).")


class LiveReductionTable(TableModel):
    """Reduction of floor live loads by influence area (BNBC 2020 Part 6 Sec 2.3.13)."""

    influenceMin: Positive = Field(description="Least KLL AT [m²] that is reduced.")
    constant: Share = Field(description="a of L = L0 (a + b / √(KLL AT)).")
    coefficient: Positive = Field(description="b of L = L0 (a + b / √(KLL AT)) [m].")
    minOneFloor: Share = Field(description="Least L / L0 of members supporting one floor.")
    minFloors: Share = Field(description="Least L / L0 of members supporting two or more.")
    heavyLive: Positive = Field(description="Live loads above this [kN/m²] are not reduced.")
    heavyFactor: Share = Field(description="L / L0 of heavy loads on members of 2+ floors.")
    notReduced: list[str] = Field(description="Area uses never reduced.")
    twoFloorsOnly: list[str] = Field(description="Area uses reduced only on 2+ floors.")
    kll: LiveElementFactors


class FireResistanceTable(TableModel):
    """Least sizes and covers of concrete members for a fire resistance rating, one value per
    rating of ``ratings`` (hours)."""

    ratings: list[Positive] = Field(min_length=1, description="Fire resistance ratings [h].")
    slabThickness: list[Positive] = Field(description="Least slab thickness [mm].")
    slabCover: list[Positive] = Field(description="Least slab cover to the bars [mm].")
    wallThickness: list[Positive] = Field(description="Least wall thickness [mm].")
    beamCover: list[Positive] = Field(description="Least beam cover to the main bars [mm].")
    beamWidth: Positive = Field(description="Least beam width the beam covers hold for [mm].")
    columnSize: list[Positive] = Field(description="Least column dimension [mm].")
    columnCoverPerHour: Positive = Field(description="Column cover per hour of rating [mm].")
    columnCoverMax: Positive = Field(description="Column cover need not exceed [mm].")

    @model_validator(mode="after")
    def _same_length(self) -> FireResistanceTable:
        n = len(self.ratings)
        for name in ("slabThickness", "slabCover", "wallThickness", "beamCover", "columnSize"):
            if len(getattr(self, name)) != n:
                raise ValueError(f"{name}: one value per rating ({n})")
        return self


# ───────────────────────────────────────── timber ─────────────────────────────────────────

TimberLocation = Literal["inside", "outside", "wet"]


class TimberGroup(BaseModel):
    """Permissible stresses of a strength group [MPa], by location of use where they differ."""

    model_config = ConfigDict(extra="forbid")

    label: str
    E: Positive = Field(description="Modulus of elasticity [MPa].")
    bending: dict[TimberLocation, Positive]
    tension: dict[TimberLocation, Positive]
    shearHorizontal: Positive
    shearAlong: Positive
    compressionParallel: dict[TimberLocation, Positive]
    compressionPerpendicular: dict[TimberLocation, Positive]


class TimberColumn(_Group):
    short: Positive = Field(description="Le/d up to which a column is short.")
    k8: Positive = Field(description="K8 = k8 √(E/Fc), where long columns start.")
    intermediate: Positive = Field(description="Fc [1 - (Le/(d K8))⁴ / intermediate].")
    long: Positive = Field(description="Long columns: long · E / (Le/d)².")
    maxSlenderness: Positive = Field(description="Largest Le/d.")


class TimberDepthFactor(_Group):
    above: Positive = Field(description="Depth [mm] above which K3 applies.")
    factor: Positive
    a: Positive
    b: Positive


class TimberDuration(_Group):
    permanent: Positive
    wind: Positive
    earthquake: Positive


class TimberDeflection(_Group):
    span: Positive
    cantilever: Positive


class TimberTable(TableModel):
    """Permissible stress design of sawn timber: stresses by strength group and location, the
    column formulas, the depth factor, load duration factors and deflection limits."""

    groups: dict[str, TimberGroup] = Field(min_length=1)
    column: TimberColumn
    depthFactor: TimberDepthFactor
    duration: TimberDuration
    deflection: TimberDeflection


# ───────────────────────────────────────── masonry ─────────────────────────────────────────


class MasonryPhi(_Group):
    """φ of masonry (strength design)."""

    axialFlexureReinforced: Phi
    axialFlexureUnreinforced: Phi
    shear: Phi
    bearing: Phi


class MasonryAxial(_Group):
    reduction: Share = Field(description="Pn = reduction × [stress × An f'm] × R(h/r).")
    slendernessBreak: Positive = Field(description="h/r where the long-wall formula starts.")
    short: Positive = Field(description="R = 1 - (h / (short r))² up to the break.")
    long: Positive = Field(description="R = (long r / h)² above the break.")


class MasonryStressBlock(_Group):
    stress: Share = Field(description="Stress of the block as a share of f'm.")
    depth: Share = Field(description="Depth of the block a as a share of c.")


class MasonryPlainShear(_Group):
    """Vn of unreinforced masonry [MPa]: the least of root √f'm, cap, and the bond's
    constant + axialShare Nu/An."""

    root: Positive
    cap: Positive
    runningBond: Positive
    runningBondGrouted: Positive
    stackBond: Positive
    axialShare: Positive


class MasonryReinforcedShear(_Group):
    """Vnm = masonry [first - slope Mu/(Vu dv)] An √f'm + axialShare Pu; Vns = steelShare
    (Av/s) fy dv; Vn ≤ maxLow An √f'm at Mu/(Vu dv) ≤ 0.25, maxHigh at ≥ 1 [MPa]."""

    masonry: Positive
    first: Positive
    slope: Positive
    axialShare: Positive
    steelShare: Positive
    maxLow: Positive
    maxHigh: Positive


class MasonrySteelStrain(_Group):
    """α of the extreme tension steel strain α εy at εmu, by wall detailing."""

    ordinary: Positive
    intermediate: Positive
    special: Positive


class MasonrySlenderWall(_Group):
    axialMax: Share = Field(description="Pu/Ag at most this × f'm.")
    axialSlender: Share = Field(description="Above this × f'm, h/t is limited.")
    heightThickness: Positive = Field(description="Largest h/t above axialSlender.")


class MasonryOrdinaryWalls(_Group):
    maxSpacing: Positive = Field(description="Largest bar spacing, each way [mm].")
    leastBarArea: Positive = Field(description="Least area of a vertical bar [mm²].")


class MasonryPrisms(BaseModel):
    """f'm from the unit's strength by mortar type (MPa), one value per entry of ``fm``."""

    model_config = ConfigDict(extra="forbid")

    fm: list[Positive] = Field(min_length=2)
    MS: list[Positive] = Field(description="Unit strength with type M or S mortar.")
    N: list[Positive] = Field(description="Unit strength with type N mortar.")

    @model_validator(mode="after")
    def _same_length(self) -> MasonryPrisms:
        if len(self.MS) != len(self.fm) or len(self.N) != len(self.fm):
            raise ValueError("one unit strength per f'm")
        for row in (self.fm, self.MS, self.N):
            if any(row[k + 1] <= row[k] for k in range(len(row) - 1)):
                raise ValueError("the values must increase")
        return self


MasonryUnitKind = Literal["clay", "concrete"]
MortarType = Literal["M", "S", "N"]


class MasonryTable(TableModel):
    """Strength design of masonry walls: φ, Em, εmu, the stress block, axial strength and
    slenderness, the modulus of rupture, shear, the steel limits and f'm from the units."""

    phi: MasonryPhi
    modulusRatio: dict[MasonryUnitKind, Positive] = Field(description="Em / f'm by unit.")
    ultimateStrain: dict[MasonryUnitKind, Positive] = Field(description="εmu by unit.")
    stressBlock: MasonryStressBlock
    axial: MasonryAxial
    fmRange: dict[MasonryUnitKind, tuple[Positive, Positive]] = Field(
        description="f'm range of strength design by unit [MPa]."
    )
    modulusOfRupture: dict[Literal["solid", "hollow", "grouted"], dict[MortarType, Positive]] = (
        Field(description="fr normal to the bed joints [MPa].")
    )
    plainShear: MasonryPlainShear
    reinforcedShear: MasonryReinforcedShear
    maxSteelStrain: MasonrySteelStrain
    slenderWall: MasonrySlenderWall
    ordinaryWalls: MasonryOrdinaryWalls
    mortarFromMix: dict[Literal["M", "S"], Positive] = Field(
        description="Largest sand parts per cement part of a nominal mortar mix of each type."
    )
    prismStrength: dict[MasonryUnitKind, MasonryPrisms]


# ───────────────────────────────────────── planning ─────────────────────────────────────────


class PlotBand(_Row):
    maxArea: float | None = Field(
        description="Largest plot area of the row [m²]; null: every larger plot."
    )
    maxKatha: float | None = Field(default=None, description="The same in katha (720 sq ft).")


class PlanningRow(_Row):
    road: float = Field(gt=0, description="Road width the row needs [m].")
    far: float | None = Field(
        default=None, gt=0, description="Largest FAR; null: not restricted (NR)."
    )
    mgc: float = Field(gt=0, le=100, description="Maximum ground coverage [% of the plot].")


class PlanningUse(_Row):
    name: str
    table: str = Field(description="The table of the rules, e.g. 'Table 3(A)'.")
    rows: list[PlanningRow | None] = Field(
        description="One per plot band (plotBands); null: the use is not permitted there."
    )
    wideRoads: list[PlanningRow] = Field(
        default_factory=list, description="Rows for any plot size on a wide road."
    )


class NarrowRoad(_Row):
    minRoad: float = Field(gt=0)
    maxRoad: float = Field(gt=0)
    far: float = Field(gt=0)
    mgc: float = Field(gt=0, le=100)
    rule: str = ""


class RoadIncrement(_Row):
    step: float = Field(gt=0, description="Road width step [m].")
    far: float = Field(ge=0, description="FAR added per step.")
    fromRoad: float = Field(ge=0)
    toRoad: float = Field(gt=0)
    rule: str = ""


class SetbackRow(_Row):
    front: float = Field(ge=0)
    rear: float = Field(ge=0)
    side: float = Field(ge=0)


class PlanningSetbacks(_Row):
    rows: list[SetbackRow] = Field(description="One per plot band [m].")
    highRise: SetbackRow
    highRiseHeight: float = Field(gt=0, description="Above this height [m] the high-rise row.")
    highRiseStoreys: int = Field(gt=0, description="Or above this many storeys.")
    rule: str = ""


class RoadCentre(_Row):
    distance: float = Field(ge=0, description="Least distance from the road's centre [m].")
    boundary: float = Field(ge=0, description="Least distance from the plot boundary [m].")
    rule: str = ""


class BetweenBuildings(_Row):
    frontRear: float = Field(ge=0)
    side: float = Field(ge=0)
    rule: str = ""


class PlanningTable(TableModel):
    """Planning rules of the plot: FAR and maximum ground coverage by use, plot size and road
    width, and the setbacks (the planning authority's rules BNBC Part 3 defers to)."""

    authority: str = Field(description="Whose rules these are.")
    plotBands: list[PlotBand] = Field(min_length=1)
    uses: dict[str, PlanningUse]
    narrowRoads: list[NarrowRoad] = Field(default_factory=list)
    roadIncrement: RoadIncrement
    setbacks: PlanningSetbacks
    roadCentre: RoadCentre
    betweenBuildings: BetweenBuildings | None = None
    storeyHeightMax: float | None = Field(
        default=None, description="Largest storey height counted once in the floor area [m]."
    )

    @model_validator(mode="after")
    def _rows(self) -> PlanningTable:
        n = len(self.plotBands)
        for key, use in self.uses.items():
            if len(use.rows) != n:
                raise ValueError(f"uses.{key}.rows: {len(use.rows)} rows for {n} plot bands")
        if len(self.setbacks.rows) != n:
            raise ValueError(f"setbacks.rows: {len(self.setbacks.rows)} rows for {n} plot bands")
        return self


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
    "transfer": TransferTable,
    "slabCoefficients": SlabCoefficientsTable,
    "plumbing": PlumbingTable,
    "hvac": HvacTable,
    "electrical": ElectricalTable,
    "fire": FireTable,
    "steelSections": SteelSectionsTable,
    "liveReduction": LiveReductionTable,
    "fireResistance": FireResistanceTable,
    "planning": PlanningTable,
    "timber": TimberTable,
    "masonry": MasonryTable,
    "cranes": CranesTable,
}


#: Merge keys of the tables' lists (path -> key, :mod:`saengine.codes.merge`): a pack that
#: extends another changes one combination by naming it, the others are kept.
MERGE_KEYS: dict[str, dict[str, str]] = {
    "combinations": {
        "strength": "name",
        "service": "name",
        "allowable": "name",
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
