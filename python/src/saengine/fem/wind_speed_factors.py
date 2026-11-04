"""Design wind pressure from factors on the design wind speed (a code pack's wind table with
``pressureMethod: "speedFactors"``).

The method of codes that scale the basic wind speed by factors and turn the design speed into a
pressure (the form of IS 875 (Part 3)):

    Vz = Vb · k1 · k2(z, terrain) · k3 · k4
    pz = airFactor · Vz²                          [N/m², V in m/s]
    pd = max(Kd · Ka · Kc, minimumShare) · pz

- k1, the risk coefficient: the pack's ``speedFactors.riskCoefficients`` row whose
  ``importance`` is the occupancy category's wind importance, at the basic wind speed Vb (linear
  between its points, constant outside); the importance itself when no row has it;
- k2, terrain and height: ``speedFactors.heightFactors`` of the terrain (the settings' exposure)
  at the height z (linear between its points, constant below the first and above the last);
- k3, topography: the wind table's ``topographic`` (a project overrides it in Project Settings
  > Wind, the field the default pack calls Kzt);
- k4, cyclonic importance: ``speedFactors.importance`` (a project overrides it through Code
  Values, ``wind.speedFactors.importance``); alpha 9 C9b: on a cyclone-prone site
  (``wind.speedFactors.cyclonic``) at least the pack's ``cyclonicImportance`` of the
  occupancy's risk class, and Kd = ``cyclonicDirectionality``;
- Kd, directionality: the wind table's ``directionality`` (or the project's override); Ka, area
  averaging of the main wind-force resisting system: ``speedFactors.areaAveraging``; Kc,
  combination: ``speedFactors.combination``.

Alpha 9 C23: a terrain with ``speedFactors.referencePressures`` (codes that tabulate the design
pressure by height, the Hong Kong Code of Practice on Wind Effects type) takes pz = q(z)·k1·k3·k4,
the factors acting on the pressure; Vz is then √(pz / airFactor) and k2 √(q(z) / q(10 m)), for the
notes only.

The pressures enter the storey forces of :func:`saengine.fem.loads.wind_levels` in place of the
velocity pressure qz, with the pack's wall pressure coefficients and its gust factor (1.0 for a
code whose coefficients include the gusts). Every number comes from the code pack in force.

Units: m, m/s; :func:`design_pressure` returns kN/m².
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from saengine.codes import context as code_context

__all__ = ["design_pressure", "design_speed", "factors", "height_factor", "risk_coefficient"]


def _table() -> Any:
    table = getattr(code_context.table("wind"), "speedFactors", None)
    if table is None:
        raise ValueError("the code pack's wind table has no speedFactors")
    return table


def _interpolate(points: list[tuple[float, float]] | list[list[float]], x: float) -> float:
    pts = sorted((float(a), float(b)) for a, b in points)
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in itertools.pairwise(pts):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y1
    return pts[-1][1]


def reference_pressure(height: float, exposure: str, table: Any | None = None) -> float | None:
    """Alpha 9 C23: q(z) [kN/m²] of the pack's ``referencePressures`` of the terrain
    ``exposure`` at ``height`` [m]; None where the pack tabulates no pressure for it."""
    rows = (table or _table()).referencePressures or {}
    if exposure not in rows:
        return None
    return _interpolate(rows[exposure], max(float(height), 0.0))


def height_factor(height: float, exposure: str) -> float:
    """k2 at ``height`` [m] in the terrain ``exposure``; alpha 9 C23: √(q(z) / q(10 m)) of a
    terrain with reference pressures."""
    q = reference_pressure(height, exposure)
    if q is not None:
        q10 = reference_pressure(10.0, exposure) or q
        return math.sqrt(q / q10) if q10 > 0 else 1.0
    rows = _table().heightFactors
    if exposure not in rows:
        raise ValueError(f"no height factors for terrain '{exposure}' in the code pack")
    return _interpolate(rows[exposure], max(float(height), 0.0))


def risk_coefficient(speed: float, importance: float) -> float:
    """k1 of the occupancy categories of wind importance ``importance`` at the basic wind
    speed ``speed`` [m/s]."""
    for row in _table().riskCoefficients:
        if abs(row.importance - importance) < 1e-9:
            return _interpolate(row.k1, float(speed))
    return float(importance)


def cyclonic_importance(importance: float, table: Any | None = None) -> float:
    """k4 of a cyclone-prone site for the occupancy of wind importance ``importance``: the
    pack's ``cyclonicImportance`` of its risk class (``riskCoefficients`` row id), else its
    'other' value, else 1."""
    table = table or _table()
    rows = table.cyclonicImportance
    for row in table.riskCoefficients:
        if abs(row.importance - importance) < 1e-9 and row.id in rows:
            return float(rows[row.id])
    return float(rows.get("other", 1.0))


def slope_factor() -> dict[str, Any] | None:
    """C12: k3 of a hill, ridge or escarpment by the pack's ``speedFactors.topography`` from
    the project's topography (Project Settings > Wind > Topography: H the feature's height Z,
    Lh; L = ``upwindLengthFactor`` × Lh the upwind slope's length): θ = atan(Z / L); k3 = 1 up
    to ``flatSlope``, else 1 + C s with C = ``gentleFactor`` Z/L up to ``steepSlope`` and
    ``steepFactor`` above, s the pack's ``speedUp`` (the peak of the code's figures at the
    crest unless changed in Code Values). None: no rule, no feature, or the project sets k3."""
    from saengine.fem.loads import _TOPOGRAPHY, _WIND_OVERRIDES

    rule = getattr(_table(), "topography", None)
    topo = _TOPOGRAPHY.get()
    if rule is None or topo is None:
        return None
    if (_WIND_OVERRIDES.get() or {}).get("topographic") is not None:
        return None
    z = float(topo.height)
    length = rule.upwindLengthFactor * float(topo.length)
    theta = math.degrees(math.atan2(z, length))
    if theta <= rule.flatSlope:
        c = 0.0
    elif theta <= rule.steepSlope:
        c = rule.gentleFactor * z / length
    else:
        c = rule.steepFactor
    return {"k3": 1.0 + c * rule.speedUp, "theta": theta, "C": c, "s": rule.speedUp}


def factors(height: float, speed: float, exposure: str, importance: float) -> dict[str, float]:
    """Every factor of the design pressure at ``height``: k1, k2, k3, k4, Kd, Ka, Kc, the
    product K (at least the pack's minimum share), Vz [m/s], pz and pd [kN/m²]."""
    from saengine.fem.loads import wind_factor

    table = _table()
    k1 = risk_coefficient(speed, importance)
    k2 = height_factor(height, exposure)
    k3 = wind_factor("topographic")
    slope = slope_factor()  # C12: k3 from the site's slope where the pack gives the rule
    if slope is not None:
        k3 = slope["k3"]
    k4 = float(table.importance)
    kd = wind_factor("directionality")
    if table.cyclonic:  # Alpha 9 C9b: a cyclone-prone site
        k4 = max(k4, cyclonic_importance(importance, table))
        if table.cyclonicDirectionality is not None:
            kd = float(table.cyclonicDirectionality)
    ka, kc = float(table.areaAveraging), float(table.combination)
    k = max(kd * ka * kc, float(table.minimumShare))
    vz = float(speed) * k1 * k2 * k3 * k4
    pz = table.airFactor * vz**2 / 1000.0
    q = reference_pressure(height, exposure, table)
    if q is not None:  # Alpha 9 C23: the code's pressure by height, the factors on it
        pz = q * k1 * k3 * k4
        vz = math.sqrt(pz * 1000.0 / table.airFactor)
    return {
        "k1": k1,
        "k2": k2,
        "k3": k3,
        "k4": k4,
        "Kd": kd,
        "Ka": ka,
        "Kc": kc,
        "K": k,
        "Vz": vz,
        "pz": pz,
        "pd": k * pz,
    }


def design_speed(height: float, speed: float, exposure: str, importance: float) -> float:
    """Vz = Vb·k1·k2·k3·k4 [m/s]."""
    return factors(height, speed, exposure, importance)["Vz"]


def design_pressure(height: float, speed: float, exposure: str, importance: float) -> float:
    """pd = max(Kd·Ka·Kc, minimumShare)·airFactor·Vz² [kN/m²] at ``height`` [m] for the basic
    wind speed ``speed`` [m/s], terrain ``exposure`` and wind importance ``importance``."""
    return factors(height, speed, exposure, importance)["pd"]
