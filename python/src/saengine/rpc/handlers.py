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

    if kind not in ("materials", "objects"):
        raise ValueError(f"unknown library kind: {kind}")
    return {"problems": check(kind, text, materials_text)}  # type: ignore[arg-type]
