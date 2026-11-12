"""The plot of the soil report's site (:mod:`saengine.gis.plot`): its area in m², katha and
decimal, its sides, the buildable envelope the setbacks leave, the floor plan's members outside
them, the grid frame a new building takes, and the plot through the schema and the GIS files."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from saengine.gis import plot
from saengine.gis.site import gis_export, gis_import, soil_location
from saengine.library.soil import Site, SoilReport
from saengine.soil.report import dumps, parse

#: A 12 m × 20 m plot at the project point, the road on its first side (along +X, at y = 0).
RECTANGLE = [[0, 0], [12000, 0], [12000, 20000], [0, 20000]]
SETBACKS = {"front": 3000, "rear": 1500, "side": 1000}
SITE_POINT = {"lat": 23.8069, "lon": 90.3687}


def site(**changes: object) -> Site:
    data = {**SITE_POINT, "rotation": 30, "plot": {"points": RECTANGLE, "road": 0, **SETBACKS}}
    data.update(changes)
    return Site.model_validate(data)


# ─────────────────────────────── units and measures ───────────────────────────────


def test_katha_and_decimal_are_the_deed_units() -> None:
    # 1 katha = 720 sq ft, 1 decimal = 1/100 acre = 435.6 sq ft; 1 ft = 0.3048 m exactly.
    assert plot.KATHA == pytest.approx(66.8902, abs=1e-4)
    assert plot.DECIMAL == pytest.approx(40.4686, abs=1e-4)
    described = plot.describe(site())
    assert described is not None
    assert (described["area"], described["perimeter"]) == (240.0, 64000.0)
    assert described["katha"] == pytest.approx(240 / 66.8902, abs=1e-3)  # 3.588
    assert described["decimal"] == pytest.approx(240 / 40.4686, abs=1e-3)  # 5.931


def test_sides_lengths_bearings_and_kinds() -> None:
    described = plot.describe(site())
    assert described is not None
    # Grid +Y at 30°: side 1 runs along +X (bearing 120°) and faces -Y (210°, SW), the road.
    sides = [
        (s["length"], s["bearing"], s["faces"], s["facing"], s["kind"], s["setback"])
        for s in described["sides"]
    ]
    assert sides == [
        (12000.0, 120.0, 210.0, "SW", "front", 3000.0),
        (20000.0, 30.0, 120.0, "SE", "side", 1000.0),
        (12000.0, 300.0, 30.0, "NE", "rear", 1500.0),
        (20000.0, 210.0, 300.0, "NW", "side", 1000.0),
    ]


def test_the_order_of_the_corners_does_not_turn_the_sides_inside_out() -> None:
    clockwise = site(plot={"points": RECTANGLE[::-1], "road": 2, **SETBACKS})
    described = plot.describe(clockwise)
    assert described is not None
    # Reversed, side 3 (corner 3 to 4) is the old first side: still facing SW, the front.
    assert described["sides"][2]["facing"] == "SW" and described["sides"][2]["kind"] == "front"
    assert described["envelopeArea"] == 155.0


# ─────────────────────────────── the envelope ───────────────────────────────


def test_envelope_by_hand() -> None:
    described = plot.describe(site())
    assert described is not None
    # 12 − 2 × 1 = 10 m wide, 20 − 3 − 1.5 = 15.5 m deep.
    assert described["envelopeArea"] == 155.0
    xs = [p[0] for p in described["envelope"]]
    ys = [p[1] for p in described["envelope"]]
    assert (min(xs), max(xs), min(ys), max(ys)) == (1000, 11000, 3000, 18500)


def test_envelope_of_a_triangle_keeps_each_side_its_setback() -> None:
    triangle = site(plot={"points": [[0, 0], [30000, 0], [0, 30000]], "road": 0, "side": 2000})
    described = plot.describe(triangle)
    assert described is not None
    from shapely.geometry import LineString, Polygon

    envelope = Polygon(described["envelope"])
    ring = [(0, 0), (30000, 0), (0, 30000)]
    for i, setback in enumerate((0, 2000, 2000)):
        side = LineString([ring[i], ring[(i + 1) % 3]])
        assert side.distance(envelope) == pytest.approx(setback, abs=1)


def test_without_a_road_side_every_side_takes_the_side_setback() -> None:
    described = plot.describe(site(plot={"points": RECTANGLE, **SETBACKS}))
    assert described is not None
    assert [s["setback"] for s in described["sides"]] == [1000.0] * 4
    assert any("side facing the road" in p for p in described["problems"])


def test_setbacks_that_leave_nothing() -> None:
    described = plot.describe(site(plot={"points": RECTANGLE, "road": 0, "side": 7000}))
    assert described is not None
    assert described["envelope"] is None and described["fit"] is None
    assert described["problems"] == ["The setbacks leave no buildable area on the plot."]


# ─────────────────────────────── the schema ───────────────────────────────


def test_road_side_must_be_a_side() -> None:
    with pytest.raises(ValidationError, match="road side is one of 0 to 3"):
        site(plot={"points": RECTANGLE, "road": 4})


def test_soil_report_round_trip_and_old_files() -> None:
    report = SoilReport(site=site())
    text = dumps(report)
    again = parse(text)
    assert not isinstance(again, list)
    assert again.site == report.site
    assert json.loads(text)["site"]["plot"] == {"points": RECTANGLE, "road": 0, **SETBACKS}
    # A file from before the plot (a boundary from QGIS only) still reads, and has no road side.
    old = SoilReport.model_validate({"site": {**SITE_POINT, "boundary": [[90.3686, 23.8068]]}})
    assert old.site is not None and old.site.plot is None


def test_a_boundary_in_lat_lon_is_the_plot() -> None:
    corners = [[90.3686, 23.8068], [90.3690, 23.8068], [90.3690, 23.8071], [90.3686, 23.8071]]
    placed = Site.model_validate({**SITE_POINT, "boundary": corners, "plot": {"road": 0}})
    ring, problem = plot.plot_ring(placed)
    assert problem is None and ring is not None
    # 0.0004° of longitude at 23.807° N ≈ 40.8 m; 0.0003° of latitude ≈ 33.2 m.
    assert math.dist(ring[0], ring[1]) == pytest.approx(40.8e3, rel=5e-3)
    assert math.dist(ring[1], ring[2]) == pytest.approx(33.2e3, rel=5e-3)
    described = plot.describe(placed)
    assert described is not None and described["given"] == "wgs84"
    assert described["lonlat"] == [*corners, corners[0]]  # exactly as given
    # Without the site point the boundary is not in the project grid.
    unplaced = Site.model_validate({"boundary": corners})
    assert plot.plot_ring(unplaced)[0] is None
    assert "set the site point" in (plot.describe(unplaced) or {})["problems"][0]


def test_soil_location_reports_the_plot() -> None:
    text = dumps(SoilReport(site=site()))
    out = soil_location(text)
    assert out["plot"]["area"] == 240.0 and out["plot"]["road"] == 0
    assert len(out["plot"]["lonlat"]) == 5 and out["plot"]["lonlat"][0] == out["plot"]["lonlat"][-1]


# ─────────────────────────────── the grid frame ───────────────────────────────


def test_fit_frame_of_a_plot_on_its_side() -> None:
    # The road on side 2 (x = 12 m, facing +X): the grid turns 270° clockwise (90° back) so the
    # road runs along X at the bottom, the frontage 20 m wide and the depth 12 m.
    turned = site(plot={"points": RECTANGLE, "road": 1, **SETBACKS})
    described = plot.describe(turned)
    assert described is not None
    fit = described["fit"]
    assert fit["turn"] == 270.0 and fit["rotation"] == 300.0
    inset = plot.GRID_INSET
    assert fit["width"] == 20000 - 2 * 1000 - 2 * inset
    assert fit["depth"] == 12000 - 3000 - 1500 - 2 * inset
    xs = [p[0] for p in fit["envelope"]]
    ys = [p[1] for p in fit["envelope"]]
    assert (min(xs), min(ys)) == (-inset, -inset)
    road = fit["plot"][1], fit["plot"][2]
    assert road[0][1] == road[1][1] == -inset - 3000  # along X, the front setback below


def test_aligned_site_keeps_the_place_on_the_earth() -> None:
    from saengine.gis.crs import Grid

    turned = site(plot={"points": RECTANGLE, "road": 1, **SETBACKS})
    aligned = Site.model_validate(plot.aligned_site(turned))
    assert aligned.rotation == -60.0
    before, after = Grid(turned), Grid(aligned)
    for old, new in zip(turned.plot.points, aligned.plot.points, strict=True):  # type: ignore[union-attr]
        assert after.to_wgs84(*new) == pytest.approx(before.to_wgs84(*old), abs=1e-9)
    described = plot.describe(aligned)
    # The road on the 20 m side: (12 − 3 − 1.5) × (20 − 2 × 1) = 7.5 × 18 m.
    assert described is not None and described["envelopeArea"] == 135.0
    assert described["fit"]["turn"] == 0.0 and described["fit"]["origin"] == [0.0, 0.0]


# ─────────────────────────────── encroachments ───────────────────────────────

FLOOR_PLAN = {
    "schema": "saengine.floorPlan/1",
    "grids": {
        "x": [{"label": "A", "position": 1500}, {"label": "B", "position": 10500}],
        "y": [{"label": "1", "position": 3500}, {"label": "2", "position": 18000}],
    },
    "stories": [
        {"id": "BASE", "name": "Base", "elevation": 0},
        {"id": "L1", "name": "Level 1", "elevation": 3000},
    ],
    "columns": [
        {"id": "C1", "type": "C400", "at": {"x": "A", "y": "1"}, "base": "BASE", "top": "L1"},
        # 1.5 m − 0.2 m = 1.3 m from the left side: clear of its 1 m setback.
        {"id": "C2", "type": "C400", "at": {"x": "A", "y": "2"}, "base": "BASE", "top": "L1"},
        # Its face at x = 10.5 + 2.2 + 0.2 = 12.9 m: 0.9 m past the plot's right side.
        {
            "id": "C3",
            "type": "C400",
            "at": {"x": "B", "y": "1", "dx": 2200},
            "base": "BASE",
            "top": "L1",
        },
        # Its face 3.5 − 1.0 − 0.2 = 2.3 m from the road: 0.7 m into the 3 m front setback.
        {
            "id": "C4",
            "type": "C400",
            "at": {"x": "B", "y": "1", "dy": -1000},
            "base": "BASE",
            "top": "L1",
        },
    ],
    "beams": [
        {
            "id": "B1",
            "type": "B300",
            "story": "L1",
            "start": {"x": "A", "y": "2"},
            "end": {"x": "B", "y": "2", "dy": 1000},
        },
    ],
    "slabs": [
        {
            "id": "S1",
            "type": "S150",
            "story": "L1",
            "boundary": [
                {"x": "A", "y": "1"},
                {"x": "B", "y": "1"},
                {"x": "B", "y": "2"},
                {"x": "A", "y": "2"},
            ],
        },
    ],
}
OBJECTS = {
    "objects": [
        {
            "id": "C400",
            "kind": "column",
            "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
        },
        {"id": "B300", "kind": "beam", "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500}},
        {"id": "S150", "kind": "slab", "thickness": 150},
    ]
}


def test_members_outside_the_plot_and_in_the_setbacks() -> None:
    found = plot.encroachments(site(), json.dumps(FLOOR_PLAN), json.dumps(OBJECTS))
    assert found["problems"] == [] and len(found["plot"]) == 4 and len(found["envelope"]) == 4
    by_id = {w["id"]: w for w in found["warnings"]}
    assert set(by_id) == {"C3", "C4", "B1"}
    assert (by_id["C3"]["kind"], by_id["C3"]["amount"]) == ("outside", 900.0)
    assert by_id["C3"]["message"] == "Column C3: 0.90 m outside the plot."
    assert (by_id["C4"]["kind"], by_id["C4"]["side"], by_id["C4"]["amount"]) == (
        "setback", "front", 700.0,
    )  # fmt: skip
    assert by_id["C4"]["message"] == "Column C4: 0.70 m into the front setback (3.00 m)."
    # B1 ends at y = 19 m; its 300 mm band's corner reaches 19 + 0.15 × 9000 / √(9000² + 1000²)
    # = 19.149 m: 0.649 m past the rear setback line at 18.5 m.
    assert (by_id["B1"]["side"], by_id["B1"]["amount"]) == ("rear", 649.1)
    assert {w["story"] for w in found["warnings"]} == {"L1"}
    assert plot.part_check_counts(found)["failed"] == 3


def test_no_plot_no_warnings() -> None:
    found = plot.encroachments(Site(), json.dumps(FLOOR_PLAN), json.dumps(OBJECTS))
    assert found == {"plot": None, "envelope": None, "warnings": [], "problems": []}


def test_validation_and_run_all_report_them(tmp_path: Path) -> None:
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import _plot_checks
    from saengine.pipeline.validate import validate_part

    for folder, name, data in (
        ("01 Soil Report", "soil-report.json", json.loads(dumps(SoilReport(site=site())))),
        ("04 Objects", "objects.json", OBJECTS),
        ("05 Floor Plan", "floor-plan.json", FLOOR_PLAN),
    ):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / name).write_text(json.dumps(data), "utf-8")
    (tmp_path / "project.saengine").write_text(
        json.dumps({"schema": "saengine.project/1", "name": "Plot", "type": "building"}), "utf-8"
    )
    project = open_project(tmp_path)
    found = _plot_checks(project, json.dumps(FLOOR_PLAN))
    assert [w["id"] for w in found] == ["C3", "C4", "B1"]
    checks = json.loads((tmp_path / "05 Floor Plan" / "checks.json").read_text("utf-8"))
    assert (checks["part"], checks["problems"], checks["failed"]) == ("floorPlan", 0, 3)
    from saengine.pipeline.validate import _plot_warnings

    warnings = _plot_warnings(project, json.dumps(FLOOR_PLAN))
    assert [(w["severity"], w["path"]) for w in warnings] == [
        ("warning", "C3"), ("warning", "C4"), ("warning", "B1"),
    ]  # fmt: skip
    assert validate_part(project, "soil").state in ("warnings", "ok")


# ─────────────────────────────── GIS files ───────────────────────────────


@pytest.mark.parametrize("suffix", ["geojson", "gpkg"])
def test_plot_through_gis_export_and_import(tmp_path: Path, suffix: str) -> None:
    (tmp_path / "01 Soil Report").mkdir()
    # Clockwise corners: the files write them counter-clockwise, and the road side follows.
    given = site(plot={"points": RECTANGLE[::-1], "road": 2, **SETBACKS})
    (tmp_path / "01 Soil Report" / "soil-report.json").write_text(
        dumps(SoilReport(site=given)), "utf-8"
    )
    out = gis_export(str(tmp_path), suffix, str(tmp_path / f"site.{suffix}"))
    assert out["problems"] == []
    assert out["counts"]["site_boundary"] == 1 and out["counts"]["buildable_envelope"] == 1
    imported = gis_import(out["path"], json.dumps({}))
    assert imported["problems"] == [] and imported["boundary"] is True
    assert any("buildable envelope is worked out" in n for n in imported["notes"])
    report = SoilReport.model_validate_json(imported["soilText"])
    assert report.site is not None and report.site.plot is not None
    assert len(report.site.boundary) == 4 and report.site.plot.points == []
    # Back from the file, the same side faces the road (now counted counter-clockwise).
    again = plot.describe(report.site)
    assert again is not None and again["area"] == pytest.approx(240.0, abs=0.01)
    road = again["sides"][again["road"]]
    assert (road["facing"], road["length"]) == ("SW", pytest.approx(12000, abs=2))


def test_counter_clockwise_keeps_the_road_side() -> None:
    ring = [[0, 0], [0, 1], [1, 1], [1, 0]]  # clockwise; side 0 is the left (x = 0)
    ccw, road = plot.counter_clockwise(ring, 0)
    assert ccw == [[0, 0], [1, 0], [1, 1], [0, 1]] and road == 3
    assert ccw[road] == [0, 1] and ccw[(road + 1) % 4] == [0, 0]  # still the left side


def test_new_building_starts_with_the_aligned_site(tmp_path: Path) -> None:
    from test_new_building import WIZARD

    from saengine.project.new_building import create_building

    turned = site(plot={"points": RECTANGLE, "road": 1, **SETBACKS})
    result = create_building(WIZARD, tmp_path, site=turned.model_dump(mode="json"))
    soil = parse((Path(result["root"]) / "01 Soil Report" / "soil-report.json").read_text("utf-8"))
    assert not isinstance(soil, list) and soil.site is not None
    assert soil.site.rotation == -60.0
    described = plot.describe(soil.site)
    assert described is not None and described["fit"]["origin"] == [0.0, 0.0]
    # The 5 m × 4 m grid of the wizard from (0, 0) is inside the envelope.
    found = plot.encroachments(
        soil.site,
        (Path(result["root"]) / "05 Floor Plan" / "floor-plan.json").read_text("utf-8"),
        (Path(result["root"]) / "04 Objects" / "objects.json").read_text("utf-8"),
    )
    assert found["warnings"] == []
