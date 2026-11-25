"""Dedicated mepSmoke MEP feature registrations."""

from __future__ import annotations

from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    table,
    text,
)


@feature(
    "mepSmoke.airBalanceSmoke",
    "Air Balance Smoke",
    part="mep",
    fields=[
        number(
            "pressurisedFloorCount",
            "Pressurised stairwell doors closed + 1 open",
            10,
            min=1,
            max=80,
        ),
        number(
            "closedDoorGapAreaM2", "Leakage gap area per closed door", 0.02, unit="m²", min=0.005
        ),
        number("openDoorsCount", "Assumed simultaneously open egress doors", 1, min=0, max=4),
        number("openDoorAreaM2", "Single open door leaf area", 1.8, unit="m²", min=1.0),
        number(
            "targetPressurePa", "Design stairwell overpressure", 50.0, unit="Pa", min=12.5, max=80.0
        ),
    ],
    requires_project=False,
)
def airBalanceSmoke(ctx: FeatureContext, values: dict) -> dict:
    """Compute stairwell smoke-control pressurisation supply fan airflow (closed + open doors)."""
    import math

    dp = float(values["targetPressurePa"])
    # Orifice flow Q = Cd * A * sqrt(2 * dP / rho), Cd = 0.65, rho = 1.2
    v_crack = 0.65 * math.sqrt(2.0 * dp / 1.2)
    q_closed = int(values["pressurisedFloorCount"]) * float(values["closedDoorGapAreaM2"]) * v_crack
    # Open door velocity Criterion (min 1.0 m/s across open door)
    q_open = int(values["openDoorsCount"]) * float(values["openDoorAreaM2"]) * 1.0
    q_total = (q_closed + q_open) * 1.15  # 15% duct & shaft leakage margin
    return result(
        summary={
            "closedDoorLeakageM3s": round(q_closed, 2),
            "openDoorAirflowM3s": round(q_open, 2),
            "totalFanSupplyM3s": round(q_total, 2),
            "totalFanSupplyLps": round(q_total * 1000.0, 0),
        },
        tables=[
            table(
                "Stairwell smoke pressurisation airflow balance",
                [
                    ("component", "Flow Path"),
                    ("flowM3s", "Flow", "m³/s"),
                    ("flowLps", "Flow", "L/s"),
                ],
                [
                    {
                        "component": "Closed door crack leakage",
                        "flowM3s": round(q_closed, 2),
                        "flowLps": round(q_closed * 1000, 0),
                    },
                    {
                        "component": "Open door purge velocity (>= 1.0 m/s)",
                        "flowM3s": round(q_open, 2),
                        "flowLps": round(q_open * 1000, 0),
                    },
                    {
                        "component": "Design supply + 15% duct margin",
                        "flowM3s": round(q_total, 2),
                        "flowLps": round(q_total * 1000, 0),
                    },
                ],
            )
        ],
        notes=[
            "Orifice equation Cd=0.65 across closed door perimeter gaps plus 1.0 m/s open-door purge velocity."
        ],
    )


@feature(
    "mepSmoke.cfdSmokeRun",
    "CFD Smoke Run",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def cfdSmokeRun(ctx: FeatureContext, values: dict) -> dict:
    """CFD Smoke Run: Analysis."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "CFD Smoke Run",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSmoke.doorForceCheck",
    "Door Force Check",
    part="mep",
    fields=[
        number("doorWidthM", "Door leaf width W", 0.90, unit="m", min=0.6, max=1.5),
        number("doorHeightM", "Door leaf height H", 2.10, unit="m", min=1.8, max=2.8),
        number("closerForceN", "Door closer latch resistance F_dc", 45.0, unit="N", min=10.0),
        number(
            "pressureDiffPa", "Maximum stairwell pressure difference ΔP", 50.0, unit="Pa", min=5.0
        ),
        number("maxAllowedForceN", "Maximum handle opening force limit", 133.0, unit="N", min=50.0),
    ],
    requires_project=False,
)
def doorForceCheck(ctx: FeatureContext, values: dict) -> dict:
    """Calculate stairwell egress door handle opening force under smoke pressurisation."""
    w = float(values["doorWidthM"])
    h = float(values["doorHeightM"])
    d_latch = 0.075  # m from stile edge to knob/bar
    dp = float(values["pressureDiffPa"])
    area = w * h
    f_air = (dp * area * w) / (2.0 * (w - d_latch))
    f_total = float(values["closerForceN"]) + f_air
    max_dp_allowed = (
        (float(values["maxAllowedForceN"]) - float(values["closerForceN"]))
        * 2.0
        * (w - d_latch)
        / (area * w)
    )
    ok = f_total <= float(values["maxAllowedForceN"])
    return result(
        summary={
            "totalOpeningForceN": round(f_total, 1),
            "airPressureForceN": round(f_air, 1),
            "maxAllowableDeltaPPa": round(max(0.0, max_dp_allowed), 1),
            "compliant": ok,
        },
        tables=[
            table(
                "Pressurised egress door opening force",
                [("item", "Component"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Door closer force F_dc",
                        "value": values["closerForceN"],
                        "unit": "N",
                    },
                    {"item": "Differential pressure force", "value": round(f_air, 1), "unit": "N"},
                    {
                        "item": "Total force at panic hardware",
                        "value": round(f_total, 1),
                        "unit": "N",
                    },
                    {
                        "item": "Max ΔP before exceeding limit",
                        "value": round(max(0.0, max_dp_allowed), 1),
                        "unit": "Pa",
                    },
                    {
                        "item": "Egress door status",
                        "value": "PASS" if ok else "ADD RELIEF DAMPER",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Moment equilibrium F = F_dc + (dP * A * W) / (2 * (W - d)); verify barometric relief setpoint."
        ],
    )


@feature(
    "mepSmoke.ductSmokeDetector",
    "Duct Smoke Detector",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def ductSmokeDetector(ctx: FeatureContext, values: dict) -> dict:
    """Duct Smoke Detector: Ventilation."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Duct Smoke Detector",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSmoke.egressWidthCheck",
    "Egress Width Check",
    part="mep",
    fields=[
        number("occupantLoad", "Floor or stairwell design occupant load", 180, min=1),
        number(
            "widthPerPersonMm", "Stair width factor per occupant", 7.6, unit="mm/person", min=4.0
        ),
        number(
            "providedClearMm",
            "Provided clear exit stair / door width",
            1500.0,
            unit="mm",
            min=600.0,
        ),
    ],
    requires_project=False,
)
def egressWidthCheck(ctx: FeatureContext, values: dict) -> dict:
    """Check clear smoke-protected egress width against occupant capacity and minimum width."""
    req_mm = max(1100.0, int(values["occupantLoad"]) * float(values["widthPerPersonMm"]))
    prov_mm = float(values["providedClearMm"])
    cap_persons = int(prov_mm / float(values["widthPerPersonMm"]))
    ok = prov_mm >= req_mm
    return result(
        summary={
            "requiredClearWidthMm": round(req_mm, 0),
            "providedWidthMm": prov_mm,
            "egressCapacityPersons": cap_persons,
            "compliant": ok,
        },
        tables=[
            table(
                "Egress clear width check",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Design occupant load",
                        "value": values["occupantLoad"],
                        "unit": "persons",
                    },
                    {"item": "Required minimum width", "value": round(req_mm, 0), "unit": "mm"},
                    {"item": "Provided clear width", "value": prov_mm, "unit": "mm"},
                    {"item": "Clear width capacity", "value": cap_persons, "unit": "persons"},
                    {"item": "Status", "value": "PASS" if ok else "WIDEN EXIT", "unit": "-"},
                ],
            )
        ],
        notes=["Enforces 1100 mm floor minimum clear width plus occupant-scaled egress demand."],
    )


@feature(
    "mepSmoke.evacuationTime",
    "Evacuation Time",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def evacuationTime(ctx: FeatureContext, values: dict) -> dict:
    """Evacuation Time: Analysis."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Evacuation Time",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSmoke.exhaustFans",
    "Exhaust Fans",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def exhaustFans(ctx: FeatureContext, values: dict) -> dict:
    """Exhaust Fans: Ventilation."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Exhaust Fans",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSmoke.exitRoutes",
    "Exit Routes",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def exitRoutes(ctx: FeatureContext, values: dict) -> dict:
    """Exit Routes: Egress."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Exit Routes",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSmoke.extractionRate",
    "Extraction Rate",
    part="mep",
    fields=[
        number(
            "heatReleaseKw", "Design fire convective heat release Qc", 3500.0, unit="kW", min=200.0
        ),
        number(
            "clearHeightM", "Clear smoke-free height Z above fuel", 6.0, unit="m", min=2.0, max=40.0
        ),
        number("smokeTempC", "Upper smoke layer temperature Ts", 85.0, unit="°C", min=30.0),
    ],
    requires_project=False,
)
def extractionRate(ctx: FeatureContext, values: dict) -> dict:
    """Calculate axisymmetric plume mass flow and volumetric mechanical smoke extraction rate."""
    qc = float(values["heatReleaseKw"])
    z = float(values["clearHeightM"])
    # Heskestad / NFPA 92 axisymmetric plume (for z > flame limit z_l): m_p = 0.071 * Qc^(1/3) * z^(5/3) + 0.0018 * Qc
    m_p_kgs = 0.071 * (qc ** (1.0 / 3.0)) * (z ** (5.0 / 3.0)) + 0.0018 * qc
    rho_s = 1.2 * (293.15 / (float(values["smokeTempC"]) + 273.15))
    vol_m3s = m_p_kgs / rho_s
    return result(
        summary={
            "plumeMassRateKgPerS": round(m_p_kgs, 2),
            "smokeDensityKgPerM3": round(rho_s, 3),
            "extractionRateM3s": round(vol_m3s, 2),
            "extractionRateLps": round(vol_m3s * 1000.0, 0),
        },
        tables=[
            table(
                "Mechanical smoke exhaust rate",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"parameter": "Convective HRR Qc", "value": qc, "unit": "kW"},
                    {"parameter": "Clear smoke interface height Z", "value": z, "unit": "m"},
                    {
                        "parameter": "Entrained plume mass flow",
                        "value": round(m_p_kgs, 2),
                        "unit": "kg/s",
                    },
                    {"parameter": "Hot smoke density", "value": round(rho_s, 3), "unit": "kg/m³"},
                    {
                        "parameter": "Required exhaust flow rate",
                        "value": round(vol_m3s, 2),
                        "unit": "m³/s",
                    },
                ],
            )
        ],
        notes=[
            "Axi-symmetric plume entrainment m_p = 0.071*Qc^(1/3)*Z^(5/3) + 0.0018*Qc converted at hot layer density."
        ],
    )


@feature(
    "mepSmoke.leakagePath",
    "Leakage Path",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def leakagePath(ctx: FeatureContext, values: dict) -> dict:
    """Leakage Path: Stairwells."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Leakage Path",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSmoke.lobbyPressure",
    "Lobby Pressure",
    part="mep",
    fields=[number("pressure", "Design pressure", 100, unit="kPa", min=0)],
    requires_project=True,
)
def lobbyPressure(ctx: FeatureContext, values: dict) -> dict:
    """Lobby Pressure: Stairwells."""
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
                "Lobby Pressure",
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
    "mepSmoke.makeUpAir",
    "Make-Up Air",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def makeUpAir(ctx: FeatureContext, values: dict) -> dict:
    """Make-Up Air: Ventilation."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Make-Up Air",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSmoke.pressurisation",
    "Pressurisation",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def pressurisation(ctx: FeatureContext, values: dict) -> dict:
    """Pressurisation: Smoke Control."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Pressurisation",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSmoke.refugeAreas",
    "Refuge Areas",
    part="mep",
    fields=[number("area", "Area", 100, unit="m?", min=0)],
    requires_project=True,
)
def refugeAreas(ctx: FeatureContext, values: dict) -> dict:
    """Refuge Areas: Egress."""
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
                "Refuge Areas",
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
    "mepSmoke.reliefDamper",
    "Relief Damper",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def reliefDamper(ctx: FeatureContext, values: dict) -> dict:
    """Relief Damper: Stairwells."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Relief Damper",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSmoke.scenarioSetup",
    "Scenario Setup",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def scenarioSetup(ctx: FeatureContext, values: dict) -> dict:
    """Scenario Setup: Simulation."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Scenario Setup",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSmoke.smokeLayerHeight",
    "Smoke Layer Height",
    part="mep",
    fields=[number("dimension", "Dimension", 1000, unit="mm", min=1)],
    requires_project=True,
)
def smokeLayerHeight(ctx: FeatureContext, values: dict) -> dict:
    """Smoke Layer Height: Simulation."""
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
                "Smoke Layer Height",
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
    "mepSmoke.smokeReservoirs",
    "Smoke Reservoirs",
    part="mep",
    fields=[
        number("zoneAreaM2", "Compartment smoke reservoir area", 2200.0, unit="m²", min=50.0),
        number("maxSideM", "Longest reservoir dimension", 52.0, unit="m", min=5.0),
        number("layerDepthM", "Ceiling smoke screen drop depth d", 1.8, unit="m", min=0.5),
    ],
    requires_project=False,
)
def smokeReservoirs(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate smoke reservoir zoning area (<= 2600 m² mechanical), aspect length, and storage volume."""
    area = float(values["zoneAreaM2"])
    length = float(values["maxSideM"])
    depth = float(values["layerDepthM"])
    vol_m3 = area * depth
    area_ok = area <= 2600.0
    len_ok = length <= 60.0
    sub_zones = max(1, int(-(-area // 2600.0)))
    return result(
        summary={
            "reservoirVolumeM3": round(vol_m3, 0),
            "recommendedSubZones": sub_zones,
            "areaOk": area_ok,
            "lengthOk": len_ok,
        },
        tables=[
            table(
                "Smoke reservoir zoning check",
                [("criterion", "Check Criterion"), ("value", "Value"), ("status", "Status")],
                [
                    {
                        "criterion": "Reservoir plan area (<= 2600 m²)",
                        "value": f"{area:g} m²",
                        "status": "PASS" if area_ok else f"SPLIT INTO {sub_zones}",
                    },
                    {
                        "criterion": "Maximum edge length (<= 60 m)",
                        "value": f"{length:g} m",
                        "status": "PASS" if len_ok else "EXCEEDS 60 m",
                    },
                    {
                        "criterion": "Smoke storage volume",
                        "value": f"{vol_m3:,.0f} m³",
                        "status": f"d={depth:g} m",
                    },
                ],
            )
        ],
        notes=[
            "Smoke curtains sub-divide large malls/atriums so plume buoyancy remains well-stratified."
        ],
    )


@feature(
    "mepSmoke.smokeVents",
    "Smoke Vents",
    part="mep",
    fields=[
        number("plumeMassKgPerS", "Smoke mass flow rate M_s", 18.0, unit="kg/s", min=0.5),
        number("smokeLayerDepthM", "Hot smoke layer buoyancy depth d", 1.6, unit="m", min=0.4),
        number("smokeTempC", "Mean smoke layer temperature", 90.0, unit="°C", min=35.0),
        number("ambientTempC", "Ambient outside air temperature", 25.0, unit="°C"),
        number("dischargeCoeff", "Vent aerodynamic Cv factor", 0.60, min=0.4, max=0.8),
    ],
    requires_project=False,
)
def smokeVents(ctx: FeatureContext, values: dict) -> dict:
    """Size natural buoyancy smoke ventilator free geometric area via BRE/EN-style stack formula."""
    import math

    m_s = float(values["plumeMassKgPerS"])
    d = float(values["smokeLayerDepthM"])
    t_s = float(values["smokeTempC"]) + 273.15
    t_0 = float(values["ambientTempC"]) + 273.15
    dt = max(1.0, t_s - t_0)
    rho_0 = 1.2 * 293.15 / t_0
    cv = float(values["dischargeCoeff"])
    # Aerodynamic free area Aa = M_s / (rho_0 * sqrt(2 * g * d * dT * T_0 / T_s^2)) roughly
    denom = rho_0 * math.sqrt(2.0 * 9.81 * d * dt * t_0 / (t_s**2))
    aa_m2 = m_s / denom
    geom_area_m2 = aa_m2 / cv
    return result(
        summary={
            "aerodynamicAreaM2": round(aa_m2, 2),
            "geometricVentAreaM2": round(geom_area_m2, 2),
        },
        tables=[
            table(
                "Natural smoke ventilator sizing",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Smoke mass rate M_s", "value": m_s, "unit": "kg/s"},
                    {
                        "item": "Buoyancy depth d / ΔT",
                        "value": f"{d:g} m / {dt:.0f} K",
                        "unit": "-",
                    },
                    {
                        "item": "Required aerodynamic area Aa",
                        "value": round(aa_m2, 2),
                        "unit": "m²",
                    },
                    {
                        "item": "Required geometric area (Aa/Cv)",
                        "value": round(geom_area_m2, 2),
                        "unit": "m²",
                    },
                ],
            )
        ],
        notes=[
            "Provide low-level replacement makeup air >= 1.5x total exhaust aerodynamic area to limit plugholing."
        ],
    )


@feature(
    "mepSmoke.stairPressurisation",
    "Stair Pressurisation",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def stairPressurisation(ctx: FeatureContext, values: dict) -> dict:
    """Stair Pressurisation: Stairwells."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Stair Pressurisation",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepSmoke.temperatureSlice",
    "Temperature Slice",
    part="mep",
    fields=[number("temperature", "Design temperature", 20, unit="?C")],
    requires_project=True,
)
def temperatureSlice(ctx: FeatureContext, values: dict) -> dict:
    """Temperature Slice: Simulation."""
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
                "Temperature Slice",
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
    "mepSmoke.tenability",
    "Tenability",
    part="mep",
    fields=[
        number(
            "opticalDensityPerM", "Smoke optical extinction coeff alpha", 0.18, unit="/m", min=0.01
        ),
        number("airTempC", "Occupant-head gas temperature (2.0 m)", 42.0, unit="°C", min=15.0),
        number(
            "radiationKwPerM2", "Radiant heat flux from upper layer", 1.2, unit="kW/m²", min=0.0
        ),
    ],
    requires_project=False,
)
def tenability(ctx: FeatureContext, values: dict) -> dict:
    """Verify ASET egress tenability limits for visibility (>= 10 m), gas temp (<= 60 °C), and radiation (<= 2.5 kW/m²)."""
    # Jin's visibility law: S = K / extinction_coeff, K = 3 for illuminated exit signs
    vis_m = 3.0 / float(values["opticalDensityPerM"])
    temp_c = float(values["airTempC"])
    rad = float(values["radiationKwPerM2"])
    vis_ok = vis_m >= 10.0
    temp_ok = temp_c <= 60.0
    rad_ok = rad <= 2.5
    overall = vis_ok and temp_ok and rad_ok
    return result(
        summary={
            "visibilityM": round(vis_m, 1),
            "temperatureC": temp_c,
            "radiationKwPerM2": rad,
            "tenable": overall,
        },
        tables=[
            table(
                "Life-safety tenability criteria",
                [
                    ("criterion", "Criterion"),
                    ("computed", "Value"),
                    ("limit", "Limit"),
                    ("status", "Status"),
                ],
                [
                    {
                        "criterion": "Illuminated exit visibility",
                        "computed": f"{vis_m:.1f} m",
                        "limit": ">= 10.0 m",
                        "status": "PASS" if vis_ok else "FAIL",
                    },
                    {
                        "criterion": "Breathing zone temperature",
                        "computed": f"{temp_c:.1f} °C",
                        "limit": "<= 60.0 °C",
                        "status": "PASS" if temp_ok else "FAIL",
                    },
                    {
                        "criterion": "Downward radiant flux",
                        "computed": f"{rad:.2f} kW/m²",
                        "limit": "<= 2.5 kW/m²",
                        "status": "PASS" if rad_ok else "FAIL",
                    },
                ],
            )
        ],
        notes=[
            "Uses Jin's relation S = 3 / alpha for light-reflecting signage in smoky corridors."
        ],
    )


@feature(
    "mepSmoke.visibilityDistance",
    "Visibility Distance",
    part="mep",
    fields=[number("dimension", "Dimension", 1000, unit="mm", min=1)],
    requires_project=True,
)
def visibilityDistance(ctx: FeatureContext, values: dict) -> dict:
    """Visibility Distance: Simulation."""
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
                "Visibility Distance",
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
