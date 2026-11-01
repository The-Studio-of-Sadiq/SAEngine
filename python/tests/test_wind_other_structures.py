"""B22: wind on other structures, topography, flexible eccentricity and signs, pinned through
the bnbc2020 code pack (BNBC 2020 Part 6 Sec 2.4.7, 2.4.11.3, 2.4.13-2.4.15; Figures 6.2.4,
6.2.20-6.2.23)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from saengine.codes import context as code_context
from saengine.fem import loads as fl
from saengine.fem import open_wind as ow


def _wind():
    return code_context.table("wind")


# ───────────────────── Sec 2.4.7, Eq 6.2.5, Figure 6.2.4: topography ─────────────────────


def _topo(feature: str, h: float, lh: float, x: float = 0.0, downwind: bool = False):
    return fl.Topography(feature, h, lh, x, downwind)


def test_topographic_multipliers_match_figure_6_2_4_exposure_b_table() -> None:
    # Figure 6.2.4, the multiplier table for Exposure B (BNBC's B), H/Lh = 0.30:
    # K1 0.43 ridge, 0.26 escarpment, 0.32 hill.
    for feature, k1 in (("ridge", 0.43), ("escarpment", 0.26), ("hill", 0.32)):
        terms = fl.topographic_terms(0.0, "B", _topo(feature, 30, 100))
        assert terms["K1"] == pytest.approx(k1, abs=0.006)
    # x/Lh = 1.0: K2 0.75 escarpment downwind, 0.33 all other cases.
    down = fl.topographic_terms(0.0, "B", _topo("escarpment", 30, 100, 100, True))
    assert down["K2"] == pytest.approx(0.75)
    up = fl.topographic_terms(0.0, "B", _topo("escarpment", 30, 100, 100))
    assert up["K2"] == pytest.approx(0.33, abs=0.005)
    # z/Lh = 0.2: K3 0.55 ridge, 0.61 escarpment, 0.45 hill.
    for feature, k3 in (("ridge", 0.55), ("escarpment", 0.61), ("hill", 0.45)):
        terms = fl.topographic_terms(20.0, "B", _topo(feature, 30, 100))
        assert terms["K3"] == pytest.approx(k3, abs=0.006)


def test_kzt_formula_and_exposure_column() -> None:
    # Kzt = (1 + K1 K2 K3)², K1/(H/Lh) by exposure: ridge A 1.30, C 1.55.
    terms = fl.topographic_terms(10.0, "A", _topo("ridge", 40, 100, 50))
    k1 = 1.30 * 0.4
    k2 = 1 - 50 / (1.5 * 100)
    k3 = math.exp(-3 * 10 / 100)
    assert terms["Kzt"] == pytest.approx((1 + k1 * k2 * k3) ** 2)
    assert fl.topographic_terms(0.0, "C", _topo("ridge", 40, 100))["K1"] == pytest.approx(0.62)


def test_steep_feature_note_2_and_limits() -> None:
    # H/Lh > 0.5: 0.5 for K1, Lh = 2H for K2 and K3 (note 2).
    terms = fl.topographic_terms(10.0, "B", _topo("hill", 40, 50, 20))
    assert terms["K1"] == pytest.approx(1.05 * 0.5)
    assert terms["Lh_m"] == pytest.approx(80)
    assert terms["K3"] == pytest.approx(math.exp(-4 * 10 / 80))
    # Sec 2.4.7.1 (iv) H/Lh ≥ 0.2 and (v) H ≥ 4.5 m (B, C) or 18.3 m (A).
    assert not fl.topographic_terms(0, "B", _topo("ridge", 10, 100))["applies"]
    assert not fl.topographic_terms(0, "A", _topo("ridge", 15, 30))["applies"]
    assert fl.topographic_terms(0, "B", _topo("ridge", 15, 30))["applies"]
    # Beyond μ·Lh from the crest, no speed-up: K2 = 0.
    assert fl.topographic_terms(0, "B", _topo("ridge", 30, 100, 400))["Kzt"] == 1.0


def test_velocity_pressure_takes_kzt_of_the_settings_topography() -> None:
    flat = fl.velocity_pressure(10.0, 65.7, "B", 1.0)
    topo = SimpleNamespace(
        feature="hill", height=30.0, length=100.0, distance=0.0, side="upwind", isolated=True
    )
    with fl.wind_overrides(SimpleNamespace(topography=topo)):
        kzt = fl.topographic_factor(10.0, "B")
        assert kzt > 1
        assert fl.velocity_pressure(10.0, 65.7, "B", 1.0) == pytest.approx(flat * kzt)
    # The settings' Kzt wins; a feature that is not isolated gives none.
    with fl.wind_overrides(SimpleNamespace(topography=topo, topographic=1.2)):
        assert fl.topographic_factor(10.0, "B") == 1.2
    topo.isolated = False
    with fl.wind_overrides(SimpleNamespace(topography=topo)):
        assert fl.topographic_factor(10.0, "B") == 1.0


# ───────────────────── Sec 2.4.11.3, Eq 6.2.23: flexible eccentricity ─────────────────────


def test_flexible_eccentricity_eq_6_2_23() -> None:
    terms = {"Iz": 0.2, "Q": 0.85, "R": 0.6, "gR": 3.9}
    eq, er = 4.5, 2.0
    gq = _wind().flexible.gQ
    a, b = gq * 0.85, 3.9 * 0.6
    expected = (eq + 1.7 * 0.2 * math.sqrt((a * eq) ** 2 + (b * er) ** 2)) / (
        1 + 1.7 * 0.2 * math.sqrt(a * a + b * b)
    )
    assert fl.flexible_eccentricity(eq, er, terms) == pytest.approx(expected)
    # eR = 0 and no resonance: e = eQ.
    assert fl.flexible_eccentricity(eq, 0.0, {**terms, "R": 0.0}) == pytest.approx(eq)


# ───────────────────── Sec 2.4.13, Figure 6.2.20: solid walls and signs ─────────────────────


def test_solid_sign_cases_a_b_coefficients() -> None:
    t = _wind().solidSigns
    assert ow.solid_sign_cf(t, 1.0, 0.05) == pytest.approx(1.80)
    assert ow.solid_sign_cf(t, 1.0, 45) == pytest.approx(1.30)
    assert ow.solid_sign_cf(t, 0.5, 2) == pytest.approx(1.70)
    assert ow.solid_sign_cf(t, 0.16, 45) == pytest.approx(1.95)
    assert ow.solid_sign_cf(t, 0.1, 100) == pytest.approx(1.95)  # held at the ends
    # Linear in s/h and B/s (note 5): s/h 0.6, B/s 3.
    row07 = (1.60 + 1.60) / 2
    row05 = (1.70 + 1.70) / 2
    assert ow.solid_sign_cf(t, 0.6, 3) == pytest.approx((row07 + row05) / 2)


def test_solid_sign_case_c_regions() -> None:
    t = _wind().solidSigns
    regions = ow.solid_sign_case_c(t, 0.5, 4)
    assert [r["Cf"] for r in regions] == pytest.approx([2.90, 1.90, 1.30, 1.10])
    assert regions[-1]["to_s"] == 4
    # B/s = 13: seven regions to the end; > 10s 0.55.
    long = ow.solid_sign_case_c(t, 0.5, 13)
    assert [r["Cf"] for r in long] == pytest.approx([4.00, 2.60, 2.00, 1.50, 1.35, 0.90, 0.55])
    # s/h > 0.8: × (1.8 − s/h) (note 4); return corner Lr/s = 1: × 0.75 on 0 to s.
    reduced = ow.solid_sign_case_c(t, 0.9, 13, return_corner=1.0)
    assert reduced[0]["Cf"] == pytest.approx(4.00 * 0.9 * 0.75)
    assert reduced[1]["Cf"] == pytest.approx(2.60 * 0.9)
    # B/s < 5: the first region is not starred, no return-corner factor.
    assert ow.solid_sign_case_c(t, 0.5, 4, return_corner=1.0)[0]["Cf"] == pytest.approx(2.90)
    assert ow.solid_sign_case_c(t, 0.5, 1.5) == []


def test_solid_sign_force_openings_and_open_signs() -> None:
    w = _wind()
    out = ow.solid_sign_wind(1.0, 0.85, 6.0, 3.0, 8.0)
    cf = ow.solid_sign_cf(w.solidSigns, 3 / 8, 2)
    assert out["cases"]["A"]["F_kN"] == pytest.approx(1.0 * 0.85 * cf * 18)
    assert out["cases"]["B"]["offset_m"] == pytest.approx(0.2 * 6)
    assert len(out["caseC"]) == 2
    # Openings < 30 %: Cf × (1 − (1 − ε)^1.5) (note 2).
    holed = ow.solid_sign_wind(1.0, 0.85, 6.0, 3.0, 8.0, solidity=0.8)
    assert holed["Cf"] == pytest.approx(cf * (1 - 0.2**1.5))
    # 30 % or more open: an open sign (Figure 6.2.22, flat members), on the solid area.
    open_sign = ow.solid_sign_wind(1.0, 0.85, 6.0, 3.0, 8.0, 0.5, None, w.openStructures)
    assert open_sign["kind"] == "open" and open_sign["Cf"] == 1.6
    assert open_sign["As_m2"] == pytest.approx(9.0)
    # A wall from the ground (s/h = 1): F 0.05 s above the centre.
    wall = ow.solid_sign_wind(1.0, 0.85, 30.0, 2.0, 2.0)
    assert wall["cases"]["A"]["z_m"] == pytest.approx(1.0 + 0.05 * 2.0)


# ───────────────────── Sec 2.4.14, Figures 6.2.21-6.2.22: other structures ─────────────────────


def test_chimney_coefficients_figure_6_2_21() -> None:
    t = _wind().chimneys
    assert ow.chimney_cf(t, "square", h_over_d=1) == 1.3
    assert ow.chimney_cf(t, "square", h_over_d=25) == 2.0
    assert ow.chimney_cf(t, "squareDiagonal", h_over_d=7) == 1.1
    assert ow.chimney_cf(t, "polygonal", h_over_d=4) == pytest.approx(1.1)
    big = 10.0  # D√qz > 5.3
    assert ow.chimney_cf(t, "round", "moderatelySmooth", 7, big) == 0.6
    assert ow.chimney_cf(t, "round", "rough", 25, big) == 0.9
    # Printed 0.2 at h/D 25 (very rough) is an apparent misprint: 1.2, the conservative value.
    assert ow.chimney_cf(t, "round", "veryRough", 25, big) == 1.2
    assert ow.chimney_cf(t, "round", "moderatelySmooth", 25, 5.0) == 1.2  # D√qz ≤ 5.3
    assert t.roundLimit == 5.3


def test_open_structures_round_limit_in_si() -> None:
    t = _wind().openStructures
    assert t.roundLimit == 5.3
    assert ow.lattice_cf(t, 0.2, rounded=True, d_sqrt_qz=5.3) == 1.3
    assert ow.lattice_cf(t, 0.2, rounded=True, d_sqrt_qz=5.4) == 0.9
    assert "2.4.14" in t.source and "6.2.22" in t.source


def test_chimney_form_member_loads() -> None:
    import numpy as np

    stack = ow.WindMember(0, np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 20.0]), 2.0)
    w = _wind()
    out = ow.open_structure_wind(
        [stack],
        lambda z: 1000.0,
        0.85,
        w.openStructures,
        "chimney",
        section="round",
        surface="rough",
        chimneys=w.chimneys,
    )
    # h/D = 10, D√qz = 2·√1000 > 5.3: rough 0.8 + (0.9 − 0.8)·3/18.
    cf = 0.8 + 0.1 * 3 / 18
    ((_, vector),) = out.loads["WX"]
    assert vector[0] == pytest.approx(1000.0 * 0.85 * cf * 2.0)
    assert out.summary["WX"]["Cf"] == pytest.approx(cf, abs=1e-3)


# ───────────────────── Sec 2.4.15: rooftop equipment ─────────────────────


def test_rooftop_factor() -> None:
    # 1.9 for Af ≤ 0.1·B·h, linear to 1.0 at B·h; none above h = 18.3 m.
    assert fl.rooftop_factor(5.0, 20.0, 10.0) == 1.9
    assert fl.rooftop_factor(200.0, 20.0, 10.0) == 1.0
    assert fl.rooftop_factor(110.0, 20.0, 10.0) == pytest.approx(1.9 - 0.9 * 0.5)
    assert fl.rooftop_factor(5.0, 20.0, 20.0) == 1.0


def test_rooftop_equipment_wind() -> None:
    item = ow.RooftopItem("tank", (3.0, 2.0), 2.0, "square")
    out = ow.rooftop_equipment_wind([item], 12.0, {"WX": 20.0, "WY": 30.0}, lambda z: 1.5, 0.85)
    cf = ow.chimney_cf(_wind().chimneys, "square", "all", 2.0 / 2.0)
    assert out["WX"] == pytest.approx(1.5 * 0.85 * cf * (2.0 * 2.0) * 1.9)
    assert out["WY"] == pytest.approx(1.5 * 0.85 * cf * (3.0 * 2.0) * 1.9)


# ───────────────────── in the derived model ─────────────────────


@pytest.fixture(scope="module")
def bay():
    from test_fem_derive import OBJECTS, PLAN

    from saengine.library import default_material_library
    from saengine.library.bim import generate

    return generate(PLAN, "s"), OBJECTS, default_material_library()


def _derive(bay, **wind):
    from saengine.fem.derive import derive_fem
    from saengine.library.settings import default_project_settings

    settings = default_project_settings("Bay")
    settings = settings.model_copy(
        update={"wind": settings.wind.model_copy(update=wind)}, deep=True
    )
    building, objects, materials = bay
    return derive_fem(building, objects, materials, settings, {"bim": "abc"})


def test_derive_rooftop_equipment_adds_to_the_roof_level(bay) -> None:
    from saengine.library.settings import RooftopEquipment

    plain = _derive(bay)
    tank = RooftopEquipment(name="tank", sizeX=2.0, sizeY=2.0, height=1.5)
    d = _derive(bay, rooftopEquipment=[tank])
    added = d.summary["wind"]["rooftop"]
    item = added["items"][0]["WX"]
    top = d.summary["wind"]["levels"]["WX"][-1]
    height = top["z"] - d.summary["wind"]["base_m"]
    assert added["WX"] > 0 and 1.0 < item["factor"] <= 1.9
    assert item["factor"] == pytest.approx(fl.rooftop_factor(item["Af_m2"], top["B_m"], height))
    assert d.summary["wind_X_kN"] == pytest.approx(plain.summary["wind_X_kN"] + added["WX"])
    assert any("rooftop equipment" in n for n in d.notes)


def test_derive_topography_raises_the_wind(bay) -> None:
    from saengine.library.settings import WindTopography

    plain = _derive(bay)
    hill = WindTopography(feature="hill", height=30.0, length=100.0)
    d = _derive(bay, topography=hill)
    topo = d.summary["wind"]["topography"]
    assert topo["applies"] and topo["Kzt"] > 1
    assert d.summary["wind_X_kN"] > plain.summary["wind_X_kN"]


def test_derive_flexible_eccentricity(bay, monkeypatch) -> None:
    cases = fl.WindDesignCases(0.75, 0.15, 0.75, 0.563, exemptHeight=1.0)
    monkeypatch.setattr(fl, "wind_design_cases", lambda: cases)
    d = _derive(bay, naturalFrequency=0.5, shearCentreDistance=1.0)
    gust = d.summary["wind"]["gust"]["X"]
    assert gust["flexible"]
    (level,) = gust["eccentricity"]["levels"]
    expected = fl.flexible_eccentricity(level["eQ_m"], 1.0, gust)
    assert level["e_m"] == pytest.approx(expected)
    row = d.summary["wind"]["levels"]["WX"][0]
    assert row["e_m"] == pytest.approx(expected)
    assert row["torsion_kNm"] == pytest.approx(row["force_kN"] * expected, rel=1e-6)
