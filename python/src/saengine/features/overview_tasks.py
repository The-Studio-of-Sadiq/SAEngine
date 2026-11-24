"""Overview task and workflow commands."""

from __future__ import annotations

from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.overview_common import (
    json_text,
    list_objects,
    require_project,
    write_export,
)


@feature(
    "overviewTasks.taskList",
    "Task List",
    part="settings",
    fields=[text("status", "Status filter", "all")],
    requires_project=False,
)
def task_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a work queue from project objects and their review metadata."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to build a task list.")
    rows = [
        {
            "task": f"Review {item.get('name', item.get('id', 'object'))}",
            "part": item.get("id", ""),
            "status": item.get("status", "Pending"),
        }
        for item in list_objects(ctx)
    ]
    status = values["status"].lower()
    rows = [row for row in rows if status == "all" or status in str(row["status"]).lower()]
    return result(
        summary={"taskCount": len(rows)},
        tables=[
            table("Task list", [("task", "Task"), ("part", "Part"), ("status", "Status")], rows)
        ],
    )


@feature(
    "overviewTasks.assignTask",
    "Assign Task",
    part="settings",
    fields=[text("task", "Task", ""), text("assignee", "Assignee", "")],
    requires_project=True,
)
def assign_task(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a task assignment to the project export folder."""
    if not values["task"].strip() or not values["assignee"].strip():
        raise FeatureInputError("Enter both task and assignee.")
    path = write_export(
        ctx,
        "11 Exports",
        "task-assignment.json",
        json_text({"task": values["task"], "assignee": values["assignee"]}),
    )
    return result(
        summary={"task": values["task"], "assignee": values["assignee"], "exportPath": str(path)}
    )


@feature(
    "overviewTasks.dueDates",
    "Due Dates",
    part="settings",
    fields=[text("task", "Task", ""), text("dueDate", "Due date YYYY-MM-DD", "")],
    requires_project=True,
)
def due_dates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a task due-date record."""
    if not values["dueDate"]:
        raise FeatureInputError("Enter a due date.")
    path = write_export(
        ctx,
        "11 Exports",
        "task-due-date.json",
        json_text({"task": values["task"], "dueDate": values["dueDate"]}),
    )
    return result(
        summary={"task": values["task"], "dueDate": values["dueDate"], "exportPath": str(path)}
    )


@feature(
    "overviewTasks.taskDependency",
    "Task Dependency",
    part="settings",
    fields=[text("task", "Task", ""), text("dependsOn", "Depends on", "")],
    requires_project=True,
)
def task_dependency(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record a task dependency."""
    if not values["task"].strip() or not values["dependsOn"].strip():
        raise FeatureInputError("Enter task and dependency names.")
    path = write_export(
        ctx,
        "11 Exports",
        "task-dependency.json",
        json_text({"task": values["task"], "dependsOn": values["dependsOn"]}),
    )
    return result(
        summary={"task": values["task"], "dependsOn": values["dependsOn"], "exportPath": str(path)}
    )


@feature(
    "overviewTasks.priorityMatrix",
    "Priority Matrix",
    part="settings",
    fields=[
        number("impact", "Impact", 3.0, unit="points", min=1, max=5),
        number("effort", "Effort", 3.0, unit="points", min=1, max=5),
    ],
    requires_project=False,
)
def priority_matrix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate an impact-effort task priority class."""
    impact, effort = values["impact"], values["effort"]
    priority = (
        "P1"
        if impact >= 4 and effort <= 2
        else "P2"
        if impact >= 4
        else "P3"
        if effort <= 2
        else "P4"
    )
    return result(
        summary={"impact": impact, "effort": effort, "priority": priority},
        tables=[
            table(
                "Priority matrix",
                [("impact", "Impact"), ("effort", "Effort"), ("priority", "Priority")],
                [{"impact": impact, "effort": effort, "priority": priority}],
            )
        ],
    )


@feature(
    "overviewTasks.reviewQueue", "Review Queue", part="objects", fields=[], requires_project=True
)
def review_queue(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List parts whose status is review or pending."""
    rows = [
        {
            "part": item.get("id", ""),
            "name": item.get("name", ""),
            "status": item.get("status", "Pending"),
        }
        for item in list_objects(ctx)
        if str(item.get("status", "Pending")).lower() in ("review", "pending", "submitted")
    ]
    return result(
        summary={"reviewCount": len(rows)},
        tables=[
            table("Review queue", [("part", "Part"), ("name", "Name"), ("status", "Status")], rows)
        ],
    )


@feature(
    "overviewTasks.approvals",
    "Approvals",
    part="settings",
    fields=[text("item", "Item", ""), text("status", "Approval status", "Pending")],
    requires_project=True,
)
def approvals(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write an approval record."""
    path = write_export(
        ctx,
        "11 Exports",
        "approval-record.json",
        json_text({"item": values["item"], "status": values["status"]}),
    )
    return result(
        summary={"item": values["item"], "status": values["status"], "exportPath": str(path)}
    )


@feature(
    "overviewTasks.discussion",
    "Discussion",
    part="settings",
    fields=[text("topic", "Topic", ""), text("comment", "Comment", "")],
    requires_project=True,
)
def discussion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a discussion comment as Markdown."""
    if not values["topic"].strip():
        raise FeatureInputError("Enter a discussion topic.")
    path = write_export(
        ctx, "11 Exports", "discussion.md", f"# {values['topic']}\n\n{values['comment']}\n"
    )
    return result(
        summary={
            "topic": values["topic"],
            "commentLength": len(values["comment"]),
            "exportPath": str(path),
        }
    )


@feature(
    "overviewTasks.reviewChecklist",
    "Review Checklist",
    part="settings",
    fields=[text("items", "Checklist items comma-separated", "Geometry,Loads,Details")],
    requires_project=True,
)
def review_checklist(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a review checklist export."""
    items = [item.strip() for item in values["items"].split(",") if item.strip()]
    path = write_export(
        ctx,
        "11 Exports",
        "review-checklist.md",
        "\n".join(f"- [ ] {item}" for item in items) + "\n",
    )
    return result(
        summary={"itemCount": len(items), "exportPath": str(path)},
        tables=[
            table(
                "Review checklist",
                [("item", "Item"), ("complete", "Complete")],
                [{"item": item, "complete": False} for item in items],
            )
        ],
    )


@feature(
    "overviewTasks.delegateReview",
    "Delegate Review",
    part="settings",
    fields=[text("reviewer", "Reviewer", ""), text("scope", "Review scope", "")],
    requires_project=True,
)
def delegate_review(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a review delegation record."""
    if not values["reviewer"].strip():
        raise FeatureInputError("Enter a reviewer.")
    path = write_export(
        ctx,
        "11 Exports",
        "review-delegation.json",
        json_text({"reviewer": values["reviewer"], "scope": values["scope"]}),
    )
    return result(
        summary={"reviewer": values["reviewer"], "scope": values["scope"], "exportPath": str(path)}
    )


@feature(
    "overviewTasks.resourceAllocator",
    "Resource Allocator",
    part="settings",
    fields=[
        text("resource", "Resource", ""),
        number("hours", "Available hours", 40.0, unit="h", min=0),
    ],
    requires_project=False,
)
def resource_allocator(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Allocate available resource hours to the work package."""
    if values["hours"] < 0:
        raise FeatureInputError("Available hours must be non-negative.")
    return result(
        summary={"resource": values["resource"], "hours": values["hours"]},
        tables=[
            table(
                "Resource allocation",
                [("resource", "Resource"), ("hours", "Hours", "h")],
                [{"resource": values["resource"], "hours": values["hours"]}],
            )
        ],
    )


@feature(
    "overviewTasks.workloadGraph",
    "Workload Graph",
    part="settings",
    fields=[text("assignments", "name=hours comma-separated", "")],
    requires_project=False,
)
def workload_graph(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert a resource workload string into chart rows."""
    rows = []
    for item in values["assignments"].split(","):
        if "=" not in item:
            continue
        name, hours = item.split("=", 1)
        try:
            rows.append({"resource": name.strip(), "hours": float(hours)})
        except ValueError:
            raise FeatureInputError("Use name=hours pairs separated by commas.") from None
    return result(
        summary={"resourceCount": len(rows), "totalHours": sum(r["hours"] for r in rows)},
        tables=[table("Workload", [("resource", "Resource"), ("hours", "Hours", "h")], rows)],
    )


@feature(
    "overviewTasks.capacityPlanner",
    "Capacity Planner",
    part="settings",
    fields=[
        number("capacity", "Team capacity", 160.0, unit="h", min=0),
        number("required", "Required effort", 120.0, unit="h", min=0),
    ],
    requires_project=False,
)
def capacity_planner(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare required effort with available capacity."""
    util = values["required"] / values["capacity"] if values["capacity"] else 0.0
    return result(
        summary={
            "capacityHours": values["capacity"],
            "requiredHours": values["required"],
            "utilisation": util,
            "shortfallHours": max(0.0, values["required"] - values["capacity"]),
        },
        notes=["Utilisation is required effort divided by capacity."],
    )


@feature(
    "overviewTasks.milestoneTracker",
    "Milestone Tracker",
    part="settings",
    fields=[
        text("milestone", "Milestone", ""),
        text("date", "Target date", ""),
        text("status", "Status", "Planned"),
    ],
    requires_project=True,
)
def milestone_tracker(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a milestone record."""
    path = write_export(
        ctx,
        "11 Exports",
        "milestone.json",
        json_text(
            {"milestone": values["milestone"], "date": values["date"], "status": values["status"]}
        ),
    )
    return result(
        summary={
            "milestone": values["milestone"],
            "date": values["date"],
            "status": values["status"],
            "exportPath": str(path),
        }
    )


@feature(
    "overviewTasks.baselineTarget",
    "Baseline Target",
    part="settings",
    fields=[number("target", "Target value", 100.0, unit="%", min=0)],
    requires_project=False,
)
def baseline_target(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record a numeric baseline target."""
    if values["target"] < 0:
        raise FeatureInputError("Target must be non-negative.")
    return result(
        summary={"baselineTarget": values["target"]},
        tables=[
            table("Baseline target", [("target", "Target", "%")], [{"target": values["target"]}])
        ],
    )


@feature(
    "overviewTasks.ganttChart",
    "Gantt Chart",
    part="settings",
    fields=[text("tasks", "task=start,end comma-separated", "")],
    requires_project=False,
)
def gantt_chart(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build a Gantt table from task=start,end records."""
    rows = []
    for item in values["tasks"].split(","):
        if "=" not in item:
            continue
        name, dates = item.split("=", 1)
        parts = [value.strip() for value in dates.split("|", 1)]
        if len(parts) != 2:
            raise FeatureInputError("Use task=start|end pairs separated by commas.")
        rows.append({"task": name.strip(), "start": parts[0], "end": parts[1]})
    return result(
        summary={"taskCount": len(rows)},
        tables=[
            table("Gantt schedule", [("task", "Task"), ("start", "Start"), ("end", "End")], rows)
        ],
    )


@feature(
    "overviewTasks.issueLog",
    "Issue Log",
    part="settings",
    fields=[text("issue", "Issue", ""), text("status", "Status", "Open")],
    requires_project=True,
)
def issue_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write an issue-log record."""
    path = write_export(
        ctx,
        "11 Exports",
        "issue-log.json",
        json_text({"issue": values["issue"], "status": values["status"]}),
    )
    return result(
        summary={"issue": values["issue"], "status": values["status"], "exportPath": str(path)}
    )


@feature(
    "overviewTasks.severityFilter",
    "Severity Filter",
    part="settings",
    fields=[text("severity", "Severity", "High")],
    requires_project=True,
)
def severity_filter(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Filter issue-log JSON if present by severity."""
    root = require_project(ctx, "filtering issues")
    path = root / "11 Exports/issue-log.json"
    raw = json_text({"severity": values["severity"]})
    if path.is_file():
        import json

        try:
            raw_data = json.loads(path.read_text("utf-8"))
            raw_data["severity"] = values["severity"]
            raw = json_text(raw_data)
            path.write_text(raw, encoding="utf-8")
        except json.JSONDecodeError:
            raise FeatureInputError("The issue log is not valid JSON.") from None
    return result(summary={"severity": values["severity"]})


@feature(
    "overviewTasks.resolutionTracking",
    "Resolution Tracking",
    part="settings",
    fields=[text("issue", "Issue", ""), text("resolution", "Resolution", "")],
    requires_project=True,
)
def resolution_tracking(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write issue-resolution tracking data."""
    path = write_export(
        ctx,
        "11 Exports",
        "issue-resolution.json",
        json_text({"issue": values["issue"], "resolution": values["resolution"]}),
    )
    return result(
        summary={
            "issue": values["issue"],
            "resolution": values["resolution"],
            "exportPath": str(path),
        }
    )


@feature(
    "overviewTasks.alertRules",
    "Alert Rules",
    part="settings",
    fields=[
        text("metric", "Metric", "Late tasks"),
        number("threshold", "Threshold", 1.0, unit="count", min=0),
    ],
    requires_project=False,
)
def alert_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a threshold rule record."""
    return result(
        summary={"metric": values["metric"], "threshold": values["threshold"]},
        tables=[
            table(
                "Alert rule",
                [("metric", "Metric"), ("threshold", "Threshold")],
                [{"metric": values["metric"], "threshold": values["threshold"]}],
            )
        ],
    )


@feature(
    "overviewTasks.digestSettings",
    "Digest Settings",
    part="settings",
    fields=[
        select(
            "frequency",
            "Digest frequency",
            [("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")],
            "weekly",
        )
    ],
    requires_project=False,
)
def digest_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record a work digest frequency."""
    return result(summary={"frequency": values["frequency"]})


@feature(
    "overviewTasks.taskReminders",
    "Task Reminders",
    part="settings",
    fields=[
        text("task", "Task", ""),
        number("leadDays", "Reminder lead time", 1.0, unit="days", min=0, max=365),
    ],
    requires_project=False,
)
def task_reminders(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate task reminder lead time in a rule record."""
    return result(
        summary={"task": values["task"], "leadDays": values["leadDays"]},
        tables=[
            table(
                "Task reminder",
                [("task", "Task"), ("leadDays", "Lead time", "days")],
                [{"task": values["task"], "leadDays": values["leadDays"]}],
            )
        ],
    )
