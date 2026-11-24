"""Architecture Envelope - walls, roofs, slabs, glazing and envelope details."""

from __future__ import annotations

import math
from typing import Any

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
from saengine.features.architecture_common import require_arch, write_json


@feature(
    "architectureEnvelope.wallLayers",
    "Wall Layers",
    part="floorPlan",
    fields=[text("wallTypeId", "Wall type id", "")],
)
def wall_layers(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Tabulate wall type layers, thickness and weight."""
    arch = require_arch(ctx)
    rows = []
    for t in arch.wallTypes:
        if values["wallTypeId"] and t.id != values["wallTypeId"]:
            continue
        for k, layer in enumerate(t.layers):
            rows.append(
                {
                    "wallType": t.id,
                    "layer": k + 1,
                    "material": layer.material,
                    "thicknessMm": layer.thickness,
                    "unitWeightKnM3": layer.unitWeight,
                }
            )
    if not rows:
        raise FeatureInputError("No matching wall layers were found.")
    return result(
        summary={"layerCount": len(rows)},
        tables=[
            table(
                "Wall layers",
                [
                    ("wallType", "Wall type"),
                    ("layer", "Layer"),
                    ("material", "Material"),
                    ("thicknessMm", "Thickness", "mm"),
                    ("unitWeightKnM3", "Unit weight", "kN/m³"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureEnvelope.curtainWalls",
    "Curtain Walls",
    part="floorPlan",
    fields=[text("curtainId", "Curtain wall id", "")],
)
def curtain_walls(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """List curtain-wall systems and lengths."""
    arch = require_arch(ctx)
    rows = [
        {
            "id": c.id,
            "type": c.type,
            "lengthM": sum(math.dist(a, b) for a, b in zip(c.path, c.path[1:])) / 1000,
        }
        for c in arch.curtainWalls
        if not values["curtainId"] or c.id == values["curtainId"]
    ]
    if not rows:
        raise FeatureInputError("No matching curtain wall was found.")
    return result(
        summary={"curtainWallCount": len(rows), "totalLengthM": sum(r["lengthM"] for r in rows)},
        tables=[
            table(
                "Curtain walls",
                [("id", "Curtain wall"), ("type", "Type"), ("lengthM", "Length", "m")],
                rows,
            )
        ],
    )


@feature(
    "architectureEnvelope.wallSweeps",
    "Wall Sweeps",
    part="floorPlan",
    fields=[
        text("wallId", "Wall id", ""),
        number("depth", "Sweep depth", 75, unit="mm", min=0),
        number("height", "Sweep height", 100, unit="mm", min=0),
    ],
)
def wall_sweeps(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Create sweep profiles for selected walls."""
    arch = require_arch(ctx)
    rows = [
        {
            "wall": w.id,
            "lengthM": sum(math.dist(a, b) for a, b in zip(w.path, w.path[1:])) / 1000,
            "depthMm": values["depth"],
            "heightMm": values["height"],
        }
        for w in arch.walls
        if not values["wallId"] or w.id == values["wallId"]
    ]
    if not rows:
        raise FeatureInputError("No matching wall was found.")
    return result(
        summary={"wallCount": len(rows), "totalSweepLengthM": sum(r["lengthM"] for r in rows)},
        tables=[
            table(
                "Wall sweeps",
                [
                    ("wall", "Wall"),
                    ("lengthM", "Length", "m"),
                    ("depthMm", "Depth", "mm"),
                    ("heightMm", "Height", "mm"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureEnvelope.reveals",
    "Reveals",
    part="floorPlan",
    fields=[
        text("hostId", "Wall id", ""),
        number("width", "Reveal width", 20, unit="mm", min=1),
        number("depth", "Reveal depth", 10, unit="mm", min=1),
    ],
)
def reveals(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Compute reveal groove volume and thickness reduction along a host wall."""
    import json

    arch = require_arch(ctx)
    host_id = values["hostId"].strip()
    wall = next((w for w in arch.walls if w.id == host_id), None)
    if wall is None:
        raise FeatureInputError(f"The reveal host wall '{host_id}' was not found.")
    wall_type = next((wt for wt in arch.wallTypes if wt.id == wall.type), None)
    wall_thickness_mm = wall_type.thickness if wall_type else 0.0
    length_mm = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(wall.path, wall.path[1:]))
    width_mm = float(values["width"])
    depth_mm = float(values["depth"])
    volume_m3 = round((length_mm / 1000.0) * (width_mm / 1000.0) * (depth_mm / 1000.0), 6)
    reduction_pct = (
        round((depth_mm / wall_thickness_mm) * 100.0, 2) if wall_thickness_mm > 0 else 0.0
    )
    outer_layer_mm = wall_type.layers[0].thickness if wall_type and wall_type.layers else 0.0
    exceeds_outer = outer_layer_mm > 0 and depth_mm > outer_layer_mm

    assert ctx.root is not None
    reg_path = ctx.root / "11 Exports" / "Architecture" / "wall-reveals.json"
    entries: list[dict[str, Any]] = []
    if reg_path.is_file():
        try:
            loaded = json.loads(reg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                entries = loaded
        except (OSError, ValueError):
            entries = []
    entry = {
        "hostId": wall.id,
        "wallType": wall.type,
        "lengthM": round(length_mm / 1000.0, 3),
        "widthMm": width_mm,
        "depthMm": depth_mm,
        "grooveVolumeM3": volume_m3,
        "thicknessReductionPercent": reduction_pct,
        "exceedsOuterLayer": exceeds_outer,
    }
    entries = [e for e in entries if e.get("hostId") != wall.id]
    entries.append(entry)
    path = write_json(ctx, "wall-reveals.json", entries)
    return result(
        summary={
            "hostId": wall.id,
            "lengthM": entry["lengthM"],
            "grooveVolumeM3": volume_m3,
            "thicknessReductionPercent": reduction_pct,
            "exportPath": path,
        },
        tables=[
            table(
                "Wall reveals",
                [
                    ("hostId", "Wall"),
                    ("lengthM", "Length", "m"),
                    ("widthMm", "Width", "mm"),
                    ("depthMm", "Depth", "mm"),
                    ("grooveVolumeM3", "Volume", "m³"),
                    ("thicknessReductionPercent", "Wall reduction", "%"),
                ],
                entries,
            )
        ],
        problems=(
            [f"Reveal depth ({depth_mm:g} mm) exceeds outer wall layer ({outer_layer_mm:g} mm)."]
            if exceeds_outer
            else []
        ),
    )


@feature(
    "architectureEnvelope.roofByFootprint",
    "Roof By Footprint",
    part="floorPlan",
    fields=[
        text("roofId", "Roof id", "RF-001"),
        text("roofType", "Roof type id", ""),
        number("slope", "Footprint slope", 30, unit="°", min=0, max=89),
    ],
)
def roof_by_footprint(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Measure roof footprint area and selected slope surface area."""
    from saengine.library.architecture import roof_area

    arch = require_arch(ctx)
    matches = [r for r in arch.roofs if r.id == values["roofId"] or not values["roofId"]]
    if not matches:
        raise FeatureInputError("No matching roof was found.")
    rows = []
    for roof in matches:
        plan, sloped = roof_area(roof)
        rows.append({"roof": roof.id, "planAreaM2": plan * 1e-6, "slopedAreaM2": sloped * 1e-6})
    return result(
        summary={
            "roofCount": len(rows),
            "planAreaM2": sum(r["planAreaM2"] for r in rows),
            "slopedAreaM2": sum(r["slopedAreaM2"] for r in rows),
        },
        tables=[
            table(
                "Roof footprints",
                [
                    ("roof", "Roof"),
                    ("planAreaM2", "Plan area", "m²"),
                    ("slopedAreaM2", "Sloped area", "m²"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureEnvelope.roofSlope",
    "Roof Slope",
    part="floorPlan",
    fields=[
        text("roofId", "Roof id", ""),
        number("slope", "Slope", 30, unit="°", min=0, max=89),
        number("drainageSlope", "Flat-roof drainage slope", 2, unit="°", min=0, max=44),
    ],
)
def roof_slope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Check the roof pitch and drainage slope values."""
    arch = require_arch(ctx)
    matches = [r for r in arch.roofs if not values["roofId"] or r.id == values["roofId"]]
    if not matches:
        raise FeatureInputError("No matching roof was found.")
    rows = [
        {"roof": r.id, "slopeDeg": values["slope"], "drainageSlopeDeg": values["drainageSlope"]}
        for r in matches
    ]
    return result(
        summary={"roofCount": len(rows)},
        tables=[
            table(
                "Roof slopes",
                [
                    ("roof", "Roof"),
                    ("slopeDeg", "Pitch", "°"),
                    ("drainageSlopeDeg", "Drainage", "°"),
                ],
                rows,
            )
        ],
    )


@feature(
    "architectureEnvelope.eavesVerges",
    "Eaves & Verges",
    part="floorPlan",
    fields=[
        text("roofId", "Roof id", ""),
        number("eavesOverhang", "Eaves overhang", 500, unit="mm", min=0),
        number("vergeOverhang", "Verge overhang", 300, unit="mm", min=0),
    ],
)
def eaves_verges(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare eaves and verge overhang dimensions."""
    arch = require_arch(ctx)
    matches = [r for r in arch.roofs if not values["roofId"] or r.id == values["roofId"]]
    if not matches:
        raise FeatureInputError("No matching roof was found.")
    rows = [
        {"roof": r.id, "eavesMm": values["eavesOverhang"], "vergeMm": values["vergeOverhang"]}
        for r in matches
    ]
    return result(
        summary={"roofCount": len(rows)},
        tables=[
            table(
                "Roof overhangs",
                [("roof", "Roof"), ("eavesMm", "Eaves", "mm"), ("vergeMm", "Verge", "mm")],
                rows,
            )
        ],
    )


@feature(
    "architectureEnvelope.insulationLayer",
    "Insulation Layer",
    part="floorPlan",
    fields=[
        text("assembly", "Assembly", "Wall"),
        number("thickness", "Insulation thickness", 50, unit="mm", min=1),
        number("conductivity", "Thermal conductivity", 0.035, unit="W/mK", min=0.001),
    ],
)
def insulation_layer(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate insulation thermal resistance R = thickness/conductivity."""
    resistance = values["thickness"] / 1000 / values["conductivity"]
    return result(
        summary={
            "assembly": values["assembly"],
            "thicknessMm": values["thickness"],
            "thermalResistanceM2KPerW": resistance,
        }
    )


@feature(
    "architectureEnvelope.thermalBridge",
    "Thermal Bridge",
    part="floorPlan",
    fields=[
        text("junction", "Junction", "Wall-floor"),
        number("length", "Linear junction length", 10, unit="m", min=0),
        number("psi", "Linear thermal transmittance", 0.05, unit="W/mK", min=0),
    ],
)
def thermal_bridge(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate linear thermal bridge heat-transfer coefficient psi × length."""
    coefficient = values["length"] * values["psi"]
    return result(
        summary={
            "junction": values["junction"],
            "lengthM": values["length"],
            "psiWPerMK": values["psi"],
            "heatTransferCoefficientWPerK": coefficient,
        }
    )


@feature(
    "architectureEnvelope.vapourBarrier",
    "Vapour Barrier",
    part="floorPlan",
    fields=[
        select(
            "position",
            "Barrier position",
            [("warm", "Warm side"), ("middle", "Middle"), ("cold", "Cold side")],
            "warm",
        ),
        number("thickness", "Barrier thickness", 0.2, unit="mm", min=0),
        number("sd", "Diffusion-equivalent thickness", 50, unit="m", min=0),
    ],
)
def vapour_barrier(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record vapour-barrier position and diffusion resistance."""
    return result(
        summary={
            "position": values["position"],
            "thicknessMm": values["thickness"],
            "diffusionEquivalentThicknessM": values["sd"],
        },
        notes=[
            "Diffusion resistance is represented by the supplied diffusion-equivalent thickness; condensate risk needs a temperature profile."
        ],
    )


@feature(
    "architectureEnvelope.floorSlabLayers",
    "Floor Slab Layers",
    part="floorPlan",
    fields=[
        number("structural", "Structural layer", 150, unit="mm", min=1),
        number("screed", "Screed", 50, unit="mm", min=0),
        number("finish", "Finish", 20, unit="mm", min=0),
    ],
)
def floor_slab_layers(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate a floor slab build-up thickness and layer table."""
    total = values["structural"] + values["screed"] + values["finish"]
    rows = [
        {"layer": "Structural", "thicknessMm": values["structural"]},
        {"layer": "Screed", "thicknessMm": values["screed"]},
        {"layer": "Finish", "thicknessMm": values["finish"]},
    ]
    return result(
        summary={"totalThicknessMm": total},
        tables=[
            table(
                "Floor slab layers", [("layer", "Layer"), ("thicknessMm", "Thickness", "mm")], rows
            )
        ],
    )


@feature(
    "architectureEnvelope.ceilingLayers",
    "Ceiling Layers",
    part="floorPlan",
    fields=[
        number("finish", "Finish thickness", 12.5, unit="mm", min=0),
        number("cavity", "Cavity depth", 300, unit="mm", min=0),
        number("void", "Service void", 150, unit="mm", min=0),
    ],
)
def ceiling_layers(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate ceiling build-up depth and opening clearance."""
    total = values["finish"] + values["cavity"] + values["void"]
    return result(
        summary={
            "totalDepthMm": total,
            "finishMm": values["finish"],
            "cavityMm": values["cavity"],
            "voidMm": values["void"],
        }
    )


@feature(
    "architectureEnvelope.slabEdgeProfile",
    "Slab Edge Profile",
    part="floorPlan",
    fields=[
        number("depth", "Edge depth", 300, unit="mm", min=1),
        number("drip", "Drip projection", 25, unit="mm", min=0),
        number("thickness", "Edge thickness", 150, unit="mm", min=1),
    ],
)
def slab_edge_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate slab-edge profile projection and volume per metre."""
    volume = values["depth"] * values["thickness"] * 1e-9
    return result(
        summary={
            "depthMm": values["depth"],
            "dripProjectionMm": values["drip"],
            "thicknessMm": values["thickness"],
            "volumePerM": volume,
        }
    )


@feature(
    "architectureEnvelope.floorOpenings",
    "Floor Openings",
    part="floorPlan",
    fields=[
        text("openingId", "Opening id", "FO-001"),
        number("width", "Width", 1000, unit="mm", min=1),
        number("length", "Length", 1000, unit="mm", min=1),
    ],
)
def floor_openings(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate floor-opening area and perimeter."""
    area = values["width"] * values["length"] * 1e-6
    perimeter = 2 * (values["width"] + values["length"]) / 1000
    return result(
        summary={"openingId": values["openingId"], "areaM2": area, "perimeterM": perimeter}
    )


@feature(
    "architectureEnvelope.compositeDeck",
    "Composite Deck",
    part="floorPlan",
    fields=[
        number("rib", "Deck rib depth", 75, unit="mm", min=0),
        number("topping", "Concrete topping", 75, unit="mm", min=0),
        number("ribWidth", "Rib width", 150, unit="mm", min=1),
        number("ribPitch", "Rib pitch", 300, unit="mm", min=1),
    ],
)
def composite_deck(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate composite deck overall depth and approximate rib volume per metre."""
    depth = values["rib"] + values["topping"]
    ribVolume = values["rib"] * values["ribWidth"] / values["ribPitch"] * 1e-6
    return result(summary={"totalDepthMm": depth, "ribVolumePerM": ribVolume})


@feature(
    "architectureEnvelope.glazingTypes",
    "Glazing Types",
    part="floorPlan",
    fields=[
        text("glazingId", "Glazing type id", "GL-01"),
        number("thickness", "Glass thickness", 24, unit="mm", min=1),
        number("uValue", "Glazing U-value", 1.8, unit="W/m²K", min=0),
    ],
)
def glazing_types(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Record glazing build-up thickness and thermal U-value."""
    return result(
        summary={
            "glazingId": values["glazingId"],
            "thicknessMm": values["thickness"],
            "uValueWPerM2K": values["uValue"],
        }
    )


@feature(
    "architectureEnvelope.windowSills",
    "Window Sills",
    part="floorPlan",
    fields=[
        text("windowId", "Window id", ""),
        number("projection", "Internal/external sill projection", 100, unit="mm", min=0),
        number("width", "Sill width", 150, unit="mm", min=1),
    ],
)
def window_sills(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate sill area per metre using the supplied window length."""
    arch = require_arch(ctx)
    window = next((w for w in arch.windows if w.id == values["windowId"]), None)
    if window is None:
        raise FeatureInputError("The window id was not found.")
    return result(
        summary={
            "windowId": window.id,
            "projectionMm": values["projection"],
            "widthMm": values["width"],
        }
    )


@feature(
    "architectureEnvelope.mullionSpacing",
    "Mullion Spacing",
    part="floorPlan",
    fields=[
        number("length", "Curtain wall length", 12000, unit="mm", min=1),
        number("targetSpacing", "Target spacing", 1500, unit="mm", min=100),
    ],
)
def mullion_spacing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Determine an integer mullion-panel division and actual spacing."""
    panels = max(1, math.ceil(values["length"] / values["targetSpacing"]))
    spacing = values["length"] / panels
    return result(
        summary={"panelCount": panels, "mullionCount": panels + 1, "actualSpacingMm": spacing}
    )


@feature(
    "architectureEnvelope.glassPanels",
    "Glass Panels",
    part="floorPlan",
    fields=[
        text("panelId", "Panel id", "P-001"),
        number("width", "Panel width", 1500, unit="mm", min=1),
        number("height", "Panel height", 2700, unit="mm", min=1),
    ],
)
def glass_panels(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate glass panel plan area and perimeter."""
    area = values["width"] * values["height"] * 1e-6
    perimeter = 2 * (values["width"] + values["height"]) / 1000
    return result(summary={"panelId": values["panelId"], "areaM2": area, "perimeterM": perimeter})


@feature(
    "architectureEnvelope.frameProfiles",
    "Frame Profiles",
    part="floorPlan",
    fields=[
        text("profileId", "Frame profile id", "F-01"),
        number("width", "Profile width", 60, unit="mm", min=1),
        number("depth", "Profile depth", 70, unit="mm", min=1),
        number("length", "Profile length", 3000, unit="mm", min=1),
    ],
)
def frame_profiles(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate frame profile cross-sectional area and volume."""
    area = values["width"] * values["depth"] * 1e-6
    volume = area * values["length"] / 1000
    return result(
        summary={"profileId": values["profileId"], "sectionAreaM2": area, "volumeM3": volume}
    )


@feature(
    "architectureEnvelope.wallBaseDetail",
    "Wall Base Detail",
    part="floorPlan",
    fields=[
        number("plinthHeight", "Plinth height", 150, unit="mm", min=0),
        number("dpcThickness", "Damp-proof-course thickness", 1.5, unit="mm", min=0),
        number("baseWidth", "Base finish width", 100, unit="mm", min=0),
    ],
)
def wall_base_detail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Prepare wall-base detail dimensions."""
    return result(
        summary={
            "plinthHeightMm": values["plinthHeight"],
            "dpcThicknessMm": values["dpcThickness"],
            "baseWidthMm": values["baseWidth"],
        }
    )


@feature(
    "architectureEnvelope.parapetDetail",
    "Parapet Detail",
    part="floorPlan",
    fields=[
        number("height", "Parapet height", 900, unit="mm", min=1),
        number("thickness", "Parapet thickness", 150, unit="mm", min=1),
        number("copingProjection", "Coping projection", 50, unit="mm", min=0),
    ],
)
def parapet_detail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate parapet cross-sectional area per metre."""
    area = values["thickness"] * values["height"] * 1e-6
    return result(
        summary={
            "heightMm": values["height"],
            "thicknessMm": values["thickness"],
            "copingProjectionMm": values["copingProjection"],
            "sectionAreaM2": area,
        }
    )


@feature(
    "architectureEnvelope.copingDetail",
    "Coping Detail",
    part="floorPlan",
    fields=[
        number("width", "Coping width", 300, unit="mm", min=1),
        number("thickness", "Coping thickness", 50, unit="mm", min=1),
        number("drip", "Drip projection", 25, unit="mm", min=0),
    ],
)
def coping_detail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculate coping area and volume per metre."""
    area = values["width"] * 1e-3
    volume = values["width"] * values["thickness"] * 1e-9
    return result(
        summary={
            "areaPerM": area,
            "volumePerM": volume,
            "widthMm": values["width"],
            "thicknessMm": values["thickness"],
            "dripMm": values["drip"],
        }
    )


@feature(
    "architectureEnvelope.expansionJoints",
    "Expansion Joints",
    part="floorPlan",
    fields=[
        number("length", "Facade length", 100, unit="m", min=0.1),
        number("spacing", "Joint spacing", 30, unit="m", min=1),
        number("width", "Joint width", 20, unit="mm", min=1),
    ],
)
def expansion_joints(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Place expansion joints at an integer division of the supplied facade length."""
    joints = max(0, math.floor(values["length"] / values["spacing"]))
    actualSpacing = values["length"] / joints if joints else values["length"]
    return result(
        summary={
            "jointCount": joints,
            "actualSpacingM": actualSpacing,
            "jointWidthMm": values["width"],
        }
    )
