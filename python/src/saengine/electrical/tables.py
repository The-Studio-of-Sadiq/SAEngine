"""BNBC 2020 Part 8 Chapter 1 (Electrical and Electronic Engineering Services for Buildings)
and the typical equipment data the proposals use: the names the electrical modules read, served
from the code pack's ``electrical`` table (``saengine/codes/packs/bnbc2020/data/electrical.json``).

Every BNBC number was transcribed from the page cited (the page of ``bnbc-2020-part2.pdf``; the
tables were read from the rendered pages); ``PAGES`` gives the page of each clause, the table's
``sources`` the clause of each entry. Numbers that are not BNBC's are marked there: "SAEngine
practice" (a stated assumption the engineer can change in 07 MEP) or "typical" (manufacturers'
catalogue ranges for the first layout, to be replaced with the selected unit's data).

Each name is read from the pack in force where it is used (``T.USES``, see
:class:`saengine.codes.context.TableNames`); the formulas stay here and in the electrical
modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context

#: The note of the typical equipment data in the reports.
TYPICAL = "typical, replace with the selected unit's data"
#: Gravity [m/s²].
G = 9.81


@dataclass(frozen=True)
class Use:
    """A row of Table 8.1.17: the minimum unit load [W/m²] without and with air conditioning
    (None: the table gives none, '-')."""

    key: str
    label: str
    non_ac: float
    ac: float | None
    #: Table 8.1.27(a) index A (use of structure) and (b) index C (contents) of the row's kind
    #: of building, the lightning risk assessment's default for a story of this use.
    lightning_a: int
    lightning_c: int


def _indices(rows: Any) -> dict[str, tuple[str, Any]]:
    return {k: (r.label, r.index) for k, r in rows.items()}


def _build(t: Any) -> dict[str, Any]:
    """The module's names from the pack's ``electrical`` table, in the shapes the electrical
    modules read (tuples keyed as before)."""
    uses = {
        k: Use(k, u.label, u.nonAc, u.ac, u.lightningA, u.lightningC) for k, u in t.uses.items()
    }
    ht, cap = t.htPanel, t.capacitorPanel
    return {
        "PAGES": dict(t.pages),
        # Table 8.1.17: load densities; Sec 1.3.18.1, 1.3.20.1
        "USES": uses,
        "USE_KEYS": tuple(uses),
        "LOAD_FACTOR": t.loadFactor,
        "SUBSTATION_KW": t.substationKw,
        "POWER_FACTOR": t.powerFactor,
        "LT_VOLTAGE": t.ltVoltage,
        # Sec 1.3.18: substation and transformer rooms
        "SUBSTATION_HEIGHT": tuple(t.substationHeight),
        "TRANSFORMER_CLEARANCE": dict(t.transformerClearance),
        "TRANSFORMER_SPACING": dict(t.transformerSpacing),
        "SOAK_PIT_OIL": t.soakPitOil,
        "SUBSTATION_AREAS": {
            (r.number, r.kva): (r.transformerArea, r.totalArea) for r in t.substationAreas
        },
        "TRANSFORMER_SIZES": tuple(t.transformerSizes),
        "TRANSFORMER_MAX": t.transformerMax,
        # Sec 1.3.19: standby generator; Sec 4.2.1: lifts
        "GENERATOR_CLEARANCE": t.generatorClearance,
        "GENERATOR_SPACING": t.generatorSpacing,
        "GENERATOR_AREAS": dict(t.generatorAreas),
        "GENERATOR_SIZES": tuple(t.generatorSizes),
        "GENERATOR_PF": t.generatorPf,
        "FUEL_RATE": t.fuelRate,
        "FUEL_HOURS": t.fuelHours,
        "ESSENTIAL_SHARE": t.essentialShare,
        "DIESEL_DENSITY": t.dieselDensity,
        "TRANSFORMER_OIL_DENSITY": t.transformerOilDensity,
        "LIFT_STOREYS": t.liftStoreys,
        "LIFT_HEIGHT": t.liftHeight,
        "LIFT_STANDBY_STOREYS": t.liftStandbyStoreys,
        "LIFT_STANDBY_HEIGHT": t.liftStandbyHeight,
        # Sec 1.3.13: shafts and rising mains; SAEngine's openings and trays
        "SHAFT_STOREYS": t.shaftStoreys,
        "SHAFT_HEIGHT": t.shaftHeight,
        "SHAFT_SIZE": tuple(t.shaftSize),
        "SHAFT_AREA": t.shaftArea,
        "CABLE_RISER_STOREYS": t.cableRiserStoreys,
        "CABLE_RISER_AREA": t.cableRiserArea,
        "BUSBAR_STOREYS": t.busbarStoreys,
        "CABLE_SPACING": t.cableSpacing,
        "BUSBAR_RANGE": tuple(t.busbarRange),
        "OPENING_CLEARANCE": t.openingClearance,
        "TRAY_CLEARANCE": t.trayClearance,
        "OPENING_STEP": t.openingStep,
        "TRAY_HEADROOM": t.trayHeadroom,
        "TRAY_FILL": t.trayFill,
        "TRAY_WIDTHS": tuple(t.trayWidths),
        # Sec 1.3.32-1.3.33: earthing, lightning
        "SYSTEM_EARTH_OHM": t.systemEarthOhm,
        "ELECTRODE_SPACING": t.electrodeSpacing,
        "EARTH_PIT": t.earthPit,
        "LIGHTNING_EARTH_OHM": dict(t.lightningEarthOhm),
        "CONSTRUCTION": _indices(t.construction),
        "STRUCTURE_USE": _indices(t.structureUse),
        "CONTENTS": _indices(t.contents),
        "ISOLATION": _indices(t.isolation),
        "TERRAIN": _indices(t.terrain),
        "HEIGHT_INDEX": tuple((r.upTo, r.index) for r in t.heightIndex),
        "THUNDER_INDEX": tuple((r.upTo, r.index) for r in t.thunderIndex),
        "THUNDER_OVER": t.thunderOver,
        "THUNDER_DEFAULT": t.thunderDefault,
        "MARGINAL_RISK": t.marginalRisk,
        "ALWAYS_HEIGHT": t.alwaysHeight,
        "SPIKE_AREA": t.spikeArea,
        "SPIKE_HEIGHT": t.spikeHeight,
        "ROOF_CONDUCTOR_REACH": t.roofConductorReach,
        "DOWN_SINGLE_AREA": t.downSingleArea,
        "DOWN_FIRST_AREA": t.downFirstArea,
        "DOWN_STEP_AREA": t.downStepArea,
        "DOWN_PERIMETER": t.downPerimeter,
        "TEST_BOX_HEIGHT": t.testBoxHeight,
        "LIGHTNING_SIZES": dict(t.lightningSizes),
        "IEC_LEVELS": {k: (v.sphere, v.mesh, v.downSpacing) for k, v in t.iecLevels.items()},
        "REBAR_OHM": t.rebarOhm,
        # typical equipment (replace with the unit's data)
        "TRANSFORMER_OIL": {
            k: (v.length, v.width, v.height, v.mass, v.oil) for k, v in t.transformerOil.items()
        },
        "DRY_MASS": t.dryMass,
        "GENERATOR_SETS": {
            k: (v.length, v.width, v.height, v.mass) for k, v in t.generatorSets.items()
        },
        "BUSBARS": {k: (v.width, v.depth, v.mass) for k, v in t.busbars.items()},
        "CABLE_OD": tuple((r.amps, r.od) for r in t.cableOd),
        "LT_PANEL": t.ltPanel.model_dump(),
        "HT_PANEL": (ht.width, ht.depth, ht.height, ht.mass),
        "CAPACITOR_PANEL": (cap.width, cap.depth, cap.height, cap.mass, cap.kvar),
        "TARGET_PF": t.targetPf,
        "UPS_KG_PER_KVA": t.upsKgPerKva,
        "BATTERY_KG_PER_KWH": t.batteryKgPerKwh,
        "UPS_AUTONOMY_MIN": t.upsAutonomyMin,
        "TANK_PLATE": t.tankPlate,
        "STEEL_WEIGHT": t.steelWeight,
    }


_names = code_context.TableNames("electrical", _build)


def __getattr__(name: str) -> Any:
    return _names.get(name, __name__)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_names()))


def cite(key: str, clause: str = "") -> str:
    """The source of ``key`` with a sub-clause, e.g. cite('1.3.18.7', '(g)') ->
    'BNBC 2020 Part 8 Sec 1.3.18.7(g) (p800)'."""
    source = _names()["PAGES"][key]
    if not clause:
        return source
    i = source.rfind(" (p")
    return source[:i] + clause + source[i:] if i >= 0 else source + clause


def next_size(value: float, sizes: tuple[float, ...] | list[float]) -> float | None:
    """The smallest size of ``sizes`` (ascending) at least ``value`` (None above the largest)."""
    for size in sorted(sizes):
        if size >= value - 1e-9:
            return float(size)
    return None


def height_index(height_m: float) -> int | None:
    """Table 8.1.27(c) index F; None above 53 m (protection required in all cases)."""
    for bound, index in _names()["HEIGHT_INDEX"]:
        if height_m <= bound + 1e-9:
            return index
    return None


def thunder_index(days: float) -> int:
    """Table 8.1.27(c) index G for the thunderstorm days a year."""
    names = _names()
    for bound, index in names["THUNDER_INDEX"]:
        if days <= bound + 1e-9:
            return index
    return names["THUNDER_OVER"]


def cable_od(amps: float) -> float:
    """Outside diameter of a 4-core copper cable for ``amps`` (typical)."""
    table = _names()["CABLE_OD"]
    for limit, od in table:
        if amps <= limit:
            return float(od)
    return float(table[-1][1])
