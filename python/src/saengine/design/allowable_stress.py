"""Allowable stress design of members by the code pack's ``allowableStress`` table (method
``elasticSection``; alpha 9 track C19).

The members are checked under the pack's allowable stress combinations
(``combinations.allowable``), formed from the analysis's per-case forces: the rows the table
lists in ``longTerm`` against the long-term allowable stresses, the others against the short-
term ones. The floor live load takes the member's live load factor (the frames' value of
``liveReduction`` method ``frameValue``, or another reduction in force).

Reinforced concrete beams and columns (:func:`rc_rows`):

- flexure (beams) and axial force with bending (columns, each axis on its own): the cracked
  elastic section, plane sections, no concrete in tension, the bars at n times the concrete's
  stress (n the modular ratio); the allowable moment at the member's axial force the largest the
  concrete (fc), the tension and the compression bars (ft) allow, found on the interaction curve
  of all the strain planes scaled to the first limit reached;
- shear: Qa = b j (α fs + share wft (pw - offset)), α = numerator / (M/(Q d) + 1) within
  [alphaMin, alphaMax] (beams and columns their own largest α), j = leverArm d, pw at most
  ``pwMax``; long-term without the shear reinforcement unless ``longWithBars``.

Structural steel members (:func:`steel_rows`): σt/ft, σc/fc + σbx/fbx + σby/fby and (σb -
σc)/ft, τ/fs, with fc by the slenderness λ = max(Lx/ix, Ly/iy) (the member's length, K = 1),
fb of the strong axis of I shapes by the larger of the two lateral-torsional forms over the
member's length, ft elsewhere.

Every number comes from the pack; the clauses from its ``clauses`` (keys ``flexure``,
``axial``, ``shear``, ``steel``). Units: N, mm, MPa (N·mm moments).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.codes import context as code_context

#: Strain planes swept for the interaction curve of the elastic section.
_DIRECTIONS = 721
#: Concrete strips over the section's depth.
_STRIPS = 200


def table() -> Any | None:
    """The pack's ``allowableStress`` table; None when the pack in force has none."""
    pack = code_context.current()
    return pack.table("allowableStress") if pack.has("allowableStress") else None


def _cite(key: str) -> str:
    """`` (<code> <clause>)`` of the table's clause ``key``, '' when it has none."""
    text = code_context.cite("allowableStress", key) if table() is not None else ""
    return f" ({text})" if text else ""


# ───────────────────────────── combinations ─────────────────────────────


@dataclass(frozen=True)
class Combination:
    """An allowable stress combination: its name, {case: factor} and whether it is long-term."""

    name: str
    factors: dict[str, float]
    long: bool


def combinations(case_forces: dict[str, Any], live_factor: float = 1.0) -> list[Combination]:
    """The pack's allowable stress combinations that the analysis's ``case_forces`` can form
    (rows whose wind or earthquake cases have no results are left out), the floor live load
    cases × ``live_factor``."""
    from saengine.design.live_reduction import is_live_case
    from saengine.fem.combinations import allowable_combination_rows

    rule = table()
    if rule is None:
        return []
    long_ids = set(rule.longTerm)
    present = set(case_forces) | {"SD", "L", "Lr"}
    out = []
    for name, factors, row in allowable_combination_rows(present):
        if not all(c in case_forces or c in ("SD", "Lr", "L") for c, v in factors.items() if v):
            continue
        scaled = {c: (v * live_factor if is_live_case(c) else v) for c, v in factors.items() if v}
        out.append(Combination(name, scaled, getattr(row, "id", None) in long_ids))
    return out


def _combined(pieces: list[Any], case_forces: dict[str, Any], combos: list[Combination]) -> list:
    from saengine.design.timber.members import asd_pieces

    return asd_pieces(pieces, case_forces, [c.factors for c in combos])


# ───────────────────────────── allowable stresses ─────────────────────────────


def _grade(fy: float) -> Any:
    """The bar grade of the table nearest ``fy`` (the largest not above it, else the least)."""
    grades = list(table().rebar.grades.values())
    below = [g for g in grades if g.fy <= fy + 1e-6]
    return max(below, key=lambda g: g.fy) if below else min(grades, key=lambda g: g.fy)


def _grade_name(fy: float) -> str:
    grades = table().rebar.grades
    chosen = _grade(fy)
    return next(k for k, g in grades.items() if g is chosen)


def rebar_stress(fy: float, dia: float, long: bool) -> float:
    """The main bars' allowable stress [MPa] (tension or compression)."""
    rule = table().rebar
    grade = _grade(fy)
    if not long:
        return float(grade.short)
    if grade.longLarge is not None and dia >= rule.largeFrom - 1e-6:
        return float(grade.longLarge)
    return float(grade.long)


def shear_bar_stress(fy: float, long: bool) -> float:
    """wft [MPa] of the shear reinforcement."""
    grade = _grade(fy)
    return float(grade.shearLong if long else grade.shearShort)


def concrete_stress(fc: float, long: bool) -> float:
    """The concrete's allowable compression [MPa] of design strength ``fc``."""
    rule = table().concrete
    return float((rule.longShare if long else rule.shortShare) * fc)


def concrete_shear(fc: float, long: bool) -> float:
    """fs [MPa]: min(share Fc, offset + slope Fc), short-term × the factor."""
    rule = table().concrete
    fs = min(rule.shearShare * fc, rule.shearOffset + rule.shearSlope * fc)
    return float(fs if long else fs * rule.shortShearFactor)


# ───────────────────────────── the elastic section ─────────────────────────────


def interaction_curve(
    width: float,
    depth: float,
    bars: list[tuple[float, float, float]],
    fc_allowed: float,
    steel_allowed: list[float],
    n: float,
) -> np.ndarray:
    """(N, M) [N, N·mm] of the allowable stress state of every strain plane: a ``width`` ×
    ``depth`` rectangle, ``bars`` (y from the centroid towards the top [mm], area [mm²],
    diameter), each bar's allowable stress ``steel_allowed``. N compression positive, M
    positive compressing the top. Rows in the order of the planes (a closed curve)."""
    h = float(depth)
    ys = np.array([b[0] for b in bars], dtype=float)
    areas = np.array([b[1] for b in bars], dtype=float)
    limits = np.array(steel_allowed, dtype=float)
    edges = np.linspace(-h / 2, h / 2, _STRIPS + 1)
    mid = (edges[:-1] + edges[1:]) / 2
    strip = width * h / _STRIPS
    phi = np.linspace(0.0, 2 * math.pi, _DIRECTIONS)
    top, bottom = np.cos(phi), np.sin(phi)
    # Concrete-equivalent stress e(y) = bottom + (top - bottom) (y + h/2) / h of each plane.
    slope = (top - bottom) / h

    def at(y: np.ndarray) -> np.ndarray:
        return bottom[:, None] + slope[:, None] * (y[None, :] + h / 2)

    e_mid, e_bar = at(mid), at(ys)
    face = np.maximum(np.maximum(top, bottom), 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        scale_c = np.where(face > 1e-12, fc_allowed / face, np.inf)
        scale_s = np.where(
            np.abs(e_bar) > 1e-12, limits[None, :] / (n * np.abs(e_bar)), np.inf
        ).min(axis=1)
    scale = np.minimum(scale_c, scale_s)
    concrete = np.maximum(e_mid, 0.0) * strip
    steel = n * e_bar * areas[None, :]
    axial = scale * (concrete.sum(axis=1) + steel.sum(axis=1))
    moment = scale * (concrete @ mid + steel @ ys)
    return np.column_stack([axial, moment])


def allowable_moment(curve: np.ndarray, axial: float, positive: bool = True) -> float | None:
    """The allowable moment [N·mm] at ``axial`` N on ``curve`` (:func:`interaction_curve`):
    the largest positive moment (``positive``) or the largest negative one's size; None when
    the axial force is beyond the curve."""
    found: list[float] = []
    n0, m0 = curve[:-1, 0], curve[:-1, 1]
    n1, m1 = curve[1:, 0], curve[1:, 1]
    lo, hi = np.minimum(n0, n1), np.maximum(n0, n1)
    crossing = (lo <= axial) & (axial <= hi) & (hi - lo > 1e-9)
    for a, b, c, d in zip(n0[crossing], m0[crossing], n1[crossing], m1[crossing], strict=True):
        found.append(b + (d - b) * (axial - a) / (c - a))
    if not found:
        return None
    value = max(found) if positive else -min(found)
    return max(value, 0.0)


def _section_bars(section: Any, axis: str) -> tuple[float, float, list[tuple[float, float, float]]]:
    """(width, depth, bars) of ``section`` for bending about the profile's x axis (``axis``
    "x": the depth along y) or its y axis ("y": the width as the depth)."""
    if axis == "x":
        return section.width, section.depth, [(b.y, b.area, b.dia) for b in section.bars]
    return section.depth, section.width, [(b.x, b.area, b.dia) for b in section.bars]


def section_curve(section: Any, axis: str, long: bool) -> np.ndarray:
    """The allowable interaction curve of an RC section about ``axis`` (long- or short-term)."""
    width, depth, bars = _section_bars(section, axis)
    n = table().concrete.modularRatio
    return interaction_curve(
        width,
        depth,
        bars,
        concrete_stress(section.fc, long),
        [rebar_stress(section.fy, dia, long) for _, _, dia in bars],
        n,
    )


def _effective_depth(width: float, depth: float, bars: list[tuple[float, float, float]]) -> float:
    """d of the bars in the lower half (the depth to their centroid from the top face)."""
    lower = [(y, a) for y, a, _ in bars if y < 0]
    if not lower:
        return 0.9 * depth
    centroid = sum(y * a for y, a in lower) / sum(a for _, a in lower)
    return depth / 2 - centroid


def allowable_shear(
    width: float,
    d: float,
    fc: float,
    fy: float,
    pw: float,
    alpha: float,
    long: bool,
) -> float:
    """Qa [N] = b j (α fs + share wft (pw - offset)) (long-term without the bars unless the
    table says so)."""
    rule = table()
    j = rule.concrete.leverArm * d
    fs = concrete_shear(fc, long)
    bars = 0.0
    if not long or rule.shear.longWithBars:
        p = min(pw, rule.shear.pwMax)
        bars = (
            rule.shear.reinforcementShare
            * shear_bar_stress(fy, long)
            * max(p - rule.shear.pwOffset, 0.0)
        )
    return width * j * (alpha * fs + bars)


def shear_alpha(moment: float, shear: float, d: float, column: bool) -> float:
    """α = numerator / (M/(Q d) + 1) within [alphaMin, the member kind's alphaMax]."""
    rule = table().shear
    top = rule.columnAlphaMax if column else rule.beamAlphaMax
    if shear <= 0 or d <= 0:
        return rule.alphaMin
    ratio = abs(moment) / (abs(shear) * d)
    return min(max(rule.alphaNumerator / (ratio + 1.0), rule.alphaMin), top)


def shear_ratio(transverse: Any, width: float) -> float:
    """pw = aw / (b x) of the member's links (0 without any)."""
    if transverse is None or not getattr(transverse, "spacing", None):
        return 0.0
    area = math.pi * float(transverse.dia) ** 2 / 4 * int(getattr(transverse, "legs", 2) or 2)
    return area / (width * float(transverse.spacing))


# ───────────────────────────── the rows ─────────────────────────────


def _row(name: str, demand: float, capacity: float, unit: str, combination: str, note: str):
    from saengine.design.check import _check

    return _check(name, demand, capacity, unit, combination, note)


def rc_rows(
    section: Any,
    object_type: Any,
    pieces: list[Any],
    service: dict[str, Any],
    turned: bool,
    kind: str,
    live_factor: float = 1.0,
) -> list[dict[str, Any]]:
    """The allowable stress rows of an RC beam (``kind`` "beam") or column ("column"): for the
    long-term and for the short-term combinations, flexure (or axial force and bending) and
    shear, each at the governing station. [] without the table or the per-case forces."""
    from saengine.design.check import _profile_forces, _where

    rule = table()
    if rule is None or not pieces:
        return []
    case_forces = {**(service.get("forces") or {}), **(service.get("lateralForces") or {})}
    combos = combinations(case_forces, live_factor)
    if not combos or not case_forces:
        return []
    combined = _combined(pieces, case_forces, combos)
    transverse = getattr(getattr(object_type, "reinforcement", None), "transverse", None)
    column = kind == "column"
    axes = ("x", "y") if column else ("x",)
    curves = {
        (axis, long): section_curve(section, axis, long) for axis in axes for long in (True, False)
    }
    geometry = {axis: _section_bars(section, axis) for axis in axes}
    depths = {axis: _effective_depth(*geometry[axis]) for axis in axes}
    pw = {axis: shear_ratio(transverse, geometry[axis][0]) for axis in axes}
    worst: dict[tuple[str, bool], tuple[float, float, float, str, str]] = {}

    def keep(key: tuple[str, bool], util: float, demand: float, cap: float, c: str, w: str):
        if key not in worst or util > worst[key][0]:
            worst[key] = (util, demand, cap, c, w)

    for piece in combined:
        for c, forces in enumerate(piece.forces):
            combo = combos[c]
            values = _profile_forces(piece, turned, np.asarray(forces, dtype=float))
            count = len(forces)
            for k in range(count):
                axial = float(values["P"][k]) if column else 0.0
                where = _where(piece, k, count)
                for axis in axes:
                    moment = float(values["Mx" if axis == "x" else "My"][k])
                    cap = allowable_moment(curves[(axis, combo.long)], axial, moment >= 0)
                    if cap is None or cap <= 0:
                        util = 99.0 if abs(moment) > 0 or abs(axial) > 0 else 0.0
                        cap = 0.0
                    else:
                        util = abs(moment) / cap
                    keep(("M" + axis, combo.long), util, abs(moment), cap, combo.name, where)
                    shear = abs(float(values["Vy" if axis == "x" else "Vx"][k]))
                    width, _, _ = geometry[axis]
                    alpha = shear_alpha(moment, shear, depths[axis], column)
                    qa = allowable_shear(
                        width, depths[axis], section.fc, section.fy, pw[axis], alpha, combo.long
                    )
                    keep(
                        ("V" + axis, combo.long),
                        shear / qa if qa > 0 else 99.0,
                        shear,
                        qa,
                        combo.name,
                        f"α = {alpha:.2f}; {where}",
                    )
    grade = _grade_name(section.fy)
    n = rule.concrete.modularRatio
    rows = []
    for long in (True, False):
        term = "long-term" if long else "short-term"
        fc_a = concrete_stress(section.fc, long)
        for axis in axes:
            found = worst.get(("M" + axis, long))
            if found is not None:
                util, demand, cap, combo, where = found
                what = "axial force and bending" if column else "flexure"
                about = f" about {axis}" if column else ""
                rows.append(
                    _row(
                        f"Allowable stress, {what}{about} ({term})",
                        demand / 1e6,
                        cap / 1e6,
                        "kN·m",
                        combo,
                        f"elastic section n = {n:g}, fc = {fc_a:.1f} MPa, ft = "
                        f"{rebar_stress(section.fy, 0.0, long):g} MPa ({grade}); {where}"
                        + _cite("axial" if column else "flexure"),
                    )
                )
                rows[-1]["utilisation"] = round(float(min(util, 99.0)), 3)
                rows[-1]["ok"] = bool(rows[-1]["utilisation"] <= 1.0)
            found = worst.get(("V" + axis, long))
            if found is not None:
                util, demand, cap, combo, where = found
                about = f" along {'y' if axis == 'x' else 'x'}" if column else ""
                rows.append(
                    _row(
                        f"Allowable stress, shear{about} ({term})",
                        demand / 1e3,
                        cap / 1e3,
                        "kN",
                        combo,
                        f"Qa = b j (α fs + {rule.shear.reinforcementShare:g} wft (pw - "
                        f"{rule.shear.pwOffset:g})), fs = {concrete_shear(section.fc, long):.2f} "
                        f"MPa, pw = {pw[axis]:.4f}; {where}" + _cite("shear"),
                    )
                )
    return rows


def steel_stresses(fy: float, long: bool) -> dict[str, float]:
    """ft, fs [MPa] of steel of strength F = ``fy``."""
    rule = table().steel
    ft = fy / rule.longDivisor
    factor = 1.0 if long else rule.shortFactor
    return {"ft": ft * factor, "fs": ft / rule.shearDivisor * factor}


def steel_compression(fy: float, slenderness: float, long: bool) -> float:
    """fc [MPa] at the slenderness ratio λ."""
    rule = table().steel
    c = rule.compression
    limit = math.sqrt(math.pi**2 * rule.modulus / (c.limitShare * fy))
    ratio = slenderness / limit
    if ratio <= 1.0:
        nu = c.nuBase + c.nuSlope * ratio**2
        value = (1.0 - c.parabola * ratio**2) * fy / nu
    else:
        value = c.elastic * fy / ratio**2
    return value * (1.0 if long else rule.shortFactor)


def steel_bending(fy: float, length: float, profile: Any, long: bool) -> float:
    """fb [MPa] of the strong axis: I shapes by the two lateral-torsional forms over the
    unbraced ``length`` [mm], other shapes ft."""
    rule = table().steel
    ft = fy / rule.longDivisor
    d = getattr(profile, "overallDepth", None)
    bf = getattr(profile, "overallWidth", None)
    tf = getattr(profile, "flangeThickness", None)
    tw = getattr(profile, "webThickness", None)
    if not (d and bf and tf and tw) or length <= 0:
        return ft * (1.0 if long else rule.shortFactor)
    b = rule.bending
    c = rule.compression
    limit = math.sqrt(math.pi**2 * rule.modulus / (c.limitShare * fy))
    area = bf * tf + (d - 2 * tf) * tw / 6
    radius = math.sqrt(tf * bf**3 / 12 / area)
    first = fy * (b.base - b.slope * (length / radius) ** 2 / (b.momentGradient * limit**2))
    second = b.flangeConstant / (length * d / (bf * tf))
    value = min(max(first, second), ft)
    return value * (1.0 if long else rule.shortFactor)


def steel_rows(
    object_type: Any,
    fy: float,
    pieces: list[Any],
    service: dict[str, Any],
    turned: bool,
) -> list[dict[str, Any]]:
    """The allowable stress rows of a steel member: the combined stress ratio and the shear,
    long-term and short-term, at the governing station. [] without the table's steel group."""
    from saengine.design.check import _profile_forces, _where
    from saengine.design.steel.properties import shape_properties

    rule = table()
    if rule is None or rule.steel is None or not pieces:
        return []
    case_forces = {**(service.get("forces") or {}), **(service.get("lateralForces") or {})}
    combos = combinations(case_forces)
    if not combos or not case_forces:
        return []
    try:
        shape = shape_properties(object_type.profile)
    except ValueError:
        return []
    combined = _combined(pieces, case_forces, combos)
    length = 1e3 * sum(float(p.length) for p in pieces)
    radius_x = math.sqrt(shape.ix / shape.area)
    radius_y = math.sqrt(shape.iy / shape.area)
    slender = max(length / radius_x, length / radius_y)
    profile = object_type.profile
    d, tf, tw = (
        getattr(profile, k, None) for k in ("overallDepth", "flangeThickness", "webThickness")
    )
    web = (d - 2 * tf) * tw if d and tf and tw else shape.area / 2
    allowed = {
        long: {
            **steel_stresses(fy, long),
            "fc": steel_compression(fy, slender, long),
            "fbx": steel_bending(fy, length, profile, long),
            "fby": steel_stresses(fy, long)["ft"],
        }
        for long in (True, False)
    }
    worst: dict[tuple[str, bool], tuple[float, str, str]] = {}
    for piece in combined:
        for c, forces in enumerate(piece.forces):
            combo = combos[c]
            a = allowed[combo.long]
            values = _profile_forces(piece, turned, np.asarray(forces, dtype=float))
            count = len(forces)
            for k in range(count):
                p = float(values["P"][k])
                bx = abs(float(values["Mx"][k])) / shape.sx
                by = abs(float(values["My"][k])) / shape.sy
                sigma = abs(p) / shape.area
                if p >= 0:
                    ratio = max(
                        sigma / a["fc"] + bx / a["fbx"] + by / a["fby"], (bx + by - sigma) / a["ft"]
                    )
                else:
                    ratio = (sigma + bx + by) / a["ft"]
                tau = max(
                    abs(float(values["Vy"][k])) / web, abs(float(values["Vx"][k])) / shape.area * 2
                )
                where = _where(piece, k, count)
                for key, util in (("N", ratio), ("V", tau / a["fs"])):
                    if (key, combo.long) not in worst or util > worst[(key, combo.long)][0]:
                        worst[(key, combo.long)] = (util, combo.name, where)
    rows = []
    for long in (True, False):
        term = "long-term" if long else "short-term"
        a = allowed[long]
        found = worst.get(("N", long))
        if found is not None:
            util, combo, where = found
            rows.append(
                _row(
                    f"Allowable stress, axial force and bending ({term})",
                    util,
                    1.0,
                    "",
                    combo,
                    f"σc/fc + σbx/fbx + σby/fby, fc = {a['fc']:.0f}, fbx = {a['fbx']:.0f}, ft = "
                    f"{a['ft']:.0f} MPa (λ = {slender:.0f}, F = {fy:g} MPa); {where}"
                    + _cite("steel"),
                )
            )
        found = worst.get(("V", long))
        if found is not None:
            util, combo, where = found
            rows.append(
                _row(
                    f"Allowable stress, shear ({term})",
                    util,
                    1.0,
                    "",
                    combo,
                    f"τ / fs, fs = {a['fs']:.0f} MPa; {where}" + _cite("steel"),
                )
            )
    return rows
