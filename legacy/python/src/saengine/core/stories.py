"""
Story/level system for SAEngine.

Defines the vertical story structure of the building. Each story has a name,
elevation, and height. Stories are ordered from base to top.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
from uuid import uuid4


@dataclass
class Story:
    """A single building story/level."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    elevation: float = 0.0    # Elevation of top of story (meters, from base)
    height: float = 3.0       # Story height (meters)
    is_base: bool = False      # True for the base/ground level
    is_master: bool = True     # Master story for stiffness similarity
    color: str = "#4FC3F7"     # Display color

    @property
    def bottom_elevation(self) -> float:
        """Elevation of the bottom of this story."""
        return self.elevation - self.height

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "elevation": self.elevation,
            "height": self.height,
            "is_base": self.is_base,
            "is_master": self.is_master,
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Story:
        return cls(
            id=data.get("id", str(uuid4())),
            name=data.get("name", ""),
            elevation=data.get("elevation", 0.0),
            height=data.get("height", 3.0),
            is_base=data.get("is_base", False),
            is_master=data.get("is_master", True),
            color=data.get("color", "#4FC3F7"),
        )


@dataclass
class StorySystem:
    """
    Manages the building's story/level structure.

    Stories are ordered from bottom (base) to top. The base story
    sits at elevation 0 and represents the ground level.
    """

    stories: List[Story] = field(default_factory=list)

    def add_story(self, name: str, height: float = 3.0,
                  is_base: bool = False) -> Story:
        """
        Add a new story on top of the existing structure.

        Args:
            name: Story name (e.g., "Story 1", "Roof")
            height: Story height in meters
            is_base: Whether this is the base level
        """
        if not self.stories:
            elevation = 0.0 if is_base else height
        else:
            top_story = self.stories[-1]
            elevation = top_story.elevation + height

        story = Story(
            name=name,
            elevation=elevation,
            height=height,
            is_base=is_base,
        )
        self.stories.append(story)
        return story

    def insert_story(self, index: int, name: str, height: float = 3.0) -> Story:
        """Insert a story at a specific position and recalculate elevations."""
        story = Story(name=name, height=height)
        self.stories.insert(index, story)
        self._recalculate_elevations()
        return story

    def remove_story(self, story_id: str) -> Optional[Story]:
        """Remove a story by ID and recalculate elevations."""
        for i, s in enumerate(self.stories):
            if s.id == story_id:
                removed = self.stories.pop(i)
                self._recalculate_elevations()
                return removed
        return None

    def get_story_by_id(self, story_id: str) -> Optional[Story]:
        """Find a story by ID."""
        for s in self.stories:
            if s.id == story_id:
                return s
        return None

    def get_story_by_name(self, name: str) -> Optional[Story]:
        """Find a story by name."""
        for s in self.stories:
            if s.name == name:
                return s
        return None

    def get_story_at_elevation(self, elevation: float,
                                tolerance: float = 0.01) -> Optional[Story]:
        """Find a story at a given elevation (within tolerance)."""
        for s in self.stories:
            if abs(s.elevation - elevation) < tolerance:
                return s
        return None

    @property
    def total_height(self) -> float:
        """Total building height."""
        if not self.stories:
            return 0.0
        return self.stories[-1].elevation

    @property
    def num_stories(self) -> int:
        """Number of stories (excluding base)."""
        return sum(1 for s in self.stories if not s.is_base)

    @property
    def elevations(self) -> List[float]:
        """All story elevations."""
        return [s.elevation for s in self.stories]

    def _recalculate_elevations(self) -> None:
        """Recalculate all elevations based on heights from bottom up."""
        current_elevation = 0.0
        for story in self.stories:
            if story.is_base:
                story.elevation = 0.0
            else:
                current_elevation += story.height
                story.elevation = current_elevation

    def clear(self) -> None:
        """Remove all stories."""
        self.stories.clear()

    @classmethod
    def create_default(cls, n_stories: int = 3,
                       typical_height: float = 3.0,
                       ground_height: float = 4.0) -> StorySystem:
        """
        Create a default story system.

        Args:
            n_stories: Number of stories above ground
            typical_height: Typical story height (meters)
            ground_height: Ground floor height (meters)
        """
        system = cls()
        system.add_story("Base", height=0.0, is_base=True)
        for i in range(1, n_stories + 1):
            h = ground_height if i == 1 else typical_height
            name = f"Story {i}" if i < n_stories else "Roof"
            system.add_story(name, height=h)
        return system

    def to_dict(self) -> dict:
        return {
            "stories": [s.to_dict() for s in self.stories],
        }

    @classmethod
    def from_dict(cls, data: dict) -> StorySystem:
        system = cls()
        system.stories = [Story.from_dict(s) for s in data.get("stories", [])]
        return system
