"""BIM openings, penetrations and coordination feature buttons."""

from __future__ import annotations

import math
from typing import Any

from saengine.features import (
    FeatureContext,
    checkbox,
    feature,
    number,
    result,
    select,
    table,
    text,
)
from saengine.features.bim_common import require_bim, write_bim_csv, write_bim_json


@feature(
    "bimAdditionsOpenings.rectangularOpening",
    "Rectangular Opening",
    part="bim",
    fields=[
        number("width", "Opening width", 1.0, unit="m", min=0.1),
        number("height", "Opening height", 1.0, unit="m", min=0.1),
        text("host", "Host element", "W1"),
    ],
)
def rectangular_opening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a rectangular wall or slab opening."""
    require_bim(ctx)
    opening = {
        "host": values["host"],
        "widthM": values["width"],
        "heightM": values["height"],
        "areaM2": values["width"] * values["height"],
    }
    path = write_bim_json(ctx, "rectangular-opening.json", opening)
    return result(summary={**opening, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.roundOpening",
    "Round Opening",
    part="bim",
    fields=[
        number("diameter", "Opening diameter", 300, unit="mm", min=20),
        text("host", "Host element", "S1"),
    ],
)
def round_opening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a circular opening."""
    require_bim(ctx)

    area = math.pi * (values["diameter"] / 2000) ** 2
    opening = {"host": values["host"], "diameterMm": values["diameter"], "areaM2": area}
    path = write_bim_json(ctx, "round-opening.json", opening)
    return result(summary={**opening, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.lintelBeam",
    "Lintel Beam",
    part="bim",
    fields=[
        number("span", "Opening span", 1.5, unit="m", min=0.1),
        number("depth", "Lintel depth", 300, unit="mm", min=50),
        number("width", "Lintel width", 250, unit="mm", min=50),
    ],
)
def lintel_beam(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Sizes a lintel from geometry for detailing."""
    require_bim(ctx)
    volume = values["span"] * values["depth"] / 1000 * values["width"] / 1000
    lintel = {
        "spanM": values["span"],
        "depthMm": values["depth"],
        "widthMm": values["width"],
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "lintel-beam.json", lintel)
    return result(
        summary={**lintel, "exportPath": path},
        notes=["Geometry summary only; structural capacity is not assessed.", f"Export: {path}"],
    )


@feature(
    "bimAdditionsOpenings.openingTrim",
    "Opening Trim",
    part="bim",
    fields=[
        select(
            "trim",
            "Trim type",
            [("metal", "Metal"), ("masonry", "Masonry"), ("timber", "Timber")],
            "metal",
        ),
        number("thickness", "Trim thickness", 25, unit="mm", min=1),
    ],
)
def opening_trim(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines trim around an opening."""
    require_bim(ctx)
    trim = {"type": values["trim"], "thicknessMm": values["thickness"]}
    path = write_bim_json(ctx, "opening-trim.json", trim)
    return result(summary={**trim, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.shaftOpening",
    "Shaft Opening",
    part="bim",
    fields=[
        number("width", "Shaft width", 1.2, unit="m", min=0.1),
        number("length", "Shaft length", 1.8, unit="m", min=0.1),
        number("storeys", "Storey count", 3, unit="ea", min=1),
    ],
)
def shaft_opening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a vertical shaft opening."""
    require_bim(ctx)
    area = values["width"] * values["length"]
    shaft = {
        "widthM": values["width"],
        "lengthM": values["length"],
        "areaM2": area,
        "storeyCount": int(values["storeys"]),
    }
    path = write_bim_json(ctx, "shaft-opening.json", shaft)
    return result(summary={**shaft, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.coreHole",
    "Core Hole",
    part="bim",
    fields=[
        number("diameter", "Core hole diameter", 50, unit="mm", min=10),
        number("depth", "Core depth", 300, unit="mm", min=10),
    ],
)
def core_hole(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Records a core-drilled hole."""
    require_bim(ctx)

    area = math.pi * (values["diameter"] / 2000) ** 2
    volume = area * values["depth"] / 1000
    hole = {
        "diameterMm": values["diameter"],
        "depthMm": values["depth"],
        "areaM2": area,
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "core-hole.json", hole)
    return result(summary={**hole, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.pipeSleeve",
    "Pipe Sleeve",
    part="bim",
    fields=[
        number("pipeDiameter", "Pipe outside diameter", 100, unit="mm", min=10),
        number("sleeveDiameter", "Sleeve inside diameter", 150, unit="mm", min=20),
        number("length", "Sleeve length", 300, unit="mm", min=20),
    ],
)
def pipe_sleeve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a pipe sleeve and clearance."""
    require_bim(ctx)
    clearance = (values["sleeveDiameter"] - values["pipeDiameter"]) / 2
    sleeve = {
        "pipeDiameterMm": values["pipeDiameter"],
        "sleeveDiameterMm": values["sleeveDiameter"],
        "lengthMm": values["length"],
        "radialClearanceMm": clearance,
    }
    path = write_bim_json(ctx, "pipe-sleeve.json", sleeve)
    return result(summary={**sleeve, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.sumpOpening",
    "Sump Opening",
    part="bim",
    fields=[
        number("width", "Sump width", 1.0, unit="m", min=0.1),
        number("length", "Sump length", 1.0, unit="m", min=0.1),
        number("depth", "Sump depth", 0.5, unit="m", min=0.1),
    ],
)
def sump_opening(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a sump opening in a slab."""
    require_bim(ctx)
    volume = values["width"] * values["length"] * values["depth"]
    sump = {
        "widthM": values["width"],
        "lengthM": values["length"],
        "depthM": values["depth"],
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "sump-opening.json", sump)
    return result(summary={**sump, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.penetrationTrim",
    "Penetration Trim",
    part="bim",
    fields=[
        number("diameter", "Penetration diameter", 150, unit="mm", min=20),
        number("flangeWidth", "Flange width", 30, unit="mm", min=5),
        select(
            "material",
            "Trim material",
            [("steel", "Steel"), ("plastic", "Plastic"), ("timber", "Timber")],
            "steel",
        ),
    ],
)
def penetration_trim(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines trim around a service penetration."""
    require_bim(ctx)
    trim = {
        "diameterMm": values["diameter"],
        "flangeWidthMm": values["flangeWidth"],
        "material": values["material"],
    }
    path = write_bim_json(ctx, "penetration-trim.json", trim)
    return result(summary={**trim, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.clearanceCheck",
    "Clearance Check",
    part="bim",
    fields=[
        number("required", "Required clearance", 300, unit="mm", min=0),
        number("provided", "Provided clearance", 250, unit="mm", min=0),
    ],
)
def clearance_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks provided clearance against a required clearance."""
    require_bim(ctx)
    passes = values["provided"] >= values["required"]
    return result(
        summary={
            "requiredClearanceMm": values["required"],
            "providedClearanceMm": values["provided"],
            "reserveMm": values["provided"] - values["required"],
            "passes": passes,
        }
    )


@feature(
    "bimAdditionsOpenings.alignmentCheck",
    "Alignment Check",
    part="bim",
    fields=[
        number("north", "North/east north coordinate", 0.0, unit="mm"),
        number("south", "North/east south coordinate", 10.0, unit="mm"),
        number("tolerance", "Alignment tolerance", 5, unit="mm", min=0),
    ],
)
def alignment_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks two opening alignment coordinates."""
    require_bim(ctx)
    deviation = abs(values["north"] - values["south"])
    passes = deviation <= values["tolerance"]
    return result(
        summary={
            "coordinateAmm": values["north"],
            "coordinateBmm": values["south"],
            "deviationMm": deviation,
            "toleranceMm": values["tolerance"],
            "passes": passes,
        }
    )


@feature(
    "bimAdditionsOpenings.conflictCheck",
    "Conflict Check",
    part="bim",
    fields=[
        text("openingIds", "Opening ids", "O1,O2"),
        number("tolerance", "Conflict tolerance", 1, unit="mm", min=0),
    ],
)
def conflict_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Reports potential opening conflicts from a supplied id list."""
    require_bim(ctx)
    ids = [x.strip() for x in values["openingIds"].split(",") if x.strip()]
    rows = [
        {"openingA": ids[i], "openingB": ids[j], "toleranceMm": values["tolerance"]}
        for i in range(len(ids))
        for j in range(i + 1, len(ids))
    ]
    path = write_bim_csv(
        ctx, "opening-conflicts.csv", ["openingA", "openingB", "toleranceMm"], rows
    )
    return result(
        summary={
            "openingCount": len(ids),
            "potentialConflictCount": len(rows),
            "toleranceMm": values["tolerance"],
            "exportPath": path,
        },
        tables=[
            table(
                "Opening Conflict Pairs",
                [
                    ("openingA", "Opening A"),
                    ("openingB", "Opening B"),
                    ("toleranceMm", "Tolerance [mm]", "mm"),
                ],
                rows,
            )
        ],
        notes=[
            "A pairwise report is produced; coordinate overlap requires the opening boundary coordinates.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimAdditionsOpenings.penetrationSchedule",
    "Penetration Schedule",
    part="bim",
    fields=[
        text("host", "Host element", "S1"),
        number("count", "Penetration count", 4, unit="ea", min=1),
    ],
)
def penetration_schedule(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a scheduled list of penetrations."""
    require_bim(ctx)
    count = int(values["count"])
    rows = [{"number": i + 1, "host": values["host"]} for i in range(count)]
    path = write_bim_csv(ctx, "penetration-schedule.csv", ["number", "host"], rows)
    return result(
        summary={"host": values["host"], "penetrationCount": count, "exportPath": path},
        tables=[table("Penetration Schedule", [("number", "Number"), ("host", "Host")], rows)],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsOpenings.firestopCollar",
    "Firestop Collar",
    part="bim",
    fields=[
        number("pipeDiameter", "Pipe diameter", 100, unit="mm", min=20),
        number("collarHeight", "Collar height", 50, unit="mm", min=5),
    ],
)
def firestop_collar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a firestop collar."""
    require_bim(ctx)
    collar = {"pipeDiameterMm": values["pipeDiameter"], "collarHeightMm": values["collarHeight"]}
    path = write_bim_json(ctx, "firestop-collar.json", collar)
    return result(summary={**collar, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.acousticSleeve",
    "Acoustic Sleeve",
    part="bim",
    fields=[
        number("pipeDiameter", "Pipe diameter", 100, unit="mm", min=20),
        number("sleeveDiameter", "Sleeve diameter", 160, unit="mm", min=30),
        number("linerThickness", "Acoustic liner thickness", 20, unit="mm", min=1),
    ],
)
def acoustic_sleeve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines an acoustic penetration sleeve."""
    require_bim(ctx)
    sleeve = {
        "pipeDiameterMm": values["pipeDiameter"],
        "sleeveDiameterMm": values["sleeveDiameter"],
        "linerThicknessMm": values["linerThickness"],
    }
    path = write_bim_json(ctx, "acoustic-sleeve.json", sleeve)
    return result(summary={**sleeve, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.thermalBreakSleeve",
    "Thermal Break Sleeve",
    part="bim",
    fields=[
        number("pipeDiameter", "Pipe diameter", 100, unit="mm", min=20),
        number("breakThickness", "Break thickness", 10, unit="mm", min=1),
    ],
)
def thermal_break_sleeve(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a thermal-break sleeve."""
    require_bim(ctx)
    sleeve = {
        "pipeDiameterMm": values["pipeDiameter"],
        "breakThicknessMm": values["breakThickness"],
    }
    path = write_bim_json(ctx, "thermal-break-sleeve.json", sleeve)
    return result(summary={**sleeve, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.openingFraming",
    "Opening Framing",
    part="bim",
    fields=[
        select(
            "framing",
            "Framing type",
            [("steel", "Steel"), ("timber", "Timber"), ("concrete", "Concrete")],
            "steel",
        ),
        number("width", "Framing width", 100, unit="mm", min=20),
    ],
)
def opening_framing(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines framing around an opening."""
    require_bim(ctx)
    framing = {"type": values["framing"], "widthMm": values["width"]}
    path = write_bim_json(ctx, "opening-framing.json", framing)
    return result(summary={**framing, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.diagonalRebar",
    "Diagonal Rebar",
    part="bim",
    fields=[
        number("span", "Opening span", 1.0, unit="m", min=0.1),
        number("diameter", "Bar diameter", 16, unit="mm", min=6),
        number("count", "Bar count", 4, unit="ea", min=1),
    ],
)
def diagonal_rebar(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a diagonal reinforcement proposal."""
    require_bim(ctx)
    length = (values["span"] ** 2 + values["span"] ** 2) ** 0.5
    rebar = {
        "spanM": values["span"],
        "barDiameterMm": values["diameter"],
        "barCount": int(values["count"]),
        "diagonalLengthM": length,
    }
    path = write_bim_json(ctx, "diagonal-rebar.json", rebar)
    return result(
        summary={**rebar, "exportPath": path},
        notes=["Diagonal length uses a 45-degree square opening assumption.", f"Export: {path}"],
    )


@feature(
    "bimAdditionsOpenings.edgeTrimAngle",
    "Edge Trim Angle",
    part="bim",
    fields=[
        number("leg", "Angle leg", 50, unit="mm", min=10),
        number("thickness", "Thickness", 6, unit="mm", min=2),
        number("length", "Trim length", 1.0, unit="m", min=0.1),
    ],
)
def edge_trim_angle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines an edge trim angle."""
    require_bim(ctx)
    trim = {"legMm": values["leg"], "thicknessMm": values["thickness"], "lengthM": values["length"]}
    path = write_bim_json(ctx, "edge-trim-angle.json", trim)
    return result(summary={**trim, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.provisionForHole",
    "Provision For Hole",
    part="bim",
    fields=[
        text("openingId", "Opening id", "O1"),
        text("owner", "Responsible discipline", "Structural"),
        checkbox("reserved", "Reserved in model", True),
    ],
)
def provision_for_hole(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Records a hole reservation for another discipline."""
    require_bim(ctx)
    provision = {
        "openingId": values["openingId"],
        "owner": values["owner"],
        "reserved": bool(values["reserved"]),
    }
    path = write_bim_json(ctx, "hole-provision.json", provision)
    return result(summary={**provision, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsOpenings.approvalWorkflow",
    "Approval Workflow",
    part="bim",
    fields=[
        text("openingIds", "Opening ids", "O1,O2"),
        select(
            "stage",
            "Approval stage",
            [("draft", "Draft"), ("review", "In review"), ("approved", "Approved")],
            "draft",
        ),
    ],
)
def approval_workflow(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Assigns an approval stage to openings."""
    require_bim(ctx)
    ids = [x.strip() for x in values["openingIds"].split(",") if x.strip()]
    rows = [{"openingId": i, "stage": values["stage"]} for i in ids]
    path = write_bim_csv(ctx, "opening-approval.csv", ["openingId", "stage"], rows)
    return result(
        summary={"openingCount": len(ids), "stage": values["stage"], "exportPath": path},
        tables=[table("Opening Approval", [("openingId", "Opening id"), ("stage", "Stage")], rows)],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsOpenings.voidReservationList",
    "Void Reservation List",
    part="bim",
    fields=[
        text("service", "Service", "Drainage"),
        number("count", "Reservation count", 5, unit="ea", min=1),
    ],
)
def void_reservation_list(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a void reservation list."""
    require_bim(ctx)
    count = int(values["count"])
    rows = [{"reservation": i + 1, "service": values["service"]} for i in range(count)]
    path = write_bim_csv(ctx, "void-reservation-list.csv", ["reservation", "service"], rows)
    return result(
        summary={"service": values["service"], "reservationCount": count, "exportPath": path},
        tables=[
            table(
                "Void Reservations", [("reservation", "Reservation"), ("service", "Service")], rows
            )
        ],
        notes=[f"Export: {path}"],
    )
