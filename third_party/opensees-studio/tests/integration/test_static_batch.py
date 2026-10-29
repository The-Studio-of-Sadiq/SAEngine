"""Linear static cases run together by the CLI equal the same cases run one by one.

``python -m opensees_studio.run`` builds the model once for consecutive linear static cases of
one solver setting and factors the stiffness once (``OpenSeesRunner.start_static_batch``). Each
case's results must equal its own run to roundoff, a pattern used by two cases must load both,
and a case that cannot join (two steps) must split the run without disturbing it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.core import StaticCase
from opensees_studio.services import load_project
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.persistence import save_project
from opensees_studio.services.result_store import load_manifest, load_results

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

FIELDS = ("node_disp", "node_reaction", "element_forces", "element_deformations", "shell_forces")


def _space_frame_with_more_cases(path: Path) -> list[int]:
    project = load_project(EXAMPLES / "space_frame_3d.osmodel")
    first = next(c for c in project.analyses if c.id == 1)
    pattern = next(p for p in project.load_patterns if p.id == first.pattern_ids[0])
    doubled = pattern.model_copy(
        update={
            "id": 50,
            "nodal_loads": [
                nl.model_copy(update={"forces": tuple(2.0 * f for f in nl.forces)})
                for nl in pattern.nodal_loads
            ],
        }
    )
    extra = [
        first.model_copy(update={"id": 101, "name": "Same pattern again"}),
        first.model_copy(update={"id": 102, "name": "Two steps", "n_steps": 2}),
        first.model_copy(update={"id": 103, "name": "Doubled", "pattern_ids": [50]}),
        first.model_copy(
            update={"id": 104, "name": "Both", "pattern_ids": [first.pattern_ids[0], 50]}
        ),
    ]
    project = project.model_copy(
        update={
            "load_patterns": [*project.load_patterns, doubled],
            "analyses": [*project.analyses, *extra],
        }
    )
    save_project(project, path)
    return [1, 101, 102, 103, 104]


def _run_cli(model: Path, ids: list[int], out: Path) -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *map(str, ids),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def _assert_same(alone, together) -> None:  # type: ignore[no-untyped-def]
    assert list(alone.load_factors) == list(together.load_factors)
    for name in FIELDS:
        a, b = getattr(alone, name), getattr(together, name)
        assert list(a) == list(b), name
        if not a:
            continue
        scale = max(float(np.abs(v).max()) for v in a.values()) or 1.0
        for tag in a:
            assert a[tag].shape == b[tag].shape, (name, tag)
            assert np.allclose(a[tag], b[tag], rtol=0.0, atol=1e-9 * scale), (name, tag)


@pytest.mark.parametrize("example", ["space_frame_3d", "cantilever"])
def test_linear_static_cases_run_together_equal_their_own_runs(
    example: str, tmp_path: Path
) -> None:
    if example == "space_frame_3d":
        model = tmp_path / "model.osmodel"
        ids = _space_frame_with_more_cases(model)
    else:
        model = EXAMPLES / "cantilever.osmodel"
        ids = [1, 2]
    project = load_project(model)
    planner = OpenSeesRunner(project)
    cases = {c.id: c for c in project.analyses}
    keys = [planner.batch_key(cases[i]) for i in ids]
    assert sum(k is not None for k in keys) >= 2  # the CLI runs some of them together
    out = tmp_path / "out"
    _run_cli(model, ids, out)
    entries = {e["case_id"]: e for e in load_manifest(out)["cases"]}
    assert [e["case_id"] for e in load_manifest(out)["cases"]] == ids
    for cid in ids:
        assert isinstance(cases[cid], StaticCase)
        alone = OpenSeesRunner(project).run(cases[cid])
        _assert_same(alone, load_results(entries[cid], out))


def test_doubled_and_combined_patterns_superpose(tmp_path: Path) -> None:
    """The copies of a pattern used by two cases load each once: 104 = 1 + 103 = 3 x 1."""
    model = tmp_path / "model.osmodel"
    ids = _space_frame_with_more_cases(model)
    out = tmp_path / "out"
    _run_cli(model, ids, out)
    entries = {e["case_id"]: e for e in load_manifest(out)["cases"]}
    one, both = (load_results(entries[c], out) for c in (1, 104))
    for tag, values in one.node_disp.items():
        assert np.allclose(both.node_disp[tag], 3.0 * values, rtol=1e-9, atol=1e-15)
