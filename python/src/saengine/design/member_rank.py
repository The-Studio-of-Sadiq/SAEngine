"""The rank of a member for the structural characteristic factor Ds (the code pack's
``horizontalCapacity.memberRanks`` and ``shearStrength``; alpha 9 track C19).

Reinforced concrete columns rank by the clear height over the depth h0/D, the axial stress
σ0/Fc under the long-term loads, the tension steel ratio pt [%] and the shear stress at the
flexural mechanism τu/Fc; beams by τu/Fc. τu = Qmu / (b j), Qmu the shear when both ends reach
their flexural strength (beams: plus the long-term gravity shear), the strengths by the pack's
``shearStrength`` forms (Mu = beam at σy d, column at σy D + axialShare N D (1 - N / (b D
Fc))). A member whose mean shear strength Qsu (``meanEmpirical``) is below Qmu fails in shear:
it takes ``shearFailureRank``. Steel members rank by the width-thickness ratios of their
plates × √(reference / F) (pipes D/t × reference / F).

The rank is a reported row (``flag``) carrying ``rank``: the storeys' check of the horizontal
capacity reads the worst rank of the design run (:mod:`saengine.fem.horizontal_capacity`).
SAEngine practice (stated in the notes): h0 and the beams' L0 are the members' analysis
lengths (centre to centre, no clear spans), pw of the links outside the end zones.

Units: N, mm, MPa.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.codes import context as code_context


def tables() -> tuple[Any, Any] | None:
    """(memberRanks, shearStrength) of the pack's ``horizontalCapacity``; None without it."""
    pack = code_context.current()
    if not pack.has("horizontalCapacity"):
        return None
    table = pack.table("horizontalCapacity")
    if table.memberRanks is None:
        return None
    return table.memberRanks, table.shearStrength


def _cite(key: str) -> str:
    """`` (<code> <clause>)`` of the horizontalCapacity clause ``key``, '' without one."""
    if not code_context.current().has("horizontalCapacity"):
        return ""
    text = code_context.cite("horizontalCapacity", key)
    return f" ({text})" if text else ""


def mean_shear_strength(
    rule: Any,
    width: float,
    d: float,
    fc: float,
    pt: float,
    pw: float,
    fwy: float,
    sigma0: float,
    span_ratio: float,
) -> float:
    """Qsu [N] = {c pt^e (Fc + offset) / (M/(Q d) + spanOffset) + bars √(pw σwy) + axial σ0}
    b j, pt [%], j = 7/8 d."""
    lo, hi = rule.spanRange
    ratio = min(max(span_ratio, lo), hi)
    concrete = (
        rule.coefficient
        * max(pt, 1e-6) ** rule.ptExponent
        * (fc + rule.offset)
        / (ratio + rule.spanOffset)
    )
    bars = rule.bars * math.sqrt(min(pw, rule.pwMax) * fwy)
    return (concrete + bars + rule.axial * max(sigma0, 0.0)) * width * 0.875 * d


def beam_strength(rule: Any, at: float, fy: float, d: float) -> float:
    """Mu [N·mm] = beam at σy d."""
    return rule.beam * at * rule.yieldFactor * fy * d


def column_strength(rule: Any, at: float, fy: float, width: float, depth: float, n: float,
                    fc: float) -> float:  # fmt: skip
    """Mu [N·mm] = column at σy D + axialShare N D (1 - N / (b D Fc)) (N compression +)."""
    n = max(n, 0.0)
    return rule.column * at * rule.yieldFactor * fy * depth + rule.axialShare * n * depth * (
        1.0 - n / (width * depth * fc)
    )


def _rank(order: list[str], limits: dict[str, Any], values: dict[str, float]) -> str:
    """The best rank of ``order`` whose limits ``values`` meet ("clearRatio" at least, the
    others at most); the last rank when none."""
    for rank in order[:-1]:
        rule = limits.get(rank)
        if rule is None:
            continue
        ok = True
        for key, value in values.items():
            limit = getattr(rule, key, None)
            if limit is None:
                continue
            if key == "clearRatio":
                ok = ok and value >= limit - 1e-9
            else:
                ok = ok and value <= limit + 1e-9
        if ok:
            return rank
    return order[-1]


def _face_bars(section: Any, axis: str, top: bool) -> float:
    """The area of the bars of a face half (tension face) about ``axis``."""
    coordinate = "y" if axis == "x" else "x"
    return sum(b.area for b in section.bars if (getattr(b, coordinate) > 0) == top)


def _long_forces(pieces: list[Any], service: dict[str, Any], turned: bool) -> tuple[float, float]:
    """(largest compression N [N], largest shear [N]) of the long-term allowable stress
    combinations (0, 0 without them)."""
    from saengine.design import allowable_stress
    from saengine.design.check import _profile_forces

    case_forces = {**(service.get("forces") or {}), **(service.get("lateralForces") or {})}
    combos = [c for c in allowable_stress.combinations(case_forces) if c.long]
    if not combos:
        return 0.0, 0.0
    combined = allowable_stress._combined(pieces, case_forces, combos)
    axial = shear = 0.0
    for piece in combined:
        for forces in piece.forces:
            values = _profile_forces(piece, turned, np.asarray(forces, dtype=float))
            axial = max(axial, float(np.max(values["P"])) if len(values["P"]) else 0.0)
            shear = max(shear, float(np.max(np.abs(values["Vy"]))) if len(values["Vy"]) else 0.0)
    return axial, shear


def rc_row(
    section: Any,
    object_type: Any,
    pieces: list[Any],
    service: dict[str, Any],
    turned: bool,
    kind: str,
) -> dict[str, Any] | None:
    """The rank row of an RC beam or column; None without the pack's rank limits."""
    from saengine.design.allowable_stress import shear_ratio
    from saengine.design.check import _check

    found = tables()
    if found is None or not pieces:
        return None
    ranks, strength = found
    if strength is None:
        return None
    length = 1e3 * sum(float(p.length) for p in pieces)
    if length <= 0:
        return None
    transverse = getattr(getattr(object_type, "reinforcement", None), "transverse", None)
    fwy = section.fy
    axial, gravity = _long_forces(pieces, service, turned)
    fc = section.fc
    notes = []
    if kind == "column":
        worst: tuple[str, dict[str, float], bool] | None = None
        order = ranks.order
        for axis in ("x", "y"):
            width, depth = (
                (section.width, section.depth) if axis == "x" else (section.depth, section.width)
            )
            at = max(_face_bars(section, axis, True), _face_bars(section, axis, False))
            d = 0.9 * depth
            mu = column_strength(strength, at, section.fy, width, depth, axial, fc)
            qmu = 2.0 * mu / length
            pt = 100.0 * at / (width * depth)
            pw = shear_ratio(transverse, width)
            sigma0 = axial / (width * depth)
            qsu = mean_shear_strength(
                strength, width, d, fc, pt, pw, fwy, sigma0, length / (2.0 * d)
            )
            values = {
                "clearRatio": length / depth,
                "axialRatio": sigma0 / fc,
                "tensionRatio": pt,
                "shearRatio": qmu / (width * 0.875 * d) / fc,
            }
            rank = _rank(order, ranks.columns, values)
            shear_failure = qsu < qmu
            if shear_failure:
                rank = ranks.shearFailureRank or order[-1]
            if worst is None or order.index(rank) > order.index(worst[0]):
                worst = (rank, {**values, "Qsu": qsu, "Qmu": qmu}, shear_failure)
        assert worst is not None
        rank, values, shear_failure = worst
        text = (
            f"h0/D = {values['clearRatio']:.2f}, σ0/Fc = {values['axialRatio']:.3f}, pt = "
            f"{values['tensionRatio']:.2f} %, τu/Fc = {values['shearRatio']:.3f}; Qsu = "
            f"{values['Qsu'] / 1e3:.0f} kN, Qmu = {values['Qmu'] / 1e3:.0f} kN"
        )
    else:
        width, depth = section.width, section.depth
        d = 0.9 * depth
        top, bottom = _face_bars(section, "x", True), _face_bars(section, "x", False)
        mu = beam_strength(strength, top, section.fy, d) + beam_strength(
            strength, bottom, section.fy, d
        )
        qmu = mu / length + gravity
        pt = 100.0 * max(top, bottom) / (width * d)
        pw = shear_ratio(transverse, width)
        qsu = mean_shear_strength(strength, width, d, fc, pt, pw, fwy, 0.0, length / (2.0 * d))
        values = {"shearRatio": qmu / (width * 0.875 * d) / fc}
        rank = _rank(ranks.order, ranks.beams, values)
        shear_failure = qsu < qmu
        if shear_failure:
            rank = ranks.shearFailureRank or ranks.order[-1]
        text = (
            f"τu/Fc = {values['shearRatio']:.3f}; Qsu = {qsu / 1e3:.0f} kN, Qmu = "
            f"{qmu / 1e3:.0f} kN (Mu at both ends over L0 + the long-term shear)"
        )
    if shear_failure:
        notes.append("shear failure before flexural yield (Qsu < Qmu)")
    notes.append("h0, L0: analysis lengths (SAEngine practice)")
    row = _check(
        f"Member rank {rank}" + _cite("ranks"),
        float(ranks.order.index(rank) + 1),
        float(len(ranks.order)),
        "",
        None,
        f"{text}; " + "; ".join(notes),
        flag=True,
    )
    row["rank"] = rank
    return row


def steel_row(object_type: Any, fy: float, kind: str) -> dict[str, Any] | None:
    """The width-thickness rank row of a steel beam or column; None without the limits or for
    a shape they do not cover."""
    from saengine.design.check import _check

    found = tables()
    if found is None:
        return None
    ranks, _ = found
    limits = ranks.steelColumns if kind == "column" else ranks.steelBeams
    if not limits:
        return None
    profile = object_type.profile
    root = math.sqrt(ranks.steelReference / fy)
    values: dict[str, float] = {}
    shape = getattr(profile, "shape", "")
    if all(getattr(profile, k, None) for k in ("overallDepth", "overallWidth", "flangeThickness",
                                                "webThickness")):  # fmt: skip
        values["flange"] = profile.overallWidth / 2 / profile.flangeThickness / root
        values["web"] = (
            (profile.overallDepth - 2 * profile.flangeThickness) / profile.webThickness / root
        )
    elif getattr(profile, "wallThickness", None) and getattr(profile, "xDim", None):
        values["tube"] = max(profile.xDim, profile.yDim) / profile.wallThickness / root
    elif getattr(profile, "wallThickness", None) and getattr(profile, "radius", None):
        values["pipe"] = 2 * profile.radius / profile.wallThickness / root**2
    else:
        return None
    order = ranks.order
    rank = order[-1]
    for candidate in order[:-1]:
        rule = limits.get(candidate)
        if rule is None:
            continue
        if all(
            getattr(rule, key, None) is None or value <= getattr(rule, key) + 1e-9
            for key, value in values.items()
        ):
            rank = candidate
            break
    text = ", ".join(f"{k} {v:.1f}" for k, v in values.items())
    row = _check(
        f"Member rank {rank}" + _cite("steelRanks"),
        float(order.index(rank) + 1),
        float(len(order)),
        "",
        None,
        f"width-thickness ratios × √(F/{ranks.steelReference:g}): {text} ({shape or 'steel'})",
        flag=True,
    )
    row["rank"] = rank
    return row
