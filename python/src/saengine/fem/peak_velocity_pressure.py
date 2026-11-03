"""Wind storey forces from the peak velocity pressure (``wind.method`` "peakVelocityPressure").

The method of EN 1991-1-4 (the code pack names the clauses), chosen by a pack's wind table:

- basic wind velocity vb = cdir·cseason·vb,0 (the project's basic wind speed is vb,0; cdir is
  the pack's ``directionality`` or the project's override);
- mean wind vm(z) = cr(z)·co(z)·vb with the logarithmic roughness factor cr(z) =
  kr·ln(z/z0), kr = 0.19·(z0/z0,II)^0.07, z taken between zmin and zmax (Sec 4.3); co the
  orography factor (the pack's ``topographic``, 1.0 on flat ground, or the project's
  override);
- turbulence intensity Iv(z) = kI/(co·ln(z/z0)) (Sec 4.4);
- peak velocity pressure qp(z) = [1 + 7·Iv(z)]·½·ρ·vm(z)² (Sec 4.5, Eq 4.8);
- the windward wall at the reference height ze of the building's proportions (Sec 7.2.2,
  h ≤ b, b < h ≤ 2b, h > 2b with the middle strips at their own height), the leeward wall at
  ze = h; external pressure coefficients cpe,10 of zones D and E by h/d (Table 7.1), the net
  force times the lack-of-correlation factor (Sec 7.2.2(3), 0.85 at h/d ≤ 1 to 1.0 at h/d ≥ 5)
  and the structural factor cscd (Sec 6.2: 1.0 where its simplified conditions hold; the
  detailed procedure of Sec 6.3 is not covered and is said so).

The internal pressure cancels in the net storey force. Units: m, m/s, kN.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from saengine.codes import context as code_context


def _table(wind: Any = None) -> Any:
    return wind if wind is not None else code_context.table("wind")


def roughness_terms(height: float, terrain: str, wind: Any = None) -> dict[str, float]:
    """kr, cr(z) and Iv(z) at ``height`` z [m] of the terrain category ``terrain`` (with co =
    1, the turbulence divided by co later)."""
    from saengine.fem.loads import wind_factor

    table = _table(wind)
    rule = table.peakVelocityPressure
    row = table.exposures[terrain]
    z0, zmin = float(row.z0), float(row.zmin)
    z = min(max(height, zmin), float(rule.zmax))
    kr = rule.krFactor * (z0 / rule.z0Reference) ** rule.krExponent
    log = math.log(z / z0)
    co = wind_factor("topographic")
    return {
        "z": z,
        "kr": kr,
        "cr": kr * log,
        "co": co,
        "Iv": rule.turbulence / (co * log),
    }


def peak_velocity_pressure(
    height: float, speed: float, terrain: str, importance: float = 1.0, wind: Any = None
) -> float:
    """qp(z) [kN/m²] at ``height`` z [m] for the fundamental basic wind velocity ``speed``
    vb,0 [m/s] on terrain ``terrain``, times ``importance`` (1.0 where the code has none)."""
    from saengine.fem.loads import wind_factor

    table = _table(wind)
    rule = table.peakVelocityPressure
    terms = roughness_terms(height, terrain, table)
    vb = wind_factor("directionality") * rule.season * speed
    vm = terms["cr"] * terms["co"] * vb
    qp = (1.0 + rule.peakFactor * terms["Iv"]) * 0.5 * rule.airDensity * vm**2
    return qp / 1000.0 * importance


def reference_height(z: float, height: float, width: float) -> float:
    """ze [m] of the windward wall at height ``z`` of a building ``height`` h tall and
    ``width`` b across the wind (EN 1991-1-4 Sec 7.2.2(1), Figure 7.4): h ≤ b one zone at h;
    b < h ≤ 2b a lower part at b and an upper part at h; h > 2b a lower part at b, an upper part
    at h and the strips between at their own height."""
    if width <= 0 or height <= width:
        return height
    if height <= 2 * width:
        return width if z <= width else height
    if z <= width:
        return width
    if z >= height - width:
        return height
    return z


def _along(points: list[tuple[float, float]], x: float) -> float:
    if not points:
        return 1.0
    points = sorted(points)
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in pairwise(points):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def wall_coefficients(ratio: float, wind: Any = None) -> tuple[float, float]:
    """(cpe,10 windward D, cpe,10 leeward E) for h/d = ``ratio``, linear between the rows; the
    pack's cpWindward and its leeward value at 1 when it has no wall table."""
    table = _table(wind)
    rows = sorted(table.wallPressure, key=lambda r: r.ratio)
    if not rows:
        return float(table.cpWindward), float(table.cpLeeward[0][1])
    windward = _along([(r.ratio, r.windward) for r in rows], ratio)
    leeward = _along([(r.ratio, r.leeward) for r in rows], ratio)
    return windward, leeward


def correlation_factor(ratio: float, wind: Any = None) -> float:
    """The lack-of-correlation factor on the net wall force for h/d = ``ratio``."""
    return _along(list(_table(wind).correlation), ratio)


def structural_factor(height: float, depth: float, wind: Any = None) -> tuple[float, str]:
    """(cscd, why) of a building ``height`` h tall and ``depth`` d along the wind: the pack's
    value where its simplified conditions hold (or the project's gust override), else the same
    value with a note that the detailed procedure is not covered."""
    from saengine.fem.loads import _WIND_OVERRIDES

    own = (_WIND_OVERRIDES.get() or {}).get("gust")
    if own is not None:
        return float(own), "the project's value"
    rule = _table(wind).structuralFactor
    if rule is None:
        return float(_table(wind).gust), "the pack's value"
    if rule.heightMax is not None and height < rule.heightMax:
        return rule.value, f"h = {height:.1f} m < {rule.heightMax:g} m"
    if (
        rule.frameHeightMax is not None
        and height < rule.frameHeightMax
        and (rule.depthRatioMax is None or height < rule.depthRatioMax * depth)
    ):
        return rule.value, (
            f"frame building with walls, h = {height:.1f} m < {rule.frameHeightMax:g} m and < "
            f"{rule.depthRatioMax:g} × d"
        )
    return rule.value, (
        f"h = {height:.1f} m outside the simplified cases: the detailed procedure for cscd is "
        f"not covered, {rule.value:g} used (check the dynamic response)"
    )


def wind_levels(
    heights: list[float],
    spans: list[tuple[float, float]],
    depths: list[float],
    speed: float,
    exposure: str,
    importance: float,
) -> list[Any]:
    """:func:`saengine.fem.loads.wind_levels` by the peak velocity pressure: storey ``i`` has
    the face ``spans[i]`` across the wind and the depth ``depths[i]`` along it. Level ``i``
    takes the lower half of storey ``i`` and the upper half of storey ``i + 1``; each half-face
    takes [qp(ze)·cpe,D - qp(h)·cpe,E]·ρ·cscd with h/d of the building at that storey's depth."""
    from saengine.fem.loads import WindLevel

    n = len(heights)
    if not n:
        return []
    if len(spans) != n or len(depths) != n:
        raise ValueError("wind_levels: one span and one depth per level")
    table = _table()
    top = heights[-1]
    qh = peak_velocity_pressure(top, speed, exposure, importance, table)
    out = []
    for i, z in enumerate(heights):
        parts = [(i, (z - (heights[i - 1] if i else 0.0)) / 2)]
        if i + 1 < n:
            parts.append((i + 1, (heights[i + 1] - z) / 2))
        force = moment = area = twist = 0.0
        for storey, tributary in parts:
            low, high = spans[storey]
            width = max(high - low, 0.0)
            depth = depths[storey]
            if width <= 0 or depth <= 0:
                continue
            ratio = top / depth
            windward, leeward = wall_coefficients(ratio, table)
            factor = correlation_factor(ratio, table) * structural_factor(top, depth, table)[0]
            ze = reference_height(z, top, width)
            qp = peak_velocity_pressure(ze, speed, exposure, importance, table)
            f = (qp * windward - qh * leeward) * factor * width * tributary
            force += f
            moment += f * (low + high) / 2
            twist += f * width
            area += width * tributary
        tributary_height = sum(t for _, t in parts)
        width = area / tributary_height if tributary_height else 0.0
        if force:
            centre = moment / force
        else:
            low, high = spans[i]
            centre = (low + high) / 2
        out.append(WindLevel(force, centre, width, twist / force if force else width))
    return out


def describe(height: float, width: float, depth: float, speed: float, exposure: str) -> str:
    """One line for the derivation notes: qp(h), cpe, ρ and cscd of the building."""
    table = _table()
    qh = peak_velocity_pressure(height, speed, exposure)
    ratio = height / depth if depth > 0 else 1.0
    windward, leeward = wall_coefficients(ratio, table)
    cscd, why = structural_factor(height, depth, table)
    return (
        f"wind by the peak velocity pressure ({code_context.code_name()}): vb,0 = {speed:g} m/s, "
        f"terrain {exposure}, qp(h = {height:.1f} m) = {qh:.3f} kN/m², h/d = {ratio:.2f}, cpe "
        f"D {windward:+.2f} / E {leeward:+.2f}, lack of correlation "
        f"{correlation_factor(ratio, table):.3f}, cscd {cscd:g} ({why}); b = {width:.1f} m"
    )
