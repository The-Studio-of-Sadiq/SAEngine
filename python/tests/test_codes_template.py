"""Code pack authoring: the template (create -> validate -> load), the example regional pack,
``saengine codepack`` (list, show, new, validate, diff) and the comparison of packs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from saengine.cli.codepack import main as codepack
from saengine.codes import registry
from saengine.codes.manifest import PackManifest
from saengine.codes.template import (
    TABLE_HELP,
    TemplateError,
    compare,
    diff_packs,
    known_tables,
    new_pack,
    validate_pack,
)

EXAMPLE = Path(__file__).parent / "data" / "codepacks" / "example-region"


@pytest.fixture(autouse=True)
def _no_user_packs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The user's own packs and trust store stay out of the tests."""
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user-data"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def _bnbc() -> dict:
    pack = registry.load("bnbc2020")
    return {name: pack.data(name) for name in pack.tables()}


def run_json(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict]:
    code = codepack([*argv, "--json"])
    document = json.loads(capsys.readouterr().out)
    assert document["exitCode"] == code
    return code, document


# ─────────────────────────────── template ───────────────────────────────


def test_every_table_is_documented():
    assert set(known_tables()) <= set(TABLE_HELP)


def test_new_pack_skeleton_changes_nothing(tmp_path: Path):
    folder = new_pack(tmp_path, "my-region", "My region", edition="BNBC 2020 + local")
    assert folder == tmp_path / "my-region"
    manifest = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    PackManifest.model_validate(manifest)
    assert manifest["extends"] == "bnbc2020" and manifest["covers"] == []
    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert "`extends`" in readme and "`locations`" in readme
    parent = _bnbc()
    # One help-only file per table of the parent, with an example of its format.
    assert {p.stem for p in (folder / "data").glob("*.json")} == set(parent)
    locations = json.loads((folder / "data" / "locations.json").read_text(encoding="utf-8"))
    assert set(locations) == {"$help", "$example"}
    assert locations["$example"]["locations"]["dhaka"]["windSpeed"] == 65.7

    result = validate_pack(folder)
    assert result.ok and result.id == "my-region", result.problems
    assert [p.level for p in result.problems] == ["warning"]  # no sources yet
    pack = registry.load_path(folder)
    assert pack.chain == ["my-region", "bnbc2020"]
    assert {name: pack.data(name) for name in pack.tables()} == parent
    assert diff_packs("bnbc2020", str(folder)) == []


def test_new_pack_edited_overrides_only_its_values(tmp_path: Path):
    folder = new_pack(tmp_path, "hill-towns", extends="bnbc2020")
    manifest = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    manifest["covers"] = ["locations", "factors"]
    manifest["clauses"] = {"locations": ["Local map, sheet 2"], "factors": ["Local annex A"]}
    (folder / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "data" / "locations.json").write_text(
        json.dumps(
            {
                "locations": {
                    "hilltop": {"name": "Hilltop", "zone": 4, "windSpeed": 55.0},
                    "sylhet": {"zone": 3},
                }
            }
        ),
        encoding="utf-8",
    )
    (folder / "data" / "factors.json").write_text(
        json.dumps({"phi": {"shear": 0.7}}), encoding="utf-8"
    )
    result = validate_pack(folder)
    assert result.ok and not result.problems, result.problems
    pack = registry.load_path(folder)
    parent = _bnbc()
    locations = pack.data("locations")["locations"]
    assert locations["hilltop"] == {"name": "Hilltop", "zone": 4, "windSpeed": 55.0}
    assert locations["sylhet"] == {**parent["locations"]["locations"]["sylhet"], "zone": 3}
    assert locations["dhaka"] == parent["locations"]["locations"]["dhaka"]
    phi = pack.data("factors")["phi"]
    assert phi["shear"] == 0.7
    assert {k: v for k, v in phi.items() if k != "shear"} == {
        k: v for k, v in parent["factors"]["phi"].items() if k != "shear"
    }
    for name in set(parent) - {"locations", "factors"}:
        assert pack.data(name) == parent[name], name
    assert pack.source("locations") == ["Local map, sheet 2"]
    changed = {d.path for d in diff_packs("bnbc2020", str(folder))}
    assert changed == {
        "locations.locations.hilltop",
        "locations.locations.sylhet.zone",
        "factors.phi.shear",
    }


def test_new_pack_refuses(tmp_path: Path):
    with pytest.raises(TemplateError, match="not a pack id"):
        new_pack(tmp_path, "My Region")
    with pytest.raises(TemplateError, match="cannot extend"):
        new_pack(tmp_path, "orphan", extends="no-such-pack")
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(TemplateError, match="not empty"):
        new_pack(tmp_path, "taken")
    # Files where folders are expected: a TemplateError, never a raw OSError.
    a_file = tmp_path / "a-file.txt"
    a_file.write_text("x", encoding="utf-8")
    with pytest.raises(TemplateError, match="is a file"):
        new_pack(a_file, "x")
    (tmp_path / "clash").write_text("x", encoding="utf-8")
    with pytest.raises(TemplateError, match="is a file"):
        new_pack(tmp_path, "clash")
    # dest below a file: mkdir fails with an OSError, reported as a TemplateError.
    with pytest.raises(TemplateError):
        new_pack(a_file / "sub", "x")


def test_cli_new_on_a_file_exits_2(capsys: pytest.CaptureFixture[str], tmp_path: Path):
    a_file = tmp_path / "a-file.txt"
    a_file.write_text("x", encoding="utf-8")
    assert codepack(["new", "x", "--dest", str(a_file)]) == 2
    assert codepack(["new", "x", "--dest", str(a_file / "sub")]) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_named_list_help_is_followable(tmp_path: Path):
    """The combinations help gives the item form of $remove, and following it drops the item."""
    folder = new_pack(tmp_path, "combo")
    help_ = json.loads((folder / "data" / "combinations.json").read_text(encoding="utf-8"))
    text = " ".join(help_["$help"])
    assert '{"name": "...", "$remove": true}' in text and "strength" in text
    assert "no service combinations" in text and "overstrength" in text
    strength = _bnbc()["combinations"]["strength"]
    dropped = strength[0]["name"]
    manifest = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    manifest["covers"] = ["combinations"]
    manifest["clauses"] = {"combinations": ["Test schedule"]}
    (folder / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "data" / "combinations.json").write_text(
        json.dumps({"strength": [{"name": dropped, "$remove": True}]}), encoding="utf-8"
    )
    names = [c["name"] for c in registry.load_path(folder).data("combinations")["strength"]]
    assert names == [c["name"] for c in strength[1:]]
    # Locations has no named lists: no such line.
    locations = json.loads((folder / "data" / "locations.json").read_text(encoding="utf-8"))
    assert not any("matched by name" in line for line in locations["$help"])


def test_validate_reports_problems(tmp_path: Path):
    folder = new_pack(tmp_path, "broken")
    (folder / "data" / "locations.json").write_text(
        json.dumps({"locations": {"nowhere": {"name": "Nowhere", "zone": 1, "windSpeed": -5}}}),
        encoding="utf-8",
    )
    result = validate_pack(folder)
    assert not result.ok
    assert any("windSpeed" in p.message for p in result.problems if p.level == "error")
    # values in a file whose table is not in covers
    assert any("not in covers" in p.message for p in result.problems)
    (folder / "data" / "wind.json").write_text("{ not json", encoding="utf-8")
    assert any(p.where == "data/wind.json" for p in validate_pack(folder).problems)
    assert not validate_pack(tmp_path / "missing").ok


def test_validate_reads_data_wrapper_and_removals(tmp_path: Path):
    """The authoring checks read a table file the way the loader does: the ``$data`` wrapper
    and a ``$remove``-only file change the parent, ``$help``/``$example`` do not."""
    folder = new_pack(tmp_path, "wrapped")
    manifest_path = folder / "pack.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["clauses"] = {"factors": ["Local annex A"]}
    factors = folder / "data" / "factors.json"
    factors.write_text(json.dumps({"$data": {"phi": {"shear": 0.7}}}), encoding="utf-8")

    def messages(covers: list[str]) -> list[str]:
        manifest["covers"] = covers
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        registry.clear_cache()
        return [p.message for p in validate_pack(folder).problems]

    assert messages(["factors"]) == []
    assert registry.load_path(folder).data("factors")["phi"]["shear"] == 0.7
    assert messages([]) == ["has values but 'factors' is not in covers"]
    # A required φ cannot be removed (the program reads it); an extra one (for hooks) can.
    factors.write_text(json.dumps({"phi": {"$remove": ["shear"]}}), encoding="utf-8")
    assert messages(["factors"]) == ["factors: phi.shear: Field required"]
    factors.write_text(
        json.dumps({"$data": {"phi": {"shear": 0.7, "localExtra": 0.8}}}), encoding="utf-8"
    )
    assert messages(["factors"]) == []
    assert registry.load_path(folder).data("factors")["phi"]["localExtra"] == 0.8
    factors.write_text(json.dumps({"phi": {"$remove": ["localExtra"]}}), encoding="utf-8")
    assert messages(["factors"]) == []
    assert "localExtra" not in registry.load_path(folder).data("factors")["phi"]
    factors.write_text(json.dumps({"$help": "x", "$example": {"phi": {}}}), encoding="utf-8")
    assert messages(["factors"]) == ["covers 'factors' but data/factors.json has only help"]


# ─────────────────────────────── the example pack ───────────────────────────────


def test_example_pack_overrides_and_inherits():
    result = validate_pack(EXAMPLE)
    assert result.ok and not result.problems, result.problems
    pack = registry.load_path(EXAMPLE)
    parent = _bnbc()
    towns = pack.data("locations")["locations"]
    old = parent["locations"]["locations"]
    assert towns["northford"] == {"name": "Northford", "zone": 3, "windSpeed": 58.0}
    assert towns["saltmarsh"]["windSpeed"] == 84.5
    assert towns["chattogram"] == {**old["chattogram"], "windSpeed": 82.0}
    assert {
        k: v for k, v in towns.items() if k not in ("northford", "saltmarsh", "chattogram")
    } == {k: v for k, v in old.items() if k != "chattogram"}
    strength = {c["name"]: c["factors"] for c in pack.data("combinations")["strength"]}
    assert "1.2D + 1.0E + 1.0L" not in strength
    assert strength["1.2D + 1.0E + 0.5L"] == {"D": 1.2, "E": 1.0, "L": 0.5}
    old_strength = {c["name"]: c["factors"] for c in parent["combinations"]["strength"]}
    assert {k: v for k, v in strength.items() if k != "1.2D + 1.0E + 0.5L"} == {
        k: v for k, v in old_strength.items() if k != "1.2D + 1.0E + 1.0L"
    }
    combos = pack.data("combinations")
    assert combos["seismicDeadUpper"] == parent["combinations"]["seismicDeadUpper"]
    for name in set(parent) - {"locations", "combinations"}:
        assert pack.data(name) == parent[name], name
    # validated models too
    assert pack.table("locations").locations["chattogram"].windSpeed == 82.0
    assert pack.table("locations").locations["chattogram"].zone == old["chattogram"]["zone"]


def test_example_pack_as_project_pack(tmp_path: Path):
    project = tmp_path / "Project"
    shutil.copytree(EXAMPLE, project / "02 Project Settings" / "code-packs" / "example-region")
    ids = {(p.id, p.scope) for p in registry.list_packs(project)}
    assert {("bnbc2020", "builtin"), ("example-region", "project")} <= ids
    pack = registry.active({"codePack": "example-region"}, project)
    assert pack.id == "example-region"
    assert pack.data("locations")["locations"]["saltmarsh"]["zone"] == 1


# ─────────────────────────────── compare ───────────────────────────────


def test_compare_keys_and_named_lists():
    a = {"t": {"x": 1, "y": [1, 2], "rows": [{"name": "A", "v": 1}, {"name": "B", "v": 2}]}}
    b = {"t": {"x": 2, "z": 3, "y": [1], "rows": [{"name": "B", "v": 3}]}}
    found = {(d.path, d.kind) for d in compare(a, b)}
    assert found == {
        ("t.x", "changed"),
        ("t.y[1]", "removed"),
        ("t.rows.[A]", "removed"),
        ("t.rows.[B].v", "changed"),
        ("t.z", "added"),
    }
    assert compare(a, a) == []


# ─────────────────────────────── command line ───────────────────────────────


def test_cli_list_and_show(capsys: pytest.CaptureFixture[str], tmp_path: Path):
    assert codepack(["list"]) == 0
    assert "bnbc2020" in capsys.readouterr().out
    code, document = run_json(capsys, "list")
    assert code == 0 and any(p["id"] == "bnbc2020" for p in document["packs"])
    code, document = run_json(capsys, "show", "bnbc2020")
    assert code == 0 and document["pack"]["id"] == "bnbc2020"
    assert document["tables"]["locations"]["providedBy"] == "bnbc2020"
    assert codepack(["show", str(EXAMPLE)]) == 0
    text = capsys.readouterr().out
    assert "inheritance: example-region -> bnbc2020" in text
    assert "locations" in text and "own" in text
    code, document = run_json(capsys, "show", "no-such-pack")
    assert code == 2 and "no-such-pack" in document["error"]


def test_cli_new_validate_diff(capsys: pytest.CaptureFixture[str], tmp_path: Path):
    code, document = run_json(capsys, "new", "coast", "--name", "Coast",
                              "--dest", str(tmp_path))  # fmt: skip
    assert code == 0 and Path(document["path"]) == (tmp_path / "coast").resolve()
    code, document = run_json(capsys, "validate", str(tmp_path / "coast"))
    assert code == 0 and document["ok"]
    code, _ = run_json(capsys, "new", "coast", "--dest", str(tmp_path))
    assert code == 2  # exists
    code, document = run_json(capsys, "diff", "bnbc2020", str(EXAMPLE))
    assert code == 0
    paths = {d["path"] for d in document["differences"]}
    assert "locations.locations.chattogram.windSpeed" in paths
    assert codepack(["diff", "bnbc2020", str(EXAMPLE)]) == 0
    assert "~ locations.locations.chattogram.windSpeed: 80.0 -> 82.0" in capsys.readouterr().out

    (tmp_path / "coast" / "data" / "seismic.json").write_text("[1, 2", encoding="utf-8")
    code, document = run_json(capsys, "validate", str(tmp_path / "coast"))
    assert code == 1 and not document["ok"]
    assert codepack(["validate", str(tmp_path / "coast")]) == 1
    assert "not usable" in capsys.readouterr().out
    assert codepack(["frobnicate"]) == 2


def test_root_pack_skeleton(tmp_path: Path):
    """A pack that extends nothing: BNBC's tables as examples; usable once every table is full."""
    folder = new_pack(tmp_path, "standalone", extends=None)
    manifest = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    assert manifest["extends"] is None
    help_ = json.loads((folder / "data" / "wind.json").read_text(encoding="utf-8"))
    assert "extends no other" in help_["$help"][1] and "exposures" in help_["$example"]
    assert not validate_pack(folder).ok
    parent = _bnbc()
    for name, data in parent.items():
        (folder / "data" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    manifest["covers"] = sorted(parent)
    manifest["sources"] = [{"id": "BNBC", "title": "BNBC 2020"}]
    (folder / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_pack(folder)
    assert result.ok, result.problems
    assert diff_packs("bnbc2020", str(folder)) == []
