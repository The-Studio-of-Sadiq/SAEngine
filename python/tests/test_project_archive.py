"""The ``.civil`` project archive: export, inspect and import of SAEngine projects. All data is
synthetic: the shipped sample and small projects written here."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from saengine.project import archive
from saengine.project.archive import (
    COMPUTED_PATHS,
    FORMAT,
    ArchiveError,
    export_project,
    import_project,
    inspect_archive,
    is_computed,
    matches,
    path_problem,
)

SAMPLE = Path(__file__).parents[2] / "workbench/resources/saengine/samples/Sample Frame"
CREATED = "2026-10-19T00:00:00Z"
#: The project file of the hand-made archives.
PROJECT = "Evil.saengine"
PROJECT_DATA = b'{"schema": 1, "name": "Evil"}'


def files_of(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    root = tmp_path / "src" / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    # Git keeps no empty folders: the sample's empty part folders exist only after a run.
    for folder in ("08 FEM", "11 Exports"):
        (root / folder).mkdir(exist_ok=True)
    return root


def add_results(root: Path) -> list[str]:
    """Computed caches as the app writes them; returns their relative paths."""
    cached = {
        "08 FEM/model.osmodel": '{"schema_version": 2}\n',
        "08 FEM/pushover.osmodel": "{}\n",
        "08 FEM/ssi.json": "{}\n",
        "08 FEM/model.results/manifest.json": "{}\n",
        "08 FEM/model.results/design-summary.json": '{"checked": 4}\n',
        "08 FEM/model-fixed.results/manifest.json": "{}\n",
        "07 MEP/mep.results/summary.json": "{}\n",
        "07 MEP/mep.results/tanks/tank-T1.osmodel": "{}\n",
        "07 MEP/hvac.results/loads.json": "{}\n",
        "09 Substructure/substructure.results/summary.json": "{}\n",
    }
    for relative, text in cached.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text, encoding="utf-8")
    return sorted(cached)


def names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        return z.namelist()


def rewrite(path: Path, out: Path, edit) -> None:
    """Copy the archive ``path`` to ``out`` through ``edit(name, data) -> (name, data) | None``."""
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            changed = edit(info.filename, src.read(info))
            if changed is not None:
                dst.writestr(changed[0], changed[1])


def make_archive(out: Path, entries: dict[str, bytes], fmt: str = FORMAT, **extra) -> Path:
    """A hand-made archive listing ``entries`` (relative to ``project/``) in its manifest."""
    files = [
        {"path": p, "size": len(d), "sha256": hashlib.sha256(d).hexdigest()}
        for p, d in entries.items()
    ]
    manifest = {
        "format": fmt,
        "saengineVersion": "0.0.1",
        "created": CREATED,
        "project": {"name": "Evil", **({"file": "Evil.saengine"} if PROJECT in entries else {})},
        "parts": [],
        "files": files,
        **extra,
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p, d in entries.items():
            z.writestr("project/" + p, d)
        z.writestr("manifest.json", json.dumps(manifest))
    return out


def codes(problems: list[dict]) -> set[str]:
    return {p["code"] for p in problems}


# --- Paths ---------------------------------------------------------------------------------


def test_computed_paths_cover_every_cache_the_app_writes(sample: Path) -> None:
    for relative in add_results(sample):
        assert is_computed(relative), relative
    for source in (
        "02 Project Settings/project-settings.json",
        "06 BIM/bim.json",
        "07 MEP/mep.json",
        "09 Substructure/substructure.json",
        "11 Exports/report.pdf",
        "Sample Frame.saengine",
    ):
        assert not is_computed(source), source
    assert is_computed("08 fem/MODEL.RESULTS", folder=True)  # Windows: any case
    assert is_computed("05 Floor Plan/check.results/x.json")
    assert matches(["**/*.results/"], "a/b/c.results/d")
    assert all("/" in p for p in COMPUTED_PATHS)  # anchored in .gitignore syntax too


@pytest.mark.parametrize(
    "bad", ["../x", "/abs", "C:/x", "a/../b", "a\\b", "CON", "nul.txt", "a /b", "dot./x", ""]
)
def test_path_problem_refuses_paths_windows_cannot_take(bad: str) -> None:
    assert path_problem(bad)


def test_path_problem_takes_ordinary_project_paths() -> None:
    assert path_problem("05 Floor Plan/Underlays/dimensions.dxf") is None
    assert path_problem("11 Exports/রিপোর্ট.pdf") is None


# --- Export / import round trip ------------------------------------------------------------


def test_round_trip_of_the_sample_is_byte_identical(sample: Path, tmp_path: Path) -> None:
    out = tmp_path / "Sample Frame.civil"
    result = export_project(sample, out, created=CREATED, saengine_version="0.0.34")
    assert result["files"] == len(files_of(sample))
    assert not [p for p in result["problems"] if p["severity"] == "error"]
    assert names(out)[-1] == "manifest.json"
    assert all(n == "manifest.json" or n.startswith("project/") for n in names(out))

    report = inspect_archive(out, current_version="0.0.34")
    assert report["ok"], report["problems"]
    manifest = report["manifest"]
    assert manifest["format"] == "saengine.civil/1"
    assert manifest["saengineVersion"] == "0.0.34"
    assert manifest["created"] == CREATED
    assert manifest["project"] == {"name": "Sample Frame", "file": "Sample Frame.saengine"}
    assert manifest["includes"] == {"results": False, "versions": False, "exports": True}
    parts = {p["id"]: p for p in manifest["parts"]}
    assert list(parts) == [
        "soil",
        "settings",
        "materials",
        "objects",
        "floorPlan",
        "bim",
        "mep",
        "fem",
        "substructure",
        "boq",
        "exports",
    ]
    # The sample's soil report is filled in (synthetic data, since the site map).
    assert parts["soil"]["files"][0]["schema"] == "saengine.soilReport/1"
    assert parts["bim"]["files"][0]["schema"] == "saengine.bim/2"
    assert parts["fem"]["missingMainFile"] is True  # derived; regenerated on open
    floor = [f["path"] for f in parts["floorPlan"]["files"]]
    assert floor == [
        "05 Floor Plan/floor-plan.json",
        "05 Floor Plan/sample-plan.dxf",
        "05 Floor Plan/Underlays/dimensions.dxf",
    ]
    assert [f["path"] for f in manifest["files"]] == ["Sample Frame.saengine"]

    imported = import_project(out, tmp_path / "dest", current_version="0.0.34")
    root = Path(imported["root"])
    assert root == tmp_path / "dest" / "Sample Frame"
    assert files_of(root) == files_of(sample)
    assert imported["files"] == result["files"]
    assert imported["migrated"] == [] and imported["pending"] == []
    assert "renamed" not in imported
    for relative in files_of(sample):  # modification times kept: the part status reads them
        assert (root / relative).stat().st_mtime_ns == (sample / relative).stat().st_mtime_ns


def test_import_under_a_new_name_renames_the_project_file(sample: Path, tmp_path: Path) -> None:
    out = tmp_path / "a.civil"
    export_project(sample, out, created=CREATED)
    imported = import_project(out, tmp_path / "dest", name="Tower: B")
    root = Path(imported["root"])
    assert root.name == "Tower- B"
    assert imported["renamed"] == {"from": "Sample Frame.saengine", "to": "Tower- B.saengine"}
    assert not (root / "Sample Frame.saengine").exists()
    data = json.loads((root / "Tower- B.saengine").read_text(encoding="utf-8"))
    assert data["name"] == "Tower- B" and data["parts"][0] == "soil"


def test_output_is_deterministic(sample: Path, tmp_path: Path) -> None:
    a, b = tmp_path / "a.civil", tmp_path / "b.civil"
    export_project(sample, a, created=CREATED, saengine_version="0.0.34")
    export_project(sample, b, created=CREATED, saengine_version="0.0.34")
    assert a.read_bytes() == b.read_bytes()


def test_the_archive_written_inside_the_project_is_not_archived(sample: Path) -> None:
    out = sample / "11 Exports" / "Sample Frame.civil"
    export_project(sample, out, created=CREATED)
    second = export_project(sample, out, created=CREATED)
    assert not [n for n in names(out) if n.endswith(".civil")]
    assert {"path": "11 Exports/Sample Frame.civil", "reason": "the archive itself"} in second[
        "skipped"
    ]


# --- What is included ----------------------------------------------------------------------


def test_results_are_left_out_unless_asked_for(sample: Path, tmp_path: Path) -> None:
    cached = add_results(sample)
    out = tmp_path / "plain.civil"
    result = export_project(sample, out, created=CREATED)
    assert not [n for n in names(out) if n.removeprefix("project/") in cached]
    skipped = {s["path"] for s in result["skipped"] if s["reason"] == "computed"}
    assert {"08 FEM/model.results/", "07 MEP/hvac.results/", "08 FEM/model.osmodel"} <= skipped

    full = tmp_path / "full.civil"
    export_project(sample, full, include_results=True, created=CREATED)
    listed = {n.removeprefix("project/") for n in names(full)}
    assert set(cached) <= listed
    manifest = inspect_archive(full)["manifest"]
    fem = next(p for p in manifest["parts"] if p["id"] == "fem")
    assert all(f["computed"] for f in fem["files"])
    assert manifest["includes"]["results"] is True
    root = Path(import_project(full, tmp_path / "dest")["root"])
    assert files_of(root) == files_of(sample)


def test_exports_and_versions(sample: Path, tmp_path: Path) -> None:
    (sample / "11 Exports" / "report.pdf").write_bytes(b"%PDF-1.7 synthetic")
    (sample / ".git" / "objects").mkdir(parents=True)
    (sample / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (sample / ".gitignore").write_text("\n".join(COMPUTED_PATHS) + "\n", encoding="utf-8")
    (sample / "Thumbs.db").write_bytes(b"junk")

    out = tmp_path / "default.civil"
    result = export_project(sample, out, created=CREATED)
    listed = set(names(out))
    assert "project/11 Exports/report.pdf" in listed
    assert "project/.gitignore" in listed
    assert not [n for n in listed if n.startswith("project/.git/")]
    assert {"path": ".git/", "reason": "versions"} in result["skipped"]
    assert {"path": "Thumbs.db", "reason": "junk"} in result["skipped"]

    lean = tmp_path / "lean.civil"
    export_project(sample, lean, include_exports=False, include_versions=True, created=CREATED)
    listed = set(names(lean))
    assert "project/11 Exports/report.pdf" not in listed
    assert "project/.git/HEAD" in listed
    manifest = inspect_archive(lean)["manifest"]
    assert manifest["includes"] == {"results": False, "versions": True, "exports": False}
    assert ".git/HEAD" in [f["path"] for f in manifest["files"]]


def test_statuses_and_note_pass_through(sample: Path, tmp_path: Path) -> None:
    out = tmp_path / "s.civil"
    export_project(sample, out, note="For the checking engineer", statuses={"bim": {"state": "ok"}})
    manifest = inspect_archive(out)["manifest"]
    assert manifest["note"] == "For the checking engineer"
    bim = next(p for p in manifest["parts"] if p["id"] == "bim")
    assert bim["status"] == {"state": "ok"}
    assert "status" not in next(p for p in manifest["parts"] if p["id"] == "soil")


def test_an_incomplete_project_is_archived_as_it_is(tmp_path: Path) -> None:
    root = tmp_path / "Draft"
    (root / "01 Soil Report").mkdir(parents=True)
    (root / "01 Soil Report" / "soil-report.json").write_text(
        '{"schema": 1, "part": "soil"}\n', encoding="utf-8"
    )
    (root / "06 BIM").mkdir()
    (root / "06 BIM" / "bim.json").write_text('{"schema": "saengine.bim/2", ', encoding="utf-8")
    manifest_text = json.dumps(
        {
            "schema": 1,
            "name": "Draft",
            "created": CREATED,
            "type": "structure",
            "parts": ["soil", "structure", "bim", "boq"],
        }
    )
    (root / "Draft.saengine").write_text(manifest_text, encoding="utf-8")

    out = tmp_path / "draft.civil"
    result = export_project(root, out, created=CREATED)
    assert {"path": "06 BIM/bim.json", "code": "invalid-json", "severity": "warning"}.items() <= (
        next(p for p in result["problems"] if p["code"] == "invalid-json").items()
    )
    report = inspect_archive(out)
    assert report["ok"]
    parts = {p["id"]: p for p in report["manifest"]["parts"]}
    assert parts["soil"]["placeholder"] is True
    assert parts["structure"]["missing"] is True and parts["structure"]["files"] == []
    assert parts["boq"]["missing"] is True
    assert "schema" not in parts["bim"]["files"][0]
    assert report["manifest"]["project"]["type"] == "structure"

    root2 = Path(import_project(out, tmp_path / "dest")["root"])
    assert files_of(root2) == files_of(root)


def test_a_folder_without_a_project_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(ArchiveError):
        export_project(tmp_path / "empty", tmp_path / "x.civil")


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows feature")
def test_links_out_of_the_project_are_not_followed(sample: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("not part of the project", encoding="utf-8")
    import _winapi

    _winapi.CreateJunction(str(outside), str(sample / "04 Objects" / "linked"))
    out = tmp_path / "j.civil"
    result = export_project(sample, out, created=CREATED)
    assert not [n for n in names(out) if "secret" in n]
    assert {"path": "04 Objects/linked", "reason": "link"} in result["skipped"]


# --- Refused archives ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["project/../../evil.txt", "project/C:/evil.txt", "evil.txt", "/project/evil.txt"]
)
def test_zip_slip_is_refused(tmp_path: Path, name: str) -> None:
    out = tmp_path / "slip.civil"
    data = b"pwned"
    manifest = {
        "format": FORMAT,
        "saengineVersion": "0.0.1",
        "project": {"name": "Evil"},
        "parts": [],
        "files": [
            {
                "path": name.removeprefix("project/"),
                "size": 5,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        ],
    }
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(name, data)
        z.writestr("manifest.json", json.dumps(manifest))
    report = inspect_archive(out)
    assert not report["ok"]
    assert codes(report["problems"]) & {"unsafe-path", "outside"}
    dest = tmp_path / "dest"
    with pytest.raises(ArchiveError):
        import_project(out, dest)
    assert not (tmp_path / "evil.txt").exists()
    assert not dest.exists() or not any(dest.iterdir())


def test_zip_bomb_is_refused(tmp_path: Path) -> None:
    out = make_archive(tmp_path / "bomb.civil", {"08 FEM/zeros.bin": bytes(8 * 1024**2)})
    report = inspect_archive(out)
    assert "zip-bomb" in codes(report["problems"])
    with pytest.raises(ArchiveError) as caught:
        import_project(out, tmp_path / "dest")
    assert "zip-bomb" in codes(caught.value.problems)
    assert not (tmp_path / "dest").exists() or not any((tmp_path / "dest").iterdir())


def test_too_large_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "MAX_UNCOMPRESSED", 10)
    out = make_archive(tmp_path / "big.civil", {"a.json": b"{}" * 20})
    assert "too-large" in codes(inspect_archive(out)["problems"])


def test_a_highly_compressible_large_file_is_stored_so_it_imports(
    sample: Path, tmp_path: Path
) -> None:
    (sample / "11 Exports" / "blank.dxf").write_bytes(b"0\n" * (2 * 1024**2))
    out = tmp_path / "s.civil"
    export_project(sample, out, created=CREATED)
    with zipfile.ZipFile(out) as z:
        assert z.getinfo("project/11 Exports/blank.dxf").compress_type == zipfile.ZIP_STORED
    assert inspect_archive(out)["ok"]


def test_checksum_tampering_is_detected(sample: Path, tmp_path: Path) -> None:
    good = tmp_path / "good.civil"
    export_project(sample, good, created=CREATED)
    bad = tmp_path / "bad.civil"
    target = "project/03 Materials/materials.json"

    def edit(name: str, data: bytes):
        if name == target:  # the same length, one byte changed
            return name, data.replace(b"C", b"D", 1)
        return name, data

    rewrite(good, bad, edit)
    report = inspect_archive(bad)
    assert not report["ok"]
    assert [p["path"] for p in report["problems"] if p["code"] == "checksum"] == [
        "03 Materials/materials.json"
    ]
    assert inspect_archive(bad, verify=False)["ok"]  # sizes still match
    with pytest.raises(ArchiveError) as caught:
        import_project(bad, tmp_path / "dest")
    assert "checksum" in codes(caught.value.problems)
    assert not (tmp_path / "dest" / "Sample Frame").exists()
    assert not list((tmp_path / "dest").glob(".civil-import-*"))  # nothing left behind


def test_unlisted_and_missing_files_are_detected(sample: Path, tmp_path: Path) -> None:
    good = tmp_path / "good.civil"
    export_project(sample, good, created=CREATED)
    bad = tmp_path / "bad.civil"

    def edit(name: str, data: bytes):
        if name == "project/10 BOQ/boq.json":
            return "project/10 BOQ/extra.json", data
        return name, data

    rewrite(good, bad, edit)
    found = codes(inspect_archive(bad)["problems"])
    assert {"unlisted-file", "missing-file"} <= found


def test_case_insensitive_duplicates_are_refused(tmp_path: Path) -> None:
    out = make_archive(tmp_path / "dup.civil", {"a/B.json": b"{}", "A/b.json": b"[]"})
    assert "duplicate-path" in codes(inspect_archive(out)["problems"])


def test_newer_format_is_refused_with_a_clear_message(tmp_path: Path) -> None:
    out = make_archive(
        tmp_path / "new.civil", {"x.json": b"{}"}, fmt="saengine.civil/2", saengineVersion="0.2.0"
    )
    report = inspect_archive(out, current_version="0.0.34")
    problem = next(p for p in report["problems"] if p["code"] == "newer-format")
    assert problem["severity"] == "error"
    assert "made with SAEngine 0.2.0, newer than this one (0.0.34)" in problem["message"]
    with pytest.raises(ArchiveError, match="newer than this one"):
        import_project(out, tmp_path / "dest", current_version="0.0.34")


def test_newer_saengine_version_warns_and_older_imports(sample: Path, tmp_path: Path) -> None:
    newer = tmp_path / "newer.civil"
    export_project(sample, newer, saengine_version="0.1.2", created=CREATED)
    report = inspect_archive(newer, current_version="0.0.34")
    assert report["ok"]
    warning = next(p for p in report["problems"] if p["code"] == "newer-version")
    assert warning["message"].startswith("made with SAEngine 0.1.2, newer than this one (0.0.34)")
    imported = import_project(newer, tmp_path / "a", current_version="0.0.34")
    assert "newer-version" in codes(imported["problems"])

    older = tmp_path / "older.civil"
    export_project(sample, older, saengine_version="0.0.9", created=CREATED)
    assert inspect_archive(older, current_version="0.0.34")["problems"] == []
    assert import_project(older, tmp_path / "b", current_version="0.0.34")["problems"] == []


def test_other_archives_are_not_projects(tmp_path: Path) -> None:
    text = tmp_path / "notes.civil"
    text.write_text("not a zip", encoding="utf-8")
    assert codes(inspect_archive(text)["problems"]) == {"not-an-archive"}
    with pytest.raises(ArchiveError):
        import_project(text, tmp_path / "dest")
    plain = tmp_path / "plain.civil"
    with zipfile.ZipFile(plain, "w") as z:
        z.writestr("hello.txt", "hi")
    assert "no-manifest" in codes(inspect_archive(plain)["problems"])
    other = make_archive(tmp_path / "other.civil", {}, fmt="something.else/1")
    assert "unknown-format" in codes(inspect_archive(other)["problems"])


# --- Destination ---------------------------------------------------------------------------


def test_an_existing_project_is_not_overwritten_unless_asked(sample: Path, tmp_path: Path) -> None:
    out = tmp_path / "a.civil"
    export_project(sample, out, created=CREATED)
    dest = tmp_path / "dest" / "Sample Frame"
    dest.mkdir(parents=True)
    (dest / "keep.txt").write_text("mine", encoding="utf-8")
    (dest / "06 BIM").mkdir()
    (dest / "06 BIM" / "bim.json").write_text("old", encoding="utf-8")
    with pytest.raises(ArchiveError, match="not empty"):
        import_project(out, tmp_path / "dest")
    assert (dest / "06 BIM" / "bim.json").read_text(encoding="utf-8") == "old"

    import_project(out, tmp_path / "dest", overwrite=True)
    assert (dest / "06 BIM" / "bim.json").read_bytes() == (
        sample / "06 BIM" / "bim.json"
    ).read_bytes()
    assert (dest / "keep.txt").read_text(encoding="utf-8") == "mine"
    assert not list((tmp_path / "dest").glob(".civil-import-*"))


def test_an_empty_destination_folder_is_used(sample: Path, tmp_path: Path) -> None:
    out = tmp_path / "a.civil"
    export_project(sample, out, created=CREATED)
    (tmp_path / "dest" / "Sample Frame").mkdir(parents=True)
    root = Path(import_project(out, tmp_path / "dest")["root"])
    assert files_of(root) == files_of(sample)


def test_footings_to_migrate_are_listed_not_applied(tmp_path: Path) -> None:
    root = tmp_path / "Old"
    (root / "06 BIM").mkdir(parents=True)
    bim = {
        "schema": "saengine.bim/2",
        "elements": [
            {"id": "F1", "kind": "footing"},
            {"id": "F2", "kind": "footing"},
            {"id": "C1", "kind": "column"},
        ],
    }
    (root / "06 BIM" / "bim.json").write_text(json.dumps(bim), encoding="utf-8")
    (root / "09 Substructure").mkdir()
    sub = {"schema": "saengine.substructure/1", "foundations": [{"id": "F1"}]}
    (root / "09 Substructure" / "substructure.json").write_text(json.dumps(sub), encoding="utf-8")
    (root / "Old.saengine").write_text('{"schema": 1, "name": "Old"}', encoding="utf-8")
    out = tmp_path / "old.civil"
    export_project(root, out, created=CREATED)
    imported = import_project(out, tmp_path / "dest")
    assert imported["migrated"] == []
    assert [p["id"] for p in imported["pending"]] == ["substructure.footings"]
    # The Substructure editor's user-facing command, which writes the footings it imports.
    assert imported["pending"][0]["command"] == "saengine.substructure.importFootings"
    assert (
        "F2" in imported["pending"][0]["message"]
        and "F1" not in imported["pending"][0]["message"].split("(")[1]
    )
    after = Path(imported["root"]) / "09 Substructure" / "substructure.json"
    assert json.loads(after.read_text(encoding="utf-8")) == sub


def test_footings_of_a_placeholder_substructure_are_migrated_on_import(tmp_path: Path) -> None:
    from test_design_footing import CORNERS, OBJECTS_WITH_FOOTINGS, footing, with_footings

    root = tmp_path / "Old"
    building = with_footings(
        *(footing(f"F{i + 1}", "F18", x, y) for i, (x, y) in enumerate(CORNERS))
    )
    files = {
        "04 Objects/objects.json": OBJECTS_WITH_FOOTINGS.model_dump_json(by_alias=True),
        "06 BIM/bim.json": building.model_dump_json(by_alias=True),
        "09 Substructure/substructure.json": '{\n\t"schema": 1,\n\t"part": "substructure"\n}\n',
        "Old.saengine": '{"schema": 1, "name": "Old"}',
    }
    for relative, text in files.items():
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_text(text, encoding="utf-8")
    out = tmp_path / "old.civil"
    export_project(root, out, created=CREATED)

    kept = import_project(out, tmp_path / "a", migrate=False)
    assert kept["migrated"] == [] and kept["pending"] == []  # the editor migrates it on open
    placeholder = Path(kept["root"]) / "09 Substructure" / "substructure.json"
    assert json.loads(placeholder.read_text(encoding="utf-8"))["schema"] == 1

    imported = import_project(out, tmp_path / "b")
    assert [(m["id"], m["count"]) for m in imported["migrated"]] == [("substructure.footings", 4)]
    assert imported["pending"] == []
    after = Path(imported["root"]) / "09 Substructure" / "substructure.json"
    saved = json.loads(after.read_text(encoding="utf-8"))
    assert [f["id"] for f in saved["foundations"]] == ["F1", "F2", "F3", "F4"]


# --- Untrusted manifests and version histories ---------------------------------------------


@pytest.mark.parametrize("kind", ["absolute", "parent", "part file", "missing", "not a project"])
def test_the_project_file_must_be_a_root_file_of_the_archive(tmp_path: Path, kind: str) -> None:
    victim = tmp_path / "victim" / "thesis.docx"
    victim.parent.mkdir()
    victim.write_bytes(b"my thesis")
    bim = b'{"schema": "saengine.bim/3", "elements": []}'
    named = {
        "absolute": str(victim),
        "parent": "../../victim/thesis.docx",
        "part file": "06 BIM/bim.json",
        "missing": "Other.saengine",
        "not a project": "notes.txt",
    }[kind]
    entries = {PROJECT: PROJECT_DATA, "06 BIM/bim.json": bim, "notes.txt": b"hi"}
    out = make_archive(tmp_path / "e.civil", entries, project={"name": "P", "file": named})
    report = inspect_archive(out)
    assert not report["ok"] and "invalid-project-file" in codes(report["problems"])
    with pytest.raises(ArchiveError):
        import_project(out, tmp_path / "dest")
    assert victim.read_bytes() == b"my thesis"
    assert not (tmp_path / "dest" / "P").exists()
    assert not list((tmp_path / "dest").glob(".civil-import-*"))


def test_without_a_named_project_file_the_root_one_is_renamed(tmp_path: Path) -> None:
    out = make_archive(
        tmp_path / "e.civil", {PROJECT: PROJECT_DATA, "a.json": b"{}"}, project={"name": "Evil"}
    )
    imported = import_project(out, tmp_path / "dest", name="Tower")
    root = Path(imported["root"])
    assert imported["renamed"] == {"from": PROJECT, "to": "Tower.saengine"}
    assert sorted(p.name for p in root.iterdir()) == ["Tower.saengine", "a.json"]
    assert json.loads((root / "Tower.saengine").read_text(encoding="utf-8"))["name"] == "Tower"


def test_a_file_that_is_also_a_folder_is_refused(tmp_path: Path) -> None:
    out = make_archive(tmp_path / "c.civil", {PROJECT: PROJECT_DATA, "a": b"x", "a/b": b"y"})
    report = inspect_archive(out)
    assert not report["ok"] and "path-conflict" in codes(report["problems"])
    with pytest.raises(ArchiveError):
        import_project(out, tmp_path / "dest")
    assert not list((tmp_path / "dest").glob(".civil-import-*"))


def test_extraction_errors_become_archive_errors(
    sample: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "s.civil"
    export_project(sample, out, created=CREATED)
    real = Path.open

    def failing(self: Path, mode: str = "r", *args, **kwargs):
        if mode == "xb" and self.name == "bim.json":
            raise PermissionError(13, "Access is denied", str(self))
        return real(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing)
    with pytest.raises(ArchiveError) as caught:
        import_project(out, tmp_path / "dest")
    assert "unwritable" in codes(caught.value.problems)
    assert not (tmp_path / "dest" / "Sample Frame").exists()


EVIL_CONFIG = (
    b"[core]\n\trepositoryformatversion = 0\n\tfsmonitor = calc.exe\n[include]\n\tpath = x\n"
)


def test_version_history_only_when_the_manifest_declares_it(tmp_path: Path) -> None:
    entries = {PROJECT: PROJECT_DATA, ".git/config": EVIL_CONFIG, ".git/HEAD": b"ref: x\n"}
    out = make_archive(tmp_path / "g.civil", entries)  # no "includes"
    report = inspect_archive(out)
    assert not report["ok"] and "unexpected-versions" in codes(report["problems"])
    with pytest.raises(ArchiveError):
        import_project(out, tmp_path / "dest")
    off = make_archive(tmp_path / "h.civil", entries, includes={"versions": False})
    assert "unexpected-versions" in codes(inspect_archive(off)["problems"])


def test_an_imported_version_history_cannot_run_programs(tmp_path: Path) -> None:
    entries = {
        PROJECT: PROJECT_DATA,
        ".git/config": EVIL_CONFIG,
        ".git/HEAD": b"ref: refs/heads/main\n",
        ".git/hooks/post-checkout": b"#!/bin/sh\ncalc.exe\n",
        ".git/modules/sub/config": EVIL_CONFIG,
        ".git/objects/info/alternates": b"C:/elsewhere/objects\n",
        ".git/commondir": b"C:/elsewhere\n",
    }
    out = make_archive(tmp_path / "g.civil", entries, includes={"versions": True})
    report = inspect_archive(out)
    assert report["ok"] and "versions" in codes(report["problems"])
    imported = import_project(out, tmp_path / "dest")
    git = Path(imported["root"]) / ".git"
    config = (git / "config").read_text(encoding="utf-8")
    assert "fsmonitor" not in config and "include" not in config
    assert "repositoryformatversion = 0" in config
    assert (git / "HEAD").read_bytes() == b"ref: refs/heads/main\n"
    for gone in ("hooks", "modules", "objects/info/alternates", "commondir"):
        assert not (git / gone).exists()
    assert {"versions", "versions-hooks"} <= codes(imported["problems"])


def test_safe_git_config_keeps_only_the_repository_format() -> None:
    sha256 = "[core]\n\trepositoryformatversion = 1\n[extensions]\n\tobjectformat = sha256\n"
    kept = archive._safe_git_config(sha256 + "\tworktreeconfig = true\n[core]\n\tpager = evil\n")
    assert "repositoryformatversion = 1" in kept and "objectformat = sha256" in kept
    assert "worktreeconfig" not in kept and "pager" not in kept
    assert "objectformat" not in archive._safe_git_config("[extensions]\nobjectformat = sha256\n")


@pytest.mark.parametrize(
    "path", ["06 BIM/.git/config", ".git", "GIT~1/config", "a/.GIT/HEAD", "06 BIM/git~1"]
)
def test_nested_repositories_and_git_links_are_refused(tmp_path: Path, path: str) -> None:
    out = make_archive(
        tmp_path / "n.civil",
        {PROJECT: PROJECT_DATA, path: EVIL_CONFIG},
        includes={"versions": True},
    )
    report = inspect_archive(out)
    assert not report["ok"] and "nested-repository" in codes(report["problems"])


def test_versions_round_trip_and_nested_repositories_are_not_exported(
    sample: Path, tmp_path: Path
) -> None:
    git = sample / ".git"
    (git / "hooks").mkdir(parents=True)
    (git / "hooks" / "pre-commit.sample").write_text("#!/bin/sh\n", encoding="utf-8")
    (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n\tbare = false\n", encoding="utf-8"
    )
    (sample / "06 BIM" / ".git").mkdir()
    (sample / "06 BIM" / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    out = tmp_path / "v.civil"
    result = export_project(sample, out, include_versions=True, created=CREATED)
    assert {"path": "06 BIM/.git/", "reason": "nested repository"} in result["skipped"]
    assert inspect_archive(out)["ok"]
    root = Path(import_project(out, tmp_path / "dest")["root"])
    assert (root / ".git" / "HEAD").read_text(encoding="utf-8") == "ref: refs/heads/main\n"
    assert not (root / ".git" / "hooks").exists()
    assert not (root / "06 BIM" / ".git").exists()
    assert "bare = false" in (root / ".git" / "config").read_text(encoding="utf-8")


# --- Editor settings ---------------------------------------------------------------------------

#: A received project naming the program SAEngine starts for its backend (synthetic).
EVIL_SETTINGS = b'{"saengine.python.path": "\\\\\\\\attacker\\\\share\\\\python.exe"}'


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        (".vscode/settings.json", True),
        (".VSCode/settings.json", True),
        ("VSCODE~1/settings.json", True),
        ("Notes/.idea/workspace.xml", True),
        (".devcontainer/devcontainer.json", True),
        ("DEVCON~1/devcontainer.json", True),
        (".vs/x", True),
        ("06 BIM/bim.json", False),
        ("Notes/vscode notes.txt", False),
        (".gitignore", False),
    ],
)
def test_is_editor_settings(relative: str, expected: bool) -> None:
    assert archive.is_editor_settings(relative) is expected


def test_editor_settings_are_not_exported(sample: Path, tmp_path: Path) -> None:
    (sample / ".vscode").mkdir()
    (sample / ".vscode" / "settings.json").write_bytes(EVIL_SETTINGS)
    (sample / "Notes" / ".idea").mkdir(parents=True)
    (sample / "Notes" / ".idea" / "workspace.xml").write_text("<x/>", encoding="utf-8")
    out = tmp_path / "s.civil"
    result = export_project(sample, out, created=CREATED)
    assert {"path": ".vscode/", "reason": "editor settings"} in result["skipped"]
    assert {"path": "Notes/.idea/", "reason": "editor settings"} in result["skipped"]
    assert not [n for n in names(out) if "vscode" in n.casefold() or ".idea" in n]
    assert inspect_archive(out)["problems"] == []


@pytest.mark.parametrize("folder", [".vscode", ".VSCODE", "VSCODE~1", "Notes/.vscode"])
def test_received_editor_settings_are_not_extracted(tmp_path: Path, folder: str) -> None:
    settings = f"{folder}/settings.json"
    entries = {PROJECT: PROJECT_DATA, "06 BIM/bim.json": b"{}", settings: EVIL_SETTINGS}
    out = make_archive(tmp_path / "evil.civil", entries)
    report = inspect_archive(out)
    assert report["ok"] and codes(report["problems"]) == {"editor-settings"}
    assert report["files"] == 2
    imported = import_project(out, tmp_path / "dest")
    root = Path(imported["root"])
    assert "editor-settings" in codes(imported["problems"])
    assert sorted(files_of(root)) == ["06 BIM/bim.json", PROJECT]


def test_received_editor_settings_do_not_reach_an_existing_folder(tmp_path: Path) -> None:
    dest = tmp_path / "dest" / "Evil"
    (dest / ".vscode").mkdir(parents=True)
    (dest / ".vscode" / "settings.json").write_text("{}", encoding="utf-8")
    entries = {PROJECT: PROJECT_DATA, "VSCODE~1/settings.json": EVIL_SETTINGS}
    out = make_archive(tmp_path / "evil.civil", entries)
    import_project(out, tmp_path / "dest", overwrite=True)
    # (VSCODE~1 is the short name of the existing .vscode on Windows: not written through.)
    assert (dest / ".vscode" / "settings.json").read_text(encoding="utf-8") == "{}"
    assert sorted(p.name for p in dest.iterdir()) == [".vscode", PROJECT]
