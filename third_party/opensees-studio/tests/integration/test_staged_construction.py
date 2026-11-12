"""Staged (sequential construction) analysis: :class:`StagedCase` against hand calculations,
against the ordinary static case, and against separately built partial models."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import Project, StagedCase, StaticCase
from opensees_studio.services.opensees_runner import OpenSeesRunner
from opensees_studio.services.result_store import load_results, write_results

E, A, I, H = 30e9, 0.1, 1e-3, 3.0  # noqa: E741 (Pa, m², m⁴, m storey height)
P1, P2 = 100e3, 200e3  # N


def _section() -> dict[str, Any]:
    return {
        "id": 1,
        "name": "col",
        "type": "ElasticSection",
        "E": E,
        "A": A,
        "Iz": I,
        "Iy": I,
        "G": E / 2.4,
        "J": 2 * I,
    }


def _pattern(pid: int, loads: list[tuple[int, float]]) -> dict[str, Any]:
    return {
        "id": pid,
        "name": f"P{pid}",
        "type": "Plain",
        "time_series_id": 1,
        "nodal_loads": [{"node_id": n, "forces": [0, 0, -f, 0, 0, 0]} for n, f in loads],
    }


def column_stack() -> Project:
    """Two storeys of one column: node 1 fixed at the base, 2 at H, 3 at 2H; P1 at 2, P2 at 3."""
    fixed = [True] * 6
    free = [False] * 6
    return Project.model_validate(
        {
            "ndm": 3,
            "ndf": 6,
            "nodes": [
                {"id": 1, "coords": [0, 0, 0], "restraint": fixed},
                {"id": 2, "coords": [0, 0, H], "restraint": free},
                {"id": 3, "coords": [0, 0, 2 * H], "restraint": free},
            ],
            "sections": [_section()],
            "elements": [
                {"id": 1, "type": "ElasticBeamColumn", "nodes": [1, 2], "section_id": 1},
                {"id": 2, "type": "ElasticBeamColumn", "nodes": [2, 3], "section_id": 1},
            ],
            "time_series": [{"id": 1, "type": "Linear"}],
            "load_patterns": [_pattern(1, [(2, P1)]), _pattern(2, [(3, P2)])],
        }
    )


def staged(stages: list[dict[str, Any]], case_id: int = 1) -> StagedCase:
    return StagedCase(id=case_id, name="DS", stages=stages)


def test_column_shortening_by_hand() -> None:
    """Storey 2 is built after storey 1 has shortened under P1: node 3 moves only with what
    happens after it exists (2 P2 H / EA), not with storey 1's earlier shortening."""
    project = column_stack()
    case = staged(
        [
            {"name": "Storey 1", "element_ids": [1], "pattern_ids": [1]},
            {"name": "Storey 2", "element_ids": [2], "pattern_ids": [2]},
        ]
    )
    result = OpenSeesRunner(project).run(case)
    flex = H / (E * A)
    assert result.stage_names == ["Storey 1", "Storey 2"]
    assert result.n_steps == 2
    # After storey 1: node 2 under P1; node 3 does not exist yet.
    assert result.node_disp[2][0, 2] == pytest.approx(-P1 * flex, rel=1e-9)
    assert result.node_disp[3][0, 2] == 0.0
    # After storey 2 (cumulative).
    assert result.node_disp[2][1, 2] == pytest.approx(-(P1 + P2) * flex, rel=1e-9)
    assert result.node_disp[3][1, 2] == pytest.approx(-2 * P2 * flex, rel=1e-9)
    # All at once node 3 would be at -(P1 + 2 P2) H / EA: the difference is P1 H / EA.
    instant = OpenSeesRunner(project).run(StaticCase(id=2, name="D", pattern_ids=[1, 2]))
    assert instant.node_disp[3][-1, 2] == pytest.approx(-(P1 + 2 * P2) * flex, rel=1e-9)
    # Forces and reactions do not depend on the sequence here (statically determinate).
    assert result.node_reaction[1][1, 2] == pytest.approx(P1 + P2, rel=1e-9)
    n1 = result.element_forces[1][1, 0]
    assert abs(n1) == pytest.approx(P1 + P2, rel=1e-9)
    assert not np.any(result.element_forces[2][0])  # storey 2 carried nothing before it existed


def frame() -> Project:
    """Two storeys, one bay in X with a stiff wall-like left column and a slender right
    column, rigid diaphragms at each floor: a statically indeterminate frame where the
    sequence changes the beam moments (differential shortening)."""
    fixed = [True] * 6
    free = [False] * 6
    master = [False, False, True, True, True, False]  # out-of-plane DOFs of a diaphragm node
    L = 6.0
    nodes = [
        {"id": 1, "coords": [0, 0, 0], "restraint": fixed},
        {"id": 2, "coords": [L, 0, 0], "restraint": fixed},
        {"id": 3, "coords": [0, 0, H], "restraint": free},
        {"id": 4, "coords": [L, 0, H], "restraint": free},
        {"id": 5, "coords": [0, 0, 2 * H], "restraint": free},
        {"id": 6, "coords": [L, 0, 2 * H], "restraint": free},
        {"id": 7, "coords": [L / 2, 0, H], "restraint": master},
        {"id": 8, "coords": [L / 2, 0, 2 * H], "restraint": master},
    ]
    sections = [
        {**_section(), "id": 1, "name": "wall", "A": 1.0, "Iz": 0.1, "Iy": 0.1, "J": 0.2},
        {**_section(), "id": 2, "name": "column", "A": 0.04, "Iz": 1.3e-4, "Iy": 1.3e-4},
        {**_section(), "id": 3, "name": "beam", "A": 0.15, "Iz": 3e-3, "Iy": 1e-3},
    ]
    beam = {"type": "ElasticBeamColumn"}
    elements = [
        {**beam, "id": 1, "nodes": [1, 3], "section_id": 1},
        {**beam, "id": 2, "nodes": [2, 4], "section_id": 2},
        {**beam, "id": 3, "nodes": [3, 4], "section_id": 3},
        {**beam, "id": 4, "nodes": [3, 5], "section_id": 1},
        {**beam, "id": 5, "nodes": [4, 6], "section_id": 2},
        {**beam, "id": 6, "nodes": [5, 6], "section_id": 3},
    ]
    w = 30e3  # N/m on the beams
    patterns = [
        {
            "id": 1,
            "name": "D1",
            "type": "Plain",
            "time_series_id": 1,
            "element_loads": [{"element_id": 3, "wz": -w}],
        },
        {
            "id": 2,
            "name": "D2",
            "type": "Plain",
            "time_series_id": 1,
            "element_loads": [{"element_id": 6, "wz": -w}],
        },
    ]
    diaphragms = [
        {"type": "RigidDiaphragm", "perp_dir": 3, "retained_node": 7, "constrained_nodes": [3, 4]},
        {"type": "RigidDiaphragm", "perp_dir": 3, "retained_node": 8, "constrained_nodes": [5, 6]},
    ]
    return Project.model_validate(
        {
            "ndm": 3,
            "ndf": 6,
            "nodes": nodes,
            "sections": sections,
            "elements": elements,
            "mp_constraints": diaphragms,
            "time_series": [{"id": 1, "type": "Linear"}],
            "load_patterns": patterns,
        }
    )


STOREYS = [
    {"name": "Level 1", "element_ids": [1, 2, 3], "pattern_ids": [1]},
    {"name": "Level 2", "element_ids": [4, 5, 6], "pattern_ids": [2]},
]


def _transformed(case: StaticCase) -> dict[str, Any]:
    return {"constraints": "Transformation", **case.model_dump()}


def test_one_stage_with_everything_is_the_static_case() -> None:
    project = frame()
    everything = staged(
        [{"name": "All", "element_ids": [1, 2, 3, 4, 5, 6], "pattern_ids": [1, 2]}]
    ).model_copy(update={"constraints": "Transformation"})
    a = OpenSeesRunner(project).run(everything)
    b = OpenSeesRunner(project).run(
        StaticCase(id=2, name="D", pattern_ids=[1, 2], constraints="Transformation")
    )
    for node, rows in b.node_disp.items():
        np.testing.assert_allclose(a.node_disp[node][-1], rows[-1], rtol=1e-9, atol=1e-15)
    for element, rows in b.element_forces.items():
        np.testing.assert_allclose(a.element_forces[element][-1], rows[-1], rtol=1e-8, atol=1e-6)


def _partial(project: Project, elements: set[int], nodes: set[int], pattern: int) -> Project:
    """A hand-built partial model: only ``elements`` and ``nodes``, the diaphragm of the first
    floor only, and the one ``pattern``."""
    keep = [mp for mp in project.mp_constraints if mp.retained_node in nodes]
    return project.model_copy(
        update={
            "nodes": [n for n in project.nodes if n.id in nodes],
            "elements": [e for e in project.elements if e.id in elements],
            "mp_constraints": keep,
            "load_patterns": [p for p in project.load_patterns if p.id == pattern],
        }
    )


def test_staged_frame_is_the_sum_of_the_partial_structures() -> None:
    """Stage results are the sum of (storey 1 under D1) and (both storeys under D2) — two
    models built by hand here — and differ from the all-at-once beam moments."""
    project = frame()
    case = staged(STOREYS).model_copy(update={"constraints": "Transformation"})
    result = OpenSeesRunner(project).run(case)

    first = OpenSeesRunner(_partial(project, {1, 2, 3}, {1, 2, 3, 4, 7}, 1)).run(
        StaticCase(id=3, name="1", pattern_ids=[1], constraints="Transformation")
    )
    second = OpenSeesRunner(_partial(project, set(range(1, 7)), set(range(1, 9)), 2)).run(
        StaticCase(id=4, name="2", pattern_ids=[2], constraints="Transformation")
    )
    for element in (1, 2, 3):
        np.testing.assert_allclose(
            result.element_forces[element][0], first.element_forces[element][-1], atol=1e-6
        )
        np.testing.assert_allclose(
            result.element_forces[element][1],
            first.element_forces[element][-1] + second.element_forces[element][-1],
            rtol=1e-9,
            atol=1e-6,
        )
    for element in (4, 5, 6):
        np.testing.assert_allclose(result.element_forces[element][0], 0.0)
        np.testing.assert_allclose(
            result.element_forces[element][1], second.element_forces[element][-1], atol=1e-6
        )
    total = sum(result.node_reaction[n][1, 2] for n in (1, 2))
    assert total == pytest.approx(2 * 30e3 * 6.0, rel=1e-9)

    # Differential shortening: the level 2 beam moments differ from the instant analysis.
    instant = OpenSeesRunner(project).run(
        StaticCase(id=2, name="D", pattern_ids=[1, 2], constraints="Transformation")
    )
    staged_m = result.element_forces[6][1]
    instant_m = instant.element_forces[6][-1]
    assert not np.allclose(staged_m, instant_m, rtol=1e-3)


def test_refuses_loads_on_what_is_not_built_yet() -> None:
    case = staged(
        [
            {"name": "Storey 1", "element_ids": [1], "pattern_ids": [2]},  # P2 is on node 3
            {"name": "Storey 2", "element_ids": [2]},
        ]
    )
    with pytest.raises(ValueError, match=r"stage 'Storey 1': pattern 2 loads node\(s\) 3"):
        OpenSeesRunner(column_stack()).run(case)


def test_refuses_a_nonlinear_model_and_missing_elements() -> None:
    data = column_stack().model_dump()
    data["materials"] = [{"id": 1, "type": "Steel01", "Fy": 4e8, "E0": 2e11, "b": 0.01}]
    data["elements"][1] = {
        "id": 2,
        "type": "Truss",
        "nodes": [2, 3],
        "area": 0.01,
        "material_id": 1,
    }
    project = Project.model_validate(data)
    case = staged(
        [
            {"name": "1", "element_ids": [1], "pattern_ids": [1]},
            {"name": "2", "element_ids": [2], "pattern_ids": [2]},
        ]
    )
    with pytest.raises(ValueError, match=r"linear elastic model.*Steel01"):
        OpenSeesRunner(project).run(case)
    missing = staged([{"name": "1", "element_ids": [1, 9], "pattern_ids": [1]}])
    assert any("missing element(s) 9" in e for e in column_stack().case_reference_errors(missing))


def test_stage_names_survive_the_result_store(tmp_path) -> None:  # type: ignore[no-untyped-def]
    case = staged(
        [
            {"name": "Storey 1", "element_ids": [1], "pattern_ids": [1]},
            {"name": "Storey 2", "element_ids": [2], "pattern_ids": [2]},
        ]
    )
    result = OpenSeesRunner(column_stack()).run(case)
    entry = write_results(result, tmp_path)
    assert entry["stages"] == ["Storey 1", "Storey 2"]
    back = load_results(entry, tmp_path)
    assert back.stage_names == ["Storey 1", "Storey 2"]
    np.testing.assert_array_equal(back.node_disp[3], result.node_disp[3])
