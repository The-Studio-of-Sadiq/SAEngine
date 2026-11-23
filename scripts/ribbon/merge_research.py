"""Builds scripts/ribbon/ribbon_catalog.json from the ribbon research (2026-11-23).

Inputs (not in the repo): the OpenCode/DeepSeek ribbon spec and the Gemini review of it, given
as paths. The catalog it writes is the source of truth afterwards; edit it by hand from then on
and run gen_ribbon_catalog.py.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent

# Tabs the spec split finer than the windows need: merged into one tab of the same window.
REMAP = {
    "studiesOptions": "studiesDesign",
    "studiesComfort": "studiesEnvironment",
    "studiesEnergy": "studiesEnvironment",
    "studiesTerrain": "studiesSite",
    "studiesEarthworks": "studiesSite",
    "studiesBenchmarks": "studiesVerification",
    "studiesValidity": "studiesVerification",
    "overviewHome": "project",
}

SCOPES: dict[str, str] = {}


def scope(names: str, value: str) -> None:
    for name in names.split():
        SCOPES[name] = value


scope(
    "soil soilProfile soilTests soilBearing soilSeismic soilEarth soilSite soilReport soilDesign",
    "soil",
)
scope("settings settingsOccupancy", "settings.code")
scope("settingsLoads", "settings.loads")
scope("settingsHazard", "settings.hazard")
scope("settingsFoundation", "settings.foundation")
scope("settingsDrawings", "settings.drawings")
scope("settingsOverrides", "settings.codeValues")
scope("settingsChecks settingsUnits settingsAudit", "settings")
scope("library libraryConcrete libraryMasonry libraryCompliance", "materials")
scope("librarySections objDesigner objRebar objWalls libraryObjects libraryChecks", "objects")
scope("plan planLoads planModelling planChecks", "plan.plan")
scope("grid stories gridCoords", "plan.grids")
scope("members memberGroups memberData", "plan.members")
scope(
    "architecture architectureRooms architectureEnvelope architectureFinishes "
    "architectureExchange architectureEnvironment architectureChecks",
    "architecture",
)
scope("bim3d bimView bimNavigation bimStudies", "bim.3d")
scope("bimAdditions bimFabrication", "bim.additions")
scope("bimExchange bimSummary bimQuantities bimQa", "bim.summary")
scope("mepCoordination mepIssues mepClash mepViews", "mep.coordination")
scope("mepPlumbing mepPlumbingDesign mepDrainage mepFixtures", "mep.plumbing")
scope("mepHvac mepHvacAnalysis mepDucts mepEquipment", "mep.hvac")
scope("mepElectrical mepPowerSystems mepLighting mepContainment mepLowVoltage", "mep.electrical")
scope("mepFire mepFireSystems mepSprinkler mepSmoke", "mep.fire")
scope("mepSystems mepBrowser mepFabrication mepCommissioning", "mep.systems")
scope("analyze femLoads femSeismic femWind femMesh femModel", "fem.model")
scope("results femServiceability femCharts femTables femDynamics", "fem.charts")
scope("femNonlinear femHinges femCapacity", "fem.pushover")
scope("design femDetailing femCode", "fem.design")
scope("femCfd femCfdResults femWindClimate", "fem.cfd")
scope("femStrutTie femStmResults femStmRegions", "fem.stm")
scope(
    "foundations foundationsPiles foundationsPileAnalysis foundationsRetaining foundationsSpecial "
    "foundationsDetailing foundationsLoads foundationsReport",
    "foundations",
)
scope("boq boqCosting boqSchedule boqTakeoff boqLibrary boqReconcile boqReports", "boq")
scope("documents documentsDrawings documentsSheets docMarkup", "documents.drawing")
scope("documentsReports documentsSchedules docTemplate docFields", "documents.report")
scope("docWorksheet docCalc docCharts", "documents.worksheet")
scope("studies studiesDesign studiesEnvironment studiesSite studiesVerification", "studies")
scope("exportsExchange exportsFabrication exportsArchive exportsPublish", "exports")
scope("project overviewParts overviewActivity overviewTasks overviewLearning", "overview")

# Labels of the tabs this round adds (the others exist in ribbonRegistry.ts).
NEW_TABS = {
    "soilProfile": "Profile & CPT",
    "soilReport": "Report",
    "soilDesign": "Geotechnical Design",
    "settingsOccupancy": "Occupancy",
    "settingsFoundation": "Foundation",
    "settingsDrawings": "Drawings & Report",
    "settingsUnits": "Units",
    "settingsAudit": "Audit",
    "libraryConcrete": "Concrete",
    "libraryMasonry": "Masonry",
    "libraryCompliance": "Compliance",
    "objDesigner": "Section Designer",
    "objRebar": "Rebar",
    "objWalls": "Walls & Slabs",
    "planLoads": "Loads",
    "planModelling": "Modelling",
    "planChecks": "Checks",
    "grid": "Grids",
    "stories": "Stories",
    "gridCoords": "Coordinates",
    "members": "Members",
    "memberGroups": "Groups",
    "memberData": "Data",
    "architectureEnvelope": "Envelope",
    "architectureFinishes": "Finishes",
    "architectureChecks": "Checks",
    "bimView": "View",
    "bimNavigation": "Navigate",
    "bimAdditions": "Additions",
    "bimSummary": "Summary",
    "bimQuantities": "Quantities",
    "bimQa": "Model QA",
    "mepClash": "Clash Detection",
    "mepViews": "Views",
    "mepDrainage": "Drainage",
    "mepFixtures": "Fixtures",
    "mepDucts": "Ducts",
    "mepEquipment": "Equipment",
    "mepLighting": "Lighting",
    "mepContainment": "Containment",
    "mepLowVoltage": "Low Voltage",
    "mepSprinkler": "Sprinklers",
    "mepSmoke": "Smoke Control",
    "mepBrowser": "Browser",
    "mepFabrication": "Fabrication",
    "mepCommissioning": "Commissioning",
    "femMesh": "Mesh",
    "femModel": "Define",
    "femCharts": "Charts",
    "femTables": "Tables",
    "femDynamics": "Dynamics",
    "femHinges": "Hinges",
    "femCapacity": "Capacity Curve",
    "femDetailing": "Detailing",
    "femCode": "Code Checks",
    "femCfd": "CFD Setup",
    "femCfdResults": "CFD Results",
    "femWindClimate": "Wind Climate",
    "femStrutTie": "Strut-and-Tie",
    "femStmResults": "STM Results",
    "femStmRegions": "D-Regions",
    "foundationsDetailing": "Detailing",
    "foundationsLoads": "Loads",
    "boqLibrary": "Cost Library",
    "boqReconcile": "Reconcile",
    "boqReports": "Reports",
    "docMarkup": "Markup",
    "docTemplate": "Template",
    "docFields": "Fields",
    "docWorksheet": "Worksheet",
    "docCalc": "Calculation",
    "docCharts": "Charts",
    "exportsPublish": "Publish",
    "overviewParts": "Parts",
    "overviewActivity": "Activity",
    "overviewTasks": "Tasks",
    "overviewLearning": "Learning",
}

# Gemini's group of code-named combination generators (EN 1990, ASCE 7): the UI stays code
# independent, the code pack picks the combinations.
SKIP_GROUPS = {"Auto Combinations"}


def main(spec_path: str, review_path: str) -> None:
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    removed = {r["label"] for r in review["remove"]}
    merged: dict[tuple[str, str], list[dict[str, str]]] = collections.OrderedDict()
    for entry in spec:
        tab = REMAP.get(entry["tab"], entry["tab"])
        for button in entry["buttons"]:
            if button["label"] in removed:
                continue
            merged.setdefault((tab, entry["group"]), []).append(
                {
                    "label": button["label"],
                    "size": button.get("size", "small"),
                    "description": button["description"],
                    "inspiredBy": button.get("inspiredBy", ""),
                }
            )
    for add in review["add"]:
        if add["group"] in SKIP_GROUPS:
            continue
        for label in add["buttons"]:
            merged.setdefault((add["tab"], add["group"]), []).append(
                {
                    "label": label,
                    "size": "small",
                    "description": f"{label}.",
                    "inspiredBy": "review",
                }
            )
    groups = [{"tab": t, "group": g, "buttons": b} for (t, g), b in merged.items()]
    unknown = sorted({g["tab"] for g in groups if g["tab"] not in SCOPES})
    if unknown:
        raise SystemExit(f"tabs without a scope: {unknown}")
    catalog = {
        "tabs": [{"id": t, "label": label, "scope": SCOPES[t]} for t, label in NEW_TABS.items()],
        "scopes": SCOPES,
        "groups": groups,
    }
    out = HERE / "ribbon_catalog.json"
    out.write_text(json.dumps(catalog, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(len(groups), sum(len(g["buttons"]) for g in groups), len(NEW_TABS))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
