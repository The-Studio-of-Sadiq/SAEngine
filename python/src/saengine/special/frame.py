"""Linear elastic 3D frames for the special structures, solved by OpenSeesPy (the engine of the
building's analysis model).

A :class:`Frame` is nodes [m], members between them with elastic sections and supports; each
load case (:class:`Loads`) gets nodal forces and uniform member loads in global axes. The model
is built afresh for every case (linear, small: the cases are independent and no state is
carried), and :func:`solve` returns per case the nodes' displacements, the support reactions and
every member's end forces in its local axes.

Local axes (as OpenSees' ``geomTransf`` builds them from ``vecxz``): x from the start to the end
of the member; ``vecxz`` is global Z, or global X for a vertical member; y = vecxz × x and z =
x × y. A horizontal member therefore has its local z up and bends in the vertical plane about
its local y. End forces are the forces the nodes put on the member, so for a member along x:
the axial force N (tension positive) is ``forces[6]``; the sagging moment (tension at the
bottom) at its start ``forces[4]`` and at its end ``-forces[10]``; the vertical shear V = dM/dx
at its start ``forces[2]`` and at its end ``-forces[8]``.

Units: m, N, Pa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Points closer than this are one node [m].
NODE_TOLERANCE = 1e-4


class FrameError(RuntimeError):
    """The frame could not be solved (a mechanism, or OpenSees failed)."""


@dataclass(frozen=True)
class Section:
    """Elastic section: area [m²], second moments about the local y and z axes and torsion
    constant [m⁴], moduli E and G [Pa], and mass per length [kg/m] (for self-weight)."""

    area: float
    iy: float
    iz: float
    j: float
    e: float
    g: float
    mass: float = 0.0


@dataclass
class Frame:
    nodes: list[np.ndarray] = field(default_factory=list)
    members: list[tuple[int, int, int]] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    supports: dict[int, tuple[int, int, int, int, int, int]] = field(default_factory=dict)
    _keys: dict[tuple[int, int, int], int] = field(default_factory=dict, repr=False)

    def node(self, point: Any) -> int:
        """The index of the node at ``point`` [m], added when there is none."""
        p = np.asarray(point, dtype=float)
        key = tuple(int(np.rint(v / NODE_TOLERANCE)) for v in p)
        found = self._keys.get(key)  # type: ignore[arg-type]
        if found is None:
            found = len(self.nodes)
            self.nodes.append(p)
            self._keys[key] = found  # type: ignore[index]
        return found

    def section(self, section: Section) -> int:
        if section in self.sections:
            return self.sections.index(section)
        self.sections.append(section)
        return len(self.sections) - 1

    def member(self, start: Any, end: Any, section: Section) -> int:
        """Adds a member between two points [m]; returns its index."""
        i, j = self.node(start), self.node(end)
        if i == j:
            raise ValueError("a member's ends are the same point")
        self.members.append((i, j, self.section(section)))
        return len(self.members) - 1

    def support(self, point: Any, fixity: tuple[int, int, int, int, int, int]) -> int:
        """Holds the node at ``point`` in the DOFs set to 1 (ux, uy, uz, rx, ry, rz); a node
        held twice keeps every DOF either holds."""
        n = self.node(point)
        old = self.supports.get(n, (0, 0, 0, 0, 0, 0))
        self.supports[n] = tuple(max(a, b) for a, b in zip(old, fixity, strict=True))  # type: ignore[assignment]
        return n

    def length(self, k: int) -> float:
        i, j, _ = self.members[k]
        return float(np.linalg.norm(self.nodes[j] - self.nodes[i]))

    def axes(self, k: int) -> tuple[np.ndarray, np.ndarray]:
        """(rotation matrix whose rows are the local x, y, z axes, vecxz) of member ``k``."""
        i, j, _ = self.members[k]
        return local_axes(self.nodes[i], self.nodes[j])


def local_axes(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = (b - a) / np.linalg.norm(b - a)
    vecxz = np.array([0.0, 0.0, 1.0]) if abs(x[2]) < 0.999 else np.array([1.0, 0.0, 0.0])
    y = np.cross(vecxz, x)
    y /= np.linalg.norm(y)
    z = np.cross(x, y)
    return np.vstack([x, y, z]), vecxz


@dataclass
class Loads:
    """One load case: nodal forces and moments (6 values, global, N and N·m) and uniform loads
    along members (3 values, global, N/m)."""

    nodal: dict[int, np.ndarray] = field(default_factory=dict)
    uniform: dict[int, np.ndarray] = field(default_factory=dict)

    def add_nodal(self, node: int, values: Any) -> None:
        v = np.zeros(6)
        given = np.asarray(values, dtype=float)
        v[: len(given)] = given
        self.nodal[node] = self.nodal.get(node, np.zeros(6)) + v

    def add_uniform(self, member: int, values: Any) -> None:
        v = np.asarray(values, dtype=float)
        self.uniform[member] = self.uniform.get(member, np.zeros(3)) + v

    def scaled(self, factor: float) -> Loads:
        return Loads(
            {k: v * factor for k, v in self.nodal.items()},
            {k: v * factor for k, v in self.uniform.items()},
        )

    def plus(self, other: Loads) -> Loads:
        out = Loads(
            {k: v.copy() for k, v in self.nodal.items()},
            {k: v.copy() for k, v in self.uniform.items()},
        )
        for k, v in other.nodal.items():
            out.add_nodal(k, v)
        for k, v in other.uniform.items():
            out.add_uniform(k, v)
        return out


@dataclass
class FrameResult:
    displacements: np.ndarray  # (nodes, 6)
    reactions: dict[int, np.ndarray]  # supported node -> 6 values
    forces: np.ndarray  # (members, 12) local end forces on the members

    def axial(self, k: int) -> float:
        """Axial force of member ``k`` [N], tension positive."""
        return float(self.forces[k, 6])

    def end_moments(self, k: int) -> tuple[float, float, float, float, float, float]:
        """(My, Mz at the start, My, Mz at the end, torsion, largest resultant bending) [N·m],
        as the member's internal moments (the end's moments with the start's sign turned)."""
        f = self.forces[k]
        my_i, mz_i, my_j, mz_j = f[4], f[5], -f[10], -f[11]
        largest = max(float(np.hypot(my_i, mz_i)), float(np.hypot(my_j, mz_j)))
        return (float(my_i), float(mz_i), float(my_j), float(mz_j), float(f[9]), largest)


def self_weight(frame: Frame, g: float = 9.80665) -> Loads:
    """The members' self-weight (their sections' mass per length) as uniform loads, down."""
    loads = Loads()
    for k, (_, _, s) in enumerate(frame.members):
        mass = frame.sections[s].mass
        if mass > 0:
            loads.add_uniform(k, [0.0, 0.0, -mass * g])
    return loads


def solve(frame: Frame, cases: dict[str, Loads]) -> dict[str, FrameResult]:
    """Each load case of ``cases`` on ``frame`` (a linear static analysis each)."""
    import openseespy.opensees as ops

    axes = [frame.axes(k) for k in range(len(frame.members))]
    out: dict[str, FrameResult] = {}
    try:
        for name, loads in cases.items():
            _build(ops, frame, axes)
            ops.timeSeries("Linear", 1)
            ops.pattern("Plain", 1, 1)
            for node, values in loads.nodal.items():
                ops.load(node + 1, *(float(v) for v in values))
            for k, w in loads.uniform.items():
                local = axes[k][0] @ np.asarray(w, dtype=float)
                ops.eleLoad(
                    "-ele",
                    k + 1,
                    "-type",
                    "-beamUniform",
                    float(local[1]),
                    float(local[2]),
                    float(local[0]),
                )
            ops.constraints("Plain")
            ops.numberer("RCM")
            ops.system("UmfPack")
            ops.integrator("LoadControl", 1.0)
            ops.algorithm("Linear")
            ops.analysis("Static")
            if ops.analyze(1) != 0:
                raise FrameError(f"load case {name}: the frame could not be solved (a mechanism?)")
            ops.reactions()
            n = len(frame.nodes)
            disp = np.array([ops.nodeDisp(t + 1) for t in range(n)], dtype=float).reshape(n, 6)
            if not np.all(np.isfinite(disp)):
                raise FrameError(f"load case {name}: the frame is a mechanism")
            reactions = {
                t: np.asarray(ops.nodeReaction(t + 1), dtype=float) for t in frame.supports
            }
            forces = np.zeros((len(frame.members), 12))
            for k in range(len(frame.members)):
                f = np.asarray(ops.eleForce(k + 1), dtype=float)
                r = axes[k][0]
                forces[k] = np.concatenate([r @ f[0:3], r @ f[3:6], r @ f[6:9], r @ f[9:12]])
            out[name] = FrameResult(disp, reactions, forces)
    finally:
        ops.wipe()
    return out


def _build(ops: Any, frame: Frame, axes: list[tuple[np.ndarray, np.ndarray]]) -> None:
    ops.wipe()
    ops.model("basic", "-ndm", 3, "-ndf", 6)
    for t, p in enumerate(frame.nodes):
        ops.node(t + 1, float(p[0]), float(p[1]), float(p[2]))
    for t, fixity in frame.supports.items():
        ops.fix(t + 1, *fixity)
    for k, (i, j, s) in enumerate(frame.members):
        sec = frame.sections[s]
        ops.geomTransf("Linear", k + 1, *(float(v) for v in axes[k][1]))
        ops.element(
            "elasticBeamColumn",
            k + 1,
            i + 1,
            j + 1,
            sec.area,
            sec.e,
            sec.g,
            sec.j,
            sec.iy,
            sec.iz,
            k + 1,
        )


def tube(
    outside: float, thickness: float, e: float, nu: float = 0.3, density: float = 0.0
) -> Section:
    """A circular tube of outside diameter and wall [m]."""
    r_o = outside / 2
    r_i = max(r_o - thickness, 0.0)
    area = np.pi * (r_o**2 - r_i**2)
    inertia = np.pi / 4 * (r_o**4 - r_i**4)
    return Section(area, inertia, inertia, 2 * inertia, e, e / (2 * (1 + nu)), area * density)
