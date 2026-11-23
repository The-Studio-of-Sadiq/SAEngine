"""BIM accessibility, zoning, fire, structural, and environmental compliance features."""

from __future__ import annotations

from typing import Any

from saengine.features import FeatureContext, FeatureInputError, feature, number, result, table
from saengine.features.bim_common import polygon_area, require_bim


def _records(
    data: dict[str, Any], key: str, label: str, required: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    value = data.get(key)
    rows = [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []
    if not rows:
        raise FeatureInputError(f"Record {label} in 06 BIM/bim.json before running this check.")
    missing = sorted({field for row in rows for field in required if field not in row})
    if missing:
        raise FeatureInputError(f"Add {', '.join(missing)} to the recorded {label} first.")
    return rows


@feature("bimSummaryCompliance.routeCheck", "Route Check", part="bim")
def route_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check recorded accessible-route segments for obstructions."""
    data = require_bim(ctx)
    rows = _records(data, "accessibleRoutes", "accessible route results", ("status",))
    failures = sum(str(r.get("status", "Fail")).lower() != "pass" for r in rows)
    return result(
        summary={"routeCount": len(rows), "failedRouteCount": failures},
        tables=[
            table(
                "Accessible Routes",
                [("id", "Route"), ("status", "Status"), ("issue", "Issue")],
                rows,
            )
        ],
    )


@feature(
    "bimSummaryCompliance.clearWidth",
    "Clear Width",
    part="bim",
    fields=[number("requiredWidthMm", "Minimum clear width", 900.0, unit="mm", min=0)],
)
def clear_width(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure recorded door and corridor clear widths."""
    data = require_bim(ctx)
    widths = _records(data, "clearWidths", "clear widths", ("id", "widthMm"))
    rows = [
        {"id": r.get("id", ""), "widthMm": float(r.get("widthMm", 0.0))}
        for r in widths
        if isinstance(r, dict)
    ]
    failed = sum(r["widthMm"] < values["requiredWidthMm"] for r in rows)
    return result(
        summary={"requiredWidthMm": values["requiredWidthMm"], "failedCount": failed},
        tables=[table("Clear Widths", [("id", "Opening"), ("widthMm", "Clear width", "mm")], rows)],
    )


@feature(
    "bimSummaryCompliance.rampCheck",
    "Ramp Check",
    part="bim",
    fields=[number("maxGradient", "Maximum gradient", 0.083, unit="rise/run", min=0)],
)
def ramp_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify recorded ramp gradients and landing provisions."""
    data = require_bim(ctx)
    ramps = _records(data, "ramps", "ramp results", ("gradient", "landingCompliant"))
    rows = [
        {
            "id": r.get("id", ""),
            "gradient": float(r.get("gradient", 0.0)),
            "landingCompliant": bool(r.get("landingCompliant", False)),
        }
        for r in ramps
        if isinstance(r, dict)
    ]
    failed = sum(r["gradient"] > values["maxGradient"] or not r["landingCompliant"] for r in rows)
    return result(
        summary={"rampCount": len(rows), "failedCount": failed},
        tables=[
            table(
                "Ramps",
                [
                    ("id", "Ramp"),
                    ("gradient", "Gradient"),
                    ("landingCompliant", "Landing compliant"),
                ],
                rows,
            )
        ],
    )


@feature("bimSummaryCompliance.accessReport", "Access Report", part="bim")
def access_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Report accessibility nonconformances with locations."""
    data = require_bim(ctx)
    rows = _records(data, "accessibilityIssues", "accessibility issues")
    return result(
        summary={"issueCount": len(rows)},
        tables=[
            table(
                "Accessibility Issues",
                [
                    ("id", "Issue"),
                    ("location", "Location"),
                    ("category", "Category"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
    )


@feature(
    "bimSummaryCompliance.turningCircle",
    "Turning Circle",
    part="bim",
    fields=[number("diameterMm", "Turning circle diameter", 1500.0, unit="mm", min=500)],
)
def turning_circle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Overlay recorded wheelchair turning clearance zones."""
    data = require_bim(ctx)
    zones = _records(data, "turningZones", "turning-clearance zones")
    return result(
        summary={"diameterMm": values["diameterMm"], "zoneCount": len(zones)},
        tables=[
            table(
                "Turning Zones",
                [("id", "Zone"), ("location", "Location")],
                zones,
            )
        ],
    )


@feature(
    "bimSummaryCompliance.travelDistance",
    "Travel Distance",
    part="bim",
    fields=[number("maxDistanceM", "Maximum travel distance", 45.0, unit="m", min=1)],
)
def travel_distance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure recorded longest travel path to an exit."""
    data = require_bim(ctx)
    routes = _records(data, "egressRoutes", "egress routes", ("distanceM",))
    distances = [float(r["distanceM"]) for r in routes]
    longest = max(distances)
    return result(
        summary={"longestTravelM": longest, "compliant": longest <= values["maxDistanceM"]}
    )


@feature(
    "bimSummaryCompliance.exitWidth",
    "Exit Width",
    part="bim",
    fields=[
        number("occupantLoad", "Occupant load", 100.0, unit="persons", min=1),
        number(
            "widthPerPersonMm",
            "Required width per occupant",
            5.0,
            unit="mm/person",
            min=0,
        ),
    ],
)
def exit_width(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check recorded exit widths against occupant demand and a configurable width per person."""
    data = require_bim(ctx)
    exits = _records(data, "exits", "exit widths", ("widthMm",))
    required_mm = values["occupantLoad"] * values["widthPerPersonMm"]
    provided_mm = sum(float(r.get("widthMm", 0.0)) for r in exits if isinstance(r, dict))
    return result(
        summary={
            "requiredExitWidthMm": required_mm,
            "providedExitWidthMm": provided_mm,
            "compliant": provided_mm >= required_mm,
        }
    )


@feature("bimSummaryCompliance.occupantLoad", "Occupant Load", part="bim")
def occupant_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute occupant load from room area and recorded density."""
    data = require_bim(ctx)
    rooms = _records(
        data,
        "rooms",
        "room areas and occupant densities",
        ("areaM2", "areaPerPersonM2"),
    )
    total = sum(float(r["areaM2"]) / float(r["areaPerPersonM2"]) for r in rooms)
    if any(float(r["areaPerPersonM2"]) <= 0 for r in rooms):
        raise FeatureInputError("Room occupant density must be greater than zero.")
    return result(summary={"occupantLoadPersons": total, "roomCount": len(rooms)})


@feature("bimSummaryCompliance.egressReport", "Egress Report", part="bim")
def egress_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarise recorded egress results storey by storey."""
    data = require_bim(ctx)
    rows = _records(
        data,
        "egressByStorey",
        "storey egress results",
        ("storey", "occupants", "exitWidthMm", "status"),
    )
    return result(
        summary={"storeyCount": len(rows)},
        tables=[
            table(
                "Egress by Storey",
                [
                    ("storey", "Storey"),
                    ("occupants", "Occupants"),
                    ("exitWidthMm", "Exit width", "mm"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
    )


@feature(
    "bimSummaryCompliance.setbackCheck",
    "Setback Check",
    part="bim",
    fields=[number("requiredSetbackMm", "Minimum setback", 3000.0, unit="mm", min=0)],
)
def setback_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compare recorded site setbacks with the permitted value."""
    data = require_bim(ctx)
    setbacks = _records(data, "setbacks", "site setbacks", ("boundary", "setbackMm"))
    rows = [
        {"boundary": r.get("boundary", ""), "setbackMm": float(r.get("setbackMm", 0.0))}
        for r in setbacks
        if isinstance(r, dict)
    ]
    failed = sum(r["setbackMm"] < values["requiredSetbackMm"] for r in rows)
    return result(
        summary={"failedBoundaryCount": failed, "requiredSetbackMm": values["requiredSetbackMm"]},
        tables=[
            table("Setbacks", [("boundary", "Boundary"), ("setbackMm", "Setback", "mm")], rows)
        ],
    )


@feature(
    "bimSummaryCompliance.heightLimit",
    "Height Limit",
    part="bim",
    fields=[number("heightLimitMm", "Overall height limit", 50000.0, unit="mm", min=0)],
)
def height_limit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check overall model height against a configured limit."""
    data = require_bim(ctx)
    elevations = [
        float(s.get("elevation", 0.0)) for s in data.get("stories", []) if isinstance(s, dict)
    ]
    if len(elevations) < 2:
        raise FeatureInputError("Add at least two story elevations before checking overall height.")
    height = max(elevations, default=0.0) - min(elevations, default=0.0)
    return result(
        summary={
            "modelHeightMm": height,
            "heightLimitMm": values["heightLimitMm"],
            "compliant": height <= values["heightLimitMm"],
        }
    )


@feature(
    "bimSummaryCompliance.siteCoverage",
    "Site Coverage",
    part="bim",
    fields=[number("siteAreaM2", "Site area", 1000.0, unit="m²", min=0.1)],
)
def site_coverage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate site coverage from slab boundary areas."""
    data = require_bim(ctx)
    slabs = [
        e
        for e in data["elements"]
        if isinstance(e, dict)
        and e.get("kind") == "slab"
        and isinstance(e.get("boundary"), list)
        and isinstance(e.get("elevation"), (int, float))
    ]
    if not slabs:
        raise FeatureInputError(
            "Add slab boundaries and elevations before calculating site coverage."
        )
    ground_elevation = min(e["elevation"] for e in slabs)
    building_area = sum(
        polygon_area(e["boundary"]) / 1e6 for e in slabs if e["elevation"] == ground_elevation
    )
    coverage = building_area / values["siteAreaM2"] * 100
    return result(summary={"buildingAreaM2": building_area, "siteCoveragePercent": coverage})


@feature("bimSummaryCompliance.zoningReport", "Zoning Report", part="bim")
def zoning_report(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Produce a zoning compliance summary from recorded checks."""
    data = require_bim(ctx)
    rows = _records(data, "zoningChecks", "zoning check results")
    return result(
        summary={"checkCount": len(rows)},
        tables=[
            table(
                "Zoning Checks",
                [
                    ("check", "Check"),
                    ("required", "Required"),
                    ("provided", "Provided"),
                    ("status", "Status"),
                ],
                rows,
            )
        ],
    )


@feature("bimSummaryCompliance.fireCompartment", "Fire Compartment", part="bim")
def fire_compartment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit recorded continuous fire containment boundaries."""
    data = require_bim(ctx)
    rows = _records(data, "fireCompartments", "fire-compartment results", ("status",))
    return result(
        summary={
            "compartmentCount": len(rows),
            "failedCount": sum(
                str(r.get("status", "Fail")).lower() != "pass" for r in rows if isinstance(r, dict)
            ),
        }
    )


@feature("bimSummaryCompliance.fireRatingAudit", "Fire Rating Audit", part="bim")
def fire_rating_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify recorded fire resistance ratings for structural elements."""
    data = require_bim(ctx)
    rows = [
        {
            "id": e.get("id", ""),
            "requiredMinutes": e.get("requiredFireRatingMin", ""),
            "providedMinutes": e.get("providedFireRatingMin", ""),
        }
        for e in data["elements"]
        if isinstance(e, dict) and "requiredFireRatingMin" in e and "providedFireRatingMin" in e
    ]
    if not rows:
        raise FeatureInputError(
            "Record required and provided fire ratings on elements before auditing."
        )
    failed = sum(float(r["providedMinutes"] or 0) < float(r["requiredMinutes"] or 0) for r in rows)
    return result(
        summary={"ratedElementCount": len(rows), "failedCount": failed},
        tables=[
            table(
                "Fire Ratings",
                [
                    ("id", "Element"),
                    ("requiredMinutes", "Required", "min"),
                    ("providedMinutes", "Provided", "min"),
                ],
                rows,
            )
        ],
    )


@feature(
    "bimSummaryCompliance.smokeZoneCheck",
    "Smoke Zone Check",
    part="bim",
    fields=[number("maxAreaM2", "Maximum smoke reservoir area", 2000.0, unit="m²", min=1)],
)
def smoke_zone_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check recorded smoke reservoir areas against the maximum."""
    data = require_bim(ctx)
    zones = _records(data, "smokeZones", "smoke reservoir zones", ("id", "areaM2"))
    rows = [
        {"id": z.get("id", ""), "areaM2": float(z.get("areaM2", 0.0))}
        for z in zones
        if isinstance(z, dict)
    ]
    failed = sum(r["areaM2"] > values["maxAreaM2"] for r in rows)
    return result(
        summary={"zoneCount": len(rows), "failedCount": failed},
        tables=[table("Smoke Zones", [("id", "Zone"), ("areaM2", "Area", "m²")], rows)],
    )


@feature(
    "bimSummaryCompliance.driftRatioAudit",
    "Drift Ratio Audit",
    part="bim",
    fields=[number("maxDriftRatio", "Maximum inter-storey drift ratio", 0.02, unit="ratio", min=0)],
)
def drift_ratio_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify recorded inter-storey drift ratios."""
    data = require_bim(ctx)
    rows = _records(data, "driftRatios", "inter-storey drift ratios", ("ratio",))
    failed = sum(
        float(r.get("ratio", 0.0)) > values["maxDriftRatio"] for r in rows if isinstance(r, dict)
    )
    return result(
        summary={"storeyCount": len(rows), "failedCount": failed},
        tables=[table("Drift Ratios", [("storey", "Storey"), ("ratio", "Drift ratio")], rows)],
    )


@feature(
    "bimSummaryCompliance.minimumThickness",
    "Minimum Thickness",
    part="bim",
    fields=[
        number("minSlabMm", "Minimum slab thickness", 100.0, unit="mm", min=1),
        number("minWallMm", "Minimum wall thickness", 150.0, unit="mm", min=1),
    ],
)
def minimum_thickness(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check slab and wall thicknesses against configured minimums."""
    data = require_bim(ctx)
    rows = []
    for e in data["elements"]:
        if isinstance(e, dict) and e.get("kind") == "slab" and "thicknessMm" in e:
            t = float(e["thicknessMm"])
            if t < values["minSlabMm"]:
                rows.append({"id": e.get("id", ""), "kind": "slab", "thicknessMm": t})
        if isinstance(e, dict) and e.get("kind") == "wall" and "thicknessMm" in e:
            t = float(e["thicknessMm"])
            if t < values["minWallMm"]:
                rows.append({"id": e.get("id", ""), "kind": "wall", "thicknessMm": t})
    if not rows and not any(
        isinstance(e, dict) and e.get("kind") in ("slab", "wall") and "thicknessMm" in e
        for e in data["elements"]
    ):
        raise FeatureInputError(
            "Record slab or wall thicknesses before checking minimum thickness."
        )
    return result(
        summary={"failedElementCount": len(rows)},
        tables=[
            table(
                "Minimum Thickness",
                [("id", "Element"), ("kind", "Kind"), ("thicknessMm", "Thickness", "mm")],
                rows,
            )
        ],
    )


@feature("bimSummaryCompliance.clearSpanAudit", "Clear Span Audit", part="bim")
def clear_span_audit(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check recorded unbraced beam lengths and audit flags."""
    data = require_bim(ctx)
    rows = [
        {
            "id": e.get("id", ""),
            "clearSpanMm": float(e["clearSpanMm"]),
            "auditStatus": e["clearSpanStatus"],
        }
        for e in data["elements"]
        if isinstance(e, dict)
        and e.get("kind") == "beam"
        and "clearSpanMm" in e
        and "clearSpanStatus" in e
    ]
    if not rows:
        raise FeatureInputError("Record clear spans and audit statuses for beams before checking.")
    failed = sum(str(r["auditStatus"]).lower() not in ("pass", "compliant") for r in rows)
    return result(
        summary={"beamCount": len(rows), "failedCount": failed},
        tables=[
            table(
                "Clear Span Audit",
                [("id", "Beam"), ("clearSpanMm", "Clear span", "mm"), ("auditStatus", "Status")],
                rows,
            )
        ],
    )


@feature(
    "bimSummaryCompliance.daylightFactor",
    "Daylight Factor",
    part="bim",
    fields=[number("requiredFactorPercent", "Minimum daylight factor", 2.0, unit="%", min=0)],
)
def daylight_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate daylight availability from recorded room daylight factors."""
    data = require_bim(ctx)
    rooms = _records(data, "rooms", "room daylight factors", ("id", "daylightFactorPercent"))
    rows = [
        {"id": r.get("id", ""), "factorPercent": float(r.get("daylightFactorPercent", 0.0))}
        for r in rooms
        if isinstance(r, dict)
    ]
    failed = sum(r["factorPercent"] < values["requiredFactorPercent"] for r in rows)
    return result(
        summary={"roomCount": len(rows), "failedCount": failed},
        tables=[
            table(
                "Daylight Factors",
                [("id", "Room"), ("factorPercent", "Daylight factor", "%")],
                rows,
            )
        ],
    )


@feature(
    "bimSummaryCompliance.ventilationArea",
    "Ventilation Area",
    part="bim",
    fields=[number("requiredRatioPercent", "Minimum operable window ratio", 5.0, unit="%", min=0)],
)
def ventilation_area(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check operable window open-area ratios against floor area."""
    data = require_bim(ctx)
    rooms = _records(
        data, "rooms", "room operable-window ratios", ("id", "operableWindowRatioPercent")
    )
    rows = [
        {"id": r.get("id", ""), "ratioPercent": float(r.get("operableWindowRatioPercent", 0.0))}
        for r in rooms
        if isinstance(r, dict)
    ]
    failed = sum(r["ratioPercent"] < values["requiredRatioPercent"] for r in rows)
    return result(
        summary={"roomCount": len(rows), "failedCount": failed},
        tables=[
            table(
                "Ventilation Area", [("id", "Room"), ("ratioPercent", "Operable ratio", "%")], rows
            )
        ],
    )


@feature(
    "bimSummaryCompliance.acousticInsulation",
    "Acoustic Insulation",
    part="bim",
    fields=[number("requiredStc", "Minimum sound transmission rating", 50.0, unit="STC", min=0)],
)
def acoustic_insulation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Audit recorded sound transmission class ratings of partitions."""
    data = require_bim(ctx)
    walls = [
        e
        for e in data["elements"]
        if isinstance(e, dict)
        and e.get("kind") == "wall"
        and isinstance(e.get("stc"), (int, float))
    ]
    if not walls:
        raise FeatureInputError("Record sound transmission ratings on walls before auditing.")
    rows = [{"id": e.get("id", ""), "stc": float(e["stc"])} for e in walls]
    failed = sum(r["stc"] < values["requiredStc"] for r in rows)
    return result(
        summary={"partitionCount": len(rows), "failedCount": failed},
        tables=[table("Acoustic Insulation", [("id", "Partition"), ("stc", "STC")], rows)],
    )
