"""Columns by the additional moment method and the load contour of biaxial bending (alpha 9
C8; the pack's ``concreteMethods.columns``, as IS 456:2000 39.6-39.7 give them).

- Slenderness (method ``additionalMoment``): about each axis lex = k lu (k and lu as the
  slenderness of :mod:`saengine.design.slender` finds them: the effective length factor of the
  framing and the clear height), D the depth in that direction. A column with lex / D above
  ``limit`` is slender: the moments about that axis take Ma = Pu D / ``divisor`` (lex / D)²,
  reduced by k = (Puz - Pu) / (Puz - Pb) <= 1 (Pb the axial force of the balanced strain
  state, the extreme bar at fyd / Es + the pack's ``neutralAxisStrain``, the concrete at
  εcu). The additional moment is added at every station (the braced columns' 0.4 M1 + 0.6 M2
  of the initial moment is not used: on the safe side). lex / D at most ``maxRatio``.
- Biaxial bending (method ``loadContour``): (Mux / Mux1)^αn + (Muy / Muy1)^αn <= 1, Mux1 and
  Muy1 the uniaxial capacities at Pu read from the interaction surface on the design
  strengths, αn by Pu / Puz (linear between the pack's points), Puz = a fck Ac + b fy Asc.
  ``surface`` keeps the interaction surface's own utilisation.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.design.tabulated_shear import _group, _interp, _paren

#: The load contour is evaluated on the points the surface ranks highest (it is a slower
#: read per point): this many.
CONTOUR_POINTS = 24


def rules() -> Any | None:
    """The pack's ``concreteMethods.columns``, or None."""
    return _group("columns")


def puz(section: Any, r: Any | None = None) -> float:
    """Puz [N] = a fck Ac + b fy Asc."""
    r = r or rules()
    a, b = r.biaxial.puzShares
    ast = section.steel_area
    return a * section.fc * (section.gross_area - ast) + b * section.fy * ast


def alpha_n(pu: float, p_uz: float, r: Any | None = None) -> float:
    r = r or rules()
    ratio = pu / p_uz if p_uz > 0 else 1.0
    points = sorted(r.biaxial.alphaN)
    return _interp(ratio, [p for p, _ in points], [a for _, a in points])


def balanced_axial(section: Any, axis: str) -> float:
    """Pb [N]: the axial force of the balanced strain state bending about ``axis`` ("x": Mx,
    over the depth; "y": over the width)."""
    from concreteproperties.results import UltimateBendingResults

    from saengine.design import design_strength
    from saengine.design.member_limits import limits

    lim = limits()
    extra = lim.neutralAxisStrain if lim is not None else 0.002
    eps_cu = design_strength.ultimate_strain(section.fc)
    eps_s = design_strength.fyd(section.fy) / section.es + extra
    if axis == "x":
        theta, reach = 0.0, section.depth / 2 + max(abs(b.y) for b in section.bars)
    else:
        theta, reach = math.pi / 2, section.width / 2 + max(abs(b.x) for b in section.bars)
    d_n = eps_cu / (eps_cu + eps_s) * reach
    cp = section.analysis
    try:
        result = cp.calculate_ultimate_section_actions(
            d_n=d_n,
            ultimate_results=UltimateBendingResults(default_units=cp.default_units, theta=theta),
        )
    except Exception:  # noqa: BLE001 - an unusual section: no reduction (k = 1 kept)
        return 0.0
    return float(result.n)


def slender_points(
    section: Any,
    slender: Any,
    points: list[tuple[float, float, float, str, str]],
) -> tuple[list[tuple[float, float, float, str, str]], list[dict[str, Any]]]:
    """The demand points with the additional moments, and the slenderness rows (one per axis),
    in place of the moment magnification's (``slender``: the column's
    :class:`saengine.design.slender.ColumnSlenderness`)."""
    from saengine.design.check import _check

    r = rules()
    s = r.slenderness
    p_uz = puz(section, r)
    rows: list[dict[str, Any]] = []
    adds: dict[str, tuple[float, float, float]] = {}  # axis -> (lex, D, Pb)
    for axis_result in slender.axes:
        info = (axis_result.check or {}).get("slenderness") or {}
        axis = info.get("axis") or axis_result.axis
        depth = section.depth if axis == "x" else section.width
        lu, k = float(info.get("lu") or 0.0), float(info.get("k") or 1.0)
        lex = k * lu
        ratio = lex / depth if depth > 0 else 0.0
        slender_axis = ratio > s.limit
        pb = balanced_axial(section, axis) if slender_axis else 0.0
        if slender_axis:
            adds[axis] = (lex, depth, pb)
        pu_max = max((p[0] for p in points), default=0.0)
        ma = _additional(pu_max, depth, lex, p_uz, pb, s) if slender_axis else 0.0
        note = f"lex = k lu = {k:.2f} × {lu:.0f} = {lex:.0f} mm, D = {depth:.0f} mm: " + (
            f"slender (> {s.limit:g}), Ma = Pu D/{s.divisor:g} (lex/D)² k = "
            f"{ma / 1e6:.2f} kN·m at Pu = {pu_max / 1e3:.0f} kN (Puz = {p_uz / 1e3:.0f} kN, "
            f"Pb = {pb / 1e3:.0f} kN)"
            if slender_axis
            else f"short (<= {s.limit:g}), no additional moment"
        )
        rows.append(
            _check(
                f"Slenderness about {axis}{_paren('slenderness')}",
                ratio,
                s.maxRatio,
                "",
                None,
                note,
                flag=not slender_axis,
            )
        )
    if not adds:
        return points, rows
    out = []
    for pu, mux, muy, combination, where in points:
        if pu > 0:
            if "x" in adds:
                lex, depth, pb = adds["x"]
                mux = mux + _additional(pu, depth, lex, p_uz, pb, s)
            if "y" in adds:
                lex, depth, pb = adds["y"]
                muy = muy + _additional(pu, depth, lex, p_uz, pb, s)
        out.append((pu, mux, muy, combination, where))
    return out, rows


def _additional(pu: float, depth: float, lex: float, p_uz: float, pb: float, s: Any) -> float:
    """Ma [N·mm] at Pu with the reduction k = (Puz - Pu)/(Puz - Pb) <= 1."""
    if pu <= 0 or depth <= 0:
        return 0.0
    k = (p_uz - pu) / (p_uz - pb) if p_uz > pb else 1.0
    k = min(1.0, max(0.0, k))
    return pu * depth / s.divisor * (lex / depth) ** 2 * k


def load_contour(
    section: Any, surface: Any, points: list[tuple[float, float, float, str, str]]
) -> tuple[float, Any, str] | None:
    """The governing load contour utilisation of the points: (utilisation, point, note); None
    when the pack keeps the surface's."""
    import numpy as np

    r = rules()
    if r is None or r.biaxial.method != "loadContour" or not points:
        return None
    p_uz = puz(section, r)
    ranked = np.argsort(-np.asarray(surface.utilisations([p[:3] for p in points])))
    best: tuple[float, Any, str] | None = None
    for i in ranked[:CONTOUR_POINTS]:
        pu, mux, muy, *_ = points[int(i)]
        if pu > section.phi_pn_max:
            util, note = pu / section.phi_pn_max, "Pu above the axial capacity"
        else:
            mux1 = surface.moment_capacity(pu, 0.0)
            muy1 = surface.moment_capacity(pu, math.pi / 2)
            if mux1 <= 0 or muy1 <= 0:
                util, note = math.inf, "no moment capacity at this axial force"
            else:
                an = alpha_n(pu, p_uz, r)
                util = (mux / mux1) ** an + (muy / muy1) ** an
                note = (
                    f"(Mux/Mux1)^αn + (Muy/Muy1)^αn, Mux1 = {mux1 / 1e6:.1f}, Muy1 = "
                    f"{muy1 / 1e6:.1f} kN·m, αn = {an:.2f} (Pu/Puz = {pu / p_uz:.2f})"
                    f"{_paren('biaxial')}"
                )
        if best is None or util > best[0]:
            best = (util, points[int(i)], note)
    return best
