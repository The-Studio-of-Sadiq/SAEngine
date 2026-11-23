"""Electrical panel, cable sizing, earthing and low-voltage MEP features."""

from __future__ import annotations

from saengine.features import (
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
)


@feature(
    "mepElectricalCableSizing.cableType",
    "Cable Type",
    part="mep",
    fields=[
        select("conductor", "Conductor", [("Cu", "Copper"), ("Al", "Aluminium")], "Cu"),
        select("insulation", "Insulation", [("PVC", "PVC"), ("XLPE", "XLPE")], "XLPE"),
    ],
    requires_project=False,
)
def cable_type(ctx, v):
    return result(
        summary={"conductor": v["conductor"], "insulation": v["insulation"]},
        tables=[
            table(
                "Cable type",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Conductor", "value": v["conductor"]},
                    {"property": "Insulation", "value": v["insulation"]},
                ],
            )
        ],
        notes=["Cable family for ampacity and voltage-drop pack lookups."],
    )


@feature(
    "mepElectricalCableSizing.ampacity",
    "Ampacity",
    part="mep",
    fields=[
        number("size", "Cable size", 25, unit="mm²", min=1),
        number("factor", "Derating factor", 0.8, min=0.1, max=1),
        number("base", "Base ampacity", 119, unit="A", min=0),
    ],
    requires_project=False,
)
def ampacity(ctx, v):
    iz = v["base"] * v["factor"]
    return result(
        summary={
            "baseAmpacityA": v["base"],
            "deratingFactor": v["factor"],
            "effectiveAmpacityA": iz,
        },
        tables=[
            table(
                "Ampacity",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Effective ampacity", "value": iz}],
            )
        ],
        notes=["Effective ampacity = base ampacity × combined derating factor."],
    )


@feature(
    "mepElectricalCableSizing.correctionFactor",
    "Correction Factor",
    part="mep",
    fields=[
        number("ambient", "Ambient factor", 1, min=0.1),
        number("grouping", "Grouping factor", 0.8, min=0.1),
        number("thermal", "Thermal insulation factor", 1, min=0.1),
    ],
    requires_project=False,
)
def correction_factor(ctx, v):
    factor = v["ambient"] * v["grouping"] * v["thermal"]
    return result(
        summary={"factor": factor},
        tables=[
            table(
                "Correction factors",
                [("factor", "Factor"), ("value", "Value")],
                [
                    {"factor": "Ambient", "value": v["ambient"]},
                    {"factor": "Grouping", "value": v["grouping"]},
                    {"factor": "Thermal insulation", "value": v["thermal"]},
                    {"factor": "Combined", "value": factor},
                ],
            )
        ],
        notes=["Combined factor = ambient × grouping × thermal insulation."],
    )


@feature(
    "mepElectricalCableSizing.autoSize",
    "Auto Size",
    part="mep",
    fields=[
        number("load", "Load current", 32, unit="A", min=0),
        number("length", "Route length", 30, unit="m", min=0),
        number("factor", "Derating factor", 0.8, min=0.1, max=1),
        number("voltage", "Supply voltage", 400, unit="V", min=1),
    ],
    requires_project=False,
)
def auto_size(ctx, v):
    from saengine.electrical.cables import size_cable

    try:
        out = size_cable(v["load"] / v["factor"], v["length"], phases=3, voltage=v["voltage"])
    except (ValueError, KeyError) as e:
        raise FeatureInputError(str(e))
    return result(
        summary={
            "recommendedSizeMm2": out["recommendedSize"],
            "selectedSizeMm2": out["size"],
            "voltageDropPct": out["cumVdPct"],
            "ok": out["ok"],
        },
        tables=[
            table(
                "Cable selection",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Recommended size", "value": out["recommendedSize"]},
                    {"item": "Voltage drop", "value": out["cumVdPct"]},
                ],
            )
        ],
        notes=["Uses the active code pack through saengine.electrical.cables.size_cable."],
    )


@feature(
    "mepElectricalCableSizing.calculateDrop",
    "Calculate Drop",
    part="mep",
    fields=[
        number("size", "Cable size", 25, unit="mm²", min=1),
        number("current", "Current", 32, unit="A", min=0),
        number("length", "Length", 30, unit="m", min=0),
        number("voltage", "Voltage", 400, unit="V", min=1),
        number("pf", "Power factor", 0.85, min=0.1, max=1),
        select("phases", "Phases", [("1", "Single"), ("3", "Three")], "3"),
    ],
    requires_project=False,
)
def calculate_drop(ctx, v):
    from saengine.electrical.cables import voltage_drop

    phases = int(v["phases"])
    try:
        out = voltage_drop(
            v["size"], v["current"], v["length"], phases=phases, pf=v["pf"], voltage=v["voltage"]
        )
    except (ValueError, KeyError) as e:
        raise FeatureInputError(str(e))
    return result(
        summary={"dropV": out["vdV"], "dropPct": out["vdPct"], "phases": phases},
        tables=[
            table(
                "Voltage drop",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Drop", "value": out["vdV"]},
                    {"item": "Percentage", "value": out["vdPct"]},
                ],
            )
        ],
        notes=["Uses saengine.electrical.cables voltage-drop data and R/X or mV/A/m mode."],
    )


@feature(
    "mepElectricalCableSizing.dropLimit",
    "Drop Limit",
    part="mep",
    fields=[
        select("kind", "Circuit kind", [("power", "Power"), ("lighting", "Lighting")], "power")
    ],
    requires_project=False,
)
def drop_limit(ctx, v):
    from saengine.electrical.cables import voltage_drop_limit

    limit = voltage_drop_limit(v["kind"])
    return result(
        summary={"dropLimitPct": limit, "kind": v["kind"]},
        tables=[
            table(
                "Voltage-drop limit",
                [("kind", "Kind"), ("limit", "Limit", "%")],
                [{"kind": v["kind"], "limit": limit}],
            )
        ],
        notes=["The limit is read from the active electrical code pack."],
    )


@feature(
    "mepElectricalCableSizing.longestRun",
    "Longest Run",
    part="mep",
    fields=[
        number("length", "Measured route", 30, unit="m", min=0),
        number("allowance", "Routing allowance", 10, unit="%", min=0, max=100),
    ],
    requires_project=False,
)
def longest_run(ctx, v):
    length = v["length"] * (1 + v["allowance"] / 100)
    return result(
        summary={"nominalLengthM": v["length"], "designLengthM": length},
        tables=[
            table(
                "Longest run",
                [("item", "Length", "m")],
                [{"item": "Design length", "Length": length}],
            )
        ],
        notes=["Design length adds the entered routing allowance."],
    )


@feature(
    "mepElectricalCableSizing.dropReport",
    "Drop Report",
    part="mep",
    fields=[
        number("drop", "Calculated drop", 2.5, unit="%", min=0),
        number("limit", "Drop limit", 5, unit="%", min=0),
    ],
    requires_project=False,
)
def drop_report(ctx, v):
    return result(
        summary={"dropPct": v["drop"], "limitPct": v["limit"], "ok": v["drop"] <= v["limit"]},
        tables=[
            table(
                "Drop report",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Drop", "value": v["drop"]},
                    {"item": "Limit", "value": v["limit"]},
                    {"item": "Pass", "value": v["drop"] <= v["limit"]},
                ],
            )
        ],
        notes=["Compares cumulative voltage drop with the selected limit."],
    )


@feature(
    "mepElectricalCableSizing.faultCapacityCheck",
    "Fault Capacity Check",
    part="mep",
    fields=[
        number("fault", "Prospective fault current", 10, unit="kA", min=0),
        number("rating", "Device breaking capacity", 10, unit="kA", min=0),
    ],
    requires_project=False,
)
def fault_capacity_check(ctx, v):
    return result(
        summary={
            "ok": v["rating"] >= v["fault"],
            "faultKa": v["fault"],
            "breakingCapacityKa": v["rating"],
        },
        tables=[
            table(
                "Fault capacity",
                [("item", "Item", "kA")],
                [
                    {"item": "Prospective fault", "kA": v["fault"]},
                    {"item": "Device rating", "kA": v["rating"]},
                ],
            )
        ],
        notes=["The device breaking capacity must meet the prospective fault current."],
    )


@feature(
    "mepElectricalCableSizing.thermalWithstand",
    "Thermal Withstand",
    part="mep",
    fields=[
        number("size", "Cable size", 25, unit="mm²", min=1),
        number("fault", "Fault current", 10, unit="kA", min=0),
        number("time", "Clearing time", 1, unit="s", min=0.01),
        select("conductor", "Conductor", [("Cu", "Copper"), ("Al", "Aluminium")], "Cu"),
        select("insulation", "Insulation", [("PVC", "PVC"), ("XLPE", "XLPE")], "PVC"),
    ],
    requires_project=False,
)
def thermal_withstand(ctx, v):
    from saengine.electrical.cables import adiabatic_min_size

    try:
        minimum = adiabatic_min_size(v["fault"], v["time"], v["conductor"], v["insulation"])
    except (ValueError, KeyError) as e:
        raise FeatureInputError(str(e))
    return result(
        summary={
            "minimumAdiabaticMm2": minimum,
            "selectedMm2": v["size"],
            "ok": v["size"] >= minimum,
        },
        tables=[
            table(
                "Thermal withstand",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Minimum area", "value": minimum},
                    {"item": "Pass", "value": v["size"] >= minimum},
                ],
            )
        ],
        notes=["Uses k-factor adiabatic size S=sqrt(I²t)/k from the active pack."],
    )


@feature(
    "mepElectricalCableSizing.i2tProtectionIntegration",
    "I2t Protection Integration",
    part="mep",
    fields=[
        number("i", "Fault current", 10, unit="kA", min=0),
        number("t", "Operating time", 1, unit="s", min=0.01),
        number("i2t", "Entered I²t", 0, unit="kA²s", min=0),
    ],
    requires_project=False,
)
def i2t_protection_integration(ctx, v):
    i2t = v["i"] ** 2 * v["t"] if v["i2t"] == 0 else v["i2t"]
    return result(
        summary={"i2tKa2s": i2t},
        tables=[
            table(
                "I²t protection",
                [("item", "Item"), ("value", "Value")],
                [{"item": "I²t", "value": i2t}],
            )
        ],
        notes=["I²t = I² × t, or uses an entered protection-device I²t."],
    )
