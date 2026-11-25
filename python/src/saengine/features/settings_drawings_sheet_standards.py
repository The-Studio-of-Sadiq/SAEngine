"""Project Settings - Drawings: Sheet Standards tab: sheet sizes, title blocks, revisions, grids, viewports."""

from __future__ import annotations

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
from saengine.features.settings_common import load_settings

_SHEETS = {
    "A0": (1189.0, 841.0),
    "A1": (841.0, 594.0),
    "A2": (594.0, 420.0),
    "A3": (420.0, 297.0),
    "ANSI D": (863.6, 558.8),
    "ARCH D": (914.4, 609.6),
}


@feature(
    "settingsDrawingsSheetStandards.sheetSize",
    "Sheet Size",
    part="settings",
    fields=[
        select(
            "sheet",
            "Target sheet standard",
            [
                ("A0", "ISO A0"),
                ("A1", "ISO A1"),
                ("A2", "ISO A2"),
                ("A3", "ISO A3"),
                ("ANSI D", "ANSI D"),
                ("ARCH D", "ARCH D"),
            ],
            "A1",
        ),
    ],
    requires_project=False,
)
def sheet_size(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect sheet dimensions and compare with active project sheetSize."""
    st = load_settings(ctx)
    w, h = _SHEETS[values["sheet"]]
    return result(
        summary={
            "projectSheet": st.drawings.sheetSize,
            "selectedSheet": values["sheet"],
            "widthMm": w,
            "heightMm": h,
        },
        tables=[
            table(
                "Sheet dimensions",
                [("sheet", "Sheet"), ("widthMm", "Width", "mm"), ("heightMm", "Height", "mm")],
                [{"sheet": values["sheet"], "widthMm": w, "heightMm": h}],
            )
        ],
        notes=["Active sheet standard is saved in drawings.sheetSize."],
    )


@feature(
    "settingsDrawingsSheetStandards.sheetBorder",
    "Sheet Border",
    part="settings",
    fields=[
        number("borderWeightMm", "Outer border lineweight", 0.50, unit="mm", min=0.18, max=1.4),
        checkbox("doubleFrame", "Draw double-line architectural border", True),
    ],
    requires_project=False,
)
def sheet_border(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure sheet frame border lineweight and single/double frame style."""
    return result(
        summary={"borderWeightMm": values["borderWeightMm"], "doubleFrame": values["doubleFrame"]},
        tables=[
            table(
                "Sheet border standard",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Border lineweight [mm]", "value": str(values["borderWeightMm"])},
                    {"property": "Double frame", "value": str(values["doubleFrame"])},
                ],
            )
        ],
        notes=["Applied to generated DXF and PDF sheet templates."],
    )


@feature(
    "settingsDrawingsSheetStandards.sheetMargin",
    "Sheet Margin",
    part="settings",
    fields=[
        number("bindingMarginMm", "Left binding margin", 20.0, unit="mm", min=5.0, max=40.0),
        number("otherMarginMm", "Top/right/bottom margin", 10.0, unit="mm", min=5.0, max=30.0),
    ],
    requires_project=False,
)
def sheet_margin(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute inner drawable frame dimensions after subtracting sheet margins."""
    st = load_settings(ctx)
    w, h = _SHEETS.get(st.drawings.sheetSize, (841.0, 594.0))
    iw = w - values["bindingMarginMm"] - values["otherMarginMm"]
    ih = h - 2.0 * values["otherMarginMm"]
    return result(
        summary={"sheetSize": st.drawings.sheetSize, "innerWidthMm": iw, "innerHeightMm": ih},
        tables=[
            table(
                "Sheet margin geometry",
                [("item", "Item"), ("mm", "Dimension", "mm")],
                [{"item": "Inner frame width", "mm": iw}, {"item": "Inner frame height", "mm": ih}],
            )
        ],
        notes=["20 mm left binding margin accommodates punched drawing sets."],
    )


@feature(
    "settingsDrawingsSheetStandards.applySheet",
    "Apply Sheet",
    part="settings",
    fields=[
        select(
            "sheet",
            "Sheet size to apply",
            [("A0", "A0"), ("A1", "A1"), ("A2", "A2"), ("A3", "A3"), ("ARCH D", "ARCH D")],
            "A1",
        ),
    ],
    requires_project=False,
)
def apply_sheet(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview applying sheet size standard across new structural drawing exports."""
    w, h = _SHEETS[values["sheet"]]
    return result(
        summary={"targetSheet": values["sheet"], "widthMm": w, "heightMm": h},
        tables=[
            table(
                "Sheet preset target",
                [("setting", "Setting"), ("value", "Value")],
                [
                    {"setting": "drawings.sheetSize", "value": values["sheet"]},
                    {"setting": "Dimensions", "value": f"{w} × {h} mm"},
                ],
            )
        ],
        notes=["Applies to foundation, framing, slab, and detail sheets."],
    )


@feature(
    "settingsDrawingsSheetStandards.titleBlock",
    "Title Block",
    part="settings",
    fields=[
        select(
            "layout",
            "Title block placement",
            [
                ("rightStrip", "Right vertical strip (130 mm)"),
                ("bottomBar", "Bottom horizontal strip (55 mm)"),
            ],
            "rightStrip",
        ),
    ],
    requires_project=False,
)
def title_block(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure title block geometry and read project title block metadata."""
    st = load_settings(ctx)
    return result(
        summary={
            "layout": values["layout"],
            "project": st.project.name,
            "status": st.drawings.status,
        },
        tables=[
            table(
                "Title block layout",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Placement", "value": values["layout"]},
                    {"field": "Consulting firm", "value": st.drawings.firm or "-"},
                    {
                        "field": "Engineer",
                        "value": st.drawings.engineer or st.project.engineer or "-",
                    },
                ],
            )
        ],
        notes=[
            "Right vertical strip keeps the lower-right corner visible when drawings are folded."
        ],
    )


@feature(
    "settingsDrawingsSheetStandards.scaleField",
    "Scale Field",
    part="settings",
    fields=[
        select(
            "displayMode",
            "Title block scale field mode",
            [("explicit", "Explicit (e.g. 1:100)"), ("asShown", "AS SHOWN (multi-scale sheets)")],
            "explicit",
        ),
    ],
    requires_project=False,
)
def scale_field(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Format the title block scale field based on active view scale settings."""
    st = load_settings(ctx)
    text_val = f"1:{st.drawings.planScale}" if values["displayMode"] == "explicit" else "AS SHOWN"
    return result(
        summary={"scaleFieldText": text_val, "planScale": st.drawings.planScale},
        tables=[
            table(
                "Scale field preview",
                [("mode", "Mode"), ("text", "Printed text")],
                [{"mode": values["displayMode"], "text": text_val}],
            )
        ],
        notes=["Multi-scale detail sheets use AS SHOWN with per-view scale labels."],
    )


@feature(
    "settingsDrawingsSheetStandards.companyLogo",
    "Company Logo",
    part="settings",
    fields=[
        number("logoWidthMm", "Logo box width on sheet", 45.0, unit="mm", min=15.0, max=120.0),
        number("logoHeightMm", "Logo box height on sheet", 18.0, unit="mm", min=8.0, max=60.0),
    ],
    requires_project=False,
)
def company_logo(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure title block logo bounding box dimensions and aspect ratio."""
    ar = values["logoWidthMm"] / values["logoHeightMm"]
    return result(
        summary={
            "widthMm": values["logoWidthMm"],
            "heightMm": values["logoHeightMm"],
            "aspectRatio": ar,
        },
        tables=[
            table(
                "Title block logo slot",
                [("dimension", "Dimension"), ("mm", "Value", "mm")],
                [
                    {"dimension": "Box width", "mm": values["logoWidthMm"]},
                    {"dimension": "Box height", "mm": values["logoHeightMm"]},
                ],
            )
        ],
        notes=["Images scale uniformly to fit inside the title block logo slot."],
    )


@feature(
    "settingsDrawingsSheetStandards.blockDefaults",
    "Block Defaults",
    part="settings",
    fields=[],
    requires_project=False,
)
def block_defaults(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Review default title block sign-off fields and disclaimer text."""
    st = load_settings(ctx)
    d = st.drawings
    rows = [
        {"field": "Drawn by", "value": d.drawnBy or "-"},
        {"field": "Checked by", "value": d.checkedBy or "-"},
        {"field": "Approved by", "value": d.approvedBy or "-"},
        {"field": "Issue status", "value": d.status},
        {"field": "Disclaimer", "value": d.standard.disclaimer or "Do not scale from drawings."},
    ]
    return result(
        summary={"status": d.status, "hasChecker": bool(d.checkedBy)},
        tables=[table("Title block defaults", [("field", "Field"), ("value", "Default")], rows)],
        notes=["Populated from drawings and drawings.standard."],
    )


@feature(
    "settingsDrawingsSheetStandards.revisionCloud",
    "Revision Cloud",
    part="settings",
    fields=[
        number("arcRadiusMm", "Cloud bulge arc radius (paper)", 3.5, unit="mm", min=1.5, max=10.0),
        number("lineweightMm", "Cloud lineweight", 0.35, unit="mm", min=0.18, max=0.70),
    ],
    requires_project=False,
)
def revision_cloud(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure revision cloud arc radius and plotted pen weight."""
    return result(
        summary={"arcRadiusMm": values["arcRadiusMm"], "lineweightMm": values["lineweightMm"]},
        tables=[
            table(
                "Revision cloud style",
                [("property", "Property"), ("mm", "Value", "mm")],
                [
                    {"property": "Paper arc radius", "mm": values["arcRadiusMm"]},
                    {"property": "Lineweight", "mm": values["lineweightMm"]},
                ],
            )
        ],
        notes=["Placed on S-REV layer with paired revision delta triangle."],
    )


@feature(
    "settingsDrawingsSheetStandards.revisionDelta",
    "Revision Delta",
    part="settings",
    fields=[
        select(
            "shape",
            "Delta symbol shape",
            [("triangle", "Equilateral triangle"), ("hexagon", "Hexagon"), ("circle", "Circle")],
            "triangle",
        ),
        number("sizeMm", "Symbol height (paper)", 6.0, unit="mm", min=3.0, max=12.0),
    ],
    requires_project=False,
)
def revision_delta(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure revision delta marker geometry and text height."""
    return result(
        summary={
            "shape": values["shape"],
            "sizeMm": values["sizeMm"],
            "textHeightMm": values["sizeMm"] * 0.45,
        },
        tables=[
            table(
                "Revision delta symbol",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Shape", "value": values["shape"]},
                    {"property": "Symbol height [mm]", "value": str(values["sizeMm"])},
                    {
                        "property": "Embedded text height [mm]",
                        "value": f"{values['sizeMm'] * 0.45:.2f}",
                    },
                ],
            )
        ],
        notes=["Displays active revision code adjacent to every revision cloud."],
    )


@feature(
    "settingsDrawingsSheetStandards.revisionTable",
    "Revision Table",
    part="settings",
    fields=[
        number("maxVisibleRows", "Max revision rows in title block", 6.0, min=3.0, max=15.0),
    ],
    requires_project=False,
)
def revision_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview formatted title block revision history table from project settings."""
    st = load_settings(ctx)
    cap = int(values["maxVisibleRows"])
    revs = st.drawings.revisions[-cap:]
    rows = [
        {
            "rev": r.code,
            "date": r.date or "-",
            "by": r.by or "-",
            "description": r.description or "-",
        }
        for r in revs
    ]
    return result(
        summary={"totalRevisions": len(st.drawings.revisions), "shownRows": len(rows)},
        tables=[
            table(
                "Title block revision table",
                [("rev", "Rev"), ("date", "Date"), ("by", "By"), ("description", "Description")],
                rows or [{"rev": "0", "date": "-", "by": "-", "description": "Initial issue"}],
            )
        ],
        notes=["Displays the most recent revisions up to maxVisibleRows."],
    )


@feature(
    "settingsDrawingsSheetStandards.revisionDefaults",
    "Revision Defaults",
    part="settings",
    fields=[
        text("initialCode", "Starting revision code", "0"),
        text("initialStatus", "Starting issue status", "FOR REVIEW"),
    ],
    requires_project=False,
)
def revision_defaults(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define starting revision code and default sheet issue status."""
    return result(
        summary={"initialCode": values["initialCode"], "initialStatus": values["initialStatus"]},
        tables=[
            table(
                "Default revision settings",
                [("field", "Field"), ("value", "Default")],
                [
                    {"field": "Initial revision code", "value": values["initialCode"]},
                    {"field": "Default status", "value": values["initialStatus"]},
                ],
            )
        ],
        notes=["Used when initializing a new drawing set."],
    )


@feature(
    "settingsDrawingsSheetStandards.drawingGrid",
    "Drawing Grid",
    part="settings",
    fields=[
        number("zoneCols", "Horizontal sheet zone divisions", 8.0, min=4.0, max=16.0),
        number("zoneRows", "Vertical sheet zone divisions", 6.0, min=2.0, max=12.0),
    ],
    requires_project=False,
)
def drawing_grid(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute border reference zone grid spacing (A-F / 1-8) for the active sheet."""
    st = load_settings(ctx)
    w, h = _SHEETS.get(st.drawings.sheetSize, (841.0, 594.0))
    return result(
        summary={
            "cols": int(values["zoneCols"]),
            "rows": int(values["zoneRows"]),
            "zoneWidthMm": w / values["zoneCols"],
            "zoneHeightMm": h / values["zoneRows"],
        },
        tables=[
            table(
                "Border zone grid",
                [("axis", "Axis"), ("divisions", "Count"), ("stepMm", "Step", "mm")],
                [
                    {
                        "axis": "Horizontal (1..N)",
                        "divisions": int(values["zoneCols"]),
                        "stepMm": w / values["zoneCols"],
                    },
                    {
                        "axis": "Vertical (A..Z)",
                        "divisions": int(values["zoneRows"]),
                        "stepMm": h / values["zoneRows"],
                    },
                ],
            )
        ],
        notes=["Alphanumeric border grid locates callouts and revisions across large sheets."],
    )


@feature(
    "settingsDrawingsSheetStandards.snapGrid",
    "Snap Grid",
    part="settings",
    fields=[
        number("snapStepMm", "Drafting snap interval (model)", 50.0, unit="mm", min=1.0, max=500.0),
        number(
            "majorGridStepMm", "Major visual grid interval", 500.0, unit="mm", min=50.0, max=5000.0
        ),
    ],
    requires_project=False,
)
def snap_grid(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure CAD drafting snap spacing and major visual grid ratio."""
    return result(
        summary={
            "snapStepMm": values["snapStepMm"],
            "majorStepMm": values["majorGridStepMm"],
            "minorPerMajor": values["majorGridStepMm"] / values["snapStepMm"],
        },
        tables=[
            table(
                "Drafting snap grid",
                [("item", "Item"), ("mm", "Spacing", "mm")],
                [
                    {"item": "Snap increment", "mm": values["snapStepMm"]},
                    {"item": "Major grid line", "mm": values["majorGridStepMm"]},
                ],
            )
        ],
        notes=["50 mm model snap aligns cleanly with standard concrete and masonry increments."],
    )


@feature(
    "settingsDrawingsSheetStandards.gridMargins",
    "Grid Margins",
    part="settings",
    fields=[
        number(
            "bubbleOffsetMm",
            "Grid bubble offset past building face",
            2500.0,
            unit="mm",
            min=500.0,
            max=10000.0,
        ),
        number("bubbleRadiusMm", "Grid bubble radius (paper)", 4.5, unit="mm", min=2.5, max=8.0),
    ],
    requires_project=False,
)
def grid_margins(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute structural grid bubble extension and paper-scaled radius."""
    scale = load_settings(ctx).drawings.planScale
    return result(
        summary={
            "bubbleOffsetMm": values["bubbleOffsetMm"],
            "modelBubbleRadiusMm": values["bubbleRadiusMm"] * scale,
        },
        tables=[
            table(
                "Structural grid bubble layout",
                [("parameter", "Parameter"), ("mm", "Value", "mm")],
                [
                    {"parameter": "Extension past framing", "mm": values["bubbleOffsetMm"]},
                    {"parameter": "Model bubble radius", "mm": values["bubbleRadiusMm"] * scale},
                ],
            )
        ],
        notes=[f"Scaled for plan scale 1:{scale}."],
    )


@feature(
    "settingsDrawingsSheetStandards.gridLegend",
    "Grid Legend",
    part="settings",
    fields=[],
    requires_project=False,
)
def grid_legend(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extract structural grid line coordinates from 05 Floor Plan for sheet grid legends."""
    fp = ctx.raw("floorPlan")
    grids = fp.get("grids", []) if isinstance(fp, dict) else []
    rows = [
        {
            "label": str(g.get("label", "-")),
            "axis": str(g.get("axis", "-")),
            "offsetMm": float(g.get("offset", 0.0)),
        }
        for g in grids
        if isinstance(g, dict)
    ]
    return result(
        summary={"gridCount": len(rows)},
        tables=[
            table(
                "Structural grid coordinate legend",
                [("label", "Grid"), ("axis", "Axis"), ("offsetMm", "Coordinate", "mm")],
                rows or [{"label": "-", "axis": "-", "offsetMm": 0.0}],
            )
        ],
        notes=["Extracted from 05 Floor Plan/floor-plan.json grids."],
    )


@feature(
    "settingsDrawingsSheetStandards.defaultScale",
    "Default Scale",
    part="settings",
    fields=[],
    requires_project=False,
)
def default_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report active default viewport scales across plans, slabs, elevations, and details."""
    d = load_settings(ctx).drawings
    rows = [
        {"viewport": "Plans", "scale": f"1:{d.planScale}"},
        {"viewport": "Slab plans", "scale": f"1:{d.slabScale}"},
        {"viewport": "Elevations", "scale": f"1:{d.elevationScale}"},
        {"viewport": "Details", "scale": f"1:{d.detailScale}"},
    ]
    return result(
        summary={
            "planScale": d.planScale,
            "slabScale": d.slabScale,
            "elevationScale": d.elevationScale,
            "detailScale": d.detailScale,
        },
        tables=[
            table("Default viewport scales", [("viewport", "Viewport"), ("scale", "Scale")], rows)
        ],
        notes=["Read from project drawings scale settings."],
    )


@feature(
    "settingsDrawingsSheetStandards.viewFrame",
    "View Frame",
    part="settings",
    fields=[
        number("paddingMm", "Viewport padding margin (paper)", 8.0, unit="mm", min=2.0, max=25.0),
        checkbox("visibleBorder", "Plot viewport frame border", False),
    ],
    requires_project=False,
)
def view_frame(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure viewport frame padding and non-plotting border visibility."""
    return result(
        summary={"paddingMm": values["paddingMm"], "plotFrame": values["visibleBorder"]},
        tables=[
            table(
                "Viewport frame settings",
                [("setting", "Setting"), ("value", "Value")],
                [
                    {"setting": "Frame padding [mm]", "value": str(values["paddingMm"])},
                    {"setting": "Plot border", "value": str(values["visibleBorder"])},
                ],
            )
        ],
        notes=[
            "Non-plotting viewport frames keep sheet layouts clean while preserving crop bounds."
        ],
    )


@feature(
    "settingsDrawingsSheetStandards.scopeBox",
    "Scope Box",
    part="settings",
    fields=[],
    requires_project=False,
)
def scope_box(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List dependent sheet scope boxes configured in project drawings settings."""
    sbs = load_settings(ctx).drawings.scopeBoxes
    rows = [
        {
            "name": sb.name,
            "x0Mm": sb.bounds[0],
            "y0Mm": sb.bounds[1],
            "x1Mm": sb.bounds[2],
            "y1Mm": sb.bounds[3],
        }
        for sb in sbs
    ]
    return result(
        summary={"scopeBoxCount": len(rows)},
        tables=[
            table(
                "Configured scope boxes",
                [
                    ("name", "Name"),
                    ("x0Mm", "X0", "mm"),
                    ("y0Mm", "Y0", "mm"),
                    ("x1Mm", "X1", "mm"),
                    ("y1Mm", "Y1", "mm"),
                ],
                rows
                or [{"name": "(none defined)", "x0Mm": 0.0, "y0Mm": 0.0, "x1Mm": 0.0, "y1Mm": 0.0}],
            )
        ],
        notes=["Scope boxes generate cropped dependent plan sheets with matchlines."],
    )


@feature(
    "settingsDrawingsSheetStandards.viewLabeling",
    "View Labeling",
    part="settings",
    fields=[
        text("titleFormat", "View title pattern", "{viewName} (Scale 1:{scale})"),
        number("underlineWeightMm", "Title underline weight", 0.50, unit="mm", min=0.18, max=1.0),
    ],
    requires_project=False,
)
def view_labeling(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview automatic viewport title text and underline lineweight."""
    st = load_settings(ctx)
    sample = (
        values["titleFormat"]
        .replace("{viewName}", "Level 2 Framing Plan")
        .replace("{scale}", str(st.drawings.planScale))
    )
    return result(
        summary={"sampleTitle": sample, "underlineWeightMm": values["underlineWeightMm"]},
        tables=[
            table(
                "View title labeling",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Formatted sample", "value": sample},
                    {"item": "Underline weight [mm]", "value": str(values["underlineWeightMm"])},
                ],
            )
        ],
        notes=["Standardizes view titles across all structural sheets."],
    )


@feature(
    "settingsDrawingsSheetStandards.keyPlan",
    "Key Plan",
    part="settings",
    fields=[
        number(
            "keyPlanWidthMm",
            "Key plan box width in title block",
            60.0,
            unit="mm",
            min=25.0,
            max=120.0,
        ),
        number("buildingSpanM", "Full building footprint span", 50.0, unit="m", min=5.0),
    ],
    requires_project=False,
)
def key_plan(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute key-plan reduction scale for multi-sheet scope-box location diagrams."""
    kp_scale = (values["buildingSpanM"] * 1000.0) / values["keyPlanWidthMm"]
    return result(
        summary={"keyPlanBoxWidthMm": values["keyPlanWidthMm"], "impliedKeyPlanScale": kp_scale},
        tables=[
            table(
                "Title block key plan sizing",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Key plan box width [mm]", "value": values["keyPlanWidthMm"]},
                    {"metric": "Key plan scale (1 : N)", "value": kp_scale},
                ],
            )
        ],
        notes=["Highlights the active scope box zone on multi-zone projects."],
    )
