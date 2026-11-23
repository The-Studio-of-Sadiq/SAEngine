"""Earthing, bonding and lightning-protection engineering calculations."""

from __future__ import annotations

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


@feature(
    "mepElectricalEarthing.rodElectrode",
    "Rod Electrode",
    part="mep",
    fields=[
        number("resistivityOhmM", "Soil resistivity", 100, unit="Ω·m", min=0.1),
        number("lengthM", "Rod length", 3, unit="m", min=0.1),
        number("diameterM", "Rod diameter", 0.016, unit="m", min=0.001),
        number("spacingM", "Rod spacing", 6, unit="m", min=0),
    ],
    requires_project=False,
)
def rod_electrode(ctx: FeatureContext, v: dict) -> dict:
    """Estimate resistance of a single vertical rod in uniform soil."""
    resistance = (
        v["resistivityOhmM"]
        / (2 * math.pi * v["lengthM"])
        * (math.log(4 * v["lengthM"] / v["diameterM"]) - 1)
    )
    return result(
        {
            "electrodeResistanceOhm": resistance,
            "spacingToLengthRatio": v["spacingM"] / v["lengthM"],
        },
        notes=[
            "Dwight approximation for a slender rod in homogeneous soil; mutual coupling, layering and seasonal variation are excluded."
        ],
    )


@feature(
    "mepElectricalEarthing.plateElectrode",
    "Plate Electrode",
    part="mep",
    fields=[
        number("resistivityOhmM", "Soil resistivity", 100, unit="Ω·m", min=0.1),
        number("widthM", "Plate width", 0.6, unit="m", min=0.1),
        number("heightM", "Plate height", 0.6, unit="m", min=0.1),
        number("burialM", "Burial depth to plate center", 1, unit="m", min=0.1),
    ],
    requires_project=False,
)
def plate_electrode(ctx: FeatureContext, v: dict) -> dict:
    """Estimate resistance of a buried rectangular plate using an equivalent disk."""
    radius = math.sqrt(v["widthM"] * v["heightM"] / math.pi)
    resistance = v["resistivityOhmM"] / (4 * radius) * (1 + radius / (v["burialM"] + radius))
    return result(
        {"equivalentRadiusM": radius, "estimatedResistanceOhm": resistance},
        notes=[
            "Equivalent-disk approximation for a plate in uniform soil; plate orientation, backfill and electrode interactions are omitted."
        ],
    )


@feature(
    "mepElectricalEarthing.earthGrid",
    "Earth Grid",
    part="mep",
    fields=[
        number("areaM2", "Grid area", 400, unit="m²", min=0.1),
        number("spacingM", "Grid conductor spacing", 5, unit="m", min=0.1),
        number("perimeterM", "Grid perimeter", 80, unit="m", min=0),
    ],
    requires_project=False,
)
def earth_grid(ctx: FeatureContext, v: dict) -> dict:
    """Estimate buried conductor length for a square mesh grid."""
    side = math.sqrt(v["areaM2"])
    lines = math.floor(side / v["spacingM"]) + 1
    return result(
        {
            "meshCountPerDirection": lines,
            "estimatedConductorLengthM": 2 * lines * side + v["perimeterM"],
        },
        notes=[
            "Square-grid takeoff estimate; conductor tails and electrode connections are excluded."
        ],
    )


@feature(
    "mepElectricalEarthing.electrodeResistance",
    "Electrode Resistance",
    part="mep",
    fields=[
        number("resistivityOhmM", "Soil resistivity", 100, unit="Ω·m", min=0.1),
        number("electrodeLengthM", "Electrode length", 3, unit="m", min=0.1),
        number("electrodeDiameterMm", "Electrode diameter", 16, unit="mm", min=1),
        number("electrodeCount", "Electrode count", 4, min=1),
    ],
    requires_project=False,
)
def electrode_resistance(ctx: FeatureContext, v: dict) -> dict:
    """Estimate a parallel group resistance for widely separated rods."""
    d = v["electrodeDiameterMm"] / 1000
    single = (
        v["resistivityOhmM"]
        / (2 * math.pi * v["electrodeLengthM"])
        * (math.log(4 * v["electrodeLengthM"] / d) - 1)
    )
    return result(
        {"singleRodOhm": single, "idealParallelGroupOhm": single / v["electrodeCount"]},
        notes=[
            "Ideal parallel estimate assumes negligible mutual coupling; actual group resistance is higher when rods are close."
        ],
    )


@feature(
    "mepElectricalEarthing.mainBonding",
    "Main Bonding",
    part="mep",
    fields=[
        number("conductorAreaMm2", "Bonding conductor area", 25, unit="mm²", min=1),
        number("faultCurrentA", "Prospective fault current", 1000, unit="A", min=0),
        number("clearingTimeS", "Clearing time", 0.2, unit="s", min=0.001),
        number("kFactor", "Adiabatic material factor", 115, min=1),
    ],
    requires_project=False,
)
def main_bonding(ctx: FeatureContext, v: dict) -> dict:
    """Compare bonding conductor area with the adiabatic thermal requirement."""
    required = v["faultCurrentA"] * math.sqrt(v["clearingTimeS"]) / v["kFactor"]
    return result(
        {
            "requiredAreaMm2": required,
            "providedAreaMm2": v["conductorAreaMm2"],
            "thermalCheckPass": v["conductorAreaMm2"] >= required,
        },
        notes=[
            "Adiabatic check S=I√t/k; confirm material, insulation temperature limits, mechanical protection and applicable minimum sizes."
        ],
    )


@feature(
    "mepElectricalEarthing.supplementaryBonding",
    "Supplementary Bonding",
    part="mep",
    fields=[
        number("measuredResistanceOhm", "Bonding resistance", 0.05, unit="Ω", min=0),
        number("maximumResistanceOhm", "Project maximum", 0.1, unit="Ω", min=0),
    ],
    requires_project=False,
)
def supplementary_bonding(ctx: FeatureContext, v: dict) -> dict:
    """Check a measured supplementary bonding resistance against the project limit."""
    return result(
        {
            "measuredResistanceOhm": v["measuredResistanceOhm"],
            "maximumResistanceOhm": v["maximumResistanceOhm"],
            "pass": v["measuredResistanceOhm"] <= v["maximumResistanceOhm"],
        },
        notes=[
            "Use a calibrated low-resistance test instrument and the project acceptance criterion."
        ],
    )


@feature(
    "mepElectricalEarthing.crossBonding",
    "Cross Bonding",
    part="mep",
    fields=[
        number("cableLengthM", "Cable length", 100, unit="m", min=0),
        number("bondingIntervalM", "Bonding interval", 25, unit="m", min=0.1),
    ],
    requires_project=False,
)
def cross_bonding(ctx: FeatureContext, v: dict) -> dict:
    """Estimate cross-bond locations along a cable route."""
    count = max(0, math.ceil(v["cableLengthM"] / v["bondingIntervalM"]) - 1)
    return result(
        {"intermediateBondCount": count, "routeLengthM": v["cableLengthM"]},
        notes=[
            "Interval is a designer input; cable sheath and screen bonding topology must match the system design."
        ],
    )


@feature(
    "mepElectricalEarthing.continuityTest",
    "Continuity Test",
    part="mep",
    fields=[
        number("measuredOhm", "Measured conductor resistance", 0.12, unit="Ω", min=0),
        number("calculatedOhm", "Expected conductor resistance", 0.1, unit="Ω", min=0),
        number("tolerancePercent", "Tolerance", 20, unit="%", min=0),
    ],
    requires_project=False,
)
def continuity_test(ctx: FeatureContext, v: dict) -> dict:
    """Compare measured bonding resistance with the calculated conductor value."""
    deviation = abs(v["measuredOhm"] - v["calculatedOhm"]) / max(v["calculatedOhm"], 1e-12) * 100
    return result(
        {"deviationPercent": deviation, "pass": deviation <= v["tolerancePercent"]},
        notes=[
            "Expected resistance must include conductor temperature, joints and test-lead compensation."
        ],
    )


@feature(
    "mepElectricalEarthing.earthFaultCurrent",
    "Earth Fault Current",
    part="mep",
    fields=[
        number("phaseVoltageV", "Phase voltage", 230, unit="V", min=1),
        number("loopImpedanceOhm", "Fault loop impedance", 0.4, unit="Ω", min=0.001),
    ],
    requires_project=False,
)
def earth_fault_current(ctx: FeatureContext, v: dict) -> dict:
    """Calculate prospective earth fault current from phase voltage and loop impedance."""
    return result(
        {"prospectiveFaultCurrentA": v["phaseVoltageV"] / v["loopImpedanceOhm"]},
        notes=["Assumes a bolted fault and uses the stated voltage and total loop impedance."],
    )


@feature(
    "mepElectricalEarthing.loopImpedance",
    "Loop Impedance",
    part="mep",
    fields=[
        number("phaseVoltageV", "Phase voltage", 230, unit="V", min=1),
        number("faultCurrentA", "Required fault current", 500, unit="A", min=0.1),
        number("measuredImpedanceOhm", "Measured loop impedance", 0.35, unit="Ω", min=0),
    ],
    requires_project=False,
)
def loop_impedance(ctx: FeatureContext, v: dict) -> dict:
    """Check measured fault-loop impedance against the entered trip-current threshold."""
    maximum = v["phaseVoltageV"] / v["faultCurrentA"]
    return result(
        {
            "maximumImpedanceOhm": maximum,
            "measuredImpedanceOhm": v["measuredImpedanceOhm"],
            "pass": v["measuredImpedanceOhm"] <= maximum,
        },
        notes=[
            "The required fault current must come from the selected protective-device operating characteristic."
        ],
    )


@feature(
    "mepElectricalEarthing.touchVoltage",
    "Touch Voltage",
    part="mep",
    fields=[
        number("faultCurrentA", "Fault current", 500, unit="A", min=0),
        number("earthPathOhm", "Earth path resistance", 0.2, unit="Ω", min=0),
        number("allowableVoltageV", "Project touch-voltage limit", 50, unit="V", min=0),
    ],
    requires_project=False,
)
def touch_voltage(ctx: FeatureContext, v: dict) -> dict:
    """Estimate touch voltage using fault current and earth-path resistance."""
    voltage = v["faultCurrentA"] * v["earthPathOhm"]
    return result(
        {
            "estimatedTouchVoltageV": voltage,
            "allowableVoltageV": v["allowableVoltageV"],
            "pass": voltage <= v["allowableVoltageV"],
        },
        notes=[
            "Simple resistive voltage-rise estimate; body impedance, current duration, surface layer and spatial gradients are omitted."
        ],
    )


@feature(
    "mepElectricalEarthing.earthingReport",
    "Earthing Report",
    part="mep",
    fields=[
        number("soilResistivityOhmM", "Soil resistivity", 100, unit="Ω·m", min=0.1),
        number("measuredResistanceOhm", "Measured earth resistance", 2, unit="Ω", min=0),
        text("testDate", "Test date", ""),
    ],
    requires_project=False,
)
def earthing_report(ctx: FeatureContext, v: dict) -> dict:
    """Summarize entered earthing test data in a report table."""
    return result(
        {
            "soilResistivityOhmM": v["soilResistivityOhmM"],
            "measuredResistanceOhm": v["measuredResistanceOhm"],
        },
        [
            table(
                "Earthing test record",
                [("parameter", "Parameter"), ("value", "Value")],
                [
                    {"parameter": "Soil resistivity (Ω·m)", "value": v["soilResistivityOhmM"]},
                    {"parameter": "Earth resistance (Ω)", "value": v["measuredResistanceOhm"]},
                    {"parameter": "Test date", "value": v["testDate"]},
                ],
            )
        ],
    )


@feature(
    "mepElectricalEarthing.soilResistivityProfile",
    "Soil Resistivity Profile",
    part="mep",
    fields=[
        number("resistivityShallowOhmM", "Shallow resistivity", 80, unit="Ω·m", min=0.1),
        number("resistivityDeepOhmM", "Deep resistivity", 180, unit="Ω·m", min=0.1),
        number("layerDepthM", "Layer interface depth", 3, unit="m", min=0.1),
    ],
    requires_project=False,
)
def soil_resistivity_profile(ctx: FeatureContext, v: dict) -> dict:
    """Represent a two-layer interpreted soil-resistivity profile."""
    return result(
        {"layerCount": 2},
        [
            table(
                "Resistivity layers",
                [
                    ("layer", "Layer"),
                    ("thicknessM", "Thickness", "m"),
                    ("resistivityOhmM", "Resistivity", "Ω·m"),
                ],
                [
                    {
                        "layer": 1,
                        "thicknessM": v["layerDepthM"],
                        "resistivityOhmM": v["resistivityShallowOhmM"],
                    },
                    {"layer": 2, "thicknessM": None, "resistivityOhmM": v["resistivityDeepOhmM"]},
                ],
            )
        ],
        [
            "Layer values should be derived from site measurements; this profile is input data, not a Wenner inversion."
        ],
    )


@feature(
    "mepElectricalEarthing.multiLayerSoil",
    "Multi Layer Soil",
    part="mep",
    fields=[
        number("upperLayerOhmM", "Upper-layer resistivity", 100, unit="Ω·m", min=0.1),
        number("upperDepthM", "Upper-layer thickness", 2, unit="m", min=0.1),
        number("lowerLayerOhmM", "Lower-layer resistivity", 300, unit="Ω·m", min=0.1),
    ],
    requires_project=False,
)
def multi_layer_soil(ctx: FeatureContext, v: dict) -> dict:
    """Calculate a depth-weighted effective resistivity for two soil layers."""
    effective = v["upperLayerOhmM"] * (1 - math.exp(-1 / v["upperDepthM"])) + v[
        "lowerLayerOhmM"
    ] * math.exp(-1 / v["upperDepthM"])
    return result(
        {"effectiveResistivityOhmM": effective},
        notes=[
            "Exponential screening average at a nominal 1 m depth; multilayer field analysis requires a validated layered-soil model."
        ],
    )


@feature(
    "mepElectricalEarthing.moistureFactor",
    "Moisture Factor",
    part="mep",
    fields=[
        number("dryResistivityOhmM", "Dry-season resistivity", 150, unit="Ω·m", min=0.1),
        number("wetSeasonFactor", "Wet-season multiplier", 0.65, min=0.01, max=2),
    ],
    requires_project=False,
)
def moisture_factor(ctx: FeatureContext, v: dict) -> dict:
    """Estimate wet-season soil resistivity from a measured dry-season value."""
    return result(
        {"wetSeasonResistivityOhmM": v["dryResistivityOhmM"] * v["wetSeasonFactor"]},
        notes=["Multiplier must be calibrated from site seasonal measurements."],
    )


@feature(
    "mepElectricalEarthing.seasonalVariation",
    "Seasonal Variation",
    part="mep",
    fields=[
        number("referenceResistivityOhmM", "Reference resistivity", 100, unit="Ω·m", min=0.1),
        number("temperatureCoefficientPerC", "Temperature coefficient", 0.02, unit="1/°C"),
        number("temperatureChangeC", "Temperature change", -10, unit="°C"),
    ],
    requires_project=False,
)
def seasonal_variation(ctx: FeatureContext, v: dict) -> dict:
    """Apply a linear temperature correction to reference soil resistivity."""
    factor = 1 + v["temperatureCoefficientPerC"] * v["temperatureChangeC"]
    if factor <= 0:
        raise FeatureInputError("Temperature correction must remain positive.")
    return result(
        {
            "correctedResistivityOhmM": v["referenceResistivityOhmM"] * factor,
            "correctionFactor": factor,
        },
        notes=[
            "Linear correction is a simplified project input; confirm soil moisture and freeze effects."
        ],
    )


@feature(
    "mepElectricalEarthing.airTerminalGrid",
    "Air Terminal Grid",
    part="mep",
    fields=[
        number("roofLengthM", "Roof length", 40, unit="m", min=0),
        number("roofWidthM", "Roof width", 25, unit="m", min=0),
        number("gridSpacingM", "Terminal spacing", 10, unit="m", min=0.1),
    ],
    requires_project=False,
)
def air_terminal_grid(ctx: FeatureContext, v: dict) -> dict:
    """Estimate air-terminal grid count on a rectangular roof."""
    nx, ny = (
        math.ceil(v["roofLengthM"] / v["gridSpacingM"]) + 1,
        math.ceil(v["roofWidthM"] / v["gridSpacingM"]) + 1,
    )
    return result(
        {"terminalCountEstimate": nx * ny, "rows": ny, "columns": nx},
        notes=[
            "Regular-grid count only; rolling-sphere geometry, roof projections and protection class are not checked."
        ],
    )


@feature(
    "mepElectricalEarthing.downConductor",
    "Down Conductor",
    part="mep",
    fields=[
        number("buildingPerimeterM", "Building perimeter", 100, unit="m", min=0),
        number("maximumSpacingM", "Maximum spacing", 20, unit="m", min=0.1),
        number("storeyHeightM", "Down-run height", 15, unit="m", min=0),
    ],
    requires_project=False,
)
def down_conductor(ctx: FeatureContext, v: dict) -> dict:
    """Estimate perimeter down-conductor count and total vertical conductor length."""
    count = max(1, math.ceil(v["buildingPerimeterM"] / v["maximumSpacingM"]))
    return result(
        {"downConductorCount": count, "estimatedVerticalLengthM": count * v["storeyHeightM"]},
        notes=[
            "Uniform perimeter distribution; routing, bends, test joints and actual roof connection points are excluded."
        ],
    )


@feature(
    "mepElectricalEarthing.surgeProtectionZone",
    "Surge Protection Zone",
    part="mep",
    fields=[
        number("upstreamLevel", "Upstream protection level", 1, min=1),
        number("downstreamLevel", "Downstream protection level", 2, min=1),
        number("separationM", "Device separation", 10, unit="m", min=0),
    ],
    requires_project=False,
)
def surge_protection_zone(ctx: FeatureContext, v: dict) -> dict:
    """Check coordination order of entered surge-protection device levels."""
    return result(
        {
            "levelsInDescendingOrder": v["upstreamLevel"] <= v["downstreamLevel"],
            "separationM": v["separationM"],
        },
        notes=[
            "Device coordination depends on manufacturer energy coordination and connection lead lengths, not level labels alone."
        ],
    )


@feature(
    "mepElectricalEarthing.gprCalculation",
    "GPR Calculation",
    part="mep",
    fields=[
        number("faultCurrentA", "Ground fault current", 5000, unit="A", min=0),
        number("gridResistanceOhm", "Grid resistance", 0.5, unit="Ω", min=0),
    ],
    requires_project=False,
)
def gpr_calculation(ctx: FeatureContext, v: dict) -> dict:
    """Calculate ground potential rise from fault current and grid resistance."""
    return result(
        {"groundPotentialRiseV": v["faultCurrentA"] * v["gridResistanceOhm"]},
        notes=[
            "GPR=IgRg; current division, fault duration and transferred potentials are not included."
        ],
    )


@feature(
    "mepElectricalEarthing.meshVoltage",
    "Mesh Voltage",
    part="mep",
    fields=[
        number("soilResistivityOhmM", "Soil resistivity", 100, unit="Ω·m", min=0.1),
        number("gridCurrentA", "Grid current", 2000, unit="A", min=0),
        number("meshFactor", "Mesh factor", 0.7, min=0),
        number("gridLengthM", "Effective conductor length", 200, unit="m", min=0.1),
    ],
    requires_project=False,
)
def mesh_voltage(ctx: FeatureContext, v: dict) -> dict:
    """Estimate mesh voltage using the entered geometry factor."""
    voltage = v["soilResistivityOhmM"] * v["gridCurrentA"] * v["meshFactor"] / v["gridLengthM"]
    return result(
        {"estimatedMeshVoltageV": voltage},
        notes=[
            "Simplified screening equation; step/touch safety requires detailed grid geometry and current-distribution analysis."
        ],
    )


@feature(
    "mepElectricalEarthing.gridConductorSize",
    "Grid Conductor Size",
    part="mep",
    fields=[
        number("faultCurrentA", "Fault current", 5000, unit="A", min=0),
        number("clearingTimeS", "Clearing time", 0.5, unit="s", min=0.001),
        number("kFactor", "Material factor", 115, min=1),
    ],
    requires_project=False,
)
def grid_conductor_size(ctx: FeatureContext, v: dict) -> dict:
    """Size a buried earthing conductor by the adiabatic short-circuit relation."""
    area = v["faultCurrentA"] * math.sqrt(v["clearingTimeS"]) / v["kFactor"]
    return result(
        {"minimumAreaMm2": area},
        notes=[
            "S=I√t/k; select a suitable commercial conductor and verify corrosion, mechanical strength, joints and applicable requirements."
        ],
    )
