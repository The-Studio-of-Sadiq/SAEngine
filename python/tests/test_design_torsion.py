"""Torsion of RC beams (saengine.design.torsion) against hand calculations to BNBC 2020 Part 6
Sec 6.4.4 (pp. 926-931)."""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.design.torsion import (
    TorsionRules,
    TorsionSection,
    cracking_torsion,
    design_torsion,
    threshold_torsion,
    torsion_checks,
    torsion_kind,
)

#: The BNBC values (Sec 6.4.4.3.4, 6.4.4.3.6, 6.4.4.6.1, 6.4.4.6.2) the pack carries.
RULES = TorsionRules(
    theta=45.0,
    ao_share=0.85,
    spacing_max=300.0,
    perimeter_divisor=8.0,
    long_spacing_max=300.0,
    long_dia_ratio=0.042,
    long_dia_min=10.0,
    fy_max=420.0,
)
PHI = 0.75
FC, FY = 25.0, 420.0

# A 300 x 600 spandrel beam, 40 mm clear cover to Ø10 closed stirrups, d = 540 mm.
SPANDREL = TorsionSection(b=300, h=600, cover=40, stirrup_dia=10, d=540)
ACP, PCP = 300 * 600, 2 * (300 + 600)  # 180 000 mm², 1800 mm
X1, Y1 = 300 - 2 * 40 - 10, 600 - 2 * 40 - 10  # 210, 510
AOH, PH = X1 * Y1, 2 * (X1 + Y1)  # 107 100 mm², 1440 mm


def test_threshold_and_cracking_torsion_by_hand() -> None:
    # φTth = 0.083 φ √f'c Acp²/pcp = 0.083 × 0.75 × 5 × 18e6 = 5.6025 kN·m
    assert threshold_torsion(SPANDREL, FC, phi=PHI) == pytest.approx(5.6025e6, rel=1e-9)
    # φTcr = 0.33 φ √f'c Acp²/pcp = 22.275 kN·m
    assert cracking_torsion(SPANDREL, FC, phi=PHI) == pytest.approx(22.275e6, rel=1e-9)
    # Axial compression Nu = 500 kN: × √(1 + Nu/(0.33 Ag √f'c)) = √(1 + 5e5/297000)
    factor = math.sqrt(1 + 500e3 / (0.33 * ACP * 5))
    assert threshold_torsion(SPANDREL, FC, nu=500e3, phi=PHI) == pytest.approx(5.6025e6 * factor)


def test_equilibrium_torsion_spandrel_by_hand() -> None:
    tu, vu = 30e6, 100e3  # 30 kN·m, 100 kN
    result = design_torsion(SPANDREL, tu, vu, FC, FY, FY, "equilibrium", rules=RULES, phi=PHI)
    assert result.required and not result.reduced
    assert result.tu_design == tu
    ao = 0.85 * AOH  # 91 035 mm²
    at_s = tu / (PHI * 2 * ao * FY * 1.0)  # cot 45° = 1: 0.52309 mm²/mm per leg
    assert at_s == pytest.approx(0.52309, abs=1e-5)
    assert result.at_s == pytest.approx(at_s, rel=1e-9)
    al = at_s * PH  # (fyt/fy) cot²θ = 1: 753.2 mm²
    al_min = 0.42 * 5 * ACP / FY - at_s * PH  # 900 - 753.2 = 146.8 mm²
    assert result.al == pytest.approx(max(al, al_min), rel=1e-9)
    assert result.al == pytest.approx(753.25, abs=0.05)
    assert result.al_min == pytest.approx(al_min, rel=1e-9)
    # (Av + 2At)/s >= max(0.062 √f'c, 0.35) bw / fyt = 0.35 × 300 / 420 = 0.25 mm²/mm
    assert result.av_2at_s_min == pytest.approx(0.25)
    assert result.s_max == pytest.approx(min(PH / 8, 300))  # 180 mm
    # Eq. 6.6.59 with Vc = 0.17 √f'c bw d = 137.7 kN
    lhs = math.hypot(vu / (300 * 540), tu * PH / (1.7 * AOH**2))
    rhs = PHI * (137.7e3 / (300 * 540) + 0.66 * 5)
    assert result.stress == pytest.approx(lhs, rel=1e-9)
    assert result.stress_limit == pytest.approx(rhs, rel=1e-9)
    assert lhs == pytest.approx(2.2998, abs=1e-3) and rhs == pytest.approx(3.1125)
    assert result.section_ok


def test_compatibility_torsion_is_reduced_to_phi_tcr() -> None:
    result = design_torsion(
        SPANDREL, 30e6, 100e3, FC, FY, FY, "compatibility", rules=RULES, phi=PHI
    )
    assert result.reduced
    assert result.tu_design == pytest.approx(22.275e6)
    assert result.at_s == pytest.approx(22.275e6 / (PHI * 2 * 0.85 * AOH * FY), rel=1e-9)
    assert "6.4.4.2.2" in result.notes[0]
    # Below φTcr nothing is reduced.
    small = design_torsion(SPANDREL, 10e6, 0, FC, FY, FY, "compatibility", rules=RULES, phi=PHI)
    assert not small.reduced and small.tu_design == 10e6


def test_below_threshold_torsion_is_neglected() -> None:
    result = design_torsion(SPANDREL, 5e6, 50e3, FC, FY, FY, rules=RULES, phi=PHI)
    assert not result.required
    assert result.at_s == 0 and result.al == 0
    rows = torsion_checks(result, SPANDREL, 50e3, (10, 2, 150), 2000, 1000, "C1", fyt_shear_max=420)
    assert len(rows) == 1 and rows[0]["flag"] and rows[0]["ok"]


def test_flanges_counted_only_when_they_raise_acp2_over_pcp() -> None:
    # Spandrel with a 125 mm slab on one side: overhang min(600 - 125, 4 × 125) = 475 mm.
    flanged = TorsionSection(300, 600, 40, 10, 540, slab=125, slab_sides=1)
    acp, pcp, used = flanged.outline()
    assert flanged.overhang == 475
    acp_f, pcp_f = ACP + 475 * 125, PCP + 2 * 475
    # 239 375²/2750 = 20.8e6 > 180 000²/1800 = 18.0e6 mm³: counted.
    assert used is True and (acp, pcp) == (acp_f, pcp_f)
    # A 60 mm slab both sides of a 300 x 500 beam: overhang 240 mm, Acp = 178 800 mm²,
    # pcp = 2560 mm, 12.5e6 < 150 000²/1600 = 14.1e6 mm³: the flanges are dropped.
    thin = TorsionSection(300, 500, 40, 10, 440, slab=60, slab_sides=2)
    assert thin.outline()[2] is False


def test_torsion_check_rows_with_stirrups() -> None:
    result = design_torsion(SPANDREL, 30e6, 100e3, FC, FY, FY, rules=RULES, phi=PHI, spacing=150)
    assert result.long_dia_min == pytest.approx(10.0)  # max(0.042 × 150, 10)
    # Ø10 2 legs at 150: 78.54/150 = 0.5236 per leg; need At/s + Av/(2s), Av/s from
    # (Vu/φ - Vc)/(fyt d) = (133.3 - 137.7) kN < 0 -> 0.
    rows = torsion_checks(
        result, SPANDREL, 100e3, (10, 2, 150), 2500, 1200, "C1", fyt_shear_max=420
    )
    by_name = {r["name"].split(" (")[0]: r for r in rows}
    stirrups = next(r for r in rows if r["name"].startswith("Torsion: closed stirrups"))
    assert stirrups["demand"] == pytest.approx(0.52, abs=0.01)
    assert stirrups["capacity"] == pytest.approx(0.52, abs=0.01)
    spacing = next(r for r in rows if "spacing" in r["name"])
    assert spacing["ok"] and spacing["capacity"] == 180
    longitudinal = next(r for r in rows if "longitudinal" in r["name"])
    assert longitudinal["demand"] == pytest.approx(753.25 + 1200, abs=0.1)
    assert longitudinal["ok"]  # 2500 mm² provided
    assert any("section size" in name for name in by_name)


def test_torsion_kind_rule() -> None:
    assert torsion_kind(True, True)[0] == "equilibrium"
    assert torsion_kind(False, False)[0] == "equilibrium"
    assert torsion_kind(True, False)[0] == "compatibility"


@pytest.mark.skipif(
    "torsion" not in type(code_context.table("concrete")).model_fields,
    reason="the BNBC pack's concrete.torsion group is added by the integrator",
)
def test_pack_rules_are_bnbc() -> None:
    assert TorsionRules.from_pack() == RULES


def _spandrel_bars(stirrup_spacing: float, side_bars: bool):
    from saengine.design.rc import section_of
    from saengine.library.objects import (
        BarGroup,
        LinearReinforcement,
        RectangleProfile,
        Transverse,
    )

    groups = [
        BarGroup(position="top", count=2, dia=16),
        BarGroup(position="bottom", count=3, dia=20),
    ]
    if side_bars:
        groups.append(BarGroup(position="sides", count=2, dia=12))
    reinforcement = LinearReinforcement(
        material="rebar",
        cover=40,
        longitudinal=groups,
        transverse=Transverse(type="tie", dia=10, spacing=stirrup_spacing, legs=2),
    )
    return section_of(RectangleProfile(xDim=300, yDim=600), reinforcement, FC, FY).bars


def _detailing(rows):
    return {
        key: next(r for r in rows if key in r["name"])
        for key in ("bar diameter", "each corner", "perimeter, gap")
    }


def test_torsion_longitudinal_detailing_sec_6_4_4_6_2() -> None:
    """2 Ø16 top (x = ±92, y = 242), 3 Ø20 bottom (x = 0, ±90, y = -240) in the spandrel.
    Inner face of the stirrups at ±100, ±250 mm: all bars are against it, one in each corner.
    The side gap is √(2² + 482²) = 482.0 mm > 300 mm. With one Ø12 on each side (x = ±94,
    y = 1) the largest gap is √(4² + 241²) = 241.03 mm; at s = 150 mm the least
    diameter is max(0.042 x 150, 10) = 10 mm <= 12; at s = 300 mm it is 12.6 mm > 12."""
    result = design_torsion(SPANDREL, 30e6, 100e3, FC, FY, FY, rules=RULES, phi=PHI, spacing=150)
    rows = torsion_checks(
        result,
        SPANDREL,
        100e3,
        (10, 2, 150),
        2500,
        1200,
        "C1",
        fyt_shear_max=420,
        bars=_spandrel_bars(150, side_bars=False),
        rules=RULES,
    )
    found = _detailing(rows)
    assert found["bar diameter"]["demand"] == pytest.approx(10.0)
    assert found["bar diameter"]["capacity"] == pytest.approx(16.0) and found["bar diameter"]["ok"]
    assert found["each corner"]["capacity"] == 4 and found["each corner"]["ok"]
    assert found["perimeter, gap"]["demand"] == pytest.approx(482.0, abs=0.01)
    assert not found["perimeter, gap"]["ok"]

    rows = torsion_checks(
        result,
        SPANDREL,
        100e3,
        (10, 2, 150),
        2500,
        1200,
        "C1",
        fyt_shear_max=420,
        bars=_spandrel_bars(150, side_bars=True),
        rules=RULES,
    )
    found = _detailing(rows)
    assert found["perimeter, gap"]["demand"] == pytest.approx(241.03, abs=0.01)
    assert found["perimeter, gap"]["ok"]
    assert found["bar diameter"]["capacity"] == pytest.approx(12.0) and found["bar diameter"]["ok"]

    # Stirrups at 300 mm: Ø12 side bars are thinner than 0.042 x 300 = 12.6 mm.
    rows = torsion_checks(
        result,
        SPANDREL,
        100e3,
        (10, 2, 300),
        2500,
        1200,
        "C1",
        fyt_shear_max=420,
        bars=_spandrel_bars(300, side_bars=True),
        rules=RULES,
    )
    found = _detailing(rows)
    assert found["bar diameter"]["demand"] == pytest.approx(12.6)
    assert not found["bar diameter"]["ok"]


def test_torsion_corner_bar_missing() -> None:
    """Only bottom bars: the two top corners hold no bar."""
    from saengine.design.rc import Bar

    bars = [Bar(-90, -240, math.pi * 100, 20), Bar(90, -240, math.pi * 100, 20)]
    result = design_torsion(SPANDREL, 30e6, 100e3, FC, FY, FY, rules=RULES, phi=PHI, spacing=150)
    rows = torsion_checks(
        result, SPANDREL, 100e3, (10, 2, 150), 2500, 1200, "C1", 420, bars=bars, rules=RULES
    )
    corner = next(r for r in rows if "each corner" in r["name"])
    assert corner["capacity"] == 2 and not corner["ok"]
