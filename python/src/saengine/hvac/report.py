"""The cooling loads of a project (the code pack's air-conditioning: BNBC 2020 Part 8 Chapter 2
in the default pack), for the structural coordination.

:func:`hvac_loads` reads ``07 MEP/mep.json`` (its ``hvac``), ``06 BIM/bim.json`` (stories and
slabs) and ``02 Project Settings`` (site location, ground level), builds one thermal zone per
story, and returns each conditioned zone's design cooling load (sensible, latent, total, kW),
design airflow, outdoor air, peak time and load components, with the building's total. The loads
come from EnergyPlus version 26.2.0 when it is found (:func:`saengine.hvac.energyplus.
find_energyplus`), else from the estimate of :mod:`saengine.hvac.fallback`. A successful
EnergyPlus run is cached in ``07 MEP/hvac.results/loads.json`` under the stamp of its model
(the epJSON) and the EnergyPlus used: the same model reuses the run without running EnergyPlus
again, while the notes and problems (references of plant, ducts and shafts, labels) are always
worked out afresh. A failed run and the estimate are never cached (the next call tries
EnergyPlus again; the estimate takes no time).

:func:`hvac_results` does the same from the parsed models, without files or cache.
:func:`plant_equipment` turns a piece of hvac plant into 07 MEP equipment (its weight on the
structure).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from saengine.hvac import energyplus as EP
from saengine.hvac import fallback as F
from saengine.hvac import tables as T
from saengine.hvac.constructions import envelope as envelope_choice
from saengine.hvac.gains import design_conditions, room_gains, single_room_gains, zone_gains
from saengine.hvac.geometry import zones as make_zones
from saengine.library.mep import HVAC_PLANT_KINDS, MEP_FILE, MepModel, hvac_references, parse
from saengine.plumbing.building import Building

RESULTS_DIR = "07 MEP/hvac.results"
RESULTS_FILE = f"{RESULTS_DIR}/loads.json"
#: Version of the cached runs: a change to the method invalidates them.
CACHE_VERSION = 3
#: kW per ton of refrigeration (12 000 Btu/h).
KW_PER_TON = 3.51685


def method() -> list[str]:
    """How the loads are found, with the values and clauses of the code pack in force (the
    clause numbers are those of the default pack)."""
    share = T.LEAST_WINDOW_SHARE
    return [
        (
            "Zones: one thermal zone per story of 06 BIM (its slabs' outline), walls on the "
            "outline, windows a centred strip of each facade's window-to-wall ratio (when not "
            "given, the least window area for a room as deep as the plan behind the facade: "
            f"{share.shallow * 100:g} % below {share.shallowDepth:g} m, {share.medium * 100:g} % "
            f"to {share.deepDepth:g} m, {share.deep * 100:g} % beyond, {T.PAGES['4.5.1']})."
        ),
        (
            f"Outside design conditions: Table 8.2.2's 2 % dry bulb and mean coincident wet bulb "
            f"({T.PAGES['2.12.2']}), its daily range; design days on the 21st of May to "
            "September; ASHRAE clear sky."
        ),
        (
            f"Inside: {T.INDOOR_DB:g} °C (Sec 2.12.2.2) within the use's Table 8.2.1 range, the "
            f"range's upper humidity ({T.PAGES['8.2.1']})."
        ),
        (
            f"Outdoor air: Table 8.2.3 per person and per floor area, summed (the breathing-zone "
            f"method of ASHRAE 62.1, whose rates the table gives) ({T.PAGES['8.2.3']}); "
            "occupants from its default density unless entered."
        ),
        (
            f"Lighting: Part 3 Table 3.4.5's maximum lighting power density ({T.PAGES['3.4.5']}) "
            "unless entered."
        ),
        (
            "Loads: EnergyPlus version 26.2.0 ideal loads air systems on the design days (the "
            "peak of each zone's supply air cooling, outdoor air included); design airflow from "
            "Sizing:Zone at 13 °C supply; components from the Zone Component Load Summary at the "
            "zone's sensible peak."
        ),
    ]


def __getattr__(name: str) -> Any:
    if name == "METHOD":  # the former constant: the method of the pack in force
        return method()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


#: The method's last line when the loads are the estimate (EnergyPlus not installed, failed, or
#: not run for this input): what was actually used, not EnergyPlus.
ESTIMATE_METHOD = (
    "Loads: SAEngine's steady-state block estimate per zone at the design day's maximum dry bulb "
    "(EnergyPlus was not run for this input): walls and roof U A (To - Ti + a I / ho) with the "
    "sol-air excess, glazing U A (To - Ti) + A SHGC I, people, lights and equipment at their "
    "design levels, outdoor air sensible and latent (ASHRAE Fundamentals Ch 1 psychrometrics); "
    "design airflow from the sensible load at 13 °C supply. An estimate for coordinating the "
    "plant's size and weight, not a design."
)


def _method(estimate: bool) -> list[str]:
    """:func:`method`, its EnergyPlus line replaced by :data:`ESTIMATE_METHOD` for the
    estimate."""
    lines = method()
    return [*lines[:-1], ESTIMATE_METHOD] if estimate else lines


def _stamp(data: Any) -> str:
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _round(value: Any, digits: int = 3) -> Any:
    """Floats to ``digits`` decimals, and those below 1 to 4 significant figures (humidity
    ratios in kg/kg, small flows in m³/s keep their precision)."""
    if isinstance(value, float):
        if value != 0.0 and abs(value) < 1.0 and math.isfinite(value):
            return float(f"{value:.4g}")
        return round(value, digits)
    if isinstance(value, dict):
        return {k: _round(v, digits) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v, digits) for v in value]
    return value


def _populations(mep: MepModel, building: Building) -> dict[str, float]:
    """Persons per story from the plumbing of 07 MEP (Table 8.2.3 has no density for
    dwellings)."""
    if mep.plumbing is None:
        return {}
    from saengine.plumbing.demand import story_population

    out = {}
    for entry in mep.plumbing.stories:
        population, _ = story_population(entry, building)
        if population > 0:
            out[entry.story] = population
    return out


def hvac_results(
    mep: MepModel,
    bim: Any = None,
    location: str | None = None,
    ground: float | None = None,
    *,
    energyplus: str | Path | None = None,
    use_energyplus: bool = True,
    cache: dict[str, Any] | None = None,
    folder: Path | None = None,
    run_energyplus: bool = True,
    rooms: Any = None,
    zoning: str | None = None,
    arch: Any = None,
) -> dict[str, Any]:
    """The cooling and heating loads of parsed models (``bim``: a BuildingModel; ``location``:
    the Project Settings site location). ``zoning``: ``"room"`` (default when architecture rooms
    exist) or ``"story"`` (per-storey block zones, for speed). See module docstring for cache and
    EnergyPlus options."""
    from saengine.mep.rooms import with_rooms

    mep, _ = with_rooms(mep, rooms)
    hvac = mep.hvac
    if hvac is None:
        return {"engine": None, "zones": [], "stories": [], "total": 0.0, "heatingTotal": 0.0,
                "notes": [], "problems": ["07 MEP has no hvac section"]}  # fmt: skip
    building = Building.of(bim, ground)
    problems = hvac_references(mep, building.stories) if building.known else []
    if not building.known:
        problems.append("06 BIM is needed for the zones (stories and slabs)")
    mode = zoning if zoning in ("room", "story") else getattr(hvac, "zoning", "room")
    if mode not in ("room", "story"):
        mode = "room"
    zoning_res = make_zones(building, hvac, rooms=rooms, by_room=(mode == "room"), arch=arch)
    problems.extend(zoning_res.problems)
    design = design_conditions(hvac, location)
    env = envelope_choice(hvac.envelope)
    populations = _populations(mep, building)
    room_by_id = (
        {r.id: r for s in rooms.stories.values() for r in s.rooms} if rooms is not None else {}
    )
    gains = {}
    for zone in zoning_res.zones:
        if zone.conditioned or zone.entry is not None:
            story_rooms = rooms.story(zone.story) if rooms is not None else None
            if zone.room is not None and zone.room in room_by_id:
                g = single_room_gains(
                    zone, room_by_id[zone.room], hvac, story_rooms, populations.get(zone.story)
                )
            elif zone.roomLabel == "Unallocated":
                g = zone_gains(zone, hvac, populations.get(zone.story))
            else:
                groups = story_rooms.hvac_groups() if story_rooms is not None else []
                if zone.entry is not None and zone.entry.gainsFrom == "rooms" and not groups:
                    problems.append(
                        f"{zone.story}: gains from the rooms asked for, but the architecture has no "
                        "rooms with a use on this story: the typed use is taken"
                    )
                g = room_gains(zone, hvac, groups, populations.get(zone.story))
            gains[zone.name] = g
            problems.extend(g.problems if zone.conditioned else [])
    conditioned = [z for z in zoning_res.zones if z.conditioned]
    notes = [*design.sources, *env.notes, *zoning_res.notes]
    for zone in zoning_res.zones:
        if not zone.conditioned:
            flow, source = EP.unconditioned_air(zone, gains.get(zone.name))
            notes.append(
                f"{zone.story}: not conditioned; ventilated with {flow:.2f} m³/s of outside air "
                f"({source}), its heat reaches the stories next to it"
            )
    if hvac.system == "none":
        notes.append("hvac system 'none': the loads are what air-conditioning would have to meet")
    for zone in conditioned:
        if design.db - gains[zone.name].indoorDB > T.MAX_INDOOR_OUTDOOR_DIFFERENCE:
            notes.append(
                f"{zone.story}: outdoor and indoor dry bulbs differ by more than 11 °C: an "
                f"ante-room is needed ({T.PAGES['2.7.2.1b']})"
            )
    base = {
        "method": method(),
        "zoning": mode,
        "design": {
            "station": design.station.key, "outdoorDB": design.db, "outdoorWB": design.wb,
            "dailyRange": design.range, "latitude": design.latitude,
            "longitude": design.longitude, "heatingOutdoorDB": design.heatingDB,
            "infiltrationACH": design.infiltrationACH,
        },
        "envelope": {
            "wall": env.wall.label, "roof": env.roof.label, "glazing": env.glazing.label,
            "uWall": round(env.uWall, 3), "uRoof": round(env.uRoof, 3),
            "uGlazing": env.uGlazing, "shgc": env.shgc, "shading": env.shading,
        },
        "assumptions": list(T.ASSUMPTIONS),
    }  # fmt: skip
    if not conditioned:
        return {**base, "engine": None, "zones": [], "stories": [], "total": 0.0,
                "heatingTotal": 0.0, "notes": notes,
                "problems": [*problems, "no conditioned story to work out"]}  # fmt: skip
    model = EP.build(zoning_res.zones, gains, env, design)
    exe = EP.find_energyplus(energyplus) if use_energyplus else None
    stamp = _stamp(
        {"version": CACHE_VERSION, "model": model.epjson, "engine": str(exe) if exe else None}
    )
    run = None
    cached = False
    if (
        exe is not None
        and cache
        and cache.get("stamp") == stamp
        and isinstance(cache.get("run"), dict)
    ):
        run, cached = cache["run"], True
    elif exe is not None and not run_energyplus:
        notes.append(
            "loads not calculated with EnergyPlus for this input: the estimate is shown; run "
            "Calculate Loads"
        )
    elif exe is not None:
        try:
            run = EP.run(model, exe, folder)
        except (EP.EnergyPlusError, OSError) as error:
            problems.append(f"{error}; the estimate is given instead")
    if run is not None:
        for warning in run.get("geometryWarnings") or []:
            problems.append(f"EnergyPlus: {warning[:400]}")
    else:
        notes.append(f"{F.LABEL}: install EnergyPlus or set {EP.ENV_VAR}")
    other_cool: dict[str, float] = {}
    other_heat: dict[str, float] = {}
    for z in zoning_res.zones:
        gz = gains.get(z.name)
        t_c = gz.indoorDB if gz is not None else design.db
        t_h = gz.heatingIndoorDB if gz is not None else design.heatingDB
        for s in z.surfaces:
            other_cool[s.name] = t_c
            other_heat[s.name] = t_h
    out_zones = []
    for zone in conditioned:
        g = gains[zone.name]
        row: dict[str, Any] = {
            "story": zone.story,
            "zone": zone.name,
            "room": zone.room,
            "roomLabel": zone.roomLabel,
            "use": g.use,
            "area": zone.area,
            "volume": zone.volume,
            "occupants": g.occupants,
            "indoorDB": g.indoorDB,
            "indoorRH": g.indoorRH,
            "heatingIndoorDB": g.heatingIndoorDB,
            "sources": g.sources,
            "gainsFrom": g.gainsFrom,
            "rooms": g.rooms,
        }
        heat_est = F.heating_load(zone, g, env, design, other_temps=other_heat)
        if run is not None and "problem" not in run["zones"].get(zone.name, {"problem": 1}):
            r = run["zones"][zone.name]
            components = dict(r["components"])
            breakdown = {k: components.get(k, 0.0) for k in EP.COMPONENTS}
            breakdown["ventilation"] = r["ventilation"]["total"]
            row.update(
                sensible=r["sensible"], latent=r["latent"], total=r["total"],
                airflow=r["airflow"], outdoorAir=r["ventilation"]["flow"], peak=r["peak"],
                breakdown=breakdown, ventilation=r["ventilation"],
                componentsTotal=components.get("total"), engine=EP.ENGINE,
                heating=r.get("heating", heat_est["total"]),
                heatingAirflow=r.get("heatingAirflow", heat_est["airflow"]),
                heatingBreakdown=heat_est["breakdown"],
            )  # fmt: skip
        else:
            if run is not None:
                problems.append(f"{zone.story}: EnergyPlus gave no cooling: the estimate is given")
            row.update(
                F.zone_load(zone, g, env, design, other_temps=other_cool),
                engine=F.ENGINE,
                heating=heat_est["total"],
                heatingAirflow=heat_est["airflow"],
                heatingBreakdown=heat_est["breakdown"],
            )
        row["glazing"] = row["breakdown"]["glazingConduction"] + row["breakdown"]["glazingSolar"]
        row["breakdown"]["glazing"] = row["glazing"]
        row["peakMonth"], row["peakHour"] = row["peak"].get("month"), row["peak"].get("time")
        row["tons"] = row["total"] / KW_PER_TON
        row["density"] = row["total"] * 1000.0 / zone.area if zone.area else None
        row["supply"], row["freshAir"] = row["airflow"], row["outdoorAir"]
        out_zones.append(row)
    stories_map: dict[str, dict[str, Any]] = {}
    for z in out_zones:
        s = stories_map.setdefault(
            z["story"],
            {
                "story": z["story"],
                "area": 0.0,
                "sensible": 0.0,
                "latent": 0.0,
                "total": 0.0,
                "heating": 0.0,
                "airflow": 0.0,
                "outdoorAir": 0.0,
                "rooms": [],
            },
        )
        s["area"] += z["area"]
        s["sensible"] += z["sensible"]
        s["latent"] += z["latent"]
        s["total"] += z["total"]
        s["heating"] += z["heating"]
        s["airflow"] += z["airflow"] or 0.0
        s["outdoorAir"] += z["outdoorAir"] or 0.0
        if z.get("room") is not None:
            s["rooms"].append(z["room"])
    total = sum(z["total"] for z in out_zones)
    heating_total = sum(z["heating"] for z in out_zones)
    result = {
        **base,
        "engine": EP.ENGINE if run is not None else F.ENGINE,
        "engineLabel": EP.ENGINE if run is not None else F.LABEL,
        "zones": out_zones,
        "stories": list(stories_map.values()),
        "total": total,
        "heatingTotal": heating_total,
        "tons": total / KW_PER_TON,
        "sensible": sum(z["sensible"] for z in out_zones),
        "latent": sum(z["latent"] for z in out_zones),
        "airflow": sum(z["airflow"] or 0.0 for z in out_zones),
        "outdoorAir": sum(z["outdoorAir"] or 0.0 for z in out_zones),
        "notes": notes,
        "problems": problems,
    }
    if run is not None:
        result["building"] = run["building"]
        result["energyplus"] = {
            "seconds": run["seconds"], "warnings": run["warnings"], "envelope": run["envelope"],
        }  # fmt: skip
        notes.append(
            "total: the sum of the zones' peaks (each sized for its own); building: the "
            "coincident peak of all zones (for central plant)"
        )
    result["method"] = _method(run is None)
    result = _round(result)
    result["stamp"] = stamp
    result["cached"] = cached
    # Whether Calculate Loads can run EnergyPlus at all: the editor checks it before starting.
    result["energyPlusFound"] = exe is not None
    result["calculated"] = run is not None or exe is None or run_energyplus
    if run is not None and not cached:
        result["run"] = run
    return result


# ───────────────────────────────────────── files ─────────────────────────────────────────


def _read(root: Path, relative: str) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _load(root: Path, mep_text: str | None):
    from saengine.library.bim import BuildingModel

    problems = []
    text = mep_text if mep_text is not None else _read(root, MEP_FILE)
    try:
        mep = parse(text)
    except ValueError as error:
        raise ValueError(f"{MEP_FILE} is not valid: {error}") from error
    bim = None
    bim_text = _read(root, "06 BIM/bim.json")
    if bim_text:
        try:
            bim = BuildingModel.model_validate_json(bim_text)
        except ValueError as error:
            problems.append(f"06 BIM/bim.json is not valid: {error}")
    location = ground = None
    settings_text = _read(root, "02 Project Settings/project-settings.json")
    if settings_text:
        try:
            data = json.loads(settings_text)
            location = (data.get("site") or {}).get("location")
            ground = (data.get("foundation") or {}).get("groundLevel")
        except (ValueError, AttributeError):
            pass
    if not isinstance(ground, int | float):
        ground = None
    return mep, bim, location, ground, problems


def read_cache(root: str | Path) -> dict[str, Any] | None:
    text = _read(Path(root), RESULTS_FILE)
    if not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def hvac_loads(
    project_root: str | Path,
    mep_text: str | None = None,
    *,
    energyplus: str | Path | None = None,
    use_energyplus: bool = True,
    cache: bool = True,
    run_energyplus: bool = True,
    zoning: str | None = None,
) -> dict[str, Any]:
    """The cooling and heating loads of a project (``mep_text``: unsaved ``07 MEP/mep.json``):
    ``{engine: "EnergyPlus version 26.2.0" | "estimate", zones: [{story, room, area, sensible,
    latent, total, heating, airflow, peak, breakdown}], total, heatingTotal, notes, problems,
    ...}`` (kW, m³/s).
    ``run_energyplus`` False: only a cached EnergyPlus run of this input is used, else the
    estimate (``calculated`` False), so that it is fast (:func:`hvac_results`).
    ``zoning``: ``"room"`` (default when architecture rooms exist) or ``"story"``.
    Never raises: ``{problems}`` when 07 MEP cannot be read."""
    root = Path(project_root)
    try:
        mep, bim, location, ground, problems = _load(root, mep_text)
    except ValueError as error:
        return {"engine": None, "zones": [], "stories": [], "total": 0.0, "heatingTotal": 0.0,
                "notes": [], "problems": [str(error)]}  # fmt: skip
    old = read_cache(root) if cache else None
    from saengine.library import architecture as arch_lib
    from saengine.mep.rooms import read_room_inputs

    rooms, problem = read_room_inputs(root, mep.plumbing)
    if problem:
        problems.append(problem)
    arch = None
    arch_text = _read(root, arch_lib.ARCHITECTURE_FILE)
    if arch_text:
        try:
            arch = arch_lib.parse(arch_text)
        except ValueError:
            arch = None
    try:
        result = hvac_results(
            mep, bim, location, ground, energyplus=energyplus,
            use_energyplus=use_energyplus, cache=old, run_energyplus=run_energyplus,
            rooms=rooms, zoning=zoning, arch=arch,
        )  # fmt: skip
    except Exception as error:  # noqa: BLE001 - a partly entered model must not fail the RPC
        return {"engine": None, "zones": [], "stories": [], "total": 0.0, "heatingTotal": 0.0,
                "notes": [], "problems": [*problems, f"the cooling load failed: {error!r}"]}  # fmt: skip
    result["problems"] = [*problems, *result.get("problems", [])]
    stamp = result.get("stamp")
    run = result.pop("run", None)  # only a fresh, successful EnergyPlus run
    if cache and stamp and run is not None:
        try:
            path = root / RESULTS_FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_name(f"{path.name}.{os.getpid()}.tmp")
            partial.write_text(
                json.dumps({"stamp": stamp, "run": run}, indent=1, default=str), encoding="utf-8"
            )
            os.replace(partial, path)  # whole or not at all, for a concurrent reader
        except OSError as error:
            result["problems"].append(f"the results could not be cached: {error}")
    return result


# ─────────────────────────────────────── plant weights ───────────────────────────────────────

#: hvac plant kinds -> 07 MEP equipment kinds; the rotating ones vibrate (the code pack's
#: impact allowance, BNBC 2020 Part 6 Sec 2.3.12 and Table 6.2.6 in the default pack).
PLANT_EQUIPMENT = {
    "chiller": ("chiller", True),
    "coolingTower": ("other", True),
    "ahu": ("ahu", True),
    "fcu": ("other", False),
    "vrfOutdoor": ("other", True),
    "splitOutdoor": ("other", True),
    "pump": ("pump", True),
    "exhaustFan": ("other", True),
    "freshAirUnit": ("ahu", True),
}


def plant_equipment(item: dict[str, Any], taken: set[str] | None = None) -> dict[str, Any] | None:
    """A piece of 07 MEP ``hvac.plant`` as 07 MEP equipment (id ``EQ-<id>``) so that its weight
    loads the structure; None when it has no operating weight or footprint yet, or when an
    equipment of that id is already in ``taken`` (never counted twice)."""
    if not item.get("operatingWeight") or not item.get("length") or not item.get("width"):
        return None
    eid = f"EQ-{item['id']}"
    if taken is not None and (eid in taken or item["id"] in taken):
        return None
    kind, vibrating = PLANT_EQUIPMENT.get(item.get("kind", ""), ("other", False))
    out = {
        "id": eid,
        "name": f"{HVAC_PLANT_KINDS.get(item.get('kind', ''), 'HVAC plant')} {item['id']}",
        "kind": kind,
        "story": item["story"],
        "x": item["x"],
        "y": item["y"],
        "length": item["length"],
        "width": item["width"],
        "operatingWeight": item["operatingWeight"],
        "vibrating": vibrating,
    }
    if item.get("height"):
        out["height"] = item["height"]
    return out
