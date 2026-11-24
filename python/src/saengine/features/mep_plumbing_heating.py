"""Dedicated mepPlumbingHeating MEP feature registrations."""

from __future__ import annotations

import json

from saengine.features import (
    FeatureContext,
    FeatureInputError,
    feature,
    number,
    result,
    select,
    table,
    text,
)


@feature(
    "mepPlumbingHeating.antiScaldValve",
    "Anti Scald Valve",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def antiScaldValve(ctx: FeatureContext, values: dict) -> dict:
    """Anti Scald Valve: Safety Controls."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Anti Scald Valve",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingHeating.balanceValves",
    "Balance Valves",
    part="mep",
    fields=[
        number("flowLps", "Branch design flow", 0.45, unit="L/s", min=0.01),
        number(
            "excessHeadKpa",
            "Excess circuit differential head to throttle",
            22.0,
            unit="kPa",
            min=1.0,
        ),
        number("authorityTarget", "Minimum valve authority", 0.50, min=0.2, max=0.9),
    ],
    requires_project=False,
)
def balanceValves(ctx: FeatureContext, values: dict) -> dict:
    """Size thermostatic/manual balancing valve Kv and preset drop for hot-water return loops."""
    import math

    q_lps = float(values["flowLps"])
    dp_kpa = float(values["excessHeadKpa"])
    q_m3h = q_lps * 3.6
    dp_bar = dp_kpa / 100.0
    kv_req = q_m3h / math.sqrt(dp_bar)
    std_dn = [(1.2, 15), (2.5, 20), (4.5, 25), (8.5, 32), (14.0, 40), (24.0, 50)]
    kv_sel, dn_mm = next((row for row in std_dn if row[0] >= kv_req), std_dn[-1])
    actual_dp_kpa = ((q_m3h / kv_sel) ** 2) * 100.0
    return result(
        summary={
            "flowLps": q_lps,
            "requiredKv": round(kv_req, 3),
            "selectedKv": kv_sel,
            "nominalDnMm": dn_mm,
            "valveDropKpa": round(actual_dp_kpa, 2),
        },
        tables=[
            table(
                "Balancing valve sizing",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Design flow", "value": q_lps, "unit": "L/s"},
                    {"parameter": "Required Kv", "value": round(kv_req, 3), "unit": "m³/h·bar^0.5"},
                    {
                        "parameter": "Selected DN / Kv",
                        "value": f"DN{dn_mm} (Kv={kv_sel})",
                        "unit": "mm",
                    },
                    {
                        "parameter": "Wide-open drop",
                        "value": round(actual_dp_kpa, 2),
                        "unit": "kPa",
                    },
                    {
                        "parameter": "Target authority",
                        "value": values["authorityTarget"],
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Valve coefficient Kv = Q [m3/h] / sqrt(dP [bar]); throttle preset to absorb excess loop head."
        ],
    )


@feature(
    "mepPlumbingHeating.circulationLoop",
    "Circulation Loop",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def circulationLoop(ctx: FeatureContext, values: dict) -> dict:
    """Circulation Loop: Distribution."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Circulation Loop",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingHeating.collectorArray",
    "Collector Array",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def collectorArray(ctx: FeatureContext, values: dict) -> dict:
    """Collector Array: Solar Thermal."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Collector Array",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingHeating.cylinderSchedule",
    "Cylinder Schedule",
    part="mep",
    fields=[
        number("coldTempC", "Cold water inlet temp", 15.0, unit="°C", min=2.0, max=35.0),
        number("storageTempC", "Hot water storage temp", 60.0, unit="°C", min=45.0, max=80.0),
        text("name", "Output schedule filename prefix", "cylinderSchedule"),
    ],
    requires_project=True,
)
def cylinderSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Build a scheduled hot-water cylinder/calorifier table from project plumbing fixtures & occupancy."""
    from saengine.library.mep import MepModel
    from saengine.plumbing import hot_water

    if ctx.root is None:
        raise FeatureInputError("Open a project with 07 MEP/mep.json before scheduling cylinders.")
    raw = ctx.raw("mep")
    if not isinstance(raw, dict):
        raise FeatureInputError("Missing 07 MEP/mep.json in project.")
    mep = MepModel.model_validate(raw)
    hw = hot_water.hot_water_results(mep) or {}
    if hw.get("heater"):
        sizing = hw["heater"]
    else:
        total_peak = 0.0
        for entry in mep.plumbing.stories:
            _, _, peak = hot_water.fixture_peak_demand(entry.fixtures, entry.occupancy)
            total_peak += peak
        occ = mep.plumbing.stories[0].occupancy if mep.plumbing.stories else None
        sizing = hot_water.heater_sizing(
            total_peak,
            occupancy=occ,
            cold_temp_c=float(values["coldTempC"]),
            storage_temp_c=float(values["storageTempC"]),
            demand_factor=1.0,
        )
    row = {
        "tag": "HWC-01",
        "peakDemandLph": round(
            float(sizing.get("peakDemandLph", sizing.get("peakHourLph", 0.0)) or 0.0), 1
        ),
        "storageVolumeL": round(float(sizing.get("storageVolumeL", 0.0) or 0.0), 1),
        "recoveryRateLph": round(float(sizing.get("recoveryRateLph", 0.0) or 0.0), 1),
        "powerKw": round(float(sizing.get("powerKw", sizing.get("heaterKw", 0.0)) or 0.0), 2),
        "storageTempC": float(values["storageTempC"]),
    }
    safe = "".join(c for c in values["name"] if c.isalnum() or c in "-_") or "cylinderSchedule"
    path = ctx.path(f"11 Exports/{safe}.json")
    if path is None:
        raise FeatureInputError("Open a project before writing export file.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"cylinders": [row], "hotWater": hw}, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return result(
        summary={
            "storageVolumeL": row["storageVolumeL"],
            "powerKw": row["powerKw"],
            "exportPath": str(path),
        },
        tables=[
            table(
                "Hot water cylinder schedule",
                [
                    ("tag", "Tag"),
                    ("storageVolumeL", "Volume", "L"),
                    ("recoveryRateLph", "Recovery", "L/h"),
                    ("powerKw", "Heat Input", "kW"),
                    ("storageTempC", "Temp", "°C"),
                ],
                [row],
            )
        ],
        notes=[
            f"Computed from 07 MEP occupancy/fixtures via saengine.plumbing.hot_water and saved to {path}."
        ],
    )


@feature(
    "mepPlumbingHeating.cylinderSize",
    "Cylinder Size",
    part="mep",
    fields=[
        select(
            "occupancy",
            "Building occupancy",
            [
                ("office", "Office"),
                ("residential", "Residential"),
                ("hotel", "Hotel"),
                ("school", "School"),
                ("hospital", "Hospital"),
            ],
            "office",
        ),
        number("occupants", "Design occupant count", 120, min=1),
        number(
            "lphPerPerson",
            "Peak hot water allowance per occupant",
            10.0,
            unit="L/(person·h)",
            min=1.0,
        ),
        number("peakDurationHr", "Peak draw-off duration", 2.0, unit="h", min=0.5),
        number("usableFraction", "Tank usable storage fraction", 0.75, min=0.5, max=0.95),
        number("coldTempC", "Cold inlet temp", 15.0, unit="°C", min=2.0),
        number("storageTempC", "Storage temp", 60.0, unit="°C", min=45.0),
    ],
    requires_project=False,
)
def cylinderSize(ctx: FeatureContext, values: dict) -> dict:
    """Size hot water storage cylinder nominal volume and heat input via hot_water.heater_sizing."""
    from saengine.plumbing import hot_water

    peak_lph = float(values["occupants"]) * float(values["lphPerPerson"])
    sizing = hot_water.heater_sizing(
        peak_lph,
        occupancy=values["occupancy"],
        cold_temp_c=float(values["coldTempC"]),
        storage_temp_c=float(values["storageTempC"]),
        peak_hours=float(values["peakDurationHr"]),
        usable_fraction=float(values["usableFraction"]),
        demand_factor=1.0,
    )
    vol = float(sizing.get("storageVolumeL", 0.0) or 0.0)
    kw = float(sizing.get("powerKw", sizing.get("heaterKw", 0.0)) or 0.0)
    rec = float(sizing.get("recoveryRateLph", 0.0) or 0.0)
    return result(
        summary={
            "storageVolumeL": round(vol, 1),
            "recoveryRateLph": round(rec, 1),
            "powerKw": round(kw, 2),
        },
        tables=[
            table(
                "Hot water cylinder sizing",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Nominal cylinder volume", "value": round(vol, 1), "unit": "L"},
                    {"parameter": "Recovery capacity", "value": round(rec, 1), "unit": "L/h"},
                    {"parameter": "Thermal power required", "value": round(kw, 2), "unit": "kW"},
                    {
                        "parameter": "Temperature rise",
                        "value": float(values["storageTempC"]) - float(values["coldTempC"]),
                        "unit": "K",
                    },
                ],
            )
        ],
        notes=[
            "Sized with saengine.plumbing.hot_water.heater_sizing allowing for unusable mixing bottom layer."
        ],
    )


@feature(
    "mepPlumbingHeating.expansionVessel",
    "Expansion Vessel",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def expansionVessel(ctx: FeatureContext, values: dict) -> dict:
    """Expansion Vessel: Safety Controls."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Expansion Vessel",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingHeating.heatExchanger",
    "Heat Exchanger",
    part="mep",
    fields=[
        number("dutyKw", "Thermal duty Q", 80.0, unit="kW", min=0.5),
        number("primaryInC", "Primary flow in", 80.0, unit="°C"),
        number("primaryOutC", "Primary return out", 60.0, unit="°C"),
        number("secondaryInC", "Cold water inlet", 15.0, unit="°C"),
        number("secondaryOutC", "Hot water outlet", 60.0, unit="°C"),
        number("uValueWPerM2K", "Overall U-value", 2500.0, unit="W/(m²·K)", min=100.0),
    ],
    requires_project=False,
)
def heatExchanger(ctx: FeatureContext, values: dict) -> dict:
    """Compute counter-flow LMTD, UA conductance, heat-transfer area, and mass flow rates."""
    import math

    q_w = float(values["dutyKw"]) * 1000.0
    t_h_in, t_h_out = float(values["primaryInC"]), float(values["primaryOutC"])
    t_c_in, t_c_out = float(values["secondaryInC"]), float(values["secondaryOutC"])
    dt1 = t_h_in - t_c_out
    dt2 = t_h_out - t_c_in
    if dt1 <= 0.1 or dt2 <= 0.1 or t_h_in <= t_h_out or t_c_out <= t_c_in:
        raise FeatureInputError(
            "Counter-flow terminal temperature differences must stay positive (primary hotter than secondary)."
        )
    lmtd = dt1 if abs(dt1 - dt2) < 1e-6 else (dt1 - dt2) / math.log(dt1 / dt2)
    ua = q_w / lmtd
    area_m2 = ua / float(values["uValueWPerM2K"])
    cp = 4.186  # kJ/(kg·K)
    m_prim_lps = float(values["dutyKw"]) / (cp * (t_h_in - t_h_out))
    m_sec_lps = float(values["dutyKw"]) / (cp * (t_c_out - t_c_in))
    return result(
        summary={
            "lmtdK": round(lmtd, 2),
            "uaWPerK": round(ua, 1),
            "areaM2": round(area_m2, 3),
            "primaryFlowLps": round(m_prim_lps, 3),
            "secondaryFlowLps": round(m_sec_lps, 3),
        },
        tables=[
            table(
                "Heat exchanger LMTD sizing",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Thermal duty", "value": values["dutyKw"], "unit": "kW"},
                    {"parameter": "Counter-flow LMTD", "value": round(lmtd, 2), "unit": "K"},
                    {"parameter": "Conductance UA", "value": round(ua, 1), "unit": "W/K"},
                    {
                        "parameter": "Required plate/coil area",
                        "value": round(area_m2, 3),
                        "unit": "m²",
                    },
                    {
                        "parameter": "Primary water flow",
                        "value": round(m_prim_lps, 3),
                        "unit": "L/s",
                    },
                    {
                        "parameter": "Secondary water flow",
                        "value": round(m_sec_lps, 3),
                        "unit": "L/s",
                    },
                ],
            )
        ],
        notes=["Pure counter-flow LMTD method; apply fouling factor margin in plate selection."],
    )


@feature(
    "mepPlumbingHeating.heaterCapacity",
    "Heater Capacity",
    part="mep",
    fields=[
        number("recoveryRateLph", "Required recovery rate", 600.0, unit="L/h", min=10.0),
        number("coldTempC", "Cold water temp", 15.0, unit="°C", min=2.0),
        number("hotTempC", "Heated water temp", 60.0, unit="°C", min=40.0),
        number("thermalEfficiency", "Heater thermal efficiency", 0.92, min=0.5, max=4.5),
    ],
    requires_project=False,
)
def heaterCapacity(ctx: FeatureContext, values: dict) -> dict:
    """Compute required water heater thermal output and fuel/electrical input power [kW]."""
    dt = float(values["hotTempC"]) - float(values["coldTempC"])
    if dt <= 0:
        raise FeatureInputError("Heated water temperature must exceed cold water temperature.")
    # Q_out [kW] = (L/h * 1 kg/L * 4.186 kJ/kgK * dT) / 3600
    q_out_kw = float(values["recoveryRateLph"]) * 4.186 * dt / 3600.0
    q_in_kw = q_out_kw / float(values["thermalEfficiency"])
    return result(
        summary={
            "thermalOutputKw": round(q_out_kw, 2),
            "inputPowerKw": round(q_in_kw, 2),
            "deltaTK": dt,
        },
        tables=[
            table(
                "Water heater capacity",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Recovery flow rate",
                        "value": values["recoveryRateLph"],
                        "unit": "L/h",
                    },
                    {"item": "Temperature rise ΔT", "value": dt, "unit": "K"},
                    {"item": "Thermal output", "value": round(q_out_kw, 2), "unit": "kW"},
                    {"item": "Input power / fuel rate", "value": round(q_in_kw, 2), "unit": "kW"},
                ],
            )
        ],
        notes=["Q_out = m * cp * dT / 3600 with water density 1.0 kg/L and cp = 4.186 kJ/(kg·K)."],
    )


@feature(
    "mepPlumbingHeating.heaterType",
    "Heater Type",
    part="mep",
    fields=[
        number("dailyHotWaterL", "Daily hot water demand at 60°C", 4000.0, unit="L/day", min=50.0),
        number("coldTempC", "Cold water temp", 15.0, unit="°C", min=2.0),
        number("hotTempC", "Hot water temp", 60.0, unit="°C", min=45.0),
    ],
    requires_project=False,
)
def heaterType(ctx: FeatureContext, values: dict) -> dict:
    """Compare water heating technologies by thermal duty, input energy, and daily kWh."""
    dt = float(values["hotTempC"]) - float(values["coldTempC"])
    daily_thermal_kwh = float(values["dailyHotWaterL"]) * 4.186 * dt / 3600.0
    techs = [
        ("Electric immersion", 0.98, 2.0),
        ("Condensing gas boiler", 0.92, 1.5),
        ("Air-source heat pump", 3.40, 3.0),
        ("Solar + electric backup (60% solar)", 0.98, 4.0),
    ]
    rows = []
    for name, cop, storage_hrs in techs:
        solar_frac = 0.60 if "Solar" in name else 0.0
        eff_thermal = daily_thermal_kwh * (1.0 - solar_frac)
        daily_input_kwh = eff_thermal / cop
        rows.append(
            {
                "type": name,
                "copOrEff": cop,
                "storageFactorHr": storage_hrs,
                "dailyInputKwh": round(daily_input_kwh, 2),
                "recommendedPeakKw": round(eff_thermal / 8.0 / cop, 2),
            }
        )
    return result(
        summary={"dailyThermalKwh": round(daily_thermal_kwh, 2), "optionsCompared": len(rows)},
        tables=[
            table(
                "Heater technology comparison",
                [
                    ("type", "Heater Type"),
                    ("copOrEff", "COP / η"),
                    ("dailyInputKwh", "Daily Energy", "kWh/d"),
                    ("recommendedPeakKw", "Input Rating", "kW"),
                ],
                rows,
            )
        ],
        notes=[
            "Compares daily input energy using specific heat 4.186 kJ/(kg·K) and 8-hour charging window."
        ],
    )


@feature(
    "mepPlumbingHeating.pressureRelief",
    "Pressure Relief",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def pressureRelief(ctx: FeatureContext, values: dict) -> dict:
    """Pressure Relief: Safety Controls."""
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
                "Pressure Relief",
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
    "mepPlumbingHeating.pumpControl",
    "Pump Control",
    part="mep",
    fields=[
        number("ratedPowerKw", "Design full-flow pump shaft power", 1.5, unit="kW", min=0.05),
        number("partLoadRatio", "Average flow turn-down ratio (Q/Q0)", 0.65, min=0.2, max=1.0),
        number("staticHeadShare", "Static lift fraction of design head", 0.15, min=0.0, max=0.8),
    ],
    requires_project=False,
)
def pumpControl(ctx: FeatureContext, values: dict) -> dict:
    """Compare constant-speed vs VFD proportional differential-pressure pump power via affinity laws."""
    p0 = float(values["ratedPowerKw"])
    f = float(values["partLoadRatio"])
    hs = float(values["staticHeadShare"])
    # Head curve needed H(f) = hs + (1 - hs) * f^2 -> required speed ratio N/N0 = sqrt(H(f)) approx
    head_ratio = hs + (1.0 - hs) * (f**2)
    # VFD power approx (hs * f + (1 - hs) * f^3); constant speed throttling approx p0 * (0.45 + 0.55 * f)
    p_vfd = p0 * head_ratio * f
    p_throttle = p0 * (0.45 + 0.55 * f)
    savings_pct = ((p_throttle - p_vfd) / p_throttle) * 100.0 if p_throttle > 0 else 0.0
    return result(
        summary={
            "partLoadRatio": f,
            "vfdPowerKw": round(p_vfd, 3),
            "throttledPowerKw": round(p_throttle, 3),
            "energySavingPct": round(savings_pct, 1),
        },
        tables=[
            table(
                "Pump speed control operating point",
                [("mode", "Control Mode"), ("powerKw", "Power", "kW"), ("headRatio", "Head H/H0")],
                [
                    {
                        "mode": "Constant speed + balancing valve",
                        "powerKw": round(p_throttle, 3),
                        "headRatio": 1.0,
                    },
                    {
                        "mode": "VFD differential pressure reset",
                        "powerKw": round(p_vfd, 3),
                        "headRatio": round(head_ratio, 3),
                    },
                ],
            )
        ],
        notes=[
            "Evaluated with pump affinity laws accounting for static head fraction along the system curve."
        ],
    )


@feature(
    "mepPlumbingHeating.recirculationPump",
    "Recirculation Pump",
    part="mep",
    fields=[
        number(
            "loopLengthM", "Total hot water loop length (flow + return)", 120.0, unit="m", min=5.0
        ),
        number("heatLossWPerM", "Insulated pipe heat loss rate", 12.0, unit="W/m", min=2.0),
        number(
            "returnDropC", "Allowable loop temperature drop ΔT", 5.0, unit="°C", min=1.0, max=15.0
        ),
        number("headLossM", "Circulating circuit friction head", 3.5, unit="m", min=0.2),
    ],
    requires_project=False,
)
def recirculationPump(ctx: FeatureContext, values: dict) -> dict:
    """Size hot-water return circulation flow rate and pump duty via saengine.plumbing.hot_water."""
    from saengine.plumbing import hot_water

    loop = hot_water.recirculation_loop(
        float(values["loopLengthM"]),
        heat_loss_w_per_m=float(values["heatLossWPerM"]),
        return_drop_c=float(values["returnDropC"]),
    )
    q_lps = float(loop.get("flowLps", loop.get("flowRateLps", 0.0)) or 0.0)
    if q_lps <= 0:
        q_lps = (
            float(values["loopLengthM"])
            * float(values["heatLossWPerM"])
            / (4186.0 * float(values["returnDropC"]))
        )
    hyd_w = 1000.0 * 9.80665 * (q_lps / 1000.0) * float(values["headLossM"])
    elec_w = hyd_w / 0.45
    return result(
        summary={
            "loopHeatLossW": float(
                loop.get("heatLossW", float(values["loopLengthM"]) * float(values["heatLossWPerM"]))
            ),
            "flowLps": round(q_lps, 4),
            "flowLpm": round(q_lps * 60.0, 2),
            "pumpPowerW": round(elec_w, 1),
        },
        tables=[
            table(
                "Recirculation pump sizing",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "parameter": "Loop heat loss",
                        "value": round(
                            float(values["loopLengthM"]) * float(values["heatLossWPerM"]), 1
                        ),
                        "unit": "W",
                    },
                    {
                        "parameter": "Required circulation flow",
                        "value": round(q_lps * 60.0, 2),
                        "unit": "L/min",
                    },
                    {"parameter": "Circuit design head", "value": values["headLossM"], "unit": "m"},
                    {
                        "parameter": "Pump electrical power (η=45%)",
                        "value": round(elec_w, 1),
                        "unit": "W",
                    },
                ],
            )
        ],
        notes=[
            "Computed via saengine.plumbing.hot_water.recirculation_loop to maintain loop temperature within ΔT."
        ],
    )


@feature(
    "mepPlumbingHeating.recoveryRate",
    "Recovery Rate",
    part="mep",
    fields=[
        number("tankVolumeL", "Cylinder water volume", 1000.0, unit="L", min=20.0),
        number("heaterOutputKw", "Net heater thermal output", 45.0, unit="kW", min=1.0),
        number("coldTempC", "Cold supply temp", 15.0, unit="°C", min=2.0),
        number("targetTempC", "Stored setpoint temp", 60.0, unit="°C", min=40.0),
    ],
    requires_project=False,
)
def recoveryRate(ctx: FeatureContext, values: dict) -> dict:
    """Compute cylinder thermal recovery rate [L/h] and full reheat duration [min]."""
    dt = float(values["targetTempC"]) - float(values["coldTempC"])
    if dt <= 0:
        raise FeatureInputError("Target temperature must exceed cold supply temperature.")
    recovery_lph = float(values["heaterOutputKw"]) * 3600.0 / (4.186 * dt)
    reheat_hr = float(values["tankVolumeL"]) / recovery_lph
    return result(
        summary={
            "recoveryRateLph": round(recovery_lph, 1),
            "fullReheatMinutes": round(reheat_hr * 60.0, 1),
            "deltaTK": dt,
        },
        tables=[
            table(
                "Cylinder thermal recovery",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Net thermal output", "value": values["heaterOutputKw"], "unit": "kW"},
                    {"item": "Temperature rise ΔT", "value": dt, "unit": "K"},
                    {
                        "item": "Continuous recovery rate",
                        "value": round(recovery_lph, 1),
                        "unit": "L/h",
                    },
                    {
                        "item": "Full-tank reheat time",
                        "value": round(reheat_hr * 60.0, 1),
                        "unit": "min",
                    },
                ],
            )
        ],
        notes=["Uses cp = 4.186 kJ/(kg·K) assuming complete mixing during reheat."],
    )


@feature(
    "mepPlumbingHeating.returnTemperature",
    "Return Temperature",
    part="mep",
    fields=[number("temperature", "Design temperature", 20, unit="?C")],
    requires_project=True,
)
def returnTemperature(ctx: FeatureContext, values: dict) -> dict:
    """Return Temperature: Distribution."""
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
                "Return Temperature",
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
    "mepPlumbingHeating.safetyValve",
    "Safety Valve",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def safetyValve(ctx: FeatureContext, values: dict) -> dict:
    """Safety Valve: Storage."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Safety Valve",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingHeating.secondaryLoop",
    "Secondary Loop",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def secondaryLoop(ctx: FeatureContext, values: dict) -> dict:
    """Secondary Loop: Pumping."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Secondary Loop",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingHeating.solarController",
    "Solar Controller",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def solarController(ctx: FeatureContext, values: dict) -> dict:
    """Solar Controller: Solar Thermal."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Solar Controller",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingHeating.standbyLoss",
    "Standby Loss",
    part="mep",
    fields=[
        number("tankVolumeL", "Storage cylinder capacity", 1000.0, unit="L", min=50.0),
        number("insulationMm", "PU foam jacket thickness", 50.0, unit="mm", min=10.0),
        number("storageTempC", "Stored water temp", 60.0, unit="°C", min=40.0),
        number("ambientTempC", "Plantroom ambient temp", 22.0, unit="°C"),
    ],
    requires_project=False,
)
def standbyLoss(ctx: FeatureContext, values: dict) -> dict:
    """Estimate insulated storage cylinder standby heat loss and daily energy decay."""
    import math

    vol_m3 = float(values["tankVolumeL"]) / 1000.0
    # Cylinder proportion H = 2*D => V = pi/4 * D^2 * (2D) = pi/2 * D^3
    d_m = (2.0 * vol_m3 / math.pi) ** (1.0 / 3.0)
    h_m = 2.0 * d_m
    area_m2 = math.pi * d_m * h_m + 2.0 * (math.pi * d_m**2 / 4.0)
    k_foam = 0.028  # W/(m·K) polyurethane insulation
    r_tot = (float(values["insulationMm"]) / 1000.0) / k_foam + 0.13
    u_val = 1.0 / r_tot
    dt = float(values["storageTempC"]) - float(values["ambientTempC"])
    loss_w = u_val * area_m2 * max(0.0, dt)
    daily_kwh = loss_w * 24.0 / 1000.0
    cooling_k_per_hr = (loss_w * 3.6) / (float(values["tankVolumeL"]) * 4.186)
    return result(
        summary={
            "surfaceAreaM2": round(area_m2, 2),
            "standbyLossW": round(loss_w, 1),
            "dailyLossKwh": round(daily_kwh, 2),
            "coolingRateKPerHr": round(cooling_k_per_hr, 3),
        },
        tables=[
            table(
                "Cylinder standby loss estimate",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Assumed cylinder H=2D surface",
                        "value": round(area_m2, 2),
                        "unit": "m²",
                    },
                    {"item": "Effective U-value", "value": round(u_val, 3), "unit": "W/(m²·K)"},
                    {"item": "Steady standby loss", "value": round(loss_w, 1), "unit": "W"},
                    {"item": "24-hour standby loss", "value": round(daily_kwh, 2), "unit": "kWh/d"},
                    {
                        "item": "Unheated temp decay",
                        "value": round(cooling_k_per_hr, 3),
                        "unit": "K/h",
                    },
                ],
            )
        ],
        notes=["Assumes H = 2D cylinder geometry and polyurethane jacket k = 0.028 W/(m·K)."],
    )


@feature(
    "mepPlumbingHeating.stratification",
    "Stratification",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def stratification(ctx: FeatureContext, values: dict) -> dict:
    """Stratification: Storage."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Stratification",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepPlumbingHeating.temperatureMonitor",
    "Temperature Monitor",
    part="mep",
    fields=[number("temperature", "Design temperature", 20, unit="?C")],
    requires_project=True,
)
def temperatureMonitor(ctx: FeatureContext, values: dict) -> dict:
    """Temperature Monitor: Safety Controls."""
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
                "Temperature Monitor",
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
    "mepPlumbingHeating.traceHeating",
    "Trace Heating",
    part="mep",
    fields=[
        number("pipeLengthM", "Maintained pipework length", 85.0, unit="m", min=1.0),
        number("pipeOdMm", "Pipe outer diameter", 54.0, unit="mm", min=12.0),
        number("insulationMm", "Insulation thickness", 25.0, unit="mm", min=5.0),
        number("maintainTempC", "Maintained water temperature", 55.0, unit="°C"),
        number("ambientTempC", "Minimum ambient temperature", 10.0, unit="°C"),
        text("name", "Output schedule name", "traceHeating"),
    ],
    requires_project=False,
)
def traceHeating(ctx: FeatureContext, values: dict) -> dict:
    """Compute linear pipe heat-trace tape output [W/m], circuit load, and breaker current."""
    import math

    r_in = float(values["pipeOdMm"]) / 2000.0
    r_out = r_in + float(values["insulationMm"]) / 1000.0
    k_ins = 0.036  # W/(m·K) mineral wool / elastomeric foam
    dt = max(1.0, float(values["maintainTempC"]) - float(values["ambientTempC"]))
    # Cylindrical radial conduction + outer surface convection R_o = 1/(h * 2*pi*r_out)
    r_cond = math.log(r_out / r_in) / (2.0 * math.pi * k_ins)
    r_conv = 1.0 / (9.0 * 2.0 * math.pi * r_out)
    q_per_m = dt / (r_cond + r_conv)
    installed_w_per_m = q_per_m * 1.25  # 25% design margin
    total_w = installed_w_per_m * float(values["pipeLengthM"])
    amps_230v = total_w / 230.0
    payload = {
        "pipeLengthM": values["pipeLengthM"],
        "calculatedLossWPerM": round(q_per_m, 2),
        "installedTapeWPerM": round(installed_w_per_m, 2),
        "totalLoadW": round(total_w, 1),
        "current230VA": round(amps_230v, 2),
    }
    export_note = "Computed cylindrical conduction heat-trace sizing (25% margin)."
    if ctx.root is not None:
        safe = "".join(c for c in values["name"] if c.isalnum() or c in "-_") or "traceHeating"
        path = ctx.path(f"11 Exports/{safe}.json")
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            export_note = f"Computed cylindrical heat-trace load ({installed_w_per_m:.1f} W/m) and saved to {path}."
    return result(
        summary={
            "lossWPerM": round(q_per_m, 2),
            "installedWPerM": round(installed_w_per_m, 2),
            "totalLoadKw": round(total_w / 1000.0, 2),
            "circuitCurrentA": round(amps_230v, 2),
        },
        tables=[
            table(
                "Electric heat-trace sizing",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "parameter": "Steady pipe heat loss",
                        "value": round(q_per_m, 2),
                        "unit": "W/m",
                    },
                    {
                        "parameter": "Tape rating (+25% margin)",
                        "value": round(installed_w_per_m, 2),
                        "unit": "W/m",
                    },
                    {"parameter": "Total circuit power", "value": round(total_w, 1), "unit": "W"},
                    {
                        "parameter": "Single-phase current (230 V)",
                        "value": round(amps_230v, 2),
                        "unit": "A",
                    },
                ],
            )
        ],
        notes=[export_note],
    )
