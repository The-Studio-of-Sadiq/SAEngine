"""The files of a package (``pack.json`` ``contents``, ``preview``) checked against what each kind
holds, and the rule that a package holds no programs.

* a design code's contents are its ``data/<table>.json`` tables, validated by the registry;
* a structure template's are presets of a built-in parametric shape (:class:`StructurePreset`,
  applied through the modeller's Generate panel: ``shape_geometry`` then ``insert``);
* a building template's are a building specification (``spec.json``, a
  :class:`saengine.library.generator.BuildingSpec` that prefills the New Building wizard) or an
  inputs-only project archive (``template.civil``, checked by
  :func:`saengine.project.archive.inspect_archive`).

The models of the templates are imported only when a template is checked.
"""

from __future__ import annotations

import json
import re
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from saengine.codes.manifest import (
    KIND_NAMES,
    MANIFEST_FILE,
    MAX_ARCHIVE_BYTES,
    MAX_FILE_BYTES,
    MAX_PACKAGE_BYTES,
    MAX_PREVIEW_BYTES,
    PREVIEW_SUFFIXES,
    PROGRAM_SUFFIXES,
    PackManifest,
    Problem,
)

TEMPLATE_KINDS = ("structureTemplate", "buildingTemplate")


def structure_preset_model() -> type[BaseModel]:
    """The model of a structure template's preset: a named :class:`ShapeInput`."""
    global _PRESET
    if _PRESET is None:
        from saengine.library.shapes import Shape

        class StructurePreset(BaseModel):
            """A preset of a built-in parametric shape (``templates/<name>.json``)."""

            model_config = ConfigDict(extra="forbid", populate_by_name=True)

            schema_ref: str | None = Field(default=None, alias="$schema")
            name: str = Field(
                min_length=1, description="Name in the shape list, e.g. 'Warren truss 24 m'."
            )
            description: str | None = None
            shape: Shape = Field(
                description="The shape and its parameters, as the Generate panel edits them."
            )

        _PRESET = StructurePreset
    return _PRESET


_PRESET: type[BaseModel] | None = None


class CodedTemplate(BaseModel):
    """A structure template whose geometry is made by the package's own Python (round M5): a
    new shape kind (a bridge, a tower, a hypar...). ``generator`` names a function of the
    package's ``hooks`` file, ``generator(params) -> geometry``, which runs only when the
    package is trusted; ``parameters`` is the JSON Schema of its parameters (the Generate panel's
    form is made from it) and ``values`` their starting values. The geometry enters the model
    through the same ``insert`` as a built-in shape's."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_ref: str | None = Field(default=None, alias="$schema")
    name: str = Field(min_length=1, description="Name in the shape list, e.g. 'Hypar 20 m'.")
    description: str | None = None
    generator: str = Field(
        pattern=r"^[A-Za-z][A-Za-z0-9_]*$",
        description="The function of the package's hooks that builds the geometry.",
    )
    parameters: dict[str, Any] = Field(
        description="JSON Schema (type object) of the parameters: properties with type number, "
        "integer, string or boolean, title, description, default, minimum, maximum, enum."
    )
    values: dict[str, Any] = Field(default_factory=dict, description="Starting values.")


def is_coded_template(data: Any) -> bool:
    """Whether a structure template file is a coded template (it names a ``generator``)."""
    return isinstance(data, dict) and "generator" in data


def building_spec_model() -> type[BaseModel]:
    from saengine.library.generator import BuildingSpec

    return BuildingSpec


# ---------------------------------------------------------------- no programs


def forbidden_file(name: str, size: int, link: bool = False) -> str | None:
    """Why a file may not be part of a package (a program, a link, too large); None when it
    may. ``name`` is its path relative to the package."""
    if link:
        return f"{name} is a link: packages may not hold links"
    suffix = PurePosixPath(name.replace("\\", "/")).suffix.lower()
    if suffix in PROGRAM_SUFFIXES:
        return f"{name} is a program or script ({suffix}): packages may not hold programs"
    limit = MAX_ARCHIVE_BYTES if suffix == ".civil" else MAX_FILE_BYTES
    if size > limit:
        return f"{name} is {size / 1e6:.1f} MB: a package file may be {limit // 2**20} MB at most"
    return None


def _skipped(rel: PurePosixPath) -> bool:
    """Files that are never copied with a package (Python's caches)."""
    return "__pycache__" in rel.parts or rel.suffix.lower() in (".pyc", ".pyo")


def folder_problems(pack_dir: Path) -> list[Problem]:
    """Programs, links and oversized files in the package folder (errors)."""
    problems: list[Problem] = []
    total = 0
    for path in sorted(pack_dir.rglob("*")):
        rel = PurePosixPath(path.relative_to(pack_dir).as_posix())
        if _skipped(rel):
            continue
        try:
            st = path.lstat()
        except OSError:
            continue
        link = stat.S_ISLNK(st.st_mode) or path.is_junction()
        if not link and not stat.S_ISREG(st.st_mode):
            continue
        total += st.st_size
        reason = forbidden_file(str(rel), st.st_size, link)
        if reason:
            problems.append(Problem(message=reason, file=str(rel)))
    if total > MAX_PACKAGE_BYTES:
        problems.append(
            Problem(
                message=f"the package is {total / 1e6:.0f} MB: at most {MAX_PACKAGE_BYTES // 2**20} MB"
            )
        )
    return problems


# ---------------------------------------------------------------- contents and preview


def _inside(pack_dir: Path, relative: str) -> bool:
    rel = relative.replace("\\", "/")
    if not rel or rel.startswith("/") or ":" in rel or ".." in rel.split("/"):
        return False
    return (pack_dir / rel).resolve().is_relative_to(pack_dir.resolve())


def content_files(pack_dir: Path, manifest: PackManifest) -> tuple[list[str], list[Problem]]:
    """The package's files of its kind (relative paths, sorted) and the problems of its
    ``contents`` (a pattern outside the folder, one that matches nothing)."""
    files: set[str] = set()
    problems: list[Problem] = []
    for pattern in manifest.content_globs():
        if not _inside(pack_dir, pattern.replace("*", "x").replace("?", "x")):
            problems.append(
                Problem(
                    message=f"contents: '{pattern}' is not inside the package folder",
                    file=MANIFEST_FILE,
                )
            )
            continue
        matched = [
            p.relative_to(pack_dir).as_posix()
            for p in pack_dir.glob(pattern.replace("\\", "/"))
            if p.is_file() and p.name != MANIFEST_FILE and not _skipped(PurePosixPath(p.name))
        ]
        if not matched and manifest.contents is not None:
            problems.append(
                Problem(
                    severity="warning",
                    message=f"contents: '{pattern}' matches no file",
                    file=MANIFEST_FILE,
                )
            )
        files.update(matched)
    return sorted(files), problems


def _errors(e: ValidationError, file: str, limit: int = 10) -> list[Problem]:
    return [
        Problem(message=f"{'.'.join(str(x) for x in err['loc']) or file}: {err['msg']}", file=file)
        for err in e.errors()[:limit]
    ]


PARAMETER_TYPES = ("number", "integer", "string", "boolean")


def parameter_schema_problems(schema: dict[str, Any]) -> list[str]:
    """Why ``schema`` is not a parameter schema the Generate panel can show: an object whose
    properties are numbers, integers, strings or booleans."""
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        return ["must be a JSON Schema of type object with properties"]
    problems = []
    for name, prop in schema["properties"].items():
        if not isinstance(prop, dict) or prop.get("type") not in PARAMETER_TYPES:
            problems.append(f"{name}: type must be one of {', '.join(PARAMETER_TYPES)}")
    return problems


def parameter_problems(
    schema: dict[str, Any], values: dict[str, Any], partial: bool = False
) -> list[str]:
    """Why ``values`` do not fit ``schema`` (types, ``minimum``, ``maximum``, ``enum``,
    ``required`` unless ``partial``); unknown names are refused. A small JSON Schema subset:
    the one :func:`parameter_schema_problems` allows."""
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    problems = []
    for name, value in values.items():
        prop = props.get(name)
        if not isinstance(prop, dict):
            problems.append(f"{name}: not a parameter of this template")
            continue
        kind = prop.get("type")
        ok = {
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
        }.get(kind, False)
        if not ok:
            problems.append(f"{name}: must be a {kind}")
            continue
        if "enum" in prop and value not in prop["enum"]:
            problems.append(f"{name}: must be one of {', '.join(map(str, prop['enum']))}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in prop and value < prop["minimum"]:
                problems.append(f"{name}: at least {prop['minimum']}")
            if "maximum" in prop and value > prop["maximum"]:
                problems.append(f"{name}: at most {prop['maximum']}")
    if not partial:
        for name in schema.get("required", []) or []:
            if name not in values:
                problems.append(f"{name}: required")
    return problems


def check_template(
    pack_dir: Path, kind: str, files: list[str], author: str = "", has_hooks: bool = False
) -> list[Problem]:
    """Each template file validated by the model that applies it; a ``template.civil`` also by
    :func:`saengine.project.archive.template_problems` (inputs only, no site more precise than
    a town, no names other than ``author``, the package's author). A coded structure template
    (:class:`CodedTemplate`) needs the package's hooks (``has_hooks``)."""
    problems: list[Problem] = []
    if not files:
        problems.append(
            Problem(
                message=f"a {KIND_NAMES[kind]} needs at least one template file (contents)",
                file=MANIFEST_FILE,
            )
        )
    for rel in files:
        path = pack_dir / rel
        suffix = path.suffix.lower()
        if kind == "buildingTemplate" and suffix == ".civil":
            from saengine.project.archive import inspect_archive, template_problems

            result = inspect_archive(path)
            problems.extend(
                Problem(
                    severity="error" if p.get("severity", "error") == "error" else "warning",
                    message=f"template archive: {p.get('message')}",
                    file=rel,
                )
                for p in result["problems"] + template_problems(path, author)
            )
            continue
        if suffix != ".json":
            expected = ".json or .civil" if kind == "buildingTemplate" else ".json"
            problems.append(Problem(message=f"a template file is {expected}", file=rel))
            continue
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            problems.append(Problem(message=f"cannot be read: {e}", file=rel))
            continue
        model = structure_preset_model() if kind == "structureTemplate" else building_spec_model()
        if kind == "structureTemplate" and is_coded_template(data):
            model = CodedTemplate
            if not has_hooks:
                problems.append(
                    Problem(
                        message="a coded template (generator) needs the package's hooks file",
                        file=rel,
                    )
                )
        if isinstance(data, dict) and kind == "buildingTemplate":
            data = {k: v for k, v in data.items() if k != "$schema"}
        try:
            parsed = model.model_validate(data)
        except ValidationError as e:
            problems.extend(_errors(e, rel))
            continue
        if isinstance(parsed, CodedTemplate):
            problems.extend(
                Problem(message=f"parameters: {m}", file=rel)
                for m in parameter_schema_problems(parsed.parameters)
            )
            problems.extend(
                Problem(message=f"values: {m}", file=rel)
                for m in parameter_problems(parsed.parameters, parsed.values, partial=True)
            )
    return problems


def preview_file(pack_dir: Path, manifest: PackManifest) -> tuple[Path | None, list[Problem]]:
    """The card image and its problems (outside the folder or not an image: error; missing or
    large: warning)."""
    if not manifest.preview:
        return None, []
    if not _inside(pack_dir, manifest.preview):
        return None, [
            Problem(
                message="preview must name an image inside the package folder", file=MANIFEST_FILE
            )
        ]
    path = pack_dir / manifest.preview
    if path.suffix.lower() not in PREVIEW_SUFFIXES:
        return None, [
            Problem(message=f"preview must be {', '.join(PREVIEW_SUFFIXES)}", file=MANIFEST_FILE)
        ]
    if not path.is_file():
        return None, [
            Problem(
                severity="warning",
                message=f"the preview '{manifest.preview}' is missing",
                file=MANIFEST_FILE,
            )
        ]
    if path.stat().st_size > MAX_PREVIEW_BYTES:
        return path, [
            Problem(
                severity="warning",
                message=f"the preview is over {MAX_PREVIEW_BYTES // 1024} KB: keep cards small",
                file=manifest.preview,
            )
        ]
    return path, []


# ─────────────────────────────────── language packs ───────────────────────────────────

_PLACEHOLDER = re.compile(r"\{\d+\}")


def check_language_pack(pack_dir: Path, files: list[str], language: str | None) -> list[Problem]:
    """A ``languagePack`` package: its ``language`` and its files.

    - ``messages/*.json``: the reports' and drawings' labels, ``{"language", "messages":
      {english: translation}}`` (read by :mod:`saengine.i18n`);
    - ``ui/*.i18n.json``: SAEngine's screens in the format of the workbench's language packs,
      ``{"contents": {module id: {key: translation}}}`` (the format of
      ``extensions/saengine-language-pack-bn/translations/main.i18n.json``).

    Each message keeps the ``{0}`` placeholders of its English text."""
    problems: list[Problem] = []
    if not language:
        problems.append(
            Problem(message="a language pack needs 'language' (e.g. \"bn\")", file=MANIFEST_FILE)
        )
    if not files:
        problems.append(
            Problem(
                message="a language pack needs messages/*.json or ui/*.i18n.json (contents)",
                file=MANIFEST_FILE,
            )
        )
    for rel in files:
        try:
            data = json.loads((pack_dir / rel).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            problems.append(Problem(message=f"cannot be read: {error}", file=rel))
            continue
        if rel.endswith(".i18n.json"):
            contents = data.get("contents") if isinstance(data, dict) else None
            if not isinstance(contents, dict) or not all(
                isinstance(m, dict) and all(isinstance(v, str) for v in m.values())
                for m in contents.values()
            ):
                problems.append(
                    Problem(message='must be {"contents": {module: {key: text}}}', file=rel)
                )
            continue
        messages = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(messages, dict) or not all(isinstance(v, str) for v in messages.values()):
            problems.append(Problem(message='must be {"messages": {english: text}}', file=rel))
            continue
        if language and data.get("language") not in (None, language):
            problems.append(
                Problem(message=f"language {data.get('language')!r} is not {language!r}", file=rel)
            )
        for english, text in messages.items():
            if sorted(_PLACEHOLDER.findall(english)) != sorted(_PLACEHOLDER.findall(text)):
                problems.append(Problem(message=f"{english!r}: the placeholders differ", file=rel))
    return problems
