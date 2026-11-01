"""The equivalent frame method of two-way slab systems (method id ``equivalentFrame`` of the
code pack's ``slabMethods``; the default pack's BNBC 2020 Part 6 Sec 6.5.7).

Each frame (:class:`saengine.design.slab_frames.SlabFrame`) is analysed for gravity load as a
continuous slab-beam on its supports, the columns' far ends fixed (the separate analysis of one
floor that the method permits), by a beam finite-element model:

- slab-beam: Ecs Is with Is = l2 h³ / 12 between the support faces (plus the beam along the
  frame, Ecs Is (1 + αf)); from the support's centre to its face Is / (1 - c2/l2)²;
- each column support is an equivalent column, a rotational spring Kec with 1/Kec = 1/ΣKc +
  1/Kt (the columns and the torsional members in series, as the method's equivalent column);
  Kc of the columns above and below with their far ends fixed, rigid over the slab's depth at
  the joints (:func:`column_stiffness`); Kt = Σ ``torsionFactor`` Ecs C / (l2 (1 - c2/l2)³) of
  the torsional members on each side (C by Eq 6.6.86 of the slab c1 wide or the transverse
  beam with its flanges, whichever is larger), times (1 + αf) where a beam runs along the frame;
  a wall across the frame at least ``fixedWallShare`` l2 long is a fixed support, other
  walls and beams a rotational spring of Kt alone;
- live load: on all spans when L <= ``uniformLiveMax`` D (unfactored); otherwise also
  ``patternLiveShare`` of the factored live load on a span and every second span (positive
  moments) and on the two spans beside a support (negative moments), never less than with full
  live load everywhere;
- the negative moments are taken at the support faces, not farther than ``faceLimit`` l1 from
  the support's centre; they and the largest positive moment of each span are shared to the
  strips as the direct design method does (:func:`saengine.design.direct_design.distribute`).

The reduction of the moments to the direct design method's static moment that the method
permits for slabs within its limits is not used (conservative).

Units: mm, N, MPa; N·mm.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from saengine.design.slab_frames import FrameResult, Loads, SlabFrame, StripMoment, clause

#: EI multiplier of the parts taken as rigid (within a joint).
RIGID = 1e6
#: Elements between the support faces of a span.
SUBDIVISIONS = 12


def _element(ei: float, length: float) -> np.ndarray:
    k = ei / length**3
    L = length
    return k * np.array(
        [
            [12, 6 * L, -12, 6 * L],
            [6 * L, 4 * L**2, -6 * L, 2 * L**2],
            [-12, -6 * L, 12, -6 * L],
            [6 * L, 2 * L**2, -6 * L, 4 * L**2],
        ]
    )


def column_stiffness(height: float, ei: float, near: float, far: float = 0.0) -> float:
    """Rotational stiffness [N·mm] at the near end of a column ``height`` long (centre to
    centre of the slabs), far end fixed, rigid over ``near``/2 at the near end and ``far``/2 at
    the far end (the slabs' depths: Ic infinite from top to bottom of the slab-beam)."""
    a, b = near / 2, far / 2
    flexible = height - a - b
    if flexible <= 0 or ei <= 0:
        return 0.0
    xs = [0.0, a, height - b, height] if b > 0 else [0.0, a, height]
    xs = sorted(set(xs))
    n = len(xs)
    size = 2 * n
    K = np.zeros((size, size))
    for i in range(n - 1):
        length = xs[i + 1] - xs[i]
        rigid = (xs[i] < a - 1e-9) or (xs[i] >= height - b - 1e-9 and b > 0)
        idx = [2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3]
        K[np.ix_(idx, idx)] += _element(ei * (RIGID if rigid else 1.0), length)
    # Near end: w = 0, θ = 1; far end fixed.
    free = [d for d in range(2, size - 2)]
    u = np.zeros(size)
    u[1] = 1.0
    if free:
        rhs = -K[np.ix_(free, [1])][:, 0]
        u[free] = np.linalg.solve(K[np.ix_(free, free)], rhs)
    return float((K @ u)[1])


def torsional_stiffness(frame: SlabFrame, support: int, rules: Any, shape: float) -> float:
    """Kt [N·mm] of the torsional members on each side of a support (Eq 6.6.88)."""
    from saengine.design.direct_design import torsion_constant, torsional_parts

    s = frame.supports[support]
    c = torsion_constant(torsional_parts(s.c1, frame.h, s.transverse_beam, shape), shape)
    total = 0.0
    for l2 in frame.panels():
        c2 = min(s.c2, 0.95 * l2)
        total += float(rules.torsionFactor) * frame.ecs * c / (l2 * (1 - c2 / l2) ** 3)
    adjacent = [frame.alpha[k] for k in (support - 1, support) if 0 <= k < len(frame.alpha)]
    return total * (1 + max(adjacent, default=0.0))


class _Model:
    """The slab-beam of a frame as beam elements, with its supports."""

    def __init__(self, frame: SlabFrame, rules: Any, uniform_share: float, shape: float):
        self.frame = frame
        xs: list[float] = []
        self.faces: list[tuple[float, float]] = []  # per span (start face, end face)
        spans = frame.spans
        for k, l1 in enumerate(spans):
            a, b = frame.supports[k], frame.supports[k + 1]
            limit = float(rules.faceLimit) * l1
            fa, fb = a.at + min(a.c1 / 2, limit), b.at - min(b.c1 / 2, limit)
            self.faces.append((fa, fb))
            inner = np.linspace(a.at + a.c1 / 2, b.at - b.c1 / 2, SUBDIVISIONS + 1)
            xs += [a.at, fa, *inner.tolist(), fb, b.at]
        self.x = np.array(sorted({round(v, 6) for v in xs}))
        is_ = frame.l2 * frame.h**3 / 12
        n = len(self.x)
        self.K = np.zeros((2 * n, 2 * n))
        self.elements: list[tuple[int, float, float, int]] = []  # (node, length, EI, span)
        for i in range(n - 1):
            x0, x1 = self.x[i], self.x[i + 1]
            mid = (x0 + x1) / 2
            k = int(np.searchsorted([s.at for s in frame.supports], mid) - 1)
            k = min(max(k, 0), len(spans) - 1)
            a, b = frame.supports[k], frame.supports[k + 1]
            ei = frame.ecs * is_ * (1 + (frame.alpha[k] if frame.alpha else 0.0))
            for s in (a, b):
                if abs(mid - s.at) < s.c1 / 2:
                    c2 = min(s.c2, 0.95 * frame.l2)
                    ei = frame.ecs * is_ / (1 - c2 / frame.l2) ** 2
            idx = [2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3]
            self.K[np.ix_(idx, idx)] += _element(ei, x1 - x0)
            self.elements.append((i, x1 - x0, ei, k))
        self.support_nodes = [int(np.argmin(abs(self.x - s.at))) for s in frame.supports]
        self.springs: list[float] = []
        for j, s in enumerate(frame.supports):
            kt = torsional_stiffness(frame, j, rules, shape)
            if s.kind == "wall" and s.wall_length >= uniform_share * frame.l2:
                kec = float("inf")
            elif s.kind == "column" and s.column_k > 0:
                kec = 1 / (1 / s.column_k + 1 / kt) if kt > 0 else s.column_k
            else:
                kec = kt
            self.springs.append(kec)

    def solve(self, loads: list[float]) -> tuple[np.ndarray, list[float]]:
        """Moments (sagging positive) at every node [N·mm] and the moments the equivalent
        columns take [N·mm] under uniform line loads ``loads`` [N/mm] per span."""
        n = len(self.x)
        K = self.K.copy()
        F = np.zeros(2 * n)
        for i, length, _, k in self.elements:
            q = loads[k]
            F[2 * i : 2 * i + 4] += [
                -q * length / 2,
                -q * length**2 / 12,
                -q * length / 2,
                q * length**2 / 12,
            ]
        fixed = []
        for node, spring in zip(self.support_nodes, self.springs, strict=True):
            fixed.append(2 * node)
            if spring == float("inf"):
                fixed.append(2 * node + 1)
            elif spring > 0:
                K[2 * node + 1, 2 * node + 1] += spring
        free = [d for d in range(2 * n) if d not in fixed]
        u = np.zeros(2 * n)
        u[free] = np.linalg.solve(K[np.ix_(free, free)], F[free])
        moments = np.zeros(n)
        counts = np.zeros(n)
        for i, length, ei, k in self.elements:
            q = loads[k]
            idx = slice(2 * i, 2 * i + 4)
            f0 = np.array(
                [-q * length / 2, -q * length**2 / 12, -q * length / 2, q * length**2 / 12]
            )
            end = _element(ei, length) @ u[idx] - f0
            moments[i] += -end[1]
            moments[i + 1] += end[3]
            counts[i] += 1
            counts[i + 1] += 1
        moments /= np.maximum(counts, 1)
        column = [
            (spring * u[2 * node + 1] if np.isfinite(spring) else 0.0)
            for node, spring in zip(self.support_nodes, self.springs, strict=True)
        ]
        return moments, column

    def at(self, moments: np.ndarray, x: float) -> float:
        return float(moments[int(np.argmin(abs(self.x - x)))])


def patterns(frame: SlabFrame, loads: Loads, rules: Any) -> list[tuple[str, list[float], str]]:
    """The load cases: (combination, line load per span [N/mm], what)."""
    spans = len(frame.spans)
    out = []
    pattern = loads.live > float(rules.uniformLiveMax) * loads.dead
    share = float(rules.patternLiveShare)
    for name, qd, ql in loads.factored():
        out.append((name, [(qd + ql) * frame.l2] * spans, "full live load on all spans"))
        if not pattern or ql <= 0:
            continue
        for start in (0, 1):
            q = [
                (qd + (share * ql if (k - start) % 2 == 0 else 0.0)) * frame.l2
                for k in range(spans)
            ]
            out.append((name, q, f"{share:g} L on alternate spans"))
        for j in range(1, spans):
            q = [(qd + (share * ql if k in (j - 1, j) else 0.0)) * frame.l2 for k in range(spans)]
            out.append((name, q, f"{share:g} L on the two spans beside support {j}"))
    return out


def design_frame(
    frame: SlabFrame, loads: Loads, rules: Any, strips: Any, within: bool = False
) -> FrameResult:
    """The strip moments of a frame by the equivalent frame method (the module notes).
    ``strips``: the direct design method's rules, whose strip tables share the moments (None:
    the column strip takes all of them, conservative)."""
    from saengine.design.direct_design import distribute

    result = FrameResult("equivalentFrame", frame)
    shape = float(rules.torsionShape)
    uniform = float(rules.fixedWallShare)
    model = _Model(frame, rules, uniform, shape)
    last = len(frame.supports) - 1
    worst: dict[tuple[int, str], tuple[float, str, str]] = {}
    for name, q, what in patterns(frame, loads, rules):
        moments, column = model.solve(q)
        for k, (fa, fb) in enumerate(model.faces):
            inside = (model.x >= fa - 1e-6) & (model.x <= fb + 1e-6)
            positive = float(moments[inside].max()) if inside.any() else 0.0
            for key, value in (
                ((k, "start"), model.at(moments, fa)),
                ((k, "positive"), positive),
                ((k, "end"), model.at(moments, fb)),
            ):
                sign = value if key[1] == "positive" else -value
                if sign > worst.get(key, (0.0, "", ""))[0]:
                    worst[key] = (sign, name, what)
        for j, m in enumerate(column):
            if frame.supports[j].kind != "column":
                continue
            old = result.column_moments.get(j)
            if old is None or abs(m) > abs(old[0]):
                result.column_moments[j] = (m, name, f"equivalent column, {what}")
    for (k, where), (value, name, what) in sorted(worst.items()):
        note = f"{what}; face at most {rules.faceLimit:g} l1 from the centre ({clause('face')})"
        if where == "positive":
            moments = (
                distribute(frame, k, "positive", value, name, strips, None, note)
                if strips is not None
                else [
                    StripMoment(
                        k, "positive", "column", value, frame.column_strip(k)[0], name, note
                    )
                ]
            )
        else:
            support = k if where == "start" else k + 1
            kind = "exterior" if support in (0, last) else "interior"
            moments = (
                distribute(frame, k, kind, value, name, strips, support, note)
                if strips is not None
                else [
                    StripMoment(
                        k,
                        f"negative at support {support}",
                        "column",
                        value,
                        frame.column_strip(k)[0],
                        name,
                        note,
                    )
                ]
            )
        result.moments += moments
    if within:
        result.notes.append(
            f"{frame.name}: within the direct design method's limits; the moments are not "
            "reduced to its static moment (permitted, not used: conservative)"
        )
    if strips is None:
        result.notes.append(
            f"{frame.name}: the code pack gives no strip shares; the column strip takes the "
            "whole frame moment (conservative)"
        )
    return result
