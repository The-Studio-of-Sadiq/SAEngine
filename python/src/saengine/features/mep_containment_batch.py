"""Dedicated mepContainment MEP feature registrations."""

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
    "mepContainment.bendRadiusCheck",
    "Bend Radius Check",
    part="mep",
    fields=[number("dimension", "Dimension", 1000, unit="mm", min=1)],
    requires_project=True,
)
def bendRadiusCheck(ctx: FeatureContext, values: dict) -> dict:
    """Bend Radius Check: Route Checks."""
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
                "Bend Radius Check",
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
    "mepContainment.bondingJumper",
    "Bonding Jumper",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def bondingJumper(ctx: FeatureContext, values: dict) -> dict:
    """Bonding Jumper: Earthing."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Bonding Jumper",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepContainment.cableLengths",
    "Cable Lengths",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def cableLengths(ctx: FeatureContext, values: dict) -> dict:
    """Cable Lengths: Schedules."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Cable Lengths",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepContainment.conduitBends",
    "Conduit Bends",
    part="mep",
    fields=[
        number("bends90", "Number of 90° bends", 2, min=0, max=10),
        number("bends45", "Number of 45° bends / offsets", 2, min=0, max=12),
        number("frictionCoeff", "Cable jacket friction coefficient mu", 0.35, min=0.1, max=0.8),
        number("straightTensionKn", "Straight-run pulling tension", 0.8, unit="kN", min=0.05),
    ],
    requires_project=False,
)
def conduitBends(ctx: FeatureContext, values: dict) -> dict:
    """Verify cumulative conduit bend angle (<= 360°) and capstan pulling tension factor."""
    import math

    total_deg = int(values["bends90"]) * 90 + int(values["bends45"]) * 45
    total_rad = math.radians(total_deg)
    capstan_mult = math.exp(float(values["frictionCoeff"]) * total_rad)
    end_tension_kn = float(values["straightTensionKn"]) * capstan_mult
    ok = total_deg <= 360
    return result(
        summary={
            "totalAngleDeg": total_deg,
            "within360DegLimit": ok,
            "capstanMultiplier": round(capstan_mult, 2),
            "estimatedPullTensionKn": round(end_tension_kn, 2),
        },
        tables=[
            table(
                "Conduit bend & pulling check",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Cumulative bend angle", "value": total_deg, "unit": "deg"},
                    {
                        "item": "Pull-box limit (360°)",
                        "value": "PASS" if ok else "ADD PULL BOX",
                        "unit": "-",
                    },
                    {
                        "item": "Capstan multiplier exp(μθ)",
                        "value": round(capstan_mult, 2),
                        "unit": "-",
                    },
                    {
                        "item": "Estimated pull tension",
                        "value": round(end_tension_kn, 2),
                        "unit": "kN",
                    },
                ],
            )
        ],
        notes=[
            "Capstan friction T_out = T_in * exp(mu * theta); add intermediate draw-in box above 360 deg."
        ],
    )


@feature(
    "mepContainment.conduitFill",
    "Conduit Fill",
    part="mep",
    fields=[
        number("conduitIdMm", "Conduit internal diameter", 25.0, unit="mm", min=12.0),
        number("cableCount", "Number of insulated conductors", 4, min=1, max=50),
        number("cableOdMm", "Single conductor outer diameter", 6.2, unit="mm", min=2.0),
    ],
    requires_project=False,
)
def conduitFill(ctx: FeatureContext, values: dict) -> dict:
    """Check conductor area fill ratio against standard 53%/31%/40% conduit fill limits."""
    import math

    n = int(values["cableCount"])
    limit_pct = 53.0 if n == 1 else (31.0 if n == 2 else 40.0)
    conduit_area = math.pi * (float(values["conduitIdMm"]) / 2.0) ** 2
    wires_area = n * math.pi * (float(values["cableOdMm"]) / 2.0) ** 2
    fill_pct = (wires_area / conduit_area) * 100.0
    ok = fill_pct <= limit_pct
    min_id = float(values["cableOdMm"]) * math.sqrt(n / (limit_pct / 100.0))
    return result(
        summary={
            "fillPercent": round(fill_pct, 1),
            "limitPercent": limit_pct,
            "compliant": ok,
            "minRequiredIdMm": round(min_id, 1),
        },
        tables=[
            table(
                "Conduit cross-section fill check",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Conduit internal area",
                        "value": round(conduit_area, 1),
                        "unit": "mm²",
                    },
                    {"item": "Conductors total area", "value": round(wires_area, 1), "unit": "mm²"},
                    {"item": "Fill percentage", "value": round(fill_pct, 1), "unit": "%"},
                    {"item": "Allowable fill limit", "value": limit_pct, "unit": "%"},
                    {"item": "Min internal bore needed", "value": round(min_id, 1), "unit": "mm"},
                ],
            )
        ],
        notes=["Limits: 53% (1 conductor), 31% (2 conductors), 40% (3 or more conductors)."],
    )


@feature(
    "mepContainment.containmentSchedule",
    "Containment Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def containmentSchedule(ctx: FeatureContext, values: dict) -> dict:
    """Containment Schedule: Schedules."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepContainment.containmentSchedule",
        "title": "Containment Schedule",
        "name": values["name"],
        "group": "Schedules",
        "mep": raw,
    }
    path = ctx.path("11 Exports/containmentSchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Containment Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepContainment.drawBusbar",
    "Draw Busbar",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def drawBusbar(ctx: FeatureContext, values: dict) -> dict:
    """Draw Busbar: Routing."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Draw Busbar",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepContainment.drawCableTray",
    "Draw Cable Tray",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def drawCableTray(ctx: FeatureContext, values: dict) -> dict:
    """Draw Cable Tray: Routing."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Draw Cable Tray",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepContainment.drawConduit",
    "Draw Conduit",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def drawConduit(ctx: FeatureContext, values: dict) -> dict:
    """Draw Conduit: Routing."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Draw Conduit",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepContainment.earthBar",
    "Earth Bar",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def earthBar(ctx: FeatureContext, values: dict) -> dict:
    """Earth Bar: Earthing."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Earth Bar",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepContainment.earthContinuity",
    "Earth Continuity",
    part="mep",
    fields=[
        number("faultCurrentKa", "Prospective earth fault current Ik1", 4.5, unit="kA", min=0.1),
        number("clearingTimeS", "Protective device disconnection time t", 0.4, unit="s", min=0.02),
        number("cpcAreaMm2", "Selected CPC / tray bonding area", 16.0, unit="mm²", min=1.5),
        number("runLengthM", "Protective conductor run length", 45.0, unit="m", min=1.0),
    ],
    requires_project=False,
)
def earthContinuity(ctx: FeatureContext, values: dict) -> dict:
    """Verify adiabatic thermal withstand and end-to-end DC continuity resistance of CPC."""
    from saengine.electrical import cables

    ik_a = float(values["faultCurrentKa"]) * 1000.0
    t_s = float(values["clearingTimeS"])
    s_cpc = float(values["cpcAreaMm2"])
    # Copper XLPE/PVC standard k=143/115 via cables.adiabatic_min_size
    s_min_mm2 = float(cables.adiabatic_min_size(ik_a, t_s))
    r_ohm = 0.0225 * float(values["runLengthM"]) / s_cpc  # 22.5 mOhm·mm²/m warm Cu at 70°C
    ok = s_cpc >= s_min_mm2
    return result(
        summary={
            "requiredMinCpcMm2": round(s_min_mm2, 2),
            "providedCpcMm2": s_cpc,
            "continuityResistanceOhm": round(r_ohm, 4),
            "compliant": ok,
        },
        tables=[
            table(
                "Earth continuity & thermal withstand",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Adiabatic min CPC area", "value": round(s_min_mm2, 2), "unit": "mm²"},
                    {"item": "Provided CPC area", "value": s_cpc, "unit": "mm²"},
                    {"item": "End-to-end R2 continuity", "value": round(r_ohm, 4), "unit": "Ω"},
                    {"item": "Thermal check", "value": "PASS" if ok else "UPSIZE CPC", "unit": "-"},
                ],
            )
        ],
        notes=[
            "Minimum adiabatic CPC sized via saengine.electrical.cables.adiabatic_min_size = I*sqrt(t)/k."
        ],
    )


@feature(
    "mepContainment.earthingResistance",
    "Earthing Resistance",
    part="mep",
    fields=[
        number("soilResistivityOhmM", "Measured soil resistivity rho", 80.0, unit="Ω·m", min=1.0),
        number("rodLengthM", "Earth electrode rod length L", 3.0, unit="m", min=1.0),
        number("rodDiameterMm", "Electrode rod diameter", 16.0, unit="mm", min=8.0),
        number("rodCount", "Number of parallel rods", 4, min=1, max=40),
        number("targetMaxOhm", "Maximum target earth resistance", 2.0, unit="Ω", min=0.2),
    ],
    requires_project=False,
)
def earthingResistance(ctx: FeatureContext, values: dict) -> dict:
    """Compute driven earth-electrode array resistance using Dwight's formula with mutual coupling."""
    import math

    rho = float(values["soilResistivityOhmM"])
    L = float(values["rodLengthM"])
    a = float(values["rodDiameterMm"]) / 2000.0
    n = int(values["rodCount"])
    r_one = (rho / (2.0 * math.pi * L)) * (math.log(4.0 * L / a) - 1.0)
    # Approximate mutual grouping factor (~0.85 for 2-4 spaced rods, ~0.65 for dense arrays)
    eta = 1.0 if n == 1 else max(0.55, 1.0 - 0.08 * math.log2(n))
    r_total = r_one / (n * eta)
    ok = r_total <= float(values["targetMaxOhm"])
    return result(
        summary={
            "singleRodOhm": round(r_one, 2),
            "arrayResistanceOhm": round(r_total, 2),
            "groupingEfficiency": round(eta, 2),
            "compliant": ok,
        },
        tables=[
            table(
                "Earth electrode array resistance",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Single rod (Dwight)", "value": round(r_one, 2), "unit": "Ω"},
                    {"item": "Grouping factor η", "value": round(eta, 2), "unit": "-"},
                    {"item": "Combined earth resistance", "value": round(r_total, 2), "unit": "Ω"},
                    {
                        "item": "Target <= max",
                        "value": "PASS" if ok else "ADD RODS / TREATMENT",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=["Dwight equation R = (rho / (2*pi*L))*(ln(4L/a) - 1) assuming spacing >= 2*L."],
    )


@feature(
    "mepContainment.expansionCouplers",
    "Expansion Couplers",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def expansionCouplers(ctx: FeatureContext, values: dict) -> dict:
    """Expansion Couplers: Fittings."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Expansion Couplers",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepContainment.lightningBond",
    "Lightning Bond",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def lightningBond(ctx: FeatureContext, values: dict) -> dict:
    """Lightning Bond: Earthing."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Lightning Bond",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepContainment.mixedVoltageCheck",
    "Mixed Voltage Check",
    part="mep",
    fields=[
        number(
            "highestCircuitV",
            "Highest circuit nominal voltage (Band II)",
            400.0,
            unit="V",
            min=50.0,
        ),
        number(
            "elvInsulationRatingV",
            "Lowest insulation voltage rating on tray",
            450.0,
            unit="V",
            min=50.0,
        ),
        number("barrierProvidedMm", "Solid divider / clear air gap", 25.0, unit="mm", min=0.0),
    ],
    requires_project=False,
)
def mixedVoltageCheck(ctx: FeatureContext, values: dict) -> dict:
    """Check insulation rating compatibility and physical divider requirement for mixed-voltage containment."""
    u_hi = float(values["highestCircuitV"])
    u_ins = float(values["elvInsulationRatingV"])
    gap = float(values["barrierProvidedMm"])
    insulated_ok = u_ins >= u_hi
    barrier_ok = gap >= 20.0
    compliant = insulated_ok or barrier_ok
    return result(
        summary={
            "insulationMatch": insulated_ok,
            "barrierGapMm": gap,
            "compliant": compliant,
        },
        tables=[
            table(
                "Mixed voltage tray check",
                [("criterion", "Criterion"), ("status", "Status"), ("detail", "Detail")],
                [
                    {
                        "criterion": "Conductor insulation >= max voltage",
                        "status": "PASS" if insulated_ok else "FAIL",
                        "detail": f"{u_ins:g} V vs {u_hi:g} V",
                    },
                    {
                        "criterion": "Physical barrier / >=20mm segregation",
                        "status": "PASS" if barrier_ok else "NONE",
                        "detail": f"{gap:g} mm",
                    },
                    {
                        "criterion": "Combined verdict",
                        "status": "COMPLIANT" if compliant else "SEPARATE TRAYS REQUIRED",
                        "detail": "Insulation or barrier",
                    },
                ],
            )
        ],
        notes=[
            "Mixed Band I / Band II circuits require insulation for highest voltage or a solid barrier/separation."
        ],
    )


@feature(
    "mepContainment.penetrationSeals",
    "Penetration Seals",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def penetrationSeals(ctx: FeatureContext, values: dict) -> dict:
    """Penetration Seals: Routing."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Penetration Seals",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepContainment.reducers",
    "Reducers",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def reducers(ctx: FeatureContext, values: dict) -> dict:
    """Reducers: Fittings."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Reducers",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepContainment.routeClash",
    "Route Clash",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def routeClash(ctx: FeatureContext, values: dict) -> dict:
    """Route Clash: Route Checks."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Route Clash",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )


@feature(
    "mepContainment.segregationCheck",
    "Segregation Check",
    part="mep",
    fields=[
        number("powerCurrentA", "Adjacent 3-phase feeder current", 250.0, unit="A", min=1.0),
        number("parallelRunM", "Parallel power/data run length", 30.0, unit="m", min=1.0),
        number(
            "providedSpacingMm", "Clear horizontal separation distance", 150.0, unit="mm", min=0.0
        ),
        number(
            "screenFactor",
            "Screened data/tray attenuation factor (1.0=unshielded, 0.3=metal divider)",
            0.5,
            min=0.1,
            max=1.0,
        ),
    ],
    requires_project=False,
)
def segregationCheck(ctx: FeatureContext, values: dict) -> dict:
    """Check EMI minimum separation between power feeders and data cabling."""
    base_sep = 200.0 if float(values["powerCurrentA"]) > 100.0 else 100.0
    len_mult = 1.25 if float(values["parallelRunM"]) > 35.0 else 1.0
    req_mm = base_sep * len_mult * float(values["screenFactor"])
    prov_mm = float(values["providedSpacingMm"])
    ok = prov_mm >= req_mm
    return result(
        summary={
            "requiredSeparationMm": round(req_mm, 0),
            "providedSeparationMm": prov_mm,
            "compliant": ok,
        },
        tables=[
            table(
                "EMI power/data segregation check",
                [("parameter", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "parameter": "Required minimum spacing",
                        "value": round(req_mm, 0),
                        "unit": "mm",
                    },
                    {"parameter": "Provided clear separation", "value": prov_mm, "unit": "mm"},
                    {
                        "parameter": "Screening factor applied",
                        "value": values["screenFactor"],
                        "unit": "-",
                    },
                    {
                        "parameter": "EMI segregation status",
                        "value": "PASS" if ok else "INCREASE GAP OR BARRIER",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Cross power and data trays at 90° where crossings occur; ferrous metal divider reduces required gap."
        ],
    )


@feature(
    "mepContainment.supportSpacing",
    "Support Spacing",
    part="mep",
    fields=[
        number("cableLoadKgPerM", "Uniform cable + tray mass load", 28.0, unit="kg/m", min=1.0),
        number("supportSpanM", "Trapese hanger / bracket spacing", 1.8, unit="m", min=0.5, max=6.0),
        number("trayRatedLoadKgPerM", "Selected tray SWL at span", 45.0, unit="kg/m", min=5.0),
    ],
    requires_project=False,
)
def supportSpacing(ctx: FeatureContext, values: dict) -> dict:
    """Check cable tray support bracket gravity reaction and safe working load utilisation."""
    w_kn_m = float(values["cableLoadKgPerM"]) * 9.80665 / 1000.0
    span = float(values["supportSpanM"])
    hanger_kn = w_kn_m * span
    util = float(values["cableLoadKgPerM"]) / float(values["trayRatedLoadKgPerM"])
    max_span_m = span * (1.0 / util) ** 0.5 if util > 0 else span
    ok = util <= 1.0
    return result(
        summary={
            "hangerLoadKn": round(hanger_kn, 3),
            "utilisation": round(util, 2),
            "maxAllowedSpanM": round(min(4.0, max_span_m), 2),
            "compliant": ok,
        },
        tables=[
            table(
                "Tray support spacing check",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Point load per support pair",
                        "value": round(hanger_kn, 3),
                        "unit": "kN",
                    },
                    {"item": "SWL utilisation", "value": f"{util * 100:.1f}", "unit": "%"},
                    {
                        "item": "Est. max span at SWL",
                        "value": round(min(4.0, max_span_m), 2),
                        "unit": "m",
                    },
                    {
                        "item": "Structural status",
                        "value": "PASS" if ok else "REDUCE SPAN",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Size trapeze threaded rods and concrete anchors for factored gravity load + maintenance point load."
        ],
    )


@feature(
    "mepContainment.trayBends",
    "Tray Bends",
    part="mep",
    fields=[
        number(
            "largestCableOdMm", "Largest cable outer diameter on tray", 38.0, unit="mm", min=5.0
        ),
        number(
            "minBendMultiplier",
            "Minimum cable bend radius multiplier (x OD)",
            12.0,
            min=4.0,
            max=20.0,
        ),
        number("trayBendRadiusMm", "Tray flat bend inner radius", 450.0, unit="mm", min=50.0),
    ],
    requires_project=False,
)
def trayBends(ctx: FeatureContext, values: dict) -> dict:
    """Verify horizontal/vertical cable tray fitting radius against largest cable minimum bend radius."""
    req_r = float(values["largestCableOdMm"]) * float(values["minBendMultiplier"])
    prov_r = float(values["trayBendRadiusMm"])
    ok = prov_r >= req_r
    return result(
        summary={
            "requiredBendRadiusMm": round(req_r, 0),
            "providedRadiusMm": prov_r,
            "compliant": ok,
        },
        tables=[
            table(
                "Cable tray bend radius check",
                [("item", "Item"), ("value", "Value"), ("unit", "Unit")],
                [
                    {"item": "Largest cable OD", "value": values["largestCableOdMm"], "unit": "mm"},
                    {"item": "Minimum required radius", "value": round(req_r, 0), "unit": "mm"},
                    {"item": "Fitting inside radius", "value": prov_r, "unit": "mm"},
                    {
                        "item": "Bend check",
                        "value": "PASS" if ok else "UPSIZE FITTING RADIUS",
                        "unit": "-",
                    },
                ],
            )
        ],
        notes=[
            "Use 450 mm or 600 mm long-radius tray bends for HV/armoured feeders exceeding standard tee radii."
        ],
    )


@feature(
    "mepContainment.trayFillCheck",
    "Tray Fill Check",
    part="mep",
    fields=[
        number("trayWidthMm", "Nominal cable tray width", 300.0, unit="mm", min=50.0),
        number("trayDepthMm", "Useful side flange depth", 50.0, unit="mm", min=25.0),
        number("cablesAreaMm2", "Sum of cable outer cross-sections", 4800.0, unit="mm²", min=10.0),
        number("maxFillPct", "Maximum allowable area fill", 40.0, unit="%", min=10.0, max=60.0),
    ],
    requires_project=False,
)
def trayFillCheck(ctx: FeatureContext, values: dict) -> dict:
    """Evaluate cable tray percentage fill against area limit and project trays when open."""
    tray_area = float(values["trayWidthMm"]) * float(values["trayDepthMm"])
    fill_pct = (float(values["cablesAreaMm2"]) / tray_area) * 100.0
    lim = float(values["maxFillPct"])
    spare_pct = max(0.0, lim - fill_pct)
    ok = fill_pct <= lim
    mep_trays = 0
    if ctx.root is not None:
        raw = ctx.raw("mep")
        if isinstance(raw, dict):
            mep_trays = len((raw.get("electrical") or {}).get("trays") or [])
    return result(
        summary={
            "trayAreaMm2": round(tray_area, 0),
            "fillPercent": round(fill_pct, 1),
            "spareCapacityPct": round(spare_pct, 1),
            "projectTrays": mep_trays,
            "compliant": ok,
        },
        tables=[
            table(
                "Cable tray fill check",
                [("item", "Parameter"), ("value", "Value"), ("unit", "Unit")],
                [
                    {
                        "item": "Tray cross-section area",
                        "value": round(tray_area, 0),
                        "unit": "mm²",
                    },
                    {"item": "Cable bundle area", "value": values["cablesAreaMm2"], "unit": "mm²"},
                    {"item": "Calculated fill", "value": round(fill_pct, 1), "unit": "%"},
                    {
                        "item": "Remaining growth allowance",
                        "value": round(spare_pct, 1),
                        "unit": "%",
                    },
                    {"item": "Status", "value": "PASS" if ok else "OVERFILLED", "unit": "-"},
                ],
            )
        ],
        notes=[
            f"40% max area fill leaves air gap for derating & future pulls ({mep_trays} project tray run(s) detected)."
        ],
    )


@feature(
    "mepContainment.traySchedule",
    "Tray Schedule",
    part="mep",
    fields=[text("name", "Output name", "MEP schedule")],
    requires_project=True,
)
def traySchedule(ctx: FeatureContext, values: dict) -> dict:
    """Tray Schedule: Schedules."""
    if ctx.root is None:
        raise FeatureInputError("Open a project before creating output.")
    raw = ctx.raw("mep") or {}
    payload = {
        "feature": "mepContainment.traySchedule",
        "title": "Tray Schedule",
        "name": values["name"],
        "group": "Schedules",
        "mep": raw,
    }
    path = ctx.path("11 Exports/traySchedule.json")
    if path is None:
        raise FeatureInputError("Open a project before creating output.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result(
        summary={"exportPath": str(path), "name": values["name"]},
        tables=[
            table(
                "Tray Schedule",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Export", "value": str(path)}],
            )
        ],
        notes=["Generated an output file from the current MEP project data."],
    )


@feature(
    "mepContainment.trayTees",
    "Tray Tees",
    part="mep",
    fields=[text("reference", "Reference", "MEP-001")],
    requires_project=True,
)
def trayTees(ctx: FeatureContext, values: dict) -> dict:
    """Tray Tees: Fittings."""
    raw = ctx.raw("mep") or {}
    reference = values.get("reference", values.get("systemId", values.get("zoneId", "MEP-001")))
    record_count = sum(len(v) for v in raw.values() if isinstance(v, list))
    return result(
        summary={"reference": reference, "mepRecords": record_count},
        tables=[
            table(
                "Tray Tees",
                [("reference", "Reference"), ("state", "State")],
                [{"reference": reference, "state": "Configured"}],
            )
        ],
        notes=["Project view or configuration state is based on the current MEP model data."],
    )
