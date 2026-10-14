"""Tests for the three-dimensional elastic frame model and solver."""

import pytest

from saengine.core.analysis import AnalysisError, analyze_linear_static
from saengine.core.frame import (
    FrameJoint,
    FrameLoadCase,
    FrameMaterial,
    FrameMember,
    FrameModel,
    FrameSection,
    JointLoad,
)
from saengine.core.frame_builder import generate_grid_frame_model
from saengine.core.grids import GridSystem
from saengine.core.project import Project
from saengine.core.stories import StorySystem


def cantilever_model():
    return FrameModel(
        joints=[
            FrameJoint(1, (0.0, 0.0, 0.0), (True, True, True, True, True, True)),
            FrameJoint(2, (4.0, 0.0, 0.0)),
        ],
        members=[FrameMember(1, 1, 2, 1, 1)],
        materials=[FrameMaterial(1, 200e6, 80e6, "Steel")],
        sections=[FrameSection(1, 0.02, 0.0001, 0.0002, 0.0002, "Test section")],
        load_cases=[
            FrameLoadCase(1, "Service", [JointLoad(2, (0.0, -10.0, 0.0, 0.0, 0.0, 0.0))])
        ],
    )


def test_project_frame_model_round_trip_and_legacy_default():
    project = Project.create_new("Frame test")
    project.frame_model = cantilever_model()

    loaded = Project.from_dict(project.to_dict())

    assert loaded.frame_model.to_dict() == project.frame_model.to_dict()
    assert Project.from_dict({"settings": {}}).frame_model == FrameModel()


def test_grid_frame_builder_generates_supported_three_dimensional_frame():
    grids = GridSystem.create_default(n_x=2, n_y=2, spacing_x=5.0, spacing_y=4.0)
    stories = StorySystem.create_default(n_stories=1, ground_height=3.0)
    material = FrameMaterial(1, 200e6, 80e6, "Steel")
    section = FrameSection(1, 0.02, 0.0001, 0.0002, 0.0002, "Frame section")

    model = generate_grid_frame_model(grids, stories, material, section)

    assert len(model.joints) == 8
    assert len(model.members) == 8
    assert sum(all(joint.restraints) for joint in model.joints) == 4
    assert len(model.load_cases) == 1


def test_grid_frame_linear_static_analysis_balances_lateral_load():
    model = generate_grid_frame_model(
        GridSystem.create_default(n_x=2, n_y=2, spacing_x=5.0, spacing_y=4.0),
        StorySystem.create_default(n_stories=1, ground_height=3.0),
        FrameMaterial(1, 200e6, 80e6, "Steel"),
        FrameSection(1, 0.02, 0.0001, 0.0002, 0.0002, "Frame section"),
    )
    top_joint = next(joint for joint in model.joints if joint.coordinates[2] == 3.0)
    model.load_cases[0].joint_loads = [
        JointLoad(top_joint.id, (10.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    ]

    result = analyze_linear_static(model, 1)
    restrained_ids = {joint.id for joint in model.joints if all(joint.restraints)}
    base_reaction = sum(
        item["values"][0]
        for item in result["reactions"]
        if item["joint_id"] in restrained_ids
    )
    max_displacement = max(
        abs(item["values"][0]) for item in result["displacements"]
    )

    assert base_reaction == pytest.approx(-10.0, rel=1e-6)
    assert max_displacement > 0


def test_linear_static_cantilever_matches_euler_bernoulli_solution():
    result = analyze_linear_static(cantilever_model(), 1)
    free_end = next(
        item for item in result["displacements"] if item["joint_id"] == 2
    )
    support = next(item for item in result["reactions"] if item["joint_id"] == 1)

    expected_deflection = -10.0 * 4.0**3 / (3.0 * 200e6 * 0.0002)
    assert result["solver"] == "SAEngine sparse elastic-frame solver"
    assert result["analysis_type"] == "linear_static"
    assert free_end["values"][1] == pytest.approx(expected_deflection, rel=1e-6)
    assert support["values"][1] == pytest.approx(10.0, rel=1e-6)
    assert support["values"][5] == pytest.approx(40.0, rel=1e-6)
    assert len(result["member_end_forces"][0]["values"]) == 12


@pytest.mark.parametrize(
    ("load", "axis", "inertia"),
    [
        ((0.0, 0.0, -10.0, 0.0, 0.0, 0.0), 2, 0.0002),
        ((-10.0, 0.0, 0.0, 0.0, 0.0, 0.0), 0, None),
    ],
)
def test_linear_static_cantilever_solves_out_of_plane_and_axial_loads(load, axis, inertia):
    model = cantilever_model()
    model.load_cases[0].joint_loads = [JointLoad(2, load)]

    result = analyze_linear_static(model, 1)
    free_end = next(item for item in result["displacements"] if item["joint_id"] == 2)
    if axis == 0:
        expected = -10.0 * 4.0 / (200e6 * 0.02)
    else:
        expected = -10.0 * 4.0**3 / (3.0 * 200e6 * inertia)

    assert free_end["values"][axis] == pytest.approx(expected, rel=1e-6)


def test_analysis_rejects_member_with_parallel_local_axis():
    model = cantilever_model()
    model.members[0].local_z_axis = (1.0, 0.0, 0.0)

    with pytest.raises(AnalysisError, match="must not be parallel"):
        analyze_linear_static(model, 1)


def test_analysis_rejects_missing_load_case():
    with pytest.raises(AnalysisError, match="does not exist"):
        analyze_linear_static(cantilever_model(), 2)
