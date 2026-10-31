"""Earth pressure (saengine.substructure.earth_pressure) and retaining walls
(saengine.substructure.retaining_walls): the formulas pinned with their sources."""

from __future__ import annotations

import math

import pytest

from saengine.library.settings import LoadCombination
from saengine.library.substructure import RetainingWall
from saengine.substructure.earth_pressure import (
    GAMMA_W,
    Soil,
    k0_jaky,
    ka_coulomb,
    ka_rankine,
    kae_mononobe_okabe,
    kp_rankine,
    seed_whitman_trapezoid,
    seismic_increment,
)
from saengine.substructure.retaining_walls import (
    aci_crack_spacing,
    base_pressure,
    beam_actions,
    factor_of_safety,
)

# ─────────────────────────────── coefficients ───────────────────────────────


def test_rankine_and_jaky_at_30_degrees() -> None:
    """Rankine Ka = (1 - sin φ) / (1 + sin φ) = 1/3, Kp = 3 at φ' = 30°; Jaky K0 = 1 - sin φ'."""
    assert ka_rankine(30) == pytest.approx(1 / 3, abs=1e-9)
    assert kp_rankine(30) == pytest.approx(3.0, abs=1e-9)
    assert k0_jaky(30) == pytest.approx(0.5, abs=1e-9)


def test_jaky_overconsolidated() -> None:
    """Mayne & Kulhawy (1982): K0 = (1 - sin φ') OCR^sin φ'."""
    assert k0_jaky(30, 4.0) == pytest.approx(0.5 * 4**0.5, rel=1e-9)


def test_rankine_sloping_backfill() -> None:
    """Rankine Ka with β = 10°, φ' = 30°: cos β (cos β - √(cos²β - cos²φ)) / (cos β + ...)
    = 0.3495 (Das, Principles of Foundation Engineering, Table 7.2)."""
    assert ka_rankine(30, 10) == pytest.approx(0.3495, abs=5e-4)


def test_coulomb_reduces_to_rankine_and_wall_friction() -> None:
    """Coulomb Ka equals Rankine's for a smooth vertical wall and level backfill; with δ = 20°,
    φ' = 30° it is 0.297 (Das, Table 7.4)."""
    assert ka_coulomb(30) == pytest.approx(ka_rankine(30), abs=1e-9)
    assert ka_coulomb(30, 20) == pytest.approx(0.297, abs=1e-3)


def test_mononobe_okabe() -> None:
    """AASHTO LRFD Eq. A11.1.1.1-2: Kae = Ka at kh = 0; φ' = 30°, δ = 0, kh = 0.1: 0.397; and
    None when φ' - β - ψ < 0 (no stable backfill)."""
    assert kae_mononobe_okabe(30, 0.0) == pytest.approx(1 / 3, abs=1e-9)
    assert kae_mononobe_okabe(30, 0.1) == pytest.approx(0.397, abs=1e-3)
    assert kae_mononobe_okabe(20, 0.5, beta=10) is None


def test_seed_whitman_trapezoid_resultant() -> None:
    """The linear pressure of resultant P at 0.6 H (Seed & Whitman 1970): ∫p = P, ∫p y = 0.6 H P;
    at 0.5 H it is uniform (Wood 1973)."""
    bottom, top = seed_whitman_trapezoid(10.0, 4.0, 0.6)
    force = (bottom + top) / 2 * 4.0
    moment = bottom * 4.0**2 / 2 + (top - bottom) * 4.0**2 / 3
    assert force == pytest.approx(10.0)
    assert moment / force == pytest.approx(0.6 * 4.0)
    assert seed_whitman_trapezoid(10.0, 4.0, 0.5) == pytest.approx((2.5, 2.5))


def test_wood_increment() -> None:
    """Wood (1973): ΔPe = kh γ H² on a rigid wall, uniform."""
    soil = Soil([(0.0, 20.0, 18.0, 20.0, 30.0)], None)
    inc = seismic_increment(soil, 3.0, 0.2, yielding=False)
    assert inc["force"] == pytest.approx(0.2 * 18.0 * 9.0)
    assert inc["arm"] == pytest.approx(1.5)


# ─────────────────────────────── layered soil ───────────────────────────────


def test_at_rest_lateral_as_the_ground_tanks() -> None:
    """BNBC 2020 Part 6 Sec 2.6.5.1 (p680): K0 (σ'v + q) + u with the submerged unit weight
    below the water table. φ' 30° (K0 0.5), γ 18, γsat 20, water 1 m, q 10, z = 3 m:
    σ'v = 18 + 2 (20 - 9.81) = 38.38, p = 0.5 (38.38 + 10) + 2 x 9.81 = 43.81 kPa."""
    soil = Soil([(0.0, 10.0, 18.0, 20.0, 30.0)], 1.0, 10.0, 0.6, "test")
    expected = 0.5 * (18.0 + 2 * (20.0 - GAMMA_W) + 10.0) + 2 * GAMMA_W
    assert soil.lateral(3.0) == pytest.approx(expected)
    assert soil.pressure(3.0, "atRest")["total"] == pytest.approx(expected)


def test_active_resultant_with_water() -> None:
    """Active Rankine thrust on 5 m, water at 2 m, q 10: soil Ka (½·36·2 + ½(36 + 66.57)·3),
    water ½ γw 3², surcharge Ka q 5."""
    soil = Soil([(0.0, 10.0, 18.0, 20.0, 30.0)], 2.0, 10.0)
    p = soil.resultant(0.0, 5.0, "active")
    sigma = 36.0 + 3 * (20.0 - GAMMA_W)
    assert p["soil"] == pytest.approx((36.0 + (36.0 + sigma) / 2 * 3) / 3, rel=1e-6)
    assert p["water"] == pytest.approx(0.5 * GAMMA_W * 9.0, rel=1e-6)
    assert p["surcharge"] == pytest.approx(10.0 / 3 * 5.0, rel=1e-6)


def test_active_cohesion_has_no_tension() -> None:
    """Active pressure with c': K σ'v - 2 c' √K, never below zero (no tension on the wall)."""
    soil = Soil([(0.0, 10.0, 18.0, 20.0, 30.0, 20.0)], None)
    assert soil.pressure(0.5, "active")["total"] == 0.0
    deep = soil.pressure(5.0, "active")
    assert deep["soil"] == pytest.approx(90.0 / 3 - 2 * 20.0 * math.sqrt(1 / 3))


def test_drained_wall_has_no_water() -> None:
    soil = Soil([(0.0, 10.0, 18.0, 20.0, 30.0)], 1.0)
    p = soil.pressure(3.0, "atRest", water=False)
    assert p["water"] == 0.0
    assert p["soil"] == pytest.approx(0.5 * 54.0)


def test_below_shifts_layers_and_water() -> None:
    soil = Soil([(0.0, 2.0, 17.0, 19.0, 28.0), (2.0, 10.0, 18.0, 20.0, 32.0)], 3.0, 10.0)
    front = soil.below(2.5)
    assert front.layers[0][0] == 0.0 and front.layers[0][4] == 32.0
    assert front.water_table == pytest.approx(0.5)
    assert front.surcharge == 0.0


# ─────────────────────────────── wall actions ───────────────────────────────


def test_beam_actions_cantilever() -> None:
    """A cantilever stem under a triangular pressure q0 (1 - y/H), q0 = 30, H = 3: M base =
    q0 H² / 6 = 45 kN·m/m, V base = q0 H / 2 = 45 kN/m."""
    _, moments, shears, props = beam_actions(3.0, lambda y: 10.0 * (3.0 - y), [], True)
    assert moments[0] == pytest.approx(45.0, rel=1e-6)
    assert shears[0] == pytest.approx(45.0, rel=1e-6)
    assert props == []


def test_beam_actions_propped_cantilever() -> None:
    """Fixed at the base, propped at the top, uniform q: M base = qL²/8, prop 3qL/8."""
    _, moments, _, props = beam_actions(3.0, lambda y: 10.0, [3.0], True)
    assert moments[0] == pytest.approx(10.0 * 9 / 8, rel=1e-6)
    assert props[0] == pytest.approx(3 * 10.0 * 3 / 8, rel=1e-6)


def test_beam_actions_simple_span() -> None:
    """Pinned at both ends, uniform q: the span moment qL²/8 at the inner face (negative)."""
    _, moments, _, _ = beam_actions(4.0, lambda y: 10.0, [4.0], False)
    assert min(moments) == pytest.approx(-20.0, rel=1e-4)


def test_base_pressure_middle_third_and_beyond() -> None:
    """Linear base pressure N/B (1 ± 6e/B) within the middle third; 2N / (3 x) beyond it."""
    toe, heel, e = base_pressure(100.0, 100.0 * 1.2, 3.0)
    assert e == pytest.approx(0.3)
    assert toe == pytest.approx(100 / 3 * (1 + 6 * 0.3 / 3))
    assert heel == pytest.approx(100 / 3 * (1 - 6 * 0.3 / 3))
    toe, heel, e = base_pressure(100.0, 100.0 * 0.8, 3.0)
    assert heel == 0.0 and toe == pytest.approx(2 * 100 / (3 * 0.8))


def test_factor_of_safety_cap() -> None:
    assert factor_of_safety(10.0, 0.0) == 99.0
    assert factor_of_safety(15.0, 10.0) == pytest.approx(1.5)


def test_aci_crack_spacing() -> None:
    """ACI 318-19 Table 24.3.2, fs = 2/3 fy = 280 MPa for Grade 420: min(380 - 2.5 cc, 300)."""
    assert aci_crack_spacing(420.0, 50.0) == pytest.approx(255.0)
    assert aci_crack_spacing(420.0, 20.0) == pytest.approx(300.0)


# ─────────────────────────────── combinations, model ───────────────────────────────


@pytest.mark.parametrize(
    ("factors", "h"),
    [
        ({"D": 1.4}, 0.0),
        ({"D": 1.2, "L": 1.6, "Lr": 0.5}, 1.6),
        ({"D": 1.2, "WX": 1.6, "L": 1.0}, 0.0),
        ({"D": 0.9, "WX": 1.6}, 1.6),
        ({"D": 0.9, "EX": 1.0}, 1.6),
    ],
)
def test_h_factor_by_combination(factors: dict[str, float], h: float) -> None:
    """BNBC 2020 Part 6 Sec 2.7.3.1 (p685), as ASCE 7-05 2.3.2: 1.6H with 1.6L and in the 0.9D
    combinations (6) and (7), none in the others."""
    assert LoadCombination(name="c", **factors).H == pytest.approx(h)


def _wall(**extra: object) -> RetainingWall:
    data = {
        "id": "RW1",
        "path": [[0, 0], [5000, 0]],
        "topLevel": 0,
        "foundingLevel": -3500,
        "material": "C25",
    }
    data.update(extra)
    return RetainingWall.model_validate(data)


def test_retaining_wall_model() -> None:
    wall = _wall()
    assert wall.length() == pytest.approx(5000.0)
    assert wall.state() == "active"
    assert _wall(kind="basement", supports=[0]).state() == "atRest"
    with pytest.raises(ValueError, match="needs the levels of its floors"):
        _wall(kind="basement")
    with pytest.raises(ValueError, match="not above its base"):
        _wall(topLevel=-3200)
