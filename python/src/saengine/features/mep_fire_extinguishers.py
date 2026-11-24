"""Dedicated mepFireExtinguishers MEP feature registrations."""

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
    "mepFireExtinguishers.classHazardDefine",
    "Class Hazard Define",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def classHazardDefine(ctx: FeatureContext, values: dict) -> dict:
    """Class Hazard Define: Hazard Assessment."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Class Hazard Define",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireExtinguishers.co2Extinguisher",
    "CO2 Extinguisher",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def co2Extinguisher(ctx: FeatureContext, values: dict) -> dict:
    """CO2 Extinguisher: Types."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "CO2 Extinguisher",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireExtinguishers.coverageAudit",
    "Coverage Audit",
    part="mep",
    fields=[
        number("area", "Area", 100, unit="m?", min=0),
        text("name", "Output name", "MEP schedule"),
    ],
    requires_project=True,
)
def coverageAudit(ctx: FeatureContext, values: dict) -> dict:
    """Coverage Audit: Compliance Verification."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepFireExtinguishers.coverageAudit",
        "title": "Coverage Audit",
        "name": values["name"],
        "group": "Compliance Verification",
        "mep": raw,
    }
    path = ctx.path("11 Exports/coverageAudit.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Coverage Audit",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepFireExtinguishers.deadEndCheck",
    "Dead End Check",
    part="mep",
    fields=[
        number("deadEndLengthM", "Corridor dead-end length", 5.5, unit="m", min=0.0),
        number("limitLengthM", "Allowable dead-end pocket limit", 6.0, unit="m", min=1.0),
        number(
            "travelToExtinguisherM",
            "Actual travel distance to extinguisher",
            14.0,
            unit="m",
            min=0.5,
        ),
    ],
    requires_project=False,
)
def deadEndCheck(ctx: FeatureContext, values: dict) -> dict:
    """Verify dead-end corridor extinguisher access & exit travel distance bounds."""
    dead_ok = float(values["deadEndLengthM"]) <= float(values["limitLengthM"])
    travel_ok = float(values["travelToExtinguisherM"]) <= 22.5
    ok = dead_ok and travel_ok
    return result(
        summary={
            "deadEndLengthM": values["deadEndLengthM"],
            "deadEndOk": dead_ok,
            "travelOk": travel_ok,
            "compliant": ok,
        },
        tables=[
            table(
                "Dead-end & extinguisher travel check",
                [
                    ("criterion", "Check"),
                    ("measured", "Measured"),
                    ("limit", "Limit"),
                    ("status", "Status"),
                ],
                [
                    {
                        "criterion": "Dead-end pocket length",
                        "measured": f"{values['deadEndLengthM']:g} m",
                        "limit": f"<= {values['limitLengthM']:g} m",
                        "status": "PASS" if dead_ok else "FAIL",
                    },
                    {
                        "criterion": "Extinguisher travel",
                        "measured": f"{values['travelToExtinguisherM']:g} m",
                        "limit": "<= 22.5 m",
                        "status": "PASS" if travel_ok else "ADD UNIT",
                    },
                ],
            )
        ],
        notes=[
            "Place portable extinguishers along normal path of exit travel so occupants never walk deeper into dead-ends."
        ],
    )


@feature(
    "mepFireExtinguishers.expiryCheck",
    "Expiry Check",
    part="mep",
    fields=[
        text("manufactureYear", "Cylinder test/service year (YYYY)", "2023"),
        number(
            "hydroIntervalYr",
            "Hydrostatic / refill test interval",
            5.0,
            unit="yr",
            min=1.0,
            max=12.0,
        ),
        number(
            "annualCheckMonths",
            "Annual inspection interval",
            12.0,
            unit="months",
            min=3.0,
            max=24.0,
        ),
    ],
    requires_project=False,
)
def expiryCheck(ctx: FeatureContext, values: dict) -> dict:
    """Compute next annual service and hydrostatic pressure test due year for fire extinguishers."""
    from datetime import date

    yr_str = values["manufactureYear"].strip()
    try:
        base_yr = int(yr_str)
    except ValueError as exc:
        raise FeatureInputError(f"Enter a valid 4-digit year instead of {yr_str!r}.") from exc
    curr_yr = date.today().year
    next_hydro = base_yr + int(values["hydroIntervalYr"])
    years_left = next_hydro - curr_yr
    status = "Due / Overdue" if years_left <= 0 else ("Due Soon" if years_left == 1 else "Valid")
    return result(
        summary={
            "baseYear": base_yr,
            "nextHydroTestYear": next_hydro,
            "yearsRemaining": years_left,
            "status": status,
        },
        tables=[
            table(
                "Extinguisher inspection & hydro schedule",
                [("item", "Milestone"), ("value", "Value")],
                [
                    {"item": "Baseline test year", "value": base_yr},
                    {"item": "Next hydrostatic test year", "value": next_hydro},
                    {"item": "Remaining service years", "value": years_left},
                    {
                        "item": "Routine tag check interval",
                        "value": f"{int(values['annualCheckMonths'])} months",
                    },
                    {"item": "Status", "value": status},
                ],
            )
        ],
        notes=[
            "Tag monthly visual gauge/pin checks and log 5-year / 12-year hydrostatic pressure retests."
        ],
    )


@feature(
    "mepFireExtinguishers.exportSchedule",
    "Export Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def exportSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Export Schedule: Schedule."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepFireExtinguishers.exportSchedule",
        "title": "Export Schedule",
        "name": values["name"],
        "group": "Schedule",
        "mep": raw,
    }
    path = ctx.path("11 Exports/exportSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Export Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepFireExtinguishers.extinguisherRadius",
    "Extinguisher Radius",
    part="mep",
    fields=[number("dimension", "Dimension", 1000, unit="mm", min=1)],
    requires_project=True,
)
def extinguisherRadius(ctx: FeatureContext, values: dict) -> dict:
    """Extinguisher Radius: Coverage Mapping."""
    design_value = float(values["dimension"])
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
                "Extinguisher Radius",
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
    "mepFireExtinguishers.extinguisherSchedule",
    "Extinguisher Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def extinguisherSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Extinguisher Schedule: Schedule."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepFireExtinguishers.extinguisherSchedule",
        "title": "Extinguisher Schedule",
        "name": values["name"],
        "group": "Schedule",
        "mep": raw,
    }
    path = ctx.path("11 Exports/extinguisherSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Extinguisher Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepFireExtinguishers.extinguisherSignoff",
    "Extinguisher Signoff",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def extinguisherSignoff(ctx: FeatureContext, values: dict) -> dict:
    """Extinguisher Signoff: Compliance Verification."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepFireExtinguishers.extinguisherSignoff",
        "title": "Extinguisher Signoff",
        "name": values["name"],
        "group": "Compliance Verification",
        "mep": raw,
    }
    path = ctx.path("11 Exports/extinguisherSignoff.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Extinguisher Signoff",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepFireExtinguishers.flammableStorageCheck",
    "Flammable Storage Check",
    part="mep",
    fields=[
        number("storageAreaM2", "Flammable liquid room / bund area", 180.0, unit="m²", min=5.0),
        number("maxTravelLimitM", "Maximum Class B travel distance", 15.0, unit="m", min=5.0),
        number("unitBRating", "Individual extinguisher B-rating", 40.0, min=10.0),
    ],
    requires_project=False,
)
def flammableStorageCheck(ctx: FeatureContext, values: dict) -> dict:
    """Calculate Class B portable extinguisher count and coverage radius for flammable storage."""
    import math

    area = float(values["storageAreaM2"])
    r_max = float(values["maxTravelLimitM"])
    # Practical circle-in-square coverage area ~(1.414 * r_eff)^2; high-hazard Class B 40-B / 80-B spacing
    unit_cov_m2 = min(area, 0.75 * math.pi * (r_max**2))
    by_travel = max(1, math.ceil(area / max(40.0, unit_cov_m2)))
    req_rating = 40.0 if r_max <= 9.1 else 80.0
    rating_ok = float(values["unitBRating"]) >= req_rating
    return result(
        summary={
            "recommendedUnits": by_travel,
            "minimumUnitRatingB": req_rating,
            "ratingOk": rating_ok,
        },
        tables=[
            table(
                "Class B flammable storage protection",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Protected floor area", "value": area, "unit": "m²"},
                    {
                        "item": "Minimum Class B rating required",
                        "value": f"{int(req_rating)}-B",
                        "unit": "-",
                    },
                    {
                        "item": "Provided unit rating",
                        "value": f"{int(values['unitBRating'])}-B",
                        "unit": "-",
                    },
                    {"item": "Minimum extinguisher units", "value": by_travel, "unit": "units"},
                ],
            )
        ],
        notes=[
            "Locate extinguishers just outside flammable-store entry doors within maximum Class B travel distance."
        ],
    )


@feature(
    "mepFireExtinguishers.foamExtinguisher",
    "Foam Extinguisher",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def foamExtinguisher(ctx: FeatureContext, values: dict) -> dict:
    """Foam Extinguisher: Types."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Foam Extinguisher",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireExtinguishers.inspectionRecord",
    "Inspection Record",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def inspectionRecord(ctx: FeatureContext, values: dict) -> dict:
    """Inspection Record: Schedule."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Inspection Record",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireExtinguishers.locationSign",
    "Location Sign",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def locationSign(ctx: FeatureContext, values: dict) -> dict:
    """Location Sign: Placement."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Location Sign",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireExtinguishers.mountingHeight",
    "Mounting Height",
    part="mep",
    fields=[number("dimension", "Dimension", 1000, unit="mm", min=1)],
    requires_project=True,
)
def mountingHeight(ctx: FeatureContext, values: dict) -> dict:
    """Mounting Height: Placement."""
    design_value = float(values["dimension"])
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
                "Mounting Height",
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
    "mepFireExtinguishers.occupyRiskLevel",
    "Occupy Risk Level",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def occupyRiskLevel(ctx: FeatureContext, values: dict) -> dict:
    """Occupy Risk Level: Hazard Assessment."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Occupy Risk Level",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireExtinguishers.placeUnit",
    "Place Unit",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def placeUnit(ctx: FeatureContext, values: dict) -> dict:
    """Place Unit: Placement."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Place Unit",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireExtinguishers.powderExtinguisher",
    "Powder Extinguisher",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def powderExtinguisher(ctx: FeatureContext, values: dict) -> dict:
    """Powder Extinguisher: Types."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Powder Extinguisher",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireExtinguishers.specialHazardUnit",
    "Special Hazard Unit",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def specialHazardUnit(ctx: FeatureContext, values: dict) -> dict:
    """Special Hazard Unit: Hazard Assessment."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Special Hazard Unit",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireExtinguishers.travelDistance",
    "Travel Distance",
    part="mep",
    fields=[number("dimension", "Dimension", 1000, unit="mm", min=1)],
    requires_project=True,
)
def travelDistance(ctx: FeatureContext, values: dict) -> dict:
    """Travel Distance: Placement."""
    design_value = float(values["dimension"])
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
                "Travel Distance",
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
    "mepFireExtinguishers.travelPathObstacle",
    "Travel Path Obstacle",
    part="mep",
    fields=[number("dimension", "Dimension", 1000, unit="mm", min=1)],
    requires_project=True,
)
def travelPathObstacle(ctx: FeatureContext, values: dict) -> dict:
    """Travel Path Obstacle: Coverage Mapping."""
    design_value = float(values["dimension"])
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
                "Travel Path Obstacle",
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
    "mepFireExtinguishers.waterExtinguisher",
    "Water Extinguisher",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def waterExtinguisher(ctx: FeatureContext, values: dict) -> dict:
    """Water Extinguisher: Types."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Water Extinguisher",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepFireExtinguishers.weightVerification",
    "Weight Verification",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def weightVerification(ctx: FeatureContext, values: dict) -> dict:
    """Weight Verification: Compliance Verification."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Weight Verification",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )
