"""Snow on the roof from the ground snow load (the code pack's ``snow`` table).

s = μ1·Ce·Ct·sk (EN 1991-1-3 5.2(3)a, the persistent and transient design situation): sk the
characteristic snow load on the ground the project gives (Site > Snow), μ1 the roof shape
coefficient by the roof's pitch (the pack's ``shape`` points, the roof form and angle of Wind >
Cladding: roof form, flat taken as 0°), Ce the exposure coefficient of the site, Ct the thermal
coefficient. The derivation puts the snow into the pack's ``loadCase`` (Lr) on the roof slabs,
the larger of it and the roof live load (``withRoofLive`` "envelope": the imposed load on roofs
need not act together with snow).

A pack without a ``snow`` table does not cover snow: a ground snow load is then reported, not
applied. Drifting at abrupt changes of height, overhangs, snow guards and the exceptional
(accidental) snow loads are not covered.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from saengine.codes import context as code_context


def shape_coefficient(angle: float, shape: list[tuple[float, float]]) -> float:
    """μ1 at the roof pitch ``angle`` [°] from (angle, μ1) points: linear between, the end
    values outside."""
    points = sorted(shape)
    if angle <= points[0][0]:
        return points[0][1]
    for (a0, m0), (a1, m1) in pairwise(points):
        if angle <= a1:
            return m0 + (m1 - m0) * (angle - a0) / (a1 - a0)
    return points[-1][1]


def roof_angle(settings: Any) -> float:
    """The roof pitch [°] of the project (Wind > Cladding: roof form; a flat roof 0°)."""
    roof = getattr(getattr(settings, "wind", None), "claddingRoof", None)
    if roof is None or getattr(roof, "form", "flat") == "flat":
        return 0.0
    return float(getattr(roof, "angle", None) or 0.0)


def roof_snow(settings: Any) -> dict[str, Any] | None:
    """The roof snow load of the project: ``{"s_kPa", "sk_kPa", "mu1", "Ce", "Ct", "angle_deg",
    "exposure", "case", "source"}``; None without a ground snow load. Raises ``LookupError``
    when the pack does not cover snow (the caller reports it)."""
    snow = getattr(getattr(settings, "site", None), "snow", None)
    ground = getattr(snow, "groundLoad", None)
    if not ground:
        return None
    pack = code_context.current()
    if not pack.has("snow"):
        raise LookupError(f"the code pack {code_context.code_name()} does not cover snow")
    table = code_context.table("snow")
    exposure = getattr(snow, "exposure", None) or table.defaultExposure
    if exposure not in table.exposures:
        exposure = table.defaultExposure
    ce = table.exposures[exposure].Ce
    ct = float(getattr(snow, "thermal", None) or table.thermal)
    angle = roof_angle(settings)
    mu1 = shape_coefficient(angle, list(table.shape))
    return {
        "s_kPa": table.factor * mu1 * ce * ct * float(ground),
        "sk_kPa": float(ground),
        "mu1": mu1,
        "Ce": ce,
        "Ct": ct,
        "angle_deg": angle,
        "exposure": exposure,
        "case": table.loadCase,
        "source": table.source,
    }
