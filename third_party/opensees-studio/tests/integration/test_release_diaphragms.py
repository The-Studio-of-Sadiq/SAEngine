"""``StaticCase.release_diaphragms``: a static case run without the model's rigid diaphragms
(a self-straining case such as a temperature change, which a rigid diaphragm would hold)."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest

pytest.importorskip("openseespy")

from opensees_studio.core import Project, StaticCase
from opensees_studio.services.opensees_runner import OpenSeesRunner

E, A, I, H, L = 30e9, 0.15, 3e-3, 3.0, 6.0  # noqa: E741 (Pa, m², m⁴, m)
N0 = 1.0e5  # N: the pair of forces stretching the beam (as an expanding beam's nodal loads)


def portal(diaphragm: bool) -> Project:
    """A fixed-base portal in the XZ plane with its two column tops, plus their centre node, on
    one rigid diaphragm; pattern 1 pushes the tops apart (±N0), pattern 2 pulls the floor."""
    fixed = [True] * 6
    free = [False] * 6
    centre = [False, False, True, True, True, False]  # free in plan, held out of plane
    nodes = [
        {"id": 1, "coords": [0, 0, 0], "restraint": fixed},
        {"id": 2, "coords": [L, 0, 0], "restraint": fixed},
        {"id": 3, "coords": [0, 0, H], "restraint": free},
        {"id": 4, "coords": [L, 0, H], "restraint": free},
    ]
    if diaphragm:
        nodes.append({"id": 5, "coords": [L / 2, 0, H], "restraint": centre})
    section = {"id": 1, "name": "s", "type": "ElasticSection", "E": E, "A": A}
    section |= {"Iz": I, "Iy": I, "G": E / 2.4, "J": 2 * I}
    beam = {"type": "ElasticBeamColumn", "section_id": 1}
    data: dict[str, Any] = {
        "ndm": 3,
        "ndf": 6,
        "nodes": nodes,
        "sections": [section],
        "elements": [
            {**beam, "id": 1, "nodes": [1, 3]},
            {**beam, "id": 2, "nodes": [2, 4]},
            {**beam, "id": 3, "nodes": [3, 4]},
        ],
        "time_series": [{"id": 1, "type": "Linear"}],
        "load_patterns": [
            {
                "id": 1,
                "name": "spread",
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [
                    {"node_id": 3, "forces": [-N0, 0, 0, 0, 0, 0]},
                    {"node_id": 4, "forces": [N0, 0, 0, 0, 0, 0]},
                ],
            },
            {
                "id": 2,
                "name": "centre",
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [{"node_id": 5 if diaphragm else 3, "forces": [N0, 0, 0, 0, 0, 0]}],
            },
        ],
    }
    if diaphragm:
        data["mp_constraints"] = [
            {
                "type": "RigidDiaphragm",
                "perp_dir": 3,
                "retained_node": 5,
                "constrained_nodes": [3, 4],
            }
        ]
    return Project.model_validate(data)


def test_default_keeps_the_diaphragm_and_the_file_unchanged() -> None:
    case = StaticCase(id=1, name="T", pattern_ids=[1])
    assert "release_diaphragms" not in case.model_dump()  # old files stay byte-identical
    assert StaticCase.model_validate(json.loads(case.model_dump_json())) == case
    held = OpenSeesRunner(portal(True)).run(case)
    # The diaphragm holds the tops together: the beam takes the pair, the columns nothing.
    assert held.node_disp[3][-1, 0] == pytest.approx(held.node_disp[4][-1, 0], abs=1e-15)
    assert abs(held.element_forces[1][-1, 1]) < 1e-6 * N0


def test_released_case_matches_the_model_without_diaphragm() -> None:
    case = StaticCase(id=1, name="T", pattern_ids=[1], release_diaphragms=True)
    assert case.model_dump()["release_diaphragms"] is True
    released = OpenSeesRunner(portal(True)).run(case)
    bare = OpenSeesRunner(portal(False)).run(StaticCase(id=1, name="T", pattern_ids=[1]))
    for node in (1, 2, 3, 4):
        np.testing.assert_allclose(released.node_disp[node], bare.node_disp[node], atol=1e-15)
        np.testing.assert_allclose(
            released.node_reaction[node], bare.node_reaction[node], atol=1e-6
        )
    for element in (1, 2, 3):
        np.testing.assert_allclose(
            released.element_forces[element], bare.element_forces[element], atol=1e-6
        )
    # The tops now move apart and the columns bend.
    assert released.node_disp[4][-1, 0] - released.node_disp[3][-1, 0] > 0
    assert abs(released.element_forces[1][-1, 4]) > 1e-3 * N0
    # The diaphragm's own node, now unconnected, reports zero.
    assert not np.any(released.node_disp[5]) and not np.any(released.node_reaction[5])


def test_released_case_refuses_a_load_on_the_diaphragm_node() -> None:
    case = StaticCase(id=1, name="T", pattern_ids=[2], release_diaphragms=True)
    with pytest.raises(ValueError, match="only a diaphragm connects"):
        OpenSeesRunner(portal(True)).run(case)


def test_release_without_diaphragms_is_the_ordinary_case() -> None:
    case = StaticCase(id=1, name="T", pattern_ids=[1], release_diaphragms=True)
    ordinary = StaticCase(id=1, name="T", pattern_ids=[1])
    a = OpenSeesRunner(portal(False)).run(case)
    b = OpenSeesRunner(portal(False)).run(ordinary)
    np.testing.assert_array_equal(a.node_disp[4], b.node_disp[4])
