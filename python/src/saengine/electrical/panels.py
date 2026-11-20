"""Distribution boards (panels), circuiting, greedy phase balancing and schedules.

Reuses story loads from :mod:`saengine.electrical.demand`, rooms from :mod:`saengine.mep.rooms`,
risers from :mod:`saengine.electrical.risers`, cable sizing and voltage drop from
:mod:`saengine.electrical.cables`, and IEC 60909 short-circuit checks from
:mod:`saengine.electrical.short_circuit`. Exports schedules to drawing tables and Excel via
:func:`saengine.fem.table_export.write_xlsx`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from saengine.electrical import tables as T
from saengine.electrical.cables import (
    default_cpc_size,
    size_cable,
    standard_breaker,
    voltage_drop_limit,
)
from saengine.electrical.short_circuit import (
    busbar_segment_impedance,
    check_breaking_capacity,
    check_disconnection,
    fault_at_node,
    select_breaking_capacity,
    transformer_source,
)

PHASES = ("L1", "L2", "L3")


def balance_phases(
    items: Sequence[Any],
    phases: tuple[str, ...] = PHASES,
) -> dict[str, Any]:
    """Greedy phase balancing (Longest Processing Time first) to minimise max phase load/current.

    ``items`` may be numbers (``[5, 4, 3, 3, 2, 1]``) or dicts ``{"value": float, "phase":
    optional, "phases": 1|3}``. Locked single-phase items and three-phase items are accumulated
    first; remaining single-phase items are sorted descending and placed on the phase with the
    lowest running total.
    """
    totals = {p: 0.0 for p in phases}
    assignments: list[str] = [""] * len(items)
    flexible: list[tuple[int, float]] = []

    for idx, item in enumerate(items):
        if isinstance(item, (int, float)):
            flexible.append((idx, float(item)))
            continue
        val = float(item.get("value", 0.0))
        n_ph = int(item.get("phases", 1))
        fixed = item.get("phase")
        if n_ph == 3 or fixed == "3P":
            for p in phases:
                totals[p] += val
            assignments[idx] = "3P"
        elif fixed in totals:
            totals[fixed] += val
            assignments[idx] = str(fixed)
        else:
            flexible.append((idx, val))

    for idx, val in sorted(flexible, key=lambda pair: (-pair[1], pair[0])):
        target = min(phases, key=lambda p: (totals[p], phases.index(p)))
        totals[target] += val
        assignments[idx] = target

    vals = list(totals.values())
    max_load = max(vals) if vals else 0.0
    min_load = min(vals) if vals else 0.0
    avg = sum(vals) / len(vals) if vals else 0.0
    imbalance = ((max_load - min_load) / avg * 100.0) if avg > 0 else 0.0
    return {
        "assignments": assignments,
        "phaseLoads": totals,
        "maxPhaseLoad": max_load,
        "minPhaseLoad": min_load,
        "imbalancePct": imbalance,
    }


def _split_load(
    prefix: str,
    description: str,
    kind: str,
    load_w: float,
    points: int,
    room: str | None,
    length_m: float,
) -> list[dict[str, Any]]:
    """Split a room/area load into final circuits respecting the pack's max points & max W."""
    if load_w <= 1e-6:
        return []
    rules = T.circuit_rules()
    defaults = rules.circuitDefaults[kind]
    max_pts = int(rules.maxPointsPerCircuit.get(kind, 1))
    max_w = float(defaults.maxLoadW)
    n_by_pts = math.ceil(max(1, points) / max_pts)
    n_by_load = math.ceil(load_w / max_w)
    count = max(1, n_by_pts, n_by_load)
    each_w = load_w / count
    pts_each = [points // count + (1 if i < points % count else 0) for i in range(count)]
    out = []
    for i in range(count):
        suffix = f"-{i + 1}" if count > 1 else ""
        desc = description if count == 1 else f"{description} ({i + 1}/{count})"
        out.append(
            {
                "id": f"{prefix}{suffix}",
                "description": desc,
                "kind": kind,
                "room": room,
                "points": max(1, pts_each[i]),
                "loadW": each_w,
                "powerFactor": float(defaults.pf),
                "phases": 1,
                "deviceType": "MCB",
                "curve": defaults.curve,
                "conductor": rules.defaultConductor,
                "insulation": rules.defaultFinalInsulation,
                "method": rules.defaultMethod,
                "length": length_m,
                "ambientTemp": float(rules.defaultAmbientTemp),
                "groupedCircuits": 1,
                "groupingArrangement": "bunched",
                "thermalInsulation": "none",
            }
        )
    return out


def _story_circuits_from_rooms(
    story_dem: dict[str, Any],
    story_rooms: Any,
    db_xy: tuple[float, float] | None,
) -> list[dict[str, Any]]:
    """Generate final circuits from architectural rooms while matching story connected load."""
    rules = T.circuit_rules()
    defaults = rules.circuitDefaults
    rooms = [r for r in story_rooms.rooms if r.area > 0]
    if not rooms:
        return []

    total_room_area = sum(r.area for r in rooms)
    connected_w = float(story_dem.get("connected") or 0.0) * 1000.0
    other_w = float(story_dem.get("other") or 0.0) * 1000.0
    area_load_w = max(0.0, connected_w - other_w)

    # Extract lighting, power and A/C shares from the story demand breakdown.
    parts = {p["part"]: float(p["kw"]) * 1000.0 for p in story_dem.get("breakdown") or []}
    light_w = parts.get("lighting", 0.0)
    power_w = parts.get("power", 0.0)
    min_w = parts.get("minimum", 0.0)
    ac_w = parts.get("airConditioning", 0.0)
    if "lightingAndPower" in parts:
        # Table 8.1.17 combined non-A/C density: split 35 % lighting / 65 % sockets & power.
        combined = parts["lightingAndPower"]
        light_w = 0.35 * combined
        power_w = 0.65 * combined
    else:
        power_w += min_w
    # Ensure exact sum to area_load_w.
    scale = (area_load_w / (light_w + power_w + ac_w)) if (light_w + power_w + ac_w) > 0 else 1.0
    light_w, power_w, ac_w = light_w * scale, power_w * scale, ac_w * scale

    circuits: list[dict[str, Any]] = []
    idx = 1
    for room in rooms:
        share = room.area / total_room_area if total_room_area > 0 else 0.0
        length = 20.0
        if db_xy is not None:
            c = room.net.centroid
            dist_m = (abs(c.x - db_xy[0]) + abs(c.y - db_xy[1])) / 1000.0
            length = max(10.0, round(dist_m + 5.0, 1))
        room_label = room.label or room.id

        if light_w > 0:
            pts = max(1, math.ceil(room.area / float(defaults["lighting"].areaPerPoint)))
            ckts = _split_load(
                f"{story_dem['story']}-L{idx}",
                f"{room_label} lighting",
                "lighting",
                light_w * share,
                pts,
                room.id,
                length,
            )
            circuits.extend(ckts)
        if power_w > 0:
            pts = max(1, math.ceil(room.area / float(defaults["socket"].areaPerPoint)))
            ckts = _split_load(
                f"{story_dem['story']}-S{idx}",
                f"{room_label} sockets",
                "socket",
                power_w * share,
                pts,
                room.id,
                length,
            )
            circuits.extend(ckts)
        if ac_w > 0:
            pts = max(1, math.ceil(room.area / float(defaults["ac"].areaPerPoint)))
            ckts = _split_load(
                f"{story_dem['story']}-AC{idx}",
                f"{room_label} A/C",
                "ac",
                ac_w * share,
                pts,
                room.id,
                length,
            )
            circuits.extend(ckts)
        idx += 1

    if other_w > 0:
        circuits.extend(
            _split_load(
                f"{story_dem['story']}-P{idx}",
                f"{story_dem['story']} other power",
                "power",
                other_w,
                1,
                None,
                20.0,
            )
        )
    return circuits


def _story_circuits_from_demand(story_dem: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate final circuits directly from a story's demand breakdown when no rooms exist."""
    rules = T.circuit_rules()
    defaults = rules.circuitDefaults
    sid = story_dem["story"]
    parts = {p["part"]: float(p["kw"]) * 1000.0 for p in story_dem.get("breakdown") or []}
    area = float(story_dem.get("area") or 0.0)
    circuits: list[dict[str, Any]] = []

    if "lightingAndPower" in parts:
        combined = parts["lightingAndPower"]
        light_w = 0.35 * combined
        power_w = 0.65 * combined
    else:
        light_w = parts.get("lighting", 0.0)
        power_w = parts.get("power", 0.0) + parts.get("minimum", 0.0)
    ac_w = parts.get("airConditioning", 0.0)
    other_w = parts.get("other", 0.0)

    if light_w > 0:
        pts = max(1, math.ceil(area / float(defaults["lighting"].areaPerPoint))) if area else 1
        circuits.extend(
            _split_load(f"{sid}-L", f"{sid} lighting", "lighting", light_w, pts, None, 20.0)
        )
    if power_w > 0:
        pts = max(1, math.ceil(area / float(defaults["socket"].areaPerPoint))) if area else 1
        circuits.extend(
            _split_load(f"{sid}-S", f"{sid} sockets & power", "socket", power_w, pts, None, 20.0)
        )
    if ac_w > 0:
        pts = max(1, math.ceil(area / float(defaults["ac"].areaPerPoint))) if area else 1
        circuits.extend(_split_load(f"{sid}-AC", f"{sid} A/C", "ac", ac_w, pts, None, 25.0))
    if other_w > 0:
        circuits.extend(
            _split_load(f"{sid}-P", f"{sid} other power", "power", other_w, 1, None, 20.0)
        )
    return circuits


def _feeder_length(story: str, building: Any, riser: Any | None = None) -> float:
    """Estimate sub-main / riser cable length [m] from the ground/lowest level to ``story``."""
    base_z = min(building.stories.values()) if building.known and building.stories else 0.0
    z = building.stories.get(story, base_z) if building.known else base_z
    rise_m = max(0.0, (z - base_z) / 1000.0)
    return max(5.0, round(rise_m + 10.0, 1))


def generate_boards(
    electrical: Any,
    demand_result: dict[str, Any],
    building: Any,
    room_inputs: Any = None,
    risers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build distribution board dicts from entered ``electrical.boards`` or auto-generate per
    story from ``demand_result`` and ``room_inputs``."""
    rules = T.circuit_rules()
    riser_by_story: dict[str, str] = {}
    for r in risers or []:
        for s in r.get("fed") or []:
            riser_by_story.setdefault(s, r["id"])
    story_demands = {s["story"]: s for s in demand_result.get("stories") or []}

    if getattr(electrical, "boards", None):
        boards: list[dict[str, Any]] = []
        for b in electrical.boards:
            raw = b.model_dump(mode="json")
            if not raw.get("circuits") and b.story in story_demands:
                sr = room_inputs.story(b.story) if room_inputs is not None else None
                db_xy = (b.x, b.y) if b.x is not None and b.y is not None else None
                ckts = (
                    _story_circuits_from_rooms(story_demands[b.story], sr, db_xy)
                    if sr is not None and sr.rooms
                    else _story_circuits_from_demand(story_demands[b.story])
                )
                raw["circuits"] = ckts
            if not raw.get("fedFrom"):
                raw["fedFrom"] = riser_by_story.get(b.story)
            boards.append(raw)
        return boards

    boards = []
    for s in demand_result.get("stories") or []:
        sid = s["story"]
        sr = room_inputs.story(sid) if room_inputs is not None else None
        ckts = (
            _story_circuits_from_rooms(s, sr, None)
            if sr is not None and sr.rooms
            else _story_circuits_from_demand(s)
        )
        if not ckts:
            continue
        fed = riser_by_story.get(sid)
        boards.append(
            {
                "id": f"DB-{sid}",
                "name": f"{s.get('name', sid)} Distribution Board",
                "story": sid,
                "room": None,
                "fedFrom": fed,
                "feederLength": _feeder_length(sid, building),
                "feederMethod": rules.defaultMethod,
                "feederInsulation": rules.defaultFeederInsulation,
                "feederConductor": rules.defaultConductor,
                "feederGrouped": 1,
                "phases": 3,
                "poles": 4,
                "incomerType": "MCCB",
                "circuits": ckts,
            }
        )

    motors = demand_result.get("motors") or []
    if motors:
        order = building.ordered() if building.known else []
        motor_story = order[0] if order else (boards[0]["story"] if boards else "GF")
        m_ckts: list[dict[str, Any]] = []
        m_def = rules.circuitDefaults["motor"]
        for m in motors:
            for k in range(1, int(m["count"]) + 1):
                suffix = f"-{k}" if m["count"] > 1 else ""
                m_ckts.append(
                    {
                        "id": f"{m['id']}{suffix}",
                        "description": f"{m['kind']} {m['id']}{suffix}",
                        "kind": "motor",
                        "points": 1,
                        "loadW": float(m["power"]) * 1000.0,
                        "powerFactor": float(m_def.pf),
                        "phases": 3,
                        "phase": "3P",
                        "deviceType": "MCCB" if float(m["power"]) > 15.0 else "MCB",
                        "curve": m_def.curve,
                        "conductor": rules.defaultConductor,
                        "insulation": rules.defaultFeederInsulation,
                        "method": rules.defaultMethod,
                        "length": 25.0,
                        "ambientTemp": float(rules.defaultAmbientTemp),
                        "groupedCircuits": 1,
                        "groupingArrangement": "bunched",
                        "thermalInsulation": "none",
                    }
                )
        boards.append(
            {
                "id": "DB-MOTOR",
                "name": "Motor & Plant Distribution Board",
                "story": motor_story,
                "room": "Plant / LT Room",
                "fedFrom": "LT1",
                "feederLength": 15.0,
                "feederMethod": rules.defaultMethod,
                "feederInsulation": rules.defaultFeederInsulation,
                "feederConductor": rules.defaultConductor,
                "feederGrouped": 1,
                "phases": 3,
                "poles": 4,
                "incomerType": "MCCB",
                "circuits": m_ckts,
            }
        )
    return boards


def _circuit_load_and_ib(ckt: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return ``(load_w, load_va, pf, ib_a)`` for one circuit."""
    rules = T.circuit_rules()
    kind = str(ckt.get("kind") or "power")
    default_pf = float(rules.circuitDefaults.get(kind, rules.circuitDefaults["power"]).pf)
    pf = float(ckt.get("powerFactor") or default_pf)
    load_w = ckt.get("loadW")
    load_va = ckt.get("loadVA")
    if load_w is None and load_va is not None:
        load_w = float(load_va) * pf
        load_va = float(load_va)
    elif load_w is not None and load_va is None:
        load_w = float(load_w)
        load_va = load_w / pf if pf > 0 else load_w
    else:
        load_w = float(load_w or 0.0)
        load_va = float(load_va or 0.0)
    phases = int(ckt.get("phases") or 1)
    if load_va <= 0:
        return 0.0, 0.0, pf, 0.0
    if phases == 1:
        ib = load_va / float(rules.phaseVoltage)
    else:
        ib = load_va / (math.sqrt(3) * float(T.LT_VOLTAGE))
    return load_w, load_va, pf, ib


def evaluate_boards(
    boards: list[dict[str, Any]],
    supply_result: dict[str, Any],
    demand_result: dict[str, Any],
    building: Any,
    risers: list[dict[str, Any]] | None = None,
    vd_mode: str = "mv_a_m",
) -> dict[str, Any]:
    """Evaluate all DBs: phase balancing, cable sizing, cumulative voltage drop, and IEC 60909
    short-circuit / breaking-capacity / Zs disconnection checks.
    """
    rules = T.circuit_rules()
    sc = T.short_circuit()
    tx_info = (supply_result or {}).get("transformers") or {}
    tx_kva = float(tx_info.get("rating") or 0.0)
    if tx_kva <= 0:
        kva_req = float((demand_result or {}).get("kva") or 100.0)
        tx_kva = T.next_size(kva_req, T.TRANSFORMER_SIZES) or float(T.TRANSFORMER_SIZES[0])

    source = transformer_source(tx_kva, parallel=1)
    riser_map = {r["id"]: r for r in (risers or [])}

    evaluated_boards: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    failing_vd: list[dict[str, Any]] = []

    for raw in boards:
        ckts_raw = [dict(c) for c in raw.get("circuits") or []]
        # 1. Compute Ib for each circuit and balance 1-phase loads across L1, L2, L3.
        balance_inputs = []
        parsed_ckts: list[dict[str, Any]] = []
        for c in ckts_raw:
            load_w, load_va, pf, ib = _circuit_load_and_ib(c)
            parsed_ckts.append(
                {
                    **c,
                    "loadW": load_w,
                    "loadVA": load_va,
                    "powerFactor": pf,
                    "ib": ib,
                }
            )
            balance_inputs.append(
                {
                    "value": ib,
                    "phase": c.get("phase"),
                    "phases": int(c.get("phases") or 1),
                }
            )

        bal = (
            balance_phases(balance_inputs)
            if int(raw.get("phases", 3)) == 3
            else {
                "assignments": [
                    "L1" if int(c.get("phases") or 1) == 1 else "3P" for c in parsed_ckts
                ],
                "phaseLoads": {"L1": sum(c["ib"] for c in parsed_ckts), "L2": 0.0, "L3": 0.0},
                "maxPhaseLoad": sum(c["ib"] for c in parsed_ckts),
                "minPhaseLoad": sum(c["ib"] for c in parsed_ckts),
                "imbalancePct": 0.0,
            }
        )
        for c, ph in zip(parsed_ckts, bal["assignments"], strict=True):
            c["phase"] = ph

        # 2. Sum circuit loads to incomer load & phase totals.
        total_w = sum(c["loadW"] for c in parsed_ckts)
        total_q = sum(
            c["loadW"] * math.tan(math.acos(min(1.0, max(0.01, c["powerFactor"]))))
            for c in parsed_ckts
        )
        total_va = math.hypot(total_w, total_q)
        max_phase_ib = float(bal["maxPhaseLoad"])
        db_phases = int(raw.get("phases", 3))
        if db_phases == 3:
            incomer_ib = max(max_phase_ib, total_va / (math.sqrt(3) * float(T.LT_VOLTAGE)))
        else:
            incomer_ib = total_va / float(rules.phaseVoltage)

        incomer_type = str(raw.get("incomerType") or "MCCB")
        incomer_in = float(
            raw.get("incomerRating")
            or standard_breaker(max(incomer_ib, 16.0))
            or rules.breakerRatings[-1]
        )
        busbar_rating = float(
            raw.get("busbarRating")
            or T.next_size(incomer_in, rules.busbarRatings)
            or rules.busbarRatings[-1]
        )
        raw_ways = len(parsed_ckts)
        ways = int(raw.get("ways") or T.next_size(raw_ways, rules.standardWays) or raw_ways)

        # 3. Upstream riser + sub-main feeder cable sizing and short circuit at the DB.
        upstream_segments: list[dict[str, Any]] = []
        upstream_vd = 0.0
        fed_from = raw.get("fedFrom")
        if fed_from and fed_from in riser_map:
            r = riser_map[fed_from]
            base_z = min(building.stories.values()) if building.known and building.stories else 0.0
            story_z = building.stories.get(raw["story"], base_z) if building.known else base_z
            r_len = max(3.0, (story_z - base_z) / 1000.0)
            if r["kind"] == "busbar":
                b_rating = float(r.get("rating") or 400.0)
                upstream_segments.append(
                    {
                        "kind": "busbar",
                        "rating": b_rating,
                        "length": r_len,
                    }
                )
                zb = busbar_segment_impedance(b_rating, r_len)
                vd_bus_v = math.sqrt(3) * float(r.get("current") or 0.0) * zb["rPh"]
                upstream_vd += vd_bus_v / float(T.LT_VOLTAGE) * 100.0

        upstream_fault = fault_at_node(source, upstream_segments)
        feeder_len = float(raw.get("feederLength") or 15.0)
        feeder_cond = str(raw.get("feederConductor") or rules.defaultConductor)
        feeder_ins = str(raw.get("feederInsulation") or rules.defaultFeederInsulation)
        feeder_meth = str(raw.get("feederMethod") or rules.defaultMethod)
        feeder_grouped = int(raw.get("feederGrouped") or 1)
        feeder_pf = (total_w / total_va) if total_va > 0 else float(T.POWER_FACTOR)

        # Sub-main reserves e.g. 2.0 % Vd so final circuits have room under 3 % / 5 %;
        # cumulative Vd is checked strictly at every final circuit!
        feeder_cable = size_cable(
            max(incomer_ib, 1.0),
            feeder_len,
            phases=db_phases,
            pf=feeder_pf,
            kind="power",
            conductor=feeder_cond,
            insulation=feeder_ins,
            method=feeder_meth,
            grouped_circuits=feeder_grouped,
            in_rating=incomer_in,
            upstream_vd_pct=upstream_vd,
            vd_limit_pct=float(voltage_drop_limit("lighting")) - 1.0,
            vd_mode=vd_mode,
            ik_ka=upstream_fault["ik3MaxKa"],
            fault_duration_s=float(sc.faultDurationS.get("submain", 0.1)),
            specified_size=raw.get("feederCableSize"),
        )
        feeder_cpc = float(raw.get("feederCpcSize") or default_cpc_size(feeder_cable["size"]))
        db_segments = [
            *upstream_segments,
            {
                "size": feeder_cable["size"],
                "length": feeder_len,
                "conductor": feeder_cond,
                "insulation": feeder_ins,
                "cpcSize": feeder_cpc,
            },
        ]
        db_fault = fault_at_node(source, db_segments)
        incomer_icu = (
            raw.get("breakingCapacityKa")
            if raw.get("breakingCapacityKa") is not None
            else select_breaking_capacity(db_fault["ik3MaxKa"], incomer_type)
        )
        incomer_sc = check_breaking_capacity(db_fault["ik3MaxKa"], incomer_type, incomer_icu)
        checks.append(
            {
                "name": f"{raw['id']} incomer breaking capacity",
                "demand": db_fault["ik3MaxKa"],
                "capacity": incomer_sc["icuKa"],
                "unit": "kA",
                "utilisation": db_fault["ik3MaxKa"] / incomer_sc["icuKa"]
                if incomer_sc["icuKa"]
                else 0.0,
                "ok": incomer_sc["ok"],
                "note": incomer_sc["note"]
                or f"Ik3 {db_fault['ik3MaxKa']:.2f} kA <= {incomer_sc['icuKa']:g} kA",
            }
        )
        db_cum_vd = feeder_cable["cumVdPct"]

        # 4. Evaluate each final circuit: breaker, cable sizing, cumulative Vd, breaking capacity, Zs.
        evaluated_ckts: list[dict[str, Any]] = []
        for way_no, c in enumerate(parsed_ckts, start=1):
            kind = str(c.get("kind") or "power")
            c_def = rules.circuitDefaults.get(kind, rules.circuitDefaults["power"])
            curve = str(c.get("curve") or c_def.curve)
            dev_type = str(c.get("deviceType") or "MCB")
            c_in = float(
                c.get("rating") or standard_breaker(max(c["ib"], 1.0)) or rules.breakerRatings[-1]
            )
            c_phases = int(c.get("phases") or 1)
            c_len = float(c.get("length") or 20.0)
            c_cond = str(c.get("conductor") or rules.defaultConductor)
            c_ins = str(c.get("insulation") or rules.defaultFinalInsulation)
            c_meth = str(c.get("method") or rules.defaultMethod)

            c_cable = size_cable(
                max(c["ib"], 0.1),
                c_len,
                phases=c_phases,
                pf=c["powerFactor"],
                kind=kind,
                conductor=c_cond,
                insulation=c_ins,
                method=c_meth,
                ambient_temp=c.get("ambientTemp"),
                grouped_circuits=int(c.get("groupedCircuits") or 1),
                grouping_arrangement=str(c.get("groupingArrangement") or "bunched"),
                thermal_insulation=str(c.get("thermalInsulation") or "none"),
                in_rating=c_in,
                upstream_vd_pct=db_cum_vd,
                vd_mode=vd_mode,
                ik_ka=db_fault["ik3MaxKa"],
                fault_duration_s=float(sc.faultDurationS.get("final", 0.01)),
                specified_size=c.get("cableSize"),
            )
            cpc_size = float(c.get("cpcSize") or default_cpc_size(c_cable["size"]))
            end_fault = fault_at_node(
                source,
                [
                    *db_segments,
                    {
                        "size": c_cable["size"],
                        "length": c_len,
                        "conductor": c_cond,
                        "insulation": c_ins,
                        "cpcSize": cpc_size,
                    },
                ],
            )
            c_icu = (
                c.get("breakingCapacityKa")
                if c.get("breakingCapacityKa") is not None
                else select_breaking_capacity(db_fault["ik3MaxKa"], dev_type)
            )
            c_brk = check_breaking_capacity(db_fault["ik3MaxKa"], dev_type, c_icu)
            c_zs = check_disconnection(end_fault["zsOhm"], c_in, curve=curve)
            c_ok = c_cable["ok"] and c_brk["ok"] and c_zs["ok"]
            if not c_cable["vdOk"]:
                failing_vd.append(
                    {
                        "board": raw["id"],
                        "circuit": c["id"],
                        "description": c["description"],
                        "cableSize": c_cable["size"],
                        "cumVdPct": c_cable["cumVdPct"],
                        "limitPct": c_cable["vdLimitPct"],
                        "recommendedSize": c_cable["recommendedSize"],
                    }
                )
            evaluated_ckts.append(
                {
                    "way": c.get("way") or way_no,
                    "id": c["id"],
                    "description": c["description"],
                    "kind": kind,
                    "room": c.get("room"),
                    "points": c.get("points", 1),
                    "loadW": round(c["loadW"], 2),
                    "loadVA": round(c["loadVA"], 2),
                    "powerFactor": c["powerFactor"],
                    "phases": c_phases,
                    "phase": c["phase"],
                    "ib": round(c["ib"], 2),
                    "deviceType": dev_type,
                    "curve": curve,
                    "rating": c_in,
                    "breakingCapacityKa": c_brk["icuKa"],
                    "cableSize": c_cable["size"],
                    "cpcSize": cpc_size,
                    "conductor": c_cond,
                    "insulation": c_ins,
                    "method": c_meth,
                    "length": c_len,
                    "It": c_cable["It"],
                    "Iz": round(c_cable["Iz"], 2),
                    "vdV": round(c_cable["vdV"], 3),
                    "vdPct": round(c_cable["vdPct"], 3),
                    "cumVdPct": round(c_cable["cumVdPct"], 3),
                    "vdLimitPct": c_cable["vdLimitPct"],
                    "vdOk": c_cable["vdOk"],
                    "ampacityOk": c_cable["ampacityOk"],
                    "faultOk": c_cable["faultOk"],
                    "recommendedSize": c_cable["recommendedSize"],
                    "endZsOhm": round(end_fault["zsOhm"], 4),
                    "zsMaxOhm": round(c_zs["zsMaxOhm"], 4),
                    "disconnectionOk": c_zs["ok"],
                    "breakingOk": c_brk["ok"],
                    "ok": c_ok,
                    "note": "; ".join(
                        n for n in (c_cable["note"], c_brk["note"], c_zs["note"]) if n
                    ),
                }
            )

        all_ckt_ok = all(c["ok"] for c in evaluated_ckts)
        max_vd = max((c["cumVdPct"] for c in evaluated_ckts), default=db_cum_vd)
        checks.append(
            {
                "name": f"{raw['id']} circuits & voltage drop",
                "demand": max_vd,
                "capacity": float(voltage_drop_limit("lighting")),
                "unit": "%",
                "utilisation": max_vd / float(voltage_drop_limit("lighting")),
                "ok": all_ckt_ok,
                "note": (
                    "all circuits pass ampacity, Vd, breaking capacity and Zs"
                    if all_ckt_ok
                    else f"{sum(not c['ok'] for c in evaluated_ckts)} circuit(s) fail"
                ),
            }
        )

        evaluated_boards.append(
            {
                "id": raw["id"],
                "name": raw.get("name") or raw["id"],
                "story": raw["story"],
                "room": raw.get("room"),
                "fedFrom": fed_from,
                "phases": db_phases,
                "poles": int(raw.get("poles", 4 if db_phases == 3 else 2)),
                "incomerType": incomer_type,
                "incomerRating": incomer_in,
                "busbarRating": busbar_rating,
                "ways": ways,
                "usedWays": len(evaluated_ckts),
                "feederLength": feeder_len,
                "feederCableSize": feeder_cable["size"],
                "feederCpcSize": feeder_cpc,
                "feederConductor": feeder_cond,
                "feederInsulation": feeder_ins,
                "feederMethod": feeder_meth,
                "feederVdPct": round(feeder_cable["vdPct"], 3),
                "upstreamVdPct": round(db_cum_vd, 3),
                "totalLoadW": round(total_w, 2),
                "totalLoadVA": round(total_va, 2),
                "incomerIb": round(incomer_ib, 2),
                "phaseLoadsA": {k: round(v, 2) for k, v in bal["phaseLoads"].items()},
                "imbalancePct": round(bal["imbalancePct"], 1),
                "ik3MaxKa": round(db_fault["ik3MaxKa"], 3),
                "ik1MinKa": round(db_fault["ik1MinKa"], 3),
                "zsOhm": round(db_fault["zsOhm"], 4),
                "incomerBreakingOk": incomer_sc["ok"],
                "ok": incomer_sc["ok"] and all_ckt_ok,
                "circuits": evaluated_ckts,
            }
        )

    return {
        "source": source,
        "boards": evaluated_boards,
        "failingVd": failing_vd,
        "checks": checks,
    }


def db_schedule_table(board: dict[str, Any]) -> dict[str, Any]:
    """Schedule table dict (``name``, ``columns``, ``rows``, ``notes``) for one DB.

    Compatible with :func:`saengine.fem.table_export.write_xlsx`.
    """
    columns = [
        "Way",
        "Description",
        "Load (W)",
        "Phase",
        "MCB",
        "Cable",
        "Length (m)",
        "Vd (%)",
    ]
    rows: list[list[Any]] = []
    for c in board.get("circuits") or []:
        mcb = f"{c['deviceType']} {c['curve']}{c['rating']:g}A"
        cable = f"{c['cableSize']:g} mm² {c['conductor']} {c['insulation']}"
        rows.append(
            [
                c["way"],
                c["description"],
                round(float(c["loadW"]), 1),
                c["phase"],
                mcb,
                cable,
                round(float(c["length"]), 1),
                round(float(c["cumVdPct"]), 2),
            ]
        )
    notes = [
        (
            f"{board['id']} ({board['story']}): {board['phases']}P {board['poles']}P, "
            f"Incomer {board['incomerType']} {board['incomerRating']:g} A, "
            f"Busbar {board['busbarRating']:g} A, {board['usedWays']}/{board['ways']} ways"
        ),
        (
            f"Total connected load: {board['totalLoadW']:.1f} W ({board['totalLoadVA']:.1f} VA), "
            f"Ik3 max = {board['ik3MaxKa']:.2f} kA, Ik1 min = {board['ik1MinKa']:.2f} kA, "
            f"Feeder: {board['feederCableSize']:g} mm² {board['feederConductor']} "
            f"{board['feederInsulation']} ({board['feederLength']:g} m)"
        ),
    ]
    return {
        "name": f"{board['id']} Schedule",
        "columns": columns,
        "rows": rows,
        "notes": notes,
    }


def export_db_schedules_xlsx(
    path: str | Path,
    boards: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Write all distribution-board schedules to an Excel workbook via ``write_xlsx``."""
    from saengine.fem.table_export import write_xlsx

    summary_rows = [
        [
            b["id"],
            b["story"],
            b.get("fedFrom") or "-",
            f"{b['incomerType']} {b['incomerRating']:g} A",
            b["busbarRating"],
            b["ways"],
            b["totalLoadW"],
            b["ik3MaxKa"],
            b["ik1MinKa"],
            "PASS" if b["ok"] else "FAIL",
        ]
        for b in boards
    ]
    sheets = [
        {
            "name": "DB Summary",
            "columns": [
                "DB",
                "Story",
                "Fed From",
                "Incomer",
                "Busbar (A)",
                "Ways",
                "Total Load (W)",
                "Ik3 max (kA)",
                "Ik1 min (kA)",
                "Status",
            ],
            "rows": summary_rows,
        },
        *[db_schedule_table(b) for b in boards],
    ]
    return write_xlsx(path, sheets)
