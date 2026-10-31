"""Wind components-and-cladding pressures (BNBC 2020 Part 6 Sec 2.4.11.5; ASCE 7-05 Figures
6-11A, 6-11B, 6-17) and the gust-effect factor of flexible buildings (Sec 2.4.8.2; ASCE 7-05
Sec 6.5.8.2). Values by hand."""

from __future__ import annotations

import math

import pytest

from saengine.codes.tables import CladdingCurve
from saengine.fem.loads import (
    cladding_coefficient,
    cladding_edge_width,
    cladding_pressures,
    flexible_gust_factor,
    is_flexible,
    velocity_pressure,
)

V, EXPOSURE, I = 65.7, "A", 1.0


# ── gust-effect factor of a flexible building (Sec 2.4.8.2, Eq. 6.2.8-6.2.16) ──


def test_flexible_gust_factor_by_hand() -> None:
    # h = 30 m, B = L = 20 m, n1 = 0.8 Hz, V = 65 m/s, Exposure A (ASCE 7-05 B: c = 0.30,
    # ℓ = 97.54 m, ε̄ = 1/3, b̄ = 0.45, ᾱ = 1/4, z_min = 9.14 m), β = 0.02:
    # z̄ = 18 m, Iz̄ = 0.30·(10/18)^(1/6) = 0.2720, Lz̄ = 97.54·1.8^(1/3) = 118.6 m,
    # Q² = 1/(1 + 0.63·(50/118.6)^0.63) = 0.7326, Vz̄ = 0.45·1.8^0.25·65 = 33.88 m/s,
    # N1 = 2.80, Rn = 0.0729, Rh = 0.2599, RB = 0.3558, RL = 0.1280, R² = 0.1989,
    # gR = 4.136, Gf = 0.925·(1 + 1.7·0.272·3.4456)/(1 + 1.7·3.4·0.272) = 0.9326.
    terms = flexible_gust_factor(30.0, 20.0, 20.0, 0.8, 65.0, "A", 0.02)
    assert terms is not None
    assert terms["zbar_m"] == pytest.approx(18.0)
    assert terms["Iz"] == pytest.approx(0.2720, abs=5e-4)
    assert terms["Lz_m"] == pytest.approx(118.6, abs=0.2)
    assert terms["Q"] ** 2 == pytest.approx(0.7326, abs=1e-3)
    assert terms["Vz_ms"] == pytest.approx(33.88, abs=0.02)
    assert terms["R"] ** 2 == pytest.approx(0.1989, rel=5e-3)
    assert terms["gR"] == pytest.approx(4.136, abs=2e-3)
    assert terms["Gf"] == pytest.approx(0.9326, abs=2e-3)


def test_flexible_gust_factor_falls_with_damping_and_frequency() -> None:
    low = flexible_gust_factor(60.0, 25.0, 25.0, 0.4, V, EXPOSURE, 0.01)["Gf"]
    damped = flexible_gust_factor(60.0, 25.0, 25.0, 0.4, V, EXPOSURE, 0.03)["Gf"]
    stiffer = flexible_gust_factor(60.0, 25.0, 25.0, 0.9, V, EXPOSURE, 0.01)["Gf"]
    assert damped < low and stiffer < low


def test_zbar_not_below_zmin() -> None:
    # Exposure A: z_min = 9.14 m > 0.6·10 m (Table 6.2.10).
    assert flexible_gust_factor(10.0, 10.0, 10.0, 0.9, V, "A")["zbar_m"] == pytest.approx(9.14)


def test_flexible_below_one_hertz() -> None:
    # Sec 2.4.2: flexible, a fundamental natural frequency less than 1 Hz.
    assert is_flexible(0.99) and not is_flexible(1.0)


# ── components and cladding (Sec 2.4.11.5) ──


def test_coefficient_log_linear_in_area() -> None:
    # Low-rise wall zone 5 suction: −1.4 at A ≤ 0.93 m² (10 ft²), −0.8 at A ≥ 46.45 m² (500 ft²).
    curve = CladdingCurve(
        surface="wall", zone="5", sign="negative", area1=0.93, gcp1=-1.4, area2=46.45, gcp2=-0.8
    )
    assert cladding_coefficient(curve, None) == -1.4
    assert cladding_coefficient(curve, 0.5) == -1.4
    assert cladding_coefficient(curve, 100.0) == -0.8
    assert cladding_coefficient(curve, math.sqrt(0.93 * 46.45)) == pytest.approx(-1.1)


def test_edge_width() -> None:
    # Low-rise: a = min(0.1·15, 0.4·12) = 1.5 m ≥ max(0.04·15, 0.9); thin: 0.1·6 = 0.6 → 0.9.
    assert cladding_edge_width(15.0, 12.0, True) == pytest.approx(1.5)
    assert cladding_edge_width(6.0, 12.0, True) == pytest.approx(0.9)
    # Low and wide: 0.4·3 = 1.2 < 0.1·40 = 4.0, and 0.04·40 = 1.6 governs.
    assert cladding_edge_width(40.0, 3.0, True) == pytest.approx(1.6)
    # h > 18.3 m: 0.1 · least, not less than 0.9 m.
    assert cladding_edge_width(20.0, 40.0, False) == pytest.approx(2.0)


def _zone(result: dict, surface: str, zone: str) -> dict:
    return next(z for z in result["zones"] if (z["surface"], z["zone"]) == (surface, zone))


def test_low_rise_pressures_by_hand() -> None:
    # h = 12 m ≤ 18.3 m: p = qh·[(GCp) − (±0.18)], walls × 0.9 (θ ≤ 10°, Figure 6-11A note 5).
    out = cladding_pressures(12.0, 15.0, V, EXPOSURE, I)
    qh = velocity_pressure(12.0, V, EXPOSURE, I)
    assert out["lowRise"] and out["qh_kPa"] == pytest.approx(qh)
    wall5 = _zone(out, "wall", "5")
    assert wall5["GCpNeg"] == pytest.approx(-1.26)
    assert wall5["pNeg_kPa"] == pytest.approx(qh * (-1.26 - 0.18))
    assert wall5["pPos_kPa"] == pytest.approx(qh * (0.9 + 0.18))
    roof3 = _zone(out, "roof", "3")
    assert roof3["pNeg_kPa"] == pytest.approx(qh * (-2.8 - 0.18))
    assert roof3["pPos_kPa"] == pytest.approx(qh * (0.3 + 0.18))
    assert out["parapet"] is None


def test_parapet_turns_corner_into_edge() -> None:
    # A parapet ≥ 0.9 m: roof zone 3 takes zone 2's (GCp) (Figure 6-11B note 7); the parapet's
    # Case A = qp·(0.9·1.0 + 2.8), Case B = qp·(0.9·1.0 + 0.9·1.4) (ASCE 7-05 6.5.12.4.4).
    out = cladding_pressures(12.0, 15.0, V, EXPOSURE, I, parapet=1.0)
    assert _zone(out, "roof", "3")["GCpNeg"] == pytest.approx(-1.8)
    qp = velocity_pressure(13.0, V, EXPOSURE, I)
    assert out["parapet"]["caseA_kPa"] == pytest.approx(qp * 3.7)
    assert out["parapet"]["caseB_kPa"] == pytest.approx(qp * (0.9 + 1.26))
    low = cladding_pressures(12.0, 15.0, V, EXPOSURE, I, parapet=0.5)
    assert _zone(low, "roof", "3")["GCpNeg"] == pytest.approx(-2.8)


def test_tall_building_pressures_by_hand() -> None:
    # h = 40 m > 18.3 m (Figure 6-17): wall zone 5 −1.8, roof zone 3 −3.2 at the smallest
    # area; no positive roof pressure; partially enclosed GCpi = ±0.55.
    out = cladding_pressures(40.0, 20.0, V, EXPOSURE, I, enclosure="partiallyEnclosed")
    qh = velocity_pressure(40.0, V, EXPOSURE, I)
    assert not out["lowRise"] and out["a_m"] == pytest.approx(2.0)
    assert _zone(out, "wall", "5")["pNeg_kPa"] == pytest.approx(qh * (-1.8 - 0.55))
    assert _zone(out, "wall", "4")["pPos_kPa"] == pytest.approx(qh * (0.9 + 0.55))
    roof3 = _zone(out, "roof", "3")
    assert roof3["pPos_kPa"] is None and roof3["pNeg_kPa"] == pytest.approx(qh * (-3.2 - 0.55))


def test_larger_area_lowers_suction() -> None:
    small = cladding_pressures(40.0, 20.0, V, EXPOSURE, I)
    large = cladding_pressures(40.0, 20.0, V, EXPOSURE, I, area=46.45)
    assert _zone(large, "wall", "5")["GCpNeg"] == pytest.approx(-1.0)
    assert _zone(large, "roof", "3")["pNeg_kPa"] > _zone(small, "roof", "3")["pNeg_kPa"]
