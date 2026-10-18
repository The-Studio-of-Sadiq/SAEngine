"""The MEP report end to end on the sample project: the equipment and openings in the analysis
model the derivation builds, the analysis run, the openings checked."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from saengine.fem.derive import derive_fem
from saengine.library.bim import BuildingModel
from saengine.library.materials import MaterialLibrary
from saengine.library.mep import parse
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import ProjectSettings
from saengine.mep import mep_report

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"

MEP = {
    "schema": "saengine.mep/1",
    "equipment": [
        {
            "id": "EQ1",
            "name": "Water tank",
            "kind": "tank",
            "story": "L1",
            "x": 3000,
            "y": 1500,
            "length": 1500,
            "width": 1000,
            "operatingWeight": 50,
            "emptyWeight": 5,
        }
    ],
    "openings": [
        {
            "id": "OP1",
            "host": "B1",
            "kind": "sleeve",
            "shape": "circle",
            "diameter": 100,
            "position": {"distance": 3000, "elevation": 250},
            "service": "DN80 drain",
        },
        {
            "id": "OP2",
            "host": "S2",
            "kind": "opening",
            "shape": "rectangle",
            "width": 400,
            "height": 400,
            "position": {"x": 9500, "y": 2500},
        },
        {
            "id": "OP3",
            "host": "W1",
            "kind": "opening",
            "shape": "rectangle",
            "width": 600,
            "height": 400,
            "position": {"x": 3500, "y": 2500},
        },
    ],
}


@pytest.fixture(scope="module")
def analysed(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    root = tmp_path_factory.mktemp("mep") / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    (root / "07 MEP" / "mep.json").write_text(json.dumps(MEP), encoding="utf-8")

    def read(relative: str) -> str:
        return (root / relative).read_text(encoding="utf-8")

    settings = ProjectSettings.model_validate_json(
        read("02 Project Settings/project-settings.json")
    )
    materials = MaterialLibrary.model_validate_json(read("03 Materials/materials.json"))
    objects = ObjectLibrary.model_validate_json(read("04 Objects/objects.json"))
    building = BuildingModel.model_validate_json(read("06 BIM/bim.json"))
    mep = parse(read("07 MEP/mep.json"))
    settings = settings.model_copy(
        update={"analysis": settings.analysis.model_copy(update={"responseSpectrum": False})}
    )

    # The derivation cuts the openings from the building model and puts the equipment on its
    # nodes and shells.
    # The openings alone also take the finishes off the opening OP2 (0.16 m² of S2).
    bare = mep.model_copy(update={"equipment": []})
    plain = derive_fem(building, objects, materials, settings, mep=bare).project
    before = {case: _vertical(plain, case) for case in ("SD", "L", "F")}
    derivation = derive_fem(building, objects, materials, settings, mep=mep)
    project = derivation.project
    model = root / "08 FEM" / "model.osmodel"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_text(json.dumps(project), encoding="utf-8")
    static = [a["id"] for a in project["analyses"] if a.get("type", "Static") == "Static"]
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *map(str, static),
            "--out",
            str(root / "08 FEM" / "model.results"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    after = {case: _vertical(project, case) for case in ("SD", "L", "F")}
    return root, {"before": before, "after": after, "project": project}


def _vertical(project: dict, case: str) -> float:
    pattern = next((p for p in project["load_patterns"] if p["name"] == case), None)
    if pattern is None:
        return 0.0
    return -sum(load["forces"][2] for load in pattern["nodal_loads"]) / 1e3


def test_equipment_goes_into_the_model(analysed) -> None:
    _, data = analysed
    # 50 kN of tank on the shells of S1: 5 kN empty (SD) and 45 kN of water, the fluid load F
    # in its own case (not SD: the 0.9D combinations must not count it).
    assert data["after"]["SD"] - data["before"]["SD"] == pytest.approx(5.0, abs=1e-4)
    assert data["after"]["F"] - data["before"]["F"] == pytest.approx(45.0, abs=1e-4)
    assert data["after"]["L"] == pytest.approx(data["before"]["L"], abs=1e-6)
    assert data["before"]["F"] == 0.0  # without MEP the model has no case F
    names = [a["name"] for a in data["project"]["analyses"]]
    assert names[:9][-1].startswith("F: ")


def test_report_checks_the_openings_with_the_analysis(analysed) -> None:
    root, _ = analysed
    report = mep_report(root)
    json.dumps(report)  # JSON-ready
    (tank,) = report["equipment"]
    assert tank["loads"] == {"SD": 5.0, "F": 45.0}
    assert tank["slabs"] == ["S1"]
    assert tank["seismicWeight"] == 50.0
    assert (tank["load"], tank["loadCase"], tank["host"]) == (50.0, "SD + F", "S1")
    assert tank["pressure"] == pytest.approx(50 / 1.5, abs=1e-3)  # kPa over 1.5 x 1.0 m
    assert report["stories"] == [{"story": "L1", "count": 1, "load": 50.0}]
    openings = {o["id"]: o for o in report["openings"]}
    beam = {c["name"]: c for c in openings["OP1"]["checks"]}
    shear = beam["Shear at the opening (net section)"]
    assert shear["demand"] > 0 and shear["combination"]
    assert shear["capacity"] > shear["demand"]
    assert "Flexure at the opening (sagging)" in beam
    assert openings["OP1"]["ok"]
    assert openings["OP1"]["check"] == "Sleeve size (h/3, SAEngine practice limit)"  # 100 / 166.7
    slab = openings["OP2"]
    assert slab["hostKind"] == "slab" and slab["checked"]
    wall = {c["name"]: c for c in openings["OP3"]["checks"]}
    assert wall["Wall length removed at the opening"]["flag"]
    assert report["summary"]["openings"] == 3
    assert report["summary"]["loads"] == {"SD": 5.0, "F": 45.0}
    assert report["clashes"] == []
