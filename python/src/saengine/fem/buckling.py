"""Linear (eigen) buckling of the frame of the analysis model under a load combination's axial
forces: critical load factors, buckling modes and effective length factors of the members.

The eigenproblem is the classical one of linear stability (e.g. McGuire, Gallagher and Ziemian,
"Matrix Structural Analysis", 2nd ed., 2000, Ch 9): (K + λ Kg) φ = 0, with K the elastic
stiffness of the frame and Kg its geometric stiffness under the axial forces N of the
combination (from the run's results, so the walls, slabs and links that carried the loads are
accounted for). λ is the factor on the combination's loads at which the frame buckles: below 1
the structure is unstable under them.

The stiffness matrices are assembled here, sparse:

- elastic frames (``ElasticBeamColumn`` on an ``ElasticSection``): the 3D beam stiffness and the
  consistent geometric stiffness (Przemieniecki, "Theory of Matrix Structural Analysis", 1968,
  Sec 15.2), with the torsional term N Ip / (A L), local axes as the runner builds them
  (:func:`saengine.fem.second_order._frame_axes`);
- trusses (``Truss``, ``CorotTruss`` on an elastic material): axial stiffness and N / L;
- zero-length links (``ZeroLength`` on ``Elastic`` materials, such as the pinned ends'
  ``<member>/pin``): springs along the global axes;
- supports (node restraints) and the multi-point constraints (rigid diaphragms, rigid links,
  equal DOFs) by a transformation to the independent DOFs.

Not in the buckling model: shells (walls and slabs: their stiffness is left out, so a building
held by walls gets lower, conservative, factors; a slab's in-plane stiffness is there only
through the rigid diaphragms), solids, joint offsets (members are their clear centre-line
length), and the frames' P-small-delta beyond one element per piece (each analysis piece is one
element; the derived model splits members at every joint).

Effective length factors (BNBC 2020 Part 6 Sec 10.5, KL/r; the elastic buckling load of a member
from a buckling analysis of the frame, as in AISC 360-05 Commentary Appendix 7, whose provisions
BNBC 2020 Part 6 Chapter 10 adopts): K = (π / L) √(E I / Pcr), Pcr = λ1 |N| the member's axial
force at the first critical factor, for bending about each principal axis. It is meaningful for
members that take part in the first mode; a member far from it gets a large K, which is shown
as none above :data:`K_SHOWN_MAX`.

Units: the model's (N, m).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Effective length factors above this are not shown (the member does not take part in mode 1).
K_SHOWN_MAX = 10.0
#: Largest number of reduced DOFs solved with dense LAPACK (more: sparse ARPACK).
DENSE_MAX = 1500
#: Axial force [N] below which a member is taken as carrying none (no K).
N_SMALL = 1.0

_FRAMES = ("ElasticBeamColumn",)
_TRUSSES = ("Truss", "CorotTruss")


class BucklingError(ValueError):
    """The buckling analysis cannot be done (no frames, unstable frame, no compression)."""


@dataclass
class _Frame:
    id: int
    name: str
    i: int
    j: int
    length: float
    axes: np.ndarray  # rows x, y, z
    E: float
    A: float
    Iz: float
    Iy: float
    G: float
    J: float
    truss: bool = False


@dataclass
class BucklingResult:
    """Critical load factors ``factors`` (ascending), their mode shapes ``modes`` (node id ->
    6 values, the largest translation 1), the frames analysed and those skipped (by type)."""

    factors: list[float]
    modes: list[dict[int, np.ndarray]]
    frames: dict[int, _Frame]
    axial: dict[int, float]
    skipped: dict[str, int] = field(default_factory=dict)
    dofs: int = 0


# ─────────────────────────────────────── elements ───────────────────────────────────────


def frame_stiffness(f: _Frame) -> np.ndarray:
    """The 12 x 12 elastic stiffness in the local axes (u, v, w, θx, θy, θz at i, then j)."""
    k = np.zeros((12, 12))
    L = f.length
    ea = f.E * f.A / L
    k[np.ix_([0, 6], [0, 6])] = ea * np.array([[1, -1], [-1, 1]])
    if f.truss:
        return k
    gj = f.G * f.J / L
    k[np.ix_([3, 9], [3, 9])] = gj * np.array([[1, -1], [-1, 1]])
    for ei, (d, r, s) in ((f.E * f.Iz, (1, 5, 1.0)), (f.E * f.Iy, (2, 4, -1.0))):
        idx = [d, r, d + 6, r + 6]
        c = s * 6 * L
        block = np.array(
            [
                [12, c, -12, c],
                [c, 4 * L * L, -c, 2 * L * L],
                [-12, -c, 12, -c],
                [c, 2 * L * L, -c, 4 * L * L],
            ]
        )
        k[np.ix_(idx, idx)] = ei / L**3 * block
    return k


def frame_geometric(f: _Frame, n: float) -> np.ndarray:
    """The 12 x 12 geometric stiffness for the axial force ``n`` (tension positive), local axes
    (Przemieniecki 1968 Sec 15.2): bending in both planes and the torsional term."""
    k = np.zeros((12, 12))
    L = f.length
    if f.truss:
        for d in (1, 2):
            k[np.ix_([d, d + 6], [d, d + 6])] = n / L * np.array([[1, -1], [-1, 1]])
        return k
    for d, r, s in ((1, 5, 1.0), (2, 4, -1.0)):
        idx = [d, r, d + 6, r + 6]
        c = s * L / 10
        block = np.array(
            [
                [6 / 5, c, -6 / 5, c],
                [c, 2 * L * L / 15, -c, -L * L / 30],
                [-6 / 5, -c, 6 / 5, -c],
                [c, -L * L / 30, -c, 2 * L * L / 15],
            ]
        )
        k[np.ix_(idx, idx)] = n / L * block
    ip = f.Iy + f.Iz
    k[np.ix_([3, 9], [3, 9])] = n * ip / (f.A * L) * np.array([[1, -1], [-1, 1]])
    return k


def _rotation(axes: np.ndarray) -> np.ndarray:
    t = np.zeros((12, 12))
    for b in range(4):
        t[3 * b : 3 * b + 3, 3 * b : 3 * b + 3] = axes
    return t


def frames_of(project: dict[str, Any]) -> tuple[dict[int, _Frame], dict[str, int]]:
    """The model's elastic frames and trusses, and the counts of the elements left out."""
    from saengine.fem.second_order import _frame_axes

    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    sections = {s["id"]: s for s in project.get("sections", [])}
    materials = {m["id"]: m for m in project.get("materials", [])}
    frames: dict[int, _Frame] = {}
    skipped: dict[str, int] = {}
    for e in project.get("elements", []):
        kind = e.get("type")
        nodes = e.get("nodes", [])
        if kind in _FRAMES or kind in _TRUSSES:
            a, b = coords.get(nodes[0]), coords.get(nodes[1])
            length = float(np.linalg.norm(b - a)) if a is not None and b is not None else 0.0
            if length <= 1e-9:
                skipped[kind] = skipped.get(kind, 0) + 1
                continue
            x, y, z = _frame_axes(a, b, e.get("vecxz"))
            if kind in _FRAMES:
                s = sections.get(e.get("section_id"), {})
                if s.get("type", "ElasticSection") != "ElasticSection" or not s.get("E"):
                    skipped[kind] = skipped.get(kind, 0) + 1
                    continue
                iz = float(s["Iz"])
                iy = float(s.get("Iy") or iz)
                young = float(s["E"])
                frames[e["id"]] = _Frame(
                    id=e["id"],
                    name=str(e.get("name") or e["id"]),
                    i=nodes[0],
                    j=nodes[1],
                    length=length,
                    axes=np.array([x, y, z]),
                    E=young,
                    A=float(s["A"]),
                    Iz=iz,
                    Iy=iy,
                    G=float(s.get("G") or young / 2.4),
                    J=float(s.get("J") or (iz + iy)),
                )
            else:
                m = materials.get(e.get("material_id"), {})
                if not m.get("E"):
                    skipped[kind] = skipped.get(kind, 0) + 1
                    continue
                frames[e["id"]] = _Frame(
                    id=e["id"],
                    name=str(e.get("name") or e["id"]),
                    i=nodes[0],
                    j=nodes[1],
                    length=length,
                    axes=np.array([x, y, z]),
                    E=float(m["E"]),
                    A=float(e["area"]),
                    Iz=0.0,
                    Iy=0.0,
                    G=0.0,
                    J=0.0,
                    truss=True,
                )
        elif kind != "ZeroLength":
            skipped[str(kind)] = skipped.get(str(kind), 0) + 1
    return frames, skipped


def _springs(project: dict[str, Any]) -> list[tuple[int, int, int, float]]:
    """Zero-length links on elastic materials: (node i, node j, DOF 0-5, stiffness)."""
    materials = {m["id"]: m for m in project.get("materials", [])}
    out = []
    for e in project.get("elements", []):
        if e.get("type") != "ZeroLength" or e.get("orient_x") or e.get("orient_y"):
            continue
        i, j = e["nodes"][:2]
        for mid, dof in zip(e.get("material_ids", []), e.get("dofs", []), strict=False):
            m = materials.get(mid, {})
            if m.get("type") == "Elastic" and m.get("E"):
                out.append((i, j, int(dof) - 1, float(m["E"])))
    return out


# ─────────────────────────────────────── assembly ───────────────────────────────────────


def _transformation(project: dict[str, Any], active: set[int]) -> tuple[Any, list[int]]:
    """The sparse map T from the independent DOFs to all DOFs of the ``active`` nodes (u = T q)
    and the node order: restraints drop DOFs, constraints tie them to their retained node's."""
    from scipy import sparse

    coords = {n["id"]: np.asarray(n["coords"], dtype=float) for n in project.get("nodes", [])}
    restraint = {n["id"]: list(n.get("restraint") or [False] * 6) for n in project.get("nodes", [])}
    ties: dict[tuple[int, int], dict[tuple[int, int], float]] = {}
    nodes = set(active)

    def rigid(slave: int, master: int, dofs: list[int], rotations: list[int]) -> None:
        d = coords[slave] - coords[master]
        for k in dofs:
            terms: dict[tuple[int, int], float] = {(master, k): 1.0}
            for r in rotations:  # u_k += (e_r × d)_k θ_r
                e = np.zeros(3)
                e[r] = 1.0
                c = float(np.cross(e, d)[k])
                if abs(c) > 0:
                    terms[(master, 3 + r)] = c
            ties[(slave, k)] = terms
        for r in rotations:
            ties[(slave, 3 + r)] = {(master, 3 + r): 1.0}

    for c in project.get("mp_constraints", []):
        master = int(c["retained_node"])
        kind = c.get("type")
        if kind == "RigidDiaphragm":
            p = int(c.get("perp_dir", 3)) - 1
            plane = [k for k in range(3) if k != p]
            for slave in c["constrained_nodes"]:
                if slave in active:
                    rigid(slave, master, plane, [p])
                    nodes.add(master)
        elif kind == "RigidLinkBeam":
            slave = int(c["constrained_node"])
            if slave in active:
                rigid(slave, master, [0, 1, 2], [0, 1, 2])
                nodes.add(master)
        else:  # equalDOF
            slave = int(c["constrained_node"])
            if slave in active:
                for dof in c.get("dofs", []):
                    ties[(slave, int(dof) - 1)] = {(master, int(dof) - 1): 1.0}
                nodes.add(master)
    order = sorted(nodes)
    column: dict[tuple[int, int], int] = {}
    for n in order:
        for k in range(6):
            if (n, k) not in ties and not restraint.get(n, [False] * 6)[k]:
                column[(n, k)] = len(column)
    rows, cols, vals = [], [], []
    position = {n: index for index, n in enumerate(order)}
    for n in order:
        for k in range(6):
            row = 6 * position[n] + k
            if restraint.get(n, [False] * 6)[k]:
                continue
            terms = ties.get((n, k), {(n, k): 1.0})
            for key, value in terms.items():
                if key in column:  # a restrained or tied master DOF contributes nothing
                    rows.append(row)
                    cols.append(column[key])
                    vals.append(value)
    t = sparse.csr_matrix((vals, (rows, cols)), shape=(6 * len(order), len(column)))
    return t, order


def _assemble(
    frames: dict[int, _Frame],
    springs: list[tuple[int, int, int, float]],
    axial: dict[int, float],
    position: dict[int, int],
    size: int,
):
    from scipy import sparse

    rows: list[np.ndarray] = []
    cols: list[np.ndarray] = []
    k_vals: list[np.ndarray] = []
    g_vals: list[np.ndarray] = []
    for f in frames.values():
        t = _rotation(f.axes)
        ke = t.T @ frame_stiffness(f) @ t
        kg = t.T @ frame_geometric(f, axial.get(f.id, 0.0)) @ t
        dofs = np.concatenate([6 * position[f.i] + np.arange(6), 6 * position[f.j] + np.arange(6)])
        r, c = np.meshgrid(dofs, dofs, indexing="ij")
        rows.append(r.ravel())
        cols.append(c.ravel())
        k_vals.append(ke.ravel())
        g_vals.append(kg.ravel())
    for i, j, dof, stiffness in springs:
        if i not in position or j not in position:
            continue
        a, b = 6 * position[i] + dof, 6 * position[j] + dof
        rows.append(np.array([a, a, b, b]))
        cols.append(np.array([a, b, a, b]))
        k_vals.append(stiffness * np.array([1.0, -1.0, -1.0, 1.0]))
        g_vals.append(np.zeros(4))
    r, c = np.concatenate(rows), np.concatenate(cols)
    k = sparse.csr_matrix((np.concatenate(k_vals), (r, c)), shape=(size, size))
    g = sparse.csr_matrix((np.concatenate(g_vals), (r, c)), shape=(size, size))
    return k, g


def linear_buckling(
    project: dict[str, Any], axial: dict[int, float], modes: int = 6
) -> BucklingResult:
    """The first ``modes`` critical load factors of the frame under the axial forces ``axial``
    (element id -> N, tension positive) and their mode shapes."""
    from scipy import sparse

    frames, skipped = frames_of(project)
    if not frames:
        raise BucklingError("the model has no elastic frames to analyse for buckling")
    if not any(axial.get(f, 0.0) < -N_SMALL for f in frames):
        raise BucklingError("no member is in compression under these loads")
    springs = _springs(project)
    active = {n for f in frames.values() for n in (f.i, f.j)}
    # A link counts when one of its nodes is on a frame; its other node joins the model.
    for i, j, _, _ in springs:
        if i in active or j in active:
            active |= {i, j}
    t, order = _transformation(project, active)
    position = {n: k for k, n in enumerate(order)}
    k_full, g_full = _assemble(frames, springs, axial, position, 6 * len(order))
    k = (t.T @ k_full @ t).tocsc()
    g = (t.T @ g_full @ t).tocsc()
    # DOFs with no stiffness (a truss node's rotations) are left out.
    keep = np.flatnonzero(np.abs(k.diagonal()) > 1e-12 * max(abs(k.diagonal()).max(), 1.0))
    k, g = k[keep][:, keep], g[keep][:, keep]
    n = len(keep)
    count = max(1, min(modes, n - 2))
    if n <= DENSE_MAX:
        from scipy.linalg import LinAlgError, eigh

        try:
            mu, vectors = eigh(-g.toarray(), k.toarray())
        except LinAlgError as error:
            raise BucklingError(
                "the frame is unstable on its own (a mechanism without the walls or slabs)"
            ) from error
        order_mu = np.argsort(mu)[::-1][:count]
        mu, vectors = mu[order_mu], vectors[:, order_mu]
    else:
        from scipy.sparse.linalg import eigsh

        try:
            mu, vectors = eigsh(-g, k=count, M=k, which="LA")
        except (RuntimeError, ValueError) as error:
            raise BucklingError(
                f"the eigenvalue solver failed: {error} (is the frame stable on its own?)"
            ) from error
        order_mu = np.argsort(mu)[::-1]
        mu, vectors = mu[order_mu], vectors[:, order_mu]
    factors: list[float] = []
    shapes: list[dict[int, np.ndarray]] = []
    expand = sparse.csr_matrix((np.ones(n), (keep, np.arange(n))), shape=(t.shape[1], n))
    for value, vector in zip(mu, vectors.T, strict=True):
        if value <= 0:
            continue  # only buckling under the loads as they act, not reversed
        full = t @ (expand @ vector)
        shape = full.reshape(-1, 6)
        peak = float(np.abs(shape[:, :3]).max()) or float(np.abs(shape).max()) or 1.0
        factors.append(1.0 / float(value))
        shapes.append({node: shape[k] / peak for k, node in enumerate(order)})
    return BucklingResult(
        factors=factors,
        modes=shapes,
        frames=frames,
        axial={f: axial.get(f, 0.0) for f in frames},
        skipped=skipped,
        dofs=n,
    )


# ─────────────────────────────────── effective lengths ───────────────────────────────────


def effective_length_factor(ei: float, length: float, pcr: float) -> float | None:
    """K = (π / L) √(E I / Pcr) (Euler: Pcr = π² E I / (K L)²); None above K_SHOWN_MAX."""
    if pcr <= 0 or ei <= 0 or length <= 0:
        return None
    k = math.pi / length * math.sqrt(ei / pcr)
    return k if k <= K_SHOWN_MAX else None


def member_effective_lengths(
    result: BucklingResult, members: list[tuple[str, list[int]]]
) -> list[dict[str, Any]]:
    """Per member (name, its analysis pieces' element ids) in compression: its length, the
    largest compression N along it, Pcr = λ1 |N|, and K about the section's strong and weak
    axes (from the first piece's section)."""
    if not result.factors:
        return []
    lam = result.factors[0]
    rows = []
    for name, ids in members:
        pieces = [result.frames[i] for i in ids if i in result.frames]
        if not pieces:
            continue
        compression = -min(result.axial.get(p.id, 0.0) for p in pieces)
        if compression <= N_SMALL:
            continue
        length = sum(p.length for p in pieces)
        first = pieces[0]
        pcr = lam * compression
        strong, weak = max(first.Iz, first.Iy), min(first.Iz, first.Iy)
        rows.append(
            {
                "member": name,
                "length": length,
                "N": compression,
                "Pcr": pcr,
                "Kmajor": effective_length_factor(first.E * strong, length, pcr)
                if not first.truss
                else None,
                "Kminor": effective_length_factor(first.E * weak, length, pcr)
                if not first.truss
                else None,
            }
        )
    return rows


def mode_shares(shape: dict[int, np.ndarray]) -> tuple[float, float, float]:
    """Shares of the mode's translations along X, Y and Z (sums of squares, 0-1)."""
    if not shape:
        return 0.0, 0.0, 0.0
    t = np.array([v[:3] for v in shape.values()])
    squares = (t**2).sum(axis=0)
    total = float(squares.sum()) or 1.0
    return tuple(float(s / total) for s in squares)  # type: ignore[return-value]
