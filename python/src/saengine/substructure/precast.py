"""Driven precast concrete piles: the square section, handling and the reinforcement
(Part 9, deep foundations; the code pack's pile rules, the default pack's Part 6 Ch 3).

A driven pile of 9 Substructure is a square precast pile of side B (``PileType.diameter``),
as the BOQ measures it: shaft perimeter 4B and area B² in its capacity
(:func:`saengine.substructure.piles.single_pile`), the square section in its structural checks.

Handling (:func:`handling_checks`): the pile is cast, lifted and pitched lying down, so its own
weight bends it. Statics of a uniform beam of weight w = γc B² per metre and length L:

- lifting at two points 0.207 L from the ends, the moments over the supports and at mid-span
  equal: ``M = 0.0214 w L²``;
- pitching from one point 0.293 L from the head, the foot on the ground: ``M = 0.0429 w L²``.

Each times the impact allowance of the code pack (``foundations.piles.detailing.driven.
impact``, the weight plus 50 % in the default pack) against φMn of the square section about its
axis (ACI 318-19 22.3, the bars as laid out, φ = 0.9), and, reported only, against the cracking
moment ``Mcr = fr B³ / 6``, ``fr = 0.62 √f'c`` (ACI 318-19 19.2.3.1), above which the pile cracks
while it is handled. The pack's service stress of a precast pile is checked by
:func:`saengine.substructure.piles.structural_checks`, its least bars, ties, grade and
slenderness by :mod:`saengine.substructure.pile_detailing`.

Units: N and mm inside; reported in kN·m.
"""

from __future__ import annotations

import math
from typing import Any

#: Two-point lift at 0.207 L from the ends: M = 0.0214 w L².
TWO_POINT = (0.207, 0.0214)
#: Pitching from one point 0.293 L from the head: M = 0.0429 w L².
ONE_POINT = (0.293, 0.0429)
#: Impact allowance on the weight during handling when the pack gives none (no impact).
NO_IMPACT = 0.0


def impact_factor() -> tuple[float, str]:
    """The handling weight's factor, 1 + the pack's impact allowance, and its clause."""
    from saengine.substructure.pile_detailing import cite, rules

    found = rules()
    if found is None:
        return 1.0 + NO_IMPACT, "no impact allowance in the code pack"
    return 1.0 + found.driven.impact, cite("detailing.driven.impact")


PRECAST_METHOD = (
    "Driven precast piles: square, side B (perimeter 4B, area B²); handling by statics of the "
    "pile under its own weight, two-point lift at 0.207 L (M = 0.0214 w L²) and pitching from "
    "0.293 L (M = 0.0429 w L²), times the code pack's impact allowance, against φMn of the "
    "square section (ACI 318-19 22.3) and, reported only, the cracking moment fr B³/6; the "
    "code pack's least bars by L/B, ties, grade, slenderness and service stress."
)


def handling_moments(side: float, length: float, unit_weight: float) -> dict[str, float]:
    """The handling moments [N·mm] of a square pile of ``side`` and ``length`` [mm] and
    concrete ``unit_weight`` [N/mm³], without impact: ``twoPoint`` and ``onePoint``."""
    w = unit_weight * side * side  # N/mm
    return {
        "twoPoint": TWO_POINT[1] * w * length**2,
        "onePoint": ONE_POINT[1] * w * length**2,
    }


def cracking_moment(side: float, fc: float) -> float:
    """Mcr = fr B³ / 6 [N·mm] of a square section, fr = 0.62 √f'c (ACI 318-19 19.2.3.1)."""
    return 0.62 * math.sqrt(fc) * side**3 / 6


def square_section(side: float, reinforcement: Any, fc: float, fy: float) -> Any:
    """The RC section of a square pile, or None without bars (or when they do not fit)."""
    from saengine.design.rc import DesignError, section_of
    from saengine.library.objects import RectangleProfile

    if reinforcement is None or not reinforcement.longitudinal:
        return None
    try:
        return section_of(RectangleProfile(xDim=side, yDim=side), reinforcement, fc, fy)
    except DesignError:
        return None


def handling_checks(
    side: float, length: float, fc: float, fy: float, reinforcement: Any, unit_weight: float
) -> list[dict[str, Any]]:
    """Handling checks of a driven precast pile (see the module notes)."""
    from saengine.design.check import _check
    from saengine.design.rc import InteractionSurface

    moments = handling_moments(side, length, unit_weight)
    section = square_section(side, reinforcement, fc, fy)
    capacity = InteractionSurface(section).moment_capacity(0.0, 0.0) if section else 0.0
    mcr = cracking_moment(side, fc)
    impact, clause = impact_factor()
    checks: list[dict[str, Any]] = []
    for key, (at, coefficient), label in (
        ("twoPoint", TWO_POINT, "lifted at two points"),
        ("onePoint", ONE_POINT, "pitched from one point"),
    ):
        mu = impact * moments[key]
        checks.append(
            _check(
                f"Pile handling, {label}",
                mu / 1e6,
                capacity / 1e6,
                "kN·m",
                None,
                f"M = {coefficient:g} w L² with the pick-up at {at:g} L, w = γc B², L = "
                f"{length / 1e3:.1f} m, × {impact:g} for impact ({clause}); φMn of the "
                f"{side:.0f} mm square section (ACI 318-19 22.3)"
                + ("" if section else ": no bars, an unreinforced precast pile cannot be handled"),
            )
        )
    worst = impact * max(moments.values())
    checks.append(
        _check(
            "Pile handling, cracking",
            worst / 1e6,
            mcr / 1e6,
            "kN·m",
            None,
            "the larger handling moment with impact against Mcr = 0.62 √f'c B³ / 6 (ACI 318-19 "
            "19.2.3.1): above it the pile cracks while it is handled; lift it at more points. "
            "Reported only",
            flag=True,
        )
    )
    return checks
