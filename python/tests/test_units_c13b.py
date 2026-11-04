"""C13b: the display units remainder (saengine.units): temperatures, the worksheets'
expressions with their values, drawing sizes and tables, the costing sheet; and SI unchanged."""

from __future__ import annotations

import math

from saengine import units as u
from saengine.report.worksheets import calculate, displayed, worksheet_blocks
from saengine.report.worksheets.core import si_only, symbol_of, with_values

US = u.Units("USCustomary", bar_names={"10": "#3", "16": "#5", "20": "#6"})
FEET = u.Units("USCustomary", {"dimension": "ft"})


def test_temperatures_absolute_and_change():
    assert US.convert(100.0, "°C") == (212.0, "°F")
    assert math.isclose(US.to_si(32.0, "°C"), 0.0, abs_tol=1e-12)
    value, unit = US.convert(20.0, "Δ°C")
    assert (round(value, 9), unit) == (36.0, "°F")
    assert math.isclose(US.to_si(36.0, "Δ°C"), 20.0)
    assert math.isclose(US.convert(1.2e-5, "1/°C")[0], 1.2e-5 / 1.8)
    assert u.SI.label("Δ°C") == "°C"  # a change shows "°C" in SI
    assert u.SI.convert(20.0, "°C") == (20.0, "°C")
    # in text: a change after Δ, ± or "by", else an absolute temperature
    text = "ΔTu = ±20 °C on the roof; supply 13 °C; dry bulbs differ by 11 °C"
    assert u.convert_text(text, US) == (
        "ΔTu = ±36 °F on the roof; supply 55.4 °F; dry bulbs differ by 19.8 °F"
    )
    assert u.convert_text(text, u.SI) == text


def test_sizes_and_bar_counts():
    assert u.inches_text(300) == '11 3/4"'
    assert US.size_text(300) == '11 3/4"'
    assert FEET.size_text(600) == "1'-11 5/8\""
    assert u.SI.size_text(300) == "300"
    assert u.convert_text("4Ø16 + 2Ø20, TIES Ø10@150", US) == "4-#5 + 2-#6, TIES #3 @ 5.91 in"
    assert u.convert_text("4Ø12", u.Units("USCustomary")) == "4Ø12"  # no pack name: as it was
    text = "B1 300x500   ELEVATION 1:50, LAP 800, SHS 150x150x8, 150 THK, W310x39"
    assert u.convert_sizes(text, US) == (
        'B1 11 3/4"x19 5/8"   ELEVATION 1:50, LAP 31 1/2", SHS 150x150x8, 5 7/8" THK, W310x39'
    )
    assert u.convert_sizes(text, u.SI) == text


def test_drawing_tables_in_mm():
    columns = [
        {"key": "mark", "title": "Cap"},
        {"key": "size", "title": "L x B x H\n(mm)"},
        {"key": "type", "title": "Pile type\nØ x L (mm)"},
        {"key": "dia", "title": "Bar\nØ (mm)"},
        {"key": "len", "title": "Length\n(mm)"},
    ]
    rows = [["PC1", "1500 x 1500 x 600", "P1: 500 x 18", "16", "6000"]]
    head, body = u.convert_mm_table(columns, rows, US)
    assert [c["title"] for c in head] == [
        "Cap",
        "L x B x H\n(in)",
        "Pile type\nØ x L",
        "Bar\nsize",
        "Length\n(ft-in)",
    ]
    assert body == [["PC1", '59" x 59" x 23 5/8"', 'P1: 19 5/8" x 59.1 ft', "#5", "19'-8 1/4\""]]
    assert u.convert_mm_table(columns, rows, u.SI) == (columns, rows)


def test_worksheet_symbols_and_si_form():
    assert symbol_of("Effective depth d") == "d"
    assert symbol_of("fyt (stirrups)") == "fyt"
    assert symbol_of("As required") is None
    assert symbol_of("Height of F") is None
    assert symbol_of("F at 30.0 m") is None
    assert si_only("0.17 λ √f'c bw d")
    assert si_only("0.000613 Kz V²")
    assert not si_only("As fy / (0.85 f'c b)")
    assert not si_only("1.15 wu ln / 2")
    symbols = {"As": (1256.0, "mm²"), "fy": (420.0, "MPa"), "f'c": (25.0, "MPa"), "b": (300, "mm")}
    assert with_values("As fy / (0.85 f'c b)", symbols, US, False) == (
        "1.95 in² × 60.9 ksi / (0.85 × 3.63 ksi × 11.8 in)"
    )
    assert with_values("1 m strip, stress block", symbols, US, False) is None


def test_worksheet_si_unchanged_and_us_expressions():
    si = calculate("beam-flexure", None)
    assert calculate("beam-flexure", None, u.SI) == si
    assert displayed(si, u.SI) is si
    assert worksheet_blocks(si, "", "", u.SI) == worksheet_blocks(si)
    assert not any("expression" in s for s in si["steps"])
    us = calculate("beam-flexure", None, US)
    a = next(s for s in us["steps"] if s.get("label") == "a")
    assert a["expression"].startswith("As × 60.9 ksi / (0.85 × 3.63 ksi × 11.8 in)")
    assert a["siForm"] is False
    vc = next(s for s in calculate("beam-shear", None, US)["steps"] if s.get("label") == "Vc")
    assert vc["siForm"] is True and "√(25.0 MPa)" in vc["expression"]
    # the numbers stay SI in the calculation; the editor's copy is converted
    assert a["value"] == next(s for s in si["steps"] if s.get("label") == "a")["value"]
    shown = displayed(us, US)
    assert next(s for s in shown["steps"] if s.get("label") == "a")["unit"] == "in"
    blocks = worksheet_blocks(us, "", "", US)
    table = next(b for b in blocks if b.get("t") == "table")
    assert table["head"][:3] == ["Quantity", "Expression", "With values"]
    assert all(b.get("shown") for b in blocks)
    assert u.convert_block(table, US) is table  # the report leaves them as they are


def test_table_specs_convert_mm_columns_in_us_only():
    from saengine.drawings.sheets import schedules
    from saengine.drawings.sheets.model import Table

    table = Table("Clear covers", [{"key": "c", "title": "Clear cover\n(mm)"}], [["40"]])
    token = schedules.TABLE_UNITS.set(US)
    try:
        spec = schedules.table_specs(table, 200)[0]
    finally:
        schedules.TABLE_UNITS.reset(token)
    assert spec.title == "Clear covers"
    assert schedules.TABLE_UNITS.get().si
