"""Soil Report field records, borehole checks and field-test reductions."""

from __future__ import annotations

import itertools
import math
from typing import Any

from saengine.features import number, result, table
from saengine.features.soil_feature_utils import (
    FeatureInputError,
    borehole,
    common_fields,
    profile,
    register_tab,
    require_report,
    result_rows,
    sample_rows,
    save_text,
)


def _fields(fid: str) -> list[Any]:
    if fid == "soil.fieldDensityTest":
        return [
            number("wetDensity", "Wet density [Mg/m³]", 1.92, unit="Mg/m³", min=0.1),
            number("moisturePct", "Water content [%]", 18.0, unit="%", min=0, max=200),
            number("maxDryDensity", "Maximum dry density [Mg/m³]", 1.85, unit="Mg/m³", min=0.1),
        ]
    if fid == "soil.fallingHeadTest":
        return [
            number("standpipeAreaMm2", "Standpipe area [mm²]", 80.0, unit="mm²", min=0.01),
            number("specimenAreaMm2", "Specimen area [mm²]", 10000.0, unit="mm²", min=0.01),
            number("lengthMm", "Specimen length [mm]", 100.0, unit="mm", min=0.1),
            number("headStartMm", "Initial head [mm]", 1000.0, unit="mm", min=0.1),
            number("headEndMm", "Final head [mm]", 400.0, unit="mm", min=0.1),
            number("timeS", "Elapsed time [s]", 600.0, unit="s", min=0.1),
        ]
    if fid == "soil.vaneShearTest":
        return [
            number("torqueNm", "Peak vane torque [N·m]", 2.0, unit="N·m", min=0.001),
            number("vaneDiameterMm", "Vane diameter [mm]", 50.0, unit="mm", min=1),
            number("vaneHeightMm", "Vane height [mm]", 100.0, unit="mm", min=1),
        ]
    if fid == "soil.pressuremeterTest":
        return [
            number("pressureIncrementKpa", "Pressure increment [kPa]", 100.0, unit="kPa", min=0.1),
            number("volumeIncrementCm3", "Volume increment [cm³]", 5.0, unit="cm³", min=0.01),
            number("cavityRadiusMm", "Cavity radius [mm]", 35.0, unit="mm", min=1),
            number("poissonRatio", "Poisson ratio", 0.30, min=0.05, max=0.49),
        ]
    if fid == "soil.lugeonTest":
        return [
            number("flowLpm", "Water take [L/min]", 12.0, unit="L/min", min=0),
            number("testLengthM", "Test interval [m]", 5.0, unit="m", min=0.1),
            number("pressureMpa", "Test pressure [MPa]", 0.8, unit="MPa", min=0.01),
        ]
    return common_fields(fid)


def _needs_project(fid: str) -> bool:
    return fid not in {
        "soil.fieldDensityTest",
        "soil.fallingHeadTest",
        "soil.vaneShearTest",
        "soil.pressuremeterTest",
        "soil.lugeonTest",
        "soil.depthRuler",
        "soil.graphicLogStyle",
        "soil.coordinateSystem",
    }


def _handle(fid: str, ctx: Any, values: dict[str, Any]) -> dict[str, Any]:
    if fid == "soil.fieldDensityTest":
        wet = values["wetDensity"]
        dry = wet / (1 + values["moisturePct"] / 100)
        relative = 100 * dry / values["maxDryDensity"]
        return result(
            summary={"dryDensityMgM3": dry, "relativeCompactionPct": relative},
            tables=[
                table(
                    "Field density reduction",
                    [("measure", "Measure"), ("value", "Value")],
                    [
                        {"measure": "Wet density [Mg/m³]", "value": wet},
                        {"measure": "Dry density [Mg/m³]", "value": dry},
                        {"measure": "Relative compaction [%]", "value": relative},
                    ],
                )
            ],
            notes=[
                "Dry density = wet density / (1 + gravimetric water content). Compare with the specified laboratory reference density."
            ],
        )
    if fid == "soil.fallingHeadTest":
        ah, a, length, h1, h2, seconds = (
            values[k]
            for k in (
                "standpipeAreaMm2",
                "specimenAreaMm2",
                "lengthMm",
                "headStartMm",
                "headEndMm",
                "timeS",
            )
        )
        if h2 >= h1:
            raise FeatureInputError("The final head must be lower than the initial head.")
        k_m_s = (ah / a) * (length / 1000) / seconds * math.log(h1 / h2)
        return result(
            summary={"permeabilityMPerS": k_m_s},
            tables=[
                table(
                    "Falling-head reduction",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Hydraulic conductivity [m/s]", "value": k_m_s},
                        {"parameter": "Head ratio h1/h2", "value": h1 / h2},
                    ],
                )
            ],
            notes=[
                "k = (aL/At) ln(h1/h2), using the entered areas and elapsed time; verify temperature and apparatus corrections before reporting."
            ],
        )
    if fid == "soil.vaneShearTest":
        d = values["vaneDiameterMm"] / 1000
        h = values["vaneHeightMm"] / 1000
        # Torque for cylindrical vane failure: T = cu*pi*D^2*(H/2 + D/6).
        cu = values["torqueNm"] / (math.pi * d**2 * (h / 2 + d / 6)) / 1000
        return result(
            summary={"undrainedStrengthKpa": cu},
            tables=[
                table(
                    "Vane shear reduction",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Torque [N·m]", "value": values["torqueNm"]},
                        {"parameter": "Undrained strength [kPa]", "value": cu},
                    ],
                )
            ],
            notes=[
                "Uniform shear stress on the vane's cylindrical surface and ends is assumed; apply remoulded measurements separately to derive sensitivity."
            ],
        )
    if fid == "soil.pressuremeterTest":
        r = values["cavityRadiusMm"] / 1000
        delta_v = values["volumeIncrementCm3"] * 1e-6
        delta_p = values["pressureIncrementKpa"] * 1000
        strain = delta_v / (2 * math.pi * r**3)
        modulus = (1 + values["poissonRatio"]) * delta_p / (2 * strain) / 1e6
        return result(
            summary={"pressuremeterModulusMpa": modulus},
            tables=[
                table(
                    "Pressuremeter elastic reduction",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {
                            "parameter": "Pressure increment [kPa]",
                            "value": values["pressureIncrementKpa"],
                        },
                        {
                            "parameter": "Volume increment [cm³]",
                            "value": values["volumeIncrementCm3"],
                        },
                        {"parameter": "Modulus [MPa]", "value": modulus},
                    ],
                )
            ],
            notes=[
                "Small-strain cylindrical cavity estimate from a single pressure-volume increment; use the corrected unload-reload or pressuremeter expansion curve for design modulus."
            ],
        )
    if fid == "soil.lugeonTest":
        lu = values["flowLpm"] / values["testLengthM"] / values["pressureMpa"]
        return result(
            summary={"lugeonValue": lu},
            tables=[
                table(
                    "Water pressure test reduction",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Normalized water take [L/min/m/MPa]", "value": lu},
                        {"parameter": "Equivalent Lugeon units", "value": lu},
                    ],
                )
            ],
            notes=[
                "Normalized to 1 MPa and 1 m test interval; the classical Lugeon unit presumes laminar flow and a valid test-stage pressure."
            ],
        )

    report = require_report(ctx)
    if fid == "soil.depthRuler":
        bh = borehole(report, values.get("boreholeId") or None)
        depth_mm = values.get("depthM", 5.0) * 1000
        layer = next((layer for layer in bh.layers if layer.top <= depth_mm < layer.bottom), None)
        if layer is None:
            raise FeatureInputError(
                f"No logged layer covers depth {depth_mm / 1000:g} m in {bh.id}."
            )
        rows = [
            {
                "borehole": bh.id,
                "depthM": depth_mm / 1000,
                "soilType": layer.soilType,
                "uscs": layer.uscs,
                "description": layer.description,
                "layerTopM": layer.top / 1000,
                "layerBottomM": layer.bottom / 1000,
            }
        ]
        return result_rows(
            "Depth ruler",
            [
                ("borehole", "Borehole"),
                ("depthM", "Depth", "m"),
                ("soilType", "Soil type"),
                ("uscs", "USCS"),
                ("description", "Description"),
                ("layerTopM", "Layer top", "m"),
                ("layerBottomM", "Layer bottom", "m"),
            ],
            rows,
            summary={"depthM": depth_mm / 1000, "boreholeId": bh.id},
            notes=["Depth is measured down from the borehole ground level."],
        )
    if fid == "soil.graphicLogStyle":
        counts: dict[str, int] = {}
        for bh in report.boreholes:
            for layer in bh.layers:
                counts[layer.soilType] = counts.get(layer.soilType, 0) + 1
        palette = {
            "clay": "#B88968",
            "silt": "#D7B85A",
            "sand": "#F1D276",
            "gravel": "#8E9B8A",
            "organic": "#705A48",
            "fill": "#B9A796",
            "rock": "#80858A",
        }
        rows = [
            {"soilType": kind, "layerCount": count, "suggestedColor": palette.get(kind, "#A0A0A0")}
            for kind, count in sorted(counts.items())
        ]
        return result_rows(
            "Graphic log legend",
            [
                ("soilType", "Soil type"),
                ("layerCount", "Layers"),
                ("suggestedColor", "Suggested color"),
            ],
            rows,
            summary={"soilTypesCount": len(rows)},
            notes=[
                "Suggested display colors are a visual legend only; the logged soil classifications are unchanged."
            ],
        )
    if fid == "soil.groundwaterStrike":
        rows = [
            {
                "borehole": bh.id,
                "waterTableM": bh.waterTable / 1000 if bh.waterTable is not None else None,
                "groundLevelM": report.ground_level(bh) / 1000,
                "waterElevationM": (report.ground_level(bh) - bh.waterTable) / 1000
                if bh.waterTable is not None
                else None,
                "readings": 1 if bh.waterTable is not None else 0,
            }
            for bh in report.boreholes
        ]
        return result_rows(
            "Groundwater strikes",
            [
                ("borehole", "Borehole"),
                ("waterTableM", "Depth to water", "m"),
                ("groundLevelM", "Ground level", "m"),
                ("waterElevationM", "Water elevation", "m"),
                ("readings", "Recorded readings"),
            ],
            rows,
            summary={
                "boreholesWithWaterCount": sum(row["waterTableM"] is not None for row in rows)
            },
            notes=[
                "The report water-table depth is measured below ground; elevations use each borehole's recorded ground level."
            ],
        )
    if fid == "soil.sptHammerType":
        rows = [
            {
                "borehole": bh.id,
                "depthM": point.depth,
                "fieldN": point.n,
                "energyPct": point.energy,
                "n60": point.n60,
                "rodFactor": point.cr,
            }
            for bh, prof in ((b, profile(report, b)) for b in report.boreholes)
            for point in prof.spt
        ]
        return result_rows(
            "SPT hammer energy and corrections",
            [
                ("borehole", "Borehole"),
                ("depthM", "Depth", "m"),
                ("fieldN", "Field N"),
                ("energyPct", "Energy", "%"),
                ("rodFactor", "Rod factor"),
                ("n60", "N60"),
            ],
            rows,
            summary={
                "designHammerEnergyPct": report.design.hammerEnergy,
                "sptTestsCount": len(rows),
            },
            notes=[
                "Per-test energy overrides the report hammer-energy setting; N60 includes the configured sampler, borehole and rod factors."
            ],
        )
    if fid == "soil.boreholePlan":
        rows = [
            {
                "borehole": bh.id,
                "xM": bh.x / 1000,
                "yM": bh.y / 1000,
                "groundLevelM": report.ground_level(bh) / 1000,
                "depthM": bh.bottom / 1000,
                "positionSource": bh.position,
            }
            for bh in report.boreholes
        ]
        return result_rows(
            "Borehole plan coordinates",
            [
                ("borehole", "Borehole"),
                ("xM", "Grid X", "m"),
                ("yM", "Grid Y", "m"),
                ("groundLevelM", "Ground level", "m"),
                ("depthM", "Depth", "m"),
                ("positionSource", "Coordinate source"),
            ],
            rows,
            summary={"boreholesCount": len(rows)},
            notes=[
                "Plan coordinates are shown in the project's local grid. The geometry is listed as data for a plan view."
            ],
        )
    if fid == "soil.coordinateSystem":
        site = report.site
        if site is None or not site.georeferenced:
            raise FeatureInputError(
                "Set the site latitude and longitude before deriving the project coordinate system."
            )
        return result(
            summary={
                "latitudeDeg": site.lat,
                "longitudeDeg": site.lon,
                "rotationDeg": site.rotation,
                "boreholesCount": len(report.boreholes),
            },
            tables=[
                table(
                    "Project grid reference",
                    [("property", "Property"), ("value", "Value")],
                    [
                        {"property": "Site latitude [°]", "value": site.lat},
                        {"property": "Site longitude [°]", "value": site.lon},
                        {"property": "Grid rotation from north [°]", "value": site.rotation},
                        {"property": "Local origin X [m]", "value": site.x / 1000},
                        {"property": "Local origin Y [m]", "value": site.y / 1000},
                    ],
                )
            ],
            notes=["Borehole locations use the report's project grid and its georeference."],
        )
    if fid == "soil.googleEarthKml":
        if report.site is None or not report.site.georeferenced:
            raise FeatureInputError(
                "Set a site latitude and longitude before exporting a Google Earth KML."
            )
        from saengine.gis.crs import Grid

        grid = Grid(report.site)
        points = []
        for bh in report.boreholes:
            lat, lon = grid.to_wgs84(bh.x, bh.y)
            points.append(
                f"<Placemark><name>{bh.id}</name><Point><coordinates>{lon:.8f},{lat:.8f},0</coordinates></Point></Placemark>"
            )
        boundary = ""
        if report.site.boundary:
            coords = " ".join(f"{p[0]:.8f},{p[1]:.8f},0" for p in report.site.boundary)
            boundary = f"<Placemark><name>Site boundary</name><Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>"
        path = save_text(
            ctx,
            "01 Soil Report/exports/boreholes.kml",
            '<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            + boundary
            + "".join(points)
            + "</Document></kml>\n",
        )
        return result(
            summary={"boreholesCount": len(points), "exportPath": path},
            notes=[
                f"KML written to {path}.",
                "The site boundary and borehole points use geographic longitude/latitude coordinates.",
            ],
        )
    if fid in {"soil.undisturbedSample", "soil.splitSpoonSample", "soil.samplePreservation"}:
        rows = sample_rows(report)
        if fid == "soil.undisturbedSample":
            rows = [
                row for row in rows if (row["type"] or "").lower() in {"ud", "undisturbed", "u"}
            ]
            title = "Undisturbed samples"
        elif fid == "soil.splitSpoonSample":
            rows = [
                row
                for row in rows
                if (row["type"] or "").lower() in {"spt", "split spoon", "spoon"}
            ]
            title = "Split-spoon samples"
        else:
            title = "Sample preservation register"
        if not rows:
            raise FeatureInputError("No matching soil samples are recorded in the boreholes.")
        return result_rows(
            title,
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("type", "Type"),
                ("depthM", "Depth", "m"),
                ("depthToM", "Depth to", "m"),
                ("recoveryPct", "Recovery", "%"),
                ("moisturePct", "Moisture", "%"),
                ("issues", "Record issues"),
            ],
            rows,
            summary={"samplesCount": len(rows)},
            notes=[
                "The register reflects only samples recorded in the Soil Report; preservation condition itself must be verified in the field log."
            ],
        )
    if fid == "soil.holeDeviationCheck":
        raise FeatureInputError(
            "No downhole deviation survey data are recorded; add surveyed inclination and azimuth stations to check the borehole path."
        )
    if fid == "soil.missingIntervalScan":
        rows = []
        for bh in report.boreholes:
            points = sorted(bh.spt, key=lambda p: p.depth)
            for a, b in itertools.pairwise(points):
                gap = (b.depth - a.depth) / 1000
                if gap > 3.0:
                    rows.append(
                        {
                            "borehole": bh.id,
                            "fromM": a.depth / 1000,
                            "toM": b.depth / 1000,
                            "gapM": gap,
                            "kind": "SPT interval",
                        }
                    )
            layers = sorted(bh.layers, key=lambda p: p.top)
            for a, b in itertools.pairwise(layers):
                if b.top - a.bottom > 1:
                    rows.append(
                        {
                            "borehole": bh.id,
                            "fromM": a.bottom / 1000,
                            "toM": b.top / 1000,
                            "gapM": (b.top - a.bottom) / 1000,
                            "kind": "unlogged layer interval",
                        }
                    )
        return result_rows(
            "Missing investigation intervals",
            [
                ("borehole", "Borehole"),
                ("fromM", "From", "m"),
                ("toM", "To", "m"),
                ("gapM", "Gap", "m"),
                ("kind", "Interval"),
            ],
            rows,
            summary={"gapsCount": len(rows)},
            notes=[
                "Flags SPT gaps longer than 3 m and any gap between adjacent logged layers; review against the investigation specification."
            ],
        )
    if fid == "soil.googleEarthKml":
        raise FeatureInputError("A georeferenced site is required for a Google Earth export.")
    if fid == "soil.boreholeLogEditor":
        bh = borehole(report, values.get("boreholeId") or None)
        rows = [
            {
                "depthM": r.depth / 1000,
                "fieldN": r.blows,
                "sample": r.sampleNumber,
                "issues": "; ".join(r.issues),
            }
            for r in bh.spt
        ]
        if not bh.layers and not bh.spt and not bh.samples:
            raise FeatureInputError(
                f"{bh.id} has no log intervals, SPT tests or samples to review."
            )
        return result(
            summary={
                "boreholeId": bh.id,
                "layersCount": len(bh.layers),
                "sptTestsCount": len(bh.spt),
                "samplesCount": len(bh.samples),
            },
            tables=[
                table(
                    "Borehole SPT log",
                    [
                        ("depthM", "Depth", "m"),
                        ("fieldN", "Field N"),
                        ("sample", "Sample"),
                        ("issues", "Record issues"),
                    ],
                    rows,
                ),
                table(
                    "Logged strata",
                    [
                        ("borehole", "Borehole"),
                        ("layer", "Layer"),
                        ("topM", "Top", "m"),
                        ("bottomM", "Bottom", "m"),
                        ("soilType", "Soil type"),
                        ("description", "Description"),
                    ],
                    [
                        {
                            k: row[k]
                            for k in (
                                "borehole",
                                "layer",
                                "topM",
                                "bottomM",
                                "soilType",
                                "description",
                            )
                        }
                        for row in __import__(
                            "saengine.features.soil_feature_utils", fromlist=["layer_rows"]
                        ).layer_rows(report, bh)
                    ],
                ),
            ],
            notes=[
                "Review and edit the source log in the Soil Report editor; this feature summarizes saved records and their schema-level issues."
            ],
        )
    if fid == "soil.fieldDensityTest":
        raise FeatureInputError("Enter the field-density test inputs to reduce the result.")
    raise FeatureInputError(
        "This Soil Report action needs its corresponding field or survey data in the project."
    )


register_tab("soil", _handle, requires_project=_needs_project, fields=_fields)
