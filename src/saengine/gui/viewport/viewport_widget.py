"""
3D Viewport Widget — PyVista/VTK integration for structural visualization.

Embeds a PyVista plotter into PySide6 using pyvistaqt. Handles grid rendering,
model display, camera controls, and object picking.
"""

from __future__ import annotations

from typing import Optional, List, TYPE_CHECKING
import os

import numpy as np
import pyvista as pv

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFrame

try:
    from pyvistaqt import QtInteractor
    HAS_PYVISTAQT = True
except ImportError:
    HAS_PYVISTAQT = False

if TYPE_CHECKING:
    from saengine.core.grids import GridSystem
    from saengine.core.stories import StorySystem


# Color constants (RGBA 0-255)
GRID_COLOR = "#4a4e57"
GRID_LABEL_COLOR = "#9aa0a6"
AXIS_X_COLOR = "#E57373"    # Red
AXIS_Y_COLOR = "#81C784"    # Green
AXIS_Z_COLOR = "#4FC3F7"    # Blue
BACKGROUND_COLOR = "#1a1d23"
BACKGROUND_COLOR_TOP = "#252830"
FLOOR_PLANE_COLOR = "#2d313a"
STORY_LINE_COLOR = "#353840"


class ViewportWidget(QWidget):
    """
    3D viewport for structural model visualization.

    Uses PyVista + pyvistaqt to provide interactive 3D rendering with
    orbit/pan/zoom controls, grid display, and future element rendering.

    Signals:
        point_picked(tuple): Emitted when a point is picked in 3D space.
        object_selected(str): Emitted with the ID of a selected object.
    """

    point_picked = Signal(tuple)
    object_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self.plotter: Optional[QtInteractor] = None
        self._grid_actors = []
        self._label_actors = []
        self._story_actors = []
        self._element_actors = {}

        self._init_plotter()

    def _init_plotter(self) -> None:
        """Initialize the PyVista plotter."""
        if not HAS_PYVISTAQT or os.environ.get("SAENGINE_HEADLESS") == "1":
            from PySide6.QtWidgets import QLabel
            fallback = QLabel("3D Viewport (Headless / Safe Mode)")
            fallback.setAlignment(Qt.AlignmentFlag.AlignCenter)
            fallback.setStyleSheet("color: #4FC3F7; font-size: 14px; background: #14161a;")
            self._layout.addWidget(fallback)
            return

        # Suppress VTK warnings
        pv.global_theme.allow_empty_mesh = True

        # Create the interactor
        self.plotter = QtInteractor(self)
        self._layout.addWidget(self.plotter.interactor)

        # Configure appearance
        self.plotter.set_background(BACKGROUND_COLOR, top=BACKGROUND_COLOR_TOP)
        self.plotter.enable_anti_aliasing("ssaa")

        # Add axis indicator (bottom-left)
        self.plotter.add_axes(
            line_width=2,
            color="#9aa0a6",
            x_color=AXIS_X_COLOR,
            y_color=AXIS_Y_COLOR,
            z_color=AXIS_Z_COLOR,
            xlabel="X",
            ylabel="Y",
            zlabel="Z",
            label_size=(0.12, 0.05),
        )

        # Set initial camera
        self.plotter.camera_position = "iso"
        self.plotter.camera.zoom(0.8)

    def render_grids(self, grids: GridSystem, stories: StorySystem) -> None:
        """
        Render the grid system and story levels in the viewport.

        Draws grid lines on the ground plane (Z=0) and at story elevations.
        """
        if not self.plotter:
            return

        # Clear previous grid actors
        self._clear_grid_actors()

        x_positions = grids.x_positions
        y_positions = grids.y_positions
        elevations = stories.elevations

        if not x_positions or not y_positions:
            return

        x_min, x_max = min(x_positions), max(x_positions)
        y_min, y_max = min(y_positions), max(y_positions)
        max_elevation = max(elevations) if elevations else 0.0

        # Extension beyond grid edges for visual padding
        pad = 1.0

        # ── Ground plane (subtle transparent fill) ──────────
        ground = pv.Plane(
            center=((x_min + x_max) / 2, (y_min + y_max) / 2, 0),
            direction=(0, 0, 1),
            i_size=x_max - x_min + pad * 2,
            j_size=y_max - y_min + pad * 2,
        )
        actor = self.plotter.add_mesh(
            ground,
            color=FLOOR_PLANE_COLOR,
            opacity=0.3,
            show_edges=False,
            name="ground_plane",
        )
        self._grid_actors.append("ground_plane")

        # ── X grid lines (along Y direction) ────────────────
        for i, x in enumerate(x_positions):
            line = pv.Line(
                (x, y_min - pad, 0),
                (x, y_max + pad, 0),
            )
            name = f"xgrid_{i}"
            self.plotter.add_mesh(
                line, color=GRID_COLOR, line_width=1.5,
                name=name,
            )
            self._grid_actors.append(name)

            # Vertical grid lines (up through stories)
            if max_elevation > 0:
                for y in y_positions:
                    vline = pv.Line((x, y, 0), (x, y, max_elevation))
                    vname = f"vgrid_x{i}_y{y_positions.index(y)}"
                    self.plotter.add_mesh(
                        vline, color=GRID_COLOR, line_width=0.5,
                        opacity=0.3, name=vname,
                    )
                    self._grid_actors.append(vname)

            # Label
            label_name = f"xlabel_{i}"
            grid_label = grids.x_grids[i].label if i < len(grids.x_grids) else str(i)
            self.plotter.add_point_labels(
                np.array([[x, y_min - pad - 0.8, 0]]),
                [grid_label],
                font_size=14,
                text_color=GRID_LABEL_COLOR,
                point_size=0,
                name=label_name,
                shape_opacity=0,
                always_visible=True,
            )
            self._label_actors.append(label_name)

        # ── Y grid lines (along X direction) ────────────────
        for j, y in enumerate(y_positions):
            line = pv.Line(
                (x_min - pad, y, 0),
                (x_max + pad, y, 0),
            )
            name = f"ygrid_{j}"
            self.plotter.add_mesh(
                line, color=GRID_COLOR, line_width=1.5,
                name=name,
            )
            self._grid_actors.append(name)

            # Vertical grid lines
            if max_elevation > 0:
                for x in x_positions:
                    vline = pv.Line((x, y, 0), (x, y, max_elevation))
                    vname = f"vgrid_y{j}_x{x_positions.index(x)}"
                    # Avoid duplicates with x vertical lines
                    if vname not in self._grid_actors:
                        self.plotter.add_mesh(
                            vline, color=GRID_COLOR, line_width=0.5,
                            opacity=0.3, name=vname,
                        )
                        self._grid_actors.append(vname)

            # Label
            label_name = f"ylabel_{j}"
            grid_label = grids.y_grids[j].label if j < len(grids.y_grids) else str(j)
            self.plotter.add_point_labels(
                np.array([[x_min - pad - 0.8, y, 0]]),
                [grid_label],
                font_size=14,
                text_color=GRID_LABEL_COLOR,
                point_size=0,
                name=label_name,
                shape_opacity=0,
                always_visible=True,
            )
            self._label_actors.append(label_name)

        # ── Story level lines ───────────────────────────────
        for k, elev in enumerate(elevations):
            if elev == 0:
                continue  # Skip base
            # Draw horizontal rectangle at story elevation
            for i, x in enumerate(x_positions):
                line = pv.Line(
                    (x, y_min, elev),
                    (x, y_max, elev),
                )
                name = f"story_x_{k}_{i}"
                self.plotter.add_mesh(
                    line, color=STORY_LINE_COLOR, line_width=1,
                    opacity=0.5, name=name,
                )
                self._story_actors.append(name)

            for j, y in enumerate(y_positions):
                line = pv.Line(
                    (x_min, y, elev),
                    (x_max, y, elev),
                )
                name = f"story_y_{k}_{j}"
                self.plotter.add_mesh(
                    line, color=STORY_LINE_COLOR, line_width=1,
                    opacity=0.5, name=name,
                )
                self._story_actors.append(name)

        # Fit camera to scene
        self.plotter.reset_camera()
        self.plotter.camera.zoom(0.85)

    def _clear_grid_actors(self) -> None:
        """Remove all grid-related actors from the scene."""
        if not self.plotter:
            return

        all_names = self._grid_actors + self._label_actors + self._story_actors
        for name in all_names:
            try:
                self.plotter.remove_actor(name)
            except (KeyError, ValueError):
                pass
        self._grid_actors.clear()
        self._label_actors.clear()
        self._story_actors.clear()

    def clear_all(self) -> None:
        """Clear all actors from the viewport."""
        if self.plotter:
            self.plotter.clear()
            self._grid_actors.clear()
            self._label_actors.clear()
            self._story_actors.clear()
            self._element_actors.clear()

    # ── Camera Presets ─────────────────────────────────────

    def set_view_3d(self) -> None:
        """Set isometric 3D view."""
        if self.plotter:
            self.plotter.camera_position = "iso"
            self.plotter.reset_camera()

    def set_view_xy(self) -> None:
        """Set plan view (top-down, looking along -Z)."""
        if self.plotter:
            self.plotter.view_xy()
            self.plotter.reset_camera()

    def set_view_xz(self) -> None:
        """Set X-elevation view (looking along -Y)."""
        if self.plotter:
            self.plotter.view_xz()
            self.plotter.reset_camera()

    def set_view_yz(self) -> None:
        """Set Y-elevation view (looking along -X)."""
        if self.plotter:
            self.plotter.view_yz()
            self.plotter.reset_camera()

    def fit_all(self) -> None:
        """Fit all objects in view."""
        if self.plotter:
            self.plotter.reset_camera()
            self.plotter.camera.zoom(0.85)

    def close(self) -> None:
        """Clean up the plotter on widget close."""
        if self.plotter:
            self.plotter.close()
        super().close()
