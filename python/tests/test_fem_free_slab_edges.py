"""FD-1 and FD-4 (walkthrough 3). FD-1: a slab panel with edges that have no beam, wall or column under them
(an L-shaped panel drawn round a stair opening) gives all its load to its supported edges; none
of it is dropped.

Before the fix the free edges' share and the part of a supported edge beyond the last node of
the beam's mesh were dropped ("part of its load has no beam, wall or column to go to; not
applied"): on the walker's 5-storey frame ~22 kN of L and the matching D and SD per floor.
"""

from __future__ import annotations

import pytest
from test_line_loads import OBJECTS, _applied, plan

from saengine.fem import slab_load_shapes as sls
from saengine.fem.derive import derive_fem
from saengine.library import default_material_library
from saengine.library.bim import generate
from saengine.library.settings import default_project_settings

#: The one-bay frame's 6 x 5 m panel less a 3 x 2.5 m corner (the stair void): 22.5 m².
L_SHAPE = [(0, 0), (6000, 0), (6000, 2500), (3000, 2500), (3000, 5000), (0, 5000)]


def _l_corners(cut_x: float, cut_y: float) -> list[tuple[float, float]]:
    return [(0, 0), (6, 0), (6, cut_y), (cut_x, cut_y), (cut_x, 5), (0, 5)]


@pytest.mark.parametrize("cut", [(3.0, 2.5), (2.75, 2.25)])
def test_free_edges_carry_nothing_and_the_total_is_kept(cut: tuple[float, float]) -> None:
    corners = _l_corners(*cut)
    area = 30 - (6 - cut[0]) * (5 - cut[1])
    shape = sls.slab_load_shapes(corners, 1.0, "twoWay", free=[2, 3])
    assert shape.edges[2].total == 0 and shape.edges[3].total == 0
    assert shape.total == pytest.approx(area, rel=1e-6)
    assert any("no beam, wall or column" in note for note in shape.notes)
    # Without free edges, the re-entrant edges take a share (what used to be lost).
    plain = sls.slab_load_shapes(corners, 1.0, "twoWay")
    assert plain.edges[2].total + plain.edges[3].total > 0.1 * area


def test_every_edge_free_gives_no_load_and_says_so() -> None:
    shape = sls.slab_load_shapes(_l_corners(3, 2.5), 1.0, "twoWay", free=range(6))
    assert shape.total == 0
    assert shape.notes


def test_one_way_panel_whose_free_edges_are_along_the_span_keeps_its_shapes() -> None:
    corners = [(0, 0), (6, 0), (6, 2), (0, 2)]  # spans 2 m along y: edges 1 and 3 carry none
    plain = sls.slab_load_shapes(corners, 1.0, "oneWay")
    kept = sls.slab_load_shapes(corners, 1.0, "oneWay", free=[1, 3])
    assert [e.total for e in kept.edges] == pytest.approx([e.total for e in plain.edges])


def _derived(boundary: list[tuple[float, float]] | None):
    settings = default_project_settings("Bay")
    settings = settings.model_copy(
        update={"analysis": settings.analysis.model_copy(update={"slabs": "loadsToBeams"})}
    )
    building = generate(plan(2), "s")
    if boundary is not None:
        elements = [
            e.model_copy(update={"boundary": [list(p) for p in boundary]}) if e.id == "S1" else e
            for e in building.elements
        ]
        building = building.model_copy(update={"elements": elements})
    derivation = derive_fem(
        building, OBJECTS, default_material_library(), settings, {"bim": "abc"}, architecture=False
    )
    floor = next(a for a in settings.areaLoads if a.id == settings.floorLoad)
    return derivation, floor


def test_l_shaped_slab_round_a_stair_opening_applies_all_its_load() -> None:
    rectangle, floor = _derived(None)
    l_shaped, _ = _derived(L_SHAPE)
    assert not [n for n in l_shaped.notes if "no beam, wall or column to go to" in n], (
        l_shaped.notes
    )
    assert any("S1: edges" in n and "nearest supported" in n for n in l_shaped.notes)
    void = 3.0 * 2.5  # m²
    # The L-shaped panel's SD + L are its 22.5 m² times the floor's finish, live load and
    # partition allowance (the rectangle's less the void's): exact, nothing dropped.
    pressure = floor.finish + floor.live + floor.partitions
    assert pressure > 0
    whole = sum(-_applied(rectangle.project, case) / 1e3 for case in ("SD", "L"))
    cut = sum(-_applied(l_shaped.project, case) / 1e3 for case in ("SD", "L"))
    assert cut == pytest.approx(whole - pressure * void, rel=1e-6)


def test_slab_corner_part_way_along_a_beam_mesh_member_reaches_the_next_node() -> None:
    # A corner at 2.75 m on the 5 m beam A-2 / B-2 lines is not a node of the 500 mm mesh: the
    # bit of edge up to the next node goes to that node, not dropped.
    boundary = [(0, 0), (6000, 0), (6000, 2250), (2750, 2250), (2750, 5000), (0, 5000)]
    rectangle, floor = _derived(None)
    l_shaped, _ = _derived(boundary)
    assert not [n for n in l_shaped.notes if "no beam, wall or column to go to" in n], (
        l_shaped.notes
    )
    void = (6 - 2.75) * (5 - 2.25)
    pressure = floor.finish + floor.live + floor.partitions
    whole = sum(-_applied(rectangle.project, case) / 1e3 for case in ("SD", "L"))
    cut = sum(-_applied(l_shaped.project, case) / 1e3 for case in ("SD", "L"))
    assert cut == pytest.approx(whole - pressure * void, rel=1e-6)


def test_deriving_an_empty_building_model_fails_and_points_to_the_build(tmp_path) -> None:
    """FD-4: before 6 BIM is built the model had 0 nodes and showed "Up to date"; now a clear
    failure that names Build from Floor Plan (nothing is written)."""
    import json

    from saengine.rpc import handlers

    bim = generate(plan(1), "s").model_dump(mode="json", by_alias=True, exclude_none=True)
    bim["elements"] = []
    out = handlers.derive_fem(
        json.dumps(bim),
        OBJECTS.model_dump_json(by_alias=True),
        default_material_library().model_dump_json(by_alias=True),
        default_project_settings("Bay").model_dump_json(by_alias=True),
        str(tmp_path / "08 FEM"),
        loads_text="",
        architecture_text="",
    )
    assert "text" not in out
    assert any("Build from Floor Plan" in p for p in out["problems"])
