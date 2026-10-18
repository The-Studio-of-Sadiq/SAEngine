"""The connected load and the maximum demand of the building (BNBC 2020 Part 8 Sec 1.3.2,
1.3.18.1).

BNBC lists the loads room by room, floor by floor, and adds the lifts, the water pumps, the
basement ventilation and any other equipment (Sec 1.3.2, p763). For the coordination the load of
a story is its floor area times a unit load: the minimum load density of Table 8.1.17 for its
use (with or without air conditioning), or the lighting plus power the engineer enters where
that is more, plus the story's other loads. The air-conditioning plant of 07 MEP ``hvac`` adds
its electrical load (cooling capacity / COP); a conditioned story that a cooling source of that
plant serves (a chiller, a VRF or split outdoor unit with a load: its ``serves``) then takes the
table's non-A/C density, so the cooling is not counted twice. Fans, AHUs, FCUs, pumps and
cooling towers are not a cooling source: they never move a story off the A/C column.

The maximum demand for the substation is the connected load times a load factor of at least
80 % (Sec 1.3.18.1, p796); Appendix A's allowances for diversity (Table 8.A.1) are for the final
circuits, not the building. kVA = kW / power factor (BNBC gives no power factor: 0.85, SAEngine
practice, editable).
"""

from __future__ import annotations

import math
from typing import Any

from saengine.electrical import tables as T
from saengine.plumbing.building import Building

#: Coefficient of performance of the cooling plant when 07 MEP gives no electrical power
#: (SAEngine estimates, to be replaced with the plant's data).
COP = {"chiller": 3.0, "chillerWaterCooled": 5.0, "vrfOutdoor": 3.5, "splitOutdoor": 3.0}
#: Fan power per air flow [kW per m³/s] (specific fan power, SAEngine estimate).
FAN_POWER = 1.5
#: Fans of an AHU or FCU as a share of its cooling capacity, cooling tower fans and pumps as a
#: share of the heat it rejects (SAEngine estimates).
AHU_SHARE = 0.05
TOWER_SHARE = 0.01
#: The plant kinds that produce the cooling (the A/C column of Table 8.1.17 includes it).
COOLING_KINDS = ("chiller", "vrfOutdoor", "splitOutdoor", "packaged")
#: Cooling sources that are a central plant: without ``serves`` they serve every story.
CENTRAL_KINDS = ("chiller",)


def _get(item: Any, key: str, default: Any = None) -> Any:
    """A field of a model or a dict (07 MEP ``hvac`` is read either way)."""
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def story_order(electrical: Any, building: Building) -> list[str]:
    """Stories lowest first: 06 BIM's, else the order of the electrical stories."""
    if building.known:
        return building.ordered()
    return [s.story for s in electrical.stories] if electrical is not None else []


def hvac_conditioned(mep: Any) -> dict[str, bool]:
    """Story -> conditioned, from 07 MEP ``hvac.stories`` (empty without hvac)."""
    hvac = _get(mep, "hvac")
    if not hvac:
        return {}
    return {
        str(_get(s, "story")): bool(_get(s, "conditioned", False))
        for s in _get(hvac, "stories", None) or []
    }


def hvac_loads(mep: Any) -> list[dict[str, Any]]:
    """The electrical load of each item of 07 MEP ``hvac.plant``: ``[{id, kind, story, kw,
    note}]``. An item's own ``power`` (kW, electrical) when 07 MEP gives one, else an estimate
    from its capacity (cooling kW / COP; fans m³/s x specific fan power)."""
    hvac = _get(mep, "hvac")
    if not hvac:
        return []
    plant = _get(hvac, "plant", None) or []
    water_cooled = any(_get(p, "kind") == "coolingTower" for p in plant)
    out = []
    for item in plant:
        kind = str(_get(item, "kind", ""))
        capacity = _get(item, "capacity")
        power = _get(item, "power") or _get(item, "electricalPower")
        if power:
            kw, note = float(power), "entered electrical power"
        elif not capacity:
            kw, note = 0.0, "no capacity or power: enter its electrical load"
        elif kind == "chiller":
            cop = COP["chillerWaterCooled" if water_cooled else "chiller"]
            kw, note = capacity / cop, f"{capacity:g} kW cooling / COP {cop:g} (SAEngine estimate)"
        elif kind in ("vrfOutdoor", "splitOutdoor"):
            kw, note = (
                capacity / COP[kind],
                (f"{capacity:g} kW cooling / COP {COP[kind]:g} (SAEngine estimate)"),
            )
        elif kind in ("exhaustFan", "freshAirUnit"):
            kw, note = (
                capacity * FAN_POWER,
                (f"{capacity:g} m³/s x {FAN_POWER:g} kW/(m³/s) (SAEngine estimate)"),
            )
        elif kind in ("ahu", "fcu"):
            kw, note = (
                capacity * AHU_SHARE,
                (f"fans {AHU_SHARE:.0%} of {capacity:g} kW cooling (SAEngine estimate)"),
            )
        elif kind == "coolingTower":
            kw, note = (
                capacity * TOWER_SHARE,
                (f"fans {TOWER_SHARE:.0%} of {capacity:g} kW rejected (SAEngine estimate)"),
            )
        else:
            kw, note = 0.0, "enter its electrical load as a motor of 07 MEP electrical"
        serves = _get(item, "serves")
        out.append({
            "id": _get(item, "id"), "kind": kind, "story": _get(item, "story"),
            "kw": float(kw), "note": note,
            "serves": [str(s) for s in serves] if serves else None,
        })  # fmt: skip
    return out


def cooled_stories(hvac: list[dict[str, Any]]) -> tuple[set[str] | None, list[str]]:
    """The stories whose cooling the hvac plant's loads already carry, and notes.

    Only a cooling source with a load counts (:data:`COOLING_KINDS`). It covers its ``serves``;
    without ``serves`` a central plant (a chiller) covers every story (returned as ``None`` in
    the set's place) and a VRF or split outdoor unit only the story it stands on, so that the
    cooling is counted twice rather than not at all (enter ``serves``)."""
    covered: set[str] = set()
    notes: list[str] = []
    everything = False
    for h in hvac:
        if str(h.get("kind", "")) not in COOLING_KINDS or not float(h.get("kw") or 0.0) > 0:
            continue
        serves = h.get("serves")
        if serves:
            covered.update(str(s) for s in serves)
        elif str(h.get("kind")) in CENTRAL_KINDS:
            everything = True
        else:
            if h.get("story") is not None:
                covered.add(str(h["story"]))
            notes.append(
                f"{h.get('id')}: no 'serves': taken to cool only its own story "
                f"{h.get('story')}; the A/C density stays on the others (enter 'serves')"
            )
    return (None if everything else covered), notes


def story_area(story: str, building: Building, order: list[str]) -> tuple[float, str]:
    """Floor area of a story [m²] and where it comes from: its slabs in 06 BIM, else (a floor
    on grade the model has no slab for) the slabs of the story above."""
    area = building.floor_area(story)
    if area > 0:
        return area, "06 BIM slabs"
    if story in order:
        for above in order[order.index(story) + 1 :]:
            area = building.floor_area(above)
            if area > 0:
                return area, f"no slab on {story}: the area of {above}'s slabs"
    return 0.0, "no slab in 06 BIM: enter the area"


def demand(
    electrical: Any,
    building: Building,
    mep: Any = None,
    hvac: list[dict[str, Any]] | None = None,
    extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The connected load and maximum demand.

    ``hvac``: the air-conditioning plant's loads ``[{id, kind, story, kw, note}]`` (default:
    :func:`hvac_loads` of ``mep``); ``extra``: other loads the caller adds (``[{id, kw,
    note}]``, e.g. the plumbing pumps when 07 MEP lists no pump motor)."""
    supply = electrical.supply
    order = story_order(electrical, building)
    notes: list[str] = []
    hvac = hvac_loads(mep) if hvac is None else hvac
    hvac_kw = sum(h["kw"] for h in hvac)
    cooled, cooled_notes = cooled_stories(hvac)
    notes.extend(cooled_notes)
    conditioned = hvac_conditioned(mep)
    factor = supply.loadFactor or T.LOAD_FACTOR
    pf = supply.powerFactor or T.POWER_FACTOR
    stories = []
    by_id = {s.story: s for s in electrical.stories}
    ordered = [s for s in order if s in by_id] + [s for s in by_id if s not in order]
    for sid in ordered:
        entry = by_id[sid]
        use = T.USES[entry.use]
        ac = entry.airConditioned
        if ac is None:
            ac = conditioned.get(sid, False)
        if entry.area is not None:
            area, area_source = float(entry.area), "entered"
        else:
            area, area_source = story_area(sid, building, order)
        story_notes = []
        if ac and (cooled is None or sid in cooled):
            minimum, column = use.non_ac, "non-A/C (the hvac plant carries the cooling)"
        elif ac and use.ac is None:
            minimum, column = use.non_ac, "non-A/C (the table gives no A/C value)"
            story_notes.append("Table 8.1.17 gives no A/C density for this use: add the cooling")
        elif ac:
            minimum, column = float(use.ac or 0.0), "A/C"
        else:
            minimum, column = use.non_ac, "non-A/C"
        entered = None
        if entry.lighting is not None or entry.power is not None:
            entered = (entry.lighting or 0.0) + (entry.power or 0.0)
        unit = minimum if entered is None else max(entered, minimum)
        if entered is not None and entered < minimum:
            story_notes.append(
                f"lighting + power {entered:g} W/m² below the minimum {minimum:g} W/m² of "
                "Table 8.1.17: the minimum is used"
            )
        other = float(entry.other or 0.0)
        connected = unit * area / 1000.0 + other
        stories.append({
            "story": sid, "name": building.names.get(sid, sid), "use": entry.use,
            "airConditioned": bool(ac), "area": area, "areaSource": area_source,
            "minimumDensity": minimum, "column": column, "entered": entered,
            "density": unit, "other": other, "connected": connected,
            "demand": connected * factor, "kva": connected * factor / pf,
            "notes": story_notes,
        })  # fmt: skip
    missing = [s for s in order[:-1] if s not in by_id]  # the top level is the roof
    if missing and electrical.stories:
        notes.append(f"stories without an electrical entry draw nothing: {', '.join(missing)}")
    motors = []
    for m in electrical.motors:
        motors.append({
            "id": m.id, "kind": m.kind, "power": m.power, "count": m.count,
            "kw": m.power * m.count, "essential": essential(m),
        })  # fmt: skip
    extra = list(extra or [])
    story_kw = sum(s["connected"] for s in stories)
    motor_kw = sum(m["kw"] for m in motors)
    extra_kw = sum(float(e.get("kw") or 0.0) for e in extra)
    connected = story_kw + hvac_kw + motor_kw + extra_kw
    maximum = connected * factor * (1 + supply.growth / 100.0)
    kva = maximum / pf
    current = kva * 1000.0 / (math.sqrt(3) * T.LT_VOLTAGE)
    notes.append(
        f"maximum demand = {factor:g} x connected load (load factor, {T.PAGES['1.3.18.1']})"
        + (f" + {supply.growth:g} % future expansion" if supply.growth else "")
        + f"; kVA = kW / {pf:g}"
        + ("" if supply.powerFactor else " (power factor: SAEngine practice, BNBC gives none)")
    )
    notes.append(
        f"unit loads: the minimum load densities of {T.PAGES['8.1.17']}; the diversity "
        f"allowances of {T.PAGES['8.A.1']} are for final circuits"
    )
    if hvac and any("estimate" in h["note"] for h in hvac):
        notes.append(
            "the hvac plant's electrical load is estimated from its capacity: enter the "
            "plant's power for the design"
        )
    return {
        "stories": stories,
        "hvac": hvac,
        "motors": motors,
        "extra": extra,
        "storiesKw": story_kw,
        "hvacKw": hvac_kw,
        "motorsKw": motor_kw,
        "extraKw": extra_kw,
        "connected": connected,
        "loadFactor": factor,
        "growth": supply.growth,
        "powerFactor": pf,
        "maximumDemand": maximum,
        "kva": kva,
        "current": current,
        "notes": notes,
    }


def essential(motor: Any) -> bool:
    """Whether a motor is on the standby generator: as entered, else lifts and pumps are
    (Sec 1.3.19.2 names the essential lifts and one or all water pumps)."""
    if motor.essential is not None:
        return bool(motor.essential)
    return motor.kind in ("lift", "pump", "firePump")
