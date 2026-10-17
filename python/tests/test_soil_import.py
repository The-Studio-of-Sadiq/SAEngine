"""Import of borehole logs from CSV and Excel, and the import template."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.library.soil import SoilReport
from saengine.soil import import_soil, soil_template
from saengine.soil.importer import EXAMPLE, soil_type_of


def write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_template_round_trip_csv_and_xlsx(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    for suffix in ("csv", "xlsx"):
        target = tmp_path / f"template.{suffix}"
        assert soil_template(str(target)) == {"path": str(target)}
        result = import_soil(str(target), None)
        assert "problems" not in result, result
        report = SoilReport.model_validate_json(result["text"])
        (hole,) = report.boreholes
        assert hole.id == "BH-1" and hole.waterTable == 1500 and hole.depth == 15000
        assert [layer.soilType for layer in hole.layers] == ["fill", "clay", "sand"]
        assert hole.layers[1].cu == 25 and hole.layers[1].bottom == 6000
        assert len(hole.spt) == sum(1 for e in EXAMPLE if e["record"] == "spt")
        assert hole.samples[0].plasticLimit == 23 and hole.samples[0].type == "UD"
        assert result["notes"] == ["BH-1: added (3 layers, 10 SPT records, 2 samples)."]


def test_template_names_the_format(tmp_path: Path) -> None:
    assert "problems" in soil_template(str(tmp_path / "template.txt"))


def test_inferred_records_units_and_merging(tmp_path: Path) -> None:
    csv = write(
        tmp_path / "log.csv",
        "BH;Top (mm);Bottom (mm);Description;USCS;N;Depth (mm);FC (%)\n"
        "BH-2;0;2000;Grey silty CLAY;;;;\n"
        "BH-2;2000;8000;Grey silty fine sand;SM;;;\n"
        "BH-2;;;;;7;1500;\n"
        "BH-2;;;;;12;4500;\n"
        "BH-2;;;;;;4500;22\n",
    )
    existing = json.dumps(
        {
            "schema": "saengine.soilReport/1",
            "report": {"title": "Kept"},
            "boreholes": [{"id": "BH-1"}, {"id": "BH-2", "x": 5}],
        }
    )
    result = import_soil(csv, existing)
    assert "problems" not in result, result
    report = SoilReport.model_validate_json(result["text"])
    assert report.report.title == "Kept"
    assert [b.id for b in report.boreholes] == ["BH-1", "BH-2"]
    hole = report.boreholes[1]
    assert hole.x == 0  # replaced
    assert [layer.soilType for layer in hole.layers] == ["clay", "sand"]
    assert [r.N for r in hole.spt] == [7, 12]
    assert hole.samples[0].finesContent == 22 and hole.samples[0].depth == 4500
    assert any(n.startswith("BH-2: replaced") for n in result["notes"])
    assert any("description" in n for n in result["notes"])


def test_row_level_problems(tmp_path: Path) -> None:
    csv = write(
        tmp_path / "bad.csv",
        "Borehole,Record,Top,Bottom,Soil type,Depth,N,Water table,PL\n"
        "BH-1,layer,0,abc,clay,,,1.5,\n"
        "BH-1,layer,1,3,loam,,,1.5,\n"
        "BH-1,spt,,,,2,7.5,2.0,\n"
        "BH-1,layer,3,5,sand,,,,30\n"
        ",layer,0,1,sand,,,,\n"
        "BH-1,core,,,,,,,\n",
    )
    problems = import_soil(csv)["problems"]
    assert "row 2 (BH-1): Bottom: 'abc' is not a number" in problems
    assert any(p.startswith("row 3 (BH-1): Soil type: 'loam'") for p in problems)
    assert "row 4 (BH-1): N: 7.5 is not a whole number of blows" in problems
    assert any(p.startswith("row 4 (BH-1): Water table: 2000 differs") for p in problems)
    assert any(p.startswith("row 5 (BH-1): a layer has no PL") for p in problems)
    assert "row 6: no borehole id" in problems
    assert "row 7 (BH-1): Record: 'core' is not layer, spt or sample" in problems


def test_model_problems_name_the_file_and_borehole(tmp_path: Path) -> None:
    csv = write(
        tmp_path / "gap.csv",
        "Borehole,Top,Bottom,Soil type\nBH-9,0,2,clay\nBH-9,3,5,sand\n",
    )
    (problem,) = import_soil(csv)["problems"]
    assert problem.startswith("gap.csv: BH-9: ") and "gap between layers 1 and 2" in problem


def test_unreadable_files(tmp_path: Path) -> None:
    assert import_soil(str(tmp_path / "missing.csv"))["problems"][0].startswith("missing.csv")
    assert "use a .csv or .xlsx" in import_soil(write(tmp_path / "a.json", "{}"))["problems"][0]
    no_header = write(tmp_path / "h.csv", "a,b\n1,2\n")
    assert "header" in import_soil(no_header)["problems"][0]


def test_soil_type_from_uscs_and_description() -> None:
    assert soil_type_of(None, "CH", None) == "clay"
    assert soil_type_of(None, "SM-SC", None) == "sand"
    assert soil_type_of(None, "PT", None) == "organic"
    assert soil_type_of("ML", None, None) == "silt"
    assert soil_type_of(None, None, "Very loose grey clayey SAND with mica") == "sand"
    assert soil_type_of(None, None, "Soft grey silty clay") == "clay"
    assert soil_type_of("Made ground", None, None) == "fill"
    assert soil_type_of("loam", None, None) is None


def test_header_units_are_converted_or_reported(tmp_path: Path) -> None:
    csv = write(
        tmp_path / "units.csv",
        "Borehole,Top,Bottom,Soil type,Bulk density (g/cc),cu (kg/cm2),E (kg/cm2)\n"
        "BH-1,0,5,clay,1.85,0.5,100\n",
    )
    result = import_soil(csv)
    layer = json.loads(result["text"])["boreholes"][0]["layers"][0]
    assert layer["unitWeight"] == pytest.approx(1.85 * 9.80665, abs=1e-3)
    assert layer["cu"] == pytest.approx(0.5 * 98.0665, abs=1e-3)
    assert layer["E"] == pytest.approx(100 * 0.0980665, abs=1e-3)
    csv = write(
        tmp_path / "tsf.csv",
        "Borehole,Top,Bottom,Soil type,cu (tsf),Unit weight (pcf)\nBH-1,0,5,clay,1,120\n",
    )
    layer = json.loads(import_soil(csv)["text"])["boreholes"][0]["layers"][0]
    assert layer["cu"] == pytest.approx(95.76)
    assert layer["unitWeight"] == pytest.approx(18.85, rel=1e-3)
    # A unit that is not understood, a density without its unit, a density as a unit weight.
    csv = write(
        tmp_path / "bad.csv",
        "Borehole,Top,Bottom,Soil type,cu (bar),Bulk density,phi\nBH-1,0,5,clay,1,1.8,30\n",
    )
    problems = import_soil(csv)["problems"]
    assert any(p.startswith("row 1: cu (bar): unknown unit 'bar'") for p in problems)
    assert any(p.startswith("row 1: Bulk density: give the unit") for p in problems)
    csv = write(
        tmp_path / "low.csv",
        "Borehole,Top,Bottom,Soil type,Unit weight\nBH-1,0,5,clay,1.8\n",
    )
    problems = import_soil(csv)["problems"]
    assert any(p.startswith("row 2 (BH-1): Unit weight: 1.8 kN/m³ is too low") for p in problems)
