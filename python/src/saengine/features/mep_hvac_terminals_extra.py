"""Dedicated mepHvacTerminals MEP feature registrations."""

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
    "mepHvacTerminals.adpiCalculation",
    "ADPI Calculation",
    part="mep",
    fields=[
        number("throwT50M", "Catalog diffuser isothermal throw T50", 3.6, unit="m", min=0.2),
        number("characteristicLengthM", "Room characteristic length L", 4.0, unit="m", min=0.5),
        number("coolingLoadWPerM2", "Zone cooling load density", 75.0, unit="W/m²", min=5.0),
    ],
    requires_project=False,
)
def adpiCalculation(ctx: FeatureContext, values: dict) -> dict:
    """Estimate Air Diffusion Performance Index (ADPI) from throw-to-length ratio T50/L."""
    ratio = float(values["throwT50M"]) / float(values["characteristicLengthM"])
    # Optimal ceiling diffuser T50/L band is ~0.8 to 1.2 for >=80% ADPI at <=80 W/m2
    load_pen = max(0.0, (float(values["coolingLoadWPerM2"]) - 65.0) * 0.12)
    off_center = abs(ratio - 1.0)
    est_adpi = max(45.0, min(96.0, 93.0 - 28.0 * (off_center**1.5) - load_pen))
    ok = est_adpi >= 80.0
    return result(
        summary={
            "throwRatioT50OverL": round(ratio, 2),
            "estimatedAdpiPct": round(est_adpi, 1),
            "compliantGe80Pct": ok,
        },
        tables=[
            table(
                "Room air diffusion comfort (ADPI)",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Throw ratio T50 / L", "value": round(ratio, 2), "unit": "-"},
                    {"item": "Optimal range (overhead jet)", "value": "0.8 - 1.2", "unit": "-"},
                    {"item": "Estimated ADPI", "value": round(est_adpi, 1), "unit": "%"},
                    {
                        "item": "Target >= 80%",
                        "value": "PASS" if ok else "ADJUST DIFFUSER SPACING",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Maintain throw-to-length T50/L near 1.0 so Coanda ceiling jet mixes before entering occupied zone."
        ],
    )


@feature(
    "mepHvacTerminals.airflowTest",
    "Airflow Test",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def airflowTest(ctx: FeatureContext, values: dict) -> dict:
    """Airflow Test: Airflow."""
    design_value = float(values["flow"])
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
                "Airflow Test",
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
    "mepHvacTerminals.balancingDamper",
    "Balancing Damper",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def balancingDamper(ctx: FeatureContext, values: dict) -> dict:
    """Balancing Damper: Airflow."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Balancing Damper",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacTerminals.diffuserType",
    "Diffuser Type",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def diffuserType(ctx: FeatureContext, values: dict) -> dict:
    """Diffuser Type: Diffusers."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Diffuser Type",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacTerminals.draftRatingMap",
    "Draft Rating Map",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def draftRatingMap(ctx: FeatureContext, values: dict) -> dict:
    """Draft Rating Map: Comfort Analysis."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Draft Rating Map",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacTerminals.externalLouvre",
    "External Louvre",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def externalLouvre(ctx: FeatureContext, values: dict) -> dict:
    """External Louvre: Grilles."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "External Louvre",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacTerminals.minimumAirflowSet",
    "Minimum Airflow Set",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def minimumAirflowSet(ctx: FeatureContext, values: dict) -> dict:
    """Minimum Airflow Set: VAV Units."""
    design_value = float(values["flow"])
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
                "Minimum Airflow Set",
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
    "mepHvacTerminals.noiseLevel",
    "Noise Level",
    part="mep",
    fields=[
        number(
            "catalogNcPerUnit",
            "Single diffuser catalog rating at flow",
            28.0,
            unit="NC",
            min=10.0,
            max=65.0,
        ),
        number("diffuserCount", "Active diffusers contributing in room", 4, min=1, max=40),
        number("distanceM", "Distance from nearest diffuser to listener", 2.5, unit="m", min=0.5),
        number("roomLimitNc", "Target room background limit", 35.0, unit="NC", min=20.0, max=55.0),
    ],
    requires_project=False,
)
def noiseLevel(ctx: FeatureContext, values: dict) -> dict:
    """Predict combined diffuser room sound level with distance and multi-source addition."""
    import math

    n = int(values["diffuserCount"])
    base_nc = float(values["catalogNcPerUnit"])
    # Standard catalog NC assumes ~10 dB room absorption; multi-unit close addition + distance adjustment
    multi_add = 10.0 * math.log10(max(1.0, 1.0 + 0.5 * (n - 1)))
    dist_adj = -5.0 * math.log10(float(values["distanceM"]) / 1.5)
    pred_nc = base_nc + multi_add + dist_adj
    ok = pred_nc <= float(values["roomLimitNc"])
    return result(
        summary={
            "predictedRoomNc": round(pred_nc, 1),
            "limitNc": float(values["roomLimitNc"]),
            "compliant": ok,
        },
        tables=[
            table(
                "Diffuser acoustic check",
                [("item", "Term"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Single terminal catalog NC", "value": base_nc, "unit": "NC"},
                    {"item": "Multi-diffuser addition", "value": round(multi_add, 1), "unit": "dB"},
                    {"item": "Distance correction", "value": round(dist_adj, 1), "unit": "dB"},
                    {"item": "Predicted occupied NC", "value": round(pred_nc, 1), "unit": "NC"},
                    {
                        "item": "Status",
                        "value": "PASS" if ok else "ATTENUATE / LOWER NECK VELOCITY",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Multi-terminal logarithmic addition with standard semi-reverberant room distance rolloff."
        ],
    )


@feature(
    "mepHvacTerminals.placeDiffuser",
    "Place Diffuser",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def placeDiffuser(ctx: FeatureContext, values: dict) -> dict:
    """Place Diffuser: Diffusers."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Place Diffuser",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacTerminals.pressureDependentMode",
    "Pressure Dependent Mode",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def pressureDependentMode(ctx: FeatureContext, values: dict) -> dict:
    """Pressure Dependent Mode: VAV Units."""
    design_value = float(values["pressure"])
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
                "Pressure Dependent Mode",
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
    "mepHvacTerminals.regeneratedNoise",
    "Regenerated Noise",
    part="mep",
    fields=[
        number("faceAreaM2", "Damper / terminal cross-section area", 0.08, unit="m²", min=0.005),
        number("staticDropPa", "Throttled static pressure drop ΔP", 120.0, unit="Pa", min=5.0),
        number(
            "downstreamAttenDb", "Lined plenum + branch insertion loss", 14.0, unit="dB", min=0.0
        ),
    ],
    requires_project=False,
)
def regeneratedNoise(ctx: FeatureContext, values: dict) -> dict:
    """Estimate damper/fitting regenerated sound power Lw and attenuated room contribution."""
    import math

    area = float(values["faceAreaM2"])
    dp = float(values["staticDropPa"])
    # ASHRAE simplified regenerated Lw ~= -4 + 10*log10(A) + 25*log10(dp)
    lw_db = -4.0 + 10.0 * math.log10(area) + 25.0 * math.log10(dp)
    lp_room = lw_db - float(values["downstreamAttenDb"]) - 8.0
    return result(
        summary={
            "soundPowerLwDb": round(lw_db, 1),
            "estimatedRoomLpDb": round(lp_room, 1),
        },
        tables=[
            table(
                "Damper regenerated noise estimate",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Static pressure drop", "value": dp, "unit": "Pa"},
                    {"item": "Regenerated sound power Lw", "value": round(lw_db, 1), "unit": "dB"},
                    {
                        "item": "Room SPL after duct & room loss",
                        "value": round(lp_room, 1),
                        "unit": "dB",
                    },
                ],
            )
        ],
        notes=[
            "Scale follows Lw ~ 25*log10(dP); keep balancing damper dP <= 125 Pa near occupied rooms."
        ],
    )


@feature(
    "mepHvacTerminals.reheatCoilCalculation",
    "Reheat Coil Calculation",
    part="mep",
    fields=[
        number("minAirflowLps", "VAV minimum heating airflow", 140.0, unit="L/s", min=10.0),
        number("enteringAirC", "Primary supply air temperature", 13.0, unit="°C"),
        number(
            "leavingAirC",
            "Target discharge heating temperature",
            32.0,
            unit="°C",
            min=20.0,
            max=42.0,
        ),
        number("waterDeltaTK", "Hot water coil ΔT", 11.0, unit="K", min=3.0),
    ],
    requires_project=False,
)
def reheatCoilCalculation(ctx: FeatureContext, values: dict) -> dict:
    """Size VAV hydronic/electric reheat coil thermal duty and hot water mass flow."""
    dt_air = float(values["leavingAirC"]) - float(values["enteringAirC"])
    if dt_air <= 0:
        raise FeatureInputError("Leaving air temperature must exceed entering air temperature.")
    q_m3s = float(values["minAirflowLps"]) / 1000.0
    heat_kw = 1.2 * 1.005 * q_m3s * dt_air
    hw_lps = heat_kw / (4.186 * float(values["waterDeltaTK"]))
    return result(
        summary={
            "reheatDutyKw": round(heat_kw, 2),
            "hotWaterFlowLps": round(hw_lps, 3),
            "airDeltaTK": round(dt_air, 1),
        },
        tables=[
            table(
                "VAV terminal reheat coil sizing",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Minimum primary airflow",
                        "value": values["minAirflowLps"],
                        "unit": "L/s",
                    },
                    {"item": "Air temperature rise ΔT", "value": round(dt_air, 1), "unit": "K"},
                    {"item": "Coil heating capacity", "value": round(heat_kw, 2), "unit": "kW"},
                    {"item": "Required LTHW flow", "value": round(hw_lps, 3), "unit": "L/s"},
                ],
            )
        ],
        notes=[
            "Standard air density 1.2 kg/m3, cp = 1.005 kJ/(kg·K); keep discharge <= 35 C to avoid stratification."
        ],
    )


@feature(
    "mepHvacTerminals.returnGrille",
    "Return Grille",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def returnGrille(ctx: FeatureContext, values: dict) -> dict:
    """Return Grille: Grilles."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Return Grille",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacTerminals.setFlowRate",
    "Set Flow Rate",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def setFlowRate(ctx: FeatureContext, values: dict) -> dict:
    """Set Flow Rate: Airflow."""
    design_value = float(values["flow"])
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
                "Set Flow Rate",
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
    "mepHvacTerminals.soundAttenuator",
    "Sound Attenuator",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def soundAttenuator(ctx: FeatureContext, values: dict) -> dict:
    """Sound Attenuator: Acoustics."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Sound Attenuator",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacTerminals.supplyGrille",
    "Supply Grille",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def supplyGrille(ctx: FeatureContext, values: dict) -> dict:
    """Supply Grille: Grilles."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Supply Grille",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacTerminals.temperatureStratification",
    "Temperature Stratification",
    part="mep",
    fields=[number("temperature", "Design temperature", 20, unit="?C")],
    requires_project=True,
)
def temperatureStratification(ctx: FeatureContext, values: dict) -> dict:
    """Temperature Stratification: Comfort Analysis."""
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
                "Temperature Stratification",
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
    "mepHvacTerminals.terminalNcRating",
    "Terminal NC Rating",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def terminalNcRating(ctx: FeatureContext, values: dict) -> dict:
    """Terminal NC Rating: Acoustics."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Terminal NC Rating",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacTerminals.terminalSchedule",
    "Terminal Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def terminalSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Terminal Schedule: Airflow."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepHvacTerminals.terminalSchedule",
        "title": "Terminal Schedule",
        "name": values["name"],
        "group": "Airflow",
        "mep": raw,
    }
    path = ctx.path("11 Exports/terminalSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Terminal Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepHvacTerminals.throwDistance",
    "Throw Distance",
    part="mep",
    fields=[number("dimension", "Dimension", 1000, unit="mm", min=1)],
    requires_project=True,
)
def throwDistance(ctx: FeatureContext, values: dict) -> dict:
    """Throw Distance: Diffusers."""
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
                "Throw Distance",
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
    "mepHvacTerminals.transferGrille",
    "Transfer Grille",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def transferGrille(ctx: FeatureContext, values: dict) -> dict:
    """Transfer Grille: Grilles."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Transfer Grille",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepHvacTerminals.vavBoxSizing",
    "VAV Box Sizing",
    part="mep",
    fields=[
        number("peakAirflowLps", "Zone peak cooling airflow", 420.0, unit="L/s", min=20.0),
        number("minFlowRatio", "Minimum ventilation turndown ratio", 0.30, min=0.1, max=0.8),
        number(
            "maxInletVelMs", "Maximum collar velocity limit", 10.0, unit="m/s", min=4.0, max=15.0
        ),
    ],
    requires_project=False,
)
def vavBoxSizing(ctx: FeatureContext, values: dict) -> dict:
    """Select circular VAV inlet collar diameter meeting peak velocity and turndown bounds."""
    import math

    q_m3s = float(values["peakAirflowLps"]) / 1000.0
    v_lim = float(values["maxInletVelMs"])
    d_min_mm = math.sqrt(4.0 * q_m3s / (math.pi * v_lim)) * 1000.0
    std_collars = [100, 125, 150, 200, 250, 300, 355, 400, 450, 500]
    collar_mm = next((d for d in std_collars if d >= d_min_mm), std_collars[-1])
    area = math.pi * ((collar_mm / 1000.0) / 2.0) ** 2
    v_peak = q_m3s / area
    q_min_lps = float(values["peakAirflowLps"]) * float(values["minFlowRatio"])
    v_min = (q_min_lps / 1000.0) / area
    sensor_ok = v_min >= 1.5  # Typical differential-pressure flow sensor lower limit ~1.5 m/s
    return result(
        summary={
            "selectedCollarMm": collar_mm,
            "peakVelocityMs": round(v_peak, 2),
            "minVelocityMs": round(v_min, 2),
            "turndownSensorOk": sensor_ok,
        },
        tables=[
            table(
                "VAV terminal unit sizing",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Selected inlet collar", "value": collar_mm, "unit": "mm"},
                    {"item": "Peak collar velocity", "value": round(v_peak, 2), "unit": "m/s"},
                    {"item": "Min turndown airflow", "value": round(q_min_lps, 1), "unit": "L/s"},
                    {"item": "Min velocity (>= 1.5 m/s)", "value": round(v_min, 2), "unit": "m/s"},
                    {
                        "item": "Sensor controllability",
                        "value": "OK" if sensor_ok else "OVERSIZED FOR LOW FLOW",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Selects smallest standard circular collar with V_peak <= limit while keeping V_min >= 1.5 m/s."
        ],
    )
