"""Creep and shrinkage of the code pack (B25): the concreteTime table of the default pack and
the generic methods of saengine.fem.concrete_time.

The pinned values are those of BNBC 2020 Part 6 Sec 5.13.3-5.13.4 and Figures 6.5.1-6.5.2
(pp. 856-858), as digitised into the bnbc2020 pack, and Sec 9.6.6-9.6.7 (pp. 1144-1145)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from saengine.codes import tables
from saengine.fem import concrete_time as ct


@pytest.fixture(scope="module")
def table():
    return tables.builtin_table("concreteTime")


def test_pack_covers_concrete_time(table) -> None:
    manifest = tables.builtin_manifest()
    assert "concreteTime" in manifest["covers"]
    assert manifest["covers"][-1] == "concreteTime"
    assert table.creep.method == "tabulatedCoefficient"
    assert table.shrinkage.method == "tabulatedStrain"
    assert ct.table() is not None


def test_creep_development_sec_5_13_3(table) -> None:
    # 40 %, 60 % and 80 % of the final (30 year) creep after 1, 6 and 30 months.
    shares = {p.days: p.share for p in table.creep.development}
    assert shares == {30: 0.4, 182.5: 0.6, 912.5: 0.8, 10950: 1.0}
    assert table.creep.finalAgeDays == 10950
    assert ct.creep_share(0) == 0.0
    assert ct.creep_share(30) == pytest.approx(0.4)
    assert ct.creep_share(182.5) == pytest.approx(0.6)
    assert ct.creep_share(912.5) == pytest.approx(0.8)
    assert ct.creep_share(20000) == pytest.approx(1.0)
    assert 0.4 < ct.creep_share(100) < 0.6


def test_sealed_thickness_and_effective_thickness(table) -> None:
    assert table.creep.sealedThickness == 600  # Sec 5.13.3: drying prevented
    assert ct.effective_thickness(400 * 400, 1600) == pytest.approx(200.0)  # 2A/u
    assert ct.effective_thickness(1, 1, sealed=True) == 600


@pytest.mark.parametrize(
    ("thickness", "humidity", "age", "expected"),
    [
        # Figure 6.5.1 read at the indoor (45 %) and outdoor (85 %) lines.
        (150, 45, 28, 3.12),
        (150, 85, 28, 1.82),
        (300, 45, 7, 2.89),
        (600, 85, 365, 0.60),
        (150, 100, 1, 1.90),
        (300, 70, 90, 1.39),
    ],
)
def test_figure_6_5_1_creep_coefficient(thickness, humidity, age, expected) -> None:
    assert ct.creep_coefficient(thickness, humidity, age) == pytest.approx(expected, abs=0.005)


def test_creep_interpolation_and_clamping() -> None:
    # Linear between thicknesses, log scale between ages, clamped outside the figure.
    mid = ct.creep_coefficient(225, 45, 28)
    assert mid == pytest.approx((3.12 + 2.42) / 2, abs=0.005)
    between = ct.creep_coefficient(150, 45, math.sqrt(7 * 28))
    assert between == pytest.approx((3.72 + 3.12) / 2, abs=0.005)
    assert ct.creep_coefficient(100, 45, 28) == ct.creep_coefficient(150, 45, 28)
    assert ct.creep_coefficient(150, 30, 28) == ct.creep_coefficient(150, 40, 28)
    assert ct.creep_coefficient(150, 45, 0.5) == ct.creep_coefficient(150, 45, 1)
    # Older at loading, thicker, wetter: less creep.
    assert ct.creep_coefficient(150, 45, 90) < ct.creep_coefficient(150, 45, 28)
    assert ct.creep_coefficient(600, 45, 28) < ct.creep_coefficient(300, 45, 28)
    assert ct.creep_coefficient(150, 85, 28) < ct.creep_coefficient(150, 45, 28)


def test_eq_6_5_3_creep_strain() -> None:
    # εcc = stress / Et × cc
    assert ct.creep_strain(10.0, 25000.0, 2.0) == pytest.approx(8e-4)


@pytest.mark.parametrize(
    ("thickness", "humidity", "days", "expected"),
    [
        # Figure 6.5.2 (× 10⁻⁶): 30 year and 6 month shrinkage.
        (150, 45, 10950, 415),
        (150, 85, 10950, 132),
        (300, 45, 10950, 363),
        (600, 85, 10950, 95),
        (150, 45, 182.5, 187),
        (300, 85, 182.5, 32),
        (600, 45, 182.5, 44),
        (150, 100, 10950, -197),  # swelling
    ],
)
def test_figure_6_5_2_shrinkage(thickness, humidity, days, expected) -> None:
    assert ct.shrinkage_strain(thickness, humidity, days) == pytest.approx(expected * 1e-6)


def test_shrinkage_in_time_and_water(table) -> None:
    assert ct.shrinkage_strain(150, 45, 0) == 0.0
    early = ct.shrinkage_strain(150, 45, 30)
    assert 0 < early < 187e-6
    assert ct.shrinkage_strain(150, 45, 50000) == pytest.approx(415e-6)
    # Proportional to the water content within 150-230 litre/m³ (190 for the figure).
    assert table.shrinkage.referenceWater == 190
    assert tuple(table.shrinkage.waterRange) == (150, 230)
    base = ct.shrinkage_strain(150, 45, 10950)
    assert ct.shrinkage_strain(150, 45, 10950, 209) == pytest.approx(base * 1.1)
    assert ct.shrinkage_strain(150, 45, 10950, 300) == pytest.approx(base * 230 / 190)


def test_eq_6_5_4_reinforced_shrinkage(table) -> None:
    assert table.shrinkage.reinforcementCoefficient == {"internal": 25, "external": 15}
    assert ct.reinforced_shrinkage(400e-6, 0.02, "internal") == pytest.approx(400e-6 / 1.5)
    assert ct.reinforced_shrinkage(400e-6, 0.02, "external") == pytest.approx(400e-6 / 1.3)
    with pytest.raises(ct.NotCovered):
        ct.reinforced_shrinkage(400e-6, 0.02, "marine")


def test_exposure_and_conditions(table) -> None:
    assert table.exposure.indoor.relativeHumidity == 45
    assert table.exposure.outdoor.relativeHumidity == 85
    indoor = ct.Conditions.of(SimpleNamespace(exposure="indoor", relativeHumidity=None))
    assert (indoor.humidity, indoor.exposure) == (45, "internal")
    own = ct.Conditions.of(
        SimpleNamespace(exposure="outdoor", relativeHumidity=75, waterContent=200, curingDays=3)
    )
    assert (own.humidity, own.exposure, own.water, own.curing) == (75, "external", 200, 3)


def test_modulus_at_the_age_of_loading() -> None:
    # SAEngine practice: f'c(t) = t / (4 + 0.85 t), Ec ∝ √f'c by the pack's Ec rule.
    assert ct.strength_share(7) == pytest.approx(7 / (4 + 0.85 * 7))
    assert ct.strength_share(28) == 1.0  # capped at f'c
    assert ct.strength_share(365) == 1.0
    assert ct.modulus_ratio(7) == pytest.approx(math.sqrt(7 / (4 + 0.85 * 7)), rel=1e-6)
    assert ct.modulus_ratio(1000) == pytest.approx(1.0)


def test_prestress_lump_values_sec_9_6(table) -> None:
    p = table.prestress
    assert dict(zip(p.creepAgesDays, p.creepCoefficients, strict=True)) == {
        7: 2.2,
        28: 1.6,
        365: 1.1,
    }
    assert p.postTensionedCreepShare == 0.8
    assert p.pretensionedShrinkage == 0.0003
    assert p.postTensionedShrinkage == 0.0002
    assert [(d.days, d.share) for d in p.creepDevelopment] == [(30, 0.5), (182.5, 0.75)]
    assert [(d.days, d.share) for d in p.shrinkageDevelopment] == [(30, 0.5), (182.5, 0.75)]
