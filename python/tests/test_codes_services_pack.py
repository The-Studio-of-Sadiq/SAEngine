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
    old = {k: v for k, v in frozen(stem).items() if "(" not in k}  # calls: their own tests
    return [d for name in old for d in same(old[name], plain(getattr(module, name)), name)]


def test_plumbing_table_equals_the_old_module():
    assert _differences("saengine.plumbing.tables", "plumbing") == []


def test_hvac_table_equals_the_old_module():
    assert _differences("saengine.hvac.tables", "hvac") == []


def test_hvac_functions_read_the_table():
    from saengine.hvac import tables as T

    assert [T.default_wwr(d) for d in (0.0, 7.99, 8.0, 14.0, 14.01)] == [0.2, 0.2, 0.3, 0.3, 0.35]
    assert [T.shgc_limit(r) for r in (0.0, 0.1, 0.15, 0.9, 1.0)] == [0.85, 0.85, 0.6, 0.27, 0.27]
    station, notes = T.station_for(None, "nowhere")
    assert station.key == "dhaka" and notes[0].startswith("site location 'nowhere'")


def test_electrical_table_equals_the_old_module():
    assert _differences("saengine.electrical.tables", "electrical") == []


def test_electrical_functions_read_the_table():
    from saengine.electrical import tables as T

    assert [T.height_index(h) for h in (9.0, 9.5, 53.0, 54.0)] == [2, 4, 30, None]
    assert [T.thunder_index(d) for d in (3, 21, 40)] == [2, 20, 21]
    assert [T.cable_od(a) for a in (10, 33, 1000)] == [17.0, 19.0, 68.0]
    assert T.cite("1.3.18.7", "(g)") == "BNBC 2020 Part 8 Sec 1.3.18.7(g) (p800)"


def test_fire_table_equals_the_old_module():
    assert _differences("saengine.fire.tables", "fire") == []


def test_fire_flows_have_one_home():
    """Table 4.4.1 is the fire table's: Part 8's storage reads the same values through the
    plumbing module's old names."""
    from saengine.fire import tables as F
    from saengine.plumbing import tables as P

    assert P.FIRE_FLOWS == F.FIRE_FLOWS and P.FIRE_HAZARD == F.FIRE_HAZARD
    assert P.FIRE_RISER_AREA == F.RISER_AREA and P.HAZARD_ORDER == F.HAZARD_ORDER
    assert [F.hazard_of(g) for g in ("A3", "B1", "J2", "Z")] == ["lightI", "lightII", "extra", None]
    assert P.fire_hazard("J2") == "ordinaryIII"
    assert [F.duration("lightI", h) for h in (51.0, 51.5, 102.5)] == [30, 38, 45]


def test_steel_sections_equal_the_old_module():
    assert _differences("saengine.library.steel_sections", "steel_sections") == []


def test_steel_section_table_and_its_json_equal_the_old_ones():
    from saengine.library import steel_sections as S

    old = frozen("steel_sections")
    assert same(old["section_table()"], plain(list(S.section_table()))) == []
    assert same(old["table_json()"], plain(S.table_json())) == []


def test_steel_sections_follow_the_pack_in_force(tmp_path):
    from saengine.library import steel_sections as S

    data = json.loads((PACKS_DIR / "bnbc2020/data/steelSections.json").read_text(encoding="utf-8"))
    ipe = data["rolled"]["IPE"]
    pack = registry.load_path(
        _pack_extending_bnbc(tmp_path, "steelSections", {"rolled": {"IPE": ipe}, "density": 7800})
    )
    base = S.find("IPE 300")
    with code_context.using(pack):
        mine = S.find("IPE 300")
        assert mine.A == base.A and mine.mass == pytest.approx(base.mass * 7800 / 7850)
    assert S.find("IPE 300") == base


@pytest.mark.parametrize("name", ["plumbing", "hvac", "electrical", "fire", "steelSections"])
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


def test_rebar_sets_equal_the_old_module_constants():
    """The bar sizes the tanks and 9 Substructure chose from (plumbing/tanks.py BAR_DIAS,
    substructure/run.py and sizing.py BAR_DIAS before code packs 3) are sets of the pack's
    ``concrete.barDiameters``."""
    from saengine.design.bars import diameters
    from saengine.substructure.run import bar_dias

    assert same((10.0, 12.0, 16.0, 20.0, 25.0), diameters("tank")) == []
    assert same((12, 16, 20, 25), bar_dias()) == []
    assert same((12.0, 16.0, 20.0, 25.0), tuple(float(d) for d in diameters("foundation"))) == []


def test_fire_hazard_labels_have_one_home():
    """The MEP schema's hazard choices are the fire table's labels (``library/mep.py`` kept its
    own copy before code packs 3)."""
    from saengine.fire import tables as F
    from saengine.library import mep

    assert mep.FIRE_HAZARDS == F.HAZARD_LABELS
    assert list(mep.FIRE_HAZARDS) == ["lightI", "lightII", "ordinaryI", "ordinaryII"] + [
        "ordinaryIII",
        "extra",
    ]
