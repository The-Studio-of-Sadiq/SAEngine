"""Punching shear by the shear strength of the critical perimeter reduced for the unbalanced
moment (method ``momentTransfer`` of the pack's ``concreteMethods.punching``; alpha 9 C18b,
the form of AS 3600:2018 9.3).

On the critical shear perimeter u at dom / 2 from the loaded area (SAEngine's critical section
at d / 2, the same pieces as the default method):

- the shear strength without moment ``Vuo = u dom fcv``, with
  ``fcv = coefficient (1 + 2 / βh) √f'c`` at most ``maxCoefficient`` √f'c, βh the long over
  the short side of the loaded area (√f'c at most ``rootMax`` where the pack gives it);
- with the unbalanced moment M*v: ``Vu = Vuo / (1 + u M*v / (divisor V* a dom))``, a the
  side of the critical perimeter parallel to the moment's direction. Written on stresses
  (V* <= φ Vu): ``V* / (u dom) + Σ |M*v| / (divisor a dom²) <= φ fcv``, both directions'
  moments added at once (on the safe side).

Shear reinforcement (closed fitments, shearheads) is not laid out by SAEngine under this
method: a perimeter short of φ fcv fails and the note says to thicken the slab, add a drop
panel or enlarge the column. The prestress term 0.3 σcp is not taken (no prestress here).

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context

METHOD = "momentTransfer"


def rules() -> Any | None:
    """The pack's ``concreteMethods.punching`` when it is this method, or None."""
    pack = code_context.current()
    if not pack.has("concreteMethods"):
        return None
    from saengine.codes.method_tables import chosen

    return chosen(pack.table("concreteMethods"), "punching", METHOD)


def cite() -> str:
    """The pack's clause of the method ("" when it gives none)."""
    return code_context.cite("concreteMethods", "punching")


def strength(fc: float, beta: float, r: Any | None = None) -> tuple[float, float, float]:
    """(fcv, the (1 + 2/βh) term, the cap) [MPa] at f'c ``fc`` and βh ``beta``."""
    r = r if r is not None else rules()
    root = math.sqrt(fc)
    if r.rootMax is not None:
        root = min(root, float(r.rootMax))
    shape = r.coefficient * (1 + 2 / max(beta, 1.0)) * root
    cap = r.maxCoefficient * root
    return min(shape, cap), shape, cap


def stress(
    b0: float, d: float, widths: tuple[float, float], vu: float, m_u: float, m_v: float,
    r: Any | None = None,
) -> tuple[float, float]:  # fmt: skip
    """(v, V*/(u d)) [MPa]: V*/(u d) + |M_u| / (divisor a_u d²) + |M_v| / (divisor a_v d²),
    ``m_u`` the moment bending the slab along u (a_u = the section's width along u)."""
    r = r if r is not None else rules()
    direct = vu / (b0 * d)
    width_u, width_v = widths
    total = direct
    for moment, width in ((m_u, width_u), (m_v, width_v)):
        if width > 0:
            total += abs(moment) / (r.momentDivisor * width * d * d)
    return total, direct


def note(fc: float, beta: float) -> str:
    """The method's line for the punching row."""
    r = rules()
    fcv, shape, cap = strength(fc, beta, r)
    where = cite()
    return (
        f"{where + ': ' if where else ''}fcv = min({r.coefficient:g} (1 + 2/βh) √f'c, "
        f"{r.maxCoefficient:g} √f'c) = min({shape:.3f}, {cap:.3f}) = {fcv:.3f} MPa, βh = "
        f"{beta:.2f}; v = V*/(u d) + M*v/({r.momentDivisor:g} a d²) (Vu = Vuo/(1 + u M*v/"
        f"({r.momentDivisor:g} V* a d)))"
    )
