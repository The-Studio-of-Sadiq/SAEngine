"""Unit tests for the Project container and dirty state management."""

from saengine.core.project import Project
from saengine.core.units import UnitSystem


def test_project_create_new():
    p = Project.create_new(name="Skyscraper-1", unit_system=UnitSystem.SI)
    assert p.settings.project_name == "Skyscraper-1"
    assert p.units.active_system == UnitSystem.SI
    assert len(p.grids.x_grids) > 0
    assert len(p.stories.stories) > 0
    assert not p.is_dirty


def test_project_dirty_flag():
    p = Project.create_new()
    assert not p.is_dirty
    assert "*" not in p.display_name

    p.mark_dirty()
    assert p.is_dirty
    assert "*" in p.display_name

    p.mark_clean()
    assert not p.is_dirty
    assert "*" not in p.display_name


def test_project_serialization():
    p = Project.create_new(name="Tower A")
    d = p.to_dict()
    assert d["saengine_version"] == "0.1.0"
    assert d["settings"]["project_name"] == "Tower A"

    restored = Project.from_dict(d)
    assert restored.settings.project_name == "Tower A"
    assert len(restored.grids.x_grids) == len(p.grids.x_grids)
    assert len(restored.stories.stories) == len(p.stories.stories)
