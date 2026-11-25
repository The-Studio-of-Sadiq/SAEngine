"""HVAC system checks, energy estimates and calculation records."""

from __future__ import annotations

from saengine.features import FeatureContext, FeatureInputError, feature, number, result, table


@feature(
    "mepHvacAnalysis.systemBalancing",
    "System Balancing",
    part="mep",
    fields=[
        number("branchDesignLs", "Branch design airflow", 180, unit="L/s", min=0.1),
        number("branchMeasuredLs", "Branch measured airflow", 165, unit="L/s", min=0),
        number("availablePressurePa", "Available balancing pressure", 35, unit="Pa", min=0),
        number("damperLossCoefficient", "Damper loss coefficient", 2.0, min=0),
    ],
    requires_project=False,
)
def system_balancing(ctx: FeatureContext, values: dict) -> dict:
    """Calculate branch airflow deviation and damper pressure requirement."""
    deviation = (values["branchMeasuredLs"] - values["branchDesignLs"]) / values["branchDesignLs"]
    velocity_pressure = 0.6 * (values["branchMeasuredLs"] / 100) ** 2
    needed = values["damperLossCoefficient"] * velocity_pressure
    return result(
        summary={
            "airflowDeviationPercent": deviation * 100,
            "damperLossPa": needed,
            "pressureAvailablePa": values["availablePressurePa"],
        },
        notes=[
            "Balancing pressure uses an approximate air dynamic pressure at the measured flow; use branch dimensions and damper data for final setting."
        ],
    )


@feature(
    "mepHvacAnalysis.fanPowerCheck",
    "Fan Power Check",
    part="mep",
    fields=[
        number("airflowM3s", "Fan airflow", 2, unit="m³/s", min=0.001),
        number("totalPressurePa", "Fan total pressure", 600, unit="Pa", min=0),
        number("fanEfficiency", "Fan total efficiency", 0.65, min=0.05, max=1),
        number("motorEfficiency", "Motor efficiency", 0.9, min=0.05, max=1),
        number(
            "maximumSpecificPowerWPerLs", "Maximum specific fan power", 2, unit="W/(L/s)", min=0.01
        ),
    ],
    requires_project=False,
)
def fan_power_check(ctx: FeatureContext, values: dict) -> dict:
    """Check fan and motor input power against the entered specific-power limit."""
    shaft_kw = values["airflowM3s"] * values["totalPressurePa"] / 1000 / values["fanEfficiency"]
    input_kw = shaft_kw / values["motorEfficiency"]
    specific = input_kw * 1000 / (values["airflowM3s"] * 1000)
    return result(
        summary={
            "inputPowerKw": input_kw,
            "specificFanPowerWPerLs": specific,
            "passes": specific <= values["maximumSpecificPowerWPerLs"],
        },
        notes=[
            "Specific fan power is electrical input divided by delivered airflow; pressure and efficiencies are entered at the selected operating point."
        ],
    )


@feature(
    "mepHvacAnalysis.ductLeakage",
    "Duct Leakage",
    part="mep",
    fields=[
        number("ductSurfaceM2", "Tested duct surface", 40, unit="m²", min=0),
        number(
            "leakageCoefficientLsM2", "Leakage rate per surface area", 0.5, unit="L/(s·m²)", min=0
        ),
        number("fanFlowLs", "Fan design flow", 900, unit="L/s", min=0.1),
        number("testPressurePa", "Leakage test pressure", 500, unit="Pa", min=0),
    ],
    requires_project=False,
)
def duct_leakage(ctx: FeatureContext, values: dict) -> dict:
    """Estimate duct leakage flow and its share of fan design airflow."""
    leakage = values["ductSurfaceM2"] * values["leakageCoefficientLsM2"]
    return result(
        summary={
            "leakageFlowLs": leakage,
            "leakagePercentOfFanFlow": 100 * leakage / values["fanFlowLs"],
            "testPressurePa": values["testPressurePa"],
        },
        notes=[
            "Leakage rate is an entered pressure-class test criterion; actual leakage depends on duct construction, joints and measured test pressure."
        ],
    )


@feature(
    "mepHvacAnalysis.cfdRoomStudy",
    "CFD Room Study",
    part="mep",
    fields=[
        number("roomVolumeM3", "Room air volume", 120, unit="m³", min=0.1),
        number("supplyFlowLs", "Supply airflow", 300, unit="L/s", min=0),
        number("roomHeatLoadKw", "Sensible room heat load", 4, unit="kW", min=0),
        number("supplyTemperatureC", "Supply air temperature", 14, unit="°C"),
        number("roomTemperatureC", "Room design temperature", 24, unit="°C"),
    ],
    requires_project=False,
)
def cfd_room_study(ctx: FeatureContext, values: dict) -> dict:
    """Provide an ideal-mixing screening state for a room airflow study."""
    ach = values["supplyFlowLs"] * 3.6 / values["roomVolumeM3"]
    mass_flow = values["supplyFlowLs"] / 1000 * 1.2
    sensible_kw = mass_flow * 1.006 * (values["roomTemperatureC"] - values["supplyTemperatureC"])
    return result(
        summary={
            "airChangesPerHour": ach,
            "idealSensibleCapacityKw": sensible_kw,
            "loadCoverageRatio": sensible_kw / values["roomHeatLoadKw"]
            if values["roomHeatLoadKw"]
            else None,
        },
        notes=[
            "This well-mixed heat-balance screening calculation is not a CFD solver and does not resolve jets, stratification, comfort indices or room geometry."
        ],
    )


@feature(
    "mepHvacAnalysis.thermalMass",
    "Thermal Mass",
    part="mep",
    fields=[
        number("exposedConcreteAreaM2", "Exposed concrete area", 80, unit="m²", min=0),
        number("thicknessM", "Concrete thickness", 0.15, unit="m", min=0.01),
        number("densityKgM3", "Concrete density", 2300, unit="kg/m³", min=1),
        number("specificHeatJkgK", "Specific heat capacity", 880, unit="J/(kg·K)", min=1),
        number("zoneAirCapacityKjK", "Zone air and contents capacity", 250, unit="kJ/K", min=0),
    ],
    requires_project=False,
)
def thermal_mass(ctx: FeatureContext, values: dict) -> dict:
    """Calculate exposed concrete heat capacity and a normalized zone time constant."""
    concrete_capacity = (
        values["exposedConcreteAreaM2"]
        * values["thicknessM"]
        * values["densityKgM3"]
        * values["specificHeatJkgK"]
        / 1000
    )
    total = concrete_capacity + values["zoneAirCapacityKjK"]
    return result(
        summary={
            "concreteCapacityKjK": concrete_capacity,
            "totalCapacityKjK": total,
            "capacityPerAreaKjM2K": total / values["exposedConcreteAreaM2"]
            if values["exposedConcreteAreaM2"]
            else None,
        },
        notes=[
            "Sensible thermal capacity is mass × specific heat; exposed-area participation and dynamic response require a transient building model."
        ],
    )


@feature(
    "mepHvacAnalysis.internalGainProfile",
    "Internal Gain Profile",
    part="mep",
    fields=[
        number("occupants", "Design occupants", 20, min=0),
        number("sensiblePerPersonW", "Sensible gain per person", 75, unit="W/person", min=0),
        number("lightingLoadW", "Lighting load", 800, unit="W", min=0),
        number("equipmentLoadW", "Equipment load", 1200, unit="W", min=0),
        number("occupancyFraction", "Scheduled occupancy fraction", 0.85, min=0, max=1),
        number("equipmentFraction", "Scheduled equipment fraction", 0.7, min=0, max=1),
    ],
    requires_project=False,
)
def internal_gain_profile(ctx: FeatureContext, values: dict) -> dict:
    """Calculate scheduled sensible gains from people, lights and equipment."""
    people = values["occupants"] * values["sensiblePerPersonW"]
    scheduled = (
        people * values["occupancyFraction"]
        + values["lightingLoadW"] * values["occupancyFraction"]
        + values["equipmentLoadW"] * values["equipmentFraction"]
    )
    return result(
        summary={
            "designSensibleGainW": people + values["lightingLoadW"] + values["equipmentLoadW"],
            "scheduledSensibleGainW": scheduled,
        },
        notes=[
            "People, lighting and equipment gains are sensible loads; schedule fractions are applied to the corresponding contributions."
        ],
    )


def _hvac(ctx: FeatureContext) -> dict:
    raw = ctx.raw("mep")
    hvac = raw.get("hvac") if raw else None
    if not isinstance(hvac, dict):
        raise FeatureInputError("Add HVAC design data to 07 MEP/mep.json first.")
    return hvac


@feature("mepHvacAnalysis.energyReport", "Energy Report", part="mep", requires_project=True)
def energy_report(ctx: FeatureContext, values: dict) -> dict:
    """Summarize project HVAC system, conditioned stories and installed plant."""
    hvac = _hvac(ctx)
    stories = hvac.get("stories", [])
    plant = hvac.get("plant", [])
    rows = [
        {
            "story": s.get("story", ""),
            "use": s.get("use", ""),
            "conditioned": bool(s.get("conditioned", False)),
            "occupants": s.get("occupants", 0),
        }
        for s in stories
    ]
    return result(
        summary={
            "system": hvac.get("system", "unspecified"),
            "conditionedStories": sum(row["conditioned"] for row in rows),
            "plantItems": len(plant),
        },
        tables=[
            table(
                "HVAC energy inputs",
                [
                    ("story", "Story"),
                    ("use", "Use"),
                    ("conditioned", "Conditioned"),
                    ("occupants", "Occupants"),
                ],
                rows,
            )
        ],
        notes=[
            "The project currently provides design configuration only; annual energy and monthly consumption require weather, schedules and plant performance data."
        ],
    )


@feature("mepHvacAnalysis.calculationNotes", "Calculation Notes", part="mep", requires_project=True)
def calculation_notes(ctx: FeatureContext, values: dict) -> dict:
    """List project HVAC assumptions that can be read from model data."""
    hvac = _hvac(ctx)
    notes = [
        {"input": "system", "value": hvac.get("system", "not specified")},
        {"input": "stories", "value": len(hvac.get("stories", []))},
        {"input": "plant", "value": len(hvac.get("plant", []))},
        {"input": "ducts", "value": len(hvac.get("ducts", []))},
        {
            "input": "envelope",
            "value": ", ".join(f"{key}={value}" for key, value in hvac.get("envelope", {}).items()),
        },
    ]
    return result(
        summary={"documentedInputCount": len(notes)},
        tables=[
            table(
                "HVAC calculation inputs", [("input", "Input"), ("value", "Project value")], notes
            )
        ],
        notes=[
            "This inventory records supplied inputs only and does not imply a load calculation has been performed."
        ],
    )


@feature("mepHvacAnalysis.designBrief", "Design Brief", part="mep", requires_project=True)
def design_brief(ctx: FeatureContext, values: dict) -> dict:
    """Compile the HVAC scope and model quantities into a concise design brief."""
    hvac = _hvac(ctx)
    story_rows = [
        {
            "story": row.get("story", ""),
            "use": row.get("use", ""),
            "occupants": row.get("occupants", 0),
            "conditioned": bool(row.get("conditioned", False)),
        }
        for row in hvac.get("stories", [])
    ]
    return result(
        summary={
            "systemType": hvac.get("system", "unspecified"),
            "zoneCount": len(story_rows),
            "equipmentCount": len(hvac.get("plant", [])),
            "ductRunCount": len(hvac.get("ducts", [])),
        },
        tables=[
            table(
                "HVAC design brief",
                [
                    ("story", "Story"),
                    ("use", "Use"),
                    ("occupants", "Occupants"),
                    ("conditioned", "Conditioned"),
                ],
                story_rows,
            )
        ],
        notes=[
            "Brief is generated from currently modeled HVAC configuration; loads, schedules and performance targets must be added to complete design documentation."
        ],
    )
