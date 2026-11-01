"""Two-way slab systems designed by frames of design strips: the slab cut into frames along the
column lines each way, each frame's moments found by the method the code pack names, then
distributed to its column strips, beams and middle strips (B33).

The pack's ``slabMethods.twoWayMethods`` lists the methods by id, tried in order; the first
whose limits the slab meets designs it:

- ``directDesign`` (:mod:`saengine.design.direct_design`): the total static moment of each
  span shared by fixed coefficients;
- ``equivalentFrame`` (:mod:`saengine.design.equivalent_frame`): each frame analysed as a
  continuous slab-beam on equivalent columns, with the live load patterns.

A pack without ``slabMethods`` (or with an empty list) does not cover these slabs: they are then
designed from shells only (the analysis's slabs as shells).

Frames (:func:`build_frames`). The frame lines along a direction are the lines of columns (and
of beams and walls) running that way (:func:`saengine.design.slab.support_lines`), the supports
along a frame the lines across it. A frame's width l2 reaches half way to the next line on each
side, or to the slab's edge (default pack BNBC 6.5.6.2.3-6.5.6.2.4, 6.5.7.2.2-6.5.7.2.4). Where the slab
continues past its first or last support (a neighbouring slab at the same level), the frame is
extended by that slab's span, so the span next to it is not taken as an end span. A frame
whose crossing lines have no column, wall or beam where it crosses them is not a frame (an
irregular grid): the slab is then not designed this way.

Units: mm, N, MPa; loads N/mm²; moments N·mm (whole strips) and N·mm/mm (per unit width).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from saengine.codes import context as code_context

#: Columns within this distance of a frame line are on it [mm] (as the design strips).
ON_LINE = 300.0


def rules() -> Any:
    """The pack's ``slabMethods`` table, or None when the pack in force does not cover it."""
    pack = code_context.current()
    if not pack.has("slabMethods"):
        return None
    return pack.table("slabMethods")


def methods() -> list[str]:
    """The methods of two-way slab systems the pack names, in order (empty: not covered)."""
    table = rules()
    return list(getattr(table, "twoWayMethods", None) or []) if table is not None else []


def clause(key: str) -> str:
    """The pack's clause ``key`` of ``slabMethods``, after the pack's edition ("" if none)."""
    table = rules()
    text = (getattr(table, "clauses", None) or {}).get(key) if table is not None else None
    if not text:
        return ""
    pack = code_context.current()
    return f"{pack.edition or pack.name} {text}"


@dataclass(frozen=True)
class ColumnStiffness:
    """A column above or below a slab: its height centre to centre of the slabs [mm], E [MPa]
    and the depth [mm] of the slab at its far end (rigid over it); I is of the column's
    section about the axis the frame bends it."""

    height: float
    e: float
    far_depth: float = 0.0


@dataclass(frozen=True)
class FrameColumn:
    """A column meeting the slab (plan, mm): ``c1`` along its u axis at ``angle`` degrees from
    global X, ``c2`` across; the columns above and below it for the equivalent frame."""

    id: str
    centre: tuple[float, float]
    c1: float
    c2: float
    angle: float = 0.0
    below: ColumnStiffness | None = None
    above: ColumnStiffness | None = None


@dataclass(frozen=True)
class FrameBeam:
    """A beam at the slab's level (plan, mm): its line, width, total depth and E [MPa]."""

    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    width: float
    depth: float
    e: float


@dataclass
class FrameSupport:
    """A support of a frame: its position along the frame [mm], sizes along (``c1``) and across
    (``c2``) the frame, what it is ("column", "wall", "beam") and, for the equivalent frame, the
    columns' stiffness [N·mm] above and below, and the transverse beam (width, depth) at it."""

    at: float
    c1: float
    c2: float
    kind: str
    ids: tuple[str, ...] = ()
    column_k: float = 0.0
    transverse_beam: tuple[float, float] | None = None
    #: A wall running across the frame over at least this much of l2 [mm] (0: none).
    wall_length: float = 0.0


@dataclass
class SlabFrame:
    """One frame: supports along it (sorted), its line across (``at``), its width l2 as the two
    halves either side of the line (``half_before``, ``half_after``; 0 past a slab edge) and the
    beams along it. ``own``: the indices of the spans that belong to the slab being designed
    (the others are spans of neighbouring slabs the frame was extended by)."""

    direction: str  # "X": spans along local x
    at: float
    supports: list[FrameSupport]
    half_before: float
    half_after: float
    h: float
    ecs: float
    own: list[int] = field(default_factory=list)
    #: Whether each side reaches the next frame line (a panel), not a slab edge.
    inner: tuple[bool, bool] = (True, True)
    #: αf of the beam along each span [-] (0: none), Ecb Ib / (Ecs Is) over the frame width.
    alpha: list[float] = field(default_factory=list)
    name: str = ""

    @property
    def l2(self) -> float:
        return self.half_before + self.half_after

    @property
    def edge(self) -> bool:
        """A frame along a slab edge (one side reaches no further panel)."""
        return not all(self.inner)

    def panels(self) -> list[float]:
        """The transverse spans of the panels either side (2 x the half reaching a line)."""
        return [
            2 * h
            for h, inner in zip((self.half_before, self.half_after), self.inner, strict=True)
            if inner and h > 0
        ]

    @property
    def spans(self) -> list[float]:
        return [b.at - a.at for a, b in zip(self.supports, self.supports[1:], strict=False)]

    def clear(self, k: int) -> float:
        a, b = self.supports[k], self.supports[k + 1]
        return b.at - a.at - (a.c1 + b.c1) / 2

    def column_strip(self, k: int) -> tuple[float, float]:
        """Widths of the column strip and the middle strip(s) of span ``k`` [mm]: the column
        strip 0.25 min(l1, l2) each side of the line (the inside half only at an edge), the
        middle strips the rest of l2 (default pack BNBC 6.5.2.1-6.5.2.2)."""
        l1 = self.spans[k]
        half = 0.0
        for side in (self.half_before, self.half_after):
            if side > 0:
                half += min(0.25 * min(l1, 2 * side), side)
        return half, max(self.l2 - half, 0.0)


@dataclass(frozen=True)
class StripMoment:
    """A design moment of one strip at one section: ``where`` ("negative at x", "positive"),
    the strip ("column", "middle", "beam"), the whole strip's moment [N·mm], its width [mm]
    and the combination."""

    span: int
    where: str
    strip: str
    moment: float
    width: float
    combination: str | None
    note: str = ""

    @property
    def per_width(self) -> float:
        return self.moment / self.width if self.width > 0 else 0.0


@dataclass
class FrameResult:
    """What a method gives for one frame: the strip moments, the moments at the supports'
    faces for the columns (``column_moments``: support index -> (moment N·mm, combination,
    note)), the method's notes, and the method id."""

    method: str
    frame: SlabFrame
    moments: list[StripMoment] = field(default_factory=list)
    column_moments: dict[int, tuple[float, str | None, str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Loads:
    """Service loads [N/mm²] and the gravity combinations' factors."""

    dead: float
    live: float
    combinations: tuple[tuple[str, float, float], ...]  # (name, dead factor, live factor)

    def factored(self) -> list[tuple[str, float, float]]:
        """(name, factored dead, factored live) [N/mm²] per combination."""
        return [(n, d * self.dead, lv * self.live) for n, d, lv in self.combinations]


# ───────────────────────────────────────── frames ─────────────────────────────────────────


def _local_sizes(column: FrameColumn, frame: Any) -> tuple[float, float]:
    """Sizes of a (turned) column along local x and y."""
    reference = math.degrees(math.atan2(frame.ux[1], frame.ux[0]))
    angle = math.radians(column.angle - reference)
    c, s = abs(math.cos(angle)), abs(math.sin(angle))
    return column.c1 * c + column.c2 * s, column.c1 * s + column.c2 * c


def _column_k(column: FrameColumn, h: float, along: float, across: float) -> float:
    """Σ Kc [N·mm] of the columns above and below (far ends fixed, rigid within the slabs),
    I = across along³ / 12 of the column's sizes along and across the frame."""
    from saengine.design.equivalent_frame import column_stiffness

    total = 0.0
    inertia = across * along**3 / 12
    for part in (column.below, column.above):
        if part is not None and part.height > 0:
            total += column_stiffness(part.height, part.e * inertia, h, part.far_depth)
    return total


def _beam_alpha(beam: FrameBeam, h: float, width: float, ecs: float) -> float:
    """αf = Ecb Ib / (Ecs Is): Ib of the beam with the slab each side of it as far as its
    projection below the slab and at most 4h (default pack BNBC 6.5.2.4), Is = width h³ / 12."""
    stem = max(beam.depth - h, 0.0)
    flange = min(stem, 4 * h)
    bf = beam.width + 2 * flange
    parts = [
        (bf * h, beam.depth - h / 2, bf * h**3 / 12),
        (beam.width * stem, stem / 2, beam.width * stem**3 / 12),
    ]
    area = sum(a for a, _, _ in parts)
    if area <= 0 or width <= 0:
        return 0.0
    y = sum(a * c for a, c, _ in parts) / area
    ib = sum(i + a * (c - y) ** 2 for a, c, i in parts)
    return beam.e * ib / (ecs * width * h**3 / 12)


def build_frames(
    direction: str,
    outline: Sequence[Sequence[float]],
    axes: Any,
    columns: Sequence[FrameColumn],
    supports: Sequence[Any],
    beams: Sequence[FrameBeam],
    h: float,
    ecs: float,
    neighbours: Sequence[Sequence[Sequence[float]]] = (),
) -> tuple[list[SlabFrame], list[str]]:
    """The frames of a slab with spans along ``direction`` ("X" or "Y" of its axes), and the
    reasons it has none. ``supports``: the beams and walls at its level
    (:class:`saengine.design.slab.LineSupport`); ``beams``: the beams with their sections."""
    from saengine.design import slab

    frame_axes = slab.PlanFrame(axes)
    local = [frame_axes.local(p) for p in outline]
    extent = (
        min(p[0] for p in local),
        max(p[0] for p in local),
        min(p[1] for p in local),
        max(p[1] for p in local),
    )
    along = 0 if direction == "X" else 1
    joints = [slab.ColumnJoint(c.id, c.centre, c.c1, c.c2, c.angle) for c in columns]
    lines = slab.support_lines(along, frame_axes, extent, joints, supports)
    across = slab.support_lines(1 - along, frame_axes, extent, joints, supports)
    problems: list[str] = []
    if len(lines) < 1 or len(across) < 2:
        return [], [
            (
                f"no grid of supports along {direction} (frame lines {len(lines)}, supports "
                f"across {len(across)})"
            )
        ]
    lo_t, hi_t = extent[2 * (1 - along)], extent[2 * (1 - along) + 1]
    lo_s, hi_s = extent[2 * along], extent[2 * along + 1]
    positions = {c.id: frame_axes.local(c.centre) for c in columns}
    sizes = {c.id: _local_sizes(c, frame_axes) for c in columns}
    support_by_id = {s.id: s for s in supports}
    frames: list[SlabFrame] = []
    for index, line in enumerate(lines):
        before = (line.at - lines[index - 1].at) / 2 if index > 0 else max(line.at - lo_t, 0.0)
        after = (
            (lines[index + 1].at - line.at) / 2
            if index + 1 < len(lines)
            else max(hi_t - line.at, 0.0)
        )
        frame_supports: list[FrameSupport] = []
        missing = []
        for cross in across:
            found: FrameSupport | None = None
            for column in columns:
                p = positions[column.id]
                if abs(p[along] - cross.at) <= ON_LINE and abs(p[1 - along] - line.at) <= ON_LINE:
                    c_along, c_across = sizes[column.id][along], sizes[column.id][1 - along]
                    found = FrameSupport(
                        cross.at,
                        c_along,
                        c_across,
                        "column",
                        (column.id,),
                        column_k=_column_k(column, h, c_along, c_across),
                    )
                    break
            if found is None:
                for sid in cross.ids:
                    item = support_by_id.get(sid)
                    if item is None:
                        continue
                    a, b = frame_axes.local(item.start), frame_axes.local(item.end)
                    t0, t1 = sorted((a[1 - along], b[1 - along]))
                    if t0 - ON_LINE <= line.at <= t1 + ON_LINE:
                        kind = item.kind or "beam"
                        wall_length = (
                            min(t1, line.at + after) - max(t0, line.at - before)
                            if kind == "wall"
                            else 0.0
                        )
                        found = FrameSupport(
                            cross.at,
                            item.width,
                            item.width,
                            kind,
                            (sid,),
                            wall_length=max(wall_length, 0.0),
                        )
                        break
            if found is None:
                missing.append(f"{cross.at / 1e3:.2f} m")
                continue
            # A transverse beam on the support line (torsional member of the frame).
            for beam in beams:
                a, b = frame_axes.local(beam.start), frame_axes.local(beam.end)
                if abs(a[along] - cross.at) <= ON_LINE and abs(b[along] - cross.at) <= ON_LINE:
                    t0, t1 = sorted((a[1 - along], b[1 - along]))
                    if t0 - ON_LINE <= line.at <= t1 + ON_LINE:
                        found.transverse_beam = (beam.width, beam.depth)
                        break
            frame_supports.append(found)
        axis = "y" if direction == "X" else "x"
        name = f"{direction} frame {axis} = {line.at / 1e3:.2f} m"
        if missing:
            problems.append(
                f"{name}: no support where it crosses the lines at {', '.join(missing)}"
            )
            continue
        if len(frame_supports) < 2:
            problems.append(f"{name}: fewer than two supports")
            continue
        own = list(range(len(frame_supports) - 1))
        frame = SlabFrame(
            direction,
            line.at,
            frame_supports,
            before,
            after,
            h,
            ecs,
            own,
            (index > 0, index + 1 < len(lines)),
            name=name,
        )
        _extend(frame, frame_axes, along, neighbours, lo_s, hi_s)
        frame.alpha = []
        for k in range(len(frame.spans)):
            a_at, b_at = frame.supports[k].at, frame.supports[k + 1].at
            alpha = 0.0
            for beam in beams:
                a, b = frame_axes.local(beam.start), frame_axes.local(beam.end)
                if abs(a[1 - along] - line.at) > ON_LINE or abs(b[1 - along] - line.at) > ON_LINE:
                    continue
                s0, s1 = sorted((a[along], b[along]))
                if s0 <= a_at + ON_LINE and s1 >= b_at - ON_LINE:
                    alpha = max(alpha, _beam_alpha(beam, h, frame.l2, ecs))
            frame.alpha.append(alpha)
        frames.append(frame)
    return frames, problems


def _extend(
    frame: SlabFrame,
    frame_axes: Any,
    along: int,
    neighbours: Sequence[Sequence[Sequence[float]]],
    lo: float,
    hi: float,
) -> None:
    """Add one span at each end where a neighbouring slab continues the frame past its end
    supports (to that slab's far edge), so the next span is not an end span."""
    from saengine.design import slab

    first, last = frame.supports[0], frame.supports[-1]
    for end, sign in ((first, -1), (last, 1)):
        if (sign < 0 and end.at - lo > 1) or (sign > 0 and hi - end.at > 1):
            continue  # the slab itself runs past this support (an overhang)
        for outline in neighbours:
            pts = [frame_axes.local(p) for p in outline]
            probe = [0.0, 0.0]
            probe[along], probe[1 - along] = end.at + sign * 50.0, frame.at
            plan = frame_axes.plan(*probe)
            if not slab._inside(plan, outline):
                continue
            far = max(p[along] for p in pts) if sign > 0 else min(p[along] for p in pts)
            if abs(far - end.at) < 500:
                continue
            ghost = FrameSupport(
                far,
                end.c1,
                end.c2,
                end.kind,
                end.ids,
                end.column_k,
                end.transverse_beam,
                end.wall_length,
            )
            if sign < 0:
                frame.supports.insert(0, ghost)
                frame.own = [k + 1 for k in frame.own]
            else:
                frame.supports.append(ghost)
            break


# ───────────────────────────────────────── design ─────────────────────────────────────────


def design_frames(frames: Sequence[SlabFrame], loads: Loads) -> tuple[list[FrameResult], list[str]]:
    """Each frame by the first of the pack's methods whose limits it meets (all frames of a
    slab by one method: the first that takes every frame). Returns the results and notes;
    raises ValueError when no method of the pack takes the slab."""
    table = rules()
    reasons: list[str] = []
    for method in methods():
        if method == "directDesign" and getattr(table, "directDesign", None) is not None:
            from saengine.design import direct_design

            problems = direct_design.limitations(frames, loads, table.directDesign)
            if problems:
                reasons.append(
                    f"direct design method ({clause('limits')}): " + "; ".join(problems[:3])
                )
                continue
            return [direct_design.design_frame(f, loads, table.directDesign) for f in frames], [
                f"designed by the direct design method ({clause('directDesign')})"
            ] + reasons
        if method == "equivalentFrame" and getattr(table, "equivalentFrame", None) is not None:
            from saengine.design import direct_design, equivalent_frame

            out = []
            for f in frames:
                within = (
                    not direct_design.limitations([f], loads, table.directDesign)
                    if (table.directDesign is not None)
                    else False
                )
                out.append(
                    equivalent_frame.design_frame(
                        f, loads, table.equivalentFrame, table.directDesign, within
                    )
                )
            return out, [
                f"designed by the equivalent frame method ({clause('equivalentFrame')})"
            ] + reasons
    if not methods():
        raise ValueError(_not_covered())
    raise ValueError("; ".join(reasons) or _not_covered())


def _not_covered() -> str:
    pack = code_context.current()
    return (
        f"slab systems on columns are not covered by the code pack {pack.name} without an "
        "analysis: set the analysis's slabs to shells"
    )


def layer_envelope(
    results: Sequence[FrameResult],
) -> dict[str, tuple[float, str | None, str]]:
    """The design moment per unit width [N·mm/mm, i.e. N·m/m] of each slab layer (bottomX,
    bottomY, topX, topY): the largest of the column and middle strips' moments over their
    widths in the slab's own spans (beams take their share, not the slab's)."""
    out: dict[str, tuple[float, str | None, str]] = {
        n: (0.0, None, "") for n in ("bottomX", "bottomY", "topX", "topY")
    }
    for result in results:
        frame = result.frame
        for m in result.moments:
            if m.strip == "beam" or m.span not in frame.own or m.width <= 0:
                continue
            face = "bottom" if m.where == "positive" else "top"
            name = f"{face}{frame.direction}"
            value = abs(m.per_width)  # N·mm/mm = N·m/m
            if value > out[name][0]:
                where = (
                    f"{frame.name}, span {m.span - frame.own[0] + 1}, {m.strip} strip "
                    f"{m.width:.0f} mm wide, {m.where}: M = {abs(m.moment) / 1e6:.1f} kN·m"
                    + (f"; {m.note}" if m.note else "")
                )
                out[name] = (value, m.combination, where)
    return out


# ───────────────────────────────────── the slab's checks ─────────────────────────────────────


@dataclass(frozen=True)
class Opening:
    """A slab opening: its id and plan corners [mm]."""

    id: str
    corners: tuple[tuple[float, float], ...]


def design_slab(
    system: str,
    h: float,
    reinforcement: Any,
    fc: float,
    fy: float,
    es: float,
    dead: float,
    live: float,
    combinations: Sequence[Any],
    context: Any,
    columns: Sequence[FrameColumn],
    beams: Sequence[FrameBeam],
    ecs: float,
    neighbours: Sequence[Sequence[Sequence[float]]] = (),
    openings: Sequence[Opening] = (),
) -> Any:
    """Design a two-way slab system by frames (the module notes): ``dead``, ``live`` its service
    loads [kN/m²], ``combinations`` the gravity combinations
    (:class:`saengine.design.slab.GravityCombination`), ``context`` its
    :class:`saengine.design.slab.SlabContext` (outline, axes, supports; its notes and shear are
    filled). Returns a :class:`saengine.design.slab.CoefficientDesign` whose ``method`` is the
    method id. Raises ValueError when the pack covers no method that takes the slab."""
    from saengine.design import slab

    if system == "oneWay":
        raise ValueError("a one-way slab is designed by the one-way coefficients")
    if not combinations:
        raise ValueError("no gravity load combination")
    if not methods():
        raise ValueError(_not_covered())
    loads = Loads(dead * 1e-3, live * 1e-3, tuple((c.name, c.dead, c.live) for c in combinations))
    frames: list[SlabFrame] = []
    problems: list[str] = []
    for direction in ("X", "Y"):
        found, why = build_frames(
            direction,
            context.boundary,
            context.axes,
            columns,
            context.supports,
            beams,
            h,
            ecs,
            neighbours,
        )
        if not found:
            raise ValueError(f"no frames along {direction}: " + "; ".join(why))
        frames += found
        problems += why
    if problems:
        raise ValueError("irregular support grid: " + "; ".join(problems[:3]))
    results, notes = design_frames(frames, loads)
    method = results[0].method
    for r in results:
        notes += r.notes
    envelope = layer_envelope(results)
    # One-way shear at d from the support faces, per unit width, in the frame's direction.
    layers = slab.layers_of(reinforcement, h)
    d_top = [lay.d for lay in (layers["topX"], layers["topY"]) if lay is not None]
    d = sum(d_top) / len(d_top) if d_top else h
    shear: dict[str, tuple[float, str | None, str]] = {}
    for frame in frames:
        for k in frame.own:
            ln = frame.clear(k)
            for name, qd, ql in loads.factored():
                vu = (qd + ql) * max(ln / 2 - d, 0.0) * 1000  # N/m
                key = f"top{frame.direction}"
                if key not in shear or vu > shear[key][0]:
                    shear[key] = (
                        vu,
                        name,
                        (
                            f"{frame.name}, span {k - frame.own[0] + 1}: "
                            f"qu (ln/2 - d), ln = {ln:.0f} mm"
                        ),
                    )
    table = slab.coefficient_table()
    title = {"directDesign": "direct design method", "equivalentFrame": "equivalent frame"}
    checks = slab._coefficient_checks(
        "twoWay",
        None,
        h,
        reinforcement,
        fc,
        fy,
        es,
        envelope,
        shear,
        context,
        None,
        table["maxSpacing"],
        f"{title.get(method, method)}, {clause(method)}",
    )
    checks += punching_checks(frames, results, loads, context, layers, fc)
    checks += corner_checks(frames, envelope, layers, fc, fy, es, h)
    checks += opening_checks(frames, openings, context, system)
    checks += column_moment_rows(results)
    context.notes += notes
    return slab.CoefficientDesign(method, envelope, dict(context.shear), None, checks, notes)


def _tributary(frames: Sequence[SlabFrame]) -> dict[str, dict[str, Any]]:
    """Per column id: its tributary lengths along X and Y [mm] (half the spans either side)
    and the frames and support indices it is on."""
    out: dict[str, dict[str, Any]] = {}
    for frame in frames:
        spans = frame.spans
        for j, s in enumerate(frame.supports):
            if s.kind != "column" or not s.ids:
                continue
            before = spans[j - 1] / 2 if j > 0 else 0.0
            after = spans[j] / 2 if j < len(spans) else 0.0
            entry = out.setdefault(s.ids[0], {"frames": {}})
            entry[f"along{frame.direction}"] = before + after
            entry["frames"][frame.direction] = (frame, j)
    return out


def punching_checks(
    frames: Sequence[SlabFrame],
    results: Sequence[FrameResult],
    loads: Loads,
    context: Any,
    layers: dict[str, Any],
    fc: float,
) -> list[dict[str, Any]]:
    """Two-way shear at each column on both a frame along X and one along Y: Vu = qu x (the
    tributary area less the area inside the critical section), with the moments the frames
    give the column about both axes, on the critical section at d/2 from the faces cut by the
    slab's edges (:func:`saengine.design.slab.critical_section`)."""
    from saengine.design import slab
    from saengine.design.check import _check

    d_top = [lay.d for lay in (layers["topX"], layers["topY"]) if lay is not None]
    if not d_top:
        return []
    d = sum(d_top) / len(d_top)
    moment_of = {id(r.frame): r.column_moments for r in results}
    phi = slab._phi_punching()
    rows = []
    frame_axes = slab.PlanFrame(context.axes)
    angle = math.degrees(math.atan2(frame_axes.ux[1], frame_axes.ux[0]))
    for column_id, info in _tributary(frames).items():
        if "X" not in info["frames"] or "Y" not in info["frames"]:
            continue
        fx, jx = info["frames"]["X"]
        fy_, jy = info["frames"]["Y"]
        sx, sy = fx.supports[jx], fy_.supports[jy]
        centre = frame_axes.plan(sx.at, sy.at)
        section = slab.critical_section(centre, sx.c1, sy.c1, angle, d, context.boundary)
        inside = (sx.c1 + d) * (sy.c1 + d)
        area = info.get("alongX", 0.0) * info.get("alongY", 0.0)
        mx = moment_of[id(fx)].get(jx, (0.0, None, ""))
        my = moment_of[id(fy_)].get(jy, (0.0, None, ""))
        capacity = slab.punching_capacity(
            fc, d, section.b0, max(sx.c1, sy.c1) / min(sx.c1, sy.c1), section.alpha_s
        )
        worst: tuple[Any, str, float] | None = None
        for name, qd, ql in loads.factored():
            vu = (qd + ql) * max(area - inside, 0.0)
            stress = slab.punching_stress(section, vu, mx[0], my[0])
            if worst is None or stress.vu > worst[0].vu:
                worst = (stress, name, vu)
        assert worst is not None
        stress, name, vu = worst
        rows.append(
            _check(
                f"Punching at {column_id} ({section.location})",
                stress.vu,
                phi * capacity.vc,
                "MPa",
                name,
                f"Vu = qu (tributary {area / 1e6:.2f} m² less the critical section) = "
                f"{vu / 1e3:.1f} kN, b0 = {section.b0:.0f} mm, d = {d:.0f} mm, unbalanced "
                f"moments from the frames {abs(mx[0]) / 1e6:.1f} (X) and {abs(my[0]) / 1e6:.1f} "
                "(Y) kN·m",
            )
        )
    return rows


def corner_checks(
    frames: Sequence[SlabFrame],
    envelope: dict[str, tuple[float, str | None, str]],
    layers: dict[str, Any],
    fc: float,
    fy: float,
    es: float,
    h: float,
) -> list[dict[str, Any]]:
    """Corner reinforcement where edge beams stiffer than ``corner.alphaMin`` (or walls) run
    along an edge each way (see :func:`corner_rows`)."""
    table = rules()
    corner = getattr(table, "corner", None) if table is not None else None
    if corner is None:
        return []
    stiff = {"X": False, "Y": False}
    longest = 0.0
    for frame in frames:
        longest = max([longest, *frame.spans])
        if frame.edge and (
            any(a > float(corner.alphaMin) for a in frame.alpha)
            or any(s.kind == "wall" for s in frame.supports)
        ):
            stiff[frame.direction] = True
    if not all(stiff.values()):
        return []
    return corner_rows(envelope, layers, fc, fy, es, h, longest)


def corner_rows(
    envelope: dict[str, tuple[float, str | None, str]],
    layers: dict[str, Any],
    fc: float,
    fy: float,
    es: float,
    h: float,
    longer_span: float,
) -> list[dict[str, Any]]:
    """Top and bottom corner steel for the largest positive moment per unit width of the
    panel, over ``extentShare`` of the longer span from the corner, as two layers parallel to
    the sides (the alternative arrangement the code permits), bars at most ``spacingFactor`` h
    apart (the pack's ``slabMethods.corner``). One row per face; [] without the rule."""
    from saengine.design import slab
    from saengine.design.check import _check

    table = rules()
    corner = getattr(table, "corner", None) if table is not None else None
    if corner is None:
        return []
    demand, combination, _ = max(
        (envelope["bottomX"], envelope["bottomY"]), key=lambda item: item[0]
    )
    if demand <= slab.NO_DEMAND:
        return []
    extent = float(corner.extentShare) * longer_span
    limit = float(corner.spacingFactor) * h
    rows = []
    for face in ("top", "bottom"):
        found = [layers[f"{face}{d}"] for d in ("X", "Y")]
        capacities = [
            slab.layer_capacity(lay.area, lay.d, fc, fy, es).phi_mn if lay is not None else 0.0
            for lay in found
        ]
        weakest = min(capacities)
        spacing = max((lay.spacing for lay in found if lay is not None), default=math.inf)
        strength = demand / 1e3 / (weakest / 1e6) if weakest > 0 else math.inf
        rows.append(
            _check(
                f"Corner reinforcement, {face} ({clause('corner')})",
                demand / 1e3,
                weakest / 1e6,
                "kN·m/m",
                combination,
                f"both {face} layers for the largest positive moment, over {extent:.0f} mm "
                f"from each exterior corner; bars at most {limit:.0f} mm apart (largest "
                f"{spacing:.0f} mm)",
                utilisation=max(strength, spacing / limit),
            )
        )
    return rows


def opening_checks(
    frames: Sequence[SlabFrame],
    openings: Sequence[Opening],
    context: Any,
    system: str,
) -> list[dict[str, Any]]:
    """Openings of a slab without beams, by where they cut the strips (the pack's
    ``slabMethods.openings``): in the area common to two middle strips any size; where two
    column strips cross at most ``columnColumnShare`` of a column strip's width; where a column
    and a middle strip cross at most ``columnMiddleShare`` of either; the bars cut are added on
    the sides. A slab with beams needs an analysis of its openings."""
    from saengine.design import slab
    from saengine.design.check import _check

    if not openings:
        return []
    table = rules()
    limits = getattr(table, "openings", None) if table is not None else None
    if limits is None:
        return []
    frame_axes = slab.PlanFrame(context.axes)
    beams = any(a > 0 for f in frames for a in f.alpha)
    rows = []
    for opening in openings:
        pts = [frame_axes.local(p) for p in opening.corners]
        s0, s1 = min(p[0] for p in pts), max(p[0] for p in pts)
        t0, t1 = min(p[1] for p in pts), max(p[1] for p in pts)
        if beams or system != "flat":
            rows.append(
                _check(
                    f"Opening {opening.id}",
                    1.0,
                    1.0,
                    "",
                    None,
                    "a slab with beams: openings only as shown by an analysis "
                    f"({clause('openingsAnalysis')}); set the analysis's slabs to shells",
                    flag=True,
                )
            )
            continue
        worst = (0.0, 1.0, "the area common to two middle strips (any size)")
        for frame in frames:
            cs, _ = frame.column_strip(frame.own[0])
            lo, hi = (t0, t1) if frame.direction == "X" else (s0, s1)
            cut = max(0.0, min(hi, frame.at + cs / 2) - max(lo, frame.at - cs / 2))
            if cut <= 0:
                continue
            a, b = (s0, s1) if frame.direction == "X" else (t0, t1)
            near = any(min(b, s.at + cs / 2) - max(a, s.at - cs / 2) > 0 for s in frame.supports)
            limit = float(limits.columnColumnShare if near else limits.columnMiddleShare)
            share = cut / cs
            what = "column strips crossing" if near else "a column and a middle strip"
            if share / limit > worst[0] / worst[1]:
                worst = (share, limit, f"{frame.name}: {what}, {cut:.0f} of {cs:.0f} mm cut")
        share, limit, what = worst
        rows.append(
            _check(
                f"Opening {opening.id} ({clause('openings')})",
                share,
                limit,
                "",
                None,
                f"{what}; add the bars cut on the sides of the opening; shear "
                f"({clause('openingShear')}): the punching sections are not reduced for it",
            )
        )
    return rows


def column_moment_rows(results: Sequence[FrameResult]) -> list[dict[str, Any]]:
    """The moments the columns take from the slab (informative, for the columns' design)."""
    from saengine.design.check import _check

    rows = []
    for result in results:
        for j, (moment, name, note) in sorted(result.column_moments.items()):
            support = result.frame.supports[j]
            row = _check(
                f"Slab moment to {', '.join(support.ids)} ({result.frame.name})",
                abs(moment) / 1e6,
                abs(moment) / 1e6,
                "kN·m",
                name,
                note,
            )
            row["flag"] = True
            rows.append(row)
    return rows


def method_text(used: set[str] | None = None) -> list[str]:
    """The report's method lines of the frame methods (``used``: the method ids used)."""
    lines = []
    used = used or set(methods())
    if "directDesign" in used:
        lines.append(
            "Two-way slab systems on columns (slabs not in the analysis model) by the direct "
            f"design method ({clause('directDesign')}): frames along the column lines each way, "
            "l2 to the panels' centre lines; Mo = qu l2 ln² / 8 per span shared to the support "
            "faces and midspan by the pack's coefficients, then to the column strip (0.25 "
            "min(l1, l2) each side of the line), the beam along it and the middle strips by "
            f"the pack's tables in l2/l1, αf1 l2/l1 and βt ({clause('strips')}); the limits of "
            f"{clause('limits')} are checked first. Flexure per metre of the slab's layers "
            "from the strips' moments over their widths; one-way shear qu (ln/2 - d); "
            "punching at each column from its tributary area with the moments the frames "
            f"give it ({clause('edgeTransfer')}, {clause('columnMoment')})."
        )
    if "equivalentFrame" in used:
        lines.append(
            "Two-way slab systems outside the direct design method's limits by the equivalent "
            f"frame method ({clause('equivalentFrame')}): each frame a continuous slab-beam "
            "(Is / (1 - c2/l2)² within the supports) on equivalent columns 1/Kec = 1/ΣKc + "
            f"1/Kt ({clause('torsion')}), the columns' far ends fixed; live load patterns "
            f"({clause('pattern')}); negative moments at the support faces ({clause('face')}), "
            "shared to the strips as the direct design method does."
        )
    table = rules()
    if table is not None and getattr(table, "corner", None) is not None:
        lines.append(
            f"Corner reinforcement ({clause('corner')}): at exterior corners with edge walls "
            "or edge beams stiffer than the pack's αf, top and bottom layers for the largest "
            "positive moment per metre over the pack's share of the longer span."
        )
    return lines
