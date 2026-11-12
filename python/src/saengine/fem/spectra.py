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
  (:func:`shape_factor_acceleration`);
- ``influenceCoefficient`` (alpha 9 C20, the GB 50011 form): the seismic influence coefficient
  α(T) = αmax × :func:`influence_shape` with the damping adjustment η2, the descending power γ
  and the tail slope η1 of the damping ratio, Z holding αmax; the rare earthquake's ratio for
  the elasto-plastic drift (:func:`rare_ratio`).

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


def elastic_spectrum(
    period: float,
    ag: float,
    soil: float,
    tb: float,
    tc: float,
    td: float,
    plateau: float = 2.5,
    eta: float = 1.0,
) -> float:
    """P5: Se(T) [g], the elastic response spectrum of the same shape (the target of the
    nonlinear time histories of a ``behaviourFactor`` pack; EN 1998-1 3.2.2.2, Eqs 3.2-3.5):

        0 ≤ T ≤ TB:   ag·S·[1 + T/TB·(η·plateau - 1)]
        TB ≤ T ≤ TC:  ag·S·η·plateau
        TC ≤ T ≤ TD:  ag·S·η·plateau·TC/T
        TD ≤ T:       ag·S·η·plateau·TC·TD/T²

    ``eta`` the damping correction (1 at 5 %)."""
    top = ag * soil * eta * plateau
    if period <= tb:
        if tb <= 0:
            return top
        return ag * soil * (1 + period / tb * (eta * plateau - 1))
    if period <= tc:
        return top
    if period <= td:
        return top * tc / period
    return top * tc * td / period**2


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
        value += _power_term(chosen.c, chosen.t0, t, chosen.n)
    c2 = getattr(chosen, "c2", 0.0)
    if c2:  # Alpha 9 C21: the second power term (NBC 105:2020 type)
        value += _power_term(c2, chosen.t0, t, chosen.n2)
    d = getattr(chosen, "d", 0.0)
    if d:  # Alpha 9 C24: the divisor 1 + d (t0 / T)^m (NCh 433 Eq 6-10 type)
        value /= 1.0 + _power_term(d, chosen.t0, t, getattr(chosen, "m", 1.0))
    if chosen.most is not None:
        value = min(value, chosen.most)
    return value


def _power_term(c: float, t0: float, t: float, n: float) -> float:
    """c (t0 / T)^n of a shape branch; at T = 0 infinite, or (alpha 9 C24) 0 for a negative
    power n (a power of T / t0)."""
    if t > 0:
        return c * (t0 / t) ** n
    return 0.0 if n < 0 else math.inf


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
    """kμ: alpha 9 C24, with the pack's ``ductilityForm`` "periodRatio" (NCh 433 Eq 6-11 type)
    1 + T / (ratioShare T0 + T / μ), T0 the site class's ``ratioPeriods`` (μ without one);
    else μ without the pack's ``ductilityPeriod`` (AS 1170.4); else (NZS 1170.5 5.2.1.1)
    μ for T >= ductilityPeriod, (μ - 1) T / ductilityPeriod + 1 below; for the
    ``softClasses`` μ for T >= ``softPeriod`` or μ below ``softDuctility``, else
    (μ - softDuctility) T / softPeriod + softDuctility. T taken at least
    ``ductilityMinPeriod``."""
    mu = float(mu)
    if getattr(rule, "ductilityForm", "linear") == "periodRatio":  # Alpha 9 C24 (NCh 433 R*)
        t0 = rule.ratioPeriods.get(site_class)
        if t0 is None or rule.ratioShare is None:
            return mu
        t = max(float(period), 0.0)
        return 1.0 + t / (float(rule.ratioShare) * float(t0) + t / mu)
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
    5.2.1.1). Alpha 9 C24: × the soil factor S of the site class and Z (``soilFactors``, 1
    without), at most the ``capByDuctility`` share of μ × Z I S, at least ``leastSoilShare``
    × Z I S (E.030 2018, NCh 433 type)."""
    if mu <= 0:
        raise ValueError("the structural ductility factor μ must be positive")
    sp = performance_factor(mu, rule)
    k_mu = ductility_factor(period, mu, site_class, rule)
    cd = hazard_product(z, importance, rule) * shape * near_fault_factor(period, rule) * sp / k_mu
    soil = soil_factor(site_class, z, rule)
    if soil != 1.0:
        cd *= soil
    caps = getattr(rule, "capByDuctility", None)
    if caps:
        cd = min(cd, _along(list(caps), float(mu)) * float(z) * float(importance) * soil)
    least = 0.0
    if rule.leastZShare is not None:
        least = rule.leastZShare * float(z) + float(rule.leastOffset or 0.0)
    if rule.leastFloor is not None:
        least = max(least, float(rule.leastFloor))
    if getattr(rule, "leastSoilShare", None) is not None:
        least = max(least, float(rule.leastSoilShare) * float(z) * soil)
    return max(cd, least * float(importance)) if least > 0 else cd


def soil_factor(site_class: str, z: float, rule: Any) -> float:
    """Alpha 9 C24: S of the site class at the site's Z by the pack's ``soilFactors`` (Z from,
    S) steps: the last step at or below Z, the first below them all; 1 without steps."""
    steps = (getattr(rule, "soilFactors", None) or {}).get(site_class)
    if not steps:
        return 1.0
    ordered = sorted((float(a), float(b)) for a, b in steps)
    found = ordered[0][1]
    for z_from, value in ordered:
        if float(z) >= z_from - 1e-12:
            found = value
    return found


def shape_factor_terms(
    period: float, site_class: str, z: float, importance: float, mu: float, rule: Any
) -> dict[str, float]:
    """The terms of :func:`shape_factor_acceleration`, for the notes and the report."""
    terms = {
        "ZI": hazard_product(z, importance, rule),
        "Sp": performance_factor(mu, rule),
        "kmu": ductility_factor(period, mu, site_class, rule),
        "N": near_fault_factor(period, rule),
    }
    if getattr(rule, "soilFactors", None):  # Alpha 9 C24
        terms["S"] = soil_factor(site_class, z, rule)
    return terms


# ───────── alpha 9 C20: the seismic influence coefficient (method influenceCoefficient) ─────────


def damped_term(term: Any, damping: float | None, reference: float) -> float:
    """base + (ref - ζ) / (a + b ζ) of a :class:`saengine.codes.tables.DampedTerm`, at least its
    ``least`` (``damping`` None: the reference ζ)."""
    zeta = reference if damping is None else float(damping)
    value = term.base + (reference - zeta) / (term.a + term.b * zeta)
    return max(value, term.least) if term.least is not None else value


def influence_terms(damping: float | None, rule: Any) -> dict[str, float]:
    """γ, η1 and η2 of the damping ratio ``damping`` (GB 50011 Eqs 5.1.5-1 to -3 type)."""
    ref = float(rule.referenceDamping)
    return {
        "gamma": damped_term(rule.gamma, damping, ref),
        "eta1": damped_term(rule.eta1, damping, ref),
        "eta2": damped_term(rule.eta2, damping, ref),
    }


def influence_shape(period: float, tg: float, damping: float | None, rule: Any) -> float:
    """α(T) / αmax of the influence coefficient spectrum (``rule`` the pack's
    :class:`saengine.codes.tables.InfluenceCoefficientRule`, ``tg`` the characteristic period
    [s]):

        0 ≤ T ≤ T1:          riseStart + (η2 - riseStart) T / T1     (T1 = risePeriod)
        T1 ≤ T ≤ Tg:         η2
        Tg ≤ T ≤ k Tg:       η2 (Tg / T)^γ                           (k = tailFrom)
        k Tg ≤ T ≤ longest:  η2 (1/k)^γ - η1 (T - k Tg)              (at least 0)

    and its value at ``longest`` beyond."""
    terms = influence_terms(damping, rule)
    eta2, gamma, eta1 = terms["eta2"], terms["gamma"], terms["eta1"]
    t = min(max(float(period), 0.0), float(rule.longest))
    rise = float(rule.risePeriod)
    tg = max(float(tg), rise)
    if t <= rise:
        return rule.riseStart + (eta2 - rule.riseStart) * t / rise
    if t <= tg:
        return eta2
    tail = float(rule.tailFrom) * tg
    if t <= tail:
        return eta2 * (tg / t) ** gamma
    return max(eta2 * (1.0 / float(rule.tailFrom)) ** gamma - eta1 * (t - tail), 0.0)


def rare_alpha_max(zone: int | None, rule: Any) -> float | None:
    """αmax of the rare earthquake in ``zone`` (the rule's ``rare``); None where not given."""
    if zone is None:
        return None
    found = rule.rare.get(int(zone))
    return None if found is None else float(found)


def rare_ratio(
    period: float, tg: float, zone: int | None, z: float, damping: float | None, rule: Any
) -> float | None:
    """α_rare(T) / α(T): the rare earthquake's influence coefficient over the frequent one's
    (αmax ``z``) at ``period``, the rare one on Tg + ``rarePeriodIncrease`` in the
    ``rareIncreaseZones``; None without the zone's rare αmax."""
    top = rare_alpha_max(zone, rule)
    if top is None or z <= 0:
        return None
    tg_rare = float(tg)
    if zone is not None and int(zone) in rule.rareIncreaseZones:
        tg_rare += float(rule.rarePeriodIncrease)
    frequent = z * influence_shape(period, tg, damping, rule)
    if frequent <= 0:
        return None
    return top * influence_shape(period, tg_rare, damping, rule) / frequent
