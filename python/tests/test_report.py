"""The printed design report (Part 11 Exports) of an analysed one-bay frame."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_design import GRAVITY, reinforced
from test_fem_derive import PLAN, SETTINGS

from saengine.boq import compute_boq
from saengine.fem.derive import derive_fem, stamp
from saengine.library import default_material_library
from saengine.library.bim import generate
from saengine.library.settings import LoadCombination
from saengine.report import build_report, report_data
from saengine.report.build import count_pages, fmt, project_name

#: Typst markup characters in the project's name: they must be printed, not interpreted.
NAME = 'Bay #1 $x$ *bold* _it_ @ref <lbl> [b] \\ "q" // c'

#: A combination far beyond the frame's strength, so that the beams fail.
OVERLOAD = LoadCombination(name="Overload 12D + 16L", D=12.0, L=16.0, Lr=5.0)


def _write(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The one-bay frame as a project folder with its manifest, analysed (all cases, modal and
    response spectrum included) and with its bill of quantities computed."""
    root = tmp_path_factory.mktemp("report")
    settings = SETTINGS.model_copy(update={"combinations": [GRAVITY, OVERLOAD]})
    building = generate(PLAN, "s")
    materials = default_material_library()
    objects = reinforced()
    texts = {
        "settings": settings.model_dump_json(by_alias=True),
        "materials": materials.model_dump_json(by_alias=True),
        "objects": objects.model_dump_json(by_alias=True),
        "bim": building.model_dump_json(by_alias=True),
    }
    d = derive_fem(
        building,
        objects,
        materials,
        settings,
        {key: stamp(text) for key, text in texts.items()},
    )
    boq = compute_boq(texts["bim"], texts["objects"], texts["materials"])
    _write(
        root,
        {
            "project.saengine": json.dumps({"schema": 1, "name": NAME, "parts": []}),
            "02 Project Settings/project-settings.json": texts["settings"],
            "03 Materials/materials.json": texts["materials"],
            "04 Objects/objects.json": texts["objects"],
            "06 BIM/bim.json": texts["bim"],
            "08 FEM/model.osmodel": json.dumps(d.project),
            "10 BOQ/boq.json": json.dumps(boq),
        },
    )
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(root / "08 FEM" / "model.osmodel"),
            "--cases",
            *(str(a["id"]) for a in d.project["analyses"]),
            "--out",
            str(root / "08 FEM" / "model.results"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    return root


@pytest.fixture(scope="module")
def data(project: Path) -> dict:
    return report_data(project, version="9.9.9")


def test_report_data_of_the_frame(data: dict) -> None:
    json.dumps(data, allow_nan=False)  # what the template receives
    assert data["meta"]["project"] == NAME
    assert data["meta"]["version"] == "9.9.9"
    assert data["meta"]["code"] == "BNBC 2020 Part 6 Chapter 6"
    basis = data["basis"]
    assert any(row[0] == "C24.1" for row in basis["materials"])
    assert any(row[0] == "B420DWR" and row[3].startswith("fy = 420") for row in basis["materials"])
    assert [row[0] for row in basis["combinations"]["rows"]] == [GRAVITY.name, OVERLOAD.name]
    assert basis["combinations"]["columns"] == ["D", "L", "Lr"]
    assert {"Linear static", "Modal (eigenvalue)", "Response spectrum"} <= set(basis["analyses"])
    assert basis["cases"][:2] == [
        ["D", "Dead (self-weight)"],
        ["SD", "Superimposed dead (finishes, partitions)"],
    ]

    # The model is current: its derivation's values are recomputed.
    model = data["model"]
    assert dict(model["rows"])["Nodes"] == "9"
    derived = dict(model["derived"])
    assert "Equivalent static base shear V" in derived
    assert all(row[3] == "Complete" for row in model["run"])

    results = data["results"]
    modal = results["modal"]
    assert modal["columns"][:3] == ["Mode", "T [s]", "f [Hz]"]
    assert "Σ X [%]" in modal["columns"] and len(modal["rows"]) >= 2
    reactions = {row[0]: row for row in results["reactions"]}
    dead = reactions["D: Dead (self-weight)"]
    assert float(dead[3].replace(",", "")) > 0  # upward reactions under the self-weight
    lateral = {row[0]: row for row in results["displacements"]}
    assert set(lateral) == {
        "WX: Wind in X",
        "WY: Wind in Y",
        "EX: Earthquake in X",
        "EY: Earthquake in Y",
    }
    ex = lateral["EX: Earthquake in X"]
    assert float(ex[1]) > 0 and float(ex[2]) > 0 and ex[4] != "–"
    assert lateral["WX: Wind in X"][4] == "–"  # Cd/I only for earthquakes


def test_member_design_marks_the_overloaded_beams(data: dict) -> None:
    design = data["design"]
    assert design["available"] and design["failed"] > 0
    tables = {t["kind"]: t for t in design["tables"]}
    assert ["column", "beam"] == [t["kind"] for t in design["tables"]]  # columns first
    beams = tables["beam"]
    assert beams["title"] == "Beams" and beams["count"] == 4
    for row, failing in zip(beams["rows"], beams["fails"], strict=True):
        assert failing == (row[-1] == "FAIL")
    assert any(row[-1] == "FAIL" and row[7] == OVERLOAD.name for row in beams["rows"])
    assert any("element(s) fail" in w for w in data["warnings"])
    assert design["method"] and any("ACI" in line for line in design["method"])
    assert len(design["details"]) == 8
    assert all(len(row) == 8 for e in design["details"] for row in e["rows"])
    # Verbatim in the limitations.
    assert data["limitations"]["design"] == design["notes"]


def test_any_element_kind_gets_a_table(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import saengine.design as design_module

    def fake(out_dir: Path, project_path: Path) -> dict:
        check = {
            "name": "Punching shear (ACI 22.6)",
            "demand": 510.0,
            "capacity": 400.0,
            "unit": "kN",
            "utilisation": 1.275,
            "combination": "1.2D + 1.6L",
            "ok": False,
            "note": "at the column face",
            "flag": False,
        }
        return {
            "code": "ACI 318-19",
            "method": ["m"],
            "combinations": ["1.2D + 1.6L"],
            "elements": [
                {
                    "id": "F1",
                    "kind": "footing",
                    "type": "FT",
                    "checks": [check],
                    "utilisation": 1.275,
                    "ok": False,
                },
                {
                    "id": "F2",
                    "kind": "footing",
                    "type": "FT",
                    "checks": [{**check, "utilisation": 1.004}],
                    "utilisation": 1.004,
                    "ok": False,
                },
                {
                    "id": "S1",
                    "kind": "slab",
                    "type": "SL",
                    "checks": [{**check, "ok": True, "utilisation": 0.5}],
                    "utilisation": 0.5,
                    "ok": True,
                },
                {
                    "id": "X1",
                    "kind": "retainingWall",
                    "type": "RW",
                    "checks": [],
                    "utilisation": 0.0,
                    "ok": True,
                },
            ],
            "skipped": [{"id": "C1", "kind": "column", "type": "COL", "reason": "no bars"}],
            "summary": {
                "checked": 3,
                "passed": 2,
                "failed": 1,
                "skipped": 1,
                "maxUtilisation": 1.275,
                "governing": "F1",
            },
            "notes": ["a note"],
        }

    monkeypatch.setattr(design_module, "design_report", fake)
    design = report_data(project)["design"]
    assert [t["title"] for t in design["tables"]] == ["Footings", "Slabs", "Retaining walls"]
    assert design["tables"][0]["rows"][0][-1] == "FAIL"
    # A marginal failure prints as checked (3 decimals), never as "1.00" beside FAIL.
    assert design["tables"][0]["rows"][1][6] == "1.004"
    assert design["tables"][0]["rows"][1][-1] == "FAIL"
    assert ["Largest utilisation", "1.275"] in design["summary"]
    assert design["details"][1]["title"].endswith("utilisation 1.004, FAIL")
    assert design["skipped"] == [["C1", "column", "COL", "no bars"]]


def test_bill_of_quantities(data: dict, project: Path) -> None:
    boq = data["boq"]
    assert boq["status"] == "ok"
    groups = {g["title"]: g for g in boq["groups"]}
    assert {"Concrete", "Reinforcement", "Formwork"} <= set(groups)
    concrete = groups["Concrete"]
    assert concrete["unit"] == "m³" and float(concrete["total"]) > 0
    stored = json.loads((project / "10 BOQ" / "boq.json").read_text(encoding="utf-8"))
    total = sum(i["quantity"] for i in stored["items"] if i["group"] == "concrete")
    assert concrete["total"] == fmt(total, 2)
    assert any("mm" in row[1] or "T" in row[1] for row in groups["Reinforcement"]["rows"])
    assert boq["notes"] == stored["notes"] and data["limitations"]["boq"] == stored["notes"]


def test_stale_or_missing_bill_of_quantities(project: Path, tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(project, copy)
    bim = copy / "06 BIM" / "bim.json"
    bim.write_text(bim.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
    data = report_data(copy)
    assert data["boq"]["status"] == "stale" and "06 BIM/bim.json" in data["boq"]["message"]
    # The model is stale too, from the same change.
    assert any("derived from earlier versions" in w for w in data["warnings"])
    assert data["model"]["derived"] == []

    (copy / "10 BOQ" / "boq.json").write_text('{"schema": 1, "part": "boq"}', encoding="utf-8")
    assert report_data(copy)["boq"]["status"] == "missing"
    (copy / "10 BOQ" / "boq.json").unlink()
    assert report_data(copy)["boq"]["status"] == "missing"


def test_build_report_writes_the_pdf(project: Path) -> None:
    result = build_report(project, version="9.9.9")
    assert "problems" not in result, result
    pdf = Path(result["path"])
    assert pdf == project / "11 Exports" / "report.pdf"
    content = pdf.read_bytes()
    assert content.startswith(b"%PDF")
    assert result["pages"] == count_pages(content) >= 6
    assert not [w for w in result["warnings"] if w.startswith("Typst")]
    if importlib.util.find_spec("pypdf") is not None:
        from pypdf import PdfReader

        text = "\n".join(page.extract_text() for page in PdfReader(str(pdf)).pages)
        assert "Bay #1 $x$ *bold* _it_ @ref <lbl> [b]" in text
        assert "FAIL" in text and "Total" in text

    other = build_report(project, project / "elsewhere" / "r.pdf")
    assert Path(other["path"]).read_bytes().startswith(b"%PDF")


def test_nothing_to_report(tmp_path: Path) -> None:
    assert "derive it first" in build_report(tmp_path)["problems"][0]
    _write(tmp_path, {"08 FEM/model.osmodel": json.dumps({"schema_version": 2, "meta": {}})})
    problems = build_report(tmp_path)["problems"]
    assert problems == ["There are no analysis results: run the analysis first."]
    assert not (tmp_path / "11 Exports" / "report.pdf").exists()


def test_project_name(tmp_path: Path) -> None:
    assert project_name(tmp_path) == tmp_path.name
    (tmp_path / "Tower A.saengine").write_text("{}", encoding="utf-8")
    assert project_name(tmp_path) == "Tower A"
    (tmp_path / "Tower A.saengine").write_text('{"name": "Tower #A"}', encoding="utf-8")
    assert project_name(tmp_path) == "Tower #A"


def test_project_name_matches_the_extension_case_insensitively(tmp_path: Path) -> None:
    # The workbench matches the manifest's extension case-insensitively; so does the report.
    (tmp_path / "Tower.SAENGINE").write_text('{"name": "T"}', encoding="utf-8")
    assert project_name(tmp_path) == "T"
    (tmp_path / "Tower.SAENGINE").write_text("{}", encoding="utf-8")
    assert project_name(tmp_path) == "Tower"


def test_formatting() -> None:
    assert fmt(None) == "–"
    assert fmt(1234.56, 1) == "1,234.6"
    assert fmt(-0.00001, 2) == "0.00"
    assert fmt(float("inf")) == "∞"
