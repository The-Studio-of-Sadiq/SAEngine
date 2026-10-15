"""Design checks of reinforced-concrete slabs from the shell forces of the analysis (ACI 318-19
strength design, which BNBC 2020 Part 6 Chapter 6 adopts).

Slabs are designed when the analysis meshes them as shells (Analysis settings: slabs as
shells). Each check envelopes every combination of the project settings and every integration
point of every shell of the slab (``S1``, ``S1#2``, ...): the moments at the points next to a
beam or a column give the support hogging, not just the element centres.

Axes. A slab's local x is global X for a slab of the floor plan (``SlabElement``) and the
direction of the first edge of its outline for a drawn area (``AreaElement``); local y is
"up" x local x, and up is global +Z (an area's normal, turned to point up). The reinforcement
layers ``bottomX``/``topX`` run along local x and resist the moment Mx (bending in the x-z
plane), ``bottomY``/``topY`` run along local y.

The analysis shells have their own local axes (OpenSees ASDShellQ4: local 1 from the middle of
side 4-1 to the middle of side 2-3, local 3 the normal of the diagonals' cross product;
ASDShellT3: local 1 along side 1-2), and report N11 N22 N12 M11 M22 M12 Q13 Q23 per unit
length at each integration point in them, with a positive M11 stretching the +3 face. The
moment tensor is turned into the slab's axes (``M' = R M Rᵀ``, ``R = [u·e]``), with the sign
set by which way local 3 faces, so that ``mx, my`` are sagging-positive (bottom in tension).

Wood-Armer design moments (Wood 1968, Armer's corrections), per unit width, at each point:

- bottom: Mx* = mx + |mxy|, My* = my + |mxy|; if Mx* < 0 then Mx* = 0 and
  My* = my + |mxy² / mx|; if My* < 0 then My* = 0 and Mx* = mx + |mxy² / my|; a value still
  negative needs no bottom bars (0);
- top (hogging, reported as magnitudes): Mx* = mx - |mxy|, My* = my - |mxy|; if Mx* > 0 then
  Mx* = 0 and My* = my - |mxy² / mx|; if My* > 0 then My* = 0 and Mx* = mx - |mxy² / my|; a
  value still positive needs no top bars (0).

Membrane forces (N11, N22, N12) are not included in the flexural design.

Layers. Per metre width, As = (π db² / 4) 1000 / s. The X layers are the outer ones (bottomX
lowest, topX highest): d = h - c - db/2 for an outer layer and h - c - db,outer - db/2 for an
inner one (a Y layer under an X layer of the same face; a Y layer is outer when its face has no
X layer). φMn = φ As fy (d - a/2), a = As fy / (0.85 f'c b), φ from εt (ACI 21.2.2); the
net tensile strain must be at least 0.004 (ACI 7.3.3.1, 8.3.3.1), φ dropping below 0.90 between
0.004 and εty + 0.003. Compression bars are ignored.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np

from saengine.design.rc import (
    EPS_CU,
    PHI_SHEAR,
    STEEL_E,
    bar_area,
    beta1,
    phi_axial_flexure,
)
from saengine.library.objects import BarMesh, PlanarReinforcement

METHOD = [
    (
        "Slabs (analysed as shells): moments per unit width at every integration point of "
        "every shell, turned into the slab's reinforcement axes (local x: global X for floor-"
        "plan slabs, the first outline edge for drawn areas), designed by Wood-Armer: bottom "
        "Mx* = mx + |mxy|, My* = my + |mxy|, top Mx* = mx - |mxy|, My* = my - |mxy|, with "
        "Armer's corrections when one of a pair has the wrong sign. Membrane forces are not "
        "included. Points inside a column are left out (the moment is designed at its faces); "
        "moments are not averaged over column or middle strips, so the peaks next to columns "
        "are designed as they are (conservative)."
    ),
    (
        "Slab layers per metre: φMn = φ As fy (d - a/2), X layers outer (d = h - c - db/2), "
        "Y layers inner (d = h - c - db,X - db/2); net tensile strain εt >= 0.004, i.e. "
        "c/d <= 0.003/0.007 (ACI 7.3.3.1, 8.3.3.1; φ by Table 21.2.2 below εty + 0.003); "
        "As,min of ACI 24.4.3.2 (0.0018 Ag for fy 420) in each layer near a tension face in a "
        "span direction (7.6.1.1, 8.6.1.1; one-way: the span direction only, taken as the "
        "direction of the larger design moment) and as a total of top + bottom in each "
        "direction (24.4.3.2); spacing at most min(3h, 450 mm) one-way in the span direction "
        "(7.7.2.3) and min(5h, 450 mm) across it (7.7.6.2.1, 24.4.3.3), min(2h, 450 mm) "
        "two-way (8.7.2.2)."
    ),
    (
        "Slab one-way shear per metre: φVc = 0.75 · 0.66 λs λ ρ^(1/3) √f'c b d (ACI Table "
        "22.5.5.1 (c), no shear reinforcement, λ = 1), ρ and d of the layer in tension at the "
        "point, against the transverse shear Qx, Qy of the shells, except within 2d of a "
        "column's faces (two-way shear governs there)."
    ),
    (
        "Flat slabs: punching at each column under the slab (ACI 22.6): critical section at "
        "d/2 from the column faces, cut by the slab edges (interior, edge, corner: αs = 40, 30, "
        "20), d the mean of the top layers, vc the least of the three ACI 22.6.5.2 expressions "
        "with λs (22.5.5.1.3); Vu = the change of the column's factored axial force at the slab "
        "(the load inside the critical section is not deducted), plus the unbalanced moment "
        "transfer γv Msc c / Jc (ACI 8.4.4.2) about both axes added at the farthest points of "
        "the section (conservative); Msc from the column end moments above and below, taken "
        "about the column's axis (not moved to the section's centroid at edges and corners); "
        "γv by 8.4.2.2.2, without the larger γf that 8.4.2.2.4 permits."
    ),
    (
        "Slab minimum thickness (ACI Table 7.3.1.1 one-way, 8.3.1.1 two-way without interior "
        "beams, 8.3.1.2 with beams, from αfm of the edge beams without flanges) is reported, "
        "not designed for; spans are centre-line spans less the supports' widths found."
    ),
]

#: Demands below this [N·m/m] need no bars (numerical noise near a free or pinned edge).
NO_DEMAND = 50.0
EPS_T_MIN = 0.004  # least net tensile strain of a nonprestressed slab (ACI 7.3.3.1, 8.3.3.1)
LAYERS = ("bottomX", "bottomY", "topX", "topY")
PHI_PUNCHING = PHI_SHEAR


# ─────────────────────────────────────── Wood-Armer ───────────────────────────────────────


def wood_armer(mx: float, my: float, mxy: float) -> tuple[float, float, float, float]:
    """Wood-Armer design moments (bottom x, bottom y, top x, top y), all >= 0, from the
    sagging-positive moments ``mx``, ``my`` and the twisting moment ``mxy`` (any consistent
    unit per width). Top moments are hogging magnitudes."""
    t = abs(mxy)
    # Bottom (sagging) reinforcement.
    bx, by = mx + t, my + t
    if bx < 0:
        bx, by = 0.0, (my + t * t / abs(mx)) if mx else my
    elif by < 0:
        by, bx = 0.0, (mx + t * t / abs(my)) if my else mx
    bx, by = max(bx, 0.0), max(by, 0.0)
    # Top (hogging) reinforcement.
    tx, ty = mx - t, my - t
    if tx > 0:
        tx, ty = 0.0, (my - t * t / abs(mx)) if mx else my
    elif ty > 0:
        ty, tx = 0.0, (mx - t * t / abs(my)) if my else mx
    tx, ty = max(-tx, 0.0), max(-ty, 0.0)
    return bx, by, tx, ty


# ─────────────────────────────────────── shells ───────────────────────────────────────


def shell_axes(points: Sequence[np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Local axes (e1, e2, e3) of an OpenSees ASDShellQ4 (four points) or ASDShellT3 (three).

    Q4: e3 along the cross product of the diagonals 1-3 and 2-4, e1 from the middle of side 4-1
    to the middle of side 2-3, projected on the plane. T3: e3 the normal of 1-2-3, e1 along
    side 1-2. e2 = e3 x e1. (Checked against the solver in the tests.)
    """
    p = [np.asarray(q, dtype=float) for q in points]
    if len(p) == 4:
        e3 = np.cross(p[2] - p[0], p[3] - p[1])
        e1 = (p[1] + p[2]) / 2 - (p[0] + p[3]) / 2
    else:
        e3 = np.cross(p[1] - p[0], p[2] - p[0])
        e1 = p[1] - p[0]
    e3 = e3 / np.linalg.norm(e3)
    e1 = e1 - (e1 @ e3) * e3
    e1 = e1 / np.linalg.norm(e1)
    return e1, np.cross(e3, e1), e3


def integration_points(points: Sequence[np.ndarray], count: int) -> list[np.ndarray]:
    """Positions of a shell's integration points, in the order the solver reports them: 2 x 2
    Gauss points of a Q4 ((-,-), (+,-), (+,+), (-,+)), the 3-point rule of a T3; other counts
    are taken at the centre."""
    p = [np.asarray(q, dtype=float) for q in points]
    if len(p) == 4 and count == 4:
        g = 1 / math.sqrt(3)
        out = []
        for xi, eta in ((-g, -g), (g, -g), (g, g), (-g, g)):
            n = [
                (1 - xi) * (1 - eta) / 4,
                (1 + xi) * (1 - eta) / 4,
                (1 + xi) * (1 + eta) / 4,
                (1 - xi) * (1 + eta) / 4,
            ]
            out.append(sum(w * q for w, q in zip(n, p, strict=True)))
        return out
    if len(p) == 3 and count == 3:
        weights = ((2 / 3, 1 / 6, 1 / 6), (1 / 6, 2 / 3, 1 / 6), (1 / 6, 1 / 6, 2 / 3))
        return [sum(w * q for w, q in zip(ws, p, strict=True)) for ws in weights]
    centre = sum(p) / len(p)
    return [centre] * count


@dataclass(frozen=True)
class SlabAxes:
    """A slab's reinforcement axes (global unit vectors): local x, local y and up."""

    x: np.ndarray
    y: np.ndarray
    up: np.ndarray


def plan_axes() -> SlabAxes:
    return SlabAxes(np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0]))


def outline_axes(outline: Sequence[Sequence[float]]) -> SlabAxes | None:
    """Axes of a drawn area: local x along its first edge, up its normal turned upwards. None
    for a wall-like (near vertical) area."""
    points = [np.asarray(q, dtype=float) for q in outline]
    normal = np.zeros(3)
    for a, b in zip(points, points[1:] + points[:1], strict=True):
        normal += np.cross(a, b)  # Newell's method, robust for any simple polygon
    if np.linalg.norm(normal) < 1e-9:
        return None
    up = normal / np.linalg.norm(normal)
    if up[2] < 0:
        up = -up
    if up[2] < 0.5:
        return None
    x = points[1] - points[0]
    x = x - (x @ up) * up
    x = x / np.linalg.norm(x)
    return SlabAxes(x, np.cross(up, x), up)


def slab_forces(
    rows: np.ndarray, axes: tuple[np.ndarray, np.ndarray, np.ndarray], slab: SlabAxes
) -> np.ndarray:
    """Per integration point (rows of N11 N22 N12 M11 M22 M12 Q13 Q23 in the shell's axes):
    ``mx, my, mxy, qx, qy`` in the slab's axes, moments sagging-positive (bottom in tension)."""
    e1, e2, e3 = axes
    face = 1.0 if float(e3 @ slab.up) >= 0 else -1.0
    r = np.array([[slab.x @ e1, slab.x @ e2], [slab.y @ e1, slab.y @ e2]])
    out = np.zeros((len(rows), 5))
    for k, row in enumerate(rows):
        m = np.array([[row[3], row[5]], [row[5], row[4]]])
        turned = r @ m @ r.T
        q = r @ np.array([row[6], row[7]])
        # Positive shell moments stretch the +e3 face: the top when e3 points up.
        out[k] = [-face * turned[0, 0], -face * turned[1, 1], -face * turned[0, 1], q[0], q[1]]
    return out


# ─────────────────────────────────────── capacities ───────────────────────────────────────


@dataclass(frozen=True)
class Layer:
    """One layer of bars per metre width."""

    name: str
    dia: float
    spacing: float
    d: float  # mm

    @property
    def area(self) -> float:
        """As per metre width [mm²/m]."""
        return bar_area(self.dia) * 1000 / self.spacing


def layers_of(reinforcement: PlanarReinforcement, h: float) -> dict[str, Layer | None]:
    """The four layers with their effective depths (X layers outer, see the module notes)."""
    c = reinforcement.cover
    result: dict[str, Layer | None] = {}
    for face in ("bottom", "top"):
        outer: BarMesh | None = getattr(reinforcement, f"{face}X")
        inner: BarMesh | None = getattr(reinforcement, f"{face}Y")
        if outer is not None:
            result[f"{face}X"] = Layer(f"{face}X", outer.dia, outer.spacing, h - c - outer.dia / 2)
        else:
            result[f"{face}X"] = None
        if inner is not None:
            below = outer.dia if outer is not None else 0.0
            result[f"{face}Y"] = Layer(
                f"{face}Y", inner.dia, inner.spacing, h - c - below - inner.dia / 2
            )
        else:
            result[f"{face}Y"] = None
    return result


@dataclass(frozen=True)
class LayerCapacity:
    """Flexural strength per metre width of a singly reinforced slab strip."""

    area: float  # mm²/m
    d: float  # mm
    a: float  # mm
    c: float  # mm
    eps_t: float
    phi: float
    mn: float  # N·mm/m
    phi_mn: float  # N·mm/m
    c_d_limit: float  # c/d at the least εt allowed in a slab (0.004, ACI 7.3.3.1, 8.3.3.1)

    @property
    def c_d(self) -> float:
        return self.c / self.d


def layer_capacity(
    area: float, d: float, fc: float, fy: float, es: float = STEEL_E, width: float = 1000.0
) -> LayerCapacity:
    """φMn of a strip ``width`` wide with ``area`` of bars at depth ``d`` (ACI 22.2, the
    rectangular stress block; φ by ACI 21.2.2)."""
    if d <= 0:
        raise ValueError("the cover leaves no room for the bars")
    a = area * fy / (0.85 * fc * width)
    c = a / beta1(fc)
    eps_t = EPS_CU * (d - c) / c if c > 0 else math.inf
    phi = phi_axial_flexure(eps_t, fy, es)
    mn = area * fy * (d - a / 2)
    limit = EPS_CU / (EPS_CU + EPS_T_MIN)
    return LayerCapacity(area, d, a, c, eps_t, phi, mn, phi * mn, limit)


def one_way_shear(rho: float, d: float, fc: float, lam: float = 1.0) -> tuple[float, float]:
    """φVc per metre [N/m] of a slab without shear reinforcement (ACI Table 22.5.5.1 (c)) and
    its size effect factor λs: Vc = 0.66 λs λ ρ^(1/3) √f'c b d <= 0.42 λ √f'c b d,
    √f'c <= 8.3 MPa, λs = √(2 / (1 + 0.004 d)) <= 1, b = 1000 mm."""
    root = min(math.sqrt(fc), 8.3)
    lambda_s = min(1.0, math.sqrt(2 / (1 + 0.004 * d)))
    vc = 0.66 * lambda_s * lam * max(rho, 0.0) ** (1 / 3) * root * 1000 * d
    vc = min(vc, 0.42 * lam * root * 1000 * d)
    return PHI_SHEAR * vc, lambda_s


def min_steel_ratio(fy: float) -> float:
    """As,min / Ag of a slab (ACI 7.6.1.1, 8.6.1.1 by Table 24.4.3.2): 0.0020 below fy 420,
    else the greater of 0.0018 x 420 / fy and 0.0014."""
    if fy < 420:
        return 0.0020
    return max(0.0018 * 420 / fy, 0.0014)


# ─────────────────────────────────────── punching ───────────────────────────────────────


@dataclass
class CriticalSection:
    """A punching critical section in the column's axes (u, v), mm: its sides as
    (u0, v0, u1, v1) segments, ``d``, and where the slab edges cut it."""

    sides: list[tuple[float, float, float, float]]
    d: float
    extents: tuple[float, float, float, float]  # -u, +u, -v, +v from the column centre
    location: str  # interior, edge, corner

    @property
    def b0(self) -> float:
        return sum(math.hypot(s[2] - s[0], s[3] - s[1]) for s in self.sides)

    @property
    def alpha_s(self) -> float:
        return {"interior": 40.0, "edge": 30.0}.get(self.location, 20.0)

    def centroid(self) -> tuple[float, float]:
        total = self.b0
        u = sum(math.hypot(s[2] - s[0], s[3] - s[1]) * (s[0] + s[2]) / 2 for s in self.sides)
        v = sum(math.hypot(s[2] - s[0], s[3] - s[1]) * (s[1] + s[3]) / 2 for s in self.sides)
        return u / total, v / total

    def polar(self, along_u: bool) -> tuple[float, float]:
        """Jc [mm⁴] (ACI R8.4.4.2.3, the analogue of the polar moment of inertia) for the
        eccentric shear of a moment bending in the u direction (``along_u``) or the v
        direction, and c: the largest distance of the section from its centroid that way."""
        uc, vc = self.centroid()
        d = self.d
        jc, reach = 0.0, 0.0
        for u0, v0, u1, v1 in self.sides:
            a0, a1, mid = (u0, u1, uc) if along_u else (v0, v1, vc)
            length = math.hypot(u1 - u0, v1 - v0)
            centre = (a0 + a1) / 2 - mid
            if abs(a1 - a0) > 1e-9:  # a side along the bending direction
                jc += d * length**3 / 12 + length * d**3 / 12 + length * d * centre**2
            else:
                jc += length * d * centre**2
            reach = max(reach, abs(a0 - mid), abs(a1 - mid))
        return jc, reach

    def widths(self) -> tuple[float, float]:
        """Width of the section along u and along v."""
        lo_u, hi_u, lo_v, hi_v = self.extents
        return lo_u + hi_u, lo_v + hi_v


def critical_section(
    centre: Sequence[float],
    c1: float,
    c2: float,
    angle: float,
    d: float,
    boundary: Sequence[Sequence[float]],
) -> CriticalSection:
    """The critical section at d/2 from the faces of a ``c1`` x ``c2`` column (``c1`` along
    the column's u axis, at ``angle`` degrees from global X) at ``centre`` (mm, plan), cut by
    the slab ``boundary`` (plan polygon, mm): a side whose line lies outside the slab is left
    out and the sides next to it run to the slab edge (ACI 22.6.4.1)."""
    cx, cy = float(centre[0]), float(centre[1])
    t = math.radians(angle)
    u = np.array([math.cos(t), math.sin(t)])
    v = np.array([-math.sin(t), math.cos(t)])
    full = ((c1 + d) / 2, (c1 + d) / 2, (c2 + d) / 2, (c2 + d) / 2)
    directions = (-u, u, -v, v)
    extents = []
    closed = []
    origin = np.array([cx, cy])
    for reach, direction in zip(full, directions, strict=True):
        if _inside(origin + direction * reach, boundary):
            extents.append(reach)
            closed.append(True)
            continue
        edge = _ray_to_boundary(origin, direction, boundary)
        extents.append(min(edge, reach) if edge is not None else 0.0)
        closed.append(False)
    lo_u, hi_u, lo_v, hi_v = extents
    sides = []
    if closed[0]:
        sides.append((-lo_u, -lo_v, -lo_u, hi_v))
    if closed[1]:
        sides.append((hi_u, -lo_v, hi_u, hi_v))
    if closed[2]:
        sides.append((-lo_u, -lo_v, hi_u, -lo_v))
    if closed[3]:
        sides.append((-lo_u, hi_v, hi_u, hi_v))
    count = sum(closed)
    location = "interior" if count == 4 else "edge" if count == 3 else "corner"
    return CriticalSection(sides, d, (lo_u, hi_u, lo_v, hi_v), location)


def _ray_to_boundary(
    origin: np.ndarray, direction: np.ndarray, boundary: Sequence[Sequence[float]]
) -> float | None:
    """Distance from ``origin`` along ``direction`` to the nearest crossing of the polygon."""
    best = None
    points = [np.asarray(p[:2], dtype=float) for p in boundary]
    for a, b in zip(points, points[1:] + points[:1], strict=True):
        edge = b - a
        matrix = np.column_stack([direction, -edge])
        if abs(np.linalg.det(matrix)) < 1e-12:
            continue
        t, s = np.linalg.solve(matrix, a - origin)
        if t >= -1e-6 and -1e-9 <= s <= 1 + 1e-9 and (best is None or t < best):
            best = max(float(t), 0.0)
    return best


@dataclass(frozen=True)
class PunchingCapacity:
    vc: float  # MPa
    expressions: tuple[float, float, float]  # ACI 22.6.5.2 (a), (b), (c) [MPa]
    lambda_s: float


def punching_capacity(
    fc: float, d: float, b0: float, beta: float, alpha_s: float, lam: float = 1.0
) -> PunchingCapacity:
    """vc of two-way shear without shear reinforcement (ACI 22.6.5.2, SI): the least of
    0.33 λs λ √f'c, 0.17 (1 + 2/β) λs λ √f'c and 0.083 (2 + αs d / b0) λs λ √f'c, with
    λs = √(2 / (1 + 0.004 d)) <= 1 (22.5.5.1.3) and √f'c <= 8.3 MPa (22.6.3.1)."""
    root = min(math.sqrt(fc), 8.3)
    lambda_s = min(1.0, math.sqrt(2 / (1 + 0.004 * d)))
    k = lambda_s * lam * root
    values = (0.33 * k, 0.17 * (1 + 2 / beta) * k, 0.083 * (2 + alpha_s * d / b0) * k)
    return PunchingCapacity(min(values), values, lambda_s)


@dataclass(frozen=True)
class PunchingStress:
    vu: float  # MPa, the largest factored shear stress on the section
    direct: float  # MPa, Vu / (b0 d)
    gamma_v: tuple[float, float]  # for moments bending along u and along v


def punching_stress(section: CriticalSection, vu: float, m_u: float, m_v: float) -> PunchingStress:
    """Largest shear stress [MPa] on the critical section under ``vu`` [N] and the unbalanced
    moments [N·mm] bending the slab along the column's u axis (``m_u``: moment vector along
    v) and along v (``m_v``), by ACI 8.4.4.2: v = Vu / (b0 d) + γv M c / Jc for each, with
    γv = 1 - 1 / (1 + (2/3) √(b1 / b2)) (8.4.2.2.2); both moment terms are added at their
    farthest points (conservative)."""
    b0, d = section.b0, section.d
    width_u, width_v = section.widths()
    gamma_u = 1 - 1 / (1 + 2 / 3 * math.sqrt(width_u / width_v))
    gamma_v = 1 - 1 / (1 + 2 / 3 * math.sqrt(width_v / width_u))
    direct = vu / (b0 * d)
    stress = direct
    for gamma, moment, along_u in ((gamma_u, m_u, True), (gamma_v, m_v, False)):
        jc, reach = section.polar(along_u)
        if jc > 0:
            stress += gamma * abs(moment) * reach / jc
    return PunchingStress(stress, direct, (gamma_u, gamma_v))


# ─────────────────────────────────────── thickness ───────────────────────────────────────

#: ACI Table 8.3.1.1 (without drop panels): fy -> (exterior without edge beams, exterior with
#: edge beams, interior) divisors of ln.
_TABLE_8_3_1_1 = {280.0: (33.0, 36.0, 36.0), 420.0: (30.0, 33.0, 33.0), 520.0: (28.0, 31.0, 31.0)}


def two_way_divisor(fy: float, exterior: bool, edge_beams: bool) -> float:
    """The ln divisor of ACI Table 8.3.1.1, interpolated in fy (footnote)."""
    column = 2 if not exterior else (1 if edge_beams else 0)
    keys = sorted(_TABLE_8_3_1_1)
    fy = min(max(fy, keys[0]), keys[-1])
    for lo, hi in pairwise(keys):
        if lo <= fy <= hi:
            a, b = _TABLE_8_3_1_1[lo][column], _TABLE_8_3_1_1[hi][column]
            return a + (b - a) * (fy - lo) / (hi - lo)
    return _TABLE_8_3_1_1[keys[-1]][column]


@dataclass(frozen=True)
class Thickness:
    required: float  # mm
    table: str
    note: str


def one_way_thickness(span: float, continuous_ends: int, fy: float) -> Thickness:
    """ACI Table 7.3.1.1: l/20 simply supported, l/24 one end continuous, l/28 both ends
    continuous, times (0.4 + fy / 700) for fy other than 420 MPa."""
    divisor = {0: 20.0, 1: 24.0}.get(continuous_ends, 28.0)
    factor = 0.4 + fy / 700
    ends = {0: "simply supported", 1: "one end continuous"}.get(continuous_ends, "both continuous")
    note = f"l = {span:.0f} mm, {ends}: l/{divisor:g}"
    if abs(factor - 1) > 1e-9:
        note += f" x (0.4 + fy/700) = {factor:.2f}"
    return Thickness(span / divisor * factor, "7.3.1.1", note)


def two_way_thickness(
    ln: float, beta: float, alpha_fm: float, fy: float, exterior: bool, edge_beams: bool
) -> Thickness:
    """ACI 8.3.1.1 (αfm <= 0.2: Table 8.3.1.1, at least 125 mm) or 8.3.1.2 (with beams:
    ln (0.8 + fy/1400) / (36 + 5β(αfm - 0.2)) >= 125 mm for αfm <= 2, / (36 + 9β) >= 90 mm
    above)."""
    if alpha_fm <= 0.2:
        divisor = two_way_divisor(fy, exterior, edge_beams)
        panel = (
            "interior" if not exterior else "exterior" + (" with edge beams" if edge_beams else "")
        )
        return Thickness(
            max(ln / divisor, 125.0),
            "8.3.1.1",
            f"ln = {ln:.0f} mm, {panel} panel: ln/{divisor:.1f}, at least 125 mm",
        )
    factor = 0.8 + fy / 1400
    if alpha_fm <= 2.0:
        required = max(ln * factor / (36 + 5 * beta * (alpha_fm - 0.2)), 125.0)
    else:
        required = max(ln * factor / (36 + 9 * beta), 90.0)
    return Thickness(required, "8.3.1.2", f"ln = {ln:.0f} mm, β = {beta:.2f}, αfm = {alpha_fm:.2f}")


@dataclass(frozen=True)
class EdgeBeam:
    """A beam in the plan (mm) with its flexural stiffness E I [N·mm²] and width [mm]."""

    start: tuple[float, float]
    end: tuple[float, float]
    ei: float
    width: float


def minimum_thickness(
    boundary: Sequence[Sequence[float]],
    axes: SlabAxes,
    system: str,
    h: float,
    fy: float,
    ec: float,
    neighbours: Sequence[Sequence[Sequence[float]]],
    beams: Sequence[EdgeBeam],
    column_size: float = 0.0,
    columns: Sequence[Sequence[float]] = (),
) -> Thickness:
    """The minimum thickness of a slab panel by ACI Table 7.3.1.1 (one-way) or 8.3.1.1 / 8.3.1.2
    (two-way, flat). ``boundary``: its plan outline (mm); ``neighbours``: the outlines of the
    other slabs at its level (for continuity and interior panels); ``beams``: the beams at its
    level; ``ec``: the slab concrete's E (MPa).

    Spans are measured in the slab's axes over its outline's extent (centre lines), less the
    width of the beams along its edges (or, without beams, ``column_size``): the clear span ln.
    αf of an edge is Eb Ib / (Es Is) with the beam's own section (no flange: lower, so on the
    safe side) and Is over half the panel width each side of the edge (ACI 8.4.1.8 strip);
    αfm is their mean over the panel's edges (0 where an edge has no beam). A slab with
    ``columns`` inside (plan points, mm; a flat slab of several panels) takes its spans from
    the largest distance between neighbouring columns in line along its x and y instead, and
    counts as an exterior panel when any of its sides is free.
    """
    points = [np.asarray(p[:2], dtype=float) for p in boundary]
    ux, uy = axes.x[:2], axes.y[:2]
    ux = ux / (np.linalg.norm(ux) or 1.0)
    uy = uy / (np.linalg.norm(uy) or 1.0)
    xs = [float(p @ ux) for p in points]
    ys = [float(p @ uy) for p in points]
    lx, ly = max(xs) - min(xs), max(ys) - min(ys)
    centre = ux * (max(xs) + min(xs)) / 2 + uy * (max(ys) + min(ys)) / 2

    def neighbour_at(point: np.ndarray) -> bool:
        return any(_inside(point, other) for other in neighbours)

    sides = {
        "x-": neighbour_at(centre - ux * (lx / 2 + 100)),
        "x+": neighbour_at(centre + ux * (lx / 2 + 100)),
        "y-": neighbour_at(centre - uy * (ly / 2 + 100)),
        "y+": neighbour_at(centre + uy * (ly / 2 + 100)),
    }

    alphas: list[float] = []
    widths: list[float] = []
    exterior_beams: list[bool] = []
    for a, b in zip(points, points[1:] + points[:1], strict=True):
        edge = b - a
        length = float(np.linalg.norm(edge))
        if length < 1:
            continue
        t = edge / length
        n = np.array([t[1], -t[0]])
        across = [float(p @ n) for p in points]
        span = max(across) - min(across)
        mid = (a + b) / 2
        inside_normal = n if _inside(mid + n * 1.0, boundary) else -n
        continued = neighbour_at(mid - inside_normal * 100)
        width = span / 2 * (2 if continued else 1)
        found = [
            beam
            for beam in beams
            if _along(np.asarray(beam.start, float), np.asarray(beam.end, float), a, b)
        ]
        alpha = 0.0
        if found:
            beam = max(found, key=lambda beam: beam.ei)
            alpha = beam.ei / (ec * width * h**3 / 12)
            widths.append(beam.width)
        alphas.append(alpha)
        if not continued:
            exterior_beams.append(alpha >= 0.8)
    alpha_fm = sum(alphas) / len(alphas) if alphas else 0.0
    support = sum(widths) / len(widths) if widths else column_size
    if len(columns) >= 2:
        plan = [(float(np.asarray(p[:2]) @ ux), float(np.asarray(p[:2]) @ uy)) for p in columns]
        lx = _grid_span(plan, 0) or lx
        ly = _grid_span(plan, 1) or ly

    if system == "oneWay":
        along_x = lx <= ly  # spans the short way
        span = lx if along_x else ly
        ends = (sides["x-"], sides["x+"]) if along_x else (sides["y-"], sides["y+"])
        result = one_way_thickness(span, sum(ends), fy)
        return Thickness(
            result.required, result.table, result.note + f", along {'x' if along_x else 'y'}"
        )
    long_x = lx >= ly
    ln_long = max(lx, ly) - support
    ln_short = max(min(lx, ly) - support, 1.0)
    exterior = not all(sides.values())
    edge_beams = bool(exterior_beams) and all(exterior_beams)
    result = two_way_thickness(ln_long, ln_long / ln_short, alpha_fm, fy, exterior, edge_beams)
    return Thickness(
        result.required, result.table, result.note + f", along {'x' if long_x else 'y'}"
    )


def _grid_span(points: list[tuple[float, float]], axis: int) -> float:
    """The largest distance from a column to its nearest neighbour in line with it along
    ``axis`` (0: x, 1: y; in line: within 300 mm across), 0 when no two are in line."""
    other = 1 - axis
    largest = 0.0
    for p in points:
        gaps = [
            abs(q[axis] - p[axis])
            for q in points
            if q is not p and abs(q[other] - p[other]) <= 300 and abs(q[axis] - p[axis]) > 300
        ]
        if gaps:
            largest = max(largest, min(gaps))
    return largest


def _inside(point: np.ndarray, polygon: Sequence[Sequence[float]]) -> bool:
    """Whether a plan point lies inside (or within 1 mm of the edge of) a plan polygon."""
    x, y = float(point[0]), float(point[1])
    flat = [(float(p[0]), float(p[1])) for p in polygon]
    inside = False
    for (x0, y0), (x1, y1) in zip(flat, flat[1:] + flat[:1], strict=True):
        dx, dy = x1 - x0, y1 - y0
        length2 = dx * dx + dy * dy
        if length2:
            s = min(max(((x - x0) * dx + (y - y0) * dy) / length2, 0.0), 1.0)
            if math.hypot(x0 + s * dx - x, y0 + s * dy - y) <= 1.0:
                return True
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
    return inside


def _along(p: np.ndarray, q: np.ndarray, a: np.ndarray, b: np.ndarray) -> bool:
    """Whether the plan segment p-q lies on the line of a-b (within 5 mm) and overlaps it by
    more than half of the shorter of the two."""
    edge = b - a
    length = float(np.linalg.norm(edge))
    t = edge / length
    n = np.array([-t[1], t[0]])
    if abs(float((p - a) @ n)) > 5 or abs(float((q - a) @ n)) > 5:
        return False
    s0, s1 = sorted((float((p - a) @ t), float((q - a) @ t)))
    overlap = min(s1, length) - max(s0, 0.0)
    return overlap > 0.5 * min(s1 - s0, length)


# ─────────────────────────────────────── the checks ───────────────────────────────────────


@dataclass
class ShellPoint:
    """The forces of one shell of a slab at its integration points, per combination."""

    id: int
    name: str
    points: list[np.ndarray]  # positions [m]
    forces: list[np.ndarray]  # per combination: (points, 5) mx my mxy qx qy [N·m/m, N/m]


@dataclass
class ColumnJoint:
    """A column meeting the slab: its plan geometry and, per combination, the force [N] and
    moment [N·mm] the slab puts on the column (global axes)."""

    id: str
    centre: tuple[float, float]  # mm
    c1: float  # mm, along the column's u axis
    c2: float
    angle: float  # degrees, u from global X
    forces: list[np.ndarray] = field(default_factory=list)
    moments: list[np.ndarray] = field(default_factory=list)


@dataclass
class SlabContext:
    """What the checks need to know about a slab beyond its forces."""

    thickness: Thickness | None = None
    boundary: list[tuple[float, float]] = field(default_factory=list)  # plan, mm
    columns: list[ColumnJoint] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def slab_checks(
    system: str,
    h: float,
    reinforcement: PlanarReinforcement,
    fc: float,
    fy: float,
    es: float,
    shells: list[ShellPoint],
    combinations: list[str],
    context: SlabContext,
) -> list[dict[str, Any]]:
    """The checks of one slab (see :data:`METHOD`), in the shape of
    :func:`saengine.design.check._check`."""
    from saengine.design.check import _check

    layers = layers_of(reinforcement, h)
    capacities = {
        name: (layer_capacity(layer.area, layer.d, fc, fy, es) if layer is not None else None)
        for name, layer in layers.items()
    }
    # Envelopes: (value, combination, where).
    envelope: dict[str, tuple[float, str | None, str]] = {n: (0.0, None, "") for n in LAYERS}
    shear_env: dict[str, tuple[float, float, float, str | None, str]] = {}

    def shear_capacity(direction: str, sagging: bool) -> tuple[float, str] | None:
        order = ("bottom", "top") if sagging else ("top", "bottom")
        for face in order:
            capacity = capacities[f"{face}{direction}"]
            if capacity is not None:
                rho = capacity.area / (1000 * capacity.d)
                return one_way_shear(rho, capacity.d, fc)[0], f"{face}{direction}"
        return None

    # Points inside a column are not designed for flexure (the design moment is at the face),
    # nor within 2d of its faces for one-way shear (two-way shear governs there, ACI 22.6).
    depth = max((layer.d for layer in layers.values() if layer is not None), default=0.0)
    skipped_points = 0
    for shell in shells:
        inside = [_near_column(p, context.columns, 0.0) for p in shell.points]
        near = [_near_column(p, context.columns, 2 * depth) for p in shell.points]
        skipped_points += sum(inside)
        for c, values in enumerate(shell.forces):
            for k, (mx, my, mxy, qx, qy) in enumerate(values):
                where = _where(shell, k)
                if not inside[k]:
                    design = wood_armer(mx, my, mxy)
                    for name, value in zip(LAYERS, design, strict=True):
                        if value > envelope[name][0]:
                            envelope[name] = (value, combinations[c], where)
                if near[k]:
                    continue
                for direction, q, m in (("X", qx, mx), ("Y", qy, my)):
                    resisting = shear_capacity(direction, m >= 0)
                    if resisting is None:
                        continue
                    capacity, layer = resisting
                    ratio = abs(q) / capacity if capacity > 0 else math.inf
                    best = shear_env.get("all")
                    if best is None or ratio > best[0]:
                        shear_env["all"] = (
                            ratio,
                            abs(q),
                            capacity,
                            combinations[c],
                            f"Q{direction.lower()}, ρ of {layer}; {where}",
                        )

    if skipped_points:
        context.notes.append(
            f"{skipped_points} shell integration points inside columns are not designed for "
            "flexure (the design moment is taken at the column faces)"
        )
    checks: list[dict[str, Any]] = []
    for name in LAYERS:
        face, direction = name[:-1], name[-1]
        demand, combination, where = envelope[name]
        capacity = capacities[name]
        label = f"Flexure {face} {direction} (Wood-Armer)"
        if capacity is None:
            if demand <= NO_DEMAND:
                continue
            what = "sagging" if face == "bottom" else "hogging"
            checks.append(
                _check(
                    label,
                    demand / 1e3,
                    0.0,
                    "kN·m/m",
                    combination,
                    f"no {face} {direction} bars, but the slab is {what} "
                    f"{demand / 1e3:.2f} kN·m/m here: {face} bars are needed; {where}",
                )
            )
            continue
        layer = layers[name]
        assert layer is not None
        note = (
            f"{_bars(layer)}: As = {capacity.area:.0f} mm²/m, d = {capacity.d:.0f} mm, "
            f"φ = {capacity.phi:.2f}"
        )
        if where:
            note += f"; {where}"
        checks.append(
            _check(label, demand / 1e3, capacity.phi_mn / 1e6, "kN·m/m", combination, note)
        )

    present = {n: c for n, c in capacities.items() if c is not None}
    if present:
        name, worst = max(present.items(), key=lambda item: item[1].c_d)
        checks.append(
            _check(
                "Net tensile strain c/d (ACI 7.3.3.1, 8.3.3.1)",
                worst.c_d,
                worst.c_d_limit,
                "",
                None,
                f"{name}: c = {worst.c:.1f} mm, d = {worst.d:.0f} mm, εt = {worst.eps_t:.4f}",
                utilisation=worst.c_d / worst.c_d_limit,
            )
        )

    if "all" in shear_env:
        ratio, demand, capacity, combination, where = shear_env["all"]
        checks.append(
            _check(
                "One-way shear",
                demand / 1e3,
                capacity / 1e3,
                "kN/m",
                combination,
                f"φVc = 0.75 · 0.66 λs ρ^(1/3) √f'c b d (ACI 22.5.5.1 (c)); {where}",
                utilisation=ratio,
            )
        )

    if present:
        span = span_direction(system, {n: envelope[n][0] for n in LAYERS})
        checks.append(_min_reinforcement_check(system, h, fy, capacities, envelope, span))
        checks.append(_max_spacing_check(system, h, layers, span))

    if context.thickness is not None:
        t = context.thickness
        checks.append(
            _check(f"Min. thickness (Table {t.table})", t.required, h, "mm", None, t.note, True)
        )

    if system == "flat":
        checks += _punching_checks(layers, fc, combinations, context)
    return checks


def span_direction(system: str, demands: dict[str, float]) -> str | None:
    """The span direction ("X" or "Y") of a one-way slab: the direction of the larger
    Wood-Armer design moment (bottom or top), X when there is no demand at all. None for a
    two-way or flat slab, which spans both ways."""
    if system != "oneWay":
        return None
    x = max(demands.get("bottomX", 0.0), demands.get("topX", 0.0))
    y = max(demands.get("bottomY", 0.0), demands.get("topY", 0.0))
    return "Y" if y > x else "X"


def _min_reinforcement_check(
    system: str,
    h: float,
    fy: float,
    capacities: dict[str, LayerCapacity | None],
    envelope: dict[str, tuple[float, str | None, str]],
    span: str | None,
) -> dict[str, Any]:
    """As,min of a slab, the governing one of:

    - ACI 7.6.1.1 / 8.6.1.1: As,min (Table 24.4.3.2) near the tension face in the direction
      of the span under consideration, i.e. in each layer whose face the Wood-Armer envelope
      puts in tension (one-way slabs: in the span direction only), and bottom bars in the
      span direction(s) (both ways for two-way and flat slabs);
    - ACI 24.4.3.2 (shrinkage and temperature; 7.6.4.1 / 8.6.1.1): the same ratio as a total
      for the section in each direction, which may be split between the two faces.

    Layers with no tension demand (e.g. light top or distribution bars) only count towards the
    total of their direction."""
    from saengine.design.check import _check

    ratio = min_steel_ratio(fy)
    as_min = ratio * 1000 * h
    # (utilisation, required, provided, what)
    found: list[tuple[float, float, float, str]] = []

    def need(required: float, provided: float, what: str) -> None:
        utilisation = required / provided if provided > 0 else math.inf
        found.append((utilisation, required, provided, what))

    for direction in ("X", "Y"):
        total = sum(
            c.area for n in (f"bottom{direction}", f"top{direction}") if (c := capacities[n])
        )
        need(as_min, total, f"total {direction} (top + bottom), ACI 24.4.3.2")
    spans = ("X", "Y") if span is None else (span,)
    for direction in spans:
        if capacities[f"bottom{direction}"] is None:
            need(as_min, 0.0, f"no bottom {direction} bars in a span direction")
    for name in LAYERS:
        capacity = capacities[name]
        if capacity is None or name[-1] not in spans or envelope[name][0] <= NO_DEMAND:
            continue
        need(as_min, capacity.area, f"{name} (tension face), ACI 7.6.1.1 / 8.6.1.1")
    utilisation, required, provided, what = max(found, key=lambda item: item[0])
    note = f"As,min = {ratio:.4f} Ag = {as_min:.0f} mm²/m; governing: {what}"
    if span is not None:
        note += f"; one-way slab spanning {span}"
    return _check(
        "Min. reinforcement (ACI 7.6.1.1, 8.6.1.1)",
        required,
        provided,
        "mm²/m",
        None,
        note,
        utilisation=utilisation,
    )


def _max_spacing_check(
    system: str, h: float, layers: dict[str, Layer | None], span: str | None
) -> dict[str, Any]:
    """Maximum bar spacing, the governing layer of: one-way slabs, flexural bars in the span
    direction min(3h, 450 mm) (ACI 7.7.2.3) and the bars across the span (shrinkage and
    temperature) min(5h, 450 mm) (ACI 7.7.6.2.1, 24.4.3.3); two-way and flat slabs
    min(2h, 450 mm) (ACI 8.7.2.2, critical sections; applied everywhere)."""
    from saengine.design.check import _check

    worst: tuple[float, Layer, float, str] | None = None
    for layer in layers.values():
        if layer is None:
            continue
        if system != "oneWay":
            limit, clause = min(2 * h, 450.0), "8.7.2.2: min(2h, 450 mm)"
        elif layer.name[-1] == span:
            limit, clause = min(3 * h, 450.0), "7.7.2.3: min(3h, 450 mm)"
        else:
            limit, clause = min(5 * h, 450.0), "7.7.6.2.1, 24.4.3.3: min(5h, 450 mm)"
        ratio = layer.spacing / limit
        if worst is None or ratio > worst[0]:
            worst = (ratio, layer, limit, clause)
    assert worst is not None
    _, layer, limit, clause = worst
    return _check(
        "Max. spacing",
        layer.spacing,
        limit,
        "mm",
        None,
        f"{layer.name} at {layer.spacing:.0f} mm; ACI {clause}",
    )


def _near_column(point: np.ndarray, columns: list[ColumnJoint], margin: float) -> bool:
    """Whether a point (m) lies within ``margin`` (mm) of a column's plan section."""
    x, y = float(point[0]) * 1e3, float(point[1]) * 1e3
    for column in columns:
        t = math.radians(column.angle)
        dx, dy = x - column.centre[0], y - column.centre[1]
        u = dx * math.cos(t) + dy * math.sin(t)
        v = -dx * math.sin(t) + dy * math.cos(t)
        if abs(u) <= column.c1 / 2 + margin and abs(v) <= column.c2 / 2 + margin:
            return True
    return False


def _bars(layer: Layer) -> str:
    return f"Ø{layer.dia:g} @ {layer.spacing:g}"


def _where(shell: ShellPoint, k: int) -> str:
    x, y, _ = shell.points[k]
    return f"{shell.name} point {k + 1} at ({x:.2f}, {y:.2f}) m"


def _punching_checks(
    layers: dict[str, Layer | None],
    fc: float,
    combinations: list[str],
    context: SlabContext,
) -> list[dict[str, Any]]:
    from saengine.design.check import _check

    top = [layer for layer in (layers["topX"], layers["topY"]) if layer is not None]
    source = "top"
    if not top:
        top = [layer for layer in (layers["bottomX"], layers["bottomY"]) if layer is not None]
        source = "bottom (no top bars)"
    if not top:
        return []
    d = sum(layer.d for layer in top) / len(top)
    checks = []
    for column in context.columns:
        section = critical_section(
            column.centre, column.c1, column.c2, column.angle, d, context.boundary
        )
        if not section.sides:
            continue
        beta = max(column.c1, column.c2) / min(column.c1, column.c2)
        capacity = punching_capacity(fc, d, section.b0, beta, section.alpha_s)
        t = math.radians(column.angle)
        u = np.array([math.cos(t), math.sin(t), 0.0])
        v = np.array([-math.sin(t), math.cos(t), 0.0])
        worst: tuple[float, PunchingStress, float, str | None] | None = None
        for c, (force, moment) in enumerate(zip(column.forces, column.moments, strict=True)):
            vu = max(-float(force[2]), 0.0)
            # A moment vector along v bends the slab in the u direction, and vice versa.
            stress = punching_stress(section, vu, float(moment @ v), float(moment @ u))
            if worst is None or stress.vu > worst[0]:
                worst = (stress.vu, stress, vu, combinations[c])
        if worst is None:
            continue
        vu_max, stress, vu, combination = worst
        area = section.b0 * d
        phi_vc = PHI_PUNCHING * capacity.vc
        a, b, cc = capacity.expressions
        note = (
            f"{section.location} column, b0 = {section.b0:.0f} mm, d = {d:.0f} mm ({source}), "
            f"Vu = {vu / 1e3:.1f} kN, vu = {vu_max:.3f} MPa (direct {stress.direct:.3f}, "
            f"γv = {stress.gamma_v[0]:.2f}/{stress.gamma_v[1]:.2f}), "
            f"vc = min({a:.3f}, {b:.3f}, {cc:.3f}) MPa, λs = {capacity.lambda_s:.2f}, "
            f"αs = {section.alpha_s:g}, β = {beta:.2f}; shown as v b0 d"
        )
        checks.append(
            _check(
                f"Punching at {column.id}",
                vu_max * area / 1e3,
                phi_vc * area / 1e3,
                "kN",
                combination,
                note,
                utilisation=vu_max / phi_vc,
            )
        )
    return checks
