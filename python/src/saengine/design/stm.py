"""Strut-and-tie capacities: the shared building blocks of every strut-and-tie model, the deep
members' own (pile caps, :mod:`saengine.substructure.pilecap`; deep beams, transfer girders
and corbels, :mod:`saengine.design.deep_beams`) and the general model of any D-region
(:mod:`saengine.design.stm_model`).

The procedure is the code pack's (``foundations.strutAndTie``, its clauses in the table's
``sources``; BNBC 2020: Part 6 Appendix I and Sec 6.2.3.2.6):

- a strut: Fns = fce Acs + As' fs', fce = effective × βs × f'c, the smaller of the strut's and
  the nodal zones' at its ends; βs ``betaPrism`` for a strut of uniform section, ``betaBottle``
  for a bottle-shaped one with its crack-control web steel, ``betaBottlePlain`` λ without it,
  ``betaTension`` in a tension member or flange and ``betaOther`` λ for every other strut;
- a tie: Fnt = Ats fy + Atp (fse + Δfp), fse + Δfp ≤ fpy;
- a node face: Fnn = fce Anz, fce = effective × βn × f'c, βn ``betaCCC`` / ``betaCCT`` /
  ``betaCTT`` by the number of ties it anchors (none, one, two or more);
- the angle between a strut and a tie meeting at a node at least ``minAngle``;
- the crack-control web steel of a bottle-shaped strut: Σ Asi sin αi / (bs si) ≥ ``webRatio``
  up to f'c ``webRatioFcMax``, one direction only at ``webAngleMin`` or more;
- all against φ Fn ≥ Fu, φ the pack's ``factors.phi.strutAndTie``.

Units: mm, N, MPa.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from saengine.codes import context as code_context

__all__ = [
    "beta_node",
    "beta_strut",
    "cite",
    "covers_general",
    "effective_strength",
    "factor",
    "min_angle",
    "node_capacity",
    "phi",
    "strut_capacity",
    "strut_nominal",
    "strut_width",
    "tie_capacity",
    "tie_nominal",
    "web_ratio",
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
    "effective": 0.85,
    "betaTension": 0.4,
    "betaOther": 0.6,
    "webRatioFcMax": 40.0,
    "webAngleMin": 40.0,
    "spreadSlope": 2.0,
    "deltaFpBonded": 420.0,
    "deltaFpUnbonded": 70.0,
    "dRegionDepth": 1.0,
}

#: The strut shapes of :func:`beta_strut`.
STRUT_SHAPES = ("prism", "bottle", "tension", "other")


def _values() -> Any:
    """The pack's ``foundations.strutAndTie`` group (read with ``.get``)."""
    return code_context.table("foundations").strutAndTie


def phi() -> float:
    """φ of strut-and-tie models and of the struts, ties, nodal zones and bearing areas in them:
    the pack's ``factors.phi.strutAndTie``."""
    return float(code_context.table("factors").phi["strutAndTie"])


def factor(name: str) -> float:
    """The pack's ``foundations.strutAndTie`` value ``name``: ``tieArm`` (the deep members' tie
    lever arm over d), ``betaCCC`` / ``betaCCT`` / ``betaCTT`` (βn), ``betaPrism`` /
    ``betaBottle`` / ``betaBottlePlain`` / ``betaTension`` / ``betaOther`` (βs), ``effective``
    (the 0.85 of fce), ``minAngle`` and ``webAngleMin`` (degrees), ``webRatio`` and
    ``webRatioFcMax`` (the crack-control web steel), ``spreadSlope``, ``deltaFpBonded`` /
    ``deltaFpUnbonded`` (MPa), ``dRegionDepth``."""
    value = _values().get(name)
    return float(_DEFAULTS[name] if value is None else value)


def covers_general() -> bool:
    """Whether the pack in force covers strut-and-tie models of any D-region."""
    return bool(_values().get("general", False))


def lightweight_bottle() -> bool:
    """Whether a bottle-shaped strut without its web steel takes βs times λ."""
    value = _values().get("lightweightBottle")
    return True if value is None else bool(value)


def cite(key: str) -> str:
    """The short clause of ``strutAndTie.<key>`` in the pack's ``foundations`` sources (the
    text before the page), "" when the pack names none."""
    sources = getattr(code_context.table("foundations"), "sources", None) or {}
    text = sources.get(f"strutAndTie.{key}", "")
    return text.split(" (", 1)[0]


def min_angle() -> float:
    """Least angle [degrees] between a strut and a tie at a node."""
    return factor("minAngle")


def effective_strength(fc: float, beta: float) -> float:
    """fce = effective × β × f'c [MPa] of a strut (β = βs) or a nodal zone (β = βn)."""
    return factor("effective") * beta * fc


def beta_strut(shape: str = "bottle", web: bool = True, lam: float = 1.0) -> float:
    """βs of a strut: ``shape`` "prism" (uniform section), "bottle" (bottle-shaped, ``web``:
    with its crack-control web steel), "tension" (in a tension member or flange) or "other";
    λ of lightweight concrete where the pack applies it."""
    if shape == "prism":
        return factor("betaPrism")
    if shape == "tension":
        return factor("betaTension")
    if shape == "bottle":
        if web:
            return factor("betaBottle")
        return factor("betaBottlePlain") * (lam if lightweight_bottle() else 1.0)
    return factor("betaOther") * lam


def beta_node(ties: int) -> float:
    """βn of a nodal zone anchoring ``ties`` ties: none (C-C-C), one (C-C-T), two or more."""
    return factor("betaCCC" if ties <= 0 else "betaCCT" if ties == 1 else "betaCTT")


def tie_capacity(area: float, fy: float) -> float:
    """φ Fnt = φ As fy [N] of a non-prestressed tie of ``area`` mm²."""
    return phi() * area * fy


def tie_nominal(
    area: float,
    fy: float,
    prestress_area: float = 0.0,
    fse: float = 0.0,
    fpy: float = 0.0,
    bonded: bool = True,
) -> float:
    """Fnt = Ats fy + Atp (fse + Δfp) [N], fse + Δfp at most fpy; Δfp the pack's for bonded
    or unbonded tendons."""
    stress = 0.0
    if prestress_area > 0:
        delta = factor("deltaFpBonded" if bonded else "deltaFpUnbonded")
        stress = fse + delta if fpy <= 0 else min(fse + delta, fpy)
    return area * fy + prestress_area * stress


def node_capacity(fc: float, area: float, kind: str = "CCT") -> float:
    """φ Fnn = φ fce Anz [N] of a node face of ``area`` mm²; ``kind`` "CCC", "CCT" or "CTT"."""
    return phi() * effective_strength(fc, factor(f"beta{kind}")) * area


def strut_capacity(fc: float, area: float, shape: str = "bottle", web: bool = True) -> float:
    """φ Fns = φ fce Acs [N] of a strut of ``area`` mm² (no compression steel, λ = 1):
    ``shape`` as in :func:`beta_strut`."""
    return phi() * effective_strength(fc, beta_strut(shape, web)) * area


def strut_nominal(fce: float, area: float, steel_area: float = 0.0, fs: float = 0.0) -> float:
    """Fns = fce Acs + As' fs' [N] of a strut with ``steel_area`` mm² of anchored, tied
    compression steel along it at stress ``fs``."""
    return fce * area + steel_area * fs


def web_ratio(layers: Iterable[tuple[float, float, float]], thickness: float) -> float:
    """Σ Asi sin αi / (bs si) of the web steel ``layers`` (area of a layer's bars Asi [mm²],
    spacing si [mm], angle αi to the strut [degrees]) crossing a strut ``thickness`` bs thick."""
    total = 0.0
    for area, spacing, angle in layers:
        if spacing > 0 and thickness > 0:
            total += area / (thickness * spacing) * abs(math.sin(math.radians(angle)))
    return total


def strut_width(bearing: float, tie_height: float, angle: float) -> float:
    """Width [mm] of a strut at a C-C-T node over a bearing of length ``bearing``, the tie's
    effective height ``tie_height`` and the strut at ``angle`` [rad] to the tie: lb sin θ +
    wt cos θ (the extended nodal zone)."""
    return bearing * math.sin(angle) + tie_height * math.cos(angle)
