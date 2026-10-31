"""Ribbed and waffle slabs, drop panels and column capitals (saengine.design.slab_systems) and
the slab design's additions for them (saengine.design.slab)."""

from __future__ import annotations

import pytest

from saengine.design import slab, slab_systems
from saengine.library.objects import ColumnCapital, DropPanel, Slab, SlabRibs


def _waffle() -> slab_systems.RibSection:
    return slab_systems.rib_section(
        75, SlabRibs(direction="both", width=125, depth=300, spacing=750)
    )


def test_rib_section_mean_and_equivalent_thickness():
    ribs = _waffle()
    assert ribs.total == 375
    assert ribs.clear == 625
    assert ribs.web_per_metre == pytest.approx(166.667, rel=1e-4)
    # Topping plus the ribs both ways, the crossings once: 75 + 300 (2/6 - 1/36).
    assert ribs.mean_thickness == pytest.approx(166.667, rel=1e-4)
    # One rib's T-section: y = 112.5 mm, I = 1.0986e9 mm⁴ per 750 mm; (12 I / 1000)^(1/3).
    assert ribs.inertia_per_metre() == pytest.approx(1.46484e9, rel=1e-4)
    assert ribs.bending_thickness == pytest.approx(260.0, rel=1e-3)


def test_one_way_ribs_count_once():
    ribs = slab_systems.rib_section(100, SlabRibs(direction="x", width=150, depth=250, spacing=600))
    assert ribs.directions == ("X",)
    assert ribs.mean_thickness == pytest.approx(100 + 250 * 0.25)


def test_analysis_thicknesses_of_a_solid_slab_are_its_own():
    solid = Slab(id="S", name="S", material="C", thickness=200)
    assert slab_systems.analysis_thicknesses(solid) == (200, 200, 200)
    assert slab_systems.design_depth(solid) == 200


def test_rib_geometry_limits():
    """ACI 318-19 9.8.1.1-9.8.1.3 and ACI 318-11 8.13.6.1."""
    bad = slab_systems.rib_section(50, SlabRibs(direction="both", width=90, depth=350, spacing=900))
    checks = {c["name"]: c for c in slab_systems.rib_geometry_checks(bad)}
    assert not checks["Rib width (joist construction)"]["ok"]  # 90 < 100
    assert not checks["Rib depth / width (joist construction)"]["ok"]  # 350 > 3.5 x 90
    assert not checks["Rib clear spacing (joist construction)"]["ok"]  # 810 > 750
    assert not checks["Topping thickness (joist construction)"]["ok"]  # 50 < 810 / 12
    good = {c["name"]: c for c in slab_systems.rib_geometry_checks(_waffle())}
    assert all(c["ok"] for c in good.values())


def test_capital_counts_inside_the_ninety_degree_pyramid():
    """ACI 318-11 13.1.2: min(size, c + 2 depth)."""
    capital = ColumnCapital(size=1200, depth=300)
    assert slab_systems.capital_size(500, capital) == 1100
    assert slab_systems.capital_size(500, ColumnCapital(size=800, depth=300)) == 800
    assert slab_systems.capital_size(500, None) == 500
    # Frustum 500 x 500 to 1000 x 1000 over 300 mm: 100 (1e6 + 2.5e5 + 5e5).
    assert slab_systems.capital_volume(
        500, 500, ColumnCapital(size=1000, depth=300)
    ) == pytest.approx(1.75e8)


def test_drop_panel_qualifies_by_projection_and_extent():
    """ACI 318-19 8.2.4: at least h/4 below the slab, at least l/6 each way."""
    ok, problems = slab_systems.drop_qualifies(
        250, DropPanel(depth=62.5, length=2400, width=2400), (7200, 7200)
    )
    assert ok and not problems
    ok, problems = slab_systems.drop_qualifies(
        250, DropPanel(depth=60, length=2000, width=2400), (7200, 7200)
    )
    assert not ok and len(problems) == 2


def test_drop_panel_depth_for_the_top_bars():
    """ACI 318-19 8.5.2.2: the projection counts up to a quarter of the reach beyond the face."""
    drop = DropPanel(depth=150, length=2400, width=2400)
    assert slab_systems.drop_flexure_depth(250, drop, 500, 500) == pytest.approx(400)
    deep = DropPanel(depth=300, length=2400, width=2400)
    assert slab_systems.drop_flexure_depth(250, deep, 500, 500) == pytest.approx(487.5)


def test_drop_zone_turns_with_the_column():
    assert slab_systems.drop_zone((0, 0), 0, 2000, 1000, (900, 400))
    assert not slab_systems.drop_zone((0, 0), 0, 2000, 1000, (400, 900))
    assert slab_systems.drop_zone((0, 0), 90, 2000, 1000, (400, 900))


def test_two_way_divisor_with_drop_panels():
    """BNBC 2020 Part 6 Table 6.6.3 (p. 902), with drop panels: 280 -> 36, 40, 40;
    420 -> 33, 36, 36; 520 -> 31, 34, 34."""
    assert slab.two_way_divisor(420, False, False, True) == pytest.approx(36)
    assert slab.two_way_divisor(420, True, False, True) == pytest.approx(33)
    assert slab.two_way_divisor(280, True, True, True) == pytest.approx(40)
    assert slab.two_way_divisor(520, False, False, True) == pytest.approx(34)
    thickness = slab.two_way_thickness(6000, 1.0, 0.0, 420, False, False, drop=True)
    assert thickness.required == pytest.approx(6000 / 36)
    assert "drop panels" in thickness.note
    # At least 100 mm with drop panels (ACI 318-19 8.3.1.1 (b)).
    assert slab.two_way_thickness(3000, 1.0, 0.0, 420, False, False, drop=True).required == 100


def test_ribbed_one_way_thickness_by_the_beam_row():
    """BNBC 2020 Part 6 Table 6.6.1 (p. 900): beams or ribbed one-way slabs l/16, 18.5, 21."""
    assert slab.one_way_thickness(6000, 0, 420, ribbed=True).required == pytest.approx(375)
    assert slab.one_way_thickness(7400, 1, 420, ribbed=True).required == pytest.approx(400)
    assert slab.one_way_thickness(6000, 0, 420).required == pytest.approx(300)


def test_required_area_for_the_rebar_contours():
    """ACI 22.2 stress block, φ = 0.90: Rn = Mu / (φ b d²), ρ = 0.85 f'c / fy (1 - √(1 -
    2 Rn / 0.85 f'c))."""
    assert slab.required_area(50e6, 150, 25, 420) == pytest.approx(940.05, rel=1e-4)
    assert slab.required_area(0.0, 150, 25, 420) == 0.0
    # Narrower compression (the ribs' webs) needs more steel for the same moment.
    assert slab.required_area(50e6, 300, 25, 420, width=166.7) > slab.required_area(
        50e6, 300, 25, 420
    )
