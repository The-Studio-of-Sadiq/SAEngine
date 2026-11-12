"""The design spectrum reduced by a ductility factor and an overstrength factor (method
``ductilityOverstrength`` of the pack's ``seismic.designSpectrum``; alpha 9 C17, the form of
the Mexico City NTC-Sismo spectra).

The elastic spectrum of the site class (a zone of the city's map, or the site's own parameters
from the code authority's tool) is a = a0 + (c - a0) T / Ta below Ta, the plateau c to Tb and
c (Tb / T)^r beyond (the zone form); with the site-specific parameter k the branch beyond Tb is
c p (Tb / T)² with p = k + (1 - k)(Tb / T)². The design ordinate is a / (Q' R) times the
importance factor, Q the seismic behaviour factor (the system's R in the pack's ``systems``):

- zone form (no k): Q' = 1 + (Q - 1) T / Ta below Ta, Q beyond; R = 1;
- site-specific form (k given): Q' = 1 + (Q - 1) √(β / k) T / Ta below Ta,
  1 + (Q - 1) √(β / k) to Tb, 1 + (Q - 1) √(β p / k) beyond; R = k1 R0 + k2 with R0 of the
  pack's ``overstrength`` points by Q and k2 = coefficient [1 - (T / Ta)^½] >= 0;
- Q' times the regularity factor of the structure (1 when regular), at least 1.

Every number comes from the pack's ``ductility`` block
(:class:`saengine.codes.tables.DuctilityOverstrength`), overridable per project.

Units: g, s.
"""

from __future__ import annotations

import math
from typing import Any


def site(site_class: str, rule: Any) -> Any:
    """The site class's spectrum parameters; ValueError when the pack gives none."""
    found = rule.sites.get(site_class)
    if found is None:
        raise ValueError(
            f"the code pack gives no spectrum for site class {site_class!r} "
            f"(seismic.designSpectrum.ductility.sites: {', '.join(rule.sites)})"
        )
    return found


def _p(period: float, s: Any) -> float:
    return s.k + (1 - s.k) * (s.tb / period) ** 2


def elastic_ordinate(period: float, site_class: str, rule: Any) -> float:
    """a(T) [g] of the elastic spectrum of ``site_class`` (see the module notes)."""
    s = site(site_class, rule)
    beta = rule.beta
    if period < s.ta:
        return s.a0 + (beta * s.c - s.a0) * period / s.ta
    if period < s.tb:
        return beta * s.c
    if s.k is not None:
        return beta * s.c * _p(period, s) * (s.tb / period) ** 2
    return beta * s.c * (s.tb / period) ** s.r


def ductility_factor(period: float, site_class: str, q: float, rule: Any) -> float:
    """Q' at ``period`` for the behaviour factor ``q``, with the regularity factor, at least
    1 (see the module notes)."""
    s = site(site_class, rule)
    if s.k is None:
        reduced = 1 + (q - 1) * period / s.ta if period < s.ta else q
    else:
        root = math.sqrt(rule.beta / s.k)
        if period < s.ta:
            reduced = 1 + (q - 1) * root * period / s.ta
        elif period < s.tb:
            reduced = 1 + (q - 1) * root
        else:
            reduced = 1 + (q - 1) * math.sqrt(rule.beta * _p(period, s) / s.k)
    return max(1.0, rule.regularityFactor * reduced)


def overstrength_factor(period: float, site_class: str, q: float, rule: Any) -> float:
    """R at ``period``: 1 in the zone form; k1 R0 + k2 in the site-specific form (see the
    module notes)."""
    s = site(site_class, rule)
    if s.k is None or not rule.overstrength:
        return 1.0
    points = sorted(rule.overstrength)
    r0 = next((r for qq, r in reversed(points) if q >= qq - 1e-9), points[0][1])
    k2 = max(0.0, rule.k2Coefficient * (1 - math.sqrt(period / s.ta))) if period < s.ta else 0.0
    return rule.redundancy * r0 + k2


def design_ordinate(period: float, site_class: str, q: float, rule: Any) -> float:
    """a / (Q' R) [g] (the importance factor not included)."""
    return elastic_ordinate(period, site_class, rule) / (
        ductility_factor(period, site_class, q, rule)
        * overstrength_factor(period, site_class, q, rule)
    )


def describe(period: float, site_class: str, q: float, rule: Any) -> str:
    """The terms in words, for the notes and the report."""
    a = elastic_ordinate(period, site_class, rule)
    qp = ductility_factor(period, site_class, q, rule)
    r = overstrength_factor(period, site_class, q, rule)
    return (
        f"a = {a:.4f} g at T = {period:.3f} s (site {site_class}), Q = {q:g}, Q' = {qp:.3f}, "
        f"R = {r:.3f}: a / (Q' R) = {a / (qp * r):.4f} g"
    )
