"""
Grid system for SAEngine.

Defines orthogonal grid lines (X and Y directions) that form the structural
layout of the building. Grids are named (A, B, C... or 1, 2, 3...) and
positioned at specific coordinates.
"""

from __future__ import annotations

import string
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import uuid4


@dataclass
class GridLine:
    """A single grid line in one direction."""

    id: str = field(default_factory=lambda: str(uuid4()))
    label: str = ""
    position: float = 0.0  # Position in meters (internal base unit)
    is_visible: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "position": self.position,
            "is_visible": self.is_visible,
        }

    @classmethod
    def from_dict(cls, data: dict) -> GridLine:
        return cls(
            id=data.get("id", str(uuid4())),
            label=data.get("label", ""),
            position=data.get("position", 0.0),
            is_visible=data.get("is_visible", True),
        )


@dataclass
class GridSystem:
    """
    Manages the building's grid layout.

    Contains X-direction grids (typically labeled 1, 2, 3...) and
    Y-direction grids (typically labeled A, B, C...).
    """

    x_grids: List[GridLine] = field(default_factory=list)
    y_grids: List[GridLine] = field(default_factory=list)

    def add_x_grid(self, label: str, position: float) -> GridLine:
        """Add a grid line in the X direction."""
        grid = GridLine(label=label, position=position)
        self.x_grids.append(grid)
        self._sort_grids()
        return grid

    def add_y_grid(self, label: str, position: float) -> GridLine:
        """Add a grid line in the Y direction."""
        grid = GridLine(label=label, position=position)
        self.y_grids.append(grid)
        self._sort_grids()
        return grid

    def remove_grid(self, grid_id: str) -> Optional[GridLine]:
        """Remove a grid line by ID from either direction."""
        for grid_list in (self.x_grids, self.y_grids):
            for i, g in enumerate(grid_list):
                if g.id == grid_id:
                    return grid_list.pop(i)
        return None

    def get_grid_by_id(self, grid_id: str) -> Optional[GridLine]:
        """Find a grid line by its ID."""
        for g in self.x_grids + self.y_grids:
            if g.id == grid_id:
                return g
        return None

    def get_grid_by_label(self, label: str) -> Optional[GridLine]:
        """Find a grid line by its label."""
        for g in self.x_grids + self.y_grids:
            if g.label == label:
                return g
        return None

    def _sort_grids(self) -> None:
        """Sort grids by position."""
        self.x_grids.sort(key=lambda g: g.position)
        self.y_grids.sort(key=lambda g: g.position)

    @property
    def x_positions(self) -> List[float]:
        return [g.position for g in self.x_grids]

    @property
    def y_positions(self) -> List[float]:
        return [g.position for g in self.y_grids]

    @property
    def x_extent(self) -> float:
        """Total width in X direction."""
        if len(self.x_grids) < 2:
            return 0.0
        return self.x_grids[-1].position - self.x_grids[0].position

    @property
    def y_extent(self) -> float:
        """Total width in Y direction."""
        if len(self.y_grids) < 2:
            return 0.0
        return self.y_grids[-1].position - self.y_grids[0].position

    def clear(self) -> None:
        """Remove all grid lines."""
        self.x_grids.clear()
        self.y_grids.clear()

    @classmethod
    def create_default(cls, n_x: int = 4, n_y: int = 3,
                       spacing_x: float = 6.0, spacing_y: float = 6.0) -> GridSystem:
        """
        Create a default grid system.

        Args:
            n_x: Number of X grids (labeled 1, 2, 3...)
            n_y: Number of Y grids (labeled A, B, C...)
            spacing_x: Spacing between X grids in meters
            spacing_y: Spacing between Y grids in meters
        """
        system = cls()
        for i in range(n_x):
            system.add_x_grid(label=str(i + 1), position=i * spacing_x)
        for j in range(n_y):
            label = string.ascii_uppercase[j] if j < 26 else f"A{j - 25}"
            system.add_y_grid(label=label, position=j * spacing_y)
        return system

    def to_dict(self) -> dict:
        return {
            "x_grids": [g.to_dict() for g in self.x_grids],
            "y_grids": [g.to_dict() for g in self.y_grids],
        }

    @classmethod
    def from_dict(cls, data: dict) -> GridSystem:
        system = cls()
        system.x_grids = [GridLine.from_dict(g) for g in data.get("x_grids", [])]
        system.y_grids = [GridLine.from_dict(g) for g in data.get("y_grids", [])]
        return system
