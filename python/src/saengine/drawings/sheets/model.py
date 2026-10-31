"""What the drawing sheets draw: the building's plan geometry and the detailed members, as plain
data (real mm; elevations in mm).

:mod:`saengine.drawings.sheets.project` fills it from a project's files (and from the detailing
model when there is one); tests fill it by hand. Nothing here reads files or computes code
rules: the bars, their lengths and their zones are what the detailing model gives, drawn as
they are.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from saengine.drawings.sheets.layout import TitleInfo

Point = tuple[float, float]


def bar_text(count: int, dia: float) -> str:
    return f"{count}Ø{dia:g}"


@dataclass
class Mesh:
    """Bars at a spacing: ``Ø10@150``."""

    dia: float
    spacing: float
    mark: str = ""
    legs: float = 0.0  # the bars' bent legs at each end (a U bar), 0: straight
    count: int | None = None  # the number of bars the detailing model gives (None: by spacing)

    @property
    def text(self) -> str:
        return f"Ø{self.dia:g}@{self.spacing:g}"


# ─────────────────────────────────── plan geometry ───────────────────────────────────


@dataclass
class Grid:
    label: str
    position: float


@dataclass
class Level:
    id: str
    name: str
    elevation: float


@dataclass
class PlanColumn:
    id: str
    mark: str
    x: float
    y: float
    bottom: float
    top: float
    b: float  # along the section's x (or the diameter of a round column)
    h: float
    rotation: float = 0.0
    round: bool = False

    def outline(self) -> list[Point]:
        if self.round:
            r = self.b / 2
            return [
                (self.x + r * math.cos(a), self.y + r * math.sin(a))
                for a in (math.radians(d) for d in range(0, 360, 10))
            ]
        c, s = math.cos(math.radians(self.rotation)), math.sin(math.radians(self.rotation))
        pts = []
        for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            du, dv = u * self.b / 2, v * self.h / 2
            pts.append((self.x + du * c - dv * s, self.y + du * s + dv * c))
        return pts

    def extent_along(self, direction: Point) -> float:
        """Half the column's width along the unit ``direction``."""
        if self.round:
            return self.b / 2
        pts = self.outline()
        return max(
            abs((p[0] - self.x) * direction[0] + (p[1] - self.y) * direction[1]) for p in pts
        )


@dataclass
class PlanBeam:
    id: str
    mark: str
    start: Point
    end: Point
    width: float
    depth: float
    elevation: float


@dataclass
class PlanWall:
    id: str
    mark: str
    start: Point
    end: Point
    thickness: float
    bottom: float
    top: float


@dataclass
class PlanSlab:
    id: str
    mark: str
    boundary: list[Point]
    thickness: float
    elevation: float
    openings: list[list[Point]] = field(default_factory=list)


@dataclass
class PlanStair:
    id: str
    mark: str
    base: float  # elevation of the foot
    top: float
    flights: list[list[Point]]  # outlines of the flights in plan
    landings: list[list[Point]] = field(default_factory=list)
    treads: list[tuple[Point, Point]] = field(default_factory=list)
    arrow: list[Point] = field(default_factory=list)  # the walking line, foot to head


@dataclass
class PlanFooting:
    id: str
    mark: str
    outline: list[Point]
    top: float
    piles: list[tuple[Point, float]] = field(default_factory=list)  # centre, diameter


@dataclass
class PlanPile:
    """A pile placed in plan, with its mark and the cap it is under ("" for none)."""

    mark: str
    centre: Point
    diameter: float
    cap: str = ""


@dataclass
class PileGridPlan:
    """The pile grid: its origin and rotation [°] and its lines along its own axes."""

    origin: Point
    rotation: float
    x: list[Grid] = field(default_factory=list)
    y: list[Grid] = field(default_factory=list)

    def point(self, x: float, y: float) -> Point:
        a = math.radians(self.rotation)
        return (
            self.origin[0] + x * math.cos(a) - y * math.sin(a),
            self.origin[1] + x * math.sin(a) + y * math.cos(a),
        )


@dataclass
class Building:
    grids_x: list[Grid] = field(default_factory=list)  # lines at x = position (labels A, B..)
    grids_y: list[Grid] = field(default_factory=list)  # lines at y = position (labels 1, 2..)
    levels: list[Level] = field(default_factory=list)
    columns: list[PlanColumn] = field(default_factory=list)
    beams: list[PlanBeam] = field(default_factory=list)
    walls: list[PlanWall] = field(default_factory=list)
    slabs: list[PlanSlab] = field(default_factory=list)
    stairs: list[PlanStair] = field(default_factory=list)
    footings: list[PlanFooting] = field(default_factory=list)
    piles: list[PlanPile] = field(default_factory=list)
    pile_grid: PileGridPlan | None = None
    north: float = 0.0  # north from the plan's +y, degrees counter-clockwise

    def level(self, level_id: str) -> Level | None:
        return next((lv for lv in self.levels if lv.id == level_id), None)


# ─────────────────────────────────── detailed members ───────────────────────────────────


@dataclass
class BeamBar:
    """A bar of a beam elevation: ``count`` bars of ``dia`` from ``start`` to ``end`` along the
    beam (mm from the beam line's start, anchorages included), with legs bent down (top bars)
    or up (bottom bars) at the ends."""

    mark: str
    dia: float
    count: int
    start: float
    end: float
    face: str = "top"  # top | bottom
    row: int = 1  # 1: the outer layer, 2: the next
    leg_start: float = 0.0
    leg_end: float = 0.0
    note: str = ""  # "lap 800", "cut-off", ...
    cut_length: float | None = None  # the cutting length of the detailing model ("length")
    bbs_length: float | None = None  # the cutting length the BBS lists (rounded there)

    @property
    def length(self) -> float:
        """The bar's run and legs as drawn (outside dimensions) [mm]; the cutting length is
        ``cut_length``."""
        return self.end - self.start + self.leg_start + self.leg_end

    @property
    def text(self) -> str:
        return bar_text(self.count, self.dia)


@dataclass
class LinkZone:
    start: float
    end: float
    dia: float
    spacing: float
    legs: int = 2
    mark: str = ""

    @property
    def count(self) -> int:
        return math.floor((self.end - self.start) / self.spacing + 1e-6) + 1

    @property
    def text(self) -> str:
        legs = f"{self.legs}L-" if self.legs != 2 else ""
        return f"{legs}Ø{self.dia:g}@{self.spacing:g}"


@dataclass
class Support:
    """A support of a beam: its faces along the beam (mm from the beam line's start)."""

    start: float
    end: float
    label: str = ""

    @property
    def centre(self) -> float:
        return (self.start + self.end) / 2


@dataclass
class BeamDetail:
    mark: str
    members: list[str]
    level: str  # level name (several, by commas, when identical beam lines are merged)
    width: float
    depth: float
    cover: float
    length: float  # the beam line from its start to its end (support centres) [mm]
    supports: list[Support] = field(default_factory=list)
    bars: list[BeamBar] = field(default_factory=list)
    links: list[LinkZone] = field(default_factory=list)
    sections: list[tuple[str, float]] = field(default_factory=list)  # name, position
    slab: float = 0.0  # slab thickness drawn at the top (0: none)

    def bars_at(self, x: float) -> list[BeamBar]:
        return [b for b in self.bars if b.start - 1e-6 <= x <= b.end + 1e-6]

    def link_at(self, x: float) -> LinkZone | None:
        return next((z for z in self.links if z.start - 1e-6 <= x <= z.end + 1e-6), None)


NOT_DESIGNED = "NOT DESIGNED"
"""What a member without reinforcement shows where its bars would be: never "-" on a sheet."""


@dataclass
class ColumnSection:
    """A column's section over one storey."""

    b: float
    h: float
    cover: float
    bars: list[tuple[int, float]]  # (count, dia) around the perimeter
    tie_dia: float
    tie_spacing: float
    round: bool = False
    legs_x: int = 2  # tie legs running along x (counted along y)
    legs_y: int = 2
    zone_length: float | None = None  # lo [mm]
    zone_spacing: float | None = None  # so [mm]
    splice: str = ""  # "lap 1000 at mid-height", ...
    marks: list[str] = field(default_factory=list)

    @property
    def size_text(self) -> str:
        return f"Ø{self.b:g}" if self.round else f"{self.b:g}x{self.h:g}"

    @property
    def designed(self) -> bool:
        """Whether the section has bars: a column type without reinforcement (one that was never
        designed) has none, and its cell says so rather than showing an empty section."""
        return bool(self.bars)

    @property
    def bars_text(self) -> str:
        return " + ".join(bar_text(n, d) for n, d in self.bars) or NOT_DESIGNED

    @property
    def ties_text(self) -> list[str]:
        if self.zone_spacing and abs(self.zone_spacing - self.tie_spacing) < 0.5:
            # the same spacing in lo and elsewhere: one spacing over the whole height
            return [f"Ø{self.tie_dia:g}@{self.tie_spacing:g} throughout"]
        if self.zone_spacing and self.zone_length:
            return [
                f"Ø{self.tie_dia:g}@{self.zone_spacing:g} in lo {self.zone_length:g}",
                f"Ø{self.tie_dia:g}@{self.tie_spacing:g} elsewhere",
            ]
        return [f"Ø{self.tie_dia:g}@{self.tie_spacing:g}"]

    def key(self) -> tuple[Any, ...]:
        return (
            self.b,
            self.h,
            self.round,
            self.cover,
            tuple(self.bars),
            self.tie_dia,
            self.tie_spacing,
            self.zone_length,
            self.zone_spacing,
            self.legs_x,
            self.legs_y,
        )


@dataclass
class ColumnLine:
    """Columns stacked on one plan position: a mark and its section per storey (level id of
    the storey's top)."""

    mark: str
    members: list[str]
    sections: dict[str, ColumnSection] = field(default_factory=dict)


@dataclass
class TopBar:
    """Top bars over a support of a slab: drawn from ``start`` to ``end`` in plan."""

    start: Point
    end: Point
    mesh: Mesh
    label: str = ""


@dataclass
class SlabDetail:
    id: str
    mark: str
    boundary: list[Point]
    thickness: float
    cover: float
    level: str  # level id
    bottom_x: Mesh | None = None
    bottom_y: Mesh | None = None
    top_x: Mesh | None = None
    top_y: Mesh | None = None
    top_bars: list[TopBar] = field(default_factory=list)
    openings: list[list[Point]] = field(default_factory=list)
    bottom_runs: list[TopBar] = field(default_factory=list)  # bottom bars with their extents


@dataclass
class FootingDetail:
    mark: str
    members: list[str]
    length: float  # along x
    width: float
    thickness: float
    cover: float
    bottom_x: Mesh | None = None
    bottom_y: Mesh | None = None
    top_x: Mesh | None = None
    top_y: Mesh | None = None
    column: tuple[float, float] | None = None  # column section b x h
    column_at: Point = (0.0, 0.0)  # the column's centre from the footing's centre (local x, y)
    column_rotation: float = 0.0  # the column's rotation in the footing's axes [degrees]
    column_round: bool = False
    starters: tuple[int, float] | None = None  # column starter bars (count, dia)
    starter_leg: float | None = None  # the starters' foot (outside dimension B) [mm]
    starter_hook: str = "toCentre"  # where the foot points: toCentre (of the footing) | outward
    starter_inset: float | None = None  # bar centre from the column face (cover + tie + d/2)
    starter_mark: str = ""
    founding_level: float | None = None
    piles: list[Point] = field(default_factory=list)  # local coordinates from the centre
    pile_dia: float = 0.0
    kind: str = "footing"  # footing | pile cap


@dataclass
class RetainingWallDetail:
    """A retaining or basement wall of 9 Substructure in section (per metre run), mm."""

    mark: str
    kind: str  # cantilever | basement
    toe: float
    heel: float
    stem_top: float
    stem_bottom: float
    base: float  # thickness
    stem_height: float
    retained: float  # the retained ground above the underside of the base
    front: float  # the front ground above the underside of the base
    cover: float
    founding_level: float
    length: float
    stem_back: Mesh | None = None
    stem_front: Mesh | None = None
    horizontal: Mesh | None = None
    heel_top: Mesh | None = None
    toe_bottom: Mesh | None = None
    supports: list[float] = field(default_factory=list)  # props above the underside [mm]


@dataclass
class LintelDetail:
    """A lintel over an opening of a wall (:mod:`saengine.design.lintels`), in the wall's
    elevation: from ``x0`` to ``x1`` along the wall, its underside ``bottom`` above the wall's
    bottom, ``depth`` [mm]; bottom and top bars ``(count, dia, mark)``, stirrups ``(dia,
    spacing, mark)``."""

    opening: str
    x0: float
    x1: float
    bottom: float
    depth: float
    width: float
    bottom_bars: tuple[int, float, str] | None = None
    top_bars: tuple[int, float, str] | None = None
    stirrups: tuple[float, float, str] | None = None

    @property
    def text(self) -> str:
        parts = []
        for bars, face in ((self.bottom_bars, "B"), (self.top_bars, "T")):
            if bars:
                mark = f"{bars[2]} " if bars[2] else ""
                parts.append(f"{mark}{bars[0]}Ø{bars[1]:g} {face}")
        if self.stirrups:
            mark = f"{self.stirrups[2]} " if self.stirrups[2] else ""
            parts.append(f"{mark}Ø{self.stirrups[0]:g}@{self.stirrups[1]:g}")
        return ", ".join(parts)


@dataclass
class WallDetail:
    mark: str
    members: list[str]
    length: float
    height: float
    thickness: float
    cover: float
    vertical: Mesh | None = None
    horizontal: Mesh | None = None
    layers: int = 2
    boundary_length: float = 0.0
    boundary_bars: tuple[int, float] | None = None  # per end
    hoops: Mesh | None = None
    openings: list[tuple[float, float, float, float]] = field(default_factory=list)  # x, sill, w, h
    levels: list[tuple[str, float]] = field(default_factory=list)  # name, height above bottom
    lintels: list[LintelDetail] = field(default_factory=list)


@dataclass
class StairDetail:
    mark: str
    members: list[str]
    riser: float
    tread: float
    flights: list[int]  # risers per flight
    waist: float
    width: float
    landing_length: float
    landing_thickness: float
    cover: float
    main: Mesh | None = None
    distribution: Mesh | None = None
    top: Mesh | None = None
    landing: Mesh | None = None
    support: float = 250.0
    base_name: str = ""
    top_name: str = ""


@dataclass
class Table:
    """A table for a sheet, in the shape of :func:`saengine.drawings.bbs.sheet_table`:
    ``columns`` ``{"key", "title" (lines by "\\n"), "width" (characters), "align"}``, ``rows``
    lists of cell strings, ``groups`` ``{"first", "count"}`` row ranges not to split."""

    title: str
    columns: list[dict[str, Any]]
    rows: list[list[str]]
    groups: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any], title: str | None = None) -> Table:
        return cls(
            title=title or str(data.get("title") or ""),
            columns=[dict(c) for c in data.get("columns") or []],
            rows=[[str(v) for v in r] for r in data.get("rows") or []],
            groups=[dict(g) for g in data.get("groups") or []],
            notes=[str(n) for n in data.get("notes") or []],
        )


# ─────────────────────────────────── structural steel ───────────────────────────────────

Point3 = tuple[float, float, float]


@dataclass
class SteelMember:
    """A structural steel beam, column or brace between two points in space (mm), with its
    section and its mass as the bill of quantities measures it (``mass`` None: not in it)."""

    id: str
    mark: str
    kind: str  # beam | column | brace
    section: str  # "SHS 150x150x8", "W310x39", ...
    shape: str  # the 04 Objects profile shape (I, U, L, rectangleHollow, circleHollow, ...)
    depth: float  # mm, in the member's elevation (across its axis)
    width: float  # mm, in plan
    start: Point3
    end: Point3
    grade: str = ""  # the material's grade ("ASTM A572 Grade 50")
    material: str = ""  # the 03 Materials id
    mass: float | None = None  # kg, the BOQ's
    connection: str = ""  # the connection mark at both ends ("CN1"), "" none

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def mass_per_metre(self) -> float | None:
        """kg/m as the BOQ's mass over the centreline length (the BOQ measures it so)."""
        if self.mass is None or self.length <= 0:
            return None
        return self.mass / (self.length / 1000)


@dataclass
class SteelConnectionDetail:
    """A designed simple connection (:mod:`saengine.design.steel_connections`) as drawn: the
    connection of an object type (``data``: its 04 Objects JSON), the member section it
    connects, where it is used and what the design checks found."""

    mark: str
    kind: str  # finPlate | endPlate | gusset
    data: dict[str, Any]
    section: str
    shape: str
    depth: float  # mm, the member's depth (a brace: across the axis in its elevation)
    width: float
    web: float  # mm, web (hollow: wall) thickness
    flange: float  # mm
    members: list[str] = field(default_factory=list)
    plate_grade: str = ""
    angle: float = 45.0  # a brace's slope from the horizontal [degrees]
    whitmore: float | None = None  # mm, the Whitmore width the design checks
    utilisation: float | None = None
    ok: bool | None = None

    @property
    def ends(self) -> int:
        return 2 * len(self.members)

    @property
    def bolts(self) -> int:
        """Bolts at one end."""
        lines = int(self.data.get("lines", 2 if self.kind == "endPlate" else 1))
        return int(self.data.get("rows", 1)) * lines


@dataclass
class SteelSet:
    """The project's structural steel: members, connections, the BOQ's steel items
    ``(code, description, kg)`` and their total."""

    members: list[SteelMember] = field(default_factory=list)
    connections: list[SteelConnectionDetail] = field(default_factory=list)
    boq_items: list[tuple[str, str, float]] = field(default_factory=list)
    boq_total: float | None = None
    boq_source: str = ""  # where the masses come from ("10 BOQ/boq.json", ...)
    grades: list[str] = field(default_factory=list)
    bolt_grades: list[str] = field(default_factory=list)
    electrodes: list[float] = field(default_factory=list)


@dataclass
class DrawingSet:
    """Everything the sheets draw."""

    title: TitleInfo = field(default_factory=TitleInfo)
    building: Building = field(default_factory=Building)
    columns: list[ColumnLine] = field(default_factory=list)
    beams: list[BeamDetail] = field(default_factory=list)
    slabs: list[SlabDetail] = field(default_factory=list)
    footings: list[FootingDetail] = field(default_factory=list)
    retaining_walls: list[RetainingWallDetail] = field(default_factory=list)
    walls: list[WallDetail] = field(default_factory=list)
    stairs: list[StairDetail] = field(default_factory=list)
    bbs: list[Table] = field(default_factory=list)  # the bar schedule, then its totals
    pile_caps: Table | None = None  # the pile cap schedule
    notes: list[str] = field(default_factory=list)  # general notes
    tables: list[Table] = field(default_factory=list)  # notes tables (lap and development, ...)
    steel: SteelSet = field(default_factory=SteelSet)
    # the architecture (05 Floor Plan/architecture.json, saengine.library.architecture's model)
    # its sheets draw; None: no architectural sheets
    architecture: Any = None
    problems: list[str] = field(default_factory=list)
    # members without reinforcement (never designed): {kind: {object type: count}}; while there
    # are any the sheets are not for construction
    undesigned: dict[str, dict[str, int]] = field(default_factory=dict)
