"""B20: the pushover's target displacement (coefficient method), fibre walls and member
acceptance, with the values of the bnbc2020 pack (BNBC 2020 Part 6 Sec 2.5.12)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from saengine.codes.tables import builtin_table
from saengine.fem import acceptance as acc
from saengine.fem import pushover_target as pt
from saengine.fem.nonlinear import (
    FiberMaterials,
    WallSpec,
    fibre_walls,
    mode_forces,
    wall_fiber_section,
)
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.settings import Pushover

PACK = builtin_table("pushover")
MATERIALS = default_material_library()
BY_ID = {m.id: m for m in MATERIALS.materials}
CONCRETE = next(m for m in MATERIALS.materials if m.category.value == "concrete")
REBAR = next(m for m in MATERIALS.materials if m.category.value == "rebar")


# ── the pack ──


def test_pack_values() -> None:
    procedure, target, rule = PACK.procedure, PACK.targetDisplacement, PACK.acceptance
    # Sec 2.5.12.2: first-mode pattern, push to 150 % of δt, no drop up to 125 % (p. 642).
    assert procedure.loadPattern == "firstMode"
    assert procedure.pushToTarget == 1.5
    assert procedure.noDropToTarget == 1.25
    assert procedure.pDelta is True  # Sec 2.5.12.1
    # Sec 2.5.12.3: bilinear fit at 60 % of Vy; Sa of Eq 6.2.34 with R = I = 1 (Sec 2.5.4.3);
    # C1 = 1 above TC; Ts of Eq 6.2.54 read as TC (p. 643).
    assert target.method == "coefficient"
    assert target.bilinearFitShare == 0.6
    assert (target.spectrumR, target.spectrumImportance) == (1.0, 1.0)
    assert (target.c1PeriodLimit, target.c1Period) == ("TC", "TC")
    assert target.minimumRd == 1.0
    # Sec 2.5.12.4: 2/3 of the deformation at gravity loss or at 70 % strength (p. 644).
    assert rule.method == "fibreStrain"
    assert rule.deformationShare == pytest.approx(2 / 3, abs=1e-6)
    assert rule.residualStrengthShare == 0.7
    assert rule.reinforcementFractureStrain == 0.06  # SAEngine practice, labelled in the pack
    assert "not BNBC" in rule.note
    for key in ("target", "period", "c0", "c1", "rd", "pushTo", "noDrop", "acceptance"):
        assert "2.5.12" in PACK.sources[key]


def test_settings_default_to_the_first_mode_and_fibre_walls() -> None:
    options = Pushover()
    assert options.pattern == "firstMode" and options.fibreWalls is True


# ── the bilinear fit and the factors ──


def epp(k: float, vy: float, top: float, n: int = 400) -> tuple[np.ndarray, np.ndarray]:
    """An elastic-perfectly plastic capacity curve to ``top``."""
    d = np.linspace(0.0, top, n + 1)
    return d, np.minimum(k * d, vy)


def test_bilinear_fit_of_an_elastic_plastic_curve() -> None:
    d, v = epp(1e7, 2e5, 0.2)
    fit = pt.bilinear_fit(d, v, 0.1, 0.6)
    assert fit["Ke"] == pytest.approx(1e7, rel=1e-6)
    assert fit["Vy"] == pytest.approx(2e5, rel=1e-4)
    assert fit["dy"] == pytest.approx(0.02, rel=1e-4)
    assert not fit["elastic"]


def test_bilinear_fit_keeps_the_area_and_meets_the_curve_at_60_percent() -> None:
    d = np.linspace(0, 0.3, 601)
    v = 3e5 * (1 - np.exp(-d / 0.03))  # smoothly softening
    target = 0.15
    fit = pt.bilinear_fit(d, v, target, 0.6)
    vy, dy, vt = fit["Vy"], fit["dy"], fit["Vt"]
    bilinear = 0.5 * vy * dy + 0.5 * (vy + vt) * (target - dy)
    inside = d <= target
    assert bilinear == pytest.approx(np.trapezoid(v[inside], d[inside]), rel=1e-3)
    # The first segment passes through the curve at 0.6 Vy.
    at = np.interp(0.6 * vy, v, d)
    assert 0.6 * vy / at == pytest.approx(fit["Ke"], rel=1e-3)
    assert vt == pytest.approx(np.interp(target, d, v), rel=1e-6)


def test_c0_of_a_linear_shape() -> None:
    # Eq 6.2.53: C0 = Σwφ / Σwφ², three equal storeys and a straight shape.
    assert pt.c0_factor([1, 1, 1], [1 / 3, 2 / 3, 1]) == pytest.approx(2 / (14 / 9))
    assert pt.c0_factor([5.0], [1.0]) == 1.0


def test_c1() -> None:
    # Eq 6.2.54: C1 = [1 + (Rd - 1) Ts/Te] / Rd for Te <= TC; 1 above TC.
    assert pt.c1_factor(0.5, 2.5, 0.8, 0.8) == pytest.approx((1 + 1.5 * 0.8 / 0.5) / 2.5)
    assert pt.c1_factor(1.2, 2.5, 0.8, 0.8) == 1.0
    assert pt.c1_factor(0.5, 1.0, 0.8, 0.8) == 1.0


def sdof(t1: float, sa: float) -> dict:
    """An elastic-plastic structure of weight 1000 kN with period ``t1``, Vy = 200 kN, C0 = 1.2,
    under a flat spectrum ``sa``."""
    k = 1e6 / 9.80665 * (2 * math.pi / t1) ** 2
    d, v = epp(k, 2e5, 0.4, 4000)
    return pt.coefficient(
        d,
        v,
        t1=t1,
        c0=1.2,
        weight=1e6,
        spectrum=lambda t: sa,
        corners={"TB": 0.2, "TC": 0.8, "TD": 2.0},
        rule=PACK.targetDisplacement,
    )


def test_target_displacement_of_a_short_period_structure() -> None:
    found = sdof(0.5, 0.5)
    # The bilinear fit is the curve itself: Te = T1 (Eq 6.2.51).
    assert found["Te"] == pytest.approx(0.5, rel=1e-6)
    # Eq 6.2.55: Rd = Sa / (Vy/W) = 0.5 / 0.2; Eq 6.2.54 with Ts = TC = 0.8 s.
    rd = 0.5 / 0.2
    c1 = (1 + (rd - 1) * 0.8 / 0.5) / rd
    assert found["Rd"] == pytest.approx(rd, rel=1e-4)
    assert found["C1"] == pytest.approx(c1, rel=1e-4)
    # Eq 6.2.52: δt = C0 C1 Sa (Te/2π)² g.
    expected = 1.2 * c1 * 0.5 * (0.5 / (2 * math.pi)) ** 2 * 9.80665
    assert found["target"] == pytest.approx(expected, rel=1e-4)
    assert found["converged"] and not found["beyondCurve"]


def test_target_displacement_above_tc_has_c1_one() -> None:
    found = sdof(1.0, 0.3)
    assert found["C1"] == 1.0
    assert found["target"] == pytest.approx(
        1.2 * 0.3 * (1.0 / (2 * math.pi)) ** 2 * 9.80665, rel=1e-4
    )


def test_target_displacement_of_an_elastic_structure_has_rd_one() -> None:
    # Vy/W = 0.2 above Sa = 0.1: Rd < 1 is taken as 1 (C1 = 1).
    found = sdof(0.3, 0.1)
    assert found["Rd"] == 1.0 and found["C1"] == 1.0


def test_target_beyond_the_curve_is_flagged() -> None:
    d, v = epp(1e7, 2e5, 0.01, 50)
    found = pt.coefficient(
        d,
        v,
        t1=2.0,
        c0=1.3,
        weight=1e6,
        spectrum=lambda t: 0.5,
        corners={"TB": 0.2, "TC": 0.8, "TD": 2.0},
        rule=PACK.targetDisplacement,
    )
    assert found["beyondCurve"]


def test_capacity_checks() -> None:
    d = np.linspace(0, 0.2, 201)
    v = np.minimum(1e7 * d, 2e5)
    v[150:] -= 1e4 * (np.arange(51))  # drops after 0.15 m
    ok = pt.capacity_checks(d, v, 0.1, 1.5, 1.25)
    assert ok["reached"] and ok["noDrop"] is True and ok["targetStep"] == 100
    late = pt.capacity_checks(d, v, 0.13, 1.5, 1.25)
    # 1.25 × 0.13 = 0.1625 m > 0.15 m where the shear drops; 1.5 × 0.13 = 0.195 m reached.
    assert late["noDrop"] is False and late["dropAt"] == pytest.approx(0.151)
    short = pt.capacity_checks(d, v, 0.15, 1.5, 1.25)
    assert not short["reached"]


# ── the first-mode load pattern ──


def test_mode_forces_follow_the_mode_with_the_largest_mass_in_x() -> None:
    nodes = [
        {"id": 1, "mass": [10.0, 10.0, 0, 0, 0, 0]},
        {"id": 2, "mass": [20.0, 20.0, 0, 0, 0, 0]},
    ]
    shapes = {
        1: {1: [0.0, -0.5, 0, 0, 0, 0], 2: [0.0, -1.0, 0, 0, 0, 0]},  # Y
        2: {1: [-0.4, 0.0, 0, 0, 0, 0], 2: [-1.0, 0.0, 0, 0, 0, 0]},  # X, sign flipped
    }
    forces = mode_forces(nodes, shapes, ["X", "Y"])
    # m·φ, pushing the positive way, largest = the heaviest node's weight.
    assert forces["X"][2] == pytest.approx(20 * 9.80665)
    assert forces["X"][1] / forces["X"][2] == pytest.approx(10 * 0.4 / (20 * 1.0))
    assert forces["Y"][1] / forces["Y"][2] == pytest.approx(0.25)


# ── fibre walls ──

WALL_TYPE = ObjectLibrary.model_validate(
    {
        "objects": [
            {
                "id": "WL",
                "name": "Shear wall 200",
                "kind": "wall",
                "material": CONCRETE.id,
                "thickness": 200,
                "reinforcement": {
                    "material": REBAR.id,
                    "cover": 25,
                    "vertical": {"dia": 12, "spacing": 200},
                    "boundary": {
                        "length": 500,
                        "count": 8,
                        "dia": 20,
                        "hoop": {"dia": 10, "spacing": 100},
                    },
                },
            }
        ]
    }
).objects[0]


def test_wall_fiber_section() -> None:
    library = FiberMaterials()
    section = wall_fiber_section(1, "W", WALL_TYPE, 3.0, BY_ID, library)
    assert section is not None
    bars = section["fibres"]
    area = sum(f["area"] for f in bars)
    # Two ends of 8 bars of 20 mm, and the web: 2 m between the boundary zones at 200 mm in two
    # layers, the first a spacing in (9 positions).
    boundary, web = 16 * math.pi * 0.02**2 / 4, 2 * 9 * math.pi * 0.012**2 / 4
    assert area == pytest.approx(boundary + web)
    # Length along local z, thickness along local y.
    assert max(abs(f["z"]) for f in bars) < 1.5 and max(abs(f["y"]) for f in bars) < 0.1
    names = {m["name"].split()[-1] for m in library.materials}
    assert names == {REBAR.id, "cover", "core", "web"}
    # The concrete patches cover the whole section.
    concrete = sum((p["y_j"] - p["y_i"]) * (p["z_j"] - p["z_i"]) for p in section["patches"])
    assert concrete == pytest.approx(3.0 * 0.2)
    assert section["shear"] > 0


def wall_project() -> dict:
    """A 2 m wall meshed into 2 x 2 shells over one 3 m storey: fixed base, a floor node at
    each end of its top tied by a diaphragm, a beam on its top right corner."""
    nodes = []
    coords = {}
    k = 0
    for z in (0.0, 1.5, 3.0):
        for x in (0.0, 1.0, 2.0):
            k += 1
            coords[k] = (x, 0.0, z)
            nodes.append(
                {
                    "id": k,
                    "coords": [x, 0.0, z],
                    "mass": [100.0 if z == 1.5 else 0.0] * 2 + [0.0] * 4,
                    "restraint": [z == 0.0] * 6,
                }
            )
    nodes.append({"id": 10, "coords": [5.0, 0.0, 3.0], "mass": [0.0] * 6, "restraint": [False] * 6})
    shells = [(1, 2, 5, 4), (2, 3, 6, 5), (4, 5, 8, 7), (5, 6, 9, 8)]
    elements = [
        {"id": i + 1, "name": "W1" if i == 0 else f"W1#{i + 1}", "type": "Shell", "nodes": list(s)}
        for i, s in enumerate(shells)
    ]
    elements.append({"id": 9, "name": "B1", "type": "ElasticBeamColumn", "nodes": [9, 10]})
    return {
        "nodes": nodes,
        "elements": elements,
        "sections": [],
        "materials": [],
        "mp_constraints": [
            {"type": "RigidDiaphragm", "retained_node": 8, "constrained_nodes": [7, 9]}
        ],
        "load_patterns": [
            {"id": 1, "name": "D", "nodal_loads": [{"node_id": 5, "forces": [0, 0, -10, 0, 0, 0]}]}
        ],
    }


def test_fibre_walls_replace_the_shells() -> None:
    project = wall_project()
    notes: list[str] = []
    walls = [WallSpec("W1", "WL", (0.0, 0.0), (2.0, 0.0))]
    count, moved = fibre_walls(project, walls, {"WL": WALL_TYPE}, BY_ID, FiberMaterials(), notes)
    assert count == 1
    elements = project["elements"]
    assert not any(e["type"] == "Shell" for e in elements)
    (wall,) = [e for e in elements if e["type"] == "ForceBeamColumn"]
    assert wall["name"] == "W1" and wall["vecxz"] == [1.0, 0.0, 0.0]
    # The centre nodes: the base's (a mesh node, fixed) and the top's (a mesh node too).
    assert wall["nodes"] == [2, 8]
    # Rigid arms from the centres to the other nodes shared with the model.
    arms = sorted(tuple(e["nodes"]) for e in elements if e["name"] == "W1/arm")
    assert arms == [(2, 1), (2, 3), (8, 7), (8, 9)]
    # The mid-height nodes go: their load and mass move to the nearest centre (a tie: the
    # first height, the base).
    assert set(moved) == {4, 5, 6}
    assert {n["id"] for n in project["nodes"]} == {1, 2, 3, 7, 8, 9, 10}
    (load,) = project["load_patterns"][0]["nodal_loads"]
    assert load["node_id"] == moved[5] and load["forces"][2] == -10
    section = next(s for s in project["sections"] if s["id"] == wall["section_id"])
    assert section["type"] == "SectionAggregator"
    assert {p["dof"] for p in section["pairings"]} == {"Vy", "Vz"}


def test_walls_with_openings_stay_shells() -> None:
    project = wall_project()
    notes: list[str] = []
    walls = [WallSpec("W1", "WL", (0.0, 0.0), (2.0, 0.0), openings=True)]
    count, _ = fibre_walls(project, walls, {"WL": WALL_TYPE}, BY_ID, FiberMaterials(), notes)
    assert count == 0 and any("openings" in n for n in notes)
    assert sum(e["type"] == "Shell" for e in project["elements"]) == 4


# ── acceptance ──


def test_concrete_failure_strains() -> None:
    material = {"fpc": -30e6, "epsc0": -0.002, "fpcu": -6e6, "epsU": -0.02}
    strength, crushed = acc.concrete_failure_strains(material, 0.7)
    # On the line from (0.002, 30) to (0.02, 6): 21 MPa at 0.002 + 0.3/0.8 × 0.018.
    assert strength == pytest.approx(0.002 + 0.3 / 0.8 * 0.018)
    assert crushed == 0.02
    # Unconfined cover: drops to zero at 0.006; 70 % at 0.002 + 0.3 × 0.004.
    plain = {"fpc": -30e6, "epsc0": -0.002, "fpcu": 0.0, "epsU": -0.006}
    assert acc.concrete_failure_strains(plain, 0.7)[0] == pytest.approx(0.0032)


def test_fibre_strain_acceptance() -> None:
    materials = [
        {"id": 1, "name": "C core", "type": "Concrete02", "fpc": -30e6, "epsc0": -0.002,
         "fpcu": -6e6, "epsU": -0.02},
        {"id": 2, "name": "C cover", "type": "Concrete02", "fpc": -30e6, "epsc0": -0.002,
         "fpcu": 0.0, "epsU": -0.006},
        {"id": 3, "name": "R", "type": "Steel02", "Fy": 420e6},
    ]  # fmt: skip
    section = {
        "id": 1,
        "type": "FiberSection",
        "patches": [
            {"kind": "rect", "material_id": 1, "n_fib_y": 1, "n_fib_z": 1},
            {"kind": "rect", "material_id": 2, "n_fib_y": 1, "n_fib_z": 1},
        ],
        "fibres": [{"y": 0, "z": 0, "area": 1e-4, "material_id": 3}],
    }
    project = {
        "materials": materials,
        "sections": [section],
        "nodes": [{"id": 1, "coords": [0, 0, 0]}, {"id": 2, "coords": [0, 0, 3]}],
        "elements": [
            {"id": 7, "name": "C1#2", "type": "ForceBeamColumn", "nodes": [1, 2], "section_id": 1}
        ],
    }
    # Step 1: core at -0.004, cover at -0.01 (spalled, not checked), bar at 0.03.
    fibres = np.zeros((2, 3, 5))
    fibres[1, :, 4] = [-0.004, -0.01, 0.03]
    results = SimpleNamespace(element_start_fibers={7: fibres}, element_end_fibers={})
    (row,) = acc.fibre_strain(project, results, 1, PACK.acceptance)
    share = PACK.acceptance.deformationShare
    core = share * (0.002 + 0.3 / 0.8 * 0.018)
    bar = share * 0.06
    assert row["member"] == "C1" and row["end"] == "i" and row["gravity"]
    # The bar governs: 0.03 / (2/3 × 0.06) = 0.75 against 0.004 / (2/3 × 0.00875) = 0.69.
    assert row["fibre"] == "bar" and row["ratio"] == pytest.approx(0.03 / bar)
    assert 0.004 / core < row["ratio"] and row["ok"]
    fibres[1, 0, 4] = -0.007
    (row,) = acc.fibre_strain(project, results, 1, PACK.acceptance)
    assert row["fibre"] == "concrete" and not row["ok"]


def test_derived_pushover_model_of_a_wall_building(tmp_path: Path) -> None:
    """The two-storey bay of test_fem_shells with a reinforced wall (no door): the wall becomes
    fibre wall elements and the gravity load of the pushover model keeps its total."""
    import test_fem_shells as shells
    from test_fem_pushover import reinforced

    from saengine.fem.derive import derive_fem
    from saengine.library.bim import generate

    objects = ObjectLibrary.model_validate(
        {
            "objects": [
                {"id": "COL", "name": "Column", **reinforced("column", 0, 0, 8)}
                | {"profile": {"shape": "rectangle", "xDim": 400, "yDim": 400}},
                {"id": "BM", "name": "Beam", **reinforced("beam", 3, 3)},
                {"id": "SL", "name": "Slab", "kind": "slab", "material": CONCRETE.id,
                 "thickness": 150},
                WALL_TYPE.model_dump(mode="json"),
                {"id": "PW", "name": "Partition", "kind": "wall", "material": CONCRETE.id,
                 "thickness": 125, "structural": False},
            ]
        }
    )  # fmt: skip
    settings = shells.settings(pushover=Pushover(directions=["X"], pattern="seismic"))
    d = derive_fem(generate(shells.PLAN, "s"), objects, MATERIALS, settings, None, tmp_path)
    model = d.pushover
    assert model is not None
    walls = [e for e in model["elements"] if e["name"].split("#")[0] == "W1"]
    assert walls and {e["type"] for e in walls} == {"ForceBeamColumn"}
    assert any("fibre wall" in n for n in d.notes)

    def vertical(project: dict, factors: dict[str, float]) -> float:
        total = 0.0
        for pattern in project["load_patterns"]:
            factor = factors.get(pattern["name"])
            if factor:
                total += factor * sum(load["forces"][2] for load in pattern["nodal_loads"])
        return total

    # The nodal loads of the wall's dropped nodes moved to its centre nodes, none lost.
    linear = vertical(d.project, {"D": 1.0, "SD": 1.0, "L": 0.25})
    assert vertical(model, {"G": 1.0}) == pytest.approx(linear, rel=1e-6)

    from opensees_studio.services.persistence import load_project

    path = tmp_path / "pushover.osmodel"
    path.write_text(json.dumps(model), encoding="utf-8")
    load_project(str(path)).validate_references()
