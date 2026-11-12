"""Unit tests for the grid system."""

from saengine.core.grids import GridLine, GridSystem


def test_default_grid_system():
    grids = GridSystem.create_default(n_x=4, n_y=3, spacing_x=6.0, spacing_y=5.0)
    assert len(grids.x_grids) == 4
    assert len(grids.y_grids) == 3

    assert grids.x_positions == [0.0, 6.0, 12.0, 18.0]
    assert grids.y_positions == [0.0, 5.0, 10.0]
    assert grids.x_extent == 18.0
    assert grids.y_extent == 10.0


def test_add_remove_grid():
    grids = GridSystem()
    g1 = grids.add_x_grid("1", 0.0)
    g2 = grids.add_x_grid("2", 8.0)

    assert len(grids.x_grids) == 2
    assert grids.get_grid_by_label("2") == g2

    removed = grids.remove_grid(g1.id)
    assert removed == g1
    assert len(grids.x_grids) == 1
    assert grids.x_positions == [8.0]


def test_grid_serialization():
    grids = GridSystem.create_default()
    d = grids.to_dict()

    restored = GridSystem.from_dict(d)
    assert len(restored.x_grids) == len(grids.x_grids)
    assert len(restored.y_grids) == len(grids.y_grids)
    assert restored.x_positions == grids.x_positions
    assert restored.y_positions == grids.y_positions
