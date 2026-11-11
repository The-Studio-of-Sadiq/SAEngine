"""The design checks of the concrete beams and columns across processes
(saengine.design.member_pool): the same report as when they are all checked in one process."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from test_design import frame  # noqa: F401 - the analysed one-bay frame (a fixture)

from saengine.design import design_report, member_pool
from saengine.design.check import _Piece


def _piece(read_only: bool, combinations: int = 40) -> _Piece:
    rng = np.random.default_rng(7)
    forces = [rng.normal(size=(11, 6)) for _ in range(combinations)]
    for f in forces:
        f.setflags(write=not read_only)
    return _Piece(
        "B1#1",
        3,
        1.5,
        False,
        np.eye(3),
        forces,
        start=np.zeros(3),
        end=np.array([1.5, 0.0, 0.0]),
        sway=[f * 0.5 for f in forces],
        sustained=None,
    )


def test_worker_count_follows_the_model_the_cores_and_the_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(member_pool.ENV_SERIAL, raising=False)
    monkeypatch.delenv(member_pool.ENV_WORKERS, raising=False)
    monkeypatch.setattr(member_pool.os, "cpu_count", lambda: 16)
    windows = sys.platform == "win32"
    assert member_pool.worker_count(member_pool.MIN_MEMBERS - 1) == 0
    assert member_pool.worker_count(1000) == (member_pool.MAX_WORKERS if windows else 0)
    monkeypatch.setattr(member_pool.os, "cpu_count", lambda: 4)
    assert member_pool.worker_count(1000) == (3 if windows else 0)
    monkeypatch.setenv(member_pool.ENV_WORKERS, "2")
    assert member_pool.worker_count(1000) == (2 if windows else 0)
    monkeypatch.setenv(member_pool.ENV_SERIAL, "1")
    assert member_pool.worker_count(1000) == 0
    monkeypatch.setattr(member_pool.os, "cpu_count", lambda: 2)
    monkeypatch.setenv(member_pool.ENV_SERIAL, "0")
    assert member_pool.worker_count(1000) == 0  # one core left: not worth it


@pytest.mark.skipif(sys.platform != "win32", reason="the workers run on Windows only")
def test_pieces_go_through_shared_memory_unchanged() -> None:
    pieces = {"B1": [_piece(True), _piece(False)], "C1": [_piece(False, 400)]}
    block = member_pool._share(pieces)
    try:
        back, other = member_pool._unshare(block.name)
        sent_all = [p for own in pieces.values() for p in own]
        got_all = [p for own in back.values() for p in own]
        for sent, got in zip(sent_all, got_all, strict=True):
            assert type(got) is _Piece and got.id == sent.id and got.sustained is None
            assert len(got.forces) == len(sent.forces)
            for a, b in zip(sent.forces + sent.sway, got.forces + got.sway, strict=True):
                assert b.dtype == a.dtype and np.array_equal(a, b)
                # Read-only where it was; a large one read in place, read-only too.
                small = b.nbytes * len(sent.forces) < member_pool._OUT_OF_BAND
                assert not b.flags.writeable or (a.flags.writeable and small)
        del back, got, got_all, a, b
        import gc

        gc.collect()
        other.close()
    finally:
        block.close()


@pytest.mark.skipif(sys.platform != "win32", reason="the workers run on Windows only")
def test_checks_across_processes_give_the_same_report(
    frame: Path,  # noqa: F811 - the fixture imported above
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results, model = frame / "08 FEM" / "model.results", frame / "08 FEM" / "model.osmodel"
    monkeypatch.setenv(member_pool.ENV_SERIAL, "1")
    serial = json.dumps(design_report(results, model), sort_keys=True, default=str)
    monkeypatch.setenv(member_pool.ENV_SERIAL, "0")
    monkeypatch.setattr(member_pool, "MIN_MEMBERS", 2)
    monkeypatch.setattr(member_pool, "MEMBERS_PER_WORKER", 1)
    taken = []
    original = member_pool.Prepared.take

    def take(self: member_pool.Prepared, index: int) -> object:
        found = original(self, index)
        taken.append(found is not None)
        return found

    monkeypatch.setattr(member_pool.Prepared, "take", take)
    try:
        parallel = json.dumps(design_report(results, model), sort_keys=True, default=str)
    finally:
        member_pool.shutdown()
    assert taken and all(taken)  # every concrete member was checked in a worker
    assert parallel == serial
