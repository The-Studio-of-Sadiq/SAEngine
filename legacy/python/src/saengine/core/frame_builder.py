"""Construction of a regular 3D frame from project grids and story elevations."""

from __future__ import annotations

import math

from saengine.core.frame import (
    FrameJoint,
    FrameLoadCase,
    FrameMaterial,
    FrameMember,
    FrameModel,
    FrameSection,
)
from saengine.core.grids import GridSystem
from saengine.core.stories import StorySystem


def _ordered_coordinates(values: list[float], description: str) -> list[float]:
    if len(values) < 2:
        raise ValueError(f"At least two {description} are required")
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{description.capitalize()} must be finite")
    ordered = sorted(values)
    if any(first == second for first, second in zip(ordered, ordered[1:])):
        raise ValueError(f"{description.capitalize()} must have unique coordinates")
    return ordered


def generate_grid_frame_model(
    grids: GridSystem,
    stories: StorySystem,
    material: FrameMaterial,
    section: FrameSection,
) -> FrameModel:
    """Generate beams and columns at every grid intersection and story level."""
    x_coordinates = _ordered_coordinates(grids.x_positions, "X grid")
    y_coordinates = _ordered_coordinates(grids.y_positions, "Y grid")
    elevations = _ordered_coordinates(
        [story.elevation for story in stories.stories],
        "story elevation",
    )

    for name, value in (
        ("elastic_modulus", material.elastic_modulus),
        ("shear_modulus", material.shear_modulus),
        ("area", section.area),
        ("torsion_constant", section.torsion_constant),
        ("moment_of_inertia_y", section.moment_of_inertia_y),
        ("moment_of_inertia_z", section.moment_of_inertia_z),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be finite and positive")

    joints = []
    joint_ids = {}
    for level, elevation in enumerate(elevations):
        for y_index, y in enumerate(y_coordinates):
            for x_index, x in enumerate(x_coordinates):
                joint_id = len(joints) + 1
                joint_ids[(level, y_index, x_index)] = joint_id
                joints.append(
                    FrameJoint(
                        id=joint_id,
                        coordinates=(x, y, elevation),
                        restraints=(True, True, True, True, True, True)
                        if level == 0
                        else (False, False, False, False, False, False),
                    )
                )

    members = []

    def add_member(
        start_joint: int,
        end_joint: int,
        local_z_axis: tuple[float, float, float],
    ) -> None:
        members.append(
            FrameMember(
                id=len(members) + 1,
                start_joint=start_joint,
                end_joint=end_joint,
                material_id=material.id,
                section_id=section.id,
                local_z_axis=local_z_axis,
            )
        )

    for level in range(len(elevations) - 1):
        for y_index in range(len(y_coordinates)):
            for x_index in range(len(x_coordinates)):
                add_member(
                    joint_ids[(level, y_index, x_index)],
                    joint_ids[(level + 1, y_index, x_index)],
                    (1.0, 0.0, 0.0),
                )

    for level in range(1, len(elevations)):
        for y_index in range(len(y_coordinates)):
            for x_index in range(len(x_coordinates) - 1):
                add_member(
                    joint_ids[(level, y_index, x_index)],
                    joint_ids[(level, y_index, x_index + 1)],
                    (0.0, 0.0, 1.0),
                )
        for x_index in range(len(x_coordinates)):
            for y_index in range(len(y_coordinates) - 1):
                add_member(
                    joint_ids[(level, y_index, x_index)],
                    joint_ids[(level, y_index + 1, x_index)],
                    (0.0, 0.0, 1.0),
                )

    return FrameModel(
        joints=joints,
        members=members,
        materials=[material],
        sections=[section],
        load_cases=[FrameLoadCase(id=1, name="Load Case 1")],
    )
