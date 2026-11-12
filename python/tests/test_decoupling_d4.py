"""Decoupling track D4 (report, worksheets, drawings, bill of quantities): the code is only a
setting.

- With the default pack the worksheets, the report's helpers and the bar detailing give the same
  values and the same clause texts as before the decoupling (now read from the pack's
  ``citations`` table and its other tables): pinned here.
- A stub pack that extends the default pack and overrides one table changes only what that
  table drives: ``citations`` changes the clause one step cites (named after the stub pack), the
  values stay; ``seismic`` (the period cap) changes the capped period and its formula.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.codes import context as code_context
from saengine.codes import registry
from saengine.report.worksheets import calculate

STUB = "stub-d4"


def _stub_pack(folder: Path, table: str, data: dict) -> Path:
    """A pack that extends the default pack and changes only ``table``."""
    pack = folder / STUB
    (pack / "data").mkdir(parents=True)
    manifest = {
        "schema": "saengine.codePack/1",
        "id": STUB,
        "name": "Stub Code 2030",
        "version": "0.1.0",
        "extends": registry.DEFAULT_PACK,
        "covers": [table],
    }
    (pack / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pack / f"data/{table}.json").write_text(json.dumps(data), encoding="utf-8")
    return pack


def _with_stub(tmp_path: Path, table: str, data: dict, kind: str, inputs: dict) -> dict:
    root = tmp_path / "Stub project"
    (root / "02 Project Settings").mkdir(parents=True)
    _stub_pack(root / registry.PROJECT_PACKS, table, data)
    with code_context.project(root):
        pack = code_context.pack_for({"codePack": STUB}, root)
        with code_context.using(pack):
            return calculate(kind, inputs)


def _steps(result: dict) -> dict[str, dict]:
    return {s["label"]: s for s in result["steps"] if "label" in s}


# ───────────────────────── no change in results with the default pack ─────────────────────────


def test_seismic_worksheet_is_pinned() -> None:
    result = calculate("seismic-base-shear", {"period_given": True, "period": 3.0})
    steps = _steps(result)
    # Values and clause texts before the decoupling (base 1433188c, 2026-11-02).
    assert steps["T"]["formula"] == "Ta ≤ T ≤ 1.4 Ta"
    assert steps["T"]["clause"] == "BNBC 2020 Part 6 Sec 2.5.7.2 (a)"
    assert steps["R"]["clause"].startswith("BNBC 2020 Part 6 Table 6.2.19 row ")
    assert steps["V"]["clause"] == "BNBC 2020 Part 6 Sec 2.5.7"
    assert steps["Z"]["clause"] == "BNBC 2020 Part 6 Table 6.2.14"
    assert result["references"] == [
        "BNBC 2020 Part 6 Sec 2.5 (Tables 6.2.14-6.2.20; Eq. 6.2.38; Sec 2.5.7)"
    ]


def test_concrete_worksheets_cite_as_before() -> None:
    beam = calculate("beam-flexure", {})
    assert beam["references"] == [
        "ACI 318-19 22.2, 21.2.2, 9.6.1.2-9.6.1.3 (BNBC 2020 Part 6 Ch 6)"
    ]
    deflection = calculate("beam-deflection", {})
    assert deflection["references"] == [
        "BNBC 2020 Part 6 Sec 6.2.5, Tables 6.6.1-6.6.2, Eqs. 6.6.1-6.6.4"
    ]
    assert _steps(deflection)["Ec"]["clause"] == "BNBC 2020 Part 6 Sec 6.1.7.1"


def test_retaining_wall_reads_the_earth_pressure_factor_from_the_pack() -> None:
    from saengine.report.worksheets.ground_loads import earth_pressure_factor

    assert earth_pressure_factor() == 1.6
    steps = _steps(calculate("retaining-wall", {}))
    assert steps["Mu"]["formula"] == "1.6 (Ka γ h³/6 + Ka q h²/2)"
    assert steps["Mu"]["clause"] == "BNBC 2020 Part 6 Sec 2.7.3.1"


def test_report_helpers_read_the_pack() -> None:
    from saengine.report import build

    assert build._period_cap_text() == " = 1.4 Ta"
    assert build._cracked_text() == (
        "BNBC 2020 Part 6 Sec 6.3.10.4.1: columns 0.70 Ig, beams 0.35 Ig, walls 0.70 Ig or "
        "0.35 Ig, slabs 0.25 Ig"
    )
    method = build._tank_method()
    assert "uplift on the base, BNBC 2020 Part 6 Sec 2.6.5)" in method[0]
    assert "residual heads (BNBC 2020 Part 8 Table 8.5.6)" in method[2]


def test_bar_detailing_cites_as_before() -> None:
    from saengine.drawings import bbs, detailing

    assert (
        detailing.bend_diameter(20).clause == "BNBC 2020 Part 6 Sec 8.1.2.2(a), Table 6.8.1, p 1066"
    )
    assert detailing.bend_diameter(12, transverse=True).value == 48
    # The schedule's bend radius uses the detailing's bend diameter (no copy of the table).
    assert bbs.code_bend_diameter(20) == 120.0
    assert bbs.code_bend_diameter(12, transverse=True) == 48.0
    assert bbs.code_bend_diameter(32) == 256.0
    assert bbs.code_bend_diameter(50) == 500.0
    assert bbs._bend_reference() == "BNBC 2020 Part 6, 8.1.2.2"


# ─────────────────────────────── a second pack swapped in ───────────────────────────────


def test_stub_citations_change_only_the_clause(tmp_path) -> None:
    inputs = {"period_given": True, "period": 3.0}
    base = calculate("seismic-base-shear", inputs)
    stub = _with_stub(
        tmp_path,
        "citations",
        {"clauses": {"wsBaseShear": "Rule 9.9"}},
        "seismic-base-shear",
        inputs,
    )
    ours, theirs = _steps(stub), _steps(base)
    assert ours["V"]["clause"] == "Stub Code 2030 Rule 9.9"
    # Everything else is the same: the values and the clauses the stub inherits (which keep
    # the name of the pack that gives them).
    assert [s.get("value") for s in stub["steps"]] == [s.get("value") for s in base["steps"]]
    assert ours["Z"]["clause"] == theirs["Z"]["clause"] == "BNBC 2020 Part 6 Table 6.2.14"
    assert stub["references"] == base["references"]


def test_stub_period_cap_changes_the_capped_period(tmp_path) -> None:
    inputs = {"period_given": True, "period": 3.0}
    base = calculate("seismic-base-shear", inputs)
    stub = _with_stub(tmp_path, "seismic", {"periodUpperFactor": 1.2}, "seismic-base-shear", inputs)
    ours, theirs = _steps(stub), _steps(base)
    assert ours["T"]["formula"] == "Ta ≤ T ≤ 1.2 Ta"
    assert ours["T"]["number"] == pytest.approx(theirs["T"]["number"] * 1.2 / 1.4)
    assert ours["Ta"] == theirs["Ta"]
    assert ours["Z"] == theirs["Z"]


def test_a_pack_without_a_clause_cites_none() -> None:
    from saengine.codes import citations

    assert citations.ref("noSuchKey") == ""
    assert citations.paren("noSuchKey") == ""
    assert citations.after("noSuchKey") == ""
    assert citations.ref("soilSprings") == "BNBC 2020 Part 6 Sec 1.2.7.3"
