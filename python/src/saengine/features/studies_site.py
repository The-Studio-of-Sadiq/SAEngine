"""Studies Site - terrain surfaces, earthworks, drainage and land-survey outputs."""

from __future__ import annotations

import itertools
import math
import xml.etree.ElementTree as ET

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
from saengine.features.studies_common import numbers, points, records, write_json, write_text


def _terrain(ctx: FeatureContext):
    """Read and validate the site's stored terrain TIN."""
    path = ctx.path("01 Soil Report/terrain.json")
    if path is None or not path.is_file():
        raise FeatureInputError("Import survey points or create a terrain surface first.")
    from saengine.gis.terrain import parse

    try:
        terrain = parse(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FeatureInputError("The project's terrain file is not valid.") from error
    if not terrain.points or not terrain.triangles:
        raise FeatureInputError("The project terrain needs survey points and triangulated faces.")
    return terrain


def _surface(
    ctx: FeatureContext, pts: list[tuple[float, float, float]], label: str
) -> tuple[list[list[float]], list[list[int]]]:
    """Triangulate supplied project-grid points and save a terrain model."""
    import numpy as np

    from saengine.gis.terrain import Terrain, TerrainSource, triangulate

    array = np.asarray(pts, dtype=float)
    try:
        triangles = triangulate(array).tolist()
    except ValueError as error:
        raise FeatureInputError(str(error)) from error
    model = Terrain(
        source=TerrainSource(format="points", units="mm", pointsRead=len(pts)),
        points=array.tolist(),
        triangles=triangles,
        notes=[label],
    )
    write_json(ctx, "01 Soil Report/terrain.json", model.model_dump(mode="json", by_alias=True))
    return model.points, model.triangles


@feature(
    "studiesSite.importSurface",
    "Import Surface",
    part="soil",
    fields=[
        text("surveyPoints", "Survey XYZ points", "0 0 10\n100 0 11\n100 100 12\n0 100 10"),
        select(
            "units",
            "Horizontal units",
            [("m", "Metres"), ("mm", "Millimetres"), ("ft", "Feet")],
            "m",
        ),
        number("datum", "Survey elevation at project z = 0", 0, unit="m"),
    ],
)
def import_surface(ctx: FeatureContext, values: dict) -> dict:
    """Import surveyed XYZ coordinates, convert horizontal units to project millimetres and build a TIN."""
    from saengine.gis.terrain import UNIT_MM

    pts = points(values["surveyPoints"], "survey points")
    scale = UNIT_MM[values["units"]]
    datum = values["datum"] * 1000
    converted = [(x * scale, y * scale, z * 1000 - datum) for x, y, z in pts]
    xyz, triangles = _surface(ctx, converted, "Survey surface imported from XYZ points.")
    return result(
        summary={"pointCount": len(xyz), "triangleCount": len(triangles), "datumMm": datum},
        tables=[
            table(
                "Imported survey points",
                [("index", "Point"), ("x", "X", "mm"), ("y", "Y", "mm"), ("z", "Elevation", "mm")],
                [{"index": i + 1, "x": p[0], "y": p[1], "z": p[2]} for i, p in enumerate(xyz)],
            )
        ],
        notes=[
            "Survey coordinates are stored in project-grid millimetres; elevations are offset by the stated survey datum."
        ],
    )


@feature(
    "studiesSite.createSurface",
    "Create Surface",
    part="soil",
    fields=[
        text(
            "points",
            "Point triples x,y,z in project mm",
            "0,0,0\n10000,0,100\n10000,10000,250\n0,10000,50\n5000,5000,150",
        )
    ],
)
def create_surface(ctx: FeatureContext, values: dict) -> dict:
    """Create a Delaunay TIN from project-grid survey points."""
    xyz, triangles = _surface(
        ctx, points(values["points"], "surface points"), "TIN created by Delaunay triangulation."
    )
    return result(
        summary={
            "pointCount": len(xyz),
            "triangleCount": len(triangles),
            "surfacePath": "01 Soil Report/terrain.json",
        },
        tables=[
            table(
                "Surface faces",
                [
                    ("face", "Face"),
                    ("pointA", "Point A"),
                    ("pointB", "Point B"),
                    ("pointC", "Point C"),
                ],
                [
                    {
                        "face": i + 1,
                        "pointA": tri[0] + 1,
                        "pointB": tri[1] + 1,
                        "pointC": tri[2] + 1,
                    }
                    for i, tri in enumerate(triangles)
                ],
            )
        ],
        notes=[
            "The engine's Delaunay triangulation is applied in plan; breakline constraints are not incorporated by this operation."
        ],
    )


@feature(
    "studiesSite.editSurface",
    "Edit Surface",
    part="soil",
    fields=[
        number("pointIndex", "One-based point index", 1, min=1),
        number("dx", "X adjustment", 0, unit="mm"),
        number("dy", "Y adjustment", 0, unit="mm"),
        number("dz", "Elevation adjustment", 0, unit="mm"),
    ],
)
def edit_surface(ctx: FeatureContext, values: dict) -> dict:
    """Move one stored survey point and retriangulate the edited terrain surface."""
    terrain = _terrain(ctx)
    index = int(values["pointIndex"]) - 1
    if not 0 <= index < len(terrain.points):
        raise FeatureInputError("The requested point index is outside the stored terrain.")
    pts = [tuple(float(v) for v in p) for p in terrain.points]
    x, y, z = pts[index]
    pts[index] = (x + values["dx"], y + values["dy"], z + values["dz"])
    xyz, triangles = _surface(
        ctx, pts, f"Point {index + 1} adjusted and the surface retriangulated."
    )
    return result(
        summary={"editedPoint": index + 1, "pointCount": len(xyz), "triangleCount": len(triangles)},
        notes=[
            "The source terrain file is updated after retriangulation; an exported copy should be retained before editing if a prior surface must be preserved."
        ],
    )


@feature(
    "studiesSite.contours",
    "Contours",
    part="soil",
    fields=[
        number("interval", "Contour interval", 1000, unit="mm", min=1),
        number("base", "Contour datum", 0, unit="mm"),
    ],
)
def contours(ctx: FeatureContext, values: dict) -> dict:
    """Extract terrain contour crossing segments from each triangular face at a fixed interval."""
    terrain = _terrain(ctx)
    import numpy as np

    pts = np.asarray(terrain.points, dtype=float)
    low, high = float(pts[:, 2].min()), float(pts[:, 2].max())
    start = (
        math.ceil((low - values["base"]) / values["interval"]) * values["interval"] + values["base"]
    )
    rows = []
    for level in range(int(start), int(high) + 1, int(values["interval"])):
        for face, tri in enumerate(terrain.triangles, 1):
            corners = [pts[i] for i in tri]
            crossings = []
            for a, b in ((0, 1), (1, 2), (2, 0)):
                z1, z2 = corners[a][2], corners[b][2]
                if min(z1, z2) <= level <= max(z1, z2) and z1 != z2:
                    ratio = (level - z1) / (z2 - z1)
                    point = [
                        corners[a][j] + ratio * (corners[b][j] - corners[a][j]) for j in range(2)
                    ]
                    if not any(math.dist(point, p) < 1e-6 for p in crossings):
                        crossings.append(point)
            if len(crossings) == 2:
                rows.append(
                    {
                        "elevation": level,
                        "face": face,
                        "x1": crossings[0][0],
                        "y1": crossings[0][1],
                        "x2": crossings[1][0],
                        "y2": crossings[1][1],
                    }
                )
    return result(
        summary={
            "contourSegmentCount": len(rows),
            "contourLevels": len({row["elevation"] for row in rows}),
        },
        tables=[
            table(
                "TIN contour segments",
                [
                    ("elevation", "Elevation", "mm"),
                    ("face", "Source face"),
                    ("x1", "Start X", "mm"),
                    ("y1", "Start Y", "mm"),
                    ("x2", "End X", "mm"),
                    ("y2", "End Y", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Contours are linear intersections with each planar TIN triangle; adjacent segments have not been stitched into polylines."
        ],
    )


@feature(
    "studiesSite.cutFill",
    "Cut Fill",
    part="soil",
    fields=[
        text("outline", "Platform polygon x,y in mm", "0,0\n10000,0\n10000,10000\n0,10000"),
        number("platformLevel", "Platform elevation", 100, unit="mm"),
    ],
)
def cut_fill(ctx: FeatureContext, values: dict) -> dict:
    """Integrate cut and fill against a platform level over a supplied polygon."""
    terrain = _terrain(ctx)
    import numpy as np
    from shapely.geometry import Polygon

    from saengine.gis.terrain import cut_fill as integrate

    ring = [
        tuple(nums[:2])
        for line in values["outline"].splitlines()
        if (nums := [float(v) for v in line.replace(",", " ").split()]) and len(nums) >= 2
    ]
    if len(ring) < 3:
        raise FeatureInputError("The platform outline needs at least three x,y points.")
    balance = integrate(
        np.asarray(terrain.points, dtype=float),
        np.asarray(terrain.triangles, dtype=int),
        Polygon(ring),
        values["platformLevel"],
    )
    return result(
        summary={
            "cutVolumeM3": balance["cut"],
            "fillVolumeM3": balance["fill"],
            "netImportM3": balance["fill"] - balance["cut"],
            "platformAreaM2": balance["area"],
            "uncoveredAreaM2": balance["uncovered"],
        },
        notes=[
            "Uses exact planar TIN clipping against the platform polygon; side slopes, shrinkage, bulking and unsuitable material are excluded."
        ],
    )


@feature(
    "studiesSite.volumeBalance",
    "Volume Balance",
    part="soil",
    fields=[
        number("cutVolume", "Bank cut volume", 1200, unit="m³", min=0),
        number("fillVolume", "Compacted fill volume", 900, unit="m³", min=0),
        number("cutBulking", "Cut bulking factor", 1.15, min=0.1),
        number("fillCompaction", "Fill compaction factor", 0.9, min=0.1),
    ],
)
def volume_balance(ctx: FeatureContext, values: dict) -> dict:
    """Balance excavated swell volume against compacted fill demand using declared factors."""
    available = values["cutVolume"] * values["cutBulking"]
    required = values["fillVolume"] / values["fillCompaction"]
    return result(
        summary={
            "availableLooseM3": available,
            "requiredLooseEquivalentM3": required,
            "surplusM3": available - required,
            "netImportM3": max(0, required - available),
        },
        tables=[
            table(
                "Earthwork balance",
                [("quantity", "Quantity"), ("volume", "Volume", "m³")],
                [
                    {"quantity": "Cut after bulking", "volume": available},
                    {"quantity": "Fill demand equivalent", "volume": required},
                ],
            )
        ],
        notes=[
            "Cut bulking and fill compaction are user-supplied conversion factors; haul losses and unsuitable excavation are excluded."
        ],
    )


@feature(
    "studiesSite.haulAnalysis",
    "Haul Analysis",
    part="soil",
    fields=[
        number("volume", "Loose haul volume", 1000, unit="m³", min=0),
        number("density", "Loose material density", 1.8, unit="t/m³", min=0),
        number("oneWayDistance", "One-way haul distance", 12, unit="km", min=0),
        number("payload", "Truck payload", 20, unit="t", min=0.1),
        number("rate", "Haul rate", 0.12, unit="currency/t-km", min=0),
    ],
)
def haul_analysis(ctx: FeatureContext, values: dict) -> dict:
    """Estimate haulage mass, loaded trips and distance-based transport cost."""
    mass = values["volume"] * values["density"]
    trips = math.ceil(mass / values["payload"]) if mass else 0
    tonne_km = mass * values["oneWayDistance"] * 2
    return result(
        summary={
            "haulMassTonnes": mass,
            "loadedTrips": trips,
            "roundTripTonneKm": tonne_km,
            "haulCost": tonne_km * values["rate"],
        },
        notes=[
            "The full mass is hauled loaded one way and empty on return; the rate is applied to round-trip tonne-kilometres."
        ],
    )


@feature(
    "studiesSite.siteBoundary",
    "Site Boundary",
    part="soil",
    fields=[
        text("corners", "Boundary corners x,y in project mm", "0,0\n50000,0\n48000,30000\n0,30000")
    ],
    requires_project=False,
)
def site_boundary(ctx: FeatureContext, values: dict) -> dict:
    """Calculate polygon area, perimeter and edge lengths from ordered site-boundary corners."""
    xy = [
        [float(value) for value in line.replace(",", " ").split()[:2]]
        for line in values["corners"].splitlines()
        if line.strip()
    ]
    if len(xy) < 3 or any(len(p) != 2 for p in xy):
        raise FeatureInputError("Enter at least three ordered x,y boundary corners.")
    edges = [math.dist(xy[i], xy[(i + 1) % len(xy)]) for i in range(len(xy))]
    signed = (
        sum(
            xy[i][0] * xy[(i + 1) % len(xy)][1] - xy[(i + 1) % len(xy)][0] * xy[i][1]
            for i in range(len(xy))
        )
        / 2
    )
    return result(
        summary={
            "areaM2": abs(signed) / 1e6,
            "perimeterM": sum(edges) / 1000,
            "cornerCount": len(xy),
        },
        tables=[
            table(
                "Boundary edges",
                [("edge", "Edge"), ("length", "Length", "m")],
                [{"edge": i + 1, "length": length / 1000} for i, length in enumerate(edges)],
            )
        ],
        notes=[
            "Shoelace polygon area and straight-line edge lengths; coordinates are interpreted as project-grid millimetres."
        ],
    )


@feature("studiesSite.slopeAnalysis", "Slope Analysis", part="soil", fields=[])
def slope_analysis(ctx: FeatureContext, values: dict) -> dict:
    """Calculate planar slope and aspect for each face of the project's terrain TIN."""
    import numpy as np

    terrain = _terrain(ctx)
    pts = np.asarray(terrain.points, dtype=float)
    rows = []
    for number_, tri in enumerate(terrain.triangles, 1):
        a, b, c = pts[tri]
        ux, uy, uz = b - a
        vx, vy, vz = c - a
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        slope = math.degrees(math.atan2(math.hypot(nx, ny), abs(nz)))
        aspect = math.degrees(math.atan2(-nx, -ny)) % 360 if math.hypot(nx, ny) else 0
        rows.append({"face": number_, "slopeDegrees": slope, "aspectDegrees": aspect})
    return result(
        summary={
            "faceCount": len(rows),
            "meanSlopeDegrees": sum(row["slopeDegrees"] for row in rows) / len(rows),
            "maximumSlopeDegrees": max(row["slopeDegrees"] for row in rows),
        },
        tables=[
            table(
                "Terrain face slopes",
                [
                    ("face", "Face"),
                    ("slopeDegrees", "Slope", "°"),
                    ("aspectDegrees", "Aspect", "°"),
                ],
                rows,
            )
        ],
        notes=[
            "Slope is the angle of each planar triangle above horizontal; aspect is its downhill bearing clockwise from north."
        ],
    )


@feature(
    "studiesSite.drainage",
    "Drainage",
    part="soil",
    fields=[
        text("outlet", "Outlet x,y in project mm", "5000,5000"),
        number("designRainfall", "Design rainfall intensity", 75, unit="mm/h", min=0),
        number("catchmentArea", "Catchment area", 0.5, unit="ha", min=0),
    ],
)
def drainage(ctx: FeatureContext, values: dict) -> dict:
    """Estimate rational-method runoff and report the selected outlet coordinates."""
    outlet = numbers(values["outlet"], "outlet coordinates")
    if len(outlet) != 2:
        raise FeatureInputError("The outlet needs exactly two coordinates, x and y.")
    flow = 0.00278 * values["designRainfall"] * values["catchmentArea"]
    return result(
        summary={"outletXmm": outlet[0], "outletYmm": outlet[1], "peakFlowM3PerS": flow},
        notes=[
            "Rational method Q = 0.00278 C i A with implicit runoff coefficient C = 1; specify a locally justified coefficient in the catchment model before sizing drainage."
        ],
    )


@feature(
    "studiesSite.surfacePoints",
    "Surface Points",
    part="soil",
    fields=[
        number("spacing", "Grid spacing", 5000, unit="mm", min=1),
        number("maximumPoints", "Maximum points", 200, min=1, max=10000),
    ],
)
def surface_points(ctx: FeatureContext, values: dict) -> dict:
    """Sample the TIN on a regular plan grid and report interpolated surface elevations."""
    import numpy as np

    from saengine.gis.terrain import elevation_at

    terrain = _terrain(ctx)
    pts = np.asarray(terrain.points, dtype=float)
    x0, y0 = pts[:, :2].min(axis=0)
    x1, y1 = pts[:, :2].max(axis=0)
    rows = []
    x = x0
    while x <= x1 + 1e-9:
        y = y0
        while y <= y1 + 1e-9 and len(rows) < int(values["maximumPoints"]):
            z = elevation_at(pts, terrain.triangles, float(x), float(y))
            if z is not None:
                rows.append({"x": float(x), "y": float(y), "z": z})
            y += values["spacing"]
        if len(rows) >= int(values["maximumPoints"]):
            break
        x += values["spacing"]
    return result(
        summary={"sampleCount": len(rows), "gridSpacingMm": values["spacing"]},
        tables=[
            table(
                "Interpolated surface points",
                [("x", "X", "mm"), ("y", "Y", "mm"), ("z", "Elevation", "mm")],
                rows,
            )
        ],
        notes=[
            "TIN barycentric interpolation on a regular grid; points outside the triangulated convex hull are omitted."
        ],
    )


@feature(
    "studiesSite.breaklines",
    "Breaklines",
    part="soil",
    fields=[text("vertices", "Breakline vertices x,y,z in mm", "0,0,0\n5000,0,100\n10000,0,150")],
    requires_project=False,
)
def breaklines(ctx: FeatureContext, values: dict) -> dict:
    """Measure breakline segments and report the grade between each pair of survey vertices."""
    pts = points(values["vertices"], "breakline vertices")
    rows = []
    for i, (a, b) in enumerate(itertools.pairwise(pts), 1):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        rows.append(
            {
                "segment": i,
                "lengthM": length / 1000,
                "riseMm": b[2] - a[2],
                "gradePercent": 100 * (b[2] - a[2]) / length if length else 0,
            }
        )
    return result(
        summary={
            "vertexCount": len(pts),
            "segmentCount": len(rows),
            "lengthM": sum(row["lengthM"] for row in rows),
        },
        tables=[
            table(
                "Breakline segments",
                [
                    ("segment", "Segment"),
                    ("lengthM", "Plan length", "m"),
                    ("riseMm", "Rise", "mm"),
                    ("gradePercent", "Grade", "%"),
                ],
                rows,
            )
        ],
        notes=[
            "Segments follow the supplied vertex order; values are suitable as breakline geometry records for the terrain model."
        ],
    )


@feature(
    "studiesSite.surfaceBoundaries",
    "Surface Boundaries",
    part="soil",
    fields=[text("boundary", "Boundary vertices x,y in mm", "0,0\n10000,0\n10000,8000\n0,8000")],
    requires_project=False,
)
def surface_boundaries(ctx: FeatureContext, values: dict) -> dict:
    """Check closure and calculate plan area, perimeter and edge lengths for a surface ring."""
    xy = [
        [float(v) for v in line.replace(",", " ").split()[:2]]
        for line in values["boundary"].splitlines()
        if line.strip()
    ]
    if len(xy) < 3 or any(len(p) != 2 for p in xy):
        raise FeatureInputError("A boundary needs at least three x,y vertices.")
    edge_lengths = [math.dist(p, xy[(i + 1) % len(xy)]) / 1000 for i, p in enumerate(xy)]
    area = (
        abs(
            sum(
                xy[i][0] * xy[(i + 1) % len(xy)][1] - xy[(i + 1) % len(xy)][0] * xy[i][1]
                for i in range(len(xy))
            )
            / 2
        )
        / 1e6
    )
    return result(
        summary={
            "closed": True,
            "areaM2": area,
            "perimeterM": sum(edge_lengths),
            "vertexCount": len(xy),
        },
        tables=[
            table(
                "Boundary edges",
                [("edge", "Edge"), ("lengthM", "Length", "m")],
                [{"edge": i + 1, "lengthM": length} for i, length in enumerate(edge_lengths)],
            )
        ],
        notes=[
            "The final point is implicitly connected back to the first to close the polygon ring."
        ],
    )


@feature(
    "studiesSite.surfaceSmoothing",
    "Surface Smoothing",
    part="soil",
    fields=[
        number("neighbours", "Plan-nearest neighbours", 4, min=1, max=20),
        number("weight", "Neighbour blend fraction", 0.25, min=0, max=1),
    ],
)
def surface_smoothing(ctx: FeatureContext, values: dict) -> dict:
    """Compute non-destructive smoothed elevations from the nearest plan neighbors of each TIN point."""
    terrain = _terrain(ctx)
    pts = [list(map(float, row)) for row in terrain.points]
    count = int(values["neighbours"])
    rows = []
    for i, point in enumerate(pts):
        nearest = sorted(
            (math.hypot(point[0] - other[0], point[1] - other[1]), j, other[2])
            for j, other in enumerate(pts)
            if j != i
        )[:count]
        if not nearest:
            continue
        mean = sum(item[2] for item in nearest) / len(nearest)
        smoothed = point[2] + values["weight"] * (mean - point[2])
        rows.append(
            {
                "point": i + 1,
                "originalZ": point[2],
                "smoothedZ": smoothed,
                "changeMm": smoothed - point[2],
            }
        )
    return result(
        summary={
            "pointCount": len(rows),
            "maximumAbsoluteChangeMm": max(abs(row["changeMm"]) for row in rows),
        },
        tables=[
            table(
                "Smoothed elevations",
                [
                    ("point", "Point"),
                    ("originalZ", "Original Z", "mm"),
                    ("smoothedZ", "Smoothed Z", "mm"),
                    ("changeMm", "Change", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "One synchronous weighted nearest-neighbor pass is reported without overwriting the survey TIN; smoothing may erase real breaks in grade."
        ],
    )


@feature(
    "studiesSite.elevationBands",
    "Elevation Bands",
    part="soil",
    fields=[number("bandSize", "Band width", 1000, unit="mm", min=1)],
)
def elevation_bands(ctx: FeatureContext, values: dict) -> dict:
    """Count stored terrain vertices and compute their mean elevation by fixed-height band."""
    terrain = _terrain(ctx)
    bands: dict[int, list[float]] = {}
    for point in terrain.points:
        index = math.floor(float(point[2]) / values["bandSize"])
        bands.setdefault(index, []).append(float(point[2]))
    rows = [
        {
            "lowerMm": index * values["bandSize"],
            "upperMm": (index + 1) * values["bandSize"],
            "pointCount": len(zs),
            "meanElevationMm": sum(zs) / len(zs),
        }
        for index, zs in sorted(bands.items())
    ]
    return result(
        summary={"bandCount": len(rows), "pointCount": sum(row["pointCount"] for row in rows)},
        tables=[
            table(
                "Elevation band counts",
                [
                    ("lowerMm", "Lower elevation", "mm"),
                    ("upperMm", "Upper elevation", "mm"),
                    ("pointCount", "Points"),
                    ("meanElevationMm", "Mean elevation", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Bands are assigned by floor(z / bandSize); counts describe vertices, not area-weighted terrain coverage."
        ],
    )


@feature(
    "studiesSite.slopeMap",
    "Slope Map",
    part="soil",
    fields=[
        number("low", "Low slope threshold", 5, unit="°", min=0, max=90),
        number("high", "High slope threshold", 15, unit="°", min=0, max=90),
    ],
)
def slope_map(ctx: FeatureContext, values: dict) -> dict:
    """Classify TIN triangle slopes into low, moderate and high map bands."""
    if values["high"] < values["low"]:
        raise FeatureInputError("The high slope threshold must not be below the low threshold.")
    import numpy as np

    terrain = _terrain(ctx)
    pts = np.asarray(terrain.points, dtype=float)
    rows = []
    for face, tri in enumerate(terrain.triangles, 1):
        a, b, c = pts[tri]
        cross = np.cross(b - a, c - a)
        slope = math.degrees(math.atan2(math.hypot(cross[0], cross[1]), abs(cross[2])))
        area = abs(cross[2]) / 2e6
        category = (
            "low" if slope < values["low"] else "moderate" if slope < values["high"] else "high"
        )
        rows.append({"face": face, "slopeDegrees": slope, "planAreaM2": area, "class": category})
    return result(
        summary={
            "lowAreaM2": sum(r["planAreaM2"] for r in rows if r["class"] == "low"),
            "moderateAreaM2": sum(r["planAreaM2"] for r in rows if r["class"] == "moderate"),
            "highAreaM2": sum(r["planAreaM2"] for r in rows if r["class"] == "high"),
        },
        tables=[
            table(
                "Slope map cells",
                [
                    ("face", "Face"),
                    ("slopeDegrees", "Slope", "°"),
                    ("planAreaM2", "Plan area", "m²"),
                    ("class", "Class"),
                ],
                rows,
            )
        ],
        notes=[
            "Slope class area is summed from horizontal triangle area, excluding edge effects outside the surveyed TIN."
        ],
    )


@feature("studiesSite.aspectMap", "Aspect Map", part="soil", fields=[])
def aspect_map(ctx: FeatureContext, values: dict) -> dict:
    """Calculate downhill aspect and face centroid coordinates for each terrain triangle."""
    import numpy as np

    terrain = _terrain(ctx)
    pts = np.asarray(terrain.points, dtype=float)
    rows = []
    for face, tri in enumerate(terrain.triangles, 1):
        a, b, c = pts[tri]
        normal = np.cross(b - a, c - a)
        aspect = (
            math.degrees(math.atan2(-normal[0], -normal[1])) % 360
            if math.hypot(normal[0], normal[1])
            else None
        )
        centre = (a + b + c) / 3
        rows.append({"face": face, "x": centre[0], "y": centre[1], "aspectDegrees": aspect})
    return result(
        summary={
            "faceCount": len(rows),
            "northFacingFaces": sum(
                r["aspectDegrees"] is not None
                and (r["aspectDegrees"] < 45 or r["aspectDegrees"] >= 315)
                for r in rows
            ),
        },
        tables=[
            table(
                "Terrain aspect map",
                [
                    ("face", "Face"),
                    ("x", "Centroid X", "mm"),
                    ("y", "Centroid Y", "mm"),
                    ("aspectDegrees", "Downhill aspect", "°"),
                ],
                rows,
            )
        ],
        notes=[
            "Aspect is the downhill bearing clockwise from north; level facets have no defined aspect."
        ],
    )


@feature(
    "studiesSite.watershed",
    "Watershed",
    part="soil",
    fields=[number("outletIndex", "One-based outlet point", 1, min=1)],
)
def watershed(ctx: FeatureContext, values: dict) -> dict:
    """Route each TIN vertex to its steepest lower plan-neighbor and count upstream contributions."""
    terrain = _terrain(ctx)
    pts = [list(map(float, row)) for row in terrain.points]
    neighbors = [set() for _ in pts]
    for tri in terrain.triangles:
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            neighbors[a].add(b)
            neighbors[b].add(a)
    downstream = [None] * len(pts)
    for i, p in enumerate(pts):
        options = [
            (p[2] - pts[j][2]) / max(math.hypot(p[0] - pts[j][0], p[1] - pts[j][1]), 1e-9)
            for j in neighbors[i]
            if pts[j][2] < p[2]
        ]
        if options:
            best_slope = max(options)
            downstream[i] = min(
                (
                    j
                    for j in neighbors[i]
                    if pts[j][2] < p[2]
                    and abs(
                        (p[2] - pts[j][2])
                        / max(math.hypot(p[0] - pts[j][0], p[1] - pts[j][1]), 1e-9)
                        - best_slope
                    )
                    < 1e-9
                ),
                key=lambda j: j,
            )
    outlet = int(values["outletIndex"]) - 1
    if not 0 <= outlet < len(pts):
        raise FeatureInputError("The selected outlet point is outside the terrain point list.")
    accum = [1.0] * len(pts)
    for i in sorted(range(len(pts)), key=lambda j: pts[j][2], reverse=True):
        if downstream[i] is not None:
            accum[downstream[i]] += accum[i]
    rows = [
        {
            "point": i + 1,
            "downstreamPoint": downstream[i] + 1 if downstream[i] is not None else None,
            "flowCount": accum[i],
            "isOutlet": i == outlet,
        }
        for i in range(len(pts))
    ]
    contributing = sum(1 for i in range(len(pts)) if i == outlet or downstream[i] == outlet)
    return result(
        summary={
            "pointCount": len(pts),
            "selectedOutlet": outlet + 1,
            "directContributors": contributing,
        },
        tables=[
            table(
                "Steepest-descent routing",
                [
                    ("point", "Point"),
                    ("downstreamPoint", "Downstream point"),
                    ("flowCount", "Accumulated vertex count"),
                    ("isOutlet", "Selected outlet"),
                ],
                rows,
            )
        ],
        notes=[
            "Vertex routing follows the steepest lower adjacent vertex on the TIN; flowCount is vertex accumulation, not a calibrated catchment area."
        ],
    )


@feature(
    "studiesSite.surfaceVolume",
    "Surface Volume",
    part="soil",
    fields=[number("referenceLevel", "Reference plane elevation", 100, unit="mm")],
)
def surface_volume(ctx: FeatureContext, values: dict) -> dict:
    """Integrate terrain volume above and below a horizontal reference plane across the convex hull."""
    terrain = _terrain(ctx)
    import numpy as np
    from shapely.geometry import MultiPoint

    from saengine.gis.terrain import cut_fill

    pts = np.asarray(terrain.points, dtype=float)
    outline = MultiPoint(pts[:, :2]).convex_hull
    volumes = cut_fill(
        pts, np.asarray(terrain.triangles, dtype=int), outline, values["referenceLevel"]
    )
    return result(
        summary={
            "abovePlaneM3": volumes["cut"],
            "belowPlaneM3": volumes["fill"],
            "surfaceAreaM2": volumes["area"],
            "uncoveredAreaM2": volumes["uncovered"],
        },
        notes=[
            "TIN planes are integrated over the survey convex hull; values above the plane are cut and values below are fill."
        ],
    )


@feature("studiesSite.terrainReport", "Terrain Report", part="soil", fields=[])
def terrain_report(ctx: FeatureContext, values: dict) -> dict:
    """Summarize coverage, elevation range and triangulation density of the stored site surface."""
    import numpy as np

    terrain = _terrain(ctx)
    pts = np.asarray(terrain.points, dtype=float)
    span = pts[:, :2].max(axis=0) - pts[:, :2].min(axis=0)
    return result(
        summary={
            "pointCount": len(pts),
            "faceCount": len(terrain.triangles),
            "elevationMinMm": float(pts[:, 2].min()),
            "elevationMaxMm": float(pts[:, 2].max()),
            "planExtentXM": float(span[0] / 1000),
            "planExtentYM": float(span[1] / 1000),
            "meanPointSpacingM": math.sqrt(span[0] * span[1] / max(len(pts), 1)) / 1000,
        },
        tables=[
            table(
                "Terrain source",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Source format", "value": terrain.source.format},
                    {"property": "Source file", "value": terrain.source.file},
                    {"property": "Horizontal units", "value": terrain.source.units},
                    {"property": "Datum", "value": terrain.source.datum},
                ],
            )
        ],
        notes=[
            "Mean point spacing is approximated as the square root of plan extent area divided by point count."
        ],
    )


@feature(
    "studiesSite.exportLandxml",
    "Export LandXML",
    part="soil",
    fields=[text("surfaceName", "Surface name", "Existing Ground")],
)
def export_landxml(ctx: FeatureContext, values: dict) -> dict:
    """Write points and TIN faces in a LandXML 1.2 surface document."""
    terrain = _terrain(ctx)
    root = ET.Element(
        "LandXML",
        version="1.2",
        language="English",
        xmlns="http://www.landxml.org/schema/LandXML-1.2",
    )
    surfaces = ET.SubElement(root, "Surfaces")
    surface = ET.SubElement(surfaces, "Surface", name=values["surfaceName"] or "Terrain")
    definition = ET.SubElement(surface, "Definition", surfType="TIN")
    pnts = ET.SubElement(definition, "Pnts")
    for index, (x, y, z) in enumerate(terrain.points, 1):
        ET.SubElement(pnts, "P", id=str(index)).text = f"{z:g} {y:g} {x:g}"
    faces = ET.SubElement(definition, "Faces")
    for tri in terrain.triangles:
        ET.SubElement(faces, "F").text = " ".join(str(i + 1) for i in tri)
    path = write_text(
        ctx, "11 Exports/terrain.xml", ET.tostring(root, encoding="unicode", xml_declaration=True)
    )
    return result(
        summary={
            "pointCount": len(terrain.points),
            "faceCount": len(terrain.triangles),
            "outputPath": path,
        },
        notes=[
            f"LandXML 1.2 surface written to {path}; project-grid coordinates are kept in millimetres."
        ],
    )


@feature(
    "studiesSite.platformLevels",
    "Platform Levels",
    part="soil",
    fields=[
        number("designLevel", "Design platform elevation", 12000, unit="mm"),
        text(
            "checkPoints",
            "Check points x,y,z in mm",
            "1000,1000,11800\n5000,5000,12100\n9000,9000,11950",
        ),
    ],
    requires_project=False,
)
def platform_levels(ctx: FeatureContext, values: dict) -> dict:
    """Compare surveyed platform check-point elevations with a nominated design level."""
    samples = points(values["checkPoints"], "platform check points")
    rows = [
        {
            "point": i + 1,
            "x": x,
            "y": y,
            "existingZ": z,
            "differenceMm": values["designLevel"] - z,
            "cutOrFill": "fill"
            if values["designLevel"] > z
            else "cut"
            if values["designLevel"] < z
            else "level",
        }
        for i, (x, y, z) in enumerate(samples)
    ]
    return result(
        summary={
            "checkCount": len(rows),
            "meanAbsoluteDifferenceMm": sum(abs(row["differenceMm"]) for row in rows) / len(rows),
            "designLevelMm": values["designLevel"],
        },
        tables=[
            table(
                "Platform level checks",
                [
                    ("point", "Point"),
                    ("x", "X", "mm"),
                    ("y", "Y", "mm"),
                    ("existingZ", "Existing elevation", "mm"),
                    ("differenceMm", "Design minus existing", "mm"),
                    ("cutOrFill", "Work"),
                ],
                rows,
            )
        ],
        notes=[
            "Positive difference indicates fill to reach the design platform; no volume interpolation between check points is performed."
        ],
    )


@feature(
    "studiesSite.stockpileVolumes",
    "Stockpile Volumes",
    part="soil",
    fields=[
        number("baseRadius", "Stockpile base radius", 8, unit="m", min=0),
        number("topRadius", "Top radius", 2, unit="m", min=0),
        number("height", "Stockpile height", 4, unit="m", min=0),
        select("shape", "Stockpile profile", [("cone", "Cone"), ("frustum", "Frustum")], "frustum"),
    ],
    requires_project=False,
)
def stockpile_volumes(ctx: FeatureContext, values: dict) -> dict:
    """Calculate conical or frustum stockpile volume from base radius, top radius and height."""
    rb, rt, height = values["baseRadius"], values["topRadius"], values["height"]
    if values["shape"] == "cone" and rt != 0:
        raise FeatureInputError(
            "A cone must have zero top radius; choose frustum for a finite top."
        )
    volume = math.pi * height * (rb**2 + rb * rt + rt**2) / 3
    return result(
        summary={
            "volumeM3": volume,
            "baseFootprintM2": math.pi * rb**2,
            "averageDepthM": volume / (math.pi * rb**2) if rb else 0,
        },
        notes=[
            "Ideal axisymmetric right cone or conical frustum; side slopes, settlement and bulking are not included."
        ],
    )


@feature(
    "studiesSite.haulRoutes",
    "Haul Routes",
    part="soil",
    fields=[
        text(
            "routes",
            "Route coordinate lists in metres",
            '[{"name":"North gate","points":[[0,0],[2,6],[14,6]]},{"name":"South gate","points":[[0,0],[0,-10],[14,-10]]}]',
        )
    ],
    requires_project=False,
)
def haul_routes(ctx: FeatureContext, values: dict) -> dict:
    """Compare polyline route lengths and report the shortest candidate haul route."""
    routes = records(values["routes"], "haul routes")
    output = []
    for route in routes:
        pts = route.get("points", [])
        if len(pts) < 2:
            raise FeatureInputError("Each haul route needs at least two coordinate points.")
        try:
            length = sum(
                math.dist((float(a[0]), float(a[1])), (float(b[0]), float(b[1])))
                for a, b in itertools.pairwise(pts)
            )
        except (IndexError, TypeError, ValueError) as error:
            raise FeatureInputError("Route coordinates must be numeric x,y pairs.") from error
        output.append(
            {"route": route.get("name", "Route"), "segmentCount": len(pts) - 1, "lengthM": length}
        )
    best = min(output, key=lambda row: row["lengthM"])
    return result(
        summary={
            "routeCount": len(output),
            "shortestRoute": best["route"],
            "shortestDistanceM": best["lengthM"],
        },
        tables=[
            table(
                "Haul route comparison",
                [("route", "Route"), ("segmentCount", "Segments"), ("lengthM", "Length", "m")],
                output,
            )
        ],
        notes=[
            "Polyline lengths are straight-plan distances; gradients, turning restrictions, traffic and operating times are not considered."
        ],
    )


@feature(
    "studiesSite.spoilAreas",
    "Spoil Areas",
    part="soil",
    fields=[
        number("volume", "Spoil volume", 500, unit="m³", min=0),
        number("depth", "Average placed depth", 1.5, unit="m", min=0.1),
        number("usableFraction", "Usable area fraction", 0.8, min=0.01, max=1),
        number("slopeAllowance", "Plan area slope allowance", 1.2, min=1, max=5),
    ],
    requires_project=False,
)
def spoil_areas(ctx: FeatureContext, values: dict) -> dict:
    """Estimate spoil placement area allowing for usable fraction and non-horizontal side slopes."""
    footprint = values["volume"] / values["depth"]
    gross = footprint * values["slopeAllowance"] / values["usableFraction"]
    return result(
        summary={
            "netFootprintM2": footprint,
            "grossAllocatedAreaM2": gross,
            "equivalentSquareSideM": math.sqrt(gross),
        },
        notes=[
            "Volume is spread at a uniform average depth; slopeAllowance and usableFraction are explicit planning factors, not geometric stability checks."
        ],
    )
