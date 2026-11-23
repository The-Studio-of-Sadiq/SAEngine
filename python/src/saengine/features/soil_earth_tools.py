"""Soil Report earth-pressure and chemical-exposure calculations beyond the base tab."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import number, result, table
from saengine.features.soil_feature_utils import (
    FeatureInputError,
    common_fields,
    register_tab,
    require_report,
    result_rows,
    samples,
)

GAMMA_W = 9.81


def _fields(fid: str) -> list[Any]:
    fields = common_fields(fid)
    if fid in {"soilEarth.slopeSurcharge", "soilEarth.bracedExcavationPressure"}:
        fields.append(
            number("slopeAngleDeg", "Backfill or slope angle [°]", 10.0, unit="°", min=0, max=40)
        )
    if fid == "soilEarth.siloPressure":
        fields.extend(
            [
                number("siloRadiusM", "Silo radius [m]", 5.0, unit="m", min=0.2),
                number("wallFrictionDeg", "Wall friction angle [°]", 20.0, unit="°", min=0, max=40),
                number(
                    "unitWeightKnM3",
                    "Stored material unit weight [kN/m³]",
                    8.0,
                    unit="kN/m³",
                    min=1,
                ),
            ]
        )
    if fid == "soilEarth.compactionInducedPressure":
        fields.append(
            number("decayDepthM", "Compaction influence depth [m]", 0.75, unit="m", min=0.05)
        )
    return fields


def _needs_project(fid: str) -> bool:
    return fid in {
        "soilEarth.backfillProperties",
        "soilEarth.sulfateAttack",
        "soilEarth.chlorideContent",
        "soilEarth.phResistivity",
        "soilEarth.durabilityClass",
        "soilEarth.totalSulphate",
        "soilEarth.organicContent",
        "soilEarth.aggressivityIndex",
        "soilEarth.cementTypeAdvice",
    }


def _sloping_ka(phi_deg: float, beta_deg: float) -> float:
    phi, beta = math.radians(phi_deg), math.radians(beta_deg)
    if beta >= phi:
        raise FeatureInputError(
            "Backfill slope must be flatter than the soil friction angle for this Rankine solution."
        )
    root = math.sqrt(max(0.0, math.cos(beta) ** 2 - math.cos(phi) ** 2))
    return math.cos(beta) * (math.cos(beta) - root) / (math.cos(beta) + root)


def _profile(
    values: dict[str, Any],
    k: float,
    water: float = 100.0,
    unit_weight: float = 18.0,
    saturated: float = 20.0,
) -> tuple[list[dict[str, float]], float, float]:
    h = values.get("heightM", 4.0)
    q = values.get("pressureKpa", 10.0)
    rows = []
    points = []
    for i in range(21):
        z = h * i / 20
        above = min(z, water)
        below = max(0.0, z - water)
        sigma_eff = unit_weight * above + max(0.0, saturated - GAMMA_W) * below
        u = GAMMA_W * below
        soil_p = k * (sigma_eff + q)
        total = soil_p + u
        points.append((z, total))
        if i % 2 == 0:
            rows.append(
                {
                    "depthM": z,
                    "effectiveVerticalStressKpa": sigma_eff + q,
                    "waterKpa": u,
                    "lateralKpa": total,
                }
            )
    force = sum(
        (points[i + 1][0] - points[i][0]) * (points[i][1] + points[i + 1][1]) / 2 for i in range(20)
    )
    moment = sum(
        (points[i + 1][0] - points[i][0])
        * (points[i][1] + points[i + 1][1])
        / 2
        * (h - (points[i][0] + points[i + 1][0]) / 2)
        for i in range(20)
    )
    return rows, force, moment / force if force else 0.0


def _handle(fid: str, ctx: Any, values: dict[str, Any]) -> dict[str, Any]:
    pressure_ids = {
        "soilEarth.wallFriction",
        "soilEarth.compactionLoads",
        "soilEarth.basementWallPressure",
        "soilEarth.anchoredWallPressure",
        "soilEarth.bracedExcavationPressure",
        "soilEarth.siloPressure",
        "soilEarth.slopeSurcharge",
        "soilEarth.railwaySurcharge",
        "soilEarth.trafficSurcharge",
        "soilEarth.compactionInducedPressure",
    }
    if fid in pressure_ids:
        from saengine.soil.earth_pressure import rankine_active

        phi = values.get("phiDeg", 30.0)
        if fid == "soilEarth.wallFriction":
            delta = values.get("wallFrictionDeg", min(phi / 2, 15.0))
            if delta > phi:
                raise FeatureInputError(
                    "Wall friction angle cannot exceed the soil friction angle."
                )
            return result(
                summary={
                    "wallFrictionAngleDeg": delta,
                    "wallFrictionCoefficient": math.tan(math.radians(delta)),
                    "rankineActiveCoefficient": rankine_active(phi),
                },
                tables=[
                    table(
                        "Wall interface parameters",
                        [("parameter", "Parameter"), ("value", "Value")],
                        [
                            {"parameter": "Soil friction angle φ' [°]", "value": phi},
                            {"parameter": "Wall friction angle δ [°]", "value": delta},
                            {"parameter": "tan δ [-]", "value": math.tan(math.radians(delta))},
                            {"parameter": "Rankine Ka [-]", "value": rankine_active(phi)},
                        ],
                    )
                ],
                notes=[
                    "Wall friction is treated as an interface angle input; the Rankine earth-pressure coefficient shown is for a smooth vertical wall and horizontal backfill."
                ],
            )
        if fid == "soilEarth.siloPressure":
            radius, h = values["siloRadiusM"], values.get("heightM", 10.0)
            gamma = values["unitWeightKnM3"]
            mu = math.tan(math.radians(values["wallFrictionDeg"]))
            k = 1 - math.sin(math.radians(phi))
            perimeter_area = 2 * radius / 4
            characteristic = gamma * radius / max(k * mu, 1e-8)
            rows = []
            for i in range(11):
                z = h * i / 10
                vertical = characteristic * (
                    1 - math.exp(-z / max(perimeter_area / (k * mu), 1e-8))
                )
                rows.append(
                    {
                        "depthM": z,
                        "verticalKpa": vertical,
                        "lateralKpa": k * vertical,
                        "wallShearKpa": mu * k * vertical,
                    }
                )
            return result(
                summary={
                    "maximumLateralPressureKpa": max(row["lateralKpa"] for row in rows),
                    "atRestCoefficient": k,
                    "characteristicDepthM": characteristic / gamma,
                },
                tables=[
                    table(
                        "Janssen silo pressure profile",
                        [
                            ("depthM", "Depth", "m"),
                            ("verticalKpa", "Vertical pressure", "kPa"),
                            ("lateralKpa", "Lateral pressure", "kPa"),
                            ("wallShearKpa", "Wall shear", "kPa"),
                        ],
                        rows,
                    )
                ],
                notes=[
                    "Janssen vertical stress saturation is used for a circular silo with uniform fill and wall friction; outlet flow, eccentric discharge and structural pressure factors are not included."
                ],
            )
        k = (
            1 - math.sin(math.radians(phi))
            if fid == "soilEarth.basementWallPressure"
            else rankine_active(phi)
        )
        if fid == "soilEarth.slopeSurcharge":
            beta = values["slopeAngleDeg"]
            k = _sloping_ka(phi, beta)
        if fid == "soilEarth.bracedExcavationPressure":
            # An apparent envelope for braced sand; the soil pressure level is uniform over height.
            h = values.get("heightM", 4.0)
            gamma = 18.0
            p = 0.65 * rankine_active(phi) * gamma * h
            rows = [{"depthM": h * i / 10, "lateralKpa": p} for i in range(11)]
            force = p * h
            return result(
                summary={
                    "apparentPressureKpa": p,
                    "resultantKnPerM": force,
                    "actsAboveBaseM": h / 2,
                },
                tables=[
                    table(
                        "Braced excavation apparent pressure",
                        [("depthM", "Depth", "m"), ("lateralKpa", "Lateral pressure", "kPa")],
                        rows,
                    )
                ],
                notes=[
                    "Uniform apparent-pressure envelope for a drained granular backfill: 0.65 Ka γ H. Confirm soil type, groundwater, excavation sequence and support spacing before design."
                ],
            )
        if fid == "soilEarth.anchoredWallPressure":
            rows, force, arm = _profile(values, k)
            anchor = values.get("pressureKpa", 10.0)
            return result(
                summary={
                    "activeResultantKnPerM": force,
                    "actsAboveBaseM": arm,
                    "uniformAnchorReactionKpa": anchor,
                },
                tables=[
                    table(
                        "Anchored-wall pressure profile",
                        [
                            ("depthM", "Depth", "m"),
                            (
                                "effectiveVerticalStressKpa",
                                "Vertical effective stress plus surcharge",
                                "kPa",
                            ),
                            ("waterKpa", "Water", "kPa"),
                            ("lateralKpa", "Active pressure", "kPa"),
                        ],
                        rows,
                    )
                ],
                notes=[
                    "Rankine active pressure is shown as the soil demand; anchor load distribution and wall stiffness require a staged wall-support analysis."
                ],
            )
        if fid == "soilEarth.compactionInducedPressure":
            h = values.get("heightM", 4.0)
            z0 = values["decayDepthM"]
            q0 = values.get("pressureKpa", 50.0)
            rows = [
                {
                    "depthM": h * i / 20,
                    "equivalentSurchargeKpa": q0 * math.exp(-(h * i / 20) / z0),
                    "lateralKpa": k * q0 * math.exp(-(h * i / 20) / z0),
                }
                for i in range(21)
            ]
            force = sum(
                (rows[i + 1]["depthM"] - rows[i]["depthM"])
                * (rows[i + 1]["lateralKpa"] + rows[i]["lateralKpa"])
                / 2
                for i in range(20)
            )
            return result(
                summary={
                    "surfaceCompactionPressureKpa": q0,
                    "resultantKnPerM": force,
                    "decayDepthM": z0,
                },
                tables=[
                    table(
                        "Compaction-induced lateral pressure",
                        [
                            ("depthM", "Depth", "m"),
                            ("equivalentSurchargeKpa", "Equivalent surcharge", "kPa"),
                            ("lateralKpa", "Lateral pressure", "kPa"),
                        ],
                        rows,
                    )
                ],
                notes=[
                    "Equivalent surcharge decays exponentially with the entered influence depth; this is a screening model, not a compactor-specific wave analysis."
                ],
            )
        rows, force, arm = _profile(values, k)
        title = (
            "At-rest lateral pressure profile"
            if fid == "soilEarth.basementWallPressure"
            else "Lateral pressure from surcharge"
        )
        method = (
            "Jaky at-rest coefficient K0 = 1 − sin φ'"
            if fid == "soilEarth.basementWallPressure"
            else "Rankine active coefficient Ka"
        )
        return result(
            summary={
                "lateralCoefficient": k,
                "resultantKnPerM": force,
                "actsAboveBaseM": arm,
                "pressureKpa": values.get("pressureKpa", 10.0),
            },
            tables=[
                table(
                    title,
                    [
                        ("depthM", "Depth", "m"),
                        ("effectiveVerticalStressKpa", "Effective vertical plus surcharge", "kPa"),
                        ("waterKpa", "Water", "kPa"),
                        ("lateralKpa", "Total lateral pressure", "kPa"),
                    ],
                    rows,
                )
            ],
            notes=[
                f"{method} for level drained backfill with the entered uniform surcharge; hydrostatic water pressure is added separately."
            ],
        )

    report = require_report(ctx)
    chem_samples = [
        (bh, sample, i) for bh, sample, i in samples(report) if sample.chemistry is not None
    ]
    if fid == "soilEarth.backfillProperties":
        from saengine.features.soil_feature_utils import profile

        rows = []
        for bh in report.boreholes:
            prof = profile(report, bh)
            for layer in prof.layers:
                rows.append(
                    {
                        "borehole": bh.id,
                        "layer": layer.index + 1,
                        "soilType": layer.soil_type,
                        "topDepthM": layer.top,
                        "bottomDepthM": layer.bottom,
                        "gammaKnM3": layer.gamma,
                        "gammaSatKnM3": layer.gamma_sat,
                        "cohesionKpa": layer.c,
                        "phiDeg": layer.phi,
                        "frictionSource": layer.sources.get("phi"),
                    }
                )
        if not rows:
            raise FeatureInputError(
                "Logged backfill soil layers are needed to report their engineering properties."
            )
        return result_rows(
            "Resolved backfill properties",
            [
                ("borehole", "Borehole"),
                ("layer", "Layer"),
                ("soilType", "Soil type"),
                ("topDepthM", "Top", "m"),
                ("bottomDepthM", "Bottom", "m"),
                ("gammaKnM3", "Unit weight", "kN/m³"),
                ("gammaSatKnM3", "Saturated unit weight", "kN/m³"),
                ("cohesionKpa", "c'", "kPa"),
                ("phiDeg", "φ'", "°"),
                ("frictionSource", "Source"),
            ],
            rows,
            summary={"layersCount": len(rows)},
            notes=[
                "Values are resolved from the log, laboratory samples, then the profile's documented SPT correlations or typical unit weights."
            ],
        )
    if not chem_samples:
        raise FeatureInputError(
            "Add soil or groundwater chemistry results to the borehole samples first."
        )
    from saengine.report.clauses import in_force
    from saengine.soil import chemistry as chemistry_engine

    with in_force(ctx.root):
        summary_data = chemistry_engine.site(report)
        if not summary_data.get("covered"):
            raise FeatureInputError(
                "The active code pack has no soil chemistry or durability provisions."
            )
    rows = []
    for bh, sample, i in chem_samples:
        chem = sample.chemistry
        rows.append(
            {
                "borehole": bh.id,
                "sample": sample.number or f"S{i + 1}",
                "depthM": sample.depth / 1000,
                "sulphateSoilPct": chem.sulphateSoil,
                "sulphateWaterMgL": chem.sulphateWater,
                "chlorideSoilPct": chem.chlorideSoil,
                "chlorideWaterMgL": chem.chlorideWater,
                "pH": chem.pH,
                "resistivityOhmCm": chem.resistivity,
                "organicContentPct": chem.organicContent,
            }
        )
    if fid == "soilEarth.sulfateAttack":
        detail = [row for row in summary_data["samples"] if row.get("sulphate")]
        if not detail:
            raise FeatureInputError(
                "No sample has sulfate chemistry that the active pack can classify."
            )
        return result(
            summary={
                "classifiedSamplesCount": len(detail),
                "governingSulphateClass": summary_data.get("sulphateClass"),
                "concreteRequirement": summary_data.get("concrete"),
            },
            tables=[
                table(
                    "Sulfate exposure assessment",
                    [
                        ("borehole", "Borehole"),
                        ("sample", "Sample"),
                        ("sulphate", "Sulfate class"),
                        ("corrosive", "Corrosivity flags"),
                    ],
                    [
                        {
                            "borehole": row["borehole"],
                            "sample": row["sample"],
                            "sulphate": row["sulphate"],
                            "corrosive": "; ".join(row["corrosive"]),
                        }
                        for row in detail
                    ],
                )
            ],
            notes=[
                "Sulfate exposure classes and concrete requirements are looked up from the active code pack using the recorded soil and water chemistry."
            ],
        )
    if fid == "soilEarth.chlorideContent":
        present = [
            row
            for row in rows
            if row["chlorideSoilPct"] is not None or row["chlorideWaterMgL"] is not None
        ]
        if not present:
            raise FeatureInputError(
                "No chloride results are recorded in the soil or groundwater samples."
            )
        return result_rows(
            "Chloride test results",
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("depthM", "Depth", "m"),
                ("chlorideSoilPct", "Soil chloride", "%"),
                ("chlorideWaterMgL", "Water chloride", "mg/L"),
            ],
            present,
            summary={
                "testedSamplesCount": len(present),
                "maximumWaterChlorideMgL": max(
                    (
                        row["chlorideWaterMgL"]
                        for row in present
                        if row["chlorideWaterMgL"] is not None
                    ),
                    default=None,
                ),
            },
            notes=[
                "Soil chloride is mass percent; dissolved groundwater chloride is reported as mg/L."
            ],
        )
    if fid == "soilEarth.phResistivity":
        present = [
            row for row in rows if row["pH"] is not None or row["resistivityOhmCm"] is not None
        ]
        if not present:
            raise FeatureInputError("No pH or soil resistivity results are recorded.")
        return result_rows(
            "pH and soil resistivity",
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("depthM", "Depth", "m"),
                ("pH", "pH"),
                ("resistivityOhmCm", "Resistivity", "ohm·cm"),
            ],
            present,
            summary={
                "testedSamplesCount": len(present),
                "minimumResistivityOhmCm": min(
                    (
                        row["resistivityOhmCm"]
                        for row in present
                        if row["resistivityOhmCm"] is not None
                    ),
                    default=None,
                ),
            },
            notes=[
                "Low resistivity and extreme pH can increase corrosion risk; soil moisture, redox conditions and test method also affect interpretation."
            ],
        )
    if fid == "soilEarth.totalSulphate":
        present = [
            row
            for row in rows
            if row["sulphateSoilPct"] is not None or row["sulphateWaterMgL"] is not None
        ]
        if not present:
            raise FeatureInputError("No sulfate results are recorded.")
        return result_rows(
            "Total sulfate results",
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("depthM", "Depth", "m"),
                ("sulphateSoilPct", "Soil sulfate", "%"),
                ("sulphateWaterMgL", "Water sulfate", "mg/L"),
            ],
            present,
            summary={
                "testedSamplesCount": len(present),
                "maximumWaterSulphateMgL": max(
                    (
                        row["sulphateWaterMgL"]
                        for row in present
                        if row["sulphateWaterMgL"] is not None
                    ),
                    default=None,
                ),
            },
            notes=[
                "Soil sulfate is reported as mass percent and water sulfate as mg/L; retain the laboratory method and extraction basis with the source report."
            ],
        )
    if fid == "soilEarth.organicContent":
        present = [row for row in rows if row["organicContentPct"] is not None]
        if not present:
            raise FeatureInputError("No loss-on-ignition organic-content results are recorded.")
        return result_rows(
            "Organic content results",
            [
                ("borehole", "Borehole"),
                ("sample", "Sample"),
                ("depthM", "Depth", "m"),
                ("organicContentPct", "Organic content", "%"),
            ],
            present,
            summary={
                "testedSamplesCount": len(present),
                "maximumOrganicContentPct": max(row["organicContentPct"] for row in present),
            },
            notes=[
                "Loss-on-ignition results are listed without extrapolating them to unsampled strata."
            ],
        )
    if fid == "soilEarth.aggressivityIndex":
        details = [item for item in summary_data["samples"] if item.get("corrosivity")]
        if not details:
            raise FeatureInputError(
                "The chemistry is insufficient for the active pack's aggressivity score."
            )
        return result(
            summary={
                "scoredSamplesCount": len(details),
                "worstCorrosivityRating": summary_data.get("corrosivityRating"),
            },
            tables=[
                table(
                    "Soil aggressivity scores",
                    [
                        ("borehole", "Borehole"),
                        ("sample", "Sample"),
                        ("score", "Score"),
                        ("rating", "Rating"),
                        ("missing", "Missing inputs"),
                    ],
                    [
                        {
                            "borehole": item["borehole"],
                            "sample": item["sample"],
                            "score": item["corrosivity"]["score"],
                            "rating": item["corrosivity"]["rating"],
                            "missing": ", ".join(item["corrosivity"]["missing"]),
                        }
                        for item in details
                    ],
                )
            ],
            notes=[
                "The composite score and rating are read from the active code pack; absent chemistry parameters remain listed as missing rather than assumed."
            ],
        )
    if fid == "soilEarth.durabilityClass":
        present = [
            item for item in summary_data["samples"] if item.get("sulphate") or item.get("flags")
        ]
        if not present:
            raise FeatureInputError(
                "The chemistry records do not support a durability classification."
            )
        return result(
            summary={
                "governingSulphateClass": summary_data.get("sulphateClass"),
                "corrosivityRating": summary_data.get("corrosivityRating"),
                "samplesAssessedCount": len(present),
            },
            tables=[
                table(
                    "Durability exposure by sample",
                    [
                        ("borehole", "Borehole"),
                        ("sample", "Sample"),
                        ("sulphate", "Sulfate class"),
                        ("flags", "Exposure flags"),
                    ],
                    [
                        {
                            "borehole": item["borehole"],
                            "sample": item["sample"],
                            "sulphate": item.get("sulphate"),
                            "flags": "; ".join(item.get("flags", [])),
                        }
                        for item in present
                    ],
                )
            ],
            notes=[
                "The class and exposure criteria come from the active code pack and the measured chemistry; the most severe reported sample governs the summary."
            ],
        )
    if fid == "soilEarth.cementTypeAdvice":
        requirement = summary_data.get("concrete")
        if not requirement:
            raise FeatureInputError(
                "The active pack did not derive a concrete requirement from the recorded chemistry."
            )
        return result(
            summary={
                "maximumWaterCementRatio": requirement["maxWaterCement"],
                "cementType": requirement.get("cement"),
                "noCalciumChloride": requirement.get("noCalciumChloride"),
            },
            tables=[
                table(
                    "Buried-concrete materials advice",
                    [("item", "Requirement"), ("value", "Value")],
                    [
                        {
                            "item": "Maximum water-cement ratio",
                            "value": requirement["maxWaterCement"],
                        },
                        {"item": "Cement type", "value": requirement.get("cement")},
                        {
                            "item": "Calcium chloride admixture prohibited",
                            "value": requirement.get("noCalciumChloride"),
                        },
                        {"item": "Basis", "value": "; ".join(requirement["reasons"])},
                    ],
                )
            ],
            notes=[chemistry_engine.requirement_text(requirement)],
        )
    raise FeatureInputError("Add the corresponding chemical test values to a borehole sample.")


register_tab("soilEarth", _handle, requires_project=_needs_project, fields=_fields)
