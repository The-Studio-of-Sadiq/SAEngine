"""The electrical coordination report of a project (BNBC 2020 Part 8 Chapter 1).

:func:`electrical_report` reads ``07 MEP/mep.json`` (its ``electrical``, and ``hvac`` for the
cooling plant's load), ``06 BIM/bim.json`` (stories, slabs, beams, columns, footings),
``04 Objects`` (beam depths, slab thicknesses), ``09 Substructure`` (the foundations under the
down-conductor columns) and ``02 Project Settings`` (ground level, building use) when present,
and returns the demand, the supply (transformers, generator, UPS), the room checks, the risers
and trays, the lightning protection, the proposed equipment and openings, and the checks.
:func:`electrical_propose_equipment` and :func:`electrical_openings` return just the proposals,
in the format of 07 MEP (``electrical.equipment`` and ``openings``).
:func:`electrical_equipment` gives the electrical equipment as 07 MEP ``equipment`` for the
analysis loads.

:func:`electrical_results` does the same from the parsed models, without files.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from saengine.electrical import tables as T
from saengine.electrical.demand import demand as compute_demand
from saengine.electrical.demand import story_order
from saengine.electrical.lightning import lightning_protection
from saengine.electrical.risers import (
    Frame,
    riser_openings,
    size_riser,
    tray_checks,
    tray_openings,
)
from saengine.electrical.rooms import (
    ground_story,
    room_checks,
    shaft_checks,
    storeys_and_height,
)
from saengine.electrical.supply import (
    capacitor_kvar,
    empty_of_oil,
    essential_load,
    fuel_tank,
    generator,
    generator_area,
    lift_standby_required,
    substation_required,
    transformers,
    typical_capacitor,
    typical_generator,
    typical_ht_panel,
    typical_lt_panel,
    typical_transformer,
    ups,
)
from saengine.library.mep import MEP_FILE, Lightning, MepModel, parse
from saengine.plumbing.building import Building

METHOD = [
    (
        "Demand (BNBC 2020 Part 8 Sec 1.3.2, Table 8.1.17): floor area x the minimum load "
        "density of the story's use (A/C or non-A/C), or the lighting + power entered where more, "
        "+ other loads, lifts, pumps, fans and the hvac plant (capacity / COP); maximum demand = "
        "load factor (at least 0.8, Sec 1.3.18.1) x connected load; kVA at the power factor."
    ),
    (
        "Supply (Sec 1.3.18-1.3.20, Tables 8.1.23, 8.1.24): an 11 kV substation from 50 kW; "
        "transformers in standard sizes for the maximum demand; the standby generator for the "
        "essential load at 0.8 power factor, its fuel for the hours entered (8, SAEngine "
        "practice); lifts on standby above ten storeys or 32 m and in hospitals (Sec 4.2.1.3)."
    ),
    (
        "Rooms (Sec 1.3.18.2-1.3.18.7, 1.3.19.2-1.3.19.3): substation not in a basement, "
        "preferably on the ground floor; height 3.0-3.6 m; clearances 0.75-1.25 m to the walls, "
        "1.5 m between transformers; soak pit above 2000 l of oil; generator on the ground floor "
        "or first basement, 1.0 m to the walls, 1.25 m between sets."
    ),
    (
        "Shafts and risers (Sec 1.3.13): one 200 x 400 mm electrical shaft per 1500 m² above six "
        "storeys or 20 m; busbar above nine storeys; riser cables 37 mm apart; openings through "
        "the slabs and beams: size + 100 mm (risers) or 50 mm (trays) each side (SAEngine)."
    ),
    (
        "Lightning (Sec 1.3.33, Tables 8.1.27-8.1.29): risk index against 40, always above 53 m; "
        "air spikes one per 80 m², roof conductors within 9 m, down conductors by the base area "
        "or one per 30 m of perimeter, on continuous perimeter columns; earth 10 ohm (2 ohm high "
        "rise); clearance Eq 8.1.1."
    ),
    (
        "Typical dimensions and weights of the proposed equipment are catalogue values to be "
        "replaced with the selected unit's data."
    ),
]

#: Project Settings building use -> Table 8.1.17 row (for the lightning risk without stories).
SETTINGS_USE = {
    "residential": "residenceMulti", "office": "office", "educational": "school",
    "healthcare": "hospital", "assembly": "departmentStore", "retail": "departmentStore",
    "industrial": "industrial", "storage": "warehouse", "parking": "parking", "mixed": "office",
}  # fmt: skip
EQUIPMENT_KIND = {"transformer": "transformer", "generator": "generator"}
BASE_IDS = {
    "transformer": "TX", "switchgear": "HT", "lvPanel": "LT", "generator": "GEN",
    "fuelTank": "FT", "ups": "UPS", "battery": "BAT", "capacitorBank": "CB",
}  # fmt: skip


def _check(name: str, demand: float, cap: float | None, unit: str, ok: bool, note: str):
    util = demand / cap if cap else (0.0 if demand == 0 else math.inf)
    return {"name": name, "demand": demand, "capacity": cap, "unit": unit,
            "utilisation": util, "ok": bool(ok), "note": note}  # fmt: skip


def _new_id(base: str, taken: set[str]) -> str:
    i = 1
    while f"{base}{i}" in taken:
        i += 1
    taken.add(f"{base}{i}")
    return f"{base}{i}"


def references(mep: MepModel, building: Building) -> list[str]:
    """Problems with the stories and shafts the electrical section refers to."""
    electrical = mep.electrical
    if electrical is None or not building.known:
        return []
    stories = building.stories
    shafts = {s.id for s in mep.shafts}
    problems = []
    for entry in electrical.stories:
        if entry.story not in stories:
            problems.append(f"electrical: no story '{entry.story}'")
    for item in [*electrical.equipment, *electrical.trays, *electrical.rooms]:
        if item.story not in stories:
            problems.append(f"{item.id}: no story '{item.story}'")
    for riser in electrical.risers:
        missing = [
            s for s in (riser.fromStory, riser.toStory, *(riser.serves or [])) if s not in stories
        ]
        if missing:
            problems.append(f"{riser.id}: no story '{missing[0]}'")
        elif stories[riser.toStory] <= stories[riser.fromStory]:
            problems.append(f"{riser.id}: its top story must be above the story it starts at")
        if riser.shaft is not None and riser.shaft not in shafts:
            problems.append(f"{riser.id}: no shaft '{riser.shaft}'")
    return problems


# ─────────────────────────────────────── proposals ───────────────────────────────────────


def _item(kind: str, iid: str, name: str, story: str, x: float, y: float, data: dict[str, Any],
          rating: float | None = None, **extra: Any) -> dict[str, Any]:  # fmt: skip
    out = {"id": iid, "kind": kind, "name": f"{name} ({T.TYPICAL.split(',')[0]})",
           "story": story, "x": round(x), "y": round(y), "length": data["length"],
           "width": data["width"], "height": data.get("height"),
           "operatingWeight": data["operatingWeight"],
           "emptyWeight": data.get("emptyWeight"), "sized": True}  # fmt: skip
    if rating is not None:
        out["rating"] = rating
    out.update(extra)
    return {k: v for k, v in out.items() if v is not None}


def propose_equipment(
    mep: MepModel,
    building: Building,
    dem: dict[str, Any],
    supply_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """The equipment SAEngine proposes where 07 MEP has none of the kind: HT switchgear,
    transformers, the LT panel and a capacitor bank for a substation; the generator and its fuel
    tank; the UPS and its battery. Typical sizes and weights, on the ground floor (transformers
    in a corner, the generator in the opposite one, Sec 1.3.18.7(a), 1.3.19.3)."""
    electrical = mep.electrical
    assert electrical is not None
    have = {e.kind for e in electrical.equipment}
    taken = {e.id for e in electrical.equipment} | {e.id for e in mep.equipment}
    story = ground_story(building) or (electrical.stories[0].story if electrical.stories else "")
    area = building.roof(story) if building.known else None
    if area is None or area.is_empty:
        area = building.footprint()
    minx, miny, maxx, _ = area.bounds if area is not None else (0.0, 0.0, 0.0, 0.0)
    out: list[dict[str, Any]] = []
    tx = supply_result["transformers"]
    cl = T.TRANSFORMER_CLEARANCE["enclosed"]
    if supply_result["substation"] and tx["count"] and "transformer" not in have:
        kind = electrical.supply.transformerType
        data = typical_transformer(tx["rating"], kind)
        x = minx + cl + data["length"] / 2
        y = miny + cl + data["width"] / 2
        for _ in range(tx["count"]):
            out.append(_item("transformer", _new_id("TX", taken),
                             f"Transformer {tx['rating']:g} kVA {kind}", story, x, y, data,
                             tx["rating"], oil=data["oil"] or None))  # fmt: skip
            x += data["length"] + T.TRANSFORMER_SPACING["11kV"]
        y_row = y + data["width"] / 2 + cl
        if electrical.supply.voltage != "0.4kV" and "switchgear" not in have:
            ht = typical_ht_panel()
            out.append(_item("switchgear", _new_id("HT", taken), "11 kV switchgear", story,
                             minx + cl + ht["length"] / 2, y_row + ht["width"] / 2, ht))  # fmt: skip
        if "lvPanel" not in have:
            amps = tx["total"] * 1000.0 / (math.sqrt(3) * T.LT_VOLTAGE)
            lt = typical_lt_panel(amps)
            out.append(_item("lvPanel", _new_id("LT", taken), f"LT panel {amps:.0f} A",
                             story, x + lt["length"] / 2, y_row + lt["width"] / 2, lt,
                             round(amps)))  # fmt: skip
        kvar = capacitor_kvar(dem["maximumDemand"], dem["powerFactor"])
        if kvar > 0 and "capacitorBank" not in have:
            cb = typical_capacitor(kvar)
            out.append(_item("capacitorBank", _new_id("CB", taken),
                             f"Capacitor bank {kvar:.0f} kvar", story,
                             x + cb["length"] / 2, y_row + 2500 + cb["width"] / 2, cb))  # fmt: skip
    gen = supply_result["generator"]
    if gen and gen.get("kva"):
        placed = next((e for e in electrical.equipment if e.kind == "generator"), None)
        gen_story = story
        if placed is None:
            data = typical_generator(gen["kva"])
            gx = maxx - T.GENERATOR_CLEARANCE - data["length"] / 2
            gy = miny + T.GENERATOR_CLEARANCE + data["width"] / 2
            out.append(_item("generator", _new_id("GEN", taken), f"Generator {gen['kva']:g} kVA",
                             story, gx, gy, data, gen["kva"], vibrating=True))  # fmt: skip
            length = data["length"]
        else:
            # the tank of the engineer's set stands beside it, on its story
            gen_story, gx, gy = placed.story, placed.x, placed.y
            length = placed.length or typical_generator(placed.rating or gen["kva"])["length"]
        tank = gen["tank"]
        if "fuelTank" not in have and tank:
            tdata = {"length": tank["length"], "width": tank["width"], "height": tank["height"],
                     "operatingWeight": round(tank["operatingWeight"], 1),
                     "emptyWeight": round(tank["emptyWeight"], 1)}  # fmt: skip
            out.append(_item("fuelTank", _new_id("FT", taken),
                             f"Fuel tank {gen['fuel']:.0f} l", gen_story,
                             gx - length / 2 - T.GENERATOR_SPACING - tank["length"] / 2,
                             gy, tdata))  # fmt: skip
    u = supply_result["ups"]
    if u and "ups" not in have:
        ux = (minx + maxx) / 2
        uy = miny + 2000
        out.append(_item("ups", _new_id("UPS", taken), f"UPS {u['kva']:g} kVA", story, ux, uy,
                         {"length": 800.0, "width": 900.0, "height": 2000.0,
                          "operatingWeight": round(u["upsWeight"], 1)}, u["kva"]))  # fmt: skip
        if "battery" not in have:
            racks = max(1, math.ceil(u["batteryWeight"] / 8.0))  # about 8 kN a rack (typical)
            out.append(_item("battery", _new_id("BAT", taken), f"Battery {u['energy']:.0f} kWh",
                             story, ux + 1500 + racks * 400, uy,
                             {"length": racks * 800.0, "width": 600.0, "height": 1800.0,
                              "operatingWeight": round(u["batteryWeight"], 1)}))  # fmt: skip
    return out


#: Below this share of its rating a transformer or generator is reported as oversized.
OVERSIZE = 0.3


def _substation_line(
    sub: bool, supply: Any, tx: dict[str, Any], entered: list[Any], installed: float, dem: dict
) -> str:
    """The summary's supply line: what the engineer chose (an 11 kV supply, the transformers
    entered) against what the demand needs, never "no substation" beside an entered one."""
    kva = dem["kva"]
    if entered:
        rating = " + ".join(f"{float(e.rating or 0):g}" for e in entered)
        line = f"Transformers entered: {rating} kVA for {kva:.0f} kVA of demand"
        if installed and kva / installed < OVERSIZE:
            line += f" (loaded {kva / installed:.0%}: oversized for this demand)"
        if not sub:
            line += (
                f"; below {T.SUBSTATION_KW:g} kW a 0.4 kV supply would do ({T.PAGES['1.3.20.1']})"
            )
        return line
    if sub:
        return f"Substation: {tx['count']} x {tx['rating']:g} kVA transformer(s)"
    if supply.voltage in ("11kV", "33kV"):
        return (
            f"{supply.voltage} supply chosen; the load is below {T.SUBSTATION_KW:g} kW, where a "
            f"0.4 kV supply would do ({T.PAGES['1.3.20.1']}): the transformer is sized for "
            f"{kva:.0f} kVA"
        )
    return f"No substation needed (below {T.SUBSTATION_KW:g} kW, {T.PAGES['1.3.20.1']})"


def _generator_line(gen: dict[str, Any] | None, ess: dict[str, Any], entered: list[Any]) -> str:
    """The summary's generator line: one rating (the entered sets', else the proposal), the
    rating the essential load needs, and the oversize when there is one."""
    if not gen or not gen.get("kva"):
        return "No standby generator"
    need = float(gen.get("required") or 0.0)
    what = "entered" if entered else "proposed"
    line = (
        f"Generator {gen['kva']:g} kVA ({what}) for {need:.0f} kVA needed by {ess['kw']:.1f} kW "
        f"essential, fuel {gen['fuel']:.0f} l ({gen['fuelHours']:g} h)"
    )
    if entered and gen["kva"] and need / gen["kva"] < OVERSIZE:
        line += f"; loaded {need / gen['kva']:.0%}: oversized for the essential load"
    return line


def _installed_generator(
    proposed: dict[str, Any], entered: list[Any], hours: float | None = None
) -> dict[str, Any]:
    """The generator result for the sets entered in 07 MEP: their total rating, the fuel and
    tank for that rating, and Table 8.1.24's room area for each set (SAEngine's own proposal
    keeps only the required kVA, from the essential load)."""
    kva = float(sum(e.rating for e in entered))
    kw = kva * T.GENERATOR_PF
    hours = proposed.get("fuelHours") or hours or T.FUEL_HOURS
    fuel = kw * hours * T.FUEL_RATE
    need = float(proposed.get("required") or 0.0)
    areas = [generator_area(float(e.rating) * T.GENERATOR_PF) for e in entered]
    room = None if any(a is None for a in areas) else sum(a[0] for a in areas if a)
    rows = ", ".join(a[1] for a in areas if a)
    ids = ", ".join(f"{e.id} {float(e.rating):g} kVA" for e in entered)
    return {
        **proposed,
        "kva": kva,
        "kw": kw,
        "required": need,
        "utilisation": need / kva if kva else None,
        "fuelHours": hours,
        "fuelRate": T.FUEL_RATE,
        "fuel": fuel,
        "tank": fuel_tank(fuel) if fuel > 0 else None,
        "entered": [e.id for e in entered],
        "proposedKva": proposed.get("kva"),
        "roomArea": room,
        "roomRow": rows or None,
        "note": f"entered in 07 MEP: {ids}"
        + (f"; {proposed['note']}" if proposed.get("note") else ""),
    }


def as_dicts(electrical: Any) -> list[dict[str, Any]]:
    return [e.model_dump(mode="json", exclude_none=True) for e in electrical.equipment]


def with_typical(item: dict[str, Any], transformer_type: str = "oil") -> dict[str, Any]:
    """An electrical equipment item with typical dimensions and weight where it gives none."""
    rating = item.get("rating")
    data: dict[str, Any] | None = None
    if item["kind"] == "transformer" and rating:
        data = typical_transformer(rating, transformer_type)
    elif item["kind"] == "generator" and rating:
        data = typical_generator(rating)
    elif item["kind"] == "lvPanel" and rating:
        data = typical_lt_panel(rating)
    elif item["kind"] == "switchgear":
        data = typical_ht_panel()
    out = dict(item)
    if data is not None:
        for key in ("length", "width", "height", "operatingWeight", "oil"):
            if out.get(key) is None and data.get(key):
                out[key] = data[key]
    if (
        out.get("emptyWeight") is None
        and item["kind"] == "transformer"
        and out.get("operatingWeight")
        and out.get("oil")
    ):
        empty = empty_of_oil(float(out["operatingWeight"]), float(out["oil"]))
        if empty is not None:
            out["emptyWeight"] = empty
    return out


# ─────────────────────────────────────── the report ───────────────────────────────────────


def electrical_results(
    mep: MepModel,
    bim: Any = None,
    objects: Any = None,
    ground: float | None = None,
    substructure: Any = None,
    building_use: str | None = None,
    hvac: list[dict[str, Any]] | None = None,
    extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The electrical report of parsed models (all but ``mep`` optional). ``hvac`` and
    ``extra``: loads the integrator supplies (see :func:`saengine.electrical.demand.demand`)."""
    building = Building.of(bim, ground)
    problems = references(mep, building)
    electrical = mep.electrical
    if electrical is None:
        return {
            "demand": None, "supply": None, "rooms": [], "risers": [], "trays": [],
            "lightning": None, "equipment": [], "openings": [], "checks": [], "summary": [],
            "notes": ["07 MEP has no electrical section"], "problems": problems,
            "method": METHOD,
        }  # fmt: skip
    notes: list[str] = []
    checks: list[dict[str, Any]] = []
    if not building.known:
        notes.append("no 06 BIM: no story levels, areas, openings or down conductors")
    order = story_order(electrical, building)
    storeys, height = storeys_and_height(building, order)
    frame = Frame.of(bim, objects)

    # Demand.
    dem = compute_demand(
        electrical, building, mep, hvac=hvac, extra=extra,
        default_use=SETTINGS_USE.get(building_use or ""),
    )  # fmt: skip
    notes.extend(dem["notes"])
    for s in dem["stories"]:
        notes.extend(f"{s['story']}: {n}" for n in s["notes"])
    uses = [s["use"] for s in dem["stories"]]
    if not uses and building_use in SETTINGS_USE:
        uses = [SETTINGS_USE[building_use]]
    hospital = "hospital" in uses or building_use == "healthcare"

    # Supply.
    supply = electrical.supply
    sub = substation_required(dem["connected"])
    tx = transformers(dem["kva"], supply.transformers)
    entered_tx = [e for e in electrical.equipment if e.kind == "transformer"]
    installed = sum(float(e.rating or 0.0) for e in entered_tx) if entered_tx else tx["total"]
    if sub:
        checks.append(_check("Transformer capacity", dem["kva"], installed, "kVA",
                             dem["kva"] <= installed + 1e-9,
                             ("entered transformers" if entered_tx else
                              f"proposed {tx['count']} x {tx['rating']:g} kVA") +
                             f"; {T.PAGES['1.3.18.1']}"))  # fmt: skip
    if sub and supply.voltage == "0.4kV":
        # A rule, not a ratio: pass or fail, no utilisation (N-E9).
        checks.append({
            "name": "Supply voltage", "demand": None, "capacity": None, "unit": "",
            "utilisation": None, "ok": False,
            "note": f"{dem['connected']:.0f} kW connected, {T.SUBSTATION_KW:g} kW or more: an "
                    f"11 kV supply with a substation is required ({T.PAGES['1.3.20.1']}); set "
                    "the supply voltage in Electrical > Supply",
        })  # fmt: skip
    ess = essential_load(electrical, dem)
    lifts = [m for m in electrical.motors if m.kind == "lift"]
    standby = bool(lifts) and lift_standby_required(storeys, height, hospital)
    entered_gen = [e for e in electrical.equipment if e.kind == "generator" and e.rating]
    want_generator = supply.generator or standby or bool(entered_gen)
    gen = generator(ess["kw"], supply.fuelHours) if want_generator else None
    if gen is not None and entered_gen:
        gen = _installed_generator(gen, entered_gen)
    if gen is not None and gen.get("kw"):
        gen["essential"] = ess
        if not entered_gen:
            row = generator_area(gen["kw"])
            gen["roomArea"] = row[0] if row else None
            gen["roomRow"] = row[1] if row else None
        cap = gen["kva"] or 0.0
        checks.append(_check("Generator capacity", gen["required"], cap, "kVA",
                             gen["required"] <= cap + 1e-9,
                             "; ".join(ess["parts"]) + f" at pf {T.GENERATOR_PF:g} "
                             f"({T.PAGES['1.3.19.2']})"))  # fmt: skip
    if standby:
        has = supply.generator or any(e.kind == "generator" for e in electrical.equipment)
        checks.append(_check("Standby power for the lifts", 1, 1 if has else 0, "", has,
                             "more than ten storeys, 32 m, or a hospital: one or more lifts on "
                             f"standby power from a generator ({T.PAGES['4.2.1']})"))  # fmt: skip
    if (storeys > T.LIFT_STOREYS or height > T.LIFT_HEIGHT) and not lifts:
        notes.append(
            f"lifts are required above six storeys or 20 m ({T.PAGES['4.2.1']}): enter their "
            "motors in 07 MEP electrical for the demand and the generator"
        )
    up = ups(supply.upsLoad, supply.upsAutonomy) if supply.ups else None
    if supply.ups and up is None:
        notes.append("a UPS is asked for: enter its load (electrical.supply.upsLoad)")
    supply_result = {"substation": sub, "voltage": supply.voltage or ("11kV" if sub else "0.4kV"),
                     "transformers": tx, "generator": gen, "ups": up,
                     "standbyLifts": standby}  # fmt: skip

    # Equipment: the entered with typical data, the proposed for what is missing.
    proposals = propose_equipment(mep, building, dem, supply_result)
    entered = [with_typical(e, supply.transformerType) for e in as_dicts(electrical)]
    for e in entered:
        if e.get("operatingWeight") is None:
            notes.append(f"{e['id']}: no operating weight; enter it for the analysis loads")
    placed = entered + [p for p in proposals if p["kind"] not in {e["kind"] for e in entered}]
    if proposals:
        notes.append(
            f"proposed equipment: {T.TYPICAL} ({len(proposals)} items; Add Equipment in 7 MEP)"
        )

    # Rooms and shafts.
    rooms = room_checks(electrical, placed, building, frame.slab_thickness, set(uses))
    checks.extend(rooms["checks"])
    notes.extend(rooms["notes"])
    max_area = max((s["area"] for s in dem["stories"]), default=0.0)
    if not max_area and building.known:
        max_area = max((building.floor_area(s) for s in order), default=0.0)
    checks.extend(shaft_checks(mep, building, storeys, height, max_area))

    # Risers and trays.
    risers = [size_riser(r, dem, building, order, storeys) for r in electrical.risers]
    for r in risers:
        if r["rating"] and r["current"]:
            checks.append(_check(f"{r['id']} rating", r["current"], r["rating"], "A", r["ok"],
                                 "; ".join(r["notes"])))  # fmt: skip
        elif not r["ok"]:
            checks.append(_check(r["id"], 1, None, "", False, "; ".join(r["notes"])))
    if storeys > T.BUSBAR_STOREYS and any(r["kind"] != "busbar" for r in risers):
        notes.append(f"more than {T.BUSBAR_STOREYS} storeys: busbar trunking risers preferred "
                     f"({T.cite('1.3.13.2', '(d)')})")  # fmt: skip
    rise = riser_openings(mep, risers, building, order)
    trays = tray_openings(mep, building, frame)
    checks.extend(tray_checks(electrical))
    notes.extend(rise["notes"])
    notes.extend(trays["notes"])
    openings = rise["openings"] + trays["openings"]

    # Lightning.
    lightning_model = electrical.lightning or Lightning()
    lightning = lightning_protection(
        lightning_model, building, bim, uses, storeys, height, substructure
    )
    checks.extend(lightning["checks"])
    notes.extend(lightning["notes"])

    failed = [c["name"] for c in checks if not c["ok"]]
    summary = [
        (
            f"Connected load {dem['connected']:.1f} kW, maximum demand {dem['maximumDemand']:.1f} kW "
            f"= {dem['kva']:.1f} kVA ({dem['current']:.0f} A at 400 V)"
        ),
        _substation_line(sub, supply, tx, entered_tx, installed, dem),
        _generator_line(gen, ess, entered_gen),
        f"{len(risers)} risers, {len(electrical.trays)} trays, {len(openings)} openings proposed",
        (
            f"Lightning: {len(lightning['downConductors'])} down conductors, "
            f"{len(lightning['airTerminals'])} air terminals ({lightning['risk']['decision']})"
        ),
        (f"{len(failed)} checks fail: {', '.join(failed)}" if failed else "All checks pass"),
    ]
    return {
        "demand": dem,
        "supply": supply_result,
        "rooms": rooms["checks"],
        "risers": risers,
        "trays": trays["crossings"],
        "lightning": lightning,
        "equipment": proposals,
        "openings": openings,
        "checks": checks,
        "summary": summary,
        "notes": notes,
        "problems": problems,
        "method": METHOD,
        "storeys": storeys,
        "height": height,
    }


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
    bim = objects = substructure = None
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
    sub_text = _read(root, "09 Substructure/substructure.json")
    if sub_text:
        try:
            substructure = json.loads(sub_text)
        except ValueError:
            substructure = None
    ground = use = None
    settings_text = _read(root, "02 Project Settings/project-settings.json")
    if settings_text:
        try:
            settings = json.loads(settings_text)
            ground = (settings.get("foundation") or {}).get("groundLevel")
            use = (settings.get("occupancy") or {}).get("use")
        except ValueError:
            pass
    return {"mep": mep, "bim": bim, "objects": objects, "substructure": substructure,
            "ground": ground if isinstance(ground, int | float) else None, "use": use,
            "problems": problems}  # fmt: skip


def service_loads(
    project_root: str | Path, mep_text: str | None, loaded: dict[str, Any]
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]], list[str]]:
    """What the other services draw that 07 MEP electrical does not list, so that the demand
    includes them (BNBC 2020 Part 8 Sec 1.3.2: lifts, pumps and the air conditioning):

    - the HVAC plant: entered plant is read by the demand itself (None here); without any, the
      plant the HVAC Results propose (:func:`saengine.hvac.plant.hvac_propose_plant`), marked
      as proposed;
    - the water pump, when no motor of kind pump is entered: the plumbing's estimate
      (:func:`saengine.plumbing.hydraulics.estimated_pump_motor`).

    Returns (hvac loads or None, extra loads, notes); never raises."""
    from saengine.electrical.demand import hvac_loads
    from saengine.plumbing.building import Building

    mep, notes = loaded["mep"], []
    hvac: list[dict[str, Any]] | None = None
    extra: list[dict[str, Any]] = []
    if mep.hvac is not None and not mep.hvac.plant and mep.electrical is not None:
        try:
            from saengine.hvac.plant import hvac_propose_plant

            proposed = hvac_propose_plant(project_root, mep_text=mep_text).get("plant") or []
        except Exception:  # noqa: BLE001 - the HVAC may be partly entered
            proposed = []
        if proposed:
            hvac = [
                {**h, "note": f"{h['note']}; proposed by the HVAC Results, not in 07 MEP yet"}
                for h in hvac_loads({"hvac": {"plant": proposed}})
            ]
            notes.append(
                f"the air conditioning draws {sum(h['kw'] for h in hvac):.0f} kW: the plant the "
                "HVAC Results propose (none is entered yet)"
            )
    electrical, plumbing = mep.electrical, mep.plumbing
    if (
        electrical is not None
        and plumbing is not None
        and not any(m.kind == "pump" for m in electrical.motors)
    ):
        try:
            from saengine.plumbing.hydraulics import estimated_pump_motor

            found = estimated_pump_motor(plumbing, Building.of(loaded["bim"], loaded["ground"]))
        except Exception:  # noqa: BLE001 - the plumbing may be partly entered
            found = None
        if found is not None:
            kw, why = found
            extra.append({"id": "water pump", "kw": kw, "note": why})
            notes.append(f"the water pump draws {kw:g} kW (no pump motor is entered): {why}")
    return hvac, extra, notes


def electrical_report(
    project_root: str | Path,
    mep_text: str | None = None,
    hvac: list[dict[str, Any]] | None = None,
    extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The electrical report of a project (``mep_text``: unsaved ``07 MEP/mep.json``). Never
    raises: ``{problems}`` when 07 MEP cannot be read. JSON-safe (no infinities)."""
    from saengine.plumbing.project import finite

    try:
        loaded = _load(project_root, mep_text)
    except ValueError as error:
        return {"problems": [str(error)]}
    fed: list[str] = []
    if hvac is None or extra is None:
        own_hvac, own_extra, fed = service_loads(project_root, mep_text, loaded)
        hvac = own_hvac if hvac is None else hvac
        extra = own_extra if extra is None else extra
    try:
        result = electrical_results(
            loaded["mep"], loaded["bim"], loaded["objects"], loaded["ground"],
            loaded["substructure"], loaded["use"], hvac=hvac, extra=extra,
        )  # fmt: skip
    except Exception as error:  # noqa: BLE001 - a partly entered model must not fail the RPC
        return {"problems": [*loaded["problems"], f"the electrical sizing failed: {error!r}"]}
    result["problems"] = [*loaded["problems"], *result["problems"]]
    result["notes"] = [*fed, *result.get("notes", [])]
    if result.get("openings"):
        from saengine.plumbing.project import missing_sleeves

        result["openingsProposed"] = len(result["openings"])
        result["openings"] = missing_sleeves(loaded["mep"], result["openings"])
    return finite(clause_only(result))


#: A page reference after a clause: " (p763)", ", p796", " (p338-339)".
_PAGE = re.compile(r"\s*\(pp?\.? ?\d+(?:[-–]\d+)?\)|,\s*pp?\.? ?\d+(?:[-–]\d+)?(?=[),;]|$)")


def clause_only(value: Any) -> Any:
    """``value`` with the page numbers taken out of its texts: citations by part, section and
    clause only (the pages differ between printings of BNBC 2020; N-E9)."""
    if isinstance(value, str):
        return _PAGE.sub("", value)
    if isinstance(value, list):
        return [clause_only(v) for v in value]
    if isinstance(value, dict):
        return {k: clause_only(v) for k, v in value.items()}
    return value


def electrical_propose_equipment(
    project_root: str | Path, mep_text: str | None = None
) -> list[dict[str, Any]]:
    """The equipment SAEngine proposes (07 MEP ``electrical.equipment`` format, ``sized``)."""
    return electrical_report(project_root, mep_text).get("equipment", [])


def electrical_openings(project_root: str | Path, mep_text: str | None = None) -> list[dict]:
    """The openings the risers and trays still need (07 MEP ``openings`` format)."""
    return electrical_report(project_root, mep_text).get("openings", [])


def electrical_equipment(mep: MepModel) -> tuple[list[dict[str, Any]], list[str]]:
    """The electrical equipment of 07 MEP as 07 MEP ``equipment`` (for the analysis loads):
    each item not linked to an equipment (``equipment``) and with no equipment of the same
    story whose footprint covers its centre; typical dimensions and weight where it gives none.
    Returns (equipment dicts, notes)."""
    from saengine.mep.loads import footprint_covers

    electrical = mep.electrical
    if electrical is None:
        return [], []
    out, notes = [], []
    for item in as_dicts(electrical):
        if item.get("equipment"):
            notes.append(f"{item['id']}: its weight is that of equipment {item['equipment']}")
            continue
        under = next(
            (
                e
                for e in mep.equipment
                if e.story == item["story"] and footprint_covers(e, item["x"], item["y"])
            ),
            None,
        )
        if under is not None:
            notes.append(
                f"{item['id']}: stands where equipment {under.id} is; its weight is taken as "
                f"{under.id}'s (link them in 07 MEP, or delete {under.id})"
            )
            continue
        full = with_typical(item, electrical.supply.transformerType)
        if not all(full.get(k) for k in ("length", "width", "operatingWeight")):
            notes.append(f"{item['id']}: no size or weight, not loaded")
            continue
        entry = {
            "id": f"EQ-{item['id']}", "name": item.get("name") or item["kind"],
            "kind": EQUIPMENT_KIND.get(item["kind"], "other"), "story": item["story"],
            "x": item["x"], "y": item["y"], "length": full["length"], "width": full["width"],
            "operatingWeight": full["operatingWeight"],
            "vibrating": bool(item.get("vibrating", item["kind"] == "generator")),
        }  # fmt: skip
        if full.get("height"):
            entry["height"] = full["height"]
        empty = full.get("emptyWeight")
        if item["kind"] == "transformer":
            # A transformer's oil is always there, part of the equipment: dead load (BNBC 2020
            # Part 6 Sec 2.1.4 D "weight of permanent equipment", Sec 2.2.6), whole weight SD.
            empty = None
        if empty is not None and 0 < empty < full["operatingWeight"]:
            # the fuel is the contents: a fluid of well-defined density and controllable
            # maximum height, F (BNBC 2020 Part 6 Sec 2.1.4); it loads as 07 MEP contentsAs
            # (fluid F by default), not as permanent dead load
            entry["emptyWeight"] = empty
        elif empty is not None and empty > full["operatingWeight"]:
            notes.append(f"{item['id']}: empty weight above the operating weight, ignored")
        out.append(entry)
    return out, notes
