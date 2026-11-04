"""The storey shear coefficient method: Qi = Ci·ΣWi with Ci = Z·Rt·Ai·C0 (alpha 9 track C19).

The design spectrum method ``standardShearCoefficient`` of the code pack's seismic table (its
``designSpectrum.shearCoefficient`` block, :class:`saengine.codes.tables.ShearCoefficientRule`)
gives the base shear coefficient C = Z·Rt·C0·I/R and, with the lateral force distribution
``shearCoefficientAi``, the storey shears Qi = V·Ai·αi:

- Rt, the vibration characteristic factor of the period T and the site class's corner period
  TC: 1 while T < TC, 1 - a·(T/TC - 1)² up to b·TC, c·TC/T beyond (a ``transition``, b
  ``transitionEnd``, c ``longFactor``), at least ``least``;
- Ai, the distribution of the storey shear coefficient over the height: 1 + (1/√αi - αi)·k·T /
  (1 + m·T), αi the weight above storey i over the total (k ``aiNumerator``, m
  ``aiDenominator``);
- C0 the standard shear coefficient: ``standardCoefficient`` for the primary design,
  ``ultimateCoefficient`` for the required horizontal capacity
  (:mod:`saengine.fem.horizontal_capacity`).

The response spectrum of the method is Z·C0·Rt(T)·I/R (the normalized spectrum Rt). The code
pack holds every number; nothing here names a code.

Units: s, N (any force unit).
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context

METHOD = "standardShearCoefficient"
DISTRIBUTION = "shearCoefficientAi"


def rule(pack: Any = None) -> Any | None:
    """The pack's ``designSpectrum.shearCoefficient`` block when its design spectrum method is
    ``standardShearCoefficient`` (default: the pack in force); None otherwise."""
    pack = pack or code_context.current()
    if not pack.has("seismic"):
        return None
    spectrum = getattr(pack.table("seismic"), "designSpectrum", None)
    if spectrum is None or spectrum.method != METHOD:
        return None
    return spectrum.shearCoefficient


def uses_ai(pack: Any = None) -> bool:
    """Whether the pack distributes the base shear by Ai (lateral force ``shearCoefficientAi``
    with the method's block)."""
    pack = pack or code_context.current()
    if not pack.has("seismic"):
        return False
    lateral = getattr(pack.table("seismic"), "lateralForce", None)
    return lateral is not None and lateral.distribution == DISTRIBUTION and rule(pack) is not None


def vibration_factor(period: float, tc: float, block: Any) -> float:
    """Rt of ``period`` T [s] for the corner period ``tc`` TC [s] (see the module notes)."""
    t = max(float(period), 0.0)
    if tc <= 0 or t < tc:
        value = 1.0
    elif t < block.transitionEnd * tc:
        value = 1.0 - block.transition * (t / tc - 1.0) ** 2
    else:
        value = block.longFactor * tc / t
    return max(value, block.least)


def site_corner(site_class: str) -> float:
    """TC [s] of ``site_class`` in the pack in force (0 when it has none)."""
    site = code_context.table("seismic").siteClasses.get(site_class)
    return float(site.TC) if site is not None else 0.0


def coefficient(
    period: float,
    site_class: str,
    z: float,
    importance: float = 1.0,
    r: float = 1.0,
    ultimate: bool = False,
) -> float:
    """C = Z·Rt·C0·I/R at ``period`` (the base shear coefficient, Ai = 1); C0 the ultimate one
    with ``ultimate``. 0 without the method."""
    block = rule()
    if block is None:
        return 0.0
    c0 = block.ultimateCoefficient if ultimate else block.standardCoefficient
    rt = vibration_factor(period, site_corner(site_class), block)
    return float(z) * rt * c0 * importance / r


def distribution_factor(alpha: float, period: float, block: Any) -> float:
    """Ai of a storey whose weight above is the share ``alpha`` αi of the total."""
    a = min(max(float(alpha), 1e-9), 1.0)
    t = max(float(period), 0.0)
    return 1.0 + (1.0 / math.sqrt(a) - a) * block.aiNumerator * t / (1.0 + block.aiDenominator * t)


def storey_terms(levels: list[tuple[float, float]], period: float) -> list[dict[str, float]]:
    """Per level of ``levels`` ((height, weight), any order) bottom up, the storey below it:
    ``{"height", "weight", "above" (ΣWi), "alpha", "Ai"}``; [] without the method."""
    block = rule()
    if block is None or not levels:
        return []
    ordered = sorted(levels, key=lambda hw: hw[0])
    total = sum(w for _, w in ordered)
    out = []
    above = total
    for height, weight in ordered:
        alpha = above / total if total > 0 else 1.0
        out.append(
            {
                "height": float(height),
                "weight": float(weight),
                "above": float(above),
                "alpha": float(alpha),
                "Ai": distribution_factor(alpha, period, block),
            }
        )
        above -= weight
    return out


def level_forces(
    levels: list[tuple[float, float]], base_shear: float, period: float
) -> list[float]:
    """The lateral force at each level of ``levels`` (in their order): the storey shears Qi =
    V·Ai·αi (Qi = Ci ΣWi with Ci = C Ai), each level's force Qi - Qi+1."""
    terms = storey_terms(levels, period)
    if not terms:
        return [0.0] * len(levels)
    shears = [base_shear * t["Ai"] * t["alpha"] for t in terms]
    forces_bottom_up = [
        shears[k] - (shears[k + 1] if k + 1 < len(shears) else 0.0) for k in range(len(shears))
    ]
    order = sorted(range(len(levels)), key=lambda i: levels[i][0])
    out = [0.0] * len(levels)
    for rank, index in enumerate(order):
        out[index] = forces_bottom_up[rank]
    return out


def summary(
    levels: list[tuple[float, float]],
    period: float,
    site_class: str,
    z: float,
    importance: float = 1.0,
    r: float = 1.0,
) -> dict[str, Any] | None:
    """The method's terms for the derivation summary and the report: ``{"Z", "Rt", "TC",
    "C0", "C0u", "storeys": [{"height", "alpha", "Ai", "Ci", "Ciu"}]}``; None without it."""
    block = rule()
    if block is None:
        return None
    tc = site_corner(site_class)
    rt = vibration_factor(period, tc, block)
    base = float(z) * rt * importance / r
    rows = [
        {
            "height": round(t["height"], 3),
            "above_kN": round(t["above"] / 1e3, 3),
            "alpha": round(t["alpha"], 4),
            "Ai": round(t["Ai"], 4),
            "Ci": round(base * block.standardCoefficient * t["Ai"], 5),
            "Ciu": round(base * block.ultimateCoefficient * t["Ai"], 5),
        }
        for t in (storey_terms(levels, period) if uses_ai() else [])
    ]
    return {
        "Z": float(z),
        "Rt": round(rt, 4),
        "TC": tc,
        "C0": block.standardCoefficient,
        "C0u": block.ultimateCoefficient,
        "storeys": rows,
        "clauses": dict(block.clauses),
    }
