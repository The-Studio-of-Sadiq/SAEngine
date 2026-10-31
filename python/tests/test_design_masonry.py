"""Masonry walls to BNBC 2020 Part 6 Chapter 7 (strength design, the clauses of TMS 402 /
ACI 530-08 Chapter 3) and the low-rise masonry building template (T31)."""

from __future__ import annotations

import math

import pytest

from saengine.design import masonry as M
from saengine.design import walls as W
from saengine.design.rc import DesignError
from saengine.library.defaults import default_material_library


def test_prism_strength_from_units_and_mortar():
    # TMS 602 / ACI 530.1-08 Table 1 (clay), type M or S mortar: 1700 psi -> 1000 psi,
    # 2600 psi -> 1500 psi; linear between.
    assert M.prism_strength(17.2, "clay", "S") == pytest.approx(
        6.9 + (17.2 - 11.7) / (17.9 - 11.7) * (10.3 - 6.9)
    )
    assert M.prism_strength(11.7, "clay", "M") == pytest.approx(6.9)
    assert M.prism_strength(14.5, "clay", "N") == pytest.approx(6.9)
    assert M.prism_strength(99.0, "clay", "S") == pytest.approx(27.6)  # top row
    assert M.prism_strength(5.0, "clay", "S") is None  # below the table: prism tests
    assert M.prism_strength(13.1, "concrete", "S") == pytest.approx(10.3)  # Table 2


def test_mortar_type_from_the_mix():
    assert M.mortar_type_of_mix(3) == "M"
    assert M.mortar_type_of_mix(4) == "S"
    assert M.mortar_type_of_mix(6) == "N"


def test_masonry_of_the_default_brick():
    library = default_material_library()
    mats = {m.id: m for m in library.materials}
    brick = mats["BRICK-1"]
    with pytest.raises(DesignError):
        M.masonry_of(brick, mats)  # neither f'm nor a unit strength
    brick.masonry.unitStrength = 17.2
    m = M.masonry_of(brick, mats)
    assert m.mortar == "S"  # the 1:4 mortar M1-4
    assert m.fm == pytest.approx(9.916, abs=1e-3)
    assert m.fm_source == "units"
    assert m.em == pytest.approx(700 * m.fm)  # Sec 1.8.2.2.1
    assert m.emu == 0.0035  # Sec 3.3.2(c)


def test_slenderness_factor_eqs_3_15_3_16():
    r = 250 / math.sqrt(12)
    assert M.slenderness_factor(3000, r) == pytest.approx(1 - (3000 / (140 * r)) ** 2)
    assert M.slenderness_factor(8000, r) == pytest.approx((70 * r / 8000) ** 2)


def test_axial_strength():
    # Pn = 0.80 [0.80 An f'm] R
    r = 250 / math.sqrt(12)
    pn = M.axial_strength(1e6, 10.0, 3000, r)
    assert pn == pytest.approx(0.64 * 1e6 * 10.0 * (1 - (3000 / (140 * r)) ** 2))


def test_modulus_of_rupture_table_3_1_8_2():
    assert M.modulus_of_rupture(M.Masonry(10.0, mortar="S")) == pytest.approx(0.689)
    assert M.modulus_of_rupture(M.Masonry(10.0, mortar="N")) == pytest.approx(0.517)
    assert M.modulus_of_rupture(M.Masonry(10.0, units="hollow")) == pytest.approx(0.434)
    assert M.modulus_of_rupture(M.Masonry(10.0, grouting="full")) == pytest.approx(1.124)


def test_plain_shear_sec_3_2_4():
    m = M.Masonry(10.0)
    # 56 An psi (0.386 MPa) governs without axial force; + 0.45 Nu with it.
    assert M.plain_shear_strength(m, 1e6, 0.0) == pytest.approx(0.386e6)
    assert M.plain_shear_strength(m, 1e6, 1e6) == pytest.approx(0.836e6)
    # 3.8 An sqrt(f'm) psi (0.316 MPa) caps it.
    assert M.plain_shear_strength(m, 1e6, 5e6) == pytest.approx(0.316e6 * math.sqrt(10.0))
    assert M.plain_shear_strength(M.Masonry(10.0, bond="stack"), 1e6, 1e6) == pytest.approx(0.159e6)


def test_reinforced_shear_sec_3_3_4_1_2():
    vn, vnm, vns, cap = M.reinforced_shear_strength(
        1e6, 10.0, mu=500e6, vu=1e6, dv=1000.0, pu=0.0, av_s=0.0, fy=420.0
    )
    root = 1e6 * math.sqrt(10.0)
    assert vnm == pytest.approx(0.083 * (4.0 - 1.75 * 0.5) * root)
    assert vns == 0.0
    assert cap == pytest.approx((0.5 + (0.332 - 0.5) * (0.25 / 0.75)) * root)
    assert vn == pytest.approx(vnm)
    # Vns = 0.5 (Av/s) fy dv
    _, _, vns, _ = M.reinforced_shear_strength(1e6, 10.0, 0.0, 1e6, 1000.0, 0.0, 0.5, 400.0)
    assert vns == pytest.approx(0.5 * 0.5 * 400.0 * 1000.0)


def test_in_plane_moment_one_bar():
    # Pu = 0, one bar yielding: Mn about the centre = As fy (d - a/2), a = As fy / (0.8 f'm t).
    mn = M.in_plane_moment(1000, 200, [(900.0, 500.0)], 10.0, 400.0, 0.0, 0.0035)
    a = 500 * 400 / (0.8 * 10 * 200)
    assert mn == pytest.approx(500 * 400 * (900 - a / 2), rel=1e-4)
    # Above the crushing force: no moment.
    assert M.in_plane_moment(1000, 200, [(900.0, 500.0)], 10.0, 400.0, 1e8, 0.0035) == 0.0


def test_max_steel_sec_3_3_3_5():
    demand, capacity = M.max_steel_ratio(
        1000, 200, [(900.0, 500.0)], 10.0, 400.0, 0.0, 0.0035, 1.5, 200_000.0
    )
    c = 0.0035 / (0.0035 + 1.5 * 0.002) * 900
    assert capacity == pytest.approx(0.8 * 10 * 200 * 0.8 * c)
    assert demand == pytest.approx(500 * 400)


def test_out_of_plane_moment_sec_3_3_5_3():
    steel = math.pi * 16**2 / 4
    mn = M.out_of_plane_moment(1000, 125, steel, 10.0, 420.0, 0.0)
    a = steel * 420 / (0.8 * 10 * 1000)
    assert mn == pytest.approx(steel * 420 * (125 - a / 2))


def _forces(p: float, v: float, m3: float, m2: float = 0.0) -> list[W.PierForces]:
    return [W.PierForces("1.2D+1.6L", p, v, m3, 0.0, m2, False, "P1 bottom")]


def test_plain_wall_checks():
    g = W.WallGeometry(4000, 250, 3000, 3000)
    d = M.masonry_wall_checks(g, None, _forces(500e3, 50e3, 100e6), M.Masonry(10.3))
    names = [c["name"] for c in d.checks]
    assert any(n.startswith("Axial strength") for n in names)
    assert any(n.startswith("In-plane flexural tension") for n in names)
    assert any(n.startswith("In-plane shear") for n in names)
    assert all(c["ok"] for c in d.checks if not c["flag"])
    # f'm 10.3 MPa is below the 10.34 MPa of strength design: a flag, not a failure.
    assert any(c["flag"] for c in d.checks)
    # A large in-plane moment on little axial force cracks plain masonry.
    d = M.masonry_wall_checks(g, None, _forces(50e3, 50e3, 2000e6), M.Masonry(12.0))
    tension = next(c for c in d.checks if c["name"].startswith("In-plane flexural tension"))
    assert not tension["ok"]


def test_reinforced_wall_checks():
    g = W.WallGeometry(4000, 250, 3000, 3000)
    bars = W.WallBars(50, 16, 800, 10, 400, 1)
    d = M.masonry_wall_checks(g, bars, _forces(500e3, 50e3, 100e6, 5e6), M.Masonry(12.0))
    names = [c["name"] for c in d.checks]
    for start in (
        "Axial strength",
        "In-plane axial force and bending",
        "Largest steel",
        "In-plane shear",
        "Out-of-plane bending",
        "Slender wall",
        "Bar spacing",
        "Vertical bar area",
    ):
        assert any(n.startswith(start) for n in names), start
    assert all(c["ok"] for c in d.checks if not c["flag"])
    # 12 mm bars are below the 129 mm² of ordinary reinforced masonry shear walls.
    thin = W.WallBars(50, 12, 600, 10, 400, 1)
    d = M.masonry_wall_checks(g, thin, _forces(500e3, 50e3, 100e6), M.Masonry(12.0))
    area = next(c for c in d.checks if c["name"].startswith("Vertical bar area"))
    assert not area["ok"]


def test_masonry_template():
    from saengine.library.generator import generate_building

    spec = {
        "gridsX": [4000, 4000],
        "gridsY": [3500, 3500],
        "storyCount": 3,
        "system": "masonry",
        "location": "barishal",
        "siteClass": "SB",
    }
    result = generate_building(spec)
    assert result["summary"]["system"] == "masonryOrdinaryPlain"  # Category B
    assert result["summary"]["counts"]["columns"] == 0
    assert result["summary"]["counts"]["walls"] == 3 * 12  # 12 wall segments per storey
    assert result["settings"]["analysis"]["slabs"] == "shells"
    walls = [o for o in result["objects"]["objects"] if o["kind"] == "wall"]
    assert walls and all(o["material"] == "BRICK-1" for o in walls)
    brick = next(m for m in result["materials"]["materials"] if m["id"] == "BRICK-1")
    assert brick["mechanical"]["E"] > 0
    assert all(f["type"] == "strip" for f in result["substructure"]["foundations"])
    # Category C: reinforced masonry.
    result = generate_building({**spec, "location": "barishal", "siteClass": "SD"})
    assert result["summary"]["system"] == "masonryOrdinaryReinforced"
    walls = [o for o in result["objects"]["objects"] if o["kind"] == "wall"]
    assert all(o.get("reinforcement") for o in walls)
    # Category D: no masonry bearing wall system is permitted.
    with pytest.raises(ValueError, match="Category D"):
        generate_building({**spec, "location": "rangpur", "siteClass": "SD"})
