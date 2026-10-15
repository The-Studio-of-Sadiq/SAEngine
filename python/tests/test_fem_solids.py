"""Solid blocks of special structures: their building model, IFC and analysis as volumes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from saengine.fem.derive import G, derive_fem
from saengine.fem.display import result_view, tetrahedron_stress, von_mises
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import BlockElement, generate_from_structure, source_stamp
from saengine.library.ifc import export_ifc
from saengine.library.settings import default_project_settings
from saengine.library.structure import StructuralModel, default_structural_model

MATERIALS = default_material_library()
CONCRETE = next(m for m in MATERIALS.materials if m.category.value == "concrete")
OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            {"id": "MASS", "name": "Mass concrete", "kind": "solid", "material": CONCRETE.id},
            {
                "id": "COL",
                "name": "Column 400x400",
                "kind": "column",
                "material": CONCRETE.id,
                "profile": {"shape": "rectangle", "xDim": 400, "yDim": 400},
            },
        ]
    }
)
SETTINGS = default_project_settings("Blocks")

L, B, H = 4000.0, 300.0, 600.0  # mm


def point(x: float, y: float, z: float) -> dict:
    return {"x": x, "y": y, "z": z}


def structure(**parts: list) -> StructuralModel:
    return StructuralModel.model_validate(
        {**default_structural_model().model_dump(mode="json", by_alias=True), **parts}
    )


# A cantilever block: its outline is the fixed end (in the YZ plane at x = 0, counter-clockwise
# seen from +x), extruded 4 m along +x.
CANTILEVER = structure(
    blocks=[
        {
            "id": "K1",
            "type": "MASS",
            "outline": [
                point(0, -B / 2, -H / 2),
                point(0, B / 2, -H / 2),
                point(0, B / 2, H / 2),
                point(0, -B / 2, H / 2),
            ],
            "thickness": L,
            "supported": True,
        }
    ]
)


def run(tmp_path: Path, project: dict, cases: list[int]) -> tuple[Path, Path]:
    model = tmp_path / "model.osmodel"
    model.write_text(json.dumps(project), encoding="utf-8")
    out = tmp_path / "model.results"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *map(str, cases),
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return model, out


def test_blocks_in_the_structural_and_building_models() -> None:
    assert CANTILEVER.check_objects(OBJECTS) == []
    assert np.allclose(CANTILEVER.blocks[0].extrusion(), [L, 0, 0])
    with pytest.raises(ValueError, match="not a solid type"):
        raise ValueError(
            *structure(blocks=[{**CANTILEVER.blocks[0].model_dump(), "type": "COL"}]).check_objects(
                OBJECTS
            )
        )
    building = generate_from_structure(CANTILEVER, source_stamp("k"))
    (block,) = [e for e in building.elements if isinstance(e, BlockElement)]
    assert (block.thickness, block.supported) == (L, True)
    assert building.check_objects(OBJECTS) == []
    ifc, ids, skipped = export_ifc(building, OBJECTS, MATERIALS, "Blocks")
    assert skipped == [] and ifc.by_guid(ids["K1"]).is_a() == "IfcBuildingElementProxy"


def test_cantilever_block_bends_under_its_own_weight(tmp_path: Path) -> None:
    d = derive_fem(
        generate_from_structure(CANTILEVER, source_stamp("k")), OBJECTS, MATERIALS, SETTINGS
    )
    solids = [e for e in d.project["elements"] if e["type"] == "Solid"]
    assert solids and {e["formulation"] for e in solids} == {"FourNodeTetrahedron"}
    assert d.summary["solids"] == len(solids)
    model, out = run(tmp_path, d.project, [1])

    from opensees_studio.services.result_store import load_manifest, load_results

    (entry,) = load_manifest(str(out))["cases"]
    results = load_results(entry, str(out))
    nodes = {n["id"]: np.array(n["coords"]) for n in d.project["nodes"]}
    density = CONCRETE.mechanical.density
    e = CONCRETE.mechanical.E * 1e6
    nu = CONCRETE.mechanical.nu if CONCRETE.mechanical.nu is not None else 0.2
    length, b, h = L / 1000, B / 1000, H / 1000
    w = density * G * b * h  # N/m
    # The supports carry the whole weight.
    weight = w * length
    reactions = sum(r[-1][2] for r in results.node_reaction.values())
    assert reactions == pytest.approx(weight, rel=1e-5)  # loads are written to 1 mN
    # Its free end sags as a Timoshenko cantilever under a uniform load does (four linear
    # tetrahedra across the width are slightly stiff).
    inertia = b * h**3 / 12
    expected = w * length**4 / (8 * e * inertia) + w * length**2 / (
        2 * 5 / 6 * e / (2 * (1 + nu)) * b * h
    )
    tip = [n for n, xyz in nodes.items() if abs(xyz[0] - length) < 1e-9]
    sag = -np.mean([results.node_disp[n][-1][2] for n in tip])
    assert 0.85 < sag / expected < 1.02

    # Stresses: tension along the top at the fixed end, about M·c/I there.
    view = result_view(out, model, f"case:{entry['case_id']}")
    root_top = [
        s
        for s in view["solids"]
        if all(nodes[n][0] < 0.3 and nodes[n][2] > 0.15 for n in s["nodes"])
    ]
    peak = max(s["stress"][0] for s in root_top)
    bending = w * length**2 / 2 * (h / 2) / inertia
    assert 0.6 < peak / bending < 1.2
    assert all(len(s["stress"]) == 7 for s in view["solids"])


def test_column_standing_on_a_footing_block(tmp_path: Path) -> None:
    """A column on a supported block is tied into it (not pinned): the frame stands up."""
    model = structure(
        blocks=[
            {
                "id": "F1",
                "type": "MASS",
                "outline": [
                    point(-1000, -1000, -800),
                    point(1000, -1000, -800),
                    point(1000, 1000, -800),
                    point(-1000, 1000, -800),
                ],
                "thickness": 800,
                "supported": True,
            }
        ],
        members=[{"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3000)}],
    )
    d = derive_fem(generate_from_structure(model, source_stamp("f")), OBJECTS, MATERIALS, SETTINGS)
    assert any("embedding struts" in n for n in d.notes)
    names = {e["name"].split("#")[0] for e in d.project["elements"]}
    assert {"C1", "F1", "F1/embed"} <= names
    project = d.project
    # A sideways push at the top of the column: it bends as a cantilever fixed in the block.
    top = next(n["id"] for n in project["nodes"] if np.allclose(n["coords"], [0, 0, 3.0]))
    project["load_patterns"][0]["nodal_loads"] = [{"node_id": top, "forces": [10e3, 0, 0, 0, 0, 0]}]
    project["load_patterns"][0]["element_loads"] = []
    path, out = run(tmp_path, project, [1])

    from opensees_studio.services.result_store import load_manifest, load_results

    (entry,) = load_manifest(str(out))["cases"]
    results = load_results(entry, str(out))
    sway = results.node_disp[top][-1][0]
    e = CONCRETE.mechanical.E * 1e6
    cantilever = 10e3 * 3.0**3 / (3 * e * 0.4**4 / 12)
    # The block and its embedding give a little: within a quarter of a fixed-base cantilever.
    assert cantilever < sway < 1.25 * cantilever
    assert sum(r[-1][0] for r in results.node_reaction.values()) == pytest.approx(-10e3, rel=1e-6)
    # The column's own forces: the moment at its base is the push times its height.
    view = result_view(out, path, f"case:{entry['case_id']}")
    (column,) = [e for e in view["elements"] if e["name"] == "C1"]
    assert abs(column["forces"][0][4]) == pytest.approx(30e3, rel=0.01)


def test_tetrahedron_stress_of_a_uniform_stretch() -> None:
    corners = [np.array(c, dtype=float) for c in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1))]
    strain = 1e-4
    stress = tetrahedron_stress(
        corners, [np.array([strain * c[0], 0, 0]) for c in corners], 30e9, 0.0
    )
    assert np.allclose(stress, [3e6, 0, 0, 0, 0, 0])
    assert von_mises(stress) == pytest.approx(3e6)
