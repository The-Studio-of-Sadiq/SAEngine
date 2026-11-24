"""Independent known-answer tests for standalone calculators in the Floor Plan window."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from saengine import features


def _row_by(res: dict, key: str, value: object, table_index: int = 0) -> dict:
    for row in res["tables"][table_index]["rows"]:
        if row[key] == value:
            return row
    raise AssertionError(f"No row with {key}={value!r} in {res['tables'][table_index]['rows']}")


def _write_minimal_plan(tmp_path: Path) -> str:
    plan_dir = tmp_path / "05 Floor Plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    plan_data = {
        "schema": "saengine.floorPlan/1",
        "grids": {
            "x": [{"label": "A", "position": 0}, {"label": "B", "position": 6000}],
            "y": [{"label": "1", "position": 0}, {"label": "2", "position": 5000}],
        },
        "stories": [
            {"id": "BASE", "name": "Base", "elevation": 0},
            {"id": "L1", "name": "Level 1", "elevation": 3200},
            {"id": "L2", "name": "Level 2", "elevation": 6400},
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
            }
        ],
    }
    (plan_dir / "floor-plan.json").write_text(json.dumps(plan_data), encoding="utf-8")
    return str(tmp_path)


# ── Grid & Coordinates (plan_grid_coords.py: 10) ──────────────────────────────────────────────────


def test_grid_coords_chainage_labels() -> None:
    # Route = 55 m, interval = 10 m, start = 100 m -> stations at 0,10,20,30,40,50,55 => 7 labels;
    # lastStationM = 100 + 55 = 155.0 m.
    res = features.run(
        "gridCoords.chainageLabels",
        None,
        {"routeLengthM": 55.0, "intervalM": 10.0, "startStationM": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["labelCount"] == 7
    assert res["summary"]["lastStationM"] == pytest.approx(155.0, rel=0.01)
    assert res["tables"][0]["rows"][3]["stationM"] == pytest.approx(130.0, rel=0.01)


def test_grid_coords_coordinate_label() -> None:
    # Round to increment q = 0.05 m:
    # easting:  123456.784 -> 123456.80
    # northing: 654321.126 -> 654321.15
    # elev:     12.344     -> 12.35
    res = features.run(
        "gridCoords.coordinateLabel",
        None,
        {
            "label": "B-2",
            "eastingM": 123456.784,
            "northingM": 654321.126,
            "elevationM": 12.344,
            "precisionM": 0.05,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["label"] == "B-2"
    assert res["summary"]["eastingM"] == pytest.approx(123456.80, abs=1e-4)
    assert res["summary"]["northingM"] == pytest.approx(654321.15, abs=1e-4)
    assert res["summary"]["elevationM"] == pytest.approx(12.35, abs=1e-4)


def test_grid_coords_datum_shift() -> None:
    # delta = target - source = 10.50 - 2.00 = +8.50 m.
    # Shifted elevations for [1.0, 4.5, 10.0]: [9.5, 13.0, 18.5].
    res = features.run(
        "gridCoords.datumShift",
        None,
        {"sourceDatumM": 2.0, "targetDatumM": 10.5, "elevationsM": "1.0,4.5,10.0"},
    )
    assert res["problems"] == []
    assert res["summary"]["datumShiftM"] == pytest.approx(8.5, rel=0.01)
    assert res["summary"]["convertedElevationCount"] == 3
    rows = res["tables"][0]["rows"]
    assert rows[0]["shiftedElevationM"] == pytest.approx(9.5, rel=0.01)
    assert rows[2]["shiftedElevationM"] == pytest.approx(18.5, rel=0.01)


def test_grid_coords_local_grid() -> None:
    # Rotation = 30 deg CCW:
    # X unit = (cos 30, sin 30) = (0.866025, 0.5)
    # Y unit = (-sin 30, cos 30) = (-0.5, 0.866025)
    res = features.run(
        "gridCoords.localGrid",
        None,
        {"originXmm": 1500.0, "originYmm": 2500.0, "rotationDeg": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["originXmm"] == pytest.approx(1500.0, rel=0.01)
    assert res["summary"]["originYmm"] == pytest.approx(2500.0, rel=0.01)
    assert res["summary"]["xAxisUnitX"] == pytest.approx(math.sqrt(3) / 2, rel=0.01)
    assert res["summary"]["xAxisUnitY"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["yAxisUnitX"] == pytest.approx(-0.5, rel=0.01)
    assert res["summary"]["yAxisUnitY"] == pytest.approx(math.sqrt(3) / 2, rel=0.01)


def test_grid_coords_north_label() -> None:
    # Azimuth from east = 60 deg -> cos(60) = 0.5, sin(60) = 0.866025.
    res = features.run(
        "gridCoords.northLabel",
        None,
        {"northAzimuthDeg": 60.0, "symbolScale": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["northAzimuthDeg"] == pytest.approx(60.0, rel=0.01)
    assert res["summary"]["directionX"] == pytest.approx(0.5, rel=0.01)
    assert res["summary"]["directionY"] == pytest.approx(math.sqrt(3) / 2, rel=0.01)
    assert res["summary"]["symbolScale"] == pytest.approx(2.5, rel=0.01)


def test_grid_coords_point_transform() -> None:
    # Rigid 2D transform: east = E0 + x*cos(theta) - y*sin(theta), north = N0 + x*sin(theta) + y*cos(theta)
    # Shift (1000, 2000), rotation = 90 deg:
    # (10, 0) -> (1000 + 0 - 0, 2000 + 10 + 0) = (1000, 2010)
    # (0, 5)  -> (1000 + 0 - 5, 2000 + 0 + 0)  = (995, 2000)
    res = features.run(
        "gridCoords.pointTransform",
        None,
        {
            "points": "10,0;0,5",
            "translationEastM": 1000.0,
            "translationNorthM": 2000.0,
            "rotationDeg": 90.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["transformedPointCount"] == 2
    rows = res["tables"][0]["rows"]
    assert rows[0]["eastingM"] == pytest.approx(1000.0, rel=0.01)
    assert rows[0]["northingM"] == pytest.approx(2010.0, rel=0.01)
    assert rows[1]["eastingM"] == pytest.approx(995.0, rel=0.01)
    assert rows[1]["northingM"] == pytest.approx(2000.0, rel=0.01)


def test_grid_coords_project_base() -> None:
    res = features.run(
        "gridCoords.projectBase",
        None,
        {"eastM": 325000.0, "northM": 2450000.0, "elevationM": 14.5},
    )
    assert res["problems"] == []
    assert res["summary"]["baseEastingM"] == pytest.approx(325000.0, rel=0.01)
    assert res["summary"]["baseNorthingM"] == pytest.approx(2450000.0, rel=0.01)
    assert res["summary"]["baseElevationM"] == pytest.approx(14.5, rel=0.01)


def test_grid_coords_rotate_north() -> None:
    # northAngleDeg = 15 deg:
    # trueNorthAzimuthFromEastDeg = (90 - 15) % 360 = 75
    # gridXAxisAzimuthDeg = 15, gridYAxisAzimuthDeg = 105
    res = features.run("gridCoords.rotateNorth", None, {"northAngleDeg": 15.0})
    assert res["problems"] == []
    assert res["summary"]["trueNorthAzimuthFromEastDeg"] == pytest.approx(75.0, rel=0.01)
    assert res["summary"]["gridXAxisAzimuthDeg"] == pytest.approx(15.0, rel=0.01)
    assert res["summary"]["gridYAxisAzimuthDeg"] == pytest.approx(105.0, rel=0.01)


def test_grid_coords_station_equation() -> None:
    # back = 250 m, ahead = 242 m -> jump = 242 - 250 = -8 m.
    res = features.run(
        "gridCoords.stationEquation",
        None,
        {"backStationM": 250.0, "aheadStationM": 242.0, "equationChainageM": 300.0},
    )
    assert res["problems"] == []
    assert res["summary"]["stationJumpM"] == pytest.approx(-8.0, rel=0.01)
    assert res["summary"]["equationChainageM"] == pytest.approx(300.0, rel=0.01)
    assert res["summary"]["backLabelM"] == pytest.approx(250.0, rel=0.01)
    assert res["summary"]["aheadLabelM"] == pytest.approx(242.0, rel=0.01)


def test_grid_coords_working_plane() -> None:
    # elevation = 6400 mm = 6.4 m; rotation = 390 deg mod 360 = 30 deg; normal = (0, 0, 1).
    res = features.run(
        "gridCoords.workingPlane",
        None,
        {"elevationMm": 6400.0, "rotationDeg": 390.0, "name": "Level 2"},
    )
    assert res["problems"] == []
    assert res["summary"]["name"] == "Level 2"
    assert res["summary"]["elevationM"] == pytest.approx(6.4, rel=0.01)
    assert res["summary"]["rotationDeg"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["normalZ"] == 1


# ── Plan / Level Templates / Openings (3) ─────────────────────────────────────────────────────────


def test_plan_reference_plane() -> None:
    res = features.run(
        "plan.referencePlane",
        None,
        {"name": "Facade East", "orientation": "y", "offsetMm": 4500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["name"] == "Facade East"
    assert res["summary"]["orientation"] == "y"
    assert res["summary"]["coordinateMm"] == pytest.approx(4500.0, rel=0.01)


def test_plan_grids_level_templates_default_height() -> None:
    res = features.run(
        "planGridsLevelTemplates.defaultHeight",
        None,
        {"heightMm": 3500.0, "missingIds": "L4,L5,L6"},
    )
    assert res["problems"] == []
    assert res["summary"]["defaultHeightMm"] == pytest.approx(3500.0, rel=0.01)
    assert res["summary"]["createdLevelCount"] == 3
    assert _row_by(res, "id", "L5")["heightMm"] == pytest.approx(3500.0, rel=0.01)


def test_plan_grids_level_templates_default_naming() -> None:
    res = features.run(
        "planGridsLevelTemplates.defaultNaming",
        None,
        {"prefix": "Floor ", "firstNumber": 2, "count": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["generatedNames"] == 4
    rows = res["tables"][0]["rows"]
    assert [r["name"] for r in rows] == ["Floor 2", "Floor 3", "Floor 4", "Floor 5"]


def test_plan_grids_openings_tag_opening() -> None:
    # 1500 mm * 2400 mm = 3.60 m2
    res = features.run(
        "planGridsOpenings.tagOpening",
        None,
        {"openingId": "SHAFT-2", "widthMm": 1500.0, "lengthMm": 2400.0, "tagPrefix": "OP"},
    )
    assert res["problems"] == []
    assert res["summary"]["tag"] == "OP-SHAFT-2"
    assert res["summary"]["areaM2"] == pytest.approx(3.6, rel=0.01)
    assert res["summary"]["dimensionLabel"] == "1500 × 2400 mm"


# ── Reference Lines (plan_grids_reference.py: 5) ──────────────────────────────────────────────────


def test_plan_grids_reference_add_dimension() -> None:
    # (0,0) to (3000,4000): length = hypot(3000, 4000) = 5000 mm = 5.0 m.
    # Midpoint = (1500, 2000); left unit normal = (-4000/5000, 3000/5000) = (-0.8, 0.6).
    # With textOffsetMm = 500 -> textX = 1500 - 400 = 1100 mm, textY = 2000 + 300 = 2300 mm.
    res = features.run(
        "planGridsReference.addDimension",
        None,
        {"startMm": "0,0", "endMm": "3000,4000", "textOffsetMm": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["dimensionMm"] == pytest.approx(5000.0, rel=0.01)
    assert res["summary"]["dimensionM"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["textXMm"] == pytest.approx(1100.0, rel=0.01)
    assert res["summary"]["textYMm"] == pytest.approx(2300.0, rel=0.01)


def test_plan_grids_reference_extend_line() -> None:
    # (0,0) to (3000,4000): length = 5000 mm, u = (0.6, 0.8).
    # Start ext = 1000 -> start = (-600, -800).
    # End ext = 1500   -> end = (3900, 5200).
    # Result length = 5000 + 1000 + 1500 = 7500 mm.
    res = features.run(
        "planGridsReference.extendLine",
        None,
        {
            "startMm": "0,0",
            "endMm": "3000,4000",
            "extensionStartMm": 1000.0,
            "extensionEndMm": 1500.0,
        },
    )
    assert res["problems"] == []
    assert res["summary"]["startXMm"] == pytest.approx(-600.0, rel=0.01)
    assert res["summary"]["startYMm"] == pytest.approx(-800.0, rel=0.01)
    assert res["summary"]["endXMm"] == pytest.approx(3900.0, rel=0.01)
    assert res["summary"]["endYMm"] == pytest.approx(5200.0, rel=0.01)
    assert res["summary"]["resultLengthMm"] == pytest.approx(7500.0, rel=0.01)


def test_plan_grids_reference_offset_line() -> None:
    # (0,0) to (6000,8000): length = 10000 mm, left normal = (-0.8, 0.6).
    # Offset = 1000 -> start = (-800, 600), end = (5200, 8600).
    res = features.run(
        "planGridsReference.offsetLine",
        None,
        {"startMm": "0,0", "endMm": "6000,8000", "offsetMm": 1000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["startXMm"] == pytest.approx(-800.0, rel=0.01)
    assert res["summary"]["startYMm"] == pytest.approx(600.0, rel=0.01)
    assert res["summary"]["endXMm"] == pytest.approx(5200.0, rel=0.01)
    assert res["summary"]["endYMm"] == pytest.approx(8600.0, rel=0.01)


def test_plan_grids_reference_plane_offset() -> None:
    # Source = 6000 mm, offset = -1500 mm, axis = y -> target = 4500 mm.
    res = features.run(
        "planGridsReference.planeOffset",
        None,
        {"sourceCoordinateMm": 6000.0, "offsetMm": -1500.0, "axis": "y"},
    )
    assert res["problems"] == []
    assert res["summary"]["axis"] == "Y"
    assert res["summary"]["targetCoordinateMm"] == pytest.approx(4500.0, rel=0.01)


def test_plan_grids_reference_set_work_plane() -> None:
    # elevation = 9600 mm = 9.6 m; rotation = 405 deg mod 360 = 45 deg.
    res = features.run(
        "planGridsReference.setWorkPlane",
        None,
        {"elevationMm": 9600.0, "referenceName": "Level 3", "rotationDeg": 405.0},
    )
    assert res["problems"] == []
    assert res["summary"]["elevationM"] == pytest.approx(9.6, rel=0.01)
    assert res["summary"]["xAxisBearingDeg"] == pytest.approx(45.0, rel=0.01)
    assert res["summary"]["normal"] == "+Z"


# ── Site Position (plan_grids_site.py: 9) ─────────────────────────────────────────────────────────


def test_plan_grids_site_coordinate_units() -> None:
    # 10 ft = 10 * 0.3048 m = 3.048 m = 3048.0 mm.
    res = features.run(
        "planGridsSite.coordinateUnits",
        None,
        {"sourceUnits": "ft", "targetUnits": "mm", "coordinate": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["convertedCoordinate"] == pytest.approx(3048.0, rel=0.01)


def test_plan_grids_site_model_scale() -> None:
    # 200 mm drawing length represents 10 m (= 10000 mm) real -> scale = 10000 / 200 = 50.
    res = features.run(
        "planGridsSite.modelScale",
        None,
        {"drawingLengthMm": 200.0, "knownLengthM": 10.0},
    )
    assert res["problems"] == []
    assert res["summary"]["drawingUnitsToMm"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["scaleRatio"] == "50:1"


def test_plan_grids_site_project_base() -> None:
    # (3000, 4000) mm -> radial offset = hypot(3000, 4000) = 5000.0 mm.
    res = features.run(
        "planGridsSite.projectBase",
        None,
        {"baseXmm": 3000.0, "baseYmm": 4000.0, "baseName": "Core origin"},
    )
    assert res["problems"] == []
    assert res["summary"]["offsetFromLocalOriginMm"] == pytest.approx(5000.0, rel=0.01)


def test_plan_grids_site_reset_north() -> None:
    # Current angle = 22.5 deg -> reset counter-rotation = -22.5 deg.
    res = features.run("planGridsSite.resetNorth", None, {"currentAngleDeg": 22.5})
    assert res["problems"] == []
    assert res["summary"]["resetRotationDeg"] == pytest.approx(-22.5, rel=0.01)
    assert res["summary"]["northAfterResetDeg"] == 0


def test_plan_grids_site_set_bearing() -> None:
    # Bearing 30 deg CW from north, length 100 m:
    # dE = 100 * sin(30) = 50.0 m; dN = 100 * cos(30) = 86.6025 m.
    res = features.run(
        "planGridsSite.setBearing",
        None,
        {"bearingDeg": 30.0, "lineLengthM": 100.0},
    )
    assert res["problems"] == []
    assert res["summary"]["deltaEastM"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["deltaNorthM"] == pytest.approx(50.0 * math.sqrt(3), rel=0.01)


def test_plan_grids_site_set_coordinates() -> None:
    res = features.run(
        "planGridsSite.setCoordinates",
        None,
        {"eastM": 420000.0, "northM": 2510000.0, "elevationM": 8.5, "rotationDeg": 375.0},
    )
    assert res["problems"] == []
    assert res["summary"]["eastingM"] == pytest.approx(420000.0, rel=0.01)
    assert res["summary"]["northingM"] == pytest.approx(2510000.0, rel=0.01)
    assert res["summary"]["elevationM"] == pytest.approx(8.5, rel=0.01)
    assert res["summary"]["rotationDeg"] == pytest.approx(15.0, rel=0.01)


def test_plan_grids_site_site_elevation() -> None:
    # siteDatum = 12.0 m, local = 6400 mm (6.4 m), benchmarkOffset = 0.35 m -> 18.75 m.
    res = features.run(
        "planGridsSite.siteElevation",
        None,
        {"siteDatumM": 12.0, "localElevationMm": 6400.0, "benchmarkOffsetM": 0.35},
    )
    assert res["problems"] == []
    assert res["summary"]["siteElevationM"] == pytest.approx(18.75, rel=0.01)


def test_plan_grids_site_survey_point() -> None:
    # local = (2500, 4000) mm = (2.5, 4.0) m; survey = (500102.5, 2600204.0) m
    # offsetEast = 500102.5 - 2.5 = 500100.0 m; offsetNorth = 2600204.0 - 4.0 = 2600200.0 m.
    res = features.run(
        "planGridsSite.surveyPoint",
        None,
        {"localXmm": 2500.0, "localYmm": 4000.0, "eastM": 500102.5, "northM": 2600204.0},
    )
    assert res["problems"] == []
    assert res["summary"]["offsetEastM"] == pytest.approx(500100.0, rel=0.01)
    assert res["summary"]["offsetNorthM"] == pytest.approx(2600200.0, rel=0.01)


def test_plan_grids_site_true_north() -> None:
    # 30 deg CCW from local +Y (90 deg) -> 120 deg from +X:
    # cos(120) = -0.5, sin(120) = 0.866025.
    res = features.run(
        "planGridsSite.trueNorth",
        None,
        {"angleFromGridDeg": 30.0, "rotationDirection": "ccw"},
    )
    assert res["problems"] == []
    assert res["summary"]["trueNorthAzimuthDeg"] == pytest.approx(120.0, rel=0.01)
    assert res["summary"]["northVectorX"] == pytest.approx(-0.5, rel=0.01)
    assert res["summary"]["northVectorY"] == pytest.approx(math.sqrt(3) / 2, rel=0.01)


# ── Loads (plan_plan_loads.py: 3) ─────────────────────────────────────────────────────────────────


def test_plan_loads_area_load_direction() -> None:
    # Surface-normal pressure 4.0 kPa on a 30 deg sloped roof:
    # vertical = 4.0 * cos(30) = 3.4641 kPa, horizontal = 4.0 * sin(30) = 2.0 kPa.
    res = features.run(
        "planLoads.areaLoadDirection",
        None,
        {"intensityKpa": 4.0, "slopeDeg": 30.0, "direction": "normal"},
    )
    assert res["problems"] == []
    assert res["summary"]["verticalComponentKpa"] == pytest.approx(2.0 * math.sqrt(3), rel=0.01)
    assert res["summary"]["horizontalComponentKpa"] == pytest.approx(2.0, rel=0.01)


def test_plan_loads_point_load() -> None:
    # V = 30 kN, H = 40 kN -> resultant = hypot(30, 40) = 50 kN; atan2(30, 40) = 36.8699 deg.
    res = features.run(
        "planLoads.pointLoad",
        None,
        {
            "node": "B-2",
            "verticalKn": 30.0,
            "horizontalKn": 40.0,
            "momentKnM": 15.0,
            "case": "L",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["forceResultantKn"] == pytest.approx(50.0, rel=0.01)
    assert res["summary"]["forceAngleDeg"] == pytest.approx(
        math.degrees(math.atan2(30.0, 40.0)), rel=0.01
    )
    assert res["summary"]["momentKnM"] == pytest.approx(15.0, rel=0.01)


def test_plan_loads_slab_load(tmp_path: Path) -> None:
    # Note: planLoads.slabLoad has requires_project=False in the registry, but calls plan_data(ctx)
    # to read slab S1's modelled area (there is no manual area field). Without a project it returns
    # a clear problem; with a 6 m x 5 m = 30 m2 slab S1 @ 4.0 kPa -> resultant = 120.0 kN.
    no_proj = features.run(
        "planLoads.slabLoad", None, {"slabId": "S1", "intensityKpa": 4.0, "case": "L"}
    )
    assert no_proj["problems"]

    root = _write_minimal_plan(tmp_path)
    res = features.run(
        "planLoads.slabLoad", root, {"slabId": "S1", "intensityKpa": 4.0, "case": "L"}
    )
    assert res["problems"] == []
    assert res["summary"]["areaM2"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["resultantKn"] == pytest.approx(120.0, rel=0.01)


# ── Camber (plan_members_camber.py: 3) ────────────────────────────────────────────────────────────


def test_plan_members_camber_camber_rounding() -> None:
    # 17.6 mm rounded to 5.0 mm increment -> 20.0 mm, change = +2.4 mm.
    res = features.run(
        "planMembersCamber.camberRounding",
        None,
        {"calculatedCamberMm": 17.6, "roundingIncrementMm": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["roundedCamberMm"] == pytest.approx(20.0, rel=0.01)
    assert res["summary"]["roundingChangeMm"] == pytest.approx(2.4, rel=0.01)


def test_plan_members_camber_camber_tag() -> None:
    res = features.run(
        "planMembersCamber.camberTag",
        None,
        {"beamId": "B4", "camberMm": 18.0, "tagPrefix": "CMB"},
    )
    assert res["problems"] == []
    assert res["summary"]["tag"] == "CMB-B4"
    assert res["summary"]["label"] == "CAMBER 18.0 mm"


def test_plan_members_camber_camber_tolerance() -> None:
    # Design = 20 mm, tolerance = 4 mm, measured = 15 mm -> deviation = -5 mm, abs = 5 mm > 4 mm -> False.
    res = features.run(
        "planMembersCamber.camberTolerance",
        None,
        {"designCamberMm": 20.0, "fabricationToleranceMm": 4.0, "measuredCamberMm": 15.0},
    )
    assert res["problems"] == []
    assert res["summary"]["deviationMm"] == pytest.approx(-5.0, rel=0.01)
    assert res["summary"]["absoluteDeviationMm"] == pytest.approx(5.0, rel=0.01)
    assert res["summary"]["withinTolerance"] is False


# ── Diaphragms / Zones / Stories (5) ──────────────────────────────────────────────────────────────


def test_plan_plan_diaphragms_load_transfer() -> None:
    # Total shear = 600 kN; shares B1:2, B2:1, B3:3 (sum=6) -> 200, 100, 300 kN.
    res = features.run(
        "planPlanDiaphragms.loadTransfer",
        None,
        {"floorShearKn": 600.0, "collectorCapacities": "B1,2;B2,1;B3,3"},
    )
    assert res["problems"] == []
    assert res["summary"]["collectors"] == 3
    assert res["summary"]["transferredShearKn"] == pytest.approx(600.0, rel=0.01)
    assert _row_by(res, "collector", "B1")["shearKn"] == pytest.approx(200.0, rel=0.01)
    assert _row_by(res, "collector", "B2")["shearKn"] == pytest.approx(100.0, rel=0.01)
    assert _row_by(res, "collector", "B3")["shearKn"] == pytest.approx(300.0, rel=0.01)


def test_plan_plan_zones_one_way_distribution() -> None:
    # 4 m (short) x 6 m (long) slab, 3 kPa, spanning in short (4 m) direction:
    # Total load = 3 * 4 * 6 = 72 kN carried by the two 6 m-long supports (36 kN each).
    # Tributary width per support = span / 2 = 4 / 2 = 2.0 m.
    # Line load per support = 3 * 2.0 = 6.0 kN/m (check: 2 * 6.0 kN/m * 6 m = 72 kN).
    res = features.run(
        "planPlanZones.oneWayDistribution",
        None,
        {
            "panelShortSpanM": 4.0,
            "panelLongSpanM": 6.0,
            "areaLoadKpa": 3.0,
            "direction": "short",
        },
    )
    assert res["problems"] == []
    assert res["summary"]["spanM"] == pytest.approx(4.0, rel=0.01)
    assert res["summary"]["tributaryWidthM"] == pytest.approx(2.0, rel=0.01)
    assert res["summary"]["lineLoadKnPerMPerSupport"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["totalPanelLoadKn"] == pytest.approx(72.0, rel=0.01)


def test_plan_plan_zones_zone_edge_offset() -> None:
    # 8 m x 6 m = 48 m2 rectangle, inset = 500 mm (0.5 m each side) -> (8-1)*(6-1) = 7 * 5 = 35 m2.
    # Excluded edge area = 48 - 35 = 13 m2.
    res = features.run(
        "planPlanZones.zoneEdgeOffset",
        None,
        {"boundaryMm": "0,0;8000,0;8000,6000;0,6000", "insetMm": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["originalEnvelopeAreaM2"] == pytest.approx(48.0, rel=0.01)
    assert res["summary"]["insetAreaM2"] == pytest.approx(35.0, rel=0.01)
    assert res["summary"]["excludedEdgeAreaM2"] == pytest.approx(13.0, rel=0.01)


def test_stories_elevation_datum(tmp_path: Path) -> None:
    # Note: stories.elevationDatum has requires_project=False in the registry, but calls
    # plan_data(ctx) to read project storeys (there is no manual storey input). Without a project
    # it returns a clear problem; with storeys [0, 3200, 6400] mm and datum = 1000 mm ->
    # converted elevations = [-1000, 2200, 5400] mm.
    no_proj = features.run(
        "stories.elevationDatum", None, {"datumElevationMm": 1000.0, "datumName": "MSL +1.0"}
    )
    assert no_proj["problems"]

    root = _write_minimal_plan(tmp_path)
    res = features.run(
        "stories.elevationDatum", root, {"datumElevationMm": 1000.0, "datumName": "MSL +1.0"}
    )
    assert res["problems"] == []
    assert res["summary"]["convertedLevels"] == 3
    assert _row_by(res, "storey", "BASE")["datumElevationMm"] == pytest.approx(-1000.0, rel=0.01)
    assert _row_by(res, "storey", "L1")["datumElevationMm"] == pytest.approx(2200.0, rel=0.01)
    assert _row_by(res, "storey", "L2")["datumElevationMm"] == pytest.approx(5400.0, rel=0.01)


def test_stories_storey_template() -> None:
    # 5 storeys, typical height = 3500 mm, base = 500 mm:
    # Elevations: 500, 4000, 7500, 11000, 14500 mm; buildingHeightM = (5 - 1) * 3.5 = 14.0 m.
    res = features.run(
        "stories.storeyTemplate",
        None,
        {"namePrefix": "F", "typicalHeightMm": 3500.0, "count": 5, "baseElevationMm": 500.0},
    )
    assert res["problems"] == []
    assert res["summary"]["storeys"] == 5
    assert res["summary"]["buildingHeightM"] == pytest.approx(14.0, rel=0.01)
    rows = res["tables"][0]["rows"]
    assert rows[0]["name"] == "F1"
    assert rows[0]["elevationMm"] == pytest.approx(500.0, rel=0.01)
    assert rows[-1]["elevationMm"] == pytest.approx(14500.0, rel=0.01)
