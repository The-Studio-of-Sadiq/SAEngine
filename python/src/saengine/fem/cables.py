"""Cables: the elastic catenary in closed form and cables as tension-only large-displacement
truss chains in OpenSees (alpha 9 track L4).

**Elastic catenary** (:func:`elastic_catenary`; Irvine, "Cable Structures", 1981, Ch 1): a
cable of unstressed length L0, weight w per unstressed length and axial stiffness EA hung
between A = (0, 0) and B = (l, h). With H the horizontal component of its tension and V the
vertical reaction at A (upward), the tension's vertical component at the Lagrangian coordinate
s from A is Tv = w s - V, T = √(H² + Tv²), and

    x(s) = H s / EA + (H / w) [asinh((w s - V) / H) + asinh(V / H)]
    z(s) = (w s² / 2 - V s) / EA + (H / w) [√(1 + ((w s - V) / H)²) - √(1 + (V / H)²)]

The two conditions x(L0) = l and z(L0) = h are solved for H and V by Newton's method from the
parabolic estimate. The sag is the largest vertical distance of the cable below its chord.

**Finite element cables** (:func:`add_cable`, :func:`cable_fe`): the cable is cut into
``segments`` co-rotational trusses (``corotTruss``: large displacements and rotations, the
geometric stiffness of the tension) on a tension-only elastic material (``Elastic`` with no
stiffness in compression) wrapped in an initial strain (``InitStrainMaterial``): the
pretension T0 is the lack of fit ε0 = T0 / (E A) of a cable whose stress-free length is the
chord / (1 + ε0). A slack segment carries nothing. The interior nodes carry the cable's own
weight (per unstressed length) and their rotations are fixed (a truss has none).

What is not modelled: bending stiffness of strands, the cable's creep and the clamps' slip;
temperature changes (an added initial strain would model them).

Units: N, m.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: Newton iterations of the catenary's two conditions at most, and their tolerance [m].
CATENARY_ITERATIONS = 100
CATENARY_TOLERANCE = 1e-10
#: Points along the cable at which the sag is looked for.
SAG_POINTS = 401


class CableError(ValueError):
    """The cable cannot be solved (no weight, a cable too short for its stiffness, ...)."""


@dataclass
class CatenaryResult:
    """The elastic catenary: H, the vertical reactions at A and B (upward), the end tensions,
    the sag below the chord [m] and where it is (horizontal distance from A)."""

    H: float
    Va: float
    Vb: float
    tensionA: float
    tensionB: float
    sag: float
    sagAt: float


def _shape(s: np.ndarray | float, h_force: float, v: float, w: float, ea: float):
    """x(s), z(s) of the elastic catenary (module notes)."""
    a = (w * np.asarray(s) - v) / h_force
    b = v / h_force
    x = h_force * np.asarray(s) / ea + h_force / w * (np.arcsinh(a) + np.arcsinh(b))
    z = (w * np.asarray(s) ** 2 / 2 - v * np.asarray(s)) / ea + h_force / w * (
        np.sqrt(1 + a**2) - np.sqrt(1 + b**2)
    )
    return x, z


def parabolic_sag(w: float, span: float, horizontal: float) -> float:
    """The sag of a shallow cable at mid-span, f = w l² / (8 H) (w per horizontal length)."""
    return w * span**2 / (8 * horizontal)


def elastic_catenary(
    span: float, rise: float, w: float, ea: float, length: float
) -> CatenaryResult:
    """The elastic catenary of unstressed ``length`` L0 between A = (0, 0) and B = (``span``,
    ``rise``) under its weight ``w`` [N/m of unstressed length], ``ea`` = E A [N]."""
    if span <= 0 or w <= 0 or ea <= 0 or length <= 0:
        raise CableError("the span, weight, EA and length must be positive")
    chord = math.hypot(span, rise)
    total = w * length
    if length > chord:
        f = math.sqrt(3 * chord * (length - chord) / 8)
        h_force = max(total * span / (8 * f), 1e-6 * total)
    else:  # taut: the stretch carries the tension
        h_force = ea * (chord - length) / length * span / chord + total
    v = total / 2 - h_force * rise / span
    unknowns = np.array([h_force, v])
    for _ in range(CATENARY_ITERATIONS):
        x, z = _shape(length, unknowns[0], unknowns[1], w, ea)
        residual = np.array([float(x) - span, float(z) - rise])
        if np.abs(residual).max() < CATENARY_TOLERANCE * max(chord, 1.0):
            break
        jacobian = np.zeros((2, 2))
        for k in range(2):
            step = 1e-7 * max(abs(unknowns[k]), total)
            moved = unknowns.copy()
            moved[k] += step
            xs, zs = _shape(length, moved[0], moved[1], w, ea)
            jacobian[:, k] = (np.array([float(xs) - span, float(zs) - rise]) - residual) / step
        delta = np.linalg.solve(jacobian, -residual)
        # Keep H positive: halve the step until it is.
        scale = 1.0
        while unknowns[0] + scale * delta[0] <= 0:
            scale /= 2
        unknowns = unknowns + scale * delta
    else:
        raise CableError("the elastic catenary did not converge")
    h_force, v = (float(u) for u in unknowns)
    s = np.linspace(0.0, length, SAG_POINTS)
    xs, zs = _shape(s, h_force, v, w, ea)
    below = rise / span * xs - zs
    k = int(np.argmax(below))
    vb = total - v
    return CatenaryResult(
        H=h_force,
        Va=v,
        Vb=vb,
        tensionA=math.hypot(h_force, v),
        tensionB=math.hypot(h_force, vb),
        sag=float(below[k]),
        sagAt=float(xs[k]),
    )


# ─────────────────────────────────── cables in OpenSees ───────────────────────────────────


@dataclass
class CableHandle:
    """A cable added to an OpenSees model: its nodes from end to end (the ends are the
    model's), its elements, its name and its resistance [N] (None: not checked)."""

    name: str
    nodes: list[int]
    elements: list[int]
    area: float
    modulus: float
    pretension: float
    resistance: float | None = None
    notes: list[str] = field(default_factory=list)


def add_cable(
    ops: Any,
    name: str,
    ends: tuple[int, int],
    coords: tuple[np.ndarray, np.ndarray],
    area: float,
    modulus: float,
    pretension: float,
    segments: int,
    tags: dict[str, int],
    ndf: int = 6,
    resistance: float | None = None,
) -> CableHandle:
    """Add a straight cable between the model's nodes ``ends`` (at ``coords``) cut into
    ``segments`` co-rotational tension-only trusses with the ``pretension`` [N] as an initial
    strain. ``tags`` holds the next free ``node``, ``element`` and ``material`` tags and is
    advanced. Returns the cable's handle."""
    if pretension <= 0:
        raise CableError(
            f"cable {name}: a cable needs a pretension (a straight slack cable has no stiffness)"
        )
    a, b = (np.asarray(c, dtype=float) for c in coords)
    base = tags["material"]
    # E, eta, Eneg: a negligible slack stiffness (1e-6 E) keeps the tangent regular when a
    # segment goes slack during the iterations (as cable_fe).
    ops.uniaxialMaterial("Elastic", base, float(modulus), 0.0, float(modulus) * 1e-6)
    ops.uniaxialMaterial("InitStrainMaterial", base + 1, base, float(pretension / (modulus * area)))
    tags["material"] = base + 2
    nodes = [ends[0]]
    for k in range(1, segments):
        tag = tags["node"]
        tags["node"] += 1
        p = a + (b - a) * k / segments
        ops.node(tag, *(float(v) for v in p))
        if ndf == 6:
            ops.fix(tag, 0, 0, 0, 1, 1, 1)
        nodes.append(tag)
    nodes.append(ends[1])
    elements = []
    for i, j in itertools.pairwise(nodes):
        tag = tags["element"]
        tags["element"] += 1
        ops.element("corotTruss", tag, i, j, float(area), base + 1)
        elements.append(tag)
    return CableHandle(name, nodes, elements, area, modulus, pretension, resistance)


def cable_weight_loads(cable: CableHandle, w: np.ndarray, length: float) -> dict[int, np.ndarray]:
    """The cable's distributed load ``w`` [N/m, global X, Y, Z] over its ``length`` lumped at
    its nodes (half a segment's share at each end)."""
    share = np.asarray(w, dtype=float) * length / (len(cable.nodes) - 1)
    loads: dict[int, np.ndarray] = {}
    for k, node in enumerate(cable.nodes):
        loads[node] = share * (0.5 if k in (0, len(cable.nodes) - 1) else 1.0)
    return loads


def _axial(ops: Any, element: int) -> float:
    for key in ("axialForce", "basicForce", "basicForces"):
        try:
            value = ops.eleResponse(element, key)
        except Exception:  # noqa: BLE001, S112 - a response this build does not give
            continue
        if value:
            return float(value[0])
    return 0.0


def cable_state(ops: Any, cable: CableHandle) -> dict[str, Any]:
    """The cable's state in the model now: its largest and least tension [N], the sag below
    its chord (vertical, [m]), the slack segments and its utilisation (largest tension over
    its resistance)."""
    tensions = [_axial(ops, e) for e in cable.elements]
    points = [
        np.asarray(ops.nodeCoord(n), dtype=float) + np.asarray(ops.nodeDisp(n)[:3])
        for n in cable.nodes
    ]
    a, b = points[0], points[-1]
    sag = 0.0
    horizontal = float(np.linalg.norm((b - a)[:2]))
    for p in points[1:-1]:
        if horizontal > 1e-9:
            t = float(np.dot((p - a)[:2], (b - a)[:2])) / horizontal**2
        else:  # a vertical cable has no sag
            continue
        chord_z = a[2] + t * (b[2] - a[2])
        sag = max(sag, float(chord_z - p[2]))
    largest = max(tensions, default=0.0)
    return {
        "cable": cable.name,
        "maxTension": largest,
        "minTension": min(tensions, default=0.0),
        "sag": sag,
        "slack": sum(1 for t in tensions if t <= 1e-6 * max(cable.pretension, 1.0)),
        "segments": len(tensions),
        "pretension": cable.pretension,
        "resistance": cable.resistance,
        "utilisation": largest / cable.resistance if cable.resistance else None,
    }


def cable_fe(
    span: float,
    rise: float,
    w: float,
    ea: float,
    length: float,
    segments: int = 20,
    ops: Any = None,
) -> dict[str, Any]:
    """The same cable as :func:`elastic_catenary` solved as ``segments`` co-rotational
    tension-only trusses (a check of the element against the closed form): ``{"H", "Va",
    "sag", "maxTension", "nodes"}``. The cable starts as a parabola a little longer than its
    unstressed length (so that every segment is in tension) and takes its whole weight in
    load steps."""
    if ops is None:
        from openseespy import opensees as ops
    chord = math.hypot(span, rise)
    area = 1.0
    modulus = ea / area
    ops.wipe()
    ops.model("basic", "-ndm", 2, "-ndf", 2)
    # The starting shape: the parabola whose length is the unstressed length stretched by the
    # tension its own sag would carry (H = w L^2 / 8 f), so the chain starts near equilibrium
    # under its whole weight (a much longer or shorter start leaves Newton far from it).
    f0 = math.sqrt(3 * chord * (length - chord) / 8) if length > chord else 0.0
    stretch = w * span**2 / (8 * f0 * ea) if f0 > 0 else 1e-6
    stretched = length * (1 + stretch)
    f = math.sqrt(3 * chord * (stretched - chord) / 8) if stretched > chord else 0.0
    xs = np.linspace(0.0, span, segments + 1)
    zs = rise * xs / span - 4 * f * xs / span * (1 - xs / span)
    for k, (x, z) in enumerate(zip(xs, zs, strict=True)):
        ops.node(k + 1, float(x), float(z))
    ops.fix(1, 1, 1)
    ops.fix(segments + 1, 1, 1)
    # Each segment's unstressed length is its share of the cable's, in proportion to its length
    # in the start shape: every segment then starts in the same tension (equal unstressed
    # lengths would leave the parabola's flatter middle segments in compression, without
    # stiffness in a tension-only cable, and the first tangent singular).
    drawn = [math.hypot(xs[k + 1] - xs[k], zs[k + 1] - zs[k]) for k in range(segments)]
    unstressed = [lg * length / sum(drawn) for lg in drawn]
    for k in range(segments):
        # Slack: a negligible stiffness (1e-6 E) keeps the tangent regular while a segment
        # goes slack during the iterations; it carries no compression of any size.
        ops.uniaxialMaterial("Elastic", 2 * k + 1, modulus, 0.0, modulus * 1e-6)
        ops.uniaxialMaterial(
            "InitStrainMaterial", 2 * k + 2, 2 * k + 1, drawn[k] / unstressed[k] - 1.0
        )
        ops.element("corotTruss", k + 1, k + 1, k + 2, area, 2 * k + 2)
    ops.timeSeries("Linear", 1)
    ops.pattern("Plain", 1, 1)
    for k in range(2, segments + 1):  # each node carries the weight of its half-segments
        ops.load(k, 0.0, -w * (unstressed[k - 2] + unstressed[k - 1]) / 2)
    ops.constraints("Plain")
    ops.numberer("RCM")
    ops.system("UmfPack")
    ops.test("NormDispIncr", 1e-10, 200)
    ops.algorithm("Newton")
    steps = 1  # the start is near equilibrium under the whole weight (above)
    ops.integrator("LoadControl", 1.0 / steps)
    ops.analysis("Static")
    if ops.analyze(steps) != 0:
        ops.wipe()
        raise CableError("the finite element cable did not converge")
    ops.reactions()
    reaction = ops.nodeReaction(1)
    points = [
        np.asarray(ops.nodeCoord(k + 1)) + np.asarray(ops.nodeDisp(k + 1))
        for k in range(segments + 1)
    ]
    a, b = points[0], points[-1]
    sag = max(
        float(a[1] + (p[0] - a[0]) / (b[0] - a[0]) * (b[1] - a[1]) - p[1]) for p in points[1:-1]
    )
    tension = max(_axial(ops, k + 1) for k in range(segments))
    ops.wipe()
    return {
        "H": -float(reaction[0]),
        "Va": float(reaction[1]),
        "sag": sag,
        "maxTension": tension,
        "nodes": [p.tolist() for p in points],
    }
