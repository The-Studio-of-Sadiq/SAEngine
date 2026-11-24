"""BIM conceptual massing and environmental form feature buttons."""

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
from saengine.features.bim_common import require_bim, write_bim_csv, write_bim_json


@feature(
    "bimAdditionsMassing.createMass",
    "Create Mass",
    part="bim",
    fields=[
        text("name", "Mass name", "Tower Mass"),
        number("width", "Mass width", 30.0, unit="m", min=0.1),
        number("length", "Mass length", 20.0, unit="m", min=0.1),
        number("height", "Mass height", 60.0, unit="m", min=0.1),
    ],
)
def create_mass(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a rectangular conceptual mass."""
    require_bim(ctx)
    volume = values["width"] * values["length"] * values["height"]
    mass = {
        "name": values["name"],
        "widthM": values["width"],
        "lengthM": values["length"],
        "heightM": values["height"],
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "conceptual-mass.json", mass)
    return result(summary={**mass, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsMassing.extrudeProfile",
    "Extrude Profile",
    part="bim",
    fields=[
        number("width", "Profile width", 10.0, unit="m", min=0.1),
        number("length", "Profile length", 10.0, unit="m", min=0.1),
        number("height", "Extrusion height", 20.0, unit="m", min=0.1),
    ],
)
def extrude_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Extrudes a rectangular mass profile."""
    require_bim(ctx)
    area = values["width"] * values["length"]
    volume = area * values["height"]
    return result(
        summary={
            "widthM": values["width"],
            "lengthM": values["length"],
            "heightM": values["height"],
            "baseAreaM2": area,
            "volumeM3": volume,
        }
    )


@feature(
    "bimAdditionsMassing.revolveProfile",
    "Revolve Profile",
    part="bim",
    fields=[
        number("radius", "Profile radius", 5.0, unit="m", min=0.1),
        number("height", "Revolved height", 20.0, unit="m", min=0.1),
        number("angle", "Revolution angle", 360, unit="°", min=1, max=360),
    ],
)
def revolve_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimates the volume of a revolved profile."""
    require_bim(ctx)

    fraction = values["angle"] / 360
    volume = math.pi * values["radius"] ** 2 * values["height"] * fraction
    return result(
        summary={
            "radiusM": values["radius"],
            "heightM": values["height"],
            "angleDeg": values["angle"],
            "volumeM3": volume,
        },
        notes=["Volume assumes a circular profile revolved about a centred axis."],
    )


@feature(
    "bimAdditionsMassing.loftSections",
    "Loft Sections",
    part="bim",
    fields=[
        number("bottomArea", "Bottom area", 100.0, unit="m²", min=0.1),
        number("topArea", "Top area", 50.0, unit="m²", min=0.1),
        number("height", "Loft height", 30.0, unit="m", min=0.1),
    ],
)
def loft_sections(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimates volume between two loft sections."""
    require_bim(ctx)
    a = values["bottomArea"]
    b = values["topArea"]
    h = values["height"]
    volume = h / 3 * (a + b + (a * b) ** 0.5)
    return result(
        summary={"bottomAreaM2": a, "topAreaM2": b, "heightM": h, "volumeM3": volume},
        notes=["Volume uses the prismoidal expression for proportional end areas."],
    )


@feature(
    "bimAdditionsMassing.formSubtraction",
    "Form Subtraction",
    part="bim",
    fields=[
        number("hostVolume", "Host volume", 1000.0, unit="m³", min=0.1),
        number("voidVolume", "Void volume", 50.0, unit="m³", min=0.1),
    ],
)
def form_subtraction(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Subtracts a void volume from a mass."""
    require_bim(ctx)
    if values["voidVolume"] > values["hostVolume"]:
        raise FeatureInputError("Void volume cannot exceed host volume.")
    residual = values["hostVolume"] - values["voidVolume"]
    return result(
        summary={
            "hostVolumeM3": values["hostVolume"],
            "voidVolumeM3": values["voidVolume"],
            "residualVolumeM3": residual,
        }
    )


@feature(
    "bimAdditionsMassing.divideSurface",
    "Divide Surface",
    part="bim",
    fields=[
        number("uCount", "U divisions", 10, unit="ea", min=1),
        number("vCount", "V divisions", 10, unit="ea", min=1),
        number("area", "Surface area", 100.0, unit="m²", min=0.1),
    ],
)
def divide_surface(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Divides a facade surface into a rectangular grid."""
    require_bim(ctx)
    u = int(values["uCount"])
    v = int(values["vCount"])
    count = u * v
    rows = [
        {"u": i + 1, "v": j + 1, "areaM2": values["area"] / count}
        for i in range(u)
        for j in range(v)
    ]
    path = write_bim_csv(ctx, "divided-surface.csv", ["u", "v", "areaM2"], rows)
    return result(
        summary={
            "uDivisions": u,
            "vDivisions": v,
            "panelCount": count,
            "areaPerPanelM2": values["area"] / count,
            "exportPath": path,
        },
        tables=[
            table(
                "Divided Surface",
                [("u", "U"), ("v", "V"), ("areaM2", "Area [m²]", "m²")],
                rows[:100],
            )
        ],
        notes=["Area per panel assumes uniform equal subdivision.", f"Export: {path}"],
    )


@feature(
    "bimAdditionsMassing.surfacePattern",
    "Surface Pattern",
    part="bim",
    fields=[
        select(
            "pattern",
            "Pattern",
            [("diamond", "Diamond"), ("square", "Square"), ("triangular", "Triangular")],
            "square",
        ),
        number("spacing", "Pattern spacing", 0.5, unit="m", min=0.01),
    ],
)
def surface_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a surface pattern."""
    require_bim(ctx)
    record = {"pattern": values["pattern"], "spacingM": values["spacing"]}
    path = write_bim_json(ctx, "surface-pattern.json", record)
    return result(summary={**record, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsMassing.applyPanel",
    "Apply Panel",
    part="bim",
    fields=[
        text("panelType", "Panel type", "CW-Glazing"),
        number("count", "Applied count", 100, unit="ea", min=1),
    ],
)
def apply_panel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Applies a panel type to a divided mass surface."""
    require_bim(ctx)
    path = write_bim_json(
        ctx, "applied-panel.json", {"panelType": values["panelType"], "count": int(values["count"])}
    )
    return result(
        summary={
            "panelType": values["panelType"],
            "panelCount": int(values["count"]),
            "exportPath": path,
        },
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsMassing.gridRotation",
    "Grid Rotation",
    part="bim",
    fields=[number("angle", "Rotation angle", 15.0, unit="°", min=-180, max=180)],
)
def grid_rotation(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Rotates a mass surface grid."""
    require_bim(ctx)
    return result(summary={"rotationDeg": values["angle"]})


@feature(
    "bimAdditionsMassing.toWalls",
    "To Walls",
    part="bim",
    fields=[
        number("height", "Wall height", 3.2, unit="m", min=0.1),
        number("perimeter", "Mass perimeter", 100.0, unit="m", min=0.1),
    ],
)
def to_walls(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Converts a mass boundary into wall area."""
    require_bim(ctx)
    area = values["perimeter"] * values["height"]
    return result(
        summary={
            "perimeterM": values["perimeter"],
            "heightM": values["height"],
            "wallAreaM2": area,
        },
        notes=["Rectilinear boundary area is length × height; openings are excluded."],
    )


@feature(
    "bimAdditionsMassing.toRoofs",
    "To Roofs",
    part="bim",
    fields=[
        number("area", "Mass roof area", 500.0, unit="m²", min=0.1),
        number("slope", "Roof slope", 10.0, unit="°", min=0, max=90),
    ],
)
def to_roofs(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Converts a mass top to roof area."""
    require_bim(ctx)

    slope_area = (
        values["area"] / math.cos(math.radians(values["slope"]))
        if abs(values["slope"]) < 90
        else values["area"]
    )
    return result(
        summary={
            "horizontalAreaM2": values["area"],
            "slopeDeg": values["slope"],
            "slopedAreaM2": slope_area,
        }
    )


@feature(
    "bimAdditionsMassing.toFloors",
    "To Floors",
    part="bim",
    fields=[
        number("area", "Mass floor area", 500.0, unit="m²", min=0.1),
        number("thickness", "Floor thickness", 150, unit="mm", min=20),
        number("storeys", "Storey count", 5, unit="ea", min=1),
    ],
)
def to_floors(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Converts mass levels to floor elements."""
    require_bim(ctx)
    storeys = int(values["storeys"])
    area = values["area"] * storeys
    volume = area * values["thickness"] / 1000
    return result(
        summary={
            "storeyCount": storeys,
            "floorAreaM2": area,
            "thicknessMm": values["thickness"],
            "concreteVolumeM3": volume,
        }
    )


@feature(
    "bimAdditionsMassing.updateMass",
    "Update Mass",
    part="bim",
    fields=[
        text("massName", "Mass name", "Tower Mass"),
        number("height", "Updated height", 60.0, unit="m", min=0.1),
    ],
)
def update_mass(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Records an updated conceptual-mass height."""
    require_bim(ctx)
    path = write_bim_json(
        ctx, "updated-mass.json", {"name": values["massName"], "heightM": values["height"]}
    )
    return result(
        summary={"massName": values["massName"], "heightM": values["height"], "exportPath": path},
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsMassing.massFloor",
    "Mass Floor",
    part="bim",
    fields=[
        number("area", "Floor area", 500.0, unit="m²", min=0.1),
        number("elevation", "Floor elevation", 10.0, unit="m"),
    ],
)
def mass_floor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a conceptual mass floor."""
    require_bim(ctx)
    floor = {"areaM2": values["area"], "elevationM": values["elevation"]}
    path = write_bim_json(ctx, "mass-floor.json", floor)
    return result(summary={**floor, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsMassing.floorAreaFace",
    "Floor Area Face",
    part="bim",
    fields=[
        number("length", "Face length", 20.0, unit="m", min=0.1),
        number("width", "Face width", 10.0, unit="m", min=0.1),
    ],
)
def floor_area_face(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculates a rectangular floor face area."""
    require_bim(ctx)
    area = values["length"] * values["width"]
    return result(summary={"lengthM": values["length"], "widthM": values["width"], "areaM2": area})


@feature(
    "bimAdditionsMassing.grossFloorSchedule",
    "Gross Floor Schedule",
    part="bim",
    fields=[
        number("area", "Typical floor gross area", 500.0, unit="m²", min=0.1),
        number("storeys", "Storey count", 5, unit="ea", min=1),
    ],
)
def gross_floor_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a gross-floor-area schedule."""
    require_bim(ctx)
    storeys = int(values["storeys"])
    rows = [{"storey": i + 1, "grossAreaM2": values["area"]} for i in range(storeys)]
    path = write_bim_csv(ctx, "gross-floor-schedule.csv", ["storey", "grossAreaM2"], rows)
    return result(
        summary={
            "storeyCount": storeys,
            "grossFloorAreaM2": values["area"] * storeys,
            "exportPath": path,
        },
        tables=[
            table(
                "Gross Floor Schedule",
                [("storey", "Storey"), ("grossAreaM2", "Gross area [m²]", "m²")],
                rows,
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsMassing.panelOptimization",
    "Panel Optimization",
    part="bim",
    fields=[
        number("area", "Facade area", 500.0, unit="m²", min=0.1),
        number("targetPanelArea", "Target panel area", 6.0, unit="m²", min=0.1),
    ],
)
def panel_optimization(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Estimates panel counts for an optimisation target."""
    require_bim(ctx)

    count = math.ceil(values["area"] / values["targetPanelArea"])
    return result(
        summary={
            "facadeAreaM2": values["area"],
            "targetPanelAreaM2": values["targetPanelArea"],
            "estimatedPanelCount": count,
        }
    )


@feature(
    "bimAdditionsMassing.planarizeFaces",
    "Planarize Faces",
    part="bim",
    fields=[
        number("faceCount", "Face count", 20, unit="ea", min=1),
        number("tolerance", "Planarity tolerance", 10, unit="mm", min=0),
    ],
)
def planarize_faces(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Reports a planarization tolerance setup."""
    require_bim(ctx)
    rows = [
        {"face": i + 1, "toleranceMm": values["tolerance"]} for i in range(int(values["faceCount"]))
    ]
    path = write_bim_csv(ctx, "planarized-faces.csv", ["face", "toleranceMm"], rows)
    return result(
        summary={
            "faceCount": int(values["faceCount"]),
            "toleranceMm": values["tolerance"],
            "exportPath": path,
        },
        tables=[
            table(
                "Planarized Faces",
                [("face", "Face"), ("toleranceMm", "Tolerance [mm]", "mm")],
                rows[:100],
            )
        ],
        notes=["Planarization coordinates require the mass face geometry.", f"Export: {path}"],
    )


@feature(
    "bimAdditionsMassing.curvatureAnalysis",
    "Curvature Analysis",
    part="bim",
    fields=[
        number("radius", "Minimum radius", 5.0, unit="m", min=0.1),
        number("measuredRadius", "Measured radius", 4.0, unit="m", min=0.1),
    ],
)
def curvature_analysis(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks a measured minimum curvature radius."""
    require_bim(ctx)
    passes = values["measuredRadius"] >= values["radius"]
    return result(
        summary={
            "requiredRadiusM": values["radius"],
            "measuredRadiusM": values["measuredRadius"],
            "passes": passes,
        }
    )


@feature(
    "bimAdditionsMassing.buildingEnvelope",
    "Building Envelope",
    part="bim",
    fields=[
        number("area", "Gross envelope area", 2000.0, unit="m²", min=0.1),
        number("uValue", "Average envelope U-value", 1.5, unit="W/m²K", min=0.1),
    ],
)
def building_envelope(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculates an envelope conductance coefficient."""
    require_bim(ctx)
    conductance = values["area"] * values["uValue"]
    return result(
        summary={
            "envelopeAreaM2": values["area"],
            "uValueWPerM2K": values["uValue"],
            "conductanceWPerK": conductance,
        }
    )


@feature(
    "bimAdditionsMassing.formEnergyZone",
    "Form Energy Zone",
    part="bim",
    fields=[
        text("zoneName", "Energy zone", "Core"),
        number("area", "Zone area", 100.0, unit="m²", min=0.1),
        number("loadDensity", "Load density", 25.0, unit="W/m²", min=0),
    ],
)
def form_energy_zone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculates a massing-zone internal load."""
    require_bim(ctx)
    load = values["area"] * values["loadDensity"]
    zone = {
        "name": values["zoneName"],
        "areaM2": values["area"],
        "loadDensityWPerM2": values["loadDensity"],
        "loadW": load,
    }
    path = write_bim_json(ctx, "form-energy-zone.json", zone)
    return result(summary={**zone, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsMassing.shadingGeometry",
    "Shading Geometry",
    part="bim",
    fields=[
        number("projection", "Shade projection", 1.0, unit="m", min=0),
        number("height", "Shade height", 0.3, unit="m", min=0),
        number("length", "Shade length", 10.0, unit="m", min=0.1),
    ],
)
def shading_geometry(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a horizontal shading geometry."""
    require_bim(ctx)
    area = values["length"] * values["projection"]
    shade = {
        "projectionM": values["projection"],
        "heightM": values["height"],
        "lengthM": values["length"],
        "areaM2": area,
    }
    path = write_bim_json(ctx, "shading-geometry.json", shade)
    return result(summary={**shade, "exportPath": path}, notes=[f"Export: {path}"])
