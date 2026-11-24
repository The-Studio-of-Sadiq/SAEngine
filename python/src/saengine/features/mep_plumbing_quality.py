"""Dedicated mepPlumbingQuality MEP feature registrations."""

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
    "mepPlumbingQuality.backwashCycle",
    "Backwash Cycle",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def backwashCycle(ctx: FeatureContext, values: dict) -> dict:
    """Backwash Cycle: Filtration."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Backwash Cycle",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.boosterSet",
    "Booster Set",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def boosterSet(ctx: FeatureContext, values: dict) -> dict:
    """Booster Set: Pressure."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Booster Set",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.carbonFilter",
    "Carbon Filter",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def carbonFilter(ctx: FeatureContext, values: dict) -> dict:
    """Carbon Filter: Filtration."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Carbon Filter",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.chlorineLevel",
    "Chlorine Level",
    part="mep",
    fields=[
        number("dosedMgPerL", "Dosed free chlorine", 1.0, unit="mg/L", min=0.05, max=10.0),
        number("tankVolumeM3", "Storage tank volume", 40.0, unit="m³", min=0.5),
        number("dailyDemandM3", "Daily throughput", 60.0, unit="m³/d", min=0.5),
        number("decayRatePerHr", "First-order bulk/wall decay k", 0.04, unit="/h", min=0.0),
        number("minResidualMgPerL", "Minimum residual target", 0.20, unit="mg/L", min=0.05),
    ],
    requires_project=False,
)
def chlorineLevel(ctx: FeatureContext, values: dict) -> dict:
    """Compute first-order free chlorine decay over storage residence time and dosing check."""
    import math

    c0 = float(values["dosedMgPerL"])
    vol = float(values["tankVolumeM3"])
    q = float(values["dailyDemandM3"])
    k = float(values["decayRatePerHr"])
    c_min = float(values["minResidualMgPerL"])
    tau_hr = 24.0 * vol / q
    c_out = c0 * math.exp(-k * tau_hr)
    max_tau_hr = math.log(c0 / c_min) / k if k > 0 and c0 > c_min else 9999.0
    boost_g_per_day = max(0.0, (c_min - c_out) * q)
    ok = c_out >= c_min
    return result(
        summary={
            "residenceTimeHr": round(tau_hr, 2),
            "outletResidualMgPerL": round(c_out, 3),
            "minResidualMgPerL": c_min,
            "compliant": ok,
        },
        tables=[
            table(
                "Chlorine residual decay check",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "parameter": "Hydraulic residence time",
                        "value": round(tau_hr, 2),
                        "unit": "h",
                    },
                    {
                        "parameter": "Max allowed residence",
                        "value": round(max_tau_hr, 1),
                        "unit": "h",
                    },
                    {"parameter": "Outlet free chlorine", "value": round(c_out, 3), "unit": "mg/L"},
                    {
                        "parameter": "Required booster Cl2",
                        "value": round(boost_g_per_day, 1),
                        "unit": "g/day",
                    },
                    {"parameter": "Compliant", "value": "PASS" if ok else "FAIL", "unit": "-"},
                ],
            )
        ],
        notes=["First-order exponential decay C = C0 * exp(-k * t), t = 24 * V_tank / Q_day."],
    )


@feature(
    "mepPlumbingQuality.deadLegCheck",
    "Dead Leg Check",
    part="mep",
    fields=[
        number("pipeDiameterMm", "Nominal pipe bore", 25.0, unit="mm", min=10.0),
        number("deadLegLengthM", "Unflushed branch length L", 2.2, unit="m", min=0.05),
        number("maxLengthLimitM", "Project dead-leg length limit", 1.5, unit="m", min=0.1),
    ],
    requires_project=False,
)
def deadLegCheck(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate dead-leg stagnation length ratio (L/D) and trapped water volume."""
    import math

    d_mm = float(values["pipeDiameterMm"])
    l_m = float(values["deadLegLengthM"])
    lim_m = float(values["maxLengthLimitM"])
    l_over_d = (l_m * 1000.0) / d_mm
    stagnant_l = math.pi * ((d_mm / 1000.0) / 2.0) ** 2 * l_m * 1000.0
    ok = l_m <= lim_m
    return result(
        summary={
            "deadLegLengthM": l_m,
            "lengthToDiameterRatio": round(l_over_d, 1),
            "stagnantVolumeL": round(stagnant_l, 3),
            "compliant": ok,
        },
        tables=[
            table(
                "Dead-leg stagnation check",
                [("item", "Check Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Dead-leg length L", "value": l_m, "unit": "m"},
                    {"item": "Limit length", "value": lim_m, "unit": "m"},
                    {"item": "Slenderness ratio L/D", "value": round(l_over_d, 1), "unit": "-"},
                    {"item": "Stagnant water volume", "value": round(stagnant_l, 3), "unit": "L"},
                    {"item": "Status", "value": "PASS" if ok else "EXCEEDS LIMIT", "unit": "-"},
                ],
            )
        ],
        notes=[
            "Short dead-legs limit biofilm growth; shorten branch, relocate tee, or add purge valve if exceeded."
        ],
    )


@feature(
    "mepPlumbingQuality.dosingSystem",
    "Dosing System",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def dosingSystem(ctx: FeatureContext, values: dict) -> dict:
    """Dosing System: Sanitisation."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Dosing System",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.flushSchedule",
    "Flush Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def flushSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Flush Schedule: Testing."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepPlumbingQuality.flushSchedule",
        "title": "Flush Schedule",
        "name": values["name"],
        "group": "Testing",
        "mep": raw,
    }
    path = ctx.path("11 Exports/flushSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Flush Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepPlumbingQuality.hardnessSensor",
    "Hardness Sensor",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def hardnessSensor(ctx: FeatureContext, values: dict) -> dict:
    """Hardness Sensor: Softening."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Hardness Sensor",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.hotWaterTemp",
    "Hot Water Temp",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def hotWaterTemp(ctx: FeatureContext, values: dict) -> dict:
    """Hot Water Temp: Temperature."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Hot Water Temp",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.legionellaControl",
    "Legionella Control",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def legionellaControl(ctx: FeatureContext, values: dict) -> dict:
    """Legionella Control: Temperature."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Legionella Control",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.mediaFilter",
    "Media Filter",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def mediaFilter(ctx: FeatureContext, values: dict) -> dict:
    """Media Filter: Filtration."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Media Filter",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.mixingValve",
    "Mixing Valve",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def mixingValve(ctx: FeatureContext, values: dict) -> dict:
    """Mixing Valve: Temperature."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Mixing Valve",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.ozoneGenerator",
    "Ozone Generator",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def ozoneGenerator(ctx: FeatureContext, values: dict) -> dict:
    """Ozone Generator: Sanitisation."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Ozone Generator",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.pressureReport",
    "Pressure Report",
    part="mep",
    fields=[
        number("pressure", "Design pressure", 100, unit="kPa", min=0),
        text("name", "Output name", "MEP schedule"),
    ],
    requires_project=True,
)
def pressureReport(ctx: FeatureContext, values: dict) -> dict:
    """Pressure Report: Pressure."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepPlumbingQuality.pressureReport",
        "title": "Pressure Report",
        "name": values["name"],
        "group": "Pressure",
        "mep": raw,
    }
    path = ctx.path("11 Exports/pressureReport.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Pressure Report",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepPlumbingQuality.qualityReport",
    "Quality Report",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def qualityReport(ctx: FeatureContext, values: dict) -> dict:
    """Quality Report: Testing."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepPlumbingQuality.qualityReport",
        "title": "Quality Report",
        "name": values["name"],
        "group": "Testing",
        "mep": raw,
    }
    path = ctx.path("11 Exports/qualityReport.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Quality Report",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepPlumbingQuality.residualPressure",
    "Residual Pressure",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def residualPressure(ctx: FeatureContext, values: dict) -> dict:
    """Residual Pressure: Pressure."""
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
                "Residual Pressure",
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
    "mepPlumbingQuality.saltMonitoring",
    "Salt Monitoring",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def saltMonitoring(ctx: FeatureContext, values: dict) -> dict:
    """Salt Monitoring: Softening."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Salt Monitoring",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.samplingPoint",
    "Sampling Point",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def samplingPoint(ctx: FeatureContext, values: dict) -> dict:
    """Sampling Point: Testing."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Sampling Point",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.staticPressure",
    "Static Pressure",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def staticPressure(ctx: FeatureContext, values: dict) -> dict:
    """Static Pressure: Pressure."""
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
                "Static Pressure",
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
    "mepPlumbingQuality.thermalFlush",
    "Thermal Flush",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def thermalFlush(ctx: FeatureContext, values: dict) -> dict:
    """Thermal Flush: Sanitisation."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Thermal Flush",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingQuality.waterAnalysis",
    "Water Analysis",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def waterAnalysis(ctx: FeatureContext, values: dict) -> dict:
    """Water Analysis: Sanitisation."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Water Analysis",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )
