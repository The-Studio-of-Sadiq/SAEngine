"""Footprint roof geometry: weighted straight skeleton, roof faces, ridges, hips, valleys,
overhangs, shed/gable/hip/mansard/drainage roofs.

All coordinates and lengths are in millimetres [mm], areas in mm², slopes in degrees [°].
The straight-skeleton wavefront solver handles convex polygons (rectangles, triangles, general
convex outlines) and non-convex rectilinear outlines (L-shapes, T-shapes, U-shapes) with arbitrary
per-edge slopes (``0`` for non-sloping gable ends).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from saengine.library.architecture import Roof

RoofLineKind = Literal["ridge", "hip", "valley", "eaves", "rake", "break"]
RoofKind = Literal["flat", "shed", "gable", "hip", "mansard", "complex"]

_EPS = 1e-6
_SNAP = 1e-2  # mm tolerance for snapping wavefront vertices / events
_MIN_AREA = 1.0  # mm²


@dataclass(frozen=True)
class RoofFace:
    """One planar roof face in 3D (vertices in CCW plan order, local z above eaves level)."""

    edge_index: int | None
    slope: float
    vertices: tuple[tuple[float, float, float], ...]
    plan_area: float
    sloped_area: float
    normal: tuple[float, float, float]


@dataclass(frozen=True)
class RoofLine:
    """One edge or skeleton line of a roof (ridge, hip, valley, eaves, rake, mansard break)."""

    kind: RoofLineKind
    start: tuple[float, float, float]
    end: tuple[float, float, float]

    @property
    def length_plan(self) -> float:
        return math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])

    @property
    def length_3d(self) -> float:
        return math.dist(self.start, self.end)


@dataclass(frozen=True)
class RoofGeometry:
    """Computed 3D geometry of a roof."""

    outline: tuple[tuple[float, float], ...]
    faces: tuple[RoofFace, ...]
    lines: tuple[RoofLine, ...]
    plan_area: float
    sloped_area: float
    max_height: float
    kind: RoofKind


# ───────────────────────────── 2D outline & overhang ─────────────────────────────


def _signed_area_2d(pts: list[tuple[float, float]]) -> float:
    area = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return 0.5 * area


def _strip_closing(
    outline: list[list[float]] | list[tuple[float, float]],
) -> list[tuple[float, float]]:
    pts = [(float(p[0]), float(p[1])) for p in outline]
    if len(pts) > 3 and math.dist(pts[0], pts[-1]) < 1e-6:
        pts = pts[:-1]
    return pts


def _normalize_outline(
    roof: Roof,
) -> tuple[list[tuple[float, float]], list[float] | None, list[float]]:
    """Return CCW outline vertices, aligned per-edge slopes (or None), and aligned overhangs."""
    pts = _strip_closing(roof.outline)
    n = len(pts)
    slopes: list[float] | None = None
    if roof.edgeSlopes is not None:
        slopes = [float(s or 0.0) for s in roof.edgeSlopes]
    if roof.edgeOverhangs is not None:
        overhangs = [float(oh) for oh in roof.edgeOverhangs]
    else:
        overhangs = [float(roof.overhang or 0.0)] * n

    if _signed_area_2d(pts) < 0:
        pts = list(reversed(pts))
        if slopes is not None:
            slopes = list(reversed(slopes))
        overhangs = list(reversed(overhangs))
    return pts, slopes, overhangs


def _offset_polygon_outward(
    pts: list[tuple[float, float]], overhangs: list[float]
) -> list[tuple[float, float]]:
    """Offset each edge ``i`` outward (to the right of CCW edge) by ``overhangs[i]``."""
    if not any(oh > 1e-9 for oh in overhangs):
        return pts
    n = len(pts)
    lines: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]] = []
    for i in range(n):
        p = pts[i]
        q = pts[(i + 1) % n]
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy) or 1.0
        tx, ty = dx / length, dy / length
        # Outward normal for CCW polygon is (ty, -tx)
        ox, oy = ty, -tx
        oh = overhangs[i]
        lines.append(((p[0] + ox * oh, p[1] + oy * oh), (tx, ty), (ox, oy)))

    out: list[tuple[float, float]] = []
    for i in range(n):
        p1, t1, _ = lines[(i - 1) % n]
        p2, t2, _ = lines[i]
        det = t1[0] * t2[1] - t1[1] * t2[0]
        if abs(det) <= 1e-9:
            out.append(p2)
        else:
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            s = (dx * t2[1] - dy * t2[0]) / det
            out.append((p1[0] + t1[0] * s, p1[1] + t1[1] * s))
    return out


def effective_outline(roof: Roof) -> list[tuple[float, float]]:
    """The roof's outer plan outline in CCW order including any overhangs [mm]."""
    pts, _, overhangs = _normalize_outline(roof)
    return _offset_polygon_outward(pts, overhangs)


# ───────────────────────────── wavefront straight skeleton ─────────────────────────────


@dataclass(frozen=True)
class _EdgeInfo:
    orig_id: int
    p0: tuple[float, float]
    tangent: tuple[float, float]
    normal: tuple[float, float]
    c: float
    speed: float
    slope: float


@dataclass
class _Node:
    pos: tuple[float, float]
    z: float
    in_edge: _EdgeInfo
    out_edge: _EdgeInfo
    vel: tuple[float, float]
    reflex: bool


def _compute_velocity(e_in: _EdgeInfo, e_out: _EdgeInfo) -> tuple[float, float]:
    n1, s1 = e_in.normal, e_in.speed
    n2, s2 = e_out.normal, e_out.speed
    det = n1[0] * n2[1] - n1[1] * n2[0]
    if abs(det) > 1e-9:
        vx = (s1 * n2[1] - s2 * n1[1]) / det
        vy = (n1[0] * s2 - n2[0] * s1) / det
        return (vx, vy)
    # Parallel edges (collinear same direction or 180-deg anti-parallel)
    dot_t = e_in.tangent[0] * e_out.tangent[0] + e_in.tangent[1] * e_out.tangent[1]
    if dot_t > 0:
        s = 0.5 * (s1 + s2)
        return (s * n1[0], s * n1[1])
    return (0.0, 0.0)


def _make_node(
    pos: tuple[float, float], z: float, in_edge: _EdgeInfo, out_edge: _EdgeInfo
) -> _Node:
    vel = _compute_velocity(in_edge, out_edge)
    t1, t2 = in_edge.tangent, out_edge.tangent
    cross = t1[0] * t2[1] - t1[1] * t2[0]
    return _Node(pos=pos, z=z, in_edge=in_edge, out_edge=out_edge, vel=vel, reflex=cross < -1e-9)


def _edge_length(u: _Node, w: _Node) -> float:
    t = u.out_edge.tangent
    return (w.pos[0] - u.pos[0]) * t[0] + (w.pos[1] - u.pos[1]) * t[1]


def _pt_key(p: tuple[float, float, float]) -> tuple[int, int, int]:
    return (round(p[0] / _SNAP), round(p[1] / _SNAP), round(p[2] / _SNAP))


def _assemble_face_loops(
    segments: list[tuple[tuple[float, float, float], tuple[float, float, float]]],
) -> list[list[tuple[float, float, float]]]:
    """Chain directed 3D half-edges into closed polygon cycles."""
    coords: dict[tuple[int, int, int], list[tuple[float, float, float]]] = {}
    directed: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []
    for p1, p2 in segments:
        k1, k2 = _pt_key(p1), _pt_key(p2)
        if k1 == k2:
            continue
        coords.setdefault(k1, []).append(p1)
        coords.setdefault(k2, []).append(p2)
        directed.append((k1, k2))

    # Drop cancelling opposite pairs (a->b and b->a) produced by zero-area collapses
    edge_counts: dict[tuple[tuple[int, int, int], tuple[int, int, int]], int] = {}
    for pair in directed:
        rev = (pair[1], pair[0])
        if edge_counts.get(rev, 0) > 0:
            edge_counts[rev] -= 1
        else:
            edge_counts[pair] = edge_counts.get(pair, 0) + 1

    canon = {
        k: (
            sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts),
            sum(p[2] for p in pts) / len(pts),
        )
        for k, pts in coords.items()
    }
    adj: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
    for (k1, k2), count in edge_counts.items():
        for _ in range(count):
            adj.setdefault(k1, []).append(k2)

    loops: list[list[tuple[float, float, float]]] = []
    while True:
        start = next((k for k, nxt in adj.items() if nxt), None)
        if start is None:
            break
        cycle: list[tuple[int, int, int]] = [start]
        prev_k: tuple[int, int, int] | None = None
        curr_k = start
        while True:
            outs = adj.get(curr_k)
            if not outs:
                break
            if len(outs) == 1 or prev_k is None:
                nxt_k = outs.pop(0)
            else:
                # Choose tightest CCW turn in XY when multiple faces pinch at one vertex
                p_prev, p_curr = canon[prev_k], canon[curr_k]
                in_ang = math.atan2(p_curr[1] - p_prev[1], p_curr[0] - p_prev[0])

                def turn_key(
                    candidate: tuple[int, int, int],
                    p_curr: tuple[float, ...] = p_curr,
                    in_ang: float = in_ang,
                ) -> float:
                    pc = canon[candidate]
                    out_ang = math.atan2(pc[1] - p_curr[1], pc[0] - p_curr[0])
                    # Back direction is in_ang + pi; sweep clockwise from back = left turn first
                    diff = (in_ang + math.pi - out_ang) % (2 * math.pi)
                    return diff if diff > 1e-9 else 2 * math.pi

                best_idx = min(range(len(outs)), key=lambda idx: turn_key(outs[idx]))
                nxt_k = outs.pop(best_idx)
            if nxt_k == start:
                break
            if nxt_k in cycle:
                # Sub-cycle closed mid-walk
                pos_idx = cycle.index(nxt_k)
                sub = [canon[k] for k in cycle[pos_idx:]]
                if len(sub) >= 3:
                    loops.append(sub)
                cycle = cycle[: pos_idx + 1]
                prev_k, curr_k = (cycle[-2] if len(cycle) >= 2 else None), cycle[-1]
                continue
            cycle.append(nxt_k)
            prev_k, curr_k = curr_k, nxt_k
            if len(cycle) > len(directed) + 4:
                break
        if len(cycle) >= 3:
            loops.append([canon[k] for k in cycle])
    return loops


def _dedup_loop_pts(pts: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    out: list[tuple[float, float, float]] = []
    for p in pts:
        if not out or math.dist(out[-1], p) > _SNAP:
            out.append(p)
    if len(out) >= 2 and math.dist(out[0], out[-1]) <= _SNAP:
        out.pop()
    return out


def _solve_wavefront(
    pts: list[tuple[float, float]],
    slopes: list[float],
    z_offset: float = 0.0,
    max_height: float | None = None,
) -> tuple[
    list[RoofFace],
    list[tuple[RoofLineKind, tuple[float, float, float], tuple[float, float, float]]],
    list[tuple[list[tuple[float, float]], list[float]]],
]:
    """Run weighted straight-skeleton wavefront propagation from ``pts`` (CCW).

    Returns ``(faces, skeleton_lines, surviving_loops)``.
    """
    n = len(pts)
    edge_infos: list[_EdgeInfo] = []
    for i in range(n):
        p = pts[i]
        q = pts[(i + 1) % n]
        dx, dy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(dx, dy) or 1.0
        tx, ty = dx / length, dy / length
        nx, ny = -ty, tx
        slope = float(slopes[i])
        speed = 1.0 / math.tan(math.radians(slope)) if slope > 0 else 0.0
        edge_infos.append(
            _EdgeInfo(
                orig_id=i,
                p0=p,
                tangent=(tx, ty),
                normal=(nx, ny),
                c=nx * p[0] + ny * p[1],
                speed=speed,
                slope=slope,
            )
        )

    init_loop: list[_Node] = []
    half_edges: dict[int, list[tuple[tuple[float, float, float], tuple[float, float, float]]]] = {
        i: [] for i in range(n)
    }
    raw_lines: list[
        tuple[RoofLineKind, tuple[float, float, float], tuple[float, float, float]]
    ] = []
    # Recorded as (p1, p2, edge_a, edge_b) for interior skeleton lines before classification
    skeleton_segs: list[
        tuple[tuple[float, float, float], tuple[float, float, float], _EdgeInfo, _EdgeInfo]
    ] = []

    for i in range(n):
        e_in = edge_infos[(i - 1) % n]
        e_out = edge_infos[i]
        init_loop.append(_make_node(pts[i], z_offset, e_in, e_out))
        p1 = (pts[i][0], pts[i][1], z_offset)
        p2 = (pts[(i + 1) % n][0], pts[(i + 1) % n][1], z_offset)
        half_edges[i].append((p1, p2))
        raw_lines.append(("eaves", p1, p2))

    active_loops: list[list[_Node]] = [init_loop]
    surviving: list[tuple[list[tuple[float, float]], list[float]]] = []
    z = 0.0
    max_steps = 30 * n + 200

    def emit_retire_2(loop: list[_Node]) -> None:
        if len(loop) == 2:
            u, w = loop[0], loop[1]
            p_u = (u.pos[0], u.pos[1], z_offset + z)
            p_w = (w.pos[0], w.pos[1], z_offset + z)
            if math.dist(p_u, p_w) > _SNAP:
                # In CCW order around u.out_edge's face, the top edge runs w -> u
                half_edges[u.out_edge.orig_id].append((p_w, p_u))
                half_edges[w.out_edge.orig_id].append((p_u, p_w))
                skeleton_segs.append((p_u, p_w, u.out_edge, w.out_edge))

    def cleanup_small_loops() -> None:
        kept: list[list[_Node]] = []
        for loop in active_loops:
            if len(loop) <= 1:
                continue
            if len(loop) == 2:
                emit_retire_2(loop)
                continue
            kept.append(loop)
        active_loops[:] = kept

    def advance_all(dz: float) -> None:
        nonlocal z
        if dz <= 1e-12:
            return
        z_old = z_offset + z
        z_new = z_offset + z + dz
        for loop in active_loops:
            for u in loop:
                old_p = (u.pos[0], u.pos[1], z_old)
                new_xy = (u.pos[0] + u.vel[0] * dz, u.pos[1] + u.vel[1] * dz)
                new_p = (new_xy[0], new_xy[1], z_new)
                if math.dist(old_p, new_p) > _SNAP:
                    half_edges[u.in_edge.orig_id].append((old_p, new_p))
                    half_edges[u.out_edge.orig_id].append((new_p, old_p))
                    skeleton_segs.append((old_p, new_p, u.in_edge, u.out_edge))
                u.pos = new_xy
                u.z = z_new
        z += dz

    def collapse_zero_edges() -> bool:
        changed = False
        while True:
            collapsed_any = False
            for loop in active_loops:
                m = len(loop)
                if m <= 2:
                    continue
                for i in range(m):
                    u = loop[i]
                    w = loop[(i + 1) % m]
                    if _edge_length(u, w) <= _SNAP:
                        mid = (0.5 * (u.pos[0] + w.pos[0]), 0.5 * (u.pos[1] + w.pos[1]))
                        merged = _make_node(mid, z_offset + z, u.in_edge, w.out_edge)
                        if i == m - 1:
                            loop[0] = merged
                            loop.pop()
                        else:
                            loop[i] = merged
                            loop.pop(i + 1)
                        collapsed_any = True
                        changed = True
                        break
                if collapsed_any:
                    break
            cleanup_small_loops()
            if not collapsed_any:
                break
        return changed

    def find_next_event() -> tuple[float, str, tuple[Any, ...]] | None:
        best_dz = math.inf
        best_event: tuple[str, tuple[Any, ...]] | None = None

        # 1. Edge collapse events
        for li, loop in enumerate(active_loops):
            m = len(loop)
            for i in range(m):
                u = loop[i]
                w = loop[(i + 1) % m]
                t = u.out_edge.tangent
                l0 = (w.pos[0] - u.pos[0]) * t[0] + (w.pos[1] - u.pos[1]) * t[1]
                ldot = (w.vel[0] - u.vel[0]) * t[0] + (w.vel[1] - u.vel[1]) * t[1]
                if l0 <= _SNAP and ldot <= 1e-9:
                    dz = 0.0
                elif ldot < -1e-9:
                    dz = max(0.0, -l0 / ldot)
                else:
                    continue
                if dz < best_dz - 1e-9:
                    best_dz = dz
                    best_event = ("collapse", (li, i))

        # 2. Split events (reflex vertex hitting non-adjacent edge)
        for li, loop_u in enumerate(active_loops):
            m_u = len(loop_u)
            for i in range(m_u):
                u = loop_u[i]
                if not u.reflex:
                    continue
                for lj, loop_e in enumerate(active_loops):
                    m_e = len(loop_e)
                    for j in range(m_e):
                        if li == lj and (j == i or (j + 1) % m_e == i or j == (i - 1) % m_e):
                            continue
                        a = loop_e[j]
                        b = loop_e[(j + 1) % m_e]
                        e = a.out_edge
                        if e is u.in_edge or e is u.out_edge:
                            continue
                        # Note: if u touches a or b while being 2 hops away, skip if same orig edge
                        dist0 = (
                            e.normal[0] * u.pos[0] + e.normal[1] * u.pos[1] - (e.c + e.speed * z)
                        )
                        denom = e.normal[0] * u.vel[0] + e.normal[1] * u.vel[1] - e.speed
                        if dist0 < -1e-4 or denom >= -1e-9:
                            continue
                        dz = max(0.0, -dist0 / denom)
                        if dz >= best_dz - 1e-9:
                            continue
                        qx = u.pos[0] + u.vel[0] * dz
                        qy = u.pos[1] + u.vel[1] * dz
                        ax = a.pos[0] + a.vel[0] * dz
                        ay = a.pos[1] + a.vel[1] * dz
                        bx = b.pos[0] + b.vel[0] * dz
                        by = b.pos[1] + b.vel[1] * dz
                        tx, ty = e.tangent
                        seg_len = (bx - ax) * tx + (by - ay) * ty
                        if seg_len < -_SNAP:
                            continue
                        proj = (qx - ax) * tx + (qy - ay) * ty
                        if -_SNAP <= proj <= seg_len + _SNAP:
                            best_dz = dz
                            best_event = ("split", (li, i, lj, j, (qx, qy)))

        if best_event is None:
            return None
        return best_dz, best_event[0], best_event[1]

    def apply_split(li: int, i: int, lj: int, j: int, q: tuple[float, float]) -> None:
        loop_u = active_loops[li]
        loop_e = active_loops[lj]
        u = loop_u[i]
        a = loop_e[j]
        b = loop_e[(j + 1) % len(loop_e)]
        e = a.out_edge
        at_a = math.dist(u.pos, a.pos) <= _SNAP or math.dist(q, a.pos) <= _SNAP
        at_b = math.dist(u.pos, b.pos) <= _SNAP or math.dist(q, b.pos) <= _SNAP

        if li == lj:
            m = len(loop_u)
            rotated = loop_u[i:] + loop_u[:i]
            k = (j - i) % m
            if at_a and 1 <= k <= m - 1:
                pos = rotated[k].pos
                n1 = _make_node(pos, z_offset + z, rotated[k].in_edge, rotated[0].out_edge)
                n2 = _make_node(pos, z_offset + z, rotated[0].in_edge, rotated[k].out_edge)
                l1 = [n1, *rotated[1:k]]
                l2 = [n2, *rotated[k + 1 :]]
            elif at_b:
                k_b = (j + 1 - i) % m
                if k_b == 0:
                    return
                pos = rotated[k_b].pos
                n1 = _make_node(pos, z_offset + z, rotated[k_b].in_edge, rotated[0].out_edge)
                n2 = _make_node(pos, z_offset + z, rotated[0].in_edge, rotated[k_b].out_edge)
                l1 = [n1, *rotated[1:k_b]]
                l2 = [n2, *rotated[k_b + 1 :]]
            else:
                w1 = _make_node(u.pos, z_offset + z, e, u.out_edge)
                w2 = _make_node(u.pos, z_offset + z, u.in_edge, e)
                l1 = [w1, *rotated[1 : k + 1]]
                l2 = [w2, *rotated[k + 1 :]]
            active_loops[li] = l1
            active_loops.append(l2)
        else:
            ra = loop_u[i:] + loop_u[:i]
            rb = loop_e[j:] + loop_e[:j]
            if at_a:
                pos = rb[0].pos
                n1 = _make_node(pos, z_offset + z, u.in_edge, rb[0].out_edge)
                n2 = _make_node(pos, z_offset + z, rb[0].in_edge, u.out_edge)
                merged = [n1, *rb[1:], n2, *ra[1:]]
            elif at_b:
                j_b = (j + 1) % len(loop_e)
                rb = loop_e[j_b:] + loop_e[:j_b]
                pos = rb[0].pos
                n1 = _make_node(pos, z_offset + z, u.in_edge, rb[0].out_edge)
                n2 = _make_node(pos, z_offset + z, rb[0].in_edge, u.out_edge)
                merged = [n1, *rb[1:], n2, *ra[1:]]
            else:
                w1 = _make_node(u.pos, z_offset + z, u.in_edge, e)
                w2 = _make_node(u.pos, z_offset + z, e, u.out_edge)
                merged = [w1, *rb[1:], rb[0], w2, *ra[1:]]
            active_loops[li] = merged
            active_loops.pop(lj)
        cleanup_small_loops()

    for _ in range(max_steps):
        cleanup_small_loops()
        if not active_loops:
            break
        if collapse_zero_edges():
            continue
        event = find_next_event()
        if event is None:
            if max_height is not None and z < max_height - 1e-6:
                advance_all(max_height - z)
            break
        dz, kind, payload = event
        if max_height is not None and z + dz >= max_height - 1e-6:
            advance_all(max_height - z)
            collapse_zero_edges()
            break
        advance_all(dz)
        if kind == "collapse":
            collapse_zero_edges()
        else:
            li, i, lj, j, q = payload
            if (
                li < len(active_loops)
                and lj < len(active_loops)
                and i < len(active_loops[li])
                and j < len(active_loops[lj])
            ):
                apply_split(li, i, lj, j, q)
                collapse_zero_edges()

    # If max_height stopped the wavefront early, record surviving loops & break lines
    if active_loops:
        z_top = z_offset + z
        for loop in active_loops:
            if len(loop) < 3:
                emit_retire_2(loop)
                continue
            loop_pts: list[tuple[float, float]] = []
            loop_slopes: list[float] = []
            m = len(loop)
            for idx in range(m):
                u = loop[idx]
                w = loop[(idx + 1) % m]
                p_u = (u.pos[0], u.pos[1], z_top)
                p_w = (w.pos[0], w.pos[1], z_top)
                half_edges[u.out_edge.orig_id].append((p_w, p_u))
                raw_lines.append(("break", p_u, p_w))
                loop_pts.append(u.pos)
                loop_slopes.append(u.out_edge.slope)
            if abs(_signed_area_2d(loop_pts)) > _MIN_AREA:
                surviving.append((loop_pts, loop_slopes))

    # Assemble faces per sloping original edge
    faces: list[RoofFace] = []
    for i, info in enumerate(edge_infos):
        if info.slope <= 0:
            continue
        loops_3d = _assemble_face_loops(half_edges[i])
        tan_s = math.tan(math.radians(info.slope))
        cos_s = math.cos(math.radians(info.slope))
        sin_s = math.sin(math.radians(info.slope))
        nx, ny = info.normal
        normal = (-sin_s * nx, -sin_s * ny, cos_s)
        for loop_pts in loops_3d:
            cleaned = _dedup_loop_pts(loop_pts)
            if len(cleaned) < 3:
                continue
            # Snap each vertex's z onto the exact plane of edge i
            exact_pts: list[tuple[float, float, float]] = []
            for x, y, _ in cleaned:
                dist_in = (x - info.p0[0]) * nx + (y - info.p0[1]) * ny
                exact_pts.append((x, y, z_offset + dist_in * tan_s))
            xy = [(p[0], p[1]) for p in exact_pts]
            signed = _signed_area_2d(xy)
            if abs(signed) < _MIN_AREA:
                continue
            if signed < 0:
                exact_pts.reverse()
            plan_a = abs(signed)
            faces.append(
                RoofFace(
                    edge_index=i,
                    slope=info.slope,
                    vertices=tuple(exact_pts),
                    plan_area=plan_a,
                    sloped_area=plan_a / cos_s,
                    normal=normal,
                )
            )

    # Classify skeleton segments into ridge / hip / valley / rake
    for p1, p2, ea, eb in skeleton_segs:
        if math.dist(p1, p2) <= _SNAP:
            continue
        if abs(p1[2] - p2[2]) < 1.0:
            # Horizontal interior edge
            kind: RoofLineKind = "ridge" if p1[2] > z_offset + 1.0 else "eaves"
            raw_lines.append((kind, p1, p2))
            continue
        if ea.slope <= 0 or eb.slope <= 0:
            raw_lines.append(("rake", p1, p2))
            continue
        # Test whether the dihedral angle between face ea and face eb is convex (hip) or concave (valley)
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        seg_len = math.hypot(dx, dy)
        if seg_len <= 1e-6:
            # Vertical step (should not occur for continuous slopes)
            raw_lines.append(("hip", p1, p2))
            continue
        # The line between faces ea and eb is a hip where the edges turn convexly (left turn from
        # ea's tangent to eb's) and a valley where they turn concavely (reflex corner of the outline).
        cross_t = ea.tangent[0] * eb.tangent[1] - ea.tangent[1] * eb.tangent[0]
        raw_lines.append(("valley" if cross_t < -1e-9 else "hip", p1, p2))

    return faces, raw_lines, surviving


def _dedup_lines(
    lines: list[tuple[RoofLineKind, tuple[float, float, float], tuple[float, float, float]]],
) -> tuple[RoofLine, ...]:
    seen: set[tuple[str, tuple[int, int, int], tuple[int, int, int]]] = set()
    out: list[RoofLine] = []
    for kind, p1, p2 in lines:
        if math.dist(p1, p2) <= _SNAP:
            continue
        k1, k2 = _pt_key(p1), _pt_key(p2)
        pair = (k1, k2) if k1 <= k2 else (k2, k1)
        sig = (kind, pair[0], pair[1])
        if sig in seen:
            continue
        seen.add(sig)
        out.append(RoofLine(kind=kind, start=p1, end=p2))
    return tuple(out)


def _single_plane_roof(
    pts: list[tuple[float, float]], slope: float, direction: float, kind: RoofKind
) -> RoofGeometry:
    """Flat, flat-with-drainage, or legacy single-pitch roof over ``pts`` (CCW)."""
    plan_area = abs(_signed_area_2d(pts))
    if slope <= 0:
        verts = tuple((x, y, 0.0) for x, y in pts)
        face = RoofFace(
            edge_index=None,
            slope=0.0,
            vertices=verts,
            plan_area=plan_area,
            sloped_area=plan_area,
            normal=(0.0, 0.0, 1.0),
        )
        lines = tuple(
            RoofLine("eaves", verts[i], verts[(i + 1) % len(verts)]) for i in range(len(verts))
        )
        return RoofGeometry(
            outline=tuple(pts),
            faces=(face,),
            lines=lines,
            plan_area=plan_area,
            sloped_area=plan_area,
            max_height=0.0,
            kind=kind,
        )
    rad_dir = math.radians(direction)
    ux, uy = math.cos(rad_dir), math.sin(rad_dir)
    rad_s = math.radians(slope)
    tan_s = math.tan(rad_s)
    cos_s = math.cos(rad_s)
    sin_s = math.sin(rad_s)
    projs = [x * ux + y * uy for x, y in pts]
    p_min = min(projs)
    verts = tuple((x, y, (x * ux + y * uy - p_min) * tan_s) for x, y in pts)
    sloped_area = plan_area / cos_s
    normal = (-sin_s * ux, -sin_s * uy, cos_s)
    face = RoofFace(
        edge_index=None,
        slope=slope,
        vertices=verts,
        plan_area=plan_area,
        sloped_area=sloped_area,
        normal=normal,
    )
    lines = tuple(
        RoofLine(
            "eaves"
            if abs(verts[i][2] - verts[(i + 1) % len(verts)][2]) < 1.0 and verts[i][2] < 1.0
            else "rake",
            verts[i],
            verts[(i + 1) % len(verts)],
        )
        for i in range(len(verts))
    )
    return RoofGeometry(
        outline=tuple(pts),
        faces=(face,),
        lines=lines,
        plan_area=plan_area,
        sloped_area=sloped_area,
        max_height=max(v[2] for v in verts),
        kind=kind,
    )


def compute_roof_geometry(roof: Roof) -> RoofGeometry:
    """Compute the 3D faces, ridge/hip/valley/eaves lines, and plan/sloped areas of ``roof``."""
    pts, edge_slopes, overhangs = _normalize_outline(roof)
    outer = _offset_polygon_outward(pts, overhangs)

    # Check whether footprint per-edge slopes are active
    if edge_slopes is None:
        if roof.breakHeight is not None and roof.slope > 0:
            edge_slopes = [float(roof.slope)] * len(outer)
        elif roof.slope > 0:
            return _single_plane_roof(outer, float(roof.slope), float(roof.direction), "shed")
        elif roof.drainageSlope > 0:
            return _single_plane_roof(
                outer, float(roof.drainageSlope), float(roof.direction), "flat"
            )
        else:
            return _single_plane_roof(outer, 0.0, float(roof.direction), "flat")

    if not any(s > 0 for s in edge_slopes):
        if roof.drainageSlope > 0:
            return _single_plane_roof(
                outer, float(roof.drainageSlope), float(roof.direction), "flat"
            )
        return _single_plane_roof(outer, 0.0, float(roof.direction), "flat")

    break_h = roof.breakHeight
    faces, raw_lines, surviving = _solve_wavefront(
        outer, edge_slopes, z_offset=0.0, max_height=break_h
    )

    if break_h is not None and surviving:
        u_slope = float(roof.upperSlope or 0.0)
        for loop_pts, loop_slopes in surviving:
            if u_slope <= 0:
                verts = tuple((x, y, break_h) for x, y in loop_pts)
                pa = abs(_signed_area_2d(loop_pts))
                faces.append(
                    RoofFace(
                        edge_index=None,
                        slope=0.0,
                        vertices=verts,
                        plan_area=pa,
                        sloped_area=pa,
                        normal=(0.0, 0.0, 1.0),
                    )
                )
            else:
                upper_slopes = [u_slope if s > 0 else 0.0 for s in loop_slopes]
                u_faces, u_lines, _ = _solve_wavefront(loop_pts, upper_slopes, z_offset=break_h)
                faces.extend(u_faces)
                raw_lines.extend((kind, p1, p2) for kind, p1, p2 in u_lines if kind != "eaves")

    lines = _dedup_lines(raw_lines)
    plan_area = sum(f.plan_area for f in faces)
    sloped_area = sum(f.sloped_area for f in faces)
    max_h = max((v[2] for f in faces for v in f.vertices), default=0.0)

    sloping_count = sum(1 for s in edge_slopes if s > 0)
    non_sloping_count = len(edge_slopes) - sloping_count
    if break_h is not None:
        kind: RoofKind = "mansard"
    elif sloping_count == 1:
        kind = "shed"
    elif non_sloping_count == 0:
        kind = "hip"
    elif (
        sloping_count == 2
        and not any(ln.kind == "hip" for ln in lines)
        or not any(ln.kind == "hip" for ln in lines)
    ):
        kind = "gable"
    else:
        kind = "complex"

    return RoofGeometry(
        outline=tuple(outer),
        faces=tuple(faces),
        lines=lines,
        plan_area=plan_area,
        sloped_area=sloped_area,
        max_height=max_h,
        kind=kind,
    )
