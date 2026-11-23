"""Review comments, change control, sharing manifests and conflict resolution for worksheets."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import UTC, datetime

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    checkbox,
    feature,
    number,
    result,
    select,
    text,
)
from saengine.features.documents_common import (
    ensure_cell,
    range_cells,
    require_root,
    save_worksheet_workspace,
    worksheet_workspace,
)


def _open(ctx, values):
    return worksheet_workspace(ctx, values["worksheetId"])


def _save(ctx, sheet, state, summary):
    path = save_worksheet_workspace(ctx, sheet, state)
    return result(summary={**summary, "worksheetId": sheet.id, "worksheetPath": path})


def _time():
    return datetime.now(UTC).isoformat(timespec="seconds")


@feature(
    "documentsWorksheetCollaboration.addComment",
    "Add Comment",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Cell address", "A1"),
        text("author", "Author", "Engineer"),
        text("comment", "Comment", "Please verify this input."),
    ],
)
def add_comment(ctx: FeatureContext, values: dict) -> dict:
    """Add a timestamped comment thread anchored to a worksheet cell."""
    sheet, state = _open(ctx, values)
    address = values["cell"].upper()
    ensure_cell(state, address)
    comments = state.setdefault("comments", [])
    thread = {
        "id": f"C{len(comments) + 1:04d}",
        "cell": address,
        "author": values["author"],
        "text": values["comment"],
        "createdAt": _time(),
        "replies": [],
        "resolved": False,
    }
    comments.append(thread)
    return _save(
        ctx,
        sheet,
        state,
        {"commentId": thread["id"], "cell": address, "commentCount": len(comments)},
    )


@feature(
    "documentsWorksheetCollaboration.replyComment",
    "Reply Comment",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("commentId", "Comment id", "C0001"),
        text("author", "Author", "Engineer"),
        text("reply", "Reply", "Updated and checked."),
    ],
)
def reply_comment(ctx: FeatureContext, values: dict) -> dict:
    """Append a timestamped response to an existing worksheet comment thread."""
    sheet, state = _open(ctx, values)
    thread = next((c for c in state.get("comments", []) if c["id"] == values["commentId"]), None)
    if thread is None:
        raise FeatureInputError("Comment thread was not found.")
    if thread.get("resolved"):
        raise FeatureInputError("Resolved comments cannot accept new replies.")
    thread.setdefault("replies", []).append(
        {"author": values["author"], "text": values["reply"], "at": _time()}
    )
    return _save(
        ctx, sheet, state, {"commentId": thread["id"], "replyCount": len(thread["replies"])}
    )


@feature(
    "documentsWorksheetCollaboration.resolveComment",
    "Resolve Comment",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("commentId", "Comment id", "C0001"),
        text("resolvedBy", "Resolved by", "Engineer"),
        checkbox("resolve", "Resolve thread", True),
    ],
)
def resolve_comment(ctx: FeatureContext, values: dict) -> dict:
    """Resolve or reopen a comment thread and record who made the review decision."""
    sheet, state = _open(ctx, values)
    thread = next((c for c in state.get("comments", []) if c["id"] == values["commentId"]), None)
    if thread is None:
        raise FeatureInputError("Comment thread was not found.")
    thread.update(
        {"resolved": values["resolve"], "resolvedBy": values["resolvedBy"], "resolvedAt": _time()}
    )
    return _save(
        ctx,
        sheet,
        state,
        {
            "commentId": thread["id"],
            "resolved": values["resolve"],
            "resolvedBy": values["resolvedBy"],
        },
    )


@feature(
    "documentsWorksheetCollaboration.filterComments",
    "Filter Comments",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        select(
            "status",
            "Thread status",
            [("all", "All"), ("open", "Open"), ("resolved", "Resolved")],
            "open",
        ),
        text("author", "Author filter", ""),
    ],
)
def filter_comments(ctx: FeatureContext, values: dict) -> dict:
    """Filter worksheet comment threads by resolution state and original author."""
    _sheet, state = _open(ctx, values)
    rows = []
    for item in state.get("comments", []):
        if values["status"] == "open" and item.get("resolved"):
            continue
        if values["status"] == "resolved" and not item.get("resolved"):
            continue
        if values["author"] and values["author"].casefold() not in item["author"].casefold():
            continue
        rows.append(
            {
                "id": item["id"],
                "cell": item["cell"],
                "author": item["author"],
                "text": item["text"],
                "resolved": item.get("resolved", False),
                "replyCount": len(item.get("replies", [])),
            }
        )
    return result(
        summary={"commentCount": len(rows)},
        tables=[
            {
                "title": "Worksheet comments",
                "columns": [
                    {"key": "id", "title": "Id"},
                    {"key": "cell", "title": "Cell"},
                    {"key": "author", "title": "Author"},
                    {"key": "text", "title": "Comment"},
                    {"key": "resolved", "title": "Resolved"},
                    {"key": "replyCount", "title": "Replies"},
                ],
                "rows": rows,
            }
        ],
    )


@feature(
    "documentsWorksheetCollaboration.trackChanges",
    "Track Changes",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        checkbox("enabled", "Track cell changes", True),
        text("actor", "Current editor", "Engineer"),
    ],
)
def track_changes(ctx: FeatureContext, values: dict) -> dict:
    """Enable or disable worksheet change tracking with the current editor attribution."""
    sheet, state = _open(ctx, values)
    state.setdefault("settings", {})["trackChanges"] = {
        "enabled": values["enabled"],
        "actor": values["actor"],
        "changedAt": _time(),
    }
    return _save(
        ctx, sheet, state, {"trackingEnabled": values["enabled"], "actor": values["actor"]}
    )


@feature(
    "documentsWorksheetCollaboration.acceptChange",
    "Accept Change",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("changeIndex", "Change index", 0, min=0),
        text("reviewer", "Reviewer", "Engineer"),
    ],
)
def accept_change(ctx: FeatureContext, values: dict) -> dict:
    """Accept a pending worksheet change record and store the reviewer and decision time."""
    sheet, state = _open(ctx, values)
    changes = state.get("changes", [])
    index = int(values["changeIndex"])
    if index >= len(changes):
        raise FeatureInputError("Change record index does not exist.")
    changes[index].update(
        {"reviewStatus": "accepted", "reviewer": values["reviewer"], "reviewedAt": _time()}
    )
    return _save(ctx, sheet, state, {"changeIndex": index, "reviewStatus": "accepted"})


@feature(
    "documentsWorksheetCollaboration.rejectChange",
    "Reject Change",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        number("changeIndex", "Change index", 0, min=0),
        text("reviewer", "Reviewer", "Engineer"),
        text("reason", "Rejection reason", "Requires calculation note"),
    ],
)
def reject_change(ctx: FeatureContext, values: dict) -> dict:
    """Reject a pending worksheet change record with an auditable reason."""
    sheet, state = _open(ctx, values)
    changes = state.get("changes", [])
    index = int(values["changeIndex"])
    if index >= len(changes):
        raise FeatureInputError("Change record index does not exist.")
    changes[index].update(
        {
            "reviewStatus": "rejected",
            "reviewer": values["reviewer"],
            "reason": values["reason"],
            "reviewedAt": _time(),
        }
    )
    return _save(
        ctx,
        sheet,
        state,
        {"changeIndex": index, "reviewStatus": "rejected", "reason": values["reason"]},
    )


@feature(
    "documentsWorksheetCollaboration.compareSheets",
    "Compare Sheets",
    part="documents",
    fields=[
        text("worksheetId", "Current worksheet id", "calculations"),
        text("otherWorksheetId", "Compare worksheet id", "calculations-review"),
    ],
)
def compare_sheets(ctx: FeatureContext, values: dict) -> dict:
    """Compare cell values and formulas between two worksheet workspaces and list differences."""
    current, base = _open(ctx, values)
    other, other_state = worksheet_workspace(ctx, values["otherWorksheetId"])
    left = base.get("cells", {})
    right = other_state.get("cells", {})
    diff = []
    for address in sorted(left.keys() | right.keys()):
        if left.get(address, {}) != right.get(address, {}):
            diff.append(
                {"cell": address, "current": left.get(address), "other": right.get(address)}
            )
    return result(
        summary={
            "differentCells": len(diff),
            "currentWorksheet": current.id,
            "comparedWorksheet": other.id,
        },
        tables=[
            {
                "title": "Worksheet differences",
                "columns": [
                    {"key": "cell", "title": "Cell"},
                    {"key": "current", "title": "Current value"},
                    {"key": "other", "title": "Compared value"},
                ],
                "rows": diff,
            }
        ],
    )


@feature(
    "documentsWorksheetCollaboration.shareSheet",
    "Share Sheet",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("recipient", "Recipient", "reviewer@example.com"),
        select(
            "access",
            "Access level",
            [("view", "View only"), ("comment", "Comment"), ("edit", "Edit")],
            "view",
        ),
        number("expiresDays", "Access duration", 14, min=1, max=365),
    ],
)
def share_sheet(ctx: FeatureContext, values: dict) -> dict:
    """Create a local share manifest with a recipient, least-required access and expiry."""
    sheet, state = _open(ctx, values)
    record = {
        "recipient": values["recipient"].strip(),
        "access": values["access"],
        "createdAt": _time(),
        "expiresDays": int(values["expiresDays"]),
    }
    shares = state.setdefault("shares", [])
    shares.append(record)
    return _save(
        ctx,
        sheet,
        state,
        {
            "shareId": len(shares),
            "recipient": record["recipient"],
            "access": record["access"],
            "expiresDays": record["expiresDays"],
            "manifestOnly": True,
        },
    )


@feature(
    "documentsWorksheetCollaboration.setPermissions",
    "Set Permissions",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("user", "User or role", "reviewer"),
        select(
            "permission",
            "Permission",
            [("view", "View"), ("comment", "Comment"), ("edit", "Edit"), ("admin", "Manage")],
            "view",
        ),
    ],
)
def set_permissions(ctx: FeatureContext, values: dict) -> dict:
    """Set or update a local worksheet permission entry for a project role or user."""
    sheet, state = _open(ctx, values)
    permissions = state.setdefault("permissions", {})
    permissions[values["user"].strip()] = {"permission": values["permission"], "updatedAt": _time()}
    return _save(ctx, sheet, state, {"user": values["user"], "permission": values["permission"]})


@feature(
    "documentsWorksheetCollaboration.exportPack",
    "Export Pack",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text(
            "zipPath",
            "Project-relative ZIP path",
            "11 Exports/worksheets/calculations-review-pack.zip",
        ),
        checkbox("includeComments", "Include comments and review history", True),
    ],
)
def export_pack(ctx: FeatureContext, values: dict) -> dict:
    """Package the typed worksheet, workspace state and optional review history into a ZIP."""
    root = require_root(ctx)
    target = (root / values["zipPath"]).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Export ZIP must be inside the project folder.") from exc
    sheet, state = _open(ctx, values)
    data = sheet.model_dump(mode="json", by_alias=True)
    workspace = {**state}
    if not values["includeComments"]:
        workspace.pop("comments", None)
        workspace.pop("changes", None)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{sheet.id}.json", json.dumps(data, ensure_ascii=False, indent=2))
        archive.writestr(
            f"{sheet.id}.workspace.json", json.dumps(workspace, ensure_ascii=False, indent=2)
        )
    return result(
        summary={
            "worksheetId": sheet.id,
            "archivePath": target.relative_to(root).as_posix(),
            "bytes": target.stat().st_size,
            "commentsIncluded": values["includeComments"],
        }
    )


@feature(
    "documentsWorksheetCollaboration.syncCopy",
    "Sync Copy",
    part="documents",
    fields=[
        text("worksheetId", "Source worksheet id", "calculations"),
        text("copyId", "Destination worksheet id", "calculations-copy"),
        checkbox("includeComments", "Copy comments", False),
    ],
)
def sync_copy(ctx: FeatureContext, values: dict) -> dict:
    """Create or update a separate worksheet copy with an independent workspace state."""
    sheet, state = _open(ctx, values)
    copy_id = values["copyId"].strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", copy_id):
        raise FeatureInputError("Copy id must use lowercase letters, digits and hyphens.")
    from saengine.library.worksheet import save_worksheet

    copied = sheet.model_copy(update={"id": copy_id})
    copy_state = json.loads(json.dumps(state))
    copy_state["id"] = copy_id
    if not values["includeComments"]:
        copy_state["comments"] = []
    root = require_root(ctx)
    path = save_worksheet(root, copied)
    copy_path = f"11 Exports/worksheets/{copy_id}.workspace.json"
    dest = root / copy_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(copy_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result(
        summary={
            "sourceWorksheet": sheet.id,
            "copyWorksheet": copy_id,
            "worksheetPath": path.relative_to(root).as_posix(),
            "commentsCopied": values["includeComments"],
        }
    )


@feature(
    "documentsWorksheetCollaboration.startReview",
    "Start Review",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("reviewer", "Assigned reviewer", "Engineer"),
        text("scope", "Review scope", "All calculations"),
    ],
)
def start_review(ctx: FeatureContext, values: dict) -> dict:
    """Open a worksheet review record with assigned reviewer, scope and a frozen starting hash."""
    sheet, state = _open(ctx, values)
    digest = hashlib.sha256(
        json.dumps(state.get("cells", {}), sort_keys=True, default=str).encode()
    ).hexdigest()
    reviews = state.setdefault("reviews", [])
    review = {
        "id": f"R{len(reviews) + 1:04d}",
        "reviewer": values["reviewer"],
        "scope": values["scope"],
        "status": "open",
        "startedAt": _time(),
        "startHash": digest,
    }
    reviews.append(review)
    return _save(
        ctx,
        sheet,
        state,
        {"reviewId": review["id"], "reviewer": review["reviewer"], "startHash": digest},
    )


@feature(
    "documentsWorksheetCollaboration.reviewerSignoff",
    "Reviewer Signoff",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("reviewId", "Review id", "R0001"),
        text("reviewer", "Reviewer", "Engineer"),
        select(
            "decision",
            "Decision",
            [("approved", "Approved"), ("changesRequired", "Changes required")],
            "approved",
        ),
        text("note", "Review note", "Calculations checked"),
    ],
)
def reviewer_signoff(ctx: FeatureContext, values: dict) -> dict:
    """Sign off an open worksheet review and bind the decision to the current cell-data hash."""
    sheet, state = _open(ctx, values)
    review = next((r for r in state.get("reviews", []) if r["id"] == values["reviewId"]), None)
    if review is None or review.get("status") != "open":
        raise FeatureInputError("An open review record was not found.")
    digest = hashlib.sha256(
        json.dumps(state.get("cells", {}), sort_keys=True, default=str).encode()
    ).hexdigest()
    review.update(
        {
            "status": values["decision"],
            "reviewer": values["reviewer"],
            "note": values["note"],
            "signedAt": _time(),
            "signedHash": digest,
        }
    )
    return _save(
        ctx,
        sheet,
        state,
        {"reviewId": review["id"], "decision": values["decision"], "signedHash": digest},
    )


@feature(
    "documentsWorksheetCollaboration.markupOverlay",
    "Markup Overlay",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Cell address", "A1"),
        text("reviewer", "Reviewer", "Engineer"),
        text("markup", "Markup note", "Check input source"),
        select(
            "severity",
            "Severity",
            [("info", "Information"), ("warning", "Warning"), ("blocking", "Blocking")],
            "warning",
        ),
    ],
)
def markup_overlay(ctx: FeatureContext, values: dict) -> dict:
    """Attach a visible review markup and severity to a worksheet cell."""
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["cell"])
    marks = cell.setdefault("reviewMarkup", [])
    marks.append(
        {
            "reviewer": values["reviewer"],
            "note": values["markup"],
            "severity": values["severity"],
            "at": _time(),
        }
    )
    return _save(
        ctx,
        sheet,
        state,
        {"cell": values["cell"], "markupCount": len(marks), "severity": values["severity"]},
    )


@feature(
    "documentsWorksheetCollaboration.sessionLog",
    "Session Log",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("actor", "Editor", "Engineer"),
        select(
            "event",
            "Session event",
            [("opened", "Opened"), ("closed", "Closed"), ("reviewed", "Reviewed")],
            "opened",
        ),
    ],
)
def session_log(ctx: FeatureContext, values: dict) -> dict:
    """Append a worksheet access or review event to the local session history."""
    sheet, state = _open(ctx, values)
    events = state.setdefault("sessionLog", [])
    events.append({"actor": values["actor"], "event": values["event"], "at": _time()})
    return _save(ctx, sheet, state, {"sessionEvent": values["event"], "eventCount": len(events)})


@feature(
    "documentsWorksheetCollaboration.lockRange",
    "Lock Range",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:B10"),
        text("lockedBy", "Locked by", "Engineer"),
    ],
)
def lock_range(ctx: FeatureContext, values: dict) -> dict:
    """Lock the selected cell range and store its owner and lock timestamp."""
    sheet, state = _open(ctx, values)
    cells = range_cells(values["range"])
    for address in cells:
        ensure_cell(state, address)["rangeLock"] = {
            "locked": True,
            "lockedBy": values["lockedBy"],
            "at": _time(),
        }
    return _save(ctx, sheet, state, {"lockedCells": len(cells), "lockedBy": values["lockedBy"]})


@feature(
    "documentsWorksheetCollaboration.unlockException",
    "Unlock Exception",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Cell address", "A1"),
        text("approvedBy", "Approver", "Lead engineer"),
        text("reason", "Reason", "Correction approved"),
    ],
)
def unlock_exception(ctx: FeatureContext, values: dict) -> dict:
    """Grant a documented, cell-specific unlock exception without removing the enclosing range lock."""
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["cell"])
    cell["unlockException"] = {
        "approvedBy": values["approvedBy"],
        "reason": values["reason"],
        "at": _time(),
    }
    return _save(
        ctx,
        sheet,
        state,
        {"cell": values["cell"], "approvedBy": values["approvedBy"], "reason": values["reason"]},
    )


@feature(
    "documentsWorksheetCollaboration.lockingStatus",
    "Locking Status",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("range", "Cell range", "A1:Z100"),
    ],
)
def locking_status(ctx: FeatureContext, values: dict) -> dict:
    """Report locked cells, lock owners and approved per-cell unlock exceptions."""
    _sheet, state = _open(ctx, values)
    rows = []
    for address in range_cells(values["range"]):
        cell = state.get("cells", {}).get(address, {})
        if cell.get("rangeLock", {}).get("locked"):
            rows.append(
                {
                    "cell": address,
                    "lockedBy": cell["rangeLock"].get("lockedBy"),
                    "exception": cell.get("unlockException"),
                }
            )
    return result(
        summary={
            "lockedCells": len(rows),
            "exceptionCount": sum(bool(row["exception"]) for row in rows),
        },
        tables=[
            {
                "title": "Lock status",
                "columns": [
                    {"key": "cell", "title": "Cell"},
                    {"key": "lockedBy", "title": "Locked by"},
                    {"key": "exception", "title": "Unlock exception"},
                ],
                "rows": rows,
            }
        ],
    )


@feature(
    "documentsWorksheetCollaboration.mergeChanges",
    "Merge Changes",
    part="documents",
    fields=[
        text("worksheetId", "Target worksheet id", "calculations"),
        text("sourceWorksheetId", "Source worksheet id", "calculations-review"),
        select(
            "strategy",
            "Merge rule",
            [
                ("sourceWins", "Source wins"),
                ("targetWins", "Target wins"),
                ("fillBlanks", "Fill target blanks"),
            ],
            "sourceWins",
        ),
    ],
)
def merge_changes(ctx: FeatureContext, values: dict) -> dict:
    """Merge source worksheet cells into a target using an explicit conflict strategy."""
    target, state = _open(ctx, values)
    source, source_state = worksheet_workspace(ctx, values["sourceWorksheetId"])
    changed = 0
    conflicts = []
    for address, cell in source_state.get("cells", {}).items():
        current = state.get("cells", {}).get(address)
        if (
            current is None
            or current == cell
            or values["strategy"] == "sourceWins"
            or (values["strategy"] == "fillBlanks" and not current)
        ):
            state.setdefault("cells", {})[address] = cell
            changed += 1
        elif current != cell:
            conflicts.append(address)
    state.setdefault("changes", []).append(
        {
            "action": "mergeWorksheet",
            "source": source.id,
            "strategy": values["strategy"],
            "changedCells": changed,
            "conflicts": conflicts,
            "at": _time(),
        }
    )
    return _save(
        ctx,
        target,
        state,
        {"mergedCells": changed, "conflicts": conflicts, "strategy": values["strategy"]},
    )


@feature(
    "documentsWorksheetCollaboration.conflictResolution",
    "Conflict Resolution",
    part="documents",
    fields=[
        text("worksheetId", "Worksheet id", "calculations"),
        text("cell", "Conflict cell", "A1"),
        text("sourceValue", "Source value", "1"),
        select("resolution", "Keep", [("source", "Source"), ("current", "Current")], "source"),
        text("resolvedBy", "Resolved by", "Engineer"),
    ],
)
def conflict_resolution(ctx: FeatureContext, values: dict) -> dict:
    """Resolve one merge conflict by choosing the incoming source value or retaining the current cell."""
    sheet, state = _open(ctx, values)
    cell = ensure_cell(state, values["cell"])
    previous = {key: cell.get(key) for key in ("value", "formula") if key in cell}
    if values["resolution"] == "source":
        try:
            incoming = json.loads(values["sourceValue"])
        except ValueError:
            incoming = values["sourceValue"]
        cell.pop("formula", None)
        cell["value"] = incoming
    cell.setdefault("conflictHistory", []).append(
        {
            "previous": previous,
            "resolution": values["resolution"],
            "resolvedBy": values["resolvedBy"],
            "at": _time(),
        }
    )
    return _save(
        ctx,
        sheet,
        state,
        {"cell": values["cell"], "resolution": values["resolution"], "previous": previous},
    )
