"""Import of borehole logs from CSV and Excel, and the import template."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saengine.library.soil import SoilReport
from saengine.soil import import_soil, soil_template
from saengine.soil.importer import EXAMPLE, EXAMPLE_ID, parse_rows, read_rows, soil_type_of


def write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_template_round_trip_csv_and_xlsx(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    for suffix in ("csv", "xlsx"):
        target = tmp_path / f"template.{suffix}"
        assert soil_template(str(target)) == {"path": str(target)}
        boreholes, problems, _ = parse_rows(read_rows(target))
        assert not problems, problems
        report = SoilReport.model_validate({"boreholes": boreholes})
        (hole,) = report.boreholes
        assert hole.id == EXAMPLE_ID and hole.waterTable == 1500 and hole.depth == 15000
        assert [layer.soilType for layer in hole.layers] == ["fill", "clay", "sand"]
        assert hole.layers[1].cu == 25 and hole.layers[1].bottom == 6000
        assert len(hole.spt) == sum(1 for e in EXAMPLE if e["record"] == "spt")
        assert hole.samples[0].plasticLimit == 23 and hole.samples[0].type == "UD"
        # N-S10: the log sheet's header and SPT columns come through the template too.
        assert hole.date == "2026-01-15" and hole.method == "Wash boring"
        last = hole.spt[-1]
        assert (last.depthTo, last.seat, last.N1, last.N2, last.recovery) == (15450, 12, 13, 15, 80)
        assert last.sampleNumber == "D-10"


def test_position_date_method_refusal_and_recovery(tmp_path: Path) -> None:
    """N-S10: lat/long, BTM, date, method, SPT to, refusal and recovery columns (synthetic log)."""
    csv = write(
        tmp_path / "log.csv",
        "Borehole,Latitude,Longitude,Date,Method,Depth (m),SPT to (m),N1,N2,Refusal,Recovery (%)\n"
        "BH-7,23.80001,90.40002,2026-02-01,Wash boring,1.5,1.95,3,4,,70\n"
        "BH-7,,,,,3.0,,30,,50/100,40\n"
        "BH-7,,,,,4.5,,50,,R,\n"
        "BH-8,,,,,1.5,,2,2,maybe,\n"
        "BH-9,,,2026-02-02,,1.5,,2,2,,\n"
        "BH-9,,,2026-02-03,,3.0,,2,2,,\n",
    )
    boreholes, problems, _ = parse_rows(read_rows(csv))
    assert problems == [
        "row 5 (BH-8): Refusal: 'maybe' is not R (or yes) nor blows/penetration as 50/100",
        "row 7 (BH-9): Date: '2026-02-03' differs from '2026-02-02' on row 6",
    ]
    hole = SoilReport.model_validate({"boreholes": [boreholes[0]]}).boreholes[0]
    assert (hole.lat, hole.lon, hole.date, hole.method) == (
        23.80001,
        90.40002,
        "2026-02-01",
        "Wash boring",
    )
    assert [(r.depth, r.depthTo, r.recovery) for r in hole.spt] == [
        (1500, 1950, 70),
        (3000, None, 40),
        (4500, None, None),
    ]
    assert hole.spt[1].refusal is not None and hole.spt[1].refusal.blows == 50
    assert hole.spt[2].refusal is True
    btm = write(
        tmp_path / "btm.csv",
        "Borehole,BTM easting,BTM northing,Depth,N\nBH-1,540123.4,2633456.7,1.5,4\n",
    )
    (only,), problems, _ = parse_rows(read_rows(btm))
    assert not problems and (only["easting"], only["northing"]) == (540123.4, 2633456.7)


def test_template_example_is_not_imported(tmp_path: Path) -> None:
    # S1: the example used to be BH-1 and silently replaced the project's own BH-1.
    target = tmp_path / "template.csv"
    soil_template(str(target))
    (problem,) = import_soil(str(target), None)["problems"]
    assert EXAMPLE_ID in problem and "not imported" in problem
    # The engineer's own BH-1 under the example.
    header = [str(c) for c in read_rows(target)[0][1]]
    line = dict.fromkeys(header, "")
    line.update({header[0]: "BH-1", header[1]: "layer"})
    top = next(h for h in header if h.startswith("Top"))
    bottom = next(h for h in header if h.startswith("Bottom"))
    kind = next(h for h in header if h.startswith("Soil type"))
    line.update({top: "0", bottom: "8", kind: "clay"})
    text = target.read_text(encoding="utf-8-sig").splitlines()
    text.append(",".join(line[h] for h in header))
    target.write_text("\n".join(text) + "\n", encoding="utf-8")
    existing = json.dumps(
        {"boreholes": [{"id": "BH-1", "layers": [{"top": 0, "bottom": 5000, "soilType": "sand"}]}]}
    )
    result = import_soil(str(target), existing)
    report = SoilReport.model_validate_json(result["text"])
    assert [b.id for b in report.boreholes] == ["BH-1"]
    assert report.boreholes[0].layers[0].bottom == 8000
    assert f"{EXAMPLE_ID}: the template's example, not imported." in result["notes"]


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
