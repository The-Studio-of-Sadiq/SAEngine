"""The plumbing report of a project (BNBC 2020 Part 8), for the structural coordination.

:func:`plumbing_report` reads ``07 MEP/mep.json`` (its ``plumbing``), ``06 BIM/bim.json`` (stories,
slabs, openings), ``01 Soil Report/soil-report.json`` (soak well) and ``02 Project
Settings`` (ground level) when present, and returns the demand, storage, risers, stacks,
rainwater, septic tank and soak well, the proposed tanks and sleeves, and the checks.
:func:`plumbing_size_tanks` and :func:`plumbing_sleeves` return just the proposals, in the
format of ``07 MEP`` (``plumbing.tanks`` and ``openings``).

:func:`plumbing_results` does the same from the parsed models, without files.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from saengine.library.mep import MEP_FILE, MepModel, PlumbingTank, check, parse
from saengine.plumbing import tables as T
from saengine.plumbing.building import Building
from saengine.plumbing.demand import daily_demand, drainage_units, hunter_flow, supply_units
from saengine.plumbing.drainage import STACKS, building_drains, soil_stack, vent_stack
from saengine.plumbing.rainwater import rainwater
from saengine.plumbing.septic import separations, septic_tank, soak_well
from saengine.plumbing.sleeves import proposed_openings, shaft_checks
from saengine.plumbing.storage import dimensions, tank_drain, tank_overflow, volumes, water_weight
from saengine.plumbing.supply import (
    SUPPLY,
    capacity,
    down_feed,
    heads,
    pump,
    pump_main,
    supply_riser,
)

METHOD = [
    (
        "Demand (BNBC 2020 Part 8 Sec 5.5-5.6, Tables 8.5.1(a)-(d)): population x lpcd; peak hourly "
        "= daily / 16 h x 2.2 (Eq 8.5.1)."
    ),
    (
        "Storage (Sec 5.9.1.2(c)): roof tank 1/2, underground reservoir 1 x the daily demand, each "
        "+ 1 h fire reserve (Part 4 Table 4.4.1 standpipe flow) for a building above 33 m (Part 3 "
        "Sec 2.4.4); two compartments (Sec 5.9.2.1); drain and overflow Tables 8.5.2, 8.5.3."
    ),
    (
        "Risers (Appendix O, Tables 8.O.1, 8.5.4, 8.5.5, 8.5.6, Sec 5.10.1(c)(ii)): fixture units, "
        "Hunter flow, velocity and 1.6 m/100 m friction (Hazen-Williams)."
    ),
    "Drainage (Sec 6.10, Tables 8.6.12-8.6.16, 8.6.2): stacks, branches, vents, building drain.",
    (
        "Rainwater (Chapter 7, Appendix R, Tables 8.7.2-8.7.4): catchment by nearest drain, leaders, "
        "gutters, storm drain; harvesting Sec 7.4.1, 7.8.9."
    ),
    (
        "Septic tank (Sec 6.9.12, Appendix S) and soak well (Sec 6.9.15, Table 8.6.10); separations "
        "Tables 8.6.8, 8.6.9."
    ),
    "Sleeves and shafts: SAEngine practice (pipe OD + 50 mm; (OD + 100)² per pipe in a shaft).",
]


def _check(name: str, demand: float, cap: float | None, unit: str, ok: bool, note: str):
    util = demand / cap if cap else (0.0 if demand == 0 else math.inf)
    return {
        "name": name, "demand": demand, "capacity": cap, "unit": unit,
        "utilisation": util, "ok": bool(ok), "note": note,
    }  # fmt: skip


def _tank_dict(tank: Any) -> dict[str, Any]:
    return tank.model_dump(mode="json", exclude_none=True)


def _new_id(base: str, taken: set[str]) -> str:
    i = 1
    while f"{base}{i}" in taken:
        i += 1
    taken.add(f"{base}{i}")
    return f"{base}{i}"


def _top_story(plumbing: Any, building: Building) -> str | None:
    if building.known:
        return building.ordered()[-1]
    return plumbing.stories[-1].story if plumbing.stories else None


def _place(kind: str, dims: dict[str, Any], building: Building, story: str | None):
    """A first position for a proposed tank (SAEngine): an overhead tank at the centre of its
    roof; ground tanks in a row south of the building's footprint."""
    if kind == "overhead" and story is not None:
        roof = building.roof(story)
        if roof is not None:
            c = roof.centroid
            return round(c.x), round(c.y)
    footprint = building.footprint()
    if footprint is None:
        return 0.0, 0.0
    minx, miny, maxx, _ = footprint.bounds
    half_w = (dims.get("width") or dims.get("diameter") or 1000.0) / 2
    half_l = (dims.get("length") or dims.get("diameter") or 1000.0) / 2
    if kind == "underground":
        return minx + half_l, miny - 1500.0 - half_w
    if kind == "septic":
        return maxx - half_l, miny - 1500.0 - half_w
    if kind == "soakWell":
        return maxx - half_l, miny - 4500.0 - 2 * half_w - 1500.0
    return (minx + maxx) / 2, miny - 1500.0 - half_w


def plumbing_results(
    mep: MepModel,
    bim: Any = None,
    soil: Any = None,
    ground: float | None = None,
    rooms: Any = None,
) -> dict[str, Any]:
    """The plumbing report of parsed models (``bim``: a BuildingModel, ``soil``: a
    SoilReport, both optional). ``rooms``: the architecture's rooms
    (:class:`saengine.mep.rooms.RoomInputs`): the stories' fixtures, occupancy and population
    come from them where they are used (:func:`saengine.mep.rooms.with_rooms`; ``rooms`` in the
    result says which, story by story), and the branch runs to the wet rooms are laid out."""
    from saengine.mep.rooms import with_rooms

    mep, sources = with_rooms(mep, rooms)
    building = Building.of(bim, ground)
    problems = check(mep, bim) if bim is not None else []
    plumbing = mep.plumbing
    if plumbing is None:
        return {
            "demand": None, "storage": None, "risers": [], "stacks": [], "rainwater": None,
            "septic": None, "tanks": [], "sleeves": [], "checks": [], "summary": [],
            "notes": ["07 MEP has no plumbing section"], "problems": problems,
            "method": METHOD,
        }  # fmt: skip
    notes: list[str] = []
    checks: list[dict[str, Any]] = []
    if not building.known:
        notes.append("no 06 BIM: no story levels, slabs, catchments, sleeves or separations")

    # Demand and fixture units.
    demand = daily_demand(plumbing, building)
    valves = plumbing.supply.flushValves
    total_units = 0.0
    for s, entry in zip(demand["stories"], plumbing.stories, strict=True):
        units, _, lines = supply_units(entry.fixtures, "total", valves)
        dfu, _, dlines = drainage_units(entry.fixtures, "all", valves)
        s.update({"supplyUnits": units, "drainageUnits": dfu, "supplyLines": lines,
                  "drainageLines": dlines})  # fmt: skip
        total_units += units
    demand["supplyUnits"] = total_units
    demand["peakFlow"] = hunter_flow(total_units, valves)
    notes.extend(demand["notes"])

    # Storage and pump.
    vol = volumes(plumbing, building, demand["daily"], mep.fire)
    pumping = pump(plumbing, demand["daily"])
    inflow = plumbing.supply.inflow or pumping["peakHourly"]
    taken = {t.id for t in plumbing.tanks} | {r.id for r in plumbing.risers}
    top = _top_story(plumbing, building)
    by_kind: dict[str, list[Any]] = {}
    for t in plumbing.tanks:
        by_kind.setdefault(t.kind, []).append(t)
    wanted = ["overhead"] if down_feed(plumbing) else []
    if not wanted:
        notes.append("up-feed (07 MEP supply): no overhead tank proposed or checked")
        if by_kind.get("overhead"):
            problems.append(
                "07 MEP places an overhead tank but its supply is up-feed: set feed to down"
            )
    if plumbing.supply.source == "mains" or by_kind.get("underground"):
        wanted.append("underground")
    proposals: list[dict[str, Any]] = []
    storage_tanks = []
    for kind in wanted:
        required = vol[kind]
        tanks = by_kind.get(kind) or [None]
        share = required / len(tanks)
        if share <= 0 and tanks == [None]:
            notes.append(f"no {kind} tank proposed: the daily demand is zero")
            continue
        for tank in tanks:
            dims = dimensions(share, kind, tank)
            q = pumping["flow"] if kind == "overhead" else inflow
            record = {
                "id": tank.id if tank else None, "kind": kind, "required": share,
                "provided": dims["volume"], "drain": tank_drain(dims["volume"] * 1000.0),
                "overflow": tank_overflow(q), "inflow": q, "waterWeight": water_weight(dims),
                "notes": dims["notes"],
            }  # fmt: skip
            proposal = _proposal(tank, kind, dims, taken, building, top)
            record["id"] = proposal["id"]
            storage_tanks.append(record)
            proposals.append(proposal)
            checks.append(_check(
                f"{proposal['id']} volume", share, dims["volume"], "m³",
                dims["volume"] >= share - 1e-9, T.PAGES["5.9.1.2"],
            ))  # fmt: skip
            if kind in ("overhead", "underground"):
                checks.append(_check(
                    f"{proposal['id']} compartments", 2, dims["compartments"], "",
                    dims["compartments"] >= 2,
                    f"at least two for alternate cleaning; {T.PAGES['5.9.2.1']}",
                ))  # fmt: skip
    storage = {**vol, "tanks": storage_tanks, "pump": pumping,
               "heads": heads(plumbing, building)}  # fmt: skip

    # Risers and stacks.
    risers = []
    stacks = []
    sizes: dict[str, dict[str, Any]] = {}
    for r in plumbing.risers:
        if r.system in SUPPLY:
            out = supply_riser(r, plumbing, building)
        elif r.system == "pumpMain":
            out = pump_main(r, pumping["flow"])
        elif r.system in STACKS:
            out = soil_stack(r, plumbing, building)
            stacks.append(out)
        else:
            continue
        sizes[r.id] = out
    for r in plumbing.risers:
        if r.system == "vent":
            out = vent_stack(r, stacks, plumbing, building)
            stacks.append(out)
            sizes[r.id] = out
    rain = rainwater(plumbing, building, demand["population"])
    for leader in rain["leaders"]:
        sizes[leader["id"]] = leader
    for r in plumbing.risers:
        out = sizes.get(r.id)
        if out is None:
            continue
        risers.append(
            {
                k: out.get(k)
                for k in ("id", "system", "units", "flow", "diameter", "required", "ok", "notes")
            }
        )
        if r.system in (*SUPPLY, "pumpMain") and out.get("diameter"):
            cap = capacity(out["diameter"], r.material)
            checks.append(
                _check(
                    f"{r.id} flow",
                    out["flow"],
                    cap,
                    "l/min",
                    out["ok"],
                    f"Ø{out['diameter']:g}; {T.PAGES['5.10.1']}",
                )
            )
        elif r.system in STACKS and out.get("capacity"):
            checks.append(_check(f"{r.id} fixture units", out["units"], out["capacity"],
                                 "units", out["ok"], f"Ø{out['diameter']:g}; "
                                 f"{T.PAGES['8.6.14']}"))  # fmt: skip
        elif not out.get("ok"):
            checks.append(_check(f"{r.id}", 1, None, "", False, "; ".join(out["notes"])))
    drains = building_drains(plumbing)
    for d in drains:
        checks.append(_check(f"Building drain ({d['name']})", d["units"], None, "units",
                             d["ok"], d["note"]))  # fmt: skip
    checks.extend(rain["checks"])
    if rain["stormDrain"]["area"] > 0:
        checks.append(
            _check(
                "Building storm drain",
                rain["stormDrain"]["area"],
                None,
                "m²",
                rain["stormDrain"]["ok"],
                rain["stormDrain"]["note"],
            )
        )

    # Rainwater harvesting tank.
    harvest = rain["harvesting"]
    if harvest.get("volume"):
        for tank in by_kind.get("rainwater") or [None]:
            share = harvest["volume"] / max(len(by_kind.get("rainwater") or [None]), 1)
            dims = dimensions(share, "rainwater", tank)
            proposals.append(_proposal(tank, "rainwater", dims, taken, building, top))

    # Septic tank and soak well.
    septic = None
    if plumbing.disposal == "septic" and demand["population"] > 0:
        user = (by_kind.get("septic") or [None])[0]
        septic = septic_tank(plumbing, building, user)
        dims = {k: septic[k] for k in ("length", "width", "waterDepth", "freeboard",
                                       "compartments")}  # fmt: skip
        for i in range(septic["count"]):
            tank = (
                (by_kind.get("septic") or [])[i] if i < len(by_kind.get("septic") or []) else None
            )
            proposal = _proposal(tank, "septic", dims, taken, building, top)
            if tank is None and i > 0:
                prev = next(p for p in reversed(proposals) if p["kind"] == "septic")
                proposal["x"] = prev["x"] - septic["length"] - 1500.0
                proposal["y"] = prev["y"]
            proposals.append(proposal)
        for name, need, got, unit, why in septic.pop("checks"):
            checks.append(_check(name, need, got, unit, got >= need - 1e-9, why))
        well_tank = (by_kind.get("soakWell") or [None])[0]
        well = (
            {"ok": False, "notes": ["an Imhoff tank is required (Sec 6.9.13.2): not sized"]}
            if septic["imhoff"]
            else soak_well(septic, well_tank, soil)
        )
        septic["soakWell"] = well
        if septic["imhoff"]:
            notes.append(
                "more than 300 residential users: an Imhoff tank (Sec 6.9.13.2) is to be "
                "designed; no septic tank or soak well proposed"
            )
        elif well.get("ok"):
            wdims = {"diameter": well["diameter"], "waterDepth": well["waterDepth"]}
            wells = by_kind.get("soakWell") or []
            for i in range(well["count"] * septic["count"]):
                tank = wells[i] if i < len(wells) else None
                proposal = _proposal(tank, "soakWell", wdims, taken, building, top)
                if tank is None and i > 0:
                    # Next to the previous well, 6 m clear (Table 8.6.8 seepage pits).
                    prev = next(p for p in reversed(proposals) if p["kind"] == "soakWell")
                    proposal["x"] = prev["x"] + well["diameter"] + 6000.0
                    proposal["y"] = prev["y"]
                proposals.append(proposal)
        else:
            checks.append(_check("Soak well", 1, None, "", False, "; ".join(well["notes"])))
    if septic is not None or by_kind.get("septic") or by_kind.get("soakWell"):
        placed = [PlumbingTank.model_validate(p) for p in proposals]
        model = plumbing.model_copy(update={"tanks": placed})
        seps = separations(model, building, {p["id"]: p for p in proposals})
        if septic is not None:
            septic["separations"] = seps
        checks.extend(seps)

    # Sleeves and shafts.
    sleeves = proposed_openings(mep, sizes, building)
    checks.extend(shaft_checks(mep, sizes))
    notes.extend(sleeves["notes"])

    room_section = _rooms_section(mep, rooms, sources, building, bim)

    failed = [c["name"] for c in checks if not c["ok"]]
    summary = [
        *([room_section["line"]] if room_section["line"] else []),
        (
            f"Population {demand['population']:g}, daily demand {demand['dailyM3']:.2f} m³ "
            f"(peak hourly {demand['peakHourlyLpm']:.1f} l/min)"
        ),
        (
            f"Overhead tank {vol['overhead']:.2f} m³, underground reservoir {vol['underground']:.2f} "
            f"m³ (fire reserve {vol['fireReserve']:g} m³)"
        ),
        f"Pump {pumping['flow']:.1f} l/min",
        f"{len(risers)} risers and stacks, {len(sleeves['openings'])} sleeves proposed",
        f"{len(failed)} of {len(checks)} checks fail"
        + (f": {', '.join(failed)}" if failed else ""),
    ]
    return {
        "demand": demand,
        "storage": storage,
        "risers": risers,
        "stacks": stacks,
        "drains": drains,
        "rainwater": rain,
        "septic": septic,
        "tanks": proposals,
        "sleeves": sleeves["openings"],
        "checks": checks,
        "summary": summary,
        "notes": notes,
        "problems": problems,
        "method": METHOD,
        "rooms": room_section,
    }


def _rooms_section(
    mep: MepModel, rooms: Any, sources: list[dict[str, Any]], building: Building, bim: Any
) -> dict[str, Any]:
    """Where each story's fixtures come from, the wet rooms and the branch runs to them."""
    from saengine.mep.rooms import kind_fixtures
    from saengine.plumbing.branches import branch_runs

    runs, run_notes = branch_runs(mep.plumbing, rooms, building, bim, list(mep.shafts))
    from_rooms = [s["story"] for s in sources if s["source"] == "rooms"]
    typed = [s["story"] for s in sources if s["source"] == "typed"]
    line = ""
    if rooms is not None and rooms.stories:
        parts = []
        if from_rooms:
            parts.append(f"from the architecture's wet rooms on {', '.join(from_rooms)}")
        if typed:
            parts.append(f"typed in 07 MEP on {', '.join(typed)}")
        line = "Fixtures " + "; ".join(parts) if parts else ""
    return {
        "stories": sources,
        "wetRooms": [r.as_dict() for r in (rooms.rooms if rooms is not None else []) if r.kind],
        "branches": runs,
        "kinds": kind_fixtures(mep.plumbing),
        "notes": [*(rooms.notes if rooms is not None else []), *run_notes],
        "line": line,
    }


def _proposal(
    tank: Any, kind: str, dims: dict[str, Any], taken: set[str], building: Building, top: str | None
) -> dict[str, Any]:
    """A tank in 07 MEP's format with the proposed dimensions (``sized`` when any is new)."""
    keys = (
        ("diameter", "waterDepth")
        if kind == "soakWell"
        else ("length", "width", "waterDepth", "freeboard", "compartments")
    )
    if tank is not None:
        out = _tank_dict(tank)
        new = {k: dims[k] for k in keys if dims.get(k) is not None and out.get(k) is None}
        out.update(new)
        if new:
            out["sized"] = True
        return out
    base = {"overhead": "OHT", "underground": "UGR", "septic": "ST", "rainwater": "RWT",
            "soakWell": "SW"}[kind]  # fmt: skip
    story = top if kind == "overhead" else None
    x, y = _place(kind, dims, building, story)
    out = {
        "id": _new_id(base, taken),
        "kind": kind,
        "x": x,
        "y": y,
        **{k: dims[k] for k in keys if k in dims},
        "construction": "rc",
        "sized": True,
    }
    if story is not None:
        out["story"] = story
    return out


# ───────────────────────────────────────── files ─────────────────────────────────────────


def _read(root: Path, relative: str) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _load(project_root: str | Path, mep_text: str | None = None):
    from saengine.library.bim import BuildingModel
    from saengine.library.soil import SoilReport, is_placeholder

    root = Path(project_root)
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
    soil = None
    soil_text = _read(root, "01 Soil Report/soil-report.json")
    if soil_text:
        try:
            data = json.loads(soil_text)
            soil = None if is_placeholder(data) else SoilReport.model_validate(data)
        except ValueError as error:
            problems.append(f"01 Soil Report is not valid: {error}")
    ground = None
    settings_text = _read(root, "02 Project Settings/project-settings.json")
    if settings_text:
        try:
            ground = json.loads(settings_text).get("foundation", {}).get("groundLevel")
        except ValueError:
            ground = None
    return mep, bim, soil, ground, problems


def plumbing_report(project_root: str | Path, mep_text: str | None = None) -> dict[str, Any]:
    """The plumbing report of a project (``mep_text``: unsaved ``07 MEP/mep.json``), with the
    rooms of ``05 Floor Plan/architecture.json`` (:func:`plumbing_results`)."""
    from saengine.mep.rooms import read_room_inputs

    try:
        mep, bim, soil, ground, problems = _load(project_root, mep_text)
    except ValueError as error:
        return {"problems": [str(error)]}
    rooms, problem = read_room_inputs(project_root, mep.plumbing)
    if problem:
        problems.append(problem)
    try:
        result = plumbing_results(
            mep, bim, soil, ground if isinstance(ground, int | float) else None, rooms=rooms
        )
    except Exception as error:  # noqa: BLE001 - a partly entered model must not fail the RPC
        return {"problems": [*problems, f"the plumbing sizing failed: {error!r}"]}
    result["problems"] = [*problems, *result["problems"]]
    return result


def plumbing_size_tanks(project_root: str | Path, mep_text: str | None = None) -> list[dict]:
    """The tanks SAEngine proposes (07 MEP ``plumbing.tanks`` format, ``sized``: true)."""
    report = plumbing_report(project_root, mep_text)
    return report.get("tanks", [])


def plumbing_sleeves(project_root: str | Path, mep_text: str | None = None) -> list[dict]:
    """The sleeves the risers need through the slabs (07 MEP ``openings`` format)."""
    report = plumbing_report(project_root, mep_text)
    return report.get("sleeves", [])


def overhead_equipment(
    tank: dict[str, Any], walls: float = 150.0, density: float = 24.0
) -> dict[str, Any] | None:
    """An overhead plumbing tank as 07 MEP equipment (kind "tank"): its outside footprint,
    the water as contents and a concrete shell of ``walls`` mm (walls, base and roof; SAEngine
    estimate until the tank design gives them) of ``density`` kN/m³ as the empty weight.
    None when the tank has no story or no length, width or water depth yet (07 MEP check()
    reports those): the caller skips it."""
    if tank.get("story") is None or not all(tank.get(k) for k in ("length", "width", "waterDepth")):
        return None
    t = tank.get("walls") or walls
    base = tank.get("base") or t
    roof = tank.get("roof") or t
    length, width = tank["length"], tank["width"]
    n = tank.get("compartments") or 2  # not given: two (Sec 5.9.2.1), as the sizing
    height = tank["waterDepth"] + (tank.get("freeboard") or 300.0)
    outer_l, outer_w = length + 2 * t, width + 2 * t  # the partitions inside the length
    shell = (
        (
            outer_l * outer_w * (base + roof)
            + (2 * (outer_l + width) * t + (n - 1) * width * t) * height
        )
        / 1e9
        * density
    )
    water = max(length - (n - 1) * t, 0.0) * width * tank["waterDepth"] / 1e9 * 9.81
    return {
        "id": f"EQ-{tank['id']}", "name": "Overhead water tank", "kind": "tank",
        "story": tank["story"], "x": tank["x"], "y": tank["y"], "length": outer_l,
        "width": outer_w, "height": height + base + roof,
        "operatingWeight": round(shell + water, 1), "emptyWeight": round(shell, 1),
    }  # fmt: skip
