"""Bolts, bearing, block shear and fillet welds of steel connections by capacity reduction
factors (method ``capacityFactorJoints`` of the pack's ``steelLimitState.connections``; alpha 9
C18c, the form of AS 4100:2020 Chapter 9). The shared connection checks of
:mod:`saengine.design.steel_connections` call these in place of their own strengths where the
pack picks the method (the geometry rules, holes, edges and spacing stay the pack's ``steel``
table's).

- Bolt in shear (9.3.2.1 type): ``φVf = φ shearShare fuf kr nn Ac`` with the threads in every
  shear plane (Ac = ``coreShare`` Ao, on the safe side), kr of the joint length (``longJoint``).
- Bolt in tension (9.3.2.2): ``φNtf = φ As fuf``; with shear (9.3.2.3)
  ``(V*/φVf)² + (N*/φNtf)² <= 1``.
- Ply in bearing (9.2.2.4): ``φVb = φ bearingFactor df tp fup``, tear-out ``φ ae tp fup`` with
  ae the distance from the bolt's centre to the edge (the clear distance + df / 2).
- Friction (9.3.3.1): ``φVsf = φ μ nei Nti kh``, reduced by ``1 - N*/Nti`` under tension.
- Block shear (9.1.9 type): ``φ min(0.6 fu Anv, 0.6 fy Agv) + φ kbs fu Ant``.
- Fillet welds (9.6.3.10 type): ``φvw = φ weldShare fuw tt kr`` per mm, tt = ``throatShare`` w,
  kr = 1.

Units: mm, MPa, N.
"""

from __future__ import annotations

import math
from typing import Any

METHOD = "capacityFactorJoints"


def table() -> Any | None:
    """The pack's ``steelLimitState.connections`` when it is this method, else None."""
    from saengine.design.steel.limit_state import rules

    t = rules()
    found = getattr(t, "connections", None) if t is not None else None
    if found is None or getattr(found, "method", None) != METHOD:
        return None
    return found


def active() -> bool:
    return table() is not None


def _t() -> Any:
    found = table()
    if found is None:
        raise ValueError("the code pack does not design joints by capacity reduction factors")
    return found


def cite(key: str) -> str:
    from saengine.codes import context as code_context

    return code_context.cite("steelLimitState", key)


def grade(name: str) -> Any:
    """The pack's bolt grade of ``name`` (a grade, or one it is taken as)."""
    t = _t()
    key = t.gradeOf.get(name, name)
    if key not in t.grades:
        raise ValueError(f"bolt grade '{name}' is not a bolt grade of the code pack")
    return t.grades[key]


def tensile_area(d: float) -> float:
    """As [mm²] of an M``d`` bolt (the pack's table; 0.78 Ao otherwise)."""
    found = _t().tensileArea.get(round(d))
    return float(found) if found is not None else 0.78 * math.pi * d**2 / 4


def long_joint(length: float) -> float:
    """kr of a joint ``length`` [mm] long along the force."""
    l1, l2, a, b, least = (float(x) for x in _t().longJoint)
    if length <= l1:
        return 1.0
    if length >= l2:
        return least
    return max(min(a - length / b, 1.0), least)


def shear(name: str, d: float, planes: int = 1, factor: float = 1.0) -> float:
    """φVf [N] of one bolt over ``planes`` shear planes (``factor``: kr)."""
    t = _t()
    ac = float(t.coreShare) * math.pi * d**2 / 4
    return float(t.phiBolt) * float(t.shearShare) * float(grade(name).fuf) * factor * planes * ac


def tension(name: str, d: float, frv: float = 0.0) -> tuple[float, str]:
    """φNtf [N] of one bolt and the note; with the bolt's shear stress ``frv`` [MPa on its shank
    area] the tension the interaction leaves, φNtf √(1 - (V*/φVf)²)."""
    t = _t()
    ntf = float(t.phiBolt) * tensile_area(d) * float(grade(name).fuf)
    note = f"φNtf = φ As fuf, φ = {float(t.phiBolt):g} ({cite('boltTension')})"
    if frv <= 0:
        return ntf, note
    vf = shear(name, d, 1)
    share = frv * math.pi * d**2 / 4 / vf if vf > 0 else math.inf
    if share >= 1:
        return 0.0, f"{note}; the shear alone uses the bolt ({cite('boltCombined')})"
    return ntf * math.sqrt(1 - share**2), (
        f"{note}, × √(1 - (V*/φVf)²) with V*/φVf = {share:.2f} ({cite('boltCombined')})"
    )


def bearing(d: float, t_plate: float, fu: float, lc: float) -> float:
    """φVb [N] of one bolt hole: the lesser of the ply's bearing and its tear-out (``lc`` the
    clear distance to the edge or the next hole; inf: no edge close by)."""
    t = _t()
    full = float(t.phiPly) * float(t.bearingFactor) * d * t_plate * fu
    if math.isinf(lc):
        return full
    ae = max(lc, 0.0) + d / 2
    return min(full, float(t.phiPly) * ae * t_plate * fu)


def slip(c: Any, d: float, planes: int = 1, tension_ed: float = 0.0) -> tuple[float, str]:
    """φVsf [N] of one fully tensioned bolt and the note (0 for a grade not tensioned)."""
    t = _t()
    g = grade(c.boltGrade)
    if not g.pretensioned:
        return 0.0, f"{c.boltGrade} M{d:g}: not a fully tensioned grade of the code pack"
    nti = t.pretension.get(round(d))
    kh = t.holeKh.get(c.holeType)
    if nti is None or kh is None:
        return 0.0, f"no Nti for M{d:g} or kh for hole '{c.holeType}' in the code pack"
    nti_n = float(nti) * 1e3
    reduce = max(1.0 - tension_ed / nti_n, 0.0) if tension_ed > 0 else 1.0
    value = float(t.phiSlip) * float(t.slipMu) * planes * nti_n * float(kh) * reduce
    note = (
        f"φVsf = φ μ nei Nti kh: φ {float(t.phiSlip):g} × μ {float(t.slipMu):g} × {planes} "
        f"plane(s) × Nti {float(nti):g} kN × kh {float(kh):g}"
        + (f" × (1 - N*/Nti) {reduce:.2f}" if tension_ed > 0 else "")
        + f" ({cite('slip')})"
    )
    return value, note


def block(fy: float, fu: float, agv: float, anv: float, ant: float, ubs: float = 1.0) -> float:
    """φRbs [N]."""
    return float(_t().phiBlock) * (min(0.6 * fu * anv, 0.6 * fy * agv) + ubs * fu * ant)


def fillet_per_mm(w: float) -> float:
    """φvw [N/mm] of a fillet weld of leg ``w`` [mm] (kr = 1)."""
    t = _t()
    return float(t.phiWeld) * float(t.weldShare) * float(t.fuw) * float(t.throatShare) * w


def method_lines() -> list[str]:
    t = table()
    if t is None:
        return []
    return [
        (
            f"Connections by capacity reduction factors ({cite('connections')}): bolts φVf = "
            f"{float(t.phiBolt):g} × {float(t.shearShare):g} fuf kr Ac (threads in the shear "
            f"planes), φNtf = φ As fuf, (V*/φVf)² + (N*/φNtf)² <= 1; the ply φ {float(t.phiPly):g} "
            f"× min({float(t.bearingFactor):g} df tp fup, ae tp fup); friction φ "
            f"{float(t.phiSlip):g} μ nei Nti kh; block shear φ {float(t.phiBlock):g}; fillet welds "
            f"φ {float(t.phiWeld):g} × {float(t.weldShare):g} fuw tt with fuw = {float(t.fuw):g} MPa."
        )
    ]
