"""Fixture schedules, connections and accessibility calculations."""

from __future__ import annotations

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


def _fixture_stories(ctx: FeatureContext) -> list[dict]:
    raw = ctx.raw("mep")
    plumbing = raw.get("plumbing") if raw else None
    stories = plumbing.get("stories", []) if isinstance(plumbing, dict) else []
    if not stories:
        raise FeatureInputError("Add plumbing stories and fixture counts to 07 MEP/mep.json first.")
    return stories


@feature(
    "mepFixtures.connectionPoints",
    "Connection Points",
    part="mep",
    fields=[
        text("fixtureTag", "Fixture tag", "WC-01"),
        select(
            "fixtureType", "Fixture type", ["wc", "basin", "shower", "kitchenSink", "floorDrain"]
        ),
        number("coldWaterLps", "Cold-water connection flow", 0.1, unit="L/s", min=0),
        number("hotWaterLps", "Hot-water connection flow", 0.05, unit="L/s", min=0),
        number("wasteDiameterMm", "Waste outlet diameter", 50, unit="mm", min=0),
    ],
    requires_project=False,
)
def connection_points(ctx: FeatureContext, values: dict) -> dict:
    """Describe the selected fixture's service connectors."""
    services = [
        {"service": "coldWater", "flowLps": values["coldWaterLps"], "connection": "inlet"},
        {"service": "hotWater", "flowLps": values["hotWaterLps"], "connection": "inlet"},
        {"service": "waste", "diameterMm": values["wasteDiameterMm"], "connection": "outlet"},
    ]
    active = [row for row in services if row.get("flowLps", row.get("diameterMm", 0)) > 0]
    return result(
        summary={
            "fixtureTag": values["fixtureTag"],
            "fixtureType": values["fixtureType"],
            "connectorCount": len(active),
        },
        tables=[
            table(
                "Fixture connectors",
                [
                    ("service", "Service"),
                    ("connection", "Connection"),
                    ("flowLps", "Flow", "L/s"),
                    ("diameterMm", "Diameter", "mm"),
                ],
                active,
            )
        ],
        notes=[
            "Connector values are explicit design inputs; coordinates and elevations must be assigned in the project model."
        ],
    )


@feature(
    "mepFixtures.fixtureUnitsTable",
    "Fixture Units Table",
    part="mep",
    fields=[
        select(
            "fixtureType", "Fixture type", ["wc", "basin", "shower", "kitchenSink", "floorDrain"]
        ),
        number("waterSupplyUnits", "Water supply units", 2.0, min=0),
        number("drainageUnits", "Drainage units", 2.0, min=0),
        number("flowLps", "Design flow", 0.1, unit="L/s", min=0),
    ],
    requires_project=False,
)
def fixture_units_table(ctx: FeatureContext, values: dict) -> dict:
    """Present fixture supply, drainage and flow factors for project configuration."""
    return result(
        summary={
            "fixtureType": values["fixtureType"],
            "waterSupplyUnits": values["waterSupplyUnits"],
            "drainageUnits": values["drainageUnits"],
        },
        tables=[
            table(
                "Fixture unit factors",
                [
                    ("fixtureType", "Fixture"),
                    ("supplyUnits", "Supply units"),
                    ("drainageUnits", "Drainage units"),
                    ("flowLps", "Flow", "L/s"),
                ],
                [
                    {
                        "fixtureType": values["fixtureType"],
                        "supplyUnits": values["waterSupplyUnits"],
                        "drainageUnits": values["drainageUnits"],
                        "flowLps": values["flowLps"],
                    }
                ],
            )
        ],
        notes=[
            "Factors are editable project design values and are not assumed to be universal fixture standards."
        ],
    )


@feature("mepFixtures.occupancyMapping", "Occupancy Mapping", part="mep", requires_project=True)
def occupancy_mapping(ctx: FeatureContext, values: dict) -> dict:
    """List fixture counts against each project's room-use classification."""
    rows = []
    for story in _fixture_stories(ctx):
        counts = story.get("fixtures", {})
        for kind, count in counts.items():
            rows.append(
                {
                    "story": story.get("story", ""),
                    "occupancy": story.get("occupancy", ""),
                    "fixture": kind,
                    "count": count,
                }
            )
    return result(
        summary={
            "mappedStoryCount": len({row["story"] for row in rows}),
            "fixtureCount": sum(float(r["count"]) for r in rows),
        },
        tables=[
            table(
                "Occupancy and fixture mapping",
                [
                    ("story", "Story"),
                    ("occupancy", "Occupancy"),
                    ("fixture", "Fixture"),
                    ("count", "Count"),
                ],
                rows,
            )
        ],
        notes=[
            "This mapping reflects the project's plumbing story and fixture data; unassigned room-level fixtures are not inferred."
        ],
    )


@feature(
    "mepFixtures.accessibility",
    "Accessibility",
    part="mep",
    fields=[
        number("clearWidthM", "Available clear width", 1.5, unit="m", min=0),
        number("requiredWidthM", "Required clear width", 1.2, unit="m", min=0.1),
        number("clearDepthM", "Available clear depth", 1.5, unit="m", min=0),
        number("requiredDepthM", "Required clear depth", 1.5, unit="m", min=0.1),
    ],
    requires_project=False,
)
def accessibility(ctx: FeatureContext, values: dict) -> dict:
    """Check user-defined accessible fixture approach clearances."""
    width_ok = values["clearWidthM"] >= values["requiredWidthM"]
    depth_ok = values["clearDepthM"] >= values["requiredDepthM"]
    return result(
        summary={"widthPasses": width_ok, "depthPasses": depth_ok, "passes": width_ok and depth_ok},
        tables=[
            table(
                "Approach clearance",
                [
                    ("axis", "Axis"),
                    ("providedM", "Provided", "m"),
                    ("requiredM", "Required", "m"),
                    ("passes", "Pass"),
                ],
                [
                    {
                        "axis": "Width",
                        "providedM": values["clearWidthM"],
                        "requiredM": values["requiredWidthM"],
                        "passes": width_ok,
                    },
                    {
                        "axis": "Depth",
                        "providedM": values["clearDepthM"],
                        "requiredM": values["requiredDepthM"],
                        "passes": depth_ok,
                    },
                ],
            )
        ],
        notes=[
            "Required clearances are editable project criteria; confirm the governing accessibility requirements before design."
        ],
    )


@feature("mepFixtures.sanitarySchedule", "Sanitary Schedule", part="mep", requires_project=True)
def sanitary_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Schedule sanitary fixture counts and associated occupancy by story."""
    rows = []
    for story in _fixture_stories(ctx):
        for kind, count in story.get("fixtures", {}).items():
            rows.append(
                {
                    "story": story.get("story", ""),
                    "occupancy": story.get("occupancy", ""),
                    "fixture": kind,
                    "quantity": count,
                }
            )
    return result(
        summary={
            "scheduledFixtureTypes": len({r["fixture"] for r in rows}),
            "totalFixtures": sum(float(r["quantity"]) for r in rows),
        },
        tables=[
            table(
                "Sanitary fixture schedule",
                [
                    ("story", "Story"),
                    ("occupancy", "Occupancy"),
                    ("fixture", "Fixture type"),
                    ("quantity", "Quantity"),
                ],
                rows,
            )
        ],
        notes=["Schedule quantities are read from 07 MEP/mep.json."],
    )


@feature("mepFixtures.fixtureCount", "Fixture Count", part="mep", requires_project=True)
def fixture_count(ctx: FeatureContext, values: dict) -> dict:
    """Aggregate each fixture type by story and building total."""
    stories = _fixture_stories(ctx)
    total_by_type: dict[str, float] = {}
    rows = []
    for story in stories:
        for kind, quantity in story.get("fixtures", {}).items():
            total_by_type[kind] = total_by_type.get(kind, 0) + float(quantity)
            rows.append({"story": story.get("story", ""), "fixture": kind, "quantity": quantity})
    return result(
        summary={"totalFixtures": sum(total_by_type.values()), "fixtureTypes": len(total_by_type)},
        tables=[
            table(
                "Count by story",
                [("story", "Story"), ("fixture", "Fixture"), ("quantity", "Quantity")],
                rows,
            ),
            table(
                "Building totals",
                [("fixture", "Fixture"), ("quantity", "Quantity")],
                [
                    {"fixture": kind, "quantity": quantity}
                    for kind, quantity in sorted(total_by_type.items())
                ],
            ),
        ],
        notes=["Counts aggregate only the fixture types recorded on each plumbing story."],
    )


@feature(
    "mepFixtures.exportFixtureSchedule",
    "Export Fixture Schedule",
    part="mep",
    requires_project=True,
)
def export_fixture_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Prepare a machine-readable fixture schedule for export."""
    rows = [
        {"story": story.get("story", ""), "fixture": kind, "quantity": quantity}
        for story in _fixture_stories(ctx)
        for kind, quantity in story.get("fixtures", {}).items()
    ]
    csv = "story,fixture,quantity\n" + "".join(
        f"{row['story']},{row['fixture']},{row['quantity']}\n" for row in rows
    )
    return result(
        summary={"rowCount": len(rows), "csv": csv},
        tables=[
            table(
                "Fixture schedule export rows",
                [("story", "Story"), ("fixture", "Fixture"), ("quantity", "Quantity")],
                rows,
            )
        ],
        notes=[
            "CSV content is returned for the caller to save; this read-only feature does not modify the project."
        ],
    )


@feature(
    "mepFixtures.grabBars",
    "Grab Bars",
    part="mep",
    fields=[
        number("barLengthMm", "Grab bar length", 600, unit="mm", min=100),
        number("supportSpacingMm", "Support spacing", 450, unit="mm", min=50),
        number("designLoadN", "Design load", 1100, unit="N", min=1),
        number("supportCapacityN", "Capacity per support", 750, unit="N", min=1),
    ],
    requires_project=False,
)
def grab_bars(ctx: FeatureContext, values: dict) -> dict:
    """Check support count and average support reaction for a grab bar."""
    support_count = max(2, int(values["barLengthMm"] / values["supportSpacingMm"]) + 1)
    reaction = values["designLoadN"] / support_count
    return result(
        summary={
            "supportCount": support_count,
            "reactionPerSupportN": reaction,
            "supportPasses": reaction <= values["supportCapacityN"],
        },
        notes=[
            "Support reaction is a simple equal-sharing screening check; verify bar bending, anchorage, wall substrate and load eccentricity separately."
        ],
    )


@feature(
    "mepFixtures.accessibleWc",
    "Accessible WC",
    part="mep",
    fields=[
        number("roomWidthM", "Room clear width", 2.2, unit="m", min=0.1),
        number("roomDepthM", "Room clear depth", 2.2, unit="m", min=0.1),
        number("wcProjectionM", "WC projection from wall", 0.72, unit="m", min=0.1),
        number("sideTransferM", "Side transfer clearance", 0.9, unit="m", min=0),
        number("frontClearanceM", "Front approach clearance", 1.2, unit="m", min=0),
    ],
    requires_project=False,
)
def accessible_wc(ctx: FeatureContext, values: dict) -> dict:
    """Check accessible WC side-transfer and frontal approach envelopes."""
    side_available = values["roomWidthM"] - values["wcProjectionM"]
    front_available = values["roomDepthM"] - values["wcProjectionM"]
    side_ok = side_available >= values["sideTransferM"]
    front_ok = front_available >= values["frontClearanceM"]
    return result(
        summary={
            "sideAvailableM": side_available,
            "frontAvailableM": front_available,
            "layoutPasses": side_ok and front_ok,
        },
        tables=[
            table(
                "WC approach envelopes",
                [
                    ("check", "Check"),
                    ("availableM", "Available", "m"),
                    ("requiredM", "Required", "m"),
                    ("passes", "Pass"),
                ],
                [
                    {
                        "check": "Side transfer",
                        "availableM": side_available,
                        "requiredM": values["sideTransferM"],
                        "passes": side_ok,
                    },
                    {
                        "check": "Front approach",
                        "availableM": front_available,
                        "requiredM": values["frontClearanceM"],
                        "passes": front_ok,
                    },
                ],
            )
        ],
        notes=[
            "This rectangular room-envelope check uses the entered fixture projection and project clearance criteria; door swings and wall-mounted accessories are excluded."
        ],
    )


@feature(
    "mepFixtures.turningCircle",
    "Turning Circle",
    part="mep",
    fields=[
        number("clearWidthM", "Unobstructed room width", 1.7, unit="m", min=0),
        number("clearDepthM", "Unobstructed room depth", 1.7, unit="m", min=0),
        number("requiredDiameterM", "Required turning diameter", 1.5, unit="m", min=0.1),
    ],
    requires_project=False,
)
def turning_circle(ctx: FeatureContext, values: dict) -> dict:
    """Verify that a circular maneuvering space fits within a clear rectangle."""
    fit = min(values["clearWidthM"], values["clearDepthM"])
    return result(
        summary={
            "availableDiameterM": fit,
            "requiredDiameterM": values["requiredDiameterM"],
            "fits": fit >= values["requiredDiameterM"],
        },
        notes=[
            "A full unobstructed circle fits only when both clear room dimensions meet the entered diameter; fixtures and door swings must be excluded from the measured clear space."
        ],
    )


@feature(
    "mepFixtures.reachRange",
    "Reach Range",
    part="mep",
    fields=[
        number("controlHeightMm", "Control height above floor", 1050, unit="mm", min=0),
        number("minimumReachMm", "Minimum permitted reach height", 400, unit="mm", min=0),
        number("maximumReachMm", "Maximum permitted reach height", 1200, unit="mm", min=1),
    ],
    requires_project=False,
)
def reach_range(ctx: FeatureContext, values: dict) -> dict:
    """Check a control mounting height against an editable reach band."""
    passes = values["minimumReachMm"] <= values["controlHeightMm"] <= values["maximumReachMm"]
    return result(
        summary={"controlHeightMm": values["controlHeightMm"], "withinReachBand": passes},
        notes=[
            "Reach limits are entered design criteria; verify forward/side approach, obstruction and accessibility standard details separately."
        ],
    )


@feature(
    "mepFixtures.showerSeat",
    "Shower Seat",
    part="mep",
    fields=[
        number("seatHeightMm", "Seat height above finished floor", 450, unit="mm", min=0),
        number("seatWidthMm", "Seat width", 900, unit="mm", min=100),
        number("compartmentWidthMm", "Compartment clear width", 1200, unit="mm", min=100),
        number("requiredTransferMm", "Required transfer clearance", 750, unit="mm", min=0),
    ],
    requires_project=False,
)
def shower_seat(ctx: FeatureContext, values: dict) -> dict:
    """Check the shower seat transfer side and record its mounting geometry."""
    remaining = values["compartmentWidthMm"] - values["seatWidthMm"]
    return result(
        summary={
            "seatHeightMm": values["seatHeightMm"],
            "transferClearanceMm": remaining,
            "transferPasses": remaining >= values["requiredTransferMm"],
        },
        notes=[
            "The side clearance is compartment width less seat width; confirm transfer orientation, folding projection, waterproofing and anchorage in the detailed layout."
        ],
    )


@feature(
    "mepFixtures.flowRateAssign",
    "Flow Rate Assign",
    part="mep",
    fields=[
        select(
            "fixtureType", "Fixture type", ["wc", "basin", "shower", "kitchenSink", "floorDrain"]
        ),
        number("coldFlowLps", "Cold-water flow per fixture", 0.1, unit="L/s", min=0),
        number("hotFlowLps", "Hot-water flow per fixture", 0.05, unit="L/s", min=0),
    ],
    requires_project=True,
)
def flow_rate_assign(ctx: FeatureContext, values: dict) -> dict:
    """Apply entered design flows to the project count for one fixture type."""
    counts = {}
    for story in _fixture_stories(ctx):
        quantity = float(story.get("fixtures", {}).get(values["fixtureType"], 0))
        if quantity:
            counts[story.get("story", "")] = quantity
    if not counts:
        raise FeatureInputError(f"No {values['fixtureType']} fixtures are recorded in the project.")
    rows = [
        {
            "story": story,
            "quantity": count,
            "coldFlowLps": count * values["coldFlowLps"],
            "hotFlowLps": count * values["hotFlowLps"],
        }
        for story, count in counts.items()
    ]
    return result(
        summary={
            "fixtureType": values["fixtureType"],
            "fixtureCount": sum(counts.values()),
            "coldFlowLps": sum(r["coldFlowLps"] for r in rows),
            "hotFlowLps": sum(r["hotFlowLps"] for r in rows),
        },
        tables=[
            table(
                "Assigned fixture flows",
                [
                    ("story", "Story"),
                    ("quantity", "Quantity"),
                    ("coldFlowLps", "Cold", "L/s"),
                    ("hotFlowLps", "Hot", "L/s"),
                ],
                rows,
            )
        ],
        notes=[
            "Calculated totals apply entered per-fixture flows to project quantities; the source project is not modified."
        ],
    )


@feature(
    "mepFixtures.peakDemand",
    "Peak Demand",
    part="mep",
    fields=[number("fixtureUnits", "Connected supply fixture units", 35, min=0.1)],
    requires_project=False,
)
def peak_demand(ctx: FeatureContext, values: dict) -> dict:
    """Estimate probable peak flow from fixture units."""
    from saengine.plumbing.hot_water import hunter_flow

    flow = hunter_flow(values["fixtureUnits"])
    return result(
        summary={"fixtureUnits": values["fixtureUnits"], "probableFlowLps": flow},
        notes=[
            "Probable demand is calculated with the engine's fixture-unit method; flush-valve fixtures require separate input and treatment."
        ],
    )


@feature(
    "mepFixtures.diversityFactor",
    "Diversity Factor",
    part="mep",
    fields=[
        number("connectedFlowLps", "Connected flow", 2.0, unit="L/s", min=0),
        number("diversityFactor", "Coincident use fraction", 0.45, min=0.01, max=1),
    ],
    requires_project=False,
)
def diversity_factor(ctx: FeatureContext, values: dict) -> dict:
    """Apply an explicit coincidence fraction to connected fixture flow."""
    coincident = values["connectedFlowLps"] * values["diversityFactor"]
    return result(
        summary={"coincidentFlowLps": coincident, "diversityFactor": values["diversityFactor"]},
        notes=[
            "Coincidence fraction is a project input and is applied directly to connected flow; no occupancy-based diversity is inferred."
        ],
    )


@feature(
    "mepFixtures.hotWaterShare",
    "Hot Water Share",
    part="mep",
    fields=[
        number("totalFlowLps", "Total fixture flow", 1.0, unit="L/s", min=0),
        number("hotFraction", "Hot-water share", 0.35, min=0, max=1),
        number("hotTemperatureC", "Hot supply temperature", 60, unit="°C"),
        number("coldTemperatureC", "Cold supply temperature", 15, unit="°C"),
        number("mixedTemperatureC", "Mixed outlet temperature", 40, unit="°C"),
    ],
    requires_project=False,
)
def hot_water_share(ctx: FeatureContext, values: dict) -> dict:
    """Calculate hot and cold blend fractions for the selected outlet temperature."""
    delta = values["hotTemperatureC"] - values["coldTemperatureC"]
    if (
        delta <= 0
        or not values["coldTemperatureC"]
        <= values["mixedTemperatureC"]
        <= values["hotTemperatureC"]
    ):
        raise FeatureInputError(
            "Mixed outlet temperature must lie between the cold and hot supply temperatures."
        )
    thermodynamic_fraction = (values["mixedTemperatureC"] - values["coldTemperatureC"]) / delta
    return result(
        summary={
            "hotFlowLps": values["totalFlowLps"] * thermodynamic_fraction,
            "coldFlowLps": values["totalFlowLps"] * (1 - thermodynamic_fraction),
            "configuredHotShare": values["hotFraction"],
        },
        notes=[
            "Blend ratio follows sensible-heat balance with equal water heat capacities; the configured hot-share input is reported for comparison, not substituted for the temperature-derived fraction."
        ],
    )


@feature(
    "mepFixtures.pressureRequirement",
    "Pressure Requirement",
    part="mep",
    fields=[
        select(
            "fixtureType", "Fixture type", ["wc", "basin", "shower", "kitchenSink", "medicalOutlet"]
        ),
        number("minimumDynamicKpa", "Minimum dynamic outlet pressure", 100, unit="kPa", min=0),
        number("availableDynamicKpa", "Available dynamic outlet pressure", 180, unit="kPa", min=0),
    ],
    requires_project=False,
)
def pressure_requirement(ctx: FeatureContext, values: dict) -> dict:
    """Check available dynamic pressure at a fixture against its design requirement."""
    deficit = values["minimumDynamicKpa"] - values["availableDynamicKpa"]
    return result(
        summary={
            "fixtureType": values["fixtureType"],
            "pressureMarginKpa": -deficit,
            "passes": deficit <= 0,
        },
        notes=[
            "Minimum pressure is a fixture-specific design input; pressure at the outlet must include elevation and distribution losses."
        ],
    )


@feature(
    "mepFixtures.mountingHeight",
    "Mounting Height",
    part="mep",
    fields=[
        select(
            "fixtureType", "Fixture type", ["basin", "wc", "urinal", "showerControl", "accessory"]
        ),
        number("heightMm", "Mounting height above finished floor", 850, unit="mm", min=0),
        number("permittedMinimumMm", "Project minimum height", 700, unit="mm", min=0),
        number("permittedMaximumMm", "Project maximum height", 1000, unit="mm", min=0),
    ],
    requires_project=False,
)
def mounting_height(ctx: FeatureContext, values: dict) -> dict:
    """Validate a fixture mounting height against project limits."""
    if values["permittedMinimumMm"] > values["permittedMaximumMm"]:
        raise FeatureInputError("Project minimum mounting height must not exceed its maximum.")
    passes = values["permittedMinimumMm"] <= values["heightMm"] <= values["permittedMaximumMm"]
    return result(
        summary={
            "fixtureType": values["fixtureType"],
            "mountingHeightMm": values["heightMm"],
            "passes": passes,
        },
        notes=[
            "Heights are measured above finished floor; the specified band is project-configurable."
        ],
    )


@feature(
    "mepFixtures.wallSupport",
    "Wall Support",
    part="mep",
    fields=[
        number("fixtureMassKg", "Fixture mass", 35, unit="kg", min=0),
        number("contentsMassKg", "Contents or user design mass", 100, unit="kg", min=0),
        number("supportCount", "Number of supports", 2, min=1),
        number("loadFactor", "Load factor", 1.5, min=1),
        number("supportCapacityN", "Support allowable load", 1500, unit="N", min=1),
    ],
    requires_project=False,
)
def wall_support(ctx: FeatureContext, values: dict) -> dict:
    """Estimate vertical reaction per fixture support."""
    reaction = (
        (values["fixtureMassKg"] + values["contentsMassKg"])
        * 9.80665
        * values["loadFactor"]
        / int(values["supportCount"])
    )
    return result(
        summary={
            "reactionPerSupportN": reaction,
            "supportCapacityN": values["supportCapacityN"],
            "passes": reaction <= values["supportCapacityN"],
        },
        notes=[
            "Load is the entered fixture plus design mass multiplied by the entered load factor and shared equally; check substrate and anchor group resistance separately."
        ],
    )


@feature("mepFixtures.drainGrouping", "Drain Grouping", part="mep", requires_project=True)
def drain_grouping(ctx: FeatureContext, values: dict) -> dict:
    """Group project fixture counts by story for local drainage coordination."""
    groups: dict[str, list[str]] = {}
    for story in _fixture_stories(ctx):
        name = story.get("story", "")
        groups[name] = [
            fixture for fixture, count in story.get("fixtures", {}).items() if float(count) > 0
        ]
    rows = [
        {
            "story": story,
            "fixtureTypes": ", ".join(sorted(fixtures)),
            "connectedTypes": len(fixtures),
        }
        for story, fixtures in groups.items()
    ]
    return result(
        summary={
            "drainGroups": len(rows),
            "connectedFixtureTypes": sum(row["connectedTypes"] for row in rows),
        },
        tables=[
            table(
                "Fixture drain groups",
                [
                    ("story", "Story"),
                    ("fixtureTypes", "Fixture types"),
                    ("connectedTypes", "Connected types"),
                ],
                rows,
            )
        ],
        notes=[
            "Fixtures are grouped by their plumbing story; physical branch connectivity and trap locations are not present in the story-count data."
        ],
    )


@feature(
    "mepFixtures.wasteConnection",
    "Waste Connection",
    part="mep",
    fields=[
        select(
            "fixtureType", "Fixture type", ["wc", "basin", "shower", "kitchenSink", "floorDrain"]
        ),
        number("wasteDiameterMm", "Waste outlet diameter", 50, unit="mm", min=32),
        number("branchSlopePercent", "Branch slope", 2, unit="%", min=0.1),
        number("fixtureUnits", "Connected drainage units", 4, min=0.1),
    ],
    requires_project=False,
)
def waste_connection(ctx: FeatureContext, values: dict) -> dict:
    """Check the selected waste outlet size against the engine drainage capacity table."""
    from saengine.plumbing.drainage import drain_size

    required, capacity = drain_size(values["fixtureUnits"], values["branchSlopePercent"] / 100)
    adequate = (
        required is not None
        and values["wasteDiameterMm"] >= required
        and capacity is not None
        and capacity >= values["fixtureUnits"]
    )
    return result(
        summary={
            "fixtureType": values["fixtureType"],
            "requiredDiameterMm": required,
            "providedDiameterMm": values["wasteDiameterMm"],
            "passes": adequate,
        },
        notes=[
            "Drainage capacity uses the engine table at the entered branch slope; verify fixture outlet compatibility and venting."
        ],
    )


@feature(
    "mepFixtures.waterConnection",
    "Water Connection",
    part="mep",
    fields=[
        select(
            "fixtureType", "Fixture type", ["wc", "basin", "shower", "kitchenSink", "medicalOutlet"]
        ),
        number("flowLps", "Design flow per fixture", 0.12, unit="L/s", min=0),
        number("pipeDiameterMm", "Connection pipe internal diameter", 15, unit="mm", min=1),
        number("minimumPressureKpa", "Required pressure", 100, unit="kPa", min=0),
        number("availablePressureKpa", "Available pressure", 180, unit="kPa", min=0),
    ],
    requires_project=False,
)
def water_connection(ctx: FeatureContext, values: dict) -> dict:
    """Check water-connection velocity and available pressure."""
    area = 3.141592653589793 * (values["pipeDiameterMm"] / 1000) ** 2 / 4
    velocity = values["flowLps"] / 1000 / area
    return result(
        summary={
            "fixtureType": values["fixtureType"],
            "velocityMs": velocity,
            "pressurePasses": values["availablePressureKpa"] >= values["minimumPressureKpa"],
        },
        notes=[
            "Velocity is computed from the entered internal diameter and flow; friction and elevation losses must be deducted from the available pressure."
        ],
    )
