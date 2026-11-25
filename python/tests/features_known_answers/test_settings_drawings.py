"""Independent known-answer tests for standalone calculators in Project Settings Drawings, Line Styles, Pen Sets, and Sheet Standards."""

from __future__ import annotations

import math

import pytest

from saengine import features

# ── Settings Drawings (settings_drawings.py: 11) ────────────────────────────────────────────────


def test_settings_drawings_batch_plot() -> None:
    # 2 standard front sheets (001, 101) + 4 floor levels (201..204) + 1 schedule sheet (301) = 7 sheets.
    res = features.run(
        "settingsDrawings.batchPlot",
        None,
        {"floorLevels": 4},
    )
    assert res["problems"] == []
    assert res["summary"]["queuedSheets"] == 7


def test_settings_drawings_callout_defaults() -> None:
    # Default plan scale 1:100; paper bubble 12 mm -> model bubble 1200 mm.
    res = features.run(
        "settingsDrawings.calloutDefaults",
        None,
        {"bubbleDiameterMm": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["paperBubbleMm"] == pytest.approx(12.0, rel=0.01)
    assert res["summary"]["modelBubbleMm"] == pytest.approx(1200.0, rel=0.01)


def test_settings_drawings_dimension_style() -> None:
    # Default plan scale 1:100; paper text = 3.0 mm -> model text = 300.0 mm.
    res = features.run(
        "settingsDrawings.dimensionStyle",
        None,
        {"textHeightMm": 3.0, "arrowSizeMm": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["paperTextMm"] == pytest.approx(3.0, rel=0.01)
    assert res["summary"]["modelTextMm"] == pytest.approx(300.0, rel=0.01)


def test_settings_drawings_label_styles() -> None:
    # Default plan scale 1:100; paper landing = 5.0 mm -> model landing = 500.0 mm.
    res = features.run(
        "settingsDrawings.labelStyles",
        None,
        {"leaderLandingMm": 5.0, "frameShape": "circle"},
    )
    assert res["problems"] == []
    assert res["summary"]["frameShape"] == "circle"
    assert res["summary"]["modelLandingMm"] == pytest.approx(500.0, rel=0.01)


def test_settings_drawings_match_lines() -> None:
    res = features.run(
        "settingsDrawings.matchLines",
        None,
        {"overlapMm": 2000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["overlapMm"] == pytest.approx(2000.0, rel=0.01)


def test_settings_drawings_north_arrow() -> None:
    # 30 deg CCW -> dx = -sin(30) = -0.5, dy = cos(30) = sqrt(3)/2 = 0.86603.
    res = features.run(
        "settingsDrawings.northArrow",
        None,
        {"trueNorthRotationDeg": 30.0, "arrowStyle": "compass"},
    )
    assert res["problems"] == []
    assert res["summary"]["dx"] == pytest.approx(-0.5, rel=0.01)
    assert res["summary"]["dy"] == pytest.approx(math.sqrt(3.0) / 2.0, rel=0.01)


def test_settings_drawings_page_numbering() -> None:
    res = features.run(
        "settingsDrawings.pageNumbering",
        None,
        {"scheme": "sheetTotal", "estimatedPages": 32},
    )
    assert res["problems"] == []
    assert res["summary"]["estimatedPages"] == 32
    assert res["summary"]["example"] == "Page 1 of 32"


def test_settings_drawings_print_setup() -> None:
    # Default A1 (841 x 594 mm), 15 mm margin on each edge -> 811 x 564 mm.
    res = features.run(
        "settingsDrawings.printSetup",
        None,
        {"marginMm": 15.0, "fitToPage": True},
    )
    assert res["problems"] == []
    assert res["summary"]["printableWidthMm"] == pytest.approx(811.0, rel=0.01)
    assert res["summary"]["printableHeightMm"] == pytest.approx(564.0, rel=0.01)
    assert res["summary"]["trueScale"] is False


def test_settings_drawings_revision_clouds() -> None:
    # Default planScale = 100, detailScale = 25; paperArc = 5 mm -> plan = 500 mm, detail = 125 mm.
    res = features.run(
        "settingsDrawings.revisionClouds",
        None,
        {"arcChordMm": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["planModelArcMm"] == pytest.approx(500.0, rel=0.01)
    assert res["summary"]["detailModelArcMm"] == pytest.approx(125.0, rel=0.01)


def test_settings_drawings_text_styles() -> None:
    # Default plan scale 100 -> model note height = 3.0 * 100 = 300 mm in table row 0.
    res = features.run(
        "settingsDrawings.textStyles",
        None,
        {"noteHeightMm": 3.0, "headingHeightMm": 6.0},
    )
    assert res["problems"] == []
    assert res["summary"]["noteHeightMm"] == pytest.approx(3.0, rel=0.01)
    assert res["tables"][0]["rows"][0]["modelMm"] == pytest.approx(300.0, rel=0.01)


def test_settings_drawings_view_scales() -> None:
    # Default A1 width 841 mm, usable = 841 - 160 = 681 mm, planScale = 100.
    # 50 m = 500 mm on sheet <= 681 mm -> fits True.
    res = features.run(
        "settingsDrawings.viewScales",
        None,
        {"buildingLengthM": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["planFitsOnSheet"] is True


# ── Settings Drawings Line Styles (settings_drawings_line_styles.py: 15) ────────────────────────


def test_settings_drawings_line_styles_annotation_scale() -> None:
    # Default scales {25, 50, 100}; paperSize = 3.0 mm -> modelMm = 75, 150, 300.
    res = features.run(
        "settingsDrawingsLineStyles.annotationScale",
        None,
        {"paperSizeMm": 3.0},
    )
    assert res["problems"] == []
    assert res["summary"]["paperSizeMm"] == pytest.approx(3.0, rel=0.01)
    model_sizes = [r["modelMm"] for r in res["tables"][0]["rows"]]
    assert model_sizes[0] == pytest.approx(75.0, rel=0.01)


def test_settings_drawings_line_styles_break_lines() -> None:
    # Default detailScale = 25 -> modelJogMm = 4.0 * 25 = 100.0 mm.
    res = features.run(
        "settingsDrawingsLineStyles.breakLines",
        None,
        {"jogSizeMm": 4.0},
    )
    assert res["problems"] == []
    assert res["summary"]["modelJogMm"] == pytest.approx(100.0, rel=0.01)


def test_settings_drawings_line_styles_centerline_style() -> None:
    res = features.run(
        "settingsDrawingsLineStyles.centerlineStyle",
        None,
        {"weightMm": 0.18},
    )
    assert res["problems"] == []
    assert res["summary"]["weightMm"] == pytest.approx(0.18, rel=0.01)


def test_settings_drawings_line_styles_dash_pattern() -> None:
    # Default planScale = 100; dash = 4.0, gap = 2.0 -> cycle = 6.0 mm, modelDash = 400, modelGap = 200.
    res = features.run(
        "settingsDrawingsLineStyles.dashPattern",
        None,
        {"dashMm": 4.0, "gapMm": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["paperCycleMm"] == pytest.approx(6.0, rel=0.01)
    assert res["summary"]["modelDashMm"] == pytest.approx(400.0, rel=0.01)
    assert res["summary"]["modelGapMm"] == pytest.approx(200.0, rel=0.01)


def test_settings_drawings_line_styles_fill_style() -> None:
    res = features.run(
        "settingsDrawingsLineStyles.fillStyle",
        None,
        {"fillKind": "solid", "transparencyPct": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["fillKind"] == "solid"
    assert res["summary"]["transparencyPct"] == pytest.approx(60.0, rel=0.01)


def test_settings_drawings_line_styles_hatch_angle() -> None:
    # 30 deg -> orthogonal adjacent part angle = (30 + 90) % 180 = 120 deg.
    res = features.run(
        "settingsDrawingsLineStyles.hatchAngle",
        None,
        {"angleDeg": 30.0},
    )
    assert res["problems"] == []
    assert res["summary"]["primaryAngleDeg"] == pytest.approx(30.0, rel=0.01)
    assert res["summary"]["adjacentPartAngleDeg"] == pytest.approx(120.0, rel=0.01)


def test_settings_drawings_line_styles_hatch_scale() -> None:
    # base = 1.5, detailScale = 50 -> effective = 1.5 * (50 / 25) = 3.0.
    res = features.run(
        "settingsDrawingsLineStyles.hatchScale",
        None,
        {"baseScale": 1.5, "detailScale": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveHatchScale"] == pytest.approx(3.0, rel=0.01)


def test_settings_drawings_line_styles_hidden_lines() -> None:
    res = features.run(
        "settingsDrawingsLineStyles.hiddenLines",
        None,
        {"weightMm": 0.25},
    )
    assert res["problems"] == []
    assert res["summary"]["weightMm"] == pytest.approx(0.25, rel=0.01)


def test_settings_drawings_line_styles_layer_color() -> None:
    res = features.run(
        "settingsDrawingsLineStyles.layerColor",
        None,
        {"aciColor": 5},
    )
    assert res["problems"] == []
    assert res["summary"]["defaultAci"] == 5


def test_settings_drawings_line_styles_minimum_weight() -> None:
    # Standard ISO weights: [0.13, 0.18, 0.25, 0.35, 0.50, 0.70, 1.00, 1.40, 2.00] (or similar);
    # verify monotonic: higher minPenMm leaves fewer or equal compliant weights.
    r_low = features.run("settingsDrawingsLineStyles.minimumWeight", None, {"minPenMm": 0.13})
    r_high = features.run("settingsDrawingsLineStyles.minimumWeight", None, {"minPenMm": 0.25})
    assert r_low["problems"] == []
    assert r_low["summary"]["compliantWeightsCount"] > r_high["summary"]["compliantWeightsCount"]


def test_settings_drawings_line_styles_model_line_scale() -> None:
    res = features.run(
        "settingsDrawingsLineStyles.modelLineScale",
        None,
        {"scaleFactor": 2.5},
    )
    assert res["problems"] == []
    assert res["summary"]["modelLineScale"] == pytest.approx(2.5, rel=0.01)


def test_settings_drawings_line_styles_override_color() -> None:
    res = features.run(
        "settingsDrawingsLineStyles.overrideColor",
        None,
        {"highlightAci": 2},
    )
    assert res["problems"] == []
    assert res["summary"]["overrideAci"] == 2


def test_settings_drawings_line_styles_pattern_scale() -> None:
    # 1.5 * 50 = 75.0.
    res = features.run(
        "settingsDrawingsLineStyles.patternScale",
        None,
        {"ltscale": 1.5, "viewScale": 50.0},
    )
    assert res["problems"] == []
    assert res["summary"]["effectiveModelScale"] == pytest.approx(75.0, rel=0.01)


def test_settings_drawings_line_styles_structural_outline() -> None:
    res = features.run(
        "settingsDrawingsLineStyles.structuralOutline",
        None,
        {"weightMm": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["weightMm"] == pytest.approx(0.5, rel=0.01)


def test_settings_drawings_line_styles_weight_scale() -> None:
    # base = 0.35 at 1:100, viewScale = 25 -> factor = (100/25)^0.25 = 4^0.25 = sqrt(2) = 1.41421;
    # scaled = 0.35 * 1.41421 = 0.49497 mm.
    expected_f = (100.0 / 25.0) ** 0.25
    res = features.run(
        "settingsDrawingsLineStyles.weightScale",
        None,
        {"baseWeightMm": 0.35, "viewScale": 25.0},
    )
    assert res["problems"] == []
    assert res["summary"]["scaleFactor"] == pytest.approx(expected_f, rel=0.01)
    assert res["summary"]["scaledWeightMm"] == pytest.approx(0.35 * expected_f, rel=0.01)


# ── Settings Drawings Pen Sets (settings_drawings_pen_sets.py: 7) ───────────────────────────────


def test_settings_drawings_pen_sets_block_scale() -> None:
    res = features.run(
        "settingsDrawingsPenSets.blockScale",
        None,
        {"insertScale": 2.0},
    )
    assert res["problems"] == []
    assert res["summary"]["blockScale"] == pytest.approx(2.0, rel=0.01)


def test_settings_drawings_pen_sets_grey_scale() -> None:
    # Rec.709: Y = 0.2126*100 + 0.7152*150 + 0.0722*200 = 21.26 + 107.28 + 14.44 = 142.98.
    # greyPct = (1 - 142.98 / 255) * 100 = 43.929%.
    lum = 0.2126 * 100.0 + 0.7152 * 150.0 + 0.0722 * 200.0
    res = features.run(
        "settingsDrawingsPenSets.greyScale",
        None,
        {"r": 100.0, "g": 150.0, "b": 200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["luminance"] == pytest.approx(lum, rel=0.01)
    assert res["summary"]["greyPct"] == pytest.approx((1.0 - lum / 255.0) * 100.0, rel=0.01)


def test_settings_drawings_pen_sets_paper_margin() -> None:
    # Border inset 10.0 mm vs hard clip 12.0 mm -> clearsHardClip False.
    res = features.run(
        "settingsDrawingsPenSets.paperMargin",
        None,
        {"hardClipMm": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["clearsHardClip"] is False


def test_settings_drawings_pen_sets_pdf_quality() -> None:
    # 1200 DPI -> step = 25.4 / 1200 = 0.021167 mm.
    res = features.run(
        "settingsDrawingsPenSets.pdfQuality",
        None,
        {"vectorDpi": 1200.0},
    )
    assert res["problems"] == []
    assert res["summary"]["resolutionMm"] == pytest.approx(25.4 / 1200.0, rel=0.01)


def test_settings_drawings_pen_sets_raster_dpi() -> None:
    # A1 (841 x 594 mm) at 254 DPI -> 841/25.4 * 254 = 8410 px, 594/25.4 * 254 = 5940 px;
    # megapixels = 8410 * 5940 / 1e6 = 49.9554 MP.
    res = features.run(
        "settingsDrawingsPenSets.rasterDpi",
        None,
        {"dpi": 254.0},
    )
    assert res["problems"] == []
    assert res["summary"]["a1PixelsWidth"] == 8410
    assert res["summary"]["a1PixelsHeight"] == 5940
    assert res["summary"]["megapixels"] == pytest.approx(49.9554, rel=0.01)


def test_settings_drawings_pen_sets_save_pen_set() -> None:
    # Scale 1:50 -> 6 ISO-snapped pens returned; writeFile=False without project.
    res = features.run(
        "settingsDrawingsPenSets.savePenSet",
        None,
        {"setName": "check-set", "scale": 50.0, "writeFile": False},
    )
    assert res["problems"] == []
    assert res["summary"]["setName"] == "check-set"
    assert res["summary"]["penCount"] == 6
    assert res["summary"]["scale"] == "1:50"


def test_settings_drawings_pen_sets_screening() -> None:
    # 60% ink -> RGB grey channel = round(255 * 0.40) = 102.
    res = features.run(
        "settingsDrawingsPenSets.screening",
        None,
        {"screenPct": 60.0},
    )
    assert res["problems"] == []
    assert res["summary"]["greyChannel"] == 102


# ── Settings Drawings Sheet Standards (settings_drawings_sheet_standards.py: 12) ────────────────


def test_settings_drawings_sheet_standards_company_logo() -> None:
    # 60 mm x 20 mm -> aspect ratio = 3.0.
    res = features.run(
        "settingsDrawingsSheetStandards.companyLogo",
        None,
        {"logoWidthMm": 60.0, "logoHeightMm": 20.0},
    )
    assert res["problems"] == []
    assert res["summary"]["aspectRatio"] == pytest.approx(3.0, rel=0.01)


def test_settings_drawings_sheet_standards_drawing_grid() -> None:
    # Default A1 (841 x 594 mm), 10 cols x 6 rows -> zoneW = 84.1 mm, zoneH = 99.0 mm.
    res = features.run(
        "settingsDrawingsSheetStandards.drawingGrid",
        None,
        {"zoneCols": 10, "zoneRows": 6},
    )
    assert res["problems"] == []
    assert res["summary"]["zoneWidthMm"] == pytest.approx(84.1, rel=0.01)
    assert res["summary"]["zoneHeightMm"] == pytest.approx(99.0, rel=0.01)


def test_settings_drawings_sheet_standards_grid_margins() -> None:
    # Default planScale = 100; radius = 5.0 mm -> modelBubbleRadiusMm = 500.0 mm.
    res = features.run(
        "settingsDrawingsSheetStandards.gridMargins",
        None,
        {"bubbleOffsetMm": 3000.0, "bubbleRadiusMm": 5.0},
    )
    assert res["problems"] == []
    assert res["summary"]["bubbleOffsetMm"] == pytest.approx(3000.0, rel=0.01)
    assert res["summary"]["modelBubbleRadiusMm"] == pytest.approx(500.0, rel=0.01)


def test_settings_drawings_sheet_standards_key_plan() -> None:
    # 80 m = 80,000 mm in 80 mm box -> scale 1:1000.
    res = features.run(
        "settingsDrawingsSheetStandards.keyPlan",
        None,
        {"keyPlanWidthMm": 80.0, "buildingSpanM": 80.0},
    )
    assert res["problems"] == []
    assert res["summary"]["impliedKeyPlanScale"] == pytest.approx(1000.0, rel=0.01)


def test_settings_drawings_sheet_standards_revision_cloud() -> None:
    res = features.run(
        "settingsDrawingsSheetStandards.revisionCloud",
        None,
        {"arcRadiusMm": 4.5, "lineweightMm": 0.5},
    )
    assert res["problems"] == []
    assert res["summary"]["arcRadiusMm"] == pytest.approx(4.5, rel=0.01)
    assert res["summary"]["lineweightMm"] == pytest.approx(0.5, rel=0.01)


def test_settings_drawings_sheet_standards_revision_delta() -> None:
    # sizeMm = 8.0 -> embedded textHeightMm = 8.0 * 0.45 = 3.6 mm.
    res = features.run(
        "settingsDrawingsSheetStandards.revisionDelta",
        None,
        {"shape": "hexagon", "sizeMm": 8.0},
    )
    assert res["problems"] == []
    assert res["summary"]["shape"] == "hexagon"
    assert res["summary"]["textHeightMm"] == pytest.approx(3.6, rel=0.01)


def test_settings_drawings_sheet_standards_revision_table() -> None:
    res = features.run(
        "settingsDrawingsSheetStandards.revisionTable",
        None,
        {"maxVisibleRows": 8},
    )
    assert res["problems"] == []
    assert res["summary"]["shownRows"] <= 8


def test_settings_drawings_sheet_standards_sheet_border() -> None:
    res = features.run(
        "settingsDrawingsSheetStandards.sheetBorder",
        None,
        {"borderWeightMm": 0.7, "doubleFrame": False},
    )
    assert res["problems"] == []
    assert res["summary"]["borderWeightMm"] == pytest.approx(0.7, rel=0.01)
    assert res["summary"]["doubleFrame"] is False


def test_settings_drawings_sheet_standards_sheet_margin() -> None:
    # Default A1 (841 x 594 mm), binding = 25 mm, other = 12 mm:
    # innerWidth = 841 - 25 - 12 = 804 mm; innerHeight = 594 - 2*12 = 570 mm.
    res = features.run(
        "settingsDrawingsSheetStandards.sheetMargin",
        None,
        {"bindingMarginMm": 25.0, "otherMarginMm": 12.0},
    )
    assert res["problems"] == []
    assert res["summary"]["innerWidthMm"] == pytest.approx(804.0, rel=0.01)
    assert res["summary"]["innerHeightMm"] == pytest.approx(570.0, rel=0.01)


def test_settings_drawings_sheet_standards_snap_grid() -> None:
    # major = 1000 mm, snap = 25 mm -> 40 minor steps per major grid.
    res = features.run(
        "settingsDrawingsSheetStandards.snapGrid",
        None,
        {"snapStepMm": 25.0, "majorGridStepMm": 1000.0},
    )
    assert res["problems"] == []
    assert res["summary"]["minorPerMajor"] == pytest.approx(40.0, rel=0.01)


def test_settings_drawings_sheet_standards_view_frame() -> None:
    res = features.run(
        "settingsDrawingsSheetStandards.viewFrame",
        None,
        {"paddingMm": 10.0, "visibleBorder": True},
    )
    assert res["problems"] == []
    assert res["summary"]["paddingMm"] == pytest.approx(10.0, rel=0.01)
    assert res["summary"]["plotFrame"] is True


def test_settings_drawings_sheet_standards_view_labeling() -> None:
    # Default plan scale = 100 -> "{viewName} [1:{scale}]" -> "Level 2 Framing Plan [1:100]".
    res = features.run(
        "settingsDrawingsSheetStandards.viewLabeling",
        None,
        {"titleFormat": "{viewName} [1:{scale}]", "underlineWeightMm": 0.35},
    )
    assert res["problems"] == []
    assert res["summary"]["sampleTitle"] == "Level 2 Framing Plan [1:100]"
    assert res["summary"]["underlineWeightMm"] == pytest.approx(0.35, rel=0.01)
