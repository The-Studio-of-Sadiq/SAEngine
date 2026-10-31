"""BNBC 2020 Part 4 (fire protection), and the few NFPA values the code leaves out: the names the
fire modules read, served from the code pack's ``fire`` table
(``saengine/codes/packs/bnbc2020/data/fire.json``).

Every BNBC value is transcribed from the rendered page of the Bangladesh Gazette edition of
11 February 2021 (``bnbc-2020-part1.pdf`` holds Parts 1 to 6); ``PAGES`` gives the PDF page of
each table and clause, the table's ``sources`` the clause of each entry. BNBC 2020 Part 4
Chapter 4 gives the flows, durations, pressures, pump ratings, pipe schedules and sprinkler
spacing; Chapter 5 says which systems each occupancy needs. It leaves the sprinkler design
density, the hose allowance, the jockey pump and the extinguisher ratings to NFPA (NFPA 10, 13,
20): those values are SAEngine's recollection of NFPA, each marked ``MEMORY`` ("from memory, to
be checked") wherever it is reported. Values marked "SAEngine" are documented assumptions where
both are silent.

Each name is read from the pack in force where it is used (``T.FLOWS``, see
:class:`saengine.codes.context.TableNames`); the formulas stay here and in the fire modules.

Units: l/min, kPa, m, m², mm as the tables give them.
"""

from __future__ import annotations

from typing import Any

from saengine.codes import context as code_context

MEMORY = "from memory, to be checked"


def _build(t: Any) -> dict[str, Any]:
    """The module's names from the pack's ``fire`` table, in the shapes the fire modules read."""
    order = list(t.hazardOrder)
    flows = {k: (v.sprinkler, v.standpipe) for k, v in t.flows.items()}

    def schedule(rows: Any) -> tuple:
        return tuple((r.size, r.light, r.ordinary, r.extra) for r in rows)

    return {
        "PAGES": dict(t.pages),
        # definitions (Part 1, Part 3); Sec 4.5
        "HIGH_RISE_HEIGHT": t.highRiseHeight,
        "HIGH_RISE_STOREYS": t.highRiseStoreys,
        "TALL_HEIGHT": t.tallHeight,
        # Table 4.4.1: flows, durations (FIRE_*: the names Part 8's storage reads)
        "HAZARD_ORDER": order,
        "HAZARDS": list(flows),
        "HAZARD_LABELS": dict(t.hazardLabels),
        "FLOWS": flows,
        "FIRE_FLOWS": {k: flows[k] for k in order},
        "RISER_AREA": t.riserArea,
        "FIRE_RISER_AREA": t.riserArea,
        "FIRE_HAZARD": dict(t.hazardOfGroup),
        "DURATION_HEIGHTS": tuple(t.durationHeights),
        "DURATIONS": {k: tuple(v) for k, v in t.durations.items()},
        # standpipes, Sec 4.2.3
        "ADDITIONAL_STANDPIPE_FLOW": t.additionalStandpipeFlow,
        "MAX_ADDITIONAL_STANDPIPES": t.maxAdditionalStandpipes,
        "HOSE_PRESSURE": dict(t.hosePressure),
        "COMBINED_PRESSURE": t.combinedPressure,
        "MAX_PRESSURE": t.maxPressure,
        "PRV_PRESSURE": t.prvPressure,
        "GRAVITY_HEIGHT": dict(t.gravityHeight),
        "HOSE_SIZE": dict(t.hoseSize),
        "HOSE_LENGTH": t.hoseLength,
        "OUTLET_HEIGHT": t.outletHeight,
        "WET_RISER_MIN": t.wetRiserMin,
        "SUPPORT_EXTRA": t.supportExtra,
        "HANGER_FACTOR": t.hangerFactor,
        "HANGER_SPACING": t.hangerSpacing,
        "TEST_STANDPIPE": t.testStandpipe,
        "TEST_SPRINKLER": t.testSprinkler,
        # fire pumps, Sec 4.2.2.5 and Table 4.4.2
        "PUMP_MIN_NET": t.pumpMinNet,
        "PUMP_RATINGS": tuple((r.rating, r.pipe) for r in t.pumpRatings),
        # sprinklers, Tables 4.4.5-4.4.7
        "STEEL_SCHEDULE": schedule(t.steelSchedule),
        "COPPER_SCHEDULE": schedule(t.copperSchedule),
        "RISER_FLOOR_AREA": dict(t.riserFloorArea),
        "COVERAGE": {k: {f: tuple(v) for f, v in by.items()} for k, by in t.coverage.items()},
        # NFPA, from memory (to be checked)
        "DENSITY_AREA": {k: tuple(v) for k, v in t.densityArea.items()},
        "HOSE_ALLOWANCE": {k: tuple(v) for k, v in t.hoseAllowance.items()},
        "K_FACTOR": t.kFactor,
        "MIN_HEAD_PRESSURE": t.minHeadPressure,
        "DESIGN_AREA_LENGTH": t.designAreaLength,
        "JOCKEY_SHARE": t.jockeyShare,
        "JOCKEY_ABOVE": t.jockeyAbove,
        "OVERLOAD_FLOW": t.overloadFlow,
        "OVERLOAD_HEAD": t.overloadHead,
        "EXTINGUISHER": {k: v.model_dump() for k, v in t.extinguisher.items()},
        "EXTINGUISHER_TRAVEL": t.extinguisherTravel,
        "EXTINGUISHER_SMALL_FLOOR": t.extinguisherSmallFloor,
        "DETECTOR_AREA": t.detectorArea,
        "CALL_POINT_AREA": t.callPointArea,
        # SAEngine: pipes and pumps
        "STEEL_BORE": dict(t.steelBore),
        "COPPER_BORE": dict(t.copperBore),
        "HAZEN_C": dict(t.hazenC),
        "STEEL_MASS": dict(t.steelMass),
        "MAX_VELOCITY": t.maxVelocity,
        "PUMP_EFFICIENCY": t.pumpEfficiency,
        "JOCKEY_EFFICIENCY": t.jockeyEfficiency,
        "MOTOR_SIZES": tuple(t.motorSizes),
        "PUMP_CLEARANCE": t.pumpClearance,
        "CONTROLLER_STRIP": t.controllerStrip,
        "PUMP_CENTRE": t.pumpCentre,
    }


_names = code_context.TableNames("fire", _build)


def __getattr__(name: str) -> Any:
    return _names.get(name, __name__)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_names()))


def cite(key: str, clause: str = "") -> str:
    """The source of ``key`` with a sub-clause appended to its section, e.g.
    cite('5.7', '(ii)') -> 'Part 4 Sec 5.7(ii) (p350-351)'."""
    source = _names()["PAGES"][key]
    if not clause:
        return source
    i = source.find(",")
    return source[:i] + clause + source[i:] if i >= 0 else source + clause


def fire_hazard(group: str) -> str | None:
    """Table 4.4.1's hazard class of a Part 3 occupancy group as its notes list it (J: ordinary
    hazard-III, the least the Fire Department may set), or None when it lists none."""
    table = _names()["FIRE_HAZARD"]
    return table.get(group) or table.get(group[:1])


def hazard_of(group: str) -> str | None:
    """Table 4.4.1's hazard class of a Part 3 occupancy group (J: extra), None when unlisted."""
    if group.startswith("J"):
        return "extra"
    return fire_hazard(group)


def duration(hazard: str, height: float) -> int:
    """Table 4.4.1 duration [min] of a hazard for a building ``height`` [m]."""
    names = _names()
    low, high = names["DURATION_HEIGHTS"]
    column = 0 if height <= low else 1 if height <= high else 2
    return names["DURATIONS"][hazard][column]


def family(hazard: str) -> str:
    """Light, ordinary or extra: the columns of Tables 4.4.5-4.4.7."""
    return "light" if hazard.startswith("light") else "extra" if hazard == "extra" else "ordinary"
