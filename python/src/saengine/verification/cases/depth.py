"""Depth tests of the structural engine (GitHub issue #298, the parity matrix's ten cheapest
structural verifications): second-order effects, a multi-storey response spectrum, rigid and
semi-rigid diaphragms, wall piers, capacity design, a retaining wall, the e2k exchange, support
settlement and the bill of quantities with a beam's detailing.

Each case runs SAEngine's own pipeline or design function and compares the result with a
reference worked out here with plain arithmetic (no SAEngine helper), within a stated tolerance.
Where a benchmark needs a load or boundary condition the pipeline does not author, the case edits
the derived project and says so in its model text.

Units: the structural model and floor plan in mm, the analysis model in m, N, kg, s, Pa.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from saengine.fem.display import result_view
from saengine.library.bim import generate
from saengine.library.settings import Settlement, SettlementSupport
from saengine.verification.cases import parity
from saengine.verification.cases.common import (
    BY_ID,
    MATERIALS,
    Case,
    Outcome,
    Quantity,
    Reference,
    building,
    derive,
    fmt,
    node_at,
    objects,
    only_pattern,
    point,
    run_model,
    settings,
    structure,
)

CONCRETE = BY_ID["C24.1"]
E_C = CONCRETE.mechanical.E * 1e6  # Pa
NU_C = CONCRETE.mechanical.nu
RHO_C = CONCRETE.mechanical.density  # kg/m³

#: Closed-form linear frame results (exact element formulations).
FRAME = 0.01


def _frame_forces(view: dict[str, Any], prefix: str) -> list[list[float]]:
    """The end forces [N, V2, V3, T, M2, M3] along the elements whose name starts with
    ``prefix``, in element order (each element's i and j ends)."""
    found: list[list[float]] = []
    for element in view["elements"]:
        if str(element["name"]).startswith(prefix):
            found += [list(map(float, f)) for f in element["forces"]]
    if not found:
        raise LookupError(f"no element named {prefix}…")
    return found


COLUMN = {
    "id": "COL",
    "name": "Column 400x400",
    "kind": "column",
    "material": CONCRETE.id,
    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
}
I_COL = 0.4**4 / 12  # m⁴


def _static_case(project: dict[str, Any], pattern_name: str) -> dict[str, Any]:
    pattern = next(p for p in project["load_patterns"] if p["name"] == pattern_name)
    return next(
        a
        for a in project["analyses"]
        if a["type"] == "Static" and pattern["id"] in a.get("pattern_ids", [])
    )


# ─────────────────────────────── 1. P-Delta cantilever ───────────────────────────────

PDELTA_SEGMENTS = 20


def p_delta(folder: Path) -> Outcome:
    """A 4 m cantilever column, 400 × 400, drawn as 20 members, under an axial load P (the
    P-Delta gravity preload) and a lateral tip load H (the dead load case), Project Settings
    second order "P-Delta"."""
    height, p, h = 4.0, 2500e3, 20e3  # m, N, N
    model = structure(
        members=[
            {
                "id": f"C{k + 1}",
                "type": "COL",
                "start": point(0, 0, 4000 * k / PDELTA_SEGMENTS),
                "end": point(0, 0, 4000 * (k + 1) / PDELTA_SEGMENTS),
            }
            for k in range(PDELTA_SEGMENTS)
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}],
    )
    d = derive(building(model), objects(COLUMN), MATERIALS, settings(secondOrder="pDelta"))
    project = d.project
    tip = node_at(project, (0, 0, height))
    preload = next(x for x in project["load_patterns"] if x["name"] == "PDelta gravity")
    preload["nodal_loads"] = [{"node_id": tip, "forces": [0, 0, -p, 0, 0, 0]}]
    preload["element_loads"] = []
    only_pattern(project, nodal=[{"node_id": tip, "forces": [h, 0, 0, 0, 0, 0]}])
    dead = _static_case(project, project["load_patterns"][0]["name"])
    assert dead.get("preload_case_ids"), "the dead load case runs on the P-Delta preload"
    columns = sum(1 for e in project["elements"] if e.get("geom_transf") == "PDelta")
    path, out, results = run_model(project, folder, [dead["id"]])
    sway = results[dead["id"]].node_disp[tip][-1][0]
    view = result_view(out, path, f"case:{dead['id']}")
    base = _frame_forces(view, "C1")[0]
    moment = max(abs(base[4]), abs(base[5]))

    ei = E_C * I_COL
    u = math.sqrt(p / ei)
    first = h * height**3 / (3 * ei)
    exact = h * (math.tan(u * height) - u * height) / (p * u)
    p_cr = math.pi**2 * ei / (4 * height**2)
    m_ref = h * height + p * exact
    reference = Reference(
        source="Beam-column theory: cantilever under an axial load P and a lateral tip load H "
        "(Timoshenko & Gere, Theory of Elastic Stability, Sec 1.5; Chen & Lui, Structural "
        "Stability), the closed-form second-order deflection",
        formula="δ = H (tan uL - uL) / (P u), u = √(P/EI); M_base = H L + P δ; "
        "approximately δ₀ / (1 - P/Pcr), Pcr = π² EI / (4 L²)",
        steps=[
            (
                f"EI = {fmt(E_C)} × {fmt(I_COL)} = {fmt(ei)} N·m², L = {height:g} m, "
                f"P = {p / 1e3:g} kN, H = {h / 1e3:g} kN"
            ),
            f"u = √(P/EI) = {fmt(u)} 1/m, uL = {fmt(u * height)}",
            f"first order δ₀ = H L³ / (3 EI) = {fmt(first * 1e3)} mm",
            (
                f"δ = H (tan uL - uL)/(P u) = {fmt(exact * 1e3)} mm, amplification "
                f"{fmt(exact / first)} (1/(1 - P/Pcr) = {fmt(1 / (1 - p / p_cr))}, Pcr = "
                f"{fmt(p_cr / 1e3)} kN)"
            ),
            (
                f"M_base = {h / 1e3:g} × {height:g} + {p / 1e3:g} × {fmt(exact)} = "
                f"{fmt(m_ref / 1e3)} kN·m"
            ),
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Tip sway with P-Delta", "mm", exact * 1e3, sway * 1e3, FRAME),
            Quantity("Amplification δ / δ₀", "-", exact / first, sway / first, FRAME),
            Quantity("Base moment H L + P δ", "kN·m", m_ref / 1e3, moment / 1e3, FRAME),
        ],
        notes=[
            (
                f"{columns} column elements with the PDelta transformation. The case replaces "
                "the derived P-Delta gravity preload by the axial load P at the tip and the dead "
                "load case by the lateral load H; the results of the case are the increment from "
                "the preloaded state."
            )
        ],
    )


# ─────────────────────────────── 2. three-storey shear building ───────────────────────────────

STOREYS, STOREY_H, STOREY_MASS = 3, 3.2, 50_000.0  # -, m, kg
#: The case's own design spectrum, Sa [m/s²] at T [s], linear between the points.
SPECTRUM = [(0.01, 4.0), (0.5, 4.0), (1.0, 2.0), (2.0, 1.0), (4.0, 0.5)]


def _cqc_rho(wi: float, wj: float, xi: float) -> float:
    """Der Kiureghian's CQC correlation coefficient of two modes, equal damping ``xi``."""
    r = wj / wi
    return 8 * xi**2 * (1 + r) * r**1.5 / ((1 - r**2) ** 2 + 4 * xi**2 * r * (1 + r) ** 2)


def shear_building(folder: Path) -> Outcome:
    """Three storeys of one 400 × 400 column, each storey's top held against rotation, vertical
    and Y movement (so each storey is a shear spring 12EI/h³), one 50 t mass in X per floor:
    the modal and the X response spectrum (CQC) cases with the case's own spectrum."""
    model = structure(
        members=[
            {
                "id": f"C{k + 1}",
                "type": "COL",
                "start": point(0, 0, 3200 * k),
                "end": point(0, 0, 3200 * (k + 1)),
            }
            for k in range(STOREYS)
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}],
    )
    d = derive(building(model), objects(COLUMN), MATERIALS, settings(responseSpectrum=True))
    project = d.project
    floors = [node_at(project, (0, 0, STOREY_H * (k + 1))) for k in range(STOREYS)]
    for node in project["nodes"]:
        node["mass"] = [0.0] * 6
        if node["id"] in floors:
            node["restraint"] = [False, True, True, True, True, True]
            node["mass"] = [STOREY_MASS, 0.0, 0.0, 0.0, 0.0, 0.0]
    project["mp_constraints"] = []
    spectrum = project["spectra"][0]
    spectrum["periods"] = [t for t, _ in SPECTRUM]
    spectrum["accelerations"] = [a for _, a in SPECTRUM]
    modal = next(a for a in project["analyses"] if a["type"] == "Modal")
    modal["n_modes"] = STOREYS
    rx = next(a for a in project["analyses"] if a["name"] == "RX: Response spectrum X")
    project["analyses"] = [a for a in project["analyses"] if a["id"] in (modal["id"], rx["id"])]
    xi = float(rx.get("damping_ratio", 0.05))
    _, _, results = run_model(project, folder, [modal["id"], rx["id"]])
    periods = sorted((float(t) for t in results[modal["id"]].periods), reverse=True)
    rs = results[rx["id"]]
    modes = sorted(rs.modes, key=lambda m: -m.period)
    roof = float(rs.combined_disp[floors[-1]][0])
    from saengine.fem.seismic_design import modal_base_shear

    base_shear = modal_base_shear(
        [
            {
                "angular_frequency": m.angular_frequency,
                "effective_mass": m.effective_mass,
                "sa_at_period": m.sa_at_period,
            }
            for m in modes
        ],
        xi,
        rs.combination,
    )

    # By hand: a uniform shear building, k per storey, m per floor.
    k = 12 * E_C * I_COL / STOREY_H**3
    n = STOREYS
    omega = [
        2 * math.sqrt(k / STOREY_MASS) * math.sin((2 * r - 1) * math.pi / (2 * (2 * n + 1)))
        for r in range(1, n + 1)
    ]
    shapes = [
        [math.sin(j * (2 * r - 1) * math.pi / (2 * n + 1)) for j in range(1, n + 1)]
        for r in range(1, n + 1)
    ]
    gamma = [sum(s) / sum(v * v for v in s) for s in shapes]
    m_eff = [STOREY_MASS * sum(s) ** 2 / sum(v * v for v in s) for s in shapes]
    t_ref = [2 * math.pi / w for w in omega]
    sa = [float(np.interp(t, [p for p, _ in SPECTRUM], [a for _, a in SPECTRUM])) for t in t_ref]
    u_roof = [gamma[r] * shapes[r][-1] * sa[r] / omega[r] ** 2 for r in range(n)]
    v_base = [m_eff[r] * sa[r] for r in range(n)]

    def cqc(values: list[float]) -> float:
        return math.sqrt(
            sum(
                _cqc_rho(omega[i], omega[j], xi) * values[i] * values[j]
                for i in range(n)
                for j in range(n)
            )
        )

    roof_ref, shear_ref = cqc(u_roof), cqc(v_base)
    total = n * STOREY_MASS
    reference = Reference(
        source="Uniform N-storey shear building (Chopra, Dynamics of Structures, the uniform "
        "shear frame; Clough & Penzien, Dynamics of Structures): ωn = 2√(k/m) sin((2n-1)π/"
        "(2(2N+1))), φjn = sin(j(2n-1)π/(2N+1)); CQC with Der Kiureghian's coefficient",
        formula="Γn = Σφ/Σφ², M*n = m(Σφ)²/Σφ²; u = Γn φ Sa/ωn², V = M*n Sa; "
        "r = √(ΣΣ ρij ri rj), ρij = 8ξ²(1+β)β^1.5 / ((1-β²)² + 4ξ²β(1+β)²)",
        steps=[
            (
                f"k = 12 E I / h³ = 12 × {fmt(E_C)} × {fmt(I_COL)} / {STOREY_H:g}³ = {fmt(k)} N/m, "
                f"m = {STOREY_MASS / 1e3:g} t per floor, ξ = {xi:g}"
            ),
            "T = "
            + ", ".join(f"{fmt(t)}" for t in t_ref)
            + " s; Sa = "
            + ", ".join(fmt(a) for a in sa)
            + " m/s² (the case's spectrum)",
            "M*/Σm = " + ", ".join(fmt(m / total) for m in m_eff),
            "roof u per mode = "
            + ", ".join(fmt(u * 1e3) for u in u_roof)
            + f" mm; CQC {fmt(roof_ref * 1e3)} mm",
            "base shear per mode = "
            + ", ".join(fmt(v / 1e3) for v in v_base)
            + f" kN; CQC {fmt(shear_ref / 1e3)} kN",
        ],
    )
    quantities = [Quantity(f"Period T{r + 1}", "s", t_ref[r], periods[r], FRAME) for r in range(n)]
    quantities += [
        Quantity(
            f"Modal mass ratio, mode {r + 1}", "-", m_eff[r] / total, modes[r].mass_ratio, FRAME
        )
        for r in range(n)
    ]
    quantities += [
        Quantity("Roof displacement, CQC", "mm", roof_ref * 1e3, roof * 1e3, FRAME),
        Quantity("Base shear, CQC", "kN", shear_ref / 1e3, base_shear / 1e3, FRAME),
    ]
    return Outcome(
        reference,
        quantities,
        notes=[
            (
                "The case holds every floor node against rotation, vertical and Y movement (a "
                "shear building), replaces the derived masses by 50 t in X per floor and the "
                "design spectrum by its own table; combination "
                f"{rs.combination}. The base shear is SAEngine's modal_base_shear of the modes."
            )
        ],
    )


# ─────────────────────────────── 3. rigid diaphragm ───────────────────────────────


def _torsion_constant(a: float, b: float) -> float:
    """Saint-Venant torsion constant of an a × b rectangle (a ≥ b), Timoshenko & Goodier's
    series."""
    a, b = max(a, b), min(a, b)
    series = sum(math.tanh(n * math.pi * a / (2 * b)) / n**5 for n in range(1, 40, 2))
    return a * b**3 / 3 * (1 - 192 / math.pi**5 * b / a * series)


def rigid_diaphragm(folder: Path) -> Outcome:
    """Four cantilever columns 3.2 m high at the corners of a 6 × 5 m plan, the one at the
    origin 500 × 500 and the others 400 × 400, their tops tied by a rigid diaphragm; 100 kN in
    X at the plan's centre."""
    height, force = 3.2, 100e3
    corners = [(0.0, 0.0, "C5"), (6.0, 0.0, "COL"), (6.0, 5.0, "COL"), (0.0, 5.0, "COL")]
    big = {
        **COLUMN,
        "id": "C5",
        "name": "Column 500x500",
        "profile": {"shape": "rectangle", "xDim": 500, "yDim": 500},
    }
    model = structure(
        members=[
            {
                "id": f"C{i + 1}",
                "type": t,
                "start": point(x * 1000, y * 1000, 0),
                "end": point(x * 1000, y * 1000, height * 1000),
            }
            for i, (x, y, t) in enumerate(corners)
        ],
        supports=[
            {"id": f"S{i + 1}", "at": point(x * 1000, y * 1000, 0)}
            for i, (x, y, _) in enumerate(corners)
        ],
    )
    d = derive(building(model), objects(COLUMN, big), MATERIALS, settings())
    project = d.project
    tops = [node_at(project, (x, y, height)) for x, y, _ in corners]
    centre = (3.0, 2.5)
    master = 1 + max(n["id"] for n in project["nodes"])
    project["nodes"].append(
        {
            "id": master,
            "coords": [centre[0], centre[1], height],
            "restraint": [False, False, True, True, True, False],
            "mass": [0.0] * 6,
        }
    )
    for node in project["nodes"]:
        node["mass"] = [0.0] * 6
    project["mp_constraints"] = [
        {
            "type": "RigidDiaphragm",
            "perp_dir": 3,
            "retained_node": master,
            "constrained_nodes": tops,
        }
    ]
    only_pattern(project, nodal=[{"node_id": master, "forces": [force, 0, 0, 0, 0, 0]}])
    case = _static_case(project, project["load_patterns"][0]["name"])
    path, out, results = run_model(project, folder, [case["id"]])
    disp = results[case["id"]].node_disp[master][-1]
    ux, uy, rz = float(disp[0]), float(disp[1]), float(disp[5])
    view = result_view(out, path, f"case:{case['id']}")
    base = _frame_forces(view, "C1")[0]
    shear_c1 = math.hypot(base[1], base[2])

    # By hand: lateral stiffness 3EI/h³ of each cantilever (both directions, square columns) and
    # the twist stiffness GJ/h of each column about its own axis.
    g = E_C / (2 * (1 + NU_C))
    sizes = [0.5, 0.4, 0.4, 0.4]
    ks = [3 * E_C * (b**4 / 12) / height**3 for b in sizes]
    kt = [g * _torsion_constant(b, b) / height for b in sizes]
    xs = [x for x, _, _ in corners]
    ys = [y for _, y, _ in corners]
    xr = sum(k * x for k, x in zip(ks, xs, strict=True)) / sum(ks)
    yr = sum(k * y for k, y in zip(ks, ys, strict=True)) / sum(ks)
    # The storey's stiffness about the centre (x, y relative to it): [ux, uy, θ].
    stiffness = np.zeros((3, 3))
    for k, x, y, t in zip(ks, xs, ys, kt, strict=True):
        dx, dy = x - centre[0], y - centre[1]
        stiffness += k * np.array([[1, 0, -dy], [0, 1, dx], [-dy, dx, dx * dx + dy * dy]])
        stiffness[2, 2] += t
    ref = np.linalg.solve(stiffness, [force, 0.0, 0.0])
    k_theta_cr = sum(
        k * ((x - xr) ** 2 + (y - yr) ** 2) for k, x, y in zip(ks, xs, ys, strict=True)
    ) + sum(kt)
    twist = force * (yr - centre[1]) / k_theta_cr
    u1 = ks[0] * math.hypot(
        ref[0] - ref[2] * (ys[0] - centre[1]), ref[1] + ref[2] * (xs[0] - centre[0])
    )
    reference = Reference(
        source="Rigid diaphragm storey by hand: centre of rigidity and torsion of a one-storey "
        "building (e.g. Paulay & Priestley, Seismic Design of Reinforced Concrete and Masonry "
        "Buildings, Sec 1.2.2(c); Chopra, Dynamics of Structures, unsymmetric-plan systems)",
        formula="k = 3EI/h³ (cantilever), kθ = GJ/h; x_r = Σk x/Σk, y_r = Σk y/Σk; "
        "θ = F (y_r - y_c) / (Σ k r² + Σ GJ/h) about the centre of rigidity; "
        "u = K⁻¹ F at the plan centre",
        steps=[
            "k = 3EI/h³: " + ", ".join(fmt(k) for k in ks) + " N/m (C1 500 × 500, C2-C4 400 × 400)",
            "GJ/h: " + ", ".join(fmt(t) for t in kt) + f" N·m (G = {fmt(g)} Pa, J by the "
            "Saint-Venant series)",
            (
                f"centre of rigidity x_r = {fmt(xr)} m, y_r = {fmt(yr)} m; force at y_c = 2.5 m, "
                f"eccentricity e = {fmt(centre[1] - yr)} m"
            ),
            f"Kθ about the CR = {fmt(k_theta_cr)} N·m, θ = F e / Kθ = {fmt(twist)} rad",
            (
                f"at the centre: ux = {fmt(ref[0] * 1e3)} mm, uy = {fmt(ref[1] * 1e3)} mm, "
                f"θ = {fmt(ref[2])} rad"
            ),
            f"shear in C1 = k₁ |u at C1| = {fmt(u1 / 1e3)} kN",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Twist about the centre of rigidity θ", "rad", twist, rz, FRAME),
            Quantity("ux at the plan centre", "mm", ref[0] * 1e3, ux * 1e3, FRAME),
            Quantity("uy at the plan centre", "mm", ref[1] * 1e3, uy * 1e3, FRAME),
            Quantity(
                "ux at the centre of rigidity, F / Σk",
                "mm",
                force / sum(ks) * 1e3,
                (ux - rz * (yr - centre[1])) * 1e3,
                FRAME,
            ),
            Quantity("Shear in the stiff column C1", "kN", u1 / 1e3, shear_c1 / 1e3, FRAME),
        ],
        notes=[
            (
                "The derived model of a special structure has no floor diaphragm: the case adds "
                "a master node at the plan centre with a rigid diaphragm constraint over the four "
                "column tops, removes the masses and loads the master node."
            )
        ],
    )


# ─────────────────────────────── 4. wall shell piers ───────────────────────────────


def wall_piers(folder: Path) -> Outcome:
    """A 4 m long, 200 mm thick wall from the base to 6 m (two storeys of 3 m) of 06 BIM,
    meshed in shells; 150 kN along X at its top (spread over the top nodes, WX) and 200 kN down
    at its top beside the self-weight (D): the piers' P, V and M against statics."""
    from saengine.design.wall_forces import wall_forces
    from saengine.fem.combinations import DesignCombination
    from saengine.library.bim import BuildingModel

    length, thick, storey, h_load, p_load = 4.0, 0.2, 3.0, 150e3, 200e3
    top_z = 2 * storey
    model = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
                {"id": "L2", "name": "Level 2", "elevation": 6000},
            ],
            "elements": [
                {
                    "id": "W1",
                    "type": "W",
                    "kind": "wall",
                    "start": [0, 0],
                    "end": [length * 1000, 0],
                    "bottom": 0,
                    "top": top_z * 1000,
                }
            ],
        }
    )
    wall_type = {
        "id": "W",
        "name": "Wall 200",
        "kind": "wall",
        "material": CONCRETE.id,
        "thickness": 200,
    }
    d = derive(
        model, objects(wall_type), MATERIALS, settings(meshSize=500), {"bim": "verification"}
    )
    project = d.project
    # A bare cantilever wall: no floor diaphragm ties its nodes (the master nodes held).
    used = {n for e in project["elements"] for n in e["nodes"]}
    masters = {c["retained_node"] for c in project["mp_constraints"]} - used
    project["mp_constraints"] = []
    for node in project["nodes"]:
        node["mass"] = [0.0] * 6
        if node["id"] in masters:
            node["restraint"] = [True] * 6
    top = [
        n for n in project["nodes"] if abs(n["coords"][2] - top_z) < 1e-6 and n["id"] not in masters
    ]
    ends = {min(n["coords"][0] for n in top), max(n["coords"][0] for n in top)}
    share = {n["id"]: 0.5 if n["coords"][0] in ends else 1.0 for n in top}
    total = sum(share.values())
    patterns = {p["name"]: p for p in project["load_patterns"]}
    patterns["WX"]["nodal_loads"] = [
        {"node_id": i, "forces": [h_load * s / total, 0, 0, 0, 0, 0]} for i, s in share.items()
    ]
    patterns["WX"]["element_loads"] = []
    patterns["D"]["nodal_loads"] += [
        {"node_id": i, "forces": [0, 0, -p_load * s / total, 0, 0, 0]} for i, s in share.items()
    ]
    ids = [_static_case(project, "D")["id"], _static_case(project, "WX")["id"]]
    _path, out, _ = run_model(project, folder, ids)
    found = wall_forces(
        project,
        model,
        out,
        [DesignCombination("D", {"D": 1.0}), DesignCombination("WX", {"WX": 1.0})],
    )
    piers = {p["storey"]: p for p in found["piers"] if p["wall"] == "W1"}
    lower, upper = piers["L1"]["cuts"]["bottom"], piers["L2"]["cuts"]["bottom"]
    unit = RHO_C * 9.80665 * thick * length  # N per metre of height
    row = 0.5  # m, the mesh size: the cut's own nodes carry half a row of shells above it
    weight = unit * top_z
    p_base = (p_load + unit * (top_z - row / 2)) / 1e3
    p_mid = (p_load + unit * (top_z - storey - row / 2)) / 1e3
    shells = sum(1 for e in project["elements"] if e["type"] == "Shell")
    reference = Reference(
        source="Statics of a cantilever wall: the free body above each cut, as ETABS forms pier "
        "forces; the self-weight lumped at the nodes, the load at a cut's own nodes belonging "
        "to the part below (saengine.design.wall_forces convention)",
        formula="P = P_top + ρ g t L (z_top - z_cut - Δ/2); V = H; M = H (z_top - z_cut)",
        steps=[
            (
                f"ρ g t L = {RHO_C:g} × 9.80665 × {thick:g} × {length:g} = {fmt(unit / 1e3)} kN/m; "
                f"whole wall {fmt(weight / 1e3)} kN; mesh row Δ = {row:g} m"
            ),
            (
                f"base (L1 pier bottom): P = {p_load / 1e3:g} + {fmt(unit / 1e3)} × "
                f"({top_z:g} - {row / 2:g}) = {fmt(p_base)} kN, V = {h_load / 1e3:g} kN, M = "
                f"{h_load / 1e3:g} × {top_z:g} = {fmt(h_load * top_z / 1e3)} kN·m"
            ),
            (
                f"level 1 (L2 pier bottom): P = {p_load / 1e3:g} + {fmt(unit / 1e3)} × "
                f"({storey:g} - {row / 2:g}) = {fmt(p_mid)} kN, V = {h_load / 1e3:g} kN, M = "
                f"{h_load / 1e3:g} × {storey:g} = {fmt(h_load * storey / 1e3)} kN·m"
            ),
        ],
    )
    tol = 0.001
    return Outcome(
        reference,
        [
            Quantity("Base pier P (D)", "kN", p_base, lower["D"]["P"], tol),
            Quantity("Base pier V2 (WX)", "kN", h_load / 1e3, lower["WX"]["V2"], tol),
            Quantity("Base pier M3 (WX)", "kN·m", h_load * top_z / 1e3, lower["WX"]["M3"], tol),
            Quantity("Level 1 pier P (D)", "kN", p_mid, upper["D"]["P"], tol),
            Quantity("Level 1 pier V2 (WX)", "kN", h_load / 1e3, upper["WX"]["V2"], tol),
            Quantity("Level 1 pier M3 (WX)", "kN·m", h_load * storey / 1e3, upper["WX"]["M3"], tol),
        ],
        notes=[
            (
                f"{shells} shells (500 mm mesh). The case removes the floor diaphragms and the "
                "masses (a bare cantilever wall), replaces the derived wind WX by the case's load "
                "and adds the top load to D, both spread over the top nodes (half at the ends). "
                "Pier forces from saengine.design.wall_forces (sums of the shells' nodal forces "
                "at each cut), so statics hold within the tolerance of 0.1 %."
            ),
            (
                "The base cut's P is the wall's whole weight less the half row lumped at the base "
                f"nodes ({fmt(unit * row / 2e3)} kN), which goes straight to the supports: the "
                "pier forces count a load at a cut's nodes in the part below. The design of the "
                "wall at its base takes this cut; the difference is that half row."
            ),
        ],
    )


# ─────────────────────────────── 9. semi-rigid diaphragm ───────────────────────────────


def semi_rigid(folder: Path) -> Outcome:
    """A 150 mm slab, 16 m long and 4 m deep in plan, of shells (the semi-rigid diaphragm),
    held in Y along its two short edges (the walls) and loaded in its plane by 50 kN/m along
    its long edge: it spans as a deep beam between the walls."""
    span, depth, thick, w, mesh = 16.0, 4.0, 0.15, 50e3, 250
    slab = {
        "id": "SL",
        "name": "Slab 150",
        "kind": "slab",
        "material": CONCRETE.id,
        "thickness": 150,
    }
    model = structure(
        areas=[
            {
                "id": "F1",
                "type": "SL",
                "outline": [
                    point(0, 0, 0),
                    point(span * 1000, 0, 0),
                    point(span * 1000, depth * 1000, 0),
                    point(0, depth * 1000, 0),
                ],
            }
        ]
    )
    d = derive(
        building(model), objects(slab), MATERIALS, settings(meshSize=mesh, diaphragm="flexible")
    )
    project = d.project
    project["mp_constraints"] = []
    for node in project["nodes"]:
        x, y, _ = node["coords"]
        at_wall = abs(x) < 1e-9 or abs(x - span) < 1e-9
        # Out of plane held (the slab's bending is not the subject); in plane: the walls hold
        # Y along the short edges, one corner holds X.
        node["restraint"] = [abs(x) < 1e-9 and abs(y) < 1e-9, at_wall, True, True, True, False]
        node["mass"] = [0.0] * 6
    edge = sorted(
        (n for n in project["nodes"] if abs(n["coords"][1] - depth) < 1e-9),
        key=lambda n: n["coords"][0],
    )
    xs = [n["coords"][0] for n in edge]
    loads = []
    for k, node in enumerate(edge):
        left = xs[k] - xs[k - 1] if k else 0.0
        right = xs[k + 1] - xs[k] if k + 1 < len(xs) else 0.0
        loads.append({"node_id": node["id"], "forces": [0, -w * (left + right) / 2, 0, 0, 0, 0]})
    only_pattern(project, nodal=loads)
    case = _static_case(project, project["load_patterns"][0]["name"])
    path, out, results = run_model(project, folder, [case["id"]])
    # The node nearest the middle of the axis (the mesh is not quite regular there).
    mid = min(
        project["nodes"],
        key=lambda n: math.hypot(n["coords"][0] - span / 2, n["coords"][1] - depth / 2),
    )["id"]
    deflection = -float(results[case["id"]].node_disp[mid][-1][1])
    # The in-plane moment at the column of shells left of midspan: Σ N11 (y - D/2) Δy.
    view = result_view(out, path, f"case:{case['id']}")
    coords = {n["id"]: np.array(n["coords"]) for n in project["nodes"]}
    column = []
    for shell in view["shells"]:
        centre = np.mean([coords[i] for i in shell["nodes"]], axis=0)
        if span / 2 - mesh / 1e3 < centre[0] < span / 2:
            ys = [coords[i][1] for i in shell["nodes"]]
            column.append((centre, max(ys) - min(ys), shell["forces"]))
    x_cut = float(np.mean([c[0] for c, _, _ in column]))
    moment = abs(sum(f[0] * (c[1] - depth / 2) * dy for c, dy, f in column))

    e, nu = E_C, NU_C
    inertia = thick * depth**3 / 12
    half, c = span / 2, depth / 2
    flexure = 5 * w * span**4 / (384 * e * inertia)
    correction = 12 / 5 * (c / half) ** 2 * (4 / 5 + nu / 2)
    v_ref = flexure * (1 + correction)
    m_ref = w / 2 * (span * x_cut - x_cut**2)
    rigid_share = 0.5
    reference = Reference(
        source="Plane stress elasticity: simply supported deep beam under a uniform load, "
        "Timoshenko & Goodier, Theory of Elasticity, Art. 22 (deflection of the axis including "
        "shear and the transverse stress); statics for the moment",
        formula="v = 5wL⁴/(384EI) [1 + (12/5)(c/l)² (4/5 + ν/2)], l = L/2, c = D/2, I = tD³/12; "
        "M(x) = w (L x - x²)/2",
        steps=[
            (
                f"L = {span:g} m, D = {depth:g} m, t = {thick:g} m, E = {fmt(e)} Pa, ν = {nu:g}, "
                f"w = {w / 1e3:g} kN/m"
            ),
            f"I = {fmt(inertia)} m⁴, bending part 5wL⁴/(384EI) = {fmt(flexure * 1e3)} mm",
            f"(12/5)(c/l)²(4/5 + ν/2) = {fmt(correction)}, v = {fmt(v_ref * 1e3)} mm",
            f"moment at the shells' centroids x = {fmt(x_cut)} m: M = {fmt(m_ref / 1e3)} kN·m",
            (
                f"each wall takes wL/2 = {fmt(rigid_share * w * span / 1e3)} kN, as a rigid "
                "diaphragm would give it here (symmetric)"
            ),
        ],
    )
    shells = sum(1 for e in project["elements"] if e["type"] == "Shell")
    return Outcome(
        reference,
        [
            Quantity("In-plane midspan deflection", "mm", v_ref * 1e3, deflection * 1e3, 0.03),
            Quantity("In-plane moment near midspan", "kN·m", m_ref / 1e3, moment / 1e3, 0.02),
        ],
        notes=[
            (
                f"{shells} shells ({mesh} mm mesh), slab drawn as an area of a special "
                "structure. The case holds the slab out of plane, holds Y along the two short "
                "edges (the walls) and X at one corner, and loads the long edge with the nodes' "
                "tributary lengths. Elasticity takes the end shear as parabolic stresses; the "
                "model holds the whole end edge, which stiffens the ends slightly. The moment is "
                "Σ N11 (y - D/2) Δy over the column of shells at the centroids next to midspan."
            )
        ],
    )


# ─────────────────────────────── 6. cantilever retaining wall ───────────────────────────────


def retaining_wall(_: Path) -> Outcome:
    """A cantilever retaining wall 4.5 m from the retained ground to the underside of its base,
    dry cohesionless backfill (γ = 18 kN/m³, φ' = 30°), level, no surcharge: Rankine active
    thrust, sliding, overturning, base pressures, and the stem's design at its base."""
    from types import SimpleNamespace

    from saengine.codes import context as code_context
    from saengine.library.substructure import RetainingWall
    from saengine.substructure import retaining_walls as rw
    from saengine.substructure.earth_pressure import Soil

    wall = RetainingWall.model_validate(
        {
            "id": "RW1",
            "path": [[0, 0], [10000, 0]],
            "topLevel": 0,
            "foundingLevel": -4500,
            "material": "C25",
            "stemTop": 400,
            "stemBottom": 400,
            "baseThickness": 500,
            "toe": 1000,
            "heel": 2000,
            "surcharge": 0,
            "seismic": False,
            "drained": True,
            "passive": False,
        }
    )
    soil = Soil([(0.0, 20.0, 18.0, 20.0, 30.0)], None)
    s = rw.section_of(wall, 0.0)
    ctx = SimpleNamespace(soil=SimpleNamespace(at=lambda *a: SimpleNamespace(qa=200.0, note="")))
    checks, detail, _ = rw.stability(ctx, wall, s, soil, 0.0, 0.0)
    by_name = {c["name"]: c for c in checks}
    base = detail["base"]
    # The stem at its base (factored by the pack's H factor) and its design.
    _ys, moment, shear, _ = rw.beam_actions(
        s.stem_height, rw._stem_load(soil, wall, s, "active"), [], True
    )
    factors = code_context.table("foundations").retainingWall
    h_factor, mu_base = float(factors.hFactor), float(factors.frictionCoefficient)
    ms, vs = abs(float(moment[0])), abs(float(shear[0]))
    fc, fy, cover = 25.0, 420.0, 50.0
    bars, stem = rw.design_strip(
        rw.Strip("Stem", h_factor * ms, ms, 400.0, cover, h_factor * vs, "base"),
        fc,
        fy,
        4700 * math.sqrt(fc),
        0.3,
    )
    flexure = next(c for c in stem if c["name"] == "Stem: flexure")

    # By hand, per metre run.
    gamma, gamma_c, ka = (
        18.0,
        24.0,
        (1 - math.sin(math.radians(30))) / (1 + math.sin(math.radians(30))),
    )
    big_h, hs, toe, stem_t, heel, tb = 4.5, 4.0, 1.0, 0.4, 2.0, 0.5
    width = toe + stem_t + heel
    thrust = 0.5 * ka * gamma * big_h**2
    weights = [
        ("stem", gamma_c * stem_t * hs, toe + stem_t / 2),
        ("base", gamma_c * width * tb, width / 2),
        ("soil over the heel", gamma * hs * heel, toe + stem_t + heel / 2),
    ]
    sum_v = sum(w for _, w, _ in weights)
    resisting = sum(w * x for _, w, x in weights)
    overturning = thrust * big_h / 3
    fs_over = resisting / overturning
    fs_slide = mu_base * sum_v / thrust
    x_r = (resisting - overturning) / sum_v
    e = width / 2 - x_r
    q_toe, q_heel = sum_v / width * (1 + 6 * e / width), sum_v / width * (1 - 6 * e / width)
    ms_ref = ka * gamma * hs**3 / 6
    vs_ref = ka * gamma * hs**2 / 2
    area = (
        bars["area"] if "area" in bars else math.pi * bars["dia"] ** 2 / 4 * 1000 / bars["spacing"]
    )
    d = 400 - cover - bars["dia"] / 2
    a = area * fy / (0.85 * fc * 1000)
    phi_mn = 0.9 * area * fy * (d - a / 2) / 1e6
    reference = Reference(
        source="Rankine active pressure and the stability of a cantilever retaining wall, the "
        "textbook procedure (Das, Principles of Foundation Engineering, chapter on retaining "
        "walls; Bowles, Foundation Analysis and Design), worked here for this wall; friction "
        "factor and the 1.6 H factor from the code pack (BNBC 2020 Part 6 Sec 3.14, 2.7.3.1)",
        formula="Ka = (1 - sin φ)/(1 + sin φ); Pa = ½ Ka γ H² at H/3; FS_ot = ΣMr / (Pa H/3); "
        "FS_sl = μ ΣV / Pa; q = ΣV/B (1 ± 6e/B); stem: Ms = Ka γ h³/6, Vs = Ka γ h²/2, "
        "Mu = 1.6 Ms, φMn = 0.9 As fy (d - a/2)",
        steps=[
            (
                f"Ka = {fmt(ka)}, H = {big_h:g} m (retained ground to the underside of the base), "
                f"Pa = ½ × {fmt(ka)} × {gamma:g} × {big_h:g}² = {fmt(thrust)} kN/m at {big_h / 3:g} m"
            ),
            "weights: "
            + "; ".join(f"{n} {fmt(w)} kN/m at x = {fmt(x)} m" for n, w, x in weights)
            + f"; ΣV = {fmt(sum_v)} kN/m (γc = {gamma_c:g} kN/m³)",
            (
                f"ΣMr = {fmt(resisting)} kN·m/m, Mo = {fmt(overturning)} kN·m/m, FS_ot = "
                f"{fmt(fs_over)}; FS_sl = {mu_base:g} × {fmt(sum_v)} / {fmt(thrust)} = {fmt(fs_slide)}"
            ),
            (
                f"x = (ΣMr - Mo)/ΣV = {fmt(x_r)} m, e = {fmt(e)} m, q_toe = {fmt(q_toe)} kPa, "
                f"q_heel = {fmt(q_heel)} kPa"
            ),
            (
                f"stem h = {hs:g} m: Ms = {fmt(ms_ref)} kN·m/m, Vs = {fmt(vs_ref)} kN/m, Mu = "
                f"{h_factor:g} Ms = {fmt(h_factor * ms_ref)} kN·m/m"
            ),
            (
                f"bars proposed Ø{bars['dia']:g} at {bars['spacing']:g}: As = {fmt(area)} mm²/m, "
                f"d = {fmt(d)} mm, a = {fmt(a)} mm, φMn = {fmt(phi_mn)} kN·m/m ≥ Mu"
            ),
        ],
    )
    tol = 0.005
    return Outcome(
        reference,
        [
            Quantity("Active thrust Pa", "kN/m", thrust, detail["pressure"]["thrust"], tol),
            Quantity(
                "FS against overturning", "-", fs_over, by_name["Overturning"]["capacity"], tol
            ),
            Quantity("FS against sliding", "-", fs_slide, by_name["Sliding"]["capacity"], tol),
            Quantity("Base pressure at the toe", "kPa", q_toe, base["toe"], tol),
            Quantity("Base pressure at the heel", "kPa", q_heel, base["heel"], tol),
            Quantity("Stem moment at the base, service", "kN·m/m", ms_ref, ms, tol),
            Quantity("Stem shear at the base, service", "kN/m", vs_ref, vs, tol),
            Quantity("Stem design moment Mu", "kN·m/m", h_factor * ms_ref, flexure["demand"], tol),
            Quantity("Stem φMn of the bars proposed", "kN·m/m", phi_mn, flexure["capacity"], tol),
        ],
        notes=[
            (
                "saengine.substructure.retaining_walls: stability() with a stub bearing lookup "
                "(qa is not compared), beam_actions() of the stem's pressure and design_strip(). "
                "The wall is drained, without surcharge, passive resistance or seismic case, and "
                f"the stem is prismatic. The design proposed Ø{bars['dia']:g} at "
                f"{bars['spacing']:g} mm; checks: "
                + ", ".join(
                    f"{c['name'].split(': ')[-1]} {'ok' if c['ok'] else 'NOT ok'}" for c in stem
                )
            )
        ],
    )


# ─────────────────────────────── 7. e2k round trip ───────────────────────────────


def _portal_response(bim: Any, objs: Any, mats: Any, folder: Path) -> tuple[float, float, int]:
    """Derive and run the one-bay frame ``bim`` with 10 kN in X at the top of the column on
    A1 (0, 0): (mean sway of the beam's joints [m], mean base moment of the two columns on A1
    and B1 [N·m], number of frame elements)."""
    d = derive(bim, objs, mats, settings(endOffsets=False, diaphragm="flexible", meshSize=10000))
    project = d.project
    for node in project["nodes"]:
        node["mass"] = [0.0] * 6
    left, right = node_at(project, (0, 0, 3.2)), node_at(project, (6, 0, 3.2))
    only_pattern(project, nodal=[{"node_id": left, "forces": [10e3, 0, 0, 0, 0, 0]}])
    case = _static_case(project, project["load_patterns"][0]["name"])
    path, out, results = run_model(project, folder, [case["id"]])
    disp = results[case["id"]].node_disp
    sway = (disp[left][-1][0] + disp[right][-1][0]) / 2
    bases = {node_at(project, (0, 0, 0)), node_at(project, (6, 0, 0))}
    frames = {e["id"]: e for e in project["elements"] if e["type"] != "Shell"}
    view = result_view(out, path, f"case:{case['id']}")
    moments = [
        max(abs(e["forces"][0][4]), abs(e["forces"][0][5]))
        for e in view["elements"]
        if e["id"] in frames and frames[e["id"]]["nodes"][0] in bases
    ]
    assert len(moments) == 2, "one column on each of A1 and B1"
    return float(sway), float(sum(moments) / 2), len(frames)


def e2k_round_trip(folder: Path) -> Outcome:
    """The one-bay frame of A3 drawn in the floor plan (columns on A1 and B1, beam B11; the
    columns on A2 and B2 stand free), exported to e2k (saengine.exporters.etabs) and read back
    (saengine.importers.etabs): both run under the same lateral load."""
    from saengine.exporters.etabs import write_e2k
    from saengine.importers.etabs import read_e2k
    from saengine.importers.project import section_lookup_noted

    plan = parity._plan(stories=1, slabs=False, only="B11")
    bim = generate(plan, "v")
    objs = objects(parity.COLUMN, parity.BEAM)
    s = settings(endOffsets=False, diaphragm="flexible", meshSize=10000)
    e2k = folder / "frame.e2k"
    write_e2k(bim, objs, MATERIALS, s, name="frame").write(e2k)
    imported = read_e2k(e2k, section_lookup=section_lookup_noted)
    sway0, moment0, count0 = _portal_response(bim, objs, MATERIALS, folder / "original")
    sway1, moment1, count1 = _portal_response(
        imported.bim, imported.objects, imported.materials, folder / "imported"
    )

    h, span, p = 3.2, 6.0, 10e3
    i_col, i_beam = 0.4**4 / 12, 0.3 * 0.5**3 / 12
    kc, kb = E_C * i_col / h, E_C * i_beam / span
    matrix = np.array([[4 * kc + 6 * kb, -6 * kc / h], [-6 * kc / h, 12 * kc / h**2]])
    theta, delta = np.linalg.solve(matrix, [0.0, p / 2])
    m_base = abs(2 * kc * (theta - 3 * delta / h))
    reference = Reference(
        source="Slope-deflection method (as case A3), and the original model's own results: "
        "the model read back from its e2k must give the same answers",
        formula="(4kc + 6kb) θ - 6kc Δ/h = 0; -6kc θ/h + 12kc Δ/h² = P/2; M_base = 2kc (θ - 3Δ/h)",
        steps=[
            (
                f"kc = {fmt(kc)} N·m, kb = {fmt(kb)} N·m; θ = {fmt(theta)} rad, Δ = "
                f"{fmt(delta * 1e3)} mm, M_base = {fmt(m_base / 1e3)} kN·m"
            ),
            (
                f"original model: sway {fmt(sway0 * 1e3)} mm, base moment {fmt(moment0 / 1e3)} kN·m, "
                f"{count0} frame elements"
            ),
            (
                f"read back from e2k: sway {fmt(sway1 * 1e3)} mm, base moment {fmt(moment1 / 1e3)} "
                f"kN·m, {count1} frame elements"
            ),
        ],
    )
    same = 1e-6
    return Outcome(
        reference,
        [
            Quantity("Sway, original model", "mm", delta * 1e3, sway0 * 1e3, FRAME),
            Quantity("Base moment, original model", "kN·m", m_base / 1e3, moment0 / 1e3, FRAME),
            Quantity(
                "Sway after the e2k round trip / original", "mm", sway0 * 1e3, sway1 * 1e3, same
            ),
            Quantity(
                "Base moment after the round trip / original",
                "kN·m",
                moment0 / 1e3,
                moment1 / 1e3,
                same,
            ),
            Quantity("Frame elements after the round trip / original", "-", count0, count1, same),
        ],
        notes=[
            (
                "Identical results: the round-trip quantities compare the re-imported model with "
                "the original within 0.0001 %. Both derive with the same analysis settings (no "
                "end offsets, flexible diaphragm); the case replaces the dead load by the "
                "lateral load and removes the masses. The frame is the A3 frame, so the "
                "original matches the hand solution as A3 does (axial deformations included)."
            )
        ],
    )


# ─────────────────────────── 10. one-bay BOQ and a beam's bar schedule ───────────────────────────

BOQ_OBJECTS = [
    {
        "id": "COL",
        "name": "Column 400x400",
        "kind": "column",
        "material": CONCRETE.id,
        "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
        "reinforcement": {
            "material": "B420DWR",
            "cover": 40,
            "longitudinal": [{"position": "perimeter", "count": 4, "dia": 16}],
            "transverse": {"type": "tie", "dia": 10, "spacing": 150},
        },
    },
    {
        "id": "BM",
        "name": "Beam 300x500",
        "kind": "beam",
        "material": CONCRETE.id,
        "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
        "reinforcement": {
            "material": "B420DWR",
            "cover": 25,
            "longitudinal": [
                {"position": "bottom", "count": 3, "dia": 20},
                {"position": "top", "count": 2, "dia": 16},
            ],
            "transverse": {"type": "stirrup", "dia": 10, "spacing": 150},
        },
    },
    {
        "id": "SL",
        "name": "Slab 150",
        "kind": "slab",
        "material": CONCRETE.id,
        "thickness": 150,
        "reinforcement": {
            "material": "B420DWR",
            "cover": 20,
            "bottomX": {"dia": 10, "spacing": 150},
            "bottomY": {"dia": 10, "spacing": 200},
        },
    },
]


def _up(value: float, step: float) -> float:
    return math.ceil(value / step - 1e-9) * step


def boq_and_schedule(_: Path) -> Outcome:
    """One bay 6 m (A-B) × 5 m (1-2), one storey of 3.2 m: four 400 × 400 columns, four
    300 × 500 beams and a 150 mm slab, all reinforced in the object library. The bill of
    quantities by the estimating rules, and the detailing and bar schedule of beam B1 (A1-B1)."""

    from saengine.boq.quantities import BoqSource, bill_of_quantities
    from saengine.drawings import bbs, detailing
    from saengine.library.bim import source_stamp

    plan = parity._plan(stories=1, slabs=True)
    bim = generate(plan, "v")
    objs = objects(*BOQ_OBJECTS)
    texts = {
        "bim": bim.model_dump_json(by_alias=True, exclude_none=True),
        "objects": objs.model_dump_json(by_alias=True, exclude_none=True),
        "materials": MATERIALS.model_dump_json(by_alias=True, exclude_none=True),
    }
    boq = bill_of_quantities(
        bim, objs, MATERIALS, BoqSource(**{k: source_stamp(v) for k, v in texts.items()})
    )

    def steel(dia: float) -> float:
        return sum(
            i.quantity for i in boq.items if i.group == "reinforcement" and i.diameter == dia
        )

    model = detailing.detailing_model(texts=texts)
    beam = next(e for e in model["elements"] if e.get("member") == "B11")
    schedule = bbs.bar_schedule({"elements": [beam]})
    stirrup = next(r for r in schedule.rows if r.shape == "51")
    top = next(r for r in schedule.rows if r.dia == 16)
    bottom = [r for r in schedule.rows if r.dia == 20]
    straight = next(r for r in bottom if "cranked" not in r.remarks)
    cranked = next(r for r in bottom if "cranked" in r.remarks)
    tails = [r.dims["A"] - r.radius - r.dia for r in bottom]

    # ── the hand take-off (the estimating rules: bars over the members' centrelines, links on
    # the centreline of the link with two 10 d hooks, d²/162 kg/m, no laps under 12 m) ──
    a_slab = 6 * 5
    conc_col = 4 * 0.4 * 0.4 * 3.2 - 4 * 0.2 * 0.2 * 0.15  # less the slab over a quarter
    clear = [5.6, 4.6, 5.6, 4.6]  # m, between the column faces
    conc_beam = sum(clear) * 0.3 * 0.5 - sum(clear) * 0.15 * 0.15  # less the slab's half
    conc_slab = a_slab * 0.15
    form_col = 4 * 1.6 * 3.2 - 4 * 0.4 * 0.15
    form_beam = sum(clear) * (0.3 + 2 * 0.5 - 0.15)
    form_slab = a_slab - sum(clear) * 0.15 - 4 * 0.2 * 0.2
    centre = 6 + 5 + 6 + 5  # m of beam centreline
    ties = 4 * (math.floor(3.2 / 0.15) + 1) * (4 * (0.4 - 2 * 0.04 - 0.01) + 2 * 10 * 0.01)
    stirrups_m = sum((math.floor(c / 0.15) + 1) for c in clear) * (
        2 * (0.3 - 2 * 0.025 - 0.01 + 0.5 - 2 * 0.025 - 0.01) + 2 * 10 * 0.01
    )
    mesh = a_slab / 0.15 + a_slab / 0.2
    kg = {10: 100 / 162, 16: 256 / 162, 20: 400 / 162}
    d10 = (ties + stirrups_m + mesh) * kg[10]
    d16 = (4 * 4 * 3.2 + 2 * centre) * kg[16]
    d20 = 3 * centre * kg[20]

    # ── the hand detailing of B1 (BNBC 2020 8.1.2: bends 6 d, links 4 d, a 90° hook 12 d, a
    # seismic link hook 135° + max(6 d, 75); BS 8666:2005 Table 2 radii and end projections;
    # shape 21: A + B + C - r - 2d, shape 51: 2(A + B + C) - 2.5 r - 5 d, up to 25 mm) ──
    r16, r20, r10 = max(32, 3 * 16), max(70, 3 * 20), max(20, 2 * 10)  # mm
    n_stirrups = math.ceil((5600 - 2 * 50) / 150 - 1e-9) + 1  # first link 50 mm from each face
    sa, sb = 300 - 2 * 25, 500 - 2 * 25  # outside dimensions of the link
    sc = max(_up(max(6 * 10, 75) + r10 + 10, 5), 130)  # hook: ext + r + d, at least P = 130
    stirrup_len = _up(2 * (sa + sb + sc) - 2.5 * r10 - 5 * 10, 25)
    b_len = 6000 + 2 * (200 - 40 - 10)  # to the far column faces' bars: cover 40 + tie 10
    # The corner bars of the beam are cranked 6 mm at 1 in 6 at each column to pass inside the
    # column's bars (the detailing's practice): one ramp at each end, √(6² + 1) - 6 per unit
    # of offset longer than straight.
    crank = 2 * 6 * (math.sqrt(37) - 6)
    top_leg = 12 * 16 + r16 + 16
    top_len = _up(top_leg + b_len + top_leg - r16 - 2 * 16 + crank, 25)
    bottom_leg = 12 * 20 + r20 + 20
    bottom_plain = bottom_leg + b_len + bottom_leg - r20 - 2 * 20
    bottom_len = _up(bottom_plain, 25)
    bottom_cranked = _up(bottom_plain + crank, 25)
    mass_b1 = (
        n_stirrups * stirrup_len * kg[10]
        + 2 * top_len * kg[16]
        + (bottom_len + 2 * bottom_cranked) * kg[20]
    ) / 1e3
    reference = Reference(
        source="Hand take-off by the estimating rules (concrete net of the overlaps, formwork "
        "of the faces against the concrete, bars over the centrelines, d²/162 kg/m) and hand "
        "detailing of the beam: BNBC 2020 Part 6 Sec 8.1.2 (bend diameters, standard and "
        "seismic hooks) and BS 8666:2005 (Table 2 minimum radii and end projections, shape "
        "codes 21 and 51, lengths rounded up to 25 mm)",
        formula="concrete: columns 4 × 0.4² × 3.2 - slab overlaps; beams Σ clear × 0.3 × 0.5 - "
        "the slab's half; slab 6 × 5 × 0.15. Links: n = ⌈(ln - 100)/s⌉ + 1; L51 = 2(A+B+C) - "
        "2.5r - 5d; U bars L21 = A + B + C - r - 2d with A = C = 12d + r + d",
        steps=[
            (
                f"concrete: columns {fmt(conc_col)} + beams {fmt(conc_beam)} + slab {fmt(conc_slab)}"
                f" = {fmt(conc_col + conc_beam + conc_slab)} m³"
            ),
            (
                f"formwork: columns {fmt(form_col)} + beams {fmt(form_beam)} + slab soffit "
                f"{fmt(form_slab)} = {fmt(form_col + form_beam + form_slab)} m²"
            ),
            (
                f"Ø10: ties {fmt(ties)} m + stirrups {fmt(stirrups_m)} m + slab mesh {fmt(mesh)} m "
                f"= {fmt(d10)} kg; Ø16: {fmt(d16)} kg; Ø20: {fmt(d20)} kg"
            ),
            (
                f"B1 links Ø10: {n_stirrups} no., A = {sa}, B = {sb}, C = {fmt(sc)}, r = {r10}: "
                f"{fmt(stirrup_len)} mm"
            ),
            (
                f"B1 top 2Ø16 (cranked, + {fmt(crank, 3)} mm): B = {b_len}, A = C = 12 × 16 + "
                f"{r16} + 16 = {top_leg}: {fmt(top_len)} mm"
            ),
            (
                f"B1 bottom 3Ø20: r = max(BS 8666 70, 6d/2 = 60) = {r20}, A = C = 12 × 20 + {r20} "
                f"+ 20 = {bottom_leg}: middle bar {fmt(bottom_len)} mm, the two corner bars "
                f"cranked {fmt(bottom_cranked)} mm; the hook's tail A - r - d = 12d = 240 mm"
            ),
            f"B1 bars: {fmt(mass_b1)} kg",
        ],
    )
    tight, exact = 0.001, 1e-6
    return Outcome(
        reference,
        [
            Quantity(
                "Concrete, the bay",
                "m³",
                conc_col + conc_beam + conc_slab,
                boq.total("concrete"),
                tight,
            ),
            Quantity(
                "Formwork, the bay",
                "m²",
                form_col + form_beam + form_slab,
                boq.total("formwork"),
                tight,
            ),
            Quantity("Reinforcement Ø10", "kg", d10, steel(10), tight),
            Quantity("Reinforcement Ø16", "kg", d16, steel(16), tight),
            Quantity("Reinforcement Ø20", "kg", d20, steel(20), tight),
            Quantity("B1 links, number", "-", n_stirrups, stirrup.total_count, exact),
            Quantity("B1 link cutting length", "mm", stirrup_len, stirrup.cutting_length, exact),
            Quantity("B1 top bar cutting length", "mm", top_len, top.cutting_length, exact),
            Quantity(
                "B1 bottom bar cutting length, straight",
                "mm",
                bottom_len,
                straight.cutting_length,
                exact,
            ),
            Quantity(
                "B1 bottom bar cutting length, cranked",
                "mm",
                bottom_cranked,
                cranked.cutting_length,
                exact,
            ),
            Quantity("B1 bottom bar hook tail A - r - d (12 d)", "mm", 12 * 20, min(tails), exact),
            Quantity("B1 bars, mass", "kg", mass_b1, schedule.total, tight),
        ],
        notes=[
            (
                "saengine.boq.quantities.bill_of_quantities (the estimating rules) and saengine."
                "drawings.detailing.detailing_model with bbs.bar_schedule for beam B11 (A1-B1). "
                "Fixed (#386): the detailing sized the 90° hooks of Ø20 bars with the code's 6d "
                "bend (r = 60 mm, A = 320 mm) while the schedule bends them on BS 8666's 70 mm, "
                "so the bent tail was 230 mm, short of 12 d = 240 mm. The hooks now take the "
                "schedule's bend (A = 330 mm)."
            )
        ],
    )


# ─────────────────────────────── 8. fixed beam, support settlement ───────────────────────────────


def settlement(folder: Path) -> Outcome:
    """Beam B11 of a one-bay floor plan between columns C1 and C2; the base of C2 settles by
    10 mm in the case ST (Project Settings → Analysis model → Support settlement). The beam's
    joints are held against rotation and horizontal movement, so the beam is fixed-ended and
    the settlement reaches it through the axial shortening of the columns."""
    delta_mm = 10.0
    plan = parity._plan(stories=1, slabs=False, only="B11")
    d = derive(
        generate(plan, "v"),
        objects(parity.COLUMN, parity.BEAM),
        MATERIALS,
        settings(
            endOffsets=False,
            diaphragm="flexible",
            meshSize=10000,
            settlement=Settlement(
                enabled=True, supports=[SettlementSupport(column="C2", value=delta_mm)]
            ),
        ),
    )
    project = d.project
    st = next(a for a in project["analyses"] if a["name"].startswith("ST"))
    beam = [e for e in project["elements"] if str(e.get("name", "")).startswith("B11")]
    joints = {n for e in beam for n in e["nodes"][:2]}
    tops = [
        n["id"] for n in project["nodes"] if n["id"] in joints and abs(n["coords"][2] - 3.2) < 1e-6
    ]
    assert len(tops) == 2, "the beam spans between the two column tops"
    for node in project["nodes"]:
        if node["id"] in tops:
            node["restraint"] = [True, True, False, True, True, True]
    project["mp_constraints"] = []
    path, out, _ = run_model(project, folder, [st["id"]])
    view = result_view(out, path, f"case:{st['id']}")
    forces = _frame_forces(view, "B11")
    moment = max(max(abs(f[4]), abs(f[5])) for f in (forces[0], forces[-1]))
    shear = max(max(abs(f[1]), abs(f[2])) for f in (forces[0], forces[-1]))

    length, height = 6.0, 3.2
    i_b = 0.3 * 0.5**3 / 12
    ea_c = E_C * 0.16
    delta = delta_mm / 1e3
    # The two columns shorten (C1) and lengthen (C2) under the beam's end shears V, so the beam
    # sees Δb = Δ - 2 V h / (E A_c), with V = 12 E I Δb / L³.
    flex = 24 * E_C * i_b * height / (length**3 * ea_c)
    delta_b = delta / (1 + flex)
    m_ref = 6 * E_C * i_b * delta_b / length**2
    v_ref = 12 * E_C * i_b * delta_b / length**3
    reference = Reference(
        source="Fixed-ended beam with a support settlement (standard fixed-end moments, e.g. "
        "Ghali, Neville & Brown, Structural Analysis, table of end forces due to end "
        "displacements)",
        formula="M = 6 E I Δb / L², V = 12 E I Δb / L³; Δb = Δ / (1 + 24 E I h / (L³ E A_c)) "
        "(the columns' axial deformation)",
        steps=[
            f"E = {fmt(E_C)} Pa, I = 0.3 × 0.5³/12 = {fmt(i_b)} m⁴, L = {length:g} m",
            (
                f"Δ = {delta_mm:g} mm at the base of C2; columns 400 × 400, h = {height:g} m, "
                f"E A_c = {fmt(ea_c)} N"
            ),
            f"24 E I h / (L³ E A_c) = {fmt(flex)}, Δb = {fmt(delta_b * 1e3)} mm",
            f"M = 6 E I Δb / L² = {fmt(m_ref / 1e3)} kN·m at each end",
            f"V = 12 E I Δb / L³ = {fmt(v_ref / 1e3)} kN",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("End moment 6EIΔ/L²", "kN·m", m_ref / 1e3, moment / 1e3, FRAME),
            Quantity("Shear 12EIΔ/L³", "kN", v_ref / 1e3, shear / 1e3, FRAME),
        ],
        notes=[
            (
                "The settlement case ST is formed by SAEngine from the settings (saengine.fem."
                "settlement). The case then holds the beam's two joints against rotation and "
                "horizontal movement (free vertically), so that the beam is fixed-ended. The "
                "columns' axial deformation, which reduces the beam's relative settlement by "
                f"{fmt(100 * (1 - delta_b / delta), 3)} %, is in the reference."
            )
        ],
    )


# ─────────────────────────── 5. strong column / weak beam, capacity shear ───────────────────────────

FC, FY, ES = 28.0, 420.0, 200000.0  # MPa
BAR20 = math.pi * 20**2 / 4  # mm²


def _strain_compatibility(
    width: float, depth: float, layers: list[tuple[float, float]], fy: float, axial: float
) -> float:
    """Nominal moment [N·mm] about the mid-depth of a rectangular section with bar ``layers``
    (depth from the compression face [mm], area [mm²]) at the axial force ``axial`` [N,
    compression positive]: ACI rectangular stress block (0.85 f'c over β1 c, εcu = 0.003),
    elastic-perfectly plastic bars, the concrete displaced by the bars in the block deducted.
    The neutral axis depth c by bisection on the force balance."""
    beta1 = 0.85 if FC <= 28 else max(0.65, 0.85 - 0.05 * (FC - 28) / 7)

    def forces(c: float) -> tuple[float, float]:
        a = min(beta1 * c, depth)
        n = 0.85 * FC * width * a
        m = n * (depth / 2 - a / 2)
        for y, area in layers:
            stress = max(-fy, min(fy, ES * 0.003 * (c - y) / c))
            if y < a:
                stress -= 0.85 * FC  # the concrete the bar displaces
            n += stress * area
            m += stress * area * (depth / 2 - y)
        return n, m

    low, high = 1.0, 10 * depth
    for _ in range(200):
        c = (low + high) / 2
        if forces(c)[0] > axial:
            high = c
        else:
            low = c
    return forces((low + high) / 2)[1]


def strong_column(_: Path) -> Outcome:
    from saengine.codes import context as code_context
    from saengine.design import ductile_joints as dj
    from saengine.verification.cases.seismic_detailing import _section

    column = _section(500.0, 500.0, [{"position": "perimeter", "count": 12, "dia": 20}], 10.0)
    beam = _section(
        400.0,
        500.0,
        [{"position": "top", "count": 4, "dia": 20}, {"position": "bottom", "count": 3, "dia": 20}],
        10.0,
    )
    joint = dj.FrameJoint(
        "J1",
        (0.0, 0.0),
        3000.0,
        "C1",
        "C2",
        [
            dj.JointBeam("B1", "B400", (1.0, 0.0), 4000.0),
            dj.JointBeam("B2", "B400", (-1.0, 0.0), 4000.0),
        ],
        height_below=3000.0,
        height_above=3000.0,
    )
    p_below, p_above = 1.5e6, 0.8e6  # N, the factored compression (one value each)
    below = dj.JointColumn(column, 0.0, p_below, p_below, 40.0, 10.0)
    above = dj.JointColumn(column, 0.0, p_above, p_above, 40.0, 10.0)
    rows, _ = dj.strong_column_checks(joint, {"B400": beam}, below, above, column.profile)
    scwb = next(r for r in rows if r["name"].startswith("Strong column / weak beam, J1 x"))
    clear_span, gravity_shear = 3500.0, 60e3  # mm, N
    shear_rows = dj.beam_capacity_shear(
        beam, clear_span, gravity_shear, stirrups=dj.Stirrups(10.0, 2, 100.0)
    )
    ve = next(r for r in shear_rows if r["name"].startswith("Capacity shear Ve"))

    joints = code_context.table("detailing").joints
    ratio, probable = float(joints["strongColumnRatio"]), float(joints["probableStress"])
    # Beam 400 × 500: bars at 40 + 10 + 10 = 60 mm from each face.
    top, bottom = 4 * BAR20, 3 * BAR20
    hog = [(60.0, bottom), (440.0, top)]  # top bars in tension: the bottom face in compression
    sag = [(60.0, top), (440.0, bottom)]
    mn_hog = _strain_compatibility(400, 500, hog, FY, 0.0)
    mn_sag = _strain_compatibility(400, 500, sag, FY, 0.0)
    mpr_hog = _strain_compatibility(400, 500, hog, probable * FY, 0.0)
    mpr_sag = _strain_compatibility(400, 500, sag, probable * FY, 0.0)
    # Column 500 × 500, 12 Ø20 on the perimeter: four layers 60, 186.7, 313.3, 440 mm deep.
    col_layers = [(60.0, 4 * BAR20), (186.67, 2 * BAR20), (313.33, 2 * BAR20), (440.0, 4 * BAR20)]
    mnc_below = _strain_compatibility(500, 500, col_layers, FY, p_below)
    mnc_above = _strain_compatibility(500, 500, col_layers, FY, p_above)
    sum_mnc = mnc_below + mnc_above
    sum_mnb = mn_hog + mn_sag
    ve_ref = (mpr_hog + mpr_sag) / clear_span + gravity_shear
    reference = Reference(
        source="BNBC 2020 Part 6 Sec 8.3.5.2 (ΣMnc ≥ 1.2 ΣMnb) and Sec 8.3.8.1(a) (Ve = (Mpr⁻ + "
        "Mpr⁺)/ln + Vg, Mpr at 1.25 fy, φ = 1), the ratio and the probable stress from the "
        "active code pack (detailing.joints); moments by strain compatibility with the ACI "
        "rectangular stress block (ACI 318-19 22.2), written out here",
        formula="Mn: Σ F = P with C = 0.85 f'c b β1 c, fs = Es 0.003 (c - y)/c ≤ fy; "
        "ΣMnb = Mn⁻ + Mn⁺ (one beam hogging, the other sagging); ΣMnc = Mnc(P below) + "
        "Mnc(P above)",
        steps=[
            f"Code pack: strong column ratio {ratio:g}, probable stress {probable:g} fy",
            (
                f"Beam 400 × 500, 4 Ø20 top, 3 Ø20 bottom, d = 440 mm, d' = 60 mm, f'c = {FC:g}, "
                f"fy = {FY:g} MPa"
            ),
            (
                f"Mn⁻ = {fmt(mn_hog / 1e6)} kN·m, Mn⁺ = {fmt(mn_sag / 1e6)} kN·m; ΣMnb = "
                f"{fmt(sum_mnb / 1e6)} kN·m, {ratio:g} ΣMnb = {fmt(ratio * sum_mnb / 1e6)} kN·m"
            ),
            (
                f"Column 500 × 500, 12 Ø20: Mnc at P = {p_below / 1e3:g} kN = "
                f"{fmt(mnc_below / 1e6)} kN·m (below), at P = {p_above / 1e3:g} kN = "
                f"{fmt(mnc_above / 1e6)} kN·m (above); ΣMnc = {fmt(sum_mnc / 1e6)} kN·m"
            ),
            f"Mpr⁻ = {fmt(mpr_hog / 1e6)} kN·m, Mpr⁺ = {fmt(mpr_sag / 1e6)} kN·m (fy × {probable:g})",
            (
                f"Ve = ({fmt(mpr_hog / 1e6)} + {fmt(mpr_sag / 1e6)}) kN·m / {clear_span / 1e3:g} m + "
                f"{gravity_shear / 1e3:g} kN = {fmt(ve_ref / 1e3)} kN"
            ),
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("1.2 ΣMnb (beams)", "kN·m", ratio * sum_mnb / 1e6, scwb["demand"], 0.005),
            Quantity("ΣMnc (columns)", "kN·m", sum_mnc / 1e6, scwb["capacity"], 0.005),
            Quantity(
                "Ratio ΣMnc / ΣMnb",
                "-",
                sum_mnc / sum_mnb,
                ratio * scwb["capacity"] / scwb["demand"],
                0.005,
            ),
            Quantity("Beam capacity shear Ve", "kN", ve_ref / 1e3, ve["demand"], 0.005),
        ],
    )


CASES = [
    Case(
        "AG1",
        "P-Delta: cantilever column under axial and lateral load",
        "analysis",
        "Second order P-Delta analysis (Project Settings → Analysis model → Second order): the "
        "tip sway, its amplification and the base moment against the closed-form beam-column.",
        "Column 400 × 400 mm, C24.1, 4 m, fixed base, drawn as 20 members; P = 2500 kN at the "
        "tip as the P-Delta gravity preload and H = 20 kN at the tip in the dead load case "
        "(both set in the derived project).",
        p_delta,
    ),
    Case(
        "AG2",
        "Three-storey shear building: periods, modal mass and CQC response spectrum",
        "analysis",
        "Modal analysis and the X response spectrum case (CQC) of a uniform three-storey shear "
        "building: periods, effective modal mass ratios, roof displacement and base shear.",
        "One 400 × 400 column, C24.1, three storeys of 3.2 m, the floors held against rotation "
        "(shear building, k = 12EI/h³), 50 t per floor in X; the case's own spectrum Sa = 4.0 "
        "m/s² to 0.5 s, then 2.0 at 1 s, 1.0 at 2 s, 0.5 at 4 s (linear); 5 % damping.",
        shear_building,
    ),
    Case(
        "AG3",
        "Rigid diaphragm: eccentric stiffness, centre of rigidity and twist",
        "analysis",
        "A one-storey rigid diaphragm over four cantilever columns of unequal stiffness under a "
        "lateral force at the plan centre: the twist, the translation at the centre of rigidity, "
        "the displacements at the centre and the stiff column's shear, by hand.",
        "Columns 3.2 m, fixed bases, at the corners of a 6 × 5 m plan: 500 × 500 at the origin, "
        "400 × 400 at the others, C24.1; 100 kN in X at (3, 2.5) m. The case adds the master "
        "node and the rigid diaphragm constraint to the derived project.",
        rigid_diaphragm,
    ),
    Case(
        "AG4",
        "Wall shell: cantilever wall, pier P, V and M",
        "analysis",
        "Pier forces of a two-storey cantilever wall of shells (saengine.design.wall_forces) "
        "against statics: axial force, in-plane shear and moment at the base and at level 1.",
        "Wall 4 m × 6 m, 200 mm, C24.1, of 06 BIM, fixed base, meshed at 500 mm; 150 kN along "
        "the top in WX and 200 kN down at the top in D beside the self-weight. The case removes "
        "the floor diaphragms and sets the loads in the derived project.",
        wall_piers,
    ),
    Case(
        "DG5",
        "Strong column / weak beam and the beam's capacity shear at one joint",
        "design",
        "Sec 8.3.5.2 ΣMnc ≥ 1.2 ΣMnb and Sec 8.3.8.1(a) Ve of a special moment frame "
        "(saengine.design.ductile_joints), the ratio and 1.25 fy from the code pack, against "
        "strain compatibility by hand.",
        "Interior joint: 500 × 500 columns (12 Ø20) above (P = 800 kN) and below (1500 kN), "
        "400 × 500 beams (4 Ø20 top, 3 Ø20 bottom) on both sides in X; f'c = 28, fy = 420 MPa; "
        "ln = 3.5 m, Vg = 60 kN.",
        strong_column,
    ),
    Case(
        "DG6",
        "Cantilever retaining wall: stability and stem design",
        "design",
        "Rankine active thrust, the factors of safety against overturning and sliding, the base "
        "pressures and the stem's design moment, shear and φMn at its base, by the textbook "
        "procedure.",
        "Wall 4.5 m from the retained ground to the underside of the base: stem 400 mm × 4.0 m, "
        "base 500 mm, toe 1.0 m, heel 2.0 m; dry backfill γ = 18 kN/m³, φ' = 30°, level, no "
        "surcharge, drained; f'c = 25, fy = 420 MPa, 50 mm cover.",
        retaining_wall,
    ),
    Case(
        "AG7",
        "e2k round trip of a verified frame with identical results",
        "analysis",
        "The one-bay portal of A3, drawn in the floor plan, exported to ETABS e2k and read back: "
        "both models run under the same lateral load and give the same sway and base moments, "
        "which match the slope-deflection solution.",
        "Floor plan bay A-B (6 m), 400 × 400 columns 3.2 m, fixed bases, beam 300 × 500 on A1-B1, "
        "C24.1; 10 kN in X at the top of A1 (set in each derived project).",
        e2k_round_trip,
    ),
    Case(
        "AG8",
        "Fixed beam with a support settlement",
        "analysis",
        "The support settlement case ST (saengine.fem.settlement) on a fixed-ended beam: the end "
        "moment 6EIΔ/L² and the shear 12EIΔ/L³.",
        "Floor plan bay A-B, beam 300 × 500 mm, 6 m between 400 × 400 columns 3.2 m high, fixed "
        "bases; the base of C2 settles 10 mm. The case holds the beam's joints against rotation "
        "and horizontal movement (free vertically) in the derived project.",
        settlement,
    ),
    Case(
        "AG9",
        "Semi-rigid diaphragm: a slab spanning as a deep beam between two walls",
        "analysis",
        "A slab of shells loaded in its plane between two walls: the in-plane midspan "
        "deflection against plane stress elasticity (bending and shear) and the in-plane moment "
        "against statics.",
        "Slab 16 m × 4 m, 150 mm, C24.1, meshed at 250 mm; the walls hold Y along the short "
        "edges; 50 kN/m in -Y along the long edge. The case sets the boundary conditions and the "
        "load in the derived project.",
        semi_rigid,
    ),
    Case(
        "DG10",
        "One-bay bill of quantities and a beam's bar schedule",
        "design",
        "The bill of quantities of a one-bay frame (concrete, formwork, bars by size) against a "
        "hand take-off, and beam B1's detailing and bar schedule (links, cutting lengths, hooks, "
        "mass) against hand detailing.",
        "Floor plan bay 6 m × 5 m, one storey 3.2 m: columns 400 × 400 (4 Ø16, ties Ø10 @ 150), "
        "beams 300 × 500 (3 Ø20 bottom, 2 Ø16 top, stirrups Ø10 @ 150), slab 150 mm (Ø10 @ "
        "150/200), C24.1, B420DWR.",
        boq_and_schedule,
    ),
]
