"""The templates of the installed packages, as the app applies them (docs/marketplace-plan.md,
round M4).

* structure templates: their presets (``templates/*.json``, :class:`StructurePreset`), offered
  in the modeller's Generate panel grouped by package; a preset fills the Generate form, and
  the shape is built by ``shape_geometry`` and inserted by ``insert`` as any shape;
* building templates: a building specification (``spec.json``, prefills the New Building
  wizard) or an inputs-only project archive (``template.civil``, opened by *New Project from
  Template...* through the archive import, after :func:`saengine.project.archive.template_problems`).

Only the package in force of each id (the project's over the user's over the built-in one) and
only usable packages are listed; a template file that does not validate is left out with its
problem, so one bad file never hides the others.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from saengine.codes.contents import building_spec_model, structure_preset_model
from saengine.codes.registry import Registry, default_registry

#: The building template the New Building wizard starts from (formerly its own default form).
DEFAULT_BUILDING_TEMPLATE = "saengine-default-building"


def _packages(kind: str, project_root: Path | None, registry: Registry | None) -> list[Any]:
    reg = registry or default_registry()
    return [p for p in reg.list_packs(project_root, kind) if p.effective and p.usable]


def _read(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), None
    except (OSError, ValueError) as error:
        return None, f"{path.name} cannot be read: {error}"


def _files(info: Any) -> list[Path]:
    from saengine.codes.contents import content_files
    from saengine.codes.manifest import MANIFEST_FILE, PackManifest

    folder = Path(info.path)
    try:
        manifest = PackManifest.model_validate_json(
            (folder / MANIFEST_FILE).read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError):
        return []
    files, _ = content_files(folder, manifest)
    return [folder / f for f in files]


def _package_fields(info: Any) -> dict[str, Any]:
    return {
        "package": info.id,
        "packageName": info.name,
        "version": info.version,
        "scope": info.scope,
    }


def structure_presets(
    project_root: Path | None = None, registry: Registry | None = None
) -> dict[str, Any]:
    """``{presets: [{package, packageName, version, scope, file, name, description, shape}],
    problems: [{package, file, message}]}``, sorted by package then name."""
    preset_model = structure_preset_model()
    presets: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    for info in _packages("structureTemplate", project_root, registry):
        for path in _files(info):
            data, problem = _read(path)
            if problem is None:
                try:
                    preset = preset_model.model_validate(data)
                except ValidationError as error:
                    problem = f"{path.name}: {error.errors()[0]['msg']}"
            if problem is not None:
                problems.append({"package": info.id, "file": path.name, "message": problem})
                continue
            dumped = preset.model_dump(mode="json", by_alias=True, exclude_none=True)
            dumped.pop("$schema", None)
            presets.append(
                {
                    **_package_fields(info),
                    "file": path.relative_to(Path(info.path)).as_posix(),
                    "name": dumped["name"],
                    "description": dumped.get("description") or "",
                    "shape": dumped["shape"],
                }
            )
    presets.sort(key=lambda p: (p["package"] != "saengine-shapes", p["packageName"], p["name"]))
    return {"presets": presets, "problems": problems}


def building_templates(
    project_root: Path | None = None, registry: Registry | None = None
) -> dict[str, Any]:
    """``{templates: [{package, packageName, version, scope, file, name, description, type:
    'spec' | 'archive', spec?, path?, author?}], problems: [...]}``. A spec template carries its
    building specification (as written in ``spec.json``, validated); an archive template its
    absolute path, opened through *New Project from Template...*."""
    from saengine.codes.manifest import MANIFEST_FILE, PackManifest

    spec_model = building_spec_model()
    templates: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    for info in _packages("buildingTemplate", project_root, registry):
        try:
            manifest = PackManifest.model_validate_json(
                (Path(info.path) / MANIFEST_FILE).read_text(encoding="utf-8-sig")
            )
        except (OSError, ValueError):
            continue
        for path in _files(info):
            base = {
                **_package_fields(info),
                "file": path.relative_to(Path(info.path)).as_posix(),
                "name": info.name,
                "description": manifest.description or "",
                "author": manifest.author or "",
            }
            if path.suffix.lower() == ".civil":
                templates.append({**base, "type": "archive", "path": str(path.resolve())})
                continue
            data, problem = _read(path)
            if problem is None:
                if isinstance(data, dict):
                    data = {k: v for k, v in data.items() if k != "$schema"}
                try:
                    spec_model.model_validate(data)
                except ValidationError as error:
                    problem = f"{path.name}: {error.errors()[0]['msg']}"
            if problem is not None:
                problems.append({"package": info.id, "file": path.name, "message": problem})
                continue
            templates.append({**base, "type": "spec", "spec": data})
    templates.sort(
        key=lambda t: (t["package"] != DEFAULT_BUILDING_TEMPLATE, t["packageName"], t["file"])
    )
    return {"templates": templates, "problems": problems}
