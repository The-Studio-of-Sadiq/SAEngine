"""Backend tests against opensees-studio's verified examples."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from saengine.rpc import handlers

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "third_party" / "opensees-studio" / "examples"
SPACE_FRAME = EXAMPLES / "space_frame_3d.osmodel"
SAMPLE = REPO / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"


def test_info_reports_backend_versions() -> None:
    info = handlers.info()
    assert info["python"].startswith("3.12")
    assert info["openseespy"] and info["openseesStudio"]


def test_validate_example_project() -> None:
    result = handlers.validate_project(str(SPACE_FRAME))
    assert result["ok"], result["errors"]
    summary = result["summary"]
    assert (summary["nodes"], summary["elements"]) == (12, 16)
    assert [a["type"] for a in summary["analyses"]] == [
        "StaticCase",
        "ModalCase",
        "TransientCase",
        "ResponseSpectrumCase",
    ]


def test_validate_reports_bad_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.osmodel"
    bad.write_text("{ not json", encoding="utf-8")
    result = handlers.validate_project(str(bad))
    assert not result["ok"] and result["errors"]


@pytest.fixture(scope="module")
def space_frame_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run the static, modal and response-spectrum cases through the opensees-studio CLI."""
    out = tmp_path_factory.mktemp("run")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(SPACE_FRAME),
            "--cases",
            "1",
            "2",
            "4",
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    events = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [e["case_id"] for e in events if e["type"] == "case_finished"] == [1, 2, 4]
    return out


def test_results_tables(space_frame_run: Path) -> None:
    cases = handlers.results_tables(str(space_frame_run), str(SPACE_FRAME))["cases"]
    by_type = {c["resultType"]: c for c in cases}
    assert set(by_type) == {"StaticResults", "ModalResults", "ResponseSpectrumResults"}

    static = by_type["StaticResults"]["tables"]
    assert [t["name"] for t in static] == ["Displacements", "Reactions", "Element forces"]
    assert len(static[0]["rows"]) == 12  # one row per node

    modal = by_type["ModalResults"]["tables"][0]
    assert len(modal["rows"]) == 6
    periods = [row[-1] for row in modal["rows"]]
    assert all(isinstance(t, float) and t > 0 for t in periods)
    assert periods == sorted(periods, reverse=True)

    # Everything must survive JSON encoding (no NaN/inf floats).
    json.dumps(cases, allow_nan=False)


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


def test_stdio_server_round_trip() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "saengine.rpc"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        info = _rpc(proc, 1, "saengine/info", {})
        assert info["result"]["python"].startswith("3.12")
        validated = _rpc(proc, 2, "project/validate", {"path": str(SPACE_FRAME)})
        assert validated["result"]["ok"]
        # Keys that are not Python names reach the handler as sent (a split proposal's "from").
        objects = SAMPLE / "04 Objects" / "objects.json"
        first = json.loads(objects.read_text(encoding="utf-8"))["objects"][0]["id"]
        applied = _rpc(
            proc,
            3,
            "design/applyProposal",
            {
                "objectsText": objects.read_text(encoding="utf-8"),
                "bimText": None,
                "proposal": {
                    "types": [],
                    "newTypes": [{"type": "X-2", "from": first, "proposed": {}, "apply": False}],
                    "reassign": [{"member": "M1", "from": first, "to": "X-2", "apply": False}],
                },
            },
        )
        assert "error" not in applied, applied
    finally:
        proc.kill()
        proc.wait()
