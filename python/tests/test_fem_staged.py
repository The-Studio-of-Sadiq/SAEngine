"""Construction sequence (Analysis.constructionSequence): the self-weight applied storey by
storey through an opensees-studio StagedCase, and what the rest of SAEngine makes of it."""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from saengine.fem.derive import derive_fem
from saengine.fem.display import result_list, result_view
from saengine.library import FloorPlan, default_floor_plan, default_material_library
from saengine.library.bim import generate
from saengine.library.settings import default_project_settings
from tests.test_fem_derive import OBJECTS, applied

# Two bays (A-B-C, 6 m each) by one (1-2, 5 m), three storeys of 3.2 m.
XS, YS = (("A", 0), ("B", 6000), ("C", 12000)), (("1", 0), ("2", 5000))
LEVELS = ("L1", "L2", "L3")
_plan = default_floor_plan().model_dump(mode="json", by_alias=True)
_plan["grids"] = {
    "x": [{"label": a, "position": p} for a, p in XS],
    "y": [{"label": a, "position": p} for a, p in YS],
}
_plan["stories"] = [{"id": "BASE", "name": "Base", "elevation": 0.0}] + [
    {"id": level, "name": f"Level {i + 1}", "elevation": 3200.0 * (i + 1)}
    for i, level in enumerate(LEVELS)
]
_below = dict(zip(LEVELS, ("BASE", *LEVELS[:-1]), strict=True))
_plan["columns"] = [
    {
        "id": f"C{x}{y}{level}",
        "type": "COL",
        "at": {"x": x, "y": y},
        "base": _below[level],
        "top": level,
    }
    for level in LEVELS
    for x, _ in XS
    for y, _ in YS
]
_lines = [((a, "1"), (b, "1")) for (a, _), (b, _) in itertools.pairwise(XS)]
_lines += [((a, "2"), (b, "2")) for (a, _), (b, _) in itertools.pairwise(XS)]
_lines += [((x, "1"), (x, "2")) for x, _ in XS]
_plan["beams"] = [
    {
        "id": f"B{i}{level}",
        "type": "BM",
        "story": level,
        "start": {"x": s[0], "y": s[1]},
        "end": {"x": e[0], "y": e[1]},
    }
    for level in LEVELS
    for i, (s, e) in enumerate(_lines)
]
_plan["slabs"] = [
    {
        "id": f"S{a}{level}",
        "type": "SL",
        "story": level,
        "boundary": [
            {"x": a, "y": "1"},
            {"x": b, "y": "1"},
            {"x": b, "y": "2"},
            {"x": a, "y": "2"},
        ],
    }
    for level in LEVELS
    for (a, _), (b, _) in itertools.pairwise(XS)
]
PLAN = FloorPlan.model_validate(_plan)


def settings(sequence: bool = True, stiffness: str | None = None):
    s = default_project_settings("Frame")
    s.analysis.constructionSequence = sequence
    s.analysis.responseSpectrum = False
    if stiffness is not None:
        s.analysis.stiffness = stiffness
    return s


def derivation(sequence: bool = True, stiffness: str | None = None):
    return derive_fem(
        generate(PLAN, "s"),
        OBJECTS,
        default_material_library(),
        settings(sequence, stiffness),
        {"bim": "x"},
    )


def test_stages_split_the_self_weight_by_storey() -> None:
    project = derivation().project
    dead = project["analyses"][0]
    assert dead["type"] == "Staged" and dead["name"].startswith("D: ")
    assert [s["name"] for s in dead["stages"]] == [
        "Level 1 (+3.20 m)",
        "Level 2 (+6.40 m)",
        "Level 3 (+9.60 m)",
    ]
    elements = {e["id"]: e for e in project["elements"]}
    nodes = {n["id"]: n["coords"] for n in project["nodes"]}
    built = [i for stage in dead["stages"] for i in stage["element_ids"]]
    assert sorted(built) == sorted(elements)  # every element is built once
    for k, stage in enumerate(dead["stages"]):
        top = 3.2 * (k + 1)
        for i in stage["element_ids"]:
            z = max(nodes[n][2] for n in elements[i]["nodes"])
            assert top - 3.2 < z <= top + 1e-6, (stage["name"], elements[i]["name"], z)
        # A stage loads only what is built by its end.
        so_far = {i for s in dead["stages"][: k + 1] for i in s["element_ids"]}
        so_far_nodes = {n for i in so_far for n in elements[i]["nodes"]}
        (pattern,) = (p for p in project["load_patterns"] if p["id"] in stage["pattern_ids"])
        assert {load["element_id"] for load in pattern["element_loads"]} <= so_far
        assert {load["node_id"] for load in pattern["nodal_loads"]} <= so_far_nodes
    # The stages add up to the whole self-weight, which D0 applies at once.
    total = sum(applied(project, f"D, stage {k + 1}") for k in range(3))
    np.testing.assert_allclose(total, applied(project, "D"), rtol=1e-6, atol=1.0)
    d0 = next(a for a in project["analyses"] if a["name"].startswith("D0: "))
    assert d0["type"] == "Static" and d0["pattern_ids"] == [1]


def test_off_by_default_and_for_special_structures() -> None:
    assert default_project_settings("x").analysis.constructionSequence is False
    project = derivation(sequence=False).project
    assert all(a["type"] != "Staged" for a in project["analyses"])
    assert not any(p["name"].startswith("D, stage") for p in project["load_patterns"])


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, Path, Path]:
    root = tmp_path_factory.mktemp("staged")
    d = derivation()
    model = root / "08 FEM" / "model.osmodel"
    model.parent.mkdir()
    model.write_text(json.dumps(d.project), encoding="utf-8")
    (root / "02 Project Settings").mkdir()
    (root / "02 Project Settings" / "project-settings.json").write_text(
        settings().model_dump_json(by_alias=True), encoding="utf-8"
    )
    out = root / "08 FEM" / "model.results"
    ids = [str(a["id"]) for a in d.project["analyses"]]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *ids,
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return d.project, model, out


def test_staged_and_at_once_carry_the_same_load_but_shorten_differently(run) -> None:
    from opensees_studio.services.result_store import load_manifest, load_results

    project, _, out = run
    by = {e["case_name"].split(":")[0]: load_results(e, out) for e in load_manifest(out)["cases"]}
    staged, at_once = by["D"], by["D0"]
    assert staged.stage_names == [s["name"] for s in project["analyses"][0]["stages"]]
    reaction = lambda r: sum(v[-1][:3] for v in r.node_reaction.values())
    np.testing.assert_allclose(reaction(staged), reaction(at_once), rtol=1e-6, atol=1e-3)
    # Roof columns: a storey built later misses the shortening below it that happened before,
    # so the roof settles less than under the load applied at once (and storey 1 the same).
    connected = {n for e in project["elements"] for n in e["nodes"]}  # not the diaphragm nodes
    nodes = {n["id"]: n["coords"] for n in project["nodes"] if n["id"] in connected}
    roof = [n for n, c in nodes.items() if abs(c[2] - 9.6) < 1e-6]
    first = [n for n, c in nodes.items() if abs(c[2] - 3.2) < 1e-6]
    assert roof and first
    for n in roof:
        assert abs(staged.node_disp[n][-1][2]) < abs(at_once.node_disp[n][-1][2])
    # Level 1 is built first and loaded by everything: its settlement does not change much.
    for n in first:
        assert staged.node_disp[n][-1][2] == pytest.approx(at_once.node_disp[n][-1][2], rel=0.25)
    # Before level 3 is built its nodes have not moved, and its columns carry nothing.
    names = {e["id"]: e["name"] for e in project["elements"]}
    for n in roof:
        assert not np.any(staged.node_disp[n][1])
    for i, name in names.items():
        if name.endswith("L3") and i in staged.element_forces:
            assert not np.any(staged.element_forces[i][1])


def test_display_stages_and_design_use_the_staged_dead_load(run) -> None:
    _, model, out = run
    listing = result_list(out, model)
    dead = next(r for r in listing["results"] if r["label"].startswith("D: "))
    assert [f["stage"] for f in dead["frames"]] == [
        "Level 1 (+3.20 m)",
        "Level 2 (+6.40 m)",
        "Level 3 (+9.60 m)",
    ]
    assert dead["peak"] == 3
    after_one = result_view(out, model, dead["key"], 1)
    final = result_view(out, model, dead["key"])
    assert after_one["label"].endswith("after Level 1 (+3.20 m)")
    assert final["label"] == dead["label"]
    reactions = lambda v: sum(np.array(r[1:4]) for r in v["reactions"])
    # After level 1 the reactions carry level 1's self-weight only (about a third).
    ratio = reactions(after_one)[2] / reactions(final)[2]
    assert 0.25 < ratio < 0.45
    # Combinations (and so the design checks) take D as the staged case: 1.4D is 1.4 times it
    # plus the superimposed dead load (SD, part of D in the combinations).
    combination = result_view(out, model, "combination:1")
    assert combination["label"] == "1.4D"
    sd_key = next(r["key"] for r in listing["results"] if r["label"].startswith("SD: "))
    staged = {n[0]: np.array(n[1:4]) for n in final["nodes"]}
    superimposed = {n[0]: np.array(n[1:4]) for n in result_view(out, model, sd_key)["nodes"]}
    for node in combination["nodes"]:
        expected = 1.4 * (staged[node[0]] + superimposed[node[0]])
        np.testing.assert_allclose(
            node[1:4], expected, rtol=1e-6, atol=2e-9
        )  # views round to 1e-9 m
