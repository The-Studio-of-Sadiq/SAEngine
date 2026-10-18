"""The supply: substation and transformers, the standby generator and its fuel, the UPS
(BNBC 2020 Part 8 Sec 1.3.18-1.3.20), and their typical sizes and weights for the structure.

- Substation: required when the load is 50 kW or more (Sec 1.3.18.1, 1.3.20.1(e)): an 11 kV
  supply, an HT panel, the transformer(s) and the LT panel. The transformers' total rating is
  the maximum demand in kVA (:mod:`saengine.electrical.demand`), in standard sizes; one unit
  up to 1600 kVA, else the load shared between units (SAEngine practice).
- Generator: Sec 1.3.19.2 sizes the standby set on the essential lighting, air conditioning,
  equipment, services, lifts and water pumps. SAEngine takes the essential motors (lifts and
  pumps unless marked otherwise), a share of the lighting and power load (0.25, SAEngine
  practice) and any other essential load entered; the set's kVA at 0.8 power factor. Lifts need
  standby power above ten storeys or 32 m and in hospitals (Sec 4.2.1.3).
- Fuel: BNBC gives no running time. The tank holds the set's full-load consumption (0.27 l/kWh,
  typical) for 8 hours (SAEngine practice), editable.
- UPS: the load entered at 0.9 power factor, its batteries for the autonomy (15 minutes).

The dimensions and weights are typical catalogue values (:mod:`saengine.electrical.tables`),
labelled so: replace them with the selected unit's data.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.electrical import tables as T


def substation_required(connected_kw: float) -> bool:
    """Sec 1.3.18.1 / 1.3.20.1(e): an 11 kV substation for loads of 50 kW and above."""
    return connected_kw >= T.SUBSTATION_KW - 1e-9


def transformers(kva: float, count: int | None = None) -> dict[str, Any]:
    """The transformers for a maximum demand of ``kva``: ``{count, rating, total, required,
    utilisation, tableArea, substationArea, note}``."""
    if kva <= 0:
        return {"count": 0, "rating": None, "total": 0.0, "required": 0.0, "utilisation": 0.0,
                "transformerArea": None, "substationArea": None, "note": "no load"}  # fmt: skip
    n = count or max(1, math.ceil(kva / T.TRANSFORMER_MAX - 1e-9))
    rating = T.next_size(kva / n, T.TRANSFORMER_SIZES)
    note = ""
    if rating is None:
        rating = float(T.TRANSFORMER_SIZES[-1])
        note = f"{kva / n:.0f} kVA a unit exceeds the largest standard size: add transformers"
    total = n * rating
    row = substation_area(n, rating)
    return {
        "count": n,
        "rating": rating,
        "total": total,
        "required": kva,
        "utilisation": kva / total,
        "transformerArea": row[0] if row else None,
        "substationArea": row[1] if row else None,
        "areaRow": row[2] if row else None,
        "note": note,
    }


def substation_area(count: int, rating: float) -> tuple[float, float, str] | None:
    """Table 8.1.23's transformer and total substation areas [m²] for ``count`` transformers of
    ``rating`` kVA: the row of that number with the next capacity up (None when the table has
    no such row)."""
    rows = sorted((kva, a) for (n, kva), a in T.SUBSTATION_AREAS.items() if n == count)
    for kva, (transformer, total) in rows:
        if kva >= rating - 1e-9:
            return float(transformer), float(total), f"{count} x {kva}"
    return None


def generator_area(kw: float) -> tuple[float, str] | None:
    """Table 8.1.24's room area [m²] for one set of ``kw`` (the next row up; None above 500)."""
    for capacity in sorted(T.GENERATOR_AREAS):
        if capacity >= kw - 1e-9:
            return float(T.GENERATOR_AREAS[capacity]), f"1 x {capacity} kW"
    return None


def essential_load(electrical: Any, demand: dict[str, Any]) -> dict[str, Any]:
    """The load on the standby generator [kW] and its parts."""
    supply = electrical.supply
    share = T.ESSENTIAL_SHARE if supply.essentialShare is None else supply.essentialShare
    motors = [m for m in demand["motors"] if m["essential"]]
    lighting = demand["storiesKw"] * share
    motors_kw = sum(m["kw"] for m in motors)
    total = motors_kw + lighting + supply.essentialLoad
    parts = [f"{m['id']} {m['kw']:g} kW" for m in motors]
    parts.append(
        f"{share:g} x {demand['storiesKw']:.1f} kW lighting and power"
        + ("" if supply.essentialShare is not None else " (SAEngine practice)")
    )
    if supply.essentialLoad:
        parts.append(f"other essential {supply.essentialLoad:g} kW")
    return {"kw": total, "motorsKw": motors_kw, "lightingKw": lighting, "share": share,
            "parts": parts}  # fmt: skip


def lift_standby_required(storeys: int, height_m: float, hospital: bool) -> bool:
    """Sec 4.2.1.3(a): standby power for one or more lifts above ten storeys or 32 m, and in
    hospitals and health care buildings."""
    return storeys > T.LIFT_STANDBY_STOREYS or height_m > T.LIFT_STANDBY_HEIGHT or hospital


def generator(essential_kw: float, hours: float | None = None) -> dict[str, Any]:
    """The standby set for ``essential_kw``: ``{kva, kw, required, fuel (l), fuelHours,
    tank: {volume m³, weight kN}}``."""
    if essential_kw <= 0:
        return {"kva": None, "kw": 0.0, "required": 0.0, "fuel": 0.0, "note": "no essential load"}
    need = essential_kw / T.GENERATOR_PF
    kva = T.next_size(need, T.GENERATOR_SIZES)
    note = ""
    if kva is None:
        kva = float(T.GENERATOR_SIZES[-1])
        note = f"{need:.0f} kVA exceeds the largest set listed: share it between sets"
    kw = kva * T.GENERATOR_PF
    hours = hours or T.FUEL_HOURS
    fuel = kw * hours * T.FUEL_RATE
    return {
        "kva": kva,
        "kw": kw,
        "required": need,
        "utilisation": need / kva,
        "fuelHours": hours,
        "fuelRate": T.FUEL_RATE,
        "fuel": fuel,
        "tank": fuel_tank(fuel),
        "note": note,
    }


def fuel_tank(litres: float) -> dict[str, Any]:
    """A rectangular steel day tank for ``litres`` of diesel with 10 % ullage: its size, the
    fuel's and the steel's weight [kN] (typical)."""
    volume = litres / 1000.0 * 1.1
    height = 1000.0 if volume <= 2.0 else 1500.0
    side = math.ceil(math.sqrt(volume * 1e9 / height) / 50.0) * 50.0
    surface = 2 * (side * side) + 4 * side * height
    steel = surface / 1e6 * T.TANK_PLATE / 1000.0 * T.STEEL_WEIGHT
    fuel = litres / 1000.0 * T.DIESEL_DENSITY * T.G / 1000.0
    return {
        "volume": volume,
        "length": side,
        "width": side,
        "height": height,
        "fuelWeight": fuel,
        "emptyWeight": steel,
        "operatingWeight": fuel + steel,
    }


def ups(load_kw: float | None, autonomy_min: float | None = None) -> dict[str, Any] | None:
    """The UPS for ``load_kw`` at 0.9 power factor and its battery (typical masses)."""
    if not load_kw:
        return None
    autonomy = autonomy_min or T.UPS_AUTONOMY_MIN
    kva = math.ceil(load_kw / 0.9 / 10.0) * 10.0
    kwh = load_kw * autonomy / 60.0 / 0.9  # battery to inverter efficiency 0.9 (typical)
    return {
        "kva": kva,
        "load": load_kw,
        "autonomy": autonomy,
        "energy": kwh,
        "upsWeight": kva * T.UPS_KG_PER_KVA * T.G / 1000.0,
        "batteryWeight": kwh * T.BATTERY_KG_PER_KWH * T.G / 1000.0,
    }


def capacitor_kvar(kw: float, pf: float, target: float = T.TARGET_PF) -> float:
    """Reactive power to raise ``pf`` to ``target`` for ``kw``."""
    if pf >= target:
        return 0.0
    return kw * (math.tan(math.acos(pf)) - math.tan(math.acos(target)))


# ─────────────────────────────── typical units ───────────────────────────────


def _row(table: dict[Any, tuple], rating: float) -> tuple:
    key = min((k for k in table if k >= rating - 1e-9), default=max(table))
    return table[key]


def typical_transformer(kva: float, kind: str = "oil") -> dict[str, Any]:
    length, width, height, mass, oil = _row(T.TRANSFORMER_OIL, kva)
    if kind == "dry":
        mass, oil = mass * T.DRY_MASS, 0.0
    operating = round(mass * T.G / 1000.0, 1)
    out = {"length": float(length), "width": float(width), "height": float(height),
           "operatingWeight": operating, "oil": float(oil)}  # fmt: skip
    empty = empty_of_oil(operating, float(oil))
    if empty is not None:
        out["emptyWeight"] = empty
    return out


def oil_weight(litres: float) -> float:
    """Weight of ``litres`` of transformer oil [kN]."""
    return litres / 1000.0 * T.TRANSFORMER_OIL_DENSITY * T.G / 1000.0


def empty_of_oil(operating: float, litres: float) -> float | None:
    """A transformer's weight without its oil [kN] (None without oil or a positive rest)."""
    if not litres or litres <= 0:
        return None
    empty = round(operating - oil_weight(litres), 1)
    return empty if 0 < empty < operating else None


def typical_generator(kva: float) -> dict[str, Any]:
    length, width, height, mass = _row(T.GENERATOR_SETS, kva)
    return {"length": float(length), "width": float(width), "height": float(height),
            "operatingWeight": round(mass * T.G / 1000.0, 1)}  # fmt: skip


def typical_lt_panel(amps: float) -> dict[str, Any]:
    """An LT switchboard: an incomer, a bus coupler or metering section and outgoing sections
    by the current (typical)."""
    p = T.LT_PANEL
    sections = 2 + max(1, math.ceil(amps / p["ampsPerSection"]))
    length = sections * p["section"]
    return {"length": length, "width": p["depth"], "height": p["height"],
            "operatingWeight": round(length / 1000.0 * p["massPerM"] * T.G / 1000.0, 1)}  # fmt: skip


def typical_ht_panel(panels: int = 3) -> dict[str, Any]:
    """HT switchgear: incoming, metering and outgoing panels in a row (typical)."""
    width, depth, height, mass = T.HT_PANEL
    return {"length": width * panels, "width": depth, "height": height,
            "operatingWeight": round(panels * mass * T.G / 1000.0, 1)}  # fmt: skip


def typical_capacitor(kvar: float) -> dict[str, Any]:
    width, depth, height, mass, per = T.CAPACITOR_PANEL
    n = max(1, math.ceil(kvar / per))
    return {"length": width * n, "width": depth, "height": height,
            "operatingWeight": round(n * mass * T.G / 1000.0, 1)}  # fmt: skip
