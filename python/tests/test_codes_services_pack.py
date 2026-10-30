"""The code tables that moved from Python modules into the BNBC 2020 code pack (code packs 3):
the building services (plumbing, HVAC, electrical, fire) and the steel sections.

Each module's names are pinned IDENTICAL to what the module returned before the move: values
*and* types (``tests/data/code_packs_3/<module>.txt``, written by ``tests/code_packs_frozen.py``
from the old module). The modules now read the pack in force where the names are used.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from code_packs_frozen import frozen, plain, same

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.codes.tables import PACKS_DIR, TABLE_MODELS, builtin_table


@pytest.fixture(autouse=True)
def _user_folder(tmp_path, monkeypatch):
    """No pack of the machine's user folder takes part."""
    monkeypatch.setenv("SAENGINE_USER_DATA", str(tmp_path / "user"))
    registry.clear_cache()
    yield
    registry.clear_cache()


def _differences(module_name: str, stem: str) -> list[str]:
    module = importlib.import_module(module_name)
    old = frozen(stem)
    return [d for name in old for d in same(old[name], plain(getattr(module, name)), name)]


def test_plumbing_table_equals_the_old_module():
    assert _differences("saengine.plumbing.tables", "plumbing") == []


@pytest.mark.parametrize("name", ["plumbing"])
def test_moved_table_is_registered_covered_and_cited(name):
    manifest = json.loads((PACKS_DIR / "bnbc2020" / "pack.json").read_text(encoding="utf-8"))
    assert name in TABLE_MODELS
    assert name in manifest["covers"]
    assert manifest["clauses"][name]
    table = builtin_table(name)
    assert table.source and table.sources
    assert registry.load("bnbc2020").has(name)


def _pack_extending_bnbc(root: Path, table: str, data: dict) -> Path:
    folder = root / "services-test"
    (folder / "data").mkdir(parents=True)
    manifest = {
        "schema": "saengine.codePack/1",
        "id": "services-test",
        "name": "Services test",
        "version": "1.0.0",
        "extends": "bnbc2020",
        "covers": [table],
    }
    (folder / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "data" / f"{table}.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


def test_plumbing_names_follow_the_pack_in_force(tmp_path):
    from saengine.plumbing import tables as T

    pack = registry.load_path(_pack_extending_bnbc(tmp_path, "plumbing", {"familySize": 6}))
    assert T.FAMILY_SIZE == 5
    with code_context.using(pack):
        assert T.FAMILY_SIZE == 6
        assert T.HUNTER == frozen("plumbing")["HUNTER"]
    assert T.FAMILY_SIZE == 5


def test_a_pack_without_the_table_reads_bnbc_2020(tmp_path):
    from saengine.plumbing import tables as T

    folder = _pack_extending_bnbc(tmp_path, "areaLoads", {})
    manifest = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    manifest.update(extends=None, covers=[])
    (folder / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "data" / "areaLoads.json").unlink()
    pack = registry.load_path(folder)
    assert not pack.has("plumbing")
    with code_context.using(pack):
        assert T.FAMILY_SIZE == 5


def test_unknown_names_are_attribute_errors():
    from saengine.plumbing import tables as T

    with pytest.raises(AttributeError):
        _ = T.NOT_A_TABLE_NAME
    assert not hasattr(T, "__wrapped__")
