"""
Project container for SAEngine.

A Project holds all data for a single structural model: grids, stories,
elements, loads, results, and settings. It is the root object that gets
serialized to/from .saengine files.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from saengine.core.grids import GridSystem
from saengine.core.stories import StorySystem
from saengine.core.units import UnitManager, UnitSystem


@dataclass
class ProjectSettings:
    """Application-level project settings."""

    project_name: str = "Untitled"
    author: str = ""
    description: str = ""
    created_at: float = field(default_factory=time.time)
    modified_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "author": self.author,
            "description": self.description,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProjectSettings:
        return cls(
            project_name=data.get("project_name", "Untitled"),
            author=data.get("author", ""),
            description=data.get("description", ""),
            created_at=data.get("created_at", time.time()),
            modified_at=data.get("modified_at", time.time()),
        )


@dataclass
class Project:
    """
    Root container for a structural model project.

    Holds all model data, settings, and state. This is the central object
    that the entire application operates on.
    """

    settings: ProjectSettings = field(default_factory=ProjectSettings)
    units: UnitManager = field(default_factory=UnitManager)
    grids: GridSystem = field(default_factory=GridSystem)
    stories: StorySystem = field(default_factory=StorySystem)

    # File path (None if never saved)
    file_path: Optional[Path] = None

    # Dirty flag — True if unsaved changes exist
    _is_dirty: bool = False

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    def mark_dirty(self) -> None:
        """Mark the project as having unsaved changes."""
        self._is_dirty = True
        self.settings.modified_at = time.time()

    def mark_clean(self) -> None:
        """Mark the project as saved (no unsaved changes)."""
        self._is_dirty = False

    @property
    def display_name(self) -> str:
        """Name to show in the title bar."""
        name = self.settings.project_name
        if self.file_path:
            name = self.file_path.stem
        if self._is_dirty:
            name += " *"
        return name

    @classmethod
    def create_new(cls, name: str = "Untitled",
                   unit_system: UnitSystem = UnitSystem.SI) -> Project:
        """Create a new empty project with defaults."""
        project = cls(
            settings=ProjectSettings(project_name=name),
            units=UnitManager(active_system=unit_system),
            grids=GridSystem.create_default(),
            stories=StorySystem.create_default(),
        )
        return project

    def to_dict(self) -> dict:
        """Serialize the entire project to a dictionary."""
        return {
            "saengine_version": "0.1.0",
            "settings": self.settings.to_dict(),
            "units": self.units.to_dict(),
            "grids": self.grids.to_dict(),
            "stories": self.stories.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Project:
        """Deserialize a project from a dictionary."""
        return cls(
            settings=ProjectSettings.from_dict(data.get("settings", {})),
            units=UnitManager.from_dict(data.get("units", {})),
            grids=GridSystem.from_dict(data.get("grids", {})),
            stories=StorySystem.from_dict(data.get("stories", {})),
        )
