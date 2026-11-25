"""Dedicated mepSystemsBalancing MEP feature registrations."""

from __future__ import annotations

import json

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)


@feature(
    "mepSystemsBalancing.airBalancing",
    "Air Balancing",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def airBalancing(ctx: FeatureContext, values: dict) -> dict:
    """Air Balancing: Air Distribution."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Air Balancing",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsBalancing.balanceMode",
    "Balance Mode",
    part="mep",
    fields=[
        number("indexLossKpa", "Index (worst-path) circuit loss", 145.0, unit="kPa", min=1.0),
        number("subBranchLossKpa", "Favoured parallel branch loss", 85.0, unit="kPa", min=1.0),
        number("branchFlowLps", "Favoured branch design flow", 2.2, unit="L/s", min=0.05),
    ],
    requires_project=False,
)
def balanceMode(ctx: FeatureContext, values: dict) -> dict:
    """Determine excess differential head to balance and PICV vs manual balancing valve authority."""
    excess_kpa = float(values["indexLossKpa"]) - float(values["subBranchLossKpa"])
    if excess_kpa < 0:
        excess_kpa = 0.0
    auth = excess_kpa / float(values["indexLossKpa"]) if float(values["indexLossKpa"]) > 0 else 0.0
    mode = (
        "Static DRV + Control Valve"
        if excess_kpa < 40.0
        else "Pressure-Independent Control Valve (PICV)"
    )
    return result(
        summary={
            "excessHeadKpa": round(excess_kpa, 1),
            "throttlingAuthority": round(auth, 2),
            "recommendedStrategy": mode,
        },
        tables=[
            table(
                "Hydronic balancing strategy",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Index circuit pressure drop",
                        "value": values["indexLossKpa"],
                        "unit": "kPa",
                    },
                    {
                        "item": "Favoured branch drop",
                        "value": values["subBranchLossKpa"],
                        "unit": "kPa",
                    },
                    {"item": "Excess head to absorb", "value": round(excess_kpa, 1), "unit": "kPa"},
                    {"item": "Recommended valve mode", "value": mode, "unit": "-"},
                ],
            )
        ],
        notes=[
            "Select PICVs where excess head varies widely at part-load across multi-riser CHW/LTHW circuits."
        ],
    )


@feature(
    "mepSystemsBalancing.balanceReport",
    "Balance Report",
    part="mep",
    fields=[
        number("tolerancePct", "Allowable flow tolerance (±%)", 10.0, unit="%", min=1.0, max=25.0),
        text("name", "Export balance report filename prefix", "balanceReport"),
    ],
    requires_project=True,
)
def balanceReport(ctx: FeatureContext, values: dict) -> dict:
    """Compute hydraulic & air system balancing summary across 07 MEP risers/ducts and export JSON."""
    if ctx.root is None:
        raise FeatureInputError(
            "Open a project with 07 MEP/mep.json before generating a balance report."
        )
    raw = ctx.raw("mep")
    if not isinstance(raw, dict):
        raise FeatureInputError("Missing 07 MEP/mep.json in project.")
    risers = (raw.get("plumbing") or {}).get("risers") or []
    ducts = (raw.get("hvac") or {}).get("ducts") or []
    rows = []
    for r in risers:
        if isinstance(r, dict):
            rows.append(
                {
                    "system": "Plumbing Riser",
                    "id": str(r.get("id", "")),
                    "target": str(r.get("kind", "supply")),
                    "tolerancePct": values["tolerancePct"],
                }
            )
    for d in ducts:
        if isinstance(d, dict):
            rows.append(
                {
                    "system": "HVAC Duct",
                    "id": str(d.get("id", "")),
                    "target": str(d.get("system", "supply")),
                    "tolerancePct": values["tolerancePct"],
                }
            )
    if not rows:
        raise FeatureInputError(
            "No risers or ducts present in 07 MEP/mep.json to schedule for balancing."
        )
    safe = "".join(c for c in values["name"] if c.isalnum() or c in "-_") or "balanceReport"
    path = ctx.path(f"11 Exports/{safe}.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"tolerancePct": values["tolerancePct"], "circuits": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    return result(
        summary={
            "circuitCount": len(rows),
            "tolerancePct": values["tolerancePct"],
            "exportPath": str(path),
        },
        tables=[
            table(
                "System balancing schedule",
                [
                    ("system", "System"),
                    ("id", "Circuit ID"),
                    ("target", "Service"),
                    ("tolerancePct", "Tol", "%"),
                ],
                rows,
            )
        ],
        notes=[f"Scheduled {len(rows)} balancing circuit(s) from 07 MEP/mep.json to {path}."],
    )


@feature(
    "mepSystemsBalancing.benchmarkComparison",
    "Benchmark Comparison",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def benchmarkComparison(ctx: FeatureContext, values: dict) -> dict:
    """Benchmark Comparison: Commissioning."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepSystemsBalancing.benchmarkComparison",
        "title": "Benchmark Comparison",
        "name": values["name"],
        "group": "Commissioning",
        "mep": raw,
    }
    path = ctx.path("11 Exports/benchmarkComparison.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Benchmark Comparison",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepSystemsBalancing.criticalPath",
    "Critical Path",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def criticalPath(ctx: FeatureContext, values: dict) -> dict:
    """Critical Path: Analyse."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Critical Path",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsBalancing.damperSetting",
    "Damper Setting",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def damperSetting(ctx: FeatureContext, values: dict) -> dict:
    """Damper Setting: Adjust."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Damper Setting",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsBalancing.differentialPressure",
    "Differential Pressure",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def differentialPressure(ctx: FeatureContext, values: dict) -> dict:
    """Differential Pressure: Hydronics."""
    design_value = float(values["pressure"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Differential Pressure",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepSystemsBalancing.exportResults",
    "Export Results",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def exportResults(ctx: FeatureContext, values: dict) -> dict:
    """Export Results: Results."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepSystemsBalancing.exportResults",
        "title": "Export Results",
        "name": values["name"],
        "group": "Results",
        "mep": raw,
    }
    path = ctx.path("11 Exports/exportResults.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Export Results",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepSystemsBalancing.fanSpeedAdjust",
    "Fan Speed Adjust",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def fanSpeedAdjust(ctx: FeatureContext, values: dict) -> dict:
    """Fan Speed Adjust: Air Distribution."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Fan Speed Adjust",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsBalancing.flowBalance",
    "Flow Balance",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def flowBalance(ctx: FeatureContext, values: dict) -> dict:
    """Flow Balance: Analyse."""
    design_value = float(values["flow"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Flow Balance",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepSystemsBalancing.flowMeasuring",
    "Flow Measuring",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def flowMeasuring(ctx: FeatureContext, values: dict) -> dict:
    """Flow Measuring: Hydronics."""
    design_value = float(values["flow"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Flow Measuring",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepSystemsBalancing.hoodCapture",
    "Hood Capture",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def hoodCapture(ctx: FeatureContext, values: dict) -> dict:
    """Hood Capture: Air Distribution."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Hood Capture",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsBalancing.hydronicLoop",
    "Hydronic Loop",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def hydronicLoop(ctx: FeatureContext, values: dict) -> dict:
    """Hydronic Loop: Hydronics."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Hydronic Loop",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsBalancing.imbalanceList",
    "Imbalance List",
    part="mep",
    fields=[
        text(
            "measuredPairs",
            "Branch measurements name=design:actual;...",
            "B1=100:82;B2=100:118;B3=100:96",
        ),
        number("tolerancePct", "Allowable % deviation", 10.0, unit="%", min=1.0),
        text("name", "Export imbalance JSON filename", "imbalanceList"),
    ],
    requires_project=False,
)
def imbalanceList(ctx: FeatureContext, values: dict) -> dict:
    """Flag out-of-tolerance terminal branches from measured vs design flow pairs."""
    tol = float(values["tolerancePct"])
    rows = []
    for tok in values["measuredPairs"].split(";"):
        tok = tok.strip()
        if not tok or "=" not in tok or ":" not in tok:
            continue
        b_id, pair = tok.split("=", 1)
        des_s, act_s = pair.split(":", 1)
        des_v, act_v = float(des_s), float(act_s)
        dev_pct = ((act_v - des_v) / des_v) * 100.0 if des_v else 0.0
        rows.append(
            {
                "branch": b_id.strip(),
                "design": des_v,
                "actual": act_v,
                "deviationPct": round(dev_pct, 1),
                "outOfTolerance": abs(dev_pct) > tol,
            }
        )
    if not rows:
        raise FeatureInputError("Provide valid name=design:actual branch pairs.")
    flagged = [r for r in rows if r["outOfTolerance"]]
    out_note = f"Identified {len(flagged)} out-of-balance branch(es) outside +/-{tol:g}%."
    if ctx.root is not None:
        safe = "".join(c for c in values["name"] if c.isalnum() or c in "-_") or "imbalanceList"
        path = ctx.path(f"11 Exports/{safe}.json")
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"tolerancePct": tol, "imbalances": flagged, "all": rows}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            out_note += f" Saved to {path}."
    return result(
        summary={"totalBranches": len(rows), "imbalancedCount": len(flagged), "tolerancePct": tol},
        tables=[
            table(
                "Branch balancing deviation audit",
                [
                    ("branch", "Branch"),
                    ("design", "Design"),
                    ("actual", "Measured"),
                    ("deviationPct", "Dev", "%"),
                    ("outOfTolerance", "Flagged"),
                ],
                rows,
            )
        ],
        notes=[out_note],
    )


@feature(
    "mepSystemsBalancing.iterateBalance",
    "Iterate Balance",
    part="mep",
    fields=[
        number("minBranchRatio", "Lowest starved branch (Q_meas/Q_des)", 0.72, min=0.2, max=1.5),
        number(
            "maxBranchRatio", "Highest overflowed branch (Q_meas/Q_des)", 1.28, min=0.5, max=2.5
        ),
        number("currentPumpHeadKpa", "Current pump operating head", 160.0, unit="kPa", min=10.0),
    ],
    requires_project=False,
)
def iterateBalance(ctx: FeatureContext, values: dict) -> dict:
    """Compute proportional valve throttling & pump speed scaling convergence for hydronic balancing."""
    r_min = float(values["minBranchRatio"])
    r_max = float(values["maxBranchRatio"])
    # Bring starved index branch to 1.0 -> global pump multiplier = 1 / r_min; overflow branch must then be throttled from r_max/r_min to 1.0
    scale_q = 1.0 / r_min
    head_mult = scale_q**2
    throttle_ratio = r_max / r_min
    new_head = float(values["currentPumpHeadKpa"]) * head_mult
    spread_pct = ((r_max - r_min) / 1.0) * 100.0
    return result(
        summary={
            "initialSpreadPct": round(spread_pct, 1),
            "pumpSpeedMultiplier": round(scale_q, 3),
            "adjustedPumpHeadKpa": round(new_head, 1),
            "maxThrottleFactor": round(throttle_ratio, 2),
        },
        tables=[
            table(
                "Proportional balance iteration step",
                [("step", "Metric"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "step": "Ratio spread (max - min)",
                        "value": round(spread_pct, 1),
                        "unit": "%",
                    },
                    {
                        "step": "Required pump/fan speed scale",
                        "value": round(scale_q, 3),
                        "unit": "x",
                    },
                    {"step": "Scaled circuit head", "value": round(new_head, 1), "unit": "kPa"},
                    {
                        "step": "Favoured branch throttle ratio",
                        "value": round(throttle_ratio, 2),
                        "unit": ":1",
                    },
                ],
            )
        ],
        notes=[
            "Lock index circuit wide open, proportion sub-branches to index ratio, then trim VFD speed to set Q=100%."
        ],
    )


@feature(
    "mepSystemsBalancing.networkSolve",
    "Network Solve",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def networkSolve(ctx: FeatureContext, values: dict) -> dict:
    """Network Solve: Analyse."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Network Solve",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsBalancing.pressureDrop",
    "Pressure Drop",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def pressureDrop(ctx: FeatureContext, values: dict) -> dict:
    """Pressure Drop: Analyse."""
    design_value = float(values["pressure"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Pressure Drop",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepSystemsBalancing.pumpSpeed",
    "Pump Speed",
    part="mep",
    fields=[
        number("ratedRpm", "Motor synchronous / rated speed N1", 1450.0, unit="rpm", min=300.0),
        number("measuredFlowLps", "Balanced full-throttle flow Q1", 14.5, unit="L/s", min=0.2),
        number("targetFlowLps", "Design required system flow Q2", 12.0, unit="L/s", min=0.2),
        number("ratedPowerKw", "Pump input power P1 at N1", 11.0, unit="kW", min=0.1),
    ],
    requires_project=False,
)
def pumpSpeed(ctx: FeatureContext, values: dict) -> dict:
    """Trim VFD pump speed using centrifugal affinity laws to eliminate excess throttling head."""
    q1 = float(values["measuredFlowLps"])
    q2 = float(values["targetFlowLps"])
    ratio = q2 / q1
    n2 = float(values["ratedRpm"]) * ratio
    freq2 = 50.0 * ratio
    p2 = float(values["ratedPowerKw"]) * (ratio**3)
    saved_kw = float(values["ratedPowerKw"]) - p2
    return result(
        summary={
            "speedRatio": round(ratio, 3),
            "targetRpm": round(n2, 0),
            "vfdFrequencyHz": round(freq2, 1),
            "trimmedPowerKw": round(p2, 2),
            "powerSavedKw": round(saved_kw, 2),
        },
        tables=[
            table(
                "VFD pump speed trim (affinity laws)",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Target VFD speed ratio", "value": round(ratio, 3), "unit": "-"},
                    {
                        "parameter": "Trimmed rotational speed N2",
                        "value": round(n2, 0),
                        "unit": "rpm",
                    },
                    {
                        "parameter": "Drive frequency (50 Hz base)",
                        "value": round(freq2, 1),
                        "unit": "Hz",
                    },
                    {"parameter": "Input power after trim P2", "value": round(p2, 2), "unit": "kW"},
                    {
                        "parameter": "Throttling power avoided",
                        "value": round(saved_kw, 2),
                        "unit": "kW",
                    },
                ],
            )
        ],
        notes=[
            "Affinity laws: Q ~ N, H ~ N^2, P ~ N^3 assuming pure quadratic system resistance curve."
        ],
    )


@feature(
    "mepSystemsBalancing.saveBalanceSet",
    "Save Balance Set",
    part="mep",
    fields=[
        text("setName", "Commissioned balance set ID", "CHW-Primary-Riser1"),
        number("totalFlowLps", "Commissioned total loop flow", 12.0, unit="L/s", min=0.1),
        number("residualDpKpa", "Verified index differential pressure", 38.0, unit="kPa", min=1.0),
    ],
    requires_project=True,
)
def saveBalanceSet(ctx: FeatureContext, values: dict) -> dict:
    """Persist validated TAB balance-set record against project MEP circuits in 11 Exports."""
    from datetime import date

    if ctx.root is None:
        raise FeatureInputError("Open a project before saving commissioned balance records.")
    raw = ctx.raw("mep") or {}
    hvac_count = len((raw.get("hvac") or {}).get("plant") or []) + len(
        (raw.get("hvac") or {}).get("ducts") or []
    )
    entry = {
        "setName": values["setName"].strip() or "BalanceSet",
        "date": date.today().isoformat(),
        "totalFlowLps": float(values["totalFlowLps"]),
        "residualDpKpa": float(values["residualDpKpa"]),
        "projectHvacItems": hvac_count,
    }
    path = ctx.path("11 Exports/balance-sets.json")
    if path is None:
        raise FeatureInputError("Open a project before saving balance sets.")
    existing = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("sets"), list):
                existing = [s for s in loaded["sets"] if isinstance(s, dict)]
        except ValueError:
            existing = []
    by_name = {str(s.get("setName", "")): s for s in existing}
    by_name[entry["setName"]] = entry
    rows = list(by_name.values())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sets": rows}, indent=2) + "\n", encoding="utf-8")
    return result(
        summary={"setName": entry["setName"], "savedSets": len(rows), "exportPath": str(path)},
        tables=[
            table(
                "Saved balance sets register",
                [
                    ("setName", "Set ID"),
                    ("date", "Date"),
                    ("totalFlowLps", "Flow", "L/s"),
                    ("residualDpKpa", "Index dP", "kPa"),
                ],
                rows,
            )
        ],
        notes=[f"Updated balance set register ({len(rows)} record(s)) at {path}."],
    )


@feature(
    "mepSystemsBalancing.signoffSheet",
    "Signoff Sheet",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def signoffSheet(ctx: FeatureContext, values: dict) -> dict:
    """Signoff Sheet: Commissioning."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepSystemsBalancing.signoffSheet",
        "title": "Signoff Sheet",
        "name": values["name"],
        "group": "Commissioning",
        "mep": raw,
    }
    path = ctx.path("11 Exports/signoffSheet.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Signoff Sheet",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepSystemsBalancing.toleranceRange",
    "Tolerance Range",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def toleranceRange(ctx: FeatureContext, values: dict) -> dict:
    """Tolerance Range: Commissioning."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Tolerance Range",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsBalancing.valveSetting",
    "Valve Setting",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def valveSetting(ctx: FeatureContext, values: dict) -> dict:
    """Valve Setting: Adjust."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Valve Setting",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )
