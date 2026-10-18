"""Water-supply benchmarks (Part 7, plumbing): the hydraulics of :mod:`saengine.plumbing.hydraulics`
(WNTR running EPANET 2.2) against hand calculations.

DW1 is a down-feed riser from a roof tank to one floor: the residual head at the take-off and
the fixture by Hazen-Williams with the fittings of BNBC 2020 Part 8 Tables 8.O.2 as equivalent
lengths. DW2 is the transfer pump from the underground reservoir to the roof tank (BNBC Sec
5.10.5). DW3 is a 20-storey tower whose lower floors see more than the 35 m of Sec 5.10.4.2:
the static heads, and the second zone's proposed intermediate tank built into the model and
analysed again (Sec 5.11.1).

Synthetic data. Hand Hazen-Williams in SI: hf = 10.67 L Q^1.852 / (C^1.852 D^4.87) (EPANET
uses 10.667 and 4.871: within 0.5 %). Units: mm in the plumbing data, m, L/s and kW here.
"""

from __future__ import annotations

import math
from pathlib import Path

from saengine.plumbing.hydraulics import KPA_PER_M, water_hydraulics
from saengine.verification.cases.common import Case, G, Outcome, Quantity, Reference, fmt

#: Hazen-Williams by hand against EPANET's constants; the EPANET binary results are single
#: precision.
HYDRAULIC = 0.005
EXACT = 0.001


def _hw(q: float, d: float, length: float, c: float) -> float:
    return 10.67 * length * q**1.852 / (c**1.852 * d**4.87)


def _stories(n: int, h: float) -> dict:
    return {
        "stories": [{"id": f"L{i}", "name": f"Level {i}", "elevation": i * h} for i in range(n + 1)]
    }


# ─────────────────────────────── DW1: a down-feed riser ───────────────────────────────


def riser_case(_: Path) -> Outcome:
    plumbing = {
        "stories": [{"story": "L0", "occupancy": "residentialFlat", "fixtures": {"wc": 4}}],
        "risers": [
            {
                "id": "R1",
                "system": "coldWater",
                "x": 0,
                "y": 0,
                "fromStory": "L0",
                "toStory": "L1",
                "diameter": 25,
                "material": "uPVC",
            }
        ],
        "tanks": [
            {
                "id": "T",
                "kind": "overhead",
                "story": "L1",
                "x": 0,
                "y": 0,
                "length": 2000,
                "width": 2000,
                "waterDepth": 1000,
                "base": 200,
            }
        ],
    }
    floor = water_hydraulics(building=_stories(1, 10000), mep={"plumbing": plumbing})["floors"][0]
    q = 56.6 / 60000
    c = 150.0
    level = 10.0 + 0.2 + 0.05
    header = 0.1 + 2 * 0.79 + 0.31
    riser = 10.2 + 0.52
    branch = 10 + 1.0 + 3.05 + 0.70 + 4 * 1.53
    h_riser = _hw(q, 0.025, header + riser, c)
    h_branch = _hw(q, 0.050, branch, c)
    takeoff = level - h_riser
    fixture = level - h_riser - h_branch - 1.0
    return Outcome(
        Reference(
            source="BNBC 2020 Part 8 Tables 8.5.5, 8.O.2(a)-(c), Secs 5.9.2.2, 5.10.1(c), 5.10.3",
            formula="h = z_tank,min - z - Σ 10.67 L Q^1.852 / (C^1.852 D^4.87)",
            steps=[
                (
                    "Roof tank on L1 (10 m), base 200, its outlet 50 mm above the bottom (Sec "
                    f"5.9.2.2): minimum level {fmt(level)} m"
                ),
                (
                    "L0: 4 water closets × 5 units (Table 8.O.1) = 20 units: 56.6 L/min (Table "
                    f"8.5.5) = {fmt(q * 1000)} L/s"
                ),
                (
                    f"Header 0.1 m + 2 elbows 0.79 + gate 0.31 (Ø25) = {fmt(header)} m; riser 10.2 m "
                    f"+ run tee 0.52 = {fmt(riser)} m; uPVC C = 150: hf = {fmt(h_riser)} m"
                ),
                f"Take-off head {fmt(level)} - {fmt(h_riser)} = {fmt(takeoff)} m",
                (
                    "Branch sized for 0.6 m/s: Ø50; 10 m + 1 m rise + branch tee 3.05 + gate 0.70 + "
                    f"4 elbows 1.53 = {fmt(branch)} m: hf = {fmt(h_branch)} m"
                ),
                f"Fixture 1 m above L0: {fmt(takeoff)} - {fmt(h_branch)} - 1.0 = {fmt(fixture)} m",
            ],
        ),
        [
            Quantity("Flow in the riser", "L/s", q * 1000, floor["riserFlow"], EXACT),
            Quantity(
                "Residual head at the take-off", "m", takeoff, floor["takeoffHead"], HYDRAULIC
            ),
            Quantity("Residual head at the fixture", "m", fixture, floor["head"], HYDRAULIC),
            Quantity(
                "Velocity in the riser",
                "m/s",
                q / (math.pi * 0.025**2 / 4),
                floor["velocity"],
                EXACT,
            ),
        ],
    )


# ─────────────────────────────── DW2: the transfer pump ───────────────────────────────


def pump_case(_: Path) -> Outcome:
    plumbing = {
        "supply": {"source": "deepTubewell"},
        "stories": [{"story": "L0", "occupancy": "residentialFlat", "population": 100}],
        "risers": [
            {
                "id": "PM",
                "system": "pumpMain",
                "x": 0,
                "y": 5000,
                "fromStory": "L0",
                "toStory": "L5",
                "diameter": 50,
                "material": "GI",
            }
        ],
        "tanks": [
            {
                "id": "OHT",
                "kind": "overhead",
                "story": "L5",
                "x": 10000,
                "y": 5000,
                "length": 4000,
                "width": 3000,
                "waterDepth": 1500,
                "freeboard": 300,
                "base": 200,
            },
            {
                "id": "UGR",
                "kind": "underground",
                "x": 0,
                "y": 0,
                "waterDepth": 2000,
                "freeboard": 300,
                "roof": 150,
                "topLevel": 0,
            },
        ],
    }
    pump = water_hydraulics(building=_stories(5, 3000), mep={"plumbing": plumbing})["pump"]
    daily = 100 * 180  # L/day: Table 8.5.1(a) row y1, 180 lpcd (full facility)
    q = daily / 16 * 2.2 / 3600 / 1000  # Eq 8.5.1: 16 h of consumption, peak factor 2.2
    static = 17.0 + 2.45
    length = 15 + static + 6.10 + 2 * 0.70 + 4 * 1.53
    hf = _hw(q, 0.050, length, 120.0)
    v = q / (math.pi * 0.05**2 / 4)
    hv = v**2 / (2 * G)
    tdh = static + hf + hv + 1.0
    power = 1000 * G * q * tdh / 0.6 / 1000
    return Outcome(
        Reference(
            source=(
                "BNBC 2020 Part 8 Table 8.5.1(a), Eq 8.5.1, Secs 5.9.1.2(c)(ii), 5.10.5 (eq. "
                "8.5.2, 8.5.3), Tables 8.O.2"
            ),
            formula="H = hs + hd + hf + hv + h_inlet; P = ρ g Q H / η",
            steps=[
                (
                    "Delivery pump = peak hourly demand (Sec 5.9.1.2(c)(ii)): 100 persons × 180 "
                    "lpcd (Table 8.5.1(a), y1) = 18 m³/day; / 16 h × 2.2 (Eq 8.5.1) = "
                    f"{fmt(q * 1000)} L/s"
                ),
                (
                    "Reservoir bottom 0 - 0.15 - 0.3 - 2.0 = -2.45 m; roof tank inlet 15 + 0.2 + 1.5 "
                    f"+ 0.3 = 17.0 m: hs + hd = {fmt(static)} m"
                ),
                (
                    f"Pump main 15 m horizontal + {fmt(static)} m + check 6.10 + 2 gates 0.70 + 4 "
                    f"elbows 1.53 (Ø50) = {fmt(length)} m; GI C = 120: hf = {fmt(hf)} m"
                ),
                f"v = {fmt(v)} m/s: hv = {fmt(hv)} m; inlet residual 1.0 m",
                f"H = {fmt(tdh)} m; P = 9.807 × {fmt(q)} × {fmt(tdh)} / 0.6 = {fmt(power)} kW",
            ],
        ),
        [
            Quantity("Pump flow", "L/s", q * 1000, pump["flow"], EXACT),
            Quantity("Friction in the pump main", "m", hf, pump["friction"], 0.01),
            Quantity("Total dynamic head", "m", tdh, pump["tdh"], HYDRAULIC),
            Quantity("Shaft power", "kW", power, pump["shaftPower"], HYDRAULIC),
        ],
    )


# ─────────────────────────────── DW3: pressure zones ───────────────────────────────


def zones_case(_: Path) -> Outcome:
    flat = {"wc": 4, "basin": 4, "shower": 3, "kitchenSink": 2, "washingMachine": 1}
    plumbing = {
        "stories": [
            {"story": f"L{i}", "occupancy": "residentialFlat", "fixtures": flat} for i in range(20)
        ],
        "risers": [
            {
                "id": "R1",
                "system": "coldWater",
                "x": 5000,
                "y": 5000,
                "fromStory": "L0",
                "toStory": "L19",
            }
        ],
        "tanks": [
            {
                "id": "OHT",
                "kind": "overhead",
                "story": "L20",
                "x": 6000,
                "y": 5000,
                "length": 4000,
                "width": 3000,
                "waterDepth": 1500,
                "base": 200,
            }
        ],
    }
    r = water_hydraulics(building=_stories(20, 3000), mep={"plumbing": plumbing})
    floors = {f["story"]: f for f in r["floors"]}
    full = 60 + 0.2 + 1.5
    required = 55 / KPA_PER_M
    over = sum(1 for f in r["floors"] if not f["staticOk"])
    second = r["zones"][1]
    # build the proposed intermediate tank, split the riser and analyse again
    plumbing["risers"][0]["fromStory"] = "L9"
    plumbing["risers"].append(
        dict(plumbing["risers"][0], id="R2", fromStory="L0", toStory=second["stories"][0])
    )
    plumbing["tanks"].append(
        {
            "id": "IT",
            "kind": "overhead",
            "story": second["standsOn"],
            "x": 5000,
            "y": 5000,
            "length": 3000,
            "width": 3000,
            "waterDepth": 1500,
            "base": second["base"],
        }
    )
    again = water_hydraulics(building=_stories(20, 3000), mep={"plumbing": plumbing})
    lower = [f for f in again["floors"] if f["riser"] == "R2"]
    top = lower[0]
    failing = sum(1 for f in lower if not f["ok"])
    return Outcome(
        Reference(
            source="BNBC 2020 Part 8 Secs 5.9.2.2, 5.10.4.2, 5.11.1, Table 8.5.6",
            formula="static head = z_tank,full - z ≤ 35 m; residual head at each fixture ≥ 55 kPa",
            steps=[
                f"Roof tank on L20 (60 m) full at 60 + 0.2 + 1.5 = {fmt(full)} m",
                (
                    f"L9 at 27 m: {fmt(full - 27)} m ≤ 35; L8 at 24 m: {fmt(full - 24)} m > 35: L0-L8 "
                    "(9 floors) need a second zone"
                ),
                (
                    "The second zone's intermediate tank: its outlet at "
                    f"{fmt(second['sourceLevel'])} m (solved with the zone's friction, rounded up "
                    f"to 10 mm), top water level {fmt(second['fullLevel'])} m, on "
                    f"{second['standsOn']} with a {fmt(second['base'])} mm stand"
                ),
                (
                    "Built into the model (riser R2 from it to L0-L8): the shower 2 m above L8 "
                    f"needs 55 kPa = {fmt(required)} m and gets {fmt(top['head'])} m"
                ),
            ],
        ),
        [
            Quantity("Static head at L0", "m", full, floors["L0"]["staticHead"], EXACT),
            Quantity("Static head at L9", "m", full - 27, floors["L9"]["staticHead"], EXACT),
            Quantity("Floors over 35 m", "-", 9, over, EXACT),
            Quantity(
                "Residual head at L8 from the proposed tank", "m", required, top["head"], HYDRAULIC
            ),
            Quantity("Floors of the second zone failing", "-", 0, failing, EXACT),
        ],
    )


CASES = [
    Case(
        "DW1",
        "Down-feed riser: residual heads at a floor",
        "design",
        "The residual head at the take-off and at the fixture of a floor fed from a roof tank "
        "through a riser, by Hazen-Williams with the fittings as equivalent lengths.",
        "Roof tank on L1 (10 m), Ø25 uPVC riser from L1 to L0 (4 water closets, 20 units, 56.6 L/min), "
        "a 10 m floor branch; plumbing.hydraulics.water_hydraulics (WNTR, EPANET 2.2).",
        riser_case,
    ),
    Case(
        "DW2",
        "Transfer pump: total dynamic head and power",
        "design",
        "The pump from the underground reservoir to the roof tank: flow, friction in the pump "
        "main, total dynamic head and shaft power.",
        "A pump delivering the peak hourly demand of 100 persons of flats to a roof tank on L5 "
        "(15 m) from a reservoir 2.45 m below ground through a Ø50 GI main 15 m long in plan; "
        "plumbing.hydraulics.water_hydraulics.",
        pump_case,
    ),
    Case(
        "DW3",
        "Tall building: static heads and the zone break",
        "design",
        "The static heads with the roof tank full against the 35 m of BNBC Sec 5.10.4.2, and "
        "the proposed source of the second pressure zone checked by building it into the model.",
        "20 storeys of flats at 3 m under a roof tank on L20, one riser; "
        "plumbing.hydraulics.water_hydraulics.",
        zones_case,
    ),
]
