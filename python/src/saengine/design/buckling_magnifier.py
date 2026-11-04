"""Slender columns by the moment magnifier with the buckling load from the balanced moment
(method ``bucklingMagnifier`` of the pack's ``concreteMethods.slenderness``; alpha 9 C18c, the
form of AS 3600:2018 10.4).

Per bending direction of a column segment (the effective length Le = k lu and the radius of
gyration r of :mod:`saengine.design.slender`, which finds the storeys, the restraints and k):

- short when Le / r is at most ``bracedLimit`` (braced) or ``unbracedLimit`` (sway storeys and
  cantilevers); every column takes at least the least moment ``M* >= N* minEccentricityShare D``;
- the buckling load ``Nc = (π² / Le²) stiffnessCoefficient do φ Mub / (1 + βd)``, Mub the
  balanced moment of the section (strain compatibility: the extreme fibre at the pack's εcu,
  the extreme tension bar at fsy / Es, the pack's rectangular stress block), do the depth to
  the extreme tension bar, φ = ``phiBuckling``, βd the sustained share of N* (the dead load
  cases), within 0 and 1;
- braced: ``δb = km / (1 - N* / Nc) >= 1``, ``km = kmBase + kmSlope M1/M2`` (SAEngine's sign:
  M1/M2 positive in single curvature, i.e. the code's km = 0.6 - 0.4 M1*/M2* with its sign), at
  least ``kmMin``, 1.0 with transverse loads along the column;
- sway storeys: the larger of δb and δs, δs the storey's (:meth:`saengine.design.slender.Storey.
  delta_s`, the project's sway magnifier option; ``sumPc`` takes ΣN*/ΣNc of the storey);
  ``M* = δ max(M2, the least moment)``; Le / r above ``slendernessMax`` is not covered (a
  rigorous analysis is asked for).

Units: mm, N, N·mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context

METHOD = "bucklingMagnifier"


def rules() -> Any | None:
    """The pack's ``concreteMethods.slenderness`` when it is this method (None otherwise)."""
    try:
        pack = code_context.current()
    except Exception:  # noqa: BLE001 - no pack machinery (a bare calculation)
        return None
    if not pack.has("concreteMethods"):
        return None
    table = pack.table("concreteMethods")
    if "slenderness" in (getattr(table, "parentMethods", None) or ()):
        return None
    from saengine.codes.method_tables import chosen

    return chosen(table, "slenderness", METHOD)


def _cite(key: str = "slenderness") -> str:
    found = code_context.cite("concreteMethods", key)
    return f" ({found})" if found else ""


def balanced(section: Any, axis: str, h: float) -> tuple[float, float] | None:
    """(Mub [N·mm], do [mm]) of the section bent about its ``axis`` ("x": the bars' y, depth
    ``h`` along y), by strain compatibility at the balanced point (see the module notes); None
    without bars. Rectangles and circles by 200 strips of the compression zone."""
    from saengine.design import rc

    bars = list(getattr(section, "bars", ()) or ())
    if not bars:
        return None
    r = rules()
    fc, fy, es = float(section.fc), float(section.fy), float(section.es)
    eps_cu = float(r.ultimateStrain) if r is not None and r.ultimateStrain else rc.eps_cu(fc)
    alpha, gamma = rc.alpha1(fc), rc.beta1(fc)
    coords = [(float(b.y) if axis == "x" else float(b.x), float(b.area)) for b in bars]
    top = h / 2
    lowest = min(y for y, _ in coords)
    do = top - lowest
    if do <= 0:
        return None
    c = eps_cu / (eps_cu + fy / es) * do
    a = min(gamma * c, h)
    from saengine.library.objects import CircleProfile

    circle = isinstance(getattr(section, "profile", None), CircleProfile)
    other = float(section.width if axis == "x" else section.depth)
    force = moment = 0.0
    strips = 200
    for i in range(strips):
        y0 = top - a * i / strips
        y1 = top - a * (i + 1) / strips
        ym = (y0 + y1) / 2
        if circle:
            radius = h / 2
            width = 2 * math.sqrt(max(radius * radius - ym * ym, 0.0))
        else:
            width = other
        f = alpha * fc * width * (y0 - y1)
        force += f
        moment += f * ym
    for y, area in coords:
        strain = eps_cu * (c - (top - y)) / c
        stress = max(min(es * strain, fy), -fy)
        if top - y < a:
            stress -= alpha * fc  # the concrete the bar displaces
        moment += stress * area * y
    return abs(moment), do


def buckling_load(mub: float, do: float, le: float, beta: float, r: Any) -> float:
    """Nc [N]."""
    beta = min(max(beta, 0.0), 1.0)
    ei = r.stiffnessCoefficient * do * r.phiBuckling * mub / (1 + beta)
    return math.pi**2 * ei / le**2 if le > 0 else math.inf


def km_factor(ratio: float, transverse: bool, r: Any) -> float:
    """km (``ratio`` = M1/M2, positive in single curvature)."""
    if transverse:
        return 1.0
    return max(r.kmBase + r.kmSlope * ratio, r.kmMin)


def magnify(
    pu: float,
    m_bot: float,
    m_top: float,
    sway: bool,
    transverse: bool,
    le: float,
    radius: float,
    depth: float,
    balanced_point: tuple[float, float] | None,
    beta: float,
    delta_s: float = 1.0,
    km_given: float | None = None,
    delta_given: float | None = None,
    spectral: bool = False,
) -> dict[str, Any]:
    """One combination of one axis: the slenderness, the magnifiers and the design moment
    ``med`` [N·mm] (see the module notes)."""
    r = rules()
    m2 = max(abs(m_bot), abs(m_top))
    m1 = min(abs(m_bot), abs(m_top))
    same = spectral or m2 == 0 or m_bot * m_top > 0
    ratio = (m1 / m2 if m2 > 0 else 1.0) * (1 if same else -1)
    lam = le / radius if radius > 0 else math.inf
    limit = float(r.unbracedLimit if sway else r.bracedLimit)
    m_min = max(pu, 0.0) * r.minEccentricityShare * depth
    out: dict[str, Any] = {
        "lambda": lam, "limit": limit, "ratio": ratio, "m2": m2, "mmin": m_min,
        "slender": lam > limit and pu > 0, "km": None, "nc": None, "db": 1.0, "ds": delta_s,
        "delta": 1.0, "beta": min(max(beta, 0.0), 1.0), "sway": sway, "buckles": False,
        "over": lam > r.slendernessMax, "spectral": spectral,
    }  # fmt: skip
    base = max(m2, m_min)
    if not out["slender"]:
        out["med"] = base
        return out
    km = float(km_given) if km_given is not None else km_factor(ratio, transverse or spectral, r)
    out["km"] = km
    nc = buckling_load(*balanced_point, le, beta, r) if balanced_point else 0.0
    out["nc"] = nc
    if delta_given is not None:
        db = float(delta_given)
    elif nc <= 0 or pu >= nc:
        db = math.inf
        out["buckles"] = True
    else:
        db = max(km / (1 - pu / nc), 1.0)
    out["db"] = db
    delta = max(db, delta_s) if sway else db
    out["delta"] = delta
    out["med"] = delta * base if math.isfinite(delta) else math.inf
    return out


def check_row(axis: str, best: dict[str, Any], combinations: list[str]) -> dict[str, Any]:
    """The slenderness row of an axis (the strength check takes M* with the magnifier)."""
    from saengine.design.check import _check

    r = rules()
    found = best["magnifier"]
    seg = best["segment"]
    kind = "unbraced" if found["sway"] else "braced"
    parts = [
        (
            f"Le = k lu = {best['k']:.2f} × {best['lu']:.0f} mm, r = {best['radius']:.0f} mm, "
            f"Le/r = {found['lambda']:.1f} against {found['limit']:g} ({kind})"
        ),
        f"{seg.pieces[0].name}" + (f" to {seg.pieces[-1].name}" if len(seg.pieces) > 1 else ""),
        f"M* at least N* × {r.minEccentricityShare:g} D = {found['mmin'] / 1e6:.1f} kN·m",
    ]
    failures = []
    if found["slender"]:
        nc = found["nc"] or 0.0
        parts.append(
            f"km = {found['km']:.2f}, βd = {found['beta']:.2f}, Nc = (π²/Le²) "
            f"{r.stiffnessCoefficient:g} do φ Mub / (1 + βd) = {nc / 1e3:.0f} kN (φ = "
            f"{r.phiBuckling:g}), δb = {_fmt(found['db'])}"
            + (f", δs = {_fmt(found['ds'])}" if found["sway"] else "")
            + f", M* = {_fmt(found['delta'])} × {max(found['m2'], found['mmin']) / 1e6:.1f} kN·m"
        )
        if found["buckles"]:
            failures.append("N* >= Nc: the column buckles, enlarge it")
    else:
        parts.append("short: no magnification")
    if found["spectral"]:
        parts.append("response spectrum combination: single curvature and km = 1.0 taken")
    if found["over"]:
        failures.append(
            f"Le/r above {r.slendernessMax:g}: a rigorous second-order analysis is required"
        )
    parts += failures
    row = _check(
        f"Slenderness about {axis} ({'slender, δ = ' + _fmt(found['delta']) if found['slender'] else 'short'})",
        float(found["lambda"]),
        float(r.slendernessMax),
        "",
        combinations[best["c"]],
        "; ".join(parts) + _cite(),
        flag=not found["slender"] and not failures,
    )
    if failures:
        row["ok"] = False
        row["utilisation"] = max(row["utilisation"], 99.0 if found["buckles"] else 1.01)
    return row


def _fmt(value: float) -> str:
    return f"{value:.2f}" if math.isfinite(value) else "∞"


def method_lines() -> list[str]:
    """The design report's lines of the method."""
    r = rules()
    if r is None:
        return []
    return [
        (
            f"Column slenderness{_cite()}: Le = k lu (k from the alignment charts in sway storeys, the "
            f"project's option in braced ones), r = 0.3 D or 0.25 D; short when Le/r <= "
            f"{r.bracedLimit:g} braced or {r.unbracedLimit:g} unbraced; M* >= N* × "
            f"{r.minEccentricityShare:g} D. Slender columns: M* = δ M2*, δb = km / (1 - N*/Nc) >= 1, "
            f"km = {r.kmBase:g} - {r.kmSlope:g} M1*/M2* >= {r.kmMin:g} (1.0 with transverse loads), "
            f"Nc = (π²/Le²) {r.stiffnessCoefficient:g} do φ Mub / (1 + βd), φ = {r.phiBuckling:g}, Mub "
            "the balanced moment by strain compatibility; unbraced: δ the larger of δb and δs (the "
            f"storey's); Le/r at most {r.slendernessMax:g}."
        )
    ]
