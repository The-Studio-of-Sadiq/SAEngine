"""BIM curtain wall, glazing and facade feature buttons."""

from __future__ import annotations

from typing import Any

from saengine.features import FeatureContext, feature, number, result, select, table, text
from saengine.features.bim_common import require_bim, write_bim_csv, write_bim_json


@feature(
    "bimAdditionsCurtain.curtainGrid",
    "Curtain Grid",
    part="bim",
    fields=[
        number("width", "Curtain wall width", 12.0, unit="m", min=0.1),
        number("bayWidth", "Bay width", 1.5, unit="m", min=0.1),
        number("storeyHeight", "Storey height", 3.2, unit="m", min=0.1),
    ],
)
def curtain_grid(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates curtain-wall grid spacing."""
    require_bim(ctx)
    bays = max(1, int(values["width"] / values["bayWidth"] + 0.999999))
    return result(
        summary={
            "widthM": values["width"],
            "bayWidthM": values["bayWidth"],
            "bayCount": bays,
            "storeyHeightM": values["storeyHeight"],
        },
        tables=[
            table(
                "Curtain Bays",
                [("bay", "Bay"), ("offsetM", "Offset [m]", "m")],
                [{"bay": i + 1, "offsetM": i * values["bayWidth"]} for i in range(bays)],
            )
        ],
    )


@feature(
    "bimAdditionsCurtain.addMullion",
    "Add Mullion",
    part="bim",
    fields=[
        text("profile", "Mullion profile", "M150"),
        number("height", "Mullion height", 3.2, unit="m", min=0.1),
    ],
)
def add_mullion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adds a curtain-wall mullion."""
    require_bim(ctx)
    row = {"profile": values["profile"], "heightM": values["height"]}
    path = write_bim_json(ctx, "curtain-mullion.json", row)
    return result(summary={**row, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.gridSegment",
    "Grid Segment",
    part="bim",
    fields=[
        number("start", "Segment start", 0.0, unit="m"),
        number("end", "Segment end", 1.5, unit="m", min=0.1),
    ],
)
def grid_segment(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a curtain-grid segment."""
    require_bim(ctx)
    length = abs(values["end"] - values["start"])
    return result(summary={"startM": values["start"], "endM": values["end"], "lengthM": length})


@feature(
    "bimAdditionsCurtain.gridOffset",
    "Grid Offset",
    part="bim",
    fields=[
        number("offset", "Grid offset", 0.1, unit="m"),
        select(
            "direction",
            "Offset direction",
            [("inward", "Inward"), ("outward", "Outward")],
            "outward",
        ),
    ],
)
def grid_offset(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Applies an offset to a curtain grid."""
    require_bim(ctx)
    return result(
        summary={"offsetM": values["offset"]},
        notes=["Offset is a view/model coordinate instruction."],
    )


@feature(
    "bimAdditionsCurtain.gridBoundary",
    "Grid Boundary",
    part="bim",
    fields=[
        number("width", "Boundary width", 12.0, unit="m", min=0.1),
        number("height", "Boundary height", 3.2, unit="m", min=0.1),
    ],
)
def grid_boundary(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines the curtain-grid boundary."""
    require_bim(ctx)
    boundary = {
        "widthM": values["width"],
        "heightM": values["height"],
        "areaM2": values["width"] * values["height"],
    }
    path = write_bim_json(ctx, "curtain-grid-boundary.json", boundary)
    return result(summary={**boundary, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.glazingPanel",
    "Glazing Panel",
    part="bim",
    fields=[
        number("width", "Panel width", 1.5, unit="m", min=0.1),
        number("height", "Panel height", 3.0, unit="m", min=0.1),
        number("thickness", "Glass thickness", 24, unit="mm", min=2),
    ],
)
def glazing_panel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a glazing panel specification."""
    require_bim(ctx)
    area = values["width"] * values["height"]
    panel = {
        "widthM": values["width"],
        "heightM": values["height"],
        "thicknessMm": values["thickness"],
        "areaM2": area,
    }
    path = write_bim_json(ctx, "glazing-panel.json", panel)
    return result(summary={**panel, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.spandrelPanel",
    "Spandrel Panel",
    part="bim",
    fields=[
        number("width", "Panel width", 1.5, unit="m", min=0.1),
        number("height", "Panel height", 0.9, unit="m", min=0.1),
        number("thickness", "Panel thickness", 50, unit="mm", min=5),
    ],
)
def spandrel_panel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a spandrel facade panel."""
    require_bim(ctx)
    panel = {
        "widthM": values["width"],
        "heightM": values["height"],
        "thicknessMm": values["thickness"],
        "areaM2": values["width"] * values["height"],
    }
    path = write_bim_json(ctx, "spandrel-panel.json", panel)
    return result(summary={**panel, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.panelSchedule",
    "Panel Schedule",
    part="bim",
    fields=[
        number("panelCount", "Panel count", 20, unit="ea", min=1),
        text("prefix", "Panel prefix", "CW"),
    ],
)
def panel_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedules facade panels."""
    require_bim(ctx)
    count = int(values["panelCount"])
    rows = [{"panel": f"{values['prefix']}-{i + 1}"} for i in range(count)]
    path = write_bim_csv(ctx, "curtain-panel-schedule.csv", ["panel"], rows)
    return result(
        summary={"panelCount": count, "exportPath": path},
        tables=[table("Panel Schedule", [("panel", "Panel")], rows)],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsCurtain.replacePanel",
    "Replace Panel",
    part="bim",
    fields=[
        text("panelId", "Panel id", "CW-1"),
        select(
            "replacement",
            "Replacement type",
            [("glazing", "Glazing"), ("spandrel", "Spandrel"), ("vent", "Vent")],
            "glazing",
        ),
    ],
)
def replace_panel(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Replaces a facade panel type."""
    require_bim(ctx)
    record = {"panelId": values["panelId"], "replacement": values["replacement"]}
    path = write_bim_json(ctx, "panel-replacement.json", record)
    return result(summary={**record, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.storefrontSystem",
    "Storefront System",
    part="bim",
    fields=[
        number("width", "System width", 6.0, unit="m", min=0.1),
        number("height", "System height", 2.7, unit="m", min=0.1),
        number("mullionSpacing", "Mullion spacing", 1.5, unit="m", min=0.1),
    ],
)
def storefront_system(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a storefront glazing system."""
    require_bim(ctx)
    bays = max(1, int(values["width"] / values["mullionSpacing"] + 0.999999))
    system = {
        "widthM": values["width"],
        "heightM": values["height"],
        "mullionSpacingM": values["mullionSpacing"],
        "bayCount": bays,
    }
    path = write_bim_json(ctx, "storefront-system.json", system)
    return result(summary={**system, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.stickSystem",
    "Stick System",
    part="bim",
    fields=[
        number("width", "Facade width", 12.0, unit="m", min=0.1),
        number("height", "Facade height", 3.2, unit="m", min=0.1),
        number("mullionSpacing", "Mullion spacing", 1.5, unit="m", min=0.1),
    ],
)
def stick_system(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a stick-built curtain-wall system."""
    require_bim(ctx)
    bays = max(1, int(values["width"] / values["mullionSpacing"] + 0.999999))
    system = {
        "widthM": values["width"],
        "heightM": values["height"],
        "mullionSpacingM": values["mullionSpacing"],
        "bayCount": bays,
    }
    path = write_bim_json(ctx, "stick-system.json", system)
    return result(summary={**system, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.unitisedSystem",
    "Unitised System",
    part="bim",
    fields=[
        number("width", "Unit width", 1.5, unit="m", min=0.1),
        number("height", "Unit height", 3.2, unit="m", min=0.1),
        number("quantity", "Unit quantity", 20, unit="ea", min=1),
    ],
)
def unitised_system(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines unitised curtain-wall modules."""
    require_bim(ctx)
    quantity = int(values["quantity"])
    area = values["width"] * values["height"] * quantity
    system = {
        "widthM": values["width"],
        "heightM": values["height"],
        "quantity": quantity,
        "totalAreaM2": area,
    }
    path = write_bim_json(ctx, "unitised-system.json", system)
    return result(summary={**system, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.cornerDetail",
    "Corner Detail",
    part="bim",
    fields=[
        select(
            "corner",
            "Corner type",
            [("miter", "Miter"), ("butt", "Butt"), ("vertical", "Vertical return")],
            "miter",
        ),
        number("angle", "Corner angle", 90, unit="°", min=1, max=180),
    ],
)
def corner_detail(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a curtain-wall corner detail."""
    require_bim(ctx)
    detail = {"cornerType": values["corner"], "angleDeg": values["angle"]}
    path = write_bim_json(ctx, "curtain-corner-detail.json", detail)
    return result(summary={**detail, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.mullionProfile",
    "Mullion Profile",
    part="bim",
    fields=[
        text("profile", "Profile name", "M150"),
        number("depth", "Depth", 150, unit="mm", min=20),
        number("width", "Width", 75, unit="mm", min=20),
    ],
)
def mullion_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a curtain mullion profile."""
    require_bim(ctx)
    profile = {"name": values["profile"], "depthMm": values["depth"], "widthMm": values["width"]}
    path = write_bim_json(ctx, "mullion-profile.json", profile)
    return result(summary={**profile, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.cornerMullion",
    "Corner Mullion",
    part="bim",
    fields=[
        text("profile", "Corner profile", "CM200"),
        number("angle", "Corner angle", 90, unit="°", min=1, max=180),
    ],
)
def corner_mullion(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adds a corner mullion profile."""
    require_bim(ctx)
    mullion = {"profile": values["profile"], "angleDeg": values["angle"]}
    path = write_bim_json(ctx, "corner-mullion.json", mullion)
    return result(summary={**mullion, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.transomProfile",
    "Transom Profile",
    part="bim",
    fields=[
        text("profile", "Transom profile", "T100"),
        number("depth", "Depth", 100, unit="mm", min=20),
        number("width", "Width", 50, unit="mm", min=20),
    ],
)
def transom_profile(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a curtain transom profile."""
    require_bim(ctx)
    profile = {"name": values["profile"], "depthMm": values["depth"], "widthMm": values["width"]}
    path = write_bim_json(ctx, "transom-profile.json", profile)
    return result(summary={**profile, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.spiderFitting",
    "Spider Fitting",
    part="bim",
    fields=[
        select("arms", "Spider arms", [("2", "2 arms"), ("3", "3 arms"), ("4", "4 arms")], "4"),
        number("diameter", "Fitting diameter", 200, unit="mm", min=50),
    ],
)
def spider_fitting(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a structural-glass spider fitting."""
    require_bim(ctx)
    fitting = {"arms": values["arms"], "diameterMm": values["diameter"]}
    path = write_bim_json(ctx, "spider-fitting.json", fitting)
    return result(summary={**fitting, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.sunshadeLouver",
    "Sunshade Louver",
    part="bim",
    fields=[
        number("length", "Louver length", 1.5, unit="m", min=0.1),
        number("depth", "Louver depth", 0.3, unit="m", min=0.01),
        number("spacing", "Louver spacing", 0.3, unit="m", min=0.05),
    ],
)
def sunshade_louver(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines exterior sunshade louvers."""
    require_bim(ctx)
    louver = {"lengthM": values["length"], "depthM": values["depth"], "spacingM": values["spacing"]}
    path = write_bim_json(ctx, "sunshade-louver.json", louver)
    return result(summary={**louver, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.structuralSilicone",
    "Structural Silicone",
    part="bim",
    fields=[
        number("thickness", "Silicone bite", 12, unit="mm", min=2),
        number("length", "Joint length", 3000, unit="mm", min=100),
    ],
)
def structural_silicone(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a structural-silicone joint."""
    require_bim(ctx)
    joint = {"biteMm": values["thickness"], "lengthMm": values["length"]}
    path = write_bim_json(ctx, "structural-silicone.json", joint)
    return result(summary={**joint, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsCurtain.thermalTransmittance",
    "Thermal Transmittance",
    part="bim",
    fields=[
        number("area", "Facade area", 100.0, unit="m²", min=0.1),
        number("uValue", "Thermal transmittance", 1.8, unit="W/m²K", min=0.1),
        number("temperatureDifference", "Design temperature difference", 20.0, unit="K", min=0),
    ],
)
def thermal_transmittance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculates steady-state facade heat flow."""
    require_bim(ctx)
    heat = values["uValue"] * values["area"] * values["temperatureDifference"]
    return result(
        summary={
            "areaM2": values["area"],
            "uValueWPerM2K": values["uValue"],
            "temperatureDifferenceK": values["temperatureDifference"],
            "heatFlowW": heat,
        },
        notes=["Heat flow uses Q = U A ΔT; it excludes thermal bridges and dynamic effects."],
    )


@feature(
    "bimAdditionsCurtain.deflectionCheck",
    "Deflection Check",
    part="bim",
    fields=[
        number("span", "Mullion span", 3.2, unit="m", min=0.1),
        number("deflection", "Calculated deflection", 12, unit="mm", min=0),
        number("limit", "Deflection limit", 16, unit="mm", min=0.1),
    ],
)
def deflection_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks facade deflection against a limit."""
    require_bim(ctx)
    ratio = values["deflection"] / values["limit"]
    passes = values["deflection"] <= values["limit"]
    return result(
        summary={
            "spanM": values["span"],
            "deflectionMm": values["deflection"],
            "limitMm": values["limit"],
            "utilization": ratio,
            "passes": passes,
        }
    )


@feature(
    "bimAdditionsCurtain.windPressureTest",
    "Wind Pressure Test",
    part="bim",
    fields=[
        number("area", "Panel area", 4.5, unit="m²", min=0.1),
        number("pressure", "Design wind pressure", 1.5, unit="kPa", min=0),
    ],
)
def wind_pressure_test(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculates wind force on a facade panel."""
    require_bim(ctx)
    force = values["pressure"] * values["area"]
    return result(
        summary={
            "panelAreaM2": values["area"],
            "pressureKpa": values["pressure"],
            "forceKn": force,
        },
        notes=[
            "Design force uses F = pA; pressure must already include the selected design coefficients."
        ],
    )
