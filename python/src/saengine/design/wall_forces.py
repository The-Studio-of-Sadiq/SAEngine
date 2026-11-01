"""Wall pier and spandrel forces from the shell model (section cuts, as ETABS piers/spandrels).

A structural wall of 06 BIM (:class:`saengine.library.bim.WallElement`) is a surface of shells
in the analysis model (:func:`saengine.fem.derive.derive_fem`): its shells are the elements
named after the wall (``"W1"``, ``"W1#2"`` ...), meshed around its openings
(``additions.wallOpenings``). Per storey (the band of the wall between two consecutive levels
of ``building.stories``, clipped to the wall's bottom and top) the wall is split along its
length by the openings that reach into the band:

- **piers**: the parts between openings or an opening and a wall end, full storey height (the
  shells whose centroid lies in the part, beside the openings);
- **spandrels**: the parts above and below each opening (its width; from the opening's head
  to the band's top, from the band's bottom to its sill);
- **sections**: the whole wall in the band, cut at the band's bottom and top levels. Under a
  window the wall is continuous at the floor: the piers' bottom cuts carry only their own
  lengths, the sill wall (the spandrel below) the rest, through its bottom edge (its
  ``edge`` cut); the section is their sum, the critical section at a wall's base.

Only an opening that reaches over :data:`MIN_OPENING` of the band's height splits it into
piers (doors, windows); a smaller one (a duct of 07 MEP, a ventilator) stays a hole in the
part it lies in (``holes``), its shells left in the part.

**Section cuts.** At the bottom, middle and top of each pier (horizontal cuts) and at the left
end, middle and right end of each spandrel (vertical cuts) the resultant is the sum of the
shells' nodal forces at the nodes of the cut, from the shells on one side: a free body, as
ETABS forms its pier forces. The nodal forces are the solver's (the shells' resisting forces,
``element_forces``, 6 per node in global axes), so the cut is in exact equilibrium with the
loads (the shells' stresses at their integration points are not: summed along a line they are
off by the discretisation). A cut at the part's edge (a storey level, an opening edge) takes
the shells of the part and their nodes on the edge; the middle cut the shells of the part on
the far side of the middle (by centroid) and their nodes shared with the near side, a cut
along element edges near the middle (the moment is taken about the cut's centre, so the
small offset of the edges only moves where the forces act, not the statics). It generalises
:func:`saengine.design.slender._shell_cut` (one shell's mean forces over its width, force
only, for the storey shear) to moments and partial sections. Loads applied at the nodes of a
cut belong to the part below it (bottom cut: the storey below, or the support; top cut: the
floor's loads on the wall are in its top cut).

The temperature case's fixed-end forces (:mod:`saengine.fem.thermal`, given as shell stress
corrections) are turned into nodal forces by ∫ Bᵀ σ dA over each shell (membrane by the
bilinear or linear shape functions, bending moments as nodal couples ``e3 × (M ∇N)``), which
reproduces the solver's nodal forces from its own stresses (tested).

**Sign convention.** The resultant is the force and moment of the part above the cut (pier) or
on the end side of the cut (spandrel) on the other part, about the centre of the cut, in the
local axes: pier 1 = up, 2 = along the wall (start to end), 3 = 1 × 2 (normal of the wall);
spandrel 1 = along the wall, 2 = up, 3 = 1 × 2. ``P`` is the axial force, compression
positive (``-F·e1``); ``V2 = F·e2`` (in-plane shear), ``V3 = F·e3`` (out-of-plane shear),
``T = M·e1``, ``M2 = M·e2`` (out-of-plane bending), ``M3 = M·e3`` (in-plane bending). For a
pier ``M3 > 0`` compresses its end-side edge (towards the wall's end) and ``M2 > 0`` its
``-e3`` face. Units: kN and kN·m; lengths and elevations in mm.

**Combinations** (:mod:`saengine.fem.combinations`): the cut is linear in the nodal forces, so
each static case's resultant is found once and a combination is the factored sum
(:func:`saengine.fem.combinations.variants`). A response spectrum combination (envelope parts
RX, RY, AX, AY) is ``S ± E`` per sign pattern, named ``"<name> [<label>]"`` as the members'
(the ``frame`` sign groups: P with T, V2 with M3, V3 with M2), with E the pier's own modal
resultant combined over the modes: for each mode the cut of the modal-force run's shell forces
(:class:`saengine.fem.seismic_design.SeismicForces`, the static response to ω²·M·u of each
mode), combined by the response spectrum case's rule (CQC or SRSS,
:func:`saengine.fem.seismic_design.combine`) and scaled (Sec 2.5.9.4), the accidental torsion
cases in absolute value. BNBC 2020 Part 6 Sec 2.5.9.4 (p. 635): every response quantity is the
combination of its modal values; the pier forces are not formed from the shells' combined
peaks (which have no common sign and would not equilibrate).

Units of the analysis model: m, N, N·m.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

#: Lengths in the building model are mm, the analysis model m.
MM = 1e-3
#: Tolerance on positions [m].
_TOL = 1e-6
#: Parts shorter or lower than this are not piers or spandrels [mm].
MIN_PART = 1.0
#: An opening splits a storey band of a wall into piers (with spandrels over and under it)
#: when its height within the band is at least this fraction of the band's height: a door or
#: a window does, a duct or a small hole (07 MEP's, a ventilator) stays a hole in its pier, as
#: an ETABS user would leave it in the pier's label. ``wall_forces(min_opening=...)``.
MIN_OPENING = 0.25
#: Order of a resultant (the frame section forces' order N Vy Vz T My Mz, so the response
#: spectrum sign patterns of the frames apply: P with T, V2 with M3, V3 with M2).
COMPONENTS = ("P", "V2", "V3", "T", "M2", "M3")
#: The ``frame`` sign groups of :data:`saengine.fem.combinations.SIGN_GROUPS`.
SIGN_KIND = "frame"
#: Pier cuts (horizontal) and spandrel cuts (vertical).
PIER_CUTS = ("bottom", "middle", "top")
SPANDREL_CUTS = ("left", "middle", "right")
CLAUSE_RS = "BNBC 2020 Part 6 Sec 2.5.9.4 (p. 635)"

_UP = np.array([0.0, 0.0, 1.0])

#: Nodal forces of a shell: (nodes, 6) [N, N·m, global], or None for none.
NodalForces = Callable[[int], "np.ndarray | None"]


# ─────────────────────────────────────── geometry ───────────────────────────────────────


@dataclass(eq=False)  # compared by identity (a wall can have thousands of shells)
class _ShellGeo:
    id: int
    nodes: list[int]
    points: list[np.ndarray]  # m
    centroid: np.ndarray


@dataclass
class _Cut:
    """A section cut: its centre and local axes, and per shell of the free body the indices of
    its nodes on the cut; ``sign`` -1 when the free body is the part whose force is taken (on
    the + side: above, or the end side), +1 when it is the other part."""

    centre: np.ndarray
    axes: tuple[np.ndarray, np.ndarray, np.ndarray]  # local 1, 2, 3 (global unit vectors)
    terms: list[tuple[_ShellGeo, list[int]]]
    sign: float

    def resultant(self, forces_of: NodalForces) -> np.ndarray:
        """[P, V2, V3, T, M2, M3] [N, N·m] of the shells' nodal forces ``forces_of(id)``."""
        terms = self.__dict__.get("_arms")
        if terms is None:
            # Per shell the indices of its nodes on the cut and their arms from the centre,
            # the same for every case (a cut is read for all of them).
            terms = self._arms = [
                (s, np.asarray(ks, dtype=int), np.array([s.points[k] - self.centre for k in ks]))
                for s, ks in self.terms
            ]
        rows, arms = [], []
        for shell, indices, arm in terms:
            found = forces_of(shell.id)
            if found is None:
                continue
            f = np.asarray(found, dtype=float).reshape(-1, 6)
            if len(f) != len(shell.nodes):
                continue
            rows.append(f[indices])
            arms.append(arm)
        force, moment = np.zeros(3), np.zeros(3)
        if rows:
            f, arm = np.concatenate(rows), np.concatenate(arms)
            # Added up node by node in order, as one sum after the other (cumsum, not sum).
            force = np.cumsum(np.vstack([force, f[:, :3]]), axis=0)[-1]
            moment = np.cumsum(np.vstack([moment, np.cross(arm, f[:, :3]) + f[:, 3:]]), axis=0)[-1]
        force, moment = self.sign * force, self.sign * moment
        e1, e2, e3 = self.axes
        return np.array(
            [-force @ e1, force @ e2, force @ e3, moment @ e1, moment @ e2, moment @ e3]
        )


def _cut(
    shells: list[_ShellGeo],
    centre: np.ndarray,
    normal: np.ndarray,
    axes: tuple[np.ndarray, np.ndarray, np.ndarray],
    side: float,
    others: list[_ShellGeo] | None = None,
) -> _Cut | None:
    """The cut of a part (``shells``) at the plane through ``centre`` normal to ``normal`` (in
    the wall's plane, pointing to the part whose force is taken). ``side`` +1: the part lies on
    the + side of the plane (bottom of a pier, left end of a spandrel), -1 on the - side, 0:
    the plane runs through the part (its middle). ``others``: the wall's other shells, whose
    nodes shared with the part across the plane are on the cut (where the plane is not a line
    of nodes: a spandrel's end, a storey level inside a wall meshed over several storeys)."""

    def offset(p: np.ndarray) -> float:
        return float((p - centre) @ normal)

    if side == 0:
        far = [s for s in shells if offset(s.centroid) > 0]
        near = {n for s in shells if offset(s.centroid) <= 0 for n in s.nodes}
        terms = [(s, [k for k, n in enumerate(s.nodes) if n in near]) for s in far]
        terms = [(s, ks) for s, ks in terms if ks]
        return _Cut(centre, axes, terms, -1.0) if terms and near else None
    # The nodes on the plane, and those the part shares with the wall's other shells across
    # it (an edge inside the wall, e.g. a spandrel's end, need not be a line of nodes).
    across = {n for s in others or [] if side * offset(s.centroid) < 0 for n in s.nodes}
    terms = [
        (s, [k for k, p in enumerate(s.points) if abs(offset(p)) <= _TOL or s.nodes[k] in across])
        for s in shells
    ]
    terms = [(s, ks) for s, ks in terms if ks]
    return _Cut(centre, axes, terms, -1.0 if side > 0 else 1.0) if terms else None


@dataclass
class _Part:
    kind: str  # "pier" | "spandrel"
    name: str
    wall: Any
    storey: Any
    band: tuple[float, float]  # mm
    span: tuple[float, float]  # along the wall, mm
    height: tuple[float, float]  # mm (a spandrel's own bottom and top)
    shells: list[_ShellGeo]
    thickness: float  # mm
    cuts: dict[str, _Cut]
    label: str = ""
    openings: list[str] = field(default_factory=list)
    position: str = ""
    #: A spandrel's cut at the band's level it stands on (below) or reaches (above), in the
    #: pier axes (1 up, 2 along the wall, 3 normal), keyed "bottom" or "top".
    edge: dict[str, _Cut] = field(default_factory=dict)
    #: The openings too small to split the wall that lie in the part.
    holes: list[str] = field(default_factory=list)
    #: A section: its solid intervals along the wall at its bottom and top level [mm].
    segments: dict[str, list[tuple[float, float]]] = field(default_factory=dict)


def _intervals(openings: list[tuple[float, float, str]], length: float) -> list[tuple]:
    """Solid intervals of [0, length] beside the (merged) opening extents."""
    merged: list[list[Any]] = []
    for a, b, oid in sorted(openings):
        if merged and a <= merged[-1][1] + MIN_PART:
            merged[-1][1] = max(merged[-1][1], b)
            merged[-1][2].append(oid)
        else:
            merged.append([a, b, [oid]])
    solid, at = [], 0.0
    for a, b, _ in merged:
        if a - at > MIN_PART:
            solid.append((at, min(a, length)))
        at = max(at, b)
    if length - at > MIN_PART:
        solid.append((at, length))
    return solid


def _bands(building: Any, wall: Any) -> list[tuple[float, float, Any, Any]]:
    """The wall's storey bands (mm): (bottom, top, story at the bottom, story at the top)."""
    stories = sorted(building.stories, key=lambda s: float(s.elevation))
    levels = [(float(s.elevation), s) for s in stories]
    low, high = float(wall.bottom), float(wall.top)
    cuts = sorted({low, high, *(z for z, _ in levels if low < z < high)})
    out = []
    for z0, z1 in itertools.pairwise(cuts):
        if z1 - z0 <= MIN_PART:
            continue
        below = next((s for z, s in reversed(levels) if z <= z0 + MIN_PART), None)
        above = next((s for z, s in levels if z >= z1 - MIN_PART), None)
        out.append((z0, z1, below, above))
    return out


def _splits(
    sill: float, head: float, z0: float, z1: float, oid: str, min_opening: float, ignore: set
) -> bool:
    """Whether an opening reaching into the band [z0, z1] splits the wall there into piers:
    its height within the band is at least ``min_opening`` x the band's height (a door, a
    window; not a duct or a small hole, which stays a hole in its pier), and it is not in
    ``ignore``."""
    within = min(head, z1) - max(sill, z0)
    return oid not in ignore and within > max(MIN_PART, min_opening * (z1 - z0) - MIN_PART)


def _segments(
    own: list[tuple[float, float, str, float, float]], z: float, length: float
) -> list[tuple[float, float]]:
    """The solid intervals of the wall along its length at the level ``z`` [mm]: beside every
    opening that the level crosses or touches (a door standing on it, a window up to it)."""
    covering = [
        (o0, min(o1, length), oid)
        for o0, o1, oid, sill, head in own
        if sill - MIN_PART <= z <= head + MIN_PART
    ]
    return _intervals(covering, length)


def _holes_in(
    holes: list[tuple[float, float, str, float, float]],
    s0: float,
    s1: float,
    h0: float,
    h1: float,
) -> list[str]:
    """The ids of the holes (along, id, extent in the band) whose middle lies in the part."""
    return [
        oid
        for o0, o1, oid, lo, hi in holes
        if s0 - MIN_PART <= (o0 + o1) / 2 <= s1 + MIN_PART
        and h0 - MIN_PART <= (lo + hi) / 2 <= h1 + MIN_PART
    ]


def _others(members: list[_ShellGeo], pool: list[_ShellGeo]) -> list[_ShellGeo]:
    """The shells of ``pool`` not in ``members`` (by identity)."""
    mine = {id(g) for g in members}
    return [g for g in pool if id(g) not in mine]


def _point(start: np.ndarray, along: np.ndarray, s: float, z: float) -> np.ndarray:
    """The point ``s`` along the wall at the elevation ``z`` [mm] (start at elevation 0) [m]."""
    return start + along * (s * MM) + _UP * (z * MM)


def _parts(
    project: dict[str, Any],
    building: Any,
    notes: list[str],
    min_opening: float = MIN_OPENING,
    ignore: Iterable[str] = (),
) -> list[_Part]:
    from saengine.library.bim import WallElement

    ignored = set(ignore)
    xyz = {int(n["id"]): np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    sections = {int(s["id"]): s for s in project.get("sections", [])}
    by_wall: dict[str, list[tuple[_ShellGeo, float]]] = {}
    for e in project.get("elements", []):
        if e.get("type") != "Shell":
            continue
        nodes = [int(n) for n in e.get("nodes", [])]
        if len(nodes) < 3 or any(n not in xyz for n in nodes):
            continue
        points = [xyz[n] for n in nodes]
        geo = _ShellGeo(int(e["id"]), nodes, points, np.mean(points, axis=0))
        h = float(sections.get(int(e.get("section_id", -1)), {}).get("h", 0.0)) / MM
        source = str(e.get("name") or e["id"]).split("#")[0]
        by_wall.setdefault(source, []).append((geo, h))
    openings: dict[str, list[Any]] = {}
    for o in building.additions.wallOpenings:
        openings.setdefault(o.host, []).append(o)

    parts: list[_Part] = []
    for wall in building.elements:
        if not isinstance(wall, WallElement) or wall.id not in by_wall:
            continue
        start = np.array([*wall.start, 0.0], dtype=float) * MM
        run = np.array([*wall.end, 0.0], dtype=float) * MM - start
        length = float(np.linalg.norm(run)) / MM
        if length < MIN_PART:
            continue
        along = run / (length * MM)
        normal = np.cross(_UP, along)
        pier_axes = (_UP, along, normal)
        spandrel_axes = (along, _UP, np.cross(along, _UP))
        shells = [g for g, _ in by_wall[wall.id]]
        thickness = max((h for _, h in by_wall[wall.id]), default=0.0)
        own = wall_openings_of(openings.get(wall.id, []), float(wall.bottom))
        # Positions along the wall and heights [mm] of the shells' centroids, once.
        s_at = {id(g): float((g.centroid - start) @ along) / MM for g in shells}
        z_at = {id(g): float(g.centroid[2]) / MM for g in shells}

        for z0, z1, below, above in _bands(building, wall):
            label = f"{_story_name(below, z0)} to {_story_name(above, z1)}"
            storey = above.id if above is not None else f"{z1:g}"
            height = z1 - z0
            in_band = [g for g in shells if z0 - MIN_PART < z_at[id(g)] < z1 + MIN_PART]
            # The wall's shells near the band (one band height either side): those across a
            # cut's plane when it is not a line of nodes. Not the whole wall: a tall core.
            near = [g for g in shells if z0 - height < z_at[id(g)] < z1 + height]
            band_ids = {id(g) for g in in_band}
            outside = [g for g in near if id(g) not in band_ids]
            reach = [
                (o0, min(o1, length), oid, sill, head)
                for o0, o1, oid, sill, head in own
                if min(head, z1) - max(sill, z0) > MIN_PART
            ]
            split = [o for o in reach if _splits(o[3], o[4], z0, z1, o[2], min_opening, ignored)]
            # The holes' extent within the band.
            holes = [
                (a, b, i, max(lo, z0), min(hi, z1))
                for a, b, i, lo, hi in reach
                if (a, b, i, lo, hi) not in split
            ]
            solid = _intervals([(o0, o1, oid) for o0, o1, oid, *_ in split], length)
            base_name = f"{wall.id}/{storey}"
            band_parts: list[_Part] = []

            for k, (s0, s1) in enumerate(solid, start=1):
                members = [g for g in in_band if s0 - MIN_PART < s_at[id(g)] < s1 + MIN_PART]
                name = f"{base_name}/P{k}"
                if not members:
                    notes.append(f"{name}: no shells of the wall found in the pier; left out")
                    continue
                centre = start + along * ((s0 + s1) / 2 * MM)
                others = _others(members, near)
                cuts: dict[str, _Cut] = {}
                for cut_name, z, side in (
                    ("bottom", z0, 1.0),
                    ("middle", (z0 + z1) / 2, 0.0),
                    ("top", z1, -1.0),
                ):
                    c = _cut(members, centre + _UP * (z * MM), _UP, pier_axes, side, others)
                    if c is not None:
                        cuts[cut_name] = c
                band_parts.append(
                    _Part(
                        "pier",
                        name,
                        wall,
                        above,
                        (z0, z1),
                        (s0, s1),
                        (z0, z1),
                        members,
                        thickness,
                        cuts,
                        label,
                        holes=_holes_in(holes, s0, s1, z0, z1),
                    )
                )
            k = 0
            for o0, o1, oid, sill, head in sorted(split):
                for position, h0, h1 in (
                    ("below", z0, max(sill, z0)),
                    ("above", min(head, z1), z1),
                ):
                    if h1 - h0 <= MIN_PART:
                        continue
                    members = [
                        g
                        for g in in_band
                        if o0 - MIN_PART < s_at[id(g)] < o1 + MIN_PART
                        and h0 - MIN_PART < z_at[id(g)] < h1 + MIN_PART
                    ]
                    if not members:
                        continue
                    k += 1
                    name = f"{base_name}/S{k}"
                    zc = (h0 + h1) / 2
                    in_others = _others(members, in_band)
                    cuts = {}
                    for cut_name, s, side in (
                        ("left", o0, 1.0),
                        ("middle", (o0 + o1) / 2, 0.0),
                        ("right", o1, -1.0),
                    ):
                        c = _cut(
                            members,
                            _point(start, along, s, zc),
                            along,
                            spandrel_axes,
                            side,
                            in_others,
                        )
                        if c is not None:
                            cuts[cut_name] = c
                    # Its edge on the band's level (the sill wall stands on the floor, the
                    # spandrel above reaches the floor over it): carries force across the
                    # level beside the piers', in the pier axes so that they add up.
                    edge: dict[str, _Cut] = {}
                    below_ = position == "below"
                    edge_name, z, side = ("bottom", z0, 1.0) if below_ else ("top", z1, -1.0)
                    plane = _point(start, along, (o0 + o1) / 2, z)
                    c = _cut(members, plane, _UP, pier_axes, side, _others(members, near))
                    if c is not None:
                        edge[edge_name] = c
                    band_parts.append(
                        _Part(
                            "spandrel",
                            name,
                            wall,
                            above,
                            (z0, z1),
                            (o0, o1),
                            (h0, h1),
                            members,
                            thickness,
                            cuts,
                            label,
                            [oid],
                            position,
                            edge,
                            _holes_in(holes, o0, o1, h0, h1),
                        )
                    )
            # The whole wall at the band's bottom and top levels: the continuous section under
            # a window (the critical section at the base), the sum of the piers' cuts and the
            # spandrels' edges there.
            centre = start + along * (length / 2 * MM)
            cuts = {}
            for cut_name, z, side in (("bottom", z0, 1.0), ("top", z1, -1.0)):
                c = _cut(in_band, centre + _UP * (z * MM), _UP, pier_axes, side, outside)
                if c is not None:
                    cuts[cut_name] = c
            if in_band:
                band_parts.append(
                    _Part(
                        "section",
                        base_name,
                        wall,
                        above,
                        (z0, z1),
                        (0.0, length),
                        (z0, z1),
                        in_band,
                        thickness,
                        cuts,
                        label,
                        holes=[o[2] for o in holes],
                        segments={
                            "bottom": _segments(own, z0, length),
                            "top": _segments(own, z1, length),
                        },
                    )
                )
            if holes:
                notes.append(
                    f"{base_name}: opening(s) {', '.join(o[2] for o in holes)} lower than "
                    f"{min_opening:g} x the storey height do not split the wall into piers; "
                    "they are holes in its parts ('holes')"
                )
            parts.extend(band_parts)
    return parts


def wall_openings_of(
    openings: Iterable[Any], bottom: float = 0.0
) -> list[tuple[float, float, str, float, float]]:
    """(start and end along the wall, id, sill and head elevation) of a wall's openings [mm],
    the elevations from the wall's ``bottom`` (the openings' sills are above it)."""
    return [
        (
            float(o.offset),
            float(o.offset + o.width),
            o.id,
            bottom + float(o.sill),
            bottom + float(o.sill + o.height),
        )
        for o in openings
    ]


def _story_name(story: Any, z: float) -> str:
    if story is None:
        return f"{z:g} mm"
    return story.name or story.id


# ─────────────────────────────────────── results ───────────────────────────────────────

_G = 1 / math.sqrt(3)


def stress_nodal_forces(points: list[np.ndarray], rows: np.ndarray) -> np.ndarray:
    """The nodal forces (nodes, 6) [N, N·m, global] of a shell's generalized stresses ``rows``
    (N11 N22 N12 M11 M22 M12 Q13 Q23 per integration point, its axes): ∫ Bᵀ σ dA with the
    bilinear (Q4, 2 x 2 Gauss points in the solver's order) or linear (T3, the mean of its
    points) shape functions; the moments as nodal couples e3 × (M ∇N). Used for the
    temperature case's stress corrections; reproduces the solver's nodal forces from its
    stresses (tested)."""
    from saengine.design.slab import shell_axes

    p = [np.asarray(q, dtype=float) for q in points]
    e1, e2, e3 = shell_axes(p)
    local = np.array([[(q - p[0]) @ e1, (q - p[0]) @ e2] for q in p])
    rows = np.asarray(rows, dtype=float).reshape(-1, 8)
    force = np.zeros((len(p), 3))
    bend = np.zeros((len(p), 3))

    def add(d: np.ndarray, r: np.ndarray, area: float) -> None:
        nonlocal force, bend
        dx, dy = d
        force += area * (
            np.outer(dx * r[0] + dy * r[2], e1)
            + np.outer(dx * r[2] + dy * r[1], e2)
            + np.outer(dx * r[6] + dy * r[7], e3)
        )
        bend += area * (np.outer(dx * r[3] + dy * r[5], e1) + np.outer(dx * r[5] + dy * r[4], e2))

    if len(p) == 4:
        for k, (xi, eta) in enumerate(((-_G, -_G), (_G, -_G), (_G, _G), (-_G, _G))):
            d_xi = np.array([-(1 - eta), 1 - eta, 1 + eta, -(1 + eta)]) / 4
            d_eta = np.array([-(1 - xi), -(1 + xi), 1 + xi, 1 - xi]) / 4
            jac = np.array([d_xi @ local, d_eta @ local])
            d = np.linalg.solve(jac, np.vstack([d_xi, d_eta]))
            r = rows[k] if len(rows) == 4 else rows.mean(axis=0)
            add(d, r, abs(float(np.linalg.det(jac))))
    elif len(p) == 3:
        m = np.column_stack([local, np.ones(3)])
        coef = np.linalg.inv(m)  # column k: the coefficients of N_k
        area = abs(float(np.linalg.det(m))) / 2
        add(coef[:2], rows.mean(axis=0), area)
    couples = np.array([np.cross(e3, b) for b in bend])
    return np.hstack([force, couples])


def case_shell_forces(
    project: dict[str, Any], out_dir: str | Path
) -> dict[str, dict[int, np.ndarray]]:
    """Each static case's shell nodal forces of the results in ``out_dir``: ``{case code:
    {shell id: (nodes, 6)}}`` [N, N·m, global], the last step, with the temperature case's
    fixed-end corrections (:mod:`saengine.fem.thermal`, :func:`stress_nodal_forces` of them)."""
    from opensees_studio.services.result_store import load_manifest, load_results
    from opensees_studio.services.results import StaticResults

    from saengine.fem.display import _code
    from saengine.fem.thermal import load_corrections, shell_force_corrections

    manifest = load_manifest(out_dir)
    thermal = load_corrections(Path(out_dir).with_suffix(".osmodel"))
    xyz = {int(n["id"]): np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    shells = {
        int(e["id"]): [int(n) for n in e.get("nodes", [])]
        for e in project.get("elements", [])
        if e.get("type") == "Shell"
    }
    out: dict[str, dict[int, np.ndarray]] = {}
    for entry in manifest["cases"]:
        results = load_results(entry, out_dir)
        if not isinstance(results, StaticResults):
            continue
        code = _code(entry["case_name"])
        reached = float(results.load_factors[-1]) if len(results.load_factors) else 1.0
        add = shell_force_corrections(thermal, code)
        found: dict[int, np.ndarray] = {}
        for i, nodes in shells.items():
            f = _nodal(results.element_forces.get(i), len(nodes))
            if i in add and all(n in xyz for n in nodes):
                f = f + reached * stress_nodal_forces([xyz[n] for n in nodes], add[i])
            found[i] = f
        out[code] = found
    return out


def _nodal(rows: Any, nodes: int) -> np.ndarray:
    """A shell's nodal forces at the last step (nodes, 6); zeros where there are none."""
    if rows is None or not len(rows):
        return np.zeros((nodes, 6))
    last = np.asarray(rows[-1], dtype=float)
    if last.size != nodes * 6:
        return np.zeros((nodes, 6))
    return last.reshape(nodes, 6)


def _envelope(cut: _Cut, seismic: Any) -> dict[str, np.ndarray]:
    """Per envelope part of the response spectrum run (RX, RY, AX, AY) the cut's peak
    resultant [N, N·m, ≥ 0]: each mode's own resultant combined over the modes (CQC/SRSS) and
    scaled; the torsion cases in absolute value."""
    from saengine.fem.seismic_design import combine

    sizes = {s.id: len(s.nodes) for s, _ in cut.terms}

    def of(r: Any) -> NodalForces:
        return lambda i: _nodal(r.element_forces.get(i), sizes[i]) if r is not None else None

    out: dict[str, np.ndarray] = {}
    for part, modes in seismic.modal.items():
        rule, damping, omegas = seismic.rules[part]
        peaks = np.array([cut.resultant(of(r)) for r in modes]).reshape(-1, len(COMPONENTS))
        out[part] = float(seismic.scale[part[1]]) * combine(peaks, omegas, damping, rule)
    for part, r in seismic.torsion.items():
        out[part] = np.abs(cut.resultant(of(r)))
    # B19: the time-history parts of the cut, from the spectrum's (saengine.fem.
    # linear_time_history.TimeHistoryForces.derived_parts).
    derived = getattr(seismic, "derived_parts", None)
    if derived is not None:
        out.update(derived(out))
    return out


def _values(vector: np.ndarray) -> dict[str, float]:
    """A resultant [N, N·m] as ``{P, V2, V3, T, M2, M3}`` in kN, kN·m."""
    return {k: float(v) / 1e3 for k, v in zip(COMPONENTS, vector, strict=True)}


def _combined(
    cut: _Cut,
    cases: Mapping[str, Mapping[int, np.ndarray]],
    combinations: list[Any],
    seismic: Any,
    signs: str,
    notes: set[str],
) -> dict[str, dict[str, float]]:
    from saengine.fem.combinations import variants

    static = {case: cut.resultant(lambda i, f=forces: f.get(i)) for case, forces in cases.items()}
    envelope = None
    if seismic is not None and any(c.has_envelope for c in combinations):
        envelope = _envelope(cut, seismic)
    out: dict[str, dict[str, float]] = {}
    for combination in combinations:
        try:
            found = variants(combination, static, envelope, kind=SIGN_KIND, signs=signs)
        except KeyError as missing:
            what = "case" if missing.args[0] in combination.factors else "part"
            notes.add(
                f"{combination.name}: no wall forces, {what} {missing.args[0]} has no results"
            )
            continue
        for name, value in found:
            out[name] = _values(value)
    return out


def _axes_list(axes: tuple[np.ndarray, ...]) -> list[list[float]]:
    return [[round(float(v), 12) + 0.0 for v in a] for a in axes]


def wall_forces(
    project: dict[str, Any],
    building: Any,
    results: str | Path | Mapping[str, Mapping[int, np.ndarray]],
    combinations: list[Any],
    seismic: Any = None,
    signs: str = "corners",
    min_opening: float = MIN_OPENING,
    ignore: Iterable[str] = (),
) -> dict[str, Any]:
    """The piers, spandrels and storey sections of the walls with their cut forces.

    ``project``: the analysis model (``08 FEM/model.osmodel``); ``building``: the
    :class:`saengine.library.bim.BuildingModel` it was derived from, with the openings the
    analysis cut (06 BIM's and, where 07 MEP adds any, :func:`saengine.mep.loads.
    with_mep_openings`'s); ``results``: the results folder, or each static case's shell nodal
    forces (:func:`case_shell_forces`); ``combinations``: :class:`saengine.fem.combinations.
    DesignCombination` (e.g. :func:`saengine.fem.combinations.design_combinations`,
    :func:`design_combination_list`); ``seismic``: the response spectrum envelopes
    (:func:`saengine.fem.seismic_design.load_seismic_forces`), needed by combinations with
    envelope parts; ``signs``: their sign patterns ("corners" or "plusMinus", the summary's
    ``signs``); ``min_opening``: the fraction of a storey band's height an opening must reach
    over to split the wall into piers (:data:`MIN_OPENING`; 0: every opening does);
    ``ignore``: ids of openings that never split a wall (holes in their parts).

    Returns ``{"piers", "spandrels", "sections", "notes"}``. A pier: ``{"pier", "wall",
    "type", "storey", "label", "bottom", "top", "start", "end", "lw", "tw", "centre", "axes",
    "shells", "cuts", "spandrels", "holes"}`` with ``cuts`` ``{"bottom" | "middle" | "top":
    {combination: {P, V2, V3, T, M2, M3}}}`` (kN, kN·m; see the module's sign convention),
    ``start``/``end`` along the wall from its start, ``bottom``/``top`` elevations,
    ``lw``/``tw`` (mm), ``centre`` [x, y] mm, ``axes`` the local 1, 2, 3 as global unit
    vectors, ``storey`` the id of the story at the top of the band, ``spandrels`` the names of
    the spandrels beside it and ``holes`` the ids of the openings too small to split the wall
    that lie in it (its section is net of them). A spandrel: the same with ``"spandrel"``,
    ``"opening"``, ``"position"`` ("above" | "below"), ``"length"``, ``"depth"``, ``cuts``
    ``{"left" | "middle" | "right": ...}`` and ``edge`` ``{"bottom" | "top": {combination:
    ...}}``: its cut on the band's level (a sill wall's bottom on the floor, a spandrel's top
    under the floor above) in the pier axes ``edge_axes`` — the force the piers' cuts at that
    level do not carry.

    A section (``"section"`` = ``"<wall>/<storey>"``): the whole wall in the band, ``cuts``
    ``{"bottom" | "top": ...}`` at the band's levels in the pier axes about the wall's middle
    (``centre``; ``lw`` its length), the sum of the piers' cuts and the spandrels' edges at
    that level: under a window the continuous section the piers share (the critical section
    at a wall's base). ``segments`` ``{"bottom" | "top": [[start, end], ...]}``: its solid
    lengths at each level (beside a door standing on it). ``piers``, ``spandrels``: its parts.
    """
    notes: list[str] = []
    cases = case_shell_forces(project, results) if isinstance(results, str | Path) else results
    if seismic is None and any(c.has_envelope for c in combinations):
        notes.append(
            "the response spectrum combinations have no wall forces: the modal-force run "
            "(saengine.fem.seismic_design) is missing"
        )
        combinations = [c for c in combinations if not c.has_envelope]
    parts = _parts(project, building, notes, min_opening, ignore)
    missing: set[str] = set()
    piers: list[dict[str, Any]] = []
    spandrels: list[dict[str, Any]] = []
    sections: list[dict[str, Any]] = []

    def combined(cuts: Mapping[str, _Cut]) -> dict[str, dict[str, dict[str, float]]]:
        return {
            name: _combined(cut, cases, combinations, seismic, signs, missing)
            for name, cut in cuts.items()
        }

    for part in parts:
        wall = part.wall
        start = np.array(wall.start, dtype=float)
        run = np.array(wall.end, dtype=float) - start
        along = run / np.linalg.norm(run)
        flat = np.array([*along, 0.0])
        pier_axes = (_UP, flat, np.cross(_UP, flat))
        s0, s1 = part.span
        axes = (flat, _UP, np.cross(flat, _UP)) if part.kind == "spandrel" else pier_axes
        common = {
            "wall": wall.id,
            "type": wall.type,
            "storey": part.storey.id if part.storey is not None else None,
            "label": part.label,
            "bottom": part.height[0],
            "top": part.height[1],
            "start": s0,
            "end": s1,
            "tw": part.thickness,
            "centre": [float(v) for v in start + along * (s0 + s1) / 2],
            "axes": _axes_list(axes),
            "shells": sorted(g.id for g in part.shells),
            "cuts": combined(part.cuts),
            "holes": part.holes,
        }
        if part.kind == "pier":
            piers.append({"pier": part.name, **common, "lw": s1 - s0, "spandrels": []})
        elif part.kind == "spandrel":
            spandrels.append(
                {
                    "spandrel": part.name,
                    **common,
                    "opening": part.openings[0] if part.openings else None,
                    "position": part.position,
                    "length": s1 - s0,
                    "depth": part.height[1] - part.height[0],
                    "edge": combined(part.edge),
                    "edge_axes": _axes_list(pier_axes),
                }
            )
        else:
            segments = {k: [[a, b] for a, b in v] for k, v in part.segments.items()}
            sections.append(
                {
                    "section": part.name,
                    **common,
                    "lw": s1 - s0,
                    "segments": segments,
                    "piers": [],
                    "spandrels": [],
                }
            )
    for s in spandrels:
        for p in piers:
            beside = (
                abs(p["end"] - s["start"]) <= MIN_PART or abs(p["start"] - s["end"]) <= MIN_PART
            )
            if p["wall"] == s["wall"] and p["storey"] == s["storey"] and beside:
                p["spandrels"].append(s["spandrel"])
    for section in sections:
        for key, items, name in (("piers", piers, "pier"), ("spandrels", spandrels, "spandrel")):
            section[key] = [
                item[name]
                for item in items
                if item["wall"] == section["wall"] and item["storey"] == section["storey"]
            ]
    if seismic is not None and any(c.has_envelope for c in combinations):
        notes.append(
            "response spectrum wall forces: each mode's pier resultant combined over the modes "
            f"(CQC/SRSS) and scaled ({CLAUSE_RS}), ± with the static part"
        )
    notes.extend(sorted(missing))
    return {"piers": piers, "spandrels": spandrels, "sections": sections, "notes": notes}


def wall_piers(
    project: dict[str, Any],
    building: Any,
    results: str | Path | Mapping[str, Mapping[int, np.ndarray]],
    combinations: list[Any],
    seismic: Any = None,
    signs: str = "corners",
    min_opening: float = MIN_OPENING,
    ignore: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """The piers of :func:`wall_forces` (each with the names of its spandrels)."""
    found = wall_forces(
        project, building, results, combinations, seismic, signs, min_opening, ignore
    )
    return found["piers"]


def design_combination_list(
    settings: Any, out_dir: str | Path, present: set[str] | None = None
) -> tuple[list[Any], Any, str]:
    """``(combinations, seismic, signs)`` for :func:`wall_forces`: the project's combinations,
    with EX, EY replaced by the response spectrum combinations when the design uses them and
    their modal-force run is there (:func:`saengine.fem.combinations.design_combinations`),
    the run's envelopes (:func:`saengine.fem.seismic_design.load_seismic_forces`) and the
    summary's sign patterns."""
    from saengine.fem import seismic_design
    from saengine.fem.combinations import design_combinations

    summary = None
    seismic = None
    if seismic_design.design_uses_spectrum(settings):
        summary = seismic_design.load_summary(out_dir)
        if summary and summary.get("available"):
            seismic = seismic_design.load_seismic_forces(out_dir)
        if seismic is None:
            summary = None
    return (
        design_combinations(settings, present, summary),
        seismic,
        str((summary or {}).get("signs", "corners")),
    )
