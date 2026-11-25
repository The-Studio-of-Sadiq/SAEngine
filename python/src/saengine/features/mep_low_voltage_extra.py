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
    fields=[
        number("endpoints", "Active endpoints / IP cameras / APs", 24, min=1, max=500),
        number(
            "perEndpointMbps", "Average stream throughput per endpoint", 12.0, unit="Mbps", min=0.5
        ),
        number("uplinkGbps", "Core switch uplink capacity", 1.0, unit="Gbps", min=0.1),
        number(
            "maxUtilPct", "Target peak link utilisation limit", 70.0, unit="%", min=20.0, max=95.0
        ),
    ],
    requires_project=False,
)
def bandwidthCheck(ctx: FeatureContext, values: dict) -> dict:
    """Check structured-cabling uplink throughput utilisation and spare bandwidth headroom."""
    tot_mbps = int(values["endpoints"]) * float(values["perEndpointMbps"])
    cap_mbps = float(values["uplinkGbps"]) * 1000.0
    util_pct = (tot_mbps / cap_mbps) * 100.0
    ok = util_pct <= float(values["maxUtilPct"])
    min_uplink_gbps = tot_mbps / (float(values["maxUtilPct"]) / 100.0 * 1000.0)
    return result(
        summary={
            "demandMbps": round(tot_mbps, 1),
            "uplinkUtilisationPct": round(util_pct, 1),
            "compliant": ok,
            "recommendedUplinkGbps": round(min_uplink_gbps, 2),
        },
        tables=[
            table(
                "ELV network bandwidth check",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Aggregate endpoint demand",
                        "value": round(tot_mbps, 1),
                        "unit": "Mbps",
                    },
                    {"item": "Provisioned uplink", "value": cap_mbps, "unit": "Mbps"},
                    {"item": "Uplink utilisation", "value": round(util_pct, 1), "unit": "%"},
                    {
                        "item": "Min uplink at target cap",
                        "value": round(min_uplink_gbps, 2),
                        "unit": "Gbps",
                    },
                    {"item": "Status", "value": "PASS" if ok else "UPGRADE UPLINK", "unit": "-"},
                ],
            )
        ],
        notes=[
            "Maintain <= 70% utilisation on uplinks for burst tolerance and multicast overhead."
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
    fields=[
        number("fiberLengthM", "Optical link path length", 350.0, unit="m", min=5.0),
        number("attenuationDbPerKm", "Fiber attenuation rate", 3.0, unit="dB/km", min=0.2),
        number("connectorPairs", "Mated connector pairs", 4, min=0, max=20),
        number("fusionSplices", "Fusion splices", 2, min=0, max=30),
        number("linkBudgetDb", "Transceiver optical power budget", 7.5, unit="dB", min=1.0),
    ],
    requires_project=False,
)
def signalLossCheck(ctx: FeatureContext, values: dict) -> dict:
    """Calculate optical fiber / structured link insertion loss budget and margin."""
    fiber_loss = (float(values["fiberLengthM"]) / 1000.0) * float(values["attenuationDbPerKm"])
    conn_loss = int(values["connectorPairs"]) * 0.50
    splice_loss = int(values["fusionSplices"]) * 0.10
    margin_db = 1.50
    total_loss = fiber_loss + conn_loss + splice_loss + margin_db
    headroom = float(values["linkBudgetDb"]) - total_loss
    ok = headroom >= 0.0
    return result(
        summary={
            "linkLossDb": round(total_loss, 2),
            "budgetDb": float(values["linkBudgetDb"]),
            "marginDb": round(headroom, 2),
            "compliant": ok,
        },
        tables=[
            table(
                "Optical link attenuation budget",
                [("component", "Loss Component"), ("lossDb", "Loss", "dB")],
                [
                    {"component": "Cable attenuation", "lossDb": round(fiber_loss, 2)},
                    {"component": "Connectors (0.5 dB/pair)", "lossDb": round(conn_loss, 2)},
                    {"component": "Fusion splices (0.1 dB)", "lossDb": round(splice_loss, 2)},
                    {"component": "Ageing & bend margin", "lossDb": margin_db},
                    {"component": "Total link loss", "lossDb": round(total_loss, 2)},
                ],
            )
        ],
        notes=[
            "Assumes 0.5 dB per mated LC/SC pair, 0.1 dB per fusion splice, and 1.5 dB ageing allowance."
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
    fields=[
        number("criticalLoadKw", "Critical IT / ELV load", 24.0, unit="kW", min=0.5),
        number("autonomyMin", "Battery backup autonomy", 15.0, unit="min", min=5.0, max=240.0),
        number("loadPf", "UPS output power factor", 0.90, min=0.7, max=1.0),
        number("dcBusV", "Battery string nominal DC bus", 240.0, unit="V", min=24.0),
    ],
    requires_project=False,
)
def upsSizing(ctx: FeatureContext, values: dict) -> dict:
    """Size critical-power UPS frame kVA and battery bank via saengine.electrical.supply.ups."""
    from saengine.electrical import supply

    kw = float(values["criticalLoadKw"])
    autonomy = float(values["autonomyMin"])
    res = supply.ups(kw, autonomy) or {}
    req_kva = kw / float(values["loadPf"])
    batt_vah = kw * 1000.0 * (autonomy / 60.0) / 0.88
    batt_ah = batt_vah / float(values["dcBusV"])
    return result(
        summary={
            "requiredKva": round(req_kva, 2),
            "standardFrameKva": res.get("rating", res.get("kva")),
            "batteryAh": round(batt_ah, 1),
            "autonomyMin": autonomy,
        },
        tables=[
            table(
                "UPS & battery sizing",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Critical real power", "value": kw, "unit": "kW"},
                    {"parameter": "UPS apparent rating", "value": round(req_kva, 2), "unit": "kVA"},
                    {
                        "parameter": "Selected standard frame",
                        "value": res.get("rating", round(req_kva, 1)),
                        "unit": "kVA",
                    },
                    {
                        "parameter": "Battery energy required (η=88%)",
                        "value": round(batt_vah / 1000.0, 2),
                        "unit": "kVAh",
                    },
                    {
                        "parameter": "Bank capacity at DC bus",
                        "value": round(batt_ah, 1),
                        "unit": "Ah",
                    },
                ],
            )
        ],
        notes=[
            "UPS kVA sized via saengine.electrical.supply.ups; size rectifier & room cooling for full-load heat loss."
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
