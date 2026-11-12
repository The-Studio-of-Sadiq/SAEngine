"""Steel members by design resistances with partial factors, cross-section classes, buckling
curves and interaction factors: the member method ``bucklingCurves`` a code pack picks with
``steelLimitState.memberResistance`` (method ``crossSectionClasses``; alpha 9 C6, the Eurocodes
pack: EN 1993-1-1 with the plates of EN 1993-1-5), a method of the limit state steel table of
:mod:`saengine.design.steel.limit_state` (its χ of the buckling curves is shared). Every number
is the group's, every clause the table's ``clauses``.

What is checked, per member and enveloped over its combinations and stations:

- **Cross-section classes** 1-4 of each plate element by c/t against ε = √(235 / fy):
  internal parts in compression, in bending and in bending with compression (the plastic
  α of the web under N for classes 1 and 2, the elastic ψ for class 3), outstands, tubes and
  angles. Class 4 elements take their effective widths (ρ by λ̄p and kσ): Aeff under uniform
  compression and Weff in bending (the compression flange first, the web's ineffective zone
  between be1 = 0.4 beff and be2 = 0.6 beff), for I-sections, channels and rectangular hollow
  sections; other class 4 shapes Weff = ρ Wel (SAEngine practice).
- **Resistances of cross-sections**: tension Npl,Rd = A fy / γM0 and Nu,Rd = k Anet fu / γM2,
  compression Nc,Rd, bending Mc,Rd by the class (Wpl, Wel, Weff), shear Vpl,Rd = Av (fy/√3)
  / γM0 with the shear areas (η hw tw at least) and the shear buckling of slender webs (χw of
  a non-rigid end post, the flanges not counted), bending with shear (the reduced yield
  strength (1 - ρ) fy of the shear area above half of Vpl,Rd) and bending with axial force
  (MN of I- and hollow sections with the exponents of the biaxial criterion for classes 1 and
  2; the linear criterion otherwise).
- **Buckling resistance**: flexural buckling about both axes, torsional (doubly symmetric
  sections) and flexural-torsional (channels, tees) buckling from Ncr, χ by the curve of the
  shape (the selection table of the pack) with its imperfection factor α; single angles about
  their least axis.
- **Lateral-torsional buckling** of members in major-axis bending: Mcr by the C1 formula (load
  at the shear centre, k = kw = 1, C1 taken as the equivalent moment factor of the moment
  diagram of the segment between the brace points of the flange in compression), χLT by the
  general case or the case of rolled and equivalent welded sections (λ̄LT,0, β), as the pack
  picks; hollow sections are not susceptible (χLT = 1).
- **Members in bending and compression**: the two checks of the interaction with kyy, kyz, kzy,
  kzz by Annex B (method 2) or Annex A (method 1), as the pack picks; Cm from the moment
  diagram of the buckling segment (0.6 + 0.4 ψ of a linear diagram, at least the pack's least
  value; 1.0 for a diagram with transverse load, SAEngine practice).
- **Global analysis** (columns, a flag): αcr from the analysis's drift ratio Δ2nd / Δ1st when the
  run knows it, against the limit above which first-order analysis suffices.

E and G are the pack's (the calculations' values), fy is the material's with the pack's lower
yield strength of thick plates. Hollow sections of ERW (the run's option) are cold-formed.
Torsion, the shift eN of the effective centroid of class 4 sections and the slenderness
limits of the default pack are not part of the method: the run says so.

Units: mm, MPa, N, N·mm; reported in kN, kN·m.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.design.steel.properties import ShapeProperties

METHOD_ID = "bucklingCurves"
ROOT3 = math.sqrt(3.0)


# ───────────────────────────────────────── data ─────────────────────────────────────────


def table() -> Any | None:
    """The pack's ``steelLimitState.memberResistance`` when it is this method
    (:func:`saengine.design.steel.limit_state.member_resistance`, the one selector of the limit
    state steel methods), else None."""
    from saengine.design.steel.limit_state import member_resistance

    return member_resistance()


def active() -> bool:
    """Whether the pack in force designs steel members by this method."""
    return table() is not None


def _t() -> Any:
    found = table()
    if found is None:
        raise ValueError("the code pack does not design steel members by buckling curves")
    return found


def clause(key: str) -> str:
    """The pack's clause of ``key`` (``steelLimitState.clauses``) with its code's name."""
    from saengine.design.steel.limit_state import cite

    return cite(key)


def design_fy(shape: ShapeProperties, fy: float) -> tuple[float, str]:
    """fy of the calculations: the material's, lowered for plates thicker than the pack's
    limit (``thickPlates``: nominal fy, thickness, fy there), and its note."""
    t = max(
        (shape.dims.get(k, 0.0) for k in ("tf", "tw", "t")),
        default=0.0,
    )
    for nominal, above, lower in _t().thickPlates:
        if abs(fy - nominal) < 0.5 and t > above:
            return float(lower), (
                f"fy = {lower:g} MPa for t = {t:g} mm > {above:g} mm ({clause('material')})"
            )
    return fy, ""


def epsilon(fy: float) -> float:
    return math.sqrt(float(_t().classes.epsilonReference) / fy)


# ─────────────────────────────────── cross-section classes ───────────────────────────────────


@dataclass(frozen=True)
class Part:
    """One plate element: its kind, c and t, the class and the stress state it was classed
    under."""

    name: str
    kind: str  # "internal", "outstand", "tube", "angle"
    c: float
    t: float
    cls: int
    state: str
    limit: float  # the c/t limit of the class found (or of class 3 for class 4)

    def describe(self) -> str:
        ratio = self.c / self.t if self.t > 0 else 0.0
        return f"{self.name} c/t = {ratio:.1f} ({self.state}, limit {self.limit:.1f}): class {self.cls}"


def _by_limits(ratio: float, limits: Sequence[float]) -> tuple[int, float]:
    for i, lim in enumerate(limits):
        if ratio <= lim + 1e-9:
            return i + 1, lim
    return 4, limits[-1]


def _web_limits(alpha: float, psi: float, eps: float) -> tuple[float, float, float]:
    """The c/t limits of classes 1, 2, 3 of an internal part in bending and compression: α
    the compressed share (plastic), ψ the end stress ratio (elastic)."""
    c = _t().classes

    def plastic(row: Sequence[float]) -> float:
        a, b, k, d = row
        if alpha > 0.5:
            return a * eps / (b * alpha - k)
        return d * eps / max(alpha, 1e-6)

    a3, b3, c3, d3 = c.webClass3
    if psi > -1:
        third = a3 * eps / (b3 + c3 * psi)
    else:
        third = d3 * eps * (1 - psi) * math.sqrt(-psi)
    return plastic(c.webClass1), plastic(c.webClass2), third


def _internal(name: str, c_: float, t: float, eps: float, state: str) -> Part:
    c = _t().classes
    limits = {
        "compression": c.internalCompression,
        "bending": c.internalBending,
    }[state]
    cls, lim = _by_limits(c_ / t, [x * eps for x in limits])
    return Part(name, "internal", c_, t, cls, state, lim)


def _outstand(name: str, c_: float, t: float, eps: float) -> Part:
    cls, lim = _by_limits(c_ / t, [x * eps for x in _t().classes.outstandCompression])
    return Part(name, "outstand", c_, t, cls, "compression", lim)


def _flange_outstand(shape: ShapeProperties) -> float:
    d = shape.dims
    if shape.family == "I":
        return max((d["bf"] - d["tw"] - 2 * d.get("r", 0.0)) / 2, 0.0)
    if shape.family == "channel":
        return max(d["bf"] - d["tw"] - d.get("r", 0.0), 0.0)
    if shape.family == "tee":
        return max((d["bf"] - d["tw"] - 2 * d.get("r", 0.0)) / 2, 0.0)
    return 0.0


def _web(shape: ShapeProperties) -> tuple[float, float, int]:
    """(c, t, number of webs) of the web(s) parallel to the major axis' depth."""
    d = shape.dims
    if shape.family in ("I", "channel"):
        return d["h"], d["tw"], 1
    if shape.family == "rhs":
        return d["h"], d["t"], 2
    return 0.0, 1.0, 0


def classify(
    shape: ShapeProperties,
    fy: float,
    state: str = "compression",
    axis: str = "y",
    n_ed: float = 0.0,
    m_ed: float = 0.0,
) -> list[Part]:
    """The parts of ``shape`` and their classes under ``state``: "compression" (uniform),
    "bending" about ``axis`` ("y" major, "z" minor) or "combined" (compression ``n_ed`` [N] with
    major-axis bending ``m_ed`` [N·mm]: the web by α and ψ)."""
    eps = epsilon(fy)
    d = shape.dims
    lim = _t().classes
    parts: list[Part] = []
    fam = shape.family
    if fam in ("bar", "round"):
        return []
    if fam == "chs":
        cls, limit = _by_limits(d["D"] / d["t"], [x * eps**2 for x in lim.tubes])
        return [Part("wall", "tube", d["D"], d["t"], cls, "compression", limit)]
    if fam == "angle":
        h, b, t = max(d["d"], d["b"]), min(d["d"], d["b"]), d["t"]
        a1, a2 = lim.angle
        ok = h / t <= a1 * eps and (b + h) / (2 * t) <= a2 * eps
        return [Part("legs", "angle", h, t, 3 if ok else 4, "compression", a1 * eps)]
    if fam in ("I", "channel", "tee"):
        # Outstand flanges: in uniform compression, also in bending (the compression flange,
        # or the tips of minor-axis bending on the safe side).
        parts.append(_outstand("flange", _flange_outstand(shape), d["tf"], eps))
        if fam == "tee":
            # The stem as an outstand in compression (its tip may be: the safe side).
            parts.append(_outstand("stem", d["d"] - d["tf"], d["tw"], eps))
            return parts
    if fam == "rhs":
        b_flat = d["b"] if axis == "y" else d["h"]
        parts.append(_internal("flange", b_flat, d["t"], eps, "compression"))
    c_w, t_w, webs = _web(shape) if axis == "y" else (*_minor_web(shape), 1)
    if webs == 0:
        return parts
    if state == "compression":
        parts.append(_internal("web", c_w, t_w, eps, "compression"))
    elif state == "bending":
        if fam == "rhs" or axis == "y":
            parts.append(_internal("web", c_w, t_w, eps, "bending"))
        # minor-axis bending of I-sections and channels: the web is at the neutral axis.
    else:
        n = max(n_ed, 0.0)
        count = 2 if fam == "rhs" else 1
        alpha = min(1.0, max(0.0, 0.5 + n / (2 * count * c_w * t_w * fy)))
        sigma_n = n / shape.area
        sigma_m = abs(m_ed) * (c_w / 2) / shape.ix if shape.ix > 0 else 0.0
        top = sigma_n + sigma_m
        psi = (sigma_n - sigma_m) / top if top > 0 else 1.0
        l1, l2, l3 = _web_limits(alpha, psi, eps)
        cls, limit = _by_limits(c_w / t_w, [l1, l2, l3])
        parts.append(
            Part("web", "internal", c_w, t_w, cls, f"α = {alpha:.2f}, ψ = {psi:.2f}", limit)
        )
    return parts


def _minor_web(shape: ShapeProperties) -> tuple[float, float]:
    """RHS bent about the minor axis: its webs are the walls of width b."""
    d = shape.dims
    if shape.family == "rhs":
        return d["b"], d["t"]
    return 0.0, 1.0


def section_class(parts: Sequence[Part]) -> int:
    return max((p.cls for p in parts), default=1)


# ─────────────────────────────────── effective widths ───────────────────────────────────


def _k_sigma_internal(psi: float) -> float:
    p = _t().plates
    if psi >= 1:
        return float(p.kSigmaUniform)
    if psi > 0:
        a, b = p.kSigmaPositive
        return a / (b + psi)
    if psi > -1:
        a, b, c = p.kSigmaNegative
        return a - b * psi + c * psi**2
    return float(p.kSigmaBending)


def reduction_internal(c: float, t: float, eps: float, psi: float = 1.0) -> float:
    """ρ of an internal compression element (EN 1993-1-5 type, ψ the stress ratio)."""
    p = _t().plates
    k = _k_sigma_internal(psi)
    lam = (c / t) / (float(p.plateFactor) * eps * math.sqrt(k))
    a, b = p.internal
    la, lb = p.internalLimit
    if lam <= la + math.sqrt(max(lb - a * psi, 0.0)):
        return 1.0
    return min(1.0, (lam - a * (b + psi)) / lam**2)


def reduction_outstand(c: float, t: float, eps: float, tip: bool = False) -> float:
    """ρ of an outstand in uniform compression (``tip``: the tip in compression, the root at
    zero stress)."""
    p = _t().plates
    k = float(p.kSigmaOutstandTip if tip else p.kSigmaOutstand)
    lam = (c / t) / (float(p.plateFactor) * eps * math.sqrt(k))
    if lam <= float(p.outstandLimit):
        return 1.0
    return min(1.0, (lam - float(p.outstand)) / lam**2)


@dataclass
class _Rect:
    y0: float
    y1: float
    z0: float
    z1: float
    sign: float = 1.0  # -1: a hole

    @property
    def area(self) -> float:
        return self.sign * (self.y1 - self.y0) * (self.z1 - self.z0)


def _props(rects: Sequence[_Rect], axis: str) -> tuple[float, float, float, float]:
    """(A, centroid, I about it, the largest fibre distance) of the plates about ``axis``
    ("y": the horizontal axis, distances along the depth y; "z": across the width)."""
    area = sum(r.area for r in rects)
    if area <= 0:
        return 0.0, 0.0, 0.0, 1.0

    def span(r: _Rect) -> tuple[float, float, float]:
        if axis == "y":
            return r.y0, r.y1, r.z1 - r.z0
        return r.z0, r.z1, r.y1 - r.y0

    centroid = sum(r.area * (span(r)[0] + span(r)[1]) / 2 for r in rects) / area
    inertia = 0.0
    lo, hi = math.inf, -math.inf
    for r in rects:
        a, b, w = span(r)
        h = b - a
        mid = (a + b) / 2
        inertia += r.sign * (w * h**3 / 12 + w * h * (mid - centroid) ** 2)
        if r.sign > 0:
            lo, hi = min(lo, a), max(hi, b)
    return area, centroid, inertia, max(hi - centroid, centroid - lo)


def _plates(shape: ShapeProperties) -> list[_Rect]:
    """The shape's plates (y up the depth from the bottom, z across from the centre)."""
    d = shape.dims
    if shape.family == "I":
        bf, tf, tw, h = d["bf"], d["tf"], d["tw"], d["d"]
        return [
            _Rect(0, tf, -bf / 2, bf / 2),
            _Rect(tf, h - tf, -tw / 2, tw / 2),
            _Rect(h - tf, h, -bf / 2, bf / 2),
        ]
    if shape.family == "channel":
        bf, tf, tw, h = d["bf"], d["tf"], d["tw"], d["d"]
        return [_Rect(0, tf, 0, bf), _Rect(tf, h - tf, 0, tw), _Rect(h - tf, h, 0, bf)]
    if shape.family == "rhs":
        big_b, big_h, t = d["B"], d["H"], d["t"]
        return [
            _Rect(0, t, -big_b / 2, big_b / 2),
            _Rect(big_h - t, big_h, -big_b / 2, big_b / 2),
            _Rect(t, big_h - t, -big_b / 2, -big_b / 2 + t),
            _Rect(t, big_h - t, big_b / 2 - t, big_b / 2),
        ]
    return []


def effective_area(shape: ShapeProperties, fy: float) -> tuple[float, list[str]]:
    """Aeff of the section in uniform compression: each class 4 element less (1 - ρ) c t."""
    eps = epsilon(fy)
    parts = classify(shape, fy, "compression")
    lost = 0.0
    notes = []
    count = {"I": (4, 1), "channel": (2, 1), "tee": (2, 1), "rhs": (2, 2)}
    for p in parts:
        if p.cls < 4:
            continue
        if p.kind == "tube":
            raise ValueError(
                "class 4 circular hollow section: not covered (shell buckling of the code's "
                "shell part)"
            )
        if p.kind == "outstand":
            rho = reduction_outstand(p.c, p.t, eps)
            n = count.get(shape.family, (1, 1))[0] if p.name == "flange" else 1
        elif p.kind == "angle":
            rho = reduction_outstand(p.c, p.t, eps)
            n = 2
        else:
            rho = reduction_internal(p.c, p.t, eps)
            n = count.get(shape.family, (1, 1))[1] if p.name == "web" else 2
        lost += n * (1 - rho) * p.c * p.t
        notes.append(f"{p.name}: ρ = {rho:.3f}")
    return shape.area - lost, notes


def effective_modulus(shape: ShapeProperties, fy: float, axis: str) -> tuple[float, list[str]]:
    """Weff of the section bent about ``axis``: the compression flange's effective width, then
    the web's ineffective zone (ψ = -1 on the gross section) for I-sections, channels and
    rectangular hollow sections; other shapes ρ Wel with the least ρ of their class 4 parts
    (SAEngine practice)."""
    eps = epsilon(fy)
    d = shape.dims
    rects = _plates(shape)
    wel = shape.sx if axis == "y" else shape.sy
    parts = classify(shape, fy, "bending", axis)
    if not rects or (shape.family == "channel" and axis == "z"):
        rhos = [
            reduction_outstand(p.c, p.t, eps, tip=True)
            if p.kind in ("outstand", "angle")
            else reduction_internal(p.c, p.t, eps, -1.0 if p.name == "web" else 1.0)
            for p in parts
            if p.cls == 4
        ]
        rho = min(rhos, default=1.0)
        return wel * rho, [f"Weff = ρ Wel, ρ = {rho:.3f} (SAEngine practice)"]
    notes: list[str] = []
    holes: list[_Rect] = []
    flange = next((p for p in parts if p.name == "flange"), None)
    web = next((p for p in parts if p.name == "web"), None)
    if axis == "y":
        top = d["d"] if shape.family in ("I", "channel") else d["H"]
        tf = d.get("tf", d.get("t", 0.0))
        if flange is not None and flange.cls == 4:
            if shape.family == "rhs":
                rho = reduction_internal(flange.c, flange.t, eps)
                gap = (1 - rho) * flange.c
                holes.append(_Rect(top - tf, top, -gap / 2, gap / 2, -1))
            else:
                rho = reduction_outstand(flange.c, flange.t, eps)
                gap = (1 - rho) * flange.c
                if shape.family == "I":
                    bf = d["bf"]
                    holes += [
                        _Rect(top - tf, top, -bf / 2, -bf / 2 + gap, -1),
                        _Rect(top - tf, top, bf / 2 - gap, bf / 2, -1),
                    ]
                else:
                    holes.append(_Rect(top - tf, top, d["bf"] - gap, d["bf"], -1))
            notes.append(f"compression flange ρ = {rho:.3f}")
        if web is not None and web.cls == 4:
            rho = reduction_internal(web.c, web.t, eps, -1.0)
            bc = web.c / 2
            beff = rho * bc
            be1 = 0.4 * beff
            gap = bc - beff
            y_top = top - tf - (d.get("r", 0.0) if shape.family != "rhs" else 0.0)
            hole_top, hole_bottom = y_top - be1, y_top - be1 - gap
            if shape.family == "rhs":
                big_b, t = d["B"], d["t"]
                holes += [
                    _Rect(hole_bottom, hole_top, -big_b / 2, -big_b / 2 + t, -1),
                    _Rect(hole_bottom, hole_top, big_b / 2 - t, big_b / 2, -1),
                ]
            else:
                z0 = -d["tw"] / 2 if shape.family == "I" else 0.0
                holes.append(_Rect(hole_bottom, hole_top, z0, z0 + d["tw"], -1))
            notes.append(f"web ρ = {rho:.3f} (ψ = -1)")
    else:
        if shape.family == "I" and flange is not None and flange.cls == 4:
            rho = reduction_outstand(flange.c, flange.t, eps, tip=True)
            gap = (1 - rho) * flange.c
            bf, tf, h = d["bf"], d["tf"], d["d"]
            holes += [
                _Rect(0, tf, bf / 2 - gap, bf / 2, -1),
                _Rect(h - tf, h, bf / 2 - gap, bf / 2, -1),
            ]
            notes.append(f"flange tips ρ = {rho:.3f}")
        elif shape.family == "rhs":
            big_b, big_h, t = d["B"], d["H"], d["t"]
            if flange is not None and flange.cls == 4:
                rho = reduction_internal(flange.c, flange.t, eps)
                gap = (1 - rho) * flange.c
                holes.append(
                    _Rect(big_h / 2 - gap / 2, big_h / 2 + gap / 2, big_b / 2 - t, big_b / 2, -1)
                )
                notes.append(f"compression wall ρ = {rho:.3f}")
            if web is not None and web.cls == 4:
                rho = reduction_internal(web.c, web.t, eps, -1.0)
                bc = web.c / 2
                gap = bc - rho * bc
                z_top = big_b / 2 - t - 0.4 * rho * bc
                holes += [
                    _Rect(0, t, z_top - gap, z_top, -1),
                    _Rect(big_h - t, big_h, z_top - gap, z_top, -1),
                ]
                notes.append(f"webs ρ = {rho:.3f} (ψ = -1)")
    if not holes:
        return wel, notes
    _a, _c, inertia, reach = _props([*rects, *holes], axis)
    return inertia / reach, notes


# ─────────────────────────────────── the member's values ───────────────────────────────────


def chi(lam: float, alpha: float, plateau: float, beta: float = 1.0) -> float:
    """χ = 1 / (Φ + √(Φ² - β λ̄²)) <= 1, Φ = 0.5 [1 + α (λ̄ - λ̄0) + β λ̄²] (β = 1: the flexural
    buckling curves; also the aluminium curves with their λ̄0)."""
    if beta == 1.0:  # the flexural buckling curves: the limit state method's χ (C9)
        from saengine.design.steel.limit_state import chi as curve_chi

        return curve_chi(lam, alpha, plateau)
    if lam <= plateau:
        return 1.0
    phi = 0.5 * (1 + alpha * (lam - plateau) + beta * lam**2)
    root = phi**2 - beta * lam**2
    if root <= 0:
        return 1.0
    return min(1.0, 1.0 / (phi + math.sqrt(root)))


def _family(shape: ShapeProperties, cold_formed: bool) -> str:
    return {
        "I": "rolledI",
        "channel": "channel",
        "tee": "tee",
        "angle": "angle",
        "bar": "solid",
        "round": "solid",
        "rhs": "coldHollow" if cold_formed else "hotHollow",
        "chs": "coldHollow" if cold_formed else "hotHollow",
    }[shape.family]


def curves(shape: ShapeProperties, fy: float, cold_formed: bool) -> tuple[str, str]:
    """(curve about the major axis, curve about the minor axis) from the pack's selection."""
    t = _t()
    fam = _family(shape, cold_formed)
    d = shape.dims
    h = d.get("d", d.get("H", d.get("D", 0.0)))
    b = d.get("bf", d.get("B", d.get("D", 1.0)))
    tf = d.get("tf", d.get("t", 0.0))
    ratio = h / b if b > 0 else 1.0
    high = fy >= float(t.highFrom) - 1e-9
    for row in t.curves:
        if row.family != fam:
            continue
        if row.depthWidthAbove is not None and not ratio > row.depthWidthAbove:
            continue
        if row.depthWidthMax is not None and not ratio <= row.depthWidthMax:
            continue
        if row.flangeMax is not None and not tf <= row.flangeMax:
            continue
        if row.flangeAbove is not None and not tf > row.flangeAbove:
            continue
        if high:
            return row.yHigh or row.y, row.zHigh or row.z
        return row.y, row.z
    return "d", "d"


def _ltb_curve(shape: ShapeProperties, method: str) -> str:
    rows = _t().lateralTorsional.general if method == "general" else _t().lateralTorsional.rolled
    d = shape.dims
    fam = "rolledI" if shape.family == "I" else "other"
    ratio = d.get("d", 1.0) / d.get("bf", 1.0) if shape.family == "I" else 0.0
    for row in rows:
        if row.family != fam:
            continue
        if row.depthWidthMax is not None and ratio > row.depthWidthMax:
            continue
        return row.curve
    return "d"


def critical_moment(shape: ShapeProperties, e: float, g: float, length: float, c1: float) -> float:
    """Mcr [N·mm] = C1 π² E Iz / L² √(Iw/Iz + L² G It / (π² E Iz)) (load at the shear centre,
    k = kw = 1) of the minor inertia Iz (the profile's iy) over ``length`` [mm]."""
    if length <= 0:
        return math.inf
    iz = shape.iy
    if iz <= 0:
        return math.inf
    term = shape.cw / iz + length**2 * g * shape.j / (math.pi**2 * e * iz)
    return c1 * math.pi**2 * e * iz / length**2 * math.sqrt(max(term, 0.0))


@dataclass
class Section:
    """What the checks need of the member's cross-section: classes, areas, moduli, shear."""

    shape: ShapeProperties
    fy: float
    fu: float
    e: float
    g: float
    cold_formed: bool
    compression_class: int = 1
    compression_parts: list[Part] = field(default_factory=list)
    bending_class: dict[str, int] = field(default_factory=dict)
    area_eff: float = 0.0
    w: dict[str, float] = field(default_factory=dict)  # by class: the modulus of bending
    w_eff: dict[str, float] = field(default_factory=dict)
    av: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, shape: ShapeProperties, fy: float, fu: float, cold_formed: bool) -> Section:
        t = _t()
        fy_d, note = design_fy(shape, fy)
        s = cls(shape, fy_d, fu, float(t.modulus), float(t.shearModulus), cold_formed)
        if note:
            s.notes.append(note)
        s.compression_parts = classify(shape, fy_d, "compression")
        s.compression_class = section_class(s.compression_parts)
        s.area_eff = shape.area
        if s.compression_class == 4:
            s.area_eff, extra = effective_area(shape, fy_d)
            s.notes.append("Aeff: " + ", ".join(extra))
        for axis in ("y", "z"):
            parts = classify(shape, fy_d, "bending", axis)
            k = section_class(parts)
            if k == 4 and shape.family == "chs":
                raise ValueError(
                    "class 4 circular hollow section: not covered (shell buckling of the "
                    "code's shell part)"
                )
            s.bending_class[axis] = k
            s.w[axis] = s.modulus(axis, k)
        s.av = {"y": s.shear_area("y"), "z": s.shear_area("z")}
        return s

    def modulus(self, axis: str, k: int) -> float:
        """W of bending about ``axis`` for class ``k``: Wpl (1, 2), Wel (3), Weff (4)."""
        sh = self.shape
        if k <= 2:
            return sh.zx if axis == "y" else sh.zy
        if k == 3:
            return sh.sx if axis == "y" else sh.sy
        if axis not in self.w_eff:
            self.w_eff[axis], extra = effective_modulus(sh, self.fy, axis)
            self.notes.append(f"Weff,{axis}: " + ", ".join(extra))
        return self.w_eff[axis]

    def shear_area(self, axis: str) -> float:
        """Av of shear along the depth (``"y"``, the major axis) or the width (``"z"``)."""
        sh, d = self.shape, self.shape.dims
        eta = float(_t().shear.eta)
        a = sh.area
        match sh.family:
            case "I":
                if axis == "y":
                    hw = d["d"] - 2 * d["tf"]
                    return max(
                        a - 2 * d["bf"] * d["tf"] + (d["tw"] + 2 * d.get("r", 0.0)) * d["tf"],
                        eta * hw * d["tw"],
                    )
                return 2 * d["bf"] * d["tf"]
            case "channel":
                if axis == "y":
                    return a - 2 * d["bf"] * d["tf"] + (d["tw"] + d.get("r", 0.0)) * d["tf"]
                return 2 * d["bf"] * d["tf"]
            case "tee":
                if axis == "y":
                    return 0.9 * (a - d["bf"] * d["tf"])
                return d["bf"] * d["tf"]
            case "rhs":
                big_b, big_h = d["B"], d["H"]
                return a * (big_h if axis == "y" else big_b) / (big_b + big_h)
            case "chs":
                return 2 * a / math.pi
            case "angle":
                leg = d["d"] if axis == "y" else d["b"]
                return leg * d["t"]
        return a

    def shear_resistance(self, axis: str) -> tuple[float, str]:
        """Vc,Rd [N] along ``axis``: Vpl,Rd, or the shear buckling resistance of a slender web
        (χw fy hw t / (√3 γM1), the flanges not counted) when smaller."""
        t = _t()
        vpl = self.av[axis] * self.fy / ROOT3 / float(t.gammaM0)
        note = f"Vpl,Rd = Av (fy/√3) / γM0, Av = {self.av[axis]:.0f} mm²"
        d = self.shape.dims
        if axis == "y" and self.shape.family in ("I", "channel", "rhs"):
            tw = d["tw"] if self.shape.family != "rhs" else d["t"]
            hw = (d["d"] - 2 * d["tf"]) if self.shape.family != "rhs" else d["h"]
            webs = 2 if self.shape.family == "rhs" else 1
            eps = epsilon(self.fy)
            s = t.shear
            if hw / tw > float(s.bucklingLimit) * eps / float(s.eta):
                lam = hw / (float(s.plateFactor) * tw * eps * math.sqrt(float(s.kTau)))
                chi_w = min(float(s.eta), float(s.chiW) / lam)
                vb = webs * chi_w * self.fy * hw * tw / (ROOT3 * float(t.gammaM1))
                if vb < vpl:
                    return vb, (
                        f"shear buckling: hw/tw = {hw / tw:.1f} > {float(s.bucklingLimit):g} ε/η, "
                        f"λ̄w = {lam:.2f}, χw = {chi_w:.3f} (non-rigid end post, flanges not "
                        f"counted; {clause('shearBuckling')})"
                    )
        return vpl, note


# ─────────────────────────────────── the member checks ───────────────────────────────────


@dataclass
class _Worst:
    utilisation: float = -1.0
    demand: float = 0.0
    capacity: float = 0.0
    combination: str | None = None
    note: str = ""
    clause: str = ""

    def offer(self, u, demand, capacity, combination, note, ref) -> None:
        if u > self.utilisation:
            self.utilisation, self.demand, self.capacity = u, demand, capacity
            self.combination, self.note, self.clause = combination, note, ref


def _row(name: str, w: _Worst, unit: str, scale: float, flag: bool = False) -> dict[str, Any]:
    u = w.utilisation
    u = round(float(u), 3) if math.isfinite(u) else 99.0
    return {
        "name": name,
        "demand": round(float(w.demand) / scale, 2),
        "capacity": round(float(w.capacity) / scale, 2),
        "unit": unit,
        "utilisation": u,
        "combination": w.combination,
        "ok": bool(u <= 1.0),
        "note": w.note,
        "flag": flag,
        "clause": w.clause,
    }


def _ratio(demand: float, capacity: float) -> float:
    if capacity > 0:
        return demand / capacity
    return 0.0 if demand <= 0 else math.inf


def _psi(s: np.ndarray, m: np.ndarray, start: float, end: float) -> tuple[float, bool]:
    """(ψ, linear) of the segment [start, end] of the diagram ``m``: ψ the smaller end moment
    over the larger, positive in single curvature (the moments in one sign convention along
    the member), and whether the diagram is linear between the ends."""
    inside = (s >= start - 1e-9) & (s <= end + 1e-9)
    if inside.sum() < 2:
        return 1.0, True
    m1, m2 = float(np.interp(start, s, m)), float(np.interp(end, s, m))
    ss, mm = s[inside], m[inside]
    peak = float(np.max(np.abs(mm)))
    if peak <= 0:
        return 1.0, True
    line = m1 + (m2 - m1) * (ss - start) / max(end - start, 1e-12)
    linear = float(np.max(np.abs(mm - line))) <= 0.02 * peak
    small, large = sorted((m1, m2), key=abs)
    psi = small / large if abs(large) > 0 else 1.0
    return max(-1.0, min(1.0, psi)), linear


def equivalent_moment(s: np.ndarray, m: np.ndarray, start: float, end: float) -> float:
    """Cm of Annex B: 0.6 + 0.4 ψ of a linear diagram, at least the pack's least value; 1.0 with
    transverse load (SAEngine practice, on the safe side)."""
    psi, linear = _psi(s, m, start, end)
    if not linear:
        return 1.0
    return max(float(_t().interaction.annexB.cmMin), 0.6 + 0.4 * psi)


def _c1(s: np.ndarray, m: np.ndarray, start: float, end: float) -> float:
    from saengine.design.steel.lengths import cb_from_diagram

    return min(float(_t().lateralTorsional.c1Max), cb_from_diagram(s, m, start, end))


def _torsional_susceptible(shape: ShapeProperties) -> bool:
    return shape.family not in ("rhs", "chs", "round")


def _ncr_modes(sec: Section, lx: float, ly: float, lz: float) -> list[tuple[float, str, str]]:
    """(Ncr [N], mode, axis of its curve) of the buckling modes."""
    sh, e, g = sec.shape, sec.e, sec.g
    out: list[tuple[float, str, str]] = []
    if sh.family == "angle":
        length = max(lx, ly)
        iv = sh.iz if sh.iz > 0 else min(sh.ix, sh.iy)
        out.append((math.pi**2 * e * iv / length**2, "flexural buckling about v-v", "v"))
        return out
    out.append(
        (math.pi**2 * e * sh.ix / lx**2 if lx > 0 else math.inf, "flexural buckling about y-y", "y")
    )
    out.append(
        (math.pi**2 * e * sh.iy / ly**2 if ly > 0 else math.inf, "flexural buckling about z-z", "z")
    )
    if sh.family in ("I", "channel", "tee"):
        torsion = g * sh.j + (math.pi**2 * e * sh.cw / lz**2 if lz > 0 else 0.0)
        ncr_t = torsion / sh.ro2
        if sh.family == "I":
            out.append((ncr_t, "torsional buckling", "z"))
        else:
            ns = out[0][0] if sh.family == "channel" else out[1][0]
            h = sh.big_h
            ft = (
                (ns + ncr_t)
                / (2 * h)
                * (1 - math.sqrt(max(0.0, 1 - 4 * ns * ncr_t * h / (ns + ncr_t) ** 2)))
            )
            out.append((ft, "flexural-torsional buckling", "z"))
    return out


def _ncr_t(sec: Section, lz: float) -> float:
    sh = sec.shape
    torsion = sec.g * sh.j + (math.pi**2 * sec.e * sh.cw / lz**2 if lz > 0 else 0.0)
    return torsion / sh.ro2


@dataclass
class Buckling:
    chi_y: float
    chi_z: float
    lam_y: float
    lam_z: float
    ncr_y: float
    ncr_z: float
    ncr_t: float
    chi: float  # the least, for Nb,Rd
    mode: str
    note: str


def buckling(sec: Section, lx: float, ly: float, lz: float) -> Buckling:
    """χ of the member's modes over the buckling lengths [mm]: flexural about y-y (profile x)
    and z-z (profile y), torsional and flexural-torsional with the z-z curve."""
    t = _t()
    cy, cz = curves(sec.shape, sec.fy, sec.cold_formed)
    nrk = sec.area_eff * sec.fy
    modes = _ncr_modes(sec, lx, ly, lz)
    plateau = float(t.plateau)
    by_axis: dict[str, tuple[float, float, float]] = {}
    least = (math.inf, "", 1.0, 0.0, "")
    for ncr, mode, axis in modes:
        curve = cy if axis == "y" else cz
        lam = math.sqrt(nrk / ncr) if math.isfinite(ncr) and ncr > 0 else 0.0
        x = chi(lam, float(t.imperfection[curve]), plateau)
        if axis in ("y", "z") and mode.startswith("flexural buckling"):
            by_axis[axis] = (x, lam, ncr)
        if axis == "v":
            by_axis["y"] = by_axis["z"] = (x, lam, ncr)
        if x < least[0]:
            least = (x, mode, lam, ncr, curve)
    xy, ly_, ny = by_axis.get("y", (1.0, 0.0, math.inf))
    xz, lz_, nz = by_axis.get("z", (1.0, 0.0, math.inf))
    x, mode, lam, ncr, curve = least
    # the torsional modes count in the minor-axis check (the conservative choice)
    xz = min(xz, x)
    note = (
        f"{mode}: Ncr = {ncr / 1e3:.0f} kN, λ̄ = {lam:.2f}, curve {curve} "
        f"(α = {float(t.imperfection[curve]):g}), χ = {x:.3f}"
    )
    return Buckling(xy, xz, ly_, lz_, ny, nz, _ncr_t(sec, lz), x, mode, note)


def lateral_torsional(
    sec: Section, length: float, c1: float, w: float
) -> tuple[float, float, float, str]:
    """(χLT, λ̄LT, Mcr, note) over the unbraced ``length`` [mm] with C1 and the modulus ``w``."""
    t = _t()
    lt = t.lateralTorsional
    sh = sec.shape
    if not _torsional_susceptible(sh) or length <= 0:
        return 1.0, 0.0, math.inf, "hollow section: not susceptible to lateral-torsional buckling"
    mcr = critical_moment(sh, sec.e, sec.g, length, c1)
    lam = math.sqrt(w * sec.fy / mcr) if math.isfinite(mcr) and mcr > 0 else 0.0
    method = lt.method if sh.family == "I" else "general"
    curve = _ltb_curve(sh, method)
    alpha = float(t.imperfection[curve])
    if method == "rolled":
        plateau, beta = float(lt.plateauRolled), float(lt.beta)
        x = chi(lam, alpha, plateau, beta)
        if lam > 0:
            x = min(x, 1.0 / lam**2)
        if lt.modification == "inverseRootC1" and lam > plateau:
            kc = 1.0 / math.sqrt(max(c1, 1.0))
            f = min(1.0, 1 - float(lt.fA) * (1 - kc) * (1 - 2 * (lam - float(lt.fB)) ** 2))
            x = min(1.0, x / f, 1.0 / lam**2)
        what = f"rolled case, λ̄LT,0 = {plateau:g}, β = {beta:g}"
    else:
        plateau = float(lt.plateauGeneral)
        x = chi(lam, alpha, plateau)
        what = "general case"
    note = (
        f"Mcr = {mcr / 1e6:.1f} kN·m (C1 = {c1:.2f}, L = {length:.0f} mm), λ̄LT = {lam:.2f}, "
        f"curve {curve}, {what}, χLT = {x:.3f}"
    )
    return x, lam, mcr, note


def _mn(sec: Section, n_ed: float, mpl_y: float, mpl_z: float) -> tuple[float, float, float, float]:
    """(MN,y,Rd, MN,z,Rd, exponent α, exponent β) of classes 1 and 2 under ``n_ed`` [N]."""
    sh, d = sec.shape, sec.shape.dims
    t = _t()
    npl = sh.area * sec.fy / float(t.gammaM0)
    n = min(abs(n_ed) / npl, 1.0) if npl > 0 else 1.0
    if sh.family == "I":
        a = min((sh.area - 2 * d["bf"] * d["tf"]) / sh.area, 0.5)
        hw = d["d"] - 2 * d["tf"]
        web_fy = hw * d["tw"] * sec.fy / float(t.gammaM0)
        my = (
            mpl_y
            if (n <= 0.25 and abs(n_ed) <= 0.5 * web_fy)
            else min(mpl_y, mpl_y * (1 - n) / (1 - 0.5 * a))
        )
        if abs(n_ed) <= web_fy or n <= a:
            mz = mpl_z
        else:
            mz = mpl_z * (1 - ((n - a) / (1 - a)) ** 2)
        return my, max(mz, 0.0), 2.0, max(1.0, 5 * n)
    if sh.family == "rhs":
        aw = min((sh.area - 2 * d["B"] * d["t"]) / sh.area, 0.5)
        af = min((sh.area - 2 * d["H"] * d["t"]) / sh.area, 0.5)
        my = min(mpl_y, mpl_y * (1 - n) / (1 - 0.5 * aw))
        mz = min(mpl_z, mpl_z * (1 - n) / (1 - 0.5 * af))
        ex = min(6.0, 1.66 / max(1 - 1.13 * n**2, 1e-6)) if n < 0.94 else 6.0
        return my, mz, ex, ex
    if sh.family == "chs":
        f = max(1 - n**1.7, 0.0)
        return mpl_y * f, mpl_z * f, 2.0, 2.0
    return 0.0, 0.0, 0.0, 0.0  # the linear criterion


def check_member(
    shape: ShapeProperties,
    steel: Any,
    stations: Sequence[Any],
    lengths: Any,
    kind: str,
    options: Any,
) -> list[dict[str, Any]]:
    """The checks of one steel member by the method (the format of
    :func:`saengine.design.steel.members.check_member`)."""
    t = _t()
    g0, g1, g2 = float(t.gammaM0), float(t.gammaM1), float(t.gammaM2)
    cold = bool(getattr(options, "erw", True))
    sec = Section.of(shape, steel.fy, steel.fu, cold)
    fy = sec.fy
    stability = getattr(options, "stability", None)
    unit_k = getattr(stability, "unit_k", None)
    a = shape.area
    npl_rd = a * fy / g0
    nu_rd = float(t.netTension) * float(getattr(options, "net_ratio", 1.0)) * a * steel.fu / g2
    nc_rd = sec.area_eff * fy / g0
    vy_rd, vy_note = sec.shear_resistance("y")
    vz_rd, vz_note = sec.shear_resistance("z")
    sec.av["y"] * fy / ROOT3 / g0
    sec.av["z"] * fy / ROOT3 / g0
    interaction = t.interaction
    reduction_from = float(t.shear.reductionFrom)
    d = shape.dims

    buckling_cache: dict[tuple[float, float, float], Buckling] = {}
    ltb_cache: dict[tuple[float, float, float], tuple[float, float, float, str]] = {}
    class_cache: dict[tuple[int, int], int] = {}

    def buck(lx: float, ly: float, lz: float) -> Buckling:
        key = (round(lx, 1), round(ly, 1), round(lz, 1))
        if key not in buckling_cache:
            buckling_cache[key] = buckling(sec, lx, ly, lz)
        return buckling_cache[key]

    def ltb(length: float, c1: float, w: float) -> tuple[float, float, float, str]:
        key = (round(length, 1), round(c1, 3), round(w, 0))
        if key not in ltb_cache:
            ltb_cache[key] = lateral_torsional(sec, length, c1, w)
        return ltb_cache[key]

    def combined_class(n_ed: float, m_ed: float) -> int:
        if n_ed <= 0:
            return sec.bending_class["y"]
        key = (round(n_ed / max(npl_rd, 1.0) * 200), round(abs(m_ed) / 1e5))
        if key not in class_cache:
            class_cache[key] = section_class(classify(shape, fy, "combined", "y", n_ed, m_ed))
        return class_cache[key]

    worst = {
        k: _Worst()
        for k in ("ty", "tr", "nc", "nb", "my", "mz", "ltb", "vy", "vz", "nm", "b61", "b62")
    }
    tensioned = compressed = False
    method_name = "Annex B" if interaction.method == "annexB" else "Annex A"
    for st in stations:
        s = np.asarray(st.s, dtype=float)
        for k in range(len(s)):
            p = float(st.P[k])
            where = st.where[k]
            kx, lx, _ = lengths.effective("x", float(s[k]), unit_k)
            ky, ly, _ = lengths.effective("y", float(s[k]), unit_k)
            kz = lengths.k.get("z", 1.0) if unit_k is None else unit_k
            mx, my = float(st.Mx[k]), float(st.My[k])
            vy, vz = abs(float(st.Vy[k])), abs(float(st.Vx[k]))
            # shear and the reduced moment resistance
            worst["vy"].offer(
                _ratio(vy, vy_rd), vy, vy_rd, st.combination, f"{vy_note}; {where}", clause("shear")
            )
            worst["vz"].offer(
                _ratio(vz, vz_rd), vz, vz_rd, st.combination, f"{vz_note}; {where}", clause("shear")
            )
            cls_here = combined_class(p, mx) if p > 0 else sec.bending_class["y"]
            wy = sec.modulus("y", cls_here)
            wz = sec.w["z"]
            mcy = wy * fy / g0
            mcz = wz * fy / g0
            rho_y = (2 * vy / vy_rd - 1) ** 2 if vy > reduction_from * vy_rd else 0.0
            rho_z = (2 * vz / vz_rd - 1) ** 2 if vz > reduction_from * vz_rd else 0.0
            shear_note = ""
            if rho_y > 0:
                if shape.family == "I" and cls_here <= 2:
                    aw = (d["d"] - 2 * d["tf"]) * d["tw"]
                    mcy = min(mcy, (wy - rho_y * aw**2 / (4 * d["tw"])) * fy / g0)
                else:
                    mcy *= 1 - rho_y
                shear_note = (
                    f"; VEd > {reduction_from:g} Vpl,Rd: ρ = {rho_y:.3f} ({clause('bendingShear')})"
                )
            if rho_z > 0:
                mcz *= 1 - rho_z
            worst["my"].offer(
                _ratio(abs(mx), mcy), abs(mx), mcy, st.combination,
                f"class {cls_here}, Mc,Rd = W fy / γM0, W = {wy / 1e3:.0f}·10³ mm³{shear_note}; {where}",
                clause("bending"),
            )  # fmt: skip
            worst["mz"].offer(
                _ratio(abs(my), mcz), abs(my), mcz, st.combination,
                f"class {sec.bending_class['z']}, W = {wz / 1e3:.0f}·10³ mm³; {where}",
                clause("bending"),
            )  # fmt: skip
            # lateral-torsional buckling: the segment of the flange in compression
            top = mx < 0
            segs = (lengths.ltb_top if top else lengths.ltb_bottom).around_all(float(s[k]))
            best = (1.0, 0.0, math.inf, "no moment", 1.0)
            if abs(mx) > 0 and segs:
                found = []
                for a0, b0, free in segs:
                    seg_len = (b0 - a0) * 1e3 * (2.0 if free else 1.0)
                    c1 = 1.0 if free else _c1(s, np.asarray(st.Mx, dtype=float), a0, b0)
                    found.append((*ltb(seg_len, c1, wy), c1))
                best = min(found, key=lambda f: f[0])
            chi_lt, lam_lt, _mcr, lt_note, c1_here = best
            mb_rd = chi_lt * wy * fy / g1
            if abs(mx) > 0 and _torsional_susceptible(shape):
                worst["ltb"].offer(
                    _ratio(abs(mx), mb_rd), abs(mx), mb_rd, st.combination,
                    f"Mb,Rd = χLT W fy / γM1, {lt_note}; {where}", clause("lateralTorsional"),
                )  # fmt: skip
            if p < 0:
                tensioned = True
                tn = -p
                worst["ty"].offer(
                    _ratio(tn, npl_rd),
                    tn,
                    npl_rd,
                    st.combination,
                    f"Npl,Rd = A fy / γM0; {where}",
                    clause("tension"),
                )
                worst["tr"].offer(
                    _ratio(tn, nu_rd), tn, nu_rd, st.combination,
                    f"Nu,Rd = {float(t.netTension):g} Anet fu / γM2, Anet = {getattr(options, 'net_ratio', 1.0):g} A; {where}",
                    clause("tension"),
                )  # fmt: skip
            # bending and axial force on the cross-section
            n_abs = abs(p)
            n_rd = nc_rd if p > 0 else min(npl_rd, nu_rd)
            mpl_y = mcy
            mpl_z = mcz
            if (
                cls_here <= 2
                and sec.bending_class["z"] <= 2
                and shape.family in ("I", "rhs", "chs")
            ):
                mny, mnz, ea, eb = _mn(sec, p, mpl_y, mpl_z)
                ratio = (
                    _ratio(abs(mx), mny) ** ea if mny > 0 else (0 if mx == 0 else math.inf)
                ) + (_ratio(abs(my), mnz) ** eb if mnz > 0 else (0 if my == 0 else math.inf))
                nm_note = (
                    f"(My/MN,y)^{ea:.2f} + (Mz/MN,z)^{eb:.2f}: MN,y = {mny / 1e6:.1f}, MN,z = "
                    f"{mnz / 1e6:.1f} kN·m, n = {n_abs / max(npl_rd, 1.0):.2f}"
                )
            else:
                ratio = _ratio(n_abs, n_rd) + _ratio(abs(mx), mcy) + _ratio(abs(my), mcz)
                nm_note = "NEd/NRd + My/My,Rd + Mz/Mz,Rd (linear)"
            worst["nm"].offer(
                ratio, ratio, 1.0, st.combination, f"{nm_note}; {where}", clause("bendingAxial")
            )
            if p <= 0:
                continue
            compressed = True
            b = buck(kx * lx, ky * ly, kz * ly)
            nb_rd = b.chi * nc_rd * g0 / g1
            worst["nc"].offer(
                _ratio(p, nc_rd), p, nc_rd, st.combination,
                f"class {sec.compression_class}, Nc,Rd = {'Aeff' if sec.compression_class == 4 else 'A'} fy / γM0; {where}",
                clause("compression"),
            )  # fmt: skip
            worst["nb"].offer(
                _ratio(p, nb_rd), p, nb_rd, st.combination,
                f"Nb,Rd = χ {'Aeff' if sec.compression_class == 4 else 'A'} fy / γM1, {b.note}, "
                f"Lcr = {kx * lx:.0f} / {ky * ly:.0f} mm; {where}",
                clause("buckling"),
            )  # fmt: skip
            # the interaction of the member (6.3.3)
            xa, xb, _ = lengths.x.around(float(s[k]))
            ya, yb, _ = lengths.y.around(float(s[k]))
            mx_arr = np.asarray(st.Mx, dtype=float)
            my_arr = np.asarray(st.My, dtype=float)
            nrk = sec.area_eff * fy
            myrk, mzrk = wy * fy, wz * fy
            chi_lt_i = chi_lt if _torsional_susceptible(shape) else 1.0
            if interaction.method == "annexA" and interaction.annexA is not None:
                kyy, kyz, kzy, kzz, k_note = _annex_a(
                    sec, b, p, mx, my, chi_lt_i, lam_lt, c1_here, cls_here,
                    (s, mx_arr, xa, xb), (s, my_arr, ya, yb), kz * ly,
                )  # fmt: skip
            else:
                kyy, kyz, kzy, kzz, k_note = _annex_b(
                    sec, b, p, cls_here, (s, mx_arr, xa, xb), (s, my_arr, ya, yb),
                    segs and (s, mx_arr, segs[0][0], segs[0][1]),
                )  # fmt: skip
            r61 = (
                p / (b.chi_y * nrk / g1)
                + kyy * abs(mx) / (chi_lt_i * myrk / g1)
                + kyz * abs(my) / (mzrk / g1)
            )
            r62 = (
                p / (b.chi_z * nrk / g1)
                + kzy * abs(mx) / (chi_lt_i * myrk / g1)
                + kzz * abs(my) / (mzrk / g1)
            )
            base = (
                f"{method_name}: χy = {b.chi_y:.3f}, χz = {b.chi_z:.3f}, χLT = {chi_lt_i:.3f}, "
                f"kyy = {kyy:.3f}, kyz = {kyz:.3f}, kzy = {kzy:.3f}, kzz = {kzz:.3f}{k_note}"
            )
            worst["b61"].offer(
                r61, r61, 1.0, st.combination, f"{base}; {where}", clause("interactionMajor")
            )
            worst["b62"].offer(
                r62, r62, 1.0, st.combination, f"{base}; {where}", clause("interactionMinor")
            )

    checks: list[dict[str, Any]] = []
    if tensioned:
        checks.append(_row("Tension: yielding (gross section)", worst["ty"], "kN", 1e3))
        checks.append(_row("Tension: rupture (net section)", worst["tr"], "kN", 1e3))
    if compressed:
        checks.append(_row("Compression: cross-section", worst["nc"], "kN", 1e3))
        checks.append(_row("Compression: buckling", worst["nb"], "kN", 1e3))
    checks.append(_row("Flexure about x (major)", worst["my"], "kN·m", 1e6))
    checks.append(_row("Flexure about y (minor)", worst["mz"], "kN·m", 1e6))
    if worst["ltb"].combination is not None:
        checks.append(_row("Lateral-torsional buckling", worst["ltb"], "kN·m", 1e6))
    checks.append(_row("Shear along y (depth)", worst["vy"], "kN", 1e3))
    checks.append(_row("Shear along x (width)", worst["vz"], "kN", 1e3))
    checks.append(_row("Axial force and flexure (cross-section)", worst["nm"], "", 1.0))
    if compressed:
        checks.append(_row("Axial force and flexure: buckling, major axis", worst["b61"], "", 1.0))
        checks.append(_row("Axial force and flexure: buckling, minor axis", worst["b62"], "", 1.0))
    if shape.family in ("tee", "angle", "channel"):
        for c in checks:
            if c["name"].startswith("Axial force and flexure"):
                c["note"] += (
                    "; singly symmetric or unsymmetric section: bending about the geometric "
                    "axes (SAEngine practice)"
                )
    if sec.compression_class == 4 and shape.family in ("channel", "tee", "angle"):
        for c in checks:
            if c["name"].startswith("Axial force and flexure"):
                c["note"] += "; the shift eN of the effective centroid is not added"
    stability_row = _global_row(stability, kind)
    if stability_row is not None:
        checks.append(stability_row)
    notes = [*sec.notes]
    if notes:
        for c in checks:
            if c["name"].startswith(("Compression", "Flexure")):
                c["note"] = f"{c['note']}; {'; '.join(notes)}"
    for c in checks:
        if c["utilisation"] < 0:
            c.update(utilisation=0.0, ok=True, demand=0.0)
    return checks


def _annex_b(
    sec: Section,
    b: Buckling,
    n_ed: float,
    cls: int,
    seg_y: tuple[np.ndarray, np.ndarray, float, float],
    seg_z: tuple[np.ndarray, np.ndarray, float, float],
    seg_lt: Any,
) -> tuple[float, float, float, float, str]:
    """kyy, kyz, kzy, kzz of Annex B (Tables B.1, B.2) and the note."""
    t = _t()
    ib = t.interaction.annexB
    g1 = float(t.gammaM1)
    nrk = sec.area_eff * sec.fy
    ny = n_ed / (b.chi_y * nrk / g1)
    nz = n_ed / (b.chi_z * nrk / g1)
    cmy = equivalent_moment(*seg_y)
    cmz = equivalent_moment(*seg_z)
    cmlt = equivalent_moment(*seg_lt) if seg_lt else 1.0
    ly, lz = b.lam_y, b.lam_z
    susceptible = _torsional_susceptible(sec.shape)
    if cls <= 2:
        a, cap = ib.plasticYY
        kyy = cmy * min(1 + (ly - a) * ny, 1 + cap * ny)
        if sec.shape.family == "I":
            fa, fb, fc = ib.plasticZZ
            kzz = cmz * min(1 + (fa * lz - fb) * nz, 1 + fc * nz)
        else:
            kzz = cmz * min(1 + (lz - a) * nz, 1 + cap * nz)
        kyz = float(ib.plasticYZ) * kzz
        if susceptible:
            ta, tb = ib.plasticZYTorsional
            den = max(cmlt - tb, 1e-6)
            if lz >= 0.4:
                kzy = max(1 - ta * lz * nz / den, 1 - ta * nz / den)
            else:
                kzy = min(0.6 + lz, 1 - ta * lz * nz / den)
        else:
            kzy = float(ib.plasticZY) * kyy
    else:
        a, cap = ib.elasticYY
        kyy = cmy * min(1 + a * ly * ny, 1 + cap * ny)
        kzz = cmz * min(1 + a * lz * nz, 1 + cap * nz)
        kyz = float(ib.elasticYZ) * kzz
        if susceptible:
            ta, tb = ib.elasticZYTorsional
            den = max(cmlt - tb, 1e-6)
            kzy = max(1 - ta * lz * nz / den, 1 - ta * nz / den)
        else:
            kzy = float(ib.elasticZY) * kyy
    return kyy, kyz, kzy, kzz, f", Cmy = {cmy:.2f}, Cmz = {cmz:.2f}, CmLT = {cmlt:.2f}"


def _cm0(seg: tuple[np.ndarray, np.ndarray, float, float], n_ed: float, ncr: float) -> float:
    a, b, c, d = _t().interaction.annexA.cm0
    psi, linear = _psi(*seg)
    ratio = n_ed / ncr if ncr > 0 and math.isfinite(ncr) else 0.0
    if not linear:
        return 1 + 0.03 * ratio  # a uniformly loaded span (SAEngine practice)
    return a + b * psi + c * (psi - d) * ratio


def _annex_a(
    sec: Section,
    b: Buckling,
    n_ed: float,
    my_ed: float,
    mz_ed: float,
    chi_lt: float,
    lam_lt: float,
    c1: float,
    cls: int,
    seg_y: tuple[np.ndarray, np.ndarray, float, float],
    seg_z: tuple[np.ndarray, np.ndarray, float, float],
    lz: float,
) -> tuple[float, float, float, float, str]:
    """kyy, kyz, kzy, kzz of Annex A (Tables A.1, A.2) and the note."""
    t = _t()
    ia = t.interaction.annexA
    sh = sec.shape
    g0, g1 = float(t.gammaM0), float(t.gammaM1)
    nrk = sec.area_eff * sec.fy
    ncy, ncz, nct = b.ncr_y, b.ncr_z, b.ncr_t
    ry = n_ed / ncy if math.isfinite(ncy) else 0.0
    rz = n_ed / ncz if math.isfinite(ncz) else 0.0
    rt = n_ed / nct if math.isfinite(nct) and nct > 0 else 0.0
    if max(ry, rz) >= 1:
        return math.inf, math.inf, math.inf, math.inf, ", NEd >= Ncr"
    mu_y = (1 - ry) / (1 - b.chi_y * ry)
    mu_z = (1 - rz) / (1 - b.chi_z * rz)
    wy = min(sh.zx / sh.sx, float(ia.wMax)) if sh.sx > 0 else 1.0
    wz = min(sh.zy / sh.sy, float(ia.wMax)) if sh.sy > 0 else 1.0
    npl = n_ed / (nrk / g1)
    a_lt = max(0.0, 1 - sh.j / sh.ix) if _torsional_susceptible(sh) else 0.0
    cmy0 = _cm0(seg_y, n_ed, ncy)
    cmz0 = _cm0(seg_z, n_ed, ncz)
    # λ̄0: the slenderness of lateral-torsional buckling under a uniform moment (C1 = 1)
    lam0 = lam_lt / math.sqrt(max(c1, 1.0)) if lam_lt > 0 else 0.0
    limit = (
        float(ia.lateralLimit) * math.sqrt(max(c1, 1.0)) * (max((1 - rz) * (1 - rt), 0.0) ** 0.25)
    )
    if lam0 <= limit or a_lt == 0:
        cmy, cmz, cmlt = cmy0, cmz0, 1.0
    else:
        w_el = sec.modulus("y", 3 if cls <= 3 else 4)
        area = sec.area_eff
        eps_y = abs(my_ed) / max(n_ed, 1.0) * area / w_el
        root = math.sqrt(eps_y) * a_lt
        cmy = cmy0 + (1 - cmy0) * root / (1 + root)
        cmz = cmz0
        cmlt = max(1.0, cmy**2 * a_lt / math.sqrt(max((1 - rz) * (1 - rt), 1e-9)))
    kyy = cmy * cmlt * mu_y / (1 - ry)
    kyz = cmz * mu_y / (1 - rz)
    kzy = cmy * cmlt * mu_z / (1 - ry)
    kzz = cmz * mu_z / (1 - rz)
    note = (
        f", Cmy = {cmy:.2f}, Cmz = {cmz:.2f}, CmLT = {cmlt:.2f}, μy = {mu_y:.3f}, μz = {mu_z:.3f}"
    )
    if cls <= 2:
        mply = sh.zx * sec.fy / g0
        mplz = sh.zy * sec.fy / g0
        lam_max = max(b.lam_y, b.lam_z)
        lzz = b.lam_z
        my_r = abs(my_ed) / (chi_lt * mply) if mply > 0 else 0.0
        mz_r = abs(mz_ed) / mplz if mplz > 0 else 0.0
        b_lt = float(ia.bLT) * a_lt * lam0**2 * my_r * mz_r
        c_lt = ia.cLT[0] * a_lt * lam0**2 / (ia.cLT[1] + lzz**4) * my_r / max(cmy, 1e-6)
        d_lt = (
            ia.dLT[0]
            * a_lt
            * lam0
            / (ia.dLT[1] + lzz**4)
            * my_r
            / max(cmy, 1e-6)
            * mz_r
            / max(cmz, 1e-6)
        )
        e_lt = ia.eLT[0] * a_lt * lam0 / (ia.eLT[1] + lzz**4) * my_r / max(cmy, 1e-6)
        p1, p2 = ia.cyy
        q1, q2 = ia.cyz
        share = float(ia.elasticShare)
        cyy = max(
            1
            + (wy - 1)
            * ((2 - p1 / wy * cmy**2 * lam_max - p2 / wy * cmy**2 * lam_max**2) * npl - b_lt),
            sh.sx / sh.zx,
        )
        cyz = max(
            1 + (wz - 1) * ((2 - q1 * cmz**2 * lam_max**2 / wz**q2) * npl - c_lt),
            share * math.sqrt(wz / wy) * sh.sy / sh.zy,
        )
        czy = max(
            1 + (wy - 1) * ((2 - q1 * cmy**2 * lam_max**2 / wy**q2) * npl - d_lt),
            share * math.sqrt(wy / wz) * sh.sx / sh.zx,
        )
        czz = max(
            1
            + (wz - 1)
            * ((2 - p1 / wz * cmz**2 * lam_max - p2 / wz * cmz**2 * lam_max**2) * npl - e_lt),
            sh.sy / sh.zy,
        )
        kyy /= cyy
        kyz *= share * math.sqrt(wz / wy) / czy
        kzy *= share * math.sqrt(wy / wz) / cyz
        kzz /= czz
        note += f", Cyy = {cyy:.3f}, Cyz = {cyz:.3f}, Czy = {czy:.3f}, Czz = {czz:.3f}"
    del lz
    return kyy, kyz, kzy, kzz, note


def _global_row(stability: Any, kind: str) -> dict[str, Any] | None:
    """Columns: αcr from Δ2nd / Δ1st (when the run knows it) against the pack's limit of
    first-order analysis, a flag."""
    if stability is None or kind != "column":
        return None
    ratio = getattr(stability, "drift_ratio", None)
    if ratio is None or not math.isfinite(ratio):
        return None
    g = _t().globalAnalysis
    first = float(g.firstOrder)
    alpha_cr = math.inf if ratio <= 1.0 else ratio / (ratio - 1.0)
    second = stability.method in ("secondOrder", "directAnalysis")
    note = (
        f"αcr ≈ Δ2nd/Δ1st / (Δ2nd/Δ1st - 1) = {alpha_cr:.1f} from Δ2nd/Δ1st = {ratio:.3f} "
        f"({stability.drift_case or 'the lateral cases'}); "
        + (
            "second-order effects are in the analysis (P-Delta with the sway imperfection)"
            if second
            else f"below {first:g} the global analysis must include second-order effects"
        )
    )
    u = first / alpha_cr if math.isfinite(alpha_cr) else 0.0
    return {
        "name": "Global analysis: αcr (sway stability)",
        "demand": round(first, 2),
        "capacity": round(alpha_cr, 2) if math.isfinite(alpha_cr) else 999.0,
        "unit": "",
        "utilisation": round(u, 3),
        "combination": None,
        "ok": bool(u <= 1.0 or second),
        "note": note,
        "flag": True,
        "clause": clause("globalAnalysis"),
    }


# ─────────────────────────────────────── the report ───────────────────────────────────────


def section_summary(shape: ShapeProperties, fy: float) -> tuple[str, list[str]]:
    """``(class label, element descriptions)`` of the section for the member's report entry."""
    fy_d, _ = design_fy(shape, fy)
    comp = classify(shape, fy_d, "compression")
    bend = classify(shape, fy_d, "bending", "y")
    label = f"class {section_class(comp)} (compression), {section_class(bend)} (bending)"
    return label, [
        *(f"compression: {p.describe()}" for p in comp),
        *(f"bending: {p.describe()}" for p in bend),
    ]


def method_lines() -> list[str]:
    """The design report's method text of the steel members by the method."""
    t = _t()
    inter = "Annex B" if t.interaction.method == "annexB" else "Annex A"
    ltb = "the general case" if t.lateralTorsional.method == "general" else "the rolled case"
    return [
        (
            f"Steel members by partial factors ({clause('code')}): γM0 = {float(t.gammaM0):g}, "
            f"γM1 = {float(t.gammaM1):g}, γM2 = {float(t.gammaM2):g}, E = {float(t.modulus):g} MPa; "
            "the load combinations are the project's ultimate ones."
        ),
        (
            f"Cross-section classes 1-4 by c/t and ε ({clause('classes')}), class 4 by the effective "
            f"widths ({clause('effectiveWidth')}); resistances of the cross-sections in tension, "
            "compression, bending, shear (η, shear buckling of slender webs), bending with shear "
            f"and with axial force ({clause('resistances')})."
        ),
        (
            f"Buckling: flexural, torsional and flexural-torsional with χ of the buckling curves "
            f"({clause('buckling')}); lateral-torsional buckling by {ltb} with Mcr from the C1 "
            f"formula, C1 from the moment diagram between the brace points ({clause('lateralTorsional')}); "
            f"members in bending and compression with the interaction factors of {inter} "
            f"({clause('interaction')}), Cm from the moment diagrams. Lcr = K L between the brace "
            "points the analysis model shows (K = 1 unless overridden); the global sway "
            f"imperfection in the analysis when the stability method is set ({clause('imperfections')})."
        ),
        (
            "Deflection of beams (serviceability): as the code pack's serviceability table gives "
            "the limits. Not checked by this method: "
            + ("" if _c12_covers("torsion") else "torsion, ")
            + "connections other than those of the member types, fatigue"
            + ("" if _c12_covers("fire") else ", fire")
            + "."
        ),
    ]


def _c12_covers(what: str) -> bool:
    """Alpha 9 C12: whether the pack adds torsion or fire design to the members."""
    from saengine.design.steel.limit_state import _covers

    return _covers(what, None)
