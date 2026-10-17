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

    return view(out_dir, project_path, key, mode)


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
    bim_text: str,
    objects_text: str,
    materials_text: str | None,
    name: str,
    substructure_text: str | None = None,
    settings_text: str | None = None,
) -> dict[str, Any]:
    """The IFC of the building model: ``{"text", "ids", "skipped"}`` or ``{"problems"}``.

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
    substructure, ground, problems = _substructure_inputs(substructure_text, settings_text)
    if problems:
        return {"problems": problems}
    ifc, ids, skipped = export_ifc(building, objects, materials, name, substructure, ground)
    return {"text": ifc.to_string(), "ids": ids, "skipped": skipped}


def _substructure_inputs(
    substructure_text: str | None, settings_text: str | None
) -> tuple[Any, float, list[str]]:
    """The substructure that is the source of the foundations (None while it is the placeholder:
    the building model's footings are), the ground level, and problems with either file."""
    from pydantic import ValidationError

    from saengine.library.settings import ProjectSettings
    from saengine.substructure.handover import authoritative_substructure

    try:
        substructure = authoritative_substructure(substructure_text)
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
) -> dict[str, Any]:
    """The analysis model (``model.osmodel`` text) of the building model with the settings' loads.

    Returns ``{"text", "notes", "summary"}`` (and ``"pushoverText"``, the pushover model, when
    the settings ask for pushovers), or ``{"problems"}`` when an input has errors.

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
    from saengine.fem.derive import stamp
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
    if soil_text is None and model_folder:
        soil_text = read_soil_text(Path(model_folder).parent)
    settings, site = resolve_site_class(parsed["settings"], soil_text)
    # The soil report is a source whenever the settings take the site class from it, also while
    # it gives no class yet (placeholder, no boreholes): boreholes added later then make the
    # model out of date.
    if parsed["settings"].site.siteClassSource == "soilReport" and soil_text is not None:
        stamps["soil"] = stamp(soil_text)
    site_notes = [site["note"]] if site["source"] == "soilReport" else []
    derivation = derive(
        parsed["bim"],
        parsed["objects"],
        parsed["materials"],
        settings,
        stamps,
        model_folder,
    )
    result = {
        "text": json.dumps(derivation.project, indent="\t", ensure_ascii=False) + "\n",
        "notes": site_notes + list(derivation.notes),
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


def compute_boq(
    bim_text: str,
    objects_text: str,
    materials_text: str,
    substructure_text: str | None = None,
    settings_text: str | None = None,
) -> dict[str, Any]:
    """The bill of quantities (``10 BOQ/boq.json`` text) of the building model and the
    substructure: ``{"text", "notes"}``, or ``{"problems"}`` when an input has errors."""
    from saengine.boq import compute_boq_text

    return compute_boq_text(
        bim_text, objects_text, materials_text, substructure_text, settings_text
    )


def build_report(project_root: str, out_pdf: str | None = None) -> dict[str, Any]:
    """The PDF design report of the project (see ``saengine.report.build_report``)."""
    from saengine.report import build_report as build

    return build(project_root, out_pdf)


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


def substructure_size(project_root: str, columns: list[str] | None = None) -> dict[str, Any]:
    """Footings proposed for ``columns`` (default: the columns without a foundation) from the
    reactions and the soil report: ``{"foundations", "designs", "notes"}`` or ``{"problems"}``."""
    from saengine.substructure.context import Skip, load_context
    from saengine.substructure.sizing import propose

    try:
        return propose(load_context(project_root), columns=columns)
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


def substructure_ensure(project_root: str) -> dict[str, Any]:
    """Writes the building model's footings into ``substructure.json`` while it is still the
    placeholder (``saengine.substructure.handover.ensure_migrated``)."""
    from saengine.substructure.handover import ensure_migrated

    return ensure_migrated(project_root)
