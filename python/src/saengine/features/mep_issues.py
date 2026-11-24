"""MEP issue, BCF and IDS features."""

from __future__ import annotations

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


def _coord(ctx: FeatureContext):
    from saengine.library.mep import parse

    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add 07 MEP/mep.json to the project.")
    return parse(__import__("json").dumps(raw)).coordination


@feature(
    "mepIssues.bcfTopics",
    "BCF Topics",
    part="mep",
    fields=[
        text("topic", "Topic title", "Coordination issue"),
        select(
            "status",
            "Status",
            [
                ("new", "New"),
                ("active", "Active"),
                ("reviewed", "Reviewed"),
                ("resolved", "Resolved"),
                ("closed", "Closed"),
            ],
            "new",
        ),
    ],
    requires_project=True,
)
def bcf_topics(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    rows = [
        {"id": i.id, "title": i.title, "status": i.status, "priority": i.priority} for i in issues
    ]
    return result(
        summary={"issues": len(rows), "newStatus": values["status"]},
        tables=[
            table(
                "BCF topics",
                [
                    ("id", "Topic"),
                    ("title", "Title"),
                    ("status", "Status"),
                    ("priority", "Priority"),
                ],
                rows,
            )
        ],
        notes=["Topic is backed by the coordination issue workflow and can be exchanged as BCF."],
    )


@feature(
    "mepIssues.bcfViewpoints",
    "BCF Viewpoints",
    part="mep",
    fields=[
        text("viewpoint", "Viewpoint name", "Issue camera"),
        number("x", "Camera X", 0, unit="mm"),
        number("y", "Camera Y", 0, unit="mm"),
        number("z", "Camera Z", 3000, unit="mm"),
    ],
    requires_project=False,
)
def bcf_viewpoints(ctx, values):
    p = [values["x"], values["y"], values["z"]]
    return result(
        summary={"viewpoint": values["viewpoint"], "pointMm": p},
        tables=[
            table(
                "BCF viewpoint",
                [("axis", "Axis"), ("value", "Value", "mm")],
                [
                    {"axis": "X", "value": p[0]},
                    {"axis": "Y", "value": p[1]},
                    {"axis": "Z", "value": p[2]},
                ],
            )
        ],
        notes=[
            "Point is stored as a viewpoint origin; orientation requires a separate target and camera direction."
        ],
    )


@feature(
    "mepIssues.assignIssues",
    "Assign Issues",
    part="mep",
    fields=[
        text("assignee", "Assignee", ""),
        text("due", "Due date", ""),
        select(
            "priority",
            "Priority",
            [("low", "Low"), ("normal", "Normal"), ("high", "High"), ("critical", "Critical")],
            "normal",
        ),
    ],
    requires_project=True,
)
def assign_issues(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    rows = [
        {
            "id": i.id,
            "assignee": values["assignee"] or i.assignedTo,
            "due": values["due"] or i.dueDate,
            "priority": values["priority"],
        }
        for i in issues
    ]
    return result(
        summary={
            "assigned": len([r for r in rows if r["assignee"]]),
            "priority": values["priority"],
        },
        tables=[
            table(
                "Issue assignments",
                [
                    ("id", "Issue"),
                    ("assignee", "Assignee"),
                    ("due", "Due date"),
                    ("priority", "Priority"),
                ],
                rows,
            )
        ],
        notes=[
            "This prepares assignment data for coordination issues; due dates use ISO 8601 where available."
        ],
    )


@feature(
    "mepIssues.idsRules",
    "IDS Rules",
    part="mep",
    fields=[
        text("rule", "Rule name", "Required property"),
        text("property", "Property name", ""),
        text("value", "Required value", ""),
    ],
    requires_project=False,
)
def ids_rules(ctx, values):
    if not values["property"]:
        raise FeatureInputError("Enter the property name to check.")
    return result(
        summary={
            "rule": values["rule"],
            "property": values["property"],
            "required": values["value"],
        },
        tables=[
            table(
                "IDS rule",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Property", "value": values["property"]},
                    {"field": "Required", "value": values["value"]},
                ],
            )
        ],
        notes=["Rule is a declarative property constraint for model validation."],
    )


@feature(
    "mepIssues.requirementSets",
    "Requirement Sets",
    part="mep",
    fields=[
        text("set", "Requirement set", "MEP coordination"),
        checkbox("clash", "Clash checks", True),
        checkbox("ids", "IDS checks", True),
        checkbox("approval", "Approval checks", True),
    ],
    requires_project=False,
)
def requirement_sets(ctx, values):
    rows = [
        {"check": "Clash", "enabled": values["clash"]},
        {"check": "IDS", "enabled": values["ids"]},
        {"check": "Approval", "enabled": values["approval"]},
    ]
    return result(
        summary={"set": values["set"], "enabled": sum(r["enabled"] for r in rows)},
        tables=[table("Requirement set", [("check", "Check"), ("enabled", "Enabled")], rows)],
        notes=["Requirement sets control which model-validation scopes run together."],
    )


@feature(
    "mepIssues.checkHistory",
    "Check History",
    part="mep",
    fields=[number("limit", "Maximum history entries", 20, unit="runs", min=1, max=100)],
    requires_project=True,
)
def check_history(ctx, values):
    c = _coord(ctx)
    rows = [
        {"run": i.id, "status": i.status, "modified": i.modified or i.created}
        for i in (c.issues if c else [])[: int(values["limit"])]
    ]
    return result(
        summary={"entries": len(rows)},
        tables=[
            table(
                "Check history",
                [("run", "Run/Issue"), ("status", "Status"), ("modified", "Modified")],
                rows,
            )
        ],
        notes=["Project history is represented by issue status and modification records."],
    )


@feature(
    "mepIssues.issueStatus",
    "Issue Status",
    part="mep",
    fields=[
        select(
            "status",
            "Status",
            [
                ("new", "New"),
                ("active", "Active"),
                ("reviewed", "Reviewed"),
                ("approved", "Approved"),
                ("resolved", "Resolved"),
                ("closed", "Closed"),
            ],
            "new",
        )
    ],
    requires_project=True,
)
def issue_status(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    counts = {
        s: sum(i.status == s for i in issues)
        for s in ("new", "active", "reviewed", "approved", "resolved", "closed")
    }
    rows = [{"status": s, "count": n} for s, n in counts.items()]
    return result(
        summary={
            "selected": values["status"],
            "open": sum(counts[s] for s in ("new", "active", "reviewed")),
        },
        tables=[table("Issue status", [("status", "Status"), ("count", "Count")], rows)],
        notes=["Status follows the coordination issue workflow."],
    )


@feature(
    "mepIssues.dueDates",
    "Due Dates",
    part="mep",
    fields=[text("today", "Reference date", "2026-11-24")],
    requires_project=True,
)
def due_dates(ctx, values):
    c = _coord(ctx)
    rows = [
        {"id": i.id, "assignee": i.assignedTo, "due": i.dueDate, "priority": i.priority}
        for i in (c.issues if c else [])
        if i.dueDate
    ]
    return result(
        summary={"datedIssues": len(rows), "referenceDate": values["today"]},
        tables=[
            table(
                "Due dates",
                [
                    ("id", "Issue"),
                    ("assignee", "Assignee"),
                    ("due", "Due date"),
                    ("priority", "Priority"),
                ],
                rows,
            )
        ],
        notes=["Compare due dates against the entered reference date in the issue board."],
    )


@feature(
    "mepIssues.priorityMatrix",
    "Priority Matrix",
    part="mep",
    fields=[
        select(
            "priority",
            "Priority",
            [("low", "Low"), ("normal", "Normal"), ("high", "High"), ("critical", "Critical")],
            "normal",
        )
    ],
    requires_project=True,
)
def priority_matrix(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    rows = [
        {"priority": p, "count": sum(i.priority == p for i in issues)}
        for p in ("low", "normal", "high", "critical")
    ]
    return result(
        summary={
            "selected": values["priority"],
            "critical": sum(i.priority == "critical" for i in issues),
        },
        tables=[table("Priority matrix", [("priority", "Priority"), ("count", "Count")], rows)],
        notes=["Priority counts are derived from coordination issues."],
    )


@feature(
    "mepIssues.assigneeLoad",
    "Assignee Load",
    part="mep",
    fields=[checkbox("openOnly", "Open issues only", True)],
    requires_project=True,
)
def assignee_load(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    if values["openOnly"]:
        issues = [i for i in issues if i.status not in ("resolved", "closed")]
    loads = {}
    for i in issues:
        loads[i.assignedTo or "Unassigned"] = loads.get(i.assignedTo or "Unassigned", 0) + 1
    rows = [{"assignee": k, "count": v} for k, v in sorted(loads.items())]
    return result(
        summary={"assignees": len(rows), "issues": sum(loads.values())},
        tables=[table("Assignee load", [("assignee", "Assignee"), ("count", "Open count")], rows)],
        notes=["Load is the number of issues assigned to each person."],
    )


@feature(
    "mepIssues.issueDashboard", "Issue Dashboard", part="mep", fields=[], requires_project=True
)
def issue_dashboard(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    open_count = sum(i.status not in ("resolved", "closed") for i in issues)
    return result(
        summary={"total": len(issues), "open": open_count, "closed": len(issues) - open_count},
        tables=[
            table(
                "Issue dashboard",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Total", "value": len(issues)},
                    {"metric": "Open", "value": open_count},
                    {"metric": "Closed", "value": len(issues) - open_count},
                ],
            )
        ],
        notes=["Counts reflect coordination issue status."],
    )


@feature(
    "mepIssues.closedIssues",
    "Closed Issues",
    part="mep",
    fields=[checkbox("includeResolved", "Include resolved", True)],
    requires_project=True,
)
def closed_issues(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    statuses = ("resolved", "closed") if values["includeResolved"] else ("closed",)
    rows = [
        {"id": i.id, "title": i.title, "status": i.status, "modified": i.modified}
        for i in issues
        if i.status in statuses
    ]
    return result(
        summary={"count": len(rows)},
        tables=[
            table(
                "Closed issues",
                [
                    ("id", "Issue"),
                    ("title", "Title"),
                    ("status", "Status"),
                    ("modified", "Modified"),
                ],
                rows,
            )
        ],
        notes=["The list separates resolved and closed issues according to the workflow."],
    )


@feature(
    "mepIssues.issueTrends",
    "Issue Trends",
    part="mep",
    fields=[number("periods", "Trend periods", 8, unit="periods", min=2, max=52)],
    requires_project=True,
)
def issue_trends(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    rows = [
        {
            "period": i + 1,
            "open": sum(j.status not in ("resolved", "closed") for j in issues if i >= 0),
        }
        for i in range(int(values["periods"]))
    ]
    return result(
        summary={
            "periods": len(rows),
            "currentOpen": sum(i.status not in ("resolved", "closed") for i in issues),
        },
        tables=[table("Issue trend", [("period", "Period"), ("open", "Open issues")], rows)],
        notes=[
            "Historical period values require issue timestamps; current open counts are shown uniformly until snapshots are available."
        ],
    )


@feature(
    "mepIssues.milestoneIssues",
    "Milestone Issues",
    part="mep",
    fields=[text("milestone", "Milestone", "Stage 1")],
    requires_project=True,
)
def milestone_issues(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    rows = [{"id": i.id, "title": i.title, "due": i.dueDate, "status": i.status} for i in issues]
    return result(
        summary={"milestone": values["milestone"], "issueCount": len(rows)},
        tables=[
            table(
                "Milestone issues",
                [("id", "Issue"), ("title", "Title"), ("due", "Due"), ("status", "Status")],
                rows,
            )
        ],
        notes=["Milestone grouping is prepared for issue due-date or workflow integration."],
    )


@feature(
    "mepIssues.exportIssueList",
    "Export Issue List",
    part="mep",
    fields=[text("name", "Export name", "mep-issues")],
    requires_project=True,
)
def export_issue_list(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    out = ctx.path("11 Exports")
    if ctx.root and out:
        out.mkdir(parents=True, exist_ok=True)
        file = out / f"{values['name']}.csv"
        import csv

        with file.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "title", "status", "priority", "assignee", "due"])
            [
                w.writerow([i.id, i.title, i.status, i.priority, i.assignedTo, i.dueDate])
                for i in issues
            ]
        path = str(file)
    else:
        path = "Project root unavailable"
    return result(
        summary={"exportedIssues": len(issues), "output": path},
        tables=[
            table(
                "Issue export",
                [("field", "Field"), ("count", "Count")],
                [{"field": "Issues", "count": len(issues)}],
            )
        ],
        notes=[f"Exported issue list: {path}"],
    )


@feature(
    "mepIssues.syncToTracker",
    "Sync To Tracker",
    part="mep",
    fields=[text("tracker", "Tracker name", "Local issue tracker")],
    requires_project=True,
)
def sync_to_tracker(ctx, values):
    c = _coord(ctx)
    count = len(c.issues) if c else 0
    return result(
        summary={"tracker": values["tracker"], "issueCount": count, "networkCalls": 0},
        tables=[
            table(
                "Tracker sync",
                [("item", "Item"), ("count", "Count")],
                [{"item": "Issues prepared", "count": count}],
            )
        ],
        notes=[
            "No network synchronization is performed; export or integration data is prepared deterministically."
        ],
    )


@feature(
    "mepIssues.attachSnapshots",
    "Attach Snapshots",
    part="mep",
    fields=[text("snapshot", "Snapshot reference", "coordination-view.png")],
    requires_project=True,
)
def attach_snapshots(ctx, values):
    c = _coord(ctx)
    count = len(c.issues) if c else 0
    return result(
        summary={"snapshot": values["snapshot"], "issues": count},
        tables=[
            table(
                "Snapshot attachments",
                [("attachment", "Attachment"), ("issues", "Target issues")],
                [{"attachment": values["snapshot"], "issues": count}],
            )
        ],
        notes=["Snapshot reference is recorded for issue attachment workflows."],
    )


@feature(
    "mepIssues.commentThread",
    "Comment Thread",
    part="mep",
    fields=[text("issue", "Issue id", ""), text("comment", "Comment", "")],
    requires_project=True,
)
def comment_thread(ctx, values):
    c = _coord(ctx)
    issue = next((i for i in c.issues if i.id == values["issue"]), None) if c else None
    if not values["issue"]:
        raise FeatureInputError("Enter the issue id.")
    rows = [
        {"author": x.author, "date": x.date, "text": x.text}
        for x in (issue.comments if issue else [])
    ]
    return result(
        summary={"issue": values["issue"], "comments": len(rows)},
        tables=[
            table(
                "Issue comments",
                [("author", "Author"), ("date", "Date"), ("text", "Comment")],
                rows,
            )
        ],
        notes=[
            "The entered comment is not persisted unless the workflow writes it back to mep.json."
        ],
    )


@feature(
    "mepIssues.issueReport",
    "Issue Report",
    part="mep",
    fields=[text("name", "Report name", "mep-issues")],
    requires_project=True,
)
def issue_report(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    open_count = sum(i.status not in ("resolved", "closed") for i in issues)
    return result(
        summary={
            "report": values["report"] if "report" in values else values["name"],
            "total": len(issues),
            "open": open_count,
        },
        tables=[
            table(
                "Issue report",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Total", "value": len(issues)},
                    {"metric": "Open", "value": open_count},
                ],
            )
        ],
        notes=["Use Export Issue List for a spreadsheet-ready issue data file."],
    )


@feature(
    "mepIssues.reviewMeeting",
    "Review Meeting",
    part="mep",
    fields=[
        text("meeting", "Meeting title", "Coordination review"),
        text("date", "Meeting date", "2026-11-24"),
        text("attendees", "Attendees", ""),
    ],
    requires_project=True,
)
def review_meeting(ctx, values):
    c = _coord(ctx)
    count = len(c.issues) if c else 0
    return result(
        summary={"meeting": values["meeting"], "date": values["date"], "issues": count},
        tables=[
            table(
                "Review meeting",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Attendees", "value": values["attendees"]},
                    {"item": "Open issues", "value": count},
                ],
            )
        ],
        notes=["Meeting agenda is prepared from the coordination issue inventory."],
    )


@feature(
    "mepIssues.issueCategories",
    "Issue Categories",
    part="mep",
    fields=[
        select(
            "category",
            "Category",
            [("clash", "Clash"), ("ids", "IDS"), ("manual", "Manual"), ("systems", "Systems")],
            "clash",
        )
    ],
    requires_project=True,
)
def issue_categories(ctx, values):
    c = _coord(ctx)
    issues = c.issues if c else []
    rows = [
        {"source": s, "count": sum(i.source == s for i in issues)}
        for s in ("clash", "ids", "bcf", "manual", "systems")
    ]
    return result(
        summary={
            "selected": values["category"],
            "count": sum(i.source == values["category"] for i in issues),
        },
        tables=[table("Issue categories", [("source", "Source"), ("count", "Count")], rows)],
        notes=["Categories come from issue source fields in the coordination model."],
    )
