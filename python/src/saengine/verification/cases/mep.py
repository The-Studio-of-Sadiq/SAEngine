"""MEP coordination benchmarks (Part 7): equipment loads and the checks of sleeves and openings.

The cases run SAEngine's own functions (:mod:`saengine.mep.loads`, :mod:`saengine.mep.openings`)
on synthetic equipment, beams and slabs, and work the same quantities out by hand: statics and
the shape functions of a four-node element, the net-section shear of a beam at a sleeve
(ACI 318-19 22.5 with d - a0), the punching perimeter an opening near a column makes ineffective
(BNBC 2020 6.4.10.6.1) and, through the analysis, the shear and moment at an opening.

Units: mm, N and MPa inside; reported in kN, kN·m and mm.
"""

from __future__ import annotations

import math
from pathlib import Path

from saengine.library.bim import BuildingModel
from saengine.library.mep import Equipment, MepModel, Opening
from saengine.mep.loads import equipment_loads
from saengine.mep.openings import (
    BeamSection,
    ColumnAt,
    SlabInfo,
    demands_at,
    ineffective_perimeter,
    net_shear,
    opening_polygon,
    slab_opening_checks,
)
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
    objects,
    point,
    run_model,
    settings,
    structure,
)

#: Tolerance of a hand calculation the code reproduces in closed form.
EXACT = 0.005
#: Linear frame results (exact element formulations).
FRAME = 0.01


# ─────────────────────────────── DM1: equipment on a shell ───────────────────────────────


def equipment_case(_: Path) -> Outcome:
    slab = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": 3000},
            ],
            "elements": [
                {
                    "id": "S1",
                    "type": "SL",
                    "kind": "slab",
                    "boundary": [[0, 0], [4000, 0], [4000, 4000], [0, 4000]],
                    "elevation": 3000,
                }
            ],
        }
    )
    # One 2 x 2 m four-node shell of S1, nodes 1-4 counter-clockwise from the origin.
    nodes = {1: [0, 0, 3.0], 2: [2, 0, 3.0], 3: [2, 2, 3.0], 4: [0, 2, 3.0]}
    shells = [("S1", (1, 2, 3, 4))]
    pump = Equipment(
        id="P1",
        kind="pump",
        story="L1",
        x=500,
        y=1200,
        length=600,
        width=400,
        operatingWeight=40,
        vibrating=True,
        loadAs="points",
        supports=[[0, 0]],
    )
    loads = equipment_loads(slab, MepModel(equipment=[pump]), nodes, shells)
    sd = {ld.node: -ld.force[2] for ld in loads.nodal if ld.case == "SD"}
    live = sum(-ld.force[2] for ld in loads.nodal if ld.case == "L")

    # By hand: the point (0.5, 1.2) m in the element 0..2 x 0..2: ξ = 0.5/1 - 1 = -0.5,
    # η = 1.2/1 - 1 = 0.2; N1 = (1 - ξ)(1 - η)/4, N3 = (1 + ξ)(1 + η)/4.
    xi, eta = 0.5 / 1.0 - 1, 1.2 / 1.0 - 1
    n1 = (1 - xi) * (1 - eta) / 4
    n3 = (1 + xi) * (1 + eta) / 4
    w = 40e3
    impact = 0.20 * w
    return Outcome(
        Reference(
            source="Bilinear shape functions of a four-node element (consistent nodal loads); "
            "BNBC 2020 Sec 2.2.6 and Table 6.2.6 (light machinery, 20 %)",
            formula="F_i = P N_i(ξ, η), N_i = (1 + ξ_i ξ)(1 + η_i η) / 4; impact = 0.20 W, case L",
            steps=[
                "A 40 kN motor-driven pump on one support at (0.5, 1.2) m of a 2 × 2 m shell",
                f"ξ = 2 × 0.5 / 2 - 1 = {xi:g}, η = 2 × 1.2 / 2 - 1 = {eta:g}",
                f"N1 = (1 + 0.5)(1 - 0.2)/4 = {fmt(n1)}, N3 = (1 - 0.5)(1 + 0.2)/4 = {fmt(n3)}",
                f"Node 1: {fmt(n1)} × 40 = {fmt(n1 * 40)} kN; node 3: {fmt(n3 * 40)} kN (SD)",
                f"Impact 20 % of the operating weight: {fmt(impact / 1e3)} kN live load",
            ],
        ),
        [
            Quantity("Dead load at node 1", "kN", n1 * w / 1e3, sd[1] / 1e3, EXACT),
            Quantity("Dead load at node 3", "kN", n3 * w / 1e3, sd[3] / 1e3, EXACT),
            Quantity("Impact (live load)", "kN", impact / 1e3, live / 1e3, EXACT),
        ],
    )


# ─────────────────────────────── DM2: sleeve through a beam ───────────────────────────────


def sleeve_case(_: Path) -> Outcome:
    a_bar = math.pi * 16**2 / 4
    beam = BeamSection(
        id="B1",
        length=6000,
        h=500,
        b=300,
        cover=40,
        stirrup_dia=10,
        legs=2,
        spacing=150,
        fc=25,
        fy=420,
        as_top=3 * a_bar,
        as_bottom=4 * a_bar,
        top_dia=16,
        bottom_dia=16,
        d=442,
        d_top=442,
    )
    shear = net_shear(beam, 150)

    d = 500 - 40 - 10 - 16 / 2
    dn = d - 150
    av = 2 * math.pi * 10**2 / 4
    av_min = max(0.062 * 5, 0.35) * 300 * 150 / 420
    vc = 0.17 * 1.0 * 5 * 300 * dn
    vs = av * 420 * dn / 150
    phi_vn = 0.75 * (vc + vs)
    return Outcome(
        Reference(
            source="ACI 318-19 Table 22.5.5.1 (a), 22.5.8.5.3, 22.5.1.2 with the effective depth "
            "reduced by the opening (BNBC 2020 6.4.1.1.1: openings in Vn)",
            formula="φVn = 0.75 [0.17 λ √f'c b (d - a0) + Av fyt (d - a0) / s]",
            steps=[
                "Beam 300 × 500, Ø10 two-leg stirrups @ 150, 4 Ø16 bottom, cover 40; Ø150 sleeve",
                f"d = 500 - 40 - 10 - 8 = {d:g} mm, d - a0 = {dn:g} mm",
                f"Av = {fmt(av)} mm² >= Av,min = 0.35 × 300 × 150 / 420 = {fmt(av_min)} mm²",
                f"Vc = 0.17 × 5 × 300 × {dn:g} = {fmt(vc / 1e3)} kN",
                f"Vs = {fmt(av)} × 420 × {dn:g} / 150 = {fmt(vs / 1e3)} kN",
                f"φVn = 0.75 × ({fmt(vc / 1e3)} + {fmt(vs / 1e3)}) = {fmt(phi_vn / 1e3)} kN",
            ],
        ),
        [
            Quantity("Vc of the net section", "kN", vc / 1e3, shear["vc"] / 1e3, EXACT),
            Quantity("Vs of the net section", "kN", vs / 1e3, shear["vs"] / 1e3, EXACT),
            Quantity("φVn at the sleeve", "kN", phi_vn / 1e3, shear["phi_vn"] / 1e3, EXACT),
        ],
    )


# ─────────────────────────────── DM3: opening near a column ───────────────────────────────


def punching_case(_: Path) -> Outcome:
    column = ColumnAt("C1", (6000.0, 6000.0), 500, 500)
    slab = SlabInfo(
        id="S1",
        boundary=[[0, 0], [12000, 0], [12000, 12000], [0, 12000]],
        h=200,
        d=160,
        fc=25,
        flat=True,
    )
    opening = Opening.model_validate(
        {
            "id": "OP1",
            "host": "S1",
            "kind": "opening",
            "shape": "rectangle",
            "width": 300,
            "height": 300,
            "position": {"x": 6000, "y": 7000},
        }
    )
    hole = opening_polygon(opening, 6000, 7000)
    b0, lost = ineffective_perimeter(column, slab.d, slab.boundary, hole)
    checks, _ = slab_opening_checks(opening, slab, [column], (), lambda _: [("U1", 500e3)])
    punching = next(c for c in checks if c["name"].startswith("Punching"))

    side = 500 + 160
    ref_b0 = 4 * side
    ref_lost = 2 * (side / 2) * 150 / (7000 - 150 - 6000)
    effective = ref_b0 - ref_lost
    vc = min(0.33, 0.17 * 3, 0.083 * (2 + 40 * 160 / effective)) * 5
    capacity = 0.75 * vc * effective * 160
    return Outcome(
        Reference(
            source="BNBC 2020 6.4.10.6.1 (ACI 318-19 22.6.4.3) and ACI 318-19 Table 22.6.5.2",
            formula="b0,eff = b0 - the part between the tangents from the column centroid to "
            "the opening; φVc = 0.75 vc b0,eff d",
            steps=[
                (
                    "Interior column 500 × 500, flat slab h = 200, d = 160, f'c = 25; a 300 × 300 "
                    "opening centred 1000 mm from the column centre"
                ),
                f"b0 = 4 (500 + 160) = {ref_b0:g} mm; 600 mm from the face < 10 h = 2000 mm",
                (
                    f"Tangents to the corners (±150, 850) cross the side v = 330 at u = ±330 × 150 / "
                    f"850: {fmt(ref_lost)} mm ineffective"
                ),
                (
                    f"vc = min(0.33, 0.51, 0.083 (2 + 40 × 160 / {fmt(effective)})) × √25 = "
                    f"{fmt(vc)} MPa"
                ),
                f"φVc = 0.75 × {fmt(vc)} × {fmt(effective)} × 160 = {fmt(capacity / 1e3)} kN",
            ],
        ),
        [
            Quantity("Critical perimeter b0", "mm", ref_b0, b0, EXACT),
            Quantity("Ineffective perimeter", "mm", ref_lost, lost, EXACT),
            Quantity(
                "φVc on the reduced perimeter", "kN", capacity / 1e3, punching["capacity"], EXACT
            ),
        ],
    )


# ─────────────────────── AM1: forces at an opening from the analysis ───────────────────────

CONCRETE = BY_ID["C24.1"]
BEAM = {
    "id": "BM",
    "name": "Beam 300x500",
    "kind": "beam",
    "material": CONCRETE.id,
    "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
}


def forces_case(folder: Path) -> Outcome:
    from saengine.design.check import _demands

    span, x = 6.0, 1.5
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
    project_settings = settings()
    d = derive(building(model), objects(BEAM), MATERIALS, project_settings)
    project = d.project
    for node in project["nodes"]:  # fork supports, as in A2
        if node["restraint"][:3] == [True, True, True]:
            node["restraint"][3] = True
    _, out, _ = run_model(project, folder, [1, 2])
    names, pieces, _, _ = _demands(project, out, project_settings)
    first = names.index("1.4D")
    combination, v, m = demands_at(pieces["M1"], (0, 0), (3000, 0), x * 1e3, names)[first]

    w = CONCRETE.mechanical.density * G * 0.3 * 0.5
    vu = 1.4 * w * (span / 2 - x)
    mu = 1.4 * w * x * (span - x) / 2
    return Outcome(
        Reference(
            source="Statics of a simply supported beam under a uniform load",
            formula="V(x) = w (L/2 - x), M(x) = w x (L - x) / 2, factored by 1.4 (1.4D)",
            steps=[
                f"w = ρ g b h = {fmt(w)} N/m (self-weight of the 300 × 500 beam), L = 6 m",
                f"At the opening x = 1.5 m: V = 1.4 × {fmt(w)} × 1.5 = {fmt(vu / 1e3)} kN",
                f"M = 1.4 × {fmt(w)} × 1.5 × 4.5 / 2 = {fmt(mu / 1e3)} kN·m (sagging)",
            ],
        ),
        [
            Quantity(f"Vu at the opening ({combination})", "kN", vu / 1e3, abs(v) / 1e3, FRAME),
            Quantity(f"Mu at the opening ({combination})", "kN·m", mu / 1e3, abs(m) / 1e6, FRAME),
        ],
        notes=["The beam of A2; the opening checks read the forces where the opening is."],
    )


CASES = [
    Case(
        "DM1",
        "Equipment on a shell slab: consistent nodal loads",
        "design",
        "A pump's weight on one support inside a four-node shell goes to the element's nodes by "
        "its shape functions (dead load), and its impact allowance to the live load.",
        "Slab S1 meshed with a 2 × 2 m shell (nodes at its corners); a 40 kN vibrating pump on "
        "one support at (0.5, 1.2) m; mep.loads.equipment_loads.",
        equipment_case,
    ),
    Case(
        "DM2",
        "Sleeve through a beam: net-section shear",
        "design",
        "Design shear strength of a beam at a sleeve with the effective depth reduced by the "
        "sleeve's diameter.",
        "Beam 300 × 500, Ø10 stirrups @ 150, 4 Ø16 bottom, cover 40, f'c = 25, fy = 420; a Ø150 "
        "sleeve at mid-depth; mep.openings.net_shear.",
        sleeve_case,
    ),
    Case(
        "DM3",
        "Slab opening near a column: punching perimeter",
        "design",
        "The part of the punching critical section an opening near a column makes ineffective "
        "and the shear strength on what is left.",
        "Flat slab h = 200 (d = 160), f'c = 25, interior column 500 × 500; a 300 × 300 opening "
        "1 m from the column centre; mep.openings.slab_opening_checks.",
        punching_case,
    ),
    Case(
        "AM1",
        "Forces at a beam opening from the analysis",
        "analysis",
        "The shear and moment the opening checks read at an opening of a simply supported beam.",
        "The A2 beam (300 × 500, 6 m, pinned ends, self-weight); an opening 1.5 m from the "
        "support; design.check._demands and mep.openings.demands_at under 1.4D.",
        forces_case,
    ),
]
