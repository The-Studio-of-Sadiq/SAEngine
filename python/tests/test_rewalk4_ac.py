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
