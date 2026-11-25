"""Dedicated mepCommissioning MEP feature registrations."""

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
    "mepCommissioning.airBalance",
    "Air Balance",
    part="mep",
    fields=[
        number("designFlowLps", "Design branch / diffuser airflow", 280.0, unit="L/s", min=5.0),
        number(
            "measuredFlowLps", "Pre-balance traverse measured airflow", 235.0, unit="L/s", min=1.0
        ),
        number("tolerancePct", "TAB allowable deviation", 10.0, unit="%", min=2.0, max=25.0),
    ],
    requires_project=False,
)
def airBalance(ctx: FeatureContext, values: dict) -> dict:
    """Check measured vs design airflow deviation and fan-speed proportional adjustment."""
    q_des = float(values["designFlowLps"])
    q_meas = float(values["measuredFlowLps"])
    dev_pct = ((q_meas - q_des) / q_des) * 100.0
    tol = float(values["tolerancePct"])
    ok = abs(dev_pct) <= tol
    speed_mult = q_des / q_meas
    power_mult = speed_mult**3
    return result(
        summary={
            "deviationPct": round(dev_pct, 1),
            "withinTolerance": ok,
            "fanSpeedMultiplier": round(speed_mult, 3),
            "fanPowerRatio": round(power_mult, 2),
        },
        tables=[
            table(
                "Testing & balancing airflow check",
                [("item", "Metric"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Design airflow", "value": q_des, "unit": "L/s"},
                    {"item": "Measured airflow", "value": q_meas, "unit": "L/s"},
                    {"item": "Balance deviation", "value": round(dev_pct, 1), "unit": "%"},
                    {
                        "item": "Required VFD speed factor",
                        "value": round(speed_mult, 3),
                        "unit": "x",
                    },
                    {
                        "item": "TAB acceptance (±" + f"{tol:g}%)",
                        "value": "PASS" if ok else "ADJUST DAMPER / FAN",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Proportional balancing assumes damper K-factors unchanged when scaling system fan RPM."
        ],
    )


@feature(
    "mepCommissioning.asBuilt",
    "As-Built",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def asBuilt(ctx: FeatureContext, values: dict) -> dict:
    """As-Built: Handover."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "As-Built",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCommissioning.closeoutReport",
    "Closeout Report",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def closeoutReport(ctx: FeatureContext, values: dict) -> dict:
    """Closeout Report: Verification."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCommissioning.closeoutReport",
        "title": "Closeout Report",
        "name": values["name"],
        "group": "Verification",
        "mep": raw,
    }
    path = ctx.path("11 Exports/closeoutReport.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Closeout Report",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCommissioning.commissioningSheets",
    "Commissioning Sheets",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def commissioningSheets(ctx: FeatureContext, values: dict) -> dict:
    """Commissioning Sheets: Handover."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCommissioning.commissioningSheets",
        "title": "Commissioning Sheets",
        "name": values["name"],
        "group": "Handover",
        "mep": raw,
    }
    path = ctx.path("11 Exports/commissioningSheets.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Commissioning Sheets",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCommissioning.controlsCheckout",
    "Controls Checkout",
    part="mep",
    fields=[
        number("spanRange", "BMS sensor measurement span (e.g. 50 °C or 500 Pa)", 50.0, min=1.0),
        number("referenceValue", "Calibrated reference instrument reading", 22.4),
        number("bmsReading", "BMS trended point value", 23.1),
        number(
            "maxErrorPctSpan",
            "Maximum allowable calibration error",
            2.0,
            unit="% span",
            min=0.2,
            max=10.0,
        ),
    ],
    requires_project=False,
)
def controlsCheckout(ctx: FeatureContext, values: dict) -> dict:
    """Check BMS sensor end-to-end calibration offset and percent-of-span accuracy."""
    err = float(values["bmsReading"]) - float(values["referenceValue"])
    pct_span = (abs(err) / float(values["spanRange"])) * 100.0
    ok = pct_span <= float(values["maxErrorPctSpan"])
    return result(
        summary={
            "offsetError": round(err, 3),
            "errorPctOfSpan": round(pct_span, 2),
            "recommendedZeroOffset": round(-err, 3),
            "calibrated": ok,
        },
        tables=[
            table(
                "BMS point-to-point calibration check",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Raw offset (BMS - Ref)",
                        "value": round(err, 3),
                        "unit": "eng. units",
                    },
                    {"item": "Percent of full span", "value": round(pct_span, 2), "unit": "%"},
                    {"item": "Recommended BMS bias", "value": round(-err, 3), "unit": "eng. units"},
                    {
                        "item": "Point verification",
                        "value": "PASS" if ok else "RECALIBRATE / BIAS",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "End-to-end point calibration compares field reference standard against BMS workstation readout."
        ],
    )


@feature(
    "mepCommissioning.defectList",
    "Defect List",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def defectList(ctx: FeatureContext, values: dict) -> dict:
    """Defect List: Documentation."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCommissioning.defectList",
        "title": "Defect List",
        "name": values["name"],
        "group": "Documentation",
        "mep": raw,
    }
    path = ctx.path("11 Exports/defectList.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Defect List",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCommissioning.energyVerify",
    "Energy Verify",
    part="mep",
    fields=[
        number("floorAreaM2", "Conditioned gross floor area", 5000.0, unit="m²", min=20.0),
        number(
            "baselineKwhPerYr",
            "Adjusted baseline annual MEP energy",
            620000.0,
            unit="kWh/yr",
            min=100.0,
        ),
        number(
            "measuredKwhPerYr",
            "Verified post-Cx metered energy",
            510000.0,
            unit="kWh/yr",
            min=100.0,
        ),
        number("tariffPerKwh", "Electricity unit tariff", 0.14, min=0.01),
    ],
    requires_project=False,
)
def energyVerify(ctx: FeatureContext, values: dict) -> dict:
    """Verify M&V Energy Use Intensity (EUI), annual energy saving %, and cost saving."""
    area = float(values["floorAreaM2"])
    base_kwh = float(values["baselineKwhPerYr"])
    meas_kwh = float(values["measuredKwhPerYr"])
    saved_kwh = base_kwh - meas_kwh
    saved_pct = (saved_kwh / base_kwh) * 100.0
    cost_saved = saved_kwh * float(values["tariffPerKwh"])
    return result(
        summary={
            "baselineEuiKwhM2": round(base_kwh / area, 1),
            "measuredEuiKwhM2": round(meas_kwh / area, 1),
            "energySavingPct": round(saved_pct, 1),
            "annualCostSaving": round(cost_saved, 0),
        },
        tables=[
            table(
                "Measurement & Verification energy summary",
                [("metric", "Metric"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "metric": "Adjusted baseline EUI",
                        "value": round(base_kwh / area, 1),
                        "unit": "kWh/(m²·yr)",
                    },
                    {
                        "metric": "Metered post-Cx EUI",
                        "value": round(meas_kwh / area, 1),
                        "unit": "kWh/(m²·yr)",
                    },
                    {
                        "metric": "Avoided annual energy",
                        "value": round(saved_kwh, 0),
                        "unit": "kWh/yr",
                    },
                    {"metric": "Net saving percentage", "value": round(saved_pct, 1), "unit": "%"},
                    {
                        "metric": "Annual utility cost saving",
                        "value": round(cost_saved, 0),
                        "unit": "currency/yr",
                    },
                ],
            )
        ],
        notes=[
            "Savings = Adjusted Baseline Energy - Metered Energy normalized over conditioned GFA."
        ],
    )


@feature(
    "mepCommissioning.equipmentStartup",
    "Equipment Startup",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def equipmentStartup(ctx: FeatureContext, values: dict) -> dict:
    """Equipment Startup: Start-Up."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Equipment Startup",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCommissioning.flushChlorinate",
    "Flush & Chlorinate",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def flushChlorinate(ctx: FeatureContext, values: dict) -> dict:
    """Flush & Chlorinate: Testing."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Flush & Chlorinate",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCommissioning.handoverPack",
    "Handover Pack",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def handoverPack(ctx: FeatureContext, values: dict) -> dict:
    """Handover Pack: Documentation."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCommissioning.handoverPack",
        "title": "Handover Pack",
        "name": values["name"],
        "group": "Documentation",
        "mep": raw,
    }
    path = ctx.path("11 Exports/handoverPack.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Handover Pack",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCommissioning.oMManual",
    "O&M Manual",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def oMManual(ctx: FeatureContext, values: dict) -> dict:
    """O&M Manual: Handover."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCommissioning.oMManual",
        "title": "O&M Manual",
        "name": values["name"],
        "group": "Handover",
        "mep": raw,
    }
    path = ctx.path("11 Exports/oMManual.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "O&M Manual",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCommissioning.performanceVerify",
    "Performance Verify",
    part="mep",
    fields=[
        number("ratedCoolingKw", "Submittal design cooling duty", 320.0, unit="kW", min=1.0),
        number("chwFlowLps", "Measured chilled-water flow", 14.8, unit="L/s", min=0.5),
        number("chwDeltaTK", "Measured CHW delta-T", 5.0, unit="K", min=1.0),
        number("measuredInputKw", "Measured electrical input power", 72.0, unit="kW", min=0.5),
    ],
    requires_project=False,
)
def performanceVerify(ctx: FeatureContext, values: dict) -> dict:
    """Verify field cooling plant functional duty, COP, and capacity shortfall vs submittal."""
    meas_duty_kw = float(values["chwFlowLps"]) * 4.186 * float(values["chwDeltaTK"])
    rated = float(values["ratedCoolingKw"])
    pct_rated = (meas_duty_kw / rated) * 100.0
    cop = meas_duty_kw / float(values["measuredInputKw"])
    ok = pct_rated >= 95.0
    return result(
        summary={
            "measuredCoolingKw": round(meas_duty_kw, 1),
            "capacityRatioPct": round(pct_rated, 1),
            "fieldCop": round(cop, 2),
            "compliant": ok,
        },
        tables=[
            table(
                "Functional performance test (FPT) verification",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Field thermal capacity Q = m·cp·ΔT",
                        "value": round(meas_duty_kw, 1),
                        "unit": "kW",
                    },
                    {
                        "item": "% of design submittal duty",
                        "value": round(pct_rated, 1),
                        "unit": "%",
                    },
                    {"item": "Field operating COP", "value": round(cop, 2), "unit": "kW/kW"},
                    {
                        "item": "Acceptance (>= 95% rated)",
                        "value": "PASS" if ok else "INVESTIGATE FOULING / FLOW",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Computes water-side capacity Q = Flow [L/s] * 4.186 * dT and field COP = Q / Power_in."
        ],
    )


@feature(
    "mepCommissioning.preStartupChecklist",
    "Pre-Startup Checklist",
    part="mep",
    fields=[
        text("reviewer", "Commissioning lead", "Cx Authority"),
        text("name", "Checklist export prefix", "preStartupChecklist"),
    ],
    requires_project=True,
)
def preStartupChecklist(ctx: FeatureContext, values: dict) -> dict:
    """Generate a discipline-specific pre-startup checklist from active 07 MEP/mep.json systems."""
    if ctx.root is None:
        raise FeatureInputError(
            "Open a project with 07 MEP/mep.json before generating pre-startup checks."
        )
    raw = ctx.raw("mep")
    if not isinstance(raw, dict):
        raise FeatureInputError("Missing 07 MEP/mep.json in project.")
    items: list[dict] = []
    plumb = raw.get("plumbing") or {}
    hvac = raw.get("hvac") or {}
    elec = raw.get("electrical") or {}
    fire = raw.get("fire") or {}
    if plumb.get("tanks") or plumb.get("risers"):
        items.append(
            {
                "discipline": "Plumbing",
                "item": "Hydrostatic pressure test & disinfection flushing complete",
                "scopeCount": len(plumb.get("risers") or []) + len(plumb.get("tanks") or []),
                "ready": False,
            }
        )
    if hvac.get("plant") or hvac.get("ducts"):
        items.append(
            {
                "discipline": "HVAC",
                "item": "Duct leakage test, filter installation & rotational check",
                "scopeCount": len(hvac.get("plant") or []) + len(hvac.get("ducts") or []),
                "ready": False,
            }
        )
    if elec.get("equipment") or elec.get("risers"):
        items.append(
            {
                "discipline": "Electrical",
                "item": "Insulation resistance (Megger), torque & earth loop continuity",
                "scopeCount": len(elec.get("equipment") or []) + len(elec.get("risers") or []),
                "ready": False,
            }
        )
    if fire.get("stories") or fire:
        items.append(
            {
                "discipline": "Fire",
                "item": "Sprinkler/hydrant hydrostatic test & alarm cause-and-effect dry run",
                "scopeCount": len(fire.get("stories") or []),
                "ready": False,
            }
        )
    if not items:
        raise FeatureInputError(
            "07 MEP/mep.json contains no systems to build a pre-startup checklist."
        )
    safe = "".join(c for c in values["name"] if c.isalnum() or c in "-_") or "preStartupChecklist"
    path = ctx.path(f"11 Exports/{safe}.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"reviewer": values["reviewer"].strip(), "checklist": items}, indent=2) + "\n",
        encoding="utf-8",
    )
    return result(
        summary={
            "disciplines": len(items),
            "exportPath": str(path),
            "reviewer": values["reviewer"].strip(),
        },
        tables=[
            table(
                "MEP pre-startup commissioning checklist",
                [
                    ("discipline", "Discipline"),
                    ("scopeCount", "Model Items"),
                    ("item", "Pre-Startup Verification"),
                ],
                items,
            )
        ],
        notes=[
            f"Tailored {len(items)} discipline pre-startup item(s) from 07 MEP/mep.json and exported to {path}."
        ],
    )


@feature(
    "mepCommissioning.pressureTests",
    "Pressure Tests",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def pressureTests(ctx: FeatureContext, values: dict) -> dict:
    """Pressure Tests: Testing."""
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
                "Pressure Tests",
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
    "mepCommissioning.punchList",
    "Punch List",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def punchList(ctx: FeatureContext, values: dict) -> dict:
    """Punch List: QA."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCommissioning.punchList",
        "title": "Punch List",
        "name": values["name"],
        "group": "QA",
        "mep": raw,
    }
    path = ctx.path("11 Exports/punchList.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Punch List",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCommissioning.seasonalTest",
    "Seasonal Test",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def seasonalTest(ctx: FeatureContext, values: dict) -> dict:
    """Seasonal Test: Verification."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Seasonal Test",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCommissioning.sensorCalibration",
    "Sensor Calibration",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def sensorCalibration(ctx: FeatureContext, values: dict) -> dict:
    """Sensor Calibration: Start-Up."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Sensor Calibration",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCommissioning.signOff",
    "Sign-Off",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def signOff(ctx: FeatureContext, values: dict) -> dict:
    """Sign-Off: QA."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Sign-Off",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCommissioning.testSheets",
    "Test Sheets",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def testSheets(ctx: FeatureContext, values: dict) -> dict:
    """Test Sheets: Documentation."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCommissioning.testSheets",
        "title": "Test Sheets",
        "name": values["name"],
        "group": "Documentation",
        "mep": raw,
    }
    path = ctx.path("11 Exports/testSheets.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Test Sheets",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCommissioning.trainingRecords",
    "Training Records",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def trainingRecords(ctx: FeatureContext, values: dict) -> dict:
    """Training Records: Documentation."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCommissioning.trainingRecords",
        "title": "Training Records",
        "name": values["name"],
        "group": "Documentation",
        "mep": raw,
    }
    path = ctx.path("11 Exports/trainingRecords.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Training Records",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCommissioning.trendReview",
    "Trend Review",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def trendReview(ctx: FeatureContext, values: dict) -> dict:
    """Trend Review: Verification."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Trend Review",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCommissioning.valveTagging",
    "Valve Tagging",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def valveTagging(ctx: FeatureContext, values: dict) -> dict:
    """Valve Tagging: Start-Up."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Valve Tagging",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepCommissioning.warrantyData",
    "Warranty Data",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def warrantyData(ctx: FeatureContext, values: dict) -> dict:
    """Warranty Data: QA."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCommissioning.warrantyData",
        "title": "Warranty Data",
        "name": values["name"],
        "group": "QA",
        "mep": raw,
    }
    path = ctx.path("11 Exports/warrantyData.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Warranty Data",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepCommissioning.witnessRecords",
    "Witness Records",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def witnessRecords(ctx: FeatureContext, values: dict) -> dict:
    """Witness Records: Documentation."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepCommissioning.witnessRecords",
        "title": "Witness Records",
        "name": values["name"],
        "group": "Documentation",
        "mep": raw,
    }
    path = ctx.path("11 Exports/witnessRecords.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Witness Records",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )
