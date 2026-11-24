"""BOQ - Reports & Exports tab: elemental BOQ, carbon reports, Excel/IFC/HTML exports & dashboards."""

from __future__ import annotations

import hashlib
from typing import Any

from saengine.boq.workbook import write_boq_xlsx
from saengine.features import (
    FeatureContext,
    checkbox,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.boq_common import (
    load_carbon,
    parse_csv_rows,
    price_project_bill,
    require_bill,
    require_root,
    safe_json,
    save_export,
)


@feature(
    "boqReports.elementalBoq",
    "Elemental BOQ",
    part="boq",
    fields=[],
    requires_project=True,
)
def elemental_boq(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Publish an elemental bill of quantities partitioned by building element part."""
    _, rates, _, costing = price_project_bill(ctx)
    rows = [
        {
            "part": p,
            "amount": amt,
            "sharePct": amt / costing.total * 100.0 if costing.total else 0.0,
        }
        for p, amt in costing.parts.items()
    ]
    return result(
        summary={
            "currency": rates.currency,
            "elementalParts": len(rows),
            "totalCost": costing.total,
        },
        tables=[
            table(
                f"Elemental BOQ summary ({rates.currency})",
                [("part", "Building part"), ("amount", "Cost"), ("sharePct", "Share", "%")],
                rows,
            )
        ],
        notes=["Categorises items into Substructure, Superstructure, Architecture, and MEP."],
    )


@feature(
    "boqReports.tradeSummary",
    "Trade Summary",
    part="boq",
    fields=[],
    requires_project=True,
)
def trade_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise priced BOQ totals and line counts by trade package."""
    _, rates, _, costing = price_project_bill(ctx)
    counts: dict[str, int] = {}
    for li in costing.lines:
        counts[li.group] = counts.get(li.group, 0) + 1
    rows = [
        {"group": g, "itemCount": counts.get(g, 0), "amount": amt}
        for g, amt in costing.groups.items()
    ]
    return result(
        summary={"currency": rates.currency, "tradeCount": len(rows), "grandTotal": costing.total},
        tables=[
            table(
                f"Trade package summary ({rates.currency})",
                [("group", "Trade"), ("itemCount", "Items"), ("amount", "Total cost")],
                rows,
            )
        ],
        notes=["Aggregates all priced BOQ items by canonical trade group."],
    )


@feature(
    "boqReports.costBreakdown",
    "Cost Breakdown",
    part="boq",
    fields=[],
    requires_project=True,
)
def cost_breakdown(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Break project cost down by BOQ line item, element breakdown, and matched rate source."""
    _, rates, _, costing = price_project_bill(ctx)
    rows = [
        {
            "code": li.code,
            "description": li.description,
            "qty": li.quantity,
            "unit": li.unit,
            "rate": li.rate or 0.0,
            "amount": li.amount or 0.0,
        }
        for li in costing.lines
        if li.amount
    ]
    return result(
        summary={"currency": rates.currency, "pricedLines": len(rows), "totalCost": costing.total},
        tables=[
            table(
                f"Itemised cost breakdown ({rates.currency})",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("qty", "Qty"),
                    ("unit", "Unit"),
                    ("rate", "Rate"),
                    ("amount", "Amount"),
                ],
                rows[:50],
            )
        ],
        notes=["Shows unit conversion-adjusted extended amounts for every priced bill line."],
    )


@feature(
    "boqReports.carbonReport",
    "Carbon Report",
    part="boq",
    fields=[checkbox("exportCsv", "Export carbon-report.csv to 10 BOQ/exports", False)],
    requires_project=True,
)
def carbon_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report embodied carbon emissions (kg CO2e) by material and building part."""
    _, _, _, costing = price_project_bill(ctx)
    rows = [
        {
            "material": c.material,
            "massKg": c.mass,
            "factorKgCo2PerKg": c.factor if c.factor is not None else 0.0,
            "carbonKgCo2e": c.carbon if c.carbon is not None else 0.0,
            "source": c.source,
        }
        for c in costing.carbon
    ]
    out_path = ""
    if values["exportCsv"]:
        lines = ["material,mass_kg,factor_kg_co2_per_kg,carbon_kg_co2e"] + [
            f'"{r["material"]}",{r["massKg"]:.2f},{r["factorKgCo2PerKg"]:.4f},{r["carbonKgCo2e"]:.2f}'
            for r in rows
        ]
        out_path = str(save_export(ctx, "carbon-report.csv", "\n".join(lines) + "\n"))
    return result(
        summary={
            "totalCarbonKgCo2e": costing.carbonTotal,
            "totalCarbonTonnesCo2e": costing.carbonTotal / 1000.0,
            "exportPath": out_path or "preview",
        },
        tables=[
            table(
                "Embodied carbon report",
                [
                    ("material", "Material"),
                    ("massKg", "Mass", "kg"),
                    ("factorKgCo2PerKg", "Factor", "kgCO2e/kg"),
                    ("carbonKgCo2e", "Embodied carbon", "kgCO2e"),
                ],
                rows,
            )
        ],
        notes=[
            "Computed via saengine.boq.costing.carbon_of using cement, steel, and rebar factors."
        ],
    )


@feature(
    "boqReports.embodiedCarbon",
    "Embodied Carbon",
    part="boq",
    fields=[
        number("cementKg", "Cement mass", 25000.0, unit="kg", min=0.0),
        number("rebarKg", "Reinforcement steel mass", 12000.0, unit="kg", min=0.0),
        number("structSteelKg", "Structural steel mass", 4000.0, unit="kg", min=0.0),
        number("brickM3", "Brickwork masonry volume", 35.0, unit="m3", min=0.0),
    ],
    requires_project=False,
)
def embodied_carbon(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate embodied carbon (kg CO2e) from material quantities and editable carbon factors."""
    factors, _ = load_carbon(ctx)
    f_map = {f.id: (f.factor or 0.0) for f in factors.factors}
    c_cem = values["cementKg"] * f_map.get("cement", 0.588)
    c_reb = values["rebarKg"] * f_map.get("rebar", 1.92)
    c_stl = values["structSteelKg"] * f_map.get("steel", 1.92)
    c_brk = values["brickM3"] * 1900.0 * (f_map.get("brick") or 0.24)
    tot = c_cem + c_reb + c_stl + c_brk
    rows = [
        {"material": "Cement", "massKg": values["cementKg"], "carbonKg": c_cem},
        {"material": "Reinforcing steel", "massKg": values["rebarKg"], "carbonKg": c_reb},
        {"material": "Structural steel", "massKg": values["structSteelKg"], "carbonKg": c_stl},
        {
            "material": "Brickwork (1900 kg/m3)",
            "massKg": values["brickM3"] * 1900.0,
            "carbonKg": c_brk,
        },
    ]
    return result(
        summary={"totalCarbonKgCo2e": tot, "totalCarbonTonnesCo2e": tot / 1000.0},
        tables=[
            table(
                "Embodied carbon breakdown",
                [
                    ("material", "Material"),
                    ("massKg", "Mass", "kg"),
                    ("carbonKg", "Embodied carbon", "kgCO2e"),
                ],
                rows,
            )
        ],
        notes=["Uses active carbon factor schedule for cradle-to-gate A1-A3 emissions."],
    )


@feature(
    "boqReports.offsetPlan",
    "Offset Plan",
    part="boq",
    fields=[
        number(
            "reductionTargetPct",
            "Design/material carbon reduction target",
            20.0,
            unit="%",
            min=0.0,
            max=80.0,
        ),
        number("offsetPricePerTonne", "Verified carbon offset price per tCO2e", 2500.0, min=0.0),
    ],
    requires_project=True,
)
def offset_plan(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Plan residual carbon offsets and abatement targets against the project embodied carbon total."""
    _, _, _, costing = price_project_bill(ctx)
    tot_t = costing.carbonTotal / 1000.0
    abated_t = tot_t * values["reductionTargetPct"] / 100.0
    residual_t = tot_t - abated_t
    offset_cost = residual_t * values["offsetPricePerTonne"]
    return result(
        summary={
            "baselineTonnesCo2e": tot_t,
            "abatedTonnesCo2e": abated_t,
            "residualTonnesCo2e": residual_t,
            "offsetBudget": offset_cost,
        },
        tables=[
            table(
                "Net-zero embodied carbon offset plan",
                [("stage", "Stage"), ("tonnes", "tCO2e"), ("cost", "Offset cost")],
                [
                    {"stage": "Baseline embodied carbon", "tonnes": tot_t, "cost": 0.0},
                    {
                        "stage": f"Material abatement ({values['reductionTargetPct']:g}%)",
                        "tonnes": -abated_t,
                        "cost": 0.0,
                    },
                    {
                        "stage": "Residual offset purchase",
                        "tonnes": residual_t,
                        "cost": offset_cost,
                    },
                ],
            )
        ],
        notes=[
            "Targets low-carbon blended cements and EAF recycled steel before purchasing offsets."
        ],
    )


@feature(
    "boqReports.exportPdf",
    "Export PDF",
    part="boq",
    fields=[text("filename", "Workbook / HTML export name", "boq-report.xlsx")],
    requires_project=True,
)
def export_pdf(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a formatted printable BOQ workbook (.xlsx) and print-ready HTML summary in 10 BOQ/exports."""
    root = require_root(ctx, "exporting printable BOQ report")
    bill, rates, carbon, costing = price_project_bill(ctx)
    xlsx_path = root / "10 BOQ" / "exports" / "boq-printable.xlsx"
    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    write_boq_xlsx(xlsx_path, bill, rates, carbon, title=root.name)
    html_rows = "".join(
        f"<tr><td>{li.code}</td><td>{li.description}</td><td>{li.quantity:.3f}</td><td>{li.unit}</td><td>{li.amount or 0:,.2f}</td></tr>"
        for li in costing.lines
    )
    html = f"<html><body><h1>Bill of Quantities ({rates.currency})</h1><p>Total: {costing.total:,.2f}</p><table border='1'>{html_rows}</table></body></html>"
    html_path = save_export(ctx, "boq-printable.html", html)
    return result(
        summary={
            "currency": rates.currency,
            "totalCost": costing.total,
            "xlsxPath": str(xlsx_path),
            "htmlPath": str(html_path),
        },
        tables=[
            table(
                "Printable export outputs",
                [("format", "Output"), ("path", "File path")],
                [
                    {"format": "Excel workbook", "path": str(xlsx_path)},
                    {"format": "Printable HTML", "path": str(html_path)},
                ],
            )
        ],
        notes=[f"Generated {xlsx_path} and {html_path} (open HTML and print-to-PDF if needed)."],
    )


@feature(
    "boqReports.exportIfcQto",
    "Export IFC QTO",
    part="boq",
    fields=[text("filename", "JSON filename", "ifc-qto.json")],
    requires_project=True,
)
def export_ifc_qto(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export element-level BOQ quantities structured as IFC Quantity Set (Qto_*) JSON records."""
    bill = require_bill(ctx)
    qto_records: list[dict[str, Any]] = []
    for it in bill["items"]:
        grp = str(it.get("group", ""))
        unit = str(it.get("unit", ""))
        prop_name = (
            "NetVolume"
            if unit == "m3"
            else ("NetArea" if unit == "m2" else ("GrossWeight" if unit == "kg" else "Count"))
        )
        for br in it.get("breakdown") or []:
            qto_records.append(
                {
                    "elementId": br.get("element"),
                    "story": br.get("story"),
                    "qtoSet": f"Qto_{str(it.get('kind') or grp).title()}BaseQuantities",
                    "property": prop_name,
                    "value": br.get("quantity"),
                    "unit": unit,
                }
            )
    fname = values["filename"].strip() or "ifc-qto.json"
    if not fname.lower().endswith(".json"):
        fname += ".json"
    target = save_export(
        ctx, fname, safe_json({"schema": "saengine.ifcQto/1", "quantities": qto_records})
    )
    return result(
        summary={"qtoRecordCount": len(qto_records), "exportPath": str(target)},
        tables=[
            table(
                "Sample IFC Qto records",
                [
                    ("elementId", "Element"),
                    ("qtoSet", "Qto Set"),
                    ("property", "Property"),
                    ("value", "Value"),
                    ("unit", "Unit"),
                ],
                qto_records[:30],
            )
        ],
        notes=[f"Exported {len(qto_records)} IFC-aligned quantity records to {target}."],
    )


@feature(
    "boqReports.publishTender",
    "Publish Tender",
    part="boq",
    fields=[text("tenderRef", "Tender package reference", "TND-2026-01")],
    requires_project=True,
)
def publish_tender(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Package the unpriced blank tender BOQ CSV and priced control workbook into 10 BOQ/exports."""
    root = require_root(ctx, "publishing tender BOQ package")
    bill, rates, carbon, costing = price_project_bill(ctx)
    blank_csv = ["code,group,description,quantity,unit,rate,amount"] + [
        f'{it.get("code")},{it.get("group")},"{str(it.get("description", "")).replace('"', '""')}",{it.get("quantity")},{it.get("unit")},,'
        for it in bill["items"]
    ]
    csv_path = save_export(
        ctx, f"{values['tenderRef']}-blank-tender.csv", "\n".join(blank_csv) + "\n"
    )
    xlsx_path = root / "10 BOQ" / "exports" / f"{values['tenderRef']}-priced-control.xlsx"
    write_boq_xlsx(xlsx_path, bill, rates, carbon, title=values["tenderRef"])
    return result(
        summary={
            "tenderRef": values["tenderRef"],
            "itemCount": len(bill["items"]),
            "controlTotal": costing.total,
            "blankCsvPath": str(csv_path),
        },
        tables=[
            table(
                "Published tender package",
                [("artifact", "Artifact"), ("path", "Path")],
                [
                    {"artifact": "Blank tender BOQ (CSV)", "path": str(csv_path)},
                    {"artifact": "Priced engineer control (XLSX)", "path": str(xlsx_path)},
                ],
            )
        ],
        notes=[f"Tender package {values['tenderRef']} published to 10 BOQ/exports."],
    )


@feature(
    "boqReports.costSummaryReport",
    "Cost Summary Report",
    part="boq",
    fields=[],
    requires_project=True,
)
def cost_summary_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Produce a formal executive cost summary with subtotals by trade and building part."""
    _, rates, _, costing = price_project_bill(ctx)
    rows = [
        {
            "section": g.title(),
            "amount": a,
            "sharePct": a / costing.total * 100.0 if costing.total else 0.0,
        }
        for g, a in costing.groups.items()
    ]
    return result(
        summary={
            "currency": rates.currency,
            "directTotal": costing.total,
            "carbonTotalKg": costing.carbonTotal,
        },
        tables=[
            table(
                f"Cost summary report ({rates.currency})",
                [("section", "Trade section"), ("amount", "Amount"), ("sharePct", "Share", "%")],
                rows,
            )
        ],
        notes=["Summarises priced bill sections with percentage cost allocation."],
    )


@feature(
    "boqReports.monthlySpendReport",
    "Monthly Spend Report",
    part="boq",
    fields=[
        number("currentMonth", "Reporting month index", 4.0, min=1.0),
        number("totalMonths", "Project duration", 12.0, min=2.0),
        number("actualSpendPct", "Cumulative actual spend %", 28.0, unit="%", min=0.0, max=150.0),
    ],
    requires_project=True,
)
def monthly_spend_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report planned vs actual spend for the current reporting month against contract budget."""
    _, rates, _, costing = price_project_bill(ctx)
    m, n = values["currentMonth"], values["totalMonths"]
    planned_cum_pct = min(100.0, (m / n) * 100.0)
    planned_cum = costing.total * planned_cum_pct / 100.0
    actual_cum = costing.total * values["actualSpendPct"] / 100.0
    return result(
        summary={
            "currency": rates.currency,
            "plannedCumulative": planned_cum,
            "actualCumulative": actual_cum,
            "spendVariance": actual_cum - planned_cum,
        },
        tables=[
            table(
                f"Month {round(m)} spend report ({rates.currency})",
                [("metric", "Metric"), ("amount", "Amount")],
                [
                    {"metric": "Total contract budget", "amount": costing.total},
                    {
                        "metric": f"Planned cumulative ({planned_cum_pct:.1f}%)",
                        "amount": planned_cum,
                    },
                    {
                        "metric": f"Actual cumulative ({values['actualSpendPct']:g}%)",
                        "amount": actual_cum,
                    },
                    {"metric": "Cumulative variance", "amount": actual_cum - planned_cum},
                ],
            )
        ],
        notes=[
            "Compares linear planned spend trajectory against actual cumulative certified expenditure."
        ],
    )


@feature(
    "boqReports.rateAnalysisReport",
    "Rate Analysis Report",
    part="boq",
    fields=[],
    requires_project=True,
)
def rate_analysis_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Show applied unit rates, conversion factors, and effective bill-unit rates for principal items."""
    _, rates, _, costing = price_project_bill(ctx)
    top_lines = sorted((li for li in costing.lines if li.amount), key=lambda l: -(l.amount or 0.0))[
        :15
    ]
    rows = [
        {
            "code": li.code,
            "description": li.description,
            "billUnit": li.unit,
            "rateCode": li.rateCode,
            "rateUnit": li.rateUnit,
            "conv": li.conversion,
            "rate": li.rate,
            "amount": li.amount,
        }
        for li in top_lines
    ]
    return result(
        summary={"currency": rates.currency, "principalItemsShown": len(rows)},
        tables=[
            table(
                f"Principal item rate analysis ({rates.currency})",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("billUnit", "Bill unit"),
                    ("rateCode", "Rate #"),
                    ("rateUnit", "Rate unit"),
                    ("rate", "Rate"),
                    ("amount", "Amount"),
                ],
                rows,
            )
        ],
        notes=["Displays the top 15 items by total extended value."],
    )


@feature(
    "boqReports.contingencyReport",
    "Contingency Report",
    part="boq",
    fields=[
        number("contingencyPct", "Initial contingency %", 5.0, unit="%", min=0.0, max=30.0),
        number("drawnDownAmount", "Contingency drawn down to date", 65000.0, min=0.0),
    ],
    requires_project=True,
)
def contingency_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report total contingency allowance, current drawdown, and remaining risk reserve."""
    _, rates, _, costing = price_project_bill(ctx)
    initial = costing.total * values["contingencyPct"] / 100.0
    drawn = values["drawnDownAmount"]
    remaining = initial - drawn
    return result(
        summary={
            "currency": rates.currency,
            "initialReserve": initial,
            "drawnDown": drawn,
            "remainingReserve": remaining,
            "drawdownPct": (drawn / initial * 100.0) if initial else 0.0,
        },
        tables=[
            table(
                f"Contingency drawdown status ({rates.currency})",
                [("item", "Line"), ("amount", "Amount")],
                [
                    {
                        "item": f"Initial contingency ({values['contingencyPct']:g}%)",
                        "amount": initial,
                    },
                    {"item": "Committed / drawn down", "amount": drawn},
                    {"item": "Remaining unallocated reserve", "amount": remaining},
                ],
            )
        ],
        notes=["Tracks drawdown of commercial risk reserve against approved variations."],
    )


@feature(
    "boqReports.profitSummary",
    "Profit Summary",
    part="boq",
    fields=[
        number("overheadPct", "Site & HO overheads %", 10.0, unit="%", min=0.0, max=40.0),
        number("marginPct", "Target net margin %", 8.0, unit="%", min=0.0, max=40.0),
        number("riskPct", "Risk allowance %", 2.0, unit="%", min=0.0, max=20.0),
    ],
    requires_project=True,
)
def profit_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise net contractor margin after direct cost, overheads, and risk allowances."""
    _, rates, _, costing = price_project_bill(ctx)
    direct = costing.total
    oh = direct * values["overheadPct"] / 100.0
    risk = direct * values["riskPct"] / 100.0
    cost_base = direct + oh + risk
    profit = cost_base * values["marginPct"] / 100.0
    sell_price = cost_base + profit
    return result(
        summary={
            "currency": rates.currency,
            "directCost": direct,
            "overheadsAndRisk": oh + risk,
            "netProfit": profit,
            "sellingPrice": sell_price,
        },
        tables=[
            table(
                f"Margin & profit summary ({rates.currency})",
                [("component", "Component"), ("amount", "Amount")],
                [
                    {"component": "Direct measured cost", "amount": direct},
                    {"component": "Overheads", "amount": oh},
                    {"component": "Risk allowance", "amount": risk},
                    {"component": "Net profit margin", "amount": profit},
                    {"component": "Tender selling total", "amount": sell_price},
                ],
            )
        ],
        notes=["Net profit computed on full cost base (direct + overheads + risk)."],
    )


@feature(
    "boqReports.clientSummary",
    "Client Summary",
    part="boq",
    fields=[],
    requires_project=True,
)
def client_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a concise one-page executive cost summary tailored for the client."""
    _, rates, _, costing = price_project_bill(ctx)
    rows = [
        {
            "part": p,
            "amount": amt,
            "sharePct": amt / costing.total * 100.0 if costing.total else 0.0,
        }
        for p, amt in costing.parts.items()
    ]
    return result(
        summary={
            "currency": rates.currency,
            "estimatedConstructionCost": costing.total,
            "embodiedCarbonTonnes": costing.carbonTotal / 1000.0,
        },
        tables=[
            table(
                f"Client executive cost summary ({rates.currency})",
                [
                    ("part", "Building element"),
                    ("amount", "Estimated cost"),
                    ("sharePct", "Share", "%"),
                ],
                rows,
            )
        ],
        notes=["High-level client presentation omitting internal rate build-up details."],
    )


@feature(
    "boqReports.executiveDashboard",
    "Executive Dashboard",
    part="boq",
    fields=[],
    requires_project=True,
)
def executive_dashboard(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Present key project cost, quantity, rate coverage, and embodied carbon KPIs on one page."""
    bill, rates, _, costing = price_project_bill(ctx)
    priced = sum(1 for li in costing.lines if li.status == "priced")
    conc = sum(
        float(it.get("quantity", 0.0)) for it in bill["items"] if it.get("group") == "concrete"
    )
    rebar = sum(
        float(it.get("quantity", 0.0)) for it in bill["items"] if it.get("group") == "reinforcement"
    )
    rows = [
        {"kpi": f"Total priced BOQ ({rates.currency})", "value": f"{costing.total:,.2f}"},
        {"kpi": "Priced item coverage", "value": f"{priced} / {len(costing.lines)}"},
        {"kpi": "Total concrete volume", "value": f"{conc:.2f} m3"},
        {"kpi": "Total reinforcement mass", "value": f"{rebar:,.1f} kg"},
        {"kpi": "Total embodied carbon", "value": f"{costing.carbonTotal / 1000.0:.2f} tCO2e"},
    ]
    return result(
        summary={
            "currency": rates.currency,
            "totalCost": costing.total,
            "concreteM3": conc,
            "rebarKg": rebar,
            "carbonTonnes": costing.carbonTotal / 1000.0,
        },
        tables=[
            table("Executive BOQ dashboard KPIs", [("kpi", "Indicator"), ("value", "Value")], rows)
        ],
        notes=["Consolidated snapshot of cost, physical quantities, and sustainability."],
    )


@feature(
    "boqReports.tenderComparison",
    "Tender Comparison",
    part="boq",
    fields=[
        number("bidder1Factor", "Bidder A vs estimate ratio", 0.96, min=0.5, max=2.0),
        number("bidder2Factor", "Bidder B vs estimate ratio", 1.03, min=0.5, max=2.0),
        number("bidder3Factor", "Bidder C vs estimate ratio", 1.11, min=0.5, max=2.0),
    ],
    requires_project=True,
)
def tender_comparison(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare competing contractor tender returns against each other and the engineer's estimate."""
    _, rates, _, costing = price_project_bill(ctx)
    est = costing.total
    rows = [
        {
            "group": g,
            "estimate": a,
            "bidderA": a * values["bidder1Factor"],
            "bidderB": a * values["bidder2Factor"],
            "bidderC": a * values["bidder3Factor"],
        }
        for g, a in costing.groups.items()
    ]
    return result(
        summary={
            "currency": rates.currency,
            "estimate": est,
            "bidderATotal": est * values["bidder1Factor"],
            "bidderBTotal": est * values["bidder2Factor"],
            "bidderCTotal": est * values["bidder3Factor"],
        },
        tables=[
            table(
                f"Tender return comparison ({rates.currency})",
                [
                    ("group", "Trade"),
                    ("estimate", "Estimate"),
                    ("bidderA", "Bidder A"),
                    ("bidderB", "Bidder B"),
                    ("bidderC", "Bidder C"),
                ],
                rows,
            )
        ],
        notes=["Highlights spread across trades to spot front-loading or pricing anomalies."],
    )


@feature(
    "boqReports.valueEngineeringReport",
    "Value Engineering Report",
    part="boq",
    fields=[
        text(
            "veCsv",
            "VE options CSV (option,trade,cost_saving,carbon_saving_kg)",
            "option,trade,cost_saving,carbon_saving_kg\nVE-01 Post-tensioned flat slab,concrete,185000,4200\nVE-02 Blended slag cement mix,materials,65000,9800\nVE-03 Standardised column sizes,formwork,95000,600",
        ),
    ],
    requires_project=True,
)
def value_engineering_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Document value engineering proposals with net cost savings and embodied carbon reductions."""
    _, rates, _, costing = price_project_bill(ctx)
    raw = parse_csv_rows(values["veCsv"])
    rows = []
    tot_save = tot_carb = 0.0
    for r in raw:
        csave = float(r["cost_saving"])
        ksave = float(r["carbon_saving_kg"])
        tot_save += csave
        tot_carb += ksave
        rows.append(
            {
                "option": r["option"],
                "trade": r["trade"],
                "costSaving": csave,
                "carbonSavingKg": ksave,
            }
        )
    return result(
        summary={
            "currency": rates.currency,
            "optionsCount": len(rows),
            "totalCostSaving": tot_save,
            "savingPctOfBill": (tot_save / costing.total * 100.0) if costing.total else 0.0,
            "carbonSavedKg": tot_carb,
        },
        tables=[
            table(
                f"Value engineering options ({rates.currency})",
                [
                    ("option", "VE proposal"),
                    ("trade", "Trade"),
                    ("costSaving", "Cost saving"),
                    ("carbonSavingKg", "Carbon saved", "kgCO2e"),
                ],
                rows,
            )
        ],
        notes=["Evaluates cost and embodied carbon benefits side by side."],
    )


@feature(
    "boqReports.benchmarkReport",
    "Benchmark Report",
    part="boq",
    fields=[
        number("gfaM2", "Gross floor area", 1200.0, unit="m2", min=10.0),
        number("marketBenchmarkPerM2", "Market norm cost per m2", 28000.0, min=100.0),
    ],
    requires_project=True,
)
def benchmark_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Benchmark project structural cost per m2 and material intensities against market norms."""
    bill, rates, _, costing = price_project_bill(ctx)
    gfa = values["gfaM2"]
    proj_per_m2 = costing.total / gfa
    conc = sum(
        float(it.get("quantity", 0.0)) for it in bill["items"] if it.get("group") == "concrete"
    )
    rebar = sum(
        float(it.get("quantity", 0.0)) for it in bill["items"] if it.get("group") == "reinforcement"
    )
    rows = [
        {
            "metric": f"Cost per m2 ({rates.currency}/m2)",
            "project": proj_per_m2,
            "benchmark": values["marketBenchmarkPerM2"],
        },
        {"metric": "Concrete intensity (m3/m2)", "project": conc / gfa, "benchmark": 0.38},
        {"metric": "Rebar intensity (kg/m2)", "project": rebar / gfa, "benchmark": 52.0},
    ]
    return result(
        summary={
            "currency": rates.currency,
            "projectCostPerM2": proj_per_m2,
            "benchmarkPerM2": values["marketBenchmarkPerM2"],
            "variancePct": (proj_per_m2 - values["marketBenchmarkPerM2"])
            / values["marketBenchmarkPerM2"]
            * 100.0,
        },
        tables=[
            table(
                "Project cost & quantity benchmarking",
                [("metric", "Metric"), ("project", "Project"), ("benchmark", "Benchmark")],
                rows,
            )
        ],
        notes=[
            "Compares cost/m2, concrete m3/m2, and rebar kg/m2 against reference building norms."
        ],
    )


@feature(
    "boqReports.reportBinder",
    "Report Binder",
    part="boq",
    fields=[text("binderTitle", "Binder title", "Structural & Commercial BOQ Binder")],
    requires_project=True,
)
def report_binder(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble cost summary, carbon ledger, and notes into a unified Markdown binder in 10 BOQ/exports."""
    bill, rates, _, costing = price_project_bill(ctx)
    sections = [
        f"# {values['binderTitle']}",
        f"Currency: {rates.currency} | Total: {costing.total:,.2f} | Carbon: {costing.carbonTotal:,.1f} kg CO2e",
        "## Trade Summary",
        *[f"- {g}: {a:,.2f} {rates.currency}" for g, a in costing.groups.items()],
        "## Measurement Notes",
        *[f"- {n}" for n in (bill.get("notes") or [])[:5]],
    ]
    target = save_export(ctx, "boq-report-binder.md", "\n".join(sections) + "\n")
    return result(
        summary={"sectionsIncluded": 3, "binderPath": str(target)},
        tables=[
            table(
                "Binder sections",
                [("section", "Section"), ("entries", "Items")],
                [
                    {"section": "Trade summary", "entries": len(costing.groups)},
                    {"section": "Carbon factors", "entries": len(costing.carbon)},
                    {"section": "Notes", "entries": len(bill.get("notes") or [])},
                ],
            )
        ],
        notes=[f"Compiled report binder saved to {target}."],
    )


@feature(
    "boqReports.reportIndex",
    "Report Index",
    part="boq",
    fields=[],
    requires_project=True,
)
def report_index(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a structured table of contents for the project BOQ report package."""
    bill, rates, _, costing = price_project_bill(ctx)
    toc = [
        {
            "sectionNo": "1.0",
            "title": "Executive & Client Cost Summary",
            "records": len(costing.parts),
        },
        {"sectionNo": "2.0", "title": "Trade Package Summary", "records": len(costing.groups)},
        {"sectionNo": "3.0", "title": "Measured Bill of Quantities", "records": len(bill["items"])},
        {"sectionNo": "4.0", "title": "Schedule of Rates Applied", "records": len(rates.items)},
        {"sectionNo": "5.0", "title": "Embodied Carbon Assessment", "records": len(costing.carbon)},
        {
            "sectionNo": "6.0",
            "title": "Measurement Conventions & Notes",
            "records": len(bill.get("notes") or []),
        },
    ]
    return result(
        summary={"sectionCount": len(toc), "totalRecords": sum(r["records"] for r in toc)},
        tables=[
            table(
                "BOQ report table of contents",
                [("sectionNo", "Section"), ("title", "Report title"), ("records", "Records")],
                toc,
            )
        ],
        notes=["Provides standard section numbering for bound tender and cost reports."],
    )


@feature(
    "boqReports.digitalSignature",
    "Digital Signature",
    part="boq",
    fields=[
        text("signatory", "Authorised QS / Engineer", "Chartered Quantity Surveyor"),
        text("role", "Designation", "Commercial Lead"),
    ],
    requires_project=True,
)
def digital_signature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a deterministic SHA-256 document seal for the priced BOQ submission."""
    bill, rates, _, costing = price_project_bill(ctx)
    payload = safe_json(
        {
            "total": costing.total,
            "currency": rates.currency,
            "items": len(bill["items"]),
            "signatory": values["signatory"],
        }
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return result(
        summary={
            "signatory": values["signatory"],
            "role": values["role"],
            "sha256Seal": digest[:24],
        },
        tables=[
            table(
                "Issued BOQ digital seal",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Signatory", "value": values["signatory"]},
                    {"field": "Role", "value": values["role"]},
                    {"field": "SHA-256 Seal", "value": digest},
                ],
            )
        ],
        notes=["Deterministic SHA-256 fingerprint binds signatory identity to priced bill state."],
    )


@feature(
    "boqReports.distributionList",
    "Distribution List",
    part="boq",
    fields=[
        text(
            "recipientsCsv",
            "Recipients CSV (name,role,package_access)",
            "name,role,package_access\nClient Rep,Employer,Summary & Client Reports\nLead Architect,Design Team,Unpriced BOQ & QTO\nTender Panel,Procurement,Blank Tender & Schedule",
        )
    ],
    requires_project=False,
)
def distribution_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Maintain the controlled document distribution list and access levels for BOQ reports."""
    raw = parse_csv_rows(values["recipientsCsv"])
    rows = [{"name": r["name"], "role": r["role"], "access": r["package_access"]} for r in raw]
    return result(
        summary={"recipientCount": len(rows)},
        tables=[
            table(
                "BOQ report distribution matrix",
                [("name", "Recipient"), ("role", "Role"), ("access", "Access scope")],
                rows,
            )
        ],
        notes=[
            "Controls confidential distribution of priced estimates vs unpriced tender documents."
        ],
    )


@feature(
    "boqReports.archiveReports",
    "Archive Reports",
    part="boq",
    fields=[text("revisionLabel", "Archive revision label", "REV-01")],
    requires_project=True,
)
def archive_reports(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Archive a complete JSON snapshot of the priced BOQ, costing, and carbon ledger under 10 BOQ/exports."""
    bill, rates, _, costing = price_project_bill(ctx)
    archive = {
        "revision": values["revisionLabel"],
        "currency": rates.currency,
        "total": costing.total,
        "carbonTotal": costing.carbonTotal,
        "groups": costing.groups,
        "parts": costing.parts,
        "itemCount": len(bill["items"]),
    }
    target = save_export(ctx, f"boq-archive-{values['revisionLabel']}.json", safe_json(archive))
    return result(
        summary={
            "revision": values["revisionLabel"],
            "archivePath": str(target),
            "totalCost": costing.total,
        },
        tables=[
            table(
                "Archived report metadata",
                [("key", "Field"), ("value", "Value")],
                [
                    {"key": "Revision", "value": values["revisionLabel"]},
                    {"key": "Archive file", "value": str(target)},
                    {"key": "Total value", "value": f"{costing.total:,.2f} {rates.currency}"},
                ],
            )
        ],
        notes=[f"Archived BOQ snapshot written to {target}."],
    )
