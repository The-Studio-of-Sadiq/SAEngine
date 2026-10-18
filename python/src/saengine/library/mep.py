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
from saengine.plumbing.tables import OCCUPANCIES, OCCUPANCY_KEYS

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


# ─────────────────────────── plumbing (sized by saengine.plumbing) ───────────────────────────

PlumbingSystem = Literal[
    "coldWater", "hotWater", "soil", "waste", "soilWaste", "vent", "rainwater", "pumpMain"
]
PLUMBING_SYSTEMS = {
    "coldWater": "Cold water riser",
    "hotWater": "Hot water riser",
    "soil": "Soil stack",
    "waste": "Waste stack",
    "soilWaste": "Soil and waste stack",
    "vent": "Vent stack",
    "rainwater": "Rainwater leader",
    "pumpMain": "Pump main",
}
PipeMaterial = Literal["uPVC", "GI", "PPR", "HDPE", "CI"]
TankKind = Literal["overhead", "underground", "septic", "rainwater", "soakWell"]
TANK_KINDS = {
    "overhead": "Overhead water tank",
    "underground": "Underground reservoir",
    "septic": "Septic tank",
    "rainwater": "Rainwater storage tank",
    "soakWell": "Soak well (seepage pit)",
}
Occupancy = Literal[OCCUPANCY_KEYS]  # type: ignore[valid-type]


class PlumbingSupply(_Model):
    """The water source and what the supply sizing assumes."""

    source: Literal["mains", "deepTubewell"] = Field(
        default="mains",
        json_schema_extra=_labels(["City water main", "Deep tube well (DTW)"]),
    )
    mainsHead: float | None = Field(
        default=None,
        ge=0,
        title="Mains head",
        description="Residual head of the city main at the connection [m].",
    )
    pumpHours: float | None = Field(
        default=None,
        gt=0,
        le=24,
        title="Pumping hours",
        description="Hours a day the pump runs to fill the overhead tank; empty: the pump "
        "delivers the peak hourly demand (BNBC 2020 Part 8 Sec 5.9.1.2(c)(ii)).",
    )
    minResidualHead: float | None = Field(
        default=None,
        gt=0,
        title="Minimum residual head",
        description="At the fixtures [m]; empty: Table 8.5.6's flow pressure.",
    )
    facility: Literal["full", "restricted"] = Field(
        default="full",
        description="Column of Table 8.5.1 (full or restricted facility).",
        json_schema_extra=_labels(["Full facility", "Restricted facility"]),
    )
    flushValves: bool = Field(
        default=False,
        title="Flush valves",
        description="Water closets and urinals with flush valves (else flush tanks/cisterns).",
    )
    inflow: float | None = Field(
        default=None,
        gt=0,
        description="Flow of the source into the underground reservoir [l/min] (sizes its "
        "overflow, Table 8.5.3); empty: the peak hourly demand.",
    )
    fireReserve: float | None = Field(
        default=None,
        ge=0,
        title="Fire reserve",
        description="Water kept for fire fighting in each tank [m³]; empty: 1 hour of the "
        "Part 4 Table 4.4.1 standpipe flow for a tall building (Sec 5.9.1.2(c)), none else.",
    )
    feed: Literal["down", "up"] = Field(
        default="down",
        description="Down-feed from an overhead (roof) tank, or up-feed pumped from the "
        "reservoir or the main without a roof tank (no overhead tank is then proposed).",
        json_schema_extra=_labels(["Down-feed (overhead tank)", "Up-feed (pumped, no roof tank)"]),
    )


class OtherFixture(_Model):
    """A fixture the list does not name, with its units."""

    name: str = Field(min_length=1)
    supplyUnits: float = Field(default=0, ge=0, title="Supply units", description="wsfu.")
    drainageUnits: float = Field(
        default=0, ge=0, title="Drainage units", description="Table 8.6.12/8.6.13 units."
    )
    count: int = Field(default=1, ge=0)


class Fixtures(_Model):
    """Number of each plumbing fixture on a story."""

    wc: int = Field(default=0, ge=0, title="Water closets")
    urinal: int = Field(default=0, ge=0, title="Urinals")
    basin: int = Field(default=0, ge=0, title="Wash basins")
    shower: int = Field(default=0, ge=0, title="Showers")
    bathtub: int = Field(default=0, ge=0, title="Bathtubs")
    kitchenSink: int = Field(default=0, ge=0, title="Kitchen sinks")
    floorDrain: int = Field(default=0, ge=0, title="Floor drains")
    washingMachine: int = Field(default=0, ge=0, title="Washing machines")
    bidet: int = Field(default=0, ge=0, title="Bidets")
    other: list[OtherFixture] = Field(default_factory=list)


class PlumbingStory(_Model):
    """What a story holds: its occupancy, people and fixtures."""

    story: Id = Field(description="Building-model story.")
    occupancy: Occupancy = Field(  # type: ignore[valid-type]
        default="residentialFlat",
        description="Row of BNBC 2020 Table 8.5.1 (water consumption).",
        json_schema_extra=_labels([OCCUPANCIES[k].label for k in OCCUPANCY_KEYS]),
    )
    population: float | None = Field(
        default=None,
        ge=0,
        description="Persons (beds, seats for those rows); empty: 5 per dwelling (one per "
        "kitchen sink, Sec 5.6.3) or 7.4 m² per person for offices (Sec 5.6.4).",
    )
    fixtures: Fixtures = Field(default_factory=Fixtures)


class Riser(_Model):
    """A vertical pipe: a water riser, a soil, waste or vent stack, a leader or a pump main."""

    id: Id
    system: PlumbingSystem = Field(  # type: ignore[valid-type]
        json_schema_extra=_labels(list(PLUMBING_SYSTEMS.values()))
    )
    x: Mm = Field(description="Plan X [mm].")
    y: Mm = Field(description="Plan Y [mm].")
    fromStory: Id = Field(title="From story", description="Story it starts at (not cut).")
    toStory: Id = Field(title="To story", description="Highest story whose floor it cuts.")
    shaft: Id | None = Field(default=None, description="Shaft it runs in.")
    serves: list[Id] | None = Field(
        default=None, description="Stories it serves; empty: all it passes."
    )
    diameter: Length | None = Field(
        default=None, description="Nominal diameter [mm]; empty: sized by SAEngine."
    )
    material: PipeMaterial | None = None  # type: ignore[valid-type]


class PlumbingTank(_Model):
    """A water tank, septic tank or soak well; its weight and walls are the structure's."""

    id: Id
    kind: TankKind = Field(  # type: ignore[valid-type]
        json_schema_extra=_labels(list(TANK_KINDS.values()))
    )
    story: Id | None = Field(
        default=None, description="Story an overhead tank stands on; empty for ground tanks."
    )
    x: Mm = Field(description="Centre, plan X [mm].")
    y: Mm = Field(description="Centre, plan Y [mm].")
    length: Length | None = Field(default=None, description="Inside, along X [mm].")
    width: Length | None = Field(default=None, description="Inside, along Y [mm].")
    diameter: Length | None = Field(default=None, description="Soak well, inside [mm].")
    waterDepth: Length | None = Field(default=None, title="Water depth", description="[mm]")
    freeboard: Length | None = Field(default=None, description="Above the water [mm].")
    compartments: int | None = Field(default=None, ge=1)
    construction: Literal["rc", "masonry", "prefab"] = Field(
        default="rc", json_schema_extra=_labels(["Reinforced concrete", "Masonry", "Prefabricated"])
    )
    walls: Length | None = Field(default=None, description="Wall thickness [mm].")
    base: Length | None = Field(default=None, description="Base slab thickness [mm].")
    roof: Length | None = Field(default=None, description="Roof slab thickness [mm].")
    material: Id | None = Field(default=None, description="Concrete from 03 Materials.")
    rebar: Id | None = Field(default=None, description="Reinforcement from 03 Materials.")
    topLevel: Mm | None = Field(
        default=None, title="Top level", description="Ground tanks: top relative to ground [mm]."
    )
    sized: bool = Field(default=False, description="Dimensions proposed by SAEngine (editable).")
    toe: Length | None = Field(
        default=None,
        description="Ground tanks: projection of the base beyond the walls [mm] (flotation).",
    )
    equipment: Id | None = Field(
        default=None,
        description="Overhead tank: the 07 MEP equipment (kind tank) that already carries its "
        "weight in the analysis; empty: SAEngine loads the model with this tank.",
    )
    emptyWeight: float | None = Field(
        default=None,
        gt=0,
        title="Empty weight",
        description="Overhead tank: its own weight empty [kN], e.g. a prefab tank's from its "
        "maker; empty: computed (rc: the concrete; masonry: brick walls, concrete base and roof; "
        "prefab: nil).",
    )
    users: float | None = Field(
        default=None, ge=0, description="Septic tank: persons served; empty: the building's."
    )
    flow: float | None = Field(
        default=None, gt=0, description="Septic tank: waste water flow [lpcd]; empty: Appendix S."
    )
    desludging: float | None = Field(
        default=None, gt=0, description="Septic tank: desludging interval [years]; empty: 1."
    )
    retention: float | None = Field(
        default=None, gt=0, description="Septic tank: liquid retention time [days]; empty: 1."
    )
    percolation: float | None = Field(
        default=None,
        gt=0,
        description="Soak well: percolation test rate [minutes for 25 mm]; empty: estimated "
        "from 01 Soil Report.",
    )


class RoofDrain(_Model):
    id: Id
    x: Mm = Field(description="Plan X [mm].")
    y: Mm = Field(description="Plan Y [mm].")
    story: Id = Field(description="Roof story it drains.")
    area: float | None = Field(
        default=None, gt=0, description="Catchment [m²]; empty: its share of the roof slab."
    )


class Harvest(_Model):
    """Rainwater harvesting storage (BNBC 2020 Part 8 Sec 7.8.9)."""

    demand: float = Field(gt=0, description="Rainwater demand [lpcd].")
    purpose: Literal["potable", "other"] = Field(
        default="other",
        description="Potable (drinking, cooking, bathing, ablution): 90 days; other: 210.",
        json_schema_extra=_labels(["Potable uses (90 days)", "Other uses (210 days)"]),
    )
    days: float | None = Field(default=None, gt=0, description="Overrides the purpose's days.")
    population: float | None = Field(default=None, ge=0, description="Empty: the building's.")
    floating: float = Field(default=0, ge=0, description="Floating storage added [m³].")


class PlumbingRoof(_Model):
    rainfallIntensity: float | None = Field(
        default=None,
        gt=0,
        title="Rainfall intensity",
        description="One-hour rainfall [mm/h], BNBC 2020 Part 8 Appendix R; empty: Dhaka, 88.",
    )
    drains: list[RoofDrain] = Field(default_factory=list)
    plotArea: float | None = Field(
        default=None, gt=0, title="Plot area", description="[m²]: harvesting from 300 (Sec 7.4.1)."
    )
    harvest: Harvest | None = None


class Plumbing(_Model):
    """The plumbing the structure coordinates with (BNBC 2020 Part 8)."""

    supply: PlumbingSupply = Field(default_factory=PlumbingSupply)
    stories: list[PlumbingStory] = Field(default_factory=list)
    risers: list[Riser] = Field(default_factory=list)
    tanks: list[PlumbingTank] = Field(default_factory=list)
    roof: PlumbingRoof | None = None
    disposal: Literal["septic", "publicSewer"] = Field(
        default="septic",
        description="Sewage to a septic tank and soak well, or to a public sewer.",
        json_schema_extra=_labels(["Septic tank and soak well", "Public sewer"]),
    )
    drainSlope: float = Field(
        default=0.01,
        gt=0,
        le=0.1,
        title="Drain slope",
        description="Of the building drain and storm drain (0.01 = 1 in 100).",
    )

    @model_validator(mode="after")
    def _ids(self) -> Plumbing:
        drains = self.roof.drains if self.roof else []
        ids = [x.id for x in (*self.risers, *self.tanks, *drains)]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate plumbing ids: {', '.join(duplicates)}")
        stories = [s.story for s in self.stories]
        twice = sorted({s for s in stories if stories.count(s) > 1})
        if twice:
            raise ValueError(f"plumbing stories listed twice: {', '.join(twice)}")
        return self


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
    plumbing: Plumbing | None = Field(
        default=None,
        description="Water supply, drainage, rainwater and tanks, sized to BNBC 2020 Part 8.",
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
    if mep.plumbing is not None:
        problems.extend(_plumbing_references(mep, stories))
    return problems


def _plumbing_references(mep: MepModel, stories: dict[str, float]) -> list[str]:
    """Problems with the stories and shafts the plumbing refers to."""
    plumbing = mep.plumbing
    assert plumbing is not None
    problems = []
    shafts = {s.id for s in mep.shafts}
    for entry in plumbing.stories:
        if entry.story not in stories:
            problems.append(f"plumbing: no story '{entry.story}'")
    for riser in plumbing.risers:
        missing = [
            s for s in (riser.fromStory, riser.toStory, *(riser.serves or [])) if s not in stories
        ]
        if missing:
            problems.append(f"{riser.id}: no story '{missing[0]}'")
        elif stories[riser.toStory] <= stories[riser.fromStory]:
            problems.append(f"{riser.id}: its top story must be above the story it starts at")
        if riser.shaft is not None and riser.shaft not in shafts:
            problems.append(f"{riser.id}: no shaft '{riser.shaft}'")
    for tank in plumbing.tanks:
        if tank.story is not None and tank.story not in stories:
            problems.append(f"{tank.id}: no story '{tank.story}'")
        if tank.kind == "overhead" and tank.story is None:
            problems.append(f"{tank.id}: an overhead tank needs the story it stands on")
        if tank.equipment is not None and not any(
            e.id == tank.equipment and e.kind == "tank" for e in mep.equipment
        ):
            problems.append(f"{tank.id}: no equipment tank '{tank.equipment}'")
    for drain in plumbing.roof.drains if plumbing.roof else []:
        if drain.story not in stories:
            problems.append(f"{drain.id}: no story '{drain.story}'")
    return problems
