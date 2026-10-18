"""MEP coordination (``07 MEP/mep.json``): what the building services put on the structure.

Part 7 records the services as far as the structure is concerned: heavy equipment standing on
the floors (their loads go into the analysis), sleeves and openings through beams, slabs and walls
(checked structurally), vertical shafts (holes in the floors of the analysis model) and the MEP
models of the consultants (IFC files, checked for clashes with the structure). The file stores
only what the engineer enters; loads, checks and clashes are worked out on demand
(:func:`saengine.mep.report.mep_report`).

Units: mm for coordinates, sizes and levels, kN for weights, degrees for rotations. Plan
coordinates are global (the building model's); a story is a building-model story id.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.labels import field_title
from saengine.library.materials import Id

SCHEMA_ID = "saengine.mep/1"
MEP_FILE = "07 MEP/mep.json"

Length = Annotated[float, Field(gt=0, description="[mm]")]
Mm = Annotated[float, Field(description="[mm]")]
Point2 = Annotated[list[float], Field(min_length=2, max_length=2, description="[x, y] in mm.")]

EquipmentKind = Literal[
    "tank", "chiller", "ahu", "pump", "generator", "transformer", "lift", "other"
]
EQUIPMENT_KINDS = {
    "tank": "Water tank",
    "chiller": "Chiller",
    "ahu": "Air handling unit",
    "pump": "Pump",
    "generator": "Generator",
    "transformer": "Transformer",
    "lift": "Lift machine",
    "other": "Other",
}
DISCIPLINES = {
    "mechanical": "Mechanical (HVAC)",
    "plumbing": "Plumbing",
    "fire": "Fire protection",
    "electrical": "Electrical",
}


def _labels(names: list[str]) -> dict[str, Any]:
    """Readable names of an enum's values for the editors (JSON Schema ``enumDescriptions``)."""
    return {"enumDescriptions": names}


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class Plinth(_Model):
    """A concrete plinth under a piece of equipment, of the equipment's footprint."""

    height: Length
    material: Id = Field(description="Concrete from 03 Materials (its density gives the weight).")


class Equipment(_Model):
    """A piece of equipment standing on a floor: its weight is a load on the structure."""

    id: Id
    name: str = Field(default="", description="E.g. 'Overhead water tank'.")
    kind: EquipmentKind = Field(  # type: ignore[valid-type]
        default="other", json_schema_extra=_labels(list(EQUIPMENT_KINDS.values()))
    )
    story: Id = Field(description="Building-model story it stands on.")
    x: Mm = Field(description="Centre of the footprint, plan X [mm].")
    y: Mm = Field(description="Centre of the footprint, plan Y [mm].")
    length: Length = Field(description="Footprint along its local x [mm].")
    width: Length = Field(description="Footprint along its local y [mm].")
    height: Length | None = None
    operatingWeight: float = Field(
        gt=0,
        title="Operating weight",
        description="Weight in operation, with its contents (water, oil, refrigerant) [kN].",
    )
    emptyWeight: float | None = Field(
        default=None,
        gt=0,
        title="Empty weight",
        description="Weight without its contents [kN]; empty: the operating weight.",
    )
    vibrating: bool = Field(
        default=False,
        description="Machinery whose operation imposes vibration or impact (BNBC 2020 Sec "
        "2.3.12): an impact allowance is added as live load (Table 6.2.6). Lifts always have it.",
    )
    impact: float | None = Field(
        default=None,
        ge=0,
        le=200,
        title="Impact allowance",
        description="Vertical impact load as a percentage of the operating weight, from the "
        "manufacturer; empty: BNBC 2020 Table 6.2.6 for the kind.",
    )
    rotation: float = Field(default=0, description="Of its local x from the global X [°].")
    loadAs: Literal["area", "points"] = Field(
        default="area",
        title="Load as",
        description="Area: spread uniformly over the footprint. Points: on its supports (the "
        "footprint corners unless given).",
        json_schema_extra=_labels(["Uniform over the footprint", "On its supports"]),
    )
    supports: list[Point2] = Field(
        default_factory=list,
        description="Support points in its local axes from the centre [x, y] mm, for 'points'; "
        "empty: the four corners of the footprint.",
    )
    plinth: Plinth | None = None

    @model_validator(mode="after")
    def _weights(self) -> Equipment:
        if self.emptyWeight is not None and self.emptyWeight > self.operatingWeight:
            raise ValueError(f"{self.id}: its empty weight exceeds its operating weight")
        return self


class OpeningPosition(_Model):
    """Where an opening is in its host: in a beam ``distance`` from the beam's start and
    ``elevation`` of its centre above the beam's bottom; in a slab the plan position ``x``,
    ``y`` of its centre; in a wall ``x`` along the wall from its start and ``y`` up from its
    bottom, to the centre."""

    distance: Mm | None = Field(default=None, description="Beam: from its start end [mm].")
    elevation: Mm | None = Field(
        default=None, description="Beam: centre above the beam's bottom [mm]."
    )
    x: Mm | None = Field(default=None, description="Slab: plan X; wall: along the wall [mm].")
    y: Mm | None = Field(default=None, description="Slab: plan Y; wall: up from its bottom [mm].")

    @model_validator(mode="after")
    def _pair(self) -> OpeningPosition:
        beam = self.distance is not None and self.elevation is not None
        plane = self.x is not None and self.y is not None
        if not (beam or plane):
            raise ValueError("give distance and elevation (beam) or x and y (slab, wall)")
        return self


class Opening(_Model):
    """A sleeve or opening through a beam, slab or wall for a service."""

    id: Id
    host: Id = Field(description="Building-model id of the beam, slab or wall it passes through.")
    kind: Literal["sleeve", "opening"] = Field(
        default="sleeve",
        json_schema_extra=_labels(["Sleeve (a pipe passing through)", "Opening"]),
    )
    shape: Literal["circle", "rectangle"] = Field(
        default="circle", json_schema_extra=_labels(["Circle", "Rectangle"])
    )
    diameter: Length | None = None
    width: Length | None = Field(
        default=None,
        description="Rectangle: along the beam or wall, or along X in a slab [mm].",
    )
    height: Length | None = Field(
        default=None,
        description="Rectangle: vertical in a beam or wall, or along Y in a slab [mm].",
    )
    position: OpeningPosition
    service: str = Field(default="", description="E.g. 'DN150 drain'.")

    @model_validator(mode="after")
    def _size(self) -> Opening:
        if self.shape == "circle" and self.diameter is None:
            raise ValueError(f"{self.id}: a circular opening needs its diameter")
        if self.shape == "rectangle" and (self.width is None or self.height is None):
            raise ValueError(f"{self.id}: a rectangular opening needs its width and height")
        return self

    @property
    def size(self) -> tuple[float, float]:
        """(width, height) [mm]: the diameter twice for a circle."""
        if self.shape == "circle":
            return float(self.diameter or 0.0), float(self.diameter or 0.0)
        return float(self.width or 0.0), float(self.height or 0.0)


class Shaft(_Model):
    """A vertical service shaft: a hole through the floors from one story up to another."""

    id: Id
    outline: list[Point2] = Field(min_length=3, description="Plan outline [mm].")
    fromStory: Id = Field(title="From story", description="Story it starts at (not cut).")
    toStory: Id = Field(title="To story", description="Highest story whose floor it cuts.")
    service: str = Field(default="")


class IfcModel(_Model):
    """An MEP model of the building services, an IFC file in the project."""

    path: str = Field(min_length=1, description="Project-relative path of the .ifc file.")
    discipline: Literal["mechanical", "plumbing", "fire", "electrical"] = Field(
        default="mechanical", json_schema_extra=_labels(list(DISCIPLINES.values()))
    )
    visible: bool = True


class MepModel(_Model):
    schema_: Literal["saengine.mep/1"] = Field(default=SCHEMA_ID, alias="schema")
    equipment: list[Equipment] = Field(default_factory=list)
    openings: list[Opening] = Field(default_factory=list)
    shafts: list[Shaft] = Field(default_factory=list)
    ifcModels: list[IfcModel] = Field(default_factory=list, title="IFC models")
    contentsAs: Literal["fluid", "live", "dead"] = Field(
        default="fluid",
        title="Contents as",
        description="Fluid: the contents (operating minus empty weight) are the fluid load F of "
        "BNBC 2020 2.7.3.1, in 1.4(D + F) and 1.2(D + F + T) + ... and not in the 0.9D "
        "combinations (live load until the analysis has an F case). Live: live load. Dead: "
        "superimposed dead load, also in the 0.9D combinations; only for contents that are "
        "always there.",
        json_schema_extra=_labels(["Fluid load F", "Live load", "Dead load (always full)"]),
    )

    @model_validator(mode="after")
    def _ids(self) -> MepModel:
        ids = [x.id for x in (*self.equipment, *self.openings, *self.shafts)]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate ids: {', '.join(duplicates)}")
        return self


def default_mep() -> MepModel:
    return MepModel()


def is_placeholder(data: Any) -> bool:
    """The file a new project starts with, before Part 7 had an editor."""
    return isinstance(data, dict) and data.get("schema") == 1 and data.get("part") == "mep"


def parse(text: str | None) -> MepModel:
    """The MEP model of a file's text; an empty one for a missing file or the placeholder.
    Raises ``ValueError`` (pydantic's ``ValidationError``) for an invalid file."""
    if not text or not text.strip():
        return default_mep()
    data = json.loads(text)
    if is_placeholder(data):
        return default_mep()
    return MepModel.model_validate(data)


def check(mep: MepModel, building: Any = None) -> list[str]:
    """Problems with what the MEP model refers to in the building model (stories, hosts)."""
    if building is None:
        return []
    stories = {s.id: s.elevation for s in building.stories}
    kinds = {e.id: e.kind for e in building.elements}
    problems = []
    for item in mep.equipment:
        if item.story not in stories:
            problems.append(f"{item.id}: no story '{item.story}'")
    for opening in mep.openings:
        kind = kinds.get(opening.host)
        if kind not in ("beam", "slab", "wall"):
            problems.append(f"{opening.id}: there is no beam, slab or wall '{opening.host}'")
            continue
        p = opening.position
        if kind == "beam" and (p.distance is None or p.elevation is None):
            problems.append(f"{opening.id}: a beam opening needs distance and elevation")
        if kind != "beam" and (p.x is None or p.y is None):
            problems.append(f"{opening.id}: a {kind} opening needs x and y")
    for shaft in mep.shafts:
        missing = [s for s in (shaft.fromStory, shaft.toStory) if s not in stories]
        if missing:
            problems.append(f"{shaft.id}: no story '{missing[0]}'")
        elif stories[shaft.toStory] <= stories[shaft.fromStory]:
            problems.append(f"{shaft.id}: its top story must be above the story it starts at")
    return problems
