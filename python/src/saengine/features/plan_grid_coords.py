"""Coordinates ribbon: survey control, local/global transforms and setting-out data."""

from __future__ import annotations

import math

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.plan_common import plan_data


def _transform(
    x: float, y: float, east: float, north: float, angle_deg: float
) -> tuple[float, float]:
    theta = math.radians(angle_deg)
    return east + x * math.cos(theta) - y * math.sin(theta), north + x * math.sin(
        theta
    ) + y * math.cos(theta)


def _xy_pairs(raw: str) -> list[tuple[float, float]]:
    pairs = []
    try:
        for item in raw.split(";"):
            if item.strip():
                x, y = item.split(",")[:2]
                pairs.append((float(x), float(y)))
    except (ValueError, TypeError) as exc:
        raise FeatureInputError("Enter point pairs as x,y;x,y using metres.") from exc
    if not pairs:
        raise FeatureInputError("Enter at least one coordinate pair.")
    return pairs


@feature(
    "gridCoords.projectBase",
    "Project Base",
    part="floorPlan",
    fields=[
        number("eastM", "Base easting", 500000, unit="m"),
        number("northM", "Base northing", 2600000, unit="m"),
        number("elevationM", "Base elevation", 0, unit="m"),
    ],
    requires_project=False,
)
def project_base(ctx: FeatureContext, values: dict) -> dict:
    """Define the local-origin global coordinate tuple for the structural grid."""
    return result(
        summary={
            "baseEastingM": values["eastM"],
            "baseNorthingM": values["northM"],
            "baseElevationM": values["elevationM"],
        },
        notes=[
            "Global coordinates are formed by adding local coordinates to this origin after rotation."
        ],
    )


@feature(
    "gridCoords.surveyPoint",
    "Survey Point",
    part="floorPlan",
    fields=[
        text("gridPoint", "Grid reference", "A-1"),
        number("eastingM", "Survey easting", 500000, unit="m"),
        number("northingM", "Survey northing", 2600000, unit="m"),
        number("elevationM", "Survey elevation", 0, unit="m"),
    ],
)
def survey_point(ctx: FeatureContext, values: dict) -> dict:
    """Record a survey coordinate at a named grid point and report its offset from the local origin."""
    return result(
        summary={
            "gridPoint": values["gridPoint"],
            "eastingM": values["eastingM"],
            "northingM": values["northingM"],
            "elevationM": values["elevationM"],
        },
        notes=["Survey control quality and datum must be supplied by the survey record."],
    )


@feature(
    "gridCoords.rotateNorth",
    "Rotate North",
    part="floorPlan",
    fields=[number("northAngleDeg", "True north angle from local +Y", 0, unit="°")],
    requires_project=False,
)
def rotate_north(ctx: FeatureContext, values: dict) -> dict:
    """Resolve true-north and grid-axis bearings from a measured angular offset."""
    angle = values["northAngleDeg"]
    return result(
        summary={
            "trueNorthAzimuthFromEastDeg": (90 - angle) % 360,
            "gridXAxisAzimuthDeg": angle % 360,
            "gridYAxisAzimuthDeg": (90 + angle) % 360,
        }
    )


@feature(
    "gridCoords.referencePlanes",
    "Reference Planes",
    part="floorPlan",
    fields=[
        text("names", "Plane names (comma-separated)", "A-axis,1-axis"),
        text("coordinatesMm", "Plane coordinates (comma-separated)", "0,0"),
        select("normal", "Plane normal", [("x", "X normal"), ("y", "Y normal")]),
    ],
    requires_project=False,
)
def reference_planes(ctx: FeatureContext, values: dict) -> dict:
    """Pair plane names with coordinate offsets along their selected normal."""
    names = [x.strip() for x in values["names"].split(",") if x.strip()]
    try:
        coords = [float(x.strip()) for x in values["coordinatesMm"].split(",") if x.strip()]
    except ValueError as exc:
        raise FeatureInputError("Plane coordinates must be numeric millimetres.") from exc
    if len(names) != len(coords):
        raise FeatureInputError("Enter the same number of plane names and coordinates.")
    return result(
        summary={"referencePlaneCount": len(names), "normal": values["normal"]},
        tables=[
            table(
                "Reference plane definitions",
                [("name", "Plane"), ("normal", "Normal"), ("coordinateMm", "Offset", "mm")],
                [
                    {"name": name, "normal": values["normal"].upper(), "coordinateMm": coord}
                    for name, coord in zip(names, coords)
                ],
            )
        ],
    )


@feature(
    "gridCoords.guides",
    "Guides",
    part="floorPlan",
    fields=[
        text("start", "Guide start x,y (m)", "0,0"),
        text("end", "Guide end x,y (m)", "10,0"),
        text("name", "Guide name", "Temporary guide"),
    ],
    requires_project=False,
)
def guides(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a guide-line vector, length and bearing from two local plan coordinates."""
    a = _xy_pairs(values["start"])[0]
    b = _xy_pairs(values["end"])[0]
    dx, dy = b[0] - a[0], b[1] - a[1]
    if math.hypot(dx, dy) <= 0:
        raise FeatureInputError("Guide endpoints must differ.")
    return result(
        summary={
            "name": values["name"],
            "lengthM": math.hypot(dx, dy),
            "bearingDeg": math.degrees(math.atan2(dy, dx)) % 360,
            "deltaXM": dx,
            "deltaYM": dy,
        }
    )


@feature(
    "gridCoords.workingPlane",
    "Working Plane",
    part="floorPlan",
    fields=[
        number("elevationMm", "Plane elevation", 3200, unit="mm"),
        number("rotationDeg", "Plan rotation", 0, unit="°"),
        text("name", "Plane name", "Level 1 plan"),
    ],
    requires_project=False,
)
def working_plane(ctx: FeatureContext, values: dict) -> dict:
    """Describe a horizontal modelling work plane at the selected elevation and rotation."""
    return result(
        summary={
            "name": values["name"],
            "elevationM": values["elevationMm"] / 1000,
            "rotationDeg": values["rotationDeg"] % 360,
            "normalX": 0,
            "normalY": 0,
            "normalZ": 1,
        }
    )


@feature(
    "gridCoords.localGrid",
    "Local Grid",
    part="floorPlan",
    fields=[
        number("originXmm", "Local origin X", 0, unit="mm"),
        number("originYmm", "Local origin Y", 0, unit="mm"),
        number("rotationDeg", "Local axis rotation", 0, unit="°"),
    ],
    requires_project=False,
)
def local_grid(ctx: FeatureContext, values: dict) -> dict:
    """Compute unit vectors and origin for a rotated local coordinate grid."""
    a = math.radians(values["rotationDeg"])
    return result(
        summary={
            "originXmm": values["originXmm"],
            "originYmm": values["originYmm"],
            "xAxisUnitX": math.cos(a),
            "xAxisUnitY": math.sin(a),
            "yAxisUnitX": -math.sin(a),
            "yAxisUnitY": math.cos(a),
        }
    )


@feature(
    "gridCoords.globalCoordinates",
    "Global Coordinates",
    part="floorPlan",
    fields=[
        text("gridPoint", "Grid point", "A-1"),
        number("baseEastM", "Base easting", 500000, unit="m"),
        number("baseNorthM", "Base northing", 2600000, unit="m"),
        number("rotationDeg", "Grid rotation", 0, unit="°"),
    ],
)
def global_coordinates(ctx: FeatureContext, values: dict) -> dict:
    """Transform a local grid intersection into global easting and northing."""
    plan = plan_data(ctx)
    from saengine.features.plan_common import parse_point, point_xy

    x, y = point_xy(plan, parse_point(values["gridPoint"]))
    east, north = _transform(
        x / 1000, y / 1000, values["baseEastM"], values["baseNorthM"], values["rotationDeg"]
    )
    return result(
        summary={
            "gridPoint": values["gridPoint"],
            "localXM": x / 1000,
            "localYM": y / 1000,
            "eastingM": east,
            "northingM": north,
        }
    )


@feature(
    "gridCoords.coordinateReport",
    "Coordinate Report",
    part="floorPlan",
    fields=[
        number("baseEastM", "Base easting", 500000, unit="m"),
        number("baseNorthM", "Base northing", 2600000, unit="m"),
        number("rotationDeg", "Grid rotation", 0, unit="°"),
    ],
)
def coordinate_report(ctx: FeatureContext, values: dict) -> dict:
    """Generate global coordinates for all grid intersections in the project."""
    plan = plan_data(ctx)
    rows = []
    for x in plan["grids"]["x"]:
        for y in plan["grids"]["y"]:
            east, north = _transform(
                float(x["position"]) / 1000,
                float(y["position"]) / 1000,
                values["baseEastM"],
                values["baseNorthM"],
                values["rotationDeg"],
            )
            rows.append(
                {
                    "gridPoint": f"{x['label']}-{y['label']}",
                    "localXM": float(x["position"]) / 1000,
                    "localYM": float(y["position"]) / 1000,
                    "eastingM": east,
                    "northingM": north,
                }
            )
    return result(
        summary={
            "coordinateCount": len(rows),
            "baseEastingM": values["baseEastM"],
            "baseNorthingM": values["baseNorthM"],
        },
        tables=[
            table(
                "Grid intersection coordinates",
                [
                    ("gridPoint", "Grid point"),
                    ("localXM", "Local X", "m"),
                    ("localYM", "Local Y", "m"),
                    ("eastingM", "Easting", "m"),
                    ("northingM", "Northing", "m"),
                ],
                rows,
            )
        ],
    )


@feature(
    "gridCoords.controlPoints",
    "Control Points",
    part="floorPlan",
    fields=[
        text(
            "points",
            "Point records label,easting,northing; semicolon separated",
            "CP1,500000,2600000;CP2,500100,2600000",
        )
    ],
    requires_project=False,
)
def control_points(ctx: FeatureContext, values: dict) -> dict:
    """Validate and report named two-dimensional survey control coordinates."""
    rows = []
    try:
        for record in values["points"].split(";"):
            if not record.strip():
                continue
            label, east, north = [x.strip() for x in record.split(",")[:3]]
            rows.append({"label": label, "eastingM": float(east), "northingM": float(north)})
    except (ValueError, IndexError) as exc:
        raise FeatureInputError(
            "Use label,easting,northing records separated by semicolons."
        ) from exc
    if len(rows) < 1:
        raise FeatureInputError("Enter at least one control point.")
    return result(
        summary={"controlPointCount": len(rows)},
        tables=[
            table(
                "Survey control points",
                [("label", "Point"), ("eastingM", "Easting", "m"), ("northingM", "Northing", "m")],
                rows,
            )
        ],
    )


@feature(
    "gridCoords.settingOutPoints",
    "Setting Out Points",
    part="floorPlan",
    fields=[
        number("baseEastM", "Base easting", 500000, unit="m"),
        number("baseNorthM", "Base northing", 2600000, unit="m"),
        number("rotationDeg", "Grid rotation", 0, unit="°"),
    ],
)
def setting_out_points(ctx: FeatureContext, values: dict) -> dict:
    """List global setting-out coordinates for column locations and footing centres."""
    plan = plan_data(ctx)
    points = [("column", m["id"], m["at"]) for m in plan["columns"]] + [
        ("footing", m["id"], m["at"]) for m in plan["footings"]
    ]
    rows = []
    from saengine.features.plan_common import point_xy

    for kind, mid, p in points:
        x, y = point_xy(plan, p)
        east, north = _transform(
            x / 1000, y / 1000, values["baseEastM"], values["baseNorthM"], values["rotationDeg"]
        )
        rows.append(
            {
                "kind": kind,
                "memberId": mid,
                "gridPoint": f"{p['x']}-{p['y']}",
                "eastingM": east,
                "northingM": north,
            }
        )
    return result(
        summary={"settingOutPointCount": len(rows)},
        tables=[
            table(
                "Setting-out coordinates",
                [
                    ("kind", "Kind"),
                    ("memberId", "Member"),
                    ("gridPoint", "Grid point"),
                    ("eastingM", "Easting", "m"),
                    ("northingM", "Northing", "m"),
                ],
                rows,
            )
        ],
    )


@feature(
    "gridCoords.offsetCoordinates",
    "Offset Coordinates",
    part="floorPlan",
    fields=[
        text("points", "Local points x,y; semicolon separated", "0,0;10,0;10,8"),
        text("baselineStart", "Baseline start x,y", "0,0"),
        text("baselineEnd", "Baseline end x,y", "10,0"),
    ],
    requires_project=False,
)
def offset_coordinates(ctx: FeatureContext, values: dict) -> dict:
    """Report signed perpendicular offsets and chainage along a selected local baseline."""
    points = _xy_pairs(values["points"])
    a = _xy_pairs(values["baselineStart"])[0]
    b = _xy_pairs(values["baselineEnd"])[0]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length == 0:
        raise FeatureInputError("Baseline endpoints must differ.")
    rows = []
    for i, p in enumerate(points):
        along = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length
        offset = (dx * (p[1] - a[1]) - dy * (p[0] - a[0])) / length
        rows.append({"point": i + 1, "chainageM": along, "offsetM": offset})
    return result(
        summary={"pointCount": len(rows), "baselineLengthM": length},
        tables=[
            table(
                "Baseline offsets",
                [
                    ("point", "Point"),
                    ("chainageM", "Chainage", "m"),
                    ("offsetM", "Signed offset", "m"),
                ],
                rows,
            )
        ],
    )


@feature(
    "gridCoords.stationEquation",
    "Station Equation",
    part="floorPlan",
    fields=[
        number("backStationM", "Back station", 100, unit="m"),
        number("aheadStationM", "Ahead station", 98, unit="m"),
        number("equationChainageM", "Equation chainage", 120, unit="m"),
    ],
    requires_project=False,
)
def station_equation(ctx: FeatureContext, values: dict) -> dict:
    """Calculate station jump and absolute chainage labels on either side of a station equation."""
    return result(
        summary={
            "equationChainageM": values["equationChainageM"],
            "stationJumpM": values["aheadStationM"] - values["backStationM"],
            "backLabelM": values["backStationM"],
            "aheadLabelM": values["aheadStationM"],
        },
        notes=["Station labels may jump at the equation; geometric chainage remains continuous."],
    )


@feature(
    "gridCoords.chainageLabels",
    "Chainage Labels",
    part="floorPlan",
    fields=[
        number("routeLengthM", "Route length", 100, unit="m", min=0),
        number("intervalM", "Label interval", 10, unit="m", min=0.01),
        number("startStationM", "Starting station", 0, unit="m"),
    ],
    requires_project=False,
)
def chainage_labels(ctx: FeatureContext, values: dict) -> dict:
    """Generate route chainage markers at a fixed distance interval."""
    count = math.floor(values["routeLengthM"] / values["intervalM"])
    rows = [
        {
            "distanceAlongM": i * values["intervalM"],
            "stationM": values["startStationM"] + i * values["intervalM"],
        }
        for i in range(count + 1)
    ]
    if rows and rows[-1]["distanceAlongM"] < values["routeLengthM"]:
        rows.append(
            {
                "distanceAlongM": values["routeLengthM"],
                "stationM": values["startStationM"] + values["routeLengthM"],
            }
        )
    return result(
        summary={
            "labelCount": len(rows),
            "lastStationM": rows[-1]["stationM"] if rows else values["startStationM"],
        },
        tables=[
            table(
                "Chainage labels",
                [("distanceAlongM", "Distance along route", "m"), ("stationM", "Station", "m")],
                rows,
            )
        ],
    )


@feature(
    "gridCoords.surveyImport",
    "Survey Import",
    part="floorPlan",
    fields=[
        text(
            "records",
            "CSV records label,easting,northing,elevation",
            "P1,500000,2600000,12.3;P2,500010,2600000,12.4",
        )
    ],
    requires_project=False,
)
def survey_import(ctx: FeatureContext, values: dict) -> dict:
    """Parse survey point records and validate coordinate field count and numeric values."""
    rows = []
    try:
        for record in values["records"].split(";"):
            if not record.strip():
                continue
            label, east, north, elev = [x.strip() for x in record.split(",")[:4]]
            rows.append(
                {
                    "label": label,
                    "eastingM": float(east),
                    "northingM": float(north),
                    "elevationM": float(elev),
                }
            )
    except (ValueError, IndexError) as exc:
        raise FeatureInputError(
            "Use label,easting,northing,elevation records separated by semicolons."
        ) from exc
    if not rows:
        raise FeatureInputError("Survey import contains no records.")
    return result(
        summary={
            "importPointCount": len(rows),
            "elevationRangeM": max(r["elevationM"] for r in rows)
            - min(r["elevationM"] for r in rows),
        },
        tables=[
            table(
                "Imported survey points",
                [
                    ("label", "Point"),
                    ("eastingM", "Easting", "m"),
                    ("northingM", "Northing", "m"),
                    ("elevationM", "Elevation", "m"),
                ],
                rows,
            )
        ],
    )


@feature(
    "gridCoords.pointTransform",
    "Point Transform",
    part="floorPlan",
    fields=[
        text("points", "Local points x,y; semicolon separated", "0,0;10,0"),
        number("translationEastM", "Easting shift", 500000, unit="m"),
        number("translationNorthM", "Northing shift", 2600000, unit="m"),
        number("rotationDeg", "Rotation", 0, unit="°"),
    ],
    requires_project=False,
)
def point_transform(ctx: FeatureContext, values: dict) -> dict:
    """Apply a two-dimensional rigid transform to local survey points."""
    points = _xy_pairs(values["points"])
    rows = []
    for i, (x, y) in enumerate(points):
        east, north = _transform(
            x, y, values["translationEastM"], values["translationNorthM"], values["rotationDeg"]
        )
        rows.append(
            {"point": i + 1, "localXM": x, "localYM": y, "eastingM": east, "northingM": north}
        )
    return result(
        summary={"transformedPointCount": len(rows), "rotationDeg": values["rotationDeg"]},
        tables=[
            table(
                "Transformed points",
                [
                    ("point", "Point"),
                    ("localXM", "Local X", "m"),
                    ("localYM", "Local Y", "m"),
                    ("eastingM", "Easting", "m"),
                    ("northingM", "Northing", "m"),
                ],
                rows,
            )
        ],
    )


@feature(
    "gridCoords.datumShift",
    "Datum Shift",
    part="floorPlan",
    fields=[
        number("sourceDatumM", "Source datum", 0, unit="m"),
        number("targetDatumM", "Target datum", 0.25, unit="m"),
        text("elevationsM", "Elevations (comma-separated)", "0,3.2,6.4,10"),
    ],
    requires_project=False,
)
def datum_shift(ctx: FeatureContext, values: dict) -> dict:
    """Convert elevation values by the constant source-to-target datum difference."""
    try:
        elevations = [float(x.strip()) for x in values["elevationsM"].split(",") if x.strip()]
    except ValueError as exc:
        raise FeatureInputError("Elevations must be comma-separated metre values.") from exc
    delta = values["targetDatumM"] - values["sourceDatumM"]
    rows = [
        {"sourceElevationM": z, "shiftedElevationM": z + delta, "shiftM": delta} for z in elevations
    ]
    return result(
        summary={"datumShiftM": delta, "convertedElevationCount": len(rows)},
        tables=[
            table(
                "Datum-shifted elevations",
                [
                    ("sourceElevationM", "Source elevation", "m"),
                    ("shiftedElevationM", "Shifted elevation", "m"),
                    ("shiftM", "Shift", "m"),
                ],
                rows,
            )
        ],
    )


@feature(
    "gridCoords.residualCheck",
    "Residual Check",
    part="floorPlan",
    fields=[text("residualsMm", "Control residuals in mm", "3,-2,1.5,-4")],
    requires_project=False,
)
def residual_check(ctx: FeatureContext, values: dict) -> dict:
    """Compute survey transformation residual RMS, mean, maximum absolute value and range."""
    try:
        residuals = [float(x.strip()) for x in values["residualsMm"].split(",") if x.strip()]
    except ValueError as exc:
        raise FeatureInputError("Residuals must be comma-separated numeric millimetres.") from exc
    if not residuals:
        raise FeatureInputError("Enter at least one residual value.")
    rms = math.sqrt(sum(x * x for x in residuals) / len(residuals))
    return result(
        summary={
            "pointCount": len(residuals),
            "rmsResidualMm": rms,
            "meanResidualMm": sum(residuals) / len(residuals),
            "maximumAbsoluteResidualMm": max(map(abs, residuals), default=0),
            "residualRangeMm": max(residuals) - min(residuals),
        }
    )


@feature(
    "gridCoords.coordinateLabel",
    "Coordinate Label",
    part="floorPlan",
    fields=[
        text("label", "Point label", "A-1"),
        number("eastingM", "Easting", 500000, unit="m"),
        number("northingM", "Northing", 2600000, unit="m"),
        number("elevationM", "Elevation", 0, unit="m"),
        number("precisionM", "Rounding increment", 0.01, unit="m", min=0.0001),
    ],
    requires_project=False,
)
def coordinate_label(ctx: FeatureContext, values: dict) -> dict:
    """Format easting, northing and elevation to a consistent drawing annotation precision."""
    q = values["precisionM"]
    return result(
        summary={
            "label": values["label"],
            "eastingM": round(values["eastingM"] / q) * q,
            "northingM": round(values["northingM"] / q) * q,
            "elevationM": round(values["elevationM"] / q) * q,
            "precisionM": q,
        }
    )


@feature(
    "gridCoords.northLabel",
    "North Label",
    part="floorPlan",
    fields=[
        number("northAzimuthDeg", "North azimuth from east", 90, unit="°"),
        number("symbolScale", "Symbol scale", 1, min=0.01),
    ],
    requires_project=False,
)
def north_label(ctx: FeatureContext, values: dict) -> dict:
    """Compute the unit-vector direction of the north symbol in the plan coordinate frame."""
    a = math.radians(values["northAzimuthDeg"])
    return result(
        summary={
            "northAzimuthDeg": values["northAzimuthDeg"] % 360,
            "directionX": math.cos(a),
            "directionY": math.sin(a),
            "symbolScale": values["symbolScale"],
        }
    )


@feature(
    "gridCoords.levelSymbol",
    "Level Symbol",
    part="floorPlan",
    fields=[
        text("storeyId", "Storey id", "L1"),
        number("datumElevationMm", "Display datum", 0, unit="mm"),
    ],
)
def level_symbol(ctx: FeatureContext, values: dict) -> dict:
    """Resolve a storey's elevation and displayed height relative to the chosen datum."""
    plan = plan_data(ctx)
    story = next((s for s in plan["stories"] if s["id"] == values["storeyId"]), None)
    if story is None:
        raise FeatureInputError("Storey id was not found.")
    return result(
        summary={
            "storey": story["id"],
            "displayElevationMm": float(story["elevation"]) - values["datumElevationMm"],
            "datumElevationMm": values["datumElevationMm"],
        }
    )


@feature(
    "gridCoords.datumNote",
    "Datum Note",
    part="floorPlan",
    fields=[
        text("datumName", "Datum name", "Project datum"),
        text("verticalDatum", "Vertical datum", "Local benchmark"),
        text("units", "Elevation units", "m"),
    ],
    requires_project=False,
)
def datum_note(ctx: FeatureContext, values: dict) -> dict:
    """Create a structured datum note and expose the declared vertical coordinate units."""
    if values["units"] not in {"m", "mm", "ft"}:
        raise FeatureInputError("Use m, mm or ft for the declared elevation units.")
    return result(
        summary={
            "datumName": values["datumName"],
            "verticalDatum": values["verticalDatum"],
            "units": values["units"],
        },
        notes=[
            f"Vertical coordinates are referenced to {values['verticalDatum']} and reported in {values['units']}."
        ],
    )


@feature(
    "gridCoords.gridNote",
    "Grid Note",
    part="floorPlan",
    fields=[
        text("gridReference", "Grid reference", "A-1"),
        text("note", "Note", "Structural grid origin"),
    ],
    requires_project=False,
)
def grid_note(ctx: FeatureContext, values: dict) -> dict:
    """Validate a grid note reference against the current plan when one is available."""
    if ctx.root:
        plan = plan_data(ctx)
        from saengine.features.plan_common import parse_point

        point = parse_point(values["gridReference"])
        point_xy = __import__("saengine.features.plan_common", fromlist=["point_xy"]).point_xy
        point_xy(plan, point)
    return result(
        summary={"gridReference": values["gridReference"], "note": values["note"]},
        notes=["Grid annotation retains the supplied reference text."],
    )
