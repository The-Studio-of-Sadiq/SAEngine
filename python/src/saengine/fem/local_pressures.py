"""Local wind pressures on cladding and fixings by area-dependent external pressure
coefficients (method ``areaDependent`` of the pack's ``wind.localPressures``; alpha 9 C5c).

The method of EN 1991-1-4 7.2 (the pack names the clauses):

- cpe of a loaded area A: cpe,1 for A <= ``areaSmall`` (1 m²), cpe,10 for A >= ``areaLarge``
  (10 m²), cpe,1 - (cpe,1 - cpe,10) log10 A between (Figure 7.2);
- walls: zones A, B, C (sides) and D, E (windward, leeward) by h/d (Table 7.1, linear between the
  rows); flat roofs: zones F, G, H, I by the parapet's hp/h (Table 7.2, sharp eaves hp = 0);
- the edge zones from e = min(b, 2h); the pressures at qp(h), the largest (ze = h on the
  roof and the upper part of the walls);
- the net pressure w = qp (cpe - cpi), cpi the more onerous of the pack's (+0.2, -0.3) where
  the openings are not known.

The result has the shape of :func:`saengine.fem.loads.cladding_pressures` (zones with the
positive and negative pressures) so the derivation and the report show it the same way.
Units: m, m², kN/m².
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from saengine.codes import context as code_context


def rules() -> Any | None:
    table = code_context.table("wind")
    found = getattr(table, "localPressures", None)
    return found if found is not None and found.method == "areaDependent" else None


def area_coefficient(cpe1: float, cpe10: float, area: float | None, rule: Any) -> float:
    """cpe of a loaded area ``area`` [m²] (None: the smallest, cpe,1)."""
    if area is None or area <= rule.areaSmall:
        return cpe1
    if area >= rule.areaLarge:
        return cpe10
    t = math.log10(area / rule.areaSmall) / math.log10(rule.areaLarge / rule.areaSmall)
    return cpe1 + (cpe10 - cpe1) * t


def _along(rows: list[Any], ratio: float, area: float | None, rule: Any) -> float:
    rows = sorted(rows, key=lambda r: r.ratio)
    values = [(r.ratio, area_coefficient(r.cpe1, r.cpe10, area, rule)) for r in rows]
    if ratio <= values[0][0]:
        return values[0][1]
    for (r0, c0), (r1, c1) in itertools.pairwise(values):
        if ratio <= r1:
            return c0 + (c1 - c0) * (ratio - r0) / (r1 - r0)
    return values[-1][1]


def local_pressures(
    height: float,
    width: float,
    depth: float,
    speed: float,
    exposure: str,
    importance: float,
    *,
    area: float | None = None,
    parapet: float | None = None,
) -> dict[str, Any] | None:
    """The local pressures by zone of a building ``height`` h tall, ``width`` b across the wind
    and ``depth`` d along it (the plan's least and largest dimensions give the worst), for the
    loaded area ``area`` [m²] and a parapet ``parapet`` hp [m] high; None without the pack's
    table."""
    from saengine.fem.peak_velocity_pressure import peak_velocity_pressure

    rule = rules()
    if rule is None or height <= 0:
        return None
    qp = peak_velocity_pressure(height, speed, exposure, importance)
    ratio_wall = height / depth if depth > 0 else 1.0
    ratio_roof = (parapet or 0.0) / height
    cpi_pos, cpi_neg = rule.internal
    e = min(width, rule.edgeFactor * height)
    groups: dict[tuple[str, str], dict[str, list[Any]]] = {}
    labels: dict[tuple[str, str], str] = {}
    for z in rule.zones:
        key = (z.surface, z.zone)
        labels.setdefault(key, z.label)
        sign = "positive" if z.cpe10 > 0 or (z.cpe10 == 0 and z.cpe1 > 0) else "negative"
        groups.setdefault(key, {}).setdefault(sign, []).append(z)
    zones = []
    for key, by_sign in groups.items():
        surface, zone = key
        ratio = ratio_wall if surface == "wall" else ratio_roof
        pos = _along(by_sign["positive"], ratio, area, rule) if "positive" in by_sign else None
        neg = _along(by_sign["negative"], ratio, area, rule) if "negative" in by_sign else None
        zones.append(
            {
                "surface": surface,
                "zone": zone,
                "label": labels[key],
                "GCpPos": pos,
                "GCpNeg": neg,
                "pPos_kPa": None if pos is None else qp * (pos - cpi_neg),
                "pNeg_kPa": None if neg is None else qp * (neg - cpi_pos),
            }
        )
    source = code_context.cite("wind", "localPressures")
    return {
        "h_m": height,
        "qh_kPa": qp,
        "lowRise": False,
        "a_m": e / 10,
        "e_m": e,
        "area_m2": area,
        "enclosure": "enclosed",
        "GCpi": max(abs(cpi_pos), abs(cpi_neg)),
        "Ri": 1.0,
        "roofForm": "flat",
        "theta_deg": 0.0,
        "figure": source,
        "zones": zones,
        "parapet": None,
        "notes": [
            (
                f"cpe by the loaded area (cpe,1 at {rule.areaSmall:g} m², cpe,10 at "
                f"{rule.areaLarge:g} m²), walls at h/d = {ratio_wall:.2f}, the roof at hp/h = "
                f"{ratio_roof:.3f}; e = min(b, {rule.edgeFactor:g} h) = {e:.2f} m; cpi "
                f"{cpi_pos:+g} / {cpi_neg:+g}, the more onerous"
            )
        ],
        "formula": "w = qp(ze) (cpe - cpi), cpe by the loaded area",
    }
