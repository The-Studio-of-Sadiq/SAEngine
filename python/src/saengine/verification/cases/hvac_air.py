"""HVAC air side and plant benchmarks (stream H2): a zone's supply air and its main duct by
equal friction, a cooling tower's heat rejection, and the web opening a duct needs through a
beam, worked out by hand.

The building (:func:`_project`): a ground floor GF and L1 at 3.8 m, a roof L2 at 7.6 m; a 400 x
900 mm beam B1 under L1 along y = 5 m from x = 0 to 8 m; 150 mm slabs on L1 and L2 over 8 x
10 m. All synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path

from saengine.hvac import air, plant
from saengine.hvac.openings import hvac_duct_openings
from saengine.library import ObjectLibrary
from saengine.verification.cases.common import MATERIALS, Case, Outcome, Quantity, Reference

EXACT = 0.005


def _project(root: Path, hvac: dict) -> Path:
    bars = {
        "material": "B420DWR", "cover": 40,
        "longitudinal": [{"position": "top", "count": 3, "dia": 20},
                         {"position": "bottom", "count": 4, "dia": 20}],
        "transverse": {"type": "tie", "dia": 10, "spacing": 150, "legs": 2},
    }  # fmt: skip
    objects = ObjectLibrary.model_validate({"objects": [
        {"id": "B400x900", "name": "Beam 400x900", "kind": "beam", "material": "C20.7",
         "profile": {"shape": "rectangle", "xDim": 400, "yDim": 900}, "reinforcement": bars},
        {"id": "S150", "name": "Slab 150", "kind": "slab", "material": "C20.7", "thickness": 150},
    ]})  # fmt: skip
    outline = [[0, 0], [8000, 0], [8000, 10000], [0, 10000]]
    bim = {
        "stories": [{"id": s, "name": s, "elevation": z}
                    for s, z in (("GF", 0), ("L1", 3800), ("L2", 7600))],
        "elements": [
            {"id": "B1", "type": "B400x900", "kind": "beam", "start": [0, 5000],
             "end": [8000, 5000], "elevation": 3800},
            {"id": "S1", "type": "S150", "kind": "slab", "boundary": outline, "elevation": 3800},
            {"id": "S2", "type": "S150", "kind": "slab", "boundary": outline, "elevation": 7600},
        ],
    }  # fmt: skip
    files = {
        "03 Materials/materials.json": MATERIALS.model_dump_json(by_alias=True),
        "04 Objects/objects.json": objects.model_dump_json(by_alias=True),
        "06 BIM/bim.json": json.dumps(bim),
        "07 MEP/mep.json": json.dumps({"schema": "saengine.mep/1", "hvac": hvac}),
    }
    for relative, text in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text, "utf-8")
    return root


# ─────────────────────────── DA1: supply air and the main duct ───────────────────────────


def supply_case(work: Path) -> Outcome:
    root = _project(work / "da1", {"stories": [{"story": "GF", "use": "officeSpace"}]})
    loads = {"zones": [{"story": "GF", "sensible": 12.06, "total": 15.0, "area": 100.0}]}
    result = air.hvac_air(root, loads, with_plant=False, with_openings=False)
    zone = result["zones"][0]
    duct = zone["ductMain"]
    q = 12.06 / (1.2 * 1.005 * 10)
    de = 1.30 * (700 * 250) ** 0.625 / (700 + 250) ** 0.25
    return Outcome(
        Reference(
            "Q = qs / (rho cp dT) (standard air, SAEngine dT 10 K); BNBC 2020 Part 8 Table "
            "8.2.3 office spaces (p. 866); equal friction 1 Pa/m, Darcy-Weisbach and Colebrook "
            "(ASHRAE Handbook Fundamentals Ch 21), Huebscher's equivalent diameter",
            "Q = 12.06 / (1.2 x 1.005 x 10); Vbz = Rp Pz + Ra Az; De = 1.30 (ab)^0.625/(a+b)^0.25",
            [
                f"Q = 12.06 / 12.06 = {q:.3f} m³/s",
                "100 m² at 5 per 100 m²: 5 persons; Vbz = 2.5 x 5 + 0.3 x 100 = 42.5 l/s",
                "1 m³/s at 1 Pa/m: a 441 mm round duct (about 440 mm on the ASHRAE chart)",
                (
                    "shallowest rectangle with aspect <= 4: 200 deep tops at 800 x 200, De "
                    f"413.6 mm < 441; 700 x 250 gives De = {de:.1f} mm, v = 1 / 0.175 = 5.71 m/s"
                ),
            ],
        ),
        [
            Quantity("Supply airflow", "m³/s", q, zone["airflow"], EXACT),
            Quantity("Outdoor air", "m³/s", 0.0425, zone["outdoorAir"], EXACT),
            Quantity("Main duct width", "mm", 700, duct["width"], EXACT),
            Quantity("Main duct height", "mm", 250, duct["height"], EXACT),
            Quantity("Main duct velocity", "m/s", 1 / 0.175, duct["velocity"], EXACT),
        ],
    )


# ─────────────────────────── DA2: cooling tower heat rejection ───────────────────────────


def tower_case(_: Path) -> Outcome:
    plan = plant.chiller_plan(2000.0)
    rejected = plant.heat_rejection(plan["unit"], plan["cop"])
    return Outcome(
        Reference(
            "BNBC 2020 Part 8 Table 8.2.11 (p. 919): water-cooled screw chillers of 530 to "
            "1050 kW, minimum COP 5.40; heat rejected = cooling + compressor work",
            "Qrej = Q (1 + 1/COP)",
            [
                "2000 kW: two duty screw chillers of 1000 kW (one more on standby)",
                f"Qrej = 1000 x (1 + 1/5.40) = {1000 * (1 + 1 / 5.4):.2f} kW",
                f"condenser water at 5.6 K: {1000 * (1 + 1 / 5.4) / (4.186 * 5.6):.2f} l/s",
            ],
        ),
        [
            Quantity("Chillers on duty", "-", 2, plan["duty"], EXACT),
            Quantity("Chiller capacity", "kW", 1000, plan["unit"], EXACT),
            Quantity("Chiller COP", "-", 5.40, plan["cop"], EXACT),
            Quantity("Tower heat rejection", "kW", 1000 * (1 + 1 / 5.4), rejected, EXACT),
            Quantity(
                "Condenser water",
                "l/s",
                1000 * (1 + 1 / 5.4) / (4.186 * 5.6),
                plant.water_flow(rejected),
                EXACT,
            ),
        ],
    )


# ─────────────────────────── DA3: a duct through a beam web ───────────────────────────


def opening_case(work: Path) -> Outcome:
    ducts = [
        {"id": "D1", "system": "exhaust", "width": 300, "height": 150, "story": "GF",
         "bottom": 3275, "path": [[4000, 1000], [4000, 9000]]},
        {"id": "D2", "system": "supply", "width": 1200, "height": 500, "story": "GF",
         "flow": 1.0, "path": [[6000, 1000], [6000, 9000]]},
    ]  # fmt: skip
    root = _project(work / "da3", {"stories": [{"story": "GF", "use": "officeSpace"}],
                                   "ducts": ducts})  # fmt: skip
    result = hvac_duct_openings(root)
    (opening,) = result["openings"]
    (conflict,) = result["conflicts"]
    below = next(o for o in conflict["options"] if o["kind"] == "routeBelow")
    raise_ = next(o for o in conflict["options"] if o["kind"] == "increaseFloorHeight")
    return Outcome(
        Reference(
            "Opening = duct outside + 50 mm each side (SAEngine practice); h/3 of BNBC 2020 "
            "Part 6 Sec 5.16.3.5(a) as SAEngine's limit (saengine.mep.openings); 2.44 m clear "
            "under a duct, BNBC 2020 Part 3 Sec 1.14.2.1(b) (Part 1 volume p. 66)",
            "w = b + 100, h = d + 100; elevation = duct centre - beam bottom; clear = beam "
            "bottom - 50 - duct - floor finish 50",
            [
                "B1: top 3800, h = 900, bottom 2900, h/3 = 300",
                (
                    "D1 300 x 150 (no insulation), underside 3275: centre 3350, 450 above the "
                    "beam's bottom, 4000 from its start; opening 400 x 250 <= 300: passes"
                ),
                (
                    "D2 1200 x 500 + 2 x 25 insulation = 1250 x 550 below the soffit 3650: an "
                    "opening 650 > 300 deep: no web opening"
                ),
                (
                    "route below: 2900 - 50 - 550 - 50 = 2250 mm clear < 2440: raise the floor "
                    "190 mm, 3800 to 3990"
                ),
            ],
        ),
        [
            Quantity("Opening width", "mm", 400, opening["width"], EXACT),
            Quantity("Opening height", "mm", 250, opening["height"], EXACT),
            Quantity("Opening distance", "mm", 4000, opening["position"]["distance"], EXACT),
            Quantity("Opening elevation", "mm", 450, opening["position"]["elevation"], EXACT),
            Quantity("Deep duct opening height", "mm", 650, conflict["opening"]["height"], EXACT),
            Quantity("Clear height under the routed duct", "mm", 2250, below["clearHeight"], EXACT),
            Quantity("Floor raise needed", "mm", 190, raise_["by"], EXACT),
        ],
        notes=["the opening checks are saengine.mep.openings' (geometry only, no forces)"],
    )


CASES = [
    Case(
        "DA1",
        "HVAC: supply air and the main duct",
        "design",
        "Supply airflow of a zone from its sensible load, its outdoor air by BNBC Table 8.2.3 "
        "and the main supply duct by equal friction as the shallowest rectangle of aspect 4.",
        "A 100 m² office zone of 12.06 kW sensible; hvac.air.hvac_air.",
        supply_case,
    ),
    Case(
        "DA2",
        "HVAC: chillers and cooling tower heat rejection",
        "design",
        "Chillers for a 2000 kW plant and the heat their cooling towers reject with the minimum "
        "COP of BNBC Table 8.2.11.",
        "2000 kW chilled water plant; hvac.plant.chiller_plan and heat_rejection.",
        tower_case,
    ),
    Case(
        "DA3",
        "HVAC: a duct through a beam web, and one routed below",
        "design",
        "The web opening a duct crossing a beam needs (position and size), and the clear "
        "height and floor raise when a deeper duct has to pass below the beam.",
        "Two ducts crossing a 400 x 900 beam; hvac.openings.hvac_duct_openings.",
        opening_case,
    ),
]
