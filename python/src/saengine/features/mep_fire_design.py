"""Fire protection hydraulic calculations and project schedules."""

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
    "mepFire.sprinklerDensity",
    "Sprinkler Density",
    part="mep",
    fields=[
        select("hazard", "Hazard classification", ["light", "ordinary", "high"]),
        number("densityLpmM2", "Design discharge density", 5, unit="L/(min·m²)", min=0.1),
        number("designAreaM2", "Remote design area", 140, unit="m²", min=1),
        number("hoseAllowanceLpm", "Hose stream allowance", 0, unit="L/min", min=0),
    ],
    requires_project=False,
)
def sprinkler_density(ctx: FeatureContext, values: dict) -> dict:
    """Calculate sprinkler and combined water demand from entered density."""
    sprinkler = values["densityLpmM2"] * values["designAreaM2"]
    total = sprinkler + values["hoseAllowanceLpm"]
    return result(
        summary={
            "sprinklerDemandLpm": sprinkler,
            "combinedDemandLpm": total,
            "combinedFlowLps": total / 60,
        },
        notes=[
            "Demand equals design discharge density multiplied by remote area plus the separately entered hose allowance; confirm design basis and duration for the project hazard."
        ],
    )


@feature(
    "mepFire.pipeSchedule",
    "Pipe Schedule",
    part="mep",
    fields=[
        select(
            "method",
            "Pipe sizing method",
            [("schedule", "Pipe schedule"), ("hydraulic", "Hydraulic calculation")],
        ),
        select("material", "Pipe material", ["steel", "copper", "stainlessSteel"]),
        number("designFlowLpm", "Design flow", 600, unit="L/min", min=1),
        number("minimumDiameterMm", "Minimum nominal diameter", 25, unit="mm", min=15),
    ],
    requires_project=False,
)
def pipe_schedule(ctx: FeatureContext, values: dict) -> dict:
    """Select a fire pipe diameter from the engine's flow sizing function."""
    from saengine.fire.network import size_for

    diameter = size_for(values["designFlowLpm"], values["material"], values["minimumDiameterMm"])
    return result(
        summary={
            "method": values["method"],
            "selectedDiameterMm": diameter,
            "designFlowLpm": values["designFlowLpm"],
        },
        notes=[
            "Diameter is selected by the engine's fire-pipe velocity sizing table; confirm friction-loss performance for the complete network."
        ],
    )


@feature(
    "mepFire.alarmValve",
    "Alarm Valve",
    part="mep",
    fields=[
        number("systemFlowLps", "System flow", 10, unit="L/s", min=0.01),
        number("valveLossCoefficient", "Valve loss coefficient", 2.5, min=0),
        number("upstreamPressureKpa", "Upstream pressure", 500, unit="kPa", min=0),
        number("minimumResidualKpa", "Minimum residual pressure", 350, unit="kPa", min=0),
        number("valveBoreMm", "Valve bore", 100, unit="mm", min=10),
    ],
    requires_project=False,
)
def alarm_valve(ctx: FeatureContext, values: dict) -> dict:
    """Estimate alarm-valve pressure loss and residual pressure."""
    velocity = values["systemFlowLps"] / 1000 / (math.pi * (values["valveBoreMm"] / 1000) ** 2 / 4)
    loss = values["valveLossCoefficient"] * 1000 * velocity**2 / 2 / 1000
    residual = values["upstreamPressureKpa"] - loss
    return result(
        summary={
            "valveLossKpa": loss,
            "residualPressureKpa": residual,
            "residualPasses": residual >= values["minimumResidualKpa"],
        },
        notes=[
            "Pressure loss uses a local-loss coefficient and water density of 1000 kg/m³; confirm the selected alarm-check valve curve and trim losses."
        ],
    )


@feature(
    "mepFire.flowSwitch",
    "Flow Switch",
    part="mep",
    fields=[
        number("normalFlowLps", "Normal system flow", 0, unit="L/s", min=0),
        number("alarmFlowLps", "Design alarm flow", 1.0, unit="L/s", min=0),
        number("switchSetpointLps", "Flow switch setpoint", 0.5, unit="L/s", min=0),
        number("switchDelayS", "Alarm delay", 30, unit="s", min=0),
    ],
    requires_project=False,
)
def flow_switch(ctx: FeatureContext, values: dict) -> dict:
    """Verify flow switch discrimination between normal and alarm flows."""
    detects = values["alarmFlowLps"] >= values["switchSetpointLps"]
    nuisance = values["normalFlowLps"] >= values["switchSetpointLps"]
    return result(
        summary={
            "detectsDesignFlow": detects,
            "avoidsNormalFlowAlarm": not nuisance,
            "delayS": values["switchDelayS"],
        },
        notes=[
            "Switch setpoint and delay are project inputs; verify the monitored flow path and device listing with the fire alarm cause-and-effect schedule."
        ],
    )


@feature(
    "mepFire.sprinklerPiping",
    "Sprinkler Piping",
    part="mep",
    fields=[
        select("material", "Pipe material", ["steel", "copper", "stainlessSteel"]),
        select("jointType", "Joint type", ["threaded", "grooved", "welded", "pressFit"]),
        number("corrosionAllowanceMm", "Corrosion allowance", 0, unit="mm", min=0),
        number("designPressureKpa", "Design pressure", 1200, unit="kPa", min=0),
    ],
    requires_project=False,
)
def sprinkler_piping(ctx: FeatureContext, values: dict) -> dict:
    """Record sprinkler pipe material, jointing and pressure design values."""
    return result(
        summary={
            "material": values["material"],
            "jointType": values["jointType"],
            "designPressureKpa": values["designPressureKpa"],
        },
        tables=[
            table(
                "Piping specification",
                [("property", "Property"), ("value", "Value")],
                [
                    {"property": "Material", "value": values["material"]},
                    {"property": "Joint type", "value": values["jointType"]},
                    {
                        "property": "Corrosion allowance",
                        "value": f"{values['corrosionAllowanceMm']} mm",
                    },
                    {"property": "Design pressure", "value": f"{values['designPressureKpa']} kPa"},
                ],
            )
        ],
        notes=[
            "Confirm pressure rating, corrosion protection, joining procedure, compatibility and fire-system approval for the selected components."
        ],
    )


@feature(
    "mepFire.storageTank",
    "Storage Tank",
    part="mep",
    fields=[
        number("designFlowLps", "Fire demand", 25, unit="L/s", min=0.1),
        number("durationMinutes", "Required duration", 60, unit="min", min=1),
        number("usableFraction", "Usable storage fraction", 0.9, min=0.1, max=1),
        number("replenishmentLps", "Reliable replenishment", 0, unit="L/s", min=0),
    ],
    requires_project=False,
)
def storage_tank(ctx: FeatureContext, values: dict) -> dict:
    """Size gross fire storage after accounting for replenishment."""
    net_l = (
        max(values["designFlowLps"] - values["replenishmentLps"], 0)
        * values["durationMinutes"]
        * 60
    )
    gross_m3 = net_l / values["usableFraction"] / 1000
    return result(
        summary={"netFireVolumeM3": net_l / 1000, "grossTankVolumeM3": gross_m3},
        notes=[
            "Net storage is (fire demand minus credited reliable replenishment) × duration; gross volume accounts for the entered unusable fraction."
        ],
    )


@feature(
    "mepFire.firePump",
    "Fire Pump",
    part="mep",
    fields=[
        number("flowLps", "Rated fire flow", 25, unit="L/s", min=0.1),
        number("headM", "Rated pump head", 70, unit="m", min=0.1),
        number("pumpEfficiency", "Pump efficiency", 0.72, min=0.05, max=1),
        number("motorEfficiency", "Motor efficiency", 0.9, min=0.05, max=1),
        number("standbyPumps", "Standby pump count", 1, min=0),
    ],
    requires_project=False,
)
def fire_pump(ctx: FeatureContext, values: dict) -> dict:
    """Estimate fire pump input power and duty/standby capacity."""
    hydraulic_kw = 9.80665 * values["flowLps"] * values["headM"] / 1000
    input_kw = hydraulic_kw / values["pumpEfficiency"] / values["motorEfficiency"]
    return result(
        summary={
            "hydraulicPowerKw": hydraulic_kw,
            "motorInputKw": input_kw,
            "installedPumpCount": 1 + int(values["standbyPumps"]),
        },
        notes=[
            "Power is derived from water hydraulic power and entered pump/motor efficiencies; confirm rated curve, driver selection and starting method."
        ],
    )


@feature(
    "mepFire.suctionTank",
    "Suction Tank",
    part="mep",
    fields=[
        number("tankVolumeM3", "Effective tank volume", 45, unit="m³", min=0),
        number("pumpFlowLps", "Fire pump flow", 25, unit="L/s", min=0.1),
        number("replenishmentLps", "Tank replenishment", 5, unit="L/s", min=0),
        number("minimumSubmergenceM", "Minimum pump submergence", 0.5, unit="m", min=0),
    ],
    requires_project=False,
)
def suction_tank(ctx: FeatureContext, values: dict) -> dict:
    """Estimate available fire draw-off duration from tank volume and net flow."""
    net = max(values["pumpFlowLps"] - values["replenishmentLps"], 0)
    duration = values["tankVolumeM3"] * 1000 / net / 60 if net else None
    return result(
        summary={
            "netDrawOffLps": net,
            "availableDurationMinutes": duration,
            "minimumSubmergenceM": values["minimumSubmergenceM"],
        },
        notes=[
            "Duration uses usable tank volume as entered; exclude dead storage and verify vortex suppression, inlet separation and minimum submergence in detailed suction design."
        ],
    )


@feature(
    "mepFire.boosterPump",
    "Booster Pump",
    part="mep",
    fields=[
        number("requiredResidualKpa", "Required residual pressure", 350, unit="kPa", min=0),
        number("availableSupplyKpa", "Available incoming pressure", 180, unit="kPa", min=0),
        number("elevationM", "Elevation to critical outlet", 25, unit="m", min=0),
        number("frictionLossKpa", "Distribution friction loss", 30, unit="kPa", min=0),
    ],
    requires_project=False,
)
def booster_pump(ctx: FeatureContext, values: dict) -> dict:
    """Calculate required booster differential pressure and head."""
    required = (
        values["requiredResidualKpa"]
        + values["elevationM"] * 9.80665
        + values["frictionLossKpa"]
        - values["availableSupplyKpa"]
    )
    return result(
        summary={
            "boosterDifferentialKpa": max(required, 0),
            "boosterHeadM": max(required, 0) / 9.80665,
            "boosterRequired": required > 0,
        },
        notes=[
            "Pressure budget adds outlet residual, static lift and friction losses, then deducts available supply pressure."
        ],
    )


@feature(
    "mepFire.heatDetector",
    "Heat Detector",
    part="mep",
    fields=[
        number("roomAreaM2", "Protected room area", 100, unit="m²", min=1),
        number("detectorCoverageM2", "Design coverage per detector", 50, unit="m²", min=1),
        number("roomLengthM", "Room length", 10, unit="m", min=0.1),
        number("maximumSpacingM", "Maximum detector spacing", 7, unit="m", min=0.1),
    ],
    requires_project=False,
)
def heat_detector(ctx: FeatureContext, values: dict) -> dict:
    """Estimate heat detector count from area and spacing criteria."""
    by_area = math.ceil(values["roomAreaM2"] / values["detectorCoverageM2"])
    by_spacing = math.ceil(values["roomLengthM"] / values["maximumSpacingM"])
    return result(
        summary={
            "detectorCount": max(by_area, by_spacing),
            "countByArea": by_area,
            "countBySpacing": by_spacing,
        },
        notes=[
            "Detector coverage and spacing are editable project design criteria; verify ceiling height, beams, airflow and manufacturer's listing."
        ],
    )


@feature(
    "mepFire.beamDetector",
    "Beam Detector",
    part="mep",
    fields=[
        number("openAreaM2", "Open protected area", 1200, unit="m²", min=1),
        number("beamCoverageM2", "Rated plan coverage per beam", 1000, unit="m²", min=1),
        number("maximumPathM", "Maximum transmitter-receiver path", 100, unit="m", min=1),
        number("longestPathM", "Longest proposed path", 75, unit="m", min=0.1),
    ],
    requires_project=False,
)
def beam_detector(ctx: FeatureContext, values: dict) -> dict:
    """Check beam detector coverage area and optical path length."""
    count = math.ceil(values["openAreaM2"] / values["beamCoverageM2"])
    return result(
        summary={
            "beamDetectorCount": count,
            "pathPasses": values["longestPathM"] <= values["maximumPathM"],
        },
        notes=[
            "Coverage and path limits must follow the selected detector listing and site geometry; obstruction and alignment tolerances are not modeled."
        ],
    )


@feature(
    "mepFire.manualCallPoint",
    "Manual Call Point",
    part="mep",
    fields=[
        number("escapeRouteLengthM", "Escape route length", 45, unit="m", min=0),
        number("maximumTravelSpacingM", "Maximum travel spacing", 30, unit="m", min=1),
        number("mountingHeightMm", "Mounting height", 1200, unit="mm", min=0),
    ],
    requires_project=False,
)
def manual_call_point(ctx: FeatureContext, values: dict) -> dict:
    """Estimate call point quantity along the entered escape route."""
    count = max(1, math.ceil(values["escapeRouteLengthM"] / values["maximumTravelSpacingM"]))
    return result(
        summary={
            "callPointCount": count,
            "routeLengthM": values["escapeRouteLengthM"],
            "mountingHeightMm": values["mountingHeightMm"],
        },
        notes=[
            "Count is a route-length spacing estimate; place call points at exits and verify travel distances and mounting criteria for the project."
        ],
    )


@feature("mepFire.detectionZoning", "Detection Zoning", part="mep", requires_project=True)
def detection_zoning(ctx: FeatureContext, values: dict) -> dict:
    """Group modeled fire story areas into detector zones by an editable area cap."""
    raw = ctx.raw("mep")
    fire = raw.get("fire") if raw else None
    stories = fire.get("stories", []) if isinstance(fire, dict) else []
    if not stories:
        raise FeatureInputError(
            "Add fire story areas to 07 MEP/mep.json before defining detection zones."
        )
    rows = []
    for story in stories:
        area = float(story.get("area", 0))
        rows.append(
            {
                "story": story.get("story", ""),
                "areaM2": area,
                "zoneCountAt500M2": math.ceil(area / 500) if area > 0 else 0,
            }
        )
    return result(
        summary={"fireStories": len(rows), "totalAreaM2": sum(row["areaM2"] for row in rows)},
        tables=[
            table(
                "Detection zone area basis",
                [
                    ("story", "Story"),
                    ("areaM2", "Area", "m²"),
                    ("zoneCountAt500M2", "Zones at 500 m²"),
                ],
                rows,
            )
        ],
        notes=[
            "Story areas come from project fire data; the displayed 500 m² split is a transparent coordination screening value, not a code requirement."
        ],
    )


def _raw_fire(ctx: FeatureContext) -> tuple[dict, dict]:
    raw = ctx.raw("mep")
    if not raw or not isinstance(raw.get("fire"), dict):
        raise FeatureInputError("Add fire system data to 07 MEP/mep.json first.")
    return raw, raw["fire"]


@feature("mepFire.fireStrategyNote", "Fire Strategy Note", part="mep", requires_project=True)
def fire_strategy_note(ctx: FeatureContext, values: dict) -> dict:
    """Summarize modeled fire protection scope for a strategy review."""
    raw, fire = _raw_fire(ctx)
    stories = fire.get("stories", [])
    devices = [
        item
        for item in raw.get("equipment", [])
        if "fire" in str(item.get("kind", "")).lower()
        or "sprink" in str(item.get("kind", "")).lower()
    ]
    rows = [
        {"system": "Fire area", "projectData": len(stories)},
        {"system": "Fire equipment", "projectData": len(devices)},
        {"system": "Fire volume", "projectData": sum(float(s.get("area", 0)) for s in stories)},
    ]
    return result(
        summary={
            "storyCount": len(stories),
            "fireEquipmentCount": len(devices),
            "documentedFloorAreaM2": rows[-1]["projectData"],
        },
        tables=[
            table(
                "Strategy scope inventory",
                [("system", "Scope"), ("projectData", "Project data")],
                rows,
            )
        ],
        notes=[
            "This scope inventory is not a fire strategy compliance determination; confirm compartmentation, egress, access and system design with the project fire strategy."
        ],
    )


@feature("mepFire.fireDrawings", "Fire Drawings", part="mep", requires_project=True)
def fire_drawings(ctx: FeatureContext, values: dict) -> dict:
    """Prepare fire plan annotations from modeled fire equipment and locations."""
    raw, fire = _raw_fire(ctx)
    equipment = [
        {
            "id": e.get("id", ""),
            "kind": e.get("kind", ""),
            "story": e.get("story", ""),
            "xMm": e.get("x"),
            "yMm": e.get("y"),
        }
        for e in raw.get("equipment", [])
        if any(
            tag in str(e.get("kind", "")).lower()
            for tag in ("fire", "sprink", "alarm", "hydrant", "pump")
        )
    ]
    return result(
        summary={"annotationCount": len(equipment), "fireStoryCount": len(fire.get("stories", []))},
        tables=[
            table(
                "Fire plan annotation data",
                [
                    ("id", "Tag"),
                    ("kind", "Equipment"),
                    ("story", "Story"),
                    ("xMm", "X", "mm"),
                    ("yMm", "Y", "mm"),
                ],
                equipment,
            )
        ],
        notes=[
            "Coordinates are plan annotation data from the project; no drawing file is written or geometry inferred."
        ],
    )


@feature("mepFire.hydraulicSummary", "Hydraulic Summary", part="mep", requires_project=True)
def hydraulic_summary(ctx: FeatureContext, values: dict) -> dict:
    """Summarize fire hydraulic results from the project's fire model."""
    raw, _ = _raw_fire(ctx)
    from saengine.fire.report import fire_results
    from saengine.library.mep import parse

    data = fire_results(parse(json.dumps(raw)))
    rows = [
        {
            "section": name,
            "recordCount": len(value) if isinstance(value, list) else int(bool(value)),
        }
        for name, value in data.items()
    ]
    if not rows:
        raise FeatureInputError("The project fire model has no hydraulic results to summarize.")
    return result(
        summary={
            "resultSections": len(rows),
            "recordCount": sum(row["recordCount"] for row in rows),
        },
        tables=[
            table(
                "Fire hydraulic report sections",
                [("section", "Section"), ("recordCount", "Records")],
                rows,
            )
        ],
        notes=[
            "Summary uses the existing fire report calculation; missing pressure, flow or geometry inputs are reported by that calculation."
        ],
    )


@feature("mepFire.equipmentList", "Equipment List", part="mep", requires_project=True)
def equipment_list(ctx: FeatureContext, values: dict) -> dict:
    """List fire equipment records and their project ratings."""
    raw, _ = _raw_fire(ctx)
    rows = [
        {
            "id": e.get("id", ""),
            "kind": e.get("kind", ""),
            "story": e.get("story", ""),
            "rating": e.get("rating", e.get("capacity", "")),
        }
        for e in raw.get("equipment", [])
        if any(
            tag in str(e.get("kind", "")).lower()
            for tag in ("fire", "sprink", "alarm", "hydrant", "pump", "extinguisher")
        )
    ]
    if not rows:
        raise FeatureInputError("Add rated fire equipment to the project equipment list first.")
    return result(
        summary={
            "fireEquipmentCount": len(rows),
            "ratedItemCount": sum(bool(row["rating"]) for row in rows),
        },
        tables=[
            table(
                "Fire equipment schedule",
                [
                    ("id", "Tag"),
                    ("kind", "Equipment type"),
                    ("story", "Story"),
                    ("rating", "Duty or rating"),
                ],
                rows,
            )
        ],
        notes=[
            "Items and ratings are read from project equipment data; fire accessories not modeled as equipment are excluded."
        ],
    )
