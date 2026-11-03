"""Track D7: project overrides of any code pack value, switching packs without stale results,
and named generic defaults for single values a pack does not give.

Acceptance (owner update 2026-11-02):
- the default pack's results are unchanged without overrides;
- an override changes only its value; a bad one is refused with its path, never raised;
- the same project run with the default pack, a stub pack and the default pack again gives each
  pack's results, with nothing stale;
- a pack missing a value uses the generic default, named as such;
- a project whose pack is missing opens and runs on the default pack, with a warning.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import generic, overrides, registry

STUB = "stub-d7"


def _stub_pack(folder: Path, tables: dict[str, dict], name: str = "Stub Code 2030") -> Path:
    """A pack that extends the default pack and changes only ``tables``."""
    pack = folder / STUB
    (pack / "data").mkdir(parents=True)
    manifest = {
        "schema": "saengine.codePack/1",
        "id": STUB,
        "name": name,
        "version": "0.1.0",
        "extends": registry.DEFAULT_PACK,
        "covers": list(tables),
    }
    (pack / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    for table, data in tables.items():
        (pack / f"data/{table}.json").write_text(json.dumps(data), encoding="utf-8")
    return pack


def _project(tmp_path: Path, tables: dict[str, dict] | None = None) -> Path:
    root = tmp_path / "D7 project"
    (root / "02 Project Settings").mkdir(parents=True)
    if tables is not None:
        _stub_pack(root / registry.PROJECT_PACKS, tables)
    return root


def _settings(**update):
    from saengine.library.settings import default_project_settings

    return default_project_settings("D7").model_copy(update=update)


def _derive(settings, root: Path | None = None):
    from test_correctness_wiring import _three_bays_two_storeys

    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library

    building, objects = _three_bays_two_storeys()
    with code_context.project(root):
        return derive_fem(building, objects, default_material_library(), settings, {"bim": "x"})


def _patterns(d) -> dict[str, list]:
    return {
        p["name"]: [p.get("nodal_loads"), p.get("element_loads")]
        for p in d.project["load_patterns"]
    }


@pytest.fixture(scope="module")
def default_model():
    return _derive(_settings())


# ─────────────────────────── no change with the default pack ───────────────────────────


def test_default_pack_has_every_value_and_no_overrides(default_model) -> None:
    pack = code_context.default_pack()
    # The default pack gives every value the generic defaults know: nothing is filled.
    assert pack.fallbacks == []
    assert pack.broken == {}
    # No overrides: the very same pack object (every cache keyed on it stays valid).
    assert code_context.pack_for(_settings()) is pack
    assert pack.with_overrides({}) is pack
    # The derived model is the D1 pin (test_decoupling_d1, re-pinned there).
    assert default_model.summary["weight_kN"] == pytest.approx(1349.7034382400013, rel=1e-12)
    assert default_model.summary["base_shear_kN"] == pytest.approx(75.92081840100009, rel=1e-12)


def test_empty_overrides_are_not_written_to_the_settings_file() -> None:
    from saengine.library.settings import ProjectSettings

    settings = _settings()
    assert "codeOverrides" not in json.loads(settings.model_dump_json(by_alias=True))
    text = settings.model_dump_json(by_alias=True)
    data = json.loads(text)
    data["codeOverrides"] = {"factors.phi.shear": 0.7}
    again = ProjectSettings.model_validate(data)
    assert again.codeOverrides == {"factors.phi.shear": 0.7}
    assert json.loads(again.model_dump_json(by_alias=True))["codeOverrides"] == {
        "factors.phi.shear": 0.7
    }


def test_the_plain_concrete_phi_is_the_pack_value() -> None:
    """D6 leftover: ground_slab.PHI_PLAIN is the pack's factors.phi.plain (BNBC 2020 Part 6 Sec
    6.2.3.4 in the default pack), the same 0.60; slab.PHI_TENSION reads factors.phi.tension."""
    from saengine.design import slab
    from saengine.substructure import ground_slab

    pack = code_context.default_pack()
    assert pack.table("factors").phi.plain == 0.6
    assert "6.2.3.4" in pack.table("factors").sources["plain"]
    assert ground_slab.phi_plain() == 0.6
    assert ground_slab.PHI_PLAIN == 0.6
    assert slab.PHI_TENSION == 0.9
    phi_vn, b0 = ground_slab.plain_punching(300.0, 150.0, 25.0)
    assert b0 == 1800.0
    assert phi_vn == pytest.approx(0.6 * 0.22 * 5.0 * 1800.0 * 150.0)


# ─────────────────────────────── overrides ───────────────────────────────


def test_paths_split_and_join() -> None:
    assert overrides.split("factors.phi.shear") == ["factors", "phi", "shear"]
    keys = overrides.split("combinations.strength[1.2D + 1.6L + 0.5Lr].factors.L")
    assert keys == ["combinations", "strength", "1.2D + 1.6L + 0.5Lr", "factors", "L"]
    assert overrides.join(keys) == "combinations.strength[1.2D + 1.6L + 0.5Lr].factors.L"
    assert overrides.split("zoneCoefficients.zones.2") == ["zoneCoefficients", "zones", "2"]
    with pytest.raises(overrides.OverrideError):
        overrides.split("factors..shear")


def test_an_override_changes_only_its_value() -> None:
    from saengine.design import rc

    pack = code_context.pack_for({"codeOverrides": {"factors.phi.shear": 0.7}})
    assert [o.as_dict() for o in pack.overrides] == [
        {"path": "factors.phi.shear", "packValue": 0.75, "value": 0.7}
    ]
    assert pack.override_problems == []
    base = code_context.default_pack()
    with code_context.using(pack):
        values = {k: rc.value(k) for k in rc._VALUES}
    with code_context.using(base):
        before = {k: rc.value(k) for k in rc._VALUES}
    assert values["PHI_SHEAR"] == 0.7 and before["PHI_SHEAR"] == 0.75
    assert {k for k in values if values[k] != before[k]} == {"PHI_SHEAR"}
    # The rest of the table and every other table are the pack's.
    assert pack.data("factors") == {
        **base.data("factors"),
        "phi": {**base.data("factors")["phi"], "shear": 0.7},
    }
    assert all(pack.data(t) == base.data(t) for t in base.tables() if t != "factors")
    assert pack.value_source("factors", "phi.shear") == "project override (BNBC 2020 gives 0.75)"
    assert pack.value_source("factors", "phi.tension") == "code pack BNBC 2020"
    # The same overrides give the same pack object (caches keyed on it stay valid).
    assert code_context.pack_for({"codeOverrides": {"factors.phi.shear": 0.7}}) is pack


def test_an_override_in_the_analysis_changes_only_what_it_drives(default_model) -> None:
    # Zone 2 (Dhaka, the default town) Z 0.20 -> 0.25: only the earthquake cases change.
    settings = _settings(codeOverrides={"zoneCoefficients.zones.2": 0.25})
    model = _derive(settings)
    ours, theirs = _patterns(model), _patterns(default_model)
    assert model.summary["base_shear_kN"] == pytest.approx(
        default_model.summary["base_shear_kN"] * 0.25 / 0.20, rel=1e-9
    )
    assert model.summary["weight_kN"] == default_model.summary["weight_kN"]
    for case in ("D", "SD", "L", "Lr", "WX", "WY"):
        assert ours[case] == theirs[case], case
    for case in ("EX", "EY"):
        assert ours[case] != theirs[case], case


def test_a_list_item_is_overridden_by_its_name() -> None:
    from saengine.library.settings import strength_combinations

    name = "1.2D + 1.6L + 0.5Lr"
    pack = code_context.pack_for(
        {"codeOverrides": {f"combinations.strength[{name}].factors.L": 1.7}}
    )
    assert pack.override_problems == []
    rows = {c.name: c for c in strength_combinations(pack=pack)}
    base = {c.name: c for c in strength_combinations(pack=code_context.default_pack())}
    assert rows[name].L == 1.7 and base[name].L == 1.6
    assert [n for n in rows if rows[n] != base[n]] == [name]


def test_bad_overrides_are_refused_with_their_path_never_raised(default_model) -> None:
    from saengine.library.settings import ProjectSettings, problems

    bad = {
        "factors.phi.tension": 1.5,  # the model refuses φ > 1
        "factors.phi.joint": "high",  # not a number
        "factors.phi.nonsense": 0.5,  # no such value
        "noTable.x": 1,  # no such table
        "factors": 0.5,  # a whole table
        "seismic.liveShare": 0.3,  # good: applied
    }
    settings = ProjectSettings.model_validate(
        {**json.loads(_settings().model_dump_json(by_alias=True)), "codeOverrides": bad}
    )
    pack = code_context.pack_for(settings)
    refused = dict(pack.override_problems)
    assert set(refused) == set(bad) - {"seismic.liveShare"}
    # SL-3: the value and its allowed range, not the validator's words.
    assert refused["factors.phi.tension"] == "1.5 is out of range: it must be at most 1"
    assert "number" in refused["factors.phi.joint"]
    assert [o.path for o in pack.overrides] == ["seismic.liveShare"]
    assert pack.table("factors").phi.tension == 0.9  # the pack's value is kept
    found = dict(problems(settings))
    for path in refused:
        assert f"codeOverrides.{path}" in found
    # The run goes on with the good override and the pack's other values.
    model = _derive(settings)
    assert model.summary["wind_X_kN"] == default_model.summary["wind_X_kN"]


def test_the_report_lists_the_overridden_values() -> None:
    from saengine.report import document
    from saengine.report.build import _basis, _Parts, code_pack_text

    settings = _settings(codeOverrides={"factors.phi.shear": 0.7})
    warnings: list[str] = []
    basis = _basis(settings, _Parts(Path("."), warnings), {}, {})
    # R1-16 of re-walk 1: by its name in words and clause, the path after it.
    [[name, pack_value, value]] = basis["codeOverrides"]
    assert name.startswith("Factors › Phi › Shear") and name.endswith("(factors.phi.shear)")
    assert (pack_value, value) == ("0.75", "0.7")
    assert basis["genericDefaults"] == []
    assert code_pack_text(settings).endswith("; 1 value overridden in this project")
    built = document._basis(
        {"basis": {**basis, "materials": [], "cases": []}},
        document.Context(document.default_report_template(), "full", []),
    )
    titles = [b.get("text") for b in built["blocks"] if b.get("t") == "h"]
    assert "Code values overridden in this project" in titles
    rows = next(
        b for b in built["blocks"] if b.get("head") == ["Value", "Code pack", "This project"]
    )
    [[name, pack_value, value]] = rows["rows"]  # R1-16: the name in words, then the path
    assert name.endswith("(factors.phi.shear)") and (pack_value, value) == ("0.75", "0.7")


def test_the_code_values_page_lists_and_marks_values() -> None:
    from saengine.rpc.handlers import codes_values

    text = json.dumps({"codeOverrides": {"factors.phi.shear": 0.7, "factors.phi.joint": 2}})
    answer = codes_values(text, None, "factors")
    assert answer["id"] == registry.DEFAULT_PACK and answer["missing"] is None
    tables = [{k: t[k] for k in ("name", "overridden", "generic")} for t in answer["tables"]]
    assert {"name": "factors", "overridden": True, "generic": False} in tables
    # With their words whatever table is shown (R1-16 of re-walk 1).
    [override] = answer["overrides"]
    assert {k: override[k] for k in ("path", "packValue", "value")} == {
        "path": "factors.phi.shear", "packValue": 0.75, "value": 0.7,
    }  # fmt: skip
    assert override["title"] == "Factors › Phi › Shear" and override["label"] == "Shear"
    assert [p["path"] for p in answer["problems"]] == ["factors.phi.joint"]
    rows = {r["path"]: r for r in answer["rows"]}
    assert rows["factors.phi.shear"]["overridden"] and rows["factors.phi.shear"]["value"] == 0.7
    assert rows["factors.phi.shear"]["packValue"] == 0.75
    assert not rows["factors.phi.tension"]["overridden"]
    assert "factors.source" not in rows and "factors.sources.plain" not in rows


# ─────────────────────────────── switching ───────────────────────────────


def test_switching_packs_and_back_leaves_nothing_stale(tmp_path, default_model) -> None:
    root = _project(tmp_path, {"zoneCoefficients": {"zones": {"2": 0.3}}})
    first = _derive(_settings(), root)
    stub = _derive(_settings(codePack=STUB), root)
    again = _derive(_settings(), root)
    overridden = _derive(
        _settings(codePack=STUB, codeOverrides={"zoneCoefficients.zones.2": 0.25}), root
    )
    back = _derive(_settings(codePack=STUB), root)

    shear = default_model.summary["base_shear_kN"]
    assert first.summary == default_model.summary
    assert stub.summary["base_shear_kN"] == pytest.approx(shear * 0.30 / 0.20, rel=1e-9)
    assert again.summary == first.summary and _patterns(again) == _patterns(first)
    assert overridden.summary["base_shear_kN"] == pytest.approx(shear * 0.25 / 0.20, rel=1e-9)
    assert back.summary == stub.summary and _patterns(back) == _patterns(stub)


def test_the_pack_fingerprint_follows_the_pack_and_the_overrides(tmp_path) -> None:
    from saengine.pipeline.design_mode import _pack_fingerprint

    root = _project(tmp_path, {"zoneCoefficients": {"zones": {"2": 0.3}}})
    a = _pack_fingerprint(json.dumps({}), root)
    b = _pack_fingerprint(json.dumps({"codePack": STUB}), root)
    c = _pack_fingerprint(
        json.dumps({"codePack": STUB, "codeOverrides": {"factors.phi.shear": 0.7}}), root
    )
    assert len({a, b, c}) == 3
    assert _pack_fingerprint(json.dumps({}), root) == a
    # The stub pack edited on disk (its version raised): a new fingerprint, so kept design
    # checks made from its old values are stale.
    manifest = root / registry.PROJECT_PACKS / STUB / "pack.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["version"] = "0.2.0"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert _pack_fingerprint(json.dumps({"codePack": STUB}), root) != b


# ─────────────────────────────── generic defaults ───────────────────────────────


def test_a_pack_missing_a_value_uses_the_named_generic_default(tmp_path) -> None:
    from saengine.report.build import _basis, _Parts
    from saengine.substructure import ground_slab

    root = _project(
        tmp_path,
        {
            "factors": {"phi": {"$remove": ["plain"]}},
            "combinations": {"$remove": ["pDeltaPreload"]},
        },
    )
    settings = _settings(codePack=STUB)
    with code_context.project(root):
        pack = code_context.pack_for(settings, root)
        with code_context.using(pack):
            phi = ground_slab.phi_plain()
            from saengine.fem import second_order

            preload = second_order.pdelta_factors()
        basis = _basis(settings, _Parts(root, []), {}, {})
    assert phi == 0.6
    assert preload == {"D": 1.2, "SD": 1.2, "F": 1.2, "L": 1.0}
    assert sorted(f.path for f in pack.fallbacks) == [
        "combinations.pDeltaPreload",
        "factors.phi.plain",
    ]
    fallback = pack.fallback("factors", "phi.plain")
    assert fallback is not None and fallback.note.startswith("ACI 318-19 Table 21.2.1")
    assert pack.value_source("factors", "phi.plain") == (
        "generic default (SAEngine practice), not given by Stub Code 2030"
    )
    assert [row[0] for row in basis["genericDefaults"]] == [
        "combinations.pDeltaPreload",
        "factors.phi.plain",
    ]
    # No generic default cites the default pack's code as its source.
    for table in generic.tables():
        for key in [""]:
            assert "BNBC" not in generic.note(table, key)
    assert all("BNBC" not in json.dumps(generic.data(t)) for t in generic.tables())


def test_generic_defaults_never_add_a_whole_table(tmp_path) -> None:
    """A pack without a table does not cover that feature: the generic defaults fill single
    values of the tables a pack has, never a table it lacks."""
    root = _project(tmp_path, {"flood": {"$replace": True, "$data": {}}})
    pack = registry.load(STUB, root)
    assert "flood" in pack.tables()
    assert pack.fallback("flood", "waveCombination") is None or pack.broken.get("flood")
    for table in generic.tables():
        assert table in code_context.default_pack().tables()


def test_a_value_the_pack_does_not_give_inside_a_group_is_filled(tmp_path) -> None:
    from saengine.fem import flood

    root = _project(tmp_path, {"flood": {"$remove": ["waveCombination"]}})
    with code_context.project(root):
        pack = code_context.pack_for({"codePack": STUB}, root)
        with code_context.using(pack):
            method, source = flood.wave_combination(None)
    assert method == "sum"
    assert source == "generic default (SAEngine practice), not given by Stub Code 2030"


# ─────────────────────────────── a missing pack ───────────────────────────────


def test_a_project_whose_pack_is_missing_opens_on_the_default_pack(default_model) -> None:
    from saengine.library.settings import ProjectSettings, problems

    data = json.loads(_settings().model_dump_json(by_alias=True))
    data["codePack"] = "gone-pack"
    settings = ProjectSettings.model_validate(data)  # no error on reading
    pack = code_context.pack_for(settings)
    assert pack.id == registry.DEFAULT_PACK and pack.missing == "gone-pack"
    assert "gone-pack" in pack.warnings[0].message and "default pack" in pack.warnings[0].message
    assert dict(problems(settings))["codePack"] == pack.warnings[0].message
    model = _derive(settings)  # and runs, on the default pack's values
    assert model.summary == default_model.summary
    with pytest.raises(registry.CodePackError):
        code_context.pack_for(settings, strict=True)


def test_code_values_page_reads_like_a_code() -> None:
    """SL-1 / SL-3 (walkthrough 3): the Code Values page's answer lists the structural tables
    first by section, each value with words, unit and clause; a refused override names the
    value's range and carries the pack's value that applies; prose notes are not values."""
    from saengine.rpc import handlers

    text = json.dumps({"codeOverrides": {"factors.phi.tension": 1.2}})
    answer = handlers.codes_values(text, None, "factors")
    assert answer["tables"][0]["name"] == "factors"
    assert answer["tables"][0]["section"] == "Concrete and steel design"
    sections = [t["section"] for t in answer["tables"]]
    assert sections.index("Fire, services and planning") > sections.index(
        "Loads, combinations and analysis"
    )
    [refused] = answer["problems"]
    assert refused["message"] == "1.2 is out of range: it must be at most 1"
    assert refused["packValue"] == 0.9
    row = next(r for r in answer["rows"] if r["path"] == "factors.phi.compressionTied")
    assert (row["label"], row["description"], row["group"]) == (
        "Compression tied",
        "Compression-controlled, tied.",
        "Phi",
    )
    assert row["clause"]  # the pack's reference of the table
    detailing = handlers.codes_values(text, None, "detailing")["rows"]
    assert any(r["unit"] == "mm" for r in detailing)
    access = handlers.codes_values(text, None, "accessibility")["rows"]
    assert not [r for r in access if ".notes" in r["path"] or r["path"].endswith(".text")]
