"""Coordination issues (status workflow), BCF 3.0 round trip and the IDS check's fallback."""

from __future__ import annotations

import io
import zipfile

import pytest

from saengine.library.mep import Coordination, Issue, MepModel
from saengine.mep import bcf, coordination


def _clash(key: str, test: str = "T1") -> dict:
    return {
        "key": key,
        "test": test,
        "elements": ["A" * 22, "B" * 22],
        "labels": ["Beam B1", "DuctSegment D1"],
        "point": [1000.0, 2000.0, 3000.0],
        "story": "L1",
    }


def test_default_tests_are_valid():
    coord = coordination.coordination_of(MepModel())
    assert [t.id for t in coord.tests] == ["T1", "T2", "T3", "T4", "T5"]
    assert coord.tests[2].ignoreSameModel


def test_new_clashes_become_new_issues():
    merged, counts = coordination.merge_found(
        Coordination(), [_clash("T1:a:b"), _clash("T1:c:d")], {"T1"}, stamp="2026-11-01T00:00:00"
    )
    assert counts == {"new": 2, "reopened": 0, "resolved": 0, "open": 2}
    assert [i.id for i in merged.issues] == ["C1", "C2"]
    assert merged.issues[0].status == "new"
    assert merged.issues[0].title == "Beam B1 vs DuctSegment D1"
    assert merged.issues[0].guid


def test_status_is_kept_and_missing_clashes_resolve():
    first, _ = coordination.merge_found(Coordination(), [_clash("T1:a:b")], {"T1"})
    first.issues[0].status = "reviewed"
    first.issues[0].assignedTo = "MEP consultant"
    again, counts = coordination.merge_found(first, [_clash("T1:a:b")], {"T1"})
    assert again.issues[0].status == "reviewed"
    assert again.issues[0].assignedTo == "MEP consultant"
    assert counts["new"] == 0
    gone, counts = coordination.merge_found(again, [], {"T1"})
    assert gone.issues[0].status == "resolved"
    assert counts["resolved"] == 1
    assert "resolved" in gone.issues[0].comments[-1].text


def test_resolved_issue_found_again_is_reopened():
    first, _ = coordination.merge_found(Coordination(), [_clash("T1:a:b")], {"T1"})
    first.issues[0].status = "closed"
    again, counts = coordination.merge_found(first, [_clash("T1:a:b")], {"T1"})
    assert again.issues[0].status == "active"
    assert counts["reopened"] == 1


def test_tests_not_run_leave_their_issues_alone():
    first, _ = coordination.merge_found(Coordination(), [_clash("T2:a:b", "T2")], {"T2"})
    again, counts = coordination.merge_found(first, [], {"T1"})
    assert again.issues[0].status == "new"
    assert counts["resolved"] == 0


def test_bcf_round_trip():
    coord, _ = coordination.merge_found(Coordination(author="Engineer"), [_clash("T1:a:b")], {"T1"})
    coord.issues[0].status = "active"
    coord.issues[0].priority = "high"
    data = bcf.export_bcf(coord, ["model.ifc"])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert "bcf.version" in names and "extensions.xml" in names
        assert b'VersionId="3.0"' in archive.read("bcf.version")
        guid = coord.issues[0].guid
        assert f"{guid}/markup.bcf" in names
        assert any(n.startswith(guid) and n.endswith(".bcfv") for n in names)
    topics = bcf.read_bcf(data)
    assert len(topics) == 1
    topic = topics[0]
    assert topic["guid"] == guid
    assert topic["status"] == "active"
    assert topic["priority"] == "high"
    assert topic["elements"] == ["A" * 22, "B" * 22]
    # the camera looks at the issue's point
    assert topic["point"] == pytest.approx([1000.0, 2000.0, 3000.0], abs=1.0)


def test_bcf_import_updates_and_adds():
    coord, _ = coordination.merge_found(Coordination(), [_clash("T1:a:b")], {"T1"})
    exported = coord.model_copy(deep=True)
    exported.issues[0].status = "resolved"
    exported.issues[0].assignedTo = "Architect"
    exported.issues[0].comments = [
        bcf.IssueComment(guid="c1", date="2026-11-01T10:00:00Z", author="A", text="Moved duct")
    ]
    extra = Issue(id="X9", guid="0c3a7ad4-7f0b-4f1e-9b0d-6c0a6b8a2c11", title="Door swing")
    exported.issues.append(extra)
    topics = bcf.read_bcf(bcf.export_bcf(exported))
    merged, counts = bcf.merge_bcf(coord, topics)
    assert counts == {"updated": 1, "added": 1, "comments": 1}
    assert merged.issues[0].status == "resolved"
    assert merged.issues[0].assignedTo == "Architect"
    assert merged.issues[1].id == "B1" and merged.issues[1].source == "bcf"
    # importing the same file again adds nothing
    _, counts = bcf.merge_bcf(merged, topics)
    assert counts["added"] == 0 and counts["comments"] == 0


def test_bcf_statuses_of_other_tools():
    assert bcf.status_of("Open") == "active"
    assert bcf.status_of("Closed") == "closed"
    assert bcf.status_of("In Progress") == "active"
    assert bcf.priority_of("Medium") == "normal"


def test_ids_without_ifctester_says_so(monkeypatch):
    from saengine.mep import ids

    if ids.available():
        pytest.skip("IfcTester is installed")
    with pytest.raises(RuntimeError, match="IfcTester"):
        ids.check_ids(".")
