"""Snow on the roof from the ground snow load (the code pack's ``snow`` table; C4, C1).

One generic method with the roof factor chosen by the pack (``snow.method``):

- ``shapeCoefficient`` (EN 1991-1-3 5.2(3)a, the persistent and transient design situation):
  s = factor·μ1·Ce·Ct·sk, μ1 by the roof's pitch (the pack's ``shape`` points);
- ``slopeFactor`` (ASCE 7-22 7.3-7.4): the flat roof load pf = factor·Ce·Ct·Is·pg (factor 0.7),
  the sloped roof load ps = Cs·pf with Cs by the pitch from the pack's ``slope`` rows (by Ct,
  slippery or other roofs), and on low-slope roofs at least the minimum pm; s = max(ps, pm).

sk / pg is the ground snow load the project gives (Site > Snow), Ce the exposure coefficient of
the site's exposure (an id of the pack's ``exposures``), Ct the thermal coefficient, Is by the
occupancy (risk) category where the pack has one, the pitch that of Wind > Cladding: roof form
(flat taken as 0°). The derivation puts the snow into the pack's ``loadCase``: Lr, the larger of
it and the roof live load (``withRoofLive`` "envelope"), or its own case S ("separate").

The drift at a roof step (the pack's ``drift`` by its method id, ``windParameter``: ASCE 7-22
7.8) is computed and reported for the lower roof's design, not applied. A pack without a
``snow`` table does not cover snow: a ground snow load is then reported, not applied.
Overhangs, snow guards, unbalanced loads and the exceptional (accidental) snow loads are not
covered.

Units: kN/m², m, °.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from saengine.codes import context as code_context

FT = 0.3048  # m per ft
PSF = 0.04788026  # kN/m² per psf
PCF = 0.15708746  # kN/m³ per pcf


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


def slope_factor(table: Any, ct: float, angle: float, slippery: bool) -> float:
    """Cs of a roof of pitch ``angle`` [°] (method ``slopeFactor``): the first of the pack's
    ``slope`` rows whose ``ctMax`` holds ``ct`` (the last row otherwise); 1 up to the row's
    start (slippery or other roofs), then linear to 0 at its end."""
    rows = sorted(table.slope, key=lambda r: r.ctMax)
    if not rows:
        return 1.0
    row = next((r for r in rows if ct <= r.ctMax + 1e-9), rows[-1])
    start = row.slipperyStart if slippery else row.otherStart
    if angle <= start:
        return 1.0
    if angle >= row.end:
        return 0.0
    return (row.end - angle) / (row.end - start)


def density(table: Any, ground: float) -> float | None:
    """γ [kN/m³] of the pack's ``density`` rule at the ground snow load; None without one."""
    rule = getattr(table, "density", None)
    if rule is None:
        return None
    return min(rule.factor * ground + rule.constant, rule.maximum)


def shape_drift(
    rule: Any, ground: float, step: Any, ce: float, ct: float, parapet: float | None
) -> dict[str, Any] | None:
    """Alpha 9 C5c: the drift by shape coefficients (method ``shapeCoefficient``, see
    :class:`saengine.codes.tables.SnowShapeDriftRule`) at the roof step ``step`` (b1 its
    ``upperLength``, b2 ``lowerLength``, h ``stepHeight``) and, without a step, at a parapet
    ``parapet`` h [m] high: ``{"hd" (h), "w" (ls), "pd" (s at the step), "mu2", "muw", "ls",
    "s1", "where", "gamma"}``."""
    gamma = rule.density
    lo, hi = rule.lengthRange
    if step is not None:
        h = float(step.stepHeight)
        b1 = float(step.upperLength)
        b2 = float(step.lowerLength or 0.0)
        cap = gamma * h / ground
        muw = min((b1 + b2) / (2 * h), cap)
        muw = min(max(muw, rule.windRange[0]), rule.windRange[1])
        mu2, where = muw, "roof step"
    elif parapet:
        h = float(parapet)
        muw = None
        mu2 = min(max(gamma * h / ground, rule.parapetRange[0]), rule.parapetRange[1])
        where = "parapet"
    else:
        return None
    ls = min(max(rule.lengthFactor * h, lo), hi)
    return {
        "hd": round(h, 4),
        "w": round(ls, 4),
        "pd": round(mu2 * ce * ct * ground, 4),
        "mu2": round(mu2, 4),
        "muw": None if muw is None else round(muw, 4),
        "ls": round(ls, 4),
        "s1": round(rule.lowerShape * ce * ct * ground, 4),
        "where": where,
        "gamma": gamma,
        "method": "shapeCoefficient",
    }


def drift(table: Any, ground: float, step: Any) -> dict[str, Any] | None:
    """The leeward and windward drifts at a roof step (``step``: upperLength, lowerLength,
    stepHeight, windParameter) by the pack's ``drift`` (method ``windParameter``: hd =
    coefficient·(pg^a·lu^b·W2^c/γ)^power in the equation's units), the larger governing:
    ``{"hd", "w", "pd", "gamma", "hc", "leeward", "windward", "W2"}`` [m, kN/m², kN/m³]; None
    without the pack's rule, a step or W2."""
    rule = getattr(table, "drift", None)
    gamma = density(table, ground)
    if rule is None or step is None or gamma is None:
        return None
    w2 = step.windParameter if step.windParameter is not None else rule.windParameter
    if w2 is None:
        return None

    def height(length: float) -> float:
        length = max(length, rule.minLength)
        if rule.units == "imperial":
            value = (
                (ground / PSF) ** rule.groundExponent
                * (length / FT) ** rule.lengthExponent
                * w2**rule.windExponent
                / (gamma / PCF)
            )
            return rule.coefficient * value**rule.power * FT
        value = ground**rule.groundExponent * length**rule.lengthExponent * w2**rule.windExponent
        return rule.coefficient * (value / gamma) ** rule.power

    leeward = height(float(step.upperLength))
    windward = rule.windwardShare * height(float(step.lowerLength)) if step.lowerLength else 0.0
    hd = max(leeward, windward)
    hc = float(step.stepHeight)
    width = rule.widthFactor * hd
    if hd > hc:
        width = min(rule.widthFactor * hd**2 / hc, rule.widthMax * hc)
        hd = hc
    return {
        "hd": round(hd, 4),
        "w": round(width, 4),
        "pd": round(gamma * hd, 4),
        "gamma": round(gamma, 4),
        "hc": hc,
        "leeward": round(leeward, 4),
        "windward": round(windward, 4),
        "W2": w2,
    }


def roof_angle(settings: Any) -> float:
    """The roof pitch [°] of the project (Wind > Cladding: roof form; a flat roof 0°)."""
    roof = getattr(getattr(settings, "wind", None), "claddingRoof", None)
    if roof is None or getattr(roof, "form", "flat") == "flat":
        return 0.0
    return float(getattr(roof, "angle", None) or 0.0)


def roof_snow(settings: Any) -> dict[str, Any] | None:
    """The roof snow load of the project: ``{"s_kPa", "sk_kPa", "mu1" (the roof factor: μ1 or
    Cs), "Ce", "Ct", "Is", "angle_deg", "exposure", "case", "method", "source"}`` and, with
    ``slopeFactor``, ``"pf_kPa"``, ``"pm_kPa"`` (None on a steeper roof); ``"drift"`` where the
    pack and the project give one; None without a ground snow load. Raises ``LookupError`` when
    the pack does not cover snow (the caller reports it)."""
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
    category = getattr(getattr(settings, "occupancy", None), "category", None)
    importance = float(table.importance.get(category, 1.0)) if table.importance else 1.0
    angle = roof_angle(settings)
    ground = float(ground)
    out: dict[str, Any] = {
        "sk_kPa": ground,
        "Ce": ce,
        "Ct": ct,
        "Is": importance,
        "angle_deg": angle,
        "exposure": exposure,
        "case": table.loadCase,
        "method": table.method,
        "source": table.source,
    }
    if table.method == "slopeFactor":
        cs = slope_factor(table, ct, angle, bool(getattr(snow, "slippery", False)))
        pf = table.factor * ce * ct * importance * ground
        rule = table.minimum
        pm = None
        if rule is not None and angle < rule.slopeMax:
            pm = importance * (rule.share * ground if ground <= rule.groundLimit else rule.value)
        out.update(mu1=cs, pf_kPa=pf, pm_kPa=pm, s_kPa=max(cs * pf, pm or 0.0))
    else:
        mu1 = shape_coefficient(angle, list(table.shape))
        out.update(mu1=mu1, s_kPa=table.factor * mu1 * ce * ct * importance * ground)
    rule = getattr(table, "drift", None)
    if getattr(rule, "method", None) == "shapeCoefficient":  # Alpha 9 C5c
        parapet = getattr(getattr(settings, "wind", None), "parapetHeight", None)
        found = shape_drift(rule, ground, getattr(snow, "drift", None), ce, ct, parapet)
    else:
        found = drift(table, ground, getattr(snow, "drift", None))
    if found is not None:
        out["drift"] = found
    return out


def describe(snow: dict[str, Any]) -> str:
    """The roof snow in words, for the derivation's notes."""
    if snow["method"] == "slopeFactor":
        text = (
            f"snow S = max(Cs·pf, pm) = {snow['s_kPa']:.2f} kN/m² on the roof slabs (pf = "
            f"0.7·Ce·Ct·Is·pg = {snow['pf_kPa']:.2f}, Cs = {snow['mu1']:.2f}, Ce = {snow['Ce']:g}, "
            f"Ct = {snow['Ct']:g}, Is = {snow['Is']:g}, pg = {snow['sk_kPa']:g}"
            + (f", pm = {snow['pm_kPa']:.2f}" if snow.get("pm_kPa") is not None else "")
            + f"; {snow['source']}; roof {snow['angle_deg']:g}°, exposure {snow['exposure']})"
        )
    else:
        text = (
            f"snow s = μ1·Ce·Ct·sk = {snow['mu1']:.2f} × {snow['Ce']:g} × {snow['Ct']:g} × "
            f"{snow['sk_kPa']:g} = {snow['s_kPa']:.2f} kN/m² on the roof slabs ({snow['source']}; "
            f"roof {snow['angle_deg']:g}°, exposure {snow['exposure']})"
        )
    if snow["case"] == "S":
        text += ", in its own case S (the combinations take Lr or S)"
    else:
        text += f", in {snow['case']} where larger than the roof live load (not together)"
    found = snow.get("drift")
    if found is not None and found.get("method") == "shapeCoefficient":  # Alpha 9 C5c
        text += (
            f"; drift at the {found['where']} h = {found['hd']:.2f} m: μ2 = {found['mu2']:.2f}"
            + (f" (μw = {found['muw']:.2f}, μs = 0)" if found.get("muw") is not None else "")
            + f", s = {found['pd']:.2f} kN/m² falling to {found['s1']:.2f} over ls = "
            f"{found['ls']:.2f} m (reported for the lower roof, not applied)"
        )
    elif found is not None:
        text += (
            f"; drift at the roof step hd = {found['hd']:.2f} m, w = {found['w']:.2f} m, pd = "
            f"{found['pd']:.2f} kN/m² (reported for the lower roof, not applied)"
        )
    return text
