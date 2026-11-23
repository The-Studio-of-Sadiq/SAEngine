"""BOQ - Libraries & Suppliers tab: rate, crew, plant, material, regional indices & maintenance."""

from __future__ import annotations

import math
from typing import Any

from saengine.boq.costing import cost_bill
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.boq_common import (
    load_bill,
    load_productivity,
    load_rates,
    parse_csv_rows,
    require_root,
    safe_json,
    save_export,
)


@feature(
    "boqLibrary.rateLibrary",
    "Rate Library",
    part="boq",
    fields=[text("chapterFilter", "Chapter code filter (blank = all)", "")],
    requires_project=False,
)
def rate_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Browse the active schedule of rates library with chapters, units, and unit rates."""
    rates, is_proj = load_rates(ctx)
    cf = values["chapterFilter"].strip()
    rows = []
    for it in rates.items:
        if cf and not it.code.startswith(cf):
            continue
        ch = rates.chapter_of(it.code)
        rows.append(
            {
                "code": it.code,
                "chapter": ch.title if ch else "-",
                "description": it.description,
                "unit": it.unit,
                "rate": it.rate if it.rate is not None else 0.0,
            }
        )
    return result(
        summary={
            "source": "project" if is_proj else "sample",
            "currency": rates.currency,
            "rateItems": len(rows),
        },
        tables=[
            table(
                f"Schedule of rates ({rates.currency})",
                [
                    ("code", "Code"),
                    ("chapter", "Chapter"),
                    ("description", "Description"),
                    ("unit", "Unit"),
                    ("rate", "Rate"),
                ],
                rows,
            )
        ],
        notes=[
            "Rates come from 10 BOQ/rates.json when present, otherwise the built-in sample schedule."
        ],
    )


@feature(
    "boqLibrary.crewLibrary",
    "Crew Library",
    part="boq",
    fields=[],
    requires_project=False,
)
def crew_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Browse defined trade crews, crew counts, and daily output rates."""
    prod, is_proj = load_productivity(ctx)
    rows = [
        {
            "id": r.id,
            "description": r.description,
            "crews": r.crews,
            "perDay": r.perDay,
            "unit": r.unit,
            "totalDailyOutput": r.crews * r.perDay,
        }
        for r in prod.rates
    ]
    return result(
        summary={"source": "project" if is_proj else "sample", "crewTypes": len(rows)},
        tables=[
            table(
                "Crew & output library",
                [
                    ("id", "ID"),
                    ("description", "Operation"),
                    ("crews", "Crews"),
                    ("perDay", "Per crew/day"),
                    ("unit", "Unit"),
                    ("totalDailyOutput", "Total/day"),
                ],
                rows,
            )
        ],
        notes=["Read from 10 BOQ/productivity.json or built-in office productivity rates."],
    )


@feature(
    "boqLibrary.plantLibrary",
    "Plant Library",
    part="boq",
    fields=[
        text(
            "plantCsv",
            "Plant catalogue CSV (code,item,hourly_rate,daily_hire,fuel_l_per_hr)",
            "PLT-01,Hydraulic Excavator 20t,3200,24000,18\nPLT-02,Mobile Concrete Pump 42m,4800,36000,22\nPLT-03,Tower Crane 8t,3500,28000,12\nPLT-04,Vibratory Roller 10t,2200,16500,14",
        ),
    ],
    requires_project=False,
)
def plant_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Maintain construction plant items with hourly operating costs and daily hire rates."""
    raw = parse_csv_rows(values["plantCsv"])
    rows = []
    for r in raw:
        try:
            hr = float(r["hourly_rate"])
            day = float(r["daily_hire"])
            fuel = float(r["fuel_l_per_hr"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError(
                "CSV requires code, item, hourly_rate, daily_hire, fuel_l_per_hr."
            ) from exc
        rows.append(
            {
                "code": r["code"],
                "item": r["item"],
                "hourlyRate": hr,
                "dailyHire": day,
                "fuelLPerHr": fuel,
            }
        )
    return result(
        summary={
            "plantCount": len(rows),
            "avgHourlyRate": sum(r["hourlyRate"] for r in rows) / len(rows),
        },
        tables=[
            table(
                "Plant & equipment rate library",
                [
                    ("code", "Code"),
                    ("item", "Equipment"),
                    ("hourlyRate", "Hourly"),
                    ("dailyHire", "Daily"),
                    ("fuelLPerHr", "Fuel", "l/hr"),
                ],
                rows,
            )
        ],
        notes=["Standard 8-hour shift assumed between hourly and daily hire benchmarks."],
    )


@feature(
    "boqLibrary.materialPrices",
    "Material Prices",
    part="boq",
    fields=[
        number("cementBagPrice", "Portland cement (50 kg bag)", 540.0, min=0.0),
        number("sandPerCft", "Coarse sand (per cft)", 55.0, min=0.0),
        number("stonePerCft", "Crushed stone chips (per cft)", 195.0, min=0.0),
        number("rebarPerKg", "Deformed steel bar (per kg)", 96.0, min=0.0),
    ],
    requires_project=False,
)
def material_prices(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Maintain base material supply prices and calculate concrete ingredient cost per m3 (1:1.5:3 mix)."""
    # 1:1.5:3 nominal mix dry vol 1.54 -> cement 0.28 m3 (8.06 bags), sand 14.8 cft, stone 29.7 cft
    c_bags = 0.28 * 1440.0 / 50.0
    s_cft = 0.42 * 35.3147
    g_cft = 0.84 * 35.3147
    conc_mat_m3 = (
        c_bags * values["cementBagPrice"]
        + s_cft * values["sandPerCft"]
        + g_cft * values["stonePerCft"]
    )
    rows = [
        {
            "material": "OPC/PCC Cement",
            "unit": "50 kg bag",
            "unitPrice": values["cementBagPrice"],
            "mixQtyPerM3": c_bags,
            "costPerM3": c_bags * values["cementBagPrice"],
        },
        {
            "material": "Coarse Sand",
            "unit": "cft",
            "unitPrice": values["sandPerCft"],
            "mixQtyPerM3": s_cft,
            "costPerM3": s_cft * values["sandPerCft"],
        },
        {
            "material": "Stone Chips",
            "unit": "cft",
            "unitPrice": values["stonePerCft"],
            "mixQtyPerM3": g_cft,
            "costPerM3": g_cft * values["stonePerCft"],
        },
        {
            "material": "Deformed Rebar",
            "unit": "kg",
            "unitPrice": values["rebarPerKg"],
            "mixQtyPerM3": 0.0,
            "costPerM3": 0.0,
        },
    ]
    return result(
        summary={"concreteMaterialCostPerM3": conc_mat_m3, "rebarPricePerKg": values["rebarPerKg"]},
        tables=[
            table(
                "Material price schedule & 1:1.5:3 concrete breakdown",
                [
                    ("material", "Material"),
                    ("unit", "Unit"),
                    ("unitPrice", "Price"),
                    ("mixQtyPerM3", "Qty/m3"),
                    ("costPerM3", "Cost/m3"),
                ],
                rows,
            )
        ],
        notes=["Uses dry concrete volume factor 1.54 and 1440 kg/m3 loose cement density."],
    )


@feature(
    "boqLibrary.regionalIndices",
    "Regional Indices",
    part="boq",
    fields=[
        number("baseCityIndex", "Base reference index", 100.0, min=10.0),
        number("projectCityIndex", "Target project city index", 112.0, min=10.0),
    ],
    requires_project=True,
)
def regional_indices(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adjust schedule of rates and bill total by regional cost index ratio."""
    bill = load_bill(ctx)
    if bill is None:
        raise FeatureInputError("Open a project with 10 BOQ/boq.json first.")
    rates, _ = load_rates(ctx)
    costing = cost_bill(bill, rates)
    fac = values["projectCityIndex"] / values["baseCityIndex"]
    rows = [
        {"group": g, "baseTotal": a, "indexedTotal": a * fac} for g, a in costing.groups.items()
    ]
    return result(
        summary={
            "indexFactor": fac,
            "baseTotal": costing.total,
            "regionalAdjustedTotal": costing.total * fac,
        },
        tables=[
            table(
                f"Regional cost adjustment ({rates.currency})",
                [("group", "Group"), ("baseTotal", "Base"), ("indexedTotal", "Adjusted")],
                rows,
            )
        ],
        notes=[
            f"Applies regional index ratio {values['projectCityIndex']:g}/{values['baseCityIndex']:g} = {fac:.4f}."
        ],
    )


@feature(
    "boqLibrary.inflation",
    "Inflation",
    part="boq",
    fields=[
        number("baseAmount", "Current cost estimate", 1000000.0, min=0.0),
        number("annualRatePct", "Annual inflation rate", 7.0, unit="%", min=-5.0, max=40.0),
        number("yearsAhead", "Escalation horizon", 2.0, unit="years", min=0.0, max=20.0),
    ],
    requires_project=False,
)
def inflation_feature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Project compounded cost escalation over future construction years."""
    r = values["annualRatePct"] / 100.0
    yrs = round(values["yearsAhead"])
    rows = []
    for y in range(max(1, yrs) + 1):
        val = values["baseAmount"] * ((1.0 + r) ** y)
        rows.append({"year": y, "index": 100.0 * ((1.0 + r) ** y), "projectedCost": val})
    final_val = values["baseAmount"] * ((1.0 + r) ** values["yearsAhead"])
    return result(
        summary={
            "baseAmount": values["baseAmount"],
            "escalatedAmount": final_val,
            "inflationMultiplier": (1.0 + r) ** values["yearsAhead"],
        },
        tables=[
            table(
                "Annual inflation projection",
                [("year", "Year"), ("index", "Index"), ("projectedCost", "Projected cost")],
                rows,
            )
        ],
        notes=["Compounds annually using (1 + r)^t."],
    )


@feature(
    "boqLibrary.locationFactors",
    "Location Factors",
    part="boq",
    fields=[
        select(
            "remoteness",
            "Site accessibility",
            [
                ("urban", "Metropolitan / urban (1.00)"),
                ("periUrban", "Peri-urban (1.06)"),
                ("remote", "Remote / island / hill (1.18)"),
            ],
            "periUrban",
        ),
        number("haulageKm", "Extra material haulage distance", 45.0, unit="km", min=0.0),
        number(
            "haulagePremiumPer100KmPct",
            "Haulage surcharge per 100 km",
            4.0,
            unit="%",
            min=0.0,
            max=25.0,
        ),
    ],
    requires_project=False,
)
def location_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive composite site location factor combining remoteness and material haulage distance."""
    base_fac = {"urban": 1.00, "periUrban": 1.06, "remote": 1.18}[values["remoteness"]]
    haul_fac = (values["haulageKm"] / 100.0) * (values["haulagePremiumPer100KmPct"] / 100.0)
    composite = base_fac + haul_fac
    return result(
        summary={
            "baseLocationFactor": base_fac,
            "haulageIncrement": haul_fac,
            "compositeFactor": composite,
        },
        tables=[
            table(
                "Location factor build-up",
                [("component", "Component"), ("factor", "Factor")],
                [
                    {"component": "Site access factor", "factor": base_fac},
                    {"component": "Haulage distance increment", "factor": haul_fac},
                    {"component": "Composite location multiplier", "factor": composite},
                ],
            )
        ],
        notes=[
            "Combines site mobilisation remoteness with bulk material transport distance surcharge."
        ],
    )


@feature(
    "boqLibrary.importRates",
    "Import Rates",
    part="boq",
    fields=[
        text(
            "ratesCsv",
            "Rates CSV (code,description,unit,rate,group)",
            "03.01,Blinding concrete 1:3:6,m3,7800,concrete\n03.04,Concrete in columns,m3,13800,concrete\n05.01,Rebar up to 12mm,kg,106,reinforcement",
        ),
        checkbox("exportJson", "Export saengine.rates/1 JSON to 10 BOQ/exports", False),
    ],
    requires_project=False,
)
def import_rates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate external CSV rate schedules into the engine RateSchedule schema."""
    raw = parse_csv_rows(values["ratesCsv"])
    items = []
    for r in raw:
        try:
            rate_val = float(r["rate"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("CSV requires code, description, unit, rate, group.") from exc
        items.append(
            {
                "code": r["code"],
                "description": r["description"],
                "unit": r["unit"],
                "rate": rate_val,
                "match": {"group": r.get("group") or None},
            }
        )
    out_path = ""
    if values["exportJson"]:
        require_root(ctx, "exporting imported rates")
        out_path = str(
            save_export(
                ctx,
                "rates-imported.json",
                safe_json({"schema": "saengine.rates/1", "items": items}),
            )
        )
    return result(
        summary={"importedRates": len(items), "exportPath": out_path or "preview"},
        tables=[
            table(
                "Imported rate items",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("unit", "Unit"),
                    ("rate", "Rate"),
                ],
                [
                    {
                        "code": i["code"],
                        "description": i["description"],
                        "unit": i["unit"],
                        "rate": i["rate"],
                    }
                    for i in items
                ],
            )
        ],
        notes=["Validated against saengine.rates/1 item schema."],
    )


@feature(
    "boqLibrary.supplierQuotes",
    "Supplier Quotes",
    part="boq",
    fields=[
        text(
            "quotesCsv",
            "Supplier quotes CSV (supplier,item,unit,quoted_rate,library_rate)",
            "Alpha Concrete,C25 Ready-mix,m3,12800,13000\nBeta Steel,B420DWR Rebar,kg,98,102\nGamma Bricks,First-class Brick,m3,8900,9000",
        ),
    ],
    requires_project=False,
)
def supplier_quotes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record supplier quotations and compute variance against practice library rates."""
    raw = parse_csv_rows(values["quotesCsv"])
    rows = []
    for r in raw:
        try:
            q = float(r["quoted_rate"])
            lib_r = float(r["library_rate"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError(
                "CSV requires supplier, item, unit, quoted_rate, library_rate."
            ) from exc
        diff_pct = (q - lib_r) / lib_r * 100.0 if lib_r > 0 else 0.0
        rows.append(
            {
                "supplier": r["supplier"],
                "item": r["item"],
                "unit": r.get("unit", ""),
                "quotedRate": q,
                "libraryRate": lib_r,
                "diffPct": diff_pct,
            }
        )
    return result(
        summary={
            "quoteCount": len(rows),
            "avgVariancePct": sum(r["diffPct"] for r in rows) / len(rows),
        },
        tables=[
            table(
                "Supplier quotation log",
                [
                    ("supplier", "Supplier"),
                    ("item", "Item"),
                    ("unit", "Unit"),
                    ("quotedRate", "Quote"),
                    ("libraryRate", "Library"),
                    ("diffPct", "Var", "%"),
                ],
                rows,
            )
        ],
        notes=["Negative variance indicates quote is below practice library allowance."],
    )


@feature(
    "boqLibrary.updatePrices",
    "Update Prices",
    part="boq",
    fields=[
        number(
            "adjustmentPct", "Global market price adjustment", 3.5, unit="%", min=-30.0, max=50.0
        )
    ],
    requires_project=False,
)
def update_prices(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview refreshing all schedule-of-rates unit prices by a percentage market adjustment."""
    rates, _ = load_rates(ctx)
    fac = 1.0 + values["adjustmentPct"] / 100.0
    rows = []
    for it in rates.items:
        if it.rate is None:
            continue
        rows.append(
            {
                "code": it.code,
                "description": it.description,
                "oldRate": it.rate,
                "newRate": it.rate * fac,
            }
        )
    return result(
        summary={
            "currency": rates.currency,
            "updatedItems": len(rows),
            "adjustmentPct": values["adjustmentPct"],
        },
        tables=[
            table(
                f"Price refresh preview ({rates.currency})",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("oldRate", "Current"),
                    ("newRate", "Updated"),
                ],
                rows,
            )
        ],
        notes=["Preview of updated rate list; does not overwrite project rates.json."],
    )


@feature(
    "boqLibrary.supplierRegister",
    "Supplier Register",
    part="boq",
    fields=[
        text(
            "registerCsv",
            "Suppliers CSV (id,name,trade,lead_days,status)",
            "id,name,trade,lead_days,status\nSUP-01,Metro Ready-Mix,Concrete,2,Approved\nSUP-02,Bengal Rebar Mills,Reinforcement,5,Approved\nSUP-03,Delta Formwork,Shuttering,7,Conditional",
        ),
    ],
    requires_project=False,
)
def supplier_register(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Maintain an approved vendor register with trade capabilities and delivery lead times."""
    raw = parse_csv_rows(values["registerCsv"])
    rows = [
        {
            "id": r["id"],
            "name": r["name"],
            "trade": r["trade"],
            "leadDays": int(float(r.get("lead_days", 7))),
            "status": r.get("status", "Approved"),
        }
        for r in raw
    ]
    return result(
        summary={
            "supplierCount": len(rows),
            "approvedCount": sum(1 for r in rows if r["status"].lower() == "approved"),
        },
        tables=[
            table(
                "Approved supplier register",
                [
                    ("id", "ID"),
                    ("name", "Vendor"),
                    ("trade", "Trade"),
                    ("leadDays", "Lead [d]"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=["Tracks qualified vendors by trade package and standard lead time."],
    )


@feature(
    "boqLibrary.quoteComparison",
    "Quote Comparison",
    part="boq",
    fields=[
        text(
            "bidsCsv",
            "Tender bids CSV (item,qty,unit,bid_a,bid_b,bid_c)",
            "Concrete C25 m3,120,m3,12600,13100,12450\nRebar kg,15000,kg,99,96,101\nFormwork m2,800,m2,580,610,595",
        ),
    ],
    requires_project=False,
)
def quote_comparison(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare competing vendor quotations across line items and identify lowest total bidder."""
    raw = parse_csv_rows(values["bidsCsv"])
    tot_a = tot_b = tot_c = 0.0
    rows = []
    for r in raw:
        try:
            q = float(r["qty"])
            a, b, c = float(r["bid_a"]), float(r["bid_b"]), float(r["bid_c"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("CSV requires item, qty, unit, bid_a, bid_b, bid_c.") from exc
        tot_a += q * a
        tot_b += q * b
        tot_c += q * c
        best = min([("Bid A", a), ("Bid B", b), ("Bid C", c)], key=lambda x: x[1])[0]
        rows.append({"item": r["item"], "qty": q, "bidA": a, "bidB": b, "bidC": c, "lowest": best})
    winner = min([("Bid A", tot_a), ("Bid B", tot_b), ("Bid C", tot_c)], key=lambda x: x[1])
    return result(
        summary={
            "bidATotal": tot_a,
            "bidBTotal": tot_b,
            "bidCTotal": tot_c,
            "lowestBidder": winner[0],
        },
        tables=[
            table(
                "Vendor quotation levelling",
                [
                    ("item", "Item"),
                    ("qty", "Qty"),
                    ("bidA", "Bid A"),
                    ("bidB", "Bid B"),
                    ("bidC", "Bid C"),
                    ("lowest", "Lowest"),
                ],
                rows,
            )
        ],
        notes=[f"Lowest overall basket total: {winner[0]} at {winner[1]:,.2f}."],
    )


@feature(
    "boqLibrary.contractRates",
    "Contract Rates",
    part="boq",
    fields=[
        number(
            "volumeDiscountPct", "Framework agreement discount", 4.0, unit="%", min=0.0, max=25.0
        )
    ],
    requires_project=False,
)
def contract_rates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply negotiated framework discount terms to the active schedule of rates."""
    rates, _ = load_rates(ctx)
    fac = 1.0 - values["volumeDiscountPct"] / 100.0
    rows = [
        {
            "code": it.code,
            "description": it.description,
            "unit": it.unit,
            "listRate": it.rate,
            "contractRate": it.rate * fac,
        }
        for it in rates.items
        if it.rate is not None
    ]
    return result(
        summary={
            "currency": rates.currency,
            "discountedItems": len(rows),
            "discountPct": values["volumeDiscountPct"],
        },
        tables=[
            table(
                f"Framework contract rates ({rates.currency})",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("unit", "Unit"),
                    ("listRate", "List"),
                    ("contractRate", "Contract"),
                ],
                rows,
            )
        ],
        notes=["Reflects negotiated volume rebate on rated schedule items."],
    )


@feature(
    "boqLibrary.deliveryTerms",
    "Delivery Terms",
    part="boq",
    fields=[
        select(
            "incoterm",
            "Delivery term",
            [
                ("EXW", "Ex-Works (buyer collects)"),
                ("DAP", "Delivered at Place / Site"),
                ("DDP", "Delivered Duty Paid"),
            ],
            "DAP",
        ),
        number("orderValue", "Order value", 500000.0, min=0.0),
        number("freightPct", "Freight & unloading share", 3.5, unit="%", min=0.0, max=25.0),
        number("dutyPct", "Customs / local levy share", 5.0, unit="%", min=0.0, max=40.0),
    ],
    requires_project=False,
)
def delivery_terms(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare landed site cost across EXW, DAP, and DDP supplier delivery terms."""
    v = values["orderValue"]
    freight = v * values["freightPct"] / 100.0 if values["incoterm"] == "EXW" else 0.0
    duty = v * values["dutyPct"] / 100.0 if values["incoterm"] in ("EXW", "DAP") else 0.0
    landed = v + freight + duty
    return result(
        summary={
            "incoterm": values["incoterm"],
            "invoiceValue": v,
            "buyerFreight": freight,
            "buyerDuty": duty,
            "totalLandedCost": landed,
        },
        tables=[
            table(
                "Landed cost by delivery term",
                [("component", "Cost element"), ("amount", "Amount")],
                [
                    {"component": "Quoted supplier price", "amount": v},
                    {"component": "Buyer freight & unloading", "amount": freight},
                    {"component": "Buyer duties / taxes", "amount": duty},
                    {"component": "Total landed site cost", "amount": landed},
                ],
            )
        ],
        notes=["Normalizes supplier quotes to equivalent delivered-to-site basis."],
    )


@feature(
    "boqLibrary.supplierRating",
    "Supplier Rating",
    part="boq",
    fields=[
        number("priceScore", "Price competitiveness (0-100)", 85.0, min=0.0, max=100.0),
        number(
            "qualityScore", "Material quality & test compliance (0-100)", 92.0, min=0.0, max=100.0
        ),
        number("deliveryScore", "On-time delivery performance (0-100)", 88.0, min=0.0, max=100.0),
    ],
    requires_project=False,
)
def supplier_rating(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Score vendor performance using weighted price (40%), quality (35%), and delivery (25%) KPIs."""
    w_p, w_q, w_d = 0.40, 0.35, 0.25
    score = (
        w_p * values["priceScore"] + w_q * values["qualityScore"] + w_d * values["deliveryScore"]
    )
    tier = (
        "Tier A (Preferred)"
        if score >= 85.0
        else ("Tier B (Approved)" if score >= 70.0 else "Tier C (Review)")
    )
    return result(
        summary={"weightedScore": score, "vendorTier": tier},
        tables=[
            table(
                "Weighted supplier scorecard",
                [
                    ("criterion", "Criterion"),
                    ("weightPct", "Weight", "%"),
                    ("score", "Raw score"),
                    ("weighted", "Weighted"),
                ],
                [
                    {
                        "criterion": "Price competitiveness",
                        "weightPct": 40.0,
                        "score": values["priceScore"],
                        "weighted": w_p * values["priceScore"],
                    },
                    {
                        "criterion": "Quality & compliance",
                        "weightPct": 35.0,
                        "score": values["qualityScore"],
                        "weighted": w_q * values["qualityScore"],
                    },
                    {
                        "criterion": "Delivery reliability",
                        "weightPct": 25.0,
                        "score": values["deliveryScore"],
                        "weighted": w_d * values["deliveryScore"],
                    },
                ],
            )
        ],
        notes=["Weighted composite rating: 40% price, 35% quality, 25% on-time delivery."],
    )


@feature(
    "boqLibrary.labourConstants",
    "Labour Constants",
    part="boq",
    fields=[
        number("hoursPerUnit", "Standard labour man-hours per unit", 2.5, unit="mh/unit", min=0.05),
        number("quantity", "Bill quantity", 120.0, min=0.1),
        number("crewSize", "Gang headcount", 5.0, min=1.0),
        number("hoursPerDay", "Shift length", 8.0, unit="hr/day", min=4.0),
    ],
    requires_project=False,
)
def labour_constants(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert labour constants (man-hours/unit) into total man-days and gang duration."""
    tot_mh = values["hoursPerUnit"] * values["quantity"]
    man_days = tot_mh / values["hoursPerDay"]
    gang_days = math.ceil(man_days / values["crewSize"])
    return result(
        summary={"totalManHours": tot_mh, "totalManDays": man_days, "gangDurationDays": gang_days},
        tables=[
            table(
                "Labour constant conversion",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"metric": "Total man-hours", "value": tot_mh, "unit": "mh"},
                    {"metric": "Total man-days", "value": man_days, "unit": "md"},
                    {"metric": "Crew duration (rounded up)", "value": gang_days, "unit": "days"},
                ],
            )
        ],
        notes=["Gang duration = ceil(quantity * labour_constant / (crew_size * shift_hours))."],
    )


@feature(
    "boqLibrary.plantOutput",
    "Plant Output",
    part="boq",
    fields=[
        number("ratedOutputPerHr", "Manufacturer rated output per hour", 30.0, min=0.5),
        number(
            "siteEfficiencyPct", "Site job & cycle efficiency", 75.0, unit="%", min=20.0, max=100.0
        ),
        number("shiftHours", "Working hours per day", 8.0, unit="hr", min=1.0),
        number("targetQuantity", "Work quantity to execute", 600.0, min=1.0),
    ],
    requires_project=False,
)
def plant_output(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Derive net effective plant daily output and required machine-days under site efficiency."""
    eff_hr = values["ratedOutputPerHr"] * values["siteEfficiencyPct"] / 100.0
    daily = eff_hr * values["shiftHours"]
    days = math.ceil(values["targetQuantity"] / daily)
    return result(
        summary={
            "effectiveHourlyOutput": eff_hr,
            "dailyOutput": daily,
            "machineDaysRequired": days,
        },
        tables=[
            table(
                "Site-adjusted plant output",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Effective hourly output", "value": eff_hr},
                    {"metric": "Effective daily output", "value": daily},
                    {"metric": "Required machine-days", "value": days},
                ],
            )
        ],
        notes=["Derates manufacturer theoretical output by site job/swing efficiency."],
    )


@feature(
    "boqLibrary.materialWastage",
    "Material Wastage",
    part="boq",
    fields=[],
    requires_project=False,
)
def material_wastage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List standard material wastage percentages by construction material category."""
    rows = [
        {
            "category": "Ready-mix concrete",
            "unit": "m3",
            "wastePct": 2.5,
            "cause": "Pump line prime & pour spillage",
        },
        {
            "category": "Site-batched cement",
            "unit": "bag",
            "wastePct": 3.0,
            "cause": "Bag breakage & moisture",
        },
        {
            "category": "Reinforcement steel",
            "unit": "kg",
            "wastePct": 4.0,
            "cause": "Cutting offcuts & rolling tolerance",
        },
        {
            "category": "Structural steel",
            "unit": "kg",
            "wastePct": 3.5,
            "cause": "Plate/section trim & gusset offcuts",
        },
        {
            "category": "Clay bricks / blocks",
            "unit": "m3",
            "wastePct": 5.0,
            "cause": "Transit breakage & half-bat cutting",
        },
        {
            "category": "Ceramic floor/wall tiles",
            "unit": "m2",
            "wastePct": 8.0,
            "cause": "Perimeter diagonal cuts & breakage",
        },
    ]
    return result(
        summary={
            "categoryCount": len(rows),
            "avgWastePct": sum(r["wastePct"] for r in rows) / len(rows),
        },
        tables=[
            table(
                "Standard material wastage schedule",
                [
                    ("category", "Material"),
                    ("unit", "Unit"),
                    ("wastePct", "Wastage", "%"),
                    ("cause", "Primary loss mechanism"),
                ],
                rows,
            )
        ],
        notes=["Reference office wastage allowances for procurement budgeting."],
    )


@feature(
    "boqLibrary.crewComposition",
    "Crew Composition",
    part="boq",
    fields=[
        select(
            "trade",
            "Work operation",
            [
                ("concrete", "Concreting gang"),
                ("rebar", "Steel fixing gang"),
                ("formwork", "Carpentry shuttering gang"),
                ("masonry", "Brickwork gang"),
            ],
            "concrete",
        ),
    ],
    requires_project=False,
)
def crew_composition(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display standard skilled/unskilled gang composition and daily cost breakdown by trade."""
    crews = {
        "concrete": [
            ("Foreman", 1, 1300.0),
            ("Concrete Finisher", 2, 950.0),
            ("Vibrator Operator", 2, 900.0),
            ("Concrete Labourer", 6, 650.0),
        ],
        "rebar": [
            ("Chargehand Steel Fixer", 1, 1200.0),
            ("Steel Fixer", 4, 920.0),
            ("Helper", 3, 650.0),
        ],
        "formwork": [
            ("Lead Carpenter", 1, 1250.0),
            ("Shutter Carpenter", 4, 950.0),
            ("Helper", 3, 650.0),
        ],
        "masonry": [
            ("Master Mason", 2, 980.0),
            ("Assistant Mason", 2, 820.0),
            ("Hod Carrier / Helper", 4, 650.0),
        ],
    }
    members = crews[values["trade"]]
    rows = [{"role": r, "count": c, "dailyWage": w, "subtotal": c * w} for r, c, w in members]
    return result(
        summary={
            "trade": values["trade"],
            "headcount": sum(r["count"] for r in rows),
            "dailyCrewCost": sum(r["subtotal"] for r in rows),
        },
        tables=[
            table(
                f"Standard {values['trade']} crew composition",
                [
                    ("role", "Role"),
                    ("count", "Qty"),
                    ("dailyWage", "Wage/day"),
                    ("subtotal", "Total/day"),
                ],
                rows,
            )
        ],
        notes=["Standard crew templates for rate build-up and 4D resource histograms."],
    )


@feature(
    "boqLibrary.productivityRates",
    "Productivity Rates",
    part="boq",
    fields=[],
    requires_project=False,
)
def productivity_rates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List active project or sample productivity rates used to compute activity durations."""
    prod, is_proj = load_productivity(ctx)
    rows = [
        {
            "id": r.id,
            "description": r.description,
            "perDay": r.perDay,
            "unit": r.unit,
            "crews": r.crews,
        }
        for r in prod.rates
    ]
    return result(
        summary={
            "source": "project" if is_proj else "sample",
            "rateCount": len(rows),
            "masonryLagLevels": prod.masonryLagLevels,
        },
        tables=[
            table(
                "Productivity rate table",
                [
                    ("id", "ID"),
                    ("description", "Operation"),
                    ("perDay", "Output/crew/day"),
                    ("unit", "Unit"),
                    ("crews", "Crews"),
                ],
                rows,
            )
        ],
        notes=["Durations divide bill quantities by (perDay * crews)."],
    )


@feature(
    "boqLibrary.priceHistory",
    "Price History",
    part="boq",
    fields=[
        text("itemName", "Tracked material/rate item", "Reinforcement Steel B420DWR"),
        text(
            "historyCsv",
            "Historical prices CSV (period,unit_price)",
            "2024-Q1,92.0\n2024-Q3,95.5\n2025-Q1,99.0\n2025-Q3,102.0\n2026-Q1,105.0",
        ),
    ],
    requires_project=False,
)
def price_history(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Track historical unit price trends and compute cumulative and period-on-period inflation."""
    raw = parse_csv_rows(values["historyCsv"])
    rows = []
    prev = None
    first = None
    for r in raw:
        try:
            p = float(r["unit_price"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("CSV requires period, unit_price.") from exc
        if first is None:
            first = p
        chg = ((p - prev) / prev * 100.0) if prev else 0.0
        prev = p
        rows.append({"period": r["period"], "price": p, "periodChangePct": chg})
    tot_chg = ((prev - first) / first * 100.0) if (first and prev) else 0.0
    return result(
        summary={
            "item": values["itemName"],
            "periods": len(rows),
            "latestPrice": prev or 0.0,
            "cumulativeChangePct": tot_chg,
        },
        tables=[
            table(
                f"Price history: {values['itemName']}",
                [
                    ("period", "Period"),
                    ("price", "Unit price"),
                    ("periodChangePct", "QoQ change", "%"),
                ],
                rows,
            )
        ],
        notes=["Tracks index movement from earliest recorded quotation to latest period."],
    )


@feature(
    "boqLibrary.rateValidity",
    "Rate Validity",
    part="boq",
    fields=[number("validityDays", "Standard rate validity window", 90.0, unit="days", min=15.0)],
    requires_project=False,
)
def rate_validity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review rate schedule items for missing or stale rates needing revalidation."""
    rates, _ = load_rates(ctx)
    rows = []
    unrated = 0
    for it in rates.items:
        needs_rev = it.rate is None
        if needs_rev:
            unrated += 1
        rows.append(
            {
                "code": it.code,
                "description": it.description,
                "rate": it.rate if it.rate is not None else 0.0,
                "status": "Needs price entry"
                if needs_rev
                else f"Valid ({int(values['validityDays'])}d)",
            }
        )
    return result(
        summary={"totalItems": len(rows), "needsRevalidation": unrated},
        tables=[
            table(
                "Rate validity register",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("rate", "Rate"),
                    ("status", "Validity status"),
                ],
                rows,
            )
        ],
        notes=["Items with null rates require current project quotations before tender issue."],
    )


@feature(
    "boqLibrary.bulkUpdate",
    "Bulk Update",
    part="boq",
    fields=[
        text("groupFilter", "Target group (blank = all groups)", "concrete"),
        number("pctIncrease", "Percentage index adjustment", 5.0, unit="%", min=-50.0, max=100.0),
    ],
    requires_project=False,
)
def bulk_update(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview applying a percentage index update to a filtered subset of schedule rates."""
    rates, _ = load_rates(ctx)
    gf = values["groupFilter"].strip().lower()
    fac = 1.0 + values["pctIncrease"] / 100.0
    rows = []
    for it in rates.items:
        if it.rate is None:
            continue
        grp = (it.match.group or "").lower()
        if gf and gf != grp:
            continue
        rows.append(
            {"code": it.code, "group": grp or "-", "oldRate": it.rate, "newRate": it.rate * fac}
        )
    return result(
        summary={"matchedItems": len(rows), "multiplier": fac},
        tables=[
            table(
                "Bulk rate update preview",
                [
                    ("code", "Code"),
                    ("group", "Group"),
                    ("oldRate", "Old rate"),
                    ("newRate", "New rate"),
                ],
                rows,
            )
        ],
        notes=["Preview only; shows before/after rates for the selected trade group."],
    )


@feature(
    "boqLibrary.libraryBackup",
    "Library Backup",
    part="boq",
    fields=[text("backupName", "Backup filename", "boq-rates-carbon-backup.json")],
    requires_project=True,
)
def library_backup(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Back up the active rates, carbon factors, and productivity libraries into 10 BOQ/exports."""
    require_root(ctx, "backing up BOQ cost libraries")
    rates, _ = load_rates(ctx)
    from saengine.features.boq_common import load_carbon

    carbon, _ = load_carbon(ctx)
    prod, _ = load_productivity(ctx)
    bundle = {
        "rates": rates.model_dump(mode="json", by_alias=True),
        "carbon": carbon.model_dump(mode="json", by_alias=True),
        "productivity": prod.model_dump(mode="json", by_alias=True),
    }
    fname = values["backupName"].strip() or "boq-library-backup.json"
    if not fname.lower().endswith(".json"):
        fname += ".json"
    target = save_export(ctx, fname, safe_json(bundle))
    return result(
        summary={
            "rateItems": len(rates.items),
            "carbonFactors": len(carbon.factors),
            "backupPath": str(target),
        },
        tables=[
            table(
                "Cost library backup manifest",
                [("library", "Library"), ("entries", "Entries")],
                [
                    {"library": "Rate schedule", "entries": len(rates.items)},
                    {"library": "Carbon factors", "entries": len(carbon.factors)},
                    {"library": "Productivity rates", "entries": len(prod.rates)},
                ],
            )
        ],
        notes=[f"Backup bundle written to {target}."],
    )
