"""Fire water: the demand, the reservoir, the fire pumps and their room (BNBC 2020 Part 4).

- Demand (Table 4.4.1, p322; Sec 4.2.3.2, p326-327; Sec 4.2.3.5, p328): the standpipe flow of the
  hazard for the first standpipe plus 1000 l/min for each other (at most eight); the sprinkler
  flow the more of Table 4.4.1's and the hydraulically calculated demand; a combined system the
  two together.
- Reservoir (Table 4.4.1 durations by the building height; Sec 4.2.2.3, p325): each flow for its
  duration. The water is kept for fire fighting only (Sec 4.2.3.7, p328).
- Fire pumps (Sec 4.2.2.5, p325-326; Table 4.4.2, p328): an automatic main pump of the next
  Table 4.4.2 rating at a net pressure of at least 272 kPa, a secondary (standby) pump on a
  diesel engine or an alternate supply, and the pressurising (jockey) pump of Figure 4.4.5, sized
  to NFPA 20 practice (from memory, to be checked). Motor power from the duty at a typical
  efficiency; the sets' sizes and weights are typical (from memory), to be replaced with the
  selected pump's data.
- Hanger and riser-support loads (Sec 4.2.3.13-4.2.3.14, p330; Sec 4.2.10.6, p332): supports carry
  the water-filled pipe + 110 kg, hangers five times the water-filled pipe + 110 kg, horizontal
  standpipe hangers at most 5 m apart.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.fire import tables as T

G = 9.80665


def standpipe_flow(hazard: str, standpipes: int) -> tuple[float, str]:
    """Sec 4.2.3.2: the supply of ``standpipes`` standpipes [l/min] and how it was found."""
    first = T.FLOWS[hazard][1]
    extra = min(max(standpipes - 1, 0), T.MAX_ADDITIONAL_STANDPIPES)
    flow = first + T.ADDITIONAL_STANDPIPE_FLOW * extra
    note = (
        f"{first:g} l/min for the first standpipe ({T.HAZARD_LABELS[hazard]}, {T.PAGES['4.4.1']})"
        + (
            f" + {extra} x {T.ADDITIONAL_STANDPIPE_FLOW:g} l/min for the others"
            + (
                f" (at most {T.MAX_ADDITIONAL_STANDPIPES} counted)"
                if standpipes - 1 > extra
                else ""
            )
            if extra
            else ""
        )
        + f" = {flow:g} l/min ({T.PAGES['4.2.3.2']})"
    )
    return flow, note


def demand(
    hazard: str,
    height: float,
    standpipes: int,
    hydrant: bool,
    sprinklers: bool,
    hydraulic_sprinkler: float | None,
) -> dict[str, Any]:
    """Flows [l/min], durations [min] and the reservoir [m³] the fire systems need."""
    minutes = T.duration(hazard, height)
    notes = []
    stand = 0.0
    if hydrant:
        stand, note = standpipe_flow(hazard, max(standpipes, 1))
        notes.append(note)
    sprinkler = 0.0
    if sprinklers:
        table = T.FLOWS[hazard][0]
        sprinkler = max(table, hydraulic_sprinkler or 0.0)
        notes.append(
            f"sprinklers: the more of {table:g} l/min ({T.PAGES['4.4.1']}) and the hydraulic "
            f"demand {hydraulic_sprinkler or 0:.0f} l/min = {sprinkler:.0f} l/min"
        )
    flow = stand + sprinkler
    if hydrant and sprinklers:
        notes.append(
            f"combined system: Table 4.4.1 plus the hydraulically calculated sprinkler demand "
            f"({T.PAGES['4.2.3.5']}): {stand:g} + {sprinkler:.0f} = {flow:.0f} l/min"
        )
    volume = flow * minutes / 1000.0
    notes.append(
        f"duration {minutes} min for a building {height:.1f} m high ({T.PAGES['4.4.1']}): "
        f"{flow:.0f} l/min x {minutes} min = {volume:.1f} m³"
    )
    return {
        "hazard": hazard,
        "standpipe": round(stand, 1),
        "sprinkler": round(sprinkler, 1),
        "flow": round(flow, 1),
        "duration": minutes,
        "volume": round(volume, 2),
        "notes": notes,
    }


def pump_rating(flow: float) -> dict[str, Any]:
    """The Table 4.4.2 rating at least ``flow`` [l/min] and its least discharge [mm]; above
    the table's largest, pumps of the largest rating in parallel."""
    for rating, discharge in T.PUMP_RATINGS:
        if rating >= flow - 1e-6:
            return {"rating": float(rating), "discharge": discharge, "count": 1}
    rating, discharge = T.PUMP_RATINGS[-1]
    count = math.ceil(flow / rating - 1e-9)
    return {"rating": float(rating), "discharge": discharge, "count": count}


def power(flow: float, head: float, efficiency: float) -> float:
    """Shaft power [kW] of ``flow`` [l/min] at ``head`` [m]."""
    return 1000.0 * G * flow / 60000.0 * head / efficiency / 1000.0


def motor(kw: float) -> float:
    """The next IEC motor size [kW] with 10 % in hand (SAEngine)."""
    need = kw * 1.1
    for size in T.MOTOR_SIZES:
        if size >= need - 1e-9:
            return size
    return math.ceil(need / 10.0) * 10.0


def typical_set(duty: str, kw: float, standby: str = "diesel") -> dict[str, float]:
    """Typical plan size [mm], height [mm] and operating weight [kN] of a fire pump set of
    ``kw`` (from memory, to be replaced with the selected set's data)."""
    if duty == "jockey":
        return {"length": 800.0, "width": 450.0, "height": 900.0, "operatingWeight": 1.2}
    if duty == "standby" and standby == "diesel":
        # engine, pump and base frame, with its fuel tank (NFPA 20: about 5 l a kW, MEMORY)
        mass = 800.0 + 14.0 * kw + 0.84 * 5.0 * kw
        return {
            "length": round(2400.0 + 10.0 * kw, -1),
            "width": 1000.0,
            "height": 1500.0,
            "operatingWeight": round(mass * G / 1000.0, 1),
        }
    mass = 200.0 + 9.0 * kw
    return {
        "length": round(1300.0 + 10.0 * kw, -1),
        "width": round(600.0 + 3.0 * kw, -1),
        "height": 1000.0,
        "operatingWeight": round(mass * G / 1000.0, 1),
    }


def pumps(flow: float, head: float, standby: str) -> list[dict[str, Any]]:
    """The fire pump sets for a duty of ``flow`` [l/min] at ``head`` [m]: main, standby and
    jockey (sizes, power and typical weights)."""
    rate = pump_rating(flow)
    rated_head = max(head, T.PUMP_MIN_NET / 9.807)
    rated = rate["rating"]
    shaft = max(
        power(rated, rated_head, T.PUMP_EFFICIENCY),
        power(rated * T.OVERLOAD_FLOW, rated_head * T.OVERLOAD_HEAD, T.PUMP_EFFICIENCY),
    )
    kw = motor(shaft)
    jockey_flow = max(4.0, round(rated * T.JOCKEY_SHARE, 1))
    jockey_head = rated_head * 1.4 + T.JOCKEY_ABOVE / 9.807  # above the main pump's churn
    jockey_kw = motor(power(jockey_flow, jockey_head, T.JOCKEY_EFFICIENCY))
    out = []
    for duty, q, h, p in (
        ("main", rated, rated_head, kw),
        ("standby", rated, rated_head, kw),
        ("jockey", jockey_flow, jockey_head, jockey_kw),
    ):
        out.append({
            "duty": duty, "flow": q, "head": math.ceil(h * 10 - 1e-9) / 10, "power": p, "count": rate["count"]
            if duty != "jockey" else 1, **typical_set(duty, p, standby),
        })  # fmt: skip
    return out


def pump_room(sets: list[dict[str, Any]]) -> dict[str, Any]:
    """The pump room the sets need [mm, m²]: side by side with the clear space round each and
    a strip for the controllers (SAEngine practice; BNBC asks a readily accessible room of
    non-combustible construction, Sec 4.2.2.5)."""
    if not sets:
        return {"length": 0.0, "width": 0.0, "area": 0.0}
    c = T.PUMP_CLEARANCE * 1000.0
    length = sum(s["width"] * s.get("count", 1) for s in sets) + c * (
        sum(s.get("count", 1) for s in sets) + 1
    )
    width = max(s["length"] for s in sets) + 2 * c + T.CONTROLLER_STRIP * 1000.0
    return {
        "length": round(length, -1),
        "width": round(width, -1),
        "area": round(length * width / 1e6, 1),
        "note": (
            f"sets side by side, {T.PUMP_CLEARANCE:g} m clear round each and a "
            f"{T.CONTROLLER_STRIP:g} m strip for the controllers (SAEngine practice); a readily "
            f"accessible room of non-combustible construction ({T.PAGES['4.2.2.5']})"
        ),
    }


def water_filled(nominal: float, material: str = "steel") -> float:
    """Weight of a metre of water-filled pipe [kg/m] (steel masses, MEMORY)."""
    from saengine.fire.network import bore

    steel = (
        T.STEEL_MASS.get(int(nominal))
        or T.STEEL_MASS[min(T.STEEL_MASS, key=lambda s: abs(s - nominal))]
    )
    d = bore(nominal, material) / 1000.0
    return steel + 1000.0 * math.pi * d * d / 4.0


def support_loads(sizes: dict[float, str], story_height: float) -> list[dict[str, Any]]:
    """The design load of a riser support and of a hanger [kN] for each pipe size used:
    supports (Sec 4.2.3.13) carry the riser between them (supports at the top, the foot and
    every other floor: two storeys) + 110 kg; hangers (Sec 4.2.3.14, 4.2.10.6) five times the
    water-filled pipe of their 5 m + 110 kg."""
    rows = []
    for nominal, role in sorted(sizes.items()):
        w = water_filled(nominal)
        if role == "riser":
            span = 2 * story_height
            load = (w * span + T.SUPPORT_EXTRA) * G / 1000.0
            basis = (
                f"{w:.1f} kg/m water-filled x {span:.1f} m (supports every other floor) + "
                f"{T.SUPPORT_EXTRA:g} kg ({T.PAGES['4.2.3.13']})"
            )
        else:
            span = T.HANGER_SPACING
            load = (T.HANGER_FACTOR * w * span + T.SUPPORT_EXTRA) * G / 1000.0
            basis = (
                f"{T.HANGER_FACTOR:g} x {w:.1f} kg/m x {span:g} m + {T.SUPPORT_EXTRA:g} kg "
                f"({T.PAGES['4.2.3.14']}; {T.PAGES['4.2.10.6']})"
            )
        rows.append({"size": nominal, "kind": "support" if role == "riser" else "hanger",
                     "spacing": round(span, 2), "load": round(load, 2), "basis": basis})  # fmt: skip
    return rows


def test_pressures(working: float, sprinklers: bool, hydrant: bool) -> list[dict[str, Any]]:
    """Sec 4.2.12.2 hydrostatic test pressures [kPa] for ``working`` [kPa]."""
    rows = []
    if hydrant:
        rows.append({
            "system": "standpipe", "pressure": round(max(T.TEST_STANDPIPE, 1.5 * working)),
            "note": f"1400 kPa or 150 % of the working pressure, 2 hours ({T.PAGES['4.2.12.2']})",
        })  # fmt: skip
    if sprinklers:
        p = working + 350.0 if working > 650.0 else T.TEST_SPRINKLER
        rows.append({
            "system": "sprinkler", "pressure": round(p),
            "note": f"1000 kPa, or 350 kPa above a working pressure over 650 kPa, 2 hours "
                    f"({T.PAGES['4.2.12.2']})",
        })  # fmt: skip
    return rows
