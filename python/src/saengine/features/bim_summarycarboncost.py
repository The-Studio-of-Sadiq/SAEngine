"""BIM embodied-carbon, cost, and lifecycle-summary features."""

from __future__ import annotations

from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.bim_common import kind_counts, require_bim, write_bim_json


def _recorded_total(data: dict[str, Any], key: str, label: str) -> tuple[float, int]:
    values = [
        float(element[key])
        for element in data["elements"]
        if isinstance(element, dict)
        and isinstance(element.get(key), (int, float))
        and not isinstance(element.get(key), bool)
    ]
    if not values:
        raise FeatureInputError(f"Record {label} on BIM elements before running this summary.")
    return sum(values), len(values)


@feature("bimSummaryCarbonCost.carbonFactors", "Carbon Factors", part="bim")
def carbon_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign recorded embodied-carbon factors to model material types."""
    data = require_bim(ctx)
    factors = data.get("carbonFactors", {})
    rows = (
        [{"material": k, "factorKgco2ePerKg": v} for k, v in sorted(factors.items())]
        if isinstance(factors, dict)
        else []
    )
    return result(
        summary={"factorCount": len(rows)},
        tables=[
            table(
                "Carbon Factors",
                [("material", "Material"), ("factorKgco2ePerKg", "Factor", "kgCO2e/kg")],
                rows,
            )
        ],
    )


@feature(
    "bimSummaryCarbonCost.calculateCarbon",
    "Calculate Carbon",
    part="bim",
    fields=[number("defaultFactor", "Default factor", 0.8, unit="kgCO2e/kg", min=0)],
)
def calculate_carbon(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate embodied carbon from element mass and recorded factors."""
    data = require_bim(ctx)
    factors = data.get("carbonFactors", {}) if isinstance(data.get("carbonFactors"), dict) else {}
    total = 0.0
    mass_count = 0
    for e in data["elements"]:
        if not isinstance(e, dict) or not isinstance(e.get("massKg"), (int, float)):
            continue
        mass = float(e["massKg"])
        factor = float(factors.get(str(e.get("type", "")), values["defaultFactor"]))
        total += mass * factor
        mass_count += 1
    if not mass_count:
        raise FeatureInputError(
            "Record element masses in 06 BIM/bim.json before calculating carbon."
        )
    return result(
        summary={
            "embodiedCarbonKgCo2e": total,
            "quantifiedElementCount": mass_count,
            "elementCount": len(data["elements"]),
        },
        notes=[
            "Recorded material factors are used when present; the entered default factor applies to other quantified elements."
        ],
    )


@feature("bimSummaryCarbonCost.carbonHotspots", "Carbon Hotspots", part="bim")
def carbon_hotspots(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Rank elements with recorded embodied-carbon contributions."""
    data = require_bim(ctx)
    rows = sorted(
        (
            {"id": e.get("id", ""), "carbonKgCo2e": float(e.get("carbonKgCo2e", 0.0))}
            for e in data["elements"]
            if isinstance(e, dict) and isinstance(e.get("carbonKgCo2e"), (int, float))
        ),
        key=lambda r: r["carbonKgCo2e"],
        reverse=True,
    )
    if not rows:
        raise FeatureInputError(
            "Record element carbon contributions before ranking carbon hotspots."
        )
    return result(
        summary={"hotspotCount": sum(r["carbonKgCo2e"] > 0 for r in rows)},
        tables=[
            table(
                "Carbon Hotspots",
                [("id", "Element"), ("carbonKgCo2e", "Carbon", "kgCO2e")],
                rows[:20],
            )
        ],
    )


@feature("bimSummaryCarbonCost.carbonReport", "Carbon Report", part="bim")
def carbon_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute element embodied carbon (kgCO2e) from BIM geometry, 04 Objects & 03 Materials."""
    import math

    from saengine.features.bim_common import polygon_area

    data = require_bim(ctx)
    elems = [e for e in (data.get("elements") or []) if isinstance(e, dict)]
    objs = {
        str(o.get("id", "")): o
        for o in ((ctx.raw("objects") or {}).get("objects") or [])
        if isinstance(o, dict)
    }
    mats = {
        str(m.get("id", "")): m
        for m in ((ctx.raw("materials") or {}).get("materials") or [])
        if isinstance(m, dict)
    }
    story_elevs = sorted(
        {float(s.get("elevation", 0.0)) for s in (data.get("stories") or []) if isinstance(s, dict)}
    )
    default_h_m = ((story_elevs[1] - story_elevs[0]) / 1000.0) if len(story_elevs) >= 2 else 3.2
    rows = []
    tot_kg = 0.0
    for e in elems:
        explicit = e.get("carbonKgCo2e")
        if isinstance(explicit, (int, float)):
            c_kg = float(explicit)
            mat_name = str(e.get("type", ""))
        else:
            obj = objs.get(str(e.get("type", "")), {})
            mat_id = str(obj.get("material", "C30"))
            mat = mats.get(mat_id, {})
            mat_kind = str(mat.get("kind", "concrete")).lower()
            dens = float(mat.get("density", 7850.0 if mat_kind == "steel" else 2400.0) or 2400.0)
            ec_per_kg = 1.55 if mat_kind == "steel" else 0.14  # ICE A1-A3 cradle-to-gate typical
            prof = obj.get("profile") if isinstance(obj.get("profile"), dict) else {}
            sec_m2 = (
                float(prof.get("width", 300.0) or 300.0) * float(prof.get("depth", 400.0) or 400.0)
            ) / 1e6
            vol_m3 = 0.0
            k = str(e.get("kind", ""))
            if k == "column":
                vol_m3 = sec_m2 * default_h_m
            elif (
                k in ("beam", "wall")
                and isinstance(e.get("start"), list)
                and isinstance(e.get("end"), list)
            ):
                s, en = e["start"], e["end"]
                L_m = math.hypot(float(en[0]) - float(s[0]), float(en[1]) - float(s[1])) / 1000.0
                if k == "wall":
                    vol_m3 = (
                        L_m * default_h_m * (float(obj.get("thickness", 200.0) or 200.0) / 1000.0)
                    )
                else:
                    vol_m3 = sec_m2 * L_m
            elif k == "slab" and isinstance(e.get("polygon"), list):
                vol_m3 = (polygon_area(e["polygon"]) / 1e6) * (
                    float(obj.get("thickness", 150.0) or 150.0) / 1000.0
                )
            c_kg = vol_m3 * dens * ec_per_kg
            mat_name = mat_id
        tot_kg += c_kg
        rows.append(
            {
                "id": str(e.get("id", "")),
                "type": str(e.get("type", "")),
                "material": mat_name,
                "carbonKgCo2e": round(c_kg, 1),
            }
        )
    if not rows:
        raise FeatureInputError("No BIM elements found to compile an embodied carbon report.")
    path = write_bim_json(
        ctx, "embodied-carbon-report.json", {"totalKgCo2e": round(tot_kg, 1), "elements": rows}
    )
    return result(
        summary={
            "elementCount": len(rows),
            "totalKgCo2e": round(tot_kg, 1),
            "totalTonnesCo2e": round(tot_kg / 1000.0, 2),
            "exportPath": path,
        },
        tables=[
            table(
                "Embodied Carbon Report (A1-A3)",
                [
                    ("id", "Element"),
                    ("type", "Type"),
                    ("material", "Material"),
                    ("carbonKgCo2e", "Carbon", "kgCO2e"),
                ],
                rows,
            )
        ],
        notes=[
            f"Computed A1-A3 embodied carbon ({tot_kg / 1000.0:.2f} tCO2e) across {len(rows)} BIM element(s); saved to {path}."
        ],
    )


@feature(
    "bimSummaryCarbonCost.epdDatabase",
    "EPD Database",
    part="bim",
    fields=[text("epdQuery", "EPD material or product", "")],
)
def epd_database(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Search the local EPD records if present; no network access."""
    data = require_bim(ctx)
    epds = data.get("epdRecords", []) if isinstance(data.get("epdRecords"), list) else []
    query = values["epdQuery"].lower()
    rows = [r for r in epds if isinstance(r, dict) and (not query or query in str(r).lower())]
    return result(
        summary={"recordCount": len(rows)},
        tables=[
            table(
                "EPD Records",
                [("name", "Product"), ("factorKgco2ePerKg", "Factor", "kgCO2e/kg")],
                rows,
            )
        ],
    )


@feature("bimSummaryCarbonCost.rateLibrary", "Rate Library", part="bim")
def rate_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Open the project-local unit-rate records."""
    data = require_bim(ctx)
    rates = data.get("unitRates", [])
    rows = rates if isinstance(rates, list) else []
    return result(
        summary={"rateCount": len(rows)},
        tables=[
            table(
                "Unit Rates",
                [("code", "Cost code"), ("description", "Description"), ("rate", "Unit rate")],
                rows,
            )
        ],
    )


@feature("bimSummaryCarbonCost.mapQuantities", "Map Quantities", part="bim")
def map_quantities(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Link object quantities to cost-item codes."""
    data = require_bim(ctx)
    rows = [{"kind": k, "costCode": str(k).upper()} for k in sorted(kind_counts(data))]
    return result(
        summary={"mappingCount": len(rows)},
        tables=[table("Quantity Mapping", [("kind", "Category"), ("costCode", "Cost code")], rows)],
    )


@feature(
    "bimSummaryCarbonCost.escalation",
    "Escalation",
    part="bim",
    fields=[
        number("escalationPercent", "Annual escalation", 3.0, unit="%/year", min=-20, max=100),
        number("years", "Escalation period", 1.0, unit="year", min=0, max=100),
    ],
)
def escalation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply compound time-based cost escalation to a base cost."""
    data = require_bim(ctx)
    base = sum(float(e.get("cost", 0.0)) for e in data["elements"])
    factor = (1 + values["escalationPercent"] / 100) ** values["years"]
    return result(
        summary={
            "baseCost": base,
            "escalatedCost": base * factor,
            "escalationPercent": values["escalationPercent"],
        }
    )


@feature("bimSummaryCarbonCost.costTotals", "Cost Totals", part="bim")
def cost_totals(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Roll up recorded element costs by category."""
    data = require_bim(ctx)
    totals: dict[str, float] = {}
    for e in data["elements"]:
        if not isinstance(e, dict) or not isinstance(e.get("cost"), (int, float)):
            continue
        kind = str(e.get("kind", "unknown"))
        totals[kind] = totals.get(kind, 0.0) + float(e["cost"])
    if not totals:
        raise FeatureInputError("Record element costs before calculating cost totals.")
    rows = [{"kind": k, "cost": v} for k, v in sorted(totals.items())]
    return result(
        summary={"costTotal": sum(totals.values())},
        tables=[table("Cost Totals", [("kind", "Category"), ("cost", "Cost")], rows)],
    )


@feature("bimSummaryCarbonCost.summaryChart", "Summary Chart", part="bim")
def summary_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Split total carbon and cost into one category table."""
    data = require_bim(ctx)
    rows = []
    for kind in sorted(kind_counts(data)):
        elements = [e for e in data["elements"] if isinstance(e, dict) and e.get("kind") == kind]
        carbon_values = [
            e["carbonKgCo2e"] for e in elements if isinstance(e.get("carbonKgCo2e"), (int, float))
        ]
        cost_values = [e["cost"] for e in elements if isinstance(e.get("cost"), (int, float))]
        if not carbon_values and not cost_values:
            continue
        rows.append(
            {
                "kind": kind,
                "carbonKgCo2e": sum(carbon_values) if carbon_values else None,
                "cost": sum(cost_values) if cost_values else None,
            }
        )
    if not rows:
        raise FeatureInputError(
            "Record carbon or cost values on BIM elements before making this chart."
        )
    return result(
        summary={"categoryCount": len(rows)},
        tables=[
            table(
                "Carbon and Cost",
                [("kind", "Category"), ("carbonKgCo2e", "Carbon", "kgCO2e"), ("cost", "Cost")],
                rows,
            )
        ],
    )


@feature("bimSummaryCarbonCost.breakdownTable", "Breakdown Table", part="bim")
def breakdown_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Break carbon and cost results down by category."""
    data = require_bim(ctx)
    _recorded_total(data, "carbonKgCo2e", "element carbon contributions")
    rows = [
        {
            "kind": k,
            "elementCount": v,
            "carbonKgCo2e": (
                sum(
                    float(e["carbonKgCo2e"])
                    for e in data["elements"]
                    if isinstance(e, dict)
                    and e.get("kind") == k
                    and isinstance(e.get("carbonKgCo2e"), (int, float))
                )
                if any(
                    isinstance(e, dict)
                    and e.get("kind") == k
                    and isinstance(e.get("carbonKgCo2e"), (int, float))
                    for e in data["elements"]
                )
                else None
            ),
        }
        for k, v in sorted(kind_counts(data).items())
    ]
    return result(
        summary={"categoryCount": len(rows)},
        tables=[
            table(
                "Breakdown",
                [
                    ("kind", "Category"),
                    ("elementCount", "Elements"),
                    ("carbonKgCo2e", "Carbon", "kgCO2e"),
                ],
                rows,
            )
        ],
    )


@feature(
    "bimSummaryCarbonCost.targets",
    "Targets",
    part="bim",
    fields=[
        number("carbonTargetKgCo2e", "Carbon target", 100000.0, unit="kgCO2e", min=0),
        number("costTarget", "Cost target", 1000000.0, unit="currency", min=0),
    ],
)
def targets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set carbon and cost targets and report variance from current values."""
    data = require_bim(ctx)
    carbon, _ = _recorded_total(data, "carbonKgCo2e", "element carbon contributions")
    cost, _ = _recorded_total(data, "cost", "element costs")
    return result(
        summary={
            "carbonVarianceKgCo2e": carbon - values["carbonTargetKgCo2e"],
            "costVariance": cost - values["costTarget"],
        }
    )


@feature("bimSummaryCarbonCost.exportDashboard", "Export Dashboard", part="bim")
def export_dashboard(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export dashboard metrics as JSON data."""
    data = require_bim(ctx)
    carbon, _ = _recorded_total(data, "carbonKgCo2e", "element carbon contributions")
    cost, _ = _recorded_total(data, "cost", "element costs")
    payload = {
        "categories": kind_counts(data),
        "carbonKgCo2e": carbon,
        "cost": cost,
    }
    path = write_bim_json(ctx, "carbon-cost-dashboard.json", payload)
    return result(summary={"exportPath": path})


@feature(
    "bimSummaryCarbonCost.energyIntensity",
    "Energy Intensity",
    part="bim",
    fields=[
        number("annualEnergyKwh", "Annual energy", 100000.0, unit="kWh/year", min=0),
        number("floorAreaM2", "Floor area", 1000.0, unit="m²", min=0.1),
    ],
)
def energy_intensity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate annual energy intensity per unit floor area."""
    require_bim(ctx)
    intensity = values["annualEnergyKwh"] / values["floorAreaM2"]
    return result(summary={"energyIntensityKwhPerM2Year": intensity})


@feature(
    "bimSummaryCarbonCost.carbonOffset",
    "Carbon Offset",
    part="bim",
    fields=[
        number("renewableOffsetKgCo2eYear", "Renewable offset", 10000.0, unit="kgCO2e/year", min=0),
        number("grossCarbonKgCo2e", "Gross carbon", 100000.0, unit="kgCO2e", min=0),
    ],
)
def carbon_offset(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Model annual renewable offsets against building carbon."""
    require_bim(ctx)
    net = max(values["grossCarbonKgCo2e"] - values["renewableOffsetKgCo2eYear"], 0.0)
    return result(
        summary={
            "netCarbonKgCo2e": net,
            "offsetPercent": (values["grossCarbonKgCo2e"] - net) / values["grossCarbonKgCo2e"] * 100
            if values["grossCarbonKgCo2e"]
            else 0,
        }
    )


@feature(
    "bimSummaryCarbonCost.lifecycleCarbon",
    "Lifecycle Carbon",
    part="bim",
    fields=[
        number("initialKgCo2e", "Initial carbon", 100000.0, unit="kgCO2e", min=0),
        number("operationalKgCo2e", "Operational carbon", 50000.0, unit="kgCO2e", min=0),
        number("endOfLifeKgCo2e", "End-of-life carbon", 10000.0, unit="kgCO2e", min=0),
    ],
)
def lifecycle_carbon(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assess cradle-to-grave carbon including operational and end-of-life stages."""
    require_bim(ctx)
    total = values["initialKgCo2e"] + values["operationalKgCo2e"] + values["endOfLifeKgCo2e"]
    return result(
        summary={"lifecycleCarbonKgCo2e": total},
        tables=[
            table(
                "Lifecycle Carbon",
                [("stage", "Stage"), ("carbonKgCo2e", "Carbon", "kgCO2e")],
                [
                    {"stage": "Initial", "carbonKgCo2e": values["initialKgCo2e"]},
                    {"stage": "Operational", "carbonKgCo2e": values["operationalKgCo2e"]},
                    {"stage": "End of life", "carbonKgCo2e": values["endOfLifeKgCo2e"]},
                ],
            )
        ],
    )


@feature("bimSummaryCarbonCost.costOptimization", "Cost Optimization", part="bim")
def cost_optimization(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report lowest-cost recorded material alternatives."""
    data = require_bim(ctx)
    alternatives = data.get("costAlternatives", [])
    rows = sorted(
        [r for r in alternatives if isinstance(r, dict)], key=lambda r: float(r.get("cost", 1e30))
    )
    return result(
        summary={"alternativeCount": len(rows)},
        tables=[
            table(
                "Cost Alternatives",
                [("name", "Alternative"), ("cost", "Cost"), ("carbonKgCo2e", "Carbon", "kgCO2e")],
                rows,
            )
        ],
    )


@feature(
    "bimSummaryCarbonCost.materialSwap",
    "Material Swap",
    part="bim",
    fields=[
        text("fromMaterial", "Original material", "Concrete"),
        text("toMaterial", "Alternative material", "Low-carbon concrete"),
    ],
)
def material_swap(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a named material substitution using recorded element metrics."""
    data = require_bim(ctx)
    if not any(
        isinstance(e, dict) and ("swapCostDelta" in e or "swapCarbonDeltaKgCo2e" in e)
        for e in data["elements"]
    ):
        raise FeatureInputError(
            "Record material-swap deltas on BIM elements before evaluating a swap."
        )
    cost_delta = sum(float(e.get("swapCostDelta", 0.0)) for e in data["elements"])
    carbon_delta = sum(float(e.get("swapCarbonDeltaKgCo2e", 0.0)) for e in data["elements"])
    return result(
        summary={
            "costDelta": cost_delta,
            "carbonDeltaKgCo2e": carbon_delta,
            "fromMaterial": values["fromMaterial"],
            "toMaterial": values["toMaterial"],
        }
    )


@feature("bimSummaryCarbonCost.costVariance", "Cost Variance", part="bim")
def cost_variance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Track budget deviations against baseline and detailed model costs."""
    data = require_bim(ctx)
    baseline, _ = _recorded_total(data, "baselineCost", "baseline costs")
    current, _ = _recorded_total(data, "cost", "element costs")
    return result(
        summary={"baselineCost": baseline, "currentCost": current, "variance": current - baseline}
    )


@feature(
    "bimSummaryCarbonCost.lccAnalysis",
    "LCC Analysis",
    part="bim",
    fields=[
        number("initialCost", "Initial cost", 1000000.0, unit="currency", min=0),
        number("annualCost", "Annual cost", 20000.0, unit="currency/year", min=0),
        number("lifeYears", "Design life", 50.0, unit="year", min=1),
    ],
)
def lcc_analysis(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate simple undiscounted ownership cost over design life."""
    require_bim(ctx)
    total = values["initialCost"] + values["annualCost"] * values["lifeYears"]
    return result(summary={"lifecycleCost": total, "designLifeYears": values["lifeYears"]})


@feature(
    "bimSummaryCarbonCost.maintenanceCost",
    "Maintenance Cost",
    part="bim",
    fields=[
        number("annualMaintenance", "Annual maintenance", 10000.0, unit="currency/year", min=0),
        number("lifeYears", "Life", 50.0, unit="year", min=1),
    ],
)
def maintenance_cost(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate long-term maintenance expenditure."""
    require_bim(ctx)
    return result(summary={"maintenanceCost": values["annualMaintenance"] * values["lifeYears"]})


@feature("bimSummaryCarbonCost.replacementSchedule", "Replacement Schedule", part="bim")
def replacement_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Forecast end-of-service replacements from recorded component lifetimes."""
    data = require_bim(ctx)
    rows = [
        {"id": e.get("id", ""), "replacementYear": e.get("replacementYear", "")}
        for e in data["elements"]
        if e.get("replacementYear") is not None
    ]
    return result(
        summary={"replacementCount": len(rows)},
        tables=[
            table(
                "Replacement Schedule",
                [("id", "Component"), ("replacementYear", "Replacement year")],
                rows,
            )
        ],
    )
