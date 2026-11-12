"""A whole project by the shared editing actions alone: an empty folder and a batch file
(tests/data/actions/three-storey-rc.json) give a three-storey, 3x2-bay RC frame with slabs,
loads and footings, Run All, Design Reinforcement, Run All again and the report; then the
exports. About a minute and a half, so it runs in the normal suite."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from saengine.actions import BatchResult, load_steps, run_actions

BATCH = Path(__file__).parent / "data" / "actions" / "three-storey-rc.json"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, BatchResult, float]:
    root = tmp_path_factory.mktemp("e2e") / "Three Storey RC"
    started = time.monotonic()
    result = run_actions(root, load_steps(BATCH.read_text(encoding="utf-8")), write=True)
    return root, result, time.monotonic() - started


def _step(result: BatchResult, name: str, nth: int = 0):
    return [r for r in result.results if r.action == name][nth]


def test_an_empty_folder_becomes_a_designed_building(built):
    root, result, seconds = built
    messages = [f"{r.action}: {r.message}" for r in result.results]
    assert result.ok, messages
    assert result.failed_step is None and seconds < 300
    plan = json.loads((root / "05 Floor Plan" / "floor-plan.json").read_text(encoding="utf-8"))
    assert len(plan["stories"]) == 4 and plan["stories"][3]["similarTo"] == "L2"
    assert (len(plan["columns"]), len(plan["beams"]), len(plan["slabs"])) == (36, 51, 18)
    assert _step(result, "columns.place").created[:2] == ["C1", "C2"]
    loads = json.loads((root / "05 Floor Plan" / "loads.json").read_text(encoding="utf-8"))
    assert loads["loads"] and all(x["wall"]["auto"] for x in loads["loads"])
    footings = _step(result, "foundations.generate")
    assert len(footings.created) == 12
    # The first Run All has no bars to check (the design step says so); Design Reinforcement
    # gives the types their bars; the second Run All checks them and writes the report.
    first = _step(result, "run.all", 0).data
    assert {s["id"]: s["status"] for s in first["steps"]}["design"] == "failed"
    applied = _step(result, "design.reinforcement.apply")
    assert "C400" in applied.message and "B300x500" in applied.message
    objects = json.loads((root / "04 Objects" / "objects.json").read_text(encoding="utf-8"))
    assert all(
        "reinforcement" in o for o in objects["objects"] if o["id"] in ("C400", "B300x500", "S150")
    )
    second = {s["id"]: s for s in _step(result, "run.all", 1).data["steps"]}
    assert second["design"]["status"] in ("ok", "warning"), second["design"]["message"]
    assert second["report"]["status"] == "ok"
    assert (root / "11 Exports" / "report.pdf").is_file()


def test_the_checks_pass_or_fail_cleanly(built):
    _root, result, _seconds = built
    summary = _step(result, "results.summary").data
    states = {p["part"]: p["state"] for p in summary["parts"]}
    assert states["floorPlan"] == "done" and states["bim"] == "done"
    assert states["fem"] in ("done", "failed") and states["substructure"] in ("done", "failed")
    design = summary["design"]
    assert design["counts"]["members"]["checked"] == 105
    checks = _step(result, "checks.list").data
    assert len(checks["members"]) == design["counts"]["members"]["failed"]
    assert all(isinstance(c["name"], str) for c in checks["building"])


@pytest.mark.parametrize(
    ("name", "params", "suffix"),
    [
        ("export.ifc", {}, ".ifc"),
        ("export.boq", {"format": "xlsx"}, ".xlsx"),
        ("export.report", {"format": "pdf"}, ".pdf"),
        ("export.drawings", {}, ".pdf"),
        ("export.archive", {}, ".civil"),
    ],
)
def test_exports(built, name, params, suffix):
    root, _result, _seconds = built
    batch = run_actions(root, [{"action": name, "params": params}])
    assert batch.ok, batch.results[0].message
    files = [Path(f) for f in batch.results[0].data["files"]]
    assert any(f.suffix == suffix and f.is_file() for f in files), files
