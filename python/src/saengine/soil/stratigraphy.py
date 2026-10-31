"""3D stratigraphy of the site from the boreholes, and fence diagrams through them.

The layers of each borehole are grouped into strata: neighbouring layers of the same kind (soil
type, or the USCS group with ``correlateBy: "uscs"``) are one stratum. The strata of all boreholes
are correlated into one sequence of *units* from the top down by aligning each borehole's sequence
with the others (longest common subsequence, starting from the borehole with the most strata): a
unit a borehole passes through without meeting it is pinched out there (zero thickness); a unit
below a borehole's termination depth is unknown there.

The boundaries between units are surfaces: the ground, the top of each unit below the first, and
the bottom of the last. Each surface is interpolated over the site by inverse distance weighting
(power 2) of the boreholes that know it, on a grid over the boreholes' extent, and the surfaces are
kept in order from the top down (a lower one is never above a higher one). The water table is
interpolated the same way from the boreholes that met it.

A fence diagram is a vertical section along a polyline through boreholes (the stratigraphy's
fences, else one through all boreholes in the order of their position along the site's main
axis), sampled at stations along it with the same interpolation, so it passes exactly through the
logs of its boreholes.

This is a geometric model of the logs for the engineer to judge, not a design value; it does not
depend on a design code.

Units: the soil report's mm in, m out (plan coordinates in the project grid, elevations on the
project datum).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any

from saengine.library.soil import Borehole, SoilReport

#: Inverse distance weighting power.
POWER = 2.0
#: Grid cells along the longer side of the site's extent.
GRID_CELLS = 24
#: The grid reaches this far beyond the outer boreholes (at least) [m].
MARGIN = 5.0
#: Stations along a fence (at least; more for long fences, one per metre at most).
FENCE_STATIONS = 60
#: Thinner than this, a unit is pinched out [m].
THIN = 1e-3


@dataclass
class Stratum:
    key: str
    soil_type: str
    top: float  # elevation [m]
    bottom: float  # elevation [m]


def _key(layer: Any, by: str) -> str:
    if by == "uscs" and layer.uscs:
        return layer.uscs.strip().upper()
    return str(layer.soilType)


def strata(report: SoilReport, borehole: Borehole, by: str = "soilType") -> list[Stratum]:
    """The borehole's layers merged into strata of one kind, as elevations [m]."""
    ground = report.ground_level(borehole) / 1e3
    result: list[Stratum] = []
    for layer in sorted(borehole.layers, key=lambda layer: layer.top):
        key = _key(layer, by)
        top, bottom = ground - layer.top / 1e3, ground - layer.bottom / 1e3
        if result and result[-1].key == key and abs(result[-1].bottom - top) < 1e-6:
            result[-1].bottom = bottom
        else:
            result.append(Stratum(key, str(layer.soilType), top, bottom))
    return result


def _lcs(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    """Index pairs of a longest common subsequence of ``a`` and ``b``."""
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            table[i][j] = (
                table[i + 1][j + 1] + 1 if a[i] == b[j] else max(table[i + 1][j], table[i][j + 1])
            )
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if a[i] == b[j]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif table[i + 1][j] >= table[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def correlate(sequences: list[list[str]]) -> tuple[list[str], list[list[int]]]:
    """One sequence of units for all ``sequences`` (each a borehole's strata from the top), and
    for each borehole the unit index of each of its strata."""
    order = sorted(range(len(sequences)), key=lambda k: -len(sequences[k]))
    master: list[str] = []
    for k in order:
        seq = sequences[k]
        pairs = _lcs(master, seq)
        merged: list[str] = []
        i = j = 0
        for mi, sj in [*pairs, (len(master), len(seq))]:
            merged += master[i:mi]  # master's units before the match
            merged += seq[j:sj]  # the borehole's unmatched strata before it
            if mi < len(master):
                merged.append(master[mi])
            i, j = mi + 1, sj + 1
        master = merged
    assignments = []
    for seq in sequences:
        pairs = _lcs(master, seq)
        units = [0] * len(seq)
        for mi, sj in pairs:
            units[sj] = mi
        assignments.append(units)
    return master, assignments


def idw(points: list[tuple[float, float, float]], x: float, y: float) -> float | None:
    """The inverse distance weighted value at (x, y) of ``points`` (x, y, value)."""
    if not points:
        return None
    total = weights = 0.0
    for px, py, value in points:
        d2 = (px - x) ** 2 + (py - y) ** 2
        if d2 < 1e-12:
            return value
        w = 1.0 / d2 ** (POWER / 2)
        total += w * value
        weights += w
    return total / weights


def _ordered(values: list[float | None]) -> list[float | None]:
    """The surfaces at a point kept in order from the top down."""
    result: list[float | None] = []
    last = math.inf
    for v in values:
        if v is None:
            result.append(None)
            continue
        v = min(v, last)
        result.append(v)
        last = v
    return result


def _main_axis_order(points: list[tuple[float, float]]) -> list[int]:
    """Indices of ``points`` ordered along their principal direction."""
    n = len(points)
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    sxx = sum((p[0] - cx) ** 2 for p in points)
    syy = sum((p[1] - cy) ** 2 for p in points)
    sxy = sum((p[0] - cx) * (p[1] - cy) for p in points)
    angle = 0.5 * math.atan2(2 * sxy, sxx - syy)
    ux, uy = math.cos(angle), math.sin(angle)
    return sorted(range(n), key=lambda i: (points[i][0] - cx) * ux + (points[i][1] - cy) * uy)


def build(report: SoilReport) -> dict[str, Any]:
    """The stratigraphy of the soil report, ready for JSON: ``{"correlateBy", "units": [{"id",
    "key", "soilType"}], "boreholes": [{"id", "x", "y", "ground", "bottom", "water", "strata":
    [{"unit", "top", "bottom"}], "surfaces": [elevation or None per surface]}], "grid": {"x",
    "y", "surfaces": [surface][iy][ix], "water": [iy][ix] or None}, "fences": [{"id",
    "boreholes": [{"id", "distance"}], "stations": [{"distance", "x", "y"}], "surfaces":
    [surface][station], "water": [station] or None, "length", "schematic"}], "notes"}``
    (m; ``surfaces`` has one more entry than ``units``: the ground, then each unit's bottom)."""
    settings = report.stratigraphy
    by = settings.correlateBy if settings is not None else "soilType"
    notes: list[str] = []
    logged = [b for b in report.boreholes if b.layers]
    if not logged:
        return {
            "correlateBy": by,
            "units": [],
            "boreholes": [],
            "grid": None,
            "fences": [],
            "notes": ["no borehole has logged layers"],
        }
    per = [strata(report, b, by) for b in logged]
    master, assignments = correlate([[s.key for s in seq] for seq in per])
    kinds: dict[int, str] = {}
    for seq, units in zip(per, assignments, strict=True):
        for stratum, unit in zip(seq, units, strict=True):
            kinds.setdefault(unit, stratum.soil_type)
    units = [
        {"id": f"U{k + 1}", "key": key, "soilType": kinds.get(k, key)}
        for k, key in enumerate(master)
    ]
    count = len(master) + 1  # surfaces: the ground, then each unit's bottom
    boreholes: list[dict[str, Any]] = []
    for borehole, seq, assigned in zip(logged, per, assignments, strict=True):
        surfaces: list[float | None] = [None] * count
        surfaces[0] = seq[0].top
        for stratum, unit in zip(seq, assigned, strict=True):
            surfaces[unit] = stratum.top if surfaces[unit] is None else surfaces[unit]
            surfaces[unit + 1] = stratum.bottom
        # Units passed through without meeting them are pinched out: their bottom is the
        # surface above them, down to the last stratum met.
        last = assigned[-1] + 1
        for k in range(1, last + 1):
            if surfaces[k] is None:
                surfaces[k] = surfaces[k - 1]
        ground = report.ground_level(borehole) / 1e3
        boreholes.append(
            {
                "id": borehole.id,
                "x": borehole.x / 1e3,
                "y": borehole.y / 1e3,
                "ground": ground,
                "bottom": seq[-1].bottom,
                "water": ground - borehole.waterTable / 1e3
                if borehole.waterTable is not None
                else None,
                "strata": [
                    {"unit": units[u]["id"], "top": s.top, "bottom": s.bottom}
                    for s, u in zip(seq, assigned, strict=True)
                ],
                "surfaces": surfaces,
            }
        )

    known = [
        [(b["x"], b["y"], b["surfaces"][k]) for b in boreholes if b["surfaces"][k] is not None]
        for k in range(count)
    ]
    water = [(b["x"], b["y"], b["water"]) for b in boreholes if b["water"] is not None]

    def at(x: float, y: float) -> tuple[list[float | None], float | None]:
        return _ordered([idw(points, x, y) for points in known]), idw(water, x, y)

    xs = [b["x"] for b in boreholes]
    ys = [b["y"] for b in boreholes]
    spread = max(max(xs) - min(xs), max(ys) - min(ys))
    grid = None
    if len(boreholes) > 1 and spread > 1.0:
        margin = max(MARGIN, 0.1 * spread)
        x0, x1 = min(xs) - margin, max(xs) + margin
        y0, y1 = min(ys) - margin, max(ys) + margin
        cell = max(x1 - x0, y1 - y0) / GRID_CELLS
        nx = max(2, round((x1 - x0) / cell) + 1)
        ny = max(2, round((y1 - y0) / cell) + 1)
        gx = [x0 + (x1 - x0) * i / (nx - 1) for i in range(nx)]
        gy = [y0 + (y1 - y0) * j / (ny - 1) for j in range(ny)]
        cells = [[at(x, y) for x in gx] for y in gy]
        grid = {
            "x": [round(v, 3) for v in gx],
            "y": [round(v, 3) for v in gy],
            "surfaces": [
                [[_round(cells[j][i][0][k]) for i in range(nx)] for j in range(ny)]
                for k in range(count)
            ],
            "water": [[_round(cells[j][i][1]) for i in range(nx)] for j in range(ny)]
            if water
            else None,
        }
    elif len(boreholes) > 1:
        notes.append(
            "the boreholes are at one plan position: give their positions (Log or Map) for the "
            "3D model; the fence is drawn with schematic spacing"
        )

    by_id = {b["id"]: b for b in boreholes}
    fences_in = [(f.id, f.boreholes) for f in settings.fences] if settings is not None else []
    if not fences_in and len(boreholes) > 1:
        order = _main_axis_order([(b["x"], b["y"]) for b in boreholes])
        fences_in = [("A", [boreholes[i]["id"] for i in order])]
    fences = []
    for fence_id, ids in fences_in:
        missing = [i for i in ids if i not in by_id]
        if missing:
            notes.append(f"fence {fence_id}: no logged borehole {', '.join(missing)}")
        chosen = [by_id[i] for i in ids if i in by_id]
        if len(chosen) < 2:
            notes.append(f"fence {fence_id}: needs two boreholes or more")
            continue
        fences.append(_fence(fence_id, chosen, at))
    return {
        "correlateBy": by,
        "units": units,
        "boreholes": boreholes,
        "grid": grid,
        "fences": fences,
        "notes": notes,
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _fence(fence_id: str, chosen: list[dict[str, Any]], at: Any) -> dict[str, Any]:
    lengths = [math.hypot(b["x"] - a["x"], b["y"] - a["y"]) for a, b in itertools.pairwise(chosen)]
    schematic = sum(lengths) < 1.0
    if schematic:
        lengths = [10.0] * len(lengths)
    total = sum(lengths)
    stations: list[dict[str, Any]] = []
    surfaces_at: list[list[float | None]] = []
    water_at: list[float | None] = []
    positions = [0.0]
    for length in lengths:
        positions.append(positions[-1] + length)
    count = max(FENCE_STATIONS, min(int(total) + 1, 400))
    distances = sorted({*positions, *(total * i / (count - 1) for i in range(count))})
    for d in distances:
        k = next((i for i in range(len(lengths)) if d <= positions[i + 1] + 1e-9), len(lengths) - 1)
        t = 0.0 if lengths[k] == 0 else (d - positions[k]) / lengths[k]
        a, b = chosen[k], chosen[k + 1]
        if schematic:
            # Coincident boreholes: blend their own surfaces instead of interpolating in plan.
            values = [
                None if va is None or vb is None else va + (vb - va) * t
                for va, vb in zip(a["surfaces"], b["surfaces"], strict=True)
            ]
            surfaces = _ordered(values)
            wa, wb = a["water"], b["water"]
            water = None if wa is None or wb is None else wa + (wb - wa) * t
            x, y = a["x"], a["y"]
        else:
            x = a["x"] + (b["x"] - a["x"]) * t
            y = a["y"] + (b["y"] - a["y"]) * t
            surfaces, water = at(x, y)
        stations.append({"distance": round(d, 3), "x": round(x, 3), "y": round(y, 3)})
        surfaces_at.append(surfaces)
        water_at.append(water)
    count_surfaces = len(chosen[0]["surfaces"])
    return {
        "id": fence_id,
        "boreholes": [
            {"id": b["id"], "distance": round(p, 3)} for b, p in zip(chosen, positions, strict=True)
        ],
        "stations": stations,
        "surfaces": [[_round(s[k]) for s in surfaces_at] for k in range(count_surfaces)],
        "water": [_round(w) for w in water_at] if any(w is not None for w in water_at) else None,
        "length": round(total, 3),
        "schematic": schematic,
    }
