"""
Model Explorer Panel — hierarchical tree navigation of the structural model.

ETABS-inspired tree structure showing Project Information, Structure Layout
(Stories, Grids), Properties, and Loads.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QHeaderView, QMenu
)

if TYPE_CHECKING:
    from saengine.core.project import Project


class ModelExplorerPanel(QWidget):
    """
    Model Explorer tree dock widget.

    Signals:
        selection_changed(str, object): Emitted when a tree node is selected.
            First arg is node type ('project', 'story', 'grid_x', 'grid_y', etc.),
            Second arg is the selected object or identifier.
        edit_requested(str): Emitted when user double-clicks or triggers edit ('grids', 'stories').
    """

    selection_changed = Signal(str, object)
    edit_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)

        # Header
        header = QLabel("MODEL EXPLORER")
        header.setObjectName("panelHeader")
        header.setStyleSheet("font-weight: bold; color: #9aa0a6; padding: 4px;")
        self._layout.addWidget(header)

        # Tree widget
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._layout.addWidget(self.tree)

        self._project: Optional[Project] = None

    def set_project(self, project: Project) -> None:
        """Set or update the active project and refresh the tree."""
        self._project = project
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the model tree from current project state."""
        self.tree.clear()
        if not self._project:
            return

        # ── Root: Model ──────────────────────────────────────────
        root = QTreeWidgetItem(self.tree, ["🏢 " + self._project.settings.project_name])
        root.setData(0, Qt.ItemDataRole.UserRole, ("project", self._project.settings))
        root.setExpanded(True)

        # 1. Project Info
        proj_info = QTreeWidgetItem(root, ["📋 Project Information"])
        proj_info.setData(0, Qt.ItemDataRole.UserRole, ("project_info", self._project.settings))
        QTreeWidgetItem(proj_info, [f"Name: {self._project.settings.project_name}"])
        QTreeWidgetItem(proj_info, [f"Units: {self._project.units.active_system.display_name}"])

        # 2. Structure Layout
        layout_node = QTreeWidgetItem(root, ["📐 Structure Layout"])
        layout_node.setExpanded(True)

        # 2a. Stories
        stories_node = QTreeWidgetItem(layout_node, [f"🏢 Story Levels ({len(self._project.stories.stories)})"])
        stories_node.setData(0, Qt.ItemDataRole.UserRole, ("stories_group", self._project.stories))
        stories_node.setExpanded(True)
        for s in reversed(self._project.stories.stories):
            story_item = QTreeWidgetItem(stories_node, [f"Level: {s.name} (+{s.elevation:.2f}m)"])
            story_item.setData(0, Qt.ItemDataRole.UserRole, ("story", s))

        # 2b. Grid System
        grids_node = QTreeWidgetItem(layout_node, ["🌐 Grid Systems"])
        grids_node.setData(0, Qt.ItemDataRole.UserRole, ("grids_group", self._project.grids))
        grids_node.setExpanded(True)

        x_group = QTreeWidgetItem(grids_node, [f"X-Grids ({len(self._project.grids.x_grids)})"])
        x_group.setData(0, Qt.ItemDataRole.UserRole, ("x_grids_group", self._project.grids.x_grids))
        for gx in self._project.grids.x_grids:
            gx_item = QTreeWidgetItem(x_group, [f"Grid {gx.label} (X = {gx.position:.2f}m)"])
            gx_item.setData(0, Qt.ItemDataRole.UserRole, ("grid_x", gx))

        y_group = QTreeWidgetItem(grids_node, [f"Y-Grids ({len(self._project.grids.y_grids)})"])
        y_group.setData(0, Qt.ItemDataRole.UserRole, ("y_grids_group", self._project.grids.y_grids))
        for gy in self._project.grids.y_grids:
            gy_item = QTreeWidgetItem(y_group, [f"Grid {gy.label} (Y = {gy.position:.2f}m)"])
            gy_item.setData(0, Qt.ItemDataRole.UserRole, ("grid_y", gy))

        # 3. Structural Elements (for future phases)
        elements_node = QTreeWidgetItem(root, ["🏗️ Elements"])
        QTreeWidgetItem(elements_node, ["Columns (0)"])
        QTreeWidgetItem(elements_node, ["Beams (0)"])
        QTreeWidgetItem(elements_node, ["Walls / Slabs (0)"])

        # 4. Loads & Cases
        loads_node = QTreeWidgetItem(root, ["⚡ Loads & Combinations"])
        QTreeWidgetItem(loads_node, ["Dead Load (DL)"])
        QTreeWidgetItem(loads_node, ["Live Load (LL)"])

    def _on_selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            return
        data = items[0].data(0, Qt.ItemDataRole.UserRole)
        if data:
            node_type, obj = data
            self.selection_changed.emit(node_type, obj)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        node_type, _ = data
        if node_type in ("grids_group", "x_grids_group", "y_grids_group", "grid_x", "grid_y"):
            self.edit_requested.emit("grids")
        elif node_type in ("stories_group", "story"):
            self.edit_requested.emit("stories")

    def _on_context_menu(self, position) -> None:
        item = self.tree.itemAt(position)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        node_type, _ = data
        menu = QMenu(self)

        if node_type in ("grids_group", "x_grids_group", "y_grids_group", "grid_x", "grid_y"):
            act_edit = menu.addAction("Edit Grid System...")
            act_edit.triggered.connect(lambda: self.edit_requested.emit("grids"))
        elif node_type in ("stories_group", "story"):
            act_edit = menu.addAction("Edit Story Levels...")
            act_edit.triggered.connect(lambda: self.edit_requested.emit("stories"))

        if not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(position))
