"""
Model commands — undoable commands for grid and story operations.
"""

from __future__ import annotations

import copy
from typing import Optional

from saengine.commands.command_manager import Command
from saengine.core.grids import GridLine, GridSystem
from saengine.core.stories import Story, StorySystem


# ─── Grid Commands ───────────────────────────────────────────────

class AddXGridCommand(Command):
    """Add a grid line in the X direction."""

    def __init__(self, grid_system: GridSystem, label: str, position: float):
        super().__init__(f"Add X grid '{label}' at {position:.2f}m")
        self.grid_system = grid_system
        self.label = label
        self.position = position
        self._grid: Optional[GridLine] = None

    def execute(self) -> None:
        self._grid = self.grid_system.add_x_grid(self.label, self.position)

    def undo(self) -> None:
        if self._grid:
            self.grid_system.remove_grid(self._grid.id)


class AddYGridCommand(Command):
    """Add a grid line in the Y direction."""

    def __init__(self, grid_system: GridSystem, label: str, position: float):
        super().__init__(f"Add Y grid '{label}' at {position:.2f}m")
        self.grid_system = grid_system
        self.label = label
        self.position = position
        self._grid: Optional[GridLine] = None

    def execute(self) -> None:
        self._grid = self.grid_system.add_y_grid(self.label, self.position)

    def undo(self) -> None:
        if self._grid:
            self.grid_system.remove_grid(self._grid.id)


class RemoveGridCommand(Command):
    """Remove a grid line."""

    def __init__(self, grid_system: GridSystem, grid_id: str, direction: str):
        super().__init__(f"Remove grid")
        self.grid_system = grid_system
        self.grid_id = grid_id
        self.direction = direction  # "x" or "y"
        self._removed_grid: Optional[GridLine] = None

    def execute(self) -> None:
        self._removed_grid = self.grid_system.remove_grid(self.grid_id)
        if self._removed_grid:
            self.description = f"Remove {self.direction.upper()} grid '{self._removed_grid.label}'"

    def undo(self) -> None:
        if self._removed_grid:
            if self.direction == "x":
                restored = self.grid_system.add_x_grid(
                    self._removed_grid.label, self._removed_grid.position
                )
            else:
                restored = self.grid_system.add_y_grid(
                    self._removed_grid.label, self._removed_grid.position
                )
            # Restore original ID
            restored.id = self._removed_grid.id


class ModifyGridCommand(Command):
    """Modify a grid line's position or label."""

    def __init__(self, grid_system: GridSystem, grid_id: str,
                 new_label: Optional[str] = None,
                 new_position: Optional[float] = None):
        super().__init__("Modify grid")
        self.grid_system = grid_system
        self.grid_id = grid_id
        self.new_label = new_label
        self.new_position = new_position
        self._old_label: str = ""
        self._old_position: float = 0.0

    def execute(self) -> None:
        grid = self.grid_system.get_grid_by_id(self.grid_id)
        if grid:
            self._old_label = grid.label
            self._old_position = grid.position
            if self.new_label is not None:
                grid.label = self.new_label
            if self.new_position is not None:
                grid.position = self.new_position
            self.grid_system._sort_grids()
            self.description = f"Modify grid '{self._old_label}'"

    def undo(self) -> None:
        grid = self.grid_system.get_grid_by_id(self.grid_id)
        if grid:
            grid.label = self._old_label
            grid.position = self._old_position
            self.grid_system._sort_grids()


# ─── Story Commands ──────────────────────────────────────────────

class AddStoryCommand(Command):
    """Add a story to the building."""

    def __init__(self, story_system: StorySystem, name: str,
                 height: float = 3.0, is_base: bool = False):
        super().__init__(f"Add story '{name}'")
        self.story_system = story_system
        self.name = name
        self.height = height
        self.is_base = is_base
        self._story: Optional[Story] = None

    def execute(self) -> None:
        self._story = self.story_system.add_story(
            self.name, self.height, self.is_base
        )

    def undo(self) -> None:
        if self._story:
            self.story_system.remove_story(self._story.id)


class RemoveStoryCommand(Command):
    """Remove a story from the building."""

    def __init__(self, story_system: StorySystem, story_id: str):
        super().__init__("Remove story")
        self.story_system = story_system
        self.story_id = story_id
        self._removed_story: Optional[Story] = None
        self._index: int = 0

    def execute(self) -> None:
        for i, s in enumerate(self.story_system.stories):
            if s.id == self.story_id:
                self._index = i
                break
        self._removed_story = self.story_system.remove_story(self.story_id)
        if self._removed_story:
            self.description = f"Remove story '{self._removed_story.name}'"

    def undo(self) -> None:
        if self._removed_story:
            restored = self.story_system.insert_story(
                self._index, self._removed_story.name, self._removed_story.height
            )
            restored.id = self._removed_story.id
            restored.is_base = self._removed_story.is_base
            restored.color = self._removed_story.color


class ModifyStoryCommand(Command):
    """Modify a story's name or height."""

    def __init__(self, story_system: StorySystem, story_id: str,
                 new_name: Optional[str] = None,
                 new_height: Optional[float] = None):
        super().__init__("Modify story")
        self.story_system = story_system
        self.story_id = story_id
        self.new_name = new_name
        self.new_height = new_height
        self._old_name: str = ""
        self._old_height: float = 0.0

    def execute(self) -> None:
        story = self.story_system.get_story_by_id(self.story_id)
        if story:
            self._old_name = story.name
            self._old_height = story.height
            if self.new_name is not None:
                story.name = self.new_name
            if self.new_height is not None:
                story.height = self.new_height
                self.story_system._recalculate_elevations()
            self.description = f"Modify story '{self._old_name}'"

    def undo(self) -> None:
        story = self.story_system.get_story_by_id(self.story_id)
        if story:
            story.name = self._old_name
            story.height = self._old_height
            self.story_system._recalculate_elevations()


class SetGridSystemCommand(Command):
    """Replace an entire grid system with a new one (undoable)."""

    def __init__(self, project_grids: GridSystem, new_grids: GridSystem, description: str = "Update Grid System"):
        super().__init__(description)
        self.project_grids = project_grids
        self.new_grids = copy.deepcopy(new_grids)
        self.old_grids = copy.deepcopy(project_grids)

    def execute(self) -> None:
        self.project_grids.x_grids = copy.deepcopy(self.new_grids.x_grids)
        self.project_grids.y_grids = copy.deepcopy(self.new_grids.y_grids)
        self.project_grids._sort_grids()

    def undo(self) -> None:
        self.project_grids.x_grids = copy.deepcopy(self.old_grids.x_grids)
        self.project_grids.y_grids = copy.deepcopy(self.old_grids.y_grids)
        self.project_grids._sort_grids()


class SetStorySystemCommand(Command):
    """Replace an entire story system with a new one (undoable)."""

    def __init__(self, project_stories: StorySystem, new_stories: StorySystem, description: str = "Update Story Data"):
        super().__init__(description)
        self.project_stories = project_stories
        self.new_stories = copy.deepcopy(new_stories)
        self.old_stories = copy.deepcopy(project_stories)

    def execute(self) -> None:
        self.project_stories.stories = copy.deepcopy(self.new_stories.stories)
        self.project_stories._recalculate_elevations()

    def undo(self) -> None:
        self.project_stories.stories = copy.deepcopy(self.old_stories.stories)
        self.project_stories._recalculate_elevations()

