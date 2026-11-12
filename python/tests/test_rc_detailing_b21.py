"""B21: RC detailing and material rules by the code pack (bnbc2020 values pinned).

Clauses: BNBC 2020 Part 6 Sec 5.13.2 / 6.1.7.1 (Ec), 6.1.8.1 (λ), 8.1.11.2 (shrinkage steel),
6.3.6.4-6.3.6.7 (crack control, flange and skin steel), 6.4.5 (shear friction), 8.1.12.2
(integrity), 9.5.3 (Class C tendons); Part 4 Table 4.1.1 (fire, brick aggregate fallback).
"""

from __future__ import annotations

import pytest

from saengine.codes.tables import builtin_table
from saengine.design import rc_detailing as r
from saengine.design import slab
from saengine.design.rc import section_of
from saengine.library.objects import (
    BarGroup,
    LinearReinforcement,
    RectangleProfile,
    Transverse,
)


def _beam(depth: float = 600.0, sides: list[BarGroup] | None = None):
    reinforcement = LinearReinforcement(
        material="R",
        cover=40,
        longitudinal=[
            BarGroup(position="bottom", count=2, dia=20),
            BarGroup(position="top", count=2, dia=16),
            *(sides or []),
        ],
        transverse=Transverse(type="stirrup", dia=10, spacing=150),
    )
    return section_of(RectangleProfile(xDim=400, yDim=depth), reinforcement, 25, 420)


def test_pack_values() -> None:
    concrete = builtin_table("concrete", "bnbc2020")
    assert concrete.modulus.normal == 4700 and concrete.modulus.brick == 3750  # 5.13.2
    assert concrete.modulus.densityCoefficient == 0.043  # 6.1.7.1
    assert tuple(concrete.modulus.densityRange) == (1440, 2560)
    assert concrete.aggregates["brick"].shrinkageFactor == 1.5  # 8.1.11.2 (b)
    assert concrete.aggregates["lightweight"].lambdaFactor == 0.75  # 6.1.8.1
    assert concrete.aggregates["sandLightweight"].lambdaFactor == 0.85
    assert concrete.shrinkage.ratioLow == 0.0020 and concrete.shrinkage.ratioMin == 0.0014
    detailing = builtin_table("detailing", "bnbc2020")
    assert (detailing.crackControl.coefficient, detailing.crackControl.cap) == (380, 300)
    assert detailing.skin.depthOver == 900  # 6.3.6.7
    assert detailing.shearFriction.mu["monolithic"] == 1.4  # 6.4.5.4.3
    assert detailing.shearFriction.mu["notRoughened"] == 0.6
    assert detailing.integrity.minBars == 2  # 8.1.12.2
    assert detailing.tendonSpacing.deltaMax == 250  # 9.5.3.2 (c)


def test_concrete_modulus_by_aggregate() -> None:
    assert r.concrete_modulus(25.0, aggregate="siliceous")[0] == pytest.approx(23500.0)
    assert r.concrete_modulus(25.0, aggregate="brick")[0] == pytest.approx(18750.0)
    ec, how = r.concrete_modulus(25.0, 1800.0, "lightweight")
    assert ec == pytest.approx(0.043 * 1800**1.5 * 5)
    assert "wc" in how
    # Without a density in range the lightweight concrete keeps the normal-weight form.
    assert r.concrete_modulus(25.0, None, "lightweight")[0] == pytest.approx(23500.0)


def test_shrinkage_ratio_8_1_11_2() -> None:
    assert r.shrinkage_ratio(275, "siliceous")[0] == pytest.approx(0.0020)  # (a), was 0.00275
    assert r.shrinkage_ratio(350, "siliceous")[0] == pytest.approx(0.0020)
    assert r.shrinkage_ratio(420, "siliceous")[0] == pytest.approx(0.0018)
    assert r.shrinkage_ratio(500, "siliceous")[0] == pytest.approx(0.0018 * 420 / 500)
    assert r.shrinkage_ratio(700, "siliceous")[0] == pytest.approx(0.0014)
    assert r.shrinkage_ratio(350, "brick")[0] == pytest.approx(0.0030)  # (b) x 1.5
    with r.using_aggregate("brick"):
        assert slab.min_steel_ratio(420) == pytest.approx(0.0027)
    assert slab.min_steel_ratio(420, "siliceous") == pytest.approx(0.0018)
    assert r.shrinkage_spacing(150.0)[0] == pytest.approx(450.0)  # (c) min(5h, 450)
    assert r.shrinkage_spacing(80.0)[0] == pytest.approx(400.0)


def test_crack_spacing_eq_6_6_11() -> None:
    # fs = 280 MPa, cc = 50 mm: min(380 - 125, 300) = 255 mm.
    assert r.crack_spacing_limit(280.0, 50.0) == pytest.approx(255.0)
    # fs = 200 MPa: 380 x 1.4 - 2.5 x 30 = 457, capped at 300 x 1.4 = 420.
    assert r.crack_spacing_limit(200.0, 30.0) == pytest.approx(420.0)
    assert r.service_stress(420.0) == pytest.approx(280.0, abs=0.01)


def test_tendon_spacing_9_5_3() -> None:
    limit, _ = r.tendon_spacing_limit(200.0, 50.0)
    assert limit == pytest.approx(0.666667 * (380 * 1.4 - 125), abs=0.01)  # 2/3 of 407
    full, _ = r.tendon_spacing_limit(100.0, 50.0)  # Δfps <= 140: no reduction
    assert full == pytest.approx(min(380 * 2.8 - 125, 300 * 2.8))
    assert r.tendon_spacing_limit(300.0, 50.0)[0] == 0.0  # above 250 MPa


def test_beam_faces_and_checks() -> None:
    section = _beam()
    bottom = r.face_spacing(section, top=False)
    assert bottom is not None
    # 400 wide, 40 cover + Ø10 stirrup: Ø20 centres 2 x (200 - 50 - 10) = 280 apart, cc 50.
    assert bottom.spacing == pytest.approx(280.0) and bottom.cc == pytest.approx(50.0)
    checks = [
        {"name": "Flexure, sagging (bottom bars)", "demand": 100.0},
        {"name": "Flexure, hogging (top bars)", "demand": 50.0},
    ]
    rows = {c["name"]: c for c in r.beam_checks(section, checks, perimeter=True, span=6000,
                                                flange=(125.0, 1))}  # fmt: skip
    crack = rows["Crack control, bottom bars"]
    assert crack["capacity"] == pytest.approx(255.0, abs=0.01) and not crack["ok"]
    assert "Skin reinforcement" not in rows  # h = 600 <= 900
    # One side: bf = 400 + min(6000/12, 6 x 125) = 900 > 600 = span / 10.
    assert "over 600 mm" in rows["Crack control, top bars"]["note"]
    assert "outer flange" in rows["Crack control, top bars"]["note"]
    assert rows["Integrity, continuous top bars"]["ok"]
    assert rows["Integrity, continuous bottom bars"]["ok"]


def test_skin_steel_6_3_6_7() -> None:
    bare = _beam(1000.0)
    faces = {"bottom": True, "top": False}
    found = r.skin_check(bare, faces)
    assert found is not None and not found["ok"]
    sides = _beam(1000.0, [BarGroup(position="sides", count=6, dia=12)])
    found = r.skin_check(sides, faces)
    assert found is not None and found["ok"], found


def test_integrity_interior_beam_bottom_only() -> None:
    rows = r.integrity_check(_beam(), perimeter=False)
    assert [row["name"] for row in rows] == ["Integrity, continuous bottom bars"]


def test_shear_friction_6_4_5() -> None:
    found = r.shear_friction(1000.0, 500.0, 25.0, 300 * 300, "roughened", aggregate="siliceous")
    assert found is not None
    assert found.vn == pytest.approx(1.0 * 1000 * 420)  # fy capped at 420 (6.4.5.6)
    assert found.limit == pytest.approx(5.0 * 90000)  # min(0.2 x 25, 3.3 + 2, 11)
    assert found.phi_vn == pytest.approx(0.75 * 420000)
    other = r.shear_friction(1000.0, 420.0, 40.0, 90000, "notRoughened", aggregate="siliceous")
    assert other.limit == pytest.approx(5.5 * 90000)  # min(0.2 x 40, 5.5)
    light = r.shear_friction(1000.0, 420.0, 25.0, 90000, "monolithic", aggregate="lightweight")
    assert light.mu == pytest.approx(1.4 * 0.75)
    with_tension = r.shear_friction(
        1000.0, 420.0, 25.0, 90000, "roughened", tension=100000.0, aggregate="siliceous"
    )
    assert with_tension.vn == pytest.approx(420000 - 100000)  # 6.4.5.7


def test_brick_fire_rows_fall_back_to_siliceous() -> None:
    from saengine.design.fire_resistance import required

    assert required("thickness", 2, "brick") == required("thickness", 2, "siliceous")
    assert required("columnSize", 2, "brick") == required("columnSize", 2, "siliceous")


def test_settings_accept_brick() -> None:
    from saengine.library.settings import Construction

    assert Construction(aggregate="brick").aggregate == "brick"
