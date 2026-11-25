"""Site Position ribbon: coordinate references, boundaries and GIS-facing summaries."""

from __future__ import annotations

import math

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.plan_common import export_csv, plan_data, profile


def _points(raw: str) -> list[tuple[float, float]]:
    points = []
    try:
        for token in raw.split(";"):
            if token.strip():
                x, y = token.split(",")[:2]
                points.append((float(x), float(y)))
    except ValueError as exc:
        raise FeatureInputError("Enter coordinate pairs as x,y;x,y in metres.") from exc
    if not points:
        raise FeatureInputError("Enter at least one coordinate point.")
    return points


def _area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        raise FeatureInputError("A closed boundary needs at least three points.")
    return (
        abs(
            sum(
                points[i][0] * points[(i + 1) % len(points)][1]
                - points[(i + 1) % len(points)][0] * points[i][1]
                for i in range(len(points))
            )
        )
        / 2
    )


@feature(
    "planGridsSite.setCoordinates",
    "Set Coordinates",
    part="floorPlan",
    fields=[
        number("eastM", "Project easting", 500000, unit="m"),
        number("northM", "Project northing", 2600000, unit="m"),
        number("elevationM", "Project elevation", 0, unit="m"),
        number("rotationDeg", "Grid rotation", 0, unit="°"),
    ],
    requires_project=False,
)
def set_coordinates(ctx: FeatureContext, values: dict) -> dict:
    """Set the coordinate transform origin and grid rotation used to position the model on site."""
    return result(
        summary={
            "eastingM": values["eastM"],
            "northingM": values["northM"],
            "elevationM": values["elevationM"],
            "rotationDeg": values["rotationDeg"] % 360,
        }
    )


@feature(
    "planGridsSite.projectBase",
    "Project Base",
    part="floorPlan",
    fields=[
        number("baseXmm", "Local base X", 0, unit="mm"),
        number("baseYmm", "Local base Y", 0, unit="mm"),
        text("baseName", "Base point name", "Structural origin"),
    ],
    requires_project=False,
)
def project_base(ctx: FeatureContext, values: dict) -> dict:
    """Describe the local structural datum and report its translation magnitude."""
    return result(
        summary={
            "baseName": values["baseName"],
            "baseXmm": values["baseXmm"],
            "baseYmm": values["baseYmm"],
            "offsetFromLocalOriginMm": math.hypot(values["baseXmm"], values["baseYmm"]),
        }
    )


@feature(
    "planGridsSite.surveyPoint",
    "Survey Point",
    part="floorPlan",
    fields=[
        number("localXmm", "Local X", 0, unit="mm"),
        number("localYmm", "Local Y", 0, unit="mm"),
        number("eastM", "Survey easting", 500000, unit="m"),
        number("northM", "Survey northing", 2600000, unit="m"),
    ],
    requires_project=False,
)
def survey_point(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a translation from one local point to its surveyed global coordinate."""
    return result(
        summary={
            "offsetEastM": values["eastM"] - values["localXmm"] / 1000,
            "offsetNorthM": values["northM"] - values["localYmm"] / 1000,
            "controlPointLocalXmm": values["localXmm"],
            "controlPointLocalYmm": values["localYmm"],
        }
    )


@feature(
    "planGridsSite.lockPosition",
    "Lock Position",
    part="floorPlan",
    fields=[
        checkbox("lockXY", "Lock plan position", True),
        checkbox("lockRotation", "Lock grid rotation", True),
        text("approvalRef", "Approval reference", "Survey check 01"),
    ],
    requires_project=False,
)
def lock_position(ctx: FeatureContext, values: dict) -> dict:
    """Describe which site position transform components are fixed by a review decision."""
    return result(
        summary={
            "positionLocked": values["lockXY"],
            "rotationLocked": values["lockRotation"],
            "approvalRef": values["approvalRef"],
        }
    )


@feature(
    "planGridsSite.trueNorth",
    "True North",
    part="floorPlan",
    fields=[
        number("angleFromGridDeg", "True north angle from grid Y", 0, unit="°"),
        select(
            "rotationDirection",
            "Positive rotation",
            [("ccw", "Counter-clockwise"), ("cw", "Clockwise")],
        ),
    ],
    requires_project=False,
)
def true_north(ctx: FeatureContext, values: dict) -> dict:
    """Calculate true-north azimuth in local plan axes, accounting for the rotation convention."""
    signed = values["angleFromGridDeg"] * (1 if values["rotationDirection"] == "ccw" else -1)
    return result(
        summary={
            "trueNorthAzimuthDeg": (90 + signed) % 360,
            "northVectorX": math.cos(math.radians(90 + signed)),
            "northVectorY": math.sin(math.radians(90 + signed)),
        }
    )


@feature(
    "planGridsSite.gridRotation",
    "Grid Rotation",
    part="floorPlan",
    fields=[
        number("angleDeg", "Grid rotation", 0, unit="°"),
        number("originXmm", "Rotation origin X", 0, unit="mm"),
        number("originYmm", "Rotation origin Y", 0, unit="mm"),
    ],
)
def grid_rotation(ctx: FeatureContext, values: dict) -> dict:
    """Rotate the floor-plan grid reference point coordinates around a selected origin."""
    plan = plan_data(ctx)
    theta = math.radians(values["angleDeg"])
    c, s = math.cos(theta), math.sin(theta)
    rows = []
    for axis in ("x", "y"):
        for line in plan["grids"][axis]:
            x, y = (float(line["position"]), 0) if axis == "x" else (0, float(line["position"]))
            dx, dy = x - values["originXmm"], y - values["originYmm"]
            rows.append(
                {
                    "axis": axis.upper(),
                    "label": line["label"],
                    "xMm": values["originXmm"] + c * dx - s * dy,
                    "yMm": values["originYmm"] + s * dx + c * dy,
                }
            )
    return result(
        summary={"rotatedGridCount": len(rows), "rotationDeg": values["angleDeg"]},
        tables=[
            table(
                "Rotated setting-out points",
                [("axis", "Axis"), ("label", "Grid"), ("xMm", "X", "mm"), ("yMm", "Y", "mm")],
                rows,
            )
        ],
    )


@feature(
    "planGridsSite.setBearing",
    "Set Bearing",
    part="floorPlan",
    fields=[
        number("bearingDeg", "Bearing clockwise from north", 0, unit="°"),
        number("lineLengthM", "Reference line length", 10, unit="m", min=0.01),
    ],
    requires_project=False,
)
def set_bearing(ctx: FeatureContext, values: dict) -> dict:
    """Resolve a site bearing into east and north coordinate deltas."""
    angle = math.radians(values["bearingDeg"])
    return result(
        summary={
            "bearingDeg": values["bearingDeg"] % 360,
            "deltaEastM": values["lineLengthM"] * math.sin(angle),
            "deltaNorthM": values["lineLengthM"] * math.cos(angle),
            "lineLengthM": values["lineLengthM"],
        }
    )


@feature(
    "planGridsSite.resetNorth",
    "Reset North",
    part="floorPlan",
    fields=[number("currentAngleDeg", "Current north angle", 12, unit="°")],
    requires_project=False,
)
def reset_north(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the counter-rotation needed to return project north to the local Y axis."""
    return result(
        summary={
            "currentAngleDeg": values["currentAngleDeg"],
            "resetRotationDeg": -values["currentAngleDeg"],
            "northAfterResetDeg": 0,
        }
    )


@feature(
    "planGridsSite.modelScale",
    "Model Scale",
    part="floorPlan",
    fields=[
        number("drawingLengthMm", "Drawing length", 100, unit="mm", min=0.001),
        number("knownLengthM", "Known real length", 10, unit="m", min=0.001),
    ],
    requires_project=False,
)
def model_scale(ctx: FeatureContext, values: dict) -> dict:
    """Calculate drawing-to-model scale from a known length calibration."""
    scale = values["knownLengthM"] * 1000 / values["drawingLengthMm"]
    return result(
        summary={
            "drawingUnitsToMm": scale,
            "scaleRatio": f"1:{round(1 / scale, 4)}" if scale < 1 else f"{scale:.4g}:1",
            "knownLengthM": values["knownLengthM"],
        }
    )


@feature(
    "planGridsSite.coordinateUnits",
    "Coordinate Units",
    part="floorPlan",
    fields=[
        select(
            "sourceUnits",
            "Input coordinate units",
            [("mm", "Millimetres"), ("m", "Metres"), ("ft", "Feet")],
        ),
        select(
            "targetUnits", "Output units", [("m", "Metres"), ("mm", "Millimetres"), ("ft", "Feet")]
        ),
        number("coordinate", "Coordinate length", 1000.0),
    ],
    requires_project=False,
)
def coordinate_units(ctx: FeatureContext, values: dict) -> dict:
    """Convert linear coordinates between mm, m and ft and summarize project grid bounds."""
    factors = {"mm": 0.001, "m": 1.0, "ft": 0.3048}
    src = float(values["coordinate"])
    converted = src * factors[values["sourceUnits"]] / factors[values["targetUnits"]]
    rows = [
        {
            "item": "Input coordinate",
            "source": f"{src:g} {values['sourceUnits']}",
            "target": f"{converted:.4g} {values['targetUnits']}",
        }
    ]
    if ctx.root is not None:
        raw_plan = ctx.raw("floorPlan")
        if isinstance(raw_plan, dict):
            grids = raw_plan.get("grids") or {}
            if isinstance(grids, dict):
                xs = [
                    float(g["position"])
                    for g in (grids.get("x") or [])
                    if isinstance(g, dict) and "position" in g
                ]
                ys = [
                    float(g["position"])
                    for g in (grids.get("y") or [])
                    if isinstance(g, dict) and "position" in g
                ]
            else:
                xs = [
                    float(g["position"])
                    for g in grids
                    if isinstance(g, dict) and g.get("axis") == "X" and "position" in g
                ]
                ys = [
                    float(g["position"])
                    for g in grids
                    if isinstance(g, dict) and g.get("axis") == "Y" and "position" in g
                ]
            if xs and ys:
                span_x_m = (max(xs) - min(xs)) * 0.001
                span_y_m = (max(ys) - min(ys)) * 0.001
                rows.append(
                    {
                        "item": "Project X grid span",
                        "source": f"{span_x_m * 1000.0:g} mm",
                        "target": f"{span_x_m / factors[values['targetUnits']]:.4g} {values['targetUnits']}",
                    }
                )
                rows.append(
                    {
                        "item": "Project Y grid span",
                        "source": f"{span_y_m * 1000.0:g} mm",
                        "target": f"{span_y_m / factors[values['targetUnits']]:.4g} {values['targetUnits']}",
                    }
                )
    return result(
        summary={
            "sourceCoordinate": src,
            "sourceUnits": values["sourceUnits"],
            "convertedCoordinate": converted,
            "targetUnits": values["targetUnits"],
        },
        tables=[
            table(
                "Coordinate unit conversion",
                [("item", "Item"), ("source", "Source"), ("target", "Converted")],
                rows,
            )
        ],
        notes=["Exact conversion factors: 1 mm = 0.001 m, 1 ft = 0.3048 m."],
    )


@feature(
    "planGridsSite.verifyPosition",
    "Verify Position",
    part="floorPlan",
    fields=[
        text(
            "controlPairs",
            "Local x,y to survey easting,northing; semicolon separated",
            "0,0,500000,2600000;10,0,500010,2600000",
        ),
        number("toleranceMm", "Horizontal tolerance", 50, unit="mm", min=0),
    ],
)
def verify_position(ctx: FeatureContext, values: dict) -> dict:
    """Compare local-to-global control point offsets and report residual spread."""
    rows = []
    try:
        for item in values["controlPairs"].split(";"):
            if item.strip():
                x, y, e, n = [float(v.strip()) for v in item.split(",")[:4]]
                rows.append({"residualEastM": e - x, "residualNorthM": n - y})
    except ValueError as exc:
        raise FeatureInputError(
            "Use x,y,easting,northing records separated by semicolons."
        ) from exc
    if len(rows) < 2:
        raise FeatureInputError("At least two control point pairs are needed to verify position.")
    east = sum(r["residualEastM"] for r in rows) / len(rows)
    north = sum(r["residualNorthM"] for r in rows) / len(rows)
    out = [
        {
            "point": i + 1,
            "residualEastMm": (r["residualEastM"] - east) * 1000,
            "residualNorthMm": (r["residualNorthM"] - north) * 1000,
            "residualMm": math.hypot(r["residualEastM"] - east, r["residualNorthM"] - north) * 1000,
        }
        for i, r in enumerate(rows)
    ]
    return result(
        summary={
            "controlPairs": len(rows),
            "maximumResidualMm": max(r["residualMm"] for r in out),
            "withinTolerance": max(r["residualMm"] for r in out) <= values["toleranceMm"],
        },
        tables=[
            table(
                "Position residuals",
                [
                    ("point", "Point"),
                    ("residualEastMm", "East residual", "mm"),
                    ("residualNorthMm", "North residual", "mm"),
                    ("residualMm", "Magnitude", "mm"),
                ],
                out,
            )
        ],
        notes=[
            "A two-dimensional translation is removed before residuals are compared; no scale or rotation adjustment is fitted."
        ],
    )


@feature(
    "planGridsSite.positionReport",
    "Position Report",
    part="floorPlan",
    fields=[
        number("baseEastM", "Base easting", 500000, unit="m"),
        number("baseNorthM", "Base northing", 2600000, unit="m"),
        number("rotationDeg", "Grid rotation", 0, unit="°"),
    ],
)
def position_report(ctx: FeatureContext, values: dict) -> dict:
    """Summarise transformed global bounds of member geometry for site setting out."""
    plan, rows = profile(ctx)
    theta = math.radians(values["rotationDeg"])
    points = []
    for r in rows:
        for x, y in ((r.get("x1Mm"), r.get("y1Mm")), (r.get("x2Mm"), r.get("y2Mm"))):
            if x is not None and y is not None:
                points.append(
                    (
                        values["baseEastM"]
                        + x / 1000 * math.cos(theta)
                        - y / 1000 * math.sin(theta),
                        values["baseNorthM"]
                        + x / 1000 * math.sin(theta)
                        + y / 1000 * math.cos(theta),
                    )
                )
    return result(
        summary={
            "pointCount": len(points),
            "minEastingM": min((p[0] for p in points), default=None),
            "maxEastingM": max((p[0] for p in points), default=None),
            "minNorthingM": min((p[1] for p in points), default=None),
            "maxNorthingM": max((p[1] for p in points), default=None),
            "gridLineCount": len(plan["grids"]["x"]) + len(plan["grids"]["y"]),
        }
    )


@feature(
    "planGridsSite.siteElevation",
    "Site Elevation",
    part="floorPlan",
    fields=[
        number("siteDatumM", "Site datum", 0, unit="m"),
        number("localElevationMm", "Model elevation", 0, unit="mm"),
        number("benchmarkOffsetM", "Benchmark offset", 0, unit="m"),
    ],
    requires_project=False,
)
def site_elevation(ctx: FeatureContext, values: dict) -> dict:
    """Convert a model elevation from its local datum to the selected site benchmark."""
    return result(
        summary={
            "siteElevationM": values["siteDatumM"]
            + values["localElevationMm"] / 1000
            + values["benchmarkOffsetM"],
            "localElevationMm": values["localElevationMm"],
            "benchmarkOffsetM": values["benchmarkOffsetM"],
        }
    )


@feature(
    "planGridsSite.contourImport",
    "Contour Import",
    part="floorPlan",
    fields=[
        text(
            "contours",
            "Contour points x,y,z metres; semicolon separated",
            "0,0,12;10,0,12.4;10,10,13",
        ),
        number("maximumSlopePercent", "Maximum adjacent slope to flag", 20, unit="%", min=0),
    ],
)
def contour_import(ctx: FeatureContext, values: dict) -> dict:
    """Parse site contour points and calculate elevation range and adjacent segment slopes."""
    pts = []
    try:
        for item in values["contours"].split(";"):
            if item.strip():
                x, y, z = [float(v.strip()) for v in item.split(",")[:3]]
                pts.append((x, y, z))
    except ValueError as exc:
        raise FeatureInputError("Contour records must be x,y,elevation metre triples.") from exc
    if not pts:
        raise FeatureInputError("Enter at least one contour point.")
    segments = []
    for i in range(1, len(pts)):
        run = math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        rise = pts[i][2] - pts[i - 1][2]
        slope = abs(rise) / run * 100 if run else math.inf
        segments.append(
            {
                "fromPoint": i,
                "toPoint": i + 1,
                "horizontalRunM": run,
                "elevationChangeM": rise,
                "slopePercent": slope,
                "exceedsThreshold": slope > values["maximumSlopePercent"],
            }
        )
    return result(
        summary={
            "pointCount": len(pts),
            "elevationRangeM": max(p[2] for p in pts) - min(p[2] for p in pts),
            "steepSegments": sum(s["exceedsThreshold"] for s in segments),
        },
        tables=[
            table(
                "Contour segments",
                [
                    ("fromPoint", "From"),
                    ("toPoint", "To"),
                    ("horizontalRunM", "Run", "m"),
                    ("elevationChangeM", "Rise", "m"),
                    ("slopePercent", "Slope", "%"),
                    ("exceedsThreshold", "Exceeds"),
                ],
                segments,
            )
        ],
    )


@feature(
    "planGridsSite.benchmarkPoint",
    "Benchmark Point",
    part="floorPlan",
    fields=[
        text("name", "Benchmark name", "BM-01"),
        number("eastingM", "Easting", 500000, unit="m"),
        number("northingM", "Northing", 2600000, unit="m"),
        number("elevationM", "Elevation", 12.5, unit="m"),
        number("accuracyMm", "Survey accuracy", 5, unit="mm", min=0),
    ],
)
def benchmark_point(ctx: FeatureContext, values: dict) -> dict:
    """Record a named survey benchmark and express its stated accuracy in metres."""
    return result(
        summary={
            "name": values["name"],
            "eastingM": values["eastingM"],
            "northingM": values["northingM"],
            "elevationM": values["elevationM"],
            "accuracyM": values["accuracyMm"] / 1000,
        }
    )


@feature(
    "planGridsSite.coordinateSystem",
    "Coordinate System",
    part="floorPlan",
    fields=[
        text("horizontalCrs", "Horizontal coordinate reference system", "Local grid"),
        text("verticalDatum", "Vertical datum", "Project benchmark"),
        select("units", "Coordinate units", [("m", "Metres"), ("ft", "Feet")]),
    ],
    requires_project=False,
)
def coordinate_system(ctx: FeatureContext, values: dict) -> dict:
    """Describe the horizontal reference system, vertical datum and coordinate units."""
    return result(
        summary={
            "horizontalCrs": values["horizontalCrs"],
            "verticalDatum": values["verticalDatum"],
            "units": values["units"],
        }
    )


@feature(
    "planGridsSite.transformMesh",
    "Transform Mesh",
    part="floorPlan",
    fields=[
        text("points", "Mesh vertices x,y,z metres; semicolon separated", "0,0,0;10,0,0;10,10,1"),
        number("translateX", "Translate X", 0, unit="m"),
        number("translateY", "Translate Y", 0, unit="m"),
        number("translateZ", "Translate Z", 0, unit="m"),
        number("rotationDeg", "Plan rotation", 0, unit="°"),
    ],
)
def transform_mesh(ctx: FeatureContext, values: dict) -> dict:
    """Apply planar rotation and XYZ translation to an entered site mesh vertex list."""
    points = []
    try:
        for item in values["points"].split(";"):
            if item.strip():
                points.append(tuple(float(v.strip()) for v in item.split(",")[:3]))
    except ValueError as exc:
        raise FeatureInputError("Mesh vertices must be x,y,z triples in metres.") from exc
    if not points or any(len(p) != 3 for p in points):
        raise FeatureInputError("Enter at least one complete mesh vertex.")
    a = math.radians(values["rotationDeg"])
    c, s = math.cos(a), math.sin(a)
    out = [
        {
            "vertex": i + 1,
            "xM": c * x - s * y + values["translateX"],
            "yM": s * x + c * y + values["translateY"],
            "zM": z + values["translateZ"],
        }
        for i, (x, y, z) in enumerate(points)
    ]
    return result(
        summary={"transformedVertices": len(out), "rotationDeg": values["rotationDeg"]},
        tables=[
            table(
                "Transformed site mesh",
                [("vertex", "Vertex"), ("xM", "X", "m"), ("yM", "Y", "m"), ("zM", "Z", "m")],
                out,
            )
        ],
    )


@feature(
    "planGridsSite.geodeticOffset",
    "Geodetic Offset",
    part="floorPlan",
    fields=[
        number("latitudeDeg", "Latitude", 23.8, unit="°", min=-90, max=90),
        number("longitudeDeg", "Longitude", 90.4, unit="°", min=-180, max=180),
        number("eastOffsetM", "East offset", 100, unit="m"),
        number("northOffsetM", "North offset", 100, unit="m"),
        number("earthRadiusM", "Earth radius", 6371008.8, unit="m", min=1),
    ],
)
def geodetic_offset(ctx: FeatureContext, values: dict) -> dict:
    """Approximate a short local east/north offset as latitude and longitude increments."""
    lat = math.radians(values["latitudeDeg"])
    dlat = values["northOffsetM"] / values["earthRadiusM"]
    denom = values["earthRadiusM"] * math.cos(lat)
    if abs(denom) < 1e-9:
        raise FeatureInputError("Longitude offset is undefined at the poles.")
    dlon = values["eastOffsetM"] / denom
    return result(
        summary={
            "latitudeDeg": values["latitudeDeg"] + math.degrees(dlat),
            "longitudeDeg": values["longitudeDeg"] + math.degrees(dlon),
            "deltaLatitudeDeg": math.degrees(dlat),
            "deltaLongitudeDeg": math.degrees(dlon),
        },
        notes=[
            "Local tangent-plane approximation for small offsets; use a geodetic projection for larger extents."
        ],
    )


@feature(
    "planGridsSite.propertyLine",
    "Property Line",
    part="floorPlan",
    fields=[
        text("points", "Property boundary x,y metres", "0,0;40,0;40,30;0,30"),
        number("setbackM", "Required setback", 3, unit="m", min=0),
    ],
)
def property_line(ctx: FeatureContext, values: dict) -> dict:
    """Compute property polygon area and the setback-enclosed comparison area."""
    pts = _points(values["points"])
    area = _area(pts)
    perimeter = sum(
        math.hypot(pts[(i + 1) % len(pts)][0] - pts[i][0], pts[(i + 1) % len(pts)][1] - pts[i][1])
        for i in range(len(pts))
    )
    return result(
        summary={
            "propertyAreaM2": area,
            "propertyPerimeterM": perimeter,
            "setbackM": values["setbackM"],
            "approximateBuildableAreaM2": max(
                0, area - values["setbackM"] * perimeter + math.pi * values["setbackM"] ** 2
            ),
        },
        notes=[
            "Buildable area uses a first-order perimeter setback approximation; corner geometry and easements are not represented."
        ],
    )


@feature(
    "planGridsSite.siteBoundary",
    "Site Boundary",
    part="floorPlan",
    fields=[
        text("points", "Boundary x,y metres", "0,0;50,0;50,40;0,40"),
        number("buildingSetbackM", "Building setback", 5, unit="m", min=0),
    ],
)
def site_boundary(ctx: FeatureContext, values: dict) -> dict:
    """Calculate boundary area, perimeter and a first-order setback buildable-area estimate."""
    pts = _points(values["points"])
    area = _area(pts)
    perimeter = sum(
        math.hypot(pts[(i + 1) % len(pts)][0] - pts[i][0], pts[(i + 1) % len(pts)][1] - pts[i][1])
        for i in range(len(pts))
    )
    return result(
        summary={
            "boundaryAreaM2": area,
            "boundaryPerimeterM": perimeter,
            "setbackM": values["buildingSetbackM"],
            "approximateBuildableAreaM2": max(
                0,
                area
                - values["buildingSetbackM"] * perimeter
                + math.pi * values["buildingSetbackM"] ** 2,
            ),
        }
    )


@feature(
    "planGridsSite.buildingFootprint",
    "Building Footprint",
    part="floorPlan",
    fields=[
        number("baseEastM", "Base easting", 500000, unit="m"),
        number("baseNorthM", "Base northing", 2600000, unit="m"),
        number("rotationDeg", "Grid rotation", 0, unit="°"),
    ],
)
def building_footprint(ctx: FeatureContext, values: dict) -> dict:
    """Derive the plan footprint envelope and slab area from structural floor geometry."""
    plan, rows = profile(ctx)
    slabs = [r for r in rows if r["category"] == "slab"]
    if not slabs:
        raise FeatureInputError(
            "Add floor slab panels before calculating the structural footprint."
        )
    x = [c for s in plan["slabs"] for c in s["boundary"]]
    from saengine.features.plan_common import point_xy

    coords = [point_xy(plan, p) for p in x]
    theta = math.radians(values["rotationDeg"])
    pts = [
        (
            values["baseEastM"] + (px * math.cos(theta) - py * math.sin(theta)) / 1000,
            values["baseNorthM"] + (px * math.sin(theta) + py * math.cos(theta)) / 1000,
        )
        for px, py in coords
    ]
    return result(
        summary={
            "slabAreaM2": sum(r["areaM2"] for r in slabs),
            "envelopeWidthM": max(p[0] for p in pts) - min(p[0] for p in pts),
            "envelopeDepthM": max(p[1] for p in pts) - min(p[1] for p in pts),
            "minEastingM": min(p[0] for p in pts),
            "minNorthingM": min(p[1] for p in pts),
        }
    )


@feature(
    "planGridsSite.gisExport",
    "GIS Export",
    part="floorPlan",
    fields=[
        text("filename", "CSV filename", "structural-points.csv"),
        number("baseEastM", "Base easting", 500000, unit="m"),
        number("baseNorthM", "Base northing", 2600000, unit="m"),
        number("rotationDeg", "Grid rotation", 0, unit="°"),
    ],
)
def gis_export(ctx: FeatureContext, values: dict) -> dict:
    """Write transformed member reference points as a GIS-ready CSV point layer."""
    _, rows = profile(ctx)
    theta = math.radians(values["rotationDeg"])
    out = []
    for r in rows:
        for label, x, y in (
            ("start", r.get("x1Mm"), r.get("y1Mm")),
            ("end", r.get("x2Mm"), r.get("y2Mm")),
        ):
            if x is not None and y is not None:
                out.append(
                    {
                        "memberId": r["id"],
                        "category": r["category"],
                        "point": label,
                        "eastingM": values["baseEastM"]
                        + x / 1000 * math.cos(theta)
                        - y / 1000 * math.sin(theta),
                        "northingM": values["baseNorthM"]
                        + x / 1000 * math.sin(theta)
                        + y / 1000 * math.cos(theta),
                    }
                )
    name = values["filename"].strip()
    if not name.lower().endswith(".csv") or "/" in name or "\\" in name:
        raise FeatureInputError("Use a simple .csv filename without folders.")
    path = export_csv(ctx, name, ["memberId", "category", "point", "eastingM", "northingM"], out)
    return result(
        summary={"exportedPoints": len(out), "file": path},
        notes=[f"Wrote transformed structural points to {path}."],
    )
