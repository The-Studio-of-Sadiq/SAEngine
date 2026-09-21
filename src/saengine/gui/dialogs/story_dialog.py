"""
Story Data Dialog — define and edit vertical levels/stories.

Supports quick story generation as well as individual story table editing,
mirroring ETABS's Story Data dialog.
"""

from __future__ import annotations

import copy
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QTableWidget,
    QTableWidgetItem, QPushButton, QDialogButtonBox, QLabel,
    QHeaderView, QMessageBox, QCheckBox
)

from saengine.core.stories import Story, StorySystem


class StoryDialog(QDialog):
    """
    Dialog for configuring building stories and elevations.
    """

    def __init__(self, current_stories: StorySystem, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Story Data Definition")
        self.resize(650, 480)

        # Working copy of stories
        self.stories: StorySystem = copy.deepcopy(current_stories)

        self._init_ui()
        self._load_table()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.tab_widget = QTabWidget(self)

        # Tab 1: Detailed Story Table
        self.tab_table = QWidget()
        self._build_table_tab(self.tab_table)
        self.tab_widget.addTab(self.tab_table, "Story Data")

        # Tab 2: Quick Uniform Story Generation
        self.tab_uniform = QWidget()
        self._build_uniform_tab(self.tab_uniform)
        self.tab_widget.addTab(self.tab_uniform, "Quick Story Generation")

        layout.addWidget(self.tab_widget)

        # Dialog Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _build_uniform_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)

        box = QGroupBox("Uniform Story Parameters")
        form = QFormLayout(box)

        self.spin_n_stories = QSpinBox()
        self.spin_n_stories.setRange(1, 200)
        self.spin_n_stories.setValue(self.stories.num_stories or 3)

        self.spin_typical_h = QDoubleSpinBox()
        self.spin_typical_h.setRange(1.0, 50.0)
        self.spin_typical_h.setValue(3.0)
        self.spin_typical_h.setSuffix(" m")

        self.spin_ground_h = QDoubleSpinBox()
        self.spin_ground_h.setRange(1.0, 50.0)
        self.spin_ground_h.setValue(4.0)
        self.spin_ground_h.setSuffix(" m")

        form.addRow("Number of Stories (Above Base):", self.spin_n_stories)
        form.addRow("Typical Story Height:", self.spin_typical_h)
        form.addRow("Ground Floor Height:", self.spin_ground_h)
        layout.addWidget(box)

        btn_apply = QPushButton("Generate Stories")
        btn_apply.clicked.connect(self._apply_uniform)
        layout.addWidget(btn_apply)
        layout.addStretch()

    def _build_table_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Story Name", "Height (m)", "Elevation (m)", "Master Story"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)

        btn_bar = QHBoxLayout()
        btn_add = QPushButton("+ Add Story On Top")
        btn_add.clicked.connect(self._add_story_top)
        btn_del = QPushButton("- Delete Selected Story")
        btn_del.clicked.connect(self._delete_story)
        btn_bar.addWidget(btn_add)
        btn_bar.addWidget(btn_del)
        btn_bar.addStretch()
        layout.addLayout(btn_bar)

    def _load_table(self) -> None:
        """Populate the table from self.stories (top-to-bottom order like ETABS)."""
        self.table.blockSignals(True)
        self.table.setRowCount(0)

        # ETABS lists stories from Roof down to Base
        stories_display = list(reversed(self.stories.stories))
        self.table.setRowCount(len(stories_display))

        for r, story in enumerate(stories_display):
            # Name
            name_item = QTableWidgetItem(story.name)
            if story.is_base:
                name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 0, name_item)

            # Height
            height_item = QTableWidgetItem(f"{story.height:.3f}")
            if story.is_base:
                height_item.setFlags(height_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 1, height_item)

            # Elevation (read-only, auto-computed)
            elev_item = QTableWidgetItem(f"{story.elevation:.3f}")
            elev_item.setFlags(elev_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 2, elev_item)

            # Master Story checkbox
            master_item = QTableWidgetItem()
            master_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            master_item.setCheckState(Qt.CheckState.Checked if story.is_master else Qt.CheckState.Unchecked)
            self.table.setItem(r, 3, master_item)

        self.table.blockSignals(False)

    def _on_cell_changed(self, row: int, col: int) -> None:
        if col == 1:  # Height changed
            self._recalculate_from_table()

    def _recalculate_from_table(self) -> None:
        """Recalculate elevations from bottom to top."""
        total_rows = self.table.rowCount()
        curr_elevation = 0.0
        # Bottom row is Base (index total_rows - 1)
        for r in reversed(range(total_rows)):
            if r == total_rows - 1:
                # Base
                continue
            height_str = self.table.item(r, 1).text() if self.table.item(r, 1) else "3.0"
            try:
                h = max(0.1, float(height_str))
            except ValueError:
                h = 3.0
            curr_elevation += h
            self.table.blockSignals(True)
            self.table.item(r, 2).setText(f"{curr_elevation:.3f}")
            self.table.blockSignals(False)

    def _add_story_top(self) -> None:
        current_top_num = self.stories.num_stories + 1
        name = f"Story {current_top_num}"
        self.stories.add_story(name, height=3.0)
        self._load_table()

    def _delete_story(self) -> None:
        r = self.table.currentRow()
        total_rows = self.table.rowCount()
        if r < 0 or r == total_rows - 1:  # Cannot delete Base
            QMessageBox.information(self, "Delete Story", "Cannot delete the Base story level.")
            return

        # Map display row to story index in self.stories.stories
        story_index = total_rows - 1 - r
        if len(self.stories.stories) > 2:  # Must have at least Base + 1 story
            story_to_remove = self.stories.stories[story_index]
            self.stories.remove_story(story_to_remove.id)
            self._load_table()

    def _apply_uniform(self) -> None:
        n = self.spin_n_stories.value()
        th = self.spin_typical_h.value()
        gh = self.spin_ground_h.value()
        self.stories = StorySystem.create_default(n_stories=n, typical_height=th, ground_height=gh)
        self._load_table()
        self.tab_widget.setCurrentIndex(0)

    def _on_accept(self) -> None:
        # Commit table changes back into self.stories
        total_rows = self.table.rowCount()
        new_stories = []

        curr_elevation = 0.0
        # Iterate from base up
        for r in reversed(range(total_rows)):
            name = self.table.item(r, 0).text().strip() if self.table.item(r, 0) else f"Level {r}"
            is_base = (r == total_rows - 1)

            if is_base:
                h = 0.0
                curr_elevation = 0.0
            else:
                try:
                    h = float(self.table.item(r, 1).text().strip())
                except ValueError:
                    h = 3.0
                curr_elevation += h

            master_item = self.table.item(r, 3)
            is_master = (master_item.checkState() == Qt.CheckState.Checked) if master_item else True

            story = Story(
                name=name,
                height=h,
                elevation=curr_elevation,
                is_base=is_base,
                is_master=is_master,
            )
            new_stories.append(story)

        self.stories.stories = new_stories
        self.accept()

    def get_story_system(self) -> StorySystem:
        """Return the resulting story system."""
        return self.stories
