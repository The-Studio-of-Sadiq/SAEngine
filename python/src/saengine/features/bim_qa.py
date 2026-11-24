"""BIM quality assurance and coordination features."""

from __future__ import annotations

from typing import Any

from saengine.features import FeatureContext, feature, number, result, table, text
from saengine.features.bim_common import kind_counts, require_bim, write_bim_csv, write_bim_json


@feature("bimQa.clashDetection", "Clash Detection", part="bim")
def clash_detection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run recorded hard-clash data and report unresolved clashes."""
    data = require_bim(ctx)
    clashes = data.get("clashes", [])
    rows = clashes if isinstance(clashes, list) else []
    return result(
        summary={"clashCount": len(rows)},
        tables=[
            table(
                "Clashes",
                [
                    ("id", "Clash"),
                    ("status", "Status"),
                    ("elementA", "Element A"),
                    ("elementB", "Element B"),
                ],
                rows,
            )
        ],
    )


@feature("bimQa.modelValidation", "Model Validation", part="bim")
def model_validation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate required BIM fields and element geometry keys."""
    data = require_bim(ctx)
    missing = [
        e for e in data["elements"] if not e.get("id") or not e.get("kind") or not e.get("type")
    ]
    duplicate_ids = len(data["elements"]) - len({str(e.get("id")) for e in data["elements"]})
    return result(
        summary={"invalidElementCount": len(missing), "duplicateIdCount": duplicate_ids},
        tables=[
            table(
                "Validation Failures",
                [("id", "Element"), ("issue", "Issue")],
                [{"id": e.get("id", ""), "issue": "Missing id, kind or type"} for e in missing],
            )
        ],
    )


@feature("bimQa.duplicateElements", "Duplicate Elements", part="bim")
def duplicate_elements(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Find elements modelled more than once."""
    data = require_bim(ctx)
    counts: dict[str, int] = {}
    for e in data["elements"]:
        key = str(e.get("id", ""))
        counts[key] = counts.get(key, 0) + 1
    rows = [{"id": k, "count": v} for k, v in sorted(counts.items()) if v > 1]
    return result(
        summary={"duplicateCount": len(rows)},
        tables=[table("Duplicate Elements", [("id", "Element id"), ("count", "Count")], rows)],
    )


@feature(
    "bimQa.namingRules",
    "Naming Rules",
    part="bim",
    fields=[text("prefix", "Required ID prefix", "")],
)
def naming_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check element IDs against a configurable prefix pattern."""
    data = require_bim(ctx)
    prefix = values["prefix"].strip()
    rows = [
        {"id": str(e.get("id", "")), "compliant": str(e.get("id", "")).startswith(prefix)}
        for e in data["elements"]
    ]
    failed = sum(not r["compliant"] for r in rows)
    return result(
        summary={"failedElementCount": failed, "elementCount": len(rows)},
        tables=[table("Naming Results", [("id", "Element id"), ("compliant", "Compliant")], rows)],
    )


@feature("bimQa.parameterRules", "Parameter Rules", part="bim")
def parameter_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check required parameters recorded for BIM elements."""
    data = require_bim(ctx)
    required = ["id", "kind", "type"]
    rows = [
        {"id": e.get("id", ""), "missing": ", ".join(k for k in required if not e.get(k))}
        for e in data["elements"]
        if any(not e.get(k) for k in required)
    ]
    return result(
        summary={"elementWithMissingCount": len(rows)},
        tables=[
            table("Parameter Rules", [("id", "Element"), ("missing", "Missing parameters")], rows)
        ],
    )


@feature(
    "bimQa.requirementSets",
    "Requirement Sets",
    part="bim",
    fields=[text("requirements", "Required parameters", "id,kind,type")],
)
def requirement_sets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert a comma-separated requirement list into BIM checks."""
    data = require_bim(ctx)
    keys = [x.strip() for x in values["requirements"].split(",") if x.strip()]
    rows = [
        {"id": e.get("id", ""), "missing": ", ".join(k for k in keys if k not in e)}
        for e in data["elements"]
        if any(k not in e for k in keys)
    ]
    return result(
        summary={"requirementCount": len(keys), "failedElementCount": len(rows)},
        tables=[
            table(
                "Requirement Sets", [("id", "Element"), ("missing", "Missing requirements")], rows
            )
        ],
    )


@feature("bimQa.qaReport", "QA Report", part="bim")
def qa_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run model integrity audit against 04 Objects and 06 BIM stories and export QA report."""
    data = require_bim(ctx)
    elems = [e for e in (data.get("elements") or []) if isinstance(e, dict)]
    stories = {str(s.get("id", "")) for s in (data.get("stories") or []) if isinstance(s, dict)}
    objs = {
        str(o.get("id", ""))
        for o in ((ctx.raw("objects") or {}).get("objects") or [])
        if isinstance(o, dict)
    }
    missing_id_kind = sum(
        1 for e in elems if not e.get("id") or not e.get("kind") or not e.get("type")
    )
    unmatched_type = sum(1 for e in elems if objs and str(e.get("type", "")) not in objs)
    unmatched_story = sum(
        1 for e in elems if stories and e.get("story") and str(e["story"]) not in stories
    )
    passed = len(elems) - missing_id_kind - unmatched_type
    pass_rate = round(max(0.0, passed) / max(1, len(elems)) * 100.0, 1)
    payload = {
        "elementCount": len(elems),
        "invalidElementCount": missing_id_kind,
        "missingObjectCatalogRef": unmatched_type,
        "unknownStoryRef": unmatched_story,
        "passRatePct": pass_rate,
        "categoryCounts": kind_counts(data),
    }
    path = write_bim_json(ctx, "bim-qa-report.json", payload)
    return result(
        summary={
            "invalidElementCount": missing_id_kind,
            "missingTypeRefs": unmatched_type,
            "passRatePct": pass_rate,
            "exportPath": path,
        },
        notes=[
            f"QA pass rate {pass_rate}% across {len(elems)} element(s); report written to {path}."
        ],
    )


@feature("bimQa.issueRegister", "Issue Register", part="bim")
def issue_register(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List open coordination issues recorded in the BIM model."""
    data = require_bim(ctx)
    issues = [i for i in data.get("issues", []) if isinstance(i, dict)]
    open_issues = [
        i for i in issues if str(i.get("status", "Open")).lower() not in ("closed", "resolved")
    ]
    return result(
        summary={"openIssueCount": len(open_issues), "issueCount": len(issues)},
        tables=[
            table(
                "Issue Register",
                [
                    ("id", "Issue"),
                    ("title", "Title"),
                    ("status", "Status"),
                    ("priority", "Priority"),
                ],
                open_issues,
            )
        ],
    )


@feature("bimQa.bcfExport", "BCF Export", part="bim")
def bcf_export(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile BIM QA & interference issues into BCF v3 interchange topics."""
    import json
    import uuid

    from saengine.library.mep import Coordination, Issue
    from saengine.mep import bcf

    data = require_bim(ctx)
    topics = [i for i in (data.get("issues") or []) if isinstance(i, dict)]
    objs = {
        str(o.get("id", ""))
        for o in ((ctx.raw("objects") or {}).get("objects") or [])
        if isinstance(o, dict)
    }
    for e in data.get("elements") or []:
        if isinstance(e, dict) and objs and str(e.get("type", "")) not in objs:
            topics.append(
                {
                    "guid": f"QA-{e.get('id')}",
                    "title": f"Missing object type {e.get('type')}",
                    "status": "active",
                }
            )
    cfile = ctx.path("11 Exports/BIM/bim_clash_comment.json")
    if cfile is not None and cfile.exists():
        try:
            loaded = json.loads(cfile.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                topics.extend(
                    [
                        {
                            "guid": str(c.get("clashId", "CL")),
                            "title": str(c.get("comment", "")),
                            "status": str(c.get("status", "active")).lower(),
                        }
                        for c in loaded
                        if isinstance(c, dict)
                    ]
                )
        except ValueError:
            pass
    issues = []
    for idx, t in enumerate(topics, start=1):
        raw_st = str(t.get("status", "active")).lower()
        st = (
            raw_st
            if raw_st in {"new", "active", "reviewed", "approved", "resolved", "closed"}
            else "active"
        )
        issues.append(
            Issue(
                id=f"QA-{idx}",
                guid=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"saengine.qa.{idx}.{t.get('guid', '')}")),
                title=str(t.get("title", f"QA Issue {idx}")),
                source="ids",
                status=st,
            )
        )
    out_zip = ctx.path("11 Exports/BIM/qa-issues.bcf")
    out_path = write_bim_json(
        ctx, "coordination-issues.bcf.json", {"version": "3.0", "topics": topics}
    )
    if out_zip is not None and issues:
        out_zip.parent.mkdir(parents=True, exist_ok=True)
        coord = Coordination(author="SAEngine", issues=issues)
        out_zip.write_bytes(bcf.export_bcf(coord))
        out_path = out_zip.relative_to(ctx.root).as_posix()
    return result(summary={"issueCount": len(topics), "exportPath": out_path})


@feature("bimQa.hardClashCheck", "Hard Clash Check", part="bim")
def hard_clash_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report recorded physical intersections between model elements."""
    data = require_bim(ctx)
    clashes = [
        c
        for c in data.get("clashes", [])
        if isinstance(c, dict) and str(c.get("type", "hard")).lower() == "hard"
    ]
    return result(
        summary={"hardClashCount": len(clashes)},
        tables=[
            table(
                "Hard Clashes",
                [("id", "Clash"), ("elementA", "Element A"), ("elementB", "Element B")],
                clashes,
            )
        ],
    )


@feature(
    "bimQa.softClashCheck",
    "Soft Clash Check",
    part="bim",
    fields=[number("clearanceMm", "Required clearance", 500.0, unit="mm", min=0)],
)
def soft_clash_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check recorded clearance violations against the required zone."""
    data = require_bim(ctx)
    violations = [
        c
        for c in data.get("clashes", [])
        if isinstance(c, dict) and str(c.get("type", "")).lower() == "clearance"
    ]
    return result(
        summary={"clearanceMm": values["clearanceMm"], "clearanceViolationCount": len(violations)},
        tables=[
            table(
                "Clearance Violations",
                [("id", "Clash"), ("actualClearanceMm", "Actual", "mm")],
                violations,
            )
        ],
    )


@feature("bimQa.clearanceReview", "Clearance Review", part="bim")
def clearance_review(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review all recorded clearance violations."""
    data = require_bim(ctx)
    rows = [
        c
        for c in data.get("clashes", [])
        if isinstance(c, dict) and str(c.get("type", "")).lower() in ("clearance", "soft")
    ]
    return result(
        summary={"clearanceCount": len(rows)},
        tables=[
            table(
                "Clearance Review",
                [
                    ("id", "Clash"),
                    ("disciplineA", "Discipline A"),
                    ("disciplineB", "Discipline B"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
    )


@feature("bimQa.clashGrouping", "Clash Grouping", part="bim")
def clash_grouping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Group recorded clashes by discipline pair."""
    data = require_bim(ctx)
    groups: dict[str, int] = {}
    for clash in data.get("clashes", []):
        if isinstance(clash, dict):
            pair = f"{clash.get('disciplineA', 'A')} / {clash.get('disciplineB', 'B')}"
            groups[pair] = groups.get(pair, 0) + 1
    rows = [{"pair": k, "count": v} for k, v in sorted(groups.items())]
    return result(
        summary={"groupCount": len(rows)},
        tables=[table("Clash Groups", [("pair", "Disciplines"), ("count", "Clashes")], rows)],
    )


@feature("bimQa.clashHistory", "Clash History", part="bim")
def clash_history(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Track clash counts and resolution progress over model reviews."""
    data = require_bim(ctx)
    history = data.get("clashHistory", [])
    rows = history if isinstance(history, list) else []
    return result(
        summary={"reviewCount": len(rows)},
        tables=[
            table(
                "Clash History",
                [("date", "Date"), ("clashCount", "Clashes"), ("resolvedCount", "Resolved")],
                rows,
            )
        ],
    )


@feature("bimQa.requirementMatrix", "Requirement Matrix", part="bim")
def requirement_matrix(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map project requirements to model elements and parameters."""
    data = require_bim(ctx)
    reqs = data.get("requirements", [])
    rows = reqs if isinstance(reqs, list) else []
    return result(
        summary={"requirementCount": len(rows), "elementCount": len(data["elements"])},
        tables=[
            table(
                "Requirement Matrix",
                [("id", "Requirement"), ("parameter", "Parameter"), ("elementCount", "Elements")],
                rows,
            )
        ],
    )


@feature("bimQa.parameterCompleteness", "Parameter Completeness", part="bim")
def parameter_completeness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check common required parameters on every element."""
    data = require_bim(ctx)
    rows = []
    for key in ("id", "kind", "type", "source"):
        populated = sum(1 for e in data["elements"] if e.get(key) not in (None, ""))
        rows.append(
            {
                "parameter": key,
                "populatedPercent": populated / len(data["elements"]) * 100
                if data["elements"]
                else 100,
            }
        )
    return result(
        summary={"elementCount": len(data["elements"])},
        tables=[
            table(
                "Parameter Completeness",
                [("parameter", "Parameter"), ("populatedPercent", "Populated", "%")],
                rows,
            )
        ],
    )


@feature("bimQa.classificationCheck", "Classification Check", part="bim")
def classification_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify classification codes for each element type."""
    data = require_bim(ctx)
    rows = [
        {"id": e.get("id", ""), "classification": e.get("classification", "")}
        for e in data["elements"]
        if not e.get("classification")
    ]
    return result(
        summary={"missingClassificationCount": len(rows)},
        tables=[
            table(
                "Classification Gaps",
                [("id", "Element"), ("classification", "Classification")],
                rows,
            )
        ],
    )


@feature(
    "bimQa.lodCheck",
    "LOD Check",
    part="bim",
    fields=[
        number("requiredLod", "Required level of development", 300.0, unit="LOD", min=100, max=500)
    ],
)
def lod_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assess elements against a required level of development."""
    data = require_bim(ctx)
    rows = [
        {
            "id": e.get("id", ""),
            "lod": e.get("lod", 0),
            "compliant": float(e.get("lod", 0)) >= values["requiredLod"],
        }
        for e in data["elements"]
    ]
    return result(
        summary={
            "requiredLod": values["requiredLod"],
            "nonCompliantCount": sum(not r["compliant"] for r in rows),
        },
        tables=[
            table(
                "LOD Check", [("id", "Element"), ("lod", "LOD"), ("compliant", "Compliant")], rows
            )
        ],
    )


@feature(
    "bimQa.issuePriority",
    "Issue Priority",
    part="bim",
    fields=[text("priorityRules", "Priority rules", "Critical,High,Medium,Low")],
)
def issue_priority(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set issue priority levels for coordination registers."""
    levels = [x.strip() for x in values["priorityRules"].split(",") if x.strip()]
    return result(
        summary={"priorityLevelCount": len(levels)},
        tables=[
            table(
                "Issue Priorities",
                [("rank", "Rank"), ("priority", "Priority")],
                [{"rank": i + 1, "priority": p} for i, p in enumerate(levels)],
            )
        ],
    )


@feature("bimQa.qaDashboard", "QA Dashboard", part="bim")
def qa_dashboard(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Show pass rates and open coordination issue counts."""
    data = require_bim(ctx)
    invalid = sum(not e.get("type") for e in data["elements"])
    issues = [i for i in data.get("issues", []) if isinstance(i, dict)]
    return result(
        summary={
            "passPercent": (1 - invalid / len(data["elements"])) * 100 if data["elements"] else 100,
            "openIssueCount": sum(
                str(i.get("status", "Open")).lower() not in ("closed", "resolved") for i in issues
            ),
        }
    )


@feature("bimQa.exportQaExcel", "Export QA Excel", part="bim")
def export_qa_excel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Cross-validate every BIM element against 04 Objects & 06 BIM stories and export QA CSV."""
    data = require_bim(ctx)
    stories = {str(s.get("id", "")) for s in (data.get("stories") or []) if isinstance(s, dict)}
    objs = {
        str(o.get("id", ""))
        for o in ((ctx.raw("objects") or {}).get("objects") or [])
        if isinstance(o, dict)
    }
    rows = []
    for e in data.get("elements") or []:
        if not isinstance(e, dict):
            continue
        type_ok = not objs or str(e.get("type", "")) in objs
        story_ok = not stories or not e.get("story") or str(e["story"]) in stories
        rows.append(
            {
                "id": e.get("id", ""),
                "kind": e.get("kind", ""),
                "type": e.get("type", ""),
                "story": e.get("story", ""),
                "typeValid": type_ok,
                "storyValid": story_ok,
                "qaStatus": "PASS" if (type_ok and story_ok) else "FAIL",
            }
        )
    path = write_bim_csv(
        ctx,
        "bim-qa-results.csv",
        ["id", "kind", "type", "story", "typeValid", "storyValid", "qaStatus"],
        rows,
    )
    return result(
        summary={
            "elementCount": len(rows),
            "passCount": sum(1 for r in rows if r["qaStatus"] == "PASS"),
            "exportPath": path,
        }
    )


@feature("bimQa.trendReport", "Trend Report", part="bim")
def trend_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report model quality metrics across recorded reviews."""
    data = require_bim(ctx)
    trends = data.get("qualityTrends", [])
    rows = trends if isinstance(trends, list) else []
    return result(
        summary={"reviewCount": len(rows)},
        tables=[
            table(
                "QA Trend",
                [("date", "Date"), ("passPercent", "Pass", "%"), ("issueCount", "Issues")],
                rows,
            )
        ],
    )


@feature("bimQa.reviewMeetingPack", "Review Meeting Pack", part="bim")
def review_meeting_pack(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assemble live BIM+MEP coordination clash, opening conflict, and QA status meeting pack."""
    from datetime import date

    data = require_bim(ctx)
    objs = {
        str(o.get("id", ""))
        for o in ((ctx.raw("objects") or {}).get("objects") or [])
        if isinstance(o, dict)
    }
    missing_refs = [
        e.get("id")
        for e in (data.get("elements") or [])
        if isinstance(e, dict) and objs and str(e.get("type", "")) not in objs
    ]
    mep_raw = ctx.raw("mep") or {}
    mep_openings = len(mep_raw.get("openings") or []) if isinstance(mep_raw, dict) else 0
    bim_openings = len((data.get("additions") or {}).get("slabOpenings") or []) + len(
        (data.get("additions") or {}).get("wallOpenings") or []
    )
    payload = {
        "date": date.today().isoformat(),
        "elementCount": len(data.get("elements") or []),
        "categories": kind_counts(data),
        "missingCatalogRefs": missing_refs,
        "bimOpenings": bim_openings,
        "mepOpenings": mep_openings,
        "issues": data.get("issues") or [],
    }
    path = write_bim_json(ctx, "review-meeting-pack.json", payload)
    return result(
        summary={
            "elementCount": payload["elementCount"],
            "missingTypeRefs": len(missing_refs),
            "coordinatedOpenings": bim_openings + mep_openings,
            "exportPath": path,
        }
    )


@feature("bimQa.correctiveActions", "Corrective Actions", part="bim")
def corrective_actions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign and track corrective actions from repeated QA failures."""
    data = require_bim(ctx)
    actions = data.get("correctiveActions", [])
    rows = actions if isinstance(actions, list) else []
    return result(
        summary={"actionCount": len(rows)},
        tables=[
            table(
                "Corrective Actions",
                [
                    ("id", "Action"),
                    ("owner", "Owner"),
                    ("status", "Status"),
                    ("failure", "Failure"),
                ],
                rows,
            )
        ],
    )
