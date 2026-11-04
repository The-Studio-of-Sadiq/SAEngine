"""Bolts, bearing, welds and block tearing of steel joints by design resistances with partial
factors: the connection method ``partialFactors`` a code pack picks with
``steel.connections.resistances`` (alpha 9 C6; the Eurocodes pack: EN 1993-1-8 Table 3.4,
3.9, 3.10.2 and 4.5.3).

:mod:`saengine.design.steel_connections` asks this module for the resistance of one bolt in
shear and in tension (with the combined shear), a line of bolts in bearing, a fillet weld per
mm and a block, when the pack picks the method; its plate checks, spacings and edges stay as
written, with the pack's values (holes, edges, the φ-equivalent factors 1/γM). Every number is
the pack's ``resistances``.

- Shear Fv,Rd = αv fub As / γM2 per shear plane (the shear plane through the threads: As, on the
  safe side); tension Ft,Rd = k2 fub As / γM2; shear with tension Fv,Ed / Fv,Rd + Ft,Ed /
  (1.4 Ft,Rd) <= 1, the tension resistance given as the share the shear leaves.
- Bearing Fb,Rd = k1 αb fu d t / γM2: αb = min(αd, fub / fu, 1), αd = e1 / (3 d0) for the end
  bolt and p1 / (3 d0) - 1/4 for the inner ones; k1 at the pack's largest value (the transverse
  edge distances are not known to the line: SAEngine practice, noted).
- Fillet welds: the simplified method fvw,d = fu / (√3 βw γM2) on the throat a = 0.707 w, or the
  directional method for a force at θ to the weld axis: F / a <= fu / (βw γM2 √(3 - sin²θ)) and
  σ⊥ <= 0.9 fu / γM2; fu and βw of the weaker part joined (:func:`parent`).
- Block tearing Veff = u fu Ant / γM2 + fy Anv / (√3 γM0), u = 1 (concentric) or the caller's
  share (eccentric).
- Slip-resistant bolts Fs,Rd = ks n μ (Fp,C - 0.8 Ft,Ed) / γM3, Fp,C = 0.7 fub As.

Units: mm, MPa, N.
"""

from __future__ import annotations

import contextlib
import math
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

#: fu [MPa] of the weaker part of the joint in progress (None: not known).
_PARENT_FU: ContextVar[float | None] = ContextVar("joint_parent_fu", default=None)
#: fub [MPa] of the bolts of the joint in progress for αb (None: fub / fu taken >= 1).
_BEARING_GRADE: ContextVar[float | None] = ContextVar("joint_bearing_fub", default=None)


def table() -> Any | None:
    """The pack's ``steel.connections.resistances`` when it picks the method, else None."""
    try:
        from saengine.design.steel_connections import steel_table

        data = steel_table().connections
    except Exception:  # noqa: BLE001 - no pack machinery: the default method
        return None
    found = getattr(data, "resistances", None) if data is not None else None
    if found is None or getattr(found, "method", None) != "partialFactors":
        return None
    return found


def active() -> bool:
    return table() is not None


@contextlib.contextmanager
def parent(fu: float | None) -> Iterator[None]:
    """The welds of the enclosed checks join parts whose weaker fu is ``fu`` [MPa]."""
    token = _PARENT_FU.set(fu)
    try:
        yield
    finally:
        _PARENT_FU.reset(token)


def _t() -> Any:
    found = table()
    if found is None:
        raise ValueError("the code pack does not design joints by partial factors")
    return found


def bolt(grade: str) -> Any:
    """The pack's bolt class of ``grade`` (a class, or a grade it is taken as)."""
    t = _t()
    key = t.gradeOf.get(grade, grade)
    if key not in t.bolts:
        raise ValueError(f"bolt grade '{grade}' is not a bolt class of the code pack")
    return t.bolts[key]


def tensile_area(d: float) -> float:
    """As [mm²] of an M``d`` bolt (the pack's table; 0.78 of the shank area otherwise)."""
    t = _t()
    found = t.tensileArea.get(int(round(d)))
    return float(found) if found is not None else 0.78 * math.pi * d**2 / 4


def shear(grade: str, d: float, planes: int = 1, factor: float = 1.0) -> float:
    """Fv,Rd [N] of one bolt over ``planes`` shear planes (``factor``: a long-joint factor)."""
    b = bolt(grade)
    return factor * float(b.alphaV) * float(b.fub) * tensile_area(d) * planes / float(_t().gammaM2)


def tension(grade: str, d: float, frv: float = 0.0) -> tuple[float, str]:
    """Ft,Rd [N] of one bolt and its note; with the bolt's shear stress ``frv`` [MPa] on its
    shank area, the tension the interaction leaves (1.4 Ft,Rd (1 - Fv,Ed / Fv,Rd) <= Ft,Rd)."""
    t = _t()
    b = bolt(grade)
    ft = float(t.k2) * float(b.fub) * tensile_area(d) / float(t.gammaM2)
    if frv <= 0:
        return ft, f"Ft,Rd = k2 fub As / γM2 (k2 = {float(t.k2):g})"
    fv_ed = frv * math.pi * d**2 / 4
    fv_rd = shear(grade, d)
    left = max(min(ft, float(t.combinedTension) * ft * (1 - fv_ed / fv_rd)), 0.0)
    return left, (
        f"Ft,Rd = k2 fub As / γM2 with Fv,Ed / Fv,Rd + Ft,Ed / ({float(t.combinedTension):g} Ft,Rd) "
        f"<= 1, Fv,Ed = {fv_ed / 1e3:.1f} kN"
    )


def bearing_line(
    d: float, t_plate: float, fu: float, rows: int, pitch: float, end: float | None, d0: float
) -> float:
    """Σ Fb,Rd [N] of a line of ``rows`` bolts loaded towards the end distance ``end`` [mm]
    (None: no edge close by), pitch p1, hole d0."""
    t = _t()
    br = t.bearing
    k1 = float(br.k1Max)
    fub = _BEARING_GRADE.get()

    def one(alpha_d: float) -> float:
        alpha_b = min(alpha_d, (fub / fu) if fub else 1.0, 1.0)
        return k1 * alpha_b * fu * d * t_plate / float(t.gammaM2)

    first = one(end / (float(br.endDistance) * d0)) if end is not None else one(1.0)
    inner = one(pitch / (float(br.innerPitch) * d0) - float(br.innerOffset))
    return first + (rows - 1) * inner


def _beta_w(fu: float) -> float:
    for limit, beta in _t().weld.betaW:
        if fu <= limit + 1e-9:
            return float(beta)
    return float(_t().weld.betaW[-1][1])


def fillet_per_mm(w: float, theta_deg: float = 0.0) -> tuple[float, str]:
    """The design resistance of a fillet weld of leg ``w`` [mm] per mm [N/mm] and its note: fu
    of the weaker part joined (:func:`parent`; the least fu the pack's βw table lists when it is
    not known, on the safe side)."""
    t = _t()
    fu = _PARENT_FU.get()
    known = fu is not None
    if fu is None:
        fu = float(t.weld.betaW[0][0])
    beta = _beta_w(fu)
    a = 0.707 * w
    g2 = float(t.gammaM2)
    if t.weld.method == "directional":
        s = math.sin(math.radians(theta_deg))
        cap = a * fu / (beta * g2 * math.sqrt(3 - s**2))
        if s > 0:
            cap = min(cap, a * float(t.weld.perpendicularShare) * fu / g2 * math.sqrt(2) / s)
        how = f"directional method, θ = {theta_deg:g}°"
    else:
        cap = a * fu / (math.sqrt(3) * beta * g2)
        how = "simplified method fvw,d = fu / (√3 βw γM2)"
    note = f"{how}, a = 0.707 w = {a:.1f} mm, fu = {fu:g} MPa, βw = {beta:g}"
    if not known:
        note += " (fu of the parts not known: the least of the pack's table)"
    return cap, note


def block(fy: float, fu: float, anv: float, ant: float, share: float = 1.0) -> float:
    """Veff,Rd [N] = share fu Ant / γM2 + fy Anv / (√3 γM0)."""
    t = _t()
    return share * fu * ant / float(t.gammaM2) + float(t.blockShear) * fy * anv / (
        math.sqrt(3) * float(t.gammaM0)
    )


def slip(
    grade: str, d: float, surface: str, hole: str, level: str, planes: int, tension_ed: float
) -> tuple[float, str]:
    """Fs,Rd [N] of one preloaded bolt and its note; 0 when the pack gives no slip values."""
    t = _t()
    s = t.slip
    if s is None:
        return 0.0, "slip resistance: not covered by the code pack"
    b = bolt(grade)
    fpc = float(s.preload) * float(b.fub) * tensile_area(d)
    mu = float(s.mu.get(surface, min(s.mu.values())))
    ks = float(s.ks.get(hole, min(s.ks.values())))
    gamma = float(s.gammaM3.get(level, max(s.gammaM3.values())))
    cap = ks * planes * mu * max(fpc - float(s.tensionReduction) * tension_ed, 0.0) / gamma
    return cap, (
        f"Fs,Rd = ks n μ (Fp,C - {float(s.tensionReduction):g} Ft,Ed) / γM3: ks = {ks:g}, n = "
        f"{planes}, μ = {mu:g}, Fp,C = {fpc / 1e3:.0f} kN, γM3 = {gamma:g}"
    )


@contextlib.contextmanager
def bolts_of(grade: str | None) -> Iterator[None]:
    """The enclosed bearing checks are of bolts of ``grade`` (αb with fub / fu)."""
    fub = None
    if grade and active():
        with contextlib.suppress(ValueError):
            fub = float(bolt(grade).fub)
    token = _BEARING_GRADE.set(fub)
    try:
        yield
    finally:
        _BEARING_GRADE.reset(token)
