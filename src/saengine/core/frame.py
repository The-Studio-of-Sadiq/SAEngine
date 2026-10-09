"""Structural model data for three-dimensional frame analysis."""

from __future__ import annotations

from dataclasses import dataclass, field


def _read_vector(
    data: dict,
    key: str,
    size: int,
    default: tuple[float, ...] | tuple[bool, ...],
) -> tuple:
    values = data.get(key, default)
    if not isinstance(values, (list, tuple)) or len(values) != size:
        raise ValueError(f"'{key}' must contain exactly {size} values")
    return tuple(values)


@dataclass
class FrameJoint:
    """A six-degree-of-freedom joint in global XYZ coordinates."""

    id: int
    coordinates: tuple[float, float, float]
    restraints: tuple[bool, bool, bool, bool, bool, bool] = (
        False, False, False, False, False, False,
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "coordinates": list(self.coordinates),
            "restraints": list(self.restraints),
        }

    @classmethod
    def from_dict(cls, data: dict) -> FrameJoint:
        return cls(
            id=data["id"],
            coordinates=_read_vector(data, "coordinates", 3, (0.0, 0.0, 0.0)),
            restraints=_read_vector(
                data, "restraints", 6, (False, False, False, False, False, False)
            ),
        )


@dataclass
class FrameMaterial:
    """Isotropic elastic material properties in the project's consistent units."""

    id: int
    elastic_modulus: float
    shear_modulus: float
    name: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "elastic_modulus": self.elastic_modulus,
            "shear_modulus": self.shear_modulus,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FrameMaterial:
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            elastic_modulus=data["elastic_modulus"],
            shear_modulus=data["shear_modulus"],
        )


@dataclass
class FrameSection:
    """Prismatic section properties for an elastic frame member."""

    id: int
    area: float
    torsion_constant: float
    moment_of_inertia_y: float
    moment_of_inertia_z: float
    name: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "area": self.area,
            "torsion_constant": self.torsion_constant,
            "moment_of_inertia_y": self.moment_of_inertia_y,
            "moment_of_inertia_z": self.moment_of_inertia_z,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FrameSection:
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            area=data["area"],
            torsion_constant=data["torsion_constant"],
            moment_of_inertia_y=data["moment_of_inertia_y"],
            moment_of_inertia_z=data["moment_of_inertia_z"],
        )


@dataclass
class FrameMember:
    """A two-node elastic frame element."""

    id: int
    start_joint: int
    end_joint: int
    material_id: int
    section_id: int
    local_z_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "start_joint": self.start_joint,
            "end_joint": self.end_joint,
            "material_id": self.material_id,
            "section_id": self.section_id,
            "local_z_axis": list(self.local_z_axis),
        }

    @classmethod
    def from_dict(cls, data: dict) -> FrameMember:
        return cls(
            id=data["id"],
            start_joint=data["start_joint"],
            end_joint=data["end_joint"],
            material_id=data["material_id"],
            section_id=data["section_id"],
            local_z_axis=_read_vector(data, "local_z_axis", 3, (0.0, 0.0, 1.0)),
        )


@dataclass
class JointLoad:
    """A joint force and moment vector in global XYZ axes."""

    joint_id: int
    values: tuple[float, float, float, float, float, float]

    def to_dict(self) -> dict:
        return {"joint_id": self.joint_id, "values": list(self.values)}

    @classmethod
    def from_dict(cls, data: dict) -> JointLoad:
        return cls(
            joint_id=data["joint_id"],
            values=_read_vector(data, "values", 6, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        )


@dataclass
class FrameLoadCase:
    """A named static load case containing joint loads."""

    id: int
    name: str
    joint_loads: list[JointLoad] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "joint_loads": [load.to_dict() for load in self.joint_loads],
        }

    @classmethod
    def from_dict(cls, data: dict) -> FrameLoadCase:
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            joint_loads=[JointLoad.from_dict(load) for load in data.get("joint_loads", [])],
        )


@dataclass
class FrameModel:
    """Joints, members, properties, and static load cases for a frame model."""

    joints: list[FrameJoint] = field(default_factory=list)
    members: list[FrameMember] = field(default_factory=list)
    materials: list[FrameMaterial] = field(default_factory=list)
    sections: list[FrameSection] = field(default_factory=list)
    load_cases: list[FrameLoadCase] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "model_version": 1,
            "joints": [joint.to_dict() for joint in self.joints],
            "members": [member.to_dict() for member in self.members],
            "materials": [material.to_dict() for material in self.materials],
            "sections": [section.to_dict() for section in self.sections],
            "load_cases": [load_case.to_dict() for load_case in self.load_cases],
        }

    @classmethod
    def from_dict(cls, data: dict) -> FrameModel:
        version = data.get("model_version", 1)
        if version != 1:
            raise ValueError(f"Unsupported frame model version: {version}")
        return cls(
            joints=[FrameJoint.from_dict(item) for item in data.get("joints", [])],
            members=[FrameMember.from_dict(item) for item in data.get("members", [])],
            materials=[FrameMaterial.from_dict(item) for item in data.get("materials", [])],
            sections=[FrameSection.from_dict(item) for item in data.get("sections", [])],
            load_cases=[FrameLoadCase.from_dict(item) for item in data.get("load_cases", [])],
        )
