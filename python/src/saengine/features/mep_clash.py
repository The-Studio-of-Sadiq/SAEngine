"""MEP clash detection and clash-tracking features."""

from __future__ import annotations

from saengine.features import (
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)


def _mep(ctx):
    from saengine.library.mep import parse

    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add 07 MEP/mep.json to the project.")
    return parse(__import__("json").dumps(raw))


@feature(
    "mepClash.clashMatrix",
    "Clash Matrix",
    part="mep",
    fields=[
        checkbox("includeArchitecture", "Include architecture", True),
        checkbox("includeStructure", "Include structure", True),
    ],
    requires_project=True,
)
def clash_matrix(ctx, values):
    mep = _mep(ctx)
    c = mep.coordination
    rows = [{"a": t.a, "b": t.b, "test": t.id, "kind": t.kind} for t in (c.tests if c else [])]
    return result(
        summary={"testCount": len(rows)},
        tables=[
            table(
                "Clash matrix",
                [("test", "Test"), ("a", "Set A"), ("b", "Set B"), ("kind", "Kind")],
                rows,
            )
        ],
        notes=["The matrix lists each configured clash test set pair."],
    )


@feature(
    "mepClash.disciplinePairs",
    "Discipline Pairs",
    part="mep",
    fields=[
        select(
            "a",
            "Set A",
            [
                ("structure", "Structure"),
                ("architecture", "Architecture"),
                ("mechanical", "Mechanical"),
                ("plumbing", "Plumbing"),
                ("electrical", "Electrical"),
                ("fire", "Fire"),
            ],
            "structure",
        ),
        select(
            "b",
            "Set B",
            [
                ("structure", "Structure"),
                ("architecture", "Architecture"),
                ("mechanical", "Mechanical"),
                ("plumbing", "Plumbing"),
                ("electrical", "Electrical"),
                ("fire", "Fire"),
            ],
            "mechanical",
        ),
    ],
    requires_project=False,
)
def discipline_pairs(ctx, values):
    return result(
        summary={"setA": values["a"], "setB": values["b"]},
        tables=[
            table(
                "Discipline pair",
                [("side", "Side"), ("discipline", "Discipline")],
                [
                    {"side": "A", "discipline": values["a"]},
                    {"side": "B", "discipline": values["b"]},
                ],
            )
        ],
        notes=["The pair is a coordinate-test rule between two element sets."],
    )


@feature(
    "mepClash.priorityRules",
    "Priority Rules",
    part="mep",
    fields=[
        select("kind", "Clash kind", [("hard", "Hard"), ("clearance", "Clearance")], "hard"),
        select(
            "priority",
            "Priority",
            [("low", "Low"), ("normal", "Normal"), ("high", "High"), ("critical", "Critical")],
            "high",
        ),
    ],
    requires_project=False,
)
def priority_rules(ctx, values):
    return result(
        summary={"clashKind": values["kind"], "priority": values["priority"]},
        tables=[
            table(
                "Priority rule",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Clash kind", "value": values["kind"]},
                    {"field": "Priority", "value": values["priority"]},
                ],
            )
        ],
        notes=["Priority rules classify detected geometry conflicts."],
    )


@feature(
    "mepClash.clashResults",
    "Clash Results",
    part="mep",
    fields=[
        select(
            "status", "Status", [("all", "All"), ("open", "Open"), ("resolved", "Resolved")], "all"
        )
    ],
    requires_project=True,
)
def clash_results(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    rows = [
        {"id": i.id, "title": i.title, "status": i.status, "priority": i.priority, "point": i.point}
        for i in issues
        if values["status"] == "all"
        or (values["status"] == "resolved" and i.status in ("resolved", "closed"))
        or (values["status"] == "open" and i.status not in ("resolved", "closed"))
    ]
    return result(
        summary={"count": len(rows)},
        tables=[
            table(
                "Clash results",
                [
                    ("id", "Issue"),
                    ("title", "Clash"),
                    ("status", "Status"),
                    ("priority", "Priority"),
                ],
                rows,
            )
        ],
        notes=[
            "Results come from coordination issue records, including clashes retained across test runs."
        ],
    )


@feature(
    "mepClash.groupClashes",
    "Group Clashes",
    part="mep",
    fields=[
        select(
            "group",
            "Group by",
            [("discipline", "Discipline"), ("level", "Level"), ("test", "Test")],
            "level",
        )
    ],
    requires_project=True,
)
def group_clashes(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    counts = {}
    for i in issues:
        key = (
            i.story
            if values["group"] == "level"
            else i.test or "manual"
            if values["group"] == "test"
            else i.source
        )
        counts[key or "Unassigned"] = counts.get(key or "Unassigned", 0) + 1
    rows = [{"group": k, "count": v} for k, v in sorted(counts.items())]
    return result(
        summary={"group": values["group"], "groups": len(rows)},
        tables=[table("Grouped clashes", [("group", "Group"), ("count", "Count")], rows)],
        notes=["Grouping uses the selected available field."],
    )


@feature(
    "mepClash.resolveSelected",
    "Resolve Selected",
    part="mep",
    fields=[
        text("issue", "Issue id", ""),
        text("reason", "Resolution reason", "Routed clear of clash"),
    ],
    requires_project=True,
)
def resolve_selected(ctx, values):
    if not values["issue"]:
        raise FeatureInputError("Enter the issue id.")
    mep = _mep(ctx)
    found = next(
        (
            i
            for i in (mep.coordination.issues if mep.coordination else [])
            if i.id == values["issue"]
        ),
        None,
    )
    if found is None:
        raise FeatureInputError(f"Issue {values['issue']} was not found.")
    return result(
        summary={"issue": values["issue"], "status": "resolved", "reason": values["reason"]},
        tables=[
            table(
                "Resolution",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Issue", "value": values["issue"]},
                    {"field": "Reason", "value": values["reason"]},
                ],
            )
        ],
        notes=["Resolution state must be written back to the project issue record."],
    )


@feature(
    "mepClash.clashReport",
    "Clash Report",
    part="mep",
    fields=[text("name", "Report name", "clash-report")],
    requires_project=True,
)
def clash_report(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    open_count = sum(i.status not in ("resolved", "closed") for i in issues)
    out = ctx.path("11 Exports")
    path = None
    if ctx.root and out:
        out.mkdir(parents=True, exist_ok=True)
        path = str(out / f"{values['name']}.md")
        (out / f"{values['name']}.md").write_text(
            f"# Clash Report\n\nOpen clashes: {open_count}\nTotal issues: {len(issues)}\n",
            encoding="utf-8",
        )
    return result(
        summary={
            "name": values["name"],
            "open": open_count,
            "total": len(issues),
            "output": path or "Project root unavailable",
        },
        tables=[
            table(
                "Clash report",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Open", "value": open_count},
                    {"metric": "Total", "value": len(issues)},
                ],
            )
        ],
        notes=[f"Report written to {path}" if path else "Project root unavailable"],
    )


@feature(
    "mepClash.exportClashCsv",
    "Export Clash CSV",
    part="mep",
    fields=[text("name", "Export name", "clashes")],
    requires_project=True,
)
def export_clash_csv(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    out = ctx.path("11 Exports")
    path = None
    if ctx.root and out:
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{values['name']}.csv"
        import csv

        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "title", "status", "priority", "test", "story"])
            [
                w.writerow([i.id, i.title, i.status, i.priority, i.test or "", i.story or ""])
                for i in issues
            ]
        path = str(path)
    return result(
        summary={"count": len(issues), "output": path or "Project root unavailable"},
        tables=[
            table(
                "CSV export",
                [("field", "Field"), ("count", "Count")],
                [{"field": "Issues", "count": len(issues)}],
            )
        ],
        notes=[f"Exported clash CSV: {path}" if path else "Project root unavailable"],
    )


@feature(
    "mepClash.trendChart",
    "Trend Chart",
    part="mep",
    fields=[number("periods", "Periods", 12, unit="periods", min=2, max=52)],
    requires_project=True,
)
def trend_chart(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    open_count = sum(i.status not in ("resolved", "closed") for i in issues)
    rows = [{"period": i + 1, "open": open_count} for i in range(int(values["periods"]))]
    return result(
        summary={"periods": int(values["periods"]), "currentOpen": open_count},
        tables=[table("Open clash trend", [("period", "Period"), ("open", "Open")], rows)],
        notes=[
            "A timestamped trend archive is required to calculate historical period-by-period counts."
        ],
    )


@feature(
    "mepClash.clashSets",
    "Clash Sets",
    part="mep",
    fields=[text("name", "Set name", "Mechanical vs Structure")],
    requires_project=True,
)
def clash_sets(ctx, values):
    mep = _mep(ctx)
    c = mep.coordination
    rows = [
        {"id": t.id, "name": t.name, "a": ",".join(t.a), "b": ",".join(t.b)}
        for t in (c.tests if c else [])
    ]
    return result(
        summary={"set": values["name"], "count": len(rows)},
        tables=[
            table(
                "Clash sets",
                [("id", "Test"), ("name", "Name"), ("a", "Set A"), ("b", "Set B")],
                rows,
            )
        ],
        notes=["Set membership is read from configured clash tests."],
    )


@feature(
    "mepClash.ruleSets",
    "Rule Sets",
    part="mep",
    fields=[text("name", "Rule set", "Standard coordination")],
    requires_project=True,
)
def rule_sets(ctx, values):
    mep = _mep(ctx)
    c = mep.coordination
    rows = [
        {
            "id": t.id,
            "kind": t.kind,
            "clearance": t.clearance,
            "tolerance": t.tolerance,
            "enabled": t.enabled,
        }
        for t in (c.tests if c else [])
    ]
    return result(
        summary={"name": values["name"], "rules": len(rows)},
        tables=[
            table(
                "Rule sets",
                [
                    ("id", "Rule"),
                    ("kind", "Kind"),
                    ("clearance", "Clearance", "mm"),
                    ("tolerance", "Tolerance", "mm"),
                    ("enabled", "Enabled"),
                ],
                rows,
            )
        ],
        notes=["Rule values are taken directly from configured clash tests."],
    )


@feature(
    "mepClash.toleranceSettings",
    "Tolerance Settings",
    part="mep",
    fields=[
        number("tolerance", "Hard tolerance", 2.0, unit="mm", min=0),
        number("clearance", "Clearance", 50.0, unit="mm", min=0),
    ],
    requires_project=False,
)
def tolerance_settings(ctx, values):
    return result(
        summary={"toleranceMm": values["tolerance"], "clearanceMm": values["clearance"]},
        tables=[
            table(
                "Tolerance settings",
                [("setting", "Setting"), ("value", "Value", "mm")],
                [
                    {"setting": "Hard overlap tolerance", "value": values["tolerance"]},
                    {"setting": "Clearance distance", "value": values["clearance"]},
                ],
            )
        ],
        notes=["These are test-input values, not accumulated tolerances."],
    )


@feature(
    "mepClash.ignoreRules",
    "Ignore Rules",
    part="mep",
    fields=[
        checkbox("sameModel", "Ignore within one model", True),
        checkbox("coordinated", "Ignore coordinated openings", True),
    ],
    requires_project=False,
)
def ignore_rules(ctx, values):
    return result(
        summary={"sameModel": values["sameModel"], "coordinated": values["coordinated"]},
        tables=[
            table(
                "Ignore rules",
                [("rule", "Rule"), ("enabled", "Enabled")],
                [
                    {"rule": "Within one model", "enabled": values["sameModel"]},
                    {"rule": "Coordinated sleeves/openings", "enabled": values["coordinated"]},
                ],
            )
        ],
        notes=["Ignore rules change which candidate clashes are reported."],
    )


@feature(
    "mepClash.testSchedule",
    "Test Schedule",
    part="mep",
    fields=[
        select(
            "frequency",
            "Frequency",
            [("daily", "Daily"), ("weekly", "Weekly"), ("milestone", "Milestone")],
            "weekly",
        ),
        checkbox("overnight", "Run overnight", True),
    ],
    requires_project=False,
)
def test_schedule(ctx, values):
    return result(
        summary={"frequency": values["frequency"], "overnight": values["overnight"]},
        tables=[
            table(
                "Clash test schedule",
                [("setting", "Setting"), ("value", "Value")],
                [
                    {"setting": "Frequency", "value": values["frequency"]},
                    {"setting": "Overnight", "value": values["overnight"]},
                ],
            )
        ],
        notes=[
            "Scheduling is a coordination workflow setting; it does not start a background process."
        ],
    )


@feature(
    "mepClash.clashBrowser",
    "Clash Browser",
    part="mep",
    fields=[text("filter", "Title filter", "")],
    requires_project=True,
)
def clash_browser(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    rows = [
        {"id": i.id, "title": i.title, "status": i.status, "priority": i.priority}
        for i in issues
        if not values["filter"] or values["filter"].lower() in i.title.lower()
    ]
    return result(
        summary={"count": len(rows)},
        tables=[
            table(
                "Clash browser",
                [
                    ("id", "Issue"),
                    ("title", "Title"),
                    ("status", "Status"),
                    ("priority", "Priority"),
                ],
                rows,
            )
        ],
        notes=["Browser listing is filtered locally from coordination issues."],
    )


@feature(
    "mepClash.clashStatus",
    "Clash Status",
    part="mep",
    fields=[
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
            "active",
        )
    ],
    requires_project=True,
)
def clash_status(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    count = sum(i.status == values["status"] for i in issues)
    return result(
        summary={"status": values["status"], "count": count},
        tables=[
            table(
                "Clash status",
                [("status", "Status"), ("count", "Count")],
                [{"status": values["status"], "count": count}],
            )
        ],
        notes=["Status comes from coordination issue records."],
    )


@feature(
    "mepClash.assignClash",
    "Assign Clash",
    part="mep",
    fields=[text("issue", "Issue id", ""), text("assignee", "Assignee", "")],
    requires_project=True,
)
def assign_clash(ctx, values):
    if not values["issue"]:
        raise FeatureInputError("Enter the clash issue id.")
    mep = _mep(ctx)
    issue = next(
        (
            i
            for i in (mep.coordination.issues if mep.coordination else [])
            if i.id == values["issue"]
        ),
        None,
    )
    if issue is None:
        raise FeatureInputError("Issue was not found.")
    return result(
        summary={"issue": values["issue"], "assignee": values["assignee"] or issue.assignedTo},
        tables=[
            table(
                "Clash assignment",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Issue", "value": values["issue"]},
                    {"field": "Assignee", "value": values["assignee"] or issue.assignedTo},
                ],
            )
        ],
        notes=["Assignment must be committed to the issue record."],
    )


@feature(
    "mepClash.clashComments",
    "Clash Comments",
    part="mep",
    fields=[text("issue", "Issue id", ""), text("comment", "Comment", "")],
    requires_project=True,
)
def clash_comments(ctx, values):
    if not values["issue"]:
        raise FeatureInputError("Enter the issue id.")
    mep = _mep(ctx)
    issue = next(
        (
            i
            for i in (mep.coordination.issues if mep.coordination else [])
            if i.id == values["issue"]
        ),
        None,
    )
    if issue is None:
        raise FeatureInputError("Issue was not found.")
    rows = [{"author": c.author, "date": c.date, "text": c.text} for c in issue.comments]
    return result(
        summary={"issue": values["issue"], "comments": len(rows)},
        tables=[
            table(
                "Clash comments",
                [("author", "Author"), ("date", "Date"), ("text", "Comment")],
                rows,
            )
        ],
        notes=["Entered comment requires persistence through the issue workflow."],
    )


@feature(
    "mepClash.clashSnapshot",
    "Clash Snapshot",
    part="mep",
    fields=[text("name", "Snapshot name", "clash snapshot")],
    requires_project=True,
)
def clash_snapshot(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    return result(
        summary={"name": values["name"], "issues": len(issues)},
        tables=[
            table(
                "Clash snapshot",
                [("item", "Item"), ("count", "Count")],
                [{"item": "Issues", "count": len(issues)}],
            )
        ],
        notes=["Snapshot captures the issue inventory, not rendered camera geometry."],
    )


@feature(
    "mepClash.clashSeverity",
    "Clash Severity",
    part="mep",
    fields=[
        select(
            "severity",
            "Severity",
            [("low", "Low"), ("normal", "Normal"), ("high", "High"), ("critical", "Critical")],
            "normal",
        )
    ],
    requires_project=True,
)
def clash_severity(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    count = sum(i.priority == values["severity"] for i in issues)
    return result(
        summary={"severity": values["severity"], "count": count},
        tables=[
            table(
                "Clash severity",
                [("severity", "Severity"), ("count", "Count")],
                [{"severity": values["severity"], "count": count}],
            )
        ],
        notes=["Severity is represented by issue priority."],
    )


@feature(
    "mepClash.repeatClash",
    "Repeat Clash",
    part="mep",
    fields=[text("key", "Clash key", "")],
    requires_project=True,
)
def repeat_clash(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    matches = [i for i in issues if not values["key"] or values["key"] in i.key]
    return result(
        summary={"key": values["key"], "matches": len(matches)},
        tables=[
            table(
                "Repeated clashes",
                [("id", "Issue"), ("key", "Key"), ("status", "Status")],
                [{"id": i.id, "key": i.key, "status": i.status} for i in matches],
            )
        ],
        notes=["Repeat detection compares stable clash keys against existing issues."],
    )


@feature(
    "mepClash.zoneSummary",
    "Zone Summary",
    part="mep",
    fields=[text("zone", "Zone", "")],
    requires_project=True,
)
def zone_summary(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    rows = [
        {"story": i.story or "Unassigned", "count": sum(j.story == i.story for j in issues)}
        for i in {j for j in issues if not values["zone"] or values["zone"] == j.story}
    ]
    return result(
        summary={"zone": values["zone"], "clashes": len(issues)},
        tables=[table("Clash zone summary", [("story", "Story"), ("count", "Count")], rows)],
        notes=["Zone summary uses issue story values."],
    )


@feature(
    "mepClash.modelComparison",
    "Model Comparison",
    part="mep",
    fields=[text("revisionA", "Revision A", "base"), text("revisionB", "Revision B", "current")],
    requires_project=True,
)
def model_comparison(ctx, values):
    mep = _mep(ctx)
    return result(
        summary={
            "revisionA": values["revisionA"],
            "revisionB": values["revisionB"],
            "equipment": len(mep.equipment),
            "openings": len(mep.openings),
        },
        tables=[
            table(
                "Model comparison",
                [("item", "Item"), ("revision", "Revision")],
                [
                    {"item": "Equipment", "revision": values["revisionB"]},
                    {"item": "Openings", "revision": values["revisionB"]},
                ],
            )
        ],
        notes=["External revision comparison requires archived model snapshots."],
    )


@feature(
    "mepClash.clashHeatMap",
    "Clash Heat Map",
    part="mep",
    fields=[number("cell", "Grid cell", 1000.0, unit="mm", min=100)],
    requires_project=True,
)
def clash_heat_map(ctx, values):
    mep = _mep(ctx)
    issues = mep.coordination.issues if mep.coordination else []
    rows = []
    for i in issues:
        if i.point:
            rows.append(
                {
                    "x": round(i.point[0] / values["cell"]) * values["cell"],
                    "y": round(i.point[1] / values["cell"]) * values["cell"],
                    "count": 1,
                }
            )
    grid = {}
    for r in rows:
        grid[(r["x"], r["y"])] = grid.get((r["x"], r["y"]), 0) + 1
    out = [{"x": k[0], "y": k[1], "count": v} for k, v in sorted(grid.items())]
    return result(
        summary={"cells": len(out), "clashes": sum(out[i]["count"] for i in range(len(out)))},
        tables=[
            table("Clash heat map", [("x", "X", "mm"), ("y", "Y", "mm"), ("count", "Count")], out)
        ],
        notes=["Heat map bins clash issue points on the entered grid."],
    )
