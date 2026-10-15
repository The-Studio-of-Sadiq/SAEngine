"""Meshing of the analysis model with Gmsh (https://gmsh.info, GPL-2.0-or-later).

Frames are lines, walls and slabs planar surfaces (with their openings cut out), and solid
blocks volumes (a planar face extruded). Gmsh's OpenCASCADE kernel fragments them all
together, so that every line lying on a surface or in a block, and every face two of them
share, are meshed with the same nodes: the solids, the shells, the beams and the columns of
the analysis model meet node for node. Surfaces become mostly four-node shells (recombined),
with triangles where quadrilaterals do not fit, and only triangles when there are blocks (their
four-node tetrahedra have triangular faces); blocks are meshed finer, at least four elements
across their smallest dimension, as linear tetrahedra are stiff in bending. Lines touching no surface
or block stay one element; others follow the mesh around them.

Coordinates are in millimetres, as in the building model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

Point = tuple[float, float, float]

_LINE, _TRIANGLE, _QUAD, _TETRAHEDRON = 1, 2, 3, 4  # Gmsh element types

#: Elements across a block's smallest dimension, at least.
BLOCK_LAYERS = 4


@dataclass
class Surface:
    """A planar surface: its outline and the outlines of its openings (mm)."""

    key: str
    outline: Sequence[Point]
    openings: Sequence[Sequence[Point]] = ()
    #: In-plane direction the shells' local 1 axis should follow (global X for slabs, the
    #: wall's direction for walls).
    direction: Point = (1.0, 0.0, 0.0)
    #: Normal the shells' node order should give (up for slabs).
    normal: Point | None = None


@dataclass
class Volume:
    """A solid block: a planar face (mm) extruded along ``extrusion`` (mm)."""

    key: str
    outline: Sequence[Point]
    extrusion: Point


@dataclass
class Mesh:
    #: Node coordinates by Gmsh node tag (mm).
    nodes: dict[int, np.ndarray] = field(default_factory=dict)
    #: Per line key, its segments as node tag pairs in order from its start to its end.
    lines: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    #: Per surface key, its shell elements as node tag tuples (three or four).
    surfaces: dict[str, list[tuple[int, ...]]] = field(default_factory=dict)
    #: Per volume key, its four-node tetrahedra (Gmsh's node order: positive volume).
    volumes: dict[str, list[tuple[int, int, int, int]]] = field(default_factory=dict)


def mesh(
    lines: Sequence[tuple[str, Point, Point]],
    surfaces: Sequence[Surface],
    size: float,
    volumes: Sequence[Volume] = (),
) -> Mesh:
    """The conforming mesh of ``lines``, ``surfaces`` and ``volumes``, elements no larger than
    ``size`` (mm), and in a block no larger than a quarter of its thickness."""
    import gmsh

    gmsh.initialize(interruptible=False)
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("saengine")
        occ = gmsh.model.occ

        def plane(points: Sequence[Point]) -> int:
            tags = [occ.addPoint(*p) for p in points]
            edges = [occ.addLine(tags[i], tags[(i + 1) % len(tags)]) for i in range(len(tags))]
            return occ.addPlaneSurface([occ.addCurveLoop(edges)])

        inputs: list[tuple[str, list[tuple[int, int]]]] = []
        for surface in surfaces:
            body = [(2, plane(surface.outline))]
            if surface.openings:
                holes = [(2, plane(o)) for o in surface.openings]
                body, _ = occ.cut(body, holes)
            if body:
                inputs.append((surface.key, list(body)))
        for key, a, b in lines:
            inputs.append((key, [(1, occ.addLine(occ.addPoint(*a), occ.addPoint(*b)))]))
        for volume in volumes:
            extruded = occ.extrude([(2, plane(volume.outline))], *volume.extrusion)
            inputs.append((volume.key, [d for d in extruded if d[0] == 3]))

        objects = [dim_tag for _, dim_tags in inputs for dim_tag in dim_tags]
        _, pieces_of = occ.fragment(objects, []) if len(objects) > 1 else (objects, [objects])
        occ.synchronize()
        pieces: dict[str, list[tuple[int, int]]] = {}
        index = 0
        for key, dim_tags in inputs:
            for _ in dim_tags:
                pieces.setdefault(key, []).extend(pieces_of[index])
                index += 1

        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", min(size, 1.0))
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.RecombineAll", 0 if volumes else 1)
        if volumes:
            # Each block's points carry its finer size (and the mesh grades away from it).
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 1)
            gmsh.model.mesh.setSize(gmsh.model.getEntities(0), size)
            for volume in volumes:
                block = min(size, _smallest_dimension(volume) / BLOCK_LAYERS)
                for piece in pieces.get(volume.key, []):
                    corners = gmsh.model.getBoundary([piece], recursive=True)
                    gmsh.model.mesh.setSize(corners, block)
        gmsh.option.setNumber("Mesh.Algorithm", 8)  # frontal-Delaunay for quadrilaterals
        gmsh.option.setNumber("Mesh.RecombinationAlgorithm", 1)  # blossom
        for _, tag in gmsh.model.getEntities(1):
            up, _ = gmsh.model.getAdjacencies(1, tag)
            if not len(up):
                gmsh.model.mesh.setTransfiniteCurve(tag, 2)  # a frame touching no surface
        gmsh.model.mesh.generate(3 if volumes else 2)

        tags, coords, _ = gmsh.model.mesh.getNodes()
        result = Mesh(
            nodes={int(t): np.array(coords[3 * i : 3 * i + 3]) for i, t in enumerate(tags)}
        )
        ends = {key: (np.array(a), np.array(b)) for key, a, b in lines}
        by_key = {s.key: s for s in surfaces}
        for key, dim_tags in pieces.items():
            for dim, tag in dim_tags:
                types, _, node_tags = gmsh.model.mesh.getElements(dim, tag)
                for kind, flat in zip(types, node_tags, strict=True):
                    width = {_LINE: 2, _TRIANGLE: 3, _QUAD: 4, _TETRAHEDRON: 4}.get(int(kind))
                    if width is None:
                        continue
                    for k in range(0, len(flat), width):
                        nodes = tuple(int(n) for n in flat[k : k + width])
                        if dim == 1:
                            result.lines.setdefault(key, []).append((nodes[0], nodes[1]))
                        elif dim == 2:
                            result.surfaces.setdefault(key, []).append(nodes)
                        elif dim == 3:
                            result.volumes.setdefault(key, []).append(nodes)  # type: ignore[arg-type]
        for key, segments in result.lines.items():
            a, b = ends[key]
            result.lines[key] = _ordered(segments, result.nodes, a, b)
        for key, elements in result.surfaces.items():
            surface = by_key[key]
            result.surfaces[key] = [
                _oriented(e, result.nodes, surface.direction, surface.normal) for e in elements
            ]
        return result
    finally:
        gmsh.finalize()


def _ordered(
    segments: list[tuple[int, int]], nodes: dict[int, np.ndarray], a: np.ndarray, b: np.ndarray
) -> list[tuple[int, int]]:
    """Segments of a line sorted from ``a`` to ``b``, each pointing that way."""
    axis = b - a

    def position(n: int) -> float:
        return float((nodes[n] - a) @ axis)

    pointing = [(i, j) if position(i) <= position(j) else (j, i) for i, j in segments]
    return sorted(pointing, key=lambda s: position(s[0]))


def _oriented(
    element: tuple[int, ...],
    nodes: dict[int, np.ndarray],
    direction: Point,
    normal: Point | None,
) -> tuple[int, ...]:
    """The element's nodes going round so that its normal follows ``normal`` (when given) and
    its first edge is the one closest to ``direction``: the shells' local axes then line up."""
    points = [nodes[n] for n in element]
    order = list(element)
    if normal is not None:
        n = np.cross(points[1] - points[0], points[2] - points[0])
        if float(n @ np.array(normal)) < 0:
            order = [order[0], *reversed(order[1:])]
    points = [nodes[n] for n in order]
    reference = np.array(direction, dtype=float)
    best = max(
        range(len(order)),
        key=lambda k: float(
            (points[(k + 1) % len(order)] - points[k])
            @ reference
            / (np.linalg.norm(points[(k + 1) % len(order)] - points[k]) or 1.0)
        ),
    )
    return tuple(order[best:] + order[:best])


def shell_node_shares(points: Sequence[np.ndarray]) -> list[float]:
    """Area each node of a 3- or 4-node shell carries under a uniform pressure (consistent
    nodal loads of the bilinear element; a third of the area each for a triangle)."""
    if len(points) == 3:
        area = float(np.linalg.norm(np.cross(points[1] - points[0], points[2] - points[0]))) / 2
        return [area / 3] * 3
    shares = [0.0] * 4
    gauss = 1 / np.sqrt(3)
    for xi in (-gauss, gauss):
        for eta in (-gauss, gauss):
            n = [
                (1 - xi) * (1 - eta) / 4,
                (1 + xi) * (1 - eta) / 4,
                (1 + xi) * (1 + eta) / 4,
                (1 - xi) * (1 + eta) / 4,
            ]
            d_xi = [-(1 - eta) / 4, (1 - eta) / 4, (1 + eta) / 4, -(1 + eta) / 4]
            d_eta = [-(1 - xi) / 4, -(1 + xi) / 4, (1 + xi) / 4, (1 - xi) / 4]
            g_xi = sum(d * p for d, p in zip(d_xi, points, strict=True))
            g_eta = sum(d * p for d, p in zip(d_eta, points, strict=True))
            jacobian = float(np.linalg.norm(np.cross(g_xi, g_eta)))
            for k in range(4):
                shares[k] += n[k] * jacobian
    return shares


def _smallest_dimension(volume: Volume) -> float:
    """A block's smallest dimension (mm): its thickness, or the narrower side of its outline's
    bounding rectangle in the outline's plane."""
    points = [np.array(p, dtype=float) for p in volume.outline]
    depth = np.array(volume.extrusion, dtype=float)
    normal = depth / (np.linalg.norm(depth) or 1.0)
    u = points[1] - points[0]
    u /= np.linalg.norm(u) or 1.0
    v = np.cross(normal, u)
    extents = [max(p @ axis for p in points) - min(p @ axis for p in points) for axis in (u, v)]
    return float(min(np.linalg.norm(depth), *extents))
