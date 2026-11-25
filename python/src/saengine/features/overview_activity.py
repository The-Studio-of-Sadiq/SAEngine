"""Overview activity and audit trail commands."""

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
    csv_text,
    json_text,
    load_export_json,
    now_iso,
    project_name,
    require_project,
    save_export_json,
    write_export,
)


def _history(ctx: FeatureContext) -> list[dict[str, Any]]:
    root = require_project(ctx, "viewing activity")
    from saengine.project import versions

    return versions.list_versions(str(root), 200)["versions"]


@feature(
    "overviewActivity.activityFeed",
    "Activity Feed",
    part="settings",
    fields=[number("limit", "Maximum entries", 20.0, unit="entries", min=1, max=200)],
    requires_project=True,
)
def activity_feed(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Show the latest saved project versions as an activity feed."""
    rows = [
        {
            "time": v["time"],
            "author": v["authorName"],
            "action": v["message"],
            "parts": ", ".join(v["parts"]),
        }
        for v in _history(ctx)[: int(values["limit"])]
    ]
    return result(
        summary={"activityCount": len(rows)},
        tables=[
            table(
                "Activity feed",
                [
                    ("time", "Time"),
                    ("author", "Author"),
                    ("action", "Activity"),
                    ("parts", "Parts"),
                ],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.changeHistory",
    "Change History",
    part="settings",
    fields=[],
    requires_project=True,
)
def change_history(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List versions and changed parts from project history."""
    rows = [
        {
            "version": v["id"],
            "time": v["time"],
            "author": v["authorName"],
            "parts": ", ".join(v["parts"]),
        }
        for v in _history(ctx)
    ]
    return result(
        summary={"changeCount": len(rows)},
        tables=[
            table(
                "Change history",
                [
                    ("version", "Version"),
                    ("time", "Time"),
                    ("author", "Author"),
                    ("parts", "Parts"),
                ],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.userSessions",
    "User Sessions",
    part="settings",
    fields=[],
    requires_project=True,
)
def user_sessions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise distinct recent authors as session records."""
    seen: dict[str, dict[str, Any]] = {}
    for item in _history(ctx):
        author = item["authorName"]
        seen.setdefault(author, {"author": author, "lastActivity": item["time"], "sessions": 0})
        seen[author]["sessions"] += 1
    rows = list(seen.values())
    return result(
        summary={"sessionCount": len(rows)},
        tables=[
            table(
                "User sessions",
                [
                    ("author", "Author"),
                    ("lastActivity", "Last activity"),
                    ("sessions", "Saved sessions"),
                ],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.filterEvents",
    "Filter Events",
    part="settings",
    fields=[text("author", "Author", ""), text("message", "Message contains", "")],
    requires_project=True,
)
def filter_events(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Filter project history by author and message text."""
    author = values["author"].lower()
    message = values["message"].lower()
    rows = [
        {"time": v["time"], "author": v["authorName"], "message": v["message"]}
        for v in _history(ctx)
        if (not author or author in v["authorName"].lower())
        and (not message or message in v["message"].lower())
    ]
    return result(
        summary={"eventCount": len(rows)},
        tables=[
            table(
                "Filtered activity",
                [("time", "Time"), ("author", "Author"), ("message", "Message")],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.timeRange",
    "Time Range",
    part="settings",
    fields=[
        text("startDate", "Start date YYYY-MM-DD", ""),
        text("endDate", "End date YYYY-MM-DD", ""),
    ],
    requires_project=True,
)
def time_range(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Limit project history by ISO date text."""
    start = values["startDate"].strip()
    end = values["endDate"].strip()
    rows = [
        {"time": v["time"], "author": v["authorName"], "message": v["message"]}
        for v in _history(ctx)
        if (not start or v["time"][:10] >= start) and (not end or v["time"][:10] <= end)
    ]
    return result(
        summary={"eventCount": len(rows)},
        tables=[
            table(
                "Events in time range",
                [("time", "Time"), ("author", "Author"), ("message", "Message")],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.auditTrail",
    "Audit Trail",
    part="settings",
    fields=[text("filename", "Audit filename", "audit-trail")],
    requires_project=True,
)
def audit_trail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the complete project version audit trail to CSV."""
    history = _history(ctx)
    rows = [
        {
            "id": v["id"],
            "time": v["time"],
            "author": v["authorName"],
            "message": v["message"],
            "parts": "; ".join(v["parts"]),
        }
        for v in history
    ]
    name = values["filename"].strip().replace(" ", "-") or "audit-trail"
    path = write_export(
        ctx,
        "11 Exports",
        f"{name}.csv",
        csv_text(["id", "time", "author", "message", "parts"], rows),
    )
    return result(
        summary={"auditEntries": len(rows), "exportPath": str(path)},
        notes=[f"Audit trail written to {path}."],
    )


@feature(
    "overviewActivity.restoreVersion",
    "Restore Version",
    part="settings",
    fields=[text("version", "Version ID", ""), text("parts", "Part IDs comma-separated", "")],
    requires_project=True,
)
def restore_version(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Restore selected parts without immediately committing (working-copy recovery)."""
    root = require_project(ctx, "restoring a version")
    version = values["version"].strip()
    if not version:
        raise FeatureInputError("Enter a version ID.")
    parts = [part.strip() for part in values["parts"].split(",") if part.strip()] or None
    from saengine.project import versions

    try:
        versions.restore(str(root), version, parts, commit=False)
    except versions.VersionsError as error:
        raise FeatureInputError(str(error)) from error
    return result(
        summary={"restored": True, "version": version},
        notes=["Restore left in the working copy and was not committed."],
    )


@feature(
    "overviewActivity.compareVersions",
    "Compare Versions",
    part="settings",
    fields=[text("a", "Earlier version", ""), text("b", "Later version or working", "working")],
    requires_project=True,
)
def compare_versions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare two project versions or one version against the working files."""
    root = require_project(ctx, "comparing versions")
    from saengine.project import versions

    compared = versions.diff(
        str(root), values["a"].strip() or None, values["b"].strip() or "working"
    )
    rows = [{"part": p["part"], "summary": p["summary"]} for p in compared["parts"]]
    return result(
        summary={"changedParts": len(rows), "problems": len(compared["problems"])},
        tables=[table("Version comparison", [("part", "Part"), ("summary", "Changes")], rows)],
        problems=compared["problems"],
    )


@feature(
    "overviewActivity.exportAudit",
    "Export Audit",
    part="settings",
    fields=[text("filename", "JSON filename", "audit-export")],
    requires_project=True,
)
def export_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export project version data as JSON."""
    history = _history(ctx)
    name = values["filename"].strip().replace(" ", "-") or "audit-export"
    path = write_export(ctx, "11 Exports", f"{name}.json", json_text(history))
    return result(
        summary={"auditEntries": len(history), "exportPath": str(path)},
        notes=[f"Audit export written to {path}."],
    )


@feature(
    "overviewActivity.securityLog",
    "Security Log",
    part="settings",
    fields=[],
    requires_project=True,
)
def security_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List project history entries that indicate security or access changes."""
    words = ("security", "permission", "access", "role", "lock")
    rows = [
        {"time": v["time"], "author": v["authorName"], "message": v["message"]}
        for v in _history(ctx)
        if any(word in v["message"].lower() for word in words)
    ]
    return result(
        summary={"securityEvents": len(rows)},
        tables=[
            table(
                "Security log",
                [("time", "Time"), ("author", "Author"), ("message", "Message")],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.activeUsers",
    "Active Users",
    part="settings",
    fields=[],
    requires_project=True,
)
def active_users(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List recent authors with their latest save activity."""
    latest: dict[str, str] = {}
    for item in _history(ctx):
        latest.setdefault(item["authorName"], item["time"])
    rows = [{"author": author, "lastActivity": time} for author, time in latest.items()]
    return result(
        summary={"activeUserCount": len(rows)},
        tables=[
            table(
                "Recent active users",
                [("author", "Author"), ("lastActivity", "Last activity")],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.sessionHistory",
    "Session History",
    part="settings",
    fields=[],
    requires_project=True,
)
def session_history(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Show chronological saved work sessions."""
    rows = [
        {"time": v["time"], "author": v["authorName"], "version": v["id"], "message": v["message"]}
        for v in reversed(_history(ctx))
    ]
    return result(
        summary={"sessionCount": len(rows)},
        tables=[
            table(
                "Session history",
                [
                    ("time", "Time"),
                    ("author", "Author"),
                    ("version", "Version"),
                    ("message", "Message"),
                ],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.broadcastNote",
    "Broadcast Note",
    part="settings",
    fields=[text("note", "Project note", "")],
    requires_project=True,
)
def broadcast_note(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Attach a timestamped note linked to the latest project version and update broadcast-note.md."""
    note_text = values["note"].strip()
    if not note_text:
        raise FeatureInputError("Enter a project note.")
    history = _history(ctx)
    latest_ver = history[0]["id"] if history else "uncommitted"
    entries = load_export_json(ctx, "11 Exports", "broadcast-log.json", [])
    log = [e for e in (entries if isinstance(entries, list) else []) if isinstance(e, dict)]
    log.append({"timestamp": now_iso(), "version": latest_ver, "note": note_text})
    save_export_json(ctx, "11 Exports", "broadcast-log.json", log)
    md = [f"# {project_name(ctx)} — Project Broadcast Log", ""]
    for item in reversed(log):
        md.append(f"- **{item['timestamp']}** (`{item['version']}`): {item['note']}")
    path = write_export(ctx, "11 Exports", "broadcast-note.md", "\n".join(md) + "\n")
    return result(
        summary={
            "noteLength": len(note_text),
            "entryCount": len(log),
            "version": latest_ver,
            "exportPath": str(path),
        },
        tables=[
            table(
                "Broadcast notes",
                [("timestamp", "UTC"), ("version", "Version"), ("note", "Note")],
                log,
            )
        ],
        notes=[f"Broadcast note appended to {path}."],
    )


@feature(
    "overviewActivity.performanceLogs",
    "Performance Logs",
    part="settings",
    fields=[],
    requires_project=True,
)
def performance_logs(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile project-history entries mentioning performance or checks."""
    words = ("performance", "check", "benchmark", "timing")
    rows = [
        {"time": v["time"], "message": v["message"]}
        for v in _history(ctx)
        if any(word in v["message"].lower() for word in words)
    ]
    return result(
        summary={"logCount": len(rows)},
        tables=[table("Performance logs", [("time", "Time"), ("message", "Message")], rows)],
    )


@feature(
    "overviewActivity.resourceUsage",
    "Resource Usage",
    part="settings",
    fields=[],
    requires_project=True,
)
def resource_usage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise project folder file usage as a resource table."""
    root = require_project(ctx, "checking resource usage")
    usage: dict[str, float] = {}
    for path in root.rglob("*"):
        if path.is_file():
            folder = (
                path.relative_to(root).parts[0] if len(path.relative_to(root).parts) > 1 else "root"
            )
            usage[folder] = usage.get(folder, 0.0) + path.stat().st_size
    rows = [
        {"resource": name, "sizeMb": round(size / 1024 / 1024, 3)}
        for name, size in sorted(usage.items())
    ]
    return result(
        summary={
            "resourceCount": len(rows),
            "totalMb": round(sum(usage.values()) / 1024 / 1024, 3),
        },
        tables=[
            table("Resource usage", [("resource", "Resource"), ("sizeMb", "Size", "MB")], rows)
        ],
    )


@feature(
    "overviewActivity.systemHealth",
    "System Health",
    part="settings",
    fields=[],
    requires_project=True,
)
def system_health(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report repository initialization and working-tree cleanliness."""
    root = require_project(ctx, "checking system health")
    from saengine.project import versions

    status = versions.status(str(root))
    return result(
        summary={
            "initialized": status["initialized"],
            "clean": status["clean"],
            "problemCount": len(status["problems"]),
        },
        tables=[
            table(
                "System health",
                [("check", "Check"), ("status", "Status")],
                [
                    {
                        "check": "Version history",
                        "status": "Initialized" if status["initialized"] else "Not initialized",
                    },
                    {"check": "Working tree", "status": "Clean" if status["clean"] else "Changed"},
                ],
            )
        ],
        problems=status["problems"],
    )


@feature(
    "overviewActivity.submissionLog",
    "Submission Log",
    part="settings",
    fields=[],
    requires_project=True,
)
def submission_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Filter project history for issue, review and submission messages."""
    words = ("submit", "submitted", "issue", "review", "approval")
    rows = [
        {"time": v["time"], "author": v["authorName"], "message": v["message"]}
        for v in _history(ctx)
        if any(word in v["message"].lower() for word in words)
    ]
    return result(
        summary={"submissionCount": len(rows)},
        tables=[
            table(
                "Submission log",
                [("time", "Time"), ("author", "Author"), ("message", "Message")],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.signOffHistory",
    "Sign-off History",
    part="settings",
    fields=[],
    requires_project=True,
)
def sign_off_history(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List issued or approved version records."""
    rows = [
        {
            "version": v["id"],
            "time": v["time"],
            "author": v["authorName"],
            "label": ", ".join(v["labels"]),
        }
        for v in _history(ctx)
        if v["issued"] or v["labels"]
    ]
    return result(
        summary={"signOffCount": len(rows)},
        tables=[
            table(
                "Sign-off history",
                [
                    ("version", "Version"),
                    ("time", "Time"),
                    ("author", "Author"),
                    ("label", "Label"),
                ],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.pendingApprovals",
    "Pending Approvals",
    part="settings",
    fields=[],
    requires_project=True,
)
def pending_approvals(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List history entries containing pending or approval words without issued status."""
    rows = [
        {"version": v["id"], "time": v["time"], "message": v["message"]}
        for v in _history(ctx)
        if not v["issued"]
        and any(
            word in v["message"].lower() for word in ("pending", "approval", "approve", "review")
        )
    ]
    return result(
        summary={"pendingCount": len(rows)},
        tables=[
            table(
                "Pending approvals",
                [("version", "Version"), ("time", "Time"), ("message", "Message")],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.cloudSyncStatus",
    "Cloud Sync Status",
    part="settings",
    fields=[],
    requires_project=True,
)
def cloud_sync_status(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report local and remote share status without network access."""
    root = require_project(ctx, "checking share status")
    from saengine.project import share

    status = share.status(str(root), fetch=False)
    return result(
        summary={
            "shared": status.get("shared", False),
            "ahead": status.get("ahead", 0),
            "behind": status.get("behind", 0),
        },
        tables=[
            table(
                "Cloud sync status",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": k, "value": str(v)}
                    for k, v in status.items()
                    if k not in ("people", "problems")
                ],
            )
        ],
        problems=status.get("problems", []),
    )


@feature(
    "overviewActivity.conflictHistory",
    "Conflict History",
    part="settings",
    fields=[],
    requires_project=True,
)
def conflict_history(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List version messages mentioning conflicts or merges."""
    rows = [
        {"time": v["time"], "author": v["authorName"], "message": v["message"]}
        for v in _history(ctx)
        if any(word in v["message"].lower() for word in ("conflict", "merge", "collision"))
    ]
    return result(
        summary={"conflictCount": len(rows)},
        tables=[
            table(
                "Conflict history",
                [("time", "Time"), ("author", "Author"), ("message", "Message")],
                rows,
            )
        ],
    )


@feature(
    "overviewActivity.syncErrors", "Sync Errors", part="settings", fields=[], requires_project=True
)
def sync_errors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report local share problems without attempting a network fetch."""
    root = require_project(ctx, "checking sync errors")
    from saengine.project import share

    status = share.status(str(root), fetch=False)
    problems = status.get("problems", [])
    return result(
        summary={"problemCount": len(problems), "shared": status.get("shared", False)},
        problems=problems,
    )
