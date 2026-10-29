"""The drawing set of a project: its plan geometry from the building model (06 BIM), the floor
plan's grids (05 Floor Plan), the object types (04 Objects) and the foundations (09
Substructure); its detailed members from the detailing model
(:func:`saengine.drawings.detailing.detailing_model`); its bar bending schedule from
:mod:`saengine.drawings.bbs`; its title block from the project settings (02 Project Settings)
and the drawing settings.

How it is called::

    data = drawing_set(project_root)                       # reads the files, runs the detailing
    data = drawing_set(project_root, detailing=model,      # or with what the caller has
                       schedule=sheet_table(bar_schedule(model)), title={"firm": ...})

Nothing is written; problems (a missing file, a member the sheets cannot draw) are in
``data.problems``.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from saengine.drawings.sheets.layout import TitleInfo
from saengine.drawings.sheets.model import (
    BeamBar,
    BeamDetail,
    Building,
    ColumnLine,
    ColumnSection,
    DrawingSet,
    FootingDetail,
    Grid,
    Level,
    LinkZone,
    LintelDetail,
    Mesh,
    PileGridPlan,
    PlanBeam,
    PlanColumn,
    PlanFooting,
    PlanPile,
    PlanSlab,
    PlanStair,
    PlanWall,
    SlabDetail,
    StairDetail,
    Support,
    Table,
    TopBar,
    WallDetail,
)

FILES = {
    "settings": "02 Project Settings/project-settings.json",
    "materials": "03 Materials/materials.json",
    "objects": "04 Objects/objects.json",
    "floorPlan": "05 Floor Plan/floor-plan.json",
    "bim": "06 BIM/bim.json",
    "substructure": "09 Substructure/substructure.json",
}


def _read(root: Path, relative: str) -> str | None:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError:
        return None


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ─────────────────────────────────── plan geometry ───────────────────────────────────


def _rect(cx: float, cy: float, lx: float, ly: float, rotation: float = 0) -> list[tuple]:
    c, s = math.cos(math.radians(rotation)), math.sin(math.radians(rotation))
    pts = []
    for u, v in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        du, dv = u * lx / 2, v * ly / 2
        pts.append((cx + du * c - dv * s, cy + du * s + dv * c))
    return pts


def building_of(bim: Any, objects: Any, plan: Any = None, substructure: Any = None) -> Building:
    """The plan geometry of the building model ``bim`` with the types of ``objects`` (library
    models), the grids of the floor plan ``plan`` and the foundations of ``substructure``."""
    types = {o.id: o for o in objects.objects}
    b = Building()
    if plan is not None:
        b.grids_x = [Grid(g.label, g.position) for g in plan.grids.x]
        b.grids_y = [Grid(g.label, g.position) for g in plan.grids.y]
    b.levels = [Level(s.id, s.name, s.elevation) for s in bim.stories]
    holes: dict[str, list[list[tuple]]] = {}
    for o in bim.additions.slabOpenings:
        holes.setdefault(o.host, []).append(_rect(o.x, o.y, o.xDim, o.yDim, o.rotation))
    for e in bim.elements:
        t = types.get(e.type)
        if e.kind == "column" and t is not None and getattr(t, "profile", None) is not None:
            p = t.profile
            if p.shape == "circle":
                b.columns.append(
                    PlanColumn(
                        e.id,
                        e.id,
                        *e.position,
                        e.bottom,
                        e.top,
                        2 * p.radius,
                        2 * p.radius,
                        e.rotation,
                        True,
                    )
                )
            else:
                bx = getattr(p, "xDim", None) or getattr(p, "overallWidth", 300)
                hy = getattr(p, "yDim", None) or getattr(p, "overallDepth", 300)
                b.columns.append(
                    PlanColumn(e.id, e.id, *e.position, e.bottom, e.top, bx, hy, e.rotation)
                )
        elif e.kind == "beam" and t is not None and getattr(t, "profile", None) is not None:
            p = t.profile
            w = getattr(p, "xDim", None) or getattr(p, "overallWidth", 300)
            d = getattr(p, "yDim", None) or getattr(p, "overallDepth", 500)
            b.beams.append(PlanBeam(e.id, e.id, tuple(e.start), tuple(e.end), w, d, e.elevation))
        elif e.kind == "wall" and t is not None:
            b.walls.append(
                PlanWall(
                    e.id,
                    e.id,
                    tuple(e.start),
                    tuple(e.end),
                    getattr(t, "thickness", 200),
                    e.bottom,
                    e.top,
                )
            )
        elif e.kind == "slab" and t is not None:
            b.slabs.append(
                PlanSlab(
                    e.id,
                    e.id,
                    [tuple(p) for p in e.boundary],
                    getattr(t, "thickness", 150),
                    e.elevation,
                    holes.get(e.id, []),
                )
            )
    level = {s.id: s.elevation for s in bim.stories}
    for st in bim.additions.stairs:
        t = types.get(st.type)
        if t is None or st.base not in level or st.top not in level:
            continue
        b.stairs.append(_plan_stair(st, t, level[st.base], level[st.top]))
    if substructure is not None:
        for f in substructure.foundations:
            if f.outline:
                outline = [tuple(p) for p in f.outline]
            elif f.center and f.length and f.width:
                outline = _rect(f.center[0], f.center[1], f.length, f.width, f.rotation)
            else:
                continue
            pile_type = substructure.cap_pile_type(f) if f.piles else None
            dia = pile_type.diameter if pile_type else 0
            piles = [(tuple(p.position), dia) for p in substructure.cap_piles(f)]
            top = (f.foundingLevel or 0) + (f.thickness or 0)
            b.footings.append(PlanFooting(f.id, f.id, outline, top, piles))
        capped = substructure.capped()
        diameters = {p.id: p.diameter for p in substructure.pileTypes}
        b.piles = [
            PlanPile(p.id, tuple(p.position), diameters.get(p.type, 0.0), capped.get(p.id, ""))
            for p in substructure.piles
        ]
        g = substructure.pileGrid
        if g is not None and (g.x or g.y):
            b.pile_grid = PileGridPlan(
                tuple(g.origin),
                g.rotation,
                [Grid(line.label, line.position) for line in g.x],
                [Grid(line.label, line.position) for line in g.y],
            )
    else:
        for e in bim.elements:
            t = types.get(e.type)
            if e.kind == "footing" and t is not None:
                outline = _rect(*e.position, t.length, t.width, e.rotation)
                b.footings.append(PlanFooting(e.id, e.id, outline, e.elevation))
    return b


def pile_cap_schedule(substructure: Any) -> Table | None:
    """The pile cap schedule: per cap its size, piles (count and marks), pile type, the columns
    it carries and its bottom bars; None without pile caps."""
    caps = [f for f in substructure.foundations if f.type == "pileCap"]
    if not caps:
        return None

    def mm(value: Any) -> str:
        return f"{float(value):.0f}" if value else "-"

    def mesh(m: Any) -> str:
        return f"Ø{m.dia:g}@{m.spacing:g}" if m is not None else "-"

    columns = [
        {"key": "mark", "title": "Cap", "width": 6},
        {"key": "size", "title": "L x B x H\n(mm)", "width": 16},
        {"key": "count", "title": "Piles", "width": 5, "align": "right"},
        {"key": "piles", "title": "Pile marks", "width": 18},
        {"key": "type", "title": "Pile type\nØ x L (mm)", "width": 16},
        {"key": "columns", "title": "Columns", "width": 12},
        {"key": "bx", "title": "Bottom\nbars X", "width": 9},
        {"key": "by", "title": "Bottom\nbars Y", "width": 9},
    ]
    rows = []
    for f in caps:
        pile = substructure.cap_pile_type(f)
        bars = f.reinforcement
        rows.append(
            [
                f.id,
                f"{mm(f.length)} x {mm(f.width)} x {mm(f.thickness)}",
                str(len(f.piles or [])),
                ", ".join(f.piles or []),
                f"{pile.id}: {pile.diameter:.0f} x {pile.length:.0f}" if pile else "-",
                ", ".join(f.columns) or "-",
                mesh(bars.bottomX if bars else None),
                mesh(bars.bottomY if bars else None),
            ]
        )
    free = [p.id for p in substructure.piles if p.id not in substructure.capped()]
    notes = [f"Piles under no cap: {', '.join(free)}."] if free else []
    return Table("Pile cap schedule", columns, rows, notes=notes)


def _flights(n: int, arrangement: str) -> list[int]:
    return [n] if arrangement != "dogLegged" or n < 2 else [math.ceil(n / 2), n // 2]


def _plan_stair(st: Any, t: Any, base: float, top: float) -> PlanStair:
    """A stair in plan: its flights from the foot (centre of the first riser's width) along
    its direction; a dog-legged stair's second flight returns beside the first (on its left)."""
    n = max(1, round((top - base) / t.riser))
    counts = _flights(n, t.arrangement)
    w, T = t.flightWidth, t.tread
    land = t.landingLength or w
    a = math.radians(st.direction)
    u, v = (math.cos(a), math.sin(a)), (-math.sin(a), math.cos(a))

    def at(s: float, r: float) -> tuple[float, float]:
        return (st.x + u[0] * s + v[0] * r, st.y + u[1] * s + v[1] * r)

    flights, treads, landings = [], [], []
    g1 = (counts[0] - 1) * T
    flights.append([at(0, -w / 2), at(g1, -w / 2), at(g1, w / 2), at(0, w / 2)])
    for i in range(1, counts[0] - 1):
        treads.append((at(i * T, -w / 2), at(i * T, w / 2)))
    arrow = [at(0, 0), at(g1, 0)]
    if len(counts) == 2:
        well = t.wellWidth
        g2 = (counts[1] - 1) * T
        r0, r1 = w / 2 + well, w / 2 + well + w
        flights.append([at(g1 - g2, r0), at(g1, r0), at(g1, r1), at(g1 - g2, r1)])
        for i in range(1, counts[1] - 1):
            treads.append((at(g1 - i * T, r0), at(g1 - i * T, r1)))
        landings.append([at(g1, -w / 2), at(g1 + land, -w / 2), at(g1 + land, r1), at(g1, r1)])
        mid = (r0 + r1) / 2
        arrow = [at(0, 0), at(g1 + land / 2, 0), at(g1 + land / 2, mid), at(g1 - g2, mid)]
    return PlanStair(st.id, st.id, base, top, flights, landings, treads, arrow)


# ─────────────────────────────────── detailed members ───────────────────────────────────


def _legs(bar: dict[str, Any]) -> tuple[float, float]:
    """The bent legs at the start and end of a bar (from its hooks and outside dimensions)."""
    hooks = list(_get(_get(bar, "at", {}), "hooks") or [None, None]) + [None, None]
    seg = [
        float(_get(s, "length", s)) if isinstance(s, dict) else float(s)
        for s in (_get(bar, "segments") or [])
    ]
    if len(seg) < 2:
        return 0.0, 0.0
    if len(seg) == 2:  # an L: A the run, B the leg at whichever end is hooked
        return (seg[1] if hooks[0] else 0.0), (seg[1] if hooks[1] and not hooks[0] else 0.0)
    return (seg[0] if hooks[0] else 0.0), (seg[-1] if hooks[1] else 0.0)


def _type_of(objects: Any, type_id: str) -> Any:
    return next((o for o in objects.objects if o.id == type_id), None)


def _bar_marks(element: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(b.get("mark")): b for b in element.get("bars", [])}


def beam_detail(e: dict[str, Any], level_name: str, slab: float = 0.0, legs: int = 2) -> BeamDetail:
    """A beam line of the detailing model as a :class:`BeamDetail`."""
    at = e.get("at", {})
    bars = []
    for b in e.get("bars", []):
        face = _get(b.get("at", {}), "face") or b.get("role")
        if face not in ("top", "bottom") or b.get("at", {}).get("from") is None:
            continue
        ls, le = _legs(b)
        note = f"LAP {b['lap']:g}" if b.get("lap") else ""
        bars.append(
            BeamBar(
                str(b["mark"]),
                float(b["dia"]),
                int(b["count"]),
                float(b["at"]["from"]),
                float(b["at"]["to"]),
                face,
                int(b["at"].get("layer") or 1),
                ls,
                le,
                note,
                float(b["length"]) if b.get("length") is not None else None,
            )
        )
    marks = _bar_marks(e)
    links = []
    for row in e.get("transverse", []):
        bar = marks.get(str(row.get("mark")), {})
        links.append(
            LinkZone(
                float(row["from"]),
                float(row["to"]),
                float(bar.get("dia", 10)),
                float(row["spacing"]),
                legs,
                str(row.get("mark", "")),
            )
        )
    supports = [
        Support(
            float(s["s"]) - float(s.get("width", 0)) / 2,
            float(s["s"]) + float(s.get("width", 0)) / 2,
            str(s.get("ref") or ""),
        )
        for s in at.get("supports", [])
    ]
    sections: list[tuple[str, float]] = []
    spans = at.get("spans") or []
    if spans:
        a, b = float(spans[0]["from"]), float(spans[0]["to"])
        sections = [("A", a + min(0.12 * (b - a), 600)), ("B", (a + b) / 2)]
    return BeamDetail(
        mark=str(e.get("member") or e.get("id")),
        members=list(e.get("members") or [e.get("id")]),
        level=level_name,
        width=float(at.get("width", 300)),
        depth=float(at.get("depth", 500)),
        cover=float(at.get("cover", 40)),
        length=float(at.get("length", 0)),
        supports=supports,
        bars=bars,
        links=links,
        sections=sections,
        slab=slab,
    )


def _beam_signature(beam: BeamDetail) -> tuple:
    return (
        beam.width,
        beam.depth,
        round(beam.length),
        tuple((b.mark, round(b.start), round(b.end)) for b in beam.bars),
        tuple((round(z.start), round(z.end), z.spacing) for z in beam.links),
        tuple((round(s.start), round(s.end)) for s in beam.supports),
    )


def _join(items: list[str]) -> str:
    seen: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return ", ".join(seen)


def levels_text(names: list[str], most: int = 3, order: dict[str, float] | None = None) -> str:
    """Level names for a title: all of them, or the first and last and how many; bottom up by
    their elevations in ``order`` when given (the members come in id order: L10 before L7)."""
    names = [n for i, n in enumerate(names) if n and n not in names[:i]]
    if order:
        names.sort(key=lambda n: order.get(n, math.inf))
    if len(names) <= most:
        return ", ".join(names)
    return f"{names[0]} to {names[-1]}, {len(names)} levels"


def merge_beams(beams: list[BeamDetail], order: dict[str, float] | None = None) -> list[BeamDetail]:
    """Beam lines with the same bars, links and supports drawn once, with all their marks and
    levels (identical beams of typical floors share one elevation), the levels bottom up by
    their elevations in ``order``."""
    out: dict[tuple, tuple[BeamDetail, list[str], list[str]]] = {}
    for beam in beams:
        key = _beam_signature(beam)
        if key in out:
            _, marks, levels = out[key]
            marks += [m.strip() for m in beam.mark.split(",")]
            levels.append(beam.level)
            out[key][0].members += beam.members
        else:
            out[key] = (beam, [m.strip() for m in beam.mark.split(",")], [beam.level])
    merged = []
    for beam, marks, levels in out.values():
        beam.mark = _join(marks)
        beam.level = levels_text(levels, order=order)
        merged.append(beam)
    return merged


def column_section(e: dict[str, Any], t: Any) -> ColumnSection | None:
    """The section of a column element of the detailing model, with its type ``t``."""
    if t is None or getattr(t, "profile", None) is None:
        return None
    p, r = t.profile, t.reinforcement
    round_ = p.shape == "circle"
    b = 2 * p.radius if round_ else getattr(p, "xDim", 300)
    h = 2 * p.radius if round_ else getattr(p, "yDim", 300)
    marks = _bar_marks(e)
    counts: Counter[float] = Counter()
    for bar in e.get("bars", []):
        if bar.get("role") == "vertical":
            counts[float(bar["dia"])] += int(bar["count"])
    if not counts and r is not None:
        for g in r.longitudinal:
            counts[float(g.dia)] += g.count
    rows = e.get("transverse", [])
    tie_dia = next(
        (float(marks[str(row["mark"])]["dia"]) for row in rows if str(row.get("mark")) in marks),
        None,
    )
    tr = r.transverse if r is not None else None
    tie_dia = tie_dia or (tr.dia if tr else 10.0)
    middle = [row for row in rows if row.get("zone") in ("middle", None)]
    ends = [row for row in rows if str(row.get("zone", "")).startswith(("end", "lo"))]
    spacing = float(middle[0]["spacing"]) if middle else (tr.spacing if tr else 150.0)
    zone_len = zone_sp = None
    if ends:
        zone_len = max(_zone_length(row, e.get("at", {})) for row in ends)
        zone_sp = min(float(row["spacing"]) for row in ends)
    legs_y = tr.legs if tr else 2
    legs_x = (tr.legsX or tr.legs) if tr else 2
    splice = ""
    laps = e.get("laps") or []
    if laps:
        splice = f"LAP {float(laps[0]['length']):g}"
    return ColumnSection(
        b,
        h,
        r.cover if r else 40.0,
        [(n, d) for d, n in sorted(counts.items(), reverse=True)],
        tie_dia,
        spacing,
        round_,
        legs_x,
        legs_y,
        zone_len,
        zone_sp,
        splice,
        sorted(marks),
    )


def _zone_length(row: dict[str, Any], at: dict[str, Any]) -> float:
    """The length lo of an end zone row of a column's ties, measured from the joint face: the
    bottom row starts at the first hoop (a half spacing or 50 mm above the face), so its lo
    runs from the column's bottom; the top row ends at the soffit of the beams (the clear
    height)."""
    f, t = float(row["from"]), float(row["to"])
    bottom = at.get("bottom")
    if bottom is None:
        return t - f
    bottom = float(bottom)
    if f - bottom <= float(row.get("spacing") or 0) + 1.0:
        return t - bottom
    clear = at.get("clearHeight")
    if clear is not None:
        soffit = bottom + float(clear)
        if abs(t - soffit) <= 1.0:
            return soffit - f
    return t - f


def column_lines(columns: list[dict[str, Any]], objects: Any) -> list[ColumnLine]:
    """Column elements of the detailing model stacked on plan positions."""
    stacks: dict[tuple[int, int], ColumnLine] = {}
    for e in sorted(columns, key=lambda e: float(e.get("at", {}).get("bottom", 0))):
        pos = e.get("at", {}).get("position") or [0, 0]
        key = (round(float(pos[0]) / 50), round(float(pos[1]) / 50))
        section = column_section(e, _type_of(objects, str(e.get("type"))))
        if section is None:
            continue
        line = stacks.setdefault(key, ColumnLine(str(e.get("member") or e["id"]), []))
        line.members.append(str(e["id"]))
        line.sections[str(e.get("story") or "")] = section
    return list(stacks.values())


def _mesh(bars: list[dict[str, Any]], role: str, direction: str | None = None) -> Mesh | None:
    for b in bars:
        at = b.get("at", {})
        wanted = b.get("role") == role and direction in (None, at.get("direction"))
        if wanted and at.get("spacing"):
            legs = max(_legs(b))
            count = int(b["count"]) if b.get("count") else None
            return Mesh(float(b["dia"]), float(at["spacing"]), str(b["mark"]), legs, count)
    return None


def slab_detail(
    e: dict[str, Any],
    slab: PlanSlab | None,
    t: Any,
    level_openings: list[list[tuple]] | None = None,
) -> SlabDetail:
    """A slab panel of the detailing model as a :class:`SlabDetail`. ``level_openings``: the
    openings of every slab of the level (the top bars over a shared support are drawn on the
    same line whichever panel lists them, clear of all of them)."""
    at = e.get("at", {})
    box = at.get("box") or [0, 0, 1000, 1000]
    boundary = (
        slab.boundary
        if slab
        else _rect((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, box[2] - box[0], box[3] - box[1])
    )
    bars = e.get("bars", [])
    cover = t.reinforcement.cover if t is not None and t.reinforcement else 20.0
    detail = SlabDetail(
        id=str(e["id"]),
        mark=str(e.get("member") or e["id"]),
        boundary=boundary,
        thickness=getattr(t, "thickness", 150),
        cover=cover,
        level=str(e.get("story") or ""),
        bottom_x=_mesh([b for b in bars if b.get("at", {}).get("face") == "bottom"], "bottom", "X"),
        bottom_y=_mesh([b for b in bars if b.get("at", {}).get("face") == "bottom"], "bottom", "Y"),
        openings=slab.openings if slab else [],
    )
    holes = [_box_of(h) for h in detail.openings]
    level_holes = [_box_of(h) for h in level_openings] if level_openings is not None else holes
    used: dict[str, list[float]] = {"X": [], "Y": []}
    bottoms = [b for b in bars if b.get("at", {}).get("face") == "bottom"]
    for i, b in enumerate(bottoms):
        x_dir = b["at"].get("direction") == "X"
        share = (0.40, 0.30, 0.50)[i % 3] if x_dir else (0.55, 0.45, 0.65)[i % 3]
        run = _run(b, box, share, holes, used)
        if run is not None:
            detail.bottom_runs.append(run)
    tops = [b for b in bars if b.get("at", {}).get("face") == "top"]
    for b in tops:
        at_b = b.get("at", {})
        # the same bar listed under both panels it spans lands on the same line
        share = (0.62, 0.72, 0.82)[int(abs(float(at_b.get("from") or 0)) // 25) % 3]
        if at_b.get("direction") != "X":
            share = 1 - share
        run = _run(b, box, share, level_holes)
        if run is not None:
            detail.top_bars.append(run)
    return detail


def _box_of(points: list[tuple]) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


CLEAR_OF_OPENINGS = 150.0  # mm a drawn slab bar line keeps from an opening's edge
"""A drafting rule: the line that stands for a set of bars is drawn where it crosses no opening,
so that neither it nor its label is read as running through the opening."""


def across_position(
    a: float,
    c: float,
    band: tuple[float, float],
    x_dir: bool,
    share: float,
    holes: list[tuple[float, float, float, float]],
    used: list[float] | None = None,
) -> float:
    """Where across its band (``band[0]..band[1]``) the line of a bar set running ``a`` to
    ``c`` is drawn: at ``share`` of the band, or the nearest share (in steps of 5 %) at which
    the line crosses no opening of ``holes`` (boxes x0, y0, x1, y1) and keeps 6 % of the band
    from the lines ``used`` before. Falls back to ``share``."""
    lo, hi = min(a, c), max(a, c)
    width = band[1] - band[0]
    gap = CLEAR_OF_OPENINGS

    def clear(v: float) -> bool:
        for x0, y0, x1, y1 in holes:
            along = (x0, x1) if x_dir else (y0, y1)
            across = (y0, y1) if x_dir else (x0, x1)
            if along[1] > lo and along[0] < hi and across[0] - gap < v < across[1] + gap:
                return False
        return not any(abs(v - u) < 0.06 * abs(width) for u in used or [])

    shares = sorted((k / 20 for k in range(2, 19)), key=lambda s: (abs(s - share), s))
    for s in (share, *shares):
        v = band[0] + width * s
        if clear(v):
            return v
    return band[0] + width * share


def _run(
    b: dict[str, Any],
    box: list[float],
    share: float,
    holes: list[tuple[float, float, float, float]] | None = None,
    used: dict[str, list[float]] | None = None,
) -> TopBar | None:
    """A slab bar of the detailing model as a line in plan: along its direction from ``from``
    to ``to``, across at ``share`` of its band (or nearby, clear of the openings: see
    :func:`across_position`)."""
    at_b = b.get("at", {})
    if at_b.get("from") is None or at_b.get("to") is None:
        return None
    x_dir = at_b.get("direction") == "X"
    band = at_b.get("band") or ([box[1], box[3]] if x_dir else [box[0], box[2]])
    a, c = float(at_b["from"]), float(at_b["to"])
    lines = used.setdefault("X" if x_dir else "Y", []) if used is not None else None
    across = across_position(
        a, c, (float(band[0]), float(band[1])), x_dir, share, list(holes or []), lines
    )
    if lines is not None:
        lines.append(across)
    mesh = Mesh(float(b["dia"]), float(at_b.get("spacing") or 0) or 200.0, str(b["mark"]))
    return (
        TopBar((a, across), (c, across), mesh) if x_dir else TopBar((across, a), (across, c), mesh)
    )


def _dedupe_top_bars(slabs: list[SlabDetail]) -> None:
    """A top bar over a support shared by two panels is drawn once. The same mark over another
    support (the edge bars of two panels of one type) is a bar of its own: the key holds the
    line's position across the bars as well as its extent along them."""
    seen: set[tuple] = set()
    for s in slabs:
        kept = []
        for bar in s.top_bars:
            x_dir = abs(bar.end[0] - bar.start[0]) >= abs(bar.end[1] - bar.start[1])
            along = (bar.start[0], bar.end[0]) if x_dir else (bar.start[1], bar.end[1])
            across = bar.start[1] if x_dir else bar.start[0]
            key = (s.level, bar.mesh.mark, x_dir, round(across), *(round(v) for v in along))
            if key in seen:
                continue
            seen.add(key)
            kept.append(bar)
        s.top_bars = kept


def footing_detail(
    e: dict[str, Any], objects: Any, columns: dict[str, dict], substructure
) -> FootingDetail:
    at = e.get("at", {})
    bars = e.get("bars", [])
    col_ids = at.get("columns") or []
    column = starters = None
    column_at: tuple[float, float] = (0.0, 0.0)
    column_rotation = 0.0
    column_round = False
    starter_leg = starter_inset = None
    starter_hook = "toCentre"
    starter_mark = ""
    if col_ids and col_ids[0] in columns:
        ce = columns[col_ids[0]]
        ca = ce.get("at", {})
        t = _type_of(objects, str(ce.get("type")))
        if t is not None and getattr(t, "profile", None) is not None:
            p = t.profile
            column_round = p.shape == "circle"
            column = (
                (2 * p.radius, 2 * p.radius)
                if column_round
                else (getattr(p, "xDim", 300), getattr(p, "yDim", 300))
            )
        # the column in the footing's own axes (centre, rotation)
        rot = float(at.get("rotation") or 0.0)
        centre = at.get("centre") or [0.0, 0.0]
        pos = ca.get("position") or centre
        dx, dy = float(pos[0]) - float(centre[0]), float(pos[1]) - float(centre[1])
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        column_at = (dx * c + dy * s, -dx * s + dy * c)
        column_rotation = float(ca.get("rotation") or 0.0) - rot
        st = [b for b in ce.get("bars", []) if b.get("role") == "starter"]
        if st:
            bar = max(st, key=lambda b: float(b["dia"]))
            starters = (int(bar["count"]), float(bar["dia"]))
            leg_start, leg_end = _legs(bar)
            starter_leg = leg_start or leg_end or None
            hooks = list(_get(bar.get("at", {}), "hooks") or [None]) + [None]
            starter_hook = str(hooks[0] or "toCentre")
            r = t.reinforcement if t is not None else None
            tie = next(
                (float(b["dia"]) for b in ce.get("bars", []) if b.get("role") == "tie"),
                float(r.transverse.dia) if r is not None and r.transverse else 10.0,
            )
            cover = float(r.cover) if r is not None else 40.0
            starter_inset = cover + tie + float(bar["dia"]) / 2
            starter_mark = str(bar.get("mark") or "")
    found = None
    if substructure is not None:
        found = next((f for f in substructure.foundations if f.id == e["id"]), None)
    cover = found.reinforcement.cover if found and found.reinforcement else 75.0
    piles = []
    pile_dia = 0.0
    if found is not None and found.piles:
        piles = [tuple(p) for p in substructure.pile_offsets(found)]
        pile_type = substructure.cap_pile_type(found)
        pile_dia = pile_type.diameter if pile_type else 0
    bottom = [b for b in bars if b.get("at", {}).get("face") == "bottom"]
    top = [b for b in bars if b.get("at", {}).get("face") == "top"]
    return FootingDetail(
        mark=str(e.get("member") or e["id"]),
        members=[str(e["id"])],
        length=float(at.get("length", 1000)),
        width=float(at.get("width", 1000)),
        thickness=float(at.get("thickness", 500)),
        cover=cover,
        bottom_x=_mesh(bottom, "bottom", "X"),
        bottom_y=_mesh(bottom, "bottom", "Y"),
        top_x=_mesh(top, "top", "X"),
        top_y=_mesh(top, "top", "Y"),
        column=column,
        column_at=column_at,
        column_rotation=column_rotation,
        column_round=column_round,
        starters=starters,
        starter_leg=starter_leg,
        starter_hook=starter_hook,
        starter_inset=starter_inset,
        starter_mark=starter_mark,
        founding_level=found.foundingLevel if found is not None else None,
        piles=piles,
        pile_dia=pile_dia,
        kind="pile cap" if e.get("kind") == "pileCap" else "footing",
    )


def wall_detail(e: dict[str, Any], t: Any, bim: Any, levels: dict[str, Level]) -> WallDetail:
    at = e.get("at", {})
    r = t.reinforcement if t is not None else None
    marks = {b.get("role"): b for b in e.get("bars", [])}

    def mesh(role: str, given: Any) -> Mesh | None:
        if given is None:
            return None
        bar = marks.get(role, {})
        return Mesh(float(bar.get("dia", given.dia)), given.spacing, str(bar.get("mark", "")))

    bottom, top = float(at.get("bottom", 0)), float(at.get("top", 3000))
    openings = [
        (o.offset, o.sill, o.width, o.height)
        for o in bim.additions.wallOpenings
        if o.host == e["id"]
    ]
    names = [
        (lv.name, lv.elevation - bottom)
        for lv in levels.values()
        if bottom - 1 <= lv.elevation <= top + 1
    ]
    boundary = r.boundary if r is not None else None
    hoop = next((b for b in e.get("bars", []) if b.get("role") in ("hoop", "boundary hoop")), None)
    return WallDetail(
        mark=str(e.get("member") or e["id"]),
        members=[str(e["id"])],
        length=float(at.get("length", 1000)),
        height=top - bottom,
        thickness=float(at.get("thickness", getattr(t, "thickness", 200))),
        cover=r.cover if r else 25.0,
        vertical=mesh("vertical", r.vertical if r else None),
        horizontal=mesh("horizontal", r.horizontal if r else None),
        layers=r.layers if r else 2,
        boundary_length=boundary.length if boundary else 0.0,
        boundary_bars=((boundary.count, boundary.dia) if boundary else None),
        hoops=(
            Mesh(boundary.hoop.dia, boundary.hoop.spacing, str(hoop.get("mark")) if hoop else "")
            if boundary and boundary.hoop
            else None
        ),
        openings=openings,
        levels=names,
        lintels=lintel_details(e, bottom),
    )


def lintel_details(e: dict[str, Any], bottom: float) -> list[LintelDetail]:
    """The lintels of a wall's detailing element (``bars`` with ``at.opening``, the roles
    "lintel bottom", "lintel top", "lintel stirrup"), in the wall's elevation."""
    found: dict[str, LintelDetail] = {}
    for bar in e.get("bars", []):
        at = bar.get("at") or {}
        opening = at.get("opening")
        role = str(bar.get("role", ""))
        if not opening or not role.startswith("lintel"):
            continue
        detail = found.get(opening)
        if detail is None:
            detail = found[opening] = LintelDetail(
                str(opening),
                float(at.get("from", 0.0)),
                float(at.get("to", 0.0)),
                float(at.get("bottom", bottom)) - bottom,
                float(at.get("depth", 150.0)),
                float(at.get("width", 0.0)),
            )
        mark = str(bar.get("mark") or "")
        if role == "lintel bottom":
            detail.bottom_bars = (int(bar.get("count", 0)), float(bar["dia"]), mark)
        elif role == "lintel top":
            detail.top_bars = (int(bar.get("count", 0)), float(bar["dia"]), mark)
        elif role == "lintel stirrup":
            detail.stirrups = (float(bar["dia"]), float(at.get("spacing", 0.0)), mark)
    return [found[k] for k in sorted(found)]


def stair_detail(e: dict[str, Any], t: Any, levels: dict[str, Level]) -> StairDetail:
    at = e.get("at", {})
    r = t.reinforcement if t is not None else None
    bars = e.get("bars", [])

    def mesh(role: str, given: Any) -> Mesh | None:
        bar = next((b for b in bars if b.get("role") == role), None)
        if given is None and bar is None:
            return None
        spacing = given.spacing if given is not None else 200.0
        dia = float(bar["dia"]) if bar else given.dia
        return Mesh(dia, spacing, str(bar["mark"]) if bar else "")

    flights = [int(n) for n in at.get("flights") or [10]]
    return StairDetail(
        mark=str(e.get("member") or e["id"]),
        members=[str(e["id"])],
        riser=float(at.get("riser", getattr(t, "riser", 160))),
        tread=float(at.get("going", getattr(t, "tread", 300))),
        flights=flights,
        waist=float(at.get("waist", getattr(t, "waistThickness", 150))),
        width=float(at.get("width", getattr(t, "flightWidth", 1200))),
        landing_length=(getattr(t, "landingLength", None) or getattr(t, "flightWidth", 1200))
        if len(flights) > 1
        else 0.0,
        landing_thickness=getattr(t, "landingThickness", None)
        or float(at.get("waist", getattr(t, "waistThickness", 150))),
        cover=r.cover if r else 20.0,
        main=mesh("main", r.main if r else None),
        distribution=mesh("distribution", r.distribution if r else None),
        top=mesh("top", r.top if r else None),
        landing=mesh("landing", r.landing if r else None),
        support=getattr(t, "supportWidth", 250.0) or 250.0,
    )


# ─────────────────────────────────── notes ───────────────────────────────────


def lap_table(dias: list[float], fy: float, fc: float) -> Table:
    """Development and lap lengths per bar size (BNBC 2020 Part 6 Sec 8.2, by the detailing
    rules of :mod:`saengine.drawings.detailing`)."""
    from saengine.drawings import detailing as dt

    columns = [
        {"key": "dia", "title": "Bar\nØ (mm)", "width": 6, "align": "right"},
        {"key": "ld", "title": "ld tension\n(mm)", "width": 10, "align": "right"},
        {"key": "ldTop", "title": "ld top\nbars (mm)", "width": 10, "align": "right"},
        {"key": "lap", "title": "Lap class B\n(mm)", "width": 11, "align": "right"},
        {"key": "lapTop", "title": "Lap B top\nbars (mm)", "width": 11, "align": "right"},
        {"key": "lapC", "title": "Lap compr.\n(mm)", "width": 10, "align": "right"},
        {"key": "ldh", "title": "ldh hook\n(mm)", "width": 9, "align": "right"},
    ]
    rows = []
    for d in sorted(set(dias)):
        cells = [f"{d:g}"]
        try:
            cells.append(f"{dt.development_tension(d, fy, fc).rounded():.0f}")
            cells.append(f"{dt.development_tension(d, fy, fc, top=True).rounded():.0f}")
            if d < 36:
                cells.append(f"{dt.lap_tension(d, fy, fc).rounded():.0f}")
                cells.append(f"{dt.lap_tension(d, fy, fc, top=True).rounded():.0f}")
                cells.append(f"{dt.lap_compression(d, fy, fc).rounded():.0f}")
            else:
                cells += ["no laps", "no laps", "no laps"]
            cells.append(f"{dt.hook_development(d, fy, fc).rounded():.0f}")
        except (TypeError, ValueError, AttributeError):
            cells += ["-"] * (len(columns) - len(cells))
        rows.append(cells + ["-"] * (len(columns) - len(cells)))
    return Table(
        f"Development and lap lengths (f'c {fc:g} MPa, fy {fy:g} MPa)",
        columns,
        rows,
        notes=["BNBC 2020 Part 6 Sec 8.2.3.2, 8.2.4, 8.2.6, 8.2.13.1, 8.2.14.1 (detailing model)"],
    )


def cover_table(objects: Any) -> Table:
    columns = [
        {"key": "kind", "title": "Element", "width": 12, "align": "left"},
        {"key": "type", "title": "Type", "width": 22, "align": "left"},
        {"key": "cover", "title": "Clear cover\n(mm)", "width": 11, "align": "right"},
    ]
    rows = []
    for o in objects.objects:
        r = getattr(o, "reinforcement", None)
        if r is not None:
            rows.append([o.kind, o.name, f"{r.cover:g}"])
    return Table("Clear covers", columns, rows)


# ─────────────────────────────────── the drawing set ───────────────────────────────────


def drawing_set(
    project_root: str | Path,
    *,
    detailing: dict[str, Any] | None = None,
    schedule: dict[str, Any] | None = None,
    title: dict[str, Any] | None = None,
    design_report: dict[str, Any] | None = None,
) -> DrawingSet:
    """Everything the sheets of the project at ``project_root`` draw (see the module notes).
    ``detailing``: the detailing model (run when left out); ``schedule``: the BBS table of
    :func:`saengine.drawings.bbs.sheet_table` (made from the detailing when left out);
    ``title``: drawing settings over the project settings (``TitleInfo`` keys: firm, drawn,
    checked, approved, revision, revisions, date, status, ...); ``design_report``: the design
    checks (the steel connections' utilisation on their details)."""
    from saengine.library.bim import BuildingModel
    from saengine.library.floorplan import FloorPlan
    from saengine.library.materials import MaterialLibrary
    from saengine.library.objects import ObjectLibrary

    root = Path(project_root)
    texts = {k: _read(root, v) for k, v in FILES.items()}
    data = DrawingSet()
    if not texts["bim"] or not texts["objects"]:
        data.problems.append(
            "The building model (06 BIM) and the object types (04 Objects) "
            "are needed for the drawings."
        )
        return data
    bim = BuildingModel.model_validate_json(texts["bim"])
    objects = ObjectLibrary.model_validate_json(texts["objects"])
    plan = FloorPlan.model_validate_json(texts["floorPlan"]) if texts["floorPlan"] else None
    materials = (
        MaterialLibrary.model_validate_json(texts["materials"]) if texts["materials"] else None
    )
    substructure = None
    if texts["substructure"]:
        from saengine.substructure.handover import authoritative_substructure

        substructure = authoritative_substructure(texts["substructure"], bim)
    info: dict[str, Any] = {}
    if texts["settings"]:
        project = json.loads(texts["settings"]).get("project") or {}
        info = {k: v for k, v in project.items() if isinstance(v, str)}
        if "name" in info:
            info["project"] = info.pop("name")
        if "location" not in info and json.loads(texts["settings"]).get("site", {}).get("location"):
            info.setdefault(
                "address", str(json.loads(texts["settings"])["site"]["location"]).title()
            )
    info.update({k: v for k, v in (title or {}).items() if v is not None})
    data.title = TitleInfo.from_dict(info)
    data.building = building_of(bim, objects, plan, substructure)
    if substructure is not None:
        data.pile_caps = pile_cap_schedule(substructure)
    if plan is None:
        data.problems.append("No floor plan: the plans are drawn without grids.")
    if detailing is None:
        from saengine.drawings.detailing import detailing_model

        try:
            detailing = detailing_model(root)
        except ValueError as error:
            data.problems.append(f"The detailing model could not be made: {error}")
            detailing = {"elements": [], "notes": []}
    fill_from_detailing(data, detailing, bim, objects, substructure)
    if schedule is None and detailing.get("elements"):
        from saengine.drawings import bbs

        try:
            schedule = bbs.sheet_table(bbs.bar_schedule(detailing))
        except (ValueError, TypeError, KeyError) as error:
            data.problems.append(f"The bar bending schedule could not be made: {error}")
    if schedule:
        data.bbs.append(Table.from_dict(schedule))
        apply_bbs_lengths(data, data.bbs[0])
        totals = schedule.get("totals")
        if totals:
            data.bbs.append(Table.from_dict(totals, "Bar masses by size and element (kg)"))
    data.notes = general_notes(objects, materials, detailing)
    concrete, fy = _grades(objects, materials)
    dias = sorted({float(m.get("dia")) for m in _marks(detailing) if m.get("dia")})
    if dias and concrete and fy:
        data.tables.append(lap_table(dias, fy, concrete))
    data.tables.append(cover_table(objects))
    if materials is not None:
        from saengine.drawings.sheets.steel import steel_set

        data.steel, problems = steel_set(
            root, texts, bim, objects, materials, substructure, design_report
        )
        data.problems += problems
    return data


def apply_bbs_lengths(data: DrawingSet, table: Table) -> None:
    """The cutting length the bar bending schedule lists for each bar mark (its column
    ``cutting_length``) onto the beam bars, so that the drawing's bar data reads as the BBS."""
    keys = [str(c.get("key")) for c in table.columns]
    if "mark" not in keys or "cutting_length" not in keys:
        return
    im, il = keys.index("mark"), keys.index("cutting_length")
    lengths: dict[str, float] = {}
    for row in table.rows:
        if max(im, il) < len(row) and row[im] and row[im] not in lengths:
            try:
                lengths[row[im]] = float(str(row[il]).replace(",", ""))
            except ValueError:
                continue
    for beam in data.beams:
        for bar in beam.bars:
            if bar.mark in lengths:
                bar.bbs_length = lengths[bar.mark]


def _marks(detailing: dict[str, Any]) -> list[dict[str, Any]]:
    marks = detailing.get("marks") or {}
    return list(marks.values()) if isinstance(marks, dict) else list(marks)


def _grades(objects: Any, materials: Any) -> tuple[float | None, float | None]:
    """The f'c most used by the reinforced types and their bars' fy."""
    if materials is None:
        return None, None
    fcs: Counter[float] = Counter()
    fys: Counter[float] = Counter()
    for o in objects.objects:
        r = getattr(o, "reinforcement", None)
        if r is None:
            continue
        m, bars = materials.get(o.material), materials.get(r.material)
        if m is not None and m.concrete is not None:
            fcs[m.concrete.fc] += 1
        if bars is not None and bars.steel is not None:
            fys[bars.steel.fy] += 1
    return (fcs.most_common(1)[0][0] if fcs else None, fys.most_common(1)[0][0] if fys else None)


def fill_from_detailing(
    data: DrawingSet, detailing: dict[str, Any], bim: Any, objects: Any, substructure: Any = None
) -> None:
    """The detailed members of ``detailing`` into ``data`` (whose building is set)."""
    levels = {lv.id: lv for lv in data.building.levels}
    elements = detailing.get("elements") or []
    columns = [e for e in elements if e.get("kind") == "column"]
    data.columns = column_lines(columns, objects)
    by_id = {str(e["id"]): e for e in columns}
    beams = []
    for e in (e for e in elements if e.get("kind") == "beam"):
        lv = levels.get(str(e.get("story") or ""))
        z = float(e.get("at", {}).get("elevation", lv.elevation if lv else 0))
        slab = next((s.thickness for s in data.building.slabs if abs(s.elevation - z) < 1), 0.0)
        t = _type_of(objects, str(e.get("type")))
        legs = (
            t.reinforcement.transverse.legs
            if t is not None and t.reinforcement and t.reinforcement.transverse
            else 2
        )
        beams.append(beam_detail(e, lv.name if lv else "", slab, legs))
    data.beams = merge_beams(beams, {lv.name: lv.elevation for lv in data.building.levels})
    slabs_by_id = {s.id: s for s in data.building.slabs}
    slab_elements = [e for e in elements if e.get("kind") == "slab"]
    openings: dict[str, list[list[tuple]]] = {}
    for e in slab_elements:
        plan_slab = slabs_by_id.get(str(e["id"]))
        if plan_slab is not None:
            openings.setdefault(str(e.get("story") or ""), []).extend(plan_slab.openings)
    data.slabs = [
        slab_detail(
            e,
            slabs_by_id.get(str(e["id"])),
            _type_of(objects, str(e.get("type"))),
            openings.get(str(e.get("story") or ""), []),
        )
        for e in slab_elements
    ]
    _dedupe_top_bars(data.slabs)
    data.footings = [
        footing_detail(e, objects, by_id, substructure)
        for e in elements
        if e.get("kind") in ("footing", "pileCap")
    ]
    data.walls = [
        wall_detail(e, _type_of(objects, str(e.get("type"))), bim, levels)
        for e in elements
        if e.get("kind") == "wall"
    ]
    data.stairs = [
        stair_detail(e, _type_of(objects, str(e.get("type"))), levels)
        for e in elements
        if e.get("kind") == "staircase"
    ]
    for st in data.stairs:
        e = next(x for x in elements if str(x.get("member") or x["id"]) == st.mark)
        stair = next((s for s in bim.additions.stairs if s.id == e["id"]), None)
        if stair is not None:
            st.base_name = levels[stair.base].name if stair.base in levels else ""
            st.top_name = levels[stair.top].name if stair.top in levels else ""
    data.problems += [str(n) for n in detailing.get("notes", []) if "not detailed" in str(n)]


def general_notes(objects: Any, materials: Any, detailing: dict[str, Any]) -> list[str]:
    """The general notes of the drawing set."""
    notes = [
        (
            "All dimensions are in millimetres and levels in metres unless noted. Do not scale "
            "from the drawings; work to the figured dimensions."
        ),
        (
            "Design and detailing to BNBC 2020 (Part 6 Chapters 6 and 8). Read these drawings "
            "with the design report and the architectural drawings."
        ),
    ]
    if materials is not None:
        concrete = sorted(
            {
                materials.get(o.material).name
                for o in objects.objects
                if materials.get(o.material) is not None
                and materials.get(o.material).concrete is not None
            }
        )
        bars = sorted(
            {
                materials.get(o.reinforcement.material).name
                for o in objects.objects
                if getattr(o, "reinforcement", None) is not None
                and materials.get(o.reinforcement.material) is not None
            }
        )
        if concrete:
            notes.append("Concrete: " + "; ".join(concrete) + ".")
        if bars:
            notes.append("Reinforcement: " + "; ".join(bars) + ". Ø denotes the bar size.")
    notes += [
        "Clear covers are to the outermost bars (links, ties) as the cover table gives.",
        (
            "Laps and anchorages are as the development and lap length table unless the "
            "drawing shows a length; laps where the elevations show them (class B), none in "
            "beam-column joints; no laps of 36 mm bars and larger: mechanical couplers."
        ),
        "Bar marks (e.g. B1-T2) refer to the bar bending schedule; shape codes to BS 8666.",
    ]
    for n in detailing.get("notes", []):
        text = str(n)
        if text.startswith("Detailing to"):
            notes.append(text)
    return notes
