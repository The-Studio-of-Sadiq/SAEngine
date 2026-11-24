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
    json_text,
    list_bim,
    list_objects,
    require_project,
    write_export,
)


@feature(
    "overviewDashboard.addKpi",
    "Add KPI",
    part="settings",
    fields=[text("name", "KPI name", ""), number("value", "Value", 0.0, unit="value")],
    requires_project=True,
)
def add_kpi(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a KPI record for the project dashboard."""
    if not values["name"].strip():
        raise FeatureInputError("Enter a KPI name.")
    path = write_export(
        ctx,
        "11 Exports",
        "dashboard-kpis.json",
        json_text({"name": values["name"], "value": values["value"]}),
    )
    return result(
        summary={"name": values["name"], "value": values["value"], "exportPath": str(path)}
    )


@feature(
    "overviewDashboard.setTarget",
    "Set Target",
    part="settings",
    fields=[text("kpi", "KPI name", ""), number("target", "Target", 100.0, unit="value")],
    requires_project=True,
)
def set_target(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a KPI target."""
    path = write_export(
        ctx,
        "11 Exports",
        "dashboard-target.json",
        json_text({"kpi": values["kpi"], "target": values["target"]}),
    )
    return result(
        summary={"kpi": values["kpi"], "target": values["target"], "exportPath": str(path)}
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
    """Write a dashboard layout name export."""
    path = write_export(
        ctx, "11 Exports", "dashboard-layout.json", json_text({"layout": values["layout"]})
    )
    return result(summary={"layout": values["layout"], "exportPath": str(path)})


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
    """Write alert recipients to a local export."""
    recipients = [item.strip() for item in values["recipients"].split(",") if item.strip()]
    path = write_export(
        ctx, "11 Exports", "alert-recipients.json", json_text({"recipients": recipients})
    )
    return result(
        summary={"recipientCount": len(recipients), "exportPath": str(path)},
        tables=[
            table(
                "Alert recipients",
                [("recipient", "Recipient")],
                [{"recipient": recipient} for recipient in recipients],
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
    """Write an alert snooze record."""
    path = write_export(
        ctx,
        "11 Exports",
        "alert-snooze.json",
        json_text({"alert": values["alert"], "hours": values["hours"]}),
    )
    return result(
        summary={"alert": values["alert"], "hours": values["hours"], "exportPath": str(path)}
    )


@feature(
    "overviewDashboard.addWidget",
    "Add Widget",
    part="settings",
    fields=[text("widget", "Widget name", "KPI")],
    requires_project=True,
)
def add_widget(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a dashboard widget configuration."""
    path = write_export(
        ctx, "11 Exports", "dashboard-widget.json", json_text({"widget": values["widget"]})
    )
    return result(summary={"widget": values["widget"], "exportPath": str(path)})


@feature(
    "overviewDashboard.filterControls",
    "Filter Controls",
    part="settings",
    fields=[text("filter", "Filter expression", "")],
    requires_project=True,
)
def filter_controls(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Store a dashboard filter expression."""
    path = write_export(
        ctx, "11 Exports", "dashboard-filter.json", json_text({"filter": values["filter"]})
    )
    return result(summary={"filter": values["filter"], "exportPath": str(path)})


@feature(
    "overviewDashboard.widgetProperties",
    "Widget Properties",
    part="settings",
    fields=[text("widget", "Widget", ""), text("properties", "Properties JSON", "{}")],
    requires_project=True,
)
def widget_properties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write widget properties JSON."""
    import json

    try:
        properties = json.loads(values["properties"])
    except json.JSONDecodeError as error:
        raise FeatureInputError("Properties must be valid JSON.") from error
    path = write_export(
        ctx,
        "11 Exports",
        "widget-properties.json",
        json_text({"widget": values["widget"], "properties": properties}),
    )
    return result(
        summary={
            "widget": values["widget"],
            "propertyCount": len(properties) if isinstance(properties, dict) else 0,
            "exportPath": str(path),
        }
    )


@feature(
    "overviewDashboard.exportPdf",
    "Export PDF",
    part="settings",
    fields=[text("filename", "Report filename", "dashboard-report")],
    requires_project=True,
)
def export_pdf(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export a Markdown dashboard report in place of a binary PDF."""
    elements, stories = list_bim(ctx)
    report = f"# {values['filename']}\\n\\n- Objects: {len(list_objects(ctx))}\\n- BIM elements: {len(elements)}\\n- Stories: {len(stories)}\\n"
    name = values["filename"].strip().replace(" ", "-") or "dashboard-report"
    path = write_export(ctx, "11 Exports", f"{name}.md", report)
    return result(
        summary={
            "exportPath": str(path),
            "bimElements": len(elements),
            "objectCount": len(list_objects(ctx)),
        },
        notes=[f"Markdown report written to {path}; binary PDF generation is not requested."],
    )


@feature(
    "overviewDashboard.scheduledEmail",
    "Scheduled Email",
    part="settings",
    fields=[text("recipient", "Recipient", ""), text("schedule", "Schedule", "Weekly")],
    requires_project=True,
)
def scheduled_email(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write scheduled-report metadata locally; no email is sent."""
    path = write_export(
        ctx,
        "11 Exports",
        "scheduled-report.json",
        json_text({"recipient": values["recipient"], "schedule": values["schedule"]}),
    )
    return result(
        summary={
            "recipient": values["recipient"],
            "schedule": values["schedule"],
            "networkAccess": False,
            "exportPath": str(path),
        },
        notes=["Email metadata is local; no message was sent."],
    )


@feature(
    "overviewDashboard.reportTemplate",
    "Report Template",
    part="settings",
    fields=[text("templateName", "Template name", "Engineering Dashboard")],
    requires_project=True,
)
def report_template(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a report-template manifest."""
    path = write_export(
        ctx,
        "11 Exports",
        "dashboard-template.json",
        json_text(
            {
                "template": values["templateName"],
                "sections": ["Project metrics", "BIM summary", "BOQ summary"],
            }
        ),
    )
    return result(summary={"templateName": values["templateName"], "exportPath": str(path)})


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
