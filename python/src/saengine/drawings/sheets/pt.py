"""Post-tensioning sheets: the tendon plan of each level with PT slabs, the tendon profiles, and
the tendon and stressing schedule (anchors, jacking force, lock-off and elongation). Drawn from
the slab tendons of the building model (``06 BIM`` additions, :class:`saengine.library.bim.
SlabTendon`) and their forces as the PT slab design works them out
(:func:`saengine.design.prestress.tendon_forces`: friction, anchor set and elastic shortening
along the tendon), never a second model of the tendons.

Conventions:

- Plan: each group runs straight from its start to its end; its tendons are drawn as lines, a
  distributed group spread over its strip (``width / count`` apart), a banded group at
  :data:`BAND_SPACING` centres at most, centred on the group's line (the band's final
  positions are the PT supplier's shop drawings'). The live end has a filled triangle, the dead
  end a filled square. The CGS heights above the soffit [mm] are written at the profile's points
  (high points over the supports, low points in the spans).
- Profile: along the tendon at the elevation scale, the heights exaggerated
  :data:`VERTICAL` times (noted), the slab's soffit and top, the CGS (parabolic between the
  profile's points, :class:`saengine.design.prestress.Segment`), the supports at the high
  points, the distances between the points and the heights at them.
- Schedule, per group: tendons x strands, strand area and fpu, length, the live and dead
  anchors, the jacking force per tendon (fpj Aps), the force at the live anchor after the
  anchor set (lock-off), the elongation to measure at each live end, and the concrete strength
  at stressing (f'ci).

Elongation (mechanics, as the jacking force is checked by it, ACI 318-11 18.20.1, which BNBC 2020
Part 6 Chapter 9 follows): Δ = ∫ P(x) dx / (Ep Aps) over the length a live end stresses, P(x)
the force after friction (18.6.2.1) as jacked; with both ends live, each end stresses up to the
point where the forces from the two ends meet. The anchor set is not part of it (the draw-in
happens at lock-off, after the elongation is measured).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.drawings.sheets.layout import TEXT, View, ViewSpec
from saengine.drawings.sheets.model import Building, Level, Point, Table
from saengine.drawings.sheets.plans import (
    DIM_1,
    DIM_2,
    EPS,
    _bounds,
    _columns,
    _level_points,
    _walls,
    grids,
)

BAND_SPACING = 300.0
"""mm, the most a banded group's tendons are drawn apart (drafting, not a code value)."""
VERTICAL = 5.0
"""The vertical exaggeration of the tendon profiles."""
PROFILE_SAMPLES = 24
"""Points per profile segment drawn."""

PLAN_NOTES = [
    (
        "Tendons straight in plan between their anchors; banded tendons at 300 mm centres at most "
        "in the band, distributed tendons evenly over their strip."
    ),
    "Filled triangle: live (stressing) end; filled square: dead end.",
    "Numbers along the tendons: height of the strands' centroid (CGS) above the soffit [mm].",
    "Final tendon positions, chairs and supports to the PT supplier's shop drawings.",
]
PROFILE_NOTES = [
    f"Vertical scale exaggerated {VERTICAL:g} times; heights are of the CGS above the soffit [mm].",
    "Parabolic between the points, the vertex at the lower point of each segment.",
    "Supports (triangles) at the high points: the strip is designed on them.",
]
SCHEDULE_NOTES = [
    "Jacking force per tendon: fpj Aps (ACI 318-11 18.5.1: fpj <= 0.80 fpu, 0.94 fpy).",
    "Lock-off: the force at the live anchor after the anchor set (18.5.1: <= 0.70 fpu).",
    (
        "Elongation: ∫P(x)dx / (Ep Aps) with the friction of 18.6.2.1, per live end; measured "
        "elongations within 7 % of these (ACI 318-11 18.20.1), else the cause found and corrected."
    ),
    "Stress when the concrete has reached f'ci; the PT design checks are in the design report.",
]


@dataclass
class PtTendon:
    """A tendon group as drawn: its bim entry (``tendon``), its slab, and its forces."""

    tendon: Any
    slab: str
    level: str  # story id
    elevation: float  # top of the slab [mm]
    thickness: float  # mm
    fc: float  # MPa
    forces: Any = None  # saengine.design.prestress.TendonForces
    pieces: list[Any] = field(default_factory=list)  # the profile's segments
    elongation: tuple[float, ...] = ()  # mm per live end (start first)
    problem: str = ""

    @property
    def start(self) -> Point:
        return (float(self.tendon.x1), float(self.tendon.y1))

    @property
    def end(self) -> Point:
        return (float(self.tendon.x2), float(self.tendon.y2))

    @property
    def length(self) -> float:
        return float(self.tendon.profile[-1].at)

    @property
    def strand_area(self) -> float:
        """Aps of one tendon [mm²]."""
        return self.tendon.strands * self.tendon.strandArea


# ─────────────────────────────────── forces ───────────────────────────────────


def elongations(
    pj: float, pieces: list[Any], stations: np.ndarray, tendon: Any, area: float
) -> tuple[float, ...]:
    """The elongation [mm] to measure at each live end (start first): ∫P(x)dx / (Ep Aps) of
    the force after friction as jacked from that end, over the length it stresses (see the
    module notes). ``pj``: the group's jacking force [N]; ``area``: the group's Aps [mm²]."""
    from saengine.design.prestress import friction_forces

    k, mu, ep = tendon.wobble, tendon.friction, tendon.ep
    if tendon.stressedAt in ("start", "end"):
        force = friction_forces(pj, pieces, stations, k, mu, tendon.stressedAt)
        return (float(np.trapezoid(force, stations)) / (ep * area),)
    from_start = friction_forces(pj, pieces, stations, k, mu, "start")
    from_end = friction_forces(pj, pieces, stations, k, mu, "end")
    # where the two diagrams meet: the start end stresses up to there, the end end the rest
    diff = from_start - from_end
    i = int(np.argmax(diff <= 0)) if np.any(diff <= 0) else len(stations) - 1
    if np.allclose(diff, 0.0, atol=1e-9 * pj):  # no friction: each end stresses half
        x_meet = float(stations[0] + stations[-1]) / 2
    elif i == 0:
        x_meet = float(stations[0])
    else:
        d0, d1 = float(diff[i - 1]), float(diff[i])
        t = d0 / (d0 - d1) if d0 != d1 else 0.0
        x_meet = float(stations[i - 1] + t * (stations[i] - stations[i - 1]))
        # a profile point in that step: the forces jump at its kink, they meet there
        for p in tendon.profile:
            if stations[i - 1] <= p.at <= stations[i]:
                x_meet = float(p.at)
                break
    p_meet = float(np.interp(x_meet, stations, from_start))
    left = stations < x_meet
    xs_a = np.append(stations[left], x_meet)
    ps_a = np.append(from_start[left], p_meet)
    xs_b = np.insert(stations[~left], 0, x_meet)
    ps_b = np.insert(from_end[~left], 0, p_meet)
    a = float(np.trapezoid(ps_a, xs_a)) / (ep * area)
    b = float(np.trapezoid(ps_b, xs_b)) / (ep * area)
    return (a, b)


def with_forces(item: PtTendon) -> PtTendon:
    """``item`` with its forces along the tendon (the PT design's) and its elongations."""
    from saengine.design import prestress

    tendon = item.tendon
    try:
        points = [(float(p.at), float(p.height)) for p in tendon.profile]
        model, pieces = prestress.strip_model(points)
        forces = prestress.tendon_forces(
            tendon, pieces, model.stations, float(tendon.width) * item.thickness, item.fc
        )
    except (ValueError, ArithmeticError) as error:
        item.problem = f"{tendon.id}: its forces could not be worked out ({error})"
        return item
    item.forces, item.pieces = forces, pieces
    item.elongation = elongations(forces.jacking, pieces, forces.stations, tendon, forces.area)
    return item


# ─────────────────────────────────── the project's tendons ───────────────────────────────────


def pt_tendons(bim: Any, objects: Any, materials: Any) -> tuple[list[PtTendon], list[str]]:
    """The slab tendons of the building model with their slabs and forces, and the problems
    (a tendon in no slab of the model)."""
    tendons = list(getattr(bim.additions, "slabTendons", None) or [])
    if not tendons:
        return [], []
    types = {o.id: o for o in objects.objects}
    elements = {e.id: e for e in bim.elements}
    stories = sorted(bim.stories, key=lambda s: s.elevation)
    out: list[PtTendon] = []
    problems: list[str] = []
    for tendon in tendons:
        slab = elements.get(tendon.host)
        t = types.get(slab.type) if slab is not None else None
        if slab is None or slab.kind != "slab" or t is None:
            problems.append(f"{tendon.id}: its slab {tendon.host} is not in the building model; "
                            "not drawn.")  # fmt: skip
            continue
        level = next(
            (s.id for s in stories if abs(s.elevation - slab.elevation) < EPS),
            stories[-1].id if stories else "",
        )
        fc = 0.0
        material = materials.get(t.material) if materials is not None else None
        if material is not None and material.concrete is not None:
            fc = float(material.concrete.fc)
        if fc <= 0:
            problems.append(f"{tendon.id}: no concrete strength for its slab; forces not drawn.")
            item = PtTendon(tendon, slab.id, level, slab.elevation, float(t.thickness), 0.0)
            item.problem = "no f'c"
            out.append(item)
            continue
        item = with_forces(
            PtTendon(tendon, slab.id, level, slab.elevation, float(getattr(t, "thickness", 200)),
                     fc)
        )  # fmt: skip
        if item.problem:
            problems.append(item.problem)
        out.append(item)
    return out, problems


# ─────────────────────────────────── the plan ───────────────────────────────────


def tendon_lines(item: PtTendon) -> list[tuple[Point, Point]]:
    """The tendons of a group in plan (see the module notes)."""
    t = item.tendon
    (x1, y1), (x2, y2) = item.start, item.end
    length = math.hypot(x2 - x1, y2 - y1) or 1.0
    nx, ny = -(y2 - y1) / length, (x2 - x1) / length
    if t.layout == "distributed":
        spacing = float(t.width) / t.count
    else:
        spacing = min(float(t.width) / t.count, BAND_SPACING)
    lines = []
    for i in range(t.count):
        off = (i - (t.count - 1) / 2) * spacing
        lines.append(((x1 + nx * off, y1 + ny * off), (x2 + nx * off, y2 + ny * off)))
    return lines


def _anchor(view: View, at: Point, towards: Point, live: bool) -> None:
    """A live end (filled triangle pointing out of the slab) or a dead end (filled square)."""
    size = view.real(1.6)
    dx, dy = towards[0] - at[0], towards[1] - at[1]
    d = math.hypot(dx, dy) or 1.0
    ux, uy = dx / d, dy / d
    nx, ny = -uy, ux
    if live:
        pts = [
            (at[0] - ux * size * 0.2, at[1] - uy * size * 0.2),
            (at[0] + ux * size + nx * size * 0.6, at[1] + uy * size + ny * size * 0.6),
            (at[0] + ux * size - nx * size * 0.6, at[1] + uy * size - ny * size * 0.6),
        ]
    else:
        h = size * 0.45
        pts = [
            (at[0] + nx * h, at[1] + ny * h),
            (at[0] + ux * 2 * h + nx * h, at[1] + uy * 2 * h + ny * h),
            (at[0] + ux * 2 * h - nx * h, at[1] + uy * 2 * h - ny * h),
            (at[0] - nx * h, at[1] - ny * h),
        ]
    view.polyline(pts, "S-PT-ANCH", close=True)
    view.hatch(pts, "SOLID", "S-PT-ANCH")


def group_text(item: PtTendon) -> str:
    """``PT1: 4 x 1 strand, banded``"""
    t = item.tendon
    strands = "strand" if t.strands == 1 else "strands"
    return f"{t.id}: {t.count} x {t.strands} {strands}, {t.layout}"


def tendon_plan(
    building: Building, level: Level, items: list[PtTendon], scale: float = 100
) -> ViewSpec:
    """The tendon plan of ``level``: its slabs, columns and walls, the tendon groups."""
    on_level = [i for i in items if i.level == level.id]
    points = _level_points(building, level)
    for item in on_level:
        for a, b in tendon_lines(item):
            points += [a, b]
    bbox = _bounds(points)
    pad = (DIM_2 + 6, DIM_2 + 6, DIM_1 + 10, DIM_1 + 10)

    def draw(view: View) -> None:
        z = level.elevation
        grids(view, building, bbox)
        _columns(view, building, z)
        _walls(view, building, z)
        for s in (s for s in building.slabs if abs(s.elevation - z) < EPS):
            view.polyline(s.boundary, "S-SLAB", close=True)
            for hole in s.openings:
                view.polyline(hole, "S-OPEN", close=True)
        for item in on_level:
            t = item.tendon
            for a, b in tendon_lines(item):
                view.line(a, b, "S-PT-TNDN")
                _anchor(view, a, b, t.stressedAt in ("start", "both"))
                _anchor(view, b, a, t.stressedAt in ("end", "both"))
        # the CGS heights at the profile's points along each group's line, then its tag
        for item in on_level:
            t = item.tendon
            (x1, y1), (x2, y2) = item.start, item.end
            plan_length = math.hypot(x2 - x1, y2 - y1) or 1.0
            ux, uy = (x2 - x1) / plan_length, (y2 - y1) / plan_length
            scale_along = plan_length / item.length if item.length > 0 else 1.0
            for p in t.profile:
                at = (x1 + ux * p.at * scale_along, y1 + uy * p.at * scale_along)
                view.circle(at, view.real(0.6), "S-PT-PROF")
                view.label(f"{p.height:g}", at, [(1.5, 1.5, "BL"), (1.5, -1.5, "TL"),
                                                 (-1.5, 1.5, "BR"), (-1.5, -1.5, "TR")],
                           TEXT, layer="S-PT-PROF")  # fmt: skip
            mid = ((x1 + x2) / 2, (y1 + y2) / 2)
            view.label(group_text(item), mid, [(0, 4, "BC"), (0, -4, "TC")], TEXT, leader=True)

    return ViewSpec(
        title=f"Post-tensioning plan - {level.name}",
        scale=scale,
        bbox=bbox,
        draw=draw,
        pad=pad,
        subtitle=f"SCALE 1:{scale:g}   TOP OF SLAB +{level.elevation / 1000:.3f}",
        key=f"pt-plan:{level.id}",
    )


# ─────────────────────────────────── the profile ───────────────────────────────────


def profile_points(item: PtTendon) -> list[Point]:
    """The CGS along the tendon (distance, height) as drawn: :data:`PROFILE_SAMPLES` points
    per parabolic segment."""
    from saengine.design.prestress import segments

    points = [(float(p.at), float(p.height)) for p in item.tendon.profile]
    out: list[Point] = []
    for piece in segments(points):
        for i in range(PROFILE_SAMPLES + (1 if piece.x1 == points[-1][0] else 0)):
            x = piece.x0 + (piece.x1 - piece.x0) * i / PROFILE_SAMPLES
            out.append((x, piece.height(x)))
    return out


def tendon_profile(item: PtTendon, scale: float = 50) -> ViewSpec:
    """The profile of a tendon group along its length (heights exaggerated, see the notes)."""
    from saengine.design.prestress import supports

    t = item.tendon
    h = item.thickness
    length = item.length
    v = VERTICAL
    bbox = (0.0, -h * v * 0.6, length, h * v * 1.25)

    def draw(view: View) -> None:
        view.line((0, 0), (length, 0), "S-CONC")  # soffit
        view.line((0, h * v), (length, h * v), "S-CONC")  # top of slab
        view.line((0, 0), (0, h * v), "S-CONC")
        view.line((length, 0), (length, h * v), "S-CONC")
        view.polyline([(x, y * v) for x, y in profile_points(item)], "S-PT-TNDN")
        points = [(float(p.at), float(p.height)) for p in t.profile]
        tri = view.real(1.8)
        for x in supports(points):
            view.polyline([(x, 0), (x - tri, -tri * 1.4), (x + tri, -tri * 1.4)], "S-PT-PROF",
                          close=True)  # fmt: skip
        for x, y in points:
            view.line((x, 0), (x, y * v), "S-PT-PROF", linetype="DASHED")
            view.circle((x, y * v), view.real(0.6), "S-PT-PROF")
            view.label(f"{y:g}", (x, y * v), [(0, 2.5, "BC"), (0, -2.5, "TC")], TEXT,
                       layer="S-PT-PROF")  # fmt: skip
        view.chain([(x, 0) for x, _ in points], -(tri * 1.4 / view.scale + 8))
        live = {"start": "LIVE END", "end": "DEAD END", "both": "LIVE END"}[t.stressedAt]
        far = {"start": "DEAD END", "end": "LIVE END", "both": "LIVE END"}[t.stressedAt]
        view.text(live, (0, h * v + view.real(3)), TEXT, "BL")
        view.text(far, (length, h * v + view.real(3)), TEXT, "BR")

    return ViewSpec(
        title=f"Tendon profile - {t.id}",
        scale=scale,
        bbox=bbox,
        draw=draw,
        pad=(8.0, DIM_1 + 6, 8.0, 10.0),
        subtitle=f"SCALE 1:{scale:g} (VERTICAL x{VERTICAL:g})   SLAB {item.slab} {h:g} THK",
        key=f"pt-profile:{t.id}",
    )


# ─────────────────────────────────── the schedule ───────────────────────────────────


def schedule_row(item: PtTendon, level_name: str) -> list[str]:
    t = item.tendon
    live = {"start": t.count, "end": t.count, "both": 2 * t.count}[t.stressedAt]
    dead = 0 if t.stressedAt == "both" else t.count
    ends = {"start": "Start", "end": "End", "both": "Both"}[t.stressedAt]
    forces = item.forces
    if forces is not None:
        pj = forces.jacking / t.count / 1e3
        at = forces.after_set[0] if t.stressedAt in ("start", "both") else forces.after_set[-1]
        lock = float(at) / t.count / 1e3
        elong = " + ".join(f"{e:.0f}" for e in item.elongation)
        jack, lock_text = f"{pj:.0f}", f"{lock:.0f}"
    else:
        jack = lock_text = elong = "-"
    fci = f"{t.transferStrength:g}" if t.transferStrength else "-"
    return [
        t.id,
        item.slab,
        level_name,
        t.layout,
        f"{t.count} x {t.strands}",
        f"{t.strandArea:g} / {t.fpu:g}",
        "bonded" if t.bonded else "unbonded",
        f"{item.length / 1000:.2f}",
        ends,
        f"{live} / {dead}",
        jack,
        lock_text,
        elong,
        fci,
    ]


def stressing_table(items: list[PtTendon], building: Building) -> Table:
    """The tendon and stressing schedule (see the module notes)."""

    def name(level: str) -> str:
        found = building.level(level)
        return found.name if found else level

    columns = [
        {"key": "mark", "title": "Group", "width": 6, "align": "left"},
        {"key": "slab", "title": "Slab", "width": 6, "align": "left"},
        {"key": "level", "title": "Level", "width": 9, "align": "left"},
        {"key": "layout", "title": "Layout", "width": 10, "align": "left"},
        {"key": "count", "title": "Tendons x\nstrands", "width": 8, "align": "right"},
        {"key": "strand", "title": "Strand mm² /\nfpu MPa", "width": 10, "align": "right"},
        {"key": "bond", "title": "Bond", "width": 8, "align": "left"},
        {"key": "length", "title": "Length\n(m)", "width": 7, "align": "right"},
        {"key": "live", "title": "Stressed\nat", "width": 7, "align": "left"},
        {"key": "anchors", "title": "Anchors\nlive / dead", "width": 8, "align": "right"},
        {"key": "pj", "title": "Jacking per\ntendon (kN)", "width": 9, "align": "right"},
        {"key": "lock", "title": "Lock-off per\ntendon (kN)", "width": 9, "align": "right"},
        {"key": "elong", "title": "Elongation per\nlive end (mm)", "width": 11, "align": "right"},
        {"key": "fci", "title": "f'ci\n(MPa)", "width": 6, "align": "right"},
    ]
    rows = [schedule_row(item, name(item.level)) for item in items]
    return Table("Tendon and stressing schedule", columns, rows)
