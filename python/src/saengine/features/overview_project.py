"""Overview project-home commands backed by the project's real part files."""

from __future__ import annotations

import json
from typing import Any

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.overview_common import (
    boq_items,
    json_text,
    list_bim,
    list_objects,
    project_name,
    require_project,
    settings_dict,
    write_export,
)


def _settings_row(ctx: FeatureContext) -> dict[str, Any]:
    raw = settings_dict(ctx)
    project = raw.get("project", {}) if isinstance(raw.get("project"), dict) else {}
    site = raw.get("site", {}) if isinstance(raw.get("site"), dict) else {}
    return {
        "name": project.get("name", project_name(ctx)),
        "engineer": project.get("engineer", ""),
        "location": site.get("location", ""),
        "areaLoads": len(raw.get("areaLoads", [])) if isinstance(raw.get("areaLoads"), list) else 0,
        "combinations": len(raw.get("combinations", []))
        if isinstance(raw.get("combinations"), list)
        else 0,
    }


@feature(
    "project.projectHealth", "Project Health", part="settings", fields=[], requires_project=True
)
def project_health(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise missing project parts, malformed JSON, and current model counts."""
    root = require_project(ctx, "checking project health")
    part_specs = {
        "Soil": "01 Soil Report/soil-report.json",
        "Settings": "02 Project Settings/project-settings.json",
        "Materials": "03 Materials/materials.json",
        "Objects": "04 Objects/objects.json",
        "Floor plan": "05 Floor Plan/floor-plan.json",
        "BIM": "06 BIM/bim.json",
        "MEP": "07 MEP/mep.json",
        "Substructure": "09 Substructure/substructure.json",
        "BOQ": "10 BOQ/boq.json",
    }
    rows = []
    issues = 0
    for name, relative in part_specs.items():
        path = root / relative
        status = "MISSING"
        detail = "File is not present"
        if path.is_file():
            try:
                json.loads(path.read_text("utf-8"))
                status = "OK"
                detail = f"{path.stat().st_size} bytes"
            except (OSError, json.JSONDecodeError) as error:
                status = "INVALID"
                detail = str(error)
        if status != "OK":
            issues += 1
        rows.append({"part": name, "status": status, "detail": detail})
    return result(
        summary={"partCount": len(rows), "issues": issues, "healthy": issues == 0},
        tables=[
            table(
                "Project part health",
                [("part", "Part"), ("status", "Status"), ("detail", "Detail")],
                rows,
            )
        ],
        notes=["Health is determined from the nine versioned project part files."],
    )


@feature(
    "project.recentProjects", "Recent Projects", part="settings", fields=[], requires_project=False
)
def recent_projects(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List the current project and nearby sibling project folders if a project is open."""
    if ctx.root is None:
        raise FeatureInputError("Open a project or archive folder to inspect recent projects.")
    root = ctx.root
    projects = [
        p for p in root.parent.iterdir() if p.is_dir() and (p / "02 Project Settings").is_dir()
    ]
    rows = [
        {"name": p.name, "path": str(p), "selected": p.resolve() == root.resolve()}
        for p in sorted(projects, key=lambda p: p.stat().st_mtime, reverse=True)
    ]
    return result(
        summary={"recentProjects": len(rows)},
        tables=[
            table(
                "Recent project folders",
                [("name", "Name"), ("path", "Location"), ("selected", "Selected")],
                rows,
            )
        ],
        notes=[
            "Recent entries are inferred from sibling SAEngine project folders; no network history is accessed."
        ],
    )


@feature(
    "project.projectTemplates",
    "Project Templates",
    part="settings",
    fields=[text("templateName", "Template name", "Building Project")],
    requires_project=True,
)
def project_templates(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a JSON template manifest from the open project's settings."""
    require_project(ctx, "saving a project template")
    raw = settings_dict(ctx)
    template = {
        "template": values["templateName"],
        "project": raw.get("project", {}),
        "site": raw.get("site", {}),
    }
    path = write_export(
        ctx,
        "11 Exports/templates",
        f"{values['templateName'].replace(' ', '-').lower()}.json",
        json_text(template),
    )
    return result(
        summary={"templateName": values["templateName"], "exportPath": str(path)},
        tables=[
            table(
                "Template manifest",
                [("field", "Field"), ("value", "Value")],
                [{"field": k, "value": str(v)} for k, v in template.items()],
            )
        ],
        notes=[f"Template written to {path}."],
    )


@feature(
    "project.projectSettings",
    "Project Settings",
    part="settings",
    fields=[text("name", "Project name", ""), text("engineer", "Engineer", "")],
    requires_project=True,
)
def project_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Read project identity settings and optionally update name and engineer."""
    root = require_project(ctx, "editing project settings")
    path = root / "02 Project Settings/project-settings.json"
    raw = settings_dict(ctx)
    if not raw:
        raise FeatureInputError("Open a project with a valid project-settings.json file.")
    project = raw.get("project")
    if not isinstance(project, dict):
        project = {}
        raw["project"] = project
    if values["name"].strip():
        project["name"] = values["name"].strip()
    if values["engineer"].strip():
        project["engineer"] = values["engineer"].strip()
    path.write_text(json_text(raw), encoding="utf-8")
    row = _settings_row(ctx)
    ctx._cache.pop("settings", None)
    return result(
        summary={"projectName": row["name"], "engineer": row["engineer"]},
        tables=[
            table(
                "Project settings",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Project name", "value": row["name"]},
                    {"field": "Engineer", "value": row["engineer"]},
                ],
            )
        ],
        notes=[f"Settings updated in {path}."],
    )


@feature(
    "project.fileInformation", "File Information", part="settings", fields=[], requires_project=True
)
def file_information(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report the open project folder and primary file sizes."""
    root = require_project(ctx, "checking file information")
    files = [
        root / "Sample Frame.saengine",
        *[p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts],
    ]
    unique = list(dict.fromkeys(p.resolve() for p in files if p.is_file()))
    rows = [
        {"file": str(p.relative_to(root)), "sizeKb": round(p.stat().st_size / 1024, 2)}
        for p in unique[:100]
    ]
    total = sum(r["sizeKb"] for r in rows)
    return result(
        summary={
            "fileCount": len(unique),
            "totalSizeKb": round(total, 2),
            "projectFolder": str(root),
        },
        tables=[table("File information", [("file", "File"), ("sizeKb", "Size", "KB")], rows)],
        notes=["Hidden version-history and temporary caches are excluded where detectable."],
    )


@feature(
    "project.projectSnapshot",
    "Project Snapshot",
    part="settings",
    fields=[text("filename", "Snapshot filename", "project-snapshot")],
    requires_project=True,
)
def project_snapshot(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a text/JSON dashboard snapshot to the exports folder."""
    require_project(ctx, "creating a project snapshot")
    objects = list_objects(ctx)
    bim, stories = list_bim(ctx)
    boq = boq_items(ctx)
    snapshot = {
        "project": project_name(ctx),
        "objects": len(objects),
        "bimElements": len(bim),
        "stories": len(stories),
        "boqItems": len(boq),
    }
    name = values["filename"].strip().replace(" ", "-") or "project-snapshot"
    path = write_export(ctx, "11 Exports", f"{name}.json", json_text(snapshot))
    return result(
        summary={**{k: v for k, v in snapshot.items()}, "exportPath": str(path)},
        notes=[f"Snapshot written to {path}."],
    )


@feature("project.keyMetrics", "Key Metrics", part="settings", fields=[], requires_project=True)
def key_metrics(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate project key counts and BOQ totals from real project files."""
    require_project(ctx, "calculating key metrics")
    bim, stories = list_bim(ctx)
    objects = list_objects(ctx)
    items = boq_items(ctx)
    amount = sum(
        float(item.get("quantity", 0) or 0) * float(item.get("rate", 0) or 0) for item in items
    )
    return result(
        summary={
            "stories": len(stories),
            "objects": len(objects),
            "bimElements": len(bim),
            "boqItems": len(items),
            "boqAmount": amount,
        },
        notes=["BOQ amount uses item quantities and rates already present in the project."],
    )


@feature("project.modelSize", "Model Size", part="bim", fields=[], requires_project=True)
def model_size(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Show BIM element counts and project file size."""
    root = require_project(ctx, "measuring the model")
    elements, stories = list_bim(ctx)
    count_by_kind: dict[str, int] = {}
    for item in elements:
        kind = str(item.get("kind", "unclassified"))
        count_by_kind[kind] = count_by_kind.get(kind, 0) + 1
    rows = [{"kind": kind, "count": count} for kind, count in sorted(count_by_kind.items())]
    total_bytes = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    return result(
        summary={
            "elementCount": len(elements),
            "storyCount": len(stories),
            "sizeKb": round(total_bytes / 1024, 2),
        },
        tables=[table("Element counts", [("kind", "Kind"), ("count", "Count")], rows)],
        notes=["File size includes the project folder; computed caches are not distinguished."],
    )


@feature(
    "project.projectInfo", "Project Information", part="settings", fields=[], requires_project=True
)
def project_info(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise project name and settings metadata."""
    require_project(ctx, "viewing project information")
    row = _settings_row(ctx)
    raw = settings_dict(ctx)
    return result(
        summary={
            "projectName": row["name"],
            "location": row["location"],
            "areaLoadCount": row["areaLoads"],
        },
        tables=[
            table(
                "Project information",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": k, "value": str(v)}
                    for k, v in {
                        "Name": row["name"],
                        "Location": row["location"],
                        "Engineer": row["engineer"],
                        "Occupancy": str(raw.get("occupancy", {})),
                    }.items()
                ],
            )
        ],
    )


@feature(
    "project.locationSite",
    "Location and Site",
    part="settings",
    fields=[text("location", "Site location", ""), text("siteClass", "Site classification", "")],
    requires_project=True,
)
def location_site(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Read and update project location and site classification."""
    root = require_project(ctx, "editing location and site")
    raw = settings_dict(ctx)
    if not raw:
        raise FeatureInputError("Open a project with project settings.")
    site = raw.setdefault("site", {})
    if values["location"].strip():
        site["location"] = values["location"].strip()
    if values["siteClass"].strip():
        site["siteClass"] = values["siteClass"].strip()
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(
        summary={"location": site.get("location", ""), "siteClass": site.get("siteClass", "")},
        tables=[
            table(
                "Location and site",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Location", "value": site.get("location", "")},
                    {"field": "Site class", "value": site.get("siteClass", "")},
                ],
            )
        ],
    )


@feature(
    "project.clientDetails",
    "Client Details",
    part="settings",
    fields=[text("client", "Client name", ""), text("email", "Client email", "")],
    requires_project=True,
)
def client_details(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Maintain client identity fields in project settings."""
    root = require_project(ctx, "editing client details")
    raw = settings_dict(ctx)
    if not raw:
        raise FeatureInputError("Open a project with project settings.")
    project = raw.setdefault("project", {})
    if values["client"].strip():
        project["client"] = values["client"].strip()
    if values["email"].strip():
        project["clientEmail"] = values["email"].strip()
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(
        summary={"client": project.get("client", ""), "clientEmail": project.get("clientEmail", "")}
    )


@feature(
    "project.buildingCodes", "Building Codes", part="settings", fields=[], requires_project=True
)
def building_codes(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report the active code-pack identifier and project occupancy settings."""
    require_project(ctx, "viewing building codes")
    raw = settings_dict(ctx)
    if not raw:
        raise FeatureInputError("Open a project with project settings.")
    occupancy = raw.get("occupancy", {})
    return result(
        summary={
            "codePackConfigured": bool(raw.get("codePack")),
            "occupancyUse": occupancy.get("use", "") if isinstance(occupancy, dict) else "",
        },
        tables=[
            table(
                "Project code configuration",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Code pack", "value": raw.get("codePack", "")},
                    {
                        "field": "Occupancy",
                        "value": occupancy.get("use", "") if isinstance(occupancy, dict) else "",
                    },
                ],
            )
        ],
    )


@feature("project.teamMembers", "Team Members", part="settings", fields=[], requires_project=True)
def team_members(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List named team fields available in project settings."""
    require_project(ctx, "viewing team members")
    raw = settings_dict(ctx)
    project = raw.get("project", {}) if isinstance(raw.get("project"), dict) else {}
    team = raw.get("team", []) if isinstance(raw.get("team"), list) else []
    rows = [item if isinstance(item, dict) else {"name": str(item)} for item in team]
    if project.get("engineer"):
        rows.insert(0, {"name": project["engineer"], "role": "Engineer"})
    return result(
        summary={"memberCount": len(rows)},
        tables=[table("Team members", [("name", "Name"), ("role", "Role")], rows)],
    )


@feature(
    "project.rolePermissions",
    "Role Permissions",
    part="settings",
    fields=[text("role", "Role", "Reviewer")],
    requires_project=True,
)
def role_permissions(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display the role permission matrix declared by the project."""
    require_project(ctx, "viewing role permissions")
    raw = settings_dict(ctx)
    permissions = raw.get("permissions", {}) if isinstance(raw.get("permissions"), dict) else {}
    role = values["role"]
    role_value = permissions.get(role, {}) if isinstance(permissions.get(role), dict) else {}
    rows = [{"permission": k, "enabled": bool(v)} for k, v in role_value.items()] or [
        {"permission": "No role matrix configured", "enabled": False}
    ]
    return result(
        summary={"role": role, "permissionCount": len(rows)},
        tables=[
            table("Role permissions", [("permission", "Permission"), ("enabled", "Enabled")], rows)
        ],
    )


@feature(
    "project.worksharingStatus",
    "Worksharing Status",
    part="settings",
    fields=[],
    requires_project=True,
)
def worksharing_status(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report local git worksharing status through the version engine."""
    root = require_project(ctx, "checking worksharing status")
    from saengine.project import versions

    try:
        status = versions.status(str(root))
    except versions.VersionsError as error:
        raise FeatureInputError(str(error)) from error
    return result(
        summary={
            "initialized": status.get("initialized", False),
            "clean": status.get("clean", True),
            "count": status.get("count", 0),
        },
        tables=[
            table(
                "Worksharing status",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": k, "value": str(v)}
                    for k, v in status.items()
                    if k not in ("parts", "changedParts", "problems")
                ],
            )
        ],
        notes=status.get("problems", []),
    )


@feature(
    "project.userActivity",
    "User Activity",
    part="settings",
    fields=[text("author", "Author filter", "")],
    requires_project=True,
)
def user_activity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List saved versions and their authors."""
    root = require_project(ctx, "viewing user activity")
    from saengine.project import versions

    history = versions.list_versions(str(root), 200)
    needle = values["author"].strip().lower()
    rows = [
        {
            "author": item.get("authorName", ""),
            "time": item.get("time", ""),
            "message": item.get("message", ""),
        }
        for item in history["versions"]
        if not needle or needle in str(item.get("authorName", "")).lower()
    ]
    return result(
        summary={"activityCount": len(rows)},
        tables=[
            table(
                "User activity",
                [("author", "Author"), ("time", "Time"), ("message", "Activity")],
                rows,
            )
        ],
    )


@feature("project.modelWarnings", "Model Warnings", part="bim", fields=[], requires_project=True)
def model_warnings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report BIM elements missing required kind, type, or geometry references."""
    require_project(ctx, "checking model warnings")
    elements, _ = list_bim(ctx)
    rows = [
        {"element": item.get("id", ""), "warning": warning}
        for item in elements
        for warning in (["Missing kind"] if not item.get("kind") else [])
        + (["Missing type"] if not item.get("type") else [])
    ]
    return result(
        summary={"warningCount": len(rows)},
        tables=[
            table(
                "Model warnings",
                [("element", "Element"), ("warning", "Warning")],
                rows or [{"element": "-", "warning": "No structural identity warnings found"}],
            )
        ],
    )


@feature("project.elementCount", "Element Count", part="bim", fields=[], requires_project=True)
def element_count(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Count BIM elements by kind and element type."""
    require_project(ctx, "counting model elements")
    elements, stories = list_bim(ctx)
    kinds: dict[str, int] = {}
    types: dict[str, int] = {}
    for item in elements:
        kinds[str(item.get("kind", "Unknown"))] = kinds.get(str(item.get("kind", "Unknown")), 0) + 1
        types[str(item.get("type", "Unknown"))] = types.get(str(item.get("type", "Unknown")), 0) + 1
    rows = [{"kind": k, "count": v} for k, v in sorted(kinds.items())]
    return result(
        summary={
            "elementCount": len(elements),
            "kindCount": len(kinds),
            "storyCount": len(stories),
        },
        tables=[table("Element counts", [("kind", "Kind"), ("count", "Count")], rows)],
    )


@feature(
    "project.performanceCheck",
    "Performance Check",
    part="bim",
    fields=[
        number("elementLimit", "Element count warning threshold", 10000.0, unit="elements", min=1)
    ],
    requires_project=True,
)
def performance_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare model size and file set against a configurable warning threshold."""
    root = require_project(ctx, "checking project performance")
    elements, _ = list_bim(ctx)
    total = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    return result(
        summary={
            "elementCount": len(elements),
            "sizeMb": round(total / 1024 / 1024, 3),
            "overElementLimit": len(elements) > values["elementLimit"],
        },
        tables=[
            table(
                "Performance check",
                [("check", "Check"), ("value", "Value"), ("status", "Status")],
                [
                    {
                        "check": "Elements",
                        "value": len(elements),
                        "status": "WARNING" if len(elements) > values["elementLimit"] else "OK",
                    },
                    {
                        "check": "Folder size MB",
                        "value": round(total / 1024 / 1024, 3),
                        "status": "OK",
                    },
                ],
            )
        ],
    )


@feature(
    "project.integrityLog",
    "Integrity Log",
    part="settings",
    fields=[text("filename", "Integrity filename", "integrity-log")],
    requires_project=True,
)
def integrity_log(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Write a JSON integrity report for all project part files."""
    root = require_project(ctx, "writing an integrity log")
    records = []
    for path in sorted(root.rglob("*.json")):
        if ".git" in path.parts:
            continue
        try:
            json.loads(path.read_text("utf-8"))
            status = "VALID"
        except (OSError, json.JSONDecodeError):
            status = "INVALID"
        records.append({"file": str(path.relative_to(root)), "status": status})
    name = values["filename"].strip().replace(" ", "-") or "integrity-log"
    path = write_export(ctx, "11 Exports", f"{name}.json", json_text(records))
    return result(
        summary={
            "jsonFileCount": len(records),
            "invalidCount": sum(r["status"] == "INVALID" for r in records),
            "exportPath": str(path),
        },
        tables=[table("JSON integrity", [("file", "File"), ("status", "Status")], records)],
        notes=[f"Integrity log written to {path}."],
    )


@feature(
    "project.projectStandards",
    "Project Standards",
    part="settings",
    fields=[text("standardName", "Standard name", "")],
    requires_project=True,
)
def project_standards(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record a named project standard in project settings."""
    root = require_project(ctx, "editing project standards")
    raw = settings_dict(ctx)
    if not raw:
        raise FeatureInputError("Open a project with project settings.")
    standards = raw.setdefault("standards", [])
    if not isinstance(standards, list):
        standards = []
        raw["standards"] = standards
    if values["standardName"].strip():
        standards.append(values["standardName"].strip())
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(
        summary={"standardCount": len(standards)},
        tables=[
            table(
                "Project standards",
                [("standard", "Standard")],
                [{"standard": str(item)} for item in standards],
            )
        ],
    )


@feature(
    "project.namingRules",
    "Naming Rules",
    part="settings",
    fields=[text("prefix", "Object ID prefix", "EL")],
    requires_project=True,
)
def naming_rules(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate object IDs against a configurable prefix and required numbering."""
    require_project(ctx, "checking naming rules")
    prefix = values["prefix"].strip()
    if not prefix:
        raise FeatureInputError("Enter an object ID prefix.")
    rows = []
    for item in list_objects(ctx):
        item_id = str(item.get("id", ""))
        rows.append({"object": item_id, "valid": item_id.startswith(prefix)})
    return result(
        summary={"objectCount": len(rows), "invalidCount": sum(not r["valid"] for r in rows)},
        tables=[table("Naming rule check", [("object", "Object"), ("valid", "Valid")], rows)],
    )


@feature(
    "project.unitSystem",
    "Unit System",
    part="settings",
    fields=[text("unitSystem", "Unit system", "SI")],
    requires_project=True,
)
def unit_system(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Display or set the project unit-system label."""
    root = require_project(ctx, "editing unit system")
    raw = settings_dict(ctx)
    if not raw:
        raise FeatureInputError("Open a project with project settings.")
    unit = values["unitSystem"].strip() or "SI"
    raw.setdefault("units", {})["system"] = unit
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(
        summary={"unitSystem": unit}, notes=["SAEngine's structural quantities remain in SI units."]
    )


@feature(
    "project.projectBaseline",
    "Project Baseline",
    part="settings",
    fields=[text("baselineName", "Baseline name", "Approved baseline")],
    requires_project=True,
)
def project_baseline(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create a baseline record and save it as a project export."""
    require_project(ctx, "creating a project baseline")
    baseline = {
        "name": values["baselineName"],
        "project": project_name(ctx),
        "objects": len(list_objects(ctx)),
        "bimElements": len(list_bim(ctx)[0]),
    }
    path = write_export(
        ctx,
        "11 Exports",
        f"{values['baselineName'].replace(' ', '-').lower()}.baseline.json",
        json_text(baseline),
    )
    return result(
        summary={**baseline, "exportPath": str(path)}, notes=[f"Baseline written to {path}."]
    )


@feature(
    "project.phaseManager",
    "Phase Manager",
    part="settings",
    fields=[text("phaseName", "Phase name", "Construction")],
    requires_project=True,
)
def phase_manager(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Add a named project phase and list all configured phases."""
    root = require_project(ctx, "editing project phases")
    raw = settings_dict(ctx)
    if not raw:
        raise FeatureInputError("Open a project with project settings.")
    phases = raw.setdefault("phases", [])
    if not isinstance(phases, list):
        phases = []
        raw["phases"] = phases
    if values["phaseName"].strip() and values["phaseName"].strip() not in phases:
        phases.append(values["phaseName"].strip())
    path = root / "02 Project Settings/project-settings.json"
    path.write_text(json_text(raw), encoding="utf-8")
    ctx._cache.pop("settings", None)
    return result(
        summary={"phaseCount": len(phases)},
        tables=[
            table("Project phases", [("phase", "Phase")], [{"phase": str(item)} for item in phases])
        ],
    )


@feature(
    "project.deliverableStatus",
    "Deliverable Status",
    part="exports",
    fields=[],
    requires_project=True,
)
def deliverable_status(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List generated deliverable files under 11 Exports."""
    root = require_project(ctx, "checking deliverables")
    folder = root / "11 Exports"
    rows = (
        [
            {
                "file": str(p.relative_to(root)),
                "sizeKb": round(p.stat().st_size / 1024, 2),
                "status": "Present",
            }
            for p in sorted(folder.rglob("*"))
            if p.is_file()
        ]
        if folder.is_dir()
        else []
    )
    return result(
        summary={"deliverableCount": len(rows)},
        tables=[
            table(
                "Deliverables",
                [("file", "File"), ("sizeKb", "Size", "KB"), ("status", "Status")],
                rows or [{"file": "-", "sizeKb": 0, "status": "No exports"}],
            )
        ],
    )
