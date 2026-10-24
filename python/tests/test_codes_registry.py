"""The code pack core: discovery, inheritance and merge, problems, trust of hooks, caching."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from saengine.codes import CodePackError, Registry, registry
from saengine.codes.manifest import manifest_schema
from saengine.codes.merge import merge, parse_table_file, resolve_table
from saengine.codes.registry import PROJECT_PACKS, SCHEMAS_DIR, schema_documents
from saengine.codes.trust import TrustStore


def write_pack(
    base: Path,
    pack_id: str,
    tables: dict | None = None,
    folder: str | None = None,
    **manifest,
) -> Path:
    d = base / (folder or pack_id)
    (d / "data").mkdir(parents=True, exist_ok=True)
    doc = {"schema": "saengine.codePack/1", "id": pack_id, "name": pack_id.upper(), **manifest}
    (d / "pack.json").write_text(json.dumps(doc), encoding="utf-8")
    for name, data in (tables or {}).items():
        (d / "data" / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return d


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    # the core alone: no table models (the BNBC models are tested in test_codes_bnbc_pack.py)
    from saengine.codes import registry as reg_module

    monkeypatch.setattr(reg_module, "_VALIDATORS", {})
    monkeypatch.setattr(reg_module, "_TABLES_IMPORTED", True)
    monkeypatch.setattr(reg_module, "_GENERATION", [reg_module._GENERATION[0] + 1])
    ns = SimpleNamespace(
        builtin=tmp_path / "builtin",
        user=tmp_path / "user",
        project=tmp_path / "project",
        trust=tmp_path / "trust.json",
    )
    ns.project_packs = ns.project / PROJECT_PACKS
    for d in (ns.builtin, ns.user, ns.project_packs):
        d.mkdir(parents=True)
    ns.reg = Registry(builtin_dir=ns.builtin, user_dir=ns.user, trust_store=TrustStore(ns.trust))
    return ns


BASE_TABLES = {
    "locations": {
        "source": "Table 1",
        "locations": {
            "a": {"name": "A", "zone": 1, "windSpeed": 50.0},
            "b": {"name": "B", "zone": 2, "windSpeed": 60.0},
        },
    },
    "combinations": {
        "$sources": ["Code 2.7.3"],
        "strength": [
            {"name": "1.4D", "factors": {"D": 1.4}},
            {"name": "1.2D + 1.6L", "factors": {"D": 1.2, "L": 1.6}},
        ],
        "service": [{"name": "D + L", "factors": {"D": 1.0, "L": 1.0}}],
    },
    "factors": {"phi": {"flexure": 0.9, "shear": 0.75}, "bars": [10, 12, 16]},
}


# ---------------------------------------------------------------- merge rules


def test_merge_dicts_deep_lists_replaced_and_directives():
    base = {"a": {"x": 1, "y": 2}, "l": [1, 2], "gone": 1}
    out = merge(base, {"a": {"y": 3, "z": 4}, "l": [9], "$remove": ["gone"]})
    assert out == {"a": {"x": 1, "y": 3, "z": 4}, "l": [9]}
    assert base == {"a": {"x": 1, "y": 2}, "l": [1, 2], "gone": 1}  # not modified
    assert merge(base, {"a": {"$replace": True, "q": 1}}) == {
        "a": {"q": 1},
        "l": [1, 2],
        "gone": 1,
    }


def test_merge_lists_by_key():
    base = [{"name": "p", "v": 1, "w": 1}, {"name": "q", "v": 2}, {"name": "r", "v": 3}]
    out = merge(
        base,
        [{"name": "q", "v": 20}, {"name": "r", "$remove": True}, {"name": "s", "v": 4}],
        {"": "name"},
    )
    assert out == [{"name": "p", "v": 1, "w": 1}, {"name": "q", "v": 20}, {"name": "s", "v": 4}]
    nested = merge({"k": base}, {"k": [{"name": "p", "v": 5}]}, {"k": "name"})
    assert nested["k"][0] == {"name": "p", "v": 5, "w": 1} and len(nested["k"]) == 3


def test_table_file_wrapper_and_replace():
    f = parse_table_file({"$data": [1, 2], "$sources": ["c"], "$mergeKeys": {}})
    assert f.data == [1, 2] and f.sources == ["c"]
    parent = parse_table_file({"a": 1, "b": 2})
    child = parse_table_file({"$replace": True, "c": 3})
    assert resolve_table([parent, child]) == {"c": 3}
    with pytest.raises(TypeError):
        parse_table_file({"$sources": "not a list"})


# ---------------------------------------------------------------- discovery, precedence


def test_discovery_precedence_project_over_user_over_builtin(dirs):
    write_pack(dirs.builtin, "base", BASE_TABLES, edition="builtin")
    write_pack(dirs.user, "base", BASE_TABLES, edition="user")
    write_pack(dirs.project_packs, "base", BASE_TABLES, edition="project")
    assert dirs.reg.load("base").edition == "user"  # no project given
    pack = dirs.reg.load("base", dirs.project)
    assert pack.edition == "project" and pack.scope == "project"

    infos = [i for i in dirs.reg.list_packs(dirs.project) if i.id == "base"]
    assert [i.scope for i in infos] == ["project", "user", "builtin"]
    project, user, builtin = infos
    assert project.effective and project.shadows == ["user", "builtin"]
    assert not user.effective and user.shadowedBy == "project"
    assert not builtin.effective and builtin.shadowedBy == "project"
    assert all(i.usable for i in infos) and not user.problems and not builtin.problems
    # the winning copy is flagged: it replaces the built-in code for this project
    assert [p.severity for p in project.problems] == ["warning"]
    assert "replaces the built-in pack 'base' for this project" in project.problems[0].message


def test_extending_own_id_builds_on_lower_scope(dirs):
    write_pack(dirs.builtin, "base", BASE_TABLES)
    write_pack(
        dirs.project_packs,
        "base",
        {"locations": {"locations": {"a": {"windSpeed": 55.5}}}},
        extends="base",
    )
    pack = dirs.reg.load("base", dirs.project)
    assert pack.chain == ["base", "base"] and pack.scope == "project"
    locs = pack.data("locations")["locations"]
    assert locs["a"] == {"name": "A", "zone": 1, "windSpeed": 55.5}
    assert locs["b"]["windSpeed"] == 60.0
    assert pack.has("factors") and pack.provided_by("factors") == "base"


def test_inheritance_overrides_only_provided_tables(dirs):
    write_pack(dirs.builtin, "base", BASE_TABLES, clauses={"factors": ["Code 9.3"]})
    write_pack(
        dirs.user,
        "region",
        {
            "locations": {
                "$sources": ["Gazette 2026"],
                "locations": {"c": {"name": "C", "zone": 3, "windSpeed": 70.0}},
                "$remove": [],
            },
            # combinations merge by name by default: one changed, one added
            "combinations": {
                "strength": [
                    {"name": "1.2D + 1.6L", "factors": {"L": 1.5}},
                    {"name": "0.9D", "factors": {"D": 0.9}},
                ]
            },
            "factors": {"phi": {"shear": 0.7}, "bars": [12, 16]},
        },
        extends="base",
        covers=["locations", "combinations", "factors"],
    )
    pack = dirs.reg.load("region")
    assert pack.chain == ["region", "base"]
    assert set(pack.data("locations")["locations"]) == {"a", "b", "c"}
    strength = pack.data("combinations")["strength"]
    assert [c["name"] for c in strength] == ["1.4D", "1.2D + 1.6L", "0.9D"]
    assert strength[1]["factors"] == {"D": 1.2, "L": 1.5}
    assert pack.data("combinations")["service"] == BASE_TABLES["combinations"]["service"]
    assert pack.data("factors") == {"phi": {"flexure": 0.9, "shear": 0.7}, "bars": [12, 16]}
    assert pack.source("locations") == ["Gazette 2026"]
    assert pack.source("combinations") == ["Code 2.7.3"]  # inherited with the table
    assert pack.source("factors") == ["Code 9.3"]  # the manifest's clauses
    # the parent is untouched
    assert set(registry_load_plain(dirs, "base")["locations"]) == {"a", "b"}


def registry_load_plain(dirs, pack_id):
    return dirs.reg.load(pack_id).data("locations")


def test_replace_whole_table(dirs):
    write_pack(dirs.builtin, "base", BASE_TABLES)
    write_pack(
        dirs.user,
        "child",
        {"factors": {"$replace": True, "phi": {"flexure": 0.85}}},
        extends="base",
    )
    assert dirs.reg.load("child").data("factors") == {"phi": {"flexure": 0.85}}


# ---------------------------------------------------------------- problems never raise


def test_bad_packs_are_listed_with_problems_not_raised(dirs):
    write_pack(dirs.builtin, "base", BASE_TABLES)
    broken = dirs.user / "broken"
    broken.mkdir()
    (broken / "pack.json").write_text("{not json", encoding="utf-8")
    bad_data = write_pack(dirs.user, "baddata", extends="base")
    (bad_data / "data" / "factors.json").write_text("[1, 2", encoding="utf-8")
    write_pack(dirs.user, "orphan", {}, extends="missing")
    write_pack(dirs.user, "Bad Id!", {}, folder="badid")
    write_pack(dirs.user, "child-of-broken", {}, extends="broken")
    write_pack(dirs.user, "warn", {}, folder="other-folder", covers=["nonsense", "wind"])

    infos = {i.id: i for i in dirs.reg.list_packs()}
    assert infos["base"].usable
    for pack_id in ("broken", "baddata", "orphan", "Bad Id!", "child-of-broken"):
        assert not infos[pack_id].usable, pack_id
        assert any(p.severity == "error" for p in infos[pack_id].problems), pack_id
        with pytest.raises(CodePackError) as e:
            dirs.reg.load(pack_id)
        assert e.value.problems
    assert "not installed" in infos["orphan"].problems[0].message
    assert "parent" in infos["child-of-broken"].problems[-1].message
    warn = infos["warn"]
    assert warn.usable and {p.severity for p in warn.problems} == {"warning"}
    assert len(warn.problems) == 3  # folder name, unknown area, covers without data
    with pytest.raises(CodePackError):
        dirs.reg.load("nothing-here")


def test_duplicate_ids_in_one_scope(dirs):
    write_pack(dirs.user, "dup", {}, folder="a-dup", edition="first")
    write_pack(dirs.user, "dup", {}, folder="b-dup", edition="second")
    infos = [i for i in dirs.reg.list_packs() if i.id == "dup"]
    assert len(infos) == 2 and sum(i.usable for i in infos) == 1
    assert dirs.reg.load("dup").edition == "first"


def test_broken_higher_copy_falls_back_to_working_lower_copy(dirs):
    write_pack(dirs.builtin, "base", BASE_TABLES, edition="builtin")
    # a broken user copy (folder name differs, data unreadable) that extends the built-in
    broken = write_pack(dirs.user, "base", {}, folder="mine", extends="base", edition="user")
    (broken / "data" / "factors.json").write_text("{bad", encoding="utf-8")
    # an unusable project copy without file errors (its parent id is missing)
    write_pack(dirs.project_packs, "base", {}, extends="missing", edition="project")
    write_pack(dirs.user, "child", {"factors": {"phi": {"shear": 0.7}}}, extends="base")

    for root in (None, dirs.project):
        pack = dirs.reg.active({"codePack": "base"}, root)  # the id still works
        assert pack.scope == "builtin" and pack.edition == "builtin"
        assert pack.data("factors")["phi"]["flexure"] == 0.9
        assert not pack.replaces_builtin and not pack.warnings
        child = dirs.reg.load("child", root)  # children build on the working copy
        assert child.chain == ["child", "base"] and child.data("factors")["phi"]["shear"] == 0.7
        assert dirs.reg.info("base", root).scope == "builtin"

    infos = {(i.id, i.scope): i for i in dirs.reg.list_packs(dirs.project)}
    builtin, user, project = (infos["base", s] for s in ("builtin", "user", "project"))
    assert builtin.effective and builtin.usable and set(builtin.shadows) == {"user", "project"}
    for info in (user, project):
        assert not info.effective and not info.usable and info.shadowedBy == "builtin"
        assert any(p.severity == "error" for p in info.problems)
        assert any("builtin copy" in p.message for p in info.problems)
    assert infos["child", "user"].usable


def test_working_copy_of_builtin_is_used_but_flagged(dirs):
    write_pack(dirs.builtin, "base", BASE_TABLES)
    write_pack(dirs.user, "base", {"factors": {"phi": {"flexure": 0.5}}}, extends="base")
    pack = dirs.reg.active({"codePack": "base"})
    assert pack.scope == "user" and pack.data("factors")["phi"]["flexure"] == 0.5
    assert pack.replaces_builtin
    assert any("every project on this machine" in w.message for w in pack.warnings)
    info = dirs.reg.info("base")
    assert info.usable and info.effective and info.shadows == ["builtin"]
    assert any("replaces the built-in pack" in p.message for p in info.problems)
    # a project copy says it affects this project only
    write_pack(dirs.project_packs, "base", {}, extends="base")
    project = dirs.reg.load("base", dirs.project)
    assert project.chain == ["base", "base", "base"] and project.replaces_builtin
    assert any("this project" in w.message for w in project.warnings)
    # a pack with no built-in namesake carries no such note
    write_pack(dirs.user, "other", {})
    assert not dirs.reg.load("other").replaces_builtin and not dirs.reg.load("other").warnings


def test_inheritance_cycle(dirs):
    write_pack(dirs.user, "a", {}, extends="b")
    write_pack(dirs.user, "b", {}, extends="c")
    write_pack(dirs.user, "c", {}, extends="a")
    infos = {i.id: i for i in dirs.reg.list_packs()}
    for pack_id in "abc":
        assert not infos[pack_id].usable
        assert any("cycle" in p.message for p in infos[pack_id].problems)
    with pytest.raises(CodePackError, match="cycle"):
        dirs.reg.load("a")


def test_table_validation_through_registered_models(dirs, monkeypatch):
    from saengine.codes import registry as reg_module

    class Thing(BaseModel):
        model_config = ConfigDict(extra="forbid")
        value: float

    validators = {}
    validators["zzThing"] = reg_module._Validator(reg_module.TypeAdapter(Thing), Thing, {})
    monkeypatch.setattr(reg_module, "_VALIDATORS", validators)
    monkeypatch.setattr(reg_module, "_GENERATION", [reg_module._GENERATION[0] + 1])
    write_pack(dirs.user, "good", {"zzThing": {"value": 2}})
    write_pack(dirs.user, "bad", {"zzThing": {"value": "two"}})
    write_pack(dirs.user, "child", {"zzThing": {"extra": 1}}, extends="good")
    good = dirs.reg.load("good")
    assert isinstance(good.table("zzThing"), Thing) and good.table("zzThing").value == 2
    assert good.data("zzThing") == {"value": 2}
    infos = {i.id: i for i in dirs.reg.list_packs()}
    assert not infos["bad"].usable and infos["bad"].problems[0].table == "zzThing"
    assert not infos["child"].usable  # the merged table is validated
    with pytest.raises(KeyError):
        good.table("nope")


# ---------------------------------------------------------------- hooks and trust

HOOKS = """
from pathlib import Path
Path(__file__).with_name("imported.marker").write_text("x")

def column_min_size(height):
    return 0.3 if height < 3.5 else 0.35
"""


def test_hooks_run_only_when_trusted_and_editing_revokes(dirs):
    pack_dir = write_pack(dirs.user, "hooked", {}, hooks="hooks.py")
    (pack_dir / "hooks.py").write_text(HOOKS, encoding="utf-8")
    marker = pack_dir / "imported.marker"

    pack = dirs.reg.load("hooked")
    info = dirs.reg.info("hooked")
    assert info.hooks and info.trusted is False
    assert pack.hook("column_min_size") is None and not pack.trusted
    assert not marker.exists()  # never imported while untrusted

    assert dirs.reg.set_trusted("hooked", True).trusted
    fn = pack.hook("column_min_size")
    assert fn is not None and fn(3.0) == 0.3 and marker.exists()
    assert pack.hook("missing_function") is None
    assert json.loads(dirs.trust.read_text())["trusted"]["hooked"][0]["sha256"]

    (pack_dir / "hooks.py").write_text(HOOKS + "\n# edited\n", encoding="utf-8")
    assert dirs.reg.info("hooked").trusted is False
    assert dirs.reg.load("hooked").hook("column_min_size") is None
    # a helper module next to the hooks is part of the trusted code too
    dirs.reg.set_trusted("hooked", True)
    assert dirs.reg.info("hooked").trusted
    (pack_dir / "helper.py").write_text("X = 1\n", encoding="utf-8")
    assert dirs.reg.info("hooked").trusted is False

    dirs.reg.set_trusted("hooked", True)
    dirs.reg.set_trusted("hooked", False)
    assert dirs.reg.info("hooked").trusted is False


def test_builtin_hooks_are_trusted_and_missing_hooks_file_is_a_problem(dirs):
    pack_dir = write_pack(dirs.builtin, "core", {}, hooks="hooks.py")
    (pack_dir / "hooks.py").write_text("def f():\n    return 7\n", encoding="utf-8")
    assert dirs.reg.load("core").hook("f")() == 7
    write_pack(dirs.user, "nohooks", {}, hooks="hooks.py")
    write_pack(dirs.user, "escape", {}, hooks="../core/hooks.py")
    infos = {i.id: i for i in dirs.reg.list_packs()}
    assert not infos["nohooks"].usable and not infos["escape"].usable
    with pytest.raises(CodePackError):
        dirs.reg.set_trusted("base-not-there", True)


# ---------------------------------------------------------------- caching


def test_cache_follows_file_times(dirs):
    pack_dir = write_pack(dirs.user, "base", BASE_TABLES)
    first = dirs.reg.load("base")
    assert dirs.reg.load("base") is first  # cached
    path = pack_dir / "data" / "factors.json"
    path.write_text(json.dumps({"phi": {"flexure": 0.875}}), encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    second = dirs.reg.load("base")
    assert second is not first and second.data("factors") == {"phi": {"flexure": 0.875}}
    # a new project pack with the same id takes over
    write_pack(dirs.project_packs, "base", BASE_TABLES, edition="p")
    assert dirs.reg.load("base", dirs.project).edition == "p"
    # a parent's change reaches the child
    write_pack(dirs.user, "kid", {}, extends="base")
    assert dirs.reg.load("kid").data("factors")["phi"]["flexure"] == 0.875
    path.write_text(json.dumps({"phi": {"flexure": 0.8}}), encoding="utf-8")
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 20_000_000))
    assert dirs.reg.load("kid").data("factors")["phi"]["flexure"] == 0.8


# ---------------------------------------------------------------- active, install, validate


def test_active_reads_code_pack_setting(dirs):
    write_pack(dirs.builtin, "bnbc2020", BASE_TABLES)
    write_pack(dirs.user, "other", {})
    assert dirs.reg.active(None).id == "bnbc2020"
    assert dirs.reg.active({"project": {"name": "x"}}).id == "bnbc2020"
    assert dirs.reg.active({"codePack": "other"}).id == "other"
    assert dirs.reg.active(SimpleNamespace(codePack="other")).id == "other"
    with pytest.raises(CodePackError):
        dirs.reg.active({"codePack": "unknown"})


def test_install_folder_and_zip_and_validate(dirs, tmp_path):
    write_pack(dirs.builtin, "base", BASE_TABLES)
    src = write_pack(tmp_path / "src", "mine", {"factors": {"phi": {"shear": 0.6}}}, extends="base")
    info = dirs.reg.install(src, "user")
    assert info.scope == "user" and info.usable and (dirs.user / "mine" / "pack.json").is_file()
    with pytest.raises(CodePackError, match="already installed"):
        dirs.reg.install(src, "user")

    zpath = tmp_path / "mine.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in src.rglob("*"):
            if f.is_file():
                zf.write(f, f"mine/{f.relative_to(src).as_posix()}")
    info = dirs.reg.install(zpath, "project", dirs.project)
    assert info.scope == "project" and info.shadows == ["user"]

    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../pack.json", "{}")
    with pytest.raises(CodePackError, match="unsafe"):
        dirs.reg.install(evil, "user")

    checked = dirs.reg.validate(src)
    assert checked.scope == "folder" and checked.usable and checked.chain == ["mine", "base"]
    assert dirs.reg.load_path(src).data("factors")["phi"] == {"flexure": 0.9, "shear": 0.6}
    assert not dirs.reg.validate(tmp_path).usable


def test_malformed_merge_directives_are_problems_not_crashes(dirs):
    write_pack(dirs.builtin, "base", BASE_TABLES)
    write_pack(dirs.user, "bad1", {"combinations": {"$remove": [{"a": 1}, ["x"]]}}, extends="base")
    write_pack(
        dirs.user,
        "bad2",
        {"combinations": {"strength": [{"name": ["x"], "factors": {}}, {"name": {"y": 1}}]}},
        extends="base",
    )
    infos = {i.id: i for i in dirs.reg.list_packs()}  # never raises
    assert infos["base"].usable
    # non-key entries are ignored: $remove of a non-string, items whose key is not a scalar
    assert infos["bad1"].usable
    assert dirs.reg.load("bad1").data("combinations") == strip_sources(BASE_TABLES["combinations"])
    strength = dirs.reg.load("bad2").data("combinations")["strength"]
    assert [c["name"] for c in strength] == ["1.4D", "1.2D + 1.6L", ["x"], {"y": 1}]


def test_merge_errors_are_reported_per_table(dirs, monkeypatch):
    from saengine.codes import registry as reg_module

    def boom(files, keys=None):
        raise RuntimeError("bad merge")

    write_pack(dirs.user, "base", BASE_TABLES)
    monkeypatch.setattr(reg_module, "resolve_table", boom)
    infos = {i.id: i for i in dirs.reg.list_packs()}
    assert not infos["base"].usable
    assert any("bad merge" in p.message and p.table for p in infos["base"].problems)


def strip_sources(table):
    return {k: v for k, v in table.items() if not k.startswith("$")}


def test_utf8_bom_files_are_read(dirs):
    d = write_pack(dirs.user, "bom", {})
    for path, doc in (
        (d / "pack.json", {"schema": "saengine.codePack/1", "id": "bom", "name": "BOM"}),
        (d / "data" / "factors.json", {"phi": {"flexure": 0.9}}),
    ):
        path.write_bytes(b"\xef\xbb\xbf" + json.dumps(doc).encode("utf-8"))
    info = dirs.reg.info("bom")
    assert info.usable, info.problems
    assert dirs.reg.load("bom").data("factors") == {"phi": {"flexure": 0.9}}


def test_install_never_deletes_the_source(dirs, tmp_path):
    write_pack(dirs.builtin, "base", BASE_TABLES)
    installed = write_pack(dirs.user, "hp", {"factors": {"phi": {"shear": 0.6}}}, extends="base")
    # reinstalling the installed folder itself: kept as it is
    info = dirs.reg.install(installed, "user", replace=True)
    assert info.usable and (installed / "data" / "factors.json").is_file()
    # a folder inside the installed one (or containing it) is refused, nothing is deleted
    inner = write_pack(installed, "hp", {}, folder="copy")
    with pytest.raises(CodePackError, match="contain one another"):
        dirs.reg.install(inner, "user", replace=True)
    assert (installed / "pack.json").is_file() and (inner / "pack.json").is_file()
    # replacing from another folder swaps the content
    other = write_pack(tmp_path / "src", "hp", {"factors": {"phi": {"shear": 0.5}}}, extends="base")
    dirs.reg.install(other, "user", replace=True)
    assert dirs.reg.load("hp").data("factors")["phi"]["shear"] == 0.5
    assert (other / "pack.json").is_file()


def test_parent_hooks_show_on_child_and_trusting_child_trusts_chain(dirs):
    parent = write_pack(dirs.user, "hp", {}, hooks="hooks.py")
    (parent / "hooks.py").write_text("def phi():\n    return 0.8\n", encoding="utf-8")
    write_pack(dirs.user, "hc", {}, extends="hp")
    info = dirs.reg.info("hc")
    assert info.usable and info.hooks and info.trusted is False
    assert info.hooksFrom == ["hp"] and info.untrustedHooks == ["hp"]
    assert dirs.reg.load("hc").hook("phi") is None

    trusted = dirs.reg.set_trusted("hc", True)
    assert trusted.trusted and trusted.untrustedHooks == []
    assert dirs.reg.load("hc").hook("phi")() == 0.8
    assert dirs.reg.info("hp").trusted
    assert dirs.reg.info("hc").trusted is True
    write_pack(dirs.user, "plain", {})
    assert dirs.reg.info("plain").hooks is False and dirs.reg.info("plain").trusted is None
    with pytest.raises(CodePackError, match="no hooks"):
        dirs.reg.set_trusted("plain", True)


def test_hooks_run_the_bytes_that_were_hashed(dirs, monkeypatch):
    from saengine.codes import registry as reg_module

    pack_dir = write_pack(dirs.user, "race", {}, hooks="hooks.py")
    hooks = pack_dir / "hooks.py"
    hooks.write_text("def f():\n    return 'trusted'\n", encoding="utf-8")
    dirs.reg.set_trusted("race", True)
    real = reg_module.read_code

    def read_then_swap(path, name):
        result = real(path, name)  # hashed and trusted ...
        hooks.write_text("def f():\n    return 'swapped'\n", encoding="utf-8")  # ... then edited
        return result

    monkeypatch.setattr(reg_module, "read_code", read_then_swap)
    assert dirs.reg.load("race").hook("f")() == "trusted"


# ---------------------------------------------------------------- the built-in packs


def test_builtin_bnbc_pack_loads_cleanly(monkeypatch, tmp_path):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path))
    infos = {i.id: i for i in registry.list_packs()}
    assert "bnbc2020" in infos and infos["bnbc2020"].scope == "builtin"
    assert infos["bnbc2020"].usable, infos["bnbc2020"].problems
    pack = registry.active({})
    assert pack.id == "bnbc2020" and pack.has("combinations")
    assert pack.source("combinations")


def test_exported_schemas_are_current():
    # check only: regenerate with registry.export_schemas() (never rewritten by the test)
    docs = schema_documents()
    assert docs["code-pack.schema.json"] == manifest_schema()
    stale = [
        file
        for file, schema in docs.items()
        if not (SCHEMAS_DIR / file).is_file()
        or json.loads((SCHEMAS_DIR / file).read_text(encoding="utf-8")) != schema
    ]
    assert stale == [], f"codes/schemas is out of date: {stale}; run registry.export_schemas()"
