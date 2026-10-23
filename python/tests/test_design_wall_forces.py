"""Wall pier and spandrel forces from the shell model (saengine.design.wall_forces).

Synthetic walls, checked by statics: a cantilever wall under a load along its top (in plane
and out of plane: V and M at the base), a wall with a door split into two piers whose shears
sum to the load, gravity (P = the wall's weight plus the load on top), and on the shipped
sample the storey shear carried by the wall's piers and the columns together.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from saengine.design.wall_forces import (
    case_shell_forces,
    wall_forces,
    wall_piers,
)
from saengine.fem.combinations import DesignCombination
from saengine.fem.derive import derive_fem
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import BuildingModel
from saengine.library.settings import default_project_settings

OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            {"id": "W", "name": "Wall 200", "kind": "wall", "material": "C24.1", "thickness": 200}
        ]
    }
)
HEIGHT = 3.0  # m
LOAD = 100e3  # N, the load along the top
WX = DesignCombination("WX", {"WX": 1.0})
WY = DesignCombination("WY", {"WY": 1.0})
D = DesignCombination("D", {"D": 1.0})
#: The cases of the derived model the tests run: D, WX, WY.
CASES = {"D": 1, "WX": 5, "WY": 6}


def building(
    length: float = 4000, openings: list[dict] | None = None, storeys: int = 1
) -> BuildingModel:
    """A wall from the base to the top (HEIGHT), drawn as one element over ``storeys``."""
    return BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                *(
                    {"id": f"L{k}", "name": f"Level {k}", "elevation": HEIGHT * 1e3 * k / storeys}
                    for k in range(1, storeys + 1)
                ),
            ],
            "elements": [
                {
                    "id": "W1",
                    "type": "W",
                    "kind": "wall",
                    "start": [0, 0],
                    "end": [length, 0],
                    "bottom": 0,
                    "top": HEIGHT * 1e3,
                }
            ],
            "additions": {"wallOpenings": openings or []},
        }
    )


def analysed(
    root: Path, model: BuildingModel, top_load: float = 0.0, ends: bool = False
) -> tuple[dict, Path]:
    """The derived model with LOAD along X in WX and along Y in WY, spread over the top
    nodes (``ends``: half on each top corner; ``top_load`` downwards in D too), run for D, WX
    and WY."""
    settings = default_project_settings("walls")
    settings = settings.model_copy(
        update={"analysis": settings.analysis.model_copy(update={"meshSize": 500})}
    )
    project = derive_fem(model, OBJECTS, default_material_library(), settings, {"bim": "x"}).project
    # A bare cantilever: no floor diaphragm ties the top nodes (its master node held).
    used = {n for e in project["elements"] for n in e["nodes"]}
    masters = {c["retained_node"] for c in project["mp_constraints"]} - used
    project["mp_constraints"] = []
    for n in project["nodes"]:
        if n["id"] in masters:
            n["restraint"] = [True] * 6
    top = [
        n["id"]
        for n in project["nodes"]
        if abs(n["coords"][2] - HEIGHT) < 1e-6 and n["id"] not in masters
    ]
    # The end nodes take half a share (a uniform load along the top edge).
    xs = sorted(n["coords"][0] for n in project["nodes"] if n["id"] in top)
    corners = {min(xs), max(xs)}
    share = {
        n["id"]: (0.5 if n["coords"][0] in corners else (0.0 if ends else 1.0))
        for n in project["nodes"]
        if n["id"] in top
    }
    total = sum(share.values())
    patterns = {p["name"]: p for p in project["load_patterns"]}
    # Only the test's loads in WX and WY (the derived wind on the wall is left out).
    patterns["WX"]["nodal_loads"] = []
    patterns["WY"]["nodal_loads"] = []
    for name, axis, value in (("WX", 0, LOAD), ("WY", 1, LOAD), ("D", 2, -top_load)):
        if not value:
            continue
        for node, k in share.items():
            forces = [0.0] * 6
            forces[axis] = value * k / total
            patterns[name]["nodal_loads"].append({"node_id": node, "forces": forces})
    path = root / "model.osmodel"
    path.write_text(json.dumps(project), encoding="utf-8")
    out = root / "model.results"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(path),
            "--cases",
            *map(str, CASES.values()),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    return project, out


def dead_load(project: dict, where=lambda z: True) -> float:
    """The dead load [N] of the model's nodes at heights ``where`` (the derived self weight
    and the test's load on top)."""
    z = {n["id"]: n["coords"][2] for n in project["nodes"]}
    pattern = next(p for p in project["load_patterns"] if p["name"] == "D")
    return -sum(load["forces"][2] for load in pattern["nodal_loads"] if where(z[load["node_id"]]))


@pytest.fixture(scope="module")
def solid(tmp_path_factory: pytest.TempPathFactory):
    model = building()
    project, out = analysed(tmp_path_factory.mktemp("solid-wall"), model, top_load=LOAD)
    return model, project, out


@pytest.fixture(scope="module")
def door(tmp_path_factory: pytest.TempPathFactory):
    # A 6 m wall with a 1.5 m wide, 2.2 m high door 2 m from its start.
    opening = {"id": "D1", "host": "W1", "offset": 2000, "width": 1500, "height": 2200}
    model = building(6000, [opening])
    # The load at the top corners, so that none is on the spandrel itself.
    project, out = analysed(tmp_path_factory.mktemp("door-wall"), model, ends=True)
    return model, project, out


def test_cantilever_wall_in_plane_by_statics(solid) -> None:
    model, project, out = solid
    piers = wall_piers(project, model, out, [WX])
    assert len(piers) == 1
    pier = piers[0]
    assert pier["pier"] == "W1/L1/P1" and pier["storey"] == "L1"
    assert pier["label"] == "Base to Level 1"
    assert pier["lw"] == pytest.approx(4000) and pier["tw"] == pytest.approx(200)
    assert pier["centre"] == pytest.approx([2000, 0])
    assert pier["axes"] == [[0, 0, 1], [1, 0, 0], [0, 1, 0]]
    assert not pier["spandrels"] and len(pier["shells"]) == len(
        [e for e in project["elements"] if e["type"] == "Shell"]
    )
    load = LOAD / 1e3  # kN
    for cut, arm in (("bottom", HEIGHT), ("middle", HEIGHT / 2), ("top", 0.0)):
        f = pier["cuts"][cut]["WX"]
        # The part above pushes the part below along +X: V2 = H, M3 = H·(lever arm), the end
        # side (+X) compressed at the base; nothing out of plane, no axial force.
        assert f["V2"] == pytest.approx(load, rel=1e-6), cut
        assert f["M3"] == pytest.approx(load * arm, rel=1e-6, abs=1e-6 * load), cut
        assert abs(f["P"]) < 1e-6 * load and abs(f["V3"]) < 1e-6 * load
        assert abs(f["M2"]) < 1e-6 * load and abs(f["T"]) < 1e-6 * load


def test_cantilever_wall_out_of_plane_by_statics(solid) -> None:
    model, project, out = solid
    pier = wall_piers(project, model, out, [WY])[0]
    load = LOAD / 1e3
    for cut, arm in (("bottom", HEIGHT), ("middle", HEIGHT / 2)):
        f = pier["cuts"][cut]["WY"]
        # Along +Y (local 3): V3 = H; M = (h e_z) x (H e_y) = -H h e_x, so M2 = -H h (the
        # +3 face, pushed away from, in tension at the base).
        assert f["V3"] == pytest.approx(load, rel=1e-6), cut
        assert f["M2"] == pytest.approx(-load * arm, rel=1e-6), cut
        assert abs(f["V2"]) < 1e-6 * load and abs(f["M3"]) < 1e-6 * load * HEIGHT
        assert abs(f["T"]) < 1e-6 * load


def test_gravity_axial_force_is_the_self_weight_and_the_load(solid) -> None:
    model, project, out = solid
    pier = wall_piers(project, model, out, [D])[0]
    load = LOAD / 1e3
    weight = dead_load(project) / 1e3 - load  # the derived self weight [kN]
    # By hand: 4 m x 3 m x 0.2 m of 24 kN/m³ concrete (C24.1 density 2400 kg/m³).
    assert weight == pytest.approx(4 * 3 * 0.2 * 2400 * 9.80665 / 1e3, rel=0.01)
    cuts = pier["cuts"]
    # Compression positive. The self weight is lumped at the nodes: at the base the weight of
    # the nodes above it (the base nodes' share goes straight into the support), at the top
    # the load and the top nodes' share, half the wall between.
    above_base = dead_load(project, lambda z: z > 1e-6) / 1e3
    on_top = dead_load(project, lambda z: z > HEIGHT - 1e-6) / 1e3
    assert cuts["bottom"]["D"]["P"] == pytest.approx(above_base, rel=1e-6)
    assert cuts["top"]["D"]["P"] == pytest.approx(on_top, rel=1e-6)
    assert cuts["bottom"]["D"]["P"] == pytest.approx(load + weight, rel=0.05)
    assert cuts["top"]["D"]["P"] == pytest.approx(load, rel=0.05)
    assert cuts["middle"]["D"]["P"] == pytest.approx(load + weight / 2, rel=0.05)
    for cut in cuts.values():
        assert abs(cut["D"]["M3"]) < 1e-3 * load and abs(cut["D"]["V2"]) < 1e-6 * load


@pytest.fixture(scope="module")
def two_storeys(tmp_path_factory: pytest.TempPathFactory):
    # One wall element over two storeys of 1.5 m: no line of nodes need run along the level.
    model = building(storeys=2)
    project, out = analysed(tmp_path_factory.mktemp("two-storeys"), model)
    return model, project, out


def test_wall_over_two_storeys_has_a_pier_in_each(two_storeys) -> None:
    model, project, out = two_storeys
    piers = {p["pier"]: p for p in wall_piers(project, model, out, [WX])}
    assert set(piers) == {"W1/L1/P1", "W1/L2/P1"}
    lower, upper = piers["W1/L1/P1"], piers["W1/L2/P1"]
    assert (lower["bottom"], lower["top"], upper["bottom"], upper["top"]) == (0, 1500, 1500, 3000)
    assert lower["label"] == "Base to Level 1" and upper["label"] == "Level 1 to Level 2"
    assert not set(lower["shells"]) & set(upper["shells"])
    load = LOAD / 1e3
    # By statics, the load at the top (3 m): M3 = H x the height above the cut.
    for pier, cut, arm in (
        (lower, "bottom", 3.0),
        (lower, "middle", 2.25),
        (lower, "top", 1.5),
        (upper, "bottom", 1.5),
        (upper, "middle", 0.75),
        (upper, "top", 0.0),
    ):
        f = pier["cuts"][cut]["WX"]
        assert f["V2"] == pytest.approx(load, rel=1e-6), (pier["pier"], cut)
        assert f["M3"] == pytest.approx(load * arm, rel=1e-6, abs=1e-6 * load), (pier["pier"], cut)


def test_combinations_are_the_factored_sums(solid) -> None:
    model, project, out = solid
    both = DesignCombination("1.2D + 1.6WX", {"D": 1.2, "WX": 1.6})
    pier = wall_piers(project, model, out, [D, WX, both])[0]
    for cut, by in pier["cuts"].items():
        for k in ("P", "V2", "V3", "T", "M2", "M3"):
            expected = 1.2 * by["D"][k] + 1.6 * by["WX"][k]
            assert by["1.2D + 1.6WX"][k] == pytest.approx(expected, abs=1e-9), (cut, k)


def test_missing_case_is_noted_not_raised(solid) -> None:
    model, project, out = solid
    found = wall_forces(project, model, out, [DesignCombination("EX", {"EX": 1.0}), WX])
    assert "EX" not in found["piers"][0]["cuts"]["bottom"]
    assert any("EX" in n for n in found["notes"])
    rs = DesignCombination("1.2D + E", {"D": 1.2}, {"RX": 1.0})
    found = wall_forces(project, model, out, [rs])
    assert any("modal-force run" in n for n in found["notes"])


def test_wall_with_a_door_splits_into_two_piers_and_a_spandrel(door) -> None:
    model, project, out = door
    found = wall_forces(project, model, out, [WX, D])
    piers = {p["pier"]: p for p in found["piers"]}
    assert set(piers) == {"W1/L1/P1", "W1/L1/P2"}
    p1, p2 = piers["W1/L1/P1"], piers["W1/L1/P2"]
    assert (p1["start"], p1["end"], p1["lw"]) == (0, 2000, 2000)
    assert (p2["start"], p2["end"], p2["lw"]) == (3500, 6000, 2500)
    assert p1["centre"] == pytest.approx([1000, 0]) and p2["centre"] == pytest.approx([4750, 0])
    (spandrel,) = found["spandrels"]
    assert spandrel["spandrel"] == "W1/L1/S1" and spandrel["position"] == "above"
    assert spandrel["opening"] == "D1"
    assert (spandrel["start"], spandrel["end"], spandrel["bottom"], spandrel["top"]) == (
        2000,
        3500,
        2200,
        3000,
    )
    assert spandrel["length"] == 1500 and spandrel["depth"] == 800
    assert p1["spandrels"] == ["W1/L1/S1"] and p2["spandrels"] == ["W1/L1/S1"]
    load = LOAD / 1e3
    # Below the door head the piers carry the whole load between them.
    for cut in ("bottom", "middle"):
        v = p1["cuts"][cut]["WX"]["V2"] + p2["cuts"][cut]["WX"]["V2"]
        assert v == pytest.approx(load, rel=1e-6), cut
        # Coupled by the spandrel: each pier takes a real share, the longer one more.
        assert 0.2 * load < p1["cuts"][cut]["WX"]["V2"] < p2["cuts"][cut]["WX"]["V2"]
    # Overturning: the couple of the piers' axial forces and their own moments balance the
    # load's moment about the wall's centre at the base.
    base = [(p, p["cuts"]["bottom"]["WX"]) for p in (p1, p2)]
    centre = 3.0  # m
    moment = sum(f["M3"] + f["P"] * (p["centre"][0] / 1e3 - centre) for p, f in base)
    assert moment == pytest.approx(load * HEIGHT, rel=1e-6)
    # Gravity: the piers carry the whole wall's weight at the base.
    weight = dead_load(project, lambda z: z > 1e-6) / 1e3
    assert sum(p["cuts"]["bottom"]["D"]["P"] for p in (p1, p2)) == pytest.approx(weight, rel=1e-6)
    # The spandrel (local 1 along the wall, 2 up): its vertical shear at the two ends carries
    # the coupling; the same at both ends, as its axial force (no load on it in WX).
    left, right = spandrel["cuts"]["left"]["WX"], spandrel["cuts"]["right"]["WX"]
    assert abs(left["V2"]) > 0.01 * load
    assert left["V2"] == pytest.approx(right["V2"], rel=1e-6)
    assert left["P"] == pytest.approx(right["P"], rel=1e-6, abs=1e-6 * load)
    # Its end moments differ by V·length (statics of the spandrel).
    assert left["M3"] - right["M3"] == pytest.approx(left["V2"] * 1.5, rel=1e-6)
    # Its top edge (under the floor level) carries a share of the load across the top beside
    # the piers'; the wall's section at the top is the sum, the whole load.
    (section,) = found["sections"]
    assert section["section"] == "W1/L1" and section["lw"] == 6000
    assert section["piers"] == ["W1/L1/P1", "W1/L1/P2"] and section["spandrels"] == ["W1/L1/S1"]
    # The door stands on the base: the base section is the two piers', the top is whole.
    assert section["segments"] == {"bottom": [[0, 2000], [3500, 6000]], "top": [[0, 6000]]}
    assert set(spandrel["edge"]) == {"top"} and spandrel["edge_axes"] == p1["axes"]
    top = p1["cuts"]["top"]["WX"]["V2"] + p2["cuts"]["top"]["WX"]["V2"]
    edge = spandrel["edge"]["top"]["WX"]["V2"]
    assert top + edge == pytest.approx(load, rel=1e-6)
    for level in ("bottom", "top"):
        assert section["cuts"][level]["WX"]["V2"] == pytest.approx(load, rel=1e-6), level
    assert section["cuts"]["bottom"]["WX"]["M3"] == pytest.approx(load * HEIGHT, rel=1e-6)


WALL = {"type": "W", "kind": "wall", "bottom": 0, "top": HEIGHT * 1e3}
WINDOW = {"width": 1000, "height": 1200}
DUCT = {"width": 400, "height": 300}


@pytest.fixture(scope="module")
def window(tmp_path_factory: pytest.TempPathFactory):
    # A 4 m wall drawn from x = 4 m back to 0 with a 1 m x 1.2 m window (sill 900, 1.5 m from
    # its start) and a 400 x 300 duct 3.2 m from its start, and a 3 m wall along Y from its
    # end (an L).
    model = BuildingModel.model_validate(
        {
            "stories": [
                {"id": "BASE", "name": "Base", "elevation": 0},
                {"id": "L1", "name": "Level 1", "elevation": HEIGHT * 1e3},
            ],
            "elements": [
                {"id": "W1", "start": [4000, 0], "end": [0, 0], **WALL},
                {"id": "W2", "start": [0, 0], "end": [0, 3000], **WALL},
            ],
            "additions": {
                "wallOpenings": [
                    {"id": "WIN", "host": "W1", "offset": 1500, "sill": 900, **WINDOW},
                    {"id": "DU", "host": "W1", "offset": 3200, "sill": 2400, **DUCT},
                ]
            },
        }
    )
    project, out = analysed(tmp_path_factory.mktemp("window-wall"), model, top_load=LOAD)
    return model, project, out


def _global(f: dict, axes: list) -> np.ndarray:
    """A cut's force [kN] in global axes."""
    up, along, normal = (np.array(a) for a in axes)
    return -f["P"] * up + f["V2"] * along + f["V3"] * normal


def test_wall_with_a_window_reports_its_whole_section_at_the_levels(window) -> None:
    model, project, out = window
    found = wall_forces(project, model, out, [WX, WY, D])
    piers = {p["pier"]: p for p in found["piers"]}
    assert set(piers) == {"W1/L1/P1", "W1/L1/P2", "W2/L1/P1"}
    p1, p2 = piers["W1/L1/P1"], piers["W1/L1/P2"]
    assert (p1["start"], p1["end"], p2["start"], p2["end"]) == (0, 1500, 2500, 4000)
    # The duct (300 of 3000 mm high) is a hole in the pier, not a split.
    assert p2["holes"] == ["DU"] and not p1["holes"]
    assert any("DU" in n for n in found["notes"])
    spandrels = {s["position"]: s for s in found["spandrels"]}
    below, above = spandrels["below"], spandrels["above"]
    assert (below["bottom"], below["top"], above["bottom"], above["top"]) == (0, 900, 2100, 3000)
    assert set(below["edge"]) == {"bottom"} and set(above["edge"]) == {"top"}
    sections = {s["section"]: s for s in found["sections"]}
    assert set(sections) == {"W1/L1", "W2/L1"}
    w1 = sections["W1/L1"]
    assert w1["lw"] == 4000 and w1["centre"] == pytest.approx([2000, 0])
    assert w1["segments"] == {"bottom": [[0, 4000]], "top": [[0, 4000]]}
    assert w1["holes"] == ["DU"]
    load = LOAD / 1e3
    walls = [p for p in found["piers"] if p["wall"] == "W1"]
    for case in ("WX", "WY", "D"):
        for level in ("bottom", "top"):
            # W1's piers and its spandrels' edges at the level: its whole section.
            parts = sum(_global(p["cuts"][level][case], p["axes"]) for p in walls)
            for s in found["spandrels"]:
                if level in s["edge"]:
                    parts = parts + _global(s["edge"][level][case], s["edge_axes"])
            np.testing.assert_allclose(
                parts, _global(w1["cuts"][level][case], w1["axes"]), atol=1e-6 * load
            )
            # Both walls' sections: the whole load (statics), the sill wall's share in it.
            whole = sum(_global(s["cuts"][level][case], s["axes"]) for s in sections.values())
            expected = {
                "WX": [load, 0, 0],
                "WY": [0, load, 0],
                "D": [0, 0, -dead_load(project, lambda z: z > 1e-6) / 1e3],
            }[case]
            if case == "D" and level == "top":
                expected = [0, 0, -dead_load(project, lambda z: z > HEIGHT - 1e-6) / 1e3]
            np.testing.assert_allclose(whole, expected, atol=1e-6 * load)
    # The sill wall carries a real share of the base shear the piers' bottoms do not.
    edge = below["edge"]["bottom"]["WX"]
    assert abs(_global(edge, below["edge_axes"])[0]) > 0.05 * load
    # In-plane moment about the section's centre (W1 runs along -X: e3 = -Y, so the load along
    # +X tips it towards its start, M3 < 0), within the L by W2's share: the overturning of
    # the two walls together about the base (moment of the load H·h about the Y axis).
    w2 = sections["W2/L1"]
    m_y = 0.0
    for s in (w1, w2):
        f = s["cuts"]["bottom"]["WX"]
        up, along, normal = (np.array(a) for a in s["axes"])
        moment = f["T"] * up + f["M2"] * along + f["M3"] * normal
        force = _global(f, s["axes"])
        centre = np.array([*s["centre"], 0.0]) / 1e3
        m_y += (moment + np.cross(centre, force))[1]
    assert m_y == pytest.approx(load * HEIGHT, rel=1e-6)


def test_small_openings_split_only_when_asked(window) -> None:
    model, project, out = window
    every = wall_piers(project, model, out, [WX], min_opening=0)
    assert [(p["start"], p["end"]) for p in every if p["wall"] == "W1"] == [
        (0, 1500),
        (2500, 3200),
        (3600, 4000),
    ]
    named = wall_piers(project, model, out, [WX], min_opening=0, ignore={"DU"})
    assert len([p for p in named if p["wall"] == "W1"]) == 2


def test_stress_nodal_forces_reproduce_the_solvers(solid) -> None:
    # The temperature case's stress corrections become nodal forces by ∫ Bᵀ σ dA: on the
    # mechanical cases that reproduces the solver's own nodal forces from its stresses.
    from opensees_studio.services.result_store import load_manifest, load_results

    from saengine.design.wall_forces import stress_nodal_forces

    _, project, out = solid
    xyz = {n["id"]: np.array(n["coords"]) for n in project["nodes"]}
    for entry in load_manifest(out)["cases"]:
        results = load_results(entry, out)
        solver, mine = [], []
        for e in (e for e in project["elements"] if e["type"] == "Shell"):
            rows = np.asarray(results.shell_forces[e["id"]][-1]).reshape(-1, 8)
            solver.append(np.asarray(results.element_forces[e["id"]][-1]).reshape(-1, 6))
            mine.append(stress_nodal_forces([xyz[n] for n in e["nodes"]], rows))
        a, b = np.concatenate(solver), np.concatenate(mine)
        scale = np.abs(a[:, :3]).max()
        np.testing.assert_allclose(b[:, :3], a[:, :3], atol=0.01 * scale)
        if np.abs(a[:, 3:]).max() > 0.01 * scale:  # out-of-plane bending (WY): the couples
            ratio = float(np.sum(a[:, 3:] * b[:, 3:]) / np.sum(b[:, 3:] ** 2))
            assert ratio == pytest.approx(1.0, abs=0.02)


def test_given_case_forces_equal_the_results_folder(door) -> None:
    model, project, out = door
    cases = case_shell_forces(project, out)
    assert set(CASES) <= set(cases)
    a = wall_piers(project, model, out, [WX])
    b = wall_piers(project, model, cases, [WX])
    assert a == b


# ─────────────────────────────────────── the sample ───────────────────────────────────────

SAMPLE = (
    Path(__file__).parents[2] / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"
)


@pytest.mark.slow
def test_sample_storey_shear_is_the_piers_and_the_columns(tmp_path: Path) -> None:
    from saengine.design.check import _demands
    from saengine.design.slender import _crosses, _global_force
    from saengine.library.settings import LoadCombination, ProjectSettings
    from saengine.pipeline.run_all import run_all

    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    result = run_all(root, ["derive", "analysis"])
    assert [s.status for s in result.steps] == ["ok", "ok"], [s.message for s in result.steps]
    fem = root / "08 FEM"
    project = json.loads((fem / "model.osmodel").read_text(encoding="utf-8"))
    model = BuildingModel.model_validate_json(
        (root / "06 BIM" / "bim.json").read_text(encoding="utf-8")
    )
    settings = ProjectSettings.model_validate_json(
        (root / "02 Project Settings" / "project-settings.json").read_text(encoding="utf-8")
    )
    out = fem / "model.results"
    lateral = [DesignCombination(c, {c: 1.0}) for c in ("EX", "EY")]
    found = wall_forces(project, model, out, [*lateral, D])
    piers = found["piers"]
    # W1 (5 m along Y, two doors at 500-1400 and 1500-2500 mm): three piers in its storey.
    assert [(p["start"], p["end"]) for p in piers] == [(0, 500), (1400, 1500), (2500, 5000)]
    assert {s["opening"] for s in found["spandrels"]} == {"D1", "D2"}
    assert all(p["storey"] == "L1" and p["label"] == "Base to Level 1" for p in piers)

    mid = 1.6  # m, the middle of the storey the wall stands in
    z = {n["id"]: n["coords"][2] for n in project["nodes"]}
    for case in ("EX", "EY"):
        one = settings.model_copy(
            update={"combinations": [LoadCombination(name=case, **{case: 1.0})]}
        )
        _, pieces, _, _ = _demands(project, out, one)
        columns = np.zeros(3)
        for own in pieces.values():
            for p in own:
                vertical = p.start is not None and abs(p.axes[0][2]) > 0.1
                if vertical and _crosses((p.start[2], p.end[2]), mid):
                    columns += _global_force(p, p.forces[0])
        walls = np.zeros(3)
        for p in piers:
            f = p["cuts"]["middle"][case]
            up, along, normal = (np.array(a) for a in p["axes"])
            walls += (-f["P"] * up + f["V2"] * along + f["V3"] * normal) * 1e3
        pattern = next(lp for lp in project["load_patterns"] if lp["name"] == case)
        applied = sum(
            np.array(load["forces"][:3])
            for load in pattern["nodal_loads"]
            if z[load["node_id"]] > mid
        )
        # The storey shear: the columns' and the wall piers' shears together.
        size = float(np.abs(applied).max())
        np.testing.assert_allclose(columns + walls, applied, atol=0.005 * size)
        if case == "EY":  # along the wall: it takes a real share
            assert walls[1] > 0.1 * applied[1]
        # The wall's base section: its piers' bottoms (the doors stand on the base).
        (section,) = found["sections"]
        assert len(section["segments"]["bottom"]) == 3
        bottoms = sum(_global(p["cuts"]["bottom"][case], p["axes"]) for p in piers)
        np.testing.assert_allclose(
            _global(section["cuts"]["bottom"][case], section["axes"]),
            bottoms,
            atol=1e-6 * float(np.abs(bottoms).max()),
        )
    # Gravity: the piers' P at the base is compression.
    assert all(p["cuts"]["bottom"]["D"]["P"] > 0 for p in piers if p["lw"] > 200)

    # The response spectrum combinations: S ± E per sign pattern, E the pier's modal resultant
    # combined over the modes (the sample designs for the earthquake from the spectrum).
    from saengine.design.check import ensure_seismic_design
    from saengine.design.wall_forces import design_combination_list

    ensure_seismic_design(out, fem / "model.osmodel", settings)
    combinations, seismic, signs = design_combination_list(settings, out)
    assert seismic is not None and any(c.has_envelope for c in combinations)
    found = wall_forces(project, model, out, combinations, seismic, signs)
    assert any("modes" in n for n in found["notes"])
    pier = max(found["piers"], key=lambda p: p["lw"])
    rs = next(c for c in combinations if c.envelope.get("RY") == 1.0)
    by = pier["cuts"]["bottom"]
    names = [n for n in by if n.startswith(rs.name + " [")]
    assert len(names) == (8 if signs == "corners" else 2)
    v2 = sorted(by[n]["V2"] for n in names)
    # Its static part (the gravity cases of the combination) at the same cut.
    gravity = DesignCombination("S", dict(rs.factors))
    same = next(p for p in wall_piers(project, model, out, [gravity]) if p["pier"] == pier["pier"])
    static = same["cuts"]["bottom"]["S"]["V2"]
    # Symmetric about the static part, ± a positive peak.
    assert (v2[0] + v2[-1]) / 2 == pytest.approx(static, abs=1e-6 * abs(v2[-1]))
    assert v2[-1] - v2[0] > 0.1 * abs(static)
