"""Reference data of the default code pack (:data:`saengine.codes.registry.DEFAULT_PACK`): loads.

A compatibility layer over the built-in default code pack: the names and values are read once
from the pack's data tables (:func:`saengine.codes.tables.builtin_table`). They give the
settings editors their lists (towns, area uses, structural systems) and the defaults of new
projects. Code that should follow the project's chosen pack reads
``saengine.codes.registry.active(settings).table(...)`` (or
:func:`saengine.codes.context.table`) instead.

Each table names the clause or table it comes from (in the pack's ``source``/``sources``). The
values are the code's defaults for the project settings; the engineer can override every one of
them, and should check them against the edition of the code that governs the project.

Units: kN/m² (kPa) for area loads, m/s for wind speeds.
"""

from __future__ import annotations

from typing import NamedTuple

from saengine.codes.registry import DEFAULT_PACK
from saengine.codes.tables import builtin_manifest, builtin_table

#: The built-in pack this module reads.
PACK_ID = DEFAULT_PACK

EDITION: str = builtin_manifest(PACK_ID)["edition"]


class Location(NamedTuple):
    name: str
    #: Seismic zone (Table 6.2.14 / Figure 6.2.24, seismic zoning map of Bangladesh).
    zone: int
    #: Basic wind speed, 3-second gust at 10 m, 50-year return period [m/s] (Table 6.2.8).
    wind_speed: float


class OccupancyCategory(NamedTuple):
    description: str
    #: Seismic importance factor I (Table 6.2.17).
    seismic_importance: float
    #: Wind importance factor I (Table 6.2.9).
    wind_importance: float


class AreaUse(NamedTuple):
    name: str
    #: Minimum uniformly distributed live load [kN/m²] (Table 6.2.3).
    live: float


class StructuralSystem(NamedTuple):
    name: str
    #: Response reduction factor R, overstrength factor Ω0 and deflection amplification Cd
    #: (Table 6.2.19).
    r: float
    omega: float
    cd: float


class SiteFactors(NamedTuple):
    #: Soil factor S and the corner periods of the normalized spectrum TB, TC, TD [s]
    #: (Table 6.2.16).
    s: float
    tb: float
    tc: float
    td: float


class ExposureProfile(NamedTuple):
    #: Power-law exponent α and gradient height zg [m] of the velocity pressure profile.
    alpha: float
    zg: float


_locations = builtin_table("locations", PACK_ID)
_zones = builtin_table("zoneCoefficients", PACK_ID)
_occupancy = builtin_table("occupancyCategories", PACK_ID)
_area = builtin_table("areaLoads", PACK_ID)
_combinations = builtin_table("combinations", PACK_ID)
_seismic = builtin_table("seismic", PACK_ID)
_wind = builtin_table("wind", PACK_ID)

#: Seismic zone coefficient Z by zone (Table 6.2.14).
ZONE_COEFFICIENT: dict[int, float] = dict(_zones.zones)

#: District towns and their seismic zone and basic wind speed (Tables 6.2.8 and 6.2.15).
LOCATIONS: dict[str, Location] = {
    k: Location(v.name, v.zone, v.windSpeed) for k, v in _locations.locations.items()
}

#: Occupancy categories of buildings (Table 6.1.1).
OCCUPANCY_CATEGORIES: dict[str, OccupancyCategory] = {
    k: OccupancyCategory(v.description, v.seismicImportance, v.windImportance)
    for k, v in _occupancy.categories.items()
}

#: Minimum uniformly distributed live loads by use of the floor area (Table 6.2.3, selection).
AREA_USES: dict[str, AreaUse] = {k: AreaUse(v.name, v.live) for k, v in _area.uses.items()}

#: Structural systems (Table 6.2.19).
STRUCTURAL_SYSTEMS: dict[str, StructuralSystem] = {
    k: StructuralSystem(v.name, v.R, v.Omega0, v.Cd) for k, v in _seismic.systems.items()
}

#: Site classes (Table 6.2.13, abridged from its descriptions and average properties of the top
#: 30 m), from the soil profile of the soil report. S1 (soft clays/silts with PI > 40, at least
#: 10 m thick) and S2 (liquefiable soils, sensitive clays) need site-specific studies (Sec
#: 2.5.3.1); the soil report flags them, the settings keep SA-SE.
SITE_CLASSES: dict[str, str] = {k: v.description for k, v in _seismic.siteClasses.items()}

#: Wind exposure categories: A - urban and suburban, B - open terrain, C - flat unobstructed
#: areas and water surfaces, including coastal belts.
EXPOSURES: dict[str, str] = {k: v.description for k, v in _wind.exposures.items()}

#: Load cases of a building (2.1, 2.2.2): dead, superimposed dead, live, roof live, wind and
#: earthquake in the two plan directions.
LOAD_CASES: dict[str, str] = dict(_combinations.loadCases)

#: Strength design load combinations (2.7.3): (name, factors). D includes superimposed dead load.
STRENGTH_COMBINATIONS: list[tuple[str, dict[str, float]]] = [
    (c.name, dict(c.factors)) for c in _combinations.strength
]


# ───────────────────────── equivalent static lateral forces ─────────────────────────

SITE_FACTORS: dict[str, SiteFactors] = {
    k: SiteFactors(v.S, v.TB, v.TC, v.TD) for k, v in _seismic.siteClasses.items()
}

#: Approximate period T = Ct·hn^m, hn in metres (Table 6.2.20): by system family.
PERIOD_COEFFICIENTS: dict[str, tuple[float, float]] = {
    k: (v.Ct, v.m) for k, v in _seismic.periodCoefficients.items()
}

#: The period family of each structural system in STRUCTURAL_SYSTEMS (systems without one use
#: "other").
SYSTEM_PERIOD_FAMILY: dict[str, str] = {
    k: v.periodFamily for k, v in _seismic.systems.items() if v.periodFamily
}

#: Damping correction factor η for 5 % damping.
DAMPING_ETA: float = _seismic.dampingEta

#: Share of the floor live load in the seismic weight W: 25 % for ordinary floors.
SEISMIC_LIVE_SHARE: float = _seismic.liveShare

#: Velocity pressure exposure profiles by exposure category (Table 6.2.11).
EXPOSURE_PROFILES: dict[str, ExposureProfile] = {
    k: ExposureProfile(v.alpha, v.zg) for k, v in _wind.exposures.items()
}

#: Wind directionality factor Kd for buildings (Table 6.2.12) and topographic factor Kzt.
WIND_KD: float = _wind.directionality
WIND_KZT: float = _wind.topographic
#: Gust effect factor G for a rigid building.
WIND_GUST: float = _wind.gust
#: External pressure coefficients of the main wind-force resisting system (Figure 6.2.6):
#: windward wall, and leeward wall by plan aspect L/B.
WIND_CP_WINDWARD: float = _wind.cpWindward
WIND_CP_LEEWARD: tuple[tuple[float, float], ...] = tuple(tuple(p) for p in _wind.cpLeeward)

del _locations, _zones, _occupancy, _area, _combinations, _seismic, _wind
