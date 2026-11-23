"""Architecture Environment - solar, daylight, energy, acoustics and indoor environment."""

from __future__ import annotations

import datetime as dt
import math
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
from saengine.features.architecture_common import require_arch, room_metrics


@feature(
    "architectureEnvironment.sunSettings",
    "Sun Settings",
    part="settings",
    fields=[
        number("latitude", "Latitude", 23.81, unit="°", min=-90, max=90),
        number("longitude", "Longitude", 90.41, unit="°", min=-180, max=180),
        text("date", "Date", "2026-06-21"),
        number("utcOffset", "UTC offset", 6, unit="h", min=-12, max=14),
    ],
)
def sun_settings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate site sun-study settings."""
    try:
        day = dt.date.fromisoformat(values["date"])
    except ValueError as error:
        raise FeatureInputError("Enter the date as YYYY-MM-DD.") from error
    return result(
        summary={
            "latitudeDeg": values["latitude"],
            "longitudeDeg": values["longitude"],
            "date": day.isoformat(),
            "utcOffsetH": values["utcOffset"],
        }
    )


@feature(
    "architectureEnvironment.shadowStudy",
    "Shadow Study",
    part="floorPlan",
    fields=[
        number("latitude", "Latitude", 23.81, unit="°", min=-90, max=90),
        number("longitude", "Longitude", 90.41, unit="°", min=-180, max=180),
        text("date", "Date", "2026-06-21"),
        number("utcOffset", "UTC offset", 6, unit="h", min=-12, max=14),
        number("height", "Building height", 20, unit="m", min=0),
    ],
)
def shadow_study(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate hourly seasonal-shadow positions at noon."""
    from saengine.environment.solar import local_time, sun_position

    try:
        day = dt.date.fromisoformat(values["date"])
    except ValueError as error:
        raise FeatureInputError("Enter the date as YYYY-MM-DD.") from error
    az, el = sun_position(
        values["latitude"], values["longitude"], local_time(day, 12, values["utcOffset"])
    )
    length = values["height"] / math.tan(math.radians(el)) if el > 0 else None
    return result(
        summary={"azimuthDeg": az, "elevationDeg": el, "shadowLengthM": length},
        notes=[
            "Geometric vertical shadow from the supplied height; surrounding massing is not included."
        ],
    )


@feature(
    "architectureEnvironment.solarExposure",
    "Solar Exposure",
    part="floorPlan",
    fields=[
        number("irradiance", "Direct irradiance", 800, unit="W/m²", min=0),
        number("exposureHours", "Annual equivalent hours", 1500, unit="h/year", min=0),
        number("area", "Facade area", 100, unit="m²", min=0),
    ],
)
def solar_exposure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate a facade's equivalent annual solar energy."""
    energy = values["irradiance"] * values["exposureHours"] * values["area"] / 1000
    return result(
        summary={
            "areaM2": values["area"],
            "annualExposureKwh": energy,
            "peakIrradianceWPerM2": values["irradiance"],
        }
    )


@feature(
    "architectureEnvironment.daylightFactor",
    "Daylight Factor",
    part="floorPlan",
    fields=[
        number("transmittance", "Glazing transmittance", 0.7, min=0, max=1),
        number("maintenance", "Maintenance factor", 0.9, min=0, max=1),
        number("reflectance", "Area-weighted reflectance", 0.5, min=0, max=0.99),
        number("frameShare", "Frame area share", 0.2, min=0, max=1),
    ],
)
def daylight_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run the engine room daylight calculation where project massing is available."""
    require_arch(ctx)
    try:
        from saengine.environment.service import daylight_study

        out = daylight_study(str(ctx.root))
    except Exception as error:
        raise FeatureInputError(f"Daylight data could not be calculated: {error}") from error
    if "problems" in out:
        raise FeatureInputError(out["problems"][0])
    rows = [
        {"room": r["room"], "dfPercent": r.get("df", 0.0), "windowAreaM2": r.get("windowArea", 0.0)}
        for r in out["rooms"]
    ]
    return result(
        summary={"roomCount": len(rows), "transmittance": values["transmittance"]},
        tables=[
            table(
                "Daylight factors",
                [
                    ("room", "Room"),
                    ("dfPercent", "Daylight factor", "%"),
                    ("windowAreaM2", "Glazed area", "m²"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureEnvironment.windowAreaRatio",
    "Window Area Ratio",
    part="floorPlan",
    fields=[
        number("glazedArea", "Glazed area", 20, unit="m²", min=0),
        number("roomFloorArea", "Room floor area", 100, unit="m²", min=0.01),
    ],
)
def window_area_ratio(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate window-to-floor area ratio."""
    ratio = values["glazedArea"] / values["roomFloorArea"]
    return result(summary={"windowAreaRatio": ratio, "windowAreaPercent": ratio * 100})


@feature(
    "architectureEnvironment.glareCheck",
    "Glare Check",
    part="floorPlan",
    fields=[
        number("sourceLuminance", "Source luminance", 5000, unit="cd/m²", min=0),
        number("backgroundLuminance", "Background luminance", 100, unit="cd/m²", min=0.001),
        number("solidAngle", "Solid angle", 0.01, unit="sr", min=0),
    ],
)
def glare_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate a simplified luminance-based glare screening index."""
    index = values["sourceLuminance"] ** 2 * values["solidAngle"] / values["backgroundLuminance"]
    return result(
        summary={
            "luminanceContrast": values["sourceLuminance"] / values["backgroundLuminance"],
            "screeningIndex": index,
        }
    )


@feature(
    "architectureEnvironment.siteOrientation",
    "Site Orientation",
    part="settings",
    fields=[
        number(
            "rotation",
            "Building rotation clockwise from true north",
            0,
            unit="°",
            min=-360,
            max=360,
        )
    ],
)
def site_orientation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record site rotation relative to true north."""
    return result(summary={"rotationDeg": values["rotation"]})


@feature(
    "architectureEnvironment.windExposure",
    "Wind Exposure",
    part="settings",
    fields=[
        number("referenceSpeed", "Reference wind speed", 8, unit="m/s", min=0),
        number("height", "Evaluation height", 10, unit="m", min=0.1),
        number("exponent", "Terrain exponent", 0.22, min=0, max=1),
    ],
)
def wind_exposure(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate mean wind speed at height using a power-law profile."""
    speed = values["referenceSpeed"] * (values["height"] / 10) ** values["exponent"]
    return result(summary={"meanSpeedMPerS": speed})


@feature(
    "architectureEnvironment.vegetation",
    "Vegetation",
    part="floorPlan",
    fields=[
        text("treeId", "Tree id", "TREE-001"),
        number("crownDiameter", "Crown diameter", 6, unit="m", min=0.1),
        number("height", "Tree height", 8, unit="m", min=0.1),
    ],
)
def vegetation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate landscaping tree crown area."""
    area = math.pi * (values["crownDiameter"] / 2) ** 2
    return result(
        summary={"treeId": values["treeId"], "crownAreaM2": area, "heightM": values["height"]}
    )


@feature(
    "architectureEnvironment.energyModel",
    "Energy Model",
    part="floorPlan",
    fields=[
        number("wallArea", "Opaque wall area", 500, unit="m²", min=0),
        number("wallU", "Wall U-value", 0.4, unit="W/m²K", min=0),
        number("windowArea", "Window area", 150, unit="m²", min=0),
        number("windowU", "Window U-value", 1.6, unit="W/m²K", min=0),
        number("volume", "Volume", 3000, unit="m³", min=0),
        number("airChanges", "Air changes", 0.5, unit="1/h", min=0),
    ],
)
def energy_model(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Build a steady-state envelope and ventilation heat-loss model."""
    fabric = values["wallArea"] * values["wallU"] + values["windowArea"] * values["windowU"]
    ventilation = 0.33 * values["volume"] * values["airChanges"]
    return result(
        summary={
            "fabricHeatLossWPerK": fabric,
            "ventilationHeatLossWPerK": ventilation,
            "totalHeatLossWPerK": fabric + ventilation,
        }
    )


@feature(
    "architectureEnvironment.thermalComfort",
    "Thermal Comfort",
    part="floorPlan",
    fields=[
        number("airTemperature", "Air temperature", 24, unit="°C"),
        number("radiantTemperature", "Mean radiant temperature", 24, unit="°C"),
        number("humidity", "Relative humidity", 50, unit="%", min=0, max=100),
        number("airSpeed", "Air speed", 0.1, unit="m/s", min=0),
    ],
)
def thermal_comfort(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate operative temperature and humidity comfort indicator."""
    operative = (values["airTemperature"] + values["radiantTemperature"]) / 2
    return result(
        summary={
            "operativeTemperatureC": operative,
            "relativeHumidityPercent": values["humidity"],
            "airSpeedMPerS": values["airSpeed"],
        },
        notes=[
            "Operative temperature is the simple mean of air and radiant temperatures; it is a screening indicator, not a PMV/PPD assessment."
        ],
    )


@feature(
    "architectureEnvironment.coolingLoadEstimate",
    "Cooling Load Estimate",
    part="floorPlan",
    fields=[
        number("floorArea", "Floor area", 1000, unit="m²", min=0.01),
        number("specificLoad", "Specific cooling load", 80, unit="W/m²", min=0),
    ],
)
def cooling_load_estimate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate peak cooling load from supplied area and specific load."""
    kw = values["floorArea"] * values["specificLoad"] / 1000
    return result(summary={"coolingLoadKw": kw, "specificLoadWPerM2": values["specificLoad"]})


@feature(
    "architectureEnvironment.heatingLoadEstimate",
    "Heating Load Estimate",
    part="floorPlan",
    fields=[
        number("heatLoss", "Heat-loss coefficient", 2500, unit="W/K", min=0),
        number("indoorTemperature", "Indoor temperature", 20, unit="°C"),
        number("outdoorTemperature", "Outdoor design temperature", -5, unit="°C"),
    ],
)
def heating_load_estimate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate steady-state design heat load."""
    kw = values["heatLoss"] * (values["indoorTemperature"] - values["outdoorTemperature"]) / 1000
    return result(summary={"heatingLoadKw": max(0.0, kw)})


@feature(
    "architectureEnvironment.envelopePerformance",
    "Envelope Performance",
    part="floorPlan",
    fields=[
        number("wallU", "Wall U-value", 0.4, unit="W/m²K", min=0),
        number("roofU", "Roof U-value", 0.25, unit="W/m²K", min=0),
        number("windowU", "Window U-value", 1.6, unit="W/m²K", min=0),
        number("airtightness", "Air leakage", 3.0, unit="m³/h/m²", min=0),
    ],
)
def envelope_performance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarize envelope U-values and airtightness."""
    return result(
        summary={
            "wallUValue": values["wallU"],
            "roofUValue": values["roofU"],
            "windowUValue": values["windowU"],
            "airtightness": values["airtightness"],
        }
    )


@feature(
    "architectureEnvironment.reverberationTime",
    "Reverberation Time",
    part="floorPlan",
    fields=[
        text("roomId", "Room id", ""),
        number("height", "Clear height", 3000, unit="mm", min=1),
        number("absorption", "Mean absorption area", 20, unit="m²", min=0.001),
    ],
)
def reverberation_time(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate Sabine reverberation time from room volume and absorption area."""
    arch = require_arch(ctx)
    rows = []
    for r in room_metrics(ctx, arch):
        if values["roomId"] and r["room"] != values["roomId"]:
            continue
        volume = r["netAreaM2"] * values["height"] / 1000
        rt = 0.161 * volume / values["absorption"]
        rows.append({"room": r["room"], "volumeM3": volume, "reverberationTimeS": rt})
    if not rows:
        raise FeatureInputError("No matching room was found.")
    return result(
        summary={"roomCount": len(rows)},
        tables=[
            table(
                "Reverberation time",
                [("room", "Room"), ("volumeM3", "Volume", "m³"), ("reverberationTimeS", "T", "s")],
                rows,
            )
        ],
    )


@feature(
    "architectureEnvironment.soundInsulation",
    "Sound Insulation",
    part="floorPlan",
    fields=[
        number("surfaceMass", "Surface mass", 200, unit="kg/m²", min=0),
        number("frequency", "Frequency", 500, unit="Hz", min=20),
    ],
)
def sound_insulation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate mass-law airborne sound insulation for a single leaf."""
    rw = 20 * math.log10(values["surfaceMass"] * values["frequency"]) - 47.2
    return result(
        summary={
            "estimatedRwDb": rw,
            "surfaceMassKgPerM2": values["surfaceMass"],
            "frequencyHz": values["frequency"],
        },
        notes=[
            "Indicative normal-incidence mass-law estimate; coincidence, sealing and construction details are omitted."
        ],
    )


@feature(
    "architectureEnvironment.noiseMapping",
    "Noise Mapping",
    part="floorPlan",
    fields=[
        number("sourceLevel", "Source level", 75, unit="dB", min=0),
        number("distance", "Source distance", 10, unit="m", min=0.1),
    ],
)
def noise_mapping(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate free-field point-source attenuation."""
    level = values["sourceLevel"] - 20 * math.log10(values["distance"])
    return result(summary={"levelAtPointDb": level, "distanceM": values["distance"]})


@feature(
    "architectureEnvironment.acousticPanels",
    "Acoustic Panels",
    part="floorPlan",
    fields=[
        number("area", "Wall or ceiling area", 100, unit="m²", min=0.01),
        number("targetAbsorption", "Target absorption area", 20, unit="m²", min=0),
        number("panelAbsorption", "Panel absorption coefficient", 0.8, min=0, max=1),
    ],
)
def acoustic_panels(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate acoustic-panel area required for a target absorption area."""
    area = (
        values["targetAbsorption"] / values["panelAbsorption"] if values["panelAbsorption"] else 0
    )
    return result(
        summary={
            "panelAreaM2": area,
            "coverPercentage": area / values["area"] * 100 if values["area"] else 0,
        }
    )


@feature(
    "architectureEnvironment.trafficNoise",
    "Traffic Noise",
    part="floorPlan",
    fields=[
        number("flow", "18-hour flow", 10000, unit="vehicles/18h", min=1),
        number("speed", "Mean speed", 50, unit="km/h", min=1),
        number("heavy", "Heavy-vehicle share", 10, unit="%", min=0),
        number("distance", "Distance from kerb", 20, unit="m", min=0.1),
    ],
)
def traffic_noise(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Screen traffic noise with the engine road-noise constants."""
    try:
        import json
        from pathlib import Path

        from saengine.environment.road_noise import road_level

        path = (
            Path(__file__).resolve().parents[1] / "library" / "data" / "environment-defaults.json"
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        k = data.get("roadNoise", data)
    except (OSError, ValueError, KeyError, TypeError):
        k = {
            "speedTerm": [33.0, 40.0, 500.0, -68.8],
            "basic": 0.0,
            "flowSlope": 10.0,
            "heavyFactor": 5.0,
            "gradientPerPercent": 0.2,
            "kerbOffset": 0.0,
            "referenceDistance": 13.5,
            "sourceHeight": 0.5,
            "facade": 2.5,
            "l10ToLaeq": -3.0,
        }
    level = road_level(
        values["flow"], values["speed"], values["heavy"], 0.0, values["distance"], 1.5, k
    )
    return result(
        summary={"l10DbA": level},
        notes=[
            "Indicative road-noise calculation; building screening and detailed ground effects are omitted."
        ],
    )


@feature(
    "architectureEnvironment.ventilationRate",
    "Ventilation Rate",
    part="floorPlan",
    fields=[
        text("roomId", "Room id", ""),
        number("airChanges", "Air changes", 1.0, unit="1/h", min=0),
        number("height", "Room height", 3000, unit="mm", min=1),
    ],
)
def ventilation_rate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate ventilation airflow from room volume."""
    arch = require_arch(ctx)
    rows = []
    for r in room_metrics(ctx, arch):
        if values["roomId"] and r["room"] != values["roomId"]:
            continue
        flow = r["netAreaM2"] * values["height"] / 1000 * values["airChanges"]
        rows.append(
            {
                "room": r["room"],
                "volumeM3": r["netAreaM2"] * values["height"] / 1000,
                "flowM3PerH": flow,
            }
        )
    if not rows:
        raise FeatureInputError("No matching room was found.")
    return result(
        summary={"roomCount": len(rows), "totalFlowM3PerH": sum(r["flowM3PerH"] for r in rows)},
        tables=[
            table(
                "Ventilation rates",
                [("room", "Room"), ("volumeM3", "Volume", "m³"), ("flowM3PerH", "Flow", "m³/h")],
                rows,
            )
        ],
    )


@feature(
    "architectureEnvironment.co2Levels",
    "CO2 Levels",
    part="floorPlan",
    fields=[
        number("outdoor", "Outdoor CO2", 420, unit="ppm", min=0),
        number("generation", "Occupant generation", 0.005, unit="l/s/person", min=0),
        number("occupants", "Occupant count", 20, unit="person", min=0),
        number("airFlow", "Outdoor-air flow", 200, unit="l/s", min=0),
    ],
)
def co2_levels(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate steady-state indoor CO2 rise under a mixing-zone model."""
    generation = values["generation"] * values["occupants"] * 1000
    rise = generation / (values["airFlow"] * 1000) * 1e6 if values["airFlow"] else float("inf")
    total = values["outdoor"] + rise if math.isfinite(rise) else values["outdoor"]
    return result(summary={"co2Ppm": total, "risePpm": rise if math.isfinite(rise) else None})


@feature(
    "architectureEnvironment.airChangeRate",
    "Air Change Rate",
    part="floorPlan",
    fields=[
        number("flow", "Airflow", 2000, unit="m³/h", min=0),
        number("volume", "Room or zone volume", 3000, unit="m³", min=0.01),
    ],
)
def air_change_rate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate air changes per hour."""
    ach = values["flow"] / values["volume"]
    return result(summary={"airChangesPerHour": ach})


@feature(
    "architectureEnvironment.pollutantSources",
    "Pollutant Sources",
    part="floorPlan",
    fields=[
        text("roomId", "Room id", ""),
        text("source", "Pollutant source", "Cleaning"),
        number("emission", "Emission rate", 1.0, unit="mg/h", min=0),
    ],
)
def pollutant_sources(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record pollutant sources and emission rates by room."""
    arch = require_arch(ctx)
    rooms = [r for r in arch.rooms if not values["roomId"] or r.id == values["roomId"]]
    if not rooms:
        raise FeatureInputError("No matching room was found.")
    rows = [
        {"room": r.id, "source": values["source"], "emissionMgPerH": values["emission"]}
        for r in rooms
    ]
    return result(
        summary={"sourceCount": len(rows)},
        tables=[
            table(
                "Pollutant sources",
                [("room", "Room"), ("source", "Source"), ("emissionMgPerH", "Emission", "mg/h")],
                rows,
            )
        ],
    )


@feature(
    "architectureEnvironment.naturalVentilation",
    "Natural Ventilation",
    part="floorPlan",
    fields=[
        number("openingArea", "Effective opening area", 4, unit="m²", min=0),
        number("windSpeed", "Wind speed", 3, unit="m/s", min=0),
        number("coefficient", "Discharge coefficient", 0.6, min=0, max=1),
    ],
)
def natural_ventilation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimate wind-driven natural ventilation airflow."""
    flow = values["coefficient"] * values["openingArea"] * values["windSpeed"] * 3600
    return result(summary={"flowM3PerH": flow})
