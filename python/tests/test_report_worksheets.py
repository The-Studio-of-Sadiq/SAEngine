"""Calculation worksheets (Part 11 Report): the kinds call the design functions, the files, and
the report's "Calculation worksheets" section."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from saengine.library.check import check_library
from saengine.library.report_template import ReportSection, ReportTemplate
from saengine.library.worksheet import WORKSHEETS_FOLDER, Worksheet, load_worksheets
from saengine.report.document import report_document
from saengine.report.worksheets import (
    KINDS,
    calculate,
    create_worksheet,
    list_worksheets,
    project_worksheets,
)
from saengine.soil.earth_pressure import rankine_active


def _step(result: dict, label: str) -> float:
    for step in result["steps"]:
        if step.get("label") == label:
            return step["number"]
    raise KeyError(label)


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_every_kind_calculates_with_its_defaults(kind: str) -> None:
    result = calculate(kind)
    assert result["problems"] == []
    assert result["steps"]
    for check in result["checks"]:
        assert check["clause"] or check["label"]


def test_unknown_kind_and_bad_inputs_are_not_calculated() -> None:
    assert calculate("no-such-kind")["problems"]
    result = calculate("beam-flexure", {"b": 10, "fc": "x"})
    assert len(result["problems"]) == 2
    assert result["steps"] == []


def test_rankine_active_coefficient() -> None:
    # Ka = (1 - sin 30°) / (1 + sin 30°) = 1/3
    assert rankine_active(30) == pytest.approx(1 / 3)


def test_development_length_simplified() -> None:
    # BNBC 2020 Part 6 Sec 8.2.3.2: ld = fy ψt ψe / (2.1 λ √f'c) db = 420 / (2.1 × 5) × 20
    result = calculate("development-length", {"db": 20, "fy": 420, "fc": 25})
    assert _step(result, "ld (tension)") == pytest.approx(800.0)
    # 8.2.4: ldc = max(0.24 fy db / √f'c, 0.043 fy db) = max(403.2, 361.2)
    assert _step(result, "ldc (compression)") == pytest.approx(403.2)


def test_column_axial_capacity() -> None:
    # ACI 318-19 22.4.2: P0 = 0.85 f'c (Ag - Ast) + fy Ast; tied φPn,max = 0.80 × 0.65 × P0
    result = calculate("column-axial", {"b": 400, "h": 400, "n": 8, "dia": 20, "pu": 2000})
    ast = 8 * math.pi * 20**2 / 4
    p0 = 0.85 * 25 * (400 * 400 - ast) + 420 * ast
    assert _step(result, "P0") == pytest.approx(p0 / 1e3)
    assert _step(result, "φPn,max") == pytest.approx(0.80 * 0.65 * p0 / 1e3)
    assert result["ok"]


def test_punching_perimeter_interior_edge_corner() -> None:
    # ACI 318-19 22.6.4.1: b0 at d/2, d = 250 - 30 = 220 mm, 400 × 400 column
    base = {"c1": 400, "c2": 400, "h": 250, "dc": 30}
    assert _step(calculate("punching", base), "b0") == pytest.approx(4 * 620)
    edge = calculate("punching", {**base, "location": "edge"})
    assert _step(edge, "b0") == pytest.approx(620 + 2 * 510)
    corner = calculate("punching", {**base, "location": "corner"})
    assert _step(corner, "b0") == pytest.approx(2 * 510)


def test_seismic_base_shear() -> None:
    # BNBC 2020 Part 6 Sec 2.5: Ta = Ct hn^m (Table 6.2.20, Eq. 6.2.38), Sa = 2/3 Z I / R Cs,
    # V = Sa W; RC SMF R = 8 (Table 6.2.19), zone 2 Z = 0.20, site SD S = 1.35, TC = 0.8 s
    result = calculate(
        "seismic-base-shear",
        {
            "zone": "2",
            "site": "SD",
            "category": "II",
            "system": "rcSmf",
            "hn": 30,
            "weight": 50000,
            "storeys": 0,
        },
    )
    ta = 0.0466 * 30**0.9
    cs = 2.5 * 1.35 * 0.8 / ta
    sa = 2 / 3 * 0.20 * 1.0 / 8 * cs
    assert _step(result, "Ta") == pytest.approx(ta)
    assert _step(result, "V") == pytest.approx(sa * 50000)


def test_wind_on_a_sign() -> None:
    # F = qh G Cf As with qh = 0.000613 Kz Kzt Kd V² I (BNBC 2020 Part 6 Sec 2.4)
    result = calculate("wind-sign", {"speed": 65.7, "height": 8, "depth": 3, "width": 6, "cf": 1.8})
    qh = _step(result, "qh")
    assert _step(result, "F") == pytest.approx(qh * 0.85 * 1.8 * 18)


def test_retaining_wall_pressure() -> None:
    # Pa = ½ Ka γ H'² with H' to the underside of the base
    result = calculate("retaining-wall", {"height": 3000, "base": 400, "phi": 30, "gamma": 18})
    assert _step(result, "Pa (soil)") == pytest.approx(0.5 / 3 * 18 * 3.4**2)


def test_worksheet_files_and_report_section(tmp_path: Path) -> None:
    made = create_worksheet(tmp_path, "development-length", "ld-b12", "Development of B12 bars")
    assert Path(made["path"]).is_file()
    assert create_worksheet(tmp_path, "development-length", "ld-b12")["existing"]
    assert create_worksheet(tmp_path, "nothing", "x")["problems"]
    hidden = Worksheet(id="hidden", kind="lap-splice", title="Lap", print=False)
    (tmp_path / WORKSHEETS_FOLDER / "hidden.json").write_text(
        json.dumps(hidden.model_dump(by_alias=True)), encoding="utf-8"
    )
    found, problems = load_worksheets(tmp_path)
    assert [s.id for _, s in found] == ["hidden", "ld-b12"] and problems == []
    assert len(list_worksheets(tmp_path)["worksheets"]) == 2

    sheets, warnings = project_worksheets(tmp_path)
    assert [s["title"] for s in sheets] == ["Development of B12 bars (Development length)"]
    assert warnings == []
    only = ReportTemplate(sections=[ReportSection(id="worksheets")])
    document = report_document({"worksheets": sheets, "warnings": []}, only)
    section = next(s for s in document["sections"] if s["id"] == "worksheets")
    assert section["blocks"][0]["text"].startswith("Development of B12 bars")


def test_library_check_of_a_worksheet() -> None:
    good = Worksheet(id="a", kind="beam-shear", title="Shear", inputs={"vu": 120})
    text = json.dumps(good.model_dump(by_alias=True))
    assert check_library("worksheet", text) == []
    bad = json.loads(text) | {"inputs": {"nope": 1, "b": 5}}
    messages = [p["message"] for p in check_library("worksheet", json.dumps(bad))]
    assert any("no input 'nope'" in m for m in messages)
    assert any("below" in m for m in messages)
