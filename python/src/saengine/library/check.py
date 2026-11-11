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
from saengine.library.materials import MaterialLibrary, plausibility
from saengine.library.objects import ObjectLibrary
from saengine.library.settings import PackListError, ProjectSettings
from saengine.library.settings import problems as settings_problems
from saengine.library.structure import StructuralModel

Kind = Literal[
    "materials",
    "objects",
    "settings",
    "floorPlan",
    "structure",
    "bim",
    "reportTemplate",
    "worksheet",
    "rates",
    "carbon",
]


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
    walk(ProjectSettings.model_json_schema())
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

    if kind == "settings":
        return _check_settings(data)
    if kind == "reportTemplate":
        return _check_report_template(data)
    if kind == "worksheet":
        return _check_worksheet(data)
    if kind in ("rates", "carbon"):
        return _check_schedule(kind, data)
    if kind == "floorPlan":
        return _check_layout(FloorPlan, data, materials_text)
    if kind == "bim":
        return _check_layout(BuildingModel, data, materials_text)
    if kind == "structure":
        return _check_layout(StructuralModel, data, materials_text)
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

    if isinstance(library, MaterialLibrary):
        return [
            _problem(index, path, message)
            for index, material in enumerate(library.materials)
            for path, message in plausibility(material)
        ]
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
        problems += coverage_warnings(library, materials)
        from saengine.codes.context import project_root
        from saengine.library.section_designer import list_sections

        root = project_root()
        if root is not None:  # designed profiles name a file of 04 Objects/sections
            designed = set(list_sections(root))
            for index, o in enumerate(library.objects):
                profile = getattr(o, "profile", None)
                if (
                    getattr(profile, "shape", None) == "designed"
                    and profile.section not in designed
                ):
                    problems.append(
                        _problem(
                            index,
                            "profile.section",
                            f"no designed section '{profile.section}' in 04 Objects/sections",
                        )
                    )
        return problems
    return []


def coverage_warnings(library: ObjectLibrary, materials: MaterialLibrary) -> list[dict[str, Any]]:
    """Warnings (``severity`` "warning", not errors) on object types the design will not check
    as the engineer may expect (W4C-6 and W4C-25 of usability walk 4):

    - a member type of a kind the code pack in force does not cover (structural glass, tensile
      membranes, beam web openings): its design reports it as not covered, never checked;
    - an open-web joist type with rigid ends (no simple connection): in a moment frame it takes
      end moments and reversed moment it is not made for."""
    from saengine.codes import context as code_context
    from saengine.design.steel_connections import SIMPLE_KINDS

    try:
        pack = code_context.current()
        name = code_context.code_name(pack)
    except Exception:  # noqa: BLE001 - no pack machinery: nothing to say
        return []
    mats = {m.id: m for m in materials.materials}
    out: list[dict[str, Any]] = []

    def warn(index: int, path: str, message: str) -> None:
        out.append({**_problem(index, path, message), "severity": "warning"})

    for index, o in enumerate(library.objects):
        material = mats.get(getattr(o, "material", None))
        category = getattr(getattr(material, "category", None), "value", None)
        uncovered: list[tuple[str, str, str]] = []  # (table, path, what)
        if category == "glass" and (
            getattr(o, "glass", None) is not None or getattr(o, "glassFin", None) is not None
        ):
            uncovered.append(("glass", "glass", "structural glass"))
        if getattr(o, "kind", None) == "membrane":
            uncovered.append(("membranes", "kind", "tensile membranes"))
        if getattr(o, "webOpenings", None) is not None:
            uncovered.append(("webOpenings", "webOpenings", "beam web openings"))
        for table, path, what in uncovered:
            if not pack.has(table):
                warn(
                    index,
                    path,
                    f"{what} are not covered by the code pack {name}: the design will report "
                    f"{o.id} as not checked (choose a pack that covers them in 02 Project "
                    "Settings, or check by hand)",
                )
        precast = getattr(o, "precast", None)
        # W4C-38: said before Run All, not only in the piece's calculations.
        if (
            precast is not None
            and getattr(precast, "element", None) == "hollowCore"
            and not getattr(precast, "cores", None)
        ):
            warn(
                index,
                "precast.cores",
                f"{o.id}: a hollow-core unit with no cores entered is designed as a solid "
                "unit (its weight and section): enter the cores and their diameter",
            )
        if precast is not None and not getattr(precast, "inserts", None):
            warn(
                index,
                "precast.inserts",
                f"{o.id}: no lifting inserts entered, so the inserts are not checked for "
                "handling (enter them with their working load)",
            )
        connection = getattr(o, "connection", None)
        if getattr(o, "joist", None) is not None and (
            connection is None or getattr(connection, "type", "") not in SIMPLE_KINDS
        ):
            warn(
                index,
                "joist",
                f"{o.id} is an open-web joist with rigid ends (no simple connection): on a "
                "moment-frame line it takes end moments and reversed moment it is not made "
                "for; give it a fin plate or shear end plate connection (pinned ends) or use a "
                "rolled beam for frame beams",
            )
    return out


def _check_layout(
    model_type: type[FloorPlan | BuildingModel | StructuralModel],
    data: Any,
    objects_text: str | None,
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
    problems = []
    if isinstance(model, BuildingModel):
        problems = [
            *(_problem(None, "additions", message) for message in model.check_additions()),
            *(_problem(None, "elements", message) for message in model.check_model()),
        ]
    if objects_text is None:
        return problems
    try:
        objects = ObjectLibrary.model_validate_json(objects_text)
    except ValidationError:
        return [
            *problems,
            _problem(None, "", "The object types file has errors; member types were not checked."),
        ]
    return [*problems, *(_problem(None, "", message) for message in model.check_objects(objects))]


def _check_report_template(data: Any) -> list[dict[str, Any]]:
    """Problems of a report template: its schema, and each section listed once."""
    from saengine.library.report_template import ReportTemplate

    try:
        template = ReportTemplate.model_validate(data)
    except ValidationError as exc:
        return [
            _problem(None, ".".join(str(p) for p in error["loc"]), _clean(error["msg"]))
            for error in exc.errors()
        ]
    problems = []
    seen: set[str] = set()
    for index, section in enumerate(template.sections):
        if section.id in seen:
            problems.append(
                _problem(None, f"sections.{index}.id", f"Section {section.id} is listed twice.")
            )
        seen.add(section.id)
    return problems


def _check_schedule(kind: str, data: Any) -> list[dict[str, Any]]:
    """Problems of the schedule of rates (``10 BOQ/rates.json``) or the carbon factors
    (``carbon-factors.json``) of :mod:`saengine.boq.costing`: each with its item's index."""
    from saengine.boq.costing import UNITS, CarbonFactors, RateSchedule

    model = RateSchedule if kind == "rates" else CarbonFactors
    entries = "items" if kind == "rates" else "factors"
    try:
        schedule = model.model_validate(data)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            loc = list(error["loc"])
            index = (
                loc[1] if len(loc) > 1 and loc[0] == entries and isinstance(loc[1], int) else None
            )
            path = ".".join(str(p) for p in (loc[2:] if index is not None else loc))
            problems.append(_problem(index, path, _clean(error["msg"])))
        return problems
    problems = []
    if isinstance(schedule, RateSchedule):
        seen: set[str] = set()
        for index, item in enumerate(schedule.items):
            if item.unit not in UNITS:
                known = ", ".join(UNITS)
                problems.append(_problem(index, "unit", f"unknown unit '{item.unit}' ({known})"))
            if item.code in seen:
                problems.append(_problem(index, "code", f"item number {item.code} is repeated"))
            seen.add(item.code)
            if item.rate is not None and item.rate < 0:
                problems.append(_problem(index, "rate", "a rate is not negative"))
    return problems


def _check_worksheet(data: Any) -> list[dict[str, Any]]:
    """Problems of a calculation worksheet: its schema, a known kind, and inputs the kind has
    and accepts (:func:`saengine.report.worksheets.calculate` names them)."""
    from saengine.library.worksheet import Worksheet
    from saengine.report.worksheets import KINDS, calculate

    try:
        sheet = Worksheet.model_validate(data)
    except ValidationError as exc:
        return [
            _problem(None, ".".join(str(p) for p in error["loc"]), _clean(error["msg"]))
            for error in exc.errors()
        ]
    kind = KINDS.get(sheet.kind)
    if kind is None:
        return [_problem(None, "kind", f"Unknown worksheet kind '{sheet.kind}'.")]
    known = {i.name for i in kind.inputs}
    problems = [
        _problem(None, f"inputs.{name}", f"{kind.title} has no input '{name}'.")
        for name in sheet.inputs
        if name not in known
    ]
    problems += [
        _problem(None, "inputs", p) for p in calculate(sheet.kind, sheet.inputs)["problems"]
    ]
    return problems


def _check_settings(data: Any) -> list[dict[str, Any]]:
    """Project settings problems; ``path`` names the section."""
    try:
        settings = ProjectSettings.model_validate(data)
    except ValidationError as exc:
        problems = []
        for error in exc.errors():
            cause = (error.get("ctx") or {}).get("error")
            if isinstance(cause, PackListError):
                # W4C-28: each choice not in the pack's lists on its own page, in words.
                problems += [_problem(None, path, message) for path, message in cause.problems()]
                continue
            problems.append(
                _problem(
                    None,
                    ".".join(str(p) for p in error["loc"] if p not in _union_tags()),
                    _clean(error["msg"]),
                )
            )
        return problems
    return [_problem(None, path, message) for path, message in settings_problems(settings)]
