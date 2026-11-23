"""BOQ - Items & Measure tab: measured items, coding, auto-measurement, hierarchy, totals & views."""

from __future__ import annotations

from typing import Any

from saengine.boq.quantities import GROUPS, KINDS, compute_boq
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
    load_rates,
    parse_csv_rows,
    price_project_bill,
    require_bill,
    require_root,
    safe_json,
    save_export,
)
from saengine.report.clauses import in_force


@feature(
    "boq.addItem",
    "Add Item",
    part="boq",
    fields=[
        text("code", "BOQ item code", "C.99"),
        select(
            "group",
            "Trade group",
            [(g, g.title()) for g in GROUPS],
            "concrete",
        ),
        text("description", "Item description", "Cast-in-situ concrete in grade beams"),
        number("quantity", "Measured quantity", 12.5, min=0.0),
        select(
            "unit",
            "Unit",
            [
                ("m3", "m3"),
                ("m2", "m2"),
                ("m", "m"),
                ("kg", "kg"),
                ("nr", "nr"),
                ("bag", "bag"),
                ("cft", "cft"),
                ("l", "l"),
            ],
            "m3",
        ),
        number("unitRate", "Unit rate", 13000.0, min=0.0),
    ],
    requires_project=False,
)
def add_item(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and price a measured BOQ line item with unit, quantity, and extended amount."""
    qty = values["quantity"]
    rate = values["unitRate"]
    amt = qty * rate
    row = {
        "code": values["code"].strip() or "X.01",
        "group": values["group"],
        "description": values["description"].strip() or "Measured item",
        "quantity": qty,
        "unit": values["unit"],
        "rate": rate,
        "amount": amt,
    }
    return result(
        summary={"code": row["code"], "quantity": qty, "unit": row["unit"], "amount": amt},
        tables=[
            table(
                "Measured BOQ line item",
                [
                    ("code", "Code"),
                    ("group", "Group"),
                    ("description", "Description"),
                    ("quantity", "Qty"),
                    ("unit", "Unit"),
                    ("rate", "Rate"),
                    ("amount", "Amount"),
                ],
                [row],
            )
        ],
        notes=["Extended amount = quantity * unit rate."],
    )


@feature(
    "boq.itemCodes",
    "Item Codes",
    part="boq",
    fields=[],
    requires_project=True,
)
def item_codes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit and verify standard group prefix codes across all measured BOQ items."""
    bill = require_bill(ctx)
    rows = []
    valid = 0
    for item in bill["items"]:
        grp = str(item.get("group", ""))
        prefix = GROUPS.get(grp, "?")
        code = str(item.get("code", ""))
        ok = code.startswith(f"{prefix}.")
        if ok:
            valid += 1
        rows.append(
            {
                "code": code,
                "group": grp,
                "expectedPrefix": prefix,
                "description": item.get("description", ""),
                "ok": ok,
            }
        )
    return result(
        summary={"totalItems": len(rows), "validCodes": valid, "allStandard": valid == len(rows)},
        tables=[
            table(
                "BOQ item coding audit",
                [
                    ("code", "Code"),
                    ("group", "Group"),
                    ("expectedPrefix", "Prefix"),
                    ("description", "Description"),
                    ("ok", "Matches"),
                ],
                rows[:50],
            )
        ],
        notes=[
            "Group prefixes follow saengine.boq.quantities.GROUPS (E, C, M, A, R, F, S, P, MT)."
        ],
    )


@feature(
    "boq.itemLibrary",
    "Item Library",
    part="boq",
    fields=[text("groupFilter", "Filter by group (blank = all)", "")],
    requires_project=False,
)
def item_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Browse reusable schedule-of-rates item definitions and matching rules."""
    rates, is_proj = load_rates(ctx)
    filt = values["groupFilter"].strip().lower()
    rows = []
    for item in rates.items:
        grp = item.match.group or "general"
        if filt and filt not in grp.lower() and filt not in item.description.lower():
            continue
        rows.append(
            {
                "code": item.code,
                "group": grp,
                "description": item.description,
                "unit": item.unit,
                "rate": item.rate if item.rate is not None else 0.0,
            }
        )
    return result(
        summary={
            "source": "project" if is_proj else "sample library",
            "itemCount": len(rows),
            "currency": rates.currency,
        },
        tables=[
            table(
                f"Standard BOQ item library ({rates.currency})",
                [
                    ("code", "Item #"),
                    ("group", "Group"),
                    ("description", "Description"),
                    ("unit", "Unit"),
                    ("rate", "Rate"),
                ],
                rows,
            )
        ],
        notes=[
            "Items match bill lines by group, element kind, material, diameter, or description pattern."
        ],
    )


@feature(
    "boq.compositeItems",
    "Composite Items",
    part="boq",
    fields=[
        text("parentCode", "Composite item code", "COMP-SLAB-150"),
        text("parentUnit", "Composite unit", "m2"),
        text(
            "componentsCsv",
            "Sub-items CSV (subcode,description,factor_per_unit,sub_unit,unit_rate)",
            "C.05,Concrete C25 (0.15 m3/m2),0.15,m3,13000\nF.03,Soffit formwork (1.0 m2/m2),1.0,m2,600\nR.10,Reinforcement steel (18 kg/m2),18.0,kg,105",
        ),
    ],
    requires_project=False,
)
def composite_items(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build a composite BOQ item rate from weighted sub-item quantities and unit rates."""
    raw = parse_csv_rows(values["componentsCsv"])
    rows = []
    comp_rate = 0.0
    for r in raw:
        try:
            fac = float(r["factor_per_unit"])
            ur = float(r["unit_rate"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError(
                "CSV requires subcode, description, factor_per_unit, sub_unit, unit_rate."
            ) from exc
        contrib = fac * ur
        comp_rate += contrib
        rows.append(
            {
                "subcode": r["subcode"],
                "description": r["description"],
                "factor": fac,
                "subUnit": r.get("sub_unit", ""),
                "unitRate": ur,
                "contribution": contrib,
            }
        )
    return result(
        summary={
            "parentCode": values["parentCode"],
            "parentUnit": values["parentUnit"],
            "subItemCount": len(rows),
            "compositeUnitRate": comp_rate,
        },
        tables=[
            table(
                f"Composite item build-up ({values['parentCode']})",
                [
                    ("subcode", "Sub-code"),
                    ("description", "Component"),
                    ("factor", "Factor"),
                    ("subUnit", "Sub-unit"),
                    ("unitRate", "Unit rate"),
                    ("contribution", "Cost / unit"),
                ],
                rows,
            )
        ],
        notes=[f"Composite rate sums weighted sub-item contributions per {values['parentUnit']}."],
    )


@feature(
    "boq.autoMeasure",
    "Auto Measure",
    part="boq",
    fields=[checkbox("exportJson", "Save measured BOQ JSON to 10 BOQ/exports", False)],
    requires_project=True,
)
def auto_measure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Re-measure full project quantities directly from BIM, Objects, Materials, Substructure, and MEP."""
    root = require_root(ctx, "auto-measuring the project BOQ")

    def _read_txt(rel: str) -> str | None:
        p = ctx.path(rel)
        return p.read_text(encoding="utf-8") if p is not None and p.is_file() else None

    bim_t = _read_txt("06 BIM/bim.json")
    obj_t = _read_txt("04 Objects/objects.json")
    mat_t = _read_txt("03 Materials/materials.json")
    if not (bim_t and obj_t and mat_t):
        raise FeatureInputError(
            "Auto Measure requires 06 BIM/bim.json, 04 Objects/objects.json, and 03 Materials/materials.json."
        )
    with in_force(ctx.root):
        doc = compute_boq(
            bim_t,
            obj_t,
            mat_t,
            _read_txt("09 Substructure/substructure.json"),
            _read_txt("02 Project Settings/project-settings.json"),
            _read_txt("07 MEP/mep.json"),
            str(root),
            _read_txt("05 Floor Plan/architecture.json"),
        )
    by_grp: dict[str, int] = {}
    for item in doc["items"]:
        g = str(item.get("group"))
        by_grp[g] = by_grp.get(g, 0) + 1
    out_path = ""
    if values["exportJson"]:
        out_path = str(save_export(ctx, "boq-remeasured.json", safe_json(doc)))
    rows = [{"group": g, "itemCount": c} for g, c in by_grp.items()]
    return result(
        summary={
            "measuredItems": len(doc["items"]),
            "groups": len(rows),
            "exportPath": out_path or "preview",
        },
        tables=[
            table(
                "Auto-measured BOQ summary",
                [("group", "Trade group"), ("itemCount", "Items")],
                rows,
            )
        ],
        notes=["Measured from 06 BIM using 04 Objects, 03 Materials, 09 Substructure, and 07 MEP."],
    )


@feature(
    "boq.measureRules",
    "Measure Rules",
    part="boq",
    fields=[],
    requires_project=False,
)
def measure_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display active measurement conventions and element-kind deduction rules."""
    bill = load_bill(ctx)
    if bill and bill.get("notes"):
        rows = [{"ruleIndex": i + 1, "ruleText": str(n)} for i, n in enumerate(bill["notes"][:10])]
    else:
        rows = [
            {
                "ruleIndex": 1,
                "ruleText": "Slabs measured over full outline and thickness less openings; beam/column/wall slab-depth overlaps belong to slab.",
            },
            {
                "ruleIndex": 2,
                "ruleText": "Beams measured clear between column faces and below slab; columns full height less slab depth.",
            },
            {
                "ruleIndex": 3,
                "ruleText": "Reinforcement taken from detailed BBS where available, else estimating rules with 40d laps per 12 m stock bar.",
            },
            {
                "ruleIndex": 4,
                "ruleText": "Formwork measured on net cast faces only (contact faces against other concrete deducted).",
            },
            {
                "ruleIndex": 5,
                "ruleText": "Excavation includes 300 mm working space around foundations; blinding 75 mm thick + 75 mm projection.",
            },
        ]
    return result(
        summary={"ruleCount": len(rows), "supportedElementKinds": len(KINDS)},
        tables=[
            table(
                "BOQ measurement conventions",
                [("ruleIndex", "#"), ("ruleText", "Measurement rule")],
                rows,
            )
        ],
        notes=[
            "Standardised measurement hierarchy avoids double-counting concrete at member intersections."
        ],
    )


@feature(
    "boq.deductOpenings",
    "Deduct Openings",
    part="boq",
    fields=[
        number("grossAreaM2", "Gross slab or wall face area", 120.0, unit="m2", min=0.5),
        number("thicknessMm", "Element thickness", 200.0, unit="mm", min=50.0),
        number(
            "minDeductAreaM2", "Minimum opening area threshold to deduct", 0.10, unit="m2", min=0.0
        ),
        text(
            "openingsCsv",
            "Openings CSV (id,width_m,height_m,count)",
            "O1,1.2,2.1,2\nO2,0.25,0.25,4\nO3,1.8,1.5,1",
        ),
    ],
    requires_project=False,
)
def deduct_openings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Deduct openings and voids exceeding minimum threshold from gross concrete and formwork quantities."""
    raw = parse_csv_rows(values["openingsCsv"])
    thresh = values["minDeductAreaM2"]
    rows = []
    tot_deduct = 0.0
    for r in raw:
        try:
            w = float(r["width_m"])
            h = float(r["height_m"])
            cnt = int(float(r.get("count", 1)))
        except (KeyError, ValueError) as exc:
            raise FeatureInputError("CSV requires id, width_m, height_m, count.") from exc
        each_a = w * h
        deducted = each_a * cnt if each_a >= thresh else 0.0
        tot_deduct += deducted
        rows.append(
            {
                "id": r.get("id", "?"),
                "eachAreaM2": each_a,
                "count": cnt,
                "deductedM2": deducted,
                "applied": each_a >= thresh,
            }
        )
    net_area = max(0.0, values["grossAreaM2"] - tot_deduct)
    net_vol = net_area * (values["thicknessMm"] / 1000.0)
    return result(
        summary={
            "grossAreaM2": values["grossAreaM2"],
            "deductedAreaM2": tot_deduct,
            "netAreaM2": net_area,
            "netVolumeM3": net_vol,
        },
        tables=[
            table(
                "Opening deduction schedule",
                [
                    ("id", "Opening"),
                    ("eachAreaM2", "Each", "m2"),
                    ("count", "Qty"),
                    ("deductedM2", "Deducted", "m2"),
                    ("applied", "Threshold met"),
                ],
                rows,
            )
        ],
        notes=[
            f"Small service penetrations below {thresh:g} m2 are ignored per measurement rules."
        ],
    )


@feature(
    "boq.insertSection",
    "Insert Section",
    part="boq",
    fields=[
        text("sectionLetter", "New section code prefix", "X"),
        text("sectionTitle", "Section title", "External Works & Drainage"),
        number("insertAfterIndex", "Insert after group order (1..12)", 2.0, min=0.0, max=20.0),
    ],
    requires_project=True,
)
def insert_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview inserting a new bill section and renumbering group sequence numbers."""
    bill = require_bill(ctx)
    existing_groups = list(dict.fromkeys(str(it.get("group", "")) for it in bill["items"]))
    pos = min(len(existing_groups), round(values["insertAfterIndex"]))
    new_order = (
        existing_groups[:pos]
        + [values["sectionTitle"].strip() or "New Section"]
        + existing_groups[pos:]
    )
    rows = [{"seq": i + 1, "section": g, "isNew": i == pos} for i, g in enumerate(new_order)]
    return result(
        summary={
            "existingSections": len(existing_groups),
            "newSectionCount": len(rows),
            "insertedAt": pos + 1,
        },
        tables=[
            table(
                "Renumbered BOQ sections",
                [("seq", "Order"), ("section", "Section"), ("isNew", "Inserted")],
                rows,
            )
        ],
        notes=[f"New section prefix '{values['sectionLetter']}' scheduled at position {pos + 1}."],
    )


@feature(
    "boq.indentItems",
    "Indent Items",
    part="boq",
    fields=[
        number("maxLevel", "Hierarchy depth (1=group, 2=item, 3=element)", 3.0, min=1.0, max=3.0)
    ],
    requires_project=True,
)
def indent_items(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display the BOQ item hierarchy indented by trade group, line item, and element breakdown."""
    bill = require_bill(ctx)
    lvl = round(values["maxLevel"])
    rows = []
    seen_groups: set[str] = set()
    for item in bill["items"]:
        grp = str(item.get("group", ""))
        if grp not in seen_groups:
            seen_groups.add(grp)
            rows.append(
                {
                    "level": 1,
                    "code": GROUPS.get(grp, "-"),
                    "label": grp.upper(),
                    "qty": "",
                    "unit": "",
                }
            )
        if lvl >= 2:
            rows.append(
                {
                    "level": 2,
                    "code": str(item.get("code", "")),
                    "label": f"  {item.get('description', '')}",
                    "qty": item.get("quantity", 0.0),
                    "unit": str(item.get("unit", "")),
                }
            )
        if lvl >= 3:
            for br in (item.get("breakdown") or [])[:4]:
                rows.append(
                    {
                        "level": 3,
                        "code": "",
                        "label": f"    - {br.get('element', '')} ({br.get('story', '-')})",
                        "qty": br.get("quantity", 0.0),
                        "unit": str(item.get("unit", "")),
                    }
                )
    return result(
        summary={"hierarchyDepth": lvl, "displayRows": len(rows)},
        tables=[
            table(
                "Hierarchical BOQ outline",
                [
                    ("level", "Lvl"),
                    ("code", "Code"),
                    ("label", "Item / Breakdown"),
                    ("qty", "Quantity"),
                    ("unit", "Unit"),
                ],
                rows[:60],
            )
        ],
        notes=["Displays 3-level WBS rollup: Group -> Bill Item -> BIM Element breakdown."],
    )


@feature(
    "boq.subtotalRows",
    "Subtotal Rows",
    part="boq",
    fields=[],
    requires_project=True,
)
def subtotal_rows(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute priced subtotals per BOQ trade group and building part (Superstructure/Substructure/MEP)."""
    _, rates, _, costing = price_project_bill(ctx)
    rows = [
        {
            "group": grp,
            "amount": amt,
            "sharePct": (amt / costing.total * 100.0) if costing.total > 0 else 0.0,
        }
        for grp, amt in costing.groups.items()
    ]
    part_rows = [
        {
            "group": f"Part: {p}",
            "amount": amt,
            "sharePct": (amt / costing.total * 100.0) if costing.total > 0 else 0.0,
        }
        for p, amt in costing.parts.items()
    ]
    return result(
        summary={"currency": rates.currency, "groupCount": len(rows), "grandTotal": costing.total},
        tables=[
            table(
                f"BOQ subtotals ({rates.currency})",
                [("group", "Trade / Part"), ("amount", "Subtotal"), ("sharePct", "Share", "%")],
                rows + part_rows,
            )
        ],
        notes=["Priced via saengine.boq.costing.cost_bill."],
    )


@feature(
    "boq.grandTotal",
    "Grand Total",
    part="boq",
    fields=[
        number("overheadPct", "Overheads & preliminaries", 10.0, unit="%", min=0.0, max=50.0),
        number("profitPct", "Contractor profit margin", 8.0, unit="%", min=0.0, max=50.0),
        number("contingencyPct", "Contingency allowance", 5.0, unit="%", min=0.0, max=50.0),
        number("taxPct", "VAT / tax rate", 7.5, unit="%", min=0.0, max=30.0),
    ],
    requires_project=True,
)
def grand_total(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recalculate the BOQ grand total including overheads, profit, contingency, and tax."""
    _, rates, _, costing = price_project_bill(ctx)
    base = costing.total
    oh = base * values["overheadPct"] / 100.0
    prof = (base + oh) * values["profitPct"] / 100.0
    cont = (base + oh + prof) * values["contingencyPct"] / 100.0
    sub_pre_tax = base + oh + prof + cont
    tax = sub_pre_tax * values["taxPct"] / 100.0
    grand = sub_pre_tax + tax
    rows = [
        {"line": "Direct measured BOQ cost", "amount": base},
        {"line": f"Overheads ({values['overheadPct']:g}%)", "amount": oh},
        {"line": f"Profit ({values['profitPct']:g}%)", "amount": prof},
        {"line": f"Contingency ({values['contingencyPct']:g}%)", "amount": cont},
        {"line": f"Tax / VAT ({values['taxPct']:g}%)", "amount": tax},
        {"line": "Grand Total", "amount": grand},
    ]
    return result(
        summary={
            "currency": rates.currency,
            "directCost": base,
            "taxAmount": tax,
            "grandTotal": grand,
        },
        tables=[
            table(
                f"Grand total rollup ({rates.currency})",
                [("line", "Cost tier"), ("amount", "Amount")],
                rows,
            )
        ],
        notes=[
            "Compounds markups sequentially: direct -> overheads -> profit -> contingency -> tax."
        ],
    )


@feature(
    "boq.sortItems",
    "Sort Items",
    part="boq",
    fields=[
        select(
            "sortBy",
            "Sort criterion",
            [
                ("amount", "Total value (descending)"),
                ("quantity", "Quantity (descending)"),
                ("code", "Item code (ascending)"),
                ("group", "Trade group"),
            ],
            "amount",
        ),
    ],
    requires_project=True,
)
def sort_items(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sort all priced BOQ items by value, quantity, item code, or trade group."""
    _, rates, _, costing = price_project_bill(ctx)
    by = values["sortBy"]
    if by == "amount":
        lines = sorted(costing.lines, key=lambda l: -(l.amount or 0.0))
    elif by == "quantity":
        lines = sorted(costing.lines, key=lambda l: -l.quantity)
    elif by == "group":
        lines = sorted(costing.lines, key=lambda l: (l.group, l.code))
    else:
        lines = sorted(costing.lines, key=lambda l: l.code)
    rows = [
        {
            "code": li.code,
            "group": li.group,
            "description": li.description,
            "qty": li.quantity,
            "unit": li.unit,
            "amount": li.amount or 0.0,
        }
        for li in lines
    ]
    return result(
        summary={
            "sortBy": by,
            "itemCount": len(rows),
            "topItemCode": rows[0]["code"] if rows else "",
        },
        tables=[
            table(
                f"Sorted BOQ ({rates.currency})",
                [
                    ("code", "Code"),
                    ("group", "Group"),
                    ("description", "Description"),
                    ("qty", "Qty"),
                    ("unit", "Unit"),
                    ("amount", "Amount"),
                ],
                rows,
            )
        ],
        notes=[f"Sorted {len(rows)} items by {by}."],
    )


@feature(
    "boq.filterItems",
    "Filter Items",
    part="boq",
    fields=[
        text("group", "Trade group filter (blank = all)", ""),
        text("unit", "Unit filter (blank = all)", ""),
        select(
            "status",
            "Pricing status",
            [("all", "All"), ("priced", "Priced only"), ("unpriced", "Unpriced / missing rate")],
            "all",
        ),
    ],
    requires_project=True,
)
def filter_items(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Filter bill items by trade group, measurement unit, and rate pricing status."""
    _, rates, _, costing = price_project_bill(ctx)
    gf = values["group"].strip().lower()
    uf = values["unit"].strip().lower()
    st = values["status"]
    rows = []
    for li in costing.lines:
        if gf and gf not in li.group.lower():
            continue
        if uf and uf != li.unit.lower():
            continue
        if st == "priced" and li.status != "priced":
            continue
        if st == "unpriced" and li.status == "priced":
            continue
        rows.append(
            {
                "code": li.code,
                "group": li.group,
                "description": li.description,
                "qty": li.quantity,
                "unit": li.unit,
                "status": li.status,
                "amount": li.amount or 0.0,
            }
        )
    return result(
        summary={
            "matchedItems": len(rows),
            "filteredAmount": sum(r["amount"] for r in rows),
            "currency": rates.currency,
        },
        tables=[
            table(
                "Filtered BOQ items",
                [
                    ("code", "Code"),
                    ("group", "Group"),
                    ("description", "Description"),
                    ("qty", "Qty"),
                    ("unit", "Unit"),
                    ("status", "Status"),
                    ("amount", "Amount"),
                ],
                rows,
            )
        ],
        notes=["Filters applied across group, unit, and pricing status."],
    )


@feature(
    "boq.itemNotes",
    "Item Notes",
    part="boq",
    fields=[
        text("itemCode", "BOQ item code (blank = first)", ""),
        text(
            "noteText",
            "Measurement assumption / specification note",
            "Includes concrete supply, placing, vibrating and 7-day wet curing.",
        ),
    ],
    requires_project=True,
)
def item_notes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Attach and inspect measurement notes and assumptions on individual BOQ line items."""
    bill = require_bill(ctx)
    code = values["itemCode"].strip()
    item = (
        next((i for i in bill["items"] if str(i.get("code", "")).lower() == code.lower()), None)
        if code
        else bill["items"][0]
    )
    if item is None:
        raise FeatureInputError(f"BOQ item '{code}' not found.")
    note = values["noteText"].strip()
    rows = [
        {"field": "Item code", "value": str(item.get("code"))},
        {"field": "Description", "value": str(item.get("description"))},
        {"field": "Quantity", "value": f"{item.get('quantity')} {item.get('unit')}"},
        {"field": "Attached note", "value": note},
    ]
    return result(
        summary={
            "itemCode": str(item.get("code")),
            "breakdownElements": len(item.get("breakdown") or []),
        },
        tables=[
            table("BOQ item specification note", [("field", "Field"), ("value", "Value")], rows)
        ],
        notes=[f"Note linked to {item.get('code')}: {note}"],
    )


@feature(
    "boq.revisionMark",
    "Revision Mark",
    part="boq",
    fields=[text("revisionTag", "Revision tag", "Rev-B")],
    requires_project=True,
)
def revision_mark(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Flag BOQ items whose source model hash differs or which carry pending measurement problems."""
    bill = require_bill(ctx)
    problems = bill.get("problems") or []
    rows = []
    for it in bill["items"]:
        code = str(it.get("code", ""))
        desc = str(it.get("description", ""))
        flagged = any(
            str(br.get("element", "")) in str(problems) for br in (it.get("breakdown") or [])
        )
        rows.append(
            {
                "code": code,
                "description": desc,
                "revision": values["revisionTag"],
                "pending": flagged,
            }
        )
    return result(
        summary={
            "revisionTag": values["revisionTag"],
            "totalItems": len(rows),
            "flaggedItems": sum(1 for r in rows if r["pending"]),
        },
        tables=[
            table(
                f"BOQ revision register ({values['revisionTag']})",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("revision", "Revision"),
                    ("pending", "Pending review"),
                ],
                rows[:50],
            )
        ],
        notes=[
            "Highlights bill lines linked to elements with unresolved design or measurement notes."
        ],
    )
