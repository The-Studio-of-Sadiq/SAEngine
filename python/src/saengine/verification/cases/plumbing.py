"""Plumbing sizing benchmarks (BNBC 2020 Part 8): demand, storage, a riser, a stack, a leader
and a septic tank of a synthetic six-storey residential building, worked out by hand from the
table rows.

The building (:func:`six_storey`): a ground floor (parking, no fixtures) and five residential
floors L1-L5 at 3 m, a roof at 18 m; each floor 14 x 10 m with four flats of two bathrooms
(water closet with a cistern, wash basin, shower) and a kitchen sink; two cold water risers,
two soil and two waste stacks, a vent stack, a pump main, two roof drains and two leaders; an
overhead tank, an underground reservoir, a septic tank and a soak well. All synthetic.

Units: litres, mm, m², l/min.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from saengine.library.bim import BuildingModel
from saengine.library.mep import MepModel
from saengine.verification.cases.common import Case, Outcome, Quantity, Reference

EXACT = 0.005
STORIES = ["GF", "L1", "L2", "L3", "L4", "L5", "ROOF"]
FLOOR = {"wc": 8, "basin": 8, "shower": 8, "kitchenSink": 4}


def six_storey_bim() -> BuildingModel:
    """Seven levels at 3 m and a 14 x 10 m slab on every level above the ground."""
    stories = [{"id": s, "name": s, "elevation": 3000 * i} for i, s in enumerate(STORIES)]
    slabs = [
        {
            "id": f"S-{s}", "type": "SL150", "kind": "slab", "elevation": 3000 * i,
            "boundary": [[0, 0], [14000, 0], [14000, 10000], [0, 10000]],
        }
        for i, s in enumerate(STORIES)
        if i > 0
    ]  # fmt: skip
    return BuildingModel.model_validate({"stories": stories, "elements": slabs})


def six_storey_plumbing() -> dict[str, Any]:
    def riser(rid: str, system: str, x: float, y: float, **extra: Any) -> dict[str, Any]:
        return {"id": rid, "system": system, "x": x, "y": y, "fromStory": "GF",
                "toStory": "ROOF", "material": "uPVC", **extra}  # fmt: skip

    return {
        "supply": {"source": "mains"},
        "stories": [
            {"story": s, "occupancy": "residentialFlat", "fixtures": dict(FLOOR)}
            for s in STORIES[1:6]
        ],
        "risers": [
            riser("R1", "coldWater", 3000, 5000),
            riser("R2", "coldWater", 11000, 5000),
            riser("S1", "soil", 3000, 4000),
            riser("S2", "soil", 11000, 4000),
            riser("W1", "waste", 3500, 4000),
            riser("W2", "waste", 11500, 4000),
            riser("V1", "vent", 3000, 3500),
            riser("P1", "pumpMain", 7000, 5000),
            riser("RW1", "rainwater", 500, 5000),
            riser("RW2", "rainwater", 13500, 5000),
        ],
        "tanks": [
            {"id": "T1", "kind": "overhead", "story": "ROOF", "x": 7000, "y": 5000},
            {"id": "T2", "kind": "underground", "x": 3000, "y": -3000},
            {"id": "T3", "kind": "septic", "x": 11000, "y": -15000},
            {
                "id": "T4",
                "kind": "soakWell",
                "x": 11000,
                "y": -22000,
                "diameter": 2000,
                "percolation": 5,
            },
        ],
        "roof": {
            "rainfallIntensity": 88,
            "drains": [
                {"id": "RD1", "x": 3500, "y": 5000, "story": "ROOF"},
                {"id": "RD2", "x": 10500, "y": 5000, "story": "ROOF"},
            ],
        },
    }


def six_storey() -> tuple[MepModel, BuildingModel]:
    mep = MepModel.model_validate({"schema": "saengine.mep/1", "plumbing": six_storey_plumbing()})
    return mep, six_storey_bim()


def _results() -> dict[str, Any]:
    from saengine.plumbing.report import plumbing_results

    mep, bim = six_storey()
    return plumbing_results(mep, bim)


def _riser(result: dict[str, Any], rid: str) -> dict[str, Any]:
    return next(r for r in [*result["stacks"], *result["risers"]] if r["id"] == rid)


# ─────────────────────────────── PL1: demand and storage ───────────────────────────────


def demand_case(_: Path) -> Outcome:
    r = _results()
    population = 5 * 4 * 5  # 5 floors x 4 flats x 5 persons (Sec 5.6.3)
    daily = population * 180  # Table 8.5.1(a) y1 moderate apartment, full facility
    peak = daily / 16 * 2.2 / 60  # Eq 8.5.1, l/min
    return Outcome(
        Reference(
            "BNBC 2020 Part 8 Table 8.5.1(a) (p1034), Sec 5.6.3 (p1039), Eq 8.5.1 (p1043), "
            "Sec 5.9.1.2(c) (p1041), Tables 8.5.2-8.5.3 (p1042)",
            "Q = P x lpcd; roof tank = Q/2, reservoir = Q (no fire reserve below 33 m)",
            [
                "P = 5 floors x 4 flats (one kitchen sink each) x 5 persons = 100",
                "Q = 100 x 180 lpcd = 18 000 l/day = 18 m³",
                "peak hourly = 18 000 / 16 x 2.2 = 2475 l/h = 41.25 l/min",
                (
                    "roof tank 9 m³ (drain 50 mm, 5500 < 9000 <= 11000; overflow 50 mm for 41 "
                    "l/min <= 190), reservoir 18 m³ (drain 63 mm, 11000 < 18000 <= 19000)"
                ),
            ],
        ),
        [
            Quantity("Population", "persons", population, r["demand"]["population"], EXACT),
            Quantity("Daily demand", "l/day", daily, r["demand"]["daily"], EXACT),
            Quantity("Peak hourly demand", "l/min", peak, r["demand"]["peakHourlyLpm"], EXACT),
            Quantity("Overhead tank", "m³", daily / 2000, r["storage"]["overhead"], EXACT),
            Quantity(
                "Underground reservoir", "m³", daily / 1000, r["storage"]["underground"], EXACT
            ),
            Quantity("Overhead tank drain", "mm", 50, r["storage"]["tanks"][0]["drain"], EXACT),
            Quantity("Reservoir drain", "mm", 63, r["storage"]["tanks"][1]["drain"], EXACT),
        ],
    )


# ─────────────────────────────────── PL2: a cold riser ───────────────────────────────────


def riser_case(_: Path) -> Outcome:
    r = _riser(_results(), "R1")
    units = 5 * 2 * (2 * 5 + 2 * 1 + 2 * 4 + 1 * 2)  # two flats a floor, 5 floors
    flow = 243.5 + (units - 200) / 20 * (260.5 - 243.5)  # Table 8.5.5 flush tanks, 200-220
    q = flow / 60000
    area_75 = math.pi / 4 * 0.075**2
    area_100 = math.pi / 4 * 0.100**2
    return Outcome(
        Reference(
            "BNBC 2020 Part 8 Appendix O Table 8.O.1 (p1196), Table 8.5.4 (p1045), Table 8.5.5 "
            "(p1046), Sec 5.10.1(c)(ii) (p1044)",
            "wsfu -> Table 8.5.5 flow -> smallest size within the velocity for its diameter",
            [
                "a flat: 2 WC x 5 + 2 basins x 1 + 2 showers x 4 + 1 kitchen sink x 2 = 22",
                "R1 carries two flats on each of 5 floors: 220 wsfu",
                "Table 8.5.5 (flush tanks) 220 units: 260.5 l/min",
                (
                    f"75 mm: v = {q / area_75:.2f} > 0.75 m/s; 100 mm: v = {q / area_100:.2f} <= "
                    "0.90 m/s"
                ),
            ],
        ),
        [
            Quantity("Supply fixture units", "wsfu", units, r["units"], EXACT),
            Quantity("Probable flow", "l/min", flow, r["flow"], EXACT),
            Quantity("Riser diameter", "mm", 100, r["diameter"], EXACT),
        ],
    )


# ─────────────────────────────────── PL3: a soil stack ───────────────────────────────────


def stack_case(_: Path) -> Outcome:
    r = _riser(_results(), "S1")
    per_floor = 4 * 3  # 4 WC (half of 8, two soil stacks) x 3 (Table 8.6.12 tank operated)
    total = 5 * per_floor
    return Outcome(
        Reference(
            "BNBC 2020 Part 8 Table 8.6.12 (p1112-1113), Table 8.6.14 (p1114), Table 8.6.2 (p1087)",
            "fixture units; > 3 storeys: total for stack and at one storey; WC outlet 100 mm",
            [
                "S1: 4 WC a floor x 3 = 12 units, 5 floors = 60 units",
                "Table 8.6.14 75 mm: total 60 >= 60 and 16 >= 12 at one storey: 75 mm would do",
                "a water closet's outlet is at least 100 mm (Table 8.6.2): 100 mm",
            ],
        ),
        [
            Quantity("Stack fixture units", "units", total, r["units"], EXACT),
            Quantity("Units at one storey", "units", per_floor, r["maxStoreyUnits"], EXACT),
            Quantity("Stack diameter", "mm", 100, r["diameter"], EXACT),
        ],
    )


# ─────────────────────────────────── PL4: a leader ───────────────────────────────────


def leader_case(_: Path) -> Outcome:
    result = _results()
    drain = next(d for d in result["rainwater"]["drains"] if d["id"] == "RD1")
    area = 7.0 * 10.0  # half the 14 x 10 roof, split at x = 7 m between the drains
    allowed_50 = 202 * 25 / 88
    allowed_65 = 367 * 25 / 88
    return Outcome(
        Reference(
            "BNBC 2020 Part 8 Table 8.7.2 (p1135), Appendix R (p1213)",
            "Table area (25 mm/h) x 25 / i >= catchment",
            [
                "RD1's catchment: the roof west of x = 7 m, 7 x 10 = 70 m²",
                (
                    f"50 mm: 202 x 25 / 88 = {allowed_50:.1f} m² < 70; 65 mm: 367 x 25 / 88 = "
                    f"{allowed_65:.1f} m² >= 70"
                ),
            ],
        ),
        [
            Quantity("Catchment", "m²", area, drain["area"], EXACT),
            Quantity("Runoff", "l/min", area * 88 / 60, drain["flow"], EXACT),
            Quantity("Leader diameter", "mm", 65, drain["leader"], EXACT),
        ],
    )


# ─────────────────────────────────── PL5: a septic tank ───────────────────────────────────


def septic_case(_: Path) -> Outcome:
    s = _results()["septic"]
    v = 100 * 120 * 1 + 100 * 40 * 1
    depth = math.ceil((v / 1000 / 3) ** (1 / 3) * 1000 / 50) * 50
    width = math.ceil(math.sqrt(v / 1000 * 1e9 / (3 * depth)) / 50) * 50
    length = max(3 * width, math.ceil(v / 1000 * 1e9 / (width * depth) / 50) * 50)
    return Outcome(
        Reference(
            "BNBC 2020 Part 8 Appendix S Eq 8.S.1 (p1214), Sec 6.9.12.8-6.9.12.13 (p1106)",
            "V = P Q t + P S Y; L >= 3 B, B >= 1 m, D >= 1 m; two chambers above 3000 l",
            [
                (
                    "P = 100, Q = 120 lpcd (groups A, C, D, cities), t = 1 day, S = 40 l/capita/"
                    "year, Y = 1 year"
                ),
                "V = 100 x 120 x 1 + 100 x 40 x 1 = 16 000 l",
                f"D = (16/3)^(1/3) = 1.747 m -> {depth} mm; B = {width} mm; L = 3 B = {length} mm",
            ],
        ),
        [
            Quantity("Septic tank volume", "l", v, s["volume"], EXACT),
            Quantity("Liquid depth", "mm", depth, s["waterDepth"], EXACT),
            Quantity("Width", "mm", width, s["width"], EXACT),
            Quantity("Length", "mm", length, s["length"], EXACT),
            Quantity("Chambers", "", 2, s["compartments"], EXACT),
        ],
    )


CASES = [
    Case(
        "DB1",
        "Plumbing: daily demand and water storage",
        "design",
        "Population, daily demand, peak hourly demand, overhead tank and underground reservoir "
        "volumes and their drain pipes for a six-storey residential building.",
        "Five residential floors of four flats (180 lpcd, Table 8.5.1(a) y1); "
        "plumbing.report.plumbing_results.",
        demand_case,
    ),
    Case(
        "DB2",
        "Plumbing: a cold water riser from fixture units",
        "design",
        "Water supply fixture units of the flats a down-feed riser serves, the Hunter flow of "
        "Table 8.5.5 and the riser's diameter by the velocity of Sec 5.10.1(c)(ii).",
        "Riser R1 serving two flats on each of five floors; plumbing.supply.supply_riser.",
        riser_case,
    ),
    Case(
        "DB3",
        "Plumbing: a soil stack",
        "design",
        "Drainage fixture units of a soil stack through five storeys and its diameter from "
        "Table 8.6.14 and the water closets' outlet of Table 8.6.2.",
        "Soil stack S1 taking four water closets a floor on five floors; "
        "plumbing.drainage.soil_stack.",
        stack_case,
    ),
    Case(
        "DB4",
        "Plumbing: a roof drain leader",
        "design",
        "The roof catchment of a drain (the roof split by the nearest drain) and its vertical "
        "leader from Table 8.7.2 at 88 mm/h.",
        "Two drains on a 14 x 10 m roof; plumbing.rainwater.rainwater.",
        leader_case,
    ),
    Case(
        "DB5",
        "Plumbing: a septic tank",
        "design",
        "The volume of a septic tank by Appendix S and its proportions by Sec 6.9.12.",
        "100 residents; plumbing.septic.septic_tank.",
        septic_case,
    ),
]
