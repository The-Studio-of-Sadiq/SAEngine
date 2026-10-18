"""What the design of a foundation needs from the project: the parts it reads and the loads.

:func:`load_context` reads the project's files once; the design functions of each foundation
type take the :class:`Context` and one :class:`~saengine.library.substructure.Foundation`
(the pile caps and rafts of :mod:`saengine.substructure.piles` and
:mod:`saengine.substructure.raft` as well as the footings of
:mod:`saengine.substructure.shallow`). A foundation that cannot be designed raises
:class:`Skip` with the reason.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from saengine.library.bim import BuildingModel, ColumnElement, WallElement
from saengine.library.materials import Category, Material, MaterialLibrary
from saengine.library.objects import CircleProfile, Column, ObjectLibrary, RectangleProfile
from saengine.library.settings import ProjectSettings, read_soil_text
from saengine.library.substructure import SUBSTRUCTURE_FILE, Foundation, Substructure, parse
from saengine.substructure.loads import BaseLoads, base_loads


class Skip(Exception):
    """A foundation that cannot be designed, with the reason (the exception's message)."""


@dataclass
class Context:
    """The project's parts a foundation's design reads, and the loads on the column bases
    (None without analysis results)."""

    substructure: Substructure
    building: BuildingModel
    objects: ObjectLibrary
    materials: MaterialLibrary
    settings: ProjectSettings
    soil_text: str | None = None
    loads: BaseLoads | None = None
    project: dict[str, Any] | None = None  # the analysis model (08 FEM/model.osmodel)
    root: Path | None = None
    out_dir: Path | None = None
    #: Why there are no loads (no analysis model, no results), when ``loads`` is None.
    no_loads: str = ""
    elements: dict[str, Any] = field(init=False)
    types: dict[str, Any] = field(init=False)
    mats: dict[str, Material] = field(init=False)

    def __post_init__(self) -> None:
        from saengine.substructure.shallow import SoilBearing

        self.elements = {e.id: e for e in self.building.elements}
        self.types = {o.id: o for o in self.objects.objects}
        self.mats = {m.id: m for m in self.materials.materials}
        self.soil = SoilBearing(
            self.soil_text,
            self.settings.foundation,
            self.substructure.design.factorOfSafety.bearing,
        )

    @property
    def ground_level(self) -> float:
        return self.settings.foundation.groundLevel

    def founding_level(self, foundation: Foundation) -> float:
        return foundation.founding_level(self.ground_level)

    def position(self, element_id: str) -> np.ndarray | None:
        """Plan position [x, y] mm of a column, or the middle of a wall."""
        element = self.elements.get(element_id)
        if isinstance(element, ColumnElement):
            return np.array(element.position[:2], dtype=float)
        if isinstance(element, WallElement):
            return (np.array(element.start, float) + np.array(element.end, float)) / 2
        return None

    def center(self, foundation: Foundation) -> np.ndarray:
        """Plan centre [x, y] mm: its own, or the centroid of its columns (a strip: the middle
        of its path; a raft: the centroid of its outline)."""
        if foundation.type == "strip" and foundation.path:
            path = np.array(foundation.path, dtype=float)
            return (path[0] + path[-1]) / 2
        if foundation.type == "raft" and foundation.outline:
            return polygon_centroid(foundation.outline)
        if foundation.center is not None:
            return np.array(foundation.center, dtype=float)
        points = [p for c in foundation.columns if (p := self.position(c)) is not None]
        if not points:
            raise Skip("it has no centre and none of its columns is in 6 BIM")
        return np.mean(points, axis=0)

    def axes(self, foundation: Foundation) -> tuple[np.ndarray, np.ndarray]:
        """The foundation's local axes u (along its length; a strip: along its path) and v, as
        global 3-vectors."""
        if foundation.type == "strip" and foundation.path:
            path = np.array(foundation.path, dtype=float)
            along = path[-1] - path[0]
            theta = math.atan2(along[1], along[0])
        else:
            theta = math.radians(foundation.rotation)
        return (
            np.array([math.cos(theta), math.sin(theta), 0.0]),
            np.array([-math.sin(theta), math.cos(theta), 0.0]),
        )

    def concrete(self, material_id: str | None, owner: str) -> Material:
        """The concrete material ``material_id``, or :class:`Skip`."""
        if material_id is None:
            raise Skip("no concrete material")
        material = self.mats.get(material_id)
        if material is None:
            raise Skip(f"unknown material '{material_id}'")
        if material.category != Category.CONCRETE or not material.concrete:
            raise Skip(f"{owner}: '{material_id}' is not concrete")
        return material

    def rebar(self, material_id: str) -> Material:
        material = self.mats.get(material_id)
        if material is None or material.steel is None:
            raise Skip(f"unknown reinforcement material '{material_id}'")
        return material

    def column_sides(self, column: ColumnElement, rotation: float) -> tuple[float, float, str]:
        """The sides [mm] of a column along the u and v axes of a foundation turned by
        ``rotation`` [°], and a note when it is skewed; :class:`Skip` for other profiles."""
        column_type = self.types.get(column.type)
        profile = column_type.profile if isinstance(column_type, Column) else None
        if isinstance(profile, RectangleProfile):
            sides = (profile.xDim, profile.yDim)
        elif isinstance(profile, CircleProfile):
            side = profile.radius * math.sqrt(math.pi)
            sides = (side, side)
        else:
            raise Skip(f"{column.id}: only rectangular and circular columns are supported")
        note = ""
        turn = (column.rotation - rotation) / 90
        if abs(turn - round(turn)) > 1e-6 and not isinstance(profile, CircleProfile):
            note = f"{column.id} is skewed to the foundation; taken at the nearest quarter turn"
        if round(turn) % 2:
            sides = sides[::-1]
        return sides[0], sides[1], note

    def require_loads(self) -> BaseLoads:
        if self.loads is None:
            raise Skip(self.no_loads or "there are no analysis results; run the analysis first")
        if not self.loads.strength:
            raise Skip("no load combination could be formed")
        return self.loads


def polygon_centroid(points: list[list[float]]) -> np.ndarray:
    """Centroid [x, y] of a simple polygon."""
    p = np.array(points, dtype=float)
    q = np.roll(p, -1, axis=0)
    cross = p[:, 0] * q[:, 1] - q[:, 0] * p[:, 1]
    area = cross.sum() / 2
    if abs(area) < 1e-9:
        return p.mean(axis=0)
    return np.array([((p[:, 0] + q[:, 0]) * cross).sum(), ((p[:, 1] + q[:, 1]) * cross).sum()]) / (
        6 * area
    )


def load_context(project_root: str | Path, out_dir: str | Path | None = None) -> Context:
    """The context of the project at ``project_root``, with the loads of the results in
    ``out_dir`` (default ``08 FEM/model.results``) when the analysis has run. Raises
    ``ValueError`` when a part cannot be read or is invalid."""
    root = Path(project_root)

    def read(relative: str) -> str:
        try:
            return (root / relative).read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError(f"{relative} could not be read: {error}") from error

    settings = ProjectSettings.model_validate_json(
        read("02 Project Settings/project-settings.json")
    )
    materials = MaterialLibrary.model_validate_json(read("03 Materials/materials.json"))
    objects = ObjectLibrary.model_validate_json(read("04 Objects/objects.json"))
    building = BuildingModel.model_validate_json(read("06 BIM/bim.json"))
    try:
        substructure_text = (root / SUBSTRUCTURE_FILE).read_text(encoding="utf-8")
    except OSError:
        substructure_text = None
    substructure = parse(substructure_text)
    out = Path(out_dir) if out_dir is not None else root / "08 FEM" / "model.results"
    model: Path | None = root / "08 FEM" / "model.osmodel"
    project: dict[str, Any] | None = None
    loads: BaseLoads | None = None
    no_loads = ""
    if out_dir is None:
        # On soil springs the supports are below the column bases: the foundations are designed
        # from the same model run with fixed bases (saengine.fem.ssi_compare).
        from saengine.fem.ssi_compare import fixed_run, on_springs

        if on_springs(root):
            fixed = fixed_run(root)
            if isinstance(fixed, str):
                no_loads = fixed
                model = None
            else:
                model, out = fixed
    try:
        if model is None:
            raise OSError
        project = json.loads(model.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        no_loads = no_loads or "there is no analysis model; build and run it in 8 FEM first"
    if project is not None:
        try:
            loads = base_loads(project, out, building, settings)
        except ValueError:
            no_loads = "there are no analysis results; run the analysis in 8 FEM first"
    return Context(
        substructure,
        building,
        objects,
        materials,
        settings,
        read_soil_text(root),
        loads,
        project,
        root,
        out,
        no_loads,
    )
