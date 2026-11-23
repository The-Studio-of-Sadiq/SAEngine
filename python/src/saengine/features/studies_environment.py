"""Studies Environment - solar, energy, comfort, carbon and outdoor exposure tools."""

from __future__ import annotations

import datetime as dt
import json
import math

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
    text,
)
from saengine.features.studies_common import numbers, records, write_json


def _pmv(
    air: float, radiant: float, speed: float, humidity: float, met: float, clo: float
) -> tuple[float, float]:
    """Fanger PMV and PPD for a homogeneous indoor environment."""
    m, work, icl = met * 58.15, 0.0, clo * 0.155
    fcl = 1 + 1.29 * icl if icl <= 0.078 else 1.05 + 0.645 * icl
    vapor = humidity * 10 * math.exp(16.6536 - 4030.183 / (air + 235))
    taa, tra = air + 273, radiant + 273
    tcla = taa + (35.5 - air) / (3.5 * (6.45 * icl + 0.1))
    p1, p2 = icl * fcl, 3.96 * icl * fcl
    p3, p4, p5 = 100 * p1, p1 * taa, 308.7 - 0.028 * (m - work) + p2 * (tra / 100) ** 4
    xn, xf = tcla / 100, tcla / 50
    for _ in range(150):
        xf = (xf + xn) / 2
        hcn = 2.38 * abs(100 * xf - taa) ** 0.25
        hc = max(12.1 * math.sqrt(max(speed, 0)), hcn)
        xn = (p5 + p4 * hc - p2 * xf**4) / (100 + p3 * hc)
        if abs(xn - xf) <= 0.00015:
            break
    tcl = 100 * xn - 273
    hc = max(12.1 * math.sqrt(max(speed, 0)), 2.38 * abs(tcl - air) ** 0.25)
    load = (
        m
        - work
        - 3.05e-3 * (5733 - 6.99 * (m - work) - vapor)
        - 0.42 * (m - work - 58.15)
        - 1.7e-5 * m * (5867 - vapor)
        - 0.0014 * m * (34 - air)
        - 3.96e-8 * fcl * ((tcl + 273) ** 4 - (radiant + 273) ** 4)
        - fcl * hc * (tcl - air)
    )
    pmv = (0.303 * math.exp(-0.036 * m) + 0.028) * load
    ppd = 100 - 95 * math.exp(-0.03353 * pmv**4 - 0.2179 * pmv**2)
    return pmv, ppd


@feature(
    "studiesEnvironment.solarPath",
    "Solar Path",
    part="settings",
    fields=[
        number("latitude", "Latitude", 23.81, unit="°", min=-90, max=90),
        number("longitude", "Longitude", 90.41, unit="°", min=-180, max=180),
        text("date", "Local date", "2026-06-21"),
        number("utcOffset", "UTC offset", 6, unit="h", min=-12, max=14),
        number("stepMinutes", "Time step", 60, unit="min", min=5, max=180),
    ],
    requires_project=False,
)
def solar_path(ctx: FeatureContext, values: dict) -> dict:
    """Calculate above-horizon solar azimuth and elevation through the selected local day."""
    try:
        day = dt.date.fromisoformat(values["date"])
    except ValueError as error:
        raise FeatureInputError("Enter the date as YYYY-MM-DD.") from error
    from saengine.environment.solar import sun_path

    points = sun_path(
        values["latitude"], values["longitude"], day, values["utcOffset"], values["stepMinutes"]
    )
    return result(
        summary={"sunUpSamples": len(points), "date": day.isoformat()},
        tables=[
            table(
                "Solar path",
                [
                    ("time", "Local time"),
                    ("azimuth", "Azimuth", "°"),
                    ("elevation", "Elevation", "°"),
                ],
                points,
            )
        ],
        notes=[
            "Solar position follows the engine's NOAA/Meeus equations; atmospheric refraction is omitted."
        ],
    )


@feature(
    "studiesEnvironment.shadowRange",
    "Shadow Range",
    part="settings",
    fields=[
        number("latitude", "Latitude", 23.81, unit="°", min=-90, max=90),
        number("longitude", "Longitude", 90.41, unit="°", min=-180, max=180),
        number("height", "Obstruction height", 20, unit="m", min=0),
        number("utcOffset", "UTC offset", 6, unit="h", min=-12, max=14),
    ],
    requires_project=False,
)
def shadow_range(ctx: FeatureContext, values: dict) -> dict:
    """Estimate noon shadow length at seasonal solstices and equinoxes from solar elevation."""
    from saengine.environment.solar import local_time, sun_position

    dates = [
        dt.date(2026, 3, 20),
        dt.date(2026, 6, 21),
        dt.date(2026, 9, 22),
        dt.date(2026, 12, 21),
    ]
    rows = []
    for day in dates:
        azimuth, elevation = sun_position(
            values["latitude"], values["longitude"], local_time(day, 12, values["utcOffset"])
        )
        length = values["height"] / math.tan(math.radians(elevation)) if elevation > 0 else None
        rows.append(
            {
                "date": day.isoformat(),
                "azimuth": azimuth,
                "elevation": elevation,
                "shadowLength": length,
            }
        )
    usable = [row["shadowLength"] for row in rows if row["shadowLength"] is not None]
    return result(
        summary={
            "minimumShadowLengthM": min(usable) if usable else None,
            "maximumShadowLengthM": max(usable) if usable else None,
        },
        tables=[
            table(
                "Seasonal noon shadow lengths",
                [
                    ("date", "Date"),
                    ("azimuth", "Azimuth", "°"),
                    ("elevation", "Elevation", "°"),
                    ("shadowLength", "Horizontal length", "m"),
                ],
                rows,
            )
        ],
        notes=[
            "Flat-ground geometric shadows at local clock noon for representative seasonal dates; terrain and nearby obstructions are excluded."
        ],
    )


@feature(
    "studiesEnvironment.irradiance",
    "Irradiance",
    part="settings",
    fields=[
        number("dni", "Direct normal irradiance", 800, unit="W/m²", min=0),
        number("dhi", "Diffuse horizontal irradiance", 100, unit="W/m²", min=0),
        number("sunAzimuth", "Sun azimuth", 180, unit="°", min=0, max=360),
        number("sunElevation", "Sun elevation", 45, unit="°", min=0, max=90),
        number("surfaceAzimuth", "Surface azimuth", 180, unit="°", min=0, max=360),
        number("tilt", "Surface tilt", 30, unit="°", min=0, max=180),
        number("albedo", "Ground albedo", 0.2, min=0, max=1),
    ],
    requires_project=False,
)
def irradiance(ctx: FeatureContext, values: dict) -> dict:
    """Resolve direct, isotropic-sky diffuse and ground-reflected irradiance on a tilted plane."""
    tilt, elevation = math.radians(values["tilt"]), math.radians(values["sunElevation"])
    delta = math.radians(values["sunAzimuth"] - values["surfaceAzimuth"])
    cosine = math.sin(elevation) * math.cos(tilt) + math.cos(elevation) * math.sin(tilt) * math.cos(
        delta
    )
    beam = values["dni"] * max(0.0, cosine)
    sky = values["dhi"] * (1 + math.cos(tilt)) / 2
    ground = (
        (values["dni"] * max(0.0, math.sin(elevation)) + values["dhi"])
        * values["albedo"]
        * (1 - math.cos(tilt))
        / 2
    )
    return result(
        summary={
            "beamWPerM2": beam,
            "skyDiffuseWPerM2": sky,
            "groundReflectedWPerM2": ground,
            "globalTiltedWPerM2": beam + sky + ground,
        },
        notes=[
            "Isotropic sky and uniform ground-reflection transposition; circumsolar brightening and horizon effects are omitted."
        ],
    )


@feature(
    "studiesEnvironment.energyModel",
    "Energy Model",
    part="mep",
    fields=[
        number("floorArea", "Conditioned floor area", 1000, unit="m²", min=0.1),
        number("wallArea", "Opaque wall area", 500, unit="m²", min=0),
        number("wallU", "Wall heat transfer coefficient", 0.4, unit="W/m²K", min=0),
        number("windowArea", "Window area", 150, unit="m²", min=0),
        number("windowU", "Window heat transfer coefficient", 1.6, unit="W/m²K", min=0),
        number("volume", "Conditioned volume", 3000, unit="m³", min=0),
        number("airChanges", "Air changes per hour", 0.5, unit="1/h", min=0),
    ],
    requires_project=False,
)
def energy_model(ctx: FeatureContext, values: dict) -> dict:
    """Assemble envelope and ventilation heat-loss coefficients from room-zone aggregates."""
    fabric = values["wallArea"] * values["wallU"] + values["windowArea"] * values["windowU"]
    ventilation = 0.33 * values["volume"] * values["airChanges"]
    return result(
        summary={
            "floorAreaM2": values["floorArea"],
            "fabricHeatLossWPerK": fabric,
            "ventilationHeatLossWPerK": ventilation,
            "totalHeatLossWPerK": fabric + ventilation,
            "heatLossPerAreaWPerM2K": (fabric + ventilation) / values["floorArea"],
        },
        tables=[
            table(
                "Heat-loss paths",
                [("path", "Path"), ("heatLoss", "Heat-loss coefficient", "W/K")],
                [
                    {"path": "Opaque wall", "heatLoss": values["wallArea"] * values["wallU"]},
                    {"path": "Windows", "heatLoss": values["windowArea"] * values["windowU"]},
                    {"path": "Ventilation", "heatLoss": ventilation},
                ],
            )
        ],
        notes=[
            "Steady-state zone balance; ventilation heat capacity uses 0.33 W·h/m³K for air. Thermal bridges, solar gains and thermal mass are not included."
        ],
    )


@feature(
    "studiesEnvironment.hvacProfiles",
    "HVAC Profiles",
    part="mep",
    fields=[
        text(
            "hourlySetpoints",
            "24 hourly temperature setpoints, °C",
            "20,20,20,20,20,20,20,21,21,21,21,21,21,21,21,21,21,21,21,21,20,20,20,20",
        ),
        number("designTemperature", "Outdoor design temperature", 5, unit="°C"),
        number("heatLoss", "Zone heat-loss coefficient", 2500, unit="W/K", min=0),
    ],
    requires_project=False,
)
def hvac_profiles(ctx: FeatureContext, values: dict) -> dict:
    """Convert an hourly zone setpoint profile to the corresponding design heat-load curve."""
    setpoints = numbers(values["hourlySetpoints"], "hourly setpoints")
    if len(setpoints) != 24:
        raise FeatureInputError("Provide exactly 24 hourly setpoints.")
    rows = [
        {
            "hour": hour,
            "setpointC": temp,
            "heatingLoadKw": max(
                0.0, values["heatLoss"] * (temp - values["designTemperature"]) / 1000
            ),
        }
        for hour, temp in enumerate(setpoints)
    ]
    return result(
        summary={
            "peakHeatingLoadKw": max(row["heatingLoadKw"] for row in rows),
            "dailyHeatingEnergyKwh": sum(row["heatingLoadKw"] for row in rows),
        },
        tables=[
            table(
                "Hourly HVAC profile",
                [
                    ("hour", "Hour"),
                    ("setpointC", "Setpoint", "°C"),
                    ("heatingLoadKw", "Ideal heating load", "kW"),
                ],
                rows,
            )
        ],
        notes=[
            "Ideal sensible heating load at constant heat-loss coefficient; plant cycling, gains and controls are omitted."
        ],
    )


@feature(
    "studiesEnvironment.renewables",
    "Renewables",
    part="mep",
    fields=[
        number("pvArea", "Photovoltaic area", 250, unit="m²", min=0),
        number("irradiation", "Annual irradiation", 1500, unit="kWh/m²/year", min=0),
        number("pvEfficiency", "Module efficiency", 0.2, min=0, max=1),
        number("performanceRatio", "System performance ratio", 0.8, min=0, max=1),
        number("heatDemand", "Annual heat demand", 120000, unit="kWh/year", min=0),
        number("heatPumpCop", "Seasonal heat-pump COP", 3, min=0.1),
        number("electricityDemand", "Annual electricity demand", 90000, unit="kWh/year", min=0),
    ],
    requires_project=False,
)
def renewables(ctx: FeatureContext, values: dict) -> dict:
    """Size annual photovoltaic yield and heat-pump electricity from supplied demand and weather."""
    pv = (
        values["pvArea"]
        * values["irradiation"]
        * values["pvEfficiency"]
        * values["performanceRatio"]
    )
    hp = values["heatDemand"] / values["heatPumpCop"]
    return result(
        summary={
            "pvGenerationKwhPerYear": pv,
            "heatPumpElectricityKwhPerYear": hp,
            "annualElectricityDemandKwh": values["electricityDemand"] + hp,
            "netElectricityKwhPerYear": pv - values["electricityDemand"] - hp,
        },
        notes=[
            "Annual area × irradiation × efficiency × performance ratio for PV; heat-pump use is heat demand divided by seasonal COP. No hourly self-consumption or storage is modeled."
        ],
    )


@feature(
    "studiesEnvironment.energySimulation",
    "Energy Simulation",
    part="mep",
    fields=[
        number("heatLoss", "Heat-loss coefficient", 2500, unit="W/K", min=0),
        number("heatingDegreeDays", "Heating degree days", 1800, unit="K·day", min=0),
        number("internalGains", "Useful annual internal gains", 15000, unit="kWh/year", min=0),
        number("solarGains", "Useful annual solar gains", 8000, unit="kWh/year", min=0),
        number("systemEfficiency", "Seasonal system efficiency", 0.9, min=0.01, max=1),
    ],
    requires_project=False,
)
def energy_simulation(ctx: FeatureContext, values: dict) -> dict:
    """Estimate annual space-heating fuel from degree days, heat loss and useful gains."""
    gross = values["heatLoss"] * values["heatingDegreeDays"] * 24 / 1000
    useful = max(0.0, gross - values["internalGains"] - values["solarGains"])
    delivered = useful / values["systemEfficiency"]
    return result(
        summary={
            "grossSpaceHeatKwh": gross,
            "usefulSpaceHeatKwh": useful,
            "deliveredEnergyKwh": delivered,
        },
        notes=[
            "Seasonal degree-day heat balance with gains subtracted before dividing by system efficiency; this is a screening estimate, not an hourly simulation."
        ],
    )


@feature(
    "studiesEnvironment.tariffs",
    "Tariffs",
    part="mep",
    fields=[
        number("electricity", "Electricity tariff", 0.15, unit="currency/kWh", min=0),
        number("gas", "Gas tariff", 0.06, unit="currency/kWh", min=0),
        number("electricityUse", "Annual electricity use", 90000, unit="kWh/year", min=0),
        number("gasUse", "Annual gas use", 120000, unit="kWh/year", min=0),
        number("fixedCharge", "Annual fixed charges", 1800, unit="currency/year", min=0),
    ],
    requires_project=False,
)
def tariffs(ctx: FeatureContext, values: dict) -> dict:
    """Calculate annual energy charges by fuel and the combined bill."""
    electric = values["electricity"] * values["electricityUse"]
    gas = values["gas"] * values["gasUse"]
    return result(
        summary={
            "electricityCharge": electric,
            "gasCharge": gas,
            "fixedCharges": values["fixedCharge"],
            "annualBill": electric + gas + values["fixedCharge"],
        },
        tables=[
            table(
                "Tariff bill",
                [
                    ("fuel", "Fuel"),
                    ("use", "Use", "kWh/year"),
                    ("rate", "Rate", "currency/kWh"),
                    ("charge", "Charge", "currency/year"),
                ],
                [
                    {
                        "fuel": "Electricity",
                        "use": values["electricityUse"],
                        "rate": values["electricity"],
                        "charge": electric,
                    },
                    {"fuel": "Gas", "use": values["gasUse"], "rate": values["gas"], "charge": gas},
                ],
            )
        ],
        notes=[
            "The calculation applies flat unit rates; standing charges are added once for the year."
        ],
    )


@feature(
    "studiesEnvironment.loadProfiles",
    "Load Profiles",
    part="mep",
    fields=[
        text(
            "hourlyMultipliers",
            "24 hourly demand multipliers",
            "0.4,0.35,0.3,0.3,0.35,0.5,0.7,0.9,1,1,1,0.95,0.9,0.9,0.95,1,1,1,0.95,0.85,0.7,0.6,0.5,0.45",
        ),
        number("dailyEnergy", "Daily reference energy", 1000, unit="kWh/day", min=0),
    ],
    requires_project=False,
)
def load_profiles(ctx: FeatureContext, values: dict) -> dict:
    """Normalize hourly multipliers and allocate the specified daily energy over a day."""
    multipliers = numbers(values["hourlyMultipliers"], "hourly multipliers")
    if len(multipliers) != 24 or any(x < 0 for x in multipliers) or sum(multipliers) <= 0:
        raise FeatureInputError("Provide 24 non-negative hourly multipliers with a positive sum.")
    rows = [
        {
            "hour": hour,
            "multiplier": factor,
            "energyKwh": values["dailyEnergy"] * factor / sum(multipliers),
        }
        for hour, factor in enumerate(multipliers)
    ]
    return result(
        summary={
            "dailyEnergyKwh": sum(row["energyKwh"] for row in rows),
            "peakHour": max(rows, key=lambda row: row["energyKwh"])["hour"],
            "peakHourEnergyKwh": max(row["energyKwh"] for row in rows),
        },
        tables=[
            table(
                "Hourly load profile",
                [("hour", "Hour"), ("multiplier", "Relative load"), ("energyKwh", "Energy", "kWh")],
                rows,
            )
        ],
        notes=[
            "The input profile shape is normalized so the hourly allocations sum to the specified daily energy."
        ],
    )


@feature(
    "studiesEnvironment.glareAnalysis",
    "Glare Analysis",
    part="mep",
    fields=[
        number("sourceLuminance", "Bright source luminance", 5000, unit="cd/m²", min=0),
        number("backgroundLuminance", "Background luminance", 100, unit="cd/m²", min=0.001),
        number("solidAngle", "Source solid angle", 0.01, unit="sr", min=0),
        number("positionIndex", "Source position index", 1, min=0.1),
        number("adaptationLuminance", "Adaptation luminance", 100, unit="cd/m²", min=0.001),
    ],
    requires_project=False,
)
def glare_analysis(ctx: FeatureContext, values: dict) -> dict:
    """Calculate a source-to-background glare index from luminance, solid angle and position."""
    contrast = values["sourceLuminance"] / values["backgroundLuminance"]
    index = (values["sourceLuminance"] ** 2 * values["solidAngle"]) / (
        values["backgroundLuminance"] * values["positionIndex"] ** 2
    )
    return result(
        summary={
            "luminanceContrast": contrast,
            "sourceGlareIndex": index,
            "adaptationLuminanceCdPerM2": values["adaptationLuminance"],
        },
        notes=[
            "This reports a simplified luminance contrast source index. It is not a daylight glare probability calculation and does not infer occupant view geometry."
        ],
    )


@feature(
    "studiesEnvironment.thermalComfort",
    "Thermal Comfort",
    part="mep",
    fields=[
        number("airTemperature", "Air temperature", 24, unit="°C", min=-30, max=60),
        number(
            "meanRadiantTemperature", "Mean radiant temperature", 25, unit="°C", min=-30, max=60
        ),
        number("airSpeed", "Air speed", 0.1, unit="m/s", min=0, max=5),
        number("relativeHumidity", "Relative humidity", 50, unit="%", min=0, max=100),
        number("metabolicRate", "Metabolic rate", 1.2, unit="met", min=0.1, max=5),
        number("clothing", "Clothing insulation", 0.6, unit="clo", min=0, max=3),
    ],
    requires_project=False,
)
def thermal_comfort(ctx: FeatureContext, values: dict) -> dict:
    """Compute Fanger predicted mean vote and percentage dissatisfied for one indoor condition."""
    if values["relativeHumidity"] == 0:
        raise FeatureInputError(
            "Relative humidity must be greater than zero for the comfort model."
        )
    pmv, ppd = _pmv(
        values["airTemperature"],
        values["meanRadiantTemperature"],
        values["airSpeed"],
        values["relativeHumidity"],
        values["metabolicRate"],
        values["clothing"],
    )
    return result(
        summary={"pmv": pmv, "ppdPercent": ppd},
        notes=[
            "Fanger heat-balance model for a uniform, steady-state environment; local discomfort, adaptation and transient effects are not represented."
        ],
    )


@feature(
    "studiesEnvironment.pedestrianWind",
    "Pedestrian Wind",
    part="settings",
    fields=[
        number("referenceSpeed", "Reference mean wind speed", 8, unit="m/s", min=0),
        number("height", "Pedestrian evaluation height", 1.5, unit="m", min=0.1),
        number("referenceHeight", "Reference height", 10, unit="m", min=0.1),
        number("exponent", "Exposure exponent", 0.22, min=0, max=1),
        number("comfortLimit", "User comfort limit", 5, unit="m/s", min=0),
        number("gustFactor", "Gust factor", 1.5, min=1, max=5),
    ],
    requires_project=False,
)
def pedestrian_wind(ctx: FeatureContext, values: dict) -> dict:
    """Estimate mean and gust speed at pedestrian height using a power-law exposure profile."""
    mean = (
        values["referenceSpeed"]
        * (values["height"] / values["referenceHeight"]) ** values["exponent"]
    )
    gust = mean * values["gustFactor"]
    return result(
        summary={
            "meanSpeedMPerS": mean,
            "estimatedGustMPerS": gust,
            "comfortLimitMPerS": values["comfortLimit"],
            "exceedsComfortLimit": mean > values["comfortLimit"],
        },
        notes=[
            "Power-law terrain reduction and supplied gust factor; building downwash, corner acceleration and annual frequency of occurrence are not modeled."
        ],
    )


@feature(
    "studiesEnvironment.operationalCarbon",
    "Operational Carbon",
    part="mep",
    fields=[
        number("electricity", "Annual electricity", 90000, unit="kWh/year", min=0),
        number("electricityFactor", "Electricity factor", 0.45, unit="kg CO2e/kWh", min=0),
        number("gas", "Annual fuel gas", 120000, unit="kWh/year", min=0),
        number("gasFactor", "Gas factor", 0.2, unit="kg CO2e/kWh", min=0),
        number("floorArea", "Gross floor area", 5000, unit="m²", min=0.1),
    ],
    requires_project=False,
)
def operational_carbon(ctx: FeatureContext, values: dict) -> dict:
    """Estimate annual operational emissions by fuel and report floor-area intensity."""
    electric, gas = (
        values["electricity"] * values["electricityFactor"],
        values["gas"] * values["gasFactor"],
    )
    total = electric + gas
    return result(
        summary={
            "electricityCarbonKgCo2e": electric,
            "gasCarbonKgCo2e": gas,
            "totalCarbonKgCo2e": total,
            "intensityKgCo2ePerM2": total / values["floorArea"],
        },
        notes=[
            "Operational emissions use user-supplied energy factors and floor area; refrigerants and upstream fuel emissions are excluded unless included in those factors."
        ],
    )


@feature(
    "studiesEnvironment.energyBenchmark",
    "Energy Benchmark",
    part="mep",
    fields=[
        number("annualEnergy", "Annual delivered energy", 750000, unit="kWh/year", min=0),
        number("floorArea", "Gross floor area", 5000, unit="m²", min=0.1),
        number("referenceIntensity", "Reference intensity", 160, unit="kWh/m²/year", min=0),
        text("benchmarkName", "Benchmark source", "Project target"),
    ],
    requires_project=False,
)
def energy_benchmark(ctx: FeatureContext, values: dict) -> dict:
    """Compare modeled energy intensity with a user-supplied reference intensity."""
    intensity = values["annualEnergy"] / values["floorArea"]
    return result(
        summary={
            "energyIntensityKwhPerM2": intensity,
            "referenceIntensityKwhPerM2": values["referenceIntensity"],
            "differenceKwhPerM2": intensity - values["referenceIntensity"],
            "ratioToReference": intensity / values["referenceIntensity"]
            if values["referenceIntensity"]
            else None,
        },
        notes=[
            f"Reference is the supplied benchmark '{values['benchmarkName']}'; this tool does not select a building-type database or compliance threshold."
        ],
    )


@feature(
    "studiesEnvironment.retrofitOptions",
    "Retrofit Options",
    part="mep",
    fields=[
        number("capitalCost", "Retrofit capital cost", 200000, unit="currency", min=0),
        number("annualSavings", "Annual energy cost savings", 30000, unit="currency/year", min=0),
        number("life", "Measure life", 20, unit="year", min=1, max=100),
        number("discountRate", "Discount rate", 0.05, min=0, max=1),
    ],
    requires_project=False,
)
def retrofit_options(ctx: FeatureContext, values: dict) -> dict:
    """Calculate simple payback and net present value of constant annual retrofit savings."""
    payback = (
        values["capitalCost"] / values["annualSavings"] if values["annualSavings"] else math.inf
    )
    rate, life = values["discountRate"], int(values["life"])
    pv = (
        values["annualSavings"] * life
        if rate == 0
        else values["annualSavings"] * (1 - (1 + rate) ** -life) / rate
    )
    return result(
        summary={
            "simplePaybackYears": payback,
            "presentValueSavings": pv,
            "netPresentValue": pv - values["capitalCost"],
        },
        notes=[
            "Annual savings are constant and received at each year-end; maintenance, energy-price changes and residual value are excluded."
        ],
    )


@feature(
    "studiesEnvironment.daylightFactor",
    "Daylight Factor",
    part="mep",
    fields=[
        number("glazingArea", "Net glazing area", 18, unit="m²", min=0),
        number("transmittance", "Diffuse glazing transmittance", 0.65, min=0, max=1),
        number("skyAngle", "Visible sky angle", 55, unit="°", min=0, max=90),
        number("maintenance", "Maintenance factor", 0.9, min=0, max=1),
        number("surfaceArea", "Room internal surface area", 240, unit="m²", min=0.1),
        number("reflectance", "Area-weighted reflectance", 0.5, min=0, max=0.99),
    ],
    requires_project=False,
)
def daylight_factor(ctx: FeatureContext, values: dict) -> dict:
    """Estimate average daylight factor using the engine's area-based room formula."""
    from saengine.environment.daylight import average_daylight_factor

    df = average_daylight_factor(
        values["glazingArea"],
        values["skyAngle"],
        values["surfaceArea"],
        values["transmittance"] * values["maintenance"],
        1.0,
        values["reflectance"],
    )
    return result(
        summary={"averageDaylightFactorPercent": df},
        notes=[
            "Area-based diffuse daylight factor: glazing transmittance × glazed area × visible sky angle × maintenance / (room surface area × (1 − reflectance²)); direct sun is excluded."
        ],
    )


@feature(
    "studiesEnvironment.noiseMap",
    "Noise Map",
    part="mep",
    fields=[
        text(
            "receivers",
            "Receiver distances and coordinates",
            '[{"id":"R1","x":0,"y":0,"distanceM":20},{"id":"R2","x":10,"y":0,"distanceM":40}]',
        ),
        number("sourceLevel", "Source level at 1 m", 90, unit="dB(A)"),
        number("referenceDistance", "Reference distance", 1, unit="m", min=0.1),
        number("barrierAttenuation", "Measured barrier attenuation", 0, unit="dB", min=0),
    ],
    requires_project=False,
)
def noise_map(ctx: FeatureContext, values: dict) -> dict:
    """Map receiver sound levels from a supplied reference level with point-source distance loss."""
    receivers = records(values["receivers"], "noise receivers")
    rows = []
    for receiver in receivers:
        try:
            distance = float(receiver["distanceM"])
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError("Each receiver needs a numeric distanceM.") from error
        if distance <= 0:
            raise FeatureInputError("Receiver distances must be positive.")
        level = (
            values["sourceLevel"]
            - 20 * math.log10(distance / values["referenceDistance"])
            - values["barrierAttenuation"]
        )
        rows.append(
            {
                "receiver": receiver.get("id", "Receiver"),
                "x": receiver.get("x"),
                "y": receiver.get("y"),
                "distanceM": distance,
                "levelDbA": level,
            }
        )
    return result(
        summary={
            "receiverCount": len(rows),
            "maximumLevelDbA": max(row["levelDbA"] for row in rows),
        },
        tables=[
            table(
                "Receiver noise levels",
                [
                    ("receiver", "Receiver"),
                    ("x", "X"),
                    ("y", "Y"),
                    ("distanceM", "Distance", "m"),
                    ("levelDbA", "Level", "dB(A)"),
                ],
                rows,
            )
        ],
        notes=[
            "Free-field point-source 20 log distance attenuation and user-supplied barrier loss; ground effects, reflections, traffic spectra and screening geometry are omitted."
        ],
    )


@feature(
    "studiesEnvironment.sunHours",
    "Sun Hours",
    part="settings",
    fields=[
        number("latitude", "Latitude", 23.81, unit="°", min=-90, max=90),
        number("longitude", "Longitude", 90.41, unit="°", min=-180, max=180),
        text("date", "Date", "2026-06-21"),
        text(
            "surfaceNormals",
            "Surface normals as azimuth,elevation pairs",
            "0,90;90,90;180,90;270,90",
        ),
        number("utcOffset", "UTC offset", 6, unit="h", min=-12, max=14),
        number("stepMinutes", "Sampling interval", 30, unit="min", min=5, max=120),
    ],
    requires_project=False,
)
def sun_hours(ctx: FeatureContext, values: dict) -> dict:
    """Count direct-sun intervals for supplied surface azimuth and tilt orientations."""
    try:
        day = dt.date.fromisoformat(values["date"])
        orientations = [
            [float(part) for part in row.split(",")]
            for row in values["surfaceNormals"].split(";")
            if row.strip()
        ]
    except (ValueError, TypeError) as error:
        raise FeatureInputError(
            "Use YYYY-MM-DD and semicolon-separated azimuth,elevation orientations."
        ) from error
    if any(len(pair) != 2 for pair in orientations):
        raise FeatureInputError("Every surface orientation needs azimuth and elevation values.")
    from saengine.environment.solar import local_time, sun_position

    count = round(24 * 60 / values["stepMinutes"])
    rows = []
    for i, (azimuth, tilt) in enumerate(orientations, 1):
        hours = 0.0
        for step in range(count):
            sun_az, sun_el = sun_position(
                values["latitude"],
                values["longitude"],
                local_time(day, step * values["stepMinutes"] / 60, values["utcOffset"]),
            )
            cosine = math.sin(math.radians(sun_el)) * math.cos(math.radians(tilt)) + math.cos(
                math.radians(sun_el)
            ) * math.sin(math.radians(tilt)) * math.cos(math.radians(sun_az - azimuth))
            if sun_el > 0 and cosine > 0:
                hours += values["stepMinutes"] / 60
        rows.append({"surface": i, "azimuth": azimuth, "tilt": tilt, "sunHours": hours})
    return result(
        summary={
            "surfaceCount": len(rows),
            "maximumSunHours": max(row["sunHours"] for row in rows) if rows else 0,
        },
        tables=[
            table(
                "Direct sun by surface orientation",
                [
                    ("surface", "Surface"),
                    ("azimuth", "Azimuth", "°"),
                    ("tilt", "Tilt", "°"),
                    ("sunHours", "Sun hours", "h"),
                ],
                rows,
            )
        ],
        notes=[
            "Above-horizon sun is counted when the plane faces the sun; obstruction and cloud cover are not modeled."
        ],
    )


@feature(
    "studiesEnvironment.pmvComfort",
    "PMV Comfort",
    part="mep",
    fields=[
        number("airTemperature", "Air temperature", 24, unit="°C", min=-30, max=60),
        number(
            "meanRadiantTemperature", "Mean radiant temperature", 24, unit="°C", min=-30, max=60
        ),
        number("airSpeed", "Air speed", 0.1, unit="m/s", min=0, max=5),
        number("relativeHumidity", "Relative humidity", 50, unit="%", min=1, max=100),
        number("metabolicRate", "Metabolic rate", 1.2, unit="met", min=0.1, max=5),
        number("clothing", "Clothing insulation", 0.6, unit="clo", min=0, max=3),
    ],
    requires_project=False,
)
def pmv_comfort(ctx: FeatureContext, values: dict) -> dict:
    """Calculate predicted mean vote and predicted percentage dissatisfied by Fanger heat balance."""
    pmv, ppd = _pmv(
        values["airTemperature"],
        values["meanRadiantTemperature"],
        values["airSpeed"],
        values["relativeHumidity"],
        values["metabolicRate"],
        values["clothing"],
    )
    return result(
        summary={
            "pmv": pmv,
            "ppdPercent": ppd,
            "thermalSensation": "cold" if pmv < -0.5 else "warm" if pmv > 0.5 else "near-neutral",
        },
        notes=[
            "PMV/PPD for a uniform, steady-state environment; occupant adaptation and local discomfort are not included."
        ],
    )


@feature(
    "studiesEnvironment.overheating",
    "Overheating",
    part="mep",
    fields=[
        text(
            "hourlyTemperatures",
            "Occupied hourly temperatures, °C",
            "24,24,24,24,24,25,26,27,28,29,29,30,30,30,29,29,28,27,27,26,25,25,24,24",
        ),
        number("threshold", "Operative temperature threshold", 26, unit="°C"),
        number("annualHours", "Occupied hours in sample period", 24, min=0),
    ],
)
def overheating(ctx: FeatureContext, values: dict) -> dict:
    """Count occupied temperature exceedance hours from a supplied time series."""
    temps = numbers(values["hourlyTemperatures"], "hourly temperatures")
    exceeded = sum(t > values["threshold"] for t in temps)
    occupied_sample_hours = len(temps)
    scaled_hours = (
        exceeded * values["annualHours"] / occupied_sample_hours if occupied_sample_hours else 0
    )
    return result(
        summary={
            "sampleExceedanceHours": exceeded,
            "scaledAnnualExceedanceHours": scaled_hours,
            "exceedanceFraction": exceeded / occupied_sample_hours if occupied_sample_hours else 0,
        },
        tables=[
            table(
                "Temperature sample",
                [
                    ("hour", "Sample hour"),
                    ("temperature", "Temperature", "°C"),
                    ("exceeds", "Exceeds threshold"),
                ],
                [
                    {"hour": i + 1, "temperature": t, "exceeds": t > values["threshold"]}
                    for i, t in enumerate(temps)
                ],
            )
        ],
        notes=[
            "Hours above the user-supplied threshold are counted; scaling assumes the sample has the same exceedance fraction as the occupied year."
        ],
    )


@feature(
    "studiesEnvironment.airQuality",
    "Air Quality",
    part="mep",
    fields=[
        number("occupants", "Occupants", 30, min=0),
        number("outdoorAir", "Outdoor air flow", 10, unit="L/s/person", min=0),
        number("co2Generation", "CO₂ generation per person", 0.005, unit="L/s/person", min=0),
        number("outdoorCo2", "Outdoor CO₂ concentration", 420, unit="ppm", min=0, max=2000),
    ],
    requires_project=False,
)
def air_quality(ctx: FeatureContext, values: dict) -> dict:
    """Estimate steady-state indoor carbon dioxide concentration by a well-mixed mass balance."""
    flow = values["occupants"] * values["outdoorAir"]
    if flow <= 0:
        raise FeatureInputError(
            "Occupants and outdoor airflow must produce a positive total ventilation rate."
        )
    excess_ppm = values["occupants"] * values["co2Generation"] / flow * 1_000_000
    return result(
        summary={
            "outdoorAirLPerS": flow,
            "indoorCo2Ppm": values["outdoorCo2"] + excess_ppm,
            "co2RisePpm": excess_ppm,
        },
        notes=[
            "Steady, well-mixed CO₂ balance with constant generation and ventilation; transient occupancy, filtration and spatial gradients are omitted."
        ],
    )


@feature(
    "studiesEnvironment.comfortReport",
    "Comfort Report",
    part="mep",
    fields=[
        text(
            "roomResults",
            "Room comfort records",
            '[{"room":"R1","pmv":0.2,"ppdPercent":6,"operativeC":24},{"room":"R2","pmv":0.8,"ppdPercent":18,"operativeC":27}]',
        )
    ],
    requires_project=False,
)
def comfort_report(ctx: FeatureContext, values: dict) -> dict:
    """Summarize room comfort records with mean values and rooms above user-review thresholds."""
    rows = records(values["roomResults"], "room comfort results")
    try:
        pmvs = [float(row["pmv"]) for row in rows]
        ppds = [float(row["ppdPercent"]) for row in rows]
    except (KeyError, TypeError, ValueError) as error:
        raise FeatureInputError(
            "Every room comfort result needs numeric pmv and ppdPercent fields."
        ) from error
    return result(
        summary={
            "roomCount": len(rows),
            "meanPmv": sum(pmvs) / len(pmvs),
            "meanPpdPercent": sum(ppds) / len(ppds),
            "roomsAbove20PercentPpd": sum(p > 20 for p in ppds),
        },
        tables=[
            table(
                "Room comfort records",
                [(key, key.replace("_", " ").title()) for key in rows[0]],
                rows,
            )
        ],
        notes=[
            "The report aggregates supplied room results and flags PPD above 20% as a screening threshold; it does not assert a standard's compliance."
        ],
    )


@feature(
    "studiesEnvironment.complianceCheck",
    "Compliance Check",
    part="mep",
    fields=[
        text(
            "results",
            "Measured result rows",
            '[{"metric":"energyIntensity","value":150,"unit":"kWh/m2/year"},{"metric":"pmv","value":0.4,"unit":"-"}]',
        ),
        text(
            "limits",
            "User-defined limits",
            '{"energyIntensity":{"max":160},"pmv":{"min":-0.5,"max":0.5}}',
        ),
    ],
    requires_project=False,
)
def compliance_check(ctx: FeatureContext, values: dict) -> dict:
    """Compare result rows to explicit user-supplied minimum and maximum bounds."""
    rows, limits = records(values["results"], "compliance results"), json.loads(values["limits"])
    if not isinstance(limits, dict):
        raise FeatureInputError("Limits must be a JSON object keyed by metric name.")
    output = []
    for row in rows:
        name = str(row.get("metric", ""))
        if name not in limits:
            output.append(
                {"metric": name, "value": row.get("value"), "status": "no limit supplied"}
            )
            continue
        try:
            value = float(row["value"])
            bound = limits[name]
            passed = ("min" not in bound or value >= float(bound["min"])) and (
                "max" not in bound or value <= float(bound["max"])
            )
        except (KeyError, TypeError, ValueError) as error:
            raise FeatureInputError(
                f"Metric {name} needs a numeric value and numeric limits."
            ) from error
        output.append(
            {"metric": name, "value": value, "status": "pass" if passed else "outside limit"}
        )
    return result(
        summary={
            "metricCount": len(output),
            "passed": sum(row["status"] == "pass" for row in output),
            "outsideLimit": sum(row["status"] == "outside limit" for row in output),
        },
        tables=[
            table(
                "User-defined criteria",
                [("metric", "Metric"), ("value", "Value"), ("status", "Status")],
                output,
            )
        ],
        notes=[
            "Only user-supplied numeric bounds are evaluated; no external standard or code threshold is embedded."
        ],
    )


@feature(
    "studiesEnvironment.exportMaps",
    "Export Maps",
    part="mep",
    fields=[
        text(
            "mapRows",
            "Map data rows",
            '[{"x":0,"y":0,"value":22,"unit":"°C"},{"x":1,"y":0,"value":24,"unit":"°C"}]',
        ),
        text("mapName", "Map name", "comfort-map"),
    ],
)
def export_maps(ctx: FeatureContext, values: dict) -> dict:
    """Write supplied environmental map coordinates and values to the project's Exports folder."""
    rows = records(values["mapRows"], "map values")
    safe = (
        "".join(char for char in values["mapName"] if char.isalnum() or char in "-_").strip("-_")
        or "map"
    )
    relative = write_json(
        ctx,
        f"11 Exports/{safe}.geojson.json",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [row["x"], row["y"]]},
                    "properties": {
                        key: value for key, value in row.items() if key not in ("x", "y")
                    },
                }
                for row in rows
            ],
        },
    )
    return result(
        summary={"pointCount": len(rows), "outputPath": relative},
        notes=[
            f"Map points written as a GeoJSON FeatureCollection to {relative}; this file stores the supplied values and is not a rendered image."
        ],
    )


@feature(
    "studiesEnvironment.wholeLifeCarbon",
    "Whole Life Carbon",
    part="mep",
    fields=[
        number("embodied", "Initial embodied carbon", 250000, unit="kg CO2e", min=0),
        number("annualOperational", "Annual operational carbon", 18000, unit="kg CO2e/year", min=0),
        number("years", "Study period", 60, unit="year", min=1, max=200),
        number("replacementCarbon", "Replacement embodied carbon", 40000, unit="kg CO2e", min=0),
        number("replacementInterval", "Replacement interval", 20, unit="year", min=1),
    ],
)
def whole_life_carbon(ctx: FeatureContext, values: dict) -> dict:
    """Sum initial, recurring operational and scheduled replacement carbon over the study life."""
    life, interval = int(values["years"]), int(values["replacementInterval"])
    years = list(range(interval, life + 1, interval))
    replacement = len(years) * values["replacementCarbon"]
    operation = life * values["annualOperational"]
    return result(
        summary={
            "embodiedKgCo2e": values["embodied"],
            "replacementKgCo2e": replacement,
            "operationalKgCo2e": operation,
            "wholeLifeKgCo2e": values["embodied"] + replacement + operation,
            "studyYears": life,
        },
        tables=[
            table(
                "Carbon by stage",
                [("stage", "Stage"), ("carbon", "Carbon", "kg CO2e")],
                [
                    {"stage": "Initial embodied", "carbon": values["embodied"]},
                    {"stage": "Replacements", "carbon": replacement},
                    {"stage": "Operations", "carbon": operation},
                ],
            )
        ],
        notes=[
            "Undiscounted totals with constant annual operational emissions and replacement events at interval multiples within the study period."
        ],
    )


@feature(
    "studiesEnvironment.offsetTargets",
    "Offset Targets",
    part="mep",
    fields=[
        number("baselineCarbon", "Baseline annual carbon", 18000, unit="kg CO2e/year", min=0),
        number("reductionPercent", "Reduction target", 40, unit="%", min=0, max=100),
        number("offsetPercent", "Offset share of residual", 50, unit="%", min=0, max=100),
    ],
    requires_project=False,
)
def offset_targets(ctx: FeatureContext, values: dict) -> dict:
    """Translate reduction and offset percentages into annual carbon targets."""
    residual = values["baselineCarbon"] * (1 - values["reductionPercent"] / 100)
    offset = residual * values["offsetPercent"] / 100
    return result(
        summary={
            "reductionKgCo2ePerYear": values["baselineCarbon"] - residual,
            "residualKgCo2ePerYear": residual,
            "offsetTargetKgCo2ePerYear": offset,
            "unabatedKgCo2ePerYear": residual - offset,
        },
        notes=[
            "The reduction target is applied first; the offset share applies to the remaining annual emissions."
        ],
    )
