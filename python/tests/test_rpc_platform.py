"""The RPC methods of the project archive (.civil) and the version history, as the workbench
calls them (synthetic copies of the sample project only)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import saengine
from saengine.rpc import handlers

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "work" / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    return root


def test_archive_round_trip_through_the_handlers(project: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "Sample Frame.civil"
    out.parent.mkdir()
    written = handlers.project_export_archive(
        str(project), str(out), include_versions=True, saengine_version="0.0.34"
    )
    assert written["path"] == str(out) and out.is_file()
    assert written["files"] > 5

    inspected = handlers.project_inspect_archive(str(out), "0.0.34")
    assert inspected["ok"]
    manifest = inspected["manifest"]
    assert manifest["project"]["name"] == "Sample Frame"
    assert manifest["saengineVersion"] == "0.0.34"
    # The sidebar's statuses are recorded, as the CLI's export does.
    assert any("status" in part for part in manifest["parts"]), manifest["parts"]

    dest = tmp_path / "dest"
    imported = handlers.project_import_archive(str(out), str(dest), "Received", False, "0.0.34")
    assert Path(imported["root"]) == dest / "Received"
    assert (dest / "Received" / "Received.saengine").is_file()


def test_refusals_are_answers_not_errors(project: Path, tmp_path: Path) -> None:
    missing = handlers.project_inspect_archive(str(tmp_path / "nothing.civil"))
    assert missing["ok"] is False and missing["problems"]

    not_zip = tmp_path / "bad.civil"
    not_zip.write_text("not an archive", encoding="utf-8")
    refused = handlers.project_import_archive(str(not_zip), str(tmp_path / "dest"))
    assert refused["ok"] is False and refused["message"]
    assert not (tmp_path / "dest" / "bad").exists()

    nothing = handlers.versions_restore(str(project), "abc1234")
    assert nothing == {**nothing, "ok": False, "code": "notInitialized"}


def test_versions_through_the_handlers(project: Path) -> None:
    author = "Test Engineer <test@example.invalid>"
    assert handlers.versions_status(str(project))["initialized"] is False
    first = handlers.versions_save(str(project), "First", author=author)
    assert first["initialized"] is True

    settings = next((project / "02 Project Settings").glob("*.json"))
    data = json.loads(settings.read_text(encoding="utf-8"))
    data["_test"] = 1
    settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
    status = handlers.versions_status(str(project))
    assert status["changedParts"] == ["settings"]

    second = handlers.versions_save(
        str(project), "Second", author=author, issued=True, label="Tender"
    )
    listed = handlers.versions_list(str(project))
    assert [v["message"] for v in listed["versions"]] == ["Second", "First"]
    assert (
        listed["versions"][0]["issued"] and listed["versions"][0]["authorName"] == "Test Engineer"
    )

    compared = handlers.versions_diff(str(project), first["version"]["id"], second["version"]["id"])
    assert [p["part"] for p in compared["parts"]] == ["settings"]

    restored = handlers.versions_restore(str(project), first["version"]["id"], ["settings"], author)
    assert restored["parts"] == ["settings"]
    assert "_test" not in json.loads(settings.read_text(encoding="utf-8"))

    issued = handlers.versions_mark_issued(str(project), "HEAD", "IFC", author)
    assert issued["tag"].startswith("issued/")

    empty = handlers.versions_save(str(project), "Nothing", author=author)
    assert empty["ok"] is False and empty["code"] == "nothingToSave"


def _rpc(proc: subprocess.Popen, ident: int, method: str, params: dict) -> dict:
    _send(proc, ident, method, params)
    return _receive(proc)


def _send(proc: subprocess.Popen, ident: int, method: str, params: dict) -> None:
    body = json.dumps({"jsonrpc": "2.0", "id": ident, "method": method, "params": params}).encode()
    proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    proc.stdin.flush()


def _receive(proc: subprocess.Popen) -> dict:
    length = 0
    while True:
        line = proc.stdout.readline().strip()
        if not line:
            break
        name, _, value = line.partition(b":")
        if name.lower() == b"content-length":
            length = int(value)
    return json.loads(proc.stdout.read(length))


def test_stdio_methods_are_registered(project: Path, tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "saengine.rpc"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        out = tmp_path / "p.civil"
        exported = _rpc(
            proc, 1, "project/exportArchive", {"projectRoot": str(project), "outPath": str(out)}
        )["result"]
        assert exported["path"] == str(out)
        inspected = _rpc(proc, 2, "project/inspectArchive", {"path": str(out)})["result"]
        assert inspected["manifest"]["saengineVersion"] == saengine.__version__
        dest = tmp_path / "in"
        imported = _rpc(
            proc, 3, "project/importArchive", {"path": str(out), "destParent": str(dest)}
        )["result"]
        assert Path(imported["root"]).is_dir()
        status = _rpc(proc, 4, "versions/status", {"projectRoot": str(project)})["result"]
        assert status["initialized"] is False
        saved = _rpc(proc, 5, "versions/save", {"projectRoot": str(project), "message": "One"})[
            "result"
        ]
        assert saved["initialized"] is True
        first = saved["version"]["id"]
        settings = project / "02 Project Settings" / "project-settings.json"
        text = settings.read_text(encoding="utf-8")
        settings.write_text(text.replace('"chattogram"', '"dhaka"'), encoding="utf-8")
        _rpc(proc, 10, "versions/save", {"projectRoot": str(project), "message": "Two"})
        # Two versions compared by id: the names are not "from"/"to", which pygls would rename.
        compared = _rpc(
            proc,
            11,
            "versions/diff",
            {"projectRoot": str(project), "fromVersion": first, "toVersion": "HEAD"},
        )["result"]
        assert [p["part"] for p in compared["parts"]] == ["settings"]
        for ident, method, params in (
            (6, "versions/list", {"projectRoot": str(project)}),
            (7, "versions/diff", {"projectRoot": str(project), "fromVersion": "HEAD~0"}),
            (
                8,
                "versions/markIssued",
                {"projectRoot": str(project), "version": "HEAD", "label": "A"},
            ),
            (9, "versions/restore", {"projectRoot": str(project), "version": "HEAD"}),
        ):
            answer = _rpc(proc, ident, method, params)
            assert "result" in answer, answer
    finally:
        proc.kill()
        proc.wait()


def test_a_long_save_does_not_hold_up_other_requests(project: Path) -> None:
    # Large files that are not computed caches (scans, drawings): a save takes seconds.
    notes = project / "Notes"
    notes.mkdir()
    for i in range(2):
        (notes / f"scan-{i}.bin").write_bytes(os.urandom(40 * 1024**2))
    proc = subprocess.Popen(
        [sys.executable, "-m", "saengine.rpc"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert "result" in _rpc(proc, 1, "mep/electricalUses", {})  # loaded once
        _send(proc, 2, "versions/save", {"projectRoot": str(project), "message": "Scans"})
        time.sleep(0.2)
        _send(proc, 3, "mep/electricalUses", {})
        _send(proc, 4, "versions/status", {"projectRoot": str(project)})
        answers = [_receive(proc) for _ in range(3)]
        # The quick request first; the project's status waits for its save (same project).
        assert [a["id"] for a in answers] == [3, 2, 4], answers
        assert answers[1]["result"]["initialized"] is True
        assert answers[2]["result"]["changedParts"] == []
    finally:
        proc.kill()
        proc.wait()
