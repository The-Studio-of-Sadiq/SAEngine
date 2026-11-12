"""Soil-structure interaction (saengine.fem.ssi): spring formulas and the models, checked by hand.

The soil is synthetic: one uniform sand layer (γ = 18 kN/m³, no water table) with SPT N = 10 every
1.5 m, so Vs = 97.0 x 10^0.314 = 199.88 m/s and G0 = ρ Vs² = (18000 / 9.80665) x 199.88² =
73.33 MPa at every depth.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from saengine.fem import ssi
from saengine.fem.derive import derive_fem
from saengine.library import FloorPlan, ObjectLibrary, default_floor_plan, default_material_library
from saengine.library.bim import generate
from saengine.library.settings import default_project_settings
from saengine.library.substructure import Substructure
from saengine.verification.cases.common import run_model

MATERIALS = default_material_library()
CONCRETE = next(m for m in MATERIALS.materials if m.id == "C24.1")
E_C = CONCRETE.mechanical.E * 1e6  # Pa

OBJECTS = ObjectLibrary.model_validate(
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
            {"id": "SL", "name": "Slab 150", "kind": "slab", "material": "C24.1", "thickness": 150},
        ]
    }
)
CORNERS = [("A", "1"), ("B", "1"), ("B", "2"), ("A", "2")]  # 6 m x 5 m, one storey of 3.2 m
BAY = FloorPlan.model_validate(
    {
        **default_floor_plan().model_dump(mode="json", by_alias=True),
        "columns": [
            {"id": f"C{i + 1}", "type": "COL", "at": {"x": x, "y": y}, "base": "BASE", "top": "L1"}
            for i, (x, y) in enumerate(CORNERS)
        ],
        "beams": [
            {
                "id": f"B{i + 1}",
                "type": "BM",
                "story": "L1",
                "start": {"x": a[0], "y": a[1]},
                "end": {"x": b[0], "y": b[1]},
            }
            for i, (a, b) in enumerate(zip(CORNERS, CORNERS[1:] + CORNERS[:1], strict=True))
        ],
        "slabs": [
            {
                "id": "S1",
                "type": "SL",
                "story": "L1",
                "boundary": [{"x": x, "y": y} for x, y in CORNERS],
            }
        ],
    }
)
SOIL = json.dumps(
    {
        "boreholes": [
            {
                "id": "BH1",
                "x": 3000,
                "y": 2500,
                "depth": 30000,
                "layers": [
                    {
                        "top": 0,
                        "bottom": 30000,
                        "description": "Uniform medium dense sand (synthetic)",
                        "soilType": "sand",
                        "unitWeight": 18.0,
                    }
                ],
                "spt": [{"depth": 1500 * k, "N": 10} for k in range(1, 21)],
            }
        ]
    }
)
VS = 199.88  # m/s
G0 = 18000 / 9.80665 * VS**2  # Pa


def bay():
    building = generate(BAY, "s")
    return building, derive_fem(building, OBJECTS, MATERIALS, default_project_settings("Bay"))


def single_column():
    plan = FloorPlan.model_validate(
        {
            **default_floor_plan().model_dump(mode="json", by_alias=True),
            "columns": [
                {"id": "C1", "type": "COL", "at": {"x": "A", "y": "1"}, "base": "BASE", "top": "L1"}
            ],
        }
    )
    building = generate(plan, "s")
    # Gross sections: the closed-form references use the column's full E·I.
    settings = default_project_settings("Col")
    settings.analysis.stiffness = "gross"
    return building, derive_fem(building, OBJECTS, MATERIALS, settings)


def springs(options=None):
    return ssi.SsiOptions(supports="soilSprings", **(options or {}))


# ─────────────────────────────── soil ───────────────────────────────


def test_shear_wave_velocity_and_modulus_from_spt() -> None:
    from saengine.substructure.piles import profiles_of

    # Vs = 97.0 N^0.314: 10^0.314 = 2.0606 -> 199.88 m/s; G0 = ρ Vs².
    assert ssi.vs_from_n(10) == pytest.approx(VS, rel=1e-4)
    assert ssi.vs_from_n(0) == pytest.approx(97.0)  # N taken at least 1
    profile = profiles_of(SOIL)[0][0]
    avg = ssi.soil_average(profile, 1.5, 3.5)
    assert avg.tests == 2 and avg.nu == pytest.approx(0.30)
    assert avg.g0 == pytest.approx(73.33e6, rel=1e-3)


def test_shear_modulus_ratio_table() -> None:
    assert ssi.shear_modulus_ratio(None) == 1.0
    assert ssi.shear_modulus_ratio(0.05) == pytest.approx(0.81)
    assert ssi.shear_modulus_ratio(0.15) == pytest.approx(0.64)
    # Between 0.15 (0.64) and 0.20 (0.49): 0.64 - 0.15 x 0.6 = 0.55 at 0.18 g.
    assert ssi.shear_modulus_ratio(0.18) == pytest.approx(0.55)
    assert ssi.shear_modulus_ratio(0.5) == pytest.approx(0.42)
    # BNBC: (2/3) Z S, Dhaka (Z = 0.20) on SD (S = 1.35) is 0.18 g.
    settings = default_project_settings("x")
    settings = settings.model_copy(
        update={
            "site": settings.site.model_copy(update={"zoneCoefficient": 0.2, "siteClass": "SD"})
        }
    )
    assert ssi.peak_acceleration(settings) == pytest.approx(0.18)


# ─────────────────────────────── footings ───────────────────────────────


def test_surface_stiffness_of_a_square_footing() -> None:
    # 2 m x 2 m on G = 50 MPa, ν = 0.3 (L/B = 1):
    # Kx = Ky = GB/(2-ν) (3.4 + 1.2) = 50e6 x 2 / 1.7 x 4.6 = 270.59e6 N/m (0.4 + 0.8 = 1.2 too)
    # Kz = GB/(1-ν) (1.55 + 0.8) = 100e6 / 0.7 x 2.35 = 335.71e6 N/m
    # Kxx = GB³/(1-ν) (0.4 + 0.1) = 400e6 / 0.7 x 0.5 = 285.71e6 N·m/rad
    # Kyy = GB³/(1-ν) (0.47 + 0.034) = 571.43e6 x 0.504 = 288.00e6 N·m/rad
    # Kzz = GB³ (0.53 + 0.51) = 416.00e6 N·m/rad
    k = ssi.surface_stiffness(50e6, 0.3, 2.0, 2.0)
    assert k["Kx"] == pytest.approx(270.588e6, rel=1e-5)
    assert k["Ky"] == pytest.approx(270.588e6, rel=1e-5)
    assert k["Kz"] == pytest.approx(335.714e6, rel=1e-5)
    assert k["Kxx"] == pytest.approx(285.714e6, rel=1e-5)
    assert k["Kyy"] == pytest.approx(288.000e6, rel=1e-5)
    assert k["Kzz"] == pytest.approx(416.000e6, rel=1e-5)
    # A long footing is stiffer across its length (y) than along it (x).
    long = ssi.surface_stiffness(50e6, 0.3, 6.0, 2.0)
    assert long["Ky"] > long["Kx"] and long["Kyy"] > long["Kxx"]
    assert ssi.surface_stiffness(50e6, 0.3, 2.0, 6.0) == long  # L is the longer side


def test_embedment_factors_of_a_square_footing() -> None:
    # 2 m square, D = 1.5 m, d = 0.5 m (h = 1.25 m):
    # βx = (1 + 0.21 √0.75) [1 + 1.6 (1.25·0.5·4/8)^0.4] = 1.18187 x 2.00480 = 2.36940
    # βz = [1 + 1.5/42 (2 + 2.6)] [1 + 0.32 (0.5·4/4)^(2/3)] = 1.16429 x 1.20159 = 1.39899
    # βxx = 1 + 2.5·0.25 [1 + 2·0.25 (1/3)^-0.2] = 1 + 0.625 x 1.62287 = 2.01429
    # βyy = 1 + 1.4 (0.25)^0.6 [1.5 + 3.7 (0.25)^1.9 (1/3)^-0.6] = 1 + 0.60939 x 2.01352 = 2.22704
    # βzz = 1 + 2.6 x 2 x 0.25^0.9 = 1 + 5.2 x 0.28717 = 2.49331
    beta = ssi.embedment_factors(2.0, 2.0, 1.5, 0.5)
    assert beta["Kx"] == pytest.approx(2.36940, rel=1e-4)
    assert beta["Ky"] == pytest.approx(2.36940, rel=1e-4)
    assert beta["Kz"] == pytest.approx(1.39899, rel=1e-4)
    assert beta["Kxx"] == pytest.approx(2.01429, rel=1e-4)
    assert beta["Kyy"] == pytest.approx(2.22704, rel=1e-4)
    assert beta["Kzz"] == pytest.approx(2.49331, rel=1e-4)
    assert set(ssi.embedment_factors(2.0, 2.0, 0.0, 0.5).values()) == {1.0}


def test_footing_axes_and_rotation() -> None:
    # A footing 6 m along u, 2 m along v: Ku is the longitudinal Kx, Kv the transverse Ky.
    local, _ = ssi.footing_springs(50e6, 50e6, 0.3, 6.0, 2.0)
    table = ssi.surface_stiffness(50e6, 0.3, 6.0, 2.0)
    assert local[:2] == pytest.approx([table["Kx"], table["Ky"]])
    assert local[3:5] == pytest.approx([table["Kxx"], table["Kyy"]])
    # Turned 90°: u along global Y.
    turned, cross = ssi.to_global(local, 90)
    assert turned[:2] == pytest.approx([local[1], local[0]]) and not cross
    assert ssi.to_global(local, 30)[1]  # cross terms dropped


# ─────────────────────────────── piles ───────────────────────────────


def test_pile_axial_stiffness_limits() -> None:
    # Rigid pile: k = kb + ks L. G = 50 MPa, ν = 0.3, L = 10 m, r0 = 0.25 m:
    # rm = 2.5 x 10 x 0.7 = 17.5 m, ζ = ln(70) = 4.24850, ks = 2π 50e6 / ζ = 73.946e6 N/m²,
    # kb = 4 x 50e6 x 0.25 / 0.7 = 71.429e6 N/m -> k = 739.46e6 + 71.43e6 = 810.89e6 N/m.
    rigid = ssi.pile_axial_stiffness(1e18, 0.19635, 0.25, 10.0, 50e6, 50e6, 0.3)
    assert rigid == pytest.approx(810.89e6, rel=1e-4)
    # Compressible and long: the head of a semi-infinite bar on shaft springs, √(ks EA).
    length = 200.0
    zeta = math.log(2.5 * length * 0.7 / 0.25)
    ks = 2 * math.pi * 50e6 / zeta
    ea = 30e9 * 0.19635
    long = ssi.pile_axial_stiffness(30e9, 0.19635, 0.25, length, 50e6, 50e6, 0.3)
    assert long == pytest.approx(math.sqrt(ks * ea), rel=1e-6)


def test_pile_lateral_stiffness_by_hand() -> None:
    # d = 0.5 m, Ep = 30 GPa: I = π 0.5⁴/64 = 3.0680e-3 m⁴, EI = 92.039e6 N·m²; Es = 60 MPa,
    # ν = 0.3: kB = 0.65 (60e6 x 0.0625 / 92.039e6)^(1/12) x 60e6 / 0.91 = 0.65 x 0.76591 x
    # 65.934e6 = 32.824e6 N/m²; β = (32.824e6 / (4 x 92.039e6))^0.25 = 0.54643 /m;
    # Khh = 4 EI β³ = 60.07e6 N/m, Kθθ = 2 EI β = 100.58e6 N·m/rad.
    k = ssi.pile_lateral_stiffness(30e9, math.pi * 0.5**4 / 64, 0.5, 60e6, 0.3)
    assert k["kB"] == pytest.approx(32.824e6, rel=1e-3)
    assert k["beta"] == pytest.approx(0.54643, rel=1e-3)
    assert k["Khh"] == pytest.approx(60.07e6, rel=2e-3)
    assert k["Ktt"] == pytest.approx(100.58e6, rel=2e-3)


def test_pile_group_cap_stiffness() -> None:
    # Four piles at (±0.75, ±0.75) m, kv = 200 MN/m, Khh = 50 MN/m, Kθθ = 3 MN·m/rad, f = 0.8:
    # Kz = 4 kv = 800e6; Krx = Kry = kv Σy² + 4 Kθθ = 200e6 x 4 x 0.5625 + 12e6 = 462e6;
    # Kx = Ky = 0.8 x 4 x 50e6 = 160e6; Krz = 0.8 x 50e6 x Σ(x² + y²) = 0.8 x 50e6 x 4.5 = 180e6.
    piles = [(-0.75, -0.75), (0.75, -0.75), (0.75, 0.75), (-0.75, 0.75)]
    k = ssi.pile_group_springs(piles, 200e6, 50e6, 3e6, 0.8)
    assert k == pytest.approx([160e6, 160e6, 800e6, 462e6, 462e6, 180e6])


# ─────────────────────────────── models ───────────────────────────────


def test_fixed_leaves_the_model_unchanged() -> None:
    building, d = bay()
    sub = Substructure.model_validate(
        {
            "foundations": [
                {
                    "id": "F1",
                    "type": "isolated",
                    "columns": ["C1"],
                    "length": 2000,
                    "width": 2000,
                    "thickness": 500,
                }
            ]
        }
    )
    before = json.dumps(d.project, sort_keys=True)
    result = ssi.apply_soil_springs(
        d.project, building, sub, SOIL, MATERIALS, options=ssi.SsiOptions(supports="fixed")
    )
    assert json.dumps(result.project, sort_keys=True) == before
    assert result.project is not d.project and not result.foundations
    # Soil springs never change the project they are given.
    ssi.apply_soil_springs(d.project, building, sub, SOIL, MATERIALS, options=springs())
    assert json.dumps(d.project, sort_keys=True) == before


def test_footings_pile_cap_and_the_note_of_columns_without_foundation() -> None:
    from opensees_studio.core.project import Project

    building, d = bay()
    sub = Substructure.model_validate(
        {
            "foundations": [
                {
                    "id": "F1",
                    "type": "isolated",
                    "columns": ["C1"],
                    "length": 2000,
                    "width": 2000,
                    "thickness": 500,
                    "foundingLevel": -1500,
                },
                {
                    "id": "PC",
                    "type": "pileCap",
                    "columns": ["C2", "C3"],
                    "center": [6000, 2500],
                    "length": 2000,
                    "width": 6500,
                    "thickness": 800,
                    "pileType": "P1",
                    "piles": [[0, -2500], [0, 2500]],
                    "foundingLevel": -1500,
                },
            ],
            "pileTypes": [{"id": "P1", "diameter": 500, "length": 15000, "material": "C24.1"}],
        }
    )
    result = ssi.apply_soil_springs(
        d.project, building, sub, SOIL, MATERIALS, ground_level=0, options=springs()
    )
    Project.model_validate(result.project)  # the engine accepts it
    assert result.fixed_columns == ["C4"]
    assert any("no foundation" in n and "C4" in n for n in result.notes)
    f1, cap = result.foundations
    # F1: G = G0 (no acceleration: G/G0 = 1), D = 1.5 m, d = 0.5 m -> surface x β by hand.
    sur = ssi.surface_stiffness(G0, 0.3, 2.0, 2.0)
    beta = ssi.embedment_factors(2.0, 2.0, 1.5, 0.5)
    assert f1.k[2] == pytest.approx(sur["Kz"] * beta["Kz"], rel=2e-3)
    assert f1.k[4] == pytest.approx(sur["Kyy"] * beta["Kyy"], rel=2e-3)
    # The column base is free now, tied to the footing's node 1.5 m below, which is on springs.
    nodes = {n["id"]: n for n in result.project["nodes"]}
    assert nodes[f1.ground]["restraint"] == [True] * 6
    assert nodes[f1.node]["coords"] == [0.0, 0.0, -1.5]
    links = {
        (c["retained_node"], c["constrained_node"])
        for c in result.project["mp_constraints"]
        if c.get("type") == "RigidLinkBeam"
    }
    assert any(r == f1.node for r, _ in links)
    # The cap: two piles 2.5 m either side in Y -> Krx = kv (2 x 2.5²) + 2 Kθθ, Kz = 2 kv.
    kv = cap.k[2] / 2
    assert cap.k[3] - cap.k[4] == pytest.approx(kv * 2 * 2.5**2, rel=1e-9)
    assert len([r for r, _ in links if r == cap.node]) == 2  # both columns tied to the cap


def test_cantilever_on_a_rocking_spring_period(tmp_path: Path) -> None:
    # One 400 x 400 column, h = 3.2 m, on a 2 m square footing founded 1.5 m below its base
    # (arm a = 1.5 m), one mass m = 20 t at its top in X:
    # T = 2π √(m (h³/3EI + 1/Kx + (h + a)²/Kyy)), Kx, Kyy the footing's springs.
    building, d = single_column()
    sub = Substructure.model_validate(
        {
            "foundations": [
                {
                    "id": "F1",
                    "type": "isolated",
                    "columns": ["C1"],
                    "length": 2000,
                    "width": 2000,
                    "thickness": 500,
                    "foundingLevel": -1500,
                }
            ]
        }
    )
    result = ssi.apply_soil_springs(
        d.project, building, sub, SOIL, MATERIALS, acceleration=0.18, options=springs()
    )
    project = result.project
    top = next(n["id"] for n in project["nodes"] if n["coords"] == [0.0, 0.0, 3.2])
    for node in project["nodes"]:
        node["mass"] = [20_000.0, 0, 0, 0, 0, 0] if node["id"] == top else [0.0] * 6
    modal = next(a["id"] for a in project["analyses"] if a["type"] == "Modal")
    _, _, results = run_model(project, tmp_path, [modal])
    period = max(float(p) for p in results[modal].periods)
    k = result.foundations[0].k
    # Kx = 0.55 G0 B/(2-ν) x 4.6 x βx (ASCE 41-06), Kyy likewise: the hand values of the
    # formulas above (G/G0 = 0.55 at 0.18 g).
    g = 0.55 * G0
    assert k[0] == pytest.approx(g * 2 / 1.7 * 4.6 * 2.36940, rel=2e-3)
    assert k[4] == pytest.approx(g * 8 / 0.7 * 0.504 * 2.22704, rel=2e-3)
    ei = E_C * 0.4**4 / 12
    flexibility = 3.2**3 / (3 * ei) + 1 / k[0] + (3.2 + 1.5) ** 2 / k[4]
    assert period == pytest.approx(2 * math.pi * math.sqrt(20_000 * flexibility), rel=0.01)
    fixed = 2 * math.pi * math.sqrt(20_000 * 3.2**3 / (3 * ei))
    assert period > 1.05 * fixed  # the springs lengthen it (by 9.6 % here)


def test_raft_under_a_column_settles_q_over_ks(tmp_path: Path) -> None:
    # A 1.5 m thick 4 x 4 m raft (ks = 20 000 kN/m³ given) under one column with P = 1000 kN:
    # the springs carry P, and the area-weighted mean settlement is P / (ks A) = 1e6 / (2e7 x
    # 16) = 3.125 mm; the thick raft settles nearly uniformly (within 10 % at the column).
    building, d = single_column()
    sub = Substructure.model_validate(
        {
            "foundations": [
                {
                    "id": "R1",
                    "type": "raft",
                    "outline": [[-2000, -2000], [2000, -2000], [2000, 2000], [-2000, 2000]],
                    "thickness": 1500,
                    "foundingLevel": -1500,
                    "material": "C24.1",
                }
            ],
            "design": {"springsFrom": 20000, "raftMeshSize": 500},
        }
    )
    result = ssi.apply_soil_springs(
        d.project, building, sub, SOIL, MATERIALS, acceleration=0.18, options=springs()
    )
    raft = result.foundations[0]
    assert raft.columns == ["C1"] and sum(kv for *_, kv in raft.raft_nodes) == pytest.approx(
        2e7 * 16
    )
    project = result.project
    top = next(n["id"] for n in project["nodes"] if n["coords"] == [0.0, 0.0, 3.2])
    pattern = project["load_patterns"][0]
    pattern["nodal_loads"] = [{"node_id": top, "forces": [0, 0, -1e6, 0, 0, 0]}]
    pattern["element_loads"] = []
    _, out, results = run_model(project, tmp_path, [1])
    reactions = results[1].node_reaction
    total = sum(float(reactions[g][-1][2]) for _, g, _ in raft.raft_nodes)
    assert total == pytest.approx(1e6, rel=1e-6)
    settlements = [float(reactions[g][-1][2]) / kv for _, g, kv in raft.raft_nodes]
    areas = [kv / 2e7 for *_, kv in raft.raft_nodes]
    mean = sum(s * a for s, a in zip(settlements, areas, strict=True)) / 16
    assert mean == pytest.approx(3.125e-3, rel=1e-6)
    base = next(n["id"] for n in project["nodes"] if n["coords"] == [0.0, 0.0, 0.0])
    assert -float(results[1].node_disp[base][-1][2]) == pytest.approx(3.125e-3, rel=0.1)
    # The movements table: force / stiffness per node, the largest at the column.
    from saengine.substructure.loads import case_reactions

    rows = ssi.foundation_movements(result, case_reactions(out), [("P", {"D": 1.0})])
    assert rows[0]["settlement"] == pytest.approx(max(settlements) * 1e3, abs=0.01)


def test_movements_are_force_over_stiffness() -> None:
    info = {
        "nodes": {
            "F1": {
                "node": 5,
                "ground": 9,
                "elements": [3],
                "k": [1e8, 1e8, 2e8, 3e8, 3e8, 4e8],
                "raftNodes": [],
            }
        }
    }
    # The ground node's reaction 400 kN up, 50 kN in X: settlement 400e3/2e8 = 2 mm, the
    # foundation moves -50e3/1e8 = -0.5 mm in X; 1.5 x D.
    cases = {"D": {9: np.array([50e3, 0, 400e3, 0, 3e5, 0]) / 1.5}}
    row = ssi.foundation_movements(info, cases, [("1.5D", {"D": 1.5})])[0]
    assert row["settlement"] == pytest.approx(2.0)
    assert row["ux"] == pytest.approx(-0.5)
    assert row["ry"] == pytest.approx(-1e-3)


def test_fixed_and_ssi_models_compared(tmp_path: Path) -> None:
    # The bay on four isolated footings: both models from one call; on springs the periods
    # lengthen, the equivalent static base shear is the same (the same story forces) and the
    # drifts grow (the bases move and rock).
    building = generate(BAY, "s")
    footings = [
        {
            "id": f"F{c}",
            "type": "isolated",
            "columns": [f"C{c}"],
            "length": 1500,
            "width": 1500,
            "thickness": 450,
            "foundingLevel": -1200,
        }
        for c in range(1, 5)
    ]
    sub = Substructure.model_validate({"foundations": footings})
    settings = default_project_settings("Bay")
    fixed, result = ssi.fixed_and_ssi(building, OBJECTS, MATERIALS, settings, sub, SOIL)
    assert [f.foundation for f in result.foundations] == ["F1", "F2", "F3", "F4"]
    summaries = []
    for name, project in (("fixed", fixed.project), ("ssi", result.project)):
        cases = [
            a["id"] for a in project["analyses"] if a["type"] == "Modal" or a["name"][:2] == "EX"
        ]
        _, out, _ = run_model(project, tmp_path / name, cases)
        summaries.append(ssi.response_summary(project, out, ssi.storey_levels(building)))
    compared = ssi.compare_responses(*summaries)
    assert compared["periods"][0]["ratio"] > 1.0
    (shear,) = [row for row in compared["baseShear"] if row["case"] == "EX"]
    assert shear["ssi"] == pytest.approx(shear["fixed"], rel=1e-6) and shear["fixed"] > 0
    (drift,) = [row for row in compared["drift"] if row["case"] == "EX"]
    assert drift["ssi"] > drift["fixed"] > 0
    rows = [row for row in compared["storeyDrift"] if row["case"] == "EX"]
    levels = ssi.storey_levels(building)
    assert [row["level"] for row in rows] == levels[1 : len(rows) + 1] and rows
    assert rows[0]["ssi"] > rows[0]["fixed"] > 0  # the first storey: the bases move and rock


def test_drifts_only_at_storey_levels() -> None:
    # Storeys at 0, 3.2 and 6.4 m. Wall-mesh rows at 2.20 and 2.23 m (a 3 cm gap with a large
    # relative movement) and a footing node at -0.5 m are not storeys. Base nodes 1, 2 move
    # 1 mm (soil springs); 3.2 m: 7 and 9 mm -> mean 8 mm; 6.4 m: 20 mm.
    # Hand: (8 - 1) / 3200 = 2.1875e-3 and (20 - 8) / 3200 = 3.75e-3.
    z_of = {1: 0.0, 2: 0.0, 3: 2.2, 4: 2.23, 5: 3.2, 6: 3.2, 7: 6.4, 8: -0.5}
    disp = {1: 1e-3, 2: 1e-3, 3: 0.0, 4: 5e-3, 5: 7e-3, 6: 9e-3, 7: 20e-3, 8: 0.5e-3}
    rows = ssi.storey_drifts(z_of, disp, [0.0, 3.2, 6.4])
    assert [z for z, _ in rows] == [3.2, 6.4]
    assert rows[0][1] == pytest.approx(7e-3 / 3.2)
    assert rows[1][1] == pytest.approx(12e-3 / 3.2)
    # A fixed base: the supports are not in the results' displacements, so they count as 0.
    rows = ssi.storey_drifts({1: 0.0, 5: 3.2}, {5: 6.4e-3}, [0.0, 3.2])
    assert rows == [(3.2, pytest.approx(2e-3))]
