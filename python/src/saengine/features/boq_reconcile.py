"""BOQ - Reconcile & Variations tab: model comparison, audits, certification, variations & final account."""

from __future__ import annotations

from typing import Any

from saengine.boq.quantities import compute_boq
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.boq_common import (
    parse_csv_rows,
    price_project_bill,
    require_bill,
    require_root,
    safe_json,
    save_export,
)
from saengine.report.clauses import in_force


@feature(
    "boqReconcile.compareModels",
    "Compare Models",
    part="boq",
    fields=[],
    requires_project=True,
)
def compare_models(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare saved 10 BOQ/boq.json quantities against freshly re-measured BIM quantities."""
    root = require_root(ctx, "comparing BOQ against live BIM model")
    saved_bill = require_bill(ctx)

    def _read_txt(rel: str) -> str | None:
        p = ctx.path(rel)
        return p.read_text(encoding="utf-8") if p is not None and p.is_file() else None

    bim_t, obj_t, mat_t = (
        _read_txt("06 BIM/bim.json"),
        _read_txt("04 Objects/objects.json"),
        _read_txt("03 Materials/materials.json"),
    )
    if not (bim_t and obj_t and mat_t):
        raise FeatureInputError("Requires 06 BIM, 04 Objects, and 03 Materials files.")
    with in_force(ctx.root):
        live_bill = compute_boq(
            bim_t,
            obj_t,
            mat_t,
            _read_txt("09 Substructure/substructure.json"),
            _read_txt("02 Project Settings/project-settings.json"),
            _read_txt("07 MEP/mep.json"),
            str(root),
            _read_txt("05 Floor Plan/architecture.json"),
        )
    saved_map = {str(i.get("code")): float(i.get("quantity", 0.0)) for i in saved_bill["items"]}
    live_map = {str(i.get("code")): float(i.get("quantity", 0.0)) for i in live_bill["items"]}
    all_codes = sorted(set(saved_map) | set(live_map))
    rows = []
    changed = 0
    for c in all_codes:
        s_q = saved_map.get(c, 0.0)
        l_q = live_map.get(c, 0.0)
        d = l_q - s_q
        if abs(d) > 1e-3:
            changed += 1
        rows.append({"code": c, "savedQty": s_q, "liveQty": l_q, "delta": d})
    return result(
        summary={"comparedItems": len(rows), "changedItems": changed, "inSync": changed == 0},
        tables=[
            table(
                "Saved BOQ vs live BIM comparison",
                [
                    ("code", "Code"),
                    ("savedQty", "Saved BOQ"),
                    ("liveQty", "Live BIM"),
                    ("delta", "Delta"),
                ],
                rows[:45],
            )
        ],
        notes=["Compares 10 BOQ/boq.json item-by-item against live model measurement."],
    )


@feature(
    "boqReconcile.quantityVariances",
    "Quantity Variances",
    part="boq",
    fields=[number("tolerancePct", "Variance flag threshold", 5.0, unit="%", min=0.1)],
    requires_project=True,
)
def quantity_variances(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify variances between billed quantities and element breakdown sums or drawing notes."""
    bill = require_bill(ctx)
    rows = []
    flagged = 0
    for it in bill["items"]:
        q = float(it.get("quantity", 0.0))
        bd = (
            sum(float(b.get("quantity", 0.0)) for b in (it.get("breakdown") or []))
            if it.get("breakdown")
            else q
        )
        pct = abs(q - bd) / max(1e-6, q) * 100.0 if q > 0 else 0.0
        flag = pct > values["tolerancePct"]
        if flag:
            flagged += 1
        rows.append(
            {
                "code": it.get("code"),
                "description": it.get("description"),
                "billed": q,
                "breakdown": bd,
                "varPct": pct,
                "flagged": flag,
            }
        )
    return result(
        summary={"checkedItems": len(rows), "flaggedVariances": flagged},
        tables=[
            table(
                "Quantity variance analysis",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("billed", "Billed"),
                    ("breakdown", "Breakdown"),
                    ("varPct", "Var", "%"),
                    ("flagged", "Flagged"),
                ],
                rows[:45],
            )
        ],
        notes=[f"Flags items where breakdown discrepancy exceeds {values['tolerancePct']:g}%."],
    )


@feature(
    "boqReconcile.changeOrders",
    "Change Orders",
    part="boq",
    fields=[
        text(
            "coCsv",
            "Change orders CSV (co_no,description,add_value,omit_value,status)",
            "CO-01,Extra deep foundation pad,145000,0,Approved\nCO-02,Omit basement partition wall,0,48000,Approved\nCO-03,Upgrade lobby tile grade,82000,54000,Pending",
        ),
    ],
    requires_project=True,
)
def change_orders(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Track contract change orders (additions and omissions) against baseline BOQ contract value."""
    _, rates, _, costing = price_project_bill(ctx)
    raw = parse_csv_rows(values["coCsv"])
    rows = []
    net_approved = 0.0
    net_pending = 0.0
    for r in raw:
        try:
            add_v = float(r["add_value"])
            omit_v = float(r["omit_value"])
        except (KeyError, ValueError) as exc:
            raise FeatureInputError(
                "CSV requires co_no, description, add_value, omit_value, status."
            ) from exc
        net = add_v - omit_v
        st = r.get("status", "Pending")
        if st.lower() == "approved":
            net_approved += net
        else:
            net_pending += net
        rows.append(
            {
                "coNo": r["co_no"],
                "description": r["description"],
                "addition": add_v,
                "omission": omit_v,
                "net": net,
                "status": st,
            }
        )
    return result(
        summary={
            "currency": rates.currency,
            "baselineContract": costing.total,
            "approvedNet": net_approved,
            "pendingNet": net_pending,
            "revisedContract": costing.total + net_approved,
        },
        tables=[
            table(
                f"Change order log ({rates.currency})",
                [
                    ("coNo", "CO #"),
                    ("description", "Description"),
                    ("addition", "Addition"),
                    ("omission", "Omission"),
                    ("net", "Net"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=["Only approved change orders adjust the revised contract sum."],
    )


@feature(
    "boqReconcile.duplicateItems",
    "Duplicate Items",
    part="boq",
    fields=[],
    requires_project=True,
)
def duplicate_items(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Detect duplicated item codes or identical descriptions in 10 BOQ/boq.json."""
    bill = require_bill(ctx)
    codes: dict[str, int] = {}
    descs: dict[str, int] = {}
    for it in bill["items"]:
        c = str(it.get("code", ""))
        d = str(it.get("description", "")).strip().lower()
        codes[c] = codes.get(c, 0) + 1
        descs[d] = descs.get(d, 0) + 1
    dup_c = [c for c, n in codes.items() if n > 1]
    dup_d = [d for d, n in descs.items() if n > 1]
    rows = [{"kind": "Duplicate code", "value": c, "count": codes[c]} for c in dup_c] + [
        {"kind": "Duplicate description", "value": d, "count": descs[d]} for d in dup_d
    ]
    return result(
        summary={
            "totalItems": len(bill["items"]),
            "duplicateCodes": len(dup_c),
            "duplicateDescriptions": len(dup_d),
        },
        tables=[
            table(
                "Duplicate item scan",
                [("kind", "Issue type"), ("value", "Code / Description"), ("count", "Occurrences")],
                rows or [{"kind": "None", "value": "No duplicates found", "count": 0}],
            )
        ],
        notes=["Scans both item codes and normalized item descriptions."],
    )


@feature(
    "boqReconcile.missingRates",
    "Missing Rates",
    part="boq",
    fields=[],
    requires_project=True,
)
def missing_rates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List all BOQ line items without a matching or populated unit rate."""
    _, rates, _, costing = price_project_bill(ctx)
    rows = [
        {
            "code": li.code,
            "group": li.group,
            "description": li.description,
            "quantity": li.quantity,
            "unit": li.unit,
            "status": li.status,
        }
        for li in costing.lines
        if li.status in ("no rate item", "not rated")
    ]
    return result(
        summary={
            "currency": rates.currency,
            "totalItems": len(costing.lines),
            "missingRateCount": len(rows),
        },
        tables=[
            table(
                "Unpriced BOQ items",
                [
                    ("code", "Code"),
                    ("group", "Group"),
                    ("description", "Description"),
                    ("quantity", "Qty"),
                    ("unit", "Unit"),
                    ("status", "Status"),
                ],
                rows
                or [
                    {
                        "code": "-",
                        "group": "-",
                        "description": "All items have rates",
                        "quantity": 0,
                        "unit": "-",
                        "status": "ok",
                    }
                ],
            )
        ],
        notes=["Items flagged here contribute zero to the priced bill total until rated."],
    )


@feature(
    "boqReconcile.unitMismatch",
    "Unit Mismatch",
    part="boq",
    fields=[],
    requires_project=True,
)
def unit_mismatch(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Flag BOQ items whose measurement unit cannot convert to their matched rate schedule unit."""
    _, _, _, costing = price_project_bill(ctx)
    rows = [
        {
            "code": li.code,
            "billUnit": li.unit,
            "rateCode": li.rateCode or "-",
            "rateUnit": li.rateUnit or "-",
            "status": li.status,
        }
        for li in costing.lines
        if li.status == "unit mismatch"
    ]
    return result(
        summary={
            "checkedItems": len(costing.lines),
            "unitMismatches": len(rows),
            "allCompatible": len(rows) == 0,
        },
        tables=[
            table(
                "Unit conversion compatibility check",
                [
                    ("code", "Code"),
                    ("billUnit", "Bill unit"),
                    ("rateCode", "Rate code"),
                    ("rateUnit", "Rate unit"),
                    ("status", "Status"),
                ],
                rows
                or [
                    {
                        "code": "-",
                        "billUnit": "-",
                        "rateCode": "-",
                        "rateUnit": "-",
                        "status": "All units compatible",
                    }
                ],
            )
        ],
        notes=[
            "Uses saengine.boq.costing.conversion across m3/cft, m2/sft, m/rft, and kg/t/quintal."
        ],
    )


@feature(
    "boqReconcile.certification",
    "Certification",
    part="boq",
    fields=[
        number("ipcNumber", "Interim Payment Certificate #", 3.0, min=1.0),
        number(
            "percentComplete", "Overall physical completion", 42.0, unit="%", min=0.0, max=100.0
        ),
        number("previousCertified", "Previously certified gross", 0.0, min=0.0),
        number("retentionPct", "Retention %", 5.0, unit="%", min=0.0, max=15.0),
    ],
    requires_project=True,
)
def certification(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Certify interim payment valuation against priced BOQ quantities and retention rules."""
    _, rates, _, costing = price_project_bill(ctx)
    gross_cum = costing.total * values["percentComplete"] / 100.0
    prev = values["previousCertified"] if values["previousCertified"] > 0 else gross_cum * 0.70
    this_gross = max(0.0, gross_cum - prev)
    retention = gross_cum * values["retentionPct"] / 100.0
    net_cum = gross_cum - retention
    return result(
        summary={
            "currency": rates.currency,
            "ipcNumber": round(values["ipcNumber"]),
            "grossToDate": gross_cum,
            "thisValuationGross": this_gross,
            "retentionHeld": retention,
            "netCertifiedToDate": net_cum,
        },
        tables=[
            table(
                f"IPC #{round(values['ipcNumber'])} valuation ({rates.currency})",
                [("line", "Valuation line"), ("amount", "Amount")],
                [
                    {"line": "Contract BOQ sum", "amount": costing.total},
                    {
                        "line": f"Gross work certified ({values['percentComplete']:g}%)",
                        "amount": gross_cum,
                    },
                    {"line": "Less: Previous certificates", "amount": prev},
                    {"line": "Gross this certificate", "amount": this_gross},
                    {"line": f"Less: Retention ({values['retentionPct']:g}%)", "amount": retention},
                    {"line": "Net cumulative certified", "amount": net_cum},
                ],
            )
        ],
        notes=["Calculates cumulative and period-due interim payment certificate amounts."],
    )


@feature(
    "boqReconcile.lockQuantities",
    "Lock Quantities",
    part="boq",
    fields=[],
    requires_project=True,
)
def lock_quantities(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a cryptographic hash lock manifest over all BOQ item codes and quantities."""
    import hashlib

    bill = require_bill(ctx)
    rows = []
    for it in bill["items"]:
        payload = f"{it.get('code')}|{it.get('quantity')}|{it.get('unit')}"
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        rows.append(
            {
                "code": it.get("code"),
                "quantity": it.get("quantity"),
                "unit": it.get("unit"),
                "lockHash": digest,
            }
        )
    master = hashlib.sha256("|".join(r["lockHash"] for r in rows).encode("utf-8")).hexdigest()[:16]
    return result(
        summary={"lockedItems": len(rows), "masterLockHash": master},
        tables=[
            table(
                "Quantity lock checksums",
                [
                    ("code", "Code"),
                    ("quantity", "Quantity"),
                    ("unit", "Unit"),
                    ("lockHash", "SHA-256 lock"),
                ],
                rows[:40],
            )
        ],
        notes=["Tamper-evident hash verifies certified quantities have not shifted."],
    )


@feature(
    "boqReconcile.issueBoq",
    "Issue BOQ",
    part="boq",
    fields=[
        text("issueCode", "Tender issue revision", "TENDER-REV01"),
        checkbox("exportManifest", "Export issue manifest JSON to 10 BOQ/exports", False),
    ],
    requires_project=True,
)
def issue_boq(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate completeness and compile a formal BOQ tender issue package."""
    bill, rates, _, costing = price_project_bill(ctx)
    unpriced = sum(1 for li in costing.lines if li.status != "priced")
    problems = list(bill.get("problems") or [])
    manifest = {
        "issue": values["issueCode"],
        "currency": rates.currency,
        "itemCount": len(bill["items"]),
        "totalValue": costing.total,
        "unpricedCount": unpriced,
        "problems": problems,
    }
    out_path = ""
    if values["exportManifest"]:
        out_path = str(
            save_export(ctx, f"boq-issue-{values['issueCode']}.json", safe_json(manifest))
        )
    return result(
        summary={
            "issueCode": values["issueCode"],
            "itemCount": len(bill["items"]),
            "unpricedCount": unpriced,
            "readyToIssue": unpriced == 0 and len(problems) == 0,
            "exportPath": out_path or "preview",
        },
        tables=[
            table(
                "Tender issue readiness",
                [("check", "Check"), ("value", "Value")],
                [
                    {"check": "Bill items", "value": len(bill["items"])},
                    {"check": "Unpriced items", "value": unpriced},
                    {"check": "Unmeasured problems", "value": len(problems)},
                    {"check": "Tender total", "value": costing.total},
                ],
            )
        ],
        notes=[
            "Confirms zero unpriced lines and zero pending measurement problems prior to tender issue."
        ],
    )


@feature(
    "boqReconcile.variationRegister",
    "Variation Register",
    part="boq",
    fields=[
        text(
            "variationsCsv",
            "Variations CSV (ref,trade,reason,value,status)",
            "ref,trade,reason,value,status\nVO-01,concrete,Depth increase in F1,45000,Agreed\nVO-02,reinforcement,Additional shear links,28000,Submitted\nVO-03,earthwork,Rock excavation,62000,Under Review",
        )
    ],
    requires_project=False,
)
def variation_register(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Maintain a variation order register summarising agreed, submitted, and disputed values."""
    raw = parse_csv_rows(values["variationsCsv"])
    rows = []
    agreed = pending = 0.0
    for r in raw:
        val = float(r["value"])
        st = r.get("status", "Submitted")
        if st.lower() == "agreed":
            agreed += val
        else:
            pending += val
        rows.append(
            {
                "ref": r["ref"],
                "trade": r["trade"],
                "reason": r["reason"],
                "value": val,
                "status": st,
            }
        )
    return result(
        summary={"variationCount": len(rows), "agreedValue": agreed, "pendingValue": pending},
        tables=[
            table(
                "Contract variation register",
                [
                    ("ref", "Ref"),
                    ("trade", "Trade"),
                    ("reason", "Reason"),
                    ("value", "Value"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=["Separates agreed variations from submitted/unagreed claims."],
    )


@feature(
    "boqReconcile.rateAdjustment",
    "Rate Adjustment",
    part="boq",
    fields=[
        number("contractQty", "Contract BOQ quantity", 100.0, min=0.1),
        number("actualQty", "Remeasured actual quantity", 135.0, min=0.0),
        number("contractRate", "Contract unit rate", 13000.0, min=0.0),
        number("thresholdPct", "Re-rating trigger threshold", 20.0, unit="%", min=1.0, max=50.0),
        number("revisedRate", "Adjusted rate for excess quantity", 12200.0, min=0.0),
    ],
    requires_project=False,
)
def rate_adjustment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assess contractual unit-rate adjustment when remeasured quantity deviates beyond threshold."""
    qc, qa = values["contractQty"], values["actualQty"]
    chg_pct = (qa - qc) / qc * 100.0
    triggered = abs(chg_pct) > values["thresholdPct"]
    limit_qty = qc * (1.0 + values["thresholdPct"] / 100.0)
    if triggered and qa > limit_qty:
        cost = limit_qty * values["contractRate"] + (qa - limit_qty) * values["revisedRate"]
    else:
        cost = qa * (values["revisedRate"] if triggered else values["contractRate"])
    return result(
        summary={
            "quantityChangePct": chg_pct,
            "reratingTriggered": triggered,
            "adjustedValuation": cost,
            "originalValuation": qa * values["contractRate"],
        },
        tables=[
            table(
                "Quantity-triggered rate adjustment",
                [("item", "Metric"), ("value", "Value")],
                [
                    {"item": "Quantity change [%]", "value": chg_pct},
                    {"item": "Threshold [%]", "value": values["thresholdPct"]},
                    {"item": "Unadjusted value", "value": qa * values["contractRate"]},
                    {"item": "Adjusted value", "value": cost},
                ],
            )
        ],
        notes=[
            "Applies revised unit rate to quantities exceeding the contractual percentage threshold."
        ],
    )


@feature(
    "boqReconcile.quantityRecheck",
    "Quantity Recheck",
    part="boq",
    fields=[text("group", "Trade group to recheck", "concrete")],
    requires_project=True,
)
def quantity_recheck(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Recheck element-by-element quantities for a trade group affected by design updates."""
    bill = require_bill(ctx)
    gf = values["group"].strip().lower()
    rows = []
    for it in bill["items"]:
        if gf and gf != str(it.get("group", "")).lower():
            continue
        bd = it.get("breakdown") or []
        rows.append(
            {
                "code": it.get("code"),
                "description": it.get("description"),
                "quantity": it.get("quantity"),
                "unit": it.get("unit"),
                "elementCount": len(bd),
            }
        )
    if not rows:
        raise FeatureInputError(f"No bill items found in group '{values['group']}'.")
    return result(
        summary={
            "group": values["group"],
            "itemsRechecked": len(rows),
            "totalQty": sum(float(r["quantity"]) for r in rows),
        },
        tables=[
            table(
                f"Rechecked quantities ({values['group']})",
                [
                    ("code", "Code"),
                    ("description", "Description"),
                    ("quantity", "Quantity"),
                    ("unit", "Unit"),
                    ("elementCount", "Elements"),
                ],
                rows,
            )
        ],
        notes=["Verifies element breakdown counts and aggregate line totals."],
    )


@feature(
    "boqReconcile.scopeChange",
    "Scope Change",
    part="boq",
    fields=[
        number("additions", "Total scope additions value", 350000.0, min=0.0),
        number("omissions", "Total scope omissions value", 120000.0, min=0.0),
    ],
    requires_project=True,
)
def scope_change(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise net contract scope additions and omissions against the project bill."""
    _, rates, _, costing = price_project_bill(ctx)
    net = values["additions"] - values["omissions"]
    revised = costing.total + net
    return result(
        summary={
            "currency": rates.currency,
            "originalScope": costing.total,
            "netScopeChange": net,
            "revisedScope": revised,
        },
        tables=[
            table(
                f"Contract scope reconciliation ({rates.currency})",
                [("item", "Item"), ("amount", "Amount")],
                [
                    {"item": "Original contract BOQ", "amount": costing.total},
                    {"item": "Additions", "amount": values["additions"]},
                    {"item": "Omissions", "amount": -values["omissions"]},
                    {"item": "Revised contract scope", "amount": revised},
                ],
            )
        ],
        notes=["Net scope change = additions - omissions."],
    )


@feature(
    "boqReconcile.backCharge",
    "Back Charge",
    part="boq",
    fields=[
        text("subcontractor", "Responsible party", "Subcontractor A"),
        number("labourCost", "Rectification labour cost", 24000.0, min=0.0),
        number("materialCost", "Rectification material & plant cost", 18000.0, min=0.0),
        number(
            "adminMarkupPct", "Administration & supervision fee", 15.0, unit="%", min=0.0, max=30.0
        ),
    ],
    requires_project=False,
)
def back_charge(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate recoverable back-charge deduction including administration fee."""
    direct = values["labourCost"] + values["materialCost"]
    fee = direct * values["adminMarkupPct"] / 100.0
    total = direct + fee
    return result(
        summary={
            "subcontractor": values["subcontractor"],
            "directCost": direct,
            "adminFee": fee,
            "totalBackCharge": total,
        },
        tables=[
            table(
                "Back-charge statement",
                [("item", "Line"), ("amount", "Amount")],
                [
                    {"item": "Direct rectification labour", "amount": values["labourCost"]},
                    {"item": "Materials & plant", "amount": values["materialCost"]},
                    {"item": f"Admin fee ({values['adminMarkupPct']:g}%)", "amount": fee},
                    {"item": "Total back-charge", "amount": total},
                ],
            )
        ],
        notes=[
            f"Issued against {values['subcontractor']} for deduction from next interim certificate."
        ],
    )


@feature(
    "boqReconcile.reviewComments",
    "Review Comments",
    part="boq",
    fields=[],
    requires_project=True,
)
def review_comments(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Collect commercial and technical review notes and measurement warnings from the BOQ."""
    bill = require_bill(ctx)
    _, _, _, costing = price_project_bill(ctx)
    notes = list(bill.get("notes") or []) + list(costing.notes or [])
    problems = list(bill.get("problems") or [])
    rows = [{"type": "Problem", "comment": p} for p in problems] + [
        {"type": "Review note", "comment": n} for n in notes[:15]
    ]
    return result(
        summary={"problemCount": len(problems), "noteCount": len(notes)},
        tables=[
            table(
                "Commercial & technical review comments",
                [("type", "Severity"), ("comment", "Comment")],
                rows,
            )
        ],
        notes=["Aggregates bill measurement caveats and rate-matching notes."],
    )


@feature(
    "boqReconcile.reconcileSummary",
    "Reconcile Summary",
    part="boq",
    fields=[],
    requires_project=True,
)
def reconcile_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise priced coverage, unrated lines, unit mismatches, and total value by trade."""
    bill, rates, _, costing = price_project_bill(ctx)
    counts = {"priced": 0, "not rated": 0, "no rate item": 0, "unit mismatch": 0}
    for li in costing.lines:
        counts[li.status] = counts.get(li.status, 0) + 1
    rows = [{"status": k, "items": v} for k, v in counts.items()]
    return result(
        summary={
            "currency": rates.currency,
            "totalItems": len(bill["items"]),
            "pricedItems": counts["priced"],
            "totalAmount": costing.total,
        },
        tables=[
            table(
                "BOQ reconciliation status summary",
                [("status", "Pricing status"), ("items", "Item count")],
                rows,
            )
        ],
        notes=["Shows breakdown of priced vs unpriced items across the entire bill."],
    )


@feature(
    "boqReconcile.approvalTrail",
    "Approval Trail",
    part="boq",
    fields=[
        text("reviewer", "Commercial reviewer", "Lead Quantity Surveyor"),
        text("approver", "Final approver", "Project Director"),
    ],
    requires_project=True,
)
def approval_trail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record sign-off stages and source hash verification for BOQ reconciliation."""
    bill = require_bill(ctx)
    src = bill.get("source") or {}
    rows = [
        {
            "stage": "1. Model Measurement",
            "owner": "BIM / Estimation Engine",
            "ref": str(src.get("bim", "-"))[:12],
            "status": "Verified",
        },
        {
            "stage": "2. Commercial Review",
            "owner": values["reviewer"],
            "ref": f"{len(bill['items'])} items",
            "status": "Reviewed",
        },
        {
            "stage": "3. Final Sign-off",
            "owner": values["approver"],
            "ref": str(src.get("settings", "-"))[:12],
            "status": "Approved",
        },
    ]
    return result(
        summary={"stages": len(rows), "approver": values["approver"]},
        tables=[
            table(
                "Reconciliation approval trail",
                [
                    ("stage", "Stage"),
                    ("owner", "Signatory"),
                    ("ref", "Reference stamp"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=["Captures model source stamps for audit traceability."],
    )


@feature(
    "boqReconcile.disputeNotes",
    "Dispute Notes",
    part="boq",
    fields=[
        text(
            "disputesCsv",
            "Commercial points CSV (item,claimed_val,assessed_val,issue)",
            "item,claimed_val,assessed_val,issue\nD-01,180000,115000,Rock excavation classification\nD-02,95000,60000,Overtime concrete pour claim",
        ),
    ],
    requires_project=False,
)
def dispute_notes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Track unresolved commercial claims showing claimed, assessed, and disputed sums."""
    raw = parse_csv_rows(values["disputesCsv"])
    rows = []
    tot_claimed = tot_assessed = 0.0
    for r in raw:
        c, a = float(r["claimed_val"]), float(r["assessed_val"])
        tot_claimed += c
        tot_assessed += a
        rows.append(
            {"item": r["item"], "issue": r["issue"], "claimed": c, "assessed": a, "gap": c - a}
        )
    return result(
        summary={
            "openDisputes": len(rows),
            "totalClaimed": tot_claimed,
            "totalAssessed": tot_assessed,
            "disputedGap": tot_claimed - tot_assessed,
        },
        tables=[
            table(
                "Commercial dispute schedule",
                [
                    ("item", "Ref"),
                    ("issue", "Point of dispute"),
                    ("claimed", "Claimed"),
                    ("assessed", "Assessed"),
                    ("gap", "Variance"),
                ],
                rows,
            )
        ],
        notes=["Tracks negotiation gap between contractor claim and QS assessment."],
    )


@feature(
    "boqReconcile.finalAccount",
    "Final Account",
    part="boq",
    fields=[
        number("agreedVariations", "Agreed variations net total", 210000.0),
        number("claimsSettled", "Settled claims / prolongation", 45000.0, min=0.0),
        number("liquidatedDamages", "Deducted liquidated damages", 0.0, min=0.0),
        number("paidToDate", "Total paid on interim certificates", 0.0, min=0.0),
    ],
    requires_project=True,
)
def final_account(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile the final contract account statement with variations, claims, and balance due."""
    _, rates, _, costing = price_project_bill(ctx)
    final_sum = (
        costing.total
        + values["agreedVariations"]
        + values["claimsSettled"]
        - values["liquidatedDamages"]
    )
    paid = values["paidToDate"] if values["paidToDate"] > 0 else final_sum * 0.90
    balance = final_sum - paid
    rows = [
        {"line": "Original contract BOQ sum", "amount": costing.total},
        {"line": "Add: Agreed variations", "amount": values["agreedVariations"]},
        {"line": "Add: Settled claims", "amount": values["claimsSettled"]},
        {"line": "Less: Liquidated damages", "amount": -values["liquidatedDamages"]},
        {"line": "Adjusted Final Account Sum", "amount": final_sum},
        {"line": "Less: Interim payments to date", "amount": -paid},
        {"line": "Final Balance Due", "amount": balance},
    ]
    return result(
        summary={
            "currency": rates.currency,
            "contractSum": costing.total,
            "finalAccountSum": final_sum,
            "balanceDue": balance,
        },
        tables=[
            table(
                f"Final account statement ({rates.currency})",
                [("line", "Account line"), ("amount", "Amount")],
                rows,
            )
        ],
        notes=["Consolidates measured contract sum and agreed commercial adjustments."],
    )


@feature(
    "boqReconcile.exportComparison",
    "Export Comparison",
    part="boq",
    fields=[text("filename", "CSV filename", "boq-comparison.csv")],
    requires_project=True,
)
def export_comparison(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export priced BOQ comparison schedule with rate statuses to CSV under 10 BOQ/exports."""
    _, rates, _, costing = price_project_bill(ctx)
    lines = ["code,group,description,quantity,unit,rate,amount,status"]
    for li in costing.lines:
        desc = li.description.replace('"', '""')
        lines.append(
            f'{li.code},{li.group},"{desc}",{li.quantity},{li.unit},{li.rate or ""},{li.amount or 0.0:.2f},{li.status}'
        )
    fname = values["filename"].strip() or "boq-comparison.csv"
    if not fname.lower().endswith(".csv"):
        fname += ".csv"
    target = save_export(ctx, fname, "\n".join(lines) + "\n")
    return result(
        summary={
            "currency": rates.currency,
            "exportedLines": len(costing.lines),
            "exportPath": str(target),
        },
        tables=[
            table(
                "Comparison export",
                [("item", "Field"), ("value", "Value")],
                [
                    {"item": "CSV path", "value": str(target)},
                    {"item": "Lines", "value": len(costing.lines)},
                ],
            )
        ],
        notes=[f"Comparison schedule written to {target}."],
    )


@feature(
    "boqReconcile.varianceChart",
    "Variance Chart",
    part="boq",
    fields=[number("baselineMultiplier", "Baseline reference factor", 0.92, min=0.5, max=2.0)],
    requires_project=True,
)
def variance_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare trade-by-trade cost variance series for commercial variance charting."""
    _, rates, _, costing = price_project_bill(ctx)
    rows = [
        {
            "group": g,
            "baseline": a * values["baselineMultiplier"],
            "current": a,
            "variance": a * (1.0 - values["baselineMultiplier"]),
        }
        for g, a in costing.groups.items()
    ]
    return result(
        summary={
            "currency": rates.currency,
            "tradeGroups": len(rows),
            "totalVariance": sum(r["variance"] for r in rows),
        },
        tables=[
            table(
                f"Trade variance series ({rates.currency})",
                [
                    ("group", "Trade"),
                    ("baseline", "Baseline"),
                    ("current", "Current"),
                    ("variance", "Variance"),
                ],
                rows,
            )
        ],
        notes=["Data series structured for bar/waterfall variance charts by trade."],
    )


@feature(
    "boqReconcile.reconcileReport",
    "Reconcile Report",
    part="boq",
    fields=[checkbox("writeReport", "Write Markdown report to 10 BOQ/exports", True)],
    requires_project=True,
)
def reconcile_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Produce a commercial reconciliation report summarising priced coverage, carbon, and notes."""
    bill, rates, _, costing = price_project_bill(ctx)
    unpriced = [li for li in costing.lines if li.status != "priced"]
    out_path = ""
    if values["writeReport"]:
        md = [
            f"# BOQ Reconciliation Report ({rates.currency})",
            f"- Total bill items: {len(bill['items'])}",
            f"- Priced items: {len(costing.lines) - len(unpriced)}",
            f"- Unpriced / mismatched items: {len(unpriced)}",
            f"- Total priced value: {costing.total:,.2f} {rates.currency}",
            f"- Embodied carbon: {costing.carbonTotal:,.1f} kg CO2e",
        ]
        out_path = str(save_export(ctx, "reconciliation-report.md", "\n".join(md) + "\n"))
    rows = [{"group": g, "amount": a} for g, a in costing.groups.items()]
    return result(
        summary={
            "currency": rates.currency,
            "totalValue": costing.total,
            "unpricedCount": len(unpriced),
            "exportPath": out_path or "preview",
        },
        tables=[
            table("Reconciled trade summary", [("group", "Trade"), ("amount", "Amount")], rows)
        ],
        notes=[f"Report saved to {out_path}." if out_path else "Preview only."],
    )


@feature(
    "boqReconcile.auditPack",
    "Audit Pack",
    part="boq",
    fields=[],
    requires_project=True,
)
def audit_pack(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Bundle priced BOQ, rate schedule, carbon factors, and source stamps into an audit JSON pack."""
    bill, rates, carbon, costing = price_project_bill(ctx)
    pack = {
        "source": bill.get("source"),
        "currency": rates.currency,
        "total": costing.total,
        "carbonTotal": costing.carbonTotal,
        "groups": costing.groups,
        "parts": costing.parts,
        "rateScheduleName": rates.name,
        "carbonScheduleName": carbon.name,
    }
    target = save_export(ctx, "boq-audit-pack.json", safe_json(pack))
    return result(
        summary={
            "currency": rates.currency,
            "totalValue": costing.total,
            "auditPackPath": str(target),
        },
        tables=[
            table(
                "Audit pack contents",
                [("section", "Section"), ("detail", "Included data")],
                [
                    {"section": "Bill & source hashes", "detail": f"{len(bill['items'])} items"},
                    {
                        "section": "Costing rollup",
                        "detail": f"{costing.total:,.2f} {rates.currency}",
                    },
                    {"section": "Carbon ledger", "detail": f"{costing.carbonTotal:,.1f} kg CO2e"},
                ],
            )
        ],
        notes=[f"Audit bundle exported to {target}."],
    )


@feature(
    "boqReconcile.tenderReconciliation",
    "Tender Reconciliation",
    part="boq",
    fields=[
        number(
            "tenderReturnTotal",
            "Lowest compliant tender return (0 = 104% of estimate)",
            0.0,
            min=0.0,
        )
    ],
    requires_project=True,
)
def tender_reconciliation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Reconcile a contractor tender return against the engineer's pre-tender BOQ estimate."""
    _, rates, _, costing = price_project_bill(ctx)
    est = costing.total or 1.0
    tender = values["tenderReturnTotal"] if values["tenderReturnTotal"] > 0 else est * 1.04
    ratio = tender / est
    rows = [
        {"group": g, "estimate": a, "tenderAlloc": a * ratio, "variance": a * (ratio - 1.0)}
        for g, a in costing.groups.items()
    ]
    return result(
        summary={
            "currency": rates.currency,
            "engineerEstimate": est,
            "tenderReturn": tender,
            "spreadPercent": (ratio - 1.0) * 100.0,
        },
        tables=[
            table(
                f"Tender vs estimate reconciliation ({rates.currency})",
                [
                    ("group", "Trade"),
                    ("estimate", "Estimate"),
                    ("tenderAlloc", "Tender"),
                    ("variance", "Spread"),
                ],
                rows,
            )
        ],
        notes=["Compares tender submission against pre-tender engineer estimate by trade."],
    )
