"""Drawing Preview ribbon: sheet setup, annotation, revision control and publishing actions."""

from __future__ import annotations

import hashlib
import json
import math
import re
import zipfile
from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path

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
from saengine.features.documents_common import document_state, save_document_state, write_csv
from saengine.features.plan_common import (
    grid_rows,
    member_rows,
    parse_point,
    plan_data,
    point_xy,
    story_map,
)


def _drawing_state(ctx: FeatureContext) -> dict:
    state = document_state(ctx, "drawingPreview")
    state.setdefault("sheets", [])
    state.setdefault("views", [])
    state.setdefault("annotations", [])
    state.setdefault("revisions", [])
    state.setdefault("issues", [])
    state.setdefault("sheetSettings", {})
    state.setdefault("titleBlocks", {})
    return state


def _save_drawing(ctx: FeatureContext, state: dict) -> str:
    return save_document_state(ctx, "drawingPreview", state)


def _sheet(state: dict, number_text: str, *, allow_locked: bool = False) -> dict:
    key = number_text.strip()
    found = next((sheet for sheet in state["sheets"] if sheet.get("number") == key), None)
    if found is None:
        raise FeatureInputError(
            f"Sheet {key!r} is not in the Documents workspace. Create it or choose another sheet."
        )
    if found.get("locked") and not allow_locked:
        raise FeatureInputError(f"Sheet {key!r} is locked after issue and is read-only.")
    return found


def _relative_output(ctx: FeatureContext, path: Path) -> str:
    if ctx.root is None:
        raise FeatureInputError("Open a project before writing a drawing output.")
    return path.relative_to(ctx.root).as_posix()


def _generate_drawings(ctx: FeatureContext, size: str | None = None) -> dict:
    if ctx.root is None:
        raise FeatureInputError("Open a project to generate the drawing set.")
    from saengine.pipeline.drawings import DrawingsError, generate

    try:
        output = generate(ctx.root, size=size, use_design=False)
    except DrawingsError as exc:
        raise FeatureInputError(str(exc)) from exc
    if output.get("problems") and not output.get("sheets"):
        raise FeatureInputError(
            "The drawing set could not be generated: " + "; ".join(output["problems"])
        )
    return output


def _sheet_rows(state: dict) -> list[dict]:
    return sorted(
        state["sheets"], key=lambda item: (item.get("order", 9999), item.get("number", ""))
    )


@feature(
    "documents.sectionMarks",
    "Section Marks",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("mark", "Section mark", "A-A"),
        text("start", "Cut start grid point", "A-1"),
        text("end", "Cut end grid point", "C-1"),
        text("viewSheet", "Reference sheet", "S-201"),
    ],
)
def section_marks(ctx: FeatureContext, values: dict) -> dict:
    """Place a section callout by resolving both cut-line ends against the current floor-plan grids."""
    plan = plan_data(ctx)
    first, last = parse_point(values["start"]), parse_point(values["end"])
    a, b = point_xy(plan, first), point_xy(plan, last)
    if a == b:
        raise FeatureInputError("The section cut needs two distinct grid points.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    annotation = {
        "kind": "section",
        "mark": values["mark"].strip(),
        "sheet": values["sheet"].strip(),
        "referenceSheet": values["viewSheet"].strip(),
        "startMm": a,
        "endMm": b,
    }
    state["annotations"].append(annotation)
    path = _save_drawing(ctx, state)
    return result(
        summary={
            "sectionMark": annotation["mark"],
            "cutLengthM": math.dist(a, b) / 1000,
            "sheet": annotation["sheet"],
        },
        tables=[
            table(
                "Section cut",
                [
                    ("mark", "Mark"),
                    ("startMm", "Start X/Y", "mm"),
                    ("endMm", "End X/Y", "mm"),
                    ("referenceSheet", "Reference"),
                ],
                [annotation],
            )
        ],
        notes=[f"Preview annotation saved to {path}; coordinates came from the floor-plan grids."],
    )


@feature(
    "documents.detailViews",
    "Detail Views",
    part="settings",
    fields=[
        text("sheet", "Host sheet", "S-101"),
        text("detailId", "Detail id", "1"),
        text("title", "Detail title", "Beam support"),
        number("scale", "Detail scale denominator", 20, min=1),
        number("centerXmm", "Detail centre X", 0, unit="mm"),
        number("centerYmm", "Detail centre Y", 0, unit="mm"),
    ],
)
def detail_views(ctx: FeatureContext, values: dict) -> dict:
    """Create a detail-view record with a defined centre and scale for the drawing preview."""
    if not values["title"].strip() or values["scale"] <= 0:
        raise FeatureInputError("Enter a detail title and a positive scale denominator.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    view = {
        "kind": "detail",
        "id": values["detailId"].strip(),
        "title": values["title"].strip(),
        "sheet": values["sheet"].strip(),
        "scale": values["scale"],
        "centerMm": [values["centerXmm"], values["centerYmm"]],
    }
    state["views"].append(view)
    path = _save_drawing(ctx, state)
    return result(
        summary={
            "detailId": view["id"],
            "scaleDenominator": view["scale"],
            "viewCount": len(state["views"]),
        },
        tables=[
            table(
                "Detail views",
                [("id", "Id"), ("title", "Title"), ("sheet", "Host sheet"), ("scale", "1 : scale")],
                [view],
            )
        ],
        notes=[f"Detail viewport saved in {path}."],
    )


@feature(
    "documents.placeView",
    "Place View",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("viewName", "View name", "Level 1 framing"),
        select(
            "viewType",
            "View type",
            [
                ("plan", "Plan"),
                ("elevation", "Elevation"),
                ("section", "Section"),
                ("schedule", "Schedule"),
            ],
            "plan",
        ),
        number("scale", "View scale denominator", 100, min=1),
        number("xMm", "Viewport X on sheet", 100, unit="mm"),
        number("yMm", "Viewport Y on sheet", 100, unit="mm"),
    ],
)
def place_view(ctx: FeatureContext, values: dict) -> dict:
    """Add a named model view to a sheet viewport layout with an explicit type, position and scale."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    if any(
        v.get("name") == values["viewName"].strip() and v.get("sheet") == values["sheet"].strip()
        for v in state["views"]
    ):
        raise FeatureInputError("That view is already placed on this sheet.")
    view = {
        "kind": values["viewType"],
        "name": values["viewName"].strip(),
        "sheet": sheet["number"],
        "scale": values["scale"],
        "positionMm": [values["xMm"], values["yMm"]],
        "source": "floorPlan",
    }
    state["views"].append(view)
    _save_drawing(ctx, state)
    return result(
        summary={
            "viewName": view["name"],
            "sheet": sheet["number"],
            "scaleDenominator": view["scale"],
        },
        tables=[
            table(
                "Sheet viewports",
                [
                    ("name", "View"),
                    ("kind", "Type"),
                    ("scale", "1 : scale"),
                    ("positionMm", "Sheet X/Y", "mm"),
                ],
                [view],
            )
        ],
    )


@feature(
    "documents.revisionSchedule",
    "Revision Schedule",
    part="settings",
    fields=[checkbox("includeSuperseded", "Include superseded revisions", True)],
)
def revision_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Read the actual drawing register and format each issue as a revision schedule."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to inspect its drawing revision register.")
    path = ctx.root / "11 Exports" / "Drawings" / "register.json"
    try:
        register = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FeatureInputError(
            "Generate or issue a drawing set before creating its revision schedule."
        ) from exc
    issues = register.get("issues", []) if isinstance(register, dict) else []
    if not values["includeSuperseded"] and issues:
        issues = issues[-1:]
    rows = [
        {
            "revision": issue.get("code", ""),
            "date": issue.get("date", ""),
            "purpose": issue.get("purpose", ""),
            "sheetCount": len(issue.get("sheets", [])),
        }
        for issue in issues
    ]
    return result(
        summary={"revisionCount": len(rows)},
        tables=[
            table(
                "Drawing revision schedule",
                [
                    ("revision", "Revision"),
                    ("date", "Issue date"),
                    ("purpose", "Purpose"),
                    ("sheetCount", "Sheets"),
                ],
                rows,
            )
        ],
        notes=["Read from the drawing set's issued register."],
    )


@feature(
    "documents.batchPrint",
    "Batch Print",
    part="settings",
    fields=[
        select("paperSize", "Paper size", [("A1", "A1"), ("A2", "A2"), ("A3", "A3")], "A1"),
        text("sheetNumbers", "Sheet numbers (comma-separated; blank means all)", ""),
    ],
)
def batch_print(ctx: FeatureContext, values: dict) -> dict:
    """Generate the SAEngine drawing sheets and combined print PDF, optionally refreshing selected sheets."""
    wanted = [item.strip() for item in values["sheetNumbers"].split(",") if item.strip()]
    output = _generate_drawings(ctx, values["paperSize"])
    available = {
        str(item.get("number", "")) for item in output.get("sheets", []) if isinstance(item, dict)
    }
    missing = set(wanted) - available
    if missing:
        raise FeatureInputError(f"Unknown sheet number(s): {', '.join(sorted(missing))}.")
    return result(
        summary={
            "printedSheetCount": len(wanted) if wanted else len(available),
            "paperSize": values["paperSize"],
            "pdf": output.get("pdf", ""),
        },
        tables=[
            table("Print set", [("number", "Sheet"), ("title", "Title")], output.get("sheets", []))
        ],
        notes=[
            "Generated by saengine.pipeline.drawings; the sheet DXFs and combined PDF share the same source model."
        ],
    )


@feature(
    "documents.printPreview",
    "Print Preview",
    part="settings",
    fields=[select("paperSize", "Preview paper", [("A1", "A1"), ("A2", "A2"), ("A3", "A3")], "A1")],
)
def print_preview(ctx: FeatureContext, values: dict) -> dict:
    """Build the real drawing sheets at the selected paper size and report clipping or build warnings."""
    output = _generate_drawings(ctx, values["paperSize"])
    sheets = output.get("sheets", [])
    return result(
        summary={
            "previewSheetCount": len(sheets),
            "paperSize": values["paperSize"],
            "stale": bool(output.get("stale")),
        },
        tables=[
            table(
                "Print preview sheets",
                [("number", "Sheet"), ("title", "Title"), ("path", "DXF")],
                sheets,
            )
        ],
        notes=list(output.get("notes", [])) + list(output.get("problems", [])),
    )


@feature(
    "documents.archiveDrawings",
    "Archive Drawings",
    part="settings",
    fields=[
        text("archiveName", "Archive name", "drawing-archive.zip"),
        text("note", "Archive note", ""),
    ],
)
def archive_drawings(ctx: FeatureContext, values: dict) -> dict:
    """Freeze the current DXF, PDF and drawing register files into a dated archive with SHA-256 inventory."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to archive drawings.")
    source = ctx.root / "11 Exports" / "Drawings"
    files = [p for p in source.rglob("*") if p.is_file() and "Issued" not in p.parts]
    if not files:
        raise FeatureInputError("Generate a drawing set before archiving it.")
    archive_name = Path(values["archiveName"].strip() or "drawing-archive.zip").name
    if not archive_name.lower().endswith(".zip"):
        archive_name += ".zip"
    target = ctx.root / "11 Exports" / "Archive" / archive_name
    target.parent.mkdir(parents=True, exist_ok=True)
    inventory = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path in sorted(files):
            relative = path.relative_to(source).as_posix()
            data = path.read_bytes()
            package.writestr(relative, data)
            inventory.append(
                {"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            )
        package.writestr(
            "archive-manifest.json",
            json.dumps(
                {
                    "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
                    "note": values["note"],
                    "files": inventory,
                },
                indent=2,
            )
            + "\n",
        )
    return result(
        summary={"archive": _relative_output(ctx, target), "fileCount": len(inventory)},
        tables=[
            table(
                "Archived files",
                [("path", "File"), ("sha256", "SHA-256"), ("bytes", "Bytes")],
                inventory,
            )
        ],
    )


@feature(
    "documents.drawingTransmittal",
    "Drawing Transmittal",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("recipient", "Recipient", ""),
        select(
            "purpose",
            "Purpose",
            [
                ("review", "For review"),
                ("approval", "For approval"),
                ("construction", "For construction"),
                ("information", "For information"),
            ],
            "review",
        ),
        text("author", "Prepared by", ""),
    ],
)
def drawing_transmittal(ctx: FeatureContext, values: dict) -> dict:
    """Create a drawing transmittal from the generated sheet register and capture its file checksums."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to issue a drawing transmittal.")
    drawing_dir = ctx.root / "11 Exports" / "Drawings"
    files = [path for path in drawing_dir.glob("*.dxf") if path.is_file()]
    if not files:
        raise FeatureInputError("Generate the drawing set before making a transmittal.")
    if not values["recipient"].strip():
        raise FeatureInputError("Enter a recipient for the transmittal.")
    state = _drawing_state(ctx)
    issue = {
        "id": values["transmittalId"].strip(),
        "recipient": values["recipient"].strip(),
        "purpose": values["purpose"],
        "preparedBy": values["author"].strip() or "Unknown",
        "issuedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": [
            {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(files)
        ],
    }
    state["issues"] = [item for item in state["issues"] if item.get("id") != issue["id"]] + [issue]
    path = _save_drawing(ctx, state)
    return result(
        summary={
            "transmittalId": issue["id"],
            "fileCount": len(files),
            "recipient": issue["recipient"],
        },
        tables=[
            table("Transmitted drawings", [("name", "File"), ("sha256", "SHA-256")], issue["files"])
        ],
        notes=[f"Issue record saved in {path}."],
    )


@feature(
    "documentsDrawings.sheetSizes",
    "Sheet Sizes",
    part="settings",
    fields=[
        select(
            "size",
            "Sheet size",
            [("A0", "A0"), ("A1", "A1"), ("A2", "A2"), ("A3", "A3"), ("A4", "A4")],
            "A1",
        ),
        select(
            "orientation",
            "Orientation",
            [("landscape", "Landscape"), ("portrait", "Portrait")],
            "landscape",
        ),
    ],
)
def sheet_sizes(ctx: FeatureContext, values: dict) -> dict:
    """Set the drawing-preview paper size and orientation used for subsequent viewport layout."""
    state = _drawing_state(ctx)
    state["sheetSettings"].update(size=values["size"], orientation=values["orientation"])
    path = _save_drawing(ctx, state)
    dimensions = {
        "A0": (841, 1189),
        "A1": (594, 841),
        "A2": (420, 594),
        "A3": (297, 420),
        "A4": (210, 297),
    }[values["size"]]
    width, height = dimensions if values["orientation"] == "landscape" else dimensions[::-1]
    return result(
        summary={
            "size": values["size"],
            "orientation": values["orientation"],
            "widthMm": width,
            "heightMm": height,
        },
        notes=[
            f"Preview settings saved to {path}; generated project sheets continue to use Project Settings until regenerated."
        ],
    )


@feature(
    "documentsDrawings.titleBlock",
    "Title Block",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("projectName", "Project name override", ""),
        text("projectNumber", "Project number", ""),
        text("drawnBy", "Drawn by", ""),
        text("checkedBy", "Checked by", ""),
        text("approvedBy", "Approved by", ""),
    ],
)
def title_block(ctx: FeatureContext, values: dict) -> dict:
    """Bind title-block values to one preview sheet, falling back to project settings for blank fields."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    settings = ctx.raw("settings") or {}
    project = settings.get("project", {})
    drawing = settings.get("drawings", {})
    fields = {
        "projectName": values["projectName"].strip() or project.get("name", ""),
        "projectNumber": values["projectNumber"].strip() or drawing.get("projectNumber", ""),
        "drawnBy": values["drawnBy"].strip() or drawing.get("drawnBy", ""),
        "checkedBy": values["checkedBy"].strip() or drawing.get("checkedBy", ""),
        "approvedBy": values["approvedBy"].strip() or drawing.get("approvedBy", ""),
    }
    state["titleBlocks"][sheet["number"]] = fields
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "boundFieldCount": sum(bool(value) for value in fields.values()),
        },
        tables=[
            table(
                "Resolved title-block fields",
                [("field", "Field"), ("value", "Value")],
                [{"field": key, "value": value} for key, value in fields.items()],
            )
        ],
    )


@feature(
    "documentsDrawings.viewports",
    "Viewports",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("viewName", "Viewport name", "Level 1 framing"),
        number("xMm", "Left X", 20, unit="mm"),
        number("yMm", "Bottom Y", 20, unit="mm"),
        number("widthMm", "Width", 250, unit="mm", min=1),
        number("heightMm", "Height", 170, unit="mm", min=1),
    ],
)
def viewports(ctx: FeatureContext, values: dict) -> dict:
    """Define a paper-space viewport rectangle and reject overlap with another viewport on the same sheet."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    rect = (
        values["xMm"],
        values["yMm"],
        values["xMm"] + values["widthMm"],
        values["yMm"] + values["heightMm"],
    )
    for other in state["views"]:
        if other.get("sheet") != sheet["number"] or "viewportMm" not in other:
            continue
        x0, y0, x1, y1 = other["viewportMm"]
        if rect[0] < x1 and x0 < rect[2] and rect[1] < y1 and y0 < rect[3]:
            raise FeatureInputError(
                f"Viewport overlaps {other.get('name', 'another view')} on this sheet."
            )
    view = next(
        (
            item
            for item in state["views"]
            if item.get("name") == values["viewName"].strip()
            and item.get("sheet") == sheet["number"]
        ),
        None,
    )
    if view is None:
        raise FeatureInputError("Place the named view on this sheet before assigning its viewport.")
    view["viewportMm"] = list(rect)
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "viewportAreaMm2": values["widthMm"] * values["heightMm"],
        },
        tables=[
            table(
                "Viewport rectangle",
                [
                    ("name", "View"),
                    ("x0Mm", "Left", "mm"),
                    ("y0Mm", "Bottom", "mm"),
                    ("x1Mm", "Right", "mm"),
                    ("y1Mm", "Top", "mm"),
                ],
                [
                    {
                        "name": view["name"],
                        "x0Mm": rect[0],
                        "y0Mm": rect[1],
                        "x1Mm": rect[2],
                        "y1Mm": rect[3],
                    }
                ],
            )
        ],
    )


@feature(
    "documentsDrawings.scaleSettings",
    "Scale Settings",
    part="settings",
    fields=[
        text("viewName", "View name", "Level 1 framing"),
        number("modelMm", "Model distance", 1000, unit="mm", min=0.001),
        number("paperMm", "Paper distance", 10, unit="mm", min=0.001),
    ],
)
def scale_settings(ctx: FeatureContext, values: dict) -> dict:
    """Calculate and save a view scale from a measured model-to-paper distance ratio."""
    scale = values["modelMm"] / values["paperMm"]
    state = _drawing_state(ctx)
    view = next(
        (item for item in state["views"] if item.get("name") == values["viewName"].strip()), None
    )
    if view is None:
        raise FeatureInputError("Place the view before setting its scale.")
    view["scale"] = scale
    view["scaleSource"] = {"modelMm": values["modelMm"], "paperMm": values["paperMm"]}
    _save_drawing(ctx, state)
    return result(
        summary={
            "viewName": view["name"],
            "scaleDenominator": scale,
            "displayScale": f"1:{scale:g}",
        },
        notes=[
            "Scale is the measured model distance divided by paper distance; both distances use millimetres."
        ],
    )


@feature(
    "documentsDrawings.northArrow",
    "North Arrow",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        number("bearingDeg", "Project north bearing", 0, unit="deg"),
        checkbox("showTrueNorth", "Show true north", True),
    ],
)
def north_arrow(ctx: FeatureContext, values: dict) -> dict:
    """Place project-north and optional true-north indicators at the configured sheet location."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    annotation = {
        "kind": "northArrow",
        "sheet": sheet["number"],
        "bearingDeg": values["bearingDeg"] % 360,
        "showTrueNorth": values["showTrueNorth"],
        "trueNorthBearingDeg": 0 if values["showTrueNorth"] else None,
    }
    state["annotations"].append(annotation)
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "projectNorthBearingDeg": annotation["bearingDeg"],
            "trueNorthShown": values["showTrueNorth"],
        },
        tables=[
            table(
                "North indicators",
                [("kind", "Indicator"), ("bearingDeg", "Bearing", "deg")],
                [{"kind": "Project north", "bearingDeg": annotation["bearingDeg"]}]
                + ([{"kind": "True north", "bearingDeg": 0}] if values["showTrueNorth"] else []),
            )
        ],
    )


@feature(
    "documentsDrawings.revisionClouds",
    "Revision Clouds",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("revision", "Revision code", "A"),
        number("x0Mm", "Left", 0, unit="mm"),
        number("y0Mm", "Bottom", 0, unit="mm"),
        number("x1Mm", "Right", 100, unit="mm"),
        number("y1Mm", "Top", 100, unit="mm"),
        number("arcMm", "Arc length", 6, unit="mm", min=1),
    ],
)
def revision_clouds(ctx: FeatureContext, values: dict) -> dict:
    """Draw a revision-cloud boundary from a validated rectangle and store it with its revision code."""
    if values["x1Mm"] <= values["x0Mm"] or values["y1Mm"] <= values["y0Mm"]:
        raise FeatureInputError("Cloud right/top coordinates must exceed left/bottom.")
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    cloud = {
        "kind": "revisionCloud",
        "sheet": sheet["number"],
        "revision": values["revision"].strip(),
        "boundsMm": [values["x0Mm"], values["y0Mm"], values["x1Mm"], values["y1Mm"]],
        "arcMm": values["arcMm"],
        "closed": True,
    }
    state["annotations"].append(cloud)
    _save_drawing(ctx, state)
    width, height = values["x1Mm"] - values["x0Mm"], values["y1Mm"] - values["y0Mm"]
    perimeter = 2 * (width + height)
    return result(
        summary={
            "revision": cloud["revision"],
            "perimeterMm": perimeter,
            "approximateArcCount": math.ceil(perimeter / values["arcMm"]),
        },
        notes=[
            "The preview records a closed cloud envelope; sheet DXF revision clouds are generated from model changes by the revision engine."
        ],
    )


@feature(
    "documentsDrawings.issueRevisions",
    "Issue Revisions",
    part="settings",
    fields=[
        text("revision", "Revision code", "A"),
        text("issueDate", "Issue date (YYYY-MM-DD)", "2026-01-01"),
        text("description", "Revision description", "Coordination issue"),
        text("issuedBy", "Issued by", ""),
        text("purpose", "Purpose", "For review"),
        checkbox("forceAllSheets", "Issue unchanged sheets", False),
    ],
)
def issue_revisions(ctx: FeatureContext, values: dict) -> dict:
    """Issue model-derived sheets through the revision engine, which updates clouds and the drawing register."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to issue drawing revisions.")
    try:
        date.fromisoformat(values["issueDate"])
    except ValueError as exc:
        raise FeatureInputError("Enter the issue date as YYYY-MM-DD.") from exc
    from saengine.pipeline.drawings import DrawingsError, issue

    try:
        answer = issue(
            ctx.root,
            code=values["revision"],
            date=values["issueDate"],
            description=values["description"],
            by=values["issuedBy"],
            purpose=values["purpose"],
            force=values["forceAllSheets"],
        )
    except DrawingsError as exc:
        raise FeatureInputError(str(exc)) from exc
    return result(
        summary={
            "revision": values["revision"],
            "issuedSheetCount": len(answer.get("sheets", [])),
            "issueFolder": answer.get("issued", ""),
        },
        tables=[
            table(
                "Issued sheets",
                [("number", "Sheet"), ("title", "Title"), ("revision", "Revision")],
                answer.get("sheets", []),
            )
        ],
        notes=list(answer.get("notes", [])),
    )


@feature(
    "documentsDrawings.revisionTable",
    "Revision Table",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        number("maximumRows", "Maximum rows", 8, min=1, max=30),
    ],
)
def revision_table(ctx: FeatureContext, values: dict) -> dict:
    """Compose a sheet revision table from saved revision entries, newest first and within the row limit."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    rows = [item for item in state["revisions"] if item.get("sheet") in (None, sheet["number"])]
    rows = sorted(rows, key=lambda item: item.get("date", ""), reverse=True)[
        : int(values["maximumRows"])
    ]
    return result(
        summary={"sheet": sheet["number"], "revisionRowCount": len(rows)},
        tables=[
            table(
                "Sheet revision table",
                [
                    ("code", "Revision"),
                    ("date", "Date"),
                    ("description", "Description"),
                    ("by", "By"),
                ],
                rows,
            )
        ],
        notes=["Revision entries are kept separately from generated issue records."],
    )


@feature(
    "documentsDrawings.batchPlot",
    "Batch Plot",
    part="settings",
    fields=[
        select("size", "Plot size", [("A1", "A1"), ("A2", "A2"), ("A3", "A3")], "A1"),
        checkbox("includePdf", "Write combined PDF", True),
    ],
)
def batch_plot(ctx: FeatureContext, values: dict) -> dict:
    """Run the drawing-set plot pipeline and report every generated sheet file and combined PDF."""
    output = _generate_drawings(ctx, values["size"])
    sheets = output.get("sheets", [])
    return result(
        summary={
            "plottedSheets": len(sheets),
            "pdf": output.get("pdf") if values["includePdf"] else None,
            "size": values["size"],
        },
        tables=[
            table(
                "Plot output",
                [("number", "Sheet"), ("title", "Title"), ("path", "DXF path")],
                sheets,
            )
        ],
        notes=list(output.get("problems", [])),
    )


@feature(
    "documentsDrawings.pdfSet",
    "PDF Set",
    part="settings",
    fields=[select("size", "Sheet size", [("A1", "A1"), ("A2", "A2"), ("A3", "A3")], "A1")],
)
def pdf_set(ctx: FeatureContext, values: dict) -> dict:
    """Regenerate the full drawing PDF set with the drawing engine's vector-to-PDF renderer."""
    output = _generate_drawings(ctx, values["size"])
    pdf = output.get("pdf")
    if not pdf:
        raise FeatureInputError("The drawing engine completed without a combined PDF path.")
    return result(
        summary={
            "pdfPath": str(pdf),
            "sheetCount": len(output.get("sheets", [])),
            "size": values["size"],
        },
        notes=list(output.get("notes", [])),
    )


@feature(
    "documentsDrawings.dwgSet",
    "DWG Set",
    part="settings",
    fields=[text("sheetNumbers", "Sheet numbers (comma-separated; blank means all)", "")],
)
def dwg_set(ctx: FeatureContext, values: dict) -> dict:
    """Convert the generated drawing DXFs to DWG with the project's configured LibreDWG converter."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to export DWG sheets.")
    from saengine.pipeline.drawings import export_dwg

    wanted = [item.strip() for item in values["sheetNumbers"].split(",") if item.strip()]
    answer = export_dwg(ctx.root, wanted or None)
    if answer.get("problems"):
        raise FeatureInputError(" ".join(answer["problems"]))
    return result(
        summary={
            "writtenCount": len(answer.get("written", [])),
            "folder": answer.get("folder", ""),
        },
        tables=[
            table(
                "DWG files",
                [("path", "File")],
                [{"path": item} for item in answer.get("written", [])],
            )
        ],
        notes=["DWG conversion uses the configured external LibreDWG tool."],
    )


@feature(
    "documentsDrawings.viewTitles",
    "View Titles",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("viewName", "View name", "Level 1 framing"),
        text("title", "Displayed title", "Framing plan"),
        text("detail", "View reference", "1 : 100"),
    ],
)
def view_titles(ctx: FeatureContext, values: dict) -> dict:
    """Add or revise the printed title and reference under one view already placed on a sheet."""
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    view = next(
        (
            item
            for item in state["views"]
            if item.get("sheet") == values["sheet"].strip()
            and item.get("name") == values["viewName"].strip()
        ),
        None,
    )
    if view is None:
        raise FeatureInputError("Place the view on the selected sheet before editing its title.")
    view["displayTitle"], view["titleReference"] = values["title"].strip(), values["detail"].strip()
    _save_drawing(ctx, state)
    return result(
        summary={
            "view": view["name"],
            "displayTitle": view["displayTitle"],
            "reference": view["titleReference"],
        }
    )


@feature(
    "documentsDrawings.calloutTags",
    "Callout Tags",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("callout", "Callout label", "1/A-301"),
        text("viewName", "Referenced view", "Beam support detail"),
        text("reference", "Grid reference", "A-1"),
    ],
)
def callout_tags(ctx: FeatureContext, values: dict) -> dict:
    """Place a detail/section callout tag after checking its grid reference against the floor plan."""
    plan = plan_data(ctx)
    point = parse_point(values["reference"])
    xy = point_xy(plan, point)
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    callout = {
        "kind": "callout",
        "sheet": values["sheet"].strip(),
        "label": values["callout"].strip(),
        "view": values["viewName"].strip(),
        "positionMm": list(xy),
    }
    state["annotations"].append(callout)
    _save_drawing(ctx, state)
    return result(
        summary={
            "callout": callout["label"],
            "referencedView": callout["view"],
            "positionXMm": xy[0],
            "positionYMm": xy[1],
        }
    )


@feature(
    "documentsDrawings.detailTags",
    "Detail Tags",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("memberId", "Component member id", "B1"),
        text("detail", "Detail reference", "2/S-402"),
    ],
)
def detail_tags(ctx: FeatureContext, values: dict) -> dict:
    """Attach a detail reference to an existing floor-plan member so the component can be traced from its mark."""
    plan = plan_data(ctx)
    member = next(
        (
            item
            for group in ("columns", "beams", "walls", "slabs", "footings")
            for item in plan.get(group, [])
            if item["id"] == values["memberId"].strip()
        ),
        None,
    )
    if member is None:
        raise FeatureInputError("The component id is not in the current floor plan.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    tag_row = {
        "kind": "detailTag",
        "sheet": values["sheet"].strip(),
        "memberId": member["id"],
        "mark": member.get("mark", member["id"]),
        "detail": values["detail"].strip(),
    }
    state["annotations"].append(tag_row)
    _save_drawing(ctx, state)
    return result(
        summary={"memberId": member["id"], "detailReference": tag_row["detail"]},
        tables=[
            table(
                "Component detail tag",
                [("memberId", "Member"), ("mark", "Mark"), ("detail", "Detail")],
                [tag_row],
            )
        ],
    )


@feature(
    "documentsDrawings.breakLines",
    "Break Lines",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("viewName", "View name", "Level 1 framing"),
        number("x0Mm", "Start X", 0, unit="mm"),
        number("y0Mm", "Start Y", 0, unit="mm"),
        number("x1Mm", "End X", 1000, unit="mm"),
        number("y1Mm", "End Y", 0, unit="mm"),
        number("gapMm", "Break gap", 20, unit="mm", min=1),
    ],
)
def break_lines(ctx: FeatureContext, values: dict) -> dict:
    """Insert a drafting break symbol along a view line and compute the omitted length and axis."""
    length = math.hypot(values["x1Mm"] - values["x0Mm"], values["y1Mm"] - values["y0Mm"])
    if length <= values["gapMm"]:
        raise FeatureInputError("The break gap must be shorter than the reference line.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    annotation = {
        "kind": "breakLine",
        "sheet": values["sheet"].strip(),
        "view": values["viewName"].strip(),
        "startMm": [values["x0Mm"], values["y0Mm"]],
        "endMm": [values["x1Mm"], values["y1Mm"]],
        "gapMm": values["gapMm"],
    }
    state["annotations"].append(annotation)
    _save_drawing(ctx, state)
    return result(
        summary={
            "referenceLengthMm": length,
            "omittedGapMm": values["gapMm"],
            "lineAngleDeg": math.degrees(
                math.atan2(values["y1Mm"] - values["y0Mm"], values["x1Mm"] - values["x0Mm"])
            ),
        }
    )


@feature(
    "documentsDrawings.alignedDimension",
    "Aligned Dimension",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("start", "First grid point", "A-1"),
        text("end", "Second grid point", "B-2"),
        text("label", "Dimension label", ""),
    ],
)
def aligned_dimension(ctx: FeatureContext, values: dict) -> dict:
    """Resolve two plan grid references and calculate their true aligned distance for annotation."""
    plan = plan_data(ctx)
    a, b = point_xy(plan, parse_point(values["start"])), point_xy(plan, parse_point(values["end"]))
    distance = math.dist(a, b)
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    dimension = {
        "kind": "alignedDimension",
        "sheet": values["sheet"].strip(),
        "startMm": list(a),
        "endMm": list(b),
        "distanceMm": distance,
        "label": values["label"].strip() or f"{distance:.0f}",
    }
    state["annotations"].append(dimension)
    _save_drawing(ctx, state)
    return result(
        summary={"distanceMm": distance, "distanceM": distance / 1000, "label": dimension["label"]},
        tables=[
            table(
                "Aligned dimension",
                [
                    ("startMm", "Start X/Y", "mm"),
                    ("endMm", "End X/Y", "mm"),
                    ("distanceMm", "Length", "mm"),
                ],
                [dimension],
            )
        ],
    )


@feature(
    "documentsDrawings.ordinateDimension",
    "Ordinate Dimension",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("origin", "Dimension origin grid point", "A-1"),
        text("target", "Target grid point", "C-2"),
        select("axis", "Ordinate axis", [("x", "X"), ("y", "Y")], "x"),
    ],
)
def ordinate_dimension(ctx: FeatureContext, values: dict) -> dict:
    """Measure one signed coordinate from a selected floor-plan origin and save an ordinate dimension."""
    plan = plan_data(ctx)
    origin, target = (
        point_xy(plan, parse_point(values["origin"])),
        point_xy(plan, parse_point(values["target"])),
    )
    axis = 0 if values["axis"] == "x" else 1
    offset = target[axis] - origin[axis]
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    record = {
        "kind": "ordinateDimension",
        "sheet": values["sheet"].strip(),
        "axis": values["axis"],
        "originMm": list(origin),
        "targetMm": list(target),
        "ordinateMm": offset,
    }
    state["annotations"].append(record)
    _save_drawing(ctx, state)
    return result(
        summary={"axis": values["axis"].upper(), "ordinateMm": offset, "ordinateM": offset / 1000}
    )


@feature(
    "documentsDrawings.detailLines",
    "Detail Lines",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("viewName", "View name", "Level 1 framing"),
        number("x0Mm", "Start X", 0, unit="mm"),
        number("y0Mm", "Start Y", 0, unit="mm"),
        number("x1Mm", "End X", 1000, unit="mm"),
        number("y1Mm", "End Y", 0, unit="mm"),
        text("lineStyle", "Line style", "Thin"),
    ],
)
def detail_lines(ctx: FeatureContext, values: dict) -> dict:
    """Add a 2D detail line, reporting its true length and direction for the selected drawing view."""
    dx, dy = values["x1Mm"] - values["x0Mm"], values["y1Mm"] - values["y0Mm"]
    if math.hypot(dx, dy) == 0:
        raise FeatureInputError("A detail line needs two different endpoints.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    line = {
        "kind": "detailLine",
        "sheet": values["sheet"].strip(),
        "view": values["viewName"].strip(),
        "startMm": [values["x0Mm"], values["y0Mm"]],
        "endMm": [values["x1Mm"], values["y1Mm"]],
        "style": values["lineStyle"],
        "lengthMm": math.hypot(dx, dy),
    }
    state["annotations"].append(line)
    _save_drawing(ctx, state)
    return result(
        summary={
            "lengthMm": line["lengthMm"],
            "angleDeg": math.degrees(math.atan2(dy, dx)),
            "lineStyle": line["style"],
        }
    )


@feature(
    "documentsDrawings.symbolicLines",
    "Symbolic Lines",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("symbol", "Symbol code", "CENTERLINE"),
        number("x0Mm", "Start X", 0, unit="mm"),
        number("y0Mm", "Start Y", 0, unit="mm"),
        number("x1Mm", "End X", 1000, unit="mm"),
        number("y1Mm", "End Y", 0, unit="mm"),
    ],
)
def symbolic_lines(ctx: FeatureContext, values: dict) -> dict:
    """Save view-specific symbolic linework with a checked line length and named drafting symbol."""
    if math.dist((values["x0Mm"], values["y0Mm"]), (values["x1Mm"], values["y1Mm"])) <= 0:
        raise FeatureInputError("Symbolic line endpoints must differ.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    line = {
        "kind": "symbolicLine",
        "sheet": values["sheet"].strip(),
        "symbol": values["symbol"].strip(),
        "startMm": [values["x0Mm"], values["y0Mm"]],
        "endMm": [values["x1Mm"], values["y1Mm"]],
    }
    state["annotations"].append(line)
    _save_drawing(ctx, state)
    return result(
        summary={"symbol": line["symbol"], "lengthMm": math.dist(line["startMm"], line["endMm"])}
    )


@feature(
    "documentsDrawings.hatchPatterns",
    "Hatch Patterns",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("region", "Region id", "R1"),
        select(
            "pattern",
            "Pattern",
            [
                ("solid", "Solid"),
                ("diagonal", "Diagonal"),
                ("cross", "Crosshatch"),
                ("dots", "Dots"),
            ],
            "diagonal",
        ),
        number("spacingMm", "Pattern spacing", 5, unit="mm", min=0.1),
        number("areaM2", "Closed region area", 1, unit="m²", min=0.001),
    ],
)
def hatch_patterns(ctx: FeatureContext, values: dict) -> dict:
    """Assign a pattern and spacing to a measured closed drafting region, with density scaled by its area."""
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    hatch = {
        "kind": "hatch",
        "sheet": values["sheet"].strip(),
        "region": values["region"].strip(),
        "pattern": values["pattern"],
        "spacingMm": values["spacingMm"],
        "areaM2": values["areaM2"],
    }
    state["annotations"].append(hatch)
    _save_drawing(ctx, state)
    return result(
        summary={
            "pattern": hatch["pattern"],
            "areaM2": hatch["areaM2"],
            "approximatePatternLines": math.ceil(
                math.sqrt(values["areaM2"] * 1_000_000) / values["spacingMm"]
            ),
        }
    )


@feature(
    "documentsDrawings.lineStyles",
    "Line Styles",
    part="settings",
    fields=[
        text("styleName", "Style name", "Review"),
        select(
            "pattern",
            "Dash pattern",
            [
                ("continuous", "Continuous"),
                ("dashed", "Dashed"),
                ("center", "Center"),
                ("hidden", "Hidden"),
            ],
            "continuous",
        ),
        number("lineweightMm", "Line weight", 0.25, unit="mm", min=0.05, max=2),
        text("colour", "ACI colour name", "white"),
    ],
)
def line_styles(ctx: FeatureContext, values: dict) -> dict:
    """Define a named line style and reject lineweights outside printable drafting limits."""
    if not values["styleName"].strip():
        raise FeatureInputError("Give the line style a name.")
    state = _drawing_state(ctx)
    styles = state.setdefault("lineStyles", {})
    styles[values["styleName"].strip()] = {
        "pattern": values["pattern"],
        "lineweightMm": values["lineweightMm"],
        "colour": values["colour"].strip(),
    }
    _save_drawing(ctx, state)
    return result(
        summary={
            "styleName": values["styleName"].strip(),
            "pattern": values["pattern"],
            "lineweightMm": values["lineweightMm"],
            "styleCount": len(styles),
        }
    )


@feature(
    "documentsDrawings.cropRegions",
    "Crop Regions",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("viewName", "View name", "Level 1 framing"),
        number("x0Mm", "Left", 0, unit="mm"),
        number("y0Mm", "Bottom", 0, unit="mm"),
        number("x1Mm", "Right", 10000, unit="mm"),
        number("y1Mm", "Top", 8000, unit="mm"),
        checkbox("visible", "Show crop boundary", False),
    ],
)
def crop_regions(ctx: FeatureContext, values: dict) -> dict:
    """Set a rectangular crop extent on an existing view and report the retained plan area."""
    if values["x1Mm"] <= values["x0Mm"] or values["y1Mm"] <= values["y0Mm"]:
        raise FeatureInputError("Crop right/top coordinates must exceed left/bottom.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    view = next(
        (
            item
            for item in state["views"]
            if item.get("sheet") == values["sheet"].strip()
            and item.get("name") == values["viewName"].strip()
        ),
        None,
    )
    if view is None:
        raise FeatureInputError("Place the view before defining its crop region.")
    view["cropMm"] = [values["x0Mm"], values["y0Mm"], values["x1Mm"], values["y1Mm"]]
    view["cropVisible"] = values["visible"]
    _save_drawing(ctx, state)
    return result(
        summary={
            "cropAreaM2": (values["x1Mm"] - values["x0Mm"])
            * (values["y1Mm"] - values["y0Mm"])
            / 1_000_000,
            "boundaryVisible": values["visible"],
        }
    )


@feature(
    "documentsDrawings.viewFilters",
    "View Filters",
    part="settings",
    fields=[
        text("viewName", "View name", "Level 1 framing"),
        select(
            "property",
            "Member property",
            [("type", "Object type"), ("category", "Category"), ("story", "Story")],
            "category",
        ),
        text("equals", "Value equals", "beam"),
        select(
            "display",
            "Display action",
            [("highlight", "Highlight"), ("hide", "Hide"), ("halftone", "Halftone")],
            "highlight",
        ),
    ],
)
def view_filters(ctx: FeatureContext, values: dict) -> dict:
    """Apply a property filter to floor-plan members and return the actual members affected in the view."""
    rows = member_rows(plan_data(ctx))
    matched = [
        row
        for row in rows
        if str(row.get(values["property"], "")).lower() == values["equals"].strip().lower()
    ]
    state = _drawing_state(ctx)
    rule = {
        "viewName": values["viewName"].strip(),
        "property": values["property"],
        "equals": values["equals"],
        "display": values["display"],
        "memberIds": [row["id"] for row in matched],
    }
    state.setdefault("viewFilters", []).append(rule)
    _save_drawing(ctx, state)
    return result(
        summary={"matchedMemberCount": len(matched), "displayAction": values["display"]},
        tables=[
            table(
                "Filtered view members",
                [("id", "Member"), ("category", "Category"), ("type", "Type"), ("story", "Story")],
                matched,
            )
        ],
        notes=[
            "The filter result is computed from current floor-plan data and saved to the preview workspace."
        ],
    )


@feature(
    "documentsDrawings.dependentViews",
    "Dependent Views",
    part="settings",
    fields=[
        text("parentView", "Parent view", "Level 1 framing"),
        text("childName", "Dependent view name", "Level 1 east"),
        number("x0Mm", "Crop left", 0, unit="mm"),
        number("y0Mm", "Crop bottom", 0, unit="mm"),
        number("x1Mm", "Crop right", 5000, unit="mm"),
        number("y1Mm", "Crop top", 5000, unit="mm"),
    ],
)
def dependent_views(ctx: FeatureContext, values: dict) -> dict:
    """Create a dependent crop from a placed parent view while inheriting its sheet and scale."""
    state = _drawing_state(ctx)
    parent = next(
        (item for item in state["views"] if item.get("name") == values["parentView"].strip()), None
    )
    if parent is None:
        raise FeatureInputError("Place the parent view before creating a dependent view.")
    if values["x1Mm"] <= values["x0Mm"] or values["y1Mm"] <= values["y0Mm"]:
        raise FeatureInputError("Dependent-view crop coordinates are not ordered.")
    child = {
        "kind": parent.get("kind", "plan"),
        "name": values["childName"].strip(),
        "sheet": parent["sheet"],
        "scale": parent.get("scale", 100),
        "parent": parent["name"],
        "cropMm": [values["x0Mm"], values["y0Mm"], values["x1Mm"], values["y1Mm"]],
    }
    state["views"].append(child)
    _save_drawing(ctx, state)
    return result(
        summary={
            "parent": child["parent"],
            "dependentView": child["name"],
            "sheet": child["sheet"],
            "scaleDenominator": child["scale"],
        }
    )


@feature(
    "documentsSheets.newSheet",
    "New Sheet",
    part="settings",
    fields=[
        text("number", "Sheet number", "S-101"),
        text("title", "Sheet title", "General arrangement"),
        select("size", "Sheet size", [("A1", "A1"), ("A2", "A2"), ("A3", "A3")], "A1"),
        select(
            "discipline",
            "Discipline",
            [("S", "Structural"), ("A", "Architectural"), ("M", "Mechanical"), ("E", "Electrical")],
            "S",
        ),
    ],
)
def new_sheet(ctx: FeatureContext, values: dict) -> dict:
    """Create a typed drawing-sheet record with unique number, discipline, size and a ready status."""
    state = _drawing_state(ctx)
    number_text = values["number"].strip()
    if not number_text or any(item.get("number") == number_text for item in state["sheets"]):
        raise FeatureInputError("Enter a sheet number that is not already in the set.")
    row = {
        "number": number_text,
        "title": values["title"].strip(),
        "size": values["size"],
        "discipline": values["discipline"],
        "status": "Draft",
        "order": len(state["sheets"]),
        "locked": False,
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    state["sheets"].append(row)
    path = _save_drawing(ctx, state)
    return result(
        summary={"sheet": row["number"], "title": row["title"], "sheetCount": len(state["sheets"])},
        tables=[
            table(
                "Sheet record",
                [
                    ("number", "Number"),
                    ("title", "Title"),
                    ("discipline", "Discipline"),
                    ("size", "Size"),
                    ("status", "Status"),
                ],
                [row],
            )
        ],
        notes=[f"Saved to {path}; plot generation uses the model-driven sheet set."],
    )


@feature(
    "documentsSheets.duplicateSheet",
    "Duplicate Sheet",
    part="settings",
    fields=[
        text("sourceSheet", "Source sheet", "S-101"),
        text("newNumber", "New sheet number", "S-102"),
        checkbox("copyViews", "Copy placed views", True),
        checkbox("copyAnnotations", "Copy annotations", True),
    ],
)
def duplicate_sheet(ctx: FeatureContext, values: dict) -> dict:
    """Duplicate a sheet's setup while selectively copying its views and annotations under a new unique number."""
    state = _drawing_state(ctx)
    source = _sheet(state, values["sourceSheet"])
    if any(item.get("number") == values["newNumber"].strip() for item in state["sheets"]):
        raise FeatureInputError("The new sheet number is already in use.")
    created = {
        **source,
        "number": values["newNumber"].strip(),
        "status": "Draft",
        "locked": False,
        "order": len(state["sheets"]),
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "duplicatedFrom": source["number"],
    }
    state["sheets"].append(created)
    if values["copyViews"]:
        state["views"].extend(
            {**item, "sheet": created["number"]}
            for item in state["views"]
            if item.get("sheet") == source["number"]
        )
    if values["copyAnnotations"]:
        state["annotations"].extend(
            {**item, "sheet": created["number"]}
            for item in state["annotations"]
            if item.get("sheet") == source["number"]
        )
    _save_drawing(ctx, state)
    return result(
        summary={
            "source": source["number"],
            "duplicate": created["number"],
            "viewCount": sum(v.get("sheet") == created["number"] for v in state["views"]),
            "annotationCount": sum(
                a.get("sheet") == created["number"] for a in state["annotations"]
            ),
        }
    )


@feature(
    "documentsSheets.sheetList",
    "Sheet List",
    part="settings",
    fields=[
        select(
            "status",
            "Status filter",
            [
                ("all", "All"),
                ("Draft", "Draft"),
                ("Issued", "Issued"),
                ("Placeholder", "Placeholder"),
            ],
            "all",
        )
    ],
)
def sheet_list(ctx: FeatureContext, values: dict) -> dict:
    """List the saved sheet register with view, annotation, revision and status counts."""
    state = _drawing_state(ctx)
    rows = []
    for sheet in _sheet_rows(state):
        if values["status"] != "all" and sheet.get("status") != values["status"]:
            continue
        rows.append(
            {
                **sheet,
                "viewCount": sum(view.get("sheet") == sheet["number"] for view in state["views"]),
                "annotationCount": sum(
                    mark.get("sheet") == sheet["number"] for mark in state["annotations"]
                ),
                "revisionCount": sum(
                    rev.get("sheet") in (None, sheet["number"]) for rev in state["revisions"]
                ),
            }
        )
    return result(
        summary={"sheetCount": len(rows)},
        tables=[
            table(
                "Drawing sheet register",
                [
                    ("number", "Number"),
                    ("title", "Title"),
                    ("discipline", "Discipline"),
                    ("size", "Size"),
                    ("status", "Status"),
                    ("viewCount", "Views"),
                    ("annotationCount", "Annotations"),
                    ("revisionCount", "Revisions"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsSheets.batchSheets",
    "Batch Sheets",
    part="settings",
    fields=[
        text("numbers", "Sheet numbers (comma-separated)", "S-201,S-202"),
        text("titlePrefix", "Title prefix", "Detail"),
        select("size", "Sheet size", [("A1", "A1"), ("A2", "A2"), ("A3", "A3")], "A1"),
        select(
            "discipline",
            "Discipline",
            [("S", "Structural"), ("A", "Architectural"), ("M", "Mechanical"), ("E", "Electrical")],
            "S",
        ),
    ],
)
def batch_sheets(ctx: FeatureContext, values: dict) -> dict:
    """Create a batch of unique sheet-register entries from explicit sheet numbers and a common template."""
    numbers = [item.strip() for item in values["numbers"].split(",") if item.strip()]
    if not numbers or len(numbers) != len(set(numbers)):
        raise FeatureInputError("Enter a non-empty list of distinct sheet numbers.")
    state = _drawing_state(ctx)
    existing = {sheet["number"] for sheet in state["sheets"]}
    collisions = existing & set(numbers)
    if collisions:
        raise FeatureInputError(f"Sheet number(s) already exist: {', '.join(sorted(collisions))}.")
    made = []
    for number_text in numbers:
        row = {
            "number": number_text,
            "title": f"{values['titlePrefix'].strip()} {number_text}",
            "size": values["size"],
            "discipline": values["discipline"],
            "status": "Draft",
            "order": len(state["sheets"]),
            "locked": False,
        }
        state["sheets"].append(row)
        made.append(row)
    _save_drawing(ctx, state)
    return result(
        summary={"createdSheetCount": len(made), "sheetNumbers": numbers},
        tables=[
            table(
                "Created sheets",
                [
                    ("number", "Number"),
                    ("title", "Title"),
                    ("size", "Size"),
                    ("discipline", "Discipline"),
                ],
                made,
            )
        ],
    )


@feature(
    "documentsSheets.sheetGuide",
    "Sheet Guide",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        checkbox("visible", "Show alignment guides", True),
        number("spacingMm", "Guide spacing", 10, unit="mm", min=1),
    ],
)
def sheet_guide(ctx: FeatureContext, values: dict) -> dict:
    """Set a sheet-specific alignment guide visibility and spacing for viewport placement."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    sheet["guide"] = {"visible": values["visible"], "spacingMm": values["spacingMm"]}
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "guidesVisible": values["visible"],
            "guideSpacingMm": values["spacingMm"],
        }
    )


@feature(
    "documentsSheets.sheetNumbers",
    "Sheet Numbers",
    part="settings",
    fields=[
        text("prefix", "Number prefix", "S-"),
        number("start", "First sequence number", 101, min=1),
        number("step", "Increment", 1, min=1),
        checkbox("renumberAll", "Renumber every sheet in order", False),
    ],
)
def sheet_numbers(ctx: FeatureContext, values: dict) -> dict:
    """Assign sequential sheet numbers by register order and update view, annotation and title-block references atomically."""
    state = _drawing_state(ctx)
    sheets = _sheet_rows(state)
    if not sheets:
        raise FeatureInputError("Create at least one sheet before renumbering the register.")
    targets = (
        sheets
        if values["renumberAll"]
        else [item for item in sheets if not re.search(r"\d+$", item["number"])]
    )
    if not targets:
        targets = sheets[-1:]
    mapping = {
        sheet["number"]: f"{values['prefix']}{int(values['start']) + i * int(values['step']):03d}"
        for i, sheet in enumerate(targets)
    }
    if len(set(mapping.values())) != len(mapping):
        raise FeatureInputError("The numbering pattern creates duplicate sheet numbers.")
    for sheet in targets:
        sheet["number"] = mapping[sheet["number"]]
    for collection in (state["views"], state["annotations"], state["revisions"], state["issues"]):
        for item in collection:
            if item.get("sheet") in mapping:
                item["sheet"] = mapping[item["sheet"]]
    state["titleBlocks"] = {
        mapping.get(key, key): value for key, value in state["titleBlocks"].items()
    }
    _save_drawing(ctx, state)
    return result(
        summary={"renumberedCount": len(mapping)},
        tables=[
            table(
                "Sheet number mapping",
                [("oldNumber", "Previous"), ("newNumber", "New")],
                [{"oldNumber": old, "newNumber": new} for old, new in mapping.items()],
            )
        ],
    )


@feature(
    "documentsSheets.reorderSheets",
    "Reorder Sheets",
    part="settings",
    fields=[text("numbers", "Sheet numbers in published order", "S-101,S-102,S-103")],
)
def reorder_sheets(ctx: FeatureContext, values: dict) -> dict:
    """Set published sheet order from an explicit sequence, appending any omitted sheets in their prior order."""
    state = _drawing_state(ctx)
    requested = [item.strip() for item in values["numbers"].split(",") if item.strip()]
    sheets = _sheet_rows(state)
    known = {item["number"] for item in sheets}
    unknown = set(requested) - known
    if unknown:
        raise FeatureInputError(f"Unknown sheet number(s): {', '.join(sorted(unknown))}.")
    if len(requested) != len(set(requested)):
        raise FeatureInputError("Each sheet may appear only once in the ordering.")
    ordered = requested + [item["number"] for item in sheets if item["number"] not in requested]
    by_number = {item["number"]: item for item in sheets}
    for index, number_text in enumerate(ordered):
        by_number[number_text]["order"] = index
    _save_drawing(ctx, state)
    return result(
        summary={"orderedSheetCount": len(ordered)},
        tables=[
            table(
                "Published sheet order",
                [("order", "Order"), ("number", "Sheet"), ("title", "Title")],
                [{"order": i + 1, **by_number[n]} for i, n in enumerate(ordered)],
            )
        ],
    )


@feature(
    "documentsSheets.placeholders",
    "Placeholders",
    part="settings",
    fields=[
        text("numbers", "Placeholder sheet numbers", "S-901,S-902"),
        text("discipline", "Discipline", "S"),
        text("purpose", "Planned drawing purpose", "Future detail sheets"),
    ],
)
def placeholders(ctx: FeatureContext, values: dict) -> dict:
    """Create numbered placeholder sheets with a planned purpose and a status that prevents accidental issue."""
    numbers = [item.strip() for item in values["numbers"].split(",") if item.strip()]
    state = _drawing_state(ctx)
    known = {item["number"] for item in state["sheets"]}
    if not numbers or len(numbers) != len(set(numbers)) or known.intersection(numbers):
        raise FeatureInputError(
            "Enter distinct placeholder numbers that are not already in the register."
        )
    made = []
    for number_text in numbers:
        row = {
            "number": number_text,
            "title": values["purpose"].strip(),
            "discipline": values["discipline"].strip(),
            "status": "Placeholder",
            "order": len(state["sheets"]),
            "locked": False,
            "placeholder": True,
        }
        state["sheets"].append(row)
        made.append(row)
    _save_drawing(ctx, state)
    return result(
        summary={"placeholderCount": len(made)},
        tables=[
            table(
                "Placeholder sheets",
                [
                    ("number", "Number"),
                    ("title", "Planned purpose"),
                    ("discipline", "Discipline"),
                    ("status", "Status"),
                ],
                made,
            )
        ],
    )


@feature(
    "documentsSheets.issueSheet",
    "Issue Sheet",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("issueDate", "Issue date (YYYY-MM-DD)", "2026-01-01"),
        select(
            "purpose",
            "Issue purpose",
            [
                ("review", "For review"),
                ("approval", "For approval"),
                ("construction", "For construction"),
                ("record", "As-recorded"),
            ],
            "review",
        ),
        text("issuedBy", "Issued by", ""),
    ],
)
def issue_sheet(ctx: FeatureContext, values: dict) -> dict:
    """Issue one sheet as a read-only record with date, purpose and issuing engineer."""
    try:
        date.fromisoformat(values["issueDate"])
    except ValueError as exc:
        raise FeatureInputError("Enter the issue date as YYYY-MM-DD.") from exc
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    if sheet.get("status") == "Placeholder":
        raise FeatureInputError(
            "A placeholder sheet cannot be issued until it has a drawing title and views."
        )
    record = {
        "sheet": sheet["number"],
        "revision": sheet.get("revision", "A"),
        "date": values["issueDate"],
        "purpose": values["purpose"],
        "issuedBy": values["issuedBy"].strip() or "Unknown",
        "lockedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    sheet.update(status="Issued", locked=True, issue=record)
    state["revisions"].append(
        {
            "sheet": sheet["number"],
            "code": record["revision"],
            "date": record["date"],
            "description": record["purpose"],
            "by": record["issuedBy"],
        }
    )
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "status": "Issued",
            "readOnly": True,
            "revision": record["revision"],
        },
        tables=[
            table(
                "Sheet issue record",
                [
                    ("sheet", "Sheet"),
                    ("revision", "Revision"),
                    ("date", "Issue date"),
                    ("purpose", "Purpose"),
                    ("issuedBy", "Issued by"),
                ],
                [record],
            )
        ],
        notes=["The sheet is locked in the Documents register after issue."],
    )


@feature(
    "documentsSheets.transmittal",
    "Transmittal",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("sheetNumbers", "Sheet numbers (comma-separated)", "S-101"),
        text("recipient", "Recipient", ""),
        text("dueDate", "Response due date (YYYY-MM-DD)", ""),
        select(
            "purpose",
            "Purpose",
            [
                ("review", "For review"),
                ("approval", "For approval"),
                ("construction", "For construction"),
                ("information", "For information"),
            ],
            "review",
        ),
    ],
)
def transmittal(ctx: FeatureContext, values: dict) -> dict:
    """Create a per-transmittal issue record with selected issued sheets and response due date."""
    if values["dueDate"].strip():
        try:
            date.fromisoformat(values["dueDate"])
        except ValueError as exc:
            raise FeatureInputError("Enter the due date as YYYY-MM-DD.") from exc
    state = _drawing_state(ctx)
    numbers = [part.strip() for part in values["sheetNumbers"].split(",") if part.strip()]
    sheets = []
    for number_text in numbers:
        sheet = _sheet(state, number_text, allow_locked=True)
        if sheet.get("status") != "Issued":
            raise FeatureInputError(
                f"Sheet {number_text} must be issued before it can enter a transmittal."
            )
        sheets.append(number_text)
    if not values["recipient"].strip() or not sheets:
        raise FeatureInputError("Choose at least one issued sheet and enter a recipient.")
    record = {
        "id": values["transmittalId"].strip(),
        "recipient": values["recipient"].strip(),
        "dueDate": values["dueDate"].strip() or None,
        "purpose": values["purpose"],
        "sheets": sheets,
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "Sent",
    }
    if any(item.get("id") == record["id"] for item in state["issues"]):
        raise FeatureInputError("That transmittal id is already in use.")
    state["issues"].append(record)
    _save_drawing(ctx, state)
    overdue = bool(record["dueDate"] and date.fromisoformat(record["dueDate"]) < date.today())
    return result(
        summary={"transmittalId": record["id"], "sheetCount": len(sheets), "overdue": overdue},
        tables=[
            table(
                "Transmittal",
                [
                    ("id", "Id"),
                    ("recipient", "Recipient"),
                    ("purpose", "Purpose"),
                    ("dueDate", "Due date"),
                    ("sheets", "Sheets"),
                    ("status", "Status"),
                ],
                [record],
            )
        ],
    )


@feature(
    "documentsSheets.stampSign",
    "Stamp & Sign",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        select(
            "stamp",
            "Approval stamp",
            [
                ("checked", "Checked"),
                ("approved", "Approved"),
                ("notForConstruction", "Not for construction"),
            ],
            "checked",
        ),
        text("professional", "Engineer name", ""),
        text("registration", "Registration number", ""),
        text("stampDate", "Date (YYYY-MM-DD)", "2026-01-01"),
    ],
)
def stamp_sign(ctx: FeatureContext, values: dict) -> dict:
    """Add a dated approval stamp record tied to the sheet and engineer identity."""
    if not values["professional"].strip():
        raise FeatureInputError("Enter the engineer whose approval stamp is being applied.")
    try:
        date.fromisoformat(values["stampDate"])
    except ValueError as exc:
        raise FeatureInputError("Enter the stamp date as YYYY-MM-DD.") from exc
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    stamp = {
        "kind": "approvalStamp",
        "sheet": sheet["number"],
        "status": values["stamp"],
        "professional": values["professional"].strip(),
        "registration": values["registration"].strip(),
        "date": values["stampDate"],
    }
    state["annotations"].append(stamp)
    sheet["approval"] = stamp
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "stamp": stamp["status"],
            "professional": stamp["professional"],
            "date": stamp["date"],
        },
        notes=[
            "This is a recorded drawing stamp; it does not create a cryptographic digital signature."
        ],
    )


@feature(
    "documentsSheets.sheetBrowser",
    "Sheet Browser",
    part="settings",
    fields=[
        text("search", "Search number or title", ""),
        select(
            "discipline",
            "Discipline",
            [
                ("all", "All"),
                ("S", "Structural"),
                ("A", "Architectural"),
                ("M", "Mechanical"),
                ("E", "Electrical"),
            ],
            "all",
        ),
    ],
)
def sheet_browser(ctx: FeatureContext, values: dict) -> dict:
    """Search the sheet hierarchy by number, title or discipline and return matching navigation entries."""
    state = _drawing_state(ctx)
    query = values["search"].strip().casefold()
    rows = [
        sheet
        for sheet in _sheet_rows(state)
        if (values["discipline"] == "all" or sheet.get("discipline") == values["discipline"])
        and (
            not query
            or query in sheet.get("number", "").casefold()
            or query in sheet.get("title", "").casefold()
        )
    ]
    return result(
        summary={"matchingSheetCount": len(rows)},
        tables=[
            table(
                "Sheet navigation",
                [
                    ("order", "Order"),
                    ("number", "Sheet"),
                    ("title", "Title"),
                    ("discipline", "Discipline"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsSheets.folderGroups",
    "Folder Groups",
    part="settings",
    fields=[
        text("groupName", "Folder group", "Foundation"),
        text("sheetNumbers", "Sheet numbers (comma-separated)", "S-101"),
        text("parentGroup", "Parent folder", "Structural"),
    ],
)
def folder_groups(ctx: FeatureContext, values: dict) -> dict:
    """Assign selected sheets to a named folder hierarchy and retain their published register order."""
    state = _drawing_state(ctx)
    numbers = {item.strip() for item in values["sheetNumbers"].split(",") if item.strip()}
    rows = []
    for number_text in numbers:
        sheet = _sheet(state, number_text)
        sheet["folder"] = values["groupName"].strip()
        sheet["parentFolder"] = values["parentGroup"].strip()
        rows.append(
            {
                "number": number_text,
                "folder": sheet["folder"],
                "parentFolder": sheet["parentFolder"],
            }
        )
    if not rows:
        raise FeatureInputError("Select at least one sheet to add to the folder group.")
    _save_drawing(ctx, state)
    return result(
        summary={"assignedSheetCount": len(rows), "group": values["groupName"].strip()},
        tables=[
            table(
                "Folder group",
                [("number", "Sheet"), ("parentFolder", "Parent folder"), ("folder", "Folder")],
                rows,
            )
        ],
    )


@feature(
    "documentsSheets.sheetParameters",
    "Sheet Parameters",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("parameter", "Parameter name", "Contract"),
        text("value", "Parameter value", ""),
        select(
            "valueType",
            "Value type",
            [("text", "Text"), ("number", "Number"), ("date", "Date")],
            "text",
        ),
    ],
)
def sheet_parameters(ctx: FeatureContext, values: dict) -> dict:
    """Store a typed sheet parameter and validate number or ISO-date values before saving."""
    if not values["parameter"].strip():
        raise FeatureInputError("Enter a parameter name.")
    value: str | float = values["value"].strip()
    if values["valueType"] == "number":
        try:
            value = float(value)
        except ValueError as exc:
            raise FeatureInputError("The parameter value must be numeric.") from exc
    elif values["valueType"] == "date":
        try:
            value = date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise FeatureInputError("Use YYYY-MM-DD for a date parameter.") from exc
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    sheet.setdefault("parameters", {})[values["parameter"].strip()] = {
        "type": values["valueType"],
        "value": value,
    }
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "parameter": values["parameter"].strip(),
            "valueType": values["valueType"],
        },
        tables=[
            table(
                "Sheet parameters",
                [("name", "Parameter"), ("type", "Type"), ("value", "Value")],
                [{"name": key, **entry} for key, entry in sheet["parameters"].items()],
            )
        ],
    )


@feature(
    "documentsSheets.sheetStatus",
    "Sheet Status",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        select(
            "status",
            "Readiness status",
            [
                ("Draft", "Draft"),
                ("For review", "For review"),
                ("For approval", "For approval"),
                ("Ready", "Ready"),
                ("Issued", "Issued"),
                ("Superseded", "Superseded"),
            ],
            "Draft",
        ),
        text("note", "Status note", ""),
    ],
)
def sheet_status(ctx: FeatureContext, values: dict) -> dict:
    """Update a sheet readiness state while preventing a released sheet from being silently unlocked."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    if sheet.get("locked") and values["status"] != "Superseded":
        raise FeatureInputError(
            "An issued sheet can only be marked Superseded; use a new revision for changes."
        )
    sheet["status"], sheet["statusNote"] = values["status"], values["note"].strip()
    sheet["statusUpdatedAt"] = datetime.now(UTC).isoformat(timespec="seconds")
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "status": sheet["status"],
            "locked": bool(sheet.get("locked")),
        }
    )


@feature(
    "documentsSheets.alignViews",
    "Align Views",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("viewNames", "View names (comma-separated)", "Level 1 framing,Level 2 framing"),
        select(
            "axis",
            "Alignment axis",
            [("horizontal", "Horizontal"), ("vertical", "Vertical")],
            "horizontal",
        ),
        number("coordinateMm", "Shared sheet coordinate", 50, unit="mm"),
    ],
)
def align_views(ctx: FeatureContext, values: dict) -> dict:
    """Align selected viewports to a shared paper coordinate on the chosen axis."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    names = [name.strip() for name in values["viewNames"].split(",") if name.strip()]
    matched = [
        view
        for view in state["views"]
        if view.get("sheet") == sheet["number"] and view.get("name") in names
    ]
    if len(matched) != len(names) or len(matched) < 2:
        raise FeatureInputError("Choose at least two existing views on the same sheet.")
    for view in matched:
        if "viewportMm" not in view:
            raise FeatureInputError(f"View {view['name']} has no viewport rectangle yet.")
    for view in matched:
        x0, y0, x1, y1 = view["viewportMm"]
        if values["axis"] == "horizontal":
            view["viewportMm"] = [x0, values["coordinateMm"], x1, values["coordinateMm"] + y1 - y0]
        else:
            view["viewportMm"] = [values["coordinateMm"], y0, values["coordinateMm"] + x1 - x0, y1]
    _save_drawing(ctx, state)
    return result(
        summary={
            "alignedViewCount": len(matched),
            "axis": values["axis"],
            "coordinateMm": values["coordinateMm"],
        },
        tables=[
            table(
                "Aligned viewports",
                [("name", "View"), ("viewportMm", "Rectangle X0/Y0/X1/Y1", "mm")],
                matched,
            )
        ],
    )


@feature(
    "documentsSheets.matchLine",
    "Match Line",
    part="settings",
    fields=[
        text("sheet", "Current sheet", "S-101"),
        text("nextSheet", "Adjacent sheet", "S-102"),
        text("label", "Match-line label", "MATCH LINE - SEE S-102"),
        number("x0Mm", "Start X", 0, unit="mm"),
        number("y0Mm", "Start Y", 0, unit="mm"),
        number("x1Mm", "End X", 1000, unit="mm"),
        number("y1Mm", "End Y", 0, unit="mm"),
    ],
)
def match_line(ctx: FeatureContext, values: dict) -> dict:
    """Place a match line that references a second registered sheet and reports its plan length."""
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    _sheet(state, values["nextSheet"])
    length = math.dist((values["x0Mm"], values["y0Mm"]), (values["x1Mm"], values["y1Mm"]))
    if length <= 0:
        raise FeatureInputError("Match-line endpoints must differ.")
    mark = {
        "kind": "matchLine",
        "sheet": values["sheet"].strip(),
        "adjacentSheet": values["nextSheet"].strip(),
        "label": values["label"].strip(),
        "startMm": [values["x0Mm"], values["y0Mm"]],
        "endMm": [values["x1Mm"], values["y1Mm"]],
        "lengthMm": length,
    }
    state["annotations"].append(mark)
    _save_drawing(ctx, state)
    return result(
        summary={"matchLineLengthMm": length, "referencedSheet": mark["adjacentSheet"]},
        tables=[
            table(
                "Sheet match line",
                [
                    ("sheet", "This sheet"),
                    ("adjacentSheet", "See sheet"),
                    ("label", "Label"),
                    ("lengthMm", "Length", "mm"),
                ],
                [mark],
            )
        ],
    )


@feature(
    "documentsSheets.guideGrid",
    "Guide Grid",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        number("columns", "Column count", 4, min=1, max=20),
        number("rows", "Row count", 3, min=1, max=20),
        number("marginMm", "Sheet margin", 15, unit="mm", min=0),
    ],
)
def guide_grid(ctx: FeatureContext, values: dict) -> dict:
    """Configure a rectangular alignment grid within the sheet margins for consistent view placement."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    paper = {"A1": (841, 594), "A2": (594, 420), "A3": (420, 297)}.get(
        sheet.get("size", "A1"), (841, 594)
    )
    usable = (paper[0] - 2 * values["marginMm"], paper[1] - 2 * values["marginMm"])
    if min(usable) <= 0:
        raise FeatureInputError("Margins must leave positive printable width and height.")
    sheet["guideGrid"] = {
        "columns": int(values["columns"]),
        "rows": int(values["rows"]),
        "marginMm": values["marginMm"],
        "cellWidthMm": usable[0] / int(values["columns"]),
        "cellHeightMm": usable[1] / int(values["rows"]),
    }
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "cellWidthMm": sheet["guideGrid"]["cellWidthMm"],
            "cellHeightMm": sheet["guideGrid"]["cellHeightMm"],
            "cellCount": int(values["columns"] * values["rows"]),
        }
    )


@feature(
    "documentsSheets.viewPlacement",
    "View Placement",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        number("columns", "Viewport columns", 2, min=1, max=10),
        number("spacingMm", "Viewport gap", 15, unit="mm", min=0),
        number("marginMm", "Outer margin", 20, unit="mm", min=0),
    ],
)
def view_placement(ctx: FeatureContext, values: dict) -> dict:
    """Lay out unplaced views in non-overlapping equal cells within the configured sheet size."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    unplaced = [
        item
        for item in state["views"]
        if item.get("sheet") == sheet["number"] and "viewportMm" not in item
    ]
    if not unplaced:
        raise FeatureInputError("There are no unplaced views on this sheet.")
    dimensions = {"A1": (841, 594), "A2": (594, 420), "A3": (420, 297)}.get(
        sheet.get("size", "A1"), (841, 594)
    )
    cols = int(values["columns"])
    rows = math.ceil(len(unplaced) / cols)
    usable_w = dimensions[0] - 2 * values["marginMm"] - (cols - 1) * values["spacingMm"]
    usable_h = dimensions[1] - 2 * values["marginMm"] - (rows - 1) * values["spacingMm"]
    if usable_w <= 0 or usable_h <= 0:
        raise FeatureInputError("The margins and gaps leave no printable area for viewports.")
    cell_w, cell_h = usable_w / cols, usable_h / rows
    for index, view in enumerate(unplaced):
        row, col = divmod(index, cols)
        x0 = values["marginMm"] + col * (cell_w + values["spacingMm"])
        y0 = values["marginMm"] + (rows - row - 1) * (cell_h + values["spacingMm"])
        view["viewportMm"] = [x0, y0, x0 + cell_w, y0 + cell_h]
        view["autoPlaced"] = True
    _save_drawing(ctx, state)
    return result(
        summary={
            "placedViewCount": len(unplaced),
            "columns": cols,
            "rows": rows,
            "cellWidthMm": cell_w,
            "cellHeightMm": cell_h,
        },
        tables=[
            table(
                "Auto-placed views",
                [("name", "View"), ("viewportMm", "Paper rectangle X0/Y0/X1/Y1", "mm")],
                unplaced,
            )
        ],
    )


@feature(
    "documentsSheets.projectInfoTag",
    "Project Info Tag",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("fieldName", "Project field", "name"),
        text("label", "Printed label", "Project"),
    ],
)
def project_info_tag(ctx: FeatureContext, values: dict) -> dict:
    """Bind a printed title-block tag to a real project-settings field and retain its resolved value."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    settings = ctx.raw("settings") or {}
    value = settings.get("project", {}).get(values["fieldName"].strip())
    if value is None:
        raise FeatureInputError(f"Project Settings has no project field {values['fieldName']!r}.")
    row = {"field": values["fieldName"].strip(), "label": values["label"].strip(), "value": value}
    state["titleBlocks"].setdefault(sheet["number"], {})["projectInfoTag"] = row
    _save_drawing(ctx, state)
    return result(summary={"sheet": sheet["number"], "label": row["label"], "value": str(value)})


@feature(
    "documentsSheets.revisionBlock",
    "Revision Block",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("columns", "Revision table columns (comma-separated)", "code,date,description,by"),
        number("rowLimit", "Visible revision rows", 8, min=1, max=30),
    ],
)
def revision_block(ctx: FeatureContext, values: dict) -> dict:
    """Configure the sheet-specific revision block columns and validate them against available issue fields."""
    allowed = {"code", "date", "description", "by", "purpose", "revision"}
    columns = [item.strip() for item in values["columns"].split(",") if item.strip()]
    if not columns or set(columns) - allowed:
        raise FeatureInputError(
            "Revision block columns may use code, date, description, by, purpose or revision."
        )
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    sheet["revisionBlock"] = {"columns": columns, "rowLimit": int(values["rowLimit"])}
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "columnCount": len(columns),
            "rowLimit": int(values["rowLimit"]),
        }
    )


@feature(
    "documentsSheets.disclaimerText",
    "Disclaimer Text",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("disclaimer", "Disclaimer", "For coordination only; verify dimensions on site."),
        checkbox("includeOnEverySheet", "Apply to every sheet", False),
    ],
)
def disclaimer_text(ctx: FeatureContext, values: dict) -> dict:
    """Save a legal disclaimer to one sheet or the project drawing-set footer."""
    if not values["disclaimer"].strip():
        raise FeatureInputError("Enter disclaimer text before saving it to the drawing set.")
    state = _drawing_state(ctx)
    if values["includeOnEverySheet"]:
        state["globalDisclaimer"] = values["disclaimer"].strip()
        target = "all sheets"
    else:
        sheet = _sheet(state, values["sheet"])
        sheet["disclaimer"] = values["disclaimer"].strip()
        target = sheet["number"]
    _save_drawing(ctx, state)
    return result(
        summary={
            "target": target,
            "characterCount": len(values["disclaimer"].strip()),
            "wordCount": len(values["disclaimer"].split()),
        }
    )


@feature(
    "documentsSheets.packageSheets",
    "Package Sheets",
    part="settings",
    fields=[
        text("sheetNumbers", "Sheet numbers (comma-separated; blank means all)", ""),
        text("packageName", "Package name", "drawing-submission.zip"),
        text("purpose", "Package purpose", "For review"),
    ],
)
def package_sheets(ctx: FeatureContext, values: dict) -> dict:
    """Bundle selected generated sheet DXFs and a manifest into a submission ZIP with file checksums."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to package drawing sheets.")
    folder = ctx.root / "11 Exports" / "Drawings"
    files = sorted(path for path in folder.glob("*.dxf") if path.is_file())
    if not files:
        raise FeatureInputError("Generate the drawing set before packaging sheets.")
    requested = {item.strip() for item in values["sheetNumbers"].split(",") if item.strip()}
    if requested:
        files = [path for path in files if path.stem.split(" ", 1)[0] in requested]
        missing = requested - {path.stem.split(" ", 1)[0] for path in files}
        if missing:
            raise FeatureInputError(
                f"Generated sheet file(s) are missing: {', '.join(sorted(missing))}."
            )
    name = Path(values["packageName"].strip() or "drawing-submission.zip").name
    if not name.lower().endswith(".zip"):
        name += ".zip"
    target = ctx.root / "11 Exports" / "Packages" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path in files:
            data = path.read_bytes()
            package.write(path, path.name)
            manifest.append(
                {"name": path.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            )
        package.writestr(
            "package-manifest.json",
            json.dumps(
                {
                    "purpose": values["purpose"],
                    "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
                    "files": manifest,
                },
                indent=2,
            )
            + "\n",
        )
    return result(
        summary={
            "package": _relative_output(ctx, target),
            "sheetCount": len(files),
            "purpose": values["purpose"],
        },
        tables=[
            table(
                "Package contents",
                [("name", "File"), ("sha256", "SHA-256"), ("bytes", "Bytes")],
                manifest,
            )
        ],
    )


@feature(
    "documentsSheets.digitalSignature",
    "Digital Signature",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text(
            "privateKeyPath",
            "Project-relative Ed25519 private key PEM",
            "11 Exports/keys/signing-key.pem",
        ),
        text("keyPassword", "Private key password (optional)", ""),
    ],
)
def digital_signature(ctx: FeatureContext, values: dict) -> dict:
    """Create a detached Ed25519 signature over a generated sheet using a project-held private key."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before signing a drawing.")
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"], allow_locked=True)
    dxf = ctx.root / "11 Exports" / "Drawings" / f"{sheet['number']} {sheet['title']}.dxf"
    if not dxf.is_file():
        raise FeatureInputError("Generate the sheet DXF before signing it.")
    key_path = (ctx.root / values["privateKeyPath"]).resolve()
    try:
        key_path.relative_to(ctx.root.resolve())
    except ValueError as exc:
        raise FeatureInputError("The signing key must be inside the project folder.") from exc
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = serialization.load_pem_private_key(
            key_path.read_bytes(), password=values["keyPassword"].encode() or None
        )
        if not isinstance(key, Ed25519PrivateKey):
            raise FeatureInputError("The private key must use Ed25519.")
        payload = dxf.read_bytes()
        signature = key.sign(payload)
    except FeatureInputError:
        raise
    except (OSError, ValueError, TypeError, ImportError) as exc:
        raise FeatureInputError(
            "Could not load an Ed25519 private key; check the project-relative PEM path and password."
        ) from exc
    sig_path = dxf.with_suffix(".dxf.sig")
    sig_path.write_text(
        json.dumps(
            {
                "algorithm": "Ed25519",
                "file": dxf.name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "signatureBase64": __import__("base64").b64encode(signature).decode("ascii"),
                "signedAt": datetime.now(UTC).isoformat(timespec="seconds"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result(
        summary={
            "sheet": sheet["number"],
            "signatureFile": _relative_output(ctx, sig_path),
            "algorithm": "Ed25519",
        },
        notes=[
            "The detached signature is verifiable with the public key corresponding to the project PEM."
        ],
    )


@feature(
    "documentsSheets.issueHistory",
    "Issue History",
    part="settings",
    fields=[text("sheet", "Sheet number (blank means all)", "")],
)
def issue_history(ctx: FeatureContext, values: dict) -> dict:
    """Read the real drawing issue register and show each sheet's history or the full set history."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to read the drawing issue register.")
    path = ctx.root / "11 Exports" / "Drawings" / "register.json"
    try:
        register = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FeatureInputError(
            "The drawing register is missing; issue a drawing set first."
        ) from exc
    rows = []
    for item in register.get("sheets", []) if isinstance(register, dict) else []:
        if values["sheet"].strip() and item.get("number") != values["sheet"].strip():
            continue
        for revision in item.get("issues", []):
            rows.append(
                {
                    "sheet": item.get("number", ""),
                    "revision": revision.get("code", ""),
                    "date": revision.get("date", ""),
                    "description": revision.get("description", ""),
                    "by": revision.get("by", ""),
                }
            )
    return result(
        summary={"issueRecordCount": len(rows)},
        tables=[
            table(
                "Drawing issue history",
                [
                    ("sheet", "Sheet"),
                    ("revision", "Revision"),
                    ("date", "Date"),
                    ("description", "Description"),
                    ("by", "Issued by"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsSheets.distributionList",
    "Distribution List",
    part="settings",
    fields=[
        text("recipient", "Recipient name or organisation", ""),
        text("email", "Email address", ""),
        text("discipline", "Discipline", "Structural"),
        checkbox("active", "Active for drawing issues", True),
    ],
)
def distribution_list(ctx: FeatureContext, values: dict) -> dict:
    """Add or update a drawing-release recipient and validate the email address before saving."""
    if not values["recipient"].strip() or not re.fullmatch(
        r"[^\s@]+@[^\s@]+\.[^\s@]+", values["email"].strip()
    ):
        raise FeatureInputError("Enter a recipient name and a valid email address.")
    state = _drawing_state(ctx)
    recipients = state.setdefault("distributionList", [])
    item = {
        "recipient": values["recipient"].strip(),
        "email": values["email"].strip(),
        "discipline": values["discipline"].strip(),
        "active": values["active"],
    }
    recipients[:] = [
        row for row in recipients if row.get("email", "").casefold() != item["email"].casefold()
    ]
    recipients.append(item)
    _save_drawing(ctx, state)
    return result(
        summary={
            "recipientCount": len(recipients),
            "activeRecipientCount": sum(row["active"] for row in recipients),
        },
        tables=[
            table(
                "Drawing distribution list",
                [
                    ("recipient", "Recipient"),
                    ("email", "Email"),
                    ("discipline", "Discipline"),
                    ("active", "Active"),
                ],
                recipients,
            )
        ],
    )


@feature(
    "docMarkup.redline",
    "Redline",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("points", "Polyline points as x,y; x,y in sheet mm", "10,10;100,100;180,70"),
        text("author", "Author", ""),
        text("note", "Review note", ""),
    ],
)
def redline(ctx: FeatureContext, values: dict) -> dict:
    """Draw a review polyline from explicit paper-space points and compute its total segment length."""
    points = []
    try:
        points = [
            [float(part.strip()) for part in item.split(",")]
            for item in values["points"].split(";")
            if item.strip()
        ]
    except ValueError as exc:
        raise FeatureInputError(
            "Polyline points must use x,y pairs separated by semicolons."
        ) from exc
    if len(points) < 2 or any(len(point) != 2 for point in points):
        raise FeatureInputError("A redline needs at least two x,y points.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    mark = {
        "kind": "redline",
        "sheet": values["sheet"].strip(),
        "pointsMm": points,
        "author": values["author"].strip() or "Unknown",
        "note": values["note"].strip(),
        "lengthMm": sum(math.dist(a, b) for a, b in pairwise(points)),
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "Open",
    }
    state["annotations"].append(mark)
    _save_drawing(ctx, state)
    return result(
        summary={
            "markupLengthMm": mark["lengthMm"],
            "vertexCount": len(points),
            "status": mark["status"],
        },
        tables=[
            table(
                "Redline geometry",
                [("point", "Vertex"), ("xMm", "X", "mm"), ("yMm", "Y", "mm")],
                [
                    {"point": i + 1, "xMm": point[0], "yMm": point[1]}
                    for i, point in enumerate(points)
                ],
            )
        ],
    )


@feature(
    "docMarkup.cloudMarkup",
    "Cloud Markup",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        number("leftMm", "Left", 10, unit="mm"),
        number("bottomMm", "Bottom", 10, unit="mm"),
        number("rightMm", "Right", 100, unit="mm"),
        number("topMm", "Top", 80, unit="mm"),
        text("comment", "Cloud comment", "Review this area"),
    ],
)
def cloud_markup(ctx: FeatureContext, values: dict) -> dict:
    """Create a revision-cloud markup around a validated paper-space rectangle with perimeter and area."""
    if values["rightMm"] <= values["leftMm"] or values["topMm"] <= values["bottomMm"]:
        raise FeatureInputError("Cloud right/top bounds must exceed left/bottom bounds.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    width, height = values["rightMm"] - values["leftMm"], values["topMm"] - values["bottomMm"]
    item = {
        "kind": "cloudMarkup",
        "sheet": values["sheet"].strip(),
        "boundsMm": [values["leftMm"], values["bottomMm"], values["rightMm"], values["topMm"]],
        "comment": values["comment"].strip(),
        "perimeterMm": 2 * (width + height),
        "areaMm2": width * height,
        "status": "Open",
    }
    state["annotations"].append(item)
    _save_drawing(ctx, state)
    return result(
        summary={
            "perimeterMm": item["perimeterMm"],
            "areaMm2": item["areaMm2"],
            "comment": item["comment"],
        }
    )


@feature(
    "docMarkup.textNote",
    "Text Note",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("noteId", "Note id", "N-1"),
        text("content", "Note text", "Verify dimensions on site."),
        number("xMm", "Text X", 30, unit="mm"),
        number("yMm", "Text Y", 30, unit="mm"),
        number("heightMm", "Text height", 2.5, unit="mm", min=0.5),
        select(
            "alignment",
            "Alignment",
            [("left", "Left"), ("center", "Centre"), ("right", "Right")],
            "left",
        ),
    ],
)
def drawing_text_note(ctx: FeatureContext, values: dict) -> dict:
    """Place a uniquely identified paper-space note with explicit insertion point, text height and alignment."""
    if not values["content"].strip():
        raise FeatureInputError("Text note content cannot be blank.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    if any(
        item.get("noteId") == values["noteId"].strip()
        and item.get("sheet") == values["sheet"].strip()
        for item in state["annotations"]
    ):
        raise FeatureInputError("A note with that id already exists on this sheet.")
    note = {
        "kind": "textNote",
        "sheet": values["sheet"].strip(),
        "noteId": values["noteId"].strip(),
        "content": values["content"].strip(),
        "positionMm": [values["xMm"], values["yMm"]],
        "heightMm": values["heightMm"],
        "alignment": values["alignment"],
        "status": "Open",
    }
    state["annotations"].append(note)
    _save_drawing(ctx, state)
    return result(
        summary={
            "noteId": note["noteId"],
            "characters": len(note["content"]),
            "positionMm": note["positionMm"],
            "alignment": note["alignment"],
        }
    )


@feature(
    "docMarkup.arrowLeader",
    "Arrow & Leader",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        number("tailXmm", "Leader tail X", 100, unit="mm"),
        number("tailYmm", "Leader tail Y", 50, unit="mm"),
        number("headXmm", "Arrow head X", 60, unit="mm"),
        number("headYmm", "Arrow head Y", 40, unit="mm"),
        text("label", "Leader label", "Check connection"),
    ],
)
def arrow_leader(ctx: FeatureContext, values: dict) -> dict:
    """Place an arrow leader from its text tail to a drawing point and calculate its length and direction."""
    start, end = (values["tailXmm"], values["tailYmm"]), (values["headXmm"], values["headYmm"])
    length = math.dist(start, end)
    if length == 0:
        raise FeatureInputError("The leader arrow head and tail must be in different locations.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    leader = {
        "kind": "arrowLeader",
        "sheet": values["sheet"].strip(),
        "tailMm": list(start),
        "headMm": list(end),
        "label": values["label"].strip(),
        "lengthMm": length,
        "angleDeg": math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])),
    }
    state["annotations"].append(leader)
    _save_drawing(ctx, state)
    return result(
        summary={"leaderLengthMm": length, "angleDeg": leader["angleDeg"], "label": leader["label"]}
    )


@feature(
    "docMarkup.dimensionNote",
    "Dimension Note",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("firstGridPoint", "First measured grid point", "A-1"),
        text("secondGridPoint", "Second measured grid point", "B-2"),
        text("author", "Author", ""),
    ],
)
def dimension_note(ctx: FeatureContext, values: dict) -> dict:
    """Create a temporary measurement markup from two grid references and record its SI distance."""
    plan = plan_data(ctx)
    first = point_xy(plan, parse_point(values["firstGridPoint"]))
    second = point_xy(plan, parse_point(values["secondGridPoint"]))
    distance = math.dist(first, second)
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    note = {
        "kind": "dimensionNote",
        "sheet": values["sheet"].strip(),
        "startMm": list(first),
        "endMm": list(second),
        "distanceMm": distance,
        "author": values["author"].strip() or "Unknown",
        "temporary": True,
    }
    state["annotations"].append(note)
    _save_drawing(ctx, state)
    return result(
        summary={"distanceM": distance / 1000, "distanceMm": distance, "temporary": True},
        tables=[
            table(
                "Measured dimension",
                [
                    ("startMm", "First point X/Y", "mm"),
                    ("endMm", "Second point X/Y", "mm"),
                    ("distanceMm", "Distance", "mm"),
                ],
                [note],
            )
        ],
    )


@feature(
    "docMarkup.freehandSketch",
    "Freehand Sketch",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("points", "Sketch points as x,y pairs in mm", "10,10;20,15;35,12"),
        text("author", "Author", ""),
        select(
            "colour",
            "Sketch colour",
            [("red", "Red"), ("blue", "Blue"), ("green", "Green"), ("black", "Black")],
            "red",
        ),
    ],
)
def freehand_sketch(ctx: FeatureContext, values: dict) -> dict:
    """Record a freehand stroke with measured length, bounds and author for the drawing review overlay."""
    try:
        points = [
            [float(n.strip()) for n in pair.split(",")]
            for pair in values["points"].split(";")
            if pair.strip()
        ]
    except ValueError as exc:
        raise FeatureInputError("Sketch points must be x,y pairs separated by semicolons.") from exc
    if len(points) < 2 or any(len(point) != 2 for point in points):
        raise FeatureInputError("A sketch needs at least two x,y points.")
    length = sum(math.dist(a, b) for a, b in pairwise(points))
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    sketch = {
        "kind": "freehandSketch",
        "sheet": values["sheet"].strip(),
        "pointsMm": points,
        "colour": values["colour"],
        "author": values["author"].strip() or "Unknown",
        "lengthMm": length,
        "boundsMm": [
            min(p[0] for p in points),
            min(p[1] for p in points),
            max(p[0] for p in points),
            max(p[1] for p in points),
        ],
    }
    state["annotations"].append(sketch)
    _save_drawing(ctx, state)
    return result(
        summary={"vertexCount": len(points), "strokeLengthMm": length, "colour": sketch["colour"]},
        tables=[
            table(
                "Sketch points",
                [("index", "Vertex"), ("xMm", "X", "mm"), ("yMm", "Y", "mm")],
                [
                    {"index": i + 1, "xMm": point[0], "yMm": point[1]}
                    for i, point in enumerate(points)
                ],
            )
        ],
    )


@feature(
    "docMarkup.comments",
    "Comments",
    part="settings",
    fields=[
        text("markupId", "Markup id", "N-1"),
        text("author", "Comment author", ""),
        text("comment", "Comment", "Please confirm this detail."),
        text("replyTo", "Parent comment id", ""),
    ],
)
def markup_comments(ctx: FeatureContext, values: dict) -> dict:
    """Add a timestamped comment to a specific markup and optionally link it to a parent reply."""
    if not values["comment"].strip():
        raise FeatureInputError("Enter comment text before saving the review thread.")
    state = _drawing_state(ctx)
    target = next(
        (
            item
            for item in state["annotations"]
            if item.get("noteId") == values["markupId"] or item.get("id") == values["markupId"]
        ),
        None,
    )
    if target is None:
        raise FeatureInputError("The markup id does not exist in this drawing workspace.")
    comments = target.setdefault("comments", [])
    if values["replyTo"].strip() and values["replyTo"].strip() not in {
        item.get("id") for item in comments
    }:
        raise FeatureInputError("The parent comment id is not in this markup thread.")
    comment = {
        "id": f"C{len(comments) + 1}",
        "author": values["author"].strip() or "Unknown",
        "text": values["comment"].strip(),
        "replyTo": values["replyTo"].strip() or None,
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "resolved": False,
    }
    comments.append(comment)
    _save_drawing(ctx, state)
    return result(
        summary={
            "markupId": values["markupId"],
            "commentId": comment["id"],
            "threadLength": len(comments),
        },
        tables=[
            table(
                "Markup comments",
                [
                    ("id", "Comment"),
                    ("replyTo", "Reply to"),
                    ("author", "Author"),
                    ("text", "Text"),
                    ("createdAt", "Created"),
                ],
                comments,
            )
        ],
    )


@feature(
    "docMarkup.assignReviewer",
    "Assign Reviewer",
    part="settings",
    fields=[
        text("markupId", "Markup id", "N-1"),
        text("reviewer", "Reviewer", ""),
        text("dueDate", "Review due date (YYYY-MM-DD)", ""),
    ],
)
def assign_reviewer(ctx: FeatureContext, values: dict) -> dict:
    """Assign a named reviewer and optional due date to an open drawing markup."""
    if not values["reviewer"].strip():
        raise FeatureInputError("Enter a reviewer name.")
    if values["dueDate"].strip():
        try:
            date.fromisoformat(values["dueDate"])
        except ValueError as exc:
            raise FeatureInputError("Use YYYY-MM-DD for the reviewer due date.") from exc
    state = _drawing_state(ctx)
    mark = next(
        (
            item
            for item in state["annotations"]
            if item.get("noteId") == values["markupId"] or item.get("id") == values["markupId"]
        ),
        None,
    )
    if mark is None:
        raise FeatureInputError("The markup id was not found.")
    mark["reviewer"] = values["reviewer"].strip()
    mark["reviewDueDate"] = values["dueDate"].strip() or None
    mark["reviewAssignedAt"] = datetime.now(UTC).isoformat(timespec="seconds")
    _save_drawing(ctx, state)
    return result(
        summary={
            "markupId": values["markupId"],
            "reviewer": mark["reviewer"],
            "dueDate": mark["reviewDueDate"],
            "status": mark.get("status", "Open"),
        }
    )


@feature(
    "docMarkup.resolveMarkup",
    "Resolve Markup",
    part="settings",
    fields=[
        text("markupId", "Markup id", "N-1"),
        text("resolvedBy", "Resolved by", ""),
        text("resolution", "Resolution note", "Addressed in revision A"),
    ],
)
def resolve_markup(ctx: FeatureContext, values: dict) -> dict:
    """Close a markup thread with a timestamp, resolver identity and required resolution note."""
    if not values["resolution"].strip():
        raise FeatureInputError("Enter a resolution note before closing the markup.")
    state = _drawing_state(ctx)
    mark = next(
        (
            item
            for item in state["annotations"]
            if item.get("noteId") == values["markupId"] or item.get("id") == values["markupId"]
        ),
        None,
    )
    if mark is None:
        raise FeatureInputError("The markup id was not found.")
    if mark.get("status") == "Resolved":
        raise FeatureInputError("This markup is already resolved.")
    mark.update(
        status="Resolved",
        resolution=values["resolution"].strip(),
        resolvedBy=values["resolvedBy"].strip() or "Unknown",
        resolvedAt=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    _save_drawing(ctx, state)
    return result(
        summary={
            "markupId": values["markupId"],
            "status": "Resolved",
            "resolvedBy": mark["resolvedBy"],
        },
        notes=[mark["resolution"]],
    )


@feature(
    "docMarkup.compareSheets",
    "Compare Sheets",
    part="settings",
    fields=[text("sheetA", "First sheet", "S-101"), text("sheetB", "Second sheet", "S-102")],
)
def compare_sheets(ctx: FeatureContext, values: dict) -> dict:
    """Compare saved view and annotation content between two sheets and list additions and omissions."""
    state = _drawing_state(ctx)
    first, second = _sheet(state, values["sheetA"]), _sheet(state, values["sheetB"])
    a = {
        (item.get("kind"), item.get("name", item.get("noteId", item.get("label", ""))))
        for item in state["views"] + state["annotations"]
        if item.get("sheet") == first["number"]
    }
    b = {
        (item.get("kind"), item.get("name", item.get("noteId", item.get("label", ""))))
        for item in state["views"] + state["annotations"]
        if item.get("sheet") == second["number"]
    }
    rows = [
        {"change": "onlyA", "kind": kind, "identity": identity} for kind, identity in sorted(a - b)
    ] + [
        {"change": "onlyB", "kind": kind, "identity": identity} for kind, identity in sorted(b - a)
    ]
    return result(
        summary={
            "differenceCount": len(rows),
            "firstSheetItems": len(a),
            "secondSheetItems": len(b),
        },
        tables=[
            table(
                "Sheet content differences",
                [("change", "Present on"), ("kind", "Item type"), ("identity", "Item")],
                rows,
            )
        ],
        notes=[
            "Comparison covers the saved preview workspace; use drawing revision issue comparison for generated DXF content."
        ],
    )


@feature(
    "docMarkup.overlay",
    "Overlay",
    part="settings",
    fields=[
        text("baseSheet", "Base sheet", "S-101"),
        text("overlaySheet", "Overlay sheet", "S-102"),
        number("opacityPercent", "Overlay opacity", 50, unit="%", min=0, max=100),
    ],
)
def overlay(ctx: FeatureContext, values: dict) -> dict:
    """Build a view-ready overlay descriptor for two sheets and count the annotations contributed by each."""
    state = _drawing_state(ctx)
    base, other = _sheet(state, values["baseSheet"]), _sheet(state, values["overlaySheet"])
    base_marks = [item for item in state["annotations"] if item.get("sheet") == base["number"]]
    overlay_marks = [item for item in state["annotations"] if item.get("sheet") == other["number"]]
    descriptor = {
        "base": base["number"],
        "overlay": other["number"],
        "opacityPercent": values["opacityPercent"],
        "baseAnnotationCount": len(base_marks),
        "overlayAnnotationCount": len(overlay_marks),
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    state.setdefault("overlays", []).append(descriptor)
    _save_drawing(ctx, state)
    return result(
        summary={
            "baseSheet": base["number"],
            "overlaySheet": other["number"],
            "opacityPercent": values["opacityPercent"],
            "combinedAnnotationCount": len(base_marks) + len(overlay_marks),
        },
        tables=[
            table(
                "Overlay layers",
                [
                    ("sheet", "Sheet"),
                    ("role", "Layer"),
                    ("annotationCount", "Annotations"),
                    ("opacityPercent", "Opacity", "%"),
                ],
                [
                    {
                        "sheet": base["number"],
                        "role": "base",
                        "annotationCount": len(base_marks),
                        "opacityPercent": 100,
                    },
                    {
                        "sheet": other["number"],
                        "role": "overlay",
                        "annotationCount": len(overlay_marks),
                        "opacityPercent": values["opacityPercent"],
                    },
                ],
            )
        ],
    )


@feature(
    "docMarkup.snapshot",
    "Snapshot",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("snapshotName", "Snapshot name", "Review capture"),
        text("capturedBy", "Captured by", ""),
    ],
)
def snapshot(ctx: FeatureContext, values: dict) -> dict:
    """Capture a deterministic snapshot of sheet views, annotations and their source-plan member schedule."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    plan_rows = member_rows(plan_data(ctx))
    snapshot_data = {
        "name": values["snapshotName"].strip(),
        "sheet": sheet["number"],
        "capturedBy": values["capturedBy"].strip() or "Unknown",
        "capturedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "views": [item for item in state["views"] if item.get("sheet") == sheet["number"]],
        "annotations": [
            item for item in state["annotations"] if item.get("sheet") == sheet["number"]
        ],
        "memberIds": [row["id"] for row in plan_rows],
    }
    raw = json.dumps(snapshot_data, sort_keys=True, separators=(",", ":"))
    snapshot_data["sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    state.setdefault("snapshots", []).append(snapshot_data)
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "snapshotName": snapshot_data["name"],
            "viewCount": len(snapshot_data["views"]),
            "annotationCount": len(snapshot_data["annotations"]),
            "sha256": snapshot_data["sha256"],
        },
        notes=[
            "Snapshot captures the document preview inputs and member ids; no raster image is claimed."
        ],
    )


@feature(
    "docMarkup.approvalStamp",
    "Approval Stamp",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        select(
            "status",
            "Stamp status",
            [("Approved", "Approved"), ("Checked", "Checked"), ("Rejected", "Rejected")],
            "Checked",
        ),
        text("engineer", "Engineer", ""),
        text("registration", "Registration number", ""),
        text("date", "Stamp date (YYYY-MM-DD)", "2026-01-01"),
    ],
)
def approval_stamp(ctx: FeatureContext, values: dict) -> dict:
    """Stamp a review status onto the drawing preview with professional identity and a validated date."""
    if not values["engineer"].strip():
        raise FeatureInputError("Enter the engineer applying the review stamp.")
    try:
        date.fromisoformat(values["date"])
    except ValueError as exc:
        raise FeatureInputError("Use YYYY-MM-DD for the stamp date.") from exc
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    stamp = {
        "kind": "approvalStamp",
        "sheet": sheet["number"],
        "status": values["status"],
        "engineer": values["engineer"].strip(),
        "registration": values["registration"].strip(),
        "date": values["date"],
    }
    state["annotations"].append(stamp)
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "status": stamp["status"],
            "engineer": stamp["engineer"],
            "date": stamp["date"],
        },
        notes=[
            "This review stamp is traceable metadata; it does not sign the DXF cryptographically."
        ],
    )


@feature(
    "docMarkup.statusStamp",
    "Status Stamp",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        select(
            "status",
            "Drawing status",
            [
                ("DRAFT", "Draft"),
                ("FOR REVIEW", "For review"),
                ("APPROVED", "Approved"),
                ("SUPERSEDED", "Superseded"),
            ],
            "DRAFT",
        ),
        text("revision", "Revision", "A"),
    ],
)
def status_stamp(ctx: FeatureContext, values: dict) -> dict:
    """Set a visible status stamp and revision on one drawing preview without overwriting its issue history."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    stamp = {
        "kind": "statusStamp",
        "sheet": sheet["number"],
        "status": values["status"],
        "revision": values["revision"].strip(),
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    sheet["statusStamp"] = stamp
    state["annotations"].append(stamp)
    _save_drawing(ctx, state)
    return result(
        summary={"sheet": sheet["number"], "stamp": stamp["status"], "revision": stamp["revision"]}
    )


@feature(
    "docMarkup.customStamp",
    "Custom Stamp",
    part="settings",
    fields=[
        text("stampName", "Stamp name", "Reviewed"),
        text("text", "Stamp text", "CHECKED"),
        text("sheet", "Sheet number", "S-101"),
        text("author", "Applied by", ""),
        select(
            "colour",
            "Stamp colour",
            [("red", "Red"), ("blue", "Blue"), ("green", "Green"), ("black", "Black")],
            "blue",
        ),
    ],
)
def custom_stamp(ctx: FeatureContext, values: dict) -> dict:
    """Define a named custom review stamp and apply its text, colour and author to the chosen sheet."""
    if not values["stampName"].strip() or not values["text"].strip():
        raise FeatureInputError("Enter a stamp name and printed text.")
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    stamp = {
        "kind": "customStamp",
        "name": values["stampName"].strip(),
        "text": values["text"].strip(),
        "colour": values["colour"],
        "sheet": sheet["number"],
        "author": values["author"].strip() or "Unknown",
    }
    state.setdefault("stampLibrary", {})[stamp["name"]] = {
        "text": stamp["text"],
        "colour": stamp["colour"],
    }
    state["annotations"].append(stamp)
    _save_drawing(ctx, state)
    return result(
        summary={
            "stampName": stamp["name"],
            "sheet": sheet["number"],
            "colour": stamp["colour"],
            "libraryStampCount": len(state["stampLibrary"]),
        }
    )


@feature(
    "docMarkup.measureDistance",
    "Measure Distance",
    part="settings",
    fields=[text("first", "First grid point", "A-1"), text("second", "Second grid point", "B-2")],
)
def measure_distance(ctx: FeatureContext, values: dict) -> dict:
    """Measure plan distance between two grid references and return horizontal, vertical and true lengths."""
    plan = plan_data(ctx)
    a, b = (
        point_xy(plan, parse_point(values["first"])),
        point_xy(plan, parse_point(values["second"])),
    )
    dx, dy = b[0] - a[0], b[1] - a[1]
    return result(
        summary={
            "deltaXMm": dx,
            "deltaYMm": dy,
            "horizontalDistanceM": abs(dx) / 1000,
            "verticalDistanceM": abs(dy) / 1000,
            "trueDistanceM": math.hypot(dx, dy) / 1000,
        },
        tables=[
            table(
                "Measured plan distance",
                [("point", "Grid point"), ("xMm", "X", "mm"), ("yMm", "Y", "mm")],
                [
                    {"point": values["first"], "xMm": a[0], "yMm": a[1]},
                    {"point": values["second"], "xMm": b[0], "yMm": b[1]},
                ],
            )
        ],
    )


@feature(
    "docMarkup.areaMarkup",
    "Area Markup",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("gridPoints", "Closed polygon grid points, semicolon-separated", "A-1;B-1;B-2;A-2"),
        text("label", "Area label", "Review zone"),
    ],
)
def area_markup(ctx: FeatureContext, values: dict) -> dict:
    """Resolve a closed polygon on the floor plan, calculate its area and save it as a review markup."""
    plan = plan_data(ctx)
    points = [
        point_xy(plan, parse_point(value))
        for value in values["gridPoints"].split(";")
        if value.strip()
    ]
    if len(points) < 3:
        raise FeatureInputError("An area markup needs at least three grid points.")
    area = (
        abs(
            sum(
                points[i][0] * points[(i + 1) % len(points)][1]
                - points[(i + 1) % len(points)][0] * points[i][1]
                for i in range(len(points))
            )
            / 2
        )
        / 1_000_000
    )
    if area <= 0:
        raise FeatureInputError("Area markup points must enclose a non-zero area.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    mark = {
        "kind": "areaMarkup",
        "sheet": values["sheet"].strip(),
        "label": values["label"].strip(),
        "pointsMm": points,
        "areaM2": area,
        "status": "Open",
    }
    state["annotations"].append(mark)
    _save_drawing(ctx, state)
    return result(
        summary={
            "areaM2": area,
            "areaMm2": area * 1_000_000,
            "vertexCount": len(points),
            "label": mark["label"],
        }
    )


@feature(
    "docMarkup.perimeterTool",
    "Perimeter Tool",
    part="settings",
    fields=[
        text("gridPoints", "Closed polygon grid points, semicolon-separated", "A-1;B-1;B-2;A-2")
    ],
)
def perimeter_tool(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the closed perimeter of a polygon defined by validated floor-plan grid points."""
    plan = plan_data(ctx)
    points = [
        point_xy(plan, parse_point(value))
        for value in values["gridPoints"].split(";")
        if value.strip()
    ]
    if len(points) < 3:
        raise FeatureInputError("A perimeter needs at least three polygon points.")
    lengths = [math.dist(points[i], points[(i + 1) % len(points)]) for i in range(len(points))]
    return result(
        summary={"perimeterM": sum(lengths) / 1000, "segmentCount": len(lengths)},
        tables=[
            table(
                "Perimeter segments",
                [("segment", "Segment"), ("lengthMm", "Length", "mm")],
                [{"segment": i + 1, "lengthMm": length} for i, length in enumerate(lengths)],
            )
        ],
    )


@feature(
    "docMarkup.countItems",
    "Count Items",
    part="settings",
    fields=[
        select(
            "category",
            "Item category",
            [
                ("all", "All members"),
                ("column", "Columns"),
                ("beam", "Beams"),
                ("wall", "Walls"),
                ("slab", "Slabs"),
                ("footing", "Footings"),
            ],
            "all",
        ),
        text("story", "Story id (blank means all)", ""),
        text("searchType", "Object type contains", ""),
    ],
)
def count_items(ctx: FeatureContext, values: dict) -> dict:
    """Count actual floor-plan objects by category, story and object-type filter for a drawing tally."""
    rows = member_rows(plan_data(ctx))
    selected = [
        row
        for row in rows
        if (values["category"] == "all" or row["category"] == values["category"])
        and (not values["story"].strip() or row["story"] == values["story"].strip())
        and values["searchType"].casefold() in row["type"].casefold()
    ]
    counts = {}
    for row in selected:
        key = (row["category"], row["story"], row["type"])
        counts[key] = counts.get(key, 0) + 1
    output = [
        {"category": key[0], "story": key[1], "type": key[2], "count": count}
        for key, count in sorted(counts.items())
    ]
    return result(
        summary={"countedMemberCount": len(selected), "groupCount": len(output)},
        tables=[
            table(
                "Drawing item tally",
                [
                    ("category", "Category"),
                    ("story", "Story"),
                    ("type", "Object type"),
                    ("count", "Count"),
                ],
                output,
            )
        ],
    )


@feature(
    "docMarkup.bcfExport",
    "BCF Export",
    part="settings",
    fields=[
        text("fileName", "BCF package name", "drawing-markups.bcfzip"),
        text("author", "Export author", ""),
    ],
)
def markup_bcf_export(ctx: FeatureContext, values: dict) -> dict:
    """Export open drawing markups as a BCF 2.1 issue archive with comments and sheet references."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to export drawing markups.")
    state = _drawing_state(ctx)
    marks = [item for item in state["annotations"] if item.get("status", "Open") != "Resolved"]
    if not marks:
        raise FeatureInputError("There are no open markups to export.")
    path = (
        ctx.root / "11 Exports" / Path(values["fileName"].strip() or "drawing-markups.bcfzip").name
    )
    if path.suffix.lower() != ".bcfzip":
        path = path.with_suffix(".bcfzip")
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "bcf.version", '<?xml version="1.0" encoding="UTF-8"?><Version VersionId="2.1"/>'
        )
        package.writestr(
            "project.bcfp",
            '<?xml version="1.0" encoding="UTF-8"?><ProjectExtension ProjectId="saengine"/>',
        )
        for index, mark in enumerate(marks, 1):
            guid = hashlib.sha1(
                f"{mark.get('sheet')}:{mark.get('kind')}:{index}".encode()
            ).hexdigest()[:22]
            xml = f'<Markup><Header><File Filename="{mark.get("sheet", "")}"/></Header><Topic Guid="{guid}" TopicType="Issue" TopicStatus="Open" Title="{mark.get("noteId", mark.get("label", mark.get("kind", "Markup")))}" CreationAuthor="{values["author"].strip() or "Unknown"}" Description="{mark.get("content", mark.get("note", ""))}"/><Comment Guid="{guid}-c" Date="{mark.get("createdAt", "")}" Author="{mark.get("author", "Unknown")}">{mark.get("note", "")}</Comment><Viewpoints><Viewpoint Guid="{guid}-view"/></Viewpoints></Markup>'
            view = f'<VisualizationInfo Guid="{guid}-view"><Components><Selection><Component IfcGuid="{mark.get("memberId", "unknown")}"/></Selection></Components></VisualizationInfo>'
            package.writestr(f"{guid}/markup.bcf", xml)
            package.writestr(f"{guid}/viewpoint.bcfv", view)
    return result(
        summary={"markupCount": len(marks), "bcfPath": path.relative_to(ctx.root).as_posix()},
        notes=["The BCF archive contains one topic for each open markup."],
    )


@feature(
    "docMarkup.bcfImport",
    "BCF Import",
    part="settings",
    fields=[
        text("packagePath", "Project-relative BCF ZIP", "11 Exports/drawing-markups.bcfzip"),
        text("importedBy", "Imported by", ""),
    ],
)
def markup_bcf_import(ctx: FeatureContext, values: dict) -> dict:
    """Read BCF markup topics from a project archive and import their titles and sheet references."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before importing BCF markups.")
    path = (ctx.root / values["packagePath"]).resolve()
    try:
        path.relative_to(ctx.root.resolve())
        with zipfile.ZipFile(path) as package:
            names = [name for name in package.namelist() if name.endswith("/markup.bcf")]
            imported = []
            for name in names:
                content = package.read(name).decode("utf-8", errors="replace")
                match = re.search(
                    r'<Topic\b[^>]*Title="([^"]*)"[^>]*TopicStatus="([^"]*)"', content
                )
                title = match.group(1) if match else Path(name).parent.name
                status = match.group(2) if match else "Open"
                header = re.search(r'<File\b[^>]*Filename="([^"]*)"', content)
                imported.append(
                    {
                        "kind": "bcfIssue",
                        "id": Path(name).parent.name,
                        "title": title,
                        "sheet": header.group(1) if header else "",
                        "status": status,
                        "importedBy": values["importedBy"].strip() or "Unknown",
                        "source": path.name,
                    }
                )
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise FeatureInputError(
            "The selected BCF file could not be read from inside the project."
        ) from exc
    state = _drawing_state(ctx)
    state.setdefault("bcfIssues", []).extend(imported)
    _save_drawing(ctx, state)
    return result(
        summary={"importedIssueCount": len(imported), "source": path.name},
        tables=[
            table(
                "Imported BCF topics",
                [("id", "Topic"), ("title", "Title"), ("sheet", "Sheet"), ("status", "Status")],
                imported,
            )
        ],
    )


@feature(
    "docMarkup.issuePin",
    "Issue Pin",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("gridPoint", "Pin location", "A-1"),
        text("issueId", "Issue id", "PIN-001"),
        text("title", "Issue title", "Review this location"),
        text("description", "Issue description", ""),
        select(
            "priority",
            "Priority",
            [("Low", "Low"), ("Normal", "Normal"), ("High", "High")],
            "Normal",
        ),
    ],
)
def issue_pin(ctx: FeatureContext, values: dict) -> dict:
    """Pin a review issue to a real floor-plan grid coordinate and save its location with the issue metadata."""
    plan = plan_data(ctx)
    xy = point_xy(plan, parse_point(values["gridPoint"]))
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    pin = {
        "kind": "issuePin",
        "id": values["issueId"].strip(),
        "sheet": values["sheet"].strip(),
        "title": values["title"].strip(),
        "description": values["description"].strip(),
        "priority": values["priority"],
        "positionMm": list(xy),
        "status": "Open",
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if any(item.get("id") == pin["id"] for item in state["annotations"]):
        raise FeatureInputError("That issue pin id already exists.")
    state["annotations"].append(pin)
    _save_drawing(ctx, state)
    return result(
        summary={
            "issueId": pin["id"],
            "positionXMm": xy[0],
            "positionYMm": xy[1],
            "priority": pin["priority"],
        }
    )


@feature(
    "docMarkup.viewpointLink",
    "Viewpoint Link",
    part="settings",
    fields=[
        text("markupId", "Markup id", "N-1"),
        text("sheet", "Sheet number", "S-101"),
        text("gridPoint", "Model grid point", "A-1"),
        number("elevationMm", "Camera elevation", 1500, unit="mm"),
        number("azimuthDeg", "Camera azimuth", 0, unit="deg"),
        number("elevationAngleDeg", "Camera elevation angle", 30, unit="deg", min=-89, max=89),
    ],
)
def viewpoint_link(ctx: FeatureContext, values: dict) -> dict:
    """Link a drawing markup to a 3D camera position resolved from floor-plan coordinates and view angles."""
    plan = plan_data(ctx)
    xy = point_xy(plan, parse_point(values["gridPoint"]))
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    mark = next(
        (
            item
            for item in state["annotations"]
            if item.get("id") == values["markupId"] or item.get("noteId") == values["markupId"]
        ),
        None,
    )
    if mark is None:
        raise FeatureInputError("The markup id does not exist.")
    mark["viewpoint"] = {
        "positionMm": [xy[0], xy[1], values["elevationMm"]],
        "azimuthDeg": values["azimuthDeg"] % 360,
        "elevationAngleDeg": values["elevationAngleDeg"],
    }
    _save_drawing(ctx, state)
    return result(
        summary={
            "markupId": values["markupId"],
            "cameraXMm": xy[0],
            "cameraYMm": xy[1],
            "cameraZMm": values["elevationMm"],
            "azimuthDeg": values["azimuthDeg"] % 360,
        }
    )


@feature(
    "docMarkup.markupLog",
    "Markup Log",
    part="settings",
    fields=[
        text("fileName", "CSV output name", "markup-log.csv"),
        select(
            "status",
            "Status filter",
            [("all", "All"), ("Open", "Open"), ("Resolved", "Resolved")],
            "all",
        ),
    ],
)
def markup_log(ctx: FeatureContext, values: dict) -> dict:
    """Export review markups, assignments, resolution notes and timestamps to a traceable CSV audit log."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to export the markup log.")
    state = _drawing_state(ctx)
    rows = [
        item
        for item in state["annotations"]
        if values["status"] == "all" or item.get("status", "Open") == values["status"]
    ]
    path = ctx.root / "11 Exports" / Path(values["fileName"].strip() or "markup-log.csv").name
    records = [
        {
            "sheet": item.get("sheet", ""),
            "id": item.get("id", item.get("noteId", "")),
            "kind": item.get("kind", ""),
            "status": item.get("status", "Open"),
            "author": item.get("author", ""),
            "reviewer": item.get("reviewer", ""),
            "createdAt": item.get("createdAt", ""),
            "resolvedAt": item.get("resolvedAt", ""),
            "resolution": item.get("resolution", ""),
        }
        for item in rows
    ]
    write_csv(
        path,
        [
            "sheet",
            "id",
            "kind",
            "status",
            "author",
            "reviewer",
            "createdAt",
            "resolvedAt",
            "resolution",
        ],
        records,
    )
    return result(
        summary={"markupCount": len(records), "csvPath": path.relative_to(ctx.root).as_posix()},
        tables=[
            table(
                "Markup log",
                [
                    ("sheet", "Sheet"),
                    ("id", "Id"),
                    ("kind", "Type"),
                    ("status", "Status"),
                    ("reviewer", "Reviewer"),
                    ("resolution", "Resolution"),
                ],
                records,
            )
        ],
    )


@feature(
    "docMarkup.changeTracking",
    "Change Tracking",
    part="settings",
    fields=[number("limit", "Recent changes", 100, min=1, max=1000)],
)
def change_tracking(ctx: FeatureContext, values: dict) -> dict:
    """Compare the saved preview workspace's prior audit snapshot with current annotation ids and states."""
    state = _drawing_state(ctx)
    current = [
        {
            "id": row.get("id", row.get("noteId", f"{row.get('kind')}:{index}")),
            "sheet": row.get("sheet", ""),
            "kind": row.get("kind", ""),
            "status": row.get("status", "Open"),
        }
        for index, row in enumerate(state["annotations"])
    ]
    history = state.setdefault("changeSnapshots", [])
    before = {row["id"]: row for row in (history[-1]["items"] if history else [])}
    now = {row["id"]: row for row in current}
    changes = (
        [{"change": "added", **row} for key, row in now.items() if key not in before]
        + [{"change": "removed", **row} for key, row in before.items() if key not in now]
        + [
            {"change": "updated", **now[key]}
            for key in before.keys() & now.keys()
            if before[key] != now[key]
        ]
    )
    history.append({"at": datetime.now(UTC).isoformat(timespec="seconds"), "items": current})
    _save_drawing(ctx, state)
    changes = changes[-int(values["limit"]) :]
    return result(
        summary={"changeCount": len(changes), "snapshotCount": len(history)},
        tables=[
            table(
                "Markup changes",
                [
                    ("change", "Change"),
                    ("id", "Markup"),
                    ("sheet", "Sheet"),
                    ("kind", "Type"),
                    ("status", "Status"),
                ],
                changes,
            )
        ],
    )


@feature(
    "docMarkup.reviewStatus",
    "Review Status",
    part="settings",
    fields=[text("sheet", "Sheet number (blank means all)", "")],
)
def review_status(ctx: FeatureContext, values: dict) -> dict:
    """Summarize open, resolved, assigned and overdue markups by sheet from the review workspace."""
    state = _drawing_state(ctx)
    marks = [
        item
        for item in state["annotations"]
        if not values["sheet"].strip() or item.get("sheet") == values["sheet"].strip()
    ]
    rows = []
    for sheet in sorted({item.get("sheet", "") for item in marks}):
        grouped = [item for item in marks if item.get("sheet", "") == sheet]
        rows.append(
            {
                "sheet": sheet,
                "openCount": sum(item.get("status", "Open") != "Resolved" for item in grouped),
                "resolvedCount": sum(item.get("status") == "Resolved" for item in grouped),
                "assignedCount": sum(bool(item.get("reviewer")) for item in grouped),
                "overdueCount": sum(
                    bool(
                        item.get("reviewDueDate")
                        and date.fromisoformat(item["reviewDueDate"]) < date.today()
                        and item.get("status") != "Resolved"
                    )
                    for item in grouped
                ),
            }
        )
    return result(
        summary={
            "markupCount": len(marks),
            "openCount": sum(row["openCount"] for row in rows),
            "resolvedCount": sum(row["resolvedCount"] for row in rows),
        },
        tables=[
            table(
                "Review status by sheet",
                [
                    ("sheet", "Sheet"),
                    ("openCount", "Open"),
                    ("resolvedCount", "Resolved"),
                    ("assignedCount", "Assigned"),
                    ("overdueCount", "Overdue"),
                ],
                rows,
            )
        ],
    )


def _view_templates(state: dict) -> list[dict]:
    return state.setdefault(
        "viewTemplates",
        [
            {
                "name": "Structural Plan",
                "settings": {
                    "scale": 100,
                    "detail": "medium",
                    "discipline": "structure",
                    "lineweights": {},
                    "overrides": {},
                    "filters": [],
                },
                "lockedProperties": [],
            }
        ],
    )


def _view_template(state: dict, name: str) -> dict:
    found = next(
        (item for item in _view_templates(state) if item.get("name") == name.strip()), None
    )
    if found is None:
        raise FeatureInputError(f"View template {name!r} does not exist.")
    return found


@feature(
    "documentsDrawingViewTemplates.assignTemplate",
    "Assign Template",
    part="settings",
    fields=[
        text("viewName", "View name", "Level 1 framing"),
        text("templateName", "View template", "Structural Plan"),
    ],
)
def assign_template(ctx: FeatureContext, values: dict) -> dict:
    """Attach an existing view template and apply its scale, detail level and discipline settings to a placed view."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    view = next(
        (item for item in state["views"] if item.get("name") == values["viewName"].strip()), None
    )
    if view is None:
        raise FeatureInputError("Place the view before assigning a view template.")
    view["template"] = template["name"]
    for key in ("scale", "detail", "discipline"):
        if key in template["settings"]:
            view[key] = template["settings"][key]
    _save_drawing(ctx, state)
    return result(
        summary={
            "view": view["name"],
            "template": template["name"],
            "scaleDenominator": view.get("scale"),
            "discipline": view.get("discipline"),
        }
    )


@feature(
    "documentsDrawingViewTemplates.replaceTemplate",
    "Replace Template",
    part="settings",
    fields=[
        text("viewName", "View name", "Level 1 framing"),
        text("newTemplate", "Replacement template", "Structural Plan"),
        checkbox("preserveScale", "Keep current scale", True),
    ],
)
def replace_template(ctx: FeatureContext, values: dict) -> dict:
    """Replace the template on a view while optionally preserving its current scale."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["newTemplate"])
    view = next(
        (item for item in state["views"] if item.get("name") == values["viewName"].strip()), None
    )
    if view is None:
        raise FeatureInputError("Place the target view before replacing its template.")
    previous_scale = view.get("scale")
    view["template"] = template["name"]
    view["detail"] = template["settings"].get("detail", view.get("detail", "medium"))
    view["discipline"] = template["settings"].get("discipline", view.get("discipline", "structure"))
    view["scale"] = (
        previous_scale
        if values["preserveScale"]
        else template["settings"].get("scale", previous_scale)
    )
    _save_drawing(ctx, state)
    return result(
        summary={
            "view": view["name"],
            "previousScale": previous_scale,
            "currentScale": view.get("scale"),
            "template": template["name"],
        }
    )


@feature(
    "documentsDrawingViewTemplates.detachTemplate",
    "Detach Template",
    part="settings",
    fields=[text("viewName", "View name", "Level 1 framing")],
)
def detach_template(ctx: FeatureContext, values: dict) -> dict:
    """Detach a view template while retaining the view's last applied settings as local properties."""
    state = _drawing_state(ctx)
    view = next(
        (item for item in state["views"] if item.get("name") == values["viewName"].strip()), None
    )
    if view is None or not view.get("template"):
        raise FeatureInputError("The selected view has no assigned template.")
    previous = view.pop("template")
    view["detachedFrom"] = previous
    _save_drawing(ctx, state)
    return result(
        summary={
            "view": view["name"],
            "detachedTemplate": previous,
            "localScale": view.get("scale"),
            "localDetail": view.get("detail"),
        }
    )


@feature(
    "documentsDrawingViewTemplates.updateViews",
    "Update Views",
    part="settings",
    fields=[
        text("templateName", "Template name", "Structural Plan"),
        checkbox("updateScale", "Push scale to attached views", True),
        checkbox("updateGraphics", "Push graphic settings", True),
    ],
)
def update_views(ctx: FeatureContext, values: dict) -> dict:
    """Push selected view-template properties to every view currently using that template."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    views = [view for view in state["views"] if view.get("template") == template["name"]]
    for view in views:
        if values["updateScale"] and "scale" in template["settings"]:
            view["scale"] = template["settings"]["scale"]
        if values["updateGraphics"]:
            for key in ("detail", "discipline", "lineweights", "overrides", "filters"):
                if key in template["settings"]:
                    view[key] = template["settings"][key]
    _save_drawing(ctx, state)
    return result(
        summary={
            "updatedViewCount": len(views),
            "template": template["name"],
            "scaleUpdated": values["updateScale"],
            "graphicsUpdated": values["updateGraphics"],
        },
        tables=[
            table(
                "Updated views",
                [
                    ("name", "View"),
                    ("sheet", "Sheet"),
                    ("scale", "Scale"),
                    ("detail", "Detail"),
                    ("discipline", "Discipline"),
                ],
                views,
            )
        ],
    )


@feature(
    "documentsDrawingViewTemplates.templateRules",
    "Template Rules",
    part="settings",
    fields=[
        text("ruleName", "Rule name", "Framing plans"),
        select(
            "discipline",
            "Discipline",
            [("structure", "Structural"), ("architecture", "Architectural"), ("mep", "MEP")],
            "structure",
        ),
        text("storyContains", "Story name contains", ""),
        text("templateName", "Template", "Structural Plan"),
        checkbox("enabled", "Rule enabled", True),
    ],
)
def template_rules(ctx: FeatureContext, values: dict) -> dict:
    """Save an automatic view-template rule using discipline and story-name predicates."""
    state = _drawing_state(ctx)
    _view_template(state, values["templateName"])
    rule = {
        "name": values["ruleName"].strip(),
        "discipline": values["discipline"],
        "storyContains": values["storyContains"].strip(),
        "template": values["templateName"].strip(),
        "enabled": values["enabled"],
    }
    if not rule["name"]:
        raise FeatureInputError("Give the assignment rule a name.")
    rules = state.setdefault("templateRules", [])
    rules[:] = [item for item in rules if item.get("name") != rule["name"]]
    rules.append(rule)
    _save_drawing(ctx, state)
    return result(
        summary={"rule": rule["name"], "enabled": rule["enabled"], "ruleCount": len(rules)},
        tables=[
            table(
                "View template rules",
                [
                    ("name", "Rule"),
                    ("discipline", "Discipline"),
                    ("storyContains", "Story test"),
                    ("template", "Template"),
                    ("enabled", "Enabled"),
                ],
                rules,
            )
        ],
    )


@feature(
    "documentsDrawingViewTemplates.categoryOverride",
    "Category Override",
    part="settings",
    fields=[
        text("templateName", "Template name", "Structural Plan"),
        select(
            "category",
            "Model category",
            [
                ("column", "Columns"),
                ("beam", "Beams"),
                ("wall", "Walls"),
                ("slab", "Slabs"),
                ("footing", "Footings"),
            ],
            "beam",
        ),
        select(
            "projection",
            "Projection line display",
            [("visible", "Visible"), ("halftone", "Halftone"), ("hidden", "Hidden")],
            "visible",
        ),
        select(
            "cut",
            "Cut line display",
            [("visible", "Visible"), ("halftone", "Halftone"), ("hidden", "Hidden")],
            "visible",
        ),
    ],
)
def category_override(ctx: FeatureContext, values: dict) -> dict:
    """Set category-specific projection and cut display overrides on a saved view template."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    override = {"projection": values["projection"], "cut": values["cut"]}
    template["settings"].setdefault("overrides", {})[values["category"]] = override
    _save_drawing(ctx, state)
    return result(
        summary={
            "template": template["name"],
            "category": values["category"],
            "projection": override["projection"],
            "cut": override["cut"],
        }
    )


@feature(
    "documentsDrawingViewTemplates.viewFilter",
    "View Filter",
    part="settings",
    fields=[
        text("viewName", "View name", "Level 1 framing"),
        select(
            "property",
            "Property",
            [("category", "Category"), ("type", "Object type"), ("story", "Story")],
            "category",
        ),
        text("equals", "Equals", "beam"),
        select(
            "effect",
            "Graphic effect",
            [("hide", "Hide"), ("halftone", "Halftone"), ("highlight", "Highlight")],
            "highlight",
        ),
    ],
)
def view_filter(ctx: FeatureContext, values: dict) -> dict:
    """Filter current plan members for a view and persist the matched member set and display effect."""
    rows = member_rows(plan_data(ctx))
    matched = [
        row["id"]
        for row in rows
        if str(row.get(values["property"], "")).casefold() == values["equals"].strip().casefold()
    ]
    state = _drawing_state(ctx)
    record = {
        "view": values["viewName"].strip(),
        "property": values["property"],
        "equals": values["equals"].strip(),
        "effect": values["effect"],
        "memberIds": matched,
    }
    state.setdefault("viewFilters", []).append(record)
    _save_drawing(ctx, state)
    return result(
        summary={"matchingMemberCount": len(matched), "effect": record["effect"]},
        tables=[
            table(
                "View filter matches",
                [("memberId", "Member")],
                [{"memberId": member_id} for member_id in matched],
            )
        ],
    )


@feature(
    "documentsDrawingViewTemplates.halftoneElements",
    "Halftone Elements",
    part="settings",
    fields=[
        text("viewName", "View name", "Level 1 framing"),
        text("memberIds", "Member ids (comma-separated)", "C1,C2"),
        number("halftonePercent", "Halftone strength", 60, unit="%", min=1, max=100),
    ],
)
def halftone_elements(ctx: FeatureContext, values: dict) -> dict:
    """Halftone selected plan members and report the members found in the chosen drawing view."""
    available = {row["id"] for row in member_rows(plan_data(ctx))}
    selected = {part.strip() for part in values["memberIds"].split(",") if part.strip()}
    missing = selected - available
    if missing:
        raise FeatureInputError(f"Unknown plan member id(s): {', '.join(sorted(missing))}.")
    state = _drawing_state(ctx)
    for view in state["views"]:
        if view.get("name") == values["viewName"].strip():
            view.setdefault("halftone", {}).update(
                {member_id: values["halftonePercent"] for member_id in selected}
            )
    state.setdefault("halftoneRules", []).append(
        {
            "view": values["viewName"].strip(),
            "memberIds": sorted(selected),
            "strengthPercent": values["halftonePercent"],
        }
    )
    _save_drawing(ctx, state)
    return result(
        summary={
            "halftonedMemberCount": len(selected),
            "strengthPercent": values["halftonePercent"],
        },
        tables=[
            table(
                "Halftoned members",
                [("memberId", "Member")],
                [{"memberId": member_id} for member_id in sorted(selected)],
            )
        ],
    )


@feature(
    "documentsDrawingViewTemplates.lineWeight",
    "Line Weight",
    part="settings",
    fields=[
        text("templateName", "Template name", "Structural Plan"),
        select(
            "category",
            "Category",
            [
                ("column", "Columns"),
                ("beam", "Beams"),
                ("wall", "Walls"),
                ("slab", "Slabs"),
                ("grid", "Grids"),
            ],
            "beam",
        ),
        number("weightMm", "Line weight", 0.35, unit="mm", min=0.05, max=2),
        select(
            "pattern",
            "Line pattern",
            [("continuous", "Continuous"), ("dashed", "Dashed"), ("center", "Center")],
            "continuous",
        ),
    ],
)
def template_line_weight(ctx: FeatureContext, values: dict) -> dict:
    """Set a printable category lineweight and linetype in the selected view template."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    template["settings"].setdefault("lineweights", {})[values["category"]] = {
        "weightMm": values["weightMm"],
        "pattern": values["pattern"],
    }
    _save_drawing(ctx, state)
    return result(
        summary={
            "template": template["name"],
            "category": values["category"],
            "weightMm": values["weightMm"],
            "pattern": values["pattern"],
        }
    )


@feature(
    "documentsDrawingViewTemplates.duplicateTemplate",
    "Duplicate Template",
    part="settings",
    fields=[
        text("sourceName", "Source template", "Structural Plan"),
        text("newName", "New template name", "Framing Plan"),
        checkbox("copyFilters", "Copy filter rules", True),
    ],
)
def duplicate_view_template(ctx: FeatureContext, values: dict) -> dict:
    """Duplicate a view template's scales, graphics and optionally filters under a unique new name."""
    state = _drawing_state(ctx)
    source = _view_template(state, values["sourceName"])
    if any(item.get("name") == values["newName"].strip() for item in _view_templates(state)):
        raise FeatureInputError("A view template with that name already exists.")
    duplicate = json.loads(json.dumps(source))
    duplicate["name"] = values["newName"].strip()
    if not values["copyFilters"]:
        duplicate["settings"]["filters"] = []
    duplicate["lockedProperties"] = []
    _view_templates(state).append(duplicate)
    _save_drawing(ctx, state)
    return result(
        summary={
            "source": source["name"],
            "duplicate": duplicate["name"],
            "templateCount": len(_view_templates(state)),
        }
    )


@feature(
    "documentsDrawingViewTemplates.renameTemplate",
    "Rename Template",
    part="settings",
    fields=[
        text("currentName", "Current name", "Structural Plan"),
        text("newName", "New name", "Framing Plan"),
    ],
)
def rename_view_template(ctx: FeatureContext, values: dict) -> dict:
    """Rename a view template and update every view and rule that references its previous name."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["currentName"])
    new_name = values["newName"].strip()
    if not new_name or any(item.get("name") == new_name for item in _view_templates(state)):
        raise FeatureInputError("Choose an unused template name.")
    old_name = template["name"]
    template["name"] = new_name
    for view in state["views"]:
        if view.get("template") == old_name:
            view["template"] = new_name
    for rule in state.get("templateRules", []):
        if rule.get("template") == old_name:
            rule["template"] = new_name
    _save_drawing(ctx, state)
    return result(
        summary={
            "oldName": old_name,
            "newName": new_name,
            "updatedViewCount": sum(view.get("template") == new_name for view in state["views"]),
        }
    )


@feature(
    "documentsDrawingViewTemplates.deleteTemplate",
    "Delete Template",
    part="settings",
    fields=[
        text("templateName", "Template name", "Structural Plan"),
        checkbox("detachViews", "Detach views using it", False),
    ],
)
def delete_view_template(ctx: FeatureContext, values: dict) -> dict:
    """Delete an unused view template or detach its views when explicitly requested."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    uses = [view for view in state["views"] if view.get("template") == template["name"]]
    if uses and not values["detachViews"]:
        raise FeatureInputError(
            f"Template is assigned to {len(uses)} view(s); detach them before deletion."
        )
    for view in uses:
        view.pop("template", None)
        view["detachedFrom"] = template["name"]
    _view_templates(state).remove(template)
    state["templateRules"] = [
        rule for rule in state.get("templateRules", []) if rule.get("template") != template["name"]
    ]
    _save_drawing(ctx, state)
    return result(
        summary={
            "deletedTemplate": template["name"],
            "detachedViewCount": len(uses),
            "remainingTemplateCount": len(_view_templates(state)),
        }
    )


@feature(
    "documentsDrawingViewTemplates.importTemplate",
    "Import Template",
    part="settings",
    fields=[
        text(
            "sourcePath",
            "Project-relative template JSON",
            "11 Exports/documents/view-template.json",
        ),
        text("newName", "Imported template name", "Imported Plan"),
    ],
)
def import_view_template(ctx: FeatureContext, values: dict) -> dict:
    """Import a validated view-template JSON file from inside the project and register it under a new name."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to import a view template.")
    path = (ctx.root / values["sourcePath"]).resolve()
    try:
        path.relative_to(ctx.root.resolve())
        template = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise FeatureInputError(
            "The template file must be readable and inside the project."
        ) from exc
    if not isinstance(template, dict) or not isinstance(template.get("settings"), dict):
        raise FeatureInputError("Template JSON must contain a settings object.")
    state = _drawing_state(ctx)
    if any(item.get("name") == values["newName"].strip() for item in _view_templates(state)):
        raise FeatureInputError("A view template with that name already exists.")
    template.update(name=values["newName"].strip(), lockedProperties=[])
    _view_templates(state).append(template)
    _save_drawing(ctx, state)
    return result(
        summary={
            "importedTemplate": template["name"],
            "source": path.relative_to(ctx.root).as_posix(),
            "templateCount": len(_view_templates(state)),
        }
    )


@feature(
    "documentsDrawingViewTemplates.scaleSetting",
    "Scale Setting",
    part="settings",
    fields=[
        text("templateName", "Template name", "Structural Plan"),
        number("scaleDenominator", "Scale denominator", 100, min=1),
        select(
            "representation",
            "Representation",
            [("model", "Model detail"), ("symbolic", "Symbolic"), ("mixed", "Mixed")],
            "mixed",
        ),
    ],
)
def view_scale_setting(ctx: FeatureContext, values: dict) -> dict:
    """Set a template's drawing scale and representation mode, updating attached views that inherit scale."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    template["settings"].update(
        scale=values["scaleDenominator"], representation=values["representation"]
    )
    changed = 0
    for view in state["views"]:
        if view.get("template") == template["name"] and view.get("scaleFromTemplate", True):
            view["scale"] = values["scaleDenominator"]
            changed += 1
    _save_drawing(ctx, state)
    return result(
        summary={
            "template": template["name"],
            "scaleDenominator": values["scaleDenominator"],
            "updatedViews": changed,
            "representation": values["representation"],
        }
    )


@feature(
    "documentsDrawingViewTemplates.detailLevel",
    "Detail Level",
    part="settings",
    fields=[
        text("templateName", "Template name", "Structural Plan"),
        select(
            "detail",
            "Geometry detail",
            [("coarse", "Coarse"), ("medium", "Medium"), ("fine", "Fine")],
            "medium",
        ),
        checkbox("hideAnalytical", "Hide analytical lines", False),
    ],
)
def detail_level(ctx: FeatureContext, values: dict) -> dict:
    """Set model detail level and analytical-line visibility on a view template and its assigned views."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    template["settings"].update(detail=values["detail"], hideAnalytical=values["hideAnalytical"])
    attached = [view for view in state["views"] if view.get("template") == template["name"]]
    for view in attached:
        view["detail"] = values["detail"]
        view["hideAnalytical"] = values["hideAnalytical"]
    _save_drawing(ctx, state)
    return result(
        summary={
            "detail": values["detail"],
            "hideAnalytical": values["hideAnalytical"],
            "affectedViewCount": len(attached),
        }
    )


@feature(
    "documentsDrawingViewTemplates.disciplineSetting",
    "Discipline Setting",
    part="settings",
    fields=[
        text("templateName", "Template name", "Structural Plan"),
        select(
            "discipline",
            "Discipline",
            [
                ("structure", "Structural"),
                ("architecture", "Architectural"),
                ("mep", "MEP"),
                ("coordination", "Coordination"),
            ],
            "structure",
        ),
        checkbox("showLinked", "Show linked model categories", True),
    ],
)
def discipline_setting(ctx: FeatureContext, values: dict) -> dict:
    """Set a template's discipline visibility defaults and update views attached to the template."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    template["settings"].update(discipline=values["discipline"], showLinked=values["showLinked"])
    views = [view for view in state["views"] if view.get("template") == template["name"]]
    for view in views:
        view["discipline"] = values["discipline"]
        view["showLinked"] = values["showLinked"]
    _save_drawing(ctx, state)
    return result(
        summary={
            "discipline": values["discipline"],
            "linkedCategoriesVisible": values["showLinked"],
            "updatedViewCount": len(views),
        }
    )


@feature(
    "documentsDrawingViewTemplates.createViewFilter",
    "Create View Filter",
    part="settings",
    fields=[
        text("templateName", "Template name", "Structural Plan"),
        text("filterName", "Filter name", "Concrete beams"),
        select(
            "property",
            "Property",
            [("category", "Category"), ("type", "Object type"), ("story", "Story")],
            "type",
        ),
        text("matchText", "Contains text", "C"),
        select(
            "effect",
            "Effect",
            [("hide", "Hide"), ("halftone", "Halftone"), ("highlight", "Highlight")],
            "highlight",
        ),
    ],
)
def create_view_filter(ctx: FeatureContext, values: dict) -> dict:
    """Create a named substring filter in a view template and list the current members it matches."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    if not values["filterName"].strip():
        raise FeatureInputError("Give the filter a name.")
    rows = member_rows(plan_data(ctx))
    matches = [
        row["id"]
        for row in rows
        if values["matchText"].casefold() in str(row.get(values["property"], "")).casefold()
    ]
    record = {
        "name": values["filterName"].strip(),
        "property": values["property"],
        "contains": values["matchText"],
        "effect": values["effect"],
        "matchedIds": matches,
    }
    template["settings"].setdefault("filters", []).append(record)
    _save_drawing(ctx, state)
    return result(
        summary={
            "filter": record["name"],
            "currentMatchCount": len(matches),
            "effect": record["effect"],
        },
        tables=[
            table(
                "Current filter matches",
                [("memberId", "Member")],
                [{"memberId": mid} for mid in matches],
            )
        ],
    )


@feature(
    "documentsDrawingViewTemplates.ruleConditions",
    "Rule Conditions",
    part="settings",
    fields=[
        text("templateName", "Template name", "Structural Plan"),
        text("filterName", "Filter name", "Concrete beams"),
        select(
            "operator",
            "Condition",
            [
                ("equals", "Equals"),
                ("contains", "Contains"),
                ("notEquals", "Does not equal"),
                ("startsWith", "Starts with"),
            ],
            "contains",
        ),
        text("value", "Comparison value", "C"),
    ],
)
def rule_conditions(ctx: FeatureContext, values: dict) -> dict:
    """Edit the property comparison operator and value on an existing template filter rule."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    rule = next(
        (
            item
            for item in template["settings"].get("filters", [])
            if item.get("name") == values["filterName"].strip()
        ),
        None,
    )
    if rule is None:
        raise FeatureInputError("Create the named view filter before editing its condition.")
    rule["operator"], rule["value"] = values["operator"], values["value"]
    _save_drawing(ctx, state)
    return result(
        summary={
            "filter": rule["name"],
            "property": rule["property"],
            "operator": rule["operator"],
            "value": rule["value"],
        }
    )


@feature(
    "documentsDrawingViewTemplates.filterColors",
    "Filter Colors",
    part="settings",
    fields=[
        text("templateName", "Template name", "Structural Plan"),
        text("filterName", "Filter name", "Concrete beams"),
        text("colour", "Colour name or hex", "#FF6B35"),
        text("fillPattern", "Fill pattern", "solid"),
    ],
)
def filter_colors(ctx: FeatureContext, values: dict) -> dict:
    """Apply a validated display colour and fill pattern to an existing view filter."""
    color = values["colour"].strip()
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}|[A-Za-z ]{1,24}", color):
        raise FeatureInputError("Use a six-digit hex colour or a plain colour name.")
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    rule = next(
        (
            item
            for item in template["settings"].get("filters", [])
            if item.get("name") == values["filterName"].strip()
        ),
        None,
    )
    if rule is None:
        raise FeatureInputError("Create the named filter before assigning its colour.")
    rule["colour"], rule["fillPattern"] = color, values["fillPattern"].strip()
    _save_drawing(ctx, state)
    return result(
        summary={"filter": rule["name"], "colour": color, "fillPattern": rule["fillPattern"]}
    )


@feature(
    "documentsDrawingViewTemplates.auditTemplates",
    "Audit Templates",
    part="settings",
    fields=[checkbox("checkUnused", "Report unused templates", True)],
)
def audit_templates(ctx: FeatureContext, values: dict) -> dict:
    """Audit template names, locked properties, filter definitions and assigned-view references."""
    state = _drawing_state(ctx)
    templates = _view_templates(state)
    names = [template.get("name", "") for template in templates]
    issues = []
    for template in templates:
        if not template.get("name"):
            issues.append({"template": "(unnamed)", "issue": "missing name"})
        if not isinstance(template.get("settings"), dict):
            issues.append(
                {"template": template.get("name", ""), "issue": "settings is not an object"}
            )
        for rule in template.get("settings", {}).get("filters", []):
            if not rule.get("property") or "contains" not in rule:
                issues.append(
                    {
                        "template": template["name"],
                        "issue": f"incomplete filter {rule.get('name', '')}",
                    }
                )
        if values["checkUnused"] and not any(
            view.get("template") == template.get("name") for view in state["views"]
        ):
            issues.append({"template": template.get("name", ""), "issue": "unused template"})
    for name in sorted({item for item in names if names.count(item) > 1}):
        issues.append({"template": name, "issue": "duplicate name"})
    dangling = {view.get("template") for view in state["views"] if view.get("template")} - set(
        names
    )
    issues.extend(
        {"template": name, "issue": "view references missing template"} for name in sorted(dangling)
    )
    return result(
        summary={"templateCount": len(templates), "auditIssueCount": len(issues)},
        tables=[
            table("View-template audit", [("template", "Template"), ("issue", "Finding")], issues)
        ],
    )


@feature(
    "documentsDrawingViewTemplates.templateMapping",
    "Template Mapping",
    part="settings",
    fields=[
        text("templateName", "Internal template", "Structural Plan"),
        text("externalStandard", "External CAD standard", "Office-Structural-Plan"),
        text("mappingNote", "Mapping note", ""),
    ],
)
def template_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Map a project view template to an external CAD standard label for controlled exchange."""
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    template["externalMapping"] = {
        "standard": values["externalStandard"].strip(),
        "note": values["mappingNote"].strip(),
        "updatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _save_drawing(ctx, state)
    return result(
        summary={
            "template": template["name"],
            "externalStandard": template["externalMapping"]["standard"],
        }
    )


@feature(
    "documentsDrawingViewTemplates.lockViewProperties",
    "Lock View Properties",
    part="settings",
    fields=[
        text("templateName", "Template name", "Structural Plan"),
        text("properties", "Properties to lock (comma-separated)", "scale,discipline,detail"),
    ],
)
def lock_view_properties(ctx: FeatureContext, values: dict) -> dict:
    """Lock selected template-controlled properties on all views assigned to a named template."""
    allowed = {"scale", "discipline", "detail", "lineweights", "overrides", "filters"}
    properties = [item.strip() for item in values["properties"].split(",") if item.strip()]
    if not properties or set(properties) - allowed:
        raise FeatureInputError(
            "Lock properties from scale, discipline, detail, lineweights, overrides or filters."
        )
    state = _drawing_state(ctx)
    template = _view_template(state, values["templateName"])
    template["lockedProperties"] = sorted(
        set(template.get("lockedProperties", [])) | set(properties)
    )
    for view in state["views"]:
        if view.get("template") == template["name"]:
            view["lockedProperties"] = template["lockedProperties"]
    _save_drawing(ctx, state)
    return result(
        summary={
            "template": template["name"],
            "lockedProperties": template["lockedProperties"],
            "affectedViewCount": sum(
                view.get("template") == template["name"] for view in state["views"]
            ),
        }
    )


@feature(
    "documentsDrawingAnnotation.linearDimension",
    "Linear Dimension",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("first", "First grid point", "A-1"),
        text("second", "Second grid point", "B-1"),
        select(
            "axis",
            "Dimension axis",
            [("aligned", "Aligned"), ("horizontal", "Horizontal"), ("vertical", "Vertical")],
            "aligned",
        ),
    ],
)
def linear_dimension(ctx: FeatureContext, values: dict) -> dict:
    """Place a linear dimension using grid-resolved plan points and return its measured SI distance."""
    plan = plan_data(ctx)
    p0, p1 = (
        point_xy(plan, parse_point(values["first"])),
        point_xy(plan, parse_point(values["second"])),
    )
    if values["axis"] == "horizontal":
        distance = abs(p1[0] - p0[0])
    elif values["axis"] == "vertical":
        distance = abs(p1[1] - p0[1])
    else:
        distance = math.dist(p0, p1)
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    state["annotations"].append(
        {
            "kind": "linearDimension",
            "sheet": values["sheet"].strip(),
            "first": values["first"],
            "second": values["second"],
            "axis": values["axis"],
            "distanceMm": distance,
        }
    )
    _save_drawing(ctx, state)
    return result(
        summary={"dimensionMm": distance, "dimensionM": distance / 1000, "axis": values["axis"]}
    )


@feature(
    "documentsDrawingAnnotation.angularDimension",
    "Angular Dimension",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("vertex", "Angle vertex grid point", "A-1"),
        text("rayA", "First ray grid point", "B-1"),
        text("rayB", "Second ray grid point", "A-2"),
    ],
)
def angular_dimension(ctx: FeatureContext, values: dict) -> dict:
    """Measure the included angle between two non-zero plan vectors resolved from floor-plan grid points."""
    plan = plan_data(ctx)
    origin = point_xy(plan, parse_point(values["vertex"]))
    a, b = point_xy(plan, parse_point(values["rayA"])), point_xy(plan, parse_point(values["rayB"]))
    u, v = (a[0] - origin[0], a[1] - origin[1]), (b[0] - origin[0], b[1] - origin[1])
    denominator = math.hypot(*u) * math.hypot(*v)
    if denominator == 0:
        raise FeatureInputError("Both angle rays must have non-zero length.")
    angle = math.degrees(math.acos(max(-1, min(1, (u[0] * v[0] + u[1] * v[1]) / denominator))))
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    state["annotations"].append(
        {
            "kind": "angularDimension",
            "sheet": values["sheet"].strip(),
            "vertexMm": list(origin),
            "angleDeg": angle,
        }
    )
    _save_drawing(ctx, state)
    return result(summary={"angleDeg": angle, "angleRad": math.radians(angle)})


@feature(
    "documentsDrawingAnnotation.radialDimension",
    "Radial Dimension",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        number("centerXmm", "Arc centre X", 0, unit="mm"),
        number("centerYmm", "Arc centre Y", 0, unit="mm"),
        number("edgeXmm", "Arc edge X", 100, unit="mm"),
        number("edgeYmm", "Arc edge Y", 0, unit="mm"),
        select("measure", "Dimension", [("radius", "Radius"), ("diameter", "Diameter")], "radius"),
    ],
)
def radial_dimension(ctx: FeatureContext, values: dict) -> dict:
    """Place a radial annotation and calculate radius, diameter and circular arc perimeter from its centre and edge."""
    radius = math.dist(
        (values["centerXmm"], values["centerYmm"]), (values["edgeXmm"], values["edgeYmm"])
    )
    if radius <= 0:
        raise FeatureInputError("Arc centre and edge must not coincide.")
    amount = radius if values["measure"] == "radius" else 2 * radius
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    state["annotations"].append(
        {
            "kind": "radialDimension",
            "sheet": values["sheet"].strip(),
            "radiusMm": radius,
            "measure": values["measure"],
            "valueMm": amount,
        }
    )
    _save_drawing(ctx, state)
    return result(
        summary={
            "radiusMm": radius,
            "diameterMm": 2 * radius,
            "dimensionMm": amount,
            "circumferenceMm": 2 * math.pi * radius,
        }
    )


@feature(
    "documentsDrawingAnnotation.baselineDimension",
    "Baseline Dimension",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("origin", "Baseline origin", "A-1"),
        text("targets", "Target grid points (semicolon-separated)", "B-1;C-1"),
    ],
)
def baseline_dimension(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a series of baseline ordinates from one grid origin to several measured grid points."""
    plan = plan_data(ctx)
    origin = point_xy(plan, parse_point(values["origin"]))
    targets = [
        point_xy(plan, parse_point(point))
        for point in values["targets"].split(";")
        if point.strip()
    ]
    if not targets:
        raise FeatureInputError("Enter at least one target grid point.")
    rows = [
        {
            "target": reference.strip(),
            "xOffsetMm": target[0] - origin[0],
            "yOffsetMm": target[1] - origin[1],
            "distanceMm": math.dist(origin, target),
        }
        for reference, target in zip(
            [p for p in values["targets"].split(";") if p.strip()], targets, strict=True
        )
    ]
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    state["annotations"].append(
        {
            "kind": "baselineDimension",
            "sheet": values["sheet"].strip(),
            "originMm": list(origin),
            "ordinates": rows,
        }
    )
    _save_drawing(ctx, state)
    return result(
        summary={
            "ordinateCount": len(rows),
            "maximumDistanceM": max(row["distanceMm"] for row in rows) / 1000,
        },
        tables=[
            table(
                "Baseline dimensions",
                [
                    ("target", "Target grid"),
                    ("xOffsetMm", "X offset", "mm"),
                    ("yOffsetMm", "Y offset", "mm"),
                    ("distanceMm", "True distance", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsDrawingAnnotation.elementTag",
    "Element Tag",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("memberId", "Member id", "B1"),
        text("displayFields", "Tag fields (comma-separated)", "mark,type,story"),
    ],
)
def element_tag(ctx: FeatureContext, values: dict) -> dict:
    """Tag a plan member with requested actual member properties and its resolved geometric endpoints."""
    plan = plan_data(ctx)
    row = next(
        (item for item in member_rows(plan) if item["id"] == values["memberId"].strip()), None
    )
    if row is None:
        raise FeatureInputError("The member id is not in the current floor plan.")
    keys = [item.strip() for item in values["displayFields"].split(",") if item.strip()]
    if not keys or set(keys) - row.keys():
        raise FeatureInputError(
            "Choose available member fields: " + ", ".join(sorted(row.keys())) + "."
        )
    tag_data = {key: row[key] for key in keys}
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    state["annotations"].append(
        {
            "kind": "elementTag",
            "sheet": values["sheet"].strip(),
            "memberId": row["id"],
            "values": tag_data,
        }
    )
    _save_drawing(ctx, state)
    return result(
        summary={"memberId": row["id"], "tagFieldCount": len(tag_data)},
        tables=[
            table(
                "Element tag values",
                [("field", "Field"), ("value", "Value")],
                [{"field": key, "value": value} for key, value in tag_data.items()],
            )
        ],
    )


@feature(
    "documentsDrawingAnnotation.materialTag",
    "Material Tag",
    part="settings",
    fields=[text("sheet", "Sheet number", "S-101"), text("memberId", "Member id", "B1")],
)
def material_tag(ctx: FeatureContext, values: dict) -> dict:
    """Resolve a member's object type and material assignment from project libraries and place a material tag."""
    plan = plan_data(ctx)
    member = next(
        (
            item
            for group in ("columns", "beams", "walls", "slabs", "footings")
            for item in plan.get(group, [])
            if item["id"] == values["memberId"].strip()
        ),
        None,
    )
    if member is None:
        raise FeatureInputError("The member id is not in the floor plan.")
    objects = (ctx.raw("objects") or {}).get("objects", [])
    object_type = next((item for item in objects if item.get("id") == member.get("type")), None)
    if object_type is None:
        raise FeatureInputError("The member's object type is missing from the object library.")
    material_id = object_type.get("material") or object_type.get("materialId")
    if not material_id:
        raise FeatureInputError("The member's object type has no material assignment to tag.")
    materials = (ctx.raw("materials") or {}).get("materials", [])
    material = next((item for item in materials if item.get("id") == material_id), None)
    if material is None:
        raise FeatureInputError(
            "The assigned material is missing from the project material library."
        )
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    record = {
        "kind": "materialTag",
        "sheet": values["sheet"].strip(),
        "memberId": member["id"],
        "objectType": object_type["id"],
        "materialId": material["id"],
        "materialName": material.get("name", material["id"]),
        "grade": material.get("grade"),
    }
    state["annotations"].append(record)
    _save_drawing(ctx, state)
    return result(
        summary={
            "memberId": member["id"],
            "materialId": material["id"],
            "materialName": record["materialName"],
            "grade": record["grade"],
        }
    )


@feature(
    "documentsDrawingAnnotation.keynote",
    "Keynote",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("memberId", "Member id", "B1"),
        text("key", "Keynote code", "S-001"),
    ],
)
def keynote(ctx: FeatureContext, values: dict) -> dict:
    """Attach an existing library keynote to a plan member and store the code and specification text."""
    library_path = Path(__file__).resolve().parents[1] / "library" / "keynotes.json"
    try:
        keynotes = json.loads(library_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FeatureInputError("The shipped keynote library is unavailable or invalid.") from exc
    key = values["key"].strip()
    if key not in keynotes:
        raise FeatureInputError(f"Keynote {key!r} is not in the keynote library.")
    plan_ids = {row["id"] for row in member_rows(plan_data(ctx))}
    if values["memberId"].strip() not in plan_ids:
        raise FeatureInputError("Choose an existing floor-plan member for the keynote.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    mark = {
        "kind": "keynote",
        "sheet": values["sheet"].strip(),
        "memberId": values["memberId"].strip(),
        "key": key,
        "text": keynotes[key],
    }
    state["annotations"].append(mark)
    _save_drawing(ctx, state)
    return result(summary={"key": key, "memberId": mark["memberId"], "keynoteText": mark["text"]})


@feature(
    "documentsDrawingAnnotation.renumberTags",
    "Renumber Tags",
    part="settings",
    fields=[
        text("sheet", "Sheet number (blank means all)", ""),
        text("prefix", "Tag prefix", "S"),
        number("start", "First number", 1, min=1),
        number("step", "Increment", 1, min=1),
    ],
)
def renumber_tags(ctx: FeatureContext, values: dict) -> dict:
    """Renumber element and keynote tags deterministically in drawing order without altering member ids."""
    state = _drawing_state(ctx)
    targets = [
        mark
        for mark in state["annotations"]
        if mark.get("kind") in ("elementTag", "keynote")
        and (not values["sheet"].strip() or mark.get("sheet") == values["sheet"].strip())
    ]
    targets.sort(
        key=lambda mark: (mark.get("sheet", ""), mark.get("memberId", ""), mark.get("kind", ""))
    )
    for index, mark in enumerate(targets):
        mark["tagNumber"] = (
            f"{values['prefix']}{int(values['start']) + index * int(values['step']):03d}"
        )
    _save_drawing(ctx, state)
    return result(
        summary={"renumberedTagCount": len(targets), "prefix": values["prefix"]},
        tables=[
            table(
                "Tag numbering",
                [("sheet", "Sheet"), ("memberId", "Member"), ("tagNumber", "New tag")],
                [
                    {
                        "sheet": mark.get("sheet"),
                        "memberId": mark.get("memberId"),
                        "tagNumber": mark["tagNumber"],
                    }
                    for mark in targets
                ],
            )
        ],
    )


@feature(
    "documentsDrawingAnnotation.textNote",
    "Text Note",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("text", "Note text", "Confirm site dimensions."),
        number("xMm", "Text X", 30, unit="mm"),
        number("yMm", "Text Y", 30, unit="mm"),
        number("heightMm", "Text height", 2.5, unit="mm", min=0.5),
        select(
            "case",
            "Letter case",
            [("unchanged", "As entered"), ("upper", "Uppercase"), ("sentence", "Sentence case")],
            "unchanged",
        ),
    ],
)
def annotation_text_note(ctx: FeatureContext, values: dict) -> dict:
    """Place an annotation text note with controlled case, paper position and text height."""
    content = values["text"].strip()
    if not content:
        raise FeatureInputError("Enter annotation text.")
    if values["case"] == "upper":
        content = content.upper()
    elif values["case"] == "sentence":
        content = content[:1].upper() + content[1:].lower()
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    state["annotations"].append(
        {
            "kind": "annotationText",
            "sheet": values["sheet"].strip(),
            "text": content,
            "positionMm": [values["xMm"], values["yMm"]],
            "heightMm": values["heightMm"],
        }
    )
    _save_drawing(ctx, state)
    return result(
        summary={
            "characterCount": len(content),
            "case": values["case"],
            "heightMm": values["heightMm"],
        }
    )


@feature(
    "documentsDrawingAnnotation.leader",
    "Leader",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("target", "Target grid point", "A-1"),
        number("textXmm", "Text X", 150, unit="mm"),
        number("textYmm", "Text Y", 100, unit="mm"),
        text("label", "Leader text", "See structural note"),
    ],
)
def annotation_leader(ctx: FeatureContext, values: dict) -> dict:
    """Place an annotation leader from a paper-space text point to a floor-plan grid coordinate."""
    plan = plan_data(ctx)
    head = point_xy(plan, parse_point(values["target"]))
    tail = (values["textXmm"], values["textYmm"])
    length = math.dist(head, tail)
    if length <= 0:
        raise FeatureInputError("The leader tail and target must differ.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    state["annotations"].append(
        {
            "kind": "annotationLeader",
            "sheet": values["sheet"].strip(),
            "headMm": list(head),
            "tailMm": list(tail),
            "label": values["label"].strip(),
            "lengthMm": length,
        }
    )
    _save_drawing(ctx, state)
    return result(summary={"leaderLengthM": length / 1000, "label": values["label"].strip()})


@feature(
    "documentsDrawingAnnotation.spellCheck",
    "Spell Check",
    part="settings",
    fields=[
        text("sheet", "Sheet number (blank means all)", ""),
        text("dictionaryWords", "Allowed terms, comma-separated", "SAEngine,BNBC,ACI"),
    ],
)
def spell_check(ctx: FeatureContext, values: dict) -> dict:
    """Scan drawing notes for words outside the supplied technical vocabulary and common English words."""
    import difflib

    state = _drawing_state(ctx)
    allowed = {word.casefold() for word in values["dictionaryWords"].split(",") if word.strip()}
    allowed.update(
        {
            "the",
            "and",
            "for",
            "with",
            "see",
            "provide",
            "verify",
            "dimensions",
            "on",
            "site",
            "check",
            "detail",
            "structural",
            "plan",
            "revision",
            "of",
            "to",
            "at",
            "in",
            "by",
            "from",
            "not",
            "all",
            "as",
            "is",
            "are",
            "this",
            "that",
        }
    )
    findings = []
    for mark in state["annotations"]:
        if values["sheet"].strip() and mark.get("sheet") != values["sheet"].strip():
            continue
        content = str(mark.get("content", mark.get("text", mark.get("label", ""))))
        for word in re.findall(r"[A-Za-z]{3,}", content):
            if word.casefold() not in allowed:
                findings.append(
                    {
                        "sheet": mark.get("sheet", ""),
                        "markup": mark.get("noteId", mark.get("id", mark.get("kind", ""))),
                        "word": word,
                        "suggestion": difflib.get_close_matches(
                            word.casefold(), sorted(allowed), n=1, cutoff=0.75
                        )[0]
                        if allowed
                        else "",
                    }
                )
    return result(
        summary={
            "spellingFindingCount": len(findings),
            "checkedMarkupCount": len(state["annotations"]),
        },
        tables=[
            table(
                "Possible spelling issues",
                [
                    ("sheet", "Sheet"),
                    ("markup", "Markup"),
                    ("word", "Word"),
                    ("suggestion", "Suggestion"),
                ],
                findings,
            )
        ],
        notes=["Technical terms can be added to the comma-separated allowed-terms field."],
    )


@feature(
    "documentsDrawingAnnotation.textStyle",
    "Text Style",
    part="settings",
    fields=[
        text("styleName", "Style name", "Drawing Note"),
        text("fontFamily", "Font family", "Saira"),
        number("heightMm", "Text height", 2.5, unit="mm", min=0.5),
        checkbox("bold", "Bold text", False),
        select(
            "case",
            "Text case",
            [("asEntered", "As entered"), ("upper", "Uppercase"), ("title", "Title case")],
            "asEntered",
        ),
    ],
)
def text_style(ctx: FeatureContext, values: dict) -> dict:
    """Save a reusable annotation text style after checking its print height and font name."""
    if (
        not re.fullmatch(r"[A-Za-z0-9 _-]{1,40}", values["styleName"].strip())
        or not values["fontFamily"].strip()
    ):
        raise FeatureInputError("Use a short style name and a non-empty font family.")
    state = _drawing_state(ctx)
    style = {
        "fontFamily": values["fontFamily"].strip(),
        "heightMm": values["heightMm"],
        "bold": values["bold"],
        "case": values["case"],
    }
    state.setdefault("textStyles", {})[values["styleName"].strip()] = style
    _save_drawing(ctx, state)
    return result(
        summary={
            "styleName": values["styleName"].strip(),
            "heightMm": style["heightMm"],
            "bold": style["bold"],
            "styleCount": len(state["textStyles"]),
        }
    )


@feature(
    "documentsDrawingAnnotation.northSymbol",
    "North Symbol",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("gridPoint", "Symbol location", "A-1"),
        number("projectNorthDeg", "Project north angle", 0, unit="deg"),
        select(
            "symbol",
            "Symbol type",
            [("arrow", "Arrow"), ("circle", "Circle"), ("compass", "Compass")],
            "arrow",
        ),
    ],
)
def north_symbol(ctx: FeatureContext, values: dict) -> dict:
    """Place an orientation symbol at a grid coordinate and store project-north bearing separately from true north."""
    plan = plan_data(ctx)
    point = point_xy(plan, parse_point(values["gridPoint"]))
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    state["annotations"].append(
        {
            "kind": "northSymbol",
            "sheet": values["sheet"].strip(),
            "positionMm": list(point),
            "symbol": values["symbol"],
            "projectNorthDeg": values["projectNorthDeg"] % 360,
            "trueNorthDeg": 0,
        }
    )
    _save_drawing(ctx, state)
    return result(
        summary={
            "symbol": values["symbol"],
            "projectNorthDeg": values["projectNorthDeg"] % 360,
            "trueNorthDeg": 0,
            "xMm": point[0],
            "yMm": point[1],
        }
    )


@feature(
    "documentsDrawingAnnotation.sectionHead",
    "Section Head",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("cutStart", "Cut start grid point", "A-1"),
        text("cutEnd", "Cut end grid point", "B-1"),
        text("sectionId", "Section identifier", "A"),
        text("target", "Reference sheet", "S-201"),
    ],
)
def section_head(ctx: FeatureContext, values: dict) -> dict:
    """Create a section cut and both section-head callout references from resolved floor-plan grid points."""
    plan = plan_data(ctx)
    a, b = (
        point_xy(plan, parse_point(values["cutStart"])),
        point_xy(plan, parse_point(values["cutEnd"])),
    )
    if math.dist(a, b) <= 0:
        raise FeatureInputError("Section-head endpoints must differ.")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    head = {
        "kind": "sectionHead",
        "sheet": values["sheet"].strip(),
        "id": values["sectionId"].strip(),
        "targetSheet": values["target"].strip(),
        "cutStartMm": list(a),
        "cutEndMm": list(b),
        "headCount": 2,
    }
    state["annotations"].append(head)
    _save_drawing(ctx, state)
    return result(
        summary={
            "sectionId": head["id"],
            "cutLengthM": math.dist(a, b) / 1000,
            "headCount": 2,
            "targetSheet": head["targetSheet"],
        }
    )


@feature(
    "documentsDrawingAnnotation.elevationTarget",
    "Elevation Target",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("storyId", "Story id", "L1"),
        text("gridPoint", "Target grid point", "A-1"),
        text("datum", "Datum label", "FFL"),
    ],
)
def elevation_target(ctx: FeatureContext, values: dict) -> dict:
    """Place a spot-elevation target using the selected story's actual project elevation and a valid plan coordinate."""
    plan = plan_data(ctx)
    story = story_map(plan).get(values["storyId"].strip())
    if story is None:
        raise FeatureInputError("Choose a story id from the floor plan.")
    point = point_xy(plan, parse_point(values["gridPoint"]))
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    target = {
        "kind": "elevationTarget",
        "sheet": values["sheet"].strip(),
        "storyId": story["id"],
        "elevationMm": story["elevation"],
        "datum": values["datum"].strip(),
        "positionMm": list(point),
    }
    state["annotations"].append(target)
    _save_drawing(ctx, state)
    return result(
        summary={
            "storyId": story["id"],
            "elevationMm": story["elevation"],
            "elevationM": story["elevation"] / 1000,
            "datum": target["datum"],
        }
    )


@feature(
    "documentsDrawingAnnotation.keynoteLegend",
    "Keynote Legend",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        checkbox("includeUnused", "Include unused library keynotes", False),
    ],
)
def keynote_legend(ctx: FeatureContext, values: dict) -> dict:
    """Generate a keynote legend from notes actually used on a sheet and optionally include the full library."""
    path = Path(__file__).resolve().parents[1] / "library" / "keynotes.json"
    try:
        library = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FeatureInputError("The keynote library is unavailable.") from exc
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    used = {
        item.get("key")
        for item in state["annotations"]
        if item.get("kind") in ("keynote", "userKeynote")
        and item.get("sheet") == values["sheet"].strip()
    }
    rows = [
        {"key": key, "text": value, "used": key in used}
        for key, value in library.items()
        if values["includeUnused"] or key in used
    ]
    return result(
        summary={"legendRowCount": len(rows), "usedKeyCount": len(used)},
        tables=[
            table(
                "Keynote legend",
                [("key", "Key"), ("text", "Specification note"), ("used", "Used on sheet")],
                rows,
            )
        ],
    )


@feature(
    "documentsDrawingAnnotation.userKeynote",
    "User Keynote",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("memberId", "Member id", "B1"),
        text("key", "Custom key", "S-101"),
        text(
            "text", "Specification note", "Provide steel connection plates to the approved detail."
        ),
    ],
)
def user_keynote(ctx: FeatureContext, values: dict) -> dict:
    """Add a project-specific keynote to the keyed note library and attach it to a floor-plan member."""
    if not values["key"].strip() or not values["text"].strip():
        raise FeatureInputError("Enter both a unique keynote code and its specification text.")
    if values["memberId"].strip() not in {row["id"] for row in member_rows(plan_data(ctx))}:
        raise FeatureInputError("The keynote target member is not in the floor plan.")
    if ctx.root is None:
        raise FeatureInputError("Open a project to save a project-specific keynote.")
    path = ctx.root / "05 Floor Plan" / "user-keynotes.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError) as exc:
        raise FeatureInputError("The project keynote file is invalid JSON.") from exc
    key = values["key"].strip()
    if key in saved:
        raise FeatureInputError("That project keynote code already exists.")
    saved[key] = values["text"].strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    state["annotations"].append(
        {
            "kind": "userKeynote",
            "sheet": values["sheet"].strip(),
            "memberId": values["memberId"].strip(),
            "key": key,
            "text": saved[key],
        }
    )
    _save_drawing(ctx, state)
    return result(
        summary={
            "key": key,
            "projectKeynoteCount": len(saved),
            "memberId": values["memberId"].strip(),
        },
        notes=[f"Project note saved to {path.relative_to(ctx.root).as_posix()}."],
    )


@feature(
    "documentsDrawingAnnotation.keynoteDatabase",
    "Keynote Database",
    part="settings",
    fields=[
        text("search", "Search key or note text", ""),
        checkbox("includeProject", "Include project keynotes", True),
    ],
)
def keynote_database(ctx: FeatureContext, values: dict) -> dict:
    """Search the shipped and optional project keynote dictionaries by code or specification text."""
    path = Path(__file__).resolve().parents[1] / "library" / "keynotes.json"
    try:
        notes = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FeatureInputError("The shipped keynote database could not be read.") from exc
    if values["includeProject"] and ctx.root is not None:
        project_path = ctx.root / "05 Floor Plan" / "user-keynotes.json"
        if project_path.is_file():
            try:
                notes.update(json.loads(project_path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                raise FeatureInputError("The project keynote database could not be read.") from exc
    query = values["search"].strip().casefold()
    rows = [
        {"key": key, "text": value}
        for key, value in sorted(notes.items())
        if not query or query in key.casefold() or query in value.casefold()
    ]
    return result(
        summary={"matchingKeynoteCount": len(rows), "databaseCount": len(notes)},
        tables=[table("Keynote database", [("key", "Key"), ("text", "Specification note")], rows)],
    )


@feature(
    "documentsDrawingAnnotation.revisionCloudMark",
    "Revision Cloud Mark",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("revision", "Revision code", "A"),
        text("markupId", "Change markup id", "N-1"),
        number("clearanceMm", "Cloud margin", 3, unit="mm", min=0),
    ],
)
def revision_cloud_mark(ctx: FeatureContext, values: dict) -> dict:
    """Wrap a review markup's measured bounds in a revision cloud for the selected revision."""
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    source = next(
        (
            item
            for item in state["annotations"]
            if item.get("id") == values["markupId"] or item.get("noteId") == values["markupId"]
        ),
        None,
    )
    if source is None or "boundsMm" not in source:
        raise FeatureInputError("The selected markup must have a rectangular boundsMm extent.")
    x0, y0, x1, y1 = source["boundsMm"]
    cloud = {
        "kind": "revisionCloud",
        "sheet": values["sheet"].strip(),
        "revision": values["revision"].strip(),
        "boundsMm": [
            x0 - values["clearanceMm"],
            y0 - values["clearanceMm"],
            x1 + values["clearanceMm"],
            y1 + values["clearanceMm"],
        ],
        "sourceMarkup": values["markupId"],
    }
    state["annotations"].append(cloud)
    _save_drawing(ctx, state)
    return result(
        summary={
            "revision": cloud["revision"],
            "sourceMarkup": cloud["sourceMarkup"],
            "cloudAreaMm2": (cloud["boundsMm"][2] - cloud["boundsMm"][0])
            * (cloud["boundsMm"][3] - cloud["boundsMm"][1]),
        }
    )


@feature(
    "documentsDrawingAnnotation.deltaSymbol",
    "Delta Symbol",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("revision", "Revision code", "A"),
        number("sequence", "Delta sequence", 1, min=1),
        text("markupId", "Related markup id", "N-1"),
    ],
)
def delta_symbol(ctx: FeatureContext, values: dict) -> dict:
    """Add a revision delta identifier and link it to an existing drawing markup and revision code."""
    state = _drawing_state(ctx)
    _sheet(state, values["sheet"])
    mark = next(
        (
            item
            for item in state["annotations"]
            if item.get("id") == values["markupId"] or item.get("noteId") == values["markupId"]
        ),
        None,
    )
    if mark is None:
        raise FeatureInputError("The related markup id does not exist.")
    symbol = {
        "kind": "deltaSymbol",
        "sheet": values["sheet"].strip(),
        "revision": values["revision"].strip(),
        "sequence": int(values["sequence"]),
        "markupId": values["markupId"].strip(),
    }
    state["annotations"].append(symbol)
    _save_drawing(ctx, state)
    return result(
        summary={
            "delta": f"{symbol['revision']}{symbol['sequence']}",
            "markupId": symbol["markupId"],
        }
    )


@feature(
    "documentsDrawingAnnotation.cloudInspector",
    "Cloud Inspector",
    part="settings",
    fields=[
        text("sheet", "Sheet number (blank means all)", ""),
        text("revision", "Revision filter", ""),
    ],
)
def cloud_inspector(ctx: FeatureContext, values: dict) -> dict:
    """Inspect saved revision clouds by sheet and revision, reporting their perimeter and enclosing area."""
    state = _drawing_state(ctx)
    rows = []
    for item in state["annotations"]:
        if (
            item.get("kind") not in ("revisionCloud", "cloudMarkup")
            or (values["sheet"].strip() and item.get("sheet") != values["sheet"].strip())
            or (values["revision"].strip() and item.get("revision") != values["revision"].strip())
        ):
            continue
        bounds = item.get("boundsMm")
        if bounds and len(bounds) == 4:
            width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            rows.append(
                {
                    "sheet": item.get("sheet", ""),
                    "revision": item.get("revision", ""),
                    "kind": item["kind"],
                    "perimeterMm": 2 * (width + height),
                    "areaMm2": width * height,
                }
            )
    return result(
        summary={"cloudCount": len(rows)},
        tables=[
            table(
                "Revision clouds",
                [
                    ("sheet", "Sheet"),
                    ("revision", "Revision"),
                    ("kind", "Cloud type"),
                    ("perimeterMm", "Perimeter", "mm"),
                    ("areaMm2", "Area", "mm²"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsDrawingTitleBlocks.selectBlock",
    "Select Block",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        select(
            "block",
            "Title block",
            [
                ("SAEngine-A1", "SAEngine A1"),
                ("SAEngine-A2", "SAEngine A2"),
                ("SAEngine-A3", "SAEngine A3"),
                ("Office-A1", "Office A1"),
            ],
            "SAEngine-A1",
        ),
    ],
)
def select_block(ctx: FeatureContext, values: dict) -> dict:
    """Select a registered title-block family for one sheet and verify its nominal paper size."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    size = values["block"].rsplit("-", 1)[-1]
    sheet["titleBlock"] = values["block"]
    sheet["size"] = size
    _save_drawing(ctx, state)
    return result(
        summary={"sheet": sheet["number"], "titleBlock": values["block"], "paperSize": size}
    )


@feature(
    "documentsDrawingTitleBlocks.sheetSize",
    "Sheet Size",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        select(
            "size",
            "Paper size",
            [("A0", "A0"), ("A1", "A1"), ("A2", "A2"), ("A3", "A3"), ("A4", "A4")],
            "A1",
        ),
        number("customWidthMm", "Custom width", 841, unit="mm", min=100),
        number("customHeightMm", "Custom height", 594, unit="mm", min=100),
    ],
)
def titleblock_sheet_size(ctx: FeatureContext, values: dict) -> dict:
    """Set a sheet paper size and calculate its working area after the current title-block margins."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    sheet["size"] = values["size"]
    if values["size"] == "custom":
        sheet["customSizeMm"] = [values["customWidthMm"], values["customHeightMm"]]
        width, height = values["customWidthMm"], values["customHeightMm"]
    else:
        dims = {
            "A0": (1189, 841),
            "A1": (841, 594),
            "A2": (594, 420),
            "A3": (420, 297),
            "A4": (297, 210),
        }
        width, height = dims[values["size"]]
    margins = sheet.get("marginsMm", [15, 15, 15, 15])
    usable = [width - margins[0] - margins[2], height - margins[1] - margins[3]]
    if min(usable) <= 0:
        raise FeatureInputError("Title-block margins exceed the selected sheet size.")
    _save_drawing(ctx, state)
    return result(
        summary={
            "paperSize": values["size"],
            "widthMm": width,
            "heightMm": height,
            "usableWidthMm": usable[0],
            "usableHeightMm": usable[1],
        }
    )


@feature(
    "documentsDrawingTitleBlocks.orientation",
    "Orientation",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        select(
            "orientation",
            "Orientation",
            [("landscape", "Landscape"), ("portrait", "Portrait")],
            "landscape",
        ),
    ],
)
def titleblock_orientation(ctx: FeatureContext, values: dict) -> dict:
    """Set portrait or landscape paper orientation and adjust every saved viewport rectangle to the new bounds."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    sheet["orientation"] = values["orientation"]
    paper = {
        "A0": (1189, 841),
        "A1": (841, 594),
        "A2": (594, 420),
        "A3": (420, 297),
        "A4": (297, 210),
    }.get(sheet.get("size", "A1"), (841, 594))
    width, height = paper if values["orientation"] == "landscape" else paper[::-1]
    adjusted = 0
    for view in state["views"]:
        if view.get("sheet") != sheet["number"] or "viewportMm" not in view:
            continue
        x0, y0, x1, y1 = view["viewportMm"]
        if x1 > width or y1 > height:
            view["viewportMm"] = [
                min(x0, width - 1),
                min(y0, height - 1),
                min(x1, width),
                min(y1, height),
            ]
            adjusted += 1
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "orientation": values["orientation"],
            "paperWidthMm": width,
            "paperHeightMm": height,
            "adjustedViewportCount": adjusted,
        }
    )


@feature(
    "documentsDrawingTitleBlocks.margins",
    "Margins",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        number("leftMm", "Left margin", 15, unit="mm", min=0),
        number("bottomMm", "Bottom margin", 15, unit="mm", min=0),
        number("rightMm", "Right margin", 15, unit="mm", min=0),
        number("topMm", "Top margin", 15, unit="mm", min=0),
        number("bindingMm", "Binding allowance", 0, unit="mm", min=0),
    ],
)
def titleblock_margins(ctx: FeatureContext, values: dict) -> dict:
    """Set printable margins and binding allowance, rejecting any layout that leaves no drawing area."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    dims = {
        "A0": (1189, 841),
        "A1": (841, 594),
        "A2": (594, 420),
        "A3": (420, 297),
        "A4": (297, 210),
    }
    width, height = dims.get(sheet.get("size", "A1"), dims["A1"])
    left = values["leftMm"] + values["bindingMm"]
    usable_w = width - left - values["rightMm"]
    usable_h = height - values["bottomMm"] - values["topMm"]
    if min(usable_w, usable_h) <= 0:
        raise FeatureInputError("Margins and binding allowance exceed the paper size.")
    sheet["marginsMm"] = [left, values["bottomMm"], values["rightMm"], values["topMm"]]
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "usableWidthMm": usable_w,
            "usableHeightMm": usable_h,
            "bindingMm": values["bindingMm"],
        }
    )


@feature(
    "documentsDrawingTitleBlocks.titleBlockBrowser",
    "Title Block Browser",
    part="settings",
    fields=[
        select(
            "size",
            "Filter by size",
            [("all", "All sizes"), ("A1", "A1"), ("A2", "A2"), ("A3", "A3")],
            "all",
        ),
        text("search", "Search block name", ""),
    ],
)
def titleblock_browser(ctx: FeatureContext, values: dict) -> dict:
    """Browse built-in title-block families by size and name with physical paper dimensions."""
    blocks = [
        {"name": "SAEngine-A1", "size": "A1", "widthMm": 841, "heightMm": 594},
        {"name": "SAEngine-A2", "size": "A2", "widthMm": 594, "heightMm": 420},
        {"name": "SAEngine-A3", "size": "A3", "widthMm": 420, "heightMm": 297},
        {"name": "Office-A1", "size": "A1", "widthMm": 841, "heightMm": 594},
    ]
    query = values["search"].strip().casefold()
    rows = [
        block
        for block in blocks
        if (values["size"] == "all" or block["size"] == values["size"])
        and (not query or query in block["name"].casefold())
    ]
    return result(
        summary={"matchingBlockCount": len(rows)},
        tables=[
            table(
                "Title-block families",
                [
                    ("name", "Family"),
                    ("size", "Paper size"),
                    ("widthMm", "Width", "mm"),
                    ("heightMm", "Height", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsDrawingTitleBlocks.projectField",
    "Project Field",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("field", "Project field path", "project.name"),
        text("label", "Printed label", "Project"),
    ],
)
def titleblock_project_field(ctx: FeatureContext, values: dict) -> dict:
    """Bind a title-block field to an actual project-settings value and save its resolved content."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    settings = ctx.raw("settings") or {}
    value = settings
    for part in values["field"].split("."):
        value = value.get(part) if isinstance(value, dict) else None
    if value is None:
        raise FeatureInputError(f"Project Settings does not provide {values['field']!r}.")
    field = {"source": values["field"], "label": values["label"].strip(), "value": value}
    state["titleBlocks"].setdefault(sheet["number"], {})[values["label"].strip()] = field
    _save_drawing(ctx, state)
    return result(summary={"sheet": sheet["number"], "label": field["label"], "value": str(value)})


@feature(
    "documentsDrawingTitleBlocks.revisionField",
    "Revision Field",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("label", "Field label", "Revision"),
        text("format", "Display format", "code-date"),
    ],
)
def revision_field(ctx: FeatureContext, values: dict) -> dict:
    """Bind the latest saved revision for one sheet into a title-block field using the chosen display format."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    revisions = [
        item for item in state["revisions"] if item.get("sheet") in (None, sheet["number"])
    ]
    if not revisions:
        raise FeatureInputError(
            "Add a revision entry or issue the drawing before binding its revision field."
        )
    latest = max(revisions, key=lambda item: item.get("date", ""))
    value = (
        latest.get("code", "")
        if values["format"] == "code"
        else f"{latest.get('code', '')} / {latest.get('date', '')}"
        if values["format"] == "code-date"
        else latest.get("date", "")
    )
    field = {"source": "latestRevision", "format": values["format"], "value": value}
    state["titleBlocks"].setdefault(sheet["number"], {})[values["label"].strip()] = field
    _save_drawing(ctx, state)
    return result(
        summary={"sheet": sheet["number"], "revision": latest.get("code", ""), "value": value}
    )


@feature(
    "documentsDrawingTitleBlocks.dateField",
    "Date Field",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("label", "Field label", "Issue date"),
        select(
            "dateSource",
            "Date source",
            [("today", "Current date"), ("issue", "Latest issue date")],
            "today",
        ),
        text("dateFormat", "Date format", "%Y-%m-%d"),
    ],
)
def titleblock_date_field(ctx: FeatureContext, values: dict) -> dict:
    """Resolve a title-block date from the current date or latest issued sheet record and format it."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    if values["dateSource"] == "today":
        chosen = date.today()
    else:
        issue = sheet.get("issue")
        if not issue:
            raise FeatureInputError("The sheet has no issued date to bind.")
        chosen = date.fromisoformat(issue["date"])
    try:
        value = chosen.strftime(values["dateFormat"])
    except (ValueError, TypeError) as exc:
        raise FeatureInputError("The date format is invalid for strftime.") from exc
    state["titleBlocks"].setdefault(sheet["number"], {})[values["label"].strip()] = {
        "source": values["dateSource"],
        "value": value,
    }
    _save_drawing(ctx, state)
    return result(
        summary={"sheet": sheet["number"], "date": value, "dateSource": values["dateSource"]}
    )


@feature(
    "documentsDrawingTitleBlocks.customField",
    "Custom Field",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("fieldName", "Field name", "Contract number"),
        text("value", "Field value", ""),
        select(
            "fieldType",
            "Field type",
            [("text", "Text"), ("number", "Number"), ("date", "Date")],
            "text",
        ),
    ],
)
def titleblock_custom_field(ctx: FeatureContext, values: dict) -> dict:
    """Define a typed project-specific title-block field and reject values that do not match its type."""
    if not values["fieldName"].strip():
        raise FeatureInputError("Enter a custom title-block field name.")
    value: str | float = values["value"].strip()
    if values["fieldType"] == "number":
        try:
            value = float(value)
        except ValueError as exc:
            raise FeatureInputError("The custom field value must be numeric.") from exc
    elif values["fieldType"] == "date":
        try:
            value = date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise FeatureInputError("Use YYYY-MM-DD for a date field.") from exc
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    state["titleBlocks"].setdefault(sheet["number"], {})[values["fieldName"].strip()] = {
        "type": values["fieldType"],
        "value": value,
    }
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "field": values["fieldName"].strip(),
            "fieldType": values["fieldType"],
            "value": str(value),
        }
    )


@feature(
    "documentsDrawingTitleBlocks.addRevision",
    "Add Revision",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("code", "Revision code", "A"),
        text("date", "Revision date (YYYY-MM-DD)", "2026-01-01"),
        text("description", "Description", "Issued for review"),
        text("by", "Prepared by", ""),
    ],
)
def add_revision(ctx: FeatureContext, values: dict) -> dict:
    """Add a unique, dated revision to a sheet's title-block table and preserve its audit metadata."""
    try:
        date.fromisoformat(values["date"])
    except ValueError as exc:
        raise FeatureInputError("Use YYYY-MM-DD for the revision date.") from exc
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    if any(
        item.get("sheet") == sheet["number"] and item.get("code") == values["code"].strip()
        for item in state["revisions"]
    ):
        raise FeatureInputError("That revision code is already recorded for this sheet.")
    revision = {
        "sheet": sheet["number"],
        "code": values["code"].strip(),
        "date": values["date"],
        "description": values["description"].strip(),
        "by": values["by"].strip() or "Unknown",
    }
    state["revisions"].append(revision)
    sheet["revision"] = revision["code"]
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "revision": revision["code"],
            "revisionCount": sum(
                item.get("sheet") == sheet["number"] for item in state["revisions"]
            ),
        },
        tables=[
            table(
                "Revision table",
                [("code", "Code"), ("date", "Date"), ("description", "Description"), ("by", "By")],
                [revision],
            )
        ],
    )


@feature(
    "documentsDrawingTitleBlocks.revisionSequence",
    "Revision Sequence",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        select(
            "sequence", "Sequence style", [("alpha", "A, B, C"), ("numeric", "1, 2, 3")], "alpha"
        ),
    ],
)
def revision_sequence(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the next revision code for a sheet using its recorded issue history and selected sequence style."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    revisions = [row for row in state["revisions"] if row.get("sheet") == sheet["number"]]
    if values["sequence"] == "numeric":
        numbers = [int(row["code"]) for row in revisions if str(row.get("code", "")).isdigit()]
        next_code = str(max(numbers, default=0) + 1)
    else:
        from saengine.drawings.sheets.revisions import next_revision

        current = max((row.get("code", "") for row in revisions), default=None)
        next_code = next_revision(current)
    return result(
        summary={
            "sheet": sheet["number"],
            "nextRevision": next_code,
            "sequenceStyle": values["sequence"],
        },
        tables=[
            table(
                "Existing revisions",
                [("code", "Code"), ("date", "Date"), ("description", "Description")],
                revisions,
            )
        ],
    )


@feature(
    "documentsDrawingTitleBlocks.revisionCloud",
    "Revision Cloud",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("revision", "Revision code", "A"),
        number("x0Mm", "Left", 20, unit="mm"),
        number("y0Mm", "Bottom", 20, unit="mm"),
        number("x1Mm", "Right", 200, unit="mm"),
        number("y1Mm", "Top", 120, unit="mm"),
        number("arcMm", "Arc length", 6, unit="mm", min=1),
    ],
)
def titleblock_revision_cloud(ctx: FeatureContext, values: dict) -> dict:
    """Add a revision cloud to the title-block annotation layer and estimate the arc count from its perimeter."""
    if values["x1Mm"] <= values["x0Mm"] or values["y1Mm"] <= values["y0Mm"]:
        raise FeatureInputError("Cloud bounds must have positive width and height.")
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    width, height = values["x1Mm"] - values["x0Mm"], values["y1Mm"] - values["y0Mm"]
    cloud = {
        "kind": "revisionCloud",
        "sheet": sheet["number"],
        "revision": values["revision"].strip(),
        "boundsMm": [values["x0Mm"], values["y0Mm"], values["x1Mm"], values["y1Mm"]],
        "arcMm": values["arcMm"],
        "layer": "S-REV",
    }
    state["annotations"].append(cloud)
    _save_drawing(ctx, state)
    return result(
        summary={
            "revision": cloud["revision"],
            "perimeterMm": 2 * (width + height),
            "arcCount": math.ceil(2 * (width + height) / values["arcMm"]),
        }
    )


@feature(
    "documentsDrawingTitleBlocks.tableStyle",
    "Table Style",
    part="settings",
    fields=[
        text("styleName", "Style name", "Revision Table"),
        number("headerHeightMm", "Header height", 8, unit="mm", min=2),
        number("rowHeightMm", "Row height", 6, unit="mm", min=2),
        number("textHeightMm", "Text height", 2.5, unit="mm", min=0.5),
        checkbox("alternateRows", "Shade alternate rows", False),
    ],
)
def revision_table_style(ctx: FeatureContext, values: dict) -> dict:
    """Define a reusable revision table style and compute its printable text-to-row proportions."""
    if not values["styleName"].strip():
        raise FeatureInputError("Enter a table style name.")
    style = {
        "headerHeightMm": values["headerHeightMm"],
        "rowHeightMm": values["rowHeightMm"],
        "textHeightMm": values["textHeightMm"],
        "alternateRows": values["alternateRows"],
    }
    state = _drawing_state(ctx)
    state.setdefault("tableStyles", {})[values["styleName"].strip()] = style
    _save_drawing(ctx, state)
    return result(
        summary={
            "styleName": values["styleName"].strip(),
            "textHeightRatio": values["textHeightMm"] / values["rowHeightMm"],
            "alternateRows": values["alternateRows"],
            "styleCount": len(state["tableStyles"]),
        }
    )


@feature(
    "documentsDrawingTitleBlocks.professionalStamp",
    "Professional Stamp",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("engineer", "Professional name", ""),
        text("registration", "Registration id", ""),
        text("jurisdiction", "Registration jurisdiction", ""),
        text("stampImage", "Project-relative stamp image path", ""),
    ],
)
def professional_stamp(ctx: FeatureContext, values: dict) -> dict:
    """Place a professional identity stamp only when an image file and registration details are present."""
    if ctx.root is None or not values["engineer"].strip() or not values["registration"].strip():
        raise FeatureInputError(
            "Enter the professional name, registration id and project stamp image."
        )
    path = (ctx.root / values["stampImage"]).resolve()
    try:
        path.relative_to(ctx.root.resolve())
    except ValueError as exc:
        raise FeatureInputError("The stamp image must be inside the project folder.") from exc
    if path.suffix.lower() not in (".png", ".jpg", ".jpeg") or not path.is_file():
        raise FeatureInputError("Choose an existing project PNG or JPEG stamp image.")
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    stamp = {
        "kind": "professionalStamp",
        "sheet": sheet["number"],
        "engineer": values["engineer"].strip(),
        "registration": values["registration"].strip(),
        "jurisdiction": values["jurisdiction"].strip(),
        "image": path.relative_to(ctx.root).as_posix(),
        "imageSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    state["annotations"].append(stamp)
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "engineer": stamp["engineer"],
            "registration": stamp["registration"],
            "stampImage": stamp["image"],
        },
        notes=[
            "Registration details and image are recorded as supplied; this feature does not independently verify licensure."
        ],
    )


@feature(
    "documentsDrawingTitleBlocks.approvalSignature",
    "Approval Signature",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text(
            "privateKeyPath",
            "Project-relative Ed25519 private key PEM",
            "11 Exports/keys/signing-key.pem",
        ),
        text("password", "Key password (optional)", ""),
    ],
)
def approval_signature(ctx: FeatureContext, values: dict) -> dict:
    """Cryptographically sign the title-block approval metadata with a project-held Ed25519 key."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before signing a title block.")
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"], allow_locked=True)
    approval = sheet.get("approval") or state["titleBlocks"].get(sheet["number"], {}).get(
        "approval"
    )
    if not approval:
        raise FeatureInputError(
            "Record the approving engineer and date before creating an approval signature."
        )
    key_path = (ctx.root / values["privateKeyPath"]).resolve()
    try:
        key_path.relative_to(ctx.root.resolve())
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = serialization.load_pem_private_key(
            key_path.read_bytes(), password=values["password"].encode() or None
        )
        if not isinstance(key, Ed25519PrivateKey):
            raise FeatureInputError("The key must use Ed25519.")
    except FeatureInputError:
        raise
    except (ValueError, TypeError, OSError, ImportError) as exc:
        raise FeatureInputError(
            "Could not load an Ed25519 private key from the project path."
        ) from exc
    payload = json.dumps(
        {"sheet": sheet["number"], "approval": approval}, sort_keys=True, separators=(",", ":")
    ).encode()
    signature = key.sign(payload)
    signature_data = {
        "algorithm": "Ed25519",
        "sheet": sheet["number"],
        "approvalSha256": hashlib.sha256(payload).hexdigest(),
        "signatureBase64": __import__("base64").b64encode(signature).decode(),
        "signedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    state.setdefault("signatures", []).append(signature_data)
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "algorithm": "Ed25519",
            "approvalSha256": signature_data["approvalSha256"],
        }
    )


@feature(
    "documentsDrawingTitleBlocks.statusWatermark",
    "Status Watermark",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        select(
            "watermark",
            "Watermark",
            [
                ("DRAFT", "Draft"),
                ("NOT FOR CONSTRUCTION", "Not for construction"),
                ("SUPERSEDED", "Superseded"),
                ("CONFIDENTIAL", "Confidential"),
            ],
            "DRAFT",
        ),
        number("opacityPercent", "Opacity", 25, unit="%", min=1, max=100),
        number("angleDeg", "Rotation", 45, unit="deg"),
    ],
)
def status_watermark(ctx: FeatureContext, values: dict) -> dict:
    """Set a sheet status watermark with printable opacity and rotation metadata."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"], allow_locked=True)
    watermark = {
        "text": values["watermark"],
        "opacityPercent": values["opacityPercent"],
        "angleDeg": values["angleDeg"],
        "updatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    sheet["watermark"] = watermark
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "watermark": watermark["text"],
            "opacityPercent": watermark["opacityPercent"],
            "angleDeg": watermark["angleDeg"],
        }
    )


@feature(
    "documentsDrawingTitleBlocks.sheetSchedule",
    "Sheet Schedule",
    part="settings",
    fields=[
        text("fileName", "CSV output file", "sheet-schedule.csv"),
        checkbox("includePlaceholders", "Include placeholder sheets", True),
    ],
)
def sheet_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Build a sheet-and-revision register from the project preview and export it as a spreadsheet-ready CSV."""
    if ctx.root is None:
        raise FeatureInputError("Open a project to export the sheet schedule.")
    state = _drawing_state(ctx)
    rows = []
    for sheet in _sheet_rows(state):
        if not values["includePlaceholders"] and sheet.get("status") == "Placeholder":
            continue
        rows.append(
            {
                "number": sheet["number"],
                "title": sheet.get("title", ""),
                "discipline": sheet.get("discipline", ""),
                "status": sheet.get("status", "Draft"),
                "revision": sheet.get("revision", ""),
                "size": sheet.get("size", ""),
            }
        )
    path = ctx.root / "11 Exports" / Path(values["fileName"].strip() or "sheet-schedule.csv").name
    write_csv(path, ["number", "title", "discipline", "status", "revision", "size"], rows)
    return result(
        summary={"sheetCount": len(rows), "csvPath": path.relative_to(ctx.root).as_posix()},
        tables=[
            table(
                "Sheet schedule",
                [
                    ("number", "Number"),
                    ("title", "Title"),
                    ("discipline", "Discipline"),
                    ("status", "Status"),
                    ("revision", "Revision"),
                    ("size", "Size"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsDrawingTitleBlocks.batchSheetRename",
    "Batch Sheet Rename",
    part="settings",
    fields=[
        text(
            "pattern",
            "Title pattern ({number}, {discipline}, {old})",
            "{discipline} Drawing {number}",
        ),
        text("sheetNumbers", "Sheet numbers (comma-separated; blank means all)", ""),
    ],
)
def batch_sheet_rename(ctx: FeatureContext, values: dict) -> dict:
    """Apply a checked naming pattern to selected sheet titles without changing numbers or published ordering."""
    state = _drawing_state(ctx)
    selected = {item.strip() for item in values["sheetNumbers"].split(",") if item.strip()}
    changed = []
    for sheet in state["sheets"]:
        if selected and sheet["number"] not in selected:
            continue
        previous = sheet.get("title", "")
        try:
            new_title = values["pattern"].format(
                number=sheet["number"], discipline=sheet.get("discipline", ""), old=previous
            )
        except (KeyError, ValueError) as exc:
            raise FeatureInputError(
                "The title pattern may use {number}, {discipline} and {old}."
            ) from exc
        if not new_title.strip():
            raise FeatureInputError("The naming pattern creates an empty sheet title.")
        sheet["title"] = new_title
        changed.append({"number": sheet["number"], "oldTitle": previous, "newTitle": new_title})
    if selected - {row["number"] for row in changed}:
        raise FeatureInputError("One or more selected sheet numbers do not exist.")
    _save_drawing(ctx, state)
    return result(
        summary={"renamedSheetCount": len(changed)},
        tables=[
            table(
                "Sheet title changes",
                [("number", "Number"), ("oldTitle", "Previous title"), ("newTitle", "New title")],
                changed,
            )
        ],
    )


@feature(
    "documentsDrawingTitleBlocks.gridMarkers",
    "Grid Markers",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        checkbox("showX", "Show X-axis grid markers", True),
        checkbox("showY", "Show Y-axis grid markers", True),
        number("borderSpacingMm", "Border spacing", 10, unit="mm", min=1),
        select(
            "numbering",
            "Marker style",
            [("labels", "Use grid labels"), ("numeric", "Number sequentially")],
            "labels",
        ),
    ],
)
def grid_markers(ctx: FeatureContext, values: dict) -> dict:
    """Configure sheet-border markers from the floor-plan's actual X and Y grid labels and spacing."""
    plan = plan_data(ctx)
    actual = {
        row_axis: [row["label"] for row in grid_rows(plan) if row["axis"].lower() == row_axis]
        for row_axis in ("x", "y")
    }
    if not values["showX"] and not values["showY"]:
        raise FeatureInputError("Enable at least one grid-marker axis.")
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    config = {
        "showX": values["showX"],
        "showY": values["showY"],
        "spacingMm": values["borderSpacingMm"],
        "numbering": values["numbering"],
        "xLabels": actual["x"] if values["showX"] else [],
        "yLabels": actual["y"] if values["showY"] else [],
    }
    sheet["gridMarkers"] = config
    _save_drawing(ctx, state)
    return result(
        summary={
            "xMarkerCount": len(config["xLabels"]),
            "yMarkerCount": len(config["yLabels"]),
            "borderSpacingMm": config["spacingMm"],
        },
        tables=[
            table(
                "Grid markers",
                [("axis", "Axis"), ("label", "Plan grid label")],
                [
                    {"axis": axis.upper(), "label": label}
                    for axis in ("x", "y")
                    for label in config[f"{axis}Labels"]
                ],
            )
        ],
    )


@feature(
    "documentsDrawingTitleBlocks.keyPlanView",
    "Key Plan View",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        text("story", "Story id (blank means whole building)", ""),
        number("scaleDenominator", "Key plan scale denominator", 500, min=1),
    ],
)
def key_plan_view(ctx: FeatureContext, values: dict) -> dict:
    """Build a small-scale key-plan locator from the chosen story's actual structural member extents."""
    plan = plan_data(ctx)
    rows = [
        row
        for row in member_rows(plan)
        if not values["story"].strip() or row.get("story") == values["story"].strip()
    ]
    points = [
        (row[key], row[ykey])
        for row in rows
        for key, ykey in (("x1Mm", "y1Mm"), ("x2Mm", "y2Mm"))
        if key in row and ykey in row
    ]
    if not points:
        raise FeatureInputError(
            "The selected story has no members with plan coordinates for a key plan."
        )
    bounds = [
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    ]
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    locator = {
        "kind": "keyPlan",
        "sheet": sheet["number"],
        "story": values["story"].strip() or "all",
        "scale": values["scaleDenominator"],
        "boundsMm": bounds,
        "memberCount": len(rows),
    }
    state["views"].append(locator)
    _save_drawing(ctx, state)
    return result(
        summary={
            "story": locator["story"],
            "memberCount": len(rows),
            "scaleDenominator": locator["scale"],
            "planWidthM": (bounds[2] - bounds[0]) / 1000,
            "planDepthM": (bounds[3] - bounds[1]) / 1000,
        },
        tables=[
            table(
                "Key plan bounds",
                [
                    ("minXMm", "Min X", "mm"),
                    ("minYMm", "Min Y", "mm"),
                    ("maxXMm", "Max X", "mm"),
                    ("maxYMm", "Max Y", "mm"),
                ],
                [
                    {
                        "minXMm": bounds[0],
                        "minYMm": bounds[1],
                        "maxXMm": bounds[2],
                        "maxYMm": bounds[3],
                    }
                ],
            )
        ],
    )


@feature(
    "documentsDrawingTitleBlocks.northArrowBlock",
    "North Arrow Block",
    part="settings",
    fields=[
        text("sheet", "Sheet number", "S-101"),
        number("bearingDeg", "Project north bearing", 0, unit="deg"),
        number("xMm", "Block X", 20, unit="mm"),
        number("yMm", "Block Y", 20, unit="mm"),
        number("sizeMm", "Block size", 15, unit="mm", min=1),
    ],
)
def north_arrow_block(ctx: FeatureContext, values: dict) -> dict:
    """Place a dynamic north-arrow block in sheet space with its project bearing and measured print size."""
    state = _drawing_state(ctx)
    sheet = _sheet(state, values["sheet"])
    block = {
        "kind": "northArrowBlock",
        "sheet": sheet["number"],
        "positionMm": [values["xMm"], values["yMm"]],
        "sizeMm": values["sizeMm"],
        "projectNorthDeg": values["bearingDeg"] % 360,
        "trueNorthDeg": 0,
    }
    state["annotations"].append(block)
    _save_drawing(ctx, state)
    return result(
        summary={
            "sheet": sheet["number"],
            "bearingDeg": block["projectNorthDeg"],
            "sizeMm": block["sizeMm"],
            "trueNorthDeg": 0,
        }
    )
