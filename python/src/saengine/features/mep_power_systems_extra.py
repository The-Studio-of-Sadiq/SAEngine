"""Power-system calculations and project schedules not covered by the primary tools."""

from __future__ import annotations

import math

from saengine.electrical.short_circuit import check_disconnection
from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    table,
)


@feature(
    "mepPowerSystems.emergencyLighting",
    "Emergency Lighting",
    part="mep",
    fields=[
        number("area", "Floor area", 80, unit="m²", min=0.1),
        number("targetLux", "Maintained illuminance", 1, unit="lx", min=0.1),
        number("lumens", "Luminaire output", 250, unit="lm", min=1),
        number("utilization", "Utilization factor", 0.35, min=0.01, max=1),
        number("maintenance", "Maintenance factor", 0.8, min=0.01, max=1),
    ],
    requires_project=False,
)
def emergency_lighting(ctx: FeatureContext, values: dict) -> dict:
    """Estimate emergency luminaire quantity using the lumen method."""
    useful_lumens = values["lumens"] * values["utilization"] * values["maintenance"]
    quantity = math.ceil(values["area"] * values["targetLux"] / useful_lumens)
    achieved_lux = quantity * useful_lumens / values["area"]
    return result(
        summary={"luminaireCount": quantity, "maintainedLux": achieved_lux},
        tables=[
            table(
                "Emergency lighting estimate",
                [("item", "Quantity"), ("value", "Result")],
                [
                    {"item": "Required luminaires", "value": quantity},
                    {"item": "Estimated maintained illuminance", "value": achieved_lux},
                ],
            )
        ],
        notes=[
            (
                "Lumen method: N = E·A/(Φ·UF·MF); this average illuminance estimate does not "
                "check escape-route spacing, uniformity, glare, or battery duration."
            )
        ],
    )


@feature(
    "mepPowerSystems.lightingCircuits",
    "Lighting Circuits",
    part="mep",
    fields=[
        number("luminaireCount", "Luminaire count", 12, unit="items", min=1),
        number("wattage", "Luminaire input power", 36, unit="W", min=0.1),
        number("voltage", "Circuit voltage", 230, unit="V", min=1),
        number("powerFactor", "Power factor", 0.9, min=0.1, max=1),
        number("rating", "Circuit current rating", 10, unit="A", min=0.1),
        number("utilization", "Maximum circuit utilization", 0.8, min=0.1, max=1),
    ],
    requires_project=False,
)
def lighting_circuits(ctx: FeatureContext, values: dict) -> dict:
    """Calculate lighting circuit current and the minimum number of loaded circuits."""
    total_w = values["luminaireCount"] * values["wattage"]
    current = total_w / (values["voltage"] * values["powerFactor"])
    usable_current = values["rating"] * values["utilization"]
    circuits = math.ceil(current / usable_current)
    return result(
        summary={
            "connectedLoadW": total_w,
            "designCurrentA": current,
            "circuitCount": circuits,
            "luminairesPerCircuit": math.ceil(values["luminaireCount"] / circuits),
        },
        tables=[
            table(
                "Lighting circuit loading",
                [("item", "Quantity"), ("value", "Result")],
                [
                    {"item": "Total luminaire load", "value": total_w},
                    {"item": "Calculated current", "value": current},
                    {"item": "Circuits at utilization limit", "value": circuits},
                ],
            )
        ],
        notes=[
            (
                "Single-phase current uses P/(V·pf); circuit count is a preliminary loading split "
                "and does not verify cable capacity, voltage drop, switching inrush, or protection."
            )
        ],
    )


@feature(
    "mepPowerSystems.generatorSizing",
    "Generator Sizing",
    part="mep",
    fields=[
        number("essentialLoad", "Essential running load", 60, unit="kW", min=0.1),
        number("powerFactor", "Running-load power factor", 0.85, min=0.1, max=1),
        number("largestMotor", "Largest motor input", 15, unit="kW", min=0),
        number("startingMultiplier", "Motor starting multiplier", 3, min=1),
        number("margin", "Capacity margin", 1.15, min=1, max=2),
    ],
    requires_project=False,
)
def generator_sizing(ctx: FeatureContext, values: dict) -> dict:
    """Estimate standby generator capacity from running load and largest-motor starting demand."""
    running_kva = values["essentialLoad"] / values["powerFactor"]
    motor_start_kva = values["largestMotor"] * values["startingMultiplier"] / values["powerFactor"]
    incremental_start_kva = max(
        0.0, motor_start_kva - values["largestMotor"] / values["powerFactor"]
    )
    required_kva = (running_kva + incremental_start_kva) * values["margin"]
    return result(
        summary={
            "runningDemandKva": running_kva,
            "startingIncrementKva": incremental_start_kva,
            "requiredGeneratorKva": required_kva,
        },
        tables=[
            table(
                "Standby generator demand",
                [("item", "Demand"), ("value", "kVA")],
                [
                    {"item": "Essential running demand", "value": running_kva},
                    {"item": "Largest-motor starting increment", "value": incremental_start_kva},
                    {"item": "Required capacity with margin", "value": required_kva},
                ],
            )
        ],
        notes=[
            (
                "The largest motor's starting demand is added above its running demand. Confirm "
                "alternator transient performance, load sequence, harmonics, and site derating."
            )
        ],
    )


@feature(
    "mepPowerSystems.fuelStorage",
    "Fuel Storage",
    part="mep",
    fields=[
        number("generatorLoad", "Generator electrical load", 100, unit="kW", min=0.1),
        number("specificConsumption", "Fuel consumption", 0.27, unit="L/kWh", min=0.01),
        number("autonomy", "Required autonomy", 24, unit="h", min=0.1),
        number("reserve", "Usable reserve", 10, unit="%", min=0, max=90),
    ],
    requires_project=False,
)
def fuel_storage(ctx: FeatureContext, values: dict) -> dict:
    """Size usable generator fuel volume for a specified load and autonomy."""
    net_l = values["generatorLoad"] * values["specificConsumption"] * values["autonomy"]
    gross_l = net_l / (1 - values["reserve"] / 100)
    return result(
        summary={
            "netFuelL": net_l,
            "tankCapacityL": gross_l,
            "autonomyH": values["autonomy"],
        },
        tables=[
            table(
                "Generator fuel storage",
                [("item", "Value"), ("capacity", "Value"), ("unit", "Unit")],
                [
                    {"item": "Net consumption", "capacity": net_l, "unit": "L"},
                    {"item": "Tank capacity including reserve", "capacity": gross_l, "unit": "L"},
                ],
            )
        ],
        notes=[
            (
                "Volume = electrical load × specific fuel consumption × autonomy; tank gross "
                "volume allows the specified reserve fraction and excludes unusable heel and "
                "expansion space."
            )
        ],
    )


@feature(
    "mepPowerSystems.loadShedding",
    "Load Shedding",
    part="mep",
    fields=[
        number("availablePower", "Available source power", 100, unit="kW", min=0.1),
        number("stageOne", "Stage 1 shedding", 10, unit="%", min=0, max=100),
        number("stageTwo", "Stage 2 shedding", 20, unit="%", min=0, max=100),
        number("stageThree", "Stage 3 shedding", 30, unit="%", min=0, max=100),
        number("reserve", "Protected reserve", 10, unit="%", min=0, max=90),
    ],
    requires_project=False,
)
def load_shedding(ctx: FeatureContext, values: dict) -> dict:
    """Calculate staged load reductions while retaining the protected essential reserve."""
    available = values["availablePower"] * (1 - values["reserve"] / 100)
    reductions = [values["stageOne"], values["stageTwo"], values["stageThree"]]
    if any(reductions[i] < reductions[i - 1] for i in range(1, len(reductions))):
        raise FeatureInputError("Shedding percentages must increase or remain equal by stage.")
    rows = [
        {
            "stage": index,
            "shedKw": values["availablePower"] * percent / 100,
            "retainedKw": values["availablePower"] * (1 - percent / 100),
            "withinAvailable": values["availablePower"] * (1 - percent / 100) <= available,
        }
        for index, percent in enumerate(reductions, start=1)
    ]
    return result(
        summary={"protectedAvailableKw": available, "stageCount": len(rows)},
        tables=[
            table(
                "Load shedding stages",
                [
                    ("stage", "Stage"),
                    ("shedKw", "Shed load", "kW"),
                    ("retainedKw", "Retained load", "kW"),
                    ("withinAvailable", "Within available power"),
                ],
                rows,
            )
        ],
        notes=[
            (
                "Stages apply the entered shedding percentages to source capacity; assign actual "
                "non-essential circuits and verify their switching priorities in the control system."
            )
        ],
    )


@feature(
    "mepPowerSystems.arcFlashStudy",
    "Arc Flash Study",
    part="mep",
    fields=[
        number("arcPower", "Arc power", 25, unit="kW", min=0.1),
        number("duration", "Arc duration", 0.1, unit="s", min=0.001),
        number("distance", "Working distance", 0.45, unit="m", min=0.05),
        number("radiantFraction", "Radiated energy fraction", 0.2, min=0, max=1),
        number("boundaryEnergy", "Boundary incident energy", 5, unit="kJ/m²", min=0.1),
    ],
    requires_project=False,
)
def arc_flash_study(ctx: FeatureContext, values: dict) -> dict:
    """Estimate radiated arc energy and an inverse-square screening distance."""
    radiated_j = values["arcPower"] * 1000 * values["duration"] * values["radiantFraction"]
    incident_j_m2 = radiated_j / (4 * math.pi * values["distance"] ** 2)
    boundary_m = math.sqrt(radiated_j / (4 * math.pi * values["boundaryEnergy"] * 1000))
    return result(
        summary={
            "radiatedEnergyJ": radiated_j,
            "incidentEnergyKjPerM2": incident_j_m2 / 1000,
            "screeningBoundaryM": boundary_m,
        },
        tables=[
            table(
                "Arc energy screening",
                [("quantity", "Quantity"), ("value", "Value")],
                [
                    {
                        "quantity": "Incident energy at working distance",
                        "value": incident_j_m2 / 1000,
                    },
                    {"quantity": "Distance to selected incident-energy level", "value": boundary_m},
                ],
            )
        ],
        notes=[
            (
                "Conservative point-source radiation screening (uniform isotropic radiation and "
                "entered arc power); not an arc-flash hazard calculation. Establish fault current, "
                "arc duration, enclosure geometry, and PPE boundaries in a qualified study."
            )
        ],
    )


@feature(
    "mepPowerSystems.earthFaultLoop",
    "Earth Fault Loop",
    part="mep",
    fields=[
        number("impedance", "Measured loop impedance", 0.45, unit="Ω", min=0.001),
        number("rating", "Protective-device rating", 32, unit="A", min=0.1),
        number("voltage", "Phase-to-earth voltage", 230, unit="V", min=1),
    ],
    requires_project=False,
)
def earth_fault_loop(ctx: FeatureContext, values: dict) -> dict:
    """Check measured fault-loop impedance against the active protective-device data."""
    check = check_disconnection(values["impedance"], values["rating"], voltage_0=values["voltage"])
    return result(
        summary={
            "loopImpedanceOhm": values["impedance"],
            "maximumImpedanceOhm": check["zsMaxOhm"],
            "prospectiveFaultCurrentA": check["ik1MinA"],
            "compliant": check["ok"],
        },
        tables=[
            table(
                "Earth-fault loop check",
                [("item", "Measured / calculated"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Measured loop impedance", "value": values["impedance"], "unit": "Ω"},
                    {
                        "item": "Maximum permitted impedance",
                        "value": check["zsMaxOhm"],
                        "unit": "Ω",
                    },
                    {"item": "Prospective fault current", "value": check["ik1MinA"], "unit": "A"},
                ],
            )
        ],
        notes=[check.get("note", "Loop impedance is within the active trip limit.")],
    )


@feature(
    "mepPowerSystems.meterSchedule",
    "Meter Schedule",
    part="mep",
    fields=[],
    requires_project=True,
)
def meter_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Tabulate project distribution boards and circuits as electrical metering points."""
    from saengine.library.mep import parse

    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add electrical boards and circuits to 07 MEP/mep.json.")
    model = parse(__import__("json").dumps(raw))
    if model.electrical is None or not model.electrical.boards:
        raise FeatureInputError("Add an electrical distribution board before scheduling meters.")
    rows = []
    for board in model.electrical.boards:
        for circuit in board.circuits:
            watts = circuit.loadW
            if watts is None and circuit.loadVA is not None:
                watts = circuit.loadVA * (circuit.powerFactor or 1.0)
            rows.append(
                {
                    "board": board.id,
                    "circuit": circuit.id,
                    "description": circuit.description,
                    "room": circuit.room or board.room or "",
                    "connectedLoadW": watts,
                    "meteringPoint": f"{board.id}/{circuit.id}",
                }
            )
    return result(
        summary={"boardCount": len(model.electrical.boards), "meterPointCount": len(rows)},
        tables=[
            table(
                "Electrical meter schedule",
                [
                    ("board", "Board"),
                    ("circuit", "Circuit"),
                    ("description", "Description"),
                    ("room", "Room"),
                    ("connectedLoadW", "Connected load", "W"),
                    ("meteringPoint", "Metering point"),
                ],
                rows,
            )
        ],
        notes=[
            (
                "Metering points are derived from modeled boards and circuits; connected power "
                "is taken from circuit watts or calculated as VA × entered power factor."
            )
        ],
    )


@feature(
    "mepPowerSystems.energyMonitoring",
    "Energy Monitoring",
    part="mep",
    fields=[
        number("targetKwh", "Reporting-period energy target", 10000, unit="kWh", min=0),
        number("periodDays", "Reporting period", 30, unit="days", min=1),
    ],
    requires_project=True,
)
def energy_monitoring(ctx: FeatureContext, values: dict) -> dict:
    """Map modeled distribution boards and circuits to project energy-monitoring points."""
    from saengine.library.mep import parse

    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add electrical boards and circuits to 07 MEP/mep.json.")
    model = parse(__import__("json").dumps(raw))
    if model.electrical is None or not model.electrical.boards:
        raise FeatureInputError(
            "Add electrical boards and circuits before defining monitor points."
        )
    points = []
    for board in model.electrical.boards:
        points.append(
            {
                "point": f"{board.id}.importEnergy",
                "source": board.name or board.id,
                "quantity": "active energy import",
                "intervalDays": values["periodDays"],
                "targetKwh": values["targetKwh"],
            }
        )
        for circuit in board.circuits:
            if circuit.loadW is not None or circuit.loadVA is not None:
                points.append(
                    {
                        "point": f"{board.id}.{circuit.id}.power",
                        "source": circuit.description or circuit.id,
                        "quantity": "circuit active power",
                        "intervalDays": values["periodDays"],
                        "targetKwh": None,
                    }
                )
    return result(
        summary={
            "monitorPointCount": len(points),
            "reportingPeriodDays": values["periodDays"],
            "targetKwh": values["targetKwh"],
        },
        tables=[
            table(
                "Energy monitoring points",
                [
                    ("point", "Point"),
                    ("source", "Board / circuit"),
                    ("quantity", "Measured quantity"),
                    ("intervalDays", "Period", "days"),
                    ("targetKwh", "Energy target", "kWh"),
                ],
                points,
            )
        ],
        notes=[
            (
                "Board totals are mapped to import-energy meters; modeled loaded circuits are "
                "listed as power submeter points. The target is a reporting value, not predicted "
                "consumption."
            )
        ],
    )
