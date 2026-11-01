"""Packages of every kind in the code pack registry (docs/marketplace-plan.md, round M1): the
``kind``, ``requires``, ``contents`` and ``preview`` of pack.json, discovery per kind, the
requires checks, no programs in a package, ``saengine codepack --kind`` and the schemas."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from saengine.cli.codepack import main as codepack
from saengine.codes import CodePackError, PackManifest, Registry, registry
from saengine.codes import registry as reg_module
from saengine.codes.manifest import version_satisfies
from saengine.codes.registry import PROJECT_PACKS, schema_documents
from saengine.codes.trust import TrustStore

PRESET = {
    "name": "Warren truss 24 m",
    "shape": {"kind": "planeTruss", "span": 24000, "depth": 2400, "panels": 8,
              "memberType": "MEMBER"},
}  # fmt: skip
SPEC = {
    "name": "Dhaka 6-storey",
    "gridsX": [6000, 6000],
    "gridsY": [5000],
    "storyCount": 6,
    "groundHeight": 3500,
    "typicalHeight": 3000,
}
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def write_package(base: Path, pack_id: str, files: dict | None = None, **manifest) -> Path:
    d = base / pack_id
    d.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "saengine.codePack/1", "id": pack_id, "name": pack_id.upper(), **manifest}
    (d / "pack.json").write_text(json.dumps(doc), encoding="utf-8")
    for rel, content in (files or {}).items():
        path = d / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(json.dumps(content), encoding="utf-8")
    return d


def structure(base: Path, pack_id: str = "trusses", **manifest) -> Path:
    files = {"templates/warren.json": PRESET, "preview.png": PNG}
    return write_package(
        base, pack_id, files, kind="structureTemplate", preview="preview.png", **manifest
    )


def zip_folder(folder: Path, dest: Path, extra: dict[str, bytes] | None = None) -> Path:
    with zipfile.ZipFile(dest, "w") as zf:
        for f in folder.rglob("*"):
            if f.is_file():
                zf.write(f, f"{folder.name}/{f.relative_to(folder).as_posix()}")
        for name, data in (extra or {}).items():
            zf.writestr(f"{folder.name}/{name}", data)
    return dest


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(reg_module, "_VALIDATORS", {})
    monkeypatch.setattr(reg_module, "_TABLES_IMPORTED", True)
    monkeypatch.setattr(reg_module, "_GENERATION", [reg_module._GENERATION[0] + 1])
    ns = SimpleNamespace(
        builtin=tmp_path / "builtin",
        user=tmp_path / "user" / "code-packs",
        packages=tmp_path / "user" / "packages",
        project=tmp_path / "project",
        src=tmp_path / "src",
    )
    ns.structures = ns.packages / "structure-templates"
    ns.buildings = ns.packages / "building-templates"
    for d in (ns.builtin, ns.user, ns.project / PROJECT_PACKS, ns.src):
        d.mkdir(parents=True)
    ns.reg = Registry(ns.builtin, ns.user, TrustStore(tmp_path / "trust.json"))
    write_package(ns.builtin, "base", {"data/factors.json": {"phi": {"flexure": 0.9}}})
    return ns


# ---------------------------------------------------------------- manifest


def test_manifest_defaults_to_design_code_and_checks_requires():
    old = PackManifest.model_validate({"schema": "saengine.codePack/1", "id": "x", "name": "X"})
    assert old.kind == "designCode" and old.requires is None
    assert old.content_globs() == ("data/*.json",)
    tpl = PackManifest.model_validate({"id": "t", "name": "T", "kind": "buildingTemplate"})
    assert tpl.content_globs() == ("spec.json", "template.civil")
    ok = {"saengine": ">=0.0.40, <1", "packages": {"bnbc2020": ">=1.0.0"}}
    assert PackManifest.model_validate({"id": "x", "name": "X", "requires": ok}).requires
    for bad in (
        {"saengine": "latest"},
        {"packages": {"BNBC": ">=1"}},
        {"packages": {"bnbc2020": "one"}},
        {"other": 1},
    ):
        with pytest.raises(ValueError):
            PackManifest.model_validate({"id": "x", "name": "X", "requires": bad})
    with pytest.raises(ValueError):
        PackManifest.model_validate({"id": "x", "name": "X", "kind": "plugin"})


@pytest.mark.parametrize(
    "version, spec, expected",
    [
        ("0.0.46", ">=0.0.50", False),
        ("0.0.50", ">=0.0.50", True),
        ("1.0", "==1.0.0", True),
        ("1.0.0", "1.0", True),
        ("1.4.5", "~=1.4.2", True),
        ("1.5.0", "~=1.4.2", False),
        ("1.9", ">=1.0, <2", True),
        ("2.0", ">=1.0, <2", False),
        ("v1.2.0-beta", ">1.1", True),
        ("1.0", "!=1.0.0", False),
        ("draft", ">=1", None),
    ],
)
def test_version_satisfies(version, spec, expected):
    assert version_satisfies(version, spec) is expected


# ---------------------------------------------------------------- discovery per kind


def test_kinds_are_listed_apart(dirs):
    structure(dirs.structures)
    write_package(dirs.buildings, "dhaka-six", {"spec.json": SPEC}, kind="buildingTemplate")
    structure(dirs.builtin, "shapes")  # the built-in folder is shared by every kind

    assert {i.id for i in dirs.reg.list_packs()} == {"base"}  # design codes, as before
    every = dirs.reg.list_packs(kind=None)
    assert [(i.kind, i.id) for i in every] == [
        ("designCode", "base"),
        ("structureTemplate", "shapes"),
        ("structureTemplate", "trusses"),
        ("buildingTemplate", "dhaka-six"),
    ]
    trusses = dirs.reg.info("trusses", kind="structureTemplate")
    assert trusses.usable and trusses.scope == "user" and trusses.problems == []
    assert trusses.contents == ["templates/warren.json"]
    assert trusses.preview == str(dirs.structures / "trusses" / "preview.png")
    assert dirs.reg.info("base").contents == ["data/factors.json"]
    assert dirs.reg.info("dhaka-six", kind="buildingTemplate").usable
    assert dirs.reg.load("shapes", kind="structureTemplate").scope == "builtin"
    with pytest.raises(CodePackError, match="no code pack 'trusses'"):
        dirs.reg.load("trusses")  # not a design code
    with pytest.raises(CodePackError, match="no structure template 'base'"):
        dirs.reg.info("base", kind="structureTemplate")


def test_package_in_the_folder_of_another_kind_is_not_used(dirs):
    structure(dirs.user, "lost")
    info = next(i for i in dirs.reg.list_packs(kind=None) if i.id == "lost")
    assert info.kind == "structureTemplate" and not info.usable
    assert "folder of design codes" in info.problems[0].message


def test_ids_are_one_namespace_across_kinds(dirs):
    write_package(dirs.user, "same")
    structure(dirs.structures, "same")
    infos = [i for i in dirs.reg.list_packs(kind=None) if i.id == "same"]
    assert [(i.kind, i.usable) for i in infos] == [
        ("designCode", True),
        ("structureTemplate", False),
    ]
    assert "another user pack has the id" in infos[1].problems[-1].message


def test_template_files_are_validated_by_their_models(dirs):
    bad_preset = {**PRESET, "shape": {"kind": "planeTruss", "span": -1}}
    write_package(
        dirs.structures,
        "bad",
        {"templates/a.json": bad_preset, "templates/notes.txt": b"x"},
        kind="structureTemplate",
        contents=["templates/*", "missing/*.json"],
        extends="base",
        preview="../outside.png",
    )
    write_package(dirs.structures, "empty", kind="structureTemplate")
    write_package(dirs.buildings, "spec", {"spec.json": {"name": "x"}}, kind="buildingTemplate")
    write_package(
        dirs.buildings, "archive", {"template.civil": b"not a zip"}, kind="buildingTemplate"
    )
    infos = {i.id: i for i in dirs.reg.list_packs(kind=None)}

    messages = [(p.severity, p.file, p.message) for p in infos["bad"].problems]
    assert not infos["bad"].usable
    assert ("error", "pack.json", "extends is for design codes only") in messages
    assert ("warning", "pack.json", "contents: 'missing/*.json' matches no file") in messages
    assert any(f == "templates/a.json" and "shape" in m for _, f, m in messages)
    assert ("error", "templates/notes.txt", "a template file is .json") in messages
    assert any("preview must name an image inside" in m for _, _, m in messages)
    assert "needs at least one template file" in infos["empty"].problems[0].message
    assert any("gridsX" in p.message for p in infos["spec"].problems)
    assert "template archive" in infos["archive"].problems[0].message


# ---------------------------------------------------------------- requires


def test_requires_saengine_version(dirs, monkeypatch):
    monkeypatch.setattr(reg_module, "saengine_version", lambda: "0.0.46")
    src = structure(dirs.src, "future", requires={"saengine": ">=0.0.50"})
    with pytest.raises(CodePackError, match="needs SAEngine >=0.0.50; this is SAEngine 0.0.46"):
        dirs.reg.install(src, "user")
    assert not (dirs.structures / "future").exists()
    structure(dirs.structures, "future", requires={"saengine": ">=0.0.50"})
    info = dirs.reg.info("future", kind="structureTemplate")
    assert not info.usable and "needs SAEngine >=0.0.50" in info.problems[0].message

    monkeypatch.setattr(reg_module, "saengine_version", lambda: "0.0.50")
    dirs.reg.clear_cache()
    assert dirs.reg.info("future", kind="structureTemplate").usable


def test_requires_packages(dirs):
    src = write_package(
        dirs.src,
        "g9",
        {"spec.json": SPEC},
        kind="buildingTemplate",
        requires={"packages": {"bd-coast": ">=1.0", "base": ">=1.0"}},
    )
    info = dirs.reg.install(src, "user")
    assert info.kind == "buildingTemplate" and (dirs.buildings / "g9" / "pack.json").is_file()
    assert not info.usable and info.missingRequires == ["bd-coast"]
    assert "needs the package 'bd-coast' >=1.0, which is not installed" in [
        p.message for p in info.problems
    ]

    write_package(dirs.src, "bd-coast", version="0.9.0", extends="base")
    dirs.reg.install(dirs.src / "bd-coast", "user")
    info = dirs.reg.info("g9", kind="buildingTemplate")
    assert info.missingRequires == ["bd-coast"]
    assert "version 0.9.0 is installed (user)" in info.problems[0].message

    write_package(dirs.src, "bd-coast", version="1.1.0", extends="base")
    dirs.reg.install(dirs.src / "bd-coast", "user", replace=True)
    info = dirs.reg.info("g9", kind="buildingTemplate")
    assert info.usable and info.missingRequires == []


# ---------------------------------------------------------------- install


def test_templates_install_into_their_user_folder_only(dirs):
    src = structure(dirs.src)
    with pytest.raises(CodePackError, match="installed for the user, not into a project"):
        dirs.reg.install(src, "project", dirs.project)
    info = dirs.reg.install(zip_folder(src, dirs.src / "t.zip"), "user")
    assert info.scope == "user" and info.usable
    assert (dirs.structures / "trusses" / "templates" / "warren.json").is_file()
    # a design code still goes to the code packs (user) and the project
    code = write_package(dirs.src, "regional", extends="base")
    assert dirs.reg.install(code, "project", dirs.project).scope == "project"
    assert (dirs.project / PROJECT_PACKS / "regional").is_dir()


def test_uninstall_removes_the_folder_and_the_trust(dirs):
    """Remove on the Packages page (round M3): user and project packages go, built-in stay."""
    src = structure(dirs.src)
    dirs.reg.install(src, "user")
    assert dirs.reg.uninstall("trusses", "user", kind="structureTemplate") == (
        dirs.structures / "trusses"
    )
    assert not (dirs.structures / "trusses").exists()
    assert not any(p.id == "trusses" for p in dirs.reg.list_packs(kind=None))
    with pytest.raises(CodePackError, match="is installed"):
        dirs.reg.uninstall("trusses", "user", kind="structureTemplate")
    with pytest.raises(CodePackError, match="cannot be removed"):
        dirs.reg.uninstall("base", "builtin")

    hooked = write_package(dirs.src, "hooked", {"hooks.py": b""}, extends="base", hooks="hooks.py")
    dirs.reg.install(hooked, "project", dirs.project)
    dirs.reg.set_trusted("hooked", True, dirs.project)
    assert dirs.reg.trust._read().get("hooked")
    dirs.reg.uninstall("hooked", "project", dirs.project)
    assert not (dirs.project / PROJECT_PACKS / "hooked").exists()
    assert not dirs.reg.trust._read().get("hooked")


def test_uninstall_refuses_a_package_others_need(dirs):
    dirs.reg.install(write_package(dirs.src, "regional", extends="base"), "user")
    dirs.reg.install(write_package(dirs.src, "coastal", extends="regional"), "user")
    with pytest.raises(CodePackError, match="needed by coastal"):
        dirs.reg.uninstall("regional", "user")
    # a copy in the project keeps the child resolvable: the user's copy may go
    dirs.reg.install(dirs.src / "regional", "project", dirs.project)
    dirs.reg.uninstall("regional", "user", dirs.project)
    assert not (dirs.user / "regional").exists()


@pytest.mark.parametrize("name", ["setup.exe", "lib/helper.dll", "run.ps1", "tool.BAT", "a.js"])
def test_programs_are_refused(dirs, name):
    src = structure(dirs.src)
    archive = zip_folder(src, dirs.src / "p.zip", {name: b"MZ"})
    with pytest.raises(CodePackError, match="packages may not hold programs"):
        dirs.reg.install(archive, "user")
    (src / name).parent.mkdir(parents=True, exist_ok=True)
    (src / name).write_bytes(b"MZ")
    with pytest.raises(CodePackError, match="packages may not hold programs"):
        dirs.reg.install(src, "user")
    assert not (dirs.structures / "trusses").exists()
    # found on disk anyway (copied by hand): listed as unusable
    structure(dirs.structures)
    (dirs.structures / "trusses" / name).parent.mkdir(parents=True, exist_ok=True)
    (dirs.structures / "trusses" / name).write_bytes(b"MZ")
    info = dirs.reg.info("trusses", kind="structureTemplate")
    assert not info.usable and "may not hold programs" in info.problems[0].message


def test_links_and_large_files_are_refused(dirs, monkeypatch):
    src = structure(dirs.src)
    archive = dirs.src / "link.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(src / "pack.json", "trusses/pack.json")
        link = zipfile.ZipInfo("trusses/templates/link.json")
        link.external_attr = (0o120777 << 16) | 0x20
        zf.writestr(link, "../../secret")
    with pytest.raises(CodePackError, match="is a link"):
        dirs.reg.install(archive, "user")

    from saengine.codes import contents

    monkeypatch.setattr(contents, "MAX_FILE_BYTES", 100)
    with pytest.raises(CodePackError, match="MB at most"):
        dirs.reg.install(zip_folder(src, dirs.src / "big.zip"), "user")
    with pytest.raises(CodePackError, match="MB at most"):
        dirs.reg.install(src, "user")


def test_python_caches_are_ignored_and_hooks_still_allowed(dirs):
    src = structure(dirs.src, hooks="hooks.py")
    (src / "hooks.py").write_text("def local(params):\n    return None\n", encoding="utf-8")
    archive = zip_folder(src, dirs.src / "h.zip", {"__pycache__/hooks.cpython-312.pyc": b"x"})
    info = dirs.reg.install(archive, "user")
    assert info.hooks and info.trusted is False  # installing never trusts
    assert not (dirs.structures / "trusses" / "__pycache__").exists()


# ---------------------------------------------------------------- CLI and schemas


@pytest.fixture
def user_data(tmp_path, monkeypatch):
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user-data"))
    registry.clear_cache()
    yield tmp_path / "user-data"
    registry.clear_cache()


def test_cli_kind(user_data, tmp_path, capsys):
    structure(user_data / "packages" / "structure-templates")
    capsys.readouterr()
    assert codepack(["list", "--json"]) == 0
    ids = [p["id"] for p in json.loads(capsys.readouterr().out)["packs"]]
    assert "trusses" not in ids and "bnbc2020" in ids
    assert codepack(["list", "--kind", "all", "--json"]) == 0
    kinds = {p["id"]: p["kind"] for p in json.loads(capsys.readouterr().out)["packs"]}
    assert kinds["trusses"] == "structureTemplate" and kinds["bnbc2020"] == "designCode"
    assert codepack(["show", "trusses", "--kind", "structureTemplate"]) == 0
    assert "contents: templates/warren.json" in capsys.readouterr().out

    folder = structure(tmp_path / "src")
    assert codepack(["validate", str(folder), "--kind", "structureTemplate"]) == 0
    capsys.readouterr()
    assert codepack(["validate", str(folder), "--kind", "designCode", "--json"]) == 1
    problems = json.loads(capsys.readouterr().out)["problems"]
    assert "the package is a structureTemplate, not a designCode" in [
        p["message"] for p in problems
    ]


def test_cli_package_alias(user_data, capsys):
    from saengine.cli.main import main

    assert main(["package", "list", "--kind", "all", "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["command"] == "codepack list"
    assert any(p["id"] == "bnbc2020" for p in document["packs"])


def test_schemas_cover_every_kind():
    docs = schema_documents()
    manifest = docs["code-pack.schema.json"]
    assert manifest["properties"]["kind"]["default"] == "designCode"
    assert {"requires", "contents", "preview"} <= set(manifest["properties"])
    assert docs["structure-template.schema.json"]["$id"] == "saengine.structureTemplate/1"
    assert "shape" in docs["structure-template.schema.json"]["properties"]
    assert "gridsX" in docs["building-template.schema.json"]["properties"]


def test_builtin_bnbc_is_an_unchanged_design_code(user_data):
    info = registry.info("bnbc2020")
    assert info.kind == "designCode" and info.usable and info.problems == []
    assert info.requires is None and info.missingRequires == []
    assert info.contents and all(c.startswith("data/") for c in info.contents)


def test_builtin_shapes_presets_are_the_generate_panel_defaults(user_data):
    from saengine.codes.contents import structure_preset_model
    from saengine.library.templates import _SHAPES

    info = registry.info("saengine-shapes", kind="structureTemplate")
    assert info.scope == "builtin" and info.usable and info.problems == []
    model = structure_preset_model()
    presets = {
        Path(rel).stem: model.model_validate_json(Path(info.path, rel).read_bytes())
        for rel in info.contents
    }
    defaults = (
        "space-truss", "plane-truss", "arch", "dome", "barrel-vault", "cable-net", "portal-frame"
    )  # fmt: skip
    # One preset per shape at the Generate panel's starting values (change both together).
    assert [presets[name].shape for name in defaults] == list(_SHAPES)
    assert len(presets) > len(defaults)  # and named variants
    assert info.preview and Path(info.preview).stat().st_size < 256 * 1024
    # Design codes are listed apart: the shapes package is not one.
    assert "saengine-shapes" not in {i.id for i in registry.list_packs()}


def test_template_archive_must_be_inputs_only(dirs, tmp_path):
    civil = tmp_path / "template.civil"
    with zipfile.ZipFile(civil, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("project/05 Floor Plan/floor-plan.json", "{}")
        zf.writestr("project/01 Soil Report/soil-report.json", "{}")
        zf.writestr("project/08 FEM/model.results/summary.json", "{}")
    write_package(
        dirs.buildings, "full", {"template.civil": civil.read_bytes()}, kind="buildingTemplate"
    )
    messages = [p.message for p in dirs.reg.info("full", kind="buildingTemplate").problems]
    assert any("soil report" in m and "client data" in m for m in messages)
    assert any("results" in m for m in messages)


def test_template_archive_location_and_author_checks(tmp_path):
    """Round M4: a full template places no site more precisely than a town and names no one but
    its author."""
    from saengine.project.archive import template_problems

    def archive(name: str, files: dict[str, object]) -> Path:
        civil = tmp_path / f"{name}.civil"
        with zipfile.ZipFile(civil, "w") as zf:
            for rel, doc in files.items():
                zf.writestr(f"project/{rel}", json.dumps(doc))
        return civil

    clean = archive(
        "clean",
        {
            "02 Project Settings/settings.json": {"site": {"location": "dhaka"}, "lat": 23.8},
            "11 Drawings/sheet.json": {"drawnBy": "SAEngine contributors"},
        },
    )
    assert template_problems(clean, "SAEngine contributors") == []
    precise = archive("precise", {"06 BIM/site.json": {"refLatitude": 23.81234}})
    assert [p["code"] for p in template_problems(precise)] == ["template-location"]
    plot = archive("plot", {"06 BIM/site.json": {"plot": [[90.4, 23.8], [90.41, 23.8]]}})
    assert [p["code"] for p in template_problems(plot)] == ["template-location"]
    named = archive("named", {"11 Drawings/sheet.json": {"checkedBy": "A. Client Engineer"}})
    problems = template_problems(named, "SAEngine contributors")
    assert [p["code"] for p in problems] == ["template-author"]
    assert "A. Client Engineer" in problems[0]["message"]


def test_catalogue_lists_presets_and_building_templates(dirs):
    from saengine.codes import catalogue

    dirs.reg.install(structure(dirs.src), "user")
    write_package(dirs.src, "g9", {"spec.json": SPEC}, kind="buildingTemplate")
    dirs.reg.install(dirs.src / "g9", "user")
    presets = catalogue.structure_presets(registry=dirs.reg)
    assert [(p["package"], p["name"]) for p in presets["presets"]] == [
        ("trusses", "Warren truss 24 m")
    ]
    assert presets["presets"][0]["shape"]["kind"] == "planeTruss"
    buildings = catalogue.building_templates(registry=dirs.reg)
    assert [(t["package"], t["type"]) for t in buildings["templates"]] == [("g9", "spec")]
    assert buildings["templates"][0]["spec"]["storyCount"] == 6


def test_builtin_default_building_is_the_wizard_start(user_data):
    """The wizard's starting values live in the built-in saengine-default-building package."""
    from saengine.codes import catalogue

    info = registry.info("saengine-default-building", kind="buildingTemplate")
    assert info.scope == "builtin" and info.usable and info.problems == []
    first = catalogue.building_templates()["templates"][0]
    assert first["package"] == catalogue.DEFAULT_BUILDING_TEMPLATE and first["type"] == "spec"
    spec = first["spec"]
    assert (spec["gridsX"], spec["gridsY"], spec["storyCount"]) == ([6000] * 3, [5000] * 2, 6)
    # Grade 500 is not allowed in special frames (BNBC 2020 Part 6 Sec 8.3.3.4(b)).
    assert spec["rebar"] == "B420DWR" and spec["system"] == "rcFrame"


HOOKS = b"""
def portal(params):
    span, height = params["span"], params["height"]
    return {
        "members": [
            {"start": [0, 0, 0], "end": [0, 0, height], "type": "COL"},
            {"start": [0, 0, height], "end": [span, 0, height], "type": "BEAM"},
            {"start": [span, 0, height], "end": [span, 0, 0], "type": "COL"},
        ],
        "supports": [{"at": [0, 0, 0], "fixity": "fixed"}, {"at": [span, 0, 0], "fixity": "fixed"}],
    }
"""
CODED = {
    "name": "Portal frame",
    "generator": "portal",
    "parameters": {
        "type": "object",
        "properties": {
            "span": {"type": "number", "minimum": 1000, "maximum": 60000},
            "height": {"type": "number", "minimum": 1000},
        },
        "required": ["span", "height"],
    },
    "values": {"span": 12000, "height": 6000},
}


def test_coded_template_runs_only_when_trusted(dirs):
    """Round M5: a new shape kind made by the package's own code, through trusted hooks."""
    from saengine.codes import catalogue
    from saengine.codes.coded import coded_geometry

    src = write_package(
        dirs.src,
        "portals",
        {"templates/portal.json": CODED, "hooks.py": HOOKS},
        kind="structureTemplate",
        hooks="hooks.py",
    )
    info = dirs.reg.install(src, "user")
    assert info.usable, info.problems
    listed = catalogue.structure_presets(registry=dirs.reg)["presets"]
    assert [(p["name"], p.get("coded"), p.get("trusted")) for p in listed] == [
        ("Portal frame", True, False)
    ]
    untrusted = coded_geometry("portals", "templates/portal.json", registry=dirs.reg)
    assert untrusted.get("untrusted") and "Packages page" in untrusted["problems"][0]

    dirs.reg.set_trusted("portals", True, kind="structureTemplate")
    geometry = coded_geometry(
        "portals",
        "templates/portal.json",
        {"span": 10000, "origin": {"x": 1000, "y": 0, "z": 0}},
        registry=dirs.reg,
    )
    assert len(geometry["members"]) == 3 and len(geometry["supports"]) == 2
    assert geometry["members"][1]["end"] == [11000.0, 0.0, 6000.0]  # span + origin, height
    bad = coded_geometry("portals", "templates/portal.json", {"span": 10}, registry=dirs.reg)
    assert bad["problems"] == ["span: at least 1000"]


def test_coded_template_needs_hooks(dirs):
    src = write_package(
        dirs.src, "nohooks", {"templates/portal.json": CODED}, kind="structureTemplate"
    )
    messages = [p.message for p in dirs.reg.validate(src).problems]
    assert any("needs the package's hooks" in m for m in messages)
