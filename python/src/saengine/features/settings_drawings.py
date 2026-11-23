"""Project Settings - Drawings & Reports tab: sheet sizes, title blocks, scales, annotations, standards, registers."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import (
    FeatureContext,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.settings_common import export_file, json_dumps_clean, load_settings
from saengine.library.settings import DETAIL_SCALES, LINEWEIGHTS, PLAN_SCALES

_SHEET_MM = {
    "A0": (1189.0, 841.0),
    "A1": (841.0, 594.0),
    "A2": (594.0, 420.0),
    "A3": (420.0, 297.0),
    "ANSI D": (863.6, 558.8),
    "ARCH D": (914.4, 609.6),
}


@feature(
    "settingsDrawings.sheetSizes",
    "Sheet Sizes",
    part="settings",
    fields=[
        select(
            "orientation",
            "Sheet orientation",
            [("landscape", "Landscape"), ("portrait", "Portrait")],
            "landscape",
        ),
    ],
    requires_project=False,
)
def sheet_sizes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List standard ISO and US drawing sheet dimensions and highlight active project sheet size."""
    st = load_settings(ctx)
    cur = st.drawings.sheetSize
    rows = []
    for name, (w, h) in _SHEET_MM.items():
        sw, sh = (w, h) if values["orientation"] == "landscape" else (h, w)
        rows.append(
            {
                "sheet": name,
                "widthMm": sw,
                "heightMm": sh,
                "areaM2": sw * sh / 1e6,
                "active": name == cur,
            }
        )
    return result(
        summary={
            "activeSheet": cur,
            "orientation": values["orientation"],
            "sheetOptions": len(rows),
        },
        tables=[
            table(
                "Standard drawing sheets",
                [
                    ("sheet", "Sheet"),
                    ("widthMm", "Width", "mm"),
                    ("heightMm", "Height", "mm"),
                    ("areaM2", "Area", "m²"),
                    ("active", "Active"),
                ],
                rows,
            )
        ],
        notes=["Active sheet size is read from project settings drawings.sheetSize."],
    )


@feature(
    "settingsDrawings.titleBlocks",
    "Title Blocks",
    part="settings",
    fields=[],
    requires_project=False,
)
def title_blocks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect title block metadata fields populated from project info and drawings settings."""
    st = load_settings(ctx)
    d = st.drawings
    p = st.project
    rows = [
        {"field": "Project Name", "value": p.name},
        {"field": "Project Number", "value": d.projectNumber or p.number or "-"},
        {"field": "Client", "value": p.client or "-"},
        {"field": "Consulting Firm", "value": d.firm or "-"},
        {"field": "Engineer", "value": d.engineer or p.engineer or "-"},
        {
            "field": "Drawn / Checked / Approved",
            "value": f"{d.drawnBy or '-'} / {d.checkedBy or '-'} / {d.approvedBy or '-'}",
        },
        {"field": "Issue Status", "value": d.status},
    ]
    return result(
        summary={"status": d.status, "firm": d.firm or "-", "revisionCount": len(d.revisions)},
        tables=[table("Title block field mapping", [("field", "Field"), ("value", "Value")], rows)],
        notes=["Title block fields inherit from Project Info when left blank in Drawings."],
    )


@feature(
    "settingsDrawings.viewScales",
    "View Scales",
    part="settings",
    fields=[
        number("buildingLengthM", "Longest building plan dimension", 36.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def view_scales(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check whether building plan fits on the active sheet at configured drawing scales."""
    st = load_settings(ctx)
    d = st.drawings
    sheet_w, _ = _SHEET_MM.get(d.sheetSize, (841.0, 594.0))
    usable_w = sheet_w - 160.0  # title block + margins
    plan_mm_on_sheet = (values["buildingLengthM"] * 1000.0) / d.planScale
    fits = plan_mm_on_sheet <= usable_w
    rows = [
        {
            "view": "Foundation & framing plans",
            "scale": f"1:{d.planScale}",
            "options": ", ".join(f"1:{s}" for s in PLAN_SCALES),
        },
        {"view": "Slab reinforcement plans", "scale": f"1:{d.slabScale}", "options": "-"},
        {"view": "Beam & wall elevations", "scale": f"1:{d.elevationScale}", "options": "-"},
        {
            "view": "Member & footing details",
            "scale": f"1:{d.detailScale}",
            "options": ", ".join(f"1:{s}" for s in DETAIL_SCALES),
        },
    ]
    return result(
        summary={
            "planScale": d.planScale,
            "slabScale": d.slabScale,
            "detailScale": d.detailScale,
            "planFitsOnSheet": fits,
        },
        tables=[
            table(
                "Configured view scales",
                [("view", "View type"), ("scale", "Scale"), ("options", "Available scales")],
                rows,
            )
        ],
        notes=[
            f"At 1:{d.planScale}, {values['buildingLengthM']:g} m draws as {plan_mm_on_sheet:.0f} mm (usable width {usable_w:.0f} mm)."
        ],
    )


@feature(
    "settingsDrawings.northArrow",
    "North Arrow",
    part="settings",
    fields=[
        number(
            "trueNorthRotationDeg",
            "Plan rotation from true north (CCW)",
            15.0,
            unit="°",
            min=-180.0,
            max=180.0,
        ),
        select(
            "arrowStyle",
            "North symbol style",
            [
                ("compass", "Compass rose"),
                ("minimal", "Minimal pointer"),
                ("grid", "True/Project north dual"),
            ],
            "grid",
        ),
    ],
    requires_project=False,
)
def north_arrow(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute true-north vs project-north azimuth vector for plan orientation symbols."""
    ang = math.radians(values["trueNorthRotationDeg"])
    return result(
        summary={
            "rotationDeg": values["trueNorthRotationDeg"],
            "style": values["arrowStyle"],
            "dx": -math.sin(ang),
            "dy": math.cos(ang),
        },
        tables=[
            table(
                "North arrow orientation",
                [("parameter", "Parameter"), ("value", "Value")],
                [
                    {"parameter": "Rotation angle [°]", "value": values["trueNorthRotationDeg"]},
                    {"parameter": "Unit vector X", "value": -math.sin(ang)},
                    {"parameter": "Unit vector Y", "value": math.cos(ang)},
                ],
            )
        ],
        notes=["Unit vector points toward true north in plan coordinates."],
    )


@feature(
    "settingsDrawings.dimensionStyle",
    "Dimension Style",
    part="settings",
    fields=[
        number("textHeightMm", "Plotted dimension text height", 2.5, unit="mm", min=1.5, max=6.0),
        number("arrowSizeMm", "Plotted tick / arrow size", 2.0, unit="mm", min=1.0, max=5.0),
    ],
    requires_project=False,
)
def dimension_style(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute model-space dimension text and arrow sizes from plotted paper sizes and plan scale."""
    st = load_settings(ctx)
    scale = st.drawings.planScale
    arrows = st.drawings.standard.arrows
    return result(
        summary={
            "arrowStyle": arrows,
            "paperTextMm": values["textHeightMm"],
            "modelTextMm": values["textHeightMm"] * scale,
        },
        tables=[
            table(
                "Dimension style scaling",
                [("item", "Property"), ("paperMm", "Paper", "mm"), ("modelMm", "Model", "mm")],
                [
                    {
                        "item": "Text height",
                        "paperMm": values["textHeightMm"],
                        "modelMm": values["textHeightMm"] * scale,
                    },
                    {
                        "item": "Arrow / tick size",
                        "paperMm": values["arrowSizeMm"],
                        "modelMm": values["arrowSizeMm"] * scale,
                    },
                ],
            )
        ],
        notes=[f"Scaled for plan scale 1:{scale} using arrow style '{arrows}'."],
    )


@feature(
    "settingsDrawings.textStyles",
    "Text Styles",
    part="settings",
    fields=[
        number(
            "noteHeightMm", "General note text height (paper)", 2.5, unit="mm", min=1.5, max=6.0
        ),
        number("headingHeightMm", "Title text height (paper)", 5.0, unit="mm", min=3.0, max=12.0),
    ],
    requires_project=False,
)
def text_styles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure plotted CAD font and scale-dependent model text heights."""
    st = load_settings(ctx)
    font = st.drawings.standard.font
    scale = st.drawings.planScale
    rows = [
        {
            "role": "General notes & callouts",
            "font": font,
            "paperMm": values["noteHeightMm"],
            "modelMm": values["noteHeightMm"] * scale,
        },
        {
            "role": "View titles & headings",
            "font": font,
            "paperMm": values["headingHeightMm"],
            "modelMm": values["headingHeightMm"] * scale,
        },
    ]
    return result(
        summary={"font": font, "planScale": scale, "noteHeightMm": values["noteHeightMm"]},
        tables=[
            table(
                "Drawing text styles",
                [
                    ("role", "Role"),
                    ("font", "Font"),
                    ("paperMm", "Paper", "mm"),
                    ("modelMm", "Model", "mm"),
                ],
                rows,
            )
        ],
        notes=["Font family comes from drawings.standard.font."],
    )


@feature(
    "settingsDrawings.labelStyles",
    "Label Styles",
    part="settings",
    fields=[
        number(
            "leaderLandingMm", "Leader landing length (paper)", 4.0, unit="mm", min=2.0, max=12.0
        ),
        select(
            "frameShape",
            "Tag enclosure shape",
            [
                ("none", "Plain text"),
                ("box", "Rectangular box"),
                ("hex", "Hexagon"),
                ("circle", "Circle bubble"),
            ],
            "box",
        ),
    ],
    requires_project=False,
)
def label_styles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure member tag leader landing and callout enclosure style."""
    scale = load_settings(ctx).drawings.planScale
    return result(
        summary={
            "frameShape": values["frameShape"],
            "paperLandingMm": values["leaderLandingMm"],
            "modelLandingMm": values["leaderLandingMm"] * scale,
        },
        tables=[
            table(
                "Tag & leader style",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Frame shape", "value": values["frameShape"]},
                    {
                        "property": "Model landing [mm]",
                        "value": str(values["leaderLandingMm"] * scale),
                    },
                ],
            )
        ],
        notes=["Applies to beam, column, slab, and footing plan tags."],
    )


@feature(
    "settingsDrawings.reportSettings",
    "Report Settings",
    part="settings",
    fields=[],
    requires_project=False,
)
def report_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect active engineering report template and appendix element selection settings."""
    st = load_settings(ctx)
    rep = st.report
    rows = [
        {"setting": "Report template", "value": rep.template},
        {"setting": "Appendix detail", "value": rep.appendix},
        {"setting": "Report language", "value": st.project.language},
        {"setting": "Display unit system", "value": st.units.system},
    ]
    return result(
        summary={
            "template": rep.template,
            "appendix": rep.appendix,
            "language": st.project.language,
        },
        tables=[
            table("Report generation settings", [("setting", "Setting"), ("value", "Value")], rows)
        ],
        notes=["Configured via project settings report.template and report.appendix."],
    )


@feature(
    "settingsDrawings.logoHeader",
    "Logo & Header",
    part="settings",
    fields=[
        text("headerLine", "Custom letterhead line (blank = settings officeLine)", ""),
    ],
    requires_project=False,
)
def logo_header(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview practice letterhead, office address line, and disclaimer text for sheets/reports."""
    st = load_settings(ctx)
    std = st.drawings.standard
    office = values["headerLine"].strip() or std.officeLine or "(not set)"
    rows = [
        {"field": "Firm name", "value": st.drawings.firm or "(not set)"},
        {"field": "Office address line", "value": office},
        {"field": "Disclaimer", "value": std.disclaimer or "Do not scale from drawings."},
    ]
    return result(
        summary={"firmSet": bool(st.drawings.firm), "officeLine": office},
        tables=[
            table("Header & title block branding", [("field", "Field"), ("value", "Text")], rows)
        ],
        notes=["Printed in title blocks and calculation report covers."],
    )


@feature(
    "settingsDrawings.pageNumbering",
    "Page Numbering",
    part="settings",
    fields=[
        select(
            "scheme",
            "Page numbering style",
            [
                ("continuous", "Continuous (1, 2, 3...)"),
                ("chapter", "Chapter-prefixed (S1-1, S1-2...)"),
                ("sheetTotal", "Sheet X of Y"),
            ],
            "sheetTotal",
        ),
        number("estimatedPages", "Estimated document page count", 48.0, min=1.0),
    ],
    requires_project=False,
)
def page_numbering(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview report and drawing set page numbering conventions."""
    n = int(values["estimatedPages"])
    samples = {
        "continuous": f"Page 1 .. Page {n}",
        "chapter": f"S1-1 .. S4-{max(1, n // 4)}",
        "sheetTotal": f"Page 1 of {n}",
    }
    return result(
        summary={
            "scheme": values["scheme"],
            "estimatedPages": n,
            "example": samples[values["scheme"]],
        },
        tables=[
            table(
                "Page numbering scheme",
                [("scheme", "Scheme"), ("example", "Preview")],
                [{"scheme": values["scheme"], "example": samples[values["scheme"]]}],
            )
        ],
        notes=["Applies across multi-section structural calculation reports."],
    )


@feature(
    "settingsDrawings.pdfPresets",
    "PDF Presets",
    part="settings",
    fields=[
        select(
            "preset",
            "PDF plot preset",
            [
                ("vectorReview", "Vector Review (300 DPI, layers off)"),
                ("recordIssue", "Record Issue (600 DPI, PDF/A, layers on)"),
                ("compactEmail", "Compact Email (150 DPI, monochrome)"),
            ],
            "recordIssue",
        ),
    ],
    requires_project=False,
)
def pdf_presets(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review PDF export presets for resolution, layer retention, and archival compliance."""
    presets = {
        "vectorReview": (300, False, True, "Color"),
        "recordIssue": (600, True, True, "Monochrome"),
        "compactEmail": (150, False, False, "Monochrome"),
    }
    dpi, layers, embed, color = presets[values["preset"]]
    return result(
        summary={
            "preset": values["preset"],
            "dpi": dpi,
            "includeLayers": layers,
            "embedFonts": embed,
        },
        tables=[
            table(
                "PDF plot preset",
                [("property", "Property"), ("value", "Setting")],
                [
                    {"property": "Raster DPI", "value": str(dpi)},
                    {"property": "CAD Layers", "value": str(layers)},
                    {"property": "Embed Fonts", "value": str(embed)},
                    {"property": "Color Mode", "value": color},
                ],
            )
        ],
        notes=["Controls vector PDF output fidelity and file size."],
    )


@feature(
    "settingsDrawings.printSetup",
    "Print Setup",
    part="settings",
    fields=[
        number("marginMm", "Plot margin around border", 10.0, unit="mm", min=0.0, max=30.0),
        checkbox("fitToPage", "Scale to fit printable area", False),
    ],
    requires_project=False,
)
def print_setup(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute printable drawing area for the active project sheet size and plotter margins."""
    st = load_settings(ctx)
    w, h = _SHEET_MM.get(st.drawings.sheetSize, (841.0, 594.0))
    m = values["marginMm"]
    pw, ph = max(50.0, w - 2.0 * m), max(50.0, h - 2.0 * m)
    return result(
        summary={
            "sheetSize": st.drawings.sheetSize,
            "printableWidthMm": pw,
            "printableHeightMm": ph,
            "trueScale": not values["fitToPage"],
        },
        tables=[
            table(
                "Plotter paper setup",
                [
                    ("dimension", "Dimension"),
                    ("grossMm", "Sheet", "mm"),
                    ("printableMm", "Printable", "mm"),
                ],
                [
                    {"dimension": "Width", "grossMm": w, "printableMm": pw},
                    {"dimension": "Height", "grossMm": h, "printableMm": ph},
                ],
            )
        ],
        notes=["True-scale plotting disables fit-to-page scaling."],
    )


@feature(
    "settingsDrawings.batchPlot",
    "Batch Plot",
    part="settings",
    fields=[
        number("floorLevels", "Number of framing floor levels", 5.0, min=1.0),
    ],
    requires_project=False,
)
def batch_plot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Queue standard structural drawing sheets for a batch plot run."""
    st = load_settings(ctx)
    pfx = st.drawings.standard.structuralPrefix
    n_floors = int(values["floorLevels"])
    sheets = [
        {"sheetNo": f"{pfx}001", "title": "General Notes & Design Criteria"},
        {"sheetNo": f"{pfx}101", "title": "Foundation Plan & Schedules"},
    ] + [
        {"sheetNo": f"{pfx}{200 + i}", "title": f"Level {i} Framing & Slab Plan"}
        for i in range(1, n_floors + 1)
    ]
    sheets.append({"sheetNo": f"{pfx}301", "title": "Column & Beam Schedules & Details"})
    return result(
        summary={"queuedSheets": len(sheets), "sheetSize": st.drawings.sheetSize},
        tables=[
            table(
                "Batch plot sheet queue",
                [("sheetNo", "Sheet No"), ("title", "Sheet Title")],
                sheets,
            )
        ],
        notes=["Uses structuralPrefix and scopeBoxes from project drawings settings."],
    )


@feature(
    "settingsDrawings.viewTemplates",
    "View Templates",
    part="settings",
    fields=[
        select(
            "templateKind",
            "View template kind",
            [
                ("framing", "Structural Framing Plan"),
                ("rebar", "Slab Reinforcement Plan"),
                ("foundation", "Foundation Layout"),
                ("section", "Detail Section"),
            ],
            "framing",
        ),
    ],
    requires_project=False,
)
def view_templates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect standard view template scale and layer visibility rules."""
    st = load_settings(ctx)
    d = st.drawings
    scales = {
        "framing": d.planScale,
        "rebar": d.slabScale,
        "foundation": d.planScale,
        "section": d.detailScale,
    }
    vis = {
        "framing": ["S-GRID", "S-COLS", "S-BEAM", "S-WALL", "S-ANNO"],
        "rebar": ["S-GRID", "S-SLAB", "S-REBAR", "S-DIM"],
        "foundation": ["S-GRID", "S-FNDN", "S-COLS", "S-DIM"],
        "section": ["S-CONC", "S-REBAR", "S-HATCH", "S-DIM"],
    }
    rows = [
        {"layer": lyr, "visible": True, "scale": f"1:{scales[values['templateKind']]}"}
        for lyr in vis[values["templateKind"]]
    ]
    return result(
        summary={
            "template": values["templateKind"],
            "scale": scales[values["templateKind"]],
            "visibleLayers": len(rows),
        },
        tables=[
            table(
                "View template layer rules",
                [("layer", "Layer"), ("visible", "Visible"), ("scale", "Scale")],
                rows,
            )
        ],
        notes=["Ensures consistent visibility and scale across generated plans and details."],
    )


@feature(
    "settingsDrawings.sheetIndex",
    "Sheet Index",
    part="settings",
    fields=[
        checkbox("writeCsv", "Export sheet index CSV to project exports", False),
    ],
    requires_project=False,
)
def sheet_index(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate an automatic drawing sheet index with active revision and issue status."""
    st = load_settings(ctx)
    pfx = st.drawings.standard.structuralPrefix
    rev = st.drawings.revisions[-1].code if st.drawings.revisions else "0"
    rows = [
        {
            "sheet": f"{pfx}001",
            "title": "General Structural Notes",
            "rev": rev,
            "status": st.drawings.status,
        },
        {
            "sheet": f"{pfx}101",
            "title": "Foundation Layout & Details",
            "rev": rev,
            "status": st.drawings.status,
        },
        {
            "sheet": f"{pfx}201",
            "title": "Typical Floor Framing Plan",
            "rev": rev,
            "status": st.drawings.status,
        },
        {
            "sheet": f"{pfx}301",
            "title": "Beam & Column Reinforcement Schedules",
            "rev": rev,
            "status": st.drawings.status,
        },
    ]
    out_path = None
    if values["writeCsv"] and ctx.root is not None:
        csv_lines = [
            "sheet,title,rev,status",
            *(f"{r['sheet']},{r['title']},{r['rev']},{r['status']}" for r in rows),
        ]
        out_path = export_file(ctx, "sheet-index.csv", "\n".join(csv_lines) + "\n")
    return result(
        summary={"sheetCount": len(rows), "currentRev": rev, "exported": out_path is not None},
        tables=[
            table(
                "Drawing sheet index",
                [("sheet", "Sheet"), ("title", "Title"), ("rev", "Rev"), ("status", "Status")],
                rows,
            )
        ],
        notes=[
            f"Written to {out_path}"
            if out_path
            else "Revision code pulled from latest drawings.revisions entry."
        ],
    )


@feature(
    "settingsDrawings.drawingRegister",
    "Drawing Register",
    part="settings",
    fields=[
        checkbox("exportJson", "Save drawing register JSON to exports", False),
    ],
    requires_project=False,
)
def drawing_register(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compile a transmittal drawing register including discipline prefixes and scope boxes."""
    st = load_settings(ctx)
    d = st.drawings
    reg = {
        "project": st.project.name,
        "status": d.status,
        "sheetSize": d.sheetSize,
        "scopeBoxes": [sb.name for sb in d.scopeBoxes],
        "revisions": [r.model_dump(mode="json") for r in d.revisions],
    }
    out_path = None
    if values["exportJson"] and ctx.root is not None:
        out_path = export_file(ctx, "drawing-register.json", json_dumps_clean(reg))
    rows = [{"field": k, "value": str(v)} for k, v in reg.items()]
    return result(
        summary={
            "scopeBoxes": len(d.scopeBoxes),
            "revisions": len(d.revisions),
            "exported": out_path is not None,
        },
        tables=[table("Drawing register summary", [("field", "Field"), ("value", "Value")], rows)],
        notes=[
            f"Exported to {out_path}"
            if out_path
            else "Tracks issued sheet metadata and dependent scope boxes."
        ],
    )


@feature(
    "settingsDrawings.calloutDefaults",
    "Callout Defaults",
    part="settings",
    fields=[
        number(
            "bubbleDiameterMm",
            "Section callout bubble diameter (paper)",
            10.0,
            unit="mm",
            min=6.0,
            max=20.0,
        ),
    ],
    requires_project=False,
)
def callout_defaults(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure section and detail callout bubble size and sheet reference format."""
    st = load_settings(ctx)
    scale = st.drawings.planScale
    return result(
        summary={
            "paperBubbleMm": values["bubbleDiameterMm"],
            "modelBubbleMm": values["bubbleDiameterMm"] * scale,
        },
        tables=[
            table(
                "Callout symbol defaults",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Paper bubble diameter [mm]", "value": values["bubbleDiameterMm"]},
                    {
                        "property": "Model bubble diameter [mm]",
                        "value": values["bubbleDiameterMm"] * scale,
                    },
                    {"property": "Reference format", "value": "<DetailNo>/<SheetNo>"},
                ],
            )
        ],
        notes=["Standardizes cross-sheet detail and section callout bubbles."],
    )


@feature(
    "settingsDrawings.revisionClouds",
    "Revision Clouds",
    part="settings",
    fields=[
        number(
            "arcChordMm",
            "Revision cloud arc chord length (paper)",
            6.0,
            unit="mm",
            min=2.0,
            max=15.0,
        ),
    ],
    requires_project=False,
)
def revision_clouds(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute scale-adjusted revision cloud arc chord lengths for plans and details."""
    st = load_settings(ctx)
    return result(
        summary={
            "paperArcMm": values["arcChordMm"],
            "planModelArcMm": values["arcChordMm"] * st.drawings.planScale,
            "detailModelArcMm": values["arcChordMm"] * st.drawings.detailScale,
        },
        tables=[
            table(
                "Revision cloud arc sizing",
                [("scale", "View scale"), ("modelArcMm", "Model arc chord", "mm")],
                [
                    {
                        "scale": f"1:{st.drawings.planScale}",
                        "modelArcMm": values["arcChordMm"] * st.drawings.planScale,
                    },
                    {
                        "scale": f"1:{st.drawings.detailScale}",
                        "modelArcMm": values["arcChordMm"] * st.drawings.detailScale,
                    },
                ],
            )
        ],
        notes=["Maintains uniform plotted cloud appearance across differing view scales."],
    )


@feature(
    "settingsDrawings.matchLines",
    "Match Lines",
    part="settings",
    fields=[
        number(
            "overlapMm", "Dependent sheet overlap margin", 1500.0, unit="mm", min=0.0, max=5000.0
        ),
    ],
    requires_project=False,
)
def match_lines(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect configured dependent scope boxes and matchline overlap boundaries."""
    st = load_settings(ctx)
    sbs = st.drawings.scopeBoxes
    rows = [
        {
            "name": sb.name,
            "widthM": (sb.bounds[2] - sb.bounds[0]) / 1000.0,
            "heightM": (sb.bounds[3] - sb.bounds[1]) / 1000.0,
            "levels": ", ".join(sb.levels) or "all",
        }
        for sb in sbs
    ]
    return result(
        summary={"scopeBoxCount": len(sbs), "overlapMm": values["overlapMm"]},
        tables=[
            table(
                "Scope box matchline layout",
                [
                    ("name", "Scope box"),
                    ("widthM", "Width", "m"),
                    ("heightM", "Height", "m"),
                    ("levels", "Levels"),
                ],
                rows
                or [{"name": "(single sheet)", "widthM": 0.0, "heightM": 0.0, "levels": "all"}],
            )
        ],
        notes=["Scope boxes split oversized floor plans into dependent sheets with matchlines."],
    )


@feature(
    "settingsDrawings.lineWeights",
    "Line Weights",
    part="settings",
    fields=[],
    requires_project=False,
)
def line_weights(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display ISO standard plotted pen lineweights available in drafting settings."""
    rows = [
        {
            "index": i + 1,
            "lineweightMm": lw,
            "role": "Thin/grid" if lw <= 0.18 else ("Medium/object" if lw <= 0.35 else "Heavy/cut"),
        }
        for i, lw in enumerate(LINEWEIGHTS)
    ]
    return result(
        summary={
            "weightCount": len(rows),
            "minWeightMm": LINEWEIGHTS[0],
            "maxWeightMm": LINEWEIGHTS[-1],
        },
        tables=[
            table(
                "Plotted lineweight table",
                [("index", "#"), ("lineweightMm", "Lineweight", "mm"), ("role", "Typical use")],
                rows,
            )
        ],
        notes=["Standard ISO lineweights supported by DraftingStandard.layers."],
    )


@feature(
    "settingsDrawings.hatchPatterns",
    "Hatch Patterns",
    part="settings",
    fields=[],
    requires_project=False,
)
def hatch_patterns(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List standard structural material section hatch patterns and DXF defaults."""
    rows = [
        {"material": "Cast-in-place concrete", "pattern": "AR-CONC", "scale": 1.0, "angleDeg": 0.0},
        {
            "material": "Structural steel section",
            "pattern": "ANSI31",
            "scale": 1.0,
            "angleDeg": 45.0,
        },
        {"material": "Masonry / brick wall", "pattern": "ANSI32", "scale": 1.0, "angleDeg": 45.0},
        {"material": "Compacted soil / earth", "pattern": "EARTH", "scale": 1.0, "angleDeg": 0.0},
    ]
    return result(
        summary={"patternCount": len(rows)},
        tables=[
            table(
                "Material hatch standards",
                [
                    ("material", "Material"),
                    ("pattern", "Pattern"),
                    ("scale", "Scale"),
                    ("angleDeg", "Angle", "°"),
                ],
                rows,
            )
        ],
        notes=["Applied to section cuts and foundation details during DXF export."],
    )


@feature(
    "settingsDrawings.symbolLibrary",
    "Symbol Library",
    part="settings",
    fields=[],
    requires_project=False,
)
def symbol_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Catalogue shared structural drafting symbols and fabrication weld symbol convention."""
    st = load_settings(ctx)
    rows = [
        {"symbol": "Section cut marker", "category": "Annotation"},
        {"symbol": "Level elevation datum", "category": "Annotation"},
        {"symbol": "Grid bubble", "category": "Grid"},
        {
            "symbol": "Weld symbol",
            "category": f"Fabrication ({st.drawings.fabrication.weldSymbols})",
        },
        {"symbol": "Moment/pinned end connection", "category": "Framing"},
    ]
    return result(
        summary={"symbolCount": len(rows), "weldStandard": st.drawings.fabrication.weldSymbols},
        tables=[
            table("Standard symbol library", [("symbol", "Symbol"), ("category", "Category")], rows)
        ],
        notes=["Weld symbol convention follows drawings.fabrication.weldSymbols."],
    )


@feature(
    "settingsDrawings.abbreviationList",
    "Abbreviation List",
    part="settings",
    fields=[],
    requires_project=False,
)
def abbreviation_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List standard structural engineering drawing abbreviations for general notes sheets."""
    abbrs = [
        ("B", "Beam"),
        ("C", "Column"),
        ("S", "Slab"),
        ("SW", "Shear Wall"),
        ("F", "Footing"),
        ("TOC", "Top of Concrete"),
        ("SSL", "Structural Slab Level"),
        ("CLR", "Clear Cover"),
        ("EF", "Each Face"),
        ("EW", "Each Way"),
        ("CJ", "Construction Joint"),
        ("EJ", "Expansion Joint"),
    ]
    rows = [{"abbr": a, "meaning": m} for a, m in abbrs]
    return result(
        summary={"abbreviationCount": len(rows)},
        tables=[
            table(
                "Standard drawing abbreviations",
                [("abbr", "Abbreviation"), ("meaning", "Meaning")],
                rows,
            )
        ],
        notes=["Printed in the legend block of the General Structural Notes sheet."],
    )
