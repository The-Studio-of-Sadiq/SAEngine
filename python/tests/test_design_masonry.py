"""Masonry walls by the code pack's allowable stress method (bnbc2020: Part 6 Chapter 7, Sec
7.3-7.6), the dimension and detailing rules, and the low-rise masonry building template.

The values are pinned through the bnbc2020 pack; each test names the clause it pins."""

from __future__ import annotations

import math

import pytest

from saengine.codes import context as code_context
from saengine.design import masonry as M
from saengine.design import masonry_asd as A
from saengine.design import masonry_dimensions as D
from saengine.design import walls as W
from saengine.design.rc import DesignError
from saengine.library.defaults import default_material_library


def test_the_pack_chooses_the_allowable_stress_method():
    # Sec 7.4.2.1 (p. 1011): working stress design, linear stress-strain.
    assert M.table().method == "allowableStress"
    assert M.method_module() is A
    assert M.combinations_kind() == "allowable"
    assert "allowable stress" in M.method_text()[0]


def test_mortar_grades_table_6_7_1():
    # Table 6.7.1 (p. 1004): M1-M6, 1:3 to 1:8, 10 to 1 N/mm².
    mortars = M.table().mortars
    assert [(g, mortars[g].sand, mortars[g].strength) for g in M.mortar_grades()] == [
        ("M1", 3.0, 10.0),
        ("M2", 4.0, 7.5),
        ("M3", 5.0, 5.0),
        ("M4", 6.0, 3.0),
        ("M5", 7.0, 2.0),
        ("M6", 8.0, 1.0),
    ]
    assert M.mortar_grade_of_mix(3) == "M1"
    assert M.mortar_grade_of_mix(4) == "M2"
    assert M.mortar_grade_of_mix(4.5) == "M3"  # leaner than M2: the next grade
    assert M.mortar_grade_of_mix(2) == "M1"
    assert M.mortar_grade_of_mix(9) is None  # leaner than M6


def test_elastic_moduli_sec_7_3_8():
    # Eqs 6.7.12-6.7.14 (p. 1008): Em = 750 f'm ≤ 15,000; Es 200,000; G = 0.4 Em.
    assert M.Masonry(10.0).em == pytest.approx(7500.0)
    assert M.Masonry(25.0).em == pytest.approx(15000.0)
    assert M.Masonry(10.0).g == pytest.approx(3000.0)
    assert M.table().elastic.es == 200000.0


def test_prism_estimate_is_labelled_and_limited():
    # Sec 7.3.3: prism tests; the TMS 602 table is kept only as a labelled estimate.
    estimate = M.table().prismEstimate
    assert "not BNBC" in estimate.label
    fm = M.prism_estimate(17.2, "clay", "M2")
    assert fm == pytest.approx(6.9 + (17.2 - 14.5) / (22.8 - 14.5) * (10.3 - 6.9))
    assert M.prism_estimate(17.2, "clay", "M4") is None  # not with a lean mortar
    assert M.prism_estimate(5.0, "clay", "M1") is None  # below the table


def test_masonry_of_the_default_brick_and_the_50_percent_route():
    library = default_material_library()
    mats = {m.id: m for m in library.materials}
    brick = mats["BRICK-1"]
    with pytest.raises(DesignError):
        M.masonry_of(brick, mats)  # neither f'm nor a unit strength
    brick.masonry.unitStrength = 17.2
    m = M.masonry_of(brick, mats)
    assert m.mortar == "M2"  # the 1:4 mortar M1-4
    assert m.fm == pytest.approx(8.006, abs=1e-3)
    assert m.fm_source == "estimate"
    # Sec 7.3.5 / 7.3.3.1(b): an estimated f'm is used with 50 % of the allowable stresses,
    # even with special inspection.
    brick.masonry.specialInspection = True
    assert M.allowable_share(M.masonry_of(brick, mats)) == 0.5
    brick.masonry.fm = 9.0
    assert M.allowable_share(M.masonry_of(brick, mats)) == 1.0
    brick.masonry.specialInspection = False
    assert M.allowable_share(M.masonry_of(brick, mats)) == 0.5
    # An old TMS mortar type is not a grade of the pack: the mix gives it, with a note.
    brick.masonry.mortarType = "S"
    m = M.masonry_of(brick, mats)
    assert m.mortar == "M2" and any("not a grade" in n for n in m.notes)


def test_allowable_axial_eqs_6_7_1_6_7_2():
    # Eq 6.7.1 (p. 1005): Fa = (f'm/5)[1 - (h'/42t)³].
    assert A.allowable_axial(10.0, 3000, 250) == pytest.approx(2.0 * (1 - (3000 / 10500) ** 3))
    # Eq 6.7.2: columns add As Fsc / (1.5 Ag).
    fa = A.allowable_axial_column(10.0, 3000, 250, 1000.0, 250 * 250, 165.0)
    assert fa == pytest.approx((2.0 + 1000 * 165 / (1.5 * 62500)) * (1 - (3000 / 10500) ** 3))


def test_flexural_compression_eq_6_7_3():
    assert A.allowable_flexural_compression(10.0) == pytest.approx(3.3)
    assert A.allowable_flexural_compression(40.0) == pytest.approx(10.0)  # capped


def test_flexural_tension_tables_6_7_2_6_7_3():
    # Table 6.7.2 (p. 1006): normal to bed joints 0.20 solid, 0.12 hollow (M1, M2).
    assert A.allowable_flexural_tension(M.Masonry(10.0, mortar="M2")) == pytest.approx(0.20)
    assert A.allowable_flexural_tension(M.Masonry(10.0, mortar="M1", units="hollow")) == (
        pytest.approx(0.12)
    )
    # M3, M4: 25 % less; M5, M6: not given, none allowed (conservative).
    assert A.allowable_flexural_tension(M.Masonry(10.0, mortar="M3")) == pytest.approx(0.15)
    assert A.allowable_flexural_tension(M.Masonry(10.0, mortar="M5")) == 0.0
    # Table 6.7.3: normal to head joints by unit; none in stack bond.
    assert A.allowable_flexural_tension(M.Masonry(10.0, mortar="M1"), "head") == (
        pytest.approx(0.35)
    )
    assert A.allowable_flexural_tension(
        M.Masonry(10.0, kind="concrete", mortar="M1", units="hollow"), "head"
    ) == pytest.approx(0.25)
    assert A.allowable_flexural_tension(M.Masonry(10.0, mortar="M1", bond="stack"), "head") == 0
    assert A.bond_stress(True) == 1.0 and A.bond_stress(False) == 0.30


def test_shear_eqs_6_7_4_to_6_7_6_and_table_6_7_4():
    # Eqs 6.7.4-6.7.5: flexural members.
    assert A.allowable_beam_shear(4.0) == pytest.approx(0.166)
    assert A.allowable_beam_shear(16.0) == pytest.approx(0.25)
    assert A.allowable_beam_shear(4.0, reinforced=True) == pytest.approx(0.5)
    assert A.allowable_beam_shear(16.0, reinforced=True) == pytest.approx(0.75)
    # Eq 6.7.6 (pp. 1006-1007): plain shear walls, clay 0.025√f'm ≤ 0.40; concrete by mortar.
    assert A.allowable_wall_shear_plain(M.Masonry(9.0)) == pytest.approx(0.075)
    assert A.allowable_wall_shear_plain(M.Masonry(400.0)) == pytest.approx(0.40)
    concrete = M.Masonry(10.0, kind="concrete", mortar="M2")
    assert A.allowable_wall_shear_plain(concrete) == pytest.approx(0.20)
    assert A.allowable_wall_shear_plain(M.Masonry(10.0, kind="concrete", mortar="M3")) == 0.12
    assert A.allowable_wall_shear_plain(M.Masonry(10.0, kind="concrete", mortar="M4")) == 0.0
    # Table 6.7.4 (p. 1007).
    assert A.allowable_wall_shear_reinforced(9.0, 0.5, False) == pytest.approx(3.5 / 36 * 3)
    assert A.allowable_wall_shear_reinforced(16.0, 0.0, False) == pytest.approx(0.4)
    assert A.allowable_wall_shear_reinforced(9.0, 1.2, False) == pytest.approx(0.17)
    assert A.allowable_wall_shear_reinforced(9.0, 0.5, True) == pytest.approx(3.5 / 24 * 3)
    assert A.allowable_wall_shear_reinforced(9.0, 1.0, True) == pytest.approx(0.37)


def test_steel_stresses_sec_7_3_6():
    # Eqs 6.7.7-6.7.10 (p. 1007).
    assert A.allowable_steel(420.0) == pytest.approx(165.0)
    assert A.allowable_steel(250.0, "tensionPlain") == pytest.approx(100.0)
    assert A.allowable_steel(420.0, "tensionPlain") == pytest.approx(135.0)
    assert A.allowable_steel(300.0, "compressionWalls") == pytest.approx(120.0)
    assert A.allowable_steel(300.0, "compressionFlexural") == pytest.approx(150.0)


def test_lateral_increase_sec_7_3_1():
    lateral = {"D + 0.7EX"}
    assert A.lateral_factor("D + 0.7EX", lateral) == pytest.approx(4 / 3, rel=1e-6)
    assert A.lateral_factor("D + L", lateral) == 1.0
    assert M.table().quality.reducedShare == 0.5  # Sec 7.3.5


def test_design_coefficients_and_cracked_section_eqs_6_7_28_to_6_7_32():
    k, j = A.design_coefficients(10.0, 0.005)
    assert k == pytest.approx(math.sqrt(0.05**2 + 0.1) - 0.05)
    assert j == pytest.approx(1 - k / 3)
    # Pure bending of one bar: the cracked section is the rectangular element of 7.6.5.1.
    fb, fs = A.flexural_stresses(10e6, 1000, 150, 500, 10.0)
    sigma, steel, c = A.cracked_section(200, 1000, [(150.0, 500.0)], 0.0, 10e6, 10.0)
    k, _ = A.design_coefficients(10.0, 500 / (1000 * 150))
    assert c == pytest.approx(k * 150, rel=1e-4)
    assert sigma == pytest.approx(fb, rel=1e-4)
    assert steel == pytest.approx(fs, rel=1e-4)
    # Uncracked: the gross section.
    sigma, steel, _ = A.cracked_section(200, 1000, [(150.0, 500.0)], 1e6, 1e6, 10.0)
    assert sigma == pytest.approx(1e6 / 2e5 + 1e6 / (1000 * 200**2 / 6))
    assert steel == 0.0


def test_dimension_rules_sec_7_4():
    # 7.4.2.2: a free top doubles the height.
    assert D.effective_height(3000, braced_top=False) == 6000
    assert D.effective_height_between_openings(3000, 1200) == pytest.approx(0.75 * 3000 + 300)
    assert D.effective_height_between_openings(3000, 1600, full_restraint=False) == 6000
    # Table 6.7.8.
    assert D.effective_length(4000, "continuousBothEnds") == pytest.approx(3200)
    assert D.effective_length(4000, "freeSupported") == pytest.approx(8000)
    # 7.4.2.4(d): stiffening coefficient, linear between.
    assert D.stiffening_coefficient(6, 2) == pytest.approx(1.4)
    assert D.stiffening_coefficient(7, 2) == pytest.approx(1.35)
    assert D.stiffening_coefficient(6, 2.5) == pytest.approx(1.7)
    assert D.stiffening_coefficient(25, 3) == pytest.approx(1.0)
    # 7.4.2.5: slenderness 20 walls, 12 columns.
    assert D.slenderness_limit("wall") == 20 and D.slenderness_limit("column") == 12
    # Table 6.7.9 (p. 1017).
    assert D.stiffening_walls(200, 3) == {"storeyHeight": 3200, "thickness": 100, "spacing": 6000}
    assert D.stiffening_walls(200, 4)["thickness"] == 200
    assert D.stiffening_walls(100, 4) is None
    assert D.stiffening_walls(400, 2)["spacing"] == 8000
    assert D.stiffening_walls(250, 6) is None
    assert D.needs_stability_analysis(8500) and not D.needs_stability_analysis(8000)
    # Table 6.7.10 (p. 1018).
    assert D.basement_ground_height(375, 40) == 2000
    assert D.basement_ground_height(375, 60) == 2500
    assert D.basement_ground_height(300, 40) == 1400
    assert D.basement_ground_height(200, 40) is None
    # Table 6.7.11 (p. 1018).
    assert D.free_standing_ratio(250) == 10
    assert D.free_standing_ratio(700) == 5
    assert D.free_standing_ratio(1200) is None
    # 7.4.9.1 and 7.4.9.4 (p. 1021).
    assert D.minimum_bearing_thickness(1, 3000) == 165
    assert D.minimum_bearing_thickness(2, 3000) == 250
    assert D.minimum_bearing_thickness(1, 3500) == 250
    assert D.parapet_ok(200, 800) and not D.parapet_ok(200, 900)
    assert not D.parapet_ok(200, 800, wall_below=250)
    assert D.concentrated_load_length(300, 250) == 1300
    assert D.concentrated_load_length(300, 250, spacing=1000) == 1000
    assert D.lateral_support_force(100.0) == pytest.approx(2.5)


def test_arches_corbels_and_bar_details():
    # 7.5.6-7.5.7 (pp. 1022-1023).
    assert D.arch_thrust_ok(30, 200) and not D.arch_thrust_ok(40, 200)
    assert D.corbel_slope_ok(60) and not D.corbel_slope_ok(55)
    # Eqs 6.7.34-6.7.35 (p. 1027), plain bars × 2.
    assert D.development_length(16, 165) == pytest.approx(0.29 * 16 * 165)
    assert D.development_length(16, 165, compression=True) == pytest.approx(0.22 * 16 * 165)
    assert D.development_length(16, 165, plain=True) == pytest.approx(2 * 0.29 * 16 * 165)
    # 7.6.6.7 (p. 1030): at least 40 db in tension, +30 % for close splices.
    assert D.lap_length(16, 100) == pytest.approx(640)
    assert D.lap_length(16, 100, close=True) == pytest.approx(832)
    # Table 6.7.12 (p. 1029), the overlap read conservatively: 8 db from 8 mm.
    assert D.bend_diameter(6) == pytest.approx(36)
    assert D.bend_diameter(20) == pytest.approx(160)
    assert D.bend_diameter(10, stirrup=True) == pytest.approx(40)
    # 7.6.4 and 7.6.6.3.
    assert D.shear_spacing_limit(1000) == 500 and D.shear_spacing_limit(2000) == 600
    assert D.least_clear_spacing(16) == 25 and D.least_clear_spacing(32) == 32
    assert D.least_cover("soil") == 50
    assert D.reinforced_effective_width(250, 2000) == 1500
    assert D.reinforced_effective_width(250, 2000, "stack") == 750


def test_strength_and_seismic_values_for_the_later_checks():
    s = M.table().strength
    # Sec 7.7.1.2(c), 7.7.2.2 (pp. 1031-1034).
    assert s.phi["slenderFlexure"] == 0.80
    assert s.phi["axial"] == 0.65 and s.phi["axialMax"] == 0.85
    assert s.phi["shear"] == 0.60 and s.phi["shearFlexure"] == 0.80
    # 7.7.1.2(d)(iii), (vi); 7.7.2.3(b).
    assert s.ultimateStrain == 0.003
    assert s.stressBlock["stress"] == 0.85 and s.stressBlock["depth"] == 0.85
    # Eqs 6.7.44-6.7.45; 7.7.2.3(c); 7.7.1.
    assert s.axial["masonry"] == 0.85 and s.axial["reduction"] == 0.80
    assert s.fmRange["shearWall"] == [7.0, 20.0] and s.fmRange["slenderWallMax"] == 40.0
    # Table 6.7.13 (p. 1033).
    assert s.modulusOfRupture["solid"]["full"].factor == 0.17
    assert s.modulusOfRupture["solid"]["partial"] is None
    assert s.modulusOfRupture["hollow"]["partial"].cap == 0.65
    # Eqs 6.7.47-6.7.48; Table 6.7.14 misprint read as 6 and 4 √psi.
    assert s.shear["cdLow"] == 2.4 and s.shear["cdHigh"] == 1.2
    assert s.shear["maxLow"] == pytest.approx(0.498) and s.shear["maxHigh"] == pytest.approx(0.332)
    # Eq 6.7.36, 7.7.1, Eq 6.7.39, 7.7.1.1(a).
    assert s.slenderWall == {
        "axialMax": 0.04,
        "minThickness": 150.0,
        "deflection": 0.007,
        "maxSteelRatio": 0.5,
    }
    seismic = M.table().seismic
    # 7.8.3-7.8.5 (pp. 1036-1038).
    assert seismic.unitStrengthMin == 12.0 and seismic.leanestMortar == "M3"
    assert seismic.zone23["barMin"] == 12 and seismic.zone23["verticalSpacing"] == 1200
    assert seismic.zone23["horizontalSpacing"] == 3000
    assert seismic.zone4["totalRatio"] == 0.002 and seismic.zone4["eachRatio"] == 0.0007
    assert seismic.zone4["barMin"] == 10 and seismic.zone4["maxSpacing"] == 1200


def _forces(p: float, v: float, m3: float, m2: float = 0.0, name: str = "D + L") -> list:
    return [W.PierForces(name, p, v, m3, 0.0, m2, False, "P1 bottom")]


def test_plain_wall_checks():
    g = W.WallGeometry(4000, 250, 3000, 3000)
    inspected = M.Masonry(8.0, mortar="M2", inspected=True)
    d = M.masonry_wall_checks(g, None, _forces(500e3, 50e3, 100e6), inspected, storeys=3)
    names = [c["name"] for c in d.checks]
    for start in (
        "Slenderness",
        "Bearing wall thickness",
        "Axial stress",
        "Combined",
        "Flexural tension",
        "In-plane shear",
        "Out-of-plane shear",
    ):
        assert any(n.startswith(start) for n in names), start
    assert all(c["ok"] for c in d.checks if not c["flag"])
    assert all("BNBC 2020 Part 6 Sec 7" in n for n in names)  # the pack's clauses
    # Without special inspection the same shear fails at 50 % of Fv (Sec 7.3.5).
    d = M.masonry_wall_checks(g, None, _forces(500e3, 50e3, 100e6), M.Masonry(8.0, mortar="M2"))
    shear = next(c for c in d.checks if c["name"].startswith("In-plane shear"))
    assert shear["capacity"] == pytest.approx(0.5 * 0.025 * math.sqrt(8.0), abs=0.01)
    assert not shear["ok"]
    # With earthquake the allowable stresses rise by one third (Sec 7.3.1).
    d = M.masonry_wall_checks(
        g,
        None,
        _forces(500e3, 50e3, 100e6, name="D + 0.7EX"),
        M.Masonry(8.0, mortar="M2"),
        lateral={"D + 0.7EX"},
    )
    shear = next(c for c in d.checks if c["name"].startswith("In-plane shear"))
    assert shear["capacity"] == pytest.approx(0.5 * 4 / 3 * 0.025 * math.sqrt(8.0), abs=0.01)
    # A large in-plane moment on little axial force exceeds Ft.
    d = M.masonry_wall_checks(g, None, _forces(50e3, 5e3, 1000e6), inspected)
    tension = next(c for c in d.checks if c["name"].startswith("Flexural tension"))
    assert not tension["ok"]
    # A thin wall fails the slenderness and the bearing thickness.
    d = M.masonry_wall_checks(
        W.WallGeometry(4000, 125, 3000, 3000), None, _forces(50e3, 0, 0), inspected
    )
    assert not next(c for c in d.checks if c["name"].startswith("Slenderness"))["ok"]
    assert not next(c for c in d.checks if c["name"].startswith("Bearing wall"))["ok"]


def test_reinforced_wall_checks():
    g = W.WallGeometry(4000, 250, 3000, 3000)
    bars = W.WallBars(50, 16, 800, 12, 400, 1)
    m = M.Masonry(10.0, mortar="M2", inspected=True)
    d = M.masonry_wall_checks(g, bars, _forces(500e3, 50e3, 100e6, 5e6), m, storeys=3)
    names = [c["name"] for c in d.checks]
    for start in (
        "Axial stress",
        "Combined",
        "In-plane steel stress",
        "Out-of-plane steel stress",
        "In-plane shear",
        "Bar diameter",
        "Clear spacing",
        "Cover",
    ):
        assert any(n.startswith(start) for n in names), start
    assert all(c["ok"] for c in d.checks if not c["flag"])
    # A large in-plane shear needs the reinforcement to take it all (Table 6.7.4).
    d = M.masonry_wall_checks(g, bars, _forces(500e3, 600e3, 100e6), m)
    shear = next(c for c in d.checks if c["name"].startswith("In-plane shear"))
    assert "reinforcement taking all the shear" in shear["note"]
    assert any(c["name"].startswith("Shear bar spacing") for c in d.checks)


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
    assert brick["mechanical"]["E"] == pytest.approx(750 * 8.006, abs=1)  # Eq 6.7.12
    assert all(f["type"] == "strip" for f in result["substructure"]["foundations"])
    # Category C: reinforced masonry, 12 mm horizontal bars (Sec 7.8.4.1 least size).
    result = generate_building({**spec, "location": "barishal", "siteClass": "SD"})
    assert result["summary"]["system"] == "masonryOrdinaryReinforced"
    walls = [o for o in result["objects"]["objects"] if o["kind"] == "wall"]
    assert all(o.get("reinforcement") for o in walls)
    assert all(o["reinforcement"]["horizontal"]["dia"] >= 12 for o in walls)
    # Category D: no masonry bearing wall system is permitted.
    with pytest.raises(ValueError, match="Category D"):
        generate_building({**spec, "location": "rangpur", "siteClass": "SD"})


def test_a_pack_without_masonry_method_is_refused():
    from saengine.codes.tables import MasonryTable

    data = code_context.default_pack().table("masonry").model_dump(by_alias=True)
    data["method"] = "strengthDesign"
    with pytest.raises(ValueError):
        MasonryTable.model_validate(data)


def test_masonry_walls_take_the_allowable_stress_combinations(monkeypatch):
    # Sec 7.4.8.5 (p. 1021): the combinations of Sec 2.7; the ASD set of Sec 2.7.2.1.
    from saengine.design import wall_design, wall_forces

    seen: dict[str, list] = {}

    def forces(project, building, results, combinations, *args, **kwargs):
        seen["combos"] = combinations
        return {"piers": [{"wall": "W1", "pier": "W1/P1", "cuts": {}}]}

    cases = {"D": {}, "L": {}, "EX": {}, "EY": {}}
    monkeypatch.setattr(wall_forces, "case_shell_forces", lambda p, o: cases)
    monkeypatch.setattr(wall_forces, "wall_forces", forces)
    piers, lateral, notes = wall_design._masonry_forces({}, None, "out", {}, set())
    combos = seen["combos"]
    names = [c.name for c in combos]
    assert "D" in names and "D + L" in names
    assert all(not k.startswith("W") for c in combos for k in c.factors)  # no wind results
    assert any(n.startswith("masonry walls:") for n in notes)  # the wind rows left out
    assert lateral
    assert all(any(k.startswith("E") for k in c.factors) for c in combos if c.name in lateral)
    assert all("SD" not in c.factors for c in combos)  # SD has no results: zero
    assert piers == {"W1": [{"wall": "W1", "pier": "W1/P1", "cuts": {}}]}
