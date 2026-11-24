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
    boq_items,
    list_bim,
    list_objects,
    load_export_json,
    now_iso,
    save_export_json,
    settings_dict,
    write_export,
)


def _load_workflow(ctx: FeatureContext) -> dict[str, Any]:
    data = load_export_json(ctx, "11 Exports", "workflow-register.json", {})
    return data if isinstance(data, dict) else {}


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
    """Assign a task in the persistent workflow register, validating configured team members."""
    task_name = values["task"].strip()
    assignee = values["assignee"].strip()
    if not task_name or not assignee:
        raise FeatureInputError("Enter both task and assignee.")
    team = settings_dict(ctx).get("team", [])
    team_names = {m.get("name") for m in team if isinstance(m, dict) and m.get("name")}
    if team_names and assignee not in team_names:
        raise FeatureInputError(
            f"Assignee '{assignee}' was not found in the project team directory."
        )
    reg = _load_workflow(ctx)
    tasks = reg.setdefault("tasks", {})
    entry = tasks.setdefault(task_name, {"task": task_name})
    entry["assignee"] = assignee
    entry["updatedAt"] = now_iso()
    path = save_export_json(ctx, "11 Exports", "workflow-register.json", reg)
    rows = list(tasks.values())
    return result(
        summary={
            "task": task_name,
            "assignee": assignee,
            "taskCount": len(rows),
            "exportPath": str(path),
        },
        tables=[
            table(
                "Assigned tasks",
                [("task", "Task"), ("assignee", "Assignee"), ("dueDate", "Due date")],
                rows,
            )
        ],
    )


@feature(
    "overviewTasks.dueDates",
    "Due Dates",
    part="settings",
    fields=[text("task", "Task", ""), text("dueDate", "Due date YYYY-MM-DD", "")],
    requires_project=True,
)
def due_dates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate an ISO due date, update the workflow register, and count overdue tasks."""
    from datetime import UTC, date, datetime

    task_name = values["task"].strip()
    due_str = values["dueDate"].strip()
    if not task_name or not due_str:
        raise FeatureInputError("Enter both task and due date (YYYY-MM-DD).")
    try:
        due = date.fromisoformat(due_str)
    except ValueError as error:
        raise FeatureInputError(f"Invalid due date '{due_str}'; use YYYY-MM-DD format.") from error
    today = datetime.now(UTC).date()
    days_remaining = (due - today).days
    reg = _load_workflow(ctx)
    tasks = reg.setdefault("tasks", {})
    entry = tasks.setdefault(task_name, {"task": task_name})
    entry["dueDate"] = due.isoformat()
    entry["daysRemaining"] = days_remaining
    path = save_export_json(ctx, "11 Exports", "workflow-register.json", reg)
    rows = [t for t in tasks.values() if "dueDate" in t]
    overdue = sum(1 for r in rows if int(r.get("daysRemaining", 0)) < 0)
    return result(
        summary={
            "task": task_name,
            "dueDate": due.isoformat(),
            "daysRemaining": days_remaining,
            "overdueCount": overdue,
            "exportPath": str(path),
        },
        tables=[
            table(
                "Task schedule",
                [("task", "Task"), ("dueDate", "Due date"), ("daysRemaining", "Days remaining")],
                rows,
            )
        ],
    )


@feature(
    "overviewTasks.taskDependency",
    "Task Dependency",
    part="settings",
    fields=[text("task", "Task", ""), text("dependsOn", "Depends on", "")],
    requires_project=True,
)
def task_dependency(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Register a task dependency edge after checking the graph for cyclic dependencies."""
    task_name = values["task"].strip()
    dep = values["dependsOn"].strip()
    if not task_name or not dep:
        raise FeatureInputError("Enter task and dependency names.")
    if task_name == dep:
        raise FeatureInputError(f"Task '{task_name}' cannot depend on itself.")
    reg = _load_workflow(ctx)
    deps: list[dict[str, str]] = reg.setdefault("dependencies", [])
    adj: dict[str, set[str]] = {}
    for edge in deps:
        adj.setdefault(edge["task"], set()).add(edge["dependsOn"])
    adj.setdefault(task_name, set()).add(dep)
    stack = [dep]
    visited: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur == task_name:
            raise FeatureInputError(
                f"Adding '{task_name}' -> '{dep}' introduces a dependency cycle."
            )
        if cur not in visited:
            visited.add(cur)
            stack.extend(adj.get(cur, ()))
    deps = [e for e in deps if not (e["task"] == task_name and e["dependsOn"] == dep)]
    deps.append({"task": task_name, "dependsOn": dep})
    reg["dependencies"] = deps
    path = save_export_json(ctx, "11 Exports", "workflow-register.json", reg)
    return result(
        summary={
            "task": task_name,
            "dependsOn": dep,
            "dependencyCount": len(deps),
            "exportPath": str(path),
        },
        tables=[table("Task dependencies", [("task", "Task"), ("dependsOn", "Depends on")], deps)],
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
    """Record item approval status in the workflow register and compute approval rate."""
    item_name = values["item"].strip()
    if not item_name:
        raise FeatureInputError("Enter an approval item name.")
    reg = _load_workflow(ctx)
    items = [r for r in reg.get("approvals", []) if r.get("item") != item_name]
    items.append(
        {"item": item_name, "status": values["status"].strip() or "Pending", "updatedAt": now_iso()}
    )
    reg["approvals"] = items
    approved = sum(1 for r in items if str(r["status"]).casefold() == "approved")
    rate = round(approved / len(items) * 100.0, 1)
    path = save_export_json(ctx, "11 Exports", "workflow-register.json", reg)
    return result(
        summary={
            "item": item_name,
            "status": items[-1]["status"],
            "approvalCount": len(items),
            "approvalRatePercent": rate,
            "exportPath": str(path),
        },
        tables=[
            table(
                "Approvals",
                [("item", "Item"), ("status", "Status"), ("updatedAt", "Updated UTC")],
                items,
            )
        ],
    )


@feature(
    "overviewTasks.discussion",
    "Discussion",
    part="settings",
    fields=[text("topic", "Topic", ""), text("comment", "Comment", "")],
    requires_project=True,
)
def discussion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Append a timestamped comment to the project discussion thread and Markdown log."""
    topic = values["topic"].strip()
    if not topic:
        raise FeatureInputError("Enter a discussion topic.")
    reg = _load_workflow(ctx)
    thread = reg.setdefault("discussions", [])
    thread.append({"topic": topic, "comment": values["comment"].strip(), "timestamp": now_iso()})
    save_export_json(ctx, "11 Exports", "workflow-register.json", reg)
    md_lines = ["# Project Discussion Log", ""]
    for item in thread:
        md_lines.append(f"## {item['topic']} ({item['timestamp']})")
        md_lines.append(item["comment"] or "(no body)")
        md_lines.append("")
    path = write_export(ctx, "11 Exports", "discussion.md", "\n".join(md_lines))
    return result(
        summary={
            "topic": topic,
            "entryCount": len(thread),
            "commentLength": len(values["comment"]),
            "exportPath": str(path),
        },
        tables=[
            table(
                "Discussion entries",
                [("timestamp", "UTC"), ("topic", "Topic"), ("comment", "Comment")],
                thread,
            )
        ],
    )


@feature(
    "overviewTasks.reviewChecklist",
    "Review Checklist",
    part="settings",
    fields=[text("items", "Checklist items comma-separated", "Geometry,Loads,Details")],
    requires_project=True,
)
def review_checklist(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate requested review domains against live BIM/loads/BOQ parts and save the checklist."""
    items = [item.strip() for item in values["items"].split(",") if item.strip()]
    if not items:
        raise FeatureInputError("Enter at least one checklist item.")
    elements, _ = list_bim(ctx)
    objects = list_objects(ctx)
    loads = settings_dict(ctx).get("areaLoads", [])
    boq = boq_items(ctx)
    domain_status = {
        "geometry": len(elements) > 0,
        "loads": bool(loads),
        "details": len(objects) > 0,
        "boq": len(boq) > 0,
    }
    rows = [{"item": item, "complete": domain_status.get(item.lower(), False)} for item in items]
    md = "\n".join(f"- [{'x' if r['complete'] else ' '}] {r['item']}" for r in rows) + "\n"
    path = write_export(ctx, "11 Exports", "review-checklist.md", md)
    done = sum(1 for r in rows if r["complete"])
    return result(
        summary={"itemCount": len(rows), "completedCount": done, "exportPath": str(path)},
        tables=[table("Review checklist", [("item", "Item"), ("complete", "Complete")], rows)],
    )


@feature(
    "overviewTasks.delegateReview",
    "Delegate Review",
    part="settings",
    fields=[text("reviewer", "Reviewer", ""), text("scope", "Review scope", "")],
    requires_project=True,
)
def delegate_review(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Match reviewable project objects by scope and record review delegation in workflow state."""
    reviewer = values["reviewer"].strip()
    if not reviewer:
        raise FeatureInputError("Enter a reviewer.")
    scope = values["scope"].strip()
    matched = [
        o
        for o in list_objects(ctx)
        if not scope
        or scope.lower() in str(o.get("kind", "")).lower()
        or scope.lower() in str(o.get("id", "")).lower()
    ]
    reg = _load_workflow(ctx)
    delegations = reg.setdefault("delegations", [])
    delegations.append(
        {
            "reviewer": reviewer,
            "scope": scope or "all",
            "matchedObjects": len(matched),
            "assignedAt": now_iso(),
        }
    )
    path = save_export_json(ctx, "11 Exports", "workflow-register.json", reg)
    return result(
        summary={
            "reviewer": reviewer,
            "scope": scope,
            "matchedObjects": len(matched),
            "exportPath": str(path),
        },
        tables=[
            table(
                "Review delegations",
                [
                    ("reviewer", "Reviewer"),
                    ("scope", "Scope"),
                    ("matchedObjects", "Matched objects"),
                ],
                delegations,
            )
        ],
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
    """Validate optional ISO milestone date, update persistent milestones, and compute overdue counts."""
    from datetime import UTC, date, datetime

    name = values["milestone"].strip()
    if not name:
        raise FeatureInputError("Enter a milestone name.")
    target_date = values["date"].strip()
    days_left: int | None = None
    if target_date:
        try:
            days_left = (date.fromisoformat(target_date) - datetime.now(UTC).date()).days
        except ValueError as error:
            raise FeatureInputError(
                f"Invalid milestone date '{target_date}'; use YYYY-MM-DD."
            ) from error
    reg = _load_workflow(ctx)
    milestones = [m for m in reg.get("milestones", []) if m.get("milestone") != name]
    milestones.append(
        {
            "milestone": name,
            "date": target_date,
            "status": values["status"],
            "daysRemaining": days_left,
        }
    )
    reg["milestones"] = milestones
    overdue = sum(
        1
        for m in milestones
        if isinstance(m.get("daysRemaining"), int)
        and m["daysRemaining"] < 0
        and m.get("status") != "Done"
    )
    path = save_export_json(ctx, "11 Exports", "workflow-register.json", reg)
    return result(
        summary={
            "milestone": name,
            "date": target_date,
            "status": values["status"],
            "milestoneCount": len(milestones),
            "overdueCount": overdue,
            "exportPath": str(path),
        },
        tables=[
            table(
                "Milestones",
                [
                    ("milestone", "Milestone"),
                    ("date", "Target date"),
                    ("status", "Status"),
                    ("daysRemaining", "Days left"),
                ],
                milestones,
            )
        ],
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
    """Append an indexed issue to persistent issue-log.json and summarize open issues."""
    issue_text = values["issue"].strip()
    if not issue_text:
        raise FeatureInputError("Enter an issue summary.")
    loaded = load_export_json(ctx, "11 Exports", "issue-log.json", [])
    entries: list[dict[str, Any]] = (
        [e for e in loaded if isinstance(e, dict)]
        if isinstance(loaded, list)
        else [loaded]
        if isinstance(loaded, dict) and loaded.get("issue")
        else []
    )
    entry = {
        "id": f"ISS-{len(entries) + 1:03d}",
        "issue": issue_text,
        "status": values["status"].strip() or "Open",
        "loggedAt": now_iso(),
    }
    entries.append(entry)
    path = save_export_json(ctx, "11 Exports", "issue-log.json", entries)
    open_count = sum(1 for e in entries if str(e.get("status", "")).lower() == "open")
    return result(
        summary={
            "id": entry["id"],
            "issue": issue_text,
            "status": entry["status"],
            "issueCount": len(entries),
            "openCount": open_count,
            "exportPath": str(path),
        },
        tables=[
            table(
                "Issue log",
                [
                    ("id", "ID"),
                    ("issue", "Issue"),
                    ("status", "Status"),
                    ("loggedAt", "Logged UTC"),
                ],
                entries,
            )
        ],
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
    loaded = load_export_json(ctx, "11 Exports", "issue-log.json", [])
    rows = (
        [
            e
            for e in loaded
            if isinstance(e, dict)
            and str(e.get("severity", values["severity"])).lower() == values["severity"].lower()
        ]
        if isinstance(loaded, list)
        else []
    )
    return result(summary={"severity": values["severity"], "matchedCount": len(rows)})


@feature(
    "overviewTasks.resolutionTracking",
    "Resolution Tracking",
    part="settings",
    fields=[text("issue", "Issue", ""), text("resolution", "Resolution", "")],
    requires_project=True,
)
def resolution_tracking(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Resolve a logged issue, update issue status in issue-log.json, and compute resolution rate."""
    issue_key = values["issue"].strip()
    resolution_text = values["resolution"].strip()
    if not issue_key or not resolution_text:
        raise FeatureInputError("Enter both an issue identifier/summary and resolution text.")
    loaded = load_export_json(ctx, "11 Exports", "issue-log.json", [])
    entries: list[dict[str, Any]] = (
        [e for e in loaded if isinstance(e, dict)] if isinstance(loaded, list) else []
    )
    matched = next(
        (e for e in entries if e.get("id") == issue_key or e.get("issue") == issue_key),
        None,
    )
    if matched is None:
        matched = {"id": f"ISS-{len(entries) + 1:03d}", "issue": issue_key}
        entries.append(matched)
    matched["status"] = "Resolved"
    matched["resolution"] = resolution_text
    matched["resolvedAt"] = now_iso()
    path = save_export_json(ctx, "11 Exports", "issue-log.json", entries)
    resolved_count = sum(1 for e in entries if str(e.get("status", "")).lower() == "resolved")
    rate = round(resolved_count / len(entries) * 100.0, 1) if entries else 0.0
    return result(
        summary={
            "issue": issue_key,
            "resolution": resolution_text,
            "resolvedCount": resolved_count,
            "totalIssues": len(entries),
            "resolutionRatePercent": rate,
            "exportPath": str(path),
        },
        tables=[
            table(
                "Issue resolutions",
                [
                    ("id", "ID"),
                    ("issue", "Issue"),
                    ("status", "Status"),
                    ("resolution", "Resolution"),
                ],
                entries,
            )
        ],
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
