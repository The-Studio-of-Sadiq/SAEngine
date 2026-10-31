"""Coded structure templates: new shape kinds made by a package's own Python (docs/
marketplace-plan.md, round M5).

A structure-template package may hold, beside presets of the built-in shapes, templates that
name a ``generator``: a function of the package's ``hooks`` file that takes the parameters (a
dict, validated against the template's JSON Schema) and returns the geometry, as a
:class:`saengine.library.shapes.Geometry` or its JSON (``members``, ``areas``, ``supports``,
``notes``; points ``[x, y, z]`` in mm). The function runs only when the package is trusted: the
same trust store, keyed by the hash of every ``.py`` file of the package, as code packs' hooks.
The geometry is placed (``origin``, ``rotation`` in the parameters, when given) and goes into
the model through the same :func:`saengine.library.shapes.insert` as a built-in shape's.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from saengine.codes.contents import CodedTemplate, is_coded_template, parameter_problems
from saengine.codes.registry import CodePackError, Registry, default_registry

KIND = "structureTemplate"
#: Parameters every coded template may take besides its own: where the shape goes.
PLACEMENT = ("origin", "rotation")


def read_template(pack_dir: Path, file: str) -> CodedTemplate:
    """The coded template ``file`` of the package folder (inside it, a coded template)."""
    path = (pack_dir / file).resolve()
    if not path.is_relative_to(pack_dir.resolve()) or not path.is_file():
        raise CodePackError(f"'{file}' is not a template of the package")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not is_coded_template(data):
        raise CodePackError(f"'{file}' is a preset of a built-in shape, not a coded template")
    return CodedTemplate.model_validate(data)


def _placement(values: dict[str, Any]) -> tuple[Any, float, list[str]]:
    from saengine.library.shapes import Point

    problems: list[str] = []
    origin = values.get("origin") or {"x": 0, "y": 0, "z": 0}
    try:
        point = Point.model_validate(origin)
    except ValidationError:
        problems.append("origin: must be {x, y, z} in mm")
        point = Point(x=0, y=0, z=0)
    rotation = values.get("rotation", 0)
    if not isinstance(rotation, (int, float)) or isinstance(rotation, bool):
        problems.append("rotation: must be a number of degrees")
        rotation = 0
    return point, float(rotation), problems


def coded_geometry(
    package: str,
    file: str,
    values: dict[str, Any] | None = None,
    project_root: Path | None = None,
    registry: Registry | None = None,
    member_type: str | None = None,
) -> dict[str, Any]:
    """The geometry of the coded template ``file`` of ``package`` with ``values`` over its
    starting values: :meth:`Geometry.to_json`, or ``{"problems": [...]}`` (with ``"untrusted":
    true`` when the package's code is not trusted, so the panel can say where to trust it).
    ``member_type``: the object type that replaces the placeholder type ``MEMBER`` (the Generate
    panel's current member type), as for the built-in shapes."""
    from saengine.library.shapes import Geometry

    reg = registry or default_registry()
    try:
        pack = reg.load(package, project_root, KIND)
        template = read_template(pack.path, file)
    except (CodePackError, OSError, ValueError) as error:
        return {"problems": [str(error)]}
    if not pack.trusted:
        return {
            "untrusted": True,
            "problems": [
                (
                    f"{template.name} is made by the code of the package '{pack.name}', which "
                    "is not trusted: read its hooks and trust it on the Packages page first"
                )
            ],
        }
    params = {**template.values, **(values or {})}
    own = {k: v for k, v in params.items() if k not in PLACEMENT}
    origin, rotation, problems = _placement(params)
    problems += parameter_problems(template.parameters, own)
    if problems:
        return {"problems": problems}
    try:
        generator = pack.hook(template.generator)
    except CodePackError as error:
        return {"problems": [str(error)]}
    if generator is None:
        return {"problems": [f"the package's hooks have no function '{template.generator}'"]}
    try:
        result = generator(dict(own))
        geometry = result if isinstance(result, Geometry) else Geometry.from_json(result)
    except Exception as error:  # noqa: BLE001 - the package's code failed: say so, do not crash
        return {"problems": [f"the code of '{pack.name}' failed: {type(error).__name__}: {error}"]}
    if member_type:
        for member in geometry.members:
            if member.type == "MEMBER":
                member.type = member_type
    return geometry.placed(origin, rotation).to_json()
