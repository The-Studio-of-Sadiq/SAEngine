"""Soil Report site, terrain, coordinate and land-boundary utilities."""

from __future__ import annotations

import itertools
import math
import zipfile
from typing import Any

from saengine.features import number, result, table, text
from saengine.features.soil_feature_utils import (
    FeatureInputError,
    common_fields,
    register_tab,
    require_report,
    result_rows,
)


def _fields(fid: str) -> list[Any]:
    if fid in {"soilSite.importDem", "soilSite.pointCloudImport"}:
        return [
            text("sourcePath", "Project-relative DEM / XYZ / DXF path", ""),
            text("units", "Horizontal and elevation units (m, mm or ft)", "m"),
            text("crs", "Source CRS (project or EPSG code)", "project"),
        ]
    if fid == "soilSite.floodDepthMap":
        return [number("waterLevelM", "Water surface elevation in project z [m]", 1.0, unit="m")]
    if fid == "soilSite.coordinateTransform":
        return [
            number("xM", "Project X [m]", 0.0, unit="m"),
            number("yM", "Project Y [m]", 0.0, unit="m"),
        ]
    if fid == "soilSite.setbacks":
        return [
            number("frontM", "Front setback [m]", 3.0, unit="m", min=0),
            number("rearM", "Rear setback [m]", 2.0, unit="m", min=0),
            number("sideM", "Side setback [m]", 1.0, unit="m", min=0),
        ]
    if fid == "soilSite.easements":
        return [
            text("easementRows", "Side index, width [m], description rows", ""),
            number("widthM", "Default easement width [m]", 2.0, unit="m", min=0),
        ]
    if fid == "soilSite.rightOfWay":
        return [
            number("roadWidthM", "Road reserve width [m]", 6.0, unit="m", min=0),
            number("setbackM", "Right-of-way offset [m]", 0.0, unit="m", min=0),
        ]
    if fid == "soilSite.contoursFromDem":
        return [number("contourIntervalM", "Contour interval [m]", 1.0, unit="m", min=0.01)]
    if fid == "soilSite.catchmentDelineation":
        return [
            number("outletXM", "Outlet X [m]", 0.0, unit="m"),
            number("outletYM", "Outlet Y [m]", 0.0, unit="m"),
        ]
    if fid == "soilSite.setCrs":
        return [text("crs", "Coordinate reference system", "EPSG:4326")]
    return common_fields(fid)


def _site(report: Any) -> Any:
    if report.site is None:
        raise FeatureInputError("Add a site record to the Soil Report first.")
    return report.site


def _terrain(ctx: Any) -> Any:
    from saengine.gis import terrain as terrain_engine

    path = ctx.path(terrain_engine.TERRAIN_FILE)
    if path is None or not path.is_file():
        raise FeatureInputError(
            "Import a DEM or terrain survey before running this terrain operation."
        )
    try:
        return terrain_engine.parse(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FeatureInputError(f"The terrain file could not be read: {error}") from error


def _polygon_area(points: list[tuple[float, float]]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2


def _d8(terrain: Any) -> tuple[dict[int, int | None], dict[int, int], float]:
    points = terrain.points
    if len(points) < 4:
        raise FeatureInputError("At least four terrain points are needed for flow routing.")
    xs = sorted({round(p[0], 2) for p in points})
    ys = sorted({round(p[1], 2) for p in points})
    dxs = [b - a for a, b in itertools.pairwise(xs) if b > a]
    dys = [b - a for a, b in itertools.pairwise(ys) if b > a]
    if not dxs or not dys:
        raise FeatureInputError(
            "The terrain needs a two-dimensional gridded DEM for D8 flow routing."
        )
    dx, dy = min(dxs), min(dys)
    lookup = {(round(p[0] / dx), round(p[1] / dy)): i for i, p in enumerate(points)}
    targets: dict[int, int | None] = {}
    accumulation = {i: 1 for i in range(len(points))}
    for i, point in enumerate(points):
        ix, iy = round(point[0] / dx), round(point[1] / dy)
        candidates = []
        for ox in (-1, 0, 1):
            for oy in (-1, 0, 1):
                if ox == oy == 0:
                    continue
                j = lookup.get((ix + ox, iy + oy))
                if j is None or points[j][2] >= point[2]:
                    continue
                distance = math.hypot(ox * dx, oy * dy)
                candidates.append(((point[2] - points[j][2]) / distance, j))
        targets[i] = max(candidates, default=(0.0, None))[1]
    for i in sorted(range(len(points)), key=lambda j: points[j][2], reverse=True):
        target = targets[i]
        if target is not None:
            accumulation[target] += accumulation[i]
    return targets, accumulation, dx * dy / 1e6


def _handle(fid: str, ctx: Any, values: dict[str, Any]) -> dict[str, Any]:
    if fid in {"soilSite.importDem", "soilSite.pointCloudImport"}:
        report = require_report(ctx)
        source_path = values["sourcePath"].strip()
        if not source_path:
            raise FeatureInputError(
                "Choose a DEM, XYZ point cloud or DXF survey path relative to the project folder."
            )
        path = ctx.path(source_path)
        if path is None or not path.is_file():
            raise FeatureInputError(
                f"Terrain survey file {source_path!r} is not present in the project."
            )
        if values["units"] not in {"m", "mm", "ft"}:
            raise FeatureInputError("Terrain units must be m, mm or ft.")
        from saengine.gis import terrain as terrain_engine

        out = terrain_engine.import_survey(
            str(ctx.root), str(path), units=values["units"], crs=values["crs"] or "project"
        )
        if out.get("problems"):
            raise FeatureInputError("; ".join(out["problems"]))
        return result(
            summary={
                "pointsCount": out["pointCount"],
                "trianglesCount": out["triangleCount"],
                "terrainPath": out["path"],
                "cutM3": out.get("terrain", {}).get("cut"),
                "fillM3": out.get("terrain", {}).get("fill"),
            },
            notes=[f"Terrain surface written to {out['path']}.", *out.get("notes", [])],
        )
    if fid == "soilSite.setCrs":
        crs = values["crs"].strip()
        try:
            from pyproj import CRS

            parsed = CRS.from_user_input(crs)
        except Exception as error:
            raise FeatureInputError(
                f"Coordinate reference system {crs!r} is not recognized: {error}"
            ) from error
        return result(
            summary={
                "crs": crs,
                "authority": parsed.to_authority()[0] if parsed.to_authority() else None,
                "code": parsed.to_authority()[1] if parsed.to_authority() else None,
            },
            tables=[
                table(
                    "Coordinate reference system",
                    [("property", "Property"), ("value", "Value")],
                    [
                        {"property": "Input", "value": crs},
                        {"property": "Name", "value": parsed.name},
                        {"property": "Axis count", "value": len(parsed.axis_info)},
                    ],
                )
            ],
            notes=[
                "This checks a CRS identifier; it does not reproject stored borehole or terrain coordinates."
            ],
        )

    report = require_report(ctx)
    site = _site(report)
    if fid in {"soilSite.basemap", "soilSite.floodZone"}:
        if not site.georeferenced:
            raise FeatureInputError(
                "Set the site latitude and longitude to position the site on a geographic map."
            )
        if fid == "soilSite.basemap":
            from saengine.gis.crs import Grid

            grid = Grid(site)
            coords = [grid.to_wgs84(bh.x, bh.y) for bh in report.boreholes]
            lats = [site.lat, *(lat for lat, _ in coords)]
            lons = [site.lon, *(lon for _, lon in coords)]
            return result(
                summary={
                    "latitudeDeg": site.lat,
                    "longitudeDeg": site.lon,
                    "rotationDeg": site.rotation,
                    "boreholesCount": len(coords),
                },
                tables=[
                    table(
                        "Map extent",
                        [
                            ("bound", "Boundary"),
                            ("latitudeDeg", "Latitude", "°"),
                            ("longitudeDeg", "Longitude", "°"),
                        ],
                        [
                            {
                                "bound": "minimum",
                                "latitudeDeg": min(lats),
                                "longitudeDeg": min(lons),
                            },
                            {"bound": "site", "latitudeDeg": site.lat, "longitudeDeg": site.lon},
                            {
                                "bound": "maximum",
                                "latitudeDeg": max(lats),
                                "longitudeDeg": max(lons),
                            },
                        ],
                    )
                ],
                notes=[
                    "This returns the geographic extent and features needed by a basemap view; raster map tiles are not downloaded."
                ],
            )
        settings_path = ctx.path("02 Project Settings/project-settings.json")
        settings_text = (
            settings_path.read_text(encoding="utf-8")
            if settings_path and settings_path.is_file()
            else None
        )
        soil_path = ctx.path("01 Soil Report/soil-report.json")
        soil_text = (
            soil_path.read_text(encoding="utf-8") if soil_path and soil_path.is_file() else None
        )
        from saengine.gis import hazard_lookup

        offer = hazard_lookup.offers(settings_text, soil_text, str(ctx.root))
        rows = [
            {
                "service": item.get("service"),
                "provider": item.get("publisher"),
                "target": ", ".join(item.get("targets", [])),
                "problem": item.get("problem"),
                "query": item.get("query"),
            }
            for item in offer.get("providers", [])
        ]
        return result(
            summary={
                "providersCount": len(rows),
                "coordinatesAvailable": offer.get("coordinates") is not None,
            },
            tables=[
                table(
                    "Flood-hazard lookup options",
                    [
                        ("service", "Service"),
                        ("provider", "Publisher"),
                        ("target", "Available hazard values"),
                        ("problem", "Coverage"),
                        ("query", "Request preview"),
                    ],
                    rows,
                )
            ],
            notes=[
                offer.get("manualNote")
                or "Only provider query options are listed; this feature does not send a network request or assign an unverified flood zone."
            ],
        )
    if fid == "soilSite.coordinateTransform":
        if not site.georeferenced:
            raise FeatureInputError(
                "A site latitude and longitude are needed to transform project coordinates."
            )
        from saengine.gis.crs import Grid

        lat, lon = Grid(site).to_wgs84(values["xM"] * 1000, values["yM"] * 1000)
        easting, northing = Grid(site).to_btm(values["xM"] * 1000, values["yM"] * 1000)
        return result(
            summary={
                "latitudeDeg": lat,
                "longitudeDeg": lon,
                "btmEastingM": easting,
                "btmNorthingM": northing,
            },
            tables=[
                table(
                    "Coordinate transformation",
                    [
                        ("system", "Coordinate system"),
                        ("x", "X / longitude"),
                        ("y", "Y / latitude"),
                    ],
                    [
                        {"system": "Project grid [m]", "x": values["xM"], "y": values["yM"]},
                        {"system": "WGS 84 [°]", "x": lon, "y": lat},
                        {"system": "BTM [m]", "x": easting, "y": northing},
                    ],
                )
            ],
            notes=[
                "The project grid is placed using the site's WGS 84 origin and rotation; BTM conversion uses EPSG:9678."
            ],
        )
    if fid == "soilSite.plotBoundaries":
        from saengine.gis.crs import Grid

        if site.boundary:
            grid = Grid(site) if site.georeferenced else None
            points = [grid.from_wgs84(lat, lon) for lon, lat in site.boundary] if grid else []
        elif site.plot and site.plot.points:
            points = [tuple(p) for p in site.plot.points]
        else:
            raise FeatureInputError(
                "Draw a site boundary or plot corners before checking the boundary geometry."
            )
        points_m = [(p[0] / 1000, p[1] / 1000) for p in points]
        area = _polygon_area(points_m)
        perimeter = sum(math.dist(a, b) for a, b in zip(points_m, points_m[1:] + points_m[:1]))
        rows = [
            {
                "corner": i + 1,
                "xM": x,
                "yM": y,
                "segmentToNextM": math.dist((x, y), points_m[(i + 1) % len(points_m)]),
            }
            for i, (x, y) in enumerate(points_m)
        ]
        return result(
            summary={"areaM2": area, "perimeterM": perimeter, "cornersCount": len(points_m)},
            tables=[
                table(
                    "Site boundary vertices",
                    [
                        ("corner", "Corner"),
                        ("xM", "Project X", "m"),
                        ("yM", "Project Y", "m"),
                        ("segmentToNextM", "Length to next", "m"),
                    ],
                    rows,
                )
            ],
            notes=[
                "Polygon area and perimeter are calculated in the local project grid after converting the WGS 84 boundary when needed."
            ],
        )
    if fid in {
        "soilSite.setbacks",
        "soilSite.easements",
        "soilSite.rightOfWay",
        "soilSite.landUseMap",
    }:
        from saengine.gis.crs import Grid

        if site.boundary:
            grid = Grid(site) if site.georeferenced else None
            points = [grid.from_wgs84(lat, lon) for lon, lat in site.boundary] if grid else []
        elif site.plot and site.plot.points:
            points = [tuple(p) for p in site.plot.points]
        else:
            raise FeatureInputError(
                "Set site boundary or plot corners before evaluating plot-side constraints."
            )
        if fid == "soilSite.easements":
            lines = [line.strip() for line in values["easementRows"].splitlines() if line.strip()]
            if not lines:
                raise FeatureInputError(
                    "Enter easement rows as side index, width in metres, description."
                )
            rows = []
            for line_no, line in enumerate(lines, 1):
                parts = [part.strip() for part in line.split(",", 2)]
                if len(parts) < 2:
                    raise FeatureInputError(f"Easement row {line_no} needs side index and width.")
                try:
                    index, width = int(parts[0]), float(parts[1])
                except ValueError:
                    raise FeatureInputError(
                        f"Easement row {line_no} has invalid numeric values."
                    ) from None
                if not 0 <= index < len(points) or width < 0:
                    raise FeatureInputError(
                        f"Easement row {line_no} has an invalid side index or negative width."
                    )
                a, b = points[index], points[(index + 1) % len(points)]
                length = math.dist(a, b) / 1000
                rows.append(
                    {
                        "sideIndex": index,
                        "description": parts[2] if len(parts) > 2 else "easement",
                        "widthM": width,
                        "lengthM": length,
                        "stripAreaM2": width * length,
                    }
                )
            return result_rows(
                "Easement side register",
                [
                    ("sideIndex", "Side"),
                    ("description", "Description"),
                    ("widthM", "Width", "m"),
                    ("lengthM", "Side length", "m"),
                    ("stripAreaM2", "Approximate strip area", "m²"),
                ],
                rows,
                summary={
                    "easementsCount": len(rows),
                    "approximateAreaM2": sum(row["stripAreaM2"] for row in rows),
                },
                notes=[
                    "Strip areas are side length × width; corner overlaps are not subtracted and legal easement geometry must be surveyed."
                ],
            )
        side_rows = []
        for i, a in enumerate(points):
            b = points[(i + 1) % len(points)]
            length = math.dist(a, b) / 1000
            if fid == "soilSite.setbacks":
                if site.plot:
                    setback = (
                        site.plot.front
                        if i == site.plot.road
                        else site.plot.rear
                        if site.plot.road is not None
                        and i == (site.plot.road + len(points) // 2) % len(points)
                        else site.plot.side
                    ) / 1000
                    source = "project plot setting"
                else:
                    setback = (
                        values["frontM"]
                        if i == 0
                        else values["rearM"]
                        if i == len(points) // 2
                        else values["sideM"]
                    )
                    source = "entered screening distance"
                side_rows.append(
                    {
                        "sideIndex": i,
                        "lengthM": length,
                        "setbackM": setback,
                        "approximateOffsetAreaM2": length * setback,
                        "source": source,
                    }
                )
            elif fid == "soilSite.rightOfWay":
                is_front = site.plot is not None and site.plot.road == i
                if is_front:
                    side_rows.append(
                        {
                            "sideIndex": i,
                            "frontageM": length,
                            "roadWidthM": values["roadWidthM"],
                            "offsetM": values["setbackM"],
                            "reserveAreaM2": length
                            * (values["roadWidthM"] / 2 + values["setbackM"]),
                        }
                    )
            else:
                use = site.plot.planning.use if site.plot and site.plot.planning else "unspecified"
                side_rows.append(
                    {
                        "sideIndex": i,
                        "lengthM": length,
                        "landUse": use,
                        "boundaryType": "site / plot boundary",
                    }
                )
        if fid == "soilSite.rightOfWay" and not side_rows:
            side_rows = [
                {
                    "sideIndex": i,
                    "frontageM": math.dist(points[i], points[(i + 1) % len(points)]) / 1000,
                    "roadWidthM": values["roadWidthM"],
                    "offsetM": values["setbackM"],
                    "reserveAreaM2": math.dist(points[i], points[(i + 1) % len(points)])
                    / 1000
                    * (values["roadWidthM"] / 2 + values["setbackM"]),
                }
                for i in range(len(points))
            ]
        if fid == "soilSite.setbacks":
            return result_rows(
                "Plot setbacks by side",
                [
                    ("sideIndex", "Side"),
                    ("lengthM", "Length", "m"),
                    ("setbackM", "Setback", "m"),
                    ("approximateOffsetAreaM2", "Offset strip area", "m²"),
                    ("source", "Source"),
                ],
                side_rows,
                summary={
                    "sidesCount": len(side_rows),
                    "approximateOffsetAreaM2": sum(
                        row["approximateOffsetAreaM2"] for row in side_rows
                    ),
                },
                notes=[
                    "The side lengths use the site polygon; offset strip area does not account for corner overlap and is not a buildable-envelope polygon."
                ],
            )
        if fid == "soilSite.rightOfWay":
            return result_rows(
                "Right-of-way frontage",
                [
                    ("sideIndex", "Side"),
                    ("frontageM", "Frontage", "m"),
                    ("roadWidthM", "Road reserve width", "m"),
                    ("offsetM", "Additional offset", "m"),
                    ("reserveAreaM2", "Approximate reserve area", "m²"),
                ],
                side_rows,
                summary={
                    "frontageSidesCount": len(side_rows),
                    "approximateReserveAreaM2": sum(row["reserveAreaM2"] for row in side_rows),
                },
                notes=[
                    "This is a geometric screening strip from the entered road reserve width and offset; confirm the legal right-of-way with the survey and authority plan."
                ],
            )
        return result_rows(
            "Land-use boundary nodes",
            [
                ("sideIndex", "Side"),
                ("lengthM", "Length", "m"),
                ("landUse", "Recorded land use"),
                ("boundaryType", "Boundary"),
            ],
            side_rows,
            summary={
                "boundarySidesCount": len(side_rows),
                "recordedLandUse": side_rows[0]["landUse"] if side_rows else "unspecified",
            },
            notes=[
                "The Soil Report stores site use only when supplied in the plot planning record; no external land-use map is downloaded."
            ],
        )
    if fid in {"soilSite.exportKmz"}:
        if not site.georeferenced:
            raise FeatureInputError(
                "A georeferenced site is required to export map features to KMZ."
            )
        from saengine.gis.crs import Grid

        grid = Grid(site)
        parts = [
            f"<Placemark><name>{bh.id}</name><Point><coordinates>{grid.to_wgs84(bh.x, bh.y)[1]:.8f},{grid.to_wgs84(bh.x, bh.y)[0]:.8f},0</coordinates></Point></Placemark>"
            for bh in report.boreholes
        ]
        if site.boundary:
            ring = " ".join(f"{lon:.8f},{lat:.8f},0" for lon, lat in site.boundary)
            parts.append(
                f"<Placemark><name>Site boundary</name><Polygon><outerBoundaryIs><LinearRing><coordinates>{ring}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"
            )
        kml = (
            '<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            + "".join(parts)
            + "</Document></kml>"
        )
        path = ctx.path("01 Soil Report/exports/site.kmz")
        if path is None:
            raise FeatureInputError("Open a project before exporting a KMZ.")
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("doc.kml", kml)
        return result(
            summary={"boreholesCount": len(report.boreholes), "exportPath": str(path.resolve())},
            notes=[
                f"KMZ written to {path.resolve()}.",
                "Contains the site boundary and borehole placemarks in WGS 84.",
            ],
        )
    if fid in {
        "soilSite.contoursFromDem",
        "soilSite.slopeMap",
        "soilSite.floodDepthMap",
        "soilSite.flowAccumulation",
        "soilSite.catchmentDelineation",
    }:
        terrain = _terrain(ctx)
        points = terrain.points
        if not points:
            raise FeatureInputError("The terrain model contains no elevation points.")
        if fid == "soilSite.contoursFromDem":
            interval = values["contourIntervalM"] * 1000
            rows = [
                {
                    "xM": p[0] / 1000,
                    "yM": p[1] / 1000,
                    "elevationM": p[2] / 1000,
                    "contourM": round(round(p[2] / interval) * interval / 1000, 4),
                }
                for p in points
            ]
            return result_rows(
                "Terrain contour nodes",
                [
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("elevationM", "Elevation", "m"),
                    ("contourM", "Nearest contour", "m"),
                ],
                rows,
                summary={"terrainNodesCount": len(rows), "contourIntervalM": interval / 1000},
                notes=[
                    "Each terrain sample is assigned to its nearest elevation contour; nodes are the data behind the contour view."
                ],
            )
        if fid == "soilSite.slopeMap":
            import numpy as np

            slopes = []
            for i, tri in enumerate(terrain.triangles):
                a, b, c = (np.asarray(points[j], dtype=float) for j in tri)
                normal = np.cross(b - a, c - a)
                horizontal = math.hypot(float(normal[0]), float(normal[1]))
                angle = math.degrees(math.atan2(horizontal, abs(float(normal[2]))))
                slopes.append(
                    {
                        "triangle": i + 1,
                        "slopeDeg": angle,
                        "slopePct": math.tan(math.radians(angle)) * 100,
                        "centroidXM": (a[0] + b[0] + c[0]) / 3000,
                        "centroidYM": (a[1] + b[1] + c[1]) / 3000,
                    }
                )
            if not slopes:
                raise FeatureInputError("The terrain model has no triangulated faces.")
            return result_rows(
                "Terrain slope triangles",
                [
                    ("triangle", "Triangle"),
                    ("centroidXM", "Centroid X", "m"),
                    ("centroidYM", "Centroid Y", "m"),
                    ("slopeDeg", "Slope", "°"),
                    ("slopePct", "Slope", "%"),
                ],
                slopes,
                summary={
                    "trianglesCount": len(slopes),
                    "maximumSlopeDeg": max(row["slopeDeg"] for row in slopes),
                    "meanSlopeDeg": sum(row["slopeDeg"] for row in slopes) / len(slopes),
                },
                notes=["Slope is derived from the plane normal of each terrain triangle."],
            )
        if fid == "soilSite.floodDepthMap":
            rows = [
                {
                    "xM": p[0] / 1000,
                    "yM": p[1] / 1000,
                    "groundElevationM": p[2] / 1000,
                    "waterLevelM": values["waterLevelM"],
                    "depthM": max(0.0, values["waterLevelM"] - p[2] / 1000),
                }
                for p in points
            ]
            return result_rows(
                "Flood depth terrain nodes",
                [
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("groundElevationM", "Ground", "m"),
                    ("waterLevelM", "Water level", "m"),
                    ("depthM", "Depth", "m"),
                ],
                rows,
                summary={
                    "nodesCount": len(rows),
                    "maximumFloodDepthM": max(row["depthM"] for row in rows),
                    "waterLevelM": values["waterLevelM"],
                },
                notes=[
                    "Depth = max(0, entered water-surface elevation − terrain elevation); flow, barriers, drainage and flood return period are not modelled."
                ],
            )
        targets, accumulation, cell_area = _d8(terrain)
        rows = [
            {
                "xM": points[i][0] / 1000,
                "yM": points[i][1] / 1000,
                "elevationM": points[i][2] / 1000,
                "downstreamIndex": targets[i],
                "upstreamCells": accumulation[i],
                "contributingAreaM2": accumulation[i] * cell_area,
            }
            for i in range(len(points))
        ]
        if fid == "soilSite.flowAccumulation":
            return result_rows(
                "D8 flow accumulation nodes",
                [
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("elevationM", "Elevation", "m"),
                    ("downstreamIndex", "Downstream node"),
                    ("upstreamCells", "Contributing cells"),
                    ("contributingAreaM2", "Contributing area", "m²"),
                ],
                rows,
                summary={
                    "nodesCount": len(rows),
                    "maximumContributingAreaM2": max(row["contributingAreaM2"] for row in rows),
                    "cellAreaM2": cell_area,
                },
                notes=[
                    "D8 routes each grid cell to its steepest downslope neighbor; the regular-grid assumption must be checked against the DEM resolution."
                ],
            )
        outlet = min(
            range(len(points)),
            key=lambda i: math.hypot(
                points[i][0] / 1000 - values["outletXM"], points[i][1] / 1000 - values["outletYM"]
            ),
        )
        catchment = []
        for i in range(len(points)):
            j = i
            for _ in range(len(points)):
                if j == outlet or targets[j] is None:
                    break
                j = targets[j]
            if j == outlet:
                catchment.append(i)
        selected = [rows[i] for i in catchment]
        return result_rows(
            "D8 catchment cells",
            [
                ("xM", "X", "m"),
                ("yM", "Y", "m"),
                ("elevationM", "Elevation", "m"),
                ("contributingAreaM2", "Contributing area", "m²"),
            ],
            selected,
            summary={
                "outletXM": points[outlet][0] / 1000,
                "outletYM": points[outlet][1] / 1000,
                "catchmentCellsCount": len(selected),
                "catchmentAreaM2": len(selected) * cell_area,
            },
            notes=[
                "Catchment membership follows D8 flow paths to the nearest DEM cell to the entered outlet; flat cells and sinks do not receive a depression-filling treatment."
            ],
        )
    if fid == "soilSite.elevationCheck":
        terrain = _terrain(ctx)
        from saengine.gis.terrain import elevation_at

        rows = []
        for bh in report.boreholes:
            model_z = elevation_at(terrain.points, terrain.triangles, bh.x, bh.y)
            if model_z is None:
                rows.append(
                    {
                        "borehole": bh.id,
                        "surveyGroundM": report.ground_level(bh) / 1000,
                        "terrainGroundM": None,
                        "differenceM": None,
                        "status": "outside terrain coverage",
                    }
                )
            else:
                difference = (report.ground_level(bh) - model_z) / 1000
                rows.append(
                    {
                        "borehole": bh.id,
                        "surveyGroundM": report.ground_level(bh) / 1000,
                        "terrainGroundM": model_z / 1000,
                        "differenceM": difference,
                        "status": "review" if abs(difference) > 0.5 else "within 0.5 m",
                    }
                )
        return result_rows(
            "Borehole ground-elevation check",
            [
                ("borehole", "Borehole"),
                ("surveyGroundM", "Borehole ground", "m"),
                ("terrainGroundM", "Terrain elevation", "m"),
                ("differenceM", "Difference", "m"),
                ("status", "Status"),
            ],
            rows,
            summary={
                "boreholesCheckedCount": len(rows),
                "outsideTerrainCount": sum(row["terrainGroundM"] is None for row in rows),
            },
            notes=[
                "Terrain elevation is linearly interpolated in its triangulation; differences above 0.5 m are review flags, not automatic corrections."
            ],
        )
    raise FeatureInputError(
        "The requested site operation needs site boundary, terrain or survey data."
    )


register_tab("soilSite", _handle, fields=_fields)
