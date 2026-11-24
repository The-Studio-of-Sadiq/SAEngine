"""BIM model snapshot and version-management features."""

from __future__ import annotations

from typing import Any

from saengine.features import FeatureContext, FeatureInputError, feature, result, table, text
from saengine.features.bim_common import kind_counts, require_bim, write_bim_json


def _snapshots(data: dict[str, Any]) -> list[dict[str, Any]]:
    value = data.get("snapshots", [])
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _previous_elements(data: dict[str, Any]) -> list[dict[str, Any]]:
    value = data.get("previousElements")
    if not isinstance(value, list):
        raise FeatureInputError("Record a previous model version before comparing element changes.")
    return [element for element in value if isinstance(element, dict)]


@feature(
    "bimSummaryVersioning.createSnapshot",
    "Create Snapshot",
    part="bim",
    fields=[text("name", "Snapshot name", "Version C01"), text("author", "Author", "Project team")],
)
def create_snapshot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a named snapshot payload of the current model state."""
    data = require_bim(ctx)
    payload = {
        "name": values["name"],
        "author": values["author"],
        "elementIds": [e.get("id") for e in data["elements"]],
        "categories": kind_counts(data),
    }
    path = write_bim_json(ctx, f"snapshot-{values['name'].replace(' ', '-')}.json", payload)
    return result(
        summary={
            "snapshotName": values["name"],
            "elementCount": len(data["elements"]),
            "exportPath": path,
        }
    )


@feature(
    "bimSummaryVersioning.snapshotNotes",
    "Snapshot Notes",
    part="bim",
    fields=[text("name", "Snapshot name", "Version C01"), text("notes", "Purpose and author", "")],
)
def snapshot_notes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record purpose and author notes for a snapshot."""
    data = require_bim(ctx)
    payload = {"name": values["name"], "notes": values["notes"]}
    path = write_bim_json(ctx, "snapshot-notes.json", payload)
    return result(
        summary={
            "snapshotName": values["name"],
            "elementCount": len(data["elements"]),
            "exportPath": path,
        }
    )


@feature(
    "bimSummaryVersioning.compareSnapshots",
    "Compare Snapshots",
    part="bim",
    fields=[text("beforeName", "Before snapshot", ""), text("afterName", "After snapshot", "")],
)
def compare_snapshots(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Diff two snapshots recorded in the BIM model."""
    data = require_bim(ctx)
    snapshots = {str(s.get("name", "")): s for s in _snapshots(data)}
    if values["beforeName"] not in snapshots or values["afterName"] not in snapshots:
        raise FeatureInputError("Select two snapshot names that are recorded in the BIM model.")
    before = set(snapshots[values["beforeName"]].get("elementIds", []))
    after = set(snapshots[values["afterName"]].get("elementIds", []))
    rows = [{"id": x, "change": "Added"} for x in sorted(after - before)]
    rows += [{"id": x, "change": "Removed"} for x in sorted(before - after)]
    return result(
        summary={"addedCount": len(after - before), "removedCount": len(before - after)},
        tables=[table("Snapshot Differences", [("id", "Element"), ("change", "Change")], rows)],
    )


@feature(
    "bimSummaryVersioning.restoreSnapshot",
    "Restore Snapshot",
    part="bim",
    fields=[text("snapshotName", "Snapshot name", "")],
)
def restore_snapshot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report a restore instruction for a selected snapshot."""
    data = require_bim(ctx)
    snapshots = {str(s.get("name", "")): s for s in _snapshots(data)}
    found = values["snapshotName"] in snapshots
    return result(
        summary={"snapshotName": values["snapshotName"], "found": found},
        problems=[] if found else ["The named snapshot was not found in the BIM model."],
    )


@feature(
    "bimSummaryVersioning.autoBaseline",
    "Auto Baseline",
    part="bim",
    fields=[text("schedule", "Snapshot schedule", "Milestone")],
)
def auto_baseline(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure automatic snapshot capture on project milestones."""
    require_bim(ctx)
    payload = {"schedule": values["schedule"], "enabled": True}
    path = write_bim_json(ctx, "auto-baseline.json", payload)
    return result(summary={"schedule": values["schedule"], "enabled": True, "exportPath": path})


@feature("bimSummaryVersioning.addedElements", "Added Elements", part="bim")
def added_elements(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List elements introduced since the previous recorded version."""
    data = require_bim(ctx)
    previous = {str(e.get("id")) for e in _previous_elements(data)}
    now = {str(e.get("id")) for e in data["elements"]}
    rows = [{"id": x} for x in sorted(now - previous)]
    return result(
        summary={"addedCount": len(rows)},
        tables=[table("Added Elements", [("id", "Element id")], rows)],
    )


@feature("bimSummaryVersioning.removedElements", "Removed Elements", part="bim")
def removed_elements(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List elements deleted since the previous recorded version."""
    data = require_bim(ctx)
    previous = {str(e.get("id")) for e in _previous_elements(data)}
    now = {str(e.get("id")) for e in data["elements"]}
    rows = [{"id": x} for x in sorted(previous - now)]
    return result(
        summary={"removedCount": len(rows)},
        tables=[table("Removed Elements", [("id", "Element id")], rows)],
    )


@feature("bimSummaryVersioning.changedElements", "Changed Elements", part="bim")
def changed_elements(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List elements whose properties changed between recorded versions."""
    data = require_bim(ctx)
    before = {str(e.get("id")): e for e in _previous_elements(data)}
    rows = [
        {"id": k, "change": "Properties changed"}
        for k, e in ((str(e.get("id")), e) for e in data["elements"])
        if k in before and before[k] != e
    ]
    return result(
        summary={"changedCount": len(rows)},
        tables=[table("Changed Elements", [("id", "Element"), ("change", "Change")], rows)],
    )


@feature("bimSummaryVersioning.deltaSummary", "Delta Summary", part="bim")
def delta_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Show a one-page summary of version-to-version changes."""
    data = require_bim(ctx)
    before = {str(e.get("id")): e for e in _previous_elements(data)}
    now = {str(e.get("id")): e for e in data["elements"]}
    changed = sum(before[k] != e for k, e in now.items() if k in before)
    return result(
        summary={
            "addedCount": len(set(now) - set(before)),
            "removedCount": len(set(before) - set(now)),
            "changedCount": changed,
        }
    )


@feature("bimSummaryVersioning.activityLog", "Activity Log", part="bim")
def activity_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review edit history with authors and timestamps."""
    data = require_bim(ctx)
    rows = data.get("activityLog", [])
    rows = rows if isinstance(rows, list) else []
    return result(
        summary={"activityCount": len(rows)},
        tables=[
            table(
                "Activity Log",
                [("timestamp", "Time"), ("author", "Author"), ("action", "Action")],
                rows,
            )
        ],
    )


@feature("bimSummaryVersioning.versionTags", "Version Tags", part="bim")
def version_tags(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tag important model states for issue and audit."""
    data = require_bim(ctx)
    tags = data.get("versionTags", [])
    rows = tags if isinstance(tags, list) else []
    return result(
        summary={"tagCount": len(rows)},
        tables=[
            table("Version Tags", [("tag", "Tag"), ("state", "State"), ("date", "Date")], rows)
        ],
    )


@feature("bimSummaryVersioning.milestones", "Milestones", part="bim")
def version_milestones(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Mark key issue milestones on the version timeline."""
    data = require_bim(ctx)
    rows = data.get("milestones", [])
    rows = rows if isinstance(rows, list) else []
    return result(
        summary={"milestoneCount": len(rows)},
        tables=[
            table(
                "Milestones", [("name", "Milestone"), ("date", "Date"), ("status", "Status")], rows
            )
        ],
    )


@feature("bimSummaryVersioning.exportLog", "Export Log", part="bim")
def export_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the recorded version log for the project record."""
    data = require_bim(ctx)
    log = data.get("activityLog", [])
    path = write_bim_json(ctx, "bim-version-log.json", log)
    return result(summary={"activityCount": len(log), "exportPath": path})


@feature("bimSummaryVersioning.compareVisual", "Compare Visual", part="bim")
def compare_visual(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare an element-state overlay for visual comparison."""
    data = require_bim(ctx)
    before = {str(e.get("id")): e for e in _previous_elements(data)}
    now = {str(e.get("id")): e for e in data["elements"]}
    rows = [{"id": x, "state": "Added"} for x in sorted(set(now) - set(before))]
    rows += [{"id": x, "state": "Removed"} for x in sorted(set(before) - set(now))]
    rows += [
        {"id": x, "state": "Changed"} for x in sorted(set(before) & set(now)) if before[x] != now[x]
    ]
    return result(
        summary={"overlayCount": len(rows)},
        tables=[table("Visual Comparison", [("id", "Element"), ("state", "State")], rows)],
    )


@feature("bimSummaryVersioning.propertyDiff", "Property Diff", part="bim")
def property_diff(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List changed parameter values between model versions."""
    data = require_bim(ctx)
    before = {str(e.get("id")): e for e in _previous_elements(data)}
    rows = []
    for e in data["elements"]:
        old = before.get(str(e.get("id")))
        if old:
            for key in sorted(set(old) | set(e)):
                if old.get(key) != e.get(key):
                    rows.append(
                        {
                            "id": e.get("id", ""),
                            "property": key,
                            "before": str(old.get(key, "")),
                            "after": str(e.get(key, "")),
                        }
                    )
    return result(
        summary={"changedPropertyCount": len(rows)},
        tables=[
            table(
                "Property Differences",
                [
                    ("id", "Element"),
                    ("property", "Property"),
                    ("before", "Before"),
                    ("after", "After"),
                ],
                rows,
            )
        ],
    )


@feature("bimSummaryVersioning.geometricVariance", "Geometric Variance", part="bim")
def geometric_variance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure spatial coordinate differences between revisions."""
    data = require_bim(ctx)
    before = {str(e.get("id")): e for e in _previous_elements(data)}
    rows = []
    for e in data["elements"]:
        old = before.get(str(e.get("id")))
        if old:
            for key in ("position", "start", "end", "boundary"):
                if old.get(key) != e.get(key):
                    rows.append({"id": e.get("id", ""), "property": key})
    return result(
        summary={"geometricChangeCount": len(rows)},
        tables=[
            table(
                "Geometric Variances",
                [("id", "Element"), ("property", "Coordinate property")],
                rows,
            )
        ],
    )


@feature(
    "bimSummaryVersioning.createBranch",
    "Create Branch",
    part="bim",
    fields=[text("branchName", "Branch name", "Design Option A")],
)
def create_branch(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Fork active model state into a named design branch."""
    data = require_bim(ctx)
    payload = {
        "branch": values["branchName"],
        "elementIds": [e.get("id") for e in data["elements"]],
    }
    path = write_bim_json(ctx, f"branch-{values['branchName'].replace(' ', '-')}.json", payload)
    return result(
        summary={
            "branchName": values["branchName"],
            "elementCount": len(data["elements"]),
            "exportPath": path,
        }
    )


@feature(
    "bimSummaryVersioning.mergeBranch",
    "Merge Branch",
    part="bim",
    fields=[text("branchName", "Branch name", "Design Option A")],
)
def merge_branch(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare reconciliation of a branch back into the active model."""
    data = require_bim(ctx)
    return result(
        summary={"branchName": values["branchName"], "elementCount": len(data["elements"])},
        notes=[
            "Merge is reported by element data; file locking is handled by the project workbench."
        ],
    )


@feature("bimSummaryVersioning.branchHistory", "Branch History", part="bim")
def branch_history(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """View design option branches and merge records."""
    data = require_bim(ctx)
    branches = data.get("branches", [])
    rows = branches if isinstance(branches, list) else []
    return result(
        summary={"branchCount": len(rows)},
        tables=[
            table(
                "Branch History",
                [("name", "Branch"), ("parent", "Parent"), ("status", "Status")],
                rows,
            )
        ],
    )


@feature(
    "bimSummaryVersioning.publishModel",
    "Publish Model",
    part="bim",
    fields=[text("revision", "Published revision", "C01")],
)
def publish_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Package the validated model state for formal client issue."""
    data = require_bim(ctx)
    payload = {
        "revision": values["revision"],
        "elementCount": len(data["elements"]),
        "categories": kind_counts(data),
    }
    path = write_bim_json(ctx, f"published-model-{values['revision']}.json", payload)
    return result(
        summary={
            "revision": values["revision"],
            "elementCount": len(data["elements"]),
            "exportPath": path,
        }
    )


@feature("bimSummaryVersioning.revisionPackage", "Revision Package", part="bim")
def revision_package(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble revision delta drawings and change logs into an issuance payload."""
    data = require_bim(ctx)
    payload = {
        "elements": data["elements"],
        "activityLog": data.get("activityLog", []),
        "previousElements": data.get("previousElements", []),
    }
    path = write_bim_json(ctx, "revision-package.json", payload)
    return result(summary={"elementCount": len(data["elements"]), "exportPath": path})


@feature(
    "bimSummaryVersioning.freezeVersion",
    "Freeze Version",
    part="bim",
    fields=[text("version", "Version to freeze", "C01")],
)
def freeze_version(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Lock a named model version to prevent further geometric modifications."""
    data = require_bim(ctx)
    payload = {"version": values["version"], "frozen": True, "elementCount": len(data["elements"])}
    path = write_bim_json(ctx, f"freeze-{values['version']}.json", payload)
    return result(summary={"version": values["version"], "frozen": True, "exportPath": path})
