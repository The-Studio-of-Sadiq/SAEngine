"""MEP clashes with the structure, MEP IFC import (synthetic IFC models, IfcOpenShell)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import numpy as np
import pytest

from saengine.library.mep import parse
from saengine.mep import mep_import_ifc, mep_report, mep_suggest_sleeves
from saengine.mep.ifc_import import inspect_ifc

SAMPLE = Path(__file__).resolve().parents[2] / "workbench/resources/saengine/samples/Sample Frame"

run = ifcopenshell.api.run


def _placement(origin, x_axis, z_axis) -> np.ndarray:
    x, z = np.array(x_axis, dtype=float), np.array(z_axis, dtype=float)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, np.cross(z, x), z, origin
    return m


def mep_ifc(path: Path, services: list[dict], system: str = "Domestic water") -> None:
    """A small MEP model in mm: each service an extruded rectangle or circle from ``origin``
    along ``direction`` over ``length``."""
    f = run("project.create_file", version="IFC4")
    project = run("root.create_entity", f, ifc_class="IfcProject", name="MEP")
    run("unit.assign_unit", f, length={"is_metric": True, "raw": "MILLIMETERS"})
    model = run("context.add_context", f, context_type="Model")
    body = run(
        "context.add_context",
        f,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model,
    )
    site = run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    run("aggregate.assign_object", f, products=[site], relating_object=project)
    pipes = run("system.add_system", f, ifc_class="IfcDistributionSystem")
    pipes.Name = system
    for item in services:
        element = run("root.create_entity", f, ifc_class=item["class"], name=item["name"])
        if "diameter" in item:
            profile = run("profile.add_parameterized_profile", f, ifc_class="IfcCircleProfileDef")
            profile.Radius = item["diameter"] / 2
        else:
            profile = run(
                "profile.add_parameterized_profile", f, ifc_class="IfcRectangleProfileDef"
            )
            profile.XDim, profile.YDim = item["width"], item["height"]
        representation = run(
            "geometry.add_profile_representation",
            f,
            context=body,
            profile=profile,
            depth=item["length"] / 1000,
        )
        run("geometry.assign_representation", f, product=element, representation=representation)
        direction = np.array(item["direction"], dtype=float)
        x_axis = [1.0, 0.0, 0.0] if abs(direction[0]) < 0.9 else [0.0, 0.0, 1.0]
        run(
            "geometry.edit_object_placement",
            f,
            product=element,
            matrix=_placement(item["origin"], x_axis, direction),
            is_si=False,
        )
        run("spatial.assign_container", f, products=[element], relating_structure=site)
        if item["class"] == "IfcPipeSegment":
            run("system.assign_system", f, products=[element], system=pipes)
    f.write(str(path))


# The sample's beam B1 runs along X at y = 0 from x = 0 to 6000, 300 x 500, top at 3200;
# its slab S1 (150 thick) spans 0..6000 x 0..5000 with its top at 3200.
DUCT = {
    "class": "IfcDuctSegment",
    "name": "SA duct 400x300",
    "width": 400.0,
    "height": 300.0,
    "origin": [3000.0, -2000.0, 2880.0],
    "direction": [0.0, 1.0, 0.0],
    "length": 4000.0,
}
PIPE = {
    "class": "IfcPipeSegment",
    "name": "DN100 riser",
    "diameter": 100.0,
    "origin": [2000.0, 2000.0, 2500.0],
    "direction": [0.0, 0.0, 1.0],
    "length": 1200.0,
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "Sample Frame"
    shutil.copytree(SAMPLE, root)
    mep_ifc(root / "07 MEP" / "services.ifc", [DUCT, PIPE])
    mep = {
        "schema": "saengine.mep/1",
        "openings": [
            {
                "id": "OP1",
                "host": "S1",
                "kind": "sleeve",
                "shape": "circle",
                "diameter": 150,
                "position": {"x": 2000, "y": 2000},
                "service": "DN100 riser",
            }
        ],
        "ifcModels": [{"path": "07 MEP/services.ifc", "discipline": "plumbing"}],
    }
    (root / "07 MEP" / "mep.json").write_text(json.dumps(mep), encoding="utf-8")
    return root


def test_clashes_and_coordination(project: Path) -> None:
    report = mep_report(project)
    clashes = {(c["mepName"], c["structural"]): c for c in report["clashes"]}
    assert set(clashes) == {("SA duct 400x300", "B1"), ("DN100 riser", "S1")}

    duct = clashes[("SA duct 400x300", "B1")]
    assert (duct["status"], duct["kind"], duct["type"]) == ("clash", "hard", "pierce")
    assert duct["depth"] == pytest.approx(300.0, abs=1)  # through the 300 wide beam
    assert duct["mepType"] == "IfcDuctSegment"
    assert duct["point"][0] == pytest.approx(3000, abs=210)
    assert duct["story"] == "L1"
    # The duct crosses B1's mid-plane at x = 3000, its centre 2880 - (3200 - 500) = 180 above
    # the beam's bottom; a 400 x 300 duct needs 450 x 350 with 25 mm each side.
    assert duct["size"] == pytest.approx(400.0, abs=1)
    suggestion = duct["sleeve"]
    assert suggestion["host"] == "B1"
    assert suggestion["kind"] == "opening"
    assert suggestion["shape"] == "rectangle"
    assert (suggestion["width"], suggestion["height"]) == (450.0, 350.0)
    assert suggestion["position"]["distance"] == pytest.approx(3000.0, abs=0.5)
    assert suggestion["position"]["elevation"] == pytest.approx(180.0, abs=0.5)

    pipe = clashes[("DN100 riser", "S1")]
    assert pipe["status"] == "coordinated"
    assert pipe["opening"] == "OP1"
    assert pipe["system"] == "Domestic water"
    assert pipe["file"] == "07 MEP/services.ifc"
    assert pipe["sleeve"] is None

    assert report["summary"]["clashes"] == 1
    assert report["summary"]["coordinated"] == 1


def test_small_sleeve_is_not_coordinated(project: Path) -> None:
    data = json.loads((project / "07 MEP" / "mep.json").read_text(encoding="utf-8"))
    data["openings"][0]["diameter"] = 80  # smaller than the DN100 pipe
    (project / "07 MEP" / "mep.json").write_text(json.dumps(data), encoding="utf-8")
    report = mep_report(project)
    pipe = next(c for c in report["clashes"] if c["structural"] == "S1")
    assert pipe["status"] == "clash"
    assert "too small" in pipe["note"]
    # Ø100 + 2 x 25 = 150, a multiple of 25.
    assert pipe["sleeve"]["shape"] == "circle"
    assert pipe["sleeve"]["diameter"] == 150.0
    assert pipe["sleeve"]["position"] == pytest.approx({"x": 2000.0, "y": 2000.0}, abs=0.5)


def test_suggested_sleeves_are_checked(project: Path) -> None:
    answer = mep_suggest_sleeves(project)
    (opening,) = answer["openings"]
    assert opening["host"] == "B1"
    # The proposal is an opening of mep.json as it is; its checks come beside it.
    data = json.loads((project / "07 MEP" / "mep.json").read_text(encoding="utf-8"))
    parse(json.dumps({**data, "openings": [*data["openings"], opening]}))
    found = answer["checks"][opening["id"]]
    checks = {c["name"]: c for c in found["checks"]}
    # 350 deep in a 500 deep beam: more than h/3, a Vierendeel opening.
    depth = checks["Opening depth for the net-section method (h/3)"]
    assert depth["demand"] == 350.0
    assert depth["capacity"] == pytest.approx(500 / 3, abs=0.01)
    assert not found["ok"]


def test_import_ifc_guesses_the_discipline(project: Path, tmp_path: Path) -> None:
    info = mep_import_ifc(project, project / "07 MEP" / "services.ifc")
    assert info["path"] == "07 MEP/services.ifc"
    assert info["inside"]
    assert info["counts"] == {"IfcDuctSegment": 1, "IfcPipeSegment": 1}
    assert info["elements"] == 2

    outside = tmp_path / "fire.ifc"
    mep_ifc(outside, [PIPE, {**PIPE, "origin": [4000.0, 1000.0, 2500.0]}], "Sprinkler zone 1")
    found = inspect_ifc(outside)
    assert found["discipline"] == "fire"
    assert found["systems"] == {"Sprinkler zone 1": 2}
    copied = mep_import_ifc(project, outside, copy=True)
    assert copied["path"] == "07 MEP/fire.ifc"
    assert (project / "07 MEP" / "fire.ifc").exists()
    left = mep_import_ifc(project, outside)
    assert not left["inside"]


def test_each_pair_is_service_against_structure(project: Path) -> None:
    # A duct along X through B5 also touches slabs, and IfcOpenShell hands some of those pairs
    # back reversed (slab first); each must still read as the duct against the structure.
    along = {
        "class": "IfcDuctSegment",
        "name": "duct B5",
        "width": 400.0,
        "height": 200.0,
        "origin": [-1000.0, 2500.0, 2900.0],
        "direction": [1.0, 0.0, 0.0],
        "length": 14000.0,
    }
    mep_ifc(project / "07 MEP" / "services.ifc", [along])
    report = mep_report(project)
    assert report["clashes"]
    for c in report["clashes"]:
        assert c["mepName"] == "duct B5" and c["mepType"] == "IfcDuctSegment"
        assert c["structuralKind"] != "ductsegment"
        assert "ductsegment" not in c["note"]
    pairs = [(c["mep"], c["structuralGlobalId"]) for c in report["clashes"]]
    assert len(pairs) == len(set(pairs))


def test_copy_never_replaces_another_model(project: Path, tmp_path: Path) -> None:
    first, second = tmp_path / "a" / "model.ifc", tmp_path / "b" / "model.ifc"
    first.parent.mkdir()
    second.parent.mkdir()
    mep_ifc(first, [PIPE], "Domestic water")
    mep_ifc(second, [DUCT], "Supply air")
    assert mep_import_ifc(project, first, copy=True)["path"] == "07 MEP/model.ifc"
    again = mep_import_ifc(project, first, copy=True)
    assert again["path"] == "07 MEP/model.ifc" and any("reused" in n for n in again["notes"])
    other = mep_import_ifc(project, second, copy=True)
    assert other["path"] == "07 MEP/model (2).ifc"
    assert (project / "07 MEP" / "model.ifc").read_bytes() == first.read_bytes()
    assert (project / "07 MEP" / "model (2).ifc").read_bytes() == second.read_bytes()


def test_unreadable_model_is_noted(project: Path) -> None:
    data = json.loads((project / "07 MEP" / "mep.json").read_text(encoding="utf-8"))
    data["ifcModels"].append({"path": "07 MEP/missing.ifc", "discipline": "fire"})
    (project / "07 MEP" / "mep.json").write_text(json.dumps(data), encoding="utf-8")
    report = mep_report(project)
    assert any("missing.ifc" in note for note in report["notes"])
    assert report["summary"]["clashes"] == 1


def test_unsaved_text_is_used(project: Path) -> None:
    data = json.loads((project / "07 MEP" / "mep.json").read_text(encoding="utf-8"))
    data["openings"] = []
    report = mep_report(project, mep_text=json.dumps(data))
    assert report["summary"]["clashes"] == 2 and report["summary"]["coordinated"] == 0
