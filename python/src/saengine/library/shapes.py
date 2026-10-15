"""Parametric shapes for the structural model of a special structure (Part 5).

Long-span roofs and towers are rarely drawn member by member: the engineer picks a shape (a
space truss, a dome, a barrel vault...), sets its few dimensions and places it. Each shape here
is a Pydantic model of those parameters, so the 3D modeller can show it as a form and scripts
can build it in one line; :func:`shape_geometry` turns one into members, panels and supports.

Generated geometry, imported geometry (:mod:`saengine.library.importers`) and script geometry
(:mod:`saengine.library.script`) all enter the model through :func:`insert`, which gives the new
elements fresh ids and leaves out what the model already has (a member between the same two
points, an area with the same corners, a support at the same point).

Shapes are built in their own axes (x along the span or length, y across, z up, origin at a
corner or the centre of the base, as each shape says) and then turned by ``rotation`` about the
vertical through ``origin`` and moved there. Units are mm and degrees, as in the model.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import Field, model_validator

from saengine.library.materials import Id
from saengine.library.structure import (
    TOLERANCE,
    Area,
    Member,
    Opening,
    Point,
    StructuralModel,
    Support,
    _Model,
)

Supports = Literal["none", "pinned", "fixed"]
SupportAt = Literal["corners", "perimeter"]

Mm = Annotated[float, Field(gt=0, description="[mm]")]


def _origin() -> Any:
    return Field(
        default_factory=lambda: Point(x=0, y=0, z=0),
        description="Where the shape's own origin is placed [mm].",
    )


def _rotation() -> Any:
    return Field(default=0, description="Rotation in plan about the origin [°].")


def _supports(default: Supports = "pinned") -> Any:
    return Field(default=default, description="Supports added where the shape meets the ground.")


def _secondary(what: str) -> Any:
    return Field(
        default=None,
        title=f"{what} type",
        description=f"Object type of the {what.lower()}s; none uses the member type.",
    )


def _panels() -> Any:
    return Field(
        default=None,
        title="Panel type",
        description="Slab or wall type of the cladding panels between the members; none adds "
        "no panels.",
    )


# ───────────────────────────── geometry ─────────────────────────────


@dataclass
class LineElement:
    start: np.ndarray
    end: np.ndarray
    type: str


@dataclass
class PanelElement:
    outline: list[np.ndarray]
    type: str
    openings: list[list[np.ndarray]] = field(default_factory=list)


@dataclass
class SupportPoint:
    at: np.ndarray
    fixity: Literal["pinned", "fixed"]


@dataclass
class Geometry:
    """Elements ready to go into a structural model, with notes on what was left out."""

    members: list[LineElement] = field(default_factory=list)
    areas: list[PanelElement] = field(default_factory=list)
    supports: list[SupportPoint] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def line(self, start: Any, end: Any, type_: str) -> None:
        a, b = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
        if np.linalg.norm(b - a) >= TOLERANCE:
            self.members.append(LineElement(a, b, type_))

    def panel(self, outline: list[Any], type_: str) -> None:
        self.areas.append(PanelElement([np.asarray(p, dtype=float) for p in outline], type_))

    def support(self, at: Any, fixity: Supports) -> None:
        if fixity != "none":
            self.supports.append(SupportPoint(np.asarray(at, dtype=float), fixity))

    def extend(self, other: Geometry) -> None:
        self.members += other.members
        self.areas += other.areas
        self.supports += other.supports
        self.notes += other.notes

    def placed(self, origin: Point, rotation: float) -> Geometry:
        """This geometry turned by ``rotation`` in plan and moved to ``origin``."""
        a = math.radians(rotation)
        turn = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
        o = origin.array()

        def move(p: np.ndarray) -> np.ndarray:
            return turn @ p + o

        return Geometry(
            [LineElement(move(m.start), move(m.end), m.type) for m in self.members],
            [
                PanelElement(
                    [move(p) for p in a.outline], a.type, [[move(p) for p in h] for h in a.openings]
                )
                for a in self.areas
            ],
            [SupportPoint(move(s.at), s.fixity) for s in self.supports],
            list(self.notes),
        )

    @staticmethod
    def from_json(data: dict[str, Any]) -> Geometry:
        """The inverse of :meth:`to_json`."""

        def p(v: list[float]) -> np.ndarray:
            return np.asarray(v, dtype=float)

        return Geometry(
            [LineElement(p(m["start"]), p(m["end"]), m["type"]) for m in data.get("members", [])],
            [
                PanelElement(
                    [p(v) for v in a["outline"]],
                    a["type"],
                    [[p(v) for v in h] for h in a.get("openings", [])],
                )
                for a in data.get("areas", [])
            ],
            [SupportPoint(p(s["at"]), s["fixity"]) for s in data.get("supports", [])],
            list(data.get("notes", [])),
        )

    def to_json(self) -> dict[str, Any]:
        """For the modeller's preview: points as [x, y, z] lists."""

        def p(v: np.ndarray) -> list[float]:
            return [_mm(x) for x in v]

        return {
            "members": [
                {"start": p(m.start), "end": p(m.end), "type": m.type} for m in self.members
            ],
            "areas": [
                {
                    "outline": [p(v) for v in a.outline],
                    "openings": [[p(v) for v in h] for h in a.openings],
                    "type": a.type,
                }
                for a in self.areas
            ],
            "supports": [{"at": p(s.at), "fixity": s.fixity} for s in self.supports],
            "notes": list(self.notes),
        }


def _mm(value: float) -> float:
    """Coordinates rounded to 0.1 mm (and no negative zero), so files stay readable."""
    return round(float(value), 1) + 0.0


# ───────────────────────────── shapes ─────────────────────────────


class SpaceTruss(_Model):
    """A double-layer grid (square on square, offset): a flat roof spanning both ways."""

    kind: Literal["spaceTruss"] = "spaceTruss"
    lengthX: Mm = Field(title="Length X", description="[mm]")
    lengthY: Mm = Field(title="Length Y", description="[mm]")
    baysX: int = Field(ge=1, le=200, title="Bays in X")
    baysY: int = Field(ge=1, le=200, title="Bays in Y")
    depth: Mm = Field(description="Between the top and bottom layers [mm].")
    memberType: Id = Field(title="Member type", description="Object type of the chords.")
    diagonalType: Id | None = _secondary("Diagonal")
    supports: Supports = _supports()
    supportAt: SupportAt = Field(
        default="perimeter", title="Supports at", description="Top-layer nodes that are held."
    )
    origin: Point = _origin()
    rotation: float = _rotation()

    def local(self) -> Geometry:
        g = Geometry()
        nx, ny = self.baysX, self.baysY
        ax, ay = self.lengthX / nx, self.lengthY / ny
        diagonal = self.diagonalType or self.memberType

        def top(i: int, j: int) -> tuple[float, float, float]:
            return (i * ax, j * ay, 0.0)

        def bottom(i: int, j: int) -> tuple[float, float, float]:
            return ((i + 0.5) * ax, (j + 0.5) * ay, -self.depth)

        for i in range(nx + 1):
            for j in range(ny + 1):
                if i < nx:
                    g.line(top(i, j), top(i + 1, j), self.memberType)
                if j < ny:
                    g.line(top(i, j), top(i, j + 1), self.memberType)
                edge = i in (0, nx) or j in (0, ny)
                corner = i in (0, nx) and j in (0, ny)
                if corner or (edge and self.supportAt == "perimeter"):
                    g.support(top(i, j), self.supports)
        for i in range(nx):
            for j in range(ny):
                if i < nx - 1:
                    g.line(bottom(i, j), bottom(i + 1, j), self.memberType)
                if j < ny - 1:
                    g.line(bottom(i, j), bottom(i, j + 1), self.memberType)
                for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                    g.line(bottom(i, j), top(i + di, j + dj), diagonal)
        return g


class PlaneTruss(_Model):
    """A flat truss with parallel chords, in its own vertical plane along x."""

    kind: Literal["planeTruss"] = "planeTruss"
    span: Mm
    depth: Mm = Field(description="Between the chord centre lines [mm].")
    panels: int = Field(ge=2, le=200, description="Panels along the span.")
    pattern: Literal["warren", "pratt", "howe"] = Field(
        default="pratt",
        description="Warren: diagonals only; Pratt: diagonals down towards midspan (in tension "
        "under gravity); Howe: diagonals up towards midspan.",
    )
    memberType: Id = Field(title="Member type", description="Object type of the chords.")
    webType: Id | None = Field(
        default=None,
        title="Web type",
        description="Object type of the diagonals and verticals; none uses the member type.",
    )
    supports: Supports = _supports()
    origin: Point = _origin()
    rotation: float = _rotation()

    def local(self) -> Geometry:
        g = Geometry()
        n, s, d = self.panels, self.span / self.panels, self.depth
        web = self.webType or self.memberType

        def bottom(i: float) -> tuple[float, float, float]:
            return (i * s, 0.0, 0.0)

        def top(i: float) -> tuple[float, float, float]:
            return (i * s, 0.0, d)

        for i in range(n):
            g.line(bottom(i), bottom(i + 1), self.memberType)
        if self.pattern == "warren":
            for i in range(n):
                if i < n - 1:
                    g.line(top(i + 0.5), top(i + 1.5), self.memberType)
                g.line(bottom(i), top(i + 0.5), web)
                g.line(top(i + 0.5), bottom(i + 1), web)
        else:
            for i in range(n):
                g.line(top(i), top(i + 1), self.memberType)
            for i in range(n + 1):
                g.line(bottom(i), top(i), web)
            for i in range(n):
                left = i + 0.5 < n / 2
                if (self.pattern == "pratt") == left:
                    g.line(top(i), bottom(i + 1), web)
                else:
                    g.line(bottom(i), top(i + 1), web)
        g.support(bottom(0), self.supports)
        g.support(bottom(n), self.supports)
        return g


def _arc(span: float, rise: float, segments: int, form: str) -> list[tuple[float, float]]:
    """(x, z) of the points of an arch from (0, 0) to (span, 0) with its crown at ``rise``."""
    if form == "parabolic":
        xs = [span * k / segments for k in range(segments + 1)]
        return [(x, 4 * rise * x * (span - x) / span**2) for x in xs]
    radius = (span**2 / 4 + rise**2) / (2 * rise)
    cz = rise - radius
    start, end = math.atan2(-cz, -span / 2), math.atan2(-cz, span / 2)
    result = []
    for k in range(segments + 1):
        a = start + (end - start) * k / segments
        result.append((span / 2 + radius * math.cos(a), cz + radius * math.sin(a)))
    result[0], result[-1] = (0.0, 0.0), (span, 0.0)
    return result


class Arch(_Model):
    """A single arch in its own vertical plane along x, springing at z = 0."""

    kind: Literal["arch"] = "arch"
    span: Mm
    rise: Mm = Field(description="Of the crown above the springings [mm].")
    segments: int = Field(ge=2, le=400, description="Straight members along the arch.")
    form: Literal["circular", "parabolic"] = "circular"
    memberType: Id = Field(title="Member type")
    supports: Supports = _supports()
    origin: Point = _origin()
    rotation: float = _rotation()

    @model_validator(mode="after")
    def _rise(self) -> Arch:
        if self.form == "circular" and self.rise > self.span / 2 + TOLERANCE:
            raise ValueError("a circular arch rises at most half its span (a half circle)")
        return self

    def local(self) -> Geometry:
        g = Geometry()
        points = [(x, 0.0, z) for x, z in _arc(self.span, self.rise, self.segments, self.form)]
        for a, b in itertools.pairwise(points):
            g.line(a, b, self.memberType)
        g.support(points[0], self.supports)
        g.support(points[-1], self.supports)
        return g


class Dome(_Model):
    """A spherical dome (a cap of a sphere) on a circular base centred on the origin."""

    kind: Literal["dome"] = "dome"
    radius: Mm = Field(description="Of the base circle [mm].")
    rise: Mm = Field(description="Of the crown above the base [mm].")
    rings: int = Field(ge=1, le=100, description="Rings from the crown down to the base.")
    segments: int = Field(ge=3, le=360, description="Meridian ribs around the dome.")
    pattern: Literal["ribbed", "schwedler"] = Field(
        default="schwedler",
        description="Ribbed: ribs and rings; Schwedler: also a diagonal in every bay.",
    )
    memberType: Id = Field(title="Member type", description="Object type of the ribs and rings.")
    diagonalType: Id | None = _secondary("Diagonal")
    panelType: Id | None = _panels()
    supports: Supports = _supports()
    origin: Point = _origin()
    rotation: float = _rotation()

    @model_validator(mode="after")
    def _rise(self) -> Dome:
        if self.rise > self.radius + TOLERANCE:
            raise ValueError("a dome rises at most its base radius (a half sphere)")
        return self

    def local(self) -> Geometry:
        g = Geometry()
        n, m = self.rings, self.segments
        sphere = (self.radius**2 + self.rise**2) / (2 * self.rise)
        centre = self.rise - sphere
        base = math.acos(max(-1.0, min(1.0, -centre / sphere)))  # polar angle of the base ring
        diagonal = self.diagonalType or self.memberType
        crown = (0.0, 0.0, self.rise)

        def node(k: int, j: int) -> tuple[float, float, float]:
            """Ring k (1 = nearest the crown, n = base), meridian j."""
            if k == n:
                r, z = self.radius, 0.0
            else:
                phi = base * k / n
                r, z = sphere * math.sin(phi), centre + sphere * math.cos(phi)
            a = 2 * math.pi * (j % m) / m
            return (r * math.cos(a), r * math.sin(a), z)

        for j in range(m):
            g.line(crown, node(1, j), self.memberType)
            if self.panelType:
                g.panel([crown, node(1, j), node(1, j + 1)], self.panelType)
            for k in range(1, n + 1):
                g.line(node(k, j), node(k, j + 1), self.memberType)
                if k < n:
                    g.line(node(k, j), node(k + 1, j), self.memberType)
                    quad = [node(k, j), node(k, j + 1), node(k + 1, j + 1), node(k + 1, j)]
                    if self.pattern == "schwedler":
                        g.line(node(k, j), node(k + 1, j + 1), diagonal)
                        if self.panelType:
                            g.panel([quad[0], quad[1], quad[2]], self.panelType)
                            g.panel([quad[0], quad[2], quad[3]], self.panelType)
                    elif self.panelType:
                        g.panel(quad, self.panelType)  # a symmetric trapezoid: flat
            g.support(node(n, j), self.supports)
        return g


class BarrelVault(_Model):
    """A cylindrical vault: arches across x (the span) repeated along y (the length)."""

    kind: Literal["barrelVault"] = "barrelVault"
    span: Mm
    rise: Mm = Field(description="Of the crown above the springings [mm].")
    length: Mm
    segments: int = Field(ge=2, le=400, description="Straight members across each arch.")
    bays: int = Field(ge=1, le=400, description="Bays along the length.")
    pattern: Literal["ribbed", "braced"] = Field(
        default="braced",
        description="Ribbed: arches and purlins; braced: also a diagonal in every bay.",
    )
    memberType: Id = Field(
        title="Member type", description="Object type of the arches and purlins."
    )
    diagonalType: Id | None = _secondary("Diagonal")
    panelType: Id | None = _panels()
    supports: Supports = _supports()
    origin: Point = _origin()
    rotation: float = _rotation()

    @model_validator(mode="after")
    def _rise(self) -> BarrelVault:
        if self.rise > self.span / 2 + TOLERANCE:
            raise ValueError("a barrel vault rises at most half its span (a half cylinder)")
        return self

    def local(self) -> Geometry:
        g = Geometry()
        arc = _arc(self.span, self.rise, self.segments, "circular")
        step = self.length / self.bays
        diagonal = self.diagonalType or self.memberType

        def node(i: int, j: int) -> tuple[float, float, float]:
            return (arc[i][0], j * step, arc[i][1])

        for j in range(self.bays + 1):
            for i in range(self.segments):
                g.line(node(i, j), node(i + 1, j), self.memberType)
            for i in range(self.segments + 1):
                if j < self.bays:
                    g.line(node(i, j), node(i, j + 1), self.memberType)
            g.support(node(0, j), self.supports)
            g.support(node(self.segments, j), self.supports)
        for j in range(self.bays):
            for i in range(self.segments):
                if self.pattern == "braced":
                    # Diagonals mirror about the crown, so the vault is braced symmetrically.
                    if i < self.segments / 2:
                        g.line(node(i, j), node(i + 1, j + 1), diagonal)
                    else:
                        g.line(node(i + 1, j), node(i, j + 1), diagonal)
                if self.panelType:
                    g.panel(
                        [node(i, j), node(i + 1, j), node(i + 1, j + 1), node(i, j + 1)],
                        self.panelType,
                    )
        return g


class CableNet(_Model):
    """A saddle-shaped (hyperbolic paraboloid) net of cables over a rectangle.

    Its corners lie at z = 0; the edges rise by ``rise`` at the middle of the x edges and fall by
    it at the middle of the y edges. Cables are drawn as members: tension-only behaviour and
    prestress come with the nonlinear analyses.
    """

    kind: Literal["cableNet"] = "cableNet"
    lengthX: Mm = Field(title="Length X", description="[mm]")
    lengthY: Mm = Field(title="Length Y", description="[mm]")
    divisionsX: int = Field(ge=2, le=400, title="Divisions in X")
    divisionsY: int = Field(ge=2, le=400, title="Divisions in Y")
    rise: float = Field(description="Saddle height at the middle of the edges [mm].")
    memberType: Id = Field(title="Member type", description="Object type of the cables.")
    edgeType: Id | None = Field(
        default=None,
        title="Edge type",
        description="Object type of the edge members; none uses the member type.",
    )
    supports: Supports = _supports()
    supportAt: SupportAt = Field(default="perimeter", title="Supports at")
    origin: Point = _origin()
    rotation: float = _rotation()

    def local(self) -> Geometry:
        g = Geometry()
        nx, ny = self.divisionsX, self.divisionsY
        edge = self.edgeType or self.memberType

        def node(i: int, j: int) -> tuple[float, float, float]:
            u, v = 2 * i / nx - 1, 2 * j / ny - 1
            return (i * self.lengthX / nx, j * self.lengthY / ny, self.rise * (v * v - u * u))

        for i in range(nx + 1):
            for j in range(ny + 1):
                if i < nx:
                    g.line(node(i, j), node(i + 1, j), edge if j in (0, ny) else self.memberType)
                if j < ny:
                    g.line(node(i, j), node(i, j + 1), edge if i in (0, nx) else self.memberType)
                on_edge = i in (0, nx) or j in (0, ny)
                corner = i in (0, nx) and j in (0, ny)
                if corner or (on_edge and self.supportAt == "perimeter"):
                    g.support(node(i, j), self.supports)
        return g


Shape = Annotated[
    SpaceTruss | PlaneTruss | Arch | Dome | BarrelVault | CableNet, Field(discriminator="kind")
]

SHAPES: tuple[type[_Model], ...] = (SpaceTruss, PlaneTruss, Arch, Dome, BarrelVault, CableNet)


class ShapeInput(_Model):
    """What the modeller's Generate panel edits: one shape."""

    shape: Shape


def shape_geometry(
    shape: SpaceTruss | PlaneTruss | Arch | Dome | BarrelVault | CableNet,
) -> Geometry:
    """The members, panels and supports of ``shape``, placed in the model."""
    return shape.local().placed(shape.origin, shape.rotation)


# ───────────────────────────── insertion ─────────────────────────────


def _key(p: np.ndarray) -> tuple[int, int, int]:
    return (round(float(p[0])), round(float(p[1])), round(float(p[2])))


def _point(p: np.ndarray) -> Point:
    return Point(x=_mm(p[0]), y=_mm(p[1]), z=_mm(p[2]))


def insert(model: StructuralModel, geometry: Geometry) -> tuple[StructuralModel, list[str], int]:
    """``model`` with ``geometry`` added: (new model, ids of the new elements, how many were
    already there and left out). Points within 1 mm count as the same point."""
    result = model.model_copy(deep=True)
    used = {e.id for e in (*result.members, *result.areas, *result.supports)}
    counters: dict[str, int] = {}

    def next_id(prefix: str) -> str:
        n = counters.get(prefix, 1)
        while f"{prefix}{n}" in used:
            n += 1
        counters[prefix] = n + 1
        used.add(f"{prefix}{n}")
        return f"{prefix}{n}"

    members = {frozenset((_key(m.start.array()), _key(m.end.array()))) for m in result.members}
    areas = {frozenset(_key(p.array()) for p in a.outline) for a in result.areas}
    supports = {_key(s.at.array()) for s in result.supports}
    ids: list[str] = []
    skipped = 0
    for m in geometry.members:
        key = frozenset((_key(m.start), _key(m.end)))
        if len(key) < 2 or key in members:
            skipped += 1
            continue
        members.add(key)
        member = Member(id=next_id("M"), type=m.type, start=_point(m.start), end=_point(m.end))
        result.members.append(member)
        ids.append(member.id)
    for a in geometry.areas:
        key = frozenset(_key(p) for p in a.outline)
        if key in areas:
            skipped += 1
            continue
        areas.add(key)
        area = Area(
            id=next_id("A"),
            type=a.type,
            outline=[_point(p) for p in a.outline],
            openings=[Opening(outline=[_point(p) for p in h]) for h in a.openings],
        )
        result.areas.append(area)
        ids.append(area.id)
    for s in geometry.supports:
        key = _key(s.at)
        if key in supports:
            skipped += 1
            continue
        supports.add(key)
        support = Support(id=next_id("SP"), at=_point(s.at), fixity=s.fixity)
        result.supports.append(support)
        ids.append(support.id)
    return result, ids, skipped
