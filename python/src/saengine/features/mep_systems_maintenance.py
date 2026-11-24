"""Asset lifecycle, inspection and maintenance planning for MEP equipment."""

from __future__ import annotations

import json

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)


def _equipment(ctx: FeatureContext) -> list[dict]:
    raw = ctx.raw("mep")
    if not isinstance(raw, dict):
        raise FeatureInputError("Add the MEP model before reviewing equipment assets.")
    records = raw.get("equipment", [])
    if not isinstance(records, list) or not records:
        raise FeatureInputError("Add at least one equipment item to the MEP model.")
    return [item for item in records if isinstance(item, dict)]


def _asset(ctx: FeatureContext, asset_id: str) -> dict:
    for item in _equipment(ctx):
        if str(item.get("id", "")) == asset_id:
            return item
    raise FeatureInputError(f"Equipment asset {asset_id!r} was not found in the MEP model.")


def _export(ctx: FeatureContext, filename: str, payload: dict) -> str:
    path = ctx.path(f"11 Exports/{filename}")
    if path is None:
        raise FeatureInputError("Open a project before creating an equipment record.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(path)


@feature(
    "mepSystemsMaintenance.registerAsset",
    "Register Asset",
    part="mep",
    fields=[text("assetId", "Equipment ID", "equipment-1")],
)
def register_asset(ctx: FeatureContext, v: dict) -> dict:
    """Create an asset register row using the selected equipment's model properties."""
    item = _asset(ctx, v["assetId"])
    row = {
        "id": item.get("id"),
        "name": item.get("name") or item.get("kind"),
        "kind": item.get("kind"),
        "story": item.get("story"),
        "operatingWeightKn": item.get("operatingWeight"),
        "footprintM2": (item.get("length", 0) * item.get("width", 0) / 1_000_000),
    }
    export = _export(ctx, "mep-asset-register.json", {"assets": [row]})
    return result(
        {"assetId": str(item.get("id")), "footprintM2": row["footprintM2"], "exportPath": export},
        [
            table(
                "Registered model asset",
                [("property", "Property"), ("value", "Value")],
                [{"property": key, "value": value} for key, value in row.items()],
            )
        ],
        ["The asset data are taken from the selected MEP equipment model element."],
    )


def _read_register(ctx: FeatureContext, filename: str, key: str) -> list[dict]:
    path = ctx.path(f"11 Exports/{filename}")
    if path is None or not path.exists():
        return []
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        rows = loaded.get(key, []) if isinstance(loaded, dict) else []
        return [r for r in rows if isinstance(r, dict)]
    except ValueError:
        return []


@feature(
    "mepSystemsMaintenance.assetTag",
    "Asset Tag",
    part="mep",
    fields=[
        text("assetId", "Equipment ID", "equipment-1"),
        text("tag", "Maintenance tag", "MEP-001"),
    ],
)
def asset_tag(ctx: FeatureContext, v: dict) -> dict:
    """Assign a unique maintenance tag to a real MEP equipment item and persist the tag register."""
    item = _asset(ctx, v["assetId"])
    tag = v["tag"].strip()
    if not tag:
        raise FeatureInputError("Enter a non-empty maintenance tag.")
    existing = _read_register(ctx, "mep-asset-tags.json", "assets")
    for row in existing:
        if row.get("tag") == tag and str(row.get("id")) != str(item["id"]):
            raise FeatureInputError(
                f"Tag {tag!r} is already assigned to equipment {row.get('id')}."
            )
    updated = {str(r.get("id")): r for r in existing if r.get("id") is not None}
    updated[str(item["id"])] = {
        "id": item["id"],
        "tag": tag,
        "name": item.get("name") or item.get("kind", ""),
        "kind": item.get("kind", ""),
        "story": item.get("story", ""),
    }
    rows = list(updated.values())
    path = _export(ctx, "mep-asset-tags.json", {"assets": rows})
    return result(
        {"assetId": str(item["id"]), "tag": tag, "taggedCount": len(rows), "exportPath": path},
        [
            table(
                "Asset tag register",
                [("id", "Equipment ID"), ("tag", "Tag"), ("kind", "Kind"), ("story", "Story")],
                rows,
            )
        ],
        [f"Validated tag uniqueness across {len(rows)} equipment asset(s)."],
    )


@feature(
    "mepSystemsMaintenance.assetLocation",
    "Asset Location",
    part="mep",
    fields=[
        text("assetId", "Equipment ID", "equipment-1"),
        text("route", "Access route", "Plantroom access"),
    ],
)
def asset_location(ctx: FeatureContext, v: dict) -> dict:
    """Report the selected equipment's model level and its entered maintenance access route."""
    item = _asset(ctx, v["assetId"])
    return result(
        {
            "assetId": str(item["id"]),
            "story": str(item.get("story", "")),
            "accessRoute": v["route"],
        },
        [
            table(
                "Asset location",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Story", "value": item.get("story")},
                    {"property": "Access route", "value": v["route"]},
                ],
            )
        ],
        [
            "The story is read from the MEP equipment model; the route describes the engineer's access note."
        ],
    )


@feature(
    "mepSystemsMaintenance.criticalityRating",
    "Criticality Rating",
    part="mep",
    fields=[
        select(
            "safety",
            "Safety consequence",
            [("low", "Low"), ("moderate", "Moderate"), ("high", "High")],
        ),
        select(
            "service",
            "Service consequence",
            [("low", "Low"), ("moderate", "Moderate"), ("high", "High")],
        ),
        select(
            "redundancy",
            "Available redundancy",
            [("none", "None"), ("partial", "Partial"), ("full", "Full")],
        ),
    ],
    requires_project=False,
)
def criticality_rating(ctx: FeatureContext, v: dict) -> dict:
    """Rank operational criticality from safety, service impact and redundancy inputs."""
    scale = {"low": 1, "moderate": 2, "high": 3}
    redundancy_credit = {"none": 2, "partial": 1, "full": 0}
    score = scale[v["safety"]] + scale[v["service"]] + redundancy_credit[v["redundancy"]]
    band = "high" if score >= 7 else "moderate" if score >= 5 else "low"
    return result(
        {"criticalityScore": score, "criticalityBand": band},
        [
            table(
                "Criticality factors",
                [("factor", "Factor"), ("rating", "Rating")],
                [
                    {"factor": "Safety", "rating": v["safety"]},
                    {"factor": "Service", "rating": v["service"]},
                    {"factor": "Redundancy", "rating": v["redundancy"]},
                ],
            )
        ],
        ["Ordinal screening score only; confirm consequence categories with the asset owner."],
    )


@feature(
    "mepSystemsMaintenance.serviceInterval",
    "Service Interval",
    part="mep",
    fields=[
        number("intervalMonths", "Service interval", 6, unit="months", min=1),
        number("planningHorizonYears", "Planning horizon", 5, unit="years", min=1),
    ],
    requires_project=False,
)
def service_interval(ctx: FeatureContext, v: dict) -> dict:
    """Calculate planned service count and the elapsed spacing over a planning horizon."""
    horizon_months = v["planningHorizonYears"] * 12
    count = int(horizon_months // v["intervalMonths"])
    return result(
        {
            "serviceIntervalMonths": v["intervalMonths"],
            "plannedServices": count,
            "planningHorizonMonths": horizon_months,
        },
        [
            table(
                "Service plan",
                [("serviceNumber", "Service number"), ("month", "Month")],
                [
                    {"serviceNumber": i, "month": i * v["intervalMonths"]}
                    for i in range(1, count + 1)
                ],
            )
        ],
        ["The count includes services due on or before the horizon end."],
    )


@feature(
    "mepSystemsMaintenance.workOrder",
    "Work Order",
    part="mep",
    fields=[
        text("assetId", "Equipment ID", "equipment-1"),
        text("task", "Service task", "Inspect and service"),
        select(
            "priority",
            "Priority",
            [("Routine", "Routine"), ("Urgent", "Urgent"), ("Shutdown", "Shutdown")],
            "Routine",
        ),
    ],
)
def work_order(ctx: FeatureContext, v: dict) -> dict:
    """Issue a numbered work order linked to real equipment operating data and append to WO register."""
    from datetime import date

    item = _asset(ctx, v["assetId"])
    task = v["task"].strip()
    if not task:
        raise FeatureInputError("Enter the maintenance task for the work order.")
    orders = _read_register(ctx, "mep-work-order.json", "workOrders")
    wo_id = f"WO-{len(orders) + 1:04d}"
    order = {
        "woId": wo_id,
        "assetId": item["id"],
        "assetName": item.get("name") or item.get("kind", ""),
        "task": task,
        "priority": v["priority"],
        "story": item.get("story", ""),
        "operatingWeightKn": item.get("operatingWeight", 0.0),
        "issuedDate": date.today().isoformat(),
    }
    orders.append(order)
    path = _export(ctx, "mep-work-order.json", {"workOrders": orders})
    return result(
        {
            "woId": wo_id,
            "assetId": str(item["id"]),
            "totalWorkOrders": len(orders),
            "exportPath": path,
        },
        [
            table(
                "Work order register",
                [
                    ("woId", "WO #"),
                    ("assetId", "Equipment"),
                    ("priority", "Priority"),
                    ("task", "Task"),
                    ("issuedDate", "Issued"),
                ],
                orders[-25:],
            )
        ],
        [f"Issued {wo_id} against {item['id']} ({len(orders)} total in register)."],
    )


@feature(
    "mepSystemsMaintenance.serviceChecklist",
    "Service Checklist",
    part="mep",
    fields=[
        select(
            "assetKind",
            "Equipment kind",
            [
                ("pump", "Pump"),
                ("ahu", "Air handling unit"),
                ("chiller", "Chiller"),
                ("other", "Other"),
            ],
        )
    ],
    requires_project=False,
)
def service_checklist(ctx: FeatureContext, v: dict) -> dict:
    """Build a maintenance checklist targeted to the selected equipment category."""
    tasks = {
        "pump": [
            "Inspect seals and leakage",
            "Check bearing noise and vibration",
            "Verify duty and standby changeover",
        ],
        "ahu": [
            "Inspect filters and differential pressure",
            "Check belt or drive condition",
            "Verify condensate drainage",
        ],
        "chiller": [
            "Review refrigerant and water-side condition",
            "Inspect heat exchanger surfaces",
            "Verify safeties and alarms",
        ],
        "other": [
            "Inspect visible condition",
            "Verify controls and alarms",
            "Record operating condition",
        ],
    }[v["assetKind"]]
    return result(
        {"checklistItems": len(tasks), "equipmentKind": v["assetKind"]},
        [
            table(
                "Service tasks",
                [("sequence", "Sequence"), ("task", "Task")],
                [{"sequence": i, "task": task} for i, task in enumerate(tasks, 1)],
            )
        ],
        ["Checklist is a planning aid; use the equipment manufacturer's maintenance instructions."],
    )


@feature(
    "mepSystemsMaintenance.serviceHistory",
    "Service History",
    part="mep",
    fields=[text("assetId", "Equipment ID", "equipment-1")],
)
def service_history(ctx: FeatureContext, v: dict) -> dict:
    """Review service records associated with the selected equipment id."""
    _asset(ctx, v["assetId"])
    raw = ctx.raw("mep") or {}
    records = raw.get("maintenanceHistory", [])
    if not isinstance(records, list):
        raise FeatureInputError("The MEP maintenanceHistory data must be a list.")
    matched = [
        r for r in records if isinstance(r, dict) and str(r.get("assetId", "")) == v["assetId"]
    ]
    return result(
        {"assetId": v["assetId"], "serviceRecordCount": len(matched)},
        [
            table(
                "Service history",
                [("date", "Date"), ("task", "Task"), ("status", "Status")],
                [
                    {
                        "date": r.get("date", ""),
                        "task": r.get("task", ""),
                        "status": r.get("status", ""),
                    }
                    for r in matched
                ],
            )
        ],
        ["Only records already associated with this asset are listed."],
    )


@feature(
    "mepSystemsMaintenance.sparePart",
    "Spare Part",
    part="mep",
    fields=[
        text("partNumber", "Part number", "PART-001"),
        text("description", "Part description", "Seal kit"),
        number("quantity", "Quantity held", 1, unit="items", min=0),
    ],
    requires_project=False,
)
def spare_part(ctx: FeatureContext, v: dict) -> dict:
    """Calculate the inventory value basis for a nominated critical spare quantity."""
    if not v["partNumber"].strip() or not v["description"].strip():
        raise FeatureInputError("Enter both a spare part number and description.")
    return result(
        {"partNumber": v["partNumber"].strip(), "quantityHeld": v["quantity"]},
        [
            table(
                "Spare part record",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Part number", "value": v["partNumber"].strip()},
                    {"property": "Description", "value": v["description"].strip()},
                    {"property": "Quantity", "value": v["quantity"]},
                ],
            )
        ],
        ["Confirm compatibility and criticality against the equipment manufacturer's parts list."],
    )


@feature(
    "mepSystemsMaintenance.stockLevel",
    "Stock Level",
    part="mep",
    fields=[
        number("onHand", "On-hand stock", 4, unit="items", min=0),
        number("allocated", "Allocated stock", 1, unit="items", min=0),
    ],
    requires_project=False,
)
def stock_level(ctx: FeatureContext, v: dict) -> dict:
    """Calculate unallocated spare stock from current inventory quantities."""
    if v["allocated"] > v["onHand"]:
        raise FeatureInputError("Allocated quantity cannot exceed on-hand stock.")
    available = v["onHand"] - v["allocated"]
    return result(
        {"availableItems": available, "allocatedItems": v["allocated"]},
        [
            table(
                "Stock position",
                [("quantity", "Quantity", "items")],
                [{"quantity": v["onHand"]}, {"quantity": -v["allocated"]}, {"quantity": available}],
            )
        ],
        ["Available stock equals on-hand quantity less committed allocations."],
    )


@feature(
    "mepSystemsMaintenance.reorderPoint",
    "Reorder Point",
    part="mep",
    fields=[
        number("dailyUse", "Average use", 0.2, unit="items/day", min=0),
        number("leadTime", "Supplier lead time", 14, unit="days", min=0),
        number("safetyStock", "Safety stock", 2, unit="items", min=0),
    ],
    requires_project=False,
)
def reorder_point(ctx: FeatureContext, v: dict) -> dict:
    """Set an inventory replenishment trigger from demand during lead time and safety stock."""
    demand = v["dailyUse"] * v["leadTime"]
    point = demand + v["safetyStock"]
    return result(
        {"leadTimeDemandItems": demand, "reorderPointItems": point},
        [
            table(
                "Replenishment basis",
                [("component", "Component"), ("quantity", "Quantity", "items")],
                [
                    {"component": "Lead-time demand", "quantity": demand},
                    {"component": "Safety stock", "quantity": v["safetyStock"]},
                    {"component": "Reorder point", "quantity": point},
                ],
            )
        ],
        ["Average usage is assumed uniform over supplier lead time."],
    )


@feature(
    "mepSystemsMaintenance.supplierContact",
    "Supplier Contact",
    part="mep",
    fields=[
        text("supplier", "Supplier", ""),
        text("contact", "Contact details", ""),
        text("partNumber", "Part number", ""),
    ],
    requires_project=False,
)
def supplier_contact(ctx: FeatureContext, v: dict) -> dict:
    """Validate and present supplier contact information against its spare part reference."""
    if not all(v[key].strip() for key in ("supplier", "contact", "partNumber")):
        raise FeatureInputError("Enter a supplier, contact detail and spare part number.")
    return result(
        {"supplier": v["supplier"].strip(), "partNumber": v["partNumber"].strip()},
        [
            table(
                "Supplier reference",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Supplier", "value": v["supplier"].strip()},
                    {"property": "Contact", "value": v["contact"].strip()},
                    {"property": "Part number", "value": v["partNumber"].strip()},
                ],
            )
        ],
        ["Verify contact details before relying on the supplier record."],
    )


@feature(
    "mepSystemsMaintenance.vibrationSensor",
    "Vibration Sensor",
    part="mep",
    fields=[
        number("velocityRms", "Vibration velocity", 2.8, unit="mm/s", min=0),
        number("alarmLimit", "Entered alarm limit", 4.5, unit="mm/s", min=0),
    ],
    requires_project=False,
)
def vibration_sensor(ctx: FeatureContext, v: dict) -> dict:
    """Compare measured vibration velocity with the entered machinery alarm threshold."""
    alarm = v["velocityRms"] >= v["alarmLimit"]
    return result(
        {"velocityRms": v["velocityRms"], "alarmLimitMmPerS": v["alarmLimit"], "alarm": alarm},
        [
            table(
                "Vibration reading",
                [("measure", "Measure"), ("value", "Value", "mm/s")],
                [
                    {"measure": "RMS velocity", "value": v["velocityRms"]},
                    {"measure": "Alarm limit", "value": v["alarmLimit"]},
                ],
            )
        ],
        [
            "The alert threshold must be selected for the machine, sensor location and measurement bandwidth."
        ],
    )


@feature(
    "mepSystemsMaintenance.oilAnalysis",
    "Oil Analysis",
    part="mep",
    fields=[
        number("waterPpm", "Water content", 100, unit="ppm", min=0),
        number("limitPpm", "Entered water limit", 500, unit="ppm", min=0),
        number("viscosityMeasured", "Measured viscosity", 46, unit="mm²/s", min=0.01),
        number("viscosityNominal", "Nominal viscosity", 46, unit="mm²/s", min=0.01),
    ],
    requires_project=False,
)
def oil_analysis(ctx: FeatureContext, v: dict) -> dict:
    """Screen lubricant water content and viscosity deviation against entered acceptance values."""
    deviation = (v["viscosityMeasured"] - v["viscosityNominal"]) / v["viscosityNominal"] * 100
    return result(
        {
            "waterPpm": v["waterPpm"],
            "waterLimitExceeded": v["waterPpm"] > v["limitPpm"],
            "viscosityDeviationPercent": deviation,
        },
        [
            table(
                "Oil condition",
                [("parameter", "Parameter"), ("measured", "Measured"), ("limit", "Entered limit")],
                [
                    {"parameter": "Water", "measured": v["waterPpm"], "limit": v["limitPpm"]},
                    {
                        "parameter": "Viscosity",
                        "measured": v["viscosityMeasured"],
                        "limit": v["viscosityNominal"],
                    },
                ],
            )
        ],
        [
            "Screening compares results with user-entered lubricant criteria; it is not a laboratory diagnosis."
        ],
    )


@feature(
    "mepSystemsMaintenance.thermalImaging",
    "Thermal Imaging",
    part="mep",
    fields=[
        number("hotspotC", "Hotspot temperature", 55, unit="°C"),
        number("referenceC", "Reference temperature", 35, unit="°C"),
    ],
    requires_project=False,
)
def thermal_imaging(ctx: FeatureContext, v: dict) -> dict:
    """Calculate temperature rise above the selected reference for thermographic screening."""
    rise = v["hotspotC"] - v["referenceC"]
    return result(
        {"hotspotC": v["hotspotC"], "temperatureRiseC": rise},
        [
            table(
                "Thermal comparison",
                [("location", "Location"), ("temperature", "Temperature", "°C")],
                [
                    {"location": "Hotspot", "temperature": v["hotspotC"]},
                    {"location": "Reference", "temperature": v["referenceC"]},
                ],
            )
        ],
        ["Compare equivalent operating states and emissivity-corrected measurements."],
    )


@feature(
    "mepSystemsMaintenance.assetDeprecation",
    "Asset Deprecation",
    part="mep",
    fields=[
        number("installedYears", "Elapsed service life", 5, unit="years", min=0),
        number("usefulLifeYears", "Expected useful life", 20, unit="years", min=0.1),
        number("replacementCost", "Replacement cost", 10000, unit="currency", min=0),
    ],
    requires_project=False,
)
def asset_deprecation(ctx: FeatureContext, v: dict) -> dict:
    """Estimate remaining useful life and straight-line depreciated replacement value."""
    remaining = max(0, v["usefulLifeYears"] - v["installedYears"])
    fraction = min(1, v["installedYears"] / v["usefulLifeYears"])
    return result(
        {
            "remainingLifeYears": remaining,
            "depreciatedValue": v["replacementCost"] * (1 - fraction),
            "lifeConsumedPercent": fraction * 100,
        },
        [
            table(
                "Lifecycle estimate",
                [("measure", "Measure"), ("value", "Value")],
                [
                    {"measure": "Remaining life [years]", "value": remaining},
                    {
                        "measure": "Depreciated value",
                        "value": v["replacementCost"] * (1 - fraction),
                    },
                ],
            )
        ],
        ["Straight-line age-based estimate; condition, inflation and residual value are excluded."],
    )


@feature(
    "mepSystemsMaintenance.failureMode",
    "Failure Mode",
    part="mep",
    fields=[
        text("failureMode", "Failure mode", "Bearing failure"),
        number("severity", "Severity", 5, min=1, max=10),
        number("occurrence", "Occurrence", 3, min=1, max=10),
        number("detectability", "Difficulty of detection", 4, min=1, max=10),
    ],
    requires_project=False,
)
def failure_mode(ctx: FeatureContext, v: dict) -> dict:
    """Calculate a screening risk-priority number from FMEA severity, occurrence and detectability."""
    rpn = v["severity"] * v["occurrence"] * v["detectability"]
    return result(
        {"riskPriorityNumber": rpn, "failureMode": v["failureMode"].strip()},
        [
            table(
                "FMEA factors",
                [("factor", "Factor"), ("rating", "Rating")],
                [
                    {"factor": "Severity", "rating": v["severity"]},
                    {"factor": "Occurrence", "rating": v["occurrence"]},
                    {"factor": "Detectability", "rating": v["detectability"]},
                ],
            )
        ],
        ["Use the organization's rating definitions; RPN alone does not determine acceptability."],
    )


@feature(
    "mepSystemsMaintenance.replacementPlan",
    "Replacement Plan",
    part="mep",
    fields=[
        number("currentAge", "Current age", 12, unit="years", min=0),
        number("life", "Expected life", 20, unit="years", min=0.1),
        number("replacementCost", "Replacement cost", 25000, unit="currency", min=0),
        number("annualEscalation", "Annual escalation", 0.03, min=0, max=1),
    ],
    requires_project=False,
)
def replacement_plan(ctx: FeatureContext, v: dict) -> dict:
    """Schedule an equipment replacement year and escalate its present replacement cost."""
    years = max(0, v["life"] - v["currentAge"])
    future_cost = v["replacementCost"] * (1 + v["annualEscalation"]) ** years
    return result(
        {"yearsToReplacement": years, "projectedCost": future_cost},
        [
            table(
                "Replacement forecast",
                [("measure", "Measure"), ("value", "Value")],
                [
                    {"measure": "Years to replacement", "value": years},
                    {"measure": "Projected cost", "value": future_cost},
                ],
            )
        ],
        ["Escalation is compounded annually; confirm service life and escalation assumptions."],
    )


@feature(
    "mepSystemsMaintenance.maintenanceLog",
    "Maintenance Log",
    part="mep",
    fields=[
        text("assetId", "Equipment ID", "equipment-1"),
        text("action", "Maintenance action", "Inspection"),
        text("technician", "Technician", ""),
    ],
)
def maintenance_log(ctx: FeatureContext, v: dict) -> dict:
    """Append a dated service entry tied to a model asset and maintain cumulative service count."""
    from datetime import date

    item = _asset(ctx, v["assetId"])
    action = v["action"].strip()
    tech = v["technician"].strip()
    if not action or not tech:
        raise FeatureInputError("Enter both the maintenance action and technician.")
    entries = _read_register(ctx, "mep-maintenance-log.json", "entries")
    entry = {
        "date": date.today().isoformat(),
        "assetId": item["id"],
        "assetName": item.get("name") or item.get("kind", ""),
        "action": action,
        "technician": tech,
        "story": item.get("story", ""),
    }
    entries.append(entry)
    path = _export(ctx, "mep-maintenance-log.json", {"entries": entries})
    asset_services = sum(1 for e in entries if str(e.get("assetId")) == str(item["id"]))
    return result(
        {
            "assetId": str(item["id"]),
            "assetServiceCount": asset_services,
            "totalLogEntries": len(entries),
            "exportPath": path,
        },
        [
            table(
                "Maintenance log ledger",
                [
                    ("date", "Date"),
                    ("assetId", "Asset"),
                    ("action", "Action"),
                    ("technician", "Technician"),
                ],
                entries[-25:],
            )
        ],
        [f"Recorded service #{asset_services} for {item['id']} ({len(entries)} total entries)."],
    )


@feature(
    "mepSystemsMaintenance.runHours",
    "Run Hours",
    part="mep",
    fields=[
        number("previousHours", "Previous meter reading", 1200, unit="h", min=0),
        number("currentHours", "Current meter reading", 1300, unit="h", min=0),
    ],
    requires_project=False,
)
def run_hours(ctx: FeatureContext, v: dict) -> dict:
    """Determine run hours accumulated between successive operating-meter readings."""
    if v["currentHours"] < v["previousHours"]:
        raise FeatureInputError(
            "Current run-hour reading cannot be less than the previous reading."
        )
    delta = v["currentHours"] - v["previousHours"]
    return result(
        {"currentRunHours": v["currentHours"], "periodRunHours": delta},
        [
            table(
                "Run-hour readings",
                [("reading", "Reading"), ("hours", "Hours", "h")],
                [
                    {"reading": "Previous", "hours": v["previousHours"]},
                    {"reading": "Current", "hours": v["currentHours"]},
                    {"reading": "Accumulated", "hours": delta},
                ],
            )
        ],
        ["Confirm the meter has not rolled over between readings."],
    )


@feature(
    "mepSystemsMaintenance.meterReading",
    "Meter Reading",
    part="mep",
    fields=[
        number("previous", "Previous consumption", 1000, unit="kWh", min=0),
        number("current", "Current consumption", 1125, unit="kWh", min=0),
        number("periodDays", "Reading interval", 30, unit="days", min=0.1),
    ],
    requires_project=False,
)
def meter_reading(ctx: FeatureContext, v: dict) -> dict:
    """Calculate interval utility consumption and average daily consumption from meter readings."""
    if v["current"] < v["previous"]:
        raise FeatureInputError("Current meter reading cannot be less than the previous reading.")
    consumption = v["current"] - v["previous"]
    return result(
        {"consumptionKwh": consumption, "averageDailyKwh": consumption / v["periodDays"]},
        [
            table(
                "Meter interval",
                [("measure", "Measure"), ("value", "Value")],
                [
                    {"measure": "Consumption [kWh]", "value": consumption},
                    {
                        "measure": "Average per day [kWh/day]",
                        "value": consumption / v["periodDays"],
                    },
                ],
            )
        ],
        ["Check meter units, rollover and reading timestamps before comparing periods."],
    )


@feature(
    "mepSystemsMaintenance.complianceCert",
    "Compliance Cert",
    part="mep",
    fields=[
        text("assetId", "Equipment ID", "equipment-1"),
        text("certificate", "Certificate reference", ""),
        text("expiryDate", "Expiry date [YYYY-MM-DD]", ""),
    ],
)
def compliance_cert(ctx: FeatureContext, v: dict) -> dict:
    """Validate certificate expiry date, compute days remaining, and update register."""
    from datetime import date

    item = _asset(ctx, v["assetId"])
    ref = v["certificate"].strip()
    expiry_str = v["expiryDate"].strip()
    if not ref or not expiry_str:
        raise FeatureInputError("Enter the certificate reference and its expiry date.")
    try:
        expiry = date.fromisoformat(expiry_str)
    except ValueError as exc:
        raise FeatureInputError(f"Expiry date {expiry_str!r} must use YYYY-MM-DD format.") from exc
    days_left = (expiry - date.today()).days
    status = "Expired" if days_left < 0 else ("ExpiringSoon" if days_left <= 30 else "Valid")
    certs = _read_register(ctx, "mep-compliance-certificates.json", "certificates")
    by_key = {(str(c.get("assetId")), str(c.get("certificateReference"))): c for c in certs}
    cert = {
        "assetId": item["id"],
        "assetName": item.get("name") or item.get("kind", ""),
        "certificateReference": ref,
        "expiryDate": expiry.isoformat(),
        "daysRemaining": days_left,
        "status": status,
    }
    by_key[(str(item["id"]), ref)] = cert
    rows = list(by_key.values())
    path = _export(ctx, "mep-compliance-certificates.json", {"certificates": rows})
    return result(
        {
            "assetId": str(item["id"]),
            "expiryDate": cert["expiryDate"],
            "daysRemaining": days_left,
            "status": status,
            "exportPath": path,
        },
        [
            table(
                "Compliance certificate register",
                [
                    ("assetId", "Asset"),
                    ("certificateReference", "Cert Ref"),
                    ("expiryDate", "Expiry"),
                    ("daysRemaining", "Days"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
        [f"Validated ISO expiry date ({status}, {days_left} day(s) remaining)."],
    )
