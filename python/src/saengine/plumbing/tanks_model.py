"""The analysis model of a rectangular RC water-retaining tank (Part 7, plumbing coordination).

A box of shells, in SI units (m, N), built as an OpenSees Studio project and run with its
runner, as :mod:`saengine.substructure.raft` runs a raft:

- walls, base and (when the tank is covered) roof as ASDShellQ4 elements with an elastic plate
  section each (``ElasticMembranePlateSection``: thickness, the concrete's E and ν), on the
  centre-line surfaces: the walls stand on the base's mid-plane and meet the roof's mid-plane;
  the plan is the internal plan plus one wall thickness each way (the walls' centre lines);
  partition walls of a tank of ``compartments`` > 1 run across the length at equal spacing;
- a structured mesh of rectangles no larger than about ``mesh`` (the wall height / 8 by
  default), the walls, base, partitions and roof sharing their nodes along their joints, so
  the joints are monolithic (moment-continuous);
- supports: ``"springs"`` (ground tanks): a vertical Winkler spring under every base node,
  ``k = ks A`` with A the node's share of the base's plan area, plus on the perimeter's nodes
  their share of the toe's plan area (``TankBox.toe``; the toe is not meshed), ``ZeroLength``
  in the vertical direction to a fixed node, linear in the load-case runs; a combination under which the
  superposed base lifts off anywhere (net uplift from the groundwater) is run again on its own
  with compression-only springs (as :mod:`saengine.substructure.raft` does: the tension
  stiffness a negligible share, Newton iterations), so the base spans between the walls where
  it has lifted off; a combination whose net load is upward (the tank would float: see the
  flotation check of :mod:`saengine.plumbing.tanks`) is run with the base held along the
  walls' lines instead (the base spanning between its walls under the net uplift, as if the
  tank were held down); ``"edges"`` (an overhead tank on the
  roof's beams): the base's nodes on the lines of the walls (perimeter and partitions) are
  restrained vertically, all rotations free (pinned along the support lines: the tank's base
  rests on beams under its walls; the beams' flexibility is not modelled);
- two base nodes restrained horizontally (one in X and Y, one in Y), so the model has no
  rigid-body motion in plan; every load case here is self-equilibrated in plan, so these
  carry nothing;
- loads as consistent nodal forces (2 × 2 Gauss points of the bilinear shape functions) of
  surface pressures that vary linearly with height (hydrostatic, earth) or are uniform (self
  weight, roof loads, uplift), one load pattern per load case, so the combinations are
  superposed (the model is linear), except the combinations rerun with compression-only
  springs above (:attr:`TankResults.direct`).

Shell results (OpenSees ASDShellQ4): per Gauss point N11 N22 N12 M11 M22 M12 Q13 Q23 per unit
length in the element's local axes (local 1 from the middle of side 4-1 to the middle of side
2-3, local 3 the normal of the diagonals, :func:`saengine.design.slab.shell_axes`), a positive
M11 stretching the +3 face. The node order here makes local 1 horizontal and local 2 vertical
(up) in every wall, and local 1 = +X, local 3 = +Z in the base and the roof. The Gauss point
values are extrapolated to the element's corners (the bilinear field through the four points)
and averaged over the elements of the same panel meeting at a node: the peaks of a wall's
moments are at its edges, where the Gauss points (0.21 of an element in) under-read them.

Units here: m, N, Pa (the project); the module's callers pass mm and kPa where noted.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

#: Wall panels of the model, named by the plan side they are on.
SIDES = ("South", "North", "West", "East")
#: Blend of even and cosine spacing of the mesh lines (see :func:`spacing`).
GRADING = 0.0
#: Columns of a shell result row.
N11, N22, N12, M11, M22, M12, Q13, Q23 = range(8)
_G = 1 / math.sqrt(3)
#: Gauss points (ξ, η) in the order the solver reports them.
GAUSS = ((-_G, -_G), (_G, -_G), (_G, _G), (-_G, _G))
#: Corner (ξ, η) of a four-node element, in node order.
CORNERS = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))


def _bilinear(xi: float, eta: float) -> np.ndarray:
    return np.array([(1 + a * xi) * (1 + b * eta) / 4 for a, b in CORNERS])


#: Values at the corners from the values at the Gauss points: the bilinear field through the
#: four points evaluated at the corners (the corners sit at ±√3 in the points' coordinates).
EXTRAPOLATE = np.array(
    [
        [(1 + a * x * math.sqrt(3)) * (1 + b * y * math.sqrt(3)) / 4 for a, b in CORNERS]
        for x, y in CORNERS
    ]
)


@dataclass
class TankBox:
    """A rectangular tank's centre-line box, in m, and its shells' properties.

    ``length`` along X and ``width`` along Y are the centre-line dimensions (internal plus one
    wall thickness), ``height`` from the base's mid-plane to the roof's mid-plane (or to the top
    of an open tank's walls)."""

    id: str
    length: float
    width: float
    height: float
    wall: float  # thickness, m
    base: float
    roof: float | None  # None: open top
    E: float  # Pa
    nu: float = 0.2
    compartments: int = 1
    mesh: float | None = None  # target element size, m; None: height / 8
    support: str = "springs"  # "springs" | "edges"
    grading: float = GRADING
    ks: float = 0.0  # N/m³ (springs)
    #: Plan area [m²] of the base's toe (its projection beyond the walls): its springs are
    #: added to the perimeter's nodes (the toe is not meshed).
    toe: float = 0.0


@dataclass
class Grid:
    """The structured mesh: node coordinates [m] and each node's (i, j, k) index."""

    xs: np.ndarray
    ys: np.ndarray
    zs: np.ndarray
    nodes: dict[tuple[int, int, int], int] = field(default_factory=dict)
    coords: list[tuple[float, float, float]] = field(default_factory=list)
    #: Elements: (panel name, node ids in order).
    elements: list[tuple[str, tuple[int, int, int, int]]] = field(default_factory=list)
    partitions: list[int] = field(default_factory=list)  # i index of each partition

    def node(self, i: int, j: int, k: int) -> int:
        key = (i, j, k)
        if key not in self.nodes:
            self.nodes[key] = len(self.coords) + 1
            self.coords.append((float(self.xs[i]), float(self.ys[j]), float(self.zs[k])))
        return self.nodes[key]

    def xyz(self, node: int) -> np.ndarray:
        return np.array(self.coords[node - 1])


def spacing(span: float, count: int, grading: float = GRADING) -> np.ndarray:
    """``count`` intervals over ``span``, graded towards both ends: ``grading`` 0 even, 1 the
    cosine spacing, between a blend of the two. The moments of a wall peak at its edges,
    where the elements are then smallest."""
    k = np.arange(count + 1) / count
    return span * ((1 - grading) * k + grading * (1 - np.cos(np.pi * k)) / 2)


def divisions(span: float, size: float, least: int = 2, multiple: int = 1) -> int:
    count = max(least, math.ceil(span / size - 1e-9))
    return math.ceil(count / multiple) * multiple


def box_grid(box: TankBox) -> Grid:
    """Mesh the box: walls (and partitions), base and roof sharing nodes."""
    size = box.mesh or box.height / 8
    n = max(1, box.compartments)
    nx = divisions(box.length, size, least=4 * n, multiple=n)
    ny = divisions(box.width, size, least=4)
    nz = divisions(box.height, size, least=4)
    bay = box.length / n
    xs = np.concatenate(
        [m * bay + spacing(bay, nx // n, box.grading)[(1 if m else 0) :] for m in range(n)]
    )
    grid = Grid(
        xs,
        spacing(box.width, ny, box.grading),
        spacing(box.height, nz, box.grading),
    )
    grid.partitions = [nx * m // n for m in range(1, n)]
    for i in range(nx):
        for j in range(ny):
            quad = (
                grid.node(i, j, 0),
                grid.node(i + 1, j, 0),
                grid.node(i + 1, j + 1, 0),
                grid.node(i, j + 1, 0),
            )
            grid.elements.append(("Base", quad))
    for k in range(nz):
        for i in range(nx):
            for j, side in ((0, "South"), (ny, "North")):
                quad = (
                    grid.node(i, j, k),
                    grid.node(i + 1, j, k),
                    grid.node(i + 1, j, k + 1),
                    grid.node(i, j, k + 1),
                )
                grid.elements.append((side, quad))
        for j in range(ny):
            walls = [(0, "West"), (nx, "East")]
            walls += [(p, f"Partition {m + 1}") for m, p in enumerate(grid.partitions)]
            for i, name in walls:
                quad = (
                    grid.node(i, j, k),
                    grid.node(i, j + 1, k),
                    grid.node(i, j + 1, k + 1),
                    grid.node(i, j, k + 1),
                )
                grid.elements.append((name, quad))
    if box.roof is not None:
        for i in range(nx):
            for j in range(ny):
                quad = (
                    grid.node(i, j, nz),
                    grid.node(i + 1, j, nz),
                    grid.node(i + 1, j + 1, nz),
                    grid.node(i, j + 1, nz),
                )
                grid.elements.append(("Roof", quad))
    return grid


def panel_index(grid: Grid) -> dict[str, tuple[dict[tuple[int, int], int], np.ndarray, np.ndarray]]:
    """Per panel: its nodes by their 2D index (a, b) and the positions [m] of its mesh lines
    along a and b (base and roof: X, Y; South and North walls: X, Z; the others: Y, Z)."""
    by_node = {node: key for key, node in grid.nodes.items()}
    out: dict[str, tuple[dict[tuple[int, int], int], np.ndarray, np.ndarray]] = {}
    for panel, quad in grid.elements:
        if panel not in out:
            if panel in ("Base", "Roof"):
                axes = (grid.xs, grid.ys)
            elif panel in ("South", "North"):
                axes = (grid.xs, grid.zs)
            else:
                axes = (grid.ys, grid.zs)
            out[panel] = ({}, *axes)
        for node in quad:
            i, j, k = by_node[node]
            if panel in ("Base", "Roof"):
                key = (i, j)
            elif panel in ("South", "North"):
                key = (i, k)
            else:
                key = (j, k)
            out[panel][0][key] = node
    return out


def _quadratic(at: float, points: np.ndarray, values: list[np.ndarray]) -> np.ndarray:
    """The parabola through three (point, value) pairs, at ``at`` (Lagrange)."""
    p0, p1, p2 = points
    w0 = (at - p1) * (at - p2) / ((p0 - p1) * (p0 - p2))
    w1 = (at - p0) * (at - p2) / ((p1 - p0) * (p1 - p2))
    w2 = (at - p0) * (at - p1) / ((p2 - p0) * (p2 - p1))
    return w0 * values[0] + w1 * values[1] + w2 * values[2]


def edge_values(
    index: tuple[dict[tuple[int, int], int], np.ndarray, np.ndarray],
    values: dict[int, np.ndarray],
    free: frozenset[str] = frozenset(),
) -> dict[int, np.ndarray]:
    """A panel's node values with those on its supported or continuous edges (all but the
    ``free`` ones among "a0", "a1", "b0", "b1": a = 0, a = last, ...) replaced by the parabola through the
    three node lines next to the edge, along the normal to the edge (corners: the mean of the
    two directions). Shell moments converge from below and peak at the panel's edges, where
    even the corner-extrapolated values of the elements read low (8-16 % at 8 elements over a
    cantilever wall); the parabola through the interior lines reads the edge within 2 % at the
    same mesh (tests)."""
    nodes, pa, pb = index
    na, nb = len(pa) - 1, len(pb) - 1
    out = dict(values)
    if na < 3 and nb < 3:
        return out

    def along_a(a: int, b: int) -> np.ndarray | None:
        if na < 3:
            return None
        inner = (1, 2, 3) if a == 0 else (na - 1, na - 2, na - 3)
        keys = [(c, b) for c in inner]
        if not all(k in nodes and nodes[k] in values for k in keys):
            return None
        return _quadratic(pa[a], pa[list(inner)], [values[nodes[k]] for k in keys])

    def along_b(a: int, b: int) -> np.ndarray | None:
        if nb < 3:
            return None
        inner = (1, 2, 3) if b == 0 else (nb - 1, nb - 2, nb - 3)
        keys = [(a, c) for c in inner]
        if not all(k in nodes and nodes[k] in values for k in keys):
            return None
        return _quadratic(pb[b], pb[list(inner)], [values[nodes[k]] for k in keys])

    for (a, b), node in nodes.items():
        if node not in values:
            continue
        found = []
        if (a == 0 and "a0" not in free) or (a == na and "a1" not in free):
            found.append(along_a(a, b))
        if (b == 0 and "b0" not in free) or (b == nb and "b1" not in free):
            found.append(along_b(a, b))
        found = [f for f in found if f is not None]
        if found:
            out[node] = sum(found) / len(found)
    return out


def panel_thickness(box: TankBox, panel: str) -> float:
    if panel == "Base":
        return box.base
    if panel == "Roof":
        return box.roof or 0.0
    return box.wall


def element_axes(grid: Grid, quad: tuple[int, ...]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    from saengine.design.slab import shell_axes

    return shell_axes([grid.xyz(n) for n in quad])


def perimeter_shares(grid: Grid) -> dict[int, float]:
    """Each node of the base's perimeter (the walls' centre lines) and its share (summing to 1)
    of the perimeter's length."""
    nx, ny = len(grid.xs) - 1, len(grid.ys) - 1
    ring = [(i, 0) for i in range(nx)] + [(nx, j) for j in range(ny)]
    ring += [(i, ny) for i in range(nx, 0, -1)] + [(0, j) for j in range(ny, 0, -1)]
    points = [np.array([grid.xs[i], grid.ys[j]]) for i, j in ring]
    shares = np.zeros(len(ring))
    for k in range(len(ring)):
        step = float(np.linalg.norm(points[(k + 1) % len(ring)] - points[k]))
        shares[k] += step / 2
        shares[(k + 1) % len(ring)] += step / 2
    shares /= shares.sum()
    return {grid.nodes[(i, j, 0)]: float(s) for (i, j), s in zip(ring, shares, strict=True)}


def base_shares(grid: Grid) -> dict[int, float]:
    """Each base node's share of the base's plan area [m²] (a quarter of each rectangle)."""
    shares: dict[int, float] = {}
    for panel, quad in grid.elements:
        if panel != "Base":
            continue
        p = [grid.xyz(n) for n in quad]
        area = abs((p[1][0] - p[0][0]) * (p[3][1] - p[0][1]))
        for n in quad:
            shares[n] = shares.get(n, 0.0) + area / 4
    return shares


# ─────────────────────────────────────── loads ───────────────────────────────────────


@dataclass
class Pressure:
    """A pressure on the elements of some panels: ``value(point)`` [Pa] at a global point [m],
    acting along ``direction(panel, quad)`` (a unit vector: the force's direction)."""

    panels: set[str]
    value: Any  # Callable[[np.ndarray], float]
    direction: Any  # Callable[[str, np.ndarray], np.ndarray] (panel, element centre) -> unit
    #: Only over this plan rectangle (x0, x1, y0, y1) [m] of a horizontal panel: integrated
    #: over each element's part inside it (exact for a uniform pressure).
    clip: tuple[float, float, float, float] | None = None


def consistent_forces(grid: Grid, pressures: list[Pressure]) -> dict[int, np.ndarray]:
    """Nodal forces [N] of the pressures, by the 2 × 2 Gauss rule of the bilinear shapes."""
    forces: dict[int, np.ndarray] = {}
    for panel, quad in grid.elements:
        found = [p for p in pressures if panel in p.panels]
        if not found:
            continue
        points = np.array([grid.xyz(n) for n in quad])
        centre = points.mean(axis=0)
        for pressure in found:
            direction = np.asarray(pressure.direction(panel, centre), dtype=float)
            if pressure.clip is not None:
                _clipped(forces, quad, points, pressure, direction)
                continue
            for xi, eta in GAUSS:
                shape = _bilinear(xi, eta)
                d_xi = np.array([-(1 - eta), 1 - eta, 1 + eta, -(1 + eta)]) / 4
                d_eta = np.array([-(1 - xi), -(1 + xi), 1 + xi, 1 - xi]) / 4
                jacobian = np.linalg.norm(np.cross(d_xi @ points, d_eta @ points))
                value = float(pressure.value(shape @ points))
                if value == 0.0:
                    continue
                for n, s in zip(quad, shape, strict=True):
                    forces.setdefault(n, np.zeros(3))
                    forces[n] += s * value * jacobian * direction
    return forces


def _clipped(
    forces: dict[int, np.ndarray],
    quad: tuple[int, ...],
    points: np.ndarray,
    pressure: Pressure,
    direction: np.ndarray,
) -> None:
    """A pressure over the part of an axis-aligned horizontal rectangle inside the clip."""
    assert pressure.clip is not None
    x0, x1, y0, y1 = pressure.clip
    xa, xb = points[:, 0].min(), points[:, 0].max()
    ya, yb = points[:, 1].min(), points[:, 1].max()
    cx0, cx1, cy0, cy1 = max(xa, x0), min(xb, x1), max(ya, y0), min(yb, y1)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    area = (cx1 - cx0) * (cy1 - cy0)
    for u, v in GAUSS:
        x = (cx0 + cx1) / 2 + u * (cx1 - cx0) / 2
        y = (cy0 + cy1) / 2 + v * (cy1 - cy0) / 2
        p = np.array([x, y, points[0, 2]])
        # The element's natural coordinates of the point (node 1 at its -x -y corner).
        xi = 2 * (x - xa) / (xb - xa) - 1
        eta = 2 * (y - ya) / (yb - ya) - 1
        if points[1, 0] < points[0, 0]:
            xi = -xi
        if points[3, 1] < points[0, 1]:
            eta = -eta
        shape = _bilinear(xi, eta)
        value = float(pressure.value(p))
        for n, s in zip(quad, shape, strict=True):
            forces.setdefault(n, np.zeros(3))
            forces[n] += s * value * area / 4 * direction


def outward(box: TankBox, grid: Grid, panel: str) -> np.ndarray:
    """The outward normal of a wall panel (partitions: +X)."""
    return {
        "South": np.array([0.0, -1.0, 0.0]),
        "North": np.array([0.0, 1.0, 0.0]),
        "West": np.array([-1.0, 0.0, 0.0]),
        "East": np.array([1.0, 0.0, 0.0]),
    }.get(panel, np.array([1.0, 0.0, 0.0]))


# ─────────────────────────────────────── model ───────────────────────────────────────


#: Share of a spring's stiffness left in tension when the springs are compression-only (as
#: :data:`saengine.substructure.raft.TENSION_SHARE`).
TENSION_SHARE = 1e-6
#: Upward base displacement [m] above which a superposed combination counts as lifting off.
LIFT = 1e-7


def tank_project(
    box: TankBox,
    grid: Grid,
    patterns: dict[str, dict[int, np.ndarray]],
    compression_only: bool = False,
) -> dict[str, Any]:
    """The OpenSees Studio project: one static analysis per load pattern (nodal forces [N] per
    node id); linear, or with compression-only springs (Newton iterations)."""
    count = len(grid.coords)
    on_lines = set()
    lines = {0, len(grid.xs) - 1, *grid.partitions}
    for (i, j, k), node in grid.nodes.items():
        if k == 0 and (i in lines or j in (0, len(grid.ys) - 1)):
            on_lines.add(node)
    anchor_xy = grid.nodes[(0, 0, 0)]
    anchor_y = grid.nodes[(len(grid.xs) - 1, 0, 0)]
    nodes = []
    for node, (x, y, z) in enumerate(grid.coords, start=1):
        restraint = [False] * 6
        if node == anchor_xy:
            restraint[0] = restraint[1] = True
        if node == anchor_y:
            restraint[1] = True
        if box.support == "edges" and node in on_lines:
            restraint[2] = True
        nodes.append(
            {
                "id": node,
                "name": "",
                "coords": [round(x, 6), round(y, 6), round(z, 6)],
                "restraint": restraint,
            }
        )
    materials: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    sections = []
    section_of: dict[float, int] = {}
    for panel, quad in grid.elements:
        t = panel_thickness(box, panel)
        if t not in section_of:
            section_of[t] = len(sections) + 1
            sections.append(
                {
                    "id": section_of[t],
                    "name": f"{box.id} {t * 1e3:g} mm",
                    "type": "ElasticMembranePlateSection",
                    "E": box.E,
                    "nu": box.nu,
                    "h": t,
                    "rho": 0.0,
                }
            )
        elements.append(
            {
                "id": len(elements) + 1,
                "name": panel,
                "type": "Shell",
                "formulation": "ASDShellQ4",
                "nodes": list(quad),
                "section_id": section_of[t],
            }
        )
    if box.support == "springs":
        shares = base_shares(grid)
        if box.toe > 0:
            for node, share in perimeter_shares(grid).items():
                shares[node] += box.toe * share
        for node, share in sorted(shares.items()):
            x, y, z = grid.coords[node - 1]
            ground = count + len(materials) + 1
            nodes.append(
                {
                    "id": ground,
                    "name": "",
                    "coords": [round(x, 6), round(y, 6), round(z, 6)],
                    "restraint": [True] * 6,
                }
            )
            material: dict[str, Any] = {
                "id": len(materials) + 1,
                "name": "",
                "type": "Elastic",
                "E": box.ks * share,
            }
            if compression_only:
                # Spring strain = ground - base displacement: negative when the base lifts.
                material["Eneg"] = box.ks * share * TENSION_SHARE
            materials.append(material)
            elements.append(
                {
                    "id": len(elements) + 1,
                    "name": f"spring {node}",
                    "type": "ZeroLength",
                    "nodes": [node, ground],
                    "material_ids": [len(materials)],
                    "dofs": [3],
                }
            )
    load_patterns, analyses = [], []
    for number, (name, forces) in enumerate(patterns.items(), start=1):
        load_patterns.append(
            {
                "id": number,
                "name": name,
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [
                    {"node_id": n, "forces": [round(float(f), 4) for f in (*v, 0.0, 0.0, 0.0)]}
                    for n, v in sorted(forces.items())
                    if np.any(v)
                ],
                "element_loads": [],
            }
        )
        analyses.append(
            {
                "id": number,
                "name": name,
                "type": "Static",
                "pattern_ids": [number],
                "n_steps": 1,
                "load_factor_increment": 1.0,
                "system": "BandGeneral",
                "constraints": "Plain",
                "integrator": "LoadControl",
                "algorithm": "Newton" if compression_only else "Linear",
                "test": "NormDispIncr",
                "tolerance": 1e-10,
                "max_iter": 100 if compression_only else 10,
            }
        )
    return {
        "meta": {"name": f"Tank {box.id}"},
        "ndm": 3,
        "ndf": 6,
        "nodes": nodes,
        "materials": materials,
        "sections": sections,
        "elements": elements,
        "time_series": [{"id": 1, "name": "", "type": "Linear", "factor": 1.0}],
        "load_patterns": load_patterns,
        "analyses": analyses,
    }


@dataclass
class TankResults:
    """Per load pattern: per panel, per node id, the averaged corner values (8 forces per unit
    length in the element axes, N/m and N·m/m), and the nodes' displacements [m]. Combinations
    run on their own (compression-only springs, or the base held along the walls' lines) are
    stored as further patterns named ``"U: <combination>"``; :attr:`direct` maps their factors
    (:func:`factors_key`) to that name, and :func:`combine` reads them instead of superposing."""

    grid: Grid
    patterns: list[str]
    panels: dict[str, dict[str, dict[int, np.ndarray]]]
    displacement: dict[str, dict[int, np.ndarray]]
    reactions: dict[str, dict[int, np.ndarray]]
    #: Element-wise Gauss values: pattern -> list (element order) of 4 × 8 arrays.
    gauss: dict[str, list[np.ndarray]]
    direct: dict[str, str] = field(default_factory=dict)
    #: Combinations under which the base lifted off the springs (rerun compression-only).
    lifted: list[str] = field(default_factory=list)
    #: Combinations whose net load is upward (rerun with the base held along the walls).
    floating: list[str] = field(default_factory=list)


def factors_key(factors: dict[str, float]) -> str:
    return json.dumps(sorted((k, round(float(v), 6)) for k, v in factors.items() if v))


def _safe(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in text) or "tank"


def _error(stdout: str) -> str | None:
    for line in stdout.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("type") == "error":
            return str(data.get("message"))
    return None


def _run(
    box: TankBox,
    grid: Grid,
    patterns: dict[str, dict[int, np.ndarray]],
    folder: Path,
    stem: str,
    compression_only: bool = False,
) -> TankResults:
    from opensees_studio.services.result_store import load_manifest, load_results

    project = tank_project(box, grid, patterns, compression_only)
    model = folder / f"{stem}.osmodel"
    out = folder / f"{stem}.results"
    if out.exists():
        shutil.rmtree(out)
    model.write_text(json.dumps(project), encoding="utf-8")
    cases = [str(a["id"]) for a in project["analyses"]]
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            *cases,
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if done.returncode != 0:
        message = _error(done.stdout) or done.stderr[-1500:]
        raise RuntimeError(f"the analysis of tank {box.id} failed: {message}")
    names = list(patterns)
    index = panel_index(grid)
    free: frozenset[str] = frozenset()
    panels: dict[str, dict[str, dict[int, np.ndarray]]] = {}
    displacement: dict[str, dict[int, np.ndarray]] = {}
    reactions: dict[str, dict[int, np.ndarray]] = {}
    gauss: dict[str, list[np.ndarray]] = {}
    count = len(grid.coords)
    for entry in load_manifest(str(out))["cases"]:
        results = load_results(entry, str(out))
        name = names[int(entry["case_id"]) - 1]
        gauss[name] = [
            np.asarray(results.shell_forces[k + 1][-1], dtype=float).reshape(-1, 8)
            for k in range(len(grid.elements))
        ]
        sums: dict[str, dict[int, np.ndarray]] = {}
        counts: dict[str, dict[int, int]] = {}
        for (panel, quad), values in zip(grid.elements, gauss[name], strict=True):
            corners = EXTRAPOLATE @ values if len(values) == 4 else np.repeat(values[:1], 4, 0)
            for node, row in zip(quad, corners, strict=True):
                sums.setdefault(panel, {}).setdefault(node, np.zeros(8))
                sums[panel][node] += row
                counts.setdefault(panel, {}).setdefault(node, 0)
                counts[panel][node] += 1
        panels[name] = {
            panel: edge_values(
                index[panel],
                {n: v / counts[panel][n] for n, v in nodes.items()},
                frozenset({"b1"}) if box.roof is None and panel not in ("Base", "Roof") else free,
            )
            for panel, nodes in sums.items()
        }
        displacement[name] = {
            n: np.asarray(results.node_disp[n][-1][:3], dtype=float) for n in range(1, count + 1)
        }
        reactions[name] = {
            n: np.asarray(v[-1][:6], dtype=float)
            for n, v in results.node_reaction.items()
            if n <= count or box.support == "springs"
        }
    return TankResults(grid, names, panels, displacement, reactions, gauss)


def _superposed(
    patterns: dict[str, dict[int, np.ndarray]], factors: dict[str, float]
) -> dict[int, np.ndarray]:
    out: dict[int, np.ndarray] = {}
    for name, factor in factors.items():
        for node, force in patterns.get(name, {}).items():
            out[node] = out.get(node, np.zeros(3)) + factor * np.asarray(force, dtype=float)
    return out


def _merge(target: TankResults, extra: TankResults, factors: dict[str, dict[str, float]]) -> None:
    for name in extra.patterns:
        target.patterns.append(name)
        target.panels[name] = extra.panels[name]
        target.displacement[name] = extra.displacement[name]
        target.reactions[name] = extra.reactions[name]
        target.gauss[name] = extra.gauss[name]
        target.direct[factors_key(factors[name])] = name


def run_tank(
    box: TankBox,
    grid: Grid,
    patterns: dict[str, dict[int, np.ndarray]],
    folder: str | Path,
    combinations: dict[str, dict[str, float]] | None = None,
) -> TankResults:
    """Run every load pattern with OpenSees Studio's runner (``tank-<id>.osmodel`` in
    ``folder``) and read the shells' forces back, extrapolated to the corners. On springs, each
    of the ``combinations`` (name -> factors) whose superposed base lifts off anywhere is run
    again on its own with compression-only springs (``tank-<id>-lift``), or, when its net load
    is upward, with the base held along the walls' lines (``tank-<id>-held``)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"tank-{_safe(box.id)}"
    linear = _run(box, grid, patterns, folder, stem)
    if box.support != "springs" or not combinations:
        return linear
    base = sorted({n for (_, _, k), n in grid.nodes.items() if k == 0})
    lift: dict[str, dict[int, np.ndarray]] = {}
    held: dict[str, dict[int, np.ndarray]] = {}
    factors_of: dict[str, dict[str, float]] = {}
    for name, factors in combinations.items():
        disp = combine_displacement(linear, factors)
        if not any(disp.get(n, np.zeros(3))[2] > LIFT for n in base):
            continue
        forces = _superposed(patterns, factors)
        net = sum(float(v[2]) for v in forces.values())  # N, + up
        key = f"U: {name}"
        factors_of[key] = factors
        (held if net >= 0 else lift)[key] = forces
        (linear.floating if net >= 0 else linear.lifted).append(name)
    if lift:
        _merge(linear, _run(box, grid, lift, folder, f"{stem}-lift", True), factors_of)
    if held:
        edges = replace(box, support="edges")
        _merge(linear, _run(edges, grid, held, folder, f"{stem}-held"), factors_of)
    return linear


def combine(results: TankResults, factors: dict[str, float]) -> dict[str, dict[int, np.ndarray]]:
    """Per panel per node, Σ factor × pattern values (or the combination's own run)."""
    own = results.direct.get(factors_key(factors))
    if own is not None:
        return {panel: dict(nodes) for panel, nodes in results.panels[own].items()}
    out: dict[str, dict[int, np.ndarray]] = {}
    for name, factor in factors.items():
        if not factor or name not in results.panels:
            continue
        for panel, nodes in results.panels[name].items():
            target = out.setdefault(panel, {})
            for node, values in nodes.items():
                target[node] = target.get(node, np.zeros(8)) + factor * values
    return out


def combine_displacement(results: TankResults, factors: dict[str, float]) -> dict[int, np.ndarray]:
    own = results.direct.get(factors_key(factors))
    if own is not None:
        return dict(results.displacement[own])
    out: dict[int, np.ndarray] = {}
    for name, factor in factors.items():
        if not factor or name not in results.displacement:
            continue
        for node, values in results.displacement[name].items():
            out[node] = out.get(node, np.zeros(3)) + factor * values
    return out


# ───────────────────────────── a single wall panel (benchmarks) ─────────────────────────────


@dataclass
class PanelResults:
    """A wall panel's corner-averaged forces under one load: node -> 8 values; node coords."""

    forces: dict[int, np.ndarray]
    coords: dict[int, tuple[float, float]]  # (x along the panel, z up), m
    reactions: dict[int, np.ndarray]


def wall_panel(
    width: float,
    height: float,
    thickness: float,
    edges: dict[str, str],
    gamma: float,
    folder: str | Path,
    E: float = 25e9,
    nu: float = 0.2,
    mesh: float | None = None,
    depth: float | None = None,
    grading: float = GRADING,
) -> PanelResults:
    """One vertical wall panel ``width`` × ``height`` [m] in the XZ plane under a hydrostatic
    pressure ``gamma`` [N/m³] × (depth - z) (``depth`` the liquid depth, default the height),
    with its edges ``{"bottom", "top", "left", "right"}`` each "fixed", "pinned" or "free"; a
    check of the shell model against plate solutions (tests and the verification pack)."""
    size = mesh or height / 8
    nx, nz = divisions(width, size, least=4), divisions(height, size, least=4)
    xs, zs = spacing(width, nx, grading), spacing(height, nz, grading)
    ids = {(i, k): i * (nz + 1) + k + 1 for i in range(nx + 1) for k in range(nz + 1)}
    nodes = []
    for (i, k), node in ids.items():
        edge = []
        if k == 0:
            edge.append(edges.get("bottom", "free"))
        if k == nz:
            edge.append(edges.get("top", "free"))
        if i == 0:
            edge.append(edges.get("left", "free"))
        if i == nx:
            edge.append(edges.get("right", "free"))
        restraint = [False] * 6
        if "fixed" in edge:
            restraint = [True] * 6
        elif "pinned" in edge:
            restraint[:3] = [True] * 3
        nodes.append(
            {
                "id": node,
                "name": "",
                "coords": [float(xs[i]), 0.0, float(zs[k])],
                "restraint": restraint,
            }
        )
    if not any(any(n["restraint"][:3]) for n in nodes):
        raise ValueError("the panel needs a supported edge")
    # In-plane: hold one node in X (the load is out of plane).
    for n in nodes:
        if n["id"] == ids[(0, 0)]:
            n["restraint"][0] = n["restraint"][2] = True
    grid = Grid(xs, np.array([0.0]), zs)
    elements = []
    quads = []
    for i in range(nx):
        for k in range(nz):
            quad = (ids[(i, k)], ids[(i + 1, k)], ids[(i + 1, k + 1)], ids[(i, k + 1)])
            quads.append(quad)
            elements.append(
                {
                    "id": len(elements) + 1,
                    "name": "Panel",
                    "type": "Shell",
                    "formulation": "ASDShellQ4",
                    "nodes": list(quad),
                    "section_id": 1,
                }
            )
    grid.coords = [(float(xs[i]), 0.0, float(zs[k])) for (i, k) in ids]
    grid.elements = [("Panel", q) for q in quads]
    liquid = height if depth is None else depth
    pressure = Pressure(
        {"Panel"},
        lambda p: gamma * max(liquid - p[2], 0.0),
        lambda _panel, _c: np.array([0.0, 1.0, 0.0]),
    )
    forces = consistent_forces(grid, [pressure])
    project = {
        "meta": {"name": "Wall panel"},
        "ndm": 3,
        "ndf": 6,
        "nodes": nodes,
        "materials": [],
        "sections": [
            {
                "id": 1,
                "name": "panel",
                "type": "ElasticMembranePlateSection",
                "E": E,
                "nu": nu,
                "h": thickness,
                "rho": 0.0,
            }
        ],
        "elements": elements,
        "time_series": [{"id": 1, "name": "", "type": "Linear", "factor": 1.0}],
        "load_patterns": [
            {
                "id": 1,
                "name": "F",
                "type": "Plain",
                "time_series_id": 1,
                "nodal_loads": [
                    {"node_id": n, "forces": [*map(float, v), 0.0, 0.0, 0.0]}
                    for n, v in sorted(forces.items())
                ],
                "element_loads": [],
            }
        ],
        "analyses": [
            {
                "id": 1,
                "name": "F",
                "type": "Static",
                "pattern_ids": [1],
                "n_steps": 1,
                "load_factor_increment": 1.0,
                "system": "BandGeneral",
                "constraints": "Plain",
                "integrator": "LoadControl",
                "algorithm": "Linear",
                "test": "NormDispIncr",
                "tolerance": 1e-10,
                "max_iter": 10,
            }
        ],
    }
    from opensees_studio.services.result_store import load_manifest, load_results

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    model = folder / "panel.osmodel"
    out = folder / "panel.results"
    if out.exists():
        shutil.rmtree(out)
    model.write_text(json.dumps(project), encoding="utf-8")
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "opensees_studio.run",
            "--project",
            str(model),
            "--cases",
            "1",
            "--out",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
    )
    if done.returncode != 0:
        raise RuntimeError(_error(done.stdout) or done.stderr[-1500:])
    entry = load_manifest(str(out))["cases"][0]
    results = load_results(entry, str(out))
    sums: dict[int, np.ndarray] = {}
    counts: dict[int, int] = {}
    for k, quad in enumerate(quads):
        values = np.asarray(results.shell_forces[k + 1][-1], dtype=float).reshape(-1, 8)
        for node, row in zip(quad, EXTRAPOLATE @ values, strict=True):
            sums[node] = sums.get(node, np.zeros(8)) + row
            counts[node] = counts.get(node, 0) + 1
    coords = {node: (float(xs[i]), float(zs[k])) for (i, k), node in ids.items()}
    reactions = {n: np.asarray(v[-1][:6], dtype=float) for n, v in results.node_reaction.items()}
    averaged = {n: v / counts[n] for n, v in sums.items()}
    free = frozenset(
        key
        for key, edge in (("a0", "left"), ("a1", "right"), ("b0", "bottom"), ("b1", "top"))
        if edges.get(edge, "free") == "free"
    )
    return PanelResults(edge_values((ids, xs, zs), averaged, free), coords, reactions)
