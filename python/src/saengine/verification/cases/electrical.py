"""Electrical coordination benchmarks (BNBC 2020 Part 8 Chapter 1): the demand and transformer,
the standby generator and its fuel, a rising main's slab opening and a cable tray's beam
openings, and the lightning protection of a synthetic eight-storey office, worked out by hand.

The building (:func:`eight_storey`): eight air-conditioned office floors GF-L7 at 3.5 m and a
roof at 28 m, each 30 x 20 m; columns on a 6 x 5 m grid (6 x 5 lines) from the ground to the
roof, each on a footing; 300 x 600 mm beams on every grid line of every floor above the ground;
150 mm slabs. Two 15 kW lifts and two 5.5 kW pumps; a busbar riser from GF to L7 outside a
shaft; a 300 x 100 mm cable tray across the L3 ceiling. All synthetic.

Units: kW, kVA, A, mm, m².
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path
from typing import Any

from saengine.library.bim import BuildingModel
from saengine.library.mep import MepModel
from saengine.library.objects import ObjectLibrary
from saengine.verification.cases.common import Case, Outcome, Quantity, Reference

EXACT = 0.005
STORIES = ["GF", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "ROOF"]
HEIGHT = 3500
XS = [0, 6000, 12000, 18000, 24000, 30000]
YS = [0, 5000, 10000, 15000, 20000]


def eight_storey_objects() -> ObjectLibrary:
    return ObjectLibrary.model_validate({"objects": [
        {"id": "C500", "name": "Column 500", "kind": "column", "material": "C25",
         "profile": {"shape": "rectangle", "xDim": 500, "yDim": 500}},
        {"id": "B300x600", "name": "Beam 300x600", "kind": "beam", "material": "C25",
         "profile": {"shape": "rectangle", "xDim": 300, "yDim": 600}},
        {"id": "S150", "name": "Slab 150", "kind": "slab", "material": "C25", "thickness": 150},
        {"id": "F2", "name": "Footing", "kind": "footing", "material": "C25", "length": 2000,
         "width": 2000, "thickness": 500},
    ]})  # fmt: skip


def eight_storey_bim() -> BuildingModel:
    """Nine levels at 3.5 m; slabs, columns, beams and footings as the module says."""
    stories = [{"id": s, "name": s, "elevation": HEIGHT * i} for i, s in enumerate(STORIES)]
    elements: list[dict[str, Any]] = []
    outline = [[0, 0], [30000, 0], [30000, 20000], [0, 20000]]
    for i, s in enumerate(STORIES):
        z = HEIGHT * i
        elements.append({"id": f"S-{s}", "type": "S150", "kind": "slab", "elevation": z,
                         "boundary": outline})  # fmt: skip
        if i + 1 < len(STORIES):
            for x in XS:
                for y in YS:
                    elements.append({"id": f"C-{s}-{x}-{y}", "type": "C500", "kind": "column",
                                     "position": [x, y], "bottom": z, "top": z + HEIGHT})  # fmt: skip
        if i == 0:
            continue
        for y in YS:
            for a, b in itertools.pairwise(XS):
                elements.append({"id": f"BX-{s}-{a}-{y}", "type": "B300x600", "kind": "beam",
                                 "start": [a, y], "end": [b, y], "elevation": z})  # fmt: skip
        for x in XS:
            for a, b in itertools.pairwise(YS):
                elements.append({"id": f"BY-{s}-{x}-{a}", "type": "B300x600", "kind": "beam",
                                 "start": [x, a], "end": [x, b], "elevation": z})  # fmt: skip
    for x in XS:
        for y in YS:
            elements.append({"id": f"F-{x}-{y}", "type": "F2", "kind": "footing",
                             "position": [x, y], "elevation": -1500})  # fmt: skip
    return BuildingModel.model_validate({"stories": stories, "elements": elements})


def eight_storey_electrical() -> dict[str, Any]:
    return {
        "supply": {"generator": True},
        "stories": [{"story": s, "use": "office", "airConditioned": True} for s in STORIES[:-1]],
        "motors": [
            {"id": "LIFT", "kind": "lift", "power": 15, "count": 2},
            {"id": "PUMP", "kind": "pump", "power": 5.5, "count": 2},
        ],
        "risers": [
            {"id": "ER1", "kind": "busbar", "x": 15000, "y": 7500, "fromStory": "GF",
             "toStory": "L7"},
        ],
        "trays": [
            {"id": "CT1", "story": "L3", "path": [[1000, 7500], [29000, 7500]], "width": 300,
             "height": 100},
        ],
        "lightning": {"enabled": True},
    }  # fmt: skip


def eight_storey() -> tuple[MepModel, BuildingModel, ObjectLibrary]:
    mep = MepModel.model_validate(
        {"schema": "saengine.mep/1", "electrical": eight_storey_electrical()}
    )
    return mep, eight_storey_bim(), eight_storey_objects()


def results() -> dict[str, Any]:
    from saengine.electrical.report import electrical_results

    mep, bim, objects = eight_storey()
    return electrical_results(mep, bim, objects)


# ─────────────────────────────── DE1: demand and transformer ───────────────────────────────


def demand_case(_: Path) -> Outcome:
    r = results()
    stories = 8 * 600 * 75 / 1000  # Table 8.1.17 office A/C 75 W/m²
    connected = stories + 2 * 15 + 2 * 5.5
    maximum = 0.8 * connected
    kva = maximum / 0.85
    return Outcome(
        Reference(
            "BNBC 2020 Part 8 Table 8.1.17 (p766), Sec 1.3.2 (p763), Sec 1.3.18.1 (p796), "
            "Table 8.1.23 (p798)",
            "P = sum(area x unit load) + motors; MD = 0.8 P; S = MD / pf; next transformer size",
            [
                "8 floors x 600 m² x 75 W/m² (office, A/C) = 360 kW",
                "lifts 2 x 15 + pumps 2 x 5.5 = 41 kW: connected 401 kW",
                "MD = 0.8 x 401 = 320.8 kW; S = 320.8 / 0.85 = 377.4 kVA -> 1 x 400 kVA",
                "Table 8.1.23 1 x 400 kVA: transformer area 13 m², substation 48 m²",
            ],
        ),
        [
            Quantity("Connected load", "kW", connected, r["demand"]["connected"], EXACT),
            Quantity("Maximum demand", "kW", maximum, r["demand"]["maximumDemand"], EXACT),
            Quantity("Maximum demand", "kVA", kva, r["demand"]["kva"], EXACT),
            Quantity("Transformer", "kVA", 400, r["supply"]["transformers"]["rating"], EXACT),
            Quantity(
                "Substation area", "m²", 48, r["supply"]["transformers"]["substationArea"], EXACT
            ),
        ],
    )


# ─────────────────────────────── DE2: generator and fuel ───────────────────────────────


def generator_case(_: Path) -> Outcome:
    gen = results()["supply"]["generator"]
    essential = 2 * 15 + 2 * 5.5 + 0.25 * 360
    fuel = 200 * 0.8 * 8 * 0.27
    return Outcome(
        Reference(
            "BNBC 2020 Part 8 Sec 1.3.19.2 (p801), Table 8.1.24 (p802); fuel rate and hours "
            "SAEngine practice",
            "kVA = essential kW / 0.8 -> next set; fuel = set kW x 8 h x 0.27 l/kWh",
            [
                "essential = lifts 30 + pumps 11 + 0.25 x 360 = 131 kW",
                "131 / 0.8 = 163.75 kVA -> 200 kVA set (160 kW)",
                "fuel = 160 x 8 x 0.27 = 345.6 l; room (Table 8.1.24, 1 x 300 kW) 48 m²",
            ],
        ),
        [
            Quantity("Essential load", "kW", essential, gen["essential"]["kw"], EXACT),
            Quantity("Generator", "kVA", 200, gen["kva"], EXACT),
            Quantity("Fuel", "l", fuel, gen["fuel"], EXACT),
            Quantity("Room area", "m²", 48, gen["roomArea"], EXACT),
        ],
    )


# ─────────────────────────────── DE3: openings ───────────────────────────────


def openings_case(_: Path) -> Outcome:
    r = results()
    riser = next(x for x in r["risers"] if x["id"] == "ER1")
    sleeves = [o for o in r["openings"] if o["id"].startswith("PE-ER1-")]
    trays = [o for o in r["openings"] if o["id"].startswith("PE-CT1-")]
    current = 8 * (0.8 * 600 * 75 / 1000 / 0.85) * 1000 / (math.sqrt(3) * 400)
    first = trays[0]
    return Outcome(
        Reference(
            "BNBC 2020 Part 8 Sec 1.3.13 (p790-792); opening allowances SAEngine practice",
            "I = S / (sqrt(3) 400 V); opening = size + 2 x 100 (riser), tray / sin + 2 x 50",
            [
                f"ER1 feeds 8 floors of 42.35 kVA: I = {current:.0f} A -> 630 A busbar 150 x 110",
                "slab opening (150 + 200) x (110 + 200) -> 350 x 350 mm on L1-L7 (7)",
                "CT1 at y = 7.5 m crosses the y-beams at x = 6, 12, 18, 24 m of the L4 floor",
                "tray 13 600-13 700 mm (L4 14 000 - 150 slab - 150 - 100), beam bottom 13 400",
                "opening 400 x 200 mm, 2500 mm from the beam start, centre 250 mm up",
            ],
        ),
        [
            Quantity("Riser current", "A", current, riser["current"], EXACT),
            Quantity("Busbar rating", "A", 630, riser["rating"], EXACT),
            Quantity("Slab openings", "", 7, len(sleeves), EXACT),
            Quantity("Slab opening width", "mm", 350, sleeves[0]["width"], EXACT),
            Quantity("Beam openings", "", 4, len(trays), EXACT),
            Quantity("Beam opening width", "mm", 400, first["width"], EXACT),
            Quantity("Beam opening height", "mm", 200, first["height"], EXACT),
            Quantity("Beam opening centre", "mm", 250, first["position"]["elevation"], EXACT),
        ],
    )


# ─────────────────────────────── DE4: lightning ───────────────────────────────


def lightning_case(_: Path) -> Outcome:
    lp = results()["lightning"]
    return Outcome(
        Reference(
            "BNBC 2020 Part 8 Tables 8.1.27-8.1.28 (p821-824), Sec 1.3.33.7-1.3.33.8 (p825-828)",
            "risk = A+B+C+D+E+F+G; n = perimeter / 30 m; spikes = roof / 80 m²; Eq 8.1.1",
            [
                (
                    "A 7 (office block) + B 2 (RC, nonmetal roof) + C 2 + D 2 + E 2 + F 11 (24-30 m) + "
                    "G 21 = 47 >= 40: protection"
                ),
                "perimeter 2 x (30 + 20) = 100 m: 4 down conductors, at the corner columns",
                "roof 600 m² / 80 = 7.5 -> at least 8 air spikes",
                "D = 0.3 x 10 + 28 / (15 x 4) = 3.47 m",
            ],
        ),
        [
            Quantity("Risk index", "", 47, lp["risk"]["total"], EXACT),
            Quantity("Down conductors", "", 4, len(lp["downConductors"]), EXACT),
            Quantity("Air terminals (at least)", "", 8, min(len(lp["airTerminals"]), 8), EXACT),
            Quantity("Clearance", "m", 0.3 * 10 + 28 / 60, lp["earth"]["clearance"], EXACT),
        ],
    )


CASES = [
    Case(
        "DE1",
        "Electrical: maximum demand and transformer",
        "design",
        "Connected load from the minimum load densities of Table 8.1.17 and the motors, the "
        "maximum demand with the 80 % load factor and the transformer and substation area.",
        "Eight air-conditioned office floors of 600 m²; electrical.report.electrical_results.",
        demand_case,
    ),
    Case(
        "DE2",
        "Electrical: standby generator and fuel",
        "design",
        "The essential load, the generator set and its fuel for eight hours, and the room area "
        "of Table 8.1.24.",
        "Lifts, pumps and a quarter of the lighting and power; electrical.supply.generator.",
        generator_case,
    ),
    Case(
        "DE3",
        "Electrical: riser and cable tray openings",
        "design",
        "The current of a busbar riser and its slab openings, and the beam web openings a cable "
        "tray needs where it crosses the beams of the floor above.",
        "Busbar ER1 GF-L7, tray CT1 under L4; electrical.risers.",
        openings_case,
    ),
    Case(
        "DE4",
        "Electrical: lightning protection",
        "design",
        "The risk index of Table 8.1.27, the number of down conductors from the perimeter, the "
        "air spikes and the clearance of Eq 8.1.1.",
        "A 30 x 20 m, 28 m office roof; electrical.lightning.lightning_protection.",
        lightning_case,
    ),
]
