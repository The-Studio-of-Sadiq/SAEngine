"""MEP fire protection features."""

from saengine.features import feature, number, result, table


@feature(
    "mepFire.hoseReel",
    "Hose Reel",
    part="mep",
    fields=[
        number("travel", "Travel distance", 30, unit="m", min=1),
        number("flow", "Hose reel flow", 30, unit="l/min", min=1),
    ],
    requires_project=False,
)
def hose_reel(ctx, v):
    return result(
        summary={"travelM": v["travel"], "flowLPerMin": v["flow"]},
        tables=[
            table(
                "Hose reel",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Travel", "value": v["travel"]}, {"item": "Flow", "value": v["flow"]}],
            )
        ],
        notes=[
            "Verify hose-reel travel distance and discharge against the applicable fire package."
        ],
    )


@feature(
    "mepFire.hydrantFlow",
    "Hydrant Flow",
    part="mep",
    fields=[
        number("required", "Required flow", 1000, unit="l/min", min=0),
        number("available", "Available flow", 1200, unit="l/min", min=0),
        number("pressure", "Residual pressure", 200, unit="kPa", min=0),
    ],
    requires_project=False,
)
def hydrant_flow(ctx, v):
    return result(
        summary={
            "requiredLPerMin": v["required"],
            "availableLPerMin": v["available"],
            "residualKpa": v["pressure"],
            "ok": v["available"] >= v["required"],
        },
        tables=[
            table(
                "Hydrant flow",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Required", "value": v["required"]},
                    {"item": "Available", "value": v["available"]},
                    {"item": "Pass", "value": v["available"] >= v["required"]},
                ],
            )
        ],
        notes=["Flow and residual pressure must be achieved simultaneously at the remote hydrant."],
    )


@feature(
    "mepFire.pumpCurve",
    "Pump Curve",
    part="mep",
    fields=[
        number("flow", "Rated flow", 3000, unit="l/min", min=0),
        number("head", "Rated head", 60, unit="m", min=0),
    ],
    requires_project=False,
)
def pump_curve(ctx, v):
    rows = [{"flow": v["flow"] * f, "head": v["head"] * (1 - 0.2 * f)} for f in (0.5, 1.0, 1.5)]
    return result(
        summary={"ratedFlowLPerMin": v["flow"], "ratedHeadM": v["head"]},
        tables=[table("Fire pump curve", [("flow", "Flow", "l/min"), ("head", "Head", "m")], rows)],
        notes=[
            "Illustrative linearized curve; use a manufacturer certified duty curve for selection."
        ],
    )


@feature(
    "mepFire.fireCompartments",
    "Fire Compartments",
    part="mep",
    fields=[
        number("area", "Compartment area", 1000, unit="m²", min=0.1),
        number("perimeter", "Perimeter", 150, unit="m", min=0),
    ],
    requires_project=False,
)
def fire_compartments(ctx, v):
    return result(
        summary={"areaM2": v["area"], "perimeterM": v["perimeter"]},
        tables=[
            table(
                "Fire compartment",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Area", "value": v["area"]},
                    {"item": "Perimeter", "value": v["perimeter"]},
                ],
            )
        ],
        notes=["Compartment geometry is a project review input."],
    )


@feature(
    "mepFire.fireDoors",
    "Fire Doors",
    part="mep",
    fields=[
        number("count", "Door count", 10, unit="doors", min=0),
        number("leafWidth", "Leaf width", 900, unit="mm", min=100),
    ],
    requires_project=False,
)
def fire_doors(ctx, v):
    return result(
        summary={"doorCount": int(v["count"]), "leafWidthMm": v["leafWidth"]},
        tables=[
            table(
                "Fire doors",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Door count", "value": v["count"]},
                    {"item": "Leaf width", "value": v["leafWidth"]},
                ],
            )
        ],
        notes=["Confirm door rating, hardware and closing arrangement separately."],
    )


@feature(
    "mepFire.firestoppingSeals",
    "Firestopping Seals",
    part="mep",
    fields=[
        number("penetrations", "Penetration count", 20, unit="openings", min=0),
        number("allowance", "Seal allowance", 50, unit="mm", min=0),
    ],
    requires_project=False,
)
def firestopping_seals(ctx, v):
    return result(
        summary={"penetrations": int(v["penetrations"]), "sealAllowanceMm": v["allowance"]},
        tables=[
            table(
                "Firestopping",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Penetrations", "value": v["penetrations"]},
                    {"item": "Allowance", "value": v["allowance"]},
                ],
            )
        ],
        notes=["Actual seal system selection depends on host and penetrating service."],
    )
