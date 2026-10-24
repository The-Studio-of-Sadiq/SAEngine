"""The temperature case T, soil springs and MEP coordination wired through the whole project: the
derivation (as the RPC derives it), the run, the combinations, the result views, the design, the
foundation loads, the bill of quantities, the IFC and the report, on a copy of the shipped sample.

The soil is synthetic: one uniform sand layer (γ = 18 kN/m³) with SPT N = 10 every 1.5 m. Its
7 MEP (:data:`EQUIPMENT_MEP`) has a 60 kN overhead tank (8 kN empty) on a 150 mm C20.7 plinth on
S2 and a Ø100 sleeve in B1.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import ifcopenshell
import numpy as np
import pytest

from saengine.fem import ssi_compare
from saengine.fem.combinations import combination_results
from saengine.fem.display import _elements, element_section_forces, result_view
from saengine.fem.thermal import end_force_corrections, load_corrections, write_corrections
from saengine.library.settings import strength_combinations
from saengine.rpc import handlers
from saengine.verification.cases.common import run_model

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"
G = 9.80665
SOIL = {
    "schema": "saengine.soilReport/1",
    "boreholes": [
        {
            "id": "BH1",
            "x": 6500,
            "y": 2500,
            "depth": 30000,
            "layers": [
                {
                    "top": 0,
                    "bottom": 30000,
                    "description": "Uniform medium dense sand (synthetic)",
                    "soilType": "sand",
                    "unitWeight": 18.0,
                }
            ],
            "spt": [{"depth": 1500 * k, "N": 10} for k in range(1, 21)],
        }
    ],
}


def _read(root: Path, relative: str) -> str:
    return (root / relative).read_text(encoding="utf-8")


#: The 7 MEP these tests are written for (the sample's before its plumbing set-up): an equipment
#: tank and a sleeve. The sample's own plumbing is tested in test_plumbing_integration.py.
EQUIPMENT_MEP = {
    "schema": "saengine.mep/1",
    "equipment": [
        {
            "id": "EQ1",
            "name": "Overhead water tank",
            "kind": "tank",
            "story": "L1",
            "x": 9500,
            "y": 2500,
            "length": 2500,
            "width": 2000,
            "height": 1800,
            "operatingWeight": 60,
            "emptyWeight": 8,
            "plinth": {"material": "C20.7", "height": 150},
        }
    ],
    "openings": [
        {
            "id": "OP1",
            "host": "B1",
            "kind": "sleeve",
            "shape": "circle",
            "diameter": 100,
            "position": {"distance": 2000, "elevation": 250},
            "service": "DN100 drain",
        }
    ],
    "shafts": [],
    "ifcModels": [],
}


def _project(tmp_path: Path, **analysis: object) -> Path:
    """A copy of the sample with the synthetic soil, :data:`EQUIPMENT_MEP` and the analysis
    settings ``analysis``."""
    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    (root / "01 Soil Report" / "soil-report.json").write_text(json.dumps(SOIL), encoding="utf-8")
    (root / "07 MEP" / "mep.json").write_text(json.dumps(EQUIPMENT_MEP), encoding="utf-8")
    path = root / "02 Project Settings" / "project-settings.json"
    settings = json.loads(path.read_text(encoding="utf-8"))
    settings["analysis"] = {**settings.get("analysis", {}), "responseSpectrum": False, **analysis}
    if analysis.get("thermal"):
        settings["combinations"] = [
            c.model_dump(mode="json") for c in strength_combinations(thermal=True)
        ]
    path.write_text(json.dumps(settings), encoding="utf-8")
    return root


def _derive(root: Path) -> dict:
    """The derivation as the workbench asks for it (the soil, MEP and substructure read beside)."""
    result = handlers.derive_fem(
        _read(root, "06 BIM/bim.json"),
        _read(root, "04 Objects/objects.json"),
        _read(root, "03 Materials/materials.json"),
        _read(root, "02 Project Settings/project-settings.json"),
        str(root / "08 FEM"),
    )
    assert "text" in result, result.get("problems")
    return result


def _run(root: Path, result: dict, types: tuple[str, ...] = ("Static",)) -> tuple[Path, Path]:
    """Writes the model and its side files as the workbench does, and runs ``types``."""
    folder = root / "08 FEM"
    folder.mkdir(exist_ok=True)
    for name, key in (("thermal.json", "thermalText"), ("ssi.json", "ssiText")):
        if key in result:
            (folder / name).write_text(result[key], encoding="utf-8")
    project = json.loads(result["text"])
    ids = [a["id"] for a in project["analyses"] if a["type"] in types]
    model, out, _ = run_model(project, folder, ids)
    return model, out


def _vertical(project: dict, case: str) -> float:
    pattern = next((p for p in project["load_patterns"] if p["name"] == case), None)
    return -sum(n["forces"][2] for n in pattern["nodal_loads"]) / 1e3 if pattern else 0.0


# ───────────────────────────────── temperature ─────────────────────────────────


def test_temperature_case_through_combinations_views_and_design(tmp_path: Path) -> None:
    root = _project(tmp_path, thermal={"enabled": True, "uniform": 20, "gradient": 10})
    result = _derive(root)
    project = json.loads(result["text"])
    names = [a["name"] for a in project["analyses"]]
    assert "T: Temperature" in names
    # The other cases keep their numbers: D .. EY, then F (the sample's tank); T comes after.
    assert names[:9] == [
        "D: Dead (self-weight)",
        "SD: Superimposed dead (finishes, partitions)",
        "L: Live",
        "Lr: Roof live",
        "WX: Wind in X",
        "WY: Wind in Y",
        "EX: Earthquake in X",
        "EY: Earthquake in Y",
        "F: Fluids (equipment contents)",
    ]
    t_case = next(a for a in project["analyses"] if a["name"] == "T: Temperature")
    assert t_case["release_diaphragms"] is True  # the sample has rigid diaphragms
    corrections = json.loads(result["thermalText"])
    assert corrections["frames"]  # the roof's beams (the sample's highest floor, 3.2 m)
    model, out = _run(root, result)
    assert load_corrections(model) == corrections

    # The combination with +T is formed with T's fixed-end forces added back.
    from opensees_studio.services.result_store import load_manifest, load_results

    from saengine.fem.combinations import settings_beside

    settings = settings_beside(model)
    entries = {e["caseName"]: e for e in combination_results(out, project, settings, corrections)}
    rising = entries["1.2D + 1.2T + 1.6L + 0.5Lr"]
    assert not rising["warnings"]
    by_code = {
        str(e["case_name"]).split(":")[0]: load_results(e, out) for e in load_manifest(out)["cases"]
    }
    beam = next(e for e in project["elements"] if e["name"] == "B1")
    f0 = end_force_corrections(corrections, "T")[beam["id"]]
    factors = {"D": 1.2, "SD": 1.2, "L": 1.6, "Lr": 0.5, "T": 1.2, "F": 1.2}
    expected = sum(
        f * (np.asarray(by_code[c].element_forces[beam["id"]][-1], dtype=float)[:12]
             + (f0 if c == "T" else 0.0))
        for c, f in factors.items()
        if c in by_code
    )  # fmt: skip
    rows = {
        (r[0], r[1]): r[2:]
        for r in next(t for t in rising["tables"] if t["name"] == "Element forces")["rows"]
    }
    assert rows[("B1", "i")] == pytest.approx(np.round(expected[:6], 1).tolist(), abs=0.2)

    # The 3D view of T shows the true member forces: the analysis's plus the fixed-end forces.
    key = next(e for e in load_manifest(out)["cases"] if e["case_name"].startswith("T:"))
    view = result_view(out, model, f"case:{key['case_id']}")
    shown = next(e for e in view["elements"] if e["id"] == beam["id"])["forces"][0]
    element = next(e for e in _elements(project) if e.id == beam["id"])
    raw = np.asarray(by_code["T"].element_forces[beam["id"]][-1], dtype=float)[:12]
    true = element_section_forces(element, raw + f0, np.zeros(3))[0]
    assert shown == pytest.approx(true.tolist(), abs=1e-2)
    without = element_section_forces(element, raw, np.zeros(3))[0]
    assert abs(true[0] - without[0]) > 1e3  # the held axial force matters (N)

    # The design checks the members under the T combinations too.
    from saengine.design.check import _demands

    checked, _, notes, _ = _demands(project, out, settings)
    assert "1.2D + 1.2T + 1.6L + 0.5Lr" in checked
    assert not [n for n in notes if "T" in n.split(":")[0]]


# ───────────────────────────────── soil springs ─────────────────────────────────


def test_soil_springs_compared_with_the_fixed_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path, supports="soilSprings")
    result = _derive(root)
    project = json.loads(result["text"])
    springs = json.loads(result["ssiText"])
    assert [s["foundation"] for s in springs["springs"]] == ["F1"]  # the sample's footing of C1
    assert any(e["type"] == "ZeroLength" for e in project["elements"])
    assert "substructure=" in project["meta"]["description"]
    _run(root, result, ("Static", "Modal"))

    # A relative project root works too (the fixed-base run's working folder is the model's).
    monkeypatch.chdir(tmp_path)
    comparison = ssi_compare.compare(Path(root.name))
    # Springs under C1 only (the wall and the other columns stay fixed): the first period
    # lengthens a little, never shortens.
    first = comparison["periods"][0]
    assert first["ssi"] > first["fixed"] and first["ratio"] > 1.0
    shears = {b["case"]: b for b in comparison["baseShear"]}
    assert shears["EX"]["ssi"] == pytest.approx(shears["EX"]["fixed"], rel=1e-3)  # same loads
    assert {d["level"] for d in comparison["storeyDrift"]} <= {3.2, 6.4, 10.0}
    assert json.loads(_read(root, "08 FEM/ssi-compare.json"))["periods"] == comparison["periods"]
    fixed = json.loads(_read(root, "08 FEM/model-fixed.osmodel"))
    # No soil springs (the steel brace M2's pinned-end links, "M2/pin", stay in both models).
    links = [e["name"] for e in fixed["elements"] if e["type"] == "ZeroLength"]
    assert all(name.split("#")[0].endswith("/pin") for name in links)

    # The foundations are designed from the fixed-base run (supports at the column bases).
    from saengine.substructure.context import load_context

    context = load_context(root)
    assert context.loads is not None and "C1" in context.loads.bases
    assert context.out_dir == root / "08 FEM" / "model-fixed.results"

    # The report states the support assumption, with the periods.
    from saengine.library.settings import ProjectSettings
    from saengine.report.build import _supports_text

    settings = ProjectSettings.model_validate_json(
        _read(root, "02 Project Settings/project-settings.json")
    )
    text = _supports_text(root, settings.analysis)
    assert "Soil springs" in text and "First period" in text
    assert ssi_compare.read_comparison(root)["stale"] is False

    # Run again after the comparison (outside Run All): the comparison is out of date, and the
    # report no longer quotes its periods as current.
    manifest = root / "08 FEM" / "model.results" / "manifest.json"
    later = (root / "08 FEM" / "ssi-compare.json").stat().st_mtime + 10
    os.utime(manifest, (later, later))
    assert ssi_compare.read_comparison(root)["stale"] is True
    text = _supports_text(root, settings.analysis)
    assert "First period" not in text and "older than the analysis model" in text


def test_foundations_wait_for_the_fixed_base_run(tmp_path: Path) -> None:
    root = _project(tmp_path, supports="soilSprings")
    result = _derive(root)
    _run(root, result)
    from saengine.substructure.context import load_context

    context = load_context(root)
    assert context.loads is None and "fixed-base run" in context.no_loads


# ───────────────────────────────── MEP coordination ─────────────────────────────────


def test_mep_in_the_model_the_bill_and_the_ifc(tmp_path: Path) -> None:
    root = _project(tmp_path)
    result = _derive(root)
    project = json.loads(result["text"])
    assert "mep=" in project["meta"]["description"]
    # The tank's water (52 kN) is the fluid case F; its empty weight (8 kN) and the plinth
    # (2.5 x 2.0 x 0.15 m of 2400 kg/m³ concrete = 17.65 kN) are superimposed dead load SD.
    assert _vertical(project, "F") == pytest.approx(52.0, abs=1e-3)
    bare = handlers.derive_fem(
        _read(root, "06 BIM/bim.json"),
        _read(root, "04 Objects/objects.json"),
        _read(root, "03 Materials/materials.json"),
        _read(root, "02 Project Settings/project-settings.json"),
        str(root / "08 FEM"),
        mep_text='{"schema": 1, "part": "mep"}',
    )
    plinth = 2.5 * 2.0 * 0.15 * 2400 * G / 1e3
    sd = _vertical(project, "SD") - _vertical(json.loads(bare["text"]), "SD")
    assert sd == pytest.approx(8.0 + plinth, abs=1e-3)

    # Bill of quantities: the plinth's concrete and formwork, the sleeve counted.
    boq = json.loads(
        handlers.compute_boq(
            _read(root, "06 BIM/bim.json"),
            _read(root, "04 Objects/objects.json"),
            _read(root, "03 Materials/materials.json"),
            _read(root, "09 Substructure/substructure.json"),
            _read(root, "02 Project Settings/project-settings.json"),
            _read(root, "07 MEP/mep.json"),
        )["text"]
    )
    items = {(i["group"], i.get("kind")): i for i in boq["items"]}
    assert items[("concrete", "plinth")]["quantity"] == pytest.approx(0.75)
    assert items[("formwork", "plinth")]["quantity"] == pytest.approx(2 * 4.5 * 0.15)
    sleeves = items[("mep", "sleeve")]
    assert (sleeves["quantity"], sleeves["unit"], sleeves["code"]) == (1.0, "nr", "P.01")
    assert boq["source"]["mep"]

    # IFC: the tank (IfcTank) on its plinth, the sleeve voiding B1.
    ifc = handlers.building_ifc(
        _read(root, "06 BIM/bim.json"),
        _read(root, "04 Objects/objects.json"),
        _read(root, "03 Materials/materials.json"),
        "Sample",
        mep_text=_read(root, "07 MEP/mep.json"),
    )
    path = tmp_path / "model.ifc"
    path.write_text(ifc["text"], encoding="utf-8")
    model = ifcopenshell.open(str(path))
    (tank,) = model.by_type("IfcTank")
    assert (tank.Name, tank.Tag) == ("Overhead water tank", "EQ1")
    assert [p.ObjectType for p in model.by_type("IfcBuildingElementProxy")] == ["Plinth"]
    voids = {
        r.RelatedOpeningElement.Name: r.RelatingBuildingElement.Name
        for r in model.by_type("IfcRelVoidsElement")
    }
    assert voids["OP1"] == "B1"
    assert "EQ1" in ifc["ids"] and "OP1" in ifc["ids"]


def test_mep_report_and_chapter(tmp_path: Path) -> None:
    root = _project(tmp_path)
    _run(root, _derive(root))
    report = handlers.mep_report(str(root))
    (tank,) = report["equipment"]
    assert tank["loads"]["F"] == pytest.approx(52.0)
    (sleeve,) = report["openings"]
    assert sleeve["id"] == "OP1" and sleeve["checked"] and sleeve["ok"]
    assert handlers.mep_report(str(root), mep_text="{")["problems"]

    from saengine.report.build import report_data

    data = report_data(root)
    chapter = data["mep"]
    assert chapter["available"]
    assert chapter["equipment"][0][:4] == ["EQ1", "Overhead water tank", "L1", "S2"]
    assert chapter["openings"][0][0] == "OP1" and chapter["openings"][0][-1] == "OK"
    modelling = dict(data["basis"]["modelling"])
    assert modelling["Column supports"].startswith("Fixed")
    assert modelling["Temperature case T"] == "Off"
    assert "F" in data["basis"]["combinations"]["columns"]


def test_chapter_marks_openings_whose_strength_is_not_checked(tmp_path: Path) -> None:
    """Without analysis results OP1 passes its size check only: the chapter says so, not OK."""
    from saengine.report.build import _mep, _Parts, opening_strength_checked

    root = _project(tmp_path)
    chapter = _mep(_Parts(root, []))
    assert chapter["openings"][0][0] == "OP1"
    assert chapter["openings"][0][-1] == "Size OK, strength not checked"
    assert chapter["partial"] == 1 and chapter["openingFails"] == [False]
    assert "1 strength not checked" in dict(chapter["summary"])["Sleeves and openings"]
    # The backend's own flag wins over the note wording.
    assert opening_strength_checked({"checked": True, "notes": ["(no results)"]}) is False
    assert opening_strength_checked({"checked": True, "strengthChecked": True, "notes": ["x"]})
    assert opening_strength_checked({"checked": True, "notes": []})


def test_mep_stamp_matches_the_workbench(tmp_path: Path) -> None:
    """The analysis model records the stamp of what it takes from 7 MEP: an IFC model's entry
    or a label does not make it stale; moving equipment does. The same text and stamp are in
    femDerivationBar.test.ts (the workbench's mepModelStamp)."""
    from saengine.fem.derive import mep_stamp, stamp

    text = (
        '{"schema": "saengine.mep/1", "contentsAs": "fluid", "equipment": [{"id": "EQ1", '
        '"name": "Tank Ø2", "x": 1.0, "y": 2500.5, "operatingWeight": 1e-7, "impact": '
        '0.000001, "rotation": 2.5e22, "big": 1e21, "neg": -0.0}], "openings": [{"id": "OP1", '
        '"service": "DN100 drain", "diameter": 100}], "shafts": [], "ifcModels": [{"path": '
        '"07 MEP/a.ifc", "visible": true}]}'
    )
    assert mep_stamp(text) == "27130defec6c8086d3157e357806649a4ec265d2"
    relabelled = text.replace("Tank Ø2", "Roof tank").replace('"visible": true', '"visible": false')
    assert mep_stamp(relabelled) == mep_stamp(text)
    assert mep_stamp(text.replace("2500.5", "2600")) != mep_stamp(text)
    assert mep_stamp("{") == stamp("{")

    # The derivation records it, so adding an MEP IFC model leaves the model current.
    root = _project(tmp_path)
    description = json.loads(_derive(root)["text"])["meta"]["description"]
    mep = json.loads(_read(root, "07 MEP/mep.json"))
    mep["ifcModels"] = [{"path": "07 MEP/HVAC.ifc", "discipline": "mechanical"}]
    assert f"mep={mep_stamp(json.dumps(mep))}" in description


# ───────────────────────────────── roofs heated by T ─────────────────────────────────


def _flat_project(
    nodes: dict[int, tuple[float, float, float]], elements: list[tuple[int, str, list[int]]]
) -> dict:
    return {
        "nodes": [{"id": n, "coords": list(xyz)} for n, xyz in nodes.items()],
        "sections": [
            {
                "id": 1,
                "type": "ElasticSection",
                "E": 25e9,
                "A": 0.15,
                "Iy": 3.125e-3,
                "Iz": 1.125e-3,
                "G": 1e10,
                "J": 1e-3,
            },
            {"id": 2, "type": "ElasticMembranePlateSection", "E": 25e9, "nu": 0.2, "h": 0.15},
        ],
        "elements": [
            {
                "id": i,
                "name": f"E{i}",
                "type": kind,
                "nodes": ns,
                "section_id": 1 if kind[0] == "E" else 2,
            }
            for i, kind, ns in elements
        ],
        "mp_constraints": [],
        "load_patterns": [],
        "analyses": [],
        "time_series": [],
    }


def test_every_roof_is_heated_not_only_the_highest() -> None:
    """A 10 m main-roof beam at 10 m and a 3 m stair-room roof beam at 13 m (the reviewer's
    case): both are roofs. Of the main roof slab, the panel under the stair room's roof slab is
    not; nor the floor below, nor the beam under the stair room's edge beam."""
    from saengine.fem.thermal import (
        ThermalOptions,
        ThermalSection,
        add_thermal_case,
        exposed_elements,
    )

    beam, shell = "ElasticBeamColumn", "Shell"
    nodes = {
        1: (0, 0, 10),
        2: (10, 0, 10),  # main roof beam
        3: (0, 5, 13),
        4: (3, 5, 13),  # stair-room roof beam (away from beam 1 in plan)
        5: (0, 0, 13),
        6: (3, 0, 13),
        7: (0, 0, 10.0),
        8: (3, 0, 10.0),  # edge beam over beam 4
        11: (0, 0, 10),
        12: (3, 0, 10),
        13: (3, 5, 10),
        14: (0, 5, 10),
        15: (10, 0, 10),
        16: (10, 5, 10),  # main roof slab panels: x 0..3 (under the stair room), x 3..10
        21: (0, 0, 13),
        22: (3, 0, 13),
        23: (3, 5, 13),
        24: (0, 5, 13),  # stair-room roof slab
        31: (0, 0, 7),
        32: (10, 0, 7),
        33: (10, 5, 7),
        34: (0, 5, 7),  # floor below
    }
    project = _flat_project(
        nodes,
        [
            (1, beam, [1, 2]),
            (2, beam, [3, 4]),
            (3, beam, [5, 6]),
            (4, beam, [7, 8]),
            (10, shell, [11, 12, 13, 14]),
            (11, shell, [12, 15, 16, 13]),
            (12, shell, [21, 22, 23, 24]),
            (13, shell, [31, 32, 33, 34]),
        ],
    )
    assert exposed_elements(project) == {1, 2, 3, 11, 12}
    sections = {1: ThermalSection(1e-5, 0.5), 2: ThermalSection(1e-5, 0.15)}
    case = add_thermal_case(
        project, sections, ThermalOptions(20, 10, "roof"), roof_elements=exposed_elements(project)
    )
    assert sorted(case.corrections["frames"]) == ["1", "2", "3"]
    assert sorted(case.corrections["shells"]) == ["11", "12"]
    assert case.corrections["roofLevels"] == [10.0, 13.0]
    assert any("10.00, 13.00 m" in n for n in case.notes)
    # Without the roof elements the old rule stands: only the highest level.
    only_top = add_thermal_case(project, sections, ThermalOptions(20, 10, "roof"))
    assert sorted(only_top.corrections["frames"]) == ["2", "3"]


def test_invalid_mep_is_a_problem_of_the_derivation(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "07 MEP" / "mep.json").write_text(
        json.dumps({"schema": "saengine.mep/1", "equipment": [{"id": "EQ1"}]}), encoding="utf-8"
    )
    result = handlers.derive_fem(
        _read(root, "06 BIM/bim.json"),
        _read(root, "04 Objects/objects.json"),
        _read(root, "03 Materials/materials.json"),
        _read(root, "02 Project Settings/project-settings.json"),
        str(root / "08 FEM"),
    )
    assert result["problems"][0].startswith("MEP: ")


def test_write_corrections_round_trip(tmp_path: Path) -> None:
    model = tmp_path / "model.osmodel"
    write_corrections(model, {"schema": 1, "case": "T", "frames": {}, "shells": {}})
    assert load_corrections(model)["case"] == "T"
    write_corrections(model, None)
    assert load_corrections(model) is None
