"""Unbraced lengths, effective length factors and the moment gradient factor Cb of steel members.

Bracing is read from the analysis model. Along a member, a node is a brace point for
displacement in a direction v (the profile's depth direction for buckling about its x-axis,
its width direction for buckling about y and for lateral-torsional buckling) when

- another frame element (not of the same member) meets it with an axis that has a component
  along v (|e · v| >= 0.25: a column braces a beam vertically, a cross beam braces it sideways),
- a shell meets it whose plane contains v (a slab braces a beam sideways and a column in plan,
  a wall braces the members in its plane), or
- the node is restrained in a translation along v (a support), or
- the member is horizontal (a beam) and a column (a vertical frame element) meets the node: a
  beam drawn continuous over interior columns is braced there in every direction, as at its
  ends.

The member's ends are taken as braced in every direction when a frame element or a support
meets them. An end only a shell meets is braced only in the directions the shell braces (its
plane; for lateral-torsional buckling only the flange the slab is attached to, the top one),
and free in the others; an end nothing meets is free in every direction (a cantilever). A
segment with a free end gets K = 2.0 for compression and Cb = 1.0 (BNBC 2020 Part 6 Sec 10.6.1,
p 3853, "For cantilevers or overhangs where the free end is unbraced, Cb = 1.0"): a cantilever
carrying a slab at its tip is free about x and for hogging LTB (bottom flange in compression).

A station at a brace point belongs to both segments that meet there; the checks take the worse
of the two (:meth:`Segments.around_all`).

A slab braces only the flange it is attached to, the top one: lateral-torsional buckling of a
beam with the top flange in compression (sagging) takes the slab's nodes as brace points
(``slab_braces_top_flange``), with the bottom flange in compression (hogging) it does not.

Effective length factor: K = 1.0 (Sec 10.3.1.2.1 for braced frames and shear-wall systems, and
Sec 10.3.2.2.2 for design by first-order analysis, which the member checks flag with its
condition αPr <= 0.5 Py, Eq 6.10.9). Sway moment frames analysed to first order with no
notional loads need K from a sidesway buckling analysis or the alignment chart instead; a
``k`` override per axis is accepted for them (:class:`LengthOptions`). With the direct analysis
method every segment takes the code pack's K (1.0, Sec 10.14.1), overrides and free ends
included (:meth:`MemberLengths.effective` with ``unit_k``).

Cb, Eq 6.10.55 (p 3852): 12.5 Mmax / (2.5 Mmax + 3 MA + 4 MB + 3 MC) Rm <= 3.0, Rm = 1.0
(doubly symmetric members, singly symmetric in single curvature), from the moment diagram of
the segment at its quarter points.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from saengine.fem.derive import pinned_twins

_FRAME_TYPES = {"ElasticBeamColumn", "ForceBeamColumn", "DispBeamColumn", "BeamWithHinges"}
_ALONG = 0.25  # |cos| above which an element or a restraint braces a direction
_VERTICAL = 0.7  # |z| of a unit axis above which a frame element is a column (or post)


@dataclass
class Segments:
    """The brace points of one direction along a member, as positions [m] from its start."""

    points: list[float]
    free_start: bool = False
    free_end: bool = False

    def around_all(self, s: float) -> list[tuple[float, float, bool]]:
        """Every segment holding position ``s``: two at a brace point (the one ending there and
        the one starting there), one elsewhere; each (start, end, has a free end)."""
        pts = self.points
        found = []
        for a, b in itertools.pairwise(pts):
            if a - 1e-9 <= s <= b + 1e-9:
                free = (self.free_start and a == pts[0]) or (self.free_end and b == pts[-1])
                found.append((a, b, free))
        return found or [(pts[0], pts[-1], self.free_start or self.free_end)]

    def around(self, s: float) -> tuple[float, float, bool]:
        """The segment holding position ``s`` (at a brace point, the longer of the two, a free
        one first): (start, end, has a free end)."""
        return max(self.around_all(s), key=lambda g: (g[2], g[1] - g[0]))

    def longest(self) -> float:
        return max((b - a for a, b in itertools.pairwise(self.points)), default=0)


@dataclass
class LengthOptions:
    """Overrides: ``k`` per axis ("x", "y", "z"); ``slab_braces_top_flange``; ``unbraced``:
    unbraced lengths [m] per axis ("x", "y": compression buckling) and "ltb" (the compression
    flange, both flanges), which replace the brace points found in the model by points evenly
    spaced at that length (the design overwrites, :mod:`saengine.design.overwrites`);
    ``sources``: where an overwritten value came from ("member", "type"; keys "kx", "ky",
    "Lx", "Ly", "Lb"), for the notes."""

    k: dict[str, float] = field(default_factory=dict)
    slab_braces_top_flange: bool = True
    unbraced: dict[str, float] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)


@dataclass
class MemberLengths:
    """How a member is braced: brace points per direction and the effective length factors."""

    length: float  # m
    x: Segments  # buckling about the profile x-axis (displacement along its depth)
    y: Segments  # buckling about y (displacement along the width), torsion
    ltb_top: Segments  # lateral-torsional buckling, top flange in compression
    ltb_bottom: Segments  # bottom flange in compression
    k: dict[str, float] = field(default_factory=lambda: {"x": 1.0, "y": 1.0, "z": 1.0})
    notes: list[str] = field(default_factory=list)
    #: Where overwritten values came from (:attr:`LengthOptions.sources`).
    sources: dict[str, str] = field(default_factory=dict)

    def overwritten(self, options: LengthOptions | None) -> MemberLengths:
        """These lengths with the unbraced length overwrites of ``options`` applied (brace
        points evenly spaced at each given length, the free ends kept)."""
        if options is None or not (options.unbraced or options.sources):
            return self
        given = options.unbraced
        notes = list(self.notes)

        def spaced(seg: Segments, lu: float | None, what: str) -> Segments:
            if lu is None or lu <= 0:
                return seg
            if lu >= self.length - 1e-9:
                if lu > self.length + 1e-6:
                    notes.append(
                        f"the unbraced length {what} ({lu * 1e3:.0f} mm) is longer than the "
                        f"member: its length {self.length * 1e3:.0f} mm taken"
                    )
                return Segments([0.0, self.length], seg.free_start, seg.free_end)
            count = int(np.ceil(self.length / lu - 1e-9))
            points = [min(n * lu, self.length) for n in range(count)] + [self.length]
            return Segments(sorted(set(points)), seg.free_start, seg.free_end)

        ltb = given.get("ltb")
        return MemberLengths(
            length=self.length,
            x=spaced(self.x, given.get("x"), "about x"),
            y=spaced(self.y, given.get("y"), "about y"),
            ltb_top=spaced(self.ltb_top, ltb, "for LTB"),
            ltb_bottom=spaced(self.ltb_bottom, ltb, "for LTB"),
            k=dict(self.k),
            notes=notes,
            sources={**self.sources, **options.sources},
        )

    @classmethod
    def simple(
        cls,
        length: float,
        x: Sequence[float] | None = None,
        y: Sequence[float] | None = None,
        ltb: Sequence[float] | None = None,
        k: dict[str, float] | None = None,
        cantilever: bool = False,
    ) -> MemberLengths:
        """A member ``length`` m long braced at its ends and at the given intermediate
        positions [m] (``ltb`` defaults to ``y``); ``cantilever``: the far end is free."""

        def seg(points: Sequence[float] | None) -> Segments:
            inner = sorted(p for p in (points or []) if 0 < p < length)
            return Segments([0.0, *inner, length], free_end=cantilever)

        y_seg = seg(y)
        return cls(
            length,
            seg(x),
            y_seg,
            seg(ltb) if ltb is not None else y_seg,
            seg(ltb) if ltb is not None else y_seg,
            {"x": 1.0, "y": 1.0, "z": 1.0, **(k or {})},
        )

    def effective(
        self, axis: str, s: float, unit_k: float | None = None
    ) -> tuple[float, float, bool]:
        """(K, L [mm], free end) for buckling about ``axis`` ("x", "y", "z") at ``s`` [m].
        ``unit_k``: the K of every segment, free ends and overrides included (the direct
        analysis method's K = 1.0, :mod:`saengine.design.steel.stability`)."""
        segments = self.x if axis == "x" else self.y
        k0 = self.k.get(axis, 1.0) if unit_k is None else unit_k
        best = (k0, 0.0, False)
        for a, b, free in segments.around_all(s):
            k = max(k0, 2.0) if free and unit_k is None else k0
            if k * (b - a) * 1e3 > best[0] * best[1]:
                best = (k, (b - a) * 1e3, free)
        return best


def cb_factor(m_max: float, m_a: float, m_b: float, m_c: float, rm: float = 1.0) -> float:
    """Cb of Eq 6.10.55 from the absolute moments: maximum, quarter, centre, three-quarter."""
    m_max, m_a, m_b, m_c = abs(m_max), abs(m_a), abs(m_b), abs(m_c)
    if m_max <= 0:
        return 1.0
    return min(3.0, 12.5 * m_max / (2.5 * m_max + 3 * m_a + 4 * m_b + 3 * m_c) * rm)


def cb_from_diagram(s: np.ndarray, m: np.ndarray, start: float, end: float) -> float:
    """Cb of the segment [start, end] of the moment diagram ``m`` at positions ``s`` (sorted)."""
    if end - start <= 1e-9 or len(s) < 2:
        return 1.0
    inside = (s >= start - 1e-9) & (s <= end + 1e-9)
    if not inside.any():
        return 1.0
    m_max = float(np.max(np.abs(m[inside])))
    quarter = [float(np.interp(start + f * (end - start), s, m)) for f in (0.25, 0.5, 0.75)]
    return cb_factor(m_max, *quarter)


# ────────────────────────────────── from the model ──────────────────────────────────


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _frame_axis(points: Sequence[np.ndarray]) -> tuple[np.ndarray, np.ndarray, float]:
    """The member's axis through the two points farthest apart, from the lower one (then the
    one with the smaller x, y): (origin, unit axis, length)."""
    best = (0, 0, -1.0)
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d = float(np.linalg.norm(points[i] - points[j]))
            if d > best[2] + 1e-9:
                best = (i, j, d)
    a, b = points[best[0]], points[best[1]]
    if tuple(np.round(b[[2, 0, 1]], 6)) < tuple(np.round(a[[2, 0, 1]], 6)):
        a, b = b, a
    length = max(best[2], 0.0)
    return a, (_unit(b - a) if length > 0 else np.array([1.0, 0.0, 0.0])), length


def member_lengths(
    project: dict[str, Any],
    pieces: Sequence[Any],
    turned: bool = False,
    options: LengthOptions | None = None,
) -> MemberLengths:
    """The bracing of the member made of the analysis elements ``pieces`` (each with ``id``,
    ``name``, ``axes``, ``depth_along_z``, ``start`` and ``end`` as :class:`saengine.design.
    check._Piece`) in the OpenSees Studio ``project`` (``nodes``, ``elements``)."""
    options = options or LengthOptions()
    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    restraint = {n["id"]: n.get("restraint") or [False] * 6 for n in project.get("nodes", [])}
    by_id = {e["id"]: e for e in project.get("elements", [])}
    # A pinned member end (a simple connection) is a twin node tied to the joint's node: what
    # meets the member there meets it at the joint.
    twins = pinned_twins(project)
    base = pieces[0].name.split("#")[0]
    frames: dict[int, list[np.ndarray]] = {}
    shells: dict[int, list[np.ndarray]] = {}
    for e in project.get("elements", []):
        nodes = e.get("nodes", [])
        name = (e.get("name") or "").split("#")[0]
        if e.get("type") in _FRAME_TYPES and len(nodes) == 2:
            if name == base or name.endswith("/embed"):
                continue
            a, b = coords.get(nodes[0]), coords.get(nodes[1])
            if a is None or b is None:
                continue
            direction = _unit(b - a)
            for n in nodes:
                frames.setdefault(twins.get(n, n), []).append(direction)
        elif e.get("type") == "Shell" and len(nodes) >= 3:
            p = [coords[n] for n in nodes[:3] if n in coords]
            if len(p) < 3:
                continue
            normal = _unit(np.cross(p[1] - p[0], p[2] - p[0]))
            for n in nodes:
                shells.setdefault(twins.get(n, n), []).append(normal)

    # The member's nodes along its axis.
    ends: list[tuple[int, np.ndarray]] = []
    for piece in pieces:
        nodes = by_id.get(piece.id, {}).get("nodes", [])
        for n in nodes[:2]:
            if n in coords:
                ends.append((twins.get(n, n), coords[n]))
    if not ends:
        start = np.asarray(pieces[0].start, dtype=float)
        end = np.asarray(pieces[-1].end, dtype=float)
        length = float(np.linalg.norm(end - start))
        return MemberLengths.simple(length, k=options.k).overwritten(options)
    origin, axis, length = _frame_axis([p for _, p in ends])
    position = {n: float((p - origin) @ axis) for n, p in ends}

    first = pieces[0]
    along_z = first.depth_along_z != turned
    depth = np.asarray(first.axes[2 if along_z else 1], dtype=float)
    width = np.asarray(first.axes[1 if along_z else 2], dtype=float)

    horizontal = abs(float(axis[2])) < _VERTICAL

    def supported(n: int) -> bool:
        """A horizontal member meeting a column (a vertical frame element) at an interior
        node: braced there in every direction, as at its ends (the connection to the column
        holds the section against twist and sideways movement)."""
        if not horizontal:
            return False
        return any(abs(float(e[2])) >= _VERTICAL for e in frames.get(n, []))

    def braced(n: int, v: np.ndarray, with_shells: bool) -> bool:
        if supported(n):
            return True
        if any(abs(float(e @ v)) >= _ALONG for e in frames.get(n, [])):
            return True
        r = restraint.get(n, [False] * 6)
        if any(r[k] and abs(float(v[k])) >= _ALONG for k in range(3)):
            return True
        return with_shells and any(abs(float(nn @ v)) < _ALONG for nn in shells.get(n, []))

    def end_braced(n: int, v: np.ndarray, with_shells: bool) -> bool:
        """An end is braced in every direction when a frame element or a support meets it;
        a shell alone braces it only in the directions in its plane (and, for lateral-
        torsional buckling, only the flange it is attached to: ``with_shells``)."""
        if frames.get(n) or any(restraint.get(n, [False] * 6)[:3]):
            return True
        return with_shells and any(abs(float(nn @ v)) < _ALONG for nn in shells.get(n, []))

    node_ids = sorted(set(position), key=position.get)
    start_node, end_node = node_ids[0], node_ids[-1]
    any_free: list[str] = []

    def segments(v: np.ndarray, with_shells: bool, what: str) -> Segments:
        inner = [
            position[n]
            for n in node_ids[1:-1]
            if braced(n, v, with_shells) and 1e-6 < position[n] < length - 1e-6
        ]
        free_start = not end_braced(start_node, v, with_shells)
        free_end = not end_braced(end_node, v, with_shells)
        if free_start or free_end:
            any_free.append(what)
        return Segments([0.0, *sorted(inner), length], free_start, free_end)

    slab_top = options.slab_braces_top_flange
    x = segments(depth, True, "about x")
    y = segments(width, True, "about y")
    ltb_top = segments(width, slab_top, "LTB with the top flange in compression")
    ltb_bottom = segments(width, False, "LTB with the bottom flange in compression")
    notes = []
    if any_free:
        notes.append(
            "a free end (cantilever) for "
            + ", ".join(any_free)
            + ": K = 2.0 for compression, Cb = 1.0 for LTB (Sec 10.6.1)"
        )
    return MemberLengths(
        length=length,
        x=x,
        y=y,
        ltb_top=ltb_top,
        ltb_bottom=ltb_bottom,
        k={"x": 1.0, "y": 1.0, "z": 1.0, **options.k},
        notes=notes,
    ).overwritten(options)


def positions(pieces: Sequence[Any], stations: int) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Each station's position [m] along the member (from its lower end, as
    :func:`member_lengths` measures them) and
    its (piece index, station index), sorted along the member."""
    points = [np.asarray(p.start, dtype=float) for p in pieces] + [
        np.asarray(p.end, dtype=float) for p in pieces
    ]
    origin, axis, _ = _frame_axis(points)
    found: list[tuple[float, int, int]] = []
    for p, piece in enumerate(pieces):
        a = float((np.asarray(piece.start, dtype=float) - origin) @ axis)
        b = float((np.asarray(piece.end, dtype=float) - origin) @ axis)
        for k in range(stations):
            found.append((a + (b - a) * k / max(stations - 1, 1), p, k))
    found.sort()
    return np.array([f[0] for f in found]), [(f[1], f[2]) for f in found]


def slenderness_note(lengths: MemberLengths) -> str:
    def text(seg: Segments) -> str:
        return f"{seg.longest():.2f} m"

    return (
        f"unbraced lengths: about x {text(lengths.x)}{source_tag(lengths, 'Lx')}, about y "
        f"{text(lengths.y)}{source_tag(lengths, 'Ly')}, LTB {text(lengths.ltb_top)} (top flange "
        f"in compression) / {text(lengths.ltb_bottom)} (bottom){source_tag(lengths, 'Lb')}; "
        f"K = {lengths.k.get('x', 1):g}{source_tag(lengths, 'kx')} / "
        f"{lengths.k.get('y', 1):g}{source_tag(lengths, 'ky')}"
        + (f"; {'; '.join(lengths.notes)}" if lengths.notes else "")
    )


def source_tag(lengths: MemberLengths, key: str) -> str:
    """ " (overwrite)" or " (type overwrite)" when the value ``key`` ("kx", "ky", "Lx", "Ly",
    "Lb") was overwritten, else ""."""
    return {"member": " (overwrite)", "type": " (type overwrite)"}.get(
        lengths.sources.get(key, ""), ""
    )


__all__ = [
    "LengthOptions",
    "MemberLengths",
    "Segments",
    "cb_factor",
    "cb_from_diagram",
    "member_lengths",
    "positions",
    "slenderness_note",
    "source_tag",
]
