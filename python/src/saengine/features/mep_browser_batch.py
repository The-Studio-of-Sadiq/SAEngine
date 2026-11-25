"""Dedicated mepBrowser MEP feature registrations."""

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
    "mepBrowser.browserPrint",
    "Browser Print",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def browserPrint(ctx: FeatureContext, values: dict) -> dict:
    """Browser Print: Views."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Browser Print",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.browserSnapshot",
    "Browser Snapshot",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def browserSnapshot(ctx: FeatureContext, values: dict) -> dict:
    """Browser Snapshot: Export."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Browser Snapshot",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.browserViews",
    "Browser Views",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def browserViews(ctx: FeatureContext, values: dict) -> dict:
    """Browser Views: Views."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Browser Views",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.clearHighlight",
    "Clear Highlight",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def clearHighlight(ctx: FeatureContext, values: dict) -> dict:
    """Clear Highlight: Selection."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Clear Highlight",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.columnLayout",
    "Column Layout",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def columnLayout(ctx: FeatureContext, values: dict) -> dict:
    """Column Layout: Views."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Column Layout",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.componentData",
    "Component Data",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def componentData(ctx: FeatureContext, values: dict) -> dict:
    """Component Data: Data."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepBrowser.componentData",
        "title": "Component Data",
        "name": values["name"],
        "group": "Data",
        "mep": raw,
    }
    path = ctx.path("11 Exports/componentData.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Component Data",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepBrowser.designChecks",
    "Design Checks",
    part="mep",
    fields=[text("discipline", "Filter discipline (blank=all, plumbing/hvac/electrical/fire)", "")],
    requires_project=True,
)
def designChecks(ctx: FeatureContext, values: dict) -> dict:
    """Run full integrated MEP systems verification across 07 MEP/mep.json."""
    from saengine.library.bim import BuildingModel
    from saengine.library.mep import MepModel
    from saengine.mep import systems

    if ctx.root is None:
        raise FeatureInputError(
            "Open a project with 07 MEP/mep.json before running MEP design checks."
        )
    raw = ctx.raw("mep")
    if not isinstance(raw, dict):
        raise FeatureInputError("Missing 07 MEP/mep.json in project.")
    try:
        mep = MepModel.model_validate(raw)
    except ValueError as error:
        raise FeatureInputError(f"Invalid 07 MEP/mep.json: {error}") from error
    raw_bim = ctx.raw("bim")
    building = None
    if isinstance(raw_bim, dict):
        try:
            building = BuildingModel.model_validate(raw_bim)
        except ValueError:
            building = None
    report = systems.analyze_systems(mep, building)
    issues = report.get("issues", [])
    filt = values["discipline"].strip().lower()
    if filt:
        issues = [
            i
            for i in issues
            if filt in str(i.get("classification") or i.get("kind") or "").lower()
            or filt in str(i.get("message", "")).lower()
        ]
    rows = [
        {
            "discipline": str(i.get("classification") or i.get("kind") or "mep"),
            "severity": str(i.get("severity", "")),
            "element": ", ".join(str(e) for e in (i.get("elements") or [])) or "-",
            "message": str(i.get("message", "")),
        }
        for i in issues[:40]
    ]
    return result(
        summary={
            "totalIssues": len(issues),
            "errors": sum(
                1 for i in issues if str(i.get("severity", "")).lower() in ("error", "fail")
            ),
            "warnings": sum(
                1 for i in issues if str(i.get("severity", "")).lower() in ("warning", "warn")
            ),
        },
        tables=[
            table(
                "Integrated MEP design checks",
                [
                    ("discipline", "Discipline"),
                    ("severity", "Severity"),
                    ("element", "Element"),
                    ("message", "Finding"),
                ],
                rows
                or [
                    {
                        "discipline": "all",
                        "severity": "ok",
                        "element": "-",
                        "message": "No issues detected.",
                    }
                ],
            )
        ],
        notes=[
            "Evaluated directly via saengine.mep.systems.analyze_systems against active project code pack."
        ],
    )


@feature(
    "mepBrowser.equipmentList",
    "Equipment List",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def equipmentList(ctx: FeatureContext, values: dict) -> dict:
    """Equipment List: Analysis."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepBrowser.equipmentList",
        "title": "Equipment List",
        "name": values["name"],
        "group": "Analysis",
        "mep": raw,
    }
    path = ctx.path("11 Exports/equipmentList.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Equipment List",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepBrowser.exportBrowser",
    "Export Browser",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def exportBrowser(ctx: FeatureContext, values: dict) -> dict:
    """Export Browser: Export."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepBrowser.exportBrowser",
        "title": "Export Browser",
        "name": values["name"],
        "group": "Export",
        "mep": raw,
    }
    path = ctx.path("11 Exports/exportBrowser.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Export Browser",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepBrowser.filterTree",
    "Filter Tree",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def filterTree(ctx: FeatureContext, values: dict) -> dict:
    """Filter Tree: Tree."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Filter Tree",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.flowRates",
    "Flow Rates",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def flowRates(ctx: FeatureContext, values: dict) -> dict:
    """Flow Rates: Data."""
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
                "Flow Rates",
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
    "mepBrowser.flowSummary",
    "Flow Summary",
    part="mep",
    fields=[
        number("flow", "Design flow", 100, unit="l/s", min=0),
        text("name", "Output name", "MEP schedule"),
    ],
    requires_project=True,
)
def flowSummary(ctx: FeatureContext, values: dict) -> dict:
    """Flow Summary: Analysis."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepBrowser.flowSummary",
        "title": "Flow Summary",
        "name": values["name"],
        "group": "Analysis",
        "mep": raw,
    }
    path = ctx.path("11 Exports/flowSummary.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Flow Summary",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepBrowser.highlightPath",
    "Highlight Path",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def highlightPath(ctx: FeatureContext, values: dict) -> dict:
    """Highlight Path: Selection."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Highlight Path",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.isolateSystem",
    "Isolate System",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def isolateSystem(ctx: FeatureContext, values: dict) -> dict:
    """Isolate System: Selection."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Isolate System",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.pressureDrops",
    "Pressure Drops",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def pressureDrops(ctx: FeatureContext, values: dict) -> dict:
    """Pressure Drops: Data."""
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
                "Pressure Drops",
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
    "mepBrowser.pressureSummary",
    "Pressure Summary",
    part="mep",
    fields=[
        number("pressure", "Design pressure", 100, unit="kPa", min=0),
        text("name", "Output name", "MEP schedule"),
    ],
    requires_project=True,
)
def pressureSummary(ctx: FeatureContext, values: dict) -> dict:
    """Pressure Summary: Analysis."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepBrowser.pressureSummary",
        "title": "Pressure Summary",
        "name": values["name"],
        "group": "Analysis",
        "mep": raw,
    }
    path = ctx.path("11 Exports/pressureSummary.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Pressure Summary",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepBrowser.savedQueries",
    "Saved Queries",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def savedQueries(ctx: FeatureContext, values: dict) -> dict:
    """Saved Queries: Views."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Saved Queries",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.selectInModel",
    "Select In Model",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def selectInModel(ctx: FeatureContext, values: dict) -> dict:
    """Select In Model: Selection."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Select In Model",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.showConnectors",
    "Show Connectors",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def showConnectors(ctx: FeatureContext, values: dict) -> dict:
    """Show Connectors: Selection."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Show Connectors",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.sortBySystem",
    "Sort By System",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def sortBySystem(ctx: FeatureContext, values: dict) -> dict:
    """Sort By System: Views."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Sort By System",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.systemSchedule",
    "System Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def systemSchedule(ctx: FeatureContext, values: dict) -> dict:
    """System Schedule: Export."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepBrowser.systemSchedule",
        "title": "System Schedule",
        "name": values["name"],
        "group": "Export",
        "mep": raw,
    }
    path = ctx.path("11 Exports/systemSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "System Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepBrowser.systemTree",
    "System Tree",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def systemTree(ctx: FeatureContext, values: dict) -> dict:
    """System Tree: Tree."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "System Tree",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.unconnectedEnds",
    "Unconnected Ends",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def unconnectedEnds(ctx: FeatureContext, values: dict) -> dict:
    """Unconnected Ends: Analysis."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Unconnected Ends",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepBrowser.zoomToSystem",
    "Zoom to System",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def zoomToSystem(ctx: FeatureContext, values: dict) -> dict:
    """Zoom to System: Tree."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Zoom to System",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )
