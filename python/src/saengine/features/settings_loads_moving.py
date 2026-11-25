"""Project Settings - Loads: Moving, Crane & Bridge Loads tab: vehicles, lanes, cranes, influence lines."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.settings_common import load_settings, parse_numbers
from saengine.fem import cranes as fem_cranes
from saengine.library.settings import CraneRunway
from saengine.report.clauses import in_force
from saengine.special import moving_loads


@feature(
    "settingsLoadsMoving.vehicleLibrary",
    "Vehicle Library",
    part="settings",
    fields=[],
    requires_project=False,
)
def vehicle_library(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List highway traffic load models available in the active code pack or practice table."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        b = moving_loads.basis("movingLoads")
        models = getattr(b.table, "loadModels", None) or {}
    rows = [
        {"id": k, "name": m.label, "laneWidthM": b.table.laneWidth, "source": b.label}
        for k, m in models.items()
    ]
    return result(
        summary={"modelCount": len(rows), "basis": b.label},
        tables=[
            table(
                "Traffic moving load library",
                [
                    ("id", "ID"),
                    ("name", "Model"),
                    ("laneWidthM", "Lane width", "m"),
                    ("source", "Basis"),
                ],
                rows
                or [
                    {
                        "id": "HL93",
                        "name": "Design Truck + Lane",
                        "laneWidthM": 3.6,
                        "source": b.label,
                    }
                ],
            )
        ],
        notes=["Loaded via saengine.special.moving_loads.basis."],
    )


@feature(
    "settingsLoadsMoving.axleLoad",
    "Axle Load",
    part="settings",
    fields=[
        number("frontAxleKn", "Front steering axle", 35.0, unit="kN", min=5.0),
        number("driveAxleKn", "Drive axle load", 145.0, unit="kN", min=10.0),
        number("rearAxleKn", "Rear trailer axle load", 145.0, unit="kN", min=10.0),
        number("spacingM", "Axle spacing", 4.3, unit="m", min=1.2),
    ],
    requires_project=False,
)
def axle_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute gross vehicle weight and simple-span peak moment for a 3-axle design truck."""
    w_tot = values["frontAxleKn"] + values["driveAxleKn"] + values["rearAxleKn"]
    s = values["spacingM"]
    span = max(12.0, 3.0 * s)
    # Approximate max moment near middle axle on simple span
    m_max = (w_tot * span / 4.0) - (values["frontAxleKn"] * s)
    return result(
        summary={"grossVehicleKn": w_tot, "wheelbaseM": 2.0 * s, "refSpanMaxMomentKnM": m_max},
        tables=[
            table(
                "3-axle vehicle summary",
                [("axle", "Axle"), ("loadKn", "Load", "kN")],
                [
                    {"axle": "Front", "loadKn": values["frontAxleKn"]},
                    {"axle": "Drive", "loadKn": values["driveAxleKn"]},
                    {"axle": "Rear", "loadKn": values["rearAxleKn"]},
                    {"axle": "Gross total", "loadKn": w_tot},
                ],
            )
        ],
        notes=[f"Reference simple-span moment evaluated on L = {span:.1f} m."],
    )


@feature(
    "settingsLoadsMoving.wheelSpacing",
    "Wheel Spacing",
    part="settings",
    fields=[
        number("gaugeWidthM", "Transverse wheel center spacing", 1.80, unit="m", min=1.0, max=2.5),
        number("axleLoadKn", "Design axle load", 145.0, unit="kN", min=10.0),
    ],
    requires_project=False,
)
def wheel_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute individual wheel load and transverse wheel-line offset from lane center."""
    wheel_kn = values["axleLoadKn"] / 2.0
    half_gauge = values["gaugeWidthM"] / 2.0
    return result(
        summary={
            "wheelLoadKn": wheel_kn,
            "gaugeWidthM": values["gaugeWidthM"],
            "halfOffsetM": half_gauge,
        },
        tables=[
            table(
                "Transverse wheel spacing",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Wheel load (half axle) [kN]", "value": wheel_kn},
                    {"item": "Wheel offset from centerline [m]", "value": half_gauge},
                ],
            )
        ],
        notes=["Standard 1.80 m transverse gauge distributes each axle into two wheel lines."],
    )


@feature(
    "settingsLoadsMoving.applyVehicle",
    "Apply Vehicle",
    part="settings",
    fields=[
        number("spanM", "Girder span L", 24.0, unit="m", min=4.0),
    ],
    requires_project=False,
)
def apply_vehicle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Evaluate dynamic impact allowance (IM) for the active moving load vehicle model."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        b = moving_loads.basis("movingLoads")
        im, _im_note = moving_loads.dynamic_factor(b.table, values["spanM"])
    return result(
        summary={
            "spanM": values["spanM"],
            "dynamicMultiplier": im,
            "impactPct": (im - 1.0) * 100.0,
        },
        tables=[
            table(
                "Dynamic vehicle allowance",
                [("spanM", "Span", "m"), ("imFactor", "1 + IM"), ("impactPct", "Impact", "%")],
                [{"spanM": values["spanM"], "imFactor": im, "impactPct": (im - 1.0) * 100.0}],
            )
        ],
        notes=["Computed via saengine.special.moving_loads.dynamic_factor."],
    )


@feature(
    "settingsLoadsMoving.laneDefinition",
    "Lane Definition",
    part="settings",
    fields=[
        number(
            "carriagewayWidthM", "Clear curb-to-curb carriageway width", 11.0, unit="m", min=3.0
        ),
    ],
    requires_project=False,
)
def lane_definition(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute design traffic lane count and multiple-presence factor from deck width."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        b = moving_loads.basis("movingLoads")
        n_lanes = moving_loads.lane_count(values["carriagewayWidthM"], b.table)
        mp_list = getattr(b.table, "multiplePresence", [1.2, 1.0, 0.85, 0.65]) or [
            1.2,
            1.0,
            0.85,
            0.65,
        ]
    mp = float(mp_list[min(n_lanes - 1, len(mp_list) - 1)])
    return result(
        summary={
            "carriagewayWidthM": values["carriagewayWidthM"],
            "designLanes": n_lanes,
            "multiplePresenceFactor": mp,
        },
        tables=[
            table(
                "Design traffic lane layout",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Design lanes", "value": n_lanes},
                    {"metric": "Notional lane width [m]", "value": b.table.laneWidth},
                    {"metric": "Multiple presence factor m", "value": mp},
                ],
            )
        ],
        notes=["Computed via saengine.special.moving_loads.lane_count."],
    )


@feature(
    "settingsLoadsMoving.laneWidth",
    "Lane Width",
    part="settings",
    fields=[
        number("laneWidthM", "Notional traffic lane width", 3.6, unit="m", min=2.5, max=4.5),
        number("laneUdlKnPerM", "Uniform lane load", 9.3, unit="kN/m", min=1.0),
    ],
    requires_project=False,
)
def lane_width(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert longitudinal traffic lane line load into equivalent area pressure."""
    kpa = values["laneUdlKnPerM"] / values["laneWidthM"]
    return result(
        summary={"laneWidthM": values["laneWidthM"], "equivalentPressureKpa": kpa},
        tables=[
            table(
                "Traffic lane pressure",
                [
                    ("widthM", "Width", "m"),
                    ("lineKnPerM", "Line load", "kN/m"),
                    ("kpa", "Pressure", "kN/m²"),
                ],
                [
                    {
                        "widthM": values["laneWidthM"],
                        "lineKnPerM": values["laneUdlKnPerM"],
                        "kpa": kpa,
                    }
                ],
            )
        ],
        notes=["Standard 3.0 m loaded patch within 3.6 m notional traffic lane."],
    )


@feature(
    "settingsLoadsMoving.laneEccentricity",
    "Lane Eccentricity",
    part="settings",
    fields=[
        number("deckWidthM", "Bridge deck total width", 12.0, unit="m", min=4.0),
        number("laneWidthM", "Loaded lane width", 3.6, unit="m", min=2.5),
        number("curbClearanceM", "Curb / barrier edge offset", 0.6, unit="m", min=0.0),
    ],
    requires_project=False,
)
def lane_eccentricity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute maximum eccentric lane offset from deck centerline for exterior girder distribution."""
    max_ecc = max(
        0.0, values["deckWidthM"] / 2.0 - values["curbClearanceM"] - values["laneWidthM"] / 2.0
    )
    return result(
        summary={"maxLaneEccentricityM": max_ecc},
        tables=[
            table(
                "Lane transverse eccentricity",
                [("item", "Item"), ("m", "Offset", "m")],
                [
                    {"item": "Deck half-width", "m": values["deckWidthM"] / 2.0},
                    {"item": "Max lane center eccentricity", "m": max_ecc},
                ],
            )
        ],
        notes=["Exterior girder reactions govern when lanes are shifted toward the deck curb."],
    )


@feature(
    "settingsLoadsMoving.lanePath",
    "Lane Path",
    part="settings",
    fields=[
        number("bridgeLengthM", "Bridge alignment length", 60.0, unit="m", min=5.0),
        number("stationStepM", "Discretization station step", 2.0, unit="m", min=0.2),
    ],
    requires_project=False,
)
def lane_path(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Generate longitudinal lane station coordinates for influence line sampling."""
    n_pts = int(values["bridgeLengthM"] / values["stationStepM"]) + 1
    rows = [
        {"station": i, "xM": round(i * values["stationStepM"], 2)} for i in range(min(n_pts, 11))
    ]
    return result(
        summary={"totalLengthM": values["bridgeLengthM"], "stationCount": n_pts},
        tables=[
            table(
                "Lane path stations (first 11)",
                [("station", "Station"), ("xM", "Chainage", "m")],
                rows,
            )
        ],
        notes=["Vehicle axles step along lane chainage stations."],
    )


@feature(
    "settingsLoadsMoving.trainLoad",
    "Train Load",
    part="settings",
    fields=[
        number("udlKnPerM", "Equivalent rail UDL (LM71 = 80 kN/m)", 80.0, unit="kN/m", min=10.0),
        number("axleKn", "Heavy locomotive axle load", 250.0, unit="kN", min=50.0),
        number("spanM", "Track bridge span L", 20.0, unit="m", min=4.0),
    ],
    requires_project=False,
)
def train_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute rail bridge dynamic factor and simple-span bending moment for train loading."""
    l_m = values["spanM"]
    # Dynamic rail factor Phi_2 = 1.44 / (sqrt(L) - 0.2) + 0.82 clamped [1.0, 1.67]
    phi_dyn = min(1.67, max(1.0, 1.44 / max(0.5, math.sqrt(l_m) - 0.2) + 0.82))
    m_static = values["udlKnPerM"] * l_m**2 / 8.0 + values["axleKn"] * l_m / 2.0
    m_dyn = m_static * phi_dyn
    return result(
        summary={"dynamicFactor": phi_dyn, "staticMomentKnM": m_static, "dynamicMomentKnM": m_dyn},
        tables=[
            table(
                "Rail train load effect",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Dynamic factor Φ", "value": phi_dyn},
                    {"item": "Static midspan moment [kN·m]", "value": m_static},
                    {"item": "Dynamic moment [kN·m]", "value": m_dyn},
                ],
            )
        ],
        notes=["Dynamic factor accounts for track irregularities and axle resonance."],
    )


@feature(
    "settingsLoadsMoving.craneLoad",
    "Crane Load",
    part="settings",
    fields=[
        number("capacityKn", "Rated crane lifting capacity", 100.0, unit="kN", min=5.0),
        number("bridgeWeightKn", "Crane bridge weight", 60.0, unit="kN", min=5.0),
        number("trolleyWeightKn", "Hoist & trolley weight", 18.0, unit="kN", min=1.0),
        number("spanM", "Crane bridge span", 18.0, unit="m", min=4.0),
    ],
    requires_project=False,
)
def crane_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute crane runway wheel vertical, impact, lateral, and longitudinal forces."""
    st = load_settings(ctx)
    crane = CraneRunway(
        id="CR-1",
        name="Overhead Crane",
        kind="pendantOperated",
        capacity=values["capacityKn"],
        bridgeWeight=values["bridgeWeightKn"],
        trolleyWeight=values["trolleyWeightKn"],
        span=values["spanM"] * 1000.0,
        hookApproach=1200.0,
        wheels=2,
        wheelBase=2800.0,
        runwaySpan=6000.0,
        railLevel=7000.0,
    )
    with in_force(ctx.root, st):
        wl = fem_cranes.wheel_loads(crane)
    return result(
        summary={
            "staticWheelKn": wl.static_max,
            "verticalWithImpactKn": wl.vertical,
            "lateralPerWheelKn": wl.lateral,
            "longitudinalPerRailKn": wl.longitudinal,
        },
        tables=[
            table(
                "Crane runway forces",
                [("force", "Component"), ("kn", "Load", "kN")],
                [
                    {"force": "Static max wheel", "kn": wl.static_max},
                    {"force": "Vertical wheel with impact", "kn": wl.vertical},
                    {"force": "Transverse lateral per wheel", "kn": wl.lateral},
                    {"force": "Longitudinal braking per rail", "kn": wl.longitudinal},
                ],
            )
        ],
        notes=wl.clauses or ["Computed via saengine.fem.cranes.wheel_loads."],
    )


@feature(
    "settingsLoadsMoving.dynamicFactor",
    "Dynamic Factor",
    part="settings",
    fields=[
        number("spanM", "Bridge span length L", 18.0, unit="m", min=2.0),
    ],
    requires_project=False,
)
def mv_dynamic_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute moving-load dynamic amplification factor across deck spans."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        b = moving_loads.basis("movingLoads")
        rows = [
            {"spanM": s, "dynamicFactor": moving_loads.dynamic_factor(b.table, s)[0]}
            for s in (6.0, 12.0, values["spanM"], 36.0, 60.0)
        ]
        cur, _ = moving_loads.dynamic_factor(b.table, values["spanM"])
    return result(
        summary={"spanM": values["spanM"], "dynamicFactor": cur},
        tables=[
            table(
                "Dynamic load allowance vs span",
                [("spanM", "Span", "m"), ("dynamicFactor", "1 + IM")],
                rows,
            )
        ],
        notes=["Evaluated using active code pack movingLoads rules."],
    )


@feature(
    "settingsLoadsMoving.applyMoving",
    "Apply Moving",
    part="settings",
    fields=[],
    requires_project=False,
)
def apply_moving(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect crane runways and bridge moving-load models configured in project settings."""
    st = load_settings(ctx)
    cranes = st.cranes
    rows = [
        {"id": c.id, "name": c.name, "kind": c.kind, "capacityKn": c.capacity, "spanM": c.span}
        for c in cranes
    ]
    has_special = any(
        bool(getattr(st.specialStructures, f, None))
        for f in ("bridges", "towers", "tanks", "silos", "chimneys", "offshore")
    )
    return result(
        summary={"configuredCranes": len(cranes), "hasSpecialStructures": has_special},
        tables=[
            table(
                "Configured moving-load systems",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("kind", "Kind"),
                    ("capacityKn", "Capacity", "kN"),
                    ("spanM", "Span", "m"),
                ],
                rows
                or [
                    {
                        "id": "-",
                        "name": "No cranes in settings",
                        "kind": "-",
                        "capacityKn": 0.0,
                        "spanM": 0.0,
                    }
                ],
            )
        ],
        notes=["Moving crane and bridge definitions live in project settings cranes and special."],
    )


@feature(
    "settingsLoadsMoving.cyclicVehicle",
    "Cyclic Vehicle",
    part="settings",
    fields=[
        number("fatigueTruckKn", "Fatigue design truck gross weight", 240.0, unit="kN", min=40.0),
        number("impactFactor", "Fatigue dynamic impact (typically 1.15)", 1.15, min=1.0, max=1.5),
    ],
    requires_project=False,
)
def cyclic_vehicle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute factored cyclic fatigue truck load for bridge stress-range checks."""
    eff = values["fatigueTruckKn"] * values["impactFactor"]
    return result(
        summary={"grossTruckKn": values["fatigueTruckKn"], "factoredFatigueKn": eff},
        tables=[
            table(
                "Cyclic fatigue truck",
                [("item", "Item"), ("kn", "Load", "kN")],
                [
                    {"item": "Nominal fatigue truck", "kn": values["fatigueTruckKn"]},
                    {"item": "With fatigue impact", "kn": eff},
                ],
            )
        ],
        notes=["Single fatigue truck placed without multi-lane presence reduction."],
    )


@feature(
    "settingsLoadsMoving.stressRangeTruck",
    "Stress Range Truck",
    part="settings",
    fields=[
        number("sigmaMaxMpa", "Peak tensile cyclic stress", 85.0, unit="MPa"),
        number("sigmaMinMpa", "Minimum cyclic stress", -15.0, unit="MPa"),
        number(
            "allowableRangeMpa", "Detail category fatigue threshold", 110.0, unit="MPa", min=10.0
        ),
    ],
    requires_project=False,
)
def stress_range_truck(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check algebraic fatigue stress range Δσ = σmax - σmin against detail category limit."""
    delta_sigma = values["sigmaMaxMpa"] - values["sigmaMinMpa"]
    util = delta_sigma / values["allowableRangeMpa"]
    return result(
        summary={"stressRangeMpa": delta_sigma, "utilisation": util, "passing": util <= 1.0},
        tables=[
            table(
                "Fatigue stress range check",
                [("metric", "Metric"), ("mpa", "Stress", "MPa")],
                [
                    {"metric": "Stress range Δσ", "mpa": delta_sigma},
                    {"metric": "Allowable threshold Δσ_fat", "mpa": values["allowableRangeMpa"]},
                ],
            )
        ],
        notes=["Stress range excludes dead-load mean stress in welded steel details."],
    )


@feature(
    "settingsLoadsMoving.repetitionIndex",
    "Repetition Index",
    part="settings",
    fields=[
        number("adttSingleLane", "Single-lane average daily truck traffic", 1500.0, min=10.0),
        number("designLifeYears", "Bridge fatigue design life", 75.0, unit="yr", min=10.0),
        number("cyclesPerTruck", "Stress cycles per truck passage", 1.5, min=1.0, max=5.0),
    ],
    requires_project=False,
)
def repetition_index(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute cumulative lifetime fatigue load cycles N = 365 × Life × ADTT × cycles/truck."""
    n_tot = 365.0 * values["designLifeYears"] * values["adttSingleLane"] * values["cyclesPerTruck"]
    return result(
        summary={"totalFatigueCycles": n_tot, "millionsOfCycles": n_tot / 1e6},
        tables=[
            table(
                "Cumulative fatigue cycle count",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Total cycles N", "value": n_tot},
                    {"item": "Million cycles (M)", "value": n_tot / 1e6},
                ],
            )
        ],
        notes=["Cumulative cycles govern finite-life S-N fatigue strength reduction."],
    )


@feature(
    "settingsLoadsMoving.axleCount",
    "Axle Count",
    part="settings",
    fields=[
        text("axleLoadsCsv", "Axle loads [kN] (comma-separated)", "35, 110, 110, 130, 130"),
    ],
    requires_project=False,
)
def axle_count(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate multi-axle heavy transport vehicle configuration and compute total load."""
    axles = parse_numbers(values["axleLoadsCsv"], "Axle loads")
    tot = sum(axles)
    rows = [
        {"axleNo": i + 1, "loadKn": v, "sharePct": (v / tot) * 100.0} for i, v in enumerate(axles)
    ]
    return result(
        summary={"axleCount": len(axles), "grossWeightKn": tot, "heaviestAxleKn": max(axles)},
        tables=[
            table(
                "Heavy vehicle axle distribution",
                [("axleNo", "Axle #"), ("loadKn", "Load", "kN"), ("sharePct", "Share", "%")],
                rows,
            )
        ],
        notes=["Supports arbitrary multi-axle specialized haul configurations."],
    )


@feature(
    "settingsLoadsMoving.legalLoad",
    "Legal Load",
    part="settings",
    fields=[
        select(
            "truck",
            "Highway legal vehicle",
            [
                ("type3", "Type 3 (3-axle, 222 kN)"),
                ("type3S2", "Type 3S2 (5-axle, 320 kN)"),
                ("type3_3", "Type 3-3 (6-axle, 356 kN)"),
            ],
            "type3S2",
        ),
    ],
    requires_project=False,
)
def legal_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect standard highway legal truck weights for bridge load-posting ratings."""
    trucks = {"type3": (3, 222.0), "type3S2": (5, 320.0), "type3_3": (6, 356.0)}
    axles, wt = trucks[values["truck"]]
    return result(
        summary={"legalVehicle": values["truck"], "axles": axles, "grossWeightKn": wt},
        tables=[
            table(
                "Legal rating vehicle",
                [("vehicle", "Vehicle"), ("axles", "Axles"), ("weightKn", "Gross", "kN")],
                [{"vehicle": values["truck"], "axles": axles, "weightKn": wt}],
            )
        ],
        notes=["Legal vehicles establish safe posting tonnage when RF < 1.0."],
    )


@feature(
    "settingsLoadsMoving.permitVehicle",
    "Permit Vehicle",
    part="settings",
    fields=[
        number("grossWeightKn", "Permit truck gross weight", 650.0, unit="kN", min=100.0),
        number("axles", "Number of axles", 7.0, min=3.0, max=20.0),
        number(
            "permitLiveFactor", "Permit evaluation live load factor γL", 1.35, min=1.1, max=1.75
        ),
    ],
    requires_project=False,
)
def permit_vehicle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute average axle load and factored permit demand for oversize vehicle evaluation."""
    n = int(values["axles"])
    avg = values["grossWeightKn"] / n
    factored = values["grossWeightKn"] * values["permitLiveFactor"]
    return result(
        summary={
            "grossWeightKn": values["grossWeightKn"],
            "meanAxleKn": avg,
            "factoredGrossKn": factored,
        },
        tables=[
            table(
                "Permit vehicle summary",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Axle count", "value": n},
                    {"item": "Mean axle load [kN]", "value": avg},
                    {"item": "Factored gross demand [kN]", "value": factored},
                ],
            )
        ],
        notes=["Permit checks evaluate escorted single-lane or mixed-traffic crossing."],
    )


@feature(
    "settingsLoadsMoving.overloadTruck",
    "Overload Truck",
    part="settings",
    fields=[
        number("designMomentKnM", "Design live load moment ML", 950.0, unit="kN·m", min=10.0),
        number("overloadMomentKnM", "Overload pass moment M_ov", 1320.0, unit="kN·m", min=10.0),
    ],
    requires_project=False,
)
def overload_truck(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute overload demand ratio M_ov / ML against standard design live load."""
    ratio = values["overloadMomentKnM"] / values["designMomentKnM"]
    return result(
        summary={"overloadRatio": ratio, "exceedsDesignEnvelope": ratio > 1.0},
        tables=[
            table(
                "Overload demand comparison",
                [("case", "Case"), ("momentKnM", "Moment", "kN·m")],
                [
                    {"case": "Design envelope", "momentKnM": values["designMomentKnM"]},
                    {"case": "Superload pass", "momentKnM": values["overloadMomentKnM"]},
                ],
            )
        ],
        notes=["Ratios > 1.0 require structural rating check prior to route approval."],
    )


@feature(
    "settingsLoadsMoving.ratingVehicle",
    "Rating Vehicle",
    part="settings",
    fields=[
        number("capacityPhiRnKnM", "Factored moment resistance φMn", 1850.0, unit="kN·m", min=10.0),
        number("deadMomentKnM", "Factored dead load moment γD MD", 620.0, unit="kN·m", min=0.0),
        number(
            "vehicleMomentKnM", "Factored unit vehicle moment γL M_veh", 980.0, unit="kN·m", min=1.0
        ),
    ],
    requires_project=False,
)
def rating_vehicle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute bridge load rating factor RF = (C - γD D) / (γL L(1+IM))."""
    rf = (values["capacityPhiRnKnM"] - values["deadMomentKnM"]) / values["vehicleMomentKnM"]
    return result(
        summary={"ratingFactor": rf, "adequate": rf >= 1.0},
        tables=[
            table(
                "Bridge load rating factor",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {
                        "metric": "Available live capacity [kN·m]",
                        "value": values["capacityPhiRnKnM"] - values["deadMomentKnM"],
                    },
                    {"metric": "Rating factor RF", "value": rf},
                ],
            )
        ],
        notes=["RF >= 1.0 indicates the structure safely carries the rating vehicle."],
    )


@feature(
    "settingsLoadsMoving.influenceLine",
    "Influence Line",
    part="settings",
    fields=[
        number("span1M", "Span 1 length", 18.0, unit="m", min=2.0),
        number("span2M", "Span 2 length (0 = simple span)", 18.0, unit="m", min=0.0),
    ],
    requires_project=False,
)
def influence_line(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute beam influence line ordinates via saengine.special.moving_loads.line_influence."""
    spans = [values["span1M"]] + ([values["span2M"]] if values["span2M"] > 0 else [])
    il = moving_loads.line_influence(spans, max_step=1.0)
    # Peak midspan sagging moment ordinate
    mid_idx = len(il.x) // 4 if len(spans) > 1 else len(il.x) // 2
    peak_m = float(max(il.moment[mid_idx]))
    rows = [
        {"stationM": round(float(il.x[i]), 2), "momentOrdM": float(il.moment[mid_idx][i])}
        for i in range(0, len(il.x), max(1, len(il.x) // 10))
    ]
    return result(
        summary={"stationCount": len(il.x), "samplePeakMomentOrdinateM": peak_m},
        tables=[
            table(
                f"Moment influence line at x={il.x[mid_idx]:.1f} m",
                [("stationM", "Load x", "m"), ("momentOrdM", "Ordinate", "m")],
                rows,
            )
        ],
        notes=[
            "Generated via saengine.special.moving_loads.line_influence continuous girder solver."
        ],
    )


@feature(
    "settingsLoadsMoving.envelopeGeneration",
    "Envelope Generation",
    part="settings",
    fields=[
        number("spanM", "Simple bridge span L", 20.0, unit="m", min=4.0),
    ],
    requires_project=False,
)
def envelope_generation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Run moving load vehicle + lane envelope along a beam line using active code pack."""
    st = load_settings(ctx)
    span = values["spanM"]
    with in_force(ctx.root, st):
        il = moving_loads.line_influence([span], max_step=1.0)
        b = moving_loads.basis("movingLoads")
        dyn, _ = moving_loads.dynamic_factor(b.table, span)
        mid = len(il.x) // 2
        high_m, low_m = moving_loads.envelope(
            [(il.x, il.moment[mid], il.moment[mid], 3.5, 1.0)], b, dyn
        )
        high_v, low_v = moving_loads.envelope(
            [(il.x, il.shear_right[0], il.shear_right[0], 3.5, 1.0)], b, dyn
        )
    pos_max = max(abs(high_m.value), abs(low_m.value))
    shear_max = max(abs(high_v.value), abs(low_v.value))
    return result(
        summary={"spanM": span, "maxEnvelopeMomentKnM": pos_max, "maxEnvelopeShearKn": shear_max},
        tables=[
            table(
                "Moving load force envelope",
                [("effect", "Effect"), ("value", "Peak value")],
                [
                    {"effect": "Max positive moment [kN·m]", "value": pos_max},
                    {"effect": "Max shear [kN]", "value": shear_max},
                ],
            )
        ],
        notes=[f"Computed via saengine.special.moving_loads.envelope ({b.label})."],
    )


@feature(
    "settingsLoadsMoving.brakingForce",
    "Braking Force",
    part="settings",
    fields=[
        number("designTruckKn", "Design truck weight", 325.0, unit="kN", min=50.0),
        number("laneLoadKnPerM", "Lane load intensity", 9.3, unit="kN/m", min=0.0),
        number("loadedLengthM", "Loaded lane length", 30.0, unit="m", min=4.0),
    ],
    requires_project=False,
)
def braking_force(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute longitudinal vehicle braking force max(0.25 × truck, 0.05 × (truck + lane))."""
    f1 = 0.25 * values["designTruckKn"]
    f2 = 0.05 * (values["designTruckKn"] + values["laneLoadKnPerM"] * values["loadedLengthM"])
    br = max(f1, f2)
    return result(
        summary={"truck25PctKn": f1, "combo5PctKn": f2, "designBrakingKn": br},
        tables=[
            table(
                "Longitudinal braking force",
                [("criterion", "Criterion"), ("kn", "Force", "kN")],
                [
                    {"criterion": "25% of design truck", "kn": f1},
                    {"criterion": "5% of truck + lane load", "kn": f2},
                    {"criterion": "Governing braking force", "kn": br},
                ],
            )
        ],
        notes=["Acts horizontally at 1.8 m above deck surface along the traffic lane."],
    )


@feature(
    "settingsLoadsMoving.centrifugalForce",
    "Centrifugal Force",
    part="settings",
    fields=[
        number("speedKmPerH", "Design highway speed v", 80.0, unit="km/h", min=20.0, max=160.0),
        number("curveRadiusM", "Horizontal curve radius R", 250.0, unit="m", min=30.0),
        number("axleWeightKn", "Vehicle axle/gross weight", 325.0, unit="kN", min=10.0),
    ],
    requires_project=False,
)
def centrifugal_force(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute radial centrifugal force C = (4/3) v² / (g R) × W on curved bridge lanes."""
    v_ms = values["speedKmPerH"] / 3.6
    c_ratio = (4.0 / 3.0) * (v_ms**2) / (9.80665 * values["curveRadiusM"])
    cf_kn = c_ratio * values["axleWeightKn"]
    return result(
        summary={"centrifugalRatioC": c_ratio, "centrifugalForceKn": cf_kn},
        tables=[
            table(
                "Radial centrifugal force",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Design speed [m/s]", "value": v_ms},
                    {"metric": "Centrifugal factor C", "value": c_ratio},
                    {"metric": "Radial force [kN]", "value": cf_kn},
                ],
            )
        ],
        notes=["C = 4/3 · v² / (g · R) accounts for dynamic speed factor on curved alignments."],
    )
