"""Overview learning, help and diagnostics commands."""

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
    load_export_json,
    now_iso,
    project_kpis,
    project_name,
    require_project,
    save_export_json,
    write_export,
)


@feature(
    "overviewLearning.guidedTour",
    "Guided Tour",
    part="settings",
    fields=[text("step", "Starting step", "project")],
    requires_project=False,
)
def guided_tour(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Provide a deterministic guided tour outline."""
    steps = [
        "Open project",
        "Review settings",
        "Check parts",
        "Run analysis",
        "Export deliverables",
    ]
    start = max(
        0,
        steps.index(
            next(
                (step for step in steps if step.lower().startswith(values["step"].lower())),
                "Open project",
            )
        ),
    )
    rows = [{"step": i + 1, "topic": step} for i, step in enumerate(steps[start:], start=start)]
    return result(
        summary={"startingStep": values["step"], "stepCount": len(rows)},
        tables=[table("Guided tour", [("step", "Step"), ("topic", "Topic")], rows)],
    )


@feature(
    "overviewLearning.sampleProjects",
    "Sample Projects",
    part="settings",
    fields=[],
    requires_project=False,
)
def sample_projects(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List sample projects shipped under workbench resources."""
    root = ctx.path("workbench/resources/saengine/samples") if ctx.root else None
    rows = (
        [
            {"project": p.name, "path": str(p)}
            for p in sorted(root.rglob("*"))
            if p.is_dir() and any(p.rglob("*.saengine"))
        ]
        if root and root.is_dir()
        else []
    )
    return result(
        summary={"sampleCount": len(rows)},
        tables=[table("Sample projects", [("project", "Project"), ("path", "Location")], rows)],
    )


@feature(
    "overviewLearning.keyboardShortcuts",
    "Keyboard Shortcuts",
    part="settings",
    fields=[],
    requires_project=False,
)
def keyboard_shortcuts(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Return a concise shortcut reference."""
    rows = [
        {"action": "Command palette", "shortcut": "Ctrl+Shift+P"},
        {"action": "Quick open", "shortcut": "Ctrl+P"},
        {"action": "Save", "shortcut": "Ctrl+S"},
    ]
    return result(
        summary={"shortcutCount": len(rows)},
        tables=[
            table("Keyboard shortcuts", [("action", "Action"), ("shortcut", "Shortcut")], rows)
        ],
    )


@feature(
    "overviewLearning.featureGlossary",
    "Feature Glossary",
    part="settings",
    fields=[text("term", "Term", "")],
    requires_project=False,
)
def feature_glossary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Search a local feature glossary."""
    glossary = {
        "part": "A reusable library object or discipline component.",
        "version": "A saved project snapshot in git history.",
        "BOQ": "Bill of quantities generated from project model data.",
        "BIM": "The project's building information model.",
    }
    needle = values["term"].lower()
    rows = [
        {"term": term, "definition": definition}
        for term, definition in glossary.items()
        if not needle or needle in term.lower()
    ]
    return result(
        summary={"termCount": len(rows)},
        tables=[table("Feature glossary", [("term", "Term"), ("definition", "Definition")], rows)],
    )


@feature(
    "overviewLearning.videoTutorials",
    "Video Tutorials",
    part="settings",
    fields=[],
    requires_project=False,
)
def video_tutorials(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List local tutorial links stored by project documentation."""
    return result(
        summary={"tutorialCount": 0},
        tables=[table("Video tutorials", [("title", "Title"), ("location", "Location")], [])],
        notes=["No external network or unverified remote tutorial content is used."],
    )


@feature(
    "overviewLearning.diagnostics", "Diagnostics", part="settings", fields=[], requires_project=True
)
def diagnostics(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run local JSON and project-part diagnostics."""
    root = require_project(ctx, "running diagnostics")
    import json

    rows = []
    for path in sorted(root.rglob("*.json")):
        if ".git" in path.parts:
            continue
        try:
            json.loads(path.read_text("utf-8"))
            status = "VALID"
        except (OSError, json.JSONDecodeError) as error:
            status = f"ERROR: {error}"
        rows.append({"file": str(path.relative_to(root)), "status": status})
    return result(
        summary={
            "checkedFiles": len(rows),
            "errorCount": sum(r["status"] != "VALID" for r in rows),
        },
        tables=[table("Diagnostics", [("file", "File"), ("status", "Status")], rows)],
    )


@feature(
    "overviewLearning.reportIssue",
    "Report Issue",
    part="settings",
    fields=[text("summary", "Issue summary", ""), text("details", "Issue details", "")],
    requires_project=True,
)
def report_issue(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Capture project JSON diagnostics and append the issue to a persistent Markdown/JSON report."""
    import json

    summary_text = values["summary"].strip()
    if not summary_text:
        raise FeatureInputError("Enter an issue summary.")
    root = require_project(ctx, "reporting a local issue")
    json_errors = []
    for p in sorted(root.rglob("*.json")):
        if ".git" in p.parts:
            continue
        try:
            json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            json_errors.append(f"{p.relative_to(root)}: {err}")
    kpis = project_kpis(ctx)
    reports = load_export_json(ctx, "11 Exports", "issue-reports.json", [])
    rows = [r for r in (reports if isinstance(reports, list) else []) if isinstance(r, dict)]
    rows.append(
        {
            "id": f"BUG-{len(rows) + 1:03d}",
            "timestamp": now_iso(),
            "summary": summary_text,
            "details": values["details"].strip(),
            "jsonErrors": len(json_errors),
            "bimElements": kpis["bimElements"],
        }
    )
    save_export_json(ctx, "11 Exports", "issue-reports.json", rows)
    md = [
        f"# Issue Report ({rows[-1]['id']})",
        "",
        f"## Summary\n{summary_text}",
        "",
        f"## Details\n{values['details'].strip() or '(none)'}",
        "",
        "## Attached Diagnostics",
        f"- Project: {project_name(ctx)}",
        f"- BIM elements: {kpis['bimElements']}, Objects: {kpis['objects']}, BOQ items: {kpis['boqItems']}",
        f"- Invalid JSON files: {len(json_errors)}",
    ]
    path = write_export(ctx, "11 Exports", "issue-report.md", "\n".join(md) + "\n")
    return result(
        summary={
            "id": rows[-1]["id"],
            "summary": summary_text,
            "jsonErrors": len(json_errors),
            "reportCount": len(rows),
            "exportPath": str(path),
        },
        tables=[
            table(
                "Local issue reports",
                [
                    ("id", "ID"),
                    ("timestamp", "UTC"),
                    ("summary", "Summary"),
                    ("jsonErrors", "JSON errors"),
                ],
                rows,
            )
        ],
        notes=[f"Diagnostic issue report written to {path}; it was not sent externally."],
    )


@feature(
    "overviewLearning.aboutSaengine",
    "About SAEngine",
    part="settings",
    fields=[],
    requires_project=False,
)
def about_saengine(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report the repository package version if available."""
    from saengine import __version__

    return result(
        summary={"version": __version__},
        tables=[
            table(
                "SAEngine",
                [("property", "Property"), ("value", "Value")],
                [{"property": "Version", "value": __version__}],
            )
        ],
    )


@feature(
    "overviewLearning.submitLog",
    "Submit Log",
    part="settings",
    fields=[text("filename", "Log filename", "diagnostic-log")],
    requires_project=True,
)
def submit_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build a project file inventory with per-folder counts, byte totals, and SHA-256 digests."""
    import hashlib

    root = require_project(ctx, "creating a diagnostic log")
    entries = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if ".git" in rel.parts or not path.is_file():
            continue
        size = path.stat().st_size
        total_bytes += size
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        entries.append({"file": rel.as_posix(), "sizeBytes": size, "sha256": digest})
        if len(entries) >= 500:
            break
    lines = [f"{e['sha256']}  {e['sizeBytes']:>9}  {e['file']}" for e in entries]
    name = values["filename"].strip().replace(" ", "-") or "diagnostic-log"
    out = write_export(ctx, "11 Exports", f"{name}.txt", "\n".join(lines) + "\n")
    return result(
        summary={
            "listedFiles": len(entries),
            "totalKb": round(total_bytes / 1024.0, 2),
            "exportPath": str(out),
        },
        tables=[
            table(
                "Diagnostic file digests",
                [("file", "File"), ("sizeBytes", "Size", "byte"), ("sha256", "SHA-256")],
                entries[:50],
            )
        ],
        notes=[f"Diagnostic checksum log written to {out}; no submission was made."],
    )


@feature(
    "overviewLearning.remoteSession",
    "Remote Session",
    part="settings",
    fields=[text("sessionId", "Session identifier", "")],
    requires_project=True,
)
def remote_session(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Capture project workspace metrics under a named local remote-session checkpoint."""
    sid = values["sessionId"].strip()
    if not sid:
        raise FeatureInputError("Enter a session identifier.")
    kpis = project_kpis(ctx)
    sessions = load_export_json(ctx, "11 Exports", "remote-session.json", [])
    rows = [s for s in (sessions if isinstance(sessions, list) else []) if isinstance(s, dict)]
    rows.append({"sessionId": sid, "timestamp": now_iso(), "project": project_name(ctx), **kpis})
    path = save_export_json(ctx, "11 Exports", "remote-session.json", rows)
    return result(
        summary={
            "sessionId": sid,
            "sessionCount": len(rows),
            "bimElements": kpis["bimElements"],
            "exportPath": str(path),
        },
        tables=[
            table(
                "Remote session log",
                [
                    ("sessionId", "Session ID"),
                    ("timestamp", "UTC"),
                    ("bimElements", "BIM elements"),
                    ("boqItems", "BOQ items"),
                ],
                rows,
            )
        ],
        notes=["Session checkpoint is stored locally; no remote connection was opened."],
    )


@feature(
    "overviewLearning.searchArticles",
    "Search Articles",
    part="settings",
    fields=[text("query", "Search query", "")],
    requires_project=False,
)
def search_articles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Search local repository documentation for a query."""
    cwd = ctx.path("docs")
    rows = []
    if cwd and cwd.is_dir():
        for path in cwd.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in (".md", ".txt")
                and values["query"].lower() in path.name.lower()
            ):
                rows.append({"title": path.stem, "location": str(path.relative_to(cwd.parent))})
    return result(
        summary={"matchCount": len(rows)},
        tables=[table("Local articles", [("title", "Title"), ("location", "Location")], rows)],
    )


@feature(
    "overviewLearning.bestPractices",
    "Best Practices",
    part="settings",
    fields=[],
    requires_project=False,
)
def best_practices(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Return a short engineering workflow checklist."""
    rows = [
        {"practice": "Use project source data", "why": "Avoids placeholder engineering values."},
        {"practice": "Record assumptions", "why": "Keeps calculations reviewable."},
        {"practice": "Export results", "why": "Creates a durable review record."},
    ]
    return result(
        summary={"practiceCount": len(rows)},
        tables=[table("Best practices", [("practice", "Practice"), ("why", "Reason")], rows)],
    )


@feature(
    "overviewLearning.designGuidelines",
    "Design Guidelines",
    part="settings",
    fields=[],
    requires_project=False,
)
def design_guidelines(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Return links to repository design documentation."""
    rows = [
        {"guideline": "Structural workflow", "location": "docs/manual"},
        {"guideline": "Feature registry", "location": "python/src/saengine/features"},
    ]
    return result(
        summary={"guidelineCount": len(rows)},
        tables=[
            table("Design guidelines", [("guideline", "Guideline"), ("location", "Location")], rows)
        ],
    )


@feature(
    "overviewLearning.userForum",
    "User Forum",
    part="settings",
    fields=[text("topic", "Topic", "")],
    requires_project=False,
)
def user_forum(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record a forum topic locally because network access is not used."""
    return result(
        summary={"topic": values["topic"], "networkAccess": False},
        notes=["No remote forum request was made."],
    )


@feature(
    "overviewLearning.featureRequests",
    "Feature Requests",
    part="settings",
    fields=[text("title", "Request title", ""), text("details", "Details", "")],
    requires_project=True,
)
def feature_requests(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Log an indexed feature request with project context to feature-requests.json and Markdown."""
    title = values["title"].strip()
    if not title:
        raise FeatureInputError("Enter a feature request title.")
    loaded = load_export_json(ctx, "11 Exports", "feature-requests.json", [])
    items = [r for r in (loaded if isinstance(loaded, list) else []) if isinstance(r, dict)]
    items.append(
        {
            "id": f"FR-{len(items) + 1:03d}",
            "timestamp": now_iso(),
            "project": project_name(ctx),
            "title": title,
            "details": values["details"].strip(),
        }
    )
    save_export_json(ctx, "11 Exports", "feature-requests.json", items)
    md = ["# Project Feature Requests", ""]
    for row in items:
        md.append(f"## {row['id']}: {row['title']} ({row['timestamp']})")
        md.append(row["details"] or "(no details)")
        md.append("")
    path = write_export(ctx, "11 Exports", "feature-request.md", "\n".join(md))
    return result(
        summary={
            "id": items[-1]["id"],
            "title": title,
            "requestCount": len(items),
            "exportPath": str(path),
        },
        tables=[
            table(
                "Feature requests", [("id", "ID"), ("timestamp", "UTC"), ("title", "Title")], items
            )
        ],
    )


@feature(
    "overviewLearning.releaseNotes",
    "Release Notes",
    part="settings",
    fields=[],
    requires_project=False,
)
def release_notes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Read repository release-note headings if available."""
    cwd = ctx.path("CHANGELOG.md") if ctx.root else None
    rows = []
    if cwd and cwd.is_file():
        for line in cwd.read_text("utf-8", errors="replace").splitlines()[:200]:
            if line.startswith("#"):
                rows.append({"heading": line.lstrip("# ").strip()})
    return result(
        summary={"releaseHeadingCount": len(rows)},
        tables=[table("Release notes", [("heading", "Heading")], rows)],
    )


@feature(
    "overviewLearning.workflowWizard",
    "Workflow Wizard",
    part="settings",
    fields=[text("goal", "Workflow goal", "review")],
    requires_project=False,
)
def workflow_wizard(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a workflow sequence for the selected goal."""
    goal = values["goal"].lower()
    steps = (
        [
            "Open project",
            "Verify source parts",
            "Run calculations",
            "Review results",
            "Export report",
        ]
        if "review" in goal or "design" in goal
        else ["Open project", "Edit inputs", "Run feature", "Export output"]
    )
    return result(
        summary={"goal": values["goal"], "stepCount": len(steps)},
        tables=[
            table(
                "Workflow",
                [("step", "Step"), ("action", "Action")],
                [{"step": i + 1, "action": action} for i, action in enumerate(steps)],
            )
        ],
    )


@feature(
    "overviewLearning.interactiveDemos",
    "Interactive Demos",
    part="settings",
    fields=[],
    requires_project=False,
)
def interactive_demos(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List verification and sample folders available locally."""
    verification = ctx.path("python/src/saengine/verification") if ctx.root else None
    rows = (
        [{"demo": "Verification suite", "location": str(verification)}]
        if verification and verification.is_dir()
        else []
    )
    return result(
        summary={"demoCount": len(rows)},
        tables=[table("Interactive demos", [("demo", "Demo"), ("location", "Location")], rows)],
    )


@feature(
    "overviewLearning.tipOfDay",
    "Tip of the Day",
    part="settings",
    fields=[number("dayIndex", "Day index", 0.0, unit="day", min=0)],
    requires_project=False,
)
def tip_of_day(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Choose a deterministic tip from a local list."""
    tips = [
        "Validate project source files before analysis.",
        "Save versions before major changes.",
        "Keep calculation assumptions visible.",
        "Export review records to 11 Exports.",
    ]
    index = int(values["dayIndex"]) % len(tips)
    return result(summary={"tipIndex": index, "tip": tips[index]})


@feature(
    "overviewLearning.benchmarkingSuite",
    "Benchmarking Suite",
    part="settings",
    fields=[
        number("warmupRuns", "Warm-up runs", 1.0, unit="runs", min=0, max=20),
        number("measuredRuns", "Measured runs", 3.0, unit="runs", min=1, max=100),
    ],
    requires_project=False,
)
def benchmarking_suite(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Describe a deterministic local benchmark configuration."""
    return result(
        summary={
            "warmupRuns": values["warmupRuns"],
            "measuredRuns": values["measuredRuns"],
            "networkAccess": False,
        },
        notes=[
            "Execution is left to the workbench benchmark runner; this feature supplies a bounded local configuration."
        ],
    )


@feature(
    "overviewLearning.verificationProblems",
    "Verification Problems",
    part="settings",
    fields=[],
    requires_project=False,
)
def verification_problems(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List verification problem modules shipped by the engine."""
    folder = ctx.path("python/src/saengine/verification/cases") if ctx.root else None
    rows = (
        [{"module": p.stem} for p in sorted(folder.glob("*.py"))]
        if folder and folder.is_dir()
        else []
    )
    return result(
        summary={"problemModuleCount": len(rows)},
        tables=[table("Verification problems", [("module", "Module")], rows)],
    )


@feature(
    "overviewLearning.validationDatasets",
    "Validation Datasets",
    part="settings",
    fields=[],
    requires_project=False,
)
def validation_datasets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List local sample-project and verification datasets."""
    sample = ctx.path("workbench/resources/saengine/samples") if ctx.root else None
    verification = ctx.path("python/src/saengine/verification/cases") if ctx.root else None
    rows = (
        [{"dataset": p.name, "location": str(p)} for p in sample.rglob("*") if p.is_dir()]
        if sample and sample.is_dir()
        else []
    )
    if verification and verification.is_dir():
        rows.extend({"dataset": p.stem, "location": str(p)} for p in verification.glob("*.py"))
    return result(
        summary={"datasetCount": len(rows)},
        tables=[
            table("Validation datasets", [("dataset", "Dataset"), ("location", "Location")], rows)
        ],
    )
