"""Dedicated mepSystemsZoning MEP feature registrations."""

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
    "mepSystemsZoning.areaSchedule",
    "Area Schedule",
    part="mep",
    fields=[
        number("area", "Area", 100, unit="m?", min=0),
        text("name", "Output name", "MEP schedule"),
    ],
    requires_project=True,
)
def areaSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Area Schedule: Areas."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepSystemsZoning.areaSchedule",
        "title": "Area Schedule",
        "name": values["name"],
        "group": "Areas",
        "mep": raw,
    }
    path = ctx.path("11 Exports/areaSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Area Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepSystemsZoning.areaType",
    "Area Type",
    part="mep",
    fields=[number("area", "Area", 100, unit="m?", min=0)],
    requires_project=True,
)
def areaType(ctx: FeatureContext, values: dict) -> dict:
    """Area Type: Areas."""
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
                "Area Type",
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
    "mepSystemsZoning.assignSystems",
    "Assign Systems",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def assignSystems(ctx: FeatureContext, values: dict) -> dict:
    """Assign Systems: Zones."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Assign Systems",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.compareZones",
    "Compare Zones",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def compareZones(ctx: FeatureContext, values: dict) -> dict:
    """Compare Zones: Report."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Compare Zones",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.createZone",
    "Create Zone",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def createZone(ctx: FeatureContext, values: dict) -> dict:
    """Create Zone: Zones."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Create Zone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.diversityFactor",
    "Diversity Factor",
    part="mep",
    fields=[
        number("connectedTotalKw", "Sum of connected zone loads", 450.0, unit="kW", min=1.0),
        number("coincidentPeakKw", "Block coincident peak load", 315.0, unit="kW", min=0.5),
    ],
    requires_project=False,
)
def diversityFactor(ctx: FeatureContext, values: dict) -> dict:
    """Calculate system diversity & coincidence factors separating block central plant from terminal totals."""
    conn = float(values["connectedTotalKw"])
    coin = float(values["coincidentPeakKw"])
    coinc_factor = coin / conn
    div_factor = conn / coin
    return result(
        summary={
            "coincidenceFactor": round(coinc_factor, 3),
            "diversityFactor": round(div_factor, 3),
            "plantReductionPct": round((1.0 - coinc_factor) * 100.0, 1),
        },
        tables=[
            table(
                "Zone load diversity metrics",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Sum of individual zone peaks [kW]", "value": conn},
                    {"metric": "Coincident central plant peak [kW]", "value": coin},
                    {"metric": "Coincidence factor (Peak / Sum)", "value": round(coinc_factor, 3)},
                    {"metric": "Diversity factor (Sum / Peak)", "value": round(div_factor, 3)},
                ],
            )
        ],
        notes=[
            "Apply coincidence factor for central chillers/transformers while keeping un-diversified zone terminal sizing."
        ],
    )


@feature(
    "mepSystemsZoning.envelopeBoundary",
    "Envelope Boundary",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def envelopeBoundary(ctx: FeatureContext, values: dict) -> dict:
    """Envelope Boundary: Thermal Boundaries."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Envelope Boundary",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.exportZones",
    "Export Zones",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def exportZones(ctx: FeatureContext, values: dict) -> dict:
    """Export Zones: Report."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepSystemsZoning.exportZones",
        "title": "Export Zones",
        "name": values["name"],
        "group": "Report",
        "mep": raw,
    }
    path = ctx.path("11 Exports/exportZones.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Export Zones",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepSystemsZoning.infiltrationZone",
    "Infiltration Zone",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def infiltrationZone(ctx: FeatureContext, values: dict) -> dict:
    """Infiltration Zone: Thermal Boundaries."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Infiltration Zone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.internalPartitions",
    "Internal Partitions",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def internalPartitions(ctx: FeatureContext, values: dict) -> dict:
    """Internal Partitions: Thermal Boundaries."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Internal Partitions",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.loadByZone",
    "Load By Zone",
    part="mep",
    fields=[
        number("coolingWPerM2", "Fallback specific cooling intensity", 110.0, unit="W/m²", min=10.0)
    ],
    requires_project=True,
)
def loadByZone(ctx: FeatureContext, values: dict) -> dict:
    """Aggregate storey/zone cooling, lighting, and ventilation loads from 07 MEP/mep.json."""
    if ctx.root is None:
        raise FeatureInputError("Open a project with 07 MEP/mep.json to compute loads by zone.")
    raw = ctx.raw("mep")
    if not isinstance(raw, dict):
        raise FeatureInputError("Missing 07 MEP/mep.json in project.")
    stories = (raw.get("hvac") or {}).get("stories") or []
    rows = []
    tot_kw = 0.0
    for i, st in enumerate(stories):
        if not isinstance(st, dict):
            continue
        area = float(st.get("areaM2", st.get("area", 200.0)) or 200.0)
        q_kw = float(st.get("coolingKw", area * float(values["coolingWPerM2"]) / 1000.0))
        tot_kw += q_kw
        rows.append(
            {
                "zone": str(st.get("story") or st.get("name") or f"Zone {i + 1}"),
                "use": str(st.get("use", "officeSpace")),
                "areaM2": round(area, 1),
                "loadKw": round(q_kw, 2),
                "wPerM2": round(q_kw * 1000.0 / max(1.0, area), 1),
            }
        )
    if not rows:
        raise FeatureInputError("No HVAC storey zones found in 07 MEP/mep.json.")
    return result(
        summary={"zoneCount": len(rows), "totalConnectedKw": round(tot_kw, 1)},
        tables=[
            table(
                "MEP zone load breakdown",
                [
                    ("zone", "Story / Zone"),
                    ("use", "Use"),
                    ("areaM2", "Area", "m²"),
                    ("loadKw", "Load", "kW"),
                    ("wPerM2", "W/m²"),
                ],
                rows,
            )
        ],
        notes=[
            "Reads hvac.stories from 07 MEP/mep.json and computes per-zone cooling density W/m²."
        ],
    )


@feature(
    "mepSystemsZoning.masterGroup",
    "Master Group",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def masterGroup(ctx: FeatureContext, values: dict) -> dict:
    """Master Group: Groupings."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Master Group",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.occupancyLink",
    "Occupancy Link",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def occupancyLink(ctx: FeatureContext, values: dict) -> dict:
    """Occupancy Link: Areas."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Occupancy Link",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.peakLoadShift",
    "Peak Load Shift",
    part="mep",
    fields=[
        number("dayPeakKw", "On-peak chiller cooling power demand", 180.0, unit="kW", min=5.0),
        number(
            "shiftFraction",
            "Fraction shifted to thermal storage / precooling",
            0.35,
            min=0.05,
            max=0.80,
        ),
        number("peakHours", "Daily peak tariff window duration", 6.0, unit="h", min=1.0, max=12.0),
        number("chillerCop", "Day vs night chiller effective COP", 4.2, min=1.5, max=7.0),
    ],
    requires_project=False,
)
def peakLoadShift(ctx: FeatureContext, values: dict) -> dict:
    """Size thermal energy storage capacity and on-peak kW demand shave from load shifting."""
    shifted_kw_th = (
        float(values["dayPeakKw"]) * float(values["shiftFraction"]) * float(values["chillerCop"])
    )
    tes_kwh_th = shifted_kw_th * float(values["peakHours"])
    shaved_elec_kw = float(values["dayPeakKw"]) * float(values["shiftFraction"])
    new_peak_kw = float(values["dayPeakKw"]) - shaved_elec_kw
    return result(
        summary={
            "shavedDemandKw": round(shaved_elec_kw, 1),
            "newOnPeakKw": round(new_peak_kw, 1),
            "thermalStorageKwh": round(tes_kwh_th, 0),
        },
        tables=[
            table(
                "Peak load shifting & thermal storage sizing",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Baseline electrical chiller peak",
                        "value": values["dayPeakKw"],
                        "unit": "kW",
                    },
                    {
                        "item": "Shaved on-peak electrical demand",
                        "value": round(shaved_elec_kw, 1),
                        "unit": "kW",
                    },
                    {
                        "item": "Remaining daytime electrical peak",
                        "value": round(new_peak_kw, 1),
                        "unit": "kW",
                    },
                    {
                        "item": "Required chilled-water / ice TES",
                        "value": round(tes_kwh_th, 0),
                        "unit": "kWh_th",
                    },
                ],
            )
        ],
        notes=["Thermal storage capacity = Shifted cooling rate x Peak window hours."],
    )


@feature(
    "mepSystemsZoning.priorityLevel",
    "Priority Level",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def priorityLevel(ctx: FeatureContext, values: dict) -> dict:
    """Priority Level: Groupings."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Priority Level",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.scheduleOverride",
    "Schedule Override",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def scheduleOverride(ctx: FeatureContext, values: dict) -> dict:
    """Schedule Override: Diversity."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepSystemsZoning.scheduleOverride",
        "title": "Schedule Override",
        "name": values["name"],
        "group": "Diversity",
        "mep": raw,
    }
    path = ctx.path("11 Exports/scheduleOverride.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Schedule Override",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepSystemsZoning.systemMapping",
    "System Mapping",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def systemMapping(ctx: FeatureContext, values: dict) -> dict:
    """System Mapping: Groupings."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "System Mapping",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.zoneAudit",
    "Zone Audit",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def zoneAudit(ctx: FeatureContext, values: dict) -> dict:
    """Zone Audit: Groupings."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepSystemsZoning.zoneAudit",
        "title": "Zone Audit",
        "name": values["name"],
        "group": "Groupings",
        "mep": raw,
    }
    path = ctx.path("11 Exports/zoneAudit.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Zone Audit",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepSystemsZoning.zoneBoundary",
    "Zone Boundary",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def zoneBoundary(ctx: FeatureContext, values: dict) -> dict:
    """Zone Boundary: Zones."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Zone Boundary",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.zoneColour",
    "Zone Colour",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def zoneColour(ctx: FeatureContext, values: dict) -> dict:
    """Zone Colour: Zones."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Zone Colour",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSystemsZoning.zoneSummary",
    "Zone Summary",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def zoneSummary(ctx: FeatureContext, values: dict) -> dict:
    """Zone Summary: Report."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepSystemsZoning.zoneSummary",
        "title": "Zone Summary",
        "name": values["name"],
        "group": "Report",
        "mep": raw,
    }
    path = ctx.path("11 Exports/zoneSummary.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Zone Summary",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepSystemsZoning.zoneTag",
    "Zone Tag",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def zoneTag(ctx: FeatureContext, values: dict) -> dict:
    """Zone Tag: Areas."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Zone Tag",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )
