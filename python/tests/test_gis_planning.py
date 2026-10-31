"""Planning compliance of the plot (1 Soil Report, site): the code pack's planning table (Dhaka
Mohanagar Imarat Nirman Bidhimala 2008), FAR and MGC, setbacks and the area statement."""

from __future__ import annotations

import json
import math

import pytest

from saengine.codes import context as code_context
from saengine.gis import planning
from saengine.library.report_template import ReportSection, ReportTemplate
from saengine.library.soil import Site
from saengine.report.document import report_document


def test_the_table_has_a_row_per_plot_band() -> None:
    table = code_context.pack_table("planning")
    assert len(table.plotBands) == 15
    assert table.plotBands[0].maxArea == 134 and table.plotBands[-1].maxArea is None
    for use in table.uses.values():
        assert len(use.rows) == 15


@pytest.mark.parametrize(
    ("use", "area", "road", "far", "mgc"),
    [
        # Table 3(A), residential: 4-5 katha on a 6 m road: FAR 3.50, MGC 62.5 %
        ("A1-A4", 300, 6.0, 3.50, 62.5),
        # 2 katha and below: 3.15, 67.5 %
        ("A1-A4", 120, 6.0, 3.15, 67.5),
        # 10-12 katha needs a 9 m road: 4.50, 57.5 %
        ("A1-A4", 700, 9.0, 4.50, 57.5),
        # any plot size on a 24 m road: 6.50, 50 %
        ("A1-A4", 2000, 24.0, 6.50, 50.0),
        # Table 3(E), offices, 7-8 katha on a 9 m road: 4.50, 57.5 %
        ("F1", 500, 9.0, 4.50, 57.5),
        # Table 3(F), industry, above 20 katha on a 12 m road: 4.25, 60 %
        ("G-K", 1500, 12.0, 4.25, 60.0),
        # Rule 51(9): a road 3.65-5.99 m wide: FAR 3.00, MGC 65 %
        ("A1-A4", 300, 4.5, 3.00, 65.0),
        # Rule 51(10): a road 2.50-3.64 m wide: FAR 2.00, MGC 65 %
        ("A1-A4", 300, 3.0, 2.00, 65.0),
    ],
)
def test_permitted_far_and_mgc(use: str, area: float, road: float, far: float, mgc: float) -> None:
    result = planning.permitted(use, area, road)
    assert result["allowed"]
    assert result["far"] == pytest.approx(far)
    assert result["mgc"] == pytest.approx(mgc)


def test_road_increment_rule_51_11() -> None:
    # 10-12 katha row on a 9 m road (4.50); a 10.5 m road is 5 × 0.30 m wider: + 0.25
    assert planning.permitted("A1-A4", 700, 10.5)["far"] == pytest.approx(4.75)


def test_narrower_road_takes_the_row_the_road_allows() -> None:
    # 10-12 katha needs 9 m; on a 6 m road the 9-10 katha row (6 m road) applies: 4.25
    result = planning.permitted("A1-A4", 700, 6.0)
    assert result["far"] == pytest.approx(4.25)
    assert result["notes"]


def test_not_permitted_and_not_restricted() -> None:
    # Table 3(B): schools are not permitted up to 5 katha
    assert not planning.permitted("B1", 200, 9.0)["allowed"]
    # Table 3(E): offices on an 18 m road: FAR not restricted (NR)
    assert math.isinf(planning.permitted("F1", 2000, 18.0)["far"])


def test_required_setbacks_table_2_and_road_centre() -> None:
    # Table 2: 4-5 katha: front 1.5, rear 2.0, each side 1.25 m
    low = planning.required_setbacks(300, 20.0, 6, None)
    assert (low["front"], low["rear"], low["side"]) == (1.5, 2.0, 1.25)
    # above 33 m: front 1.5, rear 3.0, sides 3.0
    high = planning.required_setbacks(300, 40.0, 12, None)
    assert (high["front"], high["rear"], high["side"]) == (1.5, 3.0, 3.0)
    # Rule 46(3): 4.5 m from the centre of a 3 m road: 3.0 m from the boundary
    assert planning.required_setbacks(300, 20.0, 6, 3.0)["front"] == pytest.approx(3.0)


def _site(**plan) -> Site:
    return Site.model_validate(
        {
            "plot": {
                "points": [[0, 0], [15000, 0], [15000, 22000], [0, 22000]],
                "road": 0,
                "front": 1500,
                "rear": 2000,
                "side": 1250,
                "planning": {"use": "A1-A4", "roadWidth": 6000, **plan},
            }
        }
    )


def test_area_statement_and_checks() -> None:
    # 15 × 22 m = 330 m² (4-5 katha): FAR 3.50 → 1155 m², MGC 62.5 % → 206.25 m²
    result = planning.check(_site(groundCoverage=200, floorArea=1200, excludedArea=60))
    assert result["plotArea"] == pytest.approx(330.0)
    assert result["limits"]["floorArea"] == pytest.approx(1155.0)
    assert result["limits"]["mgcArea"] == pytest.approx(206.25)
    by_label = {c["label"]: c for c in result["checks"]}
    assert by_label["FAR"]["provided"] == pytest.approx(1140 / 330, abs=1e-3)
    assert by_label["FAR"]["ok"] and by_label["Ground coverage"]["ok"]
    assert all(by_label[k]["ok"] for k in ("Front setback", "Rear setback", "Side setback"))
    assert not planning.check(_site(groundCoverage=250, floorArea=1200))["ok"]


def test_without_planning_entry_nothing_is_checked() -> None:
    assert planning.check(Site()) is None


def test_floor_areas_from_the_building_model() -> None:
    slab = {"kind": "slab", "boundary": [[0, 0], [10000, 0], [10000, 10000], [0, 10000]]}
    bim = {
        "stories": [
            {"id": "L0", "name": "Ground", "elevation": 0},
            {"id": "L1", "name": "Level 1", "elevation": 3000},
            {"id": "L2", "name": "Roof", "elevation": 6000},
        ],
        "elements": [
            {**slab, "id": "S1", "elevation": 3000},
            {**slab, "id": "S2", "elevation": 6000},
        ],
    }
    areas = planning.floor_areas(json.dumps(bim))
    assert areas["grossFloorArea"] == pytest.approx(200.0)
    assert areas["groundCoverage"] == pytest.approx(100.0)
    assert areas["height"] == pytest.approx(6.0) and areas["storeyCount"] == 2


def test_report_section() -> None:
    result = planning.check(_site(groundCoverage=200, floorArea=1200))
    only = ReportTemplate(sections=[ReportSection(id="planning")])
    document = report_document({"planning": result, "warnings": []}, only)
    assert [s["id"] for s in document["sections"]] == ["planning"]
