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
        # Full histories are large; the workbench asks for one node at a time (later phase).
        tables = []
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
    return {"cases": cases}


def check_library(kind: str, text: str, materials_text: str | None = None) -> dict[str, Any]:
    from saengine.library.check import check_library as check

    if kind not in ("materials", "objects", "floorPlan", "bim"):
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
