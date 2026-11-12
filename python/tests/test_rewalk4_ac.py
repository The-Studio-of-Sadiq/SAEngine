"""Re-walk 4, tracks A and C (2026-11-10): the fixes of the US, UK and steel walks."""

from __future__ import annotations

import json
from types import SimpleNamespace

from saengine.boq.quantities import BillOfQuantities
from saengine.boq.schedule import _material_id, material_ids, take_from_schedule

US_MATERIALS = json.dumps(
    {
        "materials": [
            {
                "id": "A615-60",
                "name": "Rebar ASTM A615 Grade 60",
                "category": "rebar",
                "steel": {"grade": "ASTM A615 Grade 60", "fy": 413.7},
            }
        ]
    }
)


# ── R4AC-1: the bill takes the schedule's bars under their material id ──


def test_schedule_grade_names_map_to_material_ids() -> None:
    ids = material_ids(US_MATERIALS)
    assert ids["ASTM A615 Grade 60"] == "A615-60"
    assert _material_id("ASTM A615 Grade 60", ids) == "A615-60"
    assert _material_id("B420DWR", {}) == "B420DWR"  # already an id: unchanged
    assert _material_id("Grade 60 (other)", {}) == "Grade-60-other"


def test_bill_with_grade_named_rows_validates() -> None:
    row = SimpleNamespace(
        element="C1",
        kind="column",
        bim=("C1",),
        dia=16.0,
        mass=12.5,
        story="L1",
        mark="C1-1",
        material="ASTM A615 Grade 60",
    )
    schedule = SimpleNamespace(rows=[row])
    document = BillOfQuantities()
    take_from_schedule(document, schedule, material_ids(US_MATERIALS))
    assert [i.material for i in document.items] == ["A615-60"]
    assert "ASTM A615 Grade 60" in document.items[0].description
    BillOfQuantities.model_validate_json(document.model_dump_json(by_alias=True))


# ── R4AC-2: the latitude and longitude typed in the wizard are the site point ──

WIZARD = {
    "schema": "saengine.newBuilding/1",
    "name": "Site Point",
    "spacings": {"x": [5000], "y": [4000]},
    "stories": [
        {"id": "BASE", "name": "Base", "elevation": 0},
        {"id": "L1", "name": "Level 1", "elevation": 3200},
    ],
    "storyHeights": [3200],
    "system": "rcFrame",
    "site": {"location": "dhaka", "siteClass": "SD", "siteClassSource": "assumed"},
}


def test_wizard_site_point_reaches_the_soil_report(tmp_path) -> None:
    from saengine.project.new_building import create_building
    from saengine.soil.report import parse as parse_soil

    # The wizard sends the typed point as the site when there is no plot.
    create_building(WIZARD, tmp_path, site={"lat": 34.0522, "lon": -118.2437})
    text = (tmp_path / "Site Point" / "01 Soil Report" / "soil-report.json").read_text("utf-8")
    report = parse_soil(text)
    assert not isinstance(report, list)
    assert report.site.point == (34.0522, -118.2437)


def _using(pack_id: str):
    from saengine.codes import context as cc

    return cc.using(cc.pack_for({"codePack": pack_id}))


# ── R4AC-3: the tie beams cite the pack in force; the title page names it alone ──


def test_tie_beam_method_follows_the_pack_in_force() -> None:
    from saengine.substructure.shallow import shallow_method

    with _using("bnbc2020"):
        bnbc = shallow_method()[-1]
    with _using("aci318-asce7-22"):
        us = shallow_method()[-1]
    with _using("eurocodes-uk"):
        uk = shallow_method()[-1]
    assert "BNBC 2020 Part 6 Sec 1.8.5.2 (b)" in bnbc and "seismic zones" in bnbc
    for text in (us, uk):
        assert "BNBC" not in text and "seismic zones" not in text
    assert "ACI 318-19 Sec 18.13.3.2" in us


def test_substructure_report_reads_the_method_when_designed() -> None:
    import inspect

    from saengine.substructure import report

    assert "SHALLOW_METHOD" not in inspect.getsource(report)


# ── R4AC-4: Grade 60 is 60 ksi; the notes take the pack's values ──


def test_us_grades_and_limits_are_inch_pound() -> None:
    from saengine.codes import context as cc
    from saengine.drawings.detailing import psi_g

    with _using("aci318-asce7-22"):
        grades = {g.id: g.fy for g in cc.table("materials").rebarGrades}
        assert grades["A615-60"] == 413.7 and grades["A615-80"] == 551.6
        assert cc.table("concrete").fytShearMax == 413.7
        # a Grade 60 bar entered as 420 MPa is still Grade 60 (psi_g 1.0), Grade 80 is 1.15
        assert psi_g(413.7) == psi_g(420.0) == 1.0
        assert psi_g(551.6) == 1.15
    with _using("bnbc2020"):
        assert cc.table("concrete").fytShearMax == 420.0


def test_detailing_lengths_from_the_bar_schedule_standard() -> None:
    from saengine.drawings.detailing import _standard_lengths

    with _using("aci318-asce7-22"):
        assert _standard_lengths() == {"round": 25.4, "stockLength": 18288.0}
    with _using("bnbc2020"):
        assert _standard_lengths() == {"round": 25.0, "stockLength": 12000.0}


def test_no_lap_note_names_the_pack_bars() -> None:
    from saengine.drawings.sheets.project import _no_lap_bars

    with _using("aci318-asce7-22"):
        assert _no_lap_bars() == "bars larger than #11"
    with _using("bnbc2020"):
        assert _no_lap_bars() == "36 mm bars and larger"


# ── R4AC-5: one column-top anchorage check, in the project's units ──


def test_column_top_anchorage_is_one_check() -> None:
    from saengine.design import ductile_joints as dj
    from saengine.drawings import detailing

    with _using("aci318-asce7-22"):
        rule, available = dj.column_top_anchorage(29.0, 413.7, 27.6, 608.0)
        assert available == 608.0 - dj.TOP_HOOK_COVER
        assert rule.value == detailing.hook_development(29.0, 413.7, 27.6).value


def test_check_problems_in_us_units() -> None:
    from saengine.pipeline.drawings import check_problems
    from saengine.units import Units

    model = {
        "elements": [
            {
                "id": "C1",
                "checks": [
                    {
                        "name": "Column bars hooked into the beams at the top (Ø29)",
                        "required": 936.8,
                        "provided": 568.0,
                        "unit": "mm",
                        "ok": False,
                        "clause": "",
                    }
                ],
            }
        ]
    }
    us = Units(system="USCustomary", bar_names={"29": "#9"})
    (line,) = check_problems(model, None, us)
    assert "mm" not in line and "#9" in line and " in needed" in line


# ── R4AC-7: the EC pack's own terms and spacings ──


def test_uk_slab_spacing_and_terms() -> None:
    from saengine.design import slab
    from saengine.drawings.detailing import hook_term
    from saengine.library.generator import _category, _term

    with _using("eurocodes-uk"):
        assert slab.max_spacing("twoWay") == (3.0, 400.0)
        assert "min(3h, 400 mm)" in slab.spacing_clause("twoWay")
        assert hook_term() != "ldh"
        assert _category() == "seismicity category"
        assert "Cd" not in _term("designDriftName", "-")
    with _using("bnbc2020"):
        assert slab.max_spacing("twoWay") == (2.0, 450.0)
        assert hook_term() == "ldh"
        assert _category() == "Seismic Design Category"


# ── 8: the UK combinations store the factors their names state ──


def test_uk_combination_names_match_factors() -> None:
    from saengine.codes import context as cc

    with _using("eurocodes-uk"):
        sets = cc.table("combinations").strengthSets
        for combos in sets.values():
            for c in combos:
                name, factors = c.name, c.factors
                assert "S" not in name.replace("Lr", "")
                if name.startswith("1.25G"):
                    assert factors["D"] == 1.25


# ── R4AC-9: names and messages in US units ──


def test_generator_names_in_inches() -> None:
    from saengine.library import generator

    token = generator._INCHES.set(True)
    try:
        assert generator._dim(863.6) == "34"
        assert (
            "m"
            not in generator.footing_sizes(
                [{"type": "isolated", "length": 2336.8, "width": 2336.8, "thickness": 457.2}]
            )[0].split("isolated")[1]
        )
    finally:
        generator._INCHES.reset(token)
    assert generator._dim(400.0) == "400"


def test_bracketed_units_convert() -> None:
    from saengine.units import Units, convert_text

    us = Units(system="USCustomary")
    assert convert_text("what the storey adds [kN]", us) == "what the storey adds [kip]"
