"""Shell elements, their plate section and rigid diaphragms: schema, validation, the
commands the runner writes and the constraint handler choice. No openseespy: the runner
gets a ``MagicMock`` ops module."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest
from pydantic import ValidationError

from opensees_studio.core import (
    ElasticBeamColumn,
    ElasticMembranePlateSection,
    ElasticSection,
    LinearTimeSeries,
    ModalCase,
    NodalLoad,
    Node,
    PlainLoadPattern,
    Project,
    RigidDiaphragmConstraint,
    ShellElement,
    StaticCase,
)
from opensees_studio.services.opensees_runner import OpenSeesRunner

FIXED = (True,) * 6
MASTER = (False, False, True, True, True, False)


def _project(**kw: object) -> Project:
    args: dict[str, object] = {
        "ndm": 3,
        "ndf": 6,
        "nodes": [
            Node(id=1, coords=(0, 0, 0), restraint=FIXED),
            Node(id=2, coords=(1, 0, 0), restraint=FIXED),
            Node(id=3, coords=(1, 1, 0)),
            Node(id=4, coords=(0, 1, 0)),
            Node(id=5, coords=(0.5, 0.5, 0), restraint=MASTER),
        ],
        "sections": [ElasticMembranePlateSection(id=1, E=30e9, nu=0.2, h=0.2, rho=2500)],
        "elements": [ShellElement(id=1, nodes=(1, 2, 3, 4), section_id=1)],
        "time_series": [LinearTimeSeries(id=1)],
        "load_patterns": [
            PlainLoadPattern(
                id=1,
                time_series_id=1,
                nodal_loads=[NodalLoad(node_id=3, forces=(0, 0, -1, 0, 0, 0))],
            )
        ],
        "analyses": [StaticCase(id=1, pattern_ids=[1]), ModalCase(id=2, n_modes=1)],
    }
    args.update(kw)
    return Project(**args)  # type: ignore[arg-type]


def _problems(project: Project) -> str:
    with pytest.raises(ValueError) as error:
        project.validate_references()
    return str(error.value)


def test_shell_node_count_must_match_its_formulation() -> None:
    ShellElement(id=1, formulation="ASDShellT3", nodes=(1, 2, 3), section_id=1)
    with pytest.raises(ValidationError, match="takes 4 nodes"):
        ShellElement(id=1, formulation="ShellMITC4", nodes=(1, 2, 3), section_id=1)
    with pytest.raises(ValidationError, match="takes 3 nodes"):
        ShellElement(id=1, formulation="ShellDKGT", nodes=(1, 2, 3, 4), section_id=1)
    with pytest.raises(ValidationError, match="distinct"):
        ShellElement(id=1, nodes=(1, 2, 2, 4), section_id=1)


def test_shells_need_a_plate_section_and_a_3d_model() -> None:
    _project().validate_references()
    wrong = _project(sections=[ElasticSection(id=1, E=1, A=1, Iz=1, Iy=1, G=1, J=1)])
    assert "needs an ElasticMembranePlateSection" in _problems(wrong)
    frame = _project(elements=[ElasticBeamColumn(id=1, nodes=(1, 3), section_id=1)])
    assert "for shell elements only" in _problems(frame)


def test_rigid_diaphragm_rules() -> None:
    tie = RigidDiaphragmConstraint(retained_node=5, constrained_nodes=[3, 4])
    _project(mp_constraints=[tie]).validate_references()

    lifted = _project(
        nodes=[
            *_project().nodes[:3],
            Node(id=4, coords=(0, 1, 0.5)),
            Node(id=5, coords=(0.5, 0.5, 0), restraint=MASTER),
        ],
        mp_constraints=[tie],
    )
    assert "node 4 is not in its plane" in _problems(lifted)

    fixed = RigidDiaphragmConstraint(retained_node=5, constrained_nodes=[1, 3])
    assert "fixity on a tied DOF" in _problems(_project(mp_constraints=[fixed]))

    twice = [tie, RigidDiaphragmConstraint(retained_node=5, constrained_nodes=[3])]
    assert "more than one tie" in _problems(_project(mp_constraints=twice))

    free_master = _project(
        nodes=[*_project().nodes[:4], Node(id=5, coords=(0.5, 0.5, 0))], mp_constraints=[tie]
    )
    assert "restrain its out-of-plane DOFs (Uz, Rx, Ry)" in _problems(free_master)


def test_runner_writes_shells_and_diaphragms_and_uses_transformation() -> None:
    tie = RigidDiaphragmConstraint(retained_node=5, constrained_nodes=[3, 4])
    project = _project(mp_constraints=[tie])
    assert project.needs_transformation and not project.has_rigid_links
    ops = MagicMock()
    ops.eleResponse.return_value = [0.0] * 32
    ops.analyze.return_value = 0
    ops.getTime.return_value = 1.0
    ops.nodeDisp.return_value = 0.0
    ops.nodeReaction.return_value = 0.0
    ops.eigen.return_value = [100.0]
    ops.nodeEigenvector.return_value = 0.0
    runner = OpenSeesRunner(project, ops_module=ops)
    runner.build()
    assert call.section("ElasticMembranePlateSection", 1, 30e9, 0.2, 0.2, 2500) in ops.mock_calls
    assert call.element("ASDShellQ4", 1, 1, 2, 3, 4, 1) in ops.mock_calls
    assert call.rigidDiaphragm(3, 5, 3, 4) in ops.mock_calls
    results = runner.run(project.analyses[0])
    assert call.constraints("Transformation") in ops.mock_calls
    assert results.shell_forces[1].shape == (1, 32)
    ops.reset_mock()
    runner.run(project.analyses[1])
    assert call.constraints("Transformation") in ops.mock_calls
