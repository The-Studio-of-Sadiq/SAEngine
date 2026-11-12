"""Tests for saengine.project.share: the office copy of a project's versions (shared folder)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from saengine.project import share, versions
from saengine.project.share import ShareError

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"
FLOOR = "05 Floor Plan/floor-plan.json"
MATERIALS = "03 Materials/materials.json"
SETTINGS = "02 Project Settings/project-settings.json"


def _project(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    shutil.copytree(SAMPLE, root)
    return root


def _edit(root: Path, relative: str, key: str, value: object) -> None:
    data = json.loads((root / relative).read_text("utf-8"))
    data[key] = value
    (root / relative).write_text(json.dumps(data, indent="\t"), encoding="utf-8")


def _read(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text("utf-8"))


def test_three_way_takes_one_sided_changes_and_reports_conflicts_by_part():
    base = {FLOOR: b"f0", MATERIALS: b"m0", SETTINGS: b"s0"}
    mine = {FLOOR: b"f1", MATERIALS: b"m0", SETTINGS: b"s1"}
    theirs = {FLOOR: b"f0", MATERIALS: b"m2", SETTINGS: b"s2", "README.txt": b"r"}
    merged, conflicts = share.three_way(base, mine, theirs)
    assert merged[FLOOR] == b"f1"  # changed here only
    assert merged[MATERIALS] == b"m2"  # changed there only
    assert merged["README.txt"] == b"r"  # added there
    assert conflicts == {"settings": [SETTINGS]}  # changed differently on both sides
    # Deleted on one side, unchanged on the other: deleted.
    merged, conflicts = share.three_way({FLOOR: b"f0"}, {}, {FLOOR: b"f0"})
    assert merged == {} and conflicts == {}


def test_share_join_sync_and_merge_per_part(tmp_path: Path):
    office = tmp_path / "office"
    alice = _project(tmp_path, "alice")
    result = share.connect(alice, str(office), author="Alice <a@office>")
    assert result["sent"] is True
    assert (office / share.MARKER).is_file() and (office / share.HISTORY).is_dir()

    bob = tmp_path / "bob" / "Tower"
    share.join(str(office), bob)
    assert _read(bob, FLOOR) == _read(alice, FLOOR)

    # Different parts on each side merge without a question.
    _edit(alice, FLOOR, "aliceNote", 1)
    _edit(bob, MATERIALS, "bobNote", 2)
    assert share.sync(alice, author="Alice <a@office>")["state"] == "sent"
    merged = share.sync(bob, author="Bob <b@office>")
    assert merged["state"] == "merged" and merged["sent"] is True
    assert _read(bob, FLOOR)["aliceNote"] == 1 and _read(bob, MATERIALS)["bobNote"] == 2
    received = share.sync(alice)
    assert received["state"] == "received"
    assert _read(alice, MATERIALS)["bobNote"] == 2

    # The same part on both sides: a conflict, settled per part.
    _edit(alice, FLOOR, "who", "alice")
    _edit(bob, FLOOR, "who", "bob")
    share.sync(alice)
    asked = share.sync(bob)
    assert asked["state"] == "conflicts"
    assert [c["part"] for c in asked["conflicts"]] == ["floorPlan"]
    assert _read(bob, FLOOR)["who"] == "bob"  # nothing changed until resolved
    done = share.sync(bob, resolutions={"floorPlan": "theirs"})
    assert done["state"] == "merged"
    assert _read(bob, FLOOR)["who"] == "alice"
    assert versions.status(bob)["clean"]


def test_locks_block_sending_a_locked_part(tmp_path: Path):
    office = tmp_path / "office"
    alice = _project(tmp_path, "alice")
    share.connect(alice, str(office))
    bob = tmp_path / "bob"
    share.join(str(office), bob)

    share.lock(alice, "floorPlan", user="alice")
    with pytest.raises(ShareError) as taken:
        share.lock(bob, "floorPlan", user="bob")
    assert taken.value.code == "locked"
    _edit(bob, FLOOR, "who", "bob")
    with pytest.raises(ShareError) as blocked:
        share.sync(bob, user="bob")
    assert blocked.value.code == "locked"
    # Bob's version is kept here, and other parts still go through after the lock is released.
    with pytest.raises(ShareError):
        share.unlock(bob, "floorPlan", user="bob")
    assert share.unlock(alice, "floorPlan", user="alice")["released"] is True
    assert share.sync(bob, user="bob")["sent"] is True
    listed = share.locks(alice, user="alice")["locks"]
    assert listed == []


def test_presence_and_not_shared(tmp_path: Path):
    alice = _project(tmp_path, "alice")
    assert share.status(alice) == {"shared": False}
    share.connect(alice, str(tmp_path / "office"))
    people = share.heartbeat(alice, user="alice", part="fem")["people"]
    assert [(p["user"], p["part"], p["me"]) for p in people] == [("alice", "fem", True)]
    assert share.heartbeat(alice, user="alice", leaving=True)["people"] == []
    status = share.status(alice, user="alice")
    assert status["shared"] and status["kind"] == "folder" and status["ahead"] == 0


def test_a_folder_that_is_not_a_share_is_refused(tmp_path: Path):
    alice = _project(tmp_path, "alice")
    other = tmp_path / "other"
    other.mkdir()
    (other / "notes.txt").write_text("x")
    with pytest.raises(ShareError) as refused:
        share.connect(alice, str(other))
    assert refused.value.code == "notShareFolder"
    assert share.is_url("https://git.office.local/tower.git")
    assert share.is_url("git@git.office.local:tower.git")
    assert not share.is_url(r"\\office\projects\tower")
