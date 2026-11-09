"""The fabrication model of the structural steel (alpha 9 L10): every steel member of the
building model cut into the parts a fabricator makes, grouped into shipping assemblies, with
part marks and assembly marks.

What it is built from (nothing is designed here):

- the members: :func:`saengine.drawings.sheets.steel.steel_members` (06 BIM beams, columns,
  members and the inclined members of the additions, with their 04 Objects types);
- the sections: the steel section table (:func:`saengine.library.steel_sections.section_of_profile`);
- the connections: the designed connection of each object type (``connection``, ``splice``,
  ``basePlate``, ``capPlate`` of 04 Objects, checked by
  :mod:`saengine.design.steel_connections`): its bolts, holes (the pack's hole table,
  :func:`~saengine.design.steel_connections.hole_diameter`), plates and welds as given there, the
  gusset outline of the connection details (:class:`saengine.drawings.sheets.steel.GussetGeometry`)
  and the base plate's anchor positions (:func:`~saengine.design.steel_connections.anchor_points`);
- the pack's ``fabrication`` table (:mod:`saengine.codes.fabrication_tables`) and Project
  Settings › Drawings › Fabrication: weld symbols, clearances, the marks' prefixes.

Each member is one assembly (a member with a cover-plate splice: two, one each side of the
joint). The main part is the member's profile cut to length: to the face of what it frames into
(a column's flange or web, a beam's web: :func:`supports`) less the end clearance, an end plate's
thickness or a flange plate connection's setback; a beam framing into a beam at the same top
level is coped over the supporting flange. Plates welded in the shop go with the assembly they
are welded to: an end plate, a brace's tab, a base or cap plate with their member; a fin plate,
a gusset, flange plates and column stiffeners with the supporting member (when there is no steel
member there they are loose parts of the supported member, to be welded on site or to an
embedded plate). Bolted splice plates are loose parts. A bolted end plate's holes are drilled in
the support too.

Coordinates of a part (mm), the DSTV NC convention (:mod:`.dstv`): x along the part from its
start (a beam's BIM start, a column's bottom, a brace's first end); on the web face ``v`` y from
the profile's lower edge (the ``u`` flange's side); on the flange faces ``o`` (top) and ``u``
(bottom) y across the flange; a plate lies in its face ``v``, x along its length and y across
its width. Holes are through holes.

Identical parts get one part mark (``p1``, ``p2``, ...: the same profile or plate, grade,
length, holes, cuts and outline); identical assemblies one assembly mark (the same main part and
the same parts in the same places): ``B1``, ``C1``, ``BR1`` by member kind (the settings'
prefixes).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from saengine.drawings.sheets.steel import natural_key

Point = tuple[float, float]
Point3 = tuple[float, float, float]

STEEL_DENSITY = 7850.0
"""kg/m³ of a plate whose material gives no density (as the bill of quantities' steel)."""
TOL = 2.0  # mm: points this close meet
KINDS = ("beam", "column", "brace")

#: DSTV profile codes by the 04 Objects profile shape (:mod:`.dstv`).
DSTV_CODES = {
    "I": "I",
    "U": "U",
    "L": "L",
    "T": "T",
    "rectangleHollow": "M",
    "circleHollow": "RO",
    "circle": "RU",
    "rectangle": "B",
}


# ─────────────────────────────────── options ───────────────────────────────────


@dataclass
class FabricationOptions:
    """What the fabrication model is made with: the pack's ``fabrication`` table under Project
    Settings › Drawings › Fabrication (:meth:`resolve`)."""

    weld_symbols: str = "aws"  # aws | isoA | isoB
    end_clearance: float = 12.0
    cope_clearance: float = 10.0
    anchor_clearance: float = 6.0
    prefixes: dict[str, str] = field(
        default_factory=lambda: {"beam": "B", "column": "C", "brace": "BR"}
    )
    part_prefix: str = "p"

    @classmethod
    def resolve(cls, settings: Any = None) -> FabricationOptions:
        """The options of the pack in force (``fabrication`` table, the default pack's when the
        pack has none) and the project's ``drawings.fabrication`` settings (a model or a dict)."""
        from saengine.codes import context as code_context

        table = code_context.pack_table("fabrication")
        s = settings.model_dump() if hasattr(settings, "model_dump") else dict(settings or {})
        symbols = str(s.get("weldSymbols") or "pack")
        return cls(
            weld_symbols=table.weldSymbols if symbols == "pack" else symbols,
            end_clearance=float(s.get("endClearance", 12.0)),
            cope_clearance=float(table.copeClearance),
            anchor_clearance=float(table.anchorHoleClearance),
            prefixes={
                "beam": str(s.get("beamPrefix") or "B"),
                "column": str(s.get("columnPrefix") or "C"),
                "brace": str(s.get("bracePrefix") or "BR"),
            },
            part_prefix=str(s.get("partPrefix") or "p"),
        )


def bolt_hole(d: float) -> float:
    """The drilled hole of a bolt of diameter ``d`` [mm]: the pack's standard hole."""
    from saengine.design.steel_connections import hole_diameter

    return hole_diameter(d)


# ─────────────────────────────────── the parts ───────────────────────────────────


@dataclass
class Hole:
    """A through hole of a part (see the module notes for the coordinates). Until the model is
    finished, x may be measured from the part's end (``from_end``) or be a position along the
    member's axis (``on_axis``: a hole drilled to match another member's connection)."""

    face: str
    x: float
    y: float
    dia: float
    group: str = ""
    from_end: bool = False
    on_axis: bool = False


@dataclass
class Cope:
    """A rectangular cope of a beam's flange and web at one end: ``length`` along the beam from
    its end, ``depth`` from the flange's outer face."""

    end: str  # start | end
    side: str  # top | bottom
    length: float
    depth: float


@dataclass
class Weld:
    """A weld of a part to its assembly: a fillet of leg ``size`` [mm] (or a complete joint
    penetration groove weld, ``kind`` "cjp"), ``length`` [mm] (None: all round), on both sides
    of the joint or the arrow side only."""

    size: float
    length: float | None
    both: bool = True
    kind: str = "fillet"  # fillet | cjp
    note: str = ""


@dataclass
class Part:
    """A part a fabricator cuts: a profile cut to length or a plate (see the module notes)."""

    kind: str  # profile | plate
    role: str  # main, fin plate, end plate, gusset, tab, flange plate, splice plate, ...
    name: str  # as the drawings print it ("IPE 300", "PL 10x150")
    profile: str  # as the NC header names it ("IPE300", "PL10*150")
    code: str  # DSTV profile code (I, U, L, B, M, RO, RU, T, C, SO)
    grade: str
    length: float
    h: float = 0.0  # profile depth; plate: its width
    b: float = 0.0  # flange width; plate: 0
    tw: float = 0.0  # web (plate: its thickness)
    tf: float = 0.0
    r: float = 0.0
    mass_per_m: float = 0.0  # kg/m
    paint_per_m: float = 0.0  # m²/m
    density: float = STEEL_DENSITY
    holes: list[Hole] = field(default_factory=list)
    contour: list[Point] | None = None  # plates: the outline in face v; None: the rectangle
    copes: list[Cope] = field(default_factory=list)
    cuts: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # web start/end, flange
    notes: list[str] = field(default_factory=list)
    mark: str = ""
    shape: str = ""  # the 04 Objects profile shape ("" for plates)

    @property
    def thickness(self) -> float:
        return self.tw

    @property
    def width(self) -> float:
        return self.h

    def outline(self) -> list[Point]:
        """A plate's outline (counter-clockwise, not closed)."""
        if self.contour:
            return list(self.contour)
        return [(0.0, 0.0), (self.length, 0.0), (self.length, self.h), (0.0, self.h)]

    @property
    def area(self) -> float:
        """A plate's area [mm²] less its holes."""
        pts = self.outline()
        a = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, [*pts[1:], pts[0]]))
        return abs(a) / 2 - sum(math.pi * h.dia**2 / 4 for h in self.holes)

    @property
    def mass(self) -> float:
        """kg of one part."""
        if self.kind == "plate":
            return self.area * self.tw * 1e-9 * self.density
        return self.mass_per_m * self.length / 1000

    def finish(self) -> None:
        """Holes measured from the end are measured from the start; holes sorted; a plate's
        outline counter-clockwise."""
        for h in self.holes:
            if h.from_end:
                h.x, h.from_end = self.length - h.x, False
            h.x, h.y = round(h.x, 1), round(h.y, 1)
        self.holes.sort(key=lambda h: (h.face, h.x, h.y))
        if self.contour:
            pts = self.contour
            signed = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, [*pts[1:], pts[0]]))
            if signed < 0:
                self.contour = list(reversed(pts))

    def signature(self) -> tuple[Any, ...]:
        """What makes two parts the same part (one mark)."""
        return (
            self.kind,
            self.role == "main",
            self.profile,
            self.grade,
            round(self.length),
            round(self.h, 1),
            round(self.tw, 1),
            tuple((h.face, round(h.x), round(h.y), round(h.dia, 1)) for h in self.holes),
            tuple((round(x), round(y)) for x, y in self.contour) if self.contour else (),
            tuple((c.end, c.side, round(c.length), round(c.depth)) for c in self.copes),
            tuple(round(c, 1) for c in self.cuts),
        )


@dataclass
class Attached:
    """A part of an assembly besides its main part: where it is on the main part (``x`` along
    it from its start, on face ``face``: o, u, v, h, or the ``start``/``end`` of the member)
    and how it is fixed (``weld``; None: bolted, a loose part)."""

    part: Part
    x: float
    face: str
    weld: Weld | None = None
    what: str = ""  # "fin plate for B12", "base plate", ...
    offset: float = 0.0  # across the face from the main part's reference line [mm] (drawing)
    angle: float = 0.0  # a gusset's brace angle to the main part [°] (drawing)
    on_axis: bool = False  # x is a position along the member's axis until finished
    anchor: float = 0.0  # the part's own x at ``x`` (a gusset: its weld's centre) (drawing)

    @property
    def loose(self) -> bool:
        return self.weld is None


@dataclass
class Assembly:
    """A shipping assembly: a main part and the parts welded to it (or shipped loose with it)."""

    kind: str  # beam | column | brace
    member: str  # the BIM element ("B12/1": the first piece of a spliced member)
    main: Part
    parts: list[Attached] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    mark: str = ""
    members: list[str] = field(default_factory=list)  # every member piece with this mark
    start: Point3 = (0.0, 0.0, 0.0)  # the piece's axis in the model (the marking plan)
    end: Point3 = (0.0, 0.0, 0.0)
    section: str = ""

    @property
    def quantity(self) -> int:
        return max(len(self.members), 1)

    @property
    def mass(self) -> float:
        """kg of one assembly (its loose parts included)."""
        return self.main.mass + sum(a.part.mass for a in self.parts)

    def signature(self) -> tuple[Any, ...]:
        return (
            self.kind,
            self.main.mark,
            tuple(
                sorted(
                    (a.part.mark, round(a.x), a.face, a.loose, round(a.offset), round(a.angle))
                    for a in self.parts
                )
            ),
        )


@dataclass
class FabricationModel:
    """The project's steel for fabrication: the assemblies (one per member piece, marked)."""

    assemblies: list[Assembly] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def marked(self) -> list[Assembly]:
        """One assembly per assembly mark (the first of its members), in mark order."""
        seen: dict[str, Assembly] = {}
        for a in self.assemblies:
            seen.setdefault(a.mark, a)
        return sorted(seen.values(), key=lambda a: _mark_key(a.mark))

    def parts(self) -> list[tuple[Part, int]]:
        """Every part mark with the number made (in all the assemblies), in mark order."""
        count: dict[str, int] = {}
        first: dict[str, Part] = {}
        for a in self.assemblies:
            for p in (a.main, *(x.part for x in a.parts)):
                count[p.mark] = count.get(p.mark, 0) + 1
                first.setdefault(p.mark, p)
        return [(first[m], count[m]) for m in sorted(first, key=_mark_key)]

    def assemblies_of(self, part_mark: str) -> list[str]:
        """The assembly marks a part is in."""
        found = {
            a.mark
            for a in self.assemblies
            if a.main.mark == part_mark or any(x.part.mark == part_mark for x in a.parts)
        }
        return sorted(found, key=_mark_key)


def _mark_key(text: str) -> tuple[Any, ...]:
    return natural_key(text)


# ─────────────────────────────────── the members ───────────────────────────────────


@dataclass
class _Member:
    m: Any  # SteelMember
    t: Any  # the object type
    s: Any  # SteelSection or None
    rotation: float
    grade: str
    density: float
    pieces: list[_Piece] = field(default_factory=list)

    @property
    def start(self) -> Point3:
        return self.m.start

    @property
    def end(self) -> Point3:
        return self.m.end

    @property
    def length(self) -> float:
        return math.dist(self.m.start, self.m.end)

    @property
    def u(self) -> Point3:
        n = self.length or 1.0
        x1, y1, z1 = self.start
        x2, y2, z2 = self.end
        return ((x2 - x1) / n, (y2 - y1) / n, (z2 - z1) / n)

    @property
    def vertical(self) -> bool:
        return abs(self.u[2]) > 0.999

    def at(self, t: float) -> Point3:
        """The point ``t`` mm along the axis from the start."""
        u = self.u
        return (self.start[0] + t * u[0], self.start[1] + t * u[1], self.start[2] + t * u[2])

    def piece_at(self, t: float) -> _Piece | None:
        for p in self.pieces:
            if p.t0 - TOL <= t <= p.t1 + TOL:
                return p
        return self.pieces[0] if self.pieces else None


@dataclass
class _Piece:
    """A length of a member that is one assembly: from ``t0`` to ``t1`` along its axis, cut back
    ``cut0`` at its start and ``cut1`` at its end."""

    member: _Member
    t0: float
    t1: float
    index: int = 0
    cut0: float = 0.0
    cut1: float = 0.0
    assembly: Assembly | None = None

    @property
    def length(self) -> float:
        return self.t1 - self.t0 - self.cut0 - self.cut1

    def local(self, t: float) -> float:
        """x on the main part of the axis position ``t``."""
        return t - self.t0 - self.cut0


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def _profile_names(s: Any, fallback: str) -> tuple[str, str]:
    """(drawing name, NC profile name) of a section: "IPE 300" and "IPE300"."""
    name = s.name if s is not None and s.name != "custom" else fallback
    return name, re.sub(r"\s+", "", name)


def _paint(s: Any) -> float:
    """Painting surface per metre [m²/m] of a section's outline."""
    if s is None:
        return 0.0
    if s.shape == "circleHollow":
        return math.pi * s.h / 1000
    if s.shape in ("I", "U"):
        return (2 * s.h + 4 * s.b - 2 * s.tw) / 1000
    return 2 * (s.h + s.b) / 1000


def _members(bim: Any, objects: Any, materials: Any) -> list[_Member]:
    from saengine.drawings.sheets.steel import steel_members
    from saengine.library.steel_sections import section_of_profile

    types = {o.id: o for o in objects.objects}
    type_of = {e.id: e.type for e in bim.elements}
    type_of.update({m.id: m.type for m in bim.additions.members})
    rotation = {e.id: float(getattr(e, "rotation", 0.0) or 0.0) for e in bim.elements}
    for m in bim.additions.members:
        rotation[m.id] = float(getattr(m, "rotation", 0.0) or 0.0)
    out = []
    for m in steel_members(bim, objects, materials):
        t = types.get(type_of.get(m.id, ""))
        try:
            s = section_of_profile(t.profile)
        except (TypeError, ValueError, KeyError, AttributeError):
            s = None
        material = materials.get(m.material) if materials is not None else None
        density = getattr(getattr(material, "mechanical", None), "density", None)
        out.append(
            _Member(m, t, s, rotation.get(m.id, 0.0), m.grade, float(density or STEEL_DENSITY))
        )
    return out


# ─────────────────────────────────── supports ───────────────────────────────────


@dataclass
class _Support:
    """What a member's end frames into: the supporting member, the face it meets (o, u: an I
    column's flanges, v: its web or a beam's web), the distance from the end's set-out point to
    that face along the member, and where it is on the support's axis."""

    member: _Member
    face: str
    reach: float
    t: float  # along the support's axis [mm]


def _column_face(col: _Member, direction: Point) -> tuple[str, float]:
    """(face, reach in plan) of a vertical member for a plan ``direction`` from its axis (the
    section turned by its rotation; the profile's x axis is the flange width, its y the
    depth, as :func:`saengine.fem.end_zones.support_reach` turns it)."""
    length = math.hypot(*direction) or 1.0
    ux, uy = direction[0] / length, direction[1] / length
    a = math.radians(col.rotation)
    lx = ux * math.cos(a) + uy * math.sin(a)
    ly = -ux * math.sin(a) + uy * math.cos(a)
    s = col.s
    h = s.h if s is not None else col.m.depth
    b = s.b if s is not None else col.m.width
    if s is not None and s.shape == "circleHollow":
        return "v", h / 2
    if abs(ly) >= abs(lx):
        return ("o" if ly > 0 else "u"), (h / 2) / max(abs(ly), 1e-9)
    if s is not None and s.shape in ("I", "U"):
        return "v", (s.tw / 2) / max(abs(lx), 1e-9)
    return ("v" if lx > 0 else "h"), (b / 2) / max(abs(lx), 1e-9)


def supports(
    me: _Member, point: Point3, inward: Point3, members: Sequence[_Member]
) -> _Support | None:
    """What the end of ``me`` at ``point`` frames into (``inward``: the unit vector from the end
    into the member): a column whose axis passes there (its face toward the member), else a beam
    or brace whose axis passes there and that is not in line with ``me`` (its web; a brace: the
    beam's flange)."""
    best: tuple[float, _Support] | None = None
    for o in members:
        if o is me:
            continue
        if o.vertical and not me.vertical:
            dxy = math.hypot(point[0] - o.start[0], point[1] - o.start[1])
            lo, hi = sorted((o.start[2], o.end[2]))
            if dxy > max(o.m.depth, o.m.width) / 2 + TOL or not lo - TOL <= point[2] <= hi + TOL:
                continue
            face, reach = _column_face(o, (inward[0], inward[1]))
            horizontal = math.hypot(inward[0], inward[1])
            if horizontal < 1e-6:
                continue
            candidate = _Support(o, face, reach / horizontal, point[2] - lo)
            # of the columns below and above a floor, the one below (a beam hangs from its top)
            rank = dxy + (0.0 if lo < point[2] - TOL else 1.0)
        else:
            if abs(_dot(me.u, o.u)) > 0.995:
                continue  # in line: a continuation, not a support
            d = (point[0] - o.start[0], point[1] - o.start[1], point[2] - o.start[2])
            t = min(max(_dot(d, o.u), 0.0), o.length)
            dist = math.dist(point, o.at(t))
            if dist > max(o.m.depth, o.m.width) / 2 + TOL:
                continue
            sin = math.sqrt(max(1 - _dot(me.u, o.u) ** 2, 1e-9))
            if me.m.kind == "brace":
                # a brace meets a beam's flange (its depth)
                candidate = _Support(o, "o" if inward[2] < 0 else "u", (o.m.depth / 2) / sin, t)
            else:
                web = o.s.tw if o.s is not None else o.m.width
                candidate = _Support(o, "v", (web / 2) / sin, t)
            rank = 1000.0 + dist
        if best is None or rank < best[0]:
            best = (rank, candidate)
    return best[1] if best else None


# ─────────────────────────────────── building it ───────────────────────────────────


def _plate(
    role: str,
    length: float,
    width: float,
    thickness: float,
    grade: str,
    density: float,
    holes: Sequence[Hole] = (),
    contour: list[Point] | None = None,
) -> Part:
    return Part(
        kind="plate",
        role=role,
        name=f"PL {thickness:g}x{width:.0f}",
        profile=f"PL{thickness:g}*{width:.0f}",
        code="B",
        grade=grade,
        length=round(length, 1),
        h=round(width, 1),
        tw=thickness,
        mass_per_m=width * thickness * 1e-6 * density,
        paint_per_m=2.0,
        density=density,
        holes=list(holes),
        contour=contour,
    )


def _plate_grade(c: Any, me: _Member, materials: Any) -> str:
    """The plates' grade: the connection's plate material, else the member's."""
    pid = getattr(c, "plateMaterial", None)
    if pid and materials is not None:
        mat = materials.get(pid)
        if mat is not None:
            steel = getattr(mat, "steel", None)
            return (steel.grade if steel is not None and steel.grade else None) or mat.name or pid
    return me.grade


def _bolt_rows(rows: int, pitch: float, end: float) -> tuple[float, list[float]]:
    """(plate length, bolt positions from its edge) of a line of ``rows`` bolts."""
    return 2 * end + (rows - 1) * pitch, [end + i * pitch for i in range(rows)]


class _Builder:
    def __init__(self, members: list[_Member], materials: Any, opts: FabricationOptions) -> None:
        self.members = members
        self.materials = materials
        self.opts = opts
        self.notes: list[str] = []
        self.stiffened: set[tuple[str, int]] = set()  # (column, level) with stiffeners already

    # ── pieces and their main parts ──

    def pieces(self, me: _Member) -> None:
        splice = getattr(me.t, "splice", None)
        L = me.length
        is_i = me.s is not None and me.s.shape == "I"
        if splice is not None and 0 < splice.distance < L and is_i:
            me.pieces = [_Piece(me, 0.0, splice.distance, 1), _Piece(me, splice.distance, L, 2)]
            me.pieces[0].cut1 = me.pieces[1].cut0 = splice.gap / 2
        else:
            if splice is not None:
                self.notes.append(
                    f"{me.m.id}: the splice is not fabricated (I sections, within the length)."
                )
            me.pieces = [_Piece(me, 0.0, L, 0)]
        s = me.s
        for p in me.pieces:
            name, profile = _profile_names(s, me.m.section)
            main = Part(
                kind="profile",
                role="main",
                name=name,
                profile=profile,
                code=DSTV_CODES.get(s.shape if s is not None else me.m.shape, "SO"),
                grade=me.grade,
                length=0.0,
                h=s.h if s is not None else me.m.depth,
                b=s.b if s is not None else me.m.width,
                tw=s.tw if s is not None else 0.0,
                tf=s.tf if s is not None else 0.0,
                r=s.r if s is not None else 0.0,
                mass_per_m=s.mass if s is not None else 0.0,
                paint_per_m=_paint(s),
                density=me.density,
                shape=s.shape if s is not None else me.m.shape,
            )
            if s is None:
                main.notes.append("Section not in the steel table: its mass is not known.")
            member_id = me.m.id if len(me.pieces) == 1 else f"{me.m.id}/{p.index}"
            p.assembly = Assembly(
                me.m.kind,
                member_id,
                main,
                start=me.at(p.t0),
                end=me.at(p.t1),
                section=me.m.section,
            )

    # ── the ends ──

    def ends(self, me: _Member) -> None:
        kind = me.m.kind
        c = getattr(me.t, "connection", None)
        for which in ("start", "end"):
            piece = me.pieces[0] if which == "start" else me.pieces[-1]
            asm = piece.assembly
            assert asm is not None
            if kind == "column":
                self._column_end(me, piece, which)
                continue
            point = me.start if which == "start" else me.end
            u = me.u
            inward = u if which == "start" else (-u[0], -u[1], -u[2])
            sup = supports(me, point, inward, self.members)
            label = which.capitalize()
            if sup is None:
                asm.notes.append(
                    f"{label}: no steel member to frame into; cut at the set-out point."
                )
            reach = sup.reach if sup is not None else 0.0
            handler = getattr(self, f"_{c.type}", None) if c is not None else None
            if c is None:
                self._cut(piece, which, reach + (self.opts.end_clearance if sup else 0.0))
                if sup is not None:
                    asm.notes.append(
                        f"{label}: no connection designed (04 Objects); cut "
                        f"{self.opts.end_clearance:g} mm clear of {sup.member.m.id}."
                    )
            elif handler is None:
                self._cut(piece, which, reach)
                asm.notes.append(f"{label}: a {c.type} connection is not detailed for fabrication.")
            else:
                handler(me, piece, which, sup, c)
            if (
                kind == "beam"
                and sup is not None
                and (c is None or c.type in ("finPlate", "endPlate"))
            ):
                self._copes(me, piece, which, sup)
        if len(me.pieces) == 2:
            self._splice(me, me.t.splice)

    @staticmethod
    def _cut(piece: _Piece, which: str, amount: float) -> None:
        if which == "start":
            piece.cut0 = max(piece.cut0, amount)
        else:
            piece.cut1 = max(piece.cut1, amount)

    @staticmethod
    def _at_end(asm: Assembly, part: Part, which: str, weld: Weld | None, what: str) -> None:
        """A part at the start or the end of the main part (its x set when finished)."""
        asm.parts.append(Attached(part, 0.0, which, weld, what))

    def _attach(
        self,
        sup: _Support | None,
        own: _Piece,
        part: Part,
        weld: Weld,
        what: str,
        offset: float = 0.0,
        angle: float = 0.0,
        dt: float = 0.0,
        level: float | None = None,
        anchor: float = 0.0,
    ) -> None:
        """A part welded to the support's assembly, else a loose part of ``own``'s. ``dt``: the
        part's level below the support point (``level``, the supported end's set-out level): on
        a column along its axis, on a beam the height on its web (the drawing's ``offset``);
        ``anchor``: the point of the part at the support point (a gusset's weld centre)."""
        if sup is not None:
            o = sup.member
            t = sup.t + (dt if o.vertical else 0.0)
            if not o.vertical and level is not None:
                depth = o.s.h if o.s is not None else o.m.depth
                offset = depth - (o.at(sup.t)[2] - (level + dt))
            target = o.piece_at(t)
            if target is not None and target.assembly is not None:
                target.assembly.parts.append(
                    Attached(
                        part, t, sup.face, weld, what, offset, angle, on_axis=True, anchor=anchor
                    )
                )
                return
        asm = own.assembly
        assert asm is not None
        asm.parts.append(Attached(part, 0.0, "", None, f"{what} (loose: weld on site)", offset))
        asm.notes.append(
            f"{part.role.capitalize()} {what}: no steel member to weld it to in the shop; "
            "shipped loose."
        )

    def _support_holes(
        self,
        sup: _Support | None,
        offsets: Sequence[tuple[float, float]],
        dia: float,
        group: str,
        level: float,
    ) -> None:
        """Holes in the support for a bolted end: ``offsets`` (vertical from ``level``, the
        supported end's set-out level, and horizontal across the member). On a column the
        vertical goes along its axis; on a beam the horizontal does."""
        if sup is None:
            return
        o = sup.member
        piece = o.piece_at(sup.t)
        if piece is None or piece.assembly is None:
            return
        main = piece.assembly.main
        for dz, dh in offsets:
            if o.vertical:
                y = (main.b if sup.face in ("o", "u") else main.h) / 2 + dh
                t = level + dz - min(o.start[2], o.end[2])
                main.holes.append(Hole(sup.face or "v", t, y, dia, group, on_axis=True))
            else:
                top = o.at(sup.t)[2]  # a beam's set-out line is its top
                y = main.h - (top - (level + dz))
                main.holes.append(Hole("v", sup.t + dh, y, dia, group, on_axis=True))

    def _copes(self, me: _Member, piece: _Piece, which: str, sup: _Support) -> None:
        """A beam framing into a beam's web with its top (or bottom) within the supporting
        flanges is coped clear of them."""
        o = sup.member
        if o.vertical or o.m.kind != "beam" or me.s is None or o.s is None:
            return
        top_me = (me.start if which == "start" else me.end)[2]
        top_o = o.at(sup.t)[2]
        clear = self.opts.cope_clearance
        length = (o.s.b - o.s.tw) / 2 + clear
        main = piece.assembly.main  # type: ignore[union-attr]
        under_flange = top_o - o.s.tf - o.s.r
        if top_me > under_flange + 1e-6:
            main.copes.append(
                Cope(which, "top", round(length), round(top_me - under_flange + clear))
            )
        bottom_me = top_me - me.s.h
        over_flange = top_o - o.s.h + o.s.tf + o.s.r
        if bottom_me < over_flange - 1e-6:
            main.copes.append(
                Cope(which, "bottom", round(length), round(over_flange - bottom_me + clear))
            )

    def _bolt_line(
        self,
        main: Part,
        which: str,
        x: float,
        ys: Sequence[float],
        hp: float,
        dia: float,
        group: str,
    ) -> None:
        """A vertical line of bolts in a web at ``x`` from the end, centred on the depth."""
        base = main.h / 2 - hp / 2
        for y in ys:
            main.holes.append(Hole("v", x, base + y, dia, group, from_end=which == "end"))

    # ── connections (handlers named by the connection's type) ──

    def _finPlate(
        self, me: _Member, piece: _Piece, which: str, sup: _Support | None, c: Any
    ) -> None:
        gap = self.opts.end_clearance
        self._cut(piece, which, (sup.reach if sup else 0.0) + gap)
        main = piece.assembly.main  # type: ignore[union-attr]
        dia = bolt_hole(c.boltDiameter)
        hp, ys = _bolt_rows(c.rows, c.pitch, c.endDistance)
        a = c.boltLineOffset
        x = a - gap
        if x < c.endDistance:
            piece.assembly.notes.append(  # type: ignore[union-attr]
                f"{which.capitalize()}: the bolt line is {x:.0f} mm from the cut end, less than "
                f"the end distance {c.endDistance:g} mm."
            )
        self._bolt_line(main, which, x, ys, hp, dia, f"{which} fin plate")
        plate = _plate(
            "fin plate",
            hp,
            a + c.edgeDistance,
            c.plateThickness,
            _plate_grade(c, me, self.materials),
            me.density,
            [Hole("v", y, a, dia) for y in ys],
        )
        h = me.s.h if me.s is not None else me.m.depth
        level = (me.start if which == "start" else me.end)[2]
        self._attach(
            sup, piece, plate, Weld(c.weldSize, hp), f"for {me.m.id}", dt=-h / 2, level=level
        )

    def _endPlate(
        self, me: _Member, piece: _Piece, which: str, sup: _Support | None, c: Any
    ) -> None:
        self._cut(piece, which, (sup.reach if sup else 0.0) + c.plateThickness)
        dia = bolt_hole(c.boltDiameter)
        hp, ys = _bolt_rows(c.rows, c.pitch, c.endDistance)
        bp = c.gauge + 2 * c.edgeDistance
        xs = (c.edgeDistance, c.edgeDistance + c.gauge)
        holes = [Hole("v", y, x, dia) for y in ys for x in xs]
        grade = _plate_grade(c, me, self.materials)
        plate = _plate("end plate", hp, bp, c.plateThickness, grade, me.density, holes)
        asm = piece.assembly
        assert asm is not None
        self._at_end(asm, plate, which, Weld(c.weldSize, hp), "end plate")
        # the support drilled to match: the rows about the beam's mid-depth
        h = me.s.h if me.s is not None else me.m.depth
        offsets = [(-h / 2 - hp / 2 + y, g) for y in ys for g in (-c.gauge / 2, c.gauge / 2)]
        level = (me.start if which == "start" else me.end)[2]
        self._support_holes(sup, offsets, dia, f"end plate of {me.m.id}", level)

    def _flangePlate(
        self, me: _Member, piece: _Piece, which: str, sup: _Support | None, c: Any
    ) -> None:
        self._cut(piece, which, (sup.reach if sup else 0.0) + c.setback)
        main = piece.assembly.main  # type: ignore[union-attr]
        dia = bolt_hole(c.boltDiameter)
        grade = _plate_grade(c, me, self.materials)
        spread = (c.lines - 1) * c.gauge / 2
        for face in ("o", "u"):
            for i in range(c.rows):
                for j in range(c.lines):
                    main.holes.append(
                        Hole(
                            face,
                            c.endDistance + i * c.pitch,
                            main.b / 2 - spread + j * c.gauge,
                            dia,
                            f"{which} flange plate",
                            from_end=which == "end",
                        )
                    )
        # the web's fin plate
        hp, ys = _bolt_rows(c.webRows, c.pitch, c.endDistance)
        self._bolt_line(main, which, c.webBoltLineOffset - c.setback, ys, hp, dia, f"{which} web")
        length = c.setback + 2 * c.endDistance + (c.rows - 1) * c.pitch
        width = 2 * spread + 2 * c.edgeDistance
        holes = [
            Hole("v", c.setback + c.endDistance + i * c.pitch, c.edgeDistance + j * c.gauge, dia)
            for i in range(c.rows)
            for j in range(c.lines)
        ]
        if c.plateWeld == "cjp":
            weld = Weld(c.plateThickness, width, kind="cjp")
        else:
            weld = Weld(c.weldSize, width)
        h = me.s.h if me.s is not None else me.m.depth
        level = (me.start if which == "start" else me.end)[2]
        for name, dz in (("top", 0.0), ("bottom", -h)):
            plate = _plate(
                "flange plate", length, width, c.plateThickness, grade, me.density, holes
            )
            self._attach(
                sup, piece, plate, weld, f"{name} for {me.m.id}", offset=dz, dt=dz, level=level
            )
        fin = _plate(
            "fin plate",
            hp,
            c.webBoltLineOffset + c.edgeDistance,
            c.webPlateThickness,
            grade,
            me.density,
            [Hole("v", y, c.webBoltLineOffset, dia) for y in ys],
        )
        self._attach(
            sup, piece, fin, Weld(c.weldSize, hp), f"web for {me.m.id}", dt=-h / 2, level=level
        )
        self._stiffeners(me, sup, c, grade)

    def _stiffeners(self, me: _Member, sup: _Support | None, c: Any, grade: str) -> None:
        """Column stiffeners opposite the beam flanges and a doubler plate (flange plate moment
        connections), once per column and level."""
        if sup is None or not sup.member.vertical or sup.member.s is None or me.s is None:
            return
        col = sup.member.s
        if col.shape != "I" or sup.face not in ("o", "u"):
            return
        key = (sup.member.m.id, round(sup.t))
        if key in self.stiffened:
            return
        self.stiffened.add(key)
        h = me.s.h
        target = sup.member.piece_at(sup.t)
        if target is None or target.assembly is None:
            return
        parts = target.assembly.parts
        if c.columnStiffeners:
            width = c.stiffenerWidth or (col.b - col.tw) / 2
            t = c.stiffenerThickness or c.plateThickness
            weld = Weld(c.weldSize, None, note="to both flanges and the web")
            for level, dz in (("top", -me.s.tf / 2), ("bottom", -h + me.s.tf / 2)):
                for side in (1, -1):
                    plate = _plate("stiffener", col.h - 2 * col.tf, width, t, grade, me.density)
                    parts.append(
                        Attached(
                            plate,
                            sup.t + dz,
                            "v",
                            weld,
                            f"{level} flange level of {me.m.id}",
                            offset=side * (col.tw / 2 + width / 2),
                            on_axis=True,
                        )
                    )
        if c.doublerThickness > 0:
            width = col.h - 2 * (col.tf + col.r)
            plate = _plate("doubler", h, width, c.doublerThickness, grade, me.density)
            parts.append(
                Attached(
                    plate,
                    sup.t - h,
                    "v",
                    Weld(c.weldSize, None),
                    "panel zone doubler",
                    on_axis=True,
                )
            )

    def _gusset(self, me: _Member, piece: _Piece, which: str, sup: _Support | None, c: Any) -> None:
        from saengine.design.steel_connections import whitmore_width
        from saengine.drawings.sheets.model import SteelConnectionDetail
        from saengine.drawings.sheets.steel import GussetGeometry

        s = me.s
        shape = s.shape if s is not None else me.m.shape
        angle = 45.0
        if sup is not None:
            angle = math.degrees(math.acos(min(abs(_dot(me.u, sup.member.u)), 1.0)))
        detail = SteelConnectionDetail(
            "",
            "gusset",
            c.model_dump(mode="json"),
            me.m.section,
            shape,
            s.h if s is not None else me.m.depth,
            s.b if s is not None else me.m.width,
            s.tw if s is not None else 0.0,
            s.tf if s is not None else 0.0,
            angle=angle,
            whitmore=max(whitmore_width(c.rows, c.lines, c.pitch, c.gauge), 2 * c.boltDiameter),
        )
        g = GussetGeometry(detail)
        reach = sup.reach if sup is not None else 0.0
        dia = bolt_hole(c.boltDiameter)
        grade = _plate_grade(c, me, self.materials)
        asm = piece.assembly
        assert asm is not None
        main = asm.main
        spread = (g.lines - 1) * g.gauge / 2
        label = which.capitalize()
        if shape in ("L", "U") and not c.tabThickness:
            # an angle's leg or a channel's web bolted straight to the gusset
            self._cut(piece, which, reach + g.tab_end)
            for i in range(g.rows):
                for j in range(g.lines):
                    if shape == "L":
                        y = main.h - g.edge - j * g.gauge  # from the heel
                    else:
                        y = main.h / 2 - spread + j * g.gauge
                    main.holes.append(
                        Hole("v", g.end + i * g.pitch, y, dia, f"{which} gusset", which == "end")
                    )
            if shape == "L" and g.edge + (g.lines - 1) * g.gauge > main.h - main.tw:
                asm.notes.append(f"{label}: the bolt lines do not fit the angle's leg.")
        else:
            self._cut(piece, which, reach + g.brace_end)
            tab_t = c.tabThickness or c.plateThickness
            holes = [
                Hole("v", g.first - g.tab_end + i * g.pitch, g.half_tab - spread + j * g.gauge, dia)
                for i in range(g.rows)
                for j in range(g.lines)
            ]
            length = g.brace_end + g.tab_weld - g.tab_end
            tab = _plate("tab", length, 2 * g.half_tab, tab_t, grade, me.density, holes)
            weld = Weld(c.weldSize, g.tab_weld, note=f"{c.tabWelds} welds")
            self._at_end(asm, tab, which, weld, "tab in the slotted end")
            asm.notes.append(
                f"{label}: slot {g.tab_weld + 10:.0f} long x {tab_t + 2:g} wide for the tab, the "
                f"tab {g.brace_end - g.tab_end:.0f} out of the end (the slot is not in the NC "
                "file's contour)."
            )
        # the gusset plate: the connection details' outline, welded along its bottom edge
        xs = [x for x, _ in g.gusset]
        ys = [y for _, y in g.gusset]
        x0, y0 = min(xs), min(ys)
        contour = [(round(x - x0, 1), round(y - y0, 1)) for x, y in g.gusset]
        holes = []
        for st, tt in g.bolts:
            px, py = g.at(st, tt)
            holes.append(Hole("v", px - x0, py - y0, dia))
        plate = _plate(
            "gusset",
            max(xs) - x0,
            max(ys) - y0,
            c.plateThickness,
            grade,
            me.density,
            holes,
            contour,
        )
        weld = Weld(c.weldSize, c.gussetWeldLength)
        self._attach(sup, piece, plate, weld, f"for {me.m.id}", angle=angle, anchor=-x0)

    def _hssJoint(
        self, me: _Member, piece: _Piece, which: str, sup: _Support | None, c: Any
    ) -> None:
        self._welded_branch(piece, which, sup, c.angle)

    def _hssMoment(
        self, me: _Member, piece: _Piece, which: str, sup: _Support | None, c: Any
    ) -> None:
        self._welded_branch(piece, which, sup, c.angle)

    def _welded_branch(self, piece: _Piece, which: str, sup: _Support | None, angle: float) -> None:
        """An HSS branch welded all round to the chord: cut to the chord's face with its end cut
        to the branch angle (a round branch: profiled to the chord by the fabricator)."""
        self._cut(piece, which, sup.reach if sup else 0.0)
        asm = piece.assembly
        assert asm is not None
        main = asm.main
        skew = 90.0 - angle
        cuts = list(main.cuts)
        cuts[0 if which == "start" else 1] = skew
        main.cuts = (cuts[0], cuts[1], cuts[2], cuts[3])
        asm.notes.append(
            f"{which.capitalize()}: welded all round to "
            f"{sup.member.m.id if sup else 'the chord'} to develop the branch"
            + (", profiled to the round chord" if main.code == "RO" else "")
            + (f"; end cut {skew:.1f}° from square." if abs(skew) > 0.05 else ".")
        )

    def _splice(self, me: _Member, c: Any) -> None:
        """Holes at the joint of a cover-plate splice and its loose plates (with the first
        piece's assembly)."""
        first, second = me.pieces
        dia = bolt_hole(c.boltDiameter)
        grade = _plate_grade(c, me, self.materials)
        spread = (c.lines - 1) * c.gauge / 2
        hw, wys = _bolt_rows(c.webRows, c.webPitch, c.webEndDistance)
        for piece, which in ((first, "end"), (second, "start")):
            main = piece.assembly.main  # type: ignore[union-attr]
            for face in ("o", "u"):
                for i in range(c.rows):
                    for j in range(c.lines):
                        main.holes.append(
                            Hole(
                                face,
                                c.endDistance + i * c.pitch,
                                main.b / 2 - spread + j * c.gauge,
                                dia,
                                "splice",
                                from_end=which == "end",
                            )
                        )
            self._bolt_line(main, which, c.webEndDistance, wys, hw, dia, "splice web")
        flange_l = 2 * (2 * c.endDistance + (c.rows - 1) * c.pitch) + c.gap
        flange_w = 2 * spread + 2 * c.edgeDistance
        holes = []
        for i in range(c.rows):
            for x in (c.endDistance + i * c.pitch, flange_l - c.endDistance - i * c.pitch):
                holes += [Hole("v", x, c.edgeDistance + j * c.gauge, dia) for j in range(c.lines)]
        web_l = 4 * c.webEndDistance + c.gap
        web_holes = [
            Hole("v", x, y, dia) for y in wys for x in (c.webEndDistance, web_l - c.webEndDistance)
        ]
        asm = first.assembly
        assert asm is not None
        for name in ("top flange", "bottom flange"):
            plate = _plate(
                "splice plate", flange_l, flange_w, c.plateThickness, grade, me.density, holes
            )
            self._at_end(asm, plate, "end", None, f"splice, {name}")
        for name in ("web, front", "web, back"):
            plate = _plate(
                "splice plate", web_l, hw, c.webPlateThickness, grade, me.density, web_holes
            )
            self._at_end(asm, plate, "end", None, f"splice, {name}")
        if me.m.kind == "column" and c.finishedToBear:
            for piece in me.pieces:
                piece.assembly.notes.append("Ends at the splice milled to bear.")  # type: ignore[union-attr]

    # ── columns ──

    def _column_end(self, me: _Member, piece: _Piece, which: str) -> None:
        asm = piece.assembly
        assert asm is not None
        z = me.start[2] if which == "start" else me.end[2]
        x0, y0 = me.start[0], me.start[1]

        def stacked(top: bool) -> bool:
            return any(
                o is not me
                and o.vertical
                and math.hypot(o.start[0] - x0, o.start[1] - y0) < TOL
                and abs((max if top else min)(o.start[2], o.end[2]) - z) < TOL
                for o in self.members
            )

        below = which == "start" and stacked(True)
        above = which == "end" and stacked(False)
        base = getattr(me.t, "basePlate", None)
        cap = getattr(me.t, "capPlate", None)
        s = me.s
        if which == "start" and base is not None and not below:
            from saengine.design.steel_connections import anchor_points

            self._cut(piece, which, base.thickness)
            dia = base.anchorDiameter + self.opts.anchor_clearance
            holes = [
                Hole("v", base.length / 2 + px, base.width / 2 + py, dia)
                for px, py in anchor_points(base)
            ]
            grade = _plate_grade(base, me, self.materials)
            plate = _plate(
                "base plate", base.length, base.width, base.thickness, grade, me.density, holes
            )
            self._at_end(
                asm, plate, "start", Weld(base.weldSize, None, note="all round"), "base plate"
            )
        elif which == "end" and cap is not None and not above and s is not None:
            self._cut(piece, which, cap.thickness)
            plate = _plate("cap plate", s.h, s.b, cap.thickness, me.grade, me.density)
            leg = max(round(min(s.tw, cap.thickness)), 3)
            self._at_end(asm, plate, "end", Weld(leg, None, note="all round"), "cap plate")
            asm.notes.append(
                f"Cap plate fillet weld {leg} mm all round (the wall thickness, SAEngine practice)."
            )
        elif below or above:
            where = "Bottom: on the column below" if below else "Top: under the column above"
            asm.notes.append(f"{where}; ends cut square to bear.")

    # ── finishing ──

    @staticmethod
    def finish(piece: _Piece) -> Assembly:
        asm = piece.assembly
        assert asm is not None
        main = asm.main
        main.length = round(piece.length, 1)
        if main.length <= 0:
            asm.notes.append("The member is shorter than its end cuts: check the model.")
        for h in main.holes:
            if h.on_axis:
                h.x, h.on_axis = piece.local(h.x), False
        for a in asm.parts:
            if a.on_axis:
                a.x, a.on_axis = piece.local(a.x), False
            elif a.face == "start":
                a.x = 0.0
            elif a.face == "end":
                a.x = main.length
            a.part.finish()
        main.finish()
        return asm


def build(
    bim: Any,
    objects: Any,
    materials: Any,
    options: FabricationOptions | None = None,
) -> FabricationModel:
    """The fabrication model of the project's structural steel (see the module notes); empty
    without steel members."""
    opts = options or FabricationOptions()
    members = _members(bim, objects, materials)
    model = FabricationModel()
    if not members:
        return model
    b = _Builder(members, materials, opts)
    for me in members:
        b.pieces(me)
    for me in members:
        b.ends(me)
    for me in members:
        for piece in me.pieces:
            model.assemblies.append(b.finish(piece))
    model.notes = b.notes
    mark(model, opts)
    return model


def mark(model: FabricationModel, opts: FabricationOptions) -> None:
    """Part marks (one per identical part; the main parts first) and assembly marks (one per
    identical assembly), in the order of the members (by kind, then their ids)."""
    order = sorted(
        model.assemblies,
        key=lambda a: (KINDS.index(a.kind) if a.kind in KINDS else 9, natural_key(a.member)),
    )
    parts = [a.main for a in order] + [x.part for a in order for x in a.parts]
    by_part: dict[tuple[Any, ...], str] = {}
    for p in parts:
        key = p.signature()
        if key not in by_part:
            by_part[key] = f"{opts.part_prefix}{len(by_part) + 1}"
        p.mark = by_part[key]
    by_assembly: dict[tuple[Any, ...], str] = {}
    counts: dict[str, int] = {}
    groups: dict[str, list[Assembly]] = {}
    for a in order:
        key = a.signature()
        if key not in by_assembly:
            prefix = opts.prefixes.get(a.kind, a.kind[:1].upper())
            counts[prefix] = counts.get(prefix, 0) + 1
            by_assembly[key] = f"{prefix}{counts[prefix]}"
        a.mark = by_assembly[key]
        groups.setdefault(a.mark, []).append(a)
    for same in groups.values():
        names = [a.member for a in same]
        for a in same:
            a.members = names
