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

from saengine.electrical.tables import USE_KEYS as ELECTRICAL_USE_KEYS
from saengine.electrical.tables import USES as ELECTRICAL_USES
from saengine.fire.tables import HAZARD_LABELS as FIRE_HAZARDS  # BNBC Table 4.4.1 hazards
from saengine.hvac.constructions import GLAZING_KEYS, GLAZINGS, ROOF_KEYS, ROOFS, WALL_KEYS, WALLS
from saengine.hvac.tables import STATION_KEYS, STATIONS, VENTILATION, VENTILATION_KEYS
from saengine.library.labels import field_title
from saengine.library.materials import Id
from saengine.mep.uses import STORY_USE_KEYS, STORY_USES
from saengine.plumbing.tables import (
    OCCUPANCIES,
    OCCUPANCY_KEYS,
    WET_ROOM_KINDS,
)

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


# ─────────────────────── coordination (clash tests, issues, BCF, IDS) ───────────────────────

#: The element sets a clash test compares: SAEngine's own structure and architecture (exported
#: to IFC from the building model and the floor plan), the MEP IFC models by discipline, and the
#: other IFC models of the coordination (an architect's or a consultant's file).
ClashSet = Literal[
    "structure", "architecture", "mechanical", "plumbing", "fire", "electrical", "external"
]
CLASH_SETS = {
    "structure": "Structure (building model)",
    "architecture": "Architecture (floor plan)",
    "mechanical": "Mechanical (HVAC) models",
    "plumbing": "Plumbing models",
    "fire": "Fire protection models",
    "electrical": "Electrical models",
    "external": "Other IFC models",
}
#: The status workflow of a coordination issue (BCF's TopicStatus).
IssueStatus = Literal["new", "active", "reviewed", "approved", "resolved", "closed"]
ISSUE_STATUSES = {
    "new": "New",
    "active": "Active",
    "reviewed": "Reviewed",
    "approved": "Approved (accepted as is)",
    "resolved": "Resolved",
    "closed": "Closed",
}
IssuePriority = Literal["low", "normal", "high", "critical"]


class CoordinationModel(_Model):
    """An IFC model taking part in the coordination besides the MEP models (an architect's or
    another consultant's file)."""

    path: str = Field(min_length=1, description="Project-relative path of the .ifc file.")
    name: str = Field(default="")
    visible: bool = True


class ClashTest(_Model):
    """A clash rule: every element of the sets ``a`` against every element of the sets ``b``,
    either intersecting (hard) or closer than the clearance."""

    id: Id
    name: str = Field(default="")
    a: list[ClashSet] = Field(min_length=1, title="Set A")
    b: list[ClashSet] = Field(min_length=1, title="Set B")
    kind: Literal["hard", "clearance"] = Field(
        default="hard", json_schema_extra=_labels(["Hard (intersecting)", "Clearance"])
    )
    clearance: Mm = Field(default=0.0, ge=0, description="Least gap for a clearance test [mm].")
    tolerance: Mm = Field(
        default=2.0, ge=0, description="Least overlap reported as a hard clash [mm]."
    )
    ignoreSameModel: bool = Field(
        default=False,
        title="Ignore within one model",
        description="Skip pairs from the same IFC model (a model's own fittings touch).",
    )
    enabled: bool = True


class IssueComment(_Model):
    guid: str = Field(default="")
    date: str = Field(default="", description="ISO 8601 date and time.")
    author: str = Field(default="")
    text: str = Field(default="")


class Issue(_Model):
    """A coordination issue: a clash found by a test, a failed IDS requirement, or a topic
    imported from BCF. ``key`` matches a clash again on the next run (test and the two
    elements' GlobalIds)."""

    id: Id
    guid: str = Field(default="", description="BCF topic GUID.")
    title: str = Field(default="")
    source: Literal["clash", "ids", "bcf", "manual"] = "clash"
    key: str = Field(default="", description="test:globalIdA:globalIdB for a clash.")
    test: str | None = None
    status: IssueStatus = Field(
        default="new", json_schema_extra=_labels(list(ISSUE_STATUSES.values()))
    )
    priority: IssuePriority = "normal"
    assignedTo: str = Field(default="", title="Assigned to")
    dueDate: str = Field(default="", title="Due date")
    description: str = Field(default="")
    elements: list[str] = Field(default_factory=list, description="IFC GlobalIds.")
    point: list[float] | None = Field(default=None, description="[x, y, z] in mm.")
    story: str | None = None
    created: str = Field(default="")
    modified: str = Field(default="")
    comments: list[IssueComment] = Field(default_factory=list)


class Coordination(_Model):
    """Multi-discipline coordination: the other IFC models, the clash tests, the IDS files the
    models are checked against, and the issues with their status workflow (exchanged as BCF)."""

    models: list[CoordinationModel] = Field(default_factory=list, title="IFC models")
    tests: list[ClashTest] = Field(default_factory=list, title="Clash tests")
    idsFiles: list[str] = Field(
        default_factory=list, title="IDS files", description="Project-relative .ids paths."
    )
    issues: list[Issue] = Field(default_factory=list)
    author: str = Field(default="", description="Author of new issues and comments (BCF).")

    @model_validator(mode="after")
    def _unique(self) -> Coordination:
        for name, ids in (
            ("tests", [t.id for t in self.tests]),
            ("issues", [i.id for i in self.issues]),
        ):
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate {name}: {', '.join(duplicates)}")
        return self


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
    fixturesFrom: Literal["auto", "rooms", "typed"] = Field(
        default="auto",
        title="Fixtures from",
        description="Where the story's fixtures come from: the wet rooms of the architecture "
        "(05 Floor Plan/architecture.json) or the counts typed here. Auto: the typed counts when "
        "any is given (they override the rooms), else the rooms.",
        json_schema_extra=_labels(
            ["Auto (typed counts override the rooms)", "The architecture's wet rooms", "Typed"]
        ),
    )


WetRoomKind = Literal[tuple(WET_ROOM_KINDS)]  # type: ignore[valid-type]


class RoomFixtures(_Model):
    """The fixtures every wet room of a kind holds in this project (replacing SAEngine's
    defaults for the kind)."""

    kind: WetRoomKind = Field(  # type: ignore[valid-type]
        json_schema_extra=_labels(list(WET_ROOM_KINDS.values()))
    )
    fixtures: Fixtures = Field(default_factory=Fixtures)


class WetRoom(_Model):
    """One wet room of the architecture given its own kind or its own fixtures."""

    room: Id = Field(description="Room id in 05 Floor Plan/architecture.json.")
    kind: WetRoomKind | None = Field(  # type: ignore[valid-type]
        default=None,
        description="Empty: found from the room's name.",
        json_schema_extra=_labels(list(WET_ROOM_KINDS.values())),
    )
    fixtures: Fixtures | None = Field(default=None, description="Empty: those of its kind.")


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
    roomFixtures: list[RoomFixtures] = Field(
        default_factory=list,
        title="Fixtures per wet room",
        description="The fixtures of each kind of wet room; a kind not listed has SAEngine's "
        "defaults.",
    )
    wetRooms: list[WetRoom] = Field(
        default_factory=list,
        title="Wet rooms",
        description="Wet rooms of the architecture given their own kind or fixtures.",
    )
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
        for name, keys in (
            ("roomFixtures kinds", [r.kind for r in self.roomFixtures]),
            ("wetRooms rooms", [r.room for r in self.wetRooms]),
        ):
            twice = sorted({k for k in keys if keys.count(k) > 1})
            if twice:
                raise ValueError(f"duplicate plumbing {name}: {', '.join(twice)}")
        stories = [s.story for s in self.stories]
        twice = sorted({s for s in stories if stories.count(s) > 1})
        if twice:
            raise ValueError(f"plumbing stories listed twice: {', '.join(twice)}")
        return self


# ──────────────────────────── hvac (cooling loads by saengine.hvac) ────────────────────────────

HvacUse = Literal[VENTILATION_KEYS]  # type: ignore[valid-type]
HvacCity = Literal[STATION_KEYS]  # type: ignore[valid-type]
HVAC_SYSTEMS = {
    "vrf": "Variable refrigerant flow (VRF)",
    "chilledWater": "Chilled water (chillers, AHUs, FCUs)",
    "split": "Split air-conditioners",
    "packaged": "Packaged units",
    "none": "None (naturally ventilated)",
}
HVAC_PLANT_KINDS = {
    "chiller": "Chiller",
    "coolingTower": "Cooling tower",
    "ahu": "Air handling unit",
    "fcu": "Fan coil unit",
    "vrfOutdoor": "VRF outdoor unit",
    "splitOutdoor": "Split outdoor unit",
    "pump": "Pump",
    "exhaustFan": "Exhaust fan",
    "freshAirUnit": "Fresh air unit",
}
DUCT_SYSTEMS = {
    "supply": "Supply air",
    "return": "Return air",
    "exhaust": "Exhaust air",
    "freshAir": "Fresh air",
    "kitchenExhaust": "Kitchen exhaust",
    "smoke": "Smoke extract",
}


class HvacDesign(_Model):
    """The design conditions (BNBC 2020 Part 8 Sec 2.7.2 and 2.12.2)."""

    city: HvacCity | None = Field(  # type: ignore[valid-type]
        default=None,
        description="Station of Table 8.2.2 (outside design conditions); empty: the Project "
        "Settings site, else Dhaka.",
        json_schema_extra=_labels([STATIONS[k].name for k in STATION_KEYS]),
    )
    outdoorDB: float | None = Field(
        default=None,
        title="Outdoor dry bulb",
        description="[°C]; empty: the station's 2 % dry bulb (Sec 2.12.2.1).",
    )
    outdoorWB: float | None = Field(
        default=None,
        title="Outdoor wet bulb",
        description="Mean coincident wet bulb [°C]; empty: the station's 2 % MWB.",
    )
    indoorDB: float | None = Field(
        default=None,
        title="Indoor dry bulb",
        description="[°C]; empty: 24 °C (Sec 2.12.2.2) within the use's Table 8.2.1 range.",
    )
    indoorRH: float | None = Field(
        default=None,
        gt=0,
        lt=100,
        title="Indoor relative humidity",
        description="[%]; empty: the upper value of the use's Table 8.2.1 range (Sec 2.12.2.3).",
    )
    dailyRange: float | None = Field(
        default=None,
        ge=0,
        title="Daily range",
        description="Of the outdoor dry bulb [°C]; empty: Table 8.2.2 column 14.",
    )


class HvacEnvelope(_Model):
    """The building envelope's constructions (typical Bangladeshi, EnergyPlus data sets)."""

    wall: Literal[WALL_KEYS] = Field(  # type: ignore[valid-type]
        default="brick250", json_schema_extra=_labels([WALLS[k].label for k in WALL_KEYS])
    )
    roof: Literal[ROOF_KEYS] = Field(  # type: ignore[valid-type]
        default="rcLimeTerracing", json_schema_extra=_labels([ROOFS[k].label for k in ROOF_KEYS])
    )
    glazing: Literal[GLAZING_KEYS] = Field(  # type: ignore[valid-type]
        default="singleClear",
        json_schema_extra=_labels([GLAZINGS[k].label for k in GLAZING_KEYS]),
    )
    uWall: float | None = Field(
        default=None, gt=0, title="Wall U-value", description="Overrides the wall's [W/m²K]."
    )
    uRoof: float | None = Field(
        default=None, gt=0, title="Roof U-value", description="Overrides the roof's [W/m²K]."
    )
    uGlazing: float | None = Field(
        default=None, gt=0, title="Glazing U-value", description="Overrides the glass's [W/m²K]."
    )
    shgc: float | None = Field(
        default=None,
        gt=0,
        lt=1,
        title="SHGC",
        description="Solar heat gain coefficient of the glazing; overrides the glass's.",
    )
    shading: Literal["none", "overhang", "blinds"] = Field(
        default="none",
        description="Overhang: a sunshade over every window 0.234 x its height deep (BNBC 2020 "
        "Part 3 Sec 4.4.3.1). Blinds: interior blinds, always drawn.",
        json_schema_extra=_labels(["None", "Overhangs (Part 3 Sec 4.4.3.1)", "Interior blinds"]),
    )


class FacadeGlazing(_Model):
    """Window-to-wall ratio of each facade (0 to 0.9); empty: 0.2 (BNBC 2020 Part 3 Sec
    4.5.1.2(a))."""

    N: float | None = Field(default=None, ge=0, le=0.9)
    E: float | None = Field(default=None, ge=0, le=0.9)
    S: float | None = Field(default=None, ge=0, le=0.9)
    W: float | None = Field(default=None, ge=0, le=0.9)


class HvacStory(_Model):
    """A story's use and internal gains for the cooling load."""

    story: Id = Field(description="Building-model story.")
    conditioned: bool = True
    use: HvacUse = Field(  # type: ignore[valid-type]
        default="officeSpace",
        description="Row of BNBC 2020 Part 8 Table 8.2.3 (ventilation and occupant density).",
        json_schema_extra=_labels([VENTILATION[k].label for k in VENTILATION_KEYS]),
    )
    occupants: float | None = Field(
        default=None, ge=0, description="Persons; empty: Table 8.2.3's default density."
    )
    lighting: float | None = Field(
        default=None, ge=0, description="[W/m²]; empty: Part 3 Table 3.4.5's maximum."
    )
    equipment: float | None = Field(
        default=None, ge=0, description="Plug loads [W/m²]; empty: SAEngine's value for the use."
    )
    glazing: FacadeGlazing = Field(default_factory=FacadeGlazing)
    gainsFrom: Literal["auto", "rooms", "typed"] = Field(
        default="auto",
        title="Gains from",
        description="Where the story's occupants, gains and outdoor air come from: the rooms "
        "of the architecture (their areas and uses) or the use and values typed here. Auto: "
        "the rooms where the story has any; typed occupants, lighting and equipment still "
        "override.",
        json_schema_extra=_labels(["Auto (the rooms where drawn)", "The rooms", "Typed"]),
    )


class HvacPlant(_Model):
    """A piece of HVAC plant: its weight is a load on the structure (through 07 MEP equipment)."""

    id: Id
    kind: Literal[tuple(HVAC_PLANT_KINDS)] = Field(  # type: ignore[valid-type]
        json_schema_extra=_labels(list(HVAC_PLANT_KINDS.values()))
    )
    story: Id = Field(description="Building-model story it stands on.")
    x: Mm = Field(description="Centre, plan X [mm].")
    y: Mm = Field(description="Centre, plan Y [mm].")
    length: Length | None = None
    width: Length | None = None
    height: Length | None = None
    capacity: float | None = Field(
        default=None, gt=0, description="Cooling [kW], or air flow [m³/s] for fans."
    )
    operatingWeight: float | None = Field(
        default=None, gt=0, title="Operating weight", description="[kN]"
    )
    sized: bool = Field(default=False, description="Proposed by SAEngine (editable).")
    serves: list[Id] | None = Field(default=None, description="Stories it serves.")
    power: float | None = Field(
        default=None,
        gt=0,
        title="Electrical power",
        description="Input [kW] for the electrical demand; empty: estimated from its capacity.",
    )
    equipment: Id | None = Field(
        default=None,
        description="The 07 MEP equipment that already carries its weight in the analysis; "
        "empty: SAEngine loads the model with this item (unless an equipment stands there).",
    )


class DuctRiser(_Model):
    fromStory: Id = Field(title="From story")
    toStory: Id = Field(title="To story")


class Duct(_Model):
    """A duct run: horizontal in plan on a story, or a riser at its first point."""

    id: Id
    system: Literal[tuple(DUCT_SYSTEMS)] = Field(  # type: ignore[valid-type]
        default="supply", json_schema_extra=_labels(list(DUCT_SYSTEMS.values()))
    )
    shape: Literal["rect", "round"] = Field(
        default="rect", json_schema_extra=_labels(["Rectangular", "Round"])
    )
    width: Length | None = None
    height: Length | None = None
    diameter: Length | None = None
    story: Id = Field(description="Building-model story.")
    path: list[Point2] = Field(min_length=1, description="Plan points [mm].")
    bottom: Mm | None = Field(
        default=None,
        description="Underside above the story's floor [mm]; empty: just below the slab soffit.",
    )
    riser: DuctRiser | None = None
    shaft: Id | None = None
    flow: float | None = Field(default=None, gt=0, description="[m³/s]")


class Hvac(_Model):
    """Air-conditioning and ventilation the structure coordinates with (BNBC 2020 Part 8
    Chapter 2): cooling loads, plant weights, ducts through the structure."""

    system: Literal[tuple(HVAC_SYSTEMS)] = Field(  # type: ignore[valid-type]
        default="split", json_schema_extra=_labels(list(HVAC_SYSTEMS.values()))
    )
    design: HvacDesign = Field(default_factory=HvacDesign)
    envelope: HvacEnvelope = Field(default_factory=HvacEnvelope)
    stories: list[HvacStory] = Field(default_factory=list)
    plant: list[HvacPlant] = Field(default_factory=list)
    ducts: list[Duct] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ids(self) -> Hvac:
        ids = [x.id for x in (*self.plant, *self.ducts)]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate hvac ids: {', '.join(duplicates)}")
        stories = [s.story for s in self.stories]
        twice = sorted({s for s in stories if stories.count(s) > 1})
        if twice:
            raise ValueError(f"hvac stories listed twice: {', '.join(twice)}")
        return self


def hvac_references(mep: MepModel, stories: dict[str, float]) -> list[str]:
    """Problems with the stories and shafts the hvac section refers to (``stories``: building
    story id -> elevation)."""
    hvac = mep.hvac
    if hvac is None:
        return []
    problems = []
    shafts = {s.id for s in mep.shafts}
    for entry in hvac.stories:
        if entry.story not in stories:
            problems.append(f"hvac: no story '{entry.story}'")
    for item in hvac.plant:
        missing = [s for s in (item.story, *(item.serves or [])) if s not in stories]
        if missing:
            problems.append(f"{item.id}: no story '{missing[0]}'")
    for duct in hvac.ducts:
        names = [duct.story, *((duct.riser.fromStory, duct.riser.toStory) if duct.riser else ())]
        missing = [s for s in names if s not in stories]
        if missing:
            problems.append(f"{duct.id}: no story '{missing[0]}'")
        elif duct.riser and stories[duct.riser.toStory] <= stories[duct.riser.fromStory]:
            problems.append(f"{duct.id}: its riser's top story must be above its start")
        if duct.shaft is not None and duct.shaft not in shafts:
            problems.append(f"{duct.id}: no shaft '{duct.shaft}'")
    return problems


# ────────────────────── electrical (coordinated by saengine.electrical) ──────────────────────

ElectricalUse = Literal[ELECTRICAL_USE_KEYS]  # type: ignore[valid-type]
ElectricalEquipmentKind = Literal[
    "transformer", "switchgear", "lvPanel", "generator", "fuelTank", "ups", "battery",
    "capacitorBank", "distributionBoard", "solarPv",
]  # fmt: skip
ELECTRICAL_EQUIPMENT_KINDS = {
    "transformer": "Transformer",
    "switchgear": "HT switchgear",
    "lvPanel": "LT panel",
    "generator": "Generator",
    "fuelTank": "Fuel tank",
    "ups": "UPS",
    "battery": "Battery bank",
    "capacitorBank": "Capacitor bank",
    "distributionBoard": "Distribution board",
    "solarPv": "Solar PV array",
}
ELECTRICAL_RISER_KINDS = {
    "busbar": "Busbar trunking",
    "cableTray": "Cable tray",
    "cableLadder": "Cable ladder",
    "conduitBank": "Conduit bank",
}
ELECTRICAL_ROOM_KINDS = {
    "substation": "Substation (HT, transformer and LT rooms)",
    "transformer": "Transformer room",
    "generator": "Generator room",
    "lvRoom": "LT switch room",
    "ups": "UPS and battery room",
}
MOTOR_KINDS = {
    "lift": "Lift",
    "pump": "Water pump",
    "firePump": "Fire pump",
    "fan": "Fan (ventilation)",
    "other": "Other motor",
}


class ElectricalSupply(_Model):
    """The supply and what the sizing assumes."""

    utility: str | None = Field(default=None, description="Distribution company, e.g. 'DPDC'.")
    voltage: Literal["11kV", "33kV", "0.4kV"] | None = Field(
        default=None,
        description="Supply voltage; empty: 11 kV with a substation when the load is 50 kW or "
        "more (BNBC 2020 Part 8 Sec 1.3.20.1(e)), else 0.4 kV.",
        json_schema_extra=_labels(["11 kV (HT)", "33 kV (HT)", "0.4 kV (LT)"]),
    )
    generator: bool = Field(default=False, description="A standby generator (Sec 1.3.19).")
    ups: bool = Field(default=False, title="UPS", description="A UPS (Sec 1.3.19.5).")
    powerFactor: float | None = Field(
        default=None,
        gt=0.5,
        le=1,
        title="Power factor",
        description="Of the maximum demand (kVA = kW / pf); empty: 0.85 (SAEngine practice, "
        "BNBC gives none).",
    )
    loadFactor: float | None = Field(
        default=None,
        ge=0.8,
        le=1,
        title="Load factor",
        description="Applied to the connected load for the substation rating; at least 0.8 "
        "(Sec 1.3.18.1); empty: 0.8.",
    )
    growth: float = Field(
        default=0,
        ge=0,
        le=200,
        description="Future expansion added to the maximum demand [%] (Sec 1.3.18.1).",
    )
    transformers: int | None = Field(
        default=None, ge=1, le=6, description="Number of transformers; empty: SAEngine chooses."
    )
    transformerType: Literal["oil", "dry"] = Field(
        default="oil",
        title="Transformer type",
        description="Oil-immersed or cast resin dry type (dry for hospitals, shopping centres "
        "and where fire must not spread, Sec 1.3.18.4).",
        json_schema_extra=_labels(["Oil type, natural cooled", "Cast resin dry type"]),
    )
    essentialShare: float | None = Field(
        default=None,
        ge=0,
        le=1,
        title="Essential share",
        description="Share of the lighting and power load on the generator; empty: 0.25 "
        "(SAEngine practice).",
    )
    essentialLoad: float = Field(
        default=0, ge=0, title="Other essential load", description="Added to the generator [kW]."
    )
    fuelHours: float | None = Field(
        default=None,
        gt=0,
        le=168,
        title="Fuel hours",
        description="Hours of full-load running the fuel tank holds; empty: 8 (SAEngine "
        "practice, BNBC gives none).",
    )
    upsLoad: float | None = Field(
        default=None, gt=0, title="UPS load", description="Load on the UPS [kW]."
    )
    upsAutonomy: float | None = Field(
        default=None, gt=0, title="UPS autonomy", description="Battery time [min]; empty: 15."
    )


class ElectricalStory(_Model):
    """What a story draws: its use (BNBC Table 8.1.17), unit loads and other loads."""

    story: Id = Field(description="Building-model story.")
    use: ElectricalUse = Field(  # type: ignore[valid-type]
        default="office",
        description="Row of BNBC 2020 Part 8 Table 8.1.17 (minimum load densities).",
        json_schema_extra=_labels([ELECTRICAL_USES[k].label for k in ELECTRICAL_USE_KEYS]),
    )
    airConditioned: bool | None = Field(
        default=None,
        title="Air conditioned",
        description="The A/C column of Table 8.1.17; empty: as 07 MEP hvac (conditioned), else "
        "not. With hvac plant entered, the plant's electrical load replaces the A/C column.",
    )
    lighting: float | None = Field(default=None, ge=0, description="Lighting [W/m²].")
    power: float | None = Field(default=None, ge=0, description="Socket outlets, power [W/m²].")
    other: float | None = Field(default=None, ge=0, description="Other loads of the story [kW].")
    area: float | None = Field(
        default=None, gt=0, description="Floor area [m²]; empty: the story's slabs in 06 BIM."
    )


class Motor(_Model):
    """Lifts, pumps and fans the building's load must include (Sec 1.3.2)."""

    id: Id
    kind: Literal["lift", "pump", "firePump", "fan", "other"] = Field(
        default="other", json_schema_extra=_labels(list(MOTOR_KINDS.values()))
    )
    power: float = Field(gt=0, description="Rated power of one [kW].")
    count: int = Field(default=1, ge=1)
    essential: bool | None = Field(
        default=None,
        description="On the standby generator; empty: lifts, pumps and fire pumps are.",
    )


class ElectricalEquipment(_Model):
    """A transformer, panel, generator, tank or battery standing on a floor."""

    id: Id
    kind: ElectricalEquipmentKind = Field(  # type: ignore[valid-type]
        json_schema_extra=_labels(list(ELECTRICAL_EQUIPMENT_KINDS.values()))
    )
    name: str = Field(default="")
    story: Id = Field(description="Building-model story it stands on.")
    x: Mm = Field(description="Centre, plan X [mm].")
    y: Mm = Field(description="Centre, plan Y [mm].")
    length: Length | None = Field(default=None, description="Along X [mm].")
    width: Length | None = Field(default=None, description="Along Y [mm].")
    height: Length | None = None
    rating: float | None = Field(
        default=None, gt=0, description="kVA (transformer, generator, UPS), kW (PV), A (panel)."
    )
    operatingWeight: float | None = Field(
        default=None,
        gt=0,
        title="Operating weight",
        description="With oil or fuel [kN]; empty: typical for the rating.",
    )
    emptyWeight: float | None = Field(
        default=None,
        gt=0,
        title="Empty weight",
        description="Without its fuel or oil [kN] (the contents load as 07 MEP contentsAs); "
        "empty: a transformer's from its oil, else the operating weight.",
    )
    vibrating: bool | None = Field(
        default=None, description="Imposes vibration (BNBC 2.3.12); empty: generators do."
    )
    oil: float | None = Field(default=None, ge=0, description="Transformer oil [litres].")
    sized: bool = Field(default=False, description="Proposed by SAEngine (editable).")
    equipment: Id | None = Field(
        default=None,
        description="The 07 MEP equipment that already carries its weight in the analysis; "
        "empty: SAEngine loads the model with this item (unless an equipment stands there).",
    )


class ElectricalRiser(_Model):
    """A rising main: busbar trunking, or cables on a tray, ladder or in conduits."""

    id: Id
    kind: Literal["busbar", "cableTray", "cableLadder", "conduitBank"] = Field(
        default="busbar", json_schema_extra=_labels(list(ELECTRICAL_RISER_KINDS.values()))
    )
    x: Mm = Field(description="Centre, plan X [mm].")
    y: Mm = Field(description="Centre, plan Y [mm].")
    width: Length | None = Field(default=None, description="Along X [mm]; empty: sized.")
    depth: Length | None = Field(default=None, description="Along Y [mm]; empty: sized.")
    fromStory: Id = Field(title="From story", description="Story it starts at (not cut).")
    toStory: Id = Field(title="To story", description="Highest story whose floor it cuts.")
    shaft: Id | None = Field(default=None, description="Shaft it runs in.")
    serves: list[Id] | None = Field(
        default=None, description="Stories it feeds; empty: all it passes."
    )
    rating: float | None = Field(default=None, gt=0, description="[A]; empty: sized.")


class CableTray(_Model):
    """A horizontal cable tray under a floor."""

    id: Id
    story: Id = Field(description="Story whose ceiling space it runs in.")
    path: list[Point2] = Field(min_length=2, description="Plan path [[x, y], ...] mm.")
    width: Length
    height: Length = Field(default=100, description="Side height [mm].")
    bottom: Mm | None = Field(
        default=None,
        description="Underside above the story's floor [mm]; empty: below the slab soffit "
        "with 150 mm to lay the cables.",
    )
    cableArea: float | None = Field(
        default=None,
        gt=0,
        title="Cable area",
        description="Sum of the cables' cross-sections (outside diameter) [mm²]: checks the fill.",
    )


class ElectricalRoom(_Model):
    """A substation, transformer, generator, LT or UPS room: its outline is checked."""

    id: Id
    kind: Literal["substation", "transformer", "generator", "lvRoom", "ups"] = Field(
        json_schema_extra=_labels(list(ELECTRICAL_ROOM_KINDS.values()))
    )
    story: Id
    outline: list[Point2] = Field(min_length=3, description="Inside face of the walls [mm].")
    height: Length | None = Field(default=None, description="Clear height [mm]; empty: story's.")


class Lightning(_Model):
    """Lightning protection and earthing (BNBC 2020 Part 8 Sec 1.3.33)."""

    enabled: bool = True
    level: Literal["I", "II", "III", "IV"] | None = Field(
        default=None,
        description="IEC 62305 protection level, when the design follows it (BNBC uses none); "
        "its mesh and down-conductor spacing then govern where stricter.",
    )
    downConductors: Literal["structuralRebar", "dedicated"] = Field(
        default="structuralRebar",
        title="Down conductors",
        description="The columns' continuous reinforcement, or dedicated copper conductors.",
        json_schema_extra=_labels(["Column reinforcement (natural)", "Dedicated copper"]),
    )
    earthing: Literal["foundation", "rods", "ring"] = Field(
        default="foundation",
        description="Foundation earth electrode, rods (pipes) or a ring conductor.",
        json_schema_extra=_labels(["Foundation reinforcement", "Rods or pipes", "Ring conductor"]),
    )
    airTerminals: list[Annotated[list[float], Field(min_length=3, max_length=3)]] | None = Field(
        default=None,
        title="Air terminals",
        description="[x, y, z] mm; empty: proposed by SAEngine.",
    )
    construction: Literal[
        "steelNonmetalRoof", "rcNonmetalRoof", "masonry", "metalRoof", "timber", "thatch"
    ] = Field(default="rcNonmetalRoof", description="Table 8.1.27(a) index B.")
    contents: Literal["ordinary", "susceptible", "power", "key", "people"] | None = Field(
        default=None, description="Table 8.1.27(b) index C; empty: from the stories' use."
    )
    isolation: Literal["builtUp", "few", "isolated"] = Field(
        default="builtUp", description="Table 8.1.27(b) index D."
    )
    terrain: Literal["flat", "hilly", "mountainous"] = Field(
        default="flat", description="Table 8.1.27(b) index E."
    )
    thunderstormDays: float | None = Field(
        default=None,
        ge=0,
        title="Thunderstorm days",
        description="A year (Table 8.1.27(c) index G); empty: over 21 (BNBC Table 8.1.28's "
        "examples).",
    )
    rule: Literal["perimeter", "area"] = Field(
        default="perimeter",
        description="Down conductors: one for every 30 m of perimeter, or by the base area "
        "(Sec 1.3.33.8(c)).",
        json_schema_extra=_labels(["One per 30 m of perimeter", "By the base area"]),
    )
    earthResistance: float | None = Field(
        default=None,
        gt=0,
        title="Earth resistance",
        description="Expected resistance to earth [ohm] for the clearance of Eq 8.1.1; empty: "
        "the limit of Sec 1.3.33.8(b).",
    )


class Electrical(_Model):
    """The electrical services the structure coordinates with (BNBC 2020 Part 8 Chapter 1)."""

    supply: ElectricalSupply = Field(default_factory=ElectricalSupply)
    stories: list[ElectricalStory] = Field(default_factory=list)
    motors: list[Motor] = Field(default_factory=list)
    equipment: list[ElectricalEquipment] = Field(default_factory=list)
    risers: list[ElectricalRiser] = Field(default_factory=list)
    trays: list[CableTray] = Field(default_factory=list)
    rooms: list[ElectricalRoom] = Field(default_factory=list)
    lightning: Lightning | None = None

    @model_validator(mode="after")
    def _ids(self) -> Electrical:
        ids = [
            x.id
            for x in (
                *self.motors, *self.equipment, *self.risers, *self.trays, *self.rooms
            )
        ]  # fmt: skip
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate electrical ids: {', '.join(duplicates)}")
        stories = [s.story for s in self.stories]
        twice = sorted({s for s in stories if stories.count(s) > 1})
        if twice:
            raise ValueError(f"electrical stories listed twice: {', '.join(twice)}")
        return self


# ─────────────────────────── fire protection (BNBC 2020 Part 4) ───────────────────────────

FIRE_RISER_SYSTEMS = {
    "standpipe": "Standpipe (hydrant) riser",
    "sprinkler": "Sprinkler riser",
    "combined": "Combined standpipe and sprinkler riser",
}
FIRE_PUMP_DUTIES = {
    "main": "Main fire pump",
    "standby": "Standby fire pump",
    "jockey": "Jockey (pressurising) pump",
}


class FireBuilding(_Model):
    """What Part 4 Chapter 5 asks of the building besides its stories."""

    construction: Literal["typeIA", "modifiedIA", "other"] = Field(
        default="typeIA",
        description="Sec 5.2: monolithic construction to the Code is Type I-A; offsite, "
        "prestressed, prefabricated or encased steel Modified Type I-A; any other: performance "
        "based fire protection (Sec 5.2.5).",
        json_schema_extra=_labels(
            ["Type I-A (monolithic RC)", "Modified Type I-A", "Other (performance based)"]
        ),
    )
    corridor: Literal["central", "singleOpen"] = Field(
        default="central",
        description="Hostels, hotels and schools (Sec 5.3.3, 5.3.4, 5.4): central corridor with "
        "rooms on both sides, or a single loaded open corridor of 3 m or more.",
        json_schema_extra=_labels(["Central corridor", "Single loaded open corridor (3 m+)"]),
    )
    dwellingUnits: int | None = Field(
        default=None,
        ge=0,
        title="Dwelling units",
        description="Flats (A3): 30 or more need a fire protection plan (Sec 5.1.6(c)).",
    )
    occupantLoad: float | None = Field(
        default=None,
        ge=0,
        title="Occupant load",
        description="Industry (G1): above 150 the protection is performance based (Sec 5.9.1).",
    )
    falseCeiling: float | None = Field(
        default=None,
        ge=0,
        title="False ceiling",
        description="Largest space under one false ceiling [m²] (offices: above 500 m² an "
        "automatic fire alarm above and below it, Sec 5.7(ix)).",
    )


class FireSupply(_Model):
    """The water-based systems: hose, pipes, storage and pumps."""

    hose: Literal["small", "large", "firstAid"] = Field(
        default="small",
        description="Hose at the outlets (Sec 4.2.3.11): small stream 63/50 mm or large stream "
        "100 mm (300 kPa at the outlet), first-aid 38 mm (200 kPa) (Sec 4.2.3.3).",
        json_schema_extra=_labels(
            ["Small stream (63 or 50 mm)", "Large stream (100 mm)", "First aid (38 mm)"]
        ),
    )
    material: Literal["steel", "GI", "copper"] = Field(
        default="steel",
        description="Pipe (Tables 4.4.3 and 4.4.8); sprinkler pipe schedules of Table 4.4.5 "
        "(steel) or 4.4.6 (copper).",
        json_schema_extra=_labels(["Black steel", "Galvanised steel", "Copper"]),
    )
    storage: Literal["dedicated", "plumbingReserve"] = Field(
        default="dedicated",
        description="The fire water in its own tanks (fire.tanks), or as the fire reserve of "
        "the plumbing tanks (plumbing.supply.fireReserve, Figure 4.4.6).",
        json_schema_extra=_labels(["Dedicated fire tanks", "Fire reserve in the plumbing tanks"]),
    )
    pumpType: Literal["endSuction", "splitCase", "verticalTurbine"] = Field(
        default="endSuction",
        title="Pump type",
        description="Centrifugal pumps (end suction, split case) need a flooded suction (Sec "
        "4.2.2.5); a vertical turbine pump stands over a tank below it.",
        json_schema_extra=_labels(
            ["End suction centrifugal", "Split case centrifugal", "Vertical turbine"]
        ),
    )
    standby: Literal["diesel", "electric"] = Field(
        default="diesel",
        description="The secondary fire pump (Sec 4.2.2.5): diesel engine, or electric on an "
        "alternate power supply.",
        json_schema_extra=_labels(["Diesel engine", "Electric, alternate supply"]),
    )
    fireEngineOnCover: bool = Field(
        default=False,
        title="Fire engine on the cover",
        description="No space for the fire engine beside the ground tank: its cover slab "
        "carries the fire engine (Sec 4.2.3.8).",
    )
    fireEngineWeight: float | None = Field(
        default=None,
        gt=0,
        title="Fire engine weight",
        description="Gross weight of the local fire engine [kN]; empty: 160 kN (from memory, "
        "to be checked with the Fire Service).",
    )


class FireStory(_Model):
    """A story's use and what protects it."""

    story: Id = Field(description="Building-model story.")
    occupancy: Occupancy | None = Field(  # type: ignore[valid-type]
        default=None,
        description="Use (Part 3 occupancy group in brackets): it sets the systems (Part 4 "
        "Chapter 5) and the hazard (Table 4.4.1); empty: the story's use in Plumbing, else "
        "office.",
        json_schema_extra=_labels(
            [f"{OCCUPANCIES[k].label} ({OCCUPANCIES[k].group})" for k in OCCUPANCY_KEYS]
        ),
    )
    area: float | None = Field(
        default=None, gt=0, description="Gross floor area [m²]; empty: the story's slabs."
    )
    undivided: float | None = Field(
        default=None,
        gt=0,
        description="Largest single effective undivided space [m²]; empty: the floor area.",
    )
    hazard: Literal[tuple(FIRE_HAZARDS)] | None = Field(  # type: ignore[valid-type]
        default=None,
        description="Table 4.4.1 hazard; empty: of the occupancy group.",
        json_schema_extra=_labels(list(FIRE_HAZARDS.values())),
    )
    sprinklered: bool | None = Field(
        default=None, description="Sprinklers on this story; empty: where Part 4 requires them."
    )
    ceiling: Literal["beams", "openJoists", "other"] = Field(
        default="beams",
        description="Construction above the sprinklers (Table 4.4.7).",
        json_schema_extra=_labels(
            ["Floor on beams or girders", "Open wood joists", "Other construction"]
        ),
    )


class FireRiser(_Model):
    """A vertical fire main: standpipe, sprinkler or combined riser."""

    id: Id
    system: Literal[tuple(FIRE_RISER_SYSTEMS)] = Field(  # type: ignore[valid-type]
        default="standpipe", json_schema_extra=_labels(list(FIRE_RISER_SYSTEMS.values()))
    )
    x: Mm = Field(description="Plan X [mm].")
    y: Mm = Field(description="Plan Y [mm].")
    fromStory: Id = Field(title="From story", description="Story it starts at (not cut).")
    toStory: Id = Field(title="To story", description="Highest story whose floor it cuts.")
    shaft: Id | None = Field(default=None, description="Shaft it runs in.")
    diameter: Length | None = Field(default=None, description="Nominal [mm]; empty: sized.")


class FireMain(_Model):
    """A horizontal fire or sprinkler main below a floor (its beam sleeves are proposed)."""

    id: Id
    story: Id = Field(description="Story whose ceiling space it runs in.")
    path: list[Point2] = Field(min_length=2, description="Plan path [[x, y], ...] mm.")
    diameter: Length | None = Field(default=None, description="Nominal [mm]; empty: sized.")
    bottom: Mm | None = Field(
        default=None,
        description="Pipe bottom above the story's floor [mm]; empty: 150 mm "
        "below the soffit of the slab above (as the cable trays).",
    )


class FirePump(_Model):
    """A fire pump set (its weight loads the floor it stands on)."""

    id: Id
    duty: Literal[tuple(FIRE_PUMP_DUTIES)] = Field(  # type: ignore[valid-type]
        default="main", json_schema_extra=_labels(list(FIRE_PUMP_DUTIES.values()))
    )
    story: Id = Field(description="Building-model story it stands on.")
    x: Mm = Field(description="Centre, plan X [mm].")
    y: Mm = Field(description="Centre, plan Y [mm].")
    length: Length | None = Field(default=None, description="Along X [mm].")
    width: Length | None = Field(default=None, description="Along Y [mm].")
    height: Length | None = None
    flow: float | None = Field(default=None, gt=0, description="Rated flow [l/min].")
    head: float | None = Field(default=None, gt=0, description="Rated head [m].")
    power: float | None = Field(default=None, gt=0, description="Motor or engine [kW].")
    operatingWeight: float | None = Field(
        default=None, gt=0, title="Operating weight", description="Set with water [kN]."
    )
    sized: bool = Field(default=False, description="Proposed by SAEngine (editable).")
    equipment: Id | None = Field(
        default=None, description="An equipment of 07 MEP that is this pump (loaded once)."
    )


class FirePumpRoom(_Model):
    """The fire pump room: its outline is checked against the sets it must hold."""

    story: Id
    outline: list[Point2] = Field(min_length=3, description="Inside face of the walls [mm].")


class Fire(_Model):
    """The fire protection the structure coordinates with (BNBC 2020 Part 4)."""

    building: FireBuilding = Field(default_factory=FireBuilding)
    supply: FireSupply = Field(default_factory=FireSupply)
    hydrant: bool | None = Field(
        default=None,
        description="A hydrant (standpipe) system; empty: where Part 4 requires one. Where "
        "Part 4 allows 'portable extinguishers or hydrants', true chooses hydrants.",
    )
    detection: bool | None = Field(
        default=None, description="Automatic detection; empty: where Part 4 requires it."
    )
    stories: list[FireStory] = Field(default_factory=list)
    risers: list[FireRiser] = Field(default_factory=list)
    mains: list[FireMain] = Field(default_factory=list)
    tanks: list[PlumbingTank] = Field(
        default_factory=list,
        description="Fire water reservoirs (kinds overhead and underground), designed as the "
        "plumbing tanks.",
    )
    pumps: list[FirePump] = Field(default_factory=list)
    pumpRoom: FirePumpRoom | None = Field(default=None, title="Pump room")

    @model_validator(mode="after")
    def _ids(self) -> Fire:
        ids = [x.id for x in (*self.risers, *self.mains, *self.tanks, *self.pumps)]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate fire ids: {', '.join(duplicates)}")
        stories = [s.story for s in self.stories]
        twice = sorted({s for s in stories if stories.count(s) > 1})
        if twice:
            raise ValueError(f"fire stories listed twice: {', '.join(twice)}")
        return self


class StoryUseEntry(_Model):
    """A storey's use, entered once for the plumbing, HVAC and electrical services
    (:mod:`saengine.mep.uses`)."""

    story: Id = Field(description="Building-model story.")
    use: Literal[STORY_USE_KEYS] = Field(  # type: ignore[valid-type]
        description="Mapped to BNBC 2020 Part 8 Tables 8.5.1, 8.2.3 and 8.1.17. Roof and "
        "services: not occupied (left out of every service's stories).",
        json_schema_extra=_labels([STORY_USES[k].label for k in STORY_USE_KEYS]),
    )
    population: float | None = Field(
        default=None,
        ge=0,
        description="Persons; empty: each service's default for the use and the floor area.",
    )


class MepModel(_Model):
    schema_: Literal["saengine.mep/1"] = Field(default=SCHEMA_ID, alias="schema")
    storyUses: list[StoryUseEntry] = Field(
        default_factory=list,
        title="Storey use",
        description="The use of each storey, read by the plumbing, HVAC and electrical services "
        "(their own storey tables keep the fixtures, gains and loads).",
    )
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
    hvac: Hvac | None = Field(
        default=None,
        title="HVAC",
        description="Air-conditioning and ventilation: cooling loads (EnergyPlus), plant and "
        "ducts, to BNBC 2020 Part 8 Chapter 2.",
    )
    electrical: Electrical | None = Field(
        default=None,
        description="Supply, plant rooms, risers, trays and lightning protection, coordinated "
        "to BNBC 2020 Part 8 Chapter 1.",
    )
    fire: Fire | None = Field(
        default=None,
        description="Fire protection: the systems required, standpipes, sprinklers, fire "
        "pumps and the fire reservoir, to BNBC 2020 Part 4.",
    )
    coordination: Coordination | None = Field(
        default=None,
        description="Multi-discipline clash tests, coordination issues with their status "
        "workflow (BCF 3.0) and IDS model checks.",
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
    from saengine.mep.uses import with_story_uses

    return with_story_uses(MepModel.model_validate(data))


def check(mep: MepModel, building: Any = None) -> list[str]:
    """Problems with what the MEP model refers to in the building model (stories, hosts)."""
    if building is None:
        return []
    stories = {s.id: s.elevation for s in building.stories}
    kinds = {e.id: e.kind for e in building.elements}
    problems = []
    for entry in mep.storyUses:
        if entry.story not in stories:
            problems.append(f"storey use: no story '{entry.story}'")
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
    if mep.hvac is not None:
        problems.extend(hvac_references(mep, stories))
    equipment = {e.id for e in mep.equipment}
    linked = [
        *(mep.hvac.plant if mep.hvac is not None else []),
        *(mep.electrical.equipment if mep.electrical is not None else []),
        *(mep.fire.pumps if mep.fire is not None else []),
    ]
    for item in linked:
        if item.equipment is not None and item.equipment not in equipment:
            problems.append(f"{item.id}: no equipment '{item.equipment}'")
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
