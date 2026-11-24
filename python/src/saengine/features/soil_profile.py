"""Soil Report Profile & CPT analyses: stratigraphy, surfaces and pore pressure."""

from __future__ import annotations

import csv
import io
import itertools
import math
from collections import defaultdict
from typing import Any

from saengine.features import number, result, table, text
from saengine.features.soil_feature_utils import (
    FeatureInputError,
    common_fields,
    layer_rows,
    register_tab,
    require_layers,
    require_report,
    result_rows,
)

GAMMA_W = 9.81


def _fields(fid: str) -> list[Any]:
    if fid in {
        "soilProfile.cptImport",
        "soilProfile.coneResistanceQc",
        "soilProfile.sleeveFrictionFs",
    }:
        return [text("cptCsv", "CPT CSV (depth_m, qc_mpa, fs_kpa, u2_kpa)", "")]
    if fid == "soilProfile.robertsonSoilClass":
        return [
            number("qcMpa", "Cone resistance qc [MPa]", 5.0, unit="MPa", min=0.01),
            number("fsKpa", "Sleeve friction fs [kPa]", 50.0, unit="kPa", min=0),
            number("sigmaVeffKpa", "Effective overburden stress [kPa]", 100.0, unit="kPa", min=0.1),
            number("sigmaVKpa", "Total overburden stress [kPa]", 120.0, unit="kPa", min=0.1),
        ]
    if fid == "soilProfile.dissipationTest":
        return [
            text("readings", "Time [min], excess pressure [kPa] pairs", ""),
            number("drainageRadiusM", "Drainage radius [m]", 0.01, unit="m", min=0.0001),
            number("timeFactor", "Radial time factor at t50", 0.245, min=0.001),
        ]
    if fid in {
        "soilProfile.hydrostaticCorrection",
        "soilProfile.equilibriumPorePressure",
        "soilProfile.porePressureProfile",
    }:
        return [
            text("readings", "Depth [m], pore pressure [kPa] pairs", ""),
            number("waterTableDepthM", "Water table depth [m]", 5.0, unit="m", min=0),
        ]
    if fid == "soilProfile.excessPorePressure":
        return [
            number("u2Kpa", "Measured CPT u2 [kPa]", 120.0, unit="kPa", min=0),
            number("u0Kpa", "Hydrostatic u0 [kPa]", 50.0, unit="kPa", min=0),
            number("qtKpa", "Corrected cone resistance qt [kPa]", 5000.0, unit="kPa", min=0.1),
            number("sigmaVKpa", "Total vertical stress [kPa]", 120.0, unit="kPa", min=0),
        ]
    if fid == "soilProfile.pinchOutCleanup":
        return [
            *common_fields(fid),
            number("minimumThicknessM", "Minimum layer thickness [m]", 0.3, unit="m", min=0.01),
        ]
    if fid == "soilProfile.depthDatumShift":
        return [*common_fields(fid), number("shiftM", "Elevation datum shift [m]", 0.0, unit="m")]
    if fid in {
        "soilProfile.interpolateSurface",
        "soilProfile.contourMap",
        "soilProfile.layerThicknessMap",
        "soilProfile.surfaceVolume",
    }:
        return [*common_fields(fid), number("layerIndex", "Layer number", 1.0, min=1)]
    return common_fields(fid)


def _needs_project(fid: str) -> bool:
    return fid not in {
        "soilProfile.cptImport",
        "soilProfile.robertsonSoilClass",
        "soilProfile.coneResistanceQc",
        "soilProfile.sleeveFrictionFs",
        "soilProfile.dissipationTest",
        "soilProfile.hydrostaticCorrection",
        "soilProfile.porePressureProfile",
        "soilProfile.excessPorePressure",
        "soilProfile.equilibriumPorePressure",
    }


def _parse_csv(raw: str) -> list[dict[str, float]]:
    if not raw.strip():
        raise FeatureInputError(
            "Paste CPT rows with a header and depth_m plus qc_mpa or fs_kpa values."
        )
    reader = csv.DictReader(io.StringIO(raw.strip()))
    if not reader.fieldnames:
        raise FeatureInputError("The CPT text needs a CSV header row.")
    names = {name.strip().lower().replace(" ", "_"): name for name in reader.fieldnames if name}
    depth_key = next((names[k] for k in ("depth_m", "depth", "depthm") if k in names), None)
    if depth_key is None:
        raise FeatureInputError("The CPT CSV needs a depth_m column.")
    aliases = {
        "qcMpa": ("qc_mpa", "qc", "cone_resistance_mpa"),
        "fsKpa": ("fs_kpa", "fs", "sleeve_friction_kpa"),
        "u2Kpa": ("u2_kpa", "u2", "pore_pressure_kpa"),
    }
    keys = {
        target: next((names[k] for k in choices if k in names), None)
        for target, choices in aliases.items()
    }
    rows = []
    for line, item in enumerate(reader, 2):
        try:
            row: dict[str, float] = {"depthM": float(item[depth_key])}
            if row["depthM"] < 0:
                raise ValueError
            for target, key in keys.items():
                if key and item.get(key, "").strip():
                    row[target] = float(item[key])
            rows.append(row)
        except (TypeError, ValueError):
            raise FeatureInputError(
                f"CPT CSV row {line} has an invalid depth or numeric measurement."
            ) from None
    if not rows:
        raise FeatureInputError("The CPT CSV has no measurement rows.")
    return sorted(rows, key=lambda row: row["depthM"])


def _pairs(raw: str, label: str) -> list[tuple[float, float]]:
    pairs = []
    for line in raw.replace(";", "\n").splitlines():
        if not line.strip():
            continue
        bits = [part.strip() for part in line.split(",")]
        if len(bits) != 2:
            raise FeatureInputError(
                f"{label} rows must be entered as value,value pairs separated by commas."
            )
        try:
            pairs.append((float(bits[0]), float(bits[1])))
        except ValueError:
            raise FeatureInputError(f"{label} contains a non-numeric reading.") from None
    if len(pairs) < 2:
        raise FeatureInputError(f"Enter at least two {label} readings.")
    return sorted(pairs)


def _hull_area(points: list[tuple[float, float]]) -> float:
    unique = sorted(set(points))
    if len(unique) < 3:
        return 0.0

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    polygon = lower[:-1] + upper[:-1]
    return (
        abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(polygon, polygon[1:] + polygon[:1]))) / 2
    )


def _interpolate(points: list[tuple[float, float, float]], x: float, y: float) -> float:
    weights = []
    for px, py, value in points:
        distance = math.hypot(px - x, py - y)
        if distance < 1e-8:
            return value
        weights.append((1 / distance**2, value))
    return sum(w * value for w, value in weights) / sum(w for w, _ in weights)


def _handle(fid: str, ctx: Any, values: dict[str, Any]) -> dict[str, Any]:
    if fid in {
        "soilProfile.cptImport",
        "soilProfile.coneResistanceQc",
        "soilProfile.sleeveFrictionFs",
    }:
        rows = _parse_csv(values["cptCsv"])
        if fid == "soilProfile.cptImport":
            return result(
                summary={
                    "cptPointsCount": len(rows),
                    "depthMinM": rows[0]["depthM"],
                    "depthMaxM": rows[-1]["depthM"],
                },
                tables=[
                    table(
                        "CPT measurements",
                        [
                            ("depthM", "Depth", "m"),
                            ("qcMpa", "Cone resistance", "MPa"),
                            ("fsKpa", "Sleeve friction", "kPa"),
                            ("u2Kpa", "Pore pressure", "kPa"),
                        ],
                        rows,
                    )
                ],
                notes=[
                    "CPT measurements are validated and tabulated from the supplied CSV; the Soil Report schema does not store CPT soundings."
                ],
            )
        key, title, unit = (
            ("qcMpa", "Cone resistance profile", "MPa")
            if fid.endswith("coneResistanceQc")
            else ("fsKpa", "Sleeve friction profile", "kPa")
        )
        found = [row for row in rows if key in row]
        if not found:
            raise FeatureInputError(f"The CPT CSV has no {key} values.")
        return result(
            summary={"pointsCount": len(found), "maximumValue": max(row[key] for row in found)},
            tables=[table(title, [("depthM", "Depth", "m"), (key, title, unit)], found)],
            notes=["Values are reported against CPT depth; no extrapolation is applied."],
        )
    if fid == "soilProfile.robertsonSoilClass":
        net = values["qcMpa"] * 1000 - values["sigmaVKpa"]
        if net <= 0:
            raise FeatureInputError("Cone resistance must exceed total vertical stress.")
        qtn = net / values["sigmaVeffKpa"]
        fr = 100 * values["fsKpa"] / net
        if qtn <= 0 or fr <= 0:
            raise FeatureInputError(
                "Normalized cone resistance and friction ratio must be positive."
            )
        ic = math.sqrt((3.47 - math.log10(qtn)) ** 2 + (math.log10(fr) + 1.22) ** 2)
        category = (
            "gravelly sand to dense sand"
            if ic < 1.31
            else "sand to silty sand"
            if ic < 2.05
            else "silty sand to sandy silt"
            if ic < 2.60
            else "clayey silt to silty clay"
            if ic < 2.95
            else "clay"
            if ic < 3.60
            else "organic soil / sensitive clay"
        )
        return result(
            summary={
                "normalizedConeResistance": qtn,
                "frictionRatioPct": fr,
                "soilBehaviorIndex": ic,
                "soilBehaviorGroup": category,
            },
            tables=[
                table(
                    "Normalized CPT classification inputs",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Net cone resistance [kPa]", "value": net},
                        {"parameter": "Qtn [-]", "value": qtn},
                        {"parameter": "Friction ratio [%]", "value": fr},
                        {"parameter": "Ic [-]", "value": ic},
                        {"parameter": "Indicative behavior", "value": category},
                    ],
                )
            ],
            notes=[
                "Robertson soil behavior type index from normalized cone resistance and friction ratio; this is a screening classification and is sensitive to stress normalization and soil cementation."
            ],
        )
    if fid == "soilProfile.dissipationTest":
        readings = _pairs(values["readings"], "time, excess pressure")
        if any(a[0] < 0 for a in readings) or any(
            b[1] > a[1] for a, b in itertools.pairwise(readings)
        ):
            raise FeatureInputError(
                "Dissipation time must be non-negative and excess pressure must not increase between readings."
            )
        u0, uinf = readings[0][1], readings[-1][1]
        target = uinf + 0.5 * (u0 - uinf)
        t50 = None
        for (t0, p0), (t1, p1) in itertools.pairwise(readings):
            if p0 >= target >= p1:
                t50 = t0 + (t1 - t0) * (p0 - target) / (p0 - p1) if p0 != p1 else t1
                break
        if t50 is None or t50 <= 0:
            raise FeatureInputError("The readings do not capture a positive t50 dissipation time.")
        cv_m2_s = values["timeFactor"] * values["drainageRadiusM"] ** 2 / (t50 * 60)
        return result(
            summary={"t50Min": t50, "cvM2PerS": cv_m2_s},
            tables=[
                table(
                    "Pore-pressure dissipation readings",
                    [("timeMin", "Time", "min"), ("excessPressureKpa", "Excess pressure", "kPa")],
                    [{"timeMin": t, "excessPressureKpa": p} for t, p in readings],
                )
            ],
            notes=[
                "t50 is linearly interpolated. cv = T50·r²/t50 uses the entered radial time factor and drainage radius; the chosen factor must match the probe geometry and drainage assumption."
            ],
        )
    if fid in {"soilProfile.hydrostaticCorrection", "soilProfile.porePressureProfile"}:
        readings = _pairs(values["readings"], "depth, pore pressure")
        rows = [
            {
                "depthM": z,
                "measuredKpa": u,
                "hydrostaticKpa": GAMMA_W * max(0.0, z - values["waterTableDepthM"]),
                "excessKpa": u - GAMMA_W * max(0.0, z - values["waterTableDepthM"]),
            }
            for z, u in readings
        ]
        return result(
            summary={
                "measurementsCount": len(rows),
                "maximumExcessKpa": max(row["excessKpa"] for row in rows),
            },
            tables=[
                table(
                    "Hydrostatic correction",
                    [
                        ("depthM", "Depth", "m"),
                        ("measuredKpa", "Measured u", "kPa"),
                        ("hydrostaticKpa", "Hydrostatic u0", "kPa"),
                        ("excessKpa", "Excess u", "kPa"),
                    ],
                    rows,
                )
            ],
            notes=[
                "Hydrostatic reference u0 = γw·max(0, z − zw); depths and water-table level use the same ground datum."
            ],
        )
    if fid == "soilProfile.excessPorePressure":
        excess = values["u2Kpa"] - values["u0Kpa"]
        net = values["qtKpa"] - values["sigmaVKpa"]
        if net <= 0:
            raise FeatureInputError("Corrected cone resistance must exceed total vertical stress.")
        bq = excess / net
        return result(
            summary={"excessPorePressureKpa": excess, "porePressureRatioBq": bq},
            tables=[
                table(
                    "CPT pore-pressure ratio",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Δu = u2 − u0 [kPa]", "value": excess},
                        {"parameter": "qt − σv [kPa]", "value": net},
                        {"parameter": "Bq [-]", "value": bq},
                    ],
                )
            ],
            notes=[
                "Bq = (u2 − u0)/(qt − σv); interpret with CPT soil behavior and drainage conditions, not as a stand-alone liquefaction verdict."
            ],
        )
    if fid == "soilProfile.equilibriumPorePressure":
        readings = _pairs(values["readings"], "depth, pore pressure")
        pressures = [p for _, p in readings]
        mean = sum(pressures) / len(pressures)
        spread = max(pressures) - min(pressures)
        return result(
            summary={
                "meanPressureKpa": mean,
                "equivalentWaterHeadM": mean / GAMMA_W,
                "pressureRangeKpa": spread,
            },
            tables=[
                table(
                    "Groundwater readings",
                    [("depthM", "Depth", "m"), ("pressureKpa", "Pressure", "kPa")],
                    [{"depthM": z, "pressureKpa": p} for z, p in readings],
                )
            ],
            notes=[
                "The arithmetic mean is a compact summary of readings supplied for the same screened interval; confirm equilibration and datum consistency before assigning a water level."
            ],
        )

    report = require_report(ctx)
    require_layers(report)
    if fid == "soilProfile.modelValidation":
        conflicts = []
        for bh in report.boreholes:
            layers = sorted(bh.layers, key=lambda item: item.top)
            for i, layer in enumerate(layers):
                if i and layer.top > layers[i - 1].bottom + 1:
                    conflicts.append(
                        {
                            "borehole": bh.id,
                            "depthM": layers[i - 1].bottom / 1000,
                            "issue": f"Unlogged gap to next layer at {layer.top / 1000:g} m",
                        }
                    )
                elif i and layer.top < layers[i - 1].bottom - 1:
                    conflicts.append(
                        {
                            "borehole": bh.id,
                            "depthM": layer.top / 1000,
                            "issue": "Overlapping layer intervals",
                        }
                    )
                if layer.bottom > bh.bottom + 1:
                    conflicts.append(
                        {
                            "borehole": bh.id,
                            "depthM": layer.bottom / 1000,
                            "issue": "Layer exceeds recorded borehole termination",
                        }
                    )
            if not bh.layers:
                conflicts.append({"borehole": bh.id, "depthM": 0.0, "issue": "No logged layers"})
        return result(
            summary={
                "conflictsCount": len(conflicts),
                "boreholesCheckedCount": len(report.boreholes),
            },
            tables=[
                table(
                    "Ground model validation",
                    [("borehole", "Borehole"), ("depthM", "Depth", "m"), ("issue", "Conflict")],
                    conflicts,
                )
            ],
            notes=[
                "Adjacent boundaries within 1 mm are treated as coincident. Validation reports do not change the logged ground model."
            ],
        )
    if fid == "soilProfile.depthDatumShift":
        shift = values["shiftM"] * 1000
        rows = []
        for bh in report.boreholes:
            ground = report.ground_level(bh)
            for i, layer in enumerate(bh.layers, 1):
                rows.append(
                    {
                        "borehole": bh.id,
                        "layer": i,
                        "topElevationM": (ground - layer.top + shift) / 1000,
                        "bottomElevationM": (ground - layer.bottom + shift) / 1000,
                        "shiftM": values["shiftM"],
                    }
                )
        return result(
            summary={"shiftM": values["shiftM"], "layersCount": len(rows)},
            tables=[
                table(
                    "Layer elevations after datum shift",
                    [
                        ("borehole", "Borehole"),
                        ("layer", "Layer"),
                        ("topElevationM", "Top elevation", "m"),
                        ("bottomElevationM", "Bottom elevation", "m"),
                        ("shiftM", "Shift", "m"),
                    ],
                    rows,
                )
            ],
            notes=[
                "Only elevations are shifted; logged depths below ground and the source project remain unchanged."
            ],
        )
    if fid in {
        "soilProfile.layerThicknessMap",
        "soilProfile.interpolateSurface",
        "soilProfile.contourMap",
        "soilProfile.surfaceVolume",
    }:
        index = max(1, int(values.get("layerIndex", 1))) - 1
        selected = []
        for bh in report.boreholes:
            if index < len(bh.layers):
                layer = bh.layers[index]
                selected.append((bh, layer))
        if not selected:
            raise FeatureInputError("No borehole has the requested layer number.")
        if fid == "soilProfile.surfaceVolume":
            points = [(bh.x / 1000, bh.y / 1000) for bh, _ in selected]
            area = _hull_area(points)
            if area <= 0 or len(selected) < 3:
                raise FeatureInputError(
                    "At least three non-collinear boreholes with the requested layer are needed for a footprint volume estimate."
                )
            thickness = [(layer.bottom - layer.top) / 1000 for _, layer in selected]
            volume = area * sum(thickness) / len(thickness)
            rows = [
                {"borehole": bh.id, "thicknessM": (layer.bottom - layer.top) / 1000}
                for bh, layer in selected
            ]
            return result(
                summary={
                    "footprintAreaM2": area,
                    "meanThicknessM": sum(thickness) / len(thickness),
                    "volumeM3": volume,
                },
                tables=[
                    table(
                        "Layer thickness observations",
                        [("borehole", "Borehole"), ("thicknessM", "Thickness", "m")],
                        rows,
                    )
                ],
                notes=[
                    "Volume is the convex-hull area of borehole locations multiplied by their arithmetic mean layer thickness; this sparse-data estimate assumes the layer spans the full hull and should not replace a gridded surface model."
                ],
            )
        rows = [
            {
                "borehole": bh.id,
                "xM": bh.x / 1000,
                "yM": bh.y / 1000,
                "layer": index + 1,
                "soilType": layer.soilType,
                "topDepthM": layer.top / 1000,
                "bottomDepthM": layer.bottom / 1000,
                "thicknessM": (layer.bottom - layer.top) / 1000,
                "topElevationM": (report.ground_level(bh) - layer.top) / 1000,
                "bottomElevationM": (report.ground_level(bh) - layer.bottom) / 1000,
            }
            for bh, layer in selected
        ]
        if fid == "soilProfile.layerThicknessMap":
            return result_rows(
                "Layer thickness map nodes",
                [
                    ("borehole", "Borehole"),
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("layer", "Layer"),
                    ("thicknessM", "Thickness", "m"),
                ],
                rows,
                summary={
                    "nodesCount": len(rows),
                    "meanThicknessM": sum(row["thicknessM"] for row in rows) / len(rows),
                },
                notes=[
                    "Each row is a logged observation node; interpolate between nodes only within the investigated area."
                ],
            )
        surface_key = "topElevationM" if fid != "soilProfile.contourMap" else "bottomElevationM"
        title = (
            "Interpolated layer-top surface nodes"
            if surface_key == "topElevationM"
            else "Layer-bottom contour nodes"
        )
        return result_rows(
            title,
            [
                ("borehole", "Borehole"),
                ("xM", "X", "m"),
                ("yM", "Y", "m"),
                ("layer", "Layer"),
                ("soilType", "Soil type"),
                (surface_key, "Elevation", "m"),
            ],
            rows,
            summary={
                "nodesCount": len(rows),
                "minimumElevationM": min(row[surface_key] for row in rows),
                "maximumElevationM": max(row[surface_key] for row in rows),
            },
            notes=[
                "The table supplies surface control points for plan interpolation; no extrapolation beyond logged boreholes is implied."
            ],
        )
    if fid == "soilProfile.sliceView":
        z = values.get("depthM", 5.0) * 1000
        rows = []
        for bh in report.boreholes:
            layer = next((item for item in bh.layers if item.top <= z < item.bottom), None)
            if layer:
                rows.append(
                    {
                        "borehole": bh.id,
                        "xM": bh.x / 1000,
                        "yM": bh.y / 1000,
                        "depthM": z / 1000,
                        "soilType": layer.soilType,
                        "uscs": layer.uscs,
                        "description": layer.description,
                    }
                )
        if not rows:
            raise FeatureInputError("No logged layer covers the requested slice depth.")
        return result_rows(
            "Ground slice observations",
            [
                ("borehole", "Borehole"),
                ("xM", "X", "m"),
                ("yM", "Y", "m"),
                ("depthM", "Depth", "m"),
                ("soilType", "Soil type"),
                ("uscs", "USCS"),
                ("description", "Description"),
            ],
            rows,
            summary={"sliceDepthM": z / 1000, "observationsCount": len(rows)},
            notes=[
                "Depth is measured below each borehole's local ground surface; the sparse observations are the data behind the slice view."
            ],
        )
    if fid in {
        "soilProfile.buildGroundModel",
        "soilProfile.correlateLayers",
        "soilProfile.zoneAssignment",
        "soilProfile.fenceDiagram",
        "soilProfile.crossSections",
        "soilProfile.sectionRegeneration",
        "soilProfile.lensDetection",
        "soilProfile.pinchOutCleanup",
    }:
        rows = layer_rows(report)
        if fid in {
            "soilProfile.buildGroundModel",
            "soilProfile.correlateLayers",
            "soilProfile.zoneAssignment",
        }:
            groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                key = (row["uscs"] or row["soilType"], row["soilType"])
                groups[key].append(row)
            grouped_rows = []
            for (symbol, kind), members in sorted(groups.items()):
                grouped_rows.append(
                    {
                        "zone": symbol,
                        "soilType": kind,
                        "observations": len(members),
                        "boreholes": ", ".join(sorted({r["borehole"] for r in members})),
                        "topDepthMinM": min(r["topM"] for r in members),
                        "bottomDepthMaxM": max(r["bottomM"] for r in members),
                    }
                )
            title = (
                "Correlated ground model zones"
                if fid != "soilProfile.correlateLayers"
                else "Layer correlation groups"
            )
            return result_rows(
                title,
                [
                    ("zone", "Correlation key"),
                    ("soilType", "Soil type"),
                    ("observations", "Layer observations"),
                    ("boreholes", "Boreholes"),
                    ("topDepthMinM", "Shallowest top", "m"),
                    ("bottomDepthMaxM", "Deepest bottom", "m"),
                ],
                grouped_rows,
                summary={"zonesCount": len(grouped_rows), "layerObservationsCount": len(rows)},
                notes=[
                    "Correlation uses matching logged USCS symbols where available, otherwise soil type; lithologic descriptions still require geotechnical review before combining units."
                ],
            )
        if fid in {"soilProfile.lensDetection", "soilProfile.pinchOutCleanup"}:
            threshold = values.get("minimumThicknessM", 0.3)
            counts_by_type: dict[str, int] = defaultdict(int)
            for row in rows:
                counts_by_type[row["soilType"]] += 1
            findings = []
            for row in rows:
                thin = row["thicknessM"] < threshold
                isolated = counts_by_type[row["soilType"]] == 1
                if (thin or isolated) and (fid == "soilProfile.lensDetection" or thin):
                    findings.append(
                        {
                            **row,
                            "finding": "thin interval: review pinch-out"
                            if thin
                            else "soil type appears at one logged interval; review for a lens",
                        }
                    )
            return result_rows(
                "Stratigraphic review findings",
                [
                    ("borehole", "Borehole"),
                    ("layer", "Layer"),
                    ("topM", "Top", "m"),
                    ("bottomM", "Bottom", "m"),
                    ("soilType", "Soil type"),
                    ("thicknessM", "Thickness", "m"),
                    ("finding", "Review"),
                ],
                findings,
                summary={"findingsCount": len(findings)},
                notes=[
                    "The tool flags sparse or thin logged units for review and does not merge or alter layer records."
                ],
            )
        ordered = sorted(report.boreholes, key=lambda bh: (bh.x, bh.y))
        if (
            fid in {"soilProfile.fenceDiagram", "soilProfile.crossSections"}
            and report.stratigraphy
            and report.stratigraphy.fences
        ):
            fence = report.stratigraphy.fences[0]
            id_order = {name: i for i, name in enumerate(fence.boreholes)}
            ordered = (
                sorted(
                    (bh for bh in report.boreholes if bh.id in id_order),
                    key=lambda bh: id_order[bh.id],
                )
                or ordered
            )
        section_rows = []
        station = 0.0
        last = None
        for bh in ordered:
            if last is not None:
                station += math.hypot(bh.x - last.x, bh.y - last.y) / 1000
            for layer in bh.layers:
                section_rows.append(
                    {
                        "stationM": station,
                        "borehole": bh.id,
                        "xM": bh.x / 1000,
                        "yM": bh.y / 1000,
                        "topDepthM": layer.top / 1000,
                        "bottomDepthM": layer.bottom / 1000,
                        "soilType": layer.soilType,
                        "uscs": layer.uscs,
                    }
                )
            last = bh
        title = (
            "Regenerated section data"
            if fid == "soilProfile.sectionRegeneration"
            else "Cross-section layer data"
        )
        return result_rows(
            title,
            [
                ("stationM", "Station", "m"),
                ("borehole", "Borehole"),
                ("xM", "X", "m"),
                ("yM", "Y", "m"),
                ("topDepthM", "Top", "m"),
                ("bottomDepthM", "Bottom", "m"),
                ("soilType", "Soil type"),
                ("uscs", "USCS"),
            ],
            section_rows,
            summary={
                "boreholesCount": len(ordered),
                "layerSegmentsCount": len(section_rows),
                "sectionLengthM": station,
            },
            notes=[
                "Stations follow the first saved fence alignment when available, otherwise boreholes are ordered by project X and Y; this table is the data behind the section view."
            ],
        )
    raise FeatureInputError(
        "The requested profile operation needs additional CPT or ground-model data."
    )


register_tab("soilProfile", _handle, requires_project=_needs_project, fields=_fields)
