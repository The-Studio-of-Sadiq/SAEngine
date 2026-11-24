"""BOQ - Schedule tab: 4D programme generation, CPM scheduling, calendars, EVM & reports."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from saengine.boq import construction_schedule as cs
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
    load_schedule,
    price_project_bill,
    require_root,
    save_export,
)
from saengine.library.bim import BuildingModel


def _build_project_schedule(ctx: FeatureContext, start_iso: str = "") -> cs.ConstructionSchedule:
    saved = load_schedule(ctx)
    if saved is not None:
        return cs.schedule(saved)
    require_root(ctx, "building the construction programme")
    bim_raw = ctx.raw("bim")
    if not bim_raw:
        raise FeatureInputError(
            "Generate 06 BIM/bim.json before building the construction schedule."
        )
    building = BuildingModel.model_validate(bim_raw)
    bill = load_bill(ctx)
    prod, _ = load_productivity(ctx)
    when = date.fromisoformat(start_iso) if start_iso.strip() else date(2026, 1, 1)
    doc = cs.generate(building, bill, prod, when)
    return cs.schedule(doc)


@feature(
    "boqSchedule.activityDurations",
    "Activity Durations",
    part="boq",
    fields=[text("startDate", "Start date (YYYY-MM-DD)", "2026-01-01")],
    requires_project=True,
)
def activity_durations(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute working-day activity durations from BOQ quantities and crew productivity rates."""
    sched = _build_project_schedule(ctx, values["startDate"])
    rows = [
        {
            "id": a.id,
            "name": a.name,
            "category": a.category,
            "level": a.level or "-",
            "workingDays": a.working_days,
            "earlyStart": str(a.earlyStart),
            "earlyFinish": str(a.earlyFinish),
            "critical": a.critical,
        }
        for a in sched.activities
    ]
    return result(
        summary={
            "activityCount": len(rows),
            "criticalCount": sum(1 for r in rows if r["critical"]),
            "projectFinish": str(sched.finish),
        },
        tables=[
            table(
                "Construction activity durations",
                [
                    ("id", "ID"),
                    ("name", "Activity"),
                    ("level", "Level"),
                    ("workingDays", "Days"),
                    ("earlyStart", "Start"),
                    ("earlyFinish", "Finish"),
                    ("critical", "Critical"),
                ],
                rows,
            )
        ],
        notes=[
            "Durations computed as sum(quantity / (perDay * crews)) rounded up to whole working days."
        ],
    )


@feature(
    "boqSchedule.dependencies",
    "Dependencies",
    part="boq",
    fields=[],
    requires_project=True,
)
def dependencies(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect precedent logic links (FS/SS) and lags across the construction programme."""
    sched = _build_project_schedule(ctx)
    rows = []
    for a in sched.activities:
        for lk in a.links:
            rows.append(
                {
                    "from": lk.source,
                    "to": a.id,
                    "type": lk.type,
                    "lagDays": lk.lag,
                    "activity": a.name,
                }
            )
    return result(
        summary={"activityCount": len(sched.activities), "linkCount": len(rows)},
        tables=[
            table(
                "Precedence network links",
                [
                    ("from", "Predecessor"),
                    ("to", "Successor"),
                    ("type", "Type"),
                    ("lagDays", "Lag [d]"),
                    ("activity", "Successor name"),
                ],
                rows,
            )
        ],
        notes=[
            "Finish-to-start (FS) and start-to-start (SS) logic governs CPM forward/backward passes."
        ],
    )


@feature(
    "boqSchedule.resourceLevelling",
    "Resource Levelling",
    part="boq",
    fields=[
        number("maxCrewsPerDay", "Target maximum concurrent activities", 4.0, min=1.0, max=20.0)
    ],
    requires_project=True,
)
def resource_levelling(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate peak daily concurrent activity demand and non-critical float slack for levelling."""
    sched = _build_project_schedule(ctx)
    cap = round(values["maxCrewsPerDay"])
    day_load: dict[date, int] = {}
    for a in sched.activities:
        if a.earlyStart and a.earlyFinish:
            d = a.earlyStart
            while d <= a.earlyFinish:
                day_load[d] = day_load.get(d, 0) + 1
                d += timedelta(days=1)
    peak = max(day_load.values()) if day_load else 0
    over_days = sum(1 for v in day_load.values() if v > cap)
    shiftable = [
        {
            "id": a.id,
            "name": a.name,
            "totalFloatDays": a.totalFloat or 0.0,
            "workingDays": a.working_days,
        }
        for a in sched.activities
        if (a.totalFloat or 0.0) > 0
    ]
    return result(
        summary={
            "peakConcurrent": peak,
            "targetMax": cap,
            "overAllocatedDays": over_days,
            "shiftableActivities": len(shiftable),
        },
        tables=[
            table(
                "Activities with positive float for levelling",
                [
                    ("id", "ID"),
                    ("name", "Activity"),
                    ("totalFloatDays", "Total float [d]"),
                    ("workingDays", "Duration [d]"),
                ],
                shiftable,
            )
        ],
        notes=[
            "Non-critical activities with positive total float can shift without delaying project completion."
        ],
    )


@feature(
    "boqSchedule.baseline",
    "Baseline",
    part="boq",
    fields=[checkbox("exportBaseline", "Save/update baseline snapshot in 10 BOQ/exports", False)],
    requires_project=True,
)
def baseline(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Capture the CPM baseline programme and compute schedule variance against any saved baseline."""
    import json

    sched = _build_project_schedule(ctx)
    base_json = ctx.path("10 BOQ/exports/schedule-baseline.json")
    prev_finishes: dict[str, str] = {}
    if base_json is not None and base_json.exists():
        try:
            loaded = json.loads(base_json.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("activities"), list):
                prev_finishes = {
                    str(r.get("id", "")): str(r.get("finish", ""))
                    for r in loaded["activities"]
                    if isinstance(r, dict)
                }
        except ValueError:
            prev_finishes = {}
    rows = []
    slipped = 0
    for a in sched.activities:
        fin = str(a.earlyFinish)
        prev_fin = prev_finishes.get(a.id, fin)
        variance_d = (
            (date.fromisoformat(fin) - date.fromisoformat(prev_fin)).days if prev_fin else 0
        )
        if variance_d > 0:
            slipped += 1
        rows.append(
            {
                "id": a.id,
                "name": a.name,
                "start": str(a.earlyStart),
                "finish": fin,
                "baselineFinish": prev_fin,
                "varianceDays": variance_d,
                "float": a.totalFloat or 0.0,
                "critical": a.critical,
            }
        )
    out_path = ""
    if values["exportBaseline"]:
        save_export(
            ctx,
            "schedule-baseline.json",
            json.dumps(
                {"start": str(sched.start), "finish": str(sched.finish), "activities": rows},
                indent=2,
            )
            + "\n",
        )
        out_path = str(save_export(ctx, "schedule-baseline.csv", cs.to_csv(sched)))
    return result(
        summary={
            "baselineStart": str(sched.start),
            "baselineFinish": str(sched.finish),
            "activities": len(rows),
            "slippedActivities": slipped,
            "exportPath": out_path or "preview",
        },
        tables=[
            table(
                "Programme baseline & variance",
                [
                    ("id", "ID"),
                    ("name", "Activity"),
                    ("start", "Start"),
                    ("finish", "Finish"),
                    ("varianceDays", "Var [d]"),
                    ("float", "Float [d]"),
                    ("critical", "Critical"),
                ],
                rows,
            )
        ],
        notes=[
            "Critical activities carry zero total float; variance compares against saved schedule-baseline.json."
        ],
    )


@feature(
    "boqSchedule.sCurve",
    "S-Curve",
    part="boq",
    fields=[number("intervals", "Number of reporting periods", 10.0, min=4.0, max=24.0)],
    requires_project=True,
)
def s_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Plot cumulative planned value S-curve across the CPM construction schedule."""
    sched = _build_project_schedule(ctx)
    _, rates, _, costing = price_project_bill(ctx)
    n = round(values["intervals"])
    start = sched.start
    end = sched.finish or (start + timedelta(days=30))
    span_days = max(1, (end - start).days)
    tot_days = sum(max(1, a.working_days) for a in sched.activities) or 1
    rows = []
    for i in range(1, n + 1):
        cutoff = start + timedelta(days=round(span_days * i / n))
        done_weight = 0.0
        for a in sched.activities:
            s = a.earlyStart or start
            e = a.earlyFinish or s
            dur = max(1, (e - s).days + 1)
            if cutoff >= e:
                frac = 1.0
            elif cutoff < s:
                frac = 0.0
            else:
                frac = ((cutoff - s).days + 1) / dur
            done_weight += frac * max(1, a.working_days)
        pct = done_weight / tot_days * 100.0
        rows.append(
            {
                "period": i,
                "date": str(cutoff),
                "plannedPct": pct,
                "plannedValue": costing.total * pct / 100.0,
            }
        )
    return result(
        summary={"currency": rates.currency, "totalPlannedValue": costing.total, "periods": n},
        tables=[
            table(
                f"Planned cost S-curve ({rates.currency})",
                [
                    ("period", "Period"),
                    ("date", "Date"),
                    ("plannedPct", "Planned", "%"),
                    ("plannedValue", "Cum value"),
                ],
                rows,
            )
        ],
        notes=["Distributes priced BOQ value across scheduled activity duration windows."],
    )


@feature(
    "boqSchedule.earnedValue",
    "Earned Value",
    part="boq",
    fields=[
        number("bac", "Budget at Completion BAC (0 = project total)", 0.0, min=0.0),
        number("plannedPct", "Planned progress PV %", 45.0, unit="%", min=0.0, max=100.0),
        number("earnedPct", "Earned progress EV %", 40.0, unit="%", min=0.0, max=100.0),
        number("actualCostPct", "Actual spend AC % of BAC", 43.0, unit="%", min=0.0, max=200.0),
    ],
    requires_project=False,
)
def earned_value(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute Earned Value Management (EVM) variances and CPI/SPI/EAC forecasts."""
    bac = values["bac"]
    if bac <= 0:
        if ctx.root is not None and load_bill(ctx) is not None:
            _, _, _, costing = price_project_bill(ctx)
            bac = costing.total
        else:
            bac = 10000000.0
    pv = bac * values["plannedPct"] / 100.0
    ev = bac * values["earnedPct"] / 100.0
    ac = bac * values["actualCostPct"] / 100.0
    sv = ev - pv
    cv = ev - ac
    spi = ev / pv if pv > 0 else 1.0
    cpi = ev / ac if ac > 0 else 1.0
    eac = bac / cpi if cpi > 0 else bac
    rows = [
        {"metric": "Budget at Completion (BAC)", "value": bac},
        {"metric": "Planned Value (PV)", "value": pv},
        {"metric": "Earned Value (EV)", "value": ev},
        {"metric": "Actual Cost (AC)", "value": ac},
        {"metric": "Schedule Variance (SV = EV - PV)", "value": sv},
        {"metric": "Cost Variance (CV = EV - AC)", "value": cv},
        {"metric": "Schedule Performance Index (SPI)", "value": spi},
        {"metric": "Cost Performance Index (CPI)", "value": cpi},
        {"metric": "Estimate at Completion (EAC = BAC/CPI)", "value": eac},
    ]
    return result(
        summary={
            "bac": bac,
            "spi": spi,
            "cpi": cpi,
            "scheduleVariance": sv,
            "costVariance": cv,
            "eac": eac,
        },
        tables=[
            table("Earned value metrics", [("metric", "EVM metric"), ("value", "Value")], rows)
        ],
        notes=["Uses standard PMI EVM definitions: SPI = EV/PV, CPI = EV/AC, EAC = BAC/CPI."],
    )


@feature(
    "boqSchedule.workCalendar",
    "Work Calendar",
    part="boq",
    fields=[
        select(
            "workWeek",
            "Working days per week",
            [("6", "6 days (Sat-Thu)"), ("5", "5 days (Mon-Fri)"), ("7", "7 days continuous")],
            "6",
        ),
        number("calendarDaysSpan", "Calendar span to evaluate", 180.0, unit="days", min=7.0),
        number("holidaysCount", "Public holidays in period", 6.0, min=0.0),
    ],
    requires_project=False,
)
def work_calendar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate net working days available from work-week pattern and public holiday deductions."""
    wdays_map = {
        "6": ["sat", "sun", "mon", "tue", "wed", "thu"],
        "5": ["mon", "tue", "wed", "thu", "fri"],
        "7": list(cs.WEEKDAYS),
    }
    cal = cs.Calendar(date(2026, 1, 1), wdays_map[values["workWeek"]], [])
    span = round(values["calendarDaysSpan"])
    gross_work = sum(1 for i in range(span) if cal.working(date(2026, 1, 1) + timedelta(days=i)))
    net_work = max(0, gross_work - round(values["holidaysCount"]))
    return result(
        summary={
            "calendarDays": span,
            "grossWorkingDays": gross_work,
            "netWorkingDays": net_work,
            "efficiencyRatio": net_work / span,
        },
        tables=[
            table(
                "Working-day calendar summary",
                [("item", "Metric"), ("days", "Days")],
                [
                    {"item": "Calendar span", "days": span},
                    {"item": "Scheduled working days", "days": gross_work},
                    {"item": "Public holidays", "days": round(values["holidaysCount"])},
                    {"item": "Net productive days", "days": net_work},
                ],
            )
        ],
        notes=["Uses engine working-day calendar rules."],
    )


@feature(
    "boqSchedule.shiftPatterns",
    "Shift Patterns",
    part="boq",
    fields=[
        number("baseDurationDays", "Single-shift activity duration", 24.0, unit="days", min=1.0),
        select(
            "shifts",
            "Shift pattern",
            [
                ("1", "Single shift (8 hr/day)"),
                ("2", "Double shift (16 hr/day, 85% 2nd shift eff.)"),
                ("3", "24/7 three shifts (80% night eff.)"),
            ],
            "2",
        ),
    ],
    requires_project=False,
)
def shift_patterns(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adjust activity durations for single, double, or continuous shift working efficiencies."""
    eff_map = {"1": 1.0, "2": 1.85, "3": 2.60}
    mult = eff_map[values["shifts"]]
    new_days = math.ceil(values["baseDurationDays"] / mult)
    return result(
        summary={
            "shifts": int(values["shifts"]),
            "effectiveMultiplier": mult,
            "adjustedDays": new_days,
            "daysSaved": values["baseDurationDays"] - new_days,
        },
        tables=[
            table(
                "Shift duration comparison",
                [("pattern", "Pattern"), ("multiplier", "Output factor"), ("days", "Duration [d]")],
                [
                    {
                        "pattern": "1 shift",
                        "multiplier": 1.0,
                        "days": math.ceil(values["baseDurationDays"]),
                    },
                    {
                        "pattern": "2 shifts",
                        "multiplier": 1.85,
                        "days": math.ceil(values["baseDurationDays"] / 1.85),
                    },
                    {
                        "pattern": "3 shifts",
                        "multiplier": 2.60,
                        "days": math.ceil(values["baseDurationDays"] / 2.60),
                    },
                ],
            )
        ],
        notes=["Accounts for night/second-shift handover and lighting efficiency losses."],
    )


@feature(
    "boqSchedule.holidaySet",
    "Holiday Set",
    part="boq",
    fields=[
        text(
            "holidaysCsv",
            "Holiday dates (YYYY-MM-DD, comma/newline separated)",
            "2026-02-21, 2026-03-26, 2026-05-01, 2026-12-16",
        ),
    ],
    requires_project=False,
)
def holiday_set(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate a public holiday calendar set against working weekdays."""
    tokens = [t.strip() for t in values["holidaysCsv"].replace("\n", ",").split(",") if t.strip()]
    rows = []
    for tok in tokens:
        try:
            d = date.fromisoformat(tok)
        except ValueError as exc:
            raise FeatureInputError(f"Invalid ISO date '{tok}' (use YYYY-MM-DD).") from exc
        rows.append({"date": str(d), "weekday": d.strftime("%A"), "onWorkday": d.weekday() != 4})
    return result(
        summary={
            "holidayCount": len(rows),
            "workdayHolidays": sum(1 for r in rows if r["onWorkday"]),
        },
        tables=[
            table(
                "Holiday calendar table",
                [("date", "Date"), ("weekday", "Weekday"), ("onWorkday", "Impacts work")],
                rows,
            )
        ],
        notes=["Validates ISO holiday dates for exclusion in the CPM working-day calendar."],
    )


@feature(
    "boqSchedule.weatherDays",
    "Weather Days",
    part="boq",
    fields=[
        number("outdoorDays", "Exposed outdoor activity duration", 60.0, unit="days", min=1.0),
        number(
            "rainProbPct", "Expected monthly rain delay rate", 12.0, unit="%", min=0.0, max=60.0
        ),
    ],
    requires_project=False,
)
def weather_days(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute weather downtime allowance days for exposed earthwork, concreting, and facade activities."""
    allowance = math.ceil(values["outdoorDays"] * values["rainProbPct"] / 100.0)
    total = values["outdoorDays"] + allowance
    return result(
        summary={
            "baseOutdoorDays": values["outdoorDays"],
            "weatherAllowanceDays": allowance,
            "adjustedDays": total,
        },
        tables=[
            table(
                "Weather contingency calculation",
                [("item", "Item"), ("days", "Working days")],
                [
                    {"item": "Base unadjusted duration", "days": values["outdoorDays"]},
                    {"item": f"Weather allowance ({values['rainProbPct']:g}%)", "days": allowance},
                    {"item": "Weather-adjusted duration", "days": total},
                ],
            )
        ],
        notes=[
            "Adds rounded-up non-productive inclement weather days to exposed external activities."
        ],
    )


@feature(
    "boqSchedule.costLoadAssign",
    "Cost Load Assign",
    part="boq",
    fields=[],
    requires_project=True,
)
def cost_load_assign(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign BOQ item costs to scheduled construction activities by element category."""
    sched = _build_project_schedule(ctx)
    _, rates, _, costing = price_project_bill(ctx)
    by_cat: dict[str, float] = {}
    for li in costing.lines:
        amt = li.amount or 0.0
        cat = (
            "foundations"
            if li.group == "earthwork"
            else (
                "finishes"
                if li.group in ("masonry", "finishes")
                else ("mep" if li.group == "mep" else "floor")
            )
        )
        by_cat[cat] = by_cat.get(cat, 0.0) + amt
    cat_acts: dict[str, int] = {}
    for a in sched.activities:
        cat_acts[a.category] = cat_acts.get(a.category, 0) + 1
    rows = []
    for a in sched.activities:
        share = by_cat.get(a.category, costing.total / max(1, len(sched.activities))) / max(
            1, cat_acts.get(a.category, 1)
        )
        rows.append({"id": a.id, "name": a.name, "category": a.category, "assignedCost": share})
    return result(
        summary={
            "currency": rates.currency,
            "activitiesCostLoaded": len(rows),
            "totalLoaded": sum(r["assignedCost"] for r in rows),
        },
        tables=[
            table(
                f"Cost-loaded schedule ({rates.currency})",
                [
                    ("id", "ID"),
                    ("name", "Activity"),
                    ("category", "Category"),
                    ("assignedCost", "Cost"),
                ],
                rows,
            )
        ],
        notes=["Distributes priced BOQ categories across matching programme activities."],
    )


@feature(
    "boqSchedule.paymentCurve",
    "Payment Curve",
    part="boq",
    fields=[
        number(
            "paymentLagDays", "Certification & payment lag", 30.0, unit="days", min=0.0, max=90.0
        )
    ],
    requires_project=True,
)
def payment_curve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate lagged employer payment disbursement curve from the scheduled construction progress."""
    sched = _build_project_schedule(ctx)
    _, rates, _, costing = price_project_bill(ctx)
    lag = round(values["paymentLagDays"])
    rows = []
    tot_days = sum(max(1, a.working_days) for a in sched.activities) or 1
    cum = 0.0
    for idx, a in enumerate(sched.activities, 1):
        cum += max(1, a.working_days) / tot_days
        pay_date = (a.earlyFinish or sched.start) + timedelta(days=lag)
        rows.append(
            {
                "step": idx,
                "activity": a.name,
                "payDate": str(pay_date),
                "cumPayment": costing.total * cum,
            }
        )
    return result(
        summary={"currency": rates.currency, "totalPayable": costing.total, "paymentLagDays": lag},
        tables=[
            table(
                f"Lagged payment curve ({rates.currency})",
                [
                    ("step", "#"),
                    ("activity", "Milestone"),
                    ("payDate", "Payment date"),
                    ("cumPayment", "Cumulative"),
                ],
                rows[:25],
            )
        ],
        notes=[
            f"Shifts activity completion dates by {lag} calendar days for valuation and payment processing."
        ],
    )


@feature(
    "boqSchedule.milestonePayments",
    "Milestone Payments",
    part="boq",
    fields=[
        number(
            "substructurePct", "Substructure complete milestone", 20.0, unit="%", min=0.0, max=100.0
        ),
        number("framePct", "Structural frame topped out", 45.0, unit="%", min=0.0, max=100.0),
        number("envelopePct", "Masonry & envelope complete", 20.0, unit="%", min=0.0, max=100.0),
        number("handoverPct", "MEP & final handover", 15.0, unit="%", min=0.0, max=100.0),
    ],
    requires_project=True,
)
def milestone_payments(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedule stage milestone payment tranches against project contract value."""
    _, rates, _, costing = price_project_bill(ctx)
    pcts = [
        values["substructurePct"],
        values["framePct"],
        values["envelopePct"],
        values["handoverPct"],
    ]
    tot_pct = sum(pcts) or 100.0
    names = [
        "M1: Substructure complete",
        "M2: Structural frame topped out",
        "M3: Envelope & masonry",
        "M4: MEP & practical completion",
    ]
    rows = [
        {
            "milestone": nm,
            "sharePct": p / tot_pct * 100.0,
            "paymentAmount": costing.total * p / tot_pct,
        }
        for nm, p in zip(names, pcts, strict=True)
    ]
    return result(
        summary={
            "currency": rates.currency,
            "totalContractValue": costing.total,
            "milestoneCount": 4,
        },
        tables=[
            table(
                f"Milestone payment schedule ({rates.currency})",
                [
                    ("milestone", "Milestone"),
                    ("sharePct", "Share", "%"),
                    ("paymentAmount", "Payment"),
                ],
                rows,
            )
        ],
        notes=["Percentages normalized to 100% of priced BOQ total."],
    )


@feature(
    "boqSchedule.retentionRelease",
    "Retention Release",
    part="boq",
    fields=[
        number("retentionPct", "Retention percentage", 5.0, unit="%", min=0.0, max=15.0),
        number("defectsMonths", "Defects liability period", 12.0, unit="months", min=3.0, max=36.0),
    ],
    requires_project=True,
)
def retention_release(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate practical-completion and final defects-liability retention release dates and sums."""
    sched = _build_project_schedule(ctx)
    _, rates, _, costing = price_project_bill(ctx)
    pc_date = sched.finish or sched.start
    dlp_date = pc_date + timedelta(days=round(values["defectsMonths"] * 30.4375))
    ret_total = costing.total * values["retentionPct"] / 100.0
    half = ret_total / 2.0
    rows = [
        {
            "tranche": "1st moiety (50% at Practical Completion)",
            "releaseDate": str(pc_date),
            "amount": half,
        },
        {
            "tranche": f"2nd moiety (50% after {values['defectsMonths']:g} mo DLP)",
            "releaseDate": str(dlp_date),
            "amount": half,
        },
    ]
    return result(
        summary={
            "currency": rates.currency,
            "totalRetention": ret_total,
            "firstReleaseDate": str(pc_date),
            "finalReleaseDate": str(dlp_date),
        },
        tables=[
            table(
                f"Retention release schedule ({rates.currency})",
                [("tranche", "Release tranche"), ("releaseDate", "Date"), ("amount", "Amount")],
                rows,
            )
        ],
        notes=["Splits retention 50% at practical completion and 50% upon defects certificate."],
    )


@feature(
    "boqSchedule.resourceHistogram",
    "Resource Histogram",
    part="boq",
    fields=[],
    requires_project=True,
)
def resource_histogram(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build weekly active crew-demand histogram across the construction programme."""
    sched = _build_project_schedule(ctx)
    weeks: dict[int, int] = {}
    for a in sched.activities:
        if not (a.earlyStart and a.earlyFinish):
            continue
        w0 = max(0, (a.earlyStart - sched.start).days // 7)
        w1 = max(w0, (a.earlyFinish - sched.start).days // 7)
        for w in range(w0, w1 + 1):
            weeks[w] = weeks.get(w, 0) + 1
    rows = [
        {"week": w + 1, "activeActivities": c, "estimatedWorkers": c * 6}
        for w, c in sorted(weeks.items())
    ]
    return result(
        summary={
            "totalWeeks": len(rows),
            "peakActiveActivities": max((r["activeActivities"] for r in rows), default=0),
            "peakWorkers": max((r["estimatedWorkers"] for r in rows), default=0),
        },
        tables=[
            table(
                "Weekly resource demand histogram",
                [
                    ("week", "Week #"),
                    ("activeActivities", "Active tasks"),
                    ("estimatedWorkers", "Est. site crew"),
                ],
                rows,
            )
        ],
        notes=["Estimates 6 site operatives per concurrent active trade workface."],
    )


@feature(
    "boqSchedule.crewAllocation",
    "Crew Allocation",
    part="boq",
    fields=[],
    requires_project=True,
)
def crew_allocation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate crew allocations and crew-days required per trade productivity rule."""
    prod, _ = load_productivity(ctx)
    sched = _build_project_schedule(ctx)
    by_rate: dict[str, float] = {}
    for a in sched.activities:
        for q in a.quantities:
            rid = q.rate or "unassigned"
            by_rate[rid] = by_rate.get(rid, 0.0) + q.days
    rows = [
        {
            "rateId": r.id,
            "description": r.description,
            "crews": r.crews,
            "perDay": r.perDay,
            "unit": r.unit,
            "scheduledDays": by_rate.get(r.id, 0.0),
        }
        for r in prod.rates
    ]
    return result(
        summary={
            "productivityRules": len(rows),
            "totalCrewDays": sum(r["scheduledDays"] for r in rows),
        },
        tables=[
            table(
                "Crew allocation summary",
                [
                    ("rateId", "Trade"),
                    ("description", "Operation"),
                    ("crews", "Crews"),
                    ("perDay", "Output/day"),
                    ("unit", "Unit"),
                    ("scheduledDays", "Scheduled days"),
                ],
                rows,
            )
        ],
        notes=["Uses output rates from 10 BOQ/productivity.json or office sample."],
    )


@feature(
    "boqSchedule.plantAllocation",
    "Plant Allocation",
    part="boq",
    fields=[
        number(
            "craneHoursPerFloor", "Tower crane / hoist hours per floor", 28.0, unit="hr", min=1.0
        )
    ],
    requires_project=True,
)
def plant_allocation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Allocate major plant items (crane, concrete pump, excavator) to scheduled activities."""
    sched = _build_project_schedule(ctx)
    rows = []
    tot_hrs = 0.0
    for a in sched.activities:
        plant = (
            "Excavator"
            if a.category in ("excavation", "backfill")
            else (
                "Piling Rig"
                if a.category == "piles"
                else (
                    "Concrete Pump & Crane"
                    if a.category in ("vertical", "floor", "foundations")
                    else "Hoist"
                )
            )
        )
        hrs = values["craneHoursPerFloor"] if a.category == "floor" else a.working_days * 6.0
        tot_hrs += hrs
        rows.append({"activity": a.name, "plant": plant, "days": a.working_days, "plantHours": hrs})
    return result(
        summary={"activities": len(rows), "totalPlantHours": tot_hrs},
        tables=[
            table(
                "Major plant allocation schedule",
                [
                    ("activity", "Activity"),
                    ("plant", "Primary plant"),
                    ("days", "Days"),
                    ("plantHours", "Est. hours", "hr"),
                ],
                rows[:30],
            )
        ],
        notes=["Maps activity categories to primary mechanical plant requirements."],
    )


@feature(
    "boqSchedule.overAllocationAlerts",
    "Over Allocation Alerts",
    part="boq",
    fields=[number("dailyCrewLimit", "Site crew capacity limit (concurrent tasks)", 3.0, min=1.0)],
    requires_project=True,
)
def over_allocation_alerts(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify calendar dates where concurrent activities exceed available site crew capacity."""
    sched = _build_project_schedule(ctx)
    limit = round(values["dailyCrewLimit"])
    counts: dict[date, list[str]] = {}
    for a in sched.activities:
        if a.earlyStart and a.earlyFinish:
            d = a.earlyStart
            while d <= a.earlyFinish:
                counts.setdefault(d, []).append(a.id)
                d += timedelta(days=1)
    alerts = [
        {"date": str(d), "concurrent": len(ids), "activities": ", ".join(ids[:6])}
        for d, ids in sorted(counts.items())
        if len(ids) > limit
    ]
    return result(
        summary={
            "crewLimit": limit,
            "overAllocatedDays": len(alerts),
            "peakConcurrent": max((len(v) for v in counts.values()), default=0),
        },
        tables=[
            table(
                "Resource over-allocation alerts",
                [("date", "Date"), ("concurrent", "Tasks"), ("activities", "Overlapping IDs")],
                alerts[:30]
                or [{"date": "-", "concurrent": 0, "activities": "No over-allocations"}],
            )
        ],
        notes=["Flags days exceeding the specified concurrent task threshold."],
    )


@feature(
    "boqSchedule.scheduleReport",
    "Schedule Report",
    part="boq",
    fields=[
        select("format", "Export format", [("csv", "CSV schedule"), ("xml", "MSPDI XML")], "csv"),
        checkbox("writeFile", "Write export file to 10 BOQ/exports", True),
    ],
    requires_project=True,
)
def schedule_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the full CPM construction schedule with early dates, total float, and critical flags."""
    sched = _build_project_schedule(ctx)
    out_path = ""
    if values["writeFile"]:
        if values["format"] == "csv":
            out_path = str(save_export(ctx, "construction-schedule.csv", cs.to_csv(sched)))
        else:
            out_path = str(save_export(ctx, "construction-schedule.xml", cs.to_mspdi(sched)))
    rows = [
        {
            "id": a.id,
            "name": a.name,
            "start": str(a.earlyStart),
            "finish": str(a.earlyFinish),
            "critical": a.critical,
        }
        for a in sched.activities[:30]
    ]
    return result(
        summary={
            "activities": len(sched.activities),
            "finishDate": str(sched.finish),
            "exportPath": out_path or "preview",
        },
        tables=[
            table(
                "Schedule export preview",
                [
                    ("id", "ID"),
                    ("name", "Activity"),
                    ("start", "Start"),
                    ("finish", "Finish"),
                    ("critical", "Critical"),
                ],
                rows,
            )
        ],
        notes=[f"Exported to {out_path}." if out_path else "Preview only."],
    )


@feature(
    "boqSchedule.progressPhotos",
    "Progress Photos",
    part="boq",
    fields=[
        text("activityId", "Activity ID (blank = first)", ""),
        text("photoRef", "Site photo filename / tag", "IMG_L1_SLAB_01.jpg"),
    ],
    requires_project=True,
)
def progress_photos(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a progress photo evidence log linked to scheduled construction activities and BIM elements."""
    sched = _build_project_schedule(ctx)
    aid = values["activityId"].strip()
    act = (
        next((a for a in sched.activities if a.id.lower() == aid.lower()), None)
        if aid
        else (sched.activities[0] if sched.activities else None)
    )
    if act is None:
        raise FeatureInputError("No matching construction activity found.")
    row = {
        "activityId": act.id,
        "activity": act.name,
        "elements": ", ".join(act.elements[:6]),
        "photoTag": values["photoRef"].strip(),
    }
    return result(
        summary={
            "activityId": act.id,
            "linkedElements": len(act.elements),
            "photoTag": row["photoTag"],
        },
        tables=[
            table(
                "Site progress evidence record",
                [
                    ("activityId", "Activity ID"),
                    ("activity", "Name"),
                    ("elements", "BIM elements"),
                    ("photoTag", "Photo ref"),
                ],
                [row],
            )
        ],
        notes=["Links site inspection photo tags to BIM element IDs in the 4D schedule."],
    )


@feature(
    "boqSchedule.lookaheadPlan",
    "Lookahead Plan",
    part="boq",
    fields=[
        number("lookaheadWeeks", "Rolling lookahead window", 4.0, unit="weeks", min=1.0, max=12.0)
    ],
    requires_project=True,
)
def lookahead_plan(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a rolling N-week lookahead plan of upcoming site activities from project start."""
    sched = _build_project_schedule(ctx)
    horizon = sched.start + timedelta(weeks=round(values["lookaheadWeeks"]))
    rows = [
        {
            "id": a.id,
            "name": a.name,
            "start": str(a.earlyStart),
            "finish": str(a.earlyFinish),
            "days": a.working_days,
            "critical": a.critical,
        }
        for a in sched.activities
        if a.earlyStart is not None and a.earlyStart <= horizon
    ]
    return result(
        summary={
            "windowWeeks": round(values["lookaheadWeeks"]),
            "horizonDate": str(horizon),
            "upcomingActivities": len(rows),
        },
        tables=[
            table(
                f"{round(values['lookaheadWeeks'])}-week rolling lookahead",
                [
                    ("id", "ID"),
                    ("name", "Activity"),
                    ("start", "Start"),
                    ("finish", "Finish"),
                    ("days", "Days"),
                    ("critical", "Critical"),
                ],
                rows,
            )
        ],
        notes=[f"Lists all activities starting on or before {horizon}."],
    )
