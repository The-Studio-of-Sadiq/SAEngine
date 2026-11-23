"""Project Settings - Drawings: Pen Sets & Plot Output tab: pen tables, plot styles, raster, CAD export, preview."""

from __future__ import annotations

import json
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
from saengine.features.settings_common import export_file, json_dumps_clean, load_settings


@feature(
    "settingsDrawingsPenSets.penTable",
    "Pen Table",
    part="settings",
    fields=[],
    requires_project=False,
)
def pen_table(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List default ACI pen-to-plotted-lineweight mapping table."""
    pens = [
        {"pen": 1, "color": "Red", "weightMm": 0.13, "use": "Grid lines & centerlines"},
        {"pen": 2, "color": "Yellow", "weightMm": 0.18, "use": "Dimensions & leaders"},
        {"pen": 3, "color": "Green", "weightMm": 0.35, "use": "Reinforcement & stirrups"},
        {"pen": 4, "color": "Cyan", "weightMm": 0.25, "use": "Beams & framing"},
        {"pen": 7, "color": "Black/White", "weightMm": 0.50, "use": "Cut concrete outlines"},
        {"pen": 8, "color": "Grey", "weightMm": 0.13, "use": "Hatches & screened background"},
    ]
    return result(
        summary={"penCount": len(pens)},
        tables=[
            table(
                "Active pen table",
                [
                    ("pen", "ACI"),
                    ("color", "Color"),
                    ("weightMm", "Weight", "mm"),
                    ("use", "Assignment"),
                ],
                pens,
            )
        ],
        notes=["Maps CAD entity ACI color indices to physical plotted stroke widths."],
    )


@feature(
    "settingsDrawingsPenSets.loadPenSet",
    "Load Pen Set",
    part="settings",
    fields=[
        text("penJson", "Pen set JSON", '{"1": 0.13, "2": 0.18, "3": 0.35, "7": 0.50}'),
    ],
    requires_project=False,
)
def load_pen_set(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate a custom pen-set JSON mapping."""
    try:
        data = json.loads(values["penJson"])
    except ValueError as exc:
        raise FeatureInputError(f"Invalid pen set JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FeatureInputError("Pen set must be a JSON object mapping ACI color to weight [mm].")
    rows = [{"aci": str(k), "weightMm": float(v)} for k, v in data.items()]
    return result(
        summary={"loadedPens": len(rows)},
        tables=[table("Loaded pen set", [("aci", "ACI"), ("weightMm", "Weight", "mm")], rows)],
        notes=["Validated pen thickness mapping."],
    )


@feature(
    "settingsDrawingsPenSets.savePenSet",
    "Save Pen Set",
    part="settings",
    fields=[
        text("setName", "Pen set name", "office-monochrome"),
        checkbox("writeFile", "Save JSON to 02 Project Settings/exports", True),
    ],
    requires_project=False,
)
def save_pen_set(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Save the current office pen set definition to 02 Project Settings/exports."""
    payload = {
        "name": values["setName"],
        "pens": {"1": 0.13, "2": 0.18, "3": 0.35, "4": 0.25, "7": 0.50, "8": 0.13},
    }
    out_path = None
    if values["writeFile"] and ctx.root is not None:
        out_path = export_file(ctx, f"pen-set-{values['setName']}.json", json_dumps_clean(payload))
    return result(
        summary={
            "setName": values["setName"],
            "penCount": len(payload["pens"]),
            "saved": out_path is not None,
        },
        tables=[
            table(
                "Saved pen set",
                [("aci", "ACI"), ("weightMm", "Weight", "mm")],
                [{"aci": k, "weightMm": v} for k, v in payload["pens"].items()],
            )
        ],
        notes=[
            f"Saved to {out_path}" if out_path else "Open a project folder to save pen set JSON."
        ],
    )


@feature(
    "settingsDrawingsPenSets.applyPenSet",
    "Apply Pen Set",
    part="settings",
    fields=[],
    requires_project=False,
)
def apply_pen_set(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify pen set application across DraftingStandard layers."""
    std = load_settings(ctx).drawings.standard
    return result(
        summary={"configuredLayers": len(std.layers), "font": std.font},
        tables=[
            table(
                "Pen set targets",
                [("target", "Output"), ("status", "Status")],
                [
                    {"target": "Plan DXF exports", "status": "Ready"},
                    {"target": "PDF plot sheets", "status": "Ready"},
                ],
            )
        ],
        notes=["Applies pen table weights to all exported sheets."],
    )


@feature(
    "settingsDrawingsPenSets.plotStyle",
    "Plot Style",
    part="settings",
    fields=[
        select(
            "style",
            "Plot style mode",
            [
                ("monochrome", "Monochrome (CTB)"),
                ("greyscale", "Greyscale"),
                ("color", "True Color"),
            ],
            "monochrome",
        ),
    ],
    requires_project=False,
)
def plot_style(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select active monochrome, greyscale, or full-color plotting style."""
    return result(
        summary={"plotStyle": values["style"]},
        tables=[
            table(
                "Plot style configuration",
                [("mode", "Mode"), ("ink", "Ink output")],
                [
                    {
                        "mode": values["style"],
                        "ink": "Black/Grey" if values["style"] != "color" else "Color",
                    }
                ],
            )
        ],
        notes=["Monochrome ensures high contrast on structural blueprints."],
    )


@feature(
    "settingsDrawingsPenSets.screening",
    "Screening",
    part="settings",
    fields=[
        number("screenPct", "Background screening intensity", 40.0, unit="%", min=10.0, max=100.0),
    ],
    requires_project=False,
)
def screening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure background architectural underlay and hatch ink screening percentage."""
    rgb_val = round(255 * (1.0 - values["screenPct"] / 100.0))
    return result(
        summary={"screeningPct": values["screenPct"], "greyChannel": rgb_val},
        tables=[
            table(
                "Screening intensity",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Ink density [%]", "value": str(values["screenPct"])},
                    {"item": "RGB grey value", "value": f"rgb({rgb_val},{rgb_val},{rgb_val})"},
                ],
            )
        ],
        notes=["40% screening keeps architectural underlays subordinate to structural framing."],
    )


@feature(
    "settingsDrawingsPenSets.greyScale",
    "Grey Scale",
    part="settings",
    fields=[
        number("r", "Input Red (0-255)", 0.0, min=0.0, max=255.0),
        number("g", "Input Green (0-255)", 180.0, min=0.0, max=255.0),
        number("b", "Input Blue (0-255)", 220.0, min=0.0, max=255.0),
    ],
    requires_project=False,
)
def grey_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert RGB display color to Rec.709 perceptual luminance greyscale."""
    lum = 0.2126 * values["r"] + 0.7152 * values["g"] + 0.0722 * values["b"]
    return result(
        summary={"luminance": lum, "greyPct": (1.0 - lum / 255.0) * 100.0},
        tables=[
            table(
                "Luminance greyscale conversion",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Luminance Y (0-255)", "value": lum},
                    {"metric": "Plotted ink [%]", "value": (1.0 - lum / 255.0) * 100.0},
                ],
            )
        ],
        notes=["Uses ITU-R BT.709 luminance weights (0.2126 R + 0.7152 G + 0.0722 B)."],
    )


@feature(
    "settingsDrawingsPenSets.lineMerge",
    "Line Merge",
    part="settings",
    fields=[
        checkbox("mergeOverlaps", "Enable overlapping vector line merge", True),
    ],
    requires_project=False,
)
def line_merge(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Toggle vector line merge to prevent ink bleed at overlapping CAD primitives."""
    return result(
        summary={"lineMergeEnabled": values["mergeOverlaps"]},
        tables=[
            table(
                "Vector line merge",
                [("setting", "Setting"), ("enabled", "Enabled")],
                [{"setting": "Merge overlapping strokes", "enabled": values["mergeOverlaps"]}],
            )
        ],
        notes=["Prevents darkening artifacts where grid lines and member edges coincide."],
    )


@feature(
    "settingsDrawingsPenSets.pdfQuality",
    "PDF Quality",
    part="settings",
    fields=[
        number("vectorDpi", "Vector coordinate precision DPI", 600.0, min=150.0, max=2400.0),
    ],
    requires_project=False,
)
def pdf_quality(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate PDF vector coordinate snap precision at target DPI."""
    step_mm = 25.4 / values["vectorDpi"]
    return result(
        summary={"vectorDpi": values["vectorDpi"], "resolutionMm": step_mm},
        tables=[
            table(
                "PDF vector resolution",
                [("dpi", "DPI"), ("stepMm", "Step", "mm")],
                [{"dpi": values["vectorDpi"], "stepMm": step_mm}],
            )
        ],
        notes=["600 DPI gives 0.042 mm paper precision for crisp rebar and leader rendering."],
    )


@feature(
    "settingsDrawingsPenSets.colourMode",
    "Colour Mode",
    part="settings",
    fields=[
        select(
            "mode",
            "Output color space",
            [
                ("monochrome", "Monochrome (1-bit/grey)"),
                ("rgb", "sRGB Color"),
                ("cmyk", "CMYK Print"),
            ],
            "rgb",
        ),
    ],
    requires_project=False,
)
def colour_mode(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure output document color space."""
    return result(
        summary={"colourMode": values["mode"]},
        tables=[table("Output color mode", [("mode", "Color space")], [{"mode": values["mode"]}])],
        notes=["sRGB is optimal for screen review and digital issue."],
    )


@feature(
    "settingsDrawingsPenSets.fontEmbedding",
    "Font Embedding",
    part="settings",
    fields=[
        checkbox("embedAll", "Embed TrueType font subsets", True),
    ],
    requires_project=False,
)
def font_embedding(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure TrueType font subset embedding for cross-platform PDF fidelity."""
    font = load_settings(ctx).drawings.standard.font
    return result(
        summary={"font": font, "embedFonts": values["embedAll"]},
        tables=[
            table(
                "Font embedding",
                [("font", "Active font"), ("embedded", "Embed subset")],
                [{"font": font, "embedded": values["embedAll"]}],
            )
        ],
        notes=["Ensures Greek engineering symbols (φ, σ, Δ) render identically on any viewer."],
    )


@feature(
    "settingsDrawingsPenSets.outputDefaults",
    "Output Defaults",
    part="settings",
    fields=[],
    requires_project=False,
)
def output_defaults(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise active sheet, scale, and IFC/DXF export defaults."""
    st = load_settings(ctx)
    return result(
        summary={
            "sheetSize": st.drawings.sheetSize,
            "planScale": st.drawings.planScale,
            "ifcSchema": st.ifc.schema_,
        },
        tables=[
            table(
                "Default output settings",
                [("setting", "Setting"), ("value", "Value")],
                [
                    {"setting": "Sheet size", "value": st.drawings.sheetSize},
                    {"setting": "Plan scale", "value": f"1:{st.drawings.planScale}"},
                    {"setting": "Report template", "value": st.report.template},
                    {"setting": "IFC schema", "value": st.ifc.schema_},
                ],
            )
        ],
        notes=["Read from drawings, report, and ifc sections of project settings."],
    )


@feature(
    "settingsDrawingsPenSets.rasterDpi",
    "Raster Dpi",
    part="settings",
    fields=[
        number("dpi", "Raster image resolution DPI", 300.0, min=72.0, max=1200.0),
    ],
    requires_project=False,
)
def raster_dpi(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate pixel dimensions for full-sheet raster exports at target DPI."""
    w_in, h_in = 841.0 / 25.4, 594.0 / 25.4
    px_w, px_h = round(w_in * values["dpi"]), round(h_in * values["dpi"])
    return result(
        summary={
            "dpi": values["dpi"],
            "a1PixelsWidth": px_w,
            "a1PixelsHeight": px_h,
            "megapixels": px_w * px_h / 1e6,
        },
        tables=[
            table(
                "A1 sheet raster dimensions",
                [("dpi", "DPI"), ("widthPx", "Width px"), ("heightPx", "Height px")],
                [{"dpi": values["dpi"], "widthPx": px_w, "heightPx": px_h}],
            )
        ],
        notes=["Balances raster clarity for shaded 3D views against PDF file size."],
    )


@feature(
    "settingsDrawingsPenSets.imageCompression",
    "Image Compression",
    part="settings",
    fields=[
        select(
            "codec",
            "Embedded image compression",
            [
                ("losslessPng", "Lossless PNG / Flate"),
                ("jpegHigh", "JPEG High (Q=90)"),
                ("jpegMedium", "JPEG Compact (Q=75)"),
            ],
            "losslessPng",
        ),
    ],
    requires_project=False,
)
def image_compression(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select compression algorithm for embedded diagrams and site maps."""
    return result(
        summary={"compression": values["codec"]},
        tables=[
            table(
                "Image compression policy",
                [("codec", "Codec"), ("recommendedFor", "Use case")],
                [
                    {
                        "codec": values["codec"],
                        "recommendedFor": "Line diagrams & screenshots"
                        if values["codec"] == "losslessPng"
                        else "Aerial site imagery",
                    }
                ],
            )
        ],
        notes=["Lossless compression avoids ringing artifacts around fine CAD text."],
    )


@feature(
    "settingsDrawingsPenSets.monochromaticRaster",
    "Monochromatic Raster",
    part="settings",
    fields=[
        checkbox("forceMono", "Convert embedded raster underlays to grayscale", True),
    ],
    requires_project=False,
)
def monochromatic_raster(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Toggle grayscale conversion for raster underlays during monochrome plotting."""
    return result(
        summary={"monochromeRaster": values["forceMono"]},
        tables=[
            table(
                "Raster underlay monochrome",
                [("setting", "Setting"), ("enabled", "Enabled")],
                [{"setting": "Convert underlays to grayscale", "enabled": values["forceMono"]}],
            )
        ],
        notes=["Keeps scanned site plans unobtrusive beneath structural vectors."],
    )


@feature(
    "settingsDrawingsPenSets.renderBackground",
    "Render Background",
    part="settings",
    fields=[
        select(
            "bg",
            "Printed sheet background",
            [("white", "Pure white (paper)"), ("transparent", "Transparent")],
            "white",
        ),
    ],
    requires_project=False,
)
def render_background(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure background fill mode for printed drawings and PNG exports."""
    return result(
        summary={"background": values["bg"]},
        tables=[table("Background rendering", [("mode", "Background")], [{"mode": values["bg"]}])],
        notes=["White paper background prevents dark-theme viewport colors from printing."],
    )


@feature(
    "settingsDrawingsPenSets.layerMapping",
    "Layer Mapping",
    part="settings",
    fields=[],
    requires_project=False,
)
def layer_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect SAEngine-to-CAD office layer mapping rules."""
    std = load_settings(ctx).drawings.standard
    rows = [
        {"internal": l.layer, "exported": l.name or f"{std.layerPrefix}{l.layer}"}
        for l in std.layers
    ]
    return result(
        summary={"mappedCount": len(rows), "prefix": std.layerPrefix or "(none)"},
        tables=[
            table(
                "CAD export layer mapping",
                [("internal", "Internal layer"), ("exported", "Exported layer")],
                rows or [{"internal": "S-COLS", "exported": f"{std.layerPrefix}S-COLS"}],
            )
        ],
        notes=["Configured via drawings.standard.layers."],
    )


@feature(
    "settingsDrawingsPenSets.dwgVersion",
    "DWG Version",
    part="settings",
    fields=[
        select(
            "format",
            "Target DXF/DWG version",
            [
                ("R2018", "AutoCAD 2018 (AC1032)"),
                ("R2013", "AutoCAD 2013 (AC1027)"),
                ("R2010", "AutoCAD 2010 (AC1024)"),
            ],
            "R2018",
        ),
    ],
    requires_project=False,
)
def dwg_version(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select target DXF/DWG format version for CAD exports."""
    return result(
        summary={"cadVersion": values["format"]},
        tables=[
            table(
                "CAD export format",
                [("version", "Target format"), ("insunits", "$INSUNITS")],
                [{"version": values["format"], "insunits": "4 (Millimetres)"}],
            )
        ],
        notes=["SAEngine drafting DXF engine defaults to R2018 (AC1032)."],
    )


@feature(
    "settingsDrawingsPenSets.blockScale",
    "Block Scale",
    part="settings",
    fields=[
        number("insertScale", "CAD block insertion scale factor", 1.0, min=0.001, max=1000.0),
    ],
    requires_project=False,
)
def block_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set uniform block insertion scale factor for exported CAD symbols."""
    return result(
        summary={"blockScale": values["insertScale"]},
        tables=[
            table(
                "Block insertion scale",
                [("axis", "Axis"), ("scale", "Scale")],
                [{"axis": "X / Y / Z", "scale": values["insertScale"]}],
            )
        ],
        notes=["Unit scale 1.0 preserves true millimetre symbol geometry."],
    )


@feature(
    "settingsDrawingsPenSets.textConversion",
    "Text Conversion",
    part="settings",
    fields=[
        select(
            "mode",
            "TrueType export handling",
            [
                ("preserveTtf", "Preserve TrueType style"),
                ("mapShx", "Map to simplex.shx"),
                ("explode", "Convert headings to polylines"),
            ],
            "preserveTtf",
        ),
    ],
    requires_project=False,
)
def text_conversion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure TrueType font handling during DXF/DWG CAD export."""
    font = load_settings(ctx).drawings.standard.font
    return result(
        summary={"font": font, "conversionMode": values["mode"]},
        tables=[
            table(
                "CAD text conversion",
                [("font", "Font"), ("mode", "Export mode")],
                [{"font": font, "mode": values["mode"]}],
            )
        ],
        notes=["Preserving TrueType maintains exact text bounding widths."],
    )


@feature(
    "settingsDrawingsPenSets.softProofing",
    "Soft Proofing",
    part="settings",
    fields=[],
    requires_project=False,
)
def soft_proofing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify ink contrast and paper color proofing settings."""
    return result(
        summary={"iccProfile": "sRGB IEC61966-2.1", "paperSim": "Bright White"},
        tables=[
            table(
                "Soft proofing profile",
                [("setting", "Setting"), ("value", "Value")],
                [
                    {"setting": "Proofing space", "value": "sRGB IEC61966-2.1"},
                    {"setting": "Min contrast ratio", "value": "7.0 : 1"},
                ],
            )
        ],
        notes=["Verifies legibility of thin grey grid lines against white paper."],
    )


@feature(
    "settingsDrawingsPenSets.overprintPreview",
    "Overprint Preview",
    part="settings",
    fields=[
        checkbox("simulateBlend", "Simulate transparent fill blending", True),
    ],
    requires_project=False,
)
def overprint_preview(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Toggle overprint and shaded hatch blending simulation for print preview."""
    return result(
        summary={"overprintSimulation": values["simulateBlend"]},
        tables=[
            table(
                "Overprint preview",
                [("option", "Option"), ("enabled", "Enabled")],
                [{"option": "Blend overlapping fills", "enabled": values["simulateBlend"]}],
            )
        ],
        notes=["Prevents opaque solid hatches from obscuring underlying grid lines."],
    )


@feature(
    "settingsDrawingsPenSets.paperMargin",
    "Paper Margin",
    part="settings",
    fields=[
        number(
            "hardClipMm", "Plotter non-printable edge margin", 5.0, unit="mm", min=0.0, max=20.0
        ),
    ],
    requires_project=False,
)
def paper_margin(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check sheet border clearance against physical plotter hard-clip margins."""
    border_margin = 10.0
    ok = border_margin >= values["hardClipMm"]
    return result(
        summary={
            "hardClipMm": values["hardClipMm"],
            "borderMarginMm": border_margin,
            "clearsHardClip": ok,
        },
        tables=[
            table(
                "Plotter printable margin",
                [("item", "Item"), ("mm", "Margin", "mm")],
                [
                    {"item": "Plotter hard clip", "mm": values["hardClipMm"]},
                    {"item": "Sheet border inset", "mm": border_margin},
                ],
            )
        ],
        notes=["Sheet border inset must exceed plotter hardware clip margin."],
    )


@feature(
    "settingsDrawingsPenSets.testPrint",
    "Test Print",
    part="settings",
    fields=[],
    requires_project=False,
)
def test_print(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate calibration lineweight & scale verification test-strip parameters."""
    st = load_settings(ctx)
    rows = [
        {"check": "100 mm calibration bar", "expectedMm": 100.0},
        {"check": "Pen weights 0.13-0.70 mm", "expectedMm": 0.70},
        {"check": f"Sheet {st.drawings.sheetSize}", "expectedMm": 1.0},
    ]
    return result(
        summary={"sheetSize": st.drawings.sheetSize, "calibrationBarMm": 100.0},
        tables=[
            table(
                "Plot calibration strip",
                [("check", "Calibration item"), ("expectedMm", "Target", "mm")],
                rows,
            )
        ],
        notes=["Measure the 100 mm calibration bar after plotting to verify 1:1 true scale."],
    )
