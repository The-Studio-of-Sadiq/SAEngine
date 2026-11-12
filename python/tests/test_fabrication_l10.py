"""Alpha 9 L10: steel fabrication (DSTV NC files, shop drawing helpers, marks) and rebar CNC
(BVBS records). The expected texts are written out by hand from the formats:

- DSTV "Standard description for steel structure pieces for the numerical controls", 7th
  edition (July 1998): ST header lines (order, drawing, phase, piece, grade, quantity, profile,
  code, length, height, flange width, flange and web thickness, radius, kg/m, m²/m, four cuts,
  four texts), BO hole lines (face, x, reference, y, diameter), SI, EN;
- BVBS guideline "Data exchange of reinforcement data" (version 3.1, its BF2D examples 1-3 and
  the checksum example "abcde@C" = 78; the layout of version 2.0).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from saengine.fabrication import bvbs, dstv
from saengine.fabrication.model import (
    Assembly,
    Attached,
    Cope,
    FabricationModel,
    FabricationOptions,
    Hole,
    Part,
    Weld,
    mark,
)

# ─────────────────────────────────── DSTV NC1 ───────────────────────────────────


def _ipe200(length: float = 4000.0) -> Part:
    return Part(
        kind="profile",
        role="main",
        name="IPE 200",
        profile="IPE200",
        code="I",
        grade="S275",
        length=length,
        h=200.0,
        b=100.0,
        tw=5.6,
        tf=8.5,
        r=12.0,
        mass_per_m=22.4,
        paint_per_m=0.768,
        holes=[
            Hole("v", 50.0, 135.0, 22.0),
            Hole("v", 50.0, 65.0, 22.0),
            Hole("v", 50.0, 65.0, 22.0, from_end=True),
            Hole("v", 50.0, 135.0, 22.0, from_end=True),
        ],
        mark="p1",
        shape="I",
    )


def test_nc1_of_an_ipe_beam_with_holes():
    part = _ipe200()
    part.finish()
    text = dstv.nc1(part, 4, dstv.NcHeader(order="1001", drawing="B1", phase="1"))
    expected = "\n".join(EXPECTED_NC1)
    assert text == expected + "\n"


EXPECTED_NC1 = (
    "ST",
    "** SAEngine",
    "  1001",
    "  B1",
    "  1",
    "  p1",
    "  S275",
    "  4",
    "  IPE200",
    "  I",
    "     4000.00",
    "      200.00",
    "      100.00",
    "        8.50",
    "        5.60",
    "       12.00",
    "      22.400",
    "       0.768",
    "       0.000",
    "       0.000",
    "       0.000",
    "       0.000",
    "  main",
    "  ",
    "  ",
    "  ",
    "BO",
    "  v     50.00u     65.00     22.00",
    "  v     50.00o    135.00     22.00",
    "  v   3950.00u     65.00     22.00",
    "  v   3950.00o    135.00     22.00",
    "SI",
    "  v   2000.00o    100.00      0.00    10 p1",
    "EN",
)


def test_nc1_plate_has_its_outline_closed_counter_clockwise():
    plate = Part(
        kind="plate",
        role="fin plate",
        name="PL 10x95",
        profile="PL10*95",
        code="B",
        grade="S275",
        length=210.0,
        h=95.0,
        tw=10.0,
        holes=[Hole("v", 35.0, 60.0, 22.0), Hole("v", 105.0, 60.0, 22.0)],
        mark="p7",
    )
    plate.finish()
    lines = dstv.nc1(plate, 2, dstv.NcHeader(order="1", drawing="B1", marking=False)).splitlines()
    # a plate: its width as the height, its thickness as the thicknesses, kg/m² and m²/m²
    assert lines[9:15] == [
        "  B",
        "      210.00",
        "       95.00",
        "       10.00",
        "       10.00",
        "       10.00",
    ]
    assert lines[16] == "      78.500"  # 10 mm x 7850 kg/m³
    ak = lines.index("AK")
    assert lines[ak + 1 : ak + 6] == [
        "  v      0.00u      0.00      0.00",
        "  v    210.00u      0.00      0.00",
        "  v    210.00u     95.00      0.00",
        "  v      0.00u     95.00      0.00",
        "  v      0.00u      0.00      0.00",
    ]
    assert "SI" not in lines  # marking off
    assert lines[-1] == "EN"


def test_nc1_coped_beam_contours_its_web_and_flange():
    part = _ipe200(3000.0)
    part.holes = []
    part.copes = [Cope("start", "top", 60.0, 30.0)]
    part.finish()
    lines = dstv.nc1(part, 1).splitlines()
    first = lines.index("AK")
    web = lines[first + 1 : first + 8]  # six corners and the first again
    assert web[0] == "  v      0.00u      0.00      0.00"
    assert "  v     60.00u    170.00      0.00" in web  # the cope's inner corner
    assert web[-1] == web[0]  # closed
    second = lines.index("AK", first + 1)
    assert lines[second + 1] == "  o     60.00s      0.00      0.00"


def test_nc1_text_is_ascii_without_line_breaks():
    part = _ipe200()
    part.grade = "S275 JR\nñ"
    text = dstv.nc1(part, 1)
    assert "  S275 JR ?" in text.splitlines()
    text.encode("ascii")


def test_write_nc_files_crlf_and_removes_stale(tmp_path):
    (tmp_path / "old.nc1").write_text("x")
    part = _ipe200()
    part.finish()
    files = dstv.write_nc_files([(part, 2)], tmp_path, dstv.NcHeader(order="9"), {"p1": "SD-102"})
    assert [f.name for f in files] == ["p1.nc1"]
    assert not (tmp_path / "old.nc1").exists()
    raw = files[0].read_bytes()
    assert b"\r\n  SD-102\r\n" in raw and raw.endswith(b"EN\r\n")


# ─────────────────────────────────── BVBS ───────────────────────────────────


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("abcde@C", 78),  # the guideline's worked example
        ("BF2D@HjTestPDF@r417@ia@p1@l1000@n10@e0.888@d12@gB500A@s48@v@Gl400@w90@l600@w0@C", 72),
        (
            (
                "BF2D@HjTestPDF@r417@ia@p1@l800@n10@e0.710@d12@gB500A@s48@v@"
                "Gl100@w180@l600@w180@l100@w0@C"
            ),
            71,
        ),
        (
            (
                "BF2D@HjTestPDF@r417@ia@p1@l1224@n10@e1.087@d12@gB500A@s48@v@"
                "Gl100@w90@l300@w45@l424@w-45@l300@w-90@l100@w0@C"
            ),
            82,
        ),
    ],
)
def test_checksum_of_the_guideline_examples(text, value):
    assert bvbs.checksum(text) == value


def _row(**kw):
    values = {
        "mark": "B1-T1",
        "dia": 12.0,
        "radius": 24.0,
        "dims": {"A": 400, "B": 600},
        "cutting_length": 1000.0,
        "total_count": 10,
        "material": "B500A",
        "shape": "11",
    }
    values.update(kw)
    return SimpleNamespace(**values)


L_BAR = SimpleNamespace(bvbs=[("l", "A"), ("w", "90"), ("l", "B"), ("w", "0")], defaults={})


def test_bvbs_record_of_an_l_bar_with_its_checksum():
    header = bvbs.BvbsHeader(project="TestPDF", drawing="417", revision="a")
    line = bvbs.record(_row(), L_BAR, header)
    # e: 1.000 m x 12²/162 kg/m; s: the mandrel, twice the bend radius
    assert line == (
        "BF2D@HjTestPDF@r417@ia@pB1-T1@l1000@n10@e0.889@d12@gB500A@s48@v@Gl400@w90@l600@w0@C83@"
    )
    assert bvbs.checksum(line[: line.rindex("C") + 1]) == 83


def test_bvbs_record_without_geometry_and_separator_in_text():
    header = bvbs.BvbsHeader(project="Test@PDF", drawing="417", revision="a")
    line = bvbs.record(
        _row(mark="7", cutting_length=2350.0, total_count=4, shape="77", dims={}),
        SimpleNamespace(bvbs=None, defaults={}),
        header,
    )
    assert "@G" not in line
    assert line.startswith("BF2D@HjTest PDF@r417@")
    header = bvbs.BvbsHeader(project="TestPDF", drawing="417", revision="a")
    line = bvbs.record(
        _row(mark="7", cutting_length=2350.0, total_count=4, shape="77", dims={}),
        SimpleNamespace(bvbs=None, defaults={}),
        header,
    )
    assert line == "BF2D@HjTestPDF@r417@ia@p7@l2350@n4@e2.089@d12@gB500A@s48@v@C91@"


def test_bvbs_geometry_of_a_radius_bend_uses_the_shape_default():
    shape = SimpleNamespace(
        bvbs=[
            ("l", "A - R - d"),
            ("w", "0"),
            ("r", "R"),
            ("w", "90"),
            ("w", "0"),
            ("l", "B - R - d"),
            ("w", "0"),
        ],
        defaults={"R": "r"},
    )
    g = bvbs.geometry(_row(dims={"A": 500, "B": 700}, radius=40.0), shape)
    assert g == "Gl448@w0@r40@w90@w0@l648@w0@"


def test_bvbs_geometry_refused_when_a_leg_is_not_positive():
    assert bvbs.geometry(_row(dims={"A": 0, "B": 600}), L_BAR) is None


def test_every_pack_shape_geometry_reads():
    """Every bvbs entry of the built-in bar schedule standards evaluates for a typical bar."""
    from saengine.codes.tables import builtin_table

    found = 0
    for pack in ("bnbc2020", "aci318-asce7-22", "eurocodes", "is-codes"):
        table = builtin_table("barSchedule", pack)
        for std in table.standards.values():
            for code, shape in std.shapes.items():
                if not shape.bvbs:
                    continue
                dims = {letter: 900.0 for letter in shape.letters}
                g = bvbs.geometry(_row(dims=dims, shape=code), shape)
                assert g is not None and g.endswith("w0@"), (pack, code)
                found += 1
    assert found >= 30


# ─────────────────────────────────── marks and options ───────────────────────────────────


def _plate(length: float = 210.0) -> Part:
    return Part("plate", "fin plate", "PL 10x95", "PL10*95", "B", "S275", length, h=95.0, tw=10.0)


def test_marks_identical_parts_and_assemblies_share_a_mark():
    a1 = Assembly("beam", "B2", _ipe200(), [Attached(_plate(), 0.0, "end", Weld(6, 210))])
    a2 = Assembly("beam", "B10", _ipe200(), [Attached(_plate(), 0.0, "end", Weld(6, 210))])
    a3 = Assembly("beam", "B3", _ipe200(5000.0))
    model = FabricationModel([a1, a2, a3])
    for a in model.assemblies:
        a.main.finish()
    mark(model, FabricationOptions())
    assert a1.main.mark == a2.main.mark == "p1"
    assert a3.main.mark == "p2"
    assert a1.parts[0].part.mark == "p3"
    assert a1.mark == a2.mark == "B1" and a3.mark == "B2"
    assert a1.members == ["B2", "B10"] and a1.quantity == 2
    assert [p.mark for p, _ in model.parts()] == ["p1", "p2", "p3"]
    assert {p.mark: n for p, n in model.parts()}["p1"] == 2


def test_plate_mass_less_its_holes():
    plate = _plate()
    plate.holes = [Hole("v", 50, 50, 22.0)]
    import math

    expected = (210 * 95 - math.pi * 22**2 / 4) * 10 * 1e-9 * 7850
    assert plate.mass == pytest.approx(expected)


def test_options_take_the_pack_weld_symbols_unless_the_project_chooses():
    assert FabricationOptions.resolve({}).weld_symbols == "aws"  # the default pack (BNBC 2020)
    assert FabricationOptions.resolve({"weldSymbols": "isoA"}).weld_symbols == "isoA"
    opts = FabricationOptions.resolve({"beamPrefix": "SB", "endClearance": 10})
    assert opts.prefixes["beam"] == "SB" and opts.end_clearance == 10


def test_eurocodes_pack_draws_iso_2553():
    from saengine.codes import context as code_context
    from saengine.codes import registry

    with code_context.using(registry.load("eurocodes")):
        assert FabricationOptions.resolve({}).weld_symbols == "isoA"


def test_broken_axis_keeps_both_ends_true():
    from saengine.drawings.sheets.shop import Axis

    axis = Axis(10_000.0, 500.0, 400.0, 600.0)
    assert axis.broken
    assert axis(200.0) == 200.0
    assert axis(10_000.0) == pytest.approx(500.0 + 600.0 + 400.0)
    assert axis(9_700.0) == pytest.approx(500.0 + 600.0 + 100.0)
    assert not Axis(1_000.0, 500.0, 400.0, 600.0).broken


def test_bom_counts_loose_parts_apart():
    from saengine.drawings.sheets.shop import bom_table

    main = _ipe200()
    main.mark = "p1"
    welded = _plate()
    welded.mark = "p3"
    loose = _plate(length=300.0)
    loose.mark = "p4"
    asm = Assembly(
        "beam",
        "B2",
        main,
        [
            Attached(welded, 0.0, "end", Weld(6, 210)),
            Attached(welded, 0.0, "start", Weld(6, 210)),
            Attached(loose, 0.0, "end", None, "splice"),
        ],
    )
    table = bom_table(asm)
    assert [r[0] for r in table.rows] == ["p1", "p3", "p4 L", ""]
    assert table.rows[1][1] == "2"
