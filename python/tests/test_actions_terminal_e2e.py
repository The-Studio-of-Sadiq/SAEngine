"""Issue #280: a whole project from the terminal alone. Each step is a ``saengine <noun> <verb>``
command (as an engineer would type it): an empty folder becomes a two-storey RC frame with a
load pattern of its own, Run All, Design Reinforcement, Run All again; the results, the report
and the bill of quantities exist, and the last edit can be undone. About a minute."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from saengine.actions.paths import OBJECTS, SETTINGS
from saengine.cli import main

COMMANDS = """
project create --name "Terminal Frame" --occupancy residential
settings site --location dhaka --siteClass SD
material concrete add --fc 28 --makeDefault true
soil allowable-bearing set --value 150
grid set --x 5000 5000 --y 4000
storeys set --count 2 --height 3000
type column add --id C400 --width 400 --depth 400
type beam add --id B300x500 --width 300 --depth 500
type slab add --id S150 --thickness 150
member add column --type C400
member add beam --type B300x500
member add slab --type S150
load area set --id FL --SD 1.5
load pattern add EQP --name Equipment --type Dead
load line add --beams B1 --value 3 --case EQP
run step analyse
foundations generate
run all
design apply
run all
"""


def _run(root: Path, line: str, capsys: pytest.CaptureFixture[str]) -> dict:
    code = main([*shlex.split(line), "--project", str(root), "--json"])
    document = json.loads(capsys.readouterr().out)
    batch = document.get("batch") or {}
    messages = [f"{r['action']}: {r['message']}" for r in batch.get("results") or []]
    assert code == 0, (line, messages, document.get("error"))
    return batch


def test_a_project_from_the_terminal(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    root = tmp_path / "Terminal Frame"
    done: dict[str, dict] = {}
    for line in filter(None, (x.strip() for x in COMMANDS.splitlines())):
        done[line] = _run(root, line, capsys)
    settings = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    assert [p["id"] for p in settings["loadPatterns"]] == ["EQP"]
    # Design Reinforcement gives the types their bars; the last Run All checks them.
    applied = done["design apply"]["results"][0]
    assert "C400" in applied["message"] and "B300x500" in applied["message"]
    objects = json.loads((root / OBJECTS).read_text(encoding="utf-8"))
    assert all("reinforcement" in o for o in objects["objects"] if o["id"] in ("C400", "B300x500"))
    last = {s["id"]: s for s in done["run all"]["results"][0]["data"]["steps"]}
    assert last["design"]["status"] in ("ok", "warning"), last["design"]["message"]
    assert last["report"]["status"] == "ok"
    assert (root / "11 Exports" / "report.pdf").is_file()
    assert any((root / "08 FEM").rglob("*")), "the analysis results"
    # The terminal's undo takes back the last written edits (the bars), and redo brings them back.
    _run(root, "undo", capsys)
    objects = json.loads((root / OBJECTS).read_text(encoding="utf-8"))
    assert not any("reinforcement" in o for o in objects["objects"] if o["id"] == "C400")
    _run(root, "redo", capsys)
    objects = json.loads((root / OBJECTS).read_text(encoding="utf-8"))
    assert all("reinforcement" in o for o in objects["objects"] if o["id"] == "C400")
