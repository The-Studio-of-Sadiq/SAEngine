"""The cross-check corpus: SAEngine models built and analysed by SAEngine's own pipeline.

    python corpus.py --work <dir> [--models cantilever portal ...]

Every model ends as ``<work>/<name>/08 FEM/model.osmodel`` with its results (``model.results``)
and, where it has end offsets, ``faces.json``: what Run All leaves in a project.

- the four small models are drawn as Part 5 structural models and derived with
  :func:`saengine.fem.derive.derive_fem`, with the loads and supports the Verification Manual's
  cases give them (:mod:`saengine.verification.cases`), and run with OpenSees Studio's runner;
- the sample (``workbench/resources/saengine/samples/Sample Frame``) and the generated
  buildings (:func:`saengine.library.generator.generate_building`, New Building from Grid) go
  through ``saengine run-all --steps derive analysis`` on a copy, one at a time.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "workbench" / "resources" / "saengine" / "samples" / "Sample Frame"

#: Generated buildings (orthogonal grids): name -> New Building from Grid spec.
BUILDINGS: dict[str, dict[str, Any]] = {
    "frame6": {
        "name": "Frame 3x2 bays 6 storeys",
        "gridsX": [6000, 6000, 6000],
        "gridsY": [5000, 5000],
        "storyCount": 6,
        "typicalHeight": 3000,
        "system": "rcFrame",
    },
    "flatslab10": {
        "name": "Flat slab 10 storeys",
        "gridsX": [6000, 6000, 6000],
        "gridsY": [6000, 6000],
        "storyCount": 10,
        "typicalHeight": 3000,
        "system": "flatSlab",
    },
    "core10": {
        "name": "Frame with core 10 storeys",
        "gridsX": [6000, 6000, 6000],
        "gridsY": [6000, 6000],
        "storyCount": 10,
        "typicalHeight": 3000,
        "system": "rcFrameWithWalls",
    },
}


def _fem(folder: Path) -> Path:
    return folder / "08 FEM"


def _store(folder: Path, project: dict[str, Any], cases: list[int], faces: Any = None) -> Path:
    from saengine.fem.end_zones import FACES_FILE
    from saengine.verification.cases.common import run_model

    fem = _fem(folder)
    if fem.exists():
        shutil.rmtree(fem)
    if faces:
        fem.mkdir(parents=True)
        (fem / FACES_FILE).write_text(json.dumps(faces), encoding="utf-8")
    model, _, _ = run_model(project, fem, cases)
    return model


def _all_cases(project: dict[str, Any]) -> list[int]:
    return [a["id"] for a in project["analyses"] if a["type"] in ("Static", "Modal")]


def cantilever(folder: Path) -> Path:
    """A 4 m concrete cantilever (300 x 500), self-weight and a 20 kN tip load (the
    Verification Manual's cantilever), plus a lateral 5 kN tip load in a second case."""
    from saengine.verification.cases.analysis import BEAM, MATERIALS
    from saengine.verification.cases.common import (
        building,
        derive,
        node_at,
        objects,
        only_pattern,
        point,
        settings,
        structure,
    )

    model = structure(
        members=[{"id": "M1", "type": "BM", "start": point(0, 0, 0), "end": point(4000, 0, 0)}],
        supports=[{"id": "S1", "at": point(0, 0, 0)}],
    )
    project = derive(building(model), objects(BEAM), MATERIALS, settings()).project
    tip = node_at(project, (4.0, 0, 0))
    only_pattern(
        project, nodal=[{"node_id": tip, "forces": [0, 0, -20e3, 0, 0, 0]}], keep_dead=True
    )
    _lateral(project, tip, [0, 5e3, 0, 0, 0, 0])
    return _store(folder, project, _all_cases(project))


def _lateral(project: dict[str, Any], node: int, forces: list[float]) -> None:
    """Put ``forces`` on ``node`` as the only load of the second static case (keeping its
    name), so every model has one gravity and one lateral case."""
    statics = [a for a in project["analyses"] if a["type"] == "Static"]
    pattern = next(p for p in project["load_patterns"] if p["id"] == statics[1]["pattern_ids"][0])
    pattern["nodal_loads"] = [{"node_id": node, "forces": forces}]
    pattern["element_loads"] = []


def portal(folder: Path) -> Path:
    """The Verification Manual's portal frame (columns 400 x 400, beam 300 x 500, h 3.2 m,
    span 6 m): self-weight in D, a 10 kN sway load at the beam in the second case."""
    from saengine.verification.cases.analysis import BEAM, COLUMN, MATERIALS
    from saengine.verification.cases.common import (
        building,
        derive,
        node_at,
        objects,
        point,
        settings,
        structure,
    )

    model = structure(
        members=[
            {"id": "C1", "type": "COL", "start": point(0, 0, 0), "end": point(0, 0, 3200)},
            {"id": "C2", "type": "COL", "start": point(6000, 0, 0), "end": point(6000, 0, 3200)},
            {"id": "B1", "type": "BM", "start": point(0, 0, 3200), "end": point(6000, 0, 3200)},
        ],
        supports=[{"id": "S1", "at": point(0, 0, 0)}, {"id": "S2", "at": point(6000, 0, 0)}],
    )
    project = derive(building(model), objects(BEAM, COLUMN), MATERIALS, settings()).project
    _lateral(project, node_at(project, (0, 0, 3.2)), [10e3, 0, 0, 0, 0, 0])
    return _store(folder, project, _all_cases(project))


def offsets_beam(folder: Path) -> Path:
    """The Verification Manual's fixed-ended beam with rigid end zones (a one-storey bay of
    400 x 400 columns, beam B11 with end offsets, rigid-zone factor 0.5, its joints held), under
    10 kN/m; plus the same beam's self-weight in a second case."""
    from saengine.library.bim import generate
    from saengine.verification.cases.parity import (
        BEAM,
        COLUMN,
        MATERIALS,
        _plan,
        derive,
        objects,
        settings,
    )

    plan = _plan(stories=1, slabs=False, only="B11")
    d = derive(
        generate(plan, "v"),
        objects(COLUMN, BEAM),
        MATERIALS,
        settings(endOffsets=True, rigidZoneFactor=0.5, diaphragm="flexible"),
    )
    project = d.project
    (element,) = [e for e in project["elements"] if str(e.get("name", "")).startswith("B11")]
    held = set(element["nodes"][:2]) | {
        n["id"] for n in project["nodes"] if abs(n["coords"][2]) < 1e-9
    }
    for node in project["nodes"]:
        node["restraint"] = [True] * 6 if node["id"] in held else [False] * 6
        node["mass"] = [0.0] * 6
    project["mp_constraints"] = []
    first = project["load_patterns"][0]
    self_weight = [x for x in first.get("element_loads", []) if x["element_id"] == element["id"]]
    first["nodal_loads"] = []
    first["element_loads"] = [{"element_id": element["id"], "wx": 0.0, "wy": 0.0, "wz": -10e3}]
    statics = [a for a in project["analyses"] if a["type"] == "Static"]
    second = next(p for p in project["load_patterns"] if p["id"] == statics[1]["pattern_ids"][0])
    second["nodal_loads"], second["element_loads"] = [], self_weight
    project["analyses"] = statics[:2]
    return _store(folder, project, [a["id"] for a in project["analyses"]], d.faces)


def plate(folder: Path) -> Path:
    """The Verification Manual's simply supported square steel plate (2 m, 20 mm, 100 mm
    mesh, edges held in translation) under its self-weight."""
    from saengine.verification.cases.analysis import MATERIALS, STEEL
    from saengine.verification.cases.common import (
        building,
        derive,
        nodes_at,
        objects,
        point,
        settings,
        structure,
    )

    plate_type = {
        "id": "PL",
        "name": "Steel plate 20",
        "kind": "slab",
        "material": STEEL.id,
        "thickness": 20,
    }
    model = structure(
        areas=[
            {
                "id": f"P{i}{j}",
                "type": "PL",
                "outline": [
                    point(i * 1000, j * 1000, 0),
                    point((i + 1) * 1000, j * 1000, 0),
                    point((i + 1) * 1000, (j + 1) * 1000, 0),
                    point(i * 1000, (j + 1) * 1000, 0),
                ],
            }
            for i in (0, 1)
            for j in (0, 1)
        ]
    )
    project = derive(
        building(model), objects(plate_type), MATERIALS, settings(meshSize=100)
    ).project
    edge = set(nodes_at(project, lambda c: min(c[0], c[1], 2.0 - c[0], 2.0 - c[1]) < 1e-9))
    for node in project["nodes"]:
        if node["id"] in edge:
            node["restraint"] = [True, True, True, False, False, False]
    statics = [a for a in project["analyses"] if a["type"] == "Static"]
    project["analyses"] = statics[:1]
    return _store(folder, project, [statics[0]["id"]])


def run_all(project: Path) -> Path:
    """``saengine run-all <project> --steps derive analysis`` (Run All's own derivation and
    analysis) on a copy."""
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "saengine.cli",
            "run-all",
            str(project),
            "--steps",
            "derive",
            "analysis",
            "--json",
            "-q",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    try:
        doc = json.loads(done.stdout)
    except json.JSONDecodeError:
        raise SystemExit(
            f"run-all failed (exit {done.returncode}): {done.stderr[-2000:]}"
        ) from None
    if doc.get("stoppedAt"):
        raise SystemExit(f"run-all stopped: {json.dumps(doc.get('steps'))[:2000]}")
    return _fem(project) / "model.osmodel"


def sample(folder: Path) -> Path:
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree(SAMPLE, folder)
    return run_all(folder)


def generated(key: str) -> Callable[[Path], Path]:
    def build(folder: Path) -> Path:
        from saengine.library.generator import generate_building, write_building

        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        spec = BUILDINGS[key]
        write_building(generate_building(spec), folder, spec["name"])
        return run_all(folder)

    build.__doc__ = f"Generated building {BUILDINGS[key]}"
    return build


MODELS: dict[str, Callable[[Path], Path]] = {
    "cantilever": cantilever,
    "portal": portal,
    "offsets": offsets_beam,
    "plate": plate,
    "sample": sample,
    **{key: generated(key) for key in BUILDINGS},
}


def build(name: str, work: Path) -> Path:
    started = time.perf_counter()
    model = MODELS[name](work / name)
    print(f"{name}: built and analysed by SAEngine in {time.perf_counter() - started:.0f} s")
    return model


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--models", nargs="*", default=list(MODELS))
    args = ap.parse_args(argv)
    for name in args.models:
        build(name, args.work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
