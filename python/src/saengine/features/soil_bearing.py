"""Soil Report bearing, settlement, ground-improvement and support analyses."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import number, result, table, text
from saengine.features.soil_feature_utils import (
    FeatureInputError,
    common_fields,
    profile,
    register_tab,
    require_report,
    result_rows,
)


def _fields(fid: str) -> list[Any]:
    if fid == "soilBearing.plateLoadTest":
        return [text("loadSettlement", "Pressure [kPa], settlement [mm] pairs", "")]
    if fid == "soilBearing.presumptiveValues":
        return [text("uscs", "USCS group to highlight", "")]
    if fid in {
        "soilBearing.limitEquilibriumLem",
        "soilBearing.strengthReductionFem",
        "soilBearing.criticalSlipSurface",
        "soilBearing.factorOfSafetyMap",
    }:
        return [
            number(
                "slopeAngleDeg", "Slope angle from horizontal [°]", 30.0, unit="°", min=1, max=80
            ),
            number("depthM", "Potential slide depth [m]", 2.0, unit="m", min=0.1),
            number("cohesionKpa", "Effective cohesion c' [kPa]", 10.0, unit="kPa", min=0),
            number("phiDeg", "Effective friction angle φ' [°]", 30.0, unit="°", min=0, max=50),
            number("gammaKnM3", "Soil unit weight [kN/m³]", 18.0, unit="kN/m³", min=1),
            number("ru", "Pore-pressure ratio ru", 0.0, min=0, max=1),
        ]
    if fid == "soilBearing.stoneColumnDesign":
        return [
            number("columnDiameterM", "Column diameter [m]", 0.8, unit="m", min=0.1),
            number("spacingM", "Column spacing [m]", 2.0, unit="m", min=0.2),
            number("stressConcentration", "Column-to-soil stress ratio", 4.0, min=1),
            number(
                "targetPressureKpa", "Target composite pressure [kPa]", 150.0, unit="kPa", min=1
            ),
            number("soilCuKpa", "Native soil cu [kPa]", 30.0, unit="kPa", min=0.1),
            number("columnPhiDeg", "Column friction angle [°]", 38.0, unit="°", min=0, max=50),
        ]
    if fid == "soilBearing.dynamicCompaction":
        return [
            number("dropMassTonnes", "Tamper mass [tonnes]", 10.0, unit="tonnes", min=0.1),
            number("dropHeightM", "Drop height [m]", 15.0, unit="m", min=0.1),
            number("coefficient", "Depth coefficient α", 0.5, min=0.1, max=1.0),
            number("passes", "Passes per point", 8.0, min=1),
        ]
    if fid == "soilBearing.raftPressureCheck":
        return [
            number("lengthM", "Raft length [m]", 20.0, unit="m", min=0.1),
            number("widthM", "Raft width [m]", 15.0, unit="m", min=0.1),
            number("verticalLoadKn", "Vertical load [kN]", 30000.0, unit="kN", min=0),
            number("momentXKnM", "Moment about X [kN·m]", 0.0, unit="kN·m"),
            number("momentYKnM", "Moment about Y [kN·m]", 0.0, unit="kN·m"),
        ]
    if fid == "soilBearing.buoyancyCheck":
        return [
            number("planAreaM2", "Raft plan area [m²]", 300.0, unit="m²", min=0.1),
            number("thicknessM", "Raft thickness [m]", 1.0, unit="m", min=0.05),
            number("embedmentM", "Raft soffit depth [m]", 3.0, unit="m", min=0),
            number("waterTableM", "Water-table depth below grade [m]", 1.0, unit="m", min=0),
            number("concreteUnitWeight", "Concrete unit weight [kN/m³]", 24.0, unit="kN/m³", min=1),
            number(
                "superimposedDeadKn",
                "Superimposed stabilizing dead load [kN]",
                0.0,
                unit="kN",
                min=0,
            ),
        ]
    return common_fields(fid)


def _needs_project(fid: str) -> bool:
    return fid not in {
        "soilBearing.plateLoadTest",
        "soilBearing.presumptiveValues",
        "soilBearing.limitEquilibriumLem",
        "soilBearing.strengthReductionFem",
        "soilBearing.criticalSlipSurface",
        "soilBearing.factorOfSafetyMap",
        "soilBearing.stoneColumnDesign",
        "soilBearing.dynamicCompaction",
        "soilBearing.raftPressureCheck",
        "soilBearing.buoyancyCheck",
    }


def _infinite_slope(values: dict[str, Any], reduction: float = 1.0) -> float:
    beta = math.radians(values["slopeAngleDeg"])
    phi = math.atan(math.tan(math.radians(values["phiDeg"])) / reduction)
    c = values["cohesionKpa"] / reduction
    gamma, z, ru = values["gammaKnM3"], values["depthM"], values["ru"]
    normal = gamma * z * math.cos(beta) ** 2 * (1 - ru)
    driving = gamma * z * math.sin(beta) * math.cos(beta)
    if driving <= 0:
        raise FeatureInputError("Slope geometry must give a positive downslope driving stress.")
    return (c + normal * math.tan(phi)) / driving


def _handle(fid: str, ctx: Any, values: dict[str, Any]) -> dict[str, Any]:
    if fid == "soilBearing.plateLoadTest":
        raw = values["loadSettlement"].replace(";", "\n")
        points = []
        for line_no, line in enumerate(raw.splitlines(), 1):
            if not line.strip():
                continue
            bits = [x.strip() for x in line.split(",")]
            if len(bits) != 2:
                raise FeatureInputError(f"Plate-load row {line_no} must be pressure,settlement.")
            try:
                pressure, settlement = map(float, bits)
            except ValueError:
                raise FeatureInputError(
                    f"Plate-load row {line_no} contains a non-numeric value."
                ) from None
            if pressure < 0 or settlement < 0:
                raise FeatureInputError("Plate pressure and settlement must be non-negative.")
            points.append((pressure, settlement))
        if len(points) < 2:
            raise FeatureInputError("Enter at least two plate-load pressure,settlement pairs.")
        points.sort()
        first = next(((q, s) for q, s in points if s > 0), None)
        if first is None:
            raise FeatureInputError(
                "At least one plate-load reading must have positive settlement."
            )
        modulus = first[0] / (first[1] / 1000)
        rows = [
            {
                "pressureKpa": q,
                "settlementMm": s,
                "secantModulusKpaPerM": q / (s / 1000) if s else None,
            }
            for q, s in points
        ]
        return result(
            summary={
                "initialSecantModulusKpaPerM": modulus,
                "maximumPressureKpa": max(q for q, _ in points),
                "readingsCount": len(rows),
            },
            tables=[
                table(
                    "Plate-load observations",
                    [
                        ("pressureKpa", "Pressure", "kPa"),
                        ("settlementMm", "Settlement", "mm"),
                        ("secantModulusKpaPerM", "Secant modulus", "kN/m³"),
                    ],
                    rows,
                )
            ],
            notes=[
                "Secant modulus is pressure divided by measured settlement; transfer from plate to footing size and embedment requires an explicit scale correction."
            ],
        )
    if fid == "soilBearing.presumptiveValues":
        from saengine.codes import context as code_context
        from saengine.report.clauses import in_force

        with in_force(ctx.root):
            shallow = code_context.table("foundations").shallow
            rows = [
                {
                    "class": row.id,
                    "description": row.name,
                    "uscsGroups": ", ".join(row.groups),
                    "allowableKpa": row.qa,
                    "waterReduction": row.waterReduction,
                }
                for row in shallow.presumptive
            ]
            reduction = shallow.presumptiveWaterReduction
            selected = (
                next(
                    (row for row in rows if values["uscs"].upper() in row["uscsGroups"].upper()),
                    None,
                )
                if values["uscs"]
                else None
            )
        return result(
            summary={
                "classesCount": len(rows),
                "selectedAllowableKpa": selected["allowableKpa"] if selected else None,
                "waterReductionShare": reduction,
            },
            tables=[
                table(
                    "Pack presumptive bearing values",
                    [
                        ("class", "Class"),
                        ("description", "Soil description"),
                        ("uscsGroups", "USCS groups"),
                        ("allowableKpa", "Allowable pressure", "kPa"),
                        ("waterReduction", "Reduced near water"),
                    ],
                    rows,
                )
            ],
            notes=[
                "Values and groundwater reduction are read from the active foundations code pack. A presumptive value is for preliminary checks within its stated applicability; weak fill and organic soil require investigation."
            ],
        )
    if fid in {
        "soilBearing.limitEquilibriumLem",
        "soilBearing.strengthReductionFem",
        "soilBearing.criticalSlipSurface",
        "soilBearing.factorOfSafetyMap",
    }:
        fs = _infinite_slope(values)
        rows = [
            {
                "reductionFactor": factor,
                "reducedStrengthFactorOfSafety": _infinite_slope(values, factor),
            }
            for factor in (1.0, 1.25, 1.5, 2.0)
        ]
        if fid == "soilBearing.strengthReductionFem":
            lo, hi = 0.1, 10.0
            for _ in range(60):
                mid = (lo + hi) / 2
                if _infinite_slope(values, mid) > 1:
                    lo = mid
                else:
                    hi = mid
            sr = (lo + hi) / 2
            return result(
                summary={
                    "strengthReductionFactor": sr,
                    "factorOfSafety": fs,
                    "method": "infinite-slope strength-reduction surrogate",
                },
                tables=[
                    table(
                        "Strength reduction sweep",
                        [
                            ("reductionFactor", "Strength reduction factor"),
                            ("reducedStrengthFactorOfSafety", "Reduced-strength FS"),
                        ],
                        rows,
                    )
                ],
                notes=[
                    "This analytical infinite-slope strength-reduction surrogate divides cohesion and tan φ by a trial factor; it is not a finite-element mesh solution. Use a soil FEM model for complex geometry, staged excavation or non-circular failure."
                ],
            )
        if fid == "soilBearing.criticalSlipSurface":
            return result(
                summary={
                    "minimumFactorOfSafety": fs,
                    "candidateDepthM": values["depthM"],
                    "candidatePlaneAngleDeg": values["slopeAngleDeg"],
                },
                tables=[
                    table(
                        "Planar slip candidate",
                        [("parameter", "Parameter"), ("value", "Value")],
                        [
                            {"parameter": "Potential slide depth [m]", "value": values["depthM"]},
                            {"parameter": "Slope angle [°]", "value": values["slopeAngleDeg"]},
                            {"parameter": "Factor of safety [-]", "value": fs},
                        ],
                    )
                ],
                notes=[
                    "The candidate is a planar infinite-slope surface at the entered depth and angle. A circular-slip search needs site topography and strength zoning not present in the Soil Report model."
                ],
            )
        return result(
            summary={
                "factorOfSafety": fs,
                "stableAtUnity": fs >= 1.0,
                "analysisModel": "infinite slope",
            },
            tables=[
                table(
                    "Slope stability stress check",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Slope angle [°]", "value": values["slopeAngleDeg"]},
                        {"parameter": "Potential slide depth [m]", "value": values["depthM"]},
                        {"parameter": "Pore-pressure ratio [-]", "value": values["ru"]},
                        {"parameter": "Factor of safety [-]", "value": fs},
                    ],
                )
            ],
            notes=[
                "Ordinary-method infinite-slope equilibrium is used: FS = [c' + (1−ru)γz cos²β tanφ']/[γz sinβ cosβ]. A factor of safety map requires multiple site slope nodes and is represented here by the input stress point."
            ],
        )
    if fid == "soilBearing.stoneColumnDesign":
        d, s, n = values["columnDiameterM"], values["spacingM"], values["stressConcentration"]
        area = math.pi * d**2 / 4
        tributary = s**2 if s > 0 else 0
        ar = area / tributary
        improvement = 1 + (n - 1) * ar
        stress_ratio = n / improvement
        cu = values["soilCuKpa"]
        column_capacity = (1 + math.sin(math.radians(values["columnPhiDeg"]))) / (
            1 - math.sin(math.radians(values["columnPhiDeg"]))
        )
        composite = cu * 5.14 * improvement
        return result(
            summary={
                "areaReplacementRatio": ar,
                "stressConcentrationRatio": stress_ratio,
                "estimatedCompositeCapacityKpa": composite,
                "targetPressureKpa": values["targetPressureKpa"],
                "targetMet": composite >= values["targetPressureKpa"],
            },
            tables=[
                table(
                    "Stone-column unit cell",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Column area [m²]", "value": area},
                        {"parameter": "Square unit-cell area [m²]", "value": tributary},
                        {"parameter": "Area replacement ratio [-]", "value": ar},
                        {"parameter": "Column bearing factor [-]", "value": column_capacity},
                        {"parameter": "Composite capacity estimate [kPa]", "value": composite},
                    ],
                )
            ],
            notes=[
                "Equal-strain unit-cell estimate with square spacing; the composite capacity scales the native undrained Nc·cu by the area-replacement stress concentration. Settlement, bulging, installation and drainage checks are separate."
            ],
        )
    if fid == "soilBearing.dynamicCompaction":
        depth = values["coefficient"] * math.sqrt(values["dropMassTonnes"] * values["dropHeightM"])
        energy = (
            values["dropMassTonnes"] * 1000 * 9.81 * values["dropHeightM"] * values["passes"] / 1000
        )
        return result(
            summary={
                "estimatedImprovementDepthM": depth,
                "energyPerPointKj": energy,
                "passes": values["passes"],
            },
            tables=[
                table(
                    "Dynamic-compaction planning estimate",
                    [("parameter", "Parameter"), ("value", "Value")],
                    [
                        {"parameter": "Tamper mass [tonnes]", "value": values["dropMassTonnes"]},
                        {"parameter": "Drop height [m]", "value": values["dropHeightM"]},
                        {"parameter": "Estimated influence depth [m]", "value": depth},
                        {"parameter": "Energy per point [kJ]", "value": energy},
                    ],
                )
            ],
            notes=[
                "Influence depth follows D = α√(WH) with W in tonnes and H in metres. α depends on soil type and saturation; verify improvement and settlement with trial sections and field monitoring."
            ],
        )
    if fid == "soilBearing.raftPressureCheck":
        b, l, load = values["widthM"], values["lengthM"], values["verticalLoadKn"]
        q0 = load / (b * l)
        qx = 6 * values["momentYKnM"] / (b * l**2)
        qy = 6 * values["momentXKnM"] / (l * b**2)
        qmax, qmin = q0 + abs(qx) + abs(qy), q0 - abs(qx) - abs(qy)
        return result(
            summary={
                "averagePressureKpa": q0,
                "maximumPressureKpa": qmax,
                "minimumPressureKpa": qmin,
                "fullContact": qmin >= 0,
            },
            tables=[
                table(
                    "Rigid raft linear contact pressure",
                    [("location", "Location"), ("pressureKpa", "Pressure", "kPa")],
                    [
                        {"location": "Average", "pressureKpa": q0},
                        {"location": "Maximum corner", "pressureKpa": qmax},
                        {"location": "Minimum corner", "pressureKpa": qmin},
                    ],
                )
            ],
            notes=[
                "Linear elastic pressure distribution for a rigid rectangular raft under biaxial moment; moments are about the raft centroid and uplift tension is not carried by soil."
            ],
        )
    if fid == "soilBearing.buoyancyCheck":
        depth = values["embedmentM"]
        submerged = max(0.0, depth - values["waterTableM"])
        uplift = 9.81 * submerged * values["planAreaM2"]
        weight = (
            values["concreteUnitWeight"] * values["thicknessM"] * values["planAreaM2"]
            + values["superimposedDeadKn"]
        )
        fs = weight / uplift if uplift > 0 else math.inf
        return result(
            summary={
                "upliftKn": uplift,
                "stabilizingDeadLoadKn": weight,
                "upliftFactorOfSafety": fs,
                "netDownwardKn": weight - uplift,
            },
            tables=[
                table(
                    "Raft buoyancy balance",
                    [("component", "Component"), ("forceKn", "Force", "kN")],
                    [
                        {"component": "Groundwater uplift", "forceKn": uplift},
                        {"component": "Raft plus entered dead load", "forceKn": weight},
                        {"component": "Net downward", "forceKn": weight - uplift},
                    ],
                )
            ],
            notes=[
                "Hydrostatic uplift acts over the full raft area when the water table is above the soffit; only raft self-weight and entered stabilizing dead load are counted."
            ],
        )

    report = require_report(ctx)
    pairs = [(bh, profile(report, bh)) for bh in report.boreholes if bh.layers]
    if not pairs:
        raise FeatureInputError(
            "Add borehole layers before running bearing or settlement analyses."
        )
    b = values.get("widthM", report.design.subgradeWidth / 1000)
    l = values.get("lengthM", b)
    df = values.get("depthM", report.design.subgradeDepth / 1000)
    q = values.get("pressureKpa", 100.0)
    from saengine.report.clauses import in_force
    from saengine.soil import bearing as bearing_engine
    from saengine.soil import settlement as settlement_engine

    if fid in {
        "soilBearing.bearingContours",
        "soilBearing.immediateSettlement",
        "soilBearing.consolidationSettlement",
        "soilBearing.differentialSettlement",
        "soilBearing.settlementContours",
        "soilBearing.soilSprings",
        "soilBearing.subgradeModulus",
        "soilBearing.springStiffnessTable",
    }:
        results = []
        with in_force(ctx.root):
            for bh, prof in pairs:
                if fid == "soilBearing.bearingContours":
                    out = bearing_engine.allowable(prof, b, l, df)
                    results.append(
                        {
                            "borehole": bh.id,
                            "xM": bh.x / 1000,
                            "yM": bh.y / 1000,
                            "allowableKpa": out.get("qa"),
                            "ultimateKpa": out.get("qu"),
                            "foundingDepthM": df,
                        }
                    )
                elif fid in {
                    "soilBearing.immediateSettlement",
                    "soilBearing.consolidationSettlement",
                    "soilBearing.differentialSettlement",
                    "soilBearing.settlementContours",
                }:
                    out = settlement_engine.settlement(prof, b, l, df, q)
                    if fid == "soilBearing.immediateSettlement":
                        rows = [
                            {
                                "borehole": bh.id,
                                "immediateMm": out["immediate"],
                                "totalMm": out["total"],
                                "settlementPressureKpa": q,
                            }
                        ]
                    elif (
                        fid == "soilBearing.consolidationSettlement"
                        or fid == "soilBearing.differentialSettlement"
                    ):
                        rows = [
                            {
                                "borehole": bh.id,
                                "immediateMm": out["immediate"],
                                "primaryConsolidationMm": out["consolidation"],
                                "secondaryMm": out["secondary"],
                                "totalMm": out["total"],
                            }
                        ]
                    else:
                        rows = []
                    if rows:
                        results.extend(rows)
                    else:
                        results.append(
                            {
                                "borehole": bh.id,
                                "xM": bh.x / 1000,
                                "yM": bh.y / 1000,
                                "settlementMm": out["total"],
                                "immediateMm": out["immediate"],
                                "consolidationMm": out["consolidation"],
                            }
                        )
                else:
                    out = settlement_engine.settlement(prof, b, l, df, q)
                    settlement_m = out["total"] / 1000
                    k = q / settlement_m if settlement_m > 0 else None
                    results.append(
                        {
                            "borehole": bh.id,
                            "xM": bh.x / 1000,
                            "yM": bh.y / 1000,
                            "settlementMm": out["total"],
                            "verticalSubgradeKpaPerM": k,
                            "horizontalKpaPerM": None if k is None else k * 0.5,
                        }
                    )
        if fid == "soilBearing.differentialSettlement":
            values_mm = [row["totalMm"] for row in results]
            separation_m = max(
                (
                    math.hypot(a.x - b_.x, a.y - b_.y) / 1000
                    for a, _ in pairs
                    for b_, _ in pairs
                    if a.id != b_.id
                ),
                default=0,
            )
            differential = max(values_mm) - min(values_mm) if values_mm else 0
            return result(
                summary={
                    "maximumSettlementMm": max(values_mm),
                    "minimumSettlementMm": min(values_mm),
                    "differentialSettlementMm": differential,
                    "maximumAngularDistortion": differential / (separation_m * 1000)
                    if separation_m
                    else None,
                },
                tables=[
                    table(
                        "Borehole settlement comparison",
                        [
                            ("borehole", "Borehole"),
                            ("immediateMm", "Immediate", "mm"),
                            ("primaryConsolidationMm", "Primary consolidation", "mm"),
                            ("secondaryMm", "Secondary", "mm"),
                            ("totalMm", "Total", "mm"),
                        ],
                        results,
                    )
                ],
                notes=[
                    "Settlement is evaluated at each investigation borehole under the same footing dimensions and pressure. Angular distortion uses the farthest borehole spacing as a screening separation, not actual column locations."
                ],
            )
        columns = [("borehole", "Borehole")]
        if fid in {
            "soilBearing.bearingContours",
            "soilBearing.settlementContours",
            "soilBearing.soilSprings",
            "soilBearing.subgradeModulus",
            "soilBearing.springStiffnessTable",
        }:
            columns.extend([("xM", "X", "m"), ("yM", "Y", "m")])
        if fid == "soilBearing.bearingContours":
            columns.extend(
                [
                    ("allowableKpa", "Allowable pressure", "kPa"),
                    ("ultimateKpa", "Ultimate pressure", "kPa"),
                    ("foundingDepthM", "Founding depth", "m"),
                ]
            )
            return result_rows(
                "Allowable bearing control points",
                columns,
                results,
                summary={
                    "boreholesCount": len(results),
                    "minimumAllowableKpa": min(
                        (r["allowableKpa"] for r in results if r["allowableKpa"] is not None),
                        default=None,
                    ),
                },
                notes=[
                    "Each point uses the soil engine's layer-resolved bearing analysis; contouring should remain within the investigated area."
                ],
            )
        if fid == "soilBearing.immediateSettlement":
            return result_rows(
                "Immediate elastic settlement",
                [
                    ("borehole", "Borehole"),
                    ("immediateMm", "Immediate", "mm"),
                    ("totalMm", "Total", "mm"),
                    ("settlementPressureKpa", "Pressure", "kPa"),
                ],
                results,
                summary={
                    "maximumImmediateSettlementMm": max(r["immediateMm"] for r in results),
                    "maximumTotalSettlementMm": max(r["totalMm"] for r in results),
                },
                notes=[
                    "The soil settlement engine resolves layer stiffness and footing influence with the active code-pack method."
                ],
            )
        if fid == "soilBearing.consolidationSettlement":
            return result_rows(
                "Primary consolidation settlement",
                [
                    ("borehole", "Borehole"),
                    ("immediateMm", "Immediate", "mm"),
                    ("primaryConsolidationMm", "Primary consolidation", "mm"),
                    ("secondaryMm", "Secondary", "mm"),
                    ("totalMm", "Total", "mm"),
                ],
                results,
                summary={
                    "maximumPrimaryConsolidationMm": max(
                        r["primaryConsolidationMm"] for r in results
                    ),
                    "maximumTotalSettlementMm": max(r["totalMm"] for r in results),
                },
                notes=[
                    "The engine reports immediate, primary and secondary contributions separately; compression parameters come from logs, laboratory tests or stated correlations."
                ],
            )
        if fid == "soilBearing.settlementContours":
            return result_rows(
                "Settlement contour nodes",
                [
                    ("borehole", "Borehole"),
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("settlementMm", "Total settlement", "mm"),
                    ("immediateMm", "Immediate", "mm"),
                    ("consolidationMm", "Consolidation", "mm"),
                ],
                results,
                summary={
                    "nodesCount": len(results),
                    "maximumSettlementMm": max(row["settlementMm"] for row in results),
                },
                notes=[
                    "These borehole values are the input nodes behind a settlement contour; interpolation outside the investigated footprint is not implied."
                ],
            )
        return result_rows(
            "Soil spring stiffness by borehole",
            [
                ("borehole", "Borehole"),
                ("xM", "X", "m"),
                ("yM", "Y", "m"),
                ("settlementMm", "Settlement", "mm"),
                ("verticalSubgradeKpaPerM", "Vertical stiffness", "kN/m³"),
                ("horizontalKpaPerM", "Indicative horizontal stiffness", "kN/m³"),
            ],
            results,
            summary={"springsCount": len(results), "footingWidthM": b},
            notes=[
                "Vertical k is pressure divided by the computed settlement; horizontal k is a simple half-value screening assumption and should be calibrated to lateral soil response."
            ],
        )
    raise FeatureInputError(
        "The requested bearing operation needs the corresponding field-test or design data."
    )


register_tab("soilBearing", _handle, requires_project=_needs_project, fields=_fields)
