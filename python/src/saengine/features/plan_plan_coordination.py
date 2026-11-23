"""Plan coordination ribbon: linked models, change review, clashes and construction phasing."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

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
from saengine.features.plan_common import member_rows, ordered_stories, plan_data, point_xy
from saengine.library.mep import (
    CLASH_SETS,
    ISSUE_STATUSES,
    ClashTest,
    Coordination,
    CoordinationModel,
    IssueComment,
    MepModel,
)
from saengine.library.mep import parse as parse_mep

_PHASE_FILE = "05 Floor Plan/construction-phases.json"
_HISTORY_FILE = "05 Floor Plan/exports/sync-history.json"
_DECISIONS_FILE = "05 Floor Plan/exports/difference-decisions.json"
_ISSUE_STATUS_OPTIONS = [(key, label) for key, label in ISSUE_STATUSES.items()]


def _require_root(ctx: FeatureContext) -> Path:
    if ctx.root is None:
        raise FeatureInputError("Open a project folder to use model coordination.")
    return ctx.root


def _project_file(ctx: FeatureContext, raw_path: str, *, must_exist: bool = True) -> Path:
    """Resolve a project-relative path and reject paths that escape the project."""
    root = _require_root(ctx).resolve()
    relative = raw_path.strip()
    if not relative:
        raise FeatureInputError("Enter a project-relative IFC path.")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise FeatureInputError("Use a project-relative path for linked model files.")
    path = (root / candidate).resolve()
    if not path.is_relative_to(root):
        raise FeatureInputError("The model path must stay inside the project folder.")
    if must_exist and not path.is_file():
        raise FeatureInputError(f"Model file was not found: {relative}.")
    return path


def _open_ifc(ctx: FeatureContext, relative: str) -> tuple[Any, Path]:
    path = _project_file(ctx, relative)
    try:
        import ifcopenshell

        return ifcopenshell.open(str(path)), path
    except Exception as exc:  # IfcOpenShell can raise several parser and file errors.
        raise FeatureInputError(f"Could not read IFC model '{relative}': {exc}") from exc


def _mep(ctx: FeatureContext) -> MepModel:
    path = ctx.path("07 MEP/mep.json")
    try:
        raw = path.read_text(encoding="utf-8") if path is not None and path.is_file() else None
        return parse_mep(raw)
    except (OSError, ValueError) as exc:
        raise FeatureInputError(f"The MEP coordination model is invalid: {exc}") from exc


def _save_mep(ctx: FeatureContext, mep: MepModel) -> str:
    path = ctx.path("07 MEP/mep.json")
    if path is None:
        raise FeatureInputError("Open a project folder to save coordination data.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(mep.model_dump(mode="json", by_alias=True), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path.relative_to(ctx.root).as_posix()


def _coordination(mep: MepModel) -> Coordination:
    return mep.coordination or Coordination()


def _diff(ctx: FeatureContext, before: str, after: str) -> dict[str, Any]:
    from saengine.library.ifc_diff import diff_ifc

    before_ifc, _ = _open_ifc(ctx, before)
    after_ifc, _ = _open_ifc(ctx, after)
    try:
        return diff_ifc(before_ifc, after_ifc)
    except Exception as exc:  # IfcOpenShell geometry and malformed IFC failures vary by release.
        raise FeatureInputError(f"Could not compare the IFC models: {exc}") from exc


def _write_json(ctx: FeatureContext, relative: str, data: dict[str, Any]) -> str:
    path = ctx.path(relative)
    if path is None:
        raise FeatureInputError("Open a project folder to write the coordination record.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path.relative_to(ctx.root).as_posix()


def _read_json(ctx: FeatureContext, relative: str, default: dict[str, Any]) -> dict[str, Any]:
    path = ctx.path(relative)
    if path is None or not path.is_file():
        return default.copy()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FeatureInputError(f"Coordination record '{relative}' is unreadable JSON.") from exc
    if not isinstance(loaded, dict):
        raise FeatureInputError(f"Coordination record '{relative}' must contain a JSON object.")
    return loaded


def _plan_and_grid_rows(ctx: FeatureContext) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan = plan_data(ctx)
    rows = [
        {"axis": axis, "label": line["label"], "positionMm": float(line["position"])}
        for axis in ("x", "y")
        for line in plan["grids"][axis]
    ]
    return plan, rows


def _ifc_grid_rows(ifc: Any) -> list[dict[str, Any]]:
    """Read labelled, axis-aligned IFC grid lines and their global plan coordinate in mm."""
    import ifcopenshell.util.placement
    import ifcopenshell.util.unit
    import numpy as np

    scale = ifcopenshell.util.unit.calculate_unit_scale(ifc) * 1000.0
    rows: list[dict[str, Any]] = []
    for grid in ifc.by_type("IfcGrid"):
        placement = getattr(grid, "ObjectPlacement", None)
        transform = (
            ifcopenshell.util.placement.get_local_placement(placement)
            if placement is not None
            else np.eye(4)
        )
        for default_group, axes in (("u", grid.UAxes or ()), ("v", grid.VAxes or ())):
            for axis in axes:
                curve = axis.AxisCurve
                first: list[float] | None = None
                last: list[float] | None = None
                direction: list[float] | None = None
                if curve.is_a("IfcLine"):
                    first = list(curve.Pnt.Coordinates)
                    raw_direction = curve.Dir.Orientation.DirectionRatios
                    direction = [float(raw_direction[0]), float(raw_direction[1])]
                elif curve.is_a("IfcPolyline") and len(curve.Points) >= 2:
                    first = list(curve.Points[0].Coordinates)
                    last = list(curve.Points[-1].Coordinates)
                    direction = [float(last[0]) - float(first[0]), float(last[1]) - float(first[1])]
                if first is None or direction is None:
                    continue
                local = np.array([float(first[0]), float(first[1]), 0.0, 1.0])
                global_point = transform @ local
                global_direction = transform[:2, :2] @ np.array(direction)
                if abs(global_direction[0]) >= abs(global_direction[1]):
                    axis_name, coordinate = "y", float(global_point[1]) * scale
                else:
                    axis_name, coordinate = "x", float(global_point[0]) * scale
                rows.append(
                    {
                        "axis": axis_name,
                        "label": str(axis.AxisTag or default_group),
                        "positionMm": coordinate,
                    }
                )
    return rows


def _ifc_storeys(ifc: Any) -> list[dict[str, Any]]:
    import ifcopenshell.util.unit

    scale = ifcopenshell.util.unit.calculate_unit_scale(ifc) * 1000.0
    return [
        {
            "name": str(storey.Name or ""),
            "longName": str(storey.LongName or ""),
            "elevationMm": float(storey.Elevation or 0.0) * scale,
        }
        for storey in ifc.by_type("IfcBuildingStorey")
    ]


def _file_metadata(ifc: Any, path: Path) -> dict[str, Any]:
    count = len(ifc.by_type("IfcElement"))
    project = next(iter(ifc.by_type("IfcProject")), None)
    return {
        "schema": str(getattr(ifc, "schema", "")),
        "projectName": str(getattr(project, "Name", "") or "") if project else "",
        "elementCount": count,
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


@feature(
    "planPlanCoordination.syncGrids",
    "Sync Grids",
    part="floorPlan",
    fields=[
        text("modelPath", "Linked IFC path", "06 BIM/architectural.ifc"),
        number("toleranceMm", "Position tolerance", 5, unit="mm", min=0),
    ],
)
def sync_grids(ctx: FeatureContext, values: dict) -> dict:
    """Compare project grid labels and positions with the grid axes in a linked IFC model."""
    _, project_rows = _plan_and_grid_rows(ctx)
    ifc, _ = _open_ifc(ctx, values["modelPath"])
    linked_rows = _ifc_grid_rows(ifc)
    if not linked_rows:
        raise FeatureInputError("The linked IFC model has no readable IfcGrid axes.")
    linked = {(row["axis"], row["label"]): row for row in linked_rows}
    rows = []
    for grid in project_rows:
        key = (grid["axis"], grid["label"])
        other = linked.get(key)
        difference = float(other["positionMm"]) - grid["positionMm"] if other else None
        rows.append(
            {
                "axis": grid["axis"].upper(),
                "label": grid["label"],
                "projectPositionMm": grid["positionMm"],
                "linkedPositionMm": other["positionMm"] if other else None,
                "differenceMm": difference,
                "status": "missing in link"
                if other is None
                else "aligned"
                if abs(difference) <= values["toleranceMm"]
                else "position differs",
            }
        )
    unmatched = [
        row
        for key, row in linked.items()
        if key not in {(r["axis"], r["label"]) for r in project_rows}
    ]
    rows.extend(
        {
            "axis": row["axis"].upper(),
            "label": row["label"],
            "projectPositionMm": None,
            "linkedPositionMm": row["positionMm"],
            "differenceMm": None,
            "status": "extra in link",
        }
        for row in unmatched
    )
    return result(
        summary={
            "projectGridCount": len(project_rows),
            "linkedGridCount": len(linked_rows),
            "positionToleranceMm": values["toleranceMm"],
            "alignedCount": sum(row["status"] == "aligned" for row in rows),
            "reviewCount": sum(row["status"] != "aligned" for row in rows),
        },
        tables=[
            table(
                "Linked grid comparison",
                [
                    ("axis", "Axis"),
                    ("label", "Grid"),
                    ("projectPositionMm", "Project position", "mm"),
                    ("linkedPositionMm", "Linked position", "mm"),
                    ("differenceMm", "Link minus project", "mm"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=[
            f"Source IFC: {values['modelPath']}. Axis coordinates are transformed to the linked model's global placement."
        ],
    )


@feature(
    "planPlanCoordination.syncStories",
    "Sync Stories",
    part="floorPlan",
    fields=[text("modelPath", "Linked IFC path", "06 BIM/architectural.ifc")],
)
def sync_stories(ctx: FeatureContext, values: dict) -> dict:
    """Match project storeys to linked IFC building storeys by id, name or long name."""
    plan = plan_data(ctx)
    ifc, _ = _open_ifc(ctx, values["modelPath"])
    linked = _ifc_storeys(ifc)
    if not linked:
        raise FeatureInputError("The linked IFC model has no IfcBuildingStorey entities.")
    rows = []
    for story in ordered_stories(plan):
        match = next(
            (
                s
                for s in linked
                if story["id"] in (s["name"], s["longName"])
                or story["name"] in (s["name"], s["longName"])
            ),
            None,
        )
        rows.append(
            {
                "storyId": story["id"],
                "storyName": story["name"],
                "linkedStorey": match["longName"] or match["name"] if match else "",
                "match": "matched" if match else "missing",
            }
        )
    return result(
        summary={
            "projectStoreys": len(plan["stories"]),
            "linkedStoreys": len(linked),
            "matchedStoreys": sum(row["match"] == "matched" for row in rows),
            "missingStoreys": sum(row["match"] == "missing" for row in rows),
        },
        tables=[
            table(
                "Storey links",
                [
                    ("storyId", "Project storey"),
                    ("storyName", "Project name"),
                    ("linkedStorey", "Linked IFC storey"),
                    ("match", "Match"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planPlanCoordination.syncLevels",
    "Sync Levels",
    part="floorPlan",
    fields=[
        text("modelPath", "Linked IFC path", "06 BIM/architectural.ifc"),
        number("toleranceMm", "Elevation tolerance", 10, unit="mm", min=0),
    ],
)
def sync_levels(ctx: FeatureContext, values: dict) -> dict:
    """Compare matched project and linked-storey elevations and report required vertical offsets."""
    plan = plan_data(ctx)
    ifc, _ = _open_ifc(ctx, values["modelPath"])
    linked = _ifc_storeys(ifc)
    if not linked:
        raise FeatureInputError("The linked IFC model has no IfcBuildingStorey elevations.")
    rows = []
    for story in ordered_stories(plan):
        match = next(
            (
                s
                for s in linked
                if story["id"] in (s["name"], s["longName"])
                or story["name"] in (s["name"], s["longName"])
            ),
            None,
        )
        difference = float(match["elevationMm"]) - float(story["elevation"]) if match else None
        rows.append(
            {
                "storyId": story["id"],
                "projectElevationMm": story["elevation"],
                "linkedElevationMm": match["elevationMm"] if match else None,
                "offsetMm": difference,
                "status": "missing"
                if match is None
                else "within tolerance"
                if abs(difference) <= values["toleranceMm"]
                else "elevation differs",
            }
        )
    return result(
        summary={
            "matchedStoreys": sum(row["status"] != "missing" for row in rows),
            "elevationDifferences": sum(row["status"] == "elevation differs" for row in rows),
            "toleranceMm": values["toleranceMm"],
        },
        tables=[
            table(
                "Storey elevation comparison",
                [
                    ("storyId", "Storey"),
                    ("projectElevationMm", "Project elevation", "mm"),
                    ("linkedElevationMm", "Linked elevation", "mm"),
                    ("offsetMm", "Linked minus project", "mm"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        notes=[
            "The reported offset is the linked level elevation minus the floor-plan elevation; no model datum is changed."
        ],
    )


@feature(
    "planPlanCoordination.syncHistory",
    "Sync History",
    part="floorPlan",
    fields=[
        text("modelPath", "Linked IFC path", "06 BIM/architectural.ifc"),
        select(
            "action",
            "History action",
            [("record", "Record current model"), ("review", "Review recorded history")],
            "record",
        ),
    ],
)
def sync_history(ctx: FeatureContext, values: dict) -> dict:
    """Record or review hash-stamped snapshots of a linked IFC model's synchronization history."""
    ifc, path = _open_ifc(ctx, values["modelPath"])
    history = _read_json(
        ctx, _HISTORY_FILE, {"schema": "saengine.planSyncHistory/1", "entries": []}
    )
    entries = history.get("entries", [])
    if not isinstance(entries, list):
        raise FeatureInputError("The synchronization history entries must be a list.")
    if values["action"] == "review":
        rows = [row for row in entries if row.get("path") == values["modelPath"]]
        return result(
            summary={
                "modelPath": values["modelPath"],
                "snapshotCount": len(rows),
                "latestSha256": rows[-1]["sha256"] if rows else "",
            },
            tables=[
                table(
                    "Model synchronization history",
                    [
                        ("recordedAt", "Recorded at"),
                        ("path", "Model path"),
                        ("bytes", "File size", "byte"),
                        ("sha256", "SHA-256"),
                    ],
                    rows,
                )
            ],
        )
    metadata = _file_metadata(ifc, path)
    prior = next((row for row in reversed(entries) if row.get("path") == values["modelPath"]), None)
    changed = prior is None or prior.get("sha256") != metadata["sha256"]
    if changed:
        entries.append(
            {
                "recordedAt": datetime.now(UTC).isoformat(timespec="seconds"),
                "path": values["modelPath"],
                **metadata,
            }
        )
    history["entries"] = entries
    written = _write_json(ctx, _HISTORY_FILE, history)
    return result(
        summary={
            "modelPath": values["modelPath"],
            "snapshotRecorded": changed,
            "snapshotCount": sum(row.get("path") == values["modelPath"] for row in entries),
            "sha256": metadata["sha256"],
        },
        notes=[f"Synchronization history: {written}"],
    )


@feature(
    "planPlanCoordination.compareModels",
    "Compare Models",
    part="floorPlan",
    fields=[
        text("beforeModel", "Earlier IFC path", "11 Exports/previous.ifc"),
        text("afterModel", "Current IFC path", "11 Exports/current.ifc"),
    ],
)
def compare_models(ctx: FeatureContext, values: dict) -> dict:
    """Compare two IFC revisions by GlobalId, geometry, placements, materials and properties."""
    diff = _diff(ctx, values["beforeModel"], values["afterModel"])
    rows = [
        {
            "kind": row["kind"],
            "globalId": row["id"],
            "description": row["what"],
            "colour": row["colour"],
        }
        for row in diff["changes"]
    ]
    return result(
        summary={
            "changeSummary": diff["summary"],
            "addedCount": diff["counts"]["added"],
            "removedCount": diff["counts"]["removed"],
            "changedCount": diff["counts"]["changed"],
            "unchangedCount": diff["counts"]["unchanged"],
        },
        tables=[
            table(
                "IFC revision changes",
                [
                    ("kind", "Change"),
                    ("globalId", "GlobalId"),
                    ("description", "Difference"),
                    ("colour", "Display colour"),
                ],
                rows,
            )
        ],
        notes=["Comparison uses the engine's semantic and geometric IFC diff by GlobalId."],
    )


@feature(
    "planPlanCoordination.highlightDifferences",
    "Highlight Differences",
    part="floorPlan",
    fields=[
        text("beforeModel", "Earlier IFC path", "11 Exports/previous.ifc"),
        text("afterModel", "Current IFC path", "11 Exports/current.ifc"),
        select(
            "changeKind",
            "Difference type",
            [
                ("all", "All differences"),
                ("added", "Added"),
                ("removed", "Removed"),
                ("changed", "Changed"),
            ],
            "all",
        ),
    ],
)
def highlight_differences(ctx: FeatureContext, values: dict) -> dict:
    """Return colour-coded IFC GlobalIds and changed fields for the selected difference class."""
    diff = _diff(ctx, values["beforeModel"], values["afterModel"])
    changes = [
        row
        for row in diff["changes"]
        if values["changeKind"] == "all" or row["kind"] == values["changeKind"]
    ]
    rows = [
        {
            "globalId": row["id"],
            "kind": row["kind"],
            "colour": row["colour"],
            "hex": row["color"],
            "fields": ", ".join(row.get("fields", [])),
            "description": row["what"],
        }
        for row in changes
    ]
    return result(
        summary={
            "highlightCount": len(rows),
            "changeKind": values["changeKind"],
            "addedCount": sum(row["kind"] == "added" for row in rows),
            "removedCount": sum(row["kind"] == "removed" for row in rows),
            "changedCount": sum(row["kind"] == "changed" for row in rows),
        },
        tables=[
            table(
                "Highlighted model differences",
                [
                    ("globalId", "GlobalId"),
                    ("kind", "Change"),
                    ("colour", "Colour"),
                    ("hex", "Hex colour"),
                    ("fields", "Changed fields"),
                    ("description", "Difference"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planPlanCoordination.acceptDifference",
    "Accept Difference",
    part="floorPlan",
    fields=[
        text("beforeModel", "Earlier IFC path", "11 Exports/previous.ifc"),
        text("afterModel", "Current IFC path", "11 Exports/current.ifc"),
        text("globalId", "Changed element GlobalId", ""),
        text("reviewer", "Reviewer", ""),
        text("comment", "Acceptance note", ""),
    ],
)
def accept_difference(ctx: FeatureContext, values: dict) -> dict:
    """Verify a selected IFC revision difference and record its acceptance with a review note."""
    diff = _diff(ctx, values["beforeModel"], values["afterModel"])
    change = next((item for item in diff["changes"] if item["id"] == values["globalId"]), None)
    if change is None:
        raise FeatureInputError(
            "GlobalId was not found among the differences between these IFC models."
        )
    decision = {
        "globalId": change["id"],
        "kind": change["kind"],
        "disposition": "accepted",
        "reviewer": values["reviewer"].strip(),
        "comment": values["comment"].strip(),
        "beforeModel": values["beforeModel"],
        "afterModel": values["afterModel"],
    }
    state = _read_json(
        ctx, _DECISIONS_FILE, {"schema": "saengine.planDifferenceDecisions/1", "decisions": []}
    )
    decisions = state.get("decisions", [])
    decisions.append(decision)
    state["decisions"] = decisions
    written = _write_json(ctx, _DECISIONS_FILE, state)
    return result(
        summary={
            "globalId": change["id"],
            "changeKind": change["kind"],
            "accepted": True,
            "decisionCount": len(decisions),
        },
        tables=[
            table(
                "Accepted model difference",
                [
                    ("globalId", "GlobalId"),
                    ("kind", "Change"),
                    ("reviewer", "Reviewer"),
                    ("comment", "Acceptance note"),
                ],
                [decision],
            )
        ],
        notes=[f"Acceptance recorded in {written}."],
    )


@feature(
    "planPlanCoordination.rejectDifference",
    "Reject Difference",
    part="floorPlan",
    fields=[
        text("beforeModel", "Earlier IFC path", "11 Exports/previous.ifc"),
        text("afterModel", "Current IFC path", "11 Exports/current.ifc"),
        text("globalId", "Changed element GlobalId", ""),
        text("reviewer", "Reviewer", ""),
        text("comment", "Rejection reason", ""),
    ],
)
def reject_difference(ctx: FeatureContext, values: dict) -> dict:
    """Verify a selected IFC revision difference and record its rejection with a review reason."""
    diff = _diff(ctx, values["beforeModel"], values["afterModel"])
    change = next((item for item in diff["changes"] if item["id"] == values["globalId"]), None)
    if change is None:
        raise FeatureInputError(
            "GlobalId was not found among the differences between these IFC models."
        )
    decision = {
        "globalId": change["id"],
        "kind": change["kind"],
        "disposition": "rejected",
        "reviewer": values["reviewer"].strip(),
        "comment": values["comment"].strip(),
        "beforeModel": values["beforeModel"],
        "afterModel": values["afterModel"],
    }
    state = _read_json(
        ctx, _DECISIONS_FILE, {"schema": "saengine.planDifferenceDecisions/1", "decisions": []}
    )
    decisions = state.get("decisions", [])
    decisions.append(decision)
    state["decisions"] = decisions
    written = _write_json(ctx, _DECISIONS_FILE, state)
    return result(
        summary={
            "globalId": change["id"],
            "changeKind": change["kind"],
            "rejected": True,
            "decisionCount": len(decisions),
        },
        tables=[
            table(
                "Rejected model difference",
                [
                    ("globalId", "GlobalId"),
                    ("kind", "Change"),
                    ("reviewer", "Reviewer"),
                    ("comment", "Rejection reason"),
                ],
                [decision],
            )
        ],
        notes=[f"Rejection recorded in {written}."],
    )


@feature(
    "planPlanCoordination.linkModel",
    "Link Model",
    part="floorPlan",
    fields=[
        text("modelPath", "Project-relative IFC path", "06 BIM/architectural.ifc"),
        text("name", "Model name", "Architectural model"),
    ],
)
def link_model(ctx: FeatureContext, values: dict) -> dict:
    """Validate and register an external IFC model in the project's coordination links."""
    ifc, path = _open_ifc(ctx, values["modelPath"])
    metadata = _file_metadata(ifc, path)
    mep = _mep(ctx)
    coordination = _coordination(mep)
    models = [model.model_copy(deep=True) for model in coordination.models]
    existing = next((model for model in models if model.path == values["modelPath"]), None)
    if existing:
        existing.name = values["name"].strip() or existing.name
    else:
        models.append(
            CoordinationModel(
                path=values["modelPath"],
                name=values["name"].strip() or path.stem,
                visible=True,
            )
        )
    mep.coordination = coordination.model_copy(update={"models": models})
    saved = _save_mep(ctx, mep)
    return result(
        summary={
            "modelPath": values["modelPath"],
            "linkCount": len(models),
            "elementCount": metadata["elementCount"],
            "ifcSchema": metadata["schema"],
        },
        notes=[f"Coordination model link saved in {saved}."],
    )


@feature(
    "planPlanCoordination.alignModel",
    "Align Model",
    part="floorPlan",
    fields=[
        text("modelPath", "Linked IFC path", "06 BIM/architectural.ifc"),
        number("translationXMm", "X translation", 0, unit="mm"),
        number("translationYMm", "Y translation", 0, unit="mm"),
        number("translationZMm", "Z translation", 0, unit="mm"),
        number("rotationDeg", "Plan rotation", 0, unit="deg"),
    ],
)
def align_model(ctx: FeatureContext, values: dict) -> dict:
    """Build a rigid plan rotation and translation transform for an IFC model's local coordinates."""
    ifc, path = _open_ifc(ctx, values["modelPath"])
    radians = math.radians(values["rotationDeg"])
    cosine, sine = math.cos(radians), math.sin(radians)
    transform = [
        [cosine, -sine, 0.0, values["translationXMm"]],
        [sine, cosine, 0.0, values["translationYMm"]],
        [0.0, 0.0, 1.0, values["translationZMm"]],
        [0.0, 0.0, 0.0, 1.0],
    ]
    metadata = _file_metadata(ifc, path)
    return result(
        summary={
            "modelPath": values["modelPath"],
            "rotationDeg": values["rotationDeg"] % 360,
            "translationXMm": values["translationXMm"],
            "translationYMm": values["translationYMm"],
            "translationZMm": values["translationZMm"],
            "elementCount": metadata["elementCount"],
            "transformMatrix": transform,
        },
        tables=[
            table(
                "IFC to project transform",
                [
                    ("row", "Row"),
                    ("m00", "X"),
                    ("m01", "Y"),
                    ("m02", "Z"),
                    ("translationMm", "Translation", "mm"),
                ],
                [
                    {
                        "row": "X",
                        "m00": cosine,
                        "m01": -sine,
                        "m02": 0.0,
                        "translationMm": values["translationXMm"],
                    },
                    {
                        "row": "Y",
                        "m00": sine,
                        "m01": cosine,
                        "m02": 0.0,
                        "translationMm": values["translationYMm"],
                    },
                    {
                        "row": "Z",
                        "m00": 0.0,
                        "m01": 0.0,
                        "m02": 1.0,
                        "translationMm": values["translationZMm"],
                    },
                ],
            )
        ],
        notes=[
            "This reports the rigid transform for review; it does not rewrite the linked IFC source."
        ],
    )


@feature(
    "planPlanCoordination.updateLink",
    "Update Link",
    part="floorPlan",
    fields=[text("modelPath", "Linked IFC path", "06 BIM/architectural.ifc")],
)
def update_link(ctx: FeatureContext, values: dict) -> dict:
    """Refresh a registered coordination model's display name and report its current IFC contents."""
    ifc, path = _open_ifc(ctx, values["modelPath"])
    metadata = _file_metadata(ifc, path)
    mep = _mep(ctx)
    coordination = _coordination(mep)
    linked = next(
        (model for model in coordination.models if model.path == values["modelPath"]), None
    )
    if linked is None:
        raise FeatureInputError("Add this IFC path to the coordination links before updating it.")
    project = next(iter(ifc.by_type("IfcProject")), None)
    linked.name = str(getattr(project, "Name", "") or path.stem) if project else path.stem
    mep.coordination = coordination
    saved = _save_mep(ctx, mep)
    return result(
        summary={
            "modelPath": values["modelPath"],
            "modelName": linked.name,
            "ifcSchema": metadata["schema"],
            "elementCount": metadata["elementCount"],
            "sha256": metadata["sha256"],
        },
        notes=[
            f"Updated link metadata in {saved}. The linked IFC remains the source of model geometry."
        ],
    )


@feature(
    "planPlanCoordination.linkStatus",
    "Link Status",
    part="floorPlan",
    fields=[],
)
def link_status(ctx: FeatureContext, values: dict) -> dict:
    """Inspect project coordination and MEP IFC links for missing files and current model metadata."""
    mep = _mep(ctx)
    links = [(model.path, model.name, "external") for model in _coordination(mep).models]
    links.extend((model.path, model.discipline, "MEP") for model in mep.ifcModels)
    if not links:
        return result(
            summary={"linkCount": 0, "availableCount": 0, "missingCount": 0},
            notes=["No linked IFC models are registered in the MEP coordination model."],
        )
    rows = []
    for relative, name, kind in links:
        path = _project_file(ctx, relative, must_exist=False)
        status, schema, count = "missing", "", 0
        if path.is_file():
            try:
                import ifcopenshell

                ifc = ifcopenshell.open(str(path))
                schema = str(ifc.schema)
                count = len(ifc.by_type("IfcElement"))
                status = "available"
            except Exception as exc:  # noqa: BLE001 - IfcOpenShell raises different parser errors.
                status = f"unreadable: {exc}"
        rows.append(
            {
                "path": relative,
                "name": name,
                "linkType": kind,
                "status": status,
                "ifcSchema": schema,
                "elementCount": count,
            }
        )
    return result(
        summary={
            "linkCount": len(rows),
            "availableCount": sum(row["status"] == "available" for row in rows),
            "missingCount": sum(row["status"] == "missing" for row in rows),
        },
        tables=[
            table(
                "IFC model links",
                [
                    ("path", "Project path"),
                    ("name", "Name or discipline"),
                    ("linkType", "Link type"),
                    ("status", "Status"),
                    ("ifcSchema", "IFC schema"),
                    ("elementCount", "Elements"),
                ],
                rows,
            )
        ],
    )


def _run_tests(
    ctx: FeatureContext, mep: MepModel, test_ids: list[str] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    from saengine.mep.coordination import run_tests

    try:
        return run_tests(str(_require_root(ctx)), mep, test_ids)
    except Exception as exc:  # IfcOpenShell geometry errors vary across supported platforms.
        raise FeatureInputError(f"Coordination clash analysis could not run: {exc}") from exc


@feature(
    "planPlanCoordination.clashDetect",
    "Clash Detect",
    part="floorPlan",
    fields=[],
)
def clash_detect(ctx: FeatureContext, values: dict) -> dict:
    """Run all enabled multi-discipline clash tests using the engine's IFC geometry workflow."""
    mep = _mep(ctx)
    clashes, per_test, notes = _run_tests(ctx, mep, None)
    rows = [
        {
            "key": item["key"],
            "test": item["test"],
            "elements": " / ".join(item["labels"]),
            "kind": item["kind"],
            "depthMm": item["depth"],
            "story": item["story"] or "",
        }
        for item in clashes
    ]
    return result(
        summary={
            "enabledTests": len(per_test),
            "clashCount": len(clashes),
            "hardClashCount": sum(item["kind"] == "hard" for item in clashes),
            "clearanceClashCount": sum(item["kind"] == "clearance" for item in clashes),
        },
        tables=[
            table(
                "Clash findings",
                [
                    ("key", "Clash key"),
                    ("test", "Test"),
                    ("elements", "Elements"),
                    ("kind", "Kind"),
                    ("depthMm", "Overlap or gap", "mm"),
                    ("story", "Storey"),
                ],
                rows,
            ),
            table(
                "Clash test totals",
                [
                    ("test", "Test"),
                    ("name", "Test name"),
                    ("found", "Findings"),
                    ("coordinated", "Coordinated crossings"),
                ],
                per_test,
            ),
        ],
        notes=notes,
    )


@feature(
    "planPlanCoordination.clearanceRule",
    "Clearance Rule",
    part="floorPlan",
    fields=[
        text("testId", "Rule id", "C1"),
        text("name", "Rule name", "Structure service clearance"),
        text("setA", "Set A (comma-separated)", "structure"),
        text("setB", "Set B (comma-separated)", "mechanical,plumbing"),
        number("clearanceMm", "Required clearance", 100, unit="mm", min=0),
        number("toleranceMm", "Hard overlap tolerance", 2, unit="mm", min=0),
        checkbox("ignoreSameModel", "Ignore within one model", True),
    ],
)
def clearance_rule(ctx: FeatureContext, values: dict) -> dict:
    """Create or update an enabled clearance clash test between selected coordination model sets."""
    set_a = list(dict.fromkeys(part.strip() for part in values["setA"].split(",") if part.strip()))
    set_b = list(dict.fromkeys(part.strip() for part in values["setB"].split(",") if part.strip()))
    if not set_a or not set_b or (set(set_a) | set(set_b)) - set(CLASH_SETS):
        raise FeatureInputError(
            f"Sets A and B must contain one or more of: {', '.join(CLASH_SETS)}."
        )
    mep = _mep(ctx)
    coordination = _coordination(mep)
    tests = [test.model_copy(deep=True) for test in coordination.tests]
    rule = ClashTest(
        id=values["testId"].strip(),
        name=values["name"].strip(),
        a=set_a,
        b=set_b,
        kind="clearance",
        clearance=values["clearanceMm"],
        tolerance=values["toleranceMm"],
        ignoreSameModel=values["ignoreSameModel"],
        enabled=True,
    )
    if not rule.id:
        raise FeatureInputError("Enter a clearance rule id.")
    existing = next((index for index, test in enumerate(tests) if test.id == rule.id), None)
    if existing is None:
        tests.append(rule)
    else:
        tests[existing] = rule
    mep.coordination = coordination.model_copy(update={"tests": tests})
    saved = _save_mep(ctx, mep)
    return result(
        summary={
            "testId": rule.id,
            "kind": rule.kind,
            "clearanceMm": rule.clearance,
            "setACount": len(rule.a),
            "setBCount": len(rule.b),
            "testCount": len(tests),
        },
        tables=[
            table(
                "Clearance rule sets",
                [("side", "Side"), ("modelSet", "Model set")],
                [
                    {"side": side, "modelSet": name}
                    for side, names in (("A", rule.a), ("B", rule.b))
                    for name in names
                ],
            )
        ],
        notes=[f"Clearance rule saved in {saved}."],
    )


@feature(
    "planPlanCoordination.hardClash",
    "Hard Clash",
    part="floorPlan",
    fields=[text("testId", "Hard clash test id (blank = all hard tests)", "")],
)
def hard_clash(ctx: FeatureContext, values: dict) -> dict:
    """Run only hard-intersection tests and isolate clashes that exceed their overlap tolerance."""
    mep = _mep(ctx)
    tests = [test for test in _coordination(mep).tests if test.enabled and test.kind == "hard"]
    if not tests:
        raise FeatureInputError(
            "Create an enabled hard-clash test before filtering geometric intersections."
        )
    chosen = (
        [test for test in tests if test.id == values["testId"].strip()]
        if values["testId"].strip()
        else tests
    )
    if not chosen:
        raise FeatureInputError("The selected id is not an enabled hard-clash test.")
    clashes, totals, notes = _run_tests(ctx, mep, [test.id for test in chosen])
    hard = [item for item in clashes if item["kind"] == "hard"]
    rows = [
        {
            "test": item["test"],
            "elementA": item["labels"][0],
            "elementB": item["labels"][1],
            "overlapMm": item["depth"],
            "pointXMm": item["point"][0],
            "pointYMm": item["point"][1],
            "pointZMm": item["point"][2],
        }
        for item in hard
    ]
    return result(
        summary={"hardClashCount": len(hard), "testsRun": len(totals)},
        tables=[
            table(
                "Hard geometric intersections",
                [
                    ("test", "Test"),
                    ("elementA", "Element A"),
                    ("elementB", "Element B"),
                    ("overlapMm", "Overlap", "mm"),
                    ("pointXMm", "Point X", "mm"),
                    ("pointYMm", "Point Y", "mm"),
                    ("pointZMm", "Point Z", "mm"),
                ],
                rows,
            )
        ],
        notes=notes,
    )


@feature(
    "planPlanCoordination.softClash",
    "Soft Clash",
    part="floorPlan",
    fields=[text("testId", "Clearance test id", "C1")],
)
def soft_clash(ctx: FeatureContext, values: dict) -> dict:
    """Run one clearance rule and list near misses that fall within its required gap."""
    mep = _mep(ctx)
    test = next(
        (
            item
            for item in _coordination(mep).tests
            if item.id == values["testId"].strip() and item.enabled
        ),
        None,
    )
    if test is None or test.kind != "clearance":
        raise FeatureInputError("Choose an enabled clearance rule from the coordination tests.")
    clashes, totals, notes = _run_tests(ctx, mep, [test.id])
    soft = [item for item in clashes if item["kind"] == "clearance"]
    rows = [
        {
            "test": item["test"],
            "elementA": item["labels"][0],
            "elementB": item["labels"][1],
            "gapMm": item["depth"],
            "pointXMm": item["point"][0],
            "pointYMm": item["point"][1],
            "pointZMm": item["point"][2],
        }
        for item in soft
    ]
    return result(
        summary={
            "clearanceRule": test.id,
            "requiredClearanceMm": test.clearance,
            "softClashCount": len(soft),
            "testsRun": len(totals),
        },
        tables=[
            table(
                "Clearance violations",
                [
                    ("test", "Test"),
                    ("elementA", "Element A"),
                    ("elementB", "Element B"),
                    ("gapMm", "Gap", "mm"),
                    ("pointXMm", "Point X", "mm"),
                    ("pointYMm", "Point Y", "mm"),
                    ("pointZMm", "Point Z", "mm"),
                ],
                rows,
            )
        ],
        notes=notes,
    )


def _phase_state(ctx: FeatureContext) -> dict[str, Any]:
    state = _read_json(ctx, _PHASE_FILE, {"schema": "saengine.planPhases/1", "assignments": []})
    if not isinstance(state.get("assignments"), list):
        raise FeatureInputError("The construction phase file must contain an assignments list.")
    return state


@feature(
    "planPlanCoordination.constructionPhase",
    "Construction Phase",
    part="floorPlan",
    fields=[
        text("memberIds", "Member ids (comma-separated; blank = all)", ""),
        text("phaseId", "Phase id", "P1"),
        text("phaseName", "Phase name", "Primary structure"),
        number("startDay", "Start day", 0, unit="day", min=0),
        number("durationDays", "Duration", 5, unit="day", min=0.01),
    ],
)
def construction_phase(ctx: FeatureContext, values: dict) -> dict:
    """Assign selected structural members to a named construction phase and schedule interval."""
    rows = member_rows(plan_data(ctx))
    wanted = {item.strip() for item in values["memberIds"].split(",") if item.strip()}
    selected = [row for row in rows if not wanted or row["id"] in wanted]
    missing = wanted - {row["id"] for row in selected}
    if missing:
        raise FeatureInputError(f"Unknown member id(s): {', '.join(sorted(missing))}.")
    if not selected:
        raise FeatureInputError("The floor plan has no structural members to phase.")
    phase_id = values["phaseId"].strip()
    if not phase_id:
        raise FeatureInputError("Enter a construction phase id.")
    state = _phase_state(ctx)
    selected_ids = {row["id"] for row in selected}
    kept = [item for item in state["assignments"] if item.get("memberId") not in selected_ids]
    assignments = kept + [
        {
            "memberId": row["id"],
            "category": row["category"],
            "story": row["story"],
            "phaseId": phase_id,
            "phaseName": values["phaseName"].strip() or phase_id,
            "startDay": values["startDay"],
            "durationDays": values["durationDays"],
        }
        for row in selected
    ]
    state["assignments"] = assignments
    written = _write_json(ctx, _PHASE_FILE, state)
    return result(
        summary={
            "phaseId": phase_id,
            "phaseName": values["phaseName"].strip() or phase_id,
            "assignedMemberCount": len(selected),
            "startDay": values["startDay"],
            "finishDay": values["startDay"] + values["durationDays"],
        },
        tables=[
            table(
                "Construction phase assignments",
                [
                    ("memberId", "Member"),
                    ("category", "Category"),
                    ("story", "Storey"),
                    ("phaseId", "Phase"),
                    ("startDay", "Start", "day"),
                    ("durationDays", "Duration", "day"),
                ],
                [
                    {
                        "memberId": row["id"],
                        "category": row["category"],
                        "story": row["story"],
                        "phaseId": phase_id,
                        "startDay": values["startDay"],
                        "durationDays": values["durationDays"],
                    }
                    for row in selected
                ],
            )
        ],
        notes=[f"Construction phase assignments saved in {written}."],
    )


@feature(
    "planPlanCoordination.timeLine",
    "Time Line",
    part="floorPlan",
    fields=[],
)
def time_line(ctx: FeatureContext, values: dict) -> dict:
    """Summarize assigned construction phases as ordered start and finish intervals."""
    assignments = _phase_state(ctx)["assignments"]
    if not assignments:
        raise FeatureInputError("Assign structural members to construction phases first.")
    phases: dict[str, dict[str, Any]] = {}
    for item in assignments:
        phase_id = item["phaseId"]
        phase = phases.setdefault(
            phase_id,
            {
                "phaseId": phase_id,
                "phaseName": item.get("phaseName", phase_id),
                "startDay": float(item["startDay"]),
                "finishDay": float(item["startDay"]) + float(item["durationDays"]),
                "memberCount": 0,
            },
        )
        phase["startDay"] = min(phase["startDay"], float(item["startDay"]))
        phase["finishDay"] = max(
            phase["finishDay"], float(item["startDay"]) + float(item["durationDays"])
        )
        phase["memberCount"] += 1
    rows = sorted(phases.values(), key=lambda phase: (phase["startDay"], phase["phaseId"]))
    return result(
        summary={
            "phaseCount": len(rows),
            "scheduledMemberCount": len(assignments),
            "projectDurationDays": max(phase["finishDay"] for phase in rows),
        },
        tables=[
            table(
                "Construction timeline",
                [
                    ("phaseId", "Phase"),
                    ("phaseName", "Name"),
                    ("startDay", "Start", "day"),
                    ("finishDay", "Finish", "day"),
                    ("memberCount", "Members"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planPlanCoordination.phaseFilter",
    "Phase Filter",
    part="floorPlan",
    fields=[
        text("phaseId", "Phase id to show", "P1"),
        checkbox("includeUnassigned", "Include unassigned members", False),
    ],
)
def phase_filter(ctx: FeatureContext, values: dict) -> dict:
    """Return structural members assigned to a selected construction phase for model visibility."""
    plan_rows = member_rows(plan_data(ctx))
    assignments = _phase_state(ctx)["assignments"]
    by_member = {item["memberId"]: item for item in assignments}
    selected = []
    for row in plan_rows:
        assignment = by_member.get(row["id"])
        is_in_phase = assignment is not None and assignment["phaseId"] == values["phaseId"].strip()
        include_unassigned = assignment is None and values["includeUnassigned"]
        if is_in_phase or include_unassigned:
            selected.append(
                {
                    "memberId": row["id"],
                    "category": row["category"],
                    "story": row["story"],
                    "phaseId": assignment["phaseId"] if assignment else "unassigned",
                    "visible": True,
                }
            )
    return result(
        summary={
            "phaseId": values["phaseId"],
            "visibleMemberCount": len(selected),
            "hiddenMemberCount": len(plan_rows) - len(selected),
        },
        tables=[
            table(
                "Members visible for phase",
                [
                    ("memberId", "Member"),
                    ("category", "Category"),
                    ("story", "Storey"),
                    ("phaseId", "Phase"),
                    ("visible", "Visible"),
                ],
                selected,
            )
        ],
    )


@feature(
    "planPlanCoordination.4dSimulation",
    "4D Simulation",
    part="floorPlan",
    fields=[number("simulationDay", "Simulation day", 0, unit="day", min=0)],
)
def simulation_4d(ctx: FeatureContext, values: dict) -> dict:
    """Calculate member completion at a selected day from the saved construction phase schedule."""
    assignments = _phase_state(ctx)["assignments"]
    if not assignments:
        raise FeatureInputError(
            "Assign structural members to construction phases before simulating the schedule."
        )
    day = values["simulationDay"]
    rows = []
    for assignment in assignments:
        start = float(assignment["startDay"])
        finish = start + float(assignment["durationDays"])
        progress = max(0.0, min(1.0, (day - start) / (finish - start)))
        status = "not started" if day < start else "complete" if day >= finish else "in progress"
        rows.append(
            {
                "memberId": assignment["memberId"],
                "category": assignment["category"],
                "story": assignment["story"],
                "phaseId": assignment["phaseId"],
                "startDay": start,
                "finishDay": finish,
                "progressPct": 100 * progress,
                "status": status,
            }
        )
    return result(
        summary={
            "simulationDay": day,
            "scheduledMemberCount": len(rows),
            "startedCount": sum(row["status"] != "not started" for row in rows),
            "completeCount": sum(row["status"] == "complete" for row in rows),
            "averageProgressPct": sum(row["progressPct"] for row in rows) / len(rows),
        },
        tables=[
            table(
                "4D construction state",
                [
                    ("memberId", "Member"),
                    ("category", "Category"),
                    ("story", "Storey"),
                    ("phaseId", "Phase"),
                    ("startDay", "Start", "day"),
                    ("finishDay", "Finish", "day"),
                    ("progressPct", "Complete", "%"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planPlanCoordination.bcfExport",
    "BCF Export",
    part="floorPlan",
    fields=[
        text("issueIds", "Issue ids (comma-separated; blank = all)", ""),
        text("fileName", "BCF file name", "coordination-issues.bcf"),
    ],
)
def bcf_export(ctx: FeatureContext, values: dict) -> dict:
    """Export project coordination issues as a Building Collaboration Format archive."""
    mep = _mep(ctx)
    coordination = _coordination(mep)
    wanted = {part.strip() for part in values["issueIds"].split(",") if part.strip()}
    known = {issue.id for issue in coordination.issues}
    if wanted - known:
        raise FeatureInputError(f"Unknown issue id(s): {', '.join(sorted(wanted - known))}.")
    name = Path(values["fileName"].strip()).name
    if not name.lower().endswith(".bcf"):
        name += ".bcf"
    if name in (".bcf", ""):
        raise FeatureInputError("Enter a BCF output file name.")
    output = _require_root(ctx) / "07 MEP" / "exports" / name
    try:
        from saengine.mep.bcf import export_bcf

        data = export_bcf(coordination, ids=sorted(wanted) if wanted else None)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    except Exception as exc:
        raise FeatureInputError(f"Could not create the BCF archive: {exc}") from exc
    return result(
        summary={
            "outputPath": output.relative_to(ctx.root).as_posix(),
            "issueCount": len(wanted) if wanted else len(coordination.issues),
            "fileBytes": len(data),
        },
        notes=[
            f"BCF 3.0 coordination issues written to {output.relative_to(ctx.root).as_posix()}."
        ],
    )


@feature(
    "planPlanCoordination.issueTracker",
    "Issue Tracker",
    part="floorPlan",
    fields=[
        text("issueId", "Issue id", "C1"),
        select("status", "Issue status", _ISSUE_STATUS_OPTIONS, "active"),
        text("assignedTo", "Assigned to", ""),
        text("dueDate", "Due date (YYYY-MM-DD)", ""),
        text("comment", "Coordination comment", ""),
    ],
)
def issue_tracker(ctx: FeatureContext, values: dict) -> dict:
    """Update a coordination issue's workflow fields and append an optional dated comment."""
    mep = _mep(ctx)
    coordination = _coordination(mep)
    issue = next(
        (item for item in coordination.issues if item.id == values["issueId"].strip()), None
    )
    if issue is None:
        raise FeatureInputError("Issue id was not found in the MEP coordination issue list.")
    due_date = values["dueDate"].strip()
    if due_date:
        try:
            date.fromisoformat(due_date)
        except ValueError as exc:
            raise FeatureInputError("Due date must use YYYY-MM-DD.") from exc
    issue.status = values["status"]
    issue.assignedTo = values["assignedTo"].strip()
    issue.dueDate = due_date
    issue.modified = datetime.now(UTC).isoformat(timespec="seconds")
    comment = values["comment"].strip()
    if comment:
        issue.comments.append(
            IssueComment(
                date=issue.modified, author=coordination.author or "SAEngine", text=comment
            )
        )
    mep.coordination = coordination
    saved = _save_mep(ctx, mep)
    return result(
        summary={
            "issueId": issue.id,
            "status": issue.status,
            "assignedTo": issue.assignedTo,
            "dueDate": issue.dueDate,
            "commentCount": len(issue.comments),
        },
        notes=[f"Issue update saved in {saved}."],
    )


@feature(
    "planPlanCoordination.exportIfc",
    "Export IFC",
    part="floorPlan",
    fields=[
        text(
            "outputPath",
            "Project-relative IFC output path",
            "05 Floor Plan/exports/coordination.ifc",
        )
    ],
)
def export_ifc(ctx: FeatureContext, values: dict) -> dict:
    """Export the current building model and MEP coordination data through SAEngine's IFC writer."""
    root = _require_root(ctx)
    raw_building, raw_objects, raw_materials = (
        ctx.raw("bim"),
        ctx.raw("objects"),
        ctx.raw("materials"),
    )
    if raw_building is None or raw_objects is None or raw_materials is None:
        raise FeatureInputError(
            "The project needs BIM, object-library and material-library data before IFC export."
        )
    from saengine.library.bim import BuildingModel
    from saengine.library.ifc import export_ifc as write_ifc
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    try:
        building = BuildingModel.model_validate(raw_building)
        objects = ObjectLibrary.model_validate(raw_objects)
        materials = MaterialLibrary.model_validate(raw_materials)
        mep = _mep(ctx)
        ifc, element_ids, skipped = write_ifc(building, objects, materials, root.name, mep=mep)
    except Exception as exc:
        raise FeatureInputError(f"The project IFC could not be prepared: {exc}") from exc
    output = _project_file(ctx, values["outputPath"], must_exist=False)
    if output.suffix.lower() != ".ifc":
        raise FeatureInputError("IFC export path must end in .ifc.")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        ifc.write(str(output))
    except Exception as exc:
        raise FeatureInputError(f"Could not write IFC file: {exc}") from exc
    return result(
        summary={
            "outputPath": output.relative_to(root).as_posix(),
            "ifcSchema": str(ifc.schema),
            "buildingElements": len(element_ids),
            "skippedElements": len(skipped),
            "fileBytes": output.stat().st_size,
        },
        tables=[
            table(
                "Elements skipped from IFC",
                [("reason", "Reason")],
                [{"reason": reason} for reason in skipped],
            )
        ],
        notes=[
            f"IFC4 model written to {output.relative_to(root).as_posix()} using the SAEngine building-model exporter."
        ],
    )


@feature(
    "planPlanCoordination.coordinationMatrix",
    "Coordination Matrix",
    part="floorPlan",
    fields=[],
)
def coordination_matrix(ctx: FeatureContext, values: dict) -> dict:
    """Map floor-plan member categories to the nearest structural grid intersection by storey."""
    plan = plan_data(ctx)
    rows = member_rows(plan)
    x_grids = plan["grids"]["x"]
    y_grids = plan["grids"]["y"]
    if not x_grids or not y_grids:
        raise FeatureInputError(
            "Define at least one X and one Y grid line to build the coordination matrix."
        )
    counts: dict[tuple[str, str, str, str], int] = {}
    plan_members = {
        member["id"]: member
        for group in ("columns", "beams", "walls", "slabs", "footings")
        for member in plan.get(group, [])
    }
    for row in rows:
        member = plan_members[row["id"]]
        if row["category"] == "slab":
            points = [point_xy(plan, point) for point in member["boundary"]]
            twice_area = sum(
                points[i][0] * points[(i + 1) % len(points)][1]
                - points[(i + 1) % len(points)][0] * points[i][1]
                for i in range(len(points))
            )
            if abs(twice_area) <= 1e-9:
                raise FeatureInputError(f"Slab '{row['id']}' has a degenerate boundary.")
            x = sum(
                (points[i][0] + points[(i + 1) % len(points)][0])
                * (
                    points[i][0] * points[(i + 1) % len(points)][1]
                    - points[(i + 1) % len(points)][0] * points[i][1]
                )
                for i in range(len(points))
            ) / (3 * twice_area)
            y = sum(
                (points[i][1] + points[(i + 1) % len(points)][1])
                * (
                    points[i][0] * points[(i + 1) % len(points)][1]
                    - points[(i + 1) % len(points)][0] * points[i][1]
                )
                for i in range(len(points))
            ) / (3 * twice_area)
        else:
            x = (float(row.get("x1Mm", 0.0)) + float(row.get("x2Mm", 0.0))) / 2
            y = (float(row.get("y1Mm", 0.0)) + float(row.get("y2Mm", 0.0))) / 2
        gx = min(x_grids, key=lambda line: abs(float(line["position"]) - x))
        gy = min(y_grids, key=lambda line: abs(float(line["position"]) - y))
        key = (str(row["story"]), str(row["category"]), str(gx["label"]), str(gy["label"]))
        counts[key] = counts.get(key, 0) + 1
    matrix = [
        {
            "storey": key[0],
            "structuralSystem": key[1],
            "xGrid": key[2],
            "yGrid": key[3],
            "memberCount": count,
        }
        for key, count in sorted(counts.items())
    ]
    return result(
        summary={
            "storeyCount": len({row["storey"] for row in matrix}),
            "systemCount": len({row["structuralSystem"] for row in matrix}),
            "gridCellCount": len(matrix),
            "memberCount": len(rows),
        },
        tables=[
            table(
                "Structural system by grid",
                [
                    ("storey", "Storey"),
                    ("structuralSystem", "Structural system"),
                    ("xGrid", "Nearest X grid"),
                    ("yGrid", "Nearest Y grid"),
                    ("memberCount", "Members"),
                ],
                matrix,
            )
        ],
        notes=[
            "Each member is assigned to the closest grid intersection to its plan centroid; this is a coordination index, not a member connectivity analysis."
        ],
    )
