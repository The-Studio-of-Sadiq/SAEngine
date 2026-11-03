"""Design spectrum shapes a code pack picks by id (``seismic.designSpectrum.method``).

The elastic shape (S, TB, TC, TD with the plateau 2.5·η) is shared by the codes SAEngine knows
and stays in :func:`saengine.fem.loads.normalized_spectrum`. How the design spectrum follows
from it differs:

- ``reducedElastic`` (the default pack's): Sa = pgaFactor·Z·I/R·Cs(T), see
  :func:`saengine.fem.loads.design_acceleration`;
- ``behaviourFactor`` (:func:`behaviour_factor_spectrum`): the design spectrum for elastic
  analysis with a behaviour factor q, the short-period branch running from 2/3 at T = 0 to
  2.5/q at TB, and a lower bound β·ag from TC on (EN 1998-1 3.2.2.5, Eqs 3.13-3.16).

Pure functions; the numbers come from the code pack in force.
"""

from __future__ import annotations


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
