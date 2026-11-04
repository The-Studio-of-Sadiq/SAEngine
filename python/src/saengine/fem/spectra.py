"""Design spectrum shapes a code pack picks by id (``seismic.designSpectrum.method``).

The elastic shape (S, TB, TC, TD with the plateau 2.5·η) is shared by the codes SAEngine knows
and stays in :func:`saengine.fem.loads.normalized_spectrum`. How the design spectrum follows
from it differs:

- ``reducedElastic`` (the default pack's): Sa = pgaFactor·Z·I/R·Cs(T), see
  :func:`saengine.fem.loads.design_acceleration`;
- ``behaviourFactor`` (:func:`behaviour_factor_spectrum`): the design spectrum for elastic
  analysis with a behaviour factor q, the short-period branch running from 2/3 at T = 0 to
  2.5/q at TB, and a lower bound β·ag from TC on (EN 1998-1 3.2.2.5, Eqs 3.13-3.16);
- ``shapeFactors`` (alpha 9 C18, the AS 1170.4 / NZS 1170.5 form): the site class's spectral
  shape factor Ch(T) from its ``shape`` branches (:func:`shape_factor`), Cd(T) = Z I Ch(T)
  N(T, D) Sp / kμ with R standing for the structural ductility factor μ
  (:func:`shape_factor_acceleration`).

Pure functions; the numbers come from the code pack in force.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any


def behaviour_factor_spectrum(
    period: float,
    ag: float,
    soil: float,
    tb: float,
    tc: float,
    td: float,
    q: float,
    plateau: float = 2.5,
    beta: float = 0.0,
) -> float:
    """Sd(T) [g] of the design spectrum with the behaviour factor ``q``:

        0 ≤ T ≤ TB:   ag·S·[2/3 + T/TB·(plateau/q - 2/3)]
        TB ≤ T ≤ TC:  ag·S·plateau/q
        TC ≤ T ≤ TD:  ag·S·plateau/q·TC/T        ≥ β·ag
        TD ≤ T:       ag·S·plateau/q·TC·TD/T²    ≥ β·ag

    ``ag`` the design ground acceleration on type A ground (γI·agR) [g], ``soil`` S."""
    if q <= 0:
        raise ValueError("behaviour factor q must be positive")
    top = ag * soil * plateau / q
    if period <= tb:
        if tb <= 0:
            return top
        return ag * soil * (2 / 3 + period / tb * (plateau / q - 2 / 3))
    if period <= tc:
        return top
    if period <= td:
        return max(top * tc / period, beta * ag)
    return max(top * tc * td / period**2, beta * ag)


# ──────────── alpha 9 C18: spectral shape factors with ductility (method shapeFactors) ────────────


def shape_factor(period: float, branches: list[Any], static: bool = False) -> float:
    """Ch(T) of a site class's ``shape`` branches (:class:`saengine.codes.tables.ShapeBranch`):
    the first branch whose ``upTo`` is at or above T (the last one beyond), Ch = a + b T +
    c (t0 / T)^n, at most its ``most``. ``static`` (the equivalent static method with the
    pack's ``staticPlateau``): below the first branch's end, the value at its end."""
    if not branches:
        raise ValueError("the site class gives no spectral shape factor branches")
    t = max(float(period), 0.0)
    if static and branches[0].upTo is not None and t < branches[0].upTo:
        t = float(branches[0].upTo)
    chosen = branches[-1]
    for branch in branches:
        if branch.upTo is None or t <= branch.upTo + 1e-12:
            chosen = branch
            break
    value = chosen.a + chosen.b * t
    if chosen.c:
        value += chosen.c * (chosen.t0 / t) ** chosen.n if t > 0 else math.inf
    if chosen.most is not None:
        value = min(value, chosen.most)
    return value


def _along(points: list[Any], x: float) -> float:
    pts = sorted((float(a), float(b)) for a, b in points)
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in pairwise(pts):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 > x0 else y1
    return pts[-1][1]


def performance_factor(mu: float, rule: Any) -> float:
    """Sp of the structural ductility factor μ by the pack's ``performance`` (μ, Sp) points
    (linear between, the end values beyond)."""
    return _along(list(rule.performance), float(mu))


def ductility_factor(period: float, mu: float, site_class: str, rule: Any) -> float:
    """kμ: μ without the pack's ``ductilityPeriod`` (AS 1170.4); else (NZS 1170.5 5.2.1.1)
    μ for T >= ductilityPeriod, (μ - 1) T / ductilityPeriod + 1 below; for the
    ``softClasses`` μ for T >= ``softPeriod`` or μ below ``softDuctility``, else
    (μ - softDuctility) T / softPeriod + softDuctility. T taken at least
    ``ductilityMinPeriod``."""
    mu = float(mu)
    if rule.ductilityPeriod is None:
        return mu
    t = max(float(period), float(rule.ductilityMinPeriod))
    if site_class in rule.softClasses and rule.softPeriod is not None:
        base = float(rule.softDuctility if rule.softDuctility is not None else 1.0)
        if t >= rule.softPeriod or mu < base:
            return mu
        return (mu - base) * t / rule.softPeriod + base
    if t >= rule.ductilityPeriod:
        return mu
    return (mu - 1.0) * t / rule.ductilityPeriod + 1.0


def near_fault_factor(period: float, rule: Any) -> float:
    """N(T, D): 1 without the site's distance D to the nearest major fault
    (``faultDistance``, a project's Code Value) or from ``nearFaultNone`` km on; Nmax(T) (the
    ``nearFault`` points) up to ``nearFaultFull`` km; linear in D between (NZS 1170.5 3.1.6)."""
    distance = rule.faultDistance
    if distance is None or not rule.nearFault or distance >= rule.nearFaultNone:
        return 1.0
    nmax = _along(list(rule.nearFault), float(period))
    if distance <= rule.nearFaultFull:
        return nmax
    share = (rule.nearFaultNone - distance) / (rule.nearFaultNone - rule.nearFaultFull)
    return 1.0 + (nmax - 1.0) * share


def hazard_product(z: float, importance: float, rule: Any) -> float:
    """Z × the importance (kp, R) within the pack's ``hazardMin`` and ``hazardMax``."""
    product = float(z) * float(importance)
    if rule.hazardMin is not None:
        product = max(product, rule.hazardMin)
    if rule.hazardMax is not None:
        product = min(product, rule.hazardMax)
    return product


def shape_factor_acceleration(
    period: float, site_class: str, z: float, importance: float, mu: float, shape: float, rule: Any
) -> float:
    """Cd(T) = (Z I) Ch(T) N(T, D) Sp / kμ [g] (``shape`` = Ch(T)), at least
    max(``leastZShare`` Z + ``leastOffset``, ``leastFloor``) × I (AS 1170.4 6.2, NZS 1170.5
    5.2.1.1)."""
    if mu <= 0:
        raise ValueError("the structural ductility factor μ must be positive")
    sp = performance_factor(mu, rule)
    k_mu = ductility_factor(period, mu, site_class, rule)
    cd = hazard_product(z, importance, rule) * shape * near_fault_factor(period, rule) * sp / k_mu
    least = 0.0
    if rule.leastZShare is not None:
        least = rule.leastZShare * float(z) + float(rule.leastOffset or 0.0)
    if rule.leastFloor is not None:
        least = max(least, float(rule.leastFloor))
    return max(cd, least * float(importance)) if least > 0 else cd


def shape_factor_terms(
    period: float, site_class: str, z: float, importance: float, mu: float, rule: Any
) -> dict[str, float]:
    """The terms of :func:`shape_factor_acceleration`, for the notes and the report."""
    return {
        "ZI": hazard_product(z, importance, rule),
        "Sp": performance_factor(mu, rule),
        "kmu": ductility_factor(period, mu, site_class, rule),
        "N": near_fault_factor(period, rule),
    }
