"""The data tables of a code pack: one pydantic model per table.

A code pack (:mod:`saengine.codes`) keeps the reference data and the plain-number factors of a
design code in ``data/<table>.json`` files; this module defines what each table holds, so a pack
is validated (and its JSON Schema generated) from the same models the program reads. The models
cover what SAEngine uses today with the default pack and are kept general enough for other
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
    clauses: dict[str, str] = Field(
        default_factory=dict,
        description="Short clause references the results cite, by key, without the code's name "
        "(e.g. 'Part 6 Sec 2.5.7.3'); read by saengine.codes.context.cite. A key the pack does "
        "not give is not cited.",
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


class Town(_Row):
    """A town of the code's hazard tables and where it is (WGS 84), for the map's suggestion."""

    name: str = Field(description="The town as the code spells it.")
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    z: float | None = Field(
        default=None, gt=0, description="Seismic zone coefficient Z; empty: not in the table."
    )
    windSpeed: float | None = Field(
        default=None, gt=0, description="Basic wind speed V [m/s]; empty: not in the table."
    )
    location: str | None = Field(
        default=None, description="Its ``locations`` id (Project Settings), where there is one."
    )


class TownMap(_Row):
    """The towns of the code's zone and wind tables with their coordinates: the site map
    suggests the nearest one's Z and V (D3: they were module constants of ``gis/towns.py``)."""

    area: str = Field(description="Where the code applies (for the outside-the-area note).")
    bounds: tuple[float, float, float, float] = Field(
        description="(south, west, north, east) [degrees] of the area."
    )
    zClause: str = Field(description="The table of the towns' Z.")
    windClause: str = Field(description="The table of the towns' V.")
    governs: str = Field(default="", description="What governs over the nearest town.")
    towns: list[Town] = Field(min_length=1)


class LocationsTable(TableModel):
    """Towns with their seismic zone and basic wind speed."""

    locations: dict[str, Location]
    default: str | None = Field(
        default=None,
        description="C7: the town a new project under this pack starts with; empty: the first "
        "of ``locations``.",
    )
    towns: TownMap | None = Field(
        default=None,
        description="Towns with coordinates for the site map's suggestion; empty: the pack "
        "does not cover the suggestion.",
    )


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
    concentrated: float | None = Field(
        default=None,
        ge=0,
        description="Minimum concentrated live load [kN], applied alone (not with the uniform "
        "load) on the patch ``patch``; empty: none.",
    )
    patch: float | None = Field(
        default=None,
        gt=0,
        description="Side of the square the concentrated load acts on [mm]; empty: the table's "
        "``concentratedPatch``.",
    )
    reducible: bool = Field(
        default=True, description="False: the uniform load is never reduced (a nonreducible row)."
    )
    roof: bool = Field(
        default=False,
        description="A roof live load (case Lr): reduced by the roof rule, not the floor rule.",
    )
    note: str | None = Field(default=None, description="The row's notes, for the user.")
    category: str | None = Field(
        default=None,
        description="The code's category of use (A, B, C1 ...), where the code groups the uses "
        "(the area-and-storeys reduction reads it); empty: none.",
    )


class RoofLiveRow(_Row):
    """A row of the minimum roof live loads by type and slope (pitched roofs by slope = rise /
    run, arched roofs and domes by rise / span)."""

    id: str
    name: str
    live: float | None = Field(
        default=None, ge=0, description="Distributed load [kN/m²]; empty: as the floor table."
    )
    concentrated: float | None = Field(default=None, ge=0, description="Concentrated load [kN].")
    slopeMin: float | None = Field(default=None, ge=0, description="Least slope (rise / run).")
    slopeMax: float | None = Field(
        default=None, gt=0, description="Slope (rise / run) the row stops below."
    )
    riseMin: float | None = Field(
        default=None, ge=0, description="Least rise / span of an arched roof or dome."
    )
    riseMax: float | None = Field(
        default=None, gt=0, description="Rise / span the row stops below."
    )


class PartitionAllowance(_Row):
    """Uniform live load in lieu of light partitions not shown on the plans."""

    share: Share = Field(description="Uniform load per kN/m of partition weight [kN/m² per kN/m].")
    minimum: Positive = Field(description="Least uniform partition allowance [kN/m²].")
    lightMax: Positive = Field(
        description="Heaviest partition [kN/m] the uniform allowance stands in for."
    )
    loadCase: Literal["L", "SD"] | None = Field(
        default=None,
        description="Load case the allowance belongs to: L (a live load: factored, reduced and "
        "in the seismic weight as the floor live load) or SD (superimposed dead). Empty: L. A "
        "project setting may choose either.",
    )


class VehicleLoads(_Row):
    """Concentrated loads where vehicles are used or stored, applied without the uniform load."""

    vehicleShare: Share = Field(description="Each load as a share of the heaviest vehicle.")
    spacing: Positive = Field(description="Spacing of the loads [m].")
    patch: Positive = Field(description="Side of the square each load acts on [mm].")
    wheel: Positive = Field(description="Least wheel load of private vehicle storage [kN].")
    jack: Positive = Field(description="Jack load of passenger vehicle garages [kN].")
    jackPatch: Positive = Field(description="Side of the jack footprint [mm].")
    mechanicalWheel: Positive = Field(
        description="Load per wheel of mechanical parking without a slab [kN]."
    )


class BarrierRow(_Row):
    id: str
    name: str
    load: Positive = Field(description="Line load [kN/m] or vehicle barrier force [kN].")
    unit: Literal["kN/m", "kN"] = "kN/m"
    widthMax: float | None = Field(default=None, gt=0, description="Applies up to this width [m].")
    widthMin: float | None = Field(default=None, gt=0, description="Applies above this width [m].")
    massMax: float | None = Field(default=None, gt=0, description="Vehicle gross mass up to [kg].")
    massMin: float | None = Field(default=None, gt=0, description="Vehicle gross mass above [kg].")


class BarrierLoads(_Row):
    """Live loads on handrails, parapets and vehicle barriers."""

    rows: list[BarrierRow]
    vehicleLength: Positive = Field(description="Length a vehicle force spreads over [m].")
    bumperHeight: Positive = Field(description="Bumper height of light vehicles [mm].")
    rampShare: Share = Field(description="Ramp barrier force as a share of the row's.")
    rampHeight: Positive = Field(description="Height of the ramp barrier force [mm].")
    longRampLength: Positive = Field(description="Straight exit ramps longer than this [m] ...")
    longRampFactor: Positive = Field(description="... take the row's force times this.")


class ImpactRow(_Row):
    id: str
    name: str
    vertical: float = Field(ge=0, description="Vertical impact, share of the static load.")
    horizontal: float | None = Field(default=None, ge=0, description="Horizontal share.")


class AreaLoadsTable(TableModel):
    """Minimum live loads by use of the floor area, with their concentrated loads, the roof
    live loads by slope, the partition allowance, vehicle and barrier loads, and the impact of
    equipment."""

    uses: dict[str, AreaUse]
    concentratedPatch: float | None = Field(
        default=None, gt=0, description="Side of the square a concentrated load acts on [mm]."
    )
    roofLive: list[RoofLiveRow] = Field(default_factory=list)
    partitions: PartitionAllowance | None = None
    vehicles: VehicleLoads | None = None
    barriers: BarrierLoads | None = None
    impact: list[ImpactRow] = Field(default_factory=list)


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
    #: The code's number of the combination ("2", "5W" ...), for the exceptions and the report.
    id: str | None = None
    name: str
    #: Load case kind -> factor. Kinds: D (incl. SD), L, Lr, W, E, F, T, H, R, ... ("W" and "E"
    #: expand to the plan directions and signs in the program, "T" to + and -).
    factors: dict[str, float]
    note: str | None = Field(
        default=None,
        description="What the row adds beyond the code (an adoption), shown with it in the report.",
    )


class FactorException(_Row):
    """A code's permitted change of one factor in some combinations (``rows``: their ids)."""

    case: str = Field(description="Load case kind whose factor changes (L, W ...).")
    to: float = Field(description="The factor it may take instead.")
    rows: list[str] = Field(description="Ids of the strength combinations it applies to.")
    liveMax: float | None = Field(
        default=None, gt=0, description="Only where every floor live load L0 ≤ this [kN/m²]."
    )
    excludedUses: list[str] = Field(
        default_factory=list, description="Area uses (garages, assembly) it never applies to."
    )
    directionality: float | None = Field(
        default=None,
        gt=0,
        description="Only when the wind's directionality factor is this (W not reduced by it).",
    )
    material: str | None = Field(
        default=None, description="Only for members of this material category (concrete)."
    )


class CantileverUplift(_Row):
    """A net upward force on horizontal cantilevers, in addition to the combinations."""

    factor: Positive = Field(description="Upward force as a share of the dead load.")
    categories: list[str] = Field(description="Seismic Design Categories it applies in.")


class FloodCombinations(_Row):
    """The combinations of one kind of flood zone."""

    strength: list[Combination] = Field(default_factory=list)
    allowable: list[Combination] = Field(default_factory=list)
    note: str | None = None


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
    optionalCases: list[str] = Field(
        default_factory=lambda: ["F", "H", "T", "R"],
        description="Load case kinds a combination is formed without when the model has no such "
        "case (a model without basement walls has no H).",
    )
    alternates: dict[str, list[str]] = Field(
        default_factory=dict,
        description="A case and the cases that may take its place at the same factor ('Lr or "
        "R'): each combination with the case is also formed with each alternate the model has.",
    )
    exceptions: dict[str, FactorException] = Field(
        default_factory=dict,
        description="Permitted factor changes of the strength combinations, by name.",
    )
    allowableStressIncrease: float | None = Field(
        default=None,
        ge=1,
        description="Allowable stress increase with the overstrength seismic load Em in the "
        "allowable stress combinations ``allowableStressIncreaseRows``.",
    )
    allowableStressIncreaseRows: list[str] = Field(
        default_factory=list, description="Ids of the allowable stress combinations it applies to."
    )
    upliftDeadFactor: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="Factor on the dead load that resists uplift in allowable stress design.",
    )
    cantileverUplift: CantileverUplift | None = None
    # B16: the combinations of a structure in a flood or tidal surge zone.
    withLateral: list[str] = Field(
        default_factory=list,
        description="Case kinds that act in the direction of a row's wind or earthquake (the "
        "flood load Fa with the wind that drives it): they expand with it.",
    )
    flood: dict[str, FloodCombinations] = Field(
        default_factory=dict,
        description="Combinations formed in a flood or tidal surge zone, by kind of zone "
        "(coastal, inland); the project's flood zone chooses one.",
    )
    pDeltaPreload: dict[str, Annotated[float, Field(ge=0)]] | None = Field(
        default=None,
        description="D6: load case -> factor of the gravity preload of a P-Delta analysis (the "
        "gravity part of the seismic strength combination); empty: the generic default "
        "(codes/generic), named in the report.",
    )
    # C4: a code with alternative sets of strength combinations (EN 1990 6.10 or 6.10a/b).
    strengthSets: dict[str, list[Combination]] = Field(
        default_factory=dict,
        description="Alternative sets of strength combinations by id; ``strengthSet`` chooses "
        "the one that becomes ``strength`` (every reader then sees that set).",
    )
    strengthSet: str | None = Field(
        default=None,
        description="Id of the set of ``strengthSets`` used as ``strength`` (a project may "
        "choose another by overriding this value); empty: ``strength`` as given.",
    )
    strengthSetLabels: dict[str, str] = Field(
        default_factory=dict, description="Readable name of each set, for the report."
    )

    @model_validator(mode="after")
    def _chosen_set(self) -> CombinationsTable:
        if self.strengthSet is None:
            return self
        chosen = self.strengthSets.get(self.strengthSet)
        if chosen is None:
            raise ValueError(
                f"strengthSet '{self.strengthSet}' is not one of the strengthSets "
                f"({', '.join(self.strengthSets) or 'none'})"
            )
        self.strength = list(chosen)
        return self


# ─────────────────────────────────────────── seismic ───────────────────────────────────────────


class SiteClass(_Row):
    description: str
    # The spectrum's shape by site class (zoneFactor hazard). A pack whose spectrum comes from
    # the site's mapped values (``designSpectrum.method`` mappedSpectral) leaves them at their defaults.
    S: float = Field(default=1.0, gt=0, description="Soil factor.")
    TB: float = Field(default=0.0, ge=0)
    TC: float = Field(default=0.0, ge=0)
    TD: float = Field(default=0.0, ge=0)
    vs30: tuple[float | None, float | None] | None = Field(
        default=None,
        description="(lower, upper) average shear wave speed of the top 30 m [m/s] of the "
        "class, where the code defines the class by it; empty: by the description.",
    )


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
    planDimension: bool = Field(
        default=False,
        description="C7: T = Ct·h^m / √d, d the base plan dimension along the shaking [m] "
        "(False: T = Ct·h^m).",
    )


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
    100ξ)), at least ``minimum``; ``none``: η = dampingEta; ``table`` (alpha 9 C9b): η of
    ``points`` (ξ, η), linear between, the end values outside."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["none", "squareRoot", "table"] = "none"
    referenceDamping: float = Field(default=0.05, gt=0, lt=1)
    numerator: float = 10.0
    offset: float = 5.0
    minimum: float = 0.0
    points: list[tuple[float, float]] = Field(
        default_factory=list, description="(ξ, η) of the method 'table', ξ ascending."
    )


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


# ── B12: building irregularities, dynamic analysis trigger, soft storey ──


class StoreyRatio(BaseModel):
    """A storey irregular when its value is below ``storeyAbove`` × the storey above's, or
    below ``threeAbove`` × the mean of the three storeys above (empty: not checked)."""

    model_config = ConfigDict(extra="forbid")

    storeyAbove: float | None = Field(default=None, gt=0, le=1)
    threeAbove: float | None = Field(default=None, gt=0, le=1)


class AdjacentRatio(BaseModel):
    """Irregular when a storey's value is more than ``adjacent`` × an adjacent storey's."""

    model_config = ConfigDict(extra="forbid")

    adjacent: float = Field(gt=1)
    #: Mass: a roof lighter than the floor below is not compared. Geometry: a one-storey
    #: penthouse is not compared.
    topExempt: bool = True


class StoreyStrength(BaseModel):
    """How a storey's lateral strength is estimated for the weak storey check. ``shearStrength``:
    the sum of the nominal shear strengths of the storey's columns and structural walls in the
    direction, Vn = concreteFactor·λ·√f'c·bw·d + Av·fyt·d/s, d = depthFactor × the depth."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["shearStrength"] = "shearStrength"
    concreteFactor: float = Field(gt=0)
    depthFactor: float = Field(gt=0, le=1)


class Irregularities(BaseModel):
    """Plan and vertical irregularity thresholds (each block empty: not checked)."""

    model_config = ConfigDict(extra="forbid")

    #: Re-entrant corner: both projections beyond it more than this share of the plan dimension.
    reentrantProjection: float | None = Field(default=None, gt=0, lt=1)
    #: Diaphragm discontinuity: open area more than this share of the gross enclosed area.
    openingShare: float | None = Field(default=None, gt=0, lt=1)
    #: Diaphragm discontinuity: effective stiffness changing by more than this share.
    diaphragmStiffnessChange: float | None = Field(default=None, gt=0, lt=1)
    #: Non-parallel systems: an element more than this many degrees off the major axes.
    nonparallelTolerance: float | None = Field(default=None, gt=0, lt=45)
    #: Seismic Design Categories where non-parallel systems ask for the orthogonal combination.
    nonparallelOrthogonal: list[str] = Field(default_factory=list)
    #: Out-of-plane offsets (plan) and in-plane discontinuity (vertical): checked when True.
    offsets: bool = False
    #: In-plane discontinuity: an in-plane offset more than this × the element's length.
    inPlaneOffset: float | None = Field(default=None, gt=0)
    soft: StoreyRatio | None = None
    extremeSoft: StoreyRatio | None = None
    mass: AdjacentRatio | None = None
    geometry: AdjacentRatio | None = None
    weak: StoreyRatio | None = None
    extremeWeak: StoreyRatio | None = None
    strength: StoreyStrength | None = None
    #: Which irregularity types count as plan ("plan") or vertical ("vertical") ones, with the
    #: pack's display label: type id -> {"group", "label"}.
    labels: dict[str, dict[str, str]] = Field(default_factory=dict)
    clauses: dict[str, str] = Field(default_factory=dict)


class DynamicAnalysis(BaseModel):
    """When the equivalent static method is not enough. ``regularHeights`` and
    ``irregularHeights``: height [m] above which dynamic analysis is required, by seismic zone
    ("1".."4"); ``recommendedIrregular``: zones where it is recommended for an irregular building
    below that height. The static procedure also needs T below ``periodTcFactor`` × TC and
    ``periodMax`` and no vertical irregularity (``verticalIrregularity``)."""

    model_config = ConfigDict(extra="forbid")

    regularHeights: dict[str, float] = Field(default_factory=dict)
    irregularHeights: dict[str, float] = Field(default_factory=dict)
    recommendedIrregular: list[str] = Field(default_factory=list)
    periodTcFactor: float | None = Field(default=None, gt=0)
    periodMax: float | None = Field(default=None, gt=0)
    verticalIrregularity: bool = False
    clause: str = ""
    staticClause: str = ""


class SoftStoreyDesign(BaseModel):
    """Design of a soft storey without the overstrength factor. ``forceFactors``: the soft
    storey's columns and beams take ``frameFactor`` × the earthquake forces, its structural walls
    ``wallFactor`` ×; ``types``: the irregularity types that make a storey soft."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["forceFactors"] = "forceFactors"
    frameFactor: float = Field(gt=1)
    wallFactor: float = Field(gt=1)
    types: list[str] = Field(default_factory=list)
    clause: str = ""


class DiaphragmConnections(BaseModel):
    """The connection force increase of irregular buildings (the factor is the pack's
    ``transfer.diaphragm.irregularIncrease``): in the ``categories`` with an irregularity of
    ``types``. ``wingTypes``: irregularities whose projecting wings need chords and collectors
    for independent motion, satisfied by a dynamic 3D analysis when ``wingsDynamicExempt``."""

    model_config = ConfigDict(extra="forbid")

    categories: list[str] = Field(default_factory=list)
    types: list[str] = Field(default_factory=list)
    wingTypes: list[str] = Field(default_factory=list)
    wingsDynamicExempt: bool = False
    clause: str = ""
    wingsClause: str = ""


class TimeHistoryTarget(BaseModel):
    """The spectrum records are scaled to: the design spectrum with ``R`` and ``I`` (empty: the
    building's own)."""

    model_config = ConfigDict(extra="forbid")

    R: float | None = Field(default=None, gt=0)
    I: float | None = Field(default=None, gt=0)


class TimeHistoryRules(BaseModel):
    """Ground motion suites of the response history procedures (B19; B36 for the nonlinear
    target). ``method``: how a suite is scaled (``periodRange``: the mean spectrum of the
    records, or of the pairs' SRSS spectra, is not below ``singleRatio`` / ``pairRatio`` times
    the target spectrum at every period from ``periodLower``·T to ``periodUpper``·T, the
    spectra ``spectrumDamping`` damped); ``minimumRecords`` per suite; ``meanFrom``: from this
    many records (or pairs) the design value is the mean of their peaks, fewer the largest;
    ``baseShearShare``: the responses are scaled by share·V/Vth where the suite's base shear
    Vth is below share·V (the equivalent static V); ``scaleDrifts``: that factor also on the
    displacements and drifts; ``simultaneousPairs``: a pair's components act together (no
    orthogonal 100 % + 30 % rule); ``targets``: by procedure (``linear``, ``nonlinear``)."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["periodRange"] = "periodRange"
    minimumRecords: int = Field(ge=1)
    periodLower: float = Field(gt=0)
    periodUpper: float = Field(gt=0)
    spectrumDamping: float = Field(default=0.05, gt=0, lt=1)
    singleRatio: float = Field(gt=0)
    pairRatio: float = Field(gt=0)
    meanFrom: int = Field(ge=1)
    baseShearShare: float = Field(default=1.0, gt=0)
    scaleDrifts: bool = True
    simultaneousPairs: bool = True
    targets: dict[str, TimeHistoryTarget] = Field(default_factory=dict)
    clauses: dict[str, str] = Field(default_factory=dict)


# ── C1: the seismic hazard of the site from mapped spectral values (saengine.fem.spectral_hazard) ──


class CsLimits(BaseModel):
    """Bounds of the seismic response coefficient Cs of the equivalent lateral force method:
    Cs ≥ max(``sdsFactor``·SDS·Ie, ``floor``) and, where S1 ≥ ``nearFaultS1``,
    Cs ≥ ``nearFaultFactor``·S1 / (R/Ie)."""

    model_config = ConfigDict(extra="forbid")

    sdsFactor: float = Field(ge=0)
    floor: float = Field(ge=0)
    nearFaultS1: float | None = Field(default=None, gt=0)
    nearFaultFactor: float | None = Field(default=None, gt=0)


class MultiPeriodRule(BaseModel):
    """SMS and SM1 from a multi-period MCER spectrum (Sa [g] by T [s]): SMS = ``smsShare`` ×
    the largest Sa from ``smsPeriods[0]`` to ``smsPeriods[1]``, at least Sa at the first;
    SM1 = the largest T·Sa from ``sm1Periods[0]`` to ``sm1Periods[1]`` (``sm1PeriodsSoft`` for
    the ``softClasses``); SDS, SD1 = ``designShare`` × them. Used when the project gives the
    MCER spectrum and not SDS and SD1."""

    model_config = ConfigDict(extra="forbid")

    smsShare: Share
    smsPeriods: tuple[Positive, Positive]
    sm1Periods: tuple[Positive, Positive]
    sm1PeriodsSoft: tuple[Positive, Positive] | None = None
    softClasses: list[str] = Field(default_factory=list)


class DesignSpectrumRule(BaseModel):
    """The design spectrum: a method id the pack picks (C4, C1). Empty: ``reducedElastic``.

    - ``reducedElastic`` (the default pack's): Sa = pgaFactor·Z·I/R·Cs(T), Cs the elastic shape
      of the site class (S, TB, TC, TD; :func:`saengine.fem.loads.design_acceleration`).
    - ``behaviourFactor`` (EN 1998-1 3.2.2.5): ag = Z·I, Sd = ag·S·[2/3 + T/TB·(2.5/q - 2/3)] up
      to TB, ag·S·2.5/q to TC, ·TC/T to TD, ·TC·TD/T² beyond, at least ``lowerBound``·ag from TC
      (:mod:`saengine.fem.spectra`); R stands for q.
    - ``mappedSpectral`` (ASCE 7-22 Ch 11-12, :mod:`saengine.fem.spectral_hazard`): the site's
      SDS and SD1 (and S1, TL) entered from the code's hazard tool (Site > Mapped spectral
      values) instead of a zone: a two-period spectrum (T0 = ``t0Share``·TS, TS = SD1/SDS;
      ``rampStart``·SDS at T = 0 up to SDS at T0, SDS to TS, SD1/T to TL, SD1·TL/T² beyond) or
      the site's multi-period design spectrum, × I/R; the equivalent lateral force coefficient
      Cs = SDS/(R/Ie) ≤ SD1/(T R/Ie) (SD1 TL/(T² R/Ie) beyond TL) within ``csLimits``; the
      Seismic Design Category read by the band of SDS and SD1 (``sdsBands``, ``sd1Bands``, the
      more severe; the band after the last where S1 ≥ ``s1Extreme``) as zone packs read it by
      zone; the period's upper limit Cu·Ta from ``periodUpper`` by SD1. The fields after
      ``lowerBound`` are this method's."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["reducedElastic", "behaviourFactor", "mappedSpectral"] = "reducedElastic"
    plateau: float = Field(default=2.5, gt=0, description="Spectral amplification of the plateau.")
    lowerBound: float = Field(default=0.0, ge=0, lt=1, description="β: least Sd / ag.")
    clause: str = ""
    # C7 (reducedElastic): the factor on Z·I/R·Cs, the long-period branch and the static plateau.
    factor: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="reducedElastic: Sa = factor·Z·I/R·Cs (IS 1893: Z/2); empty: 2/3.",
    )
    longPeriod: Literal["inverseSquare", "constant"] = Field(
        default="inverseSquare",
        description="reducedElastic: beyond TD the normalized spectrum falls as TC·TD/T² or stays "
        "at its value at TD.",
    )
    staticPlateau: bool = Field(
        default=False,
        description="reducedElastic: the equivalent static method takes the plateau below TB "
        "(no rising branch); the dynamic analysis the full shape.",
    )
    # ── mappedSpectral (C1) ──
    designShare: Share | None = Field(
        default=None, description="SDS = share × SMS, SD1 = share × SM1 (mapped values)."
    )
    t0Share: Share | None = Field(default=None, description="T0 = share × TS.")
    rampStart: Share | None = Field(
        default=None, description="Sa at T = 0 as a share of SDS (the ramp to T0)."
    )
    sdsBands: list[Positive] = Field(
        default_factory=list, description="SDS [g] at which each band from the second starts."
    )
    sd1Bands: list[Positive] = Field(
        default_factory=list, description="SD1 [g] at which each band from the second starts."
    )
    s1Extreme: Positive | None = Field(
        default=None, description="S1 [g] from which the band after the last one applies."
    )
    csLimits: CsLimits | None = None
    periodUpper: list[tuple[Positive, Positive]] = Field(
        default_factory=list,
        description="(SD1 [g], Cu) points: T ≤ Cu·Ta, Cu linear between, held beyond.",
    )
    multiPeriod: MultiPeriodRule | None = None
    clauses: dict[str, str] = Field(default_factory=dict)


class LateralForceRule(BaseModel):
    """C4: the lateral force method. Base shear × ``correction`` when T ≤ ``periodTcFactor``·TC
    and the building has more than ``minStoreys`` - 1 storeys (EN 1998-1 4.3.3.2.2 λ = 0.85);
    ``distribution``: ``heightPower`` (Fx ∝ wx·hx^k, k 1 to 2 with T) or ``linear`` (Fi ∝ zi·mi,
    EN 1998-1 4.3.3.2.3 with the linear mode shape)."""

    model_config = ConfigDict(extra="forbid")

    correction: float = Field(default=1.0, gt=0, le=1)
    periodTcFactor: float | None = Field(default=None, gt=0)
    minStoreys: int = Field(default=0, ge=0)
    # C7: "heightSquared" (IS 1893 7.6.3, Qi ∝ Wi·hi² whatever the period).
    distribution: Literal["heightPower", "linear", "heightSquared"] = "heightPower"
    minimumShare: dict[int, Annotated[float, Field(gt=0, lt=1)]] = Field(
        default_factory=dict,
        description="C7: least base shear V / W by seismic zone (IS 1893 Table 7); empty: none.",
    )
    clause: str = ""


class StabilityRule(BaseModel):
    """θ, a method id (C4, C1). ``elasticOverImportance`` (the default pack's): θ = Px δe/(I Vx
    h), θmax = 0.5/Cd ≤ ``thetaCap``; ``elasticDrift`` (ASCE 7-22 Eq 12.8-16, θ = Px Δ Ie/(Vx
    hsx Cd) with Δ = Cd δe/Ie): θ = Px δe/(Vx h), θmax = 0.5/Cd ≤ ``thetaCap``; ``designDrift``
    (EN 1998-1 4.4.2.2): θ = Ptot dr/(Vtot h) with dr = Cd·de (Cd standing for qd), θmax =
    ``thetaCap``. Below ``ignoreBelow`` second order effects need not be taken into account; up
    to ``amplifyUpTo`` they may be by 1/(1 - θ)."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["elasticOverImportance", "elasticDrift", "designDrift"] = (
        "elasticOverImportance"
    )
    ignoreBelow: float = Field(default=0.10, gt=0, lt=1)
    amplifyUpTo: float | None = Field(default=None, gt=0, lt=1)
    thetaCap: float = Field(default=0.25, gt=0, lt=1)
    clause: str = ""


class SeismicTable(TableModel):
    """Site classes, spectrum, systems, SDC and the plain numbers of the seismic analysis."""

    siteClasses: dict[str, SiteClass]
    systems: dict[str, StructuralSystem]
    periodCoefficients: dict[str, PeriodCoefficient]
    designCategories: DesignCategories
    requiredDetailing: dict[str, Literal["special", "intermediate", "ordinary"]]
    allowableDrift: dict[str, float] = Field(description="Δa/hsx by occupancy category.")
    allowableDriftLabel: str = Field(
        default="", description="The structures allowableDrift is for."
    )
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
    # B12: empty in a pack that does not cover them (the feature is then not covered).
    irregularities: Irregularities | None = None
    dynamicAnalysis: DynamicAnalysis | None = None
    softStorey: SoftStoreyDesign | None = None
    diaphragmConnections: DiaphragmConnections | None = None
    # B19: the response history procedures; empty in a pack that does not cover them.
    timeHistory: TimeHistoryRules | None = None
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
    partitionWeight: Literal["full", "withLiveShare"] | None = Field(
        default=None,
        description="How the area loads' partition allowance counts in the seismic weight: "
        "full (100 %, like the dead load; the live share and its threshold use the floor live "
        "load without it) or withLiveShare (as live load, the threshold judged on the live "
        "load with it). Empty: the generic default (full).",
    )
    periodUpperFactor: float | None = Field(
        default=None,
        ge=1,
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
    stabilityGravity: dict[str, Annotated[float, Field(ge=0)]] | None = Field(
        default=None,
        description="D6: load case -> factor of the gravity load Px of the stability "
        "coefficient θ; empty: the generic default (codes/generic), named in the report.",
    )
    # ── C4: generic methods a pack picks by id (empty: the default pack's methods) ──
    spectrumType: str | None = Field(
        default=None,
        description="Id of the spectrum of ``spectra`` whose site parameters become "
        "``siteClasses`` (EN 1998-1 Type 1 or Type 2); a project chooses another by "
        "overriding this value. Empty: ``siteClasses`` as given.",
    )
    spectra: dict[str, dict[str, SiteClass]] = Field(
        default_factory=dict,
        description="Site parameters (S, TB, TC, TD) by spectrum type id, then site class.",
    )
    designSpectrum: DesignSpectrumRule | None = Field(
        default=None,
        description="How the design spectrum follows from the elastic one; empty: "
        "reducedElastic, Sa = pgaFactor·Z·I/R·Cs(T).",
    )
    lateralForce: LateralForceRule | None = Field(
        default=None,
        description="The base shear correction and the distribution of the lateral force "
        "method; empty: no correction, Fx ∝ wx·hx^k with k from the period.",
    )
    driftAmplification: Literal["overImportance", "displacementFactor", "designForces"] | None = (
        Field(
            default=None,
            description="Design displacements from the elastic ones: overImportance (Cd·δe/I) or "
            "displacementFactor (qd·de, Cd standing for qd, the importance already in de); "
            "designForces (C7, IS 1893 7.11): the drift checked as computed from the design "
            "forces, the separation with Cd·de (Cd standing for R). Empty: overImportance.",
        )
    )
    defaultSiteClass: str | None = Field(
        default=None, description="C7: the site class of a new project under this pack."
    )
    defaultSystem: str | None = Field(
        default=None, description="C7: the structural system of a new project under this pack."
    )
    generatorSystems: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Alpha 9 C3b: the New Building generator's candidate systems by its system "
        "kind (steelMomentFrame, steelBracedFrame), least ductile first: the first one the "
        "category and the height permit is taken; a kind not listed takes the generator's own.",
    )
    stability: StabilityRule | None = Field(
        default=None,
        description="The interstorey drift sensitivity coefficient θ; empty: θ = Px δe/(I Vx "
        "h) with θmax = 0.5/Cd ≤ 0.25.",
    )

    @model_validator(mode="after")
    def _chosen_spectrum(self) -> SeismicTable:
        if self.spectrumType is None:
            return self
        chosen = self.spectra.get(self.spectrumType)
        if chosen is None:
            raise ValueError(
                f"spectrumType '{self.spectrumType}' is not one of the spectra "
                f"({', '.join(self.spectra) or 'none'})"
            )
        self.siteClasses = dict(chosen)
        return self


# ───────────────────────────────────────────── wind ─────────────────────────────────────────────


class Exposure(_Row):
    description: str
    # The power-law profile (wind.method "powerLaw"); empty in a pack whose method uses the
    # logarithmic profile (z0, zmin) instead.
    alpha: float | None = Field(default=None, gt=0)
    zg: float | None = Field(default=None, gt=0, description="Gradient height [m].")
    # C4: the logarithmic profile of a terrain category (wind.method "peakVelocityPressure").
    z0: float | None = Field(default=None, gt=0, description="Roughness length z0 [m].")
    # The terrain constants of the gust-effect factor (the default pack's Part 6 Table 6.2.10); None: a
    # pack without them gives rigid buildings only.
    c: float | None = Field(default=None, gt=0, description="Turbulence intensity factor c.")
    l: float | None = Field(default=None, gt=0, description="Integral length scale ℓ [m].")
    epsilonBar: float | None = Field(default=None, gt=0, description="Integral length ε̄.")
    alphaBar: float | None = Field(default=None, gt=0, description="Mean-speed power ᾱ.")
    bBar: float | None = Field(default=None, gt=0, description="Mean-speed factor b̄.")
    zmin: float | None = Field(
        default=None,
        gt=0,
        description="z_min of z̄ [m]; with peakVelocityPressure the least height zmin of the "
        "logarithmic profile.",
    )


class WindDesignCasesRow(_Row):
    """The design wind load cases of the main wind-force resisting system (the default pack's Part 6
    Sec 2.4.11.3 and Figure 6.2.9): read by :func:`saengine.fem.loads.wind_design_cases`."""

    partial: float = Field(gt=0, le=1, description="Case 2: share of the pressure with torsion.")
    eccentricity: float = Field(ge=0, description="Case 2 and 4: e / B.")
    simultaneous: float = Field(gt=0, le=1, description="Case 3: share of each direction.")
    simultaneousTorsional: float = Field(
        gt=0, le=1, description="Case 4: share of each direction with both torsions."
    )
    exemptHeight: float = Field(gt=0, description="Exception: one-storey height limit h [m].")


class FlexibleGustRow(_Row):
    """The gust-effect factor Gf of a flexible or dynamically sensitive building (the default pack's Part 6
    Sec 2.4.8.2): read by :func:`saengine.fem.loads.flexible_gust_factor`."""

    frequencyLimit: float = Field(gt=0, description="A building below n1 [Hz] is flexible.")
    gQ: float = Field(gt=0, description="Peak factor of the background response gQ.")
    gv: float = Field(gt=0, description="Peak factor of the wind response gv.")
    heightFactor: float = Field(gt=0, description="z̄ = heightFactor · h.")
    lead: float = Field(gt=0, description="The factor before the fraction (0.925).")
    damping: float = Field(gt=0, lt=1, description="Damping ratio β of a concrete building.")
    eccentricity: Literal["gustWeighted"] | None = Field(
        default=None,
        description="Torsional eccentricity of a flexible building: gustWeighted, e from eQ "
        "and eR weighted by the background and resonant responses "
        "(:func:`saengine.fem.loads.flexible_eccentricity`); None: the rigid e.",
    )


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


class CladdingPointCurve(_Row):
    """One external pressure coefficient (GCp) of components and cladding by effective wind area:
    (area [m²], GCp) points, linear in log A between them, the end values beyond the ends."""

    zone: str
    sign: Literal["positive", "negative"]
    points: list[tuple[float, float]] = Field(min_length=1)


class CladdingRoofTable(_Row):
    """The (GCp) of the roofs of one form over a range of roof angles θ (angleFrom < θ ≤
    angleTo) for low-rise buildings (read by :func:`saengine.fem.loads.cladding_pressures`)."""

    forms: list[str] = Field(
        min_length=1, description="Roof forms this figure covers (gable, hip, monoslope, ...)."
    )
    angleFrom: float = Field(ge=0, description="θ above this [°] ...")
    angleTo: float = Field(gt=0, description="... up to this [°].")
    roof: list[CladdingPointCurve] = Field(
        default_factory=list, description="Roof zones; empty: the low-rise flat-roof curves."
    )
    overhang: list[CladdingPointCurve] = Field(
        default_factory=list, description="Roof overhangs (top and bottom surfaces together)."
    )
    zoneLabels: dict[str, str] = Field(
        default_factory=dict, description="What each zone of this figure is (its plan)."
    )
    cornerAsEdge: dict[str, float] = Field(
        default_factory=dict,
        description="Form -> θ [°] up to which roof zone 3 is treated as zone 2 (hip roofs).",
    )
    parapetCornerAsEdge: bool = Field(
        default=False,
        description="A parapet of at least the cladding table's parapetCorner turns zone 3 into "
        "zone 2 on this figure's roofs.",
    )
    envelopeForm: str | None = Field(
        default=None,
        description="Also take the larger magnitude of this form's figure at the same angle "
        "(zone by its number), where the code's text points to both.",
    )
    note: str | None = None


class CladdingSteppedRoof(_Row):
    """The lower level of a flat stepped roof: its zones at the roof-upper wall intersection
    renamed (``zoneMap``), and the wall's positive (GCp) on a strip b = widthFactor·h1 ≤
    widthMax wide; the figure's limits on h1 and the ratios."""

    zoneMap: dict[str, str]
    widthFactor: float = Field(gt=0)
    widthMax: float = Field(gt=0, description="b at most this [m].")
    minUpperHeight: float = Field(gt=0, description="h1 at least this [m].")
    heightRatio: tuple[float, float] = Field(description="hi/h range.")
    widthRatio: tuple[float, float] = Field(description="Wi/W range.")


class CladdingDomeTable(_Row):
    """Domes on a circular base: (GCp) by the angle θ from the springline (0) to the top (90),
    with q at the top of the dome; the figure's range of hD/D and f/D."""

    negative: float = Field(lt=0, description="(GCp) suction over the whole dome.")
    positive: list[tuple[float, float]] = Field(
        min_length=1, description="(θ up to [°], positive GCp) bands."
    )
    baseMax: float = Field(gt=0, description="hD/D up to this.")
    riseRange: tuple[float, float] = Field(description="f/D range.")


class CladdingArchedTable(_Row):
    """Arched roofs: at the perimeter, the roof figures with θ the springline slope; elsewhere
    the MWFRS arched roof Cp times ``interiorFactor``."""

    interiorFactor: float = Field(gt=0)


class CladdingTable(_Row):
    """Components and cladding (the default pack's Part 6 Sec 2.4.11.5): the (GCp) curves of walls and
    flat roofs (θ ≤ 10°) of low-rise (h ≤ ``lowRiseHeight``) and taller buildings, the internal
    pressure coefficients and the edge-zone width a."""

    lowRiseHeight: float = Field(gt=0, description="h [m] up to which the low-rise curves hold.")
    lowRise: list[CladdingCurve]
    highRise: list[CladdingCurve]
    lowRiseWallFactor: float = Field(
        gt=0, le=1, description="Factor on the low-rise wall (GCp) for a roof θ ≤ 10°."
    )
    internal: dict[str, float] | None = Field(
        default=None,
        description="(GCpi) magnitude by enclosure; None: the wind table's internalPressure.",
    )
    edgeFraction: float = Field(gt=0, description="a ≤ edgeFraction · least plan dimension.")
    edgeHeightFraction: float = Field(gt=0, description="Low-rise: a ≤ this · h.")
    edgeMinFraction: float = Field(gt=0, description="a ≥ this · least plan dimension.")
    edgeMin: float = Field(gt=0, description="a ≥ this [m].")
    parapetCorner: float = Field(
        gt=0, description="A parapet this high [m] or more turns roof zone 3 into zone 2."
    )
    # B14: pitched and other roof forms (low-rise figures), and their limits.
    wallFactorMaxAngle: float | None = Field(
        default=None, description="lowRiseWallFactor only for a roof θ up to this [°]; None: any."
    )
    roofs: list[CladdingRoofTable] = Field(
        default_factory=list, description="Roof figures by form and angle; empty: flat roofs only."
    )
    highRiseRoofsFrom: float | None = Field(
        default=None,
        description="h above lowRiseHeight with a roof θ above this [°]: the low-rise roof "
        "figures with qh; None: the high-rise flat-roof curves at any θ.",
    )
    parapetPositive: dict[str, str] = Field(
        default_factory=dict,
        description="With a parapet (as parapetCorner): roof zone -> wall zone whose positive "
        "(GCp) the roof zone takes.",
    )
    stepped: CladdingSteppedRoof | None = None
    domes: CladdingDomeTable | None = None
    arched: CladdingArchedTable | None = None


class InternalPressureTable(_Row):
    """Internal pressure coefficients (GCpi) by enclosure classification and the reduction
    factor Ri of a partially enclosed building with one unpartitioned large volume:
    Ri = reductionBase·(1 + 1/√(1 + Vi/(volumeFactor·Aog))) ≤ 1, Vi the internal volume [m³],
    Aog the total area of openings in the envelope [m²]
    (read by :func:`saengine.fem.loads.internal_pressure_coefficient`)."""

    coefficients: dict[str, float] = Field(description="(GCpi) magnitude by enclosure.")
    reducedEnclosures: list[str] = Field(
        default_factory=list, description="Enclosures whose (GCpi) Ri may reduce."
    )
    reductionBase: float = Field(default=0.5, gt=0, le=1)
    volumeFactor: float = Field(gt=0, description="The constant before Aog in Ri [m].")


class RoofCpRow(_Row):
    """One h/L row of a roof pressure coefficient table: per tabulated angle, the first
    (suction) and second (pressure, where two are listed) Cp; None where none is printed (0.0 for
    interpolation)."""

    hOverL: float = Field(ge=0)
    first: list[float | None]
    second: list[float | None] | None = None


class RoofParallelZone(_Row):
    """A zone of the roof by its horizontal distance from the windward edge (in multiples of
    h): Cp values listed (one or two)."""

    upTo: float | None = Field(
        default=None, description="Zone ends this many h from the windward edge; None: the rest."
    )
    cp: list[float] = Field(min_length=1)


class RoofParallelRow(_Row):
    hOverL: float = Field(ge=0)
    zones: list[RoofParallelZone] = Field(min_length=1)


class RoofCpTable(_Row):
    """Roof pressure coefficients Cp of the main wind-force resisting system (all heights): the
    windward and leeward slopes for wind normal to the ridge (θ ≥ ``flatAngle``) by θ and h/L,
    and the zones by distance from the windward edge for θ < ``flatAngle`` and wind parallel to
    the ridge. Values between rows and angles are interpolated linearly between values of the
    same column."""

    angles: list[float] = Field(min_length=2, description="Windward slope angles θ [°].")
    windward: list[RoofCpRow] = Field(min_length=1)
    steepFrom: float = Field(description="θ [°] from which Cp = steepFactor·θ.")
    steepFactor: float
    verticalFrom: float = Field(description="θ [°] above which the slope takes verticalCp.")
    verticalCp: float
    leewardAngles: list[float] = Field(min_length=1)
    leeward: list[RoofCpRow] = Field(min_length=1)
    flatAngle: float = Field(gt=0, description="θ [°] below which the roof is flat.")
    parallel: list[RoofParallelRow] = Field(min_length=1)
    reducible: float | None = Field(
        default=None, description="The Cp value that may be reduced with its area."
    )
    areaReduction: list[tuple[float, float]] = Field(
        default_factory=list, description="(area [m²], factor) points of that reduction."
    )


class DomeCurve(_Row):
    """Cp at one point of a dome (A windward springline, B top, C leeward springline) against
    f/D, for one hD/D."""

    hdOverD: float = Field(ge=0)
    points: list[tuple[float, float]] = Field(min_length=2, description="(f/D, Cp) points.")


class DomeTable(_Row):
    """Domed roofs on a circular base: Cp at A, B and C by f/D and hD/D, Case A interpolated
    along arcs A-B-C, Case B constant A up to ``caseBAngle`` then to B and C."""

    minRise: float = Field(gt=0, description="Below this f/D, the planar roof table holds.")
    caseBAngle: float = Field(gt=0, lt=90)
    A: list[DomeCurve] = Field(min_length=1)
    B: list[DomeCurve] = Field(min_length=1)
    C: list[DomeCurve] = Field(min_length=1)


class ArchRow(_Row):
    """A rise-to-span range of an arched roof: windward quarter Cp = a·r + b (and the alternate
    coefficient that shall also be used, where given)."""

    elevated: bool = Field(description="Roof on an elevated structure (else from the ground).")
    riseFrom: float = Field(ge=0)
    riseTo: float = Field(gt=0)
    windward: tuple[float, float]
    alternate: tuple[float, float] | None = None


class ArchedTable(_Row):
    """Arched roofs: windward quarter by r, centre half Cp = a·r + b, leeward quarter Cp."""

    rows: list[ArchRow] = Field(min_length=1)
    centre: tuple[float, float]
    leeward: float


class LowRiseRow(_Row):
    angle: float = Field(ge=0, le=90, description="Roof angle θ [°].")
    gcpf: dict[str, float] = Field(description="(GCpf) by building surface (1-6, 1E-4E).")


class LowRiseTable(_Row):
    """Low-rise buildings: the combined (GCpf) by building surface and roof angle, the end
    zones 2a wide, the zone 2 extent, the torsional load cases' share."""

    maxHeight: float = Field(gt=0, description="Low-rise: mean roof height h up to this [m].")
    rows: list[LowRiseRow] = Field(min_length=2)
    endZoneFactor: float = Field(gt=0, description="E zones extend endZoneFactor·a.")
    zone2Fraction: float = Field(gt=0, description="Negative zone 2: up to this · L ...")
    zone2EaveFactor: float = Field(gt=0, description="... or this · he, the less.")
    torsionalShare: float = Field(gt=0, le=1, description="Zones 1T-4T: this · zones 1-4.")
    exemptHeight: float = Field(gt=0, description="One storey up to this h: no torsional cases.")


class MwfrsTable(_Row):
    """External pressures of the main wind-force resisting system on walls and roofs of
    enclosed and partially enclosed buildings (read by :mod:`saengine.fem.loads` and
    :mod:`saengine.fem.open_wind`)."""

    sideWall: float = Field(description="Side wall Cp.")
    overhang: float = Field(description="Cp on the underside of a windward roof overhang.")
    roof: RoofCpTable
    domes: DomeTable | None = None
    arched: ArchedTable | None = None
    lowRise: LowRiseTable | None = None


class OpenRoofRow(_Row):
    """One roof angle and load case of an open building's free roof, wind normal to the ridge:
    (CNW, CNL) the net pressure coefficients of the windward and leeward halves, by blockage;
    ``...Reverse`` for γ = 180° where the figure gives it (a monoslope roof: γ = 0° the wind
    blows from the high eave down the slope, 180° up it)."""

    angle: float = Field(ge=0, le=90)
    case: str
    clear: tuple[float, float]
    obstructed: tuple[float, float]
    clearReverse: tuple[float, float] | None = None
    obstructedReverse: tuple[float, float] | None = None


class OpenRoofAlongZone(_Row):
    """A zone of a free roof by its horizontal distance from the windward edge (multiples of
    h), wind parallel to the ridge: CN by load case, then by blockage."""

    upTo: float | None = Field(default=None, description="Ends this many h from the edge.")
    cases: dict[str, dict[str, float]]


class OpenRoofAlong(_Row):
    zones: list[OpenRoofAlongZone] = Field(min_length=1)
    flatMonoslopeAngle: float = Field(
        gt=0, description="A monoslope roof below this θ [°] takes these zones ..."
    )
    flatMonoslopeRatio: tuple[float, float] = Field(
        description="... for the wind normal to its slope too, with h/L in this range."
    )


class OpenRoofMwfrs(_Row):
    """Net pressure coefficients CN of the main wind-force resisting system of free roofs."""

    monoslope: list[OpenRoofRow] = Field(min_length=2)
    pitched: list[OpenRoofRow] = Field(min_length=2)
    troughed: list[OpenRoofRow] = Field(min_length=2)
    along: OpenRoofAlong


class OpenRoofCladdingRow(_Row):
    """CN of the components and cladding of a free roof at one angle: per blockage, per zone,
    the (positive, negative) pair of each effective-area band."""

    angle: float = Field(ge=0, le=90)
    clear: dict[str, list[tuple[float, float]]]
    obstructed: dict[str, list[tuple[float, float]]]
    note: str | None = None


class OpenRoofCladding(_Row):
    areaBands: list[float] = Field(
        min_length=1, description="Band upper limits as multiples of a² (the last band: above)."
    )
    ridgeEdgeFrom: float = Field(
        description="θ [°] from which a pitched or troughed roof's ridge (valley) is an edge."
    )
    zoneLabels: dict[str, str] = Field(default_factory=dict)
    monoslope: list[OpenRoofCladdingRow] = Field(min_length=2)
    pitched: list[OpenRoofCladdingRow] = Field(min_length=2)
    troughed: list[OpenRoofCladdingRow] = Field(min_length=2)


class OpenBuildingsTable(_Row):
    """Open buildings with monoslope, pitched or troughed free roofs: p = qh·G·CN for the
    main wind-force resisting system and the components and cladding (read by
    :mod:`saengine.fem.open_wind`)."""

    maxAngle: float = Field(gt=0, description="Roof θ up to this [°].")
    minAngle: float = Field(
        ge=0, description="Below this θ [°], every form takes the monoslope's first row."
    )
    hOverL: tuple[float, float] = Field(description="h/L range of the figures.")
    mwfrs: OpenRoofMwfrs
    cladding: OpenRoofCladding | None = None


class PeakVelocityPressureRule(_Row):
    """C4: the peak velocity pressure of EN 1991-1-4 Sec 4 (``wind.method``
    "peakVelocityPressure", :mod:`saengine.fem.peak_velocity_pressure`): vb = cdir·cseason·vb,0
    (the project's basic wind speed is vb,0); cr(z) = kr·ln(max(z, zmin)/z0) with kr =
    ``krFactor``·(z0/``z0Reference``)^``krExponent``, up to ``zmax``; vm = cr·co·vb; Iv = kI /
    (co·ln(max(z, zmin)/z0)); qp = (1 + ``peakFactor``·Iv)·½·ρ·vm²."""

    season: float = Field(default=1.0, gt=0, description="cseason.")
    airDensity: Positive = Field(description="ρ [kg/m³].")
    krFactor: Positive = Field(description="0.19 of kr.")
    krExponent: Positive = Field(description="0.07 of kr.")
    z0Reference: Positive = Field(description="z0,II [m] of kr.")
    zmax: Positive = Field(description="zmax [m].")
    turbulence: Positive = Field(description="Turbulence factor kI.")
    peakFactor: Positive = Field(description="7 of (1 + 7 Iv).")


class WallPressureRow(_Row):
    """External pressure coefficients of the walls by h/d (EN 1991-1-4 Table 7.1, zones D and
    E): ``ratio`` h/d, ``windward`` cpe,10 of D, ``leeward`` cpe,10 of E; linear between rows."""

    ratio: Positive
    windward: float
    leeward: float


class StructuralFactorRule(_Row):
    """cscd of buildings: ``value`` where ``heightMax`` (h below it) or ``frameHeightMax`` and
    ``depthRatioMax`` (frame buildings with walls, h below it and below that × the depth along
    the wind) hold (EN 1991-1-4 6.2(1) a and c); else the detailed procedure, not covered: the
    value is used with a note."""

    value: Positive = 1.0
    heightMax: Positive | None = None
    frameHeightMax: Positive | None = None
    depthRatioMax: Positive | None = None


class RiskCoefficientRow(_Row):
    """C7: a class of the risk coefficient k1 (design life): the occupancy categories whose
    wind importance is ``importance`` take k1 from the (basic wind speed [m/s], k1) points."""

    id: str
    name: str
    importance: float = Field(gt=0, description="The occupancy categories' windImportance.")
    k1: list[tuple[float, float]] = Field(min_length=1)


class SpeedFactors(_Row):
    """C7, ``method: speedFactors``: the design wind speed Vz = Vb·k1·k2·k3·k4 and the design
    pressure pd = max(Kd·Ka·Kc, minimumShare)·airFactor·Vz² [N/m², V in m/s]; k3 is the table's
    ``topographic``, Kd its ``directionality`` (:mod:`saengine.fem.wind_speed_factors`)."""

    airFactor: float = Field(gt=0, description="pz = airFactor·Vz² [N/m²].")
    heightFactors: dict[str, list[tuple[float, float]]] = Field(
        description="k2: terrain (exposure) -> (height [m], k2) points, constant below the "
        "first and above the last."
    )
    riskCoefficients: list[RiskCoefficientRow] = Field(default_factory=list)
    importance: float = Field(
        default=1.0, gt=0, description="k4 (cyclonic importance); a project overrides it."
    )
    importanceRows: dict[str, float] = Field(
        default_factory=dict, description="The code's k4 values, for the engineer's choice."
    )
    areaAveraging: float = Field(
        default=1.0, gt=0, le=1, description="Ka of the main wind-force resisting system."
    )
    areaAveragingRows: list[tuple[float, float]] = Field(
        default_factory=list, description="The code's (tributary area [m²], Ka) points."
    )
    combination: float = Field(default=1.0, gt=0, le=1, description="Kc.")
    minimumShare: float = Field(default=0.0, ge=0, le=1, description="Least Kd·Ka·Kc.")
    # Alpha 9 C9b: sites in a cyclone-prone region (a project sets ``cyclonic``).
    cyclonic: bool = Field(
        default=False,
        description="The site is in a cyclone-prone region: k4 by the occupancy's risk class "
        "(cyclonicImportance) and Kd = cyclonicDirectionality.",
    )
    cyclonicImportance: dict[str, float] = Field(
        default_factory=dict,
        description="k4 by the id of the occupancy's riskCoefficients row ('other': the rest); "
        "at least ``importance``.",
    )
    cyclonicDirectionality: float | None = Field(
        default=None, gt=0, description="Kd in a cyclone-prone region (None: unchanged)."
    )


class CpHeightRow(_Row):
    """C7: the wall pressure coefficients of a building up to ``heightRatioMax`` = h / w (w the
    lesser plan dimension): windward ``windward``; leeward the first (l/w max, Cp) row with l/w
    (l the greater plan dimension) up to it, else the last."""

    heightRatioMax: float = Field(gt=0)
    windward: float
    leeward: list[tuple[float, float]] = Field(min_length=1)


class WindTable(TableModel):
    method: Literal["powerLaw", "peakVelocityPressure", "speedFactors"] = Field(
        default="powerLaw",
        description="C4: how the storey forces are made: powerLaw (qz = 0.000613·Kz·Kzt·Kd·V²·I "
        "with the exposures' α and zg, G, Cp) or peakVelocityPressure (EN 1991-1-4: qp(ze) from "
        "the terrain categories' z0 and zmin, cpe of walls by h/d, lack of correlation, cscd); "
        "C7: speedFactors (IS 875-3: pd from Vz = Vb·k1·k2·k3·k4, see ``speedFactors``).",
    )
    speedFactors: SpeedFactors | None = None
    cpByHeight: list[CpHeightRow] | None = Field(
        default=None,
        description="C7: wall Cp by h/w and l/w in place of cpWindward and cpLeeward; empty: "
        "those.",
    )
    defaultExposure: str | None = Field(
        default=None, description="C7: the exposure (terrain) of a new project under this pack."
    )
    peakVelocityPressure: PeakVelocityPressureRule | None = None
    wallPressure: list[WallPressureRow] = Field(
        default_factory=list, description="cpe of the walls by h/d (peakVelocityPressure)."
    )
    correlation: list[tuple[float, float]] = Field(
        default_factory=list,
        description="(h/d, factor) on the net wall force for the lack of correlation between "
        "windward and leeward; linear between, the end values outside.",
    )
    structuralFactor: StructuralFactorRule | None = None
    internalPressureRange: tuple[float, float] | None = Field(
        default=None,
        description="(most positive, most negative) cpi where it cannot be worked out; reported.",
    )
    exposures: dict[str, Exposure]
    # C1: the constants of Kz = kzFactor·(max(z, kzMinHeight)/zg)^(2/α); empty: 2.01 and 4.57 m
    # (the default pack's Table 6.2.11).
    kzFactor: float | None = Field(default=None, gt=0, description="Factor of the Kz power law.")
    kzMinHeight: float | None = Field(
        default=None, gt=0, description="Kz below this height [m] is the one at it."
    )
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
    internalPressure: InternalPressureTable | None = Field(
        default=None, description="Internal pressure coefficients and Ri; None: cladding's."
    )
    mwfrs: MwfrsTable | None = Field(
        default=None,
        description="Wall and roof pressures of the main wind-force resisting system; None: "
        "storey forces only and no wind on clad special structures.",
    )
    openBuildings: OpenBuildingsTable | None = Field(
        default=None,
        description="Net pressures on the free roofs of open buildings; None: an open clad "
        "structure takes force coefficients on its members instead.",
    )
    openStructures: OpenStructuresTable | None = Field(
        default=None,
        description="Force coefficients of open structures (lattice frameworks, trussed "
        "towers); None: special structures get no wind.",
    )
    # B22: topography, solid signs and walls, chimneys and tanks, rooftop equipment.
    topography: TopographyTable | None = Field(
        default=None, description="Kzt of hills, ridges and escarpments; None: Kzt = topographic."
    )
    solidSigns: SolidSignsTable | None = Field(
        default=None, description="Cf of solid freestanding walls and signs; None: not covered."
    )
    chimneys: ChimneysTable | None = Field(
        default=None, description="Cf of chimneys, tanks and rooftop equipment; None: not covered."
    )
    rooftop: RooftopTable | None = Field(
        default=None, description="Increase of the force on rooftop equipment; None: none."
    )

    @model_validator(mode="after")
    def _profiles(self) -> WindTable:
        for key, row in self.exposures.items():
            if self.method == "powerLaw" and (row.alpha is None or row.zg is None):
                raise ValueError(f"exposure {key}: alpha and zg are required (powerLaw)")
            if self.method == "peakVelocityPressure" and (row.z0 is None or row.zmin is None):
                raise ValueError(f"exposure {key}: z0 and zmin are required (peakVelocityPressure)")
        if self.method == "peakVelocityPressure" and self.peakVelocityPressure is None:
            raise ValueError("peakVelocityPressure: the method needs its constants")
        if self.method == "speedFactors":
            if self.speedFactors is None:
                raise ValueError("speedFactors: the method needs its factors")
            missing = [k for k in self.exposures if k not in self.speedFactors.heightFactors]
            if missing:
                raise ValueError(f"speedFactors: no height factors of {', '.join(missing)}")
        return self


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
    """Design wind loads on other structures, F = qz·G·Cf·Af (the default pack's Part 6 Sec 2.4, the
    provisions of ASCE 7-05 Sec 6.5.15 and Figures 6-22, 6-23): open signs and lattice
    frameworks, and trussed towers."""

    lattice: list[LatticeCfRow] = Field(min_length=1)
    roundLimit: float = Field(
        gt=0, description="D√qz limit between the rounded-member columns (D in m, qz in N/m²)."
    )
    squareTower: TowerCf
    triangularTower: TowerCf
    diagonalFactor: tuple[float, float] = Field(
        description="Square tower, wind on the diagonal: Cf × (1 + k·ε), at most the cap."
    )
    roundTower: TowerCf = Field(
        description="Factor on Cf of a tower of rounded members (a·ε² + b·ε + c), at most 1."
    )


class TopographyShape(_Row):
    """A topographic feature's speed-up parameters: K1/(H/Lh) by exposure, γ and μ."""

    k1: dict[str, float] = Field(description="K1 / (H/Lh) by exposure.")
    gamma: float = Field(gt=0, description="Height attenuation factor γ.")
    muUpwind: float = Field(gt=0, description="Horizontal attenuation μ upwind of the crest.")
    muDownwind: float = Field(gt=0, description="Horizontal attenuation μ downwind of it.")


class TopographyTable(_Row):
    """Wind speed-up over isolated hills, ridges and escarpments: Kzt = (1 + K1·K2·K3)² with
    K1 = (K1/(H/Lh))·H/Lh, K2 = 1 − |x|/(μ·Lh), K3 = e^(−γ·z/Lh) (read by
    :func:`saengine.fem.loads.topographic_factor`)."""

    shapes: dict[Literal["ridge", "escarpment", "hill"], TopographyShape]
    minSlope: float = Field(gt=0, description="No speed-up below H/Lh of this.")
    maxSlope: float = Field(
        gt=0, description="Above it, H/Lh is taken as this for K1 and Lh as H/this for K2, K3."
    )
    minHeight: dict[str, float] = Field(description="No speed-up below a feature height H [m].")


class SolidSignRegion(_Row):
    """A region of a long sign (case C) up to ``end``·s from the windward edge (None: the rest):
    Cf by the aspect ratios of the table, None where the sign is not that long."""

    end: float | None = Field(default=None, gt=0)
    cf: list[float | None]


class SolidSignsCaseC(_Row):
    """Case C (B/s ≥ ``minAspect``): Cf of each region by B/s, × (``reductionConstant`` − s/h)
    above s/h of ``reductionAbove``."""

    aspect: list[float] = Field(min_length=2)
    regions: list[SolidSignRegion] = Field(min_length=1)
    minAspect: float = Field(gt=0)
    reductionAbove: float = Field(gt=0)
    reductionConstant: float = Field(gt=0)


class ReturnCorner(_Row):
    """The factor on the first region's Cf (B/s ≥ ``fromAspect``) with a return corner, by
    Lr/s."""

    fromAspect: float = Field(gt=0)
    factors: list[tuple[float, float]] = Field(min_length=1)


class SolidSignsTable(_Row):
    """Solid freestanding walls and solid signs, F = qh·G·Cf·As (read by
    :mod:`saengine.fem.other_wind`): Cf of cases A and B by s/h (``clearance``) and B/s
    (``aspect``), case C by region."""

    clearance: list[float] = Field(min_length=2, description="s/h of the rows.")
    aspect: list[float] = Field(min_length=2, description="B/s of the columns.")
    caseAB: list[list[float]] = Field(min_length=2)
    caseC: SolidSignsCaseC
    returnCorner: ReturnCorner | None = None
    solidMin: float = Field(gt=0, le=1, description="A sign is solid from this ε up.")
    openingExponent: float = Field(gt=0, description="Openings: Cf × (1 − (1 − ε)^this).")
    caseBOffset: float = Field(ge=0, description="Case B: F this × B toward the windward edge.")
    fullHeightLift: float = Field(ge=0, description="s/h = 1: F this × s above the centre.")
    note: str | None = None


class ChimneyRow(_Row):
    """Cf of a cross-section and surface by h/D; ``small``: rounded with D√qz up to the
    limit."""

    section: Literal["square", "squareDiagonal", "polygonal", "round"]
    surface: Literal["all", "moderatelySmooth", "rough", "veryRough"] = "all"
    small: bool = False
    cf: list[float] = Field(min_length=1)
    note: str | None = None


class ChimneysTable(_Row):
    """Chimneys, tanks, rooftop equipment and similar structures, F = qz·G·Cf·Af (read by
    :mod:`saengine.fem.other_wind`)."""

    hOverD: list[float] = Field(min_length=1)
    roundLimit: float = Field(gt=0, description="D√qz limit of round sections (D m, qz N/m²).")
    rows: list[ChimneyRow] = Field(min_length=1)


class RooftopTable(_Row):
    """The force on rooftop structures and equipment of a low building × ``factor`` for
    Af ≤ ``fullShare``·B·h, linear down to 1 at Af = ``noneShare``·B·h."""

    maxHeight: float = Field(gt=0, description="Buildings with h up to this [m].")
    factor: float = Field(ge=1)
    fullShare: float = Field(gt=0)
    noneShare: float = Field(gt=0)


# ─────────────────────────────────────── crane loads ───────────────────────────────────────


class CraneCombination(BaseModel):
    """Which crane load cases act together in the load combinations."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    factorOf: str = Field(
        default="L",
        description="Factor kind of a combination row the crane cases take (crane loads are "
        "live loads).",
    )
    gravity: list[list[Literal["V", "T", "B"]]] = Field(
        default_factory=list,
        description="Parts that act together in rows without wind or earthquake: V vertical "
        "with impact, T transverse (lateral, both signs), B longitudinal (both signs).",
    )
    lateral: list[list[Literal["V", "T", "B"]]] = Field(
        default_factory=list,
        description="Parts that act together in rows with wind or earthquake (none: the crane "
        "is left out of those rows).",
    )
    note: str = ""


class CranesTable(TableModel):
    """Crane loads: the vertical impact by kind of crane, the transverse (lateral) force on the
    runway beams, the longitudinal force, the share of these horizontal forces by kind of crane,
    and which crane load cases the combinations take together."""

    impact: dict[str, float] = Field(
        description="Vertical impact: share of the maximum wheel loads added, by crane kind."
    )
    lateral: float = Field(
        gt=0, description="Transverse force: share of the lifted load plus the trolley (and hoist)."
    )
    longitudinal: float = Field(gt=0, description="Longitudinal force: share of the wheel loads.")
    horizontalScale: dict[str, float] = Field(
        default_factory=dict,
        description="Factor on the transverse and longitudinal forces by crane kind (default 1).",
    )
    notes: dict[str, str] = Field(
        default_factory=dict,
        description="Labels of entries that are not the code's own text: {key: note}.",
    )
    combination: CraneCombination | None = Field(
        default=None, description="Crane load cases in the combinations (none: no crane cases)."
    )


# ───────────────────────────────────────── steel fatigue ─────────────────────────────────────────


class FatigueEquation(BaseModel):
    """Design stress range F_SR = (Cf × constant / N) ^ exponent ≥ F_TH [MPa]."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    constant: float = Field(gt=0)
    exponent: float = Field(gt=0)
    source: str | None = None


class FatigueCategory(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    Cf: float = Field(gt=0, description="Constant Cf of the stress category.")
    threshold: float = Field(gt=0, description="Threshold stress range F_TH [MPa].")
    equation: str = Field(default="default", description="Key of ``equations``.")
    source: str | None = None


class FatigueTable(TableModel):
    """Fatigue of steel members and connections under repeated loading: the design stress range
    by stress category, the exemptions and the service stress limit."""

    minCycles: float = Field(
        gt=0, description="No fatigue check below this number of live load cycles."
    )
    maxServiceStress: float = Field(
        gt=0, description="Largest stress under unfactored loads, as a share of Fy."
    )
    equations: dict[str, FatigueEquation]
    categories: dict[str, FatigueCategory]


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
    #: D7; a pack without it reads the generic default (codes/generic).
    plain: Phi | None = Field(
        default=None,
        description="Flexure, compression, shear and bearing of structural plain concrete.",
    )


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
    """Limits and choices of the torsion design of beams (the default pack's Part 6 Sec 6.4.4)."""

    theta: float = Field(ge=30, le=60, description="Angle θ of the compression diagonals [°].")
    aoShare: Share = Field(description="Ao / Aoh.")
    spacingMax: Positive = Field(description="Largest spacing of closed stirrups [mm].")
    perimeterDivisor: Positive = Field(description="s <= ph / this.")
    longitudinalSpacingMax: Positive = Field(description="Longitudinal bars apart at most [mm].")
    longitudinalDiaRatio: Positive = Field(description="Longitudinal bar diameter >= this × s.")
    longitudinalDiaMin: Positive = Field(description="[mm]")
    fyMax: Positive = Field(description="Largest fy, fyt of torsion steel [MPa].")


class PrestressCracking(_Group):
    """Members with bonded tendons: φMn >= factor × Mcr, waived where the strength is at least
    waiver × the required strength."""

    factor: Positive
    waiver: Positive


class PrestressBondedTop(_Group):
    """Bonded top bars over the columns of two-way slabs: at least ``minBars`` bars at most
    ``maxSpacing`` [mm] apart between lines ``beyondFace`` × h outside the column faces; bars
    ``negativeLength`` × ln each side of the support, bottom bars ``positiveLength`` × ln."""

    minBars: int = Field(ge=1)
    maxSpacing: Positive
    beyondFace: Positive
    negativeLength: Share
    positiveLength: Share


class PrestressTransferBonded(_Group):
    """Bonded bars for the tension at transfer above the limits: As = T / (stressShare fy); the
    ends of a simply supported member within endRegion × h of its anchors."""

    stressShare: Share
    endRegion: Positive


class PrestressRelaxation(_Group):
    """Relaxation loss [MPa] by the initial stress / fpu (linear between, zero below the
    first, the last value above)."""

    stressRatios: list[Share] = Field(min_length=2)
    losses: list[float] = Field(min_length=2)


class PrestressIntegrity(_Group):
    """Slabs with unbonded tendons: at least ``strands`` strands of ``strandArea`` [mm²] or more
    each way through the column (its section less ``coreInset`` [mm] each side), else bottom
    bars through it of at least bottomFactor × bottomRoot √f'c bw d / fy and bottomMin bw d /
    fy."""

    strands: int = Field(ge=1)
    strandArea: Positive
    coreInset: float = Field(ge=0)
    bottomFactor: Positive
    bottomRoot: Positive
    bottomMin: Positive


class PrestressBursting(_Group):
    """General zone bursting by simplified equations: T = share Ppu (1 - a/h), d = depthShare
    (h - 2e)."""

    method: Literal["simplified"]
    share: Positive
    depthShare: Positive


class PrestressAnchorage(_Group):
    """Post-tensioned anchorage zones: Ppu = loadFactor × the jacking force, φ; spalling steel
    ``spalling`` × Ppu (not for monostrand slab tendons); f'ci at stressing; the slab edge bars
    and hairpins of monostrand slab anchors; bursting."""

    loadFactor: Positive
    phi: Share
    spalling: Positive
    transferMulti: Positive
    transferSingle: Positive
    monostrandArea: Positive
    edgeBars: int = Field(ge=1)
    edgeBarDia: Positive
    edgeBarAhead: Positive
    edgeBarExtension: Positive
    groupSpacing: Positive
    groupMin: int = Field(ge=1)
    hairpinDia: Positive
    hairpinFrom: Positive
    hairpinTo: Positive
    bursting: PrestressBursting | None = None


class PrestressCompression(_Group):
    """Prestressed compression members: above ``threshold`` [MPa] of effective prestress, ties
    of at least ``tieMinDia`` at most ``tieSpacingDiameters`` tie diameters (and the least
    dimension) apart, or spirals ρs >= spiralCoefficient (Ag/Ach - 1) f'c / fyt, fyt <=
    spiralFytMax."""

    threshold: Positive
    tieMinDia: Positive
    tieSpacingDiameters: Positive
    spiralCoefficient: Positive
    spiralFytMax: Positive


class PrestressLimits(_Group):
    """Prestressed concrete (the pack's prestressed chapter; the default pack's clauses are in
    ``concrete.sources.prestress``): stress limits as
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
    # B30: the rest of the prestressed concrete chapter. Optional: a pack without one of them
    # leaves that check out and says it does not cover it.
    punchingMethod: Literal["precompression", "reinforced"] = Field(
        default="precompression",
        description="Punching at the columns of prestressed slabs: 'precompression' (βp √f'c + "
        "fpc term above) or 'reinforced' (the nonprestressed vc, no prestress term).",
    )
    transferSteelFpy: Positive | None = Field(
        default=None, description="Tendon stress immediately after transfer <= this × fpy."
    )
    transferSteelFpu: Share | None = Field(default=None, description="... and <= this × fpu.")
    transferCompressionEnds: Positive | None = Field(
        default=None,
        description="At transfer, at the ends of simply supported members: compression <= "
        "this f'ci.",
    )
    tensionClassT: Positive | None = Field(
        default=None, description="Class T up to this √f'c; Class C above (one-way members)."
    )
    gammaPByRatio: list[tuple[Positive, Positive]] | None = Field(
        default=None,
        description="(least fpy / fpu, γp) rows of bonded fps; the largest ratio met applies.",
    )
    fpsMinFse: Share | None = Field(
        default=None, description="The approximate fps needs fse >= this × fpu."
    )
    bondedFyMax: Positive | None = Field(
        default=None, description="fy of the bonded bars of Nc / (k fy) at most this [MPa]."
    )
    rupture: Positive | None = Field(default=None, description="fr = this λ √f'c [MPa].")
    cracking: PrestressCracking | None = None
    bondedTop: PrestressBondedTop | None = None
    transferBonded: PrestressTransferBonded | None = None
    relaxation: PrestressRelaxation | None = None
    integrity: PrestressIntegrity | None = None
    anchorage: PrestressAnchorage | None = None
    compression: PrestressCompression | None = None
    note: str = Field(default="", description="Why the values are what they are.")


class DeflectionLimitsGroup(_Group):
    """Span divisors of the computed deflection limits, ξ and the cantilever thickness divisors
    (the default pack's Part 6 Sec 6.2.5)."""

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
    # C2: the effective moment of inertia, a method id the pack picks.
    effectiveInertia: Literal["cubic", "bischoff"] = Field(
        default="cubic",
        description="Ie: 'cubic' (Ie = (Mcr/Ma)³ Ig + (1 - (Mcr/Ma)³) Icr <= Ig, Ig up to Mcr) "
        "or 'bischoff' (Ie = Icr / (1 - ((2/3) Mcr/Ma)² (1 - Icr/Ig)), Ig up to (2/3) Mcr).",
    )


# B21: the concrete's modulus and shrinkage steel by its aggregate (Project Settings >
# Construction > Concrete aggregate).
class AggregateRules(_Group):
    """What an aggregate type (Project Settings > Construction) changes in the concrete."""

    modulus: Literal["normal", "density", "brick"] = Field(
        description="Ec rule: normal weight, the density form (lightweight), brick aggregate."
    )
    lambdaFactor: Share = Field(
        alias="lambda", description="Lightweight modification factor λ on √f'c."
    )
    shrinkageFactor: float = Field(
        default=1.0, ge=1, description="Shrinkage and temperature steel × this."
    )


class ModulusRules(_Group):
    """Modulus of elasticity Ec of concrete [MPa] (f'c in MPa, wc in kg/m³)."""

    normal: Positive = Field(description="Normal weight: Ec = this √f'c.")
    brick: Positive = Field(description="Brick aggregate: Ec = this √f'c.")
    densityCoefficient: Positive = Field(description="Ec = this wc^exponent √f'c.")
    densityExponent: Positive
    densityRange: tuple[Positive, Positive] = Field(
        description="wc [kg/m³] within which the density form applies."
    )


class ShrinkageSteel(_Group):
    """Shrinkage and temperature steel of slabs (ratios of the gross area)."""

    ratioLow: Rho = Field(description="Below referenceFy.")
    referenceFy: Positive = Field(description="[MPa]")
    ratioReference: Rho = Field(description="At referenceFy and above: this × referenceFy / fy.")
    ratioMin: Rho = Field(description="Never less than this.")


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
    #: The same with drop panels (the default pack's Table 6.6.3's right-hand columns).
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
    aggregates: dict[str, AggregateRules] | None = Field(
        default=None,
        description="B21: per aggregate type, its Ec rule, λ and shrinkage steel factor "
        "(saengine.design.rc_detailing); None: normal weight for every type.",
    )
    modulus: ModulusRules | None = Field(
        default=None, description="B21: Ec of concrete (None: the material's E only)."
    )
    shrinkage: ShrinkageSteel | None = Field(
        default=None, description="B21: shrinkage and temperature steel of slabs."
    )
    clauses: dict[str, str] = Field(
        default_factory=dict,
        description="B21: clause references of the results, by key (after the pack's edition).",
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


class WallShearAmplification(_Group):
    """C2: the design shear of special walls, Ve = Ωv ωv Vu <= cap Vu. Ωv = ``omega`` where
    hw/lw exceeds ``aspect`` (else 1.0); ωv = a + ns/b (``dynamicLow``) up to
    ``dynamicStoreys`` storeys, a + ns/b (``dynamicHigh``) at most ``dynamicMax`` above, 1.0
    where hw/lw is below ``dynamicAspect``."""

    aspect: Positive
    omega: float = Field(ge=1)
    dynamicAspect: Positive
    dynamicLow: tuple[Positive, Positive]
    dynamicHigh: tuple[Positive, Positive]
    dynamicStoreys: int = Field(ge=1)
    dynamicMax: float = Field(ge=1)
    cap: float = Field(ge=1)


class SpecialWalls(_Group):
    """Plain numbers of special structural walls."""

    relaxedShare: Share
    twoCurtainShare: Share
    driftMin: Share
    stressRequired: Share = Field(description="Boundary elements required above · f'c.")
    stressStop: Share = Field(description="Boundary elements may stop below · f'c.")
    fytConfinementMax: Positive
    hxMax: Positive
    couplingHoopSpacingMax: Positive = Field(
        description="Largest spacing of the hoops over a diagonally reinforced coupling beam's "
        "whole section [mm]."
    )
    couplingHoopDb: Positive = Field(
        description="... and at most this many diameters of the diagonal bars."
    )
    couplingLegSpacingMax: Positive = Field(
        description="Largest spacing of those hoops' legs and crossties, each way [mm]."
    )
    couplingEmbedment: Positive = Field(
        description="Diagonal bars embedded into the wall piers at least this many tension "
        "development lengths."
    )
    couplingGroupWidthShare: Share = Field(
        description="Hoops around each group of diagonal bars: out-to-out at least · bw parallel "
        "to the web width."
    )
    couplingGroupDepthShare: Share = Field(
        description="... and at least · bw along the other sides."
    )
    couplingGroupLegSpacingMax: Positive = Field(
        description="Largest spacing of the crossties or hoop legs around each group, "
        "perpendicular to the diagonal bars [mm]."
    )
    couplingPerimeterRatio: Share = Field(
        description="Bars around a coupling beam's perimeter with hoops around each group: area "
        "each way at least · bw s."
    )
    couplingPerimeterSpacingMax: Positive = Field(description="... at most this far apart [mm].")
    pierLengthRatioMax: Positive = Field(
        description="A wall pier: a vertical wall segment beside an opening with lw/bw at most "
        "this ..."
    )
    pierHeightRatioMin: Positive = Field(
        description="... and its clear height over lw at least this."
    )
    pierAlternativeRatio: Positive = Field(
        description="Wall piers with lw/bw above this may take the alternative to the column "
        "rules (hoops, capacity-design shear)."
    )
    pierHoopSpacingMax: Positive = Field(
        description="Largest vertical spacing of the wall pier's hoops (the alternative) [mm]."
    )
    pierHoopExtension: Positive = Field(
        description="The wall pier's hoops extend at least this above and below its clear "
        "height [mm]."
    )
    # C2: the values of packs whose special walls differ (defaults: the default pack's rules).
    driftFactor: float = Field(
        default=1.0,
        ge=1,
        description="Displacement-based boundary elements: c >= lw / (600 · this · max(δu/hw, "
        "driftMin)).",
    )
    curtainAspect: Positive | None = Field(
        default=None,
        description="Two curtains also where hw/lw is at least this (None: by the shear only).",
    )
    shearAmplification: WallShearAmplification | None = Field(
        default=None,
        description="Design shear Ve = Ωv ωv Vu of special walls (None: Vu of the analysis).",
    )

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


# B21: crack control, skin and flange steel, structural integrity and shear friction
# (saengine.design.rc_detailing).
class CrackControl(_Group):
    """Spacing of the bars nearest the tension face: s <= coefficient (reference / fs) -
    coverFactor cc, and <= cap (reference / fs) [mm, MPa]."""

    coefficient: Positive
    reference: Positive = Field(description="Reference stress [MPa].")
    coverFactor: float = Field(ge=0)
    cap: Positive
    serviceStressShare: Share = Field(description="fs may be taken as this × fy.")


class SkinSteel(_Group):
    """Longitudinal skin steel on the side faces of deep beams."""

    depthOver: Positive = Field(description="Needed where h exceeds this [mm].")
    extentShare: Share = Field(description="Over this × h from the tension face.")


class FlangeTension(_Group):
    """Tension steel of T-beam flanges and the effective flange width."""

    spanShare: Share = Field(description="Spread over at most this × span.")
    bothSidesSpan: Share = Field(description="Slab both sides: bf <= this × span.")
    bothSidesThickness: Positive = Field(description="... overhang <= this × hf each side.")
    oneSideSpan: Share = Field(description="Slab one side: overhang <= this × span.")
    oneSideThickness: Positive = Field(description="... and <= this × hf.")


class StructuralIntegrity(_Group):
    """Continuous bars of cast-in-place beams."""

    perimeterTopShare: Share = Field(description="Perimeter beams: top >= this × As- at supports.")
    perimeterBottomShare: Share = Field(description="... bottom >= this × As+ at midspan.")
    otherBottomShare: Share = Field(description="Other beams: bottom >= this × As+ at midspan.")
    minBars: int = Field(ge=1, description="... and never fewer bars than this.")


class ShearFriction(_Group):
    """Shear transfer across a plane: Vn = Avf fy μ (+ permanent compression), μ = factor λ."""

    mu: dict[str, Positive] = Field(min_length=1, description="Surface -> μ / λ.")
    roughLimits: tuple[Positive, Positive, Positive, Positive] = Field(
        description="Monolithic or roughened normal weight: Vn <= min(a f'c, b + c f'c, d) Ac."
    )
    otherLimits: tuple[Positive, Positive] = Field(
        description="Other cases: Vn <= min(a f'c, b) Ac."
    )
    roughSurfaces: list[str] = Field(description="The surfaces the rough limits apply to.")
    fyMax: Positive = Field(description="fy of shear-friction steel at most [MPa].")
    roughness: Positive = Field(description="Roughened to a full amplitude of about [mm].")


class TendonSpacing(_Group):
    """Bonded tendons of Class C members: Δfps in place of fs in the crack-control spacing."""

    share: Share = Field(description="Tendons apart at most this × the bar spacing limit.")
    mixedShare: Share = Field(description="A bar and a tendon apart at most this × the limit.")
    deltaMax: Positive = Field(description="Δfps at most [MPa].")
    deltaExempt: Positive = Field(description="Δfps up to this: (a) and (b) do not apply [MPa].")


# D6: the bar detailing rules of the drawings (saengine.drawings.detailing).
class BarHooks(_Group):
    """Standard hooks: the straight tail beyond the bend, in bar diameters (db) and [mm]."""

    main180Db: Positive = Field(description="Main bars, 180° hooks: tail this × db ...")
    main180Min: Positive = Field(description="... and at least this [mm].")
    main90Db: Positive = Field(description="Main bars, 90° hooks: tail this × db.")
    tieSmallMax: Positive = Field(description="Stirrups and ties up to this db are 'small' [mm].")
    tie90SmallDb: Positive = Field(description="Small ties, 90° hooks: tail this × db.")
    tie90LargeDb: Positive = Field(description="Larger ties, 90° hooks: tail this × db.")
    tie135Db: Positive = Field(description="Ties, 135° hooks: tail this × db ...")
    closedMin: Positive = Field(
        description="... closed ties and seismic hooks: and at least this [mm]."
    )


class BarBends(_Group):
    """Least inside bend diameters, as a multiple of db."""

    steps: list[tuple[Positive, Positive]] = Field(
        min_length=1,
        description="(db up to [mm], factor) in ascending db; bars above the last: its factor.",
    )
    transverseMax: Positive = Field(description="Stirrups and ties up to this db [mm] ...")
    transverse: Positive = Field(description="... bend at this × db.")

    @model_validator(mode="after")
    def _check(self) -> BarBends:
        sizes = [s for s, _ in self.steps]
        if sizes != sorted(sizes):
            raise ValueError("steps: db must ascend")
        return self


class HookDevelopment(_Group):
    """C2: ldh = fy ψe ψr ψo ψc db^exponent / (coefficient λ √f'c) >= max(minDb db, min):
    ψr = ``psiR`` without the confining ties (1.0 with them), ψo = ``psiO`` without the side
    cover inside the core (1.0 with it), ψc = f'c / psiCDivisor + psiCBase below psiCFcMax,
    else 1.0."""

    coefficient: Positive
    exponent: Positive
    minDb: Positive
    min: Positive
    psiR: float = Field(ge=1)
    psiO: float = Field(ge=1)
    psiCFcMax: Positive
    psiCDivisor: Positive
    psiCBase: Positive


class HeadedDevelopment(_Group):
    """C2: ldt = fy ψe ψp ψo ψc db^exponent / (coefficient λ √f'c) >= max(minDb db, min), ψc
    as the hooks' (``hook``); ψp = ``psiP`` without the ties (1.0 with them)."""

    coefficient: Positive
    exponent: Positive
    minDb: Positive
    min: Positive
    psiP: float = Field(ge=1)
    psiO: float = Field(ge=1)


class BarDevelopment(_Group):
    """Development lengths of deformed bars (straight in tension and compression, hooked)."""

    sqrtFcMax: Positive = Field(description="√f'c used at most [MPa].")
    ldMin: Positive = Field(description="ld in tension at least [mm].")
    ldcMin: Positive = Field(description="ldc in compression at least [mm].")
    smallBarMax: Positive = Field(description="'Small' bars up to this db [mm] (k, ψs).")
    simplifiedGood: tuple[Positive, Positive] = Field(
        description="Simplified form, spacing and cover met: k of (small, larger) bars."
    )
    simplifiedOther: tuple[Positive, Positive] = Field(
        description="Simplified form, other cases: k of (small, larger) bars."
    )
    general: Positive = Field(description="General form: the k of the denominator.")
    confinementMax: Positive = Field(description="(cb + Ktr)/db at most.")
    ktr: Positive = Field(description="Ktr = this × Atr / (s n).")
    psiTop: float = Field(ge=1, description="ψt of top bars.")
    psiTEMax: Positive = Field(description="ψt ψe at most.")
    psiSSmall: Positive = Field(description="ψs of small bars (1.0 for larger).")
    compression: tuple[Positive, Positive] = Field(
        description="ldc = max(a fy db / (λ √f'c), b fy db)."
    )
    compressionConfined: Share = Field(description="ldc × this inside spirals or close ties.")
    hookCover: Share = Field(description="ldh × this with the side and tail cover.")
    hookConfined: Share = Field(description="ldh × this inside close ties.")
    # C2: methods and values of packs whose development differs (defaults: the default pack's).
    hookMethod: Literal["linear", "powerDiameter"] = Field(
        default="linear",
        description="ldh: 'linear' (0.24 ψe fy db / (λ √f'c) × hookCover, hookConfined) or "
        "'powerDiameter' (fy ψe ψr ψo ψc db^exponent / (coefficient λ √f'c), ``hook``).",
    )
    hook: HookDevelopment | None = Field(
        default=None, description="The values of hookMethod 'powerDiameter'."
    )
    headed: HeadedDevelopment | None = Field(
        default=None, description="ldt of headed bars in tension (None: not covered)."
    )
    psiG: list[tuple[Positive, Positive]] | None = Field(
        default=None,
        description="Grade factor ψg of ld: (fy up to [MPa], ψg) ascending; above the last: its "
        "ψg. None: no grade factor (1.0).",
    )


class BarLaps(_Group):
    """Lap splices of deformed bars."""

    min: Positive = Field(description="Every lap at least [mm].")
    classA: Positive = Field(description="Class A tension lap: this × ld.")
    classB: Positive = Field(description="Class B tension lap: this × ld.")
    classAProvided: Positive = Field(description="Class A only when As,prov/As,req >= this ...")
    classAShare: Share = Field(description="... and at most this share of the bars spliced.")
    noLapDb: Positive = Field(description="Bars of this db and larger are not lapped [mm].")
    compression: Positive = Field(description="Compression lap: this × fy db (fy up to the limit).")
    compressionFyLimit: Positive = Field(description="... fy limit [MPa].")
    compressionHigh: tuple[Positive, Positive] = Field(
        description="Above the limit: (a fy - b) db."
    )
    lowFc: Positive = Field(description="f'c below this [MPa] ...")
    lowFcFactor: float = Field(ge=1, description="... compression laps × this.")
    spiralDeformed: Positive = Field(description="Spiral laps: this × db (deformed uncoated).")
    spiralOther: Positive = Field(description="Spiral laps: this × db (other bars).")
    wallYield: float = Field(ge=1, description="Special walls: laps where bars may yield, × ld.")


class BarSplices(_Group):
    """Where laps may be, and the hoops over them, in members of special moment frames."""

    beamExclusionDepths: Positive = Field(
        description="No laps in beams within the joint or this × h of its faces."
    )
    hoopDepthShare: Share = Field(description="Hoops over laps at most this × d ...")
    hoopMax: Positive = Field(description="... and at most this [mm].")
    columnRegion: tuple[Share, Share] = Field(
        description="Column laps only within (from, to) shares of the clear height."
    )

    @model_validator(mode="after")
    def _check(self) -> BarSplices:
        _ordered_pair(self.columnRegion, "columnRegion")
        return self


class BarExtents(_Group):
    """Bar extents at supports and the first stirrup."""

    intoSupport: Positive = Field(description="Bottom bars into the support at least [mm].")
    slabTopExtent: Share = Field(description="Slab top bars from the support face: this × ln.")
    firstStirrup: Positive = Field(description="First stirrup from the face [mm].")
    cutoffDb: Positive = Field(description="Bars beyond the cut-off point: max(d, this × db).")
    negativeSpan: Positive = Field(description="Negative steel past inflection: ... ln / this.")
    positiveSimple: Positive = Field(
        description="1/this of the positive steel into supports (simple)."
    )
    positiveContinuous: Positive = Field(description="... (continuous members).")


class BarDetailing(_Group):
    """The bar detailing rules of the drawings: hooks, bends, development, laps, splice zones and
    bar extents."""

    hooks: BarHooks
    bends: BarBends
    development: BarDevelopment
    laps: BarLaps
    splices: BarSplices
    extents: BarExtents
    notes: dict[str, str] = Field(
        default_factory=dict,
        description="Short notes the formulas print, by key: 'ldMin', 'excess' (the sub-clause "
        "after the term), 'simplifiedOther' (said of small bars in other cases); none: nothing.",
    )


class DetailingTable(TableModel):
    special: SpecialFrames
    joints: Joints
    walls: SpecialWalls
    lintels: LintelLimits
    #: None in a pack that gives no bar spacing limits: the congestion check is then skipped.
    spacing: BarSpacing | None = None
    #: B21; None in a pack without the rule: the check is shown as not covered.
    crackControl: CrackControl | None = None
    skin: SkinSteel | None = None
    flangeTension: FlangeTension | None = None
    integrity: StructuralIntegrity | None = None
    shearFriction: ShearFriction | None = None
    tendonSpacing: TendonSpacing | None = None
    clauses: dict[str, str] = Field(
        default_factory=dict,
        description="B21: clause references of the results, by key (after the pack's edition).",
    )
    #: D6; a pack without bar detailing rules reads the generic defaults (codes/generic, D7).
    bars: BarDetailing | None = None


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


# ── steel connections, stability bracing and ponding (design/steel_connections.py,
# design/steel/members.py, design/steel/ponding.py) ──


class SteelBoltGrade(_Group):
    """Nominal stresses of a bolt grade or a threaded part [MPa]: fixed values, or shares of the
    part's Fu (threaded parts)."""

    Fnt: Positive | None = Field(default=None, description="Nominal tensile stress [MPa].")
    Fnv: Positive | None = Field(
        default=None, description="Nominal shear stress, bearing-type [MPa]."
    )
    FntOfFu: Share | None = Field(default=None, description="Fnt as a share of Fu.")
    FnvOfFu: Share | None = Field(default=None, description="Fnv as a share of Fu.")
    pretension: str | None = Field(
        default=None, description="Key of ``pretension`` (the bolt family); none: not pretensioned."
    )


class SteelSlip(_Group):
    """Slip-critical connections: Rn = μ Du hsc Tb Ns."""

    phiServiceability: Phi = Field(description="φ, slip prevented as a serviceability limit.")
    phiStrength: Phi = Field(description="φ, slip prevented at the required strength.")
    mu: dict[str, Positive] = Field(description="Mean slip coefficient by surface class.")
    Du: Positive = Field(description="Mean installed / specified minimum pretension.")
    hsc: dict[str, Positive] = Field(description="Hole factor by hole type.")


class SteelConnectionData(_Group):
    """Bolts, holes, edges and fillet welds of steel connections."""

    boltGrades: dict[str, SteelBoltGrade]
    boltAliases: dict[str, str] = Field(
        default_factory=dict,
        description="Other grade names taken as a grade of ``boltGrades`` (labelled in "
        "``sources.boltAliases``).",
    )
    pretension: dict[str, dict[int, Positive]] = Field(
        description="Minimum bolt pretension Tb [kN] by bolt family and diameter [mm]."
    )
    slip: SteelSlip
    holes: dict[int, Positive] = Field(description="Standard hole diameter [mm] by bolt diameter.")
    holeOver: Positive = Field(description="Larger bolts: standard hole d + this [mm].")
    netHoleAllowance: float = Field(ge=0, description="Hole width + this for net areas [mm].")
    edgeRolled: dict[int, Positive] = Field(description="Minimum edge distance, rolled [mm].")
    edgeSheared: dict[int, Positive] = Field(description="Minimum edge distance, sheared [mm].")
    edgeOverRolled: Positive = Field(description="Larger bolts, rolled edges: this × d.")
    edgeOverSheared: Positive = Field(description="Larger bolts, sheared edges: this × d.")
    minSpacing: Positive = Field(description="Least bolt spacing as a multiple of d.")
    maxEdgeThickness: Positive = Field(description="Largest edge distance: this × t ...")
    maxEdge: Positive = Field(description="... and at most this [mm].")
    longJointLength: Positive = Field(
        description="Tension splices: bolt pattern longer than this [mm] ..."
    )
    longJointFactor: Share = Field(description="... has Fnv times this.")
    filletMin: list[tuple[float | None, Positive]] = Field(
        description="Minimum fillet weld leg by the thinner part: [[t up to (null: above), leg "
        "[mm]], ...]."
    )
    filletMaxThin: Positive = Field(
        description="Along edges thinner than this, the leg is at most the thickness [mm] ..."
    )
    filletMaxReduce: float = Field(ge=0, description="... else the thickness less this [mm].")
    concreteBearingFull: Positive = Field(description="Pp / (f'c A1) on the full concrete area.")
    concreteBearingPartial: Positive = Field(
        description="Pp / (f'c A1 √(A2/A1)) on part of the concrete area ..."
    )
    concreteBearingMax: Positive = Field(description="... and Pp / (f'c A1) at most this.")
    methods: dict[str, str] = Field(
        default_factory=dict,
        description="Method ids where the code gives a requirement but no method (e.g. "
        "``prying``: ``tStub``); a missing key: the check is not made.",
    )
    references: dict[str, str] = Field(
        default_factory=dict,
        description="Alpha 9 C3: the clause references the connection notes are written with "
        "(the default pack's) -> this pack's references; empty: the notes as written.",
    )


class SteelBracingRow(_Group):
    """Required brace strength Pbr = strength × Pr (columns) or × Mr Cd / ho (beams), stiffness
    βbr = stiffness × Pr / Lb (or × Mr Cd / (Lb ho)) / φ."""

    strength: Positive
    stiffness: Positive


class SteelBracing(_Group):
    """Stability bracing of columns and beams (K = 1 between the braces)."""

    phi: Phi
    columnRelative: SteelBracingRow
    columnNodal: SteelBracingRow
    beamRelative: SteelBracingRow
    beamNodal: SteelBracingRow
    torsionalMoment: Positive = Field(description="Mbr = this × Mr L / (n Cb Lb).")
    torsionalStiffness: Positive = Field(description="βT = this × L Mr² / (n E Iy Cb²) / φ.")
    # Alpha 9 C3b: the form of the torsional brace moment (AISC 360-16+: Mbr = 0.02 Mr).
    torsionalMomentForm: Literal["spanRatio", "share"] = Field(
        default="spanRatio",
        description="Mbr of a nodal torsional brace: ``spanRatio`` (this × Mr L / (n Cb Lb)) "
        "or ``share`` (torsionalMoment × Mr).",
    )
    distortional: Positive = Field(description="βsec = this × E / ho × (...).")
    slenderness: Positive = Field(description="L/r limit of stability bracing.")


class PondingCurve(_Group):
    param: float = Field(ge=0, description="The curve's flexibility constant (Cs or Cp).")
    points: list[tuple[float, float]] = Field(
        description="[stress index U, upper limit of the other flexibility constant] pairs."
    )


class SteelPonding(_Group):
    """Roof ponding: the simplified stiffness limits and the digitised limit curves."""

    limit: Positive = Field(description="Cp + secondary × Cs at most this.")
    secondary: Positive = Field(description="Factor on Cs.")
    coefficient: Positive = Field(description="C = this × Ls Lp⁴ / Ip (m, mm⁴).")
    deck: Positive = Field(description="Id at least this × S⁴ (mm⁴/m, m).")
    trussFactor: Share = Field(description="Is of trusses and steel joists taken times this.")
    stressLimit: Share = Field(description="U = (this × Fy - fo) / fo.")
    primary: list[PondingCurve] = Field(
        description="Limiting Cp by Up, one curve per Cs (the primary-system figure)."
    )
    secondaryCurves: list[PondingCurve] = Field(
        description="Limiting Cs by Us, one curve per Cp (the secondary-system figure)."
    )
    clauses: dict[str, str] = Field(
        default_factory=dict,
        description="Alpha 9 C3b: the references of the check notes (``simplified``, ``deck``, "
        "``primary``, ``secondary``, ``stress``); a missing key: the default pack's numbers.",
    )


# ── B31: steel member torsion and the remaining member limit states (design/steel/torsion.py,
# design/steel/built_up.py, design/steel/members.py) ──


class SteelTorsion(_Group):
    """Torsion of steel members: HSS torsional strength Tn = Fcr C and the stress limits of
    other members."""

    phi: Phi = Field(description="φT of the torsional strength.")
    neglect: Share = Field(description="Tr at most this × Tc: HSS torsion is neglected.")
    shearYield: Share = Field(description="Shear yield stress as a share of Fy (Fcr cap, Fn).")
    normalYield: Positive = Field(description="Normal-stress Fn as a multiple of Fy.")
    roundLong: Positive = Field(description="Round HSS Fcr = this E / (√(L/D) (D/t)^1.25).")
    roundShort: Positive = Field(description="Round HSS Fcr = this E / (D/t)^1.5.")
    rectYield: Positive = Field(description="Rectangular HSS: h/t <= this √(E/Fy) yields.")
    rectInelastic: Positive = Field(description="... <= this √(E/Fy): inelastic buckling.")
    rectMaxRatio: Positive = Field(description="... h/t at most this.")
    rectElastic: Positive = Field(description="Elastic Fcr = this π² E / (h/t)².")
    methods: dict[str, str] = Field(
        default_factory=dict,
        description="Method ids where the code says 'by analysis': ``openSection`` (the "
        "torsional stresses of open sections: ``warping``), ``buckling`` (Fcr of the buckling "
        "limit state: ``leastCritical``); a missing key: that check is not made.",
    )


class SteelBuiltUp(_Group):
    """Built-up compression members: modified slenderness and dimensional limits."""

    welded: Positive = Field(description="Welded / pretensioned connectors: this α²/(1+α²).")
    componentShare: Share = Field(description="K a / ri at most this × the member's KL/r.")
    componentK: Positive = Field(description="K of a component between connectors.")
    plateSpacing: Positive = Field(description="Outside plate: spacing <= this √(E/Fy) t ...")
    plateSpacingMax: Positive = Field(description="... and at most this [mm].")
    plateStaggered: Positive = Field(description="Staggered fasteners: <= this √(E/Fy) t ...")
    plateStaggeredMax: Positive = Field(description="... and at most this [mm].")
    lacingSingle: Positive = Field(description="L/r of single lacing bars at most this.")
    lacingDouble: Positive = Field(description="L/r of double lacing bars at most this.")
    lacingShear: Share = Field(description="Lacing shear: this × φc Pn of the member.")
    lacingDoubleLength: Share = Field(description="Double lacing: L = this × the bar length.")
    tiePlateEnd: Positive = Field(description="End tie plate length >= this × line distance.")
    tiePlateIntermediate: Positive = Field(description="Intermediate: >= this × the distance.")
    tiePlateThickness: Share = Field(description="Tie plate t >= this × the line distance.")
    # Alpha 9 C3b: AISC 360-16+ Sec E6.1 (b): welded / pretensioned connectors by Ki.
    method: Literal["alpha", "ki"] = Field(
        default="alpha",
        description="Welded or pretensioned connectors: ``alpha`` ((KL/r)m with α = h / 2rib "
        "and ``welded``) or ``ki`` ((KL/r)o up to a/ri = ``kiLimit``, above it √((KL/r)o² + "
        "(Ki a/ri)²) with Ki by the components, ``ki``).",
    )
    kiLimit: Positive | None = Field(
        default=None, description="``ki``: a/ri up to which (KL/r)m = (KL/r)o."
    )
    ki: dict[str, Positive] = Field(
        default_factory=dict,
        description="``ki``: Ki by the components: ``angles`` (back-to-back), ``channels`` "
        "(back-to-back), ``other``.",
    )


class SteelBars(_Group):
    """Rectangular bars and rounds in flexure."""

    plasticCap: Positive = Field(description="Mp at most this × My.")
    yieldLimit: Positive = Field(description="Lb d / t² <= this E / Fy: yielding only.")
    ltbLimit: Positive = Field(description="... <= this E / Fy: inelastic LTB, else elastic.")
    ltbA: Positive = Field(description="Mn = Cb (ltbA - ltbB (Lb d / t²) Fy / E) My.")
    ltbB: Positive = Field(description="See ``ltbA``.")
    elastic: Positive = Field(description="Fcr = this E Cb / (Lb d / t²).")


class SteelTensionField(_Group):
    """Stiffened webs: kv, tension field action and the transverse stiffeners."""

    kv: Positive = Field(description="kv = this + this / (a/h)² of stiffened webs.")
    aspectMax: Positive = Field(description="a/h above this: kv of an unstiffened web, no TFA.")
    webLimit: Positive | None = Field(
        description="a/h above (this / (h/tw))²: likewise (null: no such limit, alpha 9 C3)."
    )
    webFlange: Positive = Field(description="No TFA when 2 Aw / (Afc + Aft) exceeds this.")
    depthFlange: Positive = Field(description="No TFA when h / bf exceeds this.")
    factor: Positive = Field(description="Vn = 0.6 Fy Aw (Cv + (1 - Cv) / (this √(1+(a/h)²))).")
    stiffenerFree: Positive = Field(description="No stiffeners needed: h/tw <= this √(E/Fy).")
    stiffenerJ: tuple[Positive, Positive, Positive] = Field(
        description="j = a / (a/h)² - b >= c of the stiffener inertia a tw³ j: [a, b, c]."
    )
    stiffenerBt: Positive = Field(description="(b/t)st <= this √(E/Fyst).")
    stiffenerArea: Positive = Field(description="Ast >= Fy/Fyst [this Ds h tw (1-Cv) Vr/Vc ...")
    stiffenerWeb: Positive = Field(description="... - this tw²].")
    Ds: dict[str, Positive] = Field(description="Ds by stiffener kind (pair, angle, plate).")
    # Alpha 9 C3b: AISC 360-16+ Sec G2.3: the stiffeners of tension field panels by inertia.
    stiffenerMethod: Literal["area", "inertia"] = Field(
        default="area",
        description="Stiffeners of panels with tension field action: ``area`` (Ast of "
        "``stiffenerArea``, ``stiffenerWeb``, ``Ds``) or ``inertia`` (Ist >= Ist2 + (Ist1 - "
        "Ist2) ρw, Ist2 = b tw³ j, Ist1 = h⁴ ρst^b / a (Fyw/E)^c of ``stiffenerInertia``).",
    )
    stiffenerInertia: tuple[Positive, Positive, Positive] | None = Field(
        default=None, description="``inertia``: Ist1 = h⁴ ρst^b / a (Fyw/E)^c: [a, b, c]."
    )


class SteelMembers(_Group):
    """B31: the member limit states beyond Secs 10.4-10.8.1, with their clause strings."""

    torsion: SteelTorsion
    builtUp: SteelBuiltUp
    bars: SteelBars
    tensionField: SteelTensionField
    clauses: dict[str, str] = Field(
        default_factory=dict, description="Clause references of the results, by key."
    )


class SteelEffectiveWidthFactors(_Group):
    """Alpha 9 C3: the imperfection factors c1, c2 of the effective width of a slender element
    in compression, be = b (1 - c1 √(Fel/Fcr)) √(Fel/Fcr), Fel = (c2 λr/λ)² Fy."""

    c1: Positive
    c2: Positive


class SteelMemberMethods(_Group):
    """Alpha 9 C3: the member strength methods a pack chooses where its steel code differs from
    the default pack's (each a method id of :mod:`saengine.design.steel.members`; a missing
    group: the default pack's methods)."""

    compressionSlender: Literal["formFactor", "effectiveWidth"] = Field(
        default="formFactor",
        description="Slender elements in compression: ``formFactor`` (Q = Qs Qa, Fcr of Q Fy) "
        "or ``effectiveWidth`` (Pn = Fcr Ae with the effective widths of every slender element).",
    )
    effectiveWidth: dict[str, SteelEffectiveWidthFactors] = Field(
        default_factory=dict,
        description="c1, c2 of ``effectiveWidth`` by element kind: ``stiffened`` (webs and "
        "other stiffened elements), ``hssWalls`` (walls of rectangular HSS), ``other`` "
        "(unstiffened elements: flanges, legs, stems).",
    )
    roundEffectiveArea: tuple[Positive, Positive] = Field(
        default=(0.038, 0.6667),
        description="Round HSS with a slender wall: Ae / Ag (or Q) = a E / (Fy D/t) + b: [a, b].",
    )
    webShear: Literal["cv", "cv1"] = Field(
        default="cv",
        description="Webs of I-shapes and channels without tension field action: ``cv`` (Cv "
        "with the elastic branch) or ``cv1`` (Cv1 = 1.10 √(kv E/Fy) / (h/tw) at most 1).",
    )
    kvUnstiffened: Positive = Field(
        default=5.0, description="kv of an unstiffened web (and of a/h beyond the limits)."
    )
    tensionField: Literal["limited", "reduced"] = Field(
        default="limited",
        description="Panels outside the proportion limits of tension field action: "
        "``limited`` (none counted) or ``reduced`` (the denominator 1.15 (a/h + √(1+(a/h)²))).",
    )
    teeFlexure: Literal["criticalMoment", "lengthLimits"] = Field(
        default="criticalMoment",
        description="Tees about the major axis: ``criticalMoment`` (Mn the least of Mp and Mcr) "
        "or ``lengthLimits`` (Lp, Lr of the stem in tension, stem local buckling, flange local "
        "buckling by λp, λr).",
    )
    teeCompression: Literal["twoStress", "general"] = Field(
        default="twoStress",
        description="Flexural-torsional buckling of tees: ``twoStress`` (Fcry, Fcrz, H) or "
        "``general`` (Fe of singly symmetric members, then the flexural buckling curve).",
    )
    hssLateralTorsional: bool = Field(
        default=False,
        description="Rectangular HSS about the major axis also checked for lateral-torsional "
        "buckling with Lp = a E ry √(J A) / Mp and Lr = b E ry √(J A) / (0.7 Fy Sx).",
    )
    hssLtb: tuple[Positive, Positive] = Field(
        default=(0.13, 2.0), description="[a, b] of ``hssLateralTorsional``."
    )
    teeStem: tuple[Positive, Positive, Positive, Positive, Positive] = Field(
        default=(0.84, 1.52, 1.43, 0.515, 1.52),
        description="Tee stems in flexural compression: d/tw <= a √(E/Fy) Fcr = Fy; <= b √(E/Fy) "
        "Fcr = (c - d (d/tw) √(Fy/E)) Fy; above Fcr = e E / (d/tw)².",
    )
    teeFlangeSlender: Positive = Field(
        default=0.7, description="Slender tee flange: Mn = this E Sxc / (bf/2tf)²."
    )


class SteelTable(TableModel):
    phi: SteelPhi
    slenderness: SteelSlenderness
    netAreaMax: Share
    #: Alpha 9 C3: the design basis of the steel checks. LRFD: Rn times φ (``phi``); ASD: Rn
    #: divided by Ω (``omega``, else ``omegaFromPhi`` / φ), under the allowable stress
    #: combinations. The project may override it.
    designMethod: Literal["LRFD", "ASD"] = Field(
        default="LRFD", description="LRFD (φ, strength combinations) or ASD (Ω, ASD combinations)."
    )
    omega: dict[str, Positive] = Field(
        default_factory=dict, description="Ω by the limit state keys of ``phi`` (ASD)."
    )
    omegaFromPhi: Positive | None = Field(
        default=None,
        description="ASD: Ω = this / φ for a limit state ``omega`` does not list (None: the pack "
        "does not cover ASD and the steel checks stay LRFD, with a note).",
    )
    memberMethods: SteelMemberMethods | None = None
    #: None in a pack without the data: the connection, bracing or ponding checks are then
    #: those of the default pack (connections) or not made (bracing, ponding).
    connections: SteelConnectionData | None = None
    bracing: SteelBracing | None = None
    ponding: SteelPonding | None = None
    #: B31: None in a pack without the data: torsion, built-up, bar and tension field checks
    #: are not made (the member reports them as not covered by the pack).
    members: SteelMembers | None = None


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
    # B28: the general strut-and-tie model of any D-region.
    general: bool = Field(
        default=False,
        description="The pack covers strut-and-tie models of any D-region (the general model "
        "editor); false: only the deep members' own models.",
    )
    effective: Share = Field(
        default=0.85,
        description="fce = effective × β × f'c of a strut and of a nodal zone.",
    )
    betaTension: Share = Field(
        default=0.4, description="βs of a strut in a tension member or a tension flange."
    )
    betaOther: Share = Field(default=0.6, description="βs of every other strut (times λ).")
    lightweightBottle: bool = Field(
        default=True,
        description="βs of a bottle-shaped strut without its web steel is times λ.",
    )
    webRatioFcMax: Positive = Field(
        default=40.0,
        description="f'c [MPa] up to which the web ratio satisfies the strut's crack control; "
        "above it the transverse tension of the 2:1 spread is checked.",
    )
    webAngleMin: Positive = Field(
        default=40.0,
        lt=90,
        description="Least angle [degrees] of web steel in one direction only to the strut.",
    )
    spreadSlope: Positive = Field(
        default=2.0,
        description="The strut's compression spreads at this longitudinal to 1 transverse.",
    )
    deltaFpBonded: float = Field(
        default=420.0, ge=0, description="Δfp [MPa] of bonded prestressed steel in a tie."
    )
    deltaFpUnbonded: float = Field(
        default=70.0, ge=0, description="Δfp [MPa] of unbonded prestressed steel in a tie."
    )
    dRegionDepth: Positive = Field(
        default=1.0,
        description="A D-region extends this × h from a force or geometric discontinuity.",
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
        default=2.0,
        ge=1,
        description="Factor of safety on the passive resistance in front (counted only where "
        "the soil in front cannot be removed).",
    )
    flotation: float = Field(
        default=1.1,
        ge=1,
        description="Least factor of safety against flotation: (flotationDead × W) / U.",
    )
    flotationDead: Share = Field(
        default=1.0, description="Factor on the dead load holding the structure down (0.9D)."
    )
    baseFriction: Share = Field(
        default=2 / 3, description="Base friction angle as a share of φ' (tan δb, δb = r φ')."
    )
    frictionCoefficient: Positive | None = Field(
        default=None,
        description="A fixed friction factor μ between the base and the soil for every soil "
        "(no adhesion); empty: tan(baseFriction φ') and the adhesion on clay.",
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
    baseCover: Positive | None = Field(
        default=None,
        description="Clear cover [mm] of the base's bars cast against the earth; empty: the "
        "wall's own cover.",
    )


class FootingCombination(_Row):
    """A load combination of the geotechnical design of shallow foundations: ``{case: factor}``
    with D the dead load (D and SD), L the normal live load (L and Lr), W and E the wind and
    earthquake (each direction, each sign), B the buoyancy (uplift) of the water at the base."""

    id: str
    name: str
    factors: dict[str, float]
    note: str | None = None


class SettlementLimit(BaseModel):
    """Permissible settlement of one column of the table: the maximum [mm], the differential
    settlement as a share of L (the column spacing) and the angular distortion δ / L."""

    model_config = ConfigDict(extra="forbid")

    total: Positive
    differential: Positive
    angular: Positive


class SettlementLimitRow(_Row):
    """A type of structure: its limits by foundation (``isolated``, ``raft``) and soil column
    (``sand`` = sand and hard clay, ``plasticClay``); a missing raft entry: not given."""

    id: str
    name: str
    isolated: dict[Literal["sand", "plasticClay"], SettlementLimit]
    raft: dict[Literal["sand", "plasticClay"], SettlementLimit] = Field(default_factory=dict)
    lengthHeight: float | None = Field(
        default=None, gt=0, description="L/H of a load-bearing wall row (interpolated between)."
    )


class PresumptiveBearing(_Row):
    """A row of the presumptive (allowable) bearing values for lightly loaded structures."""

    id: str
    name: str
    groups: list[str] = Field(default_factory=list, description="USCS groups of the row.")
    qa: float | None = Field(default=None, gt=0, description="[kPa]; empty: by investigation.")
    waterReduction: bool = Field(
        default=False, description="Reduced by ``presumptiveWaterReduction`` near water."
    )


class SubgradeRow(_Row):
    """A band of the indicative modulus of subgrade reaction (300 mm plate): granular soil by
    SPT N, cohesive soil by the unconfined compressive strength qu [kPa]; ``k`` the range
    [kN/m³] over the band (dry or moist), ``submerged`` below the water table."""

    id: str
    name: str
    low: float = Field(ge=0)
    high: float | None = Field(default=None, gt=0, description="Empty: open-ended.")
    k: tuple[float, float]
    submerged: tuple[float, float] | None = None


class ColumnBaseTransfer(_Group):
    phi: Phi = Field(description="φ of bearing on concrete.")
    bearing: Share = Field(description="Bearing strength φ (this × f'c) A1.")
    areaRatioMax: Positive = Field(description="√(A2/A1) at most this.")
    dowelRatio: Rho = Field(description="Least area across the interface / Ag of the column.")
    minBars: int = Field(ge=1, description="Least number of bars across the interface.")


class TieBeamRules(_Group):
    """Tie beams between foundations: the strut-tie force and the least size."""

    forceShare: Share = Field(description="Force: this × the larger footing or column load.")
    zones: list[int] = Field(description="Seismic zones that require them (else reported only).")
    spanDivisor: Positive = Field(description="Least dimension: the clear span / this ...")
    sizeMax: Positive = Field(description="... need not exceed this [mm].")


class PileCapRules(_Group):
    """Pile spacing and the cap's edges and pile embedment."""

    spacing: Positive = Field(description="Least c/c spacing × D.")
    spacingMin: Positive = Field(description="Least c/c spacing [mm].")
    frictionSpacing: Positive = Field(description="Least c/c spacing × D of friction piles.")
    edgeDistance: Positive = Field(description="Least clear distance pile face to cap edge [mm].")
    embedment: Positive = Field(description="Least embedment of the piles in the cap [mm].")
    singlePileDiameter: Positive | None = Field(
        default=None, description="A single pile under a column at least this diameter [mm]."
    )


class BearingFactorRules(_Group):
    """Alpha 9 C8: the factors of qnu = c Nc sc dc ic + q (Nq - 1) sq dq iq + ½ γ B Nγ sγ dγ iγ
    by the flow value Nφ = tan²(45° + φ/2) (method ``flowValue``, IS 6403): Nc, Nq of
    Prandtl-Reissner, Nγ = gammaFactor (Nq + 1) tan φ; shape 1 + a B/L (c, q), 1 - b B/L (γ),
    square and circle rows; depth dc = 1 + c Df/B √Nφ, dq = dγ = 1 + d Df/B √Nφ from φ at
    least depthPhiMin (else 1); inclination (1 - α/90)² (c, q), (1 - α/φ)² (γ)."""

    method: Literal["flowValue"] = "flowValue"
    gammaFactor: Positive
    shape: tuple[Positive, Positive, Positive] = Field(description="(sc, sq slope, sγ slope).")
    square: tuple[Positive, Positive, Positive] = Field(description="(sc, sq, sγ) of squares.")
    circle: tuple[Positive, Positive, Positive] = Field(description="(sc, sq, sγ) of circles.")
    depth: tuple[Positive, Positive] = Field(description="(dc coefficient, dq = dγ coefficient).")
    depthPhiMin: float = Field(ge=0, description="dq = dγ = 1 below this φ [°].")
    undrainedNc: Positive = Field(description="Nc at φ = 0.")


class ShallowFoundations(_Group):
    """The geotechnical rules of shallow foundations (footings and rafts): load combinations,
    allowable increase, factors of safety, depths, thicknesses, presumptive values, subgrade
    moduli, permissible settlements and the force transfer at the column base."""

    bearingCombinations: list[FootingCombination] = Field(
        description="For the bearing pressure (shear strength) of footings and rafts."
    )
    stabilityCombinations: list[FootingCombination] = Field(
        description="For overturning and sliding (the dead load resisting)."
    )
    settlementCombinations: dict[Literal["granular", "cohesive"], FootingCombination]
    lateralIncrease: float = Field(
        ge=1, description="qa × this with wind or earthquake (none for gravity alone)."
    )
    factorOfSafety: tuple[float, float] = Field(
        description="Range of the factor of safety on the bearing capacity (warned outside)."
    )
    kern: Share = Field(description="Resultant preferably within this × B of the centre.")
    overturning: float = Field(ge=1, description="Least FS against overturning.")
    sliding: float = Field(ge=1, description="Least FS against sliding.")
    friction: Positive = Field(description="Friction factor between foundation and soil.")
    minDepth: Positive = Field(description="Least depth below the natural ground [mm].")
    exteriorDepth: dict[Literal["cohesive", "granular", "temporary"], Positive] = Field(
        description="Least depth of exterior footings [mm]."
    )
    raftDepth: dict[Literal["cohesive", "granular"], Positive] = Field(
        description="Least depth of rafts [mm]."
    )
    slopeDistance: Positive = Field(
        description="Distance from a footing's centre to the slope face at its base level, at "
        "least this × B."
    )
    spreadAngle: dict[str, Positive] = Field(
        description="Largest load spread (horizontal per vertical) by footing material."
    )
    stepLap: dict[Literal["thickness", "stepHeight"], Positive] = Field(
        description="Lap at a change of level: at least this × the thickness or × the step."
    )
    minThickness: dict[Literal["soil", "piles", "plainConcrete", "masonry"], Positive] = Field(
        description="Least depth above the bottom bars (RC on soil, on piles) or thickness [mm]."
    )
    presumptive: list[PresumptiveBearing]
    presumptiveWaterReduction: Share = Field(
        description="Share of the presumptive value with the water table within B of the base."
    )
    subgrade: dict[Literal["granular", "cohesive"], list[SubgradeRow]]
    settlementLimits: list[SettlementLimitRow]
    settlementGuide: dict[Literal["sand", "clay", "differential"], Positive] = Field(
        description="The general rule for pad footings: total on sand, on clay, differential [mm]."
    )
    columnBase: ColumnBaseTransfer
    tieBeams: TieBeamRules | None = Field(
        default=None, description="Tie beams between foundations; empty: not covered."
    )
    # Alpha 9 C8: the bearing capacity factors by method id (none: Vesic, De Beer, Hansen).
    bearingFactors: BearingFactorRules | None = Field(
        default=None,
        description="The shape, depth and inclination factors of the bearing capacity "
        "equation by method (``flowValue``); empty: SAEngine's Vesic / De Beer / Hansen set.",
    )


#: Soil classes of the pile rules: sand by density, clay by consistency, silt by density.
PileDensity = Literal["loose", "medium", "dense"]
PileSoil = Literal["denseSand", "looseSand", "stiffClay", "softClay", "denseSilt", "looseSilt"]


class PileSoilClasses(_Group):
    """Where a layer's density or consistency class starts: granular soil by its mean N60,
    cohesive soil by its undrained shear strength cu."""

    mediumN: Positive = Field(description="N60 at and above which sand is medium dense.")
    denseN: Positive = Field(description="N60 at and above which sand is dense.")
    mediumCu: Positive = Field(description="cu [kPa] at and above which clay is medium stiff.")
    stiffCu: Positive = Field(description="cu [kPa] at and above which clay is stiff.")


class PileStatic(_Group):
    """The static (α / β) method of driven piles, and bored piles by its shares
    (``staticMethod`` "alphaBeta"): α by cu, Nc = base (1 + slope L/Db) ≤ max, β of sand by φ,
    Nq by density (and by φ from the figure), the critical depth by density."""

    alphaFull: tuple[float, float] = Field(description="[cu, α]: α at and below this cu [kPa].")
    alphaLow: tuple[float, float] = Field(description="[cu, α]: α at and above this cu [kPa].")
    alphaDivisor: Positive = Field(
        description="Between them α = 1 - (cu - alphaFull cu) / this [kPa]."
    )
    ncBase: Positive
    ncSlope: Positive
    ncMax: Positive
    clayBaseMax: Positive = Field(description="fb = cu Nc at most this [kPa].")
    sandBeta: list[tuple[float, float]] = Field(
        description="[φ°, β] of sand (interpolated; the end values outside)."
    )
    nq: list[tuple[float, float]] = Field(description="[φ°, Nq], the bearing capacity figure.")
    nqDensity: dict[PileDensity, tuple[float, float]] = Field(
        description="Nq range by density, interpolated in N60 over the class's range."
    )
    baseStressMax: Positive = Field(description="σ'v at the base at most this [kPa].")
    criticalDepth: dict[PileDensity, Positive] = Field(
        description="Depth (× D) below which σ'v of sand stays constant."
    )
    boredSkin: Share = Field(description="Bored piles: this × the driven pile's fs.")
    boredBase: Share = Field(description="Bored piles: this × the driven pile's fb.")


class ShaftConstruction(_Row):
    """A row of the drilled shafts' K/K0 or δ/φ table by construction method."""

    id: str
    name: str
    value: Positive


class DrilledShaft(_Group):
    """Unit values of drilled shafts (bored piles of more than ``minDiameter``)."""

    minDiameter: Positive = Field(description="A bored pile above this [mm] is a drilled shaft.")
    alpha: Share = Field(description="α up to ``alphaLimit``.")
    alphaLimit: Positive = Field(description="cu [kPa] up to which α = ``alpha``.")
    alphaHigh: list[tuple[float, float]] = Field(
        description="[cu kPa, α] above ``alphaLimit`` (the adhesion factor figure)."
    )
    sideTop: float = Field(ge=0, description="No skin friction over this top length [mm].")
    sideBottom: float = Field(ge=0, description="Nor over this many diameters at the bottom.")
    baseMax: Positive = Field(description="fb in clay at most this [kPa].")
    clayReduceAbove: Positive = Field(description="Base diameter [mm] above which Fr applies.")
    frNumerator: Positive
    frWidthFactor: Positive
    omega1: tuple[float, float, float] = Field(description="[a, b, max]: ω1 = a + b L/Db ≤ max.")
    omega2: tuple[float, float, float] = Field(description="[c, min, max]: ω2 = c √(cu/σr).")
    referenceWidth: Positive = Field(description="Br [mm].")
    referenceStress: Positive = Field(description="σr [kPa].")
    betaIntercept: Positive
    betaSlope: Positive = Field(description="β = intercept - slope √(z/Br).")
    betaMax: Positive | None = Field(default=None, description="β at most this; empty: none.")
    lowN: Positive | None = Field(
        default=None, description="β × N60/this below this N60; empty: none."
    )
    skinMax: Positive | None = Field(default=None, description="fs at most this [kPa].")
    sandBase: Positive = Field(description="fb = this × σr × N60 [kPa].")
    sandBaseMax: Positive
    sandBaseDepth: Positive = Field(description="N60 the mean over this × Db below the base.")
    sandReduceAbove: Positive = Field(description="Base diameter [mm] above which Fr applies.")
    sandFr: Positive = Field(description="Fr = this × Br / Db ≤ 1.")
    lateralRatio: list[ShaftConstruction] = Field(description="K/K0 by construction method.")
    frictionRatio: list[ShaftConstruction] = Field(description="δ/φ by construction method.")
    zetaLow: Share = Field(description="ζ of a shaft at ``spacingLow`` diameters in a group.")
    spacingLow: Positive
    clayFullSpacing: Positive = Field(description="ζ = 1 from this spacing (× B) in clay.")
    sandFullSpacing: Positive = Field(description="ζ = 1 from this spacing (× B) in sand.")
    punchingSpan: Positive = Field(description="qE = qLo + H / (this × B) (qUP - qLo) ≤ qUP.")


class SptRelation(_Group):
    """SPT relations of one pile kind and soil: fs = skin N̄60 ≤ skinMax, fb = base N60
    (× L/D when ``baseCapN`` is given, then also ≤ baseCapN N60) ≤ baseMax [kPa]."""

    skin: Positive
    skinMax: Positive
    base: Positive
    baseMax: Positive
    baseCapN: Positive | None = None


class JanbuRow(_Row):
    """A soil of the modulus number table: the range of M and the stress exponent j, matched
    to a layer by its soil type and class (sand and silt by density; clay by consistency,
    loose / medium / dense standing for soft / medium stiff / stiff); a row with no soil types
    is listed for reference only."""

    id: str
    name: str
    soilTypes: list[str] = Field(default_factory=list)
    density: list[PileDensity] = Field(default_factory=list)
    M: tuple[float, float] = Field(description="Range of the modulus number (high, low).")
    j: float = Field(ge=0, le=1)


class PileSettlement(_Group):
    """Settlement of single piles and pile groups."""

    axialShare: dict[Literal["cohesive", "granular"], Share] = Field(
        description="a in Sax = (Qp + a Qs) L / (A Ep): clay and silt, sand."
    )
    cp: dict[Literal["driven", "bored"], dict[PileSoil, Positive]]
    csIntercept: Positive
    csSlope: Positive = Field(description="Cs = (intercept + slope L/D) Cp.")
    skinDenominator: Literal["length", "diameter"] = Field(
        description="Ssf = Cs Qs / (X qo) with X the embedded length or the diameter."
    )
    groupWidthExponent: Positive = Field(description="Sg = St (B/D)^this.")
    groupCountExponent: Positive = Field(description="Rs = n^this.")
    blockDepth: Share = Field(description="The group as a block at this × L below its head.")
    referenceStress: Positive = Field(description="σr [kPa] of the modulus number method.")
    modulus: list[JanbuRow]


#: ``[from, ratio, inclusive]``: the ratio of the last row whose bound the value reaches (at or
#: above it when ``inclusive``, above it otherwise).
RatioBand = tuple[float, float, bool]


class BoredGuidanceRow(_Row):
    """A row of the bored piles' build-ability guidance: bars and hoops by diameter [mm]."""

    diameter: Positive
    bar: Positive
    count: int = Field(ge=1)
    hoop: Positive
    pitch: Positive


class BoredMix(_Row):
    """A recommended concrete mix of bored piles: its slump [mm] and conditions of use."""

    id: str
    slump: Positive
    use: str


class BoredDetailing(_Group):
    """Structural detailing of bored cast-in-situ piles and drilled shafts."""

    minFc: Positive = Field(description="Least f'c [MPa].")
    minDiameter: Positive = Field(description="Least shaft diameter [mm].")
    diameterStep: Positive = Field(description="Shafts sized in steps of this [mm].")
    minFy: Positive = Field(description="Least fy of the longitudinal bars [MPa].")
    minSteel: list[RatioBand] = Field(description="Least As/Ac by the gross area Ac [m²].")
    minBars: int = Field(ge=1, description="Least number of longitudinal bars.")
    largeDiameter: Positive = Field(description="From this diameter [mm] the bars are large.")
    largeMinBar: Positive = Field(description="Least bar diameter of large piles [mm].")
    cover: Positive = Field(description="Least cover to the cage [mm].")
    minHoopPitch: Positive = Field(description="Hoops not closer than this [mm].")
    reinforcedDepth: Positive = Field(description="Bars at least this below the cut-off [mm].")
    casingExtra: Positive = Field(description="And this below a temporary casing [mm].")
    guidance: list[BoredGuidanceRow]
    guidanceFy: Positive = Field(description="fy the guidance assumes [MPa].")
    cement: dict[Literal["dry", "submerged"], Positive] = Field(
        description="Least cement content by placement [kg/m³]."
    )
    waterCement: Positive = Field(description="Recommended water/cement ratio.")
    mixes: list[BoredMix]


class DrivenDetailing(_Group):
    """Structural detailing of driven precast concrete piles."""

    minFc: Positive = Field(description="Least f'c [MPa].")
    hardFc: Positive = Field(description="Least f'c for hard driving [MPa].")
    hardDrivingStress: Positive = Field(description="Driving stress above which it is hard [kPa].")
    maxSlenderness: Positive = Field(description="L/B at most this (else a segmental pile).")
    steelByLength: list[RatioBand] = Field(description="Least As/Ag by L/B.")
    minTie: Positive = Field(description="Least tie diameter [mm].")
    tieEnd: Share = Field(description="Least tie volume over the gross volume at the ends.")
    tieBody: Share = Field(description="Least tie volume over the gross volume in the body.")
    tieEndLength: Positive = Field(description="The ends: this × B from each end.")
    serviceStress: Share = Field(description="Service stress at most this × f'c on Ag.")
    bucklingCu: Positive = Field(description="Below this cu [kPa] the pile may buckle.")
    impact: float = Field(ge=0, description="Handling: the weight × (1 + this) for impact.")


class CastInPlaceDetailing(_Group):
    """Driven cast-in-place concrete piles."""

    minButtArea: Positive = Field(description="Least area at the butt [mm²].")
    minTip: Positive = Field(description="Least diameter at the tip [mm].")
    cover: Positive = Field(description="Least clear cover [mm].")
    corrosiveCover: Positive = Field(
        description="Least clear cover in corrosive ground or under water or slurry [mm]."
    )
    unsupportedBarsBelow: Positive = Field(
        description="Bars this far below the plane of lateral restraint [mm]."
    )


class FoundationConcrete(_Row):
    """A row of the foundation concrete table."""

    id: Literal["footing", "bored", "driven"]
    name: str
    cement: Positive = Field(description="Least cement content [kg/m³].")
    fc: Positive = Field(description="Least f'c [MPa].")
    slump: tuple[float, float] = Field(description="Slump range [mm].")


class PileDetailing(_Group):
    """Structural detailing of piles by kind, and the foundation concrete."""

    bored: BoredDetailing
    driven: DrivenDetailing
    castInPlace: CastInPlaceDetailing
    drilledShaftBarsBelow: Positive = Field(
        description="Drilled shafts: bars this far below the plane of lateral restraint [mm]."
    )
    corrosiveCover: Positive = Field(description="Least cover of piles on a corrosive site [mm].")
    concrete: list[FoundationConcrete]


class PileLateral(_Group):
    """Lateral load on piles: the head deflection, the group ratios, unbraced piles."""

    allowableDeflection: Positive = Field(description="Allowable head deflection [mm].")
    individualNormal: Positive = Field(description="Individual beyond this × B normal to H.")
    individualParallel: Positive = Field(description="And beyond this × B parallel to it.")
    groupRatio: list[tuple[float, float]] = Field(
        description="[in-line c/c × B, ratio of the lateral resistance in the group]."
    )
    unbracedCu: Positive = Field(description="Soil below this cu [kPa] gives no lateral support.")


class TestLoadFactors(_Group):
    initial: Positive = Field(description="A test pile to this × the design load.")
    routine: Positive = Field(description="A working pile to this × the design load.")


class CompressionTestRules(_Group):
    """Interpretation of axial compression load tests."""

    testLoad: TestLoadFactors
    movement: Positive = Field(description="Single pile: the load at this settlement [mm] ...")
    movementShare: Share = Field(description="... times this.")
    diameterShare: Share = Field(description="Single pile: the load at this × D ...")
    underReamedShare: Share = Field(description="(this × the bulb of an under-reamed pile) ...")
    diameterLoadShare: Share = Field(description="... times this.")
    groupMovement: Positive = Field(description="Group: the load at this settlement [mm] ...")
    groupMovementShare: Share
    groupSecondMovement: Positive = Field(description="Group: the load at this settlement ...")
    groupSecondShare: Share
    davissonOffset: Positive = Field(description="Davisson's offset [mm] ...")
    davissonDiameter: Positive = Field(description="... + D / this.")
    bsShare: Share = Field(description="Ultimate at a settlement of this × D.")
    bsAllowableShare: Share = Field(description="Allowable this × that load.")
    isMovement: Positive = Field(description="IS: also the load at this settlement [mm].")
    butlerHoySlope: Positive = Field(description="Tangent at this settlement per ton [mm].")
    butlerHoyTon: Positive = Field(description="The ton [kN].")
    brinchHansenShare: Share = Field(description="Settlement twice that under this × the load.")
    failureSafety: Positive = Field(description="Ultimate from a test over this.")
    minShare: Share = Field(description="At least this share of the piles tested.")
    minBored: int = Field(ge=0, description="At least this many bored piles tested.")
    integrityShare: Share = Field(description="Integrity tests on this share of the piles.")


class UpliftTestRules(_Group):
    testLoad: TestLoadFactors
    movement: Positive = Field(description="The load at this uplift [mm] ...")
    movementShare: Share
    breakShare: Share = Field(description="This × the load at the clear break.")
    failureSafety: Positive
    transientTestSafety: Positive = Field(description="FS on a tested uplift due to W or E.")
    transientAnalysisSafety: Positive = Field(description="FS on an analysed uplift by W or E.")


class LateralTestRules(_Group):
    testLoad: Positive = Field(description="Tests to at least this × the design load.")
    headMovement: Positive = Field(description="The load at this head movement [mm] ...")
    headShare: Share
    totalMovement: Positive = Field(description="The load at this total displacement [mm] ...")
    totalShare: Share


class PileLoadTestRules(_Group):
    compression: CompressionTestRules
    uplift: UpliftTestRules
    lateral: LateralTestRules


class PileDowndrag(_Group):
    """Negative skin friction (downdrag) and swelling uplift on piles."""

    method: Literal["neutralPoint"] = Field(
        description="Engine method (``neutralPoint``: load transfer to the neutral point)."
    )
    settlingSoils: list[str] = Field(description="Soil types that settle (fill, organic, ...).")
    softClay: bool = Field(description="Soft clays settle too.")
    dragloadFactor: Positive = Field(description="Load factor on the dragload in the section.")


class PileEarthPressure(_Group):
    """Alpha 9 C8 (method ``earthPressure``): cohesive base Nc cu (constant), skin α cu (α of
    ``static``); cohesionless skin K σ'v tan δ, δ = deltaShare φ, K by pile kind; base
    ½ D γ' Nγ + σ'v Nq (Nq of ``static.nq``, Nγ = gammaFactor (Nq + 1) tan φ), σ'v constant
    below criticalDepth × D."""

    nc: Positive
    k: dict[Literal["bored", "driven"], Positive]
    deltaShare: Share
    gammaFactor: Positive
    criticalDepth: Positive


class PileRules(_Group):
    """Deep foundation rules: the static method by id, its values, drilled shafts, the SPT
    relations and the settlement of piles."""

    staticMethod: Literal["alphaBeta", "earthPressure"] = Field(
        description="Engine method of the static pile capacity (``alphaBeta``: α in clay, β and "
        "Nq in sand, with the critical depth; alpha 9 C8 ``earthPressure``: α in clay with a "
        "constant Nc, K σ'v tan δ and ½ D γ Nγ + σ'v Nq in sand, IS 2911-1-2 Annex B)."
    )
    earthPressure: PileEarthPressure | None = Field(
        default=None, description="The values of ``earthPressure`` (C8)."
    )
    soilClasses: PileSoilClasses
    static: PileStatic
    drilledShaft: DrilledShaft
    spt: dict[Literal["bored", "driven"], dict[Literal["clay", "sand", "silt"], SptRelation]]
    settlement: PileSettlement
    detailing: PileDetailing | None = Field(
        default=None, description="Structural detailing; empty: not covered by the pack."
    )
    lateral: PileLateral | None = Field(
        default=None, description="Lateral load rules; empty: not covered by the pack."
    )
    loadTests: PileLoadTestRules | None = Field(
        default=None, description="Load test interpretation; empty: not covered by the pack."
    )
    downdrag: PileDowndrag | None = Field(
        default=None, description="Downdrag and swelling uplift; empty: not covered by the pack."
    )


class MachineSpeedClass(_Row):
    """A class of machines by operating speed, with the side of resonance its foundation must
    keep to."""

    id: str
    name: str
    upTo: Positive | None = Field(
        default=None, description="Operating speeds up to this [rpm]; empty: all above."
    )
    inclusive: bool = Field(default=False, description="``upTo`` itself is in the class.")
    allowed: list[Literal["below", "above"]] = Field(
        min_length=1,
        description="``below``: frequency ratio under ``frequencyRatioBelow`` (a stiff "
        "foundation); ``above``: at least ``frequencyRatioAbove`` (a soft one); both: either.",
    )


class MachineAmplitude(_Row):
    """Permissible amplitudes [mm] for a range of operating speeds, as (low, high) ranges; the
    engine takes the low end."""

    upTo: Positive = Field(description="Operating speeds up to this [rpm].")
    inclusive: bool = Field(default=False, description="``upTo`` itself is in the row.")
    horizontal: tuple[Positive, Positive]
    vertical: tuple[Positive, Positive]


class MachineFoundationRules(_Group):
    """Foundations of machines under dynamic forces: the impact rule, resonance, permissible
    amplitudes, static pressure, eccentricity, ground water and the lumped-parameter
    single-degree-of-freedom method with its stiffness and damping relations."""

    method: Literal["lumpedSdof"] = Field(
        description="Engine method (``lumpedSdof``: one mass on one spring and dashpot)."
    )
    impactRatio: Positive = Field(
        description="Impact forces are designed for when the live load causing the impact "
        "exceeds this share of the dead load (or on loose granular soil, cranes, heavy "
        "machinery, moving equipment)."
    )
    speedClasses: list[MachineSpeedClass] = Field(min_length=1)
    frequencyRatioBelow: Positive = Field(description="f/fn below this: a stiff foundation.")
    frequencyRatioAbove: Positive = Field(description="f/fn at least this: a soft foundation.")
    amplitudes: list[MachineAmplitude] = Field(
        description="Permissible amplitudes by operating speed, when the maker gives none."
    )
    hammerAmplitude: Positive = Field(description="Permissible amplitude of hammers [mm].")
    staticPressure: Share = Field(description="Static soil pressure at most this × qa.")
    eccentricity: Share = Field(
        description="Centre of gravity of machine and block off the base's centroid by at most "
        "this × the base dimension."
    )
    waterDepth: Positive = Field(
        description="Ground water at least this × the base width below the base."
    )
    participatingMass: tuple[float, float] = Field(
        description="Range of the participating soil mass ms / mf (the method envelopes it)."
    )
    damping: tuple[Positive, Positive] = Field(
        description="Usual range of the damping factor D of soils (warned outside)."
    )
    barkanCoefficient: Positive = Field(description="k = this × E √A / (1 - μ...).")
    barkanPoisson: list[Literal["linear", "square"]] = Field(
        min_length=1,
        description="Forms of Barkan's denominator enveloped: ``linear`` 1 - μ, ``square`` 1 - μ².",
    )
    plateOffset: Positive = Field(
        description="Cohesionless soil: k = kp ((B + this) / (Bp + this))² [m]."
    )
    decrement: Literal["exact", "approximate"] = Field(
        description="D from the logarithmic decrement: ``exact`` δ / √(4π² + δ²), "
        "``approximate`` δ / 2π."
    )
    hysteresisDivisor: Positive = Field(description="D = ΔW / (this × W).")
    note: str | None = None


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
    shallow: ShallowFoundations | None = Field(
        default=None,
        description="Shallow foundations; empty: the pack does not cover their geotechnical "
        "rules (the engine's general checks only).",
    )
    piles: PileRules | None = Field(
        default=None,
        description="Deep foundation rules; empty: the pack does not cover the static method, "
        "the SPT relations and the pile settlement.",
    )
    machine: MachineFoundationRules | None = Field(
        default=None,
        description="Machine foundations under dynamic forces; empty: not covered by the pack.",
    )
    # D3: values that were module constants of the substructure modules.
    upliftSkin: Share | None = Field(
        default=None,
        description="Share of the skin friction resisting uplift: Tult = this × Qs + W; empty: "
        "the pack gives none (the pile's weight alone).",
    )
    pileCap: PileCapRules | None = Field(
        default=None, description="Pile spacing, cap edges and embedment; empty: not covered."
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
    chordStrip: Positive | None = Field(
        default=None,
        description="Width of the slab strip along a floor's edge whose bars parallel to the "
        "edge count as the diaphragm chord [mm]; empty: the generic default.",
    )


class TransferTable(TableModel):
    """Deep beams and transfer girders, corbels and brackets, diaphragm chords and collectors
    (the default pack's Part 6 Sec 6.4.6, 6.4.7, 2.5.5.6)."""

    deepBeam: DeepBeam
    corbel: Corbel
    diaphragm: Diaphragm


class TwoWayTables(BaseModel):
    """The default pack's Tables 6.6.8-6.6.11: one row per span ratio m = la/lb (ascending), nine cases per
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
    """The default pack's 6.1.4.3: M = w ln² / divisor; shear 1.15 w ln / 2 at the first interior support."""

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
    #: Superseded by the concrete table's ``aggregates.<type>.shrinkageFactor`` (B21); kept so
    #: that older copies of a pack still load. Not read.
    brickAggregateFactor: float | None = Field(default=None, ge=1)
    discontinuousEdgeShare: Share = Field(
        description="SAEngine practice, not a clause of the default pack: top bars at a discontinuous edge "
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


class PipeFittings(_Group):
    """Equivalent pipe lengths of fittings [m] by nominal size (D5: the hydraulics' constants)."""

    sizes: list[PosNum] = Field(min_length=1, description="Nominal sizes [mm], ascending.")
    lengths: dict[str, list[PosNum]] = Field(description="Fitting -> length [m] at each size.")

    @model_validator(mode="after")
    def _lengths(self) -> PipeFittings:
        for name, row in self.lengths.items():
            if len(row) != len(self.sizes):
                raise ValueError(f"lengths.{name}: {len(row)} values for {len(self.sizes)} sizes")
        return self


class TankCombination(_Row):
    """A load combination of the water tanks' design: ``factors`` by load case (D, F, H, Lr);
    a row ``eachFluid`` repeats for each fluid case (F, and F1, F2, ... one compartment full),
    its F standing for that case; a row is used only when the tank has the ``requires`` cases;
    a case the tank does not have is left out of the factors."""

    kind: Literal["strength", "service"]
    clause: str = Field(description="The combination's number in the code, as reported.")
    factors: dict[str, Num]
    eachFluid: bool = False
    requires: list[str] = Field(default_factory=list)


class TankRules(_Group):
    """The code values of the RC water tanks' design (D5: ``plumbing/tanks.py``'s constants);
    the minimum wall steel and the largest spacing are the ``concrete`` table's ``walls``."""

    coverStrengths: list[PosNum] = Field(min_length=1, description="f'c columns [N/mm²].")
    cover: dict[str, list[PosNum | None]] = Field(
        description="Exposure -> nominal cover [mm] at each strength; null: not allowed."
    )
    weatherCover: tuple[PosNum, PosNum] = Field(
        description="Exposed to earth or weather [mm]: bars from weatherBarFrom, smaller bars."
    )
    weatherBarFrom: PosNum = Field(description="[mm]")
    againstEarth: PosNum = Field(description="Cast against and exposed to earth [mm].")
    maxSpacingFactor: PosNum = Field(
        description="Bars at most this x the thickness apart (and concrete.walls.spacingMax)."
    )
    maxWaterCement: Share = Field(description="w/c for concrete of low permeability.")
    combinations: list[TankCombination] = Field(min_length=1)

    @model_validator(mode="after")
    def _cover(self) -> TankRules:
        for exposure, row in self.cover.items():
            if len(row) != len(self.coverStrengths):
                raise ValueError(f"cover.{exposure}: one value per strength expected")
            if all(c is None for c in row):
                raise ValueError(f"cover.{exposure}: no strength allowed")
        return self


class PlumbingTable(_Services):
    """The default pack's Part 8 Chapters 5-7: water supply, drainage, rainwater; and SAEngine's pipe
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
    # D5: the hydraulics' and the tanks' code values (None: not covered by the pack)
    fixtureFlow: dict[str, PosNum] | None = Field(
        default=None, description="Required flow of a single fixture [l/min], flush tanks."
    )
    fixtureFlowValve: dict[str, PosNum] | None = Field(
        default=None, description="Fixtures whose flow differs with flush valves [l/min]."
    )
    outletAboveBottom: PosNum | None = Field(
        default=None, description="A storage tank's outlet above its bottom [mm]."
    )
    fittings: PipeFittings | None = None
    tanks: TankRules | None = None

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


class HvacAir(_Group):
    """The code values of the air distribution (D5: ``hvac/air.py``'s and ``hvac/openings.py``'s
    constants): outdoor air, exhaust rates, kitchen exhaust, headroom under ducts."""

    minPerPerson: PosNum = Field(description="Outdoor air at least [l/s per person].")
    kitchenExhaustVelocity: tuple[PosNum, PosNum] = Field(description="Least, most [m/s].")
    toiletPublic: tuple[PosNum, PosNum] = Field(
        description="Per water closet or urinal [l/s]: normal, heavy use."
    )
    toiletPrivate: tuple[PosNum, PosNum] = Field(
        description="Per bathroom of a dwelling [l/s]: continuous, intermittent."
    )
    toiletHotel: tuple[PosNum, PosNum] = Field(description="Per hotel bathroom [l/s].")
    kitchenPrivate: tuple[PosNum, PosNum] = Field(
        description="Per dwelling kitchen [l/s]: continuous, intermittent."
    )
    kitchenEquipment: dict[str, tuple[PosNum | None, PosNum | None]] = Field(
        description="Kitchen equipment -> exhaust [l/s per kW]: electric, gas; null: none."
    )
    kitchenDefault: str = Field(description="kitchenEquipment row of an unknown mix (gas).")
    ventilationPages: dict[str, int] = Field(
        default_factory=dict, description="Ventilation group -> page of its rows."
    )
    ceilingHeights: dict[str, PosNum] = Field(
        description="Ventilation group -> air-conditioned ceiling height [mm]."
    )
    assemblyUses: list[str] = Field(default_factory=list)
    assemblyCeiling: PosNum = Field(description="Ceiling height of the assembly uses [mm].")
    headroomUnderDuct: PosNum = Field(description="Least headroom under a duct [mm].")
    kitchenClearance: PosNum = Field(description="Kitchen exhaust duct to enclosure [mm].")

    @model_validator(mode="after")
    def _kitchen(self) -> HvacAir:
        if self.kitchenDefault not in self.kitchenEquipment:
            raise ValueError(f"kitchenDefault: no kitchenEquipment row '{self.kitchenDefault}'")
        return self


class CopStep(_Row):
    upTo: PosNum | None = Field(description="Unit size below this [kW]; null: above the last.")
    cop: PosNum


class HvacPlant(_Group):
    """The code values of the plant proposal (D5: ``hvac/plant.py``'s constants)."""

    cop: dict[str, list[CopStep]] = Field(description="Chiller class -> minimum COP by size.")
    waterCooledFrom: PosNum = Field(description="Water-cooled chillers from this plant [kW].")
    headroomFrom: PosNum = Field(description="Plant room headroom rule from this [kW].")
    headroom: dict[str, PosNum] = Field(
        description="Chiller class -> clear headroom below the beam soffits [mm]; 'other'."
    )


class HvacTable(_Services):
    """The default pack's Part 8 Chapter 2 (air-conditioning) and Part 3 Chapter 4 (energy); SAEngine's
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
    # D5: the air distribution's and the plant's code values (None: not covered by the pack)
    air: HvacAir | None = None
    plant: HvacPlant | None = None

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
    """The default pack's Part 8 Chapter 1 (electrical services) and Sec 4.2.1 (lifts); typical equipment
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
    """The default pack's Part 4 (fire protection): flows, durations, pressures, pump ratings, pipe
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


class RoofReduction(_Group):
    """Lr = L0 R1 R2 within [minimum, maximum]: R1 from the tributary area, R2 from the slope."""

    areaLow: Positive = Field(description="R1 = 1 up to this tributary area [m²].")
    areaHigh: Positive = Field(description="R1 = r1Min from this tributary area [m²].")
    r1Constant: Positive = Field(description="a of R1 = a - b AT between the two.")
    r1Coefficient: Positive = Field(description="b of R1 = a - b AT [1/m²].")
    r1Min: Share
    riseLow: Positive = Field(description="R2 = 1 up to this F.")
    riseHigh: Positive = Field(description="R2 = r2Min from this F.")
    r2Constant: Positive = Field(description="a of R2 = a - b F between the two.")
    r2Coefficient: Positive = Field(description="b of R2 = a - b F.")
    r2Min: Share
    slopeF: Positive = Field(description="Pitched roof: F = this × slope in per cent.")
    archF: Positive = Field(description="Arch or dome: F = this × rise / span.")
    minimum: Positive = Field(description="Least reduced roof live load [kN/m²].")
    maximum: Positive = Field(description="Most reduced roof live load [kN/m²].")
    uses: list[str] = Field(description="Area uses the rule reduces (ordinary roofs).")


class AreaAndStoreys(_Group):
    """C4: EN 1991-1-1 6.3.1.2(10)-(11): αA = ``areaShare``·ψ0 + A0/A ≤ 1 (at least
    ``categoryMinimum`` in the ``minimumCategories``), αn = (2 + (n - 2)·ψ0)/n for columns and
    walls of n > 2 storeys; the member takes ``combine`` of the two ("lesser": the one that
    reduces more, used alone)."""

    psi0: Share = Field(description="ψ0 of the imposed load.")
    areaShare: Positive = Field(description="5/7 of αA.")
    referenceArea: Positive = Field(description="A0 [m²].")
    categoryMinimum: Share | None = None
    minimumCategories: list[str] = Field(default_factory=list)
    storeysFrom: int = Field(default=3, ge=2, description="αn applies from this many storeys.")
    combine: Literal["lesser"] = "lesser"


class FloorCountReduction(_Group):
    """C7, ``method: floorCount`` (IS 875-2 3.2): L / L0 = 1 − the share of the first (floors,
    share) row whose floors is at least the floors the member carries (the last row above it);
    a member of one floor (beams) with a tributary area of ``beamArea`` m² or more is reduced by
    ``beamShare`` per ``beamArea`` m², at most ``beamMax``."""

    rows: list[tuple[int, Annotated[float, Field(ge=0, lt=1)]]] = Field(min_length=1)
    beamArea: Positive | None = None
    beamShare: Share | None = None
    beamMax: Share | None = None


class LiveReductionTable(TableModel):
    """Reduction of floor live loads by influence area (the default pack's Part 6 Sec 2.3.13),
    or (C4, ``method`` areaAndStoreys) by the loaded area and the number of storeys, or (C7,
    ``floorCount``) by the number of floors carried."""

    method: Literal["influenceArea", "areaAndStoreys", "floorCount"] = "influenceArea"
    areaAndStoreys: AreaAndStoreys | None = None
    floorCount: FloorCountReduction | None = None
    influenceMin: Positive | None = Field(
        default=None, description="Least KLL AT [m²] that is reduced."
    )
    constant: Share | None = Field(default=None, description="a of L = L0 (a + b / √(KLL AT)).")
    coefficient: Positive | None = Field(
        default=None, description="b of L = L0 (a + b / √(KLL AT)) [m]."
    )
    minOneFloor: Share | None = Field(
        default=None, description="Least L / L0 of members supporting one floor."
    )
    minFloors: Share | None = Field(
        default=None, description="Least L / L0 of members supporting two or more."
    )
    heavyLive: Positive = Field(description="Live loads above this [kN/m²] are not reduced.")
    heavyFactor: Share | None = Field(
        default=None, description="L / L0 of heavy loads on members of 2+ floors."
    )
    notReduced: list[str] = Field(description="Area uses never reduced.")
    assemblyMax: float | None = Field(
        default=None,
        gt=0,
        description="The ``notReduced`` uses are not reduced up to this L0 [kN/m²] (above it the "
        "heavy load rule applies); empty: never reduced.",
    )
    twoFloorsOnly: list[str] = Field(description="Area uses reduced only on 2+ floors.")
    notReducedBuildings: list[str] = Field(
        default_factory=list,
        description="Building kinds (project occupancy flags such as cycloneShelter) whose live "
        "loads are never reduced.",
    )
    oneWaySlabWidth: Positive | None = Field(
        default=None,
        description="AT of a one-way slab at most its span times this many spans wide.",
    )
    kll: LiveElementFactors | None = None
    roof: RoofReduction | None = Field(
        default=None, description="Reduction of the ordinary roof live load (Lr)."
    )

    @model_validator(mode="after")
    def _method_values(self) -> LiveReductionTable:
        if self.method == "areaAndStoreys":
            if self.areaAndStoreys is None:
                raise ValueError("areaAndStoreys: the method needs its values")
            return self
        if self.method == "floorCount":
            if self.floorCount is None:
                raise ValueError("floorCount: the method needs its rows")
            return self
        names = ("influenceMin", "constant", "coefficient", "minOneFloor", "minFloors")
        missing = [n for n in (*names, "heavyFactor", "kll") if getattr(self, n) is None]
        if missing:
            raise ValueError(f"influenceArea needs {', '.join(missing)}")
        return self


Hours = Annotated[float, Field(ge=0)]


class ConstructionTypeRow(_Row):
    """The fire resistance ratings [h] of the elements of one construction type; None: the
    code gives no fixed rating (e.g. 'as per the provisions of the code')."""

    label: str
    group: Literal["nonCombustible", "combustible"]
    exteriorBearing: list[Hours] = Field(
        description="Exterior bearing walls, one rating per band of ``separationLimits``."
    )
    exteriorNonBearing: list[Hours] = Field(
        description="Exterior non-bearing walls, one rating per band of ``separationLimits``."
    )
    interiorBearingWalls: Hours | None = None
    verticalExits: Hours | None = Field(
        default=None, description="Enclosures of vertical exits, exit passageways and shafts."
    )
    framingOneFloor: Hours | None = Field(
        default=None, description="Columns, girders and framing supporting one floor."
    )
    framingMoreFloors: Hours | None = Field(
        default=None, description="Columns, girders and framing supporting more than one floor."
    )
    membersSupportingWalls: Hours | None = Field(
        default=None, description="Structural members supporting walls (None: as the wall)."
    )
    floors: Hours | None = Field(default=None, description="Floor construction with its beams.")
    shafts: Hours | None = None
    fireSeparationWalls: Hours | None = None
    accessCorridors: Hours | None = None
    note: str | None = None


class FireAdvisory(BaseModel):
    """Covers of the concrete members by rating from a standard other than the code, shown as an
    advisory (never failing a member)."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="Where the covers come from, as the results print it.")
    ratings: list[Positive] = Field(min_length=1, description="Ratings [h].")
    slabCover: list[Positive] = Field(description="Least slab cover to the bars [mm].")
    beamCover: list[Positive] = Field(description="Least beam cover to the main bars [mm].")
    beamWidth: Positive = Field(description="Least beam width the beam covers hold for [mm].")
    columnCoverPerHour: Positive = Field(description="Column cover per hour of rating [mm].")
    columnCoverMax: Positive = Field(description="Column cover need not exceed [mm].")

    @model_validator(mode="after")
    def _same_length(self) -> FireAdvisory:
        for name in ("slabCover", "beamCover"):
            if len(getattr(self, name)) != len(self.ratings):
                raise ValueError(f"advisory.{name}: one value per rating ({len(self.ratings)})")
        return self


class FireResistanceTable(TableModel):
    """Construction types with the fire resistance ratings of their elements, and the least
    sizes of concrete and masonry members for a rating, one value per rating (hours) by the
    concrete's aggregate type or the masonry unit."""

    name: str = ""
    clauses: dict[str, str] = Field(
        default_factory=dict,
        description="Short clause references the checks print: nonCombustible, combustible "
        "(the ratings of each group), thickness, columnSize, masonryThickness, "
        "nonCombustibleAbove.",
    )
    constructionTypes: dict[str, ConstructionTypeRow] = Field(
        default_factory=dict, description="Construction types by id."
    )
    separationLimits: list[Positive] = Field(
        default_factory=list,
        description="Limits of the fire separation distance bands of the exterior walls [m]: the "
        "first band is up to and including the first limit, each next band below its limit, the "
        "last band at or beyond the last limit.",
    )
    nonCombustibleAbove: Positive | None = Field(
        default=None, description="Buildings higher than this [m] must be non-combustible."
    )
    aggregates: dict[str, str] = Field(
        default_factory=dict, description="Aggregate types the tables cover, with their names."
    )
    ratings: list[Positive] = Field(min_length=1, description="Ratings of the concrete rows [h].")
    thickness: dict[str, list[Positive]] = Field(
        description="Least equivalent thickness of concrete walls, floors and roofs [mm] by "
        "aggregate type."
    )
    columnSize: dict[str, list[Positive]] = Field(
        description="Least column dimension [mm] by aggregate type."
    )
    columnSizeFallback: dict[str, str] = Field(
        default_factory=dict,
        description="Aggregate types without a column row: the row used instead.",
    )
    aggregateFallback: dict[str, str] = Field(
        default_factory=dict,
        description="B21: aggregate types the table has no rows for at all (thickness and "
        "column size): the type whose rows are used instead.",
    )
    masonryRatings: list[Positive] = Field(
        default_factory=list, description="Ratings of the masonry rows [h]."
    )
    masonryThickness: dict[str, list[Positive]] = Field(
        default_factory=dict,
        description="Least equivalent thickness of masonry [mm] by unit (clayUnfilled, "
        "clayFilled, concreteUnfilled, concreteFilled).",
    )
    advisory: FireAdvisory | None = None

    @model_validator(mode="after")
    def _same_length(self) -> FireResistanceTable:
        n = len(self.ratings)
        for name in ("thickness", "columnSize"):
            for key, row in getattr(self, name).items():
                if len(row) != n:
                    raise ValueError(f"{name}.{key}: one value per rating ({n})")
        for key, row in self.masonryThickness.items():
            if len(row) != len(self.masonryRatings):
                raise ValueError(f"masonryThickness.{key}: one value per masonry rating")
        bands = len(self.separationLimits) + 1
        for key, t in self.constructionTypes.items():
            for name in ("exteriorBearing", "exteriorNonBearing"):
                if len(getattr(t, name)) != bands:
                    raise ValueError(f"constructionTypes.{key}.{name}: one value per band")
        for key, to in self.columnSizeFallback.items():
            if to not in self.columnSize:
                raise ValueError(f"columnSizeFallback.{key}: no column row '{to}'")
        for key, to in self.aggregateFallback.items():
            if to not in self.thickness or to not in self.columnSize:
                raise ValueError(f"aggregateFallback.{key}: no rows for '{to}'")
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


class TimberSpecies(BaseModel):
    """A species of the code's table: its characters and, where the table gives them, its own
    permissible stresses [MPa] (else the member is designed with its strength group)."""

    model_config = ConfigDict(extra="forbid")

    botanical: str
    name: str | None = Field(default=None, description="Trade name.")
    density: Positive | None = Field(default=None, description="At 12% moisture [kg/m³].")
    durability: str | None = Field(default=None, description="Durability class (I, II, III).")
    treatability: str | None = None
    seasoning: str | None = None
    E: Positive | None = Field(default=None, description="[MPa]")
    bending: dict[TimberLocation, Positive] | None = None
    shearHorizontal: Positive | None = None
    shearAlong: Positive | None = None
    compressionParallel: dict[TimberLocation, Positive] | None = None
    compressionPerpendicular: dict[TimberLocation, Positive] | None = None
    note: str | None = None

    @property
    def has_stresses(self) -> bool:
        return self.E is not None and self.bending is not None


class TimberSlope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slope: Positive = Field(description="Slope of grain 1 in `slope`.")
    beams: Positive = Field(description="K1 of beams, joists and ties.")
    columns: Positive = Field(description="K1 of posts and columns.")


class TimberLowDurability(_Group):
    factor: Positive
    classes: list[str]
    locations: list[TimberLocation]


class TimberColumn(_Group):
    short: Positive = Field(description="S/d up to which a column is short.")
    k8: Positive = Field(description="K8 = k8 √(E/fcp), where long columns start.")
    intermediate: Positive = Field(description="fcp [1 - (S/(K8 d))⁴ / intermediate].")
    long: Positive = Field(description="Long columns: long · E / (S/d)².")
    maxSlenderness: Positive = Field(description="Largest S/d.")


class TimberPlank(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t: Positive = Field(description="Plank thickness [mm].")
    U: Positive
    q: Positive


class TimberBoxColumn(_Group):
    short: Positive = Field(description="S/√(d1² + d2²) below which a box column is short.")
    k9: Positive = Field(description="K9 = k9 √(U E/(q fcp)).")
    planks: list[TimberPlank] = Field(min_length=1)


class TimberSpacedColumn(_Group):
    restraint: dict[str, Positive] = Field(description="End-connector position -> factor.")
    k10: Positive = Field(description="K10 = k10 √(factor E/fcp).")
    maxSlenderness: Positive = Field(description="Largest S/d of each member.")


class TimberDepthFactor(_Group):
    above: Positive = Field(description="Depth [mm] above which K3 applies.")
    factor: Positive
    a: Positive
    b: Positive


class TimberFormFactors(_Group):
    boxBase: Positive = Field(description="K4 = boxBase + boxFactor y (K3/factor - 1).")
    boxFactor: Positive
    circle: Positive = Field(description="K5 of solid circular sections.")
    squareDiagonal: Positive = Field(description="K6 of squares loaded on the diagonal.")


class TimberDuration(_Group):
    continuous: Positive
    twoMonths: Positive
    sevenDays: Positive
    windEarthquake: Positive
    impact: Positive


class TimberFlexure(_Group):
    minWidth: Positive = Field(description="[mm]")
    widthSpanRatio: Positive = Field(description="Width at least span / this.")
    depthWidthRatio: Positive = Field(description="Deeper than this × width: restrain.")
    spanWidthRatio: Positive = Field(description="Longer than this × width: restrain.")
    restraintWidthRatio: Positive = Field(description="Restraints at most this × width apart.")
    notchDepthShare: Share
    notchSpanShare: Share
    notchSectionShare: Share
    minBearing: Positive = Field(description="[mm]")


class TimberK7(BaseModel):
    model_config = ConfigDict(extra="forbid")

    length: Positive = Field(description="Bearing length [mm].")
    factor: Positive


class TimberBearing(_Group):
    fullLength: Positive = Field(description="Bearings this long or more: K7 = 1 [mm].")
    fromEnd: Positive = Field(description="K7 only for bearings this far from the end [mm].")
    k7: list[TimberK7] = Field(min_length=1)


class TimberNearSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distance: Positive = Field(description="Load to the support, in beam depths.")
    reduction: Annotated[float, Field(ge=0, le=1)]


class TimberDeflection(_Group):
    brittle: Positive = Field(description="Span / this, supporting brittle finishes.")
    span: Positive
    cantilever: Positive
    deadLoadFactor: Positive = Field(description="Dead load × this for the long term.")


class TimberNailStrength(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lengthening: Positive = Field(description="Permanent, lengthening joints [N].")
    node: Positive = Field(description="Permanent, node joints [N].")
    temporary: Positive = Field(description="Temporary structures [N].")


class TimberNailSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diameter: Positive = Field(description="[mm]")
    lengths: list[Positive] = Field(description="[mm]")
    strengths: dict[str, TimberNailStrength] = Field(description="Species id -> strengths.")


class TimberNailSpacing(_Group):
    endTension: Positive
    endCompression: Positive
    alongTension: Positive
    alongCompression: Positive
    edge: Positive
    rows: Positive


class TimberNails(_Group):
    minThickness: Positive = Field(description="Main members, mono-chord [mm].")
    diameterMin: Positive = Field(description="Diameter at least the least thickness / this.")
    diameterMax: Positive = Field(description="Diameter at most the least thickness / this.")
    penetration: Positive = Field(description="Lap joints: × the thinner member.")
    minNode: Annotated[int, Field(gt=0)]
    minLengthening: Annotated[int, Field(gt=0)]
    clenched: Positive
    spacing: TimberNailSpacing
    sizes: dict[str, TimberNailSize] = Field(min_length=1)


class TimberBoltBearing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ratio: Positive = Field(description="t'/d3.")
    parallel: Positive | None = Field(default=None, description="λ1 [%].")
    perpendicular: Positive = Field(description="λ2 [%].")


class TimberBoltSpacing(_Group):
    inRow: Positive
    rowsPerpendicularLow: Positive
    rowsPerpendicularHigh: Positive
    ratioLow: Positive
    ratioHigh: Positive
    rowsParallel: Positive
    endTensionSoftwood: Positive
    endTensionHardwood: Positive
    endCompression: Positive
    edgeParallel: Positive
    edgePerpendicular: Positive


class TimberBolts(_Group):
    singleShear: Share
    minNode: Annotated[int, Field(gt=0)]
    minLengthening: Annotated[int, Field(gt=0)]
    minMain: Positive = Field(description="[mm]")
    minSide: Positive = Field(description="[mm]")
    sideShare: Share = Field(description="Side members at least this × the main member.")
    bearing: list[TimberBoltBearing] = Field(min_length=1)
    diameterFactor: dict[str, Positive] = Field(description="Bolt diameter [mm] -> df.")
    spacing: TimberBoltSpacing


class TimberConnectors(_Group):
    ringMinMain: Positive
    ringMinSide: Positive
    ringEdge: Positive = Field(description="Loaded edge × the ring diameter.")
    ringEnd: Positive = Field(description="End distance × the ring diameter.")
    dowelThickness: tuple[Positive, Positive]
    dowelDiameter: tuple[Positive, Positive]
    dowelRatio: tuple[Positive, Positive]
    dowelEdge: tuple[Positive, Positive]
    dowelEndTension: Positive
    dowelEndCompression: Positive


# ── Alpha 9 C3b: timber by reference design values and adjustment factors (the
# ``referenceDesign`` method, saengine.design.timber.reference; e.g. NDS 2018) ──

TimberValueKey = Literal["Fb", "Ft", "Fv", "Fcp", "Fc", "E", "Emin"]
TimberSizeClass = Literal["dimension", "beamsStringers", "postsTimbers", "glulam"]


class TimberReferenceValues(BaseModel):
    """Reference design values of one grade and size class, in the table's ``units``: Fb
    bending (glulam: tension zone stressed in tension), Ft tension and Fc compression parallel
    to the grain, Fv shear, Fcp compression perpendicular to the grain, E and Emin."""

    model_config = ConfigDict(extra="forbid")

    Fb: Positive
    Ft: Positive
    Fv: Positive
    Fcp: Positive
    Fc: Positive
    E: Positive
    Emin: Positive
    FbNegative: Positive | None = Field(
        default=None, description="Glulam: Fb with the compression zone stressed in tension."
    )
    Fby: Positive | None = Field(default=None, description="Bending about the weak axis.")


class TimberReferenceSpecies(BaseModel):
    """A species combination (sawn lumber) or a glued laminated timber stress class."""

    model_config = ConfigDict(extra="forbid")

    name: str
    product: Literal["sawn", "glulam"] = "sawn"
    G: Positive = Field(description="Specific gravity (connections).")
    grades: dict[str, dict[TimberSizeClass, TimberReferenceValues]] = Field(min_length=1)
    source: str = ""


class TimberSizeFactorRow(BaseModel):
    """CF of dimension lumber up to a depth (wide face) [mm]: Fb by thickness (up to
    ``thinMax``, above), Ft, Fc."""

    model_config = ConfigDict(extra="forbid")

    depthMax: float | None = Field(gt=0, description="[mm]; null: any deeper.")
    Fb: tuple[Positive, Positive]
    Ft: Positive
    Fc: Positive


class TimberFlatUseRow(BaseModel):
    """Cfu of dimension lumber on its wide face up to a width [mm], by thickness."""

    model_config = ConfigDict(extra="forbid")

    widthMax: float | None = Field(gt=0, description="[mm]; null: any wider.")
    factor: tuple[Positive, Positive]


class TimberTemperatureRow(BaseModel):
    """Ct up to a service temperature [°C], dry and wet, by value."""

    model_config = ConfigDict(extra="forbid")

    tMax: Positive
    dry: dict[TimberValueKey, Positive]
    wet: dict[TimberValueKey, Positive]


class TimberWetService(BaseModel):
    """CM of one size class by value, and the thresholds below which CM of Fb and Fc is 1
    (dimension lumber: Fb CF and Fc CF in the table's units)."""

    model_config = ConfigDict(extra="forbid")

    factors: dict[TimberValueKey, Positive]
    fbExempt: float | None = Field(default=None, gt=0)
    fcExempt: float | None = Field(default=None, gt=0)


class TimberVolumeFactor(_Group):
    """Glulam CV = (length/L)^(1/x) (depth/d)^(1/x) (width/b)^(1/x) <= 1 [mm]."""

    length: Positive
    depth: Positive
    width: Positive
    exponent: Positive


class TimberSizeClasses(_Group):
    """How a sawn section's size class is found [mm]: thickness up to ``dimensionMax`` is
    dimension lumber; thicker, beams and stringers when the depth exceeds the thickness by more
    than ``beamsExcess``, else posts and timbers."""

    dimensionMax: Positive
    beamsExcess: Positive
    thinMax: Positive = Field(description="Dimension lumber up to this thick: the first CF of Fb.")
    timberDepth: Positive = Field(description="Timbers deeper than this: CF = (this/d)^(1/x).")
    timberExponent: Positive = Field(description="x of the timbers' CF.")


class TimberBeamStability(_Group):
    """CL: le from lu (the generic rule for any load), RB = √(le d / b²) <= rbMax, FbE = fbe
    Emin' / RB², CL = (1 + α)/a - √(((1 + α)/a)² - α/b), α = FbE / Fb*."""

    shortRatio: Positive = Field(description="lu/d below this: le = shortFactor lu.")
    shortFactor: Positive
    longRatio: Positive = Field(description="lu/d up to this: le = midFactor lu + midDepth d.")
    midFactor: Positive
    midDepth: Positive
    longFactor: Positive = Field(description="Above longRatio: le = longFactor lu.")
    rbMax: Positive
    fbe: Positive
    a: Positive
    b: Positive


class TimberColumnStability(_Group):
    """CP = (1 + α)/(2c) - √(((1 + α)/(2c))² - α/c), α = FcE / Fc*, FcE = fce Emin' /
    (le/d)²; c by product; le/d at most maxSlenderness."""

    fce: Positive
    c: dict[Literal["sawn", "glulam"], Positive]
    maxSlenderness: Positive


class TimberLrfd(_Group):
    """The LRFD format: KF and φ by value; connections KF, φz; the time effect factor λ."""

    KF: dict[TimberValueKey, Positive]
    phi: dict[TimberValueKey, Positive]
    connectionKF: Positive
    connectionPhi: Positive
    timeEffect: dict[str, Positive] = Field(
        description="λ: ``dead`` (dead load alone), ``roof`` (roof live, snow, rain governing), "
        "``lateral`` (wind or earthquake), and per live load duration (continuous, twoMonths, "
        "sevenDays, impact) when the live load governs."
    )


class TimberDowels(_Group):
    """Dowel-type fasteners (yield limit equations): dowel bearing strengths Fe = parallel × G
    (D >= ``smallDiameter``), perpendicular × G^perpendicularExponent / √D (D in in.), small
    dowels small × G^smallExponent; Fyb by fastener; the reduction terms Rd; steel side plates
    Fe = steelShare × Fu; group action γ; the geometry factor by end distance."""

    smallDiameter: Positive = Field(description="[mm]")
    parallel: Positive
    perpendicular: Positive
    perpendicularExponent: Positive
    small: Positive
    smallExponent: Positive
    boltFyb: Positive = Field(description="In the table's units.")
    nailFyb: list[tuple[Positive, Positive]] = Field(
        description="[[diameter up to (mm), Fyb], ...]."
    )
    rdLarge: dict[str, Positive] = Field(
        description="Rd / Kθ of D >= smallDiameter by mode group: I, II, III (III and IV)."
    )
    kTheta: Positive = Field(description="Kθ = 1 + this × θ/90°.")
    rdSmall: tuple[Positive, Positive, Positive] = Field(
        description="KD of small dowels: [up to (mm), KD there, a] with KD = a D (in.) + 0.5 above."
    )
    groupGamma: Positive = Field(description="Load/slip modulus γ = this × D^1.5 (lb/in, in.).")
    endFull: dict[str, Positive] = Field(
        description="End distance for CΔ = 1, in diameters: tensionSoftwood, tensionHardwood, "
        "compression."
    )
    endMin: dict[str, Positive] = Field(description="End distance for CΔ = 0.5 (the least).")
    spacingFull: Positive = Field(description="Spacing in a row for CΔ = 1, in diameters.")
    spacingMin: Positive = Field(description="Least spacing in a row, in diameters.")
    wetService: Positive = Field(description="CM of the lateral values in wet service.")


class TimberReference(_Group):
    """Reference design values and their adjustment factors (the ``referenceDesign`` method)."""

    units: str = Field(description="The unit of the stresses below, e.g. psi.")
    toMPa: Positive = Field(description="× this gives MPa.")
    format: Literal["ASD", "LRFD"] = Field(
        default="ASD",
        description="ASD (allowable stress combinations, CD) or LRFD (strength "
        "combinations, KF, φ, λ).",
    )
    defaultSpecies: str
    defaultGrade: str
    species: dict[str, TimberReferenceSpecies] = Field(min_length=1)
    sizeClasses: TimberSizeClasses
    sizeFactors: dict[str, list[TimberSizeFactorRow]] = Field(
        description="CF of dimension lumber by grade group: ``default`` and the groups of "
        "``sizeFactorGroups``."
    )
    sizeFactorGroups: dict[str, str] = Field(
        default_factory=dict, description="Grade -> its CF group (else ``default``)."
    )
    flatUse: list[TimberFlatUseRow]
    volume: TimberVolumeFactor
    wetService: dict[TimberSizeClass, TimberWetService]
    temperature: list[TimberTemperatureRow] = Field(min_length=1)
    incising: dict[TimberValueKey, Positive]
    repetitive: Positive
    duration: dict[str, float | str] = Field(
        description="CD by load case (the longest prefix of the case's name): a number, or "
        "``live`` (the material's live load duration, ``liveDuration``)."
    )
    liveDuration: dict[str, Positive] = Field(
        description="CD of the live load by the material's live load duration."
    )
    lrfd: TimberLrfd
    beamStability: TimberBeamStability
    columnStability: TimberColumnStability
    bearingArea: tuple[Positive, Positive] = Field(
        description="Cb = (lb + a) / lb for bearings shorter than b [mm]: [a, b]."
    )
    dowels: TimberDowels


class TimberTable(TableModel):
    """Permissible stress design of structural timber: stresses by strength group, species and
    location, grade, durability, slope-of-grain and duration factors, form factors, the column
    formulas (solid, box, spaced), flexural member rules, bearing, deflection, and the nailed,
    bolted, split-ring and disc-dowel joints. ``clauses``: the clause of each check (after the
    pack's name in results)."""

    groups: dict[str, TimberGroup] = Field(min_length=1)
    species: dict[str, TimberSpecies] = Field(default_factory=dict)
    grades: dict[str, Positive] = Field(description="Grade -> factor on the stresses.")
    lowDurability: TimberLowDurability
    slopeOfGrain: list[TimberSlope] = Field(min_length=1)
    duration: TimberDuration
    column: TimberColumn
    boxColumn: TimberBoxColumn
    spacedColumn: TimberSpacedColumn
    depthFactor: TimberDepthFactor
    formFactors: TimberFormFactors
    flexure: TimberFlexure
    bearing: TimberBearing
    concentratedNearSupport: list[TimberNearSupport] = Field(min_length=1)
    deflection: TimberDeflection
    nails: TimberNails
    bolts: TimberBolts
    connectors: TimberConnectors
    clauses: dict[str, str] = Field(default_factory=dict)
    # Alpha 9 C3b: the design method (``referenceDesign``: reference values and adjustment
    # factors, saengine.design.timber.reference) and its data.
    method: Literal["permissibleStress", "referenceDesign"] = Field(
        default="permissibleStress",
        description="Timber members by ``permissibleStress`` (the stresses above, K factors) or "
        "``referenceDesign`` (the ``reference`` values times their adjustment factors).",
    )
    reference: TimberReference | None = None

    @model_validator(mode="after")
    def _reference(self) -> TimberTable:
        if self.method == "referenceDesign" and self.reference is None:
            raise ValueError("method 'referenceDesign' needs the 'reference' data")
        return self


# ───────────────────────────────────────── masonry ─────────────────────────────────────────


MasonryUnitKind = Literal["clay", "concrete"]
MasonryUnits = Literal["solid", "hollow"]


class MasonryMortar(_Group):
    """One mortar grade: the cement : sand mix by volume and its least strength [MPa]."""

    cement: Positive
    sand: Positive
    strength: Positive = Field(description="Least 28-day compressive strength [MPa].")


class MasonryQuality(_Group):
    reducedShare: Share = Field(
        description="Share of the allowable masonry stresses without special inspection or "
        "prism tests during construction."
    )
    reusedUnitsShare: Share = Field(description="Largest share for reused units.")
    prismsBeforeConstruction: int = Field(gt=0)
    prismsDuringConstruction: int = Field(gt=0)
    wallAreaPerSet: Positive = Field(description="Wall area per set of prisms [m²].")
    note: str = ""


class MasonryLateralIncrease(_Group):
    factor: float = Field(ge=1, description="Allowable stresses × this with wind or earthquake.")
    note: str = ""


class MasonryAllowableAxial(_Group):
    """Fa = fmShare f'm [1 - (h'/(slenderness t))^exponent]; columns + As Fsc/(columnSteelArea
    Ag)."""

    fmShare: Share
    slenderness: Positive
    exponent: Positive
    columnSteelArea: Positive
    # Alpha 9 C3b (TMS 402-22 Eqs 8-12, 8-13 in h'/t of solid sections): slender members.
    longAbove: float | None = Field(
        default=None,
        gt=0,
        description="h'/t above which Fa = fmShare f'm (longCoefficient t / h')² (none: the "
        "formula above at every slenderness).",
    )
    longCoefficient: float | None = Field(default=None, gt=0)


class MasonryShareCap(_Group):
    """A stress fmShare × f'm (or factor × √f'm) at most cap [MPa]."""

    fmShare: Share
    cap: Positive
    # Alpha 9 C3b (TMS 402-22 Sec 8.3.4.2.2): reinforced masonry's own share.
    reinforcedShare: Share | None = Field(
        default=None, description="Fb of reinforced masonry = this × f'm (none: fmShare)."
    )


class MasonryRootCap(_Group):
    factor: Positive = Field(description="× √f'm [MPa].")
    cap: Positive


class MasonryFlexuralTension(_Group):
    bedJoints: dict[MasonryUnits, Positive] = Field(description="Normal to bed joints [MPa].")
    headJoints: dict[MasonryUnits, Positive] = Field(description="Normal to head joints [MPa].")
    headJointsByUnit: dict[MasonryUnitKind, dict[MasonryUnits, Positive]]
    fullMortars: list[str] = Field(description="Mortar grades with the full values.")
    reducedMortars: list[str] = Field(description="Mortar grades with the reduced values.")
    reduction: Share = Field(description="Reduction of the values for reducedMortars.")
    note: str = ""


class MasonryBeamShear(_Group):
    unreinforced: MasonryRootCap
    reinforced: MasonryRootCap


class MasonryAxialFriction(_Group):
    """Alpha 9 C3b (TMS 402-22 Sec 8.2.6.2): Fv of unreinforced masonry, the least of
    rootFactor √f'm, cap and base + friction × fa (groutedBase in running bond, solid grouted;
    stackBond in stack bond) [MPa]."""

    rootFactor: Positive
    cap: Positive
    base: Positive
    groutedBase: Positive
    friction: Positive
    stackBond: Positive


class MasonryPlainWallShear(_Group):
    clay: MasonryRootCap
    concrete: dict[str, Positive] = Field(description="Fv by mortar grade [MPa].")
    method: Literal["byUnit", "axialFriction"] = Field(
        default="byUnit",
        description="``byUnit`` (clay by √f'm, concrete by mortar grade) or ``axialFriction`` "
        "(alpha 9 C3b: the least of √f'm, a cap and base + friction × fa).",
    )
    axialFriction: MasonryAxialFriction | None = None
    note: str = ""


class MasonryShearRow(_Group):
    """Fv = (1/divisor)(first - M/Vd) √f'm ≤ maxFirst - maxSlope M/Vd below M/Vd = 1;
    above √f'm ≤ maxAbove at M/Vd ≥ 1 [MPa]."""

    divisor: Positive
    first: Positive
    above: Positive
    maxFirst: Positive
    maxSlope: Positive
    maxAbove: Positive


class MasonryAdditiveShear(_Group):
    """Alpha 9 C3b (TMS 402-22 Sec 8.3.5.1): Fv = Fvm + Fvs, Fvm = masonryFactor (first - slope
    M/(V dv)) √f'm + axialShare P/An, Fvs = steelShare ρh Fs; at most maxLow √f'm up to
    M/(V dv) = ratioLow and maxHigh √f'm from 1.0, linear between; fv = V / An [MPa]."""

    masonryFactor: Positive
    first: Positive
    slope: Positive
    axialShare: float = Field(ge=0)
    steelShare: Positive
    ratioLow: float = Field(ge=0, lt=1)
    maxLow: Positive
    maxHigh: Positive


class MasonryReinforcedWallShear(_Group):
    masonry: MasonryShearRow
    reinforcement: MasonryShearRow
    method: Literal["alternative", "additive"] = Field(
        default="alternative",
        description="``alternative`` (the masonry or the reinforcement taking all the shear, "
        "fv = V/(t j d)) or ``additive`` (alpha 9 C3b: Fv = Fvm + Fvs, fv = V/An).",
    )
    additive: MasonryAdditiveShear | None = None


class MasonrySteelStep(BaseModel):
    """Alpha 9 C3b: an allowable steel stress by grade: ``value`` for fy up to ``fyMax``."""

    model_config = ConfigDict(extra="forbid")

    fyMax: float | None = Field(gt=0, description="[MPa]; null: any above.")
    value: Positive = Field(description="[MPa]")


class MasonrySteelCap(_Group):
    """A steel stress fyShare × fy at most cap [MPa]."""

    fyShare: Share
    cap: Positive
    steps: list[MasonrySteelStep] | None = Field(
        default=None,
        description="Alpha 9 C3b: the stress by grade (the first step whose fyMax the bar's fy "
        "does not exceed); none: fyShare × fy at most cap.",
    )


class MasonryAllowableSteel(_Group):
    tensionDeformed: MasonrySteelCap
    tensionPlain: MasonrySteelCap
    compressionWalls: MasonrySteelCap
    compressionFlexural: MasonrySteelCap


class MasonryAllowable(_Group):
    axial: MasonryAllowableAxial
    flexuralCompression: MasonryShareCap
    flexuralTension: MasonryFlexuralTension
    bond: dict[Literal["plain", "deformed"], Positive]
    beamShear: MasonryBeamShear
    wallShearPlain: MasonryPlainWallShear
    wallShearReinforced: MasonryReinforcedWallShear
    steel: MasonryAllowableSteel
    interaction: Positive = Field(description="fa/Fa + fb/Fb at most this.")


class MasonryElastic(_Group):
    emRatio: Positive = Field(description="Em = emRatio × f'm.")
    emRatioByUnit: dict[MasonryUnitKind, Positive] | None = Field(
        default=None, description="Alpha 9 C3b: emRatio by the units (clay, concrete)."
    )
    emCap: Positive = Field(description="Em at most this [MPa].")
    es: Positive = Field(description="Es [MPa].")
    shearRatio: Positive = Field(description="G = shearRatio × Em.")


class MasonryStiffening(BaseModel):
    """Stiffening coefficient k by pilaster spacing / width (rows) and pilaster / wall
    thickness (columns), linear between."""

    model_config = ConfigDict(extra="forbid")

    spacingRatios: list[Positive] = Field(min_length=2)
    thicknessRatios: list[Positive] = Field(min_length=2)
    k: list[list[Positive]]

    @model_validator(mode="after")
    def _shape(self) -> MasonryStiffening:
        if len(self.k) != len(self.spacingRatios) or any(
            len(row) != len(self.thicknessRatios) for row in self.k
        ):
            raise ValueError("one k per spacing ratio and thickness ratio")
        return self


class MasonryStiffeningWall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    wall: float | None = Field(gt=0, description="Wall thickness up to [mm]; null: any above.")
    storeyHeight: Positive = Field(description="Largest storey height [mm].")
    thickness: Positive = Field(description="Least stiffening wall, 1 to 3 storeys [mm].")
    thicknessUpper: float | None = Field(
        gt=0, description="Least stiffening wall, 4 and 5 storeys [mm]; null: not allowed."
    )
    spacing: Positive = Field(description="Largest spacing of the stiffening walls [mm].")


class MasonryStability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lateralShare: Share = Field(description="Lateral load at a support, × the vertical load.")
    maxStoreys: int = Field(gt=0)
    heightWidth: Positive
    openingWallShare: Share
    lengthNeedingAnalysis: Positive = Field(description="Longer walls need analysis [mm].")
    stiffeningWalls: list[MasonryStiffeningWall]
    upperStoreys: int = Field(gt=0, description="From this many storeys: thicknessUpper.")


class MasonryBasementRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thickness: Positive
    light: Positive = Field(description="Largest ground height, light wall loading [mm].")
    heavy: Positive = Field(description="Largest ground height, heavy wall loading [mm].")


class MasonryBasement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unitStrength: Positive
    leanestMortar: str
    clearHeight: Positive
    traffic: Positive = Field(description="Largest traffic load [kN/m²].")
    loadLimit: Positive = Field(description="Permanent wall load between the columns [kN/m].")
    rows: list[MasonryBasementRow] = Field(min_length=1)


class MasonryFreeStandingRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pressure: Positive = Field(description="Design wind pressure up to [N/m²].")
    ratio: Positive = Field(description="Largest height / thickness.")


class MasonryFreeStanding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zones: list[int]
    leanestMortar: str
    belowGround: Positive
    rows: list[MasonryFreeStandingRow] = Field(min_length=1)


class MasonryDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effectiveHeight: dict[str, Any]
    effectiveLength: dict[str, Positive]
    stiffening: MasonryStiffening
    slenderness: dict[Literal["wall", "column"], Positive]
    heightThicknessAnalysis: Positive
    flangeWidth: Positive
    reinforcedWidth: dict[Literal["running", "stack"], Positive]
    beamLateralSupport: Positive
    bedJoint: dict[Literal["min", "max"], Positive]
    supportDeflection: Positive
    lintelBearing: Positive
    lateralSupport: dict[str, Positive]
    stability: MasonryStability
    basement: MasonryBasement
    freeStanding: MasonryFreeStanding
    minimumThickness: dict[Literal["bearing", "oneStorey", "oneStoreyHeight", "gable"], Positive]
    parapet: dict[Literal["thickness", "heightThickness"], Positive]
    loadDispersion: Positive
    concentratedLoadThickness: Positive
    corbelSlope: Positive
    archThrust: Share = Field(description="Line of thrust within this share of the section.")


class MasonryBend(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    start: Positive = Field(alias="from", description="Bar diameter from [mm].")
    to: Positive
    diameters: Positive


class MasonryReinforcement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plainBarMax: Positive
    shearSpacing: dict[str, Positive]
    column: dict[str, Positive]
    maxBarDia: Positive
    cellArea: dict[Literal["noSplice", "splice"], Share]
    clearSpacing: dict[str, Positive]
    groutClearance: dict[Literal["fine", "coarse"], Positive]
    cover: dict[Literal["interior", "weather", "soil"], Positive]
    development: dict[Literal["tension", "compression", "plainFactor"], Positive]
    extension: dict[str, Positive]
    spliceIncrease: dict[str, Positive]
    hooks: dict[str, Positive]
    bends: list[MasonryBend] = Field(min_length=1)
    bendStirrups: dict[str, Positive]
    laps: dict[str, Positive]


class MasonryRupture(_Group):
    factor: Positive
    cap: Positive


class MasonryStrength(BaseModel):
    """Values of the strength design of slender walls and shear walls (the strength checks)."""

    model_config = ConfigDict(extra="forbid")

    phi: dict[str, Positive]
    ultimateStrain: Positive
    stressBlock: dict[Literal["stress", "depth"], Share]
    axial: dict[Literal["masonry", "reduction"], Share]
    fmRange: dict[str, Any]
    modulusOfRupture: dict[MasonryUnits, dict[Literal["full", "partial"], MasonryRupture | None]]
    shear: dict[str, Any]
    slenderWall: dict[str, Positive]
    shearWall: dict[str, Positive]
    boundary: dict[str, Positive]


class MasonrySeismic(BaseModel):
    """Values of the earthquake provisions (the seismic detailing checks)."""

    model_config = ConfigDict(extra="forbid")

    zones: list[int]
    unitStrengthMin: Positive
    leanestMortar: str
    zone23: dict[str, Positive]
    zone4: dict[str, Positive]
    # B34: the openings, the strengthening arrangements, the bands and the corner bars.
    openings: MasonryOpenings | None = None
    strengthening: list[MasonryStrengthening] = Field(default_factory=list)
    bands: MasonryBands | None = None
    cornerBars: MasonryCornerBars | None = None


# ── B34: masonry part 2 (seismic detailing, high wind, anchor bolts, confined masonry) ──


class MasonryOpenings(BaseModel):
    """Openings in bearing walls in the seismic zones: the total width at most ``maxShare`` of
    the wall between cross walls, the clear distance to a corner and between openings as shares
    of the opening height by zone group, the vertical distance between openings."""

    model_config = ConfigDict(extra="forbid")

    maxShare: Share
    cornerShare: dict[str, Positive] = Field(description="Zone group ('zone23', 'zone4') -> share.")
    betweenShare: dict[str, Positive] = Field(description="Zone group -> share.")
    verticalGap: Positive = Field(description="[mm]")
    note: str = ""


class MasonryStrengthening(BaseModel):
    """One row of the strengthening arrangements: the zones, the most storeys and the
    arrangements (``mortar``, ``bands``, ``cornerBars``, ``jambBars``, ``roofBracing``)."""

    model_config = ConfigDict(extra="forbid")

    zones: list[int] = Field(min_length=1)
    storeysMax: int = Field(gt=0)
    items: list[Literal["mortar", "bands", "cornerBars", "jambBars", "roofBracing"]]
    note: str = ""


class MasonryBandRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zones: list[int] = Field(min_length=1)
    plain: tuple[int, Positive] = Field(description="(bars, diameter [mm]) of plain mild steel.")
    deformed: tuple[int, Positive] = Field(description="(bars, diameter [mm]) of deformed bars.")
    link: tuple[Positive, Positive] = Field(description="(diameter, spacing) of the links [mm].")


class MasonryBands(BaseModel):
    """Lintel and roof bands: least concrete strength and depth, the bars by zone."""

    model_config = ConfigDict(extra="forbid")

    concreteMin: Positive = Field(description="Least f'c of an RC band [MPa].")
    depthMin: Positive = Field(description="[mm]")
    rows: list[MasonryBandRow] = Field(min_length=1)


class MasonryCornerRow(BaseModel):
    """Vertical bars at corners and junctions of a building of ``storeys`` storeys, from the
    top storey down (null: none), by bar kind and zone group."""

    model_config = ConfigDict(extra="forbid")

    storeys: int = Field(gt=0)
    plain: dict[str, list[Positive | None]]
    deformed: dict[str, list[Positive | None]]


class MasonryCornerBars(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thickWall: Positive = Field(
        description="Walls up to this thickness [mm] take the table's bars; thicker walls an "
        "area increased in proportion."
    )
    rows: list[MasonryCornerRow] = Field(min_length=1)


class MasonryHighWind(BaseModel):
    """Masonry in regions where the basic wind speed exceeds ``speed``."""

    model_config = ConfigDict(extra="forbid")

    speed: Positive = Field(description="Basic wind speed above which the rules apply [km/h].")
    unitStrengthMin: Positive = Field(description="Burnt clay units [MPa].")
    groutStrengthMin: Positive = Field(description="[MPa]")
    mortars: list[str] = Field(min_length=1, description="Mortar grades allowed.")
    footingThickness: Positive = Field(description="[mm]")
    footingDepth: Positive = Field(description="Below the undisturbed ground [mm].")
    minThickness: dict[
        Literal["unreinforcedGrouted", "reinforcedBearing", "unreinforced", "interiorNonbearing"],
        Positive,
    ] = Field(description="Least wall thickness by wall type [mm].")
    maxUnsupportedHeight: Positive = Field(description="[mm]")
    gableHeight: Positive = Field(description="At the peak [mm].")
    lintelSpan: Positive = Field(description="[mm]")
    lintelExtension: Positive = Field(description="[mm]")
    exteriorWallShare: Share = Field(description="Of each side's parallel dimension.")
    solidElementMin: Positive = Field(description="Least width of a required element [mm].")
    crossWallLength: Positive = Field(description="[mm]")
    crossWallSpacing: Positive = Field(description="[mm]")


class MasonryAnchorTable(BaseModel):
    """Allowable loads [kN] by f'm (rows) and a second argument (columns)."""

    model_config = ConfigDict(extra="forbid")

    fm: list[Positive] = Field(min_length=1)
    columns: list[Positive] = Field(min_length=1)
    values: list[list[Positive]] = Field(min_length=1)

    @model_validator(mode="after")
    def _shape(self) -> MasonryAnchorTable:
        rows = len(self.values) != len(self.fm)
        if rows or any(len(r) != len(self.columns) for r in self.values):
            raise ValueError("one row per f'm and one value per column")
        return self


class MasonryAnchorBolts(BaseModel):
    """Embedded anchor bolts in masonry (allowable loads): Bv = shear.factor (f'm Ab)^exponent
    [N] or shear.steelShare Ab fy, reduced to zero at ``edgeZero`` when the edge distance is
    below edgeDiameters db and to spacingShare at spacingMin db when closer than
    spacingDiameters db; Bt = tension.factor Ap √f'm or tension.steelShare Ab fy with Ap = π
    min(lb, lbe)²; the tables' values where they apply; combined bt/Bt + bv/Bv ≤ interaction."""

    model_config = ConfigDict(extra="forbid")

    shear: dict[
        Literal[
            "factor",
            "exponent",
            "steelShare",
            "edgeDiameters",
            "edgeZero",
            "spacingDiameters",
            "spacingMin",
            "spacingShare",
        ],
        Positive,
    ]
    tension: dict[Literal["factor", "steelShare", "overlapShare"], Positive]
    interaction: Positive
    edgeMin: Positive = Field(description="[mm]")
    embedDiameters: Positive
    embedMin: Positive = Field(description="[mm]")
    spacingDiameters: Positive
    groutMin: Positive = Field(description="Grout around the bolt [mm].")
    shearTable: MasonryAnchorTable | None = Field(default=None, description="Columns: bolt dia.")
    tensionTable: MasonryAnchorTable | None = Field(
        default=None, description="Columns: embedment or edge distance [mm]."
    )
    steelTension: MasonryAnchorTable | None = Field(
        default=None, description="One row (fm ignored); columns: bolt dia."
    )
    note: str = ""


class MasonryConfinedZone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zones: list[int] = Field(min_length=1)
    density: Share = Field(description="Least wall density in each direction.")
    storeys: int = Field(gt=0, description="Most storeys.")


class MasonryConfined(BaseModel):
    """Confined masonry (``method`` names the engine method): the wall density and storeys by
    zone, the layout, the placement and least sizes of the confining elements, the walls, and
    the allowable shear stress of their concrete."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["confinedPanels"]
    zones: list[MasonryConfinedZone] = Field(min_length=1)
    wallsPerDirection: int = Field(gt=0)
    aspectMax: Positive = Field(description="Building length / width.")
    tieColumns: dict[Literal["openingArea", "maxSpacing", "intersection"], Positive]
    tieBeams: dict[Literal["maxSpacing"], Positive]
    element: dict[
        Literal[
            "areaMin",
            "dimensionMin",
            "steelAreaMin",
            "steelRatioMin",
            "tieDiaMin",
            "tieSpacingMax",
            "endTieSpacing",
            "hookLength",
            "lapDiameters",
            "lapMin",
            "lintelOpening",
        ],
        Positive,
    ]
    wall: dict[Literal["thicknessMin", "heightThicknessMax"], Positive]
    concreteShear: Positive = Field(description="Allowable vc = this × √f'c [MPa].")
    note: str = ""


class MasonryPrisms(BaseModel):
    """f'm (MPa) from the unit's strength (MPa), one unit strength per entry of ``fm``."""

    model_config = ConfigDict(extra="forbid")

    fm: list[Positive] = Field(min_length=2)
    units: list[Positive] = Field(description="Unit strength giving each f'm.")

    @model_validator(mode="after")
    def _same_length(self) -> MasonryPrisms:
        if len(self.units) != len(self.fm):
            raise ValueError("one unit strength per f'm")
        for row in (self.fm, self.units):
            if any(row[k + 1] <= row[k] for k in range(len(row) - 1)):
                raise ValueError("the values must increase")
        return self


class MasonryPrismEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(description="What the estimate is (shown with the f'm it gives).")
    grades: list[str] = Field(description="Mortar grades the estimate may be used with.")
    clay: MasonryPrisms
    concrete: MasonryPrisms


class MasonryBasicStress(_Group):
    """C9: unreinforced masonry by permissible stresses from a basic compressive stress (method
    ``basicStress``, :mod:`saengine.design.masonry_basic_stress`): fc = fb ks ka kp with fb by
    the unit strength and the mortar (``mortars``: IS grade -> (sand parts per cement part, fb
    by ``unitStrengths``), the mix of the wall's mortar picks the row), ks by the slenderness
    ratio and the eccentricity ratio (``reduction``: a row per ``eccentricities`` e/t, a column
    per ``slenderness``; null: not permitted), ka = areaBase + areaSlope A below areaBelow m²,
    kp the units' shape factor."""

    method: Literal["basicStress"] = "basicStress"
    unitStrengths: list[Positive] = Field(min_length=2, description="[MPa]")
    mortars: dict[str, tuple[Positive, list[Positive]]] = Field(
        description="Grade -> (sand parts per cement part, fb [MPa] by unitStrengths)."
    )
    slenderness: list[Positive] = Field(min_length=2)
    eccentricities: list[float] = Field(min_length=2, description="e/t of the rows.")
    reduction: list[list[float | None]] = Field(description="ks; null: not permitted.")
    areaBelow: Positive = Field(description="[m²]")
    areaBase: Positive
    areaSlope: Positive
    shapeFactor: Positive = Field(description="kp of the units.")
    effectiveHeight: Positive = Field(description="× the clear height, supported top and bottom.")
    slendernessMax: Positive = Field(description="SR of walls at most.")
    eccentricityIncrease: tuple[float, Positive] = Field(
        description="(e/t above, factor): the face stress at most factor × fc."
    )
    tension: tuple[Positive, Positive] = Field(
        description="Flexural tension [MPa]: normal to the bed joints, parallel to them."
    )
    tensionMix: Positive = Field(description="Tension only with mortars of at most this sand.")
    shear: tuple[Positive, Positive, Positive] = Field(
        description="fs = a + fd / b, at most c [MPa]."
    )
    lateralIncrease: float = Field(ge=1, description="× with wind or earthquake.")


class MasonryTable(TableModel):
    """Masonry walls: the design method (by id), the mortar grades, the allowable stresses,
    the dimension rules, the reinforcement details and the values of the strength design and
    the earthquake provisions."""

    method: Literal["allowableStress", "strength", "basicStress"] = Field(
        description="The masonry design method: 'allowableStress' (working stress, linear "
        "stress-strain), 'strength' (strength design of reinforced walls) or 'basicStress' "
        "(C9: permissible stresses from a basic compressive stress, group basicStress)."
    )
    mortars: dict[str, MasonryMortar] = Field(min_length=1, description="Mortar grades by id.")
    quality: MasonryQuality
    lateralIncrease: MasonryLateralIncrease
    allowable: MasonryAllowable
    elastic: MasonryElastic
    dimensions: MasonryDimensions
    reinforcement: MasonryReinforcement
    strength: MasonryStrength
    seismic: MasonrySeismic
    mortarFromMix: Literal["grades"] = Field(
        description="'grades': a mix gets the richest grade whose sand parts are at least its."
    )
    prismEstimate: MasonryPrismEstimate | None = None
    clauses: dict[str, str] = Field(description="Clause reference of each check, by key.")
    # B34: the methods a wall type may choose instead of ``method``; high wind; anchor bolts;
    # confined masonry. A pack without one does not cover it.
    alternatives: list[Literal["allowableStress", "strength", "basicStress"]] = Field(
        default_factory=list,
        description="Methods a wall type may choose in lieu of 'method' (none: only 'method').",
    )
    highWind: MasonryHighWind | None = None
    anchorBolts: MasonryAnchorBolts | None = None
    confined: MasonryConfined | None = None
    basicStress: MasonryBasicStress | None = None  # C9

    @model_validator(mode="after")
    def _known_mortars(self) -> MasonryTable:
        known = set(self.mortars)
        used = [
            *self.allowable.flexuralTension.fullMortars,
            *self.allowable.flexuralTension.reducedMortars,
            *self.allowable.wallShearPlain.concrete,
            *(self.prismEstimate.grades if self.prismEstimate else []),
            self.dimensions.basement.leanestMortar,
            self.dimensions.freeStanding.leanestMortar,
            self.seismic.leanestMortar,
            *(self.highWind.mortars if self.highWind else []),
        ]
        unknown = sorted(set(used) - known)
        if unknown:
            raise ValueError(f"unknown mortar grades {unknown}")
        return self


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


# B23: the building code's own site rules (the default pack's Part 3 Ch 1 for the bnbc2020 pack), beside
# the planning authority's: the plinth and formation levels, overhead lines, the open area, the
# fallback setbacks, the height by road width and construction type and the parking floors left
# out of FAR. Read by saengine.gis.planning.


class OverheadLineClass(_Row):
    id: str = Field(min_length=1)
    label: str
    vertical: float = Field(ge=0, description="Least vertical distance to the line [m].")
    horizontal: float = Field(ge=0, description="Least horizontal distance to the line [m].")
    upToKv: float | None = Field(
        default=None, gt=0, description="The distances hold up to this voltage [kV]."
    )
    stepKv: float | None = Field(
        default=None, gt=0, description="Above upToKv: the distances grow per step or part [kV]."
    )
    stepVertical: float = Field(default=0, ge=0, description="Added per step [m].")
    stepHorizontal: float = Field(default=0, ge=0, description="Added per step [m].")


class OverheadLines(_Row):
    classes: list[OverheadLineClass] = Field(min_length=1)
    rule: str = ""


class SiteLevels(_Row):
    plinthMin: float = Field(
        ge=0, description="Least plinth level above the road's centre-line surface [m]."
    )
    formationMax: float | None = Field(
        default=None,
        ge=0,
        description="Largest formation level above the road's centre line where the area is not "
        "flood prone [m]; the formation level is never below the road.",
    )
    plinthRule: str = ""
    formationRule: str = ""


class OpenArea(_Row):
    minPercent: float = Field(ge=0, le=100, description="Least total open area [% of the plot].")
    byOccupancy: dict[str, float] = Field(
        default_factory=dict, description="Occupancy group -> least open area [%]."
    )
    unpavedPercent: float = Field(
        default=0, ge=0, le=100, description="Of the minimum open space left unpaved [%]."
    )
    rule: str = ""
    unpavedRule: str = ""


class CodeFront(_Row):
    fromCentre: float = Field(ge=0, description="Least distance from the street's centre [m].")
    fromBoundary: float = Field(ge=0, description="Least distance from the property line [m].")
    rule: str = ""


class CodeSetbackRow(_Row):
    occupancies: list[str] = Field(min_length=1)
    label: str
    typology: Literal["detached", "semiDetached", "row"] | None = Field(
        default=None, description="null: any typology."
    )
    tall: bool | None = Field(
        default=None, description="True: above tallHeight or tallStoreys; null: any height."
    )
    heightMax: float | None = Field(default=None, gt=0, description="Row up to this height [m].")
    storeysMax: int | None = Field(default=None, gt=0, description="Row up to these storeys.")
    areaMin: float = Field(default=0, ge=0, description="Plot area from [m²] (inclusive).")
    areaMax: float | None = Field(default=None, gt=0, description="Plot area up to [m²].")
    rear: float | None = Field(ge=0, description="Rear distance [m]; null: by other provisions.")
    side: list[float | None] | None = Field(
        description="Side distances [m] (two for a semi-detached development: null is the "
        "pounding gap, PG); [] nil; null: by other provisions."
    )
    note: str = ""


class CodeSetbacks(_Row):
    rows: list[CodeSetbackRow] = Field(min_length=1)
    tallHeight: float = Field(gt=0)
    tallStoreys: int = Field(gt=0)
    poundingGap: str = Field(
        default="", description="The clause of the pounding gap (the seismic separation)."
    )
    rule: str = ""


class HeightColumn(_Row):
    id: str = Field(min_length=1)
    label: str
    types: list[str] = Field(min_length=1, description="Construction types (fireResistance ids).")
    storeys: list[int] = Field(
        min_length=1, description="Per band; one value: the same for every band."
    )
    heights: list[float] = Field(min_length=1, description="Per band [m].")
    stepStoreys: int = Field(default=0, ge=0, description="Added per step above the last band.")
    stepHeight: float = Field(default=0, ge=0, description="Added per step above [m].")

    @model_validator(mode="after")
    def _same_length(self) -> HeightColumn:
        if len(self.storeys) != len(self.heights):
            raise ValueError("storeys and heights need the same length")
        return self


class PlanningHeight(_Row):
    basis: float = Field(
        default=2.0, gt=0, description="The limit's basis is basis × (road + front open space)."
    )
    bands: list[float] = Field(min_length=1, description="Upper bounds of the bands [m].")
    step: float = Field(gt=0, description="Band width above the last band [m].")
    columns: list[HeightColumn] = Field(min_length=1)
    rule: str = ""


class UnlimitedRow(_Row):
    occupancies: list[str] = Field(min_length=1)
    front: float = Field(ge=0)
    rear: float = Field(ge=0)
    side: float = Field(ge=0)


class UnlimitedHeight(_Row):
    minRoad: float = Field(gt=0, description="Least front road width [m].")
    occupancies: list[str] = Field(description="Uses that may be of unlimited height.")
    types: list[str] = Field(description="Construction types that may be of unlimited height.")
    rows: list[UnlimitedRow] = Field(description="Least open spaces of an unlimited building.")
    rule: str = ""
    openSpaceRule: str = ""


class ParkingFloors(_Row):
    parkingShare: float = Field(
        gt=0, le=1, description="Share of a floor used for parking to leave it out of FAR."
    )
    rule: str = ""


class PlanningCode(_Row):
    """The building code's own site rules beside the planning authority's."""

    name: str = Field(description="How the rules are named in results, e.g. 'BNBC 2020 Part 3'.")
    occupancies: dict[str, str] = Field(
        description="Use id of the authority's table -> occupancy group of the code."
    )
    withAuthority: list[str] = Field(
        default_factory=list,
        description="Checks that bind also where the authority's rules are used (the others "
        "are shown as advisory): plinth, formation, overheadLines, unpaved, openArea, "
        "setbacks, height, unlimited.",
    )
    levels: SiteLevels | None = None
    overheadLines: OverheadLines | None = None
    openArea: OpenArea | None = None
    front: CodeFront | None = None
    setbacks: CodeSetbacks | None = None
    height: PlanningHeight | None = None
    unlimited: UnlimitedHeight | None = None
    parking: ParkingFloors | None = None


class PlanningTable(TableModel):
    """Planning rules of the plot: FAR and maximum ground coverage by use, plot size and road
    width, and the setbacks (the planning authority's rules the default pack's Part 3 defers to)."""

    clauses: dict[str, str] = Field(
        default_factory=dict,
        description="Clauses of the authority's rules named in results: coverage, far, envelope.",
    )
    buildingCode: PlanningCode | None = Field(
        default=None,
        description="The building code's own site rules (levels, overhead lines, open area, "
        "fallback setbacks, height, parking floors); null: none.",
    )

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


# ─────────────────────────── site investigation and soil chemistry ───────────────────────────


class _Band(BaseModel):
    """One band of a value: the first band whose bound the value meets is taken (a band with
    no bound takes everything left). ``above``/``atLeast`` bound from below, ``below``/
    ``atMost`` from above."""

    model_config = ConfigDict(extra="forbid")

    above: float | None = None
    atLeast: float | None = None
    below: float | None = None
    atMost: float | None = None

    def holds(self, value: float) -> bool:
        return not (
            (self.above is not None and not value > self.above)
            or (self.atLeast is not None and not value >= self.atLeast)
            or (self.below is not None and not value < self.below)
            or (self.atMost is not None and not value <= self.atMost)
        )


class ScoreBand(_Band):
    score: float


class DegreeBand(_Band):
    degree: str


class RatingBand(_Band):
    rating: str


class _Clause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause: str = Field(default="", description="The clause (and page) the values come from.")
    note: str = Field(default="", description="How the values are read, for the report.")
    sources: dict[str, str] = Field(default_factory=dict)


class Borings(_Clause):
    method: Literal["countAndSpacing"] = Field(
        description="How the number, pattern and spacing of the borings are checked."
    )
    minimum: dict[str, int] = Field(description="Least number of borings by building size.")
    notInOneLine: bool = Field(default=True, description="The borings must not be in one line.")
    spacing: dict[str, dict[str, float]] = Field(
        description="Largest spacing [m] by building size and horizontal stratification."
    )
    insideFootprint: float | None = Field(
        default=None, ge=0, le=1, description="Least share of the borings under the building."
    )


class ExplorationDepth(_Clause):
    method: Literal["footingWidths"] = Field(
        description="Depth below a spread footing in footing widths by L/B; piles below the tip."
    )
    spread: list[tuple[float, float]] = Field(
        min_length=1, description="(L/B, depth below the bearing level in footing widths)."
    )
    minimum: float = Field(ge=0, description="Least depth of any boring [m].")
    buildingWidthFactor: float | None = Field(
        default=None, description="Depth below the foundation in building widths."
    )
    buildingShare: float = Field(
        default=0.5, ge=0, le=1, description="Share of the borings that go that deep."
    )
    belowPileTip: float | None = Field(default=None, description="Below the pile tip [m].")
    pileGroupWidths: float | None = Field(
        default=None, description="Below the pile tip in largest group dimensions."
    )
    rockCore: float | None = Field(default=None, description="Rock core of piles on rock [m].")
    shaftRockCoreDiameters: float | None = Field(
        default=None, description="Rock core of an isolated shaft in diameters."
    )
    shaftGroupRockCoreWidths: float | None = Field(
        default=None, description="Rock core of a shaft group in group dimensions."
    )
    bedrockCore: float | None = Field(
        default=None, description="Core into bedrock of the boring taken to bedrock [m]."
    )


class OrganicClass(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    min: float = Field(ge=0, description="Least organic content of the class [%].")
    label: str = ""


class Organic(_Clause):
    ovenDriedRatio: float = Field(
        description="LL oven-dried / LL not dried below which a fine soil is organic."
    )
    peat: float = Field(description="Organic content from which the soil is peat [%].")
    classes: list[OrganicClass] = Field(min_length=1)


class ExpansiveCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    parameter: str = Field(description="The sample value the criterion reads.")
    unit: str = ""
    source: str = ""
    rows: list[DegreeBand] = Field(min_length=1)


class Expansive(_Clause):
    criteria: list[ExpansiveCriterion]
    degrees: list[str] = Field(description="The degrees of expansion, least first.")
    flagFrom: str = Field(description="The degree from which the soil is flagged expansive.")


class Collapsible(_Clause):
    criticalVoidRatio: dict[str, float] = Field(
        description="ec = a eL + b eP: {'liquidLimit': a, 'plasticLimit': b}."
    )
    saturationMax: float
    voidIndexMax: float
    relativeSubsidence: float


class Dispersive(_Clause):
    pinhole: dict[str, str] = Field(description="Pinhole class -> dispersive, intermediate, ...")
    pHScreen: float
    espDispersive: float
    espPlusEmgDispersive: float
    espModerate: tuple[float, float]
    espSerious: float


class SoftClayRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consistency: str
    nBelow: float
    cuBelow: float


class SoftClay(_Clause):
    rows: list[SoftClayRow]
    nAtMost: float = Field(description="Field N at or below which a clay is soft.")
    cuRange: tuple[float, float] = Field(description="cu range of soft clays [kPa].")


class Corrosivity(_Clause):
    scores: dict[str, dict[str, float] | list[ScoreBand]] = Field(
        description="Score of each parameter: by category, or by bands of its value."
    )
    units: dict[str, str] = Field(default_factory=dict)
    ratings: list[RatingBand] = Field(min_length=1, description="Rating by the total score.")
    compositionFromUscs: dict[str, str] = Field(default_factory=dict)
    compositionFromSoilType: dict[str, str] = Field(default_factory=dict)


class CorrosiveSite(_Clause):
    chloride: float = Field(description="Chloride from which the site is corrosive [ppm].")
    sulphate: float = Field(description="Sulphate from which the site is corrosive [ppm].")
    pHBelow: float
    steelPile: dict[str, float] = Field(default_factory=dict)


class SulphateClass(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    soilMin: float = Field(ge=0, description="Water-soluble SO4 in soil [% by weight].")
    waterMin: float = Field(ge=0, description="SO4 in water [ppm].")
    exclusive: bool = Field(default=False, description="The lower bounds are exclusive.")
    cement: str | None = None
    maxWaterCement: float | None = None
    noCalciumChloride: bool = False


class Sulphate(_Clause):
    classes: list[SulphateClass] = Field(min_length=1, description="Least severe first.")
    seaWater: str | None = Field(default=None, description="The class of sea water.")


class ChlorideExposure(_Clause):
    maxWaterCement: float
    maxWaterCementExtraCover: float | None = None
    extraCover: float | None = Field(default=None, description="[mm]")
    lowPermeabilityWaterCement: float | None = None


class GeoHazards(_Clause):
    items: list[str]


class Liquefaction(_Clause):
    """The code's own liquefaction procedure (the soil report's ``codePack`` method) and its
    screening rule of thumb (applied with every method)."""

    method: Literal["linearRdYoud"] = Field(
        description="Engine method: ``linearRdYoud``: CSR = csrFactor (amax/g) rd σv/σ'v with "
        "rd = 1 - rdSlope z, CRR of Youd et al. (2001) from the SPT, FL = CRR/CSR."
    )
    rdSlope: Positive = Field(description="rd = 1 - rdSlope z, z in m.")
    csrFactor: Positive = Field(description="CSR = csrFactor (amax/g) rd σv/σ'v.")
    fieldNLimit: Positive | None = Field(
        default=None,
        description="Soil with a field N above this does not liquefy (rule of thumb); empty: "
        "the code gives none.",
    )


class ClassBand(_Band):
    siteClass: str


class SoftSiteRule(BaseModel):
    """A soft-clay site class (S1 of the default pack) the SPT can only flag."""

    model_config = ConfigDict(extra="forbid")

    siteClass: str
    suRange: tuple[float, float] = Field(description="su [kPa] of the soft clays.")
    thickness: Positive = Field(description="Least thickness of the layer [m].")
    pi: Positive = Field(description="PI above which a clay counts.")


class SiteClassification(_Clause):
    """The site class of a borehole from the SPT and su over the top of the profile."""

    method: Literal["harmonicMeans"] = Field(
        description="Engine method: harmonic means of N (field) and su over ``depth``, the "
        "softer class of the two."
    )
    table: str = Field(default="", description="The table's short name used in the notes.")
    depth: Positive = Field(description="Depth classified [m].")
    nMax: Positive = Field(description="N counted at most this.")
    suMax: Positive = Field(description="su counted at most this [kPa].")
    order: list[str] = Field(min_length=1, description="The classes, stiffest first.")
    byN: list[ClassBand] = Field(min_length=1)
    bySu: list[ClassBand] = Field(min_length=1)
    rockClass: str = Field(description="The class of rock near the surface without a Vs.")
    rockShallow: Positive = Field(description="Rock within this depth [m] gives rockClass.")
    rockDeep: Positive = Field(description="Rock-like material up to this depth [m] flags ...")
    rockDeepClass: str = Field(description="... this class (it needs the Vs).")
    rockVs: Positive = Field(description="Vs [m/s] of rock (the stiffest class).")
    soft: SoftSiteRule | None = None
    liquefiableClass: str | None = Field(
        default=None, description="The class of a site with liquefiable soil (S2)."
    )
    liquefiableAssumed: str | None = Field(
        default=None, description="The class used meanwhile for a liquefiable site."
    )


class SiteInvestigationTable(TableModel):
    """Site investigation and soil chemistry: the number, spacing and depth of the borings, the
    identification of problem soils (organic, expansive, collapsible, dispersive, soft), the
    corrosivity of the soil for buried steel, and the concrete in the ground (sulphate classes,
    chloride exposure). The engine reads the bands; a pack without this table does not cover
    the checks."""

    borings: Borings
    depth: ExplorationDepth
    organic: Organic | None = None
    expansive: Expansive | None = None
    collapsible: Collapsible | None = None
    dispersive: Dispersive | None = None
    softClay: SoftClay | None = None
    corrosivity: Corrosivity | None = None
    steelCorrosion: dict[str, float | str] = Field(
        default_factory=dict, description="Steel corrosion rates [mm/side/year] by exposure."
    )
    corrosiveSite: CorrosiveSite | None = None
    sulphate: Sulphate | None = None
    chloride: ChlorideExposure | None = None
    geoHazards: GeoHazards | None = None
    # D3: the code's liquefaction procedure and its site classification by the SPT.
    liquefaction: Liquefaction | None = None
    siteClassification: SiteClassification | None = None


# ─────────────────────────────────────── serviceability ───────────────────────────────────────


class NonSeismicDrift(_Row):
    """Storey drift limit under the loads other than earthquake, as Δ / storey height: one
    ratio below the period split, another at or above it, and one for unreinforced masonry."""

    combination: str = Field(description="Id of the service combination the drift is taken under.")
    periodSplit: Positive = Field(
        description="Period [s] (the one the base shear uses) splitting short and long."
    )
    shortPeriod: Share = Field(description="Δ / h for a period below the split.")
    longPeriod: Share = Field(description="Δ / h for a period at or above the split.")
    unreinforcedMasonry: Share = Field(description="Δ / h of unreinforced masonry structures.")
    unreinforcedMasonrySystems: list[str] = Field(
        default_factory=list,
        description="Seismic system ids (the seismic table's) that are unreinforced masonry.",
    )


class WindSway(_Row):
    """Overall sway at the top under the service wind combination, as a share of the height."""

    combination: str = Field(description="Id of the service combination the sway is taken under.")
    ratio: Share = Field(description="Top deflection / height above the base.")


class MemberDeflectionUse(_Row):
    """Span divisors of one kind of member: deflection <= span / divisor under the live load,
    the wind load and the dead plus live load (empty: no limit of that kind)."""

    label: str = Field(description="What the member is, for the report.")
    live: Positive | None = Field(default=None, description="Live load: span / this.")
    wind: Positive | None = Field(default=None, description="Wind load: span / this.")
    deadLive: Positive | None = Field(default=None, description="Dead + live load: span / this.")


class MemberDeflection(_Row):
    """Deflection limits of members by use (steel and other members without their own)."""

    uses: dict[str, MemberDeflectionUse] = Field(description="Use id -> span divisors.")
    default: str = Field(description="Use id of a member whose use is not set.")
    cantileverSpan: Positive = Field(
        default=2.0, description="Span of a cantilever as a multiple of its length."
    )
    combination: str = Field(
        description="Id of the service combination of the dead + live load limit."
    )


class OverturningStability(_Row):
    """Overturning of the building as a whole: the dead load's resisting moment about the
    edge of the supports over the overturning moment of each lateral case."""

    factorOfSafety: float = Field(ge=1, description="Least resisting / overturning moment.")
    resisting: list[str] = Field(
        default_factory=lambda: ["D"], description="Load case kinds that resist (dead only)."
    )
    lateralFactors: dict[str, float] = Field(
        default_factory=lambda: {"W": 1.0, "E": 1.0},
        description="Factor on each lateral load kind (W, E) for this check.",
    )
    note: str = Field(default="", description="How the check reads the code, for the report.")


class ServiceabilityTable(TableModel):
    """Serviceability of the building: storey drift and top sway under the service wind, member
    deflection limits by use, and the stability of the whole building against overturning."""

    storeyDrift: NonSeismicDrift | None = None
    sway: WindSway | None = None
    deflection: MemberDeflection | None = None
    overturning: OverturningStability | None = None


# ─────────────────────────────────── nonstructural components ───────────────────────────────────


class ComponentForceRule(_Row):
    """The seismic design force of a component, by a method the engine names
    (:mod:`saengine.design.nonstructural`). ``amplifiedHeight``: F = αc·a·Wc·Ic/Rc ×
    (1 + heightFactor·z/h), minFactor·a·Wc·Ic ≤ F ≤ maxFactor·a·Wc·Ic, with a = groundFactor·Z·S
    (Z the zone coefficient, S the site factor of the seismic table); vertical ± verticalFactor·a·Wc."""

    method: Literal["amplifiedHeight"] = "amplifiedHeight"
    groundFactor: Positive = Field(description="a = this × Z × S [g].")
    heightFactor: float = Field(ge=0, description="Of z/h in (1 + this·z/h).")
    minFactor: float = Field(ge=0, description="Least F over a·Wc·Ic.")
    maxFactor: Positive = Field(description="Largest F over a·Wc·Ic.")
    verticalFactor: float = Field(ge=0, description="Concurrent vertical force over a·Wc.")
    zOverHMax: Positive = Field(default=1.0, description="Upper limit of z/h.")
    symbols: dict[str, str] = Field(
        default_factory=dict, description="The code's symbols (force, amplification, ...)."
    )
    equation: str = Field(default="", description="The code's equation number.")
    note: str = ""


class ComponentImportance(_Row):
    essential: Positive = Field(description="Ic of a component marked essential.")
    default: Positive = Field(description="Ic of any other component.")


class ComponentRow(_Row):
    """A row of the component coefficient tables."""

    group: str = Field(description="Key of ``groups`` (architectural, mechanical, ...).")
    heading: str = ""
    label: str
    alpha: float = Field(ge=1.0, description="Component amplification factor αc.")
    R: Positive = Field(description="Component response reduction factor Rc.")
    parapet: bool = Field(default=False, description="A parapet (for the exemptions).")
    exterior: bool = Field(default=False, description="An exterior wall or wall element.")
    distribution: bool = Field(default=False, description="A distribution system (per metre).")
    isolated: bool = Field(default=False, description="On vibration isolators (``isolation``).")


class ComponentDefaults(_Row):
    """Which row a drawn item takes when none is chosen (component ids)."""

    interiorWall: str
    parapet: str
    curtainWall: str
    structuralWall: str
    equipment: str
    equipmentKinds: dict[str, str] = Field(default_factory=dict)
    note: str = ""


class ExemptionCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    flexibleConnections: bool | None = None
    distribution: bool | None = None
    maxMountHeight: Positive | None = Field(default=None, description="[mm] above the floor.")
    maxWeight: Positive | None = Field(default=None, description="[N].")
    maxWeightPerLength: Positive | None = Field(default=None, description="[N/m].")


class ComponentExemption(ExemptionCondition):
    """Components the section does not apply to: all conditions hold, and one of the
    ``alternatives`` when there are any."""

    id: str
    label: str
    groups: list[str]
    categories: list[str] = Field(description="Seismic Design Categories.")
    importance: Positive | None = Field(default=None, description="Only with this Ic.")
    exceptParapetsOnStructuralWalls: bool = False
    alternatives: list[ExemptionCondition] = Field(default_factory=list)
    source: str | None = None


class ComponentInteraction(_Row):
    share: Positive = Field(description="Components over this share of W: interaction.")
    period: Positive = Field(description="... with periods over this [s].")


class ComponentIsolation(_Row):
    factor: Positive = Field(description="Force factor with a clearance over ``clearance``.")
    clearance: float = Field(ge=0, description="[mm].")


class ComponentConnections(_Row):
    bodyFactor: Positive = Field(description="Bodies of connections: this × F.")
    fastenerFactor: Positive = Field(description="Fasteners: this × F.")
    jointDriftFactor: Positive = Field(description="Joint movement: this × the storey drift.")
    jointMinimum: float = Field(ge=0, description="Least joint movement [mm].")


class WallAnchorage(_Row):
    minimum: Positive = Field(description="Least anchorage force [kN/m of wall].")
    maxSpacing: Positive = Field(description="Anchors farther apart: wall bending between [mm].")


class RelativeDisplacementRule(_Row):
    method: Literal["allowableDrift"] = "allowableDrift"


class NonstructuralTable(TableModel):
    """Seismic forces on nonstructural components (parapets, partitions, cladding, tanks,
    equipment, distribution systems), their relative displacements, the exterior panel
    connections and the anchorage of walls."""

    name: str = ""
    force: ComponentForceRule
    importance: ComponentImportance
    groups: dict[str, str] = Field(default_factory=dict)
    components: dict[str, ComponentRow]
    defaults: ComponentDefaults
    exemptions: list[ComponentExemption] = Field(default_factory=list)
    interaction: ComponentInteraction | None = None
    isolation: ComponentIsolation | None = None
    connections: ComponentConnections | None = None
    anchorage: WallAnchorage | None = None
    relativeDisplacement: RelativeDisplacementRule | None = None

    @model_validator(mode="after")
    def _known_rows(self) -> NonstructuralTable:
        d = self.defaults
        named = [d.interiorWall, d.parapet, d.curtainWall, d.structuralWall, d.equipment]
        for key in [*named, *d.equipmentKinds.values()]:
            if key not in self.components:
                raise ValueError(f"defaults name an unknown component '{key}'")
        return self


# ── design of steel frames for stability (fem/notional_loads.py, fem/second_order.py,
# design/steel/stability.py) ──


class StabilityAlpha(_Group):
    """α on the required axial strength Pr: 1.0 under the strength (LRFD) combinations, a
    larger factor under the allowable stress (ASD) ones."""

    lrfd: Positive = Field(description="α for design by the strength (LRFD) combinations.")
    asd: Positive = Field(description="α for design by the allowable stress (ASD) combinations.")
    source: str | None = Field(default=None, description="Clause (and page).")


class StabilityNotional(_Row):
    """Notional lateral loads Ni = coefficient × Yi of the stability design methods."""

    secondOrder: Positive = Field(
        description="Ni / Yi in the gravity-only combinations, design by second-order analysis."
    )
    firstOrderDriftFactor: Positive = Field(
        description="Design by first-order analysis: Ni = this × (Δ/L) × Yi ..."
    )
    firstOrderMinimum: Positive = Field(description="... and at least this × Yi.")


class StabilityLimits(_Row):
    """When each design method may be used (ratios of second-order to first-order drift and of
    αPr to Py)."""

    directAnalysisRequiredAbove: Positive = Field(
        description="Δ2nd / Δ1st above which the direct analysis method is required."
    )
    secondOrderUnitKMax: Positive = Field(
        description="Design by second-order analysis: K = 1 while Δ2nd / Δ1st is at most this."
    )
    firstOrderAxialMax: Share = Field(
        description="Design by first-order analysis: αPr / Py at most this (K = 1)."
    )


class DirectAnalysis(_Row):
    """The direct analysis method: a second-order analysis on reduced stiffness with notional
    loads, the members checked with K = 1."""

    method: Literal["directAnalysis"] = Field(
        default="directAnalysis", description="Method id (the engine's generic implementation)."
    )
    effectiveLengthFactor: Positive = Field(description="K of the member strengths.")
    notionalCoefficient: Positive = Field(description="Ni / Yi, in every combination.")
    additiveNotionalCoefficient: Positive = Field(
        description="Ni / Yi added when τb = 1 is used for every member."
    )
    gravityOnlyDriftRatioMax: Positive = Field(
        description="Δ2nd / Δ1st up to which Ni may be applied in the gravity-only "
        "combinations only."
    )
    flexuralStiffnessFactor: Share = Field(description="EI* = this × τb × EI.")
    axialStiffnessFactor: Share = Field(description="EA* = this × EA.")
    tauLimit: Share = Field(description="τb = 1 while αPr / Py is at most this ...")
    tauFactor: Positive = Field(description="... above it τb = this × (αPr / Py) × (1 - αPr / Py).")
    pSmallDeltaLimit: Share = Field(
        description="P-δ on the lateral displacement may be neglected while αPr < this × PeL."
    )
    asdAnalysisFactor: Positive = Field(
        description="ASD: the analysis runs under this times the combinations, results divided "
        "by it."
    )


class SteelStabilityTable(TableModel):
    """Design of steel frames for stability: the notional loads of the methods by first- and
    second-order analysis, when each method may be used, and the direct analysis method (None in
    a pack that does not cover it: the option then shows as not covered)."""

    alpha: StabilityAlpha
    notional: StabilityNotional
    limits: StabilityLimits
    directAnalysis: DirectAnalysis | None = None


# ───────────────────── flood, surge, rain, helipads and special loads (B16) ─────────────────────


class SurgeRegion(_Row):
    """A coastal region's design surge height at the sea coast and its decay inland."""

    name: str
    height50: Positive = Field(description="Surge height hT at the coast, 50-year [m].")
    height100: Positive = Field(description="Surge height hT at the coast, 100-year [m].")
    decay: Positive = Field(description="Rate of decrease k of the surge height inland [m/km].")
    note: str | None = None


class WaterLevelStation(_Row):
    """Extreme surface water level yT above the datum at a coastal location."""

    name: str
    thana: str = ""
    level50: float = Field(description="yT, 50-year [m above the datum].")
    level100: float = Field(description="yT, 100-year [m above the datum].")


class FloodHydrodynamic(BaseModel):
    """Hydrodynamic loads of moving water and wind-induced waves."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    waveShare: Positive = Field(description="Local wave amplitude hw as a share of hs.")
    minWave: Positive = Field(description="Least local wave amplitude hw [m].")
    windSpeed: dict[str, Positive] = Field(
        default_factory=dict, description="3-s gust wind speed of the waves by return period."
    )
    maxVelocity: Positive = Field(
        description="Water velocity [m/s] up to which the equivalent surcharge depth applies."
    )
    minDrag: Positive = Field(description="Least drag coefficient (shape factor) a.")
    gravity: Positive = Field(description="Acceleration due to gravity g [m/s²].")


class BreakingWave(BaseModel):
    """Breaking wave loads on piles, columns and vertical walls."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    heightRatio: Positive = Field(description="Hb / ds.")
    depthRatio: Positive = Field(description="Still water depth ds / Hm.")
    dragRound: Positive = Field(description="Drag coefficient CD of round piles and columns.")
    dragSquare: Positive = Field(description="CD of square piles and columns.")
    squareWidth: Positive = Field(description="D of a square pile as a multiple of its width.")
    dynamicPressure: dict[str, Positive] = Field(
        description="Dynamic pressure coefficient Cp by occupancy category."
    )
    staticFactor: Positive = Field(description="Static pressure γw ds × this (Eq for Pmax).")
    forceDynamic: Positive = Field(description="Ft = this × Cp γw ds² + ...")
    forceStatic: Positive = Field(description="... + this × γw ds², dry behind the wall.")
    forceStaticWet: Positive = Field(description="... + this × γw ds², water behind the wall.")


class FloodImpact(BaseModel):
    """Debris impact load F = π W Vb CI CO CD CB Rmax / (2 g Δt)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    debrisWeight: Positive = Field(description="Debris weight W [N].")
    duration: Positive = Field(description="Duration of the impact Δt [s].")
    importance: dict[str, Positive] = Field(description="CI by occupancy category.")
    orientation: Positive = Field(description="CO.")
    depth: list[tuple[float, float]] = Field(
        description="CD by water depth [m]: (depth, CD), linear between, held beyond."
    )
    blockage: list[tuple[float, float]] = Field(
        description="CB by upstream flow channel width [m]: (width, CB), linear, held beyond."
    )
    responseRatio: list[tuple[float, float]] = Field(
        description="Rmax by the ratio of the impulse duration to the natural period."
    )


class BreakawayWalls(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    minPressure: Positive = Field(description="Least design pressure on the wall [kN/m²].")
    maxCollapse: Positive = Field(
        description="Greatest collapse load [kN/m²] unless the conditions of the code are met."
    )


class RainRule(BaseModel):
    """Rain load on roofs with blocked or controlled drainage."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    controlledAllowance: float = Field(
        ge=0, description="Added above the secondary drainage level with controlled drainage."
    )
    unitWeight: Positive = Field(description="Unit weight of rainwater [kN/m³].")


class HelipadRule(BaseModel):
    """Live loads on helicopter landing areas: L1 = W1, L2 = k W2, L3 = w."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    distributed: Positive = Field(description="Distributed load w [kN/m²].")
    impact: dict[str, Positive] = Field(description="k by landing gear: hydraulic, rigid.")
    patch: Positive = Field(description="Side of the square L2 acts on [mm].")


class ExplosionRule(BaseModel):
    """Internal gas explosion in closed rooms, and the least design pressure."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ventCurve: list[tuple[float, float]] = Field(
        description="Overpressure q0 [kN/m²] by A0/v [1/m], digitised from the figure."
    )
    glassPressure: Positive = Field(description="Breaking pressure of the vent glass [kN/m²].")
    minPressure: Positive = Field(description="Least internal pressure or suction [kN/m²].")
    reliefPressure: Positive = Field(description="Relief vents open by this pressure [kN/m²].")
    rise: tuple[float, float] = Field(description="Interval of t1 [s].")
    decay: tuple[float, float] = Field(description="Interval of t2 [s].")


class ShelterRow(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    maxStoreys: int | None = Field(description="Up to this many storeys above (None: more).")
    load: Positive = Field(description="Characteristic vertical load [kN/m²].")


class ShelterRule(BaseModel):
    """Characteristic vertical loads on air raid shelters below a building."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    rows: list[ShelterRow] = Field(min_length=1)
    stable: Positive = Field(
        description="Load in buildings of particularly stable construction [kN/m²]."
    )
    liveThreshold: Positive = Field(
        description="Floors with more live load add the excess of the storeys' mean [kN/m²]."
    )


class FloodTable(TableModel):
    """Flood and surge loads (hydrostatic, hydrodynamic, waves, impact), the stability of the
    building against them, and the other miscellaneous loads: rain, helicopter landing areas,
    explosions and air raid shelters."""

    returnPeriod: dict[str, int] = Field(
        description="Return period [years] of the flood levels, surge heights and wind by "
        "occupancy category."
    )
    waterLevelReturnPeriod: dict[str, int] = Field(
        default_factory=dict,
        description="Column of the extreme surface water level table by occupancy category "
        "(empty: returnPeriod).",
    )
    waterUnitWeight: dict[str, Positive] = Field(
        description="Unit weight of water γw [kN/m³]: fresh, salt."
    )
    surgeRegions: dict[str, SurgeRegion] = Field(default_factory=dict)
    minDistance: Positive = Field(description="Distance x [km] below which x is taken as this.")
    waterLevels: dict[str, WaterLevelStation] = Field(default_factory=dict)
    freeWaterIncrease: float = Field(
        ge=0, description="Added to Hm for surfaces exposed to free water [m]."
    )
    hydrodynamic: FloodHydrodynamic
    breakingWave: BreakingWave | None = None
    waveCombination: Literal["sum", "larger"] | None = Field(
        default=None,
        description="How the moving water's (hydrodynamic) and the breaking wave loads are "
        "taken together: sum (added) or larger (the larger of the two, by its total per axis). "
        "Empty: sum, on the safe side. A project setting may choose either.",
    )
    impact: FloodImpact | None = None
    breakaway: BreakawayWalls | None = None
    stabilityFactor: Positive = Field(
        description="Least factor of safety against overturning and sliding under wind and "
        "flood together, dead load only."
    )
    flotationFactor: Positive | None = Field(
        default=None, description="Least dead load / buoyancy of a dry floodproofed building."
    )
    rain: RainRule | None = None
    helipad: HelipadRule | None = None
    explosion: ExplosionRule | None = None
    shelter: ShelterRule | None = None
    notes: dict[str, str] = Field(
        default_factory=dict,
        description="Labels of entries that are not the code's own text, or read with care.",
    )


# ───────────────────────────────── nonlinear static (pushover) ─────────────────────────────────


class PushoverProcedure(_Row):
    """How the pushover is run: the lateral load pattern the code requires, how far the control
    point is pushed and the no-drop rule of the capacity curve."""

    loadPattern: Literal["firstMode", "seismic", "uniform"] = Field(
        description="Lateral load pattern the code requires (firstMode: proportional to the "
        "fundamental mode's shape times the masses, applied at the centres of mass)."
    )
    pushToTarget: Positive = Field(
        description="Push the control point to at least this × the target displacement."
    )
    noDropToTarget: Positive = Field(
        description="The base shear may not drop in any step up to this × the target displacement."
    )
    pDelta: bool = Field(default=True, description="P-Delta effects in the analysis.")
    expectedStrengths: Literal["nominal", "expected"] = Field(
        default="nominal",
        description="Material strengths of the nonlinear model: nominal (never above the "
        "expected strengths the code caps them at) or expected.",
    )
    note: str = Field(default="", description="Why the values are what they are.")


class TargetDisplacement(_Row):
    """The target displacement of the control point (``fem.pushover_target``). Method
    ``coefficient``: a bilinear fit of the capacity curve, the effective period
    Te = T1·√(K1/Ke) and δt = C0·C1·Sa(Te)·(Te/2π)²·g."""

    method: Literal["coefficient"] = Field(
        description="Method id (the engine's generic implementation)."
    )
    bilinearFitShare: Share = Field(
        description="The bilinear curve's first segment meets the capacity curve at this × "
        "the effective yield strength."
    )
    spectrumR: Positive = Field(
        description="R of the spectrum Sa is read from (1: the real, unreduced spectrum)."
    )
    spectrumImportance: Positive = Field(description="I of the spectrum Sa is read from.")
    c1PeriodLimit: Literal["TB", "TC", "TD"] = Field(
        description="C1 = 1 where Te exceeds this corner period of the site class."
    )
    c1Period: Literal["TB", "TC", "TD"] = Field(
        description="The corner period Ts of the C1 formula C1 = [1 + (Rd - 1)·Ts/Te] / Rd."
    )
    minimumRd: Positive = Field(
        default=1.0,
        description="Rd is taken as at least this (below 1 the structure stays elastic and the "
        "C1 formula has no meaning).",
    )
    note: str = Field(default="", description="Why the values are what they are.")


class PushoverAcceptance(_Row):
    """Acceptance of the members at the target displacement (``fem.acceptance``). Method
    ``fibreStrain``: each fibre's strain at the member's end sections against a share of the
    strain at which its material loses strength."""

    method: Literal["fibreStrain"] = Field(
        description="Method id (the engine's generic implementation)."
    )
    deformationShare: Share = Field(
        description="A member's deformation may reach at most this × the deformation at which "
        "it fails (gravity loss, or strength below residualStrengthShare)."
    )
    residualStrengthShare: Share = Field(
        description="Strength (share of the peak) below which the component has failed."
    )
    reinforcementFractureStrain: Positive = Field(
        description="Strain at which a reinforcing bar is taken as lost (fracture or buckling): "
        "the fibre model's bars do not degrade."
    )
    steelFractureStrain: Positive = Field(
        description="Strain at which a structural steel fibre is taken as lost (fracture or "
        "local buckling): the fibre model's steel does not degrade."
    )
    note: str = Field(default="", description="Why the values are what they are.")


class PushoverTable(TableModel):
    """Nonlinear static (pushover) analysis: the procedure, the target displacement method and
    the acceptance of the members."""

    procedure: PushoverProcedure
    targetDisplacement: TargetDisplacement
    acceptance: PushoverAcceptance


# ───────────────────────────────── ramps and accessibility (B24) ─────────────────────────────────


class RampSlope(_Row):
    """A slope limit, as 1 vertical in ``oneIn`` horizontal (8: 1 in 8, 12.5 %)."""

    oneIn: Positive = Field(description="Horizontal run per unit rise.")


class RampRiseBand(_Row):
    """A row of a gradient-by-change-of-level table: up to ``riseMax`` of rise, the slope may be
    at most 1 in ``oneIn`` and the ramp at most ``runMax`` long."""

    riseMax: Positive | None = Field(
        default=None, description="Greatest change of level of the row [mm] (None: any more)."
    )
    oneIn: Positive = Field(description="Steepest slope of the row, 1 in this.")
    runMax: Positive = Field(description="Greatest length of the ramp [mm].")


class RampFlight(_Row):
    """The length of the sloping part between level landings [mm] (along plan)."""

    min: Annotated[float, Field(ge=0)] = Field(default=0, description="Shortest flight [mm].")
    max: Positive | None = Field(default=None, description="Longest flight [mm].")


class RampLanding(_Row):
    """The level landings between flights (and at the ends) of a ramp."""

    min: Positive = Field(description="Least landing length in the direction of travel [mm].")
    atLeastWidth: bool = Field(
        default=False, description="A landing is also at least as long as the ramp is wide."
    )


class RampWidth(_Row):
    """The least clear width of a ramp [mm], by number of traffic lanes for vehicle ramps."""

    min: Positive | None = Field(default=None, description="Least width [mm].")
    byLanes: dict[int, Positive] = Field(
        default_factory=dict, description="Least width [mm] by number of lanes (vehicle ramps)."
    )


class RampHandrails(_Row):
    """Guards and handrails on both sides of the ramp."""

    steeperThan: Positive | None = Field(
        default=None,
        description="Required on ramps steeper than 1 in this (None: on every such ramp).",
    )


class RampTransitions(_Row):
    """A steeper main slope allowed with transition slopes at both ends (vehicle ramps)."""

    oneIn: Positive = Field(description="Steepest main slope with transitions, 1 in this.")
    transitionShare: Share = Field(
        description="Each transition is sloped at this × the main slope."
    )


class RampNote(_Row):
    """A requirement the program cannot check from the model: shown with the ramp's checks."""

    text: str
    steeperThan: Positive | None = Field(
        default=None, description="Applies to ramps steeper than 1 in this only (None: always)."
    )


class RampRules(_Row):
    """The rules of one kind of ramp (``design.ramps``). A rule left out is not checked."""

    name: str = Field(description="What the code calls this kind of ramp.")
    walking: bool = Field(
        default=True,
        description="A walking ramp: no flatter than the ramp threshold it is a level walkway and "
        "no ramp rule applies.",
    )
    maxSlope: RampSlope | None = None
    byRise: list[RampRiseBand] = Field(
        default_factory=list,
        description="Gradient and length by change of level, in increasing rise; the first row "
        "whose riseMax is not exceeded applies.",
    )
    transitions: RampTransitions | None = None
    flight: RampFlight | None = None
    landing: RampLanding | None = None
    width: RampWidth | None = None
    handrails: RampHandrails | None = None
    notes: list[RampNote] = Field(default_factory=list)


class AccessibilityTable(TableModel):
    """Ramps: what counts as one, and the rules of each kind (walkway, accessible, exit,
    vehicle, parking). A kind the pack leaves out is not covered by it."""

    rampThreshold: RampSlope = Field(
        description="A sloping walking surface is a ramp when steeper than 1 in this."
    )
    ramps: dict[str, RampRules] = Field(
        default_factory=dict, description="Rules by kind of ramp (the architecture's Ramp.kind)."
    )


# ───────────────────────────────── anchoring to concrete (B26) ─────────────────────────────────
# Read by saengine.design.anchors (the concrete capacity of cast-in and post-installed anchors:
# steel, breakout, pullout, side-face blowout and pryout, their interaction and the edge rules).


class AnchorConditionPhi(_Group):
    """φ of a concrete failure mode: Condition A (supplementary reinforcement) and B (none)."""

    A: Phi
    B: Phi


class AnchorPhi(_Group):
    steelTensionDuctile: Phi
    steelShearDuctile: Phi
    steelTensionBrittle: Phi
    steelShearBrittle: Phi
    concreteShear: AnchorConditionPhi
    concreteTension: dict[str, AnchorConditionPhi] = Field(
        description="By anchor: castIn, and the post-installed categories category1-3."
    )
    anchorReinforcement: Phi


class AnchorSteel(_Group):
    futaOfFya: Positive = Field(description="futa is at most this × fya.")
    futaMax: Positive = Field(description="futa is at most this [MPa].")
    shearStud: Positive = Field(description="Vsa / (Ase futa) of cast-in headed studs.")
    shearBolt: Positive = Field(description="Vsa / (Ase futa) of bolts and post-installed anchors.")
    groutPad: Share = Field(description="Factor on the steel shear with a built-up grout pad.")
    threadConstant: Positive = Field(description="Ase = π/4 (da - this / nt)².")


class AnchorBreakoutTension(_Group):
    kc: dict[str, Positive] = Field(description="kc of Nb by castIn / postInstalled.")
    kcMaxPostInstalled: Positive
    exponent: Positive = Field(description="Nb = kc λ √f'c hef^exponent.")
    deepCoefficient: Positive = Field(description="The deep cast-in headed form's coefficient.")
    deepExponent: Positive
    deepHefMin: Positive = Field(description="[mm]")
    deepHefMax: Positive = Field(description="[mm]")
    projection: Positive = Field(description="The breakout projects this × hef [-].")
    edgeBase: Positive
    edgeSlope: Positive
    uncrackedCastIn: Positive
    uncrackedPostInstalled: Positive
    narrowEdges: int = Field(ge=1, description="Edges within the projection that limit hef.")
    spacingShare: Share = Field(description="The limited hef is at least this × the spacing.")
    eccentricity: Positive = Field(description="ψec = 1 / (1 + this × e'/hef).")


class AnchorPullout(_Group):
    headed: Positive = Field(description="Np = this × Abrg f'c.")
    hooked: Positive = Field(description="Np = this × f'c eh da.")
    hookMin: Positive = Field(description="eh at least this × da.")
    hookMax: Positive = Field(description="eh taken at most this × da.")
    uncracked: Positive = Field(description="ψc,P in uncracked concrete.")


class AnchorSideFace(_Group):
    coefficient: Positive = Field(description="Nsb = this × ca1 √Abrg λ √f'c.")
    deepRatio: Positive = Field(description="Checked where hef > this × ca1.")
    cornerRatioMax: Positive = Field(description="ca2/ca1 below this reduces Nsb.")
    cornerDivisor: Positive = Field(description="× (1 + ca2/ca1) / this.")
    groupSpacing: Positive = Field(description="Groups with s < this × ca1.")


class AnchorBreakoutShear(_Group):
    coefficient: Positive
    weldedCoefficient: Positive
    weldedMinThickness: Positive = Field(description="[mm]")
    weldedMinSpacing: Positive = Field(description="[mm]")
    lengthExponent: Positive
    exponent: Positive
    bearingLengthMax: Positive = Field(description="le at most this × da.")
    projectedArea: Positive = Field(description="AVco = this × ca1².")
    projection: Positive = Field(description="The breakout projects this × ca1 [-].")
    edgeBase: Positive
    edgeSlope: Positive
    parallel: Positive = Field(description="Shear parallel to an edge: this × the perpendicular.")
    uncracked: Positive
    crackedNoBar: Positive
    crackedEdgeBar: Positive
    crackedEdgeBarStirrups: Positive
    edgeBarMin: Positive = Field(description="Least edge bar for the cracked factors [mm].")
    stirrupSpacingMax: Positive = Field(description="Stirrups at most this [mm].")
    narrowEdges: int = Field(ge=1)
    eccentricity: Positive = Field(description="ψec,V = 1 / (1 + this × e'/ca1).")


class AnchorPryout(_Group):
    shortHef: Positive = Field(description="[mm]")
    kcpShort: Positive
    kcpLong: Positive


class AnchorInteraction(_Group):
    threshold: Share = Field(description="A ratio up to this needs no interaction.")
    limit: Positive = Field(description="Nua/φNn + Vua/φVn at most this.")


class AnchorApplicability(_Group):
    diameterMax: Positive = Field(description="[mm]")
    embedmentMax: Positive = Field(description="[mm]")


class AnchorSpacing(_Group):
    untorquedCastIn: Positive = Field(description="Least spacing / da.")
    torqued: Positive = Field(description="Least spacing / da, torqued or post-installed.")
    edgeTorquedCastIn: Positive = Field(description="Least edge / da.")
    edgePostInstalled: dict[str, Positive]
    criticalEdge: dict[str, Positive] = Field(description="cac / hef by post-installed kind.")
    postInstalledDepthShare: Share
    postInstalledDepthLess: Positive = Field(description="[mm]")


class AnchorSeismic(_Group):
    categories: list[str] = Field(description="Seismic Design Categories the rules apply in.")
    concreteFactor: Share
    reducedFactor: Share
    studWallFactor: Share


class AnchorEstimates(_Group):
    nutAcrossFlats: Positive = Field(description="Nut across the flats / da.")
    threadPitch: dict[str, Positive] = Field(description="Pitch [mm] by diameter [mm].")
    note: str = ""


class AnchorsTable(TableModel):
    """Anchoring to concrete: the strength of cast-in and post-installed anchors in tension and
    shear (steel, breakout, pullout, side-face blowout, pryout), their interaction, the
    seismic rules and the least spacings and edge distances."""

    phi: AnchorPhi
    steel: AnchorSteel
    concreteStrengthMax: dict[str, Positive] = Field(description="[MPa] by castIn/postInstalled.")
    breakoutTension: AnchorBreakoutTension
    pullout: AnchorPullout
    sideFace: AnchorSideFace
    breakoutShear: AnchorBreakoutShear
    pryout: AnchorPryout
    interaction: AnchorInteraction
    applicability: AnchorApplicability
    spacing: AnchorSpacing
    seismic: AnchorSeismic
    estimates: AnchorEstimates


# ─────────────────────────── construction: excavation, fills, formwork ───────────────────────────


class ExcavationNotices(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adjoiningDays: Positive | None = Field(
        default=None, description="Written notice to an adjoining owner before excavating [days]."
    )
    operationsHours: Positive | None = Field(
        default=None,
        description="Written notice before piling, compaction or densification that may load "
        "or move the adjoining property [h].",
    )
    monitoringHours: Positive | None = Field(
        default=None,
        description="Largest interval between level readings of adjacent buildings when a "
        "potential hazard exists [h].",
    )


class ExcavationRules(_Clause):
    """The rules of an excavation and its sides. A rule left out is not checked."""

    underFooting: Positive | None = Field(
        default=None,
        description="An excavation shall not come within this distance under a footing that is "
        "not underpinned [mm].",
    )
    geotechnicalDepth: Positive | None = Field(
        default=None,
        description="Deeper than this, the excavation's design is checked by a geotechnical "
        "engineer [mm]; so is one in soft or erratic soil.",
    )
    protectionDepth: Positive | None = Field(
        default=None,
        description="Sides this deep or deeper (to the deepest point) are shored, sheeted or "
        "retained, or sloped [mm].",
    )
    slopeHorizontal: Positive | None = Field(
        default=None,
        description="An unsupported side slopes at no steeper than 1 vertical to this many "
        "horizontal (a stepped side on average).",
    )
    maxStepHeight: Positive | None = Field(
        default=None, description="Highest step of a stepped side [mm]."
    )
    guardRailHeight: Positive | None = Field(
        default=None, description="Guard rail or solid enclosure along open sides [mm]."
    )
    guardRailSlopeExempt: Positive | None = Field(
        default=None,
        description="No guard rail where the sides slope at 1 vertical to this many horizontal "
        "or flatter.",
    )
    surchargeZone: Positive | None = Field(
        default=None,
        description="Spoil, materials and equipment kept back from the edge by this many times "
        "the depth, unless the sides are sloped or sheeted and shored for the load.",
    )
    sheetPileProjection: float | None = Field(
        default=None,
        ge=0,
        description="Sheet piles extend at least this far above the natural ground [mm].",
    )
    machinerySetback: Positive | None = Field(
        default=None, description="Heavy machinery kept back from a trench by this many depths."
    )
    machinerySetbackMax: Positive | None = Field(
        default=None, description="The machinery setback need not exceed this [mm]."
    )
    escapeDepth: Positive | None = Field(
        default=None, description="Deeper than this: ladders, ramps or other means of escape [mm]."
    )
    inspectionDepth: Positive | None = Field(
        default=None,
        description="Underpinning and the support of adjacent property for excavations this deep "
        "or deeper are under controlled inspection [mm].",
    )
    nightLighting: Positive | None = Field(
        default=None, description="Lighting of the work site at night [lux]."
    )
    notices: ExcavationNotices = Field(default_factory=ExcavationNotices)


class SeepageRules(_Clause):
    """Seepage at the base of an excavation below the water table: the method that finds the
    exit gradient, and the factor of safety against heave when the code gives one."""

    method: Literal["averageGradient"] | None = Field(
        default=None,
        description="averageGradient: the head over the shortest flow path round the cut-off "
        "(down its back and up its front); None: not computed.",
    )
    factorOfSafety: Positive | None = Field(
        default=None,
        description="Required icr / i and weight / uplift; None: the code gives none (1.0, the "
        "physical limit, is checked and the margin left to the engineer).",
    )


class FillRules(_Clause):
    """Fills that support foundations, and the backfill round them."""

    compaction: Share | None = Field(
        default=None, description="Least dry density as a share of the laboratory maximum."
    )
    compactionTest: str = Field(default="", description="The laboratory compaction test.")
    maxLift: Positive | None = Field(default=None, description="Thickest compacted layer [mm].")
    maxParticle: Positive | None = Field(default=None, description="Largest particle [mm].")
    testPitArea: Positive | None = Field(
        default=None, description="One test pit in an uncontrolled fill per this area [m²]."
    )
    testPitDepth: Positive | None = Field(
        default=None, description="Test pits reach this far below the foundations [mm]."
    )
    soilTypes: list[str] = Field(
        default_factory=lambda: ["fill"],
        description="Soil types of the soil report that are fill.",
    )


class WaterproofingRules(_Clause):
    """Below-grade walls and floors: waterproofed under hydrostatic pressure, else
    damp-proofed with a perimeter drain."""

    aboveWaterTable: Positive | None = Field(
        default=None,
        description="Wall waterproofing from this far above the highest water table [mm].",
    )
    dampAboveGrade: Positive | None = Field(
        default=None, description="Damp-proofing up to this far above the finished grade [mm]."
    )
    membrane: Positive | None = Field(
        default=None, description="Thinnest PVC or polyethylene membrane [mm]."
    )
    lap: Positive | None = Field(default=None, description="Membrane joints lapped [mm].")
    pargeting: Positive | None = Field(
        default=None, description="Cement mortar pargeting of masonry walls [mm]."
    )
    floorBase: Positive | None = Field(
        default=None, description="Gravel or crushed stone base under a damp-proofed floor [mm]."
    )
    finesPassing: Share | None = Field(
        default=None, description="Most of the base or drain passing the 4.75 mm sieve."
    )
    drainBeyond: Positive | None = Field(
        default=None, description="Perimeter drain beyond the foundation's outer edge [mm]."
    )
    drainAboveFoundation: Positive | None = Field(
        default=None, description="Top of the drain above the top of the foundation [mm]."
    )
    gradingSlope: Positive | None = Field(
        default=None, description="Ground sloped away at 1 vertical in this many horizontal."
    )
    gradingDistance: Positive | None = Field(
        default=None, description="Over this distance from the wall [mm]."
    )


class FormworkPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    minDiameter: Positive | None = Field(default=None, description="[mm]")
    topDiameter: Positive | None = Field(default=None, description="Spread at the top [mm].")
    maxHeight: Positive | None = Field(default=None, description="[mm]; None: any height.")
    note: str = ""


class FormworkSize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    min: tuple[float, float] = Field(description="Smallest section [b, h] mm (a sheet: [t, t]).")
    max: tuple[float, float] | None = Field(default=None, description="Largest section [mm].")


class FormworkRules(_Clause):
    """Formwork and its supports: the design loads, the timber's allowable stress, the camber,
    the posts and the standard member sizes."""

    loadFactor: Positive | None = Field(
        default=None, description="Formwork and scaffolds carry this many times the load."
    )
    concreteWeight: Positive | None = Field(
        default=None, description="Weight of wet concrete [kN/m³]."
    )
    liveLoad: tuple[float, float] | None = Field(
        default=None,
        description="Workmen and the impact of ramming or vibrating, light to heavy duty [kPa].",
    )
    timberBending: Positive | None = Field(
        default=None, description="Allowable bending stress of soft timber [kPa]."
    )
    tableSpan: Positive | None = Field(
        default=None, description="The standard sizes apply to spans up to this [mm]."
    )
    tableHeight: Positive | None = Field(
        default=None, description="The standard sizes apply to heights up to this [mm]."
    )
    camber: Positive | None = Field(default=None, description="Beams and slabs: 1 in this.")
    cantileverCamber: Positive | None = Field(
        default=None, description="Cantilevers: 1 in this of the projected length."
    )
    bracedPostHeight: Positive | None = Field(
        default=None,
        description="Posts higher than this are braced horizontally and diagonally [mm].",
    )
    lateralBracingHeight: Positive | None = Field(
        default=None,
        description="Floor height above which all centering is braced laterally [mm].",
    )
    steelBeamPostSpacing: Positive | None = Field(
        default=None, description="Steel posts under beam bottoms at most this far apart [mm]."
    )
    nonCombustibleHeight: Positive | None = Field(
        default=None, description="Scaffolding higher than this is non-combustible [mm]."
    )
    posts: dict[str, FormworkPost] = Field(
        default_factory=dict, description="Post limits by kind (bamboo, timber, steel)."
    )
    sizes: list[FormworkSize] = Field(
        default_factory=list, description="Standard sizes of formwork members."
    )


class ConstructionTable(TableModel):
    """Construction practice the design must show or check: excavations and their sides,
    adjoining property, seepage at the base, fills, waterproofing and formwork. A group the
    pack leaves out is not covered by it."""

    excavation: ExcavationRules | None = None
    seepage: SeepageRules | None = None
    fill: FillRules | None = None
    waterproofing: WaterproofingRules | None = None
    formwork: FormworkRules | None = None


# ─────────────────────── time-dependent concrete (creep and shrinkage, B25) ───────────────────────


class TimeShare(_Row):
    """A point of a development curve: the share of the final value reached after ``days``."""

    days: Positive = Field(description="Days under load (creep) or of drying (shrinkage).")
    share: Share = Field(description="Share of the final value reached by then.")


class CreepModel(_Row):
    """The final creep coefficient and its development in time (``fem.concrete_time``). Method
    ``tabulatedCoefficient``: the coefficient tabulated by effective section thickness, ambient
    relative humidity and age at loading (a digitised figure), developing by ``development``."""

    method: Literal["tabulatedCoefficient"] = Field(
        description="Method id (the engine's generic implementation)."
    )
    finalAgeDays: Positive = Field(description="Days under load the final coefficient is for.")
    sealedThickness: Positive = Field(
        description="Effective thickness [mm] of a member that cannot dry (immersed or sealed)."
    )
    thicknesses: list[Positive] = Field(min_length=1, description="Effective thicknesses [mm].")
    relativeHumidity: list[Positive] = Field(min_length=2, description="Ambient RH [%].")
    agesAtLoading: list[Positive] = Field(min_length=1, description="Ages at loading [days].")
    coefficients: dict[str, dict[str, list[float]]] = Field(
        description="thickness -> age at loading -> coefficient at each relative humidity."
    )
    development: list[TimeShare] = Field(
        min_length=1, description="Share of the final creep after so many days under load."
    )
    note: str = Field(default="", description="Why the values are what they are.")


class ShrinkagePoint(_Row):
    """Free shrinkage strains reached after ``days`` of drying, by thickness and humidity."""

    days: Positive
    strains: dict[str, list[float]] = Field(
        description="thickness -> strain (× strainUnit) at each relative humidity; negative: "
        "swelling."
    )


class ShrinkageModel(_Row):
    """Drying shrinkage of plain concrete and of reinforced sections (``fem.concrete_time``).
    Method ``tabulatedStrain``: strains tabulated by thickness and humidity at a few drying
    times (a digitised figure); reinforced: ε / (1 + K ρ)."""

    method: Literal["tabulatedStrain"] = Field(
        description="Method id (the engine's generic implementation)."
    )
    thicknesses: list[Positive] = Field(min_length=1, description="Effective thicknesses [mm].")
    relativeHumidity: list[Positive] = Field(min_length=2, description="Ambient RH [%].")
    points: list[ShrinkagePoint] = Field(min_length=1)
    strainUnit: Positive = Field(default=1e-6, description="Unit of the tabulated strains.")
    referenceWater: Positive = Field(
        description="Water content [litre/m³] the table is for; shrinkage is proportional to it."
    )
    waterRange: tuple[Positive, Positive] = Field(
        description="Range [litre/m³] the proportionality holds in (water is clamped to it)."
    )
    reinforcementCoefficient: dict[str, float] = Field(
        description="K of ε / (1 + K ρ) by exposure (internal, external)."
    )
    note: str = Field(default="", description="Why the values are what they are.")


class ExposureClass(_Row):
    relativeHumidity: Positive = Field(description="Ambient relative humidity [%].")
    reinforcement: str = Field(description="Key of shrinkage.reinforcementCoefficient.")


class ConcreteExposure(_Row):
    """Ambient conditions of the exposures the figures mark."""

    indoor: ExposureClass
    outdoor: ExposureClass
    note: str = Field(default="")


class StrengthGain(_Row):
    """Concrete strength at an age t (days) as a share of f'c: method ``hyperbolic``,
    t / (a + b t), capped at 1; Et from the concrete pack's Ec rule at that strength."""

    method: Literal["hyperbolic"] = Field(description="Method id.")
    a: Positive
    b: Positive
    note: str = Field(default="")


class PrestressTime(_Row):
    """Lump creep and shrinkage of the prestress losses (Part 8 prestressed design)."""

    creepAgesDays: list[Positive] = Field(min_length=1)
    creepCoefficients: list[Positive] = Field(min_length=1)
    creepDevelopment: list[TimeShare] = Field(default_factory=list)
    postTensionedCreepShare: Share
    pretensionedShrinkage: Positive
    postTensionedShrinkage: Positive = Field(
        description="Numerator of the post-tensioned shrinkage over log10(t + 2), t the age at "
        "transfer in days."
    )
    shrinkageDevelopment: list[TimeShare] = Field(default_factory=list)
    note: str = Field(default="")


class ConcreteTimeTable(TableModel):
    """Time-dependent properties of concrete: creep, shrinkage, exposure, the strength gain for
    the modulus at the age of loading, and the lump values of the prestress losses."""

    creep: CreepModel
    shrinkage: ShrinkageModel
    exposure: ConcreteExposure
    strengthGain: StrengthGain
    prestress: PrestressTime | None = None


# ──────────────────────────── steel-concrete composite members (B32) ────────────────────────────
# Read by saengine.design.steel.composite (composite beams with shear connectors, encased and
# filled composite columns, their connectors, detailing and connections).


class CompositeMaterials(_Group):
    concreteMin: Positive = Field(description="Least f'c for the available strength [MPa].")
    concreteMaxNormal: Positive = Field(description="Largest f'c, normal weight [MPa].")
    concreteMaxLight: Positive = Field(description="Largest f'c, lightweight [MPa].")
    lightweightBelow: Positive = Field(description="Density below this is lightweight [kg/m³].")
    steelFyMax: Positive = Field(description="Fy of steel and bars used at most this [MPa].")
    note: str = ""


class CompositeModulus(_Group):
    steel: Positive = Field(description="Es [MPa].")
    concreteCoefficient: Positive = Field(description="Ec = this × wc^exponent × √f'c [MPa].")
    concreteExponent: Positive
    densityMin: Positive = Field(description="wc taken at least this [kg/m³].")
    densityMax: Positive = Field(description="wc taken at most this [kg/m³].")
    densityDefault: Positive = Field(description="wc when the material gives none [kg/m³].")
    note: str = ""


class CompositeStressBlock(_Group):
    concrete: Share = Field(description="Concrete stress of the plastic distribution / f'c.")
    roundFilled: Share = Field(description="Round filled HSS in uniform compression / f'c.")
    strainLimit: Positive = Field(description="Concrete strain of the strain-compatibility method.")


class CompositeFactors(_Group):
    """φ (LRFD) or Ω (ASD) by limit state."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    compression: Positive
    tension: Positive
    flexure: Positive
    flexureEncasedComposite: Positive = Field(
        description="Encased and filled members by the plastic composite section (Sec 13.3.4(c))."
    )
    bearing: Positive


class CompositeBuckling(_Group):
    ratio: Positive = Field(description="Inelastic buckling when Pe ≥ this × Po.")
    base: Positive = Field(description="Pn = Po × this^(Po/Pe).")
    elastic: Positive = Field(description="Pn = this × Pe otherwise.")


class CompositeEncased(_Group):
    barRatioMin: Rho = Field(description="Least ρsr = Asr / Ag (scope).")
    barRatioDetailing: Rho = Field(description="Least bar area / Ag (detailing).")
    barRatioMax: Rho = Field(description="Largest bar area / net concrete area.")
    barStiffnessShare: Share = Field(description="EIeff = Es Is + this × Es Isr + C1 Ec Ic.")
    c1Base: Positive
    c1Slope: Positive
    c1Max: Share
    tieAreaPerSpacing: Positive = Field(description="Least tie area per tie spacing [mm²/mm].")
    cover: Positive = Field(description="Least clear cover [mm].")
    barSpacingLeastShare: Share = Field(description="Bar spacing at most this × least side.")
    tieLarge: Positive = Field(description="Tie bar [mm] when a side exceeds tieSmallSideMax.")
    tieSmall: Positive = Field(description="Least tie bar [mm] otherwise.")
    tieSmallSideMax: Positive = Field(description="[mm]")
    tieGreatestSideShare: Share = Field(description="Tie at least this × the greatest side.")
    tieRequiredMax: Positive = Field(description="A tie larger than this [mm] is never required.")
    tieSpacingLeastShare: Share
    tieSpacingBarDiameters: Positive
    tieSpacingMax: Positive = Field(description="[mm]")
    tieSpacingTieDiameters: Positive
    tieSpacingLeastHalf: Share
    coreFyMaxTied: Positive = Field(description="Core Fy limit of the Chapter 6 method [MPa].")
    connectorLength: Positive = Field(description="Connectors over this × the depth each side.")
    note: str = ""


class CompositeFilled(_Group):
    c2Rectangular: Share
    c2Circular: Share
    c3Base: Positive
    c3Slope: Positive
    c3Max: Share
    rectSlenderness: Positive = Field(description="b/t at most this / √Fy.")
    roundSlenderness: Positive = Field(description="D/t at most this / Fy.")
    concreteAxialMin: Positive = Field(description="[MPa]")
    concreteAxialMax: Positive = Field(description="[MPa]")
    concreteBendingMin: Positive = Field(description="[MPa]")
    concreteBendingMax: Positive = Field(description="[MPa]")
    wallRectangular: Positive = Field(description="t ≥ b √(fy / (this × Es)).")
    wallCircular: Positive = Field(description="t ≥ D √(fy / (this × Es)).")
    connectorLength: Positive = Field(description="Connectors over this × the width each side.")
    note: str = ""


class CompositeColumnRules(_Group):
    steelShareMin: Share = Field(description="Least As / Ag.")
    buckling: CompositeBuckling
    bearingCoefficient: Positive = Field(description="Pp = this × f'c × A_B.")
    encased: CompositeEncased
    filled: CompositeFilled
    connectorSpacingMax: Positive = Field(description="[mm]")


class CompositeDeck(_Group):
    ribHeightMax: Positive = Field(description="[mm]")
    ribWidthMin: Positive = Field(description="[mm]")
    studDiameterMax: Positive = Field(description="[mm]")
    studAboveDeck: Positive = Field(description="Studs extend at least this above the deck [mm].")
    studCover: Positive = Field(description="Concrete above the studs [mm].")
    slabAboveDeck: Positive = Field(description="[mm]")
    anchorageSpacing: Positive = Field(description="Deck anchored at most this apart [mm].")
    haunchDepth: Positive = Field(description="Parallel decks this deep need the haunch [mm].")
    haunchWidthFirst: Positive = Field(description="[mm] for the first stud in a row.")
    haunchWidthPerStud: Positive = Field(description="× stud diameter per further stud.")
    ribRatio: Positive = Field(description="wr / hr limit of the Rg cases.")
    emidHt: Positive = Field(description="e_mid-ht limit of the Rp cases [mm].")


class CompositeStuds(_Group):
    lengthMin: Positive = Field(description="Stud length at least this × its diameter.")
    coefficient: Positive = Field(description="Qn = this × Asc √(f'c Ec).")
    rgOne: Positive
    rgTwo: Positive
    rgThreeOrMore: Positive
    rgDirect: Positive
    rgParallelWide: Positive
    rgParallelNarrow: Positive
    rpDirect: Positive
    rpStrong: Positive
    rpParallel: Positive
    rpWeak: Positive
    note: str = ""


class CompositeChannel(_Group):
    coefficient: Positive = Field(description="Qn = this × (tf + webShare tw) Lc √(f'c Ec).")
    webShare: Positive


class CompositeSpacing(_Group):
    longitudinal: Positive = Field(description="Least spacing along the beam / d.")
    transverse: Positive = Field(description="Least spacing across the beam / d.")
    ribs: Positive = Field(description="Least spacing in perpendicular deck ribs / d.")
    slabMultiple: Positive = Field(description="Largest spacing / total slab thickness.")
    max: Positive = Field(description="Largest spacing [mm].")
    flangeRatio: Positive = Field(description="d at most this × flange thickness off the web.")
    lateralCover: Positive = Field(description="[mm]")


class CompositeDeflection(_Group):
    coefficient: Positive = Field(description="Ie = Is + this × p^exponent × (It - Is).")
    exponent: Positive
    creep: Positive = Field(description="Long-term deflection increase (share).")


class CompositeSlab(_Group):
    transverseOnDeck: Rho
    transverseParallel: Rho
    transversePerpendicular: Rho
    endBars: Positive = Field(description="Bars at the ends of beams with perpendicular ribs.")
    endBarDiameter: Positive = Field(description="[mm]")


class CompositeStudRow(_Group):
    diameter: Positive = Field(description="[mm]")
    height: Positive = Field(description="[mm]")
    strengths: list[Positive] = Field(description="Design strength [kN] by the table's grades.")


class CompositeBeamLimitState(_Group):
    """C9: the plastic positive moment of composite beams with design strengths (method
    ``partialFactors``): the concrete at ``concreteShare`` × the grade over the block depth,
    the steel at fy / ``steelGamma``, no φ; headed studs by their tabulated design strength
    (``studs``: rows by size, columns by ``grades``, linear between the grades; a stud takes
    the largest row not larger than it) × ``studShare``."""

    method: Literal["partialFactors"] = "partialFactors"
    concreteShare: Share = Field(description="Design concrete stress of the block / the grade.")
    steelGamma: Positive = Field(description="γ of the steel beam's yield stress.")
    grades: list[Positive] = Field(min_length=2, description="Concrete grade [MPa].")
    studs: list[CompositeStudRow] = Field(min_length=1)
    studShare: Share = Field(description="× the tabulated strength.")


class CompositeBeamRules(_Group):
    spanShare: Share = Field(description="Effective width per side at most this × span.")
    spacingShare: Share = Field(description="... and this × the distance to the next beam.")
    webCompact: Positive = Field(description="Plastic when h/tw ≤ this × √(E/Fy).")
    constructionStrength: Share = Field(description="Steel alone until f'c reaches this share.")
    constructionDeadFactor: Positive
    constructionLiveFactor: Positive
    deck: CompositeDeck
    studs: CompositeStuds
    channel: CompositeChannel
    spacing: CompositeSpacing
    deflection: CompositeDeflection
    slab: CompositeSlab
    # C9: composite beams by limit state with partial factors on the materials (IS 11384).
    limitState: CompositeBeamLimitState | None = None


class CompositeConnections(_Group):
    seismicReduction: Share = Field(
        description="Bearing and shear friction reduced by this share in seismic systems."
    )
    note: str = ""


class CompositeTable(TableModel):
    """Steel-concrete composite members: composite beams with shear connectors on solid slabs
    and formed steel deck, encased and filled composite columns, their load transfer,
    detailing and connections. ``method``: how the nominal section strength is found (the
    engine's ``plasticStress`` implementation)."""

    method: Literal["plasticStress"] = Field(description="Method id.")
    materials: CompositeMaterials
    modulus: CompositeModulus
    stressBlock: CompositeStressBlock
    phi: CompositeFactors
    omega: CompositeFactors
    column: CompositeColumnRules
    beam: CompositeBeamRules
    connections: CompositeConnections


# ─────────────────────── slab, wall, stair and composite methods (B33) ───────────────────────


class StripShareTable(_Group):
    """Percent of a moment a column strip takes, by l2/l1 (``ratios``) for αf1 l2/l1 = 0
    (``alphaZero``) and >= ``alphaLimit`` (``alphaFull``), linear between (both ways)."""

    ratios: list[Positive] = Field(min_length=2)
    alphaZero: list[Annotated[float, Field(ge=0, le=100)]] = Field(min_length=2)
    alphaFull: list[Annotated[float, Field(ge=0, le=100)]] = Field(min_length=2)


class ExteriorStripShareTable(_Group):
    """Percent of an exterior negative moment a column strip takes, by l2/l1, for αf1 l2/l1 = 0
    and >= ``alphaLimit`` and βt = 0 (``betaZero``: one value per ratio) and >= ``betaLimit``."""

    ratios: list[Positive] = Field(min_length=2)
    alphaZeroBetaZero: list[Annotated[float, Field(ge=0, le=100)]] = Field(min_length=2)
    alphaZeroBetaFull: list[Annotated[float, Field(ge=0, le=100)]] = Field(min_length=2)
    alphaFullBetaZero: list[Annotated[float, Field(ge=0, le=100)]] = Field(min_length=2)
    alphaFullBetaFull: list[Annotated[float, Field(ge=0, le=100)]] = Field(min_length=2)
    betaLimit: Positive


class EndSpanShares(_Group):
    """Shares of Mo in an end span by the edge condition (Table 6.6.4 of the default pack (BNBC 2020)):
    ``interiorNegative``, ``positive``, ``exteriorNegative``, each by the conditions of
    ``conditions`` in that order."""

    conditions: list[
        Literal["unrestrained", "beamsAll", "noBeams", "noBeamsEdgeBeam", "restrained"]
    ] = Field(min_length=1)
    interiorNegative: list[Share]
    positive: list[Share]
    exteriorNegative: list[Annotated[float, Field(ge=0, le=1)]]


class DirectDesignRules(_Group):
    """The direct design method of two-way slab systems on columns or walls (method id
    ``directDesign``): its limits, the static moment and its distribution to the strips."""

    minSpans: int = Field(ge=1, description="Least continuous spans each way.")
    maxPanelRatio: Positive = Field(description="Longer over shorter span of a panel at most.")
    maxSpanDifference: Share = Field(
        description="Successive spans differ by at most this share of the longer."
    )
    maxColumnOffset: Share = Field(
        description="Columns off the line by at most this share of the span."
    )
    maxLiveToDead: Positive = Field(description="Unfactored live load over dead load at most.")
    stiffnessRatioRange: tuple[Positive, Positive] = Field(
        description="αf1 l2² / (αf2 l1²) within these for panels with beams on all sides."
    )
    staticDivisor: Positive = Field(description="Mo = wu l2 ln² / staticDivisor.")
    minClearSpanShare: Share = Field(description="ln at least this share of l1.")
    interiorNegative: Share
    interiorPositive: Share
    endSpan: EndSpanShares
    interiorStrip: StripShareTable
    exteriorStrip: ExteriorStripShareTable
    positiveStrip: StripShareTable
    alphaLimit: Positive = Field(description="αf1 l2/l1 from which the 'full' columns apply.")
    beamShare: Share = Field(
        description="Share of the column strip moment beams take at αf1 l2/l1 >= alphaLimit."
    )
    uniformSupportShare: Share = Field(
        description="Supports at least this share of l2 wide spread the negative moment over l2."
    )
    edgeTransferShare: Share = Field(description="Gravity moment to an edge column: this x Mo.")
    modification: Annotated[float, Field(ge=0, lt=1)] = Field(
        description="Moments may be changed by this share if Mo is kept."
    )
    columnMomentFactor: Positive = Field(
        description="Msc = factor [(qDu + share qLu) l2 ln² - ...]."
    )
    columnMomentLiveShare: Share
    torsionShape: Positive = Field(description="C = Σ (1 - shape x/y) x³ y / 3.")
    wallEdgeMiddleFactor: Positive = Field(
        description="A middle strip beside a wall-supported edge takes this times its half."
    )


class EquivalentFrameRules(_Group):
    """The equivalent frame method (method id ``equivalentFrame``)."""

    torsionFactor: Positive = Field(description="Kt = Σ factor Ecs C / (l2 (1 - c2/l2)³).")
    uniformLiveMax: Positive = Field(
        description="Full live load on all panels when L <= this x D (else patterns)."
    )
    patternLiveShare: Share = Field(description="The share of the live load of the patterns.")
    faceLimit: Share = Field(
        description="Negative moment at the face, not farther than this x l1 from the column centre."
    )
    farSpans: int = Field(ge=1, description="Spans each way taken in the analysis of one support.")
    torsionShape: Positive = Field(description="C = Σ (1 - shape x/y) x³ y / 3.")
    fixedWallShare: Share = Field(
        description="A wall across the frame at least this share of l2 long fixes the slab."
    )


class CornerRules(_Group):
    """Corner reinforcement of two-way slabs at exterior corners."""

    alphaMin: Positive = Field(description="Edge beams stiffer than this αf need corner steel.")
    extentShare: Share = Field(description="Over this share of the longer span from the corner.")
    spacingFactor: Positive = Field(description="Bars at most this x h apart.")


class OpeningRules(_Group):
    """Openings in slabs without beams designed without an analysis of them."""

    columnColumnShare: Share = Field(
        description="Where column strips cross: at most this share of a column strip's width cut."
    )
    columnMiddleShare: Share = Field(
        description="Where a column and a middle strip cross: at most this share of either's bars."
    )


class SlabMethodsTable(TableModel):
    """Analysis methods of two-way slab systems on columns, walls or flexible beams, chosen by
    id in ``twoWayMethods`` (tried in order: the first whose limits a slab meets), and the
    detailing rules of two-way slabs (corners, openings)."""

    twoWayMethods: list[Literal["directDesign", "equivalentFrame"]] = Field(default_factory=list)
    directDesign: DirectDesignRules | None = None
    equivalentFrame: EquivalentFrameRules | None = None
    corner: CornerRules | None = None
    openings: OpeningRules | None = None
    clauses: dict[str, str] = Field(default_factory=dict)


class SlenderWallRules(_Group):
    """Out-of-plane design of slender walls by the second-order midheight moment (method id
    ``midheightMoment``)."""

    method: Literal["midheightMoment"] = "midheightMoment"
    maxAxialShare: Share = Field(description="Pu/Ag at midheight at most this x f'c.")
    deflectionFactor: Positive = Field(description="Δu = 5 Mu lc² / (factor 48 Ec Icr).")
    deflectionDivisor: Positive = Field(description="Service Δs at most lc / divisor.")
    minModularRatio: Positive = Field(description="Es/Ec not less than this in Icr.")
    serviceCrackShare: Share = Field(description="Δs by the bilinear rule above this x Mcr.")
    ruptureCoefficient: Positive = Field(description="fr = coefficient λ √f'c [MPa].")
    spreadSlope: Positive = Field(description="Concentrated loads spread 'slope' down to 1 across.")


class GradeBeamWallRules(_Group):
    """Walls designed as grade beams: flexure and shear as a beam, the exposed part as a wall."""

    method: Literal["beam"] = "beam"


class WallMethodsTable(TableModel):
    """Methods of reinforced-concrete walls beyond the compression-member design."""

    slender: SlenderWallRules | None = None
    gradeBeam: GradeBeamWallRules | None = None
    clauses: dict[str, str] = Field(default_factory=dict)


class BuiltInStairRules(_Group):
    """Flights and landings built into walls and spanning along the flight."""

    embedmentMin: Positive = Field(description="Built in at least this [mm].")
    deductedStrip: Positive = Field(description="Strip [mm] taken off the loaded width.")
    addedBreadth: Positive = Field(description="Effective breadth increased by this [mm].")


class PowerTerm(_Row):
    """One factor [base + coefficient (variable - offset)^exponent] of an empirical product
    (the sign of (variable - offset) is kept through the power)."""

    variable: Literal["A", "B", "C", "L", "H", "T", "fc"]
    base: float
    coefficient: float
    offset: float = 0.0
    exponent: Positive = 1.0


class EmpiricalExpression(_Row):
    """value = factor × Π terms (service value of a free-standing stair)."""

    id: Literal["deflection", "MS", "MF", "MK", "Mo", "AF", "TF", "MI", "Vo"]
    name: str
    unit: Literal["m", "kN", "kN·m"]
    factor: float
    terms: list[PowerTerm]


class FreeStandingRules(_Group):
    """Free-standing (landing unsupported) stairs by service-load expressions (method id
    ``empiricalTable``), scaled to the live load and factored."""

    method: Literal["empiricalTable"] = "empiricalTable"
    expressions: list[EmpiricalExpression] = Field(min_length=1)
    ranges: dict[Literal["A", "B", "C", "L", "H", "T", "fc"], tuple[float, float]]
    referenceLive: Positive = Field(description="Live load [kN/m²] of the expressions.")
    unitWeight: Positive = Field(description="Concrete unit weight [kN/m³] of the expressions.")
    liveScale: tuple[float, float, float] = Field(
        description="(a, b, c): values × (a T + LL + b) / (a T + c)."
    )
    outerShareSupport: Share = Field(description="Share of the MS steel in the outer half.")
    innerShareJunction: Share = Field(description="Share of the MK steel in the inner half.")


class SawtoothCurve(_Row):
    """Support moment coefficients (magnitudes) by number of treads for one tread/riser
    stiffness ratio k (None: k infinite); None where the figure gives no value."""

    k: Annotated[float, Field(ge=0)] | None
    coefficients: list[Positive | None]


class SawtoothRules(_Group):
    """Sawtooth (slabless) stairs: support moment Ms = coefficient n l² from a chart by the
    number of treads and the stiffness ratio (method id ``supportChart``)."""

    method: Literal["supportChart"] = "supportChart"
    treads: list[int] = Field(min_length=2)
    curves: list[SawtoothCurve] = Field(min_length=2)
    freeDivisor: Positive = Field(
        description="Free moment n l² / divisor (× (j² + 1)/j² for odd j)."
    )
    reentrantFactor: Positive = Field(description="Re-entrant corners take this × the steel.")


class HelicoidalCurve(_Row):
    """Values of one redundant coefficient (k1, k2 or k3) by β for one helix slope φ."""

    k: Literal["k1", "k2", "k3"]
    phi: Positive = Field(description="Slope of the helix [°].")
    values: list[float]


class HelicoidalChart(_Row):
    """One chart: the coefficients for one R1/R2 and b/h."""

    radiusRatio: Positive
    widthRatio: Positive
    betas: list[Positive] = Field(min_length=2, description="Total angle subtended in plan [°].")
    curves: list[HelicoidalCurve] = Field(min_length=3)


class HelicoidalRules(_Group):
    """Helicoidal stairs: midspan redundants Mo = k1 n R2², H = k2 n R2 and the support moment
    Mvs = k3 n R2² from charts (method id ``redundantCharts``), the forces along the helix by
    the closed-form equations."""

    method: Literal["redundantCharts"] = "redundantCharts"
    charts: list[HelicoidalChart] = Field(min_length=1)


class StairMethodsTable(TableModel):
    """Load distribution rules and the methods of special stairs."""

    builtIn: BuiltInStairRules | None = None
    openWellShare: Share | None = Field(
        default=None, description="Load on areas common to two crossing spans, each way."
    )
    stringers: bool = Field(default=False, description="Stairs on stringer beams are covered.")
    freeStanding: FreeStandingRules | None = None
    sawtooth: SawtoothRules | None = None
    helicoidal: HelicoidalRules | None = None
    clauses: dict[str, str] = Field(default_factory=dict)


class RoughenedTiedLimit(_Group):
    """Vnh = (base + steelShare ρv fy) λ bv d, at most cap bv d [MPa terms]."""

    base: Positive
    steelShare: Positive
    cap: Positive


class CompositeConcreteTable(TableModel):
    """Composite concrete flexural members (precast and cast-in-place concrete placed
    separately): horizontal shear at the contact surface and its ties."""

    roughenedLimit: Positive = Field(description="Vnh <= this bv d [MPa], roughened, no ties.")
    tiedSmoothLimit: Positive = Field(description="Vnh <= this bv d, minimum ties, not roughened.")
    roughenedTied: RoughenedTiedLimit
    minTies: dict[Literal["sqrtShare", "floor"], Positive] = Field(
        description="Av,min = max(sqrtShare √f'c, floor) bw s / fyt."
    )
    roughness: Positive = Field(description="Full amplitude of the roughening [mm].")
    tieSpacingFactor: Positive = Field(description="Ties at most this × the least dimension.")
    tieSpacingMax: Positive = Field(description="Ties at most this far apart [mm].")
    clauses: dict[str, str] = Field(default_factory=dict)


# ─────────────────────── steel seismic provisions: general and moment frames (B35) ───────────────────────
# Read by saengine.design.steel.seismic (capacity design of the steel members, joints and
# connections of the seismic load resisting system). B38 adds the braced frames, plate walls
# and composite seismic systems to the same table.


class SteelSeismicTrigger(_Group):
    rAbove: Positive = Field(description="The provisions apply when R is taken above this.")
    note: str = ""


class SteelSeismicExpected(_Row):
    """A row of the expected strength ratios: the steels it covers and Ry, Rt."""

    application: Literal["shapes", "hss", "pipe", "plates"] = Field(
        description="Hot-rolled shapes and bars, hollow sections, pipe or plates."
    )
    match: list[str] = Field(
        min_length=1,
        description="Regular expressions; a material matches when one is found in its grade, "
        "standard, id or name (case ignored).",
    )
    fyMin: float | None = Field(default=None, gt=0, description="Least Fy of the row [MPa].")
    fyMax: float | None = Field(default=None, gt=0, description="Largest Fy of the row [MPa].")
    Ry: float = Field(ge=1, description="Expected yield stress / Fy.")
    Rt: float = Field(ge=1, description="Expected tensile strength / Fu.")
    label: str = ""


class SteelSeismicExpectedTable(_Group):
    rows: dict[str, SteelSeismicExpected]
    fallbackRy: float = Field(ge=1, description="Ry of a steel no row matches.")
    fallbackRt: float = Field(ge=1, description="Rt of a steel no row matches.")
    note: str = ""


class SteelSeismicToughness(_Group):
    flangeThickness: Positive = Field(description="Rolled shapes this thick need the CVN [mm].")
    plateThickness: Positive = Field(description="Plates this thick need the CVN [mm].")
    energy: Positive = Field(description="[J]")
    temperature: float = Field(description="[°C]")
    weldEnergy: Positive = Field(description="Filler metal CVN [J].")
    weldTemperature: float = Field(description="[°C]")


class SteelSeismicWeb(_Group):
    """Webs in flexure or flexure and axial compression: λ = a √(E/Fy) (1 - b Ca) on one side
    of ``split`` and c √(E/Fy) (d - Ca) ≥ floor √(E/Fy) on the other."""

    split: Positive = Field(description="Ca at the change of form.")
    linearA: Positive
    linearB: Positive
    offsetA: Positive
    offsetB: Positive
    floor: Positive
    linearAbove: bool = Field(
        description="True: the linear form for Ca above the split (as printed)."
    )
    leastOfBoth: bool = Field(
        description="Take the least of the printed assignment and the swapped one."
    )
    note: str = ""


class SteelSeismicWidthThickness(_Group):
    """λps (seismically compact) as coefficients of √(E/Fy) unless noted."""

    iFlange: Positive = Field(description="Flanges of I-shapes, flexure or compression.")
    iFlangeRelaxed: Positive = Field(description="Flanges of I-shaped columns where note [d].")
    channelFlange: Positive = Field(description="Channels, angle pairs in contact, braces.")
    hPileFlange: Positive
    flatBar: Positive = Field(description="b/t of flat bars (a plain number).")
    angleLeg: Positive = Field(description="Single angles, double angles, tee flanges.")
    teeStem: Positive
    smfBeamWeb: Positive = Field(description="Webs of beams in special moment frames.")
    web: SteelSeismicWeb
    roundHss: Positive = Field(description="D/t ≤ this × (E/Fy) (no root: see the note).")
    rectHss: Positive
    hPileWeb: Positive
    phiB: Phi = Field(description="φb of Ca = Pu / (φb Py).")
    relaxedRatio: Positive = Field(
        description="Columns of special moment frames may use λp when the column-beam moment "
        "ratio exceeds this."
    )
    expectedYield: bool = Field(
        default=False,
        description="Alpha 9 C3: the limits are of √(E / (Ry Fy)) (and E / (Ry Fy)) with the "
        "member's expected yield ratio Ry, not of √(E/Fy).",
    )
    note: str = ""


class SteelSeismicColumns(_Group):
    axialRatio: Positive = Field(description="Pu / φPn above this: the amplified seismic load.")
    phi: Phi = Field(description="φ of φPn in the ratio.")
    connectionFactor: Positive = Field(description="× Ry × the connecting members' strengths.")


class SteelSeismicSplices(_Group):
    pjpFactor: Positive = Field(description="PJP groove welds: at least this × required.")
    flangeShare: Positive = Field(description="Each flange splice at least this × Ry Fy Af.")
    distance: Positive = Field(description="Splices at least this from the connections [mm].")
    shortStorey: Positive = Field(description="Clear height below this: splice at mid [mm].")
    gravityShear: Positive = Field(description="Columns not in the SLRS: this × Mpc / H.")
    smfFlexure: Positive = Field(description="Splices of SMF not groove welded: × Ry Fy Zx.")
    smfShear: Positive = Field(description="Web splices of SMF: this × ΣMpc / H.")


class SteelSeismicBases(_Group):
    shearFactor: Positive = Field(description="Column base shear: this × Ry Fy Zx / H.")
    flexureFactor: Positive = Field(description="Column base moment: this × Ry Fy Z.")


class SteelSeismicFrame(_Group):
    """The rules of one kind of moment frame; a missing rule is not required of it."""

    driftAngle: float | None = Field(default=None, gt=0, description="Connection drift [rad].")
    flexuralShare: float | None = Field(
        default=None, gt=0, description="Connection resistance at the drift / Mp."
    )
    hingeFactor: Positive = Field(description="Expected moment = this × Ry Mp.")
    compactness: Literal["seismic", "moderate", "compact", "none"] = Field(
        description="Width-thickness limits of the beams and columns (alpha 9 C3: ``moderate`` "
        "the moderately ductile limits, ``widthThicknessModerate``)."
    )
    fyLimit: Positive = Field(description="Fy of members expected to yield at most [MPa].")
    panelZone: bool = Field(description="Panel zone shear and thickness of the frame's own.")
    panelZonePhi: float | None = Field(default=None, gt=0, le=1)
    panelZoneOmega: float | None = Field(default=None, gt=0)
    panelThicknessDivisor: float | None = Field(
        default=None, gt=0, description="t ≥ (dz + wz) / this."
    )
    momentRatio: float | None = Field(
        default=None, gt=0, description="ΣM*pc / ΣM*pb must exceed this."
    )
    axialExemption: float | None = Field(
        default=None, gt=0, description="Columns with Puc below this × Fyc Ag may be exempt."
    )
    elasticRatio: float | None = Field(
        default=None, gt=0, description="A column is taken elastic above this moment ratio."
    )
    flangeBraceShare: float | None = Field(
        default=None, gt=0, description="Column flange brace: this × Fy bf tbf."
    )
    unbracedSlenderness: float | None = Field(default=None, gt=0, description="L/r at most.")
    unbracedAmplification: float | None = Field(
        default=None, gt=0, description="E at most this × the frame's available strength."
    )
    beamBracing: float | None = Field(default=None, gt=0, description="Lb ≤ this × ry E / Fy.")
    # Alpha 9 C3b (AISC 341-16+ Sec D1.2): the beam bracing limit by the expected yield stress.
    beamBracingExpected: bool = Field(
        default=False, description="Lb ≤ beamBracing × ry E / (Ry Fy) (else E / Fy)."
    )
    # Alpha 9 C3b (AISC 341-16+ Sec E3.6d with AISC 358 Sec 2.4.3): the expected moment by Cpr.
    hingeFactorMethod: Literal["fixed", "cpr"] = Field(
        default="fixed",
        description="The expected moment: ``fixed`` (hingeFactor × Ry Mp) or ``cpr`` (Cpr Ry Mp, "
        "Cpr = (Fy + Fu) / (2 Fy) at most ``cprMax``).",
    )
    cprMax: float | None = Field(default=None, gt=0, description="``cpr``: Cpr at most this.")
    braceStrength: float | None = Field(
        default=None, gt=0, description="Brace next to a hinge: Pu = this × Mu / ho."
    )
    connectionMoment: float | None = Field(
        default=None, gt=0, description="FR connections: required M = this × Ry Mp."
    )
    prShare: float | None = Field(
        default=None, gt=0, description="PR connections: Mn at least this × Mp."
    )
    weldFactor: float | None = Field(
        default=None, gt=0, description="Tension welds: this × Ry Fy × the element's area."
    )
    continuityCoefficient: float | None = Field(
        default=None, gt=0, description="Plates when tcf < this × √(bf tbf Fyb / Fyc)."
    )
    continuityWidthRatio: float | None = Field(
        default=None, gt=0, description="... or when tcf < bf / this."
    )
    plateOneSided: float | None = Field(default=None, gt=0, description="× tbf, one-sided.")
    plateTwoSided: float | None = Field(default=None, gt=0, description="× tbf, two-sided.")
    note: str = ""


class SteelSeismicTruss(_Group):
    """Special truss moment frames: the special segment and its members."""

    spanMax: Positive = Field(description="[mm]")
    depthMax: Positive = Field(description="[mm]")
    segmentMin: Share = Field(description="Special segment at least this × the span.")
    segmentMax: Share
    segmentZone: Share = Field(description="... inside the middle (between quarter points).")
    panelRatioMin: Positive = Field(description="Panel length / depth at least.")
    panelRatioMax: Positive
    crossing: Positive = Field(description="X diagonals joined for this × Pnt.")
    diagonalGravity: Positive = Field(description="Gravity axial at most this × Fy Ag.")
    chordShear: Share = Field(description="Chords give at least this share of the shear.")
    chordAxial: Positive = Field(description="Chord axial at most this × φ Fy Ag.")
    phi: Phi
    diagonalCompression: Positive = Field(description="0.3 Pnc of the diagonals' shear.")
    vneMoment: Positive = Field(description="Eq 6.10.302: this × Ry Mnc / Ls.")
    vneStiffness: Positive = Field(description="... + this × EI (L - Ls) / Ls³.")
    braceInside: Positive = Field(description="Braces at and in the segment: × Ry Pnc.")
    braceOutside: Positive = Field(description="Braces outside it: × Ry Pnc.")
    note: str = ""


class SteelSeismicConnections(_Group):
    bearingMax: Positive = Field(description="Nominal bearing at most this × d t Fu.")
    slipClass: Literal["A", "B"] = Field(description="Faying surface class of SLRS bolts.")
    clipWeb: Positive = Field(description="Clip along the web beyond k [mm].")
    clipFlange: Positive = Field(description="Clip along the flange beyond k1 at most [mm].")
    clipRadius: Positive = Field(description="Least radius of a curved clip [mm].")


class SteelSeismicPractice(_Group):
    """SAEngine practice where the code defers to tested or prequalified connections."""

    hingeOffsetDepths: float = Field(
        ge=0, description="Plastic hinge this × the beam depth from the column face."
    )
    protectedDepths: Positive = Field(
        description="Protected zone from the column face over this × the beam depth."
    )
    rigidZoneMax: float = Field(
        ge=0, le=1, description="Rigid zone factor at most this for the panel zone drift."
    )
    note: str = ""


# ─────────────── steel seismic provisions: braced frames, plate walls, composite (B38) ───────────────
# Read by saengine.design.steel.seismic_braced, seismic_walls and seismic_composite.


class SteelSeismicConcentric(_Group):
    """A concentrically braced frame kind (special or ordinary); a missing rule is not
    required of it."""

    slenderness: float | None = Field(
        default=None, gt=0, description="Braces: KL/r ≤ this × √(E/Fy)."
    )
    slendernessChevronOnly: bool = Field(
        default=False, description="The KL/r limit only for braces in K, V or inverted-V."
    )
    slendernessMax: float | None = Field(
        default=None, gt=0, description="KL/r up to this when the columns take Ry Pn."
    )
    compactMembers: list[Literal["brace", "column", "beam"]] = Field(
        default_factory=list, description="Members that must be seismically compact."
    )
    moderateMembers: list[Literal["brace", "column", "beam"]] = Field(
        default_factory=list,
        description="Alpha 9 C3: members that must meet the moderately ductile limits.",
    )
    filledHssExempt: bool = Field(
        default=False, description="Concrete-filled HSS braces need not be compact."
    )
    tensionShareMin: float | None = Field(
        default=None, gt=0, lt=1, description="Braces in tension resist at least this share."
    )
    tensionShareMax: float | None = Field(
        default=None, gt=0, lt=1, description="... and at most this share of a line's force."
    )
    lineOffset: float | None = Field(
        default=None, gt=0, description="Parallel lines within this × the building dimension."
    )
    stitchRatio: float | None = Field(
        default=None, gt=0, description="Built-up braces: a/ri ≤ this × the member's KL/r."
    )
    stitchRatioNoShear: float | None = Field(
        default=None, gt=0, description="... when buckling causes no shear in the stitches."
    )
    stitchesMin: int | None = Field(default=None, ge=1, description="Stitches at least.")
    connectionFlexure: float | None = Field(
        default=None, gt=0, description="Brace connections: M = this × Ry Mp of the brace."
    )
    connectionCompression: float | None = Field(
        default=None, gt=0, description="Brace connections: P = this × Ry Pn of the brace."
    )
    slipWithoutOmega: bool = Field(
        default=False, description="Bolt slip under the combinations without Ω0 only."
    )
    postBuckling: Positive = Field(description="Compression braces at this × Pn for the beams.")
    kBracing: bool = Field(description="K-type bracing permitted.")
    spliceFlexureShare: float | None = Field(
        default=None, gt=0, description="Column splices develop this × the lesser φMn."
    )
    protectedMiddle: float | None = Field(
        default=None, gt=0, description="Protected zone: the middle this × the brace length."
    )
    note: str = ""


class SteelSeismicEccentric(_Group):
    """Eccentrically braced frames: the links and the members outside them."""

    phi: Phi = Field(description="φv of the link shear.")
    shearYield: Positive = Field(description="Vp = this × Fy Aw.")
    flexureShear: Positive = Field(description="Vn ≤ this × Mp / e.")
    axialLimit: Positive = Field(description="Pu above this × Py: the reduced strengths.")
    mpaFactor: Positive = Field(description="Mpa = this × Mp (1 - Pr/Pc).")
    lengthRatio: Positive = Field(description="ρ' Aw/Ag at or above this: Eq 6.10.305.")
    lengthA: Positive
    lengthB: Positive
    shortLink: Positive = Field(description="e ≤ this × Mp/Vp: a shear link.")
    longLink: Positive = Field(description="e ≥ this × Mp/Vp: a flexural link.")
    flexuralLink: Positive = Field(description="No intermediate stiffeners above × Mp/Vp.")
    rotationShort: Positive = Field(description="Link rotation of short links [rad].")
    rotationLong: Positive = Field(description="Link rotation of long links [rad].")
    endStiffenerWidth: Positive = Field(description="End stiffeners: width ≥ bf - this × tw.")
    endStiffenerThickness: Positive = Field(description="End stiffeners: t ≥ this × tw.")
    stiffenerThicknessMin: Positive = Field(description="[mm]")
    spacingShort: Positive = Field(description="Spacing ≤ (this × tw - d/divisor) at γ short.")
    spacingLong: Positive = Field(description="... (this × tw - d/divisor) at γ long.")
    spacingDepthDivisor: Positive
    flangeDistance: Positive = Field(description="Long links: stiffeners this × bf from ends.")
    twoSidedDepth: Positive = Field(description="Links this deep need two-sided stiffeners.")
    oneSidedThickness: Positive = Field(description="One-sided stiffeners: t ≥ this × tw.")
    oneSidedWidth: Positive = Field(description="One-sided stiffeners: width ≥ this × bf.")
    weldWebShare: Positive = Field(description="Stiffener-to-web welds: this × Ast Fy.")
    weldFlangeShare: Positive = Field(description="Stiffener-to-flange welds: this × Ast Fy.")
    braceStrength: Positive = Field(description="Link end braces: this × Ry Z Fy / ho.")
    braceFactor: Positive = Field(description="Diagonal braces: this × Ry Vn of the link.")
    beamFactor: Positive = Field(description="Beam outside the link: this × Ry Vn.")
    columnFactor: Positive = Field(description="Columns: this × Ry Vn of the links above.")
    upperStoreysAbove: int = Field(
        ge=1, description="Above this many storeys the top storey may be a CBF."
    )
    note: str = ""


class SteelSeismicRestrained(_Group):
    """Buckling-restrained braced frames."""

    phi: Phi = Field(description="φ of the steel core's yielding.")
    connectionFactor: Positive = Field(description="Connections: × the adjusted compression.")
    betaMin: Positive = Field(description="β (compression adjustment) at least.")
    testDrift: Positive = Field(description="Restraint and tests to this × the design drift.")
    coreToughness: Positive = Field(description="Core plates this thick need the CVN [mm].")
    spliceFlexureShare: Positive = Field(description="Column splices: × the lesser φMn.")
    kBracing: bool = Field(description="K-type bracing permitted.")
    note: str = ""


class SteelSeismicPlateWalls(_Group):
    """Special plate shear walls (steel webs between boundary elements)."""

    phi: Phi = Field(description="φ of the web shear yielding.")
    shearCoefficient: Positive = Field(description="Vn = this × Fy tw Lcf sin 2α.")
    angleCoefficient: Positive = Field(description="Eq 6.10.308: h³ / (this × Ic L).")
    aspectMin: Positive = Field(description="L/h above this.")
    aspectMax: Positive = Field(description="L/h at most this.")
    inertiaCoefficient: Positive = Field(description="Ic ≥ this × tw h⁴ / L.")
    hbeBracing: Positive = Field(description="HBE braced at most this × ry E / Fy.")
    hbeBraceShare: Positive = Field(description="HBE brace strength: this × Fy bf tf.")
    connectionFactor: Positive = Field(description="HBE-to-VBE shear: moments this × Ry Mp.")
    note: str = ""


class SteelSeismicTies(_Group):
    """Transverse ties of concrete-encased composite columns of one seismic system level."""

    spacingLeastShare: float | None = Field(default=None, gt=0, description="× least side.")
    spacingBarDiameters: float | None = Field(default=None, gt=0, description="× bar db.")
    spacingTieDiameters: float | None = Field(default=None, gt=0, description="× tie db.")
    spacingMax: float | None = Field(default=None, gt=0, description="[mm]")
    tieGreatestShare: float | None = Field(default=None, gt=0, description="Tie db ≥ × side.")
    tieMin: float | None = Field(default=None, gt=0, description="Tie db at least [mm].")
    tieMax: float | None = Field(default=None, gt=0, description="Tie db need not exceed [mm].")
    zoneHeightShare: float | None = Field(default=None, gt=0, description="End zone × clear H.")
    zoneMin: float | None = Field(default=None, gt=0, description="End zone at least [mm].")
    remainderFactor: float | None = Field(default=None, gt=0, description="Elsewhere × that.")
    ashCoefficient: float | None = Field(default=None, gt=0, description="Eq 6.13.27.")
    confinedLeastShare: float | None = Field(default=None, gt=0, description="C-SMF ends.")
    confinedMax: float | None = Field(default=None, gt=0, description="C-SMF ends [mm].")
    crossTieSpacing: float | None = Field(default=None, gt=0, description="Across [mm].")
    bracedAxialShare: float | None = Field(default=None, gt=0, description="× Po: full length.")
    discontinuityShare: float | None = Field(default=None, gt=0, description="× Po.")
    footingExtension: float | None = Field(default=None, gt=0, description="[mm]")
    note: str = ""


class SteelSeismicCompositeWall(_Group):
    """Composite steel plate shear walls."""

    shearCoefficient: Positive = Field(description="Vns = this × As Fy.")
    phi: Phi = Field(description="φ of the plate's shear (the clause gives none).")
    concreteBothSides: Positive = Field(description="Concrete each side at least [mm].")
    concreteOneSide: Positive = Field(description="Concrete on one side at least [mm].")
    ratioMin: Positive = Field(description="Bars each way at least this ratio.")
    spacingMax: Positive = Field(description="Bars at most this apart [mm].")
    note: str = ""


class SteelSeismicComposite(_Group):
    """Composite members of the seismic load resisting system."""

    concreteMin: Positive = Field(description="f'c at least [MPa].")
    concreteMaxNormal: Positive = Field(description="f'c for strength at most, normal [MPa].")
    concreteMaxLight: Positive = Field(description="... lightweight [MPa].")
    steelShareMin: Share = Field(description="Steel at least this share of the section.")
    shearPhi: Phi = Field(description="φ of the encased column's shear.")
    connectorSpacingMax: Positive = Field(description="Shear connectors at most [mm].")
    levels: dict[str, Literal["ordinary", "intermediate", "special"]] = Field(
        description="Frame or braced kind -> the seismic system level of its composite members."
    )
    ordinary: SteelSeismicTies
    intermediate: SteelSeismicTies
    special: SteelSeismicTies
    beamStrain: Positive = Field(description="Eq 6.13.26: (Ycon + db) / (1 + this Fy / Es).")
    filledWall: Positive = Field(
        description="Filled rectangular HSS in SMF: t ≥ b √(Fy/(this Es))."
    )
    plateWall: SteelSeismicCompositeWall
    note: str = ""


class SteelSeismicTable(TableModel):
    """Seismic provisions for structural steel buildings: when they apply, the expected
    strengths, seismically compact sections, column strength, splices and bases, and the
    moment frames (special, intermediate, ordinary, special truss)."""

    trigger: SteelSeismicTrigger
    systems: dict[str, str] = Field(
        description="Structural system id -> the frame kind of ``frames`` its members follow."
    )
    omegaDefault: Positive = Field(description="Ω0 when the system gives none.")
    expected: SteelSeismicExpectedTable
    toughness: SteelSeismicToughness
    widthThickness: SteelSeismicWidthThickness
    #: Alpha 9 C3: the moderately ductile limits (None: the highly ductile ones are used).
    widthThicknessModerate: SteelSeismicWidthThickness | None = None
    columns: SteelSeismicColumns
    splices: SteelSeismicSplices
    bases: SteelSeismicBases
    frames: dict[str, SteelSeismicFrame]
    truss: SteelSeismicTruss
    connections: SteelSeismicConnections
    practice: SteelSeismicPractice
    # B38: braced frames, plate walls and composite seismic members (None: not covered).
    bracedSystems: dict[str, str] = Field(
        default_factory=dict,
        description="Structural system id -> the braced frame or wall kind (scbf, ocbf, ebf, "
        "brbf, spsw) its braces, links and walls follow.",
    )
    concentric: dict[str, SteelSeismicConcentric] | None = Field(
        default=None, description="Concentrically braced frames by kind (scbf, ocbf)."
    )
    eccentric: SteelSeismicEccentric | None = None
    restrained: SteelSeismicRestrained | None = None
    plateWalls: SteelSeismicPlateWalls | None = None
    compositeSeismic: SteelSeismicComposite | None = None


# ─────────────────────────── nonlinear time history analysis (B36) ───────────────────────────


class NonlinearHistoryProcedure(_Row):
    """How the nonlinear time histories are run and read (``fem.nonlinear_history``)."""

    target: str = Field(
        default="nonlinear",
        description="The ``seismic.timeHistory.targets`` entry the records are scaled to (its R "
        "and I; the period range, ratios and least number of records of that table apply).",
    )
    meanFrom: int = Field(
        ge=1,
        description="From this many records (or pairs) the design value is the mean of their "
        "peak responses, with fewer the largest.",
    )
    scaleToStaticShear: bool = Field(
        default=False,
        description="Whether the responses are scaled up to the equivalent static base shear "
        "(the nonlinear results are used as they come when false).",
    )
    pDelta: bool = Field(default=True, description="P-Delta effects in the columns and walls.")
    designReview: bool = Field(
        default=False, description="The code asks for an independent design review."
    )
    note: str = Field(default="", description="Why the values are what they are.")


class NonlinearHistoryDrift(_Row):
    """The storey drift of the nonlinear time histories against the allowable drift of the
    linear procedures (the pack's ``seismic`` drift table, with its redundancy rule)."""

    limitFactor: Positive = Field(
        description="The drift may reach this × the allowable storey drift of the linear "
        "procedures."
    )
    amplify: bool = Field(
        default=False,
        description="Whether the drifts are multiplied by Cd/I (false: the nonlinear drifts "
        "are the real ones).",
    )
    note: str = Field(default="", description="Why the values are what they are.")


class NonlinearHistoryAcceptance(_Row):
    """Acceptance of the members over the records (``fem.acceptance``). Method
    ``fibreStrain``: each fibre's peak strain at the member's end sections against a share of
    the strain at which its material fails."""

    method: Literal["fibreStrain"] = Field(
        description="Method id (the engine's generic implementation)."
    )
    deformationShare: Share = Field(
        description="A member's deformation may reach at most this × the deformation at which "
        "it fails."
    )
    residualStrengthShare: Share = Field(
        description="Strength (share of the peak) below which the component has failed."
    )
    gravityLossAllMembers: bool = Field(
        default=True,
        description="The smaller of the gravity-loss and the strength-loss deformation for "
        "every member (false: the gravity loss only for members carrying gravity loads).",
    )
    reinforcementFractureStrain: Positive = Field(
        description="Strain at which a reinforcing bar is taken as lost (fracture or buckling)."
    )
    steelFractureStrain: Positive = Field(
        description="Strain at which a structural steel fibre is taken as lost."
    )
    note: str = Field(default="", description="Why the values are what they are.")


class NonlinearHistoryTable(TableModel):
    """Nonlinear time history analysis: the procedure, the drift limit and the acceptance of
    the members."""

    procedure: NonlinearHistoryProcedure
    drift: NonlinearHistoryDrift
    acceptance: NonlinearHistoryAcceptance


# ───────────────────────────────── seismically isolated buildings (B37) ─────────────────────────────────


class IsolationDampingPoint(_Row):
    """A row of the damping coefficient table: effective damping [% of critical] -> B."""

    damping: float = Field(ge=0, description="Effective damping βD or βM [%].")
    B: Positive = Field(description="Damping coefficient BD or BM.")


class IsolationSpectrum(_Row):
    """How the isolation displacements read the design spectrum."""

    R: Positive = Field(description="R of the spectrum the displacements are read from.")
    importance: Positive = Field(description="I of that spectrum.")
    mceFactor: Positive = Field(
        description="The maximum considered earthquake spectrum: this × the design spectrum."
    )
    mcePeriod: Literal["design", "maximum", "larger"] = Field(
        description="Period SaM is read at: TD, TM or whichever gives the larger SaM."
    )
    note: str = ""


class IsolationStaticLimits(_Row):
    """Where the equivalent static analysis of an isolated building is permitted."""

    siteClasses: list[str] = Field(description="Site classes it is permitted on.")
    maxStoreys: int = Field(gt=0, description="Storeys above the isolation interface, at most.")
    maxHeight: Positive = Field(description="Height above the isolation interface, at most [m].")
    maxPeriodM: Positive = Field(description="TM at most [s].")
    periodRatio: Positive = Field(description="TD greater than this × the fixed-base period.")
    stiffnessRatio: Share = Field(
        description="Effective stiffness at DD greater than this × that at stiffnessAtShare·DD."
    )
    stiffnessAtShare: Share = Field(description="Share of DD of the stiffness comparison.")


class IsolationRestoring(_Row):
    """The lateral restoring force: F(DTD) - F(atShare·DTD) at least forceShare·W."""

    forceShare: Positive
    atShare: Share


class IsolationForces(_Row):
    """The forces above (Vs) and below (Vb) the isolation system."""

    importance: Positive = Field(description="Importance factor of isolated buildings.")
    reductionShare: Positive = Field(description="RI = reductionShare × R, ...")
    reductionMax: Positive = Field(description="... at most this ...")
    reductionMin: Positive = Field(description="... and need not be less than this.")
    activationFactor: Positive = Field(
        description="Vs at least this × the force that fully activates the isolation system."
    )
    fixedBaseR: Literal["isolated", "system"] = Field(
        description="R of the fixed-base minimum force at TD: RI ('isolated') or the system's R."
    )
    note: str = ""


class IsolationDistribution(_Row):
    exponent: float = Field(ge=0, description="Fx = Vs·wx·hx^k / Σ wi·hi^k with this k.")


class IsolationDrift(_Row):
    """Storey drift limits above the isolation system, as a share of the storey height."""

    static: Share
    spectrum: Share
    history: Share


class IsolationSpectrumAnalysis(_Row):
    maxModalDamping: Positive = Field(description="Fundamental modal damping at most [%].")
    orthogonalShare: Share = Field(description="Share of the perpendicular ground motion.")
    dampedFromShare: Share = Field(
        description="The damped spectrum applies from this × TD up (practice, see note)."
    )
    note: str = ""


class IsolationHistory(_Row):
    """Ground motions of the time-history option (Sec 2.5.16.3.2)."""

    minRecords: int = Field(gt=0, description="Pairs of records, at least.")
    averageFrom: int = Field(gt=0, description="With this many or more, the average is used.")
    periodFromShare: Positive = Field(description="Scaling range from this × TD ...")
    periodToShare: Positive = Field(description="... to this × TM.")
    spectrumFactor: Positive = Field(description="Average SRSS spectrum at least this × design.")
    tolerance: Share = Field(description="By more than this share it may not fall below.")
    recordDamping: Share = Field(description="Damping of the record spectra.")


class IsolationOverturning(_Row):
    minimumFactor: Positive


class IsolationTorsion(_Row):
    method: Literal["rigidDeck"] = Field(description="Method id of the total displacements.")
    note: str = ""


class IsolationTestStep(_Row):
    share: Positive
    of: Literal["DD", "DM", "DTD", "DTM"]
    cycles: int = Field(gt=0)


class IsolationTesting(_Row):
    liveShare: Share = Field(description="Test vertical load: dead load + this × live load.")
    windCycles: int = Field(gt=0, description="Cycles at the wind design force.")
    steps: list[IsolationTestStep]


class IsolationRequirement(_Row):
    id: str
    text: str
    check: Literal["computed", "bounds", "tests", "manual"] = Field(
        description="How SAEngine treats it: computed, from the property bounds, by the "
        "prototype tests, or a manual item for the engineer."
    )


class IsolationTable(TableModel):
    """Seismically isolated buildings: damping coefficients, the static analysis limits, the
    forces, the drift limits, the dynamic analysis rules, the tests and the review."""

    dampingCoefficients: list[IsolationDampingPoint] = Field(min_length=2)
    spectrum: IsolationSpectrum
    staticLimits: IsolationStaticLimits
    restoring: IsolationRestoring
    forces: IsolationForces
    distribution: IsolationDistribution
    drift: IsolationDrift
    spectrumAnalysis: IsolationSpectrumAnalysis
    history: IsolationHistory
    overturning: IsolationOverturning
    torsion: IsolationTorsion
    testing: IsolationTesting
    requirements: list[IsolationRequirement]
    review: list[str]


# ───────────────────────────────────────── bamboo (B39) ─────────────────────────────────────────

BambooGroupId = Literal["A", "B", "C"]


class BambooSpecies(_Row):
    """A species of the code's safe working stresses table (green condition) [MPa]."""

    name: str = Field(description="Botanical name (with synonyms) as the code prints it.")
    group: BambooGroupId
    bending: Positive = Field(description="Extreme fibre stress in bending [MPa].")
    E: Positive = Field(description="Permissible modulus of elasticity [MPa].")
    compression: Positive = Field(description="Allowable compressive stress [MPa].")


class BambooGroupLimit(_Group):
    """Least modulus of rupture and E of a group (green condition) [MPa]."""

    rupture: Positive
    E: Positive


class BambooDensityFactors(_Group):
    """Allowable long-term stress per unit density [MPa per kg/m³]; none: not given."""

    compression: Positive
    bending: Positive
    shear: Positive | None = None


class BambooSafetyFactors(_Group):
    """Factors of safety from the ultimate (tested) values to the permissible ones."""

    bending: Positive
    E: Positive
    compression: Positive


class BambooDuration(_Group):
    """Factors on the permissible stresses by load duration."""

    continuous: Positive
    medium: Positive = Field(description="Imposed (live) or medium term loading.")
    short: Positive = Field(description="Short-term loading (wind, earthquake).")


class BambooColumn(_Group):
    maxSlenderness: Positive = Field(description="Largest l/r of members in compression.")
    inertiaFactor: Share = Field(description="Share of I in the Euler buckling load (taper).")
    initialCurvature: Positive = Field(
        description="Initial bow as a share of the length (the grading's largest curvature)."
    )


class BambooJointKind(_Row):
    label: str
    group: Literal["lengthening", "bearing", "modern"]


class BambooFastening(_Row):
    label: str
    wireDiameter: Positive | None = Field(default=None, description="[mm]")
    pinDiameter: Positive | None = Field(default=None, description="[mm]")
    plateThickness: Positive | None = Field(
        default=None, description="Least hardwood splice plate [mm]."
    )
    plywoodThickness: Positive | None = Field(
        default=None, description="Least structural plywood plate [mm]."
    )


class BambooJoints(_Group):
    kinds: dict[str, BambooJointKind] = Field(min_length=1)
    fastenings: dict[str, BambooFastening] = Field(min_length=1)
    capacity: Literal["tested"] = Field(
        default="tested", description="Joint capacities come from full-scale tests."
    )


class BambooTable(TableModel):
    """Permissible stress design of round bamboo members: safe working stresses by species, by
    density or from tests with the factors of safety, load duration factors, columns (Euler
    with a reduced I, slenderness limit, initial curvature), truss force increase and the
    joints, whose capacities come from tests. ``clauses``: the clause of each check."""

    method: Literal["permissibleStress"] = "permissibleStress"
    species: dict[str, BambooSpecies] = Field(min_length=1)
    groupLimits: dict[BambooGroupId, BambooGroupLimit]
    densityFactors: dict[Literal["green", "airDry"], BambooDensityFactors]
    safetyFactors: BambooSafetyFactors
    duration: BambooDuration
    column: BambooColumn
    trussForceIncrease: float = Field(ge=1, description="Truss compression and joint forces ×.")
    minWallThickness: Positive = Field(description="Least wall of load-bearing culms [mm].")
    joints: BambooJoints
    clauses: dict[str, str] = Field(default_factory=dict)


# ─────────────────────────────────────── ferrocement (B39) ───────────────────────────────────────

FerrocementMeshId = Literal["wovenSquare", "weldedSquare", "hexagonal", "expanded"]
FerrocementExposure = Literal["noncorrosive", "corrosive", "waterRetaining"]


class FerrocementEfficiency(_Group):
    """Global efficiency factor η by the loading direction."""

    longitudinal: float = Field(ge=0, le=1)
    transverse: float = Field(ge=0, le=1)
    diagonal: float = Field(ge=0, le=1)


class FerrocementMesh(_Row):
    """A reinforcement type: design yield strength and effective moduli [MPa], η, and how its
    volume fraction is found (``wires``: from the wire diameter and spacings; ``weight``: from
    the mesh weight per unit area)."""

    label: str
    fy: Positive
    Erl: Positive = Field(description="Effective modulus, longitudinal [MPa].")
    Ert: Positive | None = Field(default=None, description="Effective modulus, transverse.")
    eta: FerrocementEfficiency
    volumeFraction: Literal["wires", "weight"] = "wires"


class FerrocementStrength(_Group):
    strainLimit: Positive = Field(description="Mortar strain at the extreme fibre.")
    stressBlock: Share = Field(description="Stress of the rectangular block × f'c.")
    compressionShare: Share = Field(description="Uniform compression × f'c (mortar alone).")
    phiFlexure: str = Field(description="Key of the factors table's φ: tension-controlled.")
    phiCompression: str = Field(description="Key of the factors table's φ: compression.")
    fyMax: Positive = Field(description="Largest design yield strength of the mesh [MPa].")
    efficiencyThickness: Positive = Field(
        description="η of the table only for sections this thick or less [mm]."
    )


class FerrocementService(_Group):
    steelShare: Share = Field(description="Allowable mesh tension × fy.")
    liquidRetaining: Positive = Field(description="Allowable mesh tension, liquid retaining.")
    mortarShare: Share = Field(description="Allowable mortar compression × f'c.")


class FerrocementDetailing(_Group):
    coverWireFactor: Positive = Field(description="Cover about this × the wire diameter.")
    thinSection: Positive = Field(description="Thinner than this [mm]: the thin-section cover.")
    thinCover: Positive = Field(description="Cover of thin sections [mm].")
    minLayers: int = Field(ge=1)
    waterVolumeFraction: Share = Field(description="Least Vf, water retaining.")
    waterSpecificSurface: Positive = Field(description="Least Sr [mm²/mm³], water retaining.")
    skeletalShare: Share = Field(description="Skeletal steel at most this × the thickness.")
    minMortarStrength: Positive = Field(description="f'c for most applications [MPa].")


class FerrocementDesignAid(_Group):
    """Mn / (f'c b h² η) = a + b X - c X², X = Vf fy / f'c."""

    a: float
    b: float
    c: float


class FerrocementTable(TableModel):
    """Ferrocement members: the mesh types (yield strength, effective moduli, η), strength
    design of the layered section, service load stresses, crack width and fatigue limits, the
    detailing rules and the design aid. ``clauses``: the clause of each check."""

    method: Literal["layeredSection"] = "layeredSection"
    meshes: dict[FerrocementMeshId, FerrocementMesh]
    bars: FerrocementMesh
    strength: FerrocementStrength
    service: FerrocementService
    crackWidth: dict[FerrocementExposure, Positive]
    fatigue: dict[Literal["oneMillion", "twoMillion"], Positive]
    detailing: FerrocementDetailing
    designAid: FerrocementDesignAid
    steelUnitWeight: Positive = Field(description="[kN/m³], for Vf from the mesh weight.")
    clauses: dict[str, str] = Field(default_factory=dict)


class CitationsTable(TableModel):
    """The clause references the documents print: the calculation report, its worksheets, the
    drawings and the bill of quantities (``clauses``, without the code's name; read by
    :mod:`saengine.codes.citations`). A key the pack does not give is not cited."""


# ───────────────────────────── MEP openings through the structure (D5) ─────────────────────────────


class MepOpeningsTable(TableModel):
    """The code rules the checks of the openings and sleeves MEP cuts through beams, slabs and
    walls read (``saengine.mep.openings``) besides the ``slabMethods.openings`` shares and the
    ``concrete.walls`` layers: the column strip width, the punching zone, the trim bars, and the
    clause of each check. A pack without it does not cover these checks."""

    columnStripShare: Share = Field(
        description="Column strip each side of a column line: this x the shorter span."
    )
    punchingDistance: PosNum = Field(
        description="An opening nearer a column than this x the slab thickness cuts b0."
    )
    trimBar: PosNum = Field(description="Trim bars around a wall opening [mm].")
    trimBars: tuple[Annotated[int, Field(ge=1)], Annotated[int, Field(ge=1)]] = Field(
        description="Trim bars a side: walls with two layers, walls with one."
    )
    clauses: dict[str, str] = Field(default_factory=dict, description="Check -> clause.")


# ───────────────────────────── C4: snow on roofs ─────────────────────────────


class SnowExposure(_Row):
    description: str
    Ce: Positive = Field(description="Exposure coefficient Ce.")


class SnowSlopeRow(BaseModel):
    """The roof slope factor Cs of roofs whose thermal factor is at most ``ctMax``: 1 up to
    ``slipperyStart`` [°] (unobstructed slippery roofs) or ``otherStart`` (other roofs), then
    linear to 0 at ``end``."""

    model_config = ConfigDict(extra="forbid")

    ctMax: Positive
    slipperyStart: float = Field(ge=0)
    otherStart: float = Field(ge=0)
    end: Positive


class SnowMinimum(BaseModel):
    """The minimum snow load of low-slope roofs (slope below ``slopeMax`` [°]): ``share`` ×
    pg (× Is) where pg ≤ ``groundLimit``, else ``value`` (× Is) [kN/m²]."""

    model_config = ConfigDict(extra="forbid")

    slopeMax: Positive
    share: Positive
    groundLimit: Positive
    value: Positive


class SnowDensity(BaseModel):
    """Snow density γ = ``factor``·pg + ``constant`` ≤ ``maximum`` [kN/m³], pg in kN/m²."""

    model_config = ConfigDict(extra="forbid")

    factor: float = Field(ge=0)
    constant: float = Field(ge=0)
    maximum: Positive


class SnowDriftRule(BaseModel):
    """The drift at a roof step (method id, :func:`saengine.fem.snow.drift`).

    ``windParameter``: hd = coefficient·(pg^a · lu^b · W2^c / γ)^power in the units of the
    method's equation (``units`` imperial: ft, psf, pcf); the windward drift is
    ``windwardShare`` × that of the lower roof's length; the drift's width w = ``widthFactor``
    hd, where hd > hc: hd = hc and w = widthFactor·hd²/hc ≤ ``widthMax``·hc. ``minLength``:
    lu taken at least this [m]; ``windParameter``: W2 when the project gives none."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["windParameter"] = "windParameter"
    units: Literal["imperial", "si"] = "imperial"
    coefficient: Positive
    groundExponent: Positive
    lengthExponent: Positive
    windExponent: Positive
    power: Positive
    windwardShare: Share
    widthFactor: Positive
    widthMax: Positive
    minLength: float = Field(default=0.0, ge=0)
    windParameter: Positive | None = None


class SnowTable(TableModel):
    """Snow on roofs from the snow load on the ground (:mod:`saengine.fem.snow_load`; C4, C1):
    s = ``factor``·(roof factor)·Ce·Ct·Is·sg on the roof, sg the ground snow load the project
    gives (Site > Snow). The roof factor is a method id (``method``):

    - ``shapeCoefficient`` (EN 1991-1-3 5.2(3)a): μ1 by the roof's pitch (``shape``: (angle
      [°], μ1) points, linear between, the end values outside);
    - ``slopeFactor`` (ASCE 7-22 7.4): Cs by the roof's pitch from the first ``slope`` row
      whose ``ctMax`` holds Ct (slippery or other roofs), the low-slope minimum ``minimum``
      governing where larger.

    Ce by the exposure of the site (and of the roof, in the ids of codes that combine them),
    Ct the thermal coefficient, Is by the occupancy (risk) category where the code has one
    (``importance``). ``loadCase``: Lr (with ``withRoofLive`` "envelope": the larger of the roof
    live load and the snow; imposed loads on roofs need not act with snow) or S (its own case,
    "separate"; the combinations take it as "Lr or S"). ``drift``: the drift at a roof step by
    its method id (reported, not applied); ``density`` the snow's unit weight. A pack without
    it does not cover snow."""

    method: Literal["shapeCoefficient", "slopeFactor"] = "shapeCoefficient"
    exposures: dict[str, SnowExposure]
    defaultExposure: str
    thermal: Positive = Field(default=1.0, description="Ct where the project gives none.")
    factor: Positive = Field(
        default=1.0,
        description="A code's constant factor on the roof snow (1.0 in EN 1991-1-3; 0.7 of the "
        "flat roof snow load in ASCE 7).",
    )
    shape: list[tuple[float, float]] = Field(
        default_factory=list, description="(roof angle °, μ1) (shapeCoefficient)."
    )
    slope: list[SnowSlopeRow] = Field(
        default_factory=list, description="The roof slope factor Cs by Ct (slopeFactor)."
    )
    minimum: SnowMinimum | None = Field(
        default=None, description="The minimum snow load of low-slope roofs (slopeFactor)."
    )
    importance: dict[str, Positive] = Field(
        default_factory=dict,
        description="Is by occupancy (risk) category; empty: none (1.0).",
    )
    loadCase: Literal["Lr", "S"] = "Lr"
    withRoofLive: Literal["envelope", "separate"] = "envelope"
    exceptionalFactor: Positive | None = Field(
        default=None, description="Cesl of the exceptional snow load (accidental; reported)."
    )
    density: SnowDensity | None = None
    drift: SnowDriftRule | None = None
    seismicShare: Share | None = Field(
        default=None, description="Share of the roof snow in the seismic weight..."
    )
    seismicThreshold: Positive | None = Field(
        default=None, description="... where the flat roof snow is above this [kN/m²]."
    )

    @model_validator(mode="after")
    def _exposure(self) -> SnowTable:
        if self.defaultExposure not in self.exposures:
            raise ValueError(f"defaultExposure '{self.defaultExposure}' is not an exposure")
        if self.method == "shapeCoefficient" and not self.shape:
            raise ValueError("shapeCoefficient: the method needs its shape points")
        if self.method == "slopeFactor" and not self.slope:
            raise ValueError("slopeFactor: the method needs its slope rows")
        return self


# Alpha 9 C5: the partial-factor concrete and geotechnical methods (their own module).
# Alpha 9 C9: steel by limit state design with partial factors and buckling curves.
from saengine.codes.limit_state_tables import SteelLimitStateTable
from saengine.codes.method_tables import (
    ConcreteMethodsTable,
    GeotechnicalMethodsTable,
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
    "fatigue": FatigueTable,
    "siteInvestigation": SiteInvestigationTable,
    "serviceability": ServiceabilityTable,
    "nonstructural": NonstructuralTable,
    "steelStability": SteelStabilityTable,
    "flood": FloodTable,
    "pushover": PushoverTable,
    "accessibility": AccessibilityTable,
    "anchors": AnchorsTable,
    "construction": ConstructionTable,
    "concreteTime": ConcreteTimeTable,
    "composite": CompositeTable,
    "slabMethods": SlabMethodsTable,
    "wallMethods": WallMethodsTable,
    "stairMethods": StairMethodsTable,
    "compositeConcrete": CompositeConcreteTable,
    "steelSeismic": SteelSeismicTable,
    "isolation": IsolationTable,
    "nonlinearHistory": NonlinearHistoryTable,
    "bamboo": BambooTable,
    "ferrocement": FerrocementTable,
    "citations": CitationsTable,
    "mepOpenings": MepOpeningsTable,
    "snow": SnowTable,
    # Alpha 9 C5.
    "concreteMethods": ConcreteMethodsTable,
    "geotechnicalMethods": GeotechnicalMethodsTable,
    # Alpha 9 C9.
    "steelLimitState": SteelLimitStateTable,
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


def _default_pack_id() -> str:
    from saengine.codes.registry import DEFAULT_PACK  # the registry imports no tables

    return DEFAULT_PACK


@cache
def builtin_table(name: str, pack_id: str = "") -> Any:
    """Table ``name`` of a built-in root pack (no inheritance), validated; read once; ``pack_id``
    empty: the default pack (:data:`saengine.codes.registry.DEFAULT_PACK`).

    :mod:`saengine.library.code_data` reads the default pack through this, without loading
    packs through the registry."""
    pack_id = pack_id or _default_pack_id()
    path = PACKS_DIR / pack_id / "data" / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "$data" in raw:
        raw = raw["$data"]
    return validate_table(name, raw)


@cache
def builtin_manifest(pack_id: str = "") -> dict[str, Any]:
    pack_id = pack_id or _default_pack_id()
    return json.loads((PACKS_DIR / pack_id / "pack.json").read_text(encoding="utf-8"))


def _register_with_registry() -> None:
    try:
        from saengine.codes.registry import register
    except ImportError:  # the registry is optional for the readers of the built-in pack
        return
    register_all(register)


_register_with_registry()


# ─────────────────────── designClauses (clause references of saengine.design) ───────────────────────


class DesignClausesTable(TableModel):
    """Clause references of the member and connection design (``saengine.design``), grouped by
    module: ``clauses.<group>.<key>`` is the clause without the code's name (the design puts the
    pack's display name before it). ``shortName``: the code's name in compact notes (e.g.
    "<short> 6.1.4.3"). A pack without this table names only itself in the design notes."""

    shortName: str = Field(default="", description="The code's short name in compact notes.")
    # C2: a pack that bundles codes, or keeps another code's method, names it per group or key.
    shortNames: dict[str, str] = Field(
        default_factory=dict,
        description="The short name of the code of a group ('slab') or one key ('slab.twoWay') "
        "where it is not shortName's.",
    )
    clauses: dict[str, dict[str, str]] = Field(
        default_factory=dict, description="Clause reference of each check: {group: {key: clause}}."
    )


TABLE_MODELS["designClauses"] = DesignClausesTable


def _register_design_clauses() -> None:
    try:
        from saengine.codes.registry import register
    except ImportError:  # the registry is optional for the readers of the built-in pack
        return
    register("designClauses", DesignClausesTable, MERGE_KEYS.get("designClauses"))


_register_design_clauses()


# ──────────────────── designLimits (code values of saengine.design not in other tables) ────────────────────


class StairGeometryLimits(_Group):
    """Stair geometry rules: 2R + T, the (riser, tread) table, flight rise, headroom, riser
    variation and the landing cap [mm]."""

    twoRiserTread: tuple[Positive, Positive] = Field(description="(least, largest) 2R + T [mm].")
    riserTread: list[tuple[Positive, Positive]] = Field(
        description="(riser, tread) combinations the code lists [mm]."
    )
    riserTreadSkip: list[tuple[Positive, Positive]] = Field(
        default_factory=list,
        description="Rows of riserTread left out of the nearest-row search (misprints) [mm].",
    )
    flightRiseMax: Positive = Field(description="Largest rise of a flight between landings [mm].")
    flightRiseMaxAssembly: Positive = Field(description="... in assembly buildings [mm].")
    headroom: Positive = Field(description="Clear headroom between flights [mm].")
    headroomReduced: Positive = Field(
        description="Reduced headroom for not more than three flights in a staircase [mm]."
    )
    riserVariation: Positive = Field(
        description="Largest variation between adjacent risers or treads [mm]."
    )
    straightLandingCap: Positive = Field(
        description="Width in the travel direction a landing of a straight run need not exceed [mm]."
    )
    widthResidential: Positive = Field(description="Least stair width, residential [mm].")
    widthEducational: Positive = Field(description="... educational, up to the occupants [mm].")
    widthEducationalLarge: Positive = Field(description="... educational, more occupants [mm].")
    educationalOccupants: int = Field(gt=0, description="Occupants of the educational rows.")
    widthHealthcare: Positive = Field(description="... hospital patient areas [mm].")
    widthHealthcareStaff: Positive = Field(description="... hospital staff areas [mm].")


class DesignLimitsTable(TableModel):
    """Code values of the member design that no other table holds: the cap of √f'c in shear
    and torsion, the design wall thickness factor of ERW hollow sections, and the stair
    geometry rules. A pack without it does not cover the checks that read it."""

    shearRootFcMax: Positive = Field(description="Cap of √f'c in shear and torsion [MPa].")
    erwWallFactor: Share = Field(
        description="Design wall thickness of electric-resistance-welded HSS over the nominal."
    )
    stairs: StairGeometryLimits


TABLE_MODELS["designLimits"] = DesignLimitsTable


def _register_design_limits() -> None:
    try:
        from saengine.codes.registry import register
    except ImportError:  # the registry is optional for the readers of the built-in pack
        return
    register("designLimits", DesignLimitsTable, MERGE_KEYS.get("designLimits"))


_register_design_limits()
