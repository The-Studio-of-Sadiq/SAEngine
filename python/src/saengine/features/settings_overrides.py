"""Project Settings - Code Overrides & Precision tab: codeOverrides inspection, partial factor overrides, precision."""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.codes import overrides
from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.settings_common import active_pack, load_settings, safe_table
from saengine.report.clauses import in_force


@feature(
    "settingsOverrides.decimalPlaces",
    "Decimal Places",
    part="settings",
    fields=[
        number("lengthDec", "Length decimals", 3.0, min=0.0, max=6.0),
        number("forceDec", "Force decimals", 1.0, min=0.0, max=6.0),
        number("stressDec", "Stress decimals", 2.0, min=0.0, max=6.0),
        number("ratioDec", "Utilisation ratio decimals", 3.0, min=1.0, max=6.0),
    ],
    requires_project=False,
)
def decimal_places(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Configure and preview display decimal places per engineering quantity."""
    st = load_settings(ctx)
    samples = [
        ("Length", 12.34567, "m", int(values["lengthDec"])),
        ("Force", 1456.789, "kN", int(values["forceDec"])),
        ("Stress", 28.4567, "MPa", int(values["stressDec"])),
        ("Utilisation", 0.84732, "-", int(values["ratioDec"])),
    ]
    rows = [
        {"quantity": q, "raw": raw, "decimals": dec, "formatted": f"{raw:.{dec}f} {u}".strip()}
        for q, raw, u, dec in samples
    ]
    return result(
        summary={
            "unitSystem": st.units.system,
            "lengthDecimals": int(values["lengthDec"]),
            "forceDecimals": int(values["forceDec"]),
            "stressDecimals": int(values["stressDec"]),
        },
        tables=[
            table(
                "Quantity decimal precision",
                [
                    ("quantity", "Quantity"),
                    ("raw", "Raw"),
                    ("decimals", "Decimals"),
                    ("formatted", "Preview"),
                ],
                rows,
            )
        ],
        notes=["Display rounding never alters stored SI engineering values."],
    )


@feature(
    "settingsOverrides.roundingRules",
    "Rounding Rules",
    part="settings",
    fields=[
        number("sampleQuantity", "Sample quantity", 12.345, min=0.0),
        number("step", "Rounding increment", 0.05, min=0.0001),
        select(
            "mode",
            "Rounding rule",
            [
                ("nearest", "Nearest increment"),
                ("up", "Always round up (conservative)"),
                ("down", "Always round down"),
            ],
            "up",
        ),
    ],
    requires_project=False,
)
def rounding_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate quantity rounding rules (nearest, ceiling, or floor) to an increment."""
    val = values["sampleQuantity"]
    step = values["step"]
    mode = values["mode"]
    if mode == "up":
        rounded = math.ceil(val / step - 1e-12) * step
    elif mode == "down":
        rounded = math.floor(val / step + 1e-12) * step
    else:
        rounded = round(val / step) * step
    rows = [
        {"rule": "Original value", "result": val},
        {"rule": f"Rounded ({mode}, step={step:g})", "result": rounded},
    ]
    return result(
        summary={"originalValue": val, "roundedValue": rounded, "delta": rounded - val},
        tables=[table("Rounding evaluation", [("rule", "Rule"), ("result", "Value")], rows)],
        notes=["Upward rounding is typical for rebar area requirements and BOQ wastage."],
    )


@feature(
    "settingsOverrides.materialFactors",
    "Material Factors",
    part="settings",
    fields=[
        number(
            "phiFlexureOverride", "Tension/flexure φ override (0 = use pack)", 0.0, min=0.0, max=1.0
        ),
        number("phiShearOverride", "Shear φ override (0 = use pack)", 0.0, min=0.0, max=1.0),
    ],
    requires_project=False,
)
def material_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare active code pack strength reduction / material partial factors with overrides."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        fac = safe_table(pack, "factors")
        phi_map = dict(getattr(fac, "phi", None) or {})
        proj_ov = overrides.of(st)
    rows = []
    for k, v in phi_map.items():
        path = f"factors.phi.{k}"
        ov = proj_ov.get(path)
        if k == "tension" and values["phiFlexureOverride"] > 0:
            ov = values["phiFlexureOverride"]
        if k == "shear" and values["phiShearOverride"] > 0:
            ov = values["phiShearOverride"]
        rows.append(
            {
                "factor": k,
                "packValue": v,
                "overrideValue": ov if ov is not None else "-",
                "effective": ov if ov is not None else v,
            }
        )
    return result(
        summary={
            "packFactorCount": len(rows),
            "projectOverrideCount": sum(1 for k in proj_ov if k.startswith("factors.")),
        },
        tables=[
            table(
                "Material / resistance factors",
                [
                    ("factor", "Limit state"),
                    ("packValue", "Pack value"),
                    ("overrideValue", "Override"),
                    ("effective", "Effective"),
                ],
                rows,
            )
        ],
        notes=[
            f"Factors read from {code_context.code_name(pack)} factors.phi and project codeOverrides."
        ],
    )


@feature(
    "settingsOverrides.loadFactors",
    "Load Factors",
    part="settings",
    fields=[
        number("deadFactor", "Dead load factor γD", 1.2, min=0.5, max=2.5),
        number("liveFactor", "Live load factor γL", 1.6, min=0.5, max=2.5),
    ],
    requires_project=False,
)
def load_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare custom dead and live load factors against the active code pack's primary combinations."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        comb = safe_table(pack, "combinations")
        strength = list(getattr(comb, "strength", None) or [])
    rows = [
        {
            "combination": r.name,
            "D": r.factors.get("D", 0.0),
            "L": r.factors.get("L", 0.0),
            "W": r.factors.get("W", 0.0),
            "E": r.factors.get("E", 0.0),
        }
        for r in strength[:12]
    ]
    return result(
        summary={
            "inputDeadFactor": values["deadFactor"],
            "inputLiveFactor": values["liveFactor"],
            "packStrengthRows": len(strength),
        },
        tables=[
            table(
                "Active pack strength load factors",
                [("combination", "Combination"), ("D", "D"), ("L", "L"), ("W", "W"), ("E", "E")],
                rows,
            )
        ],
        notes=[
            "Use codeOverrides on combinations.strength[...] to customize individual pack factors."
        ],
    )


@feature(
    "settingsOverrides.combinationFactors",
    "Combination Factors",
    part="settings",
    fields=[
        number("psi0", "Combination factor ψ0", 0.7, min=0.0, max=1.0),
        number("psi1", "Frequent factor ψ1", 0.5, min=0.0, max=1.0),
        number("psi2", "Quasi-permanent factor ψ2", 0.3, min=0.0, max=1.0),
    ],
    requires_project=False,
)
def combination_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate companion action ψ factors across ULS, frequent SLS, and quasi-permanent SLS checks."""
    rows = [
        {
            "situation": "ULS companion action (ψ0)",
            "factor": values["psi0"],
            "application": "Leading/accompanying variable load",
        },
        {
            "situation": "SLS frequent (ψ1)",
            "factor": values["psi1"],
            "application": "Crack width / reversible serviceability",
        },
        {
            "situation": "SLS quasi-permanent (ψ2)",
            "factor": values["psi2"],
            "application": "Long-term creep deflection & seismic mass",
        },
    ]
    return result(
        summary={"psi0": values["psi0"], "psi1": values["psi1"], "psi2": values["psi2"]},
        tables=[
            table(
                "Companion action ψ factors",
                [("situation", "Design situation"), ("factor", "ψ"), ("application", "Use")],
                rows,
            )
        ],
        notes=["Companion factors govern simultaneous variable actions and sustained creep share."],
    )


@feature(
    "settingsOverrides.steelFactors",
    "Steel Factors",
    part="settings",
    fields=[],
    requires_project=False,
)
def steel_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List structural steel resistance factors and any project overrides from the active pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        steel = safe_table(pack, "steel")
        phi_map = dict(getattr(steel, "phi", None) or {})
        proj_ov = overrides.of(st)
    rows = [
        {
            "limitState": k,
            "packValue": v,
            "effective": proj_ov.get(f"steel.phi.{k}", v),
            "overridden": f"steel.phi.{k}" in proj_ov,
        }
        for k, v in list(phi_map.items())[:25]
    ]
    return result(
        summary={
            "steelFactorCount": len(phi_map),
            "overriddenCount": sum(1 for r in rows if r["overridden"]),
        },
        tables=[
            table(
                "Steel partial / resistance factors",
                [
                    ("limitState", "Limit state"),
                    ("packValue", "Pack"),
                    ("effective", "Effective"),
                    ("overridden", "Overridden"),
                ],
                rows,
            )
        ],
        notes=[f"Steel resistance factors read from {code_context.code_name(pack)} steel.phi."],
    )


@feature(
    "settingsOverrides.soilFactors",
    "Soil Factors",
    part="settings",
    fields=[],
    requires_project=False,
)
def soil_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List geotechnical and foundation safety/resistance factors from the active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ft = safe_table(pack, "foundations")
    rows = []
    if ft is not None:
        for k in ("sptSafety", "noLoadTestSafety", "loadTestSafety", "partialSkin", "partialBase"):
            v = getattr(ft, k, None)
            if v is not None:
                rows.append({"parameter": k, "value": str(v)})
        ps = getattr(ft, "pileSafety", None)
        if isinstance(ps, dict):
            for k, v in ps.items():
                rows.append({"parameter": f"pileSafety.{k}", "value": str(v)})
    return result(
        summary={"geotechParameterCount": len(rows), "packId": pack.id},
        tables=[
            table(
                "Geotechnical safety & partial factors",
                [("parameter", "Parameter"), ("value", "Value")],
                rows or [{"parameter": "default", "value": "See foundations table"}],
            )
        ],
        notes=["Geotechnical factors sourced from active code pack foundations table."],
    )


@feature(
    "settingsOverrides.masonryFactors",
    "Masonry Factors",
    part="settings",
    fields=[],
    requires_project=False,
)
def masonry_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect masonry partial factors and strength reduction factors from the active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        mas = safe_table(pack, "masonry")
    d = mas.model_dump(mode="json") if mas is not None else {}
    rows = [
        {"parameter": k, "value": str(v)[:80]}
        for k, v in d.items()
        if k not in ("source", "sources", "clauses")
    ][:20]
    return result(
        summary={"masonryTablePresent": mas is not None, "parameterCount": len(rows)},
        tables=[
            table(
                "Masonry design factors",
                [("parameter", "Parameter"), ("value", "Value")],
                rows or [{"parameter": "masonry", "value": "Not covered in active pack"}],
            )
        ],
        notes=["Masonry design parameters read from the active code pack's masonry table."],
    )


@feature(
    "settingsOverrides.timberFactors",
    "Timber Factors",
    part="settings",
    fields=[],
    requires_project=False,
)
def timber_factors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect timber design resistance/modification factors from the active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        tim = safe_table(pack, "timber")
    d = tim.model_dump(mode="json") if tim is not None else {}
    rows = [
        {"parameter": k, "value": str(v)[:80]}
        for k, v in d.items()
        if k not in ("source", "sources", "clauses")
    ][:20]
    return result(
        summary={"timberTablePresent": tim is not None, "parameterCount": len(rows)},
        tables=[
            table(
                "Timber design factors",
                [("parameter", "Parameter"), ("value", "Value")],
                rows or [{"parameter": "timber", "value": "Not covered in active pack"}],
            )
        ],
        notes=[
            "Timber modification and partial factors read from the active code pack's timber table."
        ],
    )


@feature(
    "settingsOverrides.snowCombination",
    "Snow Combination",
    part="settings",
    fields=[
        number(
            "snowComboFactor", "Snow companion factor in wind/live combos", 0.5, min=0.0, max=1.6
        ),
    ],
    requires_project=False,
)
def snow_combination(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect snow load factors in active pack combinations and preview companion override."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        comb = safe_table(pack, "combinations")
        rows_s = [
            r
            for r in (getattr(comb, "strength", None) or [])
            if r.factors.get("S") or r.factors.get("Lr")
        ]
    rows = [
        {
            "combination": r.name,
            "S": r.factors.get("S", 0.0),
            "Lr": r.factors.get("Lr", 0.0),
            "overrideS": values["snowComboFactor"],
        }
        for r in rows_s
    ]
    return result(
        summary={
            "snowBearingCombinations": len(rows),
            "companionFactor": values["snowComboFactor"],
        },
        tables=[
            table(
                "Snow / roof-live combination factors",
                [
                    ("combination", "Combination"),
                    ("S", "Pack S"),
                    ("Lr", "Pack Lr"),
                    ("overrideS", "Target factor"),
                ],
                rows,
            )
        ],
        notes=["Tracks S (separate snow) and Lr (roof live/snow) combination multipliers."],
    )


@feature(
    "settingsOverrides.windCombination",
    "Wind Combination",
    part="settings",
    fields=[
        number("windFactorOverride", "Leading wind factor override", 1.6, min=0.5, max=2.5),
    ],
    requires_project=False,
)
def wind_combination(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect wind load factors across project combinations and compare with target override."""
    st = load_settings(ctx)
    rows = [
        {"combination": c.name, "WX": c.WX, "WY": c.WY, "D": c.D, "L": c.L}
        for c in st.combinations
        if abs(c.WX) > 1e-9 or abs(c.WY) > 1e-9
    ]
    max_w = max((max(abs(r["WX"]), abs(r["WY"])) for r in rows), default=0.0)
    return result(
        summary={
            "windCombinations": len(rows),
            "maxProjectWindFactor": max_w,
            "targetOverrideFactor": values["windFactorOverride"],
        },
        tables=[
            table(
                "Wind load combinations",
                [("combination", "Name"), ("WX", "WX"), ("WY", "WY"), ("D", "D"), ("L", "L")],
                rows,
            )
        ],
        notes=[
            "Compares project wind combination factors against the proposed leading wind factor."
        ],
    )


@feature(
    "settingsOverrides.seismicCombination",
    "Seismic Combination",
    part="settings",
    fields=[
        number("seismicFactorOverride", "Seismic factor override", 1.0, min=0.5, max=2.0),
    ],
    requires_project=False,
)
def seismic_combination(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect seismic load factors across project combinations and vertical dead load bounds."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        comb = safe_table(pack, "combinations")
        d_up = float(getattr(comb, "seismicDeadUpper", 1.2) or 1.2)
        d_lo = float(getattr(comb, "seismicDeadLower", 0.9) or 0.9)
    rows = [
        {"combination": c.name, "EX": c.EX, "EY": c.EY, "D": c.D, "L": c.L}
        for c in st.combinations
        if abs(c.EX) > 1e-9 or abs(c.EY) > 1e-9
    ]
    return result(
        summary={
            "seismicCombinations": len(rows),
            "seismicDeadUpper": d_up,
            "seismicDeadLower": d_lo,
            "targetSeismicFactor": values["seismicFactorOverride"],
        },
        tables=[
            table(
                "Seismic combinations",
                [("combination", "Name"), ("EX", "EX"), ("EY", "EY"), ("D", "D"), ("L", "L")],
                rows,
            )
        ],
        notes=[
            "Seismic dead load bounds (seismicDeadUpper/Lower) come from active pack combinations."
        ],
    )


@feature(
    "settingsOverrides.accidentalCombination",
    "Accidental Combination",
    part="settings",
    fields=[
        number(
            "psi1Accidental", "Frequent live factor ψ1 in accidental combo", 0.5, min=0.0, max=1.0
        ),
        number("accidentalFactor", "Accidental action multiplier γA", 1.0, min=0.5, max=1.5),
    ],
    requires_project=False,
)
def accidental_combination(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build accidental design situation combination factors (1.0 D + γA A + ψ1 L)."""
    rows = [
        {"case": "Permanent Dead (D + SD)", "factor": 1.0},
        {"case": "Accidental Action (A)", "factor": values["accidentalFactor"]},
        {"case": "Companion Live (L)", "factor": values["psi1Accidental"]},
    ]
    return result(
        summary={
            "deadFactor": 1.0,
            "accidentalFactor": values["accidentalFactor"],
            "liveCompanionFactor": values["psi1Accidental"],
        },
        tables=[
            table("Accidental load combination", [("case", "Action"), ("factor", "Factor")], rows)
        ],
        notes=[
            "Accidental combinations combine unfactored dead load, unit accidental action, and frequent live load."
        ],
    )


@feature(
    "settingsOverrides.significantFigures",
    "Significant Figures",
    part="settings",
    fields=[
        number("sigFigs", "Significant figures", 4.0, min=2.0, max=8.0),
        number("testValue", "Sample value", 0.00456789),
    ],
    requires_project=False,
)
def significant_figures(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Format numerical engineering outputs to a specified significant-figure count."""
    sf = int(values["sigFigs"])
    val = values["testValue"]
    formatted = f"{val:.{sf}g}"
    return result(
        summary={"significantFigures": sf, "formattedValue": formatted},
        tables=[
            table(
                "Significant-figure formatting",
                [("input", "Input"), ("sigFigs", "Sig figs"), ("formatted", "Output")],
                [{"input": val, "sigFigs": sf, "formatted": formatted}],
            )
        ],
        notes=[
            "Applies consistent significant-figure formatting for very small/large coefficients."
        ],
    )


@feature(
    "settingsOverrides.unitDisplayOverrides",
    "Unit Display Overrides",
    part="settings",
    fields=[],
    requires_project=False,
)
def unit_display_overrides(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect per-quantity display unit overrides in project settings."""
    st = load_settings(ctx)
    u = st.units
    fields = [k for k in type(u).model_fields if k != "system"]
    rows = [{"quantity": k, "override": getattr(u, k) or "(system default)"} for k in fields]
    return result(
        summary={
            "system": u.system,
            "overrideCount": sum(1 for k in fields if getattr(u, k) is not None),
        },
        tables=[
            table(
                "Per-quantity unit overrides",
                [("quantity", "Quantity"), ("override", "Display unit")],
                rows,
            )
        ],
        notes=["Overrides apply only when rendering UI, reports, DXF labels, and BOQ tables."],
    )


@feature(
    "settingsOverrides.toleranceBands",
    "Tolerance Bands",
    part="settings",
    fields=[
        number("nearLimitBandPct", "Near-limit warning band", 5.0, unit="%", min=0.5, max=25.0),
        number(
            "comparisonTolPct", "Result comparison tolerance", 1.0, unit="%", min=0.01, max=10.0
        ),
    ],
    requires_project=False,
)
def tolerance_bands(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define pass/near-limit/fail tolerance bands and regression comparison thresholds."""
    near = values["nearLimitBandPct"] / 100.0
    comp = values["comparisonTolPct"] / 100.0
    rows = [
        {"band": "Clear pass", "upperUtil": 1.0 - near},
        {"band": "Near-limit review", "upperUtil": 1.0},
        {"band": "Comparison match tolerance", "upperUtil": comp},
    ]
    return result(
        summary={"nearLimitThreshold": 1.0 - near, "comparisonTolerance": comp},
        tables=[
            table("Tolerance band thresholds", [("band", "Band"), ("upperUtil", "Threshold")], rows)
        ],
        notes=["Supports automated pass/fail categorization and snapshot regression tolerances."],
    )


@feature(
    "settingsOverrides.zeroDisplayRule",
    "Zero Display Rule",
    part="settings",
    fields=[
        number("zeroCutoff", "Suppression threshold |x| < ε", 1e-4, min=0.0, max=1.0),
        number("sampleValue", "Sample result value", 2.5e-5),
    ],
    requires_project=False,
)
def zero_display_rule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate near-zero suppression rules for cleaner force and displacement tables."""
    eps = values["zeroCutoff"]
    val = values["sampleValue"]
    suppressed = abs(val) < eps
    shown = "0" if suppressed else f"{val:g}"
    return result(
        summary={"cutoff": eps, "suppressed": suppressed, "displayedText": shown},
        tables=[
            table(
                "Zero suppression check",
                [("input", "Raw value"), ("cutoff", "Cutoff ε"), ("displayed", "Displayed")],
                [{"input": val, "cutoff": eps, "displayed": shown}],
            )
        ],
        notes=["Eliminates solver round-off noise (e.g. 1e-14) from tabulated output."],
    )


@feature(
    "settingsOverrides.overrideNotes",
    "Override Notes",
    part="settings",
    fields=[
        text("overridePath", "Code override path", "factors.phi.shear"),
        text(
            "justification",
            "Engineering justification",
            "Project-specific higher quality assurance",
        ),
    ],
    requires_project=False,
)
def override_notes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect active codeOverrides and record justification metadata for manual overrides."""
    st = load_settings(ctx)
    ov = overrides.of(st)
    rows = [{"path": k, "value": str(v), "note": "Active in project"} for k, v in ov.items()]
    rows.append(
        {"path": values["overridePath"], "value": "(documented)", "note": values["justification"]}
    )
    return result(
        summary={"activeOverrideCount": len(ov), "documentedPath": values["overridePath"]},
        tables=[
            table(
                "Code override justification log",
                [
                    ("path", "Override path"),
                    ("value", "Value"),
                    ("note", "Engineering justification"),
                ],
                rows,
            )
        ],
        notes=["All manual code value overrides should carry an explicit engineering rationale."],
    )


@feature(
    "settingsOverrides.overrideApproval",
    "Override Approval",
    part="settings",
    fields=[
        text("reviewer", "Checking engineer", "Principal Structural Reviewer"),
        select(
            "decision",
            "Approval state",
            [("pending", "Pending review"), ("approved", "Approved"), ("rejected", "Rejected")],
            "approved",
        ),
    ],
    requires_project=False,
)
def override_approval(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate project codeOverrides against the active pack and record reviewer sign-off."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        ov = overrides.of(st)
        probs = list(getattr(pack, "override_problems", []) or [])
    can_approve = len(probs) == 0
    rows = [
        {
            "path": p,
            "status": "valid",
            "reviewer": values["reviewer"],
            "decision": values["decision"] if can_approve else "blocked",
        }
        for p in ov
    ] + [
        {"path": p, "status": f"error: {m}", "reviewer": values["reviewer"], "decision": "rejected"}
        for p, m in probs
    ]
    return result(
        summary={
            "overrideCount": len(ov),
            "invalidOverrides": len(probs),
            "approvalReady": can_approve,
            "decision": values["decision"],
        },
        tables=[
            table(
                "Override approval status",
                [
                    ("path", "Path"),
                    ("status", "Schema check"),
                    ("reviewer", "Reviewer"),
                    ("decision", "Decision"),
                ],
                rows
                or [
                    {
                        "path": "-",
                        "status": "No overrides active",
                        "reviewer": values["reviewer"],
                        "decision": values["decision"],
                    }
                ],
            )
        ],
        notes=["Invalid overrides rejected by pack schemas cannot be approved for design."],
    )


@feature(
    "settingsOverrides.overrideExpiry",
    "Override Expiry",
    part="settings",
    fields=[
        text("reviewDate", "Current review date (YYYY-MM-DD)", "2026-11-23"),
        text("expiryDate", "Override expiry date (YYYY-MM-DD)", "2027-02-28"),
    ],
    requires_project=False,
)
def override_expiry(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check temporary override expiry dates against the current review date."""
    expired = values["reviewDate"] > values["expiryDate"]
    ov = overrides.of(load_settings(ctx))
    rows = [{"path": p, "expiryDate": values["expiryDate"], "expired": expired} for p in ov]
    return result(
        summary={
            "overrideCount": len(ov),
            "reviewDate": values["reviewDate"],
            "expiryDate": values["expiryDate"],
            "anyExpired": expired and len(ov) > 0,
        },
        tables=[
            table(
                "Override expiry schedule",
                [("path", "Path"), ("expiryDate", "Expiry"), ("expired", "Expired")],
                rows or [{"path": "(none)", "expiryDate": values["expiryDate"], "expired": False}],
            )
        ],
        notes=[
            "Flags temporary engineering overrides that have passed their scheduled review date."
        ],
    )


@feature(
    "settingsOverrides.revertOverride",
    "Revert Override",
    part="settings",
    fields=[
        text("pathToRevert", "Override path to preview reverting (blank = all)", ""),
    ],
    requires_project=False,
)
def revert_override(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Preview reverting active codeOverrides back to the active code pack's baseline values."""
    st = load_settings(ctx)
    ov = overrides.of(st)
    target = values["pathToRevert"].strip()
    rows = [
        {"path": k, "currentOverride": str(v), "willRevert": (not target or k == target)}
        for k, v in ov.items()
    ]
    return result(
        summary={
            "activeOverrides": len(ov),
            "revertedCount": sum(1 for r in rows if r["willRevert"]),
        },
        tables=[
            table(
                "Override reversion preview",
                [
                    ("path", "Path"),
                    ("currentOverride", "Override value"),
                    ("willRevert", "Revert to pack"),
                ],
                rows or [{"path": "(none)", "currentOverride": "-", "willRevert": False}],
            )
        ],
        notes=["Removing entries from settings.codeOverrides restores the code pack defaults."],
    )
