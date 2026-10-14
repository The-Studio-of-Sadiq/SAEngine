"""
Project I/O — save and load .saengine project files.

File format: JSON for human readability and easy debugging.
Future: HDF5 for large result datasets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from saengine.core.project import Project


# File extension
SAENGINE_EXTENSION = ".saengine"
SAENGINE_FILTER = f"SAEngine Project (*{SAENGINE_EXTENSION})"


def save_project(project: Project, file_path: Path) -> None:
    """
    Save a project to a .saengine JSON file.

    Args:
        project: The project to save.
        file_path: Target file path.
    """
    file_path = file_path.with_suffix(SAENGINE_EXTENSION)
    data = project.to_dict()

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    project.file_path = file_path
    project.mark_clean()


def load_project(file_path: Path) -> Project:
    """
    Load a project from a .saengine JSON file.

    Args:
        file_path: Path to the .saengine file.

    Returns:
        The loaded Project instance.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        json.JSONDecodeError: If the file is not valid JSON.
        KeyError: If required data fields are missing.
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"Project file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    project = Project.from_dict(data)
    project.file_path = file_path
    project.mark_clean()
    return project


def import_json(file_path: Path) -> dict:
    """
    Import arbitrary JSON data (for design code properties, section data, etc.).

    Args:
        file_path: Path to the JSON file.

    Returns:
        Parsed dictionary.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def import_csv(file_path: Path) -> list:
    """
    Import CSV data (for section databases, design code properties, etc.).

    Args:
        file_path: Path to the CSV file.

    Returns:
        List of dictionaries (one per row).
    """
    import csv

    rows = []
    with open(file_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


class RecentFiles:
    """Manages a list of recently opened project files."""

    MAX_RECENT = 10

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or Path.home() / ".saengine" / "recent.json"
        self._files: list[str] = []
        self._load()

    def _load(self) -> None:
        """Load recent files list from disk."""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r") as f:
                    data = json.load(f)
                self._files = data.get("recent_files", [])
            except (json.JSONDecodeError, OSError):
                self._files = []

    def _save(self) -> None:
        """Persist recent files list to disk."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w") as f:
            json.dump({"recent_files": self._files}, f, indent=2)

    def add(self, file_path: Path) -> None:
        """Add a file to the recent list."""
        path_str = str(file_path.resolve())
        # Remove if already present (will re-add at top)
        if path_str in self._files:
            self._files.remove(path_str)
        self._files.insert(0, path_str)
        # Trim to max
        self._files = self._files[:self.MAX_RECENT]
        self._save()

    @property
    def files(self) -> list[Path]:
        """Get list of recent file paths (most recent first)."""
        return [Path(f) for f in self._files if Path(f).exists()]

    def clear(self) -> None:
        """Clear the recent files list."""
        self._files.clear()
        self._save()


class ProjectIO:
    """Helper wrapper for project persistence and recent file tracking."""

    def __init__(self):
        self.recent_files = RecentFiles()

    def save_project(self, project: Project, file_path: Path | str) -> bool:
        """Save project to file."""
        try:
            path = Path(file_path)
            save_project(project, path)
            self.recent_files.add(path)
            return True
        except Exception:
            return False

    def load_project(self, file_path: Path | str) -> Optional[Project]:
        """Load project from file."""
        try:
            path = Path(file_path)
            proj = load_project(path)
            self.recent_files.add(path)
            return proj
        except Exception:
            return None

