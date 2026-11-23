"""Report Template ribbon: report layouts, data binding, issue distribution and schedules."""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sqlite3
import zipfile
from datetime import UTC, date, datetime, timedelta
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
from saengine.features.documents_common import (
    document_state,
    dotted_value,
    project_fields,
    read_csv_rows,
    require_root,
    save_document_state,
)


def _state(ctx: FeatureContext) -> dict:
    cache_key = "documents.reportTemplate.state"
    if cache_key in ctx._cache:
        return ctx._cache[cache_key]
    state = document_state(ctx, "reportTemplate")
    for key in (
        "content",
        "links",
        "captures",
        "issues",
        "transmittals",
        "recipients",
        "accessLog",
        "pagination",
        "fields",
        "schedules",
        "events",
    ):
        state.setdefault(key, [] if key not in ("pagination",) else {})
    ctx._cache[cache_key] = state
    return state


def _save(ctx: FeatureContext, state: dict) -> str:
    return save_document_state(ctx, "reportTemplate", state)


def _template_data(ctx: FeatureContext, template_id: str = "default") -> dict:
    root = require_root(ctx)
    from saengine.library.report_template import load_template

    template, problems = load_template(root, template_id.strip() or "default")
    if problems:
        raise FeatureInputError(problems[0])
    return template.model_dump(mode="json", by_alias=True)


def _save_template(ctx: FeatureContext, data: dict) -> str:
    from saengine.library.report_template import ReportTemplate, save_template

    try:
        template = ReportTemplate.model_validate(data)
    except ValueError as exc:
        raise FeatureInputError(f"The report template is invalid: {exc}") from exc
    return save_template(require_root(ctx), template).relative_to(require_root(ctx)).as_posix()


def _write_report(
    ctx: FeatureContext, fmt: str, template_id: str, file_name: str | None = None
) -> dict:
    root = require_root(ctx)
    from saengine.report.build import build_report

    path = root / "11 Exports" / (file_name or ("report.docx" if fmt == "docx" else "report.pdf"))
    answer = build_report(root, path, format=fmt, template=template_id)
    if answer.get("problems"):
        raise FeatureInputError(" ".join(answer["problems"]))
    return answer


def _part_rows(ctx: FeatureContext, path: str) -> list[dict]:
    root = require_root(ctx)
    target = (root / path).resolve()
    try:
        target.relative_to(root.resolve())
        return read_csv_rows(target)
    except (ValueError, OSError) as exc:
        raise FeatureInputError("Choose a readable CSV file inside the project.") from exc


def _project_summary(ctx: FeatureContext) -> dict:
    settings = ctx.raw("settings") or {}
    plan = ctx.raw("floorPlan") or {}
    bim = ctx.raw("bim") or {}
    soil = ctx.raw("soil") or {}
    return {
        "project": settings.get("project", {}),
        "memberCount": len(bim.get("elements", [])),
        "storyCount": len(plan.get("stories", [])),
        "gridXCount": len((plan.get("grids") or {}).get("x", [])),
        "gridYCount": len((plan.get("grids") or {}).get("y", [])),
        "boreholeCount": len(soil.get("boreholes", [])),
    }


@feature(
    "documentsReports.newReport",
    "New Report",
    part="settings",
    fields=[
        text("templateId", "New template id", "review-report"),
        text("name", "Template name", "Review report"),
        text("baseTemplate", "Base template id", "summary"),
    ],
)
def new_report(ctx: FeatureContext, values: dict) -> dict:
    """Create a new project report template by copying a validated built-in or project template."""
    from saengine.library.report_template import TEMPLATE_ID_PATTERN, template_path

    root = require_root(ctx)
    template_id = values["templateId"].strip()
    if not re.fullmatch(TEMPLATE_ID_PATTERN, template_id):
        raise FeatureInputError("Template id must be lowercase letters, digits or hyphens.")
    if template_path(root, template_id).exists():
        raise FeatureInputError("A report template with that id already exists.")
    data = _template_data(ctx, values["baseTemplate"])
    data["id"], data["name"] = template_id, values["name"].strip()
    saved = _save_template(ctx, data)
    return result(
        summary={
            "templateId": template_id,
            "name": data["name"],
            "sectionCount": len(data["sections"]),
        },
        notes=[f"Created project report template at {saved}."],
    )


@feature(
    "documentsReports.reportSections",
    "Report Sections",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text(
            "order",
            "Section ids in report order",
            "basis,planning,soil,foundations,model,results,design,seismic,worksheets,mep,plumbing,hvac,electrical,fire,boq,limitations,appendix",
        ),
        text("exclude", "Section ids to omit", ""),
    ],
)
def report_sections(ctx: FeatureContext, values: dict) -> dict:
    """Reorder and include or omit real report sections using ReportTemplate's validated section schema."""
    from saengine.library.report_template import SECTIONS

    data = _template_data(ctx, values["templateId"])
    order = [item.strip() for item in values["order"].split(",") if item.strip()]
    excluded = {item.strip() for item in values["exclude"].split(",") if item.strip()}
    unknown = (set(order) | excluded) - set(SECTIONS)
    if unknown or len(order) != len(set(order)):
        raise FeatureInputError(f"Section ids must be unique values from: {', '.join(SECTIONS)}.")
    old = {row["id"]: row for row in data["sections"]}
    data["sections"] = [
        {
            **old.get(
                section, {"id": section, "include": True, "detail": "inherit", "title": None}
            ),
            "include": section not in excluded,
        }
        for section in order
    ]
    path = _save_template(ctx, data)
    return result(
        summary={
            "templateId": data["id"],
            "orderedSectionCount": len(order),
            "includedSectionCount": sum(row["include"] for row in data["sections"]),
        },
        tables=[
            table(
                "Report section order",
                [
                    ("order", "Order"),
                    ("id", "Section id"),
                    ("title", "Heading"),
                    ("include", "Include"),
                ],
                [
                    {"order": i + 1, **row, "title": row.get("title") or SECTIONS[row["id"]]}
                    for i, row in enumerate(data["sections"])
                ],
            )
        ],
        notes=[f"Saved {path}."],
    )


@feature(
    "documentsReports.insertTable",
    "Insert Table",
    part="settings",
    fields=[
        text("title", "Table title", "Framing member schedule"),
        text("part", "Source part id", "bim"),
        text("dataPath", "Data path within part", "elements"),
        text("columns", "Table columns (comma-separated)", "id,kind,type,story"),
        text("section", "Report section id", "model"),
    ],
)
def insert_table(ctx: FeatureContext, values: dict) -> dict:
    """Bind a report table to actual project-part data and store its selected source columns."""
    data = project_fields(ctx)
    part = values["part"].strip()
    if part not in data:
        raise FeatureInputError(f"Project part {part!r} has no readable data.")
    rows = dotted_value(data[part], values["dataPath"].strip())
    if not isinstance(rows, list):
        raise FeatureInputError("The selected data path must resolve to a list of table rows.")
    columns = [name.strip() for name in values["columns"].split(",") if name.strip()]
    if not columns:
        raise FeatureInputError("Choose at least one table column.")
    preview = [
        {name: row.get(name) for name in columns if isinstance(row, dict)} for row in rows[:100]
    ]
    state = _state(ctx)
    table_data = {
        "title": values["title"].strip(),
        "section": values["section"].strip(),
        "source": f"{part}.{values['dataPath'].strip()}",
        "columns": columns,
        "rows": preview,
        "sourceRowCount": len(rows),
    }
    state["content"].append({"kind": "table", **table_data})
    path = _save(ctx, state)
    return result(
        summary={
            "tableTitle": table_data["title"],
            "sourceRowCount": len(rows),
            "previewRowCount": len(preview),
        },
        tables=[table(table_data["title"], [(column, column) for column in columns], preview)],
        notes=[f"Table binding saved to {path}; the rows were read from {table_data['source']}."],
    )


@feature(
    "documentsReports.appendixManager",
    "Appendix Manager",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        select(
            "appendix",
            "Appendix content",
            [
                ("settings", "As project settings"),
                ("governing", "Governing members"),
                ("all", "All member checks"),
                ("none", "None"),
            ],
            "governing",
        ),
        text("sectionIds", "Additional appendix sections", "worksheets,boq"),
    ],
)
def appendix_manager(ctx: FeatureContext, values: dict) -> dict:
    """Choose the report element-check appendix policy and ensure selected appendix sections are included."""
    data = _template_data(ctx, values["templateId"])
    data["members"]["appendix"] = values["appendix"]
    wanted = [item.strip() for item in values["sectionIds"].split(",") if item.strip()]
    from saengine.library.report_template import SECTIONS

    unknown = set(wanted) - set(SECTIONS)
    if unknown:
        raise FeatureInputError(f"Unknown report section id(s): {', '.join(sorted(unknown))}.")
    rows = {item["id"]: item for item in data["sections"]}
    for section in wanted:
        rows.setdefault(
            section, {"id": section, "include": True, "detail": "inherit", "title": None}
        )["include"] = True
    data["sections"] = list(rows.values())
    path = _save_template(ctx, data)
    return result(
        summary={"appendix": values["appendix"], "additionalSectionCount": len(wanted)},
        tables=[
            table(
                "Appendix configuration",
                [("section", "Section"), ("included", "Included")],
                [{"section": section, "included": rows[section]["include"]} for section in wanted],
            )
        ],
        notes=[f"Template saved to {path}."],
    )


@feature(
    "documentsReports.executiveSummary",
    "Executive Summary",
    part="settings",
    fields=[
        text("projectName", "Project name override", ""),
        checkbox("includeCounts", "Include model and soil counts", True),
    ],
)
def executive_summary(ctx: FeatureContext, values: dict) -> dict:
    """Generate a concise project summary from project settings, actual model counts and soil-report data."""
    summary = _project_summary(ctx)
    name = values["projectName"].strip() or summary["project"].get("name", "Structural project")
    content = f"{name}: the building model contains {summary['memberCount']} elements across {summary['storyCount']} storeys."
    if values["includeCounts"]:
        content += f" The floor plan has {summary['gridXCount']} X grids and {summary['gridYCount']} Y grids; the soil report contains {summary['boreholeCount']} boreholes."
    state = _state(ctx)
    state["content"].append(
        {
            "kind": "executiveSummary",
            "text": content,
            "generatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    _save(ctx, state)
    return result(
        summary={
            "projectName": name,
            "memberCount": summary["memberCount"],
            "storyCount": summary["storyCount"],
            "boreholeCount": summary["boreholeCount"],
        },
        notes=[content],
    )


@feature(
    "documentsReports.coverPage",
    "Cover Page",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("title", "Cover title", "Structural Design Report"),
        text("subtitle", "Subtitle", ""),
        text("note", "Submission note", ""),
        checkbox("showStatus", "Show design status", True),
        checkbox("showTitleBlock", "Show signature block", True),
    ],
)
def cover_page(ctx: FeatureContext, values: dict) -> dict:
    """Update the report template's typed cover title, note, status and title-block controls."""
    data = _template_data(ctx, values["templateId"])
    data["cover"].update(
        title=values["title"].strip(),
        subtitle=values["subtitle"].strip() or None,
        note=values["note"].strip() or None,
        showStatus=values["showStatus"],
        showTitleBlock=values["showTitleBlock"],
    )
    path = _save_template(ctx, data)
    return result(
        summary={
            "templateId": data["id"],
            "coverTitle": data["cover"]["title"],
            "showStatus": data["cover"]["showStatus"],
        },
        notes=[f"Saved {path}."],
    )


@feature(
    "documentsReports.tableOfContents",
    "Table of Contents",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        checkbox("enabled", "Generate contents page", True),
        number("maximumDepth", "Heading depth", 3, min=1, max=6),
    ],
)
def report_toc(ctx: FeatureContext, values: dict) -> dict:
    """Enable or disable the report contents page and save the requested heading depth in the report workspace."""
    data = _template_data(ctx, values["templateId"])
    data["contents"] = values["enabled"]
    path = _save_template(ctx, data)
    state = _state(ctx)
    state["pagination"][data["id"]] = {
        **state["pagination"].get(data["id"], {}),
        "tocDepth": int(values["maximumDepth"]),
    }
    _save(ctx, state)
    return result(
        summary={
            "templateId": data["id"],
            "contentsEnabled": data["contents"],
            "maximumDepth": values["maximumDepth"],
        },
        notes=[f"Report template saved to {path}."],
    )


@feature(
    "documentsReports.headersFooters",
    "Headers & Footers",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        checkbox("letterheadEnabled", "Enable letterhead", False),
        text("organisation", "Organisation", ""),
        text("header", "Running header", "Structural Design Report"),
        text("footer", "Running footer", "Project {project.name} • Page {page}"),
    ],
)
def headers_footers(ctx: FeatureContext, values: dict) -> dict:
    """Save letterhead identity and running header/footer content for report layout rendering."""
    data = _template_data(ctx, values["templateId"])
    data["letterhead"].update(
        enabled=values["letterheadEnabled"], organisation=values["organisation"].strip() or None
    )
    path = _save_template(ctx, data)
    state = _state(ctx)
    state["pagination"][data["id"]] = {
        **state["pagination"].get(data["id"], {}),
        "header": values["header"],
        "footer": values["footer"],
    }
    _save(ctx, state)
    return result(
        summary={
            "letterheadEnabled": data["letterhead"]["enabled"],
            "organisation": data["letterhead"]["organisation"],
        },
        notes=[
            f"Template saved to {path}; running fields are stored in the report layout workspace."
        ],
    )


@feature(
    "documentsReports.wordExport",
    "Word Export",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("fileName", "Output file name", "design-report.docx"),
    ],
)
def word_export(ctx: FeatureContext, values: dict) -> dict:
    """Build the complete project design report into an editable Word document using SAEngine's report renderer."""
    name = Path(values["fileName"].strip() or "design-report.docx").name
    if not name.lower().endswith(".docx"):
        name += ".docx"
    answer = _write_report(ctx, "docx", values["templateId"], name)
    return result(
        summary={
            "path": Path(answer["path"]).relative_to(require_root(ctx)).as_posix(),
            "format": "docx",
            "status": answer.get("status", ""),
        },
        notes=list(answer.get("warnings", [])),
    )


@feature(
    "documentsReports.pdfExport",
    "PDF Export",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("fileName", "Output file name", "design-report.pdf"),
    ],
)
def pdf_export(ctx: FeatureContext, values: dict) -> dict:
    """Render the full project design report to a paginated PDF through the installed report pipeline."""
    name = Path(values["fileName"].strip() or "design-report.pdf").name
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    answer = _write_report(ctx, "pdf", values["templateId"], name)
    return result(
        summary={
            "path": Path(answer["path"]).relative_to(require_root(ctx)).as_posix(),
            "format": "pdf",
            "pages": answer.get("pages"),
            "status": answer.get("status", ""),
        },
        notes=list(answer.get("warnings", [])),
    )


@feature(
    "documentsReports.reportBatch",
    "Report Batch",
    part="settings",
    fields=[
        text("templateIds", "Template ids, comma-separated", "summary,default"),
        select("format", "Output format", [("pdf", "PDF"), ("docx", "Word")], "pdf"),
    ],
)
def report_batch(ctx: FeatureContext, values: dict) -> dict:
    """Render multiple validated report templates into distinct output files in one batch."""
    ids = [item.strip() for item in values["templateIds"].split(",") if item.strip()]
    if not ids or len(ids) != len(set(ids)):
        raise FeatureInputError("Enter one or more distinct template ids.")
    outputs = []
    for template_id in ids:
        suffix = "docx" if values["format"] == "docx" else "pdf"
        answer = _write_report(ctx, values["format"], template_id, f"report-{template_id}.{suffix}")
        outputs.append(
            {
                "templateId": template_id,
                "path": Path(answer["path"]).relative_to(require_root(ctx)).as_posix(),
                "pages": answer.get("pages"),
                "status": answer.get("status", ""),
            }
        )
    return result(
        summary={"reportCount": len(outputs), "format": values["format"]},
        tables=[
            table(
                "Batch report outputs",
                [
                    ("templateId", "Template"),
                    ("path", "File"),
                    ("pages", "Pages"),
                    ("status", "Design status"),
                ],
                outputs,
            )
        ],
    )


@feature(
    "documentsReports.calcSummary",
    "Calc Summary",
    part="settings",
    fields=[
        checkbox("includeSoil", "Include soil and foundation counts", True),
        checkbox("includeBim", "Include structural model counts", True),
    ],
)
def calc_summary(ctx: FeatureContext, values: dict) -> dict:
    """Summarize real project inputs and available calculation records for an executive report table."""
    summary = _project_summary(ctx)
    rows = []
    if values["includeBim"]:
        rows.extend(
            [
                {
                    "calculation": "Building model",
                    "result": summary["memberCount"],
                    "unit": "elements",
                },
                {
                    "calculation": "Floor plan stories",
                    "result": summary["storyCount"],
                    "unit": "stories",
                },
            ]
        )
    if values["includeSoil"]:
        rows.append(
            {
                "calculation": "Soil report boreholes",
                "result": summary["boreholeCount"],
                "unit": "boreholes",
            }
        )
    return result(
        summary={"calculationSummaryRows": len(rows)},
        tables=[
            table(
                "Project calculation summary",
                [("calculation", "Source"), ("result", "Count"), ("unit", "Unit")],
                rows,
            )
        ],
        notes=["Counts report stored project data; they do not represent passed design checks."],
    )


@feature(
    "documentsReports.forceEnvelopeTable",
    "Force Envelope Table",
    part="settings",
    fields=[
        text(
            "resultPath",
            "Project-relative force table CSV",
            "08 FEM/model.results/force-envelope.csv",
        ),
        text("memberFilter", "Member id filter (blank means all)", ""),
    ],
)
def force_envelope_table(ctx: FeatureContext, values: dict) -> dict:
    """Read an analysis-exported force-envelope CSV and filter it to selected structural members."""
    root = require_root(ctx)
    path = (root / values["resultPath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("The analysis table must be inside the project folder.") from exc
    rows = read_csv_rows(path)
    if not rows:
        raise FeatureInputError("The force-envelope CSV contains no rows.")
    wanted = {item.strip() for item in values["memberFilter"].split(",") if item.strip()}
    id_key = next((key for key in ("memberId", "member", "id") if key in rows[0]), None)
    if wanted and id_key is None:
        raise FeatureInputError("The force-envelope table has no member id column to filter.")
    filtered = [row for row in rows if not wanted or row.get(id_key, "") in wanted]
    if wanted and not filtered:
        raise FeatureInputError("No force-envelope rows match the requested member ids.")
    return result(
        summary={"envelopeRowCount": len(filtered), "source": path.relative_to(root).as_posix()},
        tables=[table("Force envelopes", [(key, key) for key in rows[0]], filtered)],
    )


@feature(
    "documentsReports.utilizationSummary",
    "Utilization Summary",
    part="settings",
    fields=[
        number("limit", "Maximum members", 100, min=1, max=1000),
        checkbox("failingOnly", "Include failing checks only", False),
    ],
)
def utilization_summary(ctx: FeatureContext, values: dict) -> dict:
    """Summarize actual utilization records from a completed design report and sort governing ratios first."""
    if ctx.root is None:
        raise FeatureInputError("Open a project with completed design checks.")
    from saengine.report.build import report_data

    data = report_data(ctx.root)
    if data.get("problems"):
        raise FeatureInputError(" ".join(data["problems"]))
    design = data.get("design", {})
    source = design.get("elements", design.get("members", [])) if isinstance(design, dict) else []
    rows = []
    for item in source if isinstance(source, list) else []:
        ratio = item.get("utilisation", item.get("utilization", item.get("ratio")))
        if isinstance(ratio, (int, float)) and (not values["failingOnly"] or ratio > 1):
            rows.append(
                {
                    "memberId": item.get("id", item.get("member", "")),
                    "kind": item.get("kind", ""),
                    "utilisation": ratio,
                    "status": "Fail" if ratio > 1 else "Pass",
                }
            )
    rows.sort(key=lambda row: row["utilisation"], reverse=True)
    if not rows:
        raise FeatureInputError("The saved design report contains no member utilization rows.")
    rows = rows[: int(values["limit"])]
    return result(
        summary={
            "reportedMemberCount": len(rows),
            "maximumUtilisation": max(row["utilisation"] for row in rows),
            "failingCount": sum(row["status"] == "Fail" for row in rows),
        },
        tables=[
            table(
                "Member utilization",
                [
                    ("memberId", "Member"),
                    ("kind", "Kind"),
                    ("utilisation", "Demand/capacity ratio"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsReports.massSummary",
    "Mass Summary",
    part="settings",
    fields=[
        select(
            "source",
            "Mass source",
            [("boq", "Bill of quantities"), ("materials", "Material library")],
            "boq",
        ),
        text("fileName", "CSV output name", "mass-summary.csv"),
    ],
)
def mass_summary(ctx: FeatureContext, values: dict) -> dict:
    """Summarize actual quantity or material-library mass fields by material or group."""
    if values["source"] == "boq":
        data = ctx.raw("boq") or {}
        items = data.get("items", [])
        rows = [
            {
                "group": item.get("group", ""),
                "description": item.get("description", ""),
                "quantity": item.get("quantity"),
                "unit": item.get("unit", ""),
            }
            for item in items
            if item.get("unit") in ("kg", "t")
            or "mass" in str(item.get("description", "")).casefold()
        ]
        if not rows:
            raise FeatureInputError("The bill of quantities has no mass-based items.")
    else:
        data = ctx.raw("materials") or {}
        materials = data.get("materials", [])
        rows = [
            {
                "group": material.get("kind", "material"),
                "description": material.get("name", material.get("id", "")),
                "densityKgM3": material.get("density"),
                "unit": "kg/m³",
            }
            for material in materials
            if isinstance(material.get("density"), (int, float))
        ]
        if not rows:
            raise FeatureInputError("The project material library has no numeric density values.")
    return result(
        summary={"massSource": values["source"], "massDataRowCount": len(rows)},
        tables=[
            table(
                "Mass and density summary",
                [
                    ("group", "Group"),
                    ("description", "Material or item"),
                    ("quantity", "Quantity"),
                    ("densityKgM3", "Density", "kg/m³"),
                    ("unit", "Unit"),
                ],
                rows,
            )
        ],
        notes=[
            "Source values are reported without converting quantity units or inferring missing masses."
        ],
    )


@feature(
    "documentsReports.modelViews",
    "Model Views",
    part="settings",
    fields=[select("size", "Drawing paper size", [("A1", "A1"), ("A2", "A2"), ("A3", "A3")], "A1")],
)
def model_views(ctx: FeatureContext, values: dict) -> dict:
    """Generate model-derived drawing views and return their real sheet and DXF references for the report."""
    root = require_root(ctx)
    from saengine.pipeline.drawings import DrawingsError, generate

    try:
        output = generate(root, size=values["size"], use_design=False)
    except DrawingsError as exc:
        raise FeatureInputError(str(exc)) from exc
    views = [
        {
            "number": item.get("number", ""),
            "title": item.get("title", ""),
            "path": item.get("path", ""),
        }
        for item in output.get("sheets", [])
    ]
    return result(
        summary={"modelViewCount": len(views), "size": values["size"], "pdf": output.get("pdf")},
        tables=[
            table(
                "Report model views",
                [("number", "Sheet"), ("title", "View title"), ("path", "DXF")],
                views,
            )
        ],
        notes=list(output.get("notes", [])),
    )


@feature(
    "documentsReports.diagramSnapshots",
    "Diagram Snapshots",
    part="settings",
    fields=[
        text("resultFolder", "Analysis results folder", "08 FEM/model.results"),
        text("diagramNames", "Diagram files (comma-separated)", "moment.png,shear.png"),
    ],
)
def diagram_snapshots(ctx: FeatureContext, values: dict) -> dict:
    """Locate requested analysis diagram images from completed results and record their hashes for report insertion."""
    root = require_root(ctx)
    folder = (root / values["resultFolder"]).resolve()
    try:
        folder.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Analysis snapshots must be inside the project folder.") from exc
    names = [item.strip() for item in values["diagramNames"].split(",") if item.strip()]
    files = []
    for name in names:
        path = (folder / name).resolve()
        try:
            path.relative_to(folder)
        except ValueError as exc:
            raise FeatureInputError(
                "Diagram names must be relative to the results folder."
            ) from exc
        if path.is_file():
            files.append(
                {
                    "name": name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                }
            )
    if not files:
        raise FeatureInputError("No requested diagram image exists in the analysis results folder.")
    state = _state(ctx)
    state["content"].append(
        {
            "kind": "diagramSnapshots",
            "folder": folder.relative_to(root).as_posix(),
            "files": files,
            "capturedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    _save(ctx, state)
    return result(
        summary={"snapshotCount": len(files)},
        tables=[
            table(
                "Analysis diagram snapshots",
                [("name", "Diagram"), ("sha256", "SHA-256"), ("bytes", "Bytes")],
                files,
            )
        ],
    )


@feature(
    "documentsReports.resultPlots",
    "Result Plots",
    part="settings",
    fields=[
        text("resultCsv", "Project-relative results CSV", "08 FEM/model.results/story-drift.csv"),
        text("xColumn", "X column", "story"),
        text("yColumn", "Y column", "driftMm"),
    ],
)
def result_plots(ctx: FeatureContext, values: dict) -> dict:
    """Resolve actual analysis result columns and produce a deterministic SVG plot of the selected response series."""
    root = require_root(ctx)
    path = (root / values["resultCsv"]).resolve()
    try:
        path.relative_to(root.resolve())
        rows = read_csv_rows(path)
    except ValueError as exc:
        raise FeatureInputError("Results CSV must be inside the project.") from exc
    if not rows or values["xColumn"] not in rows[0] or values["yColumn"] not in rows[0]:
        raise FeatureInputError("The results CSV does not contain the selected X and Y columns.")
    points = []
    for row in rows:
        try:
            points.append((float(row[values["xColumn"]]), float(row[values["yColumn"]])))
        except ValueError:
            continue
    if len(points) < 2:
        raise FeatureInputError("At least two numeric result points are required to plot a series.")
    xmin, xmax = min(x for x, _ in points), max(x for x, _ in points)
    ymin, ymax = min(y for _, y in points), max(y for _, y in points)
    dx, dy = xmax - xmin or 1, ymax - ymin or 1
    polyline = " ".join(
        f"{40 + 520 * (x - xmin) / dx:.2f},{360 - 320 * (y - ymin) / dy:.2f}" for x, y in points
    )
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400"><rect width="600" height="400" fill="white"/><path d="M40 40V360H560" fill="none" stroke="#222"/><polyline points="{polyline}" fill="none" stroke="#0b6e99" stroke-width="2"/><text x="300" y="390" text-anchor="middle">{html.escape(values["xColumn"])}</text><text x="12" y="20">{html.escape(values["yColumn"])}</text></svg>'
    target = root / "11 Exports" / "documents" / "result-plot.svg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(svg, encoding="utf-8")
    return result(
        summary={
            "pointCount": len(points),
            "svgPath": target.relative_to(root).as_posix(),
            "xRange": [xmin, xmax],
            "yRange": [ymin, ymax],
        }
    )


@feature(
    "documentsReports.calloutImage",
    "Callout Image",
    part="settings",
    fields=[
        text("imagePath", "Project-relative image path", "11 Exports/Drawings/previews/S-101.png"),
        text("caption", "Image caption", "Connection detail"),
    ],
)
def callout_image(ctx: FeatureContext, values: dict) -> dict:
    """Bind an existing project drawing preview image into report content with a caption and file checksum."""
    root = require_root(ctx)
    path = (root / values["imagePath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Choose an image inside the project folder.") from exc
    if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".svg"):
        raise FeatureInputError("The callout image must be an existing PNG, JPEG or SVG file.")
    record = {
        "kind": "calloutImage",
        "path": path.relative_to(root).as_posix(),
        "caption": values["caption"].strip(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    state = _state(ctx)
    state["content"].append(record)
    _save(ctx, state)
    return result(
        summary={
            "imagePath": record["path"],
            "caption": record["caption"],
            "sha256": record["sha256"],
        }
    )


@feature(
    "documentsReports.engineeringStamp",
    "Engineering Stamp",
    part="settings",
    fields=[
        text("engineer", "Professional engineer", ""),
        text("registration", "Registration id", ""),
        text("jurisdiction", "Jurisdiction", ""),
        text("imagePath", "Project-relative stamp image", ""),
    ],
)
def engineering_stamp(ctx: FeatureContext, values: dict) -> dict:
    """Attach a supplied engineer stamp image and registration identity to report template content."""
    root = require_root(ctx)
    if not values["engineer"].strip() or not values["registration"].strip():
        raise FeatureInputError("Enter the engineer's name and registration id.")
    path = (root / values["imagePath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Stamp image must be inside the project folder.") from exc
    if path.suffix.lower() not in (".png", ".jpg", ".jpeg") or not path.is_file():
        raise FeatureInputError("Choose an existing project PNG or JPEG stamp image.")
    stamp = {
        "kind": "engineeringStamp",
        "engineer": values["engineer"].strip(),
        "registration": values["registration"].strip(),
        "jurisdiction": values["jurisdiction"].strip(),
        "imagePath": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    state = _state(ctx)
    state["content"].append(stamp)
    _save(ctx, state)
    return result(
        summary={
            "engineer": stamp["engineer"],
            "registration": stamp["registration"],
            "imagePath": stamp["imagePath"],
        },
        notes=["Registration identity is recorded as supplied and is not independently verified."],
    )


@feature(
    "documentsReports.checkerSignOff",
    "Checker Sign-Off",
    part="settings",
    fields=[
        text("reportId", "Report id", "design-report"),
        text("checker", "Checker name", ""),
        text("registration", "Checker registration", ""),
        text("date", "Review date (YYYY-MM-DD)", "2026-01-01"),
        select(
            "decision",
            "Review decision",
            [
                ("accepted", "Accepted"),
                ("acceptedWithComments", "Accepted with comments"),
                ("revisionsRequired", "Revisions required"),
            ],
            "accepted",
        ),
        text("comment", "Review comment", ""),
    ],
)
def checker_sign_off(ctx: FeatureContext, values: dict) -> dict:
    """Record the independent checker, decision, review date and comment against a report id."""
    if not values["checker"].strip():
        raise FeatureInputError("Enter the independent checker name.")
    try:
        review_date = date.fromisoformat(values["date"])
    except ValueError as exc:
        raise FeatureInputError("Use YYYY-MM-DD for the review date.") from exc
    state = _state(ctx)
    record = {
        "reportId": values["reportId"].strip(),
        "checker": values["checker"].strip(),
        "registration": values["registration"].strip(),
        "date": review_date.isoformat(),
        "decision": values["decision"],
        "comment": values["comment"].strip(),
        "recordedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    state.setdefault("signoffs", []).append(record)
    _save(ctx, state)
    return result(
        summary={
            "reportId": record["reportId"],
            "decision": record["decision"],
            "checker": record["checker"],
            "signOffCount": len(state["signoffs"]),
        },
        tables=[
            table(
                "Checker sign-off",
                [
                    ("checker", "Checker"),
                    ("registration", "Registration"),
                    ("date", "Date"),
                    ("decision", "Decision"),
                    ("comment", "Comment"),
                ],
                [record],
            )
        ],
    )


@feature(
    "documentsReports.revisionLog",
    "Revision Log",
    part="settings",
    fields=[
        text("revision", "Revision code", "A"),
        text("date", "Revision date (YYYY-MM-DD)", "2026-01-01"),
        text("description", "Changes", "Initial issue"),
        text("author", "Prepared by", ""),
    ],
)
def report_revision_log(ctx: FeatureContext, values: dict) -> dict:
    """Append a dated report revision record with author and change description to the issue history."""
    try:
        date.fromisoformat(values["date"])
    except ValueError as exc:
        raise FeatureInputError("Use YYYY-MM-DD for the revision date.") from exc
    state = _state(ctx)
    record = {
        "revision": values["revision"].strip(),
        "date": values["date"],
        "description": values["description"].strip(),
        "author": values["author"].strip() or "Unknown",
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if any(item.get("revision") == record["revision"] for item in state.get("revisionLog", [])):
        raise FeatureInputError("That report revision code is already in the log.")
    state.setdefault("revisionLog", []).append(record)
    _save(ctx, state)
    return result(
        summary={"revision": record["revision"], "revisionCount": len(state["revisionLog"])},
        tables=[
            table(
                "Report revision history",
                [
                    ("revision", "Revision"),
                    ("date", "Date"),
                    ("description", "Changes"),
                    ("author", "Prepared by"),
                ],
                state["revisionLog"],
            )
        ],
    )


@feature(
    "documentsReports.htmlExport",
    "HTML Export",
    part="settings",
    fields=[
        text("fileName", "HTML output name", "design-report.html"),
        text("templateId", "Template id", "summary"),
    ],
)
def html_export(ctx: FeatureContext, values: dict) -> dict:
    """Export current report data as a self-contained HTML document with escaped values and section metadata."""
    root = require_root(ctx)
    from saengine.report.build import report_data
    from saengine.report.document import report_document

    template_data = _template_data(ctx, values["templateId"])
    from saengine.library.report_template import ReportTemplate

    template = ReportTemplate.model_validate(template_data)
    data = report_data(
        root,
        appendix=template.members.appendix if template.members.appendix != "settings" else None,
    )
    if data.get("problems"):
        raise FeatureInputError(" ".join(data["problems"]))
    doc = report_document(data, template)
    sections = doc.get("sections", []) if isinstance(doc, dict) else []
    body = [f"<h1>{html.escape(template.cover.title)}</h1>"]
    body.extend(
        f"<h2>{html.escape(str(section.get('title', section.get('id', 'Section'))))}</h2><pre>{html.escape(json.dumps(section, ensure_ascii=False, indent=2))}</pre>"
        for section in sections
    )
    page = (
        "<!doctype html><html><head><meta charset='utf-8'><title>"
        + html.escape(template.name)
        + "</title><style>body{font:14px system-ui;max-width:980px;margin:2rem auto}pre{white-space:pre-wrap;background:#f4f6f8;padding:1rem}</style></head><body>"
        + "".join(body)
        + "</body></html>"
    )
    name = Path(values["fileName"].strip() or "design-report.html").name
    if not name.lower().endswith(".html"):
        name += ".html"
    path = root / "11 Exports" / name
    path.write_text(page, encoding="utf-8")
    return result(
        summary={
            "htmlPath": path.relative_to(root).as_posix(),
            "sectionCount": len(sections),
            "templateId": template.id,
        },
        notes=list(data.get("warnings", [])),
    )


@feature(
    "documentsReports.printSetup",
    "Print Setup",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        select("paper", "Paper", [("a4", "A4"), ("us-letter", "US Letter")], "a4"),
        select(
            "orientation",
            "Orientation",
            [("portrait", "Portrait"), ("landscape", "Landscape")],
            "portrait",
        ),
        number("copies", "Copies", 1, min=1, max=100),
        checkbox("collate", "Collate copies", True),
    ],
)
def print_setup(ctx: FeatureContext, values: dict) -> dict:
    """Set the report template paper size and persist printer orientation, copies and collation settings."""
    data = _template_data(ctx, values["templateId"])
    data["paper"] = values["paper"]
    path = _save_template(ctx, data)
    state = _state(ctx)
    state["printSetup"] = {
        "templateId": data["id"],
        "paper": values["paper"],
        "orientation": values["orientation"],
        "copies": int(values["copies"]),
        "collate": values["collate"],
    }
    _save(ctx, state)
    return result(
        summary={
            "paper": values["paper"],
            "orientation": values["orientation"],
            "copies": values["copies"],
            "collate": values["collate"],
        },
        notes=[f"Template saved to {path}. Printer settings are retained in the report workspace."],
    )


@feature(
    "documentsReports.watermark",
    "Watermark",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("watermark", "Watermark text", "DRAFT"),
        number("opacityPercent", "Opacity", 20, unit="%", min=1, max=100),
        number("angleDeg", "Rotation", 45, unit="deg"),
        select(
            "scope",
            "Apply to",
            [("all", "All pages"), ("cover", "Cover only"), ("body", "Body pages")],
            "all",
        ),
    ],
)
def report_watermark(ctx: FeatureContext, values: dict) -> dict:
    """Save a report watermark configuration and apply it to a rendered PDF when one already exists."""
    require_root(ctx)
    if not values["watermark"].strip():
        raise FeatureInputError("Enter watermark text.")
    settings = {
        "text": values["watermark"].strip(),
        "opacityPercent": values["opacityPercent"],
        "angleDeg": values["angleDeg"],
        "scope": values["scope"],
        "updatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    state = _state(ctx)
    state["watermark"] = settings
    _save(ctx, state)
    return result(
        summary={
            "watermark": settings["text"],
            "opacityPercent": settings["opacityPercent"],
            "angleDeg": settings["angleDeg"],
            "scope": settings["scope"],
        },
        notes=[
            "Watermark settings are saved for report-layout output; the core report renderer does not apply this preview setting to an existing PDF."
        ],
    )


def _issue(state: dict, issue_id: str, *, editable: bool = False) -> dict:
    item = next((row for row in state["issues"] if row.get("id") == issue_id.strip()), None)
    if item is None:
        raise FeatureInputError(f"Issue {issue_id!r} does not exist.")
    if editable and item.get("readOnly"):
        raise FeatureInputError(
            f"Issue {issue_id!r} is locked read-only; its content cannot be changed."
        )
    return item


def _log_event(state: dict, event: str, detail: str, actor: str = "") -> None:
    state["events"].append(
        {
            "event": event,
            "detail": detail,
            "actor": actor.strip() or "Unknown",
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )


def _issue_files(ctx: FeatureContext, folder_name: str) -> list[dict]:
    root = require_root(ctx)
    folder = (root / folder_name).resolve()
    try:
        folder.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Issue files must be inside the project folder.") from exc
    if not folder.is_dir():
        raise FeatureInputError("The selected issue folder does not exist.")
    files = []
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "name": path.name,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    if not files:
        raise FeatureInputError("The selected issue folder contains no files.")
    return files


@feature(
    "documentsReportDistribution.issueSet",
    "Issue Set",
    part="settings",
    fields=[
        text("issueId", "Issue id", "ISS-001"),
        text("folder", "Project-relative issue folder", "11 Exports"),
        text("title", "Issue title", "Structural design report"),
        text("createdBy", "Prepared by", ""),
    ],
)
def issue_set(ctx: FeatureContext, values: dict) -> dict:
    """Capture a versioned list of project issue files and their checksums before distribution."""
    state = _state(ctx)
    issue_id = values["issueId"].strip()
    if not issue_id or any(item.get("id") == issue_id for item in state["issues"]):
        raise FeatureInputError("Enter a unique issue id.")
    files = _issue_files(ctx, values["folder"])
    issue = {
        "id": issue_id,
        "title": values["title"].strip(),
        "folder": values["folder"].replace("\\", "/"),
        "files": files,
        "createdBy": values["createdBy"].strip() or "Unknown",
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "Draft",
        "readOnly": False,
    }
    state["issues"].append(issue)
    _log_event(
        state, "issueSet", f"Created {issue_id} with {len(files)} files.", issue["createdBy"]
    )
    _save(ctx, state)
    return result(
        summary={
            "issueId": issue_id,
            "fileCount": len(files),
            "totalBytes": sum(item["bytes"] for item in files),
            "status": issue["status"],
        },
        tables=[
            table(
                "Issue files", [("path", "File"), ("bytes", "Bytes"), ("sha256", "SHA-256")], files
            )
        ],
    )


@feature(
    "documentsReportDistribution.recipients",
    "Recipients",
    part="settings",
    fields=[
        text("issueId", "Issue id", "ISS-001"),
        text("recipients", "Recipients as Name <email>; separated by semicolons", ""),
        text("cc", "CC recipients, same format", ""),
    ],
)
def issue_recipients(ctx: FeatureContext, values: dict) -> dict:
    """Assign validated named recipients to an unlocked issue without contacting them."""
    state = _state(ctx)
    issue = _issue(state, values["issueId"], editable=True)
    parsed = []
    for raw in (values["recipients"] + ";" + values["cc"]).split(";"):
        raw = raw.strip()
        if not raw:
            continue
        match = re.fullmatch(r"(?:(.*?)\s*)?<([^<>\s]+@[^<>\s]+)>|([^<>\s]+@[^<>\s]+)", raw)
        if not match:
            raise FeatureInputError(f"Recipient {raw!r} must be an email address or Name <email>.")
        email = match.group(2) or match.group(3)
        parsed.append(
            {
                "name": (match.group(1) or email.split("@", 1)[0]).strip(),
                "email": email,
                "kind": "cc" if raw in values["cc"].split(";") else "to",
            }
        )
    if not parsed:
        raise FeatureInputError("Enter at least one recipient.")
    if len({item["email"].casefold() for item in parsed}) != len(parsed):
        raise FeatureInputError("Each email address may appear once per issue.")
    issue["recipients"] = parsed
    issue["updatedAt"] = datetime.now(UTC).isoformat(timespec="seconds")
    _log_event(state, "recipients", f"Set {len(parsed)} recipients on {issue['id']}.")
    _save(ctx, state)
    return result(
        summary={
            "issueId": issue["id"],
            "recipientCount": len(parsed),
            "ccCount": sum(item["kind"] == "cc" for item in parsed),
        },
        tables=[
            table(
                "Issue recipients",
                [("name", "Name"), ("email", "Email"), ("kind", "To/CC")],
                parsed,
            )
        ],
        notes=["Recipients were recorded; no email was sent."],
    )


@feature(
    "documentsReportDistribution.dueDate",
    "Due Date",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("dueDate", "Response due date (YYYY-MM-DD)", "2026-12-31"),
        text("statusFilter", "Overdue status filter", ""),
    ],
)
def due_date(ctx: FeatureContext, values: dict) -> dict:
    """Set a due date on a specific transmittal and list all overdue transmittals with outstanding responses."""
    try:
        due = date.fromisoformat(values["dueDate"])
    except ValueError as exc:
        raise FeatureInputError("Enter the due date in YYYY-MM-DD format.") from exc
    state = _state(ctx)
    target = next(
        (
            item
            for item in state["transmittals"]
            if item.get("id") == values["transmittalId"].strip()
        ),
        None,
    )
    if target is None:
        raise FeatureInputError("Create the transmittal before assigning its response due date.")
    if target.get("readOnly"):
        raise FeatureInputError("The transmittal is locked and its due date cannot be changed.")
    target["dueDate"] = due.isoformat()
    target["dueDateUpdatedAt"] = datetime.now(UTC).isoformat(timespec="seconds")
    overdue = [
        item
        for item in state["transmittals"]
        if item.get("dueDate")
        and date.fromisoformat(item["dueDate"]) < date.today()
        and item.get("status") not in ("Complete", "Closed")
    ]
    _log_event(state, "dueDate", f"Set {target['id']} due {due.isoformat()}.")
    _save(ctx, state)
    return result(
        summary={
            "transmittalId": target["id"],
            "dueDate": due.isoformat(),
            "overdueTransmittalCount": len(overdue),
        },
        tables=[
            table(
                "Overdue transmittals",
                [
                    ("id", "Transmittal"),
                    ("recipient", "Recipient"),
                    ("dueDate", "Due date"),
                    ("status", "Status"),
                ],
                overdue,
            )
        ],
        notes=["Due dates are stored independently on each transmittal record."],
    )


@feature(
    "documentsReportDistribution.lockIssue",
    "Lock Issue",
    part="settings",
    fields=[
        text("issueId", "Issue id", "ISS-001"),
        text("lockedBy", "Locked by", ""),
        text("reason", "Lock reason", "Approved for distribution"),
    ],
)
def lock_issue(ctx: FeatureContext, values: dict) -> dict:
    """Lock issue contents read-only and record the person and UTC time that applied the lock."""
    if not values["lockedBy"].strip():
        raise FeatureInputError("Enter the name of the person locking this issue.")
    state = _state(ctx)
    issue = _issue(state, values["issueId"])
    if issue.get("readOnly"):
        raise FeatureInputError("This issue is already locked read-only.")
    issue.update(
        readOnly=True,
        status="Locked",
        lockedBy=values["lockedBy"].strip(),
        lockedAt=datetime.now(UTC).isoformat(timespec="seconds"),
        lockReason=values["reason"].strip(),
    )
    _log_event(
        state, "lockIssue", f"Locked {issue['id']}: {issue['lockReason']}", issue["lockedBy"]
    )
    _save(ctx, state)
    return result(
        summary={
            "issueId": issue["id"],
            "readOnly": True,
            "lockedBy": issue["lockedBy"],
            "lockedAt": issue["lockedAt"],
        },
        notes=["Issue metadata and file checksums are now read-only."],
    )


@feature(
    "documentsReportDistribution.createTransmittal",
    "Create Transmittal",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("issueId", "Issue id", "ISS-001"),
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
        text("preparedBy", "Prepared by", ""),
    ],
)
def create_transmittal(ctx: FeatureContext, values: dict) -> dict:
    """Create a distinct transmittal for an issue snapshot with its own recipients, files and response state."""
    state = _state(ctx)
    issue = _issue(state, values["issueId"])
    if not issue.get("readOnly"):
        raise FeatureInputError("Lock the issue before creating a controlled transmittal.")
    transmittal_id = values["transmittalId"].strip()
    if not transmittal_id or any(
        item.get("id") == transmittal_id for item in state["transmittals"]
    ):
        raise FeatureInputError("Enter a unique transmittal id.")
    trans = {
        "id": transmittal_id,
        "issueId": issue["id"],
        "title": issue["title"],
        "purpose": values["purpose"],
        "preparedBy": values["preparedBy"].strip() or "Unknown",
        "recipients": list(issue.get("recipients", [])),
        "files": list(issue["files"]),
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "status": "Sent",
        "readOnly": False,
    }
    state["transmittals"].append(trans)
    _log_event(
        state,
        "createTransmittal",
        f"Created {transmittal_id} for {issue['id']}.",
        trans["preparedBy"],
    )
    _save(ctx, state)
    return result(
        summary={
            "transmittalId": transmittal_id,
            "issueId": issue["id"],
            "fileCount": len(trans["files"]),
            "recipientCount": len(trans["recipients"]),
            "purpose": trans["purpose"],
        },
        tables=[
            table(
                "Transmittal file list",
                [("name", "File"), ("bytes", "Bytes"), ("sha256", "SHA-256")],
                trans["files"],
            )
        ],
    )


@feature(
    "documentsReportDistribution.coverSheet",
    "Cover Sheet",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("organisation", "Recipient organisation", ""),
        text("attention", "Attention", ""),
        text("message", "Cover message", "Please review the enclosed structural report."),
        text("outputName", "Markdown output name", "transmittal-cover.md"),
    ],
)
def cover_sheet(ctx: FeatureContext, values: dict) -> dict:
    """Create a printable transmittal cover sheet with the issue's actual file inventory and response due date."""
    root = require_root(ctx)
    state = _state(ctx)
    trans = next(
        (
            item
            for item in state["transmittals"]
            if item.get("id") == values["transmittalId"].strip()
        ),
        None,
    )
    if trans is None:
        raise FeatureInputError("Create the transmittal before its cover sheet.")
    if trans.get("readOnly"):
        raise FeatureInputError("This transmittal is locked read-only.")
    lines = [
        f"# Transmittal {trans['id']}",
        "",
        f"**To:** {values['organisation'].strip() or 'Recipient'}",
        f"**Attention:** {values['attention'].strip() or 'Project team'}",
        f"**Issue:** {trans['issueId']} — {trans['title']}",
        f"**Purpose:** {trans['purpose']}",
        f"**Due date:** {trans.get('dueDate') or 'Not set'}",
        "",
        values["message"].strip(),
        "",
        "## Enclosed files",
        "",
    ]
    lines.extend(
        f"- {item['name']} ({item['bytes']} bytes; SHA-256 `{item['sha256']}`)"
        for item in trans["files"]
    )
    name = Path(values["outputName"].strip() or "transmittal-cover.md").name
    path = root / "11 Exports" / "Transmittals" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    trans["coverSheet"] = path.relative_to(root).as_posix()
    _save(ctx, state)
    return result(
        summary={
            "transmittalId": trans["id"],
            "coverSheet": trans["coverSheet"],
            "fileCount": len(trans["files"]),
        }
    )


@feature(
    "documentsReportDistribution.purposeCode",
    "Purpose Code",
    part="settings",
    fields=[
        text("issueId", "Issue id", "ISS-001"),
        select(
            "code",
            "Issue purpose",
            [
                ("IFA", "Issued for approval"),
                ("IFC", "Issued for construction"),
                ("IFR", "Issued for review"),
                ("IFI", "Issued for information"),
                ("AB", "As built"),
            ],
            "IFR",
        ),
        text("note", "Purpose note", ""),
    ],
)
def purpose_code(ctx: FeatureContext, values: dict) -> dict:
    """Set the controlled purpose code and note on an unlocked issue snapshot."""
    state = _state(ctx)
    issue = _issue(state, values["issueId"], editable=True)
    issue["purposeCode"] = values["code"]
    issue["purposeNote"] = values["note"].strip()
    issue["updatedAt"] = datetime.now(UTC).isoformat(timespec="seconds")
    _log_event(state, "purposeCode", f"Set {issue['id']} to {values['code']}.")
    _save(ctx, state)
    return result(
        summary={
            "issueId": issue["id"],
            "purposeCode": issue["purposeCode"],
            "note": issue["purposeNote"],
        }
    )


@feature(
    "documentsReportDistribution.transmittalLog",
    "Transmittal Log",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id (blank means all)", ""),
        checkbox("includeFiles", "Include file counts", True),
    ],
)
def transmittal_log(ctx: FeatureContext, values: dict) -> dict:
    """List transmittals with individual due dates, recipients, response states and optional file counts."""
    state = _state(ctx)
    rows = []
    for trans in state["transmittals"]:
        if values["transmittalId"].strip() and trans.get("id") != values["transmittalId"].strip():
            continue
        rows.append(
            {
                "id": trans["id"],
                "issueId": trans["issueId"],
                "purpose": trans["purpose"],
                "recipientCount": len(trans.get("recipients", [])),
                "dueDate": trans.get("dueDate", ""),
                "status": trans.get("status", ""),
                "fileCount": len(trans.get("files", [])) if values["includeFiles"] else None,
            }
        )
    overdue = [
        row
        for row in rows
        if row["dueDate"]
        and date.fromisoformat(row["dueDate"]) < date.today()
        and row["status"] not in ("Complete", "Closed")
    ]
    return result(
        summary={"transmittalCount": len(rows), "overdueCount": len(overdue)},
        tables=[
            table(
                "Transmittal log",
                [
                    ("id", "Id"),
                    ("issueId", "Issue"),
                    ("purpose", "Purpose"),
                    ("recipientCount", "Recipients"),
                    ("dueDate", "Due date"),
                    ("status", "Status"),
                    ("fileCount", "Files"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsReportDistribution.emailPackage",
    "Email Package",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("outputName", "Package name", "transmittal-package.zip"),
        number("maxPartMb", "Maximum email part size", 20, unit="MB", min=1, max=200),
    ],
)
def email_package(ctx: FeatureContext, values: dict) -> dict:
    """Build a checksummed email attachment package and an .eml draft, splitting large files into size-limited parts."""
    from email.message import EmailMessage

    root = require_root(ctx)
    state = _state(ctx)
    trans = next(
        (
            item
            for item in state["transmittals"]
            if item.get("id") == values["transmittalId"].strip()
        ),
        None,
    )
    if trans is None:
        raise FeatureInputError("Create a transmittal before preparing its email package.")
    paths = []
    for entry in trans["files"]:
        path = (root / entry["path"]).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise FeatureInputError("Transmittal contains a file outside the project.") from exc
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise FeatureInputError(f"Transmitted file {entry['name']} is missing or has changed.")
        paths.append(path)
    max_bytes = int(values["maxPartMb"] * 1024 * 1024)
    name = Path(values["outputName"].strip() or "transmittal-package.zip").name
    if not name.lower().endswith(".zip"):
        name += ".zip"
    target = root / "11 Exports" / "Transmittals" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    parts, current, size = [], [], 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path in paths:
            data = path.read_bytes()
            if len(data) > max_bytes:
                parts.append({"name": path.name, "bytes": len(data), "splitRequired": True})
                package.write(path, path.name)
            else:
                current.append(path)
                size += len(data)
                if size >= max_bytes:
                    parts.append(
                        {"part": len(parts) + 1, "files": [p.name for p in current], "bytes": size}
                    )
                    current, size = [], 0
                package.write(path, path.name)
        if current:
            parts.append(
                {"part": len(parts) + 1, "files": [p.name for p in current], "bytes": size}
            )
        package.writestr(
            "transmittal.json",
            json.dumps(
                {
                    "id": trans["id"],
                    "issueId": trans["issueId"],
                    "dueDate": trans.get("dueDate"),
                    "parts": parts,
                },
                indent=2,
            )
            + "\n",
        )
    message = EmailMessage()
    message["To"] = ", ".join(
        item["email"] for item in trans.get("recipients", []) if item.get("kind") == "to"
    )
    message["Cc"] = ", ".join(
        item["email"] for item in trans.get("recipients", []) if item.get("kind") == "cc"
    )
    message["Subject"] = f"Transmittal {trans['id']}: {trans['purpose']}"
    message.set_content(
        f"Please find transmittal {trans['id']} and issue {trans['issueId']} attached. Due date: {trans.get('dueDate') or 'not set'}.\n"
    )
    eml = target.with_suffix(".eml")
    eml.write_bytes(message.as_bytes())
    trans["emailDraft"] = eml.relative_to(root).as_posix()
    _log_event(state, "emailPackage", f"Prepared email package {target.name}.")
    _save(ctx, state)
    return result(
        summary={
            "package": target.relative_to(root).as_posix(),
            "emailDraft": trans["emailDraft"],
            "fileCount": len(paths),
            "partCount": len(parts),
        },
        tables=[
            table(
                "Email package parts",
                [
                    ("part", "Part"),
                    ("files", "Files"),
                    ("bytes", "Bytes"),
                    ("splitRequired", "Oversize file"),
                ],
                parts,
            )
        ],
        notes=["The .eml file is a draft; it has not been sent."],
    )


@feature(
    "documentsReportDistribution.portalUpload",
    "Portal Upload",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("portalFolder", "Project-relative portal handoff folder", "11 Exports/Portal"),
        text("packageName", "Package name", ""),
    ],
)
def portal_upload(ctx: FeatureContext, values: dict) -> dict:
    """Copy a validated transmittal package into a project-local portal handoff folder without network access."""
    root = require_root(ctx)
    state = _state(ctx)
    trans = next(
        (
            item
            for item in state["transmittals"]
            if item.get("id") == values["transmittalId"].strip()
        ),
        None,
    )
    if trans is None or not trans.get("emailDraft"):
        raise FeatureInputError("Prepare the transmittal package before creating a portal handoff.")
    package = Path(trans["emailDraft"]).with_suffix(".zip")
    source = (root / package).resolve()
    target_dir = (root / values["portalFolder"]).resolve()
    try:
        source.relative_to(root.resolve())
        target_dir.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Portal handoff paths must remain inside the project.") from exc
    if not source.is_file():
        raise FeatureInputError("Transmittal package file is missing.")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / (
        Path(values["packageName"].strip()).name if values["packageName"].strip() else source.name
    )
    shutil.copyfile(source, target)
    trans["portalHandoff"] = target.relative_to(root).as_posix()
    trans["portalChecksum"] = hashlib.sha256(target.read_bytes()).hexdigest()
    _save(ctx, state)
    return result(
        summary={
            "handoffPath": trans["portalHandoff"],
            "sha256": trans["portalChecksum"],
            "networkUploadPerformed": False,
        },
        notes=["This creates a local handoff copy; a connected portal is not accessed."],
    )


@feature(
    "documentsReportDistribution.linkExpiry",
    "Link Expiry",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("expiresOn", "Expiry date (YYYY-MM-DD)", "2027-01-31"),
        text("linkName", "Link label", "Issue download"),
    ],
)
def link_expiry(ctx: FeatureContext, values: dict) -> dict:
    """Set an expiry date for a shareable local handoff link and list links already past expiry."""
    try:
        expiry = date.fromisoformat(values["expiresOn"])
    except ValueError as exc:
        raise FeatureInputError("Use YYYY-MM-DD for the link expiry date.") from exc
    state = _state(ctx)
    trans = next(
        (
            item
            for item in state["transmittals"]
            if item.get("id") == values["transmittalId"].strip()
        ),
        None,
    )
    if trans is None:
        raise FeatureInputError("Create the transmittal before defining a share link.")
    link = {
        "label": values["linkName"].strip(),
        "expiresOn": expiry.isoformat(),
        "active": expiry >= date.today(),
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    trans.setdefault("links", []).append(link)
    expired = [
        {"transmittalId": item["id"], "label": row["label"], "expiresOn": row["expiresOn"]}
        for item in state["transmittals"]
        for row in item.get("links", [])
        if date.fromisoformat(row["expiresOn"]) < date.today()
    ]
    _save(ctx, state)
    return result(
        summary={
            "transmittalId": trans["id"],
            "expiresOn": link["expiresOn"],
            "active": link["active"],
            "expiredLinkCount": len(expired),
        },
        tables=[
            table(
                "Expired share links",
                [("transmittalId", "Transmittal"), ("label", "Link"), ("expiresOn", "Expired on")],
                expired,
            )
        ],
    )


@feature(
    "documentsReportDistribution.deliveryReceipts",
    "Delivery Receipts",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("recipientEmail", "Recipient email", "reviewer@example.com"),
        select(
            "receipt",
            "Delivery result",
            [("delivered", "Delivered"), ("bounced", "Bounced"), ("acknowledged", "Acknowledged")],
            "delivered",
        ),
        text("receivedAt", "Receipt date (YYYY-MM-DD)", "2026-01-01"),
        text("note", "Receipt note", ""),
    ],
)
def delivery_receipts(ctx: FeatureContext, values: dict) -> dict:
    """Record a recipient delivery or acknowledgement receipt with a validated date and issue reference."""
    try:
        date.fromisoformat(values["receivedAt"])
    except ValueError as exc:
        raise FeatureInputError("Use YYYY-MM-DD for the delivery receipt date.") from exc
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", values["recipientEmail"].strip()):
        raise FeatureInputError("Enter a valid recipient email address.")
    state = _state(ctx)
    trans = next(
        (
            item
            for item in state["transmittals"]
            if item.get("id") == values["transmittalId"].strip()
        ),
        None,
    )
    if trans is None:
        raise FeatureInputError("The transmittal id was not found.")
    receipt = {
        "recipientEmail": values["recipientEmail"].strip(),
        "result": values["receipt"],
        "receivedAt": values["receivedAt"],
        "note": values["note"].strip(),
        "recordedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    trans.setdefault("receipts", []).append(receipt)
    if receipt["result"] == "acknowledged":
        trans["status"] = "Acknowledged"
    _save(ctx, state)
    return result(
        summary={
            "transmittalId": trans["id"],
            "receipt": receipt["result"],
            "receiptCount": len(trans["receipts"]),
        },
        tables=[
            table(
                "Delivery receipts",
                [
                    ("recipientEmail", "Recipient"),
                    ("result", "Result"),
                    ("receivedAt", "Date"),
                    ("note", "Note"),
                ],
                trans["receipts"],
            )
        ],
    )


@feature(
    "documentsReportDistribution.watermarkDocument",
    "Watermark Document",
    part="settings",
    fields=[
        text("inputPdf", "Project-relative source PDF", "11 Exports/report.pdf"),
        text("watermark", "Watermark text", "CONFIDENTIAL"),
        number("opacity", "Opacity", 0.18, min=0.01, max=1),
        text("outputPdf", "Project-relative output PDF", "11 Exports/report-confidential.pdf"),
    ],
)
def watermark_document(ctx: FeatureContext, values: dict) -> dict:
    """Apply a text watermark to every page of an existing PDF and write a separate distribution copy."""
    root = require_root(ctx)
    source, target = (root / values["inputPdf"]).resolve(), (root / values["outputPdf"]).resolve()
    try:
        source.relative_to(root.resolve())
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Source and output PDF paths must be inside the project.") from exc
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise FeatureInputError("Choose an existing project PDF.")
    try:
        from io import BytesIO

        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas

        reader = PdfReader(str(source))
        writer = PdfWriter()
        for page in reader.pages:
            buffer = BytesIO()
            width, height = float(page.mediabox.width), float(page.mediabox.height)
            painter = canvas.Canvas(buffer, pagesize=(width, height))
            painter.saveState()
            painter.setFillAlpha(values["opacity"])
            painter.setFont("Helvetica-Bold", max(20, min(width, height) / 12))
            painter.translate(width / 2, height / 2)
            painter.rotate(45)
            painter.drawCentredString(0, 0, values["watermark"].strip())
            painter.restoreState()
            painter.save()
            buffer.seek(0)
            page.merge_page(PdfReader(buffer).pages[0])
            writer.add_page(page)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as stream:
            writer.write(stream)
    except (ImportError, OSError, ValueError) as exc:
        raise FeatureInputError(f"Could not watermark the PDF: {exc}") from exc
    return result(
        summary={
            "source": source.relative_to(root).as_posix(),
            "watermarkedPdf": target.relative_to(root).as_posix(),
            "pageCount": len(reader.pages),
            "watermark": values["watermark"].strip(),
        }
    )


@feature(
    "documentsReportDistribution.digitalSignature",
    "Digital Signature",
    part="settings",
    fields=[
        text(
            "packagePath",
            "Project-relative package file",
            "11 Exports/Transmittals/transmittal-package.zip",
        ),
        text(
            "privateKeyPath",
            "Project-relative Ed25519 private key PEM",
            "11 Exports/keys/signing-key.pem",
        ),
        text("password", "Key password (optional)", ""),
    ],
)
def sign_distribution(ctx: FeatureContext, values: dict) -> dict:
    """Sign an immutable report package checksum with a project-held Ed25519 private key."""
    root = require_root(ctx)
    package, key_file = (
        (root / values["packagePath"]).resolve(),
        (root / values["privateKeyPath"]).resolve(),
    )
    try:
        package.relative_to(root.resolve())
        key_file.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Package and signing key must be inside the project.") from exc
    if not package.is_file():
        raise FeatureInputError("The package file does not exist.")
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = serialization.load_pem_private_key(
            key_file.read_bytes(), password=values["password"].encode() or None
        )
        if not isinstance(key, Ed25519PrivateKey):
            raise FeatureInputError("The private key must use Ed25519.")
    except FeatureInputError:
        raise
    except (OSError, ValueError, TypeError, ImportError) as exc:
        raise FeatureInputError("Could not load a project Ed25519 private key.") from exc
    digest = hashlib.sha256(package.read_bytes()).digest()
    signature = key.sign(digest)
    signature_path = package.with_suffix(package.suffix + ".sig.json")
    signature_path.write_text(
        json.dumps(
            {
                "algorithm": "Ed25519",
                "file": package.name,
                "sha256": digest.hex(),
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
            "package": package.relative_to(root).as_posix(),
            "signatureFile": signature_path.relative_to(root).as_posix(),
            "sha256": digest.hex(),
            "algorithm": "Ed25519",
        }
    )


@feature(
    "documentsReportDistribution.permissionPolicy",
    "Permission Policy",
    part="settings",
    fields=[
        text("sourcePdf", "Project-relative source PDF", "11 Exports/report.pdf"),
        text("outputPdf", "Protected PDF output", "11 Exports/report-protected.pdf"),
        text("userPassword", "Recipient password", ""),
        text("ownerPassword", "Owner password", ""),
        checkbox("allowPrinting", "Allow printing", True),
        checkbox("allowCopying", "Allow copying text", False),
    ],
)
def permission_policy(ctx: FeatureContext, values: dict) -> dict:
    """Apply PDF encryption and per-user print/copy permissions to a distribution copy."""
    root = require_root(ctx)
    source, target = (root / values["sourcePdf"]).resolve(), (root / values["outputPdf"]).resolve()
    try:
        source.relative_to(root.resolve())
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError(
            "Source and protected PDF paths must stay inside the project."
        ) from exc
    if not source.is_file() or not values["userPassword"] or not values["ownerPassword"]:
        raise FeatureInputError(
            "Choose an existing PDF and provide distinct recipient and owner passwords."
        )
    try:
        from pypdf import PdfReader, PdfWriter

        writer = PdfWriter()
        writer.append(PdfReader(str(source)))
        writer.encrypt(
            values["userPassword"],
            values["ownerPassword"],
            permissions_flag=(4 if values["allowPrinting"] else 0)
            | (16 if values["allowCopying"] else 0),
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as stream:
            writer.write(stream)
    except (ImportError, OSError, ValueError) as exc:
        raise FeatureInputError(f"Could not apply PDF permissions: {exc}") from exc
    return result(
        summary={
            "protectedPdf": target.relative_to(root).as_posix(),
            "printingAllowed": values["allowPrinting"],
            "copyingAllowed": values["allowCopying"],
            "pageCount": len(writer.pages),
        }
    )


@feature(
    "documentsReportDistribution.revokeDistribution",
    "Revoke Distribution",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("reason", "Revocation reason", "Superseded by revised issue"),
        text("revokedBy", "Revoked by", ""),
    ],
)
def revoke_distribution(ctx: FeatureContext, values: dict) -> dict:
    """Revoke a transmittal's active local share links and record who revoked them and why."""
    state = _state(ctx)
    trans = next(
        (
            item
            for item in state["transmittals"]
            if item.get("id") == values["transmittalId"].strip()
        ),
        None,
    )
    if trans is None:
        raise FeatureInputError("The transmittal id was not found.")
    changed = 0
    for link in trans.get("links", []):
        if link.get("active"):
            link["active"] = False
            link["revokedAt"] = datetime.now(UTC).isoformat(timespec="seconds")
            changed += 1
    trans["status"] = "Revoked"
    trans["revocation"] = {
        "reason": values["reason"].strip(),
        "by": values["revokedBy"].strip() or "Unknown",
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _log_event(
        state,
        "revokeDistribution",
        f"Revoked {trans['id']}: {trans['revocation']['reason']}",
        trans["revocation"]["by"],
    )
    _save(ctx, state)
    return result(
        summary={
            "transmittalId": trans["id"],
            "revokedLinkCount": changed,
            "status": trans["status"],
        }
    )


@feature(
    "documentsReportDistribution.createArchive",
    "Create Archive",
    part="settings",
    fields=[
        text("issueId", "Issue id", "ISS-001"),
        text("archiveName", "Archive name", "report-archive.zip"),
        checkbox("includeAudit", "Include issue audit history", True),
    ],
)
def create_archive(ctx: FeatureContext, values: dict) -> dict:
    """Bundle every checksummed issue file, its frozen manifest and optionally issue audit history into a ZIP."""
    root = require_root(ctx)
    state = _state(ctx)
    issue = _issue(state, values["issueId"])
    name = Path(values["archiveName"].strip() or "report-archive.zip").name
    if not name.lower().endswith(".zip"):
        name += ".zip"
    target = root / "11 Exports" / "Archive" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for entry in issue["files"]:
            path = (root / entry["path"]).resolve()
            try:
                path.relative_to(root.resolve())
            except ValueError as exc:
                raise FeatureInputError("Issue file path escaped the project folder.") from exc
            if (
                not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
            ):
                raise FeatureInputError(f"Issue file {entry['name']} is missing or changed.")
            archive.write(path, entry["path"])
        archive.writestr(
            "issue-manifest.json", json.dumps(issue, ensure_ascii=False, indent=2) + "\n"
        )
        if values["includeAudit"]:
            archive.writestr(
                "audit-history.json",
                json.dumps(state["events"], ensure_ascii=False, indent=2) + "\n",
            )
    issue["archive"] = target.relative_to(root).as_posix()
    _save(ctx, state)
    return result(
        summary={
            "archive": issue["archive"],
            "fileCount": len(issue["files"]),
            "bytes": target.stat().st_size,
        }
    )


@feature(
    "documentsReportDistribution.retentionRules",
    "Retention Rules",
    part="settings",
    fields=[
        number("retainDays", "Keep issued records for", 2555, unit="day", min=1),
        text("ruleName", "Rule name", "Seven year issue retention"),
        checkbox("includeArchives", "Include archived packages", True),
    ],
)
def retention_rules(ctx: FeatureContext, values: dict) -> dict:
    """Define retention periods for transmittal and archive records and list records currently beyond the cutoff."""
    cutoff = date.today() - timedelta(days=int(values["retainDays"]))
    state = _state(ctx)
    rule = {
        "name": values["ruleName"].strip(),
        "retainDays": int(values["retainDays"]),
        "includeArchives": values["includeArchives"],
        "cutoffDate": cutoff.isoformat(),
        "updatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    state.setdefault("retentionRules", []).append(rule)
    eligible = [
        {"kind": "transmittal", "id": item["id"], "date": item.get("createdAt", "")[:10]}
        for item in state["transmittals"]
        if item.get("createdAt", "")[:10] and date.fromisoformat(item["createdAt"][:10]) < cutoff
    ]
    if values["includeArchives"]:
        eligible.extend(
            {"kind": "archive", "id": item["id"], "date": item.get("createdAt", "")[:10]}
            for item in state["issues"]
            if item.get("archive")
            and item.get("createdAt", "")[:10]
            and date.fromisoformat(item["createdAt"][:10]) < cutoff
        )
    _save(ctx, state)
    return result(
        summary={
            "ruleName": rule["name"],
            "cutoffDate": cutoff.isoformat(),
            "eligibleRecordCount": len(eligible),
        },
        tables=[
            table(
                "Records past retention cutoff",
                [("kind", "Record type"), ("id", "Id"), ("date", "Created")],
                eligible,
            )
        ],
        notes=["The rule identifies records for review; it does not automatically delete records."],
    )


@feature(
    "documentsReportDistribution.checksumVerification",
    "Checksum Verification",
    part="settings",
    fields=[text("issueId", "Issue id", "ISS-001")],
)
def checksum_verification(ctx: FeatureContext, values: dict) -> dict:
    """Recompute SHA-256 for every issue file and compare it with the frozen issue-set manifest."""
    root = require_root(ctx)
    state = _state(ctx)
    issue = _issue(state, values["issueId"])
    rows = []
    for entry in issue["files"]:
        path = (root / entry["path"]).resolve()
        try:
            path.relative_to(root.resolve())
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
        except (ValueError, OSError):
            digest = ""
        rows.append(
            {
                "path": entry["path"],
                "expected": entry["sha256"],
                "actual": digest,
                "status": "match"
                if digest and digest == entry["sha256"]
                else "missing"
                if not digest
                else "changed",
            }
        )
    return result(
        summary={
            "fileCount": len(rows),
            "verifiedCount": sum(row["status"] == "match" for row in rows),
            "mismatchCount": sum(row["status"] != "match" for row in rows),
        },
        tables=[
            table(
                "Issue checksum verification",
                [
                    ("path", "File"),
                    ("expected", "Recorded SHA-256"),
                    ("actual", "Current SHA-256"),
                    ("status", "Result"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsReportDistribution.readReceipts",
    "Read Receipts",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("recipientEmail", "Recipient email", "reviewer@example.com"),
        text("readDate", "Read date (YYYY-MM-DD)", "2026-01-02"),
        checkbox("downloaded", "Recipient downloaded package", True),
    ],
)
def read_receipts(ctx: FeatureContext, values: dict) -> dict:
    """Record a recipient read/download receipt against its transmittal and report outstanding recipients."""
    try:
        date.fromisoformat(values["readDate"])
    except ValueError as exc:
        raise FeatureInputError("Use YYYY-MM-DD for the read date.") from exc
    state = _state(ctx)
    trans = next(
        (
            item
            for item in state["transmittals"]
            if item.get("id") == values["transmittalId"].strip()
        ),
        None,
    )
    if trans is None:
        raise FeatureInputError("The transmittal id was not found.")
    receipt = {
        "email": values["recipientEmail"].strip(),
        "readDate": values["readDate"],
        "downloaded": values["downloaded"],
        "recordedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", receipt["email"]):
        raise FeatureInputError("Enter a valid recipient email.")
    trans.setdefault("readReceipts", []).append(receipt)
    read_emails = {row["email"].casefold() for row in trans["readReceipts"]}
    outstanding = [
        item["email"]
        for item in trans.get("recipients", [])
        if item["email"].casefold() not in read_emails
    ]
    _save(ctx, state)
    return result(
        summary={
            "transmittalId": trans["id"],
            "receiptCount": len(trans["readReceipts"]),
            "outstandingRecipientCount": len(outstanding),
        },
        tables=[
            table(
                "Outstanding recipients",
                [("email", "Recipient")],
                [{"email": email} for email in outstanding],
            )
        ],
    )


@feature(
    "documentsReportDistribution.downloadCounter",
    "Download Counter",
    part="settings",
    fields=[
        text("transmittalId", "Transmittal id", "TR-001"),
        text("recipientEmail", "Recipient email", "reviewer@example.com"),
        number("downloadCount", "Number of downloads", 1, min=1),
        text("downloadedAt", "Download date (YYYY-MM-DD)", "2026-01-02"),
    ],
)
def download_counter(ctx: FeatureContext, values: dict) -> dict:
    """Increment a per-recipient package-download count and preserve its dated audit entry."""
    try:
        date.fromisoformat(values["downloadedAt"])
    except ValueError as exc:
        raise FeatureInputError("Use YYYY-MM-DD for the download date.") from exc
    state = _state(ctx)
    trans = next(
        (
            item
            for item in state["transmittals"]
            if item.get("id") == values["transmittalId"].strip()
        ),
        None,
    )
    if trans is None:
        raise FeatureInputError("The transmittal id was not found.")
    email = values["recipientEmail"].strip().casefold()
    counts = trans.setdefault("downloadCounts", {})
    counts[email] = int(counts.get(email, 0)) + int(values["downloadCount"])
    trans.setdefault("downloadLog", []).append(
        {"email": email, "count": int(values["downloadCount"]), "date": values["downloadedAt"]}
    )
    _save(ctx, state)
    return result(
        summary={
            "transmittalId": trans["id"],
            "recipient": email,
            "recipientDownloadCount": counts[email],
            "totalDownloadCount": sum(counts.values()),
        },
        tables=[
            table(
                "Downloads by recipient",
                [("email", "Recipient"), ("count", "Downloads")],
                [{"email": key, "count": count} for key, count in counts.items()],
            )
        ],
    )


@feature(
    "documentsReportDistribution.auditHistory",
    "Audit History",
    part="settings",
    fields=[
        number("limit", "Recent audit events", 100, min=1, max=1000),
        text("actor", "Filter by actor", ""),
    ],
)
def audit_history(ctx: FeatureContext, values: dict) -> dict:
    """Display timestamped issue, transmittal, lock and distribution actions with an optional actor filter."""
    state = _state(ctx)
    actor = values["actor"].strip().casefold()
    rows = [
        row for row in state["events"] if not actor or actor in row.get("actor", "").casefold()
    ][-int(values["limit"]) :]
    return result(
        summary={
            "auditEventCount": len(rows),
            "issueCount": len(state["issues"]),
            "transmittalCount": len(state["transmittals"]),
        },
        tables=[
            table(
                "Document distribution audit history",
                [("at", "UTC time"), ("event", "Event"), ("actor", "Actor"), ("detail", "Details")],
                list(reversed(rows)),
            )
        ],
    )


def _link(ctx: FeatureContext, link_id: str, *, editable: bool = False) -> dict:
    state = _state(ctx)
    item = next((link for link in state["links"] if link.get("id") == link_id.strip()), None)
    if item is None:
        raise FeatureInputError(f"Data link {link_id!r} does not exist.")
    if editable and item.get("unlinked"):
        raise FeatureInputError("This source was unlinked and its captured values are static.")
    return item


def _resolve_link(ctx: FeatureContext, link: dict) -> Any:
    kind = link.get("kind")
    if kind == "model":
        return dotted_value(project_fields(ctx).get(link["part"], {}), link["path"])
    if kind == "worksheet":
        from saengine.features.documents_common import cell_value, range_cells, worksheet_workspace

        _sheet, workspace = worksheet_workspace(ctx, link["worksheetId"])
        addresses = range_cells(link["range"])
        return [
            {
                "cell": address,
                "value": cell_value(address, workspace)
                if workspace.get("cells", {}).get(address, {}).get("formula")
                else workspace.get("cells", {}).get(address, {}).get("value"),
                "unit": workspace.get("cells", {}).get(address, {}).get("unit"),
            }
            for address in addresses
        ]
    if kind == "sqlite":
        root = require_root(ctx)
        path = (root / link["database"]).resolve()
        try:
            path.relative_to(root.resolve())
            uri = f"file:{path.as_posix()}?mode=ro"
            with sqlite3.connect(uri, uri=True) as connection:
                connection.row_factory = sqlite3.Row
                cursor = connection.execute(link["query"], link.get("parameters", []))
                return [dict(row) for row in cursor.fetchmany(10000)]
        except (ValueError, sqlite3.Error, OSError) as exc:
            raise FeatureInputError(f"Read-only database query failed: {exc}") from exc
    if kind == "localApi":
        root = require_root(ctx)
        path = (root / link["snapshotPath"]).resolve()
        try:
            path.relative_to(root.resolve())
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            raise FeatureInputError("The local JSON API snapshot could not be read.") from exc
    return link.get("currentData")


@feature(
    "documentsReportDataLinks.linkModel",
    "Link Model",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        text("part", "Project part id", "bim"),
        text("path", "Data path in part", "elements"),
        text("description", "Link description", "Building model elements"),
    ],
)
def link_model_data(ctx: FeatureContext, values: dict) -> dict:
    """Create a live report link to an actual project part path and capture its current resolved value."""
    state = _state(ctx)
    parts = project_fields(ctx)
    if values["part"] not in parts:
        raise FeatureInputError("Select a readable project part id.")
    resolved = dotted_value(parts[values["part"]], values["path"])
    if resolved is None:
        raise FeatureInputError("The data path does not resolve in the selected project part.")
    link_id = values["linkId"].strip()
    if not link_id:
        raise FeatureInputError("Enter a data link id.")
    record = {
        "id": link_id,
        "kind": "model",
        "part": values["part"],
        "path": values["path"].strip(),
        "description": values["description"].strip(),
        "currentData": resolved,
        "lastHash": hashlib.sha256(
            json.dumps(resolved, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "refreshedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "frozenRows": [],
    }
    state["links"] = [item for item in state["links"] if item.get("id") != link_id] + [record]
    _save(ctx, state)
    count = len(resolved) if isinstance(resolved, list) else 1
    return result(
        summary={
            "linkId": link_id,
            "kind": "model",
            "valueCount": count,
            "sha256": record["lastHash"],
        }
    )


@feature(
    "documentsReportDataLinks.linkWorksheet",
    "Link Worksheet",
    part="settings",
    fields=[
        text("linkId", "Link id", "worksheet-results"),
        text("worksheetId", "Worksheet id", "calculation-1"),
        text("range", "Cell range", "A1:B10"),
        text("fieldPrefix", "Report field prefix", "worksheet"),
    ],
)
def link_worksheet(ctx: FeatureContext, values: dict) -> dict:
    """Bind a report link to live worksheet cell values and units for the selected cell range."""
    from saengine.features.documents_common import cell_value, range_cells, worksheet_workspace

    sheet, workbook = worksheet_workspace(ctx, values["worksheetId"])
    cells = range_cells(values["range"])
    rows = [
        {
            "cell": cell,
            "value": cell_value(cell, workbook)
            if workbook.get("cells", {}).get(cell, {}).get("formula")
            else workbook.get("cells", {}).get(cell, {}).get("value"),
            "unit": workbook.get("cells", {}).get(cell, {}).get("unit"),
        }
        for cell in cells
    ]
    state = _state(ctx)
    link_id = values["linkId"].strip()
    record = {
        "id": link_id,
        "kind": "worksheet",
        "worksheetId": sheet.id,
        "range": values["range"],
        "fieldPrefix": values["fieldPrefix"].strip(),
        "currentData": rows,
        "lastHash": hashlib.sha256(
            json.dumps(rows, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "refreshedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "frozenRows": [],
    }
    state["links"] = [item for item in state["links"] if item.get("id") != link_id] + [record]
    _save(ctx, state)
    return result(
        summary={
            "linkId": link_id,
            "worksheetId": sheet.id,
            "cellCount": len(rows),
            "sha256": record["lastHash"],
        },
        tables=[
            table(
                "Linked worksheet cells",
                [("cell", "Cell"), ("value", "Value"), ("unit", "Unit")],
                rows,
            )
        ],
    )


@feature(
    "documentsReportDataLinks.linkDatabase",
    "Link Database",
    part="settings",
    fields=[
        text("linkId", "Link id", "boq-database"),
        text("databasePath", "Project-relative SQLite file", "11 Exports/project.sqlite"),
        text("query", "Read-only SELECT statement", "SELECT * FROM quantities"),
        text("description", "Link description", "Quantity records"),
    ],
)
def link_database(ctx: FeatureContext, values: dict) -> dict:
    """Bind report data to a read-only, parameter-free SELECT query from a SQLite file inside the project."""
    if not re.match(r"(?is)^\s*select\b", values["query"]):
        raise FeatureInputError("Database links are read-only and must start with SELECT.")
    root = require_root(ctx)
    path = (root / values["databasePath"]).resolve()
    try:
        path.relative_to(root.resolve())
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute(values["query"]).fetchmany(10000)]
    except (ValueError, sqlite3.Error, OSError) as exc:
        raise FeatureInputError(f"Could not create a read-only database link: {exc}") from exc
    record = {
        "id": values["linkId"].strip(),
        "kind": "sqlite",
        "database": path.relative_to(root).as_posix(),
        "query": values["query"].strip(),
        "description": values["description"].strip(),
        "currentData": rows,
        "lastHash": hashlib.sha256(
            json.dumps(rows, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "refreshedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "frozenRows": [],
    }
    state = _state(ctx)
    state["links"] = [item for item in state["links"] if item.get("id") != record["id"]] + [record]
    _save(ctx, state)
    return result(
        summary={"linkId": record["id"], "databaseRows": len(rows), "sha256": record["lastHash"]},
        tables=[
            table(
                "Database preview",
                [(key, key) for key in (rows[0].keys() if rows else [])],
                rows[:50],
            )
        ],
    )


@feature(
    "documentsReportDataLinks.refreshLinks",
    "Refresh Links",
    part="settings",
    fields=[text("linkId", "Link id (blank means all)", "")],
)
def refresh_links(ctx: FeatureContext, values: dict) -> dict:
    """Re-resolve each active model, worksheet, database or local JSON link and record the new data hash."""
    state = _state(ctx)
    targets = [
        item
        for item in state["links"]
        if not values["linkId"].strip() or item.get("id") == values["linkId"].strip()
    ]
    if not targets:
        raise FeatureInputError("No report data links match the selected id.")
    rows = []
    for link in targets:
        if link.get("unlinked"):
            continue
        current = _resolve_link(ctx, link)
        frozen = {item.get("key") for item in link.get("frozenRows", [])}
        if frozen and isinstance(current, list):
            current = [
                row
                for index, row in enumerate(current)
                if str(row.get("id", row.get("cell", index))) not in frozen
            ]
        link["currentData"] = current
        link["lastHash"] = hashlib.sha256(
            json.dumps(current, sort_keys=True, default=str).encode()
        ).hexdigest()
        link["refreshedAt"] = datetime.now(UTC).isoformat(timespec="seconds")
        rows.append(
            {
                "id": link["id"],
                "kind": link["kind"],
                "valueCount": len(current) if isinstance(current, list) else 1,
                "sha256": link["lastHash"],
            }
        )
    _save(ctx, state)
    return result(
        summary={"refreshedLinkCount": len(rows)},
        tables=[
            table(
                "Refreshed data links",
                [
                    ("id", "Link"),
                    ("kind", "Source"),
                    ("valueCount", "Values"),
                    ("sha256", "SHA-256"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsReportDataLinks.apiConnection",
    "API Connection",
    part="settings",
    fields=[
        text("linkId", "Link id", "api-snapshot"),
        text("snapshotPath", "Project-relative JSON snapshot", "11 Exports/api-snapshot.json"),
        text("dataPath", "Data path in JSON", "results"),
        number("refreshMinutes", "Refresh interval", 60, unit="min", min=1),
        text("description", "Connection description", "Local API snapshot"),
    ],
)
def api_connection(ctx: FeatureContext, values: dict) -> dict:
    """Configure a deterministic local JSON API snapshot as a report source; external network endpoints are not called."""
    root = require_root(ctx)
    path = (root / values["snapshotPath"]).resolve()
    try:
        path.relative_to(root.resolve())
        source = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise FeatureInputError(
            "Choose a readable JSON snapshot inside the project; network URLs are not supported."
        ) from exc
    resolved = dotted_value(source, values["dataPath"].strip())
    if resolved is None:
        raise FeatureInputError("The API snapshot data path does not exist.")
    record = {
        "id": values["linkId"].strip(),
        "kind": "localApi",
        "snapshotPath": path.relative_to(root).as_posix(),
        "path": values["dataPath"].strip(),
        "description": values["description"].strip(),
        "refreshMinutes": int(values["refreshMinutes"]),
        "currentData": resolved,
        "lastHash": hashlib.sha256(
            json.dumps(resolved, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "refreshedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "frozenRows": [],
    }
    state = _state(ctx)
    state["links"] = [item for item in state["links"] if item.get("id") != record["id"]] + [record]
    _save(ctx, state)
    return result(
        summary={
            "linkId": record["id"],
            "snapshotPath": record["snapshotPath"],
            "refreshMinutes": record["refreshMinutes"],
            "valueCount": len(resolved) if isinstance(resolved, list) else 1,
        },
        notes=["The connection reads a project-local JSON snapshot; no network request was made."],
    )


@feature(
    "documentsReportDataLinks.fieldMap",
    "Field Map",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        text(
            "mapping",
            "Mappings as source=placeholder; separated by semicolons",
            "id=member.id;type=member.type",
        ),
        checkbox("required", "Require source fields", True),
    ],
)
def field_map(ctx: FeatureContext, values: dict) -> dict:
    """Map live source columns to report placeholders and validate all required source fields against actual rows."""
    state = _state(ctx)
    link = _link(ctx, values["linkId"])
    mappings = {}
    for pair in values["mapping"].split(";"):
        if not pair.strip():
            continue
        if "=" not in pair:
            raise FeatureInputError(
                "Mappings must use source=placeholder pairs separated by semicolons."
            )
        source, target = (part.strip() for part in pair.split("=", 1))
        if not source or not target:
            raise FeatureInputError("Each field mapping needs a source and a placeholder.")
        mappings[source] = target
    sample = link.get("currentData")
    source_row = (
        sample[0]
        if isinstance(sample, list) and sample and isinstance(sample[0], dict)
        else sample
        if isinstance(sample, dict)
        else {}
    )
    missing = set(mappings) - source_row.keys()
    if values["required"] and missing:
        raise FeatureInputError(f"Missing source fields: {', '.join(sorted(missing))}.")
    link["fieldMap"] = mappings
    link["requiredFields"] = values["required"]
    _save(ctx, state)
    return result(
        summary={
            "linkId": link["id"],
            "mappedFieldCount": len(mappings),
            "missingFieldCount": len(missing),
        },
        tables=[
            table(
                "Report field mappings",
                [("source", "Source field"), ("placeholder", "Report placeholder")],
                [{"source": key, "placeholder": target} for key, target in mappings.items()],
            )
        ],
    )


@feature(
    "documentsReportDataLinks.unitMapping",
    "Unit Mapping",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-results"),
        text("field", "Numeric field", "driftMm"),
        text("sourceUnit", "Source SI unit", "mm"),
        text("targetUnit", "Display SI unit", "m"),
    ],
)
def unit_mapping(ctx: FeatureContext, values: dict) -> dict:
    """Convert numeric linked values between dimensionally compatible units using SAEngine's unit registry."""
    from saengine.units import kind_of

    source, target = kind_of(values["sourceUnit"]), kind_of(values["targetUnit"])
    if source is None or target is None or source[0] != target[0]:
        raise FeatureInputError(
            "Source and target must be recognized units of the same physical dimension."
        )
    state = _state(ctx)
    link = _link(ctx, values["linkId"])
    factor = source[1] / target[1]
    data = link.get("currentData")
    if not isinstance(data, list):
        raise FeatureInputError("Unit mapping requires a linked table of rows.")
    converted = []
    for row in data:
        item = dict(row)
        if values["field"] not in item:
            raise FeatureInputError(f"Linked rows do not contain field {values['field']!r}.")
        try:
            item[values["field"]] = float(item[values["field"]]) * factor
        except (TypeError, ValueError) as exc:
            raise FeatureInputError(
                f"Field {values['field']!r} must be numeric for unit conversion."
            ) from exc
        item[values["field"] + "Unit"] = values["targetUnit"]
        converted.append(item)
    link["currentData"] = converted
    link["unitMap"] = {
        "field": values["field"],
        "source": values["sourceUnit"],
        "target": values["targetUnit"],
        "factor": factor,
    }
    _save(ctx, state)
    return result(
        summary={
            "linkId": link["id"],
            "field": values["field"],
            "conversionFactor": factor,
            "convertedRowCount": len(converted),
        },
        tables=[
            table(
                "Converted linked values",
                [("field", values["field"]), ("unit", "Display unit")],
                [
                    {"field": row[values["field"]], "unit": values["targetUnit"]}
                    for row in converted[:100]
                ],
            )
        ],
    )


@feature(
    "documentsReportDataLinks.linkFilters",
    "Link Filters",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        text("field", "Filter field", "kind"),
        select(
            "operator",
            "Operator",
            [("equals", "Equals"), ("contains", "Contains"), ("notEquals", "Does not equal")],
            "equals",
        ),
        text("value", "Filter value", "beam"),
    ],
)
def link_filters(ctx: FeatureContext, values: dict) -> dict:
    """Apply a source-field filter to live linked rows and save the resulting subset for report binding."""
    state = _state(ctx)
    link = _link(ctx, values["linkId"])
    rows = link.get("currentData")
    if not isinstance(rows, list):
        raise FeatureInputError("Link filtering requires tabular linked data.")
    selected = []
    for row in rows:
        if values["field"] not in row:
            raise FeatureInputError(f"Linked data has no field {values['field']!r}.")
        actual = str(row[values["field"]])
        expected = values["value"]
        passed = (
            actual.casefold() == expected.casefold()
            if values["operator"] == "equals"
            else expected.casefold() in actual.casefold()
            if values["operator"] == "contains"
            else actual.casefold() != expected.casefold()
        )
        if passed:
            selected.append(row)
    link["filters"] = link.get("filters", []) + [
        {"field": values["field"], "operator": values["operator"], "value": values["value"]}
    ]
    link["filteredData"] = selected
    _save(ctx, state)
    return result(
        summary={
            "linkId": link["id"],
            "sourceRowCount": len(rows),
            "filteredRowCount": len(selected),
        },
        tables=[
            table(
                "Filtered report data",
                [(key, key) for key in (selected[0].keys() if selected else [])],
                selected[:100],
            )
        ],
    )


@feature(
    "documentsReportDataLinks.previewData",
    "Preview Data",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        number("rowLimit", "Rows to preview", 50, min=1, max=500),
    ],
)
def preview_data(ctx: FeatureContext, values: dict) -> dict:
    """Show the current linked rows or scalar value before it is inserted into report content."""
    link = _link(ctx, values["linkId"])
    data = link.get("filteredData", link.get("currentData"))
    if isinstance(data, list):
        rows = data[: int(values["rowLimit"])]
    elif isinstance(data, dict):
        rows = [{"field": key, "value": value} for key, value in data.items()]
    else:
        rows = [{"value": data}]
    columns = [(key, key) for key in (rows[0].keys() if rows and isinstance(rows[0], dict) else [])]
    return result(
        summary={
            "linkId": link["id"],
            "kind": link["kind"],
            "rowCount": len(data) if isinstance(data, list) else 1,
            "previewCount": len(rows),
        },
        tables=[table("Linked data preview", columns, rows)],
    )


@feature(
    "documentsReportDataLinks.captureValues",
    "Capture Values",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        text("captureId", "Capture id", "baseline-1"),
        text("note", "Capture note", "Values at issue date"),
    ],
)
def capture_values(ctx: FeatureContext, values: dict) -> dict:
    """Freeze the current resolved link rows under a unique capture id with timestamp and content checksum."""
    state = _state(ctx)
    link = _link(ctx, values["linkId"])
    capture_id = values["captureId"].strip()
    if not capture_id or any(item.get("id") == capture_id for item in state["captures"]):
        raise FeatureInputError("Enter a unique capture id.")
    data = link.get("filteredData", link.get("currentData"))
    payload = json.dumps(data, sort_keys=True, default=str)
    capture = {
        "id": capture_id,
        "linkId": link["id"],
        "data": data,
        "note": values["note"].strip(),
        "capturedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(payload.encode()).hexdigest(),
    }
    state["captures"].append(capture)
    link["lastCaptureId"] = capture_id
    _save(ctx, state)
    return result(
        summary={
            "captureId": capture_id,
            "linkId": link["id"],
            "valueCount": len(data) if isinstance(data, list) else 1,
            "sha256": capture["sha256"],
        }
    )


@feature(
    "documentsReportDataLinks.freezeRow",
    "Freeze Row",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        text("rowKeys", "Row ids or cell references (comma-separated)", "C1"),
        text("reason", "Freeze reason", "Reviewed value"),
    ],
)
def freeze_row(ctx: FeatureContext, values: dict) -> dict:
    """Freeze selected linked rows by stable row id or cell reference so refreshes do not replace reviewed values."""
    state = _state(ctx)
    link = _link(ctx, values["linkId"], editable=True)
    rows = link.get("currentData")
    if not isinstance(rows, list):
        raise FeatureInputError("Row freezing requires tabular link data.")
    keys = {item.strip() for item in values["rowKeys"].split(",") if item.strip()}
    found = {str(row.get("id", row.get("cell", index))) for index, row in enumerate(rows)} & keys
    missing = keys - found
    if not keys or missing:
        raise FeatureInputError(
            "Unknown link row key(s): " + ", ".join(sorted(missing))
            if missing
            else "Select at least one row to freeze."
        )
    link["frozenRows"] = [
        item for item in link.get("frozenRows", []) if item.get("key") not in keys
    ] + [
        {
            "key": key,
            "reason": values["reason"].strip(),
            "frozenAt": datetime.now(UTC).isoformat(timespec="seconds"),
            "value": next(
                row
                for index, row in enumerate(rows)
                if str(row.get("id", row.get("cell", index))) == key
            ),
        }
        for key in sorted(keys)
    ]
    _save(ctx, state)
    return result(
        summary={"linkId": link["id"], "frozenRowCount": len(link["frozenRows"])},
        tables=[
            table(
                "Frozen link rows",
                [("key", "Row"), ("reason", "Reason"), ("frozenAt", "Frozen at")],
                link["frozenRows"],
            )
        ],
    )


@feature(
    "documentsReportDataLinks.compareCapture",
    "Compare Capture",
    part="settings",
    fields=[
        text("captureId", "Capture id", "baseline-1"),
        text("linkId", "Link id", "model-elements"),
    ],
)
def compare_capture(ctx: FeatureContext, values: dict) -> dict:
    """Compare a frozen capture with current live rows and list values added, removed or changed."""
    state = _state(ctx)
    capture = next(
        (item for item in state["captures"] if item.get("id") == values["captureId"].strip()), None
    )
    if capture is None:
        raise FeatureInputError("The capture id does not exist.")
    link = _link(ctx, values["linkId"])
    old, new = capture.get("data"), link.get("filteredData", link.get("currentData"))
    old_rows = old if isinstance(old, list) else [{"value": old}]
    new_rows = new if isinstance(new, list) else [{"value": new}]
    identity = lambda row, i: str(row.get("id", row.get("cell", i)))
    old_map = {identity(row, i): row for i, row in enumerate(old_rows)}
    new_map = {identity(row, i): row for i, row in enumerate(new_rows)}
    changes = [
        {"key": key, "change": "removed", "before": str(old_map[key]), "after": ""}
        for key in old_map.keys() - new_map.keys()
    ]
    changes += [
        {"key": key, "change": "added", "before": "", "after": str(new_map[key])}
        for key in new_map.keys() - old_map.keys()
    ]
    changes += [
        {"key": key, "change": "changed", "before": str(old_map[key]), "after": str(new_map[key])}
        for key in old_map.keys() & new_map.keys()
        if old_map[key] != new_map[key]
    ]
    return result(
        summary={"captureId": capture["id"], "changeCount": len(changes)},
        tables=[
            table(
                "Capture comparison",
                [
                    ("key", "Row"),
                    ("change", "Change"),
                    ("before", "Captured value"),
                    ("after", "Live value"),
                ],
                changes,
            )
        ],
    )


@feature(
    "documentsReportDataLinks.restoreCapture",
    "Restore Capture",
    part="settings",
    fields=[
        text("captureId", "Capture id", "baseline-1"),
        checkbox("restoreAsCurrent", "Restore captured values as current snapshot", True),
    ],
)
def restore_capture(ctx: FeatureContext, values: dict) -> dict:
    """Restore a selected frozen data capture to a link's current snapshot while retaining its live source definition."""
    state = _state(ctx)
    capture = next(
        (item for item in state["captures"] if item.get("id") == values["captureId"].strip()), None
    )
    if capture is None:
        raise FeatureInputError("The capture id does not exist.")
    link = _link(ctx, capture["linkId"])
    if values["restoreAsCurrent"]:
        link["currentData"] = capture["data"]
        link["lastHash"] = capture["sha256"]
        link["restoredCaptureId"] = capture["id"]
        link["restoredAt"] = datetime.now(UTC).isoformat(timespec="seconds")
    _save(ctx, state)
    return result(
        summary={
            "captureId": capture["id"],
            "linkId": link["id"],
            "restored": values["restoreAsCurrent"],
            "captureHash": capture["sha256"],
        },
        notes=[
            "The live source path and query remain registered; refresh can replace the restored snapshot."
        ],
    )


@feature(
    "documentsReportDataLinks.sqlQuery",
    "SQL Query",
    part="settings",
    fields=[
        text("databasePath", "Project-relative SQLite file", "11 Exports/project.sqlite"),
        text("query", "SELECT statement", "SELECT * FROM quantities WHERE quantity > :minimum"),
        number("minimum", "Minimum quantity parameter", 0),
        number("rowLimit", "Maximum rows", 500, min=1, max=10000),
    ],
)
def sql_query(ctx: FeatureContext, values: dict) -> dict:
    """Run a parameterized read-only SQLite SELECT query and preview its actual returned columns and rows."""
    root = require_root(ctx)
    if not re.match(r"(?is)^\s*select\b", values["query"]):
        raise FeatureInputError("Only SELECT statements are allowed.")
    path = (root / values["databasePath"]).resolve()
    try:
        path.relative_to(root.resolve())
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            rows = [
                dict(row)
                for row in connection.execute(
                    values["query"], {"minimum": values["minimum"]}
                ).fetchmany(int(values["rowLimit"]))
            ]
    except (ValueError, sqlite3.Error, OSError) as exc:
        raise FeatureInputError(f"Read-only SQL query failed: {exc}") from exc
    return result(
        summary={"rowCount": len(rows), "database": path.relative_to(root).as_posix()},
        tables=[
            table(
                "SQL query results", [(key, key) for key in (rows[0].keys() if rows else [])], rows
            )
        ],
    )


@feature(
    "documentsReportDataLinks.parameterFilter",
    "Parameter Filter",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        text("property", "Parameter field", "story"),
        select(
            "operator",
            "Rule",
            [("equals", "Equals"), ("notEquals", "Does not equal"), ("contains", "Contains")],
            "equals",
        ),
        text("value", "Required value", "L1"),
    ],
)
def parameter_filter(ctx: FeatureContext, values: dict) -> dict:
    """Filter linked report rows with a parameter predicate and store the precise matching subset."""
    state = _state(ctx)
    link = _link(ctx, values["linkId"])
    data = link.get("currentData")
    if not isinstance(data, list):
        raise FeatureInputError("Parameter filtering requires tabular data.")
    filtered = []
    for row in data:
        if values["property"] not in row:
            continue
        actual = str(row[values["property"]]).casefold()
        expected = values["value"].casefold()
        matched = (
            actual == expected
            if values["operator"] == "equals"
            else actual != expected
            if values["operator"] == "notEquals"
            else expected in actual
        )
        if matched:
            filtered.append(row)
    link["filteredData"] = filtered
    link["parameterFilter"] = {
        "property": values["property"],
        "operator": values["operator"],
        "value": values["value"],
    }
    _save(ctx, state)
    return result(
        summary={"sourceRowCount": len(data), "matchingRowCount": len(filtered)},
        tables=[
            table(
                "Parameter-filtered data",
                [(key, key) for key in (filtered[0].keys() if filtered else [])],
                filtered[:100],
            )
        ],
    )


@feature(
    "documentsReportDataLinks.expressionEditor",
    "Expression Editor",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        text("expression", "Arithmetic expression", "widthMm / 1000"),
        number("rowLimit", "Rows to evaluate", 100, min=1, max=1000),
    ],
)
def expression_editor(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate a safe arithmetic expression for each numeric row in a live report data link."""
    from saengine.drawings.sheets.schedule_builder import evaluate_expression

    link = _link(ctx, values["linkId"])
    rows = link.get("filteredData", link.get("currentData"))
    if not isinstance(rows, list):
        raise FeatureInputError("Expression evaluation requires table rows.")
    output = []
    try:
        for index, row in enumerate(rows[: int(values["rowLimit"])]):
            output.append(
                {"row": index + 1, "value": evaluate_expression(values["expression"], row)}
            )
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise FeatureInputError(f"Expression could not be evaluated: {exc}") from exc
    link["lastExpression"] = {
        "expression": values["expression"],
        "rowCount": len(output),
        "values": output,
    }
    state = _state(ctx)
    _save(ctx, state)
    return result(
        summary={"evaluatedRowCount": len(output), "expression": values["expression"]},
        tables=[table("Expression results", [("row", "Row"), ("value", "Result")], output)],
    )


@feature(
    "documentsReportDataLinks.embedLiveTable",
    "Embed Live Table",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        text("tableTitle", "Table title", "Live model table"),
        text("section", "Report section", "model"),
        number("maximumRows", "Maximum rows", 100, min=1, max=1000),
    ],
)
def embed_live_table(ctx: FeatureContext, values: dict) -> dict:
    """Embed the current linked rows in report content while retaining the source link id for refresh."""
    state = _state(ctx)
    link = _link(ctx, values["linkId"])
    rows = link.get("filteredData", link.get("currentData"))
    rows = rows[: int(values["maximumRows"])] if isinstance(rows, list) else [{"value": rows}]
    block = {
        "kind": "liveTable",
        "title": values["tableTitle"].strip(),
        "section": values["section"].strip(),
        "linkId": link["id"],
        "sourceHash": link.get("lastHash"),
        "rowCount": len(rows),
        "rows": rows,
    }
    state["content"].append(block)
    _save(ctx, state)
    return result(
        summary={"tableTitle": block["title"], "rowCount": len(rows), "linkId": link["id"]},
        tables=[
            table(
                block["title"],
                [
                    (key, key)
                    for key in (rows[0].keys() if rows and isinstance(rows[0], dict) else [])
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsReportDataLinks.formatDataMatrix",
    "Format Data Matrix",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        text("numericField", "Numeric field", "lengthM"),
        select(
            "thresholdRule",
            "Threshold",
            [
                ("greater", "Above threshold"),
                ("less", "Below threshold"),
                ("equal", "Equal to threshold"),
            ],
            "greater",
        ),
        number("threshold", "Threshold value", 6),
        text("highlight", "Highlight colour", "#FFE08A"),
    ],
)
def format_data_matrix(ctx: FeatureContext, values: dict) -> dict:
    """Apply a conditional display style to linked rows whose numeric field crosses a chosen threshold."""
    state = _state(ctx)
    link = _link(ctx, values["linkId"])
    rows = link.get("currentData")
    if not isinstance(rows, list):
        raise FeatureInputError("Conditional data-matrix styling requires table rows.")
    formatted = []
    for row in rows:
        if values["numericField"] not in row:
            raise FeatureInputError(f"Linked rows lack numeric field {values['numericField']!r}.")
        try:
            amount = float(row[values["numericField"]])
        except (TypeError, ValueError) as exc:
            raise FeatureInputError("The conditional format field must be numeric.") from exc
        match = (
            amount > values["threshold"]
            if values["thresholdRule"] == "greater"
            else amount < values["threshold"]
            if values["thresholdRule"] == "less"
            else amount == values["threshold"]
        )
        formatted.append({**row, "_format": {"highlight": values["highlight"]} if match else {}})
    link["formattedData"] = formatted
    _save(ctx, state)
    return result(
        summary={
            "formattedRowCount": len(formatted),
            "highlightedRowCount": sum(bool(row["_format"]) for row in formatted),
        },
        tables=[
            table(
                "Conditionally formatted data",
                [(key, key) for key in (formatted[0].keys() if formatted else [])],
                formatted[:100],
            )
        ],
    )


@feature(
    "documentsReportDataLinks.autoRefreshRate",
    "Auto Refresh Rate",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        number("intervalMinutes", "Refresh interval", 60, unit="min", min=1),
        checkbox("refreshOnOpen", "Refresh when report opens", True),
    ],
)
def auto_refresh_rate(ctx: FeatureContext, values: dict) -> dict:
    """Set a refresh interval and on-open policy for one live report link."""
    state = _state(ctx)
    link = _link(ctx, values["linkId"], editable=True)
    link["refreshPolicy"] = {
        "intervalMinutes": int(values["intervalMinutes"]),
        "refreshOnOpen": values["refreshOnOpen"],
        "updatedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _save(ctx, state)
    return result(
        summary={
            "linkId": link["id"],
            "intervalMinutes": link["refreshPolicy"]["intervalMinutes"],
            "refreshOnOpen": link["refreshPolicy"]["refreshOnOpen"],
        },
        notes=[
            "The policy is stored for report refresh; this offline feature does not run a background timer."
        ],
    )


@feature(
    "documentsReportDataLinks.checkStaleLinks",
    "Check Stale Links",
    part="settings",
    fields=[text("linkId", "Link id (blank means all)", "")],
)
def check_stale_links(ctx: FeatureContext, values: dict) -> dict:
    """Compare live sources with their recorded link hashes and report stale or unavailable data."""
    state = _state(ctx)
    links = [
        item
        for item in state["links"]
        if not values["linkId"].strip() or item.get("id") == values["linkId"].strip()
    ]
    if not links:
        raise FeatureInputError("No data link matches the selected id.")
    rows = []
    for link in links:
        try:
            data = _resolve_link(ctx, link)
            digest = hashlib.sha256(
                json.dumps(data, sort_keys=True, default=str).encode()
            ).hexdigest()
            status = "current" if digest == link.get("lastHash") else "stale"
        except FeatureInputError:
            digest, status = "", "unavailable"
        rows.append(
            {
                "id": link["id"],
                "kind": link["kind"],
                "status": status,
                "recordedHash": str(link.get("lastHash", ""))[:12],
                "currentHash": digest[:12],
            }
        )
    return result(
        summary={
            "linkCount": len(rows),
            "staleCount": sum(row["status"] != "current" for row in rows),
        },
        tables=[
            table(
                "Report data-link health",
                [
                    ("id", "Link"),
                    ("kind", "Source"),
                    ("status", "Status"),
                    ("recordedHash", "Recorded"),
                    ("currentHash", "Current"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsReportDataLinks.unlinkSource",
    "Unlink Source",
    part="settings",
    fields=[
        text("linkId", "Link id", "model-elements"),
        checkbox("keepValues", "Keep captured values as static data", True),
    ],
)
def unlink_source(ctx: FeatureContext, values: dict) -> dict:
    """Convert a live report link to static content or remove it while preserving its captured values when requested."""
    state = _state(ctx)
    link = _link(ctx, values["linkId"])
    if values["keepValues"]:
        link["currentData"] = link.get("filteredData", link.get("currentData"))
        link["unlinked"] = True
        link["kind"] = "static"
        link["unlinkedAt"] = datetime.now(UTC).isoformat(timespec="seconds")
    else:
        state["links"] = [item for item in state["links"] if item.get("id") != link["id"]]
    _save(ctx, state)
    return result(
        summary={
            "linkId": link["id"],
            "keptStaticValues": values["keepValues"],
            "remainingLinkCount": len(state["links"]),
        }
    )


@feature(
    "documentsReportDataLinks.logDataSync",
    "Log Data Sync",
    part="settings",
    fields=[
        text("linkId", "Link id (blank means all)", ""),
        number("limit", "Recent sync events", 100, min=1, max=1000),
    ],
)
def log_data_sync(ctx: FeatureContext, values: dict) -> dict:
    """Review sync timestamps and data hashes for report sources, including successful refresh actions."""
    state = _state(ctx)
    links = [
        item
        for item in state["links"]
        if not values["linkId"].strip() or item.get("id") == values["linkId"].strip()
    ]
    rows = [
        {
            "linkId": item["id"],
            "kind": item["kind"],
            "refreshedAt": item.get("refreshedAt", ""),
            "sha256": item.get("lastHash", ""),
            "unlinked": bool(item.get("unlinked")),
        }
        for item in links
    ]
    rows = rows[-int(values["limit"]) :]
    rows.extend(
        {
            "linkId": "",
            "kind": "event:" + item["event"],
            "refreshedAt": item["at"],
            "sha256": "",
            "unlinked": False,
        }
        for item in state["events"]
        if item["event"] in ("refreshLinks", "linkModel", "linkWorksheet", "linkDatabase")
    )
    return result(
        summary={"syncRecordCount": len(rows)},
        tables=[
            table(
                "Data synchronization history",
                [
                    ("linkId", "Link"),
                    ("kind", "Source/action"),
                    ("refreshedAt", "Timestamp"),
                    ("sha256", "Data hash"),
                    ("unlinked", "Static"),
                ],
                rows[-int(values["limit"]) :],
            )
        ],
    )


def _page_layout(state: dict, template_id: str) -> dict:
    return state["pagination"].setdefault(template_id, {})


@feature(
    "documentsReportPagination.paperSize",
    "Paper Size",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        select("paper", "Paper size", [("a4", "A4"), ("us-letter", "US Letter")], "a4"),
        checkbox("applyAllSections", "Apply to all sections", True),
    ],
)
def pagination_paper_size(ctx: FeatureContext, values: dict) -> dict:
    """Set the report template paper size and record whether it applies globally or only to selected sections."""
    data = _template_data(ctx, values["templateId"])
    data["paper"] = values["paper"]
    path = _save_template(ctx, data)
    state = _state(ctx)
    layout = _page_layout(state, data["id"])
    layout["paperScope"] = "all" if values["applyAllSections"] else "sectionOverrides"
    layout["paper"] = values["paper"]
    _save(ctx, state)
    dimensions = (210, 297) if values["paper"] == "a4" else (215.9, 279.4)
    return result(
        summary={
            "paper": values["paper"],
            "widthMm": dimensions[0],
            "heightMm": dimensions[1],
            "scope": layout["paperScope"],
        },
        notes=[f"Template saved to {path}."],
    )


@feature(
    "documentsReportPagination.pageMargins",
    "Page Margins",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        number("topMm", "Top margin", 20, unit="mm", min=0),
        number("bottomMm", "Bottom margin", 20, unit="mm", min=0),
        number("insideMm", "Inside margin", 20, unit="mm", min=0),
        number("outsideMm", "Outside margin", 15, unit="mm", min=0),
        number("gutterMm", "Binding gutter", 0, unit="mm", min=0),
    ],
)
def page_margins(ctx: FeatureContext, values: dict) -> dict:
    """Set report page margins and reject a layout whose content area is not positive."""
    data = _template_data(ctx, values["templateId"])
    width, height = (210, 297) if data["paper"] == "a4" else (215.9, 279.4)
    content_width = width - values["insideMm"] - values["outsideMm"] - values["gutterMm"]
    content_height = height - values["topMm"] - values["bottomMm"]
    if min(content_width, content_height) <= 0:
        raise FeatureInputError("Margins and gutter exceed the selected paper size.")
    state = _state(ctx)
    layout = _page_layout(state, data["id"])
    layout["marginsMm"] = {
        "top": values["topMm"],
        "bottom": values["bottomMm"],
        "inside": values["insideMm"],
        "outside": values["outsideMm"],
        "gutter": values["gutterMm"],
    }
    _save(ctx, state)
    return result(
        summary={
            "contentWidthMm": content_width,
            "contentHeightMm": content_height,
            "marginAreaMm2": width * height - content_width * content_height,
        }
    )


@feature(
    "documentsReportPagination.pageOrientation",
    "Page Orientation",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        select(
            "orientation",
            "Orientation",
            [("portrait", "Portrait"), ("landscape", "Landscape")],
            "portrait",
        ),
        text("sectionIds", "Apply to sections (comma-separated; blank means all)", ""),
    ],
)
def page_orientation(ctx: FeatureContext, values: dict) -> dict:
    """Set page orientation for the whole report or selected sections and calculate their printable dimensions."""
    from saengine.library.report_template import SECTIONS

    data = _template_data(ctx, values["templateId"])
    selected = [part.strip() for part in values["sectionIds"].split(",") if part.strip()]
    if set(selected) - set(SECTIONS):
        raise FeatureInputError("Choose section ids from the Report Template section list.")
    state = _state(ctx)
    layout = _page_layout(state, data["id"])
    if selected:
        layout.setdefault("sectionOrientation", {}).update(
            {section: values["orientation"] for section in selected}
        )
    else:
        layout["orientation"] = values["orientation"]
    paper = (210, 297) if data["paper"] == "a4" else (215.9, 279.4)
    width, height = paper if values["orientation"] == "portrait" else paper[::-1]
    _save(ctx, state)
    return result(
        summary={
            "orientation": values["orientation"],
            "sectionCount": len(selected) if selected else len(data["sections"]),
            "pageWidthMm": width,
            "pageHeightMm": height,
        }
    )


@feature(
    "documentsReportPagination.columnLayout",
    "Column Layout",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("sectionId", "Report section id", "boq"),
        number("columns", "Column count", 2, min=1, max=4),
        number("gutterMm", "Column gutter", 8, unit="mm", min=0),
    ],
)
def column_layout(ctx: FeatureContext, values: dict) -> dict:
    """Configure a report section's column count and compute its text-column width from the template paper."""
    data = _template_data(ctx, values["templateId"])
    if values["sectionId"] not in {row["id"] for row in data["sections"]}:
        raise FeatureInputError("The chosen section is not included in the template section list.")
    width = 210 if data["paper"] == "a4" else 215.9
    margins = _page_layout(_state(ctx), data["id"]).get(
        "marginsMm", {"inside": 20, "outside": 15, "gutter": 0}
    )
    usable = (
        width - margins.get("inside", 20) - margins.get("outside", 15) - margins.get("gutter", 0)
    )
    col_width = (usable - (int(values["columns"]) - 1) * values["gutterMm"]) / int(
        values["columns"]
    )
    if col_width <= 0:
        raise FeatureInputError("Column gutters leave no usable text width.")
    state = _state(ctx)
    _page_layout(state, data["id"]).setdefault("columns", {})[values["sectionId"]] = {
        "count": int(values["columns"]),
        "gutterMm": values["gutterMm"],
        "columnWidthMm": col_width,
    }
    _save(ctx, state)
    return result(
        summary={
            "sectionId": values["sectionId"],
            "columnCount": values["columns"],
            "columnWidthMm": col_width,
        }
    )


@feature(
    "documentsReportPagination.headerText",
    "Header Text",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("header", "Running header", "Structural Design Report"),
        text("section", "Section scope (blank means all)", ""),
        checkbox("includeRevision", "Include current revision", True),
    ],
)
def header_text(ctx: FeatureContext, values: dict) -> dict:
    """Set a running page header with optional section scope and dynamic report revision field."""
    state = _state(ctx)
    headers = _page_layout(state, values["templateId"]).setdefault("headers", {})
    key = values["section"].strip() or "*"
    headers[key] = {"text": values["header"], "revision": values["includeRevision"]}
    _save(ctx, state)
    return result(
        summary={
            "templateId": values["templateId"],
            "sectionScope": key,
            "headerLength": len(values["header"]),
            "revisionField": values["includeRevision"],
        }
    )


@feature(
    "documentsReportPagination.footerText",
    "Footer Text",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("footer", "Running footer", "Project {project.name}"),
        text("leftZone", "Left footer zone", ""),
        text("rightZone", "Right footer zone", "Page {page} of {pages}"),
    ],
)
def footer_text(ctx: FeatureContext, values: dict) -> dict:
    """Set the report footer's centre, left and right zones and validate its supported dynamic field names."""
    allowed = {"project.name", "project.number", "revision", "page", "pages", "date"}
    fields = set(
        re.findall(
            r"\{([^{}]+)\}", " ".join((values["footer"], values["leftZone"], values["rightZone"]))
        )
    )
    if fields - allowed:
        raise FeatureInputError(
            f"Unsupported footer token(s): {', '.join(sorted(fields - allowed))}."
        )
    state = _state(ctx)
    _page_layout(state, values["templateId"])["footer"] = {
        "center": values["footer"],
        "left": values["leftZone"],
        "right": values["rightZone"],
    }
    _save(ctx, state)
    return result(summary={"footerFieldCount": len(fields), "footerZones": 3})


@feature(
    "documentsReportPagination.pageNumbers",
    "Page Numbers",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        number("startAt", "First page number", 1, min=1),
        select(
            "format",
            "Number format",
            [
                ("decimal", "1, 2, 3"),
                ("roman", "i, ii, iii"),
                ("prefixed", "Section prefix and number"),
            ],
            "decimal",
        ),
        checkbox("restartEachSection", "Restart by section", False),
    ],
)
def page_numbers(ctx: FeatureContext, values: dict) -> dict:
    """Set page-number style, start value and restart policy for the report's pagination metadata."""
    state = _state(ctx)
    _page_layout(state, values["templateId"])["pageNumbers"] = {
        "startAt": int(values["startAt"]),
        "format": values["format"],
        "restartEachSection": values["restartEachSection"],
    }
    _save(ctx, state)
    sample = (
        "iv" if values["format"] == "roman" else "S-04" if values["format"] == "prefixed" else "4"
    )
    return result(
        summary={
            "startAt": values["startAt"],
            "format": values["format"],
            "restartEachSection": values["restartEachSection"],
            "example": sample,
        }
    )


@feature(
    "documentsReportPagination.sectionBreaks",
    "Section Breaks",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("beforeSection", "Start new page before section", "appendix"),
        select(
            "breakType",
            "Break type",
            [("page", "New page"), ("oddPage", "Next odd page"), ("continuous", "Continuous")],
            "page",
        ),
        checkbox("resetPageNumber", "Restart page number", False),
    ],
)
def section_breaks(ctx: FeatureContext, values: dict) -> dict:
    """Insert a validated section break rule at the boundary before a named included report section."""
    data = _template_data(ctx, values["templateId"])
    if values["beforeSection"] not in {item["id"] for item in data["sections"]}:
        raise FeatureInputError("Choose a section present in the template.")
    state = _state(ctx)
    breaks = _page_layout(state, data["id"]).setdefault("sectionBreaks", {})
    breaks[values["beforeSection"]] = {
        "type": values["breakType"],
        "resetPageNumber": values["resetPageNumber"],
    }
    _save(ctx, state)
    return result(
        summary={
            "beforeSection": values["beforeSection"],
            "breakType": values["breakType"],
            "resetPageNumber": values["resetPageNumber"],
        }
    )


@feature(
    "documentsReportPagination.tableOfContents",
    "Table of Contents",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        number("headingDepth", "Heading depth", 3, min=1, max=6),
        checkbox("includeFigures", "Include figures", True),
        checkbox("includeTables", "Include tables", True),
    ],
)
def pagination_toc(ctx: FeatureContext, values: dict) -> dict:
    """Configure contents depth and whether figure and table lists accompany the report contents page."""
    data = _template_data(ctx, values["templateId"])
    data["contents"] = True
    _save_template(ctx, data)
    state = _state(ctx)
    _page_layout(state, data["id"])["contents"] = {
        "headingDepth": int(values["headingDepth"]),
        "includeFigures": values["includeFigures"],
        "includeTables": values["includeTables"],
    }
    _save(ctx, state)
    return result(
        summary={
            "contentsEnabled": True,
            "headingDepth": values["headingDepth"],
            "figureList": values["includeFigures"],
            "tableList": values["includeTables"],
        }
    )


@feature(
    "documentsReportPagination.index",
    "Index",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("terms", "Index terms, comma-separated", "foundation,beam,soil"),
    ],
)
def report_index(ctx: FeatureContext, values: dict) -> dict:
    """Build an alphabetical index of selected terms using occurrences in report notes and inserted content."""
    terms = sorted(
        {item.strip() for item in values["terms"].split(",") if item.strip()}, key=str.casefold
    )
    state = _state(ctx)
    haystack = json.dumps(state["content"], ensure_ascii=False).casefold()
    rows = [
        {"term": term, "occurrences": len(re.findall(re.escape(term.casefold()), haystack))}
        for term in terms
    ]
    state.setdefault("indexes", {})[values["templateId"]] = rows
    _save(ctx, state)
    return result(
        summary={
            "indexedTermCount": len(rows),
            "matchedTermCount": sum(row["occurrences"] > 0 for row in rows),
        },
        tables=[table("Report index", [("term", "Term"), ("occurrences", "Occurrences")], rows)],
    )


@feature(
    "documentsReportPagination.bookmarks",
    "Bookmarks",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("sectionIds", "Sections to bookmark (comma-separated)", "basis,design,appendix"),
        checkbox("includeSubheadings", "Include subheadings", False),
    ],
)
def bookmarks(ctx: FeatureContext, values: dict) -> dict:
    """Create stable navigation bookmark ids for selected report sections."""
    data = _template_data(ctx, values["templateId"])
    selected = [item.strip() for item in values["sectionIds"].split(",") if item.strip()]
    available = {item["id"] for item in data["sections"]}
    if not selected or set(selected) - available:
        raise FeatureInputError("Choose section ids present in the report template.")
    rows = [
        {
            "section": section,
            "bookmark": re.sub(r"[^a-z0-9-]+", "-", section.casefold()),
            "includeSubheadings": values["includeSubheadings"],
        }
        for section in selected
    ]
    state = _state(ctx)
    _page_layout(state, data["id"])["bookmarks"] = rows
    _save(ctx, state)
    return result(
        summary={"bookmarkCount": len(rows)},
        tables=[
            table(
                "Report bookmarks",
                [
                    ("section", "Section"),
                    ("bookmark", "Bookmark id"),
                    ("includeSubheadings", "Subheadings"),
                ],
                rows,
            )
        ],
    )


@feature(
    "documentsReportPagination.headingNumbering",
    "Heading Numbering",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        number("maximumLevel", "Heading levels to number", 3, min=1, max=6),
        select(
            "style",
            "Numbering style",
            [("decimal", "1, 1.1, 1.1.1"), ("appendix", "A, A.1, A.1.1")],
            "decimal",
        ),
        text("separator", "Number separator", "."),
    ],
)
def heading_numbering(ctx: FeatureContext, values: dict) -> dict:
    """Configure report heading number depth, separator and decimal or appendix lettering style."""
    state = _state(ctx)
    _page_layout(state, values["templateId"])["headingNumbering"] = {
        "maximumLevel": int(values["maximumLevel"]),
        "style": values["style"],
        "separator": values["separator"],
    }
    _save(ctx, state)
    return result(
        summary={
            "maximumLevel": values["maximumLevel"],
            "style": values["style"],
            "separator": values["separator"],
        }
    )


@feature(
    "documentsReportPagination.keepWithNext",
    "Keep With Next",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        number("headingLevel", "Apply through heading level", 2, min=1, max=6),
        checkbox("keepCaptionWithTable", "Keep table captions with tables", True),
    ],
)
def keep_with_next(ctx: FeatureContext, values: dict) -> dict:
    """Set pagination keep rules for report headings and table captions to avoid orphaned labels."""
    state = _state(ctx)
    _page_layout(state, values["templateId"])["keepWithNext"] = {
        "headingThroughLevel": int(values["headingLevel"]),
        "tableCaption": values["keepCaptionWithTable"],
    }
    _save(ctx, state)
    return result(
        summary={
            "headingThroughLevel": values["headingLevel"],
            "tableCaptionKept": values["keepCaptionWithTable"],
        }
    )


@feature(
    "documentsReportPagination.orphanControl",
    "Orphan Control",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        number("minimumLines", "Minimum lines at page edge", 2, min=1, max=10),
        checkbox("protectCaptions", "Keep captions with following content", True),
    ],
)
def orphan_control(ctx: FeatureContext, values: dict) -> dict:
    """Configure minimum lines retained at a page boundary and caption-to-content pagination constraints."""
    state = _state(ctx)
    _page_layout(state, values["templateId"])["orphanControl"] = {
        "minimumLines": int(values["minimumLines"]),
        "protectCaptions": values["protectCaptions"],
    }
    _save(ctx, state)
    return result(
        summary={
            "minimumLines": values["minimumLines"],
            "captionsProtected": values["protectCaptions"],
        }
    )


@feature(
    "documentsReportPagination.multiColumnFlow",
    "Multi Column Flow",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("sectionId", "Section id", "appendix"),
        number("columns", "Column count", 2, min=1, max=4),
        checkbox("balanceLastPage", "Balance final page columns", True),
    ],
)
def multi_column_flow(ctx: FeatureContext, values: dict) -> dict:
    """Configure a balanced multi-column flow for one report section with a positive column count."""
    data = _template_data(ctx, values["templateId"])
    if values["sectionId"] not in {row["id"] for row in data["sections"]}:
        raise FeatureInputError("Choose a section in the active template.")
    state = _state(ctx)
    _page_layout(state, data["id"]).setdefault("multiColumnFlow", {})[values["sectionId"]] = {
        "columns": int(values["columns"]),
        "balanceLastPage": values["balanceLastPage"],
    }
    _save(ctx, state)
    return result(
        summary={
            "sectionId": values["sectionId"],
            "columns": values["columns"],
            "balanceLastPage": values["balanceLastPage"],
        }
    )


@feature(
    "documentsReportPagination.draftWatermark",
    "Draft Watermark",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("watermark", "Watermark text", "DRAFT"),
        number("opacity", "Opacity", 15, unit="%", min=1, max=100),
        select(
            "pages",
            "Page range",
            [("all", "All pages"), ("cover", "Cover only"), ("internal", "Internal pages")],
            "all",
        ),
    ],
)
def draft_watermark(ctx: FeatureContext, values: dict) -> dict:
    """Configure draft watermark content, opacity and page scope on a report template."""
    state = _state(ctx)
    _page_layout(state, values["templateId"])["draftWatermark"] = {
        "text": values["watermark"].strip(),
        "opacityPercent": values["opacity"],
        "pages": values["pages"],
    }
    _save(ctx, state)
    return result(
        summary={
            "watermark": values["watermark"].strip(),
            "opacityPercent": values["opacity"],
            "scope": values["pages"],
        },
        notes=[
            "The rule is saved for the report layout; apply it to a distribution PDF with the Watermark Document feature."
        ],
    )


@feature(
    "documentsReportPagination.confidentialStamp",
    "Confidential Stamp",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("classification", "Classification text", "CONFIDENTIAL"),
        text("recipient", "Recipient-specific label", ""),
        checkbox("includeFooter", "Repeat in page footer", True),
    ],
)
def confidential_stamp(ctx: FeatureContext, values: dict) -> dict:
    """Add a confidentiality classification label and optional recipient-specific footer stamp to report pagination."""
    if not values["classification"].strip():
        raise FeatureInputError("Enter a confidentiality classification.")
    state = _state(ctx)
    _page_layout(state, values["templateId"])["confidentialStamp"] = {
        "classification": values["classification"].strip(),
        "recipient": values["recipient"].strip(),
        "includeFooter": values["includeFooter"],
    }
    _save(ctx, state)
    return result(
        summary={
            "classification": values["classification"].strip(),
            "recipientLabel": values["recipient"].strip(),
            "footerRepeated": values["includeFooter"],
        }
    )


@feature(
    "documentsReportPagination.backgroundOverlay",
    "Background Overlay",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text(
            "backgroundPath",
            "Project-relative background PDF or image",
            "11 Exports/report-background.pdf",
        ),
        text("sectionIds", "Apply to section ids (blank means all)", ""),
        checkbox("underContent", "Place behind text", True),
    ],
)
def background_overlay(ctx: FeatureContext, values: dict) -> dict:
    """Bind an existing project background PDF/image to report pages after validating its type and section scope."""
    root = require_root(ctx)
    path = (root / values["backgroundPath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Background file must be inside the project folder.") from exc
    if path.suffix.lower() not in (".pdf", ".png", ".jpg", ".jpeg") or not path.is_file():
        raise FeatureInputError("Choose an existing PDF, PNG or JPEG background file.")
    sections = [part.strip() for part in values["sectionIds"].split(",") if part.strip()]
    state = _state(ctx)
    _page_layout(state, values["templateId"])["backgroundOverlay"] = {
        "path": path.relative_to(root).as_posix(),
        "sections": sections or ["*"],
        "underContent": values["underContent"],
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    _save(ctx, state)
    return result(
        summary={
            "backgroundPath": path.relative_to(root).as_posix(),
            "sectionCount": len(sections) if sections else "all",
            "underContent": values["underContent"],
        }
    )


@feature(
    "documentsReportPagination.applyMasterPage",
    "Apply Master Page",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        text("sectionId", "Report section", "design"),
        text("masterPage", "Master-page name", "Engineering Standard"),
        checkbox("inheritHeaders", "Inherit headers and footers", True),
    ],
)
def apply_master_page(ctx: FeatureContext, values: dict) -> dict:
    """Assign a named master-page layout to a report section and control its header/footer inheritance."""
    data = _template_data(ctx, values["templateId"])
    if values["sectionId"] not in {row["id"] for row in data["sections"]}:
        raise FeatureInputError("Choose an included report section.")
    state = _state(ctx)
    _page_layout(state, data["id"]).setdefault("masterPages", {})[values["sectionId"]] = {
        "name": values["masterPage"].strip(),
        "inheritHeaders": values["inheritHeaders"],
    }
    _save(ctx, state)
    return result(
        summary={
            "sectionId": values["sectionId"],
            "masterPage": values["masterPage"].strip(),
            "inheritHeaders": values["inheritHeaders"],
        }
    )


@feature(
    "documentsReportPagination.firstPageLayout",
    "First Page Layout",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        checkbox("suppressHeader", "Suppress standard header", True),
        checkbox("suppressFooter", "Suppress standard footer", True),
        number("coverTopSpaceMm", "Cover title top spacing", 45, unit="mm", min=0),
    ],
)
def first_page_layout(ctx: FeatureContext, values: dict) -> dict:
    """Configure a distinct cover-page layout with independently suppressed running header and footer."""
    state = _state(ctx)
    _page_layout(state, values["templateId"])["firstPage"] = {
        "suppressHeader": values["suppressHeader"],
        "suppressFooter": values["suppressFooter"],
        "coverTopSpaceMm": values["coverTopSpaceMm"],
    }
    _save(ctx, state)
    return result(
        summary={
            "headerSuppressed": values["suppressHeader"],
            "footerSuppressed": values["suppressFooter"],
            "coverTopSpaceMm": values["coverTopSpaceMm"],
        }
    )


@feature(
    "documentsReportPagination.oddEvenPages",
    "Odd Even Pages",
    part="settings",
    fields=[
        text("templateId", "Template id", "default"),
        checkbox("mirrorMargins", "Mirror inside/outside margins", True),
        text("oddHeader", "Odd-page header", "{project.name}"),
        text("evenHeader", "Even-page header", "{revision}"),
        checkbox("alternateFooters", "Alternate footer content", True),
    ],
)
def odd_even_pages(ctx: FeatureContext, values: dict) -> dict:
    """Configure mirrored margins and alternating odd/even headers and footers for duplex report printing."""
    state = _state(ctx)
    layout = _page_layout(state, values["templateId"])
    layout["oddEven"] = {
        "mirrorMargins": values["mirrorMargins"],
        "oddHeader": values["oddHeader"],
        "evenHeader": values["evenHeader"],
        "alternateFooters": values["alternateFooters"],
    }
    _save(ctx, state)
    return result(
        summary={
            "mirrorMargins": values["mirrorMargins"],
            "alternatingHeaders": values["oddHeader"] != values["evenHeader"],
            "alternateFooters": values["alternateFooters"],
        }
    )
