"""Fire protection benchmarks (BNBC 2020 Part 4): the systems a synthetic high-rise office needs,
its fire water and reservoir, the sprinkler demand and a standpipe's friction against hand
calculations.

The building (:func:`high_rise`): a basement shop floor B1 at -3.5 m, office floors GF-L10 at
3.5 m and a roof at 38.5 m, each 30 x 20 m; columns on a 6 x 5 m grid, 300 x 600 mm beams on
every grid line of every floor above the basement, 150 mm slabs. Two combined standpipe and
sprinkler risers in the stairs from B1 to L10, the pumps in B1 beside an underground fire tank.
All synthetic.

Units: l/min, m, kPa, m³, mm.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

from saengine.library.bim import BuildingModel
from saengine.library.mep import MepModel
from saengine.library.objects import ObjectLibrary
from saengine.verification.cases.common import Case, Outcome, Quantity, Reference

EXACT = 0.005
STORIES = ["B1", "GF", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9", "L10", "ROOF"]
HEIGHT = 3500
XS = [0, 6000, 12000, 18000, 24000, 30000]
YS = [0, 5000, 10000, 15000, 20000]


def high_rise_objects() -> ObjectLibrary:
    return ObjectLibrary.model_validate({"objects": [
        {"id": "C600", "name": "Column 600", "kind": "column", "material": "C25",
         "profile": {"shape": "rectangle", "xDim": 600, "yDim": 600}},
        {"id": "B300x600", "name": "Beam 300x600", "kind": "beam", "material": "C25",
         "profile": {"shape": "rectangle", "xDim": 300, "yDim": 600}},
        {"id": "S150", "name": "Slab 150", "kind": "slab", "material": "C25", "thickness": 150},
    ]})  # fmt: skip


def high_rise_bim() -> BuildingModel:
    """Thirteen levels at 3.5 m from -3.5 m; slabs, columns and beams as the module says."""
    stories = [{"id": s, "name": s, "elevation": HEIGHT * (i - 1)} for i, s in enumerate(STORIES)]
    elements: list[dict[str, Any]] = []
    outline = [[0, 0], [30000, 0], [30000, 20000], [0, 20000]]
    for i, s in enumerate(STORIES):
        z = HEIGHT * (i - 1)
        elements.append({"id": f"S-{s}", "type": "S150", "kind": "slab", "elevation": z,
                         "boundary": outline})  # fmt: skip
        if i + 1 < len(STORIES):
            for x in XS:
                for y in YS:
                    elements.append({"id": f"C-{s}-{x}-{y}", "type": "C600", "kind": "column",
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
    return BuildingModel.model_validate({"stories": stories, "elements": elements})


def high_rise_fire() -> dict[str, Any]:
    """The fire section: B1 large shops (underground mercantile), GF-L10 offices."""
    return {
        "stories": [
            {"story": "B1", "occupancy": "largeShop"},
            *({"story": s, "occupancy": "office"} for s in STORIES[1:-1]),
        ],
        "risers": [
            {
                "id": "FR1",
                "system": "combined",
                "x": 3000,
                "y": 2500,
                "fromStory": "B1",
                "toStory": "L10",
            },
            {
                "id": "FR2",
                "system": "combined",
                "x": 27000,
                "y": 17500,
                "fromStory": "B1",
                "toStory": "L10",
            },
        ],
        "mains": [
            {"id": "FM1", "story": "L3", "path": [[3000, 2500], [3000, 17500]], "diameter": 100}
        ],
        "pumpRoom": {
            "story": "B1",
            "outline": [[-9000, 0], [-1000, 0], [-1000, 6000], [-9000, 6000]],
        },
    }


def high_rise() -> tuple[MepModel, BuildingModel, ObjectLibrary]:
    mep = MepModel.model_validate({"fire": high_rise_fire()})
    return mep, high_rise_bim(), high_rise_objects()


def results() -> dict[str, Any]:
    from saengine.fire.report import fire_results

    mep, bim, objects = high_rise()
    return fire_results(mep, bim, objects)


# ─────────────────────────────── DF1: systems required ───────────────────────────────


def systems_case(_: Path) -> Outcome:
    report = results()
    status = {s["system"]: s["status"] for s in report["requirements"]["systems"]}
    count = sum(
        status[s] == "required" for s in ("manualAlarm", "hydrant", "sprinklers", "automaticAlarm")
    )
    return Outcome(
        Reference(
            "BNBC 2020 Part 1 definitions (p6), Part 4 Sec 5.7(xi) (p351), Sec 5.8.2(iii) (p351)",
            "high-rise: more than 10 storeys or 33 m; systems by the occupancy rows",
            [
                "GF-L10: 11 storeys above ground, L10 at 35 m > 33 m: high-rise",
                "offices, high-rise (Sec 5.7(xi)): manual alarm + hydrant system",
                (
                    "B1 large shops below ground (Sec 5.8.2(iii)): automatic alarm + sprinklers + "
                    "standpipe; portable extinguishers performance based"
                ),
                "4 systems required: manual alarm, hydrant, sprinklers, automatic alarm",
            ],
        ),
        [
            Quantity("High-rise", "", 1, int(report["requirements"]["highRise"]), EXACT),
            Quantity("Systems required", "", 4, count, EXACT),
        ],
    )


# ─────────────────────────────── DF2: water and reservoir ───────────────────────────────


def reservoir_case(_: Path) -> Outcome:
    report = results()
    dem = report["demand"]
    sprinkler = max(2650.0, report["hydraulics"]["sprinkler"]["sprinklerFlow"])
    flow = 1900 + 1000 + sprinkler
    volume = flow * 75 / 1000
    return Outcome(
        Reference(
            "BNBC 2020 Part 4 Table 4.4.1 (p322), Sec 4.2.3.2 (p326-327), Sec 4.2.3.5 (p328)",
            "Q = standpipe (first + 1000 l/min each other) + max(Table 4.4.1 sprinkler, "
            "hydraulic); V = Q x duration",
            [
                "B1 shops F2: ordinary hazard-I; standpipe 1900 l/min, sprinklers 2650 l/min",
                "two combined risers: 1900 + 1000 = 2900 l/min (Sec 4.2.3.2)",
                f"sprinklers: max(2650, hydraulic {sprinkler:.0f}) = {sprinkler:.0f} l/min",
                f"Q = {flow:.0f} l/min; building 38.5 m <= 51 m: 75 min",
                f"V = {flow:.0f} x 75 / 1000 = {volume:.2f} m³",
            ],
        ),
        [
            Quantity("Fire water flow", "l/min", flow, dem["flow"], EXACT),
            Quantity("Reservoir", "m³", volume, dem["volume"], EXACT),
        ],
    )


# ─────────────────────────────── DF3: sprinkler demand ───────────────────────────────


def sprinkler_case(_: Path) -> Outcome:
    from saengine.fire.sprinklers import hand_demand

    hand = hand_demand("ordinaryI")
    spr = results()["hydraulics"]["sprinkler"]
    by_hand = 6.1 * 139
    return Outcome(
        Reference(
            "NFPA 13 density/area and hose allowance (from memory, to be checked); BNBC 2020 "
            "Part 4 Table 4.4.7 (p333)",
            "Q = density x area + hose; the hydraulic calculation at least density x area",
            [
                "ordinary hazard-I: 6.1 mm/min over 139 m² = 847.9 l/min",
                "hose allowance 946 l/min: 1793.9 l/min",
                (
                    "Table 4.4.7: 12.1 m² a head; 600 m² / 54 heads = 11.1 m² a head; 13 heads in "
                    "the design area of at least 6.1 x 11.1 = 67.8 l/min"
                ),
                (
                    "the least head gives 67.8 l/min (K80 at 0.72 bar); the heads nearer the riser "
                    "more, so the sum exceeds 847.9 l/min"
                ),
            ],
        ),
        [
            Quantity("Density x area + hose", "l/min", by_hand + 946, hand["total"], EXACT),
            Quantity("Least head", "l/min", 6.1 * 600 / 54, spr["least"], 0.01),
            Quantity(
                "Hydraulic >= density x area",
                "",
                1.0,
                min(spr["sprinklerFlow"] / by_hand, 1.0),
                EXACT,
            ),
        ],
    )


# ─────────────────────────────── DF4: friction ───────────────────────────────


def friction_case(_: Path) -> Outcome:
    from saengine.fire.network import Net, fixed_head

    q = 1900.0 / 60000.0
    d = 0.1023
    hand = 10.667 * 30.0 * q**1.852 / (120.0**1.852 * d**4.871)
    net = Net(material="steel")
    net.node("PUMP", 0.0)
    net.node("TOP", 0.0)
    net.pipe("P", "PUMP", "TOP", 30.0, 100)
    net.demands["TOP"] = 1900.0
    sol = fixed_head(net, {"TOP": 0.0})
    return Outcome(
        Reference(
            "Hazen-Williams (SI, as EPANET)",
            "h = 10.667 L Q^1.852 / (C^1.852 D^4.871)",
            [
                "100 mm schedule 40 steel: bore 102.3 mm, C 120; L = 30 m; Q = 1900 l/min",
                f"h = 10.667 x 30 x 0.03167^1.852 / (120^1.852 x 0.1023^4.871) = {hand:.3f} m",
            ],
        ),
        [Quantity("Head loss", "m", hand, sol["head"], 0.01)],
    )


CASES = [
    Case(
        "DF1",
        "Fire: systems a high-rise office needs",
        "design",
        "Whether the building is high-rise, and the systems Part 4 Chapter 5 asks of its "
        "offices and its basement shops.",
        "Offices GF-L10 at 3.5 m, large shops in B1; fire.stories.",
        systems_case,
    ),
    Case(
        "DF2",
        "Fire: fire water and reservoir",
        "design",
        "The standpipe and sprinkler flows of a combined system and the reservoir for the "
        "duration of the building's height.",
        "Two combined risers B1-L10; ordinary hazard-I; fire.supply.",
        reservoir_case,
    ),
    Case(
        "DF3",
        "Fire: sprinkler demand",
        "design",
        "The design area's demand by hand (density x area + hose) and by the hydraulic "
        "calculation with the heads as emitters.",
        "B1 shops, 600 m², sprinklered; fire.sprinklers and fire.network.",
        sprinkler_case,
    ),
    Case(
        "DF4",
        "Fire: standpipe friction",
        "design",
        "EPANET's head loss in a 30 m standpipe against Hazen-Williams by hand.",
        "One 100 mm steel pipe, 1900 l/min; fire.network.",
        friction_case,
    ),
]
