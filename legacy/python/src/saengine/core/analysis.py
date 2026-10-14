"""Linear-static analysis of three-dimensional elastic frame models."""

from __future__ import annotations

import math
import warnings

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import MatrixRankWarning, spsolve

from saengine.core.frame import FrameModel


class AnalysisError(ValueError):
    """Raised when a frame model is invalid or cannot be analyzed."""


def _require_finite(values: tuple | list, description: str) -> None:
    if not all(
        isinstance(value, (int, float)) and math.isfinite(value)
        for value in values
    ):
        raise AnalysisError(f"{description} must contain only finite numbers")


def _require_positive_id(value: int, description: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AnalysisError(f"{description} must be a positive integer")


def _unique_by_id(items: list, description: str) -> dict[int, object]:
    result = {}
    for item in items:
        _require_positive_id(item.id, f"{description} ID")
        if item.id in result:
            raise AnalysisError(f"Duplicate {description} ID: {item.id}")
        result[item.id] = item
    return result


def _validate_model(model: FrameModel, load_case_id: int):
    if not isinstance(model, FrameModel):
        raise AnalysisError("The request must contain a frame model")

    joints = _unique_by_id(model.joints, "joint")
    members = _unique_by_id(model.members, "member")
    materials = _unique_by_id(model.materials, "material")
    sections = _unique_by_id(model.sections, "section")
    load_cases = _unique_by_id(model.load_cases, "load case")
    _require_positive_id(load_case_id, "Load case ID")

    if not joints:
        raise AnalysisError("The frame model must contain at least one joint")
    if not members:
        raise AnalysisError("The frame model must contain at least one member")
    if load_case_id not in load_cases:
        raise AnalysisError(f"Load case {load_case_id} does not exist")

    for joint in joints.values():
        if len(joint.coordinates) != 3:
            raise AnalysisError(f"Joint {joint.id} must have three coordinates")
        _require_finite(joint.coordinates, f"Joint {joint.id} coordinates")
        if len(joint.restraints) != 6 or not all(
            isinstance(value, bool) for value in joint.restraints
        ):
            raise AnalysisError(f"Joint {joint.id} restraints must contain six booleans")

    for material in materials.values():
        for name in ("elastic_modulus", "shear_modulus"):
            value = getattr(material, name)
            _require_finite([value], f"Material {material.id} {name}")
            if value <= 0:
                raise AnalysisError(f"Material {material.id} {name} must be positive")

    for section in sections.values():
        for name in (
            "area",
            "torsion_constant",
            "moment_of_inertia_y",
            "moment_of_inertia_z",
        ):
            value = getattr(section, name)
            _require_finite([value], f"Section {section.id} {name}")
            if value <= 0:
                raise AnalysisError(f"Section {section.id} {name} must be positive")

    for member in members.values():
        if member.start_joint not in joints or member.end_joint not in joints:
            raise AnalysisError(f"Member {member.id} references a missing joint")
        if member.start_joint == member.end_joint:
            raise AnalysisError(f"Member {member.id} must connect two different joints")
        if member.material_id not in materials:
            raise AnalysisError(f"Member {member.id} references a missing material")
        if member.section_id not in sections:
            raise AnalysisError(f"Member {member.id} references a missing section")
        if len(member.local_z_axis) != 3:
            raise AnalysisError(f"Member {member.id} local_z_axis must have three values")
        _require_finite(member.local_z_axis, f"Member {member.id} local_z_axis")

        start = np.asarray(joints[member.start_joint].coordinates, dtype=float)
        end = np.asarray(joints[member.end_joint].coordinates, dtype=float)
        axis = end - start
        orientation = np.asarray(member.local_z_axis, dtype=float)
        length = np.linalg.norm(axis)
        orientation_length = np.linalg.norm(orientation)
        if length <= 0:
            raise AnalysisError(f"Member {member.id} has zero length")
        if (
            orientation_length <= 0
            or np.linalg.norm(np.cross(axis, orientation))
            <= 1e-12 * length * orientation_length
        ):
            raise AnalysisError(
                f"Member {member.id} local_z_axis must not be parallel to its axis"
            )

    for load in load_cases[load_case_id].joint_loads:
        if load.joint_id not in joints:
            raise AnalysisError(f"Load case {load_case_id} references a missing joint")
        if len(load.values) != 6:
            raise AnalysisError(f"Joint load at {load.joint_id} must contain six values")
        _require_finite(load.values, f"Joint load at {load.joint_id}")

    return joints, members, materials, sections, load_cases[load_case_id]


def _local_stiffness(
    length: float,
    elastic_modulus: float,
    shear_modulus: float,
    section,
) -> np.ndarray:
    """Return the 12x12 Euler-Bernoulli frame stiffness in local axes."""
    area = section.area
    torsion = section.torsion_constant
    iy = section.moment_of_inertia_y
    iz = section.moment_of_inertia_z
    stiffness = np.zeros((12, 12), dtype=float)

    axial = elastic_modulus * area / length
    stiffness[np.ix_([0, 6], [0, 6])] = ((axial, -axial), (-axial, axial))

    torsional = shear_modulus * torsion / length
    stiffness[np.ix_([3, 9], [3, 9])] = (
        (torsional, -torsional),
        (-torsional, torsional),
    )

    bending_z = elastic_modulus * iz
    stiffness[np.ix_([1, 5, 7, 11], [1, 5, 7, 11])] = (
        (12 * bending_z / length**3, 6 * bending_z / length**2,
         -12 * bending_z / length**3, 6 * bending_z / length**2),
        (6 * bending_z / length**2, 4 * bending_z / length,
         -6 * bending_z / length**2, 2 * bending_z / length),
        (-12 * bending_z / length**3, -6 * bending_z / length**2,
         12 * bending_z / length**3, -6 * bending_z / length**2),
        (6 * bending_z / length**2, 2 * bending_z / length,
         -6 * bending_z / length**2, 4 * bending_z / length),
    )

    bending_y = elastic_modulus * iy
    stiffness[np.ix_([2, 4, 8, 10], [2, 4, 8, 10])] = (
        (12 * bending_y / length**3, -6 * bending_y / length**2,
         -12 * bending_y / length**3, -6 * bending_y / length**2),
        (-6 * bending_y / length**2, 4 * bending_y / length,
         6 * bending_y / length**2, 2 * bending_y / length),
        (-12 * bending_y / length**3, 6 * bending_y / length**2,
         12 * bending_y / length**3, 6 * bending_y / length**2),
        (-6 * bending_y / length**2, 2 * bending_y / length,
         6 * bending_y / length**2, 4 * bending_y / length),
    )
    return stiffness


def _transformation(axis: np.ndarray, local_z_axis: tuple[float, float, float]) -> np.ndarray:
    local_x = axis / np.linalg.norm(axis)
    local_y = np.cross(np.asarray(local_z_axis, dtype=float), local_x)
    local_y /= np.linalg.norm(local_y)
    local_z = np.cross(local_x, local_y)
    rotation = np.vstack((local_x, local_y, local_z))
    transform = np.zeros((12, 12), dtype=float)
    for offset in (0, 3, 6, 9):
        transform[offset:offset + 3, offset:offset + 3] = rotation
    return transform


def analyze_linear_static(model: FrameModel, load_case_id: int) -> dict:
    """Run a linear-static load case using a sparse 3D elastic-frame solver.

    Coordinates, forces, material moduli, and section properties must use one
    consistent unit system. Joint force and displacement components are ordered
    FX, FY, FZ, MX, MY, MZ and UX, UY, UZ, RX, RY, RZ, respectively.
    """
    joints, members, materials, sections, load_case = _validate_model(model, load_case_id)
    joint_indices = {joint_id: index for index, joint_id in enumerate(joints)}
    degrees_of_freedom = len(joints) * 6
    rows = []
    columns = []
    values = []
    member_stiffnesses = {}

    for member_id, member in members.items():
        start = np.asarray(joints[member.start_joint].coordinates, dtype=float)
        end = np.asarray(joints[member.end_joint].coordinates, dtype=float)
        axis = end - start
        length = np.linalg.norm(axis)
        material = materials[member.material_id]
        section = sections[member.section_id]
        local = _local_stiffness(
            length, material.elastic_modulus, material.shear_modulus, section
        )
        transform = _transformation(axis, member.local_z_axis)
        global_stiffness = transform.T @ local @ transform
        joint_dofs = [
            *range(
                joint_indices[member.start_joint] * 6,
                joint_indices[member.start_joint] * 6 + 6,
            ),
            *range(
                joint_indices[member.end_joint] * 6,
                joint_indices[member.end_joint] * 6 + 6,
            ),
        ]
        member_stiffnesses[member_id] = (local, transform, joint_dofs)
        rows.extend(np.repeat(joint_dofs, 12))
        columns.extend(np.tile(joint_dofs, 12))
        values.extend(global_stiffness.ravel())

    stiffness = coo_matrix(
        (values, (rows, columns)),
        shape=(degrees_of_freedom, degrees_of_freedom),
    ).tocsr()
    applied_loads = np.zeros(degrees_of_freedom, dtype=float)
    for load in load_case.joint_loads:
        index = joint_indices[load.joint_id] * 6
        applied_loads[index:index + 6] += load.values

    restrained = np.array(
        [
            fixed
            for joint in joints.values()
            for fixed in joint.restraints
        ],
        dtype=bool,
    )
    free_dofs = np.flatnonzero(~restrained)
    if free_dofs.size == 0:
        raise AnalysisError("The frame model has no unrestrained degrees of freedom")

    reduced_stiffness = stiffness[free_dofs][:, free_dofs].tocsc()
    with warnings.catch_warnings():
        warnings.simplefilter("error", MatrixRankWarning)
        try:
            free_displacements = spsolve(reduced_stiffness, applied_loads[free_dofs])
        except MatrixRankWarning as error:
            raise AnalysisError(
                "The frame model is unstable or has singular stiffness"
            ) from error
    if not np.all(np.isfinite(free_displacements)):
        raise AnalysisError("The frame model is unstable or has singular stiffness")

    displacements = np.zeros(degrees_of_freedom, dtype=float)
    displacements[free_dofs] = free_displacements
    reactions = stiffness @ displacements - applied_loads

    return {
        "solver": "SAEngine sparse elastic-frame solver",
        "analysis_type": "linear_static",
        "load_case_id": load_case.id,
        "displacements": [
            {
                "joint_id": joint_id,
                "values": displacements[index * 6:index * 6 + 6].tolist(),
            }
            for joint_id, index in joint_indices.items()
        ],
        "reactions": [
            {
                "joint_id": joint_id,
                "values": reactions[index * 6:index * 6 + 6].tolist(),
            }
            for joint_id, index in joint_indices.items()
        ],
        "member_end_forces": [
            {
                "member_id": member_id,
                "values": (
                    local
                    @ transform
                    @ displacements[joint_dofs]
                ).tolist(),
            }
            for member_id, (local, transform, joint_dofs) in member_stiffnesses.items()
        ],
    }
