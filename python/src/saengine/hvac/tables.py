"""BNBC 2020 Part 8 Chapter 2 (air-conditioning) and Part 3 Chapter 4 (energy): the names the
HVAC modules read, served from the code pack's ``hvac`` table
(``saengine/codes/packs/bnbc2020/data/hvac.json``).

Every BNBC value is transcribed from the rendered page of the Bangladesh Gazette edition of
11 February 2021 (``bnbc-2020-part2.pdf`` for Part 8, ``bnbc-2020-part1.pdf`` for Part 3);
``PAGES`` gives the PDF page of each table or clause, the table's ``sources`` the clause of each
entry. Entries the table marks "SAEngine" or "from memory" are not BNBC's: they are documented
assumptions where the code is silent, and the report lists them (``ASSUMPTIONS``) so that the
engineer checks them.

Each name is read from the pack in force where it is used (``T.VENTILATION``, see
:class:`saengine.codes.context.TableNames`); the formulas stay here and in the HVAC modules.

Units: °C, %, l/s, m², W/m², persons per 100 m² as the tables give them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context


@dataclass(frozen=True)
class Station:
    """One row of Table 8.2.2: the outside design conditions of a station [°C].

    ``cooling`` holds (DB, MWB) at 0.4 %, 1 % and 2 % (columns 2-7, note b: for the cooling load);
    ``evaporation`` (WB, MDB) at the same levels (columns 8-13, note c: cooling towers and
    evaporative equipment); ``range`` the mean daily range of the dry bulb (column 14, note d).
    """

    key: str
    name: str
    cooling: dict[str, tuple[float, float]]
    evaporation: dict[str, tuple[float, float]]
    range: float
    #: Site latitude [°N] and longitude [°E] for the sun: from memory, to be checked (BNBC gives
    #: none). Dhaka's 23.7 N 90.4 E is SAEngine's default.
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Inside:
    """One row of Table 8.2.1: acceptable inside design conditions for summer."""

    row: int
    label: str
    db: tuple[float, float]  # dry bulb range [°C]
    rh: tuple[float, float] | None  # relative humidity range [%]; None where printed "--"


@dataclass(frozen=True)
class Ventilation:
    """One row of Table 8.2.3: outdoor air in the breathing zone per person (``perPerson``,
    l/s) and per floor area (``perArea``, l/s per m²), the default occupant density (persons per
    100 m² of net occupiable floor area, note a) and the exhaust rate. None where the table
    prints "-". ``exhaust`` is l/s per m² unless ``exhaustNote`` says otherwise (per room, per
    water closet, per car)."""

    key: str
    label: str
    group: str
    perPerson: float | None
    perArea: float | None
    density: float | None
    exhaust: float | None = None
    exhaustNote: str = ""
    #: Living areas of dwellings: 0.35 air changes per hour but not less than 7.5 l/s a person.
    ach: float | None = None
    #: Row of Table 8.2.1 whose inside conditions apply (SAEngine's choice of the nearest row).
    inside: int | None = None


def _build(t: Any) -> dict[str, Any]:
    """The module's names from the pack's ``hvac`` table, in the shapes the HVAC modules read."""
    stations = {
        key: Station(
            key,
            s.name,
            {level: tuple(v) for level, v in s.cooling.items()},
            {level: tuple(v) for level, v in s.evaporation.items()},
            s.range,
            s.latitude,
            s.longitude,
        )
        for key, s in t.stations.items()
    }
    ventilation = {
        key: Ventilation(
            key,
            v.label,
            v.group,
            v.perPerson,
            v.perArea,
            v.density,
            v.exhaust,
            v.exhaustNote,
            v.ach,
            v.inside,
        )
        for key, v in t.ventilation.items()
    }
    return {
        "PAGES": dict(t.pages),
        # Table 8.2.2: outside design conditions (summer)
        "STATIONS": stations,
        "STATION_KEYS": tuple(stations),
        "DEFAULT_STATION": t.defaultStation,
        "DESIGN_LEVEL": t.designLevel,
        "DESIGN_MONTHS": tuple(t.designMonths),
        "INDOOR_DB": t.indoorDb,
        "MAX_INDOOR_OUTDOOR_DIFFERENCE": t.maxIndoorOutdoorDifference,
        "SETTINGS_STATION": dict(t.settingsStation),
        # Table 8.2.1: inside design conditions
        "INSIDE": {
            row: Inside(row, r.label, tuple(r.db), tuple(r.rh) if r.rh is not None else None)
            for row, r in t.inside.items()
        },
        # Table 8.2.3: minimum ventilation rates (and occupancy)
        "VENTILATION": ventilation,
        "VENTILATION_KEYS": tuple(ventilation),
        # Table 3.4.5: maximum allowable lighting power density
        "LPD": dict(t.lpd),
        "GROUP_LPD": dict(t.groupLpd),
        # Tables 8.2.9(a) / 3.4.2 and 3.4.3: glazing; Sec 4.4.3.1 and 4.5.1.2
        "SHGC_BY_WWR": {k: tuple(v) for k, v in t.shgcByWwr.items()},
        "OVERHANG_A": dict(t.overhangA),
        "OVERHANG_FACTOR": t.overhangFactor,
        "LEAST_WINDOW_SHARE": t.leastWindowShare,
        "DEFAULT_WWR": t.leastWindowShare.shallow,
        # where BNBC is silent (to be checked)
        "EQUIPMENT": dict(t.equipment),
        "EQUIPMENT_DEFAULT": t.equipmentDefault,
        "ACTIVITY": dict(t.activity),
        "ACTIVITY_DEFAULT": t.activityDefault,
        "SUPPLY_AIR_TEMPERATURE": t.supplyAirTemperature,
        "SUPPLY_AIR_HUMIDITY": t.supplyAirHumidity,
        "DESIGN_WIND_SPEED": t.designWindSpeed,
        "SITE_ELEVATION": t.siteElevation,
        "TIME_ZONE": t.timeZone,
        "ASSUMPTIONS": list(t.assumptions),
    }


_names = code_context.TableNames("hvac", _build)


def __getattr__(name: str) -> Any:
    return _names.get(name, __name__)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_names()))


def default_wwr(depth: float) -> float:
    """The window-to-wall ratio SAEngine assumes for a facade the engineer has not given: Sec
    4.5.1.2's least window area for a room of ``depth`` [m] (a whole-story zone takes the plan's
    depth behind the facade: the deepest room it may hold, the larger, safe-side glazing): 20 %
    for a room less than 8 m deep, 30 % for 8 to 14 m, 35 % deeper (``LEAST_WINDOW_SHARE``)."""
    share = _names()["LEAST_WINDOW_SHARE"]
    if depth < share.shallowDepth:
        return share.shallow
    return share.medium if depth <= share.deepDepth else share.deep


def shgc_limit(wwr: float) -> float:
    """The Table 8.2.9(a) SHGC limit for a window-to-wall ratio (0-1): the row at or above it
    (a larger ratio has the smaller, stricter limit); the largest ratio's above the table."""
    table = _names()["SHGC_BY_WWR"]
    percent = wwr * 100.0
    for ratio in sorted(table):
        if percent <= ratio + 1e-9:
            return table[ratio][0]
    return table[max(table)][0]


def station_for(city: str | None, location: str | None) -> tuple[Station, list[str]]:
    """The Table 8.2.2 station of the design (``city``) or of the Project Settings site
    (``location``); the default station (Dhaka) when neither gives one."""
    names = _names()
    stations = names["STATIONS"]
    if city:
        return stations[city], []
    key = names["SETTINGS_STATION"].get(location or "")
    if key:
        return stations[key], []
    default = stations[names["DEFAULT_STATION"]]
    note = (
        f"site location '{location}' has no Table 8.2.2 station: {default.name} is used (set the "
        "HVAC design city)"
        if location
        else f"no site location: {default.name} (Table 8.2.2) is used"
    )
    return default, [note]


def inside_conditions(use: str) -> tuple[float, float, str]:
    """Default indoor dry bulb [°C] and relative humidity [%] of a use, and where they come
    from: 24 °C (Sec 2.12.2.2) kept within the Table 8.2.1 row's range, and the row's upper
    humidity (the least energy, Sec 2.12.2.3); office buildings' row for a use without one."""
    names = _names()
    row = names["VENTILATION"][use].inside or 3
    inside = names["INSIDE"][row]
    low, high = inside.db
    db = min(max(names["INDOOR_DB"], low), high)
    rh = inside.rh[1] if inside.rh else 60.0
    source = (
        f"{db:g} °C (Sec 2.12.2.2, within Table 8.2.1 row {row} {inside.label} {low:g}-{high:g} "
        f"°C), {rh:g} % RH (upper value of the row, Sec 2.12.2.3)"
    )
    if inside.rh is None:
        source += " (the row gives no humidity: office buildings' 60 % taken)"
    return db, rh, source
