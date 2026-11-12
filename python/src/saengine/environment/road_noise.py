"""An indicative road traffic noise level at the facades (alpha 9 L11).

The form of the UK Calculation of Road Traffic Noise (CRTN, 1988), for orientation only (no
screening by other buildings or barriers, no angle-of-view, ground absorption or reflection
corrections other than the facade's): per road,

    L10,18h = basic + flowSlope · log10(Q)                                  (Chart 3)
            + 33 · log10(V + 40 + 500 / V) + 10 · log10(1 + 5 p / V) − 68.8    (Chart 4)
            + gradientPerPercent · G                                        (Chart 6)
            − 10 · log10(d' / 13.5)                                         (Chart 7)
            + facade                                                     (facade reflection)

with Q the 18-hour flow [vehicles, 06:00-24:00], V the mean speed [km/h], p the share of heavy vehicles [%],
G the gradient [%], d' the slant distance [m] from the source line (``kerbOffset`` from the
near kerb, ``sourceHeight`` high) to the receiver. Several roads add energetically. A facade
point whose straight line to a road's nearest point crosses the building is screened: it gets
no level from that road. Every constant is in ``data/environment-defaults.json`` with its
source; the result is an indicative facade level, not a noise assessment.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.environment.solar import Massing


def road_level(
    flow: float,
    speed: float,
    heavy: float,
    gradient: float,
    distance: float,
    height: float,
    k: dict[str, Any],
) -> float:
    """L10,18h [dB(A)] at the facade of one road (see the module notes); ``distance`` [m] from
    the near kerb, ``height`` [m] of the receiver above the road."""
    a, b, c, d = k["speedTerm"]
    v = max(speed, 1.0)
    level = k["basic"] + k["flowSlope"] * math.log10(max(flow, 1.0))
    level += a * math.log10(v + b + c / v) + 10 * math.log10(1 + k["heavyFactor"] * heavy / v) + d
    level += k["gradientPerPercent"] * gradient
    slant = math.hypot(max(distance, 0.0) + k["kerbOffset"], height - k["sourceHeight"])
    level -= 10 * math.log10(max(slant, 0.1) / k["referenceDistance"])
    return level + k["facade"]


def facade_levels(
    points: np.ndarray,
    roads: list[dict[str, Any]],
    massing: Massing,
    ground: float,
    k: dict[str, Any],
) -> list[dict[str, Any]]:
    """Per facade point: ``{"l10", "laeq", "roads": {road: level}, "screened": [road ids]}``.
    ``roads``: ``{id, path [[x, y] mm], flow, speed, heavy, gradient, width [mm]}``."""
    from shapely.geometry import LineString, Point

    lines = [(r, LineString([(float(p[0]), float(p[1])) for p in r["path"]])) for r in roads]
    out = []
    for p in points:
        energy = 0.0
        levels: dict[str, float] = {}
        screened: list[str] = []
        here = Point(float(p[0]), float(p[1]))
        for road, line in lines:
            nearest = line.interpolate(line.project(here))
            target = np.array([nearest.x, nearest.y, ground + k["sourceHeight"] * 1000])
            direction = target - p
            span = float(np.linalg.norm(direction))
            if span <= 0:
                continue
            ray = direction / span
            # Blocked before reaching the road: the building screens this facade point.
            if _blocked_within(massing, p, ray, span):
                screened.append(str(road["id"]))
                continue
            kerb = max(here.distance(line) - float(road.get("width") or 7000.0) / 2, 0.0) / 1000
            level = road_level(
                float(road.get("flow") or 0.0),
                float(road.get("speed") or 50.0),
                float(road.get("heavy") or 0.0),
                float(road.get("gradient") or 0.0),
                kerb,
                (float(p[2]) - ground) / 1000,
                k,
            )
            levels[str(road["id"])] = round(level, 1)
            energy += 10 ** (level / 10)
        l10 = 10 * math.log10(energy) if energy > 0 else None
        out.append(
            {
                "l10": round(l10, 1) if l10 is not None else None,
                "laeq": round(l10 + k["l10ToLaeq"], 1) if l10 is not None else None,
                "roads": levels,
                "screened": screened,
            }
        )
    return out


def _blocked_within(massing: Massing, origin: np.ndarray, ray: np.ndarray, span: float) -> bool:
    """Whether the massing blocks the ray (unit) from ``origin`` within ``span`` [mm]."""
    return bool(massing.blocked(origin[None, :], ray, reach=span)[0])
