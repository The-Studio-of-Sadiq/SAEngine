"""#278: a combination's buckling answer is kept on disk, so an export of every combination
reruns none already worked out; a changed run or model, or a damaged file, works it out again."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.fem import result_tables as rt


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("SAENGINE_SECTION_CACHE", str(tmp_path / "cache" / "section-properties"))
    project = tmp_path / "model.json"
    project.write_text("{}", encoding="utf-8")
    out_dir = tmp_path / "results"
    out_dir.mkdir()
    (out_dir / "case-1.h5").write_bytes(b"results")
    return project, out_dir


def test_round_trip_in_the_users_cache(run: tuple[Path, Path], tmp_path: Path) -> None:
    project, out_dir = run
    stamp = rt._buckling_stamp(out_dir, project)
    answer = SimpleNamespace(factors=[2.5, 4.0], modes=[{}, {}], skipped={})
    rt._buckling_disk_save(stamp, "combination:3", answer)
    saved = list((tmp_path / "cache" / "buckling").glob("*.pkl"))
    assert len(saved) == 1
    assert not list(out_dir.rglob("*.pkl"))  # never in the project
    assert rt._buckling_disk_load(stamp, "combination:3").factors == [2.5, 4.0]
    assert rt._buckling_disk_load(stamp, "combination:4") is None


def test_a_new_run_or_model_reads_nothing_old(run: tuple[Path, Path]) -> None:
    project, out_dir = run
    stamp = rt._buckling_stamp(out_dir, project)
    rt._buckling_disk_save(stamp, "combination:1", SimpleNamespace(factors=[1.0]))
    later = os.stat(out_dir / "case-1.h5").st_mtime_ns + 10**9
    os.utime(out_dir / "case-1.h5", ns=(later, later))
    assert rt._buckling_stamp(out_dir, project) != stamp
    assert rt._buckling_disk_load(rt._buckling_stamp(out_dir, project), "combination:1") is None
    project.write_text('{"changed": true}', encoding="utf-8")
    assert rt._buckling_stamp(out_dir, project) != stamp


def test_a_damaged_file_is_worked_out_again(run: tuple[Path, Path]) -> None:
    project, out_dir = run
    stamp = rt._buckling_stamp(out_dir, project)
    file = rt._buckling_disk_file(stamp, "combination:1")
    assert file is not None
    file.parent.mkdir(parents=True)
    file.write_bytes(b"not a pickle")
    assert rt._buckling_disk_load(stamp, "combination:1") is None


def test_buckling_runs_once_per_combination(
    run: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, out_dir = run
    calls: list[str] = []

    def fake_buckling(_project: object, _axial: object) -> SimpleNamespace:
        calls.append("run")
        return SimpleNamespace(factors=[3.0], modes=[{}], skipped={})

    monkeypatch.setattr("saengine.fem.buckling.linear_buckling", fake_buckling)
    monkeypatch.setattr(rt, "_summed", lambda *_args: {})
    monkeypatch.setattr("saengine.fem.thermal.load_corrections", lambda _p: None)
    model = SimpleNamespace(members=[], project=None)
    for _ in range(2):
        rt._buckling_cache.clear()  # a new session: only the disk remembers
        assert rt._buckling(out_dir, project, "combination:1", [], model).factors == [3.0]
    assert calls == ["run"]


def test_cache_off_still_works(run: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    project, out_dir = run
    monkeypatch.setenv("SAENGINE_SECTION_CACHE", "0")
    stamp = rt._buckling_stamp(out_dir, project)
    rt._buckling_disk_save(stamp, "combination:1", SimpleNamespace(factors=[1.0]))
    assert rt._buckling_disk_load(stamp, "combination:1") is None
