"""Unit tests for Project I/O and file persistence."""

import tempfile
from pathlib import Path

from saengine.core.project import Project
from saengine.core.units import UnitSystem
from saengine.io.project_io import ProjectIO


def test_save_and_load_project():
    io = ProjectIO()
    project = Project.create_new("Test Highrise", unit_system=UnitSystem.US)

    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "test_model.saengine"

        # Save
        success = io.save_project(project, file_path)
        assert success
        assert file_path.exists()
        assert not project.is_dirty
        assert project.file_path == file_path

        # Load
        loaded_project = io.load_project(file_path)
        assert loaded_project is not None
        assert loaded_project.settings.project_name == "Test Highrise"
        assert loaded_project.units.active_system == UnitSystem.US
        assert loaded_project.file_path == file_path
        assert not loaded_project.is_dirty
        assert len(loaded_project.grids.x_grids) == len(project.grids.x_grids)
        assert len(loaded_project.stories.stories) == len(project.stories.stories)
