"""The partition allowance in the seismic weight W (owner decision 2026-11-03).

BNBC 2020 Part 6 Sec 2.5.7.3 defines W as the dead load "including partition walls"; the
25 %/50 % live share of (a)/(b) is judged on the floor live load without the partition
allowance and applies to that live load only. The default pack says ``seismic.partitionWeight``
"full"; a project may choose "withLiveShare" (the earlier behaviour) or a factor of its own,
directly (``analysis.massSource.partitions``) or through ``codeOverrides``; a pack without the
value uses the generic default (full), named as such.

The model: two storeys of three 5 m x 5 m bays (75 m² of floor below the roof), the default
floor load FL: live 2.0 + partitions 1.2 kN/m² (in L, the pack's), finish 1.2 kN/m².
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.library.settings import (
    default_project_settings,
    partition_weight_basis,
    seismic_weight_rule,
)

A = 75.0  # m² of floor (level L1) under the floor load FL
LIVE, PARTITIONS = 2.0, 1.2  # kN/m²
STUB = "stub-partitions"


def _settings(partitions: str = "pack", share: float | None = None, **update):
    s = default_project_settings("W").model_copy(update=update, deep=True)
    s.analysis.massSource.partitions = partitions  # type: ignore[assignment]
    s.analysis.massSource.partitionShare = share
    return s


def _derive(settings, root: Path | None = None):
    from test_correctness_wiring import _three_bays_two_storeys

    from saengine.fem.derive import derive_fem
    from saengine.library import default_material_library

    building, objects = _three_bays_two_storeys()
    with code_context.project(root):
        return derive_fem(building, objects, default_material_library(), settings, {"bim": "x"})


def _level1(d) -> dict[str, float]:
    return d.summary["seismicWeight"]["levels"][0]["parts_kN"]


@pytest.fixture(scope="module")
def models():
    return {
        "pack": _derive(_settings()),
        "withLiveShare": _derive(_settings("withLiveShare")),
        "factor": _derive(_settings("factor", 0.5)),
    }


# ─────────────────────────────── the rule ───────────────────────────────


def test_the_rule_by_hand() -> None:
    rule = seismic_weight_rule(_settings())
    assert rule.partitions.mode == "full" and rule.partitions.case == "L"
    # In full: 1.2 + 0.25 x 2.0 (the threshold judged on 2.0, not 3.2).
    assert rule.area(LIVE, PARTITIONS) == (0.25, 1.0)
    assert rule.weight(LIVE, PARTITIONS) == pytest.approx(1.2 + 0.5)
    # With the live share (the earlier rule): 3.2 > 3 kN/m², so 50 % of both.
    old = seismic_weight_rule(_settings("withLiveShare"))
    assert old.area(LIVE, PARTITIONS) == (0.5, 0.5)
    assert old.weight(LIVE, PARTITIONS) == pytest.approx(0.5 * 3.2)
    # A factor of the project's: 0.5 x 1.2 + 0.25 x 2.0.
    own = seismic_weight_rule(_settings("factor", 0.5))
    assert own.area(LIVE, PARTITIONS) == (0.25, 0.5)
    # "factor" without a factor: the pack's.
    assert partition_weight_basis(_settings("factor")).mode == "full"
    # The pack's clause is named.
    source = rule.partitions.source
    assert source.startswith("code pack BNBC 2020") and "Sec 2.5.7.3" in source


# ─────────────────────────────── the analysis ───────────────────────────────


def test_full_partitions_in_w_by_hand(models) -> None:
    """W adds 1.2·A + 0.25·2.0·A, against the old 0.5·3.2·A."""
    full, old = models["pack"], models["withLiveShare"]
    assert _level1(full)["partitions"] == pytest.approx(PARTITIONS * A, abs=1e-3)
    assert _level1(full)["L"] == pytest.approx(0.25 * LIVE * A, abs=1e-3)
    assert _level1(old)["L"] == pytest.approx(0.5 * (LIVE + PARTITIONS) * A, abs=1e-3)
    assert "partitions" not in _level1(old)
    gain = (PARTITIONS + 0.25 * LIVE - 0.5 * (LIVE + PARTITIONS)) * A  # 7.5 kN
    assert full.summary["weight_kN"] - old.summary["weight_kN"] == pytest.approx(gain, abs=1e-6)
    # The earlier rule gives the earlier pin exactly (test_decoupling_d1 before 2026-11-03).
    assert old.summary["weight_kN"] == pytest.approx(1349.7034382400013, rel=1e-12)
    # V = Sa W: the base shear follows W.
    ratio = full.summary["weight_kN"] / old.summary["weight_kN"]
    assert full.summary["base_shear_kN"] == pytest.approx(
        old.summary["base_shear_kN"] * ratio, rel=1e-9
    )
    note = full.summary["seismicWeight"]["note"]
    assert "partition allowance in full" in note and "Sec 2.5.7.3" in note


def test_the_gravity_loads_do_not_change(models) -> None:
    """Only W changes: the L case carries the same loads (the allowance stays a live load)."""

    def loads(d) -> dict[str, dict]:
        """Per case the summed nodal forces per node and member loads per member."""
        out: dict[str, dict] = {}
        for p in d.project["load_patterns"]:
            here: dict = {}
            for x in p.get("nodal_loads", []):
                key = ("n", x["node_id"])
                here[key] = [a + b for a, b in zip(here.get(key, [0.0] * 6), x["forces"])]
            for e in p.get("element_loads", []):
                key = ("e", e["element_id"])
                here[key] = [here.get(key, [0.0])[0] + float(e.get("wz", 0.0) or 0.0)]
            out[p["name"]] = here
        return out

    full, old = loads(models["pack"]), loads(models["withLiveShare"])
    for case in ("D", "SD", "L", "Lr"):
        assert full[case].keys() == old[case].keys(), case
        for key, value in old[case].items():
            assert full[case][key] == pytest.approx(value, rel=1e-9, abs=1e-6), (case, key)


def test_a_factor_of_my_own(models) -> None:
    full, own = models["pack"], models["factor"]
    assert _level1(own)["partitions"] == pytest.approx(0.5 * PARTITIONS * A, abs=1e-3)
    assert full.summary["weight_kN"] - own.summary["weight_kN"] == pytest.approx(
        0.5 * PARTITIONS * A, abs=1e-6
    )
    assert "partition allowance x0.5 (project setting)" in own.summary["seismicWeight"]["note"]


def test_the_override_through_code_overrides(models) -> None:
    settings = _settings(codeOverrides={"seismic.partitionWeight": "withLiveShare"})
    pack = code_context.pack_for(settings)
    assert pack.override_problems == []
    basis = partition_weight_basis(settings, pack)
    assert basis.mode == "withLiveShare" and basis.source.startswith("project override")
    with code_context.using(pack):
        model = _derive(settings)
    assert model.summary["weight_kN"] == pytest.approx(
        models["withLiveShare"].summary["weight_kN"], rel=1e-12
    )
    # The project setting wins over the pack (and its override).
    chosen = _settings("full", codeOverrides={"seismic.partitionWeight": "withLiveShare"})
    assert partition_weight_basis(chosen, code_context.pack_for(chosen)).mode == "full"


def test_a_pack_without_the_value_uses_the_generic_default(tmp_path, models) -> None:
    from saengine.report.build import _basis, _Parts

    root = tmp_path / "W project"
    (root / "02 Project Settings").mkdir(parents=True)
    pack_dir = root / registry.PROJECT_PACKS / STUB
    (pack_dir / "data").mkdir(parents=True)
    manifest = {
        "schema": "saengine.codePack/1",
        "id": STUB,
        "name": "Stub Code 2031",
        "version": "0.1.0",
        "extends": registry.DEFAULT_PACK,
        "covers": ["seismic"],
    }
    (pack_dir / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pack_dir / "data/seismic.json").write_text(
        json.dumps({"$remove": ["partitionWeight"]}), encoding="utf-8"
    )
    settings = _settings(codePack=STUB)
    with code_context.project(root):
        pack = code_context.pack_for(settings, root)
        assert "seismic.partitionWeight" in [f.path for f in pack.fallbacks]
        fallback = pack.fallback("seismic", "partitionWeight")
        assert fallback is not None and fallback.note.startswith("ASCE 7-22 Sec 12.7.2")
        basis = partition_weight_basis(settings, pack)
        report = _basis(settings, _Parts(root, []), {}, {})
        with code_context.using(pack):
            model = _derive(settings, root)
    assert basis.mode == "full"
    assert basis.source == "generic default (SAEngine practice), not given by Stub Code 2031"
    assert "seismic.partitionWeight" in [row[0] for row in report["genericDefaults"]]
    assert report["partitionWeightFrom"] == basis.source
    assert model.summary["weight_kN"] == pytest.approx(
        models["pack"].summary["weight_kN"], rel=1e-12
    )


def test_partitions_as_dead_load_count_in_full_either_way() -> None:
    """With the allowance in SD (a pack's or the project's choice) it counts in full whatever the
    W rule but a factor of the project's."""
    sd = default_project_settings("W")
    sd.analysis.partitionAllowanceCase = "SD"
    assert seismic_weight_rule(sd).area(LIVE, PARTITIONS) == (0.25, 1.0)
    sd.analysis.massSource.partitions = "withLiveShare"
    assert seismic_weight_rule(sd).area(LIVE, PARTITIONS) == (0.25, 1.0)
    sd.analysis.massSource.partitions = "factor"
    sd.analysis.massSource.partitionShare = 0.4
    assert seismic_weight_rule(sd).area(LIVE, PARTITIONS) == (0.25, 0.4)


# ─────────────────────────────── the report ───────────────────────────────


def test_the_report_says_how_w_was_formed() -> None:
    from saengine.report import document
    from saengine.report.build import _basis, _Parts

    basis = _basis(_settings(), _Parts(Path("."), []), {}, {})
    assert basis["partitionWeight"].startswith("partition allowance in full")
    assert "Sec 2.5.7.3" in basis["partitionWeightFrom"]
    built = document._basis(
        {"basis": {**basis, "materials": [], "cases": []}},
        document.Context(document.default_report_template(), "full", []),
    )
    text = json.dumps(built)
    assert "In the seismic weight W: partition allowance in full" in text


# ─────────────────────────────── ETABS ───────────────────────────────


def _e2k(settings) -> tuple[str, list[dict]]:
    from test_correctness_wiring import _three_bays_two_storeys

    from saengine.exporters.etabs import write_e2k
    from saengine.library import default_material_library

    building, objects = _three_bays_two_storeys()
    export = write_e2k(building, objects, default_material_library(), settings)
    return export.text, export.report.to_dict()["approximated"]


def test_the_e2k_mass_source_gives_saengine_w() -> None:
    text, _ = _e2k(_settings())
    # The allowance in a live pattern of its own, in the mass source in full, combined as L.
    assert 'LOADPATTERN "PART"  TYPE  "Live"' in text
    assert 'MASSSOURCELOAD  "MsSrc1"  "L"  0.25' in text
    assert 'MASSSOURCELOAD  "MsSrc1"  "PART"  1' in text
    assert 'LC "PART"  FVAL 1.2' in text
    combo = next(line for line in text.splitlines() if 'LOADCASE "L"  SF 1.6' in line)
    name = combo.split('"')[1]
    assert f'COMBO "{name}"  LOADCASE "PART"  SF 1.6' in text
    # The earlier rule: the allowance in L, which takes the share judged on live + partitions.
    old, _ = _e2k(_settings("withLiveShare"))
    assert '"PART"' not in old
    assert 'MASSSOURCELOAD  "MsSrc1"  "L"  0.5' in old
    # A factor of the project's.
    own, _ = _e2k(_settings("factor", 0.3))
    assert 'MASSSOURCELOAD  "MsSrc1"  "PART"  0.3' in own


def _import(text: str):
    from saengine.importers.etabs import read_e2k

    return read_e2k("w.e2k", text=text)


def _w_v(building, objects, materials, settings) -> tuple[float, float]:
    from saengine.fem.derive import derive_fem

    d = derive_fem(building, objects, materials, settings, {"bim": "x"})
    return d.summary["seismicWeight"]["total_kN"], d.summary["base_shear_kN"]


def _floor(project):
    return {a.id: a for a in project.settings.areaLoads}["FL"]


@pytest.mark.parametrize(
    ("mode", "share", "restored", "back"),
    [
        ("pack", None, True, ("pack", None)),
        ("full", None, True, ("pack", None)),  # the pack says full: left to the pack
        ("factor", 0.3, True, ("factor", 0.3)),
        ("withLiveShare", None, False, ("pack", None)),  # in L, no PART: W is the same
    ],
)
def test_the_e2k_round_trip_restores_the_partition_allowance(mode, share, restored, back) -> None:
    """Owner decision 2026-11-03: the importer restores the partition allowance. Exported and
    read back, the area load's partitions, the mass-source setting, W and V are the original's."""
    from test_correctness_wiring import _three_bays_two_storeys

    from saengine.library import default_material_library

    settings = _settings(mode, share)
    text, _ = _e2k(settings)
    project = _import(text)
    floor = _floor(project)
    if restored:
        assert (floor.live, floor.partitions) == (pytest.approx(LIVE), pytest.approx(PARTITIONS))
    else:
        assert (floor.live, floor.partitions) == (pytest.approx(LIVE + PARTITIONS), 0.0)
    source = project.settings.analysis.massSource
    assert (source.partitions, source.partitionShare) == back
    approximated = project.report.to_dict()["approximated"]
    assert not any("imported as live load" in str(a) for a in approximated)
    # W and V: the original's (the site and seismic settings, not in the e2k, the original's).
    building, objects = _three_bays_two_storeys()
    original = _w_v(building, objects, default_material_library(), settings)
    again = project.settings.model_copy(deep=True)
    again.site, again.seismic = settings.site, settings.seismic
    w_v = _w_v(project.bim, project.objects, project.materials, again)
    assert w_v == pytest.approx(original, rel=1e-9)


def test_the_mass_source_factor_sets_the_partition_rule() -> None:
    """The PART factor of another file: the live share → with the live share; none → 0."""
    text, _ = _e2k(_settings())
    line = 'MASSSOURCELOAD  "MsSrc1"  "PART"  1 '
    assert line in text
    live = _import(text.replace(line, 'MASSSOURCELOAD  "MsSrc1"  "PART"  0.25 '))
    assert live.settings.analysis.massSource.partitions == "withLiveShare"
    none = _import(text.replace(line, ""))
    source = none.settings.analysis.massSource
    assert (source.partitions, source.partitionShare) == ("factor", 0.0)
    assert _floor(none).partitions == pytest.approx(PARTITIONS)


def test_a_partition_pattern_of_another_file() -> None:
    """A Superimposed Dead pattern named "Partitions" is the allowance in SD (the project names
    the case, the pack's being L); "PARTIAL" and a Dead pattern are read as their type says."""
    text, _ = _e2k(_settings())
    sd = text.replace('"PART"', '"Partitions"').replace(
        'LOADPATTERN "Partitions"  TYPE  "Live"', 'LOADPATTERN "Partitions"  TYPE  "Super Dead"'
    )
    assert 'TYPE  "Super Dead"' in sd
    project = _import(sd)
    assert _floor(project).partitions == pytest.approx(PARTITIONS)
    assert project.settings.analysis.partitionAllowanceCase == "SD"
    assert project.settings.analysis.massSource.partitions == "pack"  # SD counts in full
    partial = _import(text.replace('"PART"', '"PARTIAL"'))
    assert _floor(partial).partitions == 0.0
    assert _floor(partial).live == pytest.approx(LIVE + PARTITIONS)
    dead = text.replace('LOADPATTERN "PART"  TYPE  "Live"', 'LOADPATTERN "PART"  TYPE  "Dead"')
    project = _import(dead)
    assert _floor(project).partitions == 0.0
    words = json.dumps(project.report.to_dict()["approximated"])
    assert "patterns named as partitions read as their type says" in words
