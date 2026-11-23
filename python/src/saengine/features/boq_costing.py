"""BOQ - Costing tab: rate build-ups, labour/plant/material rates, markups, escalation & cash flow."""

from __future__ import annotations

import math
from typing import Any

from saengine.boq.costing import PARTS, cost_bill
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.boq_common import (
    load_rates,
    parse_csv_rows,
    price_project_bill,
    require_bill,
)


@feature(
    "boqCosting.rateBuildUp",
    "Rate Build-Up",
    part="boq",
    fields=[
        text("itemName", "Work item", "Reinforced concrete in columns (per m3)"),
        number("materialCost", "Material supply cost per unit", 9200.0, min=0.0),
        number("labourCost", "Labour cost per unit", 1850.0, min=0.0),
        number("plantCost", "Plant & equipment cost per unit", 950.0, min=0.0),
        number("wastePct", "Material wastage allowance", 3.0, unit="%", min=0.0, max=30.0),
        number("ohpPct", "Overheads & profit markup", 15.0, unit="%", min=0.0, max=50.0),
    ],
    requires_project=False,
)
def rate_build_up(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build a unit rate from material (with wastage), labour, plant, and overhead/profit markups."""
    mat = values["materialCost"] * (1.0 + values["wastePct"] / 100.0)
    lab = values["labourCost"]
    plt = values["plantCost"]
    net = mat + lab + plt
    ohp = net * values["ohpPct"] / 100.0
    total = net + ohp
    rows = [
        {
            "component": f"Materials (incl. {values['wastePct']:g}% waste)",
            "cost": mat,
            "sharePct": mat / total * 100.0 if total else 0.0,
        },
        {"component": "Labour", "cost": lab, "sharePct": lab / total * 100.0 if total else 0.0},
        {
            "component": "Plant & equipment",
            "cost": plt,
            "sharePct": plt / total * 100.0 if total else 0.0,
        },
        {
            "component": f"Overheads & profit ({values['ohpPct']:g}%)",
            "cost": ohp,
            "sharePct": ohp / total * 100.0 if total else 0.0,
        },
        {"component": "Built-up unit rate", "cost": total, "sharePct": 100.0},
    ]
    return result(
        summary={
            "netDirectRate": net,
            "builtUpRate": total,
            "materialSharePct": mat / total * 100.0 if total else 0.0,
        },
        tables=[
            table(
                f"Rate build-up: {values['itemName']}",
                [("component", "Component"), ("cost", "Unit cost"), ("sharePct", "Share", "%")],
                rows,
            )
        ],
        notes=["Unit rate = (Material*(1+waste) + Labour + Plant) * (1 + OH&P)."],
    )


@feature(
    "boqCosting.labourRates",
    "Labour Rates",
    part="boq",
    fields=[
        text(
            "crewCsv",
            "Crew CSV (trade,count,daily_wage,hours_per_day)",
            "Mason,2,950,8\nSteel Fixer,3,900,8\nHelper,4,650,8\nForeman,1,1300,8",
        ),
        number("dailyOutput", "Crew daily output quantity", 12.0, min=0.1),
        text("outputUnit", "Output unit", "m3"),
        number("burdenPct", "Statutory/supervision on-cost", 12.0, unit="%", min=0.0, max=50.0),
    ],
    requires_project=False,
)
def labour_rates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute crew daily cost, hourly rate, and unit labour cost from gang composition and productivity."""
    raw = parse_csv_rows(values["crewCsv"])
    rows = []
    tot_daily = 0.0
    tot_heads = 0
    for r in raw:
        try:
            trade = r["trade"]
            cnt = int(float(r["count"]))
            wage = float(r["daily_wage"])
            hrs = float(r.get("hours_per_day", 8.0))
        except (KeyError, ValueError) as exc:
            raise FeatureInputError(
                "CSV requires trade, count, daily_wage, hours_per_day."
            ) from exc
        cost = cnt * wage * (1.0 + values["burdenPct"] / 100.0)
        tot_daily += cost
        tot_heads += cnt
        rows.append(
            {
                "trade": trade,
                "count": cnt,
                "dailyWage": wage,
                "hourlyEq": wage / hrs,
                "burdenedDaily": cost,
            }
        )
    unit_labour = tot_daily / values["dailyOutput"]
    return result(
        summary={
            "crewSize": tot_heads,
            "dailyCrewCost": tot_daily,
            "unitLabourCost": unit_labour,
            "unit": values["outputUnit"],
        },
        tables=[
            table(
                "Labour crew rate build-up",
                [
                    ("trade", "Trade"),
                    ("count", "Headcount"),
                    ("dailyWage", "Base wage/day"),
                    ("hourlyEq", "Base/hr"),
                    ("burdenedDaily", "Burdened daily"),
                ],
                rows,
            )
        ],
        notes=[
            f"Includes {values['burdenPct']:g}% labour on-cost over {values['dailyOutput']:g} {values['outputUnit']}/day output."
        ],
    )


@feature(
    "boqCosting.plantRates",
    "Plant Rates",
    part="boq",
    fields=[
        number("purchasePrice", "Equipment capital cost", 4500000.0, min=1000.0),
        number("lifeYears", "Useful economic life", 8.0, unit="yr", min=1.0),
        number("salvagePct", "Residual salvage value", 15.0, unit="%", min=0.0, max=50.0),
        number("hoursPerYear", "Operating hours per year", 1600.0, unit="hr/yr", min=100.0),
        number("fuelAndMaintPerHr", "Fuel, consumables & maintenance/hr", 850.0, min=0.0),
        number("operatorPerHr", "Operator wage/hr", 220.0, min=0.0),
    ],
    requires_project=False,
)
def plant_rates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate hourly plant owning, standing, and operating rates from capital depreciation and fuel."""
    cap = values["purchasePrice"]
    salv = cap * values["salvagePct"] / 100.0
    hrs = values["hoursPerYear"]
    dep_hr = (cap - salv) / (values["lifeYears"] * hrs)
    interest_hr = 0.08 * (0.5 * (cap + salv)) / hrs
    standing_hr = dep_hr + interest_hr
    operating_hr = values["fuelAndMaintPerHr"] + values["operatorPerHr"]
    total_hr = standing_hr + operating_hr
    rows = [
        {"component": "Straight-line depreciation", "perHour": dep_hr},
        {"component": "Capital finance / insurance (8% avg)", "perHour": interest_hr},
        {"component": "Standing charge subtotal", "perHour": standing_hr},
        {"component": "Fuel, oil & maintenance", "perHour": values["fuelAndMaintPerHr"]},
        {"component": "Operator", "perHour": values["operatorPerHr"]},
        {"component": "All-in hourly plant rate", "perHour": total_hr},
    ]
    return result(
        summary={
            "standingPerHour": standing_hr,
            "operatingPerHour": operating_hr,
            "allInHourlyRate": total_hr,
        },
        tables=[
            table(
                "Hourly plant rate analysis",
                [("component", "Cost element"), ("perHour", "Rate / hour")],
                rows,
            )
        ],
        notes=[
            "Standing charge spreads capital depreciation and 8% average finance over annual utilisation hours."
        ],
    )


@feature(
    "boqCosting.materialRates",
    "Material Rates",
    part="boq",
    fields=[
        number("baseSupplyPrice", "Ex-works / supplier base price", 7500.0, min=0.0),
        number("deliveryCharge", "Transport & unloading per unit", 450.0, min=0.0),
        number("wastagePct", "Site handling & cutting wastage", 4.0, unit="%", min=0.0, max=30.0),
        number("discountPct", "Bulk trade discount", 2.0, unit="%", min=0.0, max=30.0),
    ],
    requires_project=False,
)
def material_rates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute landed site material rates accounting for trade discount, haulage, and wastage."""
    discounted = values["baseSupplyPrice"] * (1.0 - values["discountPct"] / 100.0)
    delivered = discounted + values["deliveryCharge"]
    wastage = delivered * values["wastagePct"] / 100.0
    net_rate = delivered + wastage
    return result(
        summary={
            "deliveredRate": delivered,
            "wastageCost": wastage,
            "effectiveMaterialRate": net_rate,
        },
        tables=[
            table(
                "Delivered material rate calculation",
                [("step", "Cost element"), ("amount", "Amount")],
                [
                    {"step": "Supplier base price", "amount": values["baseSupplyPrice"]},
                    {
                        "step": f"After {values['discountPct']:g}% bulk discount",
                        "amount": discounted,
                    },
                    {"step": "Delivered to site (+ haulage)", "amount": delivered},
                    {"step": f"Wastage allowance ({values['wastagePct']:g}%)", "amount": wastage},
                    {"step": "Effective BOQ material rate", "amount": net_rate},
                ],
            )
        ],
        notes=["Wastage is applied to the delivered-to-site cost."],
    )


@feature(
    "boqCosting.markupsOverheads",
    "Markups & Overheads",
    part="boq",
    fields=[
        number(
            "siteOverheadsPct", "Site preliminaries & supervision", 7.0, unit="%", min=0.0, max=40.0
        ),
        number("headOfficePct", "Head office overheads", 4.0, unit="%", min=0.0, max=30.0),
        number("profitPct", "Profit margin", 8.0, unit="%", min=0.0, max=40.0),
        number("riskPct", "Commercial risk allowance", 2.5, unit="%", min=0.0, max=30.0),
    ],
    requires_project=True,
)
def markups_overheads(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply site overheads, head office, profit, and risk markups to the priced project bill."""
    _, rates, _, costing = price_project_bill(ctx)
    base = costing.total
    site_oh = base * values["siteOverheadsPct"] / 100.0
    ho_oh = (base + site_oh) * values["headOfficePct"] / 100.0
    sub = base + site_oh + ho_oh
    profit = sub * values["profitPct"] / 100.0
    risk = sub * values["riskPct"] / 100.0
    total = sub + profit + risk
    rows = [
        {"tier": "Direct BOQ cost", "amount": base},
        {"tier": "Site preliminaries", "amount": site_oh},
        {"tier": "Head office overheads", "amount": ho_oh},
        {"tier": "Profit margin", "amount": profit},
        {"tier": "Risk markup", "amount": risk},
        {"tier": "Marked-up total", "amount": total},
    ]
    return result(
        summary={
            "currency": rates.currency,
            "directCost": base,
            "markedUpTotal": total,
            "effectiveMarkupPct": ((total - base) / base * 100.0) if base else 0.0,
        },
        tables=[
            table(
                f"Markups & overheads ({rates.currency})",
                [("tier", "Cost tier"), ("amount", "Amount")],
                rows,
            )
        ],
        notes=["Applies overheads sequentially before profit and risk percentage."],
    )


@feature(
    "boqCosting.contingency",
    "Contingency",
    part="boq",
    fields=[
        number("designDevPct", "Design development contingency", 3.0, unit="%", min=0.0, max=30.0),
        number("geotechRiskPct", "Substructure / ground risk", 6.0, unit="%", min=0.0, max=40.0),
        number(
            "constructionPct",
            "Construction & employer change reserve",
            4.0,
            unit="%",
            min=0.0,
            max=30.0,
        ),
    ],
    requires_project=True,
)
def contingency_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Allocate project contingency by risk category against Superstructure, Substructure, and overall bill."""
    _, rates, _, costing = price_project_bill(ctx)
    sub_cost = costing.parts.get("Substructure", 0.0)
    sup_cost = costing.total - sub_cost
    c_design = costing.total * values["designDevPct"] / 100.0
    c_geo = sub_cost * values["geotechRiskPct"] / 100.0
    c_const = costing.total * values["constructionPct"] / 100.0
    tot_cont = c_design + c_geo + c_const
    rows = [
        {
            "category": "Design development (all works)",
            "basis": costing.total,
            "pct": values["designDevPct"],
            "reserve": c_design,
        },
        {
            "category": "Ground / foundation risk (Substructure)",
            "basis": sub_cost,
            "pct": values["geotechRiskPct"],
            "reserve": c_geo,
        },
        {
            "category": "Construction variation reserve",
            "basis": costing.total,
            "pct": values["constructionPct"],
            "reserve": c_const,
        },
        {
            "category": "Total contingency",
            "basis": costing.total,
            "pct": (tot_cont / costing.total * 100.0) if costing.total else 0.0,
            "reserve": tot_cont,
        },
    ]
    return result(
        summary={
            "currency": rates.currency,
            "baseCost": costing.total,
            "totalContingency": tot_cont,
            "budgetWithContingency": costing.total + tot_cont,
            "superstructureCost": sup_cost,
        },
        tables=[
            table(
                f"Risk-based contingency allocation ({rates.currency})",
                [
                    ("category", "Risk category"),
                    ("basis", "Cost basis"),
                    ("pct", "Rate", "%"),
                    ("reserve", "Contingency"),
                ],
                rows,
            )
        ],
        notes=["Ground risk contingency targets Substructure items specifically."],
    )


@feature(
    "boqCosting.currencyTax",
    "Currency & Tax",
    part="boq",
    fields=[
        text("targetCurrency", "Target currency code", "USD"),
        number("exchangeRate", "Units of bill currency per 1 target unit", 120.0, min=0.001),
        number("vatPct", "VAT / sales tax", 7.5, unit="%", min=0.0, max=30.0),
        number(
            "withholdingPct", "Advance income / withholding tax", 3.0, unit="%", min=0.0, max=20.0
        ),
    ],
    requires_project=True,
)
def currency_tax(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert the priced bill into a target currency and compute VAT and withholding tax totals."""
    _, rates, _, costing = price_project_bill(ctx)
    ex = values["exchangeRate"]
    net_target = costing.total / ex
    vat_target = net_target * values["vatPct"] / 100.0
    wht_target = net_target * values["withholdingPct"] / 100.0
    gross_target = net_target + vat_target
    rows = [
        {"item": f"Net bill ({rates.currency})", "value": costing.total},
        {"item": f"Net bill ({values['targetCurrency']})", "value": net_target},
        {"item": f"VAT @ {values['vatPct']:g}% ({values['targetCurrency']})", "value": vat_target},
        {
            "item": f"Withholding tax @ {values['withholdingPct']:g}% ({values['targetCurrency']})",
            "value": wht_target,
        },
        {"item": f"Gross inclusive total ({values['targetCurrency']})", "value": gross_target},
    ]
    return result(
        summary={
            "sourceCurrency": rates.currency,
            "targetCurrency": values["targetCurrency"],
            "netTarget": net_target,
            "grossTarget": gross_target,
        },
        tables=[
            table(
                "Currency conversion & tax schedule", [("item", "Line"), ("value", "Amount")], rows
            )
        ],
        notes=[f"Converted at 1 {values['targetCurrency']} = {ex:g} {rates.currency}."],
    )


@feature(
    "boqCosting.costPerArea",
    "Cost Per Area",
    part="boq",
    fields=[
        number("gfaM2", "Gross floor area (0 = derive from slab concrete)", 0.0, unit="m2", min=0.0)
    ],
    requires_project=True,
)
def cost_per_area(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive benchmark cost per square metre of gross floor area across trades and building parts."""
    bill, rates, _, costing = price_project_bill(ctx)
    gfa = values["gfaM2"]
    if gfa <= 0:
        # Estimate from slab formwork area or slab concrete / 0.15 m
        slab_form = sum(
            float(it.get("quantity", 0.0))
            for it in bill["items"]
            if it.get("group") == "formwork" and it.get("kind") == "slab"
        )
        gfa = slab_form if slab_form > 0 else 500.0
    rows = [
        {"group": grp, "amount": amt, "costPerM2": amt / gfa} for grp, amt in costing.groups.items()
    ]
    return result(
        summary={
            "currency": rates.currency,
            "gfaM2": gfa,
            "totalCost": costing.total,
            "costPerM2": costing.total / gfa,
        },
        tables=[
            table(
                f"Cost per m2 benchmark ({rates.currency})",
                [("group", "Trade group"), ("amount", "Total cost"), ("costPerM2", "Cost / m2")],
                rows,
            )
        ],
        notes=["When GFA = 0, floor area is estimated from slab soffit formwork area."],
    )


@feature(
    "boqCosting.rateComparison",
    "Rate Comparison",
    part="boq",
    fields=[number("indexFactor", "Benchmark library multiplier", 1.05, min=0.2, max=5.0)],
    requires_project=True,
)
def rate_comparison(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare active project unit rates against scaled reference schedule rates."""
    bill = require_bill(ctx)
    rates, is_proj = load_rates(ctx)
    costing = cost_bill(bill, rates)
    fac = values["indexFactor"]
    rows = []
    tot_ref = 0.0
    for li in costing.lines:
        if li.rate is None or li.amount is None:
            continue
        ref_amt = li.amount * fac
        tot_ref += ref_amt
        rows.append(
            {
                "code": li.code,
                "description": li.description,
                "projectRate": li.rate,
                "refRate": li.rate * fac,
                "variance": li.amount - ref_amt,
            }
        )
    return result(
        summary={
            "rateSource": "project" if is_proj else "sample",
            "projectTotal": costing.total,
            "benchmarkTotal": tot_ref,
            "variance": costing.total - tot_ref,
        },
        tables=[
            table(
                f"Rate comparison ({rates.currency})",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("projectRate", "Project rate"),
                    ("refRate", "Benchmark"),
                    ("variance", "Amount delta"),
                ],
                rows[:40],
            )
        ],
        notes=["Compares priced bill items against indexed reference rates."],
    )


@feature(
    "boqCosting.costDrivers",
    "Cost Drivers",
    part="boq",
    fields=[number("paretoPct", "Cumulative Pareto threshold", 80.0, unit="%", min=10.0, max=99.0)],
    requires_project=True,
)
def cost_drivers(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Rank BOQ items by cost contribution to identify top Pareto cost drivers."""
    _, rates, _, costing = price_project_bill(ctx)
    ranked = sorted((li for li in costing.lines if li.amount), key=lambda l: -(l.amount or 0.0))
    tot = costing.total or 1.0
    cum = 0.0
    rows = []
    drivers = 0
    for li in ranked:
        amt = li.amount or 0.0
        pct = amt / tot * 100.0
        cum += pct
        if cum - pct < values["paretoPct"]:
            drivers += 1
        rows.append(
            {
                "code": li.code,
                "description": li.description,
                "amount": amt,
                "sharePct": pct,
                "cumPct": cum,
            }
        )
    return result(
        summary={
            "currency": rates.currency,
            "pricedItems": len(rows),
            "paretoDriverCount": drivers,
            "topItemSharePct": rows[0]["sharePct"] if rows else 0.0,
        },
        tables=[
            table(
                "Top BOQ cost drivers (Pareto)",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("amount", "Amount"),
                    ("sharePct", "Share", "%"),
                    ("cumPct", "Cumulative", "%"),
                ],
                rows[:25],
            )
        ],
        notes=[f"Top {drivers} items account for {values['paretoPct']:g}% of direct bill cost."],
    )


@feature(
    "boqCosting.priceEscalation",
    "Price Escalation",
    part="boq",
    fields=[
        number(
            "annualInflationPct",
            "Annual tender escalation rate",
            6.5,
            unit="%",
            min=-10.0,
            max=40.0,
        ),
        number(
            "monthsToMidpoint",
            "Months from base date to construction midpoint",
            14.0,
            unit="months",
            min=0.0,
        ),
    ],
    requires_project=True,
)
def price_escalation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply compound price escalation indices to the BOQ for future construction periods."""
    _, rates, _, costing = price_project_bill(ctx)
    yrs = values["monthsToMidpoint"] / 12.0
    factor = (1.0 + values["annualInflationPct"] / 100.0) ** yrs
    esc_total = costing.total * factor
    rows = [
        {
            "group": g,
            "baseAmount": a,
            "escalatedAmount": a * factor,
            "escalationDelta": a * (factor - 1.0),
        }
        for g, a in costing.groups.items()
    ]
    return result(
        summary={
            "escalationFactor": factor,
            "baseTotal": costing.total,
            "escalatedTotal": esc_total,
            "escalationAmount": esc_total - costing.total,
        },
        tables=[
            table(
                f"Escalated cost by trade ({rates.currency})",
                [
                    ("group", "Group"),
                    ("baseAmount", "Base"),
                    ("escalatedAmount", "Escalated"),
                    ("escalationDelta", "Increase"),
                ],
                rows,
            )
        ],
        notes=[
            f"Compound escalation over {values['monthsToMidpoint']:g} months at {values['annualInflationPct']:g}%/yr."
        ],
    )


@feature(
    "boqCosting.cashFlow",
    "Cash Flow",
    part="boq",
    fields=[
        number("durationMonths", "Construction duration", 12.0, unit="months", min=2.0, max=60.0),
        number("advancePct", "Mobilisation advance payment", 10.0, unit="%", min=0.0, max=30.0),
        number("retentionPct", "Retention deduction", 5.0, unit="%", min=0.0, max=15.0),
    ],
    requires_project=True,
)
def cash_flow(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Forecast monthly S-curve cash flow with mobilisation advance and retention deductions."""
    _, rates, _, costing = price_project_bill(ctx)
    n = round(values["durationMonths"])
    tot = costing.total
    adv = tot * values["advancePct"] / 100.0
    ret_f = values["retentionPct"] / 100.0

    # Logistic S-curve cumulative fraction: f(t) = 1 / (1 + exp(-8*(t - 0.5))) normalized [0, 1]
    def _s(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-8.0 * (x - 0.5)))

    s0, s1 = _s(0.0), _s(1.0)
    prev = 0.0
    rows = []
    cum_net = adv
    for m in range(1, n + 1):
        cum_f = (_s(m / n) - s0) / (s1 - s0)
        gross_m = tot * (cum_f - prev)
        prev = cum_f
        ret_m = gross_m * ret_f
        adv_rec = adv / n
        net_m = gross_m - ret_m - adv_rec
        cum_net += net_m
        rows.append(
            {
                "month": m,
                "cumProgressPct": cum_f * 100.0,
                "grossMonthly": gross_m,
                "netPayment": net_m,
                "cumCash": cum_net,
            }
        )
    return result(
        summary={
            "currency": rates.currency,
            "contractValue": tot,
            "peakMonthlyGross": max(r["grossMonthly"] for r in rows),
            "mobilisationAdvance": adv,
        },
        tables=[
            table(
                f"Monthly cash-flow forecast ({rates.currency})",
                [
                    ("month", "Month"),
                    ("cumProgressPct", "Progress", "%"),
                    ("grossMonthly", "Gross work"),
                    ("netPayment", "Net cert"),
                    ("cumCash", "Cum cash"),
                ],
                rows,
            )
        ],
        notes=["Uses symmetric logistic S-curve distribution with linear advance recovery."],
    )


@feature(
    "boqCosting.workPackages",
    "Work Packages",
    part="boq",
    fields=[],
    requires_project=True,
)
def work_packages(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group BOQ line items into standard subcontract and procurement trade packages."""
    _, rates, _, costing = price_project_bill(ctx)
    pkg_map = {
        "earthwork": "PKG-01 Civil & Earthworks",
        "concrete": "PKG-02 Concrete Supply & Pour",
        "formwork": "PKG-03 Formwork & Falsework",
        "reinforcement": "PKG-04 Reinforcement Steel",
        "steel": "PKG-05 Structural Steelwork",
        "masonry": "PKG-06 Masonry & Partitions",
        "finishes": "PKG-07 Architectural Finishes",
        "mep": "PKG-08 MEP Services",
        "materials": "PKG-09 Loose Materials",
    }
    agg: dict[str, dict[str, Any]] = {}
    for li in costing.lines:
        pkg = pkg_map.get(li.group, "PKG-99 General Works")
        rec = agg.setdefault(pkg, {"package": pkg, "items": 0, "amount": 0.0})
        rec["items"] += 1
        rec["amount"] += li.amount or 0.0
    rows = sorted(agg.values(), key=lambda r: -r["amount"])
    return result(
        summary={
            "currency": rates.currency,
            "packageCount": len(rows),
            "totalValue": costing.total,
        },
        tables=[
            table(
                f"Subcontract work packages ({rates.currency})",
                [("package", "Work package"), ("items", "Items"), ("amount", "Package value")],
                rows,
            )
        ],
        notes=["Groups bill items into tenderable procurement packages."],
    )


@feature(
    "boqCosting.tenderBreakdown",
    "Tender Breakdown",
    part="boq",
    fields=[],
    requires_project=True,
)
def tender_breakdown(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Break tender value down by building part (Substructure, Superstructure, Architecture, MEP)."""
    _, rates, _, costing = price_project_bill(ctx)
    rows = [
        {
            "part": p,
            "amount": costing.parts.get(p, 0.0),
            "sharePct": (costing.parts.get(p, 0.0) / costing.total * 100.0)
            if costing.total
            else 0.0,
        }
        for p in PARTS
    ]
    return result(
        summary={
            "currency": rates.currency,
            "tenderBase": costing.total,
            "superstructureSharePct": rows[0]["sharePct"],
        },
        tables=[
            table(
                f"Tender breakdown by building part ({rates.currency})",
                [("part", "Building part"), ("amount", "Amount"), ("sharePct", "Share", "%")],
                rows,
            )
        ],
        notes=["Partitions bill items using element-kind rules from saengine.boq.costing."],
    )


@feature(
    "boqCosting.rateAudit",
    "Rate Audit",
    part="boq",
    fields=[],
    requires_project=True,
)
def rate_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit BOQ items for missing rate definitions, null rates, or unit conversion mismatches."""
    _, _, _, costing = price_project_bill(ctx)
    rows = []
    issues = 0
    for li in costing.lines:
        if li.status != "priced":
            issues += 1
            rows.append(
                {
                    "code": li.code,
                    "description": li.description,
                    "unit": li.unit,
                    "status": li.status,
                }
            )
    return result(
        summary={
            "totalItems": len(costing.lines),
            "pricedItems": len(costing.lines) - issues,
            "auditIssues": issues,
            "allPriced": issues == 0,
        },
        tables=[
            table(
                "Rate coverage audit",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("unit", "Unit"),
                    ("status", "Audit finding"),
                ],
                rows
                or [
                    {
                        "code": "-",
                        "description": "All items priced cleanly",
                        "unit": "-",
                        "status": "priced",
                    }
                ],
            )
        ],
        notes=["Flags unrated items, unmatched descriptions, and incompatible measurement units."],
    )


@feature(
    "boqCosting.costVariance",
    "Cost Variance",
    part="boq",
    fields=[
        number("baselineBudget", "Approved baseline budget (0 = 95% of current)", 0.0, min=0.0)
    ],
    requires_project=True,
)
def cost_variance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare current priced BOQ total against an approved baseline budget by trade group."""
    _, rates, _, costing = price_project_bill(ctx)
    base = values["baselineBudget"] if values["baselineBudget"] > 0 else costing.total * 0.95
    tot = costing.total or 1.0
    rows = []
    for g, amt in costing.groups.items():
        base_g = base * (amt / tot)
        rows.append(
            {
                "group": g,
                "baseline": base_g,
                "current": amt,
                "variance": amt - base_g,
                "varPct": ((amt - base_g) / base_g * 100.0) if base_g else 0.0,
            }
        )
    return result(
        summary={
            "currency": rates.currency,
            "baselineBudget": base,
            "currentCost": costing.total,
            "variance": costing.total - base,
        },
        tables=[
            table(
                f"Budget variance by trade ({rates.currency})",
                [
                    ("group", "Trade"),
                    ("baseline", "Baseline"),
                    ("current", "Current"),
                    ("variance", "Variance"),
                    ("varPct", "Var", "%"),
                ],
                rows,
            )
        ],
        notes=["Positive variance indicates cost overrun relative to baseline."],
    )
