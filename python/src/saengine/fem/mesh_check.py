"""Mesh convergence check of the analysis model: does the shell mesh change the beams' moments?

Beams on shell slabs (and walls) share the shells' nodes, so their gravity moments depend on
how fine the slabs are meshed: a coarse mesh makes the slab too stiff along the beams and
moves moment out of them (a study against a commercial analysis program found the beam end
moments 4-21 % low at 1000 mm and within 5 % at 500 mm). :func:`mesh_convergence` derives the
model at the project's mesh and at a mesh ``factor`` times coarser, runs the gravity cases
(D, SD, L) of both (cheap linear static cases) and returns the largest change of a beam end
moment (at the support face when the model has end offsets), so Run All can warn when the
mesh is not converged (more than 5 % by default).

Units: kN·m in the result.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

#: A beam end moment changing by more than this [%] between the meshes: not converged.
THRESHOLD = 5.0
#: Ends whose moment is below this share of the largest beam end moment are not compared (a
#: small moment's relative change means nothing).
SMALL_SHARE = 0.10
GRAVITY_CASES = ("D", "SD", "L")


def _beam_end_moments(
    project: dict[str, Any],
    out_dir: Path,
    beams: set[str],
    faces: dict[str, Any] | None,
    cases: tuple[str, ...],
) -> dict[tuple[str, str], float]:
    """Per (beam, "i"|"j") the strong-axis moment My [N·m] at its ends (at its faces when the
    model has them), summed over ``cases``."""
    from opensees_studio.services.result_store import load_manifest, load_results
    from opensees_studio.services.results import StaticResults

    from saengine.fem.end_zones import element_offsets, section_at

    elements = {int(e["id"]): e for e in project.get("elements", [])}
    chains: dict[str, list[int]] = {}
    for e in project.get("elements", []):
        source = str(e.get("name") or "").split("#")[0]
        if source in beams and e.get("type") == "ElasticBeamColumn":
            chains.setdefault(source, []).append(int(e["id"]))
    patterns = {p["id"]: p for p in project.get("load_patterns", [])}
    analyses = {a["id"]: a for a in project.get("analyses", [])}
    face_of = (faces or {}).get("elements", {})
    total: dict[tuple[str, str], float] = {}
    for entry in load_manifest(out_dir)["cases"]:
        code = str(entry["case_name"]).split(":")[0].strip()
        if code not in cases:
            continue
        results = load_results(entry, out_dir)
        if not isinstance(results, StaticResults):
            continue
        loads: dict[int, np.ndarray] = {}
        for pid in analyses.get(int(entry["case_id"]), {}).get("pattern_ids", []):
            for load in patterns.get(pid, {}).get("element_loads", []):
                loads.setdefault(int(load["element_id"]), np.zeros(3))[:] += [
                    load.get("wx", 0.0),
                    load.get("wy", 0.0),
                    load.get("wz", 0.0),
                ]
        for beam, ids in chains.items():
            ids = sorted(ids)
            for end, eid in (("i", ids[0]), ("j", ids[-1])):
                face = face_of.get(str(eid), {}).get(end)
                at_id, distance = (
                    (int(face["at"][0]), float(face["at"][1])) if face else (eid, None)
                )
                rows = results.element_forces.get(at_id)
                if rows is None or not len(rows):
                    continue
                forces = np.asarray(rows[-1], dtype=float)[:12]
                element = elements[at_id]
                if distance is None:
                    moment = float(-forces[4]) if end == "i" else float(forces[10])
                else:
                    ri, _ = element_offsets(element)
                    moment = float(
                        section_at(forces, loads.get(at_id, np.zeros(3)), distance - ri)[4]
                    )
                total[(beam, end)] = total.get((beam, end), 0.0) + moment
    return total


def _run_gravity(
    derivation: Any, folder: Path, cases: tuple[str, ...]
) -> tuple[dict[str, Any], Path]:
    from saengine.fem.seismic_design import _run

    project = derivation.project
    kept = [
        a
        for a in project.get("analyses", [])
        if a.get("type") == "Static" and str(a.get("name", "")).split(":")[0].strip() in cases
    ]
    model = {**project, "analyses": kept, "spectra": [], "ground_motions": []}
    model["load_patterns"] = [
        p for p in project.get("load_patterns", []) if p.get("type", "Plain") == "Plain"
    ]
    model["time_series"] = [s for s in project.get("time_series", []) if "record_id" not in s]
    out = _run(model, folder, [int(a["id"]) for a in kept])
    return model, out


def mesh_convergence(
    building: Any,
    objects: Any,
    materials: Any,
    settings: Any,
    *,
    mep: Any = None,
    member_loads: Any = None,
    model_dir: str | Path | None = None,
    factor: float = 2.0,
    threshold: float = THRESHOLD,
    cases: tuple[str, ...] = GRAVITY_CASES,
    fine: tuple[dict[str, Any], Path, dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """The change of the beams' gravity end moments when the mesh is ``factor`` times coarser:
    ``{"meshSize_mm", "coarseSize_mm", "cases", "maxChangePercent", "estimatedErrorPercent"
    (the fine mesh's error by Richardson extrapolation), "members": [{"member",
    "end", "fine_kNm", "coarse_kNm", "changePercent"}] (largest first, at most 10),
    "compared", "threshold", "warning", "note"}``. Raises ``ValueError`` when a run fails.
    ``fine``: the project's own analysed model, its results folder and faces (current, see
    :func:`project_mesh_convergence`), which then stand for the fine mesh: only the coarse one
    is derived and run (on 25 storeys each derivation took minutes)."""
    from saengine.fem.derive import derive_fem
    from saengine.library.bim import BeamElement

    beams = {e.id for e in building.elements if isinstance(e, BeamElement)}
    size = float(settings.analysis.meshSize)
    moments = []
    with tempfile.TemporaryDirectory(prefix="saengine-meshcheck-") as tmp:
        for k, scale in enumerate((1.0, factor)):
            if k == 0 and fine is not None:
                moments.append(_beam_end_moments(fine[0], fine[1], beams, fine[2], cases))
                continue
            analysis = settings.analysis.model_copy(update={"meshScale": scale})
            derivation = derive_fem(
                building,
                objects,
                materials,
                settings.model_copy(update={"analysis": analysis}),
                model_dir=model_dir,
                mep=mep,
                member_loads=member_loads,
            )
            model, out = _run_gravity(derivation, Path(tmp) / f"mesh{k}", cases)
            moments.append(_beam_end_moments(model, out, beams, derivation.faces, cases))
    fine, coarse = moments
    largest = max((abs(v) for v in fine.values()), default=0.0)
    rows = []
    for key, value in fine.items():
        if key not in coarse or abs(value) < SMALL_SHARE * largest or not value:
            continue
        change = (coarse[key] - value) / abs(value) * 100
        rows.append(
            {
                "member": key[0],
                "end": key[1],
                "fine_kNm": round(value / 1e3, 3),
                "coarse_kNm": round(coarse[key] / 1e3, 3),
                "changePercent": round(change, 2),
            }
        )
    rows.sort(key=lambda r: -abs(r["changePercent"]))
    worst = abs(rows[0]["changePercent"]) if rows else 0.0
    note = (
        f"mesh check: the beams' gravity end moments ({' + '.join(cases)}) change by up to "
        f"{worst:.1f} % when the mesh is {factor:g} times coarser"
        + (f" ({rows[0]['member']} end {rows[0]['end']})" if rows else "")
        + (
            f"; above {threshold:g} %: the mesh is not converged, make it finer"
            if worst > threshold
            else f"; within {threshold:g} %: converged"
        )
    )
    return {
        "meshSize_mm": size,
        "coarseSize_mm": size * factor,
        "cases": list(cases),
        "maxChangePercent": round(worst, 2),
        # Richardson: with second-order convergence the fine mesh's own error is about the
        # change over (factor² - 1); a guide, the warning is on the change itself.
        "estimatedErrorPercent": round(worst / (factor**2 - 1), 2) if factor > 1 else None,
        "members": rows[:10],
        "compared": len(rows),
        "threshold": threshold,
        "warning": worst > threshold,
        "note": note,
    }


def project_mesh_convergence(project_folder: str | Path, **options: Any) -> dict[str, Any]:
    """:func:`mesh_convergence` of a project folder's files (the building model, object types,
    materials and settings, with the site class and the MEP model as the derivation takes
    them)."""
    from saengine.library import mep as mep_library
    from saengine.library.bim import BuildingModel
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import ProjectSettings, read_soil_text, resolve_site_class
    from saengine.mep.loads import has_model_content

    root = Path(project_folder)

    def text(relative: str) -> str:
        return (root / relative).read_text(encoding="utf-8")

    building = BuildingModel.model_validate_json(text("06 BIM/bim.json"))
    objects = ObjectLibrary.model_validate_json(text("04 Objects/objects.json"))
    materials = MaterialLibrary.model_validate_json(text("03 Materials/materials.json"))
    settings = ProjectSettings.model_validate_json(
        text("02 Project Settings/project-settings.json")
    )
    settings, _ = resolve_site_class(settings, read_soil_text(root))
    mep_path = root / mep_library.MEP_FILE
    mep = mep_library.parse(mep_path.read_text(encoding="utf-8") if mep_path.exists() else None)
    from saengine.library import line_loads as ll

    loads_path = root / ll.LOADS_FILE
    member_loads = ll.parse(loads_path.read_text(encoding="utf-8") if loads_path.exists() else None)
    options.setdefault("fine", _current_analysis(root))
    return mesh_convergence(
        building,
        objects,
        materials,
        settings,
        mep=mep if has_model_content(mep) else None,
        member_loads=member_loads if member_loads.loads else None,
        model_dir=root / "08 FEM",
        **options,
    )


def _current_analysis(root: Path) -> tuple[dict[str, Any], Path, dict[str, Any] | None] | None:
    """The project's analysed model, its results folder and faces when the model is derived
    from the project's files as they are and the results are its own (Run All's tests:
    ``derivation_state``, ``results_current``), else None."""
    from saengine.fem.end_zones import read_faces
    from saengine.pipeline.project import open_project
    from saengine.pipeline.run_all import (
        DERIVATION_INPUTS,
        derivation_state,
        results_current,
        results_folder,
    )

    try:
        project = open_project(root)
        model_path = project.file("fem")
        model = json.loads(model_path.read_text(encoding="utf-8"))
        description = model.get("meta", {}).get("description")
        derived, changed = derivation_state(description, project.texts(DERIVATION_INPUTS))
    except (OSError, ValueError, AttributeError):
        return None
    if not derived or changed or not results_current(model_path):
        return None
    return model, results_folder(model_path), read_faces(model_path)


#: The check's result beside the analysis results (``08 FEM/model.results``).
MESH_CHECK_FILE = "mesh-check.json"


def needs_check(project_folder: str | Path) -> str | None:
    """Why the project needs no mesh check (``analysis.meshCheck`` off, or no shells: slabs
    loading the beams and no structural walls), else None."""
    from saengine.library.bim import BuildingModel, WallElement
    from saengine.library.settings import ProjectSettings

    root = Path(project_folder)
    settings = ProjectSettings.model_validate_json(
        (root / "02 Project Settings/project-settings.json").read_text(encoding="utf-8")
    )
    if not getattr(settings.analysis, "meshCheck", True):
        return "the mesh check is off (Project Settings, Analysis model)"
    if settings.analysis.slabs == "shells":
        return None
    building = BuildingModel.model_validate_json(
        (root / "06 BIM/bim.json").read_text(encoding="utf-8")
    )
    if any(isinstance(e, WallElement) for e in building.elements):
        return None
    return "no shells: the slabs load the beams, so the mesh does not change the beams"


def dumps(result: dict[str, Any]) -> str:
    return json.dumps(result, indent="\t", ensure_ascii=False) + "\n"
