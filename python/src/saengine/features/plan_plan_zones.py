"""Zones & Areas ribbon: slab load areas, tributary distribution and zone schedules."""

from __future__ import annotations

import json
import math

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
from saengine.features.plan_common import export_csv, plan_data, profile


def _slabs(ctx: FeatureContext, story: str | None = None) -> list[dict]:
    rows = [r for r in profile(ctx)[1] if r["category"] == "slab"]
    if story:
        rows = [r for r in rows if r["story"] == story]
    return rows


def _polygon(raw: str) -> list[tuple[float, float]]:
    pts = []
    try:
        for item in raw.split(";"):
            if item.strip():
                x, y = [float(v.strip()) for v in item.split(",")[:2]]
                pts.append((x, y))
    except ValueError as exc:
        raise FeatureInputError(
            "Zone vertices must be x,y coordinates in millimetres separated by semicolons."
        ) from exc
    if len(pts) < 3:
        raise FeatureInputError("A zone boundary needs at least three points.")
    return pts


def _poly_area(pts: list[tuple[float, float]]) -> float:
    return (
        abs(
            sum(
                pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                for i in range(len(pts))
            )
        )
        / 2e6
    )


@feature(
    "planPlanZones.createZone",
    "Create Zone",
    part="floorPlan",
    fields=[
        text("name", "Zone name", "Office area"),
        text("storey", "Storey id", "L1"),
        text("boundaryMm", "Boundary x,y mm", "0,0;6000,0;6000,5000;0,5000"),
    ],
)
def create_zone(ctx: FeatureContext, values: dict) -> dict:
    """Calculate polygon area and validate a proposed plan load-zone boundary."""
    plan = plan_data(ctx)
    pts = _polygon(values["boundaryMm"])
    if values["storey"] not in {s["id"] for s in plan["stories"]}:
        raise FeatureInputError("Storey id was not found.")
    return result(
        summary={
            "zoneName": values["name"],
            "storey": values["storey"],
            "areaM2": _poly_area(pts),
            "boundaryVertices": len(pts),
        }
    )


@feature(
    "planPlanZones.assignMembers",
    "Assign Members",
    part="floorPlan",
    fields=[text("zoneName", "Zone name", "Office area"), text("slabIds", "Slab ids", "S1,S2")],
)
def assign_members(ctx: FeatureContext, values: dict) -> dict:
    """Assign slab panels to an explicit zone and total their polygon areas."""
    slabs = _slabs(ctx)
    ids = {x.strip() for x in values["slabIds"].split(",") if x.strip()}
    unknown = ids - {s["id"] for s in slabs}
    if unknown:
        raise FeatureInputError(f"Unknown slab id(s): {', '.join(sorted(unknown))}.")
    chosen = [s for s in slabs if s["id"] in ids]
    return result(
        summary={
            "zoneName": values["zoneName"],
            "assignedSlabs": len(chosen),
            "totalAreaM2": sum(s["areaM2"] for s in chosen),
        },
        tables=[
            table(
                "Zone slab members",
                [("id", "Slab"), ("story", "Storey"), ("areaM2", "Area", "m²")],
                chosen,
            )
        ],
    )


@feature(
    "planPlanZones.zoneBoundary",
    "Zone Boundary",
    part="floorPlan",
    fields=[
        text("zoneName", "Zone name", "Office area"),
        text("verticesMm", "Zone vertices x,y mm", "0,0;6000,0;6000,5000;0,5000"),
    ],
    requires_project=False,
)
def zone_boundary(ctx: FeatureContext, values: dict) -> dict:
    """Measure a polygonal zone boundary, perimeter and polygon centroid."""
    pts = _polygon(values["verticesMm"])
    twice_signed_area = sum(
        pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
        for i in range(len(pts))
    )
    if abs(twice_signed_area) <= 1e-9:
        raise FeatureInputError("Zone boundary has zero area; enter a non-degenerate polygon.")
    cx = sum(
        (pts[i][0] + pts[(i + 1) % len(pts)][0])
        * (pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1])
        for i in range(len(pts))
    ) / (3 * twice_signed_area)
    cy = sum(
        (pts[i][1] + pts[(i + 1) % len(pts)][1])
        * (pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1])
        for i in range(len(pts))
    ) / (3 * twice_signed_area)
    perimeter = (
        sum(
            math.hypot(
                pts[(i + 1) % len(pts)][0] - pts[i][0], pts[(i + 1) % len(pts)][1] - pts[i][1]
            )
            for i in range(len(pts))
        )
        / 1000
    )
    return result(
        summary={
            "zoneName": values["zoneName"],
            "areaM2": abs(twice_signed_area) / 2e6,
            "perimeterM": perimeter,
            "centroidXMm": cx,
            "centroidYMm": cy,
        }
    )


@feature(
    "planPlanZones.zoneColour",
    "Zone Colour",
    part="floorPlan",
    fields=[
        text("zoneName", "Zone name", "Office area"),
        text("colourHex", "Fill colour", "#4E79A7"),
    ],
    requires_project=False,
)
def zone_colour(ctx: FeatureContext, values: dict) -> dict:
    """Validate a zone fill color for plan display."""
    color = values["colourHex"]
    if (
        len(color) != 7
        or not color.startswith("#")
        or any(c not in "0123456789abcdefABCDEF" for c in color[1:])
    ):
        raise FeatureInputError("Enter a six-digit hexadecimal colour.")
    return result(summary={"zoneName": values["zoneName"], "colourHex": color.upper()})


@feature(
    "planPlanZones.tributaryArea",
    "Tributary Area",
    part="floorPlan",
    fields=[
        text("slabIds", "Slab ids", "S1,S2"),
        select(
            "distribution",
            "Load distribution",
            [("oneWayX", "One-way X"), ("oneWayY", "One-way Y"), ("twoWay", "Two-way 45 degree")],
        ),
    ],
)
def tributary_area(ctx: FeatureContext, values: dict) -> dict:
    """Calculate slab panel tributary area and allocate it by the selected support direction."""
    slabs = _slabs(ctx)
    ids = {x.strip() for x in values["slabIds"].split(",") if x.strip()}
    unknown = ids - {s["id"] for s in slabs}
    if unknown:
        raise FeatureInputError(f"Unknown slab id(s): {', '.join(sorted(unknown))}.")
    chosen = [s for s in slabs if s["id"] in ids]
    total = sum(s["areaM2"] for s in chosen)
    return result(
        summary={
            "panelCount": len(chosen),
            "tributaryAreaM2": total,
            "distribution": values["distribution"],
            "areaPerSupportSideM2": total / (4 if values["distribution"] == "twoWay" else 2)
            if chosen
            else 0,
        },
        notes=[
            "The two-way four-side allocation is an area screening approximation; panel dimensions and edge support conditions affect actual load distribution."
        ],
    )


@feature(
    "planPlanZones.loadTakeDown",
    "Load Take Down",
    part="floorPlan",
    fields=[
        text("slabIds", "Slab ids", "S1,S2"),
        number("deadLoadKpa", "Dead pressure", 2, unit="kPa", min=0),
        number("liveLoadKpa", "Live pressure", 3, unit="kPa", min=0),
        number("partitionLoadKpa", "Partition pressure", 1, unit="kPa", min=0),
    ],
)
def load_take_down(ctx: FeatureContext, values: dict) -> dict:
    """Sum engineer-entered dead, live and partition pressures over selected slab panels."""
    slabs = _slabs(ctx)
    ids = {x.strip() for x in values["slabIds"].split(",") if x.strip()}
    unknown = ids - {s["id"] for s in slabs}
    if unknown:
        raise FeatureInputError(f"Unknown slab id(s): {', '.join(sorted(unknown))}.")
    chosen = [s for s in slabs if s["id"] in ids]
    area = sum(s["areaM2"] for s in chosen)
    components = {
        "dead": values["deadLoadKpa"] * area,
        "live": values["liveLoadKpa"] * area,
        "partition": values["partitionLoadKpa"] * area,
    }
    return result(
        summary={
            "loadedAreaM2": area,
            "deadLoadKn": components["dead"],
            "liveLoadKn": components["live"],
            "partitionLoadKn": components["partition"],
            "totalLoadKn": sum(components.values()),
        },
        tables=[
            table(
                "Area load take-down",
                [
                    ("case", "Load component"),
                    ("intensityKpa", "Intensity", "kPa"),
                    ("areaM2", "Area", "m²"),
                    ("resultantKn", "Resultant", "kN"),
                ],
                [
                    {
                        "case": "dead",
                        "intensityKpa": values["deadLoadKpa"],
                        "areaM2": area,
                        "resultantKn": components["dead"],
                    },
                    {
                        "case": "live",
                        "intensityKpa": values["liveLoadKpa"],
                        "areaM2": area,
                        "resultantKn": components["live"],
                    },
                    {
                        "case": "partition",
                        "intensityKpa": values["partitionLoadKpa"],
                        "areaM2": area,
                        "resultantKn": components["partition"],
                    },
                ],
            )
        ],
    )


@feature(
    "planPlanZones.influenceArea",
    "Influence Area",
    part="floorPlan",
    fields=[
        text("memberId", "Supporting beam id", "B1"),
        number("tributaryWidthM", "Tributary width", 3, unit="m", min=0),
        number("adjacentSpanM", "Adjacent span", 6, unit="m", min=0),
    ],
)
def influence_area(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the floor influence area and equivalent line load on a selected supporting beam."""
    rows = profile(ctx)[1]
    beam = next(
        (r for r in rows if r["id"] == values["memberId"] and r["category"] == "beam"), None
    )
    if beam is None:
        raise FeatureInputError("Choose an existing supporting beam.")
    area = values["tributaryWidthM"] * beam["lengthM"]
    return result(
        summary={
            "beamId": beam["id"],
            "beamLengthM": beam["lengthM"],
            "influenceAreaM2": area,
            "adjacentSpanM": values["adjacentSpanM"],
            "halfAdjacentSpanAreaM2": area / 2,
        }
    )


@feature(
    "planPlanZones.previewLoads",
    "Preview Loads",
    part="floorPlan",
    fields=[
        text("slabIds", "Slab ids", "S1,S2"),
        number("intensityKpa", "Preview pressure", 3, unit="kPa", min=0),
        select(
            "case",
            "Load case",
            [("D", "Dead"), ("SD", "Superimposed dead"), ("L", "Live"), ("Lr", "Roof live")],
        ),
    ],
)
def preview_loads(ctx: FeatureContext, values: dict) -> dict:
    """Preview total applied pressure resultant on each selected slab panel."""
    slabs = _slabs(ctx)
    ids = {x.strip() for x in values["slabIds"].split(",") if x.strip()}
    unknown = ids - {s["id"] for s in slabs}
    if unknown:
        raise FeatureInputError(f"Unknown slab id(s): {', '.join(sorted(unknown))}.")
    out = [
        {
            "slabId": s["id"],
            "storey": s["story"],
            "areaM2": s["areaM2"],
            "case": values["case"],
            "resultantKn": s["areaM2"] * values["intensityKpa"],
        }
        for s in slabs
        if s["id"] in ids
    ]
    return result(
        summary={"previewPanels": len(out), "totalLoadKn": sum(r["resultantKn"] for r in out)},
        tables=[
            table(
                "Slab load preview",
                [
                    ("slabId", "Slab"),
                    ("storey", "Storey"),
                    ("areaM2", "Area", "m²"),
                    ("case", "Case"),
                    ("resultantKn", "Resultant", "kN"),
                ],
                out,
            )
        ],
    )


@feature(
    "planPlanZones.areaSchedule",
    "Area Schedule",
    part="floorPlan",
    fields=[text("storey", "Storey id (blank for all)", "")],
)
def area_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Schedule each slab panel's plan area and its storey subtotal."""
    slabs = _slabs(ctx, values["storey"] or None)
    totals = {}
    for slab in slabs:
        totals[slab["story"]] = totals.get(slab["story"], 0) + slab["areaM2"]
    return result(
        summary={
            "slabCount": len(slabs),
            "totalAreaM2": sum(totals.values()),
            "storeys": len(totals),
        },
        tables=[
            table(
                "Slab area schedule",
                [
                    ("id", "Slab"),
                    ("storey", "Storey"),
                    ("type", "Type"),
                    ("areaM2", "Area", "m²"),
                    ("perimeterM", "Perimeter", "m"),
                ],
                slabs,
            ),
            table(
                "Area by storey",
                [("storey", "Storey"), ("areaM2", "Area", "m²")],
                [{"storey": k, "areaM2": v} for k, v in sorted(totals.items())],
            ),
        ],
    )


@feature(
    "planPlanZones.loadSummary",
    "Load Summary",
    part="floorPlan",
    fields=[
        number("deadKpa", "Dead pressure", 2, unit="kPa", min=0),
        number("liveKpa", "Live pressure", 3, unit="kPa", min=0),
        number("partitionKpa", "Partition pressure", 1, unit="kPa", min=0),
    ],
)
def load_summary(ctx: FeatureContext, values: dict) -> dict:
    """Summarise total floor-zone dead, live and partition loads across modelled slab area."""
    slabs = _slabs(ctx)
    out = []
    for story in sorted({s["story"] for s in slabs}):
        area = sum(s["areaM2"] for s in slabs if s["story"] == story)
        for name, q in (
            ("dead", values["deadKpa"]),
            ("live", values["liveKpa"]),
            ("partition", values["partitionKpa"]),
        ):
            out.append(
                {
                    "storey": story,
                    "case": name,
                    "areaM2": area,
                    "intensityKpa": q,
                    "resultantKn": area * q,
                }
            )
    return result(
        summary={"loadRows": len(out), "totalGravityKn": sum(r["resultantKn"] for r in out)},
        tables=[
            table(
                "Zone load summary",
                [
                    ("storey", "Storey"),
                    ("case", "Case"),
                    ("areaM2", "Area", "m²"),
                    ("intensityKpa", "Intensity", "kPa"),
                    ("resultantKn", "Resultant", "kN"),
                ],
                out,
            )
        ],
    )


@feature(
    "planPlanZones.compareZones",
    "Compare Zones",
    part="floorPlan",
    fields=[
        text(
            "zonesJson",
            "Zone records JSON",
            '[{"name":"A","areaM2":100,"liveKpa":3},{"name":"B","areaM2":80,"liveKpa":4}]',
        )
    ],
)
def compare_zones(ctx: FeatureContext, values: dict) -> dict:
    """Compare entered zone areas, pressures and resultant live loads."""
    try:
        zones = json.loads(values["zonesJson"])
    except ValueError as exc:
        raise FeatureInputError("Zone comparison input must be valid JSON.") from exc
    if not isinstance(zones, list):
        raise FeatureInputError("Zone comparison must be a JSON array.")
    out = []
    for z in zones:
        area, load = float(z.get("areaM2", 0)), float(z.get("liveKpa", 0))
        out.append(
            {
                "name": z.get("name", ""),
                "areaM2": area,
                "liveKpa": load,
                "liveResultantKn": area * load,
            }
        )
    return result(
        summary={
            "zones": len(out),
            "areaDifferenceM2": max((r["areaM2"] for r in out), default=0)
            - min((r["areaM2"] for r in out), default=0),
        },
        tables=[
            table(
                "Zone load comparison",
                [
                    ("name", "Zone"),
                    ("areaM2", "Area", "m²"),
                    ("liveKpa", "Live pressure", "kPa"),
                    ("liveResultantKn", "Live resultant", "kN"),
                ],
                out,
            )
        ],
    )


@feature(
    "planPlanZones.exportZones",
    "Export Zones",
    part="floorPlan",
    fields=[text("filename", "CSV filename", "floor-zones.csv")],
)
def export_zones(ctx: FeatureContext, values: dict) -> dict:
    """Write current slab panels and calculated polygon areas as a zone-area CSV."""
    slabs = _slabs(ctx)
    name = values["filename"].strip()
    if not name.lower().endswith(".csv") or "/" in name or "\\" in name:
        raise FeatureInputError("Use a simple .csv filename without folders.")
    path = export_csv(ctx, name, ["id", "story", "type", "areaM2", "perimeterM"], slabs)
    return result(
        summary={"exportedSlabs": len(slabs), "file": path},
        notes=[f"Wrote slab area zones to {path}."],
    )


@feature(
    "planPlanZones.occupancyType",
    "Occupancy Type",
    part="floorPlan",
    fields=[
        text("zoneName", "Zone name", "Office area"),
        select(
            "occupancy",
            "Occupancy type",
            [
                ("residential", "Residential"),
                ("office", "Office"),
                ("assembly", "Assembly"),
                ("storage", "Storage"),
                ("parking", "Parking"),
                ("custom", "Custom"),
            ],
        ),
        number("userLiveLoadKpa", "User-entered live load", 3, unit="kPa", min=0),
    ],
)
def occupancy_type(ctx: FeatureContext, values: dict) -> dict:
    """Record a zone use and its engineer-entered live pressure without substituting code-table loads."""
    return result(
        summary={
            "zoneName": values["zoneName"],
            "occupancy": values["occupancy"],
            "liveLoadKpa": values["userLiveLoadKpa"],
        },
        notes=[
            "Occupancy classification is descriptive; live load remains the explicit engineer input."
        ],
    )


@feature(
    "planPlanZones.areaLiveLoad",
    "Area Live Load",
    part="floorPlan",
    fields=[
        text("slabIds", "Slab ids", "S1,S2"),
        number("liveLoadKpa", "Uniform live pressure", 3, unit="kPa", min=0),
        number("reductionFactor", "Applied tributary reduction factor", 1, min=0, max=1),
    ],
)
def area_live_load(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the live-load resultant over selected slabs using explicit pressure and reduction factor."""
    slabs = _slabs(ctx)
    ids = {x.strip() for x in values["slabIds"].split(",") if x.strip()}
    chosen = [s for s in slabs if s["id"] in ids]
    if ids - {s["id"] for s in slabs}:
        raise FeatureInputError("One or more slab ids do not exist.")
    area = sum(s["areaM2"] for s in chosen)
    effective = values["liveLoadKpa"] * values["reductionFactor"]
    return result(
        summary={
            "loadedSlabAreaM2": area,
            "enteredLiveLoadKpa": values["liveLoadKpa"],
            "effectiveLiveLoadKpa": effective,
            "totalLiveLoadKn": area * effective,
        }
    )


@feature(
    "planPlanZones.partitionLoad",
    "Partition Load",
    part="floorPlan",
    fields=[
        text("slabIds", "Slab ids", "S1,S2"),
        number("partitionLoadKpa", "Partition allowance", 1, unit="kPa", min=0),
        number("wallLineLoadKnPerM", "Known wall line load", 0, unit="kN/m", min=0),
        number("wallLengthM", "Wall length on floor", 0, unit="m", min=0),
    ],
)
def partition_load(ctx: FeatureContext, values: dict) -> dict:
    """Combine an area partition allowance with an explicit wall line load over selected panels."""
    slabs = _slabs(ctx)
    ids = {x.strip() for x in values["slabIds"].split(",") if x.strip()}
    chosen = [s for s in slabs if s["id"] in ids]
    if ids - {s["id"] for s in slabs}:
        raise FeatureInputError("One or more slab ids do not exist.")
    area = sum(s["areaM2"] for s in chosen)
    distributed = area * values["partitionLoadKpa"]
    wall = values["wallLengthM"] * values["wallLineLoadKnPerM"]
    return result(
        summary={
            "slabAreaM2": area,
            "areaPartitionLoadKn": distributed,
            "wallLoadKn": wall,
            "combinedPartitionLoadKn": distributed + wall,
        }
    )


@feature(
    "planPlanZones.oneWayDistribution",
    "One Way Distribution",
    part="floorPlan",
    fields=[
        number("panelShortSpanM", "Panel short span", 4, unit="m", min=0.1),
        number("panelLongSpanM", "Panel long span", 6, unit="m", min=0.1),
        number("areaLoadKpa", "Area load", 3, unit="kPa", min=0),
        select(
            "direction",
            "Span direction",
            [("short", "Short direction"), ("long", "Long direction")],
        ),
    ],
    requires_project=False,
)
def one_way_distribution(ctx: FeatureContext, values: dict) -> dict:
    """Convert one-way panel pressure into uniform edge line loads along the span direction."""
    span = values["panelShortSpanM"] if values["direction"] == "short" else values["panelLongSpanM"]
    transverse = (
        values["panelLongSpanM"] if values["direction"] == "short" else values["panelShortSpanM"]
    )
    line = values["areaLoadKpa"] * transverse / 2
    return result(
        summary={
            "spanDirection": values["direction"],
            "spanM": span,
            "tributaryWidthM": transverse / 2,
            "lineLoadKnPerMPerSupport": line,
            "totalPanelLoadKn": values["areaLoadKpa"] * span * transverse,
        }
    )


@feature(
    "planPlanZones.twoWayDistribution",
    "Two Way Distribution",
    part="floorPlan",
    fields=[
        number("shortSpanM", "Short span", 4, unit="m", min=0.1),
        number("longSpanM", "Long span", 6, unit="m", min=0.1),
        number("areaLoadKpa", "Area load", 3, unit="kPa", min=0),
    ],
)
def two_way_distribution(ctx: FeatureContext, values: dict) -> dict:
    """Partition rectangular slab load to four edges with 45-degree tributary boundaries."""
    lx, ly = sorted((values["shortSpanM"], values["longSpanM"]))
    q = values["areaLoadKpa"]
    if ly < lx:
        raise FeatureInputError("Long span must be at least the short span.")
    short_edge_area = lx**2 / 4
    long_edge_area = (lx * ly / 2) - lx**2 / 4
    rows = [
        {"edge": "short edge 1", "tributaryAreaM2": short_edge_area, "loadKn": q * short_edge_area},
        {"edge": "short edge 2", "tributaryAreaM2": short_edge_area, "loadKn": q * short_edge_area},
        {"edge": "long edge 1", "tributaryAreaM2": long_edge_area, "loadKn": q * long_edge_area},
        {"edge": "long edge 2", "tributaryAreaM2": long_edge_area, "loadKn": q * long_edge_area},
    ]
    return result(
        summary={
            "panelAreaM2": lx * ly,
            "distributedAreaM2": sum(r["tributaryAreaM2"] for r in rows),
            "totalLoadKn": sum(r["loadKn"] for r in rows),
        },
        tables=[
            table(
                "45-degree two-way tributary areas",
                [
                    ("edge", "Supporting edge"),
                    ("tributaryAreaM2", "Area", "m²"),
                    ("loadKn", "Load", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Ideal rectangular panel with four supported edges and 45-degree tributary boundaries; openings and unequal edge stiffness are omitted."
        ],
    )


@feature(
    "planPlanZones.lineLoadTransfer",
    "Line Load Transfer",
    part="floorPlan",
    fields=[
        text("wallId", "Wall id", "W1"),
        number("wallUnitWeightKnPerM3", "Wall unit weight", 18, unit="kN/m³", min=0),
        number("wallThicknessMm", "Wall thickness", 200, unit="mm", min=1),
        number("wallHeightM", "Wall height", 3, unit="m", min=0),
        number("beamTributaryWidthM", "Beam tributary width", 3, unit="m", min=0),
    ],
)
def line_load_transfer(ctx: FeatureContext, values: dict) -> dict:
    """Calculate wall line load and convert it to an area-equivalent pressure over a beam tributary width."""
    plan = plan_data(ctx)
    wall = next((m for m in plan["walls"] if m["id"] == values["wallId"]), None)
    if wall is None:
        raise FeatureInputError("Choose an existing wall id.")
    line = (
        values["wallUnitWeightKnPerM3"] * values["wallThicknessMm"] / 1000 * values["wallHeightM"]
    )
    return result(
        summary={
            "wallId": wall["id"],
            "wallLineLoadKnPerM": line,
            "equivalentAreaLoadKpa": line / values["beamTributaryWidthM"]
            if values["beamTributaryWidthM"]
            else None,
            "beamTributaryWidthM": values["beamTributaryWidthM"],
        }
    )


@feature(
    "planPlanZones.zoneEdgeOffset",
    "Zone Edge Offset",
    part="floorPlan",
    fields=[
        text("boundaryMm", "Boundary x,y mm", "0,0;6000,0;6000,5000;0,5000"),
        number("insetMm", "Inset from boundary", 100, unit="mm", min=0),
    ],
    requires_project=False,
)
def zone_edge_offset(ctx: FeatureContext, values: dict) -> dict:
    """Compute an inward rectangular zone inset and remaining area."""
    pts = _polygon(values["boundaryMm"])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    width = max(xs) - min(xs)
    depth = max(ys) - min(ys)
    if width <= 2 * values["insetMm"] or depth <= 2 * values["insetMm"]:
        raise FeatureInputError("Inset consumes the entire zone width or depth.")
    original = width * depth / 1e6
    remaining = (width - 2 * values["insetMm"]) * (depth - 2 * values["insetMm"]) / 1e6
    return result(
        summary={
            "originalEnvelopeAreaM2": original,
            "insetAreaM2": remaining,
            "excludedEdgeAreaM2": original - remaining,
            "insetMm": values["insetMm"],
        },
        notes=[
            "Inset area uses the polygon's axis-aligned rectangular envelope; angled boundaries need a polygon offset operation."
        ],
    )


@feature(
    "planPlanZones.excludeArea",
    "Exclude Area",
    part="floorPlan",
    fields=[
        text("slabId", "Slab id", "S1"),
        number("excludedAreaM2", "Excluded void area", 2, unit="m²", min=0),
        number("areaLoadKpa", "Area load", 3, unit="kPa", min=0),
    ],
)
def exclude_area(ctx: FeatureContext, values: dict) -> dict:
    """Subtract a void area from a slab panel's load area and resultant."""
    _, rows = profile(ctx)
    slab = next((r for r in rows if r["id"] == values["slabId"] and r["category"] == "slab"), None)
    if slab is None:
        raise FeatureInputError("Choose an existing slab id.")
    if values["excludedAreaM2"] > slab["areaM2"]:
        raise FeatureInputError("Excluded area exceeds the slab panel.")
    net = slab["areaM2"] - values["excludedAreaM2"]
    return result(
        summary={
            "grossAreaM2": slab["areaM2"],
            "excludedAreaM2": values["excludedAreaM2"],
            "netLoadedAreaM2": net,
            "netLoadKn": net * values["areaLoadKpa"],
        }
    )


@feature(
    "planPlanZones.zoneReCalculate",
    "Zone Re-calculate",
    part="floorPlan",
    fields=[
        number("areaToleranceM2", "Area change tolerance", 0.01, unit="m²", min=0),
        text("storey", "Storey id filter (blank for all)", ""),
    ],
)
def zone_recalculate(ctx: FeatureContext, values: dict) -> dict:
    """Recalculate each slab's area and identify panels changed beyond the entered tolerance."""
    slabs = _slabs(ctx, values["storey"] or None)
    plan = plan_data(ctx)
    raw = {s["id"]: s for s in plan["slabs"]}
    out = []
    for slab in slabs:
        geometry = raw[slab["id"]]
        coords = []
        from saengine.features.plan_common import point_xy

        for p in geometry["boundary"]:
            coords.append(point_xy(plan, p))
        area = (
            abs(
                sum(
                    coords[i][0] * coords[(i + 1) % len(coords)][1]
                    - coords[(i + 1) % len(coords)][0] * coords[i][1]
                    for i in range(len(coords))
                )
            )
            / 2e6
        )
        difference = area - slab["areaM2"]
        out.append(
            {
                "slabId": slab["id"],
                "storedAreaM2": slab["areaM2"],
                "recalculatedAreaM2": area,
                "differenceM2": difference,
                "changed": abs(difference) > values["areaToleranceM2"],
            }
        )
    return result(
        summary={"recalculatedSlabs": len(out), "changedAreas": sum(r["changed"] for r in out)},
        tables=[
            table(
                "Slab zone recalculation",
                [
                    ("slabId", "Slab"),
                    ("storedAreaM2", "Stored", "m²"),
                    ("recalculatedAreaM2", "Recalculated", "m²"),
                    ("differenceM2", "Difference", "m²"),
                    ("changed", "Changed"),
                ],
                out,
            )
        ],
    )
