"""A SAEngine project on disk: its manifest, its parts and their main files.

Mirrors ``PROJECT_PARTS``, ``STRUCTURE_PART`` and ``projectParts`` of the workbench's
``services/saengineProject/common/saengineProject.ts``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PROJECT_EXTENSION = ".saengine"


@dataclass(frozen=True)
class Part:
    id: str
    folder: str
    main_file: str | None
    label: str

    @property
    def relative(self) -> str | None:
        """``<folder>/<main file>``, the main file relative to the project root."""
        return f"{self.folder}/{self.main_file}" if self.main_file else None


#: The parts of a building project, in workflow order.
PROJECT_PARTS: tuple[Part, ...] = (
    Part("soil", "01 Soil Report", "soil-report.json", "Soil Report"),
    Part("settings", "02 Project Settings", "project-settings.json", "Project Settings"),
    Part("materials", "03 Materials", "materials.json", "Materials"),
    Part("objects", "04 Objects", "objects.json", "Object Types"),
    Part("floorPlan", "05 Floor Plan", "floor-plan.json", "Floor Plan"),
    Part("bim", "06 BIM", "bim.json", "Building Model"),
    Part("mep", "07 MEP", "mep.json", "MEP"),
    Part("fem", "08 FEM", "model.osmodel", "Analysis Model"),
    Part("substructure", "09 Substructure", "substructure.json", "Substructure"),
    Part("boq", "10 BOQ", "boq.json", "Bill of Quantities"),
    Part("exports", "11 Exports", None, "Exports"),
)

#: Part 5 of a special structure: the 3D structural model instead of the floor plan.
STRUCTURE_PART = Part("structure", "05 Structural Model", "structure.json", "Structural Model")

ALL_PARTS: tuple[Part, ...] = (*PROJECT_PARTS, STRUCTURE_PART)
_BY_ID = {p.id: p for p in ALL_PARTS}


def part_by_id(part_id: str) -> Part:
    return _BY_ID[part_id]


def project_parts(project_type: str) -> tuple[Part, ...]:
    """The parts of a project of ``project_type`` ("building" or "structure"), in order."""
    if project_type == "structure":
        return tuple(STRUCTURE_PART if p.id == "floorPlan" else p for p in PROJECT_PARTS)
    return PROJECT_PARTS


class ProjectError(ValueError):
    """The folder is not a SAEngine project."""


@dataclass(frozen=True)
class Project:
    root: Path
    manifest: Path
    name: str
    type: str

    @property
    def parts(self) -> tuple[Part, ...]:
        return project_parts(self.type)

    def file(self, part_id: str) -> Path:
        """The main file of part ``part_id``."""
        part = part_by_id(part_id)
        if part.main_file is None:
            raise ValueError(f"part {part_id} has no main file")
        return self.root / part.folder / part.main_file

    def folder(self, part_id: str) -> Path:
        return self.root / part_by_id(part_id).folder

    def text(self, part_id: str) -> str | None:
        """The text of part ``part_id``'s main file, as the workbench reads it (UTF-8, line
        endings kept); None when it is missing or unreadable."""
        return read_text(self.file(part_id))

    def texts(self, part_ids: list[str] | tuple[str, ...]) -> dict[str, str | None]:
        return {p: self.text(p) for p in part_ids}


def read_text(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None


def write_text(path: Path, text: str) -> None:
    """Writes ``text`` as UTF-8 exactly as given (no newline translation), as the workbench's
    file service does."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def find_manifest(folder: Path) -> Path | None:
    """The ``.saengine`` file of the project at ``folder`` (the first by name if several)."""
    try:
        candidates = sorted(
            p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == PROJECT_EXTENSION
        )
    except OSError:
        return None
    return candidates[0] if candidates else None


def open_project(path: str | Path) -> Project:
    """The project at ``path``: its folder, or its ``.saengine`` file."""
    path = Path(path)
    if path.is_file() and path.suffix.lower() == PROJECT_EXTENSION:
        manifest: Path | None = path
        root = path.parent
    else:
        root = path
        manifest = find_manifest(path) if path.is_dir() else None
    if manifest is None:
        raise ProjectError(
            f"{path} is not a SAEngine project: it has no {PROJECT_EXTENSION} file"
            if path.exists()
            else f"{path} does not exist"
        )
    name = manifest.stem
    project_type = "building"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ProjectError(f"{manifest.name} cannot be read: {error}") from error
    if isinstance(data, dict):
        if isinstance(data.get("name"), str) and data["name"]:
            name = data["name"]
        if data.get("type") == "structure":
            project_type = "structure"
    return Project(root=root.resolve(), manifest=manifest.resolve(), name=name, type=project_type)
