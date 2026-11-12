"""
Ribbon bar — tabbed toolbar inspired by modern CAD/CAE applications.

Provides quick access to modeling, loading, analysis, and design tools
organized into logical tab groups.
"""

from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import (
    QWidget, QTabWidget, QHBoxLayout, QVBoxLayout, QToolButton,
    QLabel, QFrame, QSizePolicy, QButtonGroup,
)


class RibbonButton(QToolButton):
    """A styled ribbon button with icon and text label below."""

    def __init__(self, text: str, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setToolTip(tooltip or text)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setMinimumSize(64, 56)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setIconSize(self.iconSize())


class RibbonSeparator(QFrame):
    """Vertical separator between ribbon groups."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.VLine)
        self.setFrameShadow(QFrame.Shadow.Sunken)
        self.setStyleSheet("color: #353840; margin: 4px 8px;")


class RibbonGroup(QWidget):
    """A labeled group of buttons within a ribbon tab."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._layout.setSpacing(2)

        # Buttons area
        self._buttons_widget = QWidget()
        self._buttons_layout = QHBoxLayout(self._buttons_widget)
        self._buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._buttons_layout.setSpacing(2)
        self._layout.addWidget(self._buttons_widget)

        # Group label
        label = QLabel(title)
        label.setObjectName("subtitleLabel")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(label)

    def add_button(self, button: RibbonButton) -> RibbonButton:
        """Add a button to this group."""
        self._buttons_layout.addWidget(button)
        return button


class RibbonTab(QWidget):
    """A single tab in the ribbon, containing groups of buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 4, 8, 0)
        self._layout.setSpacing(4)
        self._layout.addStretch()

    def add_group(self, title: str) -> RibbonGroup:
        """Add a new button group to this tab."""
        # Insert before the stretch
        stretch_index = self._layout.count() - 1
        group = RibbonGroup(title, self)
        self._layout.insertWidget(stretch_index, group)
        # Add separator after (before stretch)
        sep = RibbonSeparator(self)
        self._layout.insertWidget(stretch_index + 1, sep)
        return group


class RibbonBar(QTabWidget):
    """
    Main ribbon bar widget — a tabbed toolbar at the top of the window.

    Signals:
        action_triggered(str): Emitted with the action name when a button is clicked.
    """

    action_triggered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(110)
        self.setDocumentMode(True)

        self._build_tabs()

    def _build_tabs(self) -> None:
        """Create all ribbon tabs and their button groups."""
        self._build_home_tab()
        self._build_model_tab()
        self._build_loads_tab()
        self._build_analysis_tab()
        self._build_design_tab()
        self._build_view_tab()

    def _create_button(self, text: str, action_name: str,
                       tooltip: str = "") -> RibbonButton:
        """Create a ribbon button connected to the action signal."""
        btn = RibbonButton(text, tooltip)
        btn.clicked.connect(lambda: self.action_triggered.emit(action_name))
        return btn

    def _build_home_tab(self) -> None:
        tab = RibbonTab()
        self.addTab(tab, "Home")

        # File group
        file_group = tab.add_group("File")
        file_group.add_button(self._create_button("New", "file.new", "New Project (Ctrl+N)"))
        file_group.add_button(self._create_button("Open", "file.open", "Open Project (Ctrl+O)"))
        file_group.add_button(self._create_button("Save", "file.save", "Save Project (Ctrl+S)"))

        # Edit group
        edit_group = tab.add_group("Edit")
        self._undo_btn = self._create_button("Undo", "edit.undo", "Undo (Ctrl+Z)")
        self._redo_btn = self._create_button("Redo", "edit.redo", "Redo (Ctrl+Y)")
        edit_group.add_button(self._undo_btn)
        edit_group.add_button(self._redo_btn)

        # Selection group
        sel_group = tab.add_group("Selection")
        sel_group.add_button(self._create_button("Select", "select.pointer", "Select Objects"))
        sel_group.add_button(self._create_button("Select All", "select.all", "Select All (Ctrl+A)"))

        # Import group
        imp_group = tab.add_group("Import")
        imp_group.add_button(self._create_button("JSON", "import.json", "Import JSON Data"))
        imp_group.add_button(self._create_button("CSV", "import.csv", "Import CSV Data"))

    def _build_model_tab(self) -> None:
        tab = RibbonTab()
        self.addTab(tab, "Model")

        # Grid group
        grid_group = tab.add_group("Grid & Story")
        grid_group.add_button(self._create_button("Grids", "model.grids", "Edit Grid System"))
        grid_group.add_button(self._create_button("Stories", "model.stories", "Edit Story Levels"))

        # Elements group
        elem_group = tab.add_group("Elements")
        elem_group.add_button(self._create_button("Column", "draw.column", "Draw Column"))
        elem_group.add_button(self._create_button("Beam", "draw.beam", "Draw Beam"))
        elem_group.add_button(self._create_button("Wall", "draw.wall", "Draw Wall"))
        elem_group.add_button(self._create_button("Slab", "draw.slab", "Draw Slab"))
        elem_group.add_button(self._create_button("Brace", "draw.brace", "Draw Brace"))

        # Properties group
        prop_group = tab.add_group("Properties")
        prop_group.add_button(self._create_button("Materials", "prop.materials", "Material Library"))
        prop_group.add_button(self._create_button("Sections", "prop.sections", "Section Library"))

    def _build_loads_tab(self) -> None:
        tab = RibbonTab()
        self.addTab(tab, "Loads")

        # Load Cases group
        case_group = tab.add_group("Load Cases")
        case_group.add_button(self._create_button("Cases", "loads.cases", "Manage Load Cases"))
        case_group.add_button(self._create_button("Combos", "loads.combos", "Load Combinations"))

        # Apply Loads group
        apply_group = tab.add_group("Apply Loads")
        apply_group.add_button(self._create_button("Point", "loads.point", "Point Load"))
        apply_group.add_button(self._create_button("Line", "loads.line", "Distributed Load"))
        apply_group.add_button(self._create_button("Area", "loads.area", "Area Load"))

        # Auto Loads group
        auto_group = tab.add_group("Auto Lateral")
        auto_group.add_button(self._create_button("Seismic", "loads.seismic", "Auto Seismic Load"))
        auto_group.add_button(self._create_button("Wind", "loads.wind", "Auto Wind Load"))

    def _build_analysis_tab(self) -> None:
        tab = RibbonTab()
        self.addTab(tab, "Analysis")

        # Run group
        run_group = tab.add_group("Run")
        run_group.add_button(self._create_button("Run ▶", "analysis.run", "Run Analysis"))
        run_group.add_button(self._create_button("Options", "analysis.options", "Analysis Options"))

        # Type group
        type_group = tab.add_group("Analysis Type")
        type_group.add_button(self._create_button("Static", "analysis.static", "Static Analysis"))
        type_group.add_button(self._create_button("Modal", "analysis.modal", "Modal Analysis"))
        type_group.add_button(self._create_button("Spectrum", "analysis.spectrum", "Response Spectrum"))
        type_group.add_button(self._create_button("History", "analysis.history", "Time History"))

        # Results group
        res_group = tab.add_group("Results")
        res_group.add_button(self._create_button("Deformed", "results.deformed", "Deformed Shape"))
        res_group.add_button(self._create_button("Forces", "results.forces", "Force Diagrams"))
        res_group.add_button(self._create_button("Tables", "results.tables", "Result Tables"))

    def _build_design_tab(self) -> None:
        tab = RibbonTab()
        self.addTab(tab, "Design")

        # Design group
        design_group = tab.add_group("Code Check")
        design_group.add_button(self._create_button("Concrete", "design.concrete", "Concrete Design"))
        design_group.add_button(self._create_button("Steel", "design.steel", "Steel Design"))
        design_group.add_button(self._create_button("Check All", "design.check_all", "Check All Members"))

        # Report group
        report_group = tab.add_group("Reports")
        report_group.add_button(self._create_button("Report", "report.generate", "Generate Report"))
        report_group.add_button(self._create_button("Export", "report.export", "Export Results"))

    def _build_view_tab(self) -> None:
        tab = RibbonTab()
        self.addTab(tab, "View")

        # Camera group
        cam_group = tab.add_group("Camera")
        cam_group.add_button(self._create_button("3D", "view.3d", "3D Perspective"))
        cam_group.add_button(self._create_button("XY", "view.xy", "Plan View (Top)"))
        cam_group.add_button(self._create_button("XZ", "view.xz", "Elevation X"))
        cam_group.add_button(self._create_button("YZ", "view.yz", "Elevation Y"))
        cam_group.add_button(self._create_button("Fit All", "view.fit", "Fit All (F)"))

        # Display group
        disp_group = tab.add_group("Display")
        disp_group.add_button(self._create_button("Wireframe", "display.wireframe", "Wireframe Mode"))
        disp_group.add_button(self._create_button("Extrude", "display.extrude", "Extruded View"))
        disp_group.add_button(self._create_button("Labels", "display.labels", "Show Labels"))

        # Theme group
        theme_group = tab.add_group("Theme")
        theme_group.add_button(self._create_button("Dark", "theme.dark", "Dark Mode"))
        theme_group.add_button(self._create_button("Light", "theme.light", "Light Mode"))

    def update_undo_redo(self, can_undo: bool, can_redo: bool,
                          undo_text: str = "", redo_text: str = "") -> None:
        """Update undo/redo button states."""
        self._undo_btn.setEnabled(can_undo)
        self._redo_btn.setEnabled(can_redo)
        if undo_text:
            self._undo_btn.setToolTip(undo_text)
        if redo_text:
            self._redo_btn.setToolTip(redo_text)
