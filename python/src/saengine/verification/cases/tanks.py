"""Water-retaining tank benchmarks (Part 7, plumbing): the shell model of a tank wall, the
flotation of an underground tank, a crack width and an overhead tank's weight on the roof.

The cases run SAEngine's own functions (:mod:`saengine.plumbing.tanks_model`,
:mod:`saengine.plumbing.tanks`) on synthetic tanks and work the same quantities out by hand:
the statics of a cantilever under a triangular load, buoyancy, EN 1992-1-1 7.3.4 and the
weights of the concrete and the water.

Units: m, N inside the shell model; mm, MPa inside the section design; reported in kN, kN·m,
kPa and mm.
"""

from __future__ import annotations

import math
from pathlib import Path

from saengine.plumbing.tanks import (
    GAMMA_W,
    Soil,
    TankContext,
    crack_width,
    cracked_section,
    flotation,
    support_loads,
    tank_spec,
)
from saengine.plumbing.tanks_model import M22, Q23, wall_panel
from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

#: Tolerance of a hand calculation the code reproduces in closed form.
EXACT = 0.005
#: A shell mesh of 8 elements over the height against beam theory.
SHELL = 0.02


def wall_case(folder: Path) -> Outcome:
    gamma = GAMMA_W * 1e3
    h = 3.0
    found = wall_panel(12.0, h, 0.25, {"bottom": "fixed"}, gamma, folder / "wall")
    base = [(abs(x - 6.0), found.forces[n]) for n, (x, z) in found.coords.items() if z == 0]
    middle = min(base, key=lambda r: r[0])[1]
    m0 = gamma * h**3 / 6
    v0 = gamma * h**2 / 2
    return Outcome(
        Reference(
            source="Statics of a cantilever strip (cylindrical bending of a long wall)",
            formula="M = γ h³ / 6, V = γ h² / 2 at the base of a wall fixed at its base, free "
            "at its top, full to the top",
            steps=[
                "Wall 12 m long, 3 m high, 250 mm thick, fixed along its base; water to its top",
                f"M = 9.81 × 3³ / 6 = {fmt(m0 / 1e3)} kN·m/m",
                f"V = 9.81 × 3² / 2 = {fmt(v0 / 1e3)} kN/m",
                (
                    "SAEngine: the shell moment and shear at the middle of the base (8 ASDShellQ4 "
                    "over the height, the edge value from the parabola through the next node lines)"
                ),
            ],
        ),
        [
            Quantity("Base moment M", "kN·m/m", m0 / 1e3, middle[M22] / 1e3, SHELL),
            Quantity("Base shear V", "kN/m", v0 / 1e3, -middle[Q23] / 1e3, SHELL),
        ],
    )


TANK = {
    "id": "UGT",
    "kind": "underground",
    "length": 4000,
    "width": 3000,
    "waterDepth": 2500,
    "freeboard": 300,
    "compartments": 1,  # one: the hand calculation has no partition
    "walls": 200,
    "base": 250,
    "roof": 150,
    "toe": 500,
    "topLevel": 300,
}


def flotation_case(_: Path) -> Outcome:
    context = TankContext.build()
    spec = tank_spec(TANK, context)
    soil = Soil([(0.0, 100.0, 18.0, 20.0, 30.0)], 0.0, 10.0, 0.6, "synthetic")
    found = flotation(spec, soil, context.options)
    depth = 2.8 + 0.25 + 0.15 - 0.3
    lb, bo = 4.4 + 1.0, 3.4 + 1.0
    uplift = 9.81 * depth * lb * bo
    walls = (2 * 4.2 + 2 * 3.2) * 0.2 * 2.8
    base = lb * bo * 0.25
    roof = 4.4 * 3.4 * 0.15
    concrete = (walls + base + roof) * 24
    toe = (lb * bo - 4.4 * 3.4) * 20 * (depth - 0.25)
    fs = (concrete + toe) / uplift
    return Outcome(
        Reference(
            source="Buoyancy (BNBC 2020 Part 6 Sec 2.6.5.2: the full hydrostatic pressure on "
            "the underside), the tank empty under the water table at the ground",
            formula="FS = (W concrete + W soil on the toe) / (γw hw A base)",
            steps=[
                (
                    "Inside 4 × 3 × 2.8 m, walls 200, base 250 with a 500 mm toe, roof 150, top "
                    "300 mm above the ground; saturated soil 20 kN/m³"
                ),
                (
                    f"Base underside {fmt(depth)} m deep; U = 9.81 × {fmt(depth)} × {fmt(lb)} × "
                    f"{fmt(bo)} = {fmt(uplift)} kN"
                ),
                f"Concrete ({fmt(walls)} + {fmt(base)} + {fmt(roof)}) m³ × 24 = {fmt(concrete)} kN",
                (
                    f"Soil on the toe {fmt(lb * bo - 4.4 * 3.4)} m² × 20 × {fmt(depth - 0.25)} m = "
                    f"{fmt(toe)} kN"
                ),
                f"FS = {fmt(concrete + toe)} / {fmt(uplift)} = {fmt(fs)}",
            ],
        ),
        [
            Quantity("Uplift U", "kN", uplift, found["uplift"], EXACT),
            Quantity("Resisting weight W", "kN", concrete + toe, found["resisting"], EXACT),
            Quantity("Factor of safety", "-", fs, found["FS"], EXACT),
        ],
    )


def crack_case(_: Path) -> Outcome:
    es, ec, fc = 200_000.0, 4700 * math.sqrt(27.6), 27.6
    area = math.pi * 6**2 * 1000 / 150  # Ø12 @ 150
    h, d, c = 200.0, 150.0, 44.0
    m = 12e6  # N·mm/m
    n = es / ec
    x = (-n * area + math.sqrt((n * area) ** 2 + 2 * 1000 * n * area * d)) / 1000
    sigma = m / (area * (d - x / 3))
    fct = 0.30 * fc ** (2 / 3)
    hc = min(2.5 * (h - d), (h - x) / 3, h / 2)
    rho = area / (1000 * hc)
    strain = max((sigma - 0.4 * fct / rho * (1 + n * rho)) / es, 0.6 * sigma / es)
    sr = 3.4 * c + 0.8 * 0.5 * 0.425 * 12 / rho
    wk = sr * strain
    cracked = cracked_section(m, 0.0, h, d, area, 50.0, 0.0, es, ec)
    assert cracked is not None
    found = crack_width(cracked, h, d, c, 12, 150, area, fct, es, ec)
    return Outcome(
        Reference(
            source="EN 1992-1-1:2004 7.3.4 (7.8), (7.9), (7.11); the elastic cracked section",
            formula="wk = sr,max (εsm - εcm); sr,max = k3 c + k1 k2 k4 φ / ρp,eff",
            steps=[
                (
                    "Wall 200 mm, Ø12 @ 150 at d = 150 (c = 44), f'c 27.6, Ec = 4700 √f'c, "
                    "service M = 12 kN·m/m, kt = 0.4"
                ),
                f"x = {fmt(x)} mm, σs = M / (As (d - x/3)) = {fmt(sigma)} MPa",
                f"hc,ef = min(2.5 × 50, (200 - x)/3, 100) = {fmt(hc)} mm, ρp,eff = {fmt(rho)}",
                (
                    f"εsm - εcm = {fmt(strain)}, sr,max = 3.4 × 44 + 0.8 × 0.5 × 0.425 × 12 / ρ "
                    f"= {fmt(sr)} mm"
                ),
                f"wk = {fmt(wk)} mm",
            ],
        ),
        [
            Quantity("Steel stress σs", "MPa", sigma, found["sigma_s"], EXACT),
            Quantity("Crack spacing sr,max", "mm", sr, found["sr_max"], EXACT),
            Quantity("Crack width wk", "mm", wk, found["wk"], EXACT),
        ],
    )


OVERHEAD = {
    "id": "OHT",
    "kind": "overhead",
    "story": "Roof",
    "length": 3000,
    "width": 2500,
    "waterDepth": 1500,
    "freeboard": 300,
    "compartments": 1,  # one: the hand calculation has no partition
    "walls": 150,
    "base": 175,
    "roof": 125,
}


def overhead_case(_: Path) -> Outcome:
    context = TankContext.build()
    spec = tank_spec(OVERHEAD, context)
    found = support_loads(spec, context.options)
    walls = (2 * 3.15 + 2 * 2.65) * 0.15 * 1.8
    base = 3.3 * 2.8 * 0.175
    roof = 3.3 * 2.8 * 0.125
    empty = (walls + base + roof) * 24 + 3.3 * 2.8 * 1.0
    water = 3 * 2.5 * 1.5 * 9.81
    return Outcome(
        Reference(
            source="Weights of the concrete (24 kN/m³), the roof finish (1 kPa) and the water "
            "to the overflow (9.81 kN/m³)",
            formula="W empty = Σ V γc + finish × roof area; W full = W empty + γw L W hw",
            steps=[
                "Inside 3 × 2.5 m, water 1.5 m, freeboard 300, walls 150, base 175, roof 125",
                (
                    f"Walls (2 × 3.15 + 2 × 2.65) × 0.15 × 1.8 = {fmt(walls)} m³, base {fmt(base)}, "
                    f"roof {fmt(roof)} m³"
                ),
                f"Empty = {fmt(walls + base + roof)} × 24 + 9.24 × 1 = {fmt(empty)} kN",
                f"Water = 3 × 2.5 × 1.5 × 9.81 = {fmt(water)} kN; full {fmt(empty + water)} kN",
            ],
        ),
        [
            Quantity("Empty weight", "kN", empty, found["empty"], EXACT),
            Quantity("Water", "kN", water, found["water"], EXACT),
            Quantity("Full weight", "kN", empty + water, found["full"], EXACT),
        ],
    )


CASES = [
    Case(
        "AK1",
        "Tank wall under water: the shell model against a cantilever",
        "analysis",
        (
            "Base moment and shear of a long tank wall fixed at its base and free at its top under "
            "a hydrostatic pressure, from the shell model of the tank design."
        ),
        (
            "Wall 12 × 3 m, 250 mm, fixed base, water to the top; plumbing.tanks_model.wall_panel "
            "(ASDShellQ4, 8 elements over the height)."
        ),
        wall_case,
    ),
    Case(
        "DK1",
        "Flotation of an empty underground tank",
        "design",
        (
            "Uplift on the base under the water table at the ground against the concrete and the "
            "soil on the toe."
        ),
        (
            "Tank 4 × 3 × 2.8 m inside, walls 200, base 250 with a 500 mm toe, roof 150; "
            "plumbing.tanks.flotation."
        ),
        flotation_case,
    ),
    Case(
        "DK2",
        "Crack width of a tank wall",
        "design",
        "EN 1992-1-1 7.3.4 crack width of a wall in bending from its elastic cracked section.",
        "Wall 200 mm, Ø12 @ 150, c = 44, f'c 27.6, M = 12 kN·m/m; plumbing.tanks.crack_width.",
        crack_case,
    ),
    Case(
        "DK3",
        "Overhead tank: weight on the roof",
        "design",
        "Empty and full weight of an overhead tank, the load it puts on the roof structure.",
        (
            "Tank 3 × 2.5 m inside, water 1.5 m, walls 150, base 175, roof 125; "
            "plumbing.tanks.support_loads."
        ),
        overhead_case,
    ),
]
