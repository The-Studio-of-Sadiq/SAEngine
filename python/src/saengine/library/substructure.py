"""Substructure (``09 Substructure/substructure.json``): the foundations of the building.

Part 9 places the foundations under the columns and walls of the building model (Part 6) and
designs them under the support reactions of the analysis (Part 8) on the soil of the soil report
(Part 1): isolated, combined and strip footings, pile caps on piles, and rafts, with the tie
beams between them. The file stores only what the engineer decides (types, sizes, positions,
reinforcement, design choices); every computed value (soil pressure, pile loads, checks) is
worked out on demand (:func:`saengine.substructure.substructure_report`).

Units: mm for lengths, positions and levels (project datum), degrees for rotations, kPa for
pressures, kN/m³ for the modulus of subgrade reaction.
"""

from __future__ import annotations

import itertools
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from saengine.library.labels import field_title
from saengine.library.materials import Category, Id, MaterialLibrary
from saengine.library.objects import LinearReinforcement, PlanarReinforcement

SCHEMA_ID = "saengine.substructure/1"
SUBSTRUCTURE_FILE = "09 Substructure/substructure.json"

#: Founding depth below the finished ground when a foundation gives no founding level [mm].
DEFAULT_FOUNDING_DEPTH = 1500.0

Length = Annotated[float, Field(gt=0, description="[mm]")]
Point2 = Annotated[list[float], Field(min_length=2, max_length=2, description="[x, y] in mm.")]

FoundationType = Literal["isolated", "combined", "strip", "pileCap", "raft"]

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
        description="Plan position of the centre [x, y] mm (isolated and combined footings, "
        "pile caps); empty: the centroid of its columns.",
    )
    rotation: float = Field(default=0, description="Of its local x axis from the global X [°].")
    length: Length | None = Field(default=None, description="Along its local x [mm].")
    width: Length | None = Field(
        default=None, description="Along its local y; a strip footing: across its path [mm]."
    )
    thickness: Length | None = Field(default=None, description="[mm]")
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
    material: Id | None = Field(default=None, description="Concrete material id (03 Materials).")
    reinforcement: PlanarReinforcement | None = None
    pileType: Id | None = Field(default=None, title="Pile type", description="Pile caps.")
    piles: list[Point2] | None = Field(
        default=None,
        description="Pile positions [[dx, dy], ...] mm from the cap's centre, in its local axes.",
    )
    note: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> Foundation:
        kind = FOUNDATION_TYPES[self.type].lower()
        missing: list[str] = []
        if self.type in ("isolated", "combined", "pileCap"):
            missing = [n for n in ("length", "width", "thickness") if getattr(self, n) is None]
            if self.center is None and not self.columns:
                missing.append("center (or columns)")
        elif self.type == "strip":
            missing = [n for n in ("path", "width", "thickness") if getattr(self, n) is None]
        elif self.type == "raft":
            missing = [n for n in ("outline", "thickness") if getattr(self, n) is None]
        if self.type == "pileCap":
            if self.pileType is None:
                missing.append("pileType")
            if not self.piles:
                missing.append("piles")
        if missing:
            raise ValueError(f"{self.id}: a {kind} needs {', '.join(missing)}")
        duplicates = sorted({c for c in self.columns if self.columns.count(c) > 1})
        if duplicates:
            raise ValueError(f"{self.id}: {', '.join(duplicates)} listed twice")
        if self.path is not None and any(
            math.dist(a, b) < 1 for a, b in itertools.pairwise(self.path)
        ):
            raise ValueError(f"{self.id}: two consecutive points of the path coincide")
        if self.outline is not None and abs(polygon_area(self.outline)) < 1:
            raise ValueError(f"{self.id}: the outline encloses no area")
        return self

    def founding_level(self, ground_level: float) -> float:
        """The level of the underside [mm]: its own, or :data:`DEFAULT_FOUNDING_DEPTH` below
        ``ground_level``."""
        if self.foundingLevel is not None:
            return self.foundingLevel
        return ground_level - DEFAULT_FOUNDING_DEPTH


class PileType(_Model):
    """A pile: kind, size and reinforcement."""

    id: Id
    kind: Literal["bored", "driven"] = Field(
        default="bored",
        description="Bored cast-in-situ or driven precast.",
        json_schema_extra=_labels(["Bored (cast in situ)", "Driven (precast)"]),
    )
    diameter: Length = Field(description="Diameter (driven square piles: the side) [mm].")
    length: Length = Field(description="Below the underside of the cap [mm].")
    material: Id = Field(description="Concrete material id (03 Materials).")
    reinforcement: LinearReinforcement | None = None


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
        "soil report's.",
    )


class Design(_Model):
    """Design choices of the substructure."""

    pileCapacity: Literal["soilReport", "bnbcSpt"] = Field(
        default="soilReport",
        title="Pile capacity",
        description="From the soil report's per-layer skin friction and end bearing (Part 1), "
        "or from the SPT N values by BNBC 2020 Eqs 6.3.29 and 6.3.31-32.",
        json_schema_extra=_labels(["Soil report (per layer)", "BNBC 2020 SPT equations"]),
    )
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
    tieBeams: list[TieBeam] = Field(default_factory=list, title="Tie beams")
    design: Design = Field(default_factory=Design)

    @model_validator(mode="after")
    def _references(self) -> Substructure:
        for name, items in (
            ("foundations", self.foundations),
            ("pile types", self.pileTypes),
            ("tie beams", self.tieBeams),
        ):
            ids = [i.id for i in items]
            duplicates = sorted({i for i in ids if ids.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate {name} ids: {', '.join(duplicates)}")
        piles = {p.id: p for p in self.pileTypes}
        carried: dict[str, str] = {}
        for f in self.foundations:
            for column in f.columns:
                if column in carried:
                    raise ValueError(f"{column} is carried by both {carried[column]} and {f.id}")
                carried[column] = f.id
            if f.type != "pileCap":
                continue
            pile = piles.get(f.pileType or "")
            if pile is None:
                raise ValueError(f"{f.id}: unknown pile type '{f.pileType}'")
            problem = pile_layout_problem(f.piles or [], pile.diameter, f.length or 0, f.width or 0)
            if problem:
                raise ValueError(f"{f.id}: {problem}")
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


def parse(text: str | None) -> Substructure:
    """The substructure of a file's text; an empty one for a missing file or the placeholder.
    Raises ``ValueError`` (pydantic's ``ValidationError``) for an invalid file."""
    import json

    if not text or not text.strip():
        return default_substructure()
    data = json.loads(text)
    if is_placeholder(data):
        return default_substructure()
    return Substructure.model_validate(data)


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
