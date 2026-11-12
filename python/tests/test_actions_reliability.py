"""Track D of the AI round: a whole project done reliably by the shared editing actions.

- ``writes`` on every action of the catalogue (clients decide by it, not by names);
- a batch stopped (``should_stop``, the RPC request's cancellation, ``actions/cancel``) stops
  before its next step, a Run All at its next step boundary, and answers what was done;
- a batch with a run step is all or nothing per segment: the edits before the run step are
  written first and stay written, and the results say so;
- the AI's typical mistakes are refused by the actions with the allowed range.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from saengine.actions import BatchResult, list_actions, run_actions
from saengine.actions.paths import FLOOR_PLAN

BASE_STEPS = [
    {"action": "project.create", "params": {"name": "Base"}},
    {"action": "grid.set", "params": {"x": [5000, 5000], "y": [4000]}},
    {"action": "storeys.set", "params": {"count": 2, "height": 3000}},
    {"action": "columns.place", "params": {"type": "C400x400"}},
    {"action": "beams.place", "params": {"type": "B250x450"}},
    {"action": "slabs.place", "params": {"type": "S125"}},
]


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("reliability") / "Base"
    result = run_actions(root, BASE_STEPS, write=True)
    assert result.ok, [r.message for r in result.results]
    return root


@pytest.fixture
def copy(base: Path, tmp_path: Path) -> Path:
    import shutil

    target = tmp_path / "Copy"
    shutil.copytree(base, target)
    return target


def run(root: Path, *steps: tuple[str, dict[str, Any]], **options: Any) -> BatchResult:
    return run_actions(root, [{"action": a, "params": p} for a, p in steps], **options)


# ─────────────────────────────── writes ───────────────────────────────


def test_writes_is_on_every_action_and_marks_the_ones_that_write_to_disk():
    catalogue = {a.name: a for a in list_actions()}
    writing = {name for name, a in catalogue.items() if a.writes}
    assert {"project.create", "run.all", "run.step", "design.reinforcement.apply"} <= writing
    assert {n for n in catalogue if n.startswith("export.")} <= writing
    # Every run action writes; of the edits, only project.create (it makes the project's files).
    assert writing == {n for n, a in catalogue.items() if a.kind == "run"} | {"project.create"}
    assert not catalogue["grid.set"].writes and not catalogue["project.summary"].writes
    from saengine.rpc import handlers

    listed = {a["name"]: a for a in handlers.actions_list()}
    assert listed["project.create"]["writes"] is True and listed["grid.set"]["writes"] is False


# ─────────────────────────────── cancel ───────────────────────────────


class StopAfter:
    """A stop test that says "stop" from its ``n``-th question on."""

    def __init__(self, n: int) -> None:
        self.n, self.asked = n, 0

    def __call__(self) -> bool:
        self.asked += 1
        return self.asked >= self.n


def test_a_stopped_batch_stops_before_its_next_step_and_says_what_was_done(copy):
    before = (copy / FLOOR_PLAN).read_text(encoding="utf-8")
    batch = run(
        copy,
        ("grid.line.add", {"axis": "x", "position": 15000}),
        ("grid.line.add", {"axis": "y", "position": 8000}),
        write=True,
        should_stop=StopAfter(2),
    )
    assert batch.cancelled and not batch.ok and batch.failed_step == 1
    assert batch.results[0].ok and "Stopped" in batch.results[1].message
    # Nothing was written: the edits of a stopped segment are dropped.
    assert batch.changes == {} and batch.written == []
    assert (copy / FLOOR_PLAN).read_text(encoding="utf-8") == before


def test_run_all_stops_at_its_next_step_boundary_and_the_saved_edits_stay(copy):
    # The batch asks before step 0 (go) and step 1 (go); Run All asks before bim (go) and before
    # derive (stop): derive is not run, the batch is cancelled at step 1.
    batch = run(
        copy,
        ("grid.line.add", {"axis": "x", "position": 15000}),
        ("run.step", {"step": "derive"}),
        write=True,
        should_stop=StopAfter(4),
    )
    assert batch.cancelled and batch.failed_step == 1
    ran = batch.results[1]
    assert ran.action == "run.step" and not ran.ok
    steps = {s["id"]: s for s in ran.data["steps"]}
    assert steps["bim"]["status"] in ("ok", "warning")
    assert steps["derive"]["status"] == "notRun" and "stopped" in steps["derive"]["message"]
    assert ran.data["cancelled"] and ran.message.startswith("Stopped at")
    # The grid line was saved before the run step (a commit point) and stays written.
    assert ran.written == [FLOOR_PLAN] and batch.written == [FLOOR_PLAN]
    assert any("Written before this step and kept" in w for w in ran.warnings)
    assert '"label": "D"' in (copy / FLOOR_PLAN).read_text(encoding="utf-8")


def test_the_rpc_requests_cancellation_stops_the_batch(base):
    from saengine.rpc import jobs

    job, token = jobs.start("actions/run")
    try:
        assert jobs.cancel(["actions/run"]) == 1
        batch = run(base, ("project.summary", {}))
    finally:
        jobs.finish(job, token)
    assert batch.cancelled and batch.failed_step == 0 and not batch.results[0].ok


def _rpc(proc: subprocess.Popen, msg_id: int, method: str, params: dict) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}).encode()
    proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    proc.stdin.flush()
    length = None
    while True:
        line = proc.stdout.readline().strip()
        if not line:
            break
        name, _, value = line.partition(b":")
        if name.lower() == b"content-length":
            length = int(value)
    return json.loads(proc.stdout.read(length))


def test_actions_cancel_over_the_rpc_server(base):
    proc = subprocess.Popen(
        [sys.executable, "-m", "saengine.rpc"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert _rpc(proc, 1, "actions/cancel", {})["result"] == {"cancelled": 0}
        listed = _rpc(proc, 2, "actions/list", {"kind": "run"})["result"]
        assert listed and all(a["writes"] for a in listed)
        answer = _rpc(
            proc,
            3,
            "actions/run",
            {"projectRoot": str(base), "steps": [{"action": "project.summary", "params": {}}]},
        )["result"]
        assert answer["ok"] and answer["cancelled"] is False
    finally:
        proc.kill()
        proc.wait()


# ─────────────────────────────── segments ───────────────────────────────


def test_a_failed_run_step_keeps_the_edits_saved_before_it_and_says_so(copy):
    batch = run(
        copy,
        ("grid.line.add", {"axis": "x", "position": 15000}),
        ("design.reinforcement.apply", {}),  # no analysis results: refused
        write=True,
    )
    assert not batch.ok and batch.failed_step == 1 and not batch.cancelled
    assert batch.written == [FLOOR_PLAN] and batch.results[1].written == [FLOOR_PLAN]
    assert batch.changes == {}
    assert any("Written before this step and kept" in w for w in batch.results[1].warnings)
    assert '"label": "D"' in (copy / FLOOR_PLAN).read_text(encoding="utf-8")


def test_edits_after_the_last_run_step_are_written_with_the_batch(copy):
    batch = run(
        copy,
        ("grid.line.add", {"axis": "x", "position": 15000}),
        ("run.step", {"step": "derive"}),
        ("grid.line.add", {"axis": "y", "position": 8000}),
        write=True,
    )
    assert batch.ok, [r.message for r in batch.results]
    assert batch.results[1].written == [FLOOR_PLAN]
    assert batch.results[2].written == []  # an edit writes nothing itself
    assert FLOOR_PLAN in batch.written and FLOOR_PLAN in batch.changes


# ─────────────────────────────── guardrails through the actions ───────────────────────────────


def _refused(batch: BatchResult) -> str:
    assert not batch.ok and batch.changes == {}, [r.message for r in batch.results]
    failed = batch.results[batch.failed_step or 0]
    return failed.message + " " + " ".join(p.reason for p in failed.problems)


def test_ai_mistakes_are_refused_with_the_allowed_range(base):
    text = _refused(run(base, ("storeys.set", {"count": 2, "height": 30000})))
    assert "above 20000 mm" in text and "2.8 to 4.5 m" in text
    text = _refused(run(base, ("grid.set", {"x": [5, 5], "y": [4]})))
    assert "below 100 mm" in text
    text = _refused(
        run(
            base,
            ("type.beam.add", {"id": "B250x300", "width": 250, "depth": 300}),
            ("grid.set", {"x": [12000, 12000], "y": [4000]}),
            ("member.set", {"ids": ["B1"], "type": "B250x300"}),
        )
    )
    assert "span/depth" in text and "at least 350 mm deep" in text
    text = _refused(run(base, ("load.area.set", {"id": "FL", "L": 2000})))
    assert "kN/m²" in text and "psf" in text


def test_storeys_above_the_systems_height_limit_are_refused(base):
    # Dhaka, site class SD: Category D, where an ordinary concentric braced frame stops at 11 m.
    system = ("settings.site", {"seismicSystem": "steelOcbf"})
    assert run(base, system, ("storeys.set", {"count": 3, "height": 3000})).ok
    batch = run(base, system, ("storeys.set", {"count": 6, "height": 3000}))
    text = _refused(batch)
    assert batch.failed_step == 1 and "18.0 m tall (6 storeys)" in text
    assert "11 m height limit" in text and "at most 3 storeys of 3.0 m" in text
    # Raising the system's storeys refuses the settings change the same way.
    tall = run(base, ("storeys.set", {"count": 6, "height": 3000}), system)
    assert not tall.ok and tall.failed_step == 1 and "height limit" in _refused(tall)
