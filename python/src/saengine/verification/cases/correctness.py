"""Benchmarks of the correctness round (0.0.45): slab loads on beams as triangles and trapezoids,
the two-way slab coefficients, the live load arrangements, beam torsion, the effective moment of
inertia and the wind's torsional case. Each against a hand calculation written out in the case.

Units: mm, MPa, N, N·mm for the design cases; m, N, Pa for the analysis cases.
"""

from __future__ import annotations

import math
from pathlib import Path

from saengine.verification.cases.common import Case, Outcome, Quantity, Reference, fmt

#: Tolerance of a hand calculation the code reproduces in closed form.
EXACT = 0.005


def _opensees_beam(
    length: float,
    members: int,
    fixed: bool,
    loads: list[tuple[float, float, float]],
    supports: list[float] | None = None,
) -> list[float]:
    """A 2D beam in OpenSees (the bundled analysis), ``members`` equal members, each loaded with
    (uniform w [N/m], nodal force at its start, at its end [N], downward); fixed or pinned
    ends, and ``supports`` (stations [m]) pinned in between. Returns the bending moment at each
    node [N·m, sagging positive]."""
    from openseespy import opensees as ops

    ops.wipe()
    ops.model("basic", "-ndm", 2, "-ndf", 3)
    for i in range(members + 1):
        ops.node(i + 1, length * i / members, 0.0)
    ops.fix(1, 1, 1, 1 if fixed else 0)
    ops.fix(members + 1, 0, 1, 1 if fixed else 0)
    for at in supports or []:
        node = round(at / length * members) + 1
        ops.fix(node, 0, 1, 0)
    ops.geomTransf("Linear", 1)
    for i in range(members):
        ops.element("elasticBeamColumn", i + 1, i + 1, i + 2, 0.15, 25e9, 3.125e-3, 1)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    for i, (w, f0, f1) in enumerate(loads):
        if w:
            ops.eleLoad("-ele", i + 1, "-type", "-beamUniform", -w)
        if f0:
            ops.load(i + 1, 0.0, -f0, 0.0)
        if f1:
            ops.load(i + 2, 0.0, -f1, 0.0)
    ops.system("UmfPack")
    ops.numberer("RCM")
    ops.constraints("Plain")
    ops.integrator("LoadControl", 1.0)
    ops.algorithm("Linear")
    ops.analysis("Static")
    if ops.analyze(1) != 0:
        ops.wipe()
        raise RuntimeError("the beam did not solve")
    # The end moments acting on each element (counter-clockwise positive): the bending moment,
    # sagging positive, is minus that at its start and that at its end.
    moments = [-ops.eleForce(i + 1)[2] for i in range(members)]
    moments.append(ops.eleForce(members)[5])
    ops.wipe()
    return moments


# ─────────────────────────── slab load on a beam: the triangle ───────────────────────────


def triangle_beam(_: Path) -> Outcome:
    from saengine.fem.slab_load_shapes import segment_loads, slab_load_shapes

    L, p = 6.0, 10e3  # m, Pa: a 6 m square panel, 10 kN/m² (factored)
    shape = slab_load_shapes([(0, 0), (L, 0), (L, L), (0, L)], p, "twoWay")
    edge = shape.edges[0]
    members = 12
    loads = [segment_loads(edge, L * i / members, L * (i + 1) / members) for i in range(members)]
    fixed = _opensees_beam(L, members, True, loads)
    simple = _opensees_beam(L, members, False, loads)
    w = p * L / 2  # the triangle's peak [N/m]: the panel's half width times p
    total = p * L**2 / 4
    fem_hand = 5 * w * L**2 / 96
    mid_hand = w * L**2 / 32
    simple_hand = w * L**2 / 12
    return Outcome(
        Reference(
            "Fixed-end moments of a symmetric triangular load (e.g. Roark, Table 8.1 case 2e / "
            "any structural analysis text); BNBC 2020 Part 6 Sec 6.5.6.8.1 (p. 955): the load "
            "of a two-way panel on its beams by the 45° lines from the corners.",
            "W = p L²/4, w = p L/2; FEM = 5 w L²/96, M_mid = w L²/12 - 5 w L²/96 = w L²/32; "
            "simple span: M_mid = w L²/12 = W L/6",
            [
                (
                    f"L = {fmt(L)} m, p = {fmt(p / 1e3)} kN/m²: w = {fmt(w / 1e3)} kN/m, "
                    f"W = {fmt(total / 1e3)} kN"
                ),
                f"FEM = 5 × {fmt(w / 1e3)} × {fmt(L)}²/96 = {fmt(fem_hand / 1e3)} kN·m",
                f"fixed-fixed midspan = {fmt(w / 1e3)} × {fmt(L)}²/32 = {fmt(mid_hand / 1e3)} kN·m",
                (
                    f"simply supported midspan = {fmt(w / 1e3)} × {fmt(L)}²/12 = "
                    f"{fmt(simple_hand / 1e3)} kN·m (the uniform load of the same total gave W L/8 "
                    f"= {fmt(total * L / 8 / 1e3)} kN·m, 25 % low)"
                ),
            ],
        ),
        [
            Quantity("Edge total W", "kN", total / 1e3, edge.total / 1e3, EXACT),
            Quantity("Fixed-end moment", "kN·m", fem_hand / 1e3, -fixed[0] / 1e3, 0.01),
            Quantity("Fixed-fixed midspan moment", "kN·m", mid_hand / 1e3, fixed[6] / 1e3, 0.01),
            Quantity(
                "Simple-span midspan moment", "kN·m", simple_hand / 1e3, simple[6] / 1e3, 0.01
            ),
        ],
        [
            (
                "The beam is cut into 12 members; each takes the mean intensity of the shape over it "
                "and a pair of opposite nodal forces with the shape's moment "
                "(saengine.fem.slab_load_shapes.segment_loads), as the analysis model applies it."
            )
        ],
    )


# ─────────────────────────── two-way slab coefficients ───────────────────────────


def two_way_panel(_: Path) -> Outcome:
    from saengine.design import slab as slab_design

    la, lb = 4.0, 5.0  # m (clear spans), m = 0.80
    wd, wl = 6.0, 3.0  # kN/m², factored dead and live
    case = 4  # two adjacent edges continuous
    c = slab_design.two_way_coefficients(la / lb, case)
    # BNBC 2020 Part 6 Tables 6.6.8 (p. 961), 6.6.9 (p. 963), 6.6.10 (p. 964), m = 0.80, case 4
    neg_a, neg_b, dl_a, dl_b, ll_a, ll_b = 0.071, 0.029, 0.039, 0.016, 0.048, 0.020
    w = wd + wl
    hand = {
        "Ma,neg": neg_a * w * la**2,
        "Mb,neg": neg_b * w * lb**2,
        "Ma,pos": dl_a * wd * la**2 + ll_a * wl * la**2,
        "Mb,pos": dl_b * wd * lb**2 + ll_b * wl * lb**2,
    }
    code = {
        "Ma,neg": (c.neg_a or 0.0) * w * la**2,
        "Mb,neg": (c.neg_b or 0.0) * w * lb**2,
        "Ma,pos": c.dead_a * wd * la**2 + c.live_a * wl * la**2,
        "Mb,pos": c.dead_b * wd * lb**2 + c.live_b * wl * lb**2,
    }
    # Interpolated: m = 0.825 between the 0.80 and 0.85 rows (Ca,neg 0.071 and 0.066).
    mid = slab_design.two_way_coefficients(0.825, case)
    return Outcome(
        Reference(
            "BNBC 2020 Part 6 Sec 6.5.8.3.1 and Tables 6.6.8-6.6.10 (pp. 961-964), case 4, "
            "m = la/lb = 0.80 (values read from the code's tables)",
            "Ma,neg = Ca,neg w la², Ma,pos = Ca,dl wD la² + Ca,ll wL la² (and b with lb)",
            [
                f"la = {fmt(la)} m, lb = {fmt(lb)} m, wD = {fmt(wd)}, wL = {fmt(wl)} kN/m²",
                (
                    f"Ca,neg = {neg_a}, Cb,neg = {neg_b}; Ca,dl = {dl_a}, Cb,dl = {dl_b}; Ca,ll = "
                    f"{ll_a}, Cb,ll = {ll_b}"
                ),
                *(f"{k} = {fmt(v)} kN·m/m" for k, v in hand.items()),
                "m = 0.825: Ca,neg = (0.071 + 0.066)/2 = 0.0685",
            ],
        ),
        [
            *(Quantity(k, "kN·m/m", v, code[k], EXACT) for k, v in hand.items()),
            Quantity("Ca,neg at m = 0.825", "", 0.0685, mid.neg_a or 0.0, EXACT),
        ],
    )


# ─────────────────────────── live load arrangement, 3 spans ───────────────────────────


def pattern_three_spans(_: Path) -> Outcome:
    from saengine.fem import pattern_live as pl

    L, w = 6.0, 10e3  # m, N/m: three equal spans, live load only
    per_span = 12
    grid = pl.Grid.of([(0.0, 0.0), (L * 1e3, 0.0), (2 * L * 1e3, 0.0), (3 * L * 1e3, 0.0)])
    arrangements = pl.live_patterns(grid)
    members = 3 * per_span
    envelope_span, envelope_support = 0.0, 0.0
    full = None
    for arrangement in [None, *arrangements]:
        loads = []
        for i in range(members):
            x = (i + 0.5) * L / per_span
            on = arrangement is None or arrangement.loads(grid, x * 1e3, 0.0)
            loads.append((w if on else 0.0, 0.0, 0.0))
        moments = _opensees_beam(3 * L, members, False, loads, [L, 2 * L])
        span = max(moments[: per_span + 1])
        support = -moments[per_span]
        if arrangement is None:
            full = (span, support)
        envelope_span = max(envelope_span, span)
        envelope_support = max(envelope_support, support)
    assert full is not None
    # Three-moment equation by hand (equal spans, EI constant):
    # all spans: M_B = wL²/10, end span max = 0.08 wL²;
    # spans 1 and 3: M_B = wL²/20, R_A = 0.45 wL, end span max = 0.45² wL²/2 = 0.10125 wL²;
    # spans 1 and 2: 4 M_B + M_C = wL²/2, M_B + 4 M_C = wL²/4 -> M_B = 7 wL²/60.
    return Outcome(
        Reference(
            "BNBC 2020 Part 6 Sec 6.1.12.2 (p. 894): live load on two adjacent spans and on "
            "alternate spans; moments by the three-moment equation",
            "end span +M = 0.10125 wL² (spans 1, 3 loaded); M_B = 7 wL²/60 (spans 1, 2); "
            "full load: 0.08 wL² and wL²/10",
            [
                f"w = {fmt(w / 1e3)} kN/m, L = {fmt(L)} m: wL² = {fmt(w * L**2 / 1e3)} kN·m",
                f"full load: +M = {fmt(0.08 * w * L**2 / 1e3)}, M_B = {fmt(w * L**2 / 10 / 1e3)}",
                (
                    f"arrangements: +M = {fmt(0.10125 * w * L**2 / 1e3)}, "
                    f"M_B = {fmt(7 * w * L**2 / 60 / 1e3)} kN·m"
                ),
                f"{len(arrangements)} arrangements: {'; '.join(a.label for a in arrangements)}",
            ],
        ),
        [
            Quantity(
                "Full load end-span moment", "kN·m", 0.08 * w * L**2 / 1e3, full[0] / 1e3, 0.01
            ),
            Quantity("Full load support moment", "kN·m", w * L**2 / 10 / 1e3, full[1] / 1e3, 0.01),
            Quantity(
                "Envelope end-span moment",
                "kN·m",
                0.10125 * w * L**2 / 1e3,
                envelope_span / 1e3,
                0.01,
            ),
            Quantity(
                "Envelope support moment",
                "kN·m",
                7 * w * L**2 / 60 / 1e3,
                envelope_support / 1e3,
                0.01,
            ),
        ],
    )


# ─────────────────────────── beam torsion ───────────────────────────


def torsion_section(_: Path) -> Outcome:
    from saengine.design import torsion

    b, h, cover, stirrup, d = 300.0, 600.0, 40.0, 10.0, 540.0
    fc, fy = 25.0, 420.0
    tu, vu = 30e6, 150e3  # N·mm, N
    sec = torsion.TorsionSection(b, h, cover, stirrup, d)
    rules = torsion.TorsionRules(45.0, 0.85, 300.0, 8.0, 300.0, 0.042, 10.0, 420.0)
    result = torsion.design_torsion(sec, tu, vu, fc, fy, fy, "equilibrium", rules=rules, phi=0.75)
    root = math.sqrt(fc)
    acp, pcp = b * h, 2 * (b + h)
    tth = 0.75 * 0.083 * root * acp**2 / pcp
    x1, y1 = b - 2 * cover - stirrup, h - 2 * cover - stirrup
    aoh, ph = x1 * y1, 2 * (x1 + y1)
    at_s = tu / (0.75 * 2 * 0.85 * aoh * fy)
    al = at_s * ph
    vc = 0.17 * root * b * d
    stress = math.hypot(vu / (b * d), tu * ph / (1.7 * aoh**2))
    limit = 0.75 * (vc / (b * d) + 0.66 * root)
    return Outcome(
        Reference(
            "BNBC 2020 Part 6 Sec 6.4.4 (pp. 926-931): Eqs. 6.6.59, 6.6.61-6.6.63",
            "φTth = φ 0.083 √f'c Acp²/pcp; At/s = Tu/(2 φ Ao fyt cot θ), Ao = 0.85 Aoh; "
            "Al = (At/s) ph (fyt/fy) cot² θ; √((Vu/bw d)² + (Tu ph/1.7 Aoh²)²) ≤ "
            "φ(Vc/bw d + 0.66 √f'c)",
            [
                (
                    f"b × h = {fmt(b)} × {fmt(h)} mm, cover {fmt(cover)}, Ø{fmt(stirrup)} stirrups, "
                    f"d = {fmt(d)} mm, f'c = {fmt(fc)}, fy = fyt = {fmt(fy)} MPa"
                ),
                f"Acp = {fmt(acp)} mm², pcp = {fmt(pcp)} mm: φTth = {fmt(tth / 1e6)} kN·m",
                f"x1 = {fmt(x1)}, y1 = {fmt(y1)} mm: Aoh = {fmt(aoh)} mm², ph = {fmt(ph)} mm",
                f"At/s = {fmt(tu)}/(0.75 × 2 × 0.85 × {fmt(aoh)} × {fmt(fy)}) = {fmt(at_s)} mm²/mm",
                f"Al = {fmt(at_s)} × {fmt(ph)} = {fmt(al)} mm²",
                f"stress {fmt(stress)} MPa ≤ limit {fmt(limit)} MPa",
            ],
        ),
        [
            Quantity("φTth", "kN·m", tth / 1e6, result.phi_tth / 1e6, EXACT),
            Quantity("At/s per leg", "mm²/mm", at_s, result.at_s, EXACT),
            Quantity("Al", "mm²", al, result.al, EXACT),
            Quantity("Section stress (Eq. 6.6.59)", "MPa", stress, result.stress, EXACT),
            Quantity("Section limit (Eq. 6.6.59)", "MPa", limit, result.stress_limit, EXACT),
        ],
    )


# ─────────────────────────── deflection with Ie ───────────────────────────


def ie_deflection(_: Path) -> Outcome:
    from saengine.design import deflection
    from saengine.design.rc import section_of
    from saengine.library.objects import LinearReinforcement, RectangleProfile

    b, h, span = 300.0, 500.0, 6000.0
    fc, fy, es = 25.0, 420.0, 200_000.0
    reinforcement = LinearReinforcement.model_validate(
        {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [{"position": "bottom", "count": 3, "dia": 16}],
            "transverse": {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2},
        }
    )
    section = section_of(RectangleProfile(xDim=b, yDim=h), reinforcement, fc, fy, es)
    ec = 4700 * math.sqrt(fc)
    wd, wl = 15.0, 10.0  # N/mm (kN/m), service dead and live on a simple span
    ig = b * h**3 / 12
    ei = ec * ig
    d_dead = 5 * wd * span**4 / (384 * ei)
    d_live = 5 * wl * span**4 / (384 * ei)
    m_dead, m_live = wd * span**2 / 8, wl * span**2 / 8
    limits = deflection.DeflectionLimits(
        360, 180, 480, 240, {3: 1.0, 6: 1.2, 12: 1.4, 60: 2.0}, (16, 18.5, 21), 8
    )
    stiffness = deflection.section_stiffness(section, ec)
    result = deflection.span_deflection(
        span, stiffness, fc, ec, ei, (m_dead, d_dead), (m_live, d_live), 0.25, limits=limits
    )
    # By hand: the cracked section (n As (d - c) = b c²/2), Ie of Eq. 6.6.1.
    area = 3 * math.pi * 16**2 / 4
    dd = h - 40 - 10 - 8
    n = es / ec
    c = (-n * area + math.sqrt((n * area) ** 2 + 2 * b * n * area * dd)) / b
    icr = b * c**3 / 3 + n * area * (dd - c) ** 2
    mcr = 0.62 * math.sqrt(fc) * ig / (h / 2)
    ma = m_dead + m_live
    ie = min((mcr / ma) ** 3 * ig + (1 - (mcr / ma) ** 3) * icr, ig)
    total = 5 * (wd + wl) * span**4 / (384 * ec * ie)
    return Outcome(
        Reference(
            "BNBC 2020 Part 6 Sec 6.2.5 (pp. 899-902): Eqs. 6.6.1-6.6.3; simply supported span "
            "under uniform load Δ = 5 w l⁴/(384 Ec Ie)",
            "Ie = (Mcr/Ma)³ Ig + (1 - (Mcr/Ma)³) Icr ≤ Ig, Mcr = 0.62 √f'c Ig/yt",
            [
                (
                    f"b × h = {fmt(b)} × {fmt(h)} mm, 3 Ø16 bottom at d = {fmt(dd)} mm, l = "
                    f"{fmt(span)} mm, wD = {fmt(wd)}, wL = {fmt(wl)} kN/m"
                ),
                f"Ec = 4700 √f'c = {fmt(ec)} MPa, n = {fmt(n)}, Ig = {fmt(ig)} mm⁴",
                f"c = {fmt(c)} mm, Icr = {fmt(icr)} mm⁴, Mcr = {fmt(mcr / 1e6)} kN·m",
                f"Ma = {fmt(ma / 1e6)} kN·m: Ie = {fmt(ie)} mm⁴",
                (
                    f"Δ(D + L) = 5 × {fmt(wd + wl)} × {fmt(span)}⁴/(384 × {fmt(ec)} × {fmt(ie)}) = "
                    f"{fmt(total)} mm"
                ),
            ],
        ),
        [
            Quantity("Icr", "mm⁴", icr, stiffness.icr, EXACT),
            Quantity("Mcr", "kN·m", mcr / 1e6, result.mcr / 1e6, EXACT),
            Quantity("Ie (D + L)", "mm⁴", ie, result.ie_total, EXACT),
            Quantity("Immediate deflection D + L", "mm", total, result.immediate_total, EXACT),
        ],
        [
            (
                "The analysis deflection is given as the elastic 5 w l⁴/(384 Ec Ig); the check "
                "scales it by Ec Ig/(Ec Ie), as it scales the analysis model's deflections."
            )
        ],
    )


# ─────────────────────────── wind: the torsional case ───────────────────────────


def wind_torsion(work: Path) -> Outcome:
    import numpy as np

    from saengine.fem.derive import derive_fem
    from saengine.library import FloorPlan, ObjectLibrary, default_floor_plan
    from saengine.library import default_material_library as materials
    from saengine.library.bim import generate
    from saengine.library.settings import default_project_settings

    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {
                    "id": "COL",
                    "name": "Column 400x400",
                    "kind": "column",
                    "material": "C24.1",
                    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
                },
                {
                    "id": "BM",
                    "name": "Beam 300x500",
                    "kind": "beam",
                    "material": "C24.1",
                    "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
                },
            ]
        }
    )
    base = default_floor_plan().model_dump(mode="json", by_alias=True)
    stories = [{"id": "BASE", "name": "Base", "elevation": 0.0}] + [
        {"id": f"L{k}", "name": f"Level {k}", "elevation": 3200.0 * k} for k in (1, 2, 3)
    ]
    corners = [("A", "1"), ("B", "1"), ("B", "2"), ("A", "2")]
    columns, beams = [], []
    for k in (1, 2, 3):
        below = "BASE" if k == 1 else f"L{k - 1}"
        columns += [
            {"id": f"C{k}{i}", "type": "COL", "at": {"x": x, "y": y}, "base": below, "top": f"L{k}"}
            for i, (x, y) in enumerate(corners)
        ]
        beams += [
            {
                "id": f"B{k}{i}",
                "type": "BM",
                "story": f"L{k}",
                "start": {"x": a[0], "y": a[1]},
                "end": {"x": c[0], "y": c[1]},
            }
            for i, (a, c) in enumerate(zip(corners, corners[1:] + corners[:1], strict=True))
        ]
    plan = FloorPlan.model_validate(
        {**base, "stories": stories, "columns": columns, "beams": beams, "slabs": []}
    )
    settings = default_project_settings("Wind torsion")
    d = derive_fem(generate(plan, "s"), objects, materials(), settings, {"bim": "abc"})
    levels = d.summary["wind"]["levels"]["WX"]
    width = 5.0  # m: the building's face across wind in X (grid 1-2)
    by_hand = sum(0.15 * width * level["force_kN"] for level in levels)
    coords = {n["id"]: np.array(n["coords"]) for n in d.project["nodes"]}
    pattern = next(p for p in d.project["load_patterns"] if p["name"] == "WTX")
    centre = np.array([3.0, 2.5])
    moment = 0.0
    force = np.zeros(2)
    for load in pattern["nodal_loads"]:
        f = np.array(load["forces"])
        r = coords[load["node_id"]][:2] - centre
        moment += r[0] * f[1] - r[1] * f[0] + f[5]
        force += f[:2]
    return Outcome(
        Reference(
            "BNBC 2020 Part 6 Sec 2.4.11.3 (p. 559) and Figure 6.2.9 (p. 574): Case 2, the wind "
            "load displaced by e = 0.15 B across it",
            "WTX: at each level Mt = F · 0.15 B, F the level's wind force in X, B the face "
            "width across it; no net force",
            [
                "a 6 × 5 m bay, three storeys of 3.2 m (h = 9.6 m > 9.1 m: no exception)",
                *(
                    f"z = {fmt(level['z'])} m: F = {fmt(level['force_kN'])} kN, Mt = 0.15 × 5 × "
                    f"{fmt(level['force_kN'])} = {fmt(0.15 * width * level['force_kN'])} kN·m"
                    for level in levels
                ),
                f"ΣMt = {fmt(by_hand)} kN·m",
            ],
        ),
        [
            Quantity("Total torsion of WTX", "kN·m", by_hand, moment / 1e3, EXACT),
            Quantity(
                "Net force of WTX (|Fx| + |Fy|) over ΣF",
                "",
                1.0,
                1.0 + float(np.abs(force).sum()) / 1e3 / sum(lv["force_kN"] for lv in levels),
                1e-6,
            ),
        ],
        ["The levels' wind forces F are those the analysis model applies (fem.loads.wind_levels)."],
    )


CASES = [
    Case(
        "AN1",
        "Slab load on a beam: the 45° triangle",
        "analysis",
        "The load a square two-way panel hands to a beam (a triangle) applied member by member "
        "as the analysis model applies it; fixed-end and midspan moments against the closed "
        "form (the uniform load of the same total understated them by 20-25 %).",
        "Panel 6 × 6 m at 10 kN/m²; its edge beam 6 m, 12 members, fixed-fixed and simply "
        "supported; OpenSees elasticBeamColumn.",
        triangle_beam,
    ),
    Case(
        "DN1",
        "Two-way slab: BNBC coefficient method",
        "design",
        "Negative and positive moments of a two-way panel by Tables 6.6.8-6.6.10, and the "
        "linear interpolation between tabulated ratios.",
        "Panel 4 × 5 m (clear), case 4, wD = 6, wL = 3 kN/m² (factored); "
        "slab.two_way_coefficients.",
        two_way_panel,
    ),
    Case(
        "AN2",
        "Live load arrangement on a three-span beam",
        "analysis",
        "The arrangements of BNBC 6.1.12.2 (adjacent and alternate spans) from the column grid, "
        "enveloped with the full live load: the end-span and support moments the full load "
        "alone understates.",
        "Three 6 m spans, 10 kN/m live load, pinned supports; pattern_live.live_patterns on "
        "the supports' grid; OpenSees elasticBeamColumn.",
        pattern_three_spans,
    ),
    Case(
        "DN2",
        "Beam torsion: threshold, steel and section limit",
        "design",
        "Threshold torsion, closed stirrups At/s, longitudinal Al and the combined shear and "
        "torsion section limit of a rectangular beam.",
        "Beam 300 × 600 mm, cover 40, Ø10 stirrups, d = 540 mm, f'c = 25, fy = 420 MPa; Tu = "
        "30 kN·m, Vu = 150 kN; torsion.design_torsion.",
        torsion_section,
    ),
    Case(
        "DN3",
        "Deflection with the effective moment of inertia",
        "design",
        "Cracked moment of inertia, cracking moment, Ie (Eq. 6.6.1) and the immediate deflection "
        "of a simply supported beam.",
        "Beam 300 × 500 mm, 3 Ø16 bottom, 6 m simple span, 15 + 10 kN/m service load, f'c = "
        "25 MPa; deflection.span_deflection.",
        ie_deflection,
    ),
    Case(
        "AN3",
        "Wind: the torsional case WTX",
        "analysis",
        "The torsional wind case of Figure 6.2.9 as the analysis model applies it: at each level "
        "the moment F · 0.15 B and no net force.",
        "One 6 × 5 m bay, three storeys of 3.2 m, frames only; derive_fem with the default "
        "settings (Dhaka, exposure A).",
        wind_torsion,
    ),
]
