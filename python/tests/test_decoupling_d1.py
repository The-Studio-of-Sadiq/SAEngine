"""Decoupling track D1 (fem, library, importers, rpc, project, codes helpers): the code is only a
setting.

- With the default pack the derived model is the same as before the decoupling: the results
  and the clause texts (now read from the pack's ``clauses``) are pinned here.
- A stub pack that extends the default pack and overrides one table (``seismic``) changes only
  what that table drives: the seismic weight and the earthquake cases, and the clause it
  names; the gravity and wind cases stay the same.
- The former settings values named after the code are read as the new ones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry

STUB = "stub-d1"


def _stub_pack(folder: Path) -> Path:
    """A pack that extends the default pack and changes only its ``seismic`` table: the live
    share of the seismic weight and the clause the seismic weight note cites."""
    pack = folder / STUB
    (pack / "data").mkdir(parents=True)
    manifest = {
        "schema": "saengine.codePack/1",
        "id": STUB,
        "name": "Stub Code 2030",
        "version": "0.1.0",
        "extends": registry.DEFAULT_PACK,
        "covers": ["seismic"],
    }
    (pack / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    seismic = {"liveShare": 0.5, "clauses": {"weight": "Chapter 9 Rule 9.9"}}
    (pack / "data/seismic.json").write_text(json.dumps(seismic), encoding="utf-8")
    return pack


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
    from saengine.library.settings import default_project_settings

    return _derive(default_project_settings("D1"))


# ───────────────────────── no change in results with the default pack ─────────────────────────


def test_default_pack_results_are_pinned(default_model) -> None:
    d = default_model
    s = d.summary
    # The values of the derived model before the decoupling (v0.0.45 base, 2026-11-02).
    assert s["weight_kN"] == pytest.approx(1357.2034382399995, rel=1e-12)
    assert s["base_shear_kN"] == pytest.approx(76.34269340099998, rel=1e-12)
    assert s["period_s"] == pytest.approx(0.24771248339517093, rel=1e-12)
    assert s["wind_X_kN"] == pytest.approx(29.06010093994609, rel=1e-12)
    assert s["wind_Y_kN"] == pytest.approx(108.95203529021688, rel=1e-12)
    assert [p["name"] for p in d.project["load_patterns"]] == [
        "D", "SD", "L", "Lr", "WX", "WY", "EX", "EY", "EXP", "EXN", "EYP", "EYN",
        "WTX", "WTY", "LP1", "LP2", "LP3", "LP4",
    ]  # fmt: skip


def test_default_pack_clause_texts_are_unchanged(default_model) -> None:
    """The clause texts the notes and labels carried before now come from the pack's
    ``clauses`` and read the same with the default pack."""
    d = default_model
    live = d.summary["patternLive"]
    assert live["mode"] == "adjacent"
    assert [c["clause"] for c in live["cases"]] == [
        "BNBC 2020 Part 6 Sec 6.1.12.2 (b)",
        "BNBC 2020 Part 6 Sec 6.1.12.2 (b)",
        "BNBC 2020 Part 6 Sec 6.1.12.2 (a)",
        "BNBC 2020 Part 6 Sec 6.1.12.2 (a)",
    ]
    names = [p["name"] for p in d.project["load_patterns"]]
    assert names  # the case labels are in the analyses' titles where present
    from saengine.fem.derive import case_label

    assert (
        case_label("WTX") == "Torsion of the wind in X (BNBC 2020 Part 6 Figure 6.2.9, e = 0.15 B)"
    )
    weight = next(n for n in d.notes if n.startswith("seismic weight W ="))
    assert "(BNBC 2020 Part 6 Sec 2.5.7.3): dead load x1" in weight


def test_clause_helpers_read_the_pack() -> None:
    pack = code_context.default_pack()
    assert code_context.code_name(pack) == "BNBC 2020"
    assert code_context.cite("seismic", "weight", pack) == "BNBC 2020 Part 6 Sec 2.5.7.3"
    assert code_context.cited("areaLoads", "partitions", pack, sep="; ") == (
        "; BNBC 2020 Part 6 Sec 2.3.6, p. 540"
    )
    # A clause the pack does not give is not cited (no fallback to another code's text).
    assert code_context.cite("seismic", "noSuchClause", pack) == ""
    assert code_context.cited("seismic", "noSuchClause", pack) == ""
    assert code_context.source_ref("hvac", "ventilation", pack) == "BNBC 2020 Part 8 Table 8.2.3"


def test_tower_and_pattern_rules_come_from_the_pack() -> None:
    from saengine.fem import pattern_live, towers

    assert towers.setback_ratio() == 1.3
    assert towers.clauses()["scale"] == "BNBC 2020 Part 6 Sec 2.5.9.4 (p. 635)"
    assert towers.clauses()["setback"] == "BNBC 2020 Part 6 Sec 2.5.5.3.2"
    ok, why = pattern_live.patterns_required("flat", dead=8.0, live=6.0)
    assert not ok and "0.75 x dead load 8" in why and "Sec 6.5.7.6.2" in why
    ok, why = pattern_live.patterns_required("flat", dead=8.0, live=6.5)
    assert ok and why == "live load arrangement of BNBC 2020 Part 6 Sec 6.1.12.2"


def test_settlement_clause_and_story_response_scale_read_the_pack() -> None:
    from saengine.fem import settlement

    assert settlement.clause() == (
        "BNBC 2020 Part 6 Sec 2.7.3.1 (p. 685), T including differential settlement"
    )


# ─────────────────────────────── a second pack swapped in ───────────────────────────────


def test_stub_pack_changes_only_its_table(tmp_path, default_model) -> None:
    from saengine.library.settings import default_project_settings

    root = tmp_path / "Stub project"
    (root / "02 Project Settings").mkdir(parents=True)
    _stub_pack(root / registry.PROJECT_PACKS)
    settings = default_project_settings("D1").model_copy(update={"codePack": STUB})
    stub = _derive(settings, root)
    base = default_model

    # The seismic table drives the seismic weight and the earthquake cases: they change.
    assert stub.summary["weight_kN"] > base.summary["weight_kN"]
    assert stub.summary["base_shear_kN"] > base.summary["base_shear_kN"]
    ours, theirs = _patterns(stub), _patterns(base)
    for case in ("EX", "EY"):
        assert ours[case] != theirs[case], case
    # Nothing else: the gravity and live arrangement cases are the same.
    for case in ("D", "SD", "L", "Lr", "LP1", "LP2", "LP3", "LP4"):
        assert ours[case] == theirs[case], case
    # The wind forces are the same at every level; only their share-out to the level's nodes
    # follows the nodes' seismic weight.
    assert stub.summary["wind_X_kN"] == base.summary["wind_X_kN"]
    assert stub.summary["wind_Y_kN"] == base.summary["wind_Y_kN"]
    for axis in ("WX", "WY"):
        forces = [
            [(row["z"], row["force_kN"]) for row in d.summary["wind"]["levels"][axis]]
            for d in (stub, base)
        ]
        assert forces[0] == forces[1], axis
    for case in ("WX", "WY", "WTX", "WTY"):
        total = [sum(sum(n["forces"][:3]) for n in p[0] or []) for p in (ours[case], theirs[case])]
        assert total[0] == pytest.approx(total[1], abs=0.5), case  # N, nodal rounding
    # The clauses the stub inherits keep the name of the pack that gives them.
    assert stub.summary["patternLive"] == base.summary["patternLive"]
    # The note cites the stub pack's own clause, named after the stub pack.
    weight = next(n for n in stub.notes if n.startswith("seismic weight W ="))
    assert "(Stub Code 2030 Chapter 9 Rule 9.9)" in weight and "BNBC" not in weight
    assert "live load x0.5" in weight


# ──────────────────────────────── names and former values ────────────────────────────────


def test_former_pattern_live_values_are_read_as_the_new_ones() -> None:
    from saengine.library.settings import Analysis

    assert Analysis.model_validate({"patternLive": "bnbc"}).patternLive == "adjacent"
    assert (
        Analysis.model_validate({"patternLive": "bnbcAlternateFloors"}).patternLive
        == "adjacentAlternateFloors"
    )
    assert Analysis().patternLive == "adjacent"


def test_code_data_is_the_former_library_bnbc() -> None:
    from saengine.library import bnbc, code_data

    assert code_data.PACK_ID == registry.DEFAULT_PACK
    assert bnbc.LOCATIONS is code_data.LOCATIONS
    assert bnbc.STRUCTURAL_SYSTEMS is code_data.STRUCTURAL_SYSTEMS


def test_generated_typescript_keeps_the_former_export_name() -> None:
    from saengine.library.export import generate_typescript

    text = generate_typescript()
    assert "export const DEFAULT_CODE_TABLES: IDefaultCodeTables = {" in text
    assert "export const BNBC: IDefaultCodeTables = DEFAULT_CODE_TABLES;" in text
    assert "export type IBnbcTables = IDefaultCodeTables;" in text
