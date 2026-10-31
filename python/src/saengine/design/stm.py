"""Strut-and-tie capacities shared by the deep members: pile caps
(:mod:`saengine.substructure.pilecap`), deep beams and transfer girders
(:mod:`saengine.design.deep_beams`).

BNBC 2020 Part 6 Sec 6.2.3.2 (p. 897) gives φ = 0.75 for strut-and-tie models, and Sec 6.4.6
(deep beams) sends their design to the strut-and-tie method; the procedure here is the one of
ACI 318-19 Chapter 23, which BNBC follows:

- a strut: Fns = fce Acs, fce = 0.85 βc βs f'c (23.4.1, 23.4.3; βc = 1 on the safe side), βs
  1.0 for a prism-shaped strut, 0.75 for a bottle-shaped one with the distributed web steel of
  23.5 and 0.6 λ without it (Table 23.4.3);
- a tie: Fnt = As fy (23.7.2.1);
- a node face: Fnn = fce Anz, fce = 0.85 βc βn f'c, βn 1.0 (C-C-C), 0.8 (C-C-T), 0.6 (C-T-T)
  (23.9.1, Table 23.9.2);
- the angle between a strut and a tie meeting at a node at least 25° (23.2.7);
- all against φ F ≥ Fu with φ of BNBC Sec 6.2.3.2.

The factors are the pack's: ``factors.phi.strutAndTie`` and ``foundations.strutAndTie``.
Units: mm, N, MPa.
"""

from __future__ import annotations

import math

from saengine.codes import context as code_context

__all__ = [
    "factor",
    "min_angle",
    "node_capacity",
    "phi",
    "strut_capacity",
    "strut_width",
    "tie_capacity",
]

#: The pack's ``foundations.strutAndTie`` defaults for packs written before they were added.
_DEFAULTS = {
    "tieArm": 0.9,
    "betaCCC": 1.0,
    "betaCCT": 0.8,
    "betaCTT": 0.6,
    "betaPrism": 1.0,
    "betaBottle": 0.75,
    "betaBottlePlain": 0.6,
    "minAngle": 25.0,
    "webRatio": 0.003,
}


def phi() -> float:
    """φ of strut-and-tie models: the pack's ``factors.phi.strutAndTie`` (BNBC 2020 Part 6
    Sec 6.2.3.2, p. 897: 0.75)."""
    return float(code_context.table("factors").phi["strutAndTie"])


def factor(name: str) -> float:
    """The pack's ``foundations.strutAndTie`` value ``name`` (ACI 318-19 Chapter 23):
    ``tieArm`` (the tie's lever arm over d, SAEngine's 0.9), ``betaCCC`` / ``betaCCT`` /
    ``betaCTT`` (βn, Table 23.9.2), ``betaPrism`` / ``betaBottle`` / ``betaBottlePlain`` (βs,
    Table 23.4.3), ``minAngle`` (23.2.7, degrees), ``webRatio`` (the distributed web steel
    that makes a bottle-shaped strut's βs 0.75, 23.5.1)."""
    values = code_context.table("foundations").strutAndTie
    value = values.get(name)
    return float(_DEFAULTS[name] if value is None else value)


def min_angle() -> float:
    """Least angle [degrees] between a strut and a tie at a node (ACI 318-19 23.2.7)."""
    return factor("minAngle")


def tie_capacity(area: float, fy: float) -> float:
    """φ Fnt = φ As fy [N] of a tie of ``area`` mm² (ACI 318-19 23.7.2.1)."""
    return phi() * area * fy


def node_capacity(fc: float, area: float, kind: str = "CCT") -> float:
    """φ Fnn = φ 0.85 βn f'c Anz [N] of a node face of ``area`` mm²; ``kind`` "CCC", "CCT"
    or "CTT" (ACI 318-19 23.9.1, Table 23.9.2; βc = 1)."""
    return phi() * 0.85 * factor(f"beta{kind}") * fc * area


def strut_capacity(fc: float, area: float, shape: str = "bottle", web: bool = True) -> float:
    """φ Fns = φ 0.85 βs f'c Acs [N] of a strut of ``area`` mm²: ``shape`` "prism" or "bottle";
    a bottle-shaped strut with the web steel of 23.5 (``web``) takes βs = 0.75, else 0.6
    (ACI 318-19 23.4.1, Table 23.4.3; λ = 1, βc = 1)."""
    if shape == "prism":
        beta = factor("betaPrism")
    else:
        beta = factor("betaBottle" if web else "betaBottlePlain")
    return phi() * 0.85 * beta * fc * area


def strut_width(bearing: float, tie_height: float, angle: float) -> float:
    """Width [mm] of a strut at a C-C-T node over a bearing of length ``bearing``, the tie's
    effective height ``tie_height`` and the strut at ``angle`` [rad] to the tie: lb sin θ +
    wt cos θ (ACI 318-19 Fig. R23.2.6b)."""
    return bearing * math.sin(angle) + tie_height * math.cos(angle)
