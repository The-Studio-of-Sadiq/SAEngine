"""The analysis CLI's parallel units, selective reruns and shared modal results.

- ``--jobs 2`` runs the cases in child processes and writes the same results and manifest
  (in the requested order) as one process;
- ``--reuse`` keeps the results of the cases whose model and definition did not change, runs
  the changed ones, and removes what else the folder held;
- a response spectrum case whose modal case ran in the same process combines that case's
  modes: the same results as solving the eigenproblem again.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("openseespy.opensees")

from opensees_studio.services import load_project
from opensees_studio.services.persistence import save_project
from opensees_studio.services.result_store import load_manifest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
SPACE_FRAME = EXAMPLES / "space_frame_3d.osmodel"
CASES = [1, 2, 3, 4]  # static, modal, transient, response spectrum


def _run(model: Path, out: Path, *extra: str) -> list[dict]:
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *map(str, CASES),
            "--out",
            str(out),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def _datasets(path: Path) -> dict[str, np.ndarray]:
    import h5py

    found: dict[str, np.ndarray] = {}
    with h5py.File(path, "r") as f:
        f.visititems(
            lambda name, obj: (
                found.__setitem__(name, obj[()]) if isinstance(obj, h5py.Dataset) else None
            )
        )
    return found


def _same_files(a: Path, b: Path) -> None:
    for entry in load_manifest(a)["cases"]:
        for name in entry["files"]:
            left, right = _datasets(a / name), _datasets(b / name)
            assert left.keys() == right.keys()
            for key, value in left.items():
                np.testing.assert_array_equal(value, right[key], err_msg=f"{name}/{key}")


def test_parallel_run_equals_one_process(tmp_path: Path) -> None:
    serial, parallel = tmp_path / "serial", tmp_path / "parallel"
    _run(SPACE_FRAME, serial, "--jobs", "1")
    lines = _run(SPACE_FRAME, parallel, "--jobs", "2")
    assert any("processes" in str(line.get("message", "")) for line in lines)
    order = [e["case_id"] for e in load_manifest(parallel)["cases"]]
    assert order == CASES
    assert not list(parallel.glob("manifest.part-*.json"))
    _same_files(serial, parallel)


def test_response_spectrum_takes_the_modal_case_already_solved(tmp_path: Path) -> None:
    together, alone = tmp_path / "together", tmp_path / "alone"
    lines = _run(SPACE_FRAME, together, "--jobs", "1")
    assert any("already solved" in str(line.get("message", "")) for line in lines)
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(SPACE_FRAME),
            "--cases",
            "4",
            "--out",
            str(alone),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    left = _datasets(together / "case_4.results.h5")
    right = _datasets(alone / "case_4.results.h5")
    for key, value in left.items():
        np.testing.assert_allclose(value, right[key], rtol=1e-12, atol=1e-15, err_msg=key)


def test_reuse_keeps_unchanged_cases_and_runs_changed_ones(tmp_path: Path) -> None:
    model = tmp_path / "frame.osmodel"
    save_project(load_project(SPACE_FRAME), model)
    out = tmp_path / "results"
    _run(model, out, "--reuse", "--jobs", "1")
    (out / "design-cache.json").write_text("{}", encoding="utf-8")  # a reader's cache

    lines = _run(model, out, "--reuse", "--jobs", "1")
    kept = [line for line in lines if "results are kept" in str(line.get("message", ""))]
    assert len(kept) == len(CASES)
    assert not (out / "design-cache.json").exists()

    project = load_project(model)
    analyses = [
        a.model_copy(update={"name": "Lateral-Push renamed"}) if a.id == 1 else a
        for a in project.analyses
    ]
    save_project(project.model_copy(update={"analyses": analyses}), model)
    lines = _run(model, out, "--reuse", "--jobs", "1")
    started = [line["case_id"] for line in lines if line.get("type") == "case_started"]
    kept = [line for line in lines if "results are kept" in str(line.get("message", ""))]
    assert sorted(started) == CASES and len(kept) == len(CASES) - 1
    names = {e["case_id"]: e["case_name"] for e in load_manifest(out)["cases"]}
    assert names[1] == "Lateral-Push renamed"
    stamps = json.loads((out / "case-stamps.json").read_text(encoding="utf-8"))
    assert sorted(map(int, stamps["cases"])) == CASES
