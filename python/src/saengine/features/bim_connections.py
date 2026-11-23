"""BIM structural connection detail feature buttons."""

from __future__ import annotations

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
from saengine.features.bim_common import require_bim, write_bim_csv, write_bim_json


@feature(
    "bimAdditionsConnections.momentConnection",
    "Moment Connection",
    part="bim",
    fields=[
        text("memberA", "Member A", "B1"),
        text("memberB", "Member B", "C1"),
        select(
            "joint", "Joint type", [("full", "Full moment"), ("partial", "Partial moment")], "full"
        ),
    ],
)
def moment_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a moment-resisting connection definition."""
    require_bim(ctx)
    conn = {"memberA": values["memberA"], "memberB": values["memberB"], "joint": values["joint"]}
    path = write_bim_json(ctx, "moment-connection.json", conn)
    return result(
        summary={
            "memberA": values["memberA"],
            "memberB": values["memberB"],
            "jointType": values["joint"],
            "exportPath": path,
        },
        tables=[
            table(
                "Moment Connection",
                [("memberA", "Member A"), ("memberB", "Member B"), ("joint", "Joint")],
                [conn],
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsConnections.shearConnection",
    "Shear Connection",
    part="bim",
    fields=[
        text("beam", "Beam", "B1"),
        text("column", "Column", "C1"),
        number("reaction", "Reaction", 100, unit="kN", min=0),
    ],
)
def shear_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Records the beam reaction and connected members for connection design."""
    require_bim(ctx)
    conn = {
        "beam": values["beam"],
        "column": values["column"],
        "reactionKn": values["reaction"],
    }
    path = write_bim_json(ctx, "shear-connection.json", conn)
    return result(
        summary={**conn, "exportPath": path},
        tables=[
            table(
                "Shear Connection",
                [
                    ("beam", "Beam"),
                    ("column", "Column"),
                    ("reactionKn", "Reaction [kN]", "kN"),
                ],
                [conn],
            )
        ],
        notes=[
            "This is a connection-design input record, not a resistance check or bolt schedule.",
            f"Export: {path}",
        ],
    )


@feature(
    "bimAdditionsConnections.bracingConnection",
    "Bracing Connection",
    part="bim",
    fields=[
        text("brace", "Brace member", "M2"),
        text("frame", "Frame member", "C1"),
        number("axialForce", "Axial force", 50, unit="kN"),
    ],
)
def bracing_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a brace-to-frame connection detail."""
    require_bim(ctx)
    conn = {"brace": values["brace"], "frame": values["frame"], "axialKn": values["axialForce"]}
    path = write_bim_json(ctx, "bracing-connection.json", conn)
    return result(
        summary={
            "brace": values["brace"],
            "frame": values["frame"],
            "axialForceKn": values["axialForce"],
            "exportPath": path,
        },
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsConnections.baseConnection",
    "Base Connection",
    part="bim",
    fields=[
        text("column", "Column", "C1"),
        number("axial", "Axial force", 500, unit="kN"),
        number("moment", "Base moment", 50, unit="kN·m"),
    ],
)
def base_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a base connection record."""
    require_bim(ctx)
    conn = {"column": values["column"], "axialKn": values["axial"], "momentKnM": values["moment"]}
    path = write_bim_json(ctx, "base-connection.json", conn)
    return result(summary={**conn, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsConnections.spliceConnection",
    "Splice Connection",
    part="bim",
    fields=[
        text("member", "Member", "C1"),
        number("axial", "Axial force", 300, unit="kN"),
        number("height", "Splice height", 3200, unit="mm", min=1),
    ],
)
def splice_connection(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a member splice location."""
    require_bim(ctx)
    conn = {"member": values["member"], "axialKn": values["axial"], "heightMm": values["height"]}
    path = write_bim_json(ctx, "splice-connection.json", conn)
    return result(summary={**conn, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsConnections.basePlate",
    "Base Plate",
    part="bim",
    fields=[
        number("length", "Plate length", 500, unit="mm", min=20),
        number("width", "Plate width", 500, unit="mm", min=20),
        number("thickness", "Plate thickness", 25, unit="mm", min=3),
    ],
)
def base_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a rectangular column base plate."""
    require_bim(ctx)
    area = values["length"] * values["width"] / 1e6
    volume = area * values["thickness"] / 1000
    plate = {
        "lengthMm": values["length"],
        "widthMm": values["width"],
        "thicknessMm": values["thickness"],
        "areaM2": area,
        "volumeM3": volume,
    }
    path = write_bim_json(ctx, "base-plate.json", plate)
    return result(
        summary={**plate, "exportPath": path},
        tables=[
            table(
                "Base Plate",
                [
                    ("lengthMm", "Length [mm]", "mm"),
                    ("widthMm", "Width [mm]", "mm"),
                    ("thicknessMm", "Thickness [mm]", "mm"),
                    ("areaM2", "Area [m²]", "m²"),
                ],
                [plate],
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsConnections.gussetPlate",
    "Gusset Plate",
    part="bim",
    fields=[
        number("width", "Gusset width", 300, unit="mm", min=20),
        number("height", "Gusset height", 300, unit="mm", min=20),
        number("thickness", "Plate thickness", 12, unit="mm", min=3),
    ],
)
def gusset_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a triangular gusset plate estimate."""
    require_bim(ctx)
    area = 0.5 * values["width"] * values["height"] / 1e6
    plate = {
        "widthMm": values["width"],
        "heightMm": values["height"],
        "thicknessMm": values["thickness"],
        "areaM2": area,
    }
    path = write_bim_json(ctx, "gusset-plate.json", plate)
    return result(
        summary={**plate, "exportPath": path},
        notes=["Triangular area assumes perpendicular legs.", f"Export: {path}"],
    )


@feature(
    "bimAdditionsConnections.stiffenerPlate",
    "Stiffener Plate",
    part="bim",
    fields=[
        number("length", "Stiffener length", 300, unit="mm", min=20),
        number("width", "Stiffener width", 100, unit="mm", min=20),
        number("thickness", "Thickness", 10, unit="mm", min=3),
    ],
)
def stiffener_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a stiffener plate."""
    require_bim(ctx)
    plate = {
        "lengthMm": values["length"],
        "widthMm": values["width"],
        "thicknessMm": values["thickness"],
    }
    path = write_bim_json(ctx, "stiffener-plate.json", plate)
    return result(summary={**plate, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsConnections.cleatPlate",
    "Cleat Plate",
    part="bim",
    fields=[
        number("length", "Leg length", 150, unit="mm", min=20),
        number("width", "Cleat width", 100, unit="mm", min=20),
        number("thickness", "Thickness", 10, unit="mm", min=3),
    ],
)
def cleat_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines an angle cleat plate."""
    require_bim(ctx)
    plate = {
        "lengthMm": values["length"],
        "widthMm": values["width"],
        "thicknessMm": values["thickness"],
    }
    path = write_bim_json(ctx, "cleat-plate.json", plate)
    return result(summary={**plate, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsConnections.boltLayout",
    "Bolt Layout",
    part="bim",
    fields=[
        number("rows", "Bolt rows", 2, unit="ea", min=1),
        number("cols", "Bolt columns", 2, unit="ea", min=1),
        number("pitch", "Bolt pitch", 75, unit="mm", min=10),
        number("edge", "Edge distance", 40, unit="mm", min=5),
    ],
)
def bolt_layout(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a rectangular bolt layout."""
    require_bim(ctx)
    rows = int(values["rows"])
    cols = int(values["cols"])
    layout = [
        {
            "row": r + 1,
            "col": c + 1,
            "xMm": values["edge"] + c * values["pitch"],
            "yMm": values["edge"] + r * values["pitch"],
        }
        for r in range(rows)
        for c in range(cols)
    ]
    path = write_bim_csv(ctx, "bolt-layout.csv", ["row", "col", "xMm", "yMm"], layout)
    return result(
        summary={
            "boltCount": len(layout),
            "pitchMm": values["pitch"],
            "edgeDistanceMm": values["edge"],
            "exportPath": path,
        },
        tables=[
            table(
                "Bolt Layout",
                [
                    ("row", "Row"),
                    ("col", "Column"),
                    ("xMm", "X [mm]", "mm"),
                    ("yMm", "Y [mm]", "mm"),
                ],
                layout,
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsConnections.weldSymbol",
    "Weld Symbol",
    part="bim",
    fields=[
        select(
            "weld",
            "Weld type",
            [("fillet", "Fillet"), ("butt", "Butt"), ("plug", "Plug")],
            "fillet",
        ),
        number("size", "Weld size", 8, unit="mm", min=1),
        number("length", "Weld length", 200, unit="mm", min=1),
    ],
)
def weld_symbol(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Adds a weld symbol specification."""
    require_bim(ctx)
    weld = {"type": values["weld"], "sizeMm": values["size"], "lengthMm": values["length"]}
    path = write_bim_json(ctx, "weld-symbol.json", weld)
    return result(summary={**weld, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsConnections.holePattern",
    "Hole Pattern",
    part="bim",
    fields=[
        number("diameter", "Hole diameter", 22, unit="mm", min=2),
        number("countX", "X count", 3, unit="ea", min=1),
        number("countY", "Y count", 2, unit="ea", min=1),
        number("pitch", "Pitch", 75, unit="mm", min=5),
    ],
)
def hole_pattern(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Creates a rectangular hole pattern."""
    require_bim(ctx)
    nx = int(values["countX"])
    ny = int(values["countY"])
    holes = [
        {
            "hole": i * ny + j + 1,
            "xMm": i * values["pitch"],
            "yMm": j * values["pitch"],
            "diameterMm": values["diameter"],
        }
        for i in range(nx)
        for j in range(ny)
    ]
    path = write_bim_csv(ctx, "hole-pattern.csv", ["hole", "xMm", "yMm", "diameterMm"], holes)
    return result(
        summary={
            "holeCount": len(holes),
            "holeDiameterMm": values["diameter"],
            "pitchMm": values["pitch"],
            "exportPath": path,
        },
        tables=[
            table(
                "Hole Pattern",
                [
                    ("hole", "Hole"),
                    ("xMm", "X [mm]", "mm"),
                    ("yMm", "Y [mm]", "mm"),
                    ("diameterMm", "Diameter [mm]", "mm"),
                ],
                holes,
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsConnections.edgeDistance",
    "Edge Distance",
    part="bim",
    fields=[
        number("provided", "Provided edge distance", 40, unit="mm", min=0),
        number("minimum", "Minimum edge distance", 30, unit="mm", min=0),
    ],
)
def edge_distance(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks edge distance against a supplied minimum."""
    require_bim(ctx)
    passes = values["provided"] >= values["minimum"]
    return result(
        summary={
            "providedMm": values["provided"],
            "minimumMm": values["minimum"],
            "reserveMm": values["provided"] - values["minimum"],
            "passes": passes,
        }
    )


@feature(
    "bimAdditionsConnections.seatAngle",
    "Seat Angle",
    part="bim",
    fields=[
        number("length", "Seat length", 150, unit="mm", min=20),
        number("leg", "Angle leg", 100, unit="mm", min=20),
        number("thickness", "Thickness", 10, unit="mm", min=3),
    ],
)
def seat_angle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a beam seat angle."""
    require_bim(ctx)
    angle = {
        "lengthMm": values["length"],
        "legMm": values["leg"],
        "thicknessMm": values["thickness"],
    }
    path = write_bim_json(ctx, "seat-angle.json", angle)
    return result(summary={**angle, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsConnections.clipAngle",
    "Clip Angle",
    part="bim",
    fields=[
        number("length", "Clip length", 150, unit="mm", min=20),
        number("legA", "Leg A", 75, unit="mm", min=20),
        number("legB", "Leg B", 75, unit="mm", min=20),
        number("thickness", "Thickness", 8, unit="mm", min=3),
    ],
)
def clip_angle(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a clip angle."""
    require_bim(ctx)
    angle = {
        "lengthMm": values["length"],
        "legAMm": values["legA"],
        "legBMm": values["legB"],
        "thicknessMm": values["thickness"],
    }
    path = write_bim_json(ctx, "clip-angle.json", angle)
    return result(summary={**angle, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsConnections.flangeStiffener",
    "Flange Stiffener",
    part="bim",
    fields=[
        number("width", "Stiffener width", 150, unit="mm", min=20),
        number("length", "Stiffener length", 300, unit="mm", min=20),
        number("thickness", "Thickness", 12, unit="mm", min=3),
    ],
)
def flange_stiffener(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a member flange stiffener."""
    require_bim(ctx)
    plate = {
        "widthMm": values["width"],
        "lengthMm": values["length"],
        "thicknessMm": values["thickness"],
    }
    path = write_bim_json(ctx, "flange-stiffener.json", plate)
    return result(summary={**plate, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsConnections.anchorRods",
    "Anchor Rods",
    part="bim",
    fields=[
        number("diameter", "Rod diameter", 24, unit="mm", min=6),
        number("count", "Rod count", 4, unit="ea", min=1),
        number("embedment", "Embedment length", 300, unit="mm", min=50),
    ],
)
def anchor_rods(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedules anchor rods."""
    require_bim(ctx)
    count = int(values["count"])
    rows = [
        {"rod": i + 1, "diameterMm": values["diameter"], "embedmentMm": values["embedment"]}
        for i in range(count)
    ]
    path = write_bim_csv(ctx, "anchor-rods.csv", ["rod", "diameterMm", "embedmentMm"], rows)
    return result(
        summary={
            "rodCount": count,
            "rodDiameterMm": values["diameter"],
            "embedmentMm": values["embedment"],
            "exportPath": path,
        },
        tables=[
            table(
                "Anchor Rods",
                [
                    ("rod", "Rod"),
                    ("diameterMm", "Diameter [mm]", "mm"),
                    ("embedmentMm", "Embedment [mm]", "mm"),
                ],
                rows,
            )
        ],
        notes=[f"Export: {path}"],
    )


@feature(
    "bimAdditionsConnections.embedPlate",
    "Embed Plate",
    part="bim",
    fields=[
        number("length", "Plate length", 300, unit="mm", min=20),
        number("width", "Plate width", 300, unit="mm", min=20),
        number("thickness", "Thickness", 16, unit="mm", min=3),
    ],
)
def embed_plate(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Defines a cast-in embed plate."""
    require_bim(ctx)
    plate = {
        "lengthMm": values["length"],
        "widthMm": values["width"],
        "thicknessMm": values["thickness"],
    }
    path = write_bim_json(ctx, "embed-plate.json", plate)
    return result(summary={**plate, "exportPath": path}, notes=[f"Export: {path}"])


@feature(
    "bimAdditionsConnections.chemicalAnchor",
    "Chemical Anchor",
    part="bim",
    fields=[
        number("diameter", "Anchor diameter", 16, unit="mm", min=6),
        number("embedment", "Embedment length", 160, unit="mm", min=30),
        number("count", "Anchor count", 4, unit="ea", min=1),
    ],
)
def chemical_anchor(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Schedules chemical anchors."""
    require_bim(ctx)
    count = int(values["count"])
    return result(
        summary={
            "anchorCount": count,
            "diameterMm": values["diameter"],
            "embedmentMm": values["embedment"],
        },
        notes=[
            "Anchor adhesive system and substrate strength must be supplied by the anchorage design."
        ],
    )


@feature(
    "bimAdditionsConnections.feaJointCheck",
    "FEA Joint Check",
    part="bim",
    fields=[
        number("axial", "Axial force", 500, unit="kN"),
        number("shear", "Shear force", 100, unit="kN"),
        number("moment", "Bending moment", 50, unit="kN·m"),
    ],
)
def fea_joint_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Summarises joint actions for a finite-element check."""
    require_bim(ctx)
    demand = (values["axial"] ** 2 + values["shear"] ** 2) ** 0.5
    return result(
        summary={
            "axialForceKn": values["axial"],
            "shearForceKn": values["shear"],
            "momentKnM": values["moment"],
            "combinedPlanarDemandKn": demand,
        },
        tables=[
            table(
                "Joint Demand",
                [
                    ("axialForceKn", "Axial [kN]", "kN"),
                    ("shearForceKn", "Shear [kN]", "kN"),
                    ("momentKnM", "Moment [kN·m]", "kN·m"),
                ],
                [
                    {
                        "axialForceKn": values["axial"],
                        "shearForceKn": values["shear"],
                        "momentKnM": values["moment"],
                    }
                ],
            )
        ],
        notes=[
            "Planar resultant is a report metric; resistance and failure surfaces require an FE model."
        ],
    )


@feature(
    "bimAdditionsConnections.weldCapacity",
    "Weld Capacity",
    part="bim",
    fields=[
        number("throat", "Effective throat", 6, unit="mm", min=1),
        number("length", "Weld length", 200, unit="mm", min=1),
        number("allowableStress", "Allowable stress", 150, unit="MPa", min=1),
    ],
)
def weld_capacity(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Calculates an explicit-user-input weld capacity."""
    require_bim(ctx)
    area = values["throat"] * values["length"]
    capacity = area * values["allowableStress"] / 1000
    return result(
        summary={
            "effectiveAreaMm2": area,
            "allowableStressMpa": values["allowableStress"],
            "capacityKn": capacity,
        },
        notes=[
            "Capacity is area × supplied stress/1000; the stress input must reflect the applicable project rules and load combination."
        ],
    )


@feature(
    "bimAdditionsConnections.boltGroupCheck",
    "Bolt Group Check",
    part="bim",
    fields=[
        number("boltCount", "Bolt count", 4, unit="ea", min=1),
        number("individualCapacity", "Capacity per bolt", 50, unit="kN", min=0),
        number("appliedForce", "Applied force", 150, unit="kN", min=0),
    ],
)
def bolt_group_check(ctx: FeatureContext, values: dict[str, Any]) -> dict[str, Any]:
    """Checks a simplified equal-bolt-group capacity."""
    require_bim(ctx)
    capacity = values["boltCount"] * values["individualCapacity"]
    utilization = values["appliedForce"] / capacity if capacity > 0 else 1e9
    return result(
        summary={
            "boltCount": int(values["boltCount"]),
            "capacityKn": capacity,
            "appliedForceKn": values["appliedForce"],
            "utilization": utilization,
            "passes": utilization <= 1,
        },
        notes=[
            "Equal distribution is assumed; eccentricity and bolt-row load distribution require a dedicated connection model."
        ],
    )
