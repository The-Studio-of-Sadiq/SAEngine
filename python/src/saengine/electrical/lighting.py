"""Interior lighting design by the lumen method (EN 12464-1 / IES) and circuiting.

Computes per-room luminaire counts, even grid layouts, achieved illuminance, lighting power
density (W/m²) for HVAC gains feedback, and lighting circuits for electrical demand. All design
tables (lux targets, maintenance factor, UF table, luminaire library) come from the code pack's
``electrical.lighting`` table (:mod:`saengine.electrical.tables`).
"""

from __future__ import annotations

import math
import re
from typing import Any

from shapely.geometry import box

from saengine.electrical import tables as T
from saengine.mep import code_pack
from saengine.mep.rooms import room_grid

DEFAULT_CEILING_M = 3.0

_ROOM_LUX_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"operating|theatre|ot\b", "operatingRoom"),
    (r"ward|patient", "hospitalWard"),
    (r"conference|meeting|board", "conference"),
    (r"class|lecture|school", "classroom"),
    (r"corridor|passage|hallway", "corridor"),
    (r"lobby|foyer|reception", "lobby"),
    (r"stair|landing", "stairs"),
    (r"kitchen|pantry|cook", "kitchen"),
    (r"toilet|bath|w\.?c|washroom|restroom|powder", "toilet"),
    (r"bed\s*room|master\s*bed", "bedroom"),
    (r"living|dining|lounge", "living"),
    (r"shop|retail|store\s*front|sales", "retail"),
    (r"warehouse|storage|godown", "warehouse"),
    (r"parking|garage", "parking"),
    (r"workshop|factory|plant|industrial", "industrial"),
    (r"office|study|admin", "office"),
)

_AREA_USE_TO_LUX: dict[str, str] = {
    "residential": "living",
    "residentialPublic": "corridor",
    "office": "office",
    "officeLobby": "lobby",
    "corridorAbove": "corridor",
    "classroom": "classroom",
    "hospitalWard": "hospitalWard",
    "operatingRoom": "operatingRoom",
    "assemblyFixed": "lobby",
    "assemblyMovable": "lobby",
    "retailGround": "retail",
    "retailUpper": "retail",
    "storageLight": "warehouse",
    "storageHeavy": "warehouse",
    "parking": "parking",
    "stairs": "stairs",
}


def _lighting_table() -> Any:
    table = T.LIGHTING
    if table is None:
        raise ValueError(code_pack.not_covered("Lighting design"))
    return table


def room_index(length_m: float, width_m: float, hm_m: float) -> float:
    """Room index K = L * W / (Hm * (L + W))."""
    if length_m <= 0 or width_m <= 0 or hm_m <= 0:
        raise ValueError("room dimensions and mounting height must be positive")
    return (length_m * width_m) / (hm_m * (length_m + width_m))


def utilisation_factor(k: float, reflectance: str | None = None) -> float:
    """Interpolate utilisation factor from the code pack's UF table by room index K."""
    table = _lighting_table()
    steps = table.roomIndexSteps
    ref = reflectance or table.defaultReflectance
    row = table.ufTable.get(ref) or table.ufTable[table.defaultReflectance]
    if k <= steps[0]:
        return float(row[0])
    for i in range(1, len(steps)):
        if k <= steps[i]:
            t = (k - steps[i - 1]) / (steps[i] - steps[i - 1])
            return float(row[i - 1] + t * (row[i] - row[i - 1]))
    return float(row[-1])


def target_lux_for_room(name: str, area_use: str | None = None) -> tuple[float, str]:
    """Resolve target illuminance [lx] and matched use key from room name or area use."""
    table = _lighting_table()
    lower = name.lower()
    for pattern, key in _ROOM_LUX_PATTERNS:
        if re.search(pattern, lower) and key in table.targets:
            return float(table.targets[key]), key
    mapped = _AREA_USE_TO_LUX.get(area_use or "", "office")
    if mapped in table.targets:
        return float(table.targets[mapped]), mapped
    return float(table.targets.get("other", 300.0)), "other"


def lumen_method(
    length_m: float,
    width_m: float,
    *,
    ceiling_height_m: float = DEFAULT_CEILING_M,
    work_plane_m: float | None = None,
    target_lux: float = 500.0,
    luminaire_type: str = "ledPanel600",
    lumens: float | None = None,
    watts: float | None = None,
    shr_max: float | None = None,
    uf: float | None = None,
    mf: float | None = None,
    reflectance: str | None = None,
    outline: Any = None,
) -> dict[str, Any]:
    """Design a single room by the lumen method and lay out luminaires on an even grid.

    E = (N * Phi * UF * MF) / A  =>  N_exact = E * A / (Phi * UF * MF).
    """
    table = _lighting_table()
    spec = table.luminaires.get(luminaire_type) or next(iter(table.luminaires.values()))
    phi = float(lumens if lumens is not None else spec.lumens)
    power_w = float(watts if watts is not None else spec.watts)
    shr = float(shr_max if shr_max is not None else spec.shrMax)
    wp = float(work_plane_m if work_plane_m is not None else table.defaultWorkPlane)
    hm = max(ceiling_height_m - wp, 0.1)
    k = room_index(length_m, width_m, hm)
    uf_used = float(uf if uf is not None else utilisation_factor(k, reflectance))
    mf_used = float(mf if mf is not None else table.maintenanceFactor)
    area = float(outline.area / 1e6) if outline is not None else length_m * width_m
    n_exact = (target_lux * area) / (phi * uf_used * mf_used)
    n_req = max(1, math.ceil(n_exact - 1e-9))
    max_spacing = shr * hm
    poly = outline if outline is not None else box(0.0, 0.0, length_m * 1000.0, width_m * 1000.0)
    grid = room_grid(poly, min_count=n_req, max_sx=max_spacing, max_sy=max_spacing)
    n_placed = len(grid["points"])
    achieved_lux = (n_placed * phi * uf_used * mf_used) / area
    total_watts = n_placed * power_w
    lpd = total_watts / area
    return {
        "luminaireType": luminaire_type,
        "area": round(area, 2),
        "lengthM": round(length_m, 3),
        "widthM": round(width_m, 3),
        "ceilingHeightM": round(ceiling_height_m, 3),
        "workPlaneM": round(wp, 3),
        "mountingHeightM": round(hm, 3),
        "roomIndex": round(k, 4),
        "uf": round(uf_used, 4),
        "mf": round(mf_used, 4),
        "targetLux": round(target_lux, 1),
        "lumensPerLuminaire": phi,
        "wattsPerLuminaire": power_w,
        "shrMax": shr,
        "maxSpacingM": round(max_spacing, 3),
        "requiredExact": round(n_exact, 4),
        "requiredCount": n_req,
        "count": n_placed,
        "nx": grid["nx"],
        "ny": grid["ny"],
        "spacingX": round(grid["sx"], 3),
        "spacingY": round(grid["sy"], 3),
        "achievedLux": round(achieved_lux, 1),
        "totalWatts": round(total_watts, 1),
        "lpd": round(lpd, 2),
        "points": grid["points"],
    }


def _story_clear_height_m(story: str, building: Any, slab_thickness: dict[str, float]) -> float:
    from saengine.electrical.rooms import clear_height

    if building is not None and building.known:
        h = clear_height(story, building, slab_thickness)
        if h and h > 0:
            return h / 1000.0
    return DEFAULT_CEILING_M


def _circuits_for_story(
    story: str, luminaires: list[dict[str, Any]], voltage: float, max_watts: float
) -> list[dict[str, Any]]:
    circuits: list[dict[str, Any]] = []
    idx = 1
    current_watts = 0.0
    current_ids: list[str] = []
    for lum in luminaires:
        w = float(lum.get("watts") or 0.0)
        if current_ids and current_watts + w > max_watts + 1e-9:
            amps = current_watts / voltage
            mcb = 10 if amps <= 8.0 else 16
            cid = f"L-{story}-{idx}"
            circuits.append(
                {
                    "id": cid,
                    "story": story,
                    "luminaires": current_ids,
                    "watts": round(current_watts, 1),
                    "amps": round(amps, 2),
                    "mcbAmps": mcb,
                }
            )
            idx += 1
            current_watts = 0.0
            current_ids = []
        cid = f"L-{story}-{idx}"
        lum["circuit"] = cid
        current_watts += w
        current_ids.append(lum["id"])
    if current_ids:
        amps = current_watts / voltage
        mcb = 10 if amps <= 8.0 else 16
        cid = f"L-{story}-{idx}"
        circuits.append(
            {
                "id": cid,
                "story": story,
                "luminaires": current_ids,
                "watts": round(current_watts, 1),
                "amps": round(amps, 2),
                "mcbAmps": mcb,
            }
        )
    return circuits


def lighting_design(
    mep: Any,
    building: Any = None,
    rooms: Any = None,
    slab_thickness: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Run lumen-method lighting design across rooms (or story footprints when no rooms exist)."""
    table = _lighting_table()
    electrical = getattr(mep, "electrical", None)
    settings = getattr(electrical, "lighting", None) if electrical is not None else None
    overrides = {r.room: r for r in (settings.rooms if settings else [])}
    default_type = settings.luminaireType if settings else "ledPanel600"
    default_mf = settings.maintenanceFactor if settings else None
    default_ref = settings.reflectance if settings else None
    default_wp = settings.workPlaneM if settings else None
    slab_t = slab_thickness or {}

    placed_luminaires: list[dict[str, Any]] = []
    room_results: list[dict[str, Any]] = []
    by_story: dict[str, dict[str, Any]] = {}
    counter = 1

    def add_room_result(
        story_id: str,
        room_id: str | None,
        label: str,
        use_key: str | None,
        outline: Any,
        clear_m: float,
    ) -> None:
        nonlocal counter
        ov = overrides.get(room_id) if room_id else None
        lum_type = (ov.luminaireType if ov and ov.luminaireType else None) or (
            "highBay" if clear_m > 5.0 else default_type
        )
        if ov and ov.targetLux is not None:
            target, matched = float(ov.targetLux), ov.use or "custom"
        else:
            target, matched = target_lux_for_room(ov.use if ov and ov.use else label, use_key)
        minx, miny, maxx, maxy = outline.bounds
        lx = max((maxx - minx) / 1000.0, 0.1)
        wy = max((maxy - miny) / 1000.0, 0.1)
        res = lumen_method(
            lx,
            wy,
            ceiling_height_m=(ov.ceilingHeightM if ov and ov.ceilingHeightM else clear_m),
            work_plane_m=(ov.workPlaneM if ov and ov.workPlaneM is not None else default_wp),
            target_lux=target,
            luminaire_type=lum_type,
            lumens=ov.lumens if ov else None,
            watts=ov.watts if ov else None,
            uf=ov.uf if ov else None,
            mf=(ov.mf if ov and ov.mf is not None else default_mf),
            reflectance=(ov.reflectance if ov and ov.reflectance else default_ref),
            outline=outline,
        )
        res["story"] = story_id
        res["room"] = room_id
        res["label"] = label
        res["use"] = matched
        pts = res.pop("points")
        spec = table.luminaires.get(lum_type) or next(iter(table.luminaires.values()))
        story_lums = []
        for x, y in pts:
            lum = {
                "id": f"LUM-{counter}",
                "type": lum_type,
                "story": story_id,
                "room": room_id,
                "x": x,
                "y": y,
                "z": round(res["ceilingHeightM"] * 1000.0, 1),
                "watts": float(res["wattsPerLuminaire"]),
                "lumens": float(res["lumensPerLuminaire"]),
                "sized": True,
                "length": spec.length,
                "width": spec.width,
            }
            counter += 1
            placed_luminaires.append(lum)
            story_lums.append(lum)
        room_results.append(res)
        st = by_story.setdefault(
            story_id, {"story": story_id, "area": 0.0, "watts": 0.0, "luminaires": []}
        )
        st["area"] += res["area"]
        st["watts"] += res["totalWatts"]
        st["luminaires"].extend(story_lums)

    if rooms is not None and rooms.stories:
        for story_id, story_rooms in rooms.stories.items():
            clear_m = _story_clear_height_m(story_id, building, slab_t)
            for room in story_rooms.rooms:
                add_room_result(
                    story_id, room.id, room.label or room.name, room.use, room.net, clear_m
                )
    elif building is not None and building.known:
        order = building.ordered()
        # Exclude roof slab story unless electrical explicitly lists it
        listed = {s.story for s in (electrical.stories if electrical else [])}
        targets = order[:-1] if len(order) > 1 else order
        for story_id in targets:
            if listed and story_id not in listed:
                continue
            poly = building.roof(story_id)
            if poly is None or poly.is_empty:
                continue
            clear_m = _story_clear_height_m(story_id, building, slab_t)
            use_entry = next(
                (s.use for s in (electrical.stories if electrical else []) if s.story == story_id),
                "office",
            )
            add_room_result(story_id, None, story_id, use_entry, poly, clear_m)

    stories_out: dict[str, dict[str, Any]] = {}
    circuits_out: list[dict[str, Any]] = []
    for story_id, st in by_story.items():
        circuits = _circuits_for_story(
            story_id, st["luminaires"], table.circuitVoltage, table.circuitMaxWatts
        )
        circuits_out.extend(circuits)
        lpd = st["watts"] / st["area"] if st["area"] > 0 else 0.0
        stories_out[story_id] = {
            "story": story_id,
            "area": round(st["area"], 2),
            "watts": round(st["watts"], 1),
            "kw": round(st["watts"] / 1000.0, 3),
            "lpd": round(lpd, 2),
            "count": len(st["luminaires"]),
            "circuits": len(circuits),
        }
    return {
        "rooms": room_results,
        "stories": stories_out,
        "circuits": circuits_out,
        "luminaires": placed_luminaires,
    }


def story_lighting_loads(
    mep: Any,
    building: Any = None,
    rooms: Any = None,
    slab_thickness: dict[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Per-story lighting LPD [W/m²], kW and circuits for electrical demand and HVAC gains.

    Uses entered ``electrical.luminaires`` when present; otherwise runs :func:`lighting_design`
    only if ``electrical.lighting`` is configured (enabled). Returns ``{}`` if neither is set,
    keeping code-table defaults unchanged for models without lighting design.
    """
    electrical = getattr(mep, "electrical", None)
    if electrical is None or T.LIGHTING is None:
        return {}
    table = T.LIGHTING
    if electrical.luminaires:
        by_story: dict[str, list[dict[str, Any]]] = {}
        for lum in electrical.luminaires:
            spec = table.luminaires.get(lum.type)
            watts = float(lum.watts if lum.watts is not None else (spec.watts if spec else 36.0))
            by_story.setdefault(lum.story, []).append({"id": lum.id, "watts": watts})
        out: dict[str, dict[str, Any]] = {}
        order = building.ordered() if building is not None and building.known else list(by_story)
        for story_id, items in by_story.items():
            area = building.floor_area(story_id) if building is not None and building.known else 0.0
            if area <= 0 and rooms is not None and rooms.story(story_id) is not None:
                area = sum(r.area for r in rooms.story(story_id).rooms)
            if area <= 0 and story_id in order:
                from saengine.electrical.demand import story_area

                area = story_area(story_id, building, order)[0]
            watts = sum(i["watts"] for i in items)
            circuits = _circuits_for_story(
                story_id, items, table.circuitVoltage, table.circuitMaxWatts
            )
            out[story_id] = {
                "story": story_id,
                "area": round(area, 2),
                "watts": round(watts, 1),
                "kw": round(watts / 1000.0, 3),
                "lpd": round(watts / area, 2) if area > 0 else 0.0,
                "count": len(items),
                "circuits": len(circuits),
            }
        return out
    if electrical.lighting is not None and electrical.lighting.enabled:
        return lighting_design(mep, building, rooms, slab_thickness)["stories"]
    return {}
