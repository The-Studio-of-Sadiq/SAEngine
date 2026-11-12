"""Pushover analysis: fiber sections of the object types, and the pushover model of a building."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from test_fem_derive import PLAN, SETTINGS

from saengine.fem.derive import derive_fem
from saengine.fem.nonlinear import FiberMaterials, fiber_section
from saengine.library import ObjectLibrary, default_material_library
from saengine.library.bim import generate
from saengine.library.settings import Pushover

MATERIALS = default_material_library()
BY_ID = {m.id: m for m in MATERIALS.materials}
CONCRETE = next(m for m in MATERIALS.materials if m.category.value == "concrete")
REBAR = next(m for m in MATERIALS.materials if m.category.value == "rebar")
STEEL = next(m for m in MATERIALS.materials if m.category.value == "steel")


def reinforced(kind: str, top: int, bottom: int, perimeter: int = 0) -> dict:
    """A 300 x 500 concrete section with 16 mm bars, 40 mm cover and 10 mm ties at 150 mm."""
    groups = [
        *([{"position": "top", "count": top, "dia": 16}] if top else []),
        *([{"position": "bottom", "count": bottom, "dia": 16}] if bottom else []),
        *([{"position": "perimeter", "count": perimeter, "dia": 16}] if perimeter else []),
    ]
    return {
        "kind": kind,
        "material": CONCRETE.id,
        "profile": {"shape": "rectangle", "xDim": 300, "yDim": 500},
        "reinforcement": {
            "material": REBAR.id,
            "cover": 40,
            "longitudinal": groups,
            "transverse": {"type": "stirrup", "dia": 10, "spacing": 150, "legs": 2},
        },
    }


OBJECTS = ObjectLibrary.model_validate(
    {
        "objects": [
            {"id": "COL", "name": "Column 400x400", **reinforced("column", 0, 0, 8)}
            | {"profile": {"shape": "rectangle", "xDim": 400, "yDim": 400}},
            {"id": "BM", "name": "Beam 300x500", **reinforced("beam", 3, 3)},
            {
                "id": "SL",
                "name": "Slab 150",
                "kind": "slab",
                "material": CONCRETE.id,
                "thickness": 150,
            },
            {"id": "SB", "name": "Singly reinforced", **reinforced("beam", 0, 4)},
            {
                "id": "W",
                "name": "I 400",
                "kind": "beam",
                "material": STEEL.id,
                "profile": {
                    "shape": "I",
                    "overallWidth": 200,
                    "overallDepth": 400,
                    "webThickness": 8,
                    "flangeThickness": 13,
                },
            },
        ]
    }
)
TYPES = {o.id: o for o in OBJECTS.objects}


def moment_curvature(
    tmp_path: Path, type_id: str, curvature: float, steps: int = 200
) -> tuple[np.ndarray, np.ndarray]:
    """Bending moment about the section's strong axis against curvature, through the runner: a
    zero-length section between two nodes, the second turned (about global Y) to ``curvature``."""
    library = FiberMaterials()
    section = fiber_section(1, type_id, TYPES[type_id], BY_ID, library, False, 0)
    assert section is not None
    free = [False, True, True, True, False, True]  # axial (X) and rotation about Y move
    project = {
        "schema_version": 2,
        "meta": {"name": "section", "units": "SI (m, N, kg, s, Pa)"},
        "ndm": 3,
        "ndf": 6,
        "nodes": [
            {"id": 1, "coords": [0, 0, 0], "restraint": [True] * 6},
            {"id": 2, "coords": [0, 0, 0], "restraint": free},
        ],
        "materials": library.materials,
        "sections": [section],
        "elements": [{"id": 1, "type": "ZeroLengthSection", "nodes": [1, 2], "section_id": 1}],
        "time_series": [{"id": 1, "type": "Linear", "factor": 1.0}],
        "load_patterns": [
            {
                "id": 1,
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [{"node_id": 2, "forces": [0, 0, 0, 0, 1.0, 0]}],
            }
        ],
        "analyses": [
            {
                "id": 1,
                "name": "M-phi",
                "type": "Pushover",
                "pattern_ids": [1],
                "control_node": 2,
                "control_dof": 5,
                "target_disp": curvature,
                "step_size": abs(curvature) / steps,
                "base_nodes": [1],
            }
        ],
    }
    folder = tmp_path / type_id
    folder.mkdir()
    (folder / "s.osmodel").write_text(json.dumps(project), encoding="utf-8")
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(folder / "s.osmodel"),
            "--cases",
            "1",
            "--out",
            str(folder / "out"),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    from opensees_studio.services.result_store import load_manifest, load_results

    (entry,) = load_manifest(str(folder / "out"))["cases"]
    results = load_results(entry, str(folder / "out"))
    return np.abs(results.control_disp), np.abs(results.base_shear)


def test_steel_section_reaches_its_plastic_moment(tmp_path: Path) -> None:
    fy, e = STEEL.steel.fy * 1e6, STEEL.mechanical.E * 1e6
    b, d, tw, tf = 0.2, 0.4, 0.008, 0.013
    inertia = (b * d**3 - (b - tw) * (d - 2 * tf) ** 3) / 12
    plastic = b * tf * (d - tf) + tw * (d - 2 * tf) ** 2 / 4
    yield_curvature = fy / e / (d / 2)
    phi, m = moment_curvature(tmp_path, "W", 3 * yield_curvature, 300)
    assert m[1] / phi[1] == pytest.approx(e * inertia, rel=0.01)
    # At three times the yield curvature only the middle third of the web is still elastic.
    assert m[-1] == pytest.approx(fy * plastic, rel=0.03)


def test_reinforced_concrete_beam_reaches_its_flexural_strength(tmp_path: Path) -> None:
    fc, fy = CONCRETE.concrete.fc, REBAR.steel.fy
    area = 4 * math.pi * 0.016**2 / 4
    depth = 0.5 - 0.040 - 0.010 - 0.008
    block = area * fy / (0.85 * fc * 0.3)
    nominal = area * fy * 1e6 * (depth - block / 2)
    # Sagging: tension in the bottom bars (negative curvature about local y, z up).
    phi, m = moment_curvature(tmp_path, "SB", -0.05)
    assert m.max() == pytest.approx(nominal, rel=0.08)
    # Uncracked at first, then much softer once cracked.
    assert m[-1] / phi[-1] < 0.2 * m[1] / phi[1]


def test_rectangle_bar_layouts() -> None:
    library = FiberMaterials()
    column = fiber_section(1, "COL", TYPES["COL"], BY_ID, library, True, 0)
    beam = fiber_section(2, "BM", TYPES["BM"], BY_ID, library, False, 0)
    bars = lambda s: sorted((round(f["y"], 3), round(f["z"], 3)) for f in s["fibres"])
    # 8 bars around a 400 square: corners and one in the middle of each side, at 400/2 - 58.
    c = 0.142
    assert bars(column) == sorted(
        [(-c, -c), (-c, c), (c, -c), (c, c), (-c, 0.0), (c, 0.0), (0.0, -c), (0.0, c)]
    )
    # Beam: depth along local z (up), 3 bars top and bottom across its width.
    assert {z for _, z in bars(beam)} == {-0.192, 0.192}
    assert sorted({y for y, _ in bars(beam)}) == [-0.092, 0.0, 0.092]
    # One steel, one unconfined cover, and a core per tie ratio: the beam's ties confine its
    # smaller core more than the column's do.
    names = sorted(m["name"].split()[-1] for m in library.materials)
    assert names == sorted([REBAR.id, "core", "core", "cover"])
    cores = sorted(-m["fpc"] for m in library.materials if m["name"].endswith("core"))
    fc = CONCRETE.concrete.fc * 1e6
    assert fc < cores[0] < cores[1] < 1.5 * fc


def test_pushover_of_a_one_story_bay(tmp_path: Path) -> None:
    settings = SETTINGS.model_copy(
        update={
            "analysis": SETTINGS.analysis.model_copy(
                update={"pushover": Pushover(directions=["X"], targetDrift=2.0, steps=50)}
            )
        }
    )
    d = derive_fem(generate(PLAN, "s"), OBJECTS, MATERIALS, settings, None, tmp_path)
    model = d.pushover
    assert model is not None
    types = {e["type"] for e in model["elements"]}
    assert types == {"ForceBeamColumn"}
    (gravity, push) = model["analyses"]
    assert gravity["name"].startswith("G: Gravity") and push["name"] == "PX: Pushover X"
    assert push["target_disp"] == pytest.approx(0.02 * 3.2)
    # B20: the lateral load follows the fundamental mode in X (BNBC 2020 Sec 2.5.12.2).
    (mode,) = [p for p in model["load_patterns"] if p["id"] in push["pattern_ids"]]
    assert mode["name"] == "MX" and all(load["forces"][0] > 0 for load in mode["nodal_loads"])

    from opensees_studio.services.persistence import load_project

    path = tmp_path / "pushover.osmodel"
    path.write_text(json.dumps(model), encoding="utf-8")
    load_project(str(path)).validate_references()
    out = tmp_path / "pushover.results"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(path),
            "--cases",
            "2",
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    from opensees_studio.services.result_store import load_manifest, load_results

    (entry,) = load_manifest(str(out))["cases"]
    results = load_results(entry, str(out))
    assert not entry.get("early_stop") and results.control_disp[-1] == pytest.approx(
        0.064, rel=1e-3
    )
    shear = results.base_shear
    initial = shear[1] / results.control_disp[1]
    final = (shear[-1] - shear[-6]) / (results.control_disp[-1] - results.control_disp[-6])
    # The frame yields: the curve flattens to a fraction of its initial stiffness.
    assert shear.max() > 0 and final < 0.15 * initial

    # The column bases carry the shear, and the reactions balance it at every step.
    bases = push["base_nodes"]
    step = len(shear) - 1
    total = -sum(results.node_reaction[n][step][0] for n in bases)
    assert total == pytest.approx(shear[step], rel=1e-6)

    # The 3D display: the capacity curve as frames, and the frame at the largest base shear.
    from saengine.fem.display import result_list, result_view

    (listed,) = result_list(out, path)["results"]
    assert listed["kind"] == "pushover" and len(listed["frames"]) == len(shear)
    assert listed["frames"][-1]["displacement"] == pytest.approx(0.064, rel=1e-3)
    peak = listed["frames"][listed["peak"] - 1]
    assert peak["shear"] == pytest.approx(shear.max(), rel=1e-3)
    view = result_view(out, path, listed["key"], listed["peak"])
    assert view["kind"] == "pushover" and len(view["reactions"]) == len(bases)
    assert -sum(r[1] for r in view["reactions"]) == pytest.approx(peak["shear"], rel=1e-3)
    assert all("forces" in e for e in view["elements"])

    # B20: the target displacement (coefficient method) and the members' acceptance.
    from saengine.fem import acceptance, pushover_target

    assert results.element_start_fibers and results.element_end_fibers
    target = pushover_target.evaluate(model, push, results, SETTINGS)
    assert target["available"] and target["patternOk"]
    assert 0 < target["target"] < results.control_disp[-1]
    assert target["Te"] >= target["T1"] * 0.999 and target["C0"] == pytest.approx(1.0, abs=0.05)
    accepted = acceptance.evaluate(model, results, target)
    assert accepted["available"] and accepted["rows"]
    assert {r["member"] for r in accepted["rows"]} <= {
        e["name"].split("#")[0] for e in model["elements"]
    }
