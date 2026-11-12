"""The standard steel section table against hand formulas and sectionproperties."""

from __future__ import annotations

import math

import pytest
from pydantic import TypeAdapter

from saengine.library import steel_sections as t
from saengine.library.objects import Profile
from saengine.library.sections import section_properties


def test_i_section_without_fillets_matches_hand_formulas():
    h, b, tw, tf = 300.0, 150.0, 7.1, 10.7
    s = t.i_section("I", "I", h, b, tw, tf, 0.0)
    hw = h - 2 * tf
    assert s.A == pytest.approx(2 * b * tf + hw * tw)
    assert s.Ix == pytest.approx((b * h**3 - (b - tw) * hw**3) / 12)
    assert s.Iy == pytest.approx(2 * tf * b**3 / 12 + hw * tw**3 / 12)
    assert s.Sx == pytest.approx(s.Ix / (h / 2))
    assert s.Zx == pytest.approx(b * tf * (h - tf) + tw * hw**2 / 4, rel=1e-6)
    assert s.Zy == pytest.approx(tf * b**2 / 2 + hw * tw**2 / 4, rel=1e-6)
    assert s.J == pytest.approx((2 * b * tf**3 + hw * tw**3) / 3)
    assert s.Cw == pytest.approx(s.Iy * (h - tf) ** 2 / 4)


def test_ipe300_with_fillets():
    s = t.find("IPE 300")
    # the four root fillets add (4 - π) r² to the plates
    plates = 2 * 150 * 10.7 + (300 - 21.4) * 7.1
    assert s.A == pytest.approx(plates + (4 - math.pi) * 15**2)
    assert s.mass == pytest.approx(s.A * 1e-6 * 7850)
    # against the finite-element section properties of the same profile
    fe = section_properties(TypeAdapter(Profile).validate_python(s.profile()))
    assert fe.area == pytest.approx(s.A, rel=0.003)
    assert fe.ixx == pytest.approx(s.Ix, rel=0.003)
    assert fe.iyy == pytest.approx(s.Iy, rel=0.003)
    assert s.J < fe.j  # the thin-walled J leaves out the fillets: conservative
    assert s.J > 0.7 * fe.j


def test_shs_matches_hand_formulas_and_fe():
    b, tt = 150.0, 8.0
    sq = t.rhs_section("SHS", "SHS", b, b, tt, ro=0.0)
    bi = b - 2 * tt
    assert sq.A == pytest.approx(b**2 - bi**2)
    assert sq.Ix == pytest.approx((b**4 - bi**4) / 12)
    assert sq.Zx == pytest.approx((b**3 - bi**3) / 4, rel=1e-6)
    assert sq.Ix == pytest.approx(sq.Iy)
    s = t.find("SHS 150x150x8")
    assert s.r == pytest.approx(2.5 * tt)
    fe = section_properties(TypeAdapter(Profile).validate_python(s.profile()))
    assert fe.area == pytest.approx(s.A, rel=0.005)
    assert fe.ixx == pytest.approx(s.Ix, rel=0.005)
    assert fe.j == pytest.approx(s.J, rel=0.02)


def test_chs_angle_and_channel():
    c = t.find("CHS 168.3x6.3")
    di = 168.3 - 12.6
    assert c.A == pytest.approx(math.pi / 4 * (168.3**2 - di**2))
    assert c.J == pytest.approx(2 * c.Ix)
    a = t.find("L 75x75x8")
    assert a.Ix == pytest.approx(a.Iy)
    assert a.Iu + a.Iv == pytest.approx(a.Ix + a.Iy)
    assert a.rv < a.rx and a.r_min == a.rv
    fe = section_properties(TypeAdapter(Profile).validate_python(a.profile()))
    assert fe.area == pytest.approx(a.A, rel=0.003)
    u = t.find("ISMC 200")
    assert 0 < u.cx < u.b / 2  # centroid towards the web


def test_table_order_families_and_matching():
    table = t.section_table()
    assert {s.family for s in table} == set(t.FAMILIES)
    for fam in t.FAMILIES:
        masses = [s.mass for s in t.family(fam)]
        assert masses == sorted(masses)
    # the sample's SHS 150 brace profile (square corners) matches the table section
    sample = {"shape": "rectangleHollow", "xDim": 150, "yDim": 150, "wallThickness": 8}
    assert t.match(sample).name == "SHS 150x150x8"
    assert t.family_of(sample) == "SHS"
    assert t.families_for(sample) == ("SHS", "RHS")
    rhs_turned = {"shape": "rectangleHollow", "xDim": 200, "yDim": 100, "wallThickness": 6}
    assert t.match(rhs_turned).name == "RHS 200x100x6"
    assert t.find("ipe  300").name == "IPE 300"
    custom = t.section_of_profile(
        {"shape": "rectangleHollow", "xDim": 155, "yDim": 155, "wallThickness": 7}
    )
    assert custom.name == "custom" and custom.A > 0
    data = t.table_json()
    assert len(data["sections"]) == len(table)


def test_rhs_on_its_side_has_its_own_axes():
    upright = t.find("RHS 200x100x8")
    lying = {"shape": "rectangleHollow", "xDim": 200, "yDim": 100, "wallThickness": 8}
    s = t.section_of_profile(lying)
    # the table section is its identity, the properties are in the profile's axes
    assert t.match(lying) is upright and t.is_turned(lying)
    assert s.name == upright.name and s.turned
    assert (s.h, s.b) == (upright.b, upright.h)
    assert s.Ix == pytest.approx(upright.Iy) and s.Iy == pytest.approx(upright.Ix)
    assert s.Zx == pytest.approx(upright.Zy) and s.Sx == pytest.approx(upright.Sy)
    assert s.A == pytest.approx(upright.A) and s.J == pytest.approx(upright.J)
    # weak axis horizontal: Ix is the smaller inertia
    assert s.Ix < s.Iy
    assert s.profile()["xDim"] == 200 and s.profile()["yDim"] == 100
    assert t.oriented(upright, lying).Ix == pytest.approx(s.Ix)
    assert t.turn(s).turned is False and t.turn(s).Ix == pytest.approx(upright.Ix)
    custom = t.section_of_profile(
        {"shape": "rectangleHollow", "xDim": 210, "yDim": 105, "wallThickness": 7}
    )
    assert custom.turned and custom.Ix < custom.Iy


@pytest.mark.parametrize("size", [40, 60, 100])
def test_wall_thickness_matches_exactly(size):
    for wall in (2.5, 3.0, 4.0):
        p = {"shape": "rectangleHollow", "xDim": size, "yDim": size, "wallThickness": wall}
        s = t.section_of_profile(p)
        assert s.name == f"SHS {size}x{size}x{t._fmt(wall)}" and s.tw == wall
    # a 2.8 mm wall is no table section: custom, its own area
    p = {"shape": "rectangleHollow", "xDim": size, "yDim": size, "wallThickness": 2.8}
    assert t.match(p) is None and t.section_of_profile(p).name == "custom"


def test_tee_by_hand_and_with_fillets():
    d, b, tw, tf = 200.0, 150.0, 8.0, 12.0
    s = t.tee_section("T", "T", d, b, tw, tf, 0.0)
    stem = d - tf
    area = b * tf + stem * tw
    cy = (b * tf * (d - tf / 2) + stem * tw * stem / 2) / area
    assert s.A == pytest.approx(area) and s.cy == pytest.approx(cy)
    ix = b * tf**3 / 12 + b * tf * (d - tf / 2 - cy) ** 2 + tw * stem**3 / 12
    ix += stem * tw * (stem / 2 - cy) ** 2
    assert s.Ix == pytest.approx(ix)
    assert s.Sx == pytest.approx(ix / cy)  # the stem tip is the far fibre
    profile = {"shape": "T", "depth": d, "flangeWidth": b, "flangeThickness": tf}
    profile |= {"webThickness": tw, "filletRadius": 10}
    fillets = t.section_of_profile(profile)
    assert fillets.shape == "T" and fillets.A == pytest.approx(area + (2 - math.pi / 2) * 100)
    fe = section_properties(TypeAdapter(Profile).validate_python(profile))
    assert fe.area == pytest.approx(fillets.A, rel=0.003)
    assert fe.ixx == pytest.approx(fillets.Ix, rel=0.003)


def test_mass_per_metre_is_the_nominal_section_with_its_corners():
    s = t.find("SHS 100x100x5")
    assert t.mass_per_metre(s.profile()) == round(s.A * 1e-6 * 7850, 3)
    assert t.mass_per_metre(s.profile(), 7800) == round(s.A * 1e-6 * 7800, 3)
    with pytest.raises(TypeError):
        t.mass_per_metre({"shape": "rectangle", "xDim": 100, "yDim": 100})
