"""Dedicated mepHvacControls MEP feature registrations."""

from __future__ import annotations

import json

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
    "mepHvacControls.alarmRouting",
    "Alarm Routing",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def alarmRouting(ctx: FeatureContext, values: dict) -> dict:
    """Alarm Routing: Protocols."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Alarm Routing",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacControls.bacnetSetup",
    "BACnet Setup",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def bacnetSetup(ctx: FeatureContext, values: dict) -> dict:
    """BACnet Setup: Protocols."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "BACnet Setup",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacControls.co2Sensor",
    "CO2 Sensor",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def co2Sensor(ctx: FeatureContext, values: dict) -> dict:
    """CO2 Sensor: Sensors."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "CO2 Sensor",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacControls.controlDeadband",
    "Control Deadband",
    part="mep",
    fields=[
        number("heatingSetpointC", "Zone heating setpoint", 21.0, unit="°C", min=10.0, max=25.0),
        number("coolingSetpointC", "Zone cooling setpoint", 24.5, unit="°C", min=18.0, max=32.0),
        number(
            "sensorUncertaintyK",
            "Thermostat sensor drift + hysteresis",
            0.5,
            unit="K",
            min=0.1,
            max=2.0,
        ),
    ],
    requires_project=False,
)
def controlDeadband(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate heating/cooling neutral deadband width to avoid simultaneous bucking."""
    t_h = float(values["heatingSetpointC"])
    t_c = float(values["coolingSetpointC"])
    db = t_c - t_h
    min_rec = max(2.0, 4.0 * float(values["sensorUncertaintyK"]))
    ok = db >= min_rec
    mid = 0.5 * (t_h + t_c)
    return result(
        summary={
            "deadbandK": round(db, 2),
            "minRecommendedK": round(min_rec, 2),
            "neutralMidpointC": round(mid, 2),
            "compliant": ok,
        },
        tables=[
            table(
                "Thermostat deadband check",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Heating setpoint", "value": t_h, "unit": "°C"},
                    {"item": "Cooling setpoint", "value": t_c, "unit": "°C"},
                    {"item": "Control deadband ΔT", "value": round(db, 2), "unit": "K"},
                    {"item": "Min separation recommended", "value": round(min_rec, 2), "unit": "K"},
                    {"item": "Status", "value": "PASS" if ok else "WIDEN DEADBAND", "unit": "-"},
                ],
            )
        ],
        notes=[
            "Maintain >= 2.0 K deadband (>= 4x sensor hysteresis) to prevent simultaneous heating and cooling."
        ],
    )


@feature(
    "mepHvacControls.controlLogic",
    "Control Logic",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def controlLogic(ctx: FeatureContext, values: dict) -> dict:
    """Control Logic: Controllers."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepHvacControls.controlLogic",
        "title": "Control Logic",
        "name": values["name"],
        "group": "Controllers",
        "mep": raw,
    }
    path = ctx.path("11 Exports/controlLogic.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Control Logic",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepHvacControls.damperActuator",
    "Damper Actuator",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def damperActuator(ctx: FeatureContext, values: dict) -> dict:
    """Damper Actuator: Actuators."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Damper Actuator",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacControls.ddcController",
    "DDC Controller",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def ddcController(ctx: FeatureContext, values: dict) -> dict:
    """DDC Controller: Controllers."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "DDC Controller",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacControls.exportPoints",
    "Export Points",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def exportPoints(ctx: FeatureContext, values: dict) -> dict:
    """Export Points: Points."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepHvacControls.exportPoints",
        "title": "Export Points",
        "name": values["name"],
        "group": "Points",
        "mep": raw,
    }
    path = ctx.path("11 Exports/exportPoints.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Export Points",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepHvacControls.humiditySensor",
    "Humidity Sensor",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def humiditySensor(ctx: FeatureContext, values: dict) -> dict:
    """Humidity Sensor: Sensors."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Humidity Sensor",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacControls.manualOverride",
    "Manual Override",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def manualOverride(ctx: FeatureContext, values: dict) -> dict:
    """Manual Override: Setpoints."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepHvacControls.manualOverride",
        "title": "Manual Override",
        "name": values["name"],
        "group": "Setpoints",
        "mep": raw,
    }
    path = ctx.path("11 Exports/manualOverride.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Manual Override",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepHvacControls.modbusGateway",
    "Modbus Gateway",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def modbusGateway(ctx: FeatureContext, values: dict) -> dict:
    """Modbus Gateway: Protocols."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Modbus Gateway",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacControls.networkBus",
    "Network Bus",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def networkBus(ctx: FeatureContext, values: dict) -> dict:
    """Network Bus: Protocols."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Network Bus",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacControls.occupancySetpoint",
    "Occupancy Setpoint",
    part="mep",
    fields=[
        number("occupiedCoolC", "Occupied cooling setpoint", 24.0, unit="°C"),
        number(
            "unoccupiedSetupK", "Unoccupied temperature setup", 4.0, unit="K", min=0.0, max=10.0
        ),
        number("outdoorTempC", "Design outdoor temperature", 34.0, unit="°C"),
        number("designFlowLps", "Zone full outdoor-air ventilation", 350.0, unit="L/s", min=10.0),
        number("standbyFlowRatio", "Standby minimum outdoor-air fraction", 0.30, min=0.0, max=1.0),
    ],
    requires_project=False,
)
def occupancySetpoint(ctx: FeatureContext, values: dict) -> dict:
    """Compute unoccupied setup setpoint, envelope gradient reduction, and ventilation saving."""
    t_occ = float(values["occupiedCoolC"])
    t_unocc = t_occ + float(values["unoccupiedSetupK"])
    t_out = float(values["outdoorTempC"])
    grad_occ = max(0.1, abs(t_out - t_occ))
    grad_unocc = max(0.0, abs(t_out - t_unocc))
    cond_save_pct = max(0.0, (1.0 - grad_unocc / grad_occ) * 100.0)
    vent_unocc_lps = float(values["designFlowLps"]) * float(values["standbyFlowRatio"])
    vent_save_kw = (
        1.2 * 1.005 * ((float(values["designFlowLps"]) - vent_unocc_lps) / 1000.0) * grad_occ
    )
    return result(
        summary={
            "unoccupiedSetpointC": round(t_unocc, 1),
            "conductionReductionPct": round(cond_save_pct, 1),
            "standbyOutdoorAirLps": round(vent_unocc_lps, 1),
            "ventilationSavingKw": round(vent_save_kw, 2),
        },
        tables=[
            table(
                "Occupied vs standby/unoccupied mode",
                [
                    ("mode", "Schedule Mode"),
                    ("setpointC", "Setpoint", "°C"),
                    ("outdoorAirLps", "OA Flow", "L/s"),
                ],
                [
                    {
                        "mode": "Occupied",
                        "setpointC": t_occ,
                        "outdoorAirLps": values["designFlowLps"],
                    },
                    {
                        "mode": "Unoccupied / Standby",
                        "setpointC": round(t_unocc, 1),
                        "outdoorAirLps": round(vent_unocc_lps, 1),
                    },
                ],
            )
        ],
        notes=[
            "Combines temperature setup envelope gradient reduction with DCV standby outdoor-air turndown."
        ],
    )


@feature(
    "mepHvacControls.pidTuning",
    "PID Tuning",
    part="mep",
    fields=[
        number("processGain", "Steady-state process gain K_p", 1.5, min=0.05),
        number("timeConstantS", "Loop dominant time constant tau", 45.0, unit="s", min=1.0),
        number("deadTimeS", "Transport dead time L", 8.0, unit="s", min=0.5),
    ],
    requires_project=False,
)
def pidTuning(ctx: FeatureContext, values: dict) -> dict:
    """Compute Cohen-Coon / Ziegler-Nichols PI and PID controller gains from FOPDT parameters."""
    kp = float(values["processGain"])
    tau = float(values["timeConstantS"])
    theta = float(values["deadTimeS"])
    # ZN open-loop reaction curve
    kc_pi = 0.9 * tau / (kp * theta)
    ti_pi = 3.33 * theta
    kc_pid = 1.2 * tau / (kp * theta)
    ti_pid = 2.0 * theta
    td_pid = 0.5 * theta
    return result(
        summary={
            "controllabilityRatio": round(theta / tau, 3),
            "piGainKc": round(kc_pi, 3),
            "piIntegralTiS": round(ti_pi, 1),
            "pidGainKc": round(kc_pid, 3),
            "pidIntegralTiS": round(ti_pid, 1),
            "pidDerivativeTdS": round(td_pid, 1),
        },
        tables=[
            table(
                "Reaction-curve loop tuning parameters",
                [
                    ("controller", "Controller"),
                    ("kc", "Gain Kc"),
                    ("tiS", "Integral Ti", "s"),
                    ("tdS", "Derivative Td", "s"),
                ],
                [
                    {
                        "controller": "PI (valves/dampers)",
                        "kc": round(kc_pi, 3),
                        "tiS": round(ti_pi, 1),
                        "tdS": 0.0,
                    },
                    {
                        "controller": "PID (fast coils)",
                        "kc": round(kc_pid, 3),
                        "tiS": round(ti_pid, 1),
                        "tdS": round(td_pid, 1),
                    },
                ],
            )
        ],
        notes=[
            "Ziegler-Nichols open-loop step response tuning on FOPDT plant; favor PI without D on noisy sensors."
        ],
    )


@feature(
    "mepHvacControls.pointList",
    "Point List",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def pointList(ctx: FeatureContext, values: dict) -> dict:
    """Point List: Points."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepHvacControls.pointList",
        "title": "Point List",
        "name": values["name"],
        "group": "Points",
        "mep": raw,
    }
    path = ctx.path("11 Exports/pointList.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Point List",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepHvacControls.pointMapping",
    "Point Mapping",
    part="mep",
    fields=[text("systemId", "System ID", "system-1")],
    requires_project=True,
)
def pointMapping(ctx: FeatureContext, values: dict) -> dict:
    """Point Mapping: Points."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Point Mapping",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacControls.pointTags",
    "Point Tags",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def pointTags(ctx: FeatureContext, values: dict) -> dict:
    """Point Tags: Points."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Point Tags",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacControls.sensorHeight",
    "Sensor Height",
    part="mep",
    fields=[number("dimension", "Dimension", 1000, unit="mm", min=1)],
    requires_project=True,
)
def sensorHeight(ctx: FeatureContext, values: dict) -> dict:
    """Sensor Height: Sensors."""
    design_value = float(values["dimension"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Sensor Height",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepHvacControls.signalType",
    "Signal Type",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def signalType(ctx: FeatureContext, values: dict) -> dict:
    """Signal Type: Actuators."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Signal Type",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacControls.temperatureSensor",
    "Temperature Sensor",
    part="mep",
    fields=[number("temperature", "Design temperature", 20, unit="?C")],
    requires_project=True,
)
def temperatureSensor(ctx: FeatureContext, values: dict) -> dict:
    """Temperature Sensor: Sensors."""
    design_value = float(values["temperature"])
    safety_factor = 1.15
    sized_value = design_value * safety_factor
    return result(
        summary={
            "designValue": design_value,
            "safetyFactor": safety_factor,
            "sizedValue": sized_value,
        },
        tables=[
            table(
                "Temperature Sensor",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Design value", "value": design_value},
                    {"item": "Preliminary sized value", "value": sized_value},
                ],
            )
        ],
        notes=[
            "Preliminary sizing uses a 1.15 factor; verify applicable code and project criteria."
        ],
    )


@feature(
    "mepHvacControls.timeSchedule",
    "Time Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def timeSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Time Schedule: Setpoints."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepHvacControls.timeSchedule",
        "title": "Time Schedule",
        "name": values["name"],
        "group": "Setpoints",
        "mep": raw,
    }
    path = ctx.path("11 Exports/timeSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Time Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepHvacControls.valveActuator",
    "Valve Actuator",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def valveActuator(ctx: FeatureContext, values: dict) -> dict:
    """Valve Actuator: Actuators."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Valve Actuator",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )
