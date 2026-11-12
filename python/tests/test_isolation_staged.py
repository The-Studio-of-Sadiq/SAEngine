"""W4B-1, W4B-2: seismic isolators with the construction sequence, the footing loads under the
isolators, and the plausibility check of a run (Run All must not say "done" over absurd
results)."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from test_fem_isolation import MATERIALS, OBJECTS, _bay

from saengine.fem import isolation as iso
from saengine.fem.derive import derive_fem, stage_added_elements
from saengine.fem.results_check import implausible
from saengine.library.settings import default_project_settings
from saengine.report.build import fmt_utilisation
from saengine.substructure.loads import base_loads, support_nodes


def _settings():
    s = default_project_settings("Isolated")
    s.analysis.constructionSequence = True
    s.analysis.responseSpectrum = False
    return s


def _run(project: dict, root: Path, names: tuple[str, ...] = ("D", "D0")) -> Path:
    model = root / "08 FEM" / "model.osmodel"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps(project), encoding="utf-8")
    out = root / "08 FEM" / "model.results"
    ids = [str(a["id"]) for a in project["analyses"] if a["name"].split(":")[0] in names]
    result = subprocess.run(
        [sys.executable, "-m", "opensees_studio.run", "--project", str(model), "--cases", *ids]
        + ["--out", str(out)],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return out


@pytest.fixture(scope="module")
def derived():
    building = _bay()
    return building, derive_fem(building, OBJECTS, MATERIALS, _settings())


def _springs(project: dict) -> list[dict]:
    return [e for e in project["elements"] if e["name"].endswith(iso.ELEMENT_SUFFIX)]


def test_staged_model_builds_the_isolators_in_the_first_stage(derived) -> None:
    _, d = derived
    springs = _springs(d.project)
    assert d.isolation is not None and len(springs) == 4
    staged = [a for a in d.project["analyses"] if a["type"] == "Staged"]
    assert staged
    for analysis in staged:
        first = set(analysis["stages"][0]["element_ids"])
        assert all(e["id"] in first for e in springs)


@pytest.fixture(scope="module")
def run(derived, tmp_path_factory: pytest.TempPathFactory):
    _, d = derived
    root = tmp_path_factory.mktemp("isolated-staged")
    return root, _run(d.project, root)


def test_staged_dead_load_on_isolators_matches_the_load_at_once(run) -> None:
    from opensees_studio.services.result_store import load_manifest, load_results

    root, out = run
    by = {e["case_name"].split(":")[0]: load_results(e, out) for e in load_manifest(out)["cases"]}
    staged, at_once = by["D"], by["D0"]

    def largest(r) -> float:
        return max(float(np.abs(np.asarray(v)[-1][:3]).max()) for v in r.node_disp.values())

    # One storey: the staged dead load is the load at once (was 1e10 m: no isolators built).
    assert largest(staged) < 0.05
    assert largest(staged) == pytest.approx(largest(at_once), rel=1e-3)
    assert implausible(root / "08 FEM" / "model.osmodel", out) is None


def test_footing_loads_come_from_the_isolator_ground_nodes(derived, run) -> None:
    building, d = derived
    _, out = run
    ground = {e["nodes"][0] for e in _springs(d.project)}
    bases = {e["nodes"][1] for e in _springs(d.project)}
    supports = set(support_nodes(d.project).values())
    # Each isolated base: the isolator's fixed ground node (not the base held in rotation).
    assert ground <= supports and not bases & supports
    loads = base_loads(d.project, out, building, _settings())
    assert len(loads.bases) == 4 and not loads.unsupported
    total = 0.0
    for base_id, base in loads.bases.items():
        down = -float(loads.resultant(base_id, {"D": 1.0}, base.nodes[0][1])[2])
        assert down > 1e3, base_id  # each corner carries its share of the dead load
        total += down
    weight = sum(float(r[2]) for r in loads.cases["D0"].values())
    assert total == pytest.approx(weight, rel=1e-6)


def test_support_nodes_without_isolators_unchanged() -> None:
    project = {
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
            {"id": 2, "coords": [5, 0, 0], "restraint": [True] * 6},
            {"id": 3, "coords": [5, 0, 3], "restraint": [False] * 6},
        ]
    }
    assert support_nodes(project) == {(0, 0, 0): 1, (5000, 0, 0): 2}
    # A base held in rotation above a fixed ground node: the ground node, in either order.
    rotation = [False, False, False, True, True, True]
    for nodes in (
        [{"id": 7, "coords": [0, 0, 0], "restraint": rotation}, project["nodes"][0]],
        [project["nodes"][0], {"id": 7, "coords": [0, 0, 0], "restraint": rotation}],
    ):
        assert support_nodes({"nodes": nodes}) == {(0, 0, 0): 1}


def test_plausibility_check_names_the_case_without_isolators_in_the_stages(
    derived, tmp_path: Path
) -> None:
    _, d = derived
    broken = copy.deepcopy(d.project)
    springs = {e["id"] for e in _springs(broken)}
    for analysis in broken["analyses"]:
        for stage in analysis.get("stages", []):
            stage["element_ids"] = [i for i in stage["element_ids"] if i not in springs]
    out = _run(broken, tmp_path, ("D",))
    message = implausible(tmp_path / "08 FEM" / "model.osmodel", out)
    assert message is not None and "case D" in message and "node" in message


def test_stage_added_elements_follows_the_nodes() -> None:
    project = {
        "elements": [
            {"id": 1, "nodes": [1, 2]},  # storey 1
            {"id": 2, "nodes": [2, 3]},  # storey 2
            {"id": 3, "nodes": [9, 1]},  # isolator: ground node 9 under base 1
            {"id": 4, "nodes": [2, 3]},  # a brace added later in storey 2
            {"id": 5, "nodes": [20, 21]},  # joined to nothing: stays out
        ],
        "analyses": [
            {"type": "Static"},
            {"type": "Staged", "stages": [{"element_ids": [1]}, {"element_ids": [2]}]},
        ],
    }
    assert stage_added_elements(project) == 2
    stages = project["analyses"][1]["stages"]
    assert stages[0]["element_ids"] == [1, 3] and stages[1]["element_ids"] == [2, 4]
    # Nothing staged, nothing changed.
    assert stage_added_elements({"elements": [], "analyses": [{"type": "Static"}]}) == 0


def test_printed_utilisation_is_capped() -> None:
    assert fmt_utilisation(1_500_000.0) == ">100"
    assert fmt_utilisation(0.8234) == "0.823"
    assert fmt_utilisation(None) == "–"
