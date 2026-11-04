"""Accidental torsional effects by the factor δ on each element's earthquake effects (method
``deltaFactor`` of the pack's ``seismic.torsionalEffects``; alpha 9 C5c, EN 1998-1 4.3.3.2.4
type).

Where the analysis carries no accidental eccentricity (no eccentric static cases EXP/EXN,
EYP/EYN and no accidental torsion parts of the response spectrum design), each column, beam and
wall takes its earthquake effects × δ = 1 + c x / Le, x its distance from the centre of mass in
plan across the earthquake's direction and Le the plan's extent across it (the building's
columns and walls; the centre of mass taken at the plan's centre, SAEngine practice). The
design forms, per value of δ (the larger of the two directions', rounded up to the pack's step),
the earthquake combinations × δ for its members only, as the soft storeys' factors are formed
(:func:`saengine.fem.irregularity.soft_storey_combinations`).
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context

#: The combination name prefix of a δ group.
PREFIX = "δ ×{:g}: "


def rules() -> Any | None:
    found = getattr(code_context.table("seismic"), "torsionalEffects", None)
    return found if found is not None and found.method == "deltaFactor" else None


def prefix(factor: float) -> str:
    return PREFIX.format(factor)


def _position(e: Any) -> tuple[float, float] | None:
    kind = getattr(e, "kind", "")
    if kind == "column":
        return float(e.position[0]), float(e.position[1])
    if kind in ("beam", "wall"):
        return (
            (float(e.start[0]) + float(e.end[0])) / 2,
            (float(e.start[1]) + float(e.end[1])) / 2,
        )
    return None


def delta_groups(building: Any, present: set[str] | frozenset[str]) -> list[dict[str, Any]]:
    """``[{"factor", "prefix", "members": {ids}, "walls": {ids}}]`` of the building's elements
    by δ (see the module notes); [] when the pack has no rule or the model has eccentric
    static cases."""
    r = rules()
    if r is None or building is None or {"EXP", "EXN", "EYP", "EYN"} & set(present):
        return []
    points = []
    for e in getattr(building, "elements", []):
        if getattr(e, "kind", "") in ("column", "wall"):
            p = _position(e)
            if p is not None:
                points.append(p)
                if getattr(e, "kind", "") == "wall":
                    points += [
                        (float(e.start[0]), float(e.start[1])),
                        (float(e.end[0]), float(e.end[1])),
                    ]
    if len(points) < 2:
        return []
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    lx, ly = max(xs) - min(xs), max(ys) - min(ys)
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    groups: dict[float, dict[str, Any]] = {}
    for e in getattr(building, "elements", []):
        kind = getattr(e, "kind", "")
        if kind not in ("column", "beam", "wall"):
            continue
        p = _position(e)
        if p is None:
            continue
        dx = 1 + r.coefficient * abs(p[1] - cy) / ly if ly > 0 else 1.0  # EX: x across is y
        dy = 1 + r.coefficient * abs(p[0] - cx) / lx if lx > 0 else 1.0
        delta = math.ceil(max(dx, dy) / r.step - 1e-9) * r.step
        delta = round(delta, 4)
        if delta <= 1.0:
            continue
        group = groups.setdefault(delta, {"factor": delta, "prefix": prefix(delta),
                                          "members": set(), "walls": set()})  # fmt: skip
        group["walls" if kind == "wall" else "members"].add(e.id)
    return [groups[k] for k in sorted(groups)]


def note(groups: list[dict[str, Any]]) -> str:
    """The design's note of the δ groups."""
    r = rules()
    clause = code_context.cite("seismic", "amplification")
    return (
        f"accidental torsion by δ = 1 + {r.coefficient:g} x/Le on the earthquake effects of each "
        "element (no eccentric cases in the analysis; the centre of mass at the plan's centre): "
        + ", ".join(
            f"δ {g['factor']:g} on {len(g['members']) + len(g['walls'])} elements" for g in groups
        )
        + (f" ({clause})" if clause else "")
    )
