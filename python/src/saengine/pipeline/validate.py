"""Validation of every part of a project, as its editors report problems.

For each part's main file: the JSON itself, the schema (the part's Pydantic model in
:mod:`saengine.library`) and the rules the schema cannot express (references between entries and
between files), the same checks the editors run:

- 2 Project Settings, 3 Materials, 4 Objects, 5 Floor Plan / Structural Model, 6 BIM:
  :func:`saengine.library.check.check_library` (the editors' ``saengine.library.check``), with
  the materials for the object types and the object types for the layouts;
- 1 Soil Report: the model, and :func:`saengine.library.soil.check` (what the computations will
  be missing) as warnings;
- 7 MEP: :func:`saengine.library.mep.parse` and :func:`saengine.library.mep.check` against 6 BIM;
- 9 Substructure: :func:`saengine.library.substructure.parse` and its ``check`` against 6 BIM,
  the materials and the object types;
- 10 BOQ: the bill's model, once measured;
- 8 FEM: the derived model through OpenSees Studio's schema (``validate_project``), when it exists.

A placeholder (a part not started) and a missing optional part are not problems.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from saengine.pipeline.project import Project

#: Parts a new project starts as placeholders, which may be missing or not started.
OPTIONAL = frozenset({"soil", "mep", "substructure", "boq", "fem"})
LIBRARY_KINDS = {
    "settings": None,
    "materials": None,
    "objects": "materials",
    "floorPlan": "objects",
    "structure": "objects",
    "bim": "objects",
}


@dataclass
class PartValidation:
    part: str
    file: str | None
    #: ok, problems (an error among them), warnings, placeholder (not started), missing.
    state: str = "ok"
    problems: list[dict[str, Any]] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for p in self.problems if p["severity"] == "error")

    def to_json(self) -> dict[str, Any]:
        return {
            "part": self.part,
            "file": self.file,
            "state": self.state,
            "problems": self.problems,
        }


def _problem(message: str, severity: str = "error", path: str = "", index: int | None = None):
    return {"severity": severity, "path": path, "index": index, "message": message}


def _pydantic(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        _problem(
            str(e["msg"]).removeprefix("Value error, "),
            path=".".join(str(p) for p in e["loc"]),
        )
        for e in exc.errors()
    ]


def _is_placeholder(data: Any, part: str) -> bool:
    return (
        isinstance(data, dict)
        and data.get("part") == part
        and all(k in ("schema", "part") for k in data)
    )


def _building(project: Project) -> Any:
    from saengine.library.bim import BuildingModel

    text = project.text("bim")
    try:
        return BuildingModel.model_validate_json(text) if text else None
    except ValidationError:
        return None


def _library(project: Project, part: str, model_name: str) -> Any:
    import importlib

    text = project.text(part)
    module, _, name = model_name.rpartition(".")
    try:
        return (
            getattr(importlib.import_module(module), name).model_validate_json(text)
            if text
            else None
        )
    except ValidationError:
        return None


def validate_part(project: Project, part: str) -> PartValidation:
    """The problems of part ``part`` of ``project``."""
    from saengine.library.check import check_library

    path = project.file(part)
    result = PartValidation(part, path.relative_to(project.root).as_posix())
    text = project.text(part)
    if text is None:
        if part in OPTIONAL:
            result.state = "missing"
        else:
            result.state = "problems"
            result.problems.append(_problem(f"{result.file} is missing"))
        return result
    try:
        data = json.loads(text)
    except ValueError as exc:
        result.state = "problems"
        result.problems.append(_problem(f"Invalid JSON: {exc}"))
        return result
    if _is_placeholder(data, part):
        result.state = "placeholder"
        return result
    problems: list[dict[str, Any]] = []
    if part in LIBRARY_KINDS:
        companion = LIBRARY_KINDS[part]
        found = check_library(part, text, project.text(companion) if companion else None)  # type: ignore[arg-type]
        problems = [
            _problem(p["message"], path=p.get("path") or "", index=p.get("index")) for p in found
        ]
    elif part == "soil":
        from saengine.library.soil import SoilReport, check

        try:
            report = SoilReport.model_validate(data)
        except ValidationError as exc:
            problems = _pydantic(exc)
        else:
            problems = [_problem(m, "warning", m.split(":")[0]) for m in check(report)]
    elif part == "mep":
        from saengine.library import mep

        try:
            model = mep.parse(text)
        except ValidationError as exc:
            problems = _pydantic(exc)
        except ValueError as exc:
            problems = [_problem(str(exc))]
        else:
            problems = [
                _problem(m, path=m.split(":")[0]) for m in mep.check(model, _building(project))
            ]
    elif part == "substructure":
        from saengine.library import substructure

        try:
            model = substructure.parse(text)
        except ValidationError as exc:
            problems = _pydantic(exc)
        except ValueError as exc:
            problems = [_problem(str(exc))]
        else:
            found = substructure.check(
                model,
                _building(project),
                _library(project, "materials", "saengine.library.materials.MaterialLibrary"),
                _library(project, "objects", "saengine.library.objects.ObjectLibrary"),
            )
            problems = [_problem(m, path=m.split(":")[0]) for m in found]
    elif part == "boq":
        from saengine.boq.quantities import BillOfQuantities

        try:
            BillOfQuantities.model_validate(data)
        except ValidationError as exc:
            problems = _pydantic(exc)
    elif part == "fem":
        from saengine.rpc.handlers import validate_project

        outcome = validate_project(str(path))
        problems = [_problem(str(e)) for e in outcome.get("errors") or []]
        problems += [_problem(str(n), "warning") for n in outcome.get("notices") or []]
    result.problems = problems
    if result.errors:
        result.state = "problems"
    elif problems:
        result.state = "warnings"
    return result


def validate_project(project: Project) -> list[PartValidation]:
    """The validation of every part of ``project`` that has a main file, in order."""
    return [validate_part(project, p.id) for p in project.parts if p.main_file]
