"""Soil-structure interaction benchmarks: a column on its footing's soil springs.

The building is a floor plan (one column), derived with :func:`saengine.fem.derive.derive_fem`;
:func:`saengine.fem.ssi.apply_soil_springs` puts its base on the springs of an isolated footing
(Part 9) in a synthetic uniform sand (Part 1), and OpenSees Studio's runner gives its period.

Units: the plan in mm, the analysis model in m, N, kg, s, Pa.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from saengine.fem import ssi
from saengine.library import FloorPlan, default_floor_plan
from saengine.library.bim import generate
from saengine.library.substructure import Substructure
from saengine.verification.cases.common import (
    BY_ID,
    MATERIALS,
    Case,
    Outcome,
    Quantity,
    Reference,
    derive,
    fmt,
    node_at,
    objects,
    run_model,
    settings,
)

CONCRETE = BY_ID["C24.1"]
E_C = CONCRETE.mechanical.E * 1e6  # Pa
COLUMN = {
    "id": "COL",
    "name": "Column 400x400",
    "kind": "column",
    "material": CONCRETE.id,
    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
}
MASS = 20_000.0  # kg at the top, in X
HEIGHT = 3.2  # m, the column (Base to Level 1 of the default floor plan)
ARM = 1.5  # m, from the column base down to the footing's underside
SIDE = 2.0  # m, the square footing
THICKNESS = 0.5  # m
N_SPT = 10
GAMMA = 18.0  # kN/m³
RATIO = 0.55  # G/G0 at SDS/2.5 = 0.18 g (ASCE 7-05 Table 19.2-1, between 0.15 and 0.20)
SOIL = {
    "boreholes": [
        {
            "id": "BH1",
            "x": 0,
            "y": 0,
            "depth": 30000,
            "layers": [
                {
                    "top": 0,
                    "bottom": 30000,
                    "description": "Uniform sand (synthetic)",
                    "soilType": "sand",
                    "unitWeight": GAMMA,
                }
            ],
            "spt": [{"depth": 1500 * k, "N": N_SPT} for k in range(1, 21)],
        }
    ]
}


def rocking_oscillator(folder: Path) -> Outcome:
    plan = FloorPlan.model_validate(
        {
            **default_floor_plan().model_dump(mode="json", by_alias=True),
            "columns": [
                {"id": "C1", "type": "COL", "at": {"x": "A", "y": "1"}, "base": "BASE", "top": "L1"}
            ],
        }
    )
    building = generate(plan, "verification")
    d = derive(building, objects(COLUMN), MATERIALS, settings())
    substructure = Substructure.model_validate(
        {
            "foundations": [
                {
                    "id": "F1",
                    "type": "isolated",
                    "columns": ["C1"],
                    "length": SIDE * 1e3,
                    "width": SIDE * 1e3,
                    "thickness": THICKNESS * 1e3,
                    "foundingLevel": -ARM * 1e3,
                }
            ]
        }
    )
    result = ssi.apply_soil_springs(
        d.project,
        building,
        substructure,
        json.dumps(SOIL),
        MATERIALS,
        ground_level=0.0,
        acceleration=0.18,
        options=ssi.SsiOptions(supports="soilSprings"),
    )
    project = result.project
    top = node_at(project, (0, 0, HEIGHT))
    for node in project["nodes"]:
        node["mass"] = [MASS, 0, 0, 0, 0, 0] if node["id"] == top else [0.0] * 6
    modal = next(a["id"] for a in project["analyses"] if a["type"] == "Modal")
    _, _, results = run_model(project, folder, [modal])
    period = max(float(p) for p in results[modal].periods)

    # The reference, by hand from the soil up.
    vs = 97.0 * N_SPT**0.314
    g0 = GAMMA * 1e3 / 9.80665 * vs**2
    g = RATIO * g0
    nu = 0.3
    kx_sur = g * SIDE / (2 - nu) * (3.4 + 1.2)
    kyy_sur = g * SIDE**3 / (1 - nu) * (0.47 + 0.034)
    depth, contact = ARM, THICKNESS
    h = depth - contact / 2
    beta_x = (1 + 0.21 * math.sqrt(depth / SIDE)) * (
        1 + 1.6 * (h * contact * 2 * SIDE / SIDE**3) ** 0.4
    )
    beta_yy = 1 + 1.4 * (contact / SIDE) ** 0.6 * (
        1.5 + 3.7 * (contact / SIDE) ** 1.9 * (contact / depth) ** -0.6
    )
    kx, kyy = kx_sur * beta_x, kyy_sur * beta_yy
    ei = E_C * 0.4**4 / 12
    flex_column = HEIGHT**3 / (3 * ei)
    flexibility = flex_column + 1 / kx + (HEIGHT + ARM) ** 2 / kyy
    ref = 2 * math.pi * math.sqrt(MASS * flexibility)
    fixed = 2 * math.pi * math.sqrt(MASS * flex_column)
    reference = Reference(
        source="A one-mass oscillator, T = 2π √(m/k), its column's flexure in series with the "
        "horizontal and rocking springs of its footing (statics of the cantilever on its rigid "
        "footing); the springs of ASCE 41-06 Sec 4.4.2.1.2 (after Gazetas 1991, as tabulated in "
        "WSDOT BDM M 23-50 Tables 7.2.7-1/2) with Vs from SPT N by Imai & Tonouchi (1982)",
        formula="T = 2π √(m (h³/3EI + 1/Kx + (h + a)²/Kyy))",
        steps=[
            (
                f"Vs = 97.0 × {N_SPT}^0.314 = {fmt(vs)} m/s; ρ = {GAMMA:g}/9.80665 t/m³; "
                f"G0 = ρ Vs² = {fmt(g0 / 1e6)} MPa; G = {RATIO:g} G0 = {fmt(g / 1e6)} MPa, ν = 0.3"
            ),
            (
                f"Kx,sur = G B/(2-ν) (3.4 + 1.2) = {fmt(kx_sur / 1e3)} kN/m; "
                f"Kyy,sur = G B³/(1-ν) (0.47 + 0.034) = {fmt(kyy_sur / 1e3)} kN·m/rad (B = L = 2 m)"
            ),
            (
                f"D = {ARM:g} m, d = {THICKNESS:g} m, h = {h:g} m: βx = {fmt(beta_x)}, "
                f"βyy = {fmt(beta_yy)}; Kx = {fmt(kx / 1e3)} kN/m, Kyy = {fmt(kyy / 1e3)} kN·m/rad"
            ),
            (
                f"h = {HEIGHT:g} m, a = {ARM:g} m (column base to the footing's underside), "
                f"EI = {fmt(ei)} N·m², m = {MASS:g} kg"
            ),
            (
                f"h³/3EI = {fmt(flex_column)} m/N, 1/Kx = {fmt(1 / kx)} m/N, "
                f"(h + a)²/Kyy = {fmt((HEIGHT + ARM) ** 2 / kyy)} m/N"
            ),
            f"T = 2π √({MASS:g} × {fmt(flexibility)}) = {fmt(ref)} s (fixed base: {fmt(fixed)} s)",
        ],
    )
    spring = result.foundations[0].k
    return Outcome(
        reference,
        [
            Quantity("Horizontal spring Kx", "kN/m", kx / 1e3, spring[0] / 1e3, 0.005),
            Quantity("Rocking spring Kyy", "kN·m/rad", kyy / 1e3, spring[4] / 1e3, 0.005),
            Quantity("Period on the soil springs", "s", ref, period, 0.01),
        ],
        notes=[
            (
                "The derived masses are replaced by the one mass at the top in X,"
                " the footing's own mass is not modelled."
            ),
            "The SPT tests averaged under the footing all have N = 10: the hand G is exact.",
        ],
    )


CASES = [
    Case(
        "AS1",
        "Soil-structure interaction: oscillator on a rocking footing",
        "analysis",
        "Period of a one-mass column on the horizontal and rocking springs of its footing "
        "(Project Settings → Analysis: soil springs), against the column's flexure in series "
        "with the springs.",
        "Column 400 × 400 mm of C24.1, 3.2 m, on an isolated footing 2 × 2 × 0.5 m founded "
        "1.5 m below its base and the ground, in uniform sand (γ = 18 kN/m³, SPT N = 10 "
        "throughout), G/G0 = 0.55 (0.18 g); one mass of 20 t at the top in X.",
        rocking_oscillator,
    ),
]
