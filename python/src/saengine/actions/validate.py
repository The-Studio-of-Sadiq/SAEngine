"""The changed part files still valid: each against its part model and the input guardrails
(:func:`saengine.library.check.check_library`, the editors' and ``saengine validate``'s check),
with the parts that refer to it checked again (an object type removed that members use).

Only what an action made worse counts: a problem the file had before the batch is not the
action's (it stays the engineer's to fix), so it neither refuses the action nor is repeated.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from saengine.actions.paths import (
    BIM,
    FLOOR_PLAN,
    LOADS,
    MATERIALS,
    OBJECTS,
    PART_OF_PATH,
    SETTINGS,
    SOIL,
    SUBSTRUCTURE,
)
from saengine.actions.result import Problem
from saengine.actions.view import ProjectView, json_text

#: Which files to check again when a file changes (they refer to it).
DEPENDENTS: dict[str, tuple[str, ...]] = {
    MATERIALS: (OBJECTS, SUBSTRUCTURE),
    OBJECTS: (FLOOR_PLAN, BIM, SUBSTRUCTURE),
    FLOOR_PLAN: (LOADS,),
}

#: The list each list file keeps its entries in (problems name the entry by its id).
LIST_KEYS = {MATERIALS: "materials", OBJECTS: "objects"}


def _messages(error: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "path": ".".join(str(p) for p in e["loc"]),
            "message": e["msg"].removeprefix("Value error, "),
        }
        for e in error.errors()
    ]


def _check(path: str, texts: Callable[[str], str | None]) -> list[dict[str, Any]]:
    """The problems of ``path`` with the texts of the files as ``texts`` gives them."""
    from saengine.library.check import check_library

    text = texts(path)
    if text is None:
        return []
    if path == SETTINGS:
        return _check_settings(text)
    if path == MATERIALS:
        return check_library("materials", text)
    if path == OBJECTS:
        return check_library("objects", text, texts(MATERIALS))
    if path == FLOOR_PLAN:
        return check_library("floorPlan", text, texts(OBJECTS))
    if path == BIM:
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("schema") != "saengine.bim/2":
            return []
        return check_library("bim", text, texts(OBJECTS))
    if path == LOADS:
        return _check_loads(text, texts(FLOOR_PLAN))
    if path == SOIL:
        from saengine.library.soil import SoilReport

        try:
            SoilReport.model_validate_json(text)
        except ValidationError as error:
            return _messages(error)
        return []
    if path == SUBSTRUCTURE:
        return _check_substructure(text, texts(MATERIALS), texts(OBJECTS))
    return []


def _check_settings(text: str) -> list[dict[str, Any]]:
    """The settings' problems (:func:`check_library`). Once the settings validate, a problem of a
    value not entered yet (a pack that needs the mapped spectral values, a custom location's wind
    speed) is a warning: the settings are incomplete, not wrong, and the next action may give it;
    a value that is entered and wrong (outside the pack's range, below its minimum) is an error."""
    from saengine.library.check import check_library
    from saengine.library.settings import ProjectSettings

    problems = check_library("settings", text)
    data = json.loads(text)
    try:
        ProjectSettings.model_validate(data)
    except (ValidationError, ValueError):
        return problems
    out = []
    for problem in problems:
        node: Any = data
        for step in [s for s in (problem.get("path") or "").split(".") if s]:
            node = node.get(step) if isinstance(node, dict) else None
        out.append({**problem, "severity": "warning"} if node is None else problem)
    return out


def _check_loads(text: str, plan_text: str | None) -> list[dict[str, Any]]:
    from saengine.library import guardrails
    from saengine.library import line_loads as ll
    from saengine.library.floorplan import FloorPlan

    try:
        loads = ll.parse(text)
    except ValidationError as error:
        return _messages(error)
    except ValueError as error:
        return [{"path": "", "message": str(error)}]
    problems = guardrails.check("memberLoads", json.loads(text))
    if plan_text:
        try:
            plan = FloorPlan.model_validate_json(plan_text)
        except ValidationError:
            return problems
        problems += [{"path": "loads", "message": m} for m in ll.check(loads, plan)]
    return problems


def _check_substructure(
    text: str, materials_text: str | None, objects_text: str | None
) -> list[dict[str, Any]]:
    from saengine.library import substructure as sub
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    try:
        parsed = sub.parse(text)
    except ValidationError as error:
        return _messages(error)
    except ValueError as error:
        return [{"path": "", "message": str(error)}]
    try:
        materials = MaterialLibrary.model_validate_json(materials_text) if materials_text else None
        objects = ObjectLibrary.model_validate_json(objects_text) if objects_text else None
    except ValidationError:
        materials = objects = None
    return [{"path": "", "message": m} for m in sub.check(parsed, None, materials, objects)]


def _key(path: str, data: Any, problem: dict[str, Any]) -> tuple[Any, ...]:
    """A problem's identity across the edit: its entry's id (not its index, which moves)."""
    index = problem.get("index")
    entry: Any = index
    key = LIST_KEYS.get(path)
    if key and isinstance(index, int) and isinstance(data, dict):
        entries = data.get(key) or []
        if 0 <= index < len(entries) and isinstance(entries[index], dict):
            entry = entries[index].get("id", index)
    return (entry, problem.get("path") or "", problem.get("message") or "")


def _value(data: Any, path: str, problem: dict[str, Any]) -> tuple[str, Any]:
    """The field as the engineer reads it, and its value in ``data``."""
    node = data
    field = problem.get("path") or ""
    key = LIST_KEYS.get(path)
    index = problem.get("index")
    prefix = ""
    if key and isinstance(index, int) and isinstance(data, dict):
        entries = data.get(key) or []
        if 0 <= index < len(entries):
            node = entries[index]
            prefix = f"{key}[{node.get('id', index) if isinstance(node, dict) else index}]"
    for step in [s for s in field.split(".") if s]:
        if isinstance(node, dict):
            node = node.get(step)
        elif isinstance(node, list) and step.isdigit() and int(step) < len(node):
            node = node[int(step)]
        else:
            node = None
            break
    if isinstance(node, dict | list):
        node = None
    full = ".".join(s for s in (prefix, field) if s)
    return full, node


def check_changes(
    view: ProjectView, before: dict[str, Any], changed: list[str]
) -> tuple[list[Problem], list[str]]:
    """The new problems (errors: the action is refused) and new warnings of the ``changed`` files
    and those that refer to them; ``before`` is the view's data before the action
    (:meth:`ProjectView.changes` then)."""
    paths: list[str] = []
    for path in changed:
        for p in (path, *DEPENDENTS.get(path, ())):
            if p not in paths:
                paths.append(p)

    def now(path: str) -> str | None:
        data = view.read(path, None)
        return None if data is None else json_text(data)

    def then(path: str) -> str | None:
        if path in before:
            data = before[path]
            return None if data is None else json_text(data)
        return view.text(path)

    errors: list[Problem] = []
    warnings: list[str] = []
    for path in paths:
        if not view.has(path):
            continue
        after = _check(path, now)
        if not after:
            continue
        try:
            old = _check(path, then)
        except ValueError:
            old = []
        old_data = json.loads(then(path) or "null")
        known = {_key(path, old_data, p) for p in old}
        data = view.read(path, None)
        for problem in after:
            if _key(path, data, problem) in known:
                continue
            field, value = _value(data, path, problem)
            if problem.get("severity") == "warning":
                warnings.append(f"{PART_OF_PATH.get(path, path)}: {problem['message']}")
            else:
                errors.append(
                    Problem(field=field, value=value, reason=problem["message"], part=path)
                )
    return errors, warnings
