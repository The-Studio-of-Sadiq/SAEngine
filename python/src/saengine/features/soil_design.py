"""Soil Report geotechnical design parameters, footing checks and traceability."""

from __future__ import annotations

import math
from statistics import fmean, stdev
from typing import Any

from saengine.features import number, result, table
from saengine.features.soil_feature_utils import (
    FeatureInputError,
    common_fields,
    profile,
    profiles,
    register_tab,
    require_report,
    result_rows,
    save_text,
)


def _fields(fid: str) -> list[Any]:
    if fid == "soilDesign.footingSizeAdvice":
        return [
            *common_fields(fid),
            number("loadKn", "Service vertical load [kN]", 500.0, unit="kN", min=0.1),
            number("maximumWidthM", "Maximum trial footing width [m]", 8.0, unit="m", min=0.5),
        ]
    if fid in {"soilDesign.slidingResistance", "soilDesign.upliftResistance"}:
        return [
            number("verticalLoadKn", "Vertical stabilizing load [kN]", 1000.0, unit="kN", min=0),
            number("horizontalLoadKn", "Horizontal action [kN]", 100.0, unit="kN", min=0),
            number("contactAreaM2", "Contact area [m²]", 10.0, unit="m²", min=0.1),
            number("cohesionKpa", "Interface adhesion [kPa]", 0.0, unit="kPa", min=0),
            number(
                "interfaceAngleDeg", "Interface friction angle [°]", 25.0, unit="°", min=0, max=50
            ),
        ]
    if fid == "soilDesign.overturningAdvice":
        return [
            number("verticalLoadKn", "Stabilizing vertical load [kN]", 1000.0, unit="kN", min=0),
            number("baseWidthM", "Base width [m]", 3.0, unit="m", min=0.1),
            number("horizontalLoadKn", "Horizontal action [kN]", 100.0, unit="kN", min=0),
            number("loadHeightM", "Action height above base [m]", 3.0, unit="m", min=0),
        ]
    if fid == "soilDesign.eccentricityAdvice":
        return [
            number("verticalLoadKn", "Vertical resultant [kN]", 1000.0, unit="kN", min=0.1),
            number("momentKnM", "Moment about footing centroid [kN·m]", 100.0, unit="kN·m"),
            number("baseWidthM", "Footing width in bending direction [m]", 3.0, unit="m", min=0.1),
        ]
    if fid in {
        "soilDesign.shearModulus",
        "soilDesign.wallFrictionAngle",
        "soilDesign.baseFriction",
    }:
        return [
            *common_fields(fid),
            number("poissonRatio", "Poisson ratio ν", 0.30, min=0.05, max=0.49),
            number("interfaceRatio", "Wall/interface angle ratio δ/φ", 0.67, min=0, max=1),
        ]
    if fid == "soilDesign.pileCapacityAdvice":
        return [
            *common_fields(fid),
            number("pileDiameterM", "Pile diameter [m]", 0.6, unit="m", min=0.1),
            number("pileLengthM", "Pile length [m]", 20.0, unit="m", min=1),
        ]
    if fid == "soilDesign.pileGroupSettlement":
        return [
            *common_fields(fid),
            number("groupWidthM", "Equivalent group width [m]", 6.0, unit="m", min=0.5),
            number("groupLengthM", "Equivalent group length [m]", 6.0, unit="m", min=0.5),
            number("loadKn", "Group service load [kN]", 5000.0, unit="kN", min=1),
        ]
    if fid == "soilDesign.negativeFriction":
        return [
            *common_fields(fid),
            number("pileDiameterM", "Pile diameter [m]", 0.6, unit="m", min=0.1),
        ]
    return common_fields(fid)


def _needs_project(fid: str) -> bool:
    return fid not in {
        "soilDesign.slidingResistance",
        "soilDesign.upliftResistance",
        "soilDesign.overturningAdvice",
        "soilDesign.eccentricityAdvice",
    }


def _parameter_rows(report: Any) -> list[dict[str, Any]]:
    rows = []
    for bh, prof in profiles(report):
        for layer in prof.layers:
            rows.append(
                {
                    "borehole": bh.id,
                    "layer": layer.index + 1,
                    "topDepthM": layer.top,
                    "bottomDepthM": layer.bottom,
                    "soilType": layer.soil_type,
                    "uscs": next(
                        (
                            item.uscs
                            for item in bh.layers
                            if abs(item.top / 1000 - layer.top) < 1e-6
                        ),
                        None,
                    ),
                    "gammaKnM3": layer.gamma,
                    "gammaSatKnM3": layer.gamma_sat,
                    "cuKpa": layer.cu,
                    "cKpa": layer.c,
                    "phiDeg": layer.phi,
                    "EMpa": layer.E,
                    "n60": layer.n60,
                    "n160": layer.n160,
                    "finesPct": layer.fines,
                    "ocr": layer.ocr,
                    "sources": layer.sources,
                }
            )
    return rows


def _handle(fid: str, ctx: Any, values: dict[str, Any]) -> dict[str, Any]:
    if fid == "soilDesign.slidingResistance":
        friction = values["verticalLoadKn"] * math.tan(math.radians(values["interfaceAngleDeg"]))
        adhesion = values["cohesionKpa"] * values["contactAreaM2"]
        resistance = friction + adhesion
        fs = resistance / values["horizontalLoadKn"] if values["horizontalLoadKn"] > 0 else math.inf
        return result(
            summary={
                "slidingResistanceKn": resistance,
                "factorOfSafety": fs,
                "frictionResistanceKn": friction,
                "adhesionResistanceKn": adhesion,
            },
            tables=[
                table(
                    "Sliding resistance",
                    [("component", "Component"), ("resistanceKn", "Resistance", "kN")],
                    [
                        {"component": "Base friction", "resistanceKn": friction},
                        {"component": "Interface adhesion", "resistanceKn": adhesion},
                        {"component": "Total", "resistanceKn": resistance},
                        {
                            "component": "Horizontal action",
                            "resistanceKn": values["horizontalLoadKn"],
                        },
                    ],
                )
            ],
            notes=[
                "R = V tan δ + ca; passive resistance and key shear are excluded and should be added only when reliably mobilized."
            ],
        )
    if fid == "soilDesign.upliftResistance":
        resistance = (
            values["verticalLoadKn"] * math.tan(math.radians(values["interfaceAngleDeg"]))
            + values["cohesionKpa"] * values["contactAreaM2"]
        )
        fs = resistance / values["horizontalLoadKn"] if values["horizontalLoadKn"] else math.inf
        return result(
            summary={"upliftResistanceKn": resistance, "factorOfSafety": fs},
            tables=[
                table(
                    "Uplift resistance",
                    [("component", "Component"), ("resistanceKn", "Resistance", "kN")],
                    [
                        {
                            "component": "Entered stabilizing load friction",
                            "resistanceKn": values["verticalLoadKn"]
                            * math.tan(math.radians(values["interfaceAngleDeg"])),
                        },
                        {
                            "component": "Interface adhesion",
                            "resistanceKn": values["cohesionKpa"] * values["contactAreaM2"],
                        },
                        {"component": "Uplift action", "resistanceKn": values["horizontalLoadKn"]},
                    ],
                )
            ],
            notes=[
                "This interface resistance check uses entered loads and parameters; groundwater uplift force must be calculated from the actual geometry and water level."
            ],
        )
    if fid == "soilDesign.overturningAdvice":
        resisting = values["verticalLoadKn"] * values["baseWidthM"] / 2
        overturning = values["horizontalLoadKn"] * values["loadHeightM"]
        fs = resisting / overturning if overturning else math.inf
        e = (
            (overturning - resisting) / values["verticalLoadKn"]
            if values["verticalLoadKn"]
            else math.inf
        )
        return result(
            summary={
                "resistingMomentKnM": resisting,
                "overturningMomentKnM": overturning,
                "factorOfSafety": fs,
                "resultantEccentricityM": e,
            },
            tables=[
                table(
                    "Overturning moment balance",
                    [("component", "Component"), ("momentKnM", "Moment", "kN·m")],
                    [
                        {"component": "Resisting", "momentKnM": resisting},
                        {"component": "Overturning", "momentKnM": overturning},
                    ],
                )
            ],
            notes=[
                "Resisting arm is taken as half the base width from the toe; include uplift, eccentric dead load and construction stages in a project-specific check."
            ],
        )
    if fid == "soilDesign.eccentricityAdvice":
        e = values["momentKnM"] / values["verticalLoadKn"]
        kern = values["baseWidthM"] / 6
        return result(
            summary={
                "eccentricityM": e,
                "middleThirdLimitM": kern,
                "fullContact": abs(e) <= kern,
                "resultantWithinBase": abs(e) <= values["baseWidthM"] / 2,
            },
            tables=[
                table(
                    "Footing resultant position",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Resultant eccentricity [m]", "value": e},
                        {"parameter": "Middle-third limit [m]", "value": kern},
                        {"parameter": "Base edge limit [m]", "value": values["baseWidthM"] / 2},
                    ],
                )
            ],
            notes=[
                "For a rectangular strip footing, the middle-third rule keeps the linear soil contact pressure compressive; e outside B/2 means equilibrium cannot be maintained by soil compression alone."
            ],
        )
    report = require_report(ctx)
    data = _parameter_rows(report)
    if not data:
        raise FeatureInputError("Add borehole layers before deriving design soil parameters.")
    if fid in {
        "soilDesign.designParameterSets",
        "soilDesign.parameterTable",
        "soilDesign.adoptParameters",
        "soilDesign.characteristicValues",
        "soilDesign.parameterTraceability",
    }:
        if fid == "soilDesign.parameterTraceability":
            rows = [
                {
                    "borehole": row["borehole"],
                    "layer": row["layer"],
                    "soilType": row["soilType"],
                    "parameter": key,
                    "value": row[col],
                    "source": row["sources"].get(key),
                }
                for row in data
                for key, col in (
                    ("unitWeight", "gammaKnM3"),
                    ("cu", "cuKpa"),
                    ("c", "cKpa"),
                    ("phi", "phiDeg"),
                    ("E", "EMpa"),
                    ("finesContent", "finesPct"),
                )
                if row[col] is not None
            ]
            return result_rows(
                "Parameter source traceability",
                [
                    ("borehole", "Borehole"),
                    ("layer", "Layer"),
                    ("soilType", "Soil type"),
                    ("parameter", "Parameter"),
                    ("value", "Value"),
                    ("source", "Resolved from"),
                ],
                rows,
                summary={"parameterValuesCount": len(rows)},
                notes=[
                    "Sources distinguish logged values, lab samples, engineering correlations and typical defaults as resolved by the profile engine."
                ],
            )
        if fid == "soilDesign.characteristicValues":
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in data:
                grouped.setdefault(row["uscs"] or row["soilType"], []).append(row)
            rows = []
            for zone, layers in sorted(grouped.items()):
                for key, column in (
                    ("cuKpa", "cu"),
                    ("cKpa", "c"),
                    ("phiDeg", "phi"),
                    ("gammaKnM3", "gamma"),
                    ("EMpa", "E"),
                ):
                    vals = [row[key] for row in layers if row[key] is not None]
                    if vals:
                        avg = fmean(vals)
                        low = avg if len(vals) == 1 else avg - 1.64 * stdev(vals)
                        rows.append(
                            {
                                "zone": zone,
                                "parameter": column,
                                "observations": len(vals),
                                "mean": avg,
                                "sampleStdDev": 0.0 if len(vals) == 1 else stdev(vals),
                                "lowerCharacteristic": max(0.0, low),
                            }
                        )
            return result_rows(
                "Indicative characteristic soil values",
                [
                    ("zone", "Zone"),
                    ("parameter", "Parameter"),
                    ("observations", "Observations"),
                    ("mean", "Mean"),
                    ("sampleStdDev", "Sample standard deviation"),
                    ("lowerCharacteristic", "Mean − 1.64s lower value"),
                ],
                rows,
                summary={
                    "zonesCount": len({row["zone"] for row in rows}),
                    "parametersCount": len(rows),
                },
                notes=[
                    "The lower value uses mean − 1.64s as a transparent one-sided statistical screen; correlated and default values are included, so confirm independence and select the characteristic value for the actual limit state."
                ],
            )
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in data:
            groups.setdefault(row["uscs"] or row["soilType"], []).append(row)
        rows = [
            {
                "parameterSet": zone,
                "soilType": layers[0]["soilType"],
                "layerObservations": len(layers),
                "boreholes": ", ".join(sorted({row["borehole"] for row in layers})),
                "meanPhiDeg": _mean(layers, "phiDeg"),
                "meanCuKpa": _mean(layers, "cuKpa"),
                "meanGammaKnM3": _mean(layers, "gammaKnM3"),
                "meanEMpa": _mean(layers, "EMpa"),
            }
            for zone, layers in sorted(groups.items())
        ]
        title = (
            "Adopted parameter set candidates"
            if fid == "soilDesign.adoptParameters"
            else "Design soil parameter sets"
            if fid == "soilDesign.designParameterSets"
            else "Soil parameter table"
        )
        return result_rows(
            title,
            [
                ("parameterSet", "Parameter set / zone"),
                ("soilType", "Soil type"),
                ("layerObservations", "Layer observations"),
                ("boreholes", "Boreholes"),
                ("meanPhiDeg", "Mean φ'", "°"),
                ("meanCuKpa", "Mean cu", "kPa"),
                ("meanGammaKnM3", "Mean γ", "kN/m³"),
                ("meanEMpa", "Mean E", "MPa"),
            ],
            rows,
            summary={"parameterSetsCount": len(rows), "layerObservationsCount": len(data)},
            notes=[
                "Candidate parameter sets group matching USCS symbols, falling back to soil type. This feature reports candidates and does not write design choices back into the Soil Report."
            ],
        )
    if fid == "soilDesign.effectiveStress":
        bh = next(
            (b for b in report.boreholes if b.id == (values.get("boreholeId") or "")),
            report.boreholes[0],
        )
        prof = profile(report, bh)
        z = values.get("depthM", 5.0)
        rows = [
            {
                "depthM": z,
                "totalStressKpa": prof.sigma_v(z),
                "porePressureKpa": prof.u(z),
                "effectiveStressKpa": prof.sigma_v_eff(z),
                "waterTableDepthM": prof.water_table,
            }
        ]
        return result_rows(
            "Vertical stress profile",
            [
                ("depthM", "Depth", "m"),
                ("totalStressKpa", "Total stress", "kPa"),
                ("porePressureKpa", "Hydrostatic u", "kPa"),
                ("effectiveStressKpa", "Effective stress", "kPa"),
                ("waterTableDepthM", "Water table", "m"),
            ],
            rows,
            summary={"depthM": z, "effectiveStressKpa": rows[0]["effectiveStressKpa"]},
            notes=[
                "σ'v = σv − u; stresses are integrated layerwise from ground level using the logged water table."
            ],
        )
    if fid == "soilDesign.shearModulus":
        bh = next(
            (b for b in report.boreholes if b.id == (values.get("boreholeId") or "")),
            report.boreholes[0],
        )
        layer = profile(report, bh).layer_at(values.get("depthM", 5.0))
        if layer is None or layer.E is None:
            raise FeatureInputError(
                "No resolved Young's modulus is available at the selected depth."
            )
        shear = layer.E / (2 * (1 + values["poissonRatio"]))
        return result(
            summary={
                "youngsModulusMpa": layer.E,
                "shearModulusMpa": shear,
                "poissonRatio": values["poissonRatio"],
            },
            tables=[
                table(
                    "Elastic modulus conversion",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "E [MPa]", "value": layer.E},
                        {"parameter": "ν [-]", "value": values["poissonRatio"]},
                        {"parameter": "G [MPa]", "value": shear},
                    ],
                )
            ],
            notes=[
                "Isotropic linear-elastic relation G = E/[2(1 + ν)]; use strain-compatible modulus for seismic or cyclic analysis."
            ],
        )
    if fid == "soilDesign.earthPressureCoefficients":
        from saengine.soil.earth_pressure import rankine_active, rankine_passive

        rows = []
        for row in data:
            if row["phiDeg"] is not None:
                phi = row["phiDeg"]
                rows.append(
                    {
                        "borehole": row["borehole"],
                        "layer": row["layer"],
                        "phiDeg": phi,
                        "ka": rankine_active(phi),
                        "k0": 1 - math.sin(math.radians(phi)),
                        "kp": rankine_passive(phi),
                    }
                )
        if not rows:
            raise FeatureInputError(
                "No resolved friction angle is available for earth-pressure coefficients."
            )
        return result_rows(
            "Earth-pressure coefficients by layer",
            [
                ("borehole", "Borehole"),
                ("layer", "Layer"),
                ("phiDeg", "φ'", "°"),
                ("ka", "Active Ka"),
                ("k0", "At-rest K0"),
                ("kp", "Passive Kp"),
            ],
            rows,
            summary={"layersCount": len(rows)},
            notes=[
                "Rankine coefficients assume a vertical smooth wall and level backfill; K0 = 1 − sin φ' is the normally consolidated Jaky estimate."
            ],
        )
    if fid in {
        "soilDesign.allowablePressure",
        "soilDesign.footingSizeAdvice",
        "soilDesign.settlementEstimate",
        "soilDesign.pileCapacityAdvice",
        "soilDesign.negativeFriction",
        "soilDesign.pileGroupSettlement",
        "soilDesign.drivenResistance",
        "soilDesign.wallFrictionAngle",
        "soilDesign.baseFriction",
        "soilDesign.uncertaintySummary",
        "soilDesign.sensitivityStudy",
        "soilDesign.designNoteExport",
    }:
        bh = next(
            (b for b in report.boreholes if b.id == (values.get("boreholeId") or "")),
            report.boreholes[0],
        )
        prof = profile(report, bh)
        from saengine.report.clauses import in_force
        from saengine.soil import bearing as bearing_engine
        from saengine.soil import piles as pile_engine
        from saengine.soil import settlement as settlement_engine

        b = values.get("widthM", report.design.subgradeWidth / 1000)
        l = values.get("lengthM", b)
        df = values.get("depthM", report.design.subgradeDepth / 1000)
        q = values.get("pressureKpa", 100.0)
        with in_force(ctx.root):
            if fid == "soilDesign.allowablePressure":
                out = bearing_engine.allowable(prof, b, l, df)
                return result(
                    summary={
                        "allowableKpa": out["qa"],
                        "shearControlledKpa": out["qa_shear"],
                        "settlementControlledKpa": out["qa_settlement"],
                        "governing": out["governs"],
                        "boreholeId": bh.id,
                    },
                    tables=[
                        table(
                            "Allowable footing pressure",
                            [("parameter", "Parameter"), ("value", "Value")],
                            [
                                {"parameter": "Footing width [m]", "value": b},
                                {"parameter": "Footing length [m]", "value": l},
                                {"parameter": "Founding depth [m]", "value": df},
                                {"parameter": "Allowable pressure [kPa]", "value": out["qa"]},
                                {"parameter": "Shear limit [kPa]", "value": out["qa_shear"]},
                                {
                                    "parameter": "Settlement limit [kPa]",
                                    "value": out["qa_settlement"],
                                },
                            ],
                        )
                    ],
                    notes=[
                        out["shear"] or "No shear resistance result.",
                        out["settlement"] or "No settlement result.",
                        *out["notes"],
                    ],
                )
            if fid == "soilDesign.footingSizeAdvice":
                load, maximum = values["loadKn"], values["maximumWidthM"]
                lo, hi = 0.5, maximum
                best = None
                for _ in range(28):
                    width = (lo + hi) / 2
                    qa = bearing_engine.allowable(prof, width, width, df)["qa"]
                    pressure = load / width**2
                    if qa is not None and pressure <= qa:
                        best = (width, pressure, qa)
                        hi = width
                    else:
                        lo = width
                if best is None:
                    raise FeatureInputError(
                        "No square footing up to the entered maximum width meets the engine bearing check; increase the trial range or revise the foundation concept."
                    )
                width, pressure, qa = best
                return result(
                    summary={
                        "recommendedWidthM": width,
                        "recommendedLengthM": width,
                        "servicePressureKpa": pressure,
                        "allowableKpa": qa,
                        "loadKn": load,
                    },
                    tables=[
                        table(
                            "Square footing sizing iteration",
                            [
                                ("widthM", "Width", "m"),
                                ("servicePressureKpa", "Service pressure", "kPa"),
                                ("allowableKpa", "Allowable", "kPa"),
                            ],
                            [{"widthM": width, "servicePressureKpa": pressure, "allowableKpa": qa}],
                        )
                    ],
                    notes=[
                        "Smallest width found by bisection on the active soil-engine bearing and settlement checks; this advice does not check structural footing strength or column moments."
                    ],
                )
            if fid == "soilDesign.settlementEstimate":
                out = settlement_engine.settlement(prof, b, l, df, q)
                return result(
                    summary={
                        "immediateSettlementMm": out["immediate"],
                        "primaryConsolidationMm": out["consolidation"],
                        "secondarySettlementMm": out["secondary"],
                        "totalSettlementMm": out["total"],
                        "pressureKpa": q,
                    },
                    tables=[
                        table(
                            "Footing settlement by layer",
                            [
                                ("layer", "Layer"),
                                ("soil", "Soil type"),
                                ("top", "Top depth", "mm"),
                                ("bottom", "Bottom depth", "mm"),
                                ("immediate", "Immediate", "mm"),
                                ("consolidation", "Consolidation", "mm"),
                                ("method", "Method"),
                            ],
                            [
                                {
                                    "layer": row["layer"],
                                    "soil": row["soilType"],
                                    "top": row["top"],
                                    "bottom": row["bottom"],
                                    "immediate": row["immediate"],
                                    "consolidation": row["consolidation"],
                                    "method": ", ".join(row["method"])
                                    if isinstance(row["method"], list)
                                    else row["method"],
                                }
                                for row in out["layers"]
                            ],
                        )
                    ],
                    notes=[*out["notes"]],
                )
            if fid in {"soilDesign.pileCapacityAdvice", "soilDesign.drivenResistance"}:
                rows = pile_engine.pile_parameters(prof)
                if fid == "soilDesign.drivenResistance":
                    prof.design.pile.type = "driven"
                    rows = pile_engine.pile_parameters(prof)
                if not any(row.get("fs") is not None for row in rows):
                    raise FeatureInputError(
                        "No pile shaft resistance is available from the logged soil properties and active pack."
                    )
                dia = values.get("pileDiameterM", 0.6)
                length = values.get("pileLengthM", prof.bottom)
                side = sum(
                    row["fs"]
                    * math.pi
                    * dia
                    * max(0.0, min(row["bottom"] / 1000, length) - row["top"] / 1000)
                    for row in rows
                    if row.get("fs") is not None
                )
                base_row = next(
                    (
                        row
                        for row in reversed(rows)
                        if row.get("qb") is not None and row["bottom"] / 1000 >= length
                    ),
                    next((row for row in reversed(rows) if row.get("qb") is not None), {}),
                )
                base = base_row.get("qb", 0.0) * math.pi * dia**2 / 4
                return result(
                    summary={
                        "shaftResistanceKn": side,
                        "baseResistanceKn": base,
                        "ultimateCapacityKn": side + base,
                        "pileDiameterM": dia,
                        "pileLengthM": length,
                        "analysisType": "driven"
                        if fid.endswith("drivenResistance")
                        else report.design.pile.type,
                    },
                    tables=[
                        table(
                            "Pile unit resistance by layer",
                            [
                                ("layer", "Layer"),
                                ("top", "Top", "mm"),
                                ("bottom", "Bottom", "mm"),
                                ("fs", "Unit shaft resistance", "kPa"),
                                ("qb", "Unit base resistance", "kPa"),
                                ("method", "Method"),
                                ("note", "Notes"),
                            ],
                            rows,
                        )
                    ],
                    notes=[
                        "Ultimate shaft and toe resistances are integrated over the entered diameter and length; apply the active design factor and construction-specific exclusions in the foundation design."
                    ],
                )
            if fid == "soilDesign.negativeFriction":
                dia = values["pileDiameterM"]
                downdrag = 0.0
                rows = []
                for layer in prof.layers:
                    if layer.behaviour == "cohesive" and layer.cu is not None:
                        fs = 0.5 * layer.cu
                    elif layer.behaviour == "granular":
                        fs = 0.25 * prof.sigma_v_eff(layer.mid)
                    else:
                        continue
                    force = fs * math.pi * dia * (layer.bottom - layer.top)
                    downdrag += force
                    rows.append(
                        {
                            "layer": layer.index + 1,
                            "soilType": layer.soil_type,
                            "topM": layer.top,
                            "bottomM": layer.bottom,
                            "negativeShaftKpa": fs,
                            "downdragKn": force,
                        }
                    )
                if not rows:
                    raise FeatureInputError(
                        "No compressible soil layers are available for a downdrag screening estimate."
                    )
                return result_rows(
                    "Negative skin-friction screening",
                    [
                        ("layer", "Layer"),
                        ("soilType", "Soil type"),
                        ("topM", "Top", "m"),
                        ("bottomM", "Bottom", "m"),
                        ("negativeShaftKpa", "Negative shaft stress", "kPa"),
                        ("downdragKn", "Downdrag", "kN"),
                    ],
                    rows,
                    summary={"totalDowndragKn": downdrag, "pileDiameterM": dia},
                    notes=[
                        "Screening assumes negative shaft stress of 0.5cu in cohesive layers and 0.25σ'v in granular layers; actual neutral plane and downdrag require consolidation and load-transfer analysis."
                    ],
                )
            if fid == "soilDesign.pileGroupSettlement":
                gw, gl, load = values["groupWidthM"], values["groupLengthM"], values["loadKn"]
                out = settlement_engine.settlement(
                    prof, gw, gl, df, load / (gw * gl), foundation="raft"
                )
                return result(
                    summary={
                        "equivalentGroupWidthM": gw,
                        "equivalentGroupLengthM": gl,
                        "settlementMm": out["total"],
                        "pressureKpa": load / (gw * gl),
                    },
                    tables=[
                        table(
                            "Equivalent raft settlement layers",
                            [
                                ("layer", "Layer"),
                                ("soil", "Soil type"),
                                ("total", "Settlement", "mm"),
                                ("method", "Method"),
                            ],
                            [
                                {
                                    "layer": row["layer"],
                                    "soil": row["soilType"],
                                    "total": row["total"],
                                    "method": ", ".join(row["method"])
                                    if isinstance(row["method"], list)
                                    else row["method"],
                                }
                                for row in out["layers"]
                            ],
                        )
                    ],
                    notes=[
                        "Pile group is represented by an equivalent rectangular raft at founding depth; group interaction and pile-to-soil load transfer are not explicitly modelled."
                    ],
                )
            if fid in {"soilDesign.wallFrictionAngle", "soilDesign.baseFriction"}:
                layer = prof.layer_at(df)
                if layer is None or layer.phi is None:
                    raise FeatureInputError(
                        "No resolved friction angle is available at the selected depth."
                    )
                angle = values["interfaceRatio"] * layer.phi
                coefficient = math.tan(math.radians(angle))
                title = (
                    "Wall friction interface"
                    if fid.endswith("wallFrictionAngle")
                    else "Footing base friction interface"
                )
                return result(
                    summary={
                        "soilFrictionAngleDeg": layer.phi,
                        "interfaceAngleDeg": angle,
                        "frictionCoefficient": coefficient,
                    },
                    tables=[
                        table(
                            title,
                            [("parameter", "Parameter"), ("value", "Value")],
                            [
                                {"parameter": "Soil φ' [°]", "value": layer.phi},
                                {
                                    "parameter": "Interface ratio δ/φ [-]",
                                    "value": values["interfaceRatio"],
                                },
                                {"parameter": "Interface δ [°]", "value": angle},
                                {"parameter": "tan δ [-]", "value": coefficient},
                            ],
                        )
                    ],
                    notes=[
                        "Interface angle is an entered fraction of the layer friction angle; use interface testing or a project-specific construction assumption for final design."
                    ],
                )
    if fid == "soilDesign.uncertaintySummary":
        rows = []
        for key, title, unit in (
            ("phiDeg", "Friction angle", "°"),
            ("cuKpa", "Undrained strength", "kPa"),
            ("gammaKnM3", "Unit weight", "kN/m³"),
            ("EMpa", "Young's modulus", "MPa"),
        ):
            vals = [row[key] for row in data if row[key] is not None]
            if vals:
                rows.append(
                    {
                        "parameter": title,
                        "observations": len(vals),
                        "minimum": min(vals),
                        "mean": fmean(vals),
                        "maximum": max(vals),
                        "coefficientVariation": stdev(vals) / fmean(vals)
                        if len(vals) > 1 and fmean(vals)
                        else 0.0,
                        "unit": unit,
                    }
                )
        return result_rows(
            "Soil parameter uncertainty summary",
            [
                ("parameter", "Parameter"),
                ("observations", "Observations"),
                ("minimum", "Minimum"),
                ("mean", "Mean"),
                ("maximum", "Maximum"),
                ("coefficientVariation", "Coefficient of variation"),
                ("unit", "Unit"),
            ],
            rows,
            summary={"parametersSummarizedCount": len(rows)},
            notes=[
                "Statistics describe resolved values across logged layers; they combine measured and correlated values and are not a probabilistic reliability model."
            ],
        )
    if fid == "soilDesign.sensitivityStudy":
        from saengine.soil import bearing as bearing_engine

        layer = prof.layer_at(df)
        if layer is None:
            raise FeatureInputError("No soil layer is logged at the selected founding depth.")
        phi = layer.phi or 0.0
        c = layer.cu if layer.behaviour == "cohesive" and layer.cu is not None else layer.c
        gamma = layer.gamma
        rows = []
        for dphi in (-5.0, 0.0, 5.0):
            for factor in (0.8, 1.0, 1.2):
                qu = bearing_engine.ultimate(
                    (c or 0.0) * factor,
                    max(0.0, phi + dphi),
                    prof.sigma_v_eff(df),
                    gamma * factor,
                    b,
                    l,
                    df,
                )["qu"]
                rows.append({"deltaPhiDeg": dphi, "strengthFactor": factor, "ultimateKpa": qu})
        return result_rows(
            "Bearing sensitivity grid",
            [
                ("deltaPhiDeg", "Δφ'", "°"),
                ("strengthFactor", "c and γ factor"),
                ("ultimateKpa", "Ultimate pressure", "kPa"),
            ],
            rows,
            summary={
                "minimumUltimateKpa": min(row["ultimateKpa"] for row in rows),
                "maximumUltimateKpa": max(row["ultimateKpa"] for row in rows),
            },
            notes=[
                "Vesic/general bearing is recalculated over φ' ±5° and c, γ ×0.8-1.2; the active code pack may supply its own bearing factors."
            ],
        )
    if fid == "soilDesign.designNoteExport":
        rows = [
            f"# Geotechnical design note — {report.report.title or 'Soil Report'}",
            "",
            f"Borehole: {bh.id}",
            f"Footing: {b:g} × {l:g} m at {df:g} m depth",
            f"Applied pressure: {q:g} kPa",
            "",
            "## Resolved soil parameters",
            "",
            "| Layer | Soil | Depth [m] | γ [kN/m³] | cu [kPa] | φ' [°] | E [MPa] |",
            "|---:|---|---:|---:|---:|---:|---:|",
        ]
        rows.extend(
            f"| {row['layer']} | {row['soilType']} | {row['topDepthM']:.2f}–{row['bottomDepthM']:.2f} | {row['gammaKnM3']:.2f} | {row['cuKpa'] if row['cuKpa'] is not None else '—'} | {row['phiDeg'] if row['phiDeg'] is not None else '—'} | {row['EMpa'] if row['EMpa'] is not None else '—'} |"
            for row in data
            if row["borehole"] == bh.id
        )
        content = (
            "\n".join(rows)
            + "\n\nValues are resolved by the soil profile engine from logged data, lab samples and documented correlations. Confirm project-specific design assumptions before issue.\n"
        )
        path = save_text(ctx, "01 Soil Report/exports/geotechnical-design-note.md", content)
        return result(
            summary={
                "exportPath": path,
                "boreholeId": bh.id,
                "layersCount": len([row for row in data if row["borehole"] == bh.id]),
            },
            notes=[f"Design note written to {path}."],
        )
    raise FeatureInputError(
        "The requested soil-design feature needs project inputs or a supported analysis record."
    )


def _mean(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [row[key] for row in rows if row[key] is not None]
    return fmean(vals) if vals else None


register_tab("soilDesign", _handle, requires_project=_needs_project, fields=_fields)
