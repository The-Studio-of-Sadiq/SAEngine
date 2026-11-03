"""Roof snow loads (case S) from the ground snow load, by the code pack's ``snow`` table.

Generic: the pack gives the numbers (:class:`saengine.codes.tables.SnowTable`), the formulas
are the common form of the codes that start from a ground snow load:

- the flat roof snow load pf = flatFactor · Ce · Ct · Is · pg (Ce by terrain and roof
  exposure, Ct by thermal condition, Is by occupancy category where the pack has it);
- the sloped roof snow load ps = Cs · pf, Cs = 1 up to the slope where the roof sheds snow
  (slippery or other roofs, by Ct), then linear to 0;
- the minimum snow load of low-slope roofs pm (a share of pg up to a limit, a fixed value
  above it);
- the drift at a roof step by the pack's drift method (``windParameter``): its height hd,
  width w and surcharge pd = γ hd on the lower roof (γ from pg). The drift is reported for
  the design of the lower roof; the model takes the uniform snow load S on the roof slabs.

The project's input is Project Settings > Site > Snow (``site.snow``). Units: kN/m², m, °.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from saengine.codes import context as code_context

FT = 0.3048  # m per ft
PSF = 0.04788026  # kN/m² per psf
PCF = 0.15708746  # kN/m³ per pcf


class SnowNotCovered(Exception):
    """The code pack in force has no snow table."""


def table(pack: Any = None) -> Any:
    """The pack's ``snow`` table; :class:`SnowNotCovered` without one."""
    p = pack or code_context.current()
    if not p.has("snow"):
        raise SnowNotCovered(f"the code pack {code_context.code_name(p)} does not cover snow")
    return p.table("snow")


@dataclass
class RoofSnow:
    """The roof snow of a site: the factors, pf, ps, pm and the governing uniform load S."""

    pg: float
    Ce: float
    Ct: float
    Is: float
    Cs: float
    pf: float
    ps: float
    pm: float | None
    S: float
    drift: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out = {
            k: round(v, 4) if isinstance(v, float) else v
            for k, v in self.__dict__.items()
            if k not in ("drift", "notes")
        }
        if self.drift is not None:
            out["drift"] = self.drift
        return out


def slope_factor(data: Any, ct: float, slope: float, slippery: bool) -> float:
    """Cs of a roof of ``slope`` [°]: the first row of the pack's ``slope`` whose ``ctMax``
    holds ``ct`` (the last row otherwise); 1 without rows."""
    rows = sorted(data.slope, key=lambda r: r.ctMax)
    if not rows:
        return 1.0
    row = next((r for r in rows if ct <= r.ctMax + 1e-9), rows[-1])
    start = row.slipperyStart if slippery else row.otherStart
    if slope <= start:
        return 1.0
    if slope >= row.end:
        return 0.0
    return (row.end - slope) / (row.end - start)


def density(data: Any, pg: float) -> float | None:
    """γ [kN/m³] of the pack's ``density`` rule; None without one."""
    rule = data.density
    if rule is None:
        return None
    return min(rule.factor * pg + rule.constant, rule.maximum)


def drift(data: Any, pg: float, step: Any) -> dict[str, Any] | None:
    """The leeward and windward drifts at a roof step (``step``: upperLength, lowerLength,
    stepHeight, windParameter): the larger governs. ``{"hd", "w", "pd", "hc", "leeward",
    "windward", "W2"}`` [m, kN/m²]; None without the pack's rule or a step."""
    rule = data.drift
    gamma = density(data, pg)
    if rule is None or step is None or gamma is None:
        return None
    w2 = step.windParameter if step.windParameter is not None else rule.windParameter
    if w2 is None:
        return None

    def height(length: float) -> float:
        length = max(length, rule.minLength)
        if rule.units == "imperial":
            value = (
                (pg / PSF) ** rule.groundExponent
                * (length / FT) ** rule.lengthExponent
                * w2**rule.windExponent
                / (gamma / PCF)
            )
            return rule.coefficient * value**rule.power * FT
        value = pg**rule.groundExponent * length**rule.lengthExponent * w2**rule.windExponent
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


def roof_snow(site: Any, category: str, pack: Any = None) -> RoofSnow | None:
    """The roof snow of Project Settings > Site > Snow (``site``) for occupancy (risk)
    ``category``; None without snow. :class:`SnowNotCovered` when the pack has no snow table;
    KeyError for a terrain or thermal condition the pack does not list."""
    if site is None:
        return None
    data = table(pack)
    pg = float(site.groundLoad)
    terrain = data.exposure.get(site.terrain)
    if terrain is None:
        raise KeyError(f"terrain category '{site.terrain}' (snow exposure table)")
    ce = float(terrain[site.roofExposure])
    if site.thermal not in data.thermal:
        raise KeyError(f"thermal condition '{site.thermal}' (snow thermal table)")
    ct = float(data.thermal[site.thermal])
    importance = float(data.importance.get(category, 1.0)) if data.importance else 1.0
    pf = data.flatFactor * ce * ct * importance * pg
    cs = slope_factor(data, ct, float(site.slope), bool(site.slippery))
    ps = cs * pf
    pm = None
    rule = data.minimum
    if rule is not None and float(site.slope) < rule.slopeMax:
        pm = importance * (rule.share * pg if pg <= rule.groundLimit else rule.value)
    load = max(ps, pm or 0.0)
    notes = []
    if pm is not None and pm > ps:
        notes.append(f"the minimum snow load of a low-slope roof pm = {pm:.2f} kN/m² governs")
    out = RoofSnow(pg, ce, ct, importance, cs, pf, ps, pm, load, notes=notes)
    out.drift = drift(data, pg, getattr(site, "drift", None))
    if out.drift is not None:
        out.notes.append(
            f"drift at the roof step: hd = {out.drift['hd']:.2f} m, w = {out.drift['w']:.2f} m, "
            f"pd = {out.drift['pd']:.2f} kN/m² on top of S (reported for the lower roof's design, "
            "not applied to the model)"
        )
    return out


def seismic_weight_share(snow: RoofSnow | None, pack: Any = None) -> float:
    """The share of the flat roof snow load in the seismic weight (the pack's
    ``seismicShare`` where pf is above ``seismicThreshold``), 0 otherwise."""
    if snow is None:
        return 0.0
    try:
        data = table(pack)
    except SnowNotCovered:
        return 0.0
    if data.seismicShare is None:
        return 0.0
    if data.seismicThreshold is not None and snow.pf <= data.seismicThreshold:
        return 0.0
    return float(data.seismicShare)
