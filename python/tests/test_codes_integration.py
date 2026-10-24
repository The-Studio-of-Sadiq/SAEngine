"""Code packs wired through the program: the project's settings choose the pack (``codePack``),
the loads follow it, and everything else stays as with BNBC 2020.

The end-to-end check derives the Sample Frame at Chattogram twice: with the built-in BNBC 2020
pack and with the example pack (``tests/data/codepacks/example-region``, installed into the
project's own packs), which changes Chattogram's basic wind speed from 80 to 82 m/s. The wind
cases change by (82/80)²; every other load case is identical.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "workbench/resources/saengine/samples/Sample Frame"
EXAMPLE = Path(__file__).parent / "data/codepacks/example-region"
SETTINGS = "02 Project Settings/project-settings.json"


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    """No pack of the machine's user folder takes part."""
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def _project(tmp_path: Path, name: str, pack: str | None) -> Path:
    root = tmp_path / name / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    settings = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    settings["site"]["location"] = "chattogram"
    if pack is not None:
        settings["codePack"] = pack
    (root / SETTINGS).write_text(json.dumps(settings, indent="\t"), encoding="utf-8")
    if pack == "example-region":
        shutil.copytree(EXAMPLE, root / registry.PROJECT_PACKS / "example-region")
    return root


def _patterns(root: Path) -> dict[str, list]:
    from saengine.pipeline.run_all import run_all

    result = run_all(root, steps=["derive"])
    assert [s.status for s in result.steps] == ["ok"], [s.message for s in result.steps]
    model = json.loads((root / "08 FEM/model.osmodel").read_text(encoding="utf-8"))
    return {
        p["name"]: [p.get("nodal_loads"), p.get("element_loads")] for p in model["load_patterns"]
    }


def _numbers(value) -> list[float]:
    if isinstance(value, list):
        return [x for v in value for x in _numbers(v)]
    if isinstance(value, dict):
        return [x for k, v in value.items() if not k.endswith("id") for x in _numbers(v)]
    return [float(value)] if isinstance(value, int | float) else []


def test_example_pack_changes_the_wind_only(tmp_path):
    bnbc = _patterns(_project(tmp_path, "a", None))
    example = _patterns(_project(tmp_path, "b", "example-region"))
    assert bnbc.keys() == example.keys()
    wind = [name for name in bnbc if name.startswith("W")]
    assert wind, list(bnbc)
    for name in bnbc:
        if name in wind:
            assert example[name] != bnbc[name]
            factor = (82 / 80) ** 2
            expected = [x * factor for x in _numbers(bnbc[name])]
            assert _numbers(example[name]) == pytest.approx(
                expected, rel=1e-4, abs=2e-3
            )  # stored to 0.001
        else:
            assert example[name] == bnbc[name], name


def test_explicit_bnbc_pack_gives_identical_loads(tmp_path):
    assert _patterns(_project(tmp_path, "a", None)) == _patterns(
        _project(tmp_path, "b", "bnbc2020")
    )


def test_settings_follow_the_project_pack(tmp_path):
    from saengine.library.settings import (
        ProjectSettings,
        check,
        default_project_settings,
        derived,
        strength_combinations,
    )

    root = _project(tmp_path, "b", "example-region")
    settings = ProjectSettings.model_validate_json((root / SETTINGS).read_text(encoding="utf-8"))
    assert settings.codePack == "example-region"
    # Without the project, its own pack is not found: the validator reports it.
    assert any(p.startswith("codePack:") for p in check(settings))
    with code_context.project(root):
        assert derived(settings)["windSpeed"] == 82.0
        assert not any(p.startswith("codePack:") for p in check(settings))
        names = [c.name for c in strength_combinations(pack=code_context.pack_for(settings))]
    assert "1.2D + 1.0EX + 0.5L" in names and "1.2D + 1.0EX + 1.0L" not in names
    # Old settings (no codePack) keep BNBC 2020.
    old = default_project_settings().model_dump(by_alias=True)
    old.pop("codePack")
    assert ProjectSettings.model_validate(old).codePack == "bnbc2020"
    assert "1.2D + 1.0EX + 1.0L" in [c.name for c in strength_combinations()]


def test_validator_reports_a_missing_pack(tmp_path):
    from saengine.pipeline.project import open_project
    from saengine.pipeline.validate import validate_part

    root = _project(tmp_path, "a", "no-such-pack")
    result = validate_part(open_project(root), "settings")
    assert any("no-such-pack" in p["message"] for p in result.problems)


def test_report_states_the_pack(tmp_path):
    from saengine.library.settings import ProjectSettings
    from saengine.report.build import code_pack_text

    root = _project(tmp_path, "b", "example-region")
    settings = ProjectSettings.model_validate_json((root / SETTINGS).read_text(encoding="utf-8"))
    with code_context.project(root):
        text = code_pack_text(settings)
    assert text.startswith("BNBC 2020 (bnbc2020), modified by: Example region")
    assert "(example-region)" in text
    assert code_pack_text(
        ProjectSettings.model_validate(
            {**settings.model_dump(by_alias=True), "codePack": "bnbc2020"}
        )
    ) == ("BNBC 2020 (bnbc2020), pack version 1.0.0")


def test_civil_archive_carries_the_project_packs(tmp_path):
    from saengine.project.archive import export_project

    root = _project(tmp_path, "b", "example-region")
    out = tmp_path / "sample.civil"
    export_project(root, out)
    with zipfile.ZipFile(out) as archive:
        names = archive.namelist()
    assert any(n.endswith("code-packs/example-region/pack.json") for n in names), names[:20]
    assert any(n.endswith("code-packs/example-region/data/locations.json") for n in names)


def test_rpc_code_pack_methods(tmp_path):
    from saengine.rpc import handlers

    root = _project(tmp_path, "b", "example-region")
    packs = handlers.codes_list(str(root))
    assert {(p["id"], p["scope"]) for p in packs} == {
        ("bnbc2020", "builtin"),
        ("example-region", "project"),
    }
    shown = handlers.codes_show("example-region", str(root))
    assert shown["extends"] == "bnbc2020" and shown["licence"] == "AGPL-3.0-only"
    made = handlers.codes_new("my-code", "My code", "example-region", "project", root=str(root))
    assert Path(made["path"]).parent == root / registry.PROJECT_PACKS
    assert handlers.codes_validate(made["path"], str(root))["usable"] is True
    assert handlers.codes_show("unknown", str(root))["ok"] is False


def test_validating_a_pack_folder_does_not_shadow_it(tmp_path):
    """Validating an installed pack reads its folder as scope "folder": the pack must still be
    the one in force when listed afterwards (it was shown as shadowed by itself)."""
    root = _project(tmp_path, "b", "example-region")
    folder = root / registry.PROJECT_PACKS / "example-region"
    assert registry.list_packs(root)[-1].effective
    assert registry.validate(folder, root).usable
    infos = {i.id: i for i in registry.list_packs(root)}
    assert infos["example-region"].effective and infos["example-region"].shadowedBy is None
    assert not infos["example-region"].problems


def _gust_pack(folder: Path, pack_id: str, gust: float, extends: str | None = "bnbc2020") -> Path:
    """A pack ``pack_id`` in ``folder`` that changes only the wind gust factor G."""
    pack = folder / pack_id
    (pack / "data").mkdir(parents=True)
    manifest = {
        "schema": "saengine.codePack/1",
        "id": pack_id,
        "name": f"Gust {gust}",
        "version": "0.1.0",
        "extends": extends,
        "covers": ["wind"],
    }
    (pack / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pack / "data/wind.json").write_text(json.dumps({"gust": gust}), encoding="utf-8")
    return pack


def test_soil_and_generator_requests_find_the_project_pack(tmp_path):
    """soil/report, soil/sources and bim/generate run with the project's own pack when the
    request carries ``projectRoot`` (the workbench sends it), as every RPC request does."""
    from saengine.rpc import handlers
    from saengine.rpc.server import _scoped

    root = _project(tmp_path, "b", "example-region")
    settings_text = (root / SETTINGS).read_text(encoding="utf-8")
    soil_text = (root / "01 Soil Report/soil-report.json").read_text(encoding="utf-8")
    report = _scoped(lambda p: handlers.soil_report(p["soilText"], p["settingsText"]))(
        {"soilText": soil_text, "settingsText": settings_text, "projectRoot": str(root)}
    )
    assert not report.get("problems"), report.get("problems")
    sources = _scoped(lambda p: handlers.soil_sources(p["soilText"], p["settingsText"]))(
        {"soilText": soil_text, "settingsText": settings_text, "projectRoot": str(root)}
    )
    assert not sources.get("problems"), sources.get("problems")
    # Without the project the project-local pack cannot be found (and is not replaced silently).
    with pytest.raises(registry.CodePackError):
        code_context.pack_for(json.loads(settings_text))


def test_default_pack_follows_installs(tmp_path):
    """The default pack used without a project (generator, fem.loads outside a derivation)
    is the one the registry gives now, not one remembered from before an install."""
    assert code_context.current().scope == "builtin"
    gust = code_context.current().table("wind").gust
    source = _gust_pack(tmp_path / "src", "bnbc2020", 0.9, extends=None)
    # A whole copy of the built-in pack with a different G (extends nothing: copy its tables).
    for table in (registry.BUILTIN_DIR / "bnbc2020/data").glob("*.json"):
        if table.name != "wind.json":
            shutil.copy(table, source / "data" / table.name)
    data = json.loads((registry.BUILTIN_DIR / "bnbc2020/data/wind.json").read_text("utf-8"))
    data["gust"] = 0.9
    (source / "data/wind.json").write_text(json.dumps(data), encoding="utf-8")
    manifest = json.loads((registry.BUILTIN_DIR / "bnbc2020/pack.json").read_text("utf-8"))
    (source / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    registry.install(source, "user")
    assert registry.active({}).scope == "user"
    assert code_context.current().scope == "user"
    assert code_context.current().table("wind").gust == 0.9 != gust
    assert code_context.pack_for({}).scope == "user"


def test_generator_reads_the_coefficients_of_the_project_pack(tmp_path, monkeypatch):
    """The generator's lateral sizing reads fem.loads' wind tables from the pack the settings
    choose (with the project's own packs), not from the built-in default."""
    from saengine.fem import loads as fl
    from saengine.library import generator

    root = _project(tmp_path, "g", None)
    _gust_pack(root / registry.PROJECT_PACKS, "gusty", 0.95)
    settings = json.loads((root / SETTINGS).read_text(encoding="utf-8"))
    settings["codePack"] = "gusty"
    seen: list[float] = []
    original = fl.wind_level_forces

    def spy(*args, **kwargs):
        seen.append(code_context.table("wind").gust)
        return original(*args, **kwargs)

    monkeypatch.setattr(fl, "wind_level_forces", spy)
    spec = {
        "name": "Two storeys",
        "gridsX": [6000, 6000],
        "gridsY": [5000],
        "storyCount": 2,
        "groundHeight": 3500,
        "typicalHeight": 3000,
        "lateralSizing": "auto",
    }
    with code_context.project(root):
        generator.generate_building(spec, settings)
    assert seen and set(seen) == {0.95}
