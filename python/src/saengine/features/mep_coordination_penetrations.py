"""Service penetrations, openings and firestop coordination."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

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


def _penetrations(ctx: FeatureContext) -> list[dict]:
    raw = ctx.raw("mep")
    coordination = raw.get("coordination", {}) if isinstance(raw, dict) else {}
    items = coordination.get("penetrations", []) if isinstance(coordination, dict) else []
    if not isinstance(items, list) or not items:
        raise FeatureInputError(
            "Add penetration records to coordination.penetrations in 07 MEP/mep.json."
        )
    return [item for item in items if isinstance(item, dict)]


@feature(
    "mepCoordinationPenetrations.placeSleeve",
    "Place Sleeve",
    part="mep",
    fields=[
        number("serviceDiameterMm", "Service outside diameter", 80, unit="mm", min=1),
        number("radialClearanceMm", "Radial clearance", 10, unit="mm", min=0),
        number("wallThicknessMm", "Host thickness", 200, unit="mm", min=1),
    ],
    requires_project=False,
)
def place_sleeve(ctx: FeatureContext, v: dict) -> dict:
    """Calculate sleeve diameter and length from service and host geometry."""
    return result(
        {
            "sleeveDiameterMm": v["serviceDiameterMm"] + 2 * v["radialClearanceMm"],
            "sleeveLengthMm": v["wallThicknessMm"],
        },
        notes=[
            "Sleeve allowance is an explicit input; confirm the seal assembly and required projection at each face."
        ],
    )


@feature(
    "mepCoordinationPenetrations.cutOpening",
    "Cut Opening",
    part="mep",
    fields=[
        number("serviceWidthMm", "Service width", 300, unit="mm", min=1),
        number("serviceHeightMm", "Service height", 200, unit="mm", min=1),
        number("clearanceMm", "Perimeter clearance", 50, unit="mm", min=0),
    ],
    requires_project=False,
)
def cut_opening(ctx: FeatureContext, v: dict) -> dict:
    """Size a rectangular builder's opening around a service."""
    width, height = (
        v["serviceWidthMm"] + 2 * v["clearanceMm"],
        v["serviceHeightMm"] + 2 * v["clearanceMm"],
    )
    return result(
        {"openingWidthMm": width, "openingHeightMm": height, "openingAreaM2": width * height / 1e6},
        notes=[
            "Geometric opening size only; structural design and fire/acoustic sealing are separate approvals."
        ],
    )


@feature(
    "mepCoordinationPenetrations.coreHole",
    "Core Hole",
    part="mep",
    fields=[
        number("pipeDiameterMm", "Pipe outside diameter", 80, unit="mm", min=1),
        number("annularClearanceMm", "Annular clearance", 15, unit="mm", min=0),
        number("hostThicknessMm", "Host thickness", 200, unit="mm", min=1),
    ],
    requires_project=False,
)
def core_hole(ctx: FeatureContext, v: dict) -> dict:
    """Calculate a circular core-hole diameter and drilling depth."""
    diameter = v["pipeDiameterMm"] + 2 * v["annularClearanceMm"]
    return result(
        {
            "coreDiameterMm": diameter,
            "drillDepthMm": v["hostThicknessMm"],
            "coreAreaM2": math.pi * diameter**2 / 4e6,
        },
        notes=[
            "Clearance must suit the selected sleeve and seal system; confirm structural approval before drilling."
        ],
    )


@feature(
    "mepCoordinationPenetrations.applySeal",
    "Apply Seal",
    part="mep",
    fields=[
        number("openingDiameterMm", "Opening diameter", 150, unit="mm", min=1),
        number("serviceDiameterMm", "Service diameter", 80, unit="mm", min=0),
        number("sealDepthMm", "Seal depth", 25, unit="mm", min=1),
        number("materialYieldPercent", "Installed material yield", 85, unit="%", min=1, max=100),
    ],
    requires_project=False,
)
def apply_seal(ctx: FeatureContext, v: dict) -> dict:
    """Estimate sealant volume in the annular space around a circular service."""
    volume = (
        math.pi
        * max(0, v["openingDiameterMm"] ** 2 - v["serviceDiameterMm"] ** 2)
        / 4
        * v["sealDepthMm"]
        / 1e6
    )
    return result(
        {
            "theoreticalVolumeL": volume,
            "procurementVolumeL": volume / (v["materialYieldPercent"] / 100),
        },
        notes=[
            "Annular cylinder approximation; backing material, irregular openings and product-specific installation details are excluded."
        ],
    )


@feature(
    "mepCoordinationPenetrations.assignFirestop",
    "Assign Firestop",
    part="mep",
    fields=[
        select(
            "systemType", "Penetration type", ["metal pipe", "plastic pipe", "cable bundle", "duct"]
        ),
        text("testedSystem", "Selected tested system", ""),
        number("ratingMinutes", "Required rating", 60, unit="min", min=0),
    ],
    requires_project=False,
)
def assign_firestop(ctx: FeatureContext, v: dict) -> dict:
    """Record the selected tested firestop assembly basis for a penetration."""
    return result(
        {
            "systemType": v["systemType"],
            "testedSystem": v["testedSystem"],
            "requiredRatingMinutes": v["ratingMinutes"],
        },
        notes=[
            "Select a tested assembly matching the actual host, service, annular gap and installation configuration."
        ],
    )


@feature(
    "mepCoordinationPenetrations.fireRating",
    "Fire Rating",
    part="mep",
    fields=[
        number("hostRatingMinutes", "Host rating", 120, unit="min", min=0),
        number("sealRatingMinutes", "Seal rating", 90, unit="min", min=0),
    ],
    requires_project=False,
)
def fire_rating(ctx: FeatureContext, v: dict) -> dict:
    """Check that the selected penetration seal rating meets the host requirement."""
    return result(
        {
            "requiredRatingMinutes": v["hostRatingMinutes"],
            "providedRatingMinutes": v["sealRatingMinutes"],
            "pass": v["sealRatingMinutes"] >= v["hostRatingMinutes"],
        },
        notes=[
            "Ratings are compared numerically; verify the tested assembly and applicable jurisdictional rules."
        ],
    )


@feature(
    "mepCoordinationPenetrations.sealType",
    "Seal Type",
    part="mep",
    fields=[
        select("service", "Service material", ["metal pipe", "plastic pipe", "cable", "duct"]),
        select(
            "seal",
            "Seal approach",
            ["firestop mortar", "intumescent sealant", "wrap strip", "collar", "acoustic packing"],
        ),
        number("annularGapMm", "Annular gap", 20, unit="mm", min=0),
    ],
    requires_project=False,
)
def seal_type(ctx: FeatureContext, v: dict) -> dict:
    """Summarize service and seal selection with the installed annular gap."""
    return result(
        {"service": v["service"], "sealApproach": v["seal"], "annularGapMm": v["annularGapMm"]},
        notes=[
            "Confirm the selected system has a tested listing for the exact service, host and gap."
        ],
    )


@feature(
    "mepCoordinationPenetrations.firestopSchedule",
    "Firestop Schedule",
    part="mep",
    fields=[],
    requires_project=True,
)
def firestop_schedule(ctx: FeatureContext, v: dict) -> dict:
    """Schedule recorded service penetrations and their firestop ratings."""
    rows = _penetrations(ctx)
    return result(
        {"penetrationCount": len(rows)},
        [
            table(
                "Firestop register",
                [
                    ("id", "ID"),
                    ("service", "Service"),
                    ("host", "Host"),
                    ("system", "Firestop system"),
                    ("ratingMinutes", "Rating", "min"),
                ],
                [
                    {
                        "id": x.get("id", ""),
                        "service": x.get("service", ""),
                        "host": x.get("host", ""),
                        "system": x.get("firestopSystem", ""),
                        "ratingMinutes": x.get("ratingMinutes"),
                    }
                    for x in rows
                ],
            )
        ],
    )


@feature(
    "mepCoordinationPenetrations.penetrationList",
    "Penetration List",
    part="mep",
    fields=[text("level", "Level filter", "")],
    requires_project=True,
)
def penetration_list(ctx: FeatureContext, v: dict) -> dict:
    """List project penetrations filtered by building level."""
    rows = [x for x in _penetrations(ctx) if not v["level"] or x.get("level") == v["level"]]
    return result(
        {"penetrationCount": len(rows), "level": v["level"]},
        [
            table(
                "Penetrations",
                [
                    ("id", "ID"),
                    ("level", "Level"),
                    ("service", "Service"),
                    ("host", "Host"),
                    ("diameterMm", "Diameter", "mm"),
                    ("status", "Status"),
                ],
                [
                    {
                        "id": x.get("id", ""),
                        "level": x.get("level", ""),
                        "service": x.get("service", ""),
                        "host": x.get("host", ""),
                        "diameterMm": x.get("diameterMm"),
                        "status": x.get("status", ""),
                    }
                    for x in rows
                ],
            )
        ],
    )


@feature(
    "mepCoordinationPenetrations.conflictCheck",
    "Conflict Check",
    part="mep",
    fields=[
        number("openingXM", "Opening X", 0, unit="m"),
        number("openingYM", "Opening Y", 0, unit="m"),
        number("openingRadiusM", "Opening radius", 0.1, unit="m", min=0.001),
        number("embedXM", "Embedded item X", 0.15, unit="m"),
        number("embedYM", "Embedded item Y", 0, unit="m"),
        number("embedRadiusM", "Embedded item radius", 0.05, unit="m", min=0),
    ],
    requires_project=False,
)
def conflict_check(ctx: FeatureContext, v: dict) -> dict:
    """Check plan overlap between a proposed opening and an embedded item."""
    separation = math.hypot(v["openingXM"] - v["embedXM"], v["openingYM"] - v["embedYM"])
    clearance = separation - v["openingRadiusM"] - v["embedRadiusM"]
    return result(
        {"centerSeparationM": separation, "edgeClearanceM": clearance, "conflict": clearance < 0},
        notes=[
            "2D circular clearance test; slab thickness, reinforcement zones and tolerances must also be assessed."
        ],
    )


@feature(
    "mepCoordinationPenetrations.approvePenetration",
    "Approve Penetration",
    part="mep",
    fields=[
        text("penetrationId", "Penetration ID", ""),
        select("decision", "Decision", ["approved", "revise", "rejected"]),
        text("reviewNote", "Review note", ""),
    ],
    requires_project=True,
)
def approve_penetration(ctx: FeatureContext, v: dict) -> dict:
    """Report a proposed penetration review decision against a project record."""
    rows = _penetrations(ctx)
    match = next((x for x in rows if x.get("id") == v["penetrationId"]), None)
    if match is None:
        raise FeatureInputError(
            f"Penetration {v['penetrationId']!r} is not in the project register."
        )
    return result(
        {"penetrationId": v["penetrationId"], "decision": v["decision"]},
        [
            table(
                "Review decision",
                [
                    ("id", "ID"),
                    ("location", "Location"),
                    ("currentStatus", "Current status"),
                    ("decision", "Decision"),
                    ("note", "Review note"),
                ],
                [
                    {
                        "id": v["penetrationId"],
                        "location": match.get("level", ""),
                        "currentStatus": match.get("status", ""),
                        "decision": v["decision"],
                        "note": v["reviewNote"],
                    }
                ],
            )
        ],
        ["Decision is returned for review; the source project file is not modified."],
    )


@feature(
    "mepCoordinationPenetrations.exportRegister",
    "Export Register",
    part="mep",
    fields=[text("filename", "CSV filename", "penetration-register.csv")],
    requires_project=True,
)
def export_register(ctx: FeatureContext, v: dict) -> dict:
    """Write a penetration register CSV into the project's MEP exports folder."""
    if ctx.root is None:
        raise FeatureInputError("Choose a project to export the penetration register.")
    name = Path(v["filename"]).name
    if not name.lower().endswith(".csv"):
        raise FeatureInputError("Choose a filename ending in .csv.")
    rows = _penetrations(ctx)
    path = ctx.path(f"07 MEP/exports/{name}")
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id",
        "level",
        "service",
        "host",
        "diameterMm",
        "firestopSystem",
        "ratingMinutes",
        "status",
    ]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return result(
        {"penetrationCount": len(rows), "exportPath": str(path)},
        notes=["Register fields are copied from project penetration records."],
    )


@feature(
    "mepCoordinationPenetrations.structuralImpact",
    "Structural Impact",
    part="mep",
    fields=[
        number("openingWidthMm", "Opening width", 400, unit="mm", min=1),
        number("openingHeightMm", "Opening height", 300, unit="mm", min=1),
        number("hostThicknessMm", "Host thickness", 200, unit="mm", min=1),
        number("memberWidthMm", "Host member width", 1000, unit="mm", min=1),
    ],
    requires_project=False,
)
def structural_impact(ctx: FeatureContext, v: dict) -> dict:
    """Estimate opening area and removed section fraction for screening."""
    section = v["hostThicknessMm"] * v["memberWidthMm"]
    removed = v["openingWidthMm"] * v["openingHeightMm"]
    return result(
        {"openingAreaM2": removed / 1e6, "removedAreaFraction": min(1.0, removed / section)},
        notes=[
            "Area ratio is a geometric screening measure, not a structural capacity check; obtain engineer approval before modifying a structural member."
        ],
    )


@feature(
    "mepCoordinationPenetrations.rebarConflictCheck",
    "Rebar Conflict Check",
    part="mep",
    fields=[
        number("openingRadiusMm", "Opening radius", 75, unit="mm", min=1),
        number("barCenterDistanceMm", "Nearest bar center distance", 100, unit="mm", min=0),
        number("barDiameterMm", "Bar diameter", 16, unit="mm", min=1),
        number("requiredClearanceMm", "Required clearance", 25, unit="mm", min=0),
    ],
    requires_project=False,
)
def rebar_conflict_check(ctx: FeatureContext, v: dict) -> dict:
    """Check opening-to-rebar surface clearance using measured plan coordinates."""
    clear = v["barCenterDistanceMm"] - v["openingRadiusMm"] - v["barDiameterMm"] / 2
    return result(
        {
            "barClearanceMm": clear,
            "requiredClearanceMm": v["requiredClearanceMm"],
            "conflict": clear < v["requiredClearanceMm"],
        },
        notes=[
            "2D measured-distance check; verify bar layers, slab depth, tolerances and reinforcement scanning results."
        ],
    )


@feature(
    "mepCoordinationPenetrations.webHoleLimit",
    "Web Hole Limit",
    part="mep",
    fields=[
        number("beamDepthMm", "Beam depth", 600, unit="mm", min=1),
        number("holeDiameterMm", "Hole diameter", 80, unit="mm", min=0),
        number("shearZoneStartM", "Shear-zone start from support", 0.5, unit="m", min=0),
        number("holePositionM", "Hole position from support", 1.5, unit="m", min=0),
    ],
    requires_project=False,
)
def web_hole_limit(ctx: FeatureContext, v: dict) -> dict:
    """Screen a beam web hole against a user-entered diameter and shear-zone limit."""
    max_diameter = 0.25 * v["beamDepthMm"]
    outside = v["holePositionM"] >= v["shearZoneStartM"]
    return result(
        {
            "diameterLimitMm": max_diameter,
            "diameterPass": v["holeDiameterMm"] <= max_diameter,
            "outsideSupportShearZone": outside,
        },
        notes=[
            "Conservative geometric screening only; beam openings require structural analysis and must not be cut without approval."
        ],
    )


@feature(
    "mepCoordinationPenetrations.lintelRequirement",
    "Lintel Requirement",
    part="mep",
    fields=[
        number("openingWidthMm", "Masonry opening width", 1200, unit="mm", min=0),
        number("wallThicknessMm", "Wall thickness", 200, unit="mm", min=1),
        number("bearingMm", "End bearing", 150, unit="mm", min=0),
        number("clearSpanLimitMm", "Project lintel span limit", 900, unit="mm", min=0),
    ],
    requires_project=False,
)
def lintel_requirement(ctx: FeatureContext, v: dict) -> dict:
    """Flag openings exceeding a project-provided masonry lintel span limit."""
    return result(
        {
            "lintelRequired": v["openingWidthMm"] > v["clearSpanLimitMm"],
            "minimumLintelLengthMm": v["openingWidthMm"] + 2 * v["bearingMm"],
            "wallThicknessMm": v["wallThicknessMm"],
        },
        notes=[
            "Span criterion is an explicit project input; lintel sizing and support reactions require structural design."
        ],
    )


@feature(
    "mepCoordinationPenetrations.sleeveThickness",
    "Sleeve Thickness",
    part="mep",
    fields=[
        number("wallThicknessMm", "Host wall thickness", 200, unit="mm", min=1),
        number("sleeveProjectionMm", "Projection each face", 10, unit="mm", min=0),
        number("sleeveWallMm", "Sleeve wall thickness", 2, unit="mm", min=0.1),
    ],
    requires_project=False,
)
def sleeve_thickness(ctx: FeatureContext, v: dict) -> dict:
    """Calculate sleeve cut length and wall-material cross-sectional area."""
    length = v["wallThicknessMm"] + 2 * v["sleeveProjectionMm"]
    return result(
        {"cutLengthMm": length, "wallThicknessMm": v["sleeveWallMm"]},
        notes=[
            "Cut length includes equal projections on both faces; verify substrate, corrosion protection and firestop compatibility."
        ],
    )


@feature(
    "mepCoordinationPenetrations.puddleFlange",
    "Puddle Flange",
    part="mep",
    fields=[
        number("pipeDiameterMm", "Pipe outside diameter", 100, unit="mm", min=1),
        number("flangeDiameterMm", "Flange diameter", 300, unit="mm", min=1),
        number("wallThicknessMm", "Wall thickness", 250, unit="mm", min=1),
    ],
    requires_project=False,
)
def puddle_flange(ctx: FeatureContext, v: dict) -> dict:
    """Calculate puddle-flange radial projection and gross plate area."""
    projection = (v["flangeDiameterMm"] - v["pipeDiameterMm"]) / 2
    return result(
        {
            "radialProjectionMm": projection,
            "grossFlangeAreaM2": math.pi
            * (v["flangeDiameterMm"] ** 2 - v["pipeDiameterMm"] ** 2)
            / 4e6,
            "wallThicknessMm": v["wallThicknessMm"],
        },
        notes=[
            "Dimensional estimate; confirm weld, waterproofing membrane and structural detailing."
        ],
    )


@feature(
    "mepCoordinationPenetrations.acousticSeal",
    "Acoustic Seal",
    part="mep",
    fields=[
        number("pipeDiameterMm", "Pipe diameter", 80, unit="mm", min=1),
        number("sleeveDiameterMm", "Sleeve inside diameter", 120, unit="mm", min=1),
        number("sealDepthMm", "Packing depth", 50, unit="mm", min=0),
    ],
    requires_project=False,
)
def acoustic_seal(ctx: FeatureContext, v: dict) -> dict:
    """Calculate annular acoustic packing volume around a pipe."""
    if v["sleeveDiameterMm"] < v["pipeDiameterMm"]:
        raise FeatureInputError("Sleeve inside diameter must exceed pipe diameter.")
    area = math.pi * (v["sleeveDiameterMm"] ** 2 - v["pipeDiameterMm"] ** 2) / 4
    return result(
        {"annularAreaMm2": area, "packingVolumeL": area * v["sealDepthMm"] / 1e6},
        notes=[
            "Geometric volume only; select a tested acoustic/fire seal with suitable movement allowance."
        ],
    )


@feature(
    "mepCoordinationPenetrations.penetrationDrawings",
    "Penetration Drawings",
    part="mep",
    fields=[text("drawingId", "Drawing identifier", "BW-01")],
    requires_project=True,
)
def penetration_drawings(ctx: FeatureContext, v: dict) -> dict:
    """Provide dimensioned coordinates and opening sizes for penetration drawings."""
    rows = _penetrations(ctx)
    coords = [
        {
            "id": x.get("id", ""),
            "level": x.get("level", ""),
            "xM": x.get("xM"),
            "yM": x.get("yM"),
            "widthMm": x.get("widthMm"),
            "heightMm": x.get("heightMm"),
            "diameterMm": x.get("diameterMm"),
        }
        for x in rows
    ]
    return result(
        {"drawingId": v["drawingId"], "penetrationCount": len(coords)},
        [
            table(
                "Builder-work opening coordinates",
                [
                    ("id", "ID"),
                    ("level", "Level"),
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("widthMm", "Width", "mm"),
                    ("heightMm", "Height", "mm"),
                    ("diameterMm", "Diameter", "mm"),
                ],
                coords,
            )
        ],
        [
            "Coordinate and size schedule from the MEP register; dimensions must be checked against the coordinated model."
        ],
    )


@feature(
    "mepCoordinationPenetrations.builderWorkHoles",
    "Builder Work Holes",
    part="mep",
    fields=[text("filename", "CSV filename", "builder-work-holes.csv")],
    requires_project=True,
)
def builder_work_holes(ctx: FeatureContext, v: dict) -> dict:
    """Export opening size, host and location data for builder-work coordination."""
    if ctx.root is None:
        raise FeatureInputError("Choose a project to export builder-work holes.")
    name = Path(v["filename"]).name
    if not name.lower().endswith(".csv"):
        raise FeatureInputError("Choose a filename ending in .csv.")
    rows = _penetrations(ctx)
    path = ctx.path(f"07 MEP/exports/{name}")
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["id", "level", "xM", "yM", "host", "widthMm", "heightMm", "diameterMm"]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return result(
        {"holeCount": len(rows), "exportPath": str(path)},
        notes=[
            "CSV exports registered dimensions and locations; structural approval status is not inferred."
        ],
    )


@feature(
    "mepCoordinationPenetrations.bimVoidExport",
    "BIM Void Export",
    part="mep",
    fields=[text("filename", "JSON filename", "structural-voids.json")],
    requires_project=True,
)
def bim_void_export(ctx: FeatureContext, v: dict) -> dict:
    """Write project penetration coordinates and sizes as BIM void objects."""
    if ctx.root is None:
        raise FeatureInputError("Choose a project to export BIM void objects.")
    name = Path(v["filename"]).name
    if not name.lower().endswith(".json"):
        raise FeatureInputError("Choose a filename ending in .json.")
    rows = _penetrations(ctx)
    path = ctx.path(f"07 MEP/exports/{name}")
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    voids = [
        {
            "id": item.get("id"),
            "level": item.get("level"),
            "xM": item.get("xM"),
            "yM": item.get("yM"),
            "widthMm": item.get("widthMm"),
            "heightMm": item.get("heightMm"),
            "diameterMm": item.get("diameterMm"),
            "host": item.get("host"),
        }
        for item in rows
    ]
    path.write_text(json.dumps({"voids": voids}, indent=2), encoding="utf-8")
    return result(
        {"voidCount": len(voids), "exportPath": str(path)},
        notes=["JSON is a coordination exchange register, not a native authoring-model edit."],
    )
