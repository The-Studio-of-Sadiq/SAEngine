"""The cooling loads of a project (BNBC 2020 Part 8 Chapter 2), for the structural coordination.

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
from saengine.hvac.gains import design_conditions, zone_gains
from saengine.hvac.geometry import zones as make_zones
from saengine.library.mep import HVAC_PLANT_KINDS, MEP_FILE, MepModel, hvac_references, parse
from saengine.plumbing.building import Building

RESULTS_DIR = "07 MEP/hvac.results"
RESULTS_FILE = f"{RESULTS_DIR}/loads.json"
#: Version of the cached runs: a change to the method invalidates them.
CACHE_VERSION = 2
#: kW per ton of refrigeration (12 000 Btu/h).
KW_PER_TON = 3.51685

METHOD = [
    (
        "Zones: one thermal zone per story of 06 BIM (its slabs' outline), walls on the outline, "
        "windows a centred strip of each facade's window-to-wall ratio (when not given, the least "
        "window area for a room as deep as the plan behind the facade: 20 % below 8 m, 30 % to "
        f"14 m, 35 % beyond, BNBC 2020 {T.PAGES['4.5.1']})."
    ),
    (
        f"Outside design conditions: Table 8.2.2's 2 % dry bulb and mean coincident wet bulb "
        f"({T.PAGES['2.12.2']}), its daily range; design days on the 21st of May to September; "
        "ASHRAE clear sky."
    ),
    (
        f"Inside: 24 °C (Sec 2.12.2.2) within the use's Table 8.2.1 range, the range's upper "
        f"humidity ({T.PAGES['8.2.1']})."
    ),
    (
        f"Outdoor air: Table 8.2.3 per person and per floor area, summed (the breathing-zone "
        f"method of ASHRAE 62.1, whose rates the table gives) ({T.PAGES['8.2.3']}); occupants "
        "from its default density unless entered."
    ),
    (
        f"Lighting: Part 3 Table 3.4.5's maximum lighting power density ({T.PAGES['3.4.5']}) unless "
        "entered."
    ),
    (
        "Loads: EnergyPlus version 26.2.0 ideal loads air systems on the design days (the peak of "
        "each zone's supply air cooling, outdoor air included); design airflow from Sizing:Zone at "
        "13 °C supply; components from the Zone Component Load Summary at the zone's sensible peak."
    ),
]


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
) -> dict[str, Any]:
    """The cooling loads of parsed models (``bim``: a BuildingModel; ``location``: the Project
    Settings site location). ``cache``: the stored ``{stamp, run}`` of an EnergyPlus run, reused
    (not run again) when its stamp matches; the result's ``run`` key holds a fresh run to store.
    ``folder``: where EnergyPlus runs (kept); a temporary folder when None.
    ``run_energyplus`` False: EnergyPlus is not started (the editor's report after each edit,
    Run All); its cached run is still used when its stamp matches, else the estimate is given
    with ``calculated`` False ("loads not calculated: run Calculate Loads")."""
    hvac = mep.hvac
    if hvac is None:
        return {"engine": None, "zones": [], "total": 0.0, "notes": [],
                "problems": ["07 MEP has no hvac section"]}  # fmt: skip
    building = Building.of(bim, ground)
    problems = hvac_references(mep, building.stories) if building.known else []
    if not building.known:
        problems.append("06 BIM is needed for the zones (stories and slabs)")
    zoning = make_zones(building, hvac)
    problems.extend(zoning.problems)
    design = design_conditions(hvac, location)
    env = envelope_choice(hvac.envelope)
    populations = _populations(mep, building)
    gains = {}
    for zone in zoning.zones:
        if zone.conditioned or zone.entry is not None:
            g = zone_gains(zone, hvac, populations.get(zone.story))
            gains[zone.name] = g
            problems.extend(g.problems if zone.conditioned else [])
    conditioned = [z for z in zoning.zones if z.conditioned]
    notes = [*design.sources, *env.notes, *zoning.notes]
    for zone in zoning.zones:
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
        "method": METHOD,
        "design": {
            "station": design.station.key, "outdoorDB": design.db, "outdoorWB": design.wb,
            "dailyRange": design.range, "latitude": design.latitude,
            "longitude": design.longitude,
        },
        "envelope": {
            "wall": env.wall.label, "roof": env.roof.label, "glazing": env.glazing.label,
            "uWall": round(env.uWall, 3), "uRoof": round(env.uRoof, 3),
            "uGlazing": env.uGlazing, "shgc": env.shgc, "shading": env.shading,
        },
        "assumptions": list(T.ASSUMPTIONS),
    }  # fmt: skip
    if not conditioned:
        return {**base, "engine": None, "zones": [], "total": 0.0, "notes": notes,
                "problems": [*problems, "no conditioned story to work out"]}  # fmt: skip
    model = EP.build(zoning.zones, gains, env, design)
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
    out_zones = []
    for zone in conditioned:
        g = gains[zone.name]
        row = {
            "story": zone.story,
            "zone": zone.name,
            "use": g.use,
            "area": zone.area,
            "volume": zone.volume,
            "occupants": g.occupants,
            "indoorDB": g.indoorDB,
            "indoorRH": g.indoorRH,
            "sources": g.sources,
        }
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
            )  # fmt: skip
        else:
            if run is not None:
                problems.append(f"{zone.story}: EnergyPlus gave no cooling: the estimate is given")
            row.update(F.zone_load(zone, g, env, design), engine=F.ENGINE)
        row["glazing"] = row["breakdown"]["glazingConduction"] + row["breakdown"]["glazingSolar"]
        row["breakdown"]["glazing"] = row["glazing"]
        row["peakMonth"], row["peakHour"] = row["peak"].get("month"), row["peak"].get("time")
        row["tons"] = row["total"] / KW_PER_TON
        row["density"] = row["total"] * 1000.0 / zone.area if zone.area else None
        row["supply"], row["freshAir"] = row["airflow"], row["outdoorAir"]
        out_zones.append(row)
    total = sum(z["total"] for z in out_zones)
    result = {
        **base,
        "engine": EP.ENGINE if run is not None else F.ENGINE,
        "engineLabel": EP.ENGINE if run is not None else F.LABEL,
        "zones": out_zones,
        "total": total,
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
    result = _round(result)
    result["stamp"] = stamp
    result["cached"] = cached
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
) -> dict[str, Any]:
    """The cooling loads of a project (``mep_text``: unsaved ``07 MEP/mep.json``):
    ``{engine: "EnergyPlus version 26.2.0" | "estimate", zones: [{story, area, sensible,
    latent, total, airflow, peak, breakdown}], total, notes, problems, ...}`` (kW, m³/s).
    ``run_energyplus`` False: only a cached EnergyPlus run of this input is used, else the
    estimate (``calculated`` False), so that it is fast (:func:`hvac_results`).
    Never raises: ``{problems}`` when 07 MEP cannot be read."""
    root = Path(project_root)
    try:
        mep, bim, location, ground, problems = _load(root, mep_text)
    except ValueError as error:
        return {"engine": None, "zones": [], "total": 0.0, "notes": [], "problems": [str(error)]}
    old = read_cache(root) if cache else None
    try:
        result = hvac_results(
            mep, bim, location, ground, energyplus=energyplus,
            use_energyplus=use_energyplus, cache=old, run_energyplus=run_energyplus,
        )  # fmt: skip
    except Exception as error:  # noqa: BLE001 - a partly entered model must not fail the RPC
        return {"engine": None, "zones": [], "total": 0.0, "notes": [],
                "problems": [*problems, f"the cooling load failed: {error!r}"]}  # fmt: skip
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

#: hvac plant kinds -> 07 MEP equipment kinds; the rotating ones vibrate (BNBC 2020 Part 6
#: Sec 2.3.12, the impact allowance of Table 6.2.6).
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
