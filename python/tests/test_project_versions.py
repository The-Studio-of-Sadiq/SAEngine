"""Tests for saengine.project.versions: an engineer's version history kept in git (dulwich)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from dulwich.index import commit_tree
from dulwich.object_store import iter_tree_contents
from dulwich.objects import Blob, Commit, Tag
from dulwich.repo import Repo

from saengine.project import versions
from saengine.project.archive import COMPUTED_PATHS
from saengine.project.versions import VersionsError

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"
FLOOR = "05 Floor Plan/floor-plan.json"
MATERIALS = "03 Materials/materials.json"
SOIL = "01 Soil Report/soil-report.json"

# A synthetic soil report (not a real client's).
SOIL_REPORT = {
    "schema": "saengine.soilReport/1",
    "report": {"title": "Synthetic site", "consultant": "Test Geotech"},
    "boreholes": [
        {
            "id": "BH-1",
            "x": 0,
            "y": 0,
            "waterTable": 1500,
            "depth": 12000,
            "layers": [{"top": 0, "bottom": 12000, "soilType": "clay", "cu": 20}],
            "spt": [{"depth": 3000, "N": 5}, {"depth": 6000, "N": 12}],
        },
    ],
}


def write_json(root: Path, relative: str, value: dict) -> None:
    (root / relative).write_text(json.dumps(value, indent="\t"), encoding="utf-8")


def read_json(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def edit(root: Path, relative: str, change) -> None:
    value = read_json(root, relative)
    change(value)
    write_json(root, relative, value)


def set_beam(section: str):
    def change(plan: dict) -> None:
        plan["beams"][0]["type"] = section

    return change


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A fresh copy of the sample in a folder with spaces, with computed caches present."""
    root = tmp_path / "Office Projects" / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    # Git keeps no empty folders: the sample's empty part folders exist only after a run.
    for folder in ("08 FEM", "11 Exports"):
        (root / folder).mkdir(exist_ok=True)
    write_json(root, SOIL, SOIL_REPORT)
    fem = root / "08 FEM"
    (fem / "model.results").mkdir(parents=True)
    (fem / "model.osmodel").write_text("{}", encoding="utf-8")
    (fem / "ssi.json").write_text("{}", encoding="utf-8")
    (fem / "model.results" / "design-summary.json").write_text("{}", encoding="utf-8")
    (root / "07 MEP" / "mep.results").mkdir()
    (root / "07 MEP" / "mep.results" / "summary.json").write_text("{}", encoding="utf-8")
    (root / "09 Substructure" / "substructure.results").mkdir()
    (root / "09 Substructure" / "substructure.results" / "s.json").write_text("{}", "utf-8")
    (root / "05 Floor Plan" / "Thumbs.db").write_bytes(b"junk")
    return root


def saved_paths(root: Path, version: str = "HEAD") -> set[str]:
    repo = Repo(str(root))
    try:
        commit = repo[repo.refs[b"HEAD"]] if version == "HEAD" else repo[version.encode()]
        assert isinstance(commit, Commit)
        return {e.path.decode() for e in iter_tree_contents(repo.object_store, commit.tree)}
    finally:
        repo.close()


def test_status_before_the_first_version(project: Path):
    state = versions.status(project)
    assert state["initialized"] is False and state["initialised"] is False
    assert state["head"] is None and state["count"] == 0
    assert state["changedParts"] == [
        "soil",
        "settings",
        "materials",
        "objects",
        "floorPlan",
        "bim",
        "mep",
        "substructure",
        "boq",
        "project",
    ]
    assert not (project / ".git").exists()
    assert versions.list_versions(project) == {"versions": [], "count": 0, "more": False}


def test_first_save_starts_a_git_repository(project: Path):
    result = versions.save(project, "First version")
    assert result["initialized"] is True and result["created"] is True
    version = result["version"]
    assert version["number"] == 1 and version["message"] == "First version"
    assert version["author"] == versions.DEFAULT_AUTHOR
    assert len(version["id"]) == 7 and version["sha"].startswith(version["id"])
    assert version["issued"] is False and version["label"] is None
    assert "soil" in version["parts"] and "project" in version["parts"]

    assert (project / ".git").is_dir()
    ignore = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in COMPUTED_PATHS:
        assert pattern in ignore
    assert "thumbs.db" in ignore

    paths = saved_paths(project)
    assert {
        SOIL,
        FLOOR,
        ".gitignore",
        "Sample Frame.saengine",
        "05 Floor Plan/Underlays/dimensions.dxf",
    } <= paths
    # The computed caches and the junk are not versioned.
    assert not any(p.startswith("08 FEM/") or ".results/" in p for p in paths)
    assert "05 Floor Plan/Thumbs.db" not in paths

    state = versions.status(project)
    assert state["initialized"] and state["clean"] and state["changedParts"] == []
    assert state["branch"] == "main" and state["head"]["id"] == version["id"]
    assert state["lastVersion"] == state["head"]


def test_author_from_the_setting(project: Path):
    version = versions.save(project, "v1", "Engineer Rahim <rahim@example.com>")["version"]
    assert version["author"] == "Engineer Rahim <rahim@example.com>"
    assert (version["authorName"], version["authorEmail"]) == (
        "Engineer Rahim",
        "rahim@example.com",
    )
    edit(project, FLOOR, set_beam("B300x600"))
    version = versions.save(project, "v2", {"name": "Karim", "email": ""})["version"]
    assert version["author"] == "Karim <user@localhost>"


def test_status_by_part(project: Path):
    versions.save(project, "First version")
    edit(project, FLOOR, set_beam("B300x600"))
    (project / "11 Exports" / "report.pdf").write_bytes(b"%PDF-1.7")
    (project / "05 Floor Plan" / "sample-plan.dxf").unlink()
    (project / "08 FEM" / "model.osmodel").write_text('{"changed": true}', encoding="utf-8")
    state = versions.status(project)
    assert state["changedParts"] == ["floorPlan", "exports"]
    assert state["parts"] == [
        {
            "part": "floorPlan",
            "title": "Floor Plan",
            "added": [],
            "modified": [FLOOR],
            "deleted": ["05 Floor Plan/sample-plan.dxf"],
        },
        {
            "part": "exports",
            "title": "Exports",
            "added": ["11 Exports/report.pdf"],
            "modified": [],
            "deleted": [],
        },
    ]


def test_save_without_changes(project: Path):
    versions.save(project, "First version")
    with pytest.raises(VersionsError) as error:
        versions.save(project, "Again")
    assert error.value.code == "nothingToSave"
    # An issued save of an unchanged project marks the last version.
    result = versions.save(project, "", issued=True, label="Tender")
    assert result["created"] is False
    assert result["version"]["issued"] and result["version"]["label"] == "Tender"
    assert versions.list_versions(project)["count"] == 1


def test_list_newest_first_with_parts(project: Path):
    versions.save(project, "First version")
    edit(project, FLOOR, set_beam("B300x600"))
    versions.save(project, "Deeper beam B1")
    edit(project, MATERIALS, lambda m: m["materials"][0]["concrete"].update(fc=24.1))
    edit(project, SOIL, lambda s: s["boreholes"][0]["spt"][1].update(N=9))
    versions.save(project, "Stronger concrete, revised SPT")
    listed = versions.list_versions(project)
    assert listed["count"] == 3 and listed["more"] is False
    assert [(v["number"], v["message"], v["parts"]) for v in listed["versions"][:2]] == [
        (3, "Stronger concrete, revised SPT", ["soil", "materials"]),
        (2, "Deeper beam B1", ["floorPlan"]),
    ]
    assert listed["versions"][1]["files"] == {
        "floorPlan": {"added": 0, "modified": 1, "deleted": 0}
    }
    limited = versions.list_versions(project, limit=1)
    assert [v["number"] for v in limited["versions"]] == [3] and limited["more"] is True


def test_semantic_diff(project: Path):
    first = versions.save(project, "First version")["version"]["id"]
    edit(project, FLOOR, set_beam("B300x600"))
    edit(project, SOIL, lambda s: s["boreholes"][0]["spt"][1].update(N=9))

    working = versions.diff(project)
    assert working["from"] == first and working["to"] == "working"
    assert [(p["part"], [c["what"] for c in p["changes"]]) for p in working["parts"]] == [
        ("soil", ["BH-1 SPT at 6 m: N 12 → 9 blows/300 mm"]),
        ("floorPlan", ["Beam B1: section B300x500 → B300x600"]),
    ]

    backwards = versions.diff(project, "working", first)["parts"][1]["changes"][0]
    assert (backwards["before"], backwards["after"]) == ("B300x600", "B300x500")

    second = versions.save(project, "Revised")["version"]["id"]
    between = versions.diff(project, first, second)
    assert (between["from"], between["to"]) == (first, second)
    assert [p["part"] for p in between["parts"]] == ["soil", "floorPlan"]
    assert versions.diff(project, "HEAD~1", "HEAD")["parts"] == between["parts"]
    assert versions.diff(project, second)["parts"] == []
    # The other way round.
    back = versions.diff(project, second, first)["parts"][1]["changes"][0]
    assert (back["before"], back["after"]) == ("B300x600", "B300x500")


def test_diff_before_any_version(project: Path):
    result = versions.diff(project)
    assert result["from"] is None
    floor = next(p for p in result["parts"] if p["part"] == "floorPlan")
    assert {c["kind"] for c in floor["changes"]} == {"added"}


def test_unknown_version(project: Path):
    versions.save(project, "First version")
    for bad in ("deadbeef", "issued/nothing", "HEAD~5"):
        with pytest.raises(VersionsError) as error:
            versions.diff(project, bad)
        assert error.value.code == "unknownVersion"


def test_restore_parts_is_a_new_change_and_keeps_unsaved_work(project: Path):
    first = versions.save(project, "First version")["version"]
    edit(project, FLOOR, set_beam("B300x600"))
    second = versions.save(project, "Deeper beam")["version"]
    # Unsaved work, in the part being restored and in another part.
    edit(project, FLOOR, set_beam("B300x700"))
    edit(project, MATERIALS, lambda m: m["materials"][0]["concrete"].update(fc=27.6))

    result = versions.restore(project, first["id"], ["floorPlan"])
    assert result["restored"] == [FLOOR] and result["deleted"] == []
    assert result["parts"] == ["floorPlan"] and result["problems"] == []
    assert result["before"]["message"] == f"Before restoring version 1 ({first['id']})"
    assert result["after"]["message"] == (f"Restored Floor Plan from version 1 ({first['id']})")

    assert read_json(project, FLOOR)["beams"][0]["type"] == "B300x500"
    # The other part keeps its (now saved) edit.
    assert read_json(project, MATERIALS)["materials"][0]["concrete"]["fc"] == 27.6
    # History is only added to.
    listed = [v["sha"] for v in versions.list_versions(project)["versions"]]
    assert listed[-2:] == [second["sha"], first["sha"]] and len(listed) == 4
    # The unsaved B300x700 is in the "Before restoring" version.
    before = versions.diff(project, result["before"]["id"] + "~1", result["before"]["id"])
    texts = [c["what"] for p in before["parts"] for c in p["changes"]]
    assert "Beam B1: section B300x600 → B300x700" in texts
    assert versions.status(project)["clean"]


def test_restore_everything_deletes_files_added_later(project: Path):
    first = versions.save(project, "First version")["version"]["id"]
    (project / "11 Exports" / "plan.dxf").write_text("0\nEOF\n", encoding="utf-8")
    edit(project, FLOOR, set_beam("B300x600"))
    versions.save(project, "Exports")
    result = versions.restore(project, first, commit=False)
    assert result["deleted"] == ["11 Exports/plan.dxf"]
    assert result["restored"] == [FLOOR]
    assert result["before"] is None and result["after"] is None
    assert not (project / "11 Exports" / "plan.dxf").exists()
    # Computed caches are left alone.
    assert (project / "08 FEM" / "model.osmodel").exists()
    state = versions.status(project)
    assert state["changedParts"] == ["floorPlan", "exports"]


def test_restore_never_writes_or_deletes_editor_settings(project: Path):
    # A version (as received in a project archive's history) with a settings file naming a
    # program to run: restoring it must not write it.
    settings = project / ".vscode" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"saengine.python.path": "C:/evil/python.exe"}', encoding="utf-8")
    first = versions.save(project, "First version")["version"]["id"]
    assert ".vscode/settings.json" in saved_paths(project)
    shutil.rmtree(project / ".vscode")
    without = versions.save(project, "Without settings")["version"]["id"]
    result = versions.restore(project, first, commit=False)
    assert not settings.exists()
    assert ".vscode/settings.json" not in result["restored"]
    assert any(".vscode/settings.json" in p for p in result["problems"])
    # The engineer's own settings are not deleted by restoring a version without them.
    settings.parent.mkdir()
    settings.write_text("{}", encoding="utf-8")
    versions.save(project, "Own settings")
    result = versions.restore(project, without, commit=False)
    assert ".vscode/settings.json" not in result["deleted"]
    assert settings.read_text(encoding="utf-8") == "{}"


def test_restore_refuses_unknown_parts(project: Path):
    first = versions.save(project, "First version")["version"]["id"]
    with pytest.raises(VersionsError) as error:
        versions.restore(project, first, ["roof"])
    assert error.value.code == "unknownPart"


def test_mark_issued_is_an_annotated_tag(project: Path):
    first = versions.save(project, "First version")["version"]
    edit(project, FLOOR, set_beam("B300x600"))
    second = versions.save(
        project, "For construction", issued=True, label="Issued for construction"
    )["version"]
    assert second["issued"] and second["label"] == "Issued for construction"
    assert second["tags"] == ["issued/issued-for-construction"]

    marked = versions.mark_issued(project, first["id"], "Tender")
    assert marked["tag"] == "issued/tender" and marked["version"]["labels"] == ["Tender"]
    # Idempotent for the same label; numbered for the same label on another version.
    assert versions.mark_issued(project, first["id"], "Tender")["tag"] == "issued/tender"
    assert versions.mark_issued(project, second["id"], "Tender")["tag"] == "issued/tender-2"

    repo = Repo(str(project))
    try:
        tag = repo[repo.refs[b"refs/tags/issued/tender"]]
        assert isinstance(tag, Tag)
        assert tag.message == b"Tender\n" and tag.object[1] == first["sha"].encode()
    finally:
        repo.close()
    listed = {v["id"]: v for v in versions.list_versions(project)["versions"]}
    assert listed[second["id"]]["labels"] == ["Issued for construction", "Tender"]
    # A version can be named by its issue.
    assert versions.diff(project, "issued/tender", second["id"])["parts"][0]["part"] == (
        "floorPlan"
    )
    # A re-tender: the label means the LATEST version issued with it, in any case.
    assert versions.diff(project, "Tender", first["id"])["from"] == second["id"]
    assert versions.diff(project, "TENDER", first["id"])["from"] == second["id"]
    # The tag's own names stay exact.
    assert versions.diff(project, "issued/tender", second["id"])["from"] == first["id"]
    assert versions.diff(project, "tender-2", first["id"])["from"] == second["id"]


def test_restore_refuses_to_overwrite_an_ignored_file(project: Path):
    notes = project / "11 Exports" / "notes" / "calc.txt"
    notes.parent.mkdir()
    notes.write_text("v1 calc", encoding="utf-8")
    first = versions.save(project, "First version")["version"]["id"]
    gitignore = project / ".gitignore"
    gitignore.write_text(gitignore.read_text(encoding="utf-8") + "notes/\n", encoding="utf-8")
    notes.unlink()
    versions.save(project, "Notes ignored")
    notes.write_text("PRECIOUS NEW WORK", encoding="utf-8")
    assert versions.status(project)["clean"]
    count = versions.list_versions(project)["count"]

    with pytest.raises(VersionsError) as error:
        versions.restore(project, first, ["exports"])
    assert error.value.code == "ignoredFiles"
    assert "11 Exports/notes/calc.txt" in str(error.value)
    # Nothing changed: the file, and the history.
    assert notes.read_text(encoding="utf-8") == "PRECIOUS NEW WORK"
    assert versions.list_versions(project)["count"] == count
    # The same content as the version is no obstacle.
    notes.write_text("v1 calc", encoding="utf-8")
    result = versions.restore(project, first, ["exports"])
    assert result["problems"] == []


def test_restore_a_folder_that_is_not_one_of_the_parts(project: Path):
    extra = project / "Calculations" / "hand-calc.txt"
    extra.parent.mkdir()
    extra.write_text("M = wL^2/8", encoding="utf-8")
    first = versions.save(project, "First version")["version"]
    assert "Calculations" in first["parts"]
    extra.write_text("M = wL^2/10", encoding="utf-8")
    state = versions.status(project)
    assert state["changedParts"] == ["Calculations"]
    versions.save(project, "Continuous beam")

    result = versions.restore(project, first["id"], state["changedParts"])
    assert result["restored"] == ["Calculations/hand-calc.txt"]
    assert result["parts"] == ["Calculations"]
    assert extra.read_text(encoding="utf-8") == "M = wL^2/8"


def test_existing_repository_is_used_as_it_is(project: Path):
    repo = Repo.init(str(project), default_branch=b"develop")
    config_path = Path(repo.controldir()) / "config"
    config = repo.get_config()
    config.set((b"user",), b"name", b"Developer")
    config.write_to_path()
    (project / ".gitignore").write_text("*.log\n", encoding="utf-8")
    (project / "README.md").write_text("Developer's notes\n", encoding="utf-8")
    (project / "debug.log").write_text("noise\n", encoding="utf-8")
    from dulwich import porcelain

    porcelain.add(repo, paths=[str(project / "README.md"), str(project / ".gitignore")])
    dev = porcelain.commit(
        repo,
        message=b"Developer commit",
        author=b"Dev <dev@example.com>",
        committer=b"Dev <dev@example.com>",
    )
    repo.close()
    config_before = config_path.read_bytes()

    version = versions.save(project, "Project files")["version"]
    assert config_path.read_bytes() == config_before
    assert (project / ".gitignore").read_text(encoding="utf-8") == "*.log\n"
    paths = saved_paths(project)
    assert {"README.md", FLOOR} <= paths
    assert "debug.log" not in paths  # their ignore rules apply
    assert not any(p.startswith("08 FEM/") for p in paths)  # and saving never stages a cache
    state = versions.status(project)
    assert state["branch"] == "develop" and state["clean"]
    listed = versions.list_versions(project)["versions"]
    assert [v["sha"] for v in listed] == [version["sha"], dev.decode()]
    assert listed[1]["message"] == "Developer commit"


def test_project_inside_another_repository_is_not_versioned(tmp_path: Path):
    outer = tmp_path / "Office"
    root = outer / "Projects" / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    Repo.init(str(outer)).close()
    state = versions.status(root)
    assert state["initialized"] is False
    assert state["enclosingRepository"] == str(outer.resolve())
    assert state["problems"]
    with pytest.raises(VersionsError) as error:
        versions.save(root, "First version")
    assert error.value.code == "enclosingRepository"
    assert not (root / ".git").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_git_agrees(project: Path):
    versions.save(project, "First version")
    edit(project, FLOOR, set_beam("B300x600"))
    versions.save(project, "Second", issued=True, label="Rev B")

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(project), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout

    assert git("status", "--porcelain") == ""
    git("fsck", "--strict")
    assert git("log", "--format=%s").splitlines() == ["Second", "First version"]
    assert git("tag", "-n1").split() == ["issued/rev-b", "Rev", "B"]
    edit(project, MATERIALS, lambda m: m["materials"][0]["concrete"].update(fc=24.1))
    assert git("status", "--porcelain").strip() == f'M "{MATERIALS}"'


def test_two_hundred_versions_list_under_a_second(tmp_path: Path):
    root = tmp_path / "Big History"
    (root / "05 Floor Plan").mkdir(parents=True)
    (root / "Big History.saengine").write_text('{"schema": 1}', encoding="utf-8")
    write_json(root, FLOOR, {"schema": "saengine.floorPlan/1", "beams": []})
    versions.save(root, "Version 1")
    # 199 more versions written straight with dulwich (saving through the API is tested above).
    repo = Repo(str(root))
    try:
        manifest = repo[repo[repo.refs[b"HEAD"]].tree][b"Big History.saengine"][1]
        for i in range(2, 201):
            plan = Blob.from_string(json.dumps({"beams": [{"id": "B1", "type": f"B{i}"}]}).encode())
            repo.object_store.add_object(plan)
            tree = commit_tree(
                repo.object_store,
                [
                    (b"Big History.saengine", manifest, 0o100644),
                    (FLOOR.encode(), plan.id, 0o100644),
                ],
            )
            _commit(repo, tree, i)
        versions._maintain(repo, 200)  # as saving does every PACK_EVERY versions
    finally:
        repo.close()
    versions._clear_caches()  # a cold start: nothing read yet
    start = time.perf_counter()
    listed = versions.list_versions(root, limit=200)
    elapsed = time.perf_counter() - start
    assert len(listed["versions"]) == 200 and listed["versions"][0]["number"] == 200
    assert listed["versions"][0]["message"] == "Version 200"
    assert listed["versions"][0]["parts"] == ["floorPlan"]
    assert elapsed < 1.0, f"{elapsed:.2f} s"
    start = time.perf_counter()
    versions.status(root)
    assert time.perf_counter() - start < 1.0


def _commit(repo: Repo, tree: bytes, i: int) -> None:
    head = repo.refs[b"HEAD"]
    commit = Commit()
    commit.tree, commit.parents = tree, [head]
    commit.author = commit.committer = b"A <a@b>"
    commit.author_time = commit.commit_time = 1_760_000_000 + i
    commit.author_timezone = commit.commit_timezone = 6 * 3600
    commit.message = f"Version {i}\n".encode()
    repo.object_store.add_object(commit)
    repo.refs[b"HEAD"] = commit.id


def test_saving_packs_the_history(tmp_path: Path):
    root = tmp_path / "Packed"
    (root / "05 Floor Plan").mkdir(parents=True)
    for i in range(versions.PACK_EVERY):
        write_json(root, FLOOR, {"beams": [{"id": "B1", "type": f"B{i}"}]})
        versions.save(root, f"Version {i + 1}")
    packs = list((root / ".git" / "objects" / "pack").glob("*.pack"))
    assert len(packs) == 1
    assert versions.list_versions(root)["count"] == versions.PACK_EVERY
    assert versions.status(root)["clean"]


def _push(root: Path, extra: list[tuple[bytes, bytes, int]], message: str) -> str:
    """Add a commit on top of HEAD with the extra tree entries, as a collaborator's push or a
    developer's git would; returns its id."""
    repo = Repo(str(root))
    try:
        head = repo.refs[b"HEAD"]
        entries = [
            (e.path, e.sha, e.mode)
            for e in iter_tree_contents(repo.object_store, repo[head].tree)
            if e.path is not None
        ]
        for path, data, mode in extra:
            if mode == 0o160000:
                entries.append((path, data, mode))
                continue
            blob = Blob.from_string(data)
            repo.object_store.add_object(blob)
            entries.append((path, blob.id, mode))
        tree = commit_tree(repo.object_store, entries)
        commit = Commit()
        commit.tree, commit.parents = tree, [head]
        commit.author = commit.committer = b"Collaborator <c@example.com>"
        commit.author_time = commit.commit_time = int(time.time())
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = message.encode() + b"\n"
        repo.object_store.add_object(commit)
        repo.refs[b"HEAD"] = commit.id
        return commit.id.decode()
    finally:
        repo.close()


def test_restore_never_writes_outside_the_project_or_into_git(project: Path):
    versions.save(project, "First version")
    hostile = _push(
        project,
        [
            (rb"..\..\escaped.txt", b"PWNED\n", 0o100644),
            (b".GIT/hooks/post-commit", b"PWNED\n", 0o100644),
            (b"05 Floor Plan/GIT~1/config", b"PWNED\n", 0o100644),
            (b"11 Exports/fine.txt", b"ok\n", 0o100644),
        ],
        "Collaborator push",
    )
    result = versions.restore(project, hostile, commit=False)
    assert result["restored"] == ["11 Exports/fine.txt"]
    assert len(result["problems"]) == 3
    assert all(p.startswith("Not restored") for p in result["problems"])
    assert not (project.parent.parent / "escaped.txt").exists()
    assert not (project.parent / "escaped.txt").exists()
    assert not (project / ".git" / "hooks" / "post-commit").exists()
    assert not (project / "05 Floor Plan" / "GIT~1").exists()


def test_links_submodules_and_modes_of_a_developer_repository_are_kept(project: Path):
    (project / "tools").mkdir()
    (project / "tools" / "run.sh").write_text("echo hi\n", encoding="utf-8")
    (project / "tools" / "run.sh").chmod(0o755)
    versions.save(project, "First version")
    repo = Repo(str(project))
    tree = repo[repo[repo.refs[b"HEAD"]].tree]
    run = next(
        e for e in iter_tree_contents(repo.object_store, tree.id) if e.path == b"tools/run.sh"
    )
    repo.close()
    gitlink = b"1234567890123456789012345678901234567890"
    developer = _push(
        project,
        [(b"run-link", b"tools/run.sh", 0o120000), (b"vendor/lib", gitlink, 0o160000)],
        "Developer commit",
    )
    # Make tools/run.sh executable in history, as a developer's git would.
    repo = Repo(str(project))
    entries = [
        (e.path, e.sha, 0o100755 if e.path == b"tools/run.sh" else e.mode)
        for e in iter_tree_contents(repo.object_store, repo[developer.encode()].tree)
    ]
    repo.close()
    assert run.mode in (0o100644, 0o100755)
    _push_tree(project, entries)
    # The developer's checkout: on Windows the link is a text file, elsewhere a real symlink;
    # the submodule is a folder.
    if sys.platform == "win32":
        (project / "run-link").write_text("tools/run.sh", encoding="utf-8")
    else:
        (project / "run-link").symlink_to("tools/run.sh")
    (project / "vendor" / "lib").mkdir(parents=True)
    (project / "vendor" / "lib" / ".git").write_text("gitdir: ../../.git/modules/lib\n", "utf-8")
    assert versions.status(project)["clean"]

    edit(project, FLOOR, set_beam("B300x600"))
    version = versions.save(project, "Engineer edit")["version"]
    assert version["parts"] == ["floorPlan"]
    repo = Repo(str(project))
    try:
        modes = {
            e.path.decode(): (e.mode, e.sha)
            for e in iter_tree_contents(repo.object_store, repo[version["sha"].encode()].tree)
        }
    finally:
        repo.close()
    assert modes["tools/run.sh"][0] == 0o100755
    assert modes["run-link"][0] == 0o120000
    assert modes["vendor/lib"] == (0o160000, gitlink)
    # Restoring an older version leaves the link and the submodule alone.
    versions.restore(project, developer, ["project"], commit=False)
    assert (project / "run-link").exists() and (project / "vendor" / "lib" / ".git").exists()


def _push_tree(root: Path, entries: list[tuple[bytes, bytes, int]]) -> None:
    repo = Repo(str(root))
    try:
        head = repo.refs[b"HEAD"]
        commit = Commit()
        commit.tree, commit.parents = commit_tree(repo.object_store, entries), [head]
        commit.author = commit.committer = b"Dev <dev@example.com>"
        commit.author_time = commit.commit_time = int(time.time())
        commit.author_timezone = commit.commit_timezone = 0
        commit.message = b"chmod +x\n"
        repo.object_store.add_object(commit)
        repo.refs[b"HEAD"] = commit.id
    finally:
        repo.close()


def test_an_unreadable_folder_is_an_error_not_a_deletion(project: Path, monkeypatch):
    first = versions.save(project, "First version")["version"]
    edit(project, FLOOR, set_beam("B300x600"))
    versions.save(project, "Deeper beam")
    edit(project, FLOOR, set_beam("B300x700"))  # unsaved work
    real = versions.os.scandir

    def scandir(path):
        if Path(versions.os.fsdecode(path)).name == "05 Floor Plan":
            raise PermissionError(13, "Access is denied")
        return real(path)

    monkeypatch.setattr(versions.os, "scandir", scandir)
    for call in (
        lambda: versions.status(project),
        lambda: versions.save(project, "Should not save"),
        lambda: versions.restore(project, first["id"]),
    ):
        with pytest.raises(VersionsError) as error:
            call()
        assert error.value.code == "io"
        assert "05 Floor Plan" in str(error.value)
    monkeypatch.undo()
    assert read_json(project, FLOOR)["beams"][0]["type"] == "B300x700"  # the work is still there
    assert versions.list_versions(project)["count"] == 2


@pytest.mark.skipif(
    not Path(__file__).with_name(Path(__file__).name.upper()).exists(),
    reason="the file system is case-sensitive",
)
def test_restore_handles_a_case_only_rename(project: Path):
    (project / "11 Exports" / "Notes.txt").write_text("first\n", encoding="utf-8")
    first = versions.save(project, "First version")["version"]
    (project / "11 Exports" / "Notes.txt").rename(project / "11 Exports" / "notes.txt")
    (project / "11 Exports" / "notes.txt").write_text("second\n", encoding="utf-8")
    versions.save(project, "Renamed")
    result = versions.restore(project, first["id"], ["exports"])
    assert result["problems"] == [] and result["deleted"] == []
    assert result["restored"] == ["11 Exports/Notes.txt"]
    names = [p.name for p in (project / "11 Exports").iterdir() if p.suffix == ".txt"]
    assert names == ["Notes.txt"]
    assert (project / "11 Exports" / "Notes.txt").read_text(encoding="utf-8") == "first\n"
    assert "11 Exports/Notes.txt" in saved_paths(project)
