"""Dedicated mepPlumbingRainwater MEP feature registrations."""

from __future__ import annotations

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
    "mepPlumbingRainwater.catchmentArea",
    "Catchment Area",
    part="mep",
    fields=[number("area", "Area", 100, unit="m?", min=0)],
    requires_project=True,
)
def catchmentArea(ctx: FeatureContext, values: dict) -> dict:
    """Catchment Area: Collection."""
    design_value = float(values["area"])
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
                "Catchment Area",
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
    "mepPlumbingRainwater.disinfection",
    "Disinfection",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def disinfection(ctx: FeatureContext, values: dict) -> dict:
    """Disinfection: Treatment."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Disinfection",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.distributionPump",
    "Distribution Pump",
    part="mep",
    fields=[
        number("flowLps", "Harvested reuse booster flow", 1.2, unit="L/s", min=0.05),
        number("staticHeadM", "Static lift to highest outlet", 18.0, unit="m", min=0.0),
        number("frictionHeadM", "Pipework & filter head loss", 6.5, unit="m", min=0.5),
        number("residualHeadM", "Required outlet residual head", 10.0, unit="m", min=2.0),
        number("pumpEff", "Pump + motor combined efficiency", 0.58, min=0.2, max=0.9),
    ],
    requires_project=False,
)
def distributionPump(ctx: FeatureContext, values: dict) -> dict:
    """Size reclaimed rainwater distribution booster pump total dynamic head and motor power."""
    q_lps = float(values["flowLps"])
    tdh_m = (
        float(values["staticHeadM"])
        + float(values["frictionHeadM"])
        + float(values["residualHeadM"])
    )
    hyd_kw = 9.80665 * (q_lps / 1000.0) * tdh_m
    motor_kw = hyd_kw / float(values["pumpEff"])
    return result(
        summary={
            "flowLps": q_lps,
            "totalDynamicHeadM": round(tdh_m, 2),
            "motorPowerKw": round(motor_kw, 2),
        },
        tables=[
            table(
                "Rainwater distribution pump duty",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Design peak flow", "value": q_lps, "unit": "L/s"},
                    {"parameter": "Total dynamic head", "value": round(tdh_m, 2), "unit": "m"},
                    {"parameter": "Hydraulic water power", "value": round(hyd_kw, 3), "unit": "kW"},
                    {
                        "parameter": "Required motor power",
                        "value": round(motor_kw, 2),
                        "unit": "kW",
                    },
                ],
            )
        ],
        notes=["TDH = H_static + H_friction + H_residual; P_motor = rho * g * Q * H / eta."],
    )


@feature(
    "mepPlumbingRainwater.downpipe",
    "Downpipe",
    part="mep",
    fields=[
        number("catchmentAreaM2", "Roof catchment area per downpipe", 180.0, unit="m²", min=5.0),
        number("rainfallMmPerHr", "Design rainfall intensity", 100.0, unit="mm/h", min=10.0),
        number("runoffCoeff", "Roof runoff coefficient C", 0.95, min=0.2, max=1.0),
    ],
    requires_project=False,
)
def downpipe(ctx: FeatureContext, values: dict) -> dict:
    """Size circular rainwater leader/downpipe diameter and peak flow via saengine.plumbing.rainwater."""
    from saengine.plumbing import rainwater

    area = float(values["catchmentAreaM2"])
    rain = float(values["rainfallMmPerHr"])
    c_eff = float(values["runoffCoeff"])
    flow_lps = float(rainwater.flow(area * c_eff, rain)) / 60.0
    diam_mm = int(rainwater.leader_size(area * c_eff, rain))
    return result(
        summary={"runoffFlowLps": round(flow_lps, 2), "leaderDiameterMm": diam_mm},
        tables=[
            table(
                "Rainwater downpipe sizing",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Effective roof area", "value": round(area * c_eff, 1), "unit": "m²"},
                    {"item": "Rainfall intensity", "value": rain, "unit": "mm/h"},
                    {"item": "Peak design flow", "value": round(flow_lps, 2), "unit": "L/s"},
                    {"item": "Minimum downpipe diameter", "value": diam_mm, "unit": "mm"},
                ],
            )
        ],
        notes=[
            "Computed via saengine.plumbing.rainwater.flow and leader_size from catchment & intensity."
        ],
    )


@feature(
    "mepPlumbingRainwater.dualPumpController",
    "Dual Pump Controller",
    part="mep",
    fields=[
        number("dutyFlowLps", "Single pump rated flow Q", 2.0, unit="L/s", min=0.1),
        number("maxStartsPerHour", "Maximum motor starts per hour", 12.0, min=2.0, max=30.0),
        number(
            "leadLagFactor", "Total peak duty ratio (Duty+Assist / Single)", 1.6, min=1.0, max=2.0
        ),
    ],
    requires_project=False,
)
def dualPumpController(ctx: FeatureContext, values: dict) -> dict:
    """Size duty/standby alternation wet-well working volume to cap motor start frequency."""
    q_lpm = float(values["dutyFlowLps"]) * 60.0
    n_starts = float(values["maxStartsPerHour"])
    cycle_min = 60.0 / n_starts
    min_working_l = q_lpm * cycle_min / 4.0
    lead_cut_in_lps = float(values["dutyFlowLps"])
    lag_cut_in_lps = float(values["dutyFlowLps"]) * float(values["leadLagFactor"])
    return result(
        summary={
            "minCycleTimeMin": round(cycle_min, 2),
            "minWetWellVolumeL": round(min_working_l, 1),
            "lagCutInFlowLps": round(lag_cut_in_lps, 2),
        },
        tables=[
            table(
                "Dual-pump lead/lag controller",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "parameter": "Minimum pump cycle",
                        "value": round(cycle_min, 2),
                        "unit": "min",
                    },
                    {
                        "parameter": "Minimum active buffer volume",
                        "value": round(min_working_l, 1),
                        "unit": "L",
                    },
                    {
                        "parameter": "Lead pump trip flow",
                        "value": round(lead_cut_in_lps, 2),
                        "unit": "L/s",
                    },
                    {
                        "parameter": "Lag assist cut-in flow",
                        "value": round(lag_cut_in_lps, 2),
                        "unit": "L/s",
                    },
                ],
            )
        ],
        notes=[
            "Minimum working buffer V = Q_pump * T_cycle / 4 limits maximum pump starts per hour."
        ],
    )


@feature(
    "mepPlumbingRainwater.filterUnit",
    "Filter Unit",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def filterUnit(ctx: FeatureContext, values: dict) -> dict:
    """Filter Unit: Treatment."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Filter Unit",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.firstFlush",
    "First Flush",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def firstFlush(ctx: FeatureContext, values: dict) -> dict:
    """First Flush: Collection."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "First Flush",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.gutterSize",
    "Gutter Size",
    part="mep",
    fields=[
        number("catchmentAreaM2", "Roof area draining to gutter", 200.0, unit="m²", min=5.0),
        number("rainfallMmPerHr", "Design rainfall intensity", 100.0, unit="mm/h", min=10.0),
        number("slopePct", "Gutter longitudinal slope", 1.0, unit="%", min=0.25, max=5.0),
    ],
    requires_project=False,
)
def gutterSize(ctx: FeatureContext, values: dict) -> dict:
    """Size semicircular roof gutter width/diameter via saengine.plumbing.rainwater.gutter_size."""
    from saengine.plumbing import rainwater

    area = float(values["catchmentAreaM2"])
    rain = float(values["rainfallMmPerHr"])
    raw_slope = float(values["slopePct"]) * 10.0
    slope_mm_per_m = max((s for s in (5, 10, 20, 40) if s <= raw_slope), default=5)
    width_mm = int(rainwater.gutter_size(area, rain, slope=slope_mm_per_m))
    flow_lps = float(rainwater.flow(area, rain)) / 60.0
    return result(
        summary={"gutterWidthMm": width_mm, "peakFlowLps": round(flow_lps, 2)},
        tables=[
            table(
                "Roof gutter sizing",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Catchment area", "value": area, "unit": "m²"},
                    {"item": "Peak gutter flow", "value": round(flow_lps, 2), "unit": "L/s"},
                    {"item": "Gutter slope", "value": f"{slope_mm_per_m:g}", "unit": "mm/m"},
                    {"item": "Minimum gutter diameter", "value": width_mm, "unit": "mm"},
                ],
            )
        ],
        notes=["Computed via saengine.plumbing.rainwater.gutter_size."],
    )


@feature(
    "mepPlumbingRainwater.levelSensing",
    "Level Sensing",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def levelSensing(ctx: FeatureContext, values: dict) -> dict:
    """Level Sensing: Water Quality."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Level Sensing",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.mainsBackup",
    "Mains Backup",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def mainsBackup(ctx: FeatureContext, values: dict) -> dict:
    """Mains Backup: Water Quality."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Mains Backup",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.overflowRoute",
    "Overflow Route",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def overflowRoute(ctx: FeatureContext, values: dict) -> dict:
    """Overflow Route: Storage."""
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
                "Overflow Route",
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
    "mepPlumbingRainwater.pressureTank",
    "Pressure Tank",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def pressureTank(ctx: FeatureContext, values: dict) -> dict:
    """Pressure Tank: Pumping Systems."""
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
                "Pressure Tank",
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
    "mepPlumbingRainwater.retentionBasin",
    "Retention Basin",
    part="mep",
    fields=[
        number("catchmentM2", "Contributing site area", 2500.0, unit="m²", min=50.0),
        number("runoffCoeff", "Composite runoff coefficient C", 0.75, min=0.1, max=1.0),
        number("rainfallMmPerHr", "Design storm intensity", 80.0, unit="mm/h", min=5.0),
        number("durationMin", "Critical storm duration", 60.0, unit="min", min=5.0),
        number(
            "allowableOutflowLps", "Throttled orifice discharge limit", 15.0, unit="L/s", min=0.5
        ),
    ],
    requires_project=False,
)
def retentionBasin(ctx: FeatureContext, values: dict) -> dict:
    """Compute stormwater detention/retention basin storage volume via Rational mass balance."""
    import math

    a = float(values["catchmentM2"])
    c = float(values["runoffCoeff"])
    i = float(values["rainfallMmPerHr"])
    t_s = float(values["durationMin"]) * 60.0
    q_in_lps = c * i * a / 3600.0
    q_out_lps = float(values["allowableOutflowLps"])
    vol_in_m3 = q_in_lps * t_s / 1000.0
    vol_out_m3 = q_out_lps * t_s / 1000.0
    storage_m3 = max(0.0, vol_in_m3 - vol_out_m3)
    orifice_mm = round(
        math.sqrt((q_out_lps / 1000.0) / (0.62 * math.sqrt(2.0 * 9.81 * 1.5)) * 4.0 / math.pi)
        * 1000.0,
        0,
    )
    return result(
        summary={
            "peakInflowLps": round(q_in_lps, 2),
            "storageVolumeM3": round(storage_m3, 1),
            "orificeDiameterMm": orifice_mm,
        },
        tables=[
            table(
                "Stormwater retention basin sizing",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "parameter": "Peak Rational inflow Q_in",
                        "value": round(q_in_lps, 2),
                        "unit": "L/s",
                    },
                    {"parameter": "Throttled outflow Q_out", "value": q_out_lps, "unit": "L/s"},
                    {
                        "parameter": "Required detention storage",
                        "value": round(storage_m3, 1),
                        "unit": "m³",
                    },
                    {
                        "parameter": "Approx. orifice bore (1.5 m head)",
                        "value": orifice_mm,
                        "unit": "mm",
                    },
                ],
            )
        ],
        notes=[
            "Storage volume V = (Q_in - Q_out) * t; verify over multiple storm durations for peak V."
        ],
    )


@feature(
    "mepPlumbingRainwater.runoffCoefficient",
    "Runoff Coefficient",
    part="mep",
    fields=[
        number("roofAreaM2", "Impervious roof area (C=0.95)", 800.0, unit="m²", min=0.0),
        number("pavedAreaM2", "Paved hardscape area (C=0.85)", 400.0, unit="m²", min=0.0),
        number("greenAreaM2", "Landscaped soil area (C=0.25)", 300.0, unit="m²", min=0.0),
        number("rainfallMmPerHr", "Design rainfall intensity", 100.0, unit="mm/h", min=5.0),
    ],
    requires_project=False,
)
def runoffCoefficient(ctx: FeatureContext, values: dict) -> dict:
    """Compute area-weighted composite runoff coefficient and peak stormwater runoff flow."""
    a_r = float(values["roofAreaM2"])
    a_p = float(values["pavedAreaM2"])
    a_g = float(values["greenAreaM2"])
    tot = a_r + a_p + a_g
    if tot <= 0:
        raise FeatureInputError("Total catchment area must be positive.")
    c_comp = (0.95 * a_r + 0.85 * a_p + 0.25 * a_g) / tot
    q_lps = c_comp * float(values["rainfallMmPerHr"]) * tot / 3600.0
    return result(
        summary={
            "totalAreaM2": round(tot, 1),
            "compositeC": round(c_comp, 3),
            "peakRunoffLps": round(q_lps, 2),
        },
        tables=[
            table(
                "Composite catchment runoff",
                [
                    ("surface", "Surface"),
                    ("areaM2", "Area", "m²"),
                    ("c", "C"),
                    ("weighted", "C·A", "m²"),
                ],
                [
                    {"surface": "Roof", "areaM2": a_r, "c": 0.95, "weighted": round(0.95 * a_r, 1)},
                    {
                        "surface": "Paved hardscape",
                        "areaM2": a_p,
                        "c": 0.85,
                        "weighted": round(0.85 * a_p, 1),
                    },
                    {
                        "surface": "Landscaped",
                        "areaM2": a_g,
                        "c": 0.25,
                        "weighted": round(0.25 * a_g, 1),
                    },
                    {
                        "surface": "Composite total",
                        "areaM2": round(tot, 1),
                        "c": round(c_comp, 3),
                        "weighted": round(c_comp * tot, 1),
                    },
                ],
            )
        ],
        notes=["Rational method Q [L/s] = C_comp * I [mm/h] * A [m2] / 3600."],
    )


@feature(
    "mepPlumbingRainwater.sedimentTrap",
    "Sediment Trap",
    part="mep",
    fields=[
        number("inflowLps", "Design first-flush / inlet flow", 8.0, unit="L/s", min=0.2),
        number("detentionSec", "Minimum grit settling detention time", 45.0, unit="s", min=10.0),
        number("chamberDepthM", "Liquid settling depth", 1.2, unit="m", min=0.5),
    ],
    requires_project=False,
)
def sedimentTrap(ctx: FeatureContext, values: dict) -> dict:
    """Size stormwater sediment/grit trap chamber volume, plan area, and surface overflow rate."""
    q_m3s = float(values["inflowLps"]) / 1000.0
    vol_m3 = q_m3s * float(values["detentionSec"])
    area_m2 = vol_m3 / float(values["chamberDepthM"])
    sor_mm_per_s = (q_m3s / area_m2) * 1000.0
    return result(
        summary={
            "chamberVolumeM3": round(vol_m3, 3),
            "planAreaM2": round(area_m2, 2),
            "surfaceOverflowMmPerS": round(sor_mm_per_s, 2),
        },
        tables=[
            table(
                "Sediment trap / first-flush chamber",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Wet settling volume", "value": round(vol_m3, 3), "unit": "m³"},
                    {"item": "Minimum plan area", "value": round(area_m2, 2), "unit": "m²"},
                    {
                        "item": "Surface overflow velocity",
                        "value": round(sor_mm_per_s, 2),
                        "unit": "mm/s",
                    },
                    {"item": "Detention time", "value": values["detentionSec"], "unit": "s"},
                ],
            )
        ],
        notes=[
            "Lower surface overflow rate than particle settling velocity allows sand/silt capture ahead of cistern."
        ],
    )


@feature(
    "mepPlumbingRainwater.sizingMethod",
    "Sizing Method",
    part="mep",
    fields=[
        number("roofAreaM2", "Roof collection area", 600.0, unit="m²", min=10.0),
        number("annualRainfallMm", "Mean annual rainfall", 1800.0, unit="mm/yr", min=50.0),
        number("runoffCoeff", "Runoff & filter efficiency", 0.85, min=0.2, max=0.95),
        number("dailyNonPotableM3", "Daily non-potable demand", 2.5, unit="m³/d", min=0.1),
        number("dryDays", "Dry-spell reserve window", 20.0, unit="days", min=1.0),
    ],
    requires_project=False,
)
def sizingMethod(ctx: FeatureContext, values: dict) -> dict:
    """Compare supply-limited vs demand-limited rainwater cistern sizing balance."""
    annual_yield_m3 = (
        float(values["roofAreaM2"])
        * float(values["runoffCoeff"])
        * (float(values["annualRainfallMm"]) / 1000.0)
    )
    annual_demand_m3 = float(values["dailyNonPotableM3"]) * 365.0
    intermediate_tank_m3 = 0.05 * min(annual_yield_m3, annual_demand_m3)
    dry_spell_tank_m3 = float(values["dailyNonPotableM3"]) * float(values["dryDays"])
    governing = min(dry_spell_tank_m3, annual_yield_m3 * 0.25)
    regime = "Demand-limited" if annual_yield_m3 >= annual_demand_m3 else "Supply-limited"
    return result(
        summary={
            "annualYieldM3": round(annual_yield_m3, 1),
            "annualDemandM3": round(annual_demand_m3, 1),
            "recommendedTankM3": round(governing, 1),
            "regime": regime,
        },
        tables=[
            table(
                "Cistern sizing balance",
                [("method", "Method"), ("volumeM3", "Tank / Volume", "m³"), ("notes", "Basis")],
                [
                    {
                        "method": "Annual roof yield",
                        "volumeM3": round(annual_yield_m3, 1),
                        "notes": "Supply potential",
                    },
                    {
                        "method": "Annual non-potable demand",
                        "volumeM3": round(annual_demand_m3, 1),
                        "notes": regime,
                    },
                    {
                        "method": "5% annual rule of thumb",
                        "volumeM3": round(intermediate_tank_m3, 1),
                        "notes": "min(Y, D) x 0.05",
                    },
                    {
                        "method": "Dry-period storage",
                        "volumeM3": round(dry_spell_tank_m3, 1),
                        "notes": f"{values['dryDays']:g} days reserve",
                    },
                ],
            )
        ],
        notes=[
            "Compares intermediate 5% supply/demand envelope with site-specific dry-spell autonomy."
        ],
    )


@feature(
    "mepPlumbingRainwater.submersiblePump",
    "Submersible Pump",
    part="mep",
    fields=[
        number("flowLps", "Sump discharge flow", 3.5, unit="L/s", min=0.2),
        number("liftM", "Vertical static discharge lift", 6.0, unit="m", min=0.5),
        number("pipeLossM", "Discharge pipe + check valve loss", 2.8, unit="m", min=0.2),
        number("submergenceMm", "Minimum pump impeller submergence", 450.0, unit="mm", min=100.0),
    ],
    requires_project=False,
)
def submersiblePump(ctx: FeatureContext, values: dict) -> dict:
    """Size basement stormwater sump submersible pump head, power, and NPSHa margin."""
    q_lps = float(values["flowLps"])
    tdh_m = float(values["liftM"]) + float(values["pipeLossM"]) + 0.5
    motor_kw = (9.80665 * (q_lps / 1000.0) * tdh_m) / 0.52
    npsha_m = 10.33 + float(values["submergenceMm"]) / 1000.0 - 0.32 - 0.30
    return result(
        summary={
            "totalHeadM": round(tdh_m, 2),
            "motorKw": round(motor_kw, 2),
            "npshaM": round(npsha_m, 2),
        },
        tables=[
            table(
                "Submersible sump pump check",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Discharge flow", "value": q_lps, "unit": "L/s"},
                    {"parameter": "Total dynamic head", "value": round(tdh_m, 2), "unit": "m"},
                    {
                        "parameter": "Motor shaft power (η=52%)",
                        "value": round(motor_kw, 2),
                        "unit": "kW",
                    },
                    {"parameter": "Available NPSHa", "value": round(npsha_m, 2), "unit": "m"},
                ],
            )
        ],
        notes=["Ensures solids-handling impeller remains submerged above vortex formation depth."],
    )


@feature(
    "mepPlumbingRainwater.tankInlet",
    "Tank Inlet",
    part="mep",
    fields=[
        number("inflowLps", "Design peak inlet flow", 12.0, unit="L/s", min=0.5),
        number("maxInletVelMs", "Calmed inlet velocity limit", 0.90, unit="m/s", min=0.3, max=2.0),
    ],
    requires_project=False,
)
def tankInlet(ctx: FeatureContext, values: dict) -> dict:
    """Size smoothed tank inlet header and overflow pipe diameter one size larger than inlet."""
    import math

    from saengine.plumbing import rainwater

    q_m3s = float(values["inflowLps"]) / 1000.0
    v_lim = float(values["maxInletVelMs"])
    d_min_mm = math.sqrt(4.0 * q_m3s / (math.pi * v_lim)) * 1000.0
    inlet_dn = int(rainwater.next_size(d_min_mm))
    overflow_dn = int(rainwater.next_size(inlet_dn + 1.0))
    actual_v = q_m3s / (math.pi * ((inlet_dn / 1000.0) / 2.0) ** 2)
    return result(
        summary={
            "inletDiameterMm": inlet_dn,
            "overflowDiameterMm": overflow_dn,
            "inletVelocityMs": round(actual_v, 2),
        },
        tables=[
            table(
                "Cistern inlet & overflow sizing",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Calmed inlet bore", "value": inlet_dn, "unit": "mm"},
                    {"item": "Actual inlet velocity", "value": round(actual_v, 2), "unit": "m/s"},
                    {"item": "Overflow pipe bore (upsized)", "value": overflow_dn, "unit": "mm"},
                ],
            )
        ],
        notes=[
            "Calmed inlet prevents bottom sediment resuspension; overflow exceeds inlet capacity."
        ],
    )


@feature(
    "mepPlumbingRainwater.tankSize",
    "Tank Size",
    part="mep",
    fields=[
        number("population", "Building equivalent population", 200.0, min=1.0),
        number("catchmentAreaM2", "Roof collection area", 800.0, unit="m²", min=10.0),
        number("annualRainfallMm", "Mean annual rainfall", 1800.0, unit="mm/yr", min=50.0),
    ],
    requires_project=False,
)
def tankSize(ctx: FeatureContext, values: dict) -> dict:
    """Estimate rainwater harvesting tank capacity via saengine.plumbing.rainwater & 07 MEP if open."""
    from saengine.library.bim import BuildingModel
    from saengine.library.mep import MepModel
    from saengine.plumbing import rainwater
    from saengine.plumbing.building import Building

    if ctx.root is not None:
        raw_mep = ctx.raw("mep")
        if isinstance(raw_mep, dict):
            mep = MepModel.model_validate(raw_mep)
            raw_bim = ctx.raw("bim")
            bldg = (
                Building.of(BuildingModel.model_validate(raw_bim))
                if isinstance(raw_bim, dict)
                else Building()
            )
            res = rainwater.harvesting(mep.plumbing, bldg, float(values["population"]))
            engine_notes = [str(n) for n in res.get("notes") or []]
            if res.get("required") is None and res.get("plotArea") is None:
                # The engine needs the plot area to decide; say so rather than a table of blanks.
                raise FeatureInputError(
                    "; ".join(engine_notes) or "Enter the plot area in 07 MEP (plumbing) first."
                )
            rows = [
                {"item": str(k), "value": str(v)}
                for k, v in res.items()
                if k != "notes" and v is not None and not isinstance(v, (dict, list))
            ]
            return result(
                summary={
                    k: v
                    for k, v in res.items()
                    if v is not None and isinstance(v, (int, float, str, bool))
                },
                tables=[
                    table(
                        "Project rainwater harvesting tank sizing",
                        [("item", "Parameter"), ("value", "Value")],
                        rows,
                    )
                ],
                notes=[
                    *engine_notes,
                    "Computed from 07 MEP/mep.json plumbing catchments by the rainwater engine.",
                ],
            )
    yield_m3 = float(values["catchmentAreaM2"]) * 0.85 * float(values["annualRainfallMm"]) / 1000.0
    demand_lpd = float(values["population"]) * 40.0
    storage_m3 = min(yield_m3 * 0.06, (demand_lpd * 15.0) / 1000.0)
    return result(
        summary={"annualYieldM3": round(yield_m3, 1), "recommendedTankM3": round(storage_m3, 1)},
        tables=[
            table(
                "Standalone harvesting tank estimate",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Annual net roof yield", "value": round(yield_m3, 1), "unit": "m³"},
                    {
                        "item": "Estimated daily non-potable demand",
                        "value": round(demand_lpd, 0),
                        "unit": "L/d",
                    },
                    {
                        "item": "Recommended tank size (15d / 6%)",
                        "value": round(storage_m3, 1),
                        "unit": "m³",
                    },
                ],
            )
        ],
        notes=[
            "Uses 40 L/person/day non-potable reuse demand and 0.85 catchment yield factor when no project is open."
        ],
    )


@feature(
    "mepPlumbingRainwater.uvSteriliser",
    "UV Steriliser",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def uvSteriliser(ctx: FeatureContext, values: dict) -> dict:
    """UV Steriliser: Water Quality."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "UV Steriliser",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingRainwater.yieldEstimate",
    "Yield Estimate",
    part="mep",
    fields=[number("flow", "Design flow", 100, unit="l/s", min=0)],
    requires_project=True,
)
def yieldEstimate(ctx: FeatureContext, values: dict) -> dict:
    """Yield Estimate: Treatment."""
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
                "Yield Estimate",
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
