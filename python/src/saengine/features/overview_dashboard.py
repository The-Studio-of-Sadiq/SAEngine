"""Overview dashboard widget and alert commands."""

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
from saengine.features.overview_common import (
    boq_items,
    list_bim,
    list_objects,
    load_export_json,
    now_iso,
    project_kpis,
    project_name,
    require_project,
    save_export_json,
    write_export,
)


def _load_dashboard(ctx: FeatureContext) -> dict[str, Any]:
    data = load_export_json(ctx, "11 Exports", "dashboard-state.json", {})
    if not isinstance(data, dict):
        return {}
    return data


@feature(
    "overviewDashboard.addKpi",
    "Add KPI",
    part="settings",
    fields=[text("name", "KPI name", ""), number("kpiValue", "KPI value", 0.0, unit="value")],
    requires_project=True,
)
def add_kpi(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Store a KPI in persistent dashboard state and compare against any existing target."""
    kpi_name = values["name"].strip()
    if not kpi_name:
        raise FeatureInputError("Enter a KPI name.")
    state = _load_dashboard(ctx)
    kpis = state.setdefault("kpis", {})
    targets = state.get("targets", {})
    val = float(values["kpiValue"])
    target = targets.get(kpi_name)
    variance = round(val - float(target), 3) if isinstance(target, (int, float)) else None
    kpis[kpi_name] = {
        "name": kpi_name,
        "value": val,
        "target": target,
        "variance": variance,
        "updatedAt": now_iso(),
    }
    path = save_export_json(ctx, "11 Exports", "dashboard-state.json", state)
    rows = list(kpis.values())
    return result(
        summary={"name": kpi_name, "value": val, "kpiCount": len(rows), "exportPath": str(path)},
        tables=[
            table(
                "Dashboard KPIs",
                [
                    ("name", "KPI"),
                    ("value", "Value"),
                    ("target", "Target"),
                    ("variance", "Variance"),
                ],
                rows,
            )
        ],
    )


@feature(
    "overviewDashboard.setTarget",
    "Set Target",
    part="settings",
    fields=[text("kpi", "KPI name", ""), number("target", "Target", 100.0, unit="value")],
    requires_project=True,
)
def set_target(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set a KPI target and evaluate variance against stored or live project KPI values."""
    kpi_name = values["kpi"].strip()
    if not kpi_name:
        raise FeatureInputError("Enter a KPI name to assign a target.")
    state = _load_dashboard(ctx)
    targets = state.setdefault("targets", {})
    target_val = float(values["target"])
    targets[kpi_name] = target_val
    live = project_kpis(ctx)
    kpis = state.setdefault("kpis", {})
    actual = kpis[kpi_name]["value"] if kpi_name in kpis else live.get(kpi_name)
    variance = round(float(actual) - target_val, 3) if isinstance(actual, (int, float)) else None
    if kpi_name in kpis:
        kpis[kpi_name]["target"] = target_val
        kpis[kpi_name]["variance"] = variance
    path = save_export_json(ctx, "11 Exports", "dashboard-state.json", state)
    rows = [
        {"kpi": k, "target": v, "actual": kpis.get(k, {}).get("value", live.get(k))}
        for k, v in sorted(targets.items())
    ]
    return result(
        summary={
            "kpi": kpi_name,
            "target": target_val,
            "variance": variance,
            "targetCount": len(rows),
            "exportPath": str(path),
        },
        tables=[
            table("KPI targets", [("kpi", "KPI"), ("actual", "Actual"), ("target", "Target")], rows)
        ],
    )


@feature(
    "overviewDashboard.showTrend",
    "Show Trend",
    part="settings",
    fields=[text("values", "Comma-separated values", "10,12,11,15")],
    requires_project=False,
)
def show_trend(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert a numeric series into trend rows and slope."""
    try:
        series = [float(item.strip()) for item in values["values"].split(",") if item.strip()]
    except ValueError:
        raise FeatureInputError("Enter comma-separated numeric values.") from None
    if not series:
        raise FeatureInputError("Enter at least one numeric value.")
    rows = [{"index": i + 1, "value": value} for i, value in enumerate(series)]
    delta = series[-1] - series[0]
    return result(
        summary={"pointCount": len(series), "start": series[0], "end": series[-1], "delta": delta},
        tables=[table("Trend", [("index", "Point"), ("value", "Value")], rows)],
    )


@feature(
    "overviewDashboard.refreshKpis",
    "Refresh KPIs",
    part="settings",
    fields=[],
    requires_project=True,
)
def refresh_kpis(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Refresh KPI values directly from project counts."""
    require_project(ctx, "refreshing KPIs")
    elements, stories = list_bim(ctx)
    rows = [
        {"kpi": "Parts", "value": len(list_objects(ctx))},
        {"kpi": "BIM elements", "value": len(elements)},
        {"kpi": "Stories", "value": len(stories)},
        {"kpi": "BOQ items", "value": len(boq_items(ctx))},
    ]
    return result(
        summary={"kpiCount": len(rows), "valueCount": sum(r["value"] for r in rows)},
        tables=[table("Dashboard KPIs", [("kpi", "KPI"), ("value", "Value")], rows)],
    )


@feature(
    "overviewDashboard.projectChart",
    "Project Chart",
    part="settings",
    fields=[],
    requires_project=True,
)
def project_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Chart project counts by source part."""
    require_project(ctx, "building a project chart")
    elements, _ = list_bim(ctx)
    rows = [
        {"part": "Objects", "count": len(list_objects(ctx))},
        {"part": "BIM", "count": len(elements)},
        {"part": "BOQ", "count": len(boq_items(ctx))},
    ]
    return result(
        summary={"seriesCount": len(rows)},
        tables=[table("Project chart", [("part", "Part"), ("count", "Count")], rows)],
    )


@feature(
    "overviewDashboard.progressChart",
    "Progress Chart",
    part="settings",
    fields=[text("parts", "part=percent comma-separated", "Soil=100,Objects=75")],
    requires_project=False,
)
def progress_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert part progress values into chart rows."""
    rows = []
    for item in values["parts"].split(","):
        if "=" not in item:
            continue
        name, percent = item.split("=", 1)
        try:
            rows.append({"part": name.strip(), "progress": float(percent)})
        except ValueError:
            raise FeatureInputError("Use part=percent pairs separated by commas.") from None
    return result(
        summary={
            "partCount": len(rows),
            "averagePercent": sum(r["progress"] for r in rows) / len(rows) if rows else 0.0,
        },
        tables=[table("Progress chart", [("part", "Part"), ("progress", "Progress", "%")], rows)],
    )


@feature(
    "overviewDashboard.customChart",
    "Custom Chart",
    part="settings",
    fields=[text("labels", "Labels", "A,B,C"), text("values", "Values", "1,2,3")],
    requires_project=False,
)
def custom_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Pair labels and numeric values into chart rows."""
    labels = [item.strip() for item in values["labels"].split(",")]
    try:
        numbers = [float(item.strip()) for item in values["values"].split(",")]
    except ValueError:
        raise FeatureInputError("Values must be comma-separated numbers.") from None
    if len(labels) != len(numbers):
        raise FeatureInputError("Labels and values must contain the same number of entries.")
    rows = [{"label": label, "value": number} for label, number in zip(labels, numbers)]
    return result(
        summary={"pointCount": len(rows)},
        tables=[table("Custom chart", [("label", "Label"), ("value", "Value")], rows)],
    )


@feature(
    "overviewDashboard.arrangeLayout",
    "Arrange Layout",
    part="settings",
    fields=[text("layout", "Layout name", "Engineering overview")],
    requires_project=True,
)
def arrange_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Update active dashboard layout and compute widget grid slot allocation."""
    layout_name = values["layout"].strip() or "Engineering overview"
    state = _load_dashboard(ctx)
    widgets = state.get("widgets", [])
    columns = 2 if len(widgets) <= 4 else 3
    rows = max(1, (len(widgets) + columns - 1) // columns)
    state["layout"] = {
        "name": layout_name,
        "columns": columns,
        "rows": rows,
        "updatedAt": now_iso(),
    }
    path = save_export_json(ctx, "11 Exports", "dashboard-state.json", state)
    return result(
        summary={
            "layout": layout_name,
            "widgetCount": len(widgets),
            "columns": columns,
            "rows": rows,
            "exportPath": str(path),
        }
    )


@feature(
    "overviewDashboard.createAlert",
    "Create Alert",
    part="settings",
    fields=[
        text("metric", "Metric", "Late tasks"),
        number("threshold", "Threshold", 1.0, unit="count", min=0),
    ],
    requires_project=False,
)
def create_alert(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create an alert rule record."""
    return result(
        summary={"metric": values["metric"], "threshold": values["threshold"]},
        tables=[
            table(
                "Dashboard alert",
                [("metric", "Metric"), ("threshold", "Threshold")],
                [{"metric": values["metric"], "threshold": values["threshold"]}],
            )
        ],
    )


@feature(
    "overviewDashboard.setThreshold",
    "Set Threshold",
    part="settings",
    fields=[
        text("metric", "Metric", "BOQ cost"),
        number("threshold", "Threshold", 0.0, unit="value"),
    ],
    requires_project=False,
)
def set_threshold(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set a dashboard metric threshold."""
    return result(summary={"metric": values["metric"], "threshold": values["threshold"]})


@feature(
    "overviewDashboard.alertRecipients",
    "Alert Recipients",
    part="settings",
    fields=[text("recipients", "Comma-separated recipients", "")],
    requires_project=True,
)
def alert_recipients(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate alert recipient addresses and update persistent dashboard alert subscribers."""
    recipients = [item.strip() for item in values["recipients"].split(",") if item.strip()]
    if not recipients:
        raise FeatureInputError("Enter at least one alert recipient.")
    rows = [
        {"recipient": r, "syntaxValid": "@" in r and "." in r.rsplit("@", 1)[-1]}
        for r in recipients
    ]
    state = _load_dashboard(ctx)
    state["alertRecipients"] = rows
    path = save_export_json(ctx, "11 Exports", "dashboard-state.json", state)
    return result(
        summary={
            "recipientCount": len(rows),
            "invalidCount": sum(not row["syntaxValid"] for row in rows),
            "exportPath": str(path),
        },
        tables=[
            table(
                "Alert recipients",
                [("recipient", "Recipient"), ("syntaxValid", "Valid syntax")],
                rows,
            )
        ],
    )


@feature(
    "overviewDashboard.snoozeAlert",
    "Snooze Alert",
    part="settings",
    fields=[
        text("alert", "Alert name", ""),
        number("hours", "Snooze duration", 24.0, unit="h", min=0),
    ],
    requires_project=True,
)
def snooze_alert(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute snooze expiry UTC timestamp and persist muted dashboard alerts."""
    from datetime import UTC, datetime, timedelta

    alert_name = values["alert"].strip()
    if not alert_name:
        raise FeatureInputError("Enter an alert name to snooze.")
    until = (datetime.now(UTC) + timedelta(hours=float(values["hours"]))).isoformat(
        timespec="seconds"
    )
    state = _load_dashboard(ctx)
    snoozes = [s for s in state.get("snoozes", []) if s.get("alert") != alert_name]
    entry = {"alert": alert_name, "hours": float(values["hours"]), "snoozedUntilUtc": until}
    snoozes.append(entry)
    state["snoozes"] = snoozes
    path = save_export_json(ctx, "11 Exports", "dashboard-state.json", state)
    return result(
        summary={
            "alert": alert_name,
            "hours": entry["hours"],
            "snoozedUntilUtc": until,
            "exportPath": str(path),
        },
        tables=[
            table(
                "Snoozed alerts",
                [
                    ("alert", "Alert"),
                    ("hours", "Duration", "h"),
                    ("snoozedUntilUtc", "Snoozed until UTC"),
                ],
                snoozes,
            )
        ],
    )


@feature(
    "overviewDashboard.addWidget",
    "Add Widget",
    part="settings",
    fields=[text("widget", "Widget name", "KPI")],
    requires_project=True,
)
def add_widget(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Append a widget populated with live project metrics to dashboard state."""
    widget_name = values["widget"].strip()
    if not widget_name:
        raise FeatureInputError("Enter a widget name.")
    live = project_kpis(ctx)
    state = _load_dashboard(ctx)
    widgets = state.setdefault("widgets", [])
    widgets.append(
        {
            "id": f"W-{len(widgets) + 1:02d}",
            "widget": widget_name,
            "metrics": live,
            "addedAt": now_iso(),
        }
    )
    path = save_export_json(ctx, "11 Exports", "dashboard-state.json", state)
    return result(
        summary={"widget": widget_name, "widgetCount": len(widgets), "exportPath": str(path)},
        tables=[
            table(
                "Dashboard widgets",
                [("id", "ID"), ("widget", "Widget"), ("addedAt", "Added UTC")],
                widgets,
            )
        ],
    )


@feature(
    "overviewDashboard.filterControls",
    "Filter Controls",
    part="settings",
    fields=[text("filter", "Filter expression", "")],
    requires_project=True,
)
def filter_controls(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply a filter keyword across live project BIM elements and BOQ items and store it."""
    needle = values["filter"].strip().lower()
    elements, _ = list_bim(ctx)
    items = boq_items(ctx)
    matched_bim = [
        e
        for e in elements
        if not needle
        or needle in str(e.get("kind", "")).lower()
        or needle in str(e.get("id", "")).lower()
    ]
    matched_boq = [
        b
        for b in items
        if not needle
        or needle in str(b.get("description", "")).lower()
        or needle in str(b.get("trade", "")).lower()
    ]
    state = _load_dashboard(ctx)
    state["activeFilter"] = {
        "expression": values["filter"].strip(),
        "matchedBim": len(matched_bim),
        "matchedBoq": len(matched_boq),
    }
    path = save_export_json(ctx, "11 Exports", "dashboard-state.json", state)
    return result(
        summary={
            "filter": values["filter"].strip(),
            "matchedBim": len(matched_bim),
            "matchedBoq": len(matched_boq),
            "exportPath": str(path),
        }
    )


@feature(
    "overviewDashboard.widgetProperties",
    "Widget Properties",
    part="settings",
    fields=[text("widget", "Widget", ""), text("properties", "Properties JSON", "{}")],
    requires_project=True,
)
def widget_properties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate and merge JSON configuration onto a dashboard widget."""
    import json

    widget_name = values["widget"].strip()
    if not widget_name:
        raise FeatureInputError("Enter a widget name.")
    try:
        properties = json.loads(values["properties"])
    except json.JSONDecodeError as error:
        raise FeatureInputError("Properties must be valid JSON.") from error
    if not isinstance(properties, dict):
        raise FeatureInputError("Widget properties must be a JSON object.")
    state = _load_dashboard(ctx)
    widgets = state.setdefault("widgets", [])
    target = next(
        (w for w in widgets if w.get("widget") == widget_name or w.get("id") == widget_name), None
    )
    if target is None:
        target = {"id": f"W-{len(widgets) + 1:02d}", "widget": widget_name, "addedAt": now_iso()}
        widgets.append(target)
    merged = {**(target.get("properties") or {}), **properties}
    target["properties"] = merged
    path = save_export_json(ctx, "11 Exports", "dashboard-state.json", state)
    rows = [{"property": k, "value": str(v)} for k, v in merged.items()]
    return result(
        summary={"widget": widget_name, "propertyCount": len(merged), "exportPath": str(path)},
        tables=[table("Widget properties", [("property", "Property"), ("value", "Value")], rows)],
    )


@feature(
    "overviewDashboard.exportPdf",
    "Export PDF",
    part="settings",
    fields=[text("filename", "Report filename", "dashboard-report")],
    requires_project=True,
)
def export_pdf(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble live project metrics, BIM breakdowns, BOQ cost totals, and KPIs into Markdown."""
    live = project_kpis(ctx)
    elements, _stories = list_bim(ctx)
    state = _load_dashboard(ctx)
    by_kind: dict[str, int] = {}
    for elem in elements:
        k = str(elem.get("kind", "unknown"))
        by_kind[k] = by_kind.get(k, 0) + 1
    lines = [
        f"# {project_name(ctx)} — Executive Dashboard Report",
        "",
        "## Key Project Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Objects | {live['objects']} |",
        f"| BIM Elements | {live['bimElements']} |",
        f"| Stories | {live['stories']} |",
        f"| BOQ Line Items | {live['boqItems']} |",
        f"| BOQ Total Amount | {live['boqAmount']:,.2f} |",
        "",
        "## BIM Element Breakdown",
        "",
        "| Element Kind | Count |",
        "| --- | ---: |",
    ]
    for kind, cnt in sorted(by_kind.items()):
        lines.append(f"| {kind} | {cnt} |")
    if not by_kind:
        lines.append("| None | 0 |")
    kpis = list((state.get("kpis") or {}).values())
    if kpis:
        lines.extend(
            ["", "## Configured KPIs", "", "| KPI | Value | Target |", "| --- | ---: | ---: |"]
        )
        for row in kpis:
            lines.append(f"| {row['name']} | {row['value']} | {row.get('target', '-')} |")
    name = values["filename"].strip().replace(" ", "-") or "dashboard-report"
    path = write_export(ctx, "11 Exports", f"{name}.md", "\n".join(lines) + "\n")
    return result(
        summary={
            "exportPath": str(path),
            "bimElements": live["bimElements"],
            "objectCount": live["objects"],
            "boqAmount": live["boqAmount"],
            "kpiCount": len(kpis),
        },
        tables=[
            table(
                "BIM element breakdown",
                [("kind", "Kind"), ("count", "Count")],
                [{"kind": k, "count": v} for k, v in sorted(by_kind.items())],
            )
        ],
        notes=[f"Markdown executive dashboard report written to {path}."],
    )


@feature(
    "overviewDashboard.scheduledEmail",
    "Scheduled Email",
    part="settings",
    fields=[text("recipient", "Recipient", ""), text("schedule", "Schedule", "Weekly")],
    requires_project=True,
)
def scheduled_email(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate recipient address and update persistent scheduled-digest subscriptions."""
    recipient = values["recipient"].strip()
    if not recipient or "@" not in recipient or "." not in recipient.rsplit("@", 1)[-1]:
        raise FeatureInputError("Enter a valid email address for the scheduled digest.")
    state = _load_dashboard(ctx)
    subs = [s for s in state.get("scheduledDigests", []) if s.get("recipient") != recipient]
    subs.append(
        {
            "recipient": recipient,
            "schedule": values["schedule"],
            "kpisIncluded": len(state.get("kpis", {})),
            "updatedAt": now_iso(),
        }
    )
    state["scheduledDigests"] = subs
    path = save_export_json(ctx, "11 Exports", "dashboard-state.json", state)
    return result(
        summary={
            "recipient": recipient,
            "schedule": values["schedule"],
            "subscriptionCount": len(subs),
            "networkAccess": False,
            "exportPath": str(path),
        },
        tables=[
            table(
                "Scheduled digests",
                [("recipient", "Recipient"), ("schedule", "Cadence"), ("updatedAt", "Updated UTC")],
                subs,
            )
        ],
        notes=["Scheduled digest saved locally; no network message was sent."],
    )


@feature(
    "overviewDashboard.reportTemplate",
    "Report Template",
    part="settings",
    fields=[text("templateName", "Template name", "Engineering Dashboard")],
    requires_project=True,
)
def report_template(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Bind project live metrics and section schema into a persistent dashboard report template."""
    live = project_kpis(ctx)
    state = _load_dashboard(ctx)
    sections = [
        {"section": "Project metrics", "itemCount": live["objects"]},
        {"section": "BIM summary", "itemCount": live["bimElements"]},
        {"section": "BOQ summary", "itemCount": live["boqItems"]},
        {"section": "Configured KPIs", "itemCount": len(state.get("kpis", {}))},
    ]
    state["reportTemplate"] = {
        "template": values["templateName"].strip() or "Engineering Dashboard",
        "sections": sections,
        "updatedAt": now_iso(),
    }
    path = save_export_json(ctx, "11 Exports", "dashboard-state.json", state)
    return result(
        summary={
            "templateName": state["reportTemplate"]["template"],
            "sectionCount": len(sections),
            "exportPath": str(path),
        },
        tables=[
            table(
                "Report template sections",
                [("section", "Section"), ("itemCount", "Items")],
                sections,
            )
        ],
    )


@feature(
    "overviewDashboard.trendLine",
    "Trend Line",
    part="settings",
    fields=[text("values", "Comma-separated values", "1,2,3")],
    requires_project=False,
)
def trend_line(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute least-squares slope and intercept for numeric values."""
    try:
        series = [float(item.strip()) for item in values["values"].split(",") if item.strip()]
    except ValueError:
        raise FeatureInputError("Enter comma-separated numeric values.") from None
    n = len(series)
    if n < 2:
        raise FeatureInputError("Enter at least two values.")
    x_mean = (n - 1) / 2
    y_mean = sum(series) / n
    slope = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(series)) / sum(
        (i - x_mean) ** 2 for i in range(n)
    )
    intercept = y_mean - slope * x_mean
    rows = [{"index": i, "value": y, "trend": intercept + slope * i} for i, y in enumerate(series)]
    return result(
        summary={"slope": slope, "intercept": intercept},
        tables=[
            table("Trend line", [("index", "Index"), ("value", "Value"), ("trend", "Trend")], rows)
        ],
    )


@feature(
    "overviewDashboard.varianceAnalysis",
    "Variance Analysis",
    part="settings",
    fields=[
        number("actual", "Actual", 100.0, unit="value"),
        number("target", "Target", 90.0, unit="value"),
    ],
    requires_project=False,
)
def variance_analysis(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate absolute and percentage variance."""
    variance = values["actual"] - values["target"]
    percent = variance / values["target"] * 100 if values["target"] else 0.0
    return result(
        summary={
            "actual": values["actual"],
            "target": values["target"],
            "variance": variance,
            "variancePercent": percent,
        }
    )


@feature(
    "overviewDashboard.performanceScore",
    "Performance Score",
    part="settings",
    fields=[
        number("quality", "Quality", 80.0, unit="%", min=0, max=100),
        number("schedule", "Schedule", 80.0, unit="%", min=0, max=100),
        number("safety", "Safety", 80.0, unit="%", min=0, max=100),
    ],
    requires_project=False,
)
def performance_score(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate equal-weight quality, schedule and safety score."""
    score = (values["quality"] + values["schedule"] + values["safety"]) / 3
    return result(
        summary={
            "quality": values["quality"],
            "schedule": values["schedule"],
            "safety": values["safety"],
            "score": score,
        },
        notes=[
            "Score is an equal-weight management summary, not an engineering acceptance metric."
        ],
    )


@feature(
    "overviewDashboard.dataRefresh",
    "Data Refresh",
    part="settings",
    fields=[],
    requires_project=True,
)
def data_refresh(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Refresh dashboard counts from current project files."""
    require_project(ctx, "refreshing dashboard data")
    elements, stories = list_bim(ctx)
    return result(
        summary={
            "objectCount": len(list_objects(ctx)),
            "bimElementCount": len(elements),
            "storyCount": len(stories),
            "boqItemCount": len(boq_items(ctx)),
        }
    )
