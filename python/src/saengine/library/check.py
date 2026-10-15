"""Full validation of a library file for the visual editors.

The editors validate each field against the JSON Schema as it is typed. The rules the schema
cannot express (fu >= fy, the parts of a mix, which property groups a category needs,
duplicate ids, references between entries and between the two files) live in the Pydantic
models; this runs them and reports each problem against the entry it belongs to.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any, Literal

from pydantic import ValidationError

from saengine.library.bim import BuildingModel
from saengine.library.floorplan import FloorPlan
from saengine.library.materials import MaterialLibrary
from saengine.library.objects import ObjectLibrary

Kind = Literal["materials", "objects", "floorPlan", "bim"]


@cache
def _union_tags() -> frozenset[str]:
    tags: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("const"), str) and "/" not in node["const"]:
                tags.add(node["const"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(MaterialLibrary.model_json_schema())
    walk(ObjectLibrary.model_json_schema())
    walk(FloorPlan.model_json_schema())
    walk(BuildingModel.model_json_schema())
    return frozenset(tags)


def _problem(index: int | None, path: str, message: str) -> dict[str, Any]:
    return {"index": index, "path": path, "message": message}


def _clean(message: str) -> str:
    return message.removeprefix("Value error, ")


def check_library(kind: Kind, text: str, materials_text: str | None = None) -> list[dict[str, Any]]:
    """Problems in a library file, each with the index of its entry (None for the whole file).

    ``materials_text`` is the other file the check needs: materials.json for object types,
    objects.json for the floor plan and the building model.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [_problem(None, "", f"Invalid JSON: {exc}")]

    if kind == "floorPlan":
        return _check_layout(FloorPlan, data, materials_text)
    if kind == "bim":
        return _check_layout(BuildingModel, data, materials_text)
    model = MaterialLibrary if kind == "materials" else ObjectLibrary
    try:
        library = model.model_validate(data)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            loc = list(error["loc"])
            index = loc[1] if len(loc) > 1 and loc[0] == kind and isinstance(loc[1], int) else None
            # Discriminated unions add the variant's tag ("beam", "rectangle") to the location.
            path = ".".join(
                str(p) for p in (loc[2:] if index is not None else loc) if p not in _union_tags()
            )
            problems.append(_problem(index, path, _clean(error["msg"])))
        return problems

    if kind == "objects" and materials_text is not None and isinstance(library, ObjectLibrary):
        try:
            materials = MaterialLibrary.model_validate_json(materials_text)
        except ValidationError:
            return [
                _problem(
                    None, "", "The materials file has errors; material references were not checked."
                )
            ]
        ids = [o.id for o in library.objects]
        problems = []
        for message in library.check_materials(materials):
            object_id, _, detail = message.partition(": ")
            problems.append(
                _problem(ids.index(object_id) if object_id in ids else None, "material", detail)
            )
        return problems
    return []


def _check_layout(
    model_type: type[FloorPlan | BuildingModel], data: Any, objects_text: str | None
) -> list[dict[str, Any]]:
    """Floor plan or building model problems; ``index`` is None and ``path`` names the section."""
    try:
        model = model_type.model_validate(data)
    except ValidationError as exc:
        return [
            _problem(
                None,
                ".".join(str(p) for p in error["loc"] if p not in _union_tags()),
                _clean(error["msg"]),
            )
            for error in exc.errors()
        ]
    if objects_text is None:
        return []
    try:
        objects = ObjectLibrary.model_validate_json(objects_text)
    except ValidationError:
        return [
            _problem(None, "", "The object types file has errors; member types were not checked.")
        ]
    return [_problem(None, "", message) for message in model.check_objects(objects)]
