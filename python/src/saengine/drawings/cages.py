"""3D reinforcement cages and the bar congestion check of beams, columns and their joints.

The cages are built from what the drawings and the bar bending schedule already use, never a
second bar model:

- *which* bars, how many, how long, where they start and stop, their hooks and the hoop rows:
  the detailing model (:func:`saengine.drawings.detailing.detailing_model`), itself made from
  the object types and the design results;
- *where in the section* each bar sits: the design's own section layout
  (:func:`saengine.design.rc.section_of`, the bars the design checks used: corners first, rows
  that do not fit split as the design splits them).

Each detailing bar is put on the section positions of its face (top, bottom, sides; columns all
round) whose diameter matches, the longest runs first so that the continuous bars take the
corners; pieces of one lapped run and the extra top bars of different supports share the
positions they do not overlap on (beyond their lap). Bars are drawn on their centrelines as
polylines (bends sharp; laps side by side are drawn on one line). Stirrups, hoops and ties are
drawn at every position of their rows, spirals as helices. Slabs, walls, stairs and foundations
are listed but not drawn in this version.

Congestion (the limits are the code pack's ``detailing.spacing``; BNBC 2020 Part 6 Sec 8.1.6,
p. 1068, in the default pack):

- bars of a layer of a beam at least max(db, 25 mm) clear (8.1.6.1), layers 25 mm apart
  (8.1.6.2), per beam type;
- column bars at least max(1.5 db, 40 mm) clear (8.1.6.3), per column type;
- at each beam-column joint: the beam bars passing the joint against the column bars they cross
  (a bar through a bar is a clash; less than the 8.1.6.1 clear spacing between them is tight,
  practice where the code gives no figure for crossing bars: the concrete must pass), and the top or
  bottom bars of beams from two directions at the same level (they cannot both be in the outer
  layer). The top bars of the secondary direction already pass in the second layer, a main bar
  diameter lower (the detailing model's ``at.topDrop``, T33:
  :func:`saengine.design.rc_detailing.joint_top_layers`; the design's hogging d allows it), so
  only crossings the layering does not resolve are flagged.

Beam bars pass inside the column bars (:func:`joint_cranks`, run by the detailing model before
the marks): at each joint the bars of a beam layer that would cross a column bar closer than the
clear spacing above (a beam flush with the column face: its corner bars on the column's bar
line; a beam's middle bar on the column's middle bar) are cranked across as little as they
need, never outside the beam's outer bars, at 1 in 6 outside the joint (practice), and scheduled as cranked bars with their
longer length. Where the bars cannot keep the full spacing they keep as much of it as they can
(reported tight); bars that cannot pass at all stay (reported as a clash).

How it is called::

    model = detailing_model(project_root, ...)
    cages = cage_model(model, objects, materials)    # {"elements", "joints", "checks", ...}
    rows = congestion_rows(cages)                    # for a CSV
"""

from __future__ import annotations

import csv
import io
import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

SCHEMA_ID = "saengine.rebar-cages/1"
#: Points of a circular tie or of one turn of a spiral.
CIRCLE_POINTS = 24
#: Joint: beams within this of the column top are framing into it [mm].
LEVEL_TOL = 60.0
#: Two beams within this angle are parallel (no crossing of their bars) [degrees].
PARALLEL_DEG = 10.0
#: Beam bars cranked at a joint go 1 across in this many along (practice for offset bars).
CRANK_SLOPE = 6.0
#: Offsets smaller than this are not cranked [mm].
CRANK_MIN = 1.0

Point3 = tuple[float, float, float]


def _cite(key: str) -> str:
    """The reference ``key`` of the code pack in force (its ``citations``, with the code's
    name); '' when the pack gives none."""
    from saengine.codes import context as code_context

    return code_context.cite("citations", key)


@dataclass
class Limits:
    """The least clear spacings of the code pack (``detailing.spacing``)."""

    layer_min: float
    layer_db: float
    between_layers: float
    column_min: float
    column_db: float

    def layer(self, db: float) -> float:
        return max(self.layer_min, self.layer_db * db)

    def column(self, db: float) -> float:
        return max(self.column_min, self.column_db * db)


def limits() -> Limits | None:
    """The limits of the active code pack, or None when it gives none."""
    from saengine.codes import context as code_context

    spacing = getattr(code_context.table("detailing"), "spacing", None)
    if spacing is None:
        return None
    return Limits(
        float(spacing.layerMin),
        float(spacing.layerDb),
        float(spacing.betweenLayers),
        float(spacing.columnMin),
        float(spacing.columnDb),
    )


# ─────────────────────────────────── section positions ───────────────────────────────────


@dataclass
class Slot:
    """A bar position of the section: ``x`` across, ``y`` up from the centre [mm]."""

    x: float
    y: float
    dia: float
    face: str  # top | bottom | side | perimeter
    taken: list[tuple[float, float, float]] = field(default_factory=list)  # from, to, lap
    shift: dict[str, float] = field(default_factory=dict)  # across offset at a joint (column)

    def free(self, a: float, b: float, lap: float) -> bool:
        for t0, t1, other in self.taken:
            overlap = min(b, t1) - max(a, t0)
            if overlap > max(lap, other) + 1.0:
                return False
        return True


def _section(type_: Any, materials: dict[str, Any]) -> Any:
    from saengine.design.rc import section_of

    concrete = materials.get(getattr(type_, "material", ""))
    aggregate = getattr(getattr(concrete, "concrete", None), "maxAggregate", None)
    return section_of(type_.profile, type_.reinforcement, 1.0, 1.0, aggregate=aggregate)


def beam_slots(section: Any, side_count: int) -> list[Slot]:
    """The section's bars as slots of a beam, with their face: the ``side_count`` bars nearest
    mid-depth on the outer verticals are side bars."""
    bars = list(section.bars)
    by_mid = sorted(range(len(bars)), key=lambda i: abs(bars[i].y))
    sides = set(by_mid[:side_count]) if side_count else set()
    slots = []
    for i, bar in enumerate(bars):
        face = "side" if i in sides else ("top" if bar.y > 0 else "bottom")
        slots.append(Slot(bar.x, bar.y, bar.dia, face))
    return _corner_first(slots)


def column_slots(section: Any) -> list[Slot]:
    return _corner_first([Slot(b.x, b.y, b.dia, "perimeter") for b in section.bars])


def _corner_first(slots: list[Slot]) -> list[Slot]:
    """Outer rows first, then the bars furthest from the centre line (the corners)."""
    return sorted(slots, key=lambda s: (-abs(s.y), -abs(s.x)))


def _assign(slots: list[Slot], face: str | None, dia: float, a: float, b: float, lap: float):
    """A free slot of ``face`` (None: any) for a bar of ``dia`` from ``a`` to ``b``; the matching
    diameter first, then any; None when none is free."""
    pool = [s for s in slots if face is None or s.face == face]
    for exact in (True, False):
        for slot in pool:
            if exact and abs(slot.dia - dia) > 0.5:
                continue
            if slot.free(a, b, lap):
                slot.taken.append((a, b, lap))
                return slot
    return None


# ─────────────────────────────────── cages ───────────────────────────────────


@dataclass
class CageBar:
    """One entry of the detailing model drawn: ``lines`` holds one polyline per physical bar."""

    element: str
    member: str  # the building model element the bars belong to (for the 3D view's ids)
    mark: str
    role: str
    dia: float
    shape: str
    length: float  # developed length of one bar [mm]
    lines: list[list[Point3]] = field(default_factory=list)
    transverse: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "member": self.member,
            "mark": self.mark,
            "role": self.role,
            "dia": self.dia,
            "shape": self.shape,
            "length": self.length,
            "transverse": self.transverse,
            "lines": [[[round(v, 1) for v in p] for p in line] for line in self.lines],
        }


def _positions(rows: Sequence[dict[str, Any]], mark: str | None) -> list[float]:
    """Where the hoops of the transverse ``rows`` (of ``mark``) are, along the member: a row
    that starts where the one before ended carries its hoops after its start, a first row from
    its start (see :func:`saengine.drawings.detailing.space`)."""
    out: list[float] = []
    previous_end: float | None = None
    for row in rows:
        if mark is not None and row.get("mark") not in (mark, None):
            continue
        a, b = float(row["from"]), float(row["to"])
        n = int(row.get("count") or 0)
        if n <= 0:
            continue
        first = previous_end is None or abs(a - previous_end) > 1.0
        if first:
            out += [a] if n == 1 else [a + (b - a) * i / (n - 1) for i in range(n)]
        else:
            out += [a + (b - a) * i / n for i in range(1, n + 1)]
        previous_end = b
    return out


def _leg(bar: dict[str, Any], end: int) -> float:
    dims = bar.get("dims") or {}
    shape = bar.get("shape")
    if shape == "U":
        return float(dims.get("A" if end == 0 else "C", 0.0))
    if shape == "L":
        return float(dims.get("B", 0.0))
    return 0.0


def _beam_layout(
    element: dict[str, Any], type_: Any, materials: dict[str, Any]
) -> tuple[list[Slot], list[tuple[dict[str, Any], list[Slot | None]]]]:
    """The section positions of a beam line and the positions its longitudinal bars take: the
    ones the detailing model kept (``at.slots``, see :func:`joint_cranks`), else the longest
    runs first, corners first (:func:`_assign`)."""
    sides = sum(g.count for g in type_.reinforcement.longitudinal if g.position == "sides")
    slots = beam_slots(_section(type_, materials), sides)
    longitudinal = [
        bar for bar in element.get("bars") or [] if bar.get("role") in ("top", "bottom", "side")
    ]
    longitudinal.sort(key=lambda bar: -(bar["at"]["to"] - bar["at"]["from"]))
    placed: list[tuple[dict[str, Any], list[Slot | None]]] = []
    for bar in longitudinal:
        a, c = float(bar["at"]["from"]), float(bar["at"]["to"])
        face = bar["at"].get("face", bar["role"])
        lap = float(bar.get("lap") or 0.0)
        kept = bar["at"].get("slots") or []
        taken: list[Slot | None] = []
        for k in range(int(bar.get("count") or 0)):
            if k < len(kept):
                x, y = kept[k]
                slot = next((s for s in slots if abs(s.x - x) < 0.5 and abs(s.y - y) < 0.5), None)
                if slot is not None:
                    slot.taken.append((a, c, lap))
            else:
                slot = _assign(slots, face, float(bar["dia"]), a, c, lap)
            taken.append(slot)
        placed.append((bar, taken))
    return slots, placed


def _path(
    a: float, c: float, x: float, cranks: Sequence[dict[str, Any]]
) -> list[tuple[float, float]]:
    """The plan path ``(along, across)`` of a beam bar from ``a`` to ``c`` at the section
    position ``x``: offset by each crank's ``offset`` over its ``from``-``to`` (a joint), going
    over at 1 in ``CRANK_SLOPE`` outside it."""
    points: list[tuple[float, float]] = []
    for crank in sorted(cranks, key=lambda k: float(k["from"])):
        dx = float(crank["offset"])
        run = CRANK_SLOPE * abs(dx)
        lo, hi = float(crank["from"]), float(crank["to"])
        if points and lo - run < points[-1][0]:  # the joints are too close: straight across
            points.pop()
            points += [(lo, x + dx), (hi, x + dx), (hi + run, x)]
        else:
            points += [(lo - run, x), (lo, x + dx), (hi, x + dx), (hi + run, x)]
    if not points:
        return [(a, x), (c, x)]

    def across(s: float) -> float:
        if s <= points[0][0]:
            return points[0][1]
        for (s0, x0), (s1, x1) in itertools.pairwise(points):
            if s0 <= s <= s1:
                return x0 if s1 - s0 < 1e-9 else x0 + (x1 - x0) * (s - s0) / (s1 - s0)
        return points[-1][1]

    path = [(a, across(a)), *((s, v) for s, v in points if a + 1e-6 < s < c - 1e-6)]
    path.append((c, across(c)))
    return [p for i, p in enumerate(path) if i == 0 or p != path[i - 1]]


def path_extra(a: float, c: float, cranks: Sequence[dict[str, Any]]) -> float:
    """How much longer than ``c - a`` the cranked path of a bar is [mm]."""
    path = _path(a, c, 0.0, cranks)
    return sum(math.hypot(s1 - s0, x1 - x0) for (s0, x0), (s1, x1) in itertools.pairwise(path)) - (
        path[-1][0] - path[0][0]
    )


def _beam_cage(element: dict[str, Any], type_: Any, materials: dict[str, Any], out: dict) -> None:
    at = element.get("at") or {}
    ox, oy = at["origin"]
    ux, uy = at["direction"]
    nx, ny = -uy, ux  # the section's x: to the left of the beam line
    elev, h = float(at["elevation"]), float(at["depth"])
    b, cover = float(at["width"]), float(at["cover"])
    top_drop = float(at.get("topDrop") or 0.0)  # T33: top bars in the second layer
    slots, placed = _beam_layout(element, type_, materials)
    members = list(element.get("members") or [element["id"]])

    def point(s: float, x: float, z: float) -> Point3:
        return (ox + ux * s + nx * x, oy + uy * s + ny * x, z)

    missing = 0
    for bar, taken in placed:
        a, c = float(bar["at"]["from"]), float(bar["at"]["to"])
        face = bar["at"].get("face", bar["role"])
        hooks = bar["at"].get("hooks") or [None, None]
        cranks = bar["at"].get("cranks") or []
        covered = bar["at"].get("members") or members
        cage = CageBar(
            element["id"], covered[0], bar.get("mark") or "", bar["role"], float(bar["dia"]),
            bar.get("shape") or "straight", float(bar.get("length") or 0.0),
        )  # fmt: skip
        for k, slot in enumerate(taken):
            if slot is None:
                missing += 1
                continue
            mine = cranks[k] if k < len(cranks) else []
            for crank in mine:
                slot.shift[str(crank["at"])] = float(crank["offset"])
            z = elev - h / 2 + slot.y - (top_drop if face == "top" else 0.0)
            path = _path(a, c, slot.x, mine)
            line = [point(s, x, z) for s, x in path]
            sign = -1.0 if face == "top" else 1.0
            if hooks[0]:
                line.insert(0, point(a, path[0][1], z + sign * _leg(bar, 0)))
            if hooks[1]:
                line.append(point(c, path[-1][1], z + sign * _leg(bar, 1)))
            cage.lines.append(line)
        out["bars"].append(cage)
    if missing:
        out["notes"].append(
            f"{element['id']}: {missing} bar(s) found no free position in the section layout of "
            f"{type_.id} and are not drawn"
        )
    tdia = float(type_.reinforcement.transverse.dia) if type_.reinforcement.transverse else 0.0
    for bar in element.get("bars") or []:
        if bar.get("role") != "stirrup":
            continue
        cage = CageBar(
            element["id"], members[0], bar.get("mark") or "", "stirrup", float(bar["dia"]),
            "stirrup", float(bar.get("length") or 0.0), transverse=True,
        )  # fmt: skip
        hx, hz = b / 2 - cover - tdia / 2, h / 2 - cover - tdia / 2
        zc = elev - h / 2
        for s in _positions(element.get("transverse") or [], bar.get("mark")):
            corners = [(-hx, -hz), (hx, -hz), (hx, hz), (-hx, hz), (-hx, -hz)]
            cage.lines.append([point(s, x, zc + z) for x, z in corners])
        out["bars"].append(cage)
    out["slots"][element["id"]] = (slots, (ox, oy), (ux, uy), elev, h, b, top_drop)


def _column_cage(element: dict[str, Any], type_: Any, materials: dict[str, Any], out: dict) -> None:
    at = element.get("at") or {}
    px, py = at["position"]
    rot = math.radians(float(at.get("rotation") or 0.0))
    cr, sr = math.cos(rot), math.sin(rot)
    section = _section(type_, materials)
    slots = column_slots(section)

    def point(x: float, y: float, z: float) -> Point3:
        return (px + x * cr - y * sr, py + x * sr + y * cr, z)

    vertical = [
        bar
        for bar in element.get("bars") or []
        if bar.get("role") in ("vertical", "starter") and not bar["at"].get("for")
    ]
    vertical.sort(key=lambda bar: (bar.get("role") != "vertical", -float(bar["dia"])))
    missing = 0
    for bar in vertical:
        z0, z1 = float(bar["at"]["from"]), float(bar["at"]["to"])
        lap = float(bar.get("lap") or 0.0)
        hooks = bar["at"].get("hooks") or [None, None]
        cage = CageBar(
            element["id"], element["id"], bar.get("mark") or "", bar["role"], float(bar["dia"]),
            bar.get("shape") or "straight", float(bar.get("length") or 0.0),
        )  # fmt: skip
        for _ in range(int(bar.get("count") or 0)):
            slot = _assign(slots, None, float(bar["dia"]), z0, z1, lap)
            if slot is None:
                missing += 1
                continue
            line = [point(slot.x, slot.y, z0), point(slot.x, slot.y, z1)]
            r = math.hypot(slot.x, slot.y) or 1.0
            for end, z in ((0, z0), (1, z1)):
                if not hooks[end]:
                    continue
                leg = _leg(bar, end)
                inward = hooks[end] in ("inward", "toCentre")
                k = (-1.0 if inward else 1.0) * leg / r
                tip = point(slot.x * (1 + k), slot.y * (1 + k), z)
                if end == 0:
                    line.insert(0, tip)
                else:
                    line.append(tip)
            cage.lines.append(line)
        out["bars"].append(cage)
    if missing:
        out["notes"].append(
            f"{element['id']}: {missing} bar(s) found no free position in the section layout of "
            f"{type_.id} and are not drawn"
        )
    cover = float(type_.reinforcement.cover)
    for bar in element.get("bars") or []:
        role = bar.get("role")
        if role not in ("tie", "spiral"):
            continue
        tdia = float(bar["dia"])
        cage = CageBar(
            element["id"], element["id"], bar.get("mark") or "", role, tdia,
            bar.get("shape") or "", float(bar.get("length") or 0.0), transverse=True,
        )  # fmt: skip
        profile = type_.profile
        if role == "spiral":
            dims = bar.get("dims") or {}
            r = (float(dims.get("A", 0.0)) - tdia) / 2
            pitch = float(dims.get("B", 0.0)) or 100.0
            z0, z1 = float(bar["at"]["from"]), float(bar["at"]["to"])
            steps = max(2, int((z1 - z0) / pitch * CIRCLE_POINTS))
            cage.lines.append(
                [
                    point(
                        r * math.cos(2 * math.pi * i / CIRCLE_POINTS),
                        r * math.sin(2 * math.pi * i / CIRCLE_POINTS),
                        z0 + (z1 - z0) * i / steps,
                    )
                    for i in range(steps + 1)
                ]
            )
        else:
            for z in _positions(element.get("transverse") or [], bar.get("mark")):
                if getattr(profile, "shape", "") == "circle":
                    r = float(profile.radius) - cover - tdia / 2
                    ring = [
                        point(r * math.cos(a), r * math.sin(a), z)
                        for a in (2 * math.pi * i / CIRCLE_POINTS for i in range(CIRCLE_POINTS + 1))
                    ]
                    cage.lines.append(ring)
                else:
                    from saengine.fem.end_zones import profile_extent

                    extent = profile_extent(profile)
                    if extent is None:  # no outline to hoop (not a reinforced concrete profile)
                        continue
                    hx = extent[0] / 2 - cover - tdia / 2
                    hy = extent[1] / 2 - cover - tdia / 2
                    corners = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy), (-hx, -hy)]
                    cage.lines.append([point(x, y, z) for x, y in corners])
        out["bars"].append(cage)
    out["columns"][element["id"]] = (
        slots,
        (px, py),
        (cr, sr),
        float(at["bottom"]),
        float(at["top"]),
    )


# ─────────────────────────────────── congestion ───────────────────────────────────


def _check(
    where: str,
    name: str,
    required: float,
    provided: float,
    clause: str,
    severity: str = "warning",
    unit: str = "mm",
) -> dict[str, Any]:
    ok = provided >= required - 1e-6
    return {
        "where": where,
        "name": name,
        "required": round(required, 1),
        "provided": round(provided, 1),
        "unit": unit,
        "ok": ok,
        "severity": "ok" if ok else severity,
        "clause": clause,
    }


def _layer_checks(type_id: str, slots: list[Slot], lim: Limits) -> list[dict[str, Any]]:
    """Clear spacing of the bars in each layer and between the layers of a beam type."""
    out = []
    rows: dict[tuple[str, int], list[Slot]] = {}
    for slot in slots:
        if slot.face in ("top", "bottom"):
            rows.setdefault((slot.face, round(slot.y)), []).append(slot)
    for face in ("top", "bottom"):
        layers = sorted((k[1], v) for k, v in rows.items() if k[0] == face)
        for _, row in layers:
            row = sorted(row, key=lambda s: s.x)
            gaps = [
                (b.x - a.x - (a.dia + b.dia) / 2, max(a.dia, b.dia))
                for a, b in itertools.pairwise(row)
            ]
            if gaps:
                clear, db = min(gaps, key=lambda g: g[0] - lim.layer(g[1]))
                out.append(
                    _check(
                        f"type {type_id}",
                        f"{face} bars: clear spacing in the layer (Ø{db:g})",
                        lim.layer(db),
                        clear,
                        _cite("barSpacing"),
                    )
                )
        for (y1, r1), (y2, r2) in itertools.pairwise(layers):
            d1, d2 = max(s.dia for s in r1), max(s.dia for s in r2)
            clear = abs(y2 - y1) - (d1 + d2) / 2
            out.append(
                _check(
                    f"type {type_id}",
                    f"{face} bars: clear distance between layers",
                    lim.between_layers,
                    clear,
                    _cite("barSpacingLayers"),
                )
            )
    return out


def _column_checks(type_id: str, slots: list[Slot], lim: Limits) -> list[dict[str, Any]]:
    """Clear spacing between the bars of a column type (the closest pair)."""
    worst = None
    for i, a in enumerate(slots):
        for b in slots[i + 1 :]:
            clear = math.hypot(a.x - b.x, a.y - b.y) - (a.dia + b.dia) / 2
            need = lim.column(max(a.dia, b.dia))
            if worst is None or clear - need < worst[0] - worst[1]:
                worst = (clear, need, max(a.dia, b.dia))
    if worst is None:
        return []
    return [
        _check(
            f"type {type_id}",
            f"column bars: clear spacing (Ø{worst[2]:g})",
            worst[1],
            worst[0],
            _cite("barSpacingColumns"),
        )
    ]


def _framing(
    element: dict[str, Any], beams: list[dict[str, Any]], out: dict
) -> Iterable[tuple[dict[str, Any], tuple, float, float]]:
    """The beams framing into the top of column ``element``: (beam, its geometry in
    ``out["slots"]``, the joint's centre along the beam, half its width along the beam)."""
    column = out["columns"].get(element["id"])
    if column is None:
        return
    top = column[4]
    for beam in beams:
        geometry = out["slots"].get(beam["id"])
        if geometry is None or abs(float(beam["at"]["elevation"]) - top) > LEVEL_TOL:
            continue
        support = next(
            (s for s in beam["at"].get("supports") or [] if s.get("ref") == element["id"]), None
        )
        if support is not None:
            yield beam, geometry, float(support["s"]), float(support.get("width") or 0.0) / 2


def _through(slots: list[Slot], s0: float, half: float) -> list[Slot]:
    """The top and bottom positions of a beam with a bar passing the joint ``s0`` ± ``half``."""
    return [
        slot
        for slot in slots
        if slot.face in ("top", "bottom")
        and any(a - 1 <= s0 + half and b + 1 >= s0 - half for a, b, _ in slot.taken)
    ]


# ─────────────────────────────── joints: beam bars inside the column bars ───────────────────────


def _free(w: float, blocked: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The closed intervals of [-w, w] outside the open ``blocked`` intervals."""
    free, start = [], -w
    for lo, hi in sorted(blocked):
        if lo > w:
            break
        if lo > start:
            free.append((start, lo))
        start = max(start, hi)
    if start <= w:
        free.append((start, w))
    return free


def _attempt(xs: list[float], db: float, cols: list[tuple[float, float]], w: float,
             lim: Limits, t: float) -> list[float] | None:  # fmt: skip
    """``xs`` (sorted) moved as little as they need to stay ``t`` times the pack's clear
    spacing from the column bars ``cols`` (across position, diameter) and from each other,
    within ±``w``; None when they do not fit."""
    eps = 1e-6
    sp = db + t * lim.layer(db)
    blocked = [
        (xc - h, xc + h) for xc, dc in cols for h in ((db + dc) / 2 + t * lim.layer(max(db, dc)),)
    ]
    free = _free(w, blocked)

    def after(v: float) -> float | None:
        return next((max(v, lo) for lo, hi in free if hi >= v - eps), None)

    def before(v: float) -> float | None:
        return next((min(v, hi) for lo, hi in reversed(free) if lo <= v + eps), None)

    n = len(xs)
    least: list[float] = []
    for j in range(n):
        v = after(-w if j == 0 else least[-1] + sp)
        if v is None or v > w + eps:
            return None
        least.append(v)
    most = [0.0] * n
    for j in reversed(range(n)):
        v = before(w if j == n - 1 else most[j + 1] - sp)
        if v is None or v < least[j] - eps:
            return None
        most[j] = v
    placed: list[float] = []
    for j, x in enumerate(xs):
        lo = least[j] if j == 0 else max(least[j], placed[-1] + sp)
        hi = most[j]
        best = None
        for a, b in free:  # the free point nearest the bar's own position
            a, b = max(a, lo), min(b, hi)
            if b < a - eps:
                continue
            v = min(max(x, a), b)
            if best is None or abs(v - x) < abs(best - x) - eps:
                best = v
        if best is None:
            return None
        placed.append(best)
    return placed


def place_through(
    xs: list[float], db: float, cols: list[tuple[float, float]], w: float, lim: Limits
) -> list[float] | None:
    """Across positions for the bars ``xs`` of a beam layer passing a joint, clear of the column
    bars ``cols`` (across position, diameter) by the pack's clear spacing (8.1.6.1 in the default
    pack, taken for crossing bars) and of each other, never further out than ±``w`` (the
    beam's outer bars: they only move inward). Where that does not fit, the largest share of
    that spacing that does (the check reports them tight); None when they cannot pass at all.
    The bars keep their order and move as little as they can (unmoved when already clear)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    sorted_xs = [xs[i] for i in order]
    found = _attempt(sorted_xs, db, cols, w, lim, 1.0)
    if found is None:
        low = _attempt(sorted_xs, db, cols, w, lim, 0.0)
        if low is None:
            return None
        lo_t, hi_t = 0.0, 1.0
        for _ in range(30):
            mid = (lo_t + hi_t) / 2
            trial = _attempt(sorted_xs, db, cols, w, lim, mid)
            if trial is None:
                hi_t = mid
            else:
                lo_t, low = mid, trial
        found = low
    out = [0.0] * len(xs)
    for i, x in zip(order, found, strict=True):
        out[i] = x
    return out


def _cranks_at(element: dict[str, Any], beams: list[dict[str, Any]], out: dict, lim: Limits):
    """Sets ``shift[column]`` on the positions of the beams framing into the top of column
    ``element`` whose bars must move to pass its bars (:func:`place_through`); returns
    ``{beam id: (from, to)}``, the joint along each beam."""
    slots_c, (px, py), (cr, sr), _, _ = out["columns"][element["id"]]
    col_points = [(px + s.x * cr - s.y * sr, py + s.x * sr + s.y * cr, s.dia) for s in slots_c]
    zones: dict[str, tuple[float, float]] = {}
    for beam, geometry, s0, half in _framing(element, beams, out):
        slots_b, (ox, oy), (ux, uy), *_ = geometry
        nx, ny = -uy, ux
        zones[beam["id"]] = (s0 - half, s0 + half)
        rows: dict[tuple[str, int], list[Slot]] = {}
        for slot in _through(slots_b, s0, half):
            rows.setdefault((slot.face, round(slot.y)), []).append(slot)
        for (face, y), row in rows.items():
            # within the beam's outer bars on that face (a second layer may spread as wide)
            w = max(abs(s.x) for s in slots_b if s.face == face)
            db = max(s.dia for s in row)
            cols = [((cx - ox) * nx + (cy - oy) * ny, dc) for cx, cy, dc in col_points]
            moved = place_through([s.x for s in row], db, cols, w, lim)
            if moved is None:
                continue
            for slot, x in zip(row, moved, strict=True):
                if abs(x - slot.x) >= CRANK_MIN:
                    slot.shift[element["id"]] = round(x - slot.x, 1)
    return zones


def joint_cranks(elements: list[dict[str, Any]], types: dict[str, Any], materials: Any) -> None:
    """Beam bars through the column bars (in place, before the marks are given): at each
    beam-column joint the bars of each beam layer that would cross a column bar closer than the
    pack's clear spacing (a beam flush with the column face: its corner bars on the column's
    bar line) are cranked across to pass inside the column cage, as detailers do
    (:func:`place_through`), at 1 in ``CRANK_SLOPE`` outside the joint. A bar entry of the
    detailing model whose bars crank becomes entries of the bars alike: the cranked ones keep
    their shape and dimensions, with ``crank`` the length the cranks add (in ``length``; the
    BBS adds it to the shape's cutting length) and a remark, the cranks in
    ``at.cranks`` (per bar: ``{"at", "from", "to", "offset"}``) and every bar's section position
    in ``at.slots``, so the cages draw what is scheduled. Nothing changes without the pack's
    spacing limits."""
    lim = limits()
    if lim is None:
        return
    mats = {m.id: m for m in (materials.materials if materials is not None else [])}
    out: dict[str, Any] = {"slots": {}, "columns": {}}
    layouts: dict[str, list[tuple[dict[str, Any], list[Slot | None]]]] = {}
    beams = []
    for element in elements:
        kind, type_ = element.get("kind"), types.get(element.get("type"))
        if kind not in ("beam", "column") or not element.get("bars") or element.get("precast"):
            continue  # a precast piece's bars stay in the piece (W4C-16)
        if type_ is None or getattr(type_, "reinforcement", None) is None:
            continue
        at = element.get("at") or {}
        try:
            if kind == "beam":
                slots, placed = _beam_layout(element, type_, mats)
                out["slots"][element["id"]] = (
                    slots, tuple(at["origin"]), tuple(at["direction"]), float(at["elevation"]),
                    float(at["depth"]), float(at["width"]), float(at.get("topDrop") or 0.0),
                )  # fmt: skip
                layouts[element["id"]] = placed
                beams.append(element)
            else:
                rot = math.radians(float(at.get("rotation") or 0.0))
                out["columns"][element["id"]] = (
                    column_slots(_section(type_, mats)), tuple(at["position"]),
                    (math.cos(rot), math.sin(rot)), float(at["bottom"]), float(at["top"]),
                )  # fmt: skip
        except (KeyError, TypeError, ValueError, AttributeError):
            continue  # not laid out: drawn (or noted) by the cages as before
    zones: dict[str, dict[str, tuple[float, float]]] = {}
    for element in elements:
        if element.get("id") in out["columns"]:
            for beam_id, zone in _cranks_at(element, beams, out, lim).items():
                zones.setdefault(beam_id, {})[element["id"]] = zone
    for beam in beams:
        _split_cranked(beam, layouts[beam["id"]], zones.get(beam["id"]) or {})


def _split_cranked(
    beam: dict[str, Any],
    placed: list[tuple[dict[str, Any], list[Slot | None]]],
    zones: dict[str, tuple[float, float]],
) -> None:
    """The bar entries of ``beam`` split by their cranks (see :func:`joint_cranks`)."""
    cranked_at: set[str] = set()
    for bar, taken in placed:
        a, c = float(bar["at"]["from"]), float(bar["at"]["to"])
        groups: dict[float, list[tuple[Slot | None, list[dict[str, Any]]]]] = {}
        for slot in taken:
            cranks = []
            for ref, dx in sorted((slot.shift if slot is not None else {}).items()):
                lo, hi = zones.get(ref, (0.0, 0.0))
                if ref in zones and a - 1 <= hi and c + 1 >= lo:
                    cranks.append({"at": ref, "from": round(lo, 1), "to": round(hi, 1),
                                   "offset": dx})  # fmt: skip
            # the length the cranks add, up to the whole mm (bars within a mm share a mark)
            extra = float(math.ceil(path_extra(a, c, cranks) - 1e-6)) if cranks else 0.0
            groups.setdefault(extra, []).append((slot, cranks))
        plain = groups.pop(0.0, [])
        entries = []
        for extra, members in sorted(groups.items()):
            entry = {**bar, "at": dict(bar["at"])}
            entry["count"] = len(members)
            entry["length"] = round(float(bar.get("length") or 0.0) + extra, 1)
            entry["crank"] = extra  # the BBS adds it to the shape's cutting length
            refs = sorted({k["at"] for _, cranks in members for k in cranks})
            most = max(abs(k["offset"]) for _, cranks in members for k in cranks)
            # short (the BBS sheets wrap it); the beam's note says why
            remark = f"cranked {most:.0f} at {', '.join(refs)}"
            entry["remarks"] = f"{bar['remarks']}; {remark}" if bar.get("remarks") else remark
            entry["at"]["slots"] = [[s.x, s.y] for s, _ in members if s is not None]
            entry["at"]["cranks"] = [cranks for _, cranks in members]
            entries.append(entry)
            cranked_at.update(refs)
        if not entries:
            bar["at"]["slots"] = [[s.x, s.y] for s, _ in plain if s is not None]
            continue
        # the first group keeps the entry itself (the laps refer to it), the others follow it
        if plain:
            bar["count"] = len(plain)
            bar["at"]["slots"] = [[s.x, s.y] for s, _ in plain if s is not None]
            bar["at"].pop("cranks", None)
        else:
            first = entries.pop(0)
            bar.clear()
            bar.update(first)
        index = next(i for i, b in enumerate(beam["bars"]) if b is bar)
        beam["bars"][index + 1 : index + 1] = entries
        for lap in beam.get("laps") or []:
            if any(b is bar for b in lap.get("bars") or []):
                lap["bars"] += entries
    if cranked_at:
        beam["notes"].append(
            f"bars cranked at {', '.join(sorted(cranked_at))} to pass inside the column bars, 1 in "
            f"{CRANK_SLOPE:g} outside the joint (practice; the clear spacing of the code pack "
            "taken for crossing bars); their marks are scheduled with the cranks' length"
        )


def _joint_checks(
    element: dict[str, Any], beams: list[dict[str, Any]], out: dict, lim: Limits
) -> list[dict[str, Any]]:
    """The bars of the beams framing into the top of column ``element`` against the column's
    bars and against each other."""
    column = out["columns"].get(element["id"])
    if column is None:
        return []
    slots_c, (px, py), (cr, sr), _, top = column
    col_points = [(px + s.x * cr - s.y * sr, py + s.x * sr + s.y * cr, s.dia) for s in slots_c]
    where = f"joint {element['id']} at {element.get('story') or round(top)}"
    passing: list[tuple[str, tuple[float, float], str, float, float, float, float]] = []
    for beam, geometry, s0, half in _framing(element, beams, out):
        slots_b, (ox, oy), (ux, uy), elev, h, _, top_drop = geometry
        nx, ny = -uy, ux
        for slot in _through(slots_b, s0, half):
            across = slot.x + slot.shift.get(element["id"], 0.0)  # cranked at this joint
            x0 = ox + ux * s0 + nx * across
            y0 = oy + uy * s0 + ny * across
            z = elev - h / 2 + slot.y - (top_drop if slot.face == "top" else 0.0)
            passing.append((beam["id"], (ux, uy), slot.face, slot.dia, x0, y0, z))
    if not passing:
        return []
    checks = []
    # beam bars against the column bars they cross (in plan)
    worst = None
    for beam_id, (ux, uy), face, db, x0, y0, _ in passing:
        for cx, cy, dc in col_points:
            off = abs((cx - x0) * -uy + (cy - y0) * ux)  # across the beam bar's line
            clear = off - (db + dc) / 2
            need = lim.layer(max(db, dc))
            if worst is None or clear - need < worst[0] - worst[1]:
                worst = (clear, need, beam_id, face, db, dc)
    if worst is not None:
        clear, need, beam_id, face, db, dc = worst
        checks.append(
            _check(
                where,
                f"{beam_id} {face} bars Ø{db:g} past the column bars Ø{dc:g}"
                + (" (they clash)" if clear < 0 else ""),
                need,
                clear,
                (_cite("barSpacing") or "the bar spacing") + " taken for crossing bars (practice)",
                "error" if clear < 0 else "warning",
            )
        )
    # beams from two directions: their outer layers at the same level
    for face in ("top", "bottom"):
        by_beam: dict[str, tuple[tuple[float, float], float, float]] = {}
        for beam_id, u, f, db, *_rest, z in passing:
            if f != face:
                continue
            outer = z if face == "bottom" else -z
            known = by_beam.get(beam_id)
            if known is None or outer < (known[1] if face == "bottom" else -known[1]):
                by_beam[beam_id] = (u, z, db)
        ids = sorted(by_beam)
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                (ua, za, da), (ub, zb, dbb) = by_beam[a], by_beam[b]
                angle = math.degrees(math.acos(min(1.0, abs(ua[0] * ub[0] + ua[1] * ub[1]))))
                if angle < PARALLEL_DEG:
                    continue
                gap = abs(za - zb) - (da + dbb) / 2
                checks.append(
                    _check(
                        where,
                        f"{face} bars of {a} and {b} cross at one level"
                        + (" (they clash)" if gap < 0 else "")
                        + f" (Ø{max(da, dbb):g})",
                        0.0,
                        gap,
                        "practice: crossing bars cannot share a level"
                        + (
                            "; Project Settings > Construction > Crossing top bars puts one "
                            "direction in the second layer"
                            if face == "top"
                            else "; one direction goes a bar diameter higher, which the design's "
                            "effective depth must allow"
                        ),
                    )
                )
    return checks


def cage_model(
    model: dict[str, Any], objects: Any, materials: Any = None, check: bool = True
) -> dict[str, Any]:
    """The 3D cages of the detailing ``model``'s beams and columns, with the congestion checks
    (``check``): ``{"schema", "bars": [CageBar json], "checks", "notes", "skipped"}``."""
    types = {o.id: o for o in objects.objects}
    mats = {m.id: m for m in (materials.materials if materials is not None else [])}
    out: dict[str, Any] = {"bars": [], "notes": [], "slots": {}, "columns": {}}
    skipped: dict[str, int] = {}
    beams = []
    for element in model.get("elements") or []:
        kind = element.get("kind")
        type_ = types.get(element.get("type"))
        if kind not in ("beam", "column"):
            skipped[kind] = skipped.get(kind, 0) + 1
            continue
        if type_ is None or getattr(type_, "reinforcement", None) is None:
            continue
        if not element.get("bars"):
            continue
        try:
            if kind == "beam":
                _beam_cage(element, type_, mats, out)
                beams.append(element)
            else:
                _column_cage(element, type_, mats, out)
        except Exception as error:  # noqa: BLE001 - one member does not stop the others
            out["notes"].append(f"{element.get('id')}: not drawn in 3D ({error})")
    checks: list[dict[str, Any]] = []
    lim = limits() if check else None
    if check and lim is None:
        out["notes"].append("The code pack gives no bar spacing limits: congestion not checked.")
    if lim is not None:
        seen: set[str] = set()
        for element in model.get("elements") or []:
            type_id = element.get("type")
            if element.get("id") in out["slots"] and type_id not in seen:
                seen.add(type_id)
                checks += _layer_checks(type_id, out["slots"][element["id"]][0], lim)
            elif element.get("id") in out["columns"] and type_id not in seen:
                seen.add(type_id)
                checks += _column_checks(type_id, out["columns"][element["id"]][0], lim)
        for element in model.get("elements") or []:
            if element.get("kind") == "column":
                checks += _joint_checks(element, beams, out, lim)
    return {
        "schema": SCHEMA_ID,
        "bars": [b.to_json() for b in out["bars"]],
        "checks": checks,
        "notes": out["notes"],
        "skipped": skipped,
    }


def congestion_problems(cages: dict[str, Any], most: int = 10) -> list[str]:
    """The failing congestion checks as lines for the drawings' warnings (at most ``most``)."""
    failing = [c for c in cages.get("checks") or [] if not c.get("ok")]
    lines = [
        f"Bar congestion, {c['where']}: {c['name']}: {c['provided']:g} mm clear, "
        f"{c['required']:g} mm needed ({c['clause']})."
        for c in failing[:most]
    ]
    if len(failing) > most:
        lines.append(
            f"Bar congestion: {len(failing) - most} more (11 Exports/Drawings/{CSV_NAME})."
        )
    return lines


CSV_NAME = "rebar-congestion.csv"


def congestion_csv(cages: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(["Where", "Check", "Required [mm]", "Provided [mm]", "Result", "Clause"])
    for c in cages.get("checks") or []:
        result = "OK" if c.get("ok") else ("CLASH" if c.get("severity") == "error" else "TIGHT")
        writer.writerow([c["where"], c["name"], c["required"], c["provided"], result, c["clause"]])
    return out.getvalue()


def bar_count(cages: dict[str, Any]) -> int:
    return sum(len(b.get("lines") or []) for b in cages.get("bars") or [])


def members_of(cages: dict[str, Any]) -> Iterable[str]:
    return sorted({b["member"] for b in cages.get("bars") or []})
