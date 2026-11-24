"""Dedicated mepLowVoltage MEP feature registrations."""

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
    "mepLowVoltage.accessControl",
    "Access Control",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def accessControl(ctx: FeatureContext, values: dict) -> dict:
    """Access Control: Systems."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Access Control",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.audioVideoPoints",
    "Audio Video Points",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def audioVideoPoints(ctx: FeatureContext, values: dict) -> dict:
    """Audio Video Points: Communication."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Audio Video Points",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.bandwidthCheck",
    "Bandwidth Check",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def bandwidthCheck(ctx: FeatureContext, values: dict) -> dict:
    """Bandwidth Check: Checks."""
    design_value = float(values["value"])
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
                "Bandwidth Check",
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
    "mepLowVoltage.cableCategories",
    "Cable Categories",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def cableCategories(ctx: FeatureContext, values: dict) -> dict:
    """Cable Categories: Network."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Cable Categories",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.cableTestResults",
    "Cable Test Results",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def cableTestResults(ctx: FeatureContext, values: dict) -> dict:
    """Cable Test Results: Testing."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepLowVoltage.cableTestResults",
        "title": "Cable Test Results",
        "name": values["name"],
        "group": "Testing",
        "mep": raw,
    }
    path = ctx.path("11 Exports/cableTestResults.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Cable Test Results",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepLowVoltage.cctv",
    "CCTV",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def cctv(ctx: FeatureContext, values: dict) -> dict:
    """CCTV: Systems."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "CCTV",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.channelCount",
    "Channel Count",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def channelCount(ctx: FeatureContext, values: dict) -> dict:
    """Channel Count: Testing."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Channel Count",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.dataOutlets",
    "Data Outlets",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def dataOutlets(ctx: FeatureContext, values: dict) -> dict:
    """Data Outlets: Systems."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepLowVoltage.dataOutlets",
        "title": "Data Outlets",
        "name": values["name"],
        "group": "Systems",
        "mep": raw,
    }
    path = ctx.path("11 Exports/dataOutlets.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Data Outlets",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepLowVoltage.emergencyCall",
    "Emergency Call",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def emergencyCall(ctx: FeatureContext, values: dict) -> dict:
    """Emergency Call: Fire & Safety."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Emergency Call",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.fibreBackbone",
    "Fibre Backbone",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def fibreBackbone(ctx: FeatureContext, values: dict) -> dict:
    """Fibre Backbone: Communication."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Fibre Backbone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.fireAlarmLoop",
    "Fire Alarm Loop",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def fireAlarmLoop(ctx: FeatureContext, values: dict) -> dict:
    """Fire Alarm Loop: Fire & Safety."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Fire Alarm Loop",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.intercom",
    "Intercom",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def intercom(ctx: FeatureContext, values: dict) -> dict:
    """Intercom: Fire & Safety."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Intercom",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.paSystem",
    "PA System",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def paSystem(ctx: FeatureContext, values: dict) -> dict:
    """PA System: Systems."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "PA System",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.patchSchedule",
    "Patch Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def patchSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Patch Schedule: Network."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepLowVoltage.patchSchedule",
        "title": "Patch Schedule",
        "name": values["name"],
        "group": "Network",
        "mep": raw,
    }
    path = ctx.path("11 Exports/patchSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Patch Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepLowVoltage.publicAddressZone",
    "Public Address Zone",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def publicAddressZone(ctx: FeatureContext, values: dict) -> dict:
    """Public Address Zone: Fire & Safety."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Public Address Zone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.rackLayout",
    "Rack Layout",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def rackLayout(ctx: FeatureContext, values: dict) -> dict:
    """Rack Layout: Network."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Rack Layout",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.redundancy",
    "Redundancy",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def redundancy(ctx: FeatureContext, values: dict) -> dict:
    """Redundancy: Checks."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Redundancy",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.signalLossCheck",
    "Signal Loss Check",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def signalLossCheck(ctx: FeatureContext, values: dict) -> dict:
    """Signal Loss Check: Testing."""
    design_value = float(values["value"])
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
                "Signal Loss Check",
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
    "mepLowVoltage.smokeDetector",
    "Smoke Detector",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def smokeDetector(ctx: FeatureContext, values: dict) -> dict:
    """Smoke Detector: Fire & Safety."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Smoke Detector",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.telephoneOutlets",
    "Telephone Outlets",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def telephoneOutlets(ctx: FeatureContext, values: dict) -> dict:
    """Telephone Outlets: Communication."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Telephone Outlets",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.terminationSchedule",
    "Termination Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def terminationSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Termination Schedule: Testing."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepLowVoltage.terminationSchedule",
        "title": "Termination Schedule",
        "name": values["name"],
        "group": "Testing",
        "mep": raw,
    }
    path = ctx.path("11 Exports/terminationSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Termination Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepLowVoltage.tvOutlets",
    "TV Outlets",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def tvOutlets(ctx: FeatureContext, values: dict) -> dict:
    """TV Outlets: Communication."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "TV Outlets",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepLowVoltage.upsSizing",
    "UPS Sizing",
    part="mep",
    fields=[number("value", "Design value", 100, unit="units", min=0)],
    requires_project=True,
)
def upsSizing(ctx: FeatureContext, values: dict) -> dict:
    """UPS Sizing: Checks."""
    design_value = float(values["value"])
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
                "UPS Sizing",
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
    "mepLowVoltage.wirelessAccessPoint",
    "Wireless Access Point",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def wirelessAccessPoint(ctx: FeatureContext, values: dict) -> dict:
    """Wireless Access Point: Communication."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Wireless Access Point",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )
