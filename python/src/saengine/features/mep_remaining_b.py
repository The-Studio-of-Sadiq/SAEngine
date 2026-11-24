"""MEP fixture, equipment, containment and low-voltage features."""

from saengine.features import feature, number, result, select, table, text


@feature(
    "mepFixtures.placeFixture",
    "Place Fixture",
    part="mep",
    fields=[
        text("type", "Fixture type", "WC"),
        number("x", "X", 0, unit="mm"),
        number("y", "Y", 0, unit="mm"),
        number("height", "Mounting height", 400, unit="mm", min=0),
    ],
    requires_project=False,
)
def place_fixture(ctx, v):
    return result(
        summary={"type": v["type"], "xMm": v["x"], "yMm": v["y"], "heightMm": v["height"]},
        tables=[
            table(
                "Fixture placement",
                [("axis", "Axis"), ("value", "Value", "mm")],
                [
                    {"axis": "X", "value": v["x"]},
                    {"axis": "Y", "value": v["y"]},
                    {"axis": "Z", "value": v["height"]},
                ],
            )
        ],
        notes=["Placement coordinates are model inputs."],
    )


@feature(
    "mepFixtures.fixtureTypes",
    "Fixture Types",
    part="mep",
    fields=[
        select(
            "type",
            "Fixture type",
            [
                ("wc", "Water closet"),
                ("basin", "Basin"),
                ("shower", "Shower"),
                ("sink", "Kitchen sink"),
            ],
            "wc",
        )
    ],
    requires_project=False,
)
def fixture_types(ctx, v):
    return result(
        summary={"fixtureType": v["type"]},
        tables=[table("Fixture types", [("type", "Type")], [{"type": v["type"]}])],
        notes=["Fixture family selection."],
    )
