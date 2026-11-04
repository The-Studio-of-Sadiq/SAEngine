"""Alpha 9 P7: the checks BNBC requires without a method, by the pack's method ids (value pins
and one example per topic)."""

from __future__ import annotations

import math
from types import SimpleNamespace as NS

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.design import nonbuilding
from saengine.fem import floor_vibration as fv
from saengine.fem import wind_comfort as wc
from saengine.substructure import embedded_wall as ew
from saengine.substructure import pile_lateral_soil as pls
from saengine.substructure.earth_pressure import Soil


class _Profile:
    """A uniform borehole: one layer, γ 18 kN/m³, no water."""

    def __init__(self, layer: NS) -> None:
        self.layers = [layer]

    def layer_at(self, z: float) -> NS:
        return self.layers[0]

    def sigma_v_eff(self, z: float) -> float:
        return 18.0 * z

    def below_water(self, z: float) -> bool:
        return False


CLAY = _Profile(NS(top=0.0, bottom=30.0, behaviour="cohesive", cu=50.0, phi=None))
SAND = _Profile(NS(top=0.0, bottom=30.0, behaviour="granular", cu=None, phi=32.0))


def test_packs_choose_the_methods_by_id() -> None:
    bnbc = registry.load("bnbc2020")
    eu = registry.load("eurocodes")
    assert bnbc.table("floorVibration").steelMethod == "walkingAcceleration"
    assert bnbc.table("floorVibration").concreteMethod == "responseFactor"
    assert eu.table("floorVibration").steelMethod == "responseFactor"
    assert bnbc.table("windComfort").response == "alongWindGust"
    assert eu.table("windComfort").response == "turbulenceSpectrum"
    assert bnbc.table("embeddedWalls").method == "factoredPassive"
    assert eu.table("embeddedWalls").method == "partialFactors"
    lateral = bnbc.table("foundations").piles.lateral
    assert lateral.soilFailure.method == "broms" and lateral.pyAnalysis.method == "nonlinearSprings"
    assert "SAEngine practice" in bnbc.table("floorVibration").source


# ─────────────────────────────── piles ───────────────────────────────


def test_broms_cohesive() -> None:
    rules = pls.soil_failure_rules()
    # Fixed head, short: Hu = 9 cu D (L - 1.5 D) = 9 × 50 × 0.5 × 2.25
    short = pls.broms_cohesive(50, 0.5, 3.0, "fixed", None, rules)
    assert short["Hu"] == pytest.approx(506.25) and short["mode"] == "short"
    free = pls.broms_cohesive(50, 0.5, 3.0, "free", None, rules)
    f = free["Hu"] / 225.0
    g = 3.0 - 0.75 - f
    assert free["Hu"] * (0.75 + f / 2) == pytest.approx(2.25 * 50 * 0.5 * g * g, rel=1e-6)
    long = pls.broms_cohesive(50, 0.5, 18.0, "fixed", 200.0, rules)
    assert long["mode"] == "long"
    assert long["Hu"] * (0.75 + long["f"] / 2) == pytest.approx(400.0, rel=1e-6)


def test_broms_granular() -> None:
    rules = pls.soil_failure_rules()
    kp = math.tan(math.radians(61)) ** 2
    free = pls.broms_granular(32, 18, 0.5, 3.0, "free", None, rules)
    assert free["Hu"] == pytest.approx(0.5 * 18 * 0.5 * 27 * kp / 3)
    fixed = pls.broms_granular(32, 18, 0.5, 3.0, "fixed", None, rules)
    assert fixed["Hu"] == pytest.approx(1.5 * 18 * 9 * 0.5 * kp)
    assert pls.broms_granular(32, 18, 0.5, 4.0, "fixed", 200.0, rules)["mode"] == "intermediate"


def test_api_sand_coefficients() -> None:
    c1, c2, c3 = pls.sand_coefficients(30)
    assert (c1, c2, c3) == pytest.approx((1.91, 2.67, 28.7), rel=0.01)  # API RP 2GEO chart


def test_py_analysis_example() -> None:
    ei = 25e6 * math.pi * 0.5**4 / 64  # kN·m²
    free = pls.py_analysis(CLAY, 1.5, 0.5, 18.0, ei, "free", 50.0)
    fixed = pls.py_analysis(CLAY, 1.5, 0.5, 18.0, ei, "fixed", 50.0)
    assert free["converged"] and fixed["converged"]
    assert free["y0"] * 1e3 == pytest.approx(1.55, rel=0.05)
    assert fixed["y0"] < free["y0"] and fixed["zM"] == 0.0
    assert free["Vmax"] == pytest.approx(50.0)
    sand = pls.py_analysis(SAND, 1.5, 0.5, 18.0, ei, "free", 50.0)
    assert sand["curves"] == ["sand (API)"] and sand["y0"] > 0


# ─────────────────────────────── embedded walls ───────────────────────────────


def _rules(**changes: float) -> NS:
    return NS(
        **{
            "method": "factoredPassive",
            "passiveFactor": 2.0,
            "materials": None,
            "variableFactor": 1.0,
            "embedmentIncrease": 1.2,
            "freeEarthIncrease": 1.0,
            "minimumSurcharge": 0.0,
            "overdigShare": 0.0,
            "overdigMax": 0.0,
            "clauses": {},
            "source": "",
            **changes,
        }
    )


def test_cantilever_wall_matches_blum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ew, "table", _rules)
    soil = Soil([(0.0, 100.0, 18.0, 20.0, 30.0)], None, 0.0)
    found = ew.design_wall(soil, 4.0, "cantilever", "free", None, None)
    # Ka (H + d)³ = (Kp/F) d³: d0 = H / (4.5^(1/3) - 1)
    assert found["d0"] == pytest.approx(4.0 / (4.5 ** (1 / 3) - 1), rel=0.01)
    assert found["d"] == pytest.approx(1.2 * found["d0"])
    assert found["Mmax"] == pytest.approx(229.0, rel=0.01)


def test_propped_wall_free_earth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ew, "table", _rules)
    soil = Soil([(0.0, 100.0, 18.0, 20.0, 30.0)], None, 0.0)
    found = ew.design_wall(soil, 6.0, "propped", "free", 0.0, None)
    ht = 6.0 + found["d0"]
    active = ht**3 / 9
    passive = 1.5 * ((ht**3 - 216) / 3 - 3 * (ht**2 - 36))
    assert active == pytest.approx(passive, rel=0.02)
    assert found["T"] == pytest.approx(18 * (ht**2 / 6 - 1.5 * found["d0"] ** 2 / 2), rel=0.02)
    fixed = ew.design_wall(soil, 6.0, "propped", "fixed", 0.0, None)
    assert fixed["d"] > found["d"]


def test_default_pack_wall_adds_overdig_and_surcharge() -> None:
    soil = Soil([(0.0, 100.0, 18.0, 20.0, 30.0)], None, 0.0)
    found = ew.design_wall(soil, 4.0, "cantilever", "free", None, None)
    assert found["dig"] == pytest.approx(4.4) and found["q"] == pytest.approx(10.0)


# ─────────────────────────────── floors and wind ───────────────────────────────


def test_floor_vibration_values() -> None:
    rules = fv.table()
    assert fv.natural_frequency(0.01, 0.18) == pytest.approx(5.638, abs=1e-3)
    ap = fv.walking_acceleration(5.0, 500.0, 0.03, rules.walkingAcceleration)
    assert ap == pytest.approx(0.29 * math.exp(-1.75) / 15.0)
    office = rules.occupancies["office"]
    walking = fv.check_panel("walkingAcceleration", 5.0, 5.0, 64.0, 8.0, office, rules)
    assert walking["unit"] == "% g" and walking["limit"] == pytest.approx(0.5)
    low = fv.check_panel("walkingAcceleration", 2.5, 5.0, 64.0, 8.0, office, rules)
    assert not low["ok"]
    resonant = fv.check_panel("responseFactor", 6.0, 6.0, 64.0, 8.0, office, rules)
    assert resonant["unit"] == "R" and "resonant" in resonant["how"]
    transient = fv.check_panel("responseFactor", 12.0, 6.0, 64.0, 8.0, office, rules)
    assert "transient" in transient["how"]


def test_wind_comfort_values() -> None:
    rules = wc.table()
    assert wc.speed_ratio(rules) == pytest.approx(0.36 + 0.1 * math.log(120))
    assert wc.peak_factor(0.2, rules) == pytest.approx(3.7866, abs=1e-3)
    found = wc.along_wind_gust(100, 30, 30, 0.25, 55.0, "B", 0.015, 6.0e6, 1.0, rules)
    assert found["K"] == pytest.approx(1.65 ** (1 / 6.5) / (1 / 6.5 + 2), rel=0.05)
    peak = wc.peak_factor(0.25, rules) * found["sigma"] / 9.81 * 1e3
    assert 10 < peak < 100  # milli-g, a 100 m tower in a cyclone-prone wind
    with code_context.using(registry.load("eurocodes")):
        eu = wc.table()
        assert wc.speed_ratio(eu) == pytest.approx(0.9052, abs=1e-3)
        out = wc.turbulence_spectrum(100, 30, 0.25, 26.0, "III", 0.015, 3.0e6, 1.0, eu)
        assert out["K"] == pytest.approx(1.5, abs=0.01)  # Kx ≈ 1.5 for ξ = 1


def test_non_building_coefficients() -> None:
    # Site class SD (S 1.35), Z 0.2: SDS = 2/3 × 0.2 × 2.5 × 1.35 = 0.45
    rigid = nonbuilding.coefficient("elevatedTankBraced", 0.05, "SD", 0.2, 1.0)
    assert rigid["SDS"] == pytest.approx(0.45) and rigid["Cs"] == pytest.approx(0.135)
    plateau = nonbuilding.coefficient("elevatedTankBraced", None, "SD", 0.2, 1.0)
    assert plateau["Cs"] == pytest.approx(0.15) and plateau["omega0"] == 2.0
    rack = nonbuilding.coefficient("steelStorageRack", 1.0, "SD", 0.2, 1.0)
    assert rack["R"] == 4.0 and rack["Cs"] >= 0.03
