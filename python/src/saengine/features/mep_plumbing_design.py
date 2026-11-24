"""Plumbing sizing and design features for MEP projects."""

from __future__ import annotations

import json
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
    "mepPlumbingDesign.hotWaterReturn",
    "Hot Water Return",
    part="mep",
    fields=[
        number("lengthM", "Loop length", 30.0, unit="m", min=0.1),
        number("heatLossWPerM", "Linear heat loss", 12.0, unit="W/m", min=0),
        number("returnDropC", "Return temperature drop", 5.0, unit="°C", min=0.1),
    ],
    requires_project=False,
)
def hot_water_return(ctx: FeatureContext, values: dict) -> dict:
    """Estimate recirculation flow from distributed heat loss."""
    from saengine.plumbing.hot_water import recirculation_loop

    sizing = recirculation_loop(
        values["lengthM"],
        heat_loss_w_per_m=values["heatLossWPerM"],
        return_drop_c=values["returnDropC"],
    )
    return result(
        summary={"circulationFlowLpm": sizing.get("flowLpm"), "loopLengthM": values["lengthM"]},
        tables=[
            table(
                "Return loop sizing",
                [("item", "Item"), ("value", "Value")],
                [{"item": key, "value": value} for key, value in sizing.items()],
            )
        ],
        notes=[
            "Steady heat-loss balance; water heat capacity and density follow the plumbing calculation library."
        ],
    )


@feature(
    "mepPlumbingDesign.gasLoadCalc",
    "Gas Load Calc",
    part="mep",
    fields=[
        number("connectedLoadKw", "Connected appliance load", 40.0, unit="kW", min=0.1),
        number("diversity", "Coincident demand fraction", 0.75, min=0.01, max=1),
        number("runLengthM", "Longest run", 25.0, unit="m", min=0.1),
        number("calorificValueKwhM3", "Gas calorific value", 10.5, unit="kWh/m³", min=0.1),
    ],
    requires_project=False,
)
def gas_load_calc(ctx: FeatureContext, values: dict) -> dict:
    """Convert coincident appliance load to gas volume flow and size the run."""
    from saengine.plumbing.gas import size_gas_pipe

    flow = values["connectedLoadKw"] * values["diversity"] / values["calorificValueKwhM3"]
    sizing = size_gas_pipe(flow, values["runLengthM"])
    return result(
        summary={
            "coincidentLoadKw": values["connectedLoadKw"] * values["diversity"],
            "flowM3h": flow,
        },
        tables=[
            table(
                "Gas main",
                [("parameter", "Parameter"), ("value", "Value")],
                [{"parameter": k, "value": v} for k, v in sizing.items()],
            )
        ],
        notes=[
            "Appliance input is converted using the entered gross calorific value; pipe selection uses the engine's pressure-drop method."
        ],
    )


@feature(
    "mepPlumbingDesign.medicalGasOutlets",
    "Medical Gas Outlets",
    part="mep",
    fields=[
        select(
            "gas",
            "Medical gas",
            [
                ("O2", "Oxygen"),
                ("MA4", "Medical air 4 bar"),
                ("VAC", "Vacuum"),
                ("N2O", "Nitrous oxide"),
            ],
        ),
        number("outletCount", "Outlet count", 8, min=1),
    ],
    requires_project=False,
)
def medical_gas_outlets(ctx: FeatureContext, values: dict) -> dict:
    """Estimate diversified medical-gas terminal demand."""
    from saengine.plumbing.gas import medical_gas_flow

    design = medical_gas_flow(values["gas"], int(values["outletCount"]))
    return result(
        summary={"outletCount": int(values["outletCount"]), "designFlowLpm": design.get("flowLpm")},
        tables=[
            table(
                "Outlet demand",
                [("gas", "Gas"), ("outlets", "Outlets"), ("flowLpm", "Flow", "L/min")],
                [
                    {
                        "gas": values["gas"],
                        "outlets": int(values["outletCount"]),
                        "flowLpm": design.get("flowLpm"),
                    }
                ],
            )
        ],
        notes=["Diversified outlet flow is taken from the installed medical-gas demand table."],
    )


@feature(
    "mepPlumbingDesign.ventStackSizing",
    "Vent Stack Sizing",
    part="mep",
    fields=[
        number("soilStackMm", "Connected soil stack diameter", 100, unit="mm", min=40),
        number("fixtureUnits", "Connected drainage fixture units", 30, min=1),
        number("stackHeightStories", "Storeys served", 4, min=1),
        number("ventLengthM", "Vent run length", 12, unit="m", min=0.1),
    ],
    requires_project=False,
)
def vent_stack_sizing(ctx: FeatureContext, values: dict) -> dict:
    """Select a vent diameter for the connected stack load and length."""
    from saengine.plumbing.drainage import vent_size

    selected = vent_size(values["soilStackMm"], values["fixtureUnits"], values["ventLengthM"])
    capacity, per_story = (None, None)
    if selected:
        from saengine.plumbing.drainage import stack_capacity

        capacity, per_story = stack_capacity(int(selected), int(values["stackHeightStories"]))
    if selected is None:
        raise FeatureInputError(
            "The entered stack load and vent length exceed the available sizing table."
        )
    return result(
        summary={
            "ventDiameterMm": selected,
            "stackCapacityUnits": capacity,
            "perStoreyCapacityUnits": per_story,
        },
        notes=[
            "Vent diameter and capacity are selected from the engine drainage tables for the stated height and fixture load."
        ],
    )


@feature(
    "mepPlumbingDesign.trapArmCheck",
    "Trap Arm Check",
    part="mep",
    fields=[
        number("armLengthM", "Trap arm length", 1.5, unit="m", min=0),
        number("armDiameterMm", "Trap arm diameter", 50, unit="mm", min=32),
        number("slopePercent", "Pipe fall", 2.0, unit="%", min=0),
        number("maximumLengthM", "Maximum permitted developed length", 3.0, unit="m", min=0.1),
        number("minimumFallMm", "Minimum fall", 10.0, unit="mm", min=0),
    ],
    requires_project=False,
)
def trap_arm_check(ctx: FeatureContext, values: dict) -> dict:
    """Check trap-arm developed length and gravity fall."""
    fall = values["armLengthM"] * values["slopePercent"] * 10
    pass_length = values["armLengthM"] <= values["maximumLengthM"]
    pass_fall = fall >= values["minimumFallMm"]
    return result(
        summary={
            "developedLengthM": values["armLengthM"],
            "fallMm": fall,
            "passes": pass_length and pass_fall,
        },
        tables=[
            table(
                "Trap arm checks",
                [
                    ("check", "Check"),
                    ("provided", "Provided"),
                    ("limit", "Limit"),
                    ("passes", "Pass"),
                ],
                [
                    {
                        "check": "Developed length",
                        "provided": values["armLengthM"],
                        "limit": values["maximumLengthM"],
                        "passes": pass_length,
                    },
                    {
                        "check": "Gravity fall",
                        "provided": fall,
                        "limit": values["minimumFallMm"],
                        "passes": pass_fall,
                    },
                ],
            )
        ],
        notes=[
            "Fall is calculated from length × slope; the user-entered maximum length and minimum fall are project criteria, not code defaults."
        ],
    )


@feature(
    "mepPlumbingDesign.gullySizing",
    "Gully Sizing",
    part="mep",
    fields=[
        number("fixtureUnits", "Connected drainage fixture units", 12, min=1),
        number("slopePercent", "Outlet slope", 2, unit="%", min=0.1),
        number("minimumOutletMm", "Minimum outlet diameter", 50, unit="mm", min=32),
    ],
    requires_project=False,
)
def gully_sizing(ctx: FeatureContext, values: dict) -> dict:
    """Size a gully outlet from drainage units and pipe slope."""
    from saengine.plumbing.drainage import drain_size

    diameter, selected_slope = drain_size(values["fixtureUnits"], values["slopePercent"] / 100)
    if diameter is None or selected_slope is None:
        raise FeatureInputError("No drainage outlet size is available for this load and slope.")
    diameter = max(int(diameter), int(values["minimumOutletMm"]))
    return result(
        summary={
            "outletDiameterMm": diameter,
            "designSlopePercent": selected_slope * 100,
            "passes": True,
        },
        notes=[
            "Outlet sizing uses the drainage-unit and slope-capacity table; the entered minimum diameter is enforced."
        ],
    )


@feature(
    "mepPlumbingDesign.pumpCurves",
    "Pump Curves",
    part="mep",
    fields=[
        number("flowLps", "Duty flow", 2.0, unit="L/s", min=0.01),
        number("headM", "Duty head", 25, unit="m", min=0.1),
        number("efficiency", "Pump efficiency", 0.68, min=0.05, max=1),
        number("candidateFlowLps", "Candidate pump flow", 2.2, unit="L/s", min=0.01),
        number("candidateHeadM", "Candidate pump head", 28, unit="m", min=0.1),
    ],
    requires_project=False,
)
def pump_curves(ctx: FeatureContext, values: dict) -> dict:
    """Compare a candidate operating point with the required duty point."""
    required_kw = 9.80665 * values["flowLps"] * values["headM"] / (1000 * values["efficiency"])
    candidate_kw = (
        9.80665
        * values["candidateFlowLps"]
        * values["candidateHeadM"]
        / (1000 * values["efficiency"])
    )
    flow_ratio = values["candidateFlowLps"] / values["flowLps"]
    head_ratio = values["candidateHeadM"] / values["headM"]
    return result(
        summary={
            "requiredInputKw": required_kw,
            "candidateInputKw": candidate_kw,
            "dutyCovered": flow_ratio >= 1 and head_ratio >= 1,
        },
        tables=[
            table(
                "Pump operating points",
                [
                    ("point", "Point"),
                    ("flowLps", "Flow", "L/s"),
                    ("headM", "Head", "m"),
                    ("inputKw", "Input power", "kW"),
                ],
                [
                    {
                        "point": "Required",
                        "flowLps": values["flowLps"],
                        "headM": values["headM"],
                        "inputKw": required_kw,
                    },
                    {
                        "point": "Candidate",
                        "flowLps": values["candidateFlowLps"],
                        "headM": values["candidateHeadM"],
                        "inputKw": candidate_kw,
                    },
                ],
            )
        ],
        notes=[
            "Input power is hydraulic power divided by the entered efficiency; a real manufacturer curve is needed for final selection."
        ],
    )


@feature(
    "mepPlumbingDesign.boosterSet",
    "Booster Set",
    part="mep",
    fields=[
        number("peakFlowLps", "Peak demand", 3.0, unit="L/s", min=0.01),
        number("requiredHeadM", "Required head", 35, unit="m", min=0.1),
        number("pumpCount", "Duty pumps", 2, min=1),
        number("motorEfficiency", "Motor efficiency", 0.9, min=0.1, max=1),
    ],
    requires_project=False,
)
def booster_set(ctx: FeatureContext, values: dict) -> dict:
    """Calculate per-pump flow and motor input for a parallel booster set."""
    from saengine.plumbing.hydraulics import motor_rating

    count = int(values["pumpCount"])
    flow_each = values["peakFlowLps"] / count
    hydraulic_kw = flow_each * values["requiredHeadM"] * 9.80665 / 1000
    motor_kw = motor_rating(hydraulic_kw) / values["motorEfficiency"]
    return result(
        summary={"pumpCount": count, "flowPerPumpLps": flow_each, "motorInputKwEach": motor_kw},
        tables=[
            table(
                "Booster duty",
                [
                    ("pump", "Pump"),
                    ("flowLps", "Flow", "L/s"),
                    ("headM", "Head", "m"),
                    ("inputKw", "Input", "kW"),
                ],
                [
                    {
                        "pump": i + 1,
                        "flowLps": flow_each,
                        "headM": values["requiredHeadM"],
                        "inputKw": motor_kw,
                    }
                    for i in range(count)
                ],
            )
        ],
        notes=[
            "Flow is divided equally between the entered duty pumps; the hydraulic motor estimate is adjusted by the entered motor efficiency."
        ],
    )


@feature(
    "mepPlumbingDesign.tankSizing",
    "Tank Sizing",
    part="mep",
    fields=[
        number("dailyDemandL", "Daily demand", 12000, unit="L/day", min=1),
        number("autonomyDays", "Storage autonomy", 1, unit="day", min=0.1),
        number("usableFraction", "Usable volume fraction", 0.85, min=0.1, max=1),
        number("refillHours", "Available refill period", 6, unit="h", min=0.1),
    ],
    requires_project=False,
)
def tank_sizing(ctx: FeatureContext, values: dict) -> dict:
    """Estimate usable storage volume and refill flow for the entered demand."""
    volume = values["dailyDemandL"] * values["autonomyDays"] / values["usableFraction"]
    refill_ls = volume / (values["refillHours"] * 3600)
    return result(
        summary={"grossVolumeL": volume, "refillFlowLps": refill_ls},
        tables=[
            table(
                "Storage basis",
                [("quantity", "Quantity"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"quantity": "Daily demand", "value": values["dailyDemandL"], "unit": "L/day"},
                    {"quantity": "Autonomy", "value": values["autonomyDays"], "unit": "day"},
                    {"quantity": "Gross storage", "value": volume, "unit": "L"},
                    {"quantity": "Refill rate", "value": refill_ls, "unit": "L/s"},
                ],
            )
        ],
        notes=[
            "Gross storage equals demand × autonomy divided by usable fraction; refill flow assumes uniform filling during the stated period."
        ],
    )


@feature(
    "mepPlumbingDesign.waterSoftener",
    "Water Softener",
    part="mep",
    fields=[
        number("flowM3h", "Design flow", 1.2, unit="m³/h", min=0.01),
        number("hardnessMgL", "Feed hardness as CaCO₃", 250, unit="mg/L", min=0),
        number("targetHardnessMgL", "Target hardness as CaCO₃", 50, unit="mg/L", min=0),
        number("regenerationIntervalDays", "Regeneration interval", 1, unit="day", min=0.1),
        number("resinCapacityEqL", "Working resin capacity", 1.2, unit="eq/L", min=0.01),
    ],
    requires_project=False,
)
def water_softener(ctx: FeatureContext, values: dict) -> dict:
    """Estimate resin volume from flow, hardness removal and regeneration interval."""
    removal = max(values["hardnessMgL"] - values["targetHardnessMgL"], 0)
    daily_m3 = values["flowM3h"] * 24
    hardness_load_eq_day = daily_m3 * removal / 50
    resin_l = hardness_load_eq_day * values["regenerationIntervalDays"] / values["resinCapacityEqL"]
    if values["targetHardnessMgL"] > values["hardnessMgL"]:
        raise FeatureInputError("Target hardness cannot exceed the measured feed hardness.")
    return result(
        summary={"hardnessRemovalMgL": removal, "resinVolumeL": resin_l},
        notes=[
            "Equivalent load uses 50 mg/L as CaCO₃ per milliequivalent; verify resin capacity and regeneration salt consumption with supplier data."
        ],
    )


@feature(
    "mepPlumbingDesign.filtrationUnit",
    "Filtration Unit",
    part="mep",
    fields=[
        number("designFlowM3h", "Design flow", 2.0, unit="m³/h", min=0.01),
        number("filtrationRateM3hM2", "Filter loading rate", 8.0, unit="m³/h·m²", min=0.01),
        number("bedDepthM", "Media bed depth", 0.6, unit="m", min=0.1),
    ],
    requires_project=False,
)
def filtration_unit(ctx: FeatureContext, values: dict) -> dict:
    """Size required filter bed area and media volume."""
    area = values["designFlowM3h"] / values["filtrationRateM3hM2"]
    volume = area * values["bedDepthM"]
    return result(
        summary={"filterAreaM2": area, "mediaVolumeM3": volume},
        notes=[
            "Area is design flow divided by the entered filtration loading rate; media depth is an explicit design input."
        ],
    )


@feature(
    "mepPlumbingDesign.disinfectionUnit",
    "Disinfection Unit",
    part="mep",
    fields=[
        number("flowM3h", "Disinfection flow", 2.0, unit="m³/h", min=0.01),
        number("contactMinutes", "Contact time", 30, unit="min", min=0.1),
        number("doseMgL", "Applied dose", 2.0, unit="mg/L", min=0),
    ],
    requires_project=False,
)
def disinfection_unit(ctx: FeatureContext, values: dict) -> dict:
    """Calculate contact volume and chemical mass feed at the selected dose."""
    volume_m3 = values["flowM3h"] * values["contactMinutes"] / 60
    feed_g_h = values["flowM3h"] * values["doseMgL"]
    return result(
        summary={"contactVolumeM3": volume_m3, "chemicalFeedGPerH": feed_g_h},
        notes=[
            "Contact volume is flow × detention time; chemical feed assumes the entered dose is fully available at the point of application."
        ],
    )


@feature(
    "mepPlumbingDesign.pressureReducingValve",
    "Pressure Reducing Valve",
    part="mep",
    fields=[
        number("staticHeadM", "Upstream static head", 45, unit="m", min=0),
        number("targetPressureKpa", "Target downstream pressure", 300, unit="kPa", min=0),
        number("flowLps", "Design flow", 1.0, unit="L/s", min=0.01),
    ],
    requires_project=False,
)
def pressure_reducing_valve(ctx: FeatureContext, values: dict) -> dict:
    """Calculate pressure reduction and required valve duty."""
    upstream = values["staticHeadM"] * 9.80665
    drop = upstream - values["targetPressureKpa"]
    if drop < 0:
        raise FeatureInputError(
            "The target pressure is above the available upstream static pressure."
        )
    return result(
        summary={
            "upstreamPressureKpa": upstream,
            "requiredReductionKpa": drop,
            "flowLps": values["flowLps"],
        },
        notes=[
            "Static pressure is converted from water head at 9.80665 kPa/m; confirm dynamic pressure and valve cavitation limits against the selected product."
        ],
    )


@feature(
    "mepPlumbingDesign.balancingValve",
    "Balancing Valve",
    part="mep",
    fields=[
        number("branchFlowLps", "Branch design flow", 0.8, unit="L/s", min=0.01),
        number(
            "availableDifferentialKpa", "Available differential pressure", 25, unit="kPa", min=0.1
        ),
        number("branchLossKpa", "Branch circuit loss", 12, unit="kPa", min=0),
        number("targetValveAuthority", "Target valve authority", 0.5, min=0.05, max=0.95),
    ],
    requires_project=False,
)
def balancing_valve(ctx: FeatureContext, values: dict) -> dict:
    """Determine balancing-valve pressure drop for the target branch authority."""
    circuit = values["branchLossKpa"]
    valve_drop = circuit * (1 / values["targetValveAuthority"] - 1)
    available = values["availableDifferentialKpa"]
    return result(
        summary={
            "requiredValveDropKpa": valve_drop,
            "availableDifferentialKpa": available,
            "passes": valve_drop <= available,
        },
        notes=[
            "Valve authority is Δp across the valve divided by the total branch differential; this idealized calculation excludes vendor-specific rangeability."
        ],
    )


@feature(
    "mepPlumbingDesign.pipeInsulation",
    "Pipe Insulation",
    part="mep",
    fields=[
        number("pipeOuterDiameterMm", "Pipe outside diameter", 60, unit="mm", min=1),
        number("insulationThicknessMm", "Insulation thickness", 25, unit="mm", min=0.1),
        number("conductivityWmK", "Insulation conductivity", 0.035, unit="W/(m·K)", min=0.001),
        number(
            "temperatureDifferenceC", "Pipe-to-ambient temperature difference", 25, unit="°C", min=0
        ),
    ],
    requires_project=False,
)
def pipe_insulation(ctx: FeatureContext, values: dict) -> dict:
    """Calculate cylindrical insulation heat loss per pipe length."""
    r1 = values["pipeOuterDiameterMm"] / 2000
    r2 = r1 + values["insulationThicknessMm"] / 1000
    heat_loss = (
        2
        * math.pi
        * values["conductivityWmK"]
        * values["temperatureDifferenceC"]
        / math.log(r2 / r1)
    )
    return result(
        summary={"heatLossWPerM": heat_loss, "outerDiameterMm": 2 * r2 * 1000},
        notes=[
            "Steady one-dimensional radial conduction through cylindrical insulation; surface convection, pipe-wall resistance and thermal bridges are excluded."
        ],
    )


@feature(
    "mepPlumbingDesign.plumbingReport",
    "Plumbing Report",
    part="mep",
    requires_project=True,
)
def plumbing_report(ctx: FeatureContext, values: dict) -> dict:
    """Summarize plumbing design outputs from the current MEP model."""
    from saengine.library.mep import parse
    from saengine.plumbing.report import plumbing_results

    raw = ctx.raw("mep")
    if raw is None or not isinstance(raw.get("plumbing"), dict):
        raise FeatureInputError("Add plumbing stories and systems to 07 MEP/mep.json first.")
    model = parse(json.dumps(raw))
    report_data = plumbing_results(model)
    if not report_data:
        raise FeatureInputError("The plumbing model has no completed sizing results to report.")
    return result(
        summary={"resultSections": len(report_data)},
        tables=[
            table(
                "Plumbing report sections",
                [("section", "Section"), ("items", "Items")],
                [
                    {"section": key, "items": len(value) if isinstance(value, list) else 1}
                    for key, value in report_data.items()
                ],
            )
        ],
        notes=[
            "Report summary is derived from the current project plumbing model; no design data is modified."
        ],
    )


@feature(
    "mepPlumbingDesign.materialsList",
    "Materials List",
    part="mep",
    requires_project=True,
)
def plumbing_materials_list(ctx: FeatureContext, values: dict) -> dict:
    """List project plumbing risers and specified pipe materials."""
    raw = ctx.raw("mep")
    plumbing = raw.get("plumbing") if raw else None
    risers = plumbing.get("risers", []) if isinstance(plumbing, dict) else []
    if not risers:
        raise FeatureInputError("Add plumbing risers with system and material data first.")
    rows = [
        {
            "id": row.get("id", ""),
            "system": row.get("system", ""),
            "material": row.get("material", ""),
            "diameterMm": row.get("diameter"),
        }
        for row in risers
    ]
    return result(
        summary={
            "riserCount": len(rows),
            "materialCount": len({r["material"] for r in rows if r["material"]}),
        },
        tables=[
            table(
                "Plumbing materials list",
                [
                    ("id", "Riser"),
                    ("system", "System"),
                    ("material", "Material"),
                    ("diameterMm", "Diameter", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "Quantities are limited to risers explicitly recorded in the project; branch runs and fittings require modelled takeoffs."
        ],
    )
