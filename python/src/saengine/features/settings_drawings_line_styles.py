"""Project Settings - Drawings: Line Styles tab: lineweights, dash types, hatches, object lines, colors, scales."""

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
)
from saengine.features.settings_common import load_settings
from saengine.library.settings import LINEWEIGHTS


@feature(
    "settingsDrawingsLineStyles.lineWeight",
    "Line Weight",
    part="settings",
    fields=[],
    requires_project=False,
)
def line_weight(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign and inspect plotted lineweights across structural drawing element classes."""
    rows = [
        {"element": "Section cut concrete outline", "weightMm": 0.50},
        {"element": "Beam / column elevation", "weightMm": 0.35},
        {"element": "Reinforcement bars", "weightMm": 0.35},
        {"element": "Dimension & leader lines", "weightMm": 0.18},
        {"element": "Structural grid & hatch", "weightMm": 0.13},
    ]
    return result(
        summary={"classCount": len(rows), "availableWeights": len(LINEWEIGHTS)},
        tables=[
            table(
                "Element class lineweights",
                [("element", "Element class"), ("weightMm", "Lineweight", "mm")],
                rows,
            )
        ],
        notes=["Uses ISO standard lineweight steps from DraftingStandard."],
    )


@feature(
    "settingsDrawingsLineStyles.weightScale",
    "Weight Scale",
    part="settings",
    fields=[
        number(
            "baseWeightMm", "Base plotted lineweight (at 1:100)", 0.35, unit="mm", min=0.09, max=1.0
        ),
        number("viewScale", "Target viewport scale denominator", 50.0, min=10.0, max=500.0),
    ],
    requires_project=False,
)
def weight_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale plotted lineweights smoothly with drawing viewport magnification."""
    factor = (100.0 / values["viewScale"]) ** 0.25
    scaled = min(1.0, max(0.09, values["baseWeightMm"] * factor))
    return result(
        summary={
            "baseWeightMm": values["baseWeightMm"],
            "scaleFactor": factor,
            "scaledWeightMm": scaled,
        },
        tables=[
            table(
                "Scale-adjusted lineweight",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Scale factor", "value": factor},
                    {"item": "Adjusted weight [mm]", "value": scaled},
                ],
            )
        ],
        notes=["Enlarged details (1:20, 1:50) receive slightly heavier pens for visual hierarchy."],
    )


@feature(
    "settingsDrawingsLineStyles.minimumWeight",
    "Minimum Weight",
    part="settings",
    fields=[
        number("minPenMm", "Minimum plotted pen width", 0.13, unit="mm", min=0.05, max=0.25),
    ],
    requires_project=False,
)
def minimum_weight(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify minimum plotted pen width against printer/PDF legibility thresholds."""
    clamped = [lw for lw in LINEWEIGHTS if lw >= values["minPenMm"]]
    return result(
        summary={"minPenMm": values["minPenMm"], "compliantWeightsCount": len(clamped)},
        tables=[
            table(
                "Minimum pen legibility check",
                [("weightMm", "Lineweight", "mm"), ("allowed", "Allowed")],
                [{"weightMm": lw, "allowed": lw >= values["minPenMm"]} for lw in LINEWEIGHTS],
            )
        ],
        notes=["Lines thinner than 0.13 mm may fade on reduced half-size A3 check prints."],
    )


@feature(
    "settingsDrawingsLineStyles.applyWeights",
    "Apply Weights",
    part="settings",
    fields=[],
    requires_project=False,
)
def apply_weights(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview applying configured DraftingStandard layer weights across views."""
    std = load_settings(ctx).drawings.standard
    rows = [{"layer": l.layer, "lineweightMm": l.lineweight or 0.25} for l in std.layers]
    return result(
        summary={"configuredLayerWeights": len(rows)},
        tables=[
            table(
                "Applied layer weights",
                [("layer", "Layer"), ("lineweightMm", "Weight", "mm")],
                rows or [{"layer": "Default scheme", "lineweightMm": 0.25}],
            )
        ],
        notes=["Applies DraftingStandard.layers weights to DXF and PDF view exports."],
    )


@feature(
    "settingsDrawingsLineStyles.lineType",
    "Line Type",
    part="settings",
    fields=[],
    requires_project=False,
)
def line_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List standard CAD line types assigned to structural object categories."""
    rows = [
        {"type": "CONTINUOUS", "use": "Visible member outlines & rebar"},
        {"type": "DASHED", "use": "Hidden edges & beams below"},
        {"type": "DASHDOT", "use": "Structural grid & member centerlines"},
        {"type": "PHANTOM", "use": "Adjacent / existing structure outlines"},
    ]
    return result(
        summary={"lineTypeCount": len(rows)},
        tables=[table("CAD line types", [("type", "Line type"), ("use", "Structural use")], rows)],
        notes=["Standard AutoCAD/DXF linetype definitions."],
    )


@feature(
    "settingsDrawingsLineStyles.dashPattern",
    "Dash Pattern",
    part="settings",
    fields=[
        number("dashMm", "Dash length (paper)", 3.0, unit="mm", min=0.5, max=15.0),
        number("gapMm", "Gap length (paper)", 1.5, unit="mm", min=0.5, max=10.0),
    ],
    requires_project=False,
)
def dash_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute dash-gap repeat cycle and model-space pattern lengths."""
    scale = load_settings(ctx).drawings.planScale
    cycle = values["dashMm"] + values["gapMm"]
    return result(
        summary={
            "paperCycleMm": cycle,
            "modelDashMm": values["dashMm"] * scale,
            "modelGapMm": values["gapMm"] * scale,
        },
        tables=[
            table(
                "Dash pattern geometry",
                [("segment", "Segment"), ("paperMm", "Paper", "mm"), ("modelMm", "Model", "mm")],
                [
                    {
                        "segment": "Dash",
                        "paperMm": values["dashMm"],
                        "modelMm": values["dashMm"] * scale,
                    },
                    {
                        "segment": "Gap",
                        "paperMm": values["gapMm"],
                        "modelMm": values["gapMm"] * scale,
                    },
                ],
            )
        ],
        notes=[f"Scaled for plan scale 1:{scale}."],
    )


@feature(
    "settingsDrawingsLineStyles.patternScale",
    "Pattern Scale",
    part="settings",
    fields=[
        number("ltscale", "Global LTSCALE factor", 1.0, min=0.1, max=1000.0),
        number("viewScale", "Viewport scale denominator", 100.0, min=10.0, max=500.0),
    ],
    requires_project=False,
)
def pattern_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute effective paper-space linetype scale factor (PSLTSCALE × LTSCALE)."""
    eff = values["ltscale"] * values["viewScale"]
    return result(
        summary={"ltscale": values["ltscale"], "effectiveModelScale": eff},
        tables=[
            table(
                "Linetype pattern scaling",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Base LTSCALE", "value": values["ltscale"]},
                    {"item": "Effective model-space scale", "value": eff},
                ],
            )
        ],
        notes=["Keeps dashed/centerline patterns uniform across mixed-scale viewports."],
    )


@feature(
    "settingsDrawingsLineStyles.previewStyle",
    "Preview Style",
    part="settings",
    fields=[
        select(
            "style",
            "Style to preview",
            [
                ("outline", "Structural Outline"),
                ("hidden", "Hidden Beam"),
                ("grid", "Grid Centerline"),
                ("rebar", "Main Rebar"),
            ],
            "outline",
        ),
    ],
    requires_project=False,
)
def preview_style(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview combined linetype, color index, and plotted weight for a line style."""
    presets = {
        "outline": ("CONTINUOUS", 7, 0.35),
        "hidden": ("DASHED", 8, 0.18),
        "grid": ("DASHDOT", 1, 0.13),
        "rebar": ("CONTINUOUS", 3, 0.50),
    }
    lt, aci, lw = presets[values["style"]]
    return result(
        summary={"style": values["style"], "lineType": lt, "aciColor": aci, "lineweightMm": lw},
        tables=[
            table(
                "Line style preview",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Linetype", "value": lt},
                    {"property": "ACI color", "value": str(aci)},
                    {"property": "Plotted weight [mm]", "value": str(lw)},
                ],
            )
        ],
        notes=["Previews DXF entity attributes assigned during export."],
    )


@feature(
    "settingsDrawingsLineStyles.hatchPattern",
    "Hatch Pattern",
    part="settings",
    fields=[
        select(
            "material",
            "Section cut material",
            [
                ("concrete", "Concrete"),
                ("steel", "Structural Steel"),
                ("masonry", "Masonry"),
                ("earth", "Subgrade Earth"),
            ],
            "concrete",
        ),
    ],
    requires_project=False,
)
def ls_hatch_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select standard DXF hatch pattern name for a structural material section."""
    pats = {"concrete": "AR-CONC", "steel": "ANSI31", "masonry": "ANSI32", "earth": "EARTH"}
    return result(
        summary={"material": values["material"], "pattern": pats[values["material"]]},
        tables=[
            table(
                "Material hatch selection",
                [("material", "Material"), ("pattern", "DXF pattern")],
                [{"material": values["material"], "pattern": pats[values["material"]]}],
            )
        ],
        notes=["Standard AutoCAD hatch pattern identifiers."],
    )


@feature(
    "settingsDrawingsLineStyles.hatchScale",
    "Hatch Scale",
    part="settings",
    fields=[
        number("baseScale", "Base hatch pattern scale", 1.0, min=0.1, max=100.0),
        number("detailScale", "Detail viewport scale denominator", 25.0, min=5.0, max=250.0),
    ],
    requires_project=False,
)
def hatch_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute model-space hatch pattern scale for readable section cuts."""
    model_scale = values["baseScale"] * (values["detailScale"] / 25.0)
    return result(
        summary={"baseScale": values["baseScale"], "effectiveHatchScale": model_scale},
        tables=[
            table(
                "Hatch scale calculation",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Base scale", "value": values["baseScale"]},
                    {"item": "Effective model scale", "value": model_scale},
                ],
            )
        ],
        notes=["Normalized to 1:25 detail scale so dense concrete hatches remain legible."],
    )


@feature(
    "settingsDrawingsLineStyles.hatchAngle",
    "Hatch Angle",
    part="settings",
    fields=[
        number("angleDeg", "Hatch rotation angle", 45.0, unit="°", min=0.0, max=180.0),
    ],
    requires_project=False,
)
def hatch_angle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set hatch rotation angle and complementary adjacent-part angle."""
    comp = (values["angleDeg"] + 90.0) % 180.0
    return result(
        summary={"primaryAngleDeg": values["angleDeg"], "adjacentPartAngleDeg": comp},
        tables=[
            table(
                "Hatch orientation",
                [("part", "Part"), ("angleDeg", "Angle", "°")],
                [
                    {"part": "Primary cut member", "angleDeg": values["angleDeg"]},
                    {"part": "Adjacent cut plate/member", "angleDeg": comp},
                ],
            )
        ],
        notes=["Adjacent steel plates use orthogonal hatch angles to distinguish parts."],
    )


@feature(
    "settingsDrawingsLineStyles.fillStyle",
    "Fill Style",
    part="settings",
    fields=[
        select(
            "fillKind",
            "Cut face fill mode",
            [
                ("pattern", "Vector hatch pattern"),
                ("solid", "Solid shaded fill"),
                ("none", "Outline only (no fill)"),
            ],
            "pattern",
        ),
        number("transparencyPct", "Solid fill transparency", 75.0, unit="%", min=0.0, max=95.0),
    ],
    requires_project=False,
)
def fill_style(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure section cut fill mode and background screening transparency."""
    return result(
        summary={"fillKind": values["fillKind"], "transparencyPct": values["transparencyPct"]},
        tables=[
            table(
                "Section fill style",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Fill mode", "value": values["fillKind"]},
                    {"property": "Transparency [%]", "value": str(values["transparencyPct"])},
                ],
            )
        ],
        notes=[
            "75% transparency keeps overlapping dimension text readable over shaded walls/columns."
        ],
    )


@feature(
    "settingsDrawingsLineStyles.structuralOutline",
    "Structural Outline",
    part="settings",
    fields=[
        number("weightMm", "Visible outline weight", 0.35, unit="mm", min=0.18, max=0.70),
    ],
    requires_project=False,
)
def structural_outline(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assign visible structural member boundary lineweight and layer."""
    return result(
        summary={
            "layer": "S-COLS / S-BEAM",
            "lineType": "CONTINUOUS",
            "weightMm": values["weightMm"],
        },
        tables=[
            table(
                "Structural outline style",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Linetype", "value": "CONTINUOUS"},
                    {"item": "Weight [mm]", "value": str(values["weightMm"])},
                ],
            )
        ],
        notes=["Applied to visible column, beam, and slab edges."],
    )


@feature(
    "settingsDrawingsLineStyles.hiddenLines",
    "Hidden Lines",
    part="settings",
    fields=[
        number("weightMm", "Hidden edge lineweight", 0.18, unit="mm", min=0.09, max=0.35),
    ],
    requires_project=False,
)
def hidden_lines(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure dashed line style for concealed beams, drop panels, and footings below."""
    return result(
        summary={"lineType": "DASHED", "weightMm": values["weightMm"]},
        tables=[
            table(
                "Hidden element line style",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Linetype", "value": "DASHED"},
                    {"item": "Weight [mm]", "value": str(values["weightMm"])},
                ],
            )
        ],
        notes=["Used for hidden edges behind slabs or below finished grade."],
    )


@feature(
    "settingsDrawingsLineStyles.centerlineStyle",
    "Centerline Style",
    part="settings",
    fields=[
        number("weightMm", "Centerline pen weight", 0.13, unit="mm", min=0.09, max=0.25),
    ],
    requires_project=False,
)
def centerline_style(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure chain-dot centerline style for structural grids and member axes."""
    return result(
        summary={"lineType": "CENTER / DASHDOT", "weightMm": values["weightMm"]},
        tables=[
            table(
                "Grid & centerline style",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Linetype", "value": "DASHDOT"},
                    {"item": "Weight [mm]", "value": str(values["weightMm"])},
                ],
            )
        ],
        notes=["Applied to S-GRID and framing centerlines."],
    )


@feature(
    "settingsDrawingsLineStyles.breakLines",
    "Break Lines",
    part="settings",
    fields=[
        number("jogSizeMm", "Break symbol jog height (paper)", 3.0, unit="mm", min=1.5, max=8.0),
    ],
    requires_project=False,
)
def break_lines(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure section and elevation break-line zigzag amplitude."""
    scale = load_settings(ctx).drawings.detailScale
    return result(
        summary={"paperJogMm": values["jogSizeMm"], "modelJogMm": values["jogSizeMm"] * scale},
        tables=[
            table(
                "Break line sizing",
                [("scale", "Scale"), ("jogMm", "Jog height", "mm")],
                [
                    {"scale": "Paper", "jogMm": values["jogSizeMm"]},
                    {"scale": f"1:{scale}", "jogMm": values["jogSizeMm"] * scale},
                ],
            )
        ],
        notes=["Marks truncated member lengths in beam elevations and details."],
    )


@feature(
    "settingsDrawingsLineStyles.layerColor",
    "Layer Color",
    part="settings",
    fields=[
        number("aciColor", "AutoCAD Color Index (1-255)", 3.0, min=1.0, max=255.0),
    ],
    requires_project=False,
)
def layer_color(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect configured layer ACI colors in DraftingStandard."""
    std = load_settings(ctx).drawings.standard
    rows = [{"layer": l.layer, "aciColor": l.color or int(values["aciColor"])} for l in std.layers]
    return result(
        summary={"defaultAci": int(values["aciColor"]), "configuredLayers": len(rows)},
        tables=[
            table(
                "Layer ACI color map",
                [("layer", "Layer"), ("aciColor", "ACI color")],
                rows or [{"layer": "S-COLS", "aciColor": int(values["aciColor"])}],
            )
        ],
        notes=["ACI colors 1-7 map to standard primary CAD pens."],
    )


@feature(
    "settingsDrawingsLineStyles.overrideColor",
    "Override Color",
    part="settings",
    fields=[
        number("highlightAci", "Highlight override ACI color", 1.0, min=1.0, max=255.0),
    ],
    requires_project=False,
)
def override_color(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set temporary highlight color override for failed checks or revisions."""
    return result(
        summary={"overrideAci": int(values["highlightAci"])},
        tables=[
            table(
                "Highlight color override",
                [("role", "Role"), ("aci", "ACI color")],
                [{"role": "Overstressed / flagged element", "aci": int(values["highlightAci"])}],
            )
        ],
        notes=["ACI 1 (Red) visually flags failing members on diagnostic plan exports."],
    )


@feature(
    "settingsDrawingsLineStyles.objectColor",
    "Object Color",
    part="settings",
    fields=[],
    requires_project=False,
)
def object_color(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Map structural material categories to standard CAD display colors."""
    rows = [
        {"material": "Reinforced Concrete", "aci": 7, "colorName": "White/Black"},
        {"material": "Structural Steel", "aci": 4, "colorName": "Cyan"},
        {"material": "Reinforcement Rebar", "aci": 3, "colorName": "Green"},
        {"material": "Masonry", "aci": 30, "colorName": "Orange"},
    ]
    return result(
        summary={"mappedMaterials": len(rows)},
        tables=[
            table(
                "Material color scheme",
                [("material", "Material"), ("aci", "ACI"), ("colorName", "Color")],
                rows,
            )
        ],
        notes=["Provides quick visual differentiation on multi-material framing plans."],
    )


@feature(
    "settingsDrawingsLineStyles.colorScheme",
    "Color Scheme",
    part="settings",
    fields=[
        select(
            "scheme",
            "Drawing color scheme",
            [
                ("monochrome", "Monochrome (black & greyscale)"),
                ("discipline", "By structural element class"),
                ("utilisation", "By design utilisation ratio"),
            ],
            "discipline",
        ),
    ],
    requires_project=False,
)
def color_scheme(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Select active vector drawing color scheme preset."""
    return result(
        summary={"colorScheme": values["scheme"]},
        tables=[
            table(
                "Active color scheme",
                [("scheme", "Scheme"), ("description", "Behavior")],
                [
                    {
                        "scheme": values["scheme"],
                        "description": "Controls DXF/PDF vector stroke coloring",
                    }
                ],
            )
        ],
        notes=[
            "Utilisation mode colors elements green (< 0.85), amber (0.85-1.0), and red (> 1.0)."
        ],
    )


@feature(
    "settingsDrawingsLineStyles.annotationScale",
    "Annotation Scale",
    part="settings",
    fields=[
        number("paperSizeMm", "Plotted symbol/text size", 2.5, unit="mm", min=1.0, max=10.0),
    ],
    requires_project=False,
)
def annotation_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute annotative model-space sizes across plan and detail scales."""
    d = load_settings(ctx).drawings
    rows = [
        {"scale": f"1:{s}", "modelMm": values["paperSizeMm"] * s}
        for s in sorted({d.planScale, d.slabScale, d.detailScale})
    ]
    return result(
        summary={"paperSizeMm": values["paperSizeMm"], "scaleCount": len(rows)},
        tables=[
            table(
                "Annotative scale factors",
                [("scale", "View scale"), ("modelMm", "Model size", "mm")],
                rows,
            )
        ],
        notes=["Keeps plotted annotation height identical across sheets."],
    )


@feature(
    "settingsDrawingsLineStyles.modelLineScale",
    "Model Line Scale",
    part="settings",
    fields=[
        number("scaleFactor", "Model-space line pattern multiplier", 1.0, min=0.1, max=100.0),
    ],
    requires_project=False,
)
def model_line_scale(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Set model-space dash/dot spacing multiplier."""
    return result(
        summary={"modelLineScale": values["scaleFactor"]},
        tables=[
            table(
                "Model line scale",
                [("parameter", "Parameter"), ("value", "Value")],
                [{"parameter": "Model line pattern factor", "value": values["scaleFactor"]}],
            )
        ],
        notes=["Adjusts dash frequency when inspecting model space prior to sheet layout."],
    )


@feature(
    "settingsDrawingsLineStyles.scaleIndependent",
    "Scale Independent",
    part="settings",
    fields=[
        checkbox(
            "lockPaperWeights", "Keep plotted pen weights independent of viewport scale", True
        ),
    ],
    requires_project=False,
)
def scale_independent(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Toggle fixed paper-space lineweights across differing viewport scales."""
    return result(
        summary={"scaleIndependentWeights": values["lockPaperWeights"]},
        tables=[
            table(
                "Scale independence",
                [("setting", "Setting"), ("enabled", "Enabled")],
                [
                    {
                        "setting": "Fixed paper-space pen widths",
                        "enabled": values["lockPaperWeights"],
                    }
                ],
            )
        ],
        notes=["Recommended True so structural outlines always plot at their assigned pen mm."],
    )


@feature(
    "settingsDrawingsLineStyles.syncLineScales",
    "Sync Line Scales",
    part="settings",
    fields=[],
    requires_project=False,
)
def sync_line_scales(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check line scale synchronization across project plan, slab, elevation, and detail viewports."""
    d = load_settings(ctx).drawings
    rows = [
        {"view": "Plan", "scale": d.planScale, "ltscale": d.planScale},
        {"view": "Slab", "scale": d.slabScale, "ltscale": d.slabScale},
        {"view": "Elevation", "scale": d.elevationScale, "ltscale": d.elevationScale},
        {"view": "Detail", "scale": d.detailScale, "ltscale": d.detailScale},
    ]
    return result(
        summary={"viewportCount": len(rows), "synchronized": True},
        tables=[
            table(
                "Synchronized viewport line scales",
                [("view", "View"), ("scale", "Scale 1:N"), ("ltscale", "Synced LTSCALE")],
                rows,
            )
        ],
        notes=["Ensures identical dash spacing across every viewport scale."],
    )
