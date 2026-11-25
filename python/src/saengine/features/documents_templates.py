"""Document page, report and calculation-sheet template features."""

from __future__ import annotations

import json
import re

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
    document_state,
    require_root,
    save_document_state,
)


def _state(ctx):
    state = document_state(ctx, "templateLibrary")
    state.setdefault("templates", {})
    state.setdefault("assets", {})
    state.setdefault("themes", {})
    return state


def _save(ctx, state):
    return save_document_state(ctx, "templateLibrary", state)


def _id(value):
    key = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", key):
        raise FeatureInputError("Template id must use lowercase letters, digits and hyphens.")
    return key


@feature(
    "docTemplate.pageLayout",
    "Page Layout",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        number("widthMm", "Page width", 420, unit="mm", min=50),
        number("heightMm", "Page height", 297, unit="mm", min=50),
        select(
            "orientation",
            "Orientation",
            [("portrait", "Portrait"), ("landscape", "Landscape")],
            "landscape",
        ),
    ],
)
def page_layout(ctx: FeatureContext, values: dict) -> dict:
    """Save a document page size and orientation for a named reusable layout template."""
    if values["widthMm"] <= 0 or values["heightMm"] <= 0:
        raise FeatureInputError("Page dimensions must be positive.")
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template["page"] = {
        "widthMm": values["widthMm"],
        "heightMm": values["heightMm"],
        "orientation": values["orientation"],
    }
    _save(ctx, state)
    return result(summary={"templateId": values["templateId"], "page": template["page"]})


@feature(
    "docTemplate.margins",
    "Margins",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        number("topMm", "Top", 15, unit="mm", min=0),
        number("rightMm", "Right", 15, unit="mm", min=0),
        number("bottomMm", "Bottom", 15, unit="mm", min=0),
        number("leftMm", "Left", 15, unit="mm", min=0),
    ],
)
def margins(ctx: FeatureContext, values: dict) -> dict:
    """Set page margins and reject values that leave no printable page area."""
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    page = template.get("page", {"widthMm": 210, "heightMm": 297})
    if (
        values["leftMm"] + values["rightMm"] >= page["widthMm"]
        or values["topMm"] + values["bottomMm"] >= page["heightMm"]
    ):
        raise FeatureInputError("Margins must leave positive page width and height.")
    template["marginsMm"] = {key: values[f"{key}Mm"] for key in ("top", "right", "bottom", "left")}
    _save(ctx, state)
    return result(summary={"templateId": values["templateId"], "marginsMm": template["marginsMm"]})


@feature(
    "docTemplate.columns",
    "Columns",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        number("count", "Column count", 1, min=1, max=6),
        number("gapMm", "Column gap", 8, unit="mm", min=0),
        checkbox("equalWidth", "Equal column widths", True),
    ],
)
def columns(ctx: FeatureContext, values: dict) -> dict:
    """Configure the number, spacing and width distribution of page text columns."""
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template["columns"] = {
        "count": int(values["count"]),
        "gapMm": values["gapMm"],
        "equalWidth": values["equalWidth"],
    }
    _save(ctx, state)
    return result(
        summary={
            "columns": int(values["count"]),
            "gapMm": values["gapMm"],
            "equalWidth": values["equalWidth"],
        }
    )


@feature(
    "docTemplate.styles",
    "Styles",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text("styleName", "Style name", "Heading 1"),
        text("font", "Font family", "Aptos"),
        number("fontSizePt", "Font size", 16, min=6, max=96),
        checkbox("bold", "Bold", True),
        text("colour", "Text colour", "#1F4E78"),
    ],
)
def styles(ctx: FeatureContext, values: dict) -> dict:
    """Define a named text style with font, size, weight and validated colour."""
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", values["colour"]):
        raise FeatureInputError("Text colour must be a six-digit hexadecimal colour.")
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template.setdefault("styles", {})[values["styleName"]] = {
        "font": values["font"],
        "fontSizePt": values["fontSizePt"],
        "bold": values["bold"],
        "colour": values["colour"],
    }
    _save(ctx, state)
    return result(
        summary={
            "styleName": values["styleName"],
            "definition": template["styles"][values["styleName"]],
        }
    )


@feature(
    "docTemplate.orientation",
    "Orientation",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        select(
            "orientation",
            "Page orientation",
            [("portrait", "Portrait"), ("landscape", "Landscape")],
            "portrait",
        ),
    ],
)
def orientation(ctx: FeatureContext, values: dict) -> dict:
    """Change a named page template to portrait or landscape orientation."""
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template.setdefault("page", {})["orientation"] = values["orientation"]
    width = template["page"].setdefault("widthMm", 210)
    height = template["page"].setdefault("heightMm", 297)
    if (values["orientation"] == "landscape") != (width > height):
        template["page"]["widthMm"], template["page"]["heightMm"] = height, width
    _save(ctx, state)
    return result(
        summary={
            "templateId": values["templateId"],
            "orientation": values["orientation"],
            "widthMm": template["page"]["widthMm"],
            "heightMm": template["page"]["heightMm"],
        }
    )


@feature(
    "docTemplate.pageBackground",
    "Page Background",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text(
            "imagePath",
            "Project-relative background image",
            "11 Exports/branding/page-background.png",
        ),
        number("opacityPercent", "Opacity", 100, unit="%", min=1, max=100),
    ],
)
def page_background(ctx: FeatureContext, values: dict) -> dict:
    """Attach an existing project image as a page background with a bounded opacity."""
    root = require_root(ctx)
    path = (root / values["imagePath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Background image must be inside the project folder.") from exc
    if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise FeatureInputError("Choose an existing PNG or JPEG image.")
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template["background"] = {
        "path": path.relative_to(root).as_posix(),
        "opacityPercent": values["opacityPercent"],
    }
    _save(ctx, state)
    return result(
        summary={
            "imagePath": template["background"]["path"],
            "opacityPercent": values["opacityPercent"],
        }
    )


@feature(
    "docTemplate.textBlock",
    "Text Block",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text("blockId", "Block id", "project-heading"),
        text("content", "Text or placeholders", "{project.name}"),
        text("style", "Named style", "Heading 1"),
        number("xMm", "X position", 20, unit="mm"),
        number("yMm", "Y position", 20, unit="mm"),
    ],
)
def text_block(ctx: FeatureContext, values: dict) -> dict:
    """Add or update a text block with template placeholders and page coordinates."""
    state = _state(ctx)
    blocks = state["templates"].setdefault(_id(values["templateId"]), {}).setdefault("blocks", {})
    blocks[values["blockId"]] = {
        "kind": "text",
        "content": values["content"],
        "style": values["style"],
        "xMm": values["xMm"],
        "yMm": values["yMm"],
    }
    _save(ctx, state)
    return result(
        summary={
            "blockId": values["blockId"],
            "kind": "text",
            "positionMm": [values["xMm"], values["yMm"]],
        }
    )


@feature(
    "docTemplate.imageBlock",
    "Image Block",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text("blockId", "Block id", "company-logo"),
        text("imagePath", "Project-relative image", "11 Exports/branding/logo.png"),
        number("widthMm", "Width", 40, unit="mm", min=1),
        number("heightMm", "Height", 20, unit="mm", min=1),
        number("xMm", "X", 20, unit="mm"),
        number("yMm", "Y", 20, unit="mm"),
    ],
)
def image_block(ctx: FeatureContext, values: dict) -> dict:
    """Place a validated project image file as a sized image block in a document template."""
    root = require_root(ctx)
    path = (root / values["imagePath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Image block must use a project-relative path.") from exc
    if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise FeatureInputError("Image block needs an existing PNG or JPEG.")
    state = _state(ctx)
    block = {
        "kind": "image",
        "path": path.relative_to(root).as_posix(),
        "widthMm": values["widthMm"],
        "heightMm": values["heightMm"],
        "xMm": values["xMm"],
        "yMm": values["yMm"],
    }
    state["templates"].setdefault(_id(values["templateId"]), {}).setdefault("blocks", {})[
        values["blockId"]
    ] = block
    _save(ctx, state)
    return result(
        summary={
            "blockId": values["blockId"],
            "imagePath": block["path"],
            "sizeMm": [block["widthMm"], block["heightMm"]],
        }
    )


@feature(
    "docTemplate.chartBlock",
    "Chart Block",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text("blockId", "Block id", "results-plot"),
        text("chartId", "Worksheet chart id", "chart-1"),
        number("widthMm", "Width", 150, unit="mm", min=10),
        number("heightMm", "Height", 90, unit="mm", min=10),
        number("xMm", "X", 20, unit="mm"),
        number("yMm", "Y", 60, unit="mm"),
    ],
)
def chart_block(ctx: FeatureContext, values: dict) -> dict:
    """Bind a chart stored in worksheet state into a document template at a defined size and position."""
    from saengine.features.documents_common import worksheet_workspace

    _, workspace = worksheet_workspace(ctx, "calculations")
    chart = next((c for c in workspace.get("charts", []) if c.get("id") == values["chartId"]), None)
    if chart is None:
        raise FeatureInputError("Worksheet chart id was not found.")
    block = {
        "kind": "chart",
        "chartId": values["chartId"],
        "worksheetId": "calculations",
        "widthMm": values["widthMm"],
        "heightMm": values["heightMm"],
        "xMm": values["xMm"],
        "yMm": values["yMm"],
    }
    state = _state(ctx)
    state["templates"].setdefault(_id(values["templateId"]), {}).setdefault("blocks", {})[
        values["blockId"]
    ] = block
    _save(ctx, state)
    return result(
        summary={
            "blockId": values["blockId"],
            "chartId": values["chartId"],
            "positionMm": [values["xMm"], values["yMm"]],
        }
    )


@feature(
    "docTemplate.signatureBlock",
    "Signature Block",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text("blockId", "Block id", "review-signatures"),
        text("roles", "Signatory roles, comma separated", "Designed by,Checked by,Approved by"),
        number("lineWidthMm", "Signature line width", 50, unit="mm", min=10),
    ],
)
def signature_block(ctx: FeatureContext, values: dict) -> dict:
    """Create a signature block with a separate line and label for each specified signatory role."""
    roles = [item.strip() for item in values["roles"].split(",") if item.strip()]
    if not roles:
        raise FeatureInputError("Enter at least one signature role.")
    state = _state(ctx)
    state["templates"].setdefault(_id(values["templateId"]), {}).setdefault("blocks", {})[
        values["blockId"]
    ] = {"kind": "signatures", "roles": roles, "lineWidthMm": values["lineWidthMm"]}
    _save(ctx, state)
    return result(
        summary={"blockId": values["blockId"], "signatoryCount": len(roles), "roles": roles}
    )


@feature(
    "docTemplate.logoLibrary",
    "Logo Library",
    part="documents",
    fields=[
        text("name", "Logo name", "Company logo"),
        text("imagePath", "Project-relative PNG or JPEG", "11 Exports/branding/logo.png"),
        text("description", "Usage note", "Primary company mark"),
    ],
)
def logo_library(ctx: FeatureContext, values: dict) -> dict:
    """Register an existing project image as a named reusable document logo asset."""
    root = require_root(ctx)
    path = (root / values["imagePath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Logo must be inside the project folder.") from exc
    if not path.is_file() or path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise FeatureInputError("Logo library entry needs an existing PNG or JPEG.")
    state = _state(ctx)
    state["assets"][values["name"]] = {
        "type": "logo",
        "path": path.relative_to(root).as_posix(),
        "description": values["description"],
        "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest(),
    }
    _save(ctx, state)
    return result(summary={"logo": values["name"], "path": state["assets"][values["name"]]["path"]})


@feature(
    "docTemplate.colourTheme",
    "Colour Theme",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text("primary", "Primary colour", "#1F4E78"),
        text("secondary", "Secondary colour", "#5B9BD5"),
        text("accent", "Accent colour", "#ED7D31"),
        text("warning", "Warning colour", "#C00000"),
    ],
)
def colour_theme(ctx: FeatureContext, values: dict) -> dict:
    """Set primary, secondary, accent and warning colours after validating each hex code."""
    palette = {key: values[key] for key in ("primary", "secondary", "accent", "warning")}
    if any(not re.fullmatch(r"#[0-9A-Fa-f]{6}", colour) for colour in palette.values()):
        raise FeatureInputError("Every theme colour must use #RRGGBB format.")
    state = _state(ctx)
    state["themes"][_id(values["templateId"])] = palette
    _save(ctx, state)
    return result(summary={"templateId": values["templateId"], "palette": palette})


@feature(
    "docTemplate.fontSet",
    "Font Set",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text("bodyFont", "Body font", "Aptos"),
        text("headingFont", "Heading font", "Aptos Display"),
        text("monoFont", "Monospaced font", "Consolas"),
    ],
)
def font_set(ctx: FeatureContext, values: dict) -> dict:
    """Set the body, heading and monospaced font families for a document template."""
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template["fonts"] = {
        "body": values["bodyFont"],
        "heading": values["headingFont"],
        "monospace": values["monoFont"],
    }
    _save(ctx, state)
    return result(summary={"templateId": values["templateId"], "fonts": template["fonts"]})


@feature(
    "docTemplate.calcSheetTemplate",
    "Calculation Sheet Template",
    part="documents",
    fields=[
        text("templateId", "Template id", "beam-check"),
        text("title", "Worksheet title", "Beam flexure check"),
        text("kind", "Worksheet calculation kind", "beamFlexure"),
        text("reference", "Reference note", "AISC 360"),
    ],
)
def calc_sheet_template(ctx: FeatureContext, values: dict) -> dict:
    """Create a reusable typed worksheet template containing calculation kind, title and reference."""
    key = _id(values["templateId"])
    state = _state(ctx)
    state.setdefault("calculationSheets", {})[key] = {
        "title": values["title"],
        "kind": values["kind"],
        "reference": values["reference"],
        "inputs": {},
    }
    _save(ctx, state)
    return result(
        summary={"worksheetTemplateId": key, "title": values["title"], "kind": values["kind"]}
    )


@feature(
    "docTemplate.reportTemplate",
    "Report Template",
    part="documents",
    fields=[
        text("templateId", "Report template id", "submission"),
        text("name", "Template name", "Submission report"),
        select(
            "detail", "Detail", [("summary", "Summary"), ("full", "Full calculations")], "summary"
        ),
        select("paper", "Paper", [("a4", "A4"), ("us-letter", "US Letter")], "a4"),
    ],
)
def report_template(ctx: FeatureContext, values: dict) -> dict:
    """Create a validated report template using the engine's report-template model and save it to the project."""
    root = require_root(ctx)
    from saengine.library.report_template import ReportTemplate, save_template

    key = _id(values["templateId"])
    try:
        template = ReportTemplate(
            id=key, name=values["name"], detail=values["detail"], paper=values["paper"]
        )
        path = save_template(root, template)
    except ValueError as exc:
        raise FeatureInputError(f"Report template values are invalid: {exc}") from exc
    return result(
        summary={
            "reportTemplateId": key,
            "path": path.relative_to(root).as_posix(),
            "sections": len(template.sections),
        }
    )


@feature(
    "docTemplate.memoTemplate",
    "Memo Template",
    part="documents",
    fields=[
        text("templateId", "Memo template id", "engineering-memo"),
        text("title", "Template title", "Engineering Memorandum"),
        text("toLabel", "Recipient label", "To"),
        text("fromLabel", "Author label", "From"),
        text("subjectLabel", "Subject label", "Subject"),
    ],
)
def memo_template(ctx: FeatureContext, values: dict) -> dict:
    """Save a reusable memo heading with labeled recipient, author and subject fields."""
    state = _state(ctx)
    state.setdefault("memos", {})[_id(values["templateId"])] = {
        "title": values["title"],
        "labels": {
            "to": values["toLabel"],
            "from": values["fromLabel"],
            "subject": values["subjectLabel"],
        },
        "sections": ["Purpose", "Discussion", "Recommendations"],
    }
    _save(ctx, state)
    return result(
        summary={
            "memoTemplateId": values["templateId"],
            "title": values["title"],
            "sectionCount": 3,
        }
    )


@feature(
    "docTemplate.runningHeader",
    "Running Header",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text("leftText", "Left header", "{project.name}"),
        text("centerText", "Centre header", "{report.title}"),
        text("rightText", "Right header", "{revision}"),
    ],
)
def running_header(ctx: FeatureContext, values: dict) -> dict:
    """Set left, centred and right running header text with project metadata placeholders."""
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template["runningHeader"] = {
        "left": values["leftText"],
        "center": values["centerText"],
        "right": values["rightText"],
    }
    _save(ctx, state)
    return result(summary={"runningHeader": template["runningHeader"]})


@feature(
    "docTemplate.pageNumbering",
    "Page Numbering",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        select(
            "format",
            "Number format",
            [("1", "1, 2, 3"), ("roman", "i, ii, iii"), ("pageOf", "Page n of m")],
            "pageOf",
        ),
        number("start", "Start number", 1, min=1),
        checkbox("restartEachSection", "Restart by section", False),
    ],
)
def page_numbering(ctx: FeatureContext, values: dict) -> dict:
    """Configure page number format, starting value and section restart behavior."""
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template["pageNumbering"] = {
        "format": values["format"],
        "start": int(values["start"]),
        "restartEachSection": values["restartEachSection"],
    }
    _save(ctx, state)
    return result(summary={"pageNumbering": template["pageNumbering"]})


@feature(
    "docTemplate.projectMetaTag",
    "Project Meta Tag",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text("tag", "Placeholder", "project.name"),
        text("sourcePath", "Project data path", "settings.project.name"),
        text("fallback", "Fallback text", "Untitled project"),
    ],
)
def project_meta_tag(ctx: FeatureContext, values: dict) -> dict:
    """Bind a reusable document placeholder to a project-data path and specify its fallback."""
    from saengine.features.documents_common import dotted_value, project_fields

    value = dotted_value(project_fields(ctx), values["sourcePath"])
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template.setdefault("metadataTags", {})[values["tag"]] = {
        "sourcePath": values["sourcePath"],
        "fallback": values["fallback"],
        "preview": values["fallback"] if value is None else value,
    }
    _save(ctx, state)
    return result(
        summary={
            "tag": values["tag"],
            "preview": template["metadataTags"][values["tag"]]["preview"],
        }
    )


@feature(
    "docTemplate.coverTemplate",
    "Cover Template",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text("title", "Cover title", "Structural Design Report"),
        text("subtitle", "Subtitle", "{project.name}"),
        checkbox("showStatus", "Show design status", True),
        checkbox("showIssueDate", "Show issue date", True),
    ],
)
def cover_template(ctx: FeatureContext, values: dict) -> dict:
    """Configure the cover title, project subtitle, design status and issue date visibility."""
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template["cover"] = {
        "title": values["title"],
        "subtitle": values["subtitle"],
        "showStatus": values["showStatus"],
        "showIssueDate": values["showIssueDate"],
    }
    _save(ctx, state)
    return result(summary={"coverTemplate": template["cover"]})


@feature(
    "docTemplate.sectionDivider",
    "Section Divider",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        text("sectionId", "Section id", "results"),
        text("label", "Divider label", "Analysis results"),
        checkbox("startOnRightPage", "Start on right-hand page", True),
    ],
)
def section_divider(ctx: FeatureContext, values: dict) -> dict:
    """Set section divider title and page-break behavior for one document section."""
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template.setdefault("sectionDividers", {})[values["sectionId"]] = {
        "label": values["label"],
        "startOnRightPage": values["startOnRightPage"],
    }
    _save(ctx, state)
    return result(
        summary={
            "sectionId": values["sectionId"],
            "label": values["label"],
            "rightPage": values["startOnRightPage"],
        }
    )


@feature(
    "docTemplate.gridGuides",
    "Grid Guides",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        number("horizontalMm", "Horizontal guide spacing", 10, unit="mm", min=1),
        number("verticalMm", "Vertical guide spacing", 10, unit="mm", min=1),
        checkbox("show", "Show alignment guides", True),
    ],
)
def grid_guides(ctx: FeatureContext, values: dict) -> dict:
    """Configure the non-printing alignment grid used by document block placement."""
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template["gridGuides"] = {
        "horizontalMm": values["horizontalMm"],
        "verticalMm": values["verticalMm"],
        "show": values["show"],
    }
    _save(ctx, state)
    return result(
        summary={
            "guidesVisible": values["show"],
            "horizontalMm": values["horizontalMm"],
            "verticalMm": values["verticalMm"],
        }
    )


@feature(
    "docTemplate.defaultStyles",
    "Default Styles",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        select(
            "preset",
            "Style preset",
            [("engineering", "Engineering"), ("memo", "Memo"), ("compact", "Compact")],
            "engineering",
        ),
    ],
)
def default_styles(ctx: FeatureContext, values: dict) -> dict:
    """Apply one of the explicit engineering, memo or compact heading/body style sets."""
    presets = {
        "engineering": {
            "body": {"font": "Aptos", "fontSizePt": 10},
            "heading1": {"font": "Aptos Display", "fontSizePt": 18, "bold": True},
            "heading2": {"font": "Aptos Display", "fontSizePt": 14, "bold": True},
        },
        "memo": {
            "body": {"font": "Arial", "fontSizePt": 11},
            "heading1": {"font": "Arial", "fontSizePt": 16, "bold": True},
            "heading2": {"font": "Arial", "fontSizePt": 13, "bold": True},
        },
        "compact": {
            "body": {"font": "Aptos", "fontSizePt": 9},
            "heading1": {"font": "Aptos Display", "fontSizePt": 14, "bold": True},
            "heading2": {"font": "Aptos Display", "fontSizePt": 11, "bold": True},
        },
    }
    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template["styles"] = presets[values["preset"]]
    _save(ctx, state)
    return result(
        summary={
            "templateId": values["templateId"],
            "preset": values["preset"],
            "styleCount": len(template["styles"]),
        }
    )


@feature(
    "docTemplate.lockTemplate",
    "Lock Template",
    part="documents",
    fields=[
        text("templateId", "Template id", "engineering"),
        checkbox("locked", "Lock template from edits", True),
        text("owner", "Owner", "Engineering manager"),
    ],
)
def lock_template(ctx: FeatureContext, values: dict) -> dict:
    """Lock or unlock a template and record its responsible owner and change time."""
    from datetime import UTC, datetime

    state = _state(ctx)
    template = state["templates"].setdefault(_id(values["templateId"]), {})
    template["lock"] = {
        "locked": values["locked"],
        "owner": values["owner"],
        "changedAt": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _save(ctx, state)
    return result(
        summary={
            "templateId": values["templateId"],
            "locked": values["locked"],
            "owner": values["owner"],
        }
    )


@feature(
    "docTemplate.importTemplate",
    "Import Template",
    part="documents",
    fields=[
        text("jsonPath", "Project-relative JSON template", "11 Exports/templates/import.json"),
        text("templateId", "New template id", "imported-template"),
        checkbox("replace", "Replace same id", False),
    ],
)
def import_template(ctx: FeatureContext, values: dict) -> dict:
    """Import a project JSON layout template after validating its shape and destination id."""
    root = require_root(ctx)
    path = (root / values["jsonPath"]).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise FeatureInputError("Template import must use a project-relative path.") from exc
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FeatureInputError(f"Template file could not be read: {exc}") from exc
    if not isinstance(data, dict) or any(
        key
        not in (
            "page",
            "marginsMm",
            "columns",
            "styles",
            "fonts",
            "blocks",
            "cover",
            "runningHeader",
            "pageNumbering",
        )
        for key in data
    ):
        raise FeatureInputError("JSON is not a supported document layout template.")
    state = _state(ctx)
    key = _id(values["templateId"])
    if key in state["templates"] and not values["replace"]:
        raise FeatureInputError("Template already exists; enable Replace same id to overwrite it.")
    state["templates"][key] = data
    _save(ctx, state)
    return result(
        summary={
            "templateId": key,
            "importedKeys": sorted(data),
            "source": path.relative_to(root).as_posix(),
        }
    )
