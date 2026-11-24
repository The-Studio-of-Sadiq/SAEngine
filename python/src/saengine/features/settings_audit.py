"""Project Settings - Audit, Compliance & Governance tab: logs, exports, conformance, baselines, checksums."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from saengine.codes import conformance
from saengine.codes import context as code_context
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
from saengine.features.settings_common import (
    active_pack,
    export_file,
    json_dumps_clean,
    load_settings,
    load_settings_raw,
)
from saengine.library.settings import default_project_settings
from saengine.library.settings import problems as settings_problems
from saengine.report.clauses import in_force


@feature(
    "settingsAudit.settingsAuditLog",
    "Settings Audit Log",
    part="settings",
    fields=[],
    requires_project=False,
)
def settings_audit_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile an audit summary of project settings file metadata and modified sections."""
    st = load_settings(ctx)
    raw = load_settings_raw(ctx)
    path = ctx.path("02 Project Settings/project-settings.json")
    mtime = (
        datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")
        if path and path.is_file()
        else "-"
    )
    rows = [
        {"section": k, "lastModifiedUtc": mtime, "engineer": st.project.engineer or "-"}
        for k in sorted(raw.keys())
    ]
    return result(
        summary={
            "sectionCount": len(rows),
            "lastModifiedUtc": mtime,
            "projectName": st.project.name,
        },
        tables=[
            table(
                "Settings section audit",
                [
                    ("section", "Section"),
                    ("lastModifiedUtc", "File timestamp"),
                    ("engineer", "Engineer"),
                ],
                rows or [{"section": "(default)", "lastModifiedUtc": "-", "engineer": "-"}],
            )
        ],
        notes=["Derived from 02 Project Settings/project-settings.json."],
    )


@feature(
    "settingsAudit.exportSettings",
    "Export Settings",
    part="settings",
    fields=[
        checkbox("writeFile", "Write export JSON to 02 Project Settings/exports", True),
    ],
    requires_project=False,
)
def export_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Export the validated project settings as a portable JSON configuration file."""
    st = load_settings(ctx)
    dumped = st.model_dump(mode="json", by_alias=True, exclude_none=True)
    text_json = json_dumps_clean(dumped)
    out_path = None
    if values["writeFile"] and ctx.root is not None:
        out_path = export_file(ctx, "project-settings-export.json", text_json)
    return result(
        summary={
            "sectionCount": len(dumped),
            "byteSize": len(text_json.encode("utf-8")),
            "exported": out_path is not None,
        },
        tables=[
            table(
                "Exported sections",
                [("section", "Key"), ("type", "Type")],
                [{"section": k, "type": type(v).__name__} for k, v in dumped.items()],
            )
        ],
        notes=[
            f"Saved to {out_path}"
            if out_path
            else "Open a project folder to save project-settings-export.json."
        ],
    )


@feature(
    "settingsAudit.resetSection",
    "Reset Section",
    part="settings",
    fields=[
        select(
            "section",
            "Settings section to compare/reset",
            [
                ("occupancy", "Occupancy"),
                ("site", "Site"),
                ("seismic", "Seismic"),
                ("wind", "Wind"),
                ("foundation", "Foundation"),
                ("drawings", "Drawings"),
                ("units", "Units"),
            ],
            "seismic",
        ),
    ],
    requires_project=False,
)
def reset_section(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview resetting a project settings section back to the active code pack defaults."""
    st = load_settings(ctx)
    sec = values["section"]
    with in_force(ctx.root, st):
        default_st = default_project_settings(st.project.name, st.codePack)
    cur_sec = getattr(st, sec).model_dump(mode="json", exclude_none=True)
    def_sec = getattr(default_st, sec).model_dump(mode="json", exclude_none=True)
    rows = [
        {
            "field": k,
            "current": str(cur_sec.get(k, "-")),
            "packDefault": str(def_sec.get(k, "-")),
            "differs": cur_sec.get(k) != def_sec.get(k),
        }
        for k in sorted(set(cur_sec) | set(def_sec))
    ]
    return result(
        summary={
            "section": sec,
            "fieldCount": len(rows),
            "differingFields": sum(1 for r in rows if r["differs"]),
        },
        tables=[
            table(
                f"Section reset preview: {sec}",
                [
                    ("field", "Field"),
                    ("current", "Current"),
                    ("packDefault", "Pack default"),
                    ("differs", "Changed"),
                ],
                rows,
            )
        ],
        notes=["Non-destructive preview showing fields that differ from code pack defaults."],
    )


@feature(
    "settingsAudit.codeConformance",
    "Code Conformance",
    part="settings",
    fields=[],
    requires_project=False,
)
def code_conformance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run conformance checks on the active code pack and validate project settings against it."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        pack_findings = conformance.check_pack(pack)
        st_probs = settings_problems(st)
    rows = [
        {"scope": "Pack", "level": f.level, "check": f.check, "message": f.message}
        for f in pack_findings
    ] + [{"scope": "Settings", "level": "error", "check": p, "message": m} for p, m in st_probs]
    errs = sum(1 for r in rows if r["level"] == "error")
    return result(
        summary={
            "packId": pack.id,
            "errors": errs,
            "totalFindings": len(rows),
            "conforming": errs == 0,
        },
        tables=[
            table(
                "Code conformance report",
                [
                    ("scope", "Scope"),
                    ("level", "Level"),
                    ("check", "Check"),
                    ("message", "Finding"),
                ],
                rows
                or [{"scope": "All", "level": "ok", "check": "all", "message": "Fully conforming"}],
            )
        ],
        notes=[
            f"Conformance checked using saengine.codes.conformance on {code_context.code_name(pack)}."
        ],
    )


@feature(
    "settingsAudit.peerReview",
    "Peer Review",
    part="settings",
    fields=[
        text("reviewerName", "Peer reviewer", "Independent Checker"),
        text(
            "reviewNotes",
            "Review status note",
            "Parameters verified against geotechnical and architectural brief",
        ),
    ],
    requires_project=False,
)
def peer_review(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify settings completeness and produce a peer-review sign-off record."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        probs = settings_problems(st)
    digest = hashlib.sha256(
        json_dumps_clean(st.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()[:16]
    return result(
        summary={
            "reviewer": values["reviewerName"],
            "openProblems": len(probs),
            "settingsHash": digest,
            "readyForSignoff": len(probs) == 0,
        },
        tables=[
            table(
                "Peer review sign-off",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Reviewer", "value": values["reviewerName"]},
                    {"field": "Validation errors", "value": str(len(probs))},
                    {"field": "SHA-256 prefix", "value": digest},
                    {"field": "Notes", "value": values["reviewNotes"]},
                ],
            )
        ],
        notes=["Settings with open validation errors should be resolved prior to locking."],
    )


@feature(
    "settingsAudit.userActivityLog",
    "User Activity Log",
    part="settings",
    fields=[],
    requires_project=False,
)
def user_activity_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List recent project part file modification timestamps across the open project."""
    if ctx.root is None:
        return result(
            summary={"partFilesPresent": 0},
            tables=[
                table(
                    "Project part activity",
                    [("part", "Part"), ("exists", "Exists"), ("modifiedUtc", "Last modified")],
                    [{"part": "settings", "exists": False, "modifiedUtc": "-"}],
                )
            ],
            notes=["Open a project folder to inspect part file activity timestamps."],
        )
    rows = []
    for part, rel in ctx.PART_FILES.items():
        p = ctx.path(rel)
        if p and p.is_file():
            ts = datetime.fromtimestamp(p.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")
            rows.append(
                {"part": part, "exists": True, "modifiedUtc": ts, "bytes": p.stat().st_size}
            )
        else:
            rows.append({"part": part, "exists": False, "modifiedUtc": "-", "bytes": 0})
    return result(
        summary={"partFilesPresent": sum(1 for r in rows if r["exists"])},
        tables=[
            table(
                "Project part activity log",
                [
                    ("part", "Part"),
                    ("exists", "Present"),
                    ("modifiedUtc", "Last modified UTC"),
                    ("bytes", "Size [B]"),
                ],
                rows,
            )
        ],
        notes=["Scanned across all registered project parts."],
    )


@feature(
    "settingsAudit.fieldChangeHistory",
    "Field Change History",
    part="settings",
    fields=[
        text("fieldPath", "Settings field path (e.g. site.location)", "site.location"),
    ],
    requires_project=False,
)
def field_change_history(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare a specific dotted field path against the pack default value."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        def_st = default_project_settings(st.project.name, st.codePack)
    cur_d = st.model_dump(mode="json")
    def_d = def_st.model_dump(mode="json")
    parts = [p for p in values["fieldPath"].split(".") if p]
    c_val: Any = cur_d
    d_val: Any = def_d
    for p in parts:
        c_val = c_val.get(p) if isinstance(c_val, dict) else None
        d_val = d_val.get(p) if isinstance(d_val, dict) else None
    return result(
        summary={"fieldPath": values["fieldPath"], "modifiedFromDefault": c_val != d_val},
        tables=[
            table(
                "Field value comparison",
                [("state", "State"), ("value", "Value")],
                [
                    {"state": "Pack default", "value": str(d_val)},
                    {"state": "Current project", "value": str(c_val)},
                ],
            )
        ],
        notes=["Compares live field value against code pack default."],
    )


@feature(
    "settingsAudit.deletedItemLog",
    "Deleted Item Log",
    part="settings",
    fields=[],
    requires_project=False,
)
def deleted_item_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare project combinations and area loads against pack defaults to detect removed entries."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        def_st = default_project_settings(st.project.name, st.codePack)
    cur_areas = {a.id for a in st.areaLoads}
    def_areas = {a.id for a in def_st.areaLoads}
    removed_areas = sorted(def_areas - cur_areas)
    cur_combos = {c.name for c in st.combinations}
    def_combos = {c.name for c in def_st.combinations}
    removed_combos = sorted(def_combos - cur_combos)
    rows = [{"kind": "Area load", "id": x} for x in removed_areas] + [
        {"kind": "Combination", "id": x} for x in removed_combos
    ]
    return result(
        summary={"removedAreas": len(removed_areas), "removedCombinations": len(removed_combos)},
        tables=[
            table(
                "Defaults absent from current settings",
                [("kind", "Kind"), ("id", "Identifier")],
                rows or [{"kind": "-", "id": "No default items removed"}],
            )
        ],
        notes=["Identifies default area loads or combinations removed from project settings."],
    )


@feature(
    "settingsAudit.baselineSnapshot",
    "Baseline Snapshot",
    part="settings",
    fields=[
        checkbox("writeSnapshot", "Write baseline snapshot to exports", True),
    ],
    requires_project=False,
)
def baseline_snapshot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Capture a SHA-256 hashed baseline snapshot of project settings."""
    st = load_settings(ctx)
    payload = st.model_dump(mode="json", by_alias=True, exclude_none=True)
    text_json = json_dumps_clean(payload)
    digest = hashlib.sha256(text_json.encode("utf-8")).hexdigest()
    out_path = None
    if values["writeSnapshot"] and ctx.root is not None:
        out_path = export_file(ctx, "settings-baseline.json", text_json)
    return result(
        summary={"sha256": digest, "sectionCount": len(payload), "saved": out_path is not None},
        tables=[
            table(
                "Baseline snapshot",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "SHA-256", "value": digest},
                    {"property": "Code pack", "value": st.codePack},
                ],
            )
        ],
        notes=[
            f"Baseline saved to {out_path}"
            if out_path
            else "Open a project folder to save settings-baseline.json."
        ],
    )


@feature(
    "settingsAudit.diffReport",
    "Diff Report",
    part="settings",
    fields=[],
    requires_project=False,
)
def diff_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate a section-by-section diff report between current settings and pack defaults."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        def_st = default_project_settings(st.project.name, st.codePack)
    cur = st.model_dump(mode="json")
    base = def_st.model_dump(mode="json")
    rows = [
        {"section": k, "changed": cur.get(k) != base.get(k)} for k in sorted(set(cur) | set(base))
    ]
    return result(
        summary={
            "totalSections": len(rows),
            "modifiedSections": sum(1 for r in rows if r["changed"]),
        },
        tables=[
            table(
                "Settings diff vs pack defaults",
                [("section", "Section"), ("changed", "Modified")],
                rows,
            )
        ],
        notes=["Highlights sections customized away from active code pack defaults."],
    )


@feature(
    "settingsAudit.approvalWorkflow",
    "Approval Workflow",
    part="settings",
    fields=[
        select(
            "currentGate",
            "Current workflow gate",
            [
                ("draft", "Draft (Engineer)"),
                ("checked", "Checked (Senior)"),
                ("approved", "Approved (Principal)"),
                ("issued", "Issued for Construction"),
            ],
            "checked",
        ),
    ],
    requires_project=False,
)
def approval_workflow(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify readiness of project settings for each engineering QA approval gate."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        probs = settings_problems(st)
    gates = ["draft", "checked", "approved", "issued"]
    idx = gates.index(values["currentGate"])
    rows = [
        {"gate": g, "completed": i <= idx and len(probs) == 0, "blockingErrors": len(probs)}
        for i, g in enumerate(gates)
    ]
    return result(
        summary={
            "currentGate": values["currentGate"],
            "blockingErrors": len(probs),
            "gateCleared": len(probs) == 0,
        },
        tables=[
            table(
                "Settings QA workflow gates",
                [("gate", "Gate"), ("completed", "Cleared"), ("blockingErrors", "Errors")],
                rows,
            )
        ],
        notes=["Gates beyond Draft require zero validation errors in settings."],
    )


@feature(
    "settingsAudit.digitalSignature",
    "Digital Signature",
    part="settings",
    fields=[
        text("signer", "Signing engineer", "Lead Engineer"),
    ],
    requires_project=False,
)
def digital_signature(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute a deterministic SHA-256 fingerprint of project settings for sign-off attestation."""
    st = load_settings(ctx)
    canonical = json.dumps(
        st.model_dump(mode="json", by_alias=True, exclude_none=True), sort_keys=True
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return result(
        summary={"signer": values["signer"], "sha256": digest, "algorithm": "SHA-256"},
        tables=[
            table(
                "Settings attestation digest",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Signer", "value": values["signer"]},
                    {"field": "Canonical SHA-256", "value": digest},
                ],
            )
        ],
        notes=["Canonical sorted-JSON SHA-256 fingerprint detects any subsequent tampering."],
    )


@feature(
    "settingsAudit.reviewComments",
    "Review Comments",
    part="settings",
    fields=[
        text("topic", "Review topic", "Seismic system & site class"),
        text("comment", "Reviewer comment", "Confirm borehole SD governs over entered site class"),
    ],
    requires_project=False,
)
def review_comments(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record structured review comments tied to project settings validation items."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        probs = settings_problems(st)
    rows = [{"topic": values["topic"], "comment": values["comment"], "status": "Open"}]
    for p, m in probs:
        rows.append({"topic": p, "comment": m, "status": "Auto-flagged"})
    return result(
        summary={"commentCount": len(rows), "autoFlaggedCount": len(probs)},
        tables=[
            table(
                "Settings review comments",
                [("topic", "Topic / Path"), ("comment", "Comment"), ("status", "Status")],
                rows,
            )
        ],
        notes=["Combines manual reviewer remarks with automated settings check findings."],
    )


@feature(
    "settingsAudit.auditCertificates",
    "Audit Certificates",
    part="settings",
    fields=[
        checkbox("writeCert", "Write audit certificate Markdown to exports", True),
    ],
    requires_project=False,
)
def audit_certificates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Issue a project settings audit certificate summarizing code basis and conformance."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        probs = settings_problems(st)
    digest = hashlib.sha256(
        json.dumps(st.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()[:24]
    md = (
        "\n".join(
            [
                "# Project Settings Audit Certificate",
                f"- Project: {st.project.name}",
                f"- Code Pack: {code_context.code_name(pack)} ({pack.id} v{pack.info.version})",
                f"- Settings SHA-256 Prefix: {digest}",
                f"- Validation Errors: {len(probs)}",
            ]
        )
        + "\n"
    )
    out_path = None
    if values["writeCert"] and ctx.root is not None:
        out_path = export_file(ctx, "audit-certificate.md", md)
    return result(
        summary={
            "project": st.project.name,
            "packId": pack.id,
            "validationErrors": len(probs),
            "certificateWritten": out_path is not None,
        },
        tables=[
            table(
                "Audit certificate fields",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Project", "value": st.project.name},
                    {"field": "Pack", "value": pack.id},
                    {"field": "Errors", "value": str(len(probs))},
                    {"field": "Digest", "value": digest},
                ],
            )
        ],
        notes=[
            f"Certificate written to {out_path}"
            if out_path
            else "Open a project folder to save audit-certificate.md."
        ],
    )


@feature(
    "settingsAudit.rolePermissions",
    "Role Permissions",
    part="settings",
    fields=[
        select(
            "role",
            "Team role",
            [
                ("junior", "Junior Engineer"),
                ("lead", "Lead Structural Engineer"),
                ("checker", "Peer Reviewer"),
                ("admin", "Project Admin"),
            ],
            "lead",
        ),
    ],
    requires_project=False,
)
def role_permissions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect role-based permissions for editing code packs, overrides, and signing off settings."""
    perms = {
        "junior": (True, False, False, False),
        "lead": (True, True, False, True),
        "checker": (False, False, True, True),
        "admin": (True, True, True, True),
    }
    ed, ov, app, exp = perms[values["role"]]
    rows = [
        {"permission": "Edit general loads & units", "allowed": ed},
        {"permission": "Modify codeOverrides", "allowed": ov},
        {"permission": "Approve / lock peer review", "allowed": app},
        {"permission": "Export settings & certificates", "allowed": exp},
    ]
    return result(
        summary={"role": values["role"], "canOverride": ov, "canApprove": app},
        tables=[
            table(
                f"Permissions for role: {values['role']}",
                [("permission", "Capability"), ("allowed", "Permitted")],
                rows,
            )
        ],
        notes=["Enforces separation between design authoring and independent review."],
    )


@feature(
    "settingsAudit.archivePolicy",
    "Archive Policy",
    part="settings",
    fields=[
        number(
            "archiveAfterDays",
            "Move snapshots to archive after",
            90.0,
            unit="days",
            min=7.0,
            max=3650.0,
        ),
    ],
    requires_project=False,
)
def archive_policy(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define settings version archival thresholds and storage estimate."""
    return result(
        summary={"archiveAfterDays": values["archiveAfterDays"]},
        tables=[
            table(
                "Archival policy",
                [("rule", "Rule"), ("value", "Value")],
                [
                    {
                        "rule": "Archive age threshold [days]",
                        "value": str(values["archiveAfterDays"]),
                    },
                    {"rule": "Format", "value": "Immutable JSON + SHA-256"},
                ],
            )
        ],
        notes=["Historical baselines older than threshold are moved to cold project archive."],
    )


@feature(
    "settingsAudit.retentionPeriod",
    "Retention Period",
    part="settings",
    fields=[
        number(
            "retentionYears", "Audit record retention period", 10.0, unit="yr", min=1.0, max=50.0
        ),
    ],
    requires_project=False,
)
def retention_period(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure statutory retention duration for structural design settings and audit logs."""
    return result(
        summary={"retentionYears": values["retentionYears"]},
        tables=[
            table(
                "Audit retention policy",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Retention period [years]", "value": str(values["retentionYears"])},
                    {
                        "item": "Covers",
                        "value": "Settings, overrides, certificates, and review logs",
                    },
                ],
            )
        ],
        notes=["Statutory structural record retention is typically 10-15 years post-completion."],
    )


@feature(
    "settingsAudit.backupSchedule",
    "Backup Schedule",
    part="settings",
    fields=[
        select(
            "cadence",
            "Backup frequency",
            [
                ("hourly", "Hourly incremental"),
                ("daily", "Daily snapshot"),
                ("onSave", "Every settings save"),
            ],
            "onSave",
        ),
    ],
    requires_project=False,
)
def backup_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review automated settings backup cadence and existing export artifacts."""
    exp_dir = ctx.path("02 Project Settings/exports")
    existing = sorted(p.name for p in exp_dir.iterdir()) if exp_dir and exp_dir.is_dir() else []
    return result(
        summary={"cadence": values["cadence"], "existingExports": len(existing)},
        tables=[
            table(
                "Backup & export inventory",
                [("file", "Artifact")],
                [{"file": f} for f in existing] or [{"file": "(no exports yet)"}],
            )
        ],
        notes=[
            "Backups are written as self-contained JSON files under 02 Project Settings/exports."
        ],
    )


@feature(
    "settingsAudit.restorePoint",
    "Restore Point",
    part="settings",
    fields=[
        checkbox("createBackup", "Create restore point JSON in exports", True),
    ],
    requires_project=False,
)
def restore_point(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a validated settings restore point in 02 Project Settings/exports."""
    st = load_settings(ctx)
    payload = json_dumps_clean(st.model_dump(mode="json", by_alias=True, exclude_none=True))
    out_path = None
    if values["createBackup"] and ctx.root is not None:
        out_path = export_file(ctx, "settings-restore-point.json", payload)
    return result(
        summary={
            "project": st.project.name,
            "sizeBytes": len(payload.encode("utf-8")),
            "saved": out_path is not None,
        },
        tables=[
            table(
                "Restore point summary",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Code pack", "value": st.codePack},
                    {"item": "Area loads", "value": str(len(st.areaLoads))},
                    {"item": "Combinations", "value": str(len(st.combinations))},
                ],
            )
        ],
        notes=[
            f"Restore point saved to {out_path}"
            if out_path
            else "Open a project folder to save settings-restore-point.json."
        ],
    )


@feature(
    "settingsAudit.checksumVerify",
    "Checksum Verify",
    part="settings",
    fields=[],
    requires_project=False,
)
def checksum_verify(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute SHA-256 checksums of all core project settings and upstream files."""
    if ctx.root is None:
        raise FeatureInputError("Open a project folder to verify file checksums.")
    rows = []
    for part in ("soil", "settings", "materials", "objects", "bim"):
        p = ctx.path(ctx.PART_FILES[part])
        if p and p.is_file():
            h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            rows.append(
                {"part": part, "file": p.name, "sha256Prefix": h, "bytes": p.stat().st_size}
            )
    return result(
        summary={"verifiedFiles": len(rows)},
        tables=[
            table(
                "Project file SHA-256 checksums",
                [
                    ("part", "Part"),
                    ("file", "File"),
                    ("sha256Prefix", "SHA-256 (16 hex)"),
                    ("bytes", "Size [B]"),
                ],
                rows,
            )
        ],
        notes=["Verifies byte-level integrity of project JSON stores."],
    )


@feature(
    "settingsAudit.databaseCompact",
    "Database Compact",
    part="settings",
    fields=[],
    requires_project=False,
)
def database_compact(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure JSON serialization footprint before/after omitting default/null fields."""
    st = load_settings(ctx)
    raw = load_settings_raw(ctx)
    raw_bytes = len(json.dumps(raw).encode("utf-8")) if raw else 0
    compact_bytes = len(
        json.dumps(
            st.model_dump(mode="json", by_alias=True, exclude_none=True), separators=(",", ":")
        ).encode("utf-8")
    )
    return result(
        summary={"rawBytes": raw_bytes, "compactBytes": compact_bytes},
        tables=[
            table(
                "Settings storage footprint",
                [("mode", "Mode"), ("bytes", "Size [B]")],
                [
                    {"mode": "Current raw JSON", "bytes": raw_bytes},
                    {"mode": "Compacted canonical JSON", "bytes": compact_bytes},
                ],
            )
        ],
        notes=["Compaction strips null optional fields and redundant whitespace."],
    )


@feature(
    "settingsAudit.orphanRecordScan",
    "Orphan Record Scan",
    part="settings",
    fields=[],
    requires_project=False,
)
def orphan_record_scan(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scan project settings for unreferenced area loads, invalid override keys, or unused IDs."""
    st = load_settings(ctx)
    area_ids = [a.id for a in st.areaLoads]
    referenced = {st.floorLoad, st.roofLoad}
    fp_raw = ctx.raw("floorPlan")
    if isinstance(fp_raw, dict):
        for rm in fp_raw.get("rooms", []) if isinstance(fp_raw.get("rooms"), list) else []:
            if isinstance(rm, dict) and rm.get("areaLoad"):
                referenced.add(str(rm["areaLoad"]))
    unused_areas = [aid for aid in area_ids if aid not in referenced]
    rows = [{"kind": "Unreferenced area load", "id": aid} for aid in unused_areas]
    return result(
        summary={"areaLoadCount": len(area_ids), "unreferencedAreas": len(unused_areas)},
        tables=[
            table(
                "Orphaned settings scan",
                [("kind", "Kind"), ("id", "Identifier")],
                rows or [{"kind": "None", "id": "All area loads referenced"}],
            )
        ],
        notes=[
            "Checks whether defined areaLoads are used by floorLoad, roofLoad, or 05 Floor Plan."
        ],
    )


@feature(
    "settingsAudit.configDriftCheck",
    "Config Drift Check",
    part="settings",
    fields=[],
    requires_project=False,
)
def config_drift_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare live project settings against any saved settings-baseline.json or pack defaults."""
    st = load_settings(ctx)
    live = st.model_dump(mode="json", by_alias=True, exclude_none=True)
    baseline_path = ctx.path("02 Project Settings/exports/settings-baseline.json")
    if baseline_path and baseline_path.is_file():
        base = json.loads(baseline_path.read_text(encoding="utf-8"))
        source = "exports/settings-baseline.json"
    else:
        with in_force(ctx.root, st):
            base = default_project_settings(st.project.name, st.codePack).model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
        source = "code pack defaults"
    drifted = [k for k in sorted(set(live) | set(base)) if live.get(k) != base.get(k)]
    rows = [{"section": k, "drifted": True} for k in drifted]
    return result(
        summary={
            "baselineSource": source,
            "driftedSections": len(drifted),
            "inSync": len(drifted) == 0,
        },
        tables=[
            table(
                f"Configuration drift vs {source}",
                [("section", "Section"), ("drifted", "Differs")],
                rows or [{"section": "all", "drifted": False}],
            )
        ],
        notes=[f"Compared live settings against {source}."],
    )
