"""The analysis CLI's job count and per-case stamps (no solver needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opensees_studio import run
from opensees_studio.services import load_project

SPACE_FRAME = Path(__file__).resolve().parents[2] / "examples" / "space_frame_3d.osmodel"


def test_job_count_explicit_env_and_automatic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(run.JOBS_ENV, raising=False)
    assert run.job_count(3, 10) == 3
    assert run.job_count(None, run.PARALLEL_MIN_NODES - 1) == 1
    monkeypatch.setattr(run.os, "cpu_count", lambda: 16)
    assert run.job_count(None, run.PARALLEL_MIN_NODES) == run.MAX_AUTO_JOBS
    monkeypatch.setattr(run.os, "cpu_count", lambda: 2)
    assert run.job_count(None, run.PARALLEL_MIN_NODES) == 1
    monkeypatch.setenv(run.JOBS_ENV, "5")
    assert run.job_count(None, 10) == 5


def test_case_stamps_follow_the_model_and_the_case_closure() -> None:
    project = load_project(SPACE_FRAME)
    first = run.case_stamps(project, list(project.analyses))
    assert first == run.case_stamps(project, list(project.analyses))

    renamed = project.model_copy(update={"meta": project.meta.model_copy(update={"name": "x"})})
    assert run.case_stamps(renamed, list(renamed.analyses)) == first

    modal = next(a for a in project.analyses if a.id == 2)
    analyses = [
        a.model_copy(update={"n_modes": a.n_modes + 1}) if a.id == modal.id else a
        for a in project.analyses
    ]
    changed = project.model_copy(update={"analyses": analyses})
    second = run.case_stamps(changed, list(changed.analyses))
    assert second[1] == first[1]  # the static case does not read the modal case
    assert second[2] != first[2]
    assert second[4] != first[4]  # the response spectrum case combines its modes

    node = project.nodes[0]
    moved = project.model_copy(
        update={
            "nodes": [
                node.model_copy(update={"coords": (node.coords[0] + 1.0, *node.coords[1:])}),
                *project.nodes[1:],
            ]
        }
    )
    assert all(run.case_stamps(moved, list(moved.analyses))[cid] != first[cid] for cid in first)
