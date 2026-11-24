"""Fire-alarm zoning, loop loading and notification coverage."""

from __future__ import annotations

import math

from saengine.features import FeatureContext, feature, number, result, select, table, text


@feature(
    "mepFireAlarmZoning.createZone",
    "Create Zone",
    part="mep",
    fields=[
        text("zoneId", "Zone ID", "Z-01"),
        number("floorAreaM2", "Zone floor area", 500, unit="m²", min=0),
        number("deviceCount", "Device count", 20, min=0),
    ],
    requires_project=False,
)
def create_zone(ctx: FeatureContext, v: dict) -> dict:
    """Summarize an entered detection zone and its device density."""
    density = v["deviceCount"] / v["floorAreaM2"] if v["floorAreaM2"] else 0
    return result(
        {"zoneId": v["zoneId"], "deviceCount": int(v["deviceCount"]), "deviceDensityPerM2": density}
    )


@feature(
    "mepFireAlarmZoning.zoneBoundary",
    "Zone Boundary",
    part="mep",
    fields=[
        number("lengthM", "Boundary length", 40, unit="m", min=0),
        number("widthM", "Boundary width", 25, unit="m", min=0),
    ],
    requires_project=False,
)
def zone_boundary(ctx: FeatureContext, v: dict) -> dict:
    """Calculate area and perimeter for a rectangular detection-zone boundary."""
    return result(
        {
            "boundaryAreaM2": v["lengthM"] * v["widthM"],
            "boundaryPerimeterM": 2 * (v["lengthM"] + v["widthM"]),
        }
    )


@feature(
    "mepFireAlarmZoning.zoneAddress",
    "Zone Address",
    part="mep",
    fields=[
        number("loopNumber", "Loop number", 1, min=1),
        number("firstAddress", "First address", 1, min=1),
        number("deviceCount", "Device count", 12, min=0),
        number("addressCapacity", "Loop address capacity", 127, min=1),
    ],
    requires_project=False,
)
def zone_address(ctx: FeatureContext, v: dict) -> dict:
    """Check that the zone's device addresses fit within loop capacity."""
    last = v["firstAddress"] + v["deviceCount"] - 1
    return result(
        {
            "loopNumber": int(v["loopNumber"]),
            "firstAddress": int(v["firstAddress"]),
            "lastAddress": int(last),
            "capacityPass": last <= v["addressCapacity"],
        }
    )


@feature(
    "mepFireAlarmZoning.zoneLabel",
    "Zone Label",
    part="mep",
    fields=[
        text("zoneId", "Zone ID", "Z-01"),
        text("zoneName", "Zone name", "Level 1 east"),
        text("panelName", "Panel name", "FACP-1"),
    ],
    requires_project=False,
)
def zone_label(ctx: FeatureContext, v: dict) -> dict:
    """Prepare a uniquely labelled zone record for panel schedules."""
    return result(
        {"zoneId": v["zoneId"], "zoneName": v["zoneName"], "panelName": v["panelName"]},
        [
            table(
                "Zone identification",
                [("field", "Field"), ("value", "Value")],
                [
                    {"field": "Zone", "value": v["zoneId"]},
                    {"field": "Name", "value": v["zoneName"]},
                    {"field": "Panel", "value": v["panelName"]},
                ],
            )
        ],
    )


@feature(
    "mepFireAlarmZoning.placeDetector",
    "Place Detector",
    part="mep",
    fields=[
        number("roomLengthM", "Room length", 10, unit="m", min=0.1),
        number("roomWidthM", "Room width", 8, unit="m", min=0.1),
        number("coverageDiameterM", "Detector coverage diameter", 10, unit="m", min=0.1),
        select("type", "Detector type", ["smoke", "heat"]),
    ],
    requires_project=False,
)
def place_detector(ctx: FeatureContext, v: dict) -> dict:
    """Estimate detector count by room area and a circular coverage basis."""
    count = math.ceil(
        v["roomLengthM"] * v["roomWidthM"] / (math.pi * (v["coverageDiameterM"] / 2) ** 2)
    )
    return result(
        {"detectorCountEstimate": count, "type": v["type"]},
        notes=[
            "Area-based estimate only; ceiling geometry, beams, airflow and spacing limitations require a layout check."
        ],
    )


@feature(
    "mepFireAlarmZoning.placeSounder",
    "Place Sounder",
    part="mep",
    fields=[
        number("roomAreaM2", "Room area", 100, unit="m²", min=0),
        number("coveragePerSounderM2", "Design coverage per sounder", 80, unit="m²", min=0.1),
        number("sounderCount", "Installed sounders", 2, min=0),
    ],
    requires_project=False,
)
def place_sounder(ctx: FeatureContext, v: dict) -> dict:
    """Estimate sounder quantity from entered area and coverage criterion."""
    required = math.ceil(v["roomAreaM2"] / v["coveragePerSounderM2"])
    return result(
        {
            "requiredCount": required,
            "installedCount": int(v["sounderCount"]),
            "quantityPass": v["sounderCount"] >= required,
        },
        notes=[
            "Area coverage is not an audibility calculation; verify sound levels at occupied positions."
        ],
    )


@feature(
    "mepFireAlarmZoning.callPoint",
    "Call Point",
    part="mep",
    fields=[
        number("escapeRouteLengthM", "Escape route length", 45, unit="m", min=0),
        number("maximumTravelM", "Maximum approach distance", 30, unit="m", min=0.1),
    ],
    requires_project=False,
)
def call_point(ctx: FeatureContext, v: dict) -> dict:
    """Estimate call-point quantity along a linear escape route."""
    return result(
        {"callPointCount": max(1, math.ceil(v["escapeRouteLengthM"] / v["maximumTravelM"]))},
        notes=[
            "Linear route spacing estimate; exits, doors and final approach distances must be checked on the plan."
        ],
    )


@feature(
    "mepFireAlarmZoning.interfaceModule",
    "Interface Module",
    part="mep",
    fields=[
        text("moduleTag", "Module tag", "IM-01"),
        select("interface", "Interface type", ["monitor", "control", "isolator"]),
        number("loadMa", "Connected loop load", 1, unit="mA", min=0),
    ],
    requires_project=False,
)
def interface_module(ctx: FeatureContext, v: dict) -> dict:
    """Record the selected interface-module type and loop current."""
    return result(
        {"moduleTag": v["moduleTag"], "interfaceType": v["interface"], "loopLoadMa": v["loadMa"]}
    )


@feature(
    "mepFireAlarmZoning.causeAndEffect",
    "Cause And Effect",
    part="mep",
    fields=[
        text("initiatingZone", "Initiating zone", "Z-01"),
        text("output", "Output action", "Release doors"),
        select("actionMode", "Action mode", ["activate", "deactivate", "hold"]),
        number("delaySeconds", "Output delay", 0, unit="s", min=0),
    ],
    requires_project=False,
)
def cause_and_effect(ctx: FeatureContext, v: dict) -> dict:
    """Define one cause-and-effect relation for fire-alarm review."""
    return result(
        {
            "initiatingZone": v["initiatingZone"],
            "output": v["output"],
            "actionMode": v["actionMode"],
            "delaySeconds": v["delaySeconds"],
        }
    )


@feature(
    "mepFireAlarmZoning.logicRules",
    "Logic Rules",
    part="mep",
    fields=[
        number("inputA", "Input A state", 1, min=0, max=1),
        number("inputB", "Input B state", 0, min=0, max=1),
        select("operator", "Logic operator", ["AND", "OR"]),
    ],
    requires_project=False,
)
def logic_rules(ctx: FeatureContext, v: dict) -> dict:
    """Evaluate a two-input AND or OR fire-alarm logic expression."""
    state = (
        bool(v["inputA"]) and bool(v["inputB"])
        if v["operator"] == "AND"
        else bool(v["inputA"]) or bool(v["inputB"])
    )
    return result(
        {
            "inputA": bool(v["inputA"]),
            "inputB": bool(v["inputB"]),
            "operator": v["operator"],
            "output": state,
        }
    )


@feature(
    "mepFireAlarmZoning.testMatrix",
    "Test Matrix",
    part="mep",
    fields=[
        number("initiatingInput", "Initiating input", 1, min=0, max=1),
        number("expectedOutput", "Expected output", 1, min=0, max=1),
        number("simulatedOutput", "Simulated output", 1, min=0, max=1),
    ],
    requires_project=False,
)
def test_matrix(ctx: FeatureContext, v: dict) -> dict:
    """Compare a simulated cause-and-effect result with the expected output."""
    return result(
        {
            "initiatingInput": bool(v["initiatingInput"]),
            "expectedOutput": bool(v["expectedOutput"]),
            "simulatedOutput": bool(v["simulatedOutput"]),
            "pass": bool(v["expectedOutput"]) == bool(v["simulatedOutput"]),
        }
    )


@feature(
    "mepFireAlarmZoning.matrixReport",
    "Matrix Report",
    part="mep",
    fields=[
        text("system", "Fire system", "Detection"),
        number("inputCount", "Input count", 8, min=0),
        number("outputCount", "Output count", 12, min=0),
    ],
    requires_project=False,
)
def matrix_report(ctx: FeatureContext, v: dict) -> dict:
    """Summarize the cause-and-effect matrix dimensions for reporting."""
    return result(
        {"system": v["system"], "matrixCellCount": int(v["inputCount"] * v["outputCount"])},
        [
            table(
                "Matrix dimensions",
                [("item", "Item"), ("count", "Count")],
                [
                    {"item": "Inputs", "count": int(v["inputCount"])},
                    {"item": "Outputs", "count": int(v["outputCount"])},
                    {
                        "item": "Possible relationships",
                        "count": int(v["inputCount"] * v["outputCount"]),
                    },
                ],
            )
        ],
    )


@feature(
    "mepFireAlarmZoning.loopLoadCalculation",
    "Loop Load Calculation",
    part="mep",
    fields=[
        number("deviceCount", "Device count", 30, min=0),
        number("standbyMa", "Standby current per device", 0.3, unit="mA", min=0),
        number("alarmMa", "Alarm current per device", 5, unit="mA", min=0),
        number("loopCapacityMa", "Loop current capacity", 500, unit="mA", min=0.1),
    ],
    requires_project=False,
)
def loop_load_calculation(ctx: FeatureContext, v: dict) -> dict:
    """Calculate standby and alarm current against the entered loop capacity."""
    standby, alarm = v["deviceCount"] * v["standbyMa"], v["deviceCount"] * v["alarmMa"]
    return result(
        {
            "standbyLoadMa": standby,
            "alarmLoadMa": alarm,
            "alarmCapacityPass": alarm <= v["loopCapacityMa"],
            "loopCapacityMa": v["loopCapacityMa"],
        }
    )


@feature(
    "mepFireAlarmZoning.isolatorLocation",
    "Isolator Location",
    part="mep",
    fields=[
        number("loopDeviceCount", "Loop device count", 60, min=0),
        number("devicesPerSection", "Devices per protected section", 20, min=1),
    ],
    requires_project=False,
)
def isolator_location(ctx: FeatureContext, v: dict) -> dict:
    """Estimate short-circuit isolator count and section device ranges."""
    section = int(v["devicesPerSection"])
    rows = [
        {
            "isolator": i + 1,
            "firstDevice": i * section + 1,
            "lastDevice": min((i + 1) * section, int(v["loopDeviceCount"])),
        }
        for i in range(math.ceil(v["loopDeviceCount"] / section))
    ]
    return result(
        {"isolatorCount": len(rows)},
        [
            table(
                "Loop sections",
                [
                    ("isolator", "Isolator"),
                    ("firstDevice", "First device"),
                    ("lastDevice", "Last device"),
                ],
                rows,
            )
        ],
    )


@feature(
    "mepFireAlarmZoning.voltageDropLoop",
    "Voltage Drop Loop",
    part="mep",
    fields=[
        number("currentA", "Loop current", 0.15, unit="A", min=0),
        number("oneWayLengthM", "One-way cable length", 250, unit="m", min=0),
        number("resistanceOhmPerKm", "Conductor resistance", 18, unit="Ω/km", min=0),
        number("supplyVoltageV", "Supply voltage", 24, unit="V", min=1),
    ],
    requires_project=False,
)
def voltage_drop_loop(ctx: FeatureContext, v: dict) -> dict:
    """Calculate two-wire loop voltage drop and end-of-line voltage."""
    drop = v["currentA"] * 2 * v["oneWayLengthM"] * v["resistanceOhmPerKm"] / 1000
    return result(
        {
            "voltageDropV": drop,
            "endVoltageV": v["supplyVoltageV"] - drop,
            "dropPercent": 100 * drop / v["supplyVoltageV"],
        },
        notes=[
            "Copper-loop resistance uses the entered value; evaluate alarm current and temperature-adjusted resistance for worst case."
        ],
    )


@feature(
    "mepFireAlarmZoning.cableLengthLimit",
    "Cable Length Limit",
    part="mep",
    fields=[
        number("runLengthM", "Installed loop length", 800, unit="m", min=0),
        number("capacitanceNfPerM", "Cable capacitance", 0.08, unit="nF/m", min=0),
        number("maximumCapacitanceNf", "Loop capacitance limit", 100, unit="nF", min=0.1),
    ],
    requires_project=False,
)
def cable_length_limit(ctx: FeatureContext, v: dict) -> dict:
    """Check cable-run capacitance against the selected device loop limit."""
    capacitance = v["runLengthM"] * v["capacitanceNfPerM"]
    return result(
        {
            "estimatedCapacitanceNf": capacitance,
            "maximumCapacitanceNf": v["maximumCapacitanceNf"],
            "pass": capacitance <= v["maximumCapacitanceNf"],
        },
        notes=[
            "Cable-only capacitance estimate; devices, spurs and manufacturer topology limits are not included."
        ],
    )


@feature(
    "mepFireAlarmZoning.soundLevelMapping",
    "Sound Level Mapping",
    part="mep",
    fields=[
        number("sourceDb", "Source sound level", 100, unit="dB", min=0),
        number("distanceM", "Receiver distance", 10, unit="m", min=0.1),
        number("backgroundDb", "Background sound", 55, unit="dB", min=0),
    ],
    requires_project=False,
)
def sound_level_mapping(ctx: FeatureContext, v: dict) -> dict:
    """Estimate sound level with free-field distance loss and logarithmic background."""
    level = v["sourceDb"] - 20 * math.log10(v["distanceM"])
    total = 10 * math.log10(10 ** (level / 10) + 10 ** (v["backgroundDb"] / 10))
    return result(
        {"directSoundLevelDb": level, "combinedSoundLevelDb": total},
        notes=[
            "Point-source free-field estimate; room reverberation, barriers and frequency weighting are excluded."
        ],
    )


@feature(
    "mepFireAlarmZoning.intelligibilityIndex",
    "Intelligibility Index",
    part="mep",
    fields=[
        number("speechLevelDb", "Speech level", 75, unit="dB", min=0),
        number("noiseLevelDb", "Ambient noise", 55, unit="dB", min=0),
        number("reverberationS", "Reverberation time", 1.2, unit="s", min=0),
    ],
    requires_project=False,
)
def intelligibility_index(ctx: FeatureContext, v: dict) -> dict:
    """Calculate a screening speech-to-noise margin and reverberation indicator."""
    margin = v["speechLevelDb"] - v["noiseLevelDb"]
    index = min(1.0, max(0.0, (margin - 3) / 20)) * math.exp(-v["reverberationS"] / 2)
    return result(
        {"speechNoiseMarginDb": margin, "screeningIndex": index},
        notes=[
            "Screening index is not STI; a standards-based speech transmission measurement or validated model is required for acceptance."
        ],
    )


@feature(
    "mepFireAlarmZoning.strobeCoverage",
    "Strobe Coverage",
    part="mep",
    fields=[
        number("roomLengthM", "Room length", 20, unit="m", min=0.1),
        number("roomWidthM", "Room width", 12, unit="m", min=0.1),
        number("coverageRadiusM", "Coverage radius", 8, unit="m", min=0.1),
    ],
    requires_project=False,
)
def strobe_coverage(ctx: FeatureContext, v: dict) -> dict:
    """Estimate visual notification device count by room coverage area."""
    count = math.ceil(v["roomLengthM"] * v["roomWidthM"] / (math.pi * v["coverageRadiusM"] ** 2))
    return result(
        {"strobeCountEstimate": count, "roomAreaM2": v["roomLengthM"] * v["roomWidthM"]},
        notes=[
            "Area estimate only; candela rating, mounting height, obstructions and viewing angles control actual coverage."
        ],
    )


@feature(
    "mepFireAlarmZoning.hvacInterlock",
    "HVAC Interlock",
    part="mep",
    fields=[
        text("zone", "Initiating zone", "Z-01"),
        text("ahuTag", "AHU tag", "AHU-01"),
        select("action", "Interlock action", ["stop", "start smoke control", "close damper"]),
    ],
    requires_project=False,
)
def hvac_interlock(ctx: FeatureContext, v: dict) -> dict:
    """Define one fire-alarm interlock action for an HVAC item."""
    return result({"initiatingZone": v["zone"], "ahuTag": v["ahuTag"], "action": v["action"]})


@feature(
    "mepFireAlarmZoning.elevatorRecall",
    "Elevator Recall",
    part="mep",
    fields=[
        text("elevatorTag", "Elevator tag", "LIFT-01"),
        text("primaryFloor", "Primary recall floor", "Ground"),
        text("alternateFloor", "Alternate recall floor", "Level 1"),
        number("recallTimeS", "Target recall time", 60, unit="s", min=1),
    ],
    requires_project=False,
)
def elevator_recall(ctx: FeatureContext, v: dict) -> dict:
    """Record primary and alternate fire-service elevator recall destinations."""
    return result(
        {
            "elevatorTag": v["elevatorTag"],
            "primaryFloor": v["primaryFloor"],
            "alternateFloor": v["alternateFloor"],
            "targetRecallTimeS": v["recallTimeS"],
        }
    )


@feature(
    "mepFireAlarmZoning.doorReleaseMatrix",
    "Door Release Matrix",
    part="mep",
    fields=[
        text("doorTag", "Door tag", "D-101"),
        text("triggerZone", "Trigger zone", "Z-01"),
        select(
            "releaseMode", "Release mode", ["on alarm", "on power loss", "on alarm or power loss"]
        ),
    ],
    requires_project=False,
)
def door_release_matrix(ctx: FeatureContext, v: dict) -> dict:
    """Define a fire-alarm trigger and fail-safe release mode for a door."""
    return result(
        {"doorTag": v["doorTag"], "triggerZone": v["triggerZone"], "releaseMode": v["releaseMode"]},
        [
            table(
                "Door-release output",
                [("door", "Door"), ("triggerZone", "Trigger zone"), ("releaseMode", "Mode")],
                [
                    {
                        "door": v["doorTag"],
                        "triggerZone": v["triggerZone"],
                        "releaseMode": v["releaseMode"],
                    }
                ],
            )
        ],
    )
