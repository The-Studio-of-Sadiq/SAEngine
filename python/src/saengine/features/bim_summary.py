"""BIM summary and project-information features."""

from __future__ import annotations

from typing import Any

from saengine.features import FeatureContext, FeatureInputError, feature, result, table, text
from saengine.features.bim_common import (
    element_extent,
    kind_counts,
    require_bim,
    write_bim_json,
)


@feature("bimSummary.modelStatistics", "Model Statistics", part="bim")
def model_statistics(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Count building elements and report the model extent."""
    data = require_bim(ctx)
    counts = kind_counts(data)
    extent = element_extent(data)
    return result(
        summary={
            "elementCount": len(data["elements"]),
            "categoryCount": len(counts),
            "extentXMm": extent["maxXMm"] - extent["minXMm"],
            "extentYMm": extent["maxYMm"] - extent["minYMm"],
        },
        tables=[
            table(
                "Elements by Category",
                [("kind", "Category"), ("count", "Count")],
                [{"kind": k, "count": v} for k, v in counts.items()],
            )
        ],
    )


@feature("bimSummary.elementCount", "Element Count", part="bim")
def element_count(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Break down element counts by category and level."""
    data = require_bim(ctx)
    counts = kind_counts(data)
    story_counts = {str(s.get("name", s.get("id", ""))): 0 for s in data.get("stories", [])}
    for element in data["elements"]:
        elevation = element.get("elevation", element.get("top"))
        story = next(
            (str(s["name"]) for s in data.get("stories", []) if s.get("elevation") == elevation),
            "Unassigned",
        )
        story_counts[story] = story_counts.get(story, 0) + 1
    return result(
        summary={"elementCount": len(data["elements"])},
        tables=[
            table(
                "By Category",
                [("kind", "Category"), ("count", "Count")],
                [{"kind": k, "count": v} for k, v in counts.items()],
            ),
            table(
                "By Level",
                [("level", "Level"), ("count", "Count")],
                [{"level": k, "count": v} for k, v in story_counts.items()],
            ),
        ],
    )


@feature("bimSummary.volumeSummary", "Volume Summary", part="bim")
def volume_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise element volumes explicitly recorded in the model."""
    data = require_bim(ctx)
    totals: dict[str, tuple[int, float]] = {}
    for element in data["elements"]:
        if not isinstance(element, dict) or not isinstance(element.get("volumeM3"), (int, float)):
            continue
        kind = str(element.get("kind", "unknown"))
        count, volume = totals.get(kind, (0, 0.0))
        totals[kind] = count + 1, volume + float(element["volumeM3"])
    if not totals:
        raise FeatureInputError(
            "Record element volumes in 06 BIM/bim.json before running this summary."
        )
    rows = [
        {"kind": kind, "elementCount": count, "volumeM3": volume}
        for kind, (count, volume) in sorted(totals.items())
    ]
    return result(
        summary={
            "volumeM3": sum(row["volumeM3"] for row in rows),
            "quantifiedElementCount": sum(row["elementCount"] for row in rows),
            "categoryCount": len(rows),
        },
        tables=[
            table(
                "Volume Summary",
                [
                    ("kind", "Category"),
                    ("elementCount", "Elements"),
                    ("volumeM3", "Volume", "m³"),
                ],
                rows,
            )
        ],
    )


@feature("bimSummary.completionDashboard", "Completion Dashboard", part="bim")
def completion_dashboard(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assess source, geometry and type completeness by category."""
    data = require_bim(ctx)
    rows = []
    for kind, count in kind_counts(data).items():
        typed = sum(1 for e in data["elements"] if e.get("kind") == kind and e.get("type"))
        sourced = sum(1 for e in data["elements"] if e.get("kind") == kind and e.get("source"))
        rows.append(
            {
                "kind": kind,
                "typedPercent": typed / count * 100 if count else 0,
                "sourcedPercent": sourced / count * 100 if count else 0,
            }
        )
    return result(
        summary={"categoryCount": len(rows)},
        tables=[
            table(
                "Completeness",
                [
                    ("kind", "Category"),
                    ("typedPercent", "Typed", "%"),
                    ("sourcedPercent", "Sourced", "%"),
                ],
                rows,
            )
        ],
    )


@feature("bimSummary.milestones", "Milestones", part="bim")
def milestones(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List milestones recorded in the project model."""
    data = require_bim(ctx)
    return result(
        summary={
            "modelElementCount": len(data["elements"]),
            "milestoneCount": len(data.get("milestones", [])),
        },
        tables=[
            table(
                "Milestones",
                [("name", "Milestone"), ("date", "Date"), ("status", "Status")],
                data.get("milestones", []),
            )
        ],
    )


@feature("bimSummary.dataDrop", "Data Drop", part="bim")
def data_drop(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Package a model information summary for a contractual data drop."""
    data = require_bim(ctx)
    path = write_bim_json(
        ctx,
        "bim-data-drop.json",
        {
            "elements": len(data["elements"]),
            "stories": data.get("stories", []),
            "categories": kind_counts(data),
        },
    )
    return result(
        summary={"elementCount": len(data["elements"]), "exportPath": path},
        notes=[f"Data drop written to {path}."],
    )


@feature("bimSummary.modelProperties", "Model Properties", part="bim")
def model_properties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display model schema and top-level properties."""
    data = require_bim(ctx)
    return result(
        summary={
            "schema": str(data.get("schema", "")),
            "storyCount": len(data.get("stories", [])),
            "elementCount": len(data["elements"]),
        },
        tables=[
            table(
                "Model Properties",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": k, "value": str(v)}
                    for k, v in data.items()
                    if k not in ("elements",)
                ],
            )
        ],
    )


@feature(
    "bimSummary.projectMetadata",
    "Project Metadata",
    part="bim",
    fields=[
        text("projectName", "Project name", "SAEngine Project"),
        text("status", "Model status", "For Coordination"),
    ],
)
def project_metadata(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Add exchange metadata for the model export."""
    require_bim(ctx)
    metadata = {"name": values["projectName"], "status": values["status"], "discipline": "Building"}
    path = write_bim_json(ctx, "project-metadata.json", metadata)
    return result(
        summary={
            "projectName": values["projectName"],
            "status": values["status"],
            "exportPath": path,
        },
        notes=[f"Metadata written to {path}."],
    )


@feature("bimSummary.revisionInfo", "Revision Info", part="bim")
def revision_info(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List model revisions and source stamps."""
    data = require_bim(ctx)
    revisions = data.get("revisions", [])
    return result(
        summary={"revisionCount": len(revisions)},
        tables=[
            table(
                "Revisions",
                [("id", "Revision"), ("status", "Status"), ("date", "Date")],
                revisions if isinstance(revisions, list) else [],
            )
        ],
    )


@feature("bimSummary.storeyBreakdown", "Storey Breakdown", part="bim")
def storey_breakdown(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise element counts for every building storey."""
    data = require_bim(ctx)
    rows = []
    for storey in data.get("stories", []):
        elevation = storey.get("elevation")
        count = sum(
            1
            for e in data["elements"]
            if elevation in (e.get("elevation"), e.get("bottom"), e.get("top"))
        )
        rows.append(
            {
                "storey": storey.get("name", storey.get("id", "")),
                "elevationMm": elevation,
                "elementCount": count,
            }
        )
    return result(
        summary={"storeyCount": len(rows)},
        tables=[
            table(
                "Storey Breakdown",
                [
                    ("storey", "Storey"),
                    ("elevationMm", "Elevation", "mm"),
                    ("elementCount", "Elements"),
                ],
                rows,
            )
        ],
    )


@feature("bimSummary.categoryBreakdown", "Category Breakdown", part="bim")
def category_breakdown(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report element counts and object-type coverage by category."""
    data = require_bim(ctx)
    rows = []
    for kind, count in kind_counts(data).items():
        typed = sum(1 for e in data["elements"] if e.get("kind") == kind and e.get("type"))
        rows.append({"kind": kind, "elementCount": count, "typedCount": typed})
    return result(
        summary={"categoryCount": len(rows)},
        tables=[
            table(
                "Category Breakdown",
                [("kind", "Category"), ("elementCount", "Elements"), ("typedCount", "Typed")],
                rows,
            )
        ],
    )


@feature("bimSummary.materialBreakdown", "Material Breakdown", part="bim")
def material_breakdown(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group elements by recorded material assignment."""
    data = require_bim(ctx)
    counts: dict[str, int] = {}
    for element in data["elements"]:
        if isinstance(element, dict):
            material = str(element.get("material", "Unassigned"))
            counts[material] = counts.get(material, 0) + 1
    rows = [
        {"material": material, "elementCount": count} for material, count in sorted(counts.items())
    ]
    return result(
        summary={"materialCount": len(rows)},
        tables=[
            table(
                "Material Breakdown", [("material", "Material"), ("elementCount", "Elements")], rows
            )
        ],
    )


@feature("bimSummary.disciplineBreakdown", "Discipline Breakdown", part="bim")
def discipline_breakdown(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map structural element categories to a discipline summary."""
    data = require_bim(ctx)
    counts = kind_counts(data)
    rows = [{"discipline": "Structural", "elementCount": sum(counts.values())}]
    mep = ctx.raw("mep")
    if isinstance(mep, dict):
        rows.append(
            {
                "discipline": "MEP",
                "elementCount": sum(len(v) if isinstance(v, list) else 0 for v in mep.values()),
            }
        )
    return result(
        summary={"disciplineCount": len(rows)},
        tables=[
            table(
                "Discipline Breakdown",
                [("discipline", "Discipline"), ("elementCount", "Elements")],
                rows,
            )
        ],
    )


@feature("bimSummary.weightSummary", "Weight Summary", part="bim")
def weight_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sum element masses explicitly recorded in the BIM model."""
    data = require_bim(ctx)
    totals: dict[str, tuple[int, float]] = {}
    for element in data["elements"]:
        if not isinstance(element, dict) or not isinstance(element.get("massKg"), (int, float)):
            continue
        kind = str(element.get("kind", "unknown"))
        count, mass = totals.get(kind, (0, 0.0))
        totals[kind] = count + 1, mass + float(element["massKg"])
    if not totals:
        raise FeatureInputError(
            "Record element masses in 06 BIM/bim.json before running this summary."
        )
    rows = [
        {"kind": kind, "elementCount": count, "massKg": mass}
        for kind, (count, mass) in sorted(totals.items())
    ]
    mass_kg = sum(row["massKg"] for row in rows)
    return result(
        summary={
            "quantifiedElementCount": sum(row["elementCount"] for row in rows),
            "massKg": mass_kg,
            "massTonne": mass_kg / 1000,
        },
        tables=[
            table(
                "Weight",
                [
                    ("kind", "Category"),
                    ("elementCount", "Elements"),
                    ("massKg", "Mass", "kg"),
                ],
                rows,
            )
        ],
    )


@feature("bimSummary.warningSummary", "Warning Summary", part="bim")
def warning_summary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Rank missing types and sources as model warnings."""
    data = require_bim(ctx)
    missing_type = sum(1 for e in data["elements"] if not e.get("type"))
    missing_source = sum(1 for e in data["elements"] if not e.get("source"))
    rows = [
        {"severity": "Warning", "category": "Missing type", "count": missing_type},
        {"severity": "Info", "category": "No source", "count": missing_source},
    ]
    return result(
        summary={"warningCount": missing_type + missing_source},
        tables=[
            table(
                "Warnings",
                [("severity", "Severity"), ("category", "Category"), ("count", "Count")],
                rows,
            )
        ],
    )


@feature("bimSummary.linkStatus", "Link Status", part="bim")
def link_status(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report linked IFC and source-model status."""
    data = require_bim(ctx)
    mep = ctx.raw("mep")
    links = mep.get("ifcModels", []) if isinstance(mep, dict) else []
    rows = [
        {"name": str(x.get("name", x.get("file", ""))), "status": str(x.get("status", "Linked"))}
        for x in links
        if isinstance(x, dict)
    ]
    return result(
        summary={"linkCount": len(rows), "bimElementCount": len(data["elements"])},
        tables=[table("Linked Models", [("name", "Link"), ("status", "Status")], rows)],
    )


@feature("bimSummary.worksetStatus", "Workset Status", part="bim")
def workset_status(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report workset ownership stored in the BIM model, if present."""
    data = require_bim(ctx)
    worksets = data.get("worksets", [])
    rows = worksets if isinstance(worksets, list) else []
    return result(
        summary={"worksetCount": len(rows)},
        tables=[
            table("Worksets", [("name", "Workset"), ("owner", "Owner"), ("status", "Status")], rows)
        ],
    )


@feature("bimSummary.fileSizeReport", "File Size Report", part="bim")
def file_size_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report the on-disk size of the BIM model file."""
    data = require_bim(ctx)
    model_path = ctx.path(FeatureContext.PART_FILES["bim"])
    if model_path is None or not model_path.is_file():
        raise FeatureInputError("The BIM model file is unavailable for a file-size report.")
    size_bytes = model_path.stat().st_size
    return result(
        summary={
            "fileSizeBytes": size_bytes,
            "fileSizeKiB": size_bytes / 1024,
            "elementCount": len(data["elements"]),
        },
        tables=[
            table(
                "BIM File Size",
                [("file", "File"), ("sizeBytes", "Size", "bytes"), ("sizeKiB", "Size", "KiB")],
                [
                    {
                        "file": FeatureContext.PART_FILES["bim"],
                        "sizeBytes": size_bytes,
                        "sizeKiB": size_bytes / 1024,
                    }
                ],
            )
        ],
    )


@feature("bimSummary.purgeCandidates", "Purge Candidates", part="bim")
def purge_candidates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List object types that are unused by any current BIM element."""
    data = require_bim(ctx)
    used = {str(e.get("type")) for e in data["elements"] if e.get("type")}
    objects = ctx.raw("objects")
    available = (
        set(objects.get("objects", {}).keys())
        if isinstance(objects, dict) and isinstance(objects.get("objects"), dict)
        else set()
    )
    candidates = sorted(available - used)
    return result(
        summary={"candidateCount": len(candidates)},
        tables=[
            table("Purge Candidates", [("type", "Object type")], [{"type": x} for x in candidates])
        ],
    )


@feature("bimSummary.snapshotHistory", "Snapshot History", part="bim")
def snapshot_history(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Browse saved BIM snapshots recorded by the project."""
    data = require_bim(ctx)
    snapshots = data.get("snapshots", [])
    rows = snapshots if isinstance(snapshots, list) else []
    return result(
        summary={"snapshotCount": len(rows)},
        tables=[
            table(
                "Snapshot History",
                [("name", "Snapshot"), ("date", "Date"), ("author", "Author")],
                rows,
            )
        ],
    )


@feature("bimSummary.baselineCompare", "Baseline Compare", part="bim")
def baseline_compare(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare current element IDs with an approved baseline if stored in the BIM model."""
    data = require_bim(ctx)
    baseline = data.get("baseline", {})
    before = set(baseline.get("elementIds", [])) if isinstance(baseline, dict) else set()
    now = {str(e.get("id")) for e in data["elements"]}
    rows = [{"change": "Added", "id": x} for x in sorted(now - before)]
    rows += [{"change": "Removed", "id": x} for x in sorted(before - now)]
    return result(
        summary={"addedCount": len(now - before), "removedCount": len(before - now)},
        tables=[table("Baseline Differences", [("change", "Change"), ("id", "Element id")], rows)],
    )


@feature(
    "bimSummary.progressSnapshot",
    "Progress Snapshot",
    part="bim",
    fields=[
        text("name", "Snapshot name", "Progress review"),
        text("author", "Author", "Project team"),
    ],
)
def progress_snapshot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Capture current BIM metrics as a named progress snapshot."""
    data = require_bim(ctx)
    payload = {
        "name": values["name"],
        "author": values["author"],
        "elementCount": len(data["elements"]),
        "categories": kind_counts(data),
    }
    path = write_bim_json(ctx, "progress-snapshot.json", payload)
    return result(
        summary={
            "snapshotName": values["name"],
            "elementCount": len(data["elements"]),
            "exportPath": path,
        },
        notes=[f"Snapshot metrics written to {path}."],
    )


@feature("bimSummary.exportSnapshot", "Export Snapshot", part="bim")
def export_snapshot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export current model metrics for external reporting."""
    data = require_bim(ctx)
    payload = {
        "elementCount": len(data["elements"]),
        "stories": data.get("stories", []),
        "categories": kind_counts(data),
    }
    path = write_bim_json(ctx, "model-snapshot.json", payload)
    return result(
        summary={"elementCount": len(data["elements"]), "exportPath": path},
        notes=[f"Snapshot exported to {path}."],
    )


@feature("bimSummary.milestoneTrend", "Milestone Trend", part="bim")
def milestone_trend(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Chart completion across successive recorded milestones."""
    data = require_bim(ctx)
    milestones = data.get("milestones", [])
    rows = milestones if isinstance(milestones, list) else []
    return result(
        summary={"milestoneCount": len(rows)},
        tables=[
            table(
                "Milestone Trend",
                [("name", "Milestone"), ("date", "Date"), ("completionPercent", "Completion", "%")],
                rows,
            )
        ],
    )
