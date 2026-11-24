"""Project Settings - Loads: Live Load Tables tab: occupancy, storage, equipment, partitions, assembly, roof live."""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context
from saengine.features import (
    FeatureContext,
    feature,
    number,
    result,
    select,
    table,
)
from saengine.features.settings_common import active_pack, load_settings, safe_table
from saengine.report.clauses import in_force


@feature(
    "settingsLoadsLiveTables.occupancyLoad",
    "Occupancy Load",
    part="settings",
    fields=[],
    requires_project=False,
)
def occupancy_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List floor live loads per occupancy use from the active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        uses = getattr(safe_table(pack, "areaLoads"), "uses", None) or {}
    rows = [
        {
            "use": k,
            "name": v.name,
            "liveKnPerM2": v.live,
            "reducible": getattr(v, "reducible", True),
        }
        for k, v in list(uses.items())[:25]
    ]
    return result(
        summary={"useCount": len(uses), "packId": pack.id},
        tables=[
            table(
                "Code pack occupancy live loads",
                [
                    ("use", "Key"),
                    ("name", "Occupancy"),
                    ("liveKnPerM2", "Live", "kN/m²"),
                    ("reducible", "Reducible"),
                ],
                rows,
            )
        ],
        notes=[f"Read from {code_context.code_name(pack)} areaLoads.uses."],
    )


@feature(
    "settingsLoadsLiveTables.useCategory",
    "Use Category",
    part="settings",
    fields=[],
    requires_project=False,
)
def use_category(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Inspect floor and roof area-load assignments configured in project settings."""
    st = load_settings(ctx)
    rows = [
        {
            "id": a.id,
            "name": a.name,
            "use": a.use,
            "liveKnPerM2": a.live,
            "role": "Floor"
            if a.id == st.floorLoad
            else ("Roof" if a.id == st.roofLoad else "Space"),
        }
        for a in st.areaLoads
    ]
    return result(
        summary={"areaCount": len(rows), "floorLoadId": st.floorLoad, "roofLoadId": st.roofLoad},
        tables=[
            table(
                "Project area use assignments",
                [
                    ("id", "ID"),
                    ("name", "Name"),
                    ("use", "Code use"),
                    ("liveKnPerM2", "Live", "kN/m²"),
                    ("role", "Role"),
                ],
                rows,
            )
        ],
        notes=["Floor and roof defaults reference entries in areaLoads."],
    )


@feature(
    "settingsLoadsLiveTables.loadReduction",
    "Load Reduction",
    part="settings",
    fields=[
        number("tributaryM2", "Member tributary area At", 45.0, unit="m²", min=1.0),
        number("kll", "Influence area factor KLL", 4.0, min=1.0, max=4.0),
        number("l0Kpa", "Unreduced live load L0", 2.5, unit="kN/m²", min=0.5),
    ],
    requires_project=False,
)
def ll_load_reduction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute reduced live load using active pack influence-area reduction parameters."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        lr = safe_table(pack, "liveReduction")
        c0 = float(getattr(lr, "constant", 0.25) or 0.25)
        c1 = float(getattr(lr, "coefficient", 4.57) or 4.57)
        inf_min = float(getattr(lr, "influenceMin", 37.16) or 37.16)
    ai = values["tributaryM2"] * values["kll"]
    fac = 1.0 if ai < inf_min else min(1.0, max(0.4, c0 + c1 / math.sqrt(ai)))
    return result(
        summary={
            "influenceAreaM2": ai,
            "reductionFactor": fac,
            "reducedLiveKpa": values["l0Kpa"] * fac,
        },
        tables=[
            table(
                "Live load reduction",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Influence area KLL·At [m²]", "value": ai},
                    {"metric": "Factor L / L0", "value": fac},
                    {"metric": "Reduced L [kN/m²]", "value": values["l0Kpa"] * fac},
                ],
            )
        ],
        notes=["Uses active code pack liveReduction coefficients."],
    )


@feature(
    "settingsLoadsLiveTables.applyOccupancy",
    "Apply Occupancy",
    part="settings",
    fields=[],
    requires_project=False,
)
def apply_occupancy(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sync project areaLoads live values against the active code pack's minimum table."""
    st = load_settings(ctx)
    from saengine.library.settings import area_loads_from_pack

    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        updated, changed = area_loads_from_pack(st, pack)
    rows = [
        {"id": a.id, "use": a.use, "liveKnPerM2": a.live, "updated": a.id in changed}
        for a in updated
    ]
    return result(
        summary={"areaCount": len(rows), "changedCount": len(changed)},
        tables=[
            table(
                "Area loads synced to active pack",
                [
                    ("id", "ID"),
                    ("use", "Use"),
                    ("liveKnPerM2", "Pack live", "kN/m²"),
                    ("updated", "Changed"),
                ],
                rows,
            )
        ],
        notes=["Checked via saengine.library.settings.area_loads_from_pack."],
    )


@feature(
    "settingsLoadsLiveTables.storageLoad",
    "Storage Load",
    part="settings",
    fields=[
        select(
            "duty",
            "Storage duty class",
            [
                ("light", "Light storage (6.0 kN/m²)"),
                ("medium", "General warehouse (12.0 kN/m²)"),
                ("heavy", "Heavy industrial (24.0 kN/m²)"),
            ],
            "medium",
        ),
    ],
    requires_project=False,
)
def ll_storage_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Retrieve standard light, medium, and heavy storage design floor loads."""
    vals = {"light": 6.0, "medium": 12.0, "heavy": 24.0}
    w = vals[values["duty"]]
    return result(
        summary={"storageClass": values["duty"], "liveLoadKpa": w},
        tables=[
            table(
                "Storage live load presets",
                [("duty", "Duty class"), ("kpa", "Live load", "kN/m²")],
                [{"duty": k, "kpa": v} for k, v in vals.items()],
            )
        ],
        notes=[
            "Heavy storage loads (> 4.8 kN/m²) are generally excluded from single-floor reduction."
        ],
    )


@feature(
    "settingsLoadsLiveTables.rackLoad",
    "Rack Load",
    part="settings",
    fields=[
        number("palletWeightKn", "Single loaded pallet weight", 12.0, unit="kN", min=1.0),
        number("levels", "Number of rack beam levels", 4.0, min=1.0, max=12.0),
        number("palletsPerBay", "Pallets per bay per level", 2.0, min=1.0, max=6.0),
    ],
    requires_project=False,
)
def rack_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute upright frame leg reaction from multi-tier pallet racking."""
    total_bay = values["palletWeightKn"] * int(values["levels"]) * int(values["palletsPerBay"])
    per_leg = total_bay / 4.0  # shared by 4 upright posts per bay
    return result(
        summary={"totalBayLoadKn": total_bay, "postLoadKn": per_leg},
        tables=[
            table(
                "Pallet rack upright load",
                [("item", "Item"), ("kn", "Load", "kN")],
                [
                    {"item": "Total bay load", "kn": total_bay},
                    {"item": "Post reaction (4 posts/bay)", "kn": per_leg},
                ],
            )
        ],
        notes=[
            "Interior shared uprights carry contributions from two adjacent bays (2 × postLoad)."
        ],
    )


@feature(
    "settingsLoadsLiveTables.heightFactor",
    "Height Factor",
    part="settings",
    fields=[
        number("stackHeightM", "Clear storage stacking height", 4.5, unit="m", min=1.0),
        number("baseHeightM", "Reference stacking height", 3.0, unit="m", min=1.0),
        number("baseLoadKpa", "Base storage UDL", 12.0, unit="kN/m²", min=1.0),
    ],
    requires_project=False,
)
def height_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Scale warehouse storage live load proportionally for tall stacking heights."""
    factor = max(1.0, values["stackHeightM"] / values["baseHeightM"])
    scaled = values["baseLoadKpa"] * factor
    return result(
        summary={"heightFactor": factor, "scaledStorageKpa": scaled},
        tables=[
            table(
                "Storage height scaling",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Height factor H/H0", "value": factor},
                    {"item": "Scaled live load [kN/m²]", "value": scaled},
                ],
            )
        ],
        notes=["Accounts for vertical stacking beyond standard 3.0 m reference storage."],
    )


@feature(
    "settingsLoadsLiveTables.applyStorage",
    "Apply Storage",
    part="settings",
    fields=[
        number("storageKpa", "Design storage floor load", 12.0, unit="kN/m²", min=2.0),
    ],
    requires_project=False,
)
def apply_storage(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Validate storage load against heavy-live non-reduction rules in active pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        lr = safe_table(pack, "liveReduction")
        heavy_lim = float(getattr(lr, "heavyLive", 4.8) or 4.8)
    exceeds = values["storageKpa"] > heavy_lim
    return result(
        summary={
            "storageKpa": values["storageKpa"],
            "heavyLiveThresholdKpa": heavy_lim,
            "nonReducibleSingleFloor": exceeds,
        },
        tables=[
            table(
                "Storage load reduction check",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Storage load [kN/m²]", "value": values["storageKpa"]},
                    {"item": "Code heavy-live limit [kN/m²]", "value": heavy_lim},
                ],
            )
        ],
        notes=["Loads above heavyLive threshold cannot be reduced on one-floor members."],
    )


@feature(
    "settingsLoadsLiveTables.equipmentLoad",
    "Equipment Load",
    part="settings",
    fields=[
        number("operatingWeightKn", "Equipment operating weight", 45.0, unit="kN", min=1.0),
        number("skidAreaM2", "Equipment plinth footprint area", 6.0, unit="m²", min=0.5),
        number("vibrationFactor", "Rotating equipment dynamic factor", 1.25, min=1.0, max=2.0),
    ],
    requires_project=False,
)
def equipment_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Convert mechanical equipment operating weight into equivalent static & dynamic area pressure."""
    static_kpa = values["operatingWeightKn"] / values["skidAreaM2"]
    dyn_kpa = static_kpa * values["vibrationFactor"]
    return result(
        summary={"staticFootprintKpa": static_kpa, "dynamicFootprintKpa": dyn_kpa},
        tables=[
            table(
                "Mechanical equipment load",
                [("mode", "Mode"), ("kpa", "Pressure", "kN/m²")],
                [
                    {"mode": "Static operating", "kpa": static_kpa},
                    {"mode": "With dynamic factor", "kpa": dyn_kpa},
                ],
            )
        ],
        notes=["Use wet/operating weight including contained fluid."],
    )


@feature(
    "settingsLoadsLiveTables.pointLoad",
    "Point Load",
    part="settings",
    fields=[
        number("totalWeightKn", "Total equipment weight", 40.0, unit="kN", min=1.0),
        number("supportCount", "Number of mounting feet/isolators", 4.0, min=2.0, max=16.0),
    ],
    requires_project=False,
)
def point_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute concentrated reaction per equipment mounting foot."""
    per_foot = values["totalWeightKn"] / int(values["supportCount"])
    return result(
        summary={"supportCount": int(values["supportCount"]), "loadPerSupportKn": per_foot},
        tables=[
            table(
                "Equipment point loads",
                [("totalKn", "Total", "kN"), ("supports", "Feet"), ("perFootKn", "Per foot", "kN")],
                [
                    {
                        "totalKn": values["totalWeightKn"],
                        "supports": int(values["supportCount"]),
                        "perFootKn": per_foot,
                    }
                ],
            )
        ],
        notes=["Applies concentrated load checks to supporting slab/beams."],
    )


@feature(
    "settingsLoadsLiveTables.areaLoad",
    "Area Load",
    part="settings",
    fields=[
        number("plantAreaM2", "Mechanical plant room area", 80.0, unit="m²", min=5.0),
        number("equipmentIntensityKpa", "Design mechanical room UDL", 7.5, unit="kN/m²", min=1.0),
    ],
    requires_project=False,
)
def area_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute total distributed mechanical room design force."""
    total_kn = values["plantAreaM2"] * values["equipmentIntensityKpa"]
    return result(
        summary={"intensityKpa": values["equipmentIntensityKpa"], "totalRoomForceKn": total_kn},
        tables=[
            table(
                "Plant room distributed load",
                [("areaM2", "Area", "m²"), ("kpa", "UDL", "kN/m²"), ("totalKn", "Total", "kN")],
                [
                    {
                        "areaM2": values["plantAreaM2"],
                        "kpa": values["equipmentIntensityKpa"],
                        "totalKn": total_kn,
                    }
                ],
            )
        ],
        notes=[
            "Typical plant rooms use 5.0-10.0 kN/m² UDL plus local heavy chiller/transformer pads."
        ],
    )


@feature(
    "settingsLoadsLiveTables.applyEquipment",
    "Apply Equipment",
    part="settings",
    fields=[
        number("equipmentKpa", "Adopted mechanical area load", 7.5, unit="kN/m²", min=1.0),
    ],
    requires_project=False,
)
def apply_equipment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify mechanical area load against active pack seismic weight share."""
    st = load_settings(ctx)
    from saengine.library.settings import seismic_weight_rule

    with in_force(ctx.root, st):
        rule = seismic_weight_rule(st)
        share = rule.live(values["equipmentKpa"], "mechanical")
    return result(
        summary={
            "equipmentKpa": values["equipmentKpa"],
            "seismicMassShare": share,
            "seismicLoadKpa": values["equipmentKpa"] * share,
        },
        tables=[
            table(
                "Equipment load seismic mass",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Equipment UDL [kN/m²]", "value": values["equipmentKpa"]},
                    {"item": "Seismic mass share", "value": share},
                ],
            )
        ],
        notes=["Heavy equipment loads often carry full or elevated seismic mass share."],
    )


@feature(
    "settingsLoadsLiveTables.uniformPartition",
    "Uniform Partition",
    part="settings",
    fields=[],
    requires_project=False,
)
def uniform_partition(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Retrieve minimum uniform partition allowance and load case from active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        part = getattr(safe_table(pack, "areaLoads"), "partitions", None)
        min_p = float(getattr(part, "minimum", 1.0) or 1.0)
        lcase = str(getattr(part, "loadCase", "L") or "L")
    return result(
        summary={"minimumPartitionKpa": min_p, "packLoadCase": lcase},
        tables=[
            table(
                "Uniform partition allowance",
                [("rule", "Rule"), ("value", "Value")],
                [
                    {"rule": "Minimum UDL [kN/m²]", "value": str(min_p)},
                    {"rule": "Default load case", "value": lcase},
                ],
            )
        ],
        notes=["Read from active code pack areaLoads.partitions."],
    )


@feature(
    "settingsLoadsLiveTables.movablePartition",
    "Movable Partition",
    part="settings",
    fields=[
        number("lineWeightKnPerM", "Demountable partition line weight", 2.0, unit="kN/m", min=0.2),
        number("wallHeightM", "Partition height", 3.0, unit="m", min=1.5),
    ],
    requires_project=False,
)
def movable_partition(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check movable partition line load against light-partition UDL substitution limit."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        part = getattr(safe_table(pack, "areaLoads"), "partitions", None)
        light_max = float(getattr(part, "lightMax", 5.5) or 5.5)
        share = float(getattr(part, "share", 0.33) or 0.33)
    eq_udl = values["lineWeightKnPerM"] * share
    eligible = values["lineWeightKnPerM"] <= light_max
    return result(
        summary={
            "lineWeightKnPerM": values["lineWeightKnPerM"],
            "equivalentUdlKpa": eq_udl,
            "eligibleForUdl": eligible,
        },
        tables=[
            table(
                "Movable partition check",
                [("metric", "Metric"), ("value", "Value")],
                [
                    {"metric": "Equivalent UDL [kN/m²]", "value": eq_udl},
                    {"metric": "Pack lightMax [kN/m]", "value": light_max},
                    {"metric": "UDL allowed", "value": float(eligible)},
                ],
            )
        ],
        notes=["Walls heavier than lightMax must be modelled explicitly as line loads."],
    )


@feature(
    "settingsLoadsLiveTables.heavyPartition",
    "Heavy Partition",
    part="settings",
    fields=[
        number("wallThicknessMm", "Masonry wall thickness", 125.0, unit="mm", min=75.0),
        number("wallHeightM", "Clear wall height", 3.0, unit="m", min=1.5),
        number(
            "masonryUnitWeightKnM3", "Masonry + plaster unit weight", 20.0, unit="kN/m³", min=10.0
        ),
    ],
    requires_project=False,
)
def heavy_partition(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute heavy masonry partition line load per metre run of wall."""
    line_kn_m = (
        (values["wallThicknessMm"] / 1000.0)
        * values["wallHeightM"]
        * values["masonryUnitWeightKnM3"]
    )
    return result(
        summary={"wallLineLoadKnPerM": line_kn_m},
        tables=[
            table(
                "Heavy masonry partition line load",
                [
                    ("thicknessMm", "Thickness", "mm"),
                    ("heightM", "Height", "m"),
                    ("lineKnPerM", "Line load", "kN/m"),
                ],
                [
                    {
                        "thicknessMm": values["wallThicknessMm"],
                        "heightM": values["wallHeightM"],
                        "lineKnPerM": line_kn_m,
                    }
                ],
            )
        ],
        notes=["Heavy masonry walls should be applied as explicit beam/slab line loads."],
    )


@feature(
    "settingsLoadsLiveTables.partitionReserve",
    "Partition Reserve",
    part="settings",
    fields=[
        number("reserveKpa", "Future layout-change partition reserve", 0.5, unit="kN/m²", min=0.0),
        number("baseFloorFinishKpa", "Current finishes SD", 1.2, unit="kN/m²", min=0.0),
    ],
    requires_project=False,
)
def partition_reserve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Add future partition flexibility reserve to superimposed dead/live allowance."""
    tot = values["baseFloorFinishKpa"] + values["reserveKpa"]
    return result(
        summary={"reserveKpa": values["reserveKpa"], "totalAllowanceKpa": tot},
        tables=[
            table(
                "Partition flexibility reserve",
                [("item", "Item"), ("kpa", "Load", "kN/m²")],
                [
                    {"item": "Base finishes", "kpa": values["baseFloorFinishKpa"]},
                    {"item": "Future partition reserve", "kpa": values["reserveKpa"]},
                    {"item": "Combined allowance", "kpa": tot},
                ],
            )
        ],
        notes=["Protects open-plan office slabs against future fit-out changes."],
    )


@feature(
    "settingsLoadsLiveTables.crowdLoad",
    "Crowd Load",
    part="settings",
    fields=[
        number("crowdDensityPerM2", "Peak crowd density", 4.0, unit="persons/m²", min=0.5, max=7.0),
        number("personWeightKn", "Mean occupant weight", 0.75, unit="kN", min=0.5),
    ],
    requires_project=False,
)
def crowd_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute static crowd pressure from occupant density in public assembly areas."""
    kpa = values["crowdDensityPerM2"] * values["personWeightKn"]
    return result(
        summary={"crowdLoadKpa": kpa, "densityPerM2": values["crowdDensityPerM2"]},
        tables=[
            table(
                "Dense crowd static pressure",
                [("density", "Persons/m²"), ("kpa", "Pressure", "kN/m²")],
                [{"density": values["crowdDensityPerM2"], "kpa": kpa}],
            )
        ],
        notes=["4-6 persons/m² represents dense standing crowd conditions."],
    )


@feature(
    "settingsLoadsLiveTables.grandstandImpact",
    "Grandstand Impact",
    part="settings",
    fields=[
        number("verticalCrowdKpa", "Static vertical seating load", 4.8, unit="kN/m²", min=1.0),
        number("swayShare", "Horizontal rhythmic swaying share", 0.10, min=0.05, max=0.25),
    ],
    requires_project=False,
)
def grandstand_impact(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute horizontal rhythmic swaying force on stadium grandstand tiers."""
    horiz = values["verticalCrowdKpa"] * values["swayShare"]
    return result(
        summary={"verticalKpa": values["verticalCrowdKpa"], "horizontalSwayKpa": horiz},
        tables=[
            table(
                "Grandstand crowd swaying force",
                [("component", "Component"), ("kpa", "Load", "kN/m²")],
                [
                    {"component": "Vertical seating", "kpa": values["verticalCrowdKpa"]},
                    {"component": "Horizontal rhythmic sway", "kpa": horiz},
                ],
            )
        ],
        notes=["Horizontal spectator swaying acts concurrently with vertical assembly live load."],
    )


@feature(
    "settingsLoadsLiveTables.danceFloorLoad",
    "Dance Floor Load",
    part="settings",
    fields=[
        number("staticLiveKpa", "Static floor live load", 4.8, unit="kN/m²", min=1.0),
        number("dynamicMultiplier", "Jumping/dancing dynamic load factor", 1.7, min=1.2, max=2.5),
    ],
    requires_project=False,
)
def dance_floor_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute equivalent static load for rhythmic dancing and gymnasium floors."""
    eff = values["staticLiveKpa"] * values["dynamicMultiplier"]
    return result(
        summary={"staticKpa": values["staticLiveKpa"], "equivalentDynamicKpa": eff},
        tables=[
            table(
                "Rhythmic assembly floor load",
                [("mode", "Mode"), ("kpa", "Load", "kN/m²")],
                [
                    {"mode": "Static", "kpa": values["staticLiveKpa"]},
                    {"mode": "With rhythmic DLF", "kpa": eff},
                ],
            )
        ],
        notes=["Verify fundamental vertical frequency >= 8.4 Hz to avoid resonant amplification."],
    )


@feature(
    "settingsLoadsLiveTables.assemblyFactor",
    "Assembly Factor",
    part="settings",
    fields=[
        number("assemblyLiveKpa", "Assembly live load L0", 4.8, unit="kN/m²", min=1.0),
    ],
    requires_project=False,
)
def assembly_factor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Verify assembly live load non-reduction ceiling against active code pack."""
    st = load_settings(ctx)
    with in_force(ctx.root, st):
        pack = active_pack(ctx, st)
        lr = safe_table(pack, "liveReduction")
        cap = float(getattr(lr, "assemblyMax", 4.8) or 4.8)
    reducible = values["assemblyLiveKpa"] > cap
    return result(
        summary={
            "assemblyLiveKpa": values["assemblyLiveKpa"],
            "assemblyCapKpa": cap,
            "reducible": reducible,
        },
        tables=[
            table(
                "Assembly reduction eligibility",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Assembly L0 [kN/m²]", "value": values["assemblyLiveKpa"]},
                    {"item": "Pack assembly non-reduction cap [kN/m²]", "value": cap},
                ],
            )
        ],
        notes=["Public assembly loads up to assemblyMax are never reduced."],
    )


@feature(
    "settingsLoadsLiveTables.maintenanceLoad",
    "Maintenance Load",
    part="settings",
    fields=[
        number("concentratedKn", "Concentrated roof access load", 1.5, unit="kN", min=0.5),
        number("uniformMinKpa", "Distributed roof maintenance UDL", 0.75, unit="kN/m²", min=0.25),
    ],
    requires_project=False,
)
def maintenance_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Define non-accessible roof maintenance point and distributed live loads."""
    return result(
        summary={
            "pointLoadKn": values["concentratedKn"],
            "distributedKpa": values["uniformMinKpa"],
        },
        tables=[
            table(
                "Roof maintenance loads",
                [("load", "Load"), ("value", "Value")],
                [
                    {"load": "Concentrated point [kN]", "value": values["concentratedKn"]},
                    {"load": "Minimum UDL [kN/m²]", "value": values["uniformMinKpa"]},
                ],
            )
        ],
        notes=["Applied separately to purlins/sheeting for local bending checks."],
    )


@feature(
    "settingsLoadsLiveTables.accessibleRoof",
    "Accessible Roof",
    part="settings",
    fields=[
        number(
            "terraceLiveKpa", "Accessible roof / promenade live load", 4.8, unit="kN/m²", min=1.5
        ),
        number("paverToppingKpa", "Pedestal paver & bedding SD", 1.8, unit="kN/m²", min=0.0),
    ],
    requires_project=False,
)
def accessible_roof(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Combine accessible roof terrace live load and paver superimposed dead load."""
    tot = values["terraceLiveKpa"] + values["paverToppingKpa"]
    return result(
        summary={
            "terraceLiveKpa": values["terraceLiveKpa"],
            "paverDeadKpa": values["paverToppingKpa"],
            "totalUnfactoredKpa": tot,
        },
        tables=[
            table(
                "Accessible roof terrace loads",
                [("item", "Item"), ("kpa", "Load", "kN/m²")],
                [
                    {"item": "Terrace live load", "kpa": values["terraceLiveKpa"]},
                    {"item": "Pavers & bedding SD", "kpa": values["paverToppingKpa"]},
                ],
            )
        ],
        notes=["Accessible roof terraces take floor-equivalent occupancy live loads."],
    )


@feature(
    "settingsLoadsLiveTables.greenRoofLoad",
    "Green Roof Load",
    part="settings",
    fields=[
        number("soilDepthMm", "Growing medium depth", 300.0, unit="mm", min=50.0),
        number(
            "satUnitWeightKnM3",
            "Saturated soil + drainage unit weight",
            18.0,
            unit="kN/m³",
            min=10.0,
        ),
        number("vegetationKpa", "Planting & retention mat allowance", 0.5, unit="kN/m²", min=0.0),
    ],
    requires_project=False,
)
def green_roof_load(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate saturated vegetated green-roof dead load per m²."""
    soil_kpa = (values["soilDepthMm"] / 1000.0) * values["satUnitWeightKnM3"]
    tot = soil_kpa + values["vegetationKpa"]
    return result(
        summary={"saturatedSoilKpa": soil_kpa, "totalGreenRoofDeadKpa": tot},
        tables=[
            table(
                "Green roof dead load",
                [("layer", "Layer"), ("kpa", "Load", "kN/m²")],
                [
                    {"layer": "Saturated growing medium", "kpa": soil_kpa},
                    {"layer": "Vegetation & drainage", "kpa": values["vegetationKpa"]},
                    {"layer": "Total green roof SD", "kpa": tot},
                ],
            )
        ],
        notes=["Evaluated at full field saturation for dead load design."],
    )


@feature(
    "settingsLoadsLiveTables.solarPanelWeight",
    "Solar Panel Weight",
    part="settings",
    fields=[
        number("moduleKpa", "PV array & racking weight", 0.22, unit="kN/m²", min=0.05),
        number("ballastKpa", "Wind-uplift ballast blocks", 0.45, unit="kN/m²", min=0.0),
    ],
    requires_project=False,
)
def solar_panel_weight(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute rooftop photovoltaic array + ballast superimposed dead load."""
    tot = values["moduleKpa"] + values["ballastKpa"]
    return result(
        summary={
            "arrayWeightKpa": values["moduleKpa"],
            "ballastKpa": values["ballastKpa"],
            "totalSolarSdKpa": tot,
        },
        tables=[
            table(
                "Rooftop solar array load",
                [("component", "Component"), ("kpa", "Load", "kN/m²")],
                [
                    {"component": "Panels & racking", "kpa": values["moduleKpa"]},
                    {"component": "Ballast", "kpa": values["ballastKpa"]},
                    {"component": "Total solar SD", "kpa": tot},
                ],
            )
        ],
        notes=["Include wind uplift check on ballasted frames when unanchored."],
    )
