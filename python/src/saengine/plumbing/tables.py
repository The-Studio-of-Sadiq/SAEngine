"""BNBC 2020 Part 8 (and the few Part 3 and Part 4 values Part 8 refers to): the names the
plumbing modules read, served from the code pack's ``plumbing`` table
(``saengine/codes/packs/bnbc2020/data/plumbing.json``).

The values are transcribed from the rendered page of the Bangladesh Gazette edition of
11 February 2021 (``bnbc-2020-part2.pdf`` for Parts 7 to 10, ``bnbc-2020-part1.pdf`` for
Parts 1 to 6); ``PAGES`` gives the PDF page of each table, the table's ``sources`` the clause of
each entry. Entries the table marks "SAEngine" are not BNBC's: they are documented assumptions
where the code is silent.

Each name is read from the pack in force where it is used (``tables.HUNTER``, see
:class:`saengine.codes.context.TableNames`); the formulas stay in the plumbing modules.

Units: litres, mm, m², l/min, l/m²/day and lpcd (litres per capita per day) as the tables give
them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context


@dataclass(frozen=True)
class Occupancy:
    """One row of Tables 8.5.1(a)-(d): the per-capita water requirement of an occupancy."""

    key: str
    label: str
    table: str  # "8.5.1(a)" ...
    row: str  # the row's category as printed, e.g. "y1", "E1"
    full: float | None  # lpcd, full facility; None where the table prints "---"
    restricted: float | None  # lpcd, restricted facility
    group: str  # BNBC Part 3 occupancy group, e.g. "A3", "E1"
    unit: str = "person"  # what the population counts: person, bed, seat


@dataclass(frozen=True)
class SupplyUnits:
    """Water supply fixture units of a fixture: cold, hot and total, and where they come from."""

    cold: float
    hot: float
    total: float
    source: str
    minimum: int  # minimum supply pipe [mm], Table 8.5.6 (or Table 8.5.4's branch)


@dataclass(frozen=True)
class DrainageUnits:
    units: float
    source: str
    outlet: int  # minimum internal diameter of the waste outlet [mm], Table 8.6.2
    soil: bool  # a soil appliance (Table 8.6.2): goes to a soil (or soil-and-waste) stack


NL = float("inf")  # "NL": no limit


def _no_limit(value: float | None) -> float:
    return NL if value is None else value


def _build(t: Any) -> dict[str, Any]:
    """The module's names from the pack's ``plumbing`` table, in the shapes the plumbing modules
    read (tuples, int keys, NL for "no limit")."""
    septic = t.septic
    occupancies = {
        key: Occupancy(key, o.label, o.table, o.row, o.full, o.restricted, o.group, o.unit)
        for key, o in t.occupancies.items()
    }
    return {
        "PAGES": dict(t.pages),
        # Table 8.5.1: water consumption; Sec 5.6.3-5.6.4: population
        "OCCUPANCIES": occupancies,
        "OCCUPANCY_KEYS": tuple(occupancies),
        "FAMILY_SIZE": t.familySize,
        "OFFICE_AREA_PER_PERSON": t.officeAreaPerPerson,
        # Sec 5.9 storage and 5.10 distribution
        "ROOF_TANK_FRACTION": t.roofTankFraction,
        "RESERVOIR_FRACTION": t.reservoirFraction,
        "FIRE_RESERVE_HOURS": t.fireReserveHours,
        "CONSUMPTION_HOURS": t.consumptionHours,
        "PEAK_FACTOR": t.peakFactor,
        "TANK_DRAIN": [(r.upTo, r.diameter) for r in t.tankDrain],
        "TANK_OVERFLOW": [(r.upTo, r.diameter) for r in t.tankOverflow],
        "VELOCITY_LIMITS": [(r.diameter, r.velocity) for r in t.velocityLimits],
        "MAX_HEAD_LOSS": t.maxHeadLoss,
        "SUPPLY_DIAMETERS": list(t.supplyDiameters),
        "FLOW_PRESSURE_TANK": t.flowPressureTank,
        "FLOW_PRESSURE_VALVE": t.flowPressureValve,
        "MAX_STATIC_HEAD": t.maxStaticHead,
        "HIGH_RISE": t.highRise,
        "HUNTER": [(r.units, r.tank, r.valve) for r in t.hunter],
        "SUPPLY_UNITS": {
            k: SupplyUnits(u.cold, u.hot, u.total, u.source or "", u.minimum)
            for k, u in t.supplyUnits.items()
        },
        # Chapter 6: drainage
        "DRAINAGE_UNITS": {
            k: DrainageUnits(u.units, u.source or "", u.outlet, u.soil)
            for k, u in t.drainageUnits.items()
        },
        "TRAP_UNITS": [(r.diameter, r.units) for r in t.trapUnits],
        "STACKS": [
            (r.diameter, r.branch, r.threeStoreys, r.stackTotal, r.storeyTotal) for r in t.stacks
        ],
        "DRAIN_SLOPES": list(t.drainSlopes),
        "BUILDING_DRAINS": [(r.diameter, tuple(r.units)) for r in t.buildingDrains],
        "VENT_STACKS": [(r.diameter, r.units, dict(r.lengths)) for r in t.ventStacks],
        "BRANCH_VENTS": [
            (r.diameter, r.slope, {k: _no_limit(v) for k, v in r.lengths.items()})
            for r in t.branchVents
        ],
        "DRAIN_VELOCITY": tuple(t.drainVelocity),
        # septic tank (Sec 6.9.12), Appendix S
        "SEPTIC_MIN_VOLUME": septic.minVolume,
        "SEPTIC_MIN_WIDTH": septic.minWidth,
        "SEPTIC_MIN_DEPTH": septic.minDepth,
        "SEPTIC_LENGTH_RATIO": tuple(septic.lengthRatio),
        "SEPTIC_MAX_USERS": septic.maxUsers,
        "SEPTIC_SLUDGE": septic.sludge,
        "SEPTIC_CLEARANCE": septic.clearance,
        "SEPTIC_RETENTION": septic.retention,
        "SEPTIC_DESLUDGING": septic.desludging,
        "SEPTIC_TWO_CHAMBERS": septic.twoChambers,
        "SEPTIC_INLET_FRACTION": septic.inletFraction,
        "SEPTIC_COVER_LIVE": septic.coverLive,
        "SEPTIC_FLOW_CITY": septic.flowCity,
        "SEPTIC_FLOW_OTHER": septic.flowOther,
        "SEPTIC_REDUCTION": {k: (r.factor, r.source or "") for k, r in t.septicReduction.items()},
        "DISPOSAL_DISTANCES": {k: dict(v) for k, v in t.disposalDistances.items()},
        "TREATMENT_TANK_DISTANCES": dict(t.treatmentTankDistances),
        "ABSORPTION": [(r.rate, r.trench, r.pit) for r in t.absorption],
        "SEEPAGE_CAPACITY_FACTOR": t.seepageCapacityFactor,
        "SEEPAGE_ABOVE_WATER_TABLE": t.seepageAboveWaterTable,
        "PERCOLATION_BY_SOIL": dict(t.percolationBySoil),
        # Chapter 7: rainwater
        "TABLE_RAINFALL": t.tableRainfall,
        "DHAKA_RAINFALL": t.defaultRainfall,
        "HARVEST_PLOT": t.harvestPlot,
        "HARVEST_DAYS": dict(t.harvestDays),
        "LEADERS": [(r.diameter, r.area, r.flow) for r in t.leaders],
        "GUTTERS": [(r.diameter, {k: tuple(v) for k, v in r.slopes.items()}) for r in t.gutters],
        "STORM_DRAINS": [
            (r.diameter, {k: tuple(v) for k, v in r.slopes.items()}) for r in t.stormDrains
        ],
        "MIN_STORM_DRAIN": t.minStormDrain,
        # SAEngine: pipe outside diameters, friction, sleeves and shafts
        "OUTSIDE_DIAMETER": {k: dict(v) for k, v in t.outsideDiameter.items()},
        "HAZEN_C": dict(t.hazenC),
        "SLEEVE_CLEARANCE": t.sleeveClearance,
        "SLEEVE_SIZES": list(t.sleeveSizes),
        "SHAFT_CLEARANCE": t.shaftClearance,
        # wet rooms of the architecture (07 MEP plumbing.roomFixtures and plumbing.wetRooms
        # replace them for the project and for one room)
        "WET_ROOM_KINDS": dict(t.wetRoomKinds),
        "DEFAULT_ROOM_FIXTURES": {k: dict(v) for k, v in t.roomFixtures.items()},
    }


_names = code_context.TableNames("plumbing", _build)


def __getattr__(name: str) -> Any:
    if name in _FIRE_NAMES:
        from saengine.fire import tables as fire_tables

        return getattr(fire_tables, name)
    return _names.get(name, __name__)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_names()) | set(_FIRE_NAMES))


# Part 4 Table 4.4.1 (fire protection flows) is the fire table's: these names, which Part 8's
# storage reads, are served from it (saengine.fire.tables).
_FIRE_NAMES = ("FIRE_FLOWS", "FIRE_RISER_AREA", "FIRE_HAZARD", "HAZARD_ORDER")


def fire_hazard(group: str) -> str | None:
    """Table 4.4.1's hazard class of a Part 3 occupancy group, or None when it lists none."""
    from saengine.fire import tables as fire_tables

    return fire_tables.fire_hazard(group)
