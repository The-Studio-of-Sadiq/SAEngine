"""Loads ribbon: member, slab, equipment and environmental gravity loads."""

from __future__ import annotations

import math

from saengine.features import FeatureContext, checkbox, feature, number, result, select, table, text
from saengine.features.plan_common import (
    loads_data,
    member_rows,
    plan_data,
    profile,
    story_map,
)

_CASES = [("D", "Dead"), ("SD", "Superimposed dead"), ("L", "Live"), ("Lr", "Roof live")]


@feature(
    "planLoads.slabLoad",
    "Slab Load",
    part="floorPlan",
    fields=[
        text("slabId", "Slab id", "S1"),
        number("intensityKpa", "Area load", 2.0, unit="kPa", min=0),
        select("case", "Load case", _CASES, "L"),
    ],
    requires_project=False,
)
def slab_load(ctx: FeatureContext, values: dict) -> dict:
    """Convert a uniform slab pressure to panel load using the modelled slab area."""
    plan = plan_data(ctx)
    rows = [r for r in member_rows(plan) if r["category"] == "slab"]
    slab = next((r for r in rows if r["id"] == values["slabId"]), None)
    if slab is None:
        raise ValueError("Choose an existing slab id.")
    return result(
        summary={
            "slabId": slab["id"],
            "areaM2": slab["areaM2"],
            "intensityKpa": values["intensityKpa"],
            "resultantKn": slab["areaM2"] * values["intensityKpa"],
            "case": values["case"],
        },
        notes=[
            "Uniform vertical pressure; total force is intensity multiplied by the floor-plan polygon area."
        ],
    )


@feature(
    "planLoads.beamLoad",
    "Beam Load",
    part="floorPlan",
    fields=[
        text("beamId", "Beam id", "B1"),
        select(
            "shape",
            "Load shape",
            [("point", "Point"), ("uniform", "Uniform"), ("trapezoid", "Trapezoidal")],
        ),
        number("startKnPerM", "Start intensity", 5, unit="kN/m", min=0),
        number("endKnPerM", "End intensity", 5, unit="kN/m", min=0),
        number("pointKn", "Point load", 10, unit="kN", min=0),
        number("positionRatio", "Point position from start", 0.5, min=0, max=1),
    ],
)
def beam_load(ctx: FeatureContext, values: dict) -> dict:
    """Resolve beam-load resultant and centroid for point, uniform or trapezoidal loading."""
    _, rows = profile(ctx)
    beam = next((r for r in rows if r["id"] == values["beamId"] and r["category"] == "beam"), None)
    if beam is None:
        raise ValueError("Choose an existing beam id.")
    length = beam["lengthM"]
    if values["shape"] == "point":
        force, centroid = values["pointKn"], values["positionRatio"] * length
    else:
        w0, w1 = (
            values["startKnPerM"],
            values["endKnPerM"] if values["shape"] == "trapezoid" else values["startKnPerM"],
        )
        force = (w0 + w1) * length / 2
        centroid = length * (w0 + 2 * w1) / (3 * (w0 + w1)) if w0 + w1 else length / 2
    return result(
        summary={
            "beamId": beam["id"],
            "spanM": length,
            "resultantKn": force,
            "centroidFromStartM": centroid,
            "shape": values["shape"],
        },
        notes=["Load resultant and centroid are for the entered positive downward load only."],
    )


@feature(
    "planLoads.pointLoad",
    "Point Load",
    part="floorPlan",
    fields=[
        text("node", "Grid point", "A-1"),
        number("verticalKn", "Vertical force", 10, unit="kN"),
        number("horizontalKn", "Horizontal force", 0, unit="kN"),
        number("momentKnM", "Plan moment", 0, unit="kN·m"),
        select("case", "Load case", _CASES, "D"),
    ],
    requires_project=False,
)
def point_load(ctx: FeatureContext, values: dict) -> dict:
    """Describe a nodal force and moment vector with its resultant magnitude."""
    force = math.hypot(values["verticalKn"], values["horizontalKn"])
    return result(
        summary={
            "node": values["node"],
            "forceResultantKn": force,
            "forceAngleDeg": math.degrees(math.atan2(values["verticalKn"], values["horizontalKn"])),
            "momentKnM": values["momentKnM"],
            "case": values["case"],
        }
    )


@feature(
    "planLoads.wallLoad",
    "Wall Load",
    part="floorPlan",
    fields=[
        number("unitWeightKnPerM3", "Wall unit weight", 18, unit="kN/m³", min=0),
        number("thicknessMm", "Wall thickness", 150, unit="mm", min=1),
        number("heightMm", "Wall height", 3000, unit="mm", min=1),
        number("openingsPercent", "Openings", 0, unit="%", min=0, max=99),
    ],
)
def wall_load(ctx: FeatureContext, values: dict) -> dict:
    """Calculate wall line load from masonry volume per metre, with an openings deduction."""
    gross = values["unitWeightKnPerM3"] * values["thicknessMm"] * values["heightMm"] / 1_000_000
    return result(
        summary={
            "grossLineLoadKnPerM": gross,
            "netLineLoadKnPerM": gross * (1 - values["openingsPercent"] / 100),
            "openingsPercent": values["openingsPercent"],
        },
        notes=["Plaster and finishes are excluded unless included in the entered unit weight."],
    )


@feature(
    "planLoads.livePattern",
    "Live Pattern",
    part="floorPlan",
    fields=[
        text("spanIds", "Ordered span ids", "B1,B2,B3,B4"),
        select(
            "pattern",
            "Pattern",
            [
                ("alternate", "Alternate spans"),
                ("odd", "Odd spans"),
                ("even", "Even spans"),
                ("all", "All spans"),
            ],
        ),
        number("startIndex", "First span number", 1, min=1),
    ],
)
def live_pattern(ctx: FeatureContext, values: dict) -> dict:
    """Select spans for the requested live-load pattern along a continuous beam line."""
    spans = [part.strip() for part in values["spanIds"].split(",") if part.strip()]
    if not spans:
        raise ValueError("Enter one or more span ids in order.")
    selected = []
    for i, span in enumerate(spans):
        n = int(values["startIndex"]) + i
        if (
            values["pattern"] == "all"
            or (values["pattern"] == "alternate" and (n - int(values["startIndex"])) % 2 == 0)
            or (values["pattern"] == "odd" and n % 2 == 1)
            or (values["pattern"] == "even" and n % 2 == 0)
        ):
            selected.append({"span": span, "sequence": n, "loaded": True})
    return result(
        summary={
            "spanCount": len(spans),
            "loadedSpanCount": len(selected),
            "pattern": values["pattern"],
        },
        tables=[
            table(
                "Patterned live-load spans",
                [("span", "Span"), ("sequence", "Sequence"), ("loaded", "Loaded")],
                selected,
            )
        ],
    )


@feature(
    "planLoads.patternRanges",
    "Pattern Ranges",
    part="floorPlan",
    fields=[
        text("spanIds", "Ordered span ids", "B1,B2,B3,B4"),
        number("firstLoaded", "First loaded span number", 1, min=1),
        number("lastLoaded", "Last loaded span number", 4, min=1),
        number("stride", "Load every N spans", 2, min=1),
    ],
)
def pattern_ranges(ctx: FeatureContext, values: dict) -> dict:
    """Build explicit loaded and unloaded span ranges for a repeated loading pattern."""
    spans = [part.strip() for part in values["spanIds"].split(",") if part.strip()]
    first, last, stride = (
        int(values["firstLoaded"]),
        int(values["lastLoaded"]),
        int(values["stride"]),
    )
    if last < first:
        raise ValueError("Last loaded span must be at or after the first loaded span.")
    rows = [
        {
            "span": span,
            "sequence": i + 1,
            "loaded": first <= i + 1 <= last and (i + 1 - first) % stride == 0,
        }
        for i, span in enumerate(spans)
    ]
    return result(
        summary={"loadedSpanCount": sum(row["loaded"] for row in rows), "spanCount": len(rows)},
        tables=[
            table(
                "Pattern range",
                [("span", "Span"), ("sequence", "Sequence"), ("loaded", "Loaded")],
                rows,
            )
        ],
    )


@feature(
    "planLoads.loadGroups",
    "Load Groups",
    part="floorPlan",
    fields=[
        text("name", "Load group name", "Floor gravity"),
        text("cases", "Case ids (comma-separated)", "D,SD,L"),
        select(
            "combination",
            "Combination rule",
            [("sum", "Sum"), ("envelope", "Envelope maximum"), ("separate", "Keep separate")],
        ),
    ],
    requires_project=False,
)
def load_groups(ctx: FeatureContext, values: dict) -> dict:
    """Validate a named load group against the load cases supported by the member-load model."""
    cases = [item.strip() for item in values["cases"].split(",") if item.strip()]
    allowed = {case for case, _ in _CASES}
    unknown = sorted(set(cases) - allowed)
    if not cases or unknown:
        raise ValueError(
            f"Enter known load case ids; unknown: {', '.join(unknown) if unknown else 'none were entered'}."
        )
    return result(
        summary={
            "group": values["name"],
            "caseCount": len(cases),
            "combination": values["combination"],
        },
        tables=[
            table(
                "Load group cases",
                [("order", "Order"), ("case", "Case")],
                [{"order": i + 1, "case": case} for i, case in enumerate(cases)],
            )
        ],
    )


@feature(
    "planLoads.loadSummary",
    "Load Summary",
    part="floorPlan",
    fields=[select("case", "Case filter", [("all", "All cases"), *_CASES], "all")],
)
def load_summary(ctx: FeatureContext, values: dict) -> dict:
    """Summarise stored member loads by case, storey and calculated force."""
    plan = plan_data(ctx)
    data = loads_data(ctx)
    member = {row["id"]: row for row in member_rows(plan)}
    wall_types = {wall["id"]: wall for wall in data.get("wallTypes", [])}
    story_map(plan)
    totals: dict[tuple[str, str], float] = {}
    rows = []
    for item in data.get("loads", []):
        case = item.get("case", "SD")
        if values["case"] != "all" and case != values["case"]:
            continue
        m = member.get(item.get("member"))
        if m is None:
            continue
        force = 0.0
        if item.get("kind", "line") == "point":
            force = float(item.get("value", 0))
        elif item.get("value") is not None:
            force = float(item["value"]) * float(m.get("lengthM", 0))
        elif item.get("wall"):
            wall = wall_types.get(item["wall"].get("type"))
            if wall:
                area_weight = (
                    float(wall["unitWeight"]) * float(wall["thickness"])
                    + float(wall.get("plasterUnitWeight", 23))
                    * float(wall.get("plaster", 0))
                    * int(wall.get("plasterFaces", 2))
                ) / 1000
                height = float(item["wall"].get("height", 0))
                force = (
                    area_weight
                    * height
                    / 1000
                    * (1 - float(item["wall"].get("openings", 0)) / 100)
                    * float(m.get("lengthM", 0))
                )
        storey = m.get("story", "")
        totals[(case, storey)] = totals.get((case, storey), 0) + force
        rows.append(
            {
                "loadId": item.get("id"),
                "member": item.get("member"),
                "case": case,
                "storey": storey,
                "resultantKn": force,
            }
        )
    summary_rows = [
        {"case": case, "storey": storey, "resultantKn": force}
        for (case, storey), force in sorted(totals.items())
    ]
    return result(
        summary={"loadCount": len(rows), "resultantKn": sum(item["resultantKn"] for item in rows)},
        tables=[
            table(
                "Load by record",
                [
                    ("loadId", "Load"),
                    ("member", "Member"),
                    ("case", "Case"),
                    ("storey", "Storey"),
                    ("resultantKn", "Resultant", "kN"),
                ],
                rows,
            ),
            table(
                "Load by case and storey",
                [("case", "Case"), ("storey", "Storey"), ("resultantKn", "Resultant", "kN")],
                summary_rows,
            ),
        ],
    )


@feature(
    "planLoads.loadArrows",
    "Load Arrows",
    part="floorPlan",
    fields=[
        select("scale", "Arrow scale", [("force", "Scale to load"), ("equal", "Equal size")]),
        number("referenceKn", "Reference force", 10, unit="kN", min=0.01),
    ],
)
def load_arrows(ctx: FeatureContext, values: dict) -> dict:
    """Create arrow direction, magnitude and display-length data for stored loads."""
    plan = plan_data(ctx)
    data, members = loads_data(ctx), {row["id"]: row for row in member_rows(plan)}
    rows = []
    for item in data.get("loads", []):
        m = members.get(item.get("member"))
        if m is None:
            continue
        magnitude = float(item.get("value") or 0)
        rows.append(
            {
                "loadId": item.get("id"),
                "member": m["id"],
                "direction": "down"
                if item.get("kind", "line") == "line" or item.get("distance") is None
                else "down at beam station",
                "magnitude": magnitude,
                "arrowScale": min(1.0, magnitude / values["referenceKn"])
                if values["scale"] == "force"
                else 1.0,
            }
        )
    return result(
        summary={"arrowCount": len(rows), "scaleMode": values["scale"]},
        tables=[
            table(
                "Load arrow data",
                [
                    ("loadId", "Load"),
                    ("member", "Member"),
                    ("direction", "Direction"),
                    ("magnitude", "Input value"),
                    ("arrowScale", "Relative arrow length"),
                ],
                rows,
            )
        ],
    )


@feature(
    "planLoads.loadCheck",
    "Load Check",
    part="floorPlan",
    fields=[
        checkbox("checkMemberExists", "Check member references", True),
        checkbox("checkCase", "Check load cases", True),
        number("zeroTolerance", "Near-zero load tolerance", 0.001, unit="kN", min=0),
    ],
)
def load_check(ctx: FeatureContext, values: dict) -> dict:
    """Find stored loads with deleted member references, unsupported cases or negligible values."""
    plan, data = plan_data(ctx), loads_data(ctx)
    known = {row["id"] for row in member_rows(plan)}
    cases = {case for case, _ in _CASES}
    issues = []
    for item in data.get("loads", []):
        if values["checkMemberExists"] and item.get("member") not in known:
            issues.append(
                {
                    "loadId": item.get("id"),
                    "issue": "member reference is missing",
                    "member": item.get("member"),
                }
            )
        if values["checkCase"] and item.get("case", "SD") not in cases:
            issues.append(
                {
                    "loadId": item.get("id"),
                    "issue": "unknown load case",
                    "member": item.get("member"),
                }
            )
        load_value = float(item.get("value") or 0)
        if abs(load_value) <= values["zeroTolerance"]:
            issues.append(
                {
                    "loadId": item.get("id"),
                    "issue": "load is at or below the near-zero threshold",
                    "member": item.get("member"),
                }
            )
    return result(
        summary={"loadCount": len(data.get("loads", [])), "issueCount": len(issues)},
        tables=[
            table(
                "Load validation issues",
                [("loadId", "Load"), ("member", "Member"), ("issue", "Issue")],
                issues,
            )
        ],
    )


@feature(
    "planLoads.linearLoad",
    "Linear Load",
    part="floorPlan",
    fields=[
        text("beamId", "Beam id", "B1"),
        number("intensityKnPerM", "Uniform intensity", 5, unit="kN/m", min=0),
        number("startRatio", "Start ratio", 0, min=0, max=1),
        number("endRatio", "End ratio", 1, min=0, max=1),
    ],
)
def linear_load(ctx: FeatureContext, values: dict) -> dict:
    """Calculate the resultant of a uniform load over a selected portion of a beam."""
    _, rows = profile(ctx)
    beam = next((r for r in rows if r["id"] == values["beamId"] and r["category"] == "beam"), None)
    if beam is None or values["endRatio"] <= values["startRatio"]:
        raise ValueError("Choose an existing beam and an end ratio greater than the start ratio.")
    length = beam["lengthM"] * (values["endRatio"] - values["startRatio"])
    return result(
        summary={
            "loadedLengthM": length,
            "resultantKn": values["intensityKnPerM"] * length,
            "centroidFromBeamStartM": beam["lengthM"]
            * (values["startRatio"] + values["endRatio"])
            / 2,
        }
    )


@feature(
    "planLoads.trapezoidalLoad",
    "Trapezoidal Load",
    part="floorPlan",
    fields=[
        text("beamId", "Beam id", "B1"),
        number("startKnPerM", "Start intensity", 0, unit="kN/m", min=0),
        number("endKnPerM", "End intensity", 10, unit="kN/m", min=0),
    ],
)
def trapezoidal_load(ctx: FeatureContext, values: dict) -> dict:
    """Integrate a linearly varying beam load and locate its centroid."""
    _, rows = profile(ctx)
    beam = next((r for r in rows if r["id"] == values["beamId"] and r["category"] == "beam"), None)
    if beam is None:
        raise ValueError("Choose an existing beam id.")
    w0, w1, length = values["startKnPerM"], values["endKnPerM"], beam["lengthM"]
    resultant = (w0 + w1) * length / 2
    centroid = length * (w0 + 2 * w1) / (3 * (w0 + w1)) if w0 + w1 else length / 2
    return result(
        summary={
            "spanM": length,
            "resultantKn": resultant,
            "centroidFromStartM": centroid,
            "startIntensityKnPerM": w0,
            "endIntensityKnPerM": w1,
        }
    )


@feature(
    "planLoads.patchLoad",
    "Patch Load",
    part="floorPlan",
    fields=[
        text("slabId", "Slab id", "S1"),
        number("widthM", "Patch width", 1, unit="m", min=0.01),
        number("lengthM", "Patch length", 1, unit="m", min=0.01),
        number("intensityKpa", "Patch pressure", 5, unit="kPa", min=0),
    ],
)
def patch_load(ctx: FeatureContext, values: dict) -> dict:
    """Calculate patch load area and resultant, checking it fits within the slab polygon area."""
    _, rows = profile(ctx)
    slab = next((r for r in rows if r["id"] == values["slabId"] and r["category"] == "slab"), None)
    if slab is None:
        raise ValueError("Choose an existing slab id.")
    area = values["widthM"] * values["lengthM"]
    if area > slab["areaM2"]:
        raise ValueError("Patch area exceeds the selected slab's total area.")
    return result(
        summary={
            "patchAreaM2": area,
            "slabAreaM2": slab["areaM2"],
            "resultantKn": area * values["intensityKpa"],
            "areaFraction": area / slab["areaM2"],
        }
    )


@feature(
    "planLoads.projectedLoad",
    "Projected Load",
    part="floorPlan",
    fields=[
        number("surfaceIntensityKpa", "Load on actual surface", 2, unit="kPa", min=0),
        number("slopeDeg", "Surface slope from horizontal", 15, unit="°", min=0, max=89.9),
    ],
)
def projected_load(ctx: FeatureContext, values: dict) -> dict:
    """Convert load per actual sloping area to the equivalent load per horizontal projected area."""
    factor = 1 / math.cos(math.radians(values["slopeDeg"]))
    return result(
        summary={
            "projectionFactor": factor,
            "projectedIntensityKpa": values["surfaceIntensityKpa"] * factor,
            "slopeDeg": values["slopeDeg"],
        },
        notes=[
            "Assumes the same total force over the horizontal projection; projected intensity is actual-area intensity divided by cos(slope)."
        ],
    )


@feature(
    "planLoads.areaLoadDirection",
    "Area Load Direction",
    part="floorPlan",
    fields=[
        number("intensityKpa", "Area load intensity", 2, unit="kPa", min=0),
        number("slopeDeg", "Surface slope", 0, unit="°", min=0, max=90),
        select(
            "direction",
            "Load direction",
            [("vertical", "Global vertical"), ("normal", "Normal to surface")],
        ),
    ],
    requires_project=False,
)
def area_load_direction(ctx: FeatureContext, values: dict) -> dict:
    """Resolve vertical and surface-normal components of an area load on a sloped plane."""
    theta = math.radians(values["slopeDeg"])
    if values["direction"] == "vertical":
        vertical, horizontal = values["intensityKpa"], 0.0
    else:
        vertical = values["intensityKpa"] * math.cos(theta)
        horizontal = values["intensityKpa"] * math.sin(theta)
    return result(
        summary={
            "verticalComponentKpa": vertical,
            "horizontalComponentKpa": horizontal,
            "direction": values["direction"],
        }
    )


@feature(
    "planLoads.wallSelfLoad",
    "Wall Self Load",
    part="floorPlan",
    fields=[
        number("heightMm", "Wall height", 3000, unit="mm", min=1),
        number("thicknessMm", "Wall thickness", 150, unit="mm", min=1),
        number("densityKnPerM3", "Wall density", 18, unit="kN/m³", min=0),
        number("plasterMm", "Plaster on each face", 12, unit="mm", min=0),
        number("plasterDensity", "Plaster density", 23, unit="kN/m³", min=0),
    ],
)
def wall_self_load(ctx: FeatureContext, values: dict) -> dict:
    """Derive wall line load per metre including plaster on both faces."""
    masonry = values["heightMm"] * values["thicknessMm"] * values["densityKnPerM3"] / 1_000_000
    plaster = values["heightMm"] * 2 * values["plasterMm"] * values["plasterDensity"] / 1_000_000
    return result(
        summary={
            "masonryKnPerM": masonry,
            "plasterKnPerM": plaster,
            "totalLineLoadKnPerM": masonry + plaster,
        }
    )


@feature(
    "planLoads.stairLoad",
    "Stair Load",
    part="floorPlan",
    fields=[
        number("riseM", "Total rise", 3, unit="m", min=0.1),
        number("runM", "Horizontal run", 4, unit="m", min=0.1),
        number("flightLoadKpa", "Flight load", 3, unit="kPa", min=0),
        number("widthM", "Flight width", 1.2, unit="m", min=0.1),
        number("landingAreaM2", "Landing area", 2, unit="m²", min=0),
        number("landingLoadKpa", "Landing load", 3, unit="kPa", min=0),
    ],
)
def stair_load(ctx: FeatureContext, values: dict) -> dict:
    """Calculate flight slope length and combined flight-plus-landing gravity load."""
    flight_length = math.hypot(values["riseM"], values["runM"])
    flight_area = flight_length * values["widthM"]
    flight_force = flight_area * values["flightLoadKpa"]
    landing_force = values["landingAreaM2"] * values["landingLoadKpa"]
    return result(
        summary={
            "flightSlopeLengthM": flight_length,
            "flightAreaM2": flight_area,
            "flightLoadKn": flight_force,
            "landingLoadKn": landing_force,
            "totalLoadKn": flight_force + landing_force,
        }
    )


@feature(
    "planLoads.equipmentLoad",
    "Equipment Load",
    part="floorPlan",
    fields=[
        text("slabId", "Slab id", "S1"),
        number("equipmentKn", "Equipment weight", 20, unit="kN", min=0),
        number("footprintM2", "Footprint area", 1, unit="m²", min=0.01),
        number("maintenanceKn", "Maintenance load", 0, unit="kN", min=0),
    ],
)
def equipment_load(ctx: FeatureContext, values: dict) -> dict:
    """Convert equipment and maintenance weights into footprint pressure on a slab."""
    _, rows = profile(ctx)
    slab = next((r for r in rows if r["id"] == values["slabId"] and r["category"] == "slab"), None)
    if slab is None:
        raise ValueError("Choose an existing slab id.")
    force = values["equipmentKn"] + values["maintenanceKn"]
    return result(
        summary={
            "slabId": slab["id"],
            "footprintPressureKpa": force / values["footprintM2"],
            "totalForceKn": force,
            "footprintFraction": values["footprintM2"] / slab["areaM2"],
        }
    )


@feature(
    "planLoads.rainPondingLoad",
    "Rain Ponding Load",
    part="floorPlan",
    fields=[
        number("waterDepthMm", "Ponded water depth", 50, unit="mm", min=0),
        number("waterUnitWeight", "Water unit weight", 9.81, unit="kN/m³", min=0),
        number("pondedAreaM2", "Ponded roof area", 20, unit="m²", min=0),
    ],
)
def rain_ponding_load(ctx: FeatureContext, values: dict) -> dict:
    """Calculate hydrostatic rain-water pressure and total load over a ponded roof patch."""
    pressure = values["waterUnitWeight"] * values["waterDepthMm"] / 1000
    return result(
        summary={
            "waterPressureKpa": pressure,
            "totalPondingLoadKn": pressure * values["pondedAreaM2"],
            "waterDepthMm": values["waterDepthMm"],
        },
        notes=[
            "Static water layer; roof deflection and progressive ponding stability are not included."
        ],
    )


@feature(
    "planLoads.snowDrift",
    "Snow Drift",
    part="floorPlan",
    fields=[
        number("uniformRoofKpa", "Uniform roof snow load", 1, unit="kPa", min=0),
        number("driftPeakKpa", "Drift peak intensity", 2, unit="kPa", min=0),
        number("driftWidthM", "Drift width", 2, unit="m", min=0.01),
        number("parapetHeightM", "Upwind parapet height", 1, unit="m", min=0),
    ],
)
def snow_drift(ctx: FeatureContext, values: dict) -> dict:
    """Integrate a linear triangular drift above a uniform roof snow load."""
    drift = max(0.0, values["driftPeakKpa"] - values["uniformRoofKpa"])
    return result(
        summary={
            "triangularDriftExcessKnPerM": drift * values["driftWidthM"] / 2,
            "peakTotalKpa": values["uniformRoofKpa"] + drift,
            "driftCentroidFromParapetM": values["driftWidthM"] / 3,
            "parapetHeightM": values["parapetHeightM"],
        },
        notes=[
            "The drift excess is triangular across the specified width; the drift peak and width are engineer-entered inputs."
        ],
    )


@feature(
    "planLoads.loadTakeDown",
    "Load Take-Down",
    part="floorPlan",
    fields=[select("case", "Load case", [("all", "All cases"), *_CASES], "all")],
)
def load_take_down(ctx: FeatureContext, values: dict) -> dict:
    """Sum actual stored member-load resultants one floor at a time."""
    plan = plan_data(ctx)
    data = loads_data(ctx)
    members = {row["id"]: row for row in member_rows(plan)}
    totals = {s["id"]: 0.0 for s in plan["stories"]}
    for item in data.get("loads", []):
        if values["case"] != "all" and item.get("case", "SD") != values["case"]:
            continue
        member = members.get(item.get("member"))
        if member is None:
            continue
        force = float(item.get("value") or 0)
        if item.get("kind", "line") == "line":
            force *= float(member.get("lengthM", 0))
        story = member.get("story")
        totals[story] = totals.get(story, 0) + force
    rows = [
        {
            "storey": story["id"],
            "elevationMm": story["elevation"],
            "directLoadKn": totals.get(story["id"], 0),
        }
        for story in sorted(plan["stories"], key=lambda s: float(s["elevation"]), reverse=True)
    ]
    cumulative = 0.0
    for row in rows:
        cumulative += row["directLoadKn"]
        row["loadCarriedBelowKn"] = cumulative
    return result(
        summary={"baseAccumulatedLoadKn": cumulative, "storeyCount": len(rows)},
        tables=[
            table(
                "Floor-by-floor load take-down",
                [
                    ("storey", "Storey"),
                    ("elevationMm", "Elevation", "mm"),
                    ("directLoadKn", "Direct load", "kN"),
                    ("loadCarriedBelowKn", "Accumulated", "kN"),
                ],
                rows,
            )
        ],
        notes=[
            "Only stored member-load records are summed; slab self-weight and load combinations are outside this take-down."
        ],
    )


@feature(
    "planLoads.loadPathCheck",
    "Load Path Check",
    part="floorPlan",
    fields=[
        text("memberId", "Loaded member id", "B1"),
        number("nodeToleranceMm", "Joint coincidence tolerance", 1, unit="mm", min=0.01),
    ],
)
def load_path_check(ctx: FeatureContext, values: dict) -> dict:
    """Check whether each beam end is coincident with a column or wall support line."""
    plan = plan_data(ctx)
    rows = member_rows(plan)
    beam = next(
        (r for r in rows if r["id"] == values["memberId"] and r["category"] == "beam"), None
    )
    if beam is None:
        raise ValueError("Choose an existing beam id.")
    supports = [
        r for r in rows if r["category"] in {"column", "wall"} and r["story"] == beam["story"]
    ]
    ends = [("start", (beam["x1Mm"], beam["y1Mm"])), ("end", (beam["x2Mm"], beam["y2Mm"]))]
    matched = [
        {
            "end": label,
            "nearestSupportId": min(
                supports, key=lambda s: math.hypot(s["x1Mm"] - pt[0], s["y1Mm"] - pt[1])
            )["id"]
            if supports
            else "",
            "distanceMm": min(
                (math.hypot(s["x1Mm"] - pt[0], s["y1Mm"] - pt[1]) for s in supports), default=None
            ),
            "supported": bool(supports)
            and min(math.hypot(s["x1Mm"] - pt[0], s["y1Mm"] - pt[1]) for s in supports)
            <= values["nodeToleranceMm"],
        }
        for label, pt in ends
    ]
    return result(
        summary={
            "beamId": beam["id"],
            "supportedEnds": sum(row["supported"] for row in matched),
            "endCount": 2,
            "continuousToSupport": all(row["supported"] for row in matched),
        },
        tables=[
            table(
                "Beam end support path",
                [
                    ("end", "End"),
                    ("nearestSupportId", "Nearest support"),
                    ("distanceMm", "Distance", "mm"),
                    ("supported", "Connected"),
                ],
                matched,
            )
        ],
        notes=[
            "This geometric screen checks only endpoint coincidence against support centrelines at the beam storey."
        ],
    )


@feature(
    "planLoads.loadEnvelopeView",
    "Load Envelope View",
    part="floorPlan",
    fields=[
        text("caseValues", "Case resultants (case:value kN, comma-separated)", "D:10,SD:4,L:8,Lr:2")
    ],
    requires_project=False,
)
def load_envelope_view(ctx: FeatureContext, values: dict) -> dict:
    """Extract minimum and maximum from explicitly supplied case resultants."""
    parsed = []
    try:
        for pair in values["caseValues"].split(","):
            case, magnitude = pair.split(":", 1)
            parsed.append({"case": case.strip(), "resultantKn": float(magnitude)})
    except (ValueError, TypeError) as exc:
        raise ValueError("Enter comma-separated case:value pairs, such as D:10,L:8.") from exc
    if not parsed:
        raise ValueError("Enter at least one case resultant.")
    maximum, minimum = (
        max(parsed, key=lambda r: r["resultantKn"]),
        min(parsed, key=lambda r: r["resultantKn"]),
    )
    return result(
        summary={
            "maximumCase": maximum["case"],
            "maximumKn": maximum["resultantKn"],
            "minimumCase": minimum["case"],
            "minimumKn": minimum["resultantKn"],
        },
        tables=[
            table(
                "Load case envelope", [("case", "Case"), ("resultantKn", "Resultant", "kN")], parsed
            )
        ],
    )
