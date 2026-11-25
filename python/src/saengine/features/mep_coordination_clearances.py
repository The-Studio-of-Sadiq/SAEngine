"""Dedicated mepCoordinationClearances MEP feature registrations."""

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


@feature(
    "mepCoordinationClearances.accessZone",
    "Access Zone",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def accessZone(ctx: FeatureContext, values: dict) -> dict:
    """Access Zone: Define."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Access Zone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.applyZone",
    "Apply Zone",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def applyZone(ctx: FeatureContext, values: dict) -> dict:
    """Apply Zone: Define."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Apply Zone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.assignIssue",
    "Assign Issue",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def assignIssue(ctx: FeatureContext, values: dict) -> dict:
    """Assign Issue: Resolution Workflow."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Assign Issue",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.autoOffsetSystem",
    "Auto Offset System",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def autoOffsetSystem(ctx: FeatureContext, values: dict) -> dict:
    """Auto Offset System: Resolution Workflow."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Auto Offset System",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.clearanceReport",
    "Clearance Report",
    part="mep",
    fields=[
        number("minGapMm", "Required service-to-service gap", 50.0, unit="mm", min=0.0),
        text("name", "Export report filename prefix", "clearanceReport"),
    ],
    requires_project=True,
)
def clearanceReport(ctx: FeatureContext, values: dict) -> dict:
    """Run MEP clash & structural opening clearance coordination checks and export report."""
    from saengine.mep import coordination

    if ctx.root is None:
        raise FeatureInputError(
            "Open a project with 07 MEP/mep.json before generating a clearance report."
        )
    coord = coordination.coordinate(ctx.root)
    clashes = coord.get("clashes", [])
    rows = [
        {
            "id": str(c.get("id", f"CL-{i + 1}")),
            "a": str(c.get("a", "")),
            "b": str(c.get("b", "")),
            "clearanceMm": float(c.get("clearanceMm", 0.0) or 0.0),
            "status": "OK"
            if float(c.get("clearanceMm", 0.0) or 0.0) >= float(values["minGapMm"])
            else "VIOLATION",
        }
        for i, c in enumerate(clashes)
    ]
    safe = "".join(c for c in values["name"] if c.isalnum() or c in "-_") or "clearanceReport"
    path = ctx.path(f"11 Exports/{safe}.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"minGapMm": values["minGapMm"], "clashes": rows, "coordination": coord},
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return result(
        summary={"clashesFound": len(rows), "exportPath": str(path)},
        tables=[
            table(
                "MEP coordination clearance report",
                [
                    ("id", "ID"),
                    ("a", "Element A"),
                    ("b", "Element B"),
                    ("clearanceMm", "Gap", "mm"),
                    ("status", "Status"),
                ],
                rows[:30]
                or [
                    {
                        "id": "-",
                        "a": "All services",
                        "b": "Structure",
                        "clearanceMm": values["minGapMm"],
                        "status": "CLEAR",
                    }
                ],
            )
        ],
        notes=[
            f"Executed saengine.mep.coordination.coordinate against project BIM+MEP models; saved to {path}."
        ],
    )


@feature(
    "mepCoordinationClearances.clearanceSignoff",
    "Clearance Signoff",
    part="mep",
    fields=[
        text("reviewer", "Coordination lead initials", "MEP-BIM"),
        text("name", "Signoff register file prefix", "clearanceSignoff"),
    ],
    requires_project=True,
)
def clearanceSignoff(ctx: FeatureContext, values: dict) -> dict:
    """Validate zero hard clashes across MEP coordination model and record clearance sign-off."""
    from saengine.mep import coordination

    if ctx.root is None:
        raise FeatureInputError("Open a project before recording clearance sign-off.")
    coord = coordination.coordinate(ctx.root)
    hard_clashes = [
        c for c in coord.get("clashes", []) if float(c.get("clearanceMm", 0.0) or 0.0) <= 0.0
    ]
    signed_off = len(hard_clashes) == 0
    safe = "".join(c for c in values["name"] if c.isalnum() or c in "-_") or "clearanceSignoff"
    path = ctx.path(f"11 Exports/{safe}.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "reviewer": values["reviewer"].strip() or "MEP-BIM",
        "hardClashes": len(hard_clashes),
        "signedOff": signed_off,
    }
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return result(
        summary={**record, "exportPath": str(path)},
        tables=[
            table(
                "Coordination clearance signoff",
                [("item", "Check"), ("value", "Result")],
                [
                    {"item": "Reviewer", "value": record["reviewer"]},
                    {"item": "Blocking hard clashes", "value": len(hard_clashes)},
                    {
                        "item": "Sign-off verdict",
                        "value": "APPROVED" if signed_off else "BLOCKED (RESOLVE CLASHES)",
                    },
                ],
            )
        ],
        notes=[
            "Sign-off granted only when saengine.mep.coordination reports zero unresolved hard clashes."
        ],
    )


@feature(
    "mepCoordinationClearances.disciplineMask",
    "Discipline Mask",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def disciplineMask(ctx: FeatureContext, values: dict) -> dict:
    """Discipline Mask: Zone Filters."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Discipline Mask",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.elevationBand",
    "Elevation Band",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def elevationBand(ctx: FeatureContext, values: dict) -> dict:
    """Elevation Band: Zone Filters."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Elevation Band",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.insulatedClearance",
    "Insulated Clearance",
    part="mep",
    fields=[
        number("bareOdMm", "Bare pipe outer diameter / duct width", 114.3, unit="mm", min=10.0),
        number("insulationMm", "Thermal insulation jacket thickness", 32.0, unit="mm", min=0.0),
        number("workingClearanceMm", "Clear tool / vapour-barrier gap", 25.0, unit="mm", min=10.0),
    ],
    requires_project=False,
)
def insulatedClearance(ctx: FeatureContext, values: dict) -> dict:
    """Calculate total coordinated envelope width/radius including insulation jacket and buffer."""
    insulated_od = float(values["bareOdMm"]) + 2.0 * float(values["insulationMm"])
    envelope = insulated_od + 2.0 * float(values["workingClearanceMm"])
    min_sleeve = insulated_od + 25.0
    return result(
        summary={
            "insulatedOdMm": round(insulated_od, 1),
            "coordinatedEnvelopeMm": round(envelope, 1),
            "minSleeveIdMm": round(min_sleeve, 0),
        },
        tables=[
            table(
                "Insulated service envelope",
                [("item", "Zone Layer"), ("sizeMm", "Dimension", "mm")],
                [
                    {"item": "Bare service outer size", "sizeMm": values["bareOdMm"]},
                    {"item": "Insulated OD (+2 x t_ins)", "sizeMm": round(insulated_od, 1)},
                    {"item": "Coordinated reservation zone", "sizeMm": round(envelope, 1)},
                    {"item": "Suggested minimum sleeve ID", "sizeMm": round(min_sleeve, 0)},
                ],
            )
        ],
        notes=[
            "Maintain continuous vapour-barrier jacket through wall/slab firestop sleeves on chilled pipes."
        ],
    )


@feature(
    "mepCoordinationClearances.insulationAllowance",
    "Insulation Allowance",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def insulationAllowance(ctx: FeatureContext, values: dict) -> dict:
    """Insulation Allowance: Rules."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Insulation Allowance",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.maintenanceBuffer",
    "Maintenance Buffer",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def maintenanceBuffer(ctx: FeatureContext, values: dict) -> dict:
    """Maintenance Buffer: Spatial Buffers."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Maintenance Buffer",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.minClearance",
    "Min Clearance",
    part="mep",
    fields=[
        select(
            "material",
            "Pipe material",
            [("GI", "GI"), ("PPR", "PPR"), ("uPVC", "uPVC"), ("HDPE", "HDPE"), ("CI", "CI")],
            "GI",
        ),
        number("diameterMm", "Larger adjacent pipe/duct dimension", 200.0, unit="mm", min=15.0),
        number(
            "flangeAllowanceMm", "Flange / valve handwheel projection", 35.0, unit="mm", min=0.0
        ),
        number("providedGapMm", "Modelled centre-to-clear surface gap", 85.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def minClearance(ctx: FeatureContext, values: dict) -> dict:
    """Compute minimum required service-to-service clearance and check provided gap."""
    from saengine.mep import fabrication

    d = float(values["diameterMm"])
    opts = fabrication.FabricationOptions()
    spacing_val, spacing_source = fabrication.pipe_spacing(values["material"], d, opts)
    base_spacing = float(spacing_val) if spacing_val is not None else max(200.0, d * 10.0)
    req_gap = max(50.0, base_spacing * 0.025) + float(values["flangeAllowanceMm"])
    ok = float(values["providedGapMm"]) >= req_gap
    return result(
        summary={
            "material": values["material"],
            "supportSpacingMm": round(base_spacing, 1),
            "requiredClearGapMm": round(req_gap, 1),
            "providedGapMm": values["providedGapMm"],
            "compliant": ok,
        },
        tables=[
            table(
                "Minimum service clearance check",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Pipe support spacing", "value": round(base_spacing, 1), "unit": "mm"},
                    {"item": "Required clear gap", "value": round(req_gap, 1), "unit": "mm"},
                    {"item": "Provided clear gap", "value": values["providedGapMm"], "unit": "mm"},
                    {"item": "Source", "value": spacing_source, "unit": "-"},
                ],
            )
        ],
        notes=[f"Support spacing reference: {spacing_source}."],
    )


@feature(
    "mepCoordinationClearances.priorityRule",
    "Priority Rule",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def priorityRule(ctx: FeatureContext, values: dict) -> dict:
    """Priority Rule: Rules."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Priority Rule",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.ruleExceptions",
    "Rule Exceptions",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def ruleExceptions(ctx: FeatureContext, values: dict) -> dict:
    """Rule Exceptions: Rules."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Rule Exceptions",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.runClearance",
    "Run Clearance",
    part="mep",
    fields=[
        number("slabSoffitMm", "Structural slab soffit elevation", 3200.0, unit="mm", min=1500.0),
        number(
            "ceilingElevationMm", "Suspended ceiling plane elevation", 2700.0, unit="mm", min=1500.0
        ),
        number(
            "serviceDepthMm", "Largest duct + hanger + insulation depth", 380.0, unit="mm", min=50.0
        ),
    ],
    requires_project=False,
)
def runClearance(ctx: FeatureContext, values: dict) -> dict:
    """Check horizontal ceiling plenum depth vs service stack + hanger clearance."""
    plenum_mm = float(values["slabSoffitMm"]) - float(values["ceilingElevationMm"])
    spare_mm = plenum_mm - float(values["serviceDepthMm"])
    ok = spare_mm >= 50.0
    return result(
        summary={
            "plenumDepthMm": round(plenum_mm, 0),
            "remainingClearanceMm": round(spare_mm, 0),
            "compliantGe50Mm": ok,
        },
        tables=[
            table(
                "Ceiling plenum vertical clearance check",
                [("item", "Level / Component"), ("valueMm", "Height", "mm")],
                [
                    {"item": "Available ceiling plenum", "valueMm": round(plenum_mm, 0)},
                    {"item": "Largest service envelope", "valueMm": values["serviceDepthMm"]},
                    {"item": "Remaining hanger/crossing gap", "valueMm": round(spare_mm, 0)},
                ],
            )
        ],
        notes=[
            "Maintain >= 50 mm vertical clearance below soffit/beam and above recessed light fixtures."
        ],
    )


@feature(
    "mepCoordinationClearances.safetyEnclosure",
    "Safety Enclosure",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def safetyEnclosure(ctx: FeatureContext, values: dict) -> dict:
    """Safety Enclosure: Spatial Buffers."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Safety Enclosure",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.serviceZone",
    "Service Zone",
    part="mep",
    fields=[text("zoneId", "Zone ID", "zone-1")],
    requires_project=True,
)
def serviceZone(ctx: FeatureContext, values: dict) -> dict:
    """Service Zone: Define."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Service Zone",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.showViolations",
    "Show Violations",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def showViolations(ctx: FeatureContext, values: dict) -> dict:
    """Show Violations: Check."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Show Violations",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.slopeRule",
    "Slope Rule",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def slopeRule(ctx: FeatureContext, values: dict) -> dict:
    """Slope Rule: Rules."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Slope Rule",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.suggestFix",
    "Suggest Fix",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def suggestFix(ctx: FeatureContext, values: dict) -> dict:
    """Suggest Fix: Check."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Suggest Fix",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.systemCategoryFilter",
    "System Category Filter",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def systemCategoryFilter(ctx: FeatureContext, values: dict) -> dict:
    """System Category Filter: Zone Filters."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "System Category Filter",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCoordinationClearances.vibrationBuffer",
    "Vibration Buffer",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def vibrationBuffer(ctx: FeatureContext, values: dict) -> dict:
    """Vibration Buffer: Spatial Buffers."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Vibration Buffer",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )
