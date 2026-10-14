"""
Grid System Dialog — define and edit orthogonal grid systems.

Offers both quick uniform grid generation and custom grid coordinate tables,
mirroring the ETABS Grid System Data dialog.
"""

from __future__ import annotations

import copy
import string
from typing import Optional, List
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QTableWidget,
    QTableWidgetItem, QPushButton, QDialogButtonBox, QLabel,
    QHeaderView, QMessageBox
)

from saengine.core.grids import GridLine, GridSystem


class GridDialog(QDialog):
    """
    Dialog for configuring the structural grid system.
    """

    def __init__(self, current_grids: GridSystem, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Grid System Definition")
        self.resize(600, 480)

        # Working copy of grids
        self.grids: GridSystem = copy.deepcopy(current_grids)

        self._init_ui()
        self._load_custom_tables()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.tab_widget = QTabWidget(self)

        # Tab 1: Custom Grid Coordinates (Default / Direct Edit)
        self.tab_custom = QWidget()
        self._build_custom_tab(self.tab_custom)
        self.tab_widget.addTab(self.tab_custom, "Custom Grid Spacing")

        # Tab 2: Uniform Grid Generation
        self.tab_uniform = QWidget()
        self._build_uniform_tab(self.tab_uniform)
        self.tab_widget.addTab(self.tab_uniform, "Quick Uniform Grid")

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

        box_x = QGroupBox("X Direction (Number & Spacing)")
        form_x = QFormLayout(box_x)
        self.spin_nx = QSpinBox()
        self.spin_nx.setRange(2, 100)
        self.spin_nx.setValue(len(self.grids.x_grids) or 4)
        self.spin_sx = QDoubleSpinBox()
        self.spin_sx.setRange(0.1, 1000.0)
        self.spin_sx.setValue(6.0)
        self.spin_sx.setSuffix(" m")
        form_x.addRow("Number of Grid Lines:", self.spin_nx)
        form_x.addRow("Grid Line Spacing:", self.spin_sx)
        layout.addWidget(box_x)

        box_y = QGroupBox("Y Direction (Number & Spacing)")
        form_y = QFormLayout(box_y)
        self.spin_ny = QSpinBox()
        self.spin_ny.setRange(2, 100)
        self.spin_ny.setValue(len(self.grids.y_grids) or 3)
        self.spin_sy = QDoubleSpinBox()
        self.spin_sy.setRange(0.1, 1000.0)
        self.spin_sy.setValue(6.0)
        self.spin_sy.setSuffix(" m")
        form_y.addRow("Number of Grid Lines:", self.spin_ny)
        form_y.addRow("Grid Line Spacing:", self.spin_sy)
        layout.addWidget(box_y)

        btn_apply_uniform = QPushButton("Generate Uniform Grid")
        btn_apply_uniform.clicked.connect(self._apply_uniform)
        layout.addWidget(btn_apply_uniform)
        layout.addStretch()

    def _build_custom_tab(self, parent: QWidget) -> None:
        layout = QHBoxLayout(parent)

        # X Grid lines table
        group_x = QGroupBox("X Grid Lines (Numbers 1, 2, 3...)")
        box_x = QVBoxLayout(group_x)
        self.table_x = QTableWidget(0, 2)
        self.table_x.setHorizontalHeaderLabels(["Grid ID", "Coordinate (m)"])
        self.table_x.horizontalHeader().setStretchLastSection(True)
        box_x.addWidget(self.table_x)

        btn_bar_x = QHBoxLayout()
        btn_add_x = QPushButton("+ Add")
        btn_add_x.clicked.connect(self._add_x_row)
        btn_del_x = QPushButton("- Delete")
        btn_del_x.clicked.connect(self._delete_x_row)
        btn_bar_x.addWidget(btn_add_x)
        btn_bar_x.addWidget(btn_del_x)
        box_x.addLayout(btn_bar_x)
        layout.addWidget(group_x)

        # Y Grid lines table
        group_y = QGroupBox("Y Grid Lines (Letters A, B, C...)")
        box_y = QVBoxLayout(group_y)
        self.table_y = QTableWidget(0, 2)
        self.table_y.setHorizontalHeaderLabels(["Grid ID", "Coordinate (m)"])
        self.table_y.horizontalHeader().setStretchLastSection(True)
        box_y.addWidget(self.table_y)

        btn_bar_y = QHBoxLayout()
        btn_add_y = QPushButton("+ Add")
        btn_add_y.clicked.connect(self._add_y_row)
        btn_del_y = QPushButton("- Delete")
        btn_del_y.clicked.connect(self._delete_y_row)
        btn_bar_y.addWidget(btn_add_y)
        btn_bar_y.addWidget(btn_del_y)
        box_y.addLayout(btn_bar_y)
        layout.addWidget(group_y)

    def _load_custom_tables(self) -> None:
        """Populate custom grid tables from self.grids."""
        # X grids
        self.table_x.setRowCount(len(self.grids.x_grids))
        for r, gx in enumerate(self.grids.x_grids):
            item_lbl = QTableWidgetItem(gx.label)
            item_pos = QTableWidgetItem(f"{gx.position:.3f}")
            self.table_x.setItem(r, 0, item_lbl)
            self.table_x.setItem(r, 1, item_pos)

        # Y grids
        self.table_y.setRowCount(len(self.grids.y_grids))
        for r, gy in enumerate(self.grids.y_grids):
            item_lbl = QTableWidgetItem(gy.label)
            item_pos = QTableWidgetItem(f"{gy.position:.3f}")
            self.table_y.setItem(r, 0, item_lbl)
            self.table_y.setItem(r, 1, item_pos)

    def _add_x_row(self) -> None:
        r = self.table_x.rowCount()
        last_pos = 0.0
        if r > 0:
            try:
                last_pos = float(self.table_x.item(r - 1, 1).text()) + 6.0
            except (ValueError, AttributeError):
                last_pos = float(r * 6)
        self.table_x.insertRow(r)
        self.table_x.setItem(r, 0, QTableWidgetItem(str(r + 1)))
        self.table_x.setItem(r, 1, QTableWidgetItem(f"{last_pos:.3f}"))

    def _delete_x_row(self) -> None:
        r = self.table_x.currentRow()
        if r >= 0 and self.table_x.rowCount() > 2:
            self.table_x.removeRow(r)

    def _add_y_row(self) -> None:
        r = self.table_y.rowCount()
        last_pos = 0.0
        if r > 0:
            try:
                last_pos = float(self.table_y.item(r - 1, 1).text()) + 6.0
            except (ValueError, AttributeError):
                last_pos = float(r * 6)
        lbl = string.ascii_uppercase[r] if r < 26 else f"A{r - 25}"
        self.table_y.insertRow(r)
        self.table_y.setItem(r, 0, QTableWidgetItem(lbl))
        self.table_y.setItem(r, 1, QTableWidgetItem(f"{last_pos:.3f}"))

    def _delete_y_row(self) -> None:
        r = self.table_y.currentRow()
        if r >= 0 and self.table_y.rowCount() > 2:
            self.table_y.removeRow(r)

    def _apply_uniform(self) -> None:
        nx = self.spin_nx.value()
        ny = self.spin_ny.value()
        sx = self.spin_sx.value()
        sy = self.spin_sy.value()
        self.grids = GridSystem.create_default(n_x=nx, n_y=ny, spacing_x=sx, spacing_y=sy)
        self._load_custom_tables()
        self.tab_widget.setCurrentIndex(0)

    def _on_accept(self) -> None:
        # Save table changes into self.grids
        new_x_grids = []
        for r in range(self.table_x.rowCount()):
            lbl_item = self.table_x.item(r, 0)
            pos_item = self.table_x.item(r, 1)
            lbl = lbl_item.text().strip() if lbl_item else str(r + 1)
            try:
                pos = float(pos_item.text().strip()) if pos_item else 0.0
            except ValueError:
                QMessageBox.warning(self, "Invalid Input", f"Invalid coordinate for X Grid {lbl}")
                return
            new_x_grids.append(GridLine(label=lbl, position=pos))

        new_y_grids = []
        for r in range(self.table_y.rowCount()):
            lbl_item = self.table_y.item(r, 0)
            pos_item = self.table_y.item(r, 1)
            lbl = lbl_item.text().strip() if lbl_item else str(r + 1)
            try:
                pos = float(pos_item.text().strip()) if pos_item else 0.0
            except ValueError:
                QMessageBox.warning(self, "Invalid Input", f"Invalid coordinate for Y Grid {lbl}")
                return
            new_y_grids.append(GridLine(label=lbl, position=pos))

        if len(new_x_grids) < 2 or len(new_y_grids) < 2:
            QMessageBox.warning(self, "Invalid Grid", "A minimum of 2 grid lines in both X and Y directions is required.")
            return

        self.grids.clear()
        self.grids.x_grids = new_x_grids
        self.grids.y_grids = new_y_grids
        self.grids._sort_grids()
        self.accept()

    def get_grid_system(self) -> GridSystem:
        """Return the resulting grid system."""
        return self.grids
