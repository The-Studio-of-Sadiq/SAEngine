"""Special structures: the structural model (Part 5), its building model, IFC and analysis model."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from saengine.fem.derive import derive_fem
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import AreaElement, MemberElement, generate_from_structure, source_stamp
from saengine.library.ifc import export_ifc
from saengine.library.settings import default_project_settings
from saengine.library.structure import StructuralModel, default_structural_model

G = 9.80665
RHO = 2400.0

OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            {
                "id": "COL",
                "name": "Column 400x400",
                "kind": "column",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
            },
            {
                "id": "BM",
                "name": "Beam 300x500",
                "kind": "beam",
                "material": "C24.1",
                "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
            },
            {
                "id": "RS",
                "name": "Roof slab 150",
                "kind": "slab",
                "material": "C24.1",
                "thickness": 150,
            },
        ]
    }
)

corners = [(0, 0), (6000, 0), (6000, 5000), (0, 5000)]
H = 4000


def point(x: float, y: float, z: float) -> dict:
    return {"x": x, "y": y, "z": z}


# A canopy: four columns, four edge beams and a roof slab with a 1 m square opening.
CANOPY = StructuralModel.model_validate(
    {
        **default_structural_model().model_dump(mode="json", by_alias=True),
        "members": [
            *(
                {"id": f"C{i + 1}", "type": "COL", "start": point(x, y, 0), "end": point(x, y, H)}
                for i, (x, y) in enumerate(corners)
            ),
            *(
                {"id": f"B{i + 1}", "type": "BM", "start": point(*a, H), "end": point(*b, H)}
                for i, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1], strict=True))
            ),
        ],
        "areas": [
            {
                "id": "R1",
                "type": "RS",
                "outline": [point(x, y, H) for x, y in corners],
                "openings": [
                    {
                        "outline": [
                            point(2000, 2000, H),
                            point(3000, 2000, H),
                            point(3000, 3000, H),
                            point(2000, 3000, H),
                        ]
                    }
                ],
                "areaLoad": "RF",
            }
        ],
        "supports": [{"id": f"S{i + 1}", "at": point(x, y, 0)} for i, (x, y) in enumerate(corners)],
    }
)


def test_structural_model_rules() -> None:
    assert default_structural_model().grids[0].z[1].position == 4000
    with pytest.raises(ValidationError, match="not a flat polygon"):
        StructuralModel.model_validate(
            {
                "areas": [
                    {
                        "id": "A1",
                        "type": "RS",
                        "outline": [
                            point(0, 0, 0),
                            point(1000, 0, 0),
                            point(1000, 1000, 500),
                            point(0, 1000, 0),
                        ],
                    }
                ]
            }
        )
    with pytest.raises(ValidationError, match="same point"):
        StructuralModel.model_validate(
            {
                "members": [
                    {"id": "M1", "type": "BM", "start": point(0, 0, 0), "end": point(0, 0, 0)}
                ]
            }
        )
    with pytest.raises(ValidationError, match="duplicate element ids: X"):
        StructuralModel.model_validate(
            {
                "members": [
                    {"id": "X", "type": "BM", "start": point(0, 0, 0), "end": point(1000, 0, 0)}
                ],
                "areas": [
                    {
                        "id": "X",
                        "type": "RS",
                        "outline": [point(0, 0, 0), point(1000, 0, 0), point(0, 1000, 0)],
                    }
                ],
            }
        )
    assert CANOPY.check_objects(OBJECTS) == []


def test_building_model_and_ifc_of_a_structure() -> None:
    text = json.dumps(CANOPY.model_dump(mode="json", by_alias=True))
    model = generate_from_structure(CANOPY, source_stamp(text))
    assert model.source.structure == source_stamp(text) and model.source.floorPlan is None
    assert [s.elevation for s in model.stories] == [0, 4000]
    assert sum(isinstance(e, MemberElement) for e in model.elements) == 8
    area = next(e for e in model.elements if isinstance(e, AreaElement))
    assert (area.areaLoad, len(area.openings), len(model.supports)) == ("RF", 1, 4)
    assert model.check_objects(OBJECTS) == []

    ifc, ids, skipped = export_ifc(model, OBJECTS, default_material_library(), "Canopy")
    assert skipped == [] and set(ids) == {e.id for e in model.elements}
    classes = sorted(ifc.by_guid(ids[e]).is_a() for e in ("C1", "B1", "R1"))
    assert classes == ["IfcBeam", "IfcColumn", "IfcSlab"]


def test_analysis_model_of_a_structure(tmp_path: Path) -> None:
    from opensees_studio.core.project import Project

    building = generate_from_structure(CANOPY, "s")
    settings = default_project_settings("Canopy")
    d = derive_fem(building, OBJECTS, default_material_library(), settings)
    Project.model_validate(d.project).validate_references()
    assert d.summary["supports"] == 4 and d.summary["shells"] > 10 and d.summary["diaphragms"] == 0
    assert any("special structure" in n for n in d.notes)

    def total(case: str) -> float:
        pattern = next(p for p in d.project["load_patterns"] if p["name"] == case)
        nodal = sum(n["forces"][2] for n in pattern["nodal_loads"])
        coords = {n["id"]: np.array(n["coords"]) for n in d.project["nodes"]}
        elements = {e["id"]: e for e in d.project["elements"]}
        line = 0.0
        for load in pattern["element_loads"]:
            a, b = (coords[n] for n in elements[load["element_id"]]["nodes"])
            from saengine.fem.derive import local_axes

            x, y, z = local_axes(a, b)
            line += ((load["wx"] * x + load["wy"] * y + load["wz"] * z) * np.linalg.norm(b - a))[2]
        return nodal + line

    roof = 6 * 5 - 1  # m², less the opening
    weight = RHO * G * (roof * 0.15 + 4 * 0.16 * 4 + 22 * 0.15)
    assert total("D") == pytest.approx(-weight, rel=1e-6)
    assert total("SD") == pytest.approx(-roof * 1.5e3, rel=1e-6)
    assert total("L") == pytest.approx(-roof * 1.0e3, rel=1e-6)

    model = tmp_path / "model.osmodel"
    model.write_text(json.dumps(d.project), encoding="utf-8")
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            "1",
            "--out",
            str(tmp_path / "out"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    from opensees_studio.services.result_store import load_manifest, load_results

    results = load_results(load_manifest(tmp_path / "out")["cases"][0], tmp_path / "out")
    reaction = sum(r[-1][2] for r in results.node_reaction.values())
    assert reaction == pytest.approx(weight, rel=1e-6)
