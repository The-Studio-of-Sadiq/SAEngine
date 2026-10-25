"""The fire protection report of a project (BNBC 2020 Part 4), for the structure's coordination.

:func:`fire_report` reads ``07 MEP/mep.json`` (its ``fire``, and ``plumbing`` where the fire water
is the plumbing tanks' reserve), ``06 BIM/bim.json`` (stories, slabs, beams), ``04 Objects``
(beam depths, slab thicknesses), ``03 Materials`` and ``01 Soil Report`` (the fire tanks' design)
and ``02 Project Settings`` (ground level), and returns what Part 4 requires and why, the
sprinklers of each floor, the hydraulic calculation, the water and the reservoir, the fire pumps
and their room, the fire tanks' designs (as the plumbing tanks, OpenSees shells), the hanger and
support loads, the sleeves still missing, the quantities and the checks.
:func:`fire_propose` returns the tanks and pumps SAEngine proposes (07 MEP ``fire.tanks`` and
``fire.pumps``), :func:`fire_openings` the sleeves, :func:`fire_equipment` the fire pumps and
overhead fire tanks as 07 MEP ``equipment`` for the analysis loads.

:func:`fire_results` does the same from the parsed models, without files.
"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from saengine.fire import network as N
from saengine.fire import supply as S
from saengine.fire import tables as T
from saengine.fire.requirements import extinguishers, requirements
from saengine.fire.sprinklers import floor_sprinklers, hand_demand, schedule_size
from saengine.library.mep import FIRE_PUMP_DUTIES, MEP_FILE, MepModel, parse
from saengine.plumbing.building import Building
from saengine.plumbing.tables import OCCUPANCIES

#: The fire tanks' designs between runs, and their models (beside the plumbing tanks').
DESIGNS_FILE = "07 MEP/mep.results/fire-tank-designs.json"
MODELS_DIR = "07 MEP/mep.results/fire-tanks"
#: A fire engine's gross weight when none is given [kN] (MEMORY: a Dhaka water tender).
FIRE_ENGINE = 160.0
#: SAEngine: sprinkler deflectors this far below the floor above [m]; a story height when the
#: floor above is unknown.
HEAD_BELOW = 0.3
STOREY = 3.0

METHOD = [
    (
        "Systems (BNBC 2020 Part 4 Chapter 5, p346-p355): by the occupancy of each story (Part 3 "
        "groups), the storeys, the floor and undivided areas and whether the building is "
        "high-rise (more than 10 storeys or 33 m, Part 1 p6, Part 3 Sec 2.4.4); where the code "
        "allows 'portable extinguishers or hydrants', the hydrant choice decides."
    ),
    (
        "Water (Table 4.4.1, Sec 4.2.3.2, 4.2.3.5): standpipe flow of the hazard for the first "
        "standpipe + 1000 l/min each other (at most eight); sprinklers the more of Table 4.4.1 "
        "and the hydraulic demand; each for the duration of the building's height; the "
        "reservoir holds it for fire fighting only (Sec 4.2.3.7)."
    ),
    (
        "Hydraulics (Sec 4.2.1, 4.2.3.4): EPANET 2.2 through WNTR, Hazen-Williams C 120 (steel), "
        "fittings of BNBC Tables 8.O.2; standpipe outlets at 300 kPa (200 kPa first aid, Sec "
        "4.2.3.3) 1.5 m above the floor; sprinkler heads as emitters of K 80 in the design area "
        "of NFPA 13 (density, area, K and the hose allowance from memory, to be checked)."
    ),
    (
        "Pumps (Sec 4.2.2.5, Table 4.4.2): main pump of the next Table 4.4.2 rating, net "
        "pressure at least 272 kPa, a standby pump, a jockey pump (NFPA 20 practice, from "
        "memory); no static suction lift for centrifugal pumps. Sets' sizes and weights typical."
    ),
    (
        "Structure: the fire tanks designed as the plumbing tanks (OpenSees shells); an "
        "overhead fire tank and the pump sets load their floors once (07 MEP equipment); riser "
        "supports and hangers carry the water-filled pipe + 110 kg (x5 for hangers, Sec "
        "4.2.3.13-4.2.3.14, 4.2.10.6); sleeves through the slabs and beams by command."
    ),
]


def _check(name: str, demand: float, capacity: float | None, unit: str, ok: bool, note: str,
           clause: str = "") -> dict[str, Any]:  # fmt: skip
    util = demand / capacity if capacity else (0.0 if demand == 0 else math.inf)
    return {"name": name, "demand": demand, "capacity": capacity, "unit": unit,
            "utilisation": util, "ok": bool(ok), "note": note, "clause": clause}  # fmt: skip


def _new_id(base: str, taken: set[str]) -> str:
    i = 1
    while f"{base}{i}" in taken:
        i += 1
    taken.add(f"{base}{i}")
    return f"{base}{i}"


def fire_stories(mep: MepModel) -> tuple[list[Any], list[str]]:
    """The fire section's stories with their use resolved, and notes: a story's use is entered
    once, in Plumbing; a fire story without one takes its plumbing use (else office), and the
    plumbing stories the fire section does not list are fire stories too."""
    from saengine.library.mep import FireStory

    fire = mep.fire
    if fire is None:
        return [], []
    plumbing = {s.story: s.occupancy for s in mep.plumbing.stories} if mep.plumbing else {}
    out, notes, defaulted = [], [], []
    for s in fire.stories:
        occupancy = s.occupancy or plumbing.get(s.story)
        if occupancy is None:
            defaulted.append(s.story)
        out.append(s.model_copy(update={"occupancy": occupancy or "office"}))
    listed = {s.story for s in fire.stories}
    from_plumbing = [k for k in plumbing if k not in listed]
    out.extend(FireStory(story=k, occupancy=plumbing[k]) for k in from_plumbing)
    taken = [s.story for s in fire.stories if s.occupancy is None and s.story in plumbing]
    if taken or from_plumbing:
        notes.append(f"use of {', '.join([*taken, *from_plumbing])} as in Plumbing")
    if defaulted:
        notes.append(f"{', '.join(defaulted)}: no use given here or in Plumbing: office taken")
    return out, notes


def references(mep: MepModel, building: Building) -> list[str]:
    """Problems with the stories and shafts the fire section refers to."""
    fire = mep.fire
    if fire is None or not building.known:
        return []
    stories = building.stories
    shafts = {s.id for s in mep.shafts}
    problems = []
    for entry in fire.stories:
        if entry.story not in stories:
            problems.append(f"fire: no story '{entry.story}'")
    for item in [*fire.mains, *fire.pumps]:
        if item.story not in stories:
            problems.append(f"{item.id}: no story '{item.story}'")
    for riser in fire.risers:
        missing = [s for s in (riser.fromStory, riser.toStory) if s not in stories]
        if missing:
            problems.append(f"{riser.id}: no story '{missing[0]}'")
        elif stories[riser.toStory] <= stories[riser.fromStory]:
            problems.append(f"{riser.id}: its top story must be above the story it starts at")
        if riser.shaft is not None and riser.shaft not in shafts:
            problems.append(f"{riser.id}: no shaft '{riser.shaft}'")
    for tank in fire.tanks:
        if tank.kind not in ("overhead", "underground"):
            problems.append(f"{tank.id}: a fire tank is overhead or underground, not {tank.kind}")
        if tank.story is not None and tank.story not in stories:
            problems.append(f"{tank.id}: no story '{tank.story}'")
        if tank.kind == "overhead" and tank.story is None:
            problems.append(f"{tank.id}: an overhead tank needs the story it stands on")
    if fire.pumpRoom is not None and fire.pumpRoom.story not in stories:
        problems.append(f"fire pump room: no story '{fire.pumpRoom.story}'")
    return problems


# ─────────────────────────────────────── geometry ───────────────────────────────────────


def _level(building: Building, story: str, order: list[str]) -> float:
    """A story's level above ground [m] (by its order, a storey each, without 06 BIM)."""
    if building.known and story in building.stories:
        return building.height(story) / 1000.0
    return order.index(story) * STOREY if story in order else 0.0


def _above(building: Building, story: str) -> str | None:
    order = building.ordered()
    i = order.index(story) if story in order else -1
    return order[i + 1] if 0 <= i < len(order) - 1 else None


def _extent(building: Building, story: str) -> tuple[float, float, float, float] | None:
    """The plan bounds of a story's slabs [mm] (minx, miny, maxx, maxy)."""
    roof = building.roof(story)
    return None if roof is None or roof.is_empty else tuple(roof.bounds)  # type: ignore[return-value]


def _tank_water(tank: dict[str, Any]) -> float:
    """Water a tank holds [m³] (partitions take their share)."""
    from saengine.plumbing.storage import water_weight

    return water_weight(tank) / 9.81


def _min_water(tank: Any, building: Building) -> float:
    """The lowest water level of a tank above ground [m] (its inside bottom)."""
    if tank.kind == "overhead" and tank.story is not None:
        return (building.height(tank.story) + (tank.base or 150.0)) / 1000.0
    top = tank.topLevel if tank.topLevel is not None else 150.0
    roof = tank.roof if tank.roof is not None else 125.0
    freeboard = tank.freeboard if tank.freeboard is not None else 300.0
    return (top - roof - freeboard - (tank.waterDepth or 0.0)) / 1000.0


# ─────────────────────────────────────── the report ───────────────────────────────────────


def _empty(problems: list[str], note: str) -> dict[str, Any]:
    return {
        "requirements": None, "stories": [], "demand": None, "hydraulics": None, "pumps": [],
        "pumpRoom": None, "storage": None, "tankDesigns": [], "supports": [],
        "testPressures": [], "openings": [], "crossings": [], "proposals": {"tanks": [],
        "pumps": []}, "quantities": {}, "checks": [], "summary": [], "notes": [note],
        "problems": problems, "method": METHOD,
    }  # fmt: skip


def fire_results(
    mep: MepModel,
    bim: Any = None,
    objects: Any = None,
    ground: float | None = None,
    tank_designs: list[dict[str, Any]] | None = None,
    hydraulics: bool = True,
) -> dict[str, Any]:
    """The fire report of parsed models (all but ``mep`` optional). ``tank_designs``: the
    designs of ``fire.tanks`` (:func:`design_fire_tanks`) when the integrator ran them."""
    building = Building.of(bim, ground)
    problems = references(mep, building)
    fire = mep.fire
    if fire is None:
        return _empty(problems, "07 MEP has no fire section")
    entries, notes = fire_stories(mep)
    checks: list[dict[str, Any]] = []
    order = building.ordered([s.story for s in entries]) if building.known else [
        s.story for s in entries]  # fmt: skip
    material = fire.supply.material

    # Stories.
    rows: list[dict[str, Any]] = []
    for entry in entries:
        if building.known and entry.story not in building.stories:
            continue
        area = entry.area or building.floor_area(entry.story)
        if not area:
            problems.append(f"fire: story {entry.story} has no area (enter it, or add its slabs)")
        group = OCCUPANCIES[entry.occupancy].group
        hazard = entry.hazard or T.hazard_of(group)
        if hazard is None:
            hazard = "lightII"
            notes.append(f"{entry.story}: group {group} has no Table 4.4.1 hazard: light hazard-II")
        rows.append({
            "story": entry.story, "occupancy": entry.occupancy, "group": group,
            "hazard": hazard, "area": round(area, 1), "undivided": entry.undivided or area,
            "level": _level(building, entry.story, order), "sprinklered": entry.sprinklered,
            "ceiling": entry.ceiling,
        })  # fmt: skip
    rows.sort(key=lambda r: r["level"])
    if not rows:
        return _empty(problems, "no fire stories: give the stories' use (here or in Plumbing)")
    levels = [building.height(s) / 1000.0 for s in building.stories] if building.known else [
        r["level"] for r in rows]  # fmt: skip
    height = max(max(levels, default=0.0), max(r["level"] for r in rows))
    storeys = sum(1 for r in rows if r["level"] >= 0)
    top = max(r["level"] for r in rows)
    req = requirements(
        rows, height=height, storeys=storeys, top_occupied=top, building=fire.building,
        hydrant_choice=fire.hydrant, detection_choice=fire.detection,
    )  # fmt: skip
    status = {s["system"]: s for s in req["systems"]}
    notes.extend(req["notes"])
    hydrant = status["hydrant"]["provided"]
    sprinkler_rules = {
        story for r in req["rules"] if "sprinklers" in r["required"] for story in r["stories"]
    }
    hazard = max((r["hazard"] for r in rows), key=T.HAZARDS.index)
    for r in rows:
        r["sprinklered"] = (
            r["sprinklered"] if r["sprinklered"] is not None else r["story"] in sprinkler_rules
        )
    sprinklers = any(r["sprinklered"] for r in rows)
    status["sprinklers"]["provided"] = sprinklers
    for r in rows:
        if r["story"] in sprinkler_rules and not r["sprinklered"]:
            checks.append(_check(f"Sprinklers on {r['story']}", 1, 0, "", False,
                                 "Part 4 requires sprinklers on this story; it is set off",
                                 T.cite("5.8.2", "(iii)")))  # fmt: skip

    # Per story: extinguishers, alarm, detectors, sprinklers.
    for r in rows:
        count, note = extinguishers(r["area"], r["hazard"])
        r["extinguishers"] = count if status["extinguishers"]["provided"] else 0
        r["extinguisherNote"] = note
        r["callPoints"] = (
            max(1, math.ceil(r["area"] / T.CALL_POINT_AREA - 1e-9))
            if status["manualAlarm"]["provided"] or status["automaticAlarm"]["provided"]
            else 0
        )
        r["detectors"] = (
            max(1, math.ceil(r["area"] / T.DETECTOR_AREA - 1e-9))
            if status["automaticAlarm"]["provided"]
            else 0
        )
        r["sprinklers"] = None
        if r["sprinklered"] and r["area"] > 0:
            bounds = _extent(building, r["story"])
            extent = (
                ((bounds[2] - bounds[0]) / 1000, (bounds[3] - bounds[1]) / 1000) if bounds else None
            )
            r["sprinklers"] = floor_sprinklers(
                r["area"], r["hazard"], r["ceiling"], extent, material
            )
            r["bounds"] = bounds
    if status["manualAlarm"]["provided"] or status["automaticAlarm"]["provided"]:
        notes.append(
            f"alarm: each floor a zone ({T.PAGES['4.6.2.2']}): {len(rows)} zones; call points one "
            f"per {T.CALL_POINT_AREA:g} m² (SAEngine), detectors one per {T.DETECTOR_AREA:g} m² "
            f"({T.MEMORY})"
        )

    # Risers.
    standpipes = [x for x in fire.risers if x.system in ("standpipe", "combined")]
    sprinkler_risers = [x for x in fire.risers if x.system in ("sprinkler", "combined")]
    max_floor = max((r["area"] for r in rows if r["level"] >= 0), default=0.0)
    if hydrant:
        need = max(1, math.ceil(max_floor / T.RISER_AREA - 1e-9))
        checks.append(_check(
            "Standpipe risers", need, len(standpipes), "risers", len(standpipes) >= need,
            f"one riser serving each {T.RISER_AREA:g} m² of floor (largest {max_floor:.0f} m²); "
            "at the stair landings, vestibules or in a non-combustible enclosure (Sec 4.2.3.9)",
            T.cite("4.4.1", " note **"),
        ))  # fmt: skip
    if sprinklers:
        sprinkled = [r for r in rows if r["sprinklers"]]
        need = max((r["sprinklers"]["risersNeeded"] for r in sprinkled), default=1)
        checks.append(_check(
            "Sprinkler risers", need, len(sprinkler_risers), "risers",
            len(sprinkler_risers) >= need,
            f"one riser serves at most {T.RISER_FLOOR_AREA[T.family(hazard)]:g} m² of floor",
            T.cite("4.4.5", " note ***"),
        ))  # fmt: skip

    # Source of the water, the pump and the suction.
    plumbing = mep.plumbing
    fire_tanks = [t for t in fire.tanks if t.kind in ("overhead", "underground")]
    if fire.supply.storage == "plumbingReserve" and plumbing is not None:
        source_tanks = [t for t in plumbing.tanks if t.kind in ("underground", "overhead")]
    else:
        source_tanks = fire_tanks
    source = next((t for t in source_tanks if t.kind == "underground"), None) or next(
        iter(source_tanks), None)  # fmt: skip
    pumps_entered = [p for p in fire.pumps]
    main = next((p for p in pumps_entered if p.duty == "main"), None)
    gravity = source is not None and source.kind == "overhead" and not pumps_entered
    pump_story = (main.story if main else fire.pumpRoom.story if fire.pumpRoom else
                  (source.story if source is not None and source.kind == "overhead" else None)
                  or (order[0] if order else None))  # fmt: skip
    if main is not None:
        pxy = (main.x, main.y)
    elif fire.pumpRoom is not None:
        xs = [p[0] for p in fire.pumpRoom.outline]
        ys = [p[1] for p in fire.pumpRoom.outline]
        pxy = (sum(xs) / len(xs), sum(ys) / len(ys))
    elif source is not None:
        pxy = (source.x, source.y)
    elif fire.risers:
        pxy = (fire.risers[0].x, fire.risers[0].y)
    else:
        pxy = (0.0, 0.0)
    pump_z = (_level(building, pump_story, order) if pump_story else 0.0) + T.PUMP_CENTRE
    water_z = _min_water(source, building) if source is not None else pump_z - T.PUMP_CENTRE
    if gravity:
        pump_z = water_z

    # Hydraulics.
    hyd: dict[str, Any] | None = None
    hydraulic_sprinkler = None
    sizes_used: dict[float, str] = {}
    if hydraulics and (hydrant or sprinklers) and fire.risers and building.known:
        try:
            hyd = _hydraulics(fire, building, rows, hazard, (pxy[0] / 1000, pxy[1] / 1000, pump_z),
                              standpipes, sprinkler_risers, hydrant, sprinklers, material,
                              sizes_used)  # fmt: skip
        except Exception as error:  # noqa: BLE001 - a partly entered network must not fail all
            notes.append(f"the hydraulic calculation failed: {error!r}")
            hyd = None
        if hyd is not None:
            _finish_pump_head(hyd, water_z)
            if hyd.get("sprinkler"):
                hydraulic_sprinkler = hyd["sprinkler"]["sprinklerFlow"]
    elif (hydrant or sprinklers) and not fire.risers:
        notes.append(
            "no fire risers yet: add the standpipe and sprinkler risers for the hydraulics"
        )
    elif (hydrant or sprinklers) and not building.known:
        notes.append("no 06 BIM: the hydraulic calculation needs the stories' levels")

    # Water and the reservoir.
    dem = None
    storage = None
    if hydrant or sprinklers:
        dem = S.demand(hazard, height, len(standpipes) or 1, hydrant, sprinklers,
                       hydraulic_sprinkler)  # fmt: skip
        if sprinklers:
            hand = hand_demand(hazard)
            dem["hand"] = hand
            dem["notes"].append(f"sprinkler demand by hand: {hand['note']}")
        storage = _storage(fire, mep, building, dem, fire_tanks, checks, notes)

    # Pumps.
    pump_rows: list[dict[str, Any]] = []
    proposals: dict[str, list[dict[str, Any]]] = {"tanks": storage.pop("proposals", []) if storage
                                                  else [], "pumps": []}  # fmt: skip
    room = None
    if hyd is not None and dem is not None:
        flow = max(dem["flow"], hyd["flow"])
        head = hyd["pumpHead"]
        hyd["suction"] = {"waterLevel": round(water_z, 2), "pumpLevel": round(pump_z, 2),
                          "lift": round(max(pump_z - water_z, 0.0), 2)}  # fmt: skip
        if gravity:
            top_outlet = (
                max(
                    (
                        building.height(r.toStory) / 1000.0
                        for r in standpipes
                        if r.toStory in building.stories
                    ),
                    default=water_z,
                )
                + T.OUTLET_HEIGHT
            )
            _gravity_check(fire, hyd, water_z, top_outlet, checks, notes)
        else:
            sets = S.pumps(flow, head, fire.supply.standby)
            pump_rows, room = _pumps(fire, sets, flow, head, checks, notes, building,
                                     pump_story, pxy, proposals)  # fmt: skip
            centrifugal = fire.supply.pumpType != "verticalTurbine"
            lift = pump_z - water_z
            if source is not None:
                checks.append(_check(
                    "No static suction lift", max(lift, 0.0), 0.0, "m",
                    not (centrifugal and lift > 0.0),
                    f"water at {water_z:.2f} m, pump at {pump_z:.2f} m: "
                    + (f"a {lift:.2f} m suction lift; set the pumps below the tank's bottom "
                       "(flooded suction) or use a vertical turbine pump" if lift > 0
                       else "flooded suction"),
                    T.PAGES["4.2.2.5"],
                ))  # fmt: skip
        _pressure_checks(hyd, rows, water_z, checks, notes, fire.supply.hose)
    elif dem is not None:
        sets = S.pumps(dem["flow"], T.PUMP_MIN_NET / 9.807 + height, fire.supply.standby)
        if not gravity:
            pump_rows, room = _pumps(fire, sets, dem["flow"], T.PUMP_MIN_NET / 9.807 + height,
                                     checks, notes, building, pump_story, pxy, proposals)  # fmt: skip
            notes.append("pump head estimated as the building height + 272 kPa until the "
                         "hydraulics can run")  # fmt: skip

    # Tank designs and the fire engine on a cover.
    designs = list(tank_designs or [])
    for d in designs:
        for c in d.get("checks", []):
            if not c.get("ok", True):
                checks.append(_check(f"{d.get('id')}: {c.get('name')}", c.get("demand") or 0,
                                     c.get("capacity"), c.get("unit", ""), False,
                                     c.get("note", ""), "tank design"))  # fmt: skip
        if d.get("error"):
            notes.append(f"{d.get('id')}: not designed ({d['error']})")
    if fire.supply.fireEngineOnCover and any(t.kind == "underground" for t in fire_tanks):
        w = fire.supply.fireEngineWeight or FIRE_ENGINE
        notes.append(
            f"the ground tank's cover carries the fire engine ({T.PAGES['4.2.3.8']}): designed "
            f"for {w:g} kN spread over its roof, and to be checked for two wheel loads of 40 % of "
            f"it ({0.4 * w:.0f} kN) 1.5 m apart on 750 x 750 mm ({T.PAGES['6:2.3.5']})"
            + ("" if fire.supply.fireEngineWeight else f"; weight {FIRE_ENGINE:g} kN, {T.MEMORY}")
        )

    # Sleeves and supports.
    openings = _riser_sleeves(mep, building, sizes_used, hyd, notes)
    crossings: list[dict[str, Any]] = []
    if fire.mains and building.known:
        beam = _main_sleeves(mep, building, objects, bim, notes)
        openings.extend(beam["openings"])
        crossings = beam["crossings"]
    for main_run in fire.mains:
        sizes_used.setdefault(main_run.diameter or 100.0, "hanger")
    heights = sorted(building.stories.values()) if building.known else []
    gaps = [b - a for a, b in itertools.pairwise(heights) if b > a]
    story_h = (sorted(gaps)[len(gaps) // 2] / 1000.0) if gaps else STOREY
    supports = S.support_loads(sizes_used, story_h)
    working = hyd["pumpHead"] * 9.807 if hyd else 0.0
    tests = S.test_pressures(working, sprinklers, hydrant)

    quantities = _quantities(fire, rows, hyd, status, pump_rows, sizes_used, building)
    failed = [c["name"] for c in checks if not c["ok"]]
    required = [s["label"] for s in req["systems"] if s["status"] == "required"]
    summary = [
        req["highRiseNote"],
        "Required: " + (", ".join(required) if required else "no fixed fire fighting"),
    ]
    if dem:
        summary.append(
            f"Fire water {dem['flow']:.0f} l/min for {dem['duration']} min: reservoir "
            f"{dem['volume']:.1f} m³"
        )
    if hyd:
        duty = max(hyd["flow"], dem["flow"] if dem else 0.0)
        summary.append(f"Pump duty {duty:.0f} l/min at {hyd['pumpHead']:.1f} m")
    if pump_rows:
        m = next((p for p in pump_rows if p["duty"] == "main"), None)
        if m:
            summary.append(f"Main fire pump {m['flow']:.0f} l/min x {m['head']:.0f} m, "
                           f"{m['power']:g} kW; pump room {room['area'] if room else 0:g} m²")  # fmt: skip
    summary.append(f"{len(failed)} of {len(checks)} checks fail" + (
        f": {', '.join(failed)}" if failed else ""))  # fmt: skip
    for r in rows:
        r.pop("bounds", None)
    return {
        "requirements": req,
        "stories": rows,
        "hazard": hazard,
        "height": round(height, 2),
        "demand": dem,
        "hydraulics": hyd,
        "pumps": pump_rows,
        "pumpRoom": room,
        "storage": storage,
        "tankDesigns": designs,
        "supports": supports,
        "testPressures": tests,
        "openings": openings,
        "crossings": crossings,
        "proposals": proposals,
        "quantities": quantities,
        "checks": checks,
        "summary": summary,
        "notes": notes,
        "problems": problems,
        "method": METHOD,
    }


def _hydraulics(fire: Any, building: Building, rows: list[dict[str, Any]], hazard: str,
                pump: tuple[float, float, float], standpipes: list[Any], sprinkler_risers: list[Any],
                hydrant: bool, sprinklers: bool, material: str, sizes_used: dict[float, str]
                ) -> dict[str, Any]:  # fmt: skip
    """The standpipe and sprinkler scenarios: the head each needs at the pump and the duty."""
    first_flow = T.FLOWS[hazard][1]
    stand_flow, _ = S.standpipe_flow(hazard, max(len(standpipes), 1))
    sprinkled = [r for r in rows if r["sprinklers"]]
    spr_est = max((r["sprinklers"]["designHeads"] * r["sprinklers"]["headFlow"] for r in sprinkled),
                  default=0.0) * 1.25  # fmt: skip
    total_est = (stand_flow if hydrant else 0.0) + (spr_est if sprinklers else 0.0)
    rating = S.pump_rating(total_est)
    largest_floor_heads = max((r["sprinklers"]["heads"] for r in sprinkled), default=0)

    def riser_run(riser: Any) -> N.RiserRun:
        floors = [(s, building.height(s) / 1000.0) for s in building.between(riser.fromStory,
                                                                               riser.toStory)]  # fmt: skip
        if riser.diameter:
            nominal = riser.diameter
        elif riser.system == "sprinkler":
            nominal = max(schedule_size(largest_floor_heads, hazard, material) or 150,
                          N.size_for(spr_est, material))  # fmt: skip
        else:
            carried = first_flow + (spr_est if riser.system == "combined" else 0.0)
            nominal = max(T.WET_RISER_MIN, S.pump_rating(first_flow)["discharge"],
                          N.size_for(carried, material))  # fmt: skip
        return N.RiserRun(riser.id, riser.system, riser.x / 1000, riser.y / 1000, floors, nominal)

    runs = {r.id: riser_run(r) for r in fire.risers}
    header = max([N.size_for(total_est, material, rating["discharge"]),
                  *(r.nominal for r in runs.values())])  # fmt: skip
    hose_m = T.HOSE_PRESSURE[fire.supply.hose] / N.KPA_PER_M
    out: dict[str, Any] = {"header": header, "risers": [], "standpipe": None, "sprinkler": None}
    for r in runs.values():
        sizes_used[r.nominal] = "riser"
        out["risers"].append({"id": r.id, "system": r.system, "size": r.nominal,
                              "given": any(x.id == r.id and x.diameter for x in fire.risers),
                              "floors": len(r.floors)})  # fmt: skip
    sizes_used.setdefault(header, "hanger")

    if hydrant and standpipes:
        best: dict[str, Any] | None = None
        for first in standpipes[:4]:
            net, take = N.build(pump, [runs[s.id] for s in standpipes], material, header)
            required: dict[str, float] = {}
            outlets = []
            others = [s for s in standpipes if s.id != first.id][: T.MAX_ADDITIONAL_STANDPIPES]
            for s, flow in [
                (first, first_flow),
                *((o, T.ADDITIONAL_STANDPIPE_FLOW) for o in others),
            ]:
                run = runs[s.id]
                if not run.floors:
                    continue
                story, z = run.floors[-1]
                node = N.outlet(net, run, take[s.id][story], z, run.nominal)
                net.demands[node] = flow
                required[node] = hose_m
                outlets.append({"riser": s.id, "story": story, "node": node, "flow": flow})
            if not required:
                continue
            sol = N.fixed_head(net, required)
            if best is None or sol["head"] > best["head"]:
                best = {**sol, "outlets": outlets, "first": first.id}
        if best is not None:
            for o in best["outlets"]:
                o["pressure"] = round(best["pressure"][o["node"]] * N.KPA_PER_M, 1)
            out["standpipe"] = {
                "first": best["first"],
                "flow": round(sum(o["flow"] for o in best["outlets"]), 1),
                "sourceHead": round(best["head"], 2),
                "outlets": best["outlets"],
                "pipes": _pipe_rows(best["pipes"]),
                "required": T.HOSE_PRESSURE[fire.supply.hose],
            }

    spr: dict[str, Any] | None = None
    if sprinklers and sprinkler_risers and sprinkled:
        served = [(r, x) for r in reversed(sprinkled) for x in sprinkler_risers
                  if r["story"] in dict(runs[x.id].floors)]  # fmt: skip
        if served:
            floor, riser = served[0]
            run = runs[riser.id]
            info = floor["sprinklers"]
            b = floor.get("bounds")
            start = (riser.x / 1000, riser.y / 1000)
            corners = ([(b[0] / 1000, b[1] / 1000), (b[2] / 1000, b[1] / 1000),
                        (b[0] / 1000, b[3] / 1000), (b[2] / 1000, b[3] / 1000)] if b else [start])  # fmt: skip
            far = max(corners, key=lambda c: abs(c[0] - start[0]) + abs(c[1] - start[1]))
            above = _above(building, floor["story"])
            head_z = (building.height(above) / 1000 - HEAD_BELOW) if above else (
                floor["level"] + STOREY - HEAD_BELOW)  # fmt: skip
            given = next(
                (m.diameter for m in fire.mains if m.story == floor["story"] and m.diameter), None
            )
            cross = given or info["mainSize"] or 100
            branch = schedule_size(info["headsPerBranch"], hazard, material) or 32
            sizes_used.setdefault(cross, "hanger")
            sizes_used.setdefault(branch, "hanger")
            net, take = N.build(pump, [run], material, header)
            takeoff = take[riser.id][floor["story"]]
            heads = N.design_area(net, takeoff, start, far, head_z, info,
                                  {"cross": cross, "branch": branch})  # fmt: skip
            sol = N.emitter_head(net, heads, info["headFlow"], {})
            flows = [sol["flow"][h] for h in heads]
            valve = f"{takeoff}:FCV"
            spr = {"riser": riser, "story": floor["story"], "takeoff": sol["pressure"][takeoff]}
            out["sprinkler"] = {
                "story": floor["story"],
                "riser": riser.id,
                "heads": len(heads),
                "headFlow": info["headFlow"],
                "least": round(min(flows), 1),
                "most": round(max(flows), 1),
                "sprinklerFlow": round(sum(flows), 1),
                "flow": round(sum(flows), 1),
                "sourceHead": round(sol["head"], 2),
                "leastPressure": round(min(sol["pressure"][h] for h in heads) * N.KPA_PER_M, 1),
                "valvePressure": round(sol["pressure"][valve] * N.KPA_PER_M, 1),
                "designArea": info["designArea"],
                "density": info["density"],
                "cross": cross,
                "branch": branch,
                "pipes": _pipe_rows(sol["pipes"]),
            }
    scenarios = [s for s in (out["standpipe"], out["sprinkler"]) if s]
    if not scenarios:
        raise ValueError("no riser reaches a floor to calculate")
    # The duty: what the pump feeds at once. Sprinklers the more of Table 4.4.1 and the
    # hydraulic demand, drawn at the riser's take-off of the design floor at the pressure the
    # design area needs there; with the standpipes' flows at their outlets for a combined system
    # (Sec 4.2.3.5).
    duty = scenarios[0]
    sprinkler_demand = 0.0
    if spr is not None:
        sprinkler_demand = max(T.FLOWS[hazard][0], out["sprinkler"]["sprinklerFlow"])
        ids = [spr["riser"].id]
        if out["standpipe"]:
            ids += [o["riser"] for o in out["standpipe"]["outlets"] if o["riser"] not in ids]
        net, take = N.build(pump, [runs[i] for i in ids], material, header)
        required: dict[str, float] = {}
        for o in (out["standpipe"] or {}).get("outlets", []):
            run = runs[o["riser"]]
            node = N.outlet(net, run, take[o["riser"]][o["story"]], run.floors[-1][1], run.nominal)
            net.demands[node] = o["flow"]
            required[node] = hose_m
        takeoff = take[spr["riser"].id][spr["story"]]
        net.demands[takeoff] = sprinkler_demand
        required[takeoff] = spr["takeoff"]
        sol = N.fixed_head(net, required)
        duty = {
            "flow": round(sum(net.demands.values()), 1),
            "sourceHead": round(sol["head"], 2),
            "sprinklerDemand": round(sprinkler_demand, 1),
            "standpipeFlow": round(sum(net.demands.values()) - sprinkler_demand, 1),
            "pipes": _pipe_rows(sol["pipes"]),
        }
        out["duty"] = duty
    out["flow"] = duty["flow"]
    out["sourceHead"] = max(s["sourceHead"] for s in [*scenarios, duty])
    out["governing"] = "combined" if spr is not None and out["standpipe"] else (
        "sprinkler" if spr is not None else "standpipe")  # fmt: skip
    out["maxVelocity"] = max(
        max((p["velocity"] for p in s["pipes"]), default=0.0) for s in [*scenarios, duty]
    )
    return out


def _pipe_rows(pipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keep = ("id", "role", "nominal", "length", "equivalent", "flow", "velocity", "loss")
    return [{k: (round(p[k], 2) if isinstance(p[k], float) else p[k]) for k in keep}
            for p in pipes if p["flow"] > 0.05]  # fmt: skip


def _finish_pump_head(hyd: dict[str, Any], water_z: float) -> None:
    hyd["pumpHead"] = round(hyd["sourceHead"] - water_z, 2)


def _storage(fire: Any, mep: MepModel, building: Building, dem: dict[str, Any],
             fire_tanks: list[Any], checks: list[dict[str, Any]], notes: list[str]
             ) -> dict[str, Any]:  # fmt: skip
    """The fire water stored against the reservoir required, and the tank SAEngine proposes."""
    from saengine.plumbing.storage import dimensions

    need = dem["volume"]
    out: dict[str, Any] = {"required": need, "provided": 0.0, "tanks": [], "proposals": [],
                           "notes": []}  # fmt: skip
    if fire.supply.storage == "plumbingReserve":
        plumbing = mep.plumbing
        if plumbing is None:
            notes.append("fire water in the plumbing tanks, but 07 MEP has no plumbing")
            have = 0.0
        else:
            from saengine.plumbing.storage import fire_reserve

            have, why = fire_reserve(plumbing, building)
            out["notes"].extend(why)
        out["provided"] = have
        checks.append(_check(
            "Fire reserve in the plumbing tanks", need, have, "m³", have >= need - 1e-6,
            f"the plumbing tanks' fire reserve against {need:.1f} m³; separate draw-offs keep it "
            f"for fire fighting only ({T.PAGES['4.2.3.7']})"
            + ("" if have >= need - 1e-6 else f"; set plumbing.supply.fireReserve to {math.ceil(need)} m³"),
            T.PAGES["4.2.2.3"],
        ))  # fmt: skip
        return out
    for t in fire_tanks:
        data = t.model_dump(mode="json", exclude_none=True)
        water = _tank_water(data)
        out["tanks"].append({"id": t.id, "kind": t.kind, "volume": round(water, 2)})
        out["provided"] += water
    if not fire_tanks:
        dims = dimensions(need, "underground")
        taken = {t.id for t in fire.tanks} | {p.id for p in fire.pumps} | {
            r.id for r in fire.risers}  # fmt: skip
        tid = _new_id("FT", taken)
        x, y = (fire.risers[0].x, fire.risers[0].y) if fire.risers else (0.0, 0.0)
        footprint = building.footprint()
        if footprint is not None and not footprint.is_empty:
            minx, miny, _, _ = footprint.bounds
            x, y = minx - 4000.0, miny + dims["width"] / 2
        out["proposals"].append({
            "id": tid, "kind": "underground", "x": round(x), "y": round(y),
            "length": dims["length"], "width": dims["width"], "waterDepth": dims["waterDepth"],
            "freeboard": dims["freeboard"], "compartments": dims["compartments"],
            "construction": "rc", "sized": True,
        })  # fmt: skip
        out["notes"].append(
            f"proposed {tid}: {dims['length']:g} x {dims['width']:g} mm, water {dims['waterDepth']:g}"
            f" mm, {dims['volume']:.1f} m³ (as the plumbing reservoirs; placed beside the building)"
        )
    if fire_tanks and out["provided"] < need - 1e-6:
        # The first tank grown to make up the shortfall (its plan kept, deeper; as the plumbing
        # reservoirs are sized).
        first = fire_tanks[0]
        own = out["tanks"][0]["volume"]
        dims = dimensions(need - (out["provided"] - own), first.kind, first)
        out["proposals"].append({
            **first.model_dump(mode="json", exclude_none=True),
            **{k: dims[k] for k in ("length", "width", "waterDepth", "freeboard", "compartments")},
            "sized": True,
        })  # fmt: skip
        out["notes"].append(
            f"{first.id} holds {own:.1f} m³ of the {need:.1f} m³ needed: proposed "
            f"{dims['length']:g} x {dims['width']:g} mm, water {dims['waterDepth']:g} mm"
        )
    provided = out["provided"]
    checks.append(_check(
        "Fire reservoir", need, provided, "m³", bool(fire_tanks) and provided >= need - 1e-6,
        (f"{len(fire_tanks)} fire tank(s) hold {provided:.1f} m³" if fire_tanks else
         "no fire tank yet: Propose adds one")
        + f"; kept for fire fighting only ({T.PAGES['4.2.3.7']})",
        T.PAGES["4.2.2.3"],
    ))  # fmt: skip
    out["provided"] = round(provided, 2)
    return out


def _pumps(fire: Any, sets: list[dict[str, Any]], flow: float, head: float,
           checks: list[dict[str, Any]], notes: list[str], building: Building,
           story: str | None, pxy: tuple[float, float],
           proposals: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:  # fmt: skip
    """The pump sets required against those entered, the proposals and the pump room."""
    rows = []
    taken = {p.id for p in fire.pumps} | {t.id for t in fire.tanks} | {r.id for r in fire.risers}
    offset = 0.0
    for s in sets:
        entered = [p for p in fire.pumps if p.duty == s["duty"]]
        row = {"duty": s["duty"], "label": FIRE_PUMP_DUTIES[s["duty"]], "flow": s["flow"],
               "head": s["head"], "power": s["power"], "count": s["count"],
               "length": s["length"], "width": s["width"], "height": s["height"],
               "operatingWeight": s["operatingWeight"],
               "ids": [p.id for p in entered]}  # fmt: skip
        rows.append(row)
        if entered:
            p = entered[0]
            if s["duty"] != "jockey":
                q, h = p.flow or 0.0, p.head or 0.0
                ok = q >= s["flow"] - 1e-6 and h >= s["head"] - 0.05
                checks.append(_check(
                    f"{p.id} duty", s["head"], h, "m", ok,
                    f"{q:g} l/min at {h:g} m against {s['flow']:g} l/min at {s['head']:.1f} m "
                    f"(Table 4.4.2 rating; net pressure at least {T.PUMP_MIN_NET:g} kPa)",
                    f"{T.PAGES['4.2.2.5']}; {T.PAGES['4.4.2']}",
                ))  # fmt: skip
        elif story is not None:
            pid = _new_id({"main": "FP", "standby": "FPS", "jockey": "JP"}[s["duty"]], taken)
            proposals["pumps"].append({
                "id": pid, "duty": s["duty"], "story": story,
                "x": round(pxy[0] + offset), "y": round(pxy[1]),
                "length": s["length"], "width": s["width"], "height": s["height"],
                "flow": s["flow"], "head": s["head"], "power": s["power"],
                "operatingWeight": s["operatingWeight"], "sized": True,
            })  # fmt: skip
            offset += s["width"] + T.PUMP_CLEARANCE * 1000
    standby = [p for p in fire.pumps if p.duty == "standby"]
    checks.append(_check(
        "Secondary (standby) fire pump", 1, len(standby), "sets", bool(standby),
        f"a secondary pump on a {'diesel engine' if fire.supply.standby == 'diesel' else 'alternate supply'}"
        + ("" if standby else ": Propose adds one"),
        T.PAGES["4.2.2.5"],
    ))  # fmt: skip
    if not [p for p in fire.pumps if p.duty == "main"]:
        checks.append(_check("Main fire pump", 1, 0, "sets", False,
                             "no main fire pump yet: Propose adds one", T.PAGES["4.2.2.5"]))  # fmt: skip
    room = S.pump_room(sets)
    if fire.pumpRoom is not None:
        from shapely.geometry import Polygon

        poly = Polygon(fire.pumpRoom.outline).buffer(0)
        area = poly.area / 1e6
        minx, miny, maxx, maxy = poly.bounds
        short, long_ = sorted((maxx - minx, maxy - miny))
        need_short, need_long = sorted((room["length"], room["width"]))
        ok = area >= room["area"] - 1e-6 and short >= need_short - 1 and long_ >= need_long - 1
        room["provided"] = round(area, 1)
        checks.append(_check(
            "Fire pump room", room["area"], area, "m²", ok,
            f"{short / 1000:.1f} x {long_ / 1000:.1f} m against {need_short / 1000:.1f} x "
            f"{need_long / 1000:.1f} m; {room['note']}",
            T.PAGES["4.2.2.5"],
        ))  # fmt: skip
    else:
        notes.append(f"pump room: {room['length'] / 1000:.1f} x {room['width'] / 1000:.1f} m "
                     f"({room['area']:g} m²) needed; draw it in 07 MEP to check it")  # fmt: skip
    return rows, room


def _gravity_check(fire: Any, hyd: dict[str, Any], water_z: float, top_outlet: float,
                   checks: list[dict[str, Any]], notes: list[str]) -> None:  # fmt: skip
    """Sec 4.2.2.2(a): a roof gravity tank alone needs its static height over the top outlet
    (31 m, 20.5 m first aid, 62 m combined) and the head the hydraulics ask for."""
    combined = any(r.system == "combined" for r in fire.risers)
    need = T.GRAVITY_HEIGHT["combined" if combined else fire.supply.hose]
    static = water_z - top_outlet
    ok = static >= need - 1e-6 and hyd["sourceHead"] <= water_z + 1e-6
    checks.append(_check(
        "Roof gravity tank head", need, static, "m", ok,
        f"the tank's lowest water {static:.1f} m above the top outlet against {need:g} m, and "
        f"{hyd['sourceHead'] - top_outlet + T.OUTLET_HEIGHT:.1f} m the hydraulics need; "
        "otherwise fire pumps of the required size (Sec 4.2.2.2(b))",
        T.PAGES["4.2.2.2"],
    ))  # fmt: skip
    notes.append("roof gravity tank with no fire pumps: fed by its static head alone")


def _pressure_checks(hyd: dict[str, Any], rows: list[dict[str, Any]], water_z: float,
                     checks: list[dict[str, Any]], notes: list[str], hose: str) -> None:  # fmt: skip
    """Net pressure, the highest pressure at shut-off and the floors needing pressure reducing
    valves (Sec 4.2.2.5, 4.2.3.3)."""
    _finish_pump_head(hyd, water_z)
    rated = max(hyd["pumpHead"], T.PUMP_MIN_NET / N.KPA_PER_M)
    churn = water_z + 1.4 * rated  # NFPA 20: shut-off at most 140 % of rated (MEMORY)
    low = min(r["level"] for r in rows)
    pmax = (churn - low) * N.KPA_PER_M
    checks.append(_check(
        "Highest pressure (pump at shut-off)", pmax, T.MAX_PRESSURE, "kPa",
        pmax <= T.MAX_PRESSURE + 1e-6,
        f"churn taken as 140 % of the rated head ({T.MEMORY}), at the lowest floor "
        f"({low:.1f} m)" + ("; divide the building into pressure zones (Sec 4.5)"
                             if pmax > T.MAX_PRESSURE else ""),
        T.PAGES["4.2.3.3"],
    ))  # fmt: skip
    prv = []
    source = water_z + rated
    for r in rows:
        p = (source - r["level"] - T.OUTLET_HEIGHT) * N.KPA_PER_M
        if p > T.PRV_PRESSURE:
            prv.append(r["story"])
    hyd["prvStories"] = prv
    if prv:
        notes.append(
            f"outlets over {T.PRV_PRESSURE:g} kPa at the rated head on {', '.join(prv)}: approved "
            f"pressure reducing devices there ({T.PAGES['4.2.3.3']})"
        )
    if hyd.get("standpipe"):
        least = min(o["pressure"] for o in hyd["standpipe"]["outlets"])
        need = T.HOSE_PRESSURE[hose]
        checks.append(_check("Residual pressure at the top outlets", need, least, "kPa",
                             least >= need - 0.5,
                             f"hydraulically most remote standpipe {hyd['standpipe']['first']}",
                             T.PAGES["4.2.3.3"]))  # fmt: skip
    checks.append(_check(
        "Velocity in the fire mains", hyd["maxVelocity"], T.MAX_VELOCITY, "m/s",
        hyd["maxVelocity"] <= T.MAX_VELOCITY + 1e-6,
        "SAEngine practice limit; BNBC sizes by the hydraulic calculation", T.PAGES["4.2.3.4"],
    ))  # fmt: skip
    for r in hyd["risers"]:
        if r["system"] != "sprinkler" and r["size"] < T.WET_RISER_MIN:
            checks.append(_check(f"{r['id']} size", T.WET_RISER_MIN, r["size"], "mm", False,
                                 "a wet riser is not less than 100 mm", T.PAGES["4.2.4"]))  # fmt: skip


def _riser_sleeves(mep: MepModel, building: Building, sizes_used: dict[float, str],
                   hyd: dict[str, Any] | None, notes: list[str]) -> list[dict[str, Any]]:  # fmt: skip
    """Sleeves (07 MEP openings) where the fire risers cross the slabs."""
    from saengine.plumbing.sleeves import _in_shaft, sleeve_diameter

    fire = mep.fire
    if fire is None or not building.known:
        return []
    by_id = {r["id"]: r["size"] for r in (hyd or {}).get("risers", [])}
    existing = {o.id for o in mep.openings}
    out = []
    for riser in fire.risers:
        nominal = riser.diameter or by_id.get(riser.id) or T.WET_RISER_MIN
        for story in building.between(riser.fromStory, riser.toStory)[1:]:
            if _in_shaft(mep, riser, story, building) is not None:
                continue
            slab = building.slab_at(story, riser.x, riser.y)
            if slab is None:
                notes.append(f"{riser.id}: no slab of {story} under ({riser.x:g}, {riser.y:g})")
                continue
            if building.in_hole(slab, riser.x, riser.y):
                continue
            oid = f"FS-{riser.id}-{story}"
            if oid in existing:
                continue
            out.append({
                "id": oid, "host": slab, "kind": "sleeve", "shape": "circle",
                "diameter": sleeve_diameter(nominal, "GI"), "position": {"x": riser.x, "y": riser.y},
                "service": f"DN{nominal:g} {riser.system} riser {riser.id}",
            })  # fmt: skip
    if fire.risers:
        notes.append("riser sleeves: the steel pipe's outside diameter + 50 mm, next standard size "
                     "(SAEngine practice, as the plumbing sleeves)")  # fmt: skip
    return out


def _main_sleeves(mep: MepModel, building: Building, objects: Any, bim: Any,
                  notes: list[str]) -> dict[str, Any]:  # fmt: skip
    """Sleeves through the beams the fire mains cross at their level (circular, in the web)."""
    from saengine.electrical.risers import Frame, path_beam_crossings, tray_levels
    from saengine.plumbing.sleeves import outside_diameter, sleeve_diameter

    frame = Frame.of(bim, objects)
    existing = {o.id for o in mep.openings}
    openings, crossings = [], []
    for main in mep.fire.mains:
        nominal = main.diameter or 100.0
        od = outside_diameter(nominal, "GI")
        probe = SimpleNamespace(id=main.id, story=main.story, path=main.path, bottom=main.bottom,
                                height=od, width=od)  # fmt: skip
        levels = tray_levels(probe, building, frame)
        if levels is None:
            notes.append(f"{main.id}: its story or the floor above is not in the building model")
            continue
        seen: dict[str, int] = {}
        for cross in path_beam_crossings(main.path, frame.beams_at(levels["level"])):
            beam = cross["beam"]
            if beam.depth <= 0:
                notes.append(f"{main.id}: beam {beam.id} has no depth in 04 Objects")
                continue
            beam_bottom = beam.top - beam.depth
            record = {"main": main.id, "beam": beam.id, "point": list(cross["point"]),
                      "passesBelow": levels["top"] <= beam_bottom + 1e-6}  # fmt: skip
            crossings.append(record)
            if record["passesBelow"]:
                continue
            sleeve = sleeve_diameter(nominal, "GI")
            centre = (levels["bottom"] + levels["top"]) / 2
            soffit = beam.top - levels["thickness"]
            if centre - sleeve / 2 < beam_bottom or centre + sleeve / 2 > soffit:
                record["fits"] = False
                notes.append(
                    f"{main.id} at {beam.id}: a {sleeve:g} mm sleeve does not fit in the web "
                    f"below the slab; run the main {levels['top'] - beam_bottom:.0f} mm lower to "
                    "pass below the beam"
                )
                continue
            record["fits"] = True
            seen[beam.id] = seen.get(beam.id, 0) + 1
            oid = f"FB-{main.id}-{beam.id}" + (f"-{seen[beam.id]}" if seen[beam.id] > 1 else "")
            if oid in existing:
                continue
            openings.append({
                "id": oid, "host": beam.id, "kind": "sleeve", "shape": "circle",
                "diameter": sleeve,
                "position": {"distance": round(cross["distance"], 1),
                             "elevation": round(centre - beam_bottom, 1)},
                "service": f"DN{nominal:g} fire main {main.id}",
            })  # fmt: skip
    return {"openings": openings, "crossings": crossings}


def _quantities(fire: Any, rows: list[dict[str, Any]], hyd: dict[str, Any] | None,
                status: dict[str, Any], pumps: list[dict[str, Any]], sizes_used: dict[float, str],
                building: Building) -> dict[str, Any]:  # fmt: skip
    """Pipes by size [m], heads, valves, hose cabinets, pumps and devices for the bill."""
    pipes: dict[float, float] = {}

    def add(size: float, length: float) -> None:
        pipes[size] = pipes.get(size, 0.0) + length

    sizes = {r["id"]: r["size"] for r in (hyd or {}).get("risers", [])}
    for riser in fire.risers:
        floors = building.between(riser.fromStory, riser.toStory) if building.known else []
        if len(floors) >= 2:
            rise = (building.stories[floors[-1]] - building.stories[floors[0]]) / 1000.0
            add(riser.diameter or sizes.get(riser.id) or T.WET_RISER_MIN, rise + T.OUTLET_HEIGHT)
    for main in fire.mains:
        length = sum(
            math.hypot(b[0] - a[0], b[1] - a[1])
            for a, b in zip(main.path, main.path[1:], strict=False)
        )
        add(main.diameter or 100.0, length / 1000.0)
    heads = 0
    for r in rows:
        info = r.get("sprinklers")
        if not info:
            continue
        heads += info["heads"]
        # branch lines: a head's spacing of pipe each; the cross main the floor's square side
        branch = schedule_size(min(info["heads"], 8), r["hazard"], fire.supply.material) or 32
        add(branch, info["heads"] * info["spacing"])
        if info["mainSize"]:
            add(info["mainSize"], math.sqrt(r["area"]))
    standpipes = [x for x in fire.risers if x.system in ("standpipe", "combined")]
    outlets = sum(len(building.between(x.fromStory, x.toStory)) if building.known else 1
                  for x in standpipes)  # fmt: skip
    sprinkled = sum(1 for r in rows if r.get("sprinklers"))
    hydrant = status["hydrant"]["provided"]
    return {
        "pipes": [{"size": s, "length": round(v, 1)} for s, v in sorted(pipes.items())],
        "heads": heads,
        "landingValves": outlets if hydrant else 0,
        "hoseCabinets": outlets if hydrant else 0,
        "floorValves": sprinkled,
        "riserValves": len(fire.risers) * 2,
        "siamese": int(hydrant) + int(bool(heads)),
        "extinguishers": sum(r["extinguishers"] for r in rows),
        "callPoints": sum(r["callPoints"] for r in rows),
        "detectors": sum(r["detectors"] for r in rows),
        "pumps": [
            {
                "duty": p["duty"],
                "count": p["count"],
                "power": p["power"],
                "flow": p["flow"],
                "head": p["head"],
            }
            for p in pumps
        ],
        "note": "pipes: risers and entered mains as drawn; sprinkler pipework of each floor "
        "estimated from its heads (branch lines at the spacing, the cross main the floor's "
        "side); valves: landing valve and hose cabinet a floor a standpipe (Sec 4.2.3.10-"
        "4.2.3.11), a control set a sprinklered floor, gate and check valves a riser (Sec "
        "4.2.3.2), a Siamese connection a system (Sec 4.2.3.15, 4.2.11.1)",
    }


# ─────────────────────────────────────── tanks ───────────────────────────────────────


def tank_options(fire: Any, tank: Any) -> dict[str, Any] | None:
    """The tank design options of a fire tank: the fire engine on a ground tank's cover (Sec
    4.2.3.8) as a roof load spread over the cover."""
    if not (fire.supply.fireEngineOnCover and tank.kind == "underground"):
        return None
    w = fire.supply.fireEngineWeight or FIRE_ENGINE
    walls = tank.walls or 200.0
    area = ((tank.length or 1.0) + 2 * walls) * ((tank.width or 1.0) + 2 * walls) / 1e6
    return {"roofLive": round(max(1.0, w / max(area, 1e-6)), 2)}


def read_fire_designs(root: str | Path) -> dict[str, Any]:
    """The cached fire tank designs ``{key: {"id", "tank", "result"}}`` (empty when none), as
    :func:`saengine.plumbing.project.read_designs` (the bill takes their bars)."""
    try:
        data = json.loads((Path(root) / DESIGNS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = data.get("designs") if isinstance(data, dict) else None
    return entries if isinstance(entries, dict) else {}


def design_fire_tanks(root: str | Path, mep: MepModel, materials_text: str | None,
                      soil_text: str | None, proposals: list[dict[str, Any]] | None = None
                      ) -> list[dict[str, Any]]:  # fmt: skip
    """The designs of ``fire.tanks`` (:func:`saengine.plumbing.tanks.design_tank`), cached in
    :data:`DESIGNS_FILE` by the tank, its materials, the soil report and the options (apart from
    the plumbing tanks' cache); ``{id, kind, error}`` for one that cannot be designed yet."""
    from saengine.library.materials import MaterialLibrary
    from saengine.plumbing.project import _design_key, finite, tank_stamp
    from saengine.plumbing.tanks import TankContext, design_tank

    fire = mep.fire
    if fire is None or not fire.tanks:
        return []
    root = Path(root)
    materials = None
    if materials_text:
        try:
            materials = MaterialLibrary.model_validate_json(materials_text)
        except ValueError:
            materials = None
    try:
        text = (root / DESIGNS_FILE).read_text(encoding="utf-8")
        old = json.loads(text).get("designs") or {}
    except (OSError, ValueError, AttributeError):
        old = {}
    by_id = {str(p.get("id")): p for p in proposals or []}
    kept: dict[str, Any] = {}
    out = []
    for t in fire.tanks:
        if t.kind not in ("overhead", "underground"):
            continue
        tank = t.model_dump(mode="json", exclude_none=True)
        if t.id in by_id:
            tank = {**by_id[t.id], **tank}
        options = tank_options(fire, t)
        key = _design_key(tank, materials_text, soil_text, options)
        entry = old.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("result"), dict):
            result = entry["result"]
        else:
            try:
                context = TankContext.build(materials, soil_text, options, root / MODELS_DIR)
                result = finite(design_tank(tank, context))
            except Exception as error:  # noqa: BLE001 - one tank must not fail the report
                message = str(error).strip().splitlines()[0] if str(error).strip() else repr(error)
                result = {"id": t.id, "kind": t.kind, "error": message}
        out.append(result)
        if "error" not in result:
            kept[key] = {"id": t.id, "tank": tank_stamp(tank), "result": result}
    if kept.keys() != old.keys():
        try:
            (root / DESIGNS_FILE).parent.mkdir(parents=True, exist_ok=True)
            (root / DESIGNS_FILE).write_text(json.dumps({"designs": kept}) + "\n", encoding="utf-8")
        except OSError:
            pass
    return out


# ─────────────────────────────────────── files ───────────────────────────────────────


def _read(root: Path, relative: str) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _load(project_root: str | Path, mep_text: str | None = None) -> dict[str, Any]:
    from saengine.library.bim import BuildingModel
    from saengine.library.objects import ObjectLibrary

    root = Path(project_root)
    problems: list[str] = []
    text = mep_text if mep_text is not None else _read(root, MEP_FILE)
    try:
        mep = parse(text)
    except ValueError as error:
        raise ValueError(f"{MEP_FILE} is not valid: {error}") from error
    bim = objects = None
    bim_text = _read(root, "06 BIM/bim.json")
    if bim_text:
        try:
            bim = BuildingModel.model_validate_json(bim_text)
        except ValueError as error:
            problems.append(f"06 BIM/bim.json is not valid: {error}")
    objects_text = _read(root, "04 Objects/objects.json")
    if objects_text:
        try:
            objects = ObjectLibrary.model_validate_json(objects_text)
        except ValueError as error:
            problems.append(f"04 Objects is not valid: {error}")
    ground = None
    settings_text = _read(root, "02 Project Settings/project-settings.json")
    if settings_text:
        try:
            ground = (json.loads(settings_text).get("foundation") or {}).get("groundLevel")
        except ValueError:
            pass
    return {"mep": mep, "bim": bim, "objects": objects,
            "ground": ground if isinstance(ground, int | float) else None,
            "materials": _read(root, "03 Materials/materials.json"),
            "soil": _read(root, "01 Soil Report/soil-report.json"),
            "problems": problems}  # fmt: skip


def fire_report(project_root: str | Path, mep_text: str | None = None, *,
                designs: bool = True) -> dict[str, Any]:  # fmt: skip
    """The fire report of a project (``mep_text``: unsaved ``07 MEP/mep.json``). Never raises:
    ``{problems}`` when 07 MEP cannot be read. JSON-safe (no infinities)."""
    from saengine.plumbing.project import finite, missing_sleeves

    try:
        loaded = _load(project_root, mep_text)
    except ValueError as error:
        return {"problems": [str(error)]}
    mep = loaded["mep"]
    tank_designs = None
    if designs and mep.fire is not None and mep.fire.tanks:
        tank_designs = design_fire_tanks(project_root, mep, loaded["materials"], loaded["soil"])
    try:
        result = fire_results(mep, loaded["bim"], loaded["objects"], loaded["ground"],
                              tank_designs)  # fmt: skip
    except Exception as error:  # noqa: BLE001 - a partly entered model must not fail the RPC
        return {"problems": [*loaded["problems"], f"the fire sizing failed: {error!r}"]}
    result["problems"] = [*loaded["problems"], *result["problems"]]
    result["openingsProposed"] = len(result.get("openings") or [])
    result["openings"] = missing_sleeves(mep, result.get("openings") or [])
    if mep.fire is not None and mep.fire.risers and result.get("summary"):
        from saengine.plumbing.project import sleeves_check

        check = sleeves_check(result["openings"])
        check["name"] = "Sleeves for the fire risers and mains"
        check["note"] = check["note"].replace("(Plumbing)", "(Fire)")
        result["checks"].append(check)
        failed = [c["name"] for c in result["checks"] if not c["ok"]]
        result["summary"][-1] = f"{len(failed)} of {len(result['checks'])} checks fail" + (
            f": {', '.join(failed)}" if failed else ""
        )
    return finite(result)


def fire_propose(project_root: str | Path, mep_text: str | None = None) -> dict[str, Any]:
    """The tanks and pumps SAEngine proposes (07 MEP ``fire.tanks`` and ``fire.pumps``)."""
    report = fire_report(project_root, mep_text, designs=False)
    return report.get("proposals") or {"tanks": [], "pumps": []}


def fire_openings(project_root: str | Path, mep_text: str | None = None) -> list[dict[str, Any]]:
    """The sleeves the fire risers and mains still need (07 MEP ``openings`` format)."""
    return fire_report(project_root, mep_text, designs=False).get("openings", [])


def fire_equipment(mep: MepModel, materials: Any = None) -> tuple[list[dict[str, Any]], list[str]]:
    """The fire pumps and overhead fire tanks of 07 MEP as 07 MEP ``equipment`` (for the
    analysis loads): a pump with no size or weight takes the typical set of its power (or of
    its flow and head); pumps vibrate. Items linked to an equipment, or standing where an
    equipment of their story is, are left to it. Returns (equipment dicts, notes)."""
    from saengine.mep.loads import footprint_covers

    fire = mep.fire
    if fire is None:
        return [], []
    out, notes = [], []
    plumbing_overhead = [
        t for t in (mep.plumbing.tanks if mep.plumbing is not None else []) if t.kind == "overhead"
    ]
    for p in fire.pumps:
        if p.equipment:
            notes.append(f"{p.id}: its weight is that of equipment {p.equipment}")
            continue
        under = next(
            (e for e in mep.equipment if e.story == p.story and footprint_covers(e, p.x, p.y)), None
        )
        if under is not None:
            notes.append(f"{p.id}: stands where equipment {under.id} is; its weight is taken as "
                         f"{under.id}'s (link them in 07 MEP, or delete {under.id})")  # fmt: skip
            continue
        kw = p.power or (
            S.motor(S.power(p.flow, p.head, T.PUMP_EFFICIENCY)) if p.flow and p.head else None
        )
        typical = S.typical_set(p.duty, kw or 15.0, fire.supply.standby)
        missing = [k for k in ("length", "width", "operatingWeight") if getattr(p, k) is None]
        if missing:
            notes.append(
                f"{p.id}: {', '.join(missing)} of a typical set of {kw or 15:g} kW ({T.MEMORY})"
            )
        entry = {
            "id": f"EQ-{p.id}", "name": FIRE_PUMP_DUTIES[p.duty], "kind": "pump",
            "story": p.story, "x": p.x, "y": p.y,
            "length": p.length or typical["length"], "width": p.width or typical["width"],
            "operatingWeight": p.operatingWeight or typical["operatingWeight"],
            "vibrating": True,
        }  # fmt: skip
        if p.height or typical.get("height"):
            entry["height"] = p.height or typical["height"]
        out.append(entry)
    for t in fire.tanks:
        if t.kind != "overhead":
            if t.kind == "underground":
                notes.append(f"{t.id}: a ground tank; it stands on the ground, not on the frame")
            continue
        if t.equipment is not None:
            notes.append(f"{t.id}: its weight is that of equipment {t.equipment}")
            continue
        same = next((p for p in plumbing_overhead if p.story == t.story
                     and abs(p.x - t.x) <= (p.length or 0) / 2
                     and abs(p.y - t.y) <= (p.width or 0) / 2), None)  # fmt: skip
        if same is not None:
            notes.append(f"{t.id}: stands where plumbing tank {same.id} is; its weight is taken "
                         f"as {same.id}'s (enter the tank once: in Plumbing with its fire "
                         f"reserve, or here)")  # fmt: skip
            continue
        try:
            from saengine.plumbing.tanks import tank_equipment

            entry = tank_equipment(t.model_dump(mode="json", exclude_none=True),
                                   {"materials": materials}, basis=True)  # fmt: skip
        except (ValueError, KeyError) as error:
            notes.append(f"{t.id}: {error}; not loaded")
            continue
        basis = entry.pop("emptyBasis", None)
        entry["name"] = f"Fire water tank {t.id}"
        out.append(entry)
        notes.append(f"{t.id}: overhead fire tank, {entry['emptyWeight']:g} kN empty"
                     + (f" ({basis})" if basis else "")
                     + f" and {entry['operatingWeight'] - entry['emptyWeight']:.1f} kN of water")  # fmt: skip
    return out, notes
