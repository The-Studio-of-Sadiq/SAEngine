"""
Integration unit tests for SAEngine MainWindow with Code Studio:
- Code Editor
- File Explorer
- Terminal & Python REPL
- Git Version Control
- Ribbon Scripting Tab
- Layout Switching (CAE, Split, Code IDE)
"""

import os
os.environ["QT_API"] = "pyside6"
os.environ["SAENGINE_HEADLESS"] = "1"

import pytest
from PySide6.QtWidgets import QApplication
from unittest.mock import MagicMock, patch

from saengine.gui.main_window import MainWindow
from saengine.core.project import Project


@pytest.fixture(scope="session")
def qapp():
    """Ensure QApplication is running."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_code_studio_integration(qapp):
    # Mock ViewportWidget so VTK OpenGL is not initialized in CI/headless
    with patch("saengine.gui.main_window.ViewportWidget") as MockViewport:
        from PySide6.QtWidgets import QWidget
        mock_vp = QWidget()
        mock_vp.render_grids = MagicMock()
        mock_vp.fit_all = MagicMock()
        mock_vp.close = MagicMock()
        mock_vp.set_view_3d = MagicMock()
        mock_vp.set_view_xy = MagicMock()
        mock_vp.set_view_xz = MagicMock()
        mock_vp.set_view_yz = MagicMock()
        MockViewport.return_value = mock_vp

        window = MainWindow()

        # 1. Verify Title & Core Elements
        assert "SAEngine" in window.windowTitle()
        assert window.ribbon_bar is not None
        assert window.ribbon_bar.count() == 7  # Includes Scripting tab

        # 2. Verify Central Splitter & Editor
        assert window.central_splitter is not None
        assert window.editor_tab is not None
        assert window.editor_tab.tabs.count() >= 1

        # 3. Verify Docks
        assert window.dock_explorer is not None
        assert window.dock_files is not None
        assert window.dock_git is not None
        assert window.dock_properties is not None
        assert window.dock_output is not None
        assert window.dock_terminal is not None

        # 4. Verify Panels
        assert window.file_explorer is not None
        assert window.git_panel is not None
        assert window.terminal_widget is not None

        # 5. Verify Status Bar Indicators
        assert "Git:" in window.git_indicator.text()
        assert "Ln" in window.editor_pos_indicator.text()
        assert "Units:" in window.units_indicator.text()

        # 6. Test Layout Mode Switching
        window.set_layout_mode("cae")
        assert window.editor_tab.isHidden()

        window.set_layout_mode("split")
        assert not window.editor_tab.isHidden()

        window.set_layout_mode("code")
        assert not window.editor_tab.isHidden()

        # 7. Test Script Execution in Engine
        script_code = (
            "project.settings.project_name = 'Automated ETABS Tower'\n"
            "print('Script executed successfully in SAEngine')\n"
        )
        window.run_script(code=script_code)
        assert window.project.settings.project_name == "Automated ETABS Tower"

        # 8. Test Ribbon Action Dispatching
        window._handle_ribbon_action("script.new")
        assert window.editor_tab.tabs.count() >= 2

        window._handle_ribbon_action("layout.split")
        assert not window.editor_tab.isHidden()

        window.close()
