"""The playbook "one prompt -> a designed building" with a scripted fake model, through the
actions RPC (``actions/list``, ``actions/run`` of ``python -m saengine.rpc``) on the real engine.

The fake model plays what a real one does for "a 3-storey RC residential building in Dhaka, 3x2
bays of 5 m, designed": it reads the catalogue, creates the project, sends the edits as change
sets and the runs on their own, makes the typical mistakes (a storey of 30 m, an edit inside a
run batch), reads the refusals and corrects them, then Run All, Design Reinforcement, Run All
again and the report. The real-model version is scripts/ai/smoke_build.py (opt-in, never in CI).
About two minutes: marked slow (the full checks run it).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.ai_host import Engine, Host

pytestmark = pytest.mark.slow

PROMPT = (
    "A 3-storey RC residential building in Dhaka, 3x2 bays of 5 m, 3 m storeys, designed, "
    "with its report."
)

Call = tuple[str, dict[str, Any]]
#: One turn of the fake model: the last answer -> the next tool call (or None: it is done).
Turn = Callable[[bool, Any], Call | None]


def _batch(title: str, *steps: tuple[str, dict[str, Any]]) -> Call:
    return "run_actions", {
        "title": title,
        "steps": [{"action": a, "params": p} for a, p in steps],
    }


def fake_model() -> Iterator[Turn]:
    """The script, as turns that look at the answer before them (as a model reads it)."""
    yield lambda ok, answer: ("list_actions", {})

    def describe(ok: bool, answer: Any) -> Call:
        writing = {a["name"] for a in answer["actions"] if a["writes"]}
        assert {"project.create", "run.all", "design.reinforcement.apply"} <= writing
        return "describe_action", {"name": "storeys.set"}

    yield describe
    yield lambda ok, answer: _batch(
        "Create the project",
        ("project.create", {"name": "Playbook", "occupancy": "residential"}),
    )
    edits = [
        ("settings.site", {"location": "dhaka", "siteClass": "SD"}),
        ("material.concrete.add", {"fc": 28, "makeDefault": True}),
        ("soil.allowable_bearing.set", {"value": 150}),
        ("grid.set", {"x": [5000, 5000, 5000], "y": [5000, 5000]}),
    ]

    def first_try(ok: bool, answer: Any) -> Call:
        assert ok, answer
        # The typical mistake: a storey of 30 m (a "30 m" read as the storey's height).
        return _batch(
            "Site, grid and storeys", *edits, ("storeys.set", {"count": 3, "height": 30000})
        )

    yield first_try

    def corrected(ok: bool, answer: Any) -> Call:
        assert not ok and answer["failedStep"] == 4
        refused = answer["results"][4]
        assert "above 20000 mm" in json.dumps(refused)  # the allowed range, word for word
        return _batch(
            "Site, grid and storeys",
            *edits,
            ("storeys.set", {"count": 3, "height": 3000, "typical": True}),
        )

    yield corrected

    def members(ok: bool, answer: Any) -> Call:
        assert ok and answer["decision"] == "accepted", answer
        return _batch(
            "Types and members",
            ("type.column.add", {"id": "C400", "width": 400, "depth": 400}),
            ("type.beam.add", {"id": "B300x500", "width": 300, "depth": 500}),
            ("type.slab.add", {"id": "S150", "thickness": 150}),
            ("columns.place", {"type": "C400"}),
            ("beams.place", {"type": "B300x500"}),
            ("slabs.place", {"type": "S150"}),
        )

    yield members

    def mixed(ok: bool, answer: Any) -> Call:
        assert ok, answer
        # The second typical mistake: an edit and a run in one batch.
        return _batch(
            "Loads and analysis",
            ("load.area.set", {"id": "FL", "SD": 1.5}),
            ("run.step", {"step": "analyse"}),
        )

    yield mixed

    def split(ok: bool, answer: Any) -> Call:
        assert not ok and "load.area.set" in answer and "batch of their own" in answer
        return _batch(
            "Loads",
            ("load.area.set", {"id": "FL", "SD": 1.5}),
            ("load.wall.add", {"storeys": ["L1"], "openings": 25}),
        )

    yield split
    yield lambda ok, answer: _batch("Analysis", ("run.step", {"step": "analyse"}))

    def footings(ok: bool, answer: Any) -> Call:
        assert ok, answer
        # The loads were saved before the run (the change set the engineer accepted).
        return _batch("Footings", ("foundations.generate", {}))

    yield footings
    yield lambda ok, answer: _batch("Run All", ("run.all", {}))
    yield lambda ok, answer: _batch("Design Reinforcement", ("design.reinforcement.apply", {}))
    yield lambda ok, answer: _batch(
        "Run All with the bars, results",
        ("run.all", {}),
        ("results.summary", {}),
        ("checks.list", {"failing": True}),
    )
    yield lambda ok, answer: None


@pytest.fixture(scope="module")
def played(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Host]:
    root = tmp_path_factory.mktemp("playbook") / "Playbook"
    engine = Engine()
    try:
        host = Host(engine, root)
        ok, answer = True, {"prompt": PROMPT}
        for turn in fake_model():
            call = turn(ok, answer)
            if call is None:
                break
            ok, answer = host.call(*call)
    finally:
        engine.close()
    return root, host


def test_one_prompt_gives_a_designed_building(played):
    root, host = played
    tools = [t["tool"] for t in host.transcript]
    assert tools[:2] == ["list_actions", "describe_action"]
    refused = [t for t in host.transcript if not t["ok"]]
    assert len(refused) == 2  # the 30 m storey and the mixed batch, both corrected
    plan = json.loads((root / "05 Floor Plan" / "floor-plan.json").read_text(encoding="utf-8"))
    assert len(plan["stories"]) == 4
    assert (len(plan["columns"]), len(plan["beams"]), len(plan["slabs"])) == (36, 51, 18)
    last = host.transcript[-1]
    assert last["ok"], last["answer"]
    steps = {s["id"]: s for s in last["answer"]["results"][0]["data"]["steps"]}
    assert steps["design"]["status"] in ("ok", "warning"), steps["design"]["message"]
    assert steps["report"]["status"] == "ok"
    assert (root / "11 Exports" / "report.pdf").is_file()


def test_each_answer_says_what_was_written(played):
    _root, host = played
    runs = [t for t in host.transcript if t["ok"] and "written" in t["answer"]]
    assert runs and all(isinstance(t["answer"]["written"], list) for t in runs)
    accepted = [t for t in host.transcript if t["ok"] and t["answer"].get("decision")]
    assert all(t["answer"]["files"] for t in accepted)
    assert sum(t["seconds"] for t in host.transcript) < 600
