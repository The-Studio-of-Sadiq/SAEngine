import os
os.environ["QT_API"] = "pyside6"
os.environ["SAENGINE_HEADLESS"] = "1"

import pyvista as pv
pv.OFF_SCREEN = True

import pytest
from PySide6.QtWidgets import QApplication

from saengine.gui.ribbon.ribbon_bar import RibbonBar
from saengine.gui.panels.model_explorer import ModelExplorerPanel
from saengine.gui.panels.property_panel import PropertyPanel
from saengine.gui.panels.output_panel import OutputPanel
from saengine.gui.viewport.viewport_widget import ViewportWidget
from saengine.gui.main_window import MainWindow
from saengine.core.project import Project


@pytest.fixture(scope="session")
def qapp():
    """Ensure QApplication is running for GUI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_ribbon_bar(qapp):
    ribbon = RibbonBar()
    assert ribbon.count() == 7  # Home, Model, Loads, Analysis, Design, View, Scripting

    received_actions = []
    ribbon.action_triggered.connect(received_actions.append)

    # Click a button
    btn = ribbon._undo_btn
    btn.click()
    assert "edit.undo" in received_actions


def test_output_panel(qapp):
    panel = OutputPanel()
    panel.append_message("Test message", level="info")
    assert "Test message" in panel.console.toPlainText()

    panel.clear()
    assert panel.console.toPlainText() == ""


def test_property_panel(qapp):
    panel = PropertyPanel()
    project = Project.create_new("Tower X")
    panel.show_object("project", project)

    assert panel.table.rowCount() > 0
    assert "Tower X" in panel.table.item(0, 1).text()


def test_model_explorer(qapp):
    panel = ModelExplorerPanel()
    project = Project.create_new("Skyline Center")
    panel.set_project(project)

    assert panel.tree.topLevelItemCount() == 1
    root = panel.tree.topLevelItem(0)
    assert "Skyline Center" in root.text(0)


def test_viewport_rendering(qapp):
    vp = ViewportWidget()
    project = Project.create_new()
    vp.render_grids(project.grids, project.stories)
    vp.set_view_3d()
    vp.set_view_xy()
    vp.fit_all()
    vp.close()


def test_main_window(qapp):
    window = MainWindow()
    assert "SAEngine" in window.windowTitle()
    assert window.viewport is not None
    assert window.ribbon_bar is not None
    assert window.dock_explorer is not None
    assert window.dock_properties is not None
    assert window.dock_output is not None

    # Test undo/redo dispatch
    window.undo()
    window.redo()

    # Test new project
    window.new_project()
    assert window.project.settings.project_name == "Untitled"

    window.close()
