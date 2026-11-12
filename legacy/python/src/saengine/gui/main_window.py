"""
Main Application Window for SAEngine.

The main window uses a VS Code-centric layout:
- **Central widget**: Embedded VS Code (full IDE via ``code serve-web``)
- **Right dock**: 3D Structural Viewport (PyVista)
- **Bottom dock**: SAEngine Log & Messages

VS Code provides: file explorer, git, terminal, extensions, code editing.
SAEngine provides: 3D viewport, structural analysis, design checking.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence, QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow, QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QMessageBox, QLabel, QStatusBar, QToolBar,
    QSplitter, QPushButton, QSizePolicy
)

from saengine.core.project import Project
from saengine.commands.command_manager import CommandManager
from saengine.commands.model_commands import SetGridSystemCommand, SetStorySystemCommand
from saengine.io.project_io import ProjectIO
from saengine.gui.editor.vscode_server import VSCodeServerManager
from saengine.gui.editor.vscode_widget import VSCodeWebView
from saengine.gui.viewport.viewport_widget import ViewportWidget
from saengine.gui.panels.output_panel import OutputPanel
from saengine.gui.dialogs.grid_dialog import GridDialog
from saengine.gui.dialogs.story_dialog import StoryDialog


class MainWindow(QMainWindow):
    """
    SAEngine primary application window.

    Embeds VS Code as the main IDE workspace with the 3D structural
    viewport as a dockable panel.
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)

        self.setWindowTitle("SAEngine — Structure Analysis Engine")
        self.resize(1600, 1000)

        # Core state
        self.project: Project = Project.create_new()
        self.cmd_manager: CommandManager = CommandManager(parent=self)
        self.project_io: ProjectIO = ProjectIO()

        # VS Code server
        self._vscode_server = VSCodeServerManager(parent=self)

        # Build UI
        self._init_ui()
        self._connect_signals()
        self._setup_shortcuts()

        # Start VS Code server after a brief delay to let Qt settle
        QTimer.singleShot(500, self._start_vscode)

        # Initial model render
        self.refresh_viewport()
        self.output_panel.append_message(
            "SAEngine initialized. Starting VS Code environment...", level="success"
        )

    def _init_ui(self) -> None:
        """Construct the VS Code-centric window layout."""
        # ── Central Widget: VS Code Web View ────────────────────
        self.vscode_view = VSCodeWebView(self)
        self.setCentralWidget(self.vscode_view)

        # ── Dock Options ────────────────────────────────────────
        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks |
            QMainWindow.DockOption.AllowTabbedDocks |
            QMainWindow.DockOption.AllowNestedDocks
        )

        # ── Right Dock: 3D Structural Viewport ─────────────────
        self.dock_viewport = QDockWidget("3D Viewport", self)
        self.dock_viewport.setObjectName("dock_viewport")
        self.dock_viewport.setMinimumWidth(400)

        viewport_container = QWidget()
        viewport_layout = QVBoxLayout(viewport_container)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        viewport_layout.setSpacing(0)

        # Viewport toolbar
        vp_toolbar = QWidget()
        vp_toolbar.setFixedHeight(36)
        vp_toolbar.setStyleSheet("""
            QWidget {
                background-color: #252526;
                border-bottom: 1px solid #3c3c3c;
            }
            QPushButton {
                background: transparent;
                color: #cccccc;
                border: none;
                padding: 4px 10px;
                font-size: 11px;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover {
                background-color: #3c3c3c;
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: #4c4c4c;
            }
        """)
        vp_tb_layout = QHBoxLayout(vp_toolbar)
        vp_tb_layout.setContentsMargins(4, 0, 4, 0)
        vp_tb_layout.setSpacing(2)

        for label, action in [
            ("3D", "view.3d"), ("XY", "view.xy"),
            ("XZ", "view.xz"), ("YZ", "view.yz"),
            ("Fit", "view.fit"),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda checked, a=action: self._handle_view_action(a))
            vp_tb_layout.addWidget(btn)

        vp_tb_layout.addStretch()

        # Grid/Story buttons
        btn_grids = QPushButton("⊞ Grids")
        btn_grids.setFixedHeight(28)
        btn_grids.clicked.connect(self.open_grid_dialog)
        vp_tb_layout.addWidget(btn_grids)

        btn_stories = QPushButton("⏛ Stories")
        btn_stories.setFixedHeight(28)
        btn_stories.clicked.connect(self.open_story_dialog)
        vp_tb_layout.addWidget(btn_stories)

        viewport_layout.addWidget(vp_toolbar)

        # The actual 3D viewport
        self.viewport = ViewportWidget(viewport_container)
        viewport_layout.addWidget(self.viewport)

        self.dock_viewport.setWidget(viewport_container)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_viewport)

        # ── Bottom Dock: Output Console ─────────────────────────
        self.dock_output = QDockWidget("Log & Messages", self)
        self.dock_output.setObjectName("dock_output")
        self.output_panel = OutputPanel(self.dock_output)
        self.dock_output.setWidget(self.output_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_output)

        # ── Set Dock Sizes ──────────────────────────────────────
        self.resizeDocks(
            [self.dock_viewport],
            [500],
            Qt.Orientation.Horizontal
        )
        self.resizeDocks(
            [self.dock_output],
            [140],
            Qt.Orientation.Vertical
        )

        # ── Status Bar ──────────────────────────────────────────
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)

        self.status_label = QLabel("Ready")
        self.status_bar.addWidget(self.status_label, 1)

        self.units_indicator = QLabel(f"Units: {self.project.units.active_system.display_name}")
        self.units_indicator.setStyleSheet("color: #4FC3F7; padding: 0 8px; font-weight: bold;")
        self.status_bar.addPermanentWidget(self.units_indicator)

        self.vscode_indicator = QLabel("VS Code: Starting...")
        self.vscode_indicator.setStyleSheet("color: #FFA726; padding: 0 8px;")
        self.status_bar.addPermanentWidget(self.vscode_indicator)

        self.engine_indicator = QLabel("Engine: OpenSeesPy")
        self.engine_indicator.setStyleSheet("color: #81C784; padding: 0 8px;")
        self.status_bar.addPermanentWidget(self.engine_indicator)

    def _setup_shortcuts(self) -> None:
        """Setup keyboard shortcuts that don't conflict with VS Code."""
        # Most shortcuts are handled by VS Code itself.
        # Only SAEngine-specific shortcuts are bound here.
        pass

    def _connect_signals(self) -> None:
        """Wire all signals between components."""
        # VS Code server signals
        self._vscode_server.ready.connect(self._on_vscode_ready)
        self._vscode_server.error.connect(self._on_vscode_error)
        self._vscode_server.log_message.connect(self._on_vscode_log)

        # VS Code widget signals
        self.vscode_view.editor_loaded.connect(self._on_editor_loaded)
        self.vscode_view.editor_error.connect(self._on_editor_error)

        # Command stack
        self.cmd_manager.stack_changed.connect(self._on_stack_changed)
        self.cmd_manager.command_executed.connect(self._on_command_executed)

    # ── VS Code Lifecycle ───────────────────────────────────────

    def _start_vscode(self) -> None:
        """Start the VS Code web server with the current project folder."""
        workspace = str(Path.cwd())
        self._vscode_server.start(workspace_folder=workspace)

    def _on_vscode_ready(self, url: str) -> None:
        """Handle VS Code server becoming ready."""
        self.vscode_view.load_url(url)
        self.vscode_indicator.setText(f"VS Code: Ready")
        self.vscode_indicator.setStyleSheet("color: #81C784; padding: 0 8px;")
        self.output_panel.append_message(
            f"VS Code web server started at {url}", level="success"
        )

    def _on_vscode_error(self, message: str) -> None:
        """Handle VS Code server errors."""
        self.vscode_indicator.setText("VS Code: Error")
        self.vscode_indicator.setStyleSheet("color: #ff6b6b; padding: 0 8px;")
        self.vscode_view.show_error(message)
        self.output_panel.append_message(f"VS Code error: {message}", level="error")

    def _on_vscode_log(self, message: str) -> None:
        """Log VS Code server output."""
        self.output_panel.append_message(f"[vscode] {message}", level="info")

    def _on_editor_loaded(self) -> None:
        """Handle VS Code web UI fully loaded."""
        self.status_label.setText("VS Code ready — SAEngine workspace loaded")
        self.output_panel.append_message(
            "VS Code environment loaded successfully.", level="success"
        )

    def _on_editor_error(self, message: str) -> None:
        """Handle editor loading failure."""
        self.output_panel.append_message(f"Editor error: {message}", level="error")

    # ── View Actions ────────────────────────────────────────────

    def _handle_view_action(self, action: str) -> None:
        """Handle viewport toolbar actions."""
        if action == "view.3d":
            self.viewport.set_view_3d()
        elif action == "view.xy":
            self.viewport.set_view_xy()
        elif action == "view.xz":
            self.viewport.set_view_xz()
        elif action == "view.yz":
            self.viewport.set_view_yz()
        elif action == "view.fit":
            self.viewport.fit_all()

    # ── Dialog Handlers ─────────────────────────────────────────

    def open_grid_dialog(self) -> None:
        """Open the Grid System Definition dialog."""
        dlg = GridDialog(self.project.grids, parent=self)
        if dlg.exec() == GridDialog.DialogCode.Accepted:
            new_grids = dlg.get_grid_system()
            cmd = SetGridSystemCommand(self.project.grids, new_grids)
            self.cmd_manager.execute(cmd)
            self.project.mark_dirty()
            self.refresh_viewport()

    def open_story_dialog(self) -> None:
        """Open the Story Data Definition dialog."""
        dlg = StoryDialog(self.project.stories, parent=self)
        if dlg.exec() == StoryDialog.DialogCode.Accepted:
            new_stories = dlg.get_story_system()
            cmd = SetStorySystemCommand(self.project.stories, new_stories)
            self.cmd_manager.execute(cmd)
            self.project.mark_dirty()
            self.refresh_viewport()

    # ── UI Refresh ──────────────────────────────────────────────

    def refresh_viewport(self) -> None:
        """Refresh the 3D viewport with current model data."""
        self.viewport.render_grids(self.project.grids, self.project.stories)
        self.units_indicator.setText(f"Units: {self.project.units.active_system.display_name}")
        self._update_title()

    def _update_title(self) -> None:
        self.setWindowTitle(f"{self.project.display_name} — SAEngine")

    def _on_stack_changed(self) -> None:
        self._update_title()

    def _on_command_executed(self, description: str) -> None:
        self.status_label.setText(description)
        self.output_panel.append_message(description, level="cmd")

    # ── Theme ───────────────────────────────────────────────────

    def apply_theme(self, theme_name: str) -> None:
        """Switch between dark and light themes (Qt side only)."""
        themes_dir = Path(__file__).parent / "themes"
        theme_file = themes_dir / f"{theme_name}.qss"
        if theme_file.exists():
            with open(theme_file, "r", encoding="utf-8") as f:
                stylesheet = f.read()
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                app.setStyleSheet(stylesheet)
            self.output_panel.append_message(
                f"Applied {theme_name.capitalize()} theme.", level="info"
            )

    # ── Window Lifecycle ────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle window close — stop VS Code server and clean up."""
        self.output_panel.append_message("Shutting down SAEngine...", level="info")

        # Stop VS Code server
        self._vscode_server.stop()

        # Close viewport
        self.viewport.close()

        event.accept()
