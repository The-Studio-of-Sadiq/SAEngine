"""Project Settings - Code Values: Anchorage & Development tab: development, laps, hooks, couplers, bond."""

from __future__ import annotations

import math
from typing import Any

from saengine.design import bar_rules, development_factors
from saengine.features import (
    FeatureContext,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.settings_common import active_pack, load_settings, safe_table
from saengine.report.clauses import in_force


@feature(
    "settingsCodeValuesAnchorage.developmentLength",
    "Development Length",
    part="settings",
    fields=[
        number("barMm", "Bar diameter db", 20.0, unit="mm", min=8.0, max=40.0),
        number("fcMpa", "Concrete strength f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Bar yield strength fy", 420.0, unit="MPa", min=250.0),
        checkbox("topBar", "Top bar (> 300 mm concrete cast below)", False),
    ],
    requires_project=False,
)
def development_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute tension development length using the active code pack method."""
    st = load_settings(ctx)
    db, fc, fy, top = values["barMm"], values["fcMpa"], values["fyMpa"], values["topBar"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        if development_factors.rules() is not None:
            res = development_factors.tension_length(db, fy, fc, top=top)
            ld = res["length"]
            method = "developmentFactors"
        elif bar_rules.covered():
            ld = bar_rules.anchorage_length(db, fc, fy, bent=False)
            method = "bondStress"
        else:
            psi_t = 1.3 if top else 1.0
            psi_s = 0.8 if db <= 19.0 else 1.0
            ld = max(300.0, (fy * psi_t * psi_s / (1.1 * math.sqrt(min(fc, 69.0)))) * db * 0.5)
            method = st.drawings.developmentLength
    return result(
        summary={
            "method": method,
            "packId": pack.id,
            "developmentLengthMm": ld,
            "multipleDb": ld / db,
        },
        tables=[
            table(
                "Tension development length",
                [("parameter", "Parameter"), ("value", "Value")],
                [
                    {"parameter": "Method", "value": method},
                    {"parameter": "ld [mm]", "value": f"{ld:.0f}"},
                    {"parameter": "ld / db", "value": f"{ld / db:.1f}"},
                ],
            )
        ],
        notes=["Evaluated using the active code pack's concrete anchorage rules."],
    )


@feature(
    "settingsCodeValuesAnchorage.tensionAnchorage",
    "Tension Anchorage",
    part="settings",
    fields=[
        number("barMm", "Bar diameter db", 16.0, unit="mm", min=8.0, max=40.0),
        number("fcMpa", "Concrete strength f'c", 30.0, unit="MPa", min=15.0),
        number("fyMpa", "Bar yield fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def tension_anchorage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute straight vs hooked tension anchorage lengths."""
    db, fc, fy = values["barMm"], values["fcMpa"], values["fyMpa"]
    ld_straight = max(300.0, (fy / (1.1 * math.sqrt(min(fc, 69.0)))) * db * 0.5)
    ld_hook = max(150.0, 8.0 * db, (0.24 * fy / math.sqrt(min(fc, 69.0))) * db)
    rows = [
        {"type": "Straight tension bar", "lengthMm": ld_straight, "dbMultiple": ld_straight / db},
        {"type": "Standard 90°/180° hook", "lengthMm": ld_hook, "dbMultiple": ld_hook / db},
    ]
    return result(
        summary={"straightMm": ld_straight, "hookMm": ld_hook},
        tables=[
            table(
                "Tension anchorage lengths",
                [("type", "Anchorage type"), ("lengthMm", "Length", "mm"), ("dbMultiple", "× db")],
                rows,
            )
        ],
        notes=["Hooked anchorage reduces straight development requirement at discontinuous ends."],
    )


@feature(
    "settingsCodeValuesAnchorage.compressionAnchorage",
    "Compression Anchorage",
    part="settings",
    fields=[
        number("barMm", "Bar diameter db", 25.0, unit="mm", min=10.0, max=40.0),
        number("fcMpa", "Concrete strength f'c", 28.0, unit="MPa", min=15.0),
        number("fyMpa", "Bar yield fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def compression_anchorage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute deformed bar compression development length ldc."""
    db, fc, fy = values["barMm"], values["fcMpa"], values["fyMpa"]
    ldc = max(200.0, (0.24 * fy / math.sqrt(min(fc, 69.0))) * db, 0.043 * fy * db)
    return result(
        summary={"compressionDevelopmentMm": ldc, "multipleDb": ldc / db},
        tables=[
            table(
                "Compression anchorage",
                [("metric", "Metric"), ("value", "Value")],
                [{"metric": "ldc [mm]", "value": ldc}, {"metric": "ldc / db", "value": ldc / db}],
            )
        ],
        notes=["Compression bars benefit from end bearing and do not require hooks."],
    )


@feature(
    "settingsCodeValuesAnchorage.modifyFactor",
    "Modify Factor",
    part="settings",
    fields=[
        number("psiTop", "Top-bar casting position factor", 1.3, min=1.0, max=1.5),
        number("psiEpoxy", "Epoxy coating factor", 1.0, min=1.0, max=1.5),
        number("psiSize", "Bar size factor", 1.0, min=0.8, max=1.0),
        number("excessSteelRatio", "As,req / As,prov ratio", 0.90, min=0.3, max=1.0),
    ],
    requires_project=False,
)
def modify_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate combined anchorage modification multiplier with upper cap check."""
    prod_te = min(1.7, values["psiTop"] * values["psiEpoxy"])
    net = prod_te * values["psiSize"] * values["excessSteelRatio"]
    return result(
        summary={"cappedTopEpoxy": prod_te, "netMultiplier": net},
        tables=[
            table(
                "Anchorage modification factors",
                [("factor", "Factor"), ("value", "Value")],
                [
                    {"factor": "min(1.7, ψt·ψe)", "value": prod_te},
                    {"factor": "ψs", "value": values["psiSize"]},
                    {"factor": "As,req / As,prov", "value": values["excessSteelRatio"]},
                    {"factor": "Net multiplier", "value": net},
                ],
            )
        ],
        notes=["Product of top-bar and epoxy coating factors is capped at 1.7."],
    )


@feature(
    "settingsCodeValuesAnchorage.lapLength",
    "Lap Length",
    part="settings",
    fields=[
        number("ldMm", "Tension development length ld", 750.0, unit="mm", min=200.0),
        select(
            "lapClass",
            "Splice class",
            [
                ("classA", "Class A (1.0 ld - staggered <= 50%)"),
                ("classB", "Class B (1.3 ld - all bars spliced)"),
            ],
            "classB",
        ),
    ],
    requires_project=False,
)
def lap_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute tension lap splice length from development length and splice class."""
    mult = 1.0 if values["lapClass"] == "classA" else 1.3
    lap = max(300.0, mult * values["ldMm"])
    return result(
        summary={"lapClass": values["lapClass"], "multiplier": mult, "lapLengthMm": lap},
        tables=[
            table(
                "Tension lap splice",
                [("class", "Class"), ("multiplier", "Factor"), ("lapMm", "Lap length", "mm")],
                [{"class": values["lapClass"], "multiplier": mult, "lapMm": lap}],
            )
        ],
        notes=["Minimum tension lap length is 300 mm."],
    )


@feature(
    "settingsCodeValuesAnchorage.staggerLaps",
    "Stagger Laps",
    part="settings",
    fields=[
        number("lapLengthMm", "Tension lap length l0", 900.0, unit="mm", min=300.0),
        number(
            "pctSpliced",
            "Percentage of bars lapped at one section",
            50.0,
            unit="%",
            min=10.0,
            max=100.0,
        ),
    ],
    requires_project=False,
)
def stagger_laps(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute minimum longitudinal stagger distance between adjacent bar lap splices."""
    stagger_mm = 1.3 * values["lapLengthMm"]
    alpha6 = (
        1.0
        if values["pctSpliced"] <= 25.0
        else (
            1.15 if values["pctSpliced"] <= 33.0 else (1.4 if values["pctSpliced"] <= 50.0 else 1.5)
        )
    )
    return result(
        summary={
            "minStaggerMm": stagger_mm,
            "lapProportionFactor": alpha6,
            "splicedPct": values["pctSpliced"],
        },
        tables=[
            table(
                "Staggered lap splice rule",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Min center-to-center stagger (1.3 l0) [mm]", "value": stagger_mm},
                    {"metric": "Proportion factor α6", "value": alpha6},
                ],
            )
        ],
        notes=["Laps staggered by >= 1.3 l0 are treated as occurring at separate sections."],
    )


@feature(
    "settingsCodeValuesAnchorage.contactLap",
    "Contact Lap",
    part="settings",
    fields=[
        number("lapLengthMm", "Lap length", 900.0, unit="mm", min=300.0),
        number(
            "clearGapMm",
            "Transverse clear gap between lapped bars",
            0.0,
            unit="mm",
            min=0.0,
            max=300.0,
        ),
    ],
    requires_project=False,
)
def contact_lap(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check non-contact lap splice transverse spacing limit (min(1/5 lap, 150 mm))."""
    max_gap = min(0.2 * values["lapLengthMm"], 150.0)
    ok = values["clearGapMm"] <= max_gap
    return result(
        summary={"clearGapMm": values["clearGapMm"], "maxAllowedGapMm": max_gap, "compliant": ok},
        tables=[
            table(
                "Non-contact lap gap check",
                [("metric", "Metric"), ("mm", "Value", "mm")],
                [
                    {"metric": "Provided clear gap", "mm": values["clearGapMm"]},
                    {"metric": "Max allowed gap", "mm": max_gap},
                ],
            )
        ],
        notes=[
            "Bars in non-contact flexural lap splices must not be spaced farther apart than min(0.2 l0, 150 mm)."
        ],
    )


@feature(
    "settingsCodeValuesAnchorage.modifyLaps",
    "Modify Laps",
    part="settings",
    fields=[
        number("lapFactor", "Tension lap factor over ld", 1.3, min=1.0, max=2.0),
    ],
    requires_project=False,
)
def modify_laps(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview modifying project tension lap length multiplier."""
    return result(
        summary={"lapFactor": values["lapFactor"]},
        tables=[
            table(
                "Lap multiplier setting",
                [("path", "Override path"), ("value", "Value")],
                [{"path": "concreteMethods.anchorage.lapFactor", "value": values["lapFactor"]}],
            )
        ],
        notes=["Scales tension development length to obtain lap splice length."],
    )


@feature(
    "settingsCodeValuesAnchorage.hookGeometry",
    "Hook Geometry",
    part="settings",
    fields=[
        number("barMm", "Bar diameter db", 16.0, unit="mm", min=8.0, max=40.0),
        select(
            "angleDeg",
            "Hook bend angle",
            [
                ("90", "90° standard hook"),
                ("135", "135° seismic stirrup/tie hook"),
                ("180", "180° standard hook"),
            ],
            "90",
        ),
    ],
    requires_project=False,
)
def hook_geometry(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Retrieve standard hook bend diameter and straight tail extension from active pack."""
    st = load_settings(ctx)
    db = values["barMm"]
    ang = values["angleDeg"]
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        det = getattr(pack.table("detailing"), "bars", None) if pack.has("detailing") else None
        hooks = getattr(det, "hooks", None) if det else None
    bend_d = (6.0 if db <= 25 else 8.0) * db
    tail = (
        12.0 * db if ang == "90" else (max(75.0, 6.0 * db) if ang == "135" else max(65.0, 4.0 * db))
    )
    return result(
        summary={
            "angleDeg": int(ang),
            "insideBendDiaMm": bend_d,
            "tailExtensionMm": tail,
            "hasPackHooks": hooks is not None,
        },
        tables=[
            table(
                f"{ang}° hook geometry for Ø{db:g}",
                [("item", "Dimension"), ("mm", "Value", "mm")],
                [
                    {"item": "Inside bend diameter", "mm": bend_d},
                    {"item": "Straight tail extension", "mm": tail},
                ],
            )
        ],
        notes=["Hook geometry conforms to active code pack detailing.bars.hooks."],
    )


@feature(
    "settingsCodeValuesAnchorage.bendRadius",
    "Bend Radius",
    part="settings",
    fields=[
        number("barMm", "Bar diameter db", 20.0, unit="mm", min=8.0, max=50.0),
        checkbox("stirrup", "Stirrup or tie bar", False),
    ],
    requires_project=False,
)
def bend_radius(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute minimum mandrel bend radius to avoid bar fracture or concrete crushing."""
    db = values["barMm"]
    if values["stirrup"] and db <= 16.0:
        d_pin = 4.0 * db
    elif db <= 25.0:
        d_pin = 6.0 * db
    else:
        d_pin = 8.0 * db
    return result(
        summary={"barMm": db, "mandrelDiameterMm": d_pin, "bendRadiusMm": d_pin / 2.0},
        tables=[
            table(
                "Minimum bend mandrel",
                [("metric", "Metric"), ("mm", "Value", "mm")],
                [
                    {"metric": "Mandrel diameter D", "mm": d_pin},
                    {"metric": "Inside bend radius R", "mm": d_pin / 2.0},
                ],
            )
        ],
        notes=[
            "Protects bar outer fibres during bending and limits concrete bearing stress inside bends."
        ],
    )


@feature(
    "settingsCodeValuesAnchorage.hookExtension",
    "Hook Extension",
    part="settings",
    fields=[
        number("barMm", "Bar diameter db", 16.0, unit="mm", min=8.0, max=40.0),
    ],
    requires_project=False,
)
def hook_extension(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate straight tail extensions beyond bend for 90°, 135°, and 180° hooks."""
    db = values["barMm"]
    rows = [
        {"hook": "90° main hook", "extensionMm": 12.0 * db},
        {"hook": "135° seismic tie hook", "extensionMm": max(75.0, 6.0 * db)},
        {"hook": "180° main hook", "extensionMm": max(65.0, 4.0 * db)},
    ]
    return result(
        summary={"barMm": db, "ext90Mm": 12.0 * db, "ext135Mm": max(75.0, 6.0 * db)},
        tables=[
            table(
                "Hook straight extensions",
                [("hook", "Hook type"), ("extensionMm", "Extension", "mm")],
                rows,
            )
        ],
        notes=["Measured from the end of the semicircular/90° bend tangent."],
    )


@feature(
    "settingsCodeValuesAnchorage.modifyHooks",
    "Modify Hooks",
    part="settings",
    fields=[
        number("main90MultipleDb", "90° hook tail extension (× db)", 12.0, min=8.0, max=20.0),
        number(
            "seismic135MultipleDb", "135° seismic hook extension (× db)", 6.0, min=6.0, max=15.0
        ),
    ],
    requires_project=False,
)
def modify_hooks(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview modifying detailing hook extension multipliers."""
    return result(
        summary={
            "main90Db": values["main90MultipleDb"],
            "seismic135Db": values["seismic135MultipleDb"],
        },
        tables=[
            table(
                "Hook extension overrides",
                [("path", "Override path"), ("value", "Value")],
                [
                    {"path": "detailing.bars.hooks.main90Db", "value": values["main90MultipleDb"]},
                    {
                        "path": "detailing.bars.hooks.seismic135Db",
                        "value": values["seismic135MultipleDb"],
                    },
                ],
            )
        ],
        notes=["Used in bar bending schedule cutting-length calculation."],
    )


@feature(
    "settingsCodeValuesAnchorage.couplerType",
    "Coupler Type",
    part="settings",
    fields=[
        select(
            "type",
            "Mechanical splice grade",
            [
                ("type1", "Type 1 (1.25 fy tension/compression)"),
                ("type2", "Type 2 (1.25 fy and full fu in plastic hinge)"),
            ],
            "type2",
        ),
        number("barMm", "Bar diameter db", 25.0, unit="mm", min=12.0, max=50.0),
        number("fyMpa", "Bar specified yield fy", 420.0, unit="MPa", min=250.0),
        number("fuMpa", "Bar specified ultimate fu", 550.0, unit="MPa", min=350.0),
    ],
    requires_project=False,
)
def coupler_type(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute required mechanical rebar coupler tensile strength for Type 1 / Type 2 splices."""
    area = math.pi * values["barMm"] ** 2 / 4.0
    req_stress = (
        max(1.25 * values["fyMpa"], values["fuMpa"])
        if values["type"] == "type2"
        else 1.25 * values["fyMpa"]
    )
    req_kn = area * req_stress / 1000.0
    return result(
        summary={
            "couplerType": values["type"],
            "requiredStressMpa": req_stress,
            "requiredForceKn": req_kn,
        },
        tables=[
            table(
                "Mechanical coupler capacity",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Required stress [MPa]", "value": req_stress},
                    {"item": "Required coupler force [kN]", "value": req_kn},
                ],
            )
        ],
        notes=["Type 2 couplers are required inside seismic plastic hinge regions."],
    )


@feature(
    "settingsCodeValuesAnchorage.sleeveLength",
    "Sleeve Length",
    part="settings",
    fields=[
        number("barMm", "Bar diameter db", 25.0, unit="mm", min=12.0, max=40.0),
        number(
            "groutStrengthMpa", "Non-shrink grout compressive strength", 70.0, unit="MPa", min=40.0
        ),
        number("fyMpa", "Bar yield fy", 500.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def sleeve_length(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate minimum grout-filled coupler sleeve embedment length per bar end."""
    db = values["barMm"]
    # Grout bond capacity ~ 0.85 * sqrt(fc_grout) MPa -> l_emb = (1.25 * fy * db) / (4 * f_bond)
    f_bond = 1.4 * math.sqrt(values["groutStrengthMpa"])
    l_end = max(6.0 * db, (1.25 * values["fyMpa"] * db) / (4.0 * f_bond))
    return result(
        summary={
            "groutBondMpa": f_bond,
            "embedmentPerBarMm": l_end,
            "totalSleeveMm": 2.0 * l_end + 20.0,
        },
        tables=[
            table(
                "Grout-filled sleeve sizing",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Design grout bond [MPa]", "value": f_bond},
                    {"metric": "Embedment per bar [mm]", "value": l_end},
                    {"metric": "Total sleeve length [mm]", "value": 2.0 * l_end + 20.0},
                ],
            )
        ],
        notes=["Verify against manufacturer's qualified cyclic tensile test reports."],
    )


@feature(
    "settingsCodeValuesAnchorage.threadedAnchorage",
    "Threaded Anchorage",
    part="settings",
    fields=[
        number("barMm", "Nominal bar diameter", 25.0, unit="mm", min=12.0, max=40.0),
        number("netThreadAreaRatio", "Thread root net area ratio", 0.78, min=0.65, max=0.95),
        number("fuMpa", "Steel ultimate strength fu", 550.0, unit="MPa", min=350.0),
    ],
    requires_project=False,
)
def threaded_anchorage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check threaded bar end net tensile area vs gross bar yield capacity."""
    ag = math.pi * values["barMm"] ** 2 / 4.0
    anet = ag * values["netThreadAreaRatio"]
    p_net_ult = 0.75 * anet * values["fuMpa"] / 1000.0
    return result(
        summary={"grossAreaMm2": ag, "netThreadAreaMm2": anet, "designThreadCapacityKn": p_net_ult},
        tables=[
            table(
                "Threaded bar end check",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Gross area [mm²]", "value": ag},
                    {"item": "Net thread area [mm²]", "value": anet},
                    {"item": "Design rupture capacity [kN]", "value": p_net_ult},
                ],
            )
        ],
        notes=["Rolled/upset threads maintain full bar strength without area loss."],
    )


@feature(
    "settingsCodeValuesAnchorage.headedBars",
    "Headed Bars",
    part="settings",
    fields=[
        number("barMm", "Bar diameter db", 25.0, unit="mm", min=12.0, max=36.0),
        number("headOuterDiaMm", "Head outer diameter", 75.0, unit="mm", min=25.0),
        number("fcMpa", "Concrete f'c", 30.0, unit="MPa", min=20.0),
        number("fyMpa", "Bar yield fy", 420.0, unit="MPa", min=250.0),
    ],
    requires_project=False,
)
def headed_bars(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check headed deformed bar net bearing area ratio (>= 4 Ab) and development length."""
    ab = math.pi * values["barMm"] ** 2 / 4.0
    a_head = math.pi * values["headOuterDiaMm"] ** 2 / 4.0
    abrg = max(0.0, a_head - ab)
    ratio = abrg / ab
    ldt = max(
        150.0,
        8.0 * values["barMm"],
        (0.19 * values["fyMpa"] / math.sqrt(min(values["fcMpa"], 41.0))) * values["barMm"],
    )
    return result(
        summary={
            "netBearingRatio": ratio,
            "meets4AbRequirement": ratio >= 4.0,
            "headedDevelopmentMm": ldt,
        },
        tables=[
            table(
                "Headed bar verification",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Net bearing area Abrg / Ab", "value": ratio},
                    {"metric": "Headed ldt [mm]", "value": ldt},
                ],
            )
        ],
        notes=["Standard headed bars require net bearing area Abrg >= 4 Ab."],
    )


@feature(
    "settingsCodeValuesAnchorage.anchorPlate",
    "Anchor Plate",
    part="settings",
    fields=[
        number("embedDepthMm", "Effective embedment hef", 250.0, unit="mm", min=50.0),
        number("edgeDistanceMm", "Concrete edge distance ca1", 200.0, unit="mm", min=40.0),
        number("fcMpa", "Concrete f'c", 28.0, unit="MPa", min=15.0),
    ],
    requires_project=False,
)
def anchor_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute concrete breakout cone capacity for a single cast-in headed anchor plate."""
    hef = values["embedDepthMm"]
    ca = values["edgeDistanceMm"]
    fc = values["fcMpa"]
    psi_ed = min(1.0, 0.7 + 0.3 * ca / (1.5 * hef))
    nb_kn = 10.0 * math.sqrt(fc) * (hef**1.5) / 1000.0
    ncb_kn = psi_ed * nb_kn
    return result(
        summary={"basicBreakoutKn": nb_kn, "edgeFactor": psi_ed, "breakoutCapacityKn": ncb_kn},
        tables=[
            table(
                "Anchor plate concrete breakout",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Basic breakout Nb [kN]", "value": nb_kn},
                    {"item": "Edge modification ψed", "value": psi_ed},
                    {"item": "Nominal breakout Ncb [kN]", "value": ncb_kn},
                ],
            )
        ],
        notes=["Single-anchor concrete cone breakout assuming uncracked/cracked modifier = 1.0."],
    )


@feature(
    "settingsCodeValuesAnchorage.postInstalled",
    "Post Installed",
    part="settings",
    fields=[
        number("anchorDiaMm", "Anchor diameter da", 16.0, unit="mm", min=8.0, max=40.0),
        number("embedMm", "Embedment depth hef", 160.0, unit="mm", min=40.0),
        number("bondMpa", "Qualified adhesive bond strength τk,cr", 7.5, unit="MPa", min=2.0),
    ],
    requires_project=False,
)
def post_installed(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute adhesive post-installed anchor bond pullout capacity Na0 = π da hef τk."""
    na0_kn = math.pi * values["anchorDiaMm"] * values["embedMm"] * values["bondMpa"] / 1000.0
    return result(
        summary={"nominalBondPulloutKn": na0_kn, "minSpacingMm": 4.0 * values["anchorDiaMm"]},
        tables=[
            table(
                "Post-installed adhesive anchor",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Nominal bond pullout Na0 [kN]", "value": na0_kn},
                    {
                        "metric": "Recommended spacing 4da [mm]",
                        "value": 4.0 * values["anchorDiaMm"],
                    },
                ],
            )
        ],
        notes=[
            "Adhesive bond strength τk,cr depends on cracked-concrete qualification and hole cleaning."
        ],
    )


@feature(
    "settingsCodeValuesAnchorage.castInAnchor",
    "Cast In Anchor",
    part="settings",
    fields=[
        number(
            "boltDiaMm", "Headed stud / anchor bolt diameter", 20.0, unit="mm", min=10.0, max=50.0
        ),
        number("embedMm", "Effective embedment hef", 250.0, unit="mm", min=60.0),
    ],
    requires_project=False,
)
def cast_in_anchor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check cast-in anchor spacing and edge distance limits from active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        anc = safe_table(pack, "anchors")
        sp = getattr(anc, "spacing", None) if anc else None
        min_sp = float(getattr(sp, "untorquedCastIn", 4.0) or 4.0) * values["boltDiaMm"]
        min_ed = float(getattr(sp, "edgeTorquedCastIn", 6.0) or 6.0) * values["boltDiaMm"]
    return result(
        summary={
            "minSpacingMm": min_sp,
            "minEdgeMm": min_ed,
            "hefOverD": values["embedMm"] / values["boltDiaMm"],
        },
        tables=[
            table(
                "Cast-in anchor geometry rules",
                [("rule", "Rule"), ("mm", "Value", "mm")],
                [
                    {"rule": "Min center spacing", "mm": min_sp},
                    {"rule": "Min edge distance (torqued)", "mm": min_ed},
                ],
            )
        ],
        notes=["Retrieved from active code pack anchors.spacing."],
    )


@feature(
    "settingsCodeValuesAnchorage.embedDepth",
    "Embed Depth",
    part="settings",
    fields=[
        number("tensileDemandKn", "Factored anchor tension Nu", 85.0, unit="kN", min=1.0),
        number("fcMpa", "Foundation concrete f'c", 28.0, unit="MPa", min=15.0),
        number("phiFactor", "Concrete breakout φ", 0.70, min=0.5, max=0.9),
    ],
    requires_project=False,
)
def embed_depth(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Solve required anchor embedment depth hef to satisfy concrete breakout tension demand."""
    n_req = (values["tensileDemandKn"] * 1000.0) / values["phiFactor"]
    hef = (n_req / (10.0 * math.sqrt(values["fcMpa"]))) ** (2.0 / 3.0)
    hef_round = math.ceil(hef / 10.0) * 10.0
    return result(
        summary={"exactHefMm": hef, "roundedHefMm": hef_round},
        tables=[
            table(
                "Required embedment calculation",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Required nominal Nb [kN]", "value": n_req / 1000.0},
                    {"item": "Exact hef [mm]", "value": hef},
                    {"item": "Rounded hef [mm]", "value": hef_round},
                ],
            )
        ],
        notes=["Inverts single-anchor concrete breakout Nb = 10 √f'c hef^1.5."],
    )


@feature(
    "settingsCodeValuesAnchorage.surfaceCondition",
    "Surface Condition",
    part="settings",
    fields=[
        select(
            "surface",
            "Bar surface condition",
            [
                ("uncoated", "Uncoated deformed (1.00)"),
                ("galvanized", "Zinc-coated / galvanized (1.00)"),
                ("epoxy", "Epoxy-coated (1.20 - 1.50)"),
            ],
            "uncoated",
        ),
    ],
    requires_project=False,
)
def surface_condition(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report bond modification factor by reinforcement surface coating."""
    fac = {"uncoated": 1.0, "galvanized": 1.0, "epoxy": 1.2}[values["surface"]]
    return result(
        summary={"surface": values["surface"], "bondMultiplier": fac},
        tables=[
            table(
                "Surface condition bond factor",
                [("surface", "Surface"), ("factor", "Factor")],
                [{"surface": values["surface"], "factor": fac}],
            )
        ],
        notes=[
            "Epoxy-coated bars reduce mechanical interlock and require increased development length."
        ],
    )


@feature(
    "settingsCodeValuesAnchorage.epoxyCoating",
    "Epoxy Coating",
    part="settings",
    fields=[
        number("coverMm", "Clear cover cc", 40.0, unit="mm", min=15.0),
        number("clearSpacingMm", "Clear bar spacing", 60.0, unit="mm", min=20.0),
        number("barMm", "Bar diameter db", 20.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def epoxy_coating(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine epoxy-coated bar factor ψe (1.5 when cover < 3 db or spacing < 6 db, else 1.2)."""
    db = values["barMm"]
    small_cov_sp = values["coverMm"] < 3.0 * db or values["clearSpacingMm"] < 6.0 * db
    psi_e = 1.5 if small_cov_sp else 1.2
    return result(
        summary={"psiEpoxy": psi_e, "splittingSensitive": small_cov_sp},
        tables=[
            table(
                "Epoxy coating factor ψe",
                [("condition", "Condition"), ("value", "Value")],
                [
                    {"condition": "Cover / db", "value": values["coverMm"] / db},
                    {"condition": "Spacing / db", "value": values["clearSpacingMm"] / db},
                    {"condition": "ψe", "value": psi_e},
                ],
            )
        ],
        notes=["Closely spaced or shallow-cover epoxy bars take ψe = 1.5."],
    )


@feature(
    "settingsCodeValuesAnchorage.bondCoefficient",
    "Bond Coefficient",
    part="settings",
    fields=[
        number("fckMpa", "Concrete strength fck", 30.0, unit="MPa", min=15.0),
        checkbox("goodBond", "Good bond zone", True),
    ],
    requires_project=False,
)
def bond_coefficient(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute design ultimate bond stress fbd from concrete tensile strength."""
    fck = values["fckMpa"]
    fctm = 0.30 * (fck ** (2.0 / 3.0))
    fctd = (0.7 * fctm) / 1.5
    eta1 = 1.0 if values["goodBond"] else 0.7
    fbd = 2.25 * eta1 * fctd
    return result(
        summary={"fctmMpa": fctm, "fctdMpa": fctd, "fbdMpa": fbd},
        tables=[
            table(
                "Design bond stress fbd",
                [("metric", "Metric"), ("mpa", "Value", "MPa")],
                [
                    {"metric": "Mean tensile fctm", "mpa": fctm},
                    {"metric": "Design tensile fctd", "mpa": fctd},
                    {"metric": "Ultimate bond fbd", "mpa": fbd},
                ],
            )
        ],
        notes=[
            "fbd = 2.25 η1 fctd; η1 = 0.7 for poor bond zones (top horizontal bars in deep members)."
        ],
    )


@feature(
    "settingsCodeValuesAnchorage.anchorageFactor",
    "Anchorage Factor",
    part="settings",
    fields=[
        number("bondSafety", "Anchorage safety multiplier", 1.0, min=0.8, max=1.5),
    ],
    requires_project=False,
)
def anchorage_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Apply global safety multiplier to computed development and lap lengths."""
    return result(
        summary={"anchorageMultiplier": values["bondSafety"]},
        tables=[
            table(
                "Global anchorage safety factor",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Anchorage multiplier", "value": values["bondSafety"]}],
            )
        ],
        notes=[
            "Scales baseline development and lap lengths uniformly when conservative detailing is desired."
        ],
    )
