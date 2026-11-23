"""Lighting calculations, luminaire layouts and controls schedules."""

from __future__ import annotations

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


@feature(
    "mepLighting.lumenMethod",
    "Lumen Method",
    part="mep",
    fields=[
        number("areaM2", "Room area", 80, unit="m²", min=0.1),
        number("targetLux", "Target illuminance", 300, unit="lx", min=0),
        number("lumens", "Luminaire output", 4000, unit="lm", min=1),
        number("utilisation", "Utilisation factor", 0.65, min=0.01, max=1),
        number("maintenance", "Maintenance factor", 0.8, min=0.01, max=1),
    ],
    requires_project=False,
)
def lumen_method(ctx: FeatureContext, v: dict) -> dict:
    """Estimate luminaire count by the lumen method."""
    count = math.ceil(
        v["areaM2"] * v["targetLux"] / (v["lumens"] * v["utilisation"] * v["maintenance"])
    )
    return result(
        {
            "luminaireCount": count,
            "averageLux": count * v["lumens"] * v["utilisation"] * v["maintenance"] / v["areaM2"],
        },
        notes=[
            "Average illuminance method; uniformity, glare and point-by-point criteria need separate checks."
        ],
    )


@feature(
    "mepLighting.pointCalculation",
    "Point Calculation",
    part="mep",
    fields=[
        number("intensityCd", "Luminaire intensity", 1200, unit="cd", min=0),
        number("heightM", "Mounting height above plane", 2.5, unit="m", min=0.1),
        number("offsetM", "Horizontal offset", 1.5, unit="m", min=0),
    ],
    requires_project=False,
)
def point_calculation(ctx: FeatureContext, v: dict) -> dict:
    """Calculate direct illuminance at a horizontal point from a point source."""
    r2 = v["heightM"] ** 2 + v["offsetM"] ** 2
    lux = v["intensityCd"] * v["heightM"] / (r2**1.5)
    return result(
        {"directIlluminanceLux": lux, "slantDistanceM": math.sqrt(r2)},
        notes=[
            "Inverse-square point-source model with cosine incidence; interreflection and luminaire photometry are omitted."
        ],
    )


@feature(
    "mepLighting.daylightFactor",
    "Daylight Factor",
    part="mep",
    fields=[
        number("indoorLux", "Indoor illuminance", 150, unit="lx", min=0),
        number("exteriorLux", "Unobstructed exterior illuminance", 10000, unit="lx", min=1),
    ],
    requires_project=False,
)
def daylight_factor(ctx: FeatureContext, v: dict) -> dict:
    """Calculate daylight factor from simultaneous indoor and exterior illuminance."""
    return result(
        {"daylightFactorPercent": v["indoorLux"] / v["exteriorLux"] * 100},
        notes=[
            "Daylight factor is an overcast-sky ratio; it does not represent annual daylight availability."
        ],
    )


@feature(
    "mepLighting.lightFixtures",
    "Light Fixtures",
    part="mep",
    fields=[
        number("roomLengthM", "Room length", 10, unit="m", min=0.1),
        number("roomWidthM", "Room width", 8, unit="m", min=0.1),
        number("spacingM", "Luminaire spacing", 3, unit="m", min=0.1),
        text("fixtureType", "Fixture type", "LED panel"),
    ],
    requires_project=False,
)
def light_fixtures(ctx: FeatureContext, v: dict) -> dict:
    """Generate an even rectangular fixture coordinate grid."""
    nx, ny = math.ceil(v["roomLengthM"] / v["spacingM"]), math.ceil(v["roomWidthM"] / v["spacingM"])
    coords = [
        {
            "row": y + 1,
            "column": x + 1,
            "xM": (x + 0.5) * v["roomLengthM"] / nx,
            "yM": (y + 0.5) * v["roomWidthM"] / ny,
            "type": v["fixtureType"],
        }
        for y in range(ny)
        for x in range(nx)
    ]
    return result(
        {"fixtureCount": len(coords)},
        [
            table(
                "Proposed fixture locations",
                [
                    ("row", "Row"),
                    ("column", "Column"),
                    ("xM", "X", "m"),
                    ("yM", "Y", "m"),
                    ("type", "Type"),
                ],
                coords,
            )
        ],
        ["Even-grid layout proposal; check ceiling coordination and photometric distribution."],
    )


@feature(
    "mepLighting.switchingGroups",
    "Switching Groups",
    part="mep",
    fields=[
        number("luminaireCount", "Luminaire count", 16, min=1),
        number("groupSize", "Luminaires per group", 4, min=1),
    ],
    requires_project=False,
)
def switching_groups(ctx: FeatureContext, v: dict) -> dict:
    """Calculate switching group count and membership ranges."""
    n, size = int(v["luminaireCount"]), int(v["groupSize"])
    rows = [
        {
            "group": i + 1,
            "firstLuminaire": i * size + 1,
            "lastLuminaire": min((i + 1) * size, n),
            "count": min(size, n - i * size),
        }
        for i in range(math.ceil(n / size))
    ]
    return result(
        {"groupCount": len(rows)},
        [
            table(
                "Switching groups",
                [
                    ("group", "Group"),
                    ("firstLuminaire", "First"),
                    ("lastLuminaire", "Last"),
                    ("count", "Count"),
                ],
                rows,
            )
        ],
    )


@feature(
    "mepLighting.sensorPlacement",
    "Sensor Placement",
    part="mep",
    fields=[
        number("roomLengthM", "Room length", 12, unit="m", min=0.1),
        number("roomWidthM", "Room width", 8, unit="m", min=0.1),
        number("coverageRadiusM", "Sensor coverage radius", 5, unit="m", min=0.1),
    ],
    requires_project=False,
)
def sensor_placement(ctx: FeatureContext, v: dict) -> dict:
    """Estimate minimum occupancy sensor count by circular coverage area."""
    count = math.ceil(v["roomLengthM"] * v["roomWidthM"] / (math.pi * v["coverageRadiusM"] ** 2))
    return result(
        {"sensorCountEstimate": count, "roomAreaM2": v["roomLengthM"] * v["roomWidthM"]},
        notes=[
            "Area-based minimum; sensor field-of-view, mounting height and overlapping coverage require layout validation."
        ],
    )


@feature(
    "mepLighting.luxLevels",
    "Lux Levels",
    part="mep",
    fields=[
        number("calculatedLux", "Calculated illuminance", 320, unit="lx", min=0),
        number("requiredLux", "Required illuminance", 300, unit="lx", min=0),
    ],
    requires_project=False,
)
def lux_levels(ctx: FeatureContext, v: dict) -> dict:
    """Compare calculated illuminance with the entered room criterion."""
    return result(
        {
            "calculatedLux": v["calculatedLux"],
            "requiredLux": v["requiredLux"],
            "pass": v["calculatedLux"] >= v["requiredLux"],
            "marginLux": v["calculatedLux"] - v["requiredLux"],
        }
    )


@feature(
    "mepLighting.uniformityCheck",
    "Uniformity Check",
    part="mep",
    fields=[
        number("minimumLux", "Minimum illuminance", 180, unit="lx", min=0),
        number("averageLux", "Average illuminance", 300, unit="lx", min=0.1),
        number("minimumRatio", "Minimum-to-average criterion", 0.6, min=0, max=1),
    ],
    requires_project=False,
)
def uniformity_check(ctx: FeatureContext, v: dict) -> dict:
    """Check minimum-to-average illuminance uniformity."""
    ratio = v["minimumLux"] / v["averageLux"]
    return result(
        {
            "uniformityRatio": ratio,
            "minimumRatio": v["minimumRatio"],
            "pass": ratio >= v["minimumRatio"],
        },
        notes=[
            "Uniformity is minimum divided by average illuminance on the stated calculation plane."
        ],
    )


@feature(
    "mepLighting.energyCompliance",
    "Energy Compliance",
    part="mep",
    fields=[
        number("connectedPowerW", "Connected lighting power", 1800, unit="W", min=0),
        number("floorAreaM2", "Floor area", 80, unit="m²", min=0.1),
        number("limitWPerM2", "Power density limit", 8, unit="W/m²", min=0),
    ],
    requires_project=False,
)
def energy_compliance(ctx: FeatureContext, v: dict) -> dict:
    """Calculate lighting power density and compare with the entered limit."""
    lpd = v["connectedPowerW"] / v["floorAreaM2"]
    return result(
        {
            "powerDensityWPerM2": lpd,
            "limitWPerM2": v["limitWPerM2"],
            "pass": lpd <= v["limitWPerM2"],
        },
        notes=["The applicable project criterion must be supplied as an input."],
    )


@feature(
    "mepLighting.luminaireSchedule",
    "Luminaire Schedule",
    part="mep",
    fields=[
        text("type", "Luminaire type", "LED-600"),
        number("quantity", "Quantity", 20, min=0),
        number("wattageW", "Input power", 36, unit="W", min=0),
        number("mountingHeightM", "Mounting height", 3, unit="m", min=0),
    ],
    requires_project=False,
)
def luminaire_schedule(ctx: FeatureContext, v: dict) -> dict:
    """Prepare a luminaire schedule row and connected load."""
    return result(
        {"quantity": int(v["quantity"]), "connectedLoadW": v["quantity"] * v["wattageW"]},
        [
            table(
                "Luminaire schedule",
                [
                    ("type", "Type"),
                    ("quantity", "Quantity"),
                    ("wattageW", "Power", "W"),
                    ("mountingHeightM", "Height", "m"),
                ],
                [
                    {
                        "type": v["type"],
                        "quantity": int(v["quantity"]),
                        "wattageW": v["wattageW"],
                        "mountingHeightM": v["mountingHeightM"],
                    }
                ],
            )
        ],
    )


@feature(
    "mepLighting.lampTypes",
    "Lamp Types",
    part="mep",
    fields=[
        select("technology", "Lamp technology", ["LED", "fluorescent", "HID"]),
        number("ratedLifeHours", "Rated life", 50000, unit="h", min=1),
        number("wattageW", "Lamp power", 36, unit="W", min=0),
    ],
    requires_project=False,
)
def lamp_types(ctx: FeatureContext, v: dict) -> dict:
    """Summarize selected lamp technology and nameplate properties."""
    return result(
        {
            "technology": v["technology"],
            "ratedLifeHours": v["ratedLifeHours"],
            "wattageW": v["wattageW"],
        },
        notes=["Use manufacturer data for lumen maintenance and actual service life."],
    )


@feature(
    "mepLighting.lightOutputRatio",
    "Light Output Ratio",
    part="mep",
    fields=[
        number("lampLumens", "Lamp lumens", 5000, unit="lm", min=0),
        number("luminaireOutputLumens", "Luminaire output", 4000, unit="lm", min=0),
    ],
    requires_project=False,
)
def light_output_ratio(ctx: FeatureContext, v: dict) -> dict:
    """Calculate luminaire light output ratio from lamp and luminaire lumens."""
    if v["lampLumens"] == 0:
        raise FeatureInputError("Lamp lumens must be greater than zero.")
    return result(
        {
            "lightOutputRatio": v["luminaireOutputLumens"] / v["lampLumens"],
            "luminaireOutputLumens": v["luminaireOutputLumens"],
        }
    )


@feature(
    "mepLighting.mountingHeight",
    "Mounting Height",
    part="mep",
    fields=[
        number("mountingM", "Mounting height", 3, unit="m", min=0),
        number("workplaneM", "Workplane height", 0.8, unit="m", min=0),
    ],
    requires_project=False,
)
def mounting_height(ctx: FeatureContext, v: dict) -> dict:
    """Calculate luminaire height above the working plane."""
    if v["mountingM"] <= v["workplaneM"]:
        raise FeatureInputError("Mounting height must exceed working-plane height.")
    return result({"heightAboveWorkplaneM": v["mountingM"] - v["workplaneM"]})


@feature(
    "mepLighting.fixtureMaintenance",
    "Fixture Maintenance",
    part="mep",
    fields=[
        number("initialLux", "Initial illuminance", 400, unit="lx", min=0),
        number("maintenanceFactor", "Maintenance factor", 0.8, min=0, max=1),
    ],
    requires_project=False,
)
def fixture_maintenance(ctx: FeatureContext, v: dict) -> dict:
    """Apply a maintenance factor to initial illuminance."""
    return result(
        {
            "maintainedLux": v["initialLux"] * v["maintenanceFactor"],
            "lossLux": v["initialLux"] * (1 - v["maintenanceFactor"]),
        },
        notes=[
            "Maintenance factor combines dirt and lumen-depreciation effects supplied by the designer."
        ],
    )


@feature(
    "mepLighting.daylightSensors",
    "Daylight Sensors",
    part="mep",
    fields=[
        number("targetLux", "Target illuminance", 300, unit="lx", min=0),
        number("daylightLux", "Available daylight", 180, unit="lx", min=0),
        number("connectedPowerW", "Controlled lighting power", 500, unit="W", min=0),
    ],
    requires_project=False,
)
def daylight_sensors(ctx: FeatureContext, v: dict) -> dict:
    """Estimate the remaining electric-light output fraction under daylight dimming."""
    fraction = (
        min(1.0, max(0.0, (v["targetLux"] - v["daylightLux"]) / v["targetLux"]))
        if v["targetLux"]
        else 0
    )
    return result(
        {"outputFraction": fraction, "estimatedPowerW": fraction * v["connectedPowerW"]},
        notes=[
            "Linear daylight response is an idealized control curve; commissioning is needed to account for sensor calibration and daylight gradients."
        ],
    )


@feature(
    "mepLighting.dimmerZones",
    "Dimmer Zones",
    part="mep",
    fields=[
        number("fixtureCount", "Fixtures", 18, min=1),
        number("zoneCapacity", "Fixtures per zone", 6, min=1),
    ],
    requires_project=False,
)
def dimmer_zones(ctx: FeatureContext, v: dict) -> dict:
    """Calculate dimmer-zone count and fixture allocation."""
    n, cap = int(v["fixtureCount"]), int(v["zoneCapacity"])
    counts = [min(cap, n - i * cap) for i in range(math.ceil(n / cap))]
    return result(
        {"zoneCount": len(counts), "fixturesPerZoneMaximum": cap},
        [
            table(
                "Dimmer-zone allocations",
                [("zone", "Zone"), ("fixtureCount", "Fixtures")],
                [{"zone": i + 1, "fixtureCount": count} for i, count in enumerate(counts)],
            )
        ],
    )


@feature(
    "mepLighting.occupancySensors",
    "Occupancy Sensors",
    part="mep",
    fields=[
        number("roomAreaM2", "Room area", 120, unit="m²", min=0),
        number("coveragePerSensorM2", "Coverage per sensor", 60, unit="m²", min=0.1),
        number("holdMinutes", "Off-delay", 15, unit="min", min=0),
    ],
    requires_project=False,
)
def occupancy_sensors(ctx: FeatureContext, v: dict) -> dict:
    """Estimate sensor count and report the selected occupancy hold time."""
    return result(
        {
            "sensorCount": math.ceil(v["roomAreaM2"] / v["coveragePerSensorM2"]),
            "holdMinutes": v["holdMinutes"],
        },
        notes=[
            "Area-based count is only a planning estimate; sensor geometry and occupancy patterns govern placement."
        ],
    )


@feature(
    "mepLighting.timeScheduling",
    "Time Scheduling",
    part="mep",
    fields=[
        number("occupiedHours", "Occupied hours per day", 10, unit="h", min=0, max=24),
        number("daysPerYear", "Operating days", 250, unit="days/year", min=0, max=366),
        number("loadKw", "Lighting load", 5, unit="kW", min=0),
    ],
    requires_project=False,
)
def time_scheduling(ctx: FeatureContext, v: dict) -> dict:
    """Calculate scheduled annual lighting energy use."""
    return result(
        {
            "annualEnergyKwh": v["occupiedHours"] * v["daysPerYear"] * v["loadKw"],
            "annualOperatingHours": v["occupiedHours"] * v["daysPerYear"],
        }
    )


@feature(
    "mepLighting.sceneProgramming",
    "Scene Programming",
    part="mep",
    fields=[
        text("sceneName", "Scene name", "Presentation"),
        number("taskLevelPercent", "Task lighting level", 70, min=0, max=100),
        number("accentLevelPercent", "Accent lighting level", 40, min=0, max=100),
    ],
    requires_project=False,
)
def scene_programming(ctx: FeatureContext, v: dict) -> dict:
    """Represent a lighting scene as independent task and accent output levels."""
    return result(
        {
            "sceneName": v["sceneName"],
            "taskLevelPercent": v["taskLevelPercent"],
            "accentLevelPercent": v["accentLevelPercent"],
        },
        [
            table(
                "Scene channels",
                [("channel", "Channel"), ("levelPercent", "Output", "%")],
                [
                    {"channel": "Task", "levelPercent": v["taskLevelPercent"]},
                    {"channel": "Accent", "levelPercent": v["accentLevelPercent"]},
                ],
            )
        ],
    )


@feature(
    "mepLighting.poleLayout",
    "Pole Layout",
    part="mep",
    fields=[
        number("roadLengthM", "Road length", 200, unit="m", min=0),
        number("poleSpacingM", "Pole spacing", 30, unit="m", min=1),
        number("setbackM", "End setback", 5, unit="m", min=0),
    ],
    requires_project=False,
)
def pole_layout(ctx: FeatureContext, v: dict) -> dict:
    """Generate evenly spaced pole stations along a straight road."""
    n = max(0, math.floor((v["roadLengthM"] - 2 * v["setbackM"]) / v["poleSpacingM"]) + 1)
    rows = [{"pole": i + 1, "stationM": v["setbackM"] + i * v["poleSpacingM"]} for i in range(n)]
    return result(
        {"poleCount": n},
        [table("Pole stations", [("pole", "Pole"), ("stationM", "Station", "m")], rows)],
    )


@feature(
    "mepLighting.facadeLighting",
    "Facade Lighting",
    part="mep",
    fields=[
        number("facadeWidthM", "Facade width", 30, unit="m", min=0.1),
        number("fixtureSpacingM", "Fixture spacing", 5, unit="m", min=0.1),
        number("beamAngleDeg", "Beam angle", 30, unit="deg", min=1, max=179),
    ],
    requires_project=False,
)
def facade_lighting(ctx: FeatureContext, v: dict) -> dict:
    """Estimate facade fixture count and beam footprint at the target distance."""
    count = math.ceil(v["facadeWidthM"] / v["fixtureSpacingM"])
    footprint = 2 * v["fixtureSpacingM"] * math.tan(math.radians(v["beamAngleDeg"] / 2))
    return result(
        {"fixtureCount": count, "beamFootprintM": footprint},
        notes=[
            "Ideal conical beam approximation; photometric intensity distribution and overlap are not modelled."
        ],
    )


@feature(
    "mepLighting.floodlightAiming",
    "Floodlight Aiming",
    part="mep",
    fields=[
        number("mountHeightM", "Mounting height", 12, unit="m", min=0.1),
        number("targetDistanceM", "Target distance", 20, unit="m", min=0),
        number("tiltDeg", "Tilt from vertical", 35, unit="deg", min=0, max=89),
    ],
    requires_project=False,
)
def floodlight_aiming(ctx: FeatureContext, v: dict) -> dict:
    """Calculate aiming point and beam incidence geometry for a floodlight."""
    x = v["mountHeightM"] * math.tan(math.radians(v["tiltDeg"]))
    return result(
        {
            "horizontalAimM": x,
            "targetOffsetM": v["targetDistanceM"] - x,
            "slantDistanceM": v["mountHeightM"] / math.cos(math.radians(v["tiltDeg"])),
        },
        notes=[
            "Geometric aiming only; check glare, intensity distribution and target illuminance."
        ],
    )


@feature(
    "mepLighting.spillLightCheck",
    "Spill Light Check",
    part="mep",
    fields=[
        number("intensityCd", "Intensity toward boundary", 300, unit="cd", min=0),
        number("distanceM", "Boundary distance", 25, unit="m", min=0.1),
        number("limitLux", "Boundary illuminance limit", 5, unit="lx", min=0),
    ],
    requires_project=False,
)
def spill_light_check(ctx: FeatureContext, v: dict) -> dict:
    """Estimate illuminance at a neighboring boundary from a point source."""
    lux = v["intensityCd"] / v["distanceM"] ** 2
    return result(
        {"boundaryIlluminanceLux": lux, "limitLux": v["limitLux"], "pass": lux <= v["limitLux"]},
        notes=[
            "Point-source inverse-square estimate; actual aiming, shielding and multiple luminaires must be included."
        ],
    )


@feature(
    "mepLighting.skyGlowLimit",
    "Sky Glow Limit",
    part="mep",
    fields=[
        number("upwardFluxLm", "Upward luminous flux", 5000, unit="lm", min=0),
        number("totalFluxLm", "Total luminaire flux", 20000, unit="lm", min=0),
        number("limitPercent", "Upward flux limit", 5, unit="%", min=0, max=100),
    ],
    requires_project=False,
)
def sky_glow_limit(ctx: FeatureContext, v: dict) -> dict:
    """Compare the upward light output ratio with the entered project limit."""
    ratio = 100 * v["upwardFluxLm"] / v["totalFluxLm"] if v["totalFluxLm"] else 0
    return result(
        {
            "upwardFluxRatioPercent": ratio,
            "limitPercent": v["limitPercent"],
            "pass": ratio <= v["limitPercent"],
        },
        notes=[
            "Uses supplied photometric fluxes; environmental zone classification and reflected light are outside this calculation."
        ],
    )
