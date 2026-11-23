"""Project Settings - Code Values: Detailing tab: bar spacing, sizes, covers, stirrups, bundles, splices."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import bar_rules, bars
from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.settings_common import active_pack, load_settings, parse_numbers, safe_table
from saengine.report.clauses import in_force


@feature(
    "settingsCodeValuesDetailing.minSpacing",
    "Min Spacing",
    part="settings",
    fields=[
        number("barMm", "Main bar diameter db", 20.0, unit="mm", min=8.0, max=40.0),
        number("aggregateMm", "Max aggregate size dagg", 20.0, unit="mm", min=10.0, max=40.0),
    ],
    requires_project=False,
)
def cv_min_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute minimum clear horizontal spacing between bars in beams and columns."""
    st = load_settings(ctx)
    db, agg = values["barMm"], values["aggregateMm"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        sp = getattr(safe_table(pack, "detailing"), "spacing", None)
        beam_min = max(
            float(getattr(sp, "layerMin", 25.0) or 25.0),
            float(getattr(sp, "layerDb", 1.0) or 1.0) * db,
            4.0 / 3.0 * agg,
        )
        col_min = max(
            float(getattr(sp, "columnMin", 40.0) or 40.0),
            float(getattr(sp, "columnDb", 1.5) or 1.5) * db,
            4.0 / 3.0 * agg,
        )
    return result(
        summary={"beamMinClearMm": beam_min, "columnMinClearMm": col_min},
        tables=[
            table(
                "Minimum clear bar spacing",
                [("member", "Member"), ("minClearMm", "Min clear", "mm")],
                [
                    {"member": "Beam / slab", "minClearMm": beam_min},
                    {"member": "Column", "minClearMm": col_min},
                ],
            )
        ],
        notes=["Ensures aggregate passage and proper consolidation around reinforcement."],
    )


@feature(
    "settingsCodeValuesDetailing.maxSpacing",
    "Max Spacing",
    part="settings",
    fields=[
        number("slabThicknessMm", "Slab thickness h", 175.0, unit="mm", min=80.0),
    ],
    requires_project=False,
)
def cv_max_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute maximum distribution and primary flexural bar spacing in slabs."""
    h = values["slabThicknessMm"]
    s_main = min(3.0 * h, 450.0)
    s_temp = min(5.0 * h, 450.0)
    return result(
        summary={"maxPrimarySpacingMm": s_main, "maxShrinkageSpacingMm": s_temp},
        tables=[
            table(
                "Maximum slab bar spacing",
                [("role", "Reinforcement"), ("maxMm", "Max spacing", "mm")],
                [
                    {"role": "Primary flexural bars", "maxMm": s_main},
                    {"role": "Shrinkage & temperature", "maxMm": s_temp},
                ],
            )
        ],
        notes=[
            "Capped at min(3h, 450 mm) for flexural bars and min(5h, 450 mm) for temperature bars."
        ],
    )


@feature(
    "settingsCodeValuesDetailing.layerSpacing",
    "Layer Spacing",
    part="settings",
    fields=[
        number("aggregateMm", "Max aggregate size", 20.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def layer_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine vertical clear spacing between parallel reinforcement layers in beams."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        sp = getattr(safe_table(pack, "detailing"), "spacing", None)
        clear = max(
            float(getattr(sp, "betweenLayers", 25.0) or 25.0), 4.0 / 3.0 * values["aggregateMm"]
        )
    return result(
        summary={"verticalClearMm": clear},
        tables=[
            table(
                "Vertical bar layer spacing",
                [("item", "Item"), ("mm", "Value", "mm")],
                [{"item": "Min vertical clear gap", "mm": clear}],
            )
        ],
        notes=["Upper layer bars must align directly over lower layer bars for vibrator access."],
    )


@feature(
    "settingsCodeValuesDetailing.applySpacing",
    "Apply Spacing",
    part="settings",
    fields=[
        number("minSlabSpacingMm", "Minimum practical slab spacing", 100.0, unit="mm", min=50.0),
        number(
            "minStirrupSpacingMm", "Minimum practical stirrup spacing", 75.0, unit="mm", min=50.0
        ),
    ],
    requires_project=False,
)
def apply_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview applying practical bar spacing limits to concrete detailing overrides."""
    return result(
        summary={
            "minSlabSpacingMm": values["minSlabSpacingMm"],
            "minStirrupSpacingMm": values["minStirrupSpacingMm"],
        },
        tables=[
            table(
                "Spacing override mapping",
                [("path", "Override path"), ("mm", "Value", "mm")],
                [
                    {"path": "concrete.minSlabSpacing", "mm": values["minSlabSpacingMm"]},
                    {"path": "concrete.minStirrupSpacing", "mm": values["minStirrupSpacingMm"]},
                ],
            )
        ],
        notes=["Constrains automatic bar proposal algorithms."],
    )


@feature(
    "settingsCodeValuesDetailing.minBarSize",
    "Min Bar Size",
    part="settings",
    fields=[],
    requires_project=False,
)
def min_bar_size(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List smallest permitted bar diameters per structural element group in active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        rows = [
            {"group": g, "minDiaMm": min(bars.diameters(g))}
            for g in ("slab", "main", "column", "stirrup", "foundation")
        ]
    return result(
        summary={
            "minMainBarMm": min(bars.diameters("main")),
            "minStirrupMm": min(bars.diameters("stirrup")),
        },
        tables=[
            table(
                "Minimum bar sizes",
                [("group", "Element group"), ("minDiaMm", "Min diameter", "mm")],
                rows,
            )
        ],
        notes=["Read from active code pack concrete.barDiameters."],
    )


@feature(
    "settingsCodeValuesDetailing.maxBarSize",
    "Max Bar Size",
    part="settings",
    fields=[],
    requires_project=False,
)
def max_bar_size(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List largest permitted bar diameters per structural element group in active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        rows = [
            {"group": g, "maxDiaMm": max(bars.diameters(g))}
            for g in ("slab", "main", "column", "stirrup", "foundation")
        ]
    return result(
        summary={
            "maxMainBarMm": max(bars.diameters("main")),
            "maxColumnMm": max(bars.diameters("column")),
        },
        tables=[
            table(
                "Maximum bar sizes",
                [("group", "Element group"), ("maxDiaMm", "Max diameter", "mm")],
                rows,
            )
        ],
        notes=["Read from active code pack concrete.barDiameters."],
    )


@feature(
    "settingsCodeValuesDetailing.preferredDiameters",
    "Preferred Diameters",
    part="settings",
    fields=[
        text("preferredCsv", "Preferred bar diameters [mm]", "10, 12, 16, 20, 25"),
    ],
    requires_project=False,
)
def preferred_diameters(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate preferred detailer bar sizes against active code pack barDiameters."""
    wanted = parse_numbers(values["preferredCsv"], "Preferred diameters")
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        avail = set(bars.diameters("all"))
    rows = [
        {"diameterMm": d, "inCodePack": d in avail, "areaMm2": math.pi * d**2 / 4.0} for d in wanted
    ]
    return result(
        summary={"preferredCount": len(rows), "allInPack": all(r["inCodePack"] for r in rows)},
        tables=[
            table(
                "Preferred bar diameter validation",
                [
                    ("diameterMm", "Dia", "mm"),
                    ("inCodePack", "In pack"),
                    ("areaMm2", "Area", "mm²"),
                ],
                rows,
            )
        ],
        notes=["Standardizing on fewer bar sizes simplifies site procurement and reduces waste."],
    )


@feature(
    "settingsCodeValuesDetailing.applyBarSizes",
    "Apply Bar Sizes",
    part="settings",
    fields=[
        text("mainBarsCsv", "Main bar list [mm]", "12, 16, 20, 25, 32"),
    ],
    requires_project=False,
)
def apply_bar_sizes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview updating concrete.barDiameters.main override list."""
    dias = parse_numbers(values["mainBarsCsv"], "Main bars")
    return result(
        summary={"barCount": len(dias), "minMm": min(dias), "maxMm": max(dias)},
        tables=[
            table(
                "Main bar override",
                [("path", "Override path"), ("values", "Diameters [mm]")],
                [
                    {
                        "path": "concrete.barDiameters.main",
                        "values": ", ".join(f"{d:g}" for d in dias),
                    }
                ],
            )
        ],
        notes=["Overrides candidate bars available to beam and column rebar proposals."],
    )


@feature(
    "settingsCodeValuesDetailing.nominalCover",
    "Nominal Cover",
    part="settings",
    fields=[],
    requires_project=False,
)
def nominal_cover(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report nominal clear concrete covers by member type from active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        conc = safe_table(pack, "concrete")
        cov = getattr(conc, "cover", None) or {}
    rows = [{"member": k, "coverMm": v} for k, v in cov.items()] if isinstance(cov, dict) else []
    if not rows:
        rows = [
            {"member": "beam", "coverMm": 38.0},
            {"member": "column", "coverMm": 38.0},
            {"member": "slab", "coverMm": 20.0},
            {"member": "footing", "coverMm": 75.0},
        ]
    return result(
        summary={"coverRuleCount": len(rows)},
        tables=[
            table(
                "Nominal concrete covers",
                [("member", "Member"), ("coverMm", "Clear cover", "mm")],
                rows,
            )
        ],
        notes=["Read from active code pack concrete.cover."],
    )


@feature(
    "settingsCodeValuesDetailing.coverExposure",
    "Cover Exposure",
    part="settings",
    fields=[
        select(
            "exposure",
            "Exposure class",
            [
                ("XC1", "XC1 Dry interior"),
                ("XC3", "XC3 Sheltered"),
                ("XC4", "XC4 Cyclic wet/dry"),
                ("XS1", "XS1 Coastal airborne"),
            ],
            "XC3",
        ),
        number("fckMpa", "Concrete strength f'c", 30.0, unit="MPa", min=15.0),
    ],
    requires_project=False,
)
def cover_exposure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Link exposure class and concrete grade to required durability cover."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        if safe_table(pack, "concreteMethods") and getattr(
            pack.table("concreteMethods"), "cover", None
        ):
            cov = bar_rules.nominal_cover([values["exposure"]], 20.0, values["fckMpa"])["cnom"]
        else:
            cov = {"XC1": 25.0, "XC3": 35.0, "XC4": 40.0, "XS1": 50.0}[values["exposure"]]
    return result(
        summary={"exposure": values["exposure"], "nominalCoverMm": cov},
        tables=[
            table(
                "Exposure-linked cover",
                [
                    ("exposure", "Exposure"),
                    ("fckMpa", "f'c", "MPa"),
                    ("coverMm", "Nominal cover", "mm"),
                ],
                [{"exposure": values["exposure"], "fckMpa": values["fckMpa"], "coverMm": cov}],
            )
        ],
        notes=["Durability cover increases for chloride and cyclic moisture exposures."],
    )


@feature(
    "settingsCodeValuesDetailing.coverTolerance",
    "Cover Tolerance",
    part="settings",
    fields=[
        number("cminMm", "Minimum required cover cmin", 30.0, unit="mm", min=10.0),
        number(
            "deltaDevMm",
            "Construction deviation allowance Δcdev",
            10.0,
            unit="mm",
            min=0.0,
            max=20.0,
        ),
    ],
    requires_project=False,
)
def cover_tolerance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute nominal specified drawing cover cnom = cmin + Δcdev."""
    cnom = values["cminMm"] + values["deltaDevMm"]
    return result(
        summary={
            "cminMm": values["cminMm"],
            "deviationMm": values["deltaDevMm"],
            "nominalCoverMm": cnom,
        },
        tables=[
            table(
                "Cover tolerance addition",
                [("term", "Term"), ("mm", "Value", "mm")],
                [
                    {"term": "Minimum cover cmin", "mm": values["cminMm"]},
                    {"term": "Execution tolerance Δcdev", "mm": values["deltaDevMm"]},
                    {"term": "Specified nominal cover cnom", "mm": cnom},
                ],
            )
        ],
        notes=["Drawing schedules specify nominal cover cnom = cmin + Δcdev."],
    )


@feature(
    "settingsCodeValuesDetailing.applyCover",
    "Apply Cover",
    part="settings",
    fields=[
        number("beamCoverMm", "Beam clear cover", 40.0, unit="mm", min=20.0),
        number("slabCoverMm", "Slab clear cover", 20.0, unit="mm", min=15.0),
    ],
    requires_project=False,
)
def apply_cover(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview applying custom clear cover overrides for beams and slabs."""
    return result(
        summary={"beamCoverMm": values["beamCoverMm"], "slabCoverMm": values["slabCoverMm"]},
        tables=[
            table(
                "Cover overrides",
                [("path", "Override path"), ("mm", "Value", "mm")],
                [
                    {"path": "concrete.cover.beam", "mm": values["beamCoverMm"]},
                    {"path": "concrete.cover.slab", "mm": values["slabCoverMm"]},
                ],
            )
        ],
        notes=["Affects effective depth d and durability checks."],
    )


@feature(
    "settingsCodeValuesDetailing.tieLegCount",
    "Tie Leg Count",
    part="settings",
    fields=[
        number("sectionWidthMm", "Beam or column width b", 450.0, unit="mm", min=200.0),
        number("coverMm", "Clear cover to tie", 40.0, unit="mm", min=20.0),
        number("longBarsPerFace", "Longitudinal bars across face", 4.0, min=2.0, max=12.0),
    ],
    requires_project=False,
)
def tie_leg_count(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine minimum stirrup/tie legs across width to keep unrestrained bars within 150 mm."""
    n_bars = int(values["longBarsPerFace"])
    core_w = values["sectionWidthMm"] - 2.0 * values["coverMm"]
    bar_pitch = core_w / max(1, n_bars - 1)
    # Every corner bar held, and no unheld bar > 150 mm clear from a held bar
    min_legs = 2 if bar_pitch <= 150.0 else math.ceil(core_w / 300.0) + 1
    return result(
        summary={"barPitchMm": bar_pitch, "minTieLegs": max(2, min_legs)},
        tables=[
            table(
                "Stirrup/tie leg requirement",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Core width [mm]", "value": core_w},
                    {"metric": "Longitudinal bar pitch [mm]", "value": bar_pitch},
                    {"metric": "Minimum tie legs", "value": max(2, min_legs)},
                ],
            )
        ],
        notes=[
            "Intermediate crossties required whenever adjacent longitudinal bars exceed 150 mm from a restrained bar."
        ],
    )


@feature(
    "settingsCodeValuesDetailing.cornerBendRadius",
    "Corner Bend Radius",
    part="settings",
    fields=[
        number("tieDiaMm", "Stirrup / tie diameter dt", 10.0, unit="mm", min=6.0, max=16.0),
    ],
    requires_project=False,
)
def corner_bend_radius(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute stirrup internal mandrel diameter (4 dt) and corner bend radius."""
    dt = values["tieDiaMm"]
    return result(
        summary={"tieDiaMm": dt, "mandrelDiaMm": 4.0 * dt, "insideRadiusMm": 2.0 * dt},
        tables=[
            table(
                "Stirrup corner bend",
                [("item", "Item"), ("mm", "Value", "mm")],
                [
                    {"item": "Inside mandrel diameter (4 dt)", "mm": 4.0 * dt},
                    {"item": "Inside radius (2 dt)", "mm": 2.0 * dt},
                ],
            )
        ],
        notes=["Corner longitudinal bars must fit snugly inside the stirrup corner bend."],
    )


@feature(
    "settingsCodeValuesDetailing.closedTies",
    "Closed Ties",
    part="settings",
    fields=[
        number("memberDepthMm", "Column/beam core depth", 400.0, unit="mm", min=150.0),
        number("longBarDiaMm", "Smallest longitudinal bar db", 16.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def closed_ties(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute seismic closed hoop maximum spacing in plastic hinge confinement zones."""
    s_max = min(values["memberDepthMm"] / 4.0, 6.0 * values["longBarDiaMm"], 150.0)
    return result(
        summary={"maxHoopSpacingMm": s_max},
        tables=[
            table(
                "Seismic closed hoop spacing",
                [("criterion", "Criterion"), ("mm", "Spacing", "mm")],
                [
                    {"criterion": "d / 4", "mm": values["memberDepthMm"] / 4.0},
                    {"criterion": "6 db", "mm": 6.0 * values["longBarDiaMm"]},
                    {"criterion": "150 mm cap", "mm": 150.0},
                    {"criterion": "Governing max spacing", "mm": s_max},
                ],
            )
        ],
        notes=["Closed seismic hoops require 135° hooks anchored into the confined core."],
    )


@feature(
    "settingsCodeValuesDetailing.crosstieSpacing",
    "Crosstie Spacing",
    part="settings",
    fields=[
        number("coreWidthMm", "Confined core width bc", 370.0, unit="mm", min=100.0),
        number("hxMaxMm", "Max horizontal crosstie spacing hx", 350.0, unit="mm", min=150.0),
    ],
    requires_project=False,
)
def crosstie_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute required lateral crosstie count across a confined column or boundary-element core."""
    n_spaces = max(1, math.ceil(values["coreWidthMm"] / values["hxMaxMm"]))
    actual_hx = values["coreWidthMm"] / n_spaces
    return result(
        summary={"internalLegs": n_spaces + 1, "actualHxMm": actual_hx},
        tables=[
            table(
                "Lateral crosstie spacing",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Total legs across width", "value": n_spaces + 1},
                    {"metric": "Actual hx [mm]", "value": actual_hx},
                ],
            )
        ],
        notes=["Seismic confinement limits centre-to-centre leg spacing hx <= 350 mm."],
    )


@feature(
    "settingsCodeValuesDetailing.bundleLimit",
    "Bundle Limit",
    part="settings",
    fields=[
        number("barsInBundle", "Number of bars in bundle", 3.0, min=2.0, max=4.0),
        number("barMm", "Individual bar diameter db", 25.0, unit="mm", min=12.0, max=36.0),
    ],
    requires_project=False,
)
def bundle_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute equivalent single-bar diameter for bundled reinforcement and check bar limit."""
    n = int(values["barsInBundle"])
    db = values["barMm"]
    d_eq = db * math.sqrt(n)
    max_allowed = 4 if db <= 32.0 else 3
    return result(
        summary={"barsInBundle": n, "equivalentDiaMm": d_eq, "compliant": n <= max_allowed},
        tables=[
            table(
                "Bundled bar equivalent diameter",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Equivalent diameter db√n [mm]", "value": d_eq},
                    {"item": "Max bars allowed per bundle", "value": max_allowed},
                ],
            )
        ],
        notes=["Maximum 4 bars per bundle (limited to 3 for large bars > 32 mm)."],
    )


@feature(
    "settingsCodeValuesDetailing.barGrouping",
    "Bar Grouping",
    part="settings",
    fields=[
        number("beamWidthMm", "Beam web width bw", 350.0, unit="mm", min=200.0),
        number("coverMm", "Side clear cover", 40.0, unit="mm", min=20.0),
        number("stirrupMm", "Stirrup diameter", 10.0, unit="mm", min=6.0),
        number("barMm", "Main bar diameter", 20.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def bar_grouping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate maximum number of bars fitting in a single beam flexural layer."""
    avail = values["beamWidthMm"] - 2.0 * (values["coverMm"] + values["stirrupMm"])
    s_min = max(25.0, values["barMm"])
    n_max = max(1, int((avail + s_min) // (values["barMm"] + s_min)))
    return result(
        summary={"availableWidthMm": avail, "maxBarsPerLayer": n_max},
        tables=[
            table(
                "Single-layer bar capacity",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Inside-stirrup width [mm]", "value": avail},
                    {"metric": "Min clear gap [mm]", "value": s_min},
                    {"metric": "Max bars per layer", "value": n_max},
                ],
            )
        ],
        notes=[
            "Additional bars beyond single-layer capacity must be placed in a second row or bundled."
        ],
    )


@feature(
    "settingsCodeValuesDetailing.bundleSpacing",
    "Bundle Spacing",
    part="settings",
    fields=[
        number("equivalentDiaMm", "Bundle equivalent diameter d_eq", 43.3, unit="mm", min=15.0),
        number("aggregateMm", "Max aggregate size", 20.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def bundle_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine minimum clear spacing between adjacent bar bundles."""
    s_min = max(values["equivalentDiaMm"], 4.0 / 3.0 * values["aggregateMm"], 25.0)
    return result(
        summary={"minBundleClearMm": s_min},
        tables=[
            table(
                "Bundled bar clear spacing",
                [("item", "Item"), ("mm", "Value", "mm")],
                [
                    {"item": "Equivalent bundle diameter", "mm": values["equivalentDiaMm"]},
                    {"item": "Min clear spacing between bundles", "mm": s_min},
                ],
            )
        ],
        notes=[
            "Bundle spacing uses the equivalent bundle diameter db,eq in place of single bar db."
        ],
    )


@feature(
    "settingsCodeValuesDetailing.bundleClearance",
    "Bundle Clearance",
    part="settings",
    fields=[
        number("aggregateMm", "Nominal max aggregate size", 20.0, unit="mm", min=10.0),
        number("equivalentDiaMm", "Bundle equivalent diameter", 40.0, unit="mm", min=15.0),
    ],
    requires_project=False,
)
def bundle_clearance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify concrete cover and aggregate clearance around bundled reinforcement."""
    c_min = max(values["equivalentDiaMm"], 4.0 / 3.0 * values["aggregateMm"] + 10.0)
    return result(
        summary={
            "recommendedCoverMm": c_min,
            "aggregateClearMm": 4.0 / 3.0 * values["aggregateMm"],
        },
        tables=[
            table(
                "Bundle cover & aggregate clearance",
                [("metric", "Metric"), ("mm", "Value", "mm")],
                [
                    {"metric": "4/3 × aggregate size", "mm": 4.0 / 3.0 * values["aggregateMm"]},
                    {"metric": "Recommended cover to bundle", "mm": c_min},
                ],
            )
        ],
        notes=["Cover to bundled bars should be at least the equivalent diameter."],
    )


@feature(
    "settingsCodeValuesDetailing.spliceLocation",
    "Splice Location",
    part="settings",
    fields=[
        number("spanM", "Clear beam span L", 6.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def splice_location(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Identify permitted flexural top and bottom lap splice zones along a beam span."""
    l_m = values["spanM"]
    rows = [
        {
            "bars": "Top longitudinal bars",
            "zone": "Middle third (0.33L to 0.67L)",
            "startM": 0.33 * l_m,
            "endM": 0.67 * l_m,
        },
        {
            "bars": "Bottom longitudinal bars",
            "zone": "Away from plastic hinge (> 2h from face)",
            "startM": 0.15 * l_m,
            "endM": 0.35 * l_m,
        },
    ]
    return result(
        summary={"spanM": l_m, "topSpliceZoneStartM": 0.33 * l_m, "topSpliceZoneEndM": 0.67 * l_m},
        tables=[
            table(
                "Permitted beam splice zones",
                [("bars", "Bars"), ("zone", "Zone"), ("startM", "From", "m"), ("endM", "To", "m")],
                rows,
            )
        ],
        notes=["Avoid splicing bars at peak moment sections and seismic plastic hinge zones."],
    )


@feature(
    "settingsCodeValuesDetailing.staggerDistance",
    "Stagger Distance",
    part="settings",
    fields=[
        number("lapMm", "Design lap splice length l0", 850.0, unit="mm", min=300.0),
    ],
    requires_project=False,
)
def stagger_distance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute required clear/centre stagger offset between adjacent tension splices."""
    center_offset = 1.3 * values["lapMm"]
    clear_gap = 0.3 * values["lapMm"]
    return result(
        summary={"centerOffsetMm": center_offset, "clearEndGapMm": clear_gap},
        tables=[
            table(
                "Splice stagger offsets",
                [("metric", "Metric"), ("mm", "Distance", "mm")],
                [
                    {"metric": "Center-to-center stagger (1.3 l0)", "mm": center_offset},
                    {"metric": "Clear gap between splice ends", "mm": clear_gap},
                ],
            )
        ],
        notes=["Minimum 0.3 l0 clear longitudinal gap separates staggered lap zones."],
    )


@feature(
    "settingsCodeValuesDetailing.contactSplice",
    "Contact Splice",
    part="settings",
    fields=[
        number("lapMm", "Lap length", 800.0, unit="mm", min=300.0),
        number(
            "transverseSpacingMm",
            "Center-to-center spacing of non-contact bars",
            100.0,
            unit="mm",
            min=0.0,
        ),
    ],
    requires_project=False,
)
def contact_splice(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check non-contact lap splice spacing limit against min(l0/5, 150 mm)."""
    lim = min(values["lapMm"] / 5.0, 150.0)
    return result(
        summary={"maxAllowedOffsetMm": lim, "compliant": values["transverseSpacingMm"] <= lim},
        tables=[
            table(
                "Contact / non-contact splice check",
                [("item", "Item"), ("mm", "Value", "mm")],
                [
                    {"item": "Provided transverse offset", "mm": values["transverseSpacingMm"]},
                    {"item": "Max permitted offset", "mm": lim},
                ],
            )
        ],
        notes=["Contact laps are preferred to eliminate transverse splitting struts."],
    )


@feature(
    "settingsCodeValuesDetailing.lapOffset",
    "Lap Offset",
    part="settings",
    fields=[
        number("barMm", "Bar diameter db", 20.0, unit="mm", min=10.0),
        number("crankSlope", "Crank slope (run / offset)", 6.0, min=4.0, max=12.0),
    ],
    requires_project=False,
)
def lap_offset(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cranked column-splice bar offset slope and horizontal reaction check."""
    offset = values["barMm"]
    crank_len = offset * values["crankSlope"]
    return result(
        summary={
            "transverseOffsetMm": offset,
            "crankLengthMm": crank_len,
            "slopeCompliant": values["crankSlope"] >= 6.0,
        },
        tables=[
            table(
                "Column splice offset bend",
                [("metric", "Metric"), ("mm", "Value", "mm")],
                [
                    {"metric": "Bar offset (1 db)", "mm": offset},
                    {"metric": "Crank transition length", "mm": crank_len},
                ],
            )
        ],
        notes=[
            "Offset bent longitudinal bars must have slope <= 1:6 and lateral ties at both bend points."
        ],
    )
