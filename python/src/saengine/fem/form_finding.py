"""Form finding and load analysis of tensile membranes and cable nets on four corners (alpha 9
L7), with numpy only.

**Mesh** (:func:`mesh`): an (n + 1) × (n + 1) grid by bilinear interpolation of the four
corners; links along u (warp: corner 1 to 2) and v (fill: corner 2 to 3); the corners fixed;
the edges either cables (their nodes free) or fixed straight edges.

**Form finding** (:func:`find_form`): the force density method (Schek 1974): each link has q =
T / L (fabric links: the prestress × the link's tributary width / its length on the starting
grid; edge cables: their prestress / length); the free nodes' equilibrium Σ q (xj - xi) = 0 is
linear, D_ff x_f = -D_fx x_x, solved for each coordinate.

**Load analysis** (:func:`analyse`): on the found form, every link is elastic and tension-only,
T = T0 + k (L - L0) ≥ 0 with T0 the found prestress, k = E t × width / L0 (fabric) or E A / L0
(cables); pressures act normal to the deformed surface (follower loads), snow on plan, the
fabric's weight down; solved by dynamic relaxation with kinetic damping (Barnes). Results: the
links' forces, the fabric's stress per unit width, the movements, the corner reactions.

Units: mm, N, N/mm (= kN/m), N/mm² (= MPa; kPa × 1e-3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

KPA = 1e-3


@dataclass
class Net:
    """A membrane or cable net: node coordinates, links (i, j), their kind ("warp", "fill",
    "cable"), the fixed nodes, the links' tributary widths [mm] and prestress [N]."""

    xyz: np.ndarray
    links: np.ndarray
    kinds: list[str]
    fixed: np.ndarray
    width: np.ndarray
    prestress: np.ndarray
    n: int
    corners: list[int] = field(default_factory=list)


def mesh(
    corners: np.ndarray,
    n: int,
    prestress_warp: float,
    prestress_fill: float,
    edge_cables: bool,
    cable_prestress: float,
) -> Net:
    """The starting grid of four ``corners`` [mm] (4 × 3) with ``n`` divisions per edge."""
    c = np.asarray(corners, dtype=float)
    ids = np.arange((n + 1) ** 2).reshape(n + 1, n + 1)  # [i (u), j (v)]
    xyz = np.zeros(((n + 1) ** 2, 3))
    for i in range(n + 1):
        for j in range(n + 1):
            u, v = i / n, j / n
            xyz[ids[i, j]] = (
                (1 - u) * (1 - v) * c[0] + u * (1 - v) * c[1] + u * v * c[2] + (1 - u) * v * c[3]
            )
    links, kinds, width, prestress = [], [], [], []

    def boundary_u(j: int) -> bool:
        return j in (0, n)

    def boundary_v(i: int) -> bool:
        return i in (0, n)

    for i in range(n):
        for j in range(n + 1):  # warp links along u
            a, b = ids[i, j], ids[i + 1, j]
            w = _side(xyz, ids, i, j, "u", n)
            links.append((a, b))
            if boundary_u(j) and edge_cables:
                kinds.append("cable")
                width.append(w / 2)
                prestress.append(cable_prestress + prestress_warp * w / 2)
            else:
                kinds.append("warp")
                share = w / 2 if boundary_u(j) else w
                width.append(share)
                prestress.append(prestress_warp * share)
    for i in range(n + 1):
        for j in range(n):  # fill links along v
            a, b = ids[i, j], ids[i, j + 1]
            w = _side(xyz, ids, i, j, "v", n)
            links.append((a, b))
            if boundary_v(i) and edge_cables:
                kinds.append("cable")
                width.append(w / 2)
                prestress.append(cable_prestress + prestress_fill * w / 2)
            else:
                kinds.append("fill")
                share = w / 2 if boundary_v(i) else w
                width.append(share)
                prestress.append(prestress_fill * share)
    corner_ids = [int(ids[0, 0]), int(ids[n, 0]), int(ids[n, n]), int(ids[0, n])]
    if edge_cables:
        fixed = np.array(sorted(corner_ids))
    else:
        edge = set(ids[0, :]) | set(ids[n, :]) | set(ids[:, 0]) | set(ids[:, n])
        fixed = np.array(sorted(int(k) for k in edge))
    return Net(
        xyz,
        np.array(links, dtype=int),
        kinds,
        fixed,
        np.array(width, dtype=float),
        np.array(prestress, dtype=float),
        n,
        corner_ids,
    )


def _side(xyz: np.ndarray, ids: np.ndarray, i: int, j: int, along: str, n: int) -> float:
    """The tributary width of a link: the mean length of the cross links beside it."""
    if along == "u":
        a, b = ids[i, j], ids[i + 1, j]
        lo, hi = max(j - 1, 0), min(j + 1, n)
        cross = [np.linalg.norm(xyz[ids[i, jj + 1]] - xyz[ids[i, jj]]) for jj in range(lo, hi)]
    else:
        a, b = ids[i, j], ids[i, j + 1]
        lo, hi = max(i - 1, 0), min(i + 1, n)
        cross = [np.linalg.norm(xyz[ids[ii + 1, j]] - xyz[ids[ii, j]]) for ii in range(lo, hi)]
    del a, b
    return float(np.mean(cross)) if cross else 0.0


def find_form(net: Net) -> Net:
    """The equilibrium shape of the prestress by force density (a new Net, the same links)."""
    xyz = net.xyz.copy()
    lengths = np.linalg.norm(xyz[net.links[:, 1]] - xyz[net.links[:, 0]], axis=1)
    q = net.prestress / np.maximum(lengths, 1e-9)
    count = len(xyz)
    d = np.zeros((count, count))
    for (a, b), qq in zip(net.links, q, strict=True):
        d[a, a] += qq
        d[b, b] += qq
        d[a, b] -= qq
        d[b, a] -= qq
    fixed = np.zeros(count, dtype=bool)
    fixed[net.fixed] = True
    free = ~fixed
    dff = d[np.ix_(free, free)]
    dfx = d[np.ix_(free, fixed)]
    xyz[free] = np.linalg.solve(dff, -dfx @ xyz[fixed])
    found = np.linalg.norm(xyz[net.links[:, 1]] - xyz[net.links[:, 0]], axis=1)
    return Net(
        xyz,
        net.links,
        net.kinds,
        net.fixed,
        net.width,
        q * found,  # the forces at the found form
        net.n,
        net.corners,
    )


def quads(n: int) -> np.ndarray:
    """The grid's quads as node ids (n² × 4), counter-clockwise in (u, v)."""
    ids = np.arange((n + 1) ** 2).reshape(n + 1, n + 1)
    return np.stack(
        [ids[:-1, :-1].ravel(), ids[1:, :-1].ravel(), ids[1:, 1:].ravel(), ids[:-1, 1:].ravel()],
        axis=1,
    )


def node_areas(
    net: Net, xyz: np.ndarray, cells: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(surface area, plan area, unit normal (z up)) per node from the grid's quads."""
    q = quads(net.n) if cells is None else cells
    p = xyz[q]  # (cells, 4, 3)
    cross = np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 1]) / 2
    cross[cross[:, 2] < 0] *= -1
    a = np.linalg.norm(cross, axis=1)
    area = np.zeros(len(xyz))
    plan = np.zeros(len(xyz))
    normal = np.zeros((len(xyz), 3))
    for k in range(4):
        np.add.at(area, q[:, k], a / 4)
        np.add.at(plan, q[:, k], np.abs(cross[:, 2]) / 4)
        np.add.at(normal, q[:, k], cross)
    norms = np.linalg.norm(normal, axis=1)
    normal = normal / np.maximum(norms, 1e-12)[:, None]
    return area, plan, normal


@dataclass
class Response:
    xyz: np.ndarray
    forces: np.ndarray  # per link [N]
    movement: float  # largest node movement from the found form [mm]
    reactions: np.ndarray  # per corner [N] (resultant)
    converged: bool
    iterations: int


def analyse(
    form: Net,
    stiffness: np.ndarray,
    snow: float = 0.0,
    pressure: float = 0.0,
    weight: float = 0.0,
    prestress_factor: float = 1.0,
    tolerance: float = 1e-3,
    iterations: int = 20000,
) -> Response:
    """The found form under snow on plan [N/mm²], a pressure normal to the surface [N/mm²]
    (positive down onto the surface's upper face, negative suction) and the fabric's weight
    [N/mm²], the links elastic and tension-only with axial stiffness ``stiffness`` [N/mm],
    by dynamic relaxation with kinetic damping."""
    x0 = form.xyz
    x = x0.copy()
    links = form.links
    l0 = np.linalg.norm(x0[links[:, 1]] - x0[links[:, 0]], axis=1)
    t0 = form.prestress * prestress_factor
    free = np.ones(len(x), dtype=bool)
    free[form.fixed] = False
    k = np.maximum(stiffness, 1e-9)
    mass = np.zeros(len(x))
    np.add.at(mass, links[:, 0], k + t0 / np.maximum(l0, 1e-9))
    np.add.at(mass, links[:, 1], k + t0 / np.maximum(l0, 1e-9))
    mass = np.maximum(mass, 1e-9)  # Δt = 1: m = Σ (k + T/L) keeps it stable with margin
    v = np.zeros_like(x)
    cells = quads(form.n)
    ke_last = 0.0
    converged = False
    scale = max(float(np.max(np.abs(t0))) if len(t0) else 1.0, 1.0)
    it = 0
    forces = t0.copy()
    for it in range(1, iterations + 1):
        d = x[links[:, 1]] - x[links[:, 0]]
        length = np.linalg.norm(d, axis=1)
        forces = np.maximum(t0 + k * (length - l0), 0.0)
        unit = d / np.maximum(length, 1e-9)[:, None]
        r = np.zeros_like(x)
        np.add.at(r, links[:, 0], forces[:, None] * unit)
        np.add.at(r, links[:, 1], -forces[:, None] * unit)
        area, plan, normal = node_areas(form, x, cells)
        r[:, 2] -= snow * plan + weight * area
        r -= pressure * area[:, None] * normal
        r[~free] = 0.0
        if float(np.max(np.abs(r))) < tolerance * scale:
            converged = True
            break
        v += r / mass[:, None]
        ke = float(np.sum(mass[:, None] * v**2))
        if ke < ke_last:  # a peak: restart from rest
            v[:] = 0.0
            ke_last = 0.0
            continue
        ke_last = ke
        x += v
    reactions = np.zeros(len(form.corners))
    d = x[links[:, 1]] - x[links[:, 0]]
    unit = d / np.maximum(np.linalg.norm(d, axis=1), 1e-9)[:, None]
    pull = np.zeros_like(x)
    np.add.at(pull, links[:, 0], forces[:, None] * unit)
    np.add.at(pull, links[:, 1], -forces[:, None] * unit)
    for c, node in enumerate(form.corners):
        reactions[c] = float(np.linalg.norm(pull[node]))
    movement = float(np.max(np.linalg.norm(x - x0, axis=1))) if len(x) else 0.0
    return Response(x, forces, movement, reactions, converged, it)
