"""Analysis benchmarks: SAEngine's analysis model (derived from a structural model) against theory.

Every case draws its structure as a Part 5 structural model (members, areas, blocks, supports),
derives the OpenSees Studio project with :func:`saengine.fem.derive.derive_fem` (sections,
meshing, self-weight, masses, spectra, records, pushover model), runs it with OpenSees Studio's
runner and reads the results the way the workbench does (:mod:`saengine.fem.display`). Where
a benchmark needs a load or a boundary condition the pipeline does not author, the case edits the
derived project and says so in its model description.

Units: the structural model in mm, the analysis model in m, N, kg, s, Pa.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from saengine.fem.display import result_view
from saengine.fem.nonlinear import HARDENING
from saengine.library.settings import Pushover, TimeHistory
from saengine.verification.cases.common import (
    BY_ID,
    MATERIALS,
    Case,
    G,
    Outcome,
    Quantity,
    Reference,
    building,
    derive,
    fmt,
    node_at,
    nodes_at,
    objects,
    only_pattern,
    point,
    run_model,
    settings,
    structure,
)

CONCRETE = BY_ID["C24.1"]
STEEL = BY_ID["A36"]
E_C = CONCRETE.mechanical.E * 1e6  # Pa
RHO_C = CONCRETE.mechanical.density  # kg/m³

BEAM = {
    "id": "BM",
    "name": "Beam 300x500",
    "kind": "beam",
    "material": CONCRETE.id,
    "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
}
COLUMN = {
    "id": "COL",
    "name": "Column 400x400",
    "kind": "column",
    "material": CONCRETE.id,
    "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
}
B_BM, H_BM = 0.3, 0.5
I_BM = B_BM * H_BM**3 / 12  # m⁴, about the beam's strong axis
A_BM = B_BM * H_BM
I_COL = 0.4**4 / 12
A_COL = 0.16

#: Tolerance of closed-form linear frame results (exact element formulations).
FRAME = 0.01


# ─────────────────────────────── cantilever (Euler-Bernoulli) ───────────────────────────────


def cantilever(folder: Path) -> Outcome:
    length, p = 4.0, 20e3  # m, N at the tip
    model = structure(
        members=[{"id": "M1", "type": "BM", "start": point(0, 0, 0), "end": point(4000, 0, 0)}],
        supports=[{"id": "S1", "at": point(0, 0, 0)}],
    )
    d = derive(building(model), objects(BEAM), MATERIALS, settings())
    project = d.project
    tip = node_at(project, (length, 0, 0))
    only_pattern(project, nodal=[{"node_id": tip, "forces": [0, 0, -p, 0, 0, 0]}], keep_dead=True)
    path, out, results = run_model(project, folder, [1])
    deflection = -results[1].node_disp[tip][-1][2]
    view = result_view(out, path, "case:1")
    (member,) = [e for e in view["elements"] if e["name"] == "M1"]
    moment = abs(member["forces"][0][4])
    shear = abs(member["forces"][0][2])

    w = RHO_C * G * A_BM
    ei = E_C * I_BM
    ref_deflection = w * length**4 / (8 * ei) + p * length**3 / (3 * ei)
    ref_moment = w * length**2 / 2 + p * length
    ref_shear = w * length + p
    reference = Reference(
        source="Euler-Bernoulli beam theory (e.g. Timoshenko & Gere, Mechanics of Materials, "
        "cantilever tables), superposition of a uniform load and a tip load",
        formula="δ = wL⁴/(8EI) + PL³/(3EI);  M_A = wL²/2 + PL;  V_A = wL + P",
        steps=[
            f"w = ρ g b h = {RHO_C:g} × 9.80665 × 0.3 × 0.5 = {fmt(w)} N/m (self-weight)",
            f"E = {fmt(E_C)} Pa, I = b h³/12 = {fmt(I_BM)} m⁴, EI = {fmt(ei)} N·m²",
            f"δ = {fmt(w)}×4⁴/(8EI) + {fmt(p)}×4³/(3EI) = {fmt(ref_deflection * 1e3)} mm",
            f"M_A = {fmt(w)}×4²/2 + {fmt(p)}×4 = {fmt(ref_moment / 1e3)} kN·m",
            f"V_A = {fmt(w)}×4 + {fmt(p)} = {fmt(ref_shear / 1e3)} kN",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Tip deflection", "mm", ref_deflection * 1e3, deflection * 1e3, FRAME),
            Quantity("Fixed-end moment", "kN·m", ref_moment / 1e3, moment / 1e3, FRAME),
            Quantity("Fixed-end shear", "kN", ref_shear / 1e3, shear / 1e3, FRAME),
        ],
    )


# ─────────────────────────────── simply supported beam ───────────────────────────────


def simply_supported(folder: Path) -> Outcome:
    span = 6.0
    model = structure(
        members=[
            {"id": "M1", "type": "BM", "start": point(0, 0, 0), "end": point(3000, 0, 0)},
            {"id": "M2", "type": "BM", "start": point(3000, 0, 0), "end": point(6000, 0, 0)},
        ],
        supports=[
            {"id": "S1", "at": point(0, 0, 0), "fixity": "pinned"},
            {"id": "S2", "at": point(6000, 0, 0), "fixity": "pinned"},
        ],
    )
    d = derive(building(model), objects(BEAM), MATERIALS, settings())
    project = d.project
    # Two pins leave a straight member free to spin about its own axis: hold that twist at the
    # supports (fork supports), as a real bearing does.
    for node in project["nodes"]:
        if node["restraint"][:3] == [True, True, True]:
            node["restraint"][3] = True
    path, out, results = run_model(project, folder, [1])
    mid = node_at(project, (span / 2, 0, 0))
    deflection = -results[1].node_disp[mid][-1][2]
    view = result_view(out, path, "case:1")
    (half,) = [e for e in view["elements"] if e["name"] == "M1"]
    moment = abs(half["forces"][-1][4])

    w = RHO_C * G * A_BM
    ei = E_C * I_BM
    ref_deflection = 5 * w * span**4 / (384 * ei)
    ref_moment = w * span**2 / 8
    reference = Reference(
        source="Euler-Bernoulli beam theory, simply supported beam under a uniform load "
        "(standard beam tables)",
        formula="δ_mid = 5wL⁴/(384EI);  M_mid = wL²/8",
        steps=[
            f"w = ρ g b h = {fmt(w)} N/m (self-weight of the 300 × 500 beam)",
            f"EI = {fmt(ei)} N·m², L = {span:g} m",
            f"δ_mid = 5 × {fmt(w)} × 6⁴ / (384 EI) = {fmt(ref_deflection * 1e3)} mm",
            f"M_mid = {fmt(w)} × 6² / 8 = {fmt(ref_moment / 1e3)} kN·m",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Midspan deflection", "mm", ref_deflection * 1e3, deflection * 1e3, FRAME),
            Quantity("Midspan moment", "kN·m", ref_moment / 1e3, moment / 1e3, FRAME),
        ],
        notes=[
            (
                "Two pinned supports leave a straight member free to rotate about its own axis "
                "(a mechanism the solver rejects); the case holds that twist at the supports."
            )
        ],
    )


# ─────────────────────────────── portal frame sway ───────────────────────────────


def portal_frame(folder: Path) -> Outcome:
    h, span, p = 3.2, 6.0, 10e3
    model = structure(
        members=[
            {"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3200)},
            {"id": "C2", "type": "COL", "start": point(6000, 0, 0), "end": point(6000, 0, 3200)},
            {"id": "B1", "type": "BM", "start": point(0, 0, 3200), "end": point(6000, 0, 3200)},
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}],
    )
    d = derive(building(model), objects(BEAM, COLUMN), MATERIALS, settings())
    project = d.project
    left, right = node_at(project, (0, 0, h)), node_at(project, (span, 0, h))
    only_pattern(project, nodal=[{"node_id": left, "forces": [p, 0, 0, 0, 0, 0]}])
    path, out, results = run_model(project, folder, [1])
    sway = (results[1].node_disp[left][-1][0] + results[1].node_disp[right][-1][0]) / 2
    view = result_view(out, path, "case:1")
    bases = [abs(e["forces"][0][4]) for e in view["elements"] if e["name"] in ("C1", "C2")]
    base_moment = sum(bases) / 2

    # Slope-deflection, members axially rigid: joint rotation θ (equal at both top joints by
    # antisymmetry) and sway Δ.
    kc, kb = E_C * I_COL / h, E_C * I_BM / span
    matrix = np.array([[4 * kc + 6 * kb, -6 * kc / h], [-6 * kc / h, 12 * kc / h**2]])
    theta, delta = np.linalg.solve(matrix, [0.0, p / 2])
    m_base = 2 * kc * (theta - 3 * delta / h)
    reference = Reference(
        source="Slope-deflection method (hand stiffness method), members axially rigid",
        formula="M_top = 2EIc/h (2θ - 3Δ/h), M_base = 2EIc/h (θ - 3Δ/h), M_beam = 6EIb θ/L; "
        "joint: M_top + M_beam = 0; story: Σ V_col = P",
        steps=[
            (
                f"kc = EIc/h = {fmt(kc)} N·m, kb = EIb/L = {fmt(kb)} N·m "
                f"(column 400 × 400, beam 300 × 500, h = {h:g} m, L = {span:g} m)"
            ),
            "Joint: (4kc + 6kb) θ - 6kc Δ/h = 0",
            "Story shear (P/2 per column): -6kc θ/h + 12kc Δ/h² = P/2",
            f"θ = {fmt(theta)} rad, Δ = {fmt(delta * 1e3)} mm",
            f"M_base = 2kc (θ - 3Δ/h) = {fmt(m_base / 1e3)} kN·m (each column)",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity(
                "Sway at the beam (mean of the two joints)", "mm", delta * 1e3, sway * 1e3, FRAME
            ),
            Quantity(
                "Column base moment (mean)", "kN·m", abs(m_base) / 1e3, base_moment / 1e3, FRAME
            ),
        ],
        notes=[
            (
                "The analysis model keeps axial deformations; the beam's shortening makes the two "
                "joints differ by about 2 % of the sway, so their mean is compared."
            )
        ],
    )


# ─────────────────────────────── cantilever natural frequency ───────────────────────────────

SEGMENTS = 20


def natural_frequency(folder: Path) -> Outcome:
    height = 3.0
    model = structure(
        members=[
            {
                "id": f"C{k + 1}",
                "type": "COL",
                "start": point(0, 0, 3000 * k / SEGMENTS),
                "end": point(0, 0, 3000 * (k + 1) / SEGMENTS),
            }
            for k in range(SEGMENTS)
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}],
    )
    d = derive(building(model), objects(COLUMN), MATERIALS, settings())
    project = d.project
    modal = next(a["id"] for a in project["analyses"] if a["type"] == "Modal")
    _, _, results = run_model(project, folder, [modal])
    frequency = 1 / float(results[modal].periods[0])

    m = RHO_C * A_COL
    ei = E_C * I_COL
    ref = 1.875104**2 / (2 * math.pi) * math.sqrt(ei / (m * height**4))
    reference = Reference(
        source="Euler-Bernoulli cantilever vibration (e.g. Clough & Penzien, Dynamics of "
        "Structures; Blevins, Formulas for Natural Frequency and Mode Shape): β₁L = 1.8751",
        formula="f₁ = (1.8751² / 2π) √(EI / (m L⁴))",
        steps=[
            f"m = ρ A = {RHO_C:g} × 0.16 = {fmt(m)} kg/m, EI = {fmt(ei)} N·m², L = {height:g} m",
            f"f₁ = 3.5160 / 2π × √({fmt(ei)} / ({fmt(m)} × 3⁴)) = {fmt(ref)} Hz",
        ],
    )
    return Outcome(
        reference,
        [Quantity("First natural frequency", "Hz", ref, frequency, FRAME)],
        notes=[
            (
                "Frame members are not subdivided by the mesh size and the masses are lumped at "
                f"the nodes from the self-weight: the column is drawn as {SEGMENTS} members. Drawn "
                "as one member its single lumped mass at the top gives a frequency 30 % low."
            )
        ],
    )


# ─────────────────────────────── one-mass oscillator ───────────────────────────────

MASS = 20_000.0  # kg at the top of the column
DT = 0.01
SINE_HZ, SINE_G, SINE_S = 1.5, 0.2, 3.0


def _oscillator(folder: Path, history: bool):
    """The 400 × 400 column, 3 m, fixed at its base, carrying one mass in X at its top: derived,
    then its masses replaced by that one. Returns (project, top node, stiffness)."""
    model = structure(
        members=[{"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3000)}],
        supports=[{"id": "S1", "at": point(0, 0, 0)}],
    )
    histories = []
    if history:
        record = folder / "02 Project Settings" / "records" / "sine.txt"
        record.parent.mkdir(parents=True, exist_ok=True)
        t = np.arange(0, SINE_S + DT / 2, DT)
        a = SINE_G * np.sin(2 * math.pi * SINE_HZ * t)
        record.write_text(
            "\n".join(f"{ti:.4f} {ai:.6f}" for ti, ai in zip(t, a, strict=True)) + "\n"
        )
        histories = [
            TimeHistory(name="Sine", record="02 Project Settings/records/sine.txt", direction="X")
        ]
    model_dir = folder / "08 FEM"
    model_dir.mkdir(parents=True, exist_ok=True)
    d = derive(
        building(model),
        objects(COLUMN),
        MATERIALS,
        settings(timeHistories=histories),
        None,
        model_dir,
    )
    project = d.project
    top = node_at(project, (0, 0, 3.0))
    for node in project["nodes"]:
        node["mass"] = [MASS, 0, 0, 0, 0, 0] if node["id"] == top else [0.0] * 6
    k = 3 * E_C * I_COL / 3.0**3
    return project, top, k, model_dir


def response_spectrum(folder: Path) -> Outcome:
    project, top, k, model_dir = _oscillator(folder, False)
    ids = {a["name"]: a["id"] for a in project["analyses"]}
    modal, rx = ids["Modal"], ids["RX: Response spectrum X"]
    _, _, results = run_model(project, model_dir, [modal, rx])
    period = float(results[modal].periods[0])
    u = float(results[rx].combined_disp[top][0])

    omega = math.sqrt(k / MASS)
    t = 2 * math.pi / omega
    # BNBC 2020 Part 6, 2.5.4.3: Sa = (2/3)(Z I / R) Cs; site class SD: S = 1.35, TB = 0.2 s,
    # TC = 0.8 s; on the plateau TB <= T <= TC, Cs = 2.5 S η, η = 1 at 5 % damping.
    z, importance, r = 0.20, 1.0, 5.0  # Dhaka (zone 2), ordinary building, RC IMF
    assert 0.2 <= t <= 0.8
    sa = 2 / 3 * z * importance / r * 2.5 * 1.35 * 1.0 * G
    ref_u = sa / omega**2
    reference = Reference(
        source="Single-degree-of-freedom oscillator (Chopra, Dynamics of Structures, ch. 6): "
        "peak displacement Sa/ω²; design spectrum of BNBC 2020 Part 6 2.5.4.3",
        formula="k = 3EI/L³, ω = √(k/m), u = Sa/ω², Sa = (2/3)(ZI/R)·2.5Sη·g on the plateau",
        steps=[
            f"k = 3EI/L³ = 3 × {fmt(E_C * I_COL)} / 3³ = {fmt(k)} N/m, m = {MASS:g} kg",
            f"ω = {fmt(omega)} rad/s, T = {fmt(t)} s (between TB = 0.2 s and TC = 0.8 s)",
            (
                "Z = 0.20 (Dhaka), I = 1.0, R = 5 (RC intermediate moment frame), site class SD: "
                "S = 1.35, η = 1"
            ),
            f"Sa = (2/3)(0.20 × 1.0 / 5) × 2.5 × 1.35 × g = {fmt(sa)} m/s²",
            f"u = Sa/ω² = {fmt(ref_u * 1e3)} mm",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Period", "s", t, period, FRAME),
            Quantity("Peak displacement", "mm", ref_u * 1e3, u * 1e3, FRAME),
        ],
        notes=[
            (
                "The derived masses (from the self-weight) are replaced by one mass in X at the top, "
                "so the column is a one-degree-of-freedom oscillator."
            )
        ],
    )


def newmark_average_acceleration(
    mass: float, stiffness: float, zeta: float, ground: np.ndarray, dt: float
) -> np.ndarray:
    """Displacement history of a linear oscillator under ground acceleration ``ground`` [m/s²]:
    Newmark's average-acceleration method in incremental form (Chopra, Table 5.4.2)."""
    gamma, beta = 0.5, 0.25
    c = 2 * zeta * math.sqrt(stiffness * mass)
    p = -mass * ground
    u, v = 0.0, 0.0
    a = (p[0] - c * v - stiffness * u) / mass
    k_hat = stiffness + gamma / (beta * dt) * c + mass / (beta * dt**2)
    a_coef = mass / (beta * dt) + gamma / beta * c
    b_coef = mass / (2 * beta) + dt * (gamma / (2 * beta) - 1) * c
    history = [u]
    for i in range(len(p) - 1):
        dp = p[i + 1] - p[i] + a_coef * v + b_coef * a
        du = dp / k_hat
        dv = gamma / (beta * dt) * du - gamma / beta * v + dt * (1 - gamma / (2 * beta)) * a
        da = du / (beta * dt**2) - v / (beta * dt) - a / (2 * beta)
        u, v, a = u + du, v + dv, a + da
        history.append(u)
    return np.array(history)


def time_history(folder: Path) -> Outcome:
    project, top, k, model_dir = _oscillator(folder, True)
    th = next(a for a in project["analyses"] if a["type"] == "Transient")
    _, _, results = run_model(project, model_dir, [th["id"]])
    # The dead loads before the shaking only shorten the column: they move its top in Z, not X.
    ux = results[th["id"]].node_disp_history(top)[:, 0]
    peak = float(np.max(np.abs(ux)))

    t = np.arange(0, SINE_S + DT / 2, DT)
    ground = SINE_G * G * np.sin(2 * math.pi * SINE_HZ * t)
    # The runner steps one record interval past the record's end (ground at rest there).
    ground = np.append(ground, 0.0)
    ref_history = newmark_average_acceleration(MASS, k, 0.05, ground, DT)
    ref_peak = float(np.max(np.abs(ref_history)))
    t_n = 2 * math.pi / math.sqrt(k / MASS)
    reference = Reference(
        source="Independent Newmark-β integration (average acceleration, γ = 1/2, β = 1/4) of "
        "the one-degree-of-freedom equation m ü + c u̇ + k u = -m üg (Chopra, Table 5.4.2)",
        formula="k̂ = k + γc/(βΔt) + m/(βΔt²); Δp̂ = Δp + (m/(βΔt) + γc/β) u̇ + "
        "(m/(2β) + Δt(γ/(2β) - 1) c) ü",
        steps=[
            f"m = {MASS:g} kg, k = 3EI/L³ = {fmt(k)} N/m, Tn = {fmt(t_n)} s, ζ = 5 %",
            f"üg = {SINE_G:g} g sin(2π × {SINE_HZ:g} t), 0 <= t <= {SINE_S:g} s, Δt = {DT:g} s",
            f"Peak |u| over {len(ground)} steps = {fmt(ref_peak * 1e3)} mm",
        ],
    )
    return Outcome(
        reference,
        [Quantity("Peak displacement", "mm", ref_peak * 1e3, peak * 1e3, FRAME)],
        notes=[
            (
                "SAEngine damps the time history with stiffness-proportional Rayleigh damping "
                "calibrated to 5 % in mode 1, which for one degree of freedom is c = 2ζωm."
            ),
        ],
    )


# ─────────────────────────────── pushover: plastic moment ───────────────────────────────

I_SECTION = {"b": 0.2, "d": 0.4, "tw": 0.008, "tf": 0.013}


def _i_moment_curvature(fy: float, e: float, hardening: float) -> tuple[np.ndarray, np.ndarray]:
    """Moment-curvature [N·m, 1/m] of the I section in strong-axis bending: plane sections,
    bilinear steel (E up to fy, then hardening × E), integrated over 2000 strips of the depth."""
    b, dd, tw, tf = I_SECTION.values()
    n = 2000
    y = (np.arange(n) + 0.5) / n * dd - dd / 2
    area = np.where(np.abs(y) > dd / 2 - tf, b, tw) * dd / n
    eps_y = fy / e
    kappa = np.concatenate([[0.0], np.geomspace(1e-6, 2.0, 3000)])
    eps = np.abs(np.outer(kappa, y))
    stress = np.where(eps <= eps_y, e * eps, fy + hardening * e * (eps - eps_y))
    return kappa, (stress * area * np.abs(y)).sum(axis=1)


def _continuum_base_moment(tip: float, height: float, kappa: np.ndarray, moment: np.ndarray):
    """Base moment [N·m] of a cantilever whose tip is pushed ``tip`` [m] by a point load, from
    δ = ∫ κ(M(s)) s ds along the height (s from the tip), solved for the load by bisection."""
    s = (np.arange(4000) + 0.5) / 4000 * height

    def deflection(load: float) -> float:
        return float(np.sum(np.interp(load * s, moment, kappa) * s) * height / s.size)

    lo, hi = 0.0, moment[-1] / height
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if deflection(mid) < tip else (lo, mid)
    return lo * height


def pushover(folder: Path) -> Outcome:
    height, drift, steps = 3.0, 3.0, 150  # m, %, steps (0.6 mm each)
    drifts = (1.0, 2.0, 3.0)  # %, where the curves are compared
    column = {
        "id": "W",
        "name": "I 400 x 200",
        "kind": "column",
        "material": STEEL.id,
        "profile": {
            "shape": "I",
            "overallWidth": 200,
            "overallDepth": 400,
            "webThickness": 8,
            "flangeThickness": 13,
        },
    }
    model = structure(
        members=[{"id": "C1", "type": "W", "start": point(0, 0, 0), "end": point(0, 0, 3000)}],
        supports=[{"id": "S1", "at": point(0, 0, 0)}],
    )
    # A column's depth lies along global Y: pushing in Y bends it about its strong axis.
    options = Pushover(directions=["Y"], targetDrift=drift, steps=steps)
    d = derive(
        building(model), objects(column), MATERIALS, settings(pushover=options), None, folder
    )
    project = d.pushover
    assert project is not None
    push = next(a for a in project["analyses"] if a["type"] == "Pushover")
    _, _, results = run_model(project, folder, [push["id"]], "pushover")
    result = results[push["id"]]
    base = node_at(project, (0, 0, 0))
    moments = np.array([abs(row[3]) for row in result.node_reaction[base]])  # about X
    displacement = np.abs(result.control_disp)
    stiffness = moments[1] / height / displacement[1]
    pushed = {x: float(np.interp(height * x / 100, displacement, moments)) for x in drifts}

    b, dd, tw, tf = I_SECTION.values()
    fy, e = STEEL.steel.fy * 1e6, STEEL.mechanical.E * 1e6
    z = b * tf * (dd - tf) + tw * (dd - 2 * tf) ** 2 / 4
    inertia = (b * dd**3 - (b - tw) * (dd - 2 * tf) ** 3) / 12
    mp = z * fy
    k_el = 3 * e * inertia / height**3
    dy = mp * height**2 / (3 * e * inertia)
    kappa, curve = _i_moment_curvature(fy, e, HARDENING)
    exact = {x: _continuum_base_moment(height * x / 100, height, kappa, curve) for x in drifts}
    reference = Reference(
        source="Plastic theory of steel beams (e.g. Neal, The Plastic Methods of Structural "
        "Analysis): plastic moment Mp = Z fy; elastic stiffness of a cantilever 3EI/L³; the "
        "inelastic tip deflection of a cantilever from the curvature along it, δ = ∫ κ(M) s ds "
        "(Euler-Bernoulli, plane sections; e.g. Timoshenko & Gere, Mechanics of Materials, "
        "inelastic bending), with the moment-curvature of the section integrated over its depth",
        formula="Z = b tf (d - tf) + tw (d - 2tf)²/4;  Mp = Z fy;  k = 3EI/L³;  "
        "M(κ) = ∫ σ(κ y) |y| dA, σ bilinear (E, then b E past fy);  δ(P) = ∫₀ᴸ κ(P s) s ds",
        steps=[
            "I 400 × 200 × 8 × 13 (welded, no root radii), A36: fy = 250 MPa, E = 200 GPa",
            f"Z = 0.2 × 0.013 × 0.387 + 0.008 × 0.374²/4 = {fmt(z * 1e6)} × 10³ mm³",
            f"Mp = Z fy = {fmt(mp / 1e3)} kN·m",
            f"I = {fmt(inertia * 1e12)} mm⁴, k = 3EI/L³ = {fmt(k_el / 1e3)} kN/m",
            (
                f"Tip displacement when the base reaches Mp elastically: Mp L²/(3EI) = "
                f"{fmt(dy * 1e3)} mm; the push goes to {drift:g} % drift = "
                f"{height * drift * 10:g} mm"
            ),
            (
                f"The steel hardens past yield by b = {HARDENING:g} of E (the material SAEngine "
                "assigns, Steel02 with b = 0.01), so the base moment does not cap at Mp: it rises "
                "past it as the yielded zone at the base strains further. The reference follows "
                "that hardening exactly in the continuum, with a bilinear stress-strain law: "
                "M(κ) over 2000 strips of the depth, then δ = ∫ κ(P s) s ds over 4000 stations "
                "of the height, solved for the tip load P at each drift"
            ),
            *(
                f"{x:g} % drift ({height * x * 10:g} mm): base moment {fmt(exact[x] / 1e3)} kN·m "
                f"= {exact[x] / mp:.3f} Mp"
                for x in drifts
            ),
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Initial lateral stiffness", "kN/m", k_el / 1e3, stiffness / 1e3, FRAME),
            *(
                Quantity(
                    f"Base moment at {x:g} % drift", "kN·m", exact[x] / 1e3, pushed[x] / 1e3, 0.03
                )
                for x in drifts
            ),
        ],
        notes=[
            (
                "The derived model is one force-based element (5 Lobatto points) with Steel02 "
                "fibers. It differs from the continuum reference in two ways, which the 3 % "
                "tolerance covers: Steel02 rounds the corner at yield (R0 = 18) where the "
                "reference is bilinear, so near the knee SAEngine's moment is a little lower; and "
                "the element lumps the base's plastic curvature over its end integration weight "
                "(L/20) where the continuum spreads it over the length where M > My, so at large "
                "drift SAEngine's moment is a little higher. An elastic-perfectly-plastic material "
                "would cap the curve at Mp; with SAEngine's 1 % hardening the exact base moment is "
                f"{exact[1.0] / mp:.2f}, {exact[2.0] / mp:.2f} and {exact[3.0] / mp:.2f} Mp at "
                "1, 2 and 3 % drift."
            ),
        ],
    )


# ─────────────────────────────── plate (Timoshenko) ───────────────────────────────


def plate(folder: Path) -> Outcome:
    side, thickness, mesh_size = 2.0, 0.020, 100  # m, m, mm
    plate_type = {
        "id": "PL",
        "name": "Steel plate 20",
        "kind": "slab",
        "material": STEEL.id,
        "thickness": thickness * 1000,
    }
    half = side * 1000 / 2
    # Four quarter panels: their shared corner puts a node at the plate's centre.
    model = structure(
        areas=[
            {
                "id": f"P{i}{j}",
                "type": "PL",
                "outline": [
                    point(i * half, j * half, 0),
                    point((i + 1) * half, j * half, 0),
                    point((i + 1) * half, (j + 1) * half, 0),
                    point(i * half, (j + 1) * half, 0),
                ],
            }
            for i in (0, 1)
            for j in (0, 1)
        ]
    )
    d = derive(building(model), objects(plate_type), MATERIALS, settings(meshSize=mesh_size))
    project = d.project
    edge = set(nodes_at(project, lambda c: min(c[0], c[1], side - c[0], side - c[1]) < 1e-9))
    for node in project["nodes"]:
        if node["id"] in edge:
            node["restraint"] = [True, True, True, False, False, False]
    path, out, results = run_model(project, folder, [1])
    centre = node_at(project, (side / 2, side / 2, 0))
    deflection = -results[1].node_disp[centre][-1][2]
    view = result_view(out, path, "case:1")
    around = [s for s in view["shells"] if centre in s["nodes"]]
    moment = float(
        np.mean([abs(s["forces"][3]) for s in around] + [abs(s["forces"][4]) for s in around])
    )
    shells = sum(1 for e in project["elements"] if e["type"] == "Shell")

    e, nu = STEEL.mechanical.E * 1e6, STEEL.mechanical.nu
    q = STEEL.mechanical.density * G * thickness
    stiffness = e * thickness**3 / (12 * (1 - nu**2))
    ref_w = 0.00406 * q * side**4 / stiffness
    ref_m = 0.0479 * q * side**2
    reference = Reference(
        source="Timoshenko & Woinowsky-Krieger, Theory of Plates and Shells, simply supported "
        "rectangular plate under uniform load (Navier solution), b/a = 1: α = 0.00406, "
        "β = 0.0479 (ν = 0.3)",
        formula="w_c = α q a⁴ / D,  D = E h³ / (12 (1 - ν²));  Mx = My = β q a²",
        steps=[
            (
                f"Square steel plate a = {side:g} m, h = {thickness * 1000:g} mm (a/h = 100), "
                f"E = 200 GPa, ν = {nu:g}"
            ),
            f"q = ρ g h = 7850 × 9.80665 × 0.02 = {fmt(q)} Pa (self-weight)",
            f"D = {fmt(stiffness)} N·m",
            f"w_c = 0.00406 × {fmt(q)} × 2⁴ / D = {fmt(ref_w * 1e3)} mm",
            f"M_c = 0.0479 × {fmt(q)} × 2² = {fmt(ref_m)} N·m/m",
        ],
    )
    return Outcome(
        reference,
        [
            Quantity("Central deflection", "mm", ref_w * 1e3, deflection * 1e3, 0.02),
            Quantity("Central moment Mx = My", "N·m/m", ref_m, moment, 0.02),
        ],
        notes=[
            (
                f"{shells} ASDShellQ4 elements ({mesh_size} mm mesh); all edge nodes held in "
                "translation, free to rotate (the derived model of a special structure has no "
                "line supports, so the case adds them). The moment is the mean over the four "
                "elements at the centre, read at their centroids (about 50 mm from the centre)."
            )
        ],
    )


# ─────────────────────────────── solid cantilever ───────────────────────────────


def solid_cantilever(folder: Path) -> Outcome:
    length, b, h = 4.0, 0.3, 0.6
    default_mesh = settings().analysis.meshSize
    finest = 100.0  # mm, the smallest mesh size Project Settings accept
    # The default and the finest mesh a user can choose, then one below that floor (set past
    # the settings' validation) to show where the elements converge.
    meshes = [default_mesh, finest, 50.0]
    solid = {"id": "MASS", "name": "Mass concrete", "kind": "solid", "material": CONCRETE.id}
    model = structure(
        blocks=[
            {
                "id": "K1",
                "type": "MASS",
                "outline": [
                    point(0, -150, -300),
                    point(0, 150, -300),
                    point(0, 150, 300),
                    point(0, -150, 300),
                ],
                "thickness": 4000,
                "supported": True,
            }
        ]
    )
    sags, counts = [], []
    for mesh_size in meshes:
        d = derive(building(model), objects(solid), MATERIALS, settings(meshSize=mesh_size))
        project = d.project
        _, _, results = run_model(project, folder, [1], f"mesh{mesh_size:g}")
        tip = nodes_at(project, lambda c: abs(c[0] - length) < 1e-9)
        sags.append(-float(np.mean([results[1].node_disp[n][-1][2] for n in tip])))
        counts.append(d.summary["solids"])

    nu = CONCRETE.mechanical.nu
    w = RHO_C * G * b * h
    inertia = b * h**3 / 12
    shear_modulus = E_C / (2 * (1 + nu))
    bending = w * length**4 / (8 * E_C * inertia)
    shear = w * length**2 / (2 * 5 / 6 * shear_modulus * b * h)
    reference = Reference(
        source="Timoshenko beam theory: cantilever under a uniform load, bending plus shear "
        "deflection with the shear coefficient κ = 5/6 of a rectangle",
        formula="δ = wL⁴/(8EI) + wL²/(2κGA)",
        steps=[
            (
                f"Block 300 × 600 × 4000 mm of C24.1: E = {fmt(E_C)} Pa, ν = {nu:g}, "
                f"G = {fmt(shear_modulus)} Pa"
            ),
            f"w = ρ g b h = {fmt(w)} N/m",
            (
                f"Bending: wL⁴/(8EI) = {fmt(bending * 1e3)} mm; shear: wL²/(2κGA) = "
                f"{fmt(shear * 1e3)} mm"
            ),
            f"δ = {fmt((bending + shear) * 1e3)} mm",
        ],
    )
    labels = [
        f"default {default_mesh:g} mm mesh",
        f"{finest:g} mm mesh (finest allowed)",
        f"{meshes[2]:g} mm mesh (below minimum)",
    ]
    return Outcome(
        reference,
        [
            Quantity(f"Tip deflection, {label}", "mm", (bending + shear) * 1e3, sag * 1e3, 0.05)
            for label, sag in zip(labels, sags, strict=True)
        ],
        notes=[
            (
                f"Four-node tetrahedra: {', '.join(f'{c} at {m:g} mm' for c, m in zip(counts, meshes, strict=True))}. "
                "The tip deflection is the mean over the end face."
            ),
            (
                "KNOWN ISSUE (the case fails): SAEngine meshes blocks into linear (four-node) "
                "tetrahedra only, which are too stiff in bending and converge slowly, and Project "
                "Settings do not accept a mesh size below 100 mm. At the default mesh and at the "
                "finest mesh a user can choose, the deflection of this bending-dominated block is "
                "about 8 % low, outside the 5 % tolerance; only a finer mesh than the settings "
                "allow comes within it. The fully held end face also restrains the section's "
                "warping, which beam theory does not (a small part of the gap). Remedies are "
                "SAEngine's to choose: quadratic (ten-node) tetrahedra, hexahedra, or a lower "
                "mesh-size floor for solids."
            ),
        ],
    )


CASES = [
    Case(
        "A1",
        "Cantilever beam: tip deflection and fixed-end moment",
        "analysis",
        "A horizontal reinforced-concrete cantilever under its own weight and a point load at "
        "its tip.",
        "Beam 300 × 500 mm of C24.1, 4 m long along X, fixed at x = 0 (one member, one fixed "
        "support). Load case D: the self-weight derived by SAEngine, plus 20 kN down at the tip "
        "added to the case.",
        cantilever,
    ),
    Case(
        "A2",
        "Simply supported beam under a uniform load",
        "analysis",
        "Midspan deflection and moment of a simply supported beam under its own weight.",
        "Beam 300 × 500 mm of C24.1, span 6 m along X drawn as two members meeting at midspan, "
        "pinned supports at both ends (twist about the beam axis held). Load case D: the "
        "self-weight.",
        simply_supported,
    ),
    Case(
        "A3",
        "Portal frame sway",
        "analysis",
        "Lateral sway and base moments of a fixed-base single-bay portal frame under a "
        "horizontal load at beam level.",
        "Columns 400 × 400 mm, 3.2 m high, 6 m apart; beam 300 × 500 mm; all C24.1; both "
        "column bases fixed. 10 kN in +X at the top of the left column; no other load.",
        portal_frame,
    ),
    Case(
        "A4",
        "Cantilever natural frequency",
        "analysis",
        "First natural frequency of a uniform cantilever with distributed mass.",
        f"Column 400 × 400 mm of C24.1, 3 m tall, fixed at its base, drawn as {SEGMENTS} "
        "members; masses lumped at the nodes from the self-weight (SAEngine's derivation). "
        "Modal analysis.",
        natural_frequency,
    ),
    Case(
        "A5",
        "Response spectrum: one-mass oscillator",
        "analysis",
        "Peak displacement of a one-degree-of-freedom oscillator under SAEngine's BNBC 2020 "
        "design spectrum.",
        "Column 400 × 400 mm of C24.1, 3 m tall, fixed at its base, with one 20 t mass in X at "
        "its top (other masses removed). Project settings: Dhaka, site class SD, RC IMF. "
        "Modal and response spectrum X analyses as derived.",
        response_spectrum,
    ),
    Case(
        "A6",
        "Time history: one-mass oscillator",
        "analysis",
        "Peak displacement of the same oscillator under a sine ground motion, against an "
        "independent Newmark-β integration.",
        "The A5 oscillator; a 3 s record of 0.2 g at 1.5 Hz (Δt = 0.01 s) in the project's "
        "records folder, entered as a time history in X with 5 % damping. The time history "
        "derived by SAEngine runs after the dead loads (which only shorten the column), and "
        "the top's displacement history in X is compared.",
        time_history,
    ),
    Case(
        "A7",
        "Pushover of a steel cantilever: plastic moment and hardening",
        "analysis",
        "The derived pushover model (force-based fiber elements) of a steel cantilever column "
        "against the exact inelastic response of the same cantilever: past its plastic moment "
        "and along the hardening branch, at 1, 2 and 3 % drift.",
        "Welded I 400 × 200 × 8 × 13 column of A36, 3 m tall, fixed at its base (one member). "
        "Pushover in Y (strong axis) to 3 % drift in 150 steps, the lateral load following the "
        "masses, as SAEngine derives it.",
        pushover,
    ),
    Case(
        "A8",
        "Simply supported square plate (shells)",
        "analysis",
        "Central deflection and moment of a simply supported square plate under a uniform "
        "load, with SAEngine's shell meshing.",
        "Steel plate 2 m × 2 m × 20 mm (A36, ν = 0.3) drawn as four quarter areas, meshed at "
        "100 mm into quadrilateral shells; every edge node held in translation. Load case D: "
        "the self-weight.",
        plate,
    ),
    Case(
        "A9",
        "Solid cantilever (blocks)",
        "analysis",
        "Tip deflection of a cantilever modelled as a solid block of tetrahedra under its own "
        "weight.",
        "Block 300 × 600 mm, 4 m long, of C24.1, its end face supported (held in every "
        "direction); meshed at the default size, at 100 mm (the finest Project Settings "
        "accept) and at 50 mm. Load case D: the self-weight.",
        solid_cantilever,
    ),
]
