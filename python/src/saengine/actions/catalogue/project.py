"""Project actions: a new project (empty, or a whole building by the generator) and a building
generated into an existing project. The building is :func:`saengine.library.generator.
generate_building`; the starting files are those of :mod:`saengine.project.new_building`."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import Field

from saengine.actions.catalogue._plan import GROUPS, members
from saengine.actions.catalogue._util import Params
from saengine.actions.errors import refuse
from saengine.actions.paths import (
    BIM,
    FLOOR_PLAN,
    MATERIALS,
    OBJECTS,
    SETTINGS,
    SUBSTRUCTURE,
)
from saengine.actions.registry import action
from saengine.actions.result import ActionResult
from saengine.actions.view import ProjectView

Use = Literal[
    "residential",
    "office",
    "educational",
    "healthcare",
    "assembly",
    "retail",
    "industrial",
    "storage",
    "parking",
    "mixed",
]


class CreateParams(Params):
    name: str = Field(min_length=1, max_length=120, description="The project's name.")
    codePack: str | None = Field(
        default=None, description="Id of the design code pack (codes/list); none: the default."
    )
    location: str | None = Field(
        default=None, description="Town of the pack's hazard tables, or custom."
    )
    siteClass: str | None = Field(default=None, description="One of the pack's site classes.")
    occupancy: Use | None = Field(default=None, description="The building's use.")
    units: Literal["SI", "USCustomary"] | None = Field(
        default=None, description="Display units; none: the pack's suggestion."
    )
    building: dict[str, Any] | None = Field(
        default=None,
        description="A whole building from a grid and storeys (the generator's BuildingSpec: "
        "gridsX, gridsY spacings [mm], storyCount or stories, system, footing, ...); none: an "
        "empty project (then grid.set, storeys.set, ...).",
    )


def _manifest_path(view: ProjectView) -> str | None:
    try:
        found = sorted(p.name for p in view.root.iterdir() if p.suffix.lower() == ".saengine")
    except OSError:
        return None
    return found[0] if found else None


def _put_building(view: ProjectView, result: dict[str, Any]) -> None:
    from saengine.library.generator import building_texts

    for path, text in building_texts(result).items():
        view.put(path, json.loads(text))


def _building_spec(raw: dict[str, Any], extra: dict[str, Any]) -> Any:
    from pydantic import ValidationError

    from saengine.actions.errors import ActionError
    from saengine.actions.result import Problem
    from saengine.library.generator import BuildingSpec
    from saengine.project.new_building import spec_from_wizard

    spec, _notes = spec_from_wizard(dict(raw))
    spec.update({k: v for k, v in extra.items() if v is not None})
    try:
        return BuildingSpec.model_validate(spec)
    except ValidationError as error:
        problems = [
            Problem(
                field="building." + ".".join(str(p) for p in e["loc"]),
                value=e.get("input") if not isinstance(e.get("input"), dict | list) else None,
                reason=e["msg"].removeprefix("Value error, "),
            )
            for e in error.errors()
        ]
        raise ActionError(
            "The building is not valid: " + "; ".join(f"{p.field}: {p.reason}" for p in problems),
            problems,
        ) from error


def _generate(spec: Any, settings: Any = None) -> dict[str, Any]:
    from saengine.library.generator import generate_building

    try:
        return generate_building(spec, settings)
    except ValueError as error:
        refuse(f"The building cannot be generated: {error}", "building", None)
        raise


@action(
    "project.create",
    summary="Create a project in the folder: empty (then grid, storeys, members...) or a whole "
    "building from a grid and storeys (building: the generator's spec).",
    params=CreateParams,
    parts=(
        "settings",
        "materials",
        "objects",
        "floorPlan",
        "bim",
        "substructure",
        "soil",
        "mep",
        "boq",
    ),
    kind="edit",
    writes=True,
    example={"name": "Example House", "occupancy": "residential"},
)
def project_create(view: ProjectView, p: CreateParams) -> ActionResult:
    from saengine.codes import context as code_context
    from saengine.library.generator import project_manifest
    from saengine.project.new_building import OTHER_PARTS, starting_file

    existing = _manifest_path(view)
    if existing or any(path.endswith(".saengine") for path in view.changes()):
        refuse(
            f"There is a project in this folder already ({existing or 'created by this batch'}): "
            "create the new one in an empty folder.",
            "name",
            p.name,
        )
    p = _resolve_names(p)
    notes: list[str] = []
    file, manifest = project_manifest(p.name)
    view.put(file, manifest)
    extra = {
        "name": p.name,
        "codePack": p.codePack,
        "location": p.location,
        "siteClass": p.siteClass,
        "occupancy": p.occupancy,
        "units": p.units,
    }
    if p.building is not None:
        spec = _building_spec(p.building, extra)
        result = _generate(spec)
        _put_building(view, result)
        notes += list(result.get("notes") or [])
        what = "a building generated from its grid and storeys"
    else:
        from saengine.library.bim import BuildingModel
        from saengine.library.defaults import default_material_library, default_object_library
        from saengine.library.floorplan import FloorPlan
        from saengine.library.settings import default_project_settings
        from saengine.library.substructure import SCHEMA_ID as SUBSTRUCTURE_SCHEMA

        try:
            pack = code_context.pack_for(
                {"codePack": p.codePack} if p.codePack else None, strict=True
            )
        except Exception as error:
            refuse(f"The code pack '{p.codePack}' cannot be used: {error}", "codePack", p.codePack)
            raise
        with code_context.using(pack):
            settings = default_project_settings(p.name, p.codePack)
            data = settings.model_dump(mode="json", by_alias=True, exclude_none=True)
            if p.occupancy:
                data.setdefault("occupancy", {})["use"] = p.occupancy
            if p.location:
                data.setdefault("site", {})["location"] = p.location
            if p.siteClass:
                data.setdefault("site", {}).update(siteClass=p.siteClass, siteClassSource="entered")
            if p.units:
                data.setdefault("units", {})["system"] = p.units
            view.put(SETTINGS, data)
            dump = {"mode": "json", "by_alias": True, "exclude_none": True}
            view.put(MATERIALS, default_material_library().model_dump(**dump))
            view.put(OBJECTS, default_object_library().model_dump(**dump))
        view.put(FLOOR_PLAN, FloorPlan().model_dump(**dump))
        view.put(BIM, BuildingModel().model_dump(**dump))
        view.put(SUBSTRUCTURE, {"schema": SUBSTRUCTURE_SCHEMA, "foundations": []})
        what = "an empty project (default materials and object types; no grid or storeys yet)"
    for folder, main in OTHER_PARTS.items():
        if main is not None:
            view.put(f"{folder}/{main[0]}", json.loads(starting_file(main[1])))
    return ActionResult(message=f"Created {p.name}: {what}.", created=[file], warnings=notes)


def _key(text: str) -> str:
    return "".join(c for c in text.casefold() if c.isalnum())


def _resolve_names(p: CreateParams) -> CreateParams:
    """The code pack and the town as the engineer (or the AI) writes them: "BNBC 2020" is the
    pack bnbc2020 and "Dhaka" its town dhaka. Exact ids pass unchanged; no match is left for
    the usual refusal, which names the accepted values."""
    from saengine.codes import context as code_context
    from saengine.codes import registry

    update: dict[str, Any] = {}
    pack_id = p.codePack
    if pack_id:
        try:
            packs = registry.list_packs()
        except Exception:  # noqa: BLE001 - the refusal below reports an unusable pack
            packs = []
        ids = [info.id for info in packs]
        if pack_id not in ids:
            want = _key(pack_id)
            for info in packs:
                if want in {_key(info.id), _key(getattr(info, "name", "") or "")}:
                    update["codePack"] = pack_id = info.id
                    break
    if p.location and p.location != "custom":
        try:
            pack = code_context.pack_for({"codePack": pack_id} if pack_id else None, strict=True)
            towns = pack.table("locations").locations if pack.has("locations") else {}
        except Exception:  # noqa: BLE001 - the usual validation reports it
            towns = {}
        if p.location not in towns:
            want = _key(p.location)
            for key, town in towns.items():
                if want in {_key(key), _key(getattr(town, "name", "") or "")}:
                    update["location"] = key
                    break
    return p.model_copy(update=update) if update else p


class GenerateParams(Params):
    building: dict[str, Any] = Field(
        description="The generator's BuildingSpec: gridsX and gridsY spacings [mm], storyCount "
        "(or stories), system, footing, concrete, rebar, occupancy, ..."
    )
    replace: bool = Field(
        default=False,
        description="Replace the members already on the floor plan (else refused when there are).",
    )


@action(
    "building.generate",
    summary="Generate a whole building (grid, storeys, materials, types, members, footings) "
    "into the project from a BuildingSpec; the settings' code pack and site are kept.",
    params=GenerateParams,
    parts=("settings", "materials", "objects", "floorPlan", "bim", "substructure"),
    kind="edit",
    example={"building": {"gridsX": [5000, 5000, 5000], "gridsY": [4000, 4000], "storyCount": 3}},
)
def building_generate(view: ProjectView, p: GenerateParams) -> ActionResult:
    from saengine.library.settings import ProjectSettings

    plan = view.read(FLOOR_PLAN, {})
    count = sum(len(members(plan, g)) for g in GROUPS)
    if count and not p.replace:
        refuse(
            f"The floor plan has {count} members already: give replace: true to replace them "
            "with the generated building.",
            "replace",
            False,
        )
    settings_data = view.read(SETTINGS)
    name = (settings_data.get("project") or {}).get("name") or "Building"
    spec = _building_spec(p.building, {"name": p.building.get("name") or name})
    try:
        settings = ProjectSettings.model_validate(settings_data)
    except ValueError as error:
        refuse(f"02 Project Settings are not valid ({error}): fix them first.", "", None)
        raise
    result = _generate(spec, settings)
    _put_building(view, result)
    counts = {g: len(result["floorPlan"].get(g) or []) for g in GROUPS}
    said = ", ".join(f"{n} {g}" for g, n in counts.items() if n)
    return ActionResult(
        message=f"Generated the building: {said}.", warnings=list(result.get("notes") or [])
    )
