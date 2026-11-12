"""Unit tests for GridDialog and StoryDialog."""

import os
os.environ["QT_API"] = "pyside6"

import pytest
from PySide6.QtWidgets import QApplication

from saengine.gui.dialogs.grid_dialog import GridDialog
from saengine.gui.dialogs.story_dialog import StoryDialog
from saengine.core.grids import GridSystem
from saengine.core.stories import StorySystem


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_grid_dialog_initialization(qapp):
    grids = GridSystem.create_default(n_x=4, n_y=3, spacing_x=6.0, spacing_y=5.0)
    dlg = GridDialog(grids)
    assert dlg.table_x.rowCount() == 4
    assert dlg.table_y.rowCount() == 3

    # Test uniform grid generation
    dlg.spin_nx.setValue(5)
    dlg.spin_ny.setValue(4)
    dlg.spin_sx.setValue(8.0)
    dlg.spin_sy.setValue(7.0)
    dlg._apply_uniform()

    assert dlg.table_x.rowCount() == 5
    assert dlg.table_y.rowCount() == 4

    result = dlg.get_grid_system()
    assert len(result.x_grids) == 5
    assert len(result.y_grids) == 4
    assert result.x_positions[-1] == 32.0


def test_story_dialog_initialization(qapp):
    stories = StorySystem.create_default(n_stories=3, typical_height=3.0, ground_height=4.0)
    dlg = StoryDialog(stories)
    # 4 rows: Roof, Story 2, Story 1, Base
    assert dlg.table.rowCount() == 4

    # Add a story on top
    dlg._add_story_top()
    assert dlg.table.rowCount() == 5

    result = dlg.get_story_system()
    assert result.num_stories == 4
