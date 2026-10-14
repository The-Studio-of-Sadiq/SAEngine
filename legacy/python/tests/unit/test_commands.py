"""Unit tests for the command pattern and undo/redo operations."""

from saengine.commands.command_manager import CommandManager
from saengine.commands.model_commands import (
    AddXGridCommand, AddYGridCommand, RemoveGridCommand,
    AddStoryCommand, SetGridSystemCommand, SetStorySystemCommand
)
from saengine.core.grids import GridSystem
from saengine.core.stories import StorySystem


def test_command_undo_redo_grid():
    mgr = CommandManager()
    grids = GridSystem()

    cmd = AddXGridCommand(grids, label="1", position=0.0)
    mgr.execute(cmd)

    assert len(grids.x_grids) == 1
    assert mgr.can_undo
    assert not mgr.can_redo

    # Undo
    mgr.undo()
    assert len(grids.x_grids) == 0
    assert not mgr.can_undo
    assert mgr.can_redo

    # Redo
    mgr.redo()
    assert len(grids.x_grids) == 1
    assert mgr.can_undo


def test_set_grid_system_command_undo():
    mgr = CommandManager()
    grids = GridSystem.create_default(n_x=3, n_y=3, spacing_x=5.0, spacing_y=5.0)

    new_grids = GridSystem.create_default(n_x=6, n_y=6, spacing_x=10.0, spacing_y=10.0)
    cmd = SetGridSystemCommand(grids, new_grids)
    mgr.execute(cmd)

    assert len(grids.x_grids) == 6
    assert grids.x_extent == 50.0

    # Undo
    mgr.undo()
    assert len(grids.x_grids) == 3
    assert grids.x_extent == 10.0

    # Redo
    mgr.redo()
    assert len(grids.x_grids) == 6
    assert grids.x_extent == 50.0


def test_story_command_undo_redo():
    mgr = CommandManager()
    stories = StorySystem()
    stories.add_story("Base", 0.0, is_base=True)

    cmd = AddStoryCommand(stories, "Story 1", height=4.0)
    mgr.execute(cmd)

    assert stories.total_height == 4.0
    assert stories.num_stories == 1

    mgr.undo()
    assert stories.total_height == 0.0
    assert stories.num_stories == 0

    mgr.redo()
    assert stories.total_height == 4.0
    assert stories.num_stories == 1
