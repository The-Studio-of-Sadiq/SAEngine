"""Miscellaneous loads of the code pack's ``flood`` table: rain on roofs (case R), helicopter
landing areas, internal gas explosions and air raid shelters.

- **Rain** (:func:`rain_load`): with the primary drains blocked, all the rainwater up to the
  inlet of the secondary drainage (or the top of the parapet), γw × depth, plus the pack's
  allowance with controlled drainage. Case R on the roof slabs; the combinations take it in
  place of the roof live load ("Lr or R", the pack's ``alternates``). The steel ponding check
  (:mod:`saengine.design.steel.ponding`) takes the same R for its stress under D + R.
- **Helicopter landing areas** (:func:`helipad_loads`): L1 = W1 on the contact areas, L2 =
  k W2 on a square patch, L3 = w distributed; the most unfavourable. L3 is applied as the live
  load of the landing area's slabs; L1 and L2 are reported for the slab's local design.
- **Gas explosions** (:func:`explosion_pressure`): the overpressure q0 by A0/v (the pack's
  digitised curve), at least the least design pressure; a static action on all the room's
  walls and floors.
- **Air raid shelters** (:func:`shelter_load`): the characteristic vertical load by the
  storeys above, raised by the excess of their mean live load over the threshold.

Units: kN, kN/m², m (the helipad patch in mm, as the pack gives it).
"""

from __future__ import annotations

from typing import Any

from saengine.fem.flood import FloodNotCovered, _interp, table


def rain_load(rain: Any, data: Any | None = None) -> float | None:
    """R [kN/m²] of Project Settings → Site → Rain (``depth`` [mm] to the secondary drains,
    ``controlledDrainage``); None without a depth or without the pack's rain rule."""
    if rain is None or getattr(rain, "depth", None) is None:
        return None
    try:
        rule = (data or table()).rain
    except FloodNotCovered:
        return None
    if rule is None:
        return None
    load = float(rule.unitWeight) * float(rain.depth) / 1000.0
    if getattr(rain, "controlledDrainage", False):
        load += float(rule.controlledAllowance)
    return load


def project_rain_load(settings: Any) -> float | None:
    """The project's rain load R [kN/m²] (for the ponding check's D + R), None without one."""
    return rain_load(getattr(getattr(settings, "site", None), "rain", None))


def helipad_loads(helipad: Any, data: Any | None = None) -> dict[str, Any] | None:
    """{"L1_kN", "L2_kN", "L2_kPa" (on the patch), "L3_kPa", "k", "patch_mm"} of a helicopter
    landing area, None without one or without the pack's rule."""
    if helipad is None:
        return None
    rule = (data or table()).helipad
    if rule is None:
        return None
    k = float(rule.impact[helipad.gear])
    patch = float(rule.patch) / 1000.0
    l2 = k * float(helipad.loadedWeight)
    return {
        "L1_kN": float(helipad.weight),
        "L2_kN": l2,
        "L2_kPa": l2 / patch**2,
        "L3_kPa": float(rule.distributed),
        "k": k,
        "patch_mm": float(rule.patch),
    }


def explosion_pressure(vent_area: float, volume: float, data: Any | None = None) -> dict[str, Any]:
    """{"ratio", "q0_kPa", "design_kPa", "notes"} of a room: q0 from the pack's curve at A0/v,
    at least the pack's least design pressure."""
    rule = (data or table()).explosion
    ratio = float(vent_area) / float(volume)
    q0 = _interp(rule.ventCurve, ratio)
    notes = []
    first, last = float(rule.ventCurve[0][0]), float(rule.ventCurve[-1][0])
    if ratio > last:
        notes.append(f"A0/v = {ratio:.3f} 1/m is beyond the figure (to {last:.3f}); q0 held")
    elif ratio < first:
        notes.append(f"A0/v = {ratio:.3f} 1/m is below the figure's first point; q0 held")
    return {
        "ratio": ratio,
        "q0_kPa": q0,
        "design_kPa": max(q0, float(rule.minPressure)),
        "rise_s": list(rule.rise),
        "decay_s": list(rule.decay),
        "notes": notes,
    }


def shelter_load(
    storeys: int, stable: bool, mean_live: float | None = None, data: Any | None = None
) -> dict[str, Any]:
    """{"base_kPa", "extra_kPa", "load_kPa"}: the characteristic vertical load on an air raid
    shelter with ``storeys`` usable storeys above, of particularly stable construction or not,
    raised by the mean live load above over the pack's threshold."""
    rule = (data or table()).shelter
    if stable:
        base = float(rule.stable)
    else:
        base = next(
            float(r.load) for r in rule.rows if r.maxStoreys is None or storeys <= r.maxStoreys
        )
    extra = max(0.0, float(mean_live or 0.0) - float(rule.liveThreshold))
    return {"base_kPa": base, "extra_kPa": extra, "load_kPa": base + extra}


__all__ = [
    "explosion_pressure",
    "helipad_loads",
    "project_rain_load",
    "rain_load",
    "shelter_load",
]
