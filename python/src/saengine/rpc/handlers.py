"""Request handlers, kept free of any transport so they can be tested directly.

Every handler takes and returns plain JSON-compatible values.
"""

from __future__ import annotations

import math
import platform
import threading
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
        if results.n_steps > 1 and len(results.load_factors) and not results.stage_names:
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
        from saengine.fem.thermal import load_corrections

        settings = settings_beside(project_file)
        if settings is not None:
            payload = _json.loads(Path(project_file).read_text(encoding="utf-8"))
            thermal = load_corrections(project_file)
            # The response spectrum design combinations (E = the scaled spectrum), when the
            # project designs from it and its modal-force run is there (fem/seismicDesign).
            from saengine.fem import seismic_design as rs

            seismic = rs.load_summary(out_dir) if rs.design_uses_spectrum(settings) else None
            cases.extend(combination_results(out_dir, payload, settings, thermal, seismic=seismic))
    return {"cases": cases}


def result_list(out_dir: str, project_path: str) -> dict[str, Any]:
    """The results of a run that can be shown in 3D (see ``saengine.fem.display``)."""
    from saengine.fem.display import result_list as listing

    return listing(out_dir, project_path)


def result_view(out_dir: str, project_path: str, key: str, mode: int | None) -> dict[str, Any]:
    """One result's deflected shape and force diagrams (see ``saengine.fem.display``)."""
    from saengine.fem.display import result_view as view

    return view(out_dir, project_path, key, mode)


def check_library(kind: str, text: str, materials_text: str | None = None) -> dict[str, Any]:
    from saengine.library.check import check_library as check

    if kind not in (
        "materials",
        "objects",
        "settings",
        "floorPlan",
        "structure",
        "bim",
        "reportTemplate",
        "worksheet",
    ):
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
    bim_text: str,
    objects_text: str,
    materials_text: str | None,
    name: str,
    substructure_text: str | None = None,
    settings_text: str | None = None,
    mep_text: str | None = None,
    architecture_text: str | None = None,
    rebar_root: str | None = None,
) -> dict[str, Any]:
    """The IFC of the building model: ``{"text", "ids", "skipped"}`` or ``{"problems"}``.

    With ``rebar_root`` (the project's folder) the reinforcement cages of its beams and columns
    are in the model too, as IfcReinforcingBar keyed ``rebar:<member>/<n>``
    (``saengine.pipeline.drawings.rebar_cages``: the detailing of the drawings, from the files
    on disk and the last analysis run's kept design).

    With ``mep_text`` (``07 MEP/mep.json``) its equipment, plinths, sleeves, openings and shafts
    are in the model too; with ``architecture_text`` (``05 Floor Plan/architecture.json``) its
    walls, doors, windows, rooms and finishes, keyed ``arch:<id>`` in ``ids``.

    ``ids`` maps element ids to IFC GlobalIds, for the 3D view to link elements to the project.
    With ``substructure_text`` (``09 Substructure/substructure.json``, once it is no longer the
    placeholder) the foundations are its own, founded from the ground level of ``settings_text``.
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
    substructure, ground, problems = _substructure_inputs(
        substructure_text, settings_text, building
    )
    if problems:
        return {"problems": problems}
    from saengine.library.mep import parse as parse_mep

    try:
        mep = parse_mep(mep_text)
    except ValueError as exc:
        return {"problems": [f"MEP: {_first_line(exc)}"]}
    has_mep = bool(
        mep.equipment
        or mep.openings
        or mep.shafts
        or (mep.plumbing is not None and (mep.plumbing.tanks or mep.plumbing.risers))
        or (mep.hvac is not None and (mep.hvac.plant or mep.hvac.ducts))
        or (
            mep.electrical is not None
            and (mep.electrical.equipment or mep.electrical.risers or mep.electrical.trays)
        )
    )
    from saengine.library.architecture import parse as parse_architecture

    try:
        architecture = parse_architecture(architecture_text)
    except ValueError as exc:
        return {"problems": [f"Architecture: {_first_line(exc)}"]}
    rebar = None
    rebar_notes: list[str] = []
    if rebar_root:
        from saengine.pipeline.drawings import DrawingsError, rebar_cages

        try:
            rebar = rebar_cages(rebar_root, check=False)
        except (DrawingsError, ValueError, OSError) as exc:
            rebar_notes.append(f"Reinforcement: {_first_line(exc)}")
    ifc, ids, skipped = export_ifc(
        building,
        objects,
        materials,
        name,
        substructure,
        ground,
        mep if has_mep else None,
        architecture if architecture.instances() else None,
        rebar,
    )
    skipped = [*skipped, *rebar_notes]
    hosts = {w.id: w.base for w in architecture.walls}
    stories = {
        **{f"arch:{w.id}": w.base for w in architecture.walls},
        **{f"arch:{o.id}": hosts[o.wall] for o in [*architecture.doors, *architecture.windows]},
        **{
            f"arch:{key}": r.story
            for r in architecture.rooms
            for key in (r.id, f"{r.id}:flooring", f"{r.id}:ceiling")
        },
        **{f"arch:{c.id}": c.base for c in [*architecture.curtainWalls, *architecture.railings]},
        **{f"arch:{i.id}": i.story for i in [*architecture.roofs, *architecture.ramps]},
    }
    return {
        "text": ifc.to_string(),
        "ids": ids,
        "skipped": skipped,
        "architectureStories": {k: v for k, v in stories.items() if k in ids},
    }


def architecture_import_ifc(
    path: str, architecture_text: str | None, floor_plan_text: str
) -> dict[str, Any]:
    """Adopts an architect's IFC (walls, doors, windows, spaces) into the architecture:
    ``{"architecture": <json>, "summary": {"adopted", "skipped", "notes"}}`` or ``{"problems"}``.
    """
    from pydantic import ValidationError

    from saengine.library.architecture import parse as parse_architecture
    from saengine.library.architecture_ifc import import_architecture
    from saengine.library.export import library_json
    from saengine.library.floorplan import FloorPlan

    try:
        architecture = parse_architecture(architecture_text)
        floor_plan = FloorPlan.model_validate_json(floor_plan_text)
    except (ValidationError, ValueError) as exc:
        return {"problems": [_first_line(exc)]}
    if not floor_plan.stories:
        return {"problems": ["The floor plan has no stories to put the architecture on."]}
    elevations = {s.id: s.elevation for s in floor_plan.stories}
    try:
        result, summary = import_architecture(path, architecture, elevations)
    except (OSError, RuntimeError, ValidationError, ValueError) as exc:
        return {"problems": [f"The IFC could not be read: {_first_line(exc)}"]}
    data = library_json(result)
    # The adopted items as the editor writes them: without their default values.
    for key in ("walls", "doors", "windows", "rooms", "separators"):
        data[key] = [
            item.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_defaults=True)
            for item in getattr(result, key)
        ]
    return {"architecture": data, "summary": summary}


def architecture_inspect_drawing(path: str) -> dict[str, Any]:
    """An architect's DWG/DXF for the layer-mapping step: its layers (entity counts, block names,
    sample texts), unit and a preview (``saengine.library.architecture_dxf.inspect_drawing``), or
    ``{"problems"}``."""
    from saengine.library.architecture_dxf import inspect_drawing
    from saengine.library.dwg import DwgError

    try:
        return inspect_drawing(path)
    except (DwgError, OSError, ValueError) as exc:
        return {"problems": [f"The drawing could not be read: {_first_line(exc)}"]}
    except Exception as exc:  # noqa: BLE001 - ezdxf raises its own errors for broken files
        return {"problems": [f"The drawing could not be read: {_first_line(exc)}"]}


def architecture_import_drawing(
    path: str, architecture_text: str | None, floor_plan_text: str, options: dict[str, Any]
) -> dict[str, Any]:
    """Adopts an architect's DWG/DXF plan (walls, doors, windows, room names) onto one story:
    ``{"architecture": <json>, "summary": {"adopted", "skipped", "notes", "replaced"}}`` or
    ``{"problems"}``. ``options``: see ``saengine.library.architecture_dxf.import_drawing``."""
    from pydantic import ValidationError

    from saengine.library.architecture import parse as parse_architecture
    from saengine.library.architecture_dxf import import_drawing
    from saengine.library.dwg import DwgError
    from saengine.library.export import library_json
    from saengine.library.floorplan import FloorPlan

    try:
        architecture = parse_architecture(architecture_text)
        floor_plan = FloorPlan.model_validate_json(floor_plan_text)
    except (ValidationError, ValueError) as exc:
        return {"problems": [_first_line(exc)]}
    elevations = {s.id: s.elevation for s in floor_plan.stories}
    try:
        result, summary = import_drawing(path, architecture, elevations, options or {})
    except (DwgError, OSError, ValidationError, ValueError) as exc:
        return {"problems": [f"The drawing could not be imported: {_first_line(exc)}"]}
    data = library_json(result)
    # The adopted items as the editor writes them: without their default values.
    for key in ("walls", "doors", "windows", "rooms", "separators"):
        data[key] = [
            item.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_defaults=True)
            for item in getattr(result, key)
        ]
    return {"architecture": data, "summary": summary}


def architecture_check(architecture_text: str, floor_plan_text: str | None) -> dict[str, Any]:
    """Problems of the architecture, with its rooms' net floor outlines and areas:
    ``{"problems", "rooms": {id: {"outline", "area"}}}`` (areas in m²)."""
    from pydantic import ValidationError

    from saengine.library.architecture import check, parse, room_boundary
    from saengine.library.floorplan import FloorPlan

    try:
        architecture = parse(architecture_text)
    except (ValidationError, ValueError) as exc:
        return {"problems": [_first_line(exc)], "rooms": {}}
    floor_plan = None
    if floor_plan_text:
        try:
            floor_plan = FloorPlan.model_validate_json(floor_plan_text)
        except (ValidationError, ValueError):
            floor_plan = None
    rooms: dict[str, Any] = {}
    if floor_plan is not None:
        elevations = {s.id: s.elevation for s in floor_plan.stories}
        for room in architecture.rooms:
            boundary = room_boundary(architecture, room, elevations)
            if boundary is not None:
                rooms[room.id] = {
                    "outline": [list(p) for p in list(boundary[1].exterior.coords)[:-1]],
                    "area": boundary[1].area / 1e6,
                }
    return {"problems": check(architecture, floor_plan), "rooms": rooms}


def architecture_ramps(architecture_text: str, settings_text: str | None) -> dict[str, Any]:
    """Every ramp of the architecture checked against the ramp rules of the code pack the
    settings choose (``saengine.design.ramps.check_ramps``), or ``{"problems"}``."""
    from pydantic import ValidationError

    from saengine.design.ramps import check_ramps
    from saengine.library.architecture import parse
    from saengine.library.settings import ProjectSettings

    try:
        architecture = parse(architecture_text)
    except (ValidationError, ValueError) as exc:
        return {"problems": [_first_line(exc)], "ramps": []}
    settings = None
    if settings_text:
        try:
            settings = ProjectSettings.model_validate_json(settings_text)
        except (ValidationError, ValueError):
            settings = None
    return {"problems": [], **check_ramps(architecture, settings)}


def _substructure_inputs(
    substructure_text: str | None, settings_text: str | None, building: Any = None
) -> tuple[Any, float, list[str]]:
    """The substructure that is the source of the foundations (None while it is the placeholder:
    the building model's footings are), the ground level, and problems with either file."""
    from pydantic import ValidationError

    from saengine.library.settings import ProjectSettings
    from saengine.substructure.handover import authoritative_substructure

    try:
        substructure = authoritative_substructure(substructure_text, building)
    except ValidationError as exc:
        return None, 0.0, _messages(exc, "Substructure")
    except ValueError as exc:
        return None, 0.0, [f"Substructure: {exc}"]
    ground = 0.0
    if settings_text:
        try:
            ground = ProjectSettings.model_validate_json(settings_text).foundation.groundLevel
        except ValidationError:
            pass  # the settings editor reports it; the ground then stays at 0
    return substructure, ground, []


def derive_fem(
    bim_text: str,
    objects_text: str,
    materials_text: str,
    settings_text: str,
    model_folder: str | None = None,
    soil_text: str | None = None,
    mep_text: str | None = None,
    substructure_text: str | None = None,
    loads_text: str | None = None,
    architecture_text: str | None = None,
) -> dict[str, Any]:
    """The analysis model (``model.osmodel`` text) of the building model with the settings' loads.

    Returns ``{"text", "notes", "summary"}`` (and ``"pushoverText"``, the pushover model, when
    the settings ask for pushovers; ``"thermalText"``, the temperature case's fixed-end forces
    for ``08 FEM/thermal.json``, when the settings have the case T; ``"ssiText"``, the soil
    springs for ``08 FEM/ssi.json``, when the column supports are soil springs), or
    ``{"problems"}`` when an input has errors.

    ``mep_text`` (``07 MEP/mep.json``) and ``substructure_text`` (``09 Substructure/
    substructure.json``: for soil springs, and for the earth pressure H on basement walls) are
    read beside ``model_folder`` when not
    given. The MEP file's stamp (of what the model takes from it, ``derive.mep_stamp``) is recorded
    (key ``mep``) once it is more than the placeholder,
    the substructure's (key ``substructure``) when the supports are soil springs.

    ``loads_text`` (``05 Floor Plan/loads.json``, :mod:`saengine.library.line_loads`, read
    beside ``model_folder`` when not given): the line and point loads on members; its stamp is
    recorded (key ``loads``) once it has a load. With end offsets the result also has
    ``"facesText"``, the support face offsets for ``08 FEM/faces.json``
    (:mod:`saengine.fem.end_zones`).

    ``architecture_text`` (``05 Floor Plan/architecture.json``, read beside ``model_folder``
    when not given): its walls and rooms load the model (:mod:`saengine.fem.architecture_loads`);
    its stamp is recorded (key ``architecture``) once it has a wall or a room.

    The site class is resolved here (``saengine.library.settings.resolve_site_class``): with
    the source "From the soil report", the soil report's governing class replaces the entered
    one. ``soil_text`` is the soil report's text; when it is not given, the project's
    ``01 Soil Report/soil-report.json`` beside ``model_folder`` (``08 FEM``) is read. The soil
    report's stamp is recorded with the other sources (key ``soil``) whenever the source is
    "From the soil report", even when the report gives no class yet.
    """
    import json

    from pydantic import ValidationError

    from saengine.fem.derive import derive_fem as derive
    from saengine.fem.derive import mep_stamp, model_text, objects_stamp, settings_stamp, stamp
    from saengine.library.bim import BuildingModel
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary
    from saengine.library.settings import ProjectSettings, read_soil_text, resolve_site_class

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
    # The settings without the project's details and title block (X28): typing a name there
    # leaves the model current.
    stamps["settings"] = settings_stamp(settings_text)
    # Nor the bars (N-X9): a bar-only Apply leaves the analysis current.
    stamps["objects"] = objects_stamp(objects_text)
    if soil_text is None and model_folder:
        soil_text = read_soil_text(Path(model_folder).parent)
    settings, site = resolve_site_class(parsed["settings"], soil_text)
    # The soil report is a source whenever the settings take the site class from it, also while
    # it gives no class yet (placeholder, no boreholes): boreholes added later then make the
    # model out of date.
    if parsed["settings"].site.siteClassSource == "soilReport" and soil_text is not None:
        stamps["soil"] = stamp(soil_text)
    site_notes = [site["note"]] if site["source"] == "soilReport" else []
    from saengine.library import mep as mep_library
    from saengine.library import substructure as substructure_library

    root = Path(model_folder).parent if model_folder else None
    if mep_text is None and root is not None:
        mep_text = _read(root / mep_library.MEP_FILE)
    try:
        mep = mep_library.parse(mep_text)
    except ValueError as exc:
        return {"problems": [f"MEP: {_first_line(exc)}"]}
    if mep_text and _has_content(mep):
        stamps["mep"] = mep_stamp(mep_text)
    from saengine.library import line_loads as ll

    if loads_text is None and root is not None:
        loads_text = _read(root / ll.LOADS_FILE)
    try:
        member_loads = ll.parse(loads_text)
    except ValueError as exc:
        return {"problems": [f"Line loads: {_first_line(exc)}"]}
    if member_loads.loads:
        stamps["loads"] = stamp(loads_text or "")
    from saengine.fem.architecture_loads import has_loads
    from saengine.library import architecture as arch_lib

    if architecture_text is None and root is not None:
        architecture_text = _read(root / arch_lib.ARCHITECTURE_FILE)
    try:
        architecture = arch_lib.parse(architecture_text)
    except ValueError as exc:
        return {"problems": [f"Architecture: {_first_line(exc)}"]}
    if has_loads(architecture):
        stamps["architecture"] = stamp(architecture_text or "")
    # The substructure: the foundations of the soil springs, and the earth pressure options and
    # retaining walls of the basement walls' case H (saengine.substructure.basement_loads).
    from saengine.substructure.basement_loads import has_earth_pressure

    springs = settings.analysis.supports == "soilSprings"
    if substructure_text is None and root is not None:
        substructure_text = _read(root / substructure_library.SUBSTRUCTURE_FILE)
    try:
        substructure = substructure_library.parse(substructure_text)
    except ValueError as exc:
        if springs:
            return {"problems": [f"Substructure: {_first_line(exc)}"]}
        substructure = None
    earth = has_earth_pressure(parsed["bim"], parsed["objects"], substructure)
    if springs or earth:
        stamps["substructure"] = stamp(substructure_text or "")
        if soil_text is not None:
            stamps["soil"] = stamp(soil_text)
    derivation = derive(
        parsed["bim"],
        parsed["objects"],
        parsed["materials"],
        settings,
        stamps,
        model_folder,
        mep=mep if _has_content(mep) else None,
        substructure=substructure,
        soil_text=soil_text,
        member_loads=member_loads if member_loads.loads else None,
        architecture=architecture if has_loads(architecture) else False,
    )
    if model_folder:
        from saengine.report.build import keep_derivation

        # The derivation's notes and code values for the report (it need not derive again).
        keep_derivation(model_folder, derivation)
    result = {
        "text": model_text(derivation.project),
        "notes": site_notes + list(derivation.notes),
        "summary": derivation.summary,
    }
    if derivation.pushover is not None:
        result["pushoverText"] = model_text(derivation.pushover)
    if derivation.thermal is not None:
        result["thermalText"] = json.dumps(derivation.thermal)
    if derivation.ssi is not None:
        result["ssiText"] = json.dumps(derivation.ssi, indent="\t", ensure_ascii=False) + "\n"
    if derivation.faces is not None:
        result["facesText"] = json.dumps(derivation.faces, ensure_ascii=False)
    return result


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _first_line(exc: Exception) -> str:
    return str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__


def _has_content(mep: Any) -> bool:
    """Whether an MEP model has anything the analysis model takes (equipment, openings, shafts,
    an overhead plumbing tank)."""
    from saengine.mep.loads import has_model_content

    return has_model_content(mep)


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

    from saengine.library.dwg import DwgError
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
    except DwgError as exc:  # names the file already
        return {"problems": [str(exc)]}
    except Exception as exc:  # noqa: BLE001 - unreadable files are reported to the user
        return {"problems": [f"{Path(path).name}: {exc}"]}


def convert_dwg(path: str, cache: str | None = None) -> dict[str, Any]:
    """A DWG drawing as DXF (``saengine.library.dwg``): ``{"ok", "dxf", "warnings", "cached"}``,
    or ``{"ok": False, "code", "message"}`` (``code`` ``"no-converter"`` or ``"failed"``)."""
    from saengine.library.dwg import ConverterMissing, DwgError, convert

    try:
        return {"ok": True, **convert(path, cache).to_json()}
    except ConverterMissing as exc:
        return {"ok": False, "code": "no-converter", "message": str(exc)}
    except DwgError as exc:
        return {"ok": False, "code": "failed", "message": str(exc)}


def convert_pdf(path: str, page: int | None = None, cache: str | None = None) -> dict[str, Any]:
    """One page of an architect's PDF as DXF (``saengine.library.pdf_underlay``): ``{"ok",
    "dxf", "page", "pages", "vector", "size", "segments", "warnings", "cached"}``, or ``{"ok":
    False, "code": "failed", "message"}``."""
    from saengine.library.pdf_underlay import PdfError, convert

    try:
        return {"ok": True, **convert(path, int(page or 1), cache).to_json()}
    except PdfError as exc:
        return {"ok": False, "code": "failed", "message": str(exc)}


def workbook_export(
    out_path: str, floor_plan_text: str, objects_text: str | None, loads_text: str | None
) -> dict[str, Any]:
    """The model as an Excel workbook (``saengine.library.workbook``): ``{"ok", "path",
    "sheets"}`` or ``{"ok": False, "message"}``."""
    from saengine.library.workbook import export_workbook

    try:
        return {"ok": True, **export_workbook(out_path, floor_plan_text, objects_text, loads_text)}
    except (OSError, ValueError) as exc:
        return {"ok": False, "message": str(exc)}


def workbook_import(
    path: str, floor_plan_text: str, objects_text: str | None, loads_text: str | None
) -> dict[str, Any]:
    """An edited model workbook read against the current files: ``{"ok", "problems", "diff",
    "texts", "changed"}`` (``saengine.library.workbook.import_workbook``)."""
    from saengine.library.workbook import import_workbook

    try:
        return import_workbook(path, floor_plan_text, objects_text, loads_text)
    except (OSError, ValueError) as exc:
        return {"ok": False, "problems": [str(exc)], "diff": {}, "texts": {}, "changed": []}


def ai_search_code(
    query: str, project_root: str | None = None, limit: int = 8, docs: bool = True
) -> dict[str, Any]:
    """The passages of the code pack in force (and the manual) that best match ``query``, each
    with its clauses (``saengine.ai.knowledge.search_code``): ``{pack, query, found, passages,
    note}``. The AI assistant answers code questions only from these; ``found`` False means the
    pack does not cover the question."""
    from saengine.ai.knowledge import search_code

    if not isinstance(query, str) or not query.strip():
        return {"ok": False, "message": "query is empty", "problems": ["query is empty"]}
    return search_code(query, project_root, limit, include_docs=docs)


def installer_components() -> dict[str, Any]:
    """The setup's optional components the backend runs, found as the backend finds them for
    use (``find_energyplus``, ``find_converter``): ``{"energyplus", "libredwg"}``, each
    ``{"state": "installed" | "elsewhere" | "missing", "path"?}``. ``installed``: the component's
    copy in the app folder; ``elsewhere``: another copy (the environment variable, an installed
    program), which works too. LibreCAD is found by the workbench (``findCadProgram``)."""
    from saengine.hvac.energyplus import bundled_dir as energyplus_dir
    from saengine.hvac.energyplus import find_energyplus
    from saengine.library.dwg import bundled_dir as libredwg_dir
    from saengine.library.dwg import find_converter

    def state(exe: Path | None, bundled: Path) -> dict[str, Any]:
        if exe is None:
            return {"state": "missing"}
        inside = exe.resolve().is_relative_to(bundled.resolve())
        return {"state": "installed" if inside else "elsewhere", "path": str(exe)}

    return {
        "energyplus": state(find_energyplus(), energyplus_dir()),
        "libredwg": state(find_converter(), libredwg_dir()),
    }


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
    """The RC member design checks of a run (see ``saengine.design.check``): the ones kept for
    the run's inputs (``saengine.pipeline.design_mode.report``: Run All, Apply, the design view
    and the proposal share one run of the checks per change of the project)."""
    from saengine.pipeline.design_mode import report

    return report(out_dir, project_path) or {}


def strut_and_tie(model: Any, project_path: str | None) -> dict[str, Any]:
    """One strut-and-tie model of a D-region solved and checked
    (``saengine.design.stm_model.check_model``) with the code pack the project of the analysis
    model ``project_path`` chooses; ``{"problems"}`` when the model is not valid."""
    from pydantic import ValidationError

    from saengine.codes import context as code_context
    from saengine.design.stm_model import check_model
    from saengine.library.strut_and_tie import StmModel
    from saengine.pipeline.design_mode import _plain

    try:
        parsed = StmModel.model_validate(model)
    except ValidationError as exc:
        return {"problems": _messages(exc, "Strut-and-tie model"), "checks": [], "ok": False}
    settings = _project_settings(project_path) if project_path else None
    try:
        pack = code_context.pack_for(settings, project_path)
    except Exception:  # noqa: BLE001 - a pack that cannot load: the default's procedure
        pack = None
    with code_context.using(pack):
        return _plain(check_model(parsed))


def strut_and_tie_template(kind: str, parameters: dict[str, float] | None) -> dict[str, Any]:
    """A strut-and-tie model to start from (``saengine.design.stm_model.template``), or
    ``{"error"}``."""
    from saengine.design.stm_model import template

    try:
        return {"model": template(kind, parameters).model_dump(mode="json")}
    except ValueError as exc:
        return {"error": str(exc)}


def _project_settings(project_path: str) -> Any:
    """The project settings of the model ``project_path`` (two folders up), with the site class
    the analysis uses; None when they cannot be read."""
    from pydantic import ValidationError

    from saengine.library.settings import ProjectSettings, read_soil_text, resolve_site_class

    root = Path(project_path).resolve().parent.parent
    try:
        settings = ProjectSettings.model_validate_json(
            (root / "02 Project Settings/project-settings.json").read_text(encoding="utf-8")
        )
    except (OSError, ValidationError):
        return None
    return resolve_site_class(settings, read_soil_text(root))[0]


def seismic_design(out_dir: str, project_path: str) -> dict[str, Any] | None:
    """The response spectrum design of a run (``saengine.fem.seismic_design.seismic_design``,
    run=True: the modal-force run is made once per analysis run): its scaling, orthogonal rule,
    accidental torsion, drifts and combinations; None when the project designs for earthquake
    from the static cases (``analysis.seismicDesign``)."""
    from saengine.design.check import ensure_seismic_design
    from saengine.fem import seismic_design as rs
    from saengine.pipeline.design_mode import _plain

    settings = _project_settings(project_path)
    if settings is None or not rs.design_uses_spectrum(settings):
        return None
    summary = ensure_seismic_design(out_dir, project_path, settings)
    if summary is None:
        summary = rs.seismic_design(out_dir, project_path, settings, run=False)
    return _plain({k: v for k, v in summary.items() if k != "run"})


def second_order_summary(out_dir: str, project_path: str) -> dict[str, Any] | None:
    """What the P-Delta analysis of a run changed (``saengine.fem.second_order.
    drift_amplification`` with the stories, I and Cd): ``{"method": "pDelta", "stiffness",
    "cases", "notes"}``; ``{"method": "none", "stiffness"}`` for a first-order model."""
    import json

    from saengine.fem import second_order
    from saengine.library.settings import derived
    from saengine.pipeline.design_mode import _plain

    settings = _project_settings(project_path)
    stiffness = getattr(getattr(settings, "analysis", None), "stiffness", None)
    try:
        project = json.loads(Path(project_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not second_order.is_second_order(project):
        return {"method": "none", "stiffness": stiffness, "cases": []}
    levels = _story_levels(project_path)
    values = derived(settings) if settings is not None else {}
    result = second_order.drift_amplification(
        project,
        out_dir,
        levels=levels,
        importance=values.get("seismicImportance"),
        cd=values.get("Cd"),
    )
    return _plain({"method": "pDelta", "stiffness": stiffness, **result})


def _story_levels(project_path: str) -> list[float] | None:
    """The building's storey elevations [m] (``06 BIM/bim.json``); None for a special structure
    or when it cannot be read."""
    from pydantic import ValidationError

    from saengine.library.bim import BuildingModel

    root = Path(project_path).resolve().parent.parent
    try:
        building = BuildingModel.model_validate_json(
            (root / "06 BIM/bim.json").read_text(encoding="utf-8")
        )
    except (OSError, ValidationError):
        return None
    if building.source is not None and building.source.structure is not None:
        return None
    return sorted({s.elevation / 1e3 for s in building.stories}) or None


def compute_boq(
    bim_text: str,
    objects_text: str,
    materials_text: str,
    substructure_text: str | None = None,
    settings_text: str | None = None,
    mep_text: str | None = None,
    project_root: str | None = None,
    architecture_text: str | None = None,
) -> dict[str, Any]:
    """The bill of quantities (``10 BOQ/boq.json`` text) of the building model, the
    substructure, the MEP plinths and sleeves, the plumbing (tanks, pipes, fixtures) and the
    architecture (brickwork, plaster, finishes, doors and windows): ``{"text", "notes"}``, or
    ``{"problems"}`` when an input has errors. ``project_root``: where the plumbing tanks' last
    designs are read from (their bars), and the architecture when ``architecture_text`` is not
    given."""
    from saengine.boq import compute_boq_text

    return compute_boq_text(
        bim_text,
        objects_text,
        materials_text,
        substructure_text,
        settings_text,
        mep_text,
        project_root,
        architecture_text,
    )


def cost_boq(
    boq_text: str, rates_text: str | None = None, carbon_text: str | None = None
) -> dict[str, Any]:
    """The bill priced by the schedule of rates, with its embodied carbon
    (``saengine.boq.costing``): ``{"costing", "sampleRates"}`` or ``{"problems"}``."""
    from saengine.boq.costing import cost_texts

    return cost_texts(boq_text, rates_text, carbon_text)


def boq_templates() -> dict[str, str]:
    """The texts a project's ``10 BOQ/rates.json`` and ``carbon-factors.json`` start from: the
    sample schedule (made-up rates) and the carbon factors shipped."""
    from saengine.boq.costing import default_carbon_text, sample_rates_text

    return {"rates": sample_rates_text(), "carbon": default_carbon_text()}


def export_boq_xlsx(
    path: str,
    boq_text: str,
    rates_text: str | None = None,
    carbon_text: str | None = None,
    title: str = "",
) -> dict[str, Any]:
    """The bill, its costing and embodied carbon written to an Excel workbook
    (``saengine.boq.workbook``)."""
    from saengine.boq.workbook import write_boq_xlsx_texts

    return write_boq_xlsx_texts(path, boq_text, rates_text, carbon_text, title)


def build_report(
    project_root: str,
    out_pdf: str | None = None,
    format: str = "pdf",
    template: str | None = None,
) -> dict[str, Any]:
    """The design report of the project, PDF or Word (see ``saengine.report.build_report``)."""
    from saengine.report import build_report as build

    return build(project_root, out_pdf, format=format, template=template)


def report_templates(project_root: str) -> dict[str, Any]:
    """The report templates the project can print (built-in and its own) and the one its
    settings name: ``{"templates": [{id, name, source, path?}], "current"}``."""
    from saengine.library.report_template import DEFAULT_TEMPLATE_ID, list_templates
    from saengine.report.build import _Parts

    settings = _Parts(Path(project_root), []).settings()
    current = getattr(getattr(settings, "report", None), "template", None) or DEFAULT_TEMPLATE_ID
    return {"templates": list_templates(project_root), "current": current}


def report_template_create(
    project_root: str, template_id: str, base: str | None = None, name: str | None = None
) -> dict[str, Any]:
    """Writes a new report template ``template_id`` into the project, a copy of ``base`` (a
    built-in or project template; the default when not given): ``{"path"}`` or ``{"problems"}``.
    An existing file is never overwritten."""
    import re

    from saengine.library.report_template import (
        TEMPLATE_ID_PATTERN,
        load_template,
        save_template,
        template_path,
    )

    if not re.match(TEMPLATE_ID_PATTERN, template_id):
        return {
            "problems": [
                f"'{template_id}' is not a template id: lower-case letters, digits and hyphens."
            ]
        }
    if template_path(project_root, template_id).exists():
        return {"path": str(template_path(project_root, template_id)), "existing": True}
    template, problems = load_template(project_root, base)
    if problems:
        return {"problems": problems}
    copy = template.model_copy(update={"id": template_id, "name": name or template.name})
    return {"path": str(save_template(project_root, copy))}


# ─────────────────────────────────────── soil report ───────────────────────────────────────


def soil_report(soil_text: str, settings_text: str | None = None) -> dict[str, Any]:
    """Everything computed from the soil report (see ``saengine.soil.soil_report``), with the
    site class of the settings resolved as the analysis uses it."""
    from saengine.library.settings import resolve_settings_text
    from saengine.soil import soil_report as compute

    return compute(soil_text, resolve_settings_text(settings_text, soil_text))


def allowable_bearing(
    soil_text: str,
    settings_text: str | None,
    x_mm: float,
    y_mm: float,
    founding_level_mm: float,
    b_mm: float,
    l_mm: float,
) -> dict[str, Any]:
    """Net allowable bearing pressure of a footing (see ``saengine.soil.allowable_bearing``)."""
    from saengine.soil import allowable_bearing as compute

    return compute(soil_text, settings_text, x_mm, y_mm, founding_level_mm, b_mm, l_mm)


def import_soil(path: str, soil_text: str | None = None) -> dict[str, Any]:
    """The soil report with the boreholes of a CSV or Excel file merged in:
    ``{"text", "notes"}`` or ``{"problems"}``."""
    from saengine.soil import import_soil as read

    return read(path, soil_text)


def soil_template(path: str) -> dict[str, Any]:
    """Writes the borehole import template (.csv or .xlsx): ``{"path"}`` or ``{"problems"}``."""
    from saengine.soil import soil_template as write

    return write(path)


def soil_settlement(
    soil_text: str, borehole: str, b_mm: float, l_mm: float, df_mm: float, q_kpa: float
) -> dict[str, Any]:
    """Settlement of a footing at a borehole under a net pressure."""
    from saengine.soil import footing_settlement

    return footing_settlement(soil_text, borehole, b_mm, l_mm, df_mm, q_kpa)


def soil_sources(soil_text: str | None, settings_text: str | None = None) -> dict[str, Any]:
    """Where the site class and the allowable bearing pressure come from, for Project Settings.

    Returns ``{"site", "soil", "bearing"}``: ``site`` the info of ``resolve_site_class`` (the
    class the analysis uses and its source), ``soil`` the soil report's own class
    (``soil_site_class``), ``bearing`` ``{"source": "override" | "soilReport" | "none",
    "override", "boreholes", "note"}``.
    """
    from pydantic import ValidationError

    from saengine.library.settings import (
        ProjectSettings,
        default_project_settings,
        resolve_site_class,
        soil_site_class,
    )

    try:
        settings = (
            ProjectSettings.model_validate_json(settings_text)
            if settings_text
            else default_project_settings()
        )
    except ValidationError:
        settings = default_project_settings()
    _, site = resolve_site_class(settings, soil_text)
    soil = site["soil"] if site["soil"] is not None else soil_site_class(soil_text, settings)
    boreholes = soil.get("boreholes", 0)
    override = settings.foundation.allowableBearing
    if override:
        source = "override"
        note = f"qa = {override:g} kPa, the override, for every footing."
    elif boreholes:
        source = "soilReport"
        note = (
            "qa per footing from 1 Soil Report: the lowest of the boreholes within 10 m (else "
            "the nearest), at the footing's founding level, B and L."
        )
    else:
        source = "none"
        note = "No qa: the footings are designed without the bearing check."
    return {
        "site": site,
        "soil": soil,
        "bearing": {
            "source": source,
            "override": override,
            "boreholes": boreholes,
            "note": note,
            "levels": _ground_levels(soil_text, settings.foundation.groundLevel)
            if source == "soilReport"
            else None,
        },
    }


def _ground_levels(soil_text: str | None, finished: float) -> str | None:
    """A note when Project Settings → Foundation's ground level differs (by more than 100 mm)
    from the ground of a borehole: qa is net of the overburden below the borehole's ground."""
    from saengine.soil.report import parse

    report = parse(soil_text or "")
    if isinstance(report, list):
        return None
    differ = [
        f"{bh.id} {report.ground_level(bh) / 1e3:+.2f} m"
        for bh in report.boreholes
        if abs(report.ground_level(bh) - finished) > 100
    ]
    if not differ:
        return None
    return (
        f"The finished ground ({finished / 1e3:+.2f} m) differs from the ground of "
        + ", ".join(differ)
        + ": qa is net of the overburden below each borehole's ground, so fill above it is "
        "taken as a load and a cut is flagged in the footing's notes."
    )


# ─────────────────────────────────────── substructure ───────────────────────────────────────


def _problem(error: Exception) -> dict[str, Any]:
    from pydantic import ValidationError

    if isinstance(error, ValidationError):
        return {"problems": _messages(error, "9 Substructure")}
    return {"problems": [str(error) or type(error).__name__]}


def substructure_report(project_root: str) -> dict[str, Any]:
    """The design checks of the project's saved substructure (see
    ``saengine.substructure.substructure_report``), or ``{"problems"}`` when a part of the
    project cannot be read.

    The result adds ``sources``: the stamp of each part file the design reads, by part id ("" for
    a missing file), taken before the design reads them, so the part list can tell when the
    checks no longer describe the project (an edit while the design runs counts as a change)."""
    from saengine.substructure import substructure_report as report

    sources = substructure_sources(project_root)
    try:
        result = report(project_root)
    except ValueError as error:
        return _problem(error)
    return {**result, "sources": sources}


def substructure_design(project_root: str) -> dict[str, Any]:
    """Run All's foundation step (``saengine.substructure.run.design_foundations``): moves the
    building model's footings in while the substructure is the placeholder, gives foundations
    without bars the minimum mesh (``summary["barsAdded"]``) and checks them. The same answer as
    :func:`substructure_report`, with ``sources`` taken after the bars were written (they are
    part of what was checked), or ``{"problems"}``."""
    from saengine.substructure.run import design_foundations

    try:
        result = design_foundations(project_root)
    except ValueError as error:
        return _problem(error)
    if result.get("problems") and result.get("foundations") is None:
        return result
    return {**result, "sources": substructure_sources(project_root)}


#: The part files the foundation design reads, by the part ids the workbench knows them under
#: (besides the analysis results, which the part list compares by time).
SUBSTRUCTURE_SOURCES = {
    "soil": "01 Soil Report/soil-report.json",
    "settings": "02 Project Settings/project-settings.json",
    "materials": "03 Materials/materials.json",
    "objects": "04 Objects/objects.json",
    "bim": "06 BIM/bim.json",
    "substructure": "09 Substructure/substructure.json",
}


def substructure_sources(project_root: str) -> dict[str, str]:
    """The stamp of each of :data:`SUBSTRUCTURE_SOURCES` in the project ("" when missing)."""
    from pathlib import Path

    from saengine.library.bim import source_stamp

    stamps: dict[str, str] = {}
    for part, relative in SUBSTRUCTURE_SOURCES.items():
        try:
            stamps[part] = source_stamp((Path(project_root) / relative).read_text(encoding="utf-8"))
        except OSError:
            stamps[part] = ""
    return stamps


def substructure_size(
    project_root: str, columns: list[str] | None = None, substructure_text: str | None = None
) -> dict[str, Any]:
    """Footings proposed for ``columns`` (default: the columns without a foundation) from the
    reactions and the soil report, with the editor's substructure ``substructure_text`` when
    given: ``{"foundations", "designs", "notes"}`` or ``{"problems"}``."""
    from saengine.substructure.context import Skip, load_context
    from saengine.substructure.sizing import propose

    try:
        return propose(
            load_context(project_root, substructure_text=substructure_text), columns=columns
        )
    except Skip as reason:  # no analysis results yet
        return {"foundations": [], "designs": [], "notes": [f"Nothing sized: {reason}."]}
    except ValueError as error:
        return _problem(error)


def substructure_migrate(project_root: str) -> dict[str, Any]:
    """The saved substructure with the building model's footings added (nothing is written):
    ``{"substructure", "notes", "count"}`` or ``{"problems"}``."""
    from saengine.substructure import migrate_project

    try:
        return migrate_project(project_root)
    except (OSError, ValueError) as error:
        return _problem(error)


# ─────────────────────────────────────── MEP coordination ───────────────────────────────────────


def _mep_call(call: Any) -> dict[str, Any]:
    try:
        return call()
    except ValueError as error:
        return {"problems": [_first_line(error)]}


def mep_report(
    project_root: str, out_dir: str | None = None, mep_text: str | None = None
) -> dict[str, Any]:
    """The MEP coordination report (``saengine.mep.mep_report``), or ``{"problems"}``."""
    from saengine.mep import mep_report as report

    return _mep_call(lambda: report(project_root, out_dir, mep_text))


def mep_suggest_sleeves(
    project_root: str, mep_text: str | None = None, allowance: float | None = None
) -> dict[str, Any]:
    """Sleeves and openings that would coordinate the clashes (``{openings, notes}``)."""
    from saengine.mep import mep_suggest_sleeves as suggest

    return _mep_call(
        lambda: suggest(project_root, 25.0 if allowance is None else allowance, mep_text)
    )


def mep_import_ifc(project_root: str, path: str, copy: bool = False) -> dict[str, Any]:
    """What an MEP IFC model holds (its discipline and elements), for 07 MEP's model list."""
    from saengine.mep import mep_import_ifc as inspect

    try:
        return inspect(project_root, path, copy)
    except (OSError, RuntimeError, ValueError) as error:
        return {"problems": [f"{Path(path).name}: {_first_line(error)}"]}


def mep_coordinate(
    project_root: str, mep_text: str | None = None, tests: list[str] | None = None
) -> dict[str, Any]:
    """Runs the clash tests and merges their clashes into the coordination issues
    (``saengine.mep.coordination.coordinate``), or ``{"problems"}``."""
    from saengine.mep.coordination import coordinate

    try:
        return coordinate(project_root, mep_text, tests)
    except (OSError, RuntimeError, ValueError) as error:
        return {"problems": [_first_line(error)]}


def _coordination(project_root: str, mep_text: str | None) -> Any:
    from saengine.library.mep import MEP_FILE, parse
    from saengine.mep.coordination import coordination_of

    if mep_text is None:
        try:
            mep_text = (Path(project_root) / MEP_FILE).read_text(encoding="utf-8")
        except OSError:
            mep_text = None
    mep = parse(mep_text)
    return mep, coordination_of(mep)


def mep_export_bcf(
    project_root: str, path: str, mep_text: str | None = None, issues: list[str] | None = None
) -> dict[str, Any]:
    """Writes the coordination issues (``issues``: their ids, else all) to the BCF 3.0 file
    ``path``: ``{"path", "topics"}`` or ``{"problems"}``."""
    from saengine.mep.bcf import export_bcf

    try:
        mep, coordination = _coordination(project_root, mep_text)
        files = ["SAEngine model"] + [m.path for m in mep.ifcModels]
        files += [m.path for m in coordination.models]
        Path(path).write_bytes(export_bcf(coordination, files, issues))
    except (OSError, ValueError) as error:
        return {"problems": [_first_line(error)]}
    count = len([i for i in coordination.issues if issues is None or i.id in issues])
    return {"path": path, "topics": count}


def mep_import_bcf(project_root: str, path: str, mep_text: str | None = None) -> dict[str, Any]:
    """Merges the topics of the BCF file ``path`` into the coordination issues:
    ``{"coordination", "counts"}`` or ``{"problems"}``."""
    import zipfile
    from xml.etree.ElementTree import ParseError

    from saengine.mep.bcf import merge_bcf, read_bcf

    try:
        _, coordination = _coordination(project_root, mep_text)
        topics = read_bcf(Path(path).read_bytes())
        merged, counts = merge_bcf(coordination, topics)
    except (OSError, ValueError, zipfile.BadZipFile, ParseError) as error:
        return {"problems": [_first_line(error)]}
    return {
        "coordination": merged.model_dump(mode="json", by_alias=True, exclude_none=True),
        "counts": counts,
    }


def mep_check_ids(project_root: str, mep_text: str | None = None) -> dict[str, Any]:
    """Checks the models against the coordination's IDS files (``saengine.mep.ids``):
    ``{"coordination", "results", "counts", "notes"}`` or ``{"problems"}`` (also when
    IfcTester is not installed)."""
    from saengine.mep.ids import check_ids

    try:
        return check_ids(project_root, mep_text)
    except (OSError, RuntimeError, ValueError) as error:
        return {"problems": [_first_line(error)]}


# ─────────────────────────────────────── plumbing (Part 7) ───────────────────────────────────────


#: One plumbing report at a time: the server runs them in worker threads (a project's first tank
#: designs take half a minute), and they share the tank designs' cache file.
_PLUMBING_LOCK = threading.Lock()


def plumbing_report(
    project_root: str, mep_text: str | None = None, designs: bool | str = True
) -> dict[str, Any]:
    """The plumbing report (BNBC 2020 Part 8 sizing, tank designs, hydraulics), JSON-safe
    (``saengine.plumbing.project.full_report``); never raises. ``designs="cached"``: the quick
    first pass, with the tank designs not yet cached listed as pending."""
    from saengine.plumbing.project import full_report

    try:
        if designs == "cached":
            return full_report(project_root, mep_text, designs="cached")
        with _PLUMBING_LOCK:
            return full_report(project_root, mep_text, designs=bool(designs))
    except Exception as error:  # noqa: BLE001 - a partly entered model must not fail the RPC
        return {"problems": [f"the plumbing report failed: {_first_line(error)}"]}


def plumbing_size_tanks(project_root: str, mep_text: str | None = None) -> dict[str, Any]:
    """The tanks SAEngine proposes, in 07 MEP's ``plumbing.tanks`` format: ``{tanks, notes}``
    or ``{problems}``."""
    from saengine.plumbing.project import finite
    from saengine.plumbing.report import plumbing_report as report

    result = report(project_root, mep_text)
    if "tanks" not in result:
        return {"problems": result.get("problems") or ["no plumbing report"]}
    return finite({"tanks": result["tanks"], "notes": result.get("notes", [])})


def plumbing_sleeves(project_root: str, mep_text: str | None = None) -> dict[str, Any]:
    """The sleeves the risers and stacks still need through the slabs (07 MEP openings, those
    no opening of 07 MEP already gives): ``{openings, notes}`` or ``{problems}``."""
    from saengine.library.mep import MEP_FILE, parse
    from saengine.plumbing.project import finite, missing_sleeves
    from saengine.plumbing.report import plumbing_report as report

    result = report(project_root, mep_text)
    if "sleeves" not in result:
        return {"problems": result.get("problems") or ["no plumbing report"]}
    text = mep_text if mep_text is not None else _read(Path(project_root) / MEP_FILE)
    try:
        missing = missing_sleeves(parse(text), result["sleeves"])
    except ValueError as error:
        return {"problems": [f"{MEP_FILE} is not valid: {_first_line(error)}"]}
    return finite({"openings": missing, "notes": result.get("notes", [])})


def plumbing_occupancies() -> dict[str, Any]:
    """BNBC 2020 Part 8 Table 8.5.1's occupancies: ``{occupancies: [{key, label, lpcd, ...}]}``."""
    from saengine.plumbing.project import occupancies

    return {"occupancies": occupancies()}


def warm_plumbing() -> None:
    """Imports the hydraulics (WNTR's first import takes a second or two) ahead of the editor's
    first plumbing report."""
    import contextlib

    # Only a head start: when it fails, the report says what is missing.
    with contextlib.suppress(Exception):
        import saengine.plumbing.hydraulics  # noqa: F401


# ──────────────────────────── HVAC and electrical (Part 7) ────────────────────────────


def _finite(result: Any) -> Any:
    from saengine.plumbing.project import finite

    return finite(result)


def hvac_report(
    project_root: str, mep_text: str | None = None, calculate: bool = False
) -> dict[str, Any]:
    """The HVAC report of 7 MEP: the cooling loads (``saengine.hvac.report.hvac_loads``) at the
    top level and the air side, plant, shafts and duct openings (``saengine.hvac.air.hvac_air``)
    under ``air``. ``calculate`` False (the editor after each edit, Run All): EnergyPlus is not
    started; its cached run is used when it matches the input, else the estimate, with
    ``calculated`` False. ``calculate`` True: EnergyPlus version 26.2.0 runs (a separate
    process, about half a minute; :func:`hvac_cancel_loads` stops it). Never raises."""
    from saengine.hvac.air import hvac_air
    from saengine.hvac.report import hvac_loads

    try:
        loads = hvac_loads(project_root, mep_text, run_energyplus=calculate)
    except Exception as error:  # noqa: BLE001 - a partly entered model must not fail the RPC
        return {"problems": [f"the cooling loads failed: {_first_line(error)}"]}
    try:
        air = hvac_air(project_root, loads=loads, mep_text=mep_text)
    except Exception as error:  # noqa: BLE001
        air = {"problems": [f"the air side failed: {_first_line(error)}"], "checks": []}
    loads.pop("stamp", None)
    return _finite({**loads, "air": air})


def hvac_cancel_loads() -> dict[str, Any]:
    """Stops the EnergyPlus runs in progress: ``{cancelled: n}``."""
    from saengine.hvac.energyplus import cancel_runs

    return {"cancelled": cancel_runs()}


def _fast_loads(project_root: str, mep_text: str | None) -> dict[str, Any] | None:
    from saengine.hvac.report import hvac_loads

    try:
        return hvac_loads(project_root, mep_text, run_energyplus=False)
    except Exception:  # noqa: BLE001 - the caller works without the loads
        return None


def hvac_propose_plant(project_root: str, mep_text: str | None = None) -> dict[str, Any]:
    """The plant SAEngine proposes (07 MEP ``hvac.plant`` entries, ``sized``) for the loads last
    calculated (else the estimate): ``{plant, notes, ...}`` or ``{problems}``."""
    from saengine.hvac.plant import hvac_propose_plant as propose

    try:
        return _finite(propose(project_root, _fast_loads(project_root, mep_text), mep_text))
    except Exception as error:  # noqa: BLE001
        return {"problems": [f"the plant could not be proposed: {_first_line(error)}"]}


def hvac_duct_openings(project_root: str, mep_text: str | None = None) -> dict[str, Any]:
    """The openings the ducts need through beams and slabs (07 MEP openings, each passing its
    checks; ``replaces`` an accepted one when a duct moved), the conflicts with their options
    and the ``stale`` openings: ``{openings, conflicts, stale, notes}`` or ``{problems}``."""
    from saengine.hvac.openings import hvac_duct_openings as openings

    try:
        return _finite(openings(project_root, _fast_loads(project_root, mep_text), mep_text))
    except Exception as error:  # noqa: BLE001
        return {"problems": [f"the duct openings could not be found: {_first_line(error)}"]}


def hvac_tables() -> dict[str, Any]:
    """BNBC 2020 Part 8 Table 8.2.2's stations (2 % cooling design conditions, Sec 2.12.2.1)
    and Table 8.2.3's occupancies: ``{cities: [{key, label, db, wb, range}], uses: [{key,
    label, perPerson, perArea, density, source}]}``."""
    from saengine.hvac import tables as T

    cities = [
        {
            "key": s.key,
            "label": s.name,
            "db": s.cooling[T.DESIGN_LEVEL][0],
            "wb": s.cooling[T.DESIGN_LEVEL][1],
            "range": s.range,
        }
        for s in T.STATIONS.values()
    ]
    uses = [
        {
            "key": v.key,
            "label": v.label,
            "perPerson": v.perPerson,
            "perArea": v.perArea,
            "density": v.density,
            "source": "BNBC 2020 Part 8 Table 8.2.3",
        }
        for v in T.VENTILATION.values()
    ]
    return {"cities": cities, "uses": uses}


def hvac_constructions() -> dict[str, Any]:
    """The envelope constructions SAEngine knows (typical Bangladeshi walls and roofs, glazing
    from EnergyPlus version 26.2.0's data sets) with their U-values: ``{wall, roof, glazing}``
    lists of ``{key, label, u, shgc?}``."""
    from saengine.hvac import constructions as C

    return {
        "wall": [
            {"key": k, "label": c.label, "u": round(C.u_value(c), 3)} for k, c in C.WALLS.items()
        ],
        "roof": [
            {"key": k, "label": c.label, "u": round(C.u_value(c, roof=True), 3)}
            for k, c in C.ROOFS.items()
        ],
        "glazing": [
            {"key": k, "label": g.label, "u": g.u, "shgc": g.shgc} for k, g in C.GLAZINGS.items()
        ],
    }


def electrical_report(project_root: str, mep_text: str | None = None) -> dict[str, Any]:
    """The electrical report of 7 MEP (``saengine.electrical.report.electrical_report``: demand,
    substation, generator, rooms, risers, trays, lightning protection), JSON-safe; never
    raises."""
    from saengine.electrical.report import electrical_report as report

    try:
        return report(project_root, mep_text)
    except Exception as error:  # noqa: BLE001
        return {"problems": [f"the electrical report failed: {_first_line(error)}"]}


def electrical_propose_equipment(project_root: str, mep_text: str | None = None) -> dict[str, Any]:
    """The electrical equipment SAEngine proposes (07 MEP ``electrical.equipment``, ``sized``):
    ``{equipment, notes}`` or ``{problems}``."""
    result = electrical_report(project_root, mep_text)
    if "equipment" not in result:
        return {"problems": result.get("problems") or ["no electrical report"]}
    return {"equipment": result["equipment"], "notes": result.get("notes", [])}


def electrical_openings(project_root: str, mep_text: str | None = None) -> dict[str, Any]:
    """The openings the risers and trays still need (07 MEP openings no opening of 07 MEP
    already gives): ``{openings, notes}`` or ``{problems}``."""
    result = electrical_report(project_root, mep_text)
    if "openings" not in result and "summary" not in result:
        return {"problems": result.get("problems") or ["no electrical report"]}
    notes = [n for n in result.get("notes", []) if isinstance(n, str) and "opening" in n]
    return {"openings": result.get("openings", []), "notes": notes}


def electrical_uses() -> dict[str, Any]:
    """BNBC 2020 Part 8 Table 8.1.17's occupancies (minimum load densities, W/m²):
    ``{uses: [{key, label, nonAc, ac, source}]}``."""
    from saengine.electrical.tables import USES

    return {
        "uses": [
            {"key": u.key, "label": u.label, "nonAc": u.non_ac, "ac": u.ac,
             "source": "BNBC 2020 Part 8 Table 8.1.17"}
            for u in USES.values()
        ]
    }  # fmt: skip


def fire_report(project_root: str, mep_text: str | None = None) -> dict[str, Any]:
    """The fire protection report of 7 MEP (``saengine.fire.report.fire_report``: the systems
    BNBC 2020 Part 4 requires, sprinklers, hydraulics, water, pumps, the fire tanks' designs,
    missing sleeves), JSON-safe; never raises."""
    from saengine.fire.report import fire_report as report

    try:
        return report(project_root, mep_text)
    except Exception as error:  # noqa: BLE001
        return {"problems": [f"the fire report failed: {_first_line(error)}"]}


def fire_propose(project_root: str, mep_text: str | None = None) -> dict[str, Any]:
    """The fire tanks and pumps SAEngine proposes (07 MEP ``fire.tanks`` and ``fire.pumps``,
    ``sized``): ``{tanks, pumps, notes}`` or ``{problems}``."""
    from saengine.fire.report import fire_report as report

    try:
        result = report(project_root, mep_text, designs=False)
    except Exception as error:  # noqa: BLE001
        return {"problems": [f"the fire report failed: {_first_line(error)}"]}
    if "proposals" not in result:
        return {"problems": result.get("problems") or ["no fire report"]}
    storage = result.get("storage") or {}
    return {**result["proposals"], "notes": storage.get("notes", [])}


def fire_openings(project_root: str, mep_text: str | None = None) -> dict[str, Any]:
    """The sleeves the fire risers and mains still need (07 MEP openings no opening of 07 MEP
    already gives): ``{openings, notes}`` or ``{problems}``."""
    from saengine.fire.report import fire_report as report

    try:
        result = report(project_root, mep_text, designs=False)
    except Exception as error:  # noqa: BLE001
        return {"problems": [f"the fire report failed: {_first_line(error)}"]}
    if "openings" not in result:
        return {"problems": result.get("problems") or ["no fire report"]}
    notes = [n for n in result.get("notes", []) if isinstance(n, str) and "sleeve" in n]
    return {"openings": result["openings"], "notes": notes}


def warm_services() -> None:
    """Imports the plumbing, HVAC, electrical and fire modules ahead of the editor's first
    report (the plumbing's tank design imports the design package: many seconds cold)."""
    import contextlib

    with contextlib.suppress(Exception):
        import saengine.electrical.report
        import saengine.fire.report
        import saengine.hvac.air
        import saengine.hvac.report
        import saengine.plumbing.project
        import saengine.plumbing.tanks  # noqa: F401


# ─────────────────────────────────────── soil springs ───────────────────────────────────────


def ssi_compare(project_root: str) -> dict[str, Any]:
    """Fixed base against soil springs (see ``saengine.fem.ssi_compare.compare``)."""
    from saengine.fem.ssi_compare import compare

    return _mep_call(lambda: compare(project_root))


def mesh_check(project_root: str) -> dict[str, Any]:
    """The mesh convergence check of Run All (``saengine.fem.mesh_check``): the beams' gravity
    end moments on the project's mesh and on one twice as coarse, written to ``08 FEM/
    model.results/mesh-check.json``; ``{"skipped": why}`` when the project needs none,
    ``{"problems"}`` when it could not be run."""
    from saengine.fem import mesh_check as mc

    root = Path(project_root)
    try:
        why = mc.needs_check(root)
        if why is not None:
            return {"skipped": why}
        result = mc.project_mesh_convergence(root)
    except (OSError, ValueError, KeyError) as error:
        return {"problems": [f"mesh check: {_first_line(error)}"]}
    folder = root / "08 FEM" / "model.results"
    if folder.is_dir():
        (folder / mc.MESH_CHECK_FILE).write_text(mc.dumps(result), encoding="utf-8")
    return result


def substructure_ensure(project_root: str) -> dict[str, Any]:
    """Writes the building model's footings into ``substructure.json`` while it is still the
    placeholder (``saengine.substructure.handover.ensure_migrated``)."""
    from saengine.substructure.handover import ensure_migrated

    return ensure_migrated(project_root)


# ───────────────────────────── the project archive and versions ─────────────────────────────


def _refusal(error: Exception) -> dict[str, Any]:
    """An archive or versions operation that was refused, as the workbench reads it:
    ``{ok: false, code, message, problems}`` (the message is written for the engineer)."""
    problems = list(getattr(error, "problems", None) or [])
    return {
        "ok": False,
        "code": getattr(error, "code", None) or (problems[0].get("code") if problems else None),
        "message": str(error),
        "problems": problems,
    }


def _part_statuses(project_root: str) -> dict[str, Any] | None:
    """The sidebar's status of each part, recorded in an archive's manifest (as the CLI does)."""
    from saengine.pipeline.project import ProjectError, open_project
    from saengine.pipeline.status import part_statuses

    try:
        project = open_project(project_root)
        return {s.part: s.to_json() for s in part_statuses(project)}
    except (ProjectError, OSError, ValueError):
        return None


def project_export_archive(
    project_root: str,
    out_path: str,
    include_results: bool = False,
    include_versions: bool = False,
    include_exports: bool = True,
    note: str | None = None,
    saengine_version: str | None = None,
) -> dict[str, Any]:
    """Writes the project into one ``.civil`` file (``saengine.project.archive.export_project``):
    ``{path, size, files, skipped, problems}``, or a refusal (:func:`_refusal`)."""
    from saengine.project.archive import ArchiveError, export_project

    try:
        return export_project(
            project_root,
            out_path,
            include_results=include_results,
            include_versions=include_versions,
            include_exports=include_exports,
            note=note,
            statuses=_part_statuses(project_root),
            saengine_version=saengine_version,
        )
    except (ArchiveError, OSError) as error:
        return _refusal(error)


def project_inspect_archive(
    path: str, current_version: str | None = None, verify: bool = True
) -> dict[str, Any]:
    """What a ``.civil`` file holds: ``{manifest|null, problems, ok, files, size}``."""
    from saengine.project.archive import ArchiveError, inspect_archive

    try:
        return inspect_archive(path, current_version, verify)
    except (ArchiveError, OSError) as error:
        return _refusal(error)


def project_import_archive(
    path: str,
    dest_parent: str,
    name: str | None = None,
    overwrite: bool = False,
    current_version: str | None = None,
    migrate: bool = True,
) -> dict[str, Any]:
    """Unpacks a ``.civil`` file into ``<dest_parent>/<name>``: ``{root, name, files, problems
    (warnings), migrated, pending, renamed?}``, or a refusal (nothing is left behind)."""
    from saengine.project.archive import ArchiveError, import_project

    try:
        return import_project(path, dest_parent, name, overwrite, current_version, migrate)
    except (ArchiveError, OSError) as error:
        return _refusal(error)


def _versions_call(call: Any) -> dict[str, Any]:
    from saengine.project.versions import VersionsError

    try:
        return call()
    except VersionsError as error:
        return _refusal(error)


def versions_status(project_root: str) -> dict[str, Any]:
    """What changed since the last version (``saengine.project.versions.status``)."""
    from saengine.project import versions

    return _versions_call(lambda: versions.status(project_root))


def versions_list(project_root: str, limit: int = 200) -> dict[str, Any]:
    """The versions, newest first: ``{versions, count, more}``."""
    from saengine.project import versions

    return _versions_call(lambda: versions.list_versions(project_root, int(limit)))


def versions_save(
    project_root: str,
    message: str,
    author: str | None = None,
    issued: bool = False,
    label: str | None = None,
) -> dict[str, Any]:
    """Saves the project's current files as a version: ``{version, created, initialized}``."""
    from saengine.project import versions

    return _versions_call(
        lambda: versions.save(project_root, message, author=author, issued=issued, label=label)
    )


def versions_diff(project_root: str, a: str | None = None, b: str | None = None) -> dict[str, Any]:
    """Two versions (or a version and the current files, ``b`` omitted) compared part by part."""
    from saengine.project import versions

    return _versions_call(lambda: versions.diff(project_root, a, b or versions.WORKING))


def versions_restore(
    project_root: str,
    version: str,
    parts: list[str] | None = None,
    author: str | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Brings back the files of ``parts`` (all when omitted) from ``version``, as a new change."""
    from saengine.project import versions

    return _versions_call(
        lambda: versions.restore(project_root, version, parts=parts, author=author, commit=commit)
    )


def versions_mark_issued(
    project_root: str, version: str, label: str, author: str | None = None
) -> dict[str, Any]:
    """Marks ``version`` as issued with ``label``: ``{version, tag}``."""
    from saengine.project import versions

    return _versions_call(lambda: versions.mark_issued(project_root, version, label, author=author))


# ─────────────────────────────────────── shared projects ───────────────────────────────────────


def share_status(project_root: str, user: str | None = None, fetch: bool = True) -> dict[str, Any]:
    """The office copy: ``{shared, location, kind, ahead, behind, locks, people, problems}``."""
    from saengine.project import share

    return _versions_call(lambda: share.status(project_root, user=user, fetch=fetch))


def share_connect(project_root: str, location: str, author: str | None = None) -> dict[str, Any]:
    """Shares the project at a shared folder or git server address, then syncs."""
    from saengine.project import share

    return _versions_call(lambda: share.connect(project_root, location, author=author))


def share_disconnect(project_root: str) -> dict[str, Any]:
    """Stops syncing this copy."""
    from saengine.project import share

    return _versions_call(lambda: share.disconnect(project_root))


def share_join(location: str, target: str) -> dict[str, Any]:
    """Copies a shared project into the new folder ``target``: ``{projectRoot}``."""
    from saengine.project import share

    return _versions_call(lambda: share.join(location, target))


def share_sync(
    project_root: str,
    author: str | None = None,
    resolutions: dict[str, str] | None = None,
    user: str | None = None,
) -> dict[str, Any]:
    """Saves, fetches, merges per part file and sends: ``{state, received, sent, conflicts}``."""
    from saengine.project import share

    return _versions_call(
        lambda: share.sync(project_root, author=author, resolutions=resolutions, user=user)
    )


def share_lock(
    project_root: str, part: str, user: str | None = None, note: str | None = None
) -> dict[str, Any]:
    """Takes the lock of a part in the shared folder: ``{lock}``."""
    from saengine.project import share

    return _versions_call(lambda: share.lock(project_root, part, user=user, note=note or ""))


def share_unlock(
    project_root: str, part: str, user: str | None = None, force: bool = False
) -> dict[str, Any]:
    """Releases (or with ``force`` breaks) the lock of a part: ``{released, was}``."""
    from saengine.project import share

    return _versions_call(lambda: share.unlock(project_root, part, user=user, force=force))


def share_heartbeat(
    project_root: str, user: str | None = None, part: str | None = None, leaving: bool = False
) -> dict[str, Any]:
    """Keeps (or with ``leaving`` ends) this engineer's presence: ``{available, people}``."""
    from saengine.project import share

    return _versions_call(
        lambda: share.heartbeat(project_root, user=user, part=part, leaving=leaving)
    )


# ─────────────────────────────────────── design mode ───────────────────────────────────────


def design_required(
    out_dir: str, project_path: str, options: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The reinforcement every designed element requires (``saengine.design.design_required``),
    kept beside the results while the project does not change
    (:mod:`saengine.pipeline.design_mode`)."""
    from saengine.pipeline.design_mode import required

    return required(out_dir, project_path, options)


def design_proposal(
    out_dir: str, project_path: str, options: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The bars SAEngine proposes per object type and foundation
    (``saengine.design.design_proposal``); an unknown mode is a ValueError."""
    from saengine.design import design_proposal as propose
    from saengine.pipeline.design_mode import _plain

    return _plain(propose(out_dir, project_path, options))


def design_apply_proposal(
    objects_text: str,
    bim_text: str | None,
    proposal: dict[str, Any],
    floor_plan_text: str | None = None,
    substructure_text: str | None = None,
) -> dict[str, Any]:
    """The part files with a proposal applied, as new texts (``saengine.design.apply_proposal``,
    pure). A project without a building model sends no ``bimText``: an empty one is used."""
    from saengine.design import apply_proposal

    return apply_proposal(
        objects_text, bim_text or "{}", proposal, floor_plan_text, substructure_text
    )


# ─────────────────────── structural models of other programs, steel sections ───────────────────────


def import_structural(
    path: str, dest_parent: str, name: str | None = None, overwrite: bool = False
) -> dict[str, Any]:
    """A new project from an ETABS (.e2k), STAAD.Pro (.std) or SAP2000 (.s2k) text file
    (``saengine.importers.project.import_structural``): ``{root, name, format, report,
    problems, files}``, or ``{error, problems}`` when the file cannot be imported."""
    from saengine.importers.project import StructuralImportError
    from saengine.importers.project import import_structural as run

    try:
        return run(path, dest_parent, name, overwrite)
    except StructuralImportError as error:
        return {"error": str(error), "problems": [str(error)]}


def new_building(
    spec: dict[str, Any],
    dest_parent: str,
    name: str | None = None,
    overwrite: bool = False,
    site: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Integrator glue: a new building project from a grid and storeys
    (``saengine.project.new_building.create_building``, the generator of
    ``saengine.library.generator``): ``{root, name, notes, summary, settingsPatch, files}``, or
    ``{error}`` when the spec is not valid or the folder holds files already. ``site``: the soil
    report's site the new project starts with (its plot, the grid aligned with it)."""
    from saengine.project.new_building import NewBuildingError, create_building

    try:
        return create_building(spec, dest_parent, name, overwrite, site)
    except NewBuildingError as error:
        return {"error": str(error), "notes": []}


def steel_sections() -> dict[str, Any]:
    """SAEngine's standard steel section table (``saengine.library.steel_sections``)."""
    from saengine.library.steel_sections import table_json

    return table_json()


# ─────────────────────────────────────── site map and GIS ───────────────────────────────────


def soil_location(
    soil_text: str | None, bim_text: str | None = None, settings_text: str | None = None
) -> dict[str, Any]:
    """Where the site, the boreholes and the building are (``saengine.gis.site.soil_location``)."""
    from saengine.gis.site import soil_location as locate

    return locate(soil_text, bim_text, settings_text)


def plot_check(
    soil_text: str | None, floor_plan_text: str | None, objects_text: str | None = None
) -> dict[str, Any]:
    """The plot and its buildable envelope in project mm, and the floor plan's members outside
    them (``saengine.gis.plot.encroachments``): ``{plot, envelope, warnings, problems}``."""
    from saengine.gis.plot import encroachments
    from saengine.soil.report import parse

    report = parse(soil_text or "")
    if isinstance(report, list):
        return {"plot": None, "envelope": None, "warnings": [], "problems": report}
    return encroachments(report.site, floor_plan_text, objects_text)


def gis_export(project_root: str, format: str, out_path: str) -> dict[str, Any]:
    """The site, boreholes and building outline as GeoJSON or GeoPackage (WGS 84)."""
    from saengine.gis.site import gis_export as export

    return export(project_root, format, out_path)


def gis_import(path: str, soil_text: str | None = None) -> dict[str, Any]:
    """The soil report with a GeoJSON or GeoPackage file's boreholes and boundary merged in."""
    from saengine.gis.site import gis_import as read

    try:
        return read(path, soil_text)
    except (OSError, ValueError) as error:
        return {"problems": [str(error) or type(error).__name__]}


def qgis_program() -> str | None:
    """The launcher of an installed QGIS, or None (QGIS is not bundled)."""
    from saengine.gis.site import qgis_program as find

    return find()


def qgis_command(program: str, file_path: str) -> list[str] | dict[str, Any]:
    """The program and arguments that open ``file_path`` in QGIS (a .bat launcher through
    cmd.exe, its last argument to pass verbatim), or ``{problems}`` for a path cmd.exe would
    interpret."""
    from saengine.gis.site import qgis_command as command

    try:
        return command(program, file_path)
    except ValueError as error:
        return {"problems": [str(error)]}


# ───────────────────────────── the structural drawings ─────────────────────────────


def drawings_generate(
    project_root: str,
    sheets: list[str] | None = None,
    size: str | None = None,
    design_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generates the drawings into ``11 Exports/Drawings`` (``saengine.pipeline.drawings``):
    the answer the Exports page reads, or ``{sheets: [], problems}`` when nothing is drawn.
    ``design_report``: the design checks Run All has just made (else those of the last run)."""
    from saengine.pipeline.drawings import DrawingsError, generate

    try:
        return generate(project_root, sheets or None, size or None, design_report=design_report)
    except DrawingsError as error:
        return {"sheets": [], "notes": [], "problems": [str(error)]}
    except (ValueError, OSError) as error:
        return {"sheets": [], "notes": [], "problems": [_first_line(error)]}


def drawings_list(project_root: str) -> dict[str, Any]:
    """The last generation's drawings with what is out of date (reads files only)."""
    from saengine.pipeline.drawings import list_drawings

    return list_drawings(project_root)


def drawings_issue(project_root: str, args: dict[str, Any]) -> dict[str, Any]:
    """Issues the drawing set (``saengine.pipeline.drawings.issue``): every sheet drawn again,
    the new or changed ones with the new revision, copied into ``Issued/<rev> <date>``; the
    answer of ``drawings_generate`` with ``issued``, or ``{sheets: [], problems}``."""
    from saengine.pipeline.drawings import DrawingsError, issue

    try:
        return issue(
            project_root,
            args.get("code") or None,
            args.get("date") or None,
            str(args.get("description") or ""),
            str(args.get("by") or ""),
            str(args.get("purpose") or ""),
            args.get("sheets") or None,
            force=bool(args.get("force")),
            dwg=bool(args.get("dwg")),
        )
    except DrawingsError as error:
        return {"sheets": [], "notes": [], "problems": [str(error)]}
    except (ValueError, OSError) as error:
        return {"sheets": [], "notes": [], "problems": [_first_line(error)]}


def drawings_dwg(project_root: str, sheets: list[str] | None = None) -> dict[str, Any]:
    """The current sheets as DWG (LibreDWG's dxf2dwg, a separate program):
    ``{written, folder, problems}``."""
    from saengine.pipeline.drawings import export_dwg

    try:
        return export_dwg(project_root, sheets or None)
    except OSError as error:
        return {"written": [], "folder": None, "problems": [_first_line(error)]}


def drawings_progress(project_root: str) -> dict[str, Any]:
    """Where a generation of the project is (``{running: false}`` when none runs)."""
    from saengine.pipeline.drawings import progress

    return progress(project_root)


def story_response(out_dir: str, project_path: str) -> dict[str, Any]:
    """The storey response, modal participation, spectrum and curves of a run (the FEM
    results' charts; ``saengine.fem.story_response``)."""
    from saengine.fem.story_response import story_response as compute

    return compute(out_dir, project_path)


def member_forces(out_dir: str, project_path: str, member: str) -> dict[str, Any]:
    """A member's section forces and deflection along it for every static case and load
    combination (the member detail window; ``saengine.fem.member_detail``)."""
    from saengine.fem.member_detail import member_forces as compute

    return compute(out_dir, project_path, member)


def column_interaction(out_dir: str, project_path: str, member: str | None) -> dict[str, Any]:
    """The P-M interaction diagrams of the run's concrete columns with their demand points
    (worked out once per run by the design checks; ``saengine.fem.member_detail``)."""
    from saengine.fem.member_detail import column_interaction as compute

    return compute(out_dir, project_path, member)


def export_xlsx(path: str, sheets: list[dict[str, Any]]) -> dict[str, Any]:
    """Result tables written to an Excel workbook (``saengine.fem.table_export``)."""
    from saengine.fem.table_export import write_xlsx

    return write_xlsx(path, sheets)


# ───────────────────────────────────────── code packs ─────────────────────────────────────────


def _pack_root(root: str | None) -> Path | None:
    from saengine.codes import context as code_context

    return code_context.find_project_root(root) if root else None


def _pack_info(info: Any, root: Path | None) -> dict[str, Any]:
    """A :class:`saengine.codes.PackInfo` as the Code Packs page reads it, with the manifest's
    author, licence, description and sources when the pack's pack.json can be read."""
    from saengine.codes.manifest import MANIFEST_FILE, PackManifest

    result = info.model_dump(mode="json")
    try:
        manifest = PackManifest.model_validate_json(
            (Path(info.path) / MANIFEST_FILE).read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError):
        return result
    result.update(
        author=manifest.author,
        licence=manifest.licence,
        description=manifest.description,
        sources=[s.model_dump(mode="json", exclude_none=True) for s in manifest.sources],
        clauses=manifest.clauses,
    )
    return result


def codes_list(root: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    """Every code pack found (built-in, the user's, the project's), shadowed ones included.

    ``kind``: a package kind (``designCode``, the default, ``structureTemplate``,
    ``buildingTemplate``), or ``all`` for every kind with each manifest's author, licence and
    description (the Packages page)."""
    from saengine.codes import registry
    from saengine.codes.manifest import KINDS

    base = _pack_root(root)
    if kind == "all":
        return [_pack_info(p, base) for p in registry.list_packs(base, None)]
    wanted = kind if kind in KINDS else "designCode"
    return [p.model_dump(mode="json") for p in registry.list_packs(base, wanted)]


def codes_templates(kind: str, root: str | None = None) -> dict[str, Any]:
    """The templates of the installed packages: ``structureTemplate`` → the Generate panel's
    presets, ``buildingTemplate`` → the wizard's specifications and the full templates
    (:mod:`saengine.codes.catalogue`)."""
    from saengine.codes import catalogue

    base = _pack_root(root)
    if kind == "structureTemplate":
        return catalogue.structure_presets(base)
    return catalogue.building_templates(base)


def codes_coded_geometry(
    package: str,
    file: str,
    values: dict[str, Any] | None = None,
    root: str | None = None,
    member_type: str | None = None,
) -> dict[str, Any]:
    """The geometry of a coded structure template (:func:`saengine.codes.coded.coded_geometry`),
    to preview and insert like a built-in shape's; ``{problems}`` when it cannot be made."""
    from saengine.codes.coded import coded_geometry

    return coded_geometry(package, file, values or {}, _pack_root(root), member_type=member_type)


def codes_check_template(path: str, author: str = "") -> dict[str, Any]:
    """``{ok, problems}``: whether the archive may be opened as a full building template
    (:func:`saengine.project.archive.template_problems`, plus :func:`inspect_archive`)."""
    from saengine.project.archive import inspect_archive, template_problems

    result = inspect_archive(path)
    problems = [*result.get("problems", []), *template_problems(path, author)]
    errors = [p for p in problems if p.get("severity", "error") == "error"]
    return {"ok": not errors, "problems": problems}


def codes_remove(
    pack_id: str, scope: str = "user", kind: str | None = None, root: str | None = None
) -> dict[str, Any]:
    """Removes the user's (or the project's) package ``pack_id`` of ``kind``: ``{ok, path}``."""
    from saengine.codes import CodePackError, registry
    from saengine.codes.manifest import KINDS

    base = _pack_root(root)
    try:
        folder = registry.uninstall(
            pack_id,
            "project" if scope == "project" else "user",
            base,
            kind if kind in KINDS else "designCode",
        )
    except (CodePackError, OSError) as error:
        return _refusal(error)
    return {"ok": True, "id": pack_id, "path": str(folder)}


def codes_show(pack_id: str, root: str | None = None) -> dict[str, Any]:
    """The pack in force with this id, with its manifest's details."""
    from saengine.codes import CodePackError, registry

    base = _pack_root(root)
    try:
        return _pack_info(registry.info(pack_id, base), base)
    except CodePackError as error:
        return _refusal(error)


def codes_new(
    pack_id: str,
    name: str,
    extends: str | None,
    scope: str = "user",
    dest: str | None = None,
    root: str | None = None,
) -> dict[str, Any]:
    """Writes a new pack's skeleton (:func:`saengine.codes.template.new_pack`) into ``dest``,
    else the user's packs or the project's (``scope``): ``{path}`` of its folder."""
    from saengine.codes import registry
    from saengine.codes.template import TemplateError, new_pack

    base = _pack_root(root)
    if not dest:
        if scope == "project":
            if base is None:
                return _refusal(ValueError("a project pack needs the project folder"))
            dest = str(registry.project_packs_dir(base))
        else:
            dest = str(registry.user_packs_dir())
    try:
        folder = new_pack(dest, pack_id, name or pack_id, extends or None, project_root=base)
    except TemplateError as error:
        return _refusal(error)
    registry.clear_cache()
    return {"ok": True, "path": str(folder), "manifest": str(folder / "pack.json")}


def codes_install(
    path: str, scope: str = "user", root: str | None = None, replace: bool = False
) -> dict[str, Any]:
    """Copies a pack folder or .zip into the user's packs or the project's: its info.
    ``replace``: an installed package of the same id and scope is replaced (an update)."""
    from saengine.codes import CodePackError, registry

    base = _pack_root(root)
    try:
        info = registry.install(
            Path(path), "project" if scope == "project" else "user", base, bool(replace)
        )
    except (CodePackError, OSError) as error:
        return _refusal(error)
    return _pack_info(info, base)


def codes_validate(path: str, root: str | None = None) -> dict[str, Any]:
    """The pack in ``path`` resolved against the installed packs, with its problems and the
    authoring warnings of :func:`saengine.codes.template.validate_pack`."""
    from saengine.codes import registry

    base = _pack_root(root)
    from saengine.codes.template import validate_pack

    info = registry.validate(Path(path), base).model_dump(mode="json")
    try:
        report = validate_pack(Path(path), base).to_json()
    except (OSError, ValueError) as error:  # the authoring checks are extra: never a failure
        report = {"problems": [{"level": "warning", "message": _first_line(error)}]}
    seen = {p.get("message") for p in info.get("problems", [])}
    for problem in report.get("problems", []):
        if problem.get("message") not in seen:
            info.setdefault("problems", []).append(
                {"severity": problem.get("level", "warning"), "message": problem["message"]}
            )
    return info


def codes_trust(
    pack_id: str, trusted: bool, root: str | None = None, kind: str | None = None
) -> dict[str, Any]:
    """Trusts (or stops trusting) the hooks of the package in force with this id and kind (a
    design code by default; a structure template's coded templates, round M5)."""
    from saengine.codes import CodePackError, registry
    from saengine.codes.manifest import KINDS

    base = _pack_root(root)
    try:
        info = registry.set_trusted(
            pack_id, bool(trusted), base, kind if kind in KINDS else "designCode"
        )
        return _pack_info(info, base)
    except CodePackError as error:
        return _refusal(error)


def worksheet_kinds() -> dict[str, Any]:
    """The calculation worksheet kinds and their inputs (``saengine.report.worksheets``)."""
    from saengine.report.worksheets import kinds

    return {"kinds": kinds()}


def worksheet_calculate(
    kind: str, inputs: dict[str, Any], project_root: str | None = None
) -> dict[str, Any]:
    """The calculation of a worksheet ``kind`` for ``inputs``, with the project's code pack."""
    from saengine.report.worksheets import calculate, project_pack

    with project_pack(project_root) as problems:
        result = calculate(kind, inputs)
    if problems:
        result.setdefault("notes", []).extend(problems)
    return result


def worksheet_list(project_root: str) -> dict[str, Any]:
    """The project's worksheets with their result (``{worksheets, problems}``)."""
    from saengine.report.worksheets import list_worksheets

    return list_worksheets(project_root)


def worksheet_create(
    project_root: str, kind: str, worksheet_id: str, title: str | None = None
) -> dict[str, Any]:
    """Writes a new worksheet of ``kind`` into the project: ``{path}`` or ``{problems}``."""
    from saengine.report.worksheets import create_worksheet

    return create_worksheet(project_root, kind, worksheet_id, title)
