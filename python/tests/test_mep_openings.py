"""Structural checks of MEP sleeves and openings in beams, slabs and walls (hand calculations)."""

from __future__ import annotations

import math

import pytest

from saengine.library.bim import WallElement
from saengine.library.mep import Opening
from saengine.mep.openings import (
    BeamSection,
    ColumnAt,
    SlabInfo,
    beam_opening_checks,
    ineffective_perimeter,
    net_shear,
    opening_polygon,
    slab_opening_checks,
    wall_opening_checks,
)

# 300 x 500 beam, 6 m between column centres (400 wide along it), cover 40 to Ø10 stirrups
# (2 legs @ 150), 3 Ø16 top, 4 Ø16 bottom: d = 500 - 40 - 10 - 8 = 442 mm; f'c 25, fy 420.
AS_BOTTOM = 4 * math.pi * 16**2 / 4
BEAM = BeamSection(
    id="B1",
    length=6000,
    h=500,
    b=300,
    cover=40,
    stirrup_dia=10,
    legs=2,
    spacing=150,
    fc=25,
    fy=420,
    as_top=3 * math.pi * 16**2 / 4,
    as_bottom=AS_BOTTOM,
    top_dia=16,
    bottom_dia=16,
    d=442,
    d_top=442,
    start_face=200,
    end_face=200,
    phi_mn={False: 125e6, True: 95e6},
)


def sleeve(identifier: str = "OP1", distance: float = 3000, diameter: float = 150, **kw):
    return Opening.model_validate(
        {
            "id": identifier,
            "host": "B1",
            "kind": kw.get("kind", "sleeve"),
            "shape": "circle",
            "diameter": diameter,
            "position": {"distance": distance, "elevation": kw.get("elevation", 250)},
        }
    )


def by_name(checks):
    return {c["name"]: c for c in checks}


def test_net_section_shear_by_hand() -> None:
    # dn = 442 - 150 = 292; Av = 2 x 78.54 = 157.1 >= Av,min = 0.35 x 300 x 150 / 420 = 37.5
    # Vc = 0.17 x 5 x 300 x 292 = 74.46 kN; Vs = 157.1 x 420 x 292 / 150 = 128.43 kN
    # φVn = 0.75 (74.46 + 128.43) = 152.17 kN
    shear = net_shear(BEAM, 150)
    av = 2 * math.pi * 10**2 / 4
    vc = 0.17 * 5 * 300 * 292
    vs = av * 420 * 292 / 150
    assert shear["dn"] == 292
    assert shear["vc"] == pytest.approx(vc)
    assert shear["vs"] == pytest.approx(vs)
    assert shear["phi_vn"] == pytest.approx(0.75 * (vc + vs))


def test_sleeve_at_midspan() -> None:
    demands = [("1.2D + 1.6L", -120e3, -80e6), ("0.9D + 1.0EX", 40e3, 20e6)]
    checks, notes = beam_opening_checks(sleeve(), BEAM, demands)
    c = by_name(checks)
    size = c["Sleeve size (h/3, SAEngine practice limit)"]
    assert (size["demand"], size["capacity"]) == (150, pytest.approx(166.67, abs=0.01))
    assert size["ok"]
    # Clear of the faces: min(3000 - 75 - 200, 6000 - 200 - 3000 - 75) = 2725 mm >= h.
    face = c["Clear distance from the support face (h)"]
    assert face["capacity"] == 2725 and face["utilisation"] == pytest.approx(500 / 2725, abs=1e-3)
    # Above: 500 - (250 + 75) = 175 >= 40 + 10 + 16 = 66; below: 250 - 75 = 175.
    assert c["Concrete above the opening"]["capacity"] == 175
    assert c["Concrete above the opening"]["demand"] == 66
    assert c["Concrete below the opening"]["capacity"] == 175
    # Sagging 80 kN·m: a = 804.2 x 420 / (0.85 x 25 x 300) = 52.98 mm above the opening.
    zone = c["Compression zone above the opening (sagging)"]
    assert zone["demand"] == pytest.approx(AS_BOTTOM * 420 / (0.85 * 25 * 300), abs=0.01)
    assert zone["combination"] == "1.2D + 1.6L"
    assert c["Flexure at the opening (sagging)"]["utilisation"] == pytest.approx(80 / 125, abs=1e-3)
    assert c["Flexure at the opening (hogging)"]["utilisation"] == pytest.approx(20 / 95, abs=1e-3)
    shear = c["Shear at the opening (net section)"]
    assert shear["demand"] == 120
    assert shear["capacity"] == pytest.approx(net_shear(BEAM, 150)["phi_vn"] / 1e3, abs=0.01)
    assert all(check["ok"] for check in checks)
    assert not notes


def test_sleeve_rules_that_fail() -> None:
    near = by_name(beam_opening_checks(sleeve(distance=400), BEAM)[0])
    # 400 - 75 - 200 = 125 mm from the face, less than h = 500.
    assert near["Clear distance from the support face (h)"]["capacity"] == 125
    assert not near["Clear distance from the support face (h)"]["ok"]

    big = by_name(beam_opening_checks(sleeve(diameter=200), BEAM)[0])
    assert not big["Sleeve size (h/3, SAEngine practice limit)"]["ok"]

    high = by_name(beam_opening_checks(sleeve(elevation=400), BEAM)[0])
    # 500 - (400 + 75) = 25 mm above: cuts the top bars.
    assert high["Concrete above the opening"]["capacity"] == 25
    assert not high["Concrete above the opening"]["ok"]

    pair = [sleeve("OP1", 3000), sleeve("OP2", 3300)]
    spaced = by_name(beam_opening_checks(pair[0], BEAM, None, pair)[0])
    gap = spaced["Spacing to OP2 (3 diameters, SAEngine practice limit)"]
    assert (gap["demand"], gap["capacity"], gap["ok"]) == (450, 300, False)


def test_large_opening_needs_detailed_design() -> None:
    opening = Opening.model_validate(
        {
            "id": "OP3",
            "host": "B1",
            "kind": "opening",
            "shape": "rectangle",
            "width": 600,
            "height": 200,
            "position": {"distance": 3000, "elevation": 250},
        }
    )
    checks, notes = beam_opening_checks(opening, BEAM, [("U1", 100e3, 0.0)])
    c = by_name(checks)
    assert not c["Opening depth for the net-section method (h/3)"]["ok"]
    assert not c["Opening length for the net-section method (d)"]["ok"]
    assert "Shear at the opening (net section)" not in c
    assert any("Vierendeel" in note for note in notes)


# Flat slab 12 x 12 m, columns 500 x 500 on a 6 m grid, h = 200, d = 160, f'c = 25.
COLUMNS = [
    ColumnAt(f"C{i}{j}", (6000.0 * i, 6000.0 * j), 500, 500) for i in range(3) for j in range(3)
]
FLAT = SlabInfo(
    id="S1",
    boundary=[[0, 0], [12000, 0], [12000, 12000], [0, 12000]],
    h=200,
    d=160,
    fc=25,
    flat=True,
    bars_x=2 * math.pi * 12**2 / 4 / 200,
    bars_y=2 * math.pi * 12**2 / 4 / 200,
)


def slab_opening(x: float, y: float, size: float = 300) -> Opening:
    return Opening.model_validate(
        {
            "id": "OP1",
            "host": "S1",
            "kind": "opening",
            "shape": "rectangle",
            "width": size,
            "height": size,
            "position": {"x": x, "y": y},
        }
    )


def test_column_strips_cross() -> None:
    # (6000, 7000): within 0.25 x 6000 = 1500 of the column lines x = 6000 and y = 6000, where
    # the column strips (3000 wide) cross: at most 3000 / 8 = 375 mm cut each way.
    checks, notes = slab_opening_checks(slab_opening(6000, 7000), FLAT, COLUMNS)
    c = by_name(checks)
    for bars in ("X", "Y"):
        rule = c[f"{bars} bars cut where column strips cross (BNBC 6.5.4.2.2: 1/8)"]
        assert (rule["demand"], rule["capacity"]) == (300, 375)
        assert rule["ok"] and not rule["flag"]
    assert any("mm² of X bars" in n for n in notes)
    wide = by_name(slab_opening_checks(slab_opening(6000, 7000, 400), FLAT, COLUMNS)[0])
    assert not wide["X bars cut where column strips cross (BNBC 6.5.4.2.2: 1/8)"]["ok"]


def test_column_and_middle_strip() -> None:
    # (6000, 9000): X bars in the middle strip (3000 wide), Y bars in the column strip
    # (3000 wide): a quarter of either, 750 mm.
    checks, _ = slab_opening_checks(slab_opening(6000, 9000, 700), FLAT, COLUMNS)
    c = by_name(checks)
    assert c["X bars cut in the middle strip (BNBC 6.5.4.2.3: 1/4)"]["capacity"] == 750
    assert c["Y bars cut in the column strip (BNBC 6.5.4.2.3: 1/4)"]["capacity"] == 750
    assert all(check["ok"] for check in checks)


def test_middle_strips_any_size() -> None:
    checks, notes = slab_opening_checks(slab_opening(3000, 3000, 1500), FLAT, COLUMNS)
    assert not [c for c in checks if "strip" in c["name"]]
    assert any("BNBC 6.5.4.2.1" in n for n in notes)


def test_strips_by_the_extent_of_the_opening() -> None:
    # Centred at (3000, 3000), where two middle strips cross, but 5000 mm square: 500..5500 in
    # x and y. The column strips are 1500 mm either side of the lines 0 and 6000 (clipped to
    # 0..1500 at the slab edge, 1500 wide; 4500..7500 inside, 3000 wide). Its corner parts lie
    # where column strips cross: 500..1500 (1000 mm of the 1500 mm edge strip, limit 1500 / 8 =
    # 187.5) and 4500..5500 (1000 mm of 3000, limit 375); it governs the edge strip. Where it
    # crosses a column strip from a middle strip: the 3000 mm middle strip 1500..4500 is cut
    # over its full 3000 mm width (limit 750); the column strips over 1000 mm (limit 375 for the
    # edge strip of 1500).
    checks, notes = slab_opening_checks(slab_opening(3000, 3000, 5000), FLAT, COLUMNS)
    c = by_name(checks)
    for bars in ("X", "Y"):
        cross = c[f"{bars} bars cut where column strips cross (BNBC 6.5.4.2.2: 1/8)"]
        assert (cross["demand"], cross["capacity"], cross["ok"]) == (1000, 187.5, False)
        column = c[f"{bars} bars cut in the column strip (BNBC 6.5.4.2.3: 1/4)"]
        assert (column["demand"], column["capacity"]) == (1000, 375)
        middle = c[f"{bars} bars cut in the middle strip (BNBC 6.5.4.2.3: 1/4)"]
        assert (middle["demand"], middle["capacity"]) == (3000, 750)
    assert any("the part where two middle strips cross" in n for n in notes)
    # 2800 mm square at the same centre (1600..4400) stays in the middle strips.
    checks, notes = slab_opening_checks(slab_opening(3000, 3000, 2800), FLAT, COLUMNS)
    assert not [c for c in checks if "strip" in c["name"]]
    assert any(n.startswith("OP1: where two middle strips cross") for n in notes)


def test_punching_in_a_column_strip_beyond_10h() -> None:
    # (3000, 6600): 2600 mm from the faces of C01 and C11 (more than 10 h = 2000) but inside
    # the column strip of the line y = 6000 (5250..7500 holds 6450..6750): BNBC 6.4.10.6 asks
    # for the modified perimeter at those columns in a flat slab, not at C00 or C10.
    checks, _ = slab_opening_checks(slab_opening(3000, 6600), FLAT, COLUMNS)
    names = {c["name"] for c in checks if "perimeter" in c["name"]}
    assert names == {
        "Critical perimeter at C01 (BNBC 6.4.10.6.1)",
        "Critical perimeter at C11 (BNBC 6.4.10.6.1)",
    }
    assert all("in a column strip" in c["note"] for c in checks if "perimeter" in c["name"])
    # With beams the strip clause does not apply, and the opening is beyond 10 h.
    beams = SlabInfo(**{**FLAT.__dict__, "flat": False})
    checks, _ = slab_opening_checks(slab_opening(3000, 6600), beams, COLUMNS)
    assert not [c for c in checks if "perimeter" in c["name"]]


def test_strip_rules_are_a_guide_with_beams() -> None:
    beams = SlabInfo(**{**FLAT.__dict__, "flat": False})
    checks, _ = slab_opening_checks(slab_opening(6000, 7000, 400), beams, COLUMNS)
    rule = by_name(checks)["X bars cut where column strips cross (BNBC 6.5.4.2.2: 1/8)"]
    assert rule["flag"] and not rule["ok"]


def test_punching_perimeter_by_hand() -> None:
    # Column at (6000, 6000), d = 160: the critical section is a 660 mm square (b0 = 2640).
    # The 300 x 300 opening at (6000, 7000) is 6850 - 6250 = 600 mm from the face, less than
    # 10 h = 2000. Tangents from the centroid to its near corners (±150, 850) cut the side at
    # v = 330 at u = ±330 x 150 / 850: 116.5 mm of b0 is ineffective.
    column = COLUMNS[4]
    assert column.centre == (6000.0, 6000.0)
    hole = opening_polygon(slab_opening(6000, 7000), 6000, 7000)
    b0, lost = ineffective_perimeter(column, 160, FLAT.boundary, hole)
    assert b0 == pytest.approx(2640)
    assert lost == pytest.approx(2 * 330 * 150 / 850)

    # With 600 kN delivered to the column: vc = min(0.33, 0.17 x 3, 0.083 (2 + 40 x 160 / b0))
    # x √25 on b0 = 2523.5 mm (λs = 1 for d = 160): 1.65 MPa; φVc = 0.75 x 1.65 x 2523.5 x 160.
    def shear(column_id: str):
        return [("U1", 600e3)] if column_id == "C11" else None

    checks, _ = slab_opening_checks(slab_opening(6000, 7000), FLAT, COLUMNS, (), shear)
    punching = by_name(checks)["Punching at C11 with the opening (BNBC 6.4.10.6.1)"]
    effective = 2640 - 2 * 330 * 150 / 850
    capacity = 0.75 * 0.33 * 5 * effective * 160
    assert punching["capacity"] == pytest.approx(capacity / 1e3, abs=0.01)
    assert punching["utilisation"] == pytest.approx(600e3 / capacity, abs=1e-3)
    assert not punching["ok"]
    # Without results the reduced perimeter is reported only.
    flagged = by_name(slab_opening_checks(slab_opening(6000, 7000), FLAT, COLUMNS)[0])
    assert flagged["Critical perimeter at C11 (BNBC 6.4.10.6.1)"]["flag"]


def test_far_opening_and_framed_columns() -> None:
    checks, _ = slab_opening_checks(slab_opening(3000, 3000), FLAT, COLUMNS)
    assert not [c for c in checks if "Punching" in c["name"] or "perimeter" in c["name"]]
    framed = [ColumnAt(c.id, c.centre, c.c1, c.c2, beams=True) for c in COLUMNS]
    checks, notes = slab_opening_checks(slab_opening(6000, 7000), FLAT, framed)
    assert not [c for c in checks if "perimeter" in c["name"]]
    assert any("beams framing in" in n for n in notes)


def test_opening_past_the_slab_edge() -> None:
    checks, _ = slab_opening_checks(slab_opening(11950, 3000), FLAT, COLUMNS)
    edge = by_name(checks)["Opening inside the slab"]
    assert edge["demand"] > 0 and not edge["ok"]


def test_wall_openings() -> None:
    wall = WallElement(id="W1", type="W200", start=[0, 0], end=[5000, 0], bottom=0, top=3000)
    opening = Opening.model_validate(
        {
            "id": "OPW",
            "host": "W1",
            "kind": "opening",
            "shape": "rectangle",
            "width": 1000,
            "height": 1000,
            "position": {"x": 2500, "y": 1500},
        }
    )
    checks, notes = wall_opening_checks(opening, wall, 200)
    c = by_name(checks)
    assert c["Opening inside the wall"]["ok"]
    removed = c["Wall length removed at the opening"]
    assert removed["utilisation"] == pytest.approx(0.2) and removed["flag"]
    assert any("BNBC 6.6.3.7" in n for n in notes)
    past = opening.model_copy(update={"position": opening.position.model_copy(update={"x": 4800})})
    assert not by_name(wall_opening_checks(past, wall, 200)[0])["Opening inside the wall"]["ok"]
