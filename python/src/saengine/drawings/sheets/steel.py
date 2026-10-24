"""Structural steel sheets: the steel framing plan of each level, the elevations of the braced
bays, the steel member schedule, the connection details and the steel general notes, drawn only
when the project has structural steel members (object types of 04 Objects whose material is a
steel of 03 Materials).

What is drawn comes from elsewhere and is not worked out here:

- members: the building model (06 BIM: beams, columns, members and the inclined members of
  ``additions.members``) with their object types;
- masses: the bill of quantities (``10 BOQ/boq.json``, :mod:`saengine.boq.quantities`), per
  member as its breakdown lists it, so that the schedule's total is the BOQ's steel total. When
  the bill is missing or older than the building model, object types or materials, the BOQ
  module measures it again in memory (and the problems say so);
- connections: the designed simple connection of each object type (``connection`` of 04
  Objects, checked by :mod:`saengine.design.steel_connections`), its bolt pattern, plates and
  welds as given there; the Whitmore width is the design module's; the utilisation is the
  design checks' when the drawings are made with them.

Conventions: weld symbols to AWS A2.4 (the reference line, the arrow, the fillet triangle with
its perpendicular leg on the left: below the line on the arrow side, above it on the other
side, the leg size left of it and the length right of it, the tail for notes); bolts are drawn
as their holes with a cross. Layers ``S-STEEL``, ``S-STEEL-AXIS``, ``S-STEEL-PLATE``, ``S-BOLT``
and ``S-WELD`` (docs/drawings-layers.md).
"""

from __future__ import annotations

import itertools
import json
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from saengine.drawings.sheets.layout import (
    TEXT,
    TEXT_LARGE,
    View,
    ViewSpec,
    tag,
    text_rect,
    text_width,
)
from saengine.drawings.sheets.model import (
    Building,
    Level,
    Point,
    SteelConnectionDetail,
    SteelMember,
    SteelSet,
    Table,
)

EPS = 1.0  # mm
BOQ_FILE = "10 BOQ/boq.json"
KINDS = ("beam", "column", "brace")
CONNECTION_SCALE = 5.0
"""The connection details' scale (1:5)."""
WELD_STANDARD = "AWS A2.4"
GUSSET_CLEARANCE = 50.0
"""mm a brace tab's corner keeps from the frame member the gusset is welded to (drafting)."""
BRACE_SETBACK = 50.0
"""mm from the gusset's free end to the brace's end (drafting: room to erect and weld)."""


def natural_key(text: str) -> tuple[Any, ...]:
    """``M2`` before ``M10``."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text))


# ─────────────────────────────────── the project's steel ───────────────────────────────────


def _is_steel(material: Any) -> bool:
    from saengine.library.materials import Category

    return material is not None and material.category == Category.STEEL


def _section(profile: Any) -> tuple[str, str, float, float, float, float]:
    """name, shape, depth, width, web, flange of a steel profile (the section table's)."""
    from saengine.library.steel_sections import section_of_profile

    try:
        s = section_of_profile(profile)
    except (TypeError, ValueError, KeyError, AttributeError):
        p = profile.model_dump() if hasattr(profile, "model_dump") else dict(profile)
        h = float(p.get("yDim") or p.get("overallDepth") or p.get("depth") or 200)
        b = float(p.get("xDim") or p.get("overallWidth") or p.get("flangeWidth") or h)
        t = float(p.get("wallThickness") or p.get("webThickness") or 8)
        return f"{p.get('shape', 'section')} {h:g}x{b:g}", str(p.get("shape", "")), h, b, t, t
    name = s.name
    if name == "custom":
        name = f"{s.family} {s.h:g}x{s.b:g}x{s.tw:g}" if s.tw else f"{s.family} {s.h:g}x{s.b:g}"
    return name, s.shape, s.h, s.b, s.tw, s.tf


def steel_members(bim: Any, objects: Any, materials: Any) -> list[SteelMember]:
    """The structural steel members of the building model (beams, columns, braces)."""
    if materials is None:
        return []
    types = {o.id: o for o in objects.objects}
    out: list[SteelMember] = []

    def add(member_id: str, type_id: str, start, end) -> None:
        t = types.get(type_id)
        if t is None or t.kind not in KINDS or getattr(t, "profile", None) is None:
            return
        material = materials.get(t.material)
        if not _is_steel(material):
            return
        name, shape, h, b, _, _ = _section(t.profile)
        grade = material.steel.grade if material.steel is not None else material.name
        out.append(
            SteelMember(
                member_id,
                member_id,
                t.kind,
                name,
                shape,
                h,
                b,
                tuple(float(v) for v in start),  # type: ignore[arg-type]
                tuple(float(v) for v in end),  # type: ignore[arg-type]
                grade,
                material.id,
            )
        )

    for e in bim.elements:
        if e.kind == "column":
            add(e.id, e.type, (*e.position, e.bottom), (*e.position, e.top))
        elif e.kind == "beam":
            add(e.id, e.type, (*e.start, e.elevation), (*e.end, e.elevation))
        elif e.kind == "member":
            add(e.id, e.type, e.start, e.end)
    for m in bim.additions.members:
        add(m.id, m.type, (m.x1, m.y1, m.z1), (m.x2, m.y2, m.z2))
    out.sort(key=lambda m: (KINDS.index(m.kind), natural_key(m.mark)))
    return out


def _slope(member: SteelMember) -> float:
    (x1, y1, z1), (x2, y2, z2) = member.start, member.end
    return math.degrees(math.atan2(abs(z2 - z1), math.hypot(x2 - x1, y2 - y1)))


def _design_entries(design_report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for e in (design_report or {}).get("elements") or []:
        if isinstance(e, dict) and e.get("connections"):
            out[str(e.get("id") or e.get("member"))] = e
    return out


def steel_connections(
    members: list[SteelMember],
    bim: Any,
    objects: Any,
    materials: Any,
    design_report: dict[str, Any] | None = None,
) -> list[SteelConnectionDetail]:
    """One connection detail per object type that has a ``connection`` (marks CN1, CN2...),
    with the members using it; sets the members' ``connection`` marks."""
    from saengine.design.steel_connections import whitmore_width

    types = {o.id: o for o in objects.objects}
    type_of = {e.id: e.type for e in bim.elements}
    type_of.update({m.id: m.type for m in bim.additions.members})
    design = _design_entries(design_report)
    found: dict[str, SteelConnectionDetail] = {}
    for member in members:
        t = types.get(type_of.get(member.id, ""))
        c = getattr(t, "connection", None) if t is not None else None
        if c is None:
            continue
        detail = found.get(t.id)
        if detail is None:
            _, shape, h, b, tw, tf = _section(t.profile)
            data = c.model_dump(mode="json")
            plate = materials.get(c.plateMaterial) if c.plateMaterial else None
            plate = plate if _is_steel(plate) else materials.get(t.material)
            whitmore = None
            if c.type == "gusset":
                whitmore = max(
                    whitmore_width(c.rows, c.lines, c.pitch, c.gauge), 2 * c.boltDiameter
                )
            detail = found[t.id] = SteelConnectionDetail(
                f"CN{len(found) + 1}",
                c.type,
                data,
                member.section,
                shape,
                h,
                b,
                tw,
                tf,
                plate_grade=plate.id if plate is not None else "",
                angle=_slope(member) if member.kind == "brace" else 0.0,
                whitmore=whitmore,
            )
        detail.members.append(member.mark)
        member.connection = detail.mark
        entry = design.get(member.id)
        if entry:
            result = entry["connections"][0]
            u = float(result.get("utilisation") or 0.0)
            detail.utilisation = max(detail.utilisation or 0.0, u)
            detail.ok = bool(result.get("ok")) and detail.ok is not False
    return list(found.values())


def boq_steel(
    root: Path,
    texts: dict[str, str | None],
    bim: Any,
    objects: Any,
    materials: Any,
    substructure: Any = None,
) -> tuple[list[tuple[str, str, float]], dict[str, float], str, list[str]]:
    """The structural steel of the bill of quantities: its items ``(code, description, kg)``,
    the mass per member (its breakdown), where it came from and problems. ``10 BOQ/boq.json``
    when it was measured from the current building model, object types and materials; else
    measured again in memory by :mod:`saengine.boq.quantities` (nothing is written)."""
    from saengine.library.bim import source_stamp

    problems: list[str] = []
    doc = None
    source = "10 BOQ"
    text = None
    try:
        text = (root / BOQ_FILE).read_text(encoding="utf-8")
    except OSError:
        problems.append(
            "Steel: 10 BOQ has not been measured; the masses are measured for the drawings."
        )
    if text:
        try:
            doc = json.loads(text)
        except ValueError:
            problems.append("Steel: 10 BOQ/boq.json cannot be read; the masses are measured again.")
        else:
            recorded = doc.get("source") or {}
            stale = [
                k for k in ("bim", "objects", "materials")
                if texts.get(k) and recorded.get(k) != source_stamp(texts[k] or "")
            ]  # fmt: skip
            if stale:
                problems.append(
                    "Steel: 10 BOQ is older than "
                    + ", ".join({"bim": "06 BIM", "objects": "04 Objects", "materials":
                                 "03 Materials"}[k] for k in stale)
                    + "; the masses are measured again (measure the BOQ to bring it up to date)."
                )  # fmt: skip
                doc = None
    if doc is None:
        from saengine.boq.quantities import bill_of_quantities

        bill = bill_of_quantities(bim, objects, materials, substructure=substructure)
        doc = bill.model_dump(mode="json", by_alias=True, exclude_none=True)
        source = "the BOQ measured for the drawings"
    items: list[tuple[str, str, float]] = []
    by_member: dict[str, float] = {}
    for item in doc.get("items") or []:
        if item.get("group") != "steel":
            continue
        items.append((str(item.get("code")), str(item.get("description")), float(item["quantity"])))
        for entry in item.get("breakdown") or []:
            element = str(entry.get("element"))
            by_member[element] = by_member.get(element, 0.0) + float(entry.get("quantity") or 0)
    return items, by_member, source, problems


def steel_set(
    root: Path,
    texts: dict[str, str | None],
    bim: Any,
    objects: Any,
    materials: Any,
    substructure: Any = None,
    design_report: dict[str, Any] | None = None,
) -> tuple[SteelSet, list[str]]:
    """The project's structural steel for the sheets (an empty set: no steel sheets)."""
    members = steel_members(bim, objects, materials)
    if not members:
        return SteelSet(), []
    connections = steel_connections(members, bim, objects, materials, design_report)
    items, by_member, source, problems = boq_steel(
        root, texts, bim, objects, materials, substructure
    )
    for m in members:
        m.mass = by_member.get(m.id)
        if m.mass is None:
            problems.append(f"Steel: {m.mark} is not in the BOQ's structural steel.")
    total = round(sum(q for _, _, q in items), 3) if items else None
    grades = sorted({f"{m.grade} ({m.material})" if m.material else m.grade for m in members})
    bolts = sorted({str(c.data.get("boltGrade")) for c in connections})
    electrodes = sorted({float(c.data.get("electrode") or 480) for c in connections})
    return (
        SteelSet(members, connections, items, total, source, grades, bolts, electrodes),
        problems,
    )


# ─────────────────────────────────── tables and notes ───────────────────────────────────


def _kg(value: float | None, digits: int = 1) -> str:
    return "-" if value is None else f"{value:,.{digits}f}"


def member_schedule(steel: SteelSet, levels: Sequence[Level] = ()) -> Table:
    """The steel member schedule: mark, kind, section, grade, length, kg/m, mass (the BOQ's),
    the connections at its ends and its levels; the last row the total (the BOQ's)."""
    columns = [
        {"key": "mark", "title": "Mark", "width": 6, "align": "left"},
        {"key": "kind", "title": "Member", "width": 7, "align": "left"},
        {"key": "section", "title": "Section", "width": 14, "align": "left"},
        {"key": "grade", "title": "Grade", "width": 12, "align": "left"},
        {"key": "length", "title": "Length\n(mm)", "width": 7, "align": "right"},
        {"key": "kgm", "title": "Mass\n(kg/m)", "width": 7, "align": "right"},
        {"key": "mass", "title": "Mass\n(kg)", "width": 8, "align": "right"},
        {"key": "end1", "title": "End 1", "width": 6, "align": "left"},
        {"key": "end2", "title": "End 2", "width": 6, "align": "left"},
        {"key": "levels", "title": "From - to", "width": 16, "align": "left"},
    ]

    def level_at(z: float) -> str:
        for lv in levels:
            if abs(lv.elevation - z) < EPS:
                return lv.name
        return f"{z / 1000:+.3f}"

    rows = []
    for m in steel.members:
        ends = m.connection or "-"
        rows.append(
            [
                m.mark,
                m.kind,
                m.section,
                m.material or m.grade,
                f"{m.length:.0f}",
                _kg(m.mass_per_metre, 2),
                _kg(m.mass),
                ends,
                ends,
                f"{level_at(min(m.start[2], m.end[2]))} - {level_at(max(m.start[2], m.end[2]))}",
            ]
        )
    total = sum(m.mass for m in steel.members if m.mass is not None)
    rows.append(["TOTAL", "", "", "", "", "", _kg(total), "", "", ""])
    return Table(
        "Steel member schedule",
        columns,
        rows,
        notes=[f"Masses: {steel.boq_source}."],
    )


def quantities_table(steel: SteelSet) -> Table:
    """The structural steel items of the bill of quantities, as it lists them."""
    columns = [
        {"key": "code", "title": "BOQ\nitem", "width": 6, "align": "left"},
        {"key": "description", "title": "Description", "width": 40, "align": "left"},
        {"key": "kg", "title": "Quantity\n(kg)", "width": 10, "align": "right"},
    ]
    rows = [[code, text, _kg(q)] for code, text, q in steel.boq_items]
    rows.append(["", "Total structural steel", _kg(steel.boq_total)])
    return Table(f"Structural steel quantities ({steel.boq_source})", columns, rows)


def bolt_table(steel: SteelSet) -> Table:
    """Bolts per connection: per end and in all."""
    from saengine.design.steel_connections import hole_diameter

    columns = [
        {"key": "mark", "title": "Conn.", "width": 5, "align": "left"},
        {"key": "type", "title": "Type", "width": 12, "align": "left"},
        {"key": "bolt", "title": "Bolts", "width": 12, "align": "left"},
        {"key": "hole", "title": "Hole\nØ (mm)", "width": 6, "align": "right"},
        {"key": "end", "title": "Per\nend", "width": 5, "align": "right"},
        {"key": "ends", "title": "Ends", "width": 5, "align": "right"},
        {"key": "total", "title": "Total", "width": 6, "align": "right"},
    ]
    rows = []
    for c in steel.connections:
        d = float(c.data.get("boltDiameter") or 20)
        rows.append(
            [
                c.mark,
                TYPE_NAMES.get(c.kind, c.kind),
                f"M{d:g} {c.data.get('boltGrade')}",
                f"{hole_diameter(d):g}",
                str(c.bolts),
                str(c.ends),
                str(c.bolts * c.ends),
            ]
        )
    return Table("Bolts", columns, rows)


TYPE_NAMES = {"finPlate": "fin plate", "endPlate": "end plate", "gusset": "bolted gusset"}


def steel_notes(steel: SteelSet) -> list[str]:
    """The steel general notes (placeholders where the engineer has to specify)."""
    from saengine.design.steel_connections import BOLT_ALIASES

    bolts = []
    for grade in steel.bolt_grades:
        alias = BOLT_ALIASES.get(grade)
        bolts.append(f"ISO {grade} (taken as ASTM {alias} in design)" if alias else f"ASTM {grade}")
    electrodes = ", ".join(f"FEXX {e:g} MPa" + (" (E70XX)" if abs(e - 480) < 1 else "")
                           for e in steel.electrodes)  # fmt: skip
    notes = [
        (
            "Structural steel to BNBC 2020 Part 6 Chapter 10 (LRFD). Read with the general notes "
            "of the concrete drawings, the design report and the architectural drawings."
        ),
        "Steel grades: " + "; ".join(steel.grades) + ".",
    ]
    if bolts:
        notes.append(
            "Bolts: " + "; ".join(bolts) + ", bearing type, in standard holes (BNBC 2020 Table "
            "6.10.11), snug tight unless noted, with a hardened washer under the turned part. "
            "Pitch, gauge, end and edge distances as the connection details."
        )
    if steel.electrodes:
        notes.append(
            f"Welding: shop welds to AWS D1.1, electrodes {electrodes}. Fillet weld sizes are leg "
            f"lengths. Weld symbols to {WELD_STANDARD}: triangle below the reference line: the "
            "arrow side; above: the other side; both: both sides."
        )
    notes += [
        (
            "Member marks refer to the steel member schedule, connection marks (CN) to the "
            "connection details. Lengths are work point to work point; fabricate to the "
            "fabricator's shop drawings, checked by the engineer."
        ),
        (
            "Steel masses are those of the bill of quantities (10 BOQ); connection plates and "
            "bolts are not included in them."
        ),
        "Surface preparation and paint system: [TO BE SPECIFIED BY THE ENGINEER].",
        "Fire protection and fire resistance rating: [TO BE SPECIFIED BY THE ENGINEER].",
        (
            "Erection: provide temporary bracing until the permanent bracing and slabs are "
            "complete; do not cut or weld members on site without the engineer's approval."
        ),
    ]
    return notes


# ─────────────────────────────────── plans ───────────────────────────────────


def _xy(p: Sequence[float]) -> Point:
    return (float(p[0]), float(p[1]))


def _inclined(m: SteelMember) -> bool:
    return abs(m.start[2] - m.end[2]) > EPS and m.kind != "column"


def plan_level_of(member: SteelMember, levels: Sequence[Level]) -> Level | None:
    """The level whose framing plan shows ``member``: a beam's own level; a brace's the
    lowest level at or above its top end (it is drawn below that level)."""
    top = max(member.start[2], member.end[2])
    for lv in sorted(levels, key=lambda lv: lv.elevation):
        if lv.elevation >= top - EPS:
            return lv
    return None


def _on_plan(member: SteelMember, level: Level, levels: Sequence[Level]) -> bool:
    z = level.elevation
    if member.kind == "column":
        lo, hi = sorted((member.start[2], member.end[2]))
        return lo < z + EPS and hi > z - EPS
    if not _inclined(member):
        return abs(member.start[2] - z) < EPS
    lv = plan_level_of(member, levels)
    return lv is not None and lv.id == level.id


def level_has_steel(steel: SteelSet, level: Level, levels: Sequence[Level]) -> bool:
    return any(_on_plan(m, level, levels) for m in steel.members)


def _section_outline(m: SteelMember, centre: Point) -> list[Point]:
    """A column's section in plan (an I as its outline, others as their box)."""
    h, b = m.depth, m.width
    cx, cy = centre
    if m.shape == "I":
        tf, tw = max(h * 0.06, 6), max(b * 0.04, 5)
        pts = [
            (-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, -h / 2 + tf), (tw / 2, -h / 2 + tf),
            (tw / 2, h / 2 - tf), (b / 2, h / 2 - tf), (b / 2, h / 2), (-b / 2, h / 2),
            (-b / 2, h / 2 - tf), (-tw / 2, h / 2 - tf), (-tw / 2, -h / 2 + tf),
            (-b / 2, -h / 2 + tf),
        ]  # fmt: skip
    else:
        pts = [(-b / 2, -h / 2), (b / 2, -h / 2), (b / 2, h / 2), (-b / 2, h / 2)]
    return [(cx + x, cy + y) for x, y in pts]


def _end_marks(view: View, m: SteelMember, a: Point, b: Point) -> None:
    """The connection mark at both ends of a member line a-b in a view."""
    if not m.connection:
        return
    length = math.dist(a, b) or 1.0
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    inset = min(view.real(4.0), length / 4)
    for (px, py), sign in ((a, 1), (b, -1)):
        at = (px + ux * inset * sign, py + uy * inset * sign)
        tries = [(dx, dy, "MC") for dx, dy in ((0, 5), (0, -5), (6, 4), (-6, 4), (6, -4), (-6, -4))]
        view.label(m.connection, at, tries, leader=True)


def steel_plan(
    building: Building, steel: SteelSet, level: Level, scale: float = 100
) -> ViewSpec | None:
    """The steel framing plan of ``level``: the concrete frame for reference, the steel beams
    as single heavy lines, the steel columns' sections, the braces below the level, each with
    its mark and section, and the connection marks at the members' ends."""
    from saengine.drawings.sheets import plans

    levels = building.levels
    mine = [m for m in steel.members if _on_plan(m, level, levels)]
    if not mine:
        return None
    steel_ids = {m.id for m in steel.members}
    pts = plans._level_points(building, level)
    for m in mine:
        pts += [_xy(m.start), _xy(m.end)]
    bbox = plans._bounds(pts)

    def draw(view: View) -> None:
        z = level.elevation
        plans.grids(view, building, bbox)
        rc = Building(
            grids_x=building.grids_x,
            grids_y=building.grids_y,
            levels=building.levels,
            columns=[c for c in building.columns if c.id not in steel_ids],
            beams=[b for b in building.beams if b.id not in steel_ids],
            walls=building.walls,
        )
        plans._columns(view, rc, z)
        plans._walls(view, rc, z)
        plans._beam_edges(view, rc, z, "S-BEAM")
        lines = []
        for m in mine:
            if m.kind == "column":
                outline = _section_outline(m, _xy(m.start))
                tag(view.polyline(outline, "S-STEEL", close=True), mark=m.mark, section=m.section)
                view.reserve(outline, 0.3)
                continue
            a, b = _xy(m.start), _xy(m.end)
            if math.dist(a, b) < EPS:
                continue
            extra = {"linetype": "DASHED"} if _inclined(m) else {}
            tag(view.polyline([a, b], "S-STEEL", **extra), mark=m.mark, section=m.section)
            lines.append((m, a, b))
        plans._column_marks(view, rc, z)
        for m in mine:
            if m.kind == "column":
                half = max(m.depth, m.width) / 2 / view.scale + 1.2
                view.label(
                    f"{m.mark} {m.section}",
                    _xy(m.start),
                    [(half, half, "BL"), (-half, half, "BR"), (half, -half, "TL"),
                     (-half, -half, "TR")],
                )  # fmt: skip
        for m, a, b in lines:
            what = " BRACE BELOW" if _inclined(m) else ""
            plans._along_label(view, f"{m.mark} {m.section}{what}", a, b, 2.2)
        for m, a, b in lines:
            _end_marks(view, m, a, b)

    return ViewSpec(
        title=f"Steel framing plan - {level.name}",
        scale=scale,
        bbox=bbox,
        draw=draw,
        pad=plans._pad(),
        subtitle=f"SCALE 1:{scale:g}   TOP OF STEEL +{level.elevation / 1000:.3f}",
        key=f"steel-plan:{level.id}",
    )


PLAN_NOTES = [
    "Steel beams: heavy lines at the level; dashed: braces below the level (see the elevations).",
    "Concrete columns, walls and beams are shown for reference: see the framing plans.",
    "CN marks: the connections at the members' ends (connection details).",
    "Member marks refer to the steel member schedule.",
]


# ─────────────────────────────────── elevations ───────────────────────────────────


class ElevationLine:
    """A vertical plane through braced bays: ``origin`` and ``direction`` (unit, plan) of its
    axis u; ``title`` ("Elevation on grid 1")."""

    def __init__(self, title: str, key: str, origin: Point, direction: Point) -> None:
        self.title = title
        self.key = key
        self.origin = origin
        self.direction = direction
        self.members: list[SteelMember] = []

    def u(self, p: Sequence[float]) -> float:
        return (p[0] - self.origin[0]) * self.direction[0] + (p[1] - self.origin[1]) * (
            self.direction[1]
        )

    def off(self, p: Sequence[float]) -> float:
        """Distance of plan point p from the plane."""
        return abs(
            (p[0] - self.origin[0]) * -self.direction[1]
            + (p[1] - self.origin[1]) * self.direction[0]
        )


def elevation_lines(building: Building, steel: SteelSet) -> list[ElevationLine]:
    """The planes of the braced bays: a brace on a grid line is drawn in that grid's
    elevation (with the other braces on it); one off the grids in the plane of its own."""
    lines: dict[str, ElevationLine] = {}
    for m in steel.members:
        if m.kind != "brace" or not _inclined(m):
            continue
        a, b = _xy(m.start), _xy(m.end)
        if math.dist(a, b) < EPS:
            continue
        line = None
        if abs(a[1] - b[1]) < EPS:
            g = next((g for g in building.grids_y if abs(g.position - a[1]) < EPS), None)
            if g is not None:
                key = f"y:{g.label}"
                line = lines.get(key) or ElevationLine(
                    f"Elevation on grid {g.label}", key, (0.0, g.position), (1.0, 0.0)
                )
        elif abs(a[0] - b[0]) < EPS:
            g = next((g for g in building.grids_x if abs(g.position - a[0]) < EPS), None)
            if g is not None:
                key = f"x:{g.label}"
                line = lines.get(key) or ElevationLine(
                    f"Elevation on grid {g.label}", key, (g.position, 0.0), (0.0, 1.0)
                )
        if line is None:
            length = math.dist(a, b)
            d = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
            if d[0] < -1e-9 or (abs(d[0]) < 1e-9 and d[1] < 0):
                d = (-d[0], -d[1])
            key = f"m:{m.mark}"
            line = ElevationLine(f"Elevation on {m.mark}", key, a, d)
        lines[line.key] = line
        line.members.append(m)
    return list(lines.values())


def steel_elevation(building: Building, steel: SteelSet, line: ElevationLine, scale: float = 100):
    """The elevation of a braced plane: grids, levels, the concrete or steel columns and beams
    in the plane, the braces with their marks, sections and end connection marks; bay and
    storey dimensions."""
    levels = sorted(building.levels, key=lambda lv: lv.elevation)
    tol = 50.0
    columns = [c for c in building.columns if line.off((c.x, c.y)) <= max(c.b, c.h) / 2 + tol]
    beams = [b for b in building.beams if line.off(b.start) <= tol and line.off(b.end) <= tol]
    steel_ids = {m.id for m in steel.members}
    grids = []
    for g in building.grids_x:
        if abs(line.direction[0]) > 0.5:
            grids.append((g.label, line.u((g.position, line.origin[1]))))
    for g in building.grids_y:
        if abs(line.direction[1]) > 0.5:
            grids.append((g.label, line.u((line.origin[0], g.position))))
    us = [u for _, u in grids]
    us += [line.u(p) for m in line.members for p in (m.start, m.end)]
    us += [line.u((c.x, c.y)) for c in columns]
    zs = [lv.elevation for lv in levels] + [p[2] for m in line.members for p in (m.start, m.end)]
    u0, u1 = min(us), max(us)
    grids = [(label, u) for label, u in grids if u0 - EPS <= u <= u1 + EPS]
    z0, z1 = min(zs), max(zs)
    bbox = (u0 - 300, z0 - 300, u1 + 300, z1 + 300)

    def draw(view: View) -> None:
        e, r = view.real(6.0), view.real(4.5)
        for label, u in grids:
            view.line((u, z0 - e), (u, z1 + e), "S-GRID")
            c = (u, z1 + e + r)
            view.circle(c, r, "S-GRID-BUBBLE")
            view.reserve([(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)])
            view.text(label, c, TEXT_LARGE, "MC", "S-GRID-BUBBLE")
        for lv in levels:
            view.line((u0 - 300, lv.elevation), (u1 + 300, lv.elevation), "S-GRID")
            tip = (u1 + 300 + view.real(1.5), lv.elevation)
            s = view.real(1.8)
            view.polyline(
                [tip, (tip[0] + s, tip[1] + s), (tip[0] - s, tip[1] + s)], "S-GRID-BUBBLE", True
            )
            view.text(
                f"{lv.name.upper()} {lv.elevation / 1000:+.3f}",
                (tip[0] + s + view.real(1.0), lv.elevation),
                TEXT,
                "ML",
            )
        for c in columns:
            half = c.extent_along(line.direction)
            u = line.u((c.x, c.y))
            layer = "S-STEEL" if c.id in steel_ids else "S-COLS"
            outline = [(u - half, c.bottom), (u + half, c.bottom), (u + half, c.top),
                       (u - half, c.top)]  # fmt: skip
            view.polyline(outline, layer, close=True)
            view.reserve(outline, 0.2)
        for b in beams:
            ua, ub = sorted((line.u(b.start), line.u(b.end)))
            layer = "S-STEEL" if b.id in steel_ids else "S-BEAM-EDGE"
            outline = [(ua, b.elevation - b.depth), (ub, b.elevation - b.depth),
                       (ub, b.elevation), (ua, b.elevation)]  # fmt: skip
            view.polyline(outline, layer, close=True)
            view.reserve(outline, 0.2)
        braces = []
        for m in line.members:
            a = (line.u(m.start), m.start[2])
            b = (line.u(m.end), m.end[2])
            length = math.dist(a, b)
            ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            nx, ny = -uy * m.depth / 2, ux * m.depth / 2
            stop = min(300.0, length / 6)
            p, q = (a[0] + ux * stop, a[1] + uy * stop), (b[0] - ux * stop, b[1] - uy * stop)
            view.line(a, b, "S-STEEL-AXIS")
            for sign in (1, -1):
                entity = view.line(
                    (p[0] + sign * nx, p[1] + sign * ny), (q[0] + sign * nx, q[1] + sign * ny),
                    "S-STEEL",
                )  # fmt: skip
                tag(entity, mark=m.mark, section=m.section)
            for end in (p, q):
                view.line((end[0] + nx, end[1] + ny), (end[0] - nx, end[1] - ny), "S-STEEL")
            braces.append((m, a, b))
        # bay and storey dimensions
        xs = sorted({u for _, u in grids})
        if len(xs) > 1:
            view.chain([(x, z0) for x in xs], -10)
        heights = sorted({lv.elevation for lv in levels})
        if len(heights) > 1:
            view.chain([(u0 - 300, z) for z in heights], 8, angle=90)
        for m, a, b in braces:
            plans_along(view, f"{m.mark} {m.section}", a, b, m.depth / 2 / view.scale + 2.2)
        for m, a, b in braces:
            _end_marks(view, m, a, b)

    return ViewSpec(
        title=line.title,
        scale=scale,
        bbox=bbox,
        draw=draw,
        pad=(22, 22, 40, 16),
        subtitle=f"SCALE 1:{scale:g}",
        key=f"steel-elevation:{line.key}",
    )


def plans_along(view: View, text: str, a: Point, b: Point, offset: float) -> None:
    from saengine.drawings.sheets.plans import _along_label

    _along_label(view, text, a, b, offset)


ELEVATION_NOTES = [
    (
        "Work lines (centre lines) meet at the work points; brace lengths in the member schedule "
        "are work point to work point."
    ),
    "CN marks: the connections at the members' ends (connection details).",
    "Concrete members are shown for reference: see the concrete drawings.",
]


# ─────────────────────────────────── connection details ───────────────────────────────────


def _ceil(value: float, step: float = 5.0) -> float:
    return math.ceil(value / step - 1e-9) * step


class GussetGeometry:
    """A bolted brace end on a gusset welded to a frame member, in the detail's coordinates
    (mm): the weld along y = 0 centred on x = 0, the brace axis through the origin at
    ``angle`` from the horizontal; ``s`` along the axis, ``t`` across it."""

    def __init__(self, c: SteelConnectionDetail) -> None:
        from shapely.geometry import MultiPoint, box

        d = c.data
        self.rows = int(d.get("rows", 3))
        self.lines = int(d.get("lines", 2))
        self.pitch = float(d.get("pitch", 70))
        self.gauge = float(d.get("gauge", 60))
        self.end = float(d.get("endDistance", 35))
        self.edge = float(d.get("edgeDistance", 35))
        self.weld = float(d.get("gussetWeldLength", 300))
        self.tab_weld = float(d.get("tabWeldLength", 150))
        self.angle = min(max(c.angle or 45.0, 25.0), 65.0)
        a = math.radians(self.angle)
        self.u = (math.cos(a), math.sin(a))
        self.v = (-math.sin(a), math.cos(a))
        spread = (self.lines - 1) * self.gauge / 2
        self.half_tab = spread + self.edge
        self.tab_end = _ceil((GUSSET_CLEARANCE + self.half_tab * math.cos(a)) / math.sin(a))
        self.first = self.tab_end + self.end
        self.last = self.first + (self.rows - 1) * self.pitch
        self.free_end = self.last + self.end
        self.brace_end = self.free_end + BRACE_SETBACK
        self.whitmore = c.whitmore or (2 * spread + 2 * (self.rows - 1) * self.pitch * math.tan(
            math.radians(30)))  # fmt: skip
        half = _ceil(max(self.whitmore / 2, self.half_tab) + 15)
        self.half_width = half
        hull = MultiPoint(
            [(-self.weld / 2, 0), (self.weld / 2, 0), self.at(self.tab_end, half),
             self.at(self.tab_end, -half), self.at(self.free_end, half),
             self.at(self.free_end, -half)]
        ).convex_hull  # fmt: skip
        hull = hull.intersection(box(-1e6, 0, 1e6, 1e6))
        self.gusset = [(float(x), float(y)) for x, y in list(hull.exterior.coords)[:-1]]
        xs = [x for x, _ in self.gusset]
        self.frame = (min(*xs, -self.weld / 2) - 60, max(*xs, self.weld / 2) + 60)
        """The frame member drawn under the gusset: from x to x."""
        self.far = self.brace_end + self.tab_weld + 100
        """Where the brace drawn is broken off (along the axis)."""
        self.bolts = [
            (self.first + i * self.pitch, -spread + j * self.gauge)
            for i in range(self.rows)
            for j in range(self.lines)
        ]

    def at(self, s: float, t: float) -> Point:
        return (s * self.u[0] + t * self.v[0], s * self.u[1] + t * self.v[1])


def _aligned_dim(view: View, p1: Point, p2: Point, offset: float, text: str | None = None):
    """A dimension along p1-p2 (real), its line ``offset`` paper mm to the left of p1→p2."""
    sheet = view.sheet
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length < EPS:
        return None
    nx, ny = -dy / length, dx / length
    dim = sheet.msp.add_aligned_dim(
        p1=view.m(*p1),
        p2=view.m(*p2),
        distance=offset * sheet.scale,
        text=text if text is not None else "<>",
        dimstyle=sheet.dimstyle_for(view.scale),
        dxfattribs={"layer": "S-DIMS"},
    )
    dim.render()
    angle = math.degrees(math.atan2(dy, dx))
    if angle > 90 + 1e-6:
        angle -= 180
    elif angle <= -90 + 1e-6:
        angle += 180
    label = (text or "<>").replace("<>", f"{length:.0f}")
    a, b = view.p(*p1), view.p(*p2)
    mx, my = (a[0] + b[0]) / 2 + nx * offset, (a[1] + b[1]) / 2 + ny * offset
    side = 1 if offset >= 0 else -1
    tx, ty = mx + nx * side * (1.0 + TEXT / 2), my + ny * side * (1.0 + TEXT / 2)
    sheet.labels.take(text_rect(tx, ty, label, TEXT, "MC", angle))
    pa = (a[0] + nx * offset, a[1] + ny * offset)
    pb = (b[0] + nx * offset, b[1] + ny * offset)
    sheet.labels.segment(pa, pb)
    for start, end in ((a, pa), (b, pb)):
        if math.dist(start, end) > 1.6:
            sheet.labels.segment(start, end)
    return dim


def _chain_aligned(view: View, points: Sequence[Point], offset: float) -> None:
    for a, b in itertools.pairwise(points):
        _aligned_dim(view, a, b, offset)


def weld_symbol(
    view: View,
    at: Point,
    size: float,
    length: float | None,
    both: bool = True,
    tail: str = "",
    tries: Sequence[tuple[float, float]] | None = None,
) -> tuple[float, float] | None:
    """A fillet weld symbol (AWS A2.4) whose arrow points at the real point ``at``: the
    reference line, the triangle (below: arrow side; above too when ``both``), the leg size
    left of it, the length right of it and ``tail`` (a note). Placed at the first of the paper
    offsets ``tries`` (of the reference line's arrow end) where it is clear; returns it."""
    sheet = view.sheet
    labels = sheet.labels
    ax, ay = view.p(*at)
    ref = 18.0
    tri = 2.5
    size_text = f"{size:g}"
    length_text = f"{length:.0f}" if length else ""
    tail_w = text_width(tail, TEXT) + 4 if tail else 0.0
    candidates = [*(tries or []), *(
        (sx * dx, sy * dy) for dx, dy in ((6, 8), (10, 14), (16, 6), (14, 22), (24, 12), (22, 30))
        for sx in (1, -1) for sy in (1, -1)
    )]  # fmt: skip

    def geometry(dx: float, dy: float):
        left = dx < 0  # the reference line runs left from the arrow's end
        x0 = ax + dx
        y0 = ay + dy
        xs = (x0 - ref, x0) if left else (x0, x0 + ref)
        tx = xs[0] + 6.0
        box = (
            xs[0] - (tail_w if left else 0) - 0.5,
            y0 - (TEXT + 1.0),
            xs[1] + (0 if left else tail_w) + 0.5,
            y0 + (TEXT + 1.0),
        )
        return xs, y0, tx, box, left

    chosen = None
    for dx, dy in candidates:
        xs, y0, tx, box, left = geometry(dx, dy)
        if not labels.free(box, soft=True):
            continue
        end = (xs[1] if left else xs[0], y0)
        if not labels.leader_free((ax, ay), end, box):
            continue
        chosen = (dx, dy)
        break
    if chosen is None:
        chosen = candidates[0]
        labels.forced.append(f"weld {size_text}")
    xs, y0, tx, box, left = geometry(*chosen)
    end = (xs[1] if left else xs[0], y0)

    def line(a, b) -> None:
        sheet.p_line(a, b, "S-WELD")

    line((ax, ay), end)
    labels.segment((ax, ay), end)
    # the arrowhead
    ang = math.atan2(end[1] - ay, end[0] - ax)
    for side in (1, -1):
        a = ang + side * math.radians(15)
        line((ax, ay), (ax + 2.2 * math.cos(a), ay + 2.2 * math.sin(a)))
    line((xs[0], y0), (xs[1], y0))
    # the triangles: perpendicular leg on the left
    for sign in (-1, 1) if both else (-1,):
        line((tx, y0), (tx, y0 + sign * tri))
        line((tx, y0 + sign * tri), (tx + tri, y0))
        # the texts stand on the line (other side) or hang from it (arrow side)
        v = "B" if sign > 0 else "T"
        ty = y0 + sign * 0.4
        sheet.p_text(size_text, tx - 0.6, ty, TEXT, v + "R", "S-WELD", reserve=False)
        if length_text:
            sheet.p_text(length_text, tx + tri + 0.6, ty, TEXT, v + "L", "S-WELD", reserve=False)
    if tail:
        tail_x = xs[0] if left else xs[1]
        out = -1 if left else 1
        for sign in (1, -1):
            line((tail_x, y0), (tail_x + out * 2.0, y0 + sign * 2.0))
        sheet.p_text(
            tail, tail_x + out * 2.8, y0, TEXT, "MR" if left else "ML", "S-WELD", reserve=False
        )
    labels.take(box)
    return chosen


def _bolt(view: View, centre: Point, hole: float, **values: Any) -> None:
    r = hole / 2
    entity = view.circle(centre, r, "S-BOLT")
    tag(entity, **values)
    k = r * 1.5
    view.line((centre[0] - k, centre[1]), (centre[0] + k, centre[1]), "S-BOLT")
    view.line((centre[0], centre[1] - k), (centre[0], centre[1] + k), "S-BOLT")
    view.reserve([(centre[0] - k, centre[1] - k), (centre[0] + k, centre[1] + k)], 0.3)


def _break(view: View, a: Point, b: Point, layer: str) -> None:
    """A break line from a to b (a zig-zag in its middle)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    z = view.real(1.5)

    def at(f: float, n: float = 0.0) -> Point:
        return (a[0] + dx * f + nx * n, a[1] + dy * f + ny * n)

    view.polyline(
        [at(-0.08), at(0.42), at(0.47, z), at(0.53, -z), at(0.58), at(1.08)], layer, lineweight=18
    )


def _data_lines(c: SteelConnectionDetail) -> list[str]:
    from saengine.design.steel_connections import hole_diameter

    d = c.data
    bolt = float(d.get("boltDiameter") or 20)
    lines_n = int(d.get("lines", 2 if c.kind == "endPlate" else 1))
    rows = int(d.get("rows", 1))
    out = [
        f"{TYPE_NAMES.get(c.kind, c.kind).upper()} AT BOTH ENDS OF {', '.join(c.members)}",
        f"MEMBER {c.section}",
        (
            f"BOLTS {rows} x {lines_n} = {c.bolts} M{bolt:g} {d.get('boltGrade')} PER END,"
            f" HOLES Ø{hole_diameter(bolt):g}"
        ),
        f"PITCH {float(d.get('pitch', 0)):g}"
        + (f", GAUGE {float(d.get('gauge')):g}" if lines_n > 1 and d.get("gauge") else "")
        + f", END {float(d.get('endDistance', 0)):g}, EDGE {float(d.get('edgeDistance', 0)):g}",
    ]
    grade = f" {c.plate_grade}" if c.plate_grade else ""
    tp = float(d.get("plateThickness", 10))
    if c.kind == "gusset":
        tab = float(d.get("tabThickness") or tp)
        out.append(f"GUSSET PL {tp:g}, TAB PL {tab:g}{grade}")
    else:
        out.append(f"{TYPE_NAMES[c.kind].upper()} PL {tp:g}{grade}")
    w = float(d.get("weldSize", 6))
    fexx = float(d.get("electrode", 480))
    out.append(
        f"FILLET WELDS {w:g}, FEXX {fexx:g} MPa" + (" (E70XX)" if abs(fexx - 480) < 1 else "")
    )
    if c.kind == "gusset":
        out.append(
            f"GUSSET WELD 2 x {float(d.get('gussetWeldLength', 300)):g},"
            f" TAB WELDS {int(d.get('tabWelds', 4))} x {float(d.get('tabWeldLength', 150)):g}"
        )
        if c.whitmore:
            out.append(f"WHITMORE WIDTH Lw {c.whitmore:.0f} (30° SPREAD)")
        out.append(f"BRACE SLOPE {c.angle:.1f}°")
    if c.utilisation is not None:
        out.append(f"DESIGN CHECK: UTILISATION {c.utilisation:.2f}, {'OK' if c.ok else 'FAILS'}")
    else:
        out.append("DESIGN CHECK: SEE THE DESIGN REPORT")
    return out


def connection_detail(
    c: SteelConnectionDetail,
    scale: float = CONNECTION_SCALE,
    max_size: tuple[float, float] | None = None,
) -> ViewSpec:
    """The detail of a designed connection at ``1:scale`` with its data beside it, or under it
    when the two side by side are wider than ``max_size`` (paper mm); at 1:10 when the detail
    alone is too large at ``1:scale``."""
    if c.kind == "gusset":
        g = GussetGeometry(c)
        pts = [*g.gusset, g.at(g.far, c.depth / 2), g.at(g.far, -c.depth / 2),
               (g.frame[0], -40), (g.frame[1], -40)]  # fmt: skip
        drawer = _gusset
    elif c.kind == "finPlate":
        a = float(c.data.get("boltLineOffset", 60))
        edge = float(c.data.get("edgeDistance", 35))
        hp = 2 * float(c.data.get("endDistance", 35)) + (int(c.data.get("rows", 3)) - 1) * float(
            c.data.get("pitch", 70)
        )
        pts = [(-40, -c.depth / 2 - 150), (a + edge + 300, c.depth / 2 + 150), (0, hp / 2)]
        g = None
        drawer = _fin_plate
    else:
        gauge = float(c.data.get("gauge", 90))
        edge = float(c.data.get("edgeDistance", 35))
        bp = gauge + 2 * edge
        pts = [(-max(bp, c.width) / 2, -c.depth / 2), (max(bp, c.width) / 2, c.depth / 2)]
        g = None
        drawer = _end_plate
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    real = (min(xs), min(ys), max(xs), max(ys))
    lines = _data_lines(c)
    data_w = max(text_width(t, TEXT) for t in lines) + 4
    data_h = len(lines) * TEXT * 1.6 + 4
    limit = (max_size[0] - 8, max_size[1] - 30) if max_size else (math.inf, math.inf)
    own = scale
    draw_w = (real[2] - real[0]) / scale + 44
    draw_h = (real[3] - real[1]) / scale + 40
    if draw_w > limit[0] or draw_h + data_h > limit[1] and draw_w + data_w > limit[0]:
        scale = max(scale, 10.0)
        draw_w = (real[2] - real[0]) / scale + 44
        draw_h = (real[3] - real[1]) / scale + 40
    below = draw_w + data_w > limit[0]
    width = max(draw_w, data_w) if below else draw_w + data_w
    height = draw_h + data_h if below else max(draw_h, data_h)

    def draw(view: View) -> None:
        # the data first, so that the detail's labels keep clear of it
        x, y = (2, data_h - 2) if below else (draw_w + 2, height - 2)
        for text in lines:
            view.text(text, (x, y), TEXT, "TL")
            y -= TEXT * 1.6
        bottom = data_h if below else (height - draw_h) / 2
        inset = view.inset(22, bottom + 20, scale, origin=(real[0], real[1]))
        drawer(inset, c, g)

    return ViewSpec(
        f"Connection {c.mark}",
        1,
        (0, 0, width, height),
        draw,
        pad=(2, 2, 2, 2),
        subtitle=f"{TYPE_NAMES.get(c.kind, c.kind).upper()}   SCALE 1:{scale:g}",
        key=f"connection:{c.mark}",
        group="refit" if scale != own else "",
    )


def _gusset(view: View, c: SteelConnectionDetail, g: GussetGeometry) -> None:
    from saengine.design.steel_connections import hole_diameter

    d = c.data
    bolt = float(d.get("boltDiameter", 20))
    hole = hole_diameter(bolt)
    w = float(d.get("weldSize", 6))
    tp = float(d.get("plateThickness", 10))
    tab_t = float(d.get("tabThickness") or tp)
    # the frame member the gusset is welded to
    x0, x1 = g.frame
    view.line((x0, 0), (x1, 0), "S-STEEL")
    view.line((x0, -25), (x1, -25), "S-STEEL")
    _break(view, (x0, 25), (x0, -50), "S-STEEL")
    _break(view, (x1, 25), (x1, -50), "S-STEEL")
    view.reserve([(x0, -25), (x1, 0)])
    # the gusset, the tab and the brace
    tag(view.polyline(g.gusset, "S-STEEL-PLATE", close=True), part="gusset", thickness=f"{tp:g}")
    t = g.half_tab
    tab = [g.at(g.tab_end, -t), g.at(g.brace_end, -t), g.at(g.brace_end, t), g.at(g.tab_end, t)]
    tag(view.polyline(tab, "S-STEEL-PLATE", close=True), part="tab", thickness=f"{tab_t:g}")
    inside = [g.at(g.brace_end, -t), g.at(g.brace_end + g.tab_weld, -t),
              g.at(g.brace_end + g.tab_weld, t), g.at(g.brace_end, t)]  # fmt: skip
    view.polyline(inside, "S-STEEL-PLATE", linetype="HIDDEN")
    far = g.far
    h = c.depth / 2
    for sign in (1, -1):
        tag(
            view.line(g.at(g.brace_end, sign * h), g.at(far, sign * h), "S-STEEL"),
            mark=", ".join(c.members),
            section=c.section,
        )
    view.line(g.at(g.brace_end, h), g.at(g.brace_end, -h), "S-STEEL")
    _break(view, g.at(far, h + 30), g.at(far, -h - 30), "S-STEEL")
    view.line(g.at(-40, 0), g.at(far + 60, 0), "S-STEEL-AXIS")
    # the bolts and the Whitmore section
    for i, (s, tt) in enumerate(g.bolts):
        _bolt(view, g.at(s, tt), hole, row=i // g.lines + 1, line=i % g.lines + 1, dia=f"{bolt:g}")
    spread = (g.lines - 1) * g.gauge / 2
    lw = g.whitmore / 2
    # spread at 30° from the row nearest the brace to the row deepest in the gusset
    for sign in (1, -1):
        view.line(g.at(g.last, sign * spread), g.at(g.first, sign * lw), "S-STEEL-PLATE",
                  linetype="DASHED")  # fmt: skip
    tag(
        view.line(g.at(g.first, -lw), g.at(g.first, lw), "S-STEEL-PLATE", linetype="DASHED"),
        part="whitmore",
        width=f"{g.whitmore:.0f}",
    )
    # dimensions: along the brace (tab end, pitches, gusset end), across (edges, gauges),
    # the gusset weld
    along = [g.tab_end, *[g.first + i * g.pitch for i in range(g.rows)], g.free_end]
    offset = (g.half_width - spread) / view.scale + 6
    _chain_aligned(view, [g.at(s, spread) for s in along], offset)
    across = [-t, *[-spread + j * g.gauge for j in range(g.lines)], t]
    _chain_aligned(view, [g.at(g.tab_end, v) for v in across], 4.0)
    view.dim((-g.weld / 2, -25), (g.weld / 2, -25), -6)
    # weld symbols, then the labels
    weld_symbol(view, (g.weld / 4, 0), w, g.weld, True, "E70XX" if abs(
        float(d.get("electrode", 480)) - 480) < 1 else "", tries=[(8, -12), (-8, -12), (12, -16),
                                                                   (-12, -16), (6, 10), (-6, 10)])  # fmt: skip
    weld_symbol(
        view,
        g.at(g.brace_end + g.tab_weld / 2, t),
        w,
        g.tab_weld,
        True,
        f"{int(d.get('tabWelds', 4))} WELDS",
    )
    view.label(
        f"WHITMORE SECTION Lw = {g.whitmore:.0f}",
        g.at(g.first, -lw * 0.6),
        [(24, -4, "ML"), (30, 4, "ML"), (24, -10, "TL")],
        leader=True,
    )
    view.label(
        f"GUSSET PL {tp:g}" + (f" {c.plate_grade}" if c.plate_grade else ""),
        g.at(g.tab_end * 0.5, g.half_tab * 0.6),
        [(-14, 14, "BR"), (-20, 8, "BR"), (-14, 20, "BR")],
        leader=True,
    )
    view.label(
        f"TAB PL {tab_t:g}",
        g.at(g.free_end + BRACE_SETBACK / 2, 0),
        [(6, -10, "TL"), (-6, -10, "TR"), (6, 10, "BL")],
        leader=True,
    )
    view.label(
        f"{g.rows * g.lines} M{bolt:g} {d.get('boltGrade')} BOLTS",
        g.at(*g.bolts[-1]),
        [(10, 8, "BL"), (-10, 8, "BR"), (10, -8, "TL"), (-10, -8, "TR")],
        leader=True,
    )
    view.label(
        f"{', '.join(c.members)} {c.section}",
        g.at(far - 60, -h),
        [(4, -6, "TL"), (-4, -6, "TR"), (4, 6, "BL")],
        leader=True,
    )
    view.label("FRAME MEMBER", (x0 + 40, -12), [(0, -8, "TC"), (-6, -8, "TR")], leader=True)


def _fin_plate(view: View, c: SteelConnectionDetail, _g: Any) -> None:
    from saengine.design.steel_connections import hole_diameter

    d = c.data
    rows = int(d.get("rows", 3))
    pitch, end = float(d.get("pitch", 70)), float(d.get("endDistance", 35))
    edge, a = float(d.get("edgeDistance", 35)), float(d.get("boltLineOffset", 60))
    tp, w = float(d.get("plateThickness", 10)), float(d.get("weldSize", 6))
    bolt = float(d.get("boltDiameter", 20))
    hp = 2 * end + (rows - 1) * pitch
    h = c.depth / 2
    top, bottom = h + 150, -h - 150
    # the support face, the beam (flanges, end), the plate
    view.line((0, bottom), (0, top), "S-STEEL")
    view.line((-30, bottom), (-30, top), "S-STEEL")
    _break(view, (-60, top), (30, top), "S-STEEL")
    _break(view, (-60, bottom), (30, bottom), "S-STEEL")
    gap = 12.0
    far = a + edge + 300
    for y in (h, h - c.flange, -h + c.flange, -h):
        view.line((gap, y), (far, y), "S-STEEL")
    view.line((gap, h), (gap, -h), "S-STEEL")
    _break(view, (far, h + 30), (far, -h - 30), "S-STEEL")
    plate = [(0, -hp / 2), (a + edge, -hp / 2), (a + edge, hp / 2), (0, hp / 2)]
    tag(view.polyline(plate, "S-STEEL-PLATE", close=True), part="fin plate", thickness=f"{tp:g}")
    hole = hole_diameter(bolt)
    for i in range(rows):
        _bolt(view, (a, -hp / 2 + end + i * pitch), hole, row=i + 1, line=1, dia=f"{bolt:g}")
    ys = [-hp / 2, *[-hp / 2 + end + i * pitch for i in range(rows)], hp / 2]
    view.chain([(a + edge, y) for y in ys], -8, angle=90)
    view.chain([(0, -hp / 2), (a, -hp / 2), (a + edge, -hp / 2)], -6)
    weld_symbol(view, (0, hp / 4), w, hp, True, tries=[(-8, 10), (-8, -10), (-12, 16)])
    view.label(f"FIN PL {tp:g}" + (f" {c.plate_grade}" if c.plate_grade else ""),
               ((a + edge) / 2, hp / 2), [(0, 8, "BC"), (6, 8, "BL")], leader=True)  # fmt: skip
    view.label(f"{rows} M{bolt:g} {d.get('boltGrade')} BOLTS", (a, -hp / 2 + end),
               [(14, -10, "TL"), (14, 10, "BL")], leader=True)  # fmt: skip
    view.label(f"{', '.join(c.members)} {c.section}", (far - 100, h),
               [(0, 6, "BC"), (6, 6, "BL")], leader=True)  # fmt: skip
    view.label("SUPPORT", (-15, top - 80), [(-6, 0, "MR"), (-6, 6, "BR")], leader=True)


def _end_plate(view: View, c: SteelConnectionDetail, _g: Any) -> None:
    from saengine.design.steel_connections import hole_diameter

    d = c.data
    rows = int(d.get("rows", 3))
    pitch, end = float(d.get("pitch", 70)), float(d.get("endDistance", 35))
    edge, gauge = float(d.get("edgeDistance", 35)), float(d.get("gauge", 90))
    tp, w = float(d.get("plateThickness", 10)), float(d.get("weldSize", 6))
    bolt = float(d.get("boltDiameter", 20))
    hp = 2 * end + (rows - 1) * pitch
    bp = gauge + 2 * edge
    h, b = c.depth / 2, c.width / 2
    # the beam's section behind the plate (hidden), the plate, the bolts
    tw, tf = max(c.web, 4.0), max(c.flange, 6.0)
    outline = [(-b, -h), (b, -h), (b, -h + tf), (tw / 2, -h + tf), (tw / 2, h - tf), (b, h - tf),
               (b, h), (-b, h), (-b, h - tf), (-tw / 2, h - tf), (-tw / 2, -h + tf),
               (-b, -h + tf)]  # fmt: skip
    view.polyline(outline, "S-STEEL", close=True, linetype="HIDDEN")
    plate = [(-bp / 2, -hp / 2), (bp / 2, -hp / 2), (bp / 2, hp / 2), (-bp / 2, hp / 2)]
    tag(view.polyline(plate, "S-STEEL-PLATE", close=True), part="end plate", thickness=f"{tp:g}")
    hole = hole_diameter(bolt)
    for i in range(rows):
        for j, x in enumerate((-gauge / 2, gauge / 2)):
            y = -hp / 2 + end + i * pitch
            _bolt(view, (x, y), hole, row=i + 1, line=j + 1, dia=f"{bolt:g}")
    ys = [-hp / 2, *[-hp / 2 + end + i * pitch for i in range(rows)], hp / 2]
    view.chain([(bp / 2, y) for y in ys], -(b - bp / 2) / view.scale - 8, angle=90)
    view.chain([(x, -h) for x in (-bp / 2, -gauge / 2, gauge / 2, bp / 2)], -8)
    weld_symbol(view, (tw / 2, hp / 4), w, hp, True, tries=[(14, 12), (14, -12), (18, 18)])
    view.label(f"END PL {tp:g}" + (f" {c.plate_grade}" if c.plate_grade else ""),
               (-bp / 2, hp / 2), [(-6, 8, "BR"), (-6, -8, "TR")], leader=True)  # fmt: skip
    view.label(f"{2 * rows} M{bolt:g} {d.get('boltGrade')} BOLTS", (-gauge / 2, -hp / 2 + end),
               [(-14, -10, "TR"), (-14, 10, "BR")], leader=True)  # fmt: skip


CONNECTION_NOTES = [
    (
        f"Weld symbols to {WELD_STANDARD}: below the reference line the arrow side, above the "
        "other side; fillet leg size left of the triangle, length right of it."
    ),
    "Bolts are drawn as their holes with a cross; dimensions in mm to bolt centres.",
    (
        "Brace details: the work line through the gusset weld's centre; the tab clearances are "
        "drafting values to be confirmed on the shop drawings."
    ),
    "Connections designed to BNBC 2020 Part 6 Sec 10.10 (design report).",
]
