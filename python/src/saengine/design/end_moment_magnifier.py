"""Slender columns by the end moments and the member's P-δ magnifier (alpha 9 C20b; the pack's
``concreteMethods.columns.slenderness`` method ``endMomentMagnifier``, as GB 50010-2010
6.2.3-6.2.5 give it).

About each axis and in each combination, from the column's signed end moments (the first and
the last station of its pieces; M2 the larger in magnitude, M1/M2 positive in single
curvature):

- not needed where M1/M2 <= exemptRatio, N / (fc A) <= exemptAxial and lc / i <= a - b M1/M2
  (``exemptSlenderness``), lc the clear height between the supports (the slenderness's lu)
  and i the radius of gyration (h / √12 of a rectangle, D / 4 of a circle);
- else M = Cm ηns M2, Cm = cmBase + cmRatio M1/M2 >= cmMin, ηns = 1 + (lc / h)² ζc / (divisor
  (M2 / N + ea) / h0), ζc = zetaShare fc A / N <= 1, ea of the pack's least eccentricity; M2
  where Cm ηns < 1. The combination's points take at least M about that axis.

The sway (P-Δ) effects are the analysis's (a second-order run) or the parent method's moment
magnification of the sway storeys, as for the other packs. Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.design.tabulated_shear import _group, _paren


def rules() -> Any | None:
    """The pack's ``columns.slenderness`` of method ``endMomentMagnifier``, or None."""
    found = _group("columns")
    if found is None or getattr(found.slenderness, "method", None) != "endMomentMagnifier":
        return None
    return found.slenderness


def _radius(section: Any, depth: float) -> float:
    if section.profile.__class__.__name__ == "CircleProfile":
        return depth / 4
    return depth / math.sqrt(12)


def magnified(
    m1: float, m2: float, n: float, lc: float, depth: float, h0: float, area: float, fcd: float,
    radius: float, s: Any,
) -> tuple[float, float, float, bool]:  # fmt: skip
    """(M [N·mm], Cm, ηns, exempt) of one axis: M >= |M2|."""
    from saengine.design import design_strength

    big = abs(m2)
    if big <= 0 or n <= 0:
        return big, 1.0, 1.0, True
    ratio = m1 / m2 if m2 != 0 else 0.0
    a, b = s.exemptSlenderness
    if (
        ratio <= s.exemptRatio
        and n / (fcd * area) <= s.exemptAxial
        and lc / radius <= a - b * ratio
    ):
        return big, 1.0, 1.0, True
    cm = max(s.cmBase + s.cmRatio * ratio, s.cmMin)
    zeta = min(s.zetaShare * fcd * area / n, 1.0)
    ea = design_strength.eccentricity(depth)
    eta = 1 + (lc / depth) ** 2 * zeta / (s.divisor * (big / n + ea) / h0) if h0 > 0 else 1.0
    return max(cm * eta, 1.0) * big, cm, eta, False


def magnified_points(
    section: Any,
    slender: Any,
    pieces: list[Any],
    combinations: list[str],
    turned: bool,
    points: list[tuple[float, float, float, str, str]],
) -> tuple[list[tuple[float, float, float, str, str]], list[dict[str, Any]]]:
    """The demand points with the magnified moments and the slenderness rows (one per axis),
    in place of the moment magnification's (``slender``: the column's
    :class:`saengine.design.slender.ColumnSlenderness`)."""
    from saengine.design import design_strength
    from saengine.design.check import _check, _profile_forces

    s = rules()
    if not pieces:
        return points, []

    def order(p: Any) -> int:  # the pieces along the column: name#1, name#2 ...
        suffix = p.name.partition("#")[2]
        return int(suffix) if suffix.isdigit() else 1

    pieces = sorted(pieces, key=order)
    area = float(section.gross_area)
    fcd = design_strength.fcd(section.fc)
    lengths: dict[str, float] = {}
    for axis_result in slender.axes:
        info = (axis_result.check or {}).get("slenderness") or {}
        lengths[info.get("axis") or axis_result.axis] = float(info.get("lu") or 0.0)
    geometry = {
        "x": (
            float(section.depth),
            section.depth / 2 + max((abs(b.y) for b in section.bars), default=0.0),
        ),
        "y": (
            float(section.width),
            section.width / 2 + max((abs(b.x) for b in section.bars), default=0.0),
        ),
    }
    key = {"x": "Mx", "y": "My"}
    # Per combination: the signed end moments of each axis and the largest compression.
    ends: dict[int, dict[str, tuple[float, float]]] = {}
    axial: dict[int, float] = {}
    count = max((len(p.forces) for p in pieces), default=0)
    for c in range(count):
        first = _profile_forces(pieces[0], turned, pieces[0].forces[c])
        last = _profile_forces(pieces[-1], turned, pieces[-1].forces[c])
        per: dict[str, tuple[float, float]] = {}
        for axis, name in key.items():
            a_end = float(first[name][0])
            b_end = float(last[name][-1])
            per[axis] = (b_end, a_end) if abs(a_end) >= abs(b_end) else (a_end, b_end)
        ends[c] = per  # (M1, M2) by axis
        axial[c] = max(
            max(float(v) for v in _profile_forces(p, turned, p.forces[c])["P"]) for p in pieces
        )
    moments: dict[str, dict[str, float]] = {"x": {}, "y": {}}
    rows: list[dict[str, Any]] = []
    for axis in ("x", "y"):
        depth, h0 = geometry[axis]
        lc = lengths.get(axis, 0.0)
        radius = _radius(section, depth)
        governing = None
        for c in range(count):
            m1, m2 = ends[c][axis]
            m, cm, eta, exempt = magnified(m1, m2, axial[c], lc, depth, h0, area, fcd, radius, s)
            name = combinations[c] if c < len(combinations) else str(c)
            moments[axis][name] = max(moments[axis].get(name, 0.0), m)
            if governing is None or (not exempt and cm * eta > governing[1] * governing[2]):
                governing = (name, cm, eta, exempt, m1 / m2 if m2 else 0.0)
        if governing is None or lc <= 0:
            continue
        name, cm, eta, exempt, ratio = governing
        a, b = s.exemptSlenderness
        rows.append(
            _check(
                f"Slenderness about {axis}{_paren('slenderness')}",
                lc / radius,
                a - b * ratio,
                "",
                name,
                f"lc = {lc:.0f} mm, i = {radius:.0f} mm, M1/M2 = {ratio:.2f}: "
                + (
                    "the end moments' P-δ need not be added"
                    if exempt
                    else f"M = Cm ηns M2, Cm = {cm:.2f}, ηns = {eta:.3f}"
                ),
                flag=True,
            )
        )
    out = []
    for pu, mux, muy, combination, where in points:
        mux = max(mux, moments["x"].get(combination, 0.0)) if pu > 0 else mux
        muy = max(muy, moments["y"].get(combination, 0.0)) if pu > 0 else muy
        out.append((pu, mux, muy, combination, where))
    return out, rows
