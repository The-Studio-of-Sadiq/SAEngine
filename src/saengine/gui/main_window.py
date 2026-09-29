"""
Main Application Window for SAEngine.

Integrates the Ribbon Bar, 3D Viewport, Model Explorer, Property Panel,
Output Console, and complete Code Studio (Code Editor, File Explorer,
Terminal & REPL, Git Version Control) into a dockable desktop CAE/CAD workspace.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QAction, QIcon, QKeySequence, QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow, QDockWidget, QWidget, QVBoxLayout,
    QFileDialog, QMessageBox, QLabel, QStatusBar, QSplitter
)

from saengine.core.project import Project
from saengine.commands.command_manager import CommandManager
from saengine.commands.model_commands import SetGridSystemCommand, SetStorySystemCommand
from saengine.io.project_io import ProjectIO
from saengine.gui.ribbon.ribbon_bar import RibbonBar
from saengine.gui.viewport.viewport_widget import ViewportWidget
from saengine.gui.panels.model_explorer import ModelExplorerPanel
from saengine.gui.panels.property_panel import PropertyPanel
from saengine.gui.panels.output_panel import OutputPanel
from saengine.gui.dialogs.grid_dialog import GridDialog
from saengine.gui.dialogs.story_dialog import StoryDialog

from saengine.gui.editor.code_editor import EditorTabWidget
from saengine.gui.editor.file_explorer import FileExplorerPanel
from saengine.gui.editor.terminal import TerminalWidget
from saengine.gui.editor.git_panel import GitPanel
from saengine.gui.editor.script_runner import ScriptRunner


class MainWindow(QMainWindow):
    """
    SAEngine primary application window.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.setWindowTitle("SAEngine — Structure Analysis Engine")
        self.resize(1440, 920)

        # Core state
        self.project: Project = Project.create_new()
        self.cmd_manager: CommandManager = CommandManager(parent=self)
        self.project_io: ProjectIO = ProjectIO()
        self.script_runner: ScriptRunner = ScriptRunner(self)

        # Build UI
        self._init_ui()
        self._connect_signals()

        # Initial model render & refresh
        self.refresh_all()
        self.output_panel.append_message("SAEngine initialized successfully. Ready.", level="success")
        self.output_panel.append_message("Code Studio ready: Code Editor, Terminal, File Explorer, and Git active.", level="info")

    def _init_ui(self) -> None:
        """Construct the complete window layout and docks."""
        # 1. Central Widget: Splitter with 3D Viewport & Code Editor
        self.central_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.central_splitter.setObjectName("central_splitter")

        self.viewport = ViewportWidget(self)
        self.editor_tab = EditorTabWidget(self)

        self.central_splitter.addWidget(self.viewport)
        self.central_splitter.addWidget(self.editor_tab)
        # Default view: Hybrid split view (3D model + code editor)
        self.central_splitter.setSizes([740, 700])
        self.setCentralWidget(self.central_splitter)

        # 2. Ribbon Bar (top tabbed toolbar)
        self.ribbon_bar = RibbonBar(self)
        self.addToolBarBreak()
        # Container for ribbon
        ribbon_container = QWidget(self)
        ribbon_layout = QVBoxLayout(ribbon_container)
        ribbon_layout.setContentsMargins(0, 0, 0, 0)
        ribbon_layout.setSpacing(0)
        ribbon_layout.addWidget(self.ribbon_bar)
        self.setMenuWidget(ribbon_container)

        # 3. Dock Widgets
        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks |
            QMainWindow.DockOption.AllowTabbedDocks |
            QMainWindow.DockOption.AllowNestedDocks
        )

        # Left Docks:
        # 1. Model Explorer (Structural model tree)
        self.dock_explorer = QDockWidget("Model Explorer", self)
        self.dock_explorer.setObjectName("dock_explorer")
        self.explorer_panel = ModelExplorerPanel(self.dock_explorer)
        self.dock_explorer.setWidget(self.explorer_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_explorer)

        # 2. File Explorer (Project directory tree)
        self.dock_files = QDockWidget("File Explorer", self)
        self.dock_files.setObjectName("dock_files")
        self.file_explorer = FileExplorerPanel(root_path=Path.cwd(), parent=self.dock_files)
        self.dock_files.setWidget(self.file_explorer)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_files)

        # 3. Source Control (Git)
        self.dock_git = QDockWidget("Source Control (Git)", self)
        self.dock_git.setObjectName("dock_git")
        self.git_panel = GitPanel(repo_dir=Path.cwd(), parent=self.dock_git)
        self.dock_git.setWidget(self.git_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_git)

        # Tabify left docks
        self.tabifyDockWidget(self.dock_explorer, self.dock_files)
        self.tabifyDockWidget(self.dock_files, self.dock_git)
        self.dock_explorer.raise_()

        # Right Dock: Property Panel
        self.dock_properties = QDockWidget("Properties", self)
        self.dock_properties.setObjectName("dock_properties")
        self.property_panel = PropertyPanel(self.dock_properties)
        self.dock_properties.setWidget(self.property_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_properties)

        # Bottom Docks:
        # 1. Output Console
        self.dock_output = QDockWidget("Log & Messages", self)
        self.dock_output.setObjectName("dock_output")
        self.output_panel = OutputPanel(self.dock_output)
        self.dock_output.setWidget(self.output_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_output)

        # 2. Terminal & Python REPL
        self.dock_terminal = QDockWidget("Terminal & Shell", self)
        self.dock_terminal.setObjectName("dock_terminal")
        self.terminal_widget = TerminalWidget(
            cwd=Path.cwd(),
            env_context={
                "project": self.project,
                "cmd_manager": self.cmd_manager,
                "app": self,
            },
            parent=self.dock_terminal
        )
        self.dock_terminal.setWidget(self.terminal_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_terminal)

        # Tabify bottom docks
        self.tabifyDockWidget(self.dock_output, self.dock_terminal)
        self.dock_output.raise_()

        # Set dock sizes
        self.resizeDocks(
            [self.dock_explorer, self.dock_files, self.dock_git, self.dock_properties],
            [270, 270, 270, 280],
            Qt.Orientation.Horizontal
        )
        self.resizeDocks(
            [self.dock_output, self.dock_terminal],
            [180, 180],
            Qt.Orientation.Vertical
        )

        # 4. Status Bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)

        self.status_label = QLabel("Ready")
        self.status_bar.addWidget(self.status_label, 1)

        self.git_indicator = QLabel("Git: main")
        self.git_indicator.setStyleSheet("color: #FFCB6B; padding: 0 8px; font-weight: bold;")
        self.status_bar.addPermanentWidget(self.git_indicator)

        self.editor_pos_indicator = QLabel("Ln 1, Col 1")
        self.editor_pos_indicator.setStyleSheet("color: #9aa0a6; padding: 0 8px;")
        self.status_bar.addPermanentWidget(self.editor_pos_indicator)

        self.units_indicator = QLabel(f"Units: {self.project.units.active_system.display_name}")
        self.units_indicator.setStyleSheet("color: #4FC3F7; padding: 0 8px; font-weight: bold;")
        self.status_bar.addPermanentWidget(self.units_indicator)

        self.story_indicator = QLabel("Active: All Stories")
        self.story_indicator.setStyleSheet("color: #9aa0a6; padding: 0 8px;")
        self.status_bar.addPermanentWidget(self.story_indicator)

        self.engine_indicator = QLabel("Engine: OpenSeesPy")
        self.engine_indicator.setStyleSheet("color: #81C784; padding: 0 8px;")
        self.status_bar.addPermanentWidget(self.engine_indicator)

        # 5. Global Keyboard Shortcuts
        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        """Setup keyboard shortcuts for quick access."""
        # File
        self._action_new = QAction(self)
        self._action_new.setShortcut(QKeySequence.StandardKey.New)
        self._action_new.triggered.connect(self.new_project)
        self.addAction(self._action_new)

        self._action_open = QAction(self)
        self._action_open.setShortcut(QKeySequence.StandardKey.Open)
        self._action_open.triggered.connect(self.open_project)
        self.addAction(self._action_open)

        self._action_save = QAction(self)
        self._action_save.setShortcut(QKeySequence.StandardKey.Save)
        self._action_save.triggered.connect(self.save_project)
        self.addAction(self._action_save)

        # Edit
        self._action_undo = QAction(self)
        self._action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self._action_undo.triggered.connect(self.undo)
        self.addAction(self._action_undo)

        self._action_redo = QAction(self)
        self._action_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self._action_redo.triggered.connect(self.redo)
        self.addAction(self._action_redo)

        # View Fit
        self._action_fit = QAction(self)
        self._action_fit.setShortcut(QKeySequence(Qt.Key.Key_F))
        self._action_fit.triggered.connect(self.viewport.fit_all)
        self.addAction(self._action_fit)

        # Code Studio Shortcuts
        # F5 - Run Current Script
        self._action_run_script = QAction(self)
        self._action_run_script.setShortcut(QKeySequence(Qt.Key.Key_F5))
        self._action_run_script.triggered.connect(lambda: self.run_script())
        self.addAction(self._action_run_script)

        # Ctrl + ` : Toggle Terminal
        self._action_toggle_terminal = QAction(self)
        self._action_toggle_terminal.setShortcut(QKeySequence("Ctrl+`"))
        self._action_toggle_terminal.triggered.connect(self.toggle_terminal)
        self.addAction(self._action_toggle_terminal)

        # Ctrl + Shift + E : Toggle File Explorer
        self._action_toggle_files = QAction(self)
        self._action_toggle_files.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self._action_toggle_files.triggered.connect(self.toggle_file_explorer)
        self.addAction(self._action_toggle_files)

        # Ctrl + Shift + G : Toggle Git
        self._action_toggle_git = QAction(self)
        self._action_toggle_git.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self._action_toggle_git.triggered.connect(self.toggle_git)
        self.addAction(self._action_toggle_git)

    def _connect_signals(self) -> None:
        """Wire all signals between components."""
        # Ribbon actions
        self.ribbon_bar.action_triggered.connect(self._handle_ribbon_action)

        # Command stack
        self.cmd_manager.stack_changed.connect(self._on_stack_changed)
        self.cmd_manager.command_executed.connect(self._on_command_executed)

        # Model Explorer
        self.explorer_panel.selection_changed.connect(self._on_explorer_selection)
        self.explorer_panel.edit_requested.connect(self._handle_edit_request)

        # Code Studio: Editor signals
        self.editor_tab.run_script_requested.connect(self.run_script)
        self.editor_tab.tabs.currentChanged.connect(self._on_editor_tab_changed)

        # Code Studio: File Explorer signals
        self.file_explorer.file_double_clicked.connect(self.editor_tab.open_file)
        self.file_explorer.open_in_terminal_requested.connect(self.terminal_widget.set_cwd)

        # Code Studio: Git signals
        self.git_panel.status_updated.connect(self._on_git_status_updated)
        self.git_panel.file_selected_for_diff.connect(lambda f: self.dock_git.raise_())

        # Script Runner signals
        self.script_runner.output_received.connect(self._on_script_output)
        self.script_runner.model_modified.connect(self.refresh_all)

    # ── Action Dispatcher ───────────────────────────────────────

    def _handle_ribbon_action(self, action: str) -> None:
        """Route action strings from ribbon buttons."""
        # File
        if action == "file.new":
            self.new_project()
        elif action == "file.open":
            self.open_project()
        elif action == "file.save":
            self.save_project()

        # Edit
        elif action == "edit.undo":
            self.undo()
        elif action == "edit.redo":
            self.redo()

        # Model
        elif action == "model.grids":
            self.open_grid_dialog()
        elif action == "model.stories":
            self.open_story_dialog()

        # View
        elif action == "view.3d":
            self.viewport.set_view_3d()
        elif action == "view.xy":
            self.viewport.set_view_xy()
        elif action == "view.xz":
            self.viewport.set_view_xz()
        elif action == "view.yz":
            self.viewport.set_view_yz()
        elif action == "view.fit":
            self.viewport.fit_all()

        # Theme
        elif action == "theme.dark":
            self.apply_theme("dark")
        elif action == "theme.light":
            self.apply_theme("light")

        # Code Studio Actions
        elif action == "script.new":
            self.editor_tab.new_file()
            self.set_layout_mode("split")
        elif action == "script.open":
            self.editor_tab.open_file_dialog()
        elif action == "script.save":
            self.editor_tab.save_current_file()
        elif action == "script.run":
            self.run_script()
        elif action == "script.stop":
            self.script_runner.stop()

        # Developer Tools
        elif action == "tools.files":
            self.toggle_file_explorer()
        elif action == "tools.terminal":
            self.toggle_terminal()
        elif action == "tools.git":
            self.toggle_git()
        elif action == "tools.repl":
            self.dock_terminal.show()
            self.dock_terminal.raise_()
            self.terminal_widget.tabs.setCurrentIndex(1)  # Python REPL tab

        # Git Quick Actions
        elif action == "git.commit":
            self.dock_git.show()
            self.dock_git.raise_()
            self.git_panel.edit_commit_msg.setFocus()
        elif action == "git.push":
            self.git_panel.git_push()
        elif action == "git.pull":
            self.git_panel.git_pull()

        # Workspace Layout Presets
        elif action == "layout.cae":
            self.set_layout_mode("cae")
        elif action == "layout.split":
            self.set_layout_mode("split")
        elif action == "layout.code":
            self.set_layout_mode("code")

        # Fallback / Stubs for future phases
        elif action.startswith("draw."):
            elem = action.split(".")[1].capitalize()
            self.output_panel.append_message(f"Drawing tool '{elem}' activated (Phase 2 feature).", level="info")
        elif action.startswith("analysis."):
            self.output_panel.append_message(f"Analysis option '{action}' selected (Phase 4 solver engine).", level="info")
        elif action.startswith("design."):
            self.output_panel.append_message(f"Design code check '{action}' selected (Phase 5 module).", level="info")
        elif action.startswith("loads."):
            self.output_panel.append_message(f"Load definition '{action}' selected (Phase 3 feature).", level="info")
        elif action.startswith("import."):
            self._handle_import(action)

    def _handle_edit_request(self, target: str) -> None:
        if target == "grids":
            self.open_grid_dialog()
        elif target == "stories":
            self.open_story_dialog()

    def _handle_import(self, action: str) -> None:
        ext = "JSON Files (*.json)" if "json" in action else "CSV Files (*.csv)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Import Data", "", ext)
        if file_path:
            self.output_panel.append_message(f"Imported configuration from {file_path}", level="success")

    # ── Code Studio Operations ──────────────────────────────────

    def run_script(self, code: Optional[str] = None, file_path: Optional[Path] = None) -> None:
        """Execute active script in the live engine context."""
        if code is None:
            ed = self.editor_tab.current_editor()
            if ed:
                code = ed.toPlainText()
                file_path = ed.file_path
            else:
                self.output_panel.append_message("No active script to execute.", level="warning")
                return

        context = {
            "app": self,
            "project": self.project,
            "cmd_manager": self.cmd_manager,
            "viewport": self.viewport,
            "output": self.output_panel,
            "terminal": self.terminal_widget,
        }

        name = file_path.name if file_path else "active script"
        self.output_panel.append_message(f"Running '{name}' in SAEngine environment...", level="cmd")
        self.script_runner.execute_in_engine(code, context, file_path)

    def _on_script_output(self, text: str, level: str) -> None:
        self.output_panel.append_message(text.rstrip(), level=level)
        self.terminal_widget.shell.append_output(text)

    def _on_git_status_updated(self, branch: str) -> None:
        self.git_indicator.setText(f"Git: {branch}")

    def _on_editor_tab_changed(self, index: int) -> None:
        ed = self.editor_tab.current_editor()
        if ed:
            c = ed.textCursor()
            self.editor_pos_indicator.setText(f"Ln {c.blockNumber()+1}, Col {c.positionInBlock()+1}")

    def toggle_file_explorer(self) -> None:
        if self.dock_files.isVisible():
            self.dock_files.hide()
        else:
            self.dock_files.show()
            self.dock_files.raise_()

    def toggle_terminal(self) -> None:
        if self.dock_terminal.isVisible():
            self.dock_terminal.hide()
        else:
            self.dock_terminal.show()
            self.dock_terminal.raise_()

    def toggle_git(self) -> None:
        if self.dock_git.isVisible():
            self.dock_git.hide()
        else:
            self.dock_git.show()
            self.dock_git.raise_()

    def set_layout_mode(self, mode: str) -> None:
        """Switch between CAE View, Split View, and Code IDE View."""
        if mode == "cae":
            self.viewport.show()
            self.editor_tab.hide()
            self.dock_explorer.show()
            self.dock_explorer.raise_()
            self.dock_properties.show()
            self.dock_output.show()
            self.dock_output.raise_()
            self.output_panel.append_message("Layout: 3D Structural Modeling View (CAE)", level="info")
        elif mode == "split":
            self.viewport.show()
            self.editor_tab.show()
            self.dock_files.show()
            self.dock_files.raise_()
            self.dock_terminal.show()
            self.dock_terminal.raise_()
            self.central_splitter.setSizes([720, 720])
            self.output_panel.append_message("Layout: Hybrid Split View (3D Model + Code Studio)", level="info")
        elif mode == "code":
            self.viewport.hide()
            self.editor_tab.show()
            self.dock_files.show()
            self.dock_files.raise_()
            self.dock_git.show()
            self.dock_terminal.show()
            self.dock_terminal.raise_()
            self.output_panel.append_message("Layout: Code Studio IDE View", level="info")

    # ── Project Operations ──────────────────────────────────────

    def new_project(self) -> None:
        """Create a fresh structural project."""
        if not self._maybe_save():
            return

        self.project = Project.create_new()
        self.cmd_manager.clear()
        self.terminal_widget.update_context({"project": self.project, "cmd_manager": self.cmd_manager})
        self.refresh_all()
        self.output_panel.append_message("Created new project.", level="info")

    def open_project(self) -> None:
        """Open an existing .saengine project file."""
        if not self._maybe_save():
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "SAEngine Project (*.saengine);;All Files (*.*)"
        )
        if not file_path:
            return

        project = self.project_io.load_project(file_path)
        if project:
            self.project = project
            self.cmd_manager.clear()
            self.terminal_widget.update_context({"project": self.project, "cmd_manager": self.cmd_manager})
            self.refresh_all()
            self.output_panel.append_message(f"Opened project: {file_path}", level="success")
        else:
            QMessageBox.critical(self, "Error", f"Failed to load project from {file_path}")

    def save_project(self) -> bool:
        """Save the project. Prompts for location if never saved before."""
        if self.project.file_path is None:
            return self.save_project_as()

        success = self.project_io.save_project(self.project, self.project.file_path)
        if success:
            self.project.mark_clean()
            self._update_title()
            self.output_panel.append_message(f"Project saved: {self.project.file_path}", level="success")
            self.git_panel.refresh()
            return True
        else:
            QMessageBox.critical(self, "Error", "Failed to save project file.")
            return False

    def save_project_as(self) -> bool:
        """Prompt user for a destination file path and save."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", f"{self.project.settings.project_name}.saengine",
            "SAEngine Project (*.saengine)"
        )
        if not file_path:
            return False

        path = Path(file_path)
        if not path.suffix:
            path = path.with_suffix(".saengine")

        success = self.project_io.save_project(self.project, path)
        if success:
            self.project.file_path = path
            self.project.settings.project_name = path.stem
            self.project.mark_clean()
            self._update_title()
            self.output_panel.append_message(f"Project saved as: {path}", level="success")
            self.git_panel.refresh()
            return True
        else:
            QMessageBox.critical(self, "Error", "Failed to save project file.")
            return False

    def _maybe_save(self) -> bool:
        """Check for unsaved changes before destructive actions."""
        if not self.project.is_dirty:
            return True

        ret = QMessageBox.warning(
            self, "Unsaved Changes",
            f"The project '{self.project.display_name}' has unsaved changes.\nDo you want to save them?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel
        )
        if ret == QMessageBox.StandardButton.Save:
            return self.save_project()
        elif ret == QMessageBox.StandardButton.Cancel:
            return False
        return True

    # ── Undo / Redo & Commands ──────────────────────────────────

    def undo(self) -> None:
        cmd = self.cmd_manager.undo()
        if cmd:
            self.project.mark_dirty()
            self.refresh_all()

    def redo(self) -> None:
        cmd = self.cmd_manager.redo()
        if cmd:
            self.project.mark_dirty()
            self.refresh_all()

    def _on_stack_changed(self) -> None:
        self.ribbon_bar.update_undo_redo(
            self.cmd_manager.can_undo,
            self.cmd_manager.can_redo,
            self.cmd_manager.undo_description,
            self.cmd_manager.redo_description
        )
        self._update_title()

    def _on_command_executed(self, description: str) -> None:
        self.status_label.setText(description)
        self.output_panel.append_message(description, level="cmd")

    # ── Dialog Handlers ─────────────────────────────────────────

    def open_grid_dialog(self) -> None:
        """Open the Grid System Definition dialog."""
        dlg = GridDialog(self.project.grids, parent=self)
        if dlg.exec() == GridDialog.DialogCode.Accepted:
            new_grids = dlg.get_grid_system()
            cmd = SetGridSystemCommand(self.project.grids, new_grids)
            self.cmd_manager.execute(cmd)
            self.project.mark_dirty()
            self.refresh_all()

    def open_story_dialog(self) -> None:
        """Open the Story Data Definition dialog."""
        dlg = StoryDialog(self.project.stories, parent=self)
        if dlg.exec() == StoryDialog.DialogCode.Accepted:
            new_stories = dlg.get_story_system()
            cmd = SetStorySystemCommand(self.project.stories, new_stories)
            self.cmd_manager.execute(cmd)
            self.project.mark_dirty()
            self.refresh_all()

    # ── UI Refresh & Themes ─────────────────────────────────────

    def refresh_all(self) -> None:
        """Full refresh of viewport, panels, and title."""
        self.viewport.render_grids(self.project.grids, self.project.stories)
        self.explorer_panel.set_project(self.project)
        self.property_panel.show_object("project", self.project)
        self.terminal_widget.update_context({"project": self.project, "cmd_manager": self.cmd_manager})
        self.units_indicator.setText(f"Units: {self.project.units.active_system.display_name}")
        self._update_title()

    def _on_explorer_selection(self, node_type: str, obj: object) -> None:
        self.property_panel.show_object(node_type, obj)

    def _update_title(self) -> None:
        self.setWindowTitle(f"{self.project.display_name} — SAEngine")

    def apply_theme(self, theme_name: str) -> None:
        """Switch between dark and light themes."""
        themes_dir = Path(__file__).parent / "themes"
        theme_file = themes_dir / f"{theme_name}.qss"
        if theme_file.exists():
            with open(theme_file, "r", encoding="utf-8") as f:
                stylesheet = f.read()
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                app.setStyleSheet(stylesheet)
            self.output_panel.append_message(f"Applied {theme_name.capitalize()} theme.", level="info")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close event with dirty check."""
        if self._maybe_save():
            self.viewport.close()
            event.accept()
        else:
            event.ignore()
