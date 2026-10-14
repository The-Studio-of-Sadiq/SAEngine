"""
Property Panel — displays and inspects properties of the selected object.
"""

from __future__ import annotations

from typing import Optional, Any
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QHeaderView
)

from saengine.core.grids import GridLine
from saengine.core.stories import Story
from saengine.core.project import Project, ProjectSettings


class PropertyPanel(QWidget):
    """
    Inspector panel displaying name/value properties for selected entities.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(4)

        # Header
        self._header = QLabel("PROPERTIES")
        self._header.setObjectName("panelHeader")
        self._header.setStyleSheet("font-weight: bold; color: #9aa0a6; padding: 4px;")
        self._layout.addWidget(self._header)

        # Entity title label
        self._target_label = QLabel("No selection")
        self._target_label.setStyleSheet("color: #4FC3F7; font-weight: bold; padding: 2px 4px;")
        self._layout.addWidget(self._target_label)

        # Property table
        self.table = QTableWidget(self)
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Property", "Value"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self._layout.addWidget(self.table)

    def show_object(self, obj_type: str, obj: Any) -> None:
        """Display properties for a given object."""
        self.table.setRowCount(0)

        if isinstance(obj, Story):
            self._target_label.setText(f"Story: {obj.name}")
            props = [
                ("Name", obj.name),
                ("Elevation", f"{obj.elevation:.3f} m"),
                ("Height", f"{obj.height:.3f} m"),
                ("Is Base", "Yes" if obj.is_base else "No"),
                ("Is Master Story", "Yes" if obj.is_master else "No"),
                ("Color", str(obj.color)),
                ("Story ID", obj.id[:8] + "..."),
            ]
        elif isinstance(obj, GridLine):
            self._target_label.setText(f"Grid Line: {obj.label}")
            props = [
                ("Label", obj.label),
                ("Coordinate", f"{obj.position:.3f} m"),
                ("Visible", "Yes" if obj.is_visible else "No"),
                ("Grid ID", obj.id[:8] + "..."),
            ]
        elif isinstance(obj, ProjectSettings):
            self._target_label.setText(f"Project: {obj.project_name}")
            props = [
                ("Project Name", obj.project_name),
                ("Author", obj.author or "Not specified"),
                ("Description", obj.description or "None"),
            ]
        elif isinstance(obj, Project):
            self._target_label.setText(f"Project: {obj.settings.project_name}")
            props = [
                ("Project Name", obj.settings.project_name),
                ("Unit System", obj.units.active_system.display_name),
                ("Total Stories", str(obj.stories.num_stories)),
                ("Building Height", f"{obj.stories.total_height:.2f} m"),
                ("X Grids", str(len(obj.grids.x_grids))),
                ("Y Grids", str(len(obj.grids.y_grids))),
                ("X Dimension", f"{obj.grids.x_extent:.2f} m"),
                ("Y Dimension", f"{obj.grids.y_extent:.2f} m"),
                ("Has Unsaved Changes", "Yes" if obj.is_dirty else "No"),
            ]
        else:
            self._target_label.setText("Model Summary")
            props = [("Status", "Select an item to view properties")]

        self.table.setRowCount(len(props))
        for row, (prop, val) in enumerate(props):
            item_prop = QTableWidgetItem(prop)
            item_prop.setFlags(item_prop.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_prop.setForeground(Qt.GlobalColor.gray)

            item_val = QTableWidgetItem(str(val))
            item_val.setFlags(item_val.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.table.setItem(row, 0, item_prop)
            self.table.setItem(row, 1, item_val)
