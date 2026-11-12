"""In-plane shear of walls by the shear span ratio (alpha 9 C20b; the pack's
``concreteMethods.shearSpanWalls``, method ``shearSpanRatio``, as GB 50010-2010 6.3.20-6.3.21
and 11.7.3-11.7.4 give them).

For every combination of the pier: λ = M / (V h0) within ``lambdaRange``, h0 = depthShare ×
lw, N (compression) at most axialShare fcd t lw (tension: N = 0, on the safe side), and

    V <= 1 / (λ - lambdaOffset) (a fctd t h0 + b N Aw / A) + c fyv Ash h0 / sv

with (a, b, c) the pack's ``terms`` (``seismicTerms`` in the earthquake combinations: their
γRE is applied to the forces, :mod:`saengine.design.seismic_grades`), Aw / A = 1 (a
rectangular pier), Ash / sv = ρh t; the section V <= sectionShare fcd t h0; the web steel each
way at least ``webMin``. The governing combination is the one of the largest V over the
resistance.

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.design.tabulated_shear import _group, _paren


def rules() -> Any | None:
    """The pack's ``concreteMethods.shearSpanWalls`` (method ``shearSpanRatio``), or None."""
    return _group("shearSpanWalls", "shearSpanRatio")


def _row(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from saengine.design.check import _check

    return _check(*args, **kwargs)


def resistance(
    v: float, m: float, n: float, t: float, lw: float, fc: float, fy: float, rho_h: float,
    seismic: bool,
) -> tuple[float, float, float]:  # fmt: skip
    """(Vu [N], λ, the section's limit [N]) of a pier under (V, M, N) [N, N·mm, N]."""
    from saengine.design import design_strength

    r = rules()
    h0 = r.depthShare * lw
    lo, hi = r.lambdaRange
    lam = abs(m) / (abs(v) * h0) if abs(v) > 0 and h0 > 0 else hi
    lam = min(max(lam, lo), hi)
    a, b, c = r.seismicTerms if (seismic and r.seismicTerms is not None) else r.terms
    fcd = design_strength.fcd(fc, shear=True)
    ftd = design_strength.fctd(fc)
    fyv = design_strength.fyd(fy)
    axial = min(max(n, 0.0), r.axialShare * fcd * t * lw)
    concrete = (a * ftd * t * h0 + b * axial) / (lam - r.lambdaOffset)
    steel = c * fyv * rho_h * t * h0
    return concrete + steel, lam, r.sectionShare * fcd * t * h0


def shear_row(
    forces: list[Any], t: float, lw: float, fc: float, fy: float, rho_h: float
) -> dict[str, Any] | None:
    """The in-plane shear row of the governing combination (None without forces)."""
    r = rules()
    worst = None
    for f in forces:
        v = abs(f.V2)
        if v <= 0:
            continue
        vu, lam, cap = resistance(
            v, f.M3, f.P, t, lw, fc, fy, rho_h, bool(getattr(f, "earthquake", False))
        )
        capacity = min(vu, cap)
        u = v / capacity if capacity > 0 else math.inf
        if worst is None or u > worst[0]:
            worst = (u, f, vu, lam, cap)
    if worst is None:
        return None
    _u, f, vu, lam, cap = worst
    seismic = bool(getattr(f, "earthquake", False)) and r.seismicTerms is not None
    a, b, c = r.seismicTerms if seismic else r.terms
    return _row(
        f"In-plane shear{_paren('wallShear')}",
        abs(f.V2) / 1e3,
        min(vu, cap) / 1e3,
        "kN",
        f.combination,
        f"V <= 1/(λ - {r.lambdaOffset:g}) ({a:g} ft t h0 + {b:g} N) + {c:g} fyv Ash h0/sv = "
        f"{vu / 1e3:.1f} kN, λ = {lam:.2f}, h0 = {r.depthShare:g} lw, N = {f.P / 1e3:.0f} kN "
        f"(at most {r.axialShare:g} fc t lw), ρh = {rho_h:.4f}; the section at most "
        f"{r.sectionShare:g} fc t h0 = {cap / 1e3:.1f} kN"
        + ("; the earthquake form (γRE on the forces)" if seismic else ""),
    )


def web_rows(rho_l: float, rho_h: float) -> list[dict[str, Any]]:
    """The least web steel each way."""
    r = rules()
    return [
        _row(
            f"Wall web steel, {name}{_paren('wallSteel')}",
            100 * r.webMin,
            100 * rho,
            "%",
            None,
            f"at least {100 * r.webMin:g} % each way",
        )
        for name, rho in (("vertical", rho_l), ("horizontal", rho_h))
    ]
