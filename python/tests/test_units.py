"""C13: display units (saengine.units): conversion pins both ways, number and feet-inch text,
the report document and the bar bending schedule in US customary units, and SI unchanged."""

from __future__ import annotations

import math

import pytest

from saengine import units as u
from saengine.library.settings import DisplayUnits, ProjectInfo, ProjectSettings

US = u.Units("USCustomary", bar_names={"10": "#3", "16": "#5"})

# (SI value, SI unit, US value, US unit): from the exact definitions (NIST SP 811)
PINS = [
    (1.0, "m", 3.280839895, "ft"),
    (25.4, "mm", 1.0, "in"),
    (4.4482216152605, "kN", 1.0, "kip"),
    (6.894757293168, "MPa", 1.0, "ksi"),
    (0.04788025898, "kN/m²", 1.0, "psf"),
    (0.04788025898, "kPa", 1.0, "psf"),
    (1.3558179483314, "kN·m", 1.0, "kip·ft"),
    (14.593902937206, "kN/m", 1.0, "kip/ft"),
    (0.157087463844, "kN/m³", 1.0, "pcf"),
    (16.018463374, "kg/m³", 1.0, "pcf"),
    (645.16, "mm²", 1.0, "in²"),
    (1.0, "m³", 35.314666721, "ft³"),
    (0.45359237, "kg", 1.0, "lb"),
    (0.44704, "m/s", 1.0, "mph"),
    (0.17512683524, "kN/mm", 1.0, "kip/in"),
]


@pytest.mark.parametrize(("si", "si_unit", "us", "us_unit"), PINS)
def test_conversion_pins_both_ways(si, si_unit, us, us_unit):
    value, unit = US.convert(si, si_unit)
    assert unit == us_unit
    assert math.isclose(value, us, rel_tol=1e-9)
    assert math.isclose(US.to_si(us, si_unit), si, rel_tol=1e-9)


def test_choices_and_si():
    yards = u.Units("USCustomary", {"volume": "yd³", "force": "lbf"})
    assert yards.convert(1.0, "m³")[1] == "yd³"
    assert math.isclose(yards.convert(1.0, "kN")[0], 224.8089431, rel_tol=1e-9)
    assert u.SI.convert(250.0, "mm") == (250.0, "mm")
    assert US.convert(20.0, "°C") == (20.0, "°C")  # temperatures stay


def test_formats():
    assert US.format(250, "mm") == "9.84 in"
    assert US.format(28, "MPa") == "4.06 ksi"
    assert US.format(4.8, "kN/m²") == "100 psf"
    assert u.fmt(12345.6) == "12,346"
    assert u.feet_inches(3810) == "12'-6\""
    assert u.feet_inches(165.1) == '6 1/2"'
    assert u.feet_inches(3048) == "10'-0\""
    text = "Beam 300 × 500 mm, f'c = 28 MPa, Ø16 @ 150, Table 6.2.19, 5 mm/m"
    assert u.convert_text(text, US) == (
        "Beam 11.8 × 19.7 in, f'c = 4.06 ksi, #5 @ 5.91 in, Table 6.2.19, 5 mm/m"
    )
    assert u.convert_text(text, u.SI) == text
    assert u.convert_levels("ROOF +3.000", US) == "ROOF +9.84'"


def test_settings_units_default_si_and_not_written():
    settings = ProjectSettings(project=ProjectInfo(name="P"), floorLoad="FL", roofLoad="RF")
    assert "units" not in settings.model_dump(by_alias=True)
    assert u.units_of(settings).si
    us = settings.model_copy(update={"units": DisplayUnits(system="USCustomary", force="lbf")})
    assert us.model_dump(by_alias=True)["units"]["system"] == "USCustomary"
    assert u.units_of(us).unit("force") == "lbf"
    with pytest.raises(ValueError):
        DisplayUnits(force="ksi")


def test_new_project_takes_the_pack_units():
    from saengine.library.settings import default_project_settings

    assert default_project_settings("P").units.system == "SI"
    assert default_project_settings("P", "aci318-asce7-22").units.system == "USCustomary"


def test_report_section_in_us_units():
    document = {
        "sections": [
            {
                "id": "basis",
                "title": "Design basis",
                "blocks": [
                    {"t": "h", "level": 1, "text": "Design basis"},
                    {"t": "pairs", "rows": [["Shell mesh size", "500 mm"]], "width": "55%"},
                    {
                        "t": "table",
                        "head": ["Check", "Value", "", "Limit", "Unit", "Util."],
                        "rows": [["Flexure", "120", "≤", "150", "kN·m", "0.80"]],
                    },
                    {
                        "t": "checks",
                        "title": "B1",
                        "ok": True,
                        "rows": [["Shear", "80.0", "100", "kN", "0.80", "1.2D", "OK", ""]],
                        "fails": [False],
                    },
                ],
            }
        ],
        "warnings": [],
    }
    out = u.convert_document(document, US)
    blocks = out["sections"][0]["blocks"]
    assert blocks[1] == {"t": "note", "text": u.UNITS_NOTE}
    assert blocks[2]["rows"] == [["Shell mesh size", "19.7 in"]]
    assert blocks[3]["rows"] == [["Flexure", "88.5", "≤", "111", "kip·ft", "0.80"]]
    assert blocks[4]["rows"][0][:4] == ["Shear", "18", "22.5", "kip"]
    assert u.convert_document(document, u.SI) is document


def test_bbs_csv_si_unchanged_and_us():
    from saengine.drawings import bbs
    from tests.test_drawings_bbs import beam

    schedule = bbs.bar_schedule({"elements": [beam()]})
    assert bbs.schedule_csv(schedule) == bbs.schedule_csv(schedule, u.SI)
    us = bbs.schedule_csv(schedule, US)
    assert "(ft-in)" in us
    assert "Mass (lb)" in us
    # the 300x500 beam's stirrup: 1450 mm -> 4'-9 1/8", Ø10 -> #3
    assert "B420DWR #3" in us
    assert "4'-9 1/8\"" in us
    assert bbs.sheet_table(schedule) == bbs.sheet_table(schedule, u.SI)
    shown = bbs.sheet_table(schedule, US)
    assert "(ft-in)" in shown["columns"][4]["title"]
    assert shown["totals"]["columns"][-1]["title"] == "Total\n(lb)"
    # the drawings' bar data keep the cutting lengths in mm
    assert shown["cuttingLengths"] == bbs.sheet_table(schedule)["cuttingLengths"]
