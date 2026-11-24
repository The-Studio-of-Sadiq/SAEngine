"""Dedicated mepSystems MEP feature registrations."""

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
    "mepSystems.branchSplitting",
    "Branch Splitting",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def branchSplitting(ctx: FeatureContext, values: dict) -> dict:
    """Branch Splitting: Connectivity."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Branch Splitting",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.connectTo",
    "Connect To",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def connectTo(ctx: FeatureContext, values: dict) -> dict:
    """Connect To: Connectivity."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Connect To",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.connectorManager",
    "Connector Manager",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def connectorManager(ctx: FeatureContext, values: dict) -> dict:
    """Connector Manager: Systems."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Connector Manager",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.disconnectNode",
    "Disconnect Node",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def disconnectNode(ctx: FeatureContext, values: dict) -> dict:
    """Disconnect Node: Connectivity."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Disconnect Node",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.disconnectedSystems",
    "Disconnected Systems",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def disconnectedSystems(ctx: FeatureContext, values: dict) -> dict:
    """Disconnected Systems: Checks."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Disconnected Systems",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.flowBalance",
    "Flow Balance",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def flowBalance(ctx: FeatureContext, values: dict) -> dict:
    """Flow Balance: Checks."""
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
    "mepSystems.loopDetection",
    "Loop Detection",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def loopDetection(ctx: FeatureContext, values: dict) -> dict:
    """Loop Detection: Analysis."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Loop Detection",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.openConnectors",
    "Open Connectors",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def openConnectors(ctx: FeatureContext, values: dict) -> dict:
    """Open Connectors: Connectivity."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Open Connectors",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.pressureBalance",
    "Pressure Balance",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def pressureBalance(ctx: FeatureContext, values: dict) -> dict:
    """Pressure Balance: Analysis."""
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
                "Pressure Balance",
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
    "mepSystems.sizeMismatch",
    "Size Mismatch",
    part="mep",
    fields=[
        number("upstreamSizeMm", "Upstream header / duct / pipe ID", 150.0, unit="mm", min=10.0),
        number("downstreamSizeMm", "Downstream continuation bore", 200.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def sizeMismatch(ctx: FeatureContext, values: dict) -> dict:
    """Check pipe/duct diameter transitions and flag unexpected downstream upsizing or excessive reduction."""
    up = float(values["upstreamSizeMm"])
    dn = float(values["downstreamSizeMm"])
    ratio = dn / up
    if dn > up + 1e-6:
        verdict = "Downstream expansion (>1.0x)"
    elif ratio < 0.4:
        verdict = "Abrupt contraction (<0.4x)"
    else:
        verdict = "Normal taper"
    loss_k = ((1.0 - (min(up, dn) / max(up, dn)) ** 2) ** 2) if dn != up else 0.0
    mep_openings = 0
    if ctx.root is not None and isinstance(ctx.raw("mep"), dict):
        mep_openings = len((ctx.raw("mep") or {}).get("openings") or [])
    return result(
        summary={
            "upstreamMm": up,
            "downstreamMm": dn,
            "diameterRatio": round(ratio, 2),
            "verdict": verdict,
            "fittingLossK": round(loss_k, 3),
        },
        tables=[
            table(
                "Conduit transition size-mismatch check",
                [("item", "Metric"), ("value", "Value")],
                [
                    {"item": "Upstream nominal size [mm]", "value": up},
                    {"item": "Downstream nominal size [mm]", "value": dn},
                    {"item": "Diameter ratio (D_down / D_up)", "value": round(ratio, 2)},
                    {"item": "Borda-Carnot transition K", "value": round(loss_k, 3)},
                    {"item": "Assessment", "value": f"{verdict} ({mep_openings} model opening(s))"},
                ],
            )
        ],
        notes=[
            "Downstream upsizing along feed lines without added branches indicates model connectivity mismatch."
        ],
    )


@feature(
    "mepSystems.systemCapacity",
    "System Capacity",
    part="mep",
    fields=[
        number(
            "demandReservePct",
            "Required capacity reserve margin",
            10.0,
            unit="%",
            min=0.0,
            max=50.0,
        )
    ],
    requires_project=True,
)
def systemCapacity(ctx: FeatureContext, values: dict) -> dict:
    """Audit installed MEP plant capacities (chiller/VRF, transformer, tanks) vs project stories in 07 MEP."""
    from saengine.mep import systems

    if ctx.root is None:
        raise FeatureInputError("Open a project with 07 MEP/mep.json to verify system capacity.")
    raw = ctx.raw("mep")
    if not isinstance(raw, dict):
        raise FeatureInputError("Missing 07 MEP/mep.json in project.")
    rep = (
        systems.mep_systems_report(ctx.root)
        if hasattr(systems, "mep_systems_report")
        else systems.analyze_systems(ctx.root)
    )
    hvac_units = (raw.get("hvac") or {}).get("plant") or []
    tanks = (raw.get("plumbing") or {}).get("tanks") or []
    elec_eq = (raw.get("electrical") or {}).get("equipment") or []
    hvac_kw = sum(float(u.get("capacityKw", 0.0) or 0.0) for u in hvac_units if isinstance(u, dict))
    tank_m3 = sum(
        float(
            t.get("capacityM3", t.get("volumeL", 0.0) / 1000.0 if t.get("volumeL") else 0.0) or 0.0
        )
        for t in tanks
        if isinstance(t, dict)
    )
    elec_kva = sum(
        float(e.get("kva", e.get("ratingKva", 0.0)) or 0.0) for e in elec_eq if isinstance(e, dict)
    )
    rows = [
        {
            "system": "HVAC Plant Cooling",
            "installed": round(hvac_kw, 1),
            "unit": "kW",
            "units": len(hvac_units),
        },
        {
            "system": "Plumbing Water Tanks",
            "installed": round(tank_m3, 1),
            "unit": "m³",
            "units": len(tanks),
        },
        {
            "system": "Electrical Supply Equipment",
            "installed": round(elec_kva, 1),
            "unit": "kVA",
            "units": len(elec_eq),
        },
    ]
    return result(
        summary={
            "installedHvacKw": round(hvac_kw, 1),
            "installedTankM3": round(tank_m3, 1),
            "installedElecKva": round(elec_kva, 1),
            "systemIssues": len(rep.get("issues", [])) if isinstance(rep, dict) else 0,
        },
        tables=[
            table(
                "Installed MEP plant capacity ledger",
                [
                    ("system", "Subsystem"),
                    ("units", "Plant Items"),
                    ("installed", "Total Capacity"),
                    ("unit", "Unit"),
                ],
                rows,
            )
        ],
        notes=[
            f"Tallied from 07 MEP/mep.json with {values['demandReservePct']:g}% design reserve target."
        ],
    )


@feature(
    "mepSystems.systemColours",
    "System Colours",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def systemColours(ctx: FeatureContext, values: dict) -> dict:
    """System Colours: Systems."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "System Colours",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.systemDiagram",
    "System Diagram",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def systemDiagram(ctx: FeatureContext, values: dict) -> dict:
    """System Diagram: Documentation."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepSystems.systemDiagram",
        "title": "System Diagram",
        "name": values["name"],
        "group": "Documentation",
        "mep": raw,
    }
    path = ctx.path("11 Exports/systemDiagram.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "System Diagram",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepSystems.systemExport",
    "System Export",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def systemExport(ctx: FeatureContext, values: dict) -> dict:
    """System Export: Documentation."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepSystems.systemExport",
        "title": "System Export",
        "name": values["name"],
        "group": "Documentation",
        "mep": raw,
    }
    path = ctx.path("11 Exports/systemExport.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "System Export",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepSystems.systemFlowCheck",
    "System Flow Check",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def systemFlowCheck(ctx: FeatureContext, values: dict) -> dict:
    """System Flow Check: Analysis."""
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
                "System Flow Check",
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
    "mepSystems.systemGrouping",
    "System Grouping",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def systemGrouping(ctx: FeatureContext, values: dict) -> dict:
    """System Grouping: Classification."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "System Grouping",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.systemLegend",
    "System Legend",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def systemLegend(ctx: FeatureContext, values: dict) -> dict:
    """System Legend: Documentation."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "System Legend",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.systemNaming",
    "System Naming",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def systemNaming(ctx: FeatureContext, values: dict) -> dict:
    """System Naming: Classification."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "System Naming",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.systemParameters",
    "System Parameters",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def systemParameters(ctx: FeatureContext, values: dict) -> dict:
    """System Parameters: Classification."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "System Parameters",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.systemTemplates",
    "System Templates",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def systemTemplates(ctx: FeatureContext, values: dict) -> dict:
    """System Templates: Classification."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "System Templates",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystems.systemZones",
    "System Zones",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def systemZones(ctx: FeatureContext, values: dict) -> dict:
    """System Zones: Systems."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "System Zones",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )
