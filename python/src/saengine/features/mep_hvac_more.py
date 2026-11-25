"""HVAC zone controls, equipment selection and energy features."""

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
)


@feature(
    "mepHvac.zoneHeating",
    "Zone Heating",
    part="mep",
    fields=[
        number("zoneAreaM2", "Zone floor area", 45, unit="m²", min=0.1),
        number("designHeatLossWm2", "Design heat loss", 55, unit="W/m²", min=0),
        number("outsideTemperatureC", "Outdoor design temperature", 5, unit="°C"),
        number("setpointC", "Heating setpoint", 21, unit="°C"),
    ],
    requires_project=False,
)
def zone_heating(ctx: FeatureContext, values: dict) -> dict:
    """Estimate zone heating load from area-normalized heat loss."""
    load = values["zoneAreaM2"] * values["designHeatLossWm2"]
    return result(
        summary={
            "heatingLoadKw": load / 1000,
            "designTemperatureRiseC": values["setpointC"] - values["outsideTemperatureC"],
        },
        notes=[
            "Heating demand uses the entered area-specific loss at the stated outdoor design condition; envelope and infiltration must be calculated separately."
        ],
    )


@feature(
    "mepHvac.zoneCooling",
    "Zone Cooling",
    part="mep",
    fields=[
        number("sensibleLoadKw", "Zone sensible load", 5, unit="kW", min=0),
        number("latentLoadKw", "Zone latent load", 1.2, unit="kW", min=0),
        number("supplyTemperatureC", "Supply air temperature", 14, unit="°C"),
        number("roomTemperatureC", "Room setpoint", 24, unit="°C"),
    ],
    requires_project=False,
)
def zone_cooling(ctx: FeatureContext, values: dict) -> dict:
    """Calculate total zone cooling load and supply air requirement."""
    total = values["sensibleLoadKw"] + values["latentLoadKw"]
    dt = values["roomTemperatureC"] - values["supplyTemperatureC"]
    if dt <= 0:
        raise FeatureInputError("Supply air temperature must be below the room cooling setpoint.")
    from saengine.hvac.air import supply_airflow

    flow = supply_airflow(values["sensibleLoadKw"], dt) * 1000
    return result(
        summary={"totalCoolingKw": total, "sensibleAirflowLs": flow},
        notes=[
            "Supply airflow is calculated from sensible heat balance; latent load is added to total coil duty."
        ],
    )


@feature(
    "mepHvac.zoningRules",
    "Zoning Rules",
    part="mep",
    fields=[
        number("adjacentZoneAreaM2", "Adjacent space area", 80, unit="m²", min=0.1),
        number("maximumZoneAreaM2", "Maximum zone area", 100, unit="m²", min=0.1),
        number("solarLoadDifferenceKw", "Adjacent solar load difference", 1.0, unit="kW", min=0),
        number(
            "maximumSolarLoadDifferenceKw",
            "Maximum combined solar load difference",
            2,
            unit="kW",
            min=0,
        ),
        select(
            "orientation", "Dominant orientation", ["north", "east", "south", "west", "interior"]
        ),
    ],
    requires_project=False,
)
def zoning_rules(ctx: FeatureContext, values: dict) -> dict:
    """Check proposed adjacent spaces against area and solar-load zoning limits."""
    return result(
        summary={
            "areaPasses": values["adjacentZoneAreaM2"] <= values["maximumZoneAreaM2"],
            "solarPasses": values["solarLoadDifferenceKw"]
            <= values["maximumSolarLoadDifferenceKw"],
            "orientation": values["orientation"],
        },
        notes=[
            "Spaces should share similar occupancy schedules, solar exposure and thermal response; both thresholds are project criteria."
        ],
    )


@feature(
    "mepHvac.zoneReheat",
    "Zone Reheat",
    part="mep",
    fields=[
        number("minimumAirflowLs", "Minimum ventilation airflow", 80, unit="L/s", min=0),
        number("supplyTemperatureC", "Primary air temperature", 14, unit="°C"),
        number("zoneSetpointC", "Zone heating setpoint", 21, unit="°C"),
        number("airDensityKgM3", "Air density", 1.2, unit="kg/m³", min=0.1),
        number("specificHeatKjKgK", "Air specific heat", 1.006, unit="kJ/(kg·K)", min=0.1),
    ],
    requires_project=False,
)
def zone_reheat(ctx: FeatureContext, values: dict) -> dict:
    """Determine reheat coil duty for the minimum primary airflow."""
    delta = max(values["zoneSetpointC"] - values["supplyTemperatureC"], 0)
    kw = (
        values["minimumAirflowLs"]
        / 1000
        * values["airDensityKgM3"]
        * values["specificHeatKjKgK"]
        * delta
    )
    return result(
        summary={"reheatDutyKw": kw, "temperatureRiseC": delta},
        notes=[
            "Reheat duty is sensible air heating at minimum airflow; avoid simultaneous cooling and reheat by coordinating terminal control sequences."
        ],
    )


@feature(
    "mepHvac.equipmentSizing",
    "Equipment Sizing",
    part="mep",
    fields=[
        number("coincidentCoolingKw", "Coincident cooling load", 120, unit="kW", min=0),
        number("coincidentHeatingKw", "Coincident heating load", 80, unit="kW", min=0),
        number("coolingSafetyFactor", "Cooling sizing factor", 1.1, min=1),
        number("heatingSafetyFactor", "Heating sizing factor", 1.1, min=1),
        number("unitCapacityKw", "Selected unit capacity", 40, unit="kW", min=0.1),
    ],
    requires_project=False,
)
def equipment_sizing(ctx: FeatureContext, values: dict) -> dict:
    """Determine required equipment capacity and modular unit counts."""
    cooling = values["coincidentCoolingKw"] * values["coolingSafetyFactor"]
    heating = values["coincidentHeatingKw"] * values["heatingSafetyFactor"]
    return result(
        summary={
            "requiredCoolingKw": cooling,
            "requiredHeatingKw": heating,
            "coolingUnits": math.ceil(cooling / values["unitCapacityKw"]),
            "heatingUnits": math.ceil(heating / values["unitCapacityKw"]),
        },
        notes=[
            "Safety factors are explicit project inputs; use coincident zone loads and verify turndown, redundancy and ambient derating."
        ],
    )


@feature(
    "mepHvac.coilSelection",
    "Coil Selection",
    part="mep",
    fields=[
        number("coilDutyKw", "Coil duty", 30, unit="kW", min=0),
        number("waterTemperatureDropC", "Water temperature difference", 5.5, unit="°C", min=0.1),
        number("airflowM3s", "Coil airflow", 2.5, unit="m³/s", min=0.01),
        number("airTemperatureChangeC", "Air temperature change", 10, unit="°C", min=0.1),
    ],
    requires_project=False,
)
def coil_selection(ctx: FeatureContext, values: dict) -> dict:
    """Calculate coil water flow and verify sensible air-side duty."""
    water_ls = values["coilDutyKw"] / (4.186 * values["waterTemperatureDropC"])
    air_kw = values["airflowM3s"] * 1.2 * 1.006 * values["airTemperatureChangeC"]
    return result(
        summary={
            "waterFlowLs": water_ls,
            "airSideSensibleKw": air_kw,
            "airSideDutyPasses": air_kw >= values["coilDutyKw"],
        },
        notes=[
            "Water flow uses specific heat 4.186 kJ/(kg·K) and density near 1 kg/L; air-side check assumes 1.2 kg/m³ density."
        ],
    )


@feature(
    "mepHvac.fanCurvePick",
    "Fan Curve Pick",
    part="mep",
    fields=[
        number("requiredFlowM3s", "Required airflow", 2, unit="m³/s", min=0.01),
        number("requiredPressurePa", "Required static pressure", 500, unit="Pa", min=0),
        number("curveFlowM3s", "Candidate fan flow at duty", 2.2, unit="m³/s", min=0),
        number("curvePressurePa", "Candidate fan pressure at duty", 540, unit="Pa", min=0),
        number("fanEfficiency", "Candidate efficiency", 0.7, min=0.05, max=1),
    ],
    requires_project=False,
)
def fan_curve_pick(ctx: FeatureContext, values: dict) -> dict:
    """Compare a candidate fan operating point with the required duty."""
    return result(
        summary={
            "dutyCovered": values["curveFlowM3s"] >= values["requiredFlowM3s"]
            and values["curvePressurePa"] >= values["requiredPressurePa"],
            "airPowerKw": values["requiredFlowM3s"] * values["requiredPressurePa"] / 1000,
            "inputPowerKw": values["requiredFlowM3s"]
            * values["requiredPressurePa"]
            / 1000
            / values["fanEfficiency"],
        },
        notes=[
            "The candidate point is checked against required flow and pressure; final selection requires the manufacturer's complete fan curve, motor limit and stable operating range."
        ],
    )


@feature(
    "mepHvac.terminalSelection",
    "Terminal Selection",
    part="mep",
    fields=[
        number("designFlowLs", "Design terminal airflow", 180, unit="L/s", min=0.1),
        number("terminalMaximumLs", "Terminal maximum airflow", 220, unit="L/s", min=0.1),
        number("terminalMinimumLs", "Terminal minimum airflow", 60, unit="L/s", min=0),
        number("roomNoiseLimitNc", "Room noise criterion NC", 35, min=0),
        number("terminalNoiseNc", "Terminal noise estimate NC", 30, min=0),
    ],
    requires_project=False,
)
def terminal_selection(ctx: FeatureContext, values: dict) -> dict:
    """Check terminal airflow range and stated room noise criterion."""
    flow_ok = values["terminalMinimumLs"] <= values["designFlowLs"] <= values["terminalMaximumLs"]
    return result(
        summary={
            "airflowPasses": flow_ok,
            "noisePasses": values["terminalNoiseNc"] <= values["roomNoiseLimitNc"],
            "requiredFlowLs": values["designFlowLs"],
        },
        notes=[
            "Noise estimate must be manufacturer-rated for the selected inlet pressure and room installation; airflow limits are terminal data."
        ],
    )


@feature(
    "mepHvac.thermostatSetpoints",
    "Thermostat Setpoints",
    part="mep",
    fields=[
        number("occupiedCoolingC", "Occupied cooling setpoint", 24, unit="°C"),
        number("occupiedHeatingC", "Occupied heating setpoint", 21, unit="°C"),
        number("unoccupiedCoolingC", "Unoccupied cooling setpoint", 28, unit="°C"),
        number("unoccupiedHeatingC", "Unoccupied heating setpoint", 16, unit="°C"),
        number("deadbandC", "Minimum deadband", 2, unit="°C", min=0),
    ],
    requires_project=False,
)
def thermostat_setpoints(ctx: FeatureContext, values: dict) -> dict:
    """Check heating and cooling setpoint separation in occupied and setback modes."""
    occupied = values["occupiedCoolingC"] - values["occupiedHeatingC"]
    unoccupied = values["unoccupiedCoolingC"] - values["unoccupiedHeatingC"]
    return result(
        summary={
            "occupiedDeadbandC": occupied,
            "unoccupiedDeadbandC": unoccupied,
            "passes": occupied >= values["deadbandC"] and unoccupied >= values["deadbandC"],
        },
        notes=[
            "Setpoints are editable project controls; coordinate deadband with humidity control, thermal comfort and plant operating limits."
        ],
    )


@feature(
    "mepHvac.controlSequences",
    "Control Sequences",
    part="mep",
    fields=[
        select("systemType", "System type", ["vav", "vrf", "ahu", "fanCoil"]),
        number("occupiedStartHour", "Occupied start hour", 8, min=0, max=23),
        number("occupiedEndHour", "Occupied end hour", 18, min=1, max=24),
        number("minimumOutsideAirFraction", "Minimum outside-air fraction", 0.2, min=0, max=1),
        number("economizerEnabled", "Economizer enabled (0 or 1)", 0, min=0, max=1),
    ],
    requires_project=False,
)
def control_sequences(ctx: FeatureContext, values: dict) -> dict:
    """Record sequence parameters and validate the occupied schedule interval."""
    start = int(values["occupiedStartHour"])
    end = int(values["occupiedEndHour"])
    return result(
        summary={
            "systemType": values["systemType"],
            "occupiedHours": (end - start) % 24,
            "scheduleValid": start != end,
            "economizer": bool(values["economizerEnabled"]),
        },
        tables=[
            table(
                "Sequence parameters",
                [("parameter", "Parameter"), ("value", "Value")],
                [
                    {
                        "parameter": "Outside air fraction",
                        "value": values["minimumOutsideAirFraction"],
                    },
                    {"parameter": "Occupied start", "value": start},
                    {"parameter": "Occupied end", "value": end},
                ],
            )
        ],
        notes=[
            "This provides sequence configuration data only; interlocks, safeties, alarms and point mapping require project controls design."
        ],
    )


@feature(
    "mepHvac.scheduleProfiles",
    "Schedule Profiles",
    part="mep",
    fields=[
        number("weekdayOccupiedHours", "Weekday occupied hours", 10, unit="h/day", min=0, max=24),
        number("weekendOccupiedHours", "Weekend occupied hours", 0, unit="h/day", min=0, max=24),
        number("weekdayCount", "Weekdays per week", 5, min=0, max=7),
        number("weekendCount", "Weekend days per week", 2, min=0, max=7),
        number("occupiedFraction", "Occupied load fraction", 1, min=0, max=1),
        number("setbackFraction", "Setback load fraction", 0.25, min=0, max=1),
    ],
    requires_project=False,
)
def schedule_profiles(ctx: FeatureContext, values: dict) -> dict:
    """Calculate weekly occupied hours and weighted HVAC load factor."""
    occupied = (
        values["weekdayOccupiedHours"] * values["weekdayCount"]
        + values["weekendOccupiedHours"] * values["weekendCount"]
    )
    weighted = (
        occupied * values["occupiedFraction"] + (168 - occupied) * values["setbackFraction"]
    ) / 168
    return result(
        summary={"occupiedHoursPerWeek": occupied, "weeklyAverageLoadFraction": weighted},
        notes=[
            "The weekly profile averages the explicit occupied and setback fractions across 168 hours; holidays and seasonal variation are excluded."
        ],
    )


@feature(
    "mepHvac.sensorLayout",
    "Sensor Layout",
    part="mep",
    fields=[
        number("zoneAreaM2", "Zone area", 120, unit="m²", min=1),
        number("maximumAreaPerSensorM2", "Maximum monitored area per sensor", 60, unit="m²", min=1),
        number("zoneLengthM", "Zone length", 12, unit="m", min=0.1),
        number("maximumSensorSpacingM", "Maximum sensor spacing", 8, unit="m", min=0.1),
    ],
    requires_project=False,
)
def sensor_layout(ctx: FeatureContext, values: dict) -> dict:
    """Estimate sensor count from monitored area and longitudinal spacing."""
    count = max(
        math.ceil(values["zoneAreaM2"] / values["maximumAreaPerSensorM2"]),
        math.ceil(values["zoneLengthM"] / values["maximumSensorSpacingM"]),
    )
    return result(
        summary={"sensorCount": count},
        notes=[
            "Sensor coverage and spacing are project criteria; account for stratification, return-air location, solar exposure and representative occupied positions."
        ],
    )


@feature(
    "mepHvac.energyEstimate",
    "Energy Estimate",
    part="mep",
    fields=[
        number("coolingLoadKw", "Design cooling load", 100, unit="kW", min=0),
        number("heatingLoadKw", "Design heating load", 60, unit="kW", min=0),
        number(
            "coolingEquivalentHours",
            "Annual cooling equivalent full-load hours",
            1200,
            unit="h",
            min=0,
        ),
        number(
            "heatingEquivalentHours",
            "Annual heating equivalent full-load hours",
            900,
            unit="h",
            min=0,
        ),
        number("coolingCop", "Seasonal cooling COP", 3.2, min=0.1),
        number("heatingEfficiency", "Seasonal heating efficiency", 0.9, min=0.1),
    ],
    requires_project=False,
)
def energy_estimate(ctx: FeatureContext, values: dict) -> dict:
    """Estimate annual HVAC input energy using equivalent full-load hours."""
    cooling_kwh = values["coolingLoadKw"] * values["coolingEquivalentHours"] / values["coolingCop"]
    heating_kwh = (
        values["heatingLoadKw"] * values["heatingEquivalentHours"] / values["heatingEfficiency"]
    )
    return result(
        summary={
            "coolingInputKwh": cooling_kwh,
            "heatingInputKwh": heating_kwh,
            "annualInputKwh": cooling_kwh + heating_kwh,
        },
        notes=[
            "Annual estimate uses equivalent full-load hours and seasonal performance inputs; fans, pumps, auxiliaries, weather and occupancy schedules are excluded."
        ],
    )


@feature(
    "mepHvac.partLoadValues",
    "Part Load Values",
    part="mep",
    fields=[
        number("copAt25", "COP at 25% load", 4.0, min=0.1),
        number("copAt50", "COP at 50% load", 3.8, min=0.1),
        number("copAt75", "COP at 75% load", 3.5, min=0.1),
        number("copAt100", "COP at 100% load", 3.0, min=0.1),
        number("hours25", "Hours at 25% load", 800, unit="h", min=0),
        number("hours50", "Hours at 50% load", 1200, unit="h", min=0),
        number("hours75", "Hours at 75% load", 800, unit="h", min=0),
        number("hours100", "Hours at full load", 200, unit="h", min=0),
    ],
    requires_project=False,
)
def part_load_values(ctx: FeatureContext, values: dict) -> dict:
    """Calculate load-weighted seasonal COP from entered operating bins."""
    bins = [
        (0.25, values["copAt25"], values["hours25"]),
        (0.5, values["copAt50"], values["hours50"]),
        (0.75, values["copAt75"], values["hours75"]),
        (1.0, values["copAt100"], values["hours100"]),
    ]
    cooling = sum(load * hour for load, _, hour in bins)
    electricity = sum(load * hour / cop for load, cop, hour in bins)
    return result(
        summary={
            "seasonalCop": cooling / electricity if electricity else None,
            "operatingHours": sum(hour for _, _, hour in bins),
        },
        tables=[
            table(
                "Part-load operating bins",
                [("loadFraction", "Load fraction"), ("cop", "COP"), ("hours", "Hours")],
                [{"loadFraction": load, "cop": cop, "hours": hour} for load, cop, hour in bins],
            )
        ],
        notes=[
            "Seasonal COP is weighted by cooling energy output over the entered operating bins; equipment cycling and standby energy are excluded."
        ],
    )


@feature(
    "mepHvac.efficiencyRatios",
    "Efficiency Ratios",
    part="mep",
    fields=[
        number("measuredCop", "Equipment COP", 3.4, min=0.1),
        number("targetCop", "Project target COP", 3.2, min=0.1),
        number("measuredEer", "Equipment EER", 11.6, min=0.1),
        number("targetEer", "Project target EER", 10.5, min=0.1),
    ],
    requires_project=False,
)
def efficiency_ratios(ctx: FeatureContext, values: dict) -> dict:
    """Compare entered equipment COP and EER with project targets."""
    return result(
        summary={
            "copMargin": values["measuredCop"] - values["targetCop"],
            "eerMargin": values["measuredEer"] - values["targetEer"],
            "bothTargetsMet": values["measuredCop"] >= values["targetCop"]
            and values["measuredEer"] >= values["targetEer"],
        },
        notes=[
            "Ratios are compared at the stated rating conditions; seasonal and part-load performance may differ."
        ],
    )
