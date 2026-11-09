"""The precast piece schedule (alpha 9 L1): per piece mark the count, size, concrete, weight,
bars, inserts and mould area, for the bill of quantities and the shop drawings.

The marks are those of :func:`saengine.design.precast.pieces_of`; the concrete and weight by
its section (:func:`saengine.design.precast.piece_section`: hollow-core cores and double-tee
voids deducted). Bars: the longitudinal bars of beams and columns over the piece's length
and their links by :func:`saengine.boq.quantities.transverse_length` (rectangular profiles);
the mesh of floor units and wall panels is measured with the slabs and walls of the bill and
not repeated. The mould area is the piece's surfaces less the top face cast against the air
(the perimeter less the width, times the length, plus both ends).

Note: the bill's slab items measure a precast floor type as a slab of its thickness; this
schedule gives the net concrete of its units.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["piece_schedule"]

HEADERS = [
    "Mark",
    "Type",
    "Element",
    "Count",
    "Length (mm)",
    "Width (mm)",
    "Concrete (m³ each)",
    "Weight (kN each)",
    "Bars (kg each)",
    "Inserts each",
    "Mould (m² each)",
    "Concrete (m³ all)",
]


def _bars(obj: Any, length: float) -> float | None:
    """Mass of the bars of a beam or column piece [kg]; None when not measured here."""
    from saengine.boq.quantities import bar_length, bar_mass, transverse_length

    reinforcement = getattr(obj, "reinforcement", None)
    if obj.kind not in ("beam", "column") or reinforcement is None:
        return None
    if not hasattr(reinforcement, "longitudinal"):
        return None
    mass = sum(
        g.count * bar_mass(g.dia) * bar_length(length, g.dia) / 1e3
        for g in reinforcement.longitudinal
    )
    links = getattr(reinforcement, "transverse", None)
    profile = getattr(obj, "profile", None)
    if links is not None and getattr(profile, "shape", "") == "rectangle":
        from shapely.geometry import box

        section = box(0, 0, float(profile.xDim), float(profile.yDim))
        run = transverse_length(section, float(reinforcement.cover), links, length)
        mass += bar_mass(links.dia) * run / 1e3
    return mass


def piece_schedule(pieces: list[Any], types: dict[str, Any], materials: Any) -> dict[str, Any]:
    """``{"headers", "rows" (strings), "items" (numbers per mark), "totals": {"count",
    "concrete", "weight", "bars"}}`` of the marks ``pieces``."""
    from saengine.design.precast import _density, piece_section, self_weight

    rows: list[list[str]] = []
    items: list[dict[str, Any]] = []
    totals = {"count": 0, "concrete": 0.0, "weight": 0.0, "bars": 0.0}
    for piece in pieces:
        obj = types[piece.type]
        material = materials.get(obj.material) if materials is not None else None
        width = piece.height if piece.element == "wallPanel" else (piece.width or None)
        try:
            section = piece_section(obj, obj.precast, width)
        except ValueError:
            continue
        run = float(piece.length)
        volume = (section.area + section.weight_area) * run * 1e-9
        weight = self_weight(section, _density(material)) * run / 1e3
        bars = _bars(obj, run)
        inserts = len(obj.precast.inserts)
        perimeter = 2 * (section.b + section.h)
        mould = ((perimeter - section.b) * run + 2 * section.area) * 1e-6
        items.append(
            {
                "mark": piece.mark,
                "type": piece.type,
                "element": piece.element,
                "count": piece.count,
                "length": run,
                "width": section.b,
                "concrete": volume,
                "weight": weight,
                "bars": bars,
                "inserts": inserts,
                "mould": mould,
            }
        )
        rows.append(
            [
                piece.mark,
                piece.type,
                piece.element,
                str(piece.count),
                f"{run:.0f}",
                f"{section.b:.0f}",
                f"{volume:.3f}",
                f"{weight:.1f}",
                "–" if bars is None else f"{bars:.1f}",
                str(inserts),
                f"{mould:.2f}",
                f"{volume * piece.count:.2f}",
            ]
        )
        totals["count"] += piece.count
        totals["concrete"] += volume * piece.count
        totals["weight"] += weight * piece.count
        totals["bars"] += (bars or 0.0) * piece.count
    totals = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in totals.items()}
    if not math.isfinite(totals["concrete"]):
        totals["concrete"] = 0.0
    return {"headers": HEADERS, "rows": rows, "items": items, "totals": totals}
