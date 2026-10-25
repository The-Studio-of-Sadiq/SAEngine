"""Deflection of reinforced-concrete beams and slabs under service loads: BNBC 2020 Part 6
Sec 6.2.5 (pp. 899-903). Units: N, mm, MPa, N·mm.

- Immediate deflection with Ec (Sec 6.1.7.1: 4700 √f'c for normal weight concrete, or the
  material's E; :func:`saengine.design.slender.concrete_modulus`) and the effective moment of
  inertia Ie = (Mcr/Ma)³ Ig + (1 - (Mcr/Ma)³) Icr <= Ig (Eq. 6.6.1, p. 900), Mcr = fr Ig / yt
  (Eq. 6.6.2), fr = 0.62 λ √f'c (Eq. 6.6.3).
- For prismatic members Ie may be taken at midspan for simple and continuous spans and at the
  support for cantilevers (Sec 6.2.5.2.4, p. 901); the average of the positive- and
  negative-moment sections is offered as :func:`averaged_inertia`.
- Long-term deflection: the immediate deflection under the sustained load times
  λΔ = ξ / (1 + 50 ρ') (Eq. 6.6.4, p. 901), ρ' at midspan (support for cantilevers), ξ 2.0 for
  5 years or more, 1.4 at 12 months, 1.2 at 6, 1.0 at 3 (linear between).
- Limits, Table 6.6.2 (p. 902): immediate live-load deflection l/180 (flat roofs) and l/360
  (floors); the part after the nonstructural elements are attached (long-term deflection under
  all sustained loads plus the immediate deflection of the additional live load) l/480 where
  they are likely to be damaged by large deflections (masonry partitions), l/240 where not.
- Minimum thickness, Table 6.6.1 (p. 900): members not supporting or attached to construction
  likely to be damaged need no deflection calculation when at least l/16, l/18.5, l/21 (beams:
  simply supported, one end, both ends continuous) or l/8 (cantilever), times (0.4 + fy/700) for
  fy other than 420 MPa (Sec 6.2.5.2.1). Slab thickness is :mod:`saengine.design.slab`'s.

The analysis deflection is linear, with the analysis's own stiffness E·I: the immediate
deflection is that deflection times E·I / (Ec Ie). It must be the member's own deflection,
relative to the chord between its supports (for a cantilever, the tip relative to the
support), under unfactored service load cases.

The additional live load's immediate deflection is taken as the whole live-load deflection
(on the safe side: no part of it is assumed to occur before the partitions are built), and no
deflection before the attachment of nonstructural elements is subtracted (Table 6.6.2 note †
permits it with data SAEngine does not have).

Limits and the ξ table are read from the code pack's ``concrete`` table, group ``deflection``
(:class:`DeflectionLimits`).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from saengine.design.rc import STEEL_E, DesignError, RcSection
from saengine.library.objects import RectangleProfile


def _check(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from saengine.design.check import _check as check

    return check(*args, **kwargs)


@dataclass(frozen=True)
class DeflectionLimits:
    """Table 6.6.2's span divisors, the ξ table and Table 6.6.1's cantilever divisors."""

    live_floor: float  # l / this: floors, immediate live-load deflection
    live_roof: float  # flat roofs
    attached_sensitive: float  # after attachment, elements likely to be damaged
    attached_insensitive: float  # after attachment, elements not likely to be damaged
    xi: dict[float, float]  # months -> ξ
    beam_divisors: tuple[float, float, float]  # simply supported, one end, both ends continuous
    cantilever_beam: float

    @classmethod
    def from_pack(cls) -> DeflectionLimits:
        from saengine.codes import context as code_context

        concrete = code_context.table("concrete")
        t = concrete.deflection
        return cls(
            live_floor=float(t["liveFloor"]),
            live_roof=float(t["liveRoof"]),
            attached_sensitive=float(t["attachedSensitive"]),
            attached_insensitive=float(t["attachedInsensitive"]),
            xi={float(k): float(v) for k, v in t["xi"].items()},
            beam_divisors=tuple(float(v) for v in concrete.beamThickness),
            cantilever_beam=float(t["cantileverBeam"]),
        )


# ─────────────────────────────────────── section properties ───────────────────────────────────────


@dataclass(frozen=True)
class Strip:
    """A rectangular piece of concrete: ``width`` between ``top`` and ``bottom`` [mm from the
    compression face, bottom > top]."""

    width: float
    top: float
    bottom: float


@dataclass(frozen=True)
class SectionStiffness:
    ig: float  # mm⁴, gross concrete section about its centroid (bars ignored)
    yt: float  # mm, centroid to the extreme tension fibre
    icr: float  # mm⁴, cracked transformed section
    c: float  # mm, cracked neutral axis depth from the compression face
    rho_prime: float  # compression steel As' / (b d)
    d: float  # mm


def _gross(strips: Sequence[Strip]) -> tuple[float, float, float]:
    """(area, centroid depth, I about the centroid)."""
    area = sum(s.width * (s.bottom - s.top) for s in strips)
    ybar = sum(s.width * (s.bottom - s.top) * (s.top + s.bottom) / 2 for s in strips) / area
    inertia = 0.0
    for s in strips:
        h = s.bottom - s.top
        inertia += s.width * h**3 / 12 + s.width * h * ((s.top + s.bottom) / 2 - ybar) ** 2
    return area, ybar, inertia


def _compression(strips: Sequence[Strip], c: float) -> tuple[float, float]:
    """(first moment about the neutral axis at depth c, second moment) of the concrete above
    it."""
    q = i = 0.0
    for s in strips:
        top, bottom = s.top, min(s.bottom, c)
        if bottom <= top:
            continue
        q += s.width * ((c - top) ** 2 - (c - bottom) ** 2) / 2
        i += s.width * ((c - top) ** 3 - (c - bottom) ** 3) / 3
    return q, i


def cracked_section(
    strips: Sequence[Strip],
    bars: Sequence[tuple[float, float]],
    n: float,
) -> tuple[float, float]:
    """(c, Icr) of a cracked transformed section: the concrete ``strips`` in compression above
    the neutral axis, ``bars`` (depth from the compression face [mm], area [mm²]) transformed by
    n (tension) or n - 1 (compression, the concrete they displace taken out)."""
    depth = max(s.bottom for s in strips)

    def moment(c: float) -> float:
        q, _ = _compression(strips, c)
        for y, a in bars:
            q += ((n - 1) if y < c else n) * a * (c - y)
        return q

    lo, hi = 1e-6, depth
    if moment(hi) < 0:
        raise ValueError("no neutral axis inside the section")
    for _ in range(200):
        mid = (lo + hi) / 2
        if moment(mid) > 0:
            hi = mid
        else:
            lo = mid
    c = (lo + hi) / 2
    _, inertia = _compression(strips, c)
    for y, a in bars:
        inertia += ((n - 1) if y < c else n) * a * (y - c) ** 2
    return c, inertia


def section_stiffness(
    section: RcSection,
    ec: float,
    hogging: bool = False,
    flange: tuple[float, float] | None = None,
) -> SectionStiffness:
    """Ig, yt, Icr and ρ' of a rectangular beam or slab strip (a 1000 mm wide
    :class:`RcSection` for a slab) bending with its bottom (sagging) or top (``hogging``) in
    tension. ``flange``: (effective width, slab thickness) [mm] of a slab cast with the beam on
    its top (a T-section; leave it out for a rectangle, which gives the larger deflection)."""
    if not isinstance(section.profile, RectangleProfile):
        raise DesignError("deflection is computed for rectangular sections only")
    b, h = section.profile.xDim, section.profile.yDim
    strips = [Strip(b, 0.0, h)]
    if flange is not None and flange[0] > b and flange[1] > 0:
        bf, hf = flange
        strips = [Strip(bf, 0.0, hf), Strip(b, hf, h)]
    if hogging:  # the compression face is the bottom: mirror the strips
        strips = [Strip(s.width, h - s.bottom, h - s.top) for s in strips]
    _, ybar, ig = _gross(strips)
    yt = h - ybar
    # Bar depth from the compression face: y is up from mid-depth.
    bars = [((h / 2 + bar.y) if hogging else (h / 2 - bar.y), bar.area) for bar in section.bars]
    n = section.es / ec if section.es else STEEL_E / ec
    c, icr = cracked_section(strips, bars, n)
    tension = [(y, a) for y, a in bars if y > h / 2]
    compression = [(y, a) for y, a in bars if y < h / 2]
    if not tension:
        raise ValueError("no bars on the tension face")
    d = sum(y * a for y, a in tension) / sum(a for _, a in tension)
    rho_prime = sum(a for _, a in compression) / (b * d)
    return SectionStiffness(ig, yt, icr, c, rho_prime, d)


def cracking_moment(fc: float, ig: float, yt: float, lam: float = 1.0) -> float:
    """Mcr = fr Ig / yt [N·mm], fr = 0.62 λ √f'c (Eqs. 6.6.2, 6.6.3)."""
    return 0.62 * lam * math.sqrt(fc) * ig / yt


def effective_inertia(ma: float, mcr: float, ig: float, icr: float) -> float:
    """Ie of Eq. 6.6.1 [mm⁴], not more than Ig (Ig when Ma <= Mcr)."""
    ma = abs(ma)
    if ma <= mcr:
        return ig
    r = (mcr / ma) ** 3
    return min(r * ig + (1 - r) * icr, ig)


def averaged_inertia(ie_mid: float, ie_ends: Sequence[float]) -> float:
    """Sec 6.2.5.2.4: the average of the positive (midspan) and negative (support) moment
    sections' Ie, the supports' value the mean of the continuous ends."""
    if not ie_ends:
        return ie_mid
    return (ie_mid + sum(ie_ends) / len(ie_ends)) / 2


def xi_factor(months: float, table: dict[float, float]) -> float:
    """ξ of Sec 6.2.5.2.5 for a load sustained ``months``: linear between the table's points,
    the last value beyond it."""
    points = sorted(table.items())
    if months <= points[0][0]:
        if months < points[0][0]:
            raise ValueError(f"ξ is given from {points[0][0]:g} months")
        return points[0][1]
    for (m0, x0), (m1, x1) in itertools.pairwise(points):
        if months <= m1:
            return x0 + (x1 - x0) * (months - m0) / (m1 - m0)
    return points[-1][1]


def long_term_multiplier(rho_prime: float, xi: float) -> float:
    """λΔ = ξ / (1 + 50 ρ') (Eq. 6.6.4)."""
    return xi / (1 + 50 * rho_prime)


def beam_minimum_depth(
    span: float, continuous_ends: int, fy: float, cantilever: bool, limits: DeflectionLimits
) -> float:
    """Table 6.6.1's least beam depth h [mm] without a deflection calculation, normal weight
    concrete (note (b): × (0.4 + fy/700) for fy other than 420 MPa)."""
    from saengine.library.generator import fy_factor

    divisor = (
        limits.cantilever_beam
        if cantilever
        else limits.beam_divisors[max(0, min(int(continuous_ends), 2))]
    )
    return span / divisor * fy_factor(fy)


# ─────────────────────────────────────── the check ───────────────────────────────────────


@dataclass(frozen=True)
class Deflection:
    span: float  # mm
    ie_dead: float  # mm⁴, at the dead (D + SD) service moment
    ie_sustained: float  # at D + SD + ψ L
    ie_total: float  # at D + SD + L
    mcr: float  # N·mm
    immediate_dead: float  # mm
    immediate_total: float
    immediate_live: float  # immediate_total - immediate_dead
    immediate_sustained: float
    xi: float
    multiplier: float  # λΔ
    long_term: float  # λΔ × immediate_sustained
    after_attachment: float  # long_term + immediate_live
    live_limit: float  # mm
    attached_limit: float  # mm
    notes: tuple[str, ...] = field(default=())

    @property
    def total(self) -> float:
        """Immediate under the whole service load plus the long-term part [mm]."""
        return self.immediate_total + self.long_term


def span_deflection(
    span: float,
    stiffness: SectionStiffness,
    fc: float,
    ec: float,
    ei_analysis: float,
    dead: tuple[float, float],
    live: tuple[float, float],
    sustained_live_share: float,
    roof: bool = False,
    sensitive: bool = True,
    months: float = 60.0,
    lam: float = 1.0,
    limits: DeflectionLimits | None = None,
) -> Deflection:
    """The deflections of one span (or cantilever) for the Table 6.6.2 checks.

    ``dead`` and ``live``: (service moment Ma at the Ie section [N·mm], elastic deflection of
    the analysis [mm, downward positive, relative to the chord]) of the unfactored dead (D +
    SD) and live (L) cases; ``ei_analysis`` [N·mm²]: the analysis's E·I of the member;
    ``sustained_live_share`` ψ: the share of the live load that is sustained; ``roof``: a flat
    roof (l/180 for the live load); ``sensitive``: it supports or is attached to nonstructural
    elements likely to be damaged by large deflections (l/480, else l/240)."""
    limits = DeflectionLimits.from_pack() if limits is None else limits
    if not 0 <= sustained_live_share <= 1:
        raise ValueError("the sustained share of the live load must be between 0 and 1")
    mcr = cracking_moment(fc, stiffness.ig, stiffness.yt, lam)
    (m_d, d_d), (m_l, d_l) = dead, live
    psi = sustained_live_share
    ie_d = effective_inertia(m_d, mcr, stiffness.ig, stiffness.icr)
    ie_t = effective_inertia(m_d + m_l, mcr, stiffness.ig, stiffness.icr)
    ie_s = effective_inertia(m_d + psi * m_l, mcr, stiffness.ig, stiffness.icr)
    i_dead = d_d * ei_analysis / (ec * ie_d)
    i_total = (d_d + d_l) * ei_analysis / (ec * ie_t)
    i_sus = (d_d + psi * d_l) * ei_analysis / (ec * ie_s)
    i_live = max(i_total - i_dead, 0.0)
    xi = xi_factor(months, limits.xi)
    lam_delta = long_term_multiplier(stiffness.rho_prime, xi)
    long_term = lam_delta * i_sus
    live_div = limits.live_roof if roof else limits.live_floor
    attached_div = limits.attached_sensitive if sensitive else limits.attached_insensitive
    notes = (
        f"Ec = {ec:.0f} MPa, Ig = {stiffness.ig:.4g}, Icr = {stiffness.icr:.4g} mm⁴",
        f"Mcr = {mcr / 1e6:.1f} kN·m",
        f"Ie = {ie_d:.4g} (D), {ie_s:.4g} (D + {psi:g} L), {ie_t:.4g} (D + L) mm⁴ (Eq. 6.6.1)",
        f"λΔ = ξ/(1 + 50ρ') = {xi:g}/(1 + 50 × {stiffness.rho_prime:.4f}) = {lam_delta:.2f}",
    )
    return Deflection(
        span,
        ie_d,
        ie_s,
        ie_t,
        mcr,
        i_dead,
        i_total,
        i_live,
        i_sus,
        xi,
        lam_delta,
        long_term,
        long_term + i_live,
        span / live_div,
        span / attached_div,
        notes,
    )


def deflection_checks(
    result: Deflection,
    roof: bool = False,
    sensitive: bool = True,
    where: str = "",
    limits: DeflectionLimits | None = None,
) -> list[dict[str, Any]]:
    """Check rows of Table 6.6.2 for a span computed by :func:`span_deflection` (combination
    "service": unfactored loads)."""
    limits = DeflectionLimits.from_pack() if limits is None else limits
    live_div = limits.live_roof if roof else limits.live_floor
    attached_div = limits.attached_sensitive if sensitive else limits.attached_insensitive
    at = f"; {where}" if where else ""
    base = "; ".join(result.notes)
    return [
        _check(
            "Deflection: immediate, live load (Table 6.6.2)",
            result.immediate_live,
            result.live_limit,
            "mm",
            "service",
            f"l/{live_div:g} ({'flat roof' if roof else 'floor'}), l = {result.span:.0f} mm; "
            f"{base}{at}",
        ),
        _check(
            "Deflection: after attachment of nonstructural elements (Table 6.6.2)",
            result.after_attachment,
            result.attached_limit,
            "mm",
            "service",
            f"λΔ × immediate sustained ({result.immediate_sustained:.1f} mm) + immediate live "
            f"({result.immediate_live:.1f} mm); l/{attached_div:g} "
            + (
                "(elements likely to be damaged)"
                if sensitive
                else "(elements not likely to be damaged)"
            )
            + f"; {base}{at}",
        ),
    ]
