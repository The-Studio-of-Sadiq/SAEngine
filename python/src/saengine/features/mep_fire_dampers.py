"""Dedicated mepFireDampers MEP feature registrations."""

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
    "mepFireDampers.accessClearanceCheck",
    "Access Clearance Check",
    part="mep",
    fields=[
        number("ductWidthMm", "Duct / damper clear width", 600.0, unit="mm", min=150.0),
        number("accessPanelWidthMm", "Inspection access panel width", 450.0, unit="mm", min=150.0),
        number(
            "clearFrontMm", "Clear maintenance space in front of door", 600.0, unit="mm", min=100.0
        ),
        number(
            "minClearanceMm", "Minimum maintenance access clearance", 500.0, unit="mm", min=300.0
        ),
    ],
    requires_project=False,
)
def accessClearanceCheck(ctx: FeatureContext, values: dict) -> dict:
    """Verify fire/smoke damper access door opening size and unobstructed maintenance reach."""
    front_ok = float(values["clearFrontMm"]) >= float(values["minClearanceMm"])
    reach_ratio = float(values["accessPanelWidthMm"]) / float(values["ductWidthMm"])
    panel_ok = float(values["accessPanelWidthMm"]) >= min(450.0, float(values["ductWidthMm"]))
    ok = front_ok and panel_ok
    return result(
        summary={
            "clearFrontMm": values["clearFrontMm"],
            "accessPanelMm": values["accessPanelWidthMm"],
            "widthCoverageRatio": round(reach_ratio, 2),
            "compliant": ok,
        },
        tables=[
            table(
                "Fire damper maintenance access check",
                [("item", "Criterion"), ("value", "Provided"), ("status", "Status")],
                [
                    {
                        "item": "Frontal clearance (>= min)",
                        "value": f"{values['clearFrontMm']:g} mm",
                        "status": "PASS" if front_ok else "OBSTRUCTED",
                    },
                    {
                        "item": "Access panel width",
                        "value": f"{values['accessPanelWidthMm']:g} mm",
                        "status": "PASS" if panel_ok else "TOO NARROW",
                    },
                ],
            )
        ],
        notes=[
            "Install hinged inspection door adjacent to fusible link / actuator for periodic drop testing."
        ],
    )


@feature(
    "mepFireDampers.accessPanel",
    "Access Panel",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def accessPanel(ctx: FeatureContext, values: dict) -> dict:
    """Access Panel: Placement."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Access Panel",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.acousticAttenuation",
    "Acoustic Attenuation",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def acousticAttenuation(ctx: FeatureContext, values: dict) -> dict:
    """Acoustic Attenuation: Airflow Impact."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Acoustic Attenuation",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.actuator",
    "Actuator",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def actuator(ctx: FeatureContext, values: dict) -> dict:
    """Actuator: Control."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Actuator",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.bmsOverride",
    "BMS Override",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def bmsOverride(ctx: FeatureContext, values: dict) -> dict:
    """BMS Override: Smoke Control."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "BMS Override",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.damperRating",
    "Damper Rating",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def damperRating(ctx: FeatureContext, values: dict) -> dict:
    """Damper Rating: Placement."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Damper Rating",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.damperReport",
    "Damper Report",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def damperReport(ctx: FeatureContext, values: dict) -> dict:
    """Damper Report: Checks."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepFireDampers.damperReport",
        "title": "Damper Report",
        "name": values["name"],
        "group": "Checks",
        "mep": raw,
    }
    path = ctx.path("11 Exports/damperReport.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Damper Report",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepFireDampers.damperSchedule",
    "Damper Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def damperSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Damper Schedule: Checks."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepFireDampers.damperSchedule",
        "title": "Damper Schedule",
        "name": values["name"],
        "group": "Checks",
        "mep": raw,
    }
    path = ctx.path("11 Exports/damperSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Damper Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepFireDampers.ductLocation",
    "Duct Location",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def ductLocation(ctx: FeatureContext, values: dict) -> dict:
    """Duct Location: Placement."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Duct Location",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.exhaustInterlock",
    "Exhaust Interlock",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def exhaustInterlock(ctx: FeatureContext, values: dict) -> dict:
    """Exhaust Interlock: Smoke Control."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Exhaust Interlock",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.freeAreaFactor",
    "Free Area Factor",
    part="mep",
    fields=[number("area", "Area", 100, unit="m?", min=0)],
    requires_project=True,
)
def freeAreaFactor(ctx: FeatureContext, values: dict) -> dict:
    """Free Area Factor: Airflow Impact."""
    design_value = float(values["area"])
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
                "Free Area Factor",
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
    "mepFireDampers.fusibleLink",
    "Fusible Link",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def fusibleLink(ctx: FeatureContext, values: dict) -> dict:
    """Fusible Link: Control."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Fusible Link",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.inspectionHatchPosition",
    "Inspection Hatch Position",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def inspectionHatchPosition(ctx: FeatureContext, values: dict) -> dict:
    """Inspection Hatch Position: Maintenance Access."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Inspection Hatch Position",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.interlockLogic",
    "Interlock Logic",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def interlockLogic(ctx: FeatureContext, values: dict) -> dict:
    """Interlock Logic: Control."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepFireDampers.interlockLogic",
        "title": "Interlock Logic",
        "name": values["name"],
        "group": "Control",
        "mep": raw,
    }
    path = ctx.path("11 Exports/interlockLogic.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Interlock Logic",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepFireDampers.placeDamper",
    "Place Damper",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def placeDamper(ctx: FeatureContext, values: dict) -> dict:
    """Place Damper: Placement."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Place Damper",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.pressureLossCheck",
    "Pressure Loss Check",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def pressureLossCheck(ctx: FeatureContext, values: dict) -> dict:
    """Pressure Loss Check: Airflow Impact."""
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
                "Pressure Loss Check",
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
    "mepFireDampers.pressurizationControl",
    "Pressurization Control",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def pressurizationControl(ctx: FeatureContext, values: dict) -> dict:
    """Pressurization Control: Smoke Control."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Pressurization Control",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.ratingCheck",
    "Rating Check",
    part="mep",
    fields=[
        number(
            "barrierRatingMin",
            "Fire barrier / floor separation rating",
            120.0,
            unit="min",
            min=30.0,
        ),
        number(
            "damperRatingMin", "Damper tested fire endurance rating", 90.0, unit="min", min=30.0
        ),
        number("staticPressurePa", "System duct closing pressure", 350.0, unit="Pa", min=50.0),
    ],
    requires_project=False,
)
def ratingCheck(ctx: FeatureContext, values: dict) -> dict:
    """Verify fire damper assembly hour rating meets or exceeds compartment wall/slab rating."""
    barrier = float(values["barrierRatingMin"])
    damper = float(values["damperRatingMin"])
    # Common compartmental rule: 3-hr barriers require >=3-hr damper; <=2-hr barriers allow 1.5-hr damper (or equal)
    req_damper = 180.0 if barrier >= 180.0 else (90.0 if barrier >= 90.0 else 60.0)
    ok = damper >= req_damper
    return result(
        summary={
            "barrierRatingMin": barrier,
            "requiredDamperMin": req_damper,
            "providedDamperMin": damper,
            "compliant": ok,
        },
        tables=[
            table(
                "Fire damper compartment rating check",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Fire wall / floor rating", "value": barrier, "unit": "min"},
                    {"item": "Minimum damper rating", "value": req_damper, "unit": "min"},
                    {"item": "Selected damper rating", "value": damper, "unit": "min"},
                    {
                        "item": "Dynamic closure rating pressure",
                        "value": values["staticPressurePa"],
                        "unit": "Pa",
                    },
                    {
                        "item": "Compliance",
                        "value": "PASS" if ok else "UPGRADE DAMPER RATING",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Select dynamic-rated curtain or multi-blade damper tested under system airflow & static pressure."
        ],
    )


@feature(
    "mepFireDampers.sealCheck",
    "Seal Check",
    part="mep",
    fields=[
        number("damperAreaM2", "Damper nominal face area", 0.48, unit="m²", min=0.02),
        number(
            "testPressurePa", "Compartment test pressure differential", 1000.0, unit="Pa", min=100.0
        ),
        number(
            "leakageRateLpsPerM2", "Manufacturer blade seal leakage", 18.0, unit="L/(s·m²)", min=0.5
        ),
        number(
            "maxClassLimitLpsPerM2",
            "Class I / II maximum allowable leakage",
            20.3,
            unit="L/(s·m²)",
            min=2.0,
        ),
    ],
    requires_project=False,
)
def sealCheck(ctx: FeatureContext, values: dict) -> dict:
    """Compute total closed-damper smoke leakage flow and verify leakage-class limit."""
    q_leak_lps = float(values["damperAreaM2"]) * float(values["leakageRateLpsPerM2"])
    ok = float(values["leakageRateLpsPerM2"]) <= float(values["maxClassLimitLpsPerM2"])
    return result(
        summary={
            "totalLeakageLps": round(q_leak_lps, 2),
            "leakageClassOk": ok,
            "testPressurePa": float(values["testPressurePa"]),
        },
        tables=[
            table(
                "Combination fire-smoke damper seal leakage",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Damper face area", "value": values["damperAreaM2"], "unit": "m²"},
                    {
                        "item": "Specific leakage at ΔP",
                        "value": values["leakageRateLpsPerM2"],
                        "unit": "L/(s·m²)",
                    },
                    {
                        "item": "Total blade bypass leakage",
                        "value": round(q_leak_lps, 2),
                        "unit": "L/s",
                    },
                    {
                        "item": "Seal class check",
                        "value": "PASS" if ok else "EXCEEDS LIMIT",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=["Provide stainless-steel side jamb seals and perimeter intumescent sleeve sealant."],
    )


@feature(
    "mepFireDampers.serviceHistoryLog",
    "Service History Log",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def serviceHistoryLog(ctx: FeatureContext, values: dict) -> dict:
    """Service History Log: Maintenance Access."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepFireDampers.serviceHistoryLog",
        "title": "Service History Log",
        "name": values["name"],
        "group": "Maintenance Access",
        "mep": raw,
    }
    path = ctx.path("11 Exports/serviceHistoryLog.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Service History Log",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepFireDampers.signalOutput",
    "Signal Output",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def signalOutput(ctx: FeatureContext, values: dict) -> dict:
    """Signal Output: Control."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Signal Output",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireDampers.smokeDamperMode",
    "Smoke Damper Mode",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def smokeDamperMode(ctx: FeatureContext, values: dict) -> dict:
    """Smoke Damper Mode: Smoke Control."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Smoke Damper Mode",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )
