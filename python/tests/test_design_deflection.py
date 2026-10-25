"""RC deflection (saengine.design.deflection) against hand calculations to BNBC 2020 Part 6
Sec 6.2.5 (Eqs. 6.6.1-6.6.4, Tables 6.6.1 and 6.6.2; pp. 900-902)."""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.design.deflection import (
    DeflectionLimits,
    beam_minimum_depth,
    cracking_moment,
    deflection_checks,
    effective_inertia,
    long_term_multiplier,
    section_stiffness,
    span_deflection,
    xi_factor,
)
from saengine.design.rc import section_of
from saengine.library.objects import (
    BarGroup,
    LinearReinforcement,
    RectangleProfile,
    Transverse,
)

#: Table 6.6.2 (p. 902), the ξ list of Sec 6.2.5.2.5 (p. 901), Table 6.6.1 beams (p. 900).
LIMITS = DeflectionLimits(
    live_floor=360,
    live_roof=180,
    attached_sensitive=480,
    attached_insensitive=240,
    xi={3: 1.0, 6: 1.2, 12: 1.4, 60: 2.0},
    beam_divisors=(16, 18.5, 21),
    cantilever_beam=8,
)
FC = 25.0
EC = 4700 * math.sqrt(FC)  # 23 500 MPa (Sec 6.1.7.1)


def beam(top: int = 0):
    """300 x 500, 3 Ø20 bottom (and ``top`` Ø16 top), 40 mm clear cover to Ø10 stirrups."""
    groups = [BarGroup(position="bottom", count=3, dia=20)]
    if top:
        groups.append(BarGroup(position="top", count=top, dia=16))
    reinforcement = LinearReinforcement(
        material="rebar",
        cover=40,
        longitudinal=groups,
        transverse=Transverse(type="stirrup", dia=10, spacing=150),
    )
    return section_of(RectangleProfile(xDim=300, yDim=500), reinforcement, FC, 420)


def test_section_properties_by_hand() -> None:
    s = section_stiffness(beam(), EC)
    b, h, d = 300, 500, 500 - 40 - 10 - 10  # d = 440 mm
    n = 200_000 / EC
    as_ = 3 * math.pi * 20**2 / 4  # 942.5 mm²
    # b c²/2 = n As (d - c)
    c = (-n * as_ + math.sqrt((n * as_) ** 2 + 2 * b * n * as_ * d)) / b
    icr = b * c**3 / 3 + n * as_ * (d - c) ** 2
    assert s.d == pytest.approx(d)
    assert s.ig == pytest.approx(b * h**3 / 12)
    assert s.yt == pytest.approx(250)
    assert s.c == pytest.approx(c, rel=1e-6)
    assert s.icr == pytest.approx(icr, rel=1e-6)
    assert s.rho_prime == 0
    # Mcr = 0.62 √f'c Ig / yt = 3.1 × 3.125e9 / 250 = 38.75 kN·m
    assert cracking_moment(FC, s.ig, s.yt) == pytest.approx(38.75e6)


def test_t_section_with_neutral_axis_in_the_flange_is_a_wide_rectangle() -> None:
    wide = section_stiffness(beam(), EC, flange=(1500, 125))
    n = 200_000 / EC
    as_, d, bf = 3 * math.pi * 100, 440.0, 1500
    c = (-n * as_ + math.sqrt((n * as_) ** 2 + 2 * bf * n * as_ * d)) / bf
    assert c < 125
    assert wide.icr == pytest.approx(bf * c**3 / 3 + n * as_ * (d - c) ** 2, rel=1e-6)
    assert wide.yt > 250  # the centroid moves up towards the flange


def test_simply_supported_beam_immediate_and_long_term_deflection() -> None:
    section = beam()
    s = section_stiffness(section, EC)
    span, w_d, w_l, psi = 6000.0, 15.0, 8.0, 0.25  # N/mm service loads
    ei_an = EC * 0.35 * s.ig  # the analysis's cracked stiffness

    def elastic(w: float, ei: float) -> float:
        return 5 * w * span**4 / (384 * ei)

    def moment(w: float) -> float:
        return w * span**2 / 8

    result = span_deflection(
        span,
        s,
        FC,
        EC,
        ei_an,
        dead=(moment(w_d), elastic(w_d, ei_an)),
        live=(moment(w_l), elastic(w_l, ei_an)),
        sustained_live_share=psi,
        limits=LIMITS,
    )
    mcr = 38.75e6
    ie = {
        k: effective_inertia(moment(w), mcr, s.ig, s.icr)
        for k, w in (("d", w_d), ("s", w_d + psi * w_l), ("t", w_d + w_l))
    }
    # Ma(D) = 67.5 kN·m > Mcr: Ie by Eq. 6.6.1 between Icr and Ig.
    r = (mcr / moment(w_d)) ** 3
    assert ie["d"] == pytest.approx(r * s.ig + (1 - r) * s.icr)
    assert s.icr < ie["t"] < ie["s"] < ie["d"] < s.ig
    dead = elastic(w_d, EC * ie["d"])  # 5 w L⁴ / (384 Ec Ie)
    total = elastic(w_d + w_l, EC * ie["t"])
    sustained = elastic(w_d + psi * w_l, EC * ie["s"])
    assert result.immediate_dead == pytest.approx(dead, rel=1e-9)
    assert result.immediate_total == pytest.approx(total, rel=1e-9)
    assert result.immediate_live == pytest.approx(total - dead, rel=1e-9)
    assert result.multiplier == pytest.approx(2.0)  # ξ = 2.0 (5 years), ρ' = 0
    assert result.long_term == pytest.approx(2.0 * sustained, rel=1e-9)
    assert result.after_attachment == pytest.approx(2.0 * sustained + total - dead, rel=1e-9)
    assert result.live_limit == pytest.approx(6000 / 360)
    assert result.attached_limit == pytest.approx(6000 / 480)
    rows = deflection_checks(result, limits=LIMITS)
    assert [r["capacity"] for r in rows] == [pytest.approx(16.67), pytest.approx(12.5)]
    assert rows[0]["demand"] == pytest.approx(round(total - dead, 2))
    assert rows[0]["ok"] == (total - dead <= 6000 / 360)
    assert rows[1]["ok"] == (2.0 * sustained + total - dead <= 12.5)


def test_limit_table_choices() -> None:
    s = section_stiffness(beam(), EC)
    args = (5000.0, s, FC, EC, EC * s.ig, (10e6, 1.0), (5e6, 0.5), 0.0)
    roof = span_deflection(*args, roof=True, sensitive=False, limits=LIMITS)
    assert roof.live_limit == pytest.approx(5000 / 180)  # flat roof
    assert roof.attached_limit == pytest.approx(5000 / 240)  # not likely to be damaged
    floor = span_deflection(*args, limits=LIMITS)
    assert floor.live_limit == pytest.approx(5000 / 360)
    assert floor.attached_limit == pytest.approx(5000 / 480)
    # Below Mcr Ie = Ig: the deflection is the gross-section one.
    assert floor.immediate_dead == pytest.approx(1.0)


def test_long_term_multiplier_and_xi() -> None:
    assert xi_factor(60, LIMITS.xi) == 2.0
    assert xi_factor(120, LIMITS.xi) == 2.0
    assert xi_factor(12, LIMITS.xi) == 1.4
    assert xi_factor(9, LIMITS.xi) == pytest.approx(1.3)
    with pytest.raises(ValueError):
        xi_factor(1, LIMITS.xi)
    s = section_stiffness(beam(top=2), EC)
    rho_prime = 2 * math.pi * 64 / (300 * 440)
    assert s.rho_prime == pytest.approx(rho_prime)
    assert long_term_multiplier(s.rho_prime, 2.0) == pytest.approx(2 / (1 + 50 * rho_prime))


def test_beam_minimum_depth_table_6_6_1() -> None:
    assert beam_minimum_depth(6000, 0, 420, False, LIMITS) == pytest.approx(375)
    assert beam_minimum_depth(6000, 2, 420, False, LIMITS) == pytest.approx(6000 / 21)
    assert beam_minimum_depth(2000, 0, 420, True, LIMITS) == pytest.approx(250)
    assert beam_minimum_depth(6000, 1, 500, False, LIMITS) == pytest.approx(
        6000 / 18.5 * (0.4 + 500 / 700)
    )


@pytest.mark.skipif(
    "deflection" not in type(code_context.table("concrete")).model_fields,
    reason="the BNBC pack's concrete.deflection group is added by the integrator",
)
def test_pack_limits_are_bnbc_table_6_6_2() -> None:
    assert DeflectionLimits.from_pack() == LIMITS
