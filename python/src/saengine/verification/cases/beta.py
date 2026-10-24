"""Benchmarks of the "structural office beta" items: punching with headed studs, a P-M point of a
flanged (T) wall, a lintel over a door, and the gravity load the building generator sizes its
columns for. Synthetic data; the references are plain arithmetic of the code's equations (or, for
the generator, of the generated geometry and the project's area loads), none of SAEngine's
helpers used for them. Units: mm, MPa, N, N·mm; reported in kN, kN·m, MPa.
"""

from __future__ import annotations

import math
from pathlib import Path

from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

EXACT = 1e-3


def _area(dia: float) -> float:
    return math.pi * dia**2 / 4


def punching_studs(_: Path) -> Outcome:
    from saengine.design import punching as P

    fc, c, d, vu_kn = 30.0, 500.0, 210.0, 1100.0
    studs = P.ShearReinforcement("studs", 12.0, 12, 6, 90.0, 140.0, 350.0)
    big = [(-6000.0, -6000.0), (6000.0, -6000.0), (6000.0, 6000.0), (-6000.0, 6000.0)]
    result = P.slab_punching(
        (0.0, 0.0), c, c, 0.0, d, big, [P.Demand(vu_kn * 1e3, 0.0, 0.0, "U")], fc,
        thickness=260.0, provided=studs,
    )  # fmt: skip
    assert result is not None and result.reinforcement is not None
    r = result.reinforcement
    root = math.sqrt(fc)
    b0 = 4 * (c + d)
    vu = vu_kn * 1e3 / (b0 * d)
    vc = root * min(0.25, 0.17 * (1 + 2 / 1.0), 0.083 * (2 + 40 * d / b0))
    vs = 12 * _area(12) * 350 / (b0 * 140)
    capacity = 0.75 * min(vc + vs, 0.66 * root)
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 6.4.10.1, 6.4.10.5.1 (pp. 937-941), Eq. 6.6.72-6.6.74",
        formula="b0 = 4 (c + d); vu = Vu / (b0 d); with studs vc = λ √f'c min(0.25, 0.17 (1 + "
        "2/β), 0.083 (2 + αs d / b0)); vs = Av fyt / (b0 s); φ (vc + vs) <= φ 0.66 √f'c",
        steps=[
            "interior column 500 x 500 mm, d = 210 mm, f'c = 30 MPa, Vu = 1100 kN, no moment",
            f"b0 = 4 x 710 = {fmt(b0)} mm, vu = {fmt(vu)} MPa",
            f"vc = √30 x min(0.25, 0.51, {fmt(0.083 * (2 + 40 * d / b0))}) = {fmt(vc)} MPa",
            f"12 Ø12 studs per line, s = 140 mm, fyt = 350 MPa: vs = {fmt(vs)} MPa",
            f"φ (vc + vs) = {fmt(capacity)} MPa (vn,max = 0.66 √30 = {fmt(0.66 * root)} MPa)",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("vu", "MPa", vu, result.vu, EXACT),
            Quantity("vc with studs", "MPa", vc, r.vc, EXACT),
            Quantity("vs", "MPa", vs, r.vs, EXACT),
            Quantity(
                "φ(vc + vs) b0 d",
                "kN",
                capacity * b0 * d / 1e3,
                result.check("P")["capacity"],
                0.005,
            ),
        ],
        ["the outer section beyond the last line is checked by SAEngine as well (its own row)"],
    )


def t_wall_point(_: Path) -> Outcome:
    from shapely import affinity
    from shapely.geometry import box
    from shapely.ops import unary_union

    from saengine.design import wall_flanges as F
    from saengine.design.rc import Bar

    fc, fy, es = 25.0, 420.0, 200_000.0
    # Flange 1000 x 200 (y 800-1000), web 200 x 800 (y 0-800); 4 Ø16 at y = 950, 2 Ø20 at y = 50.
    yc = (200_000 * 900 + 160_000 * 400) / 360_000
    poly = affinity.translate(
        unary_union([box(-500, 800, 500, 1000), box(-100, 0, 100, 800)]), 0, -yc
    )
    bars = [Bar(x, 950 - yc, _area(16), 16) for x in (-450, -150, 150, 450)]
    bars += [Bar(x, 50 - yc, _area(20), 20) for x in (-50, 50)]
    section = F.FlangedSection(poly, tuple(bars), fc, fy, es, (0.0, yc), (0.0, 1.0), ["web"])
    pn, _, sy, _ = F.FlangedInteraction(section, coarse=True).actions(0.0, 400.0)
    # c = 400: a = 0.85 x 400 = 340 mm: the flange (200) and 140 mm of web in the block.
    cf, cw = 0.85 * fc * 1000 * 200, 0.85 * fc * 200 * 140
    top_strain = 0.003 * (400 - 50) / 400
    top = (min(es * top_strain, fy) - 0.85 * fc) * 4 * _area(16)
    bottom = -fy * 2 * _area(20)
    pn_hand = cf + cw + top + bottom
    mn_hand = cf * (900 - yc) + cw * (730 - yc) + top * (950 - yc) + bottom * (50 - yc)
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 6.3.2 (strain compatibility, the stress block), 8.3.6.5",
        formula="a = β1 c; C = 0.85 f'c (flange + web in the block); fs = Es εs <= fy, εs = "
        "0.003 (c - y) / c; Pn = ΣF, Mn = ΣF (y - yc) about the gross centroid",
        steps=[
            (
                f"T: flange 1000 x 200, web 200 x 800 mm; gross centroid yc = {fmt(yc)} mm from the "
                "web's tip; f'c = 25, fy = 420 MPa"
            ),
            (
                f"c = 400 mm (compression at the flange): a = 340 mm; Cf = {fmt(cf / 1e3)} kN, Cw = "
                f"{fmt(cw / 1e3)} kN"
            ),
            (
                f"top bars ε = {fmt(top_strain)} > εy: {fmt(top / 1e3)} kN (less the displaced "
                f"concrete); bottom bars yield in tension: {fmt(bottom / 1e3)} kN"
            ),
            f"Pn = {fmt(pn_hand / 1e3)} kN, Mn = {fmt(mn_hand / 1e6)} kN·m",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Pn at c = 400 mm", "kN", pn_hand / 1e3, pn / 1e3, EXACT),
            Quantity("Mn at c = 400 mm", "kN·m", mn_hand / 1e6, sy / 1e6, EXACT),
        ],
    )


def lintel(_: Path) -> Outcome:
    from saengine.design import lintels as L

    clear, width, depth, above = 1200.0, 250.0, 150.0, 1000.0
    loads = L.lintel_loads(clear, width, depth, above, masonry_weight=18.85, concrete_weight=24)
    found = L.design_lintel(loads, width, depth, 25.0, 420.0)
    span = clear + 150
    rise = span / 2  # 45°
    q_t = 18.85e-6 * width * rise
    w = 24e-6 * width * depth
    mu = 1.4 * (q_t * span**2 / 12 + w * span**2 / 8)
    vu = 1.4 * (q_t * span / 4 + w * span / 2)
    dd = depth - 25 - 8 - 5
    a = 2 * _area(10) * 420 / (0.85 * 25 * width)
    phi_mn = 0.9 * 2 * _area(10) * 420 * (dd - a / 2)
    flexure = found["checks"][0]
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 7.4.3.2 (p. 1015), Sec 2.7.3.1 (p. 685); stated 45° rule",
        formula="L = clear + bearing; masonry arches over a triangle of height L/2 tan 45°: q_t = "
        "γ t L/2; Mu = 1.4 (q_t L²/12 + w L²/8), Vu = 1.4 (q_t L/4 + w L/2); φMn of 2 Ø10",
        steps=[
            (
                "door 1200 mm, bearings 150 mm: L = 1350 mm; lintel 250 x 150; 1000 mm of brick "
                "(18.85 kN/m³) above: it arches"
            ),
            f"q_t = {fmt(q_t)} N/mm, own weight w = {fmt(w)} N/mm",
            f"Mu = {fmt(mu / 1e6)} kN·m, Vu = {fmt(vu / 1e3)} kN (1.4D, no live load)",
            f"2 Ø10, d = {fmt(dd)} mm: a = {fmt(a)} mm, φMn = {fmt(phi_mn / 1e6)} kN·m",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Mu", "kN·m", mu / 1e6, found["loads"]["Mu"], 0.01),
            Quantity("Vu", "kN", vu / 1e3, found["loads"]["Vu"], 0.01),
            Quantity("φMn", "kN·m", phi_mn / 1e6, flexure["capacity"], 0.01),
        ],
    )


def generator_gravity(_: Path) -> Outcome:
    from saengine.library.defaults import default_material_library
    from saengine.library.generator import generate_building

    spec = {
        "name": "Gravity",
        "gridsX": [6000, 5000],
        "gridsY": [5000, 4000],
        "storyCount": 3,
        "typicalHeight": 3200,
        "groundHeight": 3600,
        "concrete": "C24.1",
        "rebar": "B420DWR",
        "location": "dhaka",
        "occupancy": "office",
        "occupancyCategory": "II",
    }
    result = generate_building(spec)
    plan, objects, settings = result["floorPlan"], result["objects"], result["settings"]
    density = default_material_library().get("C24.1").mechanical.density or 2400.0
    gamma = density * 9.80665 / 1000  # kN/m³
    types = {o["id"]: o for o in objects["objects"]}
    xs = {g["label"]: g["position"] for g in plan["grids"]["x"]}
    ys = {g["label"]: g["position"] for g in plan["grids"]["y"]}
    levels = {s["id"]: s["elevation"] for s in plan["stories"]}
    loads = {a["id"]: a for a in settings["areaLoads"]}
    roof = plan["stories"][-1]["id"]
    total = slabs = beams = columns = 0.0
    least = min(t["thickness"] for t in types.values() if t["kind"] == "slab")
    for s in plan["slabs"]:
        corners = [(xs[p["x"]], ys[p["y"]]) for p in s["boundary"]]
        area = (
            abs(
                sum(
                    x0 * y1 - x1 * y0
                    for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1], strict=True)
                )
            )
            / 2
            / 1e6
        )
        load = loads[settings["roofLoad"] if s["story"] == roof else settings["floorLoad"]]
        q = types[s["type"]]["thickness"] / 1000 * gamma + load["finish"] + load["partitions"]
        slabs += area * (q + load["live"])
    for b in plan["beams"]:
        p = types[b["type"]]["profile"]
        span = math.dist(
            (xs[b["start"]["x"]], ys[b["start"]["y"]]), (xs[b["end"]["x"]], ys[b["end"]["y"]])
        )
        beams += span / 1000 * p["xDim"] / 1000 * (p["yDim"] - least) / 1000 * gamma
    for c in plan["columns"]:
        p = types[c["type"]]["profile"]
        height = (levels[c["top"]] - levels[c["base"]]) / 1000
        columns += p["xDim"] / 1000 * p["yDim"] / 1000 * height * gamma
    total = slabs + beams + columns
    generated = sum(result["summary"]["baseServiceLoads"].values())
    reference = Reference(
        source="Statics: the base loads the columns are sized for add up to the building's "
        "service gravity load (tributary areas cover each floor exactly once)",
        formula="Σ floors A_slab (t γ + finishes + partitions + live) + Σ beams l b (h - t_min) γ "
        "+ Σ columns b h H γ",
        steps=[
            (
                "3 storeys (3.6, 3.2, 3.2 m) on grids 6 + 5 m by 5 + 4 m, office use, C24.1 "
                f"(γ = {fmt(gamma)} kN/m³), the generated slab, beam and column types"
            ),
            (
                f"slabs with their area loads: {fmt(slabs)} kN; beams below the thinnest slab: "
                f"{fmt(beams)} kN; columns: {fmt(columns)} kN"
            ),
            f"total {fmt(total)} kN",
        ],
    )
    return Outcome(
        reference,
        [Quantity("Σ base service loads of the columns", "kN", total, generated, 0.005)],
        ["the generator's columns are sized from these loads (gravity only, preliminary)"],
    )


CASES = [
    Case(
        "DX1",
        "Punching: headed shear studs at an interior column",
        "design",
        "vc, vs and the utilisation of a flat slab's critical section with a given stud layout.",
        "Column 500 x 500 mm, d = 210 mm, f'c = 30 MPa, Vu = 1100 kN, 6 lines of 12 Ø12 studs "
        "@ 140 mm; punching.slab_punching.",
        punching_studs,
    ),
    Case(
        "DX2",
        "Walls: a P-M point of a flanged (T) wall",
        "design",
        "Pn and Mn of a T section by strain compatibility at a neutral-axis depth in the web.",
        "Flange 1000 x 200, web 200 x 800 mm, 4 Ø16 + 2 Ø20, c = 400 mm; "
        "wall_flanges.FlangedInteraction.",
        t_wall_point,
    ),
    Case(
        "DX3",
        "Lintel over a door in a brick wall",
        "design",
        "The 45° arching load, the factored moment and shear, and φMn of the bars chosen.",
        "Door 1200 mm, lintel 250 x 150 mm, 1000 mm of brick above; lintels.design_lintel.",
        lintel,
    ),
    Case(
        "DX4",
        "Building generator: gravity load at the base",
        "design",
        "The service loads the generator sizes the columns for add up to the building's weight "
        "and area loads.",
        "2 x 2 bays (6 + 5 m by 5 + 4 m), 3 storeys, office; library.generator.",
        generator_gravity,
    ),
]
