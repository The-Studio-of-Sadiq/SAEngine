"""MEP electrical circuits and panel features."""

from __future__ import annotations

from saengine.features import (
    FeatureInputError,
    feature,
    number,
    result,
    table,
)


def _electrical_data(ctx):
    raw = ctx.raw("mep")
    if raw is None:
        raise FeatureInputError("Add 07 MEP/mep.json to the project.")
    return raw.get("electrical") or {}


def _boards(electrical):
    boards = electrical.get("boards", [])
    return boards if isinstance(boards, list) else []


def _circuits(electrical):
    return [
        circuit
        for board in _boards(electrical)
        for circuit in board.get("circuits", [])
        if isinstance(circuit, dict)
    ]


def _board_load(board):
    return sum(
        (circuit.get("loadW") or circuit.get("loadVA") or 0) / 1000
        for circuit in board.get("circuits", [])
        if isinstance(circuit, dict)
    )


@feature(
    "mepElectrical.circuitManager",
    "Circuit Manager",
    part="mep",
    fields=[number("circuits", "Circuit count", 12, unit="circuits", min=1)],
    requires_project=True,
)
def circuit_manager(ctx, v):
    electrical = _electrical_data(ctx)
    supply = electrical.get("supply") or {}
    return result(
        summary={"circuits": int(v["circuits"])},
        tables=[
            table(
                "Circuit manager",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Circuits", "value": v["circuits"]},
                    {
                        "item": "Supply",
                        "value": supply.get("voltage") or supply.get("utility") or "None",
                    },
                ],
            )
        ],
        notes=["Circuit grouping is prepared from the electrical model."],
    )


@feature(
    "mepElectrical.circuitSchedule",
    "Circuit Schedule",
    part="mep",
    fields=[],
    requires_project=True,
)
def circuit_schedule(ctx, v):
    electrical = _electrical_data(ctx)
    rows = [
        {
            "id": c.get("id", ""),
            "load": (c.get("loadW") or c.get("loadVA") or 0) / 1000,
            "phases": c.get("phases", 1),
            "breaker": c.get("rating"),
        }
        for c in _circuits(electrical)
    ]
    return result(
        summary={"circuits": len(rows)},
        tables=[
            table(
                "Circuit schedule",
                [
                    ("id", "Circuit"),
                    ("load", "Load", "kW"),
                    ("phases", "Phases"),
                    ("breaker", "Breaker", "A"),
                ],
                rows,
            )
        ],
        notes=["Circuits are read from 07 MEP/mep.json."],
    )


@feature("mepElectrical.loadBalance", "Load Balance", part="mep", fields=[], requires_project=True)
def load_balance(ctx, v):
    electrical = _electrical_data(ctx)
    rows = [
        {
            "id": c.get("id", ""),
            "phases": c.get("phases", 1),
            "load": (c.get("loadW") or c.get("loadVA") or 0) / 1000,
        }
        for c in _circuits(electrical)
    ]
    l = sum(r["load"] for r in rows)
    p = max((r["phases"] for r in rows), default=3)
    return result(
        summary={"connectedKw": l, "perPhaseKw": l / p if p else l},
        tables=[
            table(
                "Load balance",
                [("id", "Circuit"), ("phases", "Phases"), ("load", "Load", "kW")],
                rows,
            )
        ],
        notes=["Equal share estimate for the assigned phase count."],
    )


@feature(
    "mepElectrical.placeSocket",
    "Place Socket",
    part="mep",
    fields=[
        number("x", "X", 0, unit="mm"),
        number("y", "Y", 0, unit="mm"),
        number("height", "Mounting height", 300, unit="mm", min=0),
    ],
    requires_project=False,
)
def place_socket(ctx, v):
    return result(
        summary={"xMm": v["x"], "yMm": v["y"], "heightMm": v["height"]},
        tables=[
            table(
                "Socket position",
                [("axis", "Axis"), ("value", "Value", "mm")],
                [
                    {"axis": "X", "value": v["x"]},
                    {"axis": "Y", "value": v["y"]},
                    {"axis": "Z", "value": v["height"]},
                ],
            )
        ],
        notes=["Position is a model placement coordinate."],
    )


@feature(
    "mepElectrical.placeSwitch",
    "Place Switch",
    part="mep",
    fields=[
        number("x", "X", 0, unit="mm"),
        number("y", "Y", 0, unit="mm"),
        number("height", "Mounting height", 1200, unit="mm", min=0),
    ],
    requires_project=False,
)
def place_switch(ctx, v):
    return result(
        summary={"xMm": v["x"], "yMm": v["y"], "heightMm": v["height"]},
        tables=[
            table(
                "Switch position",
                [("axis", "Axis"), ("value", "Value", "mm")],
                [
                    {"axis": "X", "value": v["x"]},
                    {"axis": "Y", "value": v["y"]},
                    {"axis": "Z", "value": v["height"]},
                ],
            )
        ],
        notes=["Position is a model placement coordinate."],
    )


@feature(
    "mepElectrical.distributionBoard",
    "Distribution Board",
    part="mep",
    fields=[
        number("ways", "Number of ways", 12, unit="ways", min=1),
        number("incomer", "Incomer rating", 100, unit="A", min=1),
    ],
    requires_project=False,
)
def distribution_board(ctx, v):
    return result(
        summary={"ways": int(v["ways"]), "incomerA": v["incomer"]},
        tables=[
            table(
                "Distribution board",
                [("item", "Item"), ("value", "Value")],
                [{"item": "Ways", "value": v["ways"]}, {"item": "Incomer", "value": v["incomer"]}],
            )
        ],
        notes=["Board data for schedule and panel-layout planning."],
    )


@feature(
    "mepElectrical.panelSchedule", "Panel Schedule", part="mep", fields=[], requires_project=True
)
def panel_schedule(ctx, v):
    electrical = _electrical_data(ctx)
    rows = [
        {
            "id": p.get("id", ""),
            "name": p.get("name", ""),
            "rating": p.get("incomerRating") or p.get("busbarRating"),
            "location": p.get("room") or p.get("story", ""),
        }
        for p in _boards(electrical)
    ]
    return result(
        summary={"panels": len(rows)},
        tables=[
            table(
                "Panel schedule",
                [
                    ("id", "Panel"),
                    ("name", "Name"),
                    ("rating", "Rating", "A"),
                    ("location", "Location"),
                ],
                rows,
            )
        ],
        notes=["Panel data is read from 07 MEP/mep.json."],
    )


@feature(
    "mepElectrical.panelLoadCalc", "Panel Load Calc", part="mep", fields=[], requires_project=True
)
def panel_load_calc(ctx, v):
    electrical = _electrical_data(ctx)
    rows = [
        {
            "id": p.get("id", ""),
            "load": _board_load(p),
            "rating": p.get("incomerRating") or p.get("busbarRating"),
            "util": _board_load(p) / (p.get("incomerRating") or p.get("busbarRating"))
            if (p.get("incomerRating") or p.get("busbarRating"))
            else None,
        }
        for p in _boards(electrical)
    ]
    return result(
        summary={"panels": len(rows)},
        tables=[
            table(
                "Panel loads",
                [
                    ("id", "Panel"),
                    ("load", "Load", "kW"),
                    ("rating", "Rating", "A"),
                    ("util", "Utilisation"),
                ],
                rows,
            )
        ],
        notes=[
            "Utilisation requires comparable kW and kVA units; review before protection selection."
        ],
    )


@feature(
    "mepElectrical.spareWays",
    "Spare Ways",
    part="mep",
    fields=[number("sparePercent", "Spare capacity", 20, unit="%", min=0, max=100)],
    requires_project=True,
)
def spare_ways(ctx, v):
    electrical = _electrical_data(ctx)
    ways = sum(p.get("ways") or 0 for p in _boards(electrical))
    spare = round(ways * v["sparePercent"] / 100)
    return result(
        summary={"ways": ways, "spareWays": spare},
        tables=[
            table(
                "Spare ways",
                [("item", "Item"), ("value", "Value")],
                [
                    {"item": "Existing ways", "value": ways},
                    {"item": "Recommended spare", "value": spare},
                ],
            )
        ],
        notes=["Recommended spare ways = entered spare percentage of panel ways."],
    )


@feature(
    "mepElectrical.panelUpgrade",
    "Panel Upgrade",
    part="mep",
    fields=[
        number("existing", "Existing rating", 100, unit="A", min=1),
        number("required", "Required rating", 160, unit="A", min=1),
    ],
    requires_project=False,
)
def panel_upgrade(ctx, v):
    return result(
        summary={"upgradeRequired": v["required"] > v["existing"], "recommendedA": v["required"]},
        tables=[
            table(
                "Panel upgrade",
                [("item", "Rating", "A")],
                [
                    {"item": "Existing", "value": v["existing"]},
                    {"item": "Required", "value": v["required"]},
                ],
            )
        ],
        notes=["Upgrade if required rating exceeds existing rating."],
    )
