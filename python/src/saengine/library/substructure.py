"""Substructure (``09 Substructure/substructure.json``): the foundations of the building.

Part 9 places the foundations under the columns and walls of the building model (Part 6) and
designs them under the support reactions of the analysis (Part 8) on the soil of the soil report
(Part 1): isolated, combined and strip footings, pile caps on piles, and rafts, with the tie
beams between them. The piles are placed on their own (on the pile grid, independent of the
building's grid) and a pile cap is formed over a group of them: its centre need not lie on its
columns, and the design carries that eccentricity into the pile loads. The file stores only what the engineer decides (types, sizes, positions,
reinforcement, design choices); every computed value (soil pressure, pile loads, checks) is
worked out on demand (:func:`saengine.substructure.substructure_report`).

Units: mm for lengths, positions and levels (project datum), degrees for rotations, kPa for
pressures, kN/m³ for the modulus of subgrade reaction.
"""

from __future__ import annotations

import itertools
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from saengine.library.labels import field_title
from saengine.library.materials import Category, Id, MaterialLibrary
from saengine.library.objects import (
    BarMesh,
    LinearReinforcement,
    PlanarReinforcement,
    PunchingReinforcement,
)

SCHEMA_ID = "saengine.substructure/1"
SUBSTRUCTURE_FILE = "09 Substructure/substructure.json"

#: Founding depth below the finished ground when a foundation gives no founding level [mm].
DEFAULT_FOUNDING_DEPTH = 1500.0

Length = Annotated[float, Field(gt=0, description="[mm]")]
Point2 = Annotated[list[float], Field(min_length=2, max_length=2, description="[x, y] in mm.")]

FoundationType = Literal["isolated", "combined", "strip", "pileCap", "raft"]
FootingSection = Literal["flat", "sloped", "stepped"]

FOUNDATION_TYPES = {
    "isolated": "Isolated footing",
    "combined": "Combined footing",
    "strip": "Strip footing",
    "pileCap": "Pile cap",
    "raft": "Raft",
}


def _labels(names: list[str]) -> dict[str, Any]:
    """Readable names of an enum's values for the editors (JSON Schema ``enumDescriptions``)."""
    return {"enumDescriptions": names}


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, field_title_generator=field_title
    )


class Foundation(_Model):
    """One foundation: a footing, a pile cap or a raft, with the columns (and walls) it
    carries."""

    id: Id
    type: FoundationType = Field(  # type: ignore[valid-type]
        title="Type",
        description="Isolated footing (one column), combined footing (several columns on one "
        "rectangle), strip footing (under walls or a column line, along a path), pile cap on "
        "piles, or raft (a slab on the soil under many columns).",
        json_schema_extra=_labels(list(FOUNDATION_TYPES.values())),
    )
    columns: list[Id] = Field(
        default_factory=list,
        description="Building-model ids of the columns it carries (a strip footing: the walls "
        "and columns on its path). A raft without any carries every column base inside its "
        "outline.",
    )
    center: Point2 | None = Field(
        default=None,
        description="Plan position of the centre [x, y] mm (isolated and combined footings; "
        "empty: the centroid of its columns). A pile cap always has one: it is placed over its "
        "piles, not over its columns.",
    )
    rotation: float = Field(default=0, description="Of its local x axis from the global X [°].")
    length: Length | None = Field(default=None, description="Along its local x [mm].")
    width: Length | None = Field(
        default=None, description="Along its local y; a strip footing: across its path [mm]."
    )
    thickness: Length | None = Field(
        default=None, description="[mm]; a sloped or stepped footing: under the column."
    )
    section: FootingSection = Field(
        default="flat",
        title="Section",
        description="Isolated footings: flat (one thickness), sloped (the top slopes from a "
        "flat top round the column down to the edge thickness) or stepped (an upper step round "
        "the column on a lower slab of the edge thickness).",
        json_schema_extra=_labels(["Flat", "Sloped", "Stepped"]),
    )
    edgeThickness: Length | None = Field(
        default=None,
        title="Edge thickness",
        description="A sloped footing: at its edges; a stepped footing: of the lower step [mm].",
    )
    topLength: Length | None = Field(
        default=None,
        title="Top length",
        description="Along its local x, the flat top of a sloped footing or the upper step of a "
        "stepped one, centred on the column [mm].",
    )
    topWidth: Length | None = Field(
        default=None,
        title="Top width",
        description="Along its local y, the flat top or upper step [mm].",
    )
    path: list[Point2] | None = Field(
        default=None,
        min_length=2,
        description="Centre line of a strip footing [[x, y], ...] mm.",
    )
    outline: list[Point2] | None = Field(
        default=None, min_length=3, description="Plan outline of a raft [[x, y], ...] mm."
    )
    foundingLevel: float | None = Field(
        default=None,
        title="Founding level",
        description="Level of the underside, project datum [mm]; empty: 1.5 m below the "
        "finished ground of Project Settings → Foundation.",
    )
    allowableBearing: float | None = Field(
        default=None,
        gt=0,
        title="Allowable bearing override qa",
        description="Net allowable bearing pressure of this foundation [kPa], instead of the "
        "soil report's at its position, founding level and size (and of the project's "
        "override).",
    )
    slopeDistance: Length | None = Field(
        default=None,
        title="Distance to a slope face",
        description="A footing on or near a slope: horizontal distance from its centre to the "
        "sloping surface at its base level [mm], checked against the code pack's least "
        "multiple of its width; empty: level ground.",
    )
    material: Id | None = Field(default=None, description="Concrete material id (03 Materials).")
    reinforcement: PlanarReinforcement | None = None
    punchingReinforcement: PunchingReinforcement | None = Field(
        default=None,
        title="Punching reinforcement",
        description="Studs or stirrups round its columns, checked where the concrete alone is "
        "not enough (isolated, combined footings and rafts; empty: none).",
    )
    piles: list[Id] | None = Field(
        default=None,
        description="Pile caps: the ids of the piles it stands on (the substructure's piles, "
        "placed in plan; all of one pile type).",
    )
    note: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> Foundation:
        kind = FOUNDATION_TYPES[self.type].lower()
        missing: list[str] = []
        if self.type in ("isolated", "combined", "pileCap"):
            missing = [n for n in ("length", "width", "thickness") if getattr(self, n) is None]
            if self.type == "pileCap" and self.center is None:
                missing.append("center")
            elif self.center is None and not self.columns:
                missing.append("center (or columns)")
        elif self.type == "strip":
            missing = [n for n in ("path", "width", "thickness") if getattr(self, n) is None]
        elif self.type == "raft":
            missing = [n for n in ("outline", "thickness") if getattr(self, n) is None]
        if self.type == "pileCap" and not self.piles:
            missing.append("piles")
        if missing:
            raise ValueError(f"{self.id}: a {kind} needs {', '.join(missing)}")
        listed = self.columns + (self.piles or [])
        duplicates = sorted({c for c in listed if listed.count(c) > 1})
        if duplicates:
            raise ValueError(f"{self.id}: {', '.join(duplicates)} listed twice")
        if self.piles and self.type != "pileCap":
            raise ValueError(f"{self.id}: only a pile cap stands on piles")
        if self.path is not None and any(
            math.dist(a, b) < 1 for a, b in itertools.pairwise(self.path)
        ):
            raise ValueError(f"{self.id}: two consecutive points of the path coincide")
        if self.outline is not None and abs(polygon_area(self.outline)) < 1:
            raise ValueError(f"{self.id}: the outline encloses no area")
        if self.section != "flat":
            self._check_section()
        return self

    def _check_section(self) -> None:
        if self.type != "isolated":
            raise ValueError(f"{self.id}: only an isolated footing is sloped or stepped")
        missing = [
            n for n in ("edgeThickness", "topLength", "topWidth") if getattr(self, n) is None
        ]
        if missing:
            raise ValueError(f"{self.id}: a {self.section} footing needs {', '.join(missing)}")
        if self.edgeThickness >= self.thickness:  # type: ignore[operator]
            raise ValueError(f"{self.id}: the edge thickness must be less than the thickness")
        if self.topLength > self.length or self.topWidth > self.width:  # type: ignore[operator]
            raise ValueError(f"{self.id}: the top must lie within the footing's plan")

    def concrete_volume(self) -> float | None:
        """Concrete volume [mm³] of a rectangular footing or cap: L B h, or for a stepped one
        L B he + Lt Bt (h - he), and for a sloped one L B he plus the prismatoid between the
        base and the flat top, (h - he) / 6 (L B + Lt Bt + (L + Lt)(B + Bt)). None for strips
        and rafts."""
        if self.length is None or self.width is None or self.thickness is None:
            return None
        flat = self.length * self.width * self.thickness
        if self.section == "flat" or self.edgeThickness is None:
            return flat
        lt, bt, he = float(self.topLength or 0), float(self.topWidth or 0), self.edgeThickness
        rise = self.thickness - he
        base = self.length * self.width * he
        if self.section == "stepped":
            return base + lt * bt * rise
        return base + rise / 6 * (
            self.length * self.width + lt * bt + (self.length + lt) * (self.width + bt)
        )

    def founding_level(self, ground_level: float) -> float:
        """The level of the underside [mm]: its own, or :data:`DEFAULT_FOUNDING_DEPTH` below
        ``ground_level``."""
        if self.foundingLevel is not None:
            return self.foundingLevel
        return ground_level - DEFAULT_FOUNDING_DEPTH


class PileType(_Model):
    """A pile: kind, size and reinforcement."""

    id: Id
    kind: Literal["bored", "driven", "drivenCastInPlace"] = Field(
        default="bored",
        description="Bored cast-in-situ, driven precast (square), or driven cast-in-place (a "
        "shell or tube driven and filled with concrete: round, the capacity of a driven pile).",
        json_schema_extra=_labels(
            ["Bored (cast in situ)", "Driven (precast)", "Driven (cast in place)"]
        ),
    )
    diameter: Length = Field(description="Diameter (driven square piles: the side) [mm].")
    length: Length = Field(description="Below the underside of the cap [mm].")
    material: Id = Field(description="Concrete material id (03 Materials).")
    reinforcement: LinearReinforcement | None = None
    headFixity: Literal["fixed", "free"] = Field(
        default="fixed",
        title="Head fixity",
        description="Fixed: the pile bars developed into the cap, which holds the head against "
        "rotation; free: the head may rotate (pinned).",
        json_schema_extra=_labels(["Fixed in the cap", "Free (pinned)"]),
    )
    shaftConstruction: str | None = Field(
        default=None,
        title="Shaft construction (K/K0)",
        description="Drilled shafts in sand: the code pack's construction method for K/K0 (e.g. "
        "openHole, slurryLight, slurryHeavy, permanentCasing); with the concreting method, β = "
        "K tan δ instead of the empirical depth relation. Empty: the depth relation.",
    )
    shaftConcreting: str | None = Field(
        default=None,
        title="Shaft concreting (δ/φ)",
        description="Drilled shafts in sand: the code pack's construction method for δ/φ (e.g. "
        "dry, slurryGood, slurryPoor, casingUnderWater).",
    )
    fixityDepth: Length | None = Field(
        default=None,
        title="Depth to fixity",
        description="Below the pile head, where the pile acts as fixed against the lateral load, "
        "from the geotechnical report [mm]; none: the pile is designed for axial force only.",
    )
    tipDiameter: Length | None = Field(
        default=None,
        title="Tip diameter",
        description="Driven cast-in-place piles tapered towards the tip: its diameter [mm]; "
        "empty: uniform.",
    )
    placement: Literal["dry", "submerged"] = Field(
        default="submerged",
        title="Concrete placement",
        description="Bored piles: concrete placed in a dry bore, or by tremie under water or "
        "slurry (the code pack's least cement content and mix by placement).",
        json_schema_extra=_labels(["Dry bore", "Tremie under water or slurry"]),
    )
    hardDriving: bool = Field(
        default=False,
        title="Hard driving",
        description="Driven piles: driving stresses above the code pack's limit (1000 kPa in "
        "the default pack), which asks for a higher concrete grade.",
    )
    reinforcedLength: Length | None = Field(
        default=None,
        title="Cage length",
        description="Length of the longitudinal bars below the cut-off [mm]; empty: the full "
        "length of the pile.",
    )
    casingDepth: Length | None = Field(
        default=None,
        title="Temporary casing",
        description="Bored piles: depth of the temporary casing below the cut-off [mm]; the cage "
        "runs past it by the code pack's length.",
    )
    unbracedLength: Length | None = Field(
        default=None,
        title="Unbraced length",
        description="Length below the cap standing in air or water, in scour, or in soil that "
        "cannot support it laterally [mm]: that part is designed as a column. Soil weaker "
        "than the code pack's cu limit is found from the soil report.",
    )
    lateralDeflection: float | None = Field(
        default=None,
        gt=0,
        title="Allowable head deflection",
        description="The performance requirement on the pile head's lateral movement [mm]; "
        "empty: the code pack's.",
    )


class PileLoadTest(_Model):
    """A static load test of a pile type at the site: its load-movement curve."""

    id: Id = Field(description="Its mark, e.g. TP1 (test pile) or WP3 (working pile).")
    pileType: Id = Field(title="Pile type", description="Pile type id.")
    kind: Literal["compression", "uplift", "lateral"] = Field(
        default="compression",
        description="Axial compression, uplift (tension) or lateral load.",
        json_schema_extra=_labels(["Compression", "Uplift", "Lateral"]),
    )
    test: Literal["initial", "routine"] = Field(
        default="initial",
        description="Initial test on a test pile (to twice the design load or failure) or "
        "routine test on a working pile (to one and a half times).",
        json_schema_extra=_labels(["Initial (test pile)", "Routine (working pile)"]),
    )
    group: bool = Field(
        default=False, description="A compression test on a pile group (its own criteria)."
    )
    points: list[tuple[float, float]] = Field(
        default_factory=list,
        description="The curve: [load kN, movement mm] at each stage of loading, from the "
        "start (movement at the pile head; lateral tests: the head's lateral movement).",
    )
    breakLoad: float | None = Field(
        default=None,
        gt=0,
        title="Clear break",
        description="Uplift tests: the load at which the curve shows a clear break [kN]; "
        "empty: none seen.",
    )
    bulbDiameter: Length | None = Field(
        default=None,
        title="Bulb diameter",
        description="Under-reamed piles: the bulb's diameter [mm] (its share of settlement).",
    )

    @model_validator(mode="after")
    def _curve(self) -> PileLoadTest:
        for load, movement in self.points:
            if load < 0 or movement < 0:
                raise ValueError(f"load test {self.id}: loads and movements are not negative")
        return self


class Pile(_Model):
    """One pile, placed in plan: its mark, pile type and position."""

    id: Id = Field(description="Its mark on the pile layout plan (PL1, PL2, ...).")
    type: Id = Field(title="Pile type", description="Pile type id.")
    position: Point2 = Field(description="Plan position of its centre [x, y] mm.")


class PileGridLine(_Model):
    """A line of the pile grid."""

    label: Annotated[str, Field(pattern=r"^[A-Za-z0-9.'-]+$", min_length=1, max_length=8)]
    position: float = Field(
        description="Distance from the grid's origin along the grid's own axis [mm]."
    )


class PileGrid(_Model):
    """The grid the piles are set out on, independent of the building's grid: its own origin and
    rotation, named lines across its x axis (``x``, at x = position) and its y axis (``y``)."""

    origin: Point2 = Field(
        default_factory=lambda: [0.0, 0.0], description="Plan position of its origin [mm]."
    )
    rotation: float = Field(default=0, description="Of its x axis from the global X [°].")
    x: list[PileGridLine] = Field(
        default_factory=list, title="X lines", description="Lines at x = position (local)."
    )
    y: list[PileGridLine] = Field(
        default_factory=list, title="Y lines", description="Lines at y = position (local)."
    )

    @model_validator(mode="after")
    def _distinct(self) -> PileGrid:
        labels = [g.label for g in self.x + self.y]
        duplicates = sorted({label for label in labels if labels.count(label) > 1})
        if duplicates:
            raise ValueError(f"pile grid: {', '.join(duplicates)} used twice")
        return self

    def point(self, x: float, y: float) -> list[float]:
        """The plan position [mm] of the local point (x, y)."""
        a = math.radians(self.rotation)
        c, s = math.cos(a), math.sin(a)
        return [self.origin[0] + x * c - y * s, self.origin[1] + x * s + y * c]

    def intersections(self) -> list[tuple[str, str, list[float]]]:
        """Every crossing of an x and a y line: (x label, y label, plan position)."""
        return [
            (gx.label, gy.label, self.point(gx.position, gy.position))
            for gx in self.x
            for gy in self.y
        ]


class TieBeam(_Model):
    """A tie (grade) beam between two foundations."""

    id: Id
    from_: Id = Field(alias="from", title="From", description="Foundation id.")
    to: Id = Field(description="Foundation id.")
    type: Id = Field(description="Beam object type id (04 Objects): profile and bars.")
    level: float | None = Field(
        default=None,
        description="Level of its top, project datum [mm]; empty: the top of the lower of the "
        "two foundations.",
    )
    settlement: float | None = Field(
        default=None,
        ge=0,
        title="Differential settlement",
        description="Settlement of one end relative to the other the tie beam is designed for "
        "[mm]; empty: none.",
    )


class FactorOfSafety(_Model):
    """Factors of safety of the geotechnical capacities."""

    pileCompression: float = Field(
        default=2.5,
        ge=1,
        le=10,
        title="Pile compression",
        description="Overall factor of safety on the ultimate compression capacity of a pile: "
        "BNBC 2020 Table 6.3.10a gives 2.5 for permanent structures with normal control (2.0 "
        "good, 2.8 poor, 3.0 very poor); Sec 3.10.1.18 asks at least 3.0 without a load test "
        "at the site (Sec 3.10.4.10: bored piles too), so the design raises a smaller value "
        "to 3.0 unless a load test is given.",
    )
    pileLoadTest: bool = Field(
        default=False,
        title="Pile load test at the site",
        description="BNBC 2020 Sec 3.10.1.18: without a load test at the site the overall "
        "factor of safety in compression is at least 3.0 (2.0 with one, with good quality "
        "control); Sec 3.10.4.10 for bored piles.",
    )
    pileUplift: float = Field(
        default=2.5,
        ge=1,
        le=10,
        title="Pile uplift",
        description="Overall factor of safety on the ultimate uplift capacity (BNBC 2020 "
        "Table 6.3.10a: downward and upward load).",
    )
    pileSkin: float = Field(
        default=1.5,
        ge=1,
        le=10,
        title="Pile skin friction (partial)",
        description="Partial factor of safety on the skin friction; the allowable load is the "
        "lesser of the overall and the partial ones (BNBC 2020 Sec 3.10.1.18: 1.5).",
    )
    pileEndBearing: float = Field(
        default=3.0,
        ge=1,
        le=10,
        title="Pile end bearing (partial)",
        description="Partial factor of safety on the end bearing (BNBC 2020 Sec 3.10.1.18: 3.0).",
    )
    bearing: float | None = Field(
        default=None,
        ge=1,
        le=10,
        title="Bearing",
        description="Factor of safety on the bearing capacity of footings and rafts; empty: the "
        "soil report's. The code pack's range (2.0-3.0 in the default pack) is warned outside.",
    )


class Design(_Model):
    """Design choices of the substructure."""

    pileCapacity: Literal["soilReport", "static", "spt"] = Field(
        default="soilReport",
        title="Pile capacity",
        description="From the soil report's per-layer skin friction and end bearing (Part 1), "
        "by the code pack's static method (α in clay, β and Nq in sand), or by the code pack's "
        "SPT relations. The former value 'bnbcSpt' is read as 'spt'.",
        json_schema_extra=_labels(
            ["Soil report (per layer)", "Static method (code pack)", "SPT relations (code pack)"]
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _former_method(cls, data: Any) -> Any:
        """The SPT method's former id, 'bnbcSpt', is read as 'spt'."""
        if isinstance(data, dict) and data.get("pileCapacity") == "bnbcSpt":
            data = {**data, "pileCapacity": "spt"}
        return data

    factorOfSafety: FactorOfSafety = Field(default_factory=FactorOfSafety)
    raftMeshSize: float = Field(
        default=500, ge=100, le=5000, title="Raft mesh size", description="[mm]"
    )
    springsFrom: Literal["soilReport"] | Annotated[float, Field(gt=0)] = Field(
        default="soilReport",
        title="Subgrade springs",
        description="Modulus of subgrade reaction of rafts: from the soil report, or a value "
        "[kN/m³].",
    )
    structureType: str = Field(
        default="rcc",
        title="Type of structure (settlement limits)",
        description="Row of the code pack's permissible settlements (total, differential, "
        "angular distortion) the footings and rafts are checked against: steel, rcc, framed "
        "(multistoried framed building with panel walls), loadBearingWalls (L/H below), silo, "
        "waterTank.",
        json_schema_extra={
            "enum": ["steel", "rcc", "framed", "loadBearingWalls", "silo", "waterTank"],
            "enumDescriptions": [
                "Steel structure",
                "RCC structure",
                "Multistoried framed building with panel walls",
                "Load bearing walls",
                "Silo",
                "Water tank",
            ],
        },
    )
    wallLengthHeight: float = Field(
        default=2.0,
        gt=0,
        title="Load bearing walls L/H",
        description="Length of the deflected part of the wall over its height, for the load "
        "bearing wall rows (interpolated).",
    )
    temporary: bool = Field(
        default=False,
        title="Temporary structure",
        description="The code pack's least depth of exterior footings of temporary structures "
        "applies instead of that of permanent ones.",
    )
    presumptiveSoil: str | None = Field(
        default=None,
        title="Presumptive soil (no soil report)",
        description="Without a soil report and without a qa override: the row of the code "
        "pack's presumptive bearing values (lightly loaded structures and preliminary design), "
        "e.g. sand, clay, softClay. Empty: none.",
    )
    raftSprings: Literal["noTension", "linear"] = Field(
        default="noTension",
        title="Raft springs",
        description="No tension: where the raft lifts off, the soil carries nothing (solved "
        "iteratively); linear: the springs may pull.",
        json_schema_extra=_labels(["No tension (iterative)", "Linear"]),
    )
    downdrag: bool = Field(
        default=True,
        title="Negative skin friction",
        description="Check the piles for downdrag where the soil around them settles (fill, "
        "organic and soft soil by the code pack), to the neutral point.",
    )
    downdragDepth: Length | None = Field(
        default=None,
        title="Settling soil to",
        description="Depth below the ground down to which the soil settles round the piles "
        "[mm]; empty: the settling layers of the soil report from the top.",
    )
    swellingDepth: Length | None = Field(
        default=None,
        title="Swelling zone to",
        description="Depth below the ground of the zone of seasonal moisture change in "
        "expansive soil [mm]; empty: the layers whose samples the soil report finds expansive.",
    )


class GroundSlab(_Model):
    """A slab on grade (ground-bearing slab): a plain or lightly reinforced slab laid on the
    compacted ground, under a uniform floor load and a concentrated (post or wheel) load."""

    id: Id
    outline: list[Point2] = Field(min_length=3, description="Plan outline [[x, y], ...] mm.")
    thickness: Length = Field(default=150, description="[mm]")
    material: Id = Field(description="Concrete material id (03 Materials).")
    mesh: BarMesh | None = Field(
        default=None,
        title="Mesh",
        description="One layer of bars each way for crack control (empty: plain concrete).",
    )
    meshMaterial: Id | None = Field(
        default=None, title="Mesh material", description="Rebar material id (03 Materials)."
    )
    uniformLoad: float = Field(
        default=5.0, ge=0, title="Uniform load", description="Floor load on it [kPa]."
    )
    pointLoad: float = Field(
        default=0.0,
        ge=0,
        title="Concentrated load",
        description="The largest post, rack-leg or wheel load, service [kN]; 0: none.",
    )
    contactSide: Length = Field(
        default=150,
        title="Contact side",
        description="Side of the square base plate or tyre print of the concentrated load [mm].",
    )
    subgradeModulus: float | None = Field(
        default=None,
        gt=0,
        title="Subgrade modulus k",
        description="Of the compacted sub-base [kN/m³]; empty: the subgrade springs value of "
        "9 Substructure → Design.",
    )
    factorOfSafety: float = Field(
        default=2.0,
        ge=1,
        le=5,
        title="Factor of safety",
        description="On the modulus of rupture for the concentrated load's flexural stress.",
    )
    jointSpacing: Length | None = Field(
        default=None,
        title="Joint spacing",
        description="Of the contraction joints [mm]; empty: not checked.",
    )
    note: str | None = None


RetainingWallKind = Literal["cantilever", "basement"]

RETAINING_WALL_KINDS = {
    "cantilever": "Cantilever retaining wall",
    "basement": "Basement wall (propped by the floors)",
}


class RetainingWallBars(_Model):
    """The bars of a retaining or basement wall per metre run (BarMesh: diameter, spacing);
    empty layers are proposed by the design."""

    material: Id = Field(description="Reinforcement material id (03 Materials).")
    cover: Length = Field(
        default=50,
        description="To the bars at the faces of the stem against earth or weather [mm] (BNBC "
        "2020 Part 6 Sec 8.1.7.2 (b): 50 mm for 19 mm bars and larger, 40 mm for 16 mm and "
        "smaller); 75 mm cast against earth is used under the base.",
    )
    stemBack: BarMesh | None = Field(
        default=None,
        title="Stem, soil face (vertical)",
        description="Vertical bars at the face against the soil: the main bars of a cantilever "
        "stem.",
    )
    stemFront: BarMesh | None = Field(
        default=None,
        title="Stem, inner face (vertical)",
        description="Vertical bars at the exposed (or inner) face: the span bars of a basement "
        "wall between the floors.",
    )
    horizontal: BarMesh | None = Field(
        default=None,
        title="Horizontal (each face)",
        description="Horizontal distribution bars at each face (BNBC 2020 Part 6 Sec 6.6.3.3).",
    )
    heelTop: BarMesh | None = Field(
        default=None, title="Heel, top", description="Main bars at the top of the heel."
    )
    toeBottom: BarMesh | None = Field(
        default=None, title="Toe, bottom", description="Main bars at the bottom of the toe."
    )
    baseDistribution: BarMesh | None = Field(
        default=None,
        title="Base, along the wall",
        description="Distribution bars of the base along the wall, each face.",
    )


class Backfill(_Model):
    """The soil placed behind the wall, when it is not the ground of the soil report."""

    gamma: float = Field(default=18.0, gt=0, title="Unit weight γ", description="[kN/m³]")
    gammaSat: float | None = Field(
        default=None, gt=0, title="Saturated unit weight γsat", description="[kN/m³]; empty: γ + 2."
    )
    phi: float | None = Field(
        default=30.0, ge=0, le=50, title="Friction angle φ'", description="[°]"
    )
    c: float = Field(default=0.0, ge=0, title="Cohesion c'", description="[kPa]")


class RetainingWall(_Model):
    """A retaining wall (a cantilever on its own base) or a basement wall (spanning between
    the basement floors and the raft), designed per metre run along its path. The soil is that
    of 1 Soil Report at the wall (the nearest borehole) unless a backfill is given."""

    id: Id
    kind: RetainingWallKind = Field(  # type: ignore[valid-type]
        default="cantilever",
        description="A cantilever wall on its own base (stability, stem and base design), or a "
        "basement wall propped at the floors (one-way span between the supports).",
        json_schema_extra=_labels(list(RETAINING_WALL_KINDS.values())),
    )
    path: list[Point2] = Field(
        min_length=2,
        description="Plan line of the wall's soil face [[x, y], ...] mm; the soil is on the "
        "left looking along the path unless soilSide says otherwise.",
    )
    soilSide: Literal["left", "right"] = Field(
        default="left",
        title="Soil side",
        description="Side of the path the retained soil is on, looking along the path.",
        json_schema_extra=_labels(["Left", "Right"]),
    )
    wall: Id | None = Field(
        default=None,
        title="Building wall",
        description="The wall of 6 BIM this is (a basement wall of the building): its earth "
        "pressure then loads the analysis model as case H. Empty: a free-standing wall.",
    )
    topLevel: float = Field(
        title="Top of the wall", description="Level of the top of the stem, project datum [mm]."
    )
    retainedLevel: float | None = Field(
        default=None,
        title="Retained ground level",
        description="Level of the ground behind the wall [mm]; empty: the finished ground of "
        "Project Settings → Foundation.",
    )
    frontLevel: float | None = Field(
        default=None,
        title="Front ground level",
        description="Level of the ground (or basement floor) in front of the wall [mm]; empty: "
        "the top of the base.",
    )
    foundingLevel: float = Field(
        title="Founding level", description="Level of the underside of the base [mm]."
    )
    stemTop: Length = Field(default=200, title="Stem thickness at the top", description="[mm]")
    stemBottom: Length = Field(default=300, title="Stem thickness at the base", description="[mm]")
    baseThickness: Length = Field(default=400, title="Base thickness", description="[mm]")
    toe: float = Field(default=600, ge=0, description="Base beyond the stem's front face [mm].")
    heel: float = Field(default=1500, ge=0, description="Base beyond the stem's back face [mm].")
    supports: list[float] = Field(
        default_factory=list,
        description="Basement walls: levels of the floors that prop the wall [mm] (the top one "
        "is usually the ground floor slab); the base is held by the raft or footing.",
    )
    baseFixed: bool = Field(
        default=True,
        title="Fixed at the base",
        description="Basement walls: the wall is continuous with the raft (fixed); off: pinned.",
    )
    pressure: Literal["auto", "atRest", "active"] | None = Field(
        default="auto",
        title="Earth pressure",
        description="Auto: active on a cantilever wall (free to rotate), at rest on a basement "
        "wall (propped, cannot yield).",
        json_schema_extra=_labels(["Auto", "At rest (K0)", "Active (Ka)"]),
    )
    method: Literal["rankine", "coulomb"] = Field(
        default="rankine",
        description="Active pressure by Rankine (on the vertical plane through the heel) or "
        "Coulomb (with the wall friction δ, on the stem's back).",
        json_schema_extra=_labels(["Rankine", "Coulomb"]),
    )
    backslope: float = Field(default=0, ge=0, le=45, title="Backfill slope β", description="[°]")
    wallFriction: float | None = Field(
        default=None,
        ge=0,
        le=45,
        title="Wall friction δ",
        description="[°]; empty: 2/3 φ' (Coulomb and the seismic increment).",
    )
    surcharge: float = Field(
        default=10.0,
        ge=0,
        description="Uniform surcharge on the retained ground [kPa] (traffic, stored material).",
    )
    drained: bool = Field(
        default=False,
        description="A drain behind the wall (weep holes, a drainage layer) keeps the water "
        "off it: no water pressure on the wall and no uplift under the base.",
    )
    designWaterTable: float | None = Field(
        default=None,
        title="Design water table",
        description="Depth below the retained ground [m]; empty: the borehole's measured "
        "level. Use the highest level expected (flood, monsoon).",
    )
    backfill: Backfill | None = Field(
        default=None,
        description="Properties of the backfill behind the wall; empty: the soil report's layers.",
    )
    passive: bool = Field(
        default=False,
        title="Passive resistance in front",
        description="The soil in front of the base cannot be removed inadvertently by "
        "excavation: count its passive pressure against sliding (with the code pack's factor). "
        "Off: not counted, as the code pack requires where the soil could be removed.",
    )
    frictionCoefficient: float | None = Field(
        default=None,
        gt=0,
        le=1.5,
        title="Verified base friction factor",
        description="A base friction factor verified by analysis and test, instead of the code "
        "pack's (0.5 in the default pack); empty: the pack's.",
    )
    seismic: bool = Field(
        default=True,
        title="Seismic earth pressure",
        description="Check the wall with the seismic increment of the earth pressure "
        "(Mononobe-Okabe on a cantilever wall, Wood on a basement wall) at the site's peak "
        "ground acceleration.",
    )
    material: Id = Field(description="Concrete material id (03 Materials).")
    reinforcement: RetainingWallBars | None = None
    crackLimit: float = Field(
        default=0.3,
        gt=0,
        title="Crack width limit",
        description="Service crack width at the soil face [mm]: 0.3 for walls in soil, 0.2 "
        "where they must be watertight (EN 1992-3 Table 7.105, class 1).",
    )
    note: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> RetainingWall:
        if self.topLevel <= self.foundingLevel + self.baseThickness:
            raise ValueError(f"{self.id}: the top of the wall is not above its base")
        if self.stemBottom < self.stemTop:
            raise ValueError(f"{self.id}: the stem is thinner at the base than at the top")
        if any(math.dist(a, b) < 1 for a, b in itertools.pairwise(self.path)):
            raise ValueError(f"{self.id}: two consecutive points of the path coincide")
        top = self.topLevel
        base = self.foundingLevel + self.baseThickness
        for level in self.supports:
            if not base < level <= top + 1e-6:
                raise ValueError(f"{self.id}: the support at {level:g} is not on the wall")
        if self.kind == "basement" and not self.supports:
            raise ValueError(f"{self.id}: a basement wall needs the levels of its floors")
        return self

    def length(self) -> float:
        """Along its path [mm]."""
        return sum(math.dist(a, b) for a, b in itertools.pairwise(self.path))

    def state(self) -> str:
        """The earth pressure state the design uses."""
        if self.pressure in (None, "auto"):
            return "active" if self.kind == "cantilever" else "atRest"
        return self.pressure


EXCAVATION_SUPPORTS = {
    "sloped": "Sloped sides",
    "stepped": "Stepped sides",
    "shored": "Shoring, bracing and sheeting",
    "sheetPiles": "Sheet piles",
    "retainingWall": "Retaining wall",
    "rock": "Rock cut",
    "none": "Vertical, unsupported",
}

ExcavationSupport = Literal[
    "sloped", "stepped", "shored", "sheetPiles", "retainingWall", "rock", "none"
]


class AdjoiningStructure(_Model):
    """A building or structure next to an excavation: its foundation decides whether it is
    underpinned or its added load provided for, and the notices and monitoring it needs."""

    id: Id = Field(description="Its mark, e.g. AB1.")
    name: str | None = Field(default=None, description="What it is, e.g. 'Four-storey house'.")
    distance: float = Field(
        default=0,
        ge=0,
        description="Clear distance in plan from the excavation's edge to its foundation [mm].",
    )
    foundingLevel: float = Field(
        title="Founding level", description="Underside of its foundation [mm, project datum]."
    )
    underpinned: bool = Field(
        default=False,
        description="Its foundation is underpinned or otherwise protected against settlement "
        "before the excavation.",
    )
    otherProperty: bool = Field(
        default=True,
        title="Another owner's property",
        description="It stands on another owner's property (written notice before excavating).",
    )
    sensitive: bool = Field(
        default=False,
        title="Old or likely to be damaged",
        description="An old structure likely to be damaged by piling or excavation "
        "(tell-tales while piling).",
    )


class ExcavationLoad(_Model):
    """Spoil, materials, equipment or machinery placed beside an excavation."""

    kind: Literal["spoil", "materials", "equipment", "machinery"] = Field(
        default="spoil",
        description="Spoil or materials, equipment such as trucks, or heavy excavating machinery.",
        json_schema_extra=_labels(
            ["Excavated spoil", "Construction materials", "Equipment, trucks", "Heavy machinery"]
        ),
    )
    distance: float = Field(
        ge=0,
        description="From the edge of the excavation (the toe of a sloped side) [mm].",
    )
    pressure: float | None = Field(
        default=None, ge=0, description="Its surcharge on the ground [kPa] (for the shoring)."
    )


class Excavation(_Model):
    """An excavation for the foundations or a basement: its depth, how its sides are kept, the
    loads and buildings beside it and the ground water at its base. The checks are the
    code pack's rules of excavation work; the design of an embedded wall and its supports is a
    separate (planned) feature."""

    id: Id
    outline: list[Point2] | None = Field(
        default=None,
        min_length=3,
        description="Plan outline of its edge [[x, y], ...] mm (the foundations near it are "
        "checked against it).",
    )
    groundLevel: float | None = Field(
        default=None,
        title="Ground level",
        description="Of the adjacent ground [mm, project datum]; empty: the project's.",
    )
    bottomLevel: float = Field(
        title="Bottom level", description="Deepest point of the excavation [mm, project datum]."
    )
    permanent: bool = Field(
        default=False, description="A permanent excavation (kept after the work)."
    )
    support: ExcavationSupport = Field(  # type: ignore[valid-type]
        default="sloped",
        title="Sides",
        description="How its sides are kept.",
        json_schema_extra=_labels(list(EXCAVATION_SUPPORTS.values())),
    )
    sideSlope: float | None = Field(
        default=None,
        gt=0,
        title="Side slope (H per V)",
        description="Horizontal per vertical of a sloped side, or the average of a stepped one.",
    )
    stepHeight: Length | None = Field(
        default=None, title="Step height", description="Highest step of a stepped side [mm]."
    )
    sheetPileTop: float | None = Field(
        default=None,
        title="Sheet piles above ground",
        description="Height of the sheet piles above the natural ground [mm].",
    )
    cutoffLevel: float | None = Field(
        default=None,
        title="Cut-off toe level",
        description="Toe of the sheet piles or cut-off wall [mm, project datum] (seepage).",
    )
    guardRail: bool = Field(
        default=False,
        title="Guard rail",
        description="A guard rail or solid enclosure at least the code's height along the "
        "open sides.",
    )
    accessPrecluded: bool = Field(
        default=False,
        title="Access precluded",
        description="Access to the area round the excavation is precluded (no guard rail needed).",
    )
    designWaterTable: float | None = Field(
        default=None,
        title="Design water table",
        description="Depth below the adjacent ground [m]; empty: the nearest borehole's.",
    )
    dewatered: bool = Field(
        default=False,
        description="The ground water is lowered below the bottom while the excavation is open.",
    )
    erraticSoil: bool = Field(
        default=False,
        title="Erratic soil",
        description="The soil is erratic (the soft soil of the soil report is found by itself).",
    )
    piling: bool = Field(
        default=False,
        description="Piles are bored or driven near the adjoining structures.",
    )
    loads: list[ExcavationLoad] = Field(
        default_factory=list, description="Spoil, materials and machinery beside it."
    )
    adjoining: list[AdjoiningStructure] = Field(
        default_factory=list, title="Adjoining structures", description="Buildings next to it."
    )
    note: str | None = None

    @model_validator(mode="after")
    def _levels(self) -> Excavation:
        ids = [a.id for a in self.adjoining]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"{self.id}: duplicate adjoining structures {', '.join(duplicates)}")
        return self


class Formwork(_Model):
    """The slab formwork the design checks against the code pack's loads and timber stress:
    sheeting on joists on posts."""

    slabThickness: Length | None = Field(
        default=None,
        title="Slab thickness",
        description="[mm]; empty: the thickest slab type of 04 Objects.",
    )
    material: Id | None = Field(
        default=None,
        description="Concrete material id (03 Materials): a unit weight above the code's wet "
        "concrete weight governs.",
    )
    liveLoad: float | None = Field(
        default=None,
        gt=0,
        title="Workers and placing",
        description="Live load of workmen and vibrating [kPa]; empty: the heavy end of the "
        "code pack's range.",
    )
    sheeting: Length = Field(default=25, description="Sheeting thickness [mm].")
    joistWidth: Length = Field(default=50, title="Joist width", description="[mm]")
    joistDepth: Length = Field(default=100, title="Joist depth", description="[mm]")
    joistSpacing: Length = Field(default=500, title="Joist spacing", description="[mm]")
    joistSpan: Length = Field(
        default=1000, title="Joist span", description="Between ledgers or posts [mm]."
    )
    span: Length | None = Field(
        default=None,
        description="Largest clear span the formwork bridges [mm] (the standard sizes apply up "
        "to the code's limit).",
    )
    postKind: Literal["bamboo", "timber", "ballie", "steel"] = Field(
        default="timber",
        title="Posts",
        json_schema_extra=_labels(["Bamboo", "Timber", "Ballie", "Steel centering"]),
    )
    postHeight: Length = Field(default=3000, title="Post height", description="[mm]")
    postDiameter: Length | None = Field(
        default=None,
        title="Post diameter",
        description="Least diameter of a round post [mm] (steel: empty).",
    )


MACHINE_KINDS = {
    "periodic": "Reciprocating engine or compressor (periodic force)",
    "impact": "Forge hammer or punch press (impact)",
    "rotary": "Turbine, generator or rotary compressor (high speed)",
}

MACHINE_STIFFNESS = {
    "barkan": "From E of the soil (Barkan)",
    "subgrade": "From the subgrade modulus ks",
    "plateLoad": "From a repeated plate load test",
    "resonance": "From a resonance test",
    "given": "Given",
}


class MachineFoundation(_Model):
    """A block foundation under a machine or generator: the soil under it as one spring and
    dashpot, checked by the code pack's machine foundation rules (resonance, amplitudes, static
    pressure, eccentricity, ground water). Masses in t, forces in kN, stiffness in kN/m."""

    id: Id = Field(description="Its mark, e.g. MF1.")
    name: str | None = Field(default=None, description="The machine, e.g. 'Generator 500 kVA'.")
    kind: Literal["periodic", "impact", "rotary"] = Field(
        default="rotary",
        description="What the machine produces.",
        json_schema_extra=_labels(list(MACHINE_KINDS.values())),
    )
    form: Literal["block", "box", "wall", "frame"] = Field(
        default="block",
        description="Block, box (hollow block), wall or framed foundation; the method takes it "
        "as a rigid block on the soil.",
        json_schema_extra=_labels(["Block", "Box", "Wall", "Framed"]),
    )
    center: Point2 | None = Field(
        default=None, description="Plan centre of the base [x, y] mm (the nearest borehole)."
    )
    length: Length = Field(description="Base length L [mm].")
    width: Length = Field(description="Base width B [mm].")
    height: Length = Field(description="Depth of the block [mm].")
    foundingLevel: float = Field(
        title="Founding level", description="Underside of the block [mm, project datum]."
    )
    material: Id | None = Field(
        default=None,
        description="Concrete material id (03 Materials) for the block's weight; empty: the "
        "project's concrete.",
    )
    blockMass: float | None = Field(
        default=None,
        gt=0,
        title="Block mass",
        description="Mass of the block [t]; empty: from its size (a box or frame: enter it).",
    )
    machineMass: float = Field(gt=0, title="Machine mass", description="[t]")
    speed: float = Field(
        gt=0,
        title="Operating speed",
        description="[rpm]; a hammer: blows per minute.",
    )
    machineOffset: Point2 | None = Field(
        default=None,
        title="Machine offset",
        description="Centre of gravity of the machine from the centre of the base, along L "
        "and B [mm].",
    )
    force: float | None = Field(
        default=None,
        ge=0,
        title="Unbalanced force",
        description="Vertical amplitude of the unbalanced force at the operating speed [kN].",
    )
    unbalance: float | None = Field(
        default=None,
        ge=0,
        description="Rotating unbalance m·e [kg·m]: the force m·e·ω² at any speed (instead of "
        "the force).",
    )
    horizontalForce: float | None = Field(
        default=None, ge=0, title="Horizontal force", description="[kN] at the operating speed."
    )
    horizontalStiffness: float | None = Field(
        default=None,
        gt=0,
        title="Horizontal stiffness",
        description="[kN/m]: the horizontal mode is checked only with it (the code's methods "
        "give the vertical spring).",
    )
    impulse: float | None = Field(
        default=None,
        gt=0,
        description="Impulse of one blow [kN·s] (hammers: the amplitude I / (m ωn)).",
    )
    impactLoad: float | None = Field(
        default=None,
        ge=0,
        title="Impact live load",
        description="Live load causing the impact [kN] (for the impact rule).",
    )
    movingEquipment: bool = Field(
        default=False,
        title="Crane or moving equipment",
        description="It carries cranes, heavy machinery or moving equipment (impact designed for).",
    )
    looseGranular: bool = Field(
        default=False,
        title="Loose granular soil",
        description="It bears on loose granular soil (impact designed for).",
    )
    allowableAmplitude: float | None = Field(
        default=None,
        gt=0,
        title="Maker's amplitude",
        description="Permissible amplitude given by the manufacturer [mm]; empty: the code's.",
    )
    stiffnessMethod: Literal["barkan", "subgrade", "plateLoad", "resonance", "given"] = Field(
        default="barkan",
        title="Spring from",
        json_schema_extra=_labels(list(MACHINE_STIFFNESS.values())),
    )
    E: float | None = Field(
        default=None,
        gt=0,
        title="Young's modulus E",
        description="Of the soil from a laboratory test [MPa]; empty: G below, else 1 Soil "
        "Report's layers under the base.",
    )
    G: float | None = Field(
        default=None,
        gt=0,
        title="Shear modulus G",
        description="Of the soil from a torsional test [MPa]: E = 2G(1 + μ).",
    )
    poisson: float = Field(
        default=0.35, gt=0, lt=0.5, title="Poisson's ratio μ", description="Of the soil."
    )
    ks: float | None = Field(
        default=None,
        gt=0,
        title="Subgrade modulus ks",
        description="[kN/m³]; empty: 1 Soil Report's at the nearest borehole.",
    )
    plateStiffness: float | None = Field(
        default=None, gt=0, title="Plate stiffness kp", description="[kN/m]"
    )
    plateWidth: float | None = Field(default=None, gt=0, title="Plate width Bp", description="[mm]")
    cohesive: bool | None = Field(
        default=None,
        description="Plate load test in cohesive soil; empty: from the soil report's layer.",
    )
    testFrequency: float | None = Field(
        default=None, gt=0, title="Resonance frequency", description="Of the test [Hz]."
    )
    testMass: float | None = Field(
        default=None, gt=0, title="Vibrator mass", description="Of the test [t]."
    )
    stiffness: float | None = Field(
        default=None, gt=0, description="Given vertical spring k [kN/m]."
    )
    damping: float | None = Field(
        default=None, gt=0, lt=1, title="Damping factor D", description="Empty: from below."
    )
    decrement: float | None = Field(
        default=None, gt=0, title="Logarithmic decrement δ", description="Of a test."
    )
    workLost: float | None = Field(
        default=None, gt=0, title="Work lost ΔW", description="Hysteresis loop of a test."
    )
    workDone: float | None = Field(
        default=None, gt=0, title="Work done W", description="Of the same loop."
    )
    participatingMass: float | None = Field(
        default=None,
        ge=0,
        title="Participating soil ms / mf",
        description="Empty: the code's range is enveloped.",
    )
    designWaterTable: float | None = Field(
        default=None,
        title="Design water table",
        description="Depth below the ground [m]; empty: the substructure's, else the borehole's.",
    )
    adjacentFoundingLevel: float | None = Field(
        default=None,
        title="Adjacent foundations",
        description="Founding level of the adjacent building's foundations [mm, project datum].",
    )
    separated: bool = Field(
        default=True,
        description="Separated from the building's foundations and floors by a gap or joint.",
    )
    note: str | None = None


class EarthPressure(_Model):
    """The basement walls of the building in the analysis model (load case H)."""

    basementWalls: bool = Field(
        default=True,
        title="Earth pressure on basement walls",
        description="Load the walls of 6 BIM whose type is a basement wall (and the walls the "
        "retaining walls name) with the earth and water pressure at rest, as load case H.",
    )
    surcharge: float = Field(
        default=10.0, ge=0, description="On the ground round the building [kPa]."
    )
    designWaterTable: float | None = Field(
        default=None,
        title="Design water table",
        description="Depth below the finished ground [m]; empty: each borehole's measured level.",
    )
    k0Cohesive: float = Field(
        default=0.6,
        gt=0,
        le=1.5,
        title="K0 of clay",
        description="At-rest coefficient of a layer without φ' (given by cu only).",
    )


def pile_layout_problem(
    piles: list[list[float]], diameter: float, length: float, width: float
) -> str | None:
    """What is physically wrong with piles of ``diameter`` at offsets ``piles`` [mm] in a cap
    ``length`` x ``width``: a pile not wholly within the cap, or two piles overlapping (centres
    closer than one diameter); None when they fit. The code minimum spacing is a design check,
    not a validation rule."""
    half_l, half_w = length / 2, width / 2
    for dx, dy in piles:
        if abs(dx) > half_l - diameter / 2 + 1e-6 or abs(dy) > half_w - diameter / 2 + 1e-6:
            return f"the pile at [{dx:g}, {dy:g}] does not lie within the cap"
    for k, (x0, y0) in enumerate(piles):
        for x1, y1 in piles[k + 1 :]:
            if math.hypot(x1 - x0, y1 - y0) < diameter - 1e-6:
                if (x0, y0) == (x1, y1):
                    return f"two piles at the same position [{x0:g}, {y0:g}]"
                return (
                    f"the piles at [{x0:g}, {y0:g}] and [{x1:g}, {y1:g}] overlap: their centres "
                    f"are closer than the diameter {diameter:g} mm"
                )
    return None


class Substructure(_Model):
    schema_: Literal["saengine.substructure/1"] = Field(default=SCHEMA_ID, alias="schema")
    foundations: list[Foundation] = Field(default_factory=list)
    pileTypes: list[PileType] = Field(default_factory=list, title="Pile types")
    pileGrid: PileGrid | None = Field(
        default=None,
        title="Pile grid",
        description="The grid the piles are set out on, independent of the building's grid.",
    )
    piles: list[Pile] = Field(
        default_factory=list,
        description="Every pile, placed in plan; a pile cap lists the ones it stands on.",
    )
    tieBeams: list[TieBeam] = Field(default_factory=list, title="Tie beams")
    loadTests: list[PileLoadTest] = Field(
        default_factory=list,
        title="Pile load tests",
        description="Static load tests at the site: their curves give the safe loads, and a "
        "compression test lets the pile type's capacity take the factor of safety with a test.",
    )
    groundSlabs: list[GroundSlab] = Field(
        default_factory=list,
        title="Slabs on grade",
        description="Ground-bearing slabs on the compacted ground.",
    )
    retainingWalls: list[RetainingWall] = Field(
        default_factory=list,
        title="Retaining walls",
        description="Cantilever retaining walls and basement walls, designed per metre run.",
    )
    earthPressure: EarthPressure = Field(
        default_factory=EarthPressure,
        title="Earth pressure",
        description="The earth and water pressure on the building's basement walls (case H).",
    )
    design: Design = Field(default_factory=Design)
    excavations: list[Excavation] = Field(
        default_factory=list,
        description="Excavations for the foundations and basements: their sides, the loads and "
        "buildings beside them, and the ground water at the base.",
    )
    formwork: Formwork | None = Field(
        default=None,
        description="The slab formwork, checked against the code pack's construction loads.",
    )
    machineFoundations: list[MachineFoundation] = Field(
        default_factory=list,
        title="Machine foundations",
        description="Block foundations of machines and generators under their dynamic forces.",
    )

    @model_validator(mode="before")
    @classmethod
    def _upgrade(cls, data: Any, info: ValidationInfo) -> Any:
        """Pile caps of the earlier format (a pile type and pile offsets from the cap's centre)
        are read as piles placed in plan (:func:`upgrade_pile_caps`)."""
        positions = (info.context or {}).get("positions") if info is not None else None
        return upgrade_pile_caps(data, positions) if isinstance(data, dict) else data

    @model_validator(mode="after")
    def _references(self) -> Substructure:
        for name, items in (
            ("foundations", self.foundations),
            ("pile types", self.pileTypes),
            ("piles", self.piles),
            ("load tests", self.loadTests),
            ("tie beams", self.tieBeams),
            ("slabs on grade", self.groundSlabs),
            ("retaining walls", self.retainingWalls),
            ("excavations", self.excavations),
            ("machine foundations", self.machineFoundations),
        ):
            ids = [i.id for i in items]
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate {name} ids: {', '.join(duplicates)}")
        types = {p.id for p in self.pileTypes}
        for pile in self.piles:
            if pile.type not in types:
                raise ValueError(f"{pile.id}: unknown pile type '{pile.type}'")
        for test in self.loadTests:
            if test.pileType not in types:
                raise ValueError(f"load test {test.id}: unknown pile type '{test.pileType}'")
        piles = {p.id: p for p in self.piles}
        carried: dict[str, str] = {}
        capped: dict[str, str] = {}
        for f in self.foundations:
            for column in f.columns:
                if column in carried:
                    raise ValueError(f"{column} is carried by both {carried[column]} and {f.id}")
                carried[column] = f.id
            for pile_id in f.piles or []:
                if pile_id not in piles:
                    raise ValueError(f"{f.id}: unknown pile '{pile_id}'")
                if pile_id in capped:
                    raise ValueError(f"pile {pile_id} is under both {capped[pile_id]} and {f.id}")
                capped[pile_id] = f.id
            kinds = sorted({piles[p].type for p in f.piles or []})
            if len(kinds) > 1:
                raise ValueError(
                    f"{f.id}: its piles are of more than one type ({', '.join(kinds)})"
                )
        foundations = {f.id for f in self.foundations}
        for tie in self.tieBeams:
            for end in (tie.from_, tie.to):
                if end not in foundations:
                    raise ValueError(f"{tie.id}: unknown foundation '{end}'")
            if tie.from_ == tie.to:
                raise ValueError(f"{tie.id}: ties {tie.to} to itself")
        return self

    def foundation(self, foundation_id: str) -> Foundation | None:
        return next((f for f in self.foundations if f.id == foundation_id), None)

    def pile_type(self, pile_id: str | None) -> PileType | None:
        return next((p for p in self.pileTypes if p.id == pile_id), None)

    def pile(self, pile_id: str) -> Pile | None:
        return next((p for p in self.piles if p.id == pile_id), None)

    def cap_piles(self, foundation: Foundation) -> list[Pile]:
        """The piles a pile cap stands on, in its order."""
        by_id = {p.id: p for p in self.piles}
        return [by_id[p] for p in foundation.piles or [] if p in by_id]

    def cap_pile_type(self, foundation: Foundation) -> PileType | None:
        """The pile type of a pile cap's piles (one per cap)."""
        piles = self.cap_piles(foundation)
        return self.pile_type(piles[0].type) if piles else None

    def pile_offsets(self, foundation: Foundation) -> list[list[float]]:
        """A pile cap's piles as offsets [[u, v], ...] mm from its centre in its local axes."""
        if foundation.center is None:
            return []
        a = math.radians(foundation.rotation)
        c, s = math.cos(a), math.sin(a)
        x0, y0 = foundation.center
        return [
            [(x - x0) * c + (y - y0) * s, -(x - x0) * s + (y - y0) * c]
            for x, y in (p.position for p in self.cap_piles(foundation))
        ]

    def capped(self) -> dict[str, str]:
        """The cap of each pile under one: {pile id: foundation id}."""
        return {p: f.id for f in self.foundations for p in f.piles or []}


#: BNBC 2020 Part 6 Sec 3.10.1.19 and 3.10.1.30: piles at least 2.5 diameters and 750 mm apart.
MIN_SPACING_DIAMETERS = 2.5
MIN_SPACING = 750.0


def cap_outline(foundation: Foundation) -> list[list[float]]:
    """The plan corners [mm] of a pile cap (or a footing) with a centre and a size."""
    if foundation.center is None or not foundation.length or not foundation.width:
        return []
    a = math.radians(foundation.rotation)
    c, s = math.cos(a), math.sin(a)
    x0, y0 = foundation.center
    half_l, half_w = foundation.length / 2, foundation.width / 2
    return [
        [x0 + u * c - v * s, y0 + u * s + v * c]
        for u, v in ((-half_l, -half_w), (half_l, -half_w), (half_l, half_w), (-half_l, half_w))
    ]


def pile_layout_warnings(substructure: Substructure) -> list[str]:
    """What is wrong with the piles placed in plan, before any design: a pile under no cap (or
    inside a cap that does not list it), a cap's pile not wholly within it, and two piles
    overlapping or closer than 2.5 diameters and 750 mm (BNBC 2020 Part 6 Secs 3.10.1.19,
    3.10.1.30; friction piles' 3 diameters are checked per cap by its design)."""
    warnings: list[str] = []
    capped = substructure.capped()
    types = {p.id: p for p in substructure.pileTypes}
    caps = {f.id: f for f in substructure.foundations if f.type == "pileCap"}
    for pile in substructure.piles:
        diameter = types[pile.type].diameter if pile.type in types else 0.0
        cap = caps.get(capped.get(pile.id, ""))
        if cap is None:
            inside = next(
                (f.id for f in caps.values() if _inside_rectangle(pile.position, f, -diameter / 2)),
                None,
            )
            warnings.append(
                f"{pile.id}: inside the outline of {inside} but not one of its piles"
                if inside
                else f"{pile.id}: under no pile cap"
            )
        elif not _inside_rectangle(pile.position, cap, diameter / 2):
            warnings.append(f"{pile.id}: not wholly within its pile cap {cap.id}")
    piles = substructure.piles
    for k, a in enumerate(piles):
        for b in piles[k + 1 :]:
            d = max(
                types[a.type].diameter if a.type in types else 0.0,
                types[b.type].diameter if b.type in types else 0.0,
            )
            distance = math.dist(a.position, b.position)
            need = max(MIN_SPACING_DIAMETERS * d, MIN_SPACING)
            if distance < d - 1e-6:
                warnings.append(
                    f"{a.id} and {b.id} overlap: their centres are {distance:.0f} mm apart, less "
                    f"than the diameter {d:.0f} mm"
                )
            elif distance < need - 0.5:
                warnings.append(
                    f"{a.id} and {b.id} are {distance:.0f} mm apart, less than {need:.0f} mm "
                    "(2.5 D and 750 mm, BNBC 2020 Part 6 Secs 3.10.1.19 and 3.10.1.30)"
                )
    return warnings


def _inside_rectangle(point: list[float], foundation: Foundation, margin: float) -> bool:
    """Whether ``point`` lies at least ``margin`` [mm] inside a cap's rectangle (a negative
    margin: within that distance outside it)."""
    if foundation.center is None or not foundation.length or not foundation.width:
        return False
    a = math.radians(foundation.rotation)
    dx, dy = point[0] - foundation.center[0], point[1] - foundation.center[1]
    u = dx * math.cos(a) + dy * math.sin(a)
    v = -dx * math.sin(a) + dy * math.cos(a)
    return (
        abs(u) <= foundation.length / 2 - margin + 1e-6
        and abs(v) <= foundation.width / 2 - margin + 1e-6
    )


#: The marks the upgrade of an earlier file gives the piles: PL1, PL2, ...
PILE_PREFIX = "PL"


def _is_point(value: Any) -> bool:
    return (
        isinstance(value, list | tuple)
        and len(value) == 2
        and all(isinstance(v, int | float) for v in value)
    )


def _old_cap(f: Any) -> bool:
    return (
        isinstance(f, dict)
        and f.get("type") == "pileCap"
        and ("pileType" in f or any(_is_point(p) for p in f.get("piles") or []))
    )


def needs_upgrade(data: Any) -> bool:
    """Whether a substructure's JSON has pile caps of the earlier format: a ``pileType`` and
    ``piles`` as offsets [dx, dy] from the cap's centre."""
    foundations = data.get("foundations") if isinstance(data, dict) else None
    return isinstance(foundations, list) and any(_old_cap(f) for f in foundations)


def upgrade_pile_caps(
    data: dict[str, Any], positions: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The substructure's JSON ``data`` with the pile caps of the earlier format (a pile type
    and offsets from the cap's centre in its local axes) as piles placed in plan, each cap
    listing its piles by id (PL1, PL2, ...) and getting its centre. A cap without a centre had
    the centroid of its columns: ``positions`` gives the plan position of each column and wall
    {id: [x, y]} for that (a ``ValueError`` without it). ``data`` itself is not changed; it is
    returned as it is when there is nothing to upgrade."""
    if not needs_upgrade(data):
        return data
    data = dict(data)
    foundations = [dict(f) if isinstance(f, dict) else f for f in data.get("foundations") or []]
    piles = [dict(p) for p in data.get("piles") or [] if isinstance(p, dict)]
    taken = {str(p.get("id")) for p in piles}
    counter = itertools.count(1)
    for f in foundations:
        if not _old_cap(f):
            continue
        offsets = [p for p in f.get("piles") or [] if _is_point(p)]
        pile_type = f.pop("pileType", None)
        center = f.get("center")
        if not _is_point(center):
            known = [
                (float(p[0]), float(p[1]))
                for c in f.get("columns") or []
                if (p := (positions or {}).get(c)) is not None
            ]
            if not known:
                raise ValueError(
                    f"{f.get('id')}: a pile cap of an earlier version without a centre: its piles "
                    "are placed from its columns; open the project in 9 Substructure to bring it "
                    "up to date"
                )
            center = [sum(p[0] for p in known) / len(known), sum(p[1] for p in known) / len(known)]
            f["center"] = [round(center[0], 1), round(center[1], 1)]
        a = math.radians(float(f.get("rotation") or 0))
        c, s = math.cos(a), math.sin(a)
        ids: list[str] = []
        for dx, dy in offsets:
            pile_id = next(f"{PILE_PREFIX}{n}" for n in counter if f"{PILE_PREFIX}{n}" not in taken)
            taken.add(pile_id)
            piles.append(
                {
                    "id": pile_id,
                    "type": pile_type,
                    "position": [
                        round(center[0] + dx * c - dy * s, 1),
                        round(center[1] + dx * s + dy * c, 1),
                    ],
                }
            )
            ids.append(pile_id)
        f["piles"] = ids
    data["foundations"] = foundations
    data["piles"] = piles
    return data


def column_positions(building: Any) -> dict[str, list[float]]:
    """{id: [x, y]} of the columns and the middles of the walls of a building model (a
    :class:`~saengine.library.bim.BuildingModel`), for :func:`upgrade_pile_caps`."""
    positions: dict[str, list[float]] = {}
    for e in getattr(building, "elements", []):
        if getattr(e, "kind", None) == "column":
            positions.setdefault(e.id, [float(e.position[0]), float(e.position[1])])
        elif getattr(e, "kind", None) == "wall":
            positions.setdefault(e.id, [(e.start[0] + e.end[0]) / 2, (e.start[1] + e.end[1]) / 2])
    return positions


def polygon_area(points: list[list[float]]) -> float:
    """Signed area of a polygon [mm²] (counter-clockwise positive)."""
    return 0.5 * sum(
        a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1], strict=True)
    )


def default_substructure() -> Substructure:
    return Substructure()


def is_placeholder(data: Any) -> bool:
    """The file a new project starts with, before Part 9 had an editor."""
    return isinstance(data, dict) and data.get("schema") == 1 and data.get("part") == "substructure"


def parse(text: str | None, building: Any = None) -> Substructure:
    """The substructure of a file's text; an empty one for a missing file or the placeholder.
    Pile caps of an earlier version are read as piles placed in plan (``building``, the
    building model, places those without a centre: :func:`upgrade_pile_caps`). Raises
    ``ValueError`` (pydantic's ``ValidationError``) for an invalid file."""
    import json

    if not text or not text.strip():
        return default_substructure()
    data = json.loads(text)
    if is_placeholder(data):
        return default_substructure()
    context = {"positions": column_positions(building)} if building is not None else None
    return Substructure.model_validate(data, context=context)


def check(
    substructure: Substructure,
    building: Any = None,
    materials: MaterialLibrary | None = None,
    objects: Any = None,
) -> list[str]:
    """Problems with references into the other parts, which the schema alone cannot see: the
    columns and walls (``building``, a :class:`~saengine.library.bim.BuildingModel`), the
    concrete and bar materials (``materials``) and the tie beams' object types (``objects``,
    an :class:`~saengine.library.objects.ObjectLibrary`). Each part is checked when given."""
    problems: list[str] = []
    if building is not None:
        from saengine.library.bim import ColumnElement, WallElement

        bases = {e.id: e for e in building.elements if isinstance(e, ColumnElement | WallElement)}
        for f in substructure.foundations:
            for column in f.columns:
                element = bases.get(column)
                if element is None:
                    problems.append(f"{f.id}: '{column}' is not a column or wall of 6 BIM")
                elif isinstance(element, WallElement) and f.type != "strip":
                    problems.append(f"{f.id}: wall '{column}' can stand on a strip footing only")
        for r in substructure.retainingWalls:
            if r.wall is not None and not isinstance(bases.get(r.wall), WallElement):
                problems.append(f"{r.id}: '{r.wall}' is not a wall of 6 BIM")
    if materials is not None:

        def concrete(owner: str, material: str | None) -> None:
            if material is None:
                return
            m = materials.get(material)
            if m is None:
                problems.append(f"{owner}: unknown material '{material}'")
            elif m.category != Category.CONCRETE:
                problems.append(f"{owner}: material '{material}' is not concrete")

        def bars(owner: str, reinforcement: Any) -> None:
            if reinforcement is None:
                return
            m = materials.get(reinforcement.material)
            if m is None:
                problems.append(
                    f"{owner}: unknown reinforcement material '{reinforcement.material}'"
                )
            elif m.category != Category.REBAR:
                problems.append(f"{owner}: reinforcement material '{m.id}' is not rebar")

        for f in substructure.foundations:
            concrete(f.id, f.material)
            bars(f.id, f.reinforcement)
        for p in substructure.pileTypes:
            concrete(p.id, p.material)
            bars(p.id, p.reinforcement)
        for slab in substructure.groundSlabs:
            concrete(slab.id, slab.material)
            if slab.meshMaterial is not None:
                m = materials.get(slab.meshMaterial)
                if m is None or m.category != Category.REBAR:
                    problems.append(f"{slab.id}: mesh material '{slab.meshMaterial}' is not rebar")
        for r in substructure.retainingWalls:
            concrete(r.id, r.material)
            bars(r.id, r.reinforcement)
    if objects is not None:
        from saengine.library.objects import Beam

        types = {o.id: o for o in objects.objects}
        for tie in substructure.tieBeams:
            found = types.get(tie.type)
            if found is None:
                problems.append(f"{tie.id}: unknown object type '{tie.type}'")
            elif not isinstance(found, Beam):
                problems.append(f"{tie.id}: object type '{tie.type}' is not a beam")
    return problems
