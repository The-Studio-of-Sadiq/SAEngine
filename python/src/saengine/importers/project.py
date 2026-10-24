"""Integrator glue: a new SAEngine project from an ETABS, STAAD.Pro or SAP2000 text file.

:func:`import_structural` picks the importer by the file's extension (``.e2k`` / ``.$et``:
:mod:`saengine.importers.etabs`; ``.std``: :mod:`saengine.importers.staad`; ``.s2k`` /
``.$2k``: :mod:`saengine.importers.sap2000`), writes the project into ``<dest>/<name>`` (the
parts 02-06, the manifest and ``import-report.json``; the other parts are filled in when the
project is opened, or by :func:`saengine.pipeline.project` callers) and returns its report.
Section names the file gives without dimensions are looked up in SAEngine's standard section
table (:mod:`saengine.library.steel_sections`: ``IPE300``, ``HEA 200``, ``SHS100X100X5``, ...).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

#: The importers by file extension (lower case).
FORMATS = {
    ".e2k": "etabs",
    ".$et": "etabs",
    ".std": "staad",
    ".s2k": "sap2000",
    ".$2k": "sap2000",
}

#: The parts the importers do not write: folder and (placeholder) main file, as a new project
#: made by the workbench has them (``placeholder`` of services/saengineProject).
_OTHER_PARTS = {
    "01 Soil Report": ("soil-report.json", "soil"),
    "07 MEP": ("mep.json", "mep"),
    "08 FEM": None,
    "09 Substructure": ("substructure.json", "substructure"),
    "10 BOQ": ("boq.json", "boq"),
    "11 Exports": None,
}


class StructuralImportError(ValueError):
    """The file cannot be imported (unknown format, unreadable, or the folder exists)."""


def section_lookup_noted(name: str) -> tuple[dict[str, Any], str | None] | None:
    """The 04 Objects profile of a steel section named ``name`` and the approximation made
    (None: exact), or None when the name cannot be read. The same reading as the STAAD and
    SAP2000 importers (:func:`saengine.importers.neutral.named_profile`): SAEngine's section
    table first (``IPE300``, ``HE200A``, ``SHS100X100X5``), then names that carry their
    dimensions, then W/UB/UC estimates and placeholder I-shapes (each reported)."""
    from saengine.importers.neutral import named_profile

    profile, note = named_profile(name)
    if profile is None:
        return None
    return profile.model_dump(), note


def section_lookup(name: str) -> dict[str, Any] | None:
    """The 04 Objects profile of the steel section named ``name`` (:func:`section_lookup_noted`
    without the approximation), or None."""
    found = section_lookup_noted(name)
    return found[0] if found else None


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "-", name).strip().strip(".") or "Imported"


def import_structural(
    path: str | Path, dest_parent: str | Path, name: str | None = None, overwrite: bool = False
) -> dict[str, Any]:
    """Imports ``path`` into a new project ``<dest_parent>/<name>`` (default: the model's own
    name): ``{"root", "name", "format", "report" (ImportReport.to_dict()), "problems", "files"}``.
    Raises :class:`StructuralImportError` when the file cannot be imported or the folder holds a project
    already (unless ``overwrite``)."""
    path = Path(path)
    kind = FORMATS.get(path.suffix.lower())
    if kind is None:
        raise StructuralImportError(
            f"{path.name}: not an ETABS (.e2k), STAAD.Pro (.std) or SAP2000 (.s2k) text file"
        )
    if not path.is_file():
        raise StructuralImportError(f"{path} does not exist")
    try:
        if kind == "etabs":
            from saengine.importers.etabs import read_e2k

            imported = read_e2k(path, name, section_lookup=section_lookup_noted)
        elif kind == "staad":
            from saengine.importers.staad import import_staad

            imported = import_staad(path, name)
        else:
            from saengine.importers.sap2000 import import_sap2000

            imported = import_sap2000(path, name)
    except (OSError, UnicodeError) as error:
        raise StructuralImportError(f"{path.name} could not be read: {error}") from error
    if name:
        imported.name = name
    root = Path(dest_parent) / _safe(imported.name)
    if root.exists() and any(root.iterdir()) and not overwrite:
        raise StructuralImportError(f"{root} exists already and is not empty")
    root.mkdir(parents=True, exist_ok=True)
    files = imported.write(root)
    for folder, main in _OTHER_PARTS.items():
        (root / folder).mkdir(exist_ok=True)
        if main is not None and not (root / folder / main[0]).exists():
            placeholder = json.dumps({"schema": 1, "part": main[1]}, indent="\t") + "\n"
            (root / folder / main[0]).write_text(placeholder, encoding="utf-8")
    return {
        "root": str(root),
        "name": imported.name,
        "format": kind,
        "report": imported.report.to_dict(),
        "problems": imported.problems(),
        "files": [str(p) for p in files],
    }


__all__ = [
    "FORMATS",
    "StructuralImportError",
    "import_structural",
    "section_lookup",
    "section_lookup_noted",
]
