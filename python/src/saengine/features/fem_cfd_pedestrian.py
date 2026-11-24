"""CFD Wind - Pedestrian Comfort tab (`femCfdPedestrian`): Lawson/Davenport Weibull speed exceedance and canopy shielding."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.fem_common import parse_numbers


def _comfort_grade(p_5: float, p_10: float, p_15: float) -> str:
    if p_5 <= 2.0:
        return "A - Sitting Long"
    if p_5 <= 5.0:
        return "B - Standing / Strolling"
    if p_5 <= 10.0 and p_10 <= 2.0:
        return "C - Business Walking"
    if p_15 <= 0.3:
        return "D - Fast Walking Only"
    return "E - Uncomfortable / Safety Hazard"


@feature(
    "femCfdPedestrian.meanSpeed",
    "Mean Pedestrian Speed",
    part="fem",
    fields=[
        number(
            "speedupFactor", "CFD amplification factor γ = U_ped / U_ref", 0.72, min=0.05, max=3.0
        ),
        number("uRefMs", "Meteorological reference speed at H_ref", 6.5, unit="m/s", min=0.5),
    ],
    requires_project=False,
)
def mean_speed(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute pedestrian-level mean wind speed at z = 1.75 m from CFD amplification ratio."""
    u_ped = values["speedupFactor"] * values["uRefMs"]
    rows = [{"gamma": values["speedupFactor"], "uRefMs": values["uRefMs"], "uPedMs": u_ped}]
    return result(
        summary={"pedestrianMeanMs": u_ped, "amplificationGamma": values["speedupFactor"]},
        tables=[
            table(
                "Pedestrian-height mean wind speed",
                [("gamma", "γ = U/Uref"), ("uRefMs", "U_ref", "m/s"), ("uPedMs", "U_1.75m", "m/s")],
                rows,
            )
        ],
        notes=[
            "Amplification ratio γ combines CFD directional simulations with climate statistics."
        ],
    )


@feature(
    "femCfdPedestrian.gustFactor",
    "Gust Equivalent Mean",
    part="fem",
    fields=[
        number("meanSpeedMs", "Mean speed U_mean", 3.8, unit="m/s", min=0.1),
        number("turbulenceIntensity", "Local turbulence intensity I_u", 0.25, min=0.01, max=0.8),
        number("peakFactor", "Peak gust factor g", 3.4, min=2.0, max=4.5),
    ],
    requires_project=False,
)
def gust_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Gust Equivalent Mean (GEM) wind speed accounting for corner vortex buffeting."""
    u_gust = values["meanSpeedMs"] * (1.0 + values["peakFactor"] * values["turbulenceIntensity"])
    u_gem = max(values["meanSpeedMs"], u_gust / 1.85)
    rows = [
        {
            "meanMs": values["meanSpeedMs"],
            "gustMs": u_gust,
            "gemMs": u_gem,
            "gustDominated": u_gem > values["meanSpeedMs"],
        }
    ]
    return result(
        summary={"gustMs": u_gust, "gemMs": u_gem},
        tables=[
            table(
                "Gust Equivalent Mean (GEM) computation",
                [
                    ("meanMs", "Mean", "m/s"),
                    ("gustMs", "Peak Gust", "m/s"),
                    ("gemMs", "GEM", "m/s"),
                    ("gustDominated", "Gust Controls"),
                ],
                rows,
            )
        ],
        notes=["GEM = max(U_mean, U_gust / 1.85) captures high-turbulence discomfort zones."],
    )


@feature(
    "femCfdPedestrian.exceedanceLimit",
    "Exceedance Probability",
    part="fem",
    fields=[
        number("thresholdMs", "Threshold speed U_lim", 5.0, unit="m/s", min=1.0),
        number("weibullScaleMs", "Scaled local Weibull c_loc", 3.6, unit="m/s", min=0.5),
        number("weibullShapeK", "Weibull shape k", 1.85, min=1.0, max=4.0),
    ],
    requires_project=False,
)
def exceedance_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute annual exceedance probability P(U > U_lim) from local Weibull parameters."""
    p = math.exp(-((values["thresholdMs"] / values["weibullScaleMs"]) ** values["weibullShapeK"]))
    rows = [
        {
            "thresholdMs": values["thresholdMs"],
            "exceedancePct": 100.0 * p,
            "hoursPerYear": 8760.0 * p,
        }
    ]
    return result(
        summary={"exceedancePercent": 100.0 * p, "hoursPerYear": 8760.0 * p},
        tables=[
            table(
                "Annual wind speed exceedance",
                [
                    ("thresholdMs", "U_lim", "m/s"),
                    ("exceedancePct", "P(U>U_lim)", "%"),
                    ("hoursPerYear", "Hours/yr"),
                ],
                rows,
            )
        ],
        notes=["Integrates Weibull wind-climate probability distribution."],
    )


@feature(
    "femCfdPedestrian.comfortCategory",
    "Comfort Category",
    part="fem",
    fields=[
        number("pOver5Pct", "Exceedance P(U > 5 m/s)", 3.5, unit="%", min=0.0, max=100.0),
        number("pOver10Pct", "Exceedance P(U > 10 m/s)", 0.4, unit="%", min=0.0, max=100.0),
        number("pOver15Pct", "Safety exceedance P(U > 15 m/s)", 0.02, unit="%", min=0.0, max=100.0),
    ],
    requires_project=False,
)
def comfort_category(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Classify pedestrian microclimate activity grade from threshold exceedance rates."""
    grade = _comfort_grade(values["pOver5Pct"], values["pOver10Pct"], values["pOver15Pct"])
    rows = [
        {
            "p5Pct": values["pOver5Pct"],
            "p10Pct": values["pOver10Pct"],
            "p15Pct": values["pOver15Pct"],
            "category": grade,
        }
    ]
    return result(
        summary={"category": grade, "safeForStanding": values["pOver5Pct"] <= 5.0},
        tables=[
            table(
                "Pedestrian wind comfort rating",
                [
                    ("p5Pct", "P>5", "%"),
                    ("p10Pct", "P>10", "%"),
                    ("p15Pct", "P>15", "%"),
                    ("category", "Grade"),
                ],
                rows,
            )
        ],
        notes=["Evaluated using annual probability-of-exceedance comfort bands."],
    )


@feature(
    "femCfdPedestrian.probePoint",
    "Comfort Probe Point",
    part="fem",
    fields=[
        number("xM", "Probe X", 12.0, unit="m"),
        number("yM", "Probe Y", 5.0, unit="m"),
        number("gamma", "Directional velocity amplification γ", 0.85, min=0.05),
        number("weibullScaleRefMs", "Reference Weibull c_ref", 4.8, unit="m/s", min=0.5),
    ],
    requires_project=False,
)
def probe_point(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate Weibull comfort exceedance at a single pedestrian probe location."""
    c_loc = values["gamma"] * values["weibullScaleRefMs"]
    p5 = 100.0 * math.exp(-((5.0 / c_loc) ** 1.9))
    p10 = 100.0 * math.exp(-((10.0 / c_loc) ** 1.9))
    p15 = 100.0 * math.exp(-((15.0 / c_loc) ** 1.9))
    grade = _comfort_grade(p5, p10, p15)
    rows = [{"coord": f"({values['xM']}, {values['yM']})", "p5Pct": p5, "grade": grade}]
    return result(
        summary={"pOver5Pct": p5, "grade": grade},
        tables=[
            table(
                "Virtual anemometer probe result",
                [("coord", "(x, y)"), ("p5Pct", "P>5 m/s", "%"), ("grade", "Comfort Class")],
                rows,
            )
        ],
        notes=["Probe sampled at 1.75 m pedestrian breathing height."],
    )


@feature(
    "femCfdPedestrian.zoneAverage",
    "Zone Average Comfort",
    part="fem",
    fields=[
        text("zoneName", "Outdoor zone name", "Main Entrance Plaza"),
        text("probeGammas", "Sampled probe γ ratios (CSV)", "0.52, 0.64, 0.71, 0.88, 0.58"),
        number("weibullScaleRefMs", "Reference Weibull c_ref", 4.8, unit="m/s", min=0.5),
    ],
    requires_project=False,
)
def zone_average(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Aggregate spatial probe amplification ratios across a pedestrian plaza or walkway."""
    gammas = parse_numbers(values["probeGammas"], "probeGammas")
    mean_g = sum(gammas) / len(gammas)
    max_g = max(gammas)
    c_loc = mean_g * values["weibullScaleRefMs"]
    p5_avg = 100.0 * math.exp(-((5.0 / c_loc) ** 1.9))
    rows = [
        {"zone": values["zoneName"], "meanGamma": mean_g, "peakGamma": max_g, "meanP5Pct": p5_avg}
    ]
    return result(
        summary={
            "zone": values["zoneName"],
            "meanGamma": mean_g,
            "peakGamma": max_g,
            "meanPOver5Pct": p5_avg,
        },
        tables=[
            table(
                "Zone spatial comfort summary",
                [
                    ("zone", "Zone"),
                    ("meanGamma", "Mean γ"),
                    ("peakGamma", "Peak γ"),
                    ("meanP5Pct", "Avg P>5", "%"),
                ],
                rows,
            )
        ],
        notes=["Report both spatial mean and corner hot-spot amplification ratios."],
    )


@feature(
    "femCfdPedestrian.comfortMap",
    "Comfort Contour Map",
    part="fem",
    fields=[
        text(
            "gammaGrid", "Plaza amplification γ samples (CSV)", "0.45, 0.62, 0.78, 0.95, 1.15, 0.55"
        ),
        number("weibullCMs", "Site Weibull scale c_ref", 4.6, unit="m/s", min=0.5),
    ],
    requires_project=False,
)
def comfort_map(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map spatial amplification samples onto pedestrian comfort activity classes."""
    gammas = parse_numbers(values["gammaGrid"], "gammaGrid")
    rows = []
    for i, g in enumerate(gammas, 1):
        cloc = max(0.2, g * values["weibullCMs"])
        p5 = 100.0 * math.exp(-((5.0 / cloc) ** 1.9))
        p10 = 100.0 * math.exp(-((10.0 / cloc) ** 1.9))
        p15 = 100.0 * math.exp(-((15.0 / cloc) ** 1.9))
        rows.append(
            {"cellId": f"P{i}", "gamma": g, "p5Pct": p5, "grade": _comfort_grade(p5, p10, p15)}
        )
    return result(
        summary={"mappedPoints": len(rows), "maxPOver5Pct": max(r["p5Pct"] for r in rows)},
        tables=[
            table(
                "Pedestrian comfort spatial map",
                [("cellId", "Point"), ("gamma", "γ"), ("p5Pct", "P>5", "%"), ("grade", "Class")],
                rows,
            )
        ],
        notes=["Evaluated at 1.75 m above finished landscape grade."],
    )


@feature(
    "femCfdPedestrian.statistics",
    "Comfort Statistics",
    part="fem",
    fields=[
        text("p5Series", "Spatial P(U > 5 m/s) percentages (CSV)", "1.2, 2.8, 4.1, 6.5, 9.2, 3.0"),
    ],
    requires_project=False,
)
def statistics(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute mean, median, 95th percentile, and variance of comfort exceedance field."""
    vals = sorted(parse_numbers(values["p5Series"], "p5Series"))
    n = len(vals)
    mean_v = sum(vals) / n
    med_v = vals[n // 2]
    p95 = vals[min(n - 1, int(0.95 * (n - 1)))]
    rows = [
        {"samples": n, "meanPct": mean_v, "medianPct": med_v, "p95Pct": p95, "maxPct": vals[-1]}
    ]
    return result(
        summary={"meanPOver5Pct": mean_v, "p95POver5Pct": p95, "maxPOver5Pct": vals[-1]},
        tables=[
            table(
                "Pedestrian comfort distribution stats",
                [
                    ("samples", "Count"),
                    ("meanPct", "Mean", "%"),
                    ("medianPct", "Median", "%"),
                    ("p95Pct", "95th %", "%"),
                    ("maxPct", "Max", "%"),
                ],
                rows,
            )
        ],
        notes=["Summary metrics characterize overall public realm usability."],
    )


@feature(
    "femCfdPedestrian.comfortReport",
    "Comfort Report",
    part="fem",
    fields=[
        number("areaM2", "Total evaluated pedestrian area", 2400.0, unit="m²", min=10.0),
        number(
            "sittingSharePct", "Area meeting Sitting grade A/B", 68.0, unit="%", min=0.0, max=100.0
        ),
        number("hazardAreaM2", "Safety exceedance zone (> 15 m/s)", 0.0, unit="m²", min=0.0),
    ],
    requires_project=False,
)
def comfort_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile executive pedestrian wind comfort and safety compliance summary."""
    rows = [
        {"metric": "Evaluated public realm area", "value": f"{values['areaM2']:.1f} m²"},
        {
            "metric": "Leisure seating/strolling compliant share",
            "value": f"{values['sittingSharePct']:.1f}%",
        },
        {"metric": "Safety hazard zone area", "value": f"{values['hazardAreaM2']:.1f} m²"},
    ]
    return result(
        summary={
            "areaM2": values["areaM2"],
            "sittingSharePct": values["sittingSharePct"],
            "safetyPass": values["hazardAreaM2"] <= 0.5,
        },
        tables=[
            table(
                "Pedestrian wind microclimate summary",
                [("metric", "Item"), ("value", "Result")],
                rows,
            )
        ],
        notes=[
            "Corner downwash mitigation screens are recommended where safety zones exceed threshold."
        ],
    )


@feature(
    "femCfdPedestrian.worstLocations",
    "Worst Comfort Locations",
    part="fem",
    fields=[
        text("gammas", "Probe amplification ratios (CSV)", "0.61, 1.32, 0.88, 1.45, 0.74, 1.18"),
        number("targetMaxGamma", "Comfort γ threshold", 1.0, min=0.1),
    ],
    requires_project=False,
)
def worst_locations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Rank hot-spot building corners or passages with highest wind speed amplification."""
    gammas = parse_numbers(values["gammas"], "gammas")
    ranked = sorted(
        [(f"Probe-{i + 1}", g) for i, g in enumerate(gammas)], key=lambda x: x[1], reverse=True
    )
    rows = [
        {"rank": r + 1, "probe": p, "gamma": g, "exceeds": g > values["targetMaxGamma"]}
        for r, (p, g) in enumerate(ranked[:5])
    ]
    return result(
        summary={"worstProbe": ranked[0][0], "peakGamma": ranked[0][1]},
        tables=[
            table(
                "Top wind-amplification hotspots",
                [("rank", "Rank"), ("probe", "Location"), ("gamma", "γ"), ("exceeds", "Flagged")],
                rows,
            )
        ],
        notes=["Corner acceleration and passage Venturi effects drive top peaks."],
    )


@feature(
    "femCfdPedestrian.passRate",
    "Target Pass Rate",
    part="fem",
    fields=[
        text("p5Samples", "Zone P(U > 5 m/s) samples (CSV)", "2.1, 3.4, 4.9, 5.8, 7.2, 4.0"),
        number(
            "targetLimitPct", "Design target P(U > 5 m/s) limit", 5.0, unit="%", min=0.5, max=50.0
        ),
    ],
    requires_project=False,
)
def pass_rate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate percentage of sampled plaza locations meeting the intended activity target."""
    vals = parse_numbers(values["p5Samples"], "p5Samples")
    passing = sum(1 for v in vals if v <= values["targetLimitPct"])
    pct = 100.0 * passing / len(vals)
    rows = [{"totalProbes": len(vals), "passingProbes": passing, "passRatePct": pct}]
    return result(
        summary={"passRatePct": pct, "passingProbes": passing, "totalProbes": len(vals)},
        tables=[
            table(
                "Plaza comfort target pass rate",
                [
                    ("totalProbes", "Total"),
                    ("passingProbes", "Passing"),
                    ("passRatePct", "Pass Rate", "%"),
                ],
                rows,
            )
        ],
        notes=["Mitigate failed zones via canopies, colonnades, or evergreen windbreaks."],
    )


@feature(
    "femCfdPedestrian.exportMap",
    "Export Comfort Map",
    part="fem",
    fields=[
        number("nPoints", "Exported grid points", 400.0, min=4.0),
        select(
            "format",
            "Grid export format",
            [("csv", "CSV (x,y,P5,Grade)"), ("vtk", "VTK Surface Overlay")],
            "csv",
        ),
    ],
    requires_project=False,
)
def export_map(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Format pedestrian comfort map grid metadata for CAD/GIS overlay export."""
    rows = [{"format": values["format"], "points": round(values["nPoints"]), "planeHeightM": 1.75}]
    return result(
        summary={"format": values["format"], "points": round(values["nPoints"])},
        tables=[
            table(
                "Pedestrian comfort overlay export",
                [("format", "Format"), ("points", "Points"), ("planeHeightM", "Elevation", "m")],
                rows,
            )
        ],
        notes=["Export includes annual exceedance percentages and Lawson comfort grade indices."],
    )


@feature(
    "femCfdPedestrian.weibullParameters",
    "Site Weibull Parameters",
    part="fem",
    fields=[
        number("meanSpeedMs", "Long-term mean site speed U_bar", 4.3, unit="m/s", min=0.5),
        number("stdDevMs", "Wind speed standard deviation σ_U", 2.3, unit="m/s", min=0.2),
    ],
    requires_project=False,
)
def weibull_parameters(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate meteorological Weibull shape k and scale c parameters from mean and variance."""
    k = (values["stdDevMs"] / values["meanSpeedMs"]) ** (-1.086)
    c = values["meanSpeedMs"] / math.gamma(1.0 + 1.0 / k)
    rows = [
        {"meanMs": values["meanSpeedMs"], "stdMs": values["stdDevMs"], "shapeK": k, "scaleCMs": c}
    ]
    return result(
        summary={"weibullShapeK": k, "weibullScaleCMs": c},
        tables=[
            table(
                "Fitted Weibull wind-speed distribution",
                [
                    ("meanMs", "Mean", "m/s"),
                    ("stdMs", "StdDev", "m/s"),
                    ("shapeK", "Shape k"),
                    ("scaleCMs", "Scale c", "m/s"),
                ],
                rows,
            )
        ],
        notes=["Justus empirical moment estimator k = (σ / U)^(-1.086)."],
    )


@feature(
    "femCfdPedestrian.directionalWeights",
    "Directional Wind Weights",
    part="fem",
    fields=[
        text(
            "sectorProbsPct",
            "Directional frequency weights (%) CSV",
            "12, 8, 6, 10, 18, 22, 14, 10",
        ),
        text(
            "sectorGammas",
            "Directional CFD γ factors CSV",
            "0.65, 0.72, 0.85, 1.05, 0.90, 0.58, 0.62, 0.70",
        ),
    ],
    requires_project=False,
)
def directional_weights(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Integrate annual directional exceedance by weighting sector probabilities with CFD γ."""
    probs = parse_numbers(values["sectorProbsPct"], "sectorProbsPct")
    gammas = parse_numbers(values["sectorGammas"], "sectorGammas")
    n = min(len(probs), len(gammas))
    total_w = sum(probs[:n]) or 100.0
    p5_total = 0.0
    rows = []
    for i in range(n):
        w = probs[i] / total_w
        cloc = max(0.2, gammas[i] * 4.8)
        p5_dir = math.exp(-((5.0 / cloc) ** 1.9))
        contrib = 100.0 * w * p5_dir
        p5_total += contrib
        rows.append(
            {
                "sector": f"S{i + 1}",
                "weightPct": 100.0 * w,
                "gamma": gammas[i],
                "contribPct": contrib,
            }
        )
    return result(
        summary={"integratedPOver5Pct": p5_total, "sectors": n},
        tables=[
            table(
                "Directional probability integration",
                [
                    ("sector", "Sector"),
                    ("weightPct", "Freq", "%"),
                    ("gamma", "γ"),
                    ("contribPct", "P>5 Contrib", "%"),
                ],
                rows,
            )
        ],
        notes=["Weighted sector sum prevents over-conservatism from rare wind directions."],
    )


@feature(
    "femCfdPedestrian.terrainRoughness",
    "Surroundings Roughness",
    part="fem",
    fields=[
        number(
            "frontalAreaRatio",
            "Upstream building frontal area density λ_f",
            0.22,
            min=0.01,
            max=0.6,
        ),
        number("obstacleHeightM", "Mean surrounding building height zh", 14.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def terrain_roughness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate surrounding urban Macdonald roughness length z0 and displacement height d."""
    lf = values["frontalAreaRatio"]
    h = values["obstacleHeightM"]
    d = h * (1.0 + (4.0 ** (-lf)) * (lf - 1.0))
    d = max(0.0, min(0.8 * h, d))
    z0 = max(0.03, (h - d) * math.exp(-((0.5 * 1.2 / (0.41**2) * (1.0 - d / h) * lf) ** (-0.5))))
    rows = [{"lambdaF": lf, "meanHeightM": h, "displacementM": d, "roughnessZ0M": z0}]
    return result(
        summary={"displacementHeightM": d, "roughnessZ0M": z0},
        tables=[
            table(
                "Macdonald morphometric urban roughness",
                [
                    ("lambdaF", "λf"),
                    ("meanHeightM", "zh", "m"),
                    ("displacementM", "d", "m"),
                    ("roughnessZ0M", "z0", "m"),
                ],
                rows,
            )
        ],
        notes=["Account for explicit nearby blocks inside the 3D CFD geometry radius."],
    )


@feature(
    "femCfdPedestrian.canopyShield",
    "Canopy & Podium Shielding",
    part="fem",
    fields=[
        number("canopyProjectionM", "Horizontal canopy projection L_c", 4.0, unit="m", min=0.5),
        number("buildingHeightM", "Tower height H", 60.0, unit="m", min=6.0),
        number("unshieldedGamma", "Unshielded corner amplification γ0", 1.25, min=0.3),
    ],
    requires_project=False,
)
def canopy_shield(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate downwash speed reduction factor from a podium or entrance wind canopy."""
    proj_ratio = min(1.0, values["canopyProjectionM"] / (0.12 * values["buildingHeightM"]))
    reduction = 0.35 * proj_ratio
    gamma_new = values["unshieldedGamma"] * (1.0 - reduction)
    rows = [
        {
            "gammaBefore": values["unshieldedGamma"],
            "reductionPct": 100.0 * reduction,
            "gammaAfter": gamma_new,
        }
    ]
    return result(
        summary={"gammaMitigated": gamma_new, "reductionPercent": 100.0 * reduction},
        tables=[
            table(
                "Podium canopy downwash attenuation",
                [
                    ("gammaBefore", "γ_before"),
                    ("reductionPct", "Reduction", "%"),
                    ("gammaAfter", "γ_after"),
                ],
                rows,
            )
        ],
        notes=["Solid horizontal canopies deflect descending facade boundary-layer jets."],
    )


@feature(
    "femCfdPedestrian.treePorosity",
    "Tree Crown Porosity",
    part="fem",
    fields=[
        number("leafAreaDensity", "Leaf area density LAD", 1.8, unit="m²/m³", min=0.1, max=5.0),
        number("dragCoeffCd", "Foliage drag coefficient Cd", 0.25, min=0.05, max=0.6),
    ],
    requires_project=False,
)
def tree_porosity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute canopy inertial momentum sink coefficient C2 for porous foliage zones."""
    c2 = 2.0 * values["dragCoeffCd"] * values["leafAreaDensity"]
    pressure_drop_k = c2 * 3.0
    rows = [
        {
            "lad": values["leafAreaDensity"],
            "cd": values["dragCoeffCd"],
            "inertialLossC2": c2,
            "loss3mCrownK": pressure_drop_k,
        }
    ]
    return result(
        summary={"inertialCoeffC2PerM": c2, "pressureLossFactorK": pressure_drop_k},
        tables=[
            table(
                "Vegetative crown Darcy-Forchheimer sink",
                [
                    ("lad", "LAD", "m²/m³"),
                    ("cd", "Cd"),
                    ("inertialLossC2", "C2", "1/m"),
                    ("loss3mCrownK", "ΔP/q (3m)"),
                ],
                rows,
            )
        ],
        notes=["S = -ρ Cd LAD |U| U represents vegetative drag in momentum equations."],
    )


@feature(
    "femCfdPedestrian.porosityModeler",
    "Screen Porosity Modeler",
    part="fem",
    fields=[
        number("openAreaRatio", "Perforated screen open-area ratio β", 0.4, min=0.05, max=0.95),
        number("windSpeedMs", "Approach wind speed U", 8.0, unit="m/s", min=0.5),
    ],
    requires_project=False,
)
def porosity_modeler(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute hydraulic pressure loss coefficient K and velocity bleed across windbreak screens."""
    beta = values["openAreaRatio"]
    k_loss = ((1.0 / (0.65 * beta)) - 1.0) ** 2
    u_down = values["windSpeedMs"] / math.sqrt(1.0 + k_loss)
    rows = [
        {
            "porosityBeta": beta,
            "lossCoeffK": k_loss,
            "downstreamSpeedMs": u_down,
            "shelterEfficiencyPct": 100.0 * (1.0 - u_down / values["windSpeedMs"]),
        }
    ]
    return result(
        summary={"lossCoefficientK": k_loss, "downstreamSpeedMs": u_down},
        tables=[
            table(
                "Perforated windbreak screen bleed analysis",
                [
                    ("porosityBeta", "β"),
                    ("lossCoeffK", "K_loss"),
                    ("downstreamSpeedMs", "U_down", "m/s"),
                    ("shelterEfficiencyPct", "Reduction", "%"),
                ],
                rows,
            )
        ],
        notes=["30%–50% porosity screens prevent strong downstream recirculation vortices."],
    )


@feature(
    "femCfdPedestrian.seasonalFilter",
    "Seasonal Comfort Filter",
    part="fem",
    fields=[
        select(
            "season",
            "Seasonal window",
            [
                ("summer", "Summer outdoor dining"),
                ("winter", "Winter exposure"),
                ("annual", "Full-year envelope"),
            ],
            "summer",
        ),
        number("seasonalFactor", "Seasonal wind-speed ratio", 0.86, min=0.4, max=1.5),
        number("annualP5Pct", "Annual P(U > 5 m/s)", 4.8, unit="%", min=0.0, max=100.0),
    ],
    requires_project=False,
)
def seasonal_filter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adjust pedestrian wind exceedance probability for seasonal outdoor occupancy periods."""
    adj_p5 = max(0.0, min(100.0, values["annualP5Pct"] * (values["seasonalFactor"] ** 1.9)))
    rows = [
        {
            "season": values["season"],
            "factor": values["seasonalFactor"],
            "annualP5Pct": values["annualP5Pct"],
            "seasonalP5Pct": adj_p5,
        }
    ]
    return result(
        summary={"season": values["season"], "seasonalPOver5Pct": adj_p5},
        tables=[
            table(
                "Seasonal pedestrian comfort filter",
                [
                    ("season", "Season"),
                    ("factor", "Speed Ratio"),
                    ("annualP5Pct", "Annual P>5", "%"),
                    ("seasonalP5Pct", "Seasonal P>5", "%"),
                ],
                rows,
            )
        ],
        notes=[
            "Seasonal filtering captures warm-season outdoor seating periods separately from winter storms."
        ],
    )


@feature(
    "femCfdPedestrian.diurnalCycle",
    "Diurnal Activity Filter",
    part="fem",
    fields=[
        number(
            "daytimeWeibullScaleMs",
            "Daytime hours (07:00–21:00) scale c_day",
            4.9,
            unit="m/s",
            min=0.5,
        ),
        number("nightWeibullScaleMs", "Nighttime scale c_night", 3.4, unit="m/s", min=0.5),
    ],
    requires_project=False,
)
def diurnal_cycle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare occupied daytime vs overnight pedestrian exceedance probabilities."""
    p5_day = 100.0 * math.exp(-((5.0 / values["daytimeWeibullScaleMs"]) ** 1.9))
    p5_night = 100.0 * math.exp(-((5.0 / values["nightWeibullScaleMs"]) ** 1.9))
    rows = [
        {
            "period": "Daytime (07:00–21:00)",
            "scaleMs": values["daytimeWeibullScaleMs"],
            "p5Pct": p5_day,
        },
        {
            "period": "Nighttime (21:00–07:00)",
            "scaleMs": values["nightWeibullScaleMs"],
            "p5Pct": p5_night,
        },
    ]
    return result(
        summary={"daytimePOver5Pct": p5_day, "nighttimePOver5Pct": p5_night},
        tables=[
            table(
                "Diurnal comfort probability breakdown",
                [("period", "Window"), ("scaleMs", "Weibull c", "m/s"), ("p5Pct", "P>5 m/s", "%")],
                rows,
            )
        ],
        notes=["Daytime thermal convection often yields higher afternoon surface winds."],
    )
