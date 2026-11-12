"""Masonry part 2 (B34): strength design of slender walls and shear walls, the earthquake and
high wind rules, embedded anchor bolts and confined masonry, pinned through the bnbc2020 pack
(Part 6 Chapter 7, Sec 7.3.9, 7.7-7.9, 7.11). Each test names the clause it pins."""

from __future__ import annotations

import itertools
import math

import pytest

from saengine.design import confined_masonry as C
from saengine.design import masonry as M
from saengine.design import masonry_anchors as AN
from saengine.design import masonry_seismic as S
from saengine.design import masonry_strength as SD
from saengine.design import walls as W
from saengine.design.rc import DesignError


def _forces(p, v, m3, m2=0.0, name="D + L", earthquake=True):
    return [
        W.PierForces(name, p, v, m3, 0.0, m2, earthquake, f"P1 {cut}")
        for cut in ("bottom", "middle", "top")
    ]


def _names(rows):
    return [r["name"] for r in rows]


# ───────────────────────────────────── the pack's choices ─────────────────────────────────────


def test_the_pack_permits_strength_design_in_lieu_of_allowable_stress():
    # Sec 7.4.2.1 (p. 1011): working stress design; slender and shear walls may use Sec 7.7.
    assert M.methods() == ["allowableStress", "strength"]
    assert M.method_id(None) == "allowableStress"
    assert M.method_id("strength") == "strength"
    assert M.method_module("strength") is SD
    assert M.combinations_kind("strength") == "strength"
    assert len(M.method_text(["strength", "confinedPanels"])) == 3


def test_a_pack_without_the_part_2_groups_does_not_cover_them(monkeypatch):
    t = M.table()
    bare = t.model_copy(update={"confined": None, "anchorBolts": None, "highWind": None})
    monkeypatch.setattr(M, "table", lambda: bare)
    assert not C.covered() and not AN.covered()
    g = W.WallGeometry(4000, 250, 3000, 3000)
    rows, _notes = S.detailing(g, None, M.Masonry(8.0, mortar="M2"), wind_kmh=260.0)
    assert rows == []


# ─────────────────────────────────────── anchor bolts ───────────────────────────────────────


def test_anchor_bolt_shear_eqs_6_7_15_6_7_16_and_table_6_7_5():
    # Sec 7.3.9.3 (pp. 1008-1009): Bv = 1070 (f'm Ab)^(1/4) N or 0.12 Ab fy, or Table 6.7.5.
    bolt = AN.AnchorBolt(16, 150, 300, None, 250)  # edge ≥ 12 db: no reduction
    ab = math.pi * 16**2 / 4
    bv, note = AN.allowable_shear(bolt, 10.0)
    masonry = 1070 * (10.0 * ab) ** 0.25
    steel = 0.12 * ab * 250
    assert bv == pytest.approx(min(masonry, steel, 5.9e3))
    assert "table" in note
    # Table rows are read at or below f'm: 11 MPa reads the 10 MPa row (22 mm: 8.5 kN).
    big = AN.AnchorBolt(22, 200, 400, None, 400)
    assert AN.allowable_shear(big, 11.0)[0] == pytest.approx(
        min(8.5e3, 1070 * (11 * math.pi * 121) ** 0.25)
    )
    # Edge distance below 12 db: the masonry value falls to zero at 40 mm.
    near = AN.AnchorBolt(16, 150, 40, None, 250)
    assert AN.edge_factor(near) == 0.0
    half = AN.AnchorBolt(16, 150, (12 * 16 + 40) / 2, None, 250)
    assert AN.edge_factor(half) == pytest.approx(0.5)
    # Spacing below 8 db: down to 0.75 at 4 db.
    assert AN.spacing_factor(AN.AnchorBolt(16, 150, 300, 4 * 16)) == pytest.approx(0.75)
    assert AN.spacing_factor(AN.AnchorBolt(16, 150, 300, 6 * 16)) == pytest.approx(0.875)


def test_anchor_bolt_tension_eqs_6_7_17_to_6_7_20_and_tables_6_7_6_6_7_7():
    # Sec 7.3.9.4 (pp. 1009-1010): Bt = 0.04 Ap √f'm or 0.2 Ab fy, Ap = π min(lb, lbe)².
    bolt = AN.AnchorBolt(16, 100, 150, None, 250)
    ap = math.pi * 100**2
    assert AN.projected_area(bolt) == pytest.approx(ap)
    bt, _note = AN.allowable_tension(bolt, 10.0)
    assert bt == pytest.approx(
        min(0.04 * ap * math.sqrt(10), 0.2 * math.pi * 64 * 250, 4.3e3, 9.8e3)
    )
    # Table 6.7.6 prints 6.7 kN at f'm 20 / 100 mm (out of line): the formula's 5.6 kN governs.
    bt20, _ = AN.allowable_tension(AN.AnchorBolt(20, 100, 200, None, 400), 20.0)
    assert bt20 == pytest.approx(0.04 * ap * math.sqrt(20))
    assert bt20 < 6.7e3
    # Overlapping projected areas lose 50 % of the overlap (a neighbour on each side).
    close = AN.AnchorBolt(16, 100, 150, 100, 250)
    assert AN.projected_area(close) < ap


def test_anchor_bolt_interaction_and_placement_sec_7_3_9_5_to_7_3_9_8():
    # Eq 6.7.21 bt/Bt + bv/Bv ≤ 1; lbe ≥ 40 mm; lb ≥ 4 db and 50 mm; spacing ≥ 4 db.
    bolt = AN.AnchorBolt(12, 40, 30, 40, 250)
    rows = AN.bolt_checks(bolt, 10.0, 1e3, 1e3)
    by = {r["name"].split(" (")[0]: r for r in rows}
    assert not by["Anchor bolt edge distance"]["ok"]
    assert not by["Anchor bolt embedment"]["ok"]  # 50 mm > 4 × 12
    assert by["Anchor bolt embedment"]["demand"] == 50.0
    assert not by["Anchor bolt spacing"]["ok"]  # 48 mm
    assert any(n.startswith("Anchor bolt bt/Bt + bv/Bv ≤ 1") for n in by)


def test_wall_anchorage_by_the_bolts():
    from saengine.library.objects import MasonryAnchorBolts

    bolts = MasonryAnchorBolts(dia=16, embedment=150, edge=100, spacing=600, placement="face")
    rows = AN.wall_anchorage_checks(bolts, 10.0, 5.0)  # 5 kN/m × 0.6 m = 3 kN per bolt
    tension = next(r for r in rows if r["name"].startswith("Anchor bolt tension"))
    assert tension["demand"] == pytest.approx(3.0)
    top = bolts.model_copy(update={"placement": "top"})
    shear = next(
        r
        for r in AN.wall_anchorage_checks(top, 10.0, 5.0)
        if r["name"].startswith("Anchor bolt shear")
    )
    assert shear["demand"] == pytest.approx(3.0)


# ─────────────────────────────────────── strength design ───────────────────────────────────────


def test_strength_values_tables_6_7_13_6_7_14():
    # Table 6.7.13 (p. 1033): fr; solid partly grouted not allowed.
    assert SD.modulus_of_rupture(M.Masonry(16.0, units="hollow", grouting="full")) == pytest.approx(
        min(0.33 * 4, 1.2)
    )
    partial = M.Masonry(16.0, units="hollow", grouting="partial")
    assert SD.modulus_of_rupture(partial) == pytest.approx(min(0.21 * 4, 0.65))
    with pytest.raises(DesignError):
        SD.modulus_of_rupture(M.Masonry(16.0, units="solid", grouting="partial"))
    # Eqs 6.7.48a-b: Cd 2.4 at M/Vd ≤ 0.25, 1.2 at ≥ 1.0, straight line between.
    assert SD.shear_coefficient(0.1) == 2.4
    assert SD.shear_coefficient(1.5) == 1.2
    assert SD.shear_coefficient(0.625) == pytest.approx(1.8)
    # Table 6.7.14 (read as 6 and 4 √psi in SI): 0.498 and 0.332 √f'm.
    assert SD.shear_maximum(0.0) == pytest.approx(0.498)
    assert SD.shear_maximum(2.0) == pytest.approx(0.332)


def test_slender_wall_moment_strength_eq_6_7_38():
    # Sec 7.7.1.2(c): Mn = Ase fy (d - a/2), Ase = (As fy + Pu)/fy, a = (As fy + Pu)/(0.85 f'm b).
    mn, a, ase = SD.slender_moment_strength(500.0, 100e3, 1000.0, 100.0, 10.0, 420.0)
    total = 500 * 420 + 100e3
    assert a == pytest.approx(total / (0.85 * 10 * 1000))
    assert ase == pytest.approx(total / 420)
    assert mn == pytest.approx(total * (100 - a / 2))
    # ρb with εmu 0.003 and the 0.85 / 0.85 block.
    assert SD.balanced_ratio(10, 420, 2e5) == pytest.approx(
        0.85 * 10 * 0.85 * 0.003 / (0.003 + 0.0021) / 420
    )


def test_axial_phi_increase_sec_7_7_2_2():
    # φ 0.65, to 0.85 as Pu falls from min(0.10 f'm Ae, 0.25 Pb) to zero when fy < 410 MPa.
    assert SD.axial_phi(0.0, 10, 1e6, 1e9, 400) == pytest.approx(0.85)
    assert SD.axial_phi(0.5e6, 10, 1e6, 1e9, 400) == pytest.approx(0.75)
    assert SD.axial_phi(0.0, 10, 1e6, 1e9, 420) == 0.65


def test_strength_wall_checks():
    g = W.WallGeometry(4000, 200, 3000, 3000)
    bars = W.WallBars(20, 16, 600, 12, 400, 1)
    m = M.Masonry(12.0, units="hollow", grouting="full", mortar="M1", inspected=True)
    d = M.masonry_wall_checks(g, bars, _forces(300e3, 200e3, 400e6, 5e6), m, method="strength")
    names = _names(d.checks)
    for start in (
        "Slender wall Pu/Ag",
        "Slender wall Mu ≤ φ Mn",
        "Slender wall ρ",
        "Shear wall Pu ≤ φ 0.8 Po",
        "Shear wall Mu ≤ φ Mn",
        "Shear wall Vu ≤ φ Vn",
        "Shear wall ρh + ρv",
    ):
        assert any(n.startswith(start) for n in names), start
    assert all(c["ok"] for c in d.checks if not c["flag"])
    # Solid units: the in-plane strength design is for hollow units only (Sec 7.7.2).
    solid = M.Masonry(12.0, units="solid", grouting="full", mortar="M1")
    d = M.masonry_wall_checks(g, bars, _forces(300e3, 50e3, 40e6, 5e6), solid, method="strength")
    assert not any(n.startswith("Shear wall Vu") for n in _names(d.checks))
    assert any("hollow-unit" in n for n in d.notes)
    # A high axial stress is outside the slender wall method (Eq 6.7.36).
    d = M.masonry_wall_checks(g, bars, _forces(2000e3, 50e3, 40e6, 5e6), m, method="strength")
    row = next(c for c in d.checks if c["name"].startswith("Slender wall Pu/Ag"))
    assert not row["ok"]
    # Plain masonry cannot be designed by strength.
    with pytest.raises(DesignError):
        M.masonry_wall_checks(g, None, _forces(300e3, 50e3, 40e6), m, method="strength")


# ───────────────────────────────────── earthquake and wind ─────────────────────────────────────


def test_zone_4_shear_force_factor_sec_7_8_5_5():
    g = W.WallGeometry(4000, 250, 3000, 3000)
    m = M.Masonry(8.0, mortar="M2", inspected=True)
    quake = _forces(500e3, 500e3, 100e6, name="D + 0.7EX")
    d2 = M.masonry_wall_checks(g, None, quake, m, zone=2)
    d4 = M.masonry_wall_checks(g, None, quake, m, zone=4)
    v2 = next(c for c in d2.checks if c["name"].startswith("In-plane shear"))
    v4 = next(c for c in d4.checks if c["name"].startswith("In-plane shear"))
    assert v4["demand"] == pytest.approx(1.5 * v2["demand"], rel=1e-2)
    assert any("× 1.5" in n for n in d4.notes)


def test_corner_bars_table_6_7_17_and_bands_table_6_7_16():
    # Table 6.7.17 (p. 1042), deformed bars, from the top storey down.
    assert S.corner_bar(4, 4, 0, 250) == 10.0
    assert S.corner_bar(4, 4, 3, 250) == 20.0
    assert S.corner_bar(2, 4, 3, 250) == 12.0
    assert S.corner_bar(3, 2, 1, 250) is None  # nil in Zones 2 and 3
    assert S.corner_bar(4, 4, 3, 250, deformed=False) == 25.0
    # Thicker than one and a half bricks: the area in proportion.
    assert S.corner_bar(4, 1, 0, 500) == pytest.approx(10 * math.sqrt(500 / 375))
    # Table 6.7.16 (p. 1041).
    assert S.band_bars(2).deformed == (2, 10.0)
    assert S.band_bars(4).plain == (2, 16.0)
    # Table 6.7.15 (pp. 1040-1041).
    assert S.strengthening_row(1, 4).items == ["mortar"]
    assert "jambBars" not in S.strengthening_row(3, 2).items
    assert "jambBars" in S.strengthening_row(3, 3).items
    assert S.strengthening_row(4, 5) is None


def test_seismic_rows_of_plain_and_reinforced_walls():
    g = W.WallGeometry(4000, 250, 3000, 3000)
    plain = M.Masonry(8.0, mortar="M4", unit_strength=10.0)
    rows, _notes = S.detailing(g, None, plain, zone=3, storeys=3, storey_from_top=2)
    by = {r["name"].split(" (")[0]: r for r in rows}
    assert not by["Mortar not leaner than M3"]["ok"]  # Sec 7.8.3(b)
    assert not by["Unit strength ≥ 12 MPa"]["ok"]  # Sec 7.8.3(a)
    assert by["Lintel and roof bands"]["flag"]
    assert "12 mm deformed" in by["Vertical bars at corners and junctions"]["note"]
    # Zone 4 reinforced: ρh + ρv ≥ 0.002 (Sec 7.8.5.1), walls ≥ 150 mm (7.8.5.4).
    light = W.WallBars(20, 12, 1200, 12, 3000, 1)
    rows, _ = S.detailing(
        W.WallGeometry(4000, 125, 3000, 3000), light, M.Masonry(10.0, mortar="M2"), zone=4
    )
    by = {r["name"].split(" (")[0]: r for r in rows}
    assert not by["ρh + ρv ≥ 0.002"]["ok"]
    assert not by["Reinforced bearing wall thickness"]["ok"]
    # Openings over half the wall need their jambs strengthened (Sec 7.8.6.1(b), (f)).
    rows, _ = S.detailing(g, None, plain, zone=2, storeys=1, opening_share=0.6)
    assert any(r["name"].startswith("Openings ≤ 50%") and r["flag"] for r in rows)
    # Outside the zones only the Table 6.7.15 mortar applies (Zone 1).
    rows, _ = S.detailing(g, None, plain, zone=1, storeys=2)
    assert _names(rows) == [n for n in _names(rows) if n.startswith("Mortar")]


def test_high_wind_rules_sec_7_9_and_table_6_7_18():
    g = W.WallGeometry(4000, 200, 3600, 3600)
    m = M.Masonry(8.0, mortar="M3", unit_strength=12.0)
    assert S.wind_rows(g, None, m, 190.0, True, []) == []  # ≤ 200 km/h
    rows = S.wind_rows(g, None, m, 230.0, True, [])
    by = {r["name"].split(" (")[0]: r for r in rows}
    assert not by["Brick strength ≥ 15 MPa"]["ok"]
    assert not by["Mortar M1 or M2"]["ok"]
    assert by["Wall thickness, high wind"]["demand"] == 200.0  # unreinforced solid
    assert not by["Unsupported height ≤ 3500 mm"]["ok"]
    grouted = M.Masonry(8.0, mortar="M1", grouting="full")
    rows = S.wind_rows(g, None, grouted, 230.0, True, [])
    assert next(r for r in rows if r["name"].startswith("Wall thickness"))["demand"] == 250.0


# ─────────────────────────────────────── confined masonry ───────────────────────────────────────


def _confinement() -> C.Confinement:
    element = C.Element(200, 200, 4, 12, 6, 150, 100)
    return C.Confinement(element, C.Element(200, 200, 4, 12, 6, 150), 20.0, 420.0)


def test_tie_column_placement_sec_7_11_8_3():
    # Ends, both sides of openings over 1.5 m², within the wall at ≤ 5 m.
    cols = C.tie_column_positions(9000, [(3000, 4500, 1.5 * 2.1)], 200)
    assert cols[0] == 100 and cols[-1] == 8900
    assert 2900 in cols and 4600 in cols
    assert max(b - a for a, b in itertools.pairwise(cols)) <= 5000
    # A small opening gets none beside it, and none inside it.
    cols = C.tie_column_positions(9000, [(4000, 4600, 0.36)], 200)
    assert all(not (3900 < x < 4700) for x in cols)
    assert max(b - a for a, b in itertools.pairwise(cols)) <= 5000 + 600


def test_confined_panel_checks_sec_7_11_5():
    g = W.WallGeometry(3000, 200, 3000, 3000)
    m = M.Masonry(8.0, mortar="M2")
    conf = _confinement()
    d = C.panel_checks(g, _forces(200e3, 30e3, 150e6, 2e6), m, conf, [100.0, 2900.0])
    shear = next(c for c in d.checks if c["name"].startswith("In-plane shear"))
    # Masonry Fv over the length less the tie columns + vc = 0.091 √f'c (App J.1.9) on them.
    fv = 0.5 * min(0.025 * math.sqrt(8.0), 0.40)
    depth = 200 - (25 + 6 + 6)
    expected = fv * 200 * (3000 - 400) + 0.091 * math.sqrt(20.0) * 2 * 200 * depth
    assert shear["capacity"] == pytest.approx(expected / 1e3, abs=0.01)
    names = _names(d.checks)
    for start in ("Confined wall thickness", "Confined wall h/t", "Tie column spacing",
                  "Tie beam spacing", "In-plane fb ≤ Fb", "Tie column bars fs"):  # fmt: skip
        assert any(n.startswith(start) for n in names), start


def test_confining_elements_sec_7_11_8_5_to_7_11_8_7():
    small = C.Element(100, 140, 2, 10, 6, 250, 200)
    conf = C.Confinement(small, small, 20.0, 420.0)
    rows = {r["name"].split(" (")[0]: r for r in C.element_rows(conf)}
    assert not rows["Tie column area"]["ok"]  # 0.014 m² < 0.02 m²
    assert not rows["Tie column depth in the wall's plane"]["ok"]  # < 150 mm
    assert not rows["Tie column bars"]["ok"]  # 157 mm² < 300 mm²
    assert not rows["Tie column tie spacing"]["ok"]  # > 200 mm
    assert rows["Tie column end-zone ties"]["flag"]  # 100 mm recommended
    assert all(r["ok"] for r in C.element_rows(_confinement()) if not r["flag"])


def test_wall_density_and_storeys_sec_7_11_7():
    walls = [
        {"start": (0, 0), "end": (10000, 0), "thickness": 250, "confined": True, "lowest": True},
        {
            "start": (0, 8000),
            "end": (10000, 8000),
            "thickness": 250,
            "confined": True,
            "lowest": True,
        },
        {"start": (0, 0), "end": (0, 8000), "thickness": 250, "confined": True, "lowest": True},
        {
            "start": (10000, 0),
            "end": (10000, 8000),
            "thickness": 250,
            "confined": True,
            "lowest": True,
        },
    ]
    floor = 10000 * 8000.0
    rows = {r["name"].split(" (")[0]: r for r in C.building_rows(walls, floor, 3, 1, (10000, 8000))}
    # X: 2 × 10 m × 0.25 m = 5 m² over 80 m² = 6.25 % ≥ 4 % (Zone 3).
    assert rows["Wall density in X ≥ 4%"]["ok"]
    assert rows["Wall density in Y ≥ 4%"]["capacity"] == pytest.approx(4.0 / 80.0, abs=1e-3)
    assert rows["Storeys of confined masonry"]["capacity"] == 3.0
    rows = {r["name"].split(" (")[0]: r for r in C.building_rows(walls, 3 * floor, 4, 3)}
    assert not rows["Storeys of confined masonry"]["ok"]  # Zone 4: 2 storeys
    assert not rows["Wall density in X ≥ 5%"]["ok"]


def test_wall_type_takes_confinement_and_anchor_bolts():
    from saengine.library.defaults import default_material_library
    from saengine.library.objects import ObjectLibrary

    lib = ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "kind": "wall",
                    "id": "CW",
                    "name": "Confined wall",
                    "material": "BRICK-1",
                    "thickness": 250,
                    "masonryMethod": "allowableStress",
                    "confinement": {"concrete": "NOPE", "rebar": "NOPE"},
                    "anchorBolts": {"dia": 16},
                }
            ]
        }
    )
    problems = lib.check_materials(default_material_library())
    assert any("confinement material 'NOPE'" in p for p in problems)


def test_masonry_template_confines_plain_walls():
    from saengine.library.generator import generate_building

    spec = {
        "gridsX": [4000, 4000],
        "gridsY": [3500, 3500],
        "storyCount": 2,
        "system": "masonry",
        "location": "barishal",
        "siteClass": "SB",
    }
    result = generate_building(spec)
    walls = [o for o in result["objects"]["objects"] if o["kind"] == "wall"]
    zone = result["summary"]["zone"]
    row = next(z for z in M.table().confined.zones if int(zone) in z.zones)
    assert result["summary"]["masonry"]["confined"] == (2 <= row.storeys)
    if result["summary"]["masonry"]["confined"]:
        assert all(o["confinement"]["tieColumn"]["depth"] >= 150 for o in walls)


def test_confined_wall_detail_is_drawn():
    from saengine.drawings.sheets import DrawingSettings, build_sheets
    from saengine.drawings.sheets.model import DrawingSet, WallDetail

    wall = WallDetail(
        "W1",
        ["W1"],
        6000,
        3000,
        250,
        25,
        openings=[(2000, 900, 1500, 1200)],
        tie_columns=[100.0, 1900.0, 3600.0, 5900.0],
        tie_depth=200.0,
        tie_beam_depth=200.0,
        tie_text="4Ø12, TIES Ø6@150 (100 AT THE ENDS)",
        tie_beam_text="4Ø12, TIES Ø6@150",
    )
    texts = [
        e.dxf.text
        for sheet in build_sheets(DrawingSet(walls=[wall]), DrawingSettings())
        for e in sheet.msp.query("TEXT")
    ]
    assert any("TIE COLUMN" in t for t in texts)
    assert any("TIE BEAM" in t for t in texts)
