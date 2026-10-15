"""Request handlers, kept free of any transport so they can be tested directly.

Every handler takes and returns plain JSON-compatible values.
"""

from __future__ import annotations

import math
import platform
from importlib import metadata
from pathlib import Path
from typing import Any

import saengine


def info() -> dict[str, Any]:
    """Versions of the backend stack, for the workbench's runtime check."""

    def version(dist: str) -> str | None:
        try:
            return metadata.version(dist)
        except metadata.PackageNotFoundError:
            return None

    return {
        "saengine": saengine.__version__,
        "openseesStudio": version("opensees-studio"),
        "openseespy": version("openseespy"),
        "python": platform.python_version(),
    }


def validate_project(path: str) -> dict[str, Any]:
    """Load ``path`` with the opensees-studio schema and check its references."""
    from opensees_studio.services.persistence import load_project

    notices: list[str] = []
    try:
        project = load_project(path, on_notice=notices.append)
        project.validate_references()
    except Exception as exc:  # noqa: BLE001 - every failure is reported to the user
        return {"ok": False, "errors": [str(exc)], "notices": notices}
    return {
        "ok": True,
        "errors": [],
        "notices": notices,
        "summary": {
            "name": project.meta.name,
            "units": project.meta.units.value,
            "ndm": project.ndm,
            "ndf": project.ndf,
            "nodes": len(project.nodes),
            "elements": len(project.elements),
            "analyses": [
                {"id": case.id, "name": case.name, "type": type(case).__name__}
                for case in project.analyses
            ],
        },
    }


def _cell(value: Any) -> Any:
    """JSON has no inf/nan; send them as strings the workbench can display."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def _table(table: Any, name: str) -> dict[str, Any]:
    return {
        "name": name,
        "title": table.title,
        "columns": list(table.columns),
        "rows": [[_cell(c) for c in row] for row in table.rows],
        "notes": list(table.notes),
    }


def _peak_table(results: Any, project: Any) -> Any:
    """Each node's largest displacement during a time history, from where it started."""
    import numpy as np
    from opensees_studio.services.result_tables import ResultTable

    table = ResultTable(
        "Peak displacements during the shaking",
        ["Node", "|ux| max", "|uy| max", "|uz| max", "At time (s)"],
    )
    times = np.asarray(results.time(), dtype=float)
    for node in project.nodes if project is not None else []:
        try:
            history = np.asarray(results.node_disp_history(node.id), dtype=float)
        except (KeyError, ValueError):
            continue
        if history.ndim != 2 or not len(history):
            continue
        moved = np.abs(history[:, :3] - history[0, :3])
        step = int(np.argmax(np.linalg.norm(moved, axis=1)))
        table.rows.append([node.id, *(float(v) for v in moved.max(axis=0)), float(times[step])])
    table.notes.append(
        "Displacements in the model's length unit, measured from the position under the dead "
        "loads, before the shaking."
    )
    return table


def _tables_for(results: Any, project: Any) -> list[dict[str, Any]]:
    """The same tables, in the same order, as opensees-studio's Results panel."""
    from opensees_studio.services import result_tables as rt
    from opensees_studio.services.results import (
        ModalResults,
        PushoverResults,
        ResponseSpectrumResults,
        StaticResults,
        TransientResults,
    )

    if isinstance(results, StaticResults):
        tables = list(
            zip(
                rt.static_tables(results, project),
                ("Displacements", "Reactions", "Element forces"),
                strict=True,
            )
        )
        if results.n_steps > 1 and len(results.load_factors):
            tables.append((rt.static_history_table(results, project), "Static history"))
    elif isinstance(results, PushoverResults):
        tables = list(
            zip(
                rt.pushover_tables(results, project),
                ("Curve", "Displacements", "Element forces"),
                strict=True,
            )
        )
    elif isinstance(results, ModalResults):
        tables = [(rt.modal_tables(results)[0], "Frequencies")]
    elif isinstance(results, ResponseSpectrumResults):
        combined, modes = rt.response_spectrum_tables(results, project)
        tables = [(combined, "Combined displacements"), (modes, "Modes")]
    elif isinstance(results, TransientResults):
        # Full histories are large: the 3D view plays them; the table holds each node's peaks.
        tables = [(_peak_table(results, project), "Peak displacements")]
    else:
        tables = []
    return [_table(table, name) for table, name in tables]


def results_tables(out_dir: str, project_path: str | None = None) -> dict[str, Any]:
    """Every case in ``out_dir/manifest.json`` with its result tables."""
    from opensees_studio.services.persistence import load_project
    from opensees_studio.services.result_store import load_manifest, load_results

    manifest = load_manifest(out_dir)
    project_file = project_path or manifest.get("project")
    project = load_project(project_file) if project_file and Path(project_file).exists() else None

    cases = []
    for entry in manifest["cases"]:
        results = load_results(entry, out_dir)
        cases.append(
            {
                "caseId": entry["case_id"],
                "caseName": entry["case_name"],
                "resultType": entry["result_type"],
                "earlyStop": bool(entry.get("early_stop")),
                "warnings": list(entry.get("warnings", [])),
                "tables": _tables_for(results, project),
            }
        )
    # Models derived by SAEngine: the project settings' load combinations of these results.
    # (Not for the pushover model: its single gravity case is no design load case.)
    pushover_model = project is not None and any(
        type(a).__name__ == "PushoverCase" for a in project.analyses
    )
    if (
        project is not None
        and project.meta.author == "SAEngine"
        and project_file
        and not pushover_model
    ):
        import json as _json

        from saengine.fem.combinations import combination_results, settings_beside

        settings = settings_beside(project_file)
        if settings is not None:
            payload = _json.loads(Path(project_file).read_text(encoding="utf-8"))
            cases.extend(combination_results(out_dir, payload, settings))
    return {"cases": cases}


def result_list(out_dir: str, project_path: str) -> dict[str, Any]:
    """The results of a run that can be shown in 3D (see ``saengine.fem.display``)."""
    from saengine.fem.display import result_list as listing

    return listing(out_dir, project_path)


def result_view(out_dir: str, project_path: str, key: str, mode: int | None) -> dict[str, Any]:
    """One result's deflected shape and force diagrams (see ``saengine.fem.display``)."""
    from saengine.fem.display import result_view as view

    return view(out_dir, project_path, key, mode or 1)


def check_library(kind: str, text: str, materials_text: str | None = None) -> dict[str, Any]:
    from saengine.library.check import check_library as check

    if kind not in ("materials", "objects", "settings", "floorPlan", "structure", "bim"):
        raise ValueError(f"unknown library kind: {kind}")
    return {"problems": check(kind, text, materials_text)}  # type: ignore[arg-type]


def generate_building(floor_plan_text: str, bim_text: str | None) -> dict[str, Any]:
    """The building model generated from the floor plan, keeping the model's own elements.

    Returns ``{"text": ...}``, or ``{"problems": [...]}`` when the floor plan (or the current
    building model) has errors that must be fixed first.
    """
    import json

    from pydantic import ValidationError

    from saengine.library.bim import BuildingModel, generate, source_stamp
    from saengine.library.floorplan import FloorPlan

    def messages(exc: ValidationError, where: str) -> list[str]:
        result = []
        for error in exc.errors():
            message = error["msg"].removeprefix("Value error, ")
            path = ".".join(str(p) for p in error["loc"])
            result.append(f"{where}: {path}: {message}" if path else f"{where}: {message}")
        return result

    try:
        plan = FloorPlan.model_validate_json(floor_plan_text)
    except ValidationError as exc:
        return {"problems": messages(exc, "Floor plan")}
    previous = None
    if bim_text:
        try:
            data = json.loads(bim_text)
        except json.JSONDecodeError:
            data = None
        # Older or placeholder files have nothing of their own to keep.
        if isinstance(data, dict) and data.get("schema") == "saengine.bim/2":
            try:
                previous = BuildingModel.model_validate(data)
            except ValidationError as exc:
                return {"problems": messages(exc, "Building model")}
    try:
        model = generate(plan, source_stamp(floor_plan_text), previous)
    except ValueError as exc:
        return {"problems": [str(exc)]}
    data = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {"text": json.dumps(data, indent="\t", ensure_ascii=False) + "\n"}


def generate_building_from_structure(structure_text: str, bim_text: str | None) -> dict[str, Any]:
    """The building model of a special structure, keeping the model's own elements.

    Returns ``{"text": ...}``, or ``{"problems": [...]}`` when the structural model (or the
    current building model) has errors that must be fixed first.
    """
    import json

    from pydantic import ValidationError

    from saengine.library.bim import BuildingModel, generate_from_structure, source_stamp
    from saengine.library.structure import StructuralModel

    try:
        structure = StructuralModel.model_validate_json(structure_text)
    except ValidationError as exc:
        return {"problems": _messages(exc, "Structural model")}
    previous = None
    if bim_text:
        try:
            data = json.loads(bim_text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and data.get("schema") == "saengine.bim/2":
            try:
                previous = BuildingModel.model_validate(data)
            except ValidationError as exc:
                return {"problems": _messages(exc, "Building model")}
    model = generate_from_structure(structure, source_stamp(structure_text), previous)
    data = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {"text": json.dumps(data, indent="\t", ensure_ascii=False) + "\n"}


def building_ifc(
    bim_text: str, objects_text: str, materials_text: str | None, name: str
) -> dict[str, Any]:
    """The IFC of the building model: ``{"text", "ids", "skipped"}`` or ``{"problems"}``.

    ``ids`` maps element ids to IFC GlobalIds, for the 3D view to link elements to the project.
    """
    from pydantic import ValidationError

    from saengine.library.bim import BuildingModel
    from saengine.library.ifc import export_ifc
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    try:
        building = BuildingModel.model_validate_json(bim_text)
        objects = ObjectLibrary.model_validate_json(objects_text)
    except ValidationError as exc:
        return {"problems": [str(e["msg"]) for e in exc.errors()]}
    try:
        materials = MaterialLibrary.model_validate_json(materials_text) if materials_text else None
    except ValidationError:
        materials = None  # material names fall back to their ids
    ifc, ids, skipped = export_ifc(building, objects, materials, name)
    return {"text": ifc.to_string(), "ids": ids, "skipped": skipped}


def derive_fem(
    bim_text: str,
    objects_text: str,
    materials_text: str,
    settings_text: str,
    model_folder: str | None = None,
) -> dict[str, Any]:
    """The analysis model (``model.osmodel`` text) of the building model with the settings' loads.

    Returns ``{"text", "notes", "summary"}`` (and ``"pushoverText"``, the pushover model, when
    the settings ask for pushovers), or ``{"problems"}`` when an input has errors.
    """
    import json

    from pydantic import ValidationError

    from saengine.fem.derive import derive_fem as derive
    from saengine.fem.derive import stamp
    from saengine.library.bim import BuildingModel
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import ProjectSettings

    inputs = {
        "bim": (BuildingModel, bim_text, "Building model"),
        "objects": (ObjectLibrary, objects_text, "Object types"),
        "materials": (MaterialLibrary, materials_text, "Materials"),
        "settings": (ProjectSettings, settings_text, "Project settings"),
    }
    parsed = {}
    for key, (model, text, label) in inputs.items():
        try:
            parsed[key] = model.model_validate_json(text)
        except ValidationError as exc:
            return {
                "problems": [
                    f"{label}: {e['msg'].removeprefix('Value error, ')}" for e in exc.errors()
                ]
            }
    stamps = {key: stamp(text) for key, (_, text, _) in inputs.items()}
    derivation = derive(
        parsed["bim"],
        parsed["objects"],
        parsed["materials"],
        parsed["settings"],
        stamps,
        model_folder,
    )
    result = {
        "text": json.dumps(derivation.project, indent="\t", ensure_ascii=False) + "\n",
        "notes": derivation.notes,
        "summary": derivation.summary,
    }
    if derivation.pushover is not None:
        result["pushoverText"] = (
            json.dumps(derivation.pushover, indent="\t", ensure_ascii=False) + "\n"
        )
    return result


def _messages(exc: Any, where: str) -> list[str]:
    return [
        f"{where}: {'.'.join(str(p) for p in e['loc'])}: {e['msg'].removeprefix('Value error, ')}"
        for e in exc.errors()
    ]


def shape_geometry(shape: dict[str, Any]) -> dict[str, Any]:
    """The members, areas and supports of a parametric shape, to preview and insert.

    Returns the geometry (see ``saengine.library.shapes.Geometry.to_json``) or ``{"problems"}``.
    """
    from pydantic import ValidationError

    from saengine.library.shapes import ShapeInput
    from saengine.library.shapes import shape_geometry as build

    try:
        parsed = ShapeInput.model_validate({"shape": shape}).shape
    except ValidationError as exc:
        problems = []
        for e in exc.errors():
            field = ".".join(str(p) for p in e["loc"][2:])  # without "shape" and the kind
            message = e["msg"].removeprefix("Value error, ")
            problems.append(f"{field}: {message}" if field else message[:1].upper() + message[1:])
        return {"problems": problems}
    return build(parsed).to_json()


def import_geometry(path: str, options: dict[str, Any], objects_text: str | None) -> dict[str, Any]:
    """The geometry of a DXF, IFC or Rhino file, typed with the options and object types."""
    import json

    from pydantic import ValidationError

    from saengine.library.importers import ImportOptions
    from saengine.library.importers import import_geometry as read

    try:
        parsed = ImportOptions.model_validate(options)
    except ValidationError as exc:
        return {"problems": _messages(exc, "Options")}
    kinds: dict[str, str] = {}
    try:
        objects = json.loads(objects_text) if objects_text else {}
        kinds = {
            o["id"]: o["kind"] for o in objects.get("objects", []) if "id" in o and "kind" in o
        }
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass  # no layer-named types then
    try:
        return read(path, parsed, kinds).to_json()
    except Exception as exc:  # noqa: BLE001 - unreadable files are reported to the user
        return {"problems": [f"{Path(path).name}: {exc}"]}


def insert_geometry(structure_text: str, geometry: dict[str, Any]) -> dict[str, Any]:
    """The structural model with previewed geometry added: ``{"text", "ids", "skipped"}``."""
    import json

    from pydantic import ValidationError

    from saengine.library.shapes import Geometry, insert
    from saengine.library.structure import StructuralModel

    try:
        model = StructuralModel.model_validate_json(structure_text)
        result, ids, skipped = insert(model, Geometry.from_json(geometry))
    except ValidationError as exc:
        return {"problems": _messages(exc, "Structural model")}
    data = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    return {
        "text": json.dumps(data, indent="\t", ensure_ascii=False) + "\n",
        "ids": ids,
        "skipped": skipped,
    }


def run_script(structure_text: str, script_path: str) -> dict[str, Any]:
    """Runs a structural model script (see ``saengine.library.script``)."""
    from pydantic import ValidationError

    from saengine.library.script import run_script as run

    try:
        return run(structure_text, script_path)
    except ValidationError as exc:
        return {"error": "; ".join(_messages(exc, "Structural model")), "output": ""}


def design_report(out_dir: str, project_path: str) -> dict[str, Any]:
    """The RC member design checks of a run (see ``saengine.design.check``)."""
    from saengine.design import design_report as report

    return report(out_dir, project_path)


def compute_boq(bim_text: str, objects_text: str, materials_text: str) -> dict[str, Any]:
    """The bill of quantities (``10 BOQ/boq.json`` text) of the building model:
    ``{"text", "notes"}``, or ``{"problems"}`` when an input has errors."""
    from saengine.boq import compute_boq_text

    return compute_boq_text(bim_text, objects_text, materials_text)


def build_report(project_root: str, out_pdf: str | None = None) -> dict[str, Any]:
    """The PDF design report of the project (see ``saengine.report.build_report``)."""
    from saengine.report import build_report as build

    return build(project_root, out_pdf)
