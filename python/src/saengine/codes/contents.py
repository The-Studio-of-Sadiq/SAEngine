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


def check_template(pack_dir: Path, kind: str, files: list[str]) -> list[Problem]:
    """Each template file validated by the model that applies it."""
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
            from saengine.project.archive import inspect_archive

            result = inspect_archive(path)
            problems.extend(
                Problem(
                    severity="error" if p.get("severity", "error") == "error" else "warning",
                    message=f"template archive: {p.get('message')}",
                    file=rel,
                )
                for p in result["problems"]
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
        if isinstance(data, dict) and kind == "buildingTemplate":
            data = {k: v for k, v in data.items() if k != "$schema"}
        try:
            model.model_validate(data)
        except ValidationError as e:
            problems.extend(_errors(e, rel))
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
