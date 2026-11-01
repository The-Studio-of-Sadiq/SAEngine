"""Design checks of reinforced-concrete slabs from the shell forces of the analysis (ACI 318-19
strength design, which the default pack's BNBC 2020 Part 6 Chapter 6 adopts).

Slabs are designed when the analysis meshes them as shells (Analysis settings: slabs as
shells). Flexure and one-way shear are designed by design strips, as SAFE and ETABS do (ACI
318-19 8.4.1.1-8.4.1.2 permit any analysis satisfying equilibrium and compatibility; the strips
follow 8.4.1.5 and 8.4.1.6): the Wood-Armer moments of the integration points of every shell of
the slab (``S1``, ``S1#2``, ...) are averaged across the width of each strip at stations along
it, and each check envelopes every station, strip and combination of the project settings.

Design strips (see :func:`design_strips`). Strips run along the slab's local x (they design the
X layers) and along local y (the Y layers). The support lines across a direction are the column
lines (columns meeting the slab, in line within 300 mm) and the beams and walls at the slab's
level running that way. A column strip is centred on each support line, with a half-width on
each side of 0.25 min(l1, l2) (ACI 8.4.1.5; l1 the span of the bay along the strip, l2 the
distance to the next line on that side; at the slab's edge only the inside half, or the
overhang where the slab runs past the line). Middle strips fill the space between column strips
(8.4.1.6). The strips are cut into bays at the faces of the support lines across them (the
faces of columns, beams and walls: the design sections of ACI 8.10.4.1 / 8.11.6.1): the slab
over a support further in from its faces than half a station spacing, or than the support's
centre line, is designed with the support, not by the strips. A direction with fewer than two
support lines across it (no column grid: an irregular drawn area, a slab of a special
structure) is cut into equal strips at most 1 m wide instead (the conventional design per
metre width, and never narrower than the mesh).

Averaging (see :func:`element_means` and :func:`strip_average`). The Wood-Armer design moments
are taken at each integration point first, bottom and top separately (conservative: the average
of |mxy| is at least |average mxy|; SAFE's Wood-Armer option does the same). Each shell is then
reduced to the area-weighted mean of its points at its centre: the points of a shell carry a
gradient of their own (near a column several times the moment field's), but the shells' means
are in equilibrium with the loads, on any mesh. A shell belongs to the strip its centre lies
in; shells with their centre inside a column are left out (for one-way shear, within 2d of a
column). Stations along each bay are spaced about the mesh size (⌈ln / mesh⌉ intervals), the
first and last at the support faces. The value at a station is a least-squares parabola along
the strip through the shells' means, each weighted by its area (so the mean across the strip
on any mesh), taken at the station: through the shells within 1.25 mesh sizes either way at an
inner station, and from the face to the middle of the bay at a face (the static moment of a
uniform load is a parabola), so a face value is the face's and not that of the first row of
shells, half a mesh size or more into the span (for the shear a straight line). The shells
taken in reach into a support no further than half a spacing and never to its centre line, so
nothing of the next span, where the shear has the other sign, is taken in. On a flat slab the
strip moments of a bay add up to its static moment ln² / 8 per unit load and width within a
few per cent at a mesh of 0.5 m and of 1 m alike (tests).

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
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design import slab_systems
from saengine.design.clauses import clause as pack_clause
from saengine.design.clauses import short_clause, short_name
from saengine.design.rc import (
    bar_area,
    beta1,
    phi_axial_flexure,
)
from saengine.design.rc import value as rc_value
from saengine.library.objects import BarMesh, PlanarReinforcement

METHOD = [
    (
        "Slabs (analysed as shells): moments per unit width at every integration point of "
        "every shell, turned into the slab's reinforcement axes (local x: global X for floor-"
        "plan slabs, the first outline edge for drawn areas), Wood-Armer design moments at each "
        "point: bottom Mx* = mx + |mxy|, My* = my + |mxy|, top Mx* = mx - |mxy|, My* = my - "
        "|mxy|, with Armer's corrections when one of a pair has the wrong sign. Membrane forces "
        "are not included."
    ),
    (
        "Slab design strips (ACI 8.4.1.1-8.4.1.2: any method satisfying equilibrium and "
        "compatibility; strips per 8.4.1.5-8.4.1.6, as SAFE/ETABS design FE slabs): along x "
        "(X bars) and along y (Y bars); support lines are the column lines (columns in line "
        "within 300 mm) and the beams and walls running that way; a column strip on each line "
        "extends 0.25 min(l1, l2) each side (l2 to the next line on that side; at an edge the "
        "inside half only), middle strips fill the rest; strips are cut into bays at the "
        "support faces. The Wood-Armer moments are taken at each integration point first "
        "(bottom and top separately), then each shell is reduced to the area-weighted mean of "
        "its points at its centre (shells' means are in equilibrium with the loads on any "
        "mesh); a shell belongs to the strip its centre lies in. Stations about one mesh size "
        "apart along each bay, the first and last at the faces; at each, a least-squares "
        "parabola along the strip through the shells' means, weighted by their areas (the "
        "mean across the strip), is taken at the station: through the shells within 1.25 mesh "
        "sizes at an inner station, from the face to mid-bay at a face (the shape of the static "
        "moment), never reaching into a support to its centre line. The design moment of a "
        "layer is the envelope over stations, strips and combinations, reported with the "
        "governing strip. Without at least two support lines across a direction (no column "
        "grid), that direction is cut into equal strips at most 1 m wide (design per metre "
        "width, never narrower than the mesh). Shells with their centre inside a column are "
        "not designed."
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
        "22.5.5.1 (c), no shear reinforcement, λ = 1), ρ and d of the layer in tension under "
        "the strip's average moment, against the transverse shear Qx (X strips), Qy (Y strips) "
        "averaged across the strip like the moments (a straight line instead of a parabola), "
        "leaving out the shells with their centre within 2d of a column's faces (two-way "
        "shear governs there)."
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
LAYERS = ("bottomX", "bottomY", "topX", "topY")


def _eps_t_min() -> float:
    """Least net tensile strain of a nonprestressed slab, the pack's ``concrete.slabStrainMin``
    (default pack BNBC 2020: 0.004, ACI 7.3.3.1, 8.3.3.1)."""
    return float(code_context.table("concrete").slabStrainMin)


def _phi_punching() -> float:
    """φ of two-way (punching) shear, the pack's ``factors.phi.punching`` (default pack BNBC 2020: 0.75, as
    the shear φ)."""
    return float(code_context.table("factors").phi["punching"])


def _two_way_thickness(drop: bool = False) -> dict[float, tuple[float, float, float]]:
    """ACI Table 8.3.1.1 (without drop panels), the pack's ``concrete.twoWayThickness``: fy ->
    (exterior without edge beams, exterior with edge beams, interior) divisors of ln (default pack BNBC
    2020: 280 -> 33, 36, 36; 420 -> 30, 33, 33; 520 -> 28, 31, 31). With ``drop``: the
    columns with drop panels, ``concrete.twoWayThicknessDrop`` (default pack BNBC 2020 Table 6.6.3: 280 ->
    36, 40, 40; 420 -> 33, 36, 36; 520 -> 31, 34, 34)."""
    table = code_context.table("concrete")
    if drop:
        found = getattr(table, "twoWayThicknessDrop", None)
        if found is None:
            raise ValueError("the code pack has no minimum thickness with drop panels")
        return found
    return table.twoWayThickness


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


def integration_areas(points: Sequence[np.ndarray], count: int) -> list[float]:
    """The plan area each of a shell's :func:`integration_points` stands for (its weight times
    the Jacobian: the four of a Q4 share its area by its shape, a T3's three equally) [units²
    of ``points``]."""
    p = [np.asarray(q, dtype=float)[:2] for q in points]
    if len(p) == 4 and count == 4:
        g = 1 / math.sqrt(3)
        out = []
        for xi, eta in ((-g, -g), (g, -g), (g, g), (-g, g)):
            d_xi = ((1 - eta) * (p[1] - p[0]) + (1 + eta) * (p[2] - p[3])) / 4
            d_eta = ((1 - xi) * (p[3] - p[0]) + (1 + xi) * (p[2] - p[1])) / 4
            out.append(abs(float(d_xi[0] * d_eta[1] - d_xi[1] * d_eta[0])))
        return out
    area = _polygon_area(p)
    return [area / count] * count if count else []


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
    area: float, d: float, fc: float, fy: float, es: float | None = None, width: float = 1000.0
) -> LayerCapacity:
    """φMn of a strip ``width`` wide with ``area`` of bars at depth ``d`` (ACI 22.2, the
    rectangular stress block; φ by ACI 21.2.2)."""
    if es is None:
        es = rc_value("STEEL_E")
    if d <= 0:
        raise ValueError("the cover leaves no room for the bars")
    a = area * fy / (0.85 * fc * width)
    c = a / beta1(fc)
    eps_t = rc_value("EPS_CU") * (d - c) / c if c > 0 else math.inf
    phi = phi_axial_flexure(eps_t, fy, es)
    mn = area * fy * (d - a / 2)
    limit = rc_value("EPS_CU") / (rc_value("EPS_CU") + _eps_t_min())
    return LayerCapacity(area, d, a, c, eps_t, phi, mn, phi * mn, limit)


def one_way_shear(rho: float, d: float, fc: float, lam: float = 1.0) -> tuple[float, float]:
    """φVc per metre [N/m] of a slab without shear reinforcement (ACI Table 22.5.5.1 (c)) and
    its size effect factor λs: Vc = 0.66 λs λ ρ^(1/3) √f'c b d <= 0.42 λ √f'c b d,
    √f'c <= 8.3 MPa, λs = √(2 / (1 + 0.004 d)) <= 1, b = 1000 mm."""
    root = min(math.sqrt(fc), 8.3)
    lambda_s = min(1.0, math.sqrt(2 / (1 + 0.004 * d)))
    vc = 0.66 * lambda_s * lam * max(rho, 0.0) ** (1 / 3) * root * 1000 * d
    vc = min(vc, 0.42 * lam * root * 1000 * d)
    return rc_value("PHI_SHEAR") * vc, lambda_s


def min_steel_ratio(fy: float, aggregate: str | None = None) -> float:
    """As,min / Ag of a slab: the shrinkage and temperature ratio of the code pack (B21,
    :func:`saengine.design.rc_detailing.shrinkage_ratio`: the default pack's BNBC 8.1.11.2 (a) 0.0020 below fy
    420, else the greater of 0.0018 x 420 / fy and 0.0014), times the aggregate's factor
    (8.1.11.2 (b): x 1.5 for brick aggregate). ``aggregate``: None, the project's."""
    from saengine.design.rc_detailing import shrinkage_ratio

    return shrinkage_ratio(fy, aggregate)[0]


#: φ of a tension-controlled section (ACI Table 21.2.2), taken for the rebar contours.
PHI_TENSION = 0.90


def required_area(moment: float, d: float, fc: float, fy: float, width: float = 1000.0) -> float:
    """As [mm²/m] a layer at depth ``d`` (mm) needs for ``moment`` [N·mm/m] (the rectangular
    stress block, ACI 22.2, tension-controlled φ = 0.90; compression ``width`` mm per metre):
    ρ = 0.85 f'c / fy (1 - √(1 - 2 Rn / (0.85 f'c))), Rn = Mu / (φ b d²), As = ρ b d with
    b = ``width``, per metre. A moment beyond the section's (Rn above 0.85 f'c / 2) returns
    the steel at that limit: the contour then shows the section is too thin there."""
    if moment <= 0 or d <= 0:
        return 0.0
    rn = moment / (rc_value("PHI_TENSION") * width * d**2)
    k = 0.85 * fc
    root = max(0.0, 1 - 2 * rn / k)
    return k / fy * (1 - math.sqrt(root)) * width * d


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


def two_way_divisor(fy: float, exterior: bool, edge_beams: bool, drop: bool = False) -> float:
    """The ln divisor of ACI Table 8.3.1.1 (``drop``: with drop panels), interpolated in fy
    (footnote)."""
    column = 2 if not exterior else (1 if edge_beams else 0)
    table = _two_way_thickness(drop)
    keys = sorted(table)
    fy = min(max(fy, keys[0]), keys[-1])
    for lo, hi in pairwise(keys):
        if lo <= fy <= hi:
            a, b = table[lo][column], table[hi][column]
            return a + (b - a) * (fy - lo) / (hi - lo)
    return table[keys[-1]][column]


@dataclass(frozen=True)
class Thickness:
    required: float  # mm
    table: str
    note: str


def one_way_thickness(
    span: float, continuous_ends: int, fy: float, ribbed: bool = False
) -> Thickness:
    """ACI Table 7.3.1.1: l/20 simply supported, l/24 one end continuous, l/28 both ends
    continuous, times (0.4 + fy / 700) for fy other than 420 MPa. ``ribbed``: the row of beams
    and ribbed one-way slabs of the default pack's BNBC 2020 Table 6.6.1 (p. 900), the pack's
    ``concrete.beamThickness`` (l/16, l/18.5, l/21), against the total depth."""
    if ribbed:
        rows = code_context.table("concrete").beamThickness
        divisor = float(rows[min(continuous_ends, 2)])
        factor = 0.4 + fy / 700
        note = f"l = {span:.0f} mm, ribbed one-way: l/{divisor:g}"
        if abs(factor - 1) > 1e-9:
            note += f" x (0.4 + fy/700) = {factor:.2f}"
        return Thickness(span / divisor * factor, "6.6.1", note)
    divisor = {0: 20.0, 1: 24.0}.get(continuous_ends, 28.0)
    factor = 0.4 + fy / 700
    ends = {0: "simply supported", 1: "one end continuous"}.get(continuous_ends, "both continuous")
    note = f"l = {span:.0f} mm, {ends}: l/{divisor:g}"
    if abs(factor - 1) > 1e-9:
        note += f" x (0.4 + fy/700) = {factor:.2f}"
    return Thickness(span / divisor * factor, "7.3.1.1", note)


def two_way_thickness(
    ln: float,
    beta: float,
    alpha_fm: float,
    fy: float,
    exterior: bool,
    edge_beams: bool,
    drop: bool = False,
) -> Thickness:
    """ACI 8.3.1.1 (αfm <= 0.2: Table 8.3.1.1, at least 125 mm; ``drop``: with drop panels, at
    least 100 mm) or 8.3.1.2 (with beams: ln (0.8 + fy/1400) / (36 + 5β(αfm - 0.2)) >= 125 mm
    for αfm <= 2, / (36 + 9β) >= 90 mm above)."""
    if alpha_fm <= 0.2:
        divisor = two_way_divisor(fy, exterior, edge_beams, drop)
        panel = (
            "interior" if not exterior else "exterior" + (" with edge beams" if edge_beams else "")
        )
        least = slab_systems.DROP_MIN_THICKNESS if drop else 125.0
        return Thickness(
            max(ln / divisor, least),
            "8.3.1.1",
            f"ln = {ln:.0f} mm, {panel} panel"
            + (" with drop panels" if drop else "")
            + f": ln/{divisor:.1f}, at least {least:.0f} mm",
        )
    factor = 0.8 + fy / 1400
    if alpha_fm <= 2.0:
        required = max(ln * factor / (36 + 5 * beta * (alpha_fm - 0.2)), 125.0)
    else:
        required = max(ln * factor / (36 + 9 * beta), 90.0)
    return Thickness(required, "8.3.1.2", f"ln = {ln:.0f} mm, β = {beta:.2f}, αfm = {alpha_fm:.2f}")


@dataclass(frozen=True)
class EdgeBeam:
    """A beam in the plan (mm) with its flexural stiffness E I [N·mm²], width and total depth
    [mm] (0: not known; the coefficient method's depth rule then cannot be checked)."""

    start: tuple[float, float]
    end: tuple[float, float]
    ei: float
    width: float
    depth: float = 0.0


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
    drop: bool = False,
    ribbed: bool = False,
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

    ``drop``: the slab has drop panels that qualify (slab_systems.drop_qualifies), so the
    two-way table with drop panels applies; ``ribbed``: a one-way slab with ribs, by the row of
    beams and ribbed one-way slabs (``h`` is then the total depth).
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
        result = one_way_thickness(span, sum(ends), fy, ribbed)
        return Thickness(
            result.required, result.table, result.note + f", along {'x' if along_x else 'y'}"
        )
    long_x = lx >= ly
    ln_long = max(lx, ly) - support
    ln_short = max(min(lx, ly) - support, 1.0)
    exterior = not all(sides.values())
    edge_beams = bool(exterior_beams) and all(exterior_beams)
    result = two_way_thickness(
        ln_long, ln_long / ln_short, alpha_fm, fy, exterior, edge_beams, drop and alpha_fm <= 0.2
    )
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


# ─────────────────────────────────────── design strips ───────────────────────────────────────

#: Columns (and beams) this close across are on one support line [mm] (as :func:`_grid_span`).
LINE_TOLERANCE = 300.0
#: Width of the strips of a direction without a column grid [mm] (design per metre width).
FALLBACK_WIDTH = 1000.0
#: A beam or wall is a support line when it runs within this angle of a slab axis [°].
PARALLEL = 5.0


@dataclass(frozen=True)
class LineSupport:
    """A beam or wall at a slab's level (plan, mm), which supports it along its line."""

    id: str
    start: tuple[float, float]
    end: tuple[float, float]
    width: float  # mm
    #: "beam", "wall" or "" (not stated). Only the coefficient methods use it: a side of a
    #: panel counts as on a wall only where a "wall" support lies, never by default.
    kind: str = ""


@dataclass(frozen=True)
class SupportLine:
    """Supports in line across a direction: their position across (``at``, mm in the slab's
    axes), the half-width of the widest one along the strips they cut (their faces are at
    ``at ± half``) and their ids."""

    at: float
    half: float
    ids: tuple[str, ...]


@dataclass(frozen=True)
class Strip:
    """One bay of a design strip, in the slab's axes (mm): it runs along ``direction`` ("X":
    along local x, designing the X layers) from ``start`` to ``end`` (support faces or slab
    edges) and spans ``lo`` to ``hi`` across. ``kind``: "column", "middle" or "strip" (a
    strip of a direction without a column grid); ``span`` is the bay's l1. ``before`` and
    ``after``: how far past ``start`` and ``end`` the support there reaches to its centre line
    (its half-width; 0 at a slab edge): the face stations sample the slab no further into the
    support, so they never take in the next span's points (where the shear changes sign)."""

    direction: str
    kind: str
    name: str
    lo: float
    hi: float
    start: float
    end: float
    span: float
    before: float = 0.0
    after: float = 0.0

    @property
    def width(self) -> float:
        return self.hi - self.lo


@dataclass(frozen=True)
class StripLayout:
    """The design strips of a slab in one direction; ``note`` says when it has no grid."""

    strips: list[Strip]
    note: str | None = None


class PlanFrame:
    """A slab's plan axes: local (s, t) coordinates [mm] of plan points along its x and y."""

    def __init__(self, axes: SlabAxes) -> None:
        ux, uy = np.asarray(axes.x[:2], dtype=float), np.asarray(axes.y[:2], dtype=float)
        self.ux = ux / (np.linalg.norm(ux) or 1.0)
        self.uy = uy / (np.linalg.norm(uy) or 1.0)

    def local(self, point: Sequence[float]) -> tuple[float, float]:
        p = np.asarray(point[:2], dtype=float)
        return float(p @ self.ux), float(p @ self.uy)

    def plan(self, s: float, t: float) -> np.ndarray:
        """The plan point [mm] of local coordinates (s, t)."""
        return self.ux * s + self.uy * t


def _cluster(found: list[tuple[float, float, str]]) -> list[SupportLine]:
    """Support lines from (position across, half-width, id), merging those within
    :data:`LINE_TOLERANCE` of the first of a line."""
    lines: list[list[tuple[float, float, str]]] = []
    for item in sorted(found):
        if lines and item[0] - lines[-1][0][0] <= LINE_TOLERANCE:
            lines[-1].append(item)
        else:
            lines.append([item])
    return [
        SupportLine(
            sum(i[0] for i in line) / len(line),
            max(i[1] for i in line),
            tuple(dict.fromkeys(i[2] for i in line)),
        )
        for line in lines
    ]


def support_lines(
    along: int,
    frame: PlanFrame,
    extent: tuple[float, float, float, float],
    columns: Sequence[ColumnJoint],
    supports: Sequence[LineSupport],
) -> list[SupportLine]:
    """The support lines running along local x (``along`` 0: lines of constant t) or local y
    (1: constant s), sorted across. ``extent``: the slab's (s0, s1, t0, t1) in its axes [mm].
    A column gives a line through its centre with its half-size across the line; a beam or wall
    running that way (within :data:`PARALLEL`) whose line lies on the slab and which runs over
    at least half the slab's length, or half its own, gives a line with half its width."""
    across = 1 - along
    found: list[tuple[float, float, str]] = []
    reference = math.degrees(math.atan2(frame.ux[1], frame.ux[0]))
    for column in columns:
        position = frame.local(column.centre)
        angle = math.radians(column.angle - reference)
        c, s = abs(math.cos(angle)), abs(math.sin(angle))
        # Half-sizes along local x and y of the (turned) column.
        half = (column.c1 * c + column.c2 * s) / 2, (column.c1 * s + column.c2 * c) / 2
        found.append((position[across], half[across], column.id))
    lo, hi = extent[2 * along], extent[2 * along + 1]
    lo_across, hi_across = extent[2 * across], extent[2 * across + 1]
    for support in supports:
        a, b = frame.local(support.start), frame.local(support.end)
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length < 1 or abs(b[along] - a[along]) < length * math.cos(math.radians(PARALLEL)):
            continue
        at = (a[across] + b[across]) / 2
        if not lo_across - 1 <= at <= hi_across + 1:
            continue
        s0, s1 = sorted((a[along], b[along]))
        overlap = min(s1, hi) - max(s0, lo)
        if overlap <= 0 or overlap < 0.5 * min(s1 - s0, hi - lo):
            continue
        found.append((at, support.width / 2, support.id))
    return _cluster(found)


def _bays(
    lines: list[SupportLine], lo: float, hi: float
) -> list[tuple[float, float, float, float, float]]:
    """The bays (start, end, span l1, support half-width before start, after end) between the
    faces of the support ``lines`` across a strip and the slab's edges ``lo``, ``hi`` along it:
    overhangs past the first and last line are bays of their own (span: edge to line)."""
    if not lines:
        return [(lo, hi, hi - lo, 0.0, 0.0)]
    bays = []
    first, last = lines[0], lines[-1]
    if first.at - first.half - lo > 1:
        bays.append((lo, first.at - first.half, first.at - lo, 0.0, first.half))
    for a, b in pairwise(lines):
        if b.at - b.half - (a.at + a.half) > 1:
            bays.append((a.at + a.half, b.at - b.half, b.at - a.at, a.half, b.half))
    if hi - (last.at + last.half) > 1:
        bays.append((last.at + last.half, hi, hi - last.at, last.half, 0.0))
    return bays


def _names(ids: tuple[str, ...]) -> str:
    return ", ".join(ids[:3]) + (", ..." if len(ids) > 3 else "")


def design_strips(
    direction: str,
    frame: PlanFrame,
    extent: tuple[float, float, float, float],
    columns: Sequence[ColumnJoint],
    supports: Sequence[LineSupport],
    mesh: float,
) -> StripLayout:
    """The design strips of a slab along ``direction`` ("X" or "Y"), bay by bay (see the module
    notes): column strips 0.25 min(l1, l2) each side of the support lines across the direction
    (ACI 8.4.1.5), middle strips between them (8.4.1.6), or, with fewer than two lines across,
    equal strips at most :data:`FALLBACK_WIDTH` (and at least ``mesh``) wide."""
    along = 0 if direction == "X" else 1
    across_axis = "y" if direction == "X" else "x"
    lines = support_lines(along, frame, extent, columns, supports)  # across the strips' width
    ends = support_lines(1 - along, frame, extent, columns, supports)  # cutting them into bays
    lo, hi = extent[2 * along], extent[2 * along + 1]
    lo_t, hi_t = extent[2 * (1 - along)], extent[2 * (1 - along) + 1]
    strips: list[Strip] = []
    note = None
    for bay in _bays(ends, lo, hi):
        span = bay[2]
        if len(lines) < 2:
            width = max(FALLBACK_WIDTH, mesh)
            count = max(1, math.ceil((hi_t - lo_t) / width - 1e-9))
            step = (hi_t - lo_t) / count
            for k in range(count):
                a, b = lo_t + k * step, lo_t + (k + 1) * step
                strips.append(
                    Strip(
                        direction,
                        "strip",
                        f"{direction} strip {across_axis} = {a / 1e3:.2f} to {b / 1e3:.2f} m",
                        a,
                        b,
                        *bay,
                    )
                )
            note = (
                f"{direction} strips: fewer than two support lines across {direction} (no column "
                f"grid), designed in {count} equal strips {step / 1e3:.2f} m wide (at most "
                f"{width / 1e3:.2f} m: design per metre width) instead of column and middle strips"
            )
            continue
        bands: list[tuple[float, float, SupportLine]] = []
        for k, line in enumerate(lines):
            below = line.at - lines[k - 1].at if k > 0 else None
            above = lines[k + 1].at - line.at if k + 1 < len(lines) else None
            half_below = 0.25 * min(span, below) if below is not None else None
            half_above = 0.25 * min(span, above) if above is not None else None
            # At the slab's edge: the inside half only, or the overhang past the line.
            if half_below is None:
                half_below = min(half_above or 0.0, max(line.at - lo_t, 0.0))
            if half_above is None:
                half_above = min(half_below, max(hi_t - line.at, 0.0))
            a, b = max(line.at - half_below, lo_t), min(line.at + half_above, hi_t)
            if b - a > 1:
                bands.append((a, b, line))
        edge = lo_t
        for a, b, line in bands:
            if a - edge > 1:
                strips.append(_middle(direction, across_axis, edge, a, bay))
            strips.append(
                Strip(
                    direction,
                    "column",
                    f"{direction} column strip on the line of {_names(line.ids)} "
                    f"({across_axis} = {line.at / 1e3:.2f} m)",
                    a,
                    b,
                    *bay,
                )
            )
            edge = b
        if hi_t - edge > 1:
            strips.append(_middle(direction, across_axis, edge, hi_t, bay))
    return StripLayout(strips, note)


def _middle(
    direction: str,
    axis: str,
    a: float,
    b: float,
    bay: tuple[float, float, float, float, float],
) -> Strip:
    return Strip(
        direction,
        "middle",
        f"{direction} middle strip {axis} = {a / 1e3:.2f} to {b / 1e3:.2f} m",
        a,
        b,
        *bay,
    )


def stations(strip: Strip, mesh: float) -> list[tuple[float, float, float]]:
    """Design sections along a strip's bay: (station, band start, band end) [mm], ⌈ln / mesh⌉
    intervals from face to face, each band reaching half way to the next station on both sides.
    At a face the band reaches into the support by half a spacing at most and never to the
    support's centre line (``strip.before`` / ``strip.after``, less 1 mm), so it takes in the
    slab between the face and the centre line but nothing of the next span, where the shear has
    the other sign. :func:`strip_average` fits over wider windows but within the first and last
    band's limits."""
    length = strip.end - strip.start
    count = max(1, math.ceil(length / mesh - 1e-9)) if mesh > 0 else 1
    step = length / count
    into = (
        min(step / 2, max(strip.before - 1.0, 0.0)),
        min(step / 2, max(strip.after - 1.0, 0.0)),
    )
    out = []
    for k in range(count + 1):
        at = strip.start + k * step
        a = at - (into[0] if k == 0 else step / 2)
        b = at + (into[1] if k == count else step / 2)
        out.append((at, a, b))
    return out


def strip_weights(across: np.ndarray, lo: float, hi: float, reach: float) -> np.ndarray:
    """The width [mm] each point at ``across`` represents in a strip from ``lo`` to ``hi``:
    half way to its neighbours, to the strip's edges from the outermost points but at most
    ``reach`` beyond them; points within 1 mm of each other share their width."""
    order = np.argsort(across, kind="stable")
    values = across[order]
    groups: list[list[int]] = []
    for k, value in enumerate(values):
        if groups and value - values[groups[-1][0]] <= 1.0:
            groups[-1].append(k)
        else:
            groups.append([k])
    centres = [float(np.mean(values[g])) for g in groups]
    weights = np.zeros(len(across))
    for k, group in enumerate(groups):
        left = (centres[k - 1] + centres[k]) / 2 if k > 0 else max(lo, centres[k] - reach)
        right = (
            (centres[k] + centres[k + 1]) / 2
            if k + 1 < len(groups)
            else min(hi, centres[k] + reach)
        )
        share = max(right - left, 0.0) / len(group)
        for index in group:
            weights[order[index]] = share
    return weights


def strip_average(
    strip: Strip,
    along: np.ndarray,
    across: np.ndarray,
    values: np.ndarray,
    mesh: float,
    keep: np.ndarray | None = None,
    areas: np.ndarray | None = None,
    degree: int = 2,
) -> list[tuple[float, np.ndarray]]:
    """The averages across a strip of ``values`` (one row per point, any trailing shape) at
    each of its :func:`stations` that has points: (station [mm], average). ``along``,
    ``across``: the points' coordinates in the slab's axes along and across the strip [mm];
    ``keep``: the points that count (default all).

    Each point is weighted by the plan area it stands for (``areas``: on any mesh, structured
    or not, the area-weighted mean over a band is the mean across the strip), or without
    ``areas`` by its width across (:func:`strip_weights`, for points in rows). The value at a
    station is a weighted least-squares polynomial along the strip of ``degree`` (2: a
    parabola, the shape of the static moment under a uniform load; 1 for the shear), taken at
    the station: through the points within 1.25 ``mesh`` either way at an inner station, from
    the face to the middle of the bay at a face, so the face value is the face's and not that
    of the first row of shells, half a mesh size or more into the span (with fewer distinct
    positions along, a lower degree). No point further into a support than the face bands of
    :func:`stations` allow is taken in."""
    inside = (across >= strip.lo - 1e-6) & (across <= strip.hi + 1e-6)
    inside &= (along >= strip.start - mesh) & (along <= strip.end + mesh)
    if keep is not None:
        inside &= keep
    candidates = np.flatnonzero(inside)
    middle = (strip.start + strip.end) / 2
    found = stations(strip, mesh)
    first, last = found[0][1], found[-1][2]  # into the supports no further than allowed
    reach = 1.25 * mesh
    out = []
    for k, (at, a, b) in enumerate(found):
        if k == 0 and len(found) > 2:
            a, b = first, middle
        elif k == len(found) - 1 and len(found) > 2:
            a, b = middle, last
        else:
            a, b = max(first, at - reach), min(last, at + reach)
        position = along[candidates]
        chosen = candidates[(position >= a - 1e-6) & (position <= b + 1e-6)]
        if not len(chosen):
            continue
        weights = (
            strip_weights(across[chosen], strip.lo, strip.hi, mesh / 2)
            if areas is None
            else np.asarray(areas, dtype=float)[chosen]
        )
        if float(weights.sum()) <= 0:
            continue
        value = _fit(along[chosen], weights, values[chosen], at, degree, mesh)
        out.append((at, value))
    return out


def _fit(
    along: np.ndarray, weights: np.ndarray, values: np.ndarray, at: float, degree: int, mesh: float
) -> np.ndarray:
    """A weighted least-squares polynomial along the strip of at most ``degree`` through the
    points, taken at ``at``: of lower degree when the points lie at fewer distinct positions
    along (:func:`_positions`, a quarter mesh size apart) than it needs."""
    scale = max(mesh, 1.0)
    degree = min(degree, _positions(along, scale / 4) - 1)
    flat = values.reshape(len(values), -1)
    if degree <= 0:
        mean = weights @ flat / weights.sum()
        return mean.reshape(values.shape[1:])
    x = (along - at) / scale  # the value at the station is the constant term
    basis = np.vander(x, degree + 1, increasing=True)
    root = np.sqrt(weights)[:, None]
    solution = np.linalg.lstsq(basis * root, flat * root, rcond=None)[0]
    return solution[0].reshape(values.shape[1:])


def _positions(along: np.ndarray, tolerance: float) -> int:
    """How many distinct positions the points lie at: in order along, a point further than
    ``tolerance`` from the first point of the current position starts the next (as
    :func:`strip_weights` groups points). A row of shells whose centres scatter by a few mm (an
    irregular mesh) is one position wherever it lies; rounding to fixed steps would count a row
    across a step's edge twice, and a parabola through two rows would bend to their scatter."""
    count, first = 0, -math.inf
    for value in np.sort(along):
        if value - first > tolerance:
            count, first = count + 1, float(value)
    return count


def element_means(
    groups: np.ndarray,
    plan: np.ndarray,
    values: np.ndarray,
    areas: np.ndarray,
    keep: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per shell (``groups``: the shell of each point), the area-weighted mean of the ``values``
    of its points that are kept, at their area-weighted centre (``plan``: (points, any number
    of coordinates)), with their area: (centres, means, areas). A shell's integration points
    carry a gradient within it that need not be the moment field's (near a column it is
    several times too steep), but its mean is in equilibrium with the loads: strips average
    shells' means."""
    index = np.flatnonzero(keep)
    labels, inverse = np.unique(groups[index], return_inverse=True)
    weight = areas[index]
    total = np.bincount(inverse, weights=weight, minlength=len(labels))
    centres = (
        np.stack(
            [
                np.bincount(inverse, weights=weight * plan[index, k], minlength=len(labels))
                for k in range(plan.shape[1])
            ],
            axis=1,
        )
        / total[:, None]
    )
    flat = values[index].reshape(len(index), -1) * weight[:, None]
    means = np.zeros((len(labels), flat.shape[1]))
    np.add.at(means, inverse, flat)
    means /= total[:, None]
    return centres, means.reshape((len(labels), *values.shape[1:])), total


def mesh_size(area: float, points: int) -> float:
    """The mesh size [mm] a slab of ``area`` [mm²] with ``points`` integration points has:
    a Q4 has four points over h², so h = 2 √(area / points); 1 m when unknown."""
    if area <= 0 or points <= 0:
        return 1000.0
    return 2 * math.sqrt(area / points)


def _polygon_area(points: Sequence[Sequence[float]]) -> float:
    flat = [(float(p[0]), float(p[1])) for p in points]
    return abs(
        sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(flat, flat[1:] + flat[:1], strict=True))
        / 2
    )


# ─────────────────────────────────────── the checks ───────────────────────────────────────


@dataclass
class ShellPoint:
    """The forces of one shell of a slab at its integration points, per combination."""

    id: int
    name: str
    points: list[np.ndarray]  # positions [m]
    forces: list[np.ndarray]  # per combination: (points, 5) mx my mxy qx qy [N·m/m, N/m]
    #: The plan area [m²] each point stands for (:func:`integration_areas`); None: all alike.
    areas: list[float] | None = None


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
    axes: SlabAxes = field(default_factory=plan_axes)
    supports: list[LineSupport] = field(default_factory=list)  # beams and walls at its level
    #: Filled by :func:`slab_checks`: the design strips of both directions.
    strips: list[Strip] = field(default_factory=list)
    #: Filled by :func:`slab_checks`: the strip averages at every station.
    sections: list[StripSection] = field(default_factory=list)
    #: Filled by :func:`slab_checks`: the largest one-way shear [N/m] each layer's ρ resists
    #: (layer name -> (|Vu|, combination, where)), for the design mode.
    shear: dict[str, tuple[float, str | None, str]] = field(default_factory=dict)
    #: Integrator glue: the slab type's punching reinforcement (``objects.PunchingReinforcement``)
    #: or None; checked (and else proposed) where the concrete alone is not enough.
    punching: Any = None
    #: The slab type's ribs (:class:`slab_systems.RibSection`), drop panel
    #: (``objects.DropPanel``) and column capital (``objects.ColumnCapital``), or None.
    ribs: slab_systems.RibSection | None = None
    drop: Any = None
    capital: Any = None
    #: Filled by :func:`slab_checks`: per shell id, the steel [mm²/m] each layer (LAYERS order)
    #: needs for its Wood-Armer moment, enveloped over the combinations (the rebar contours).
    contours: dict[int, list[float]] = field(default_factory=dict)
    #: Integrator glue: the effective precompression [MPa] of the slab's tendons along x and
    #: along y (saengine.design.prestress), for punching with prestress; None: not prestressed.
    precompression: tuple[float, float] | None = None


@dataclass(frozen=True)
class StripSection:
    """The averages across a strip at one station [mm along it], per combination [N·m/m]:
    ``moment`` the signed moment of the strip's direction (mx for X strips, my for Y strips;
    sagging positive), ``bottom`` and ``top`` the Wood-Armer moments of its layers."""

    strip: Strip
    at: float
    moment: np.ndarray
    bottom: np.ndarray
    top: np.ndarray


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

    ribs = context.ribs
    layers = _slab_layers(reinforcement, h, ribs)

    def compression_width(name: str) -> float:
        """The compression zone's width per metre: the ribs' webs under a hogging moment in a
        rib direction (slab_systems), else the whole metre."""
        if ribs is not None and name.startswith("top") and name[-1] in ribs.directions:
            return ribs.web_per_metre
        return 1000.0

    capacities = {
        name: (
            layer_capacity(layer.area, layer.d, fc, fy, es, compression_width(name))
            if layer is not None
            else None
        )
        for name, layer in layers.items()
    }
    # Over drop panels the top bars work at the panel's depth (ACI 318-19 8.5.2.2), limited by
    # the column (or capital) with the least reach to the panel's edge.
    drop = context.drop if context.columns else None
    h_drop = h
    drop_layers: dict[str, Layer | None] = {}
    drop_capacities: dict[str, LayerCapacity | None] = {}
    if drop is not None:
        h_drop = min(
            slab_systems.drop_flexure_depth(
                h, drop, *slab_systems.support_size(c.c1, c.c2, context.capital)
            )
            for c in context.columns
        )
        drop_layers = layers_of(reinforcement, h_drop)
        drop_capacities = {
            name: layer_capacity(layer.area, layer.d, fc, fy, es) if layer is not None else None
            for name, layer in drop_layers.items()
        }

    def over_drop(point: Sequence[float]) -> bool:
        """Whether a plan point (mm) lies over a drop panel."""
        return drop is not None and any(
            slab_systems.drop_zone(c.centre, c.angle, drop.length, drop.width, point)
            for c in context.columns
        )

    # Envelopes: (value, combination, where); over the drop panels the top layers apart.
    envelope: dict[str, tuple[float, str | None, str]] = {n: (0.0, None, "") for n in LAYERS}
    drop_env: dict[str, tuple[float, str | None, str]] = {
        n: (0.0, None, "") for n in LAYERS if n.startswith("top")
    }
    shear_env: dict[str, tuple[float, float, float, str | None, str]] = {}

    def shear_capacity(direction: str, sagging: bool) -> tuple[float, str] | None:
        order = ("bottom", "top") if sagging else ("top", "bottom")
        for face in order:
            capacity = capacities[f"{face}{direction}"]
            if capacity is not None:
                if ribs is not None and direction in ribs.directions:
                    # The ribs' webs, 1.1 Vc (ACI 318-19 9.8.1.5).
                    web = ribs.web_per_metre
                    rho = capacity.area / (web * capacity.d)
                    phi_vc = one_way_shear(rho, capacity.d, fc)[0] * web / 1000
                    return phi_vc * slab_systems.RIB_SHEAR_FACTOR, f"{face}{direction}, ribs"
                rho = capacity.area / (1000 * capacity.d)
                return one_way_shear(rho, capacity.d, fc)[0], f"{face}{direction}"
        return None

    # Shells with their centre inside a column are not designed for flexure (the design moment
    # is at the face), nor within 2d of its faces for one-way shear (two-way shear governs
    # there, ACI 22.6).
    depth = max((layer.d for layer in layers.values() if layer is not None), default=0.0)
    positions = [p for shell in shells for p in shell.points]
    count = len(positions)
    if not count:
        raise ValueError("the slab's shells have no results")
    # The plan area each point stands for; alike when a shell does not say.
    if all(shell.areas is not None for shell in shells):
        areas = np.array([a for shell in shells for a in shell.areas or []], dtype=float)
    else:
        areas = np.ones(count)
    # Per point and combination: mx my mxy qx qy, and the Wood-Armer moments (LAYERS order).
    forces = np.stack(
        [np.concatenate([shell.forces[c] for shell in shells]) for c in range(len(combinations))],
        axis=1,
    )
    design = np.array([[wood_armer(*f[:3]) for f in row] for row in forces])

    frame = PlanFrame(context.axes)
    local = np.array([frame.local(p[:2] * 1e3) for p in positions])
    outline = [frame.local(p) for p in context.boundary] if len(context.boundary) >= 3 else []
    corners = outline or [tuple(q) for q in local]
    extent = (
        min(q[0] for q in corners),
        max(q[0] for q in corners),
        min(q[1] for q in corners),
        max(q[1] for q in corners),
    )
    area = _polygon_area(outline) if outline else 0.0
    mesh = mesh_size(area, count)
    if not outline:  # no outline: the points' extent, half a mesh size round them
        extent = (
            extent[0] - mesh / 2,
            extent[1] + mesh / 2,
            extent[2] - mesh / 2,
            extent[3] + mesh / 2,
        )
    # The shells' means: mx my mxy qx qy, then the Wood-Armer moments; for flexure those of
    # the shells whose centre is outside the columns, for shear further than 2d from them.
    groups = np.repeat(np.arange(len(shells)), [len(shell.points) for shell in shells])
    plan = np.hstack([local, np.array([p[:2] for p in positions])])
    centres, means, weights = element_means(
        groups, plan, np.concatenate([forces, design], axis=2), areas, np.ones(count, bool)
    )
    inside = np.array([_near_column(c[2:], context.columns, 0.0) for c in centres])
    near = np.array([_near_column(c[2:], context.columns, 2 * depth) for c in centres])
    skipped_shells = int(inside.sum())
    # The rebar contours: each shell's Wood-Armer moments, enveloped over the combinations, as
    # the steel each layer needs there (strength only; As,min not included).
    peak = means[:, :, 5:9].max(axis=1) * 1e3  # N·mm/m, LAYERS order
    estimated = _contour_depths(layers, reinforcement, h, ribs)
    estimated_drop = _contour_depths(drop_layers, reinforcement, h_drop, None) if drop else {}
    context.contours = {}
    for i, shell in enumerate(shells):
        if inside[i]:
            continue
        dropped = over_drop(centres[i, 2:] * 1e3)
        row = []
        for k, name in enumerate(LAYERS):
            if dropped and name.startswith("top"):
                d, width = estimated_drop[name], 1000.0
            else:
                d, width = estimated[name], compression_width(name)
            row.append(round(required_area(float(peak[i, k]), d, fc, fy, width), 1))
        context.contours[shell.id] = row
    flexure = centres[~inside], means[~inside], weights[~inside]
    shear = centres[~near], means[~near], weights[~near]
    context.strips, context.sections, context.shear = [], [], {}
    for direction, along in (("X", 0), ("Y", 1)):
        layout = design_strips(direction, frame, extent, context.columns, context.supports, mesh)
        context.strips += layout.strips
        if layout.note:
            context.notes.append(layout.note)
        # Wood-Armer moments of this direction's layers: bottom, top.
        names = (f"bottom{direction}", f"top{direction}")
        columns_of = [LAYERS.index(n) for n in names]
        for strip in layout.strips:

            def where(at: float, strip: Strip = strip, along: int = along) -> str:
                middle = (strip.lo + strip.hi) / 2
                x, y = frame.plan(at, middle) if along == 0 else frame.plan(middle, at)
                return (
                    f"{strip.name}, {strip.width / 1e3:.2f} m wide, station at "
                    f"({x / 1e3:.2f}, {y / 1e3:.2f}) m"
                )

            centres, means, weights = flexure
            fields = means[:, :, [along, *(5 + k for k in columns_of)]]
            s, t = centres[:, along], centres[:, 1 - along]
            for at, averaged in strip_average(strip, s, t, fields, mesh, None, weights):
                context.sections.append(
                    StripSection(strip, at, averaged[:, 0], averaged[:, 1], averaged[:, 2])
                )
                values = averaged[:, 1:]
                middle = (strip.lo + strip.hi) / 2
                dropped = over_drop(
                    frame.plan(at, middle) if along == 0 else frame.plan(middle, at)
                )
                for k, name in enumerate(names):
                    target = drop_env if dropped and name in drop_env else envelope
                    c = int(np.argmax(values[:, k]))
                    if values[c, k] > target[name][0]:
                        target[name] = (float(values[c, k]), combinations[c], where(at))
            # One-way shear: the strip's transverse shear and moment, away from the columns.
            centres, means, weights = shear
            fields = means[:, :, [3 + along, along]]
            s, t = centres[:, along], centres[:, 1 - along]
            for at, values in strip_average(strip, s, t, fields, mesh, None, weights, 1):
                for c, (q, m) in enumerate(values):
                    resisting = shear_capacity(direction, m >= 0)
                    if resisting is None:
                        continue
                    capacity, layer = resisting
                    seen = context.shear.get(layer)
                    if seen is None or abs(q) > seen[0]:
                        context.shear[layer] = (
                            abs(float(q)),
                            combinations[c],
                            f"Q{direction.lower()}; {where(at)}",
                        )
                    ratio = abs(q) / capacity if capacity > 0 else math.inf
                    best = shear_env.get("all")
                    if best is None or ratio > best[0]:
                        shear_env["all"] = (
                            ratio,
                            abs(float(q)),
                            capacity,
                            combinations[c],
                            f"Q{direction.lower()}, ρ of {layer}; {where(at)}",
                        )

    if skipped_shells:
        context.notes.append(
            f"{skipped_shells} shells with their centre inside a column are not designed for "
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
        if ribs is not None and direction in ribs.directions:
            if face == "top":
                note += f", compression in the ribs' webs ({ribs.web_per_metre:.0f} mm/m)"
            elif capacity.a > ribs.topping:
                note += (
                    f"; the compression block (a = {capacity.a:.0f} mm) reaches below the "
                    f"topping ({ribs.topping:.0f} mm): the T-section's web is not counted"
                )
        if where:
            note += f"; {where}"
        checks.append(
            _check(label, demand / 1e3, capacity.phi_mn / 1e6, "kN·m/m", combination, note)
        )

    for name, (demand, combination, where) in drop_env.items():
        if demand <= NO_DEMAND:
            continue
        direction = name[-1]
        label = f"Flexure top {direction} over drop panels (Wood-Armer)"
        layer, capacity = drop_layers.get(name), drop_capacities.get(name)
        if layer is None or capacity is None:
            checks.append(
                _check(
                    label,
                    demand / 1e3,
                    0.0,
                    "kN·m/m",
                    combination,
                    f"no top {direction} bars, but the slab is hogging {demand / 1e3:.2f} "
                    f"kN·m/m over a drop panel: top bars are needed; {where}",
                )
            )
            continue
        checks.append(
            _check(
                label,
                demand / 1e3,
                capacity.phi_mn / 1e6,
                "kN·m/m",
                combination,
                f"{_bars(layer)}: As = {capacity.area:.0f} mm²/m, d = {capacity.d:.0f} mm in "
                f"{h_drop:.0f} mm (the slab and at most a quarter of the panel's reach beyond "
                f"the column or capital face, ACI 318-19 8.5.2.2), φ = {capacity.phi:.2f}; "
                f"{where}",
            )
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
                "φVc = 0.75 · 0.66 λs ρ^(1/3) √f'c b d (ACI 22.5.5.1 (c))"
                + (
                    "; ribs: b = the webs per metre, x 1.1 (ACI 318-19 9.8.1.5)"
                    if ribs is not None
                    else ""
                )
                + f"; {where}",
                utilisation=ratio,
            )
        )

    if present:
        span = span_direction(system, {n: envelope[n][0] for n in LAYERS})
        checks.append(_min_reinforcement_check(system, h, fy, capacities, envelope, span))
        # The bars in the ribs are given per metre: their spacing is the ribs'.
        spaced = {
            n: layer
            for n, layer in layers.items()
            if ribs is None or not (n.startswith("bottom") and n[-1] in ribs.directions)
        }
        if any(spaced.values()):
            checks.append(_max_spacing_check(system, h, spaced, span))
        if ribs is not None:
            checks += _rib_min_reinforcement_checks(ribs, fc, fy, capacities)

    if ribs is not None:
        checks += slab_systems.rib_geometry_checks(ribs)

    if context.thickness is not None:
        t = context.thickness
        checks.append(
            _check(f"Min. thickness (Table {t.table})", t.required, h, "mm", None, t.note, True)
        )

    if system == "flat":
        punching_layers = layers if ribs is None else layers_of(reinforcement, h)
        checks += _punching_checks(
            punching_layers, fc, combinations, context, h=h, fy=fy, cover=reinforcement.cover
        )
    return checks


def _slab_layers(
    reinforcement: PlanarReinforcement, h: float, ribs: slab_systems.RibSection | None
) -> dict[str, Layer | None]:
    """The layers of a slab ``h`` thick; with ribs, those of a rib direction at the total
    depth, the others in the topping (slab_systems)."""
    if ribs is None:
        return layers_of(reinforcement, h)
    full, topping = layers_of(reinforcement, ribs.total), layers_of(reinforcement, h)
    return {n: (full[n] if n[-1] in ribs.directions else topping[n]) for n in LAYERS}


#: Bar assumed for the rebar contours where a layer has no bars [mm].
CONTOUR_BAR = 12.0


def _contour_depths(
    layers: dict[str, Layer | None],
    reinforcement: PlanarReinforcement,
    h: float,
    ribs: slab_systems.RibSection | None,
) -> dict[str, float]:
    """d [mm] of each layer for the rebar contours: the layer's own, or for a layer with no
    bars that of a Ø12 layer (X outer, Y inner) in the depth its direction works in."""
    depths = {}
    for name in LAYERS:
        layer = layers.get(name)
        if layer is not None:
            depths[name] = layer.d
            continue
        depth = ribs.total if ribs is not None and name[-1] in ribs.directions else h
        inner = CONTOUR_BAR if name.endswith("Y") else 0.0
        depths[name] = depth - reinforcement.cover - inner - CONTOUR_BAR / 2
    return depths


def _rib_min_reinforcement_checks(
    ribs: slab_systems.RibSection,
    fc: float,
    fy: float,
    capacities: dict[str, LayerCapacity | None],
) -> list[dict[str, Any]]:
    """As,min of the ribs as beams (ACI 318-19 9.6.1.2: the greater of 0.25 √f'c / fy and
    1.4 / fy times bw d), per metre: bw the webs in a metre, for the bottom bars of each rib
    direction."""
    from saengine.design.check import _check

    ratio = max(0.25 * math.sqrt(fc), 1.4) / fy
    checks = []
    for direction in ribs.directions:
        capacity = capacities[f"bottom{direction}"]
        provided = capacity.area if capacity is not None else 0.0
        d = capacity.d if capacity is not None else ribs.total - 40.0
        required = ratio * ribs.web_per_metre * d
        checks.append(
            _check(
                f"Min. reinforcement of the ribs {direction} (ACI 318-19 9.6.1.2)",
                required,
                provided,
                "mm²/m",
                None,
                f"As,min = max(0.25 √f'c, 1.4) / fy · bw d = {ratio:.5f} x "
                f"{ribs.web_per_metre:.0f} mm/m x {d:.0f} mm",
                utilisation=required / provided if provided > 0 else math.inf,
            )
        )
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
    from saengine.design.rc_detailing import shrinkage_ratio

    ratio, how = shrinkage_ratio(fy)
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
    note = f"As,min = {ratio:.4f} Ag = {as_min:.0f} mm²/m ({how}); governing: {what}"
    if span is not None:
        note += f"; one-way slab spanning {span}" + _integrity_note()
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
            from saengine.design.rc_detailing import shrinkage_spacing

            limit, clause = shrinkage_spacing(h)
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
        f"{layer.name} at {layer.spacing:.0f} mm; "
        + (clause if clause[:1].isupper() else f"ACI {clause}"),
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


def _punching_checks(
    layers: dict[str, Layer | None],
    fc: float,
    combinations: list[str],
    context: SlabContext,
    *,
    h: float | None = None,
    fy: float = 420.0,
    cover: float = 20.0,
) -> list[dict[str, Any]]:
    top = [layer for layer in (layers["topX"], layers["topY"]) if layer is not None]
    source = "top"
    if not top:
        top = [layer for layer in (layers["bottomX"], layers["bottomY"]) if layer is not None]
        source = "bottom (no top bars)"
    if not top:
        return []
    d = sum(layer.d for layer in top) / len(top)
    phi_punching = _phi_punching()
    checks = []
    drop, ribs = context.drop, context.ribs
    head = float(drop.depth) if drop is not None else 0.0
    if ribs is not None and drop is None and context.columns:
        context.notes.append(
            "punching of a ribbed or waffle slab without a solid head is not checked: give the "
            "slab type a drop panel as the solid head round the columns"
        )
        return []
    for column in context.columns:
        # ACI 318-19 22.6.4.1: at d/2 from the column (or capital) face with d through the drop
        # panel, and at d/2 outside the panel's edge with the slab's own d (slab_systems).
        c1, c2 = slab_systems.support_size(column.c1, column.c2, context.capital)
        faces = [(c1, c2, d + head, "capital face" if context.capital is not None else "")]
        if drop is not None and ribs is None:
            faces.append((float(drop.length), float(drop.width), d, "outside the drop panel"))
        elif drop is not None and column is context.columns[0]:
            context.notes.append(
                "outside a waffle's solid heads the ribs take the shear as one-way shear "
                "(checked with the strips); no second punching section"
            )
        for index, (s1, s2, depth, what) in enumerate(faces):
            found = _punching_row(
                column, s1, s2, depth, what, fc, combinations, context, phi_punching, source
            )
            if found is None:
                continue
            row, plain_note, vu_max, phi_vc, vu, combination = found
            if index == 0 and (vu_max > phi_vc or context.punching is not None):
                # Integrator glue: shear reinforcement (saengine.design.punching): the studs or
                # stirrups of the slab type checked, else proposed; every combination's demand.
                effective = replace(column, c1=s1, c2=s2)
                row = _punching_with_reinforcement(
                    effective,
                    depth,
                    fc,
                    combinations,
                    context,
                    None if h is None else h + head,
                    fy,
                    cover,
                    top,
                    row,
                )
                if not row["note"].startswith(plain_note):
                    # The column's own Vu of the governing combination, as without reinforcement.
                    row["note"] = (
                        f"Vu = {vu / 1e3:.1f} kN at the column ({combination}); " + row["note"]
                    )
            checks.append(row)
    return checks


def _punching_row(
    column: ColumnJoint,
    c1: float,
    c2: float,
    d: float,
    what: str,
    fc: float,
    combinations: list[str],
    context: SlabContext,
    phi_punching: float,
    source: str,
) -> tuple[dict[str, Any], str, float, float, float, str | None] | None:
    """One punching section round ``column``, as if it were ``c1`` x ``c2`` (its capital, or
    a drop panel's edge), with depth ``d``: (the check, its note, vu, φvc [MPa], Vu [N], the
    governing combination); None when the section lies outside the slab or no force is known."""
    from saengine.design.check import _check

    section = critical_section(column.centre, c1, c2, column.angle, d, context.boundary)
    if not section.sides:
        return None
    beta = max(c1, c2) / min(c1, c2)
    capacity = punching_capacity(fc, d, section.b0, beta, section.alpha_s)
    prestressed = None
    prestress_cite = ""
    if context.precompression is not None:
        from saengine.design import prestress

        found = prestress.clause("punching")
        prestress_cite = f" ({found})" if found else ""
    if context.precompression is not None and section.location == "interior":
        from saengine.design import prestress

        lo, hi = prestress.limits().punchingFpcRange
        if all(lo <= f <= hi for f in context.precompression):
            fpc = sum(context.precompression) / 2
            vc = prestress.punching_vc(fc, d, section.b0, section.alpha_s, fpc)
            if vc is not None:
                prestressed = (vc, fpc)
                capacity = PunchingCapacity(vc, capacity.expressions, capacity.lambda_s)
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
        return None
    vu_max, stress, vu, combination = worst
    area = section.b0 * d
    phi_vc = phi_punching * capacity.vc
    a, b, cc = capacity.expressions
    note = (
        f"{section.location} column, b0 = {section.b0:.0f} mm, d = {d:.0f} mm ({source}), "
        f"Vu = {vu / 1e3:.1f} kN, vu = {vu_max:.3f} MPa (direct {stress.direct:.3f}, "
        f"γv = {stress.gamma_v[0]:.2f}/{stress.gamma_v[1]:.2f}), "
        f"vc = min({a:.3f}, {b:.3f}, {cc:.3f}) MPa, λs = {capacity.lambda_s:.2f}, "
        f"αs = {section.alpha_s:g}, β = {beta:.2f}; shown as v b0 d"
    )
    if prestressed is not None:
        note += (
            f"; prestressed: vc = βp √f'c + 0.3 fpc = {prestressed[0]:.3f} MPa, fpc = "
            f"{prestressed[1]:.2f} MPa, Vp = 0{prestress_cite}"
        )
    elif context.precompression is not None:
        note += f"; prestressed slab: the nonprestressed vc, no prestress term{prestress_cite}"
    if what:
        note = f"{what} ({c1:.0f} x {c2:.0f} mm): " + note
    row = _check(
        f"Punching at {column.id}" + (f" ({what})" if what else ""),
        vu_max * area / 1e3,
        phi_vc * area / 1e3,
        "kN",
        combination,
        note,
        utilisation=vu_max / phi_vc,
    )
    return row, note, vu_max, phi_vc, vu, combination


def _punching_with_reinforcement(
    column: ColumnJoint,
    d: float,
    fc: float,
    combinations: list[str],
    context: SlabContext,
    h: float | None,
    fy: float,
    cover: float,
    top: list[Layer],
    plain: dict[str, Any],
) -> dict[str, Any]:
    from saengine.design import punching

    t = math.radians(column.angle)
    u = np.array([math.cos(t), math.sin(t), 0.0])
    v = np.array([-math.sin(t), math.cos(t), 0.0])
    demands = [
        punching.Demand(max(-float(f[2]), 0.0), float(m @ v), float(m @ u), combinations[c])
        for c, (f, m) in enumerate(zip(column.forces, column.moments, strict=True))
    ]
    given = context.punching
    provided = None
    kind = "studs"
    fyt = None
    if given is not None:
        kind = given.kind
        fyt = given.fyt or (punching.STUD_FY if kind == "studs" else min(fy, 420.0))
        provided = punching.ShearReinforcement(
            kind, float(given.dia), int(given.perLine), int(given.lines),
            float(given.firstLine), float(given.spacing), float(fyt),
        )  # fmt: skip
    elif kind == "stirrups":
        fyt = min(fy, 420.0)

    def run(
        layout: punching.ShearReinforcement | None,
    ) -> punching.PunchingResult | None:
        return punching.slab_punching(
            column.centre,
            column.c1,
            column.c2,
            column.angle,
            d,
            context.boundary,
            demands,
            fc,
            thickness=h,
            kind=layout.kind if layout is not None else kind,
            fyt=layout.fyt if layout is not None else fyt,
            covers=(cover, cover),
            flexural_bar=max(layer.dia for layer in top),
            provided=layout,
        )

    try:
        result = run(provided)
    except (ValueError, ArithmeticError) as error:
        plain["note"] += f"; shear reinforcement not designed: {error}"
        return plain
    if result is None:
        return plain
    name = f"Punching at {column.id}"
    # Re-checkable with another layout, and a fresh proposal where the given one fails (the
    # design mode's one layout per slab type, saengine.design.proposal.punching_layout).
    return punching.recheckable(result.check(name), name, run, fy, provided)


# ──────────────────── coefficient method: slabs on beams (slabs: loadsToBeams) ────────────────────
#
# With the analysis's slabs as "loadsToBeams" (the default) the slabs are not in the analysis
# model: they hand their loads to the beams. Such a slab is designed here from its own loads by
# the methods the default pack's BNBC 2020 Part 6 gives for slabs on beams and walls:
#
# - two-way panels: Sec 6.5.8 (pp. 960-966), the coefficient method of Tables 6.6.8 (negative
#   moments, w = dead + live), 6.6.9 (dead load positive), 6.6.10 (live load positive) and 6.6.11
#   (the shares Wa, Wb of the load in the two directions); M = C w l² with la, lb the clear
#   spans in the short and long directions (notation, p. 880), m = la / lb, nine cases by which
#   edges are continuous (a crosshatched edge "continues across, or is fixed at the support");
#   scope (Sec 6.5.8.2): supported on all four edges by walls or beams with a total depth of at
#   least 3 times the slab's, rectangular, centre-to-centre spans no more than 2 : 1, and
#   αf1 l2 / l1 >= 1;
# - one-way slabs (and panels longer than 2 : 1): Sec 6.1.4.3 (p. 891), the approximate moments
#   and shears of continuous one-way slabs, within its limits (a)-(e).
#
# The numbers are the code pack's ``slabCoefficients`` table.

#: The report's method text of the coefficient design (with :data:`METHOD`).


def _coefficient_method() -> str:
    """``COEFFICIENT_METHOD``: the report's method text of the coefficient design, with the
    clauses of the code pack in force."""
    return (
        "Slabs on beams (analysis slabs 'loadsToBeams', not in the analysis model): designed from "
        f"their own loads. Two-way panels by the coefficient method of {pack_clause('slab', 'twoWayMethod')} "
        "(Tables 6.6.8-6.6.11): Ma,neg = Ca,neg w la², Ma,pos = Ca,dl wD la² + Ca,ll wL la² (and b "
        "with lb), la and lb the clear spans (short, long: centre lines less half the supports' "
        "widths), the case by which edges have a slab beyond them, coefficients interpolated in "
        "m = la/lb; scope checked: rectangular, on beams (total depth >= 3h) or walls on all four "
        "edges, centre-to-centre spans <= 2 : 1, αf l2/l1 >= 1 (beam's own section). Top bars at a "
        f"discontinuous edge for 1/3 of the positive moment (SAEngine practice, not a {short_name()} clause). "
        f"One-way slabs (and two-way types longer than 2 : 1) by {short_clause('slab', 'oneWaySec')}: w ln²/14 (end "
        "span) or /16 (interior span) positive, /9 or /10 at the exterior face of the first "
        "interior support (two, more spans), /11 at other interior faces, /12 for spans <= 3.048 m, "
        "/24 (beam) or /16 (wall) at a discontinuous end, the negative ln the mean of the adjacent "
        "clear spans; outside its limits (a single span, adjacent spans differing by more than "
        "20 %, L > 3D) the bounds w ln²/8 (positive) and w ln,max²/8 (interior support) instead. "
        "Every gravity combination of the project (its dead and live factors) is enveloped. Shear "
        "per metre: Wa w la / 2 at the long edges, Wb w lb / 2 at the short edges (Table 6.6.11), "
        "1.15 w ln / 2 at the first interior support of an end span (Sec 6.1.4.3), against φVc of "
        "the bars in tension there. As,min (Sec 8.1.11.2: 0.0020 below fy 420, 0.0018 x 420/fy, "
        ">= 0.0014; x 1.5 with brick aggregate) in both bottom layers and in a top layer that "
        "resists a negative moment; spacing <= 2h and 450 mm two-way (Sec 6.5.8.6.2, 8.1.6.6), 3h "
        "and 450 mm along a one-way span (8.1.6.5), 5h and 450 mm across it (8.1.6.7)."
    )


def coefficient_table() -> dict[str, Any]:
    """The code pack's ``slabCoefficients`` table as plain data."""
    table = code_context.table("slabCoefficients")
    if hasattr(table, "model_dump"):
        return table.model_dump(by_alias=True)
    return table


@dataclass(frozen=True)
class GravityCombination:
    """A combination's factors on a slab's dead load (D + SD) and live load (L, or Lr on a
    roof)."""

    name: str
    dead: float
    live: float


def gravity_combinations(
    combinations: Sequence[Any], roof: bool = False
) -> list[GravityCombination]:
    """The gravity parts of project combinations (``LoadCombination``: ``D``, ``L``, ``Lr``):
    each one with a positive dead or live factor and no negative one (a combination that
    relieves gravity does not govern a slab on beams). Lateral cases are left out: a slab on
    beams is not in the analysis model and carries no lateral moment."""
    out: list[GravityCombination] = []
    for c in combinations:
        dead = float(getattr(c, "D", 0) or 0)
        live = float(getattr(c, "Lr" if roof else "L", 0) or 0)
        if dead < 0 or live < 0 or (dead <= 0 and live <= 0):
            continue
        out.append(GravityCombination(str(getattr(c, "name", "")), dead, live))
    return out


@dataclass(frozen=True)
class PanelSide:
    """One side of a rectangular panel: its support (beam or wall) and whether a slab is
    beyond it (``neighbour``: its index in the neighbours given, None: a discontinuous edge)."""

    name: str  # "x-", "x+" (the ends of the span along x), "y-", "y+"
    length: float  # mm, centre line
    support: str
    width: float  # mm, of the support
    wall: bool  # a wall ("wall" LineSupport) supports some of it
    beam: EdgeBeam | None  # the most flexible beam along it (None: walls only)
    neighbour: int | None
    beams: tuple[EdgeBeam, ...] = ()  # every beam along it

    @property
    def continuous(self) -> bool:
        return self.neighbour is not None


@dataclass(frozen=True)
class CoefficientPanel:
    """A rectangular slab panel in its axes (mm): its extent (s0, s1 along x, t0, t1 along
    y) and sides."""

    s0: float
    s1: float
    t0: float
    t1: float
    sides: dict[str, PanelSide]

    @property
    def lx(self) -> float:
        return self.s1 - self.s0

    @property
    def ly(self) -> float:
        return self.t1 - self.t0

    def clear(self, direction: str) -> float:
        """The clear span along ``direction`` ("X", "Y"): the centre-line span less half the
        widths of the supports at its two ends."""
        d = direction.lower()
        span = self.lx if d == "x" else self.ly
        return span - (self.sides[f"{d}-"].width + self.sides[f"{d}+"].width) / 2


def _union_length(pieces: list[tuple[float, float]]) -> float:
    total, end = 0.0, -math.inf
    for a, b in sorted(pieces):
        if b <= end:
            continue
        total += b - max(a, end)
        end = b
    return total


_SideGeometry = tuple[int, float, float, float, tuple[float, float]]


def _box_sides(s0: float, s1: float, t0: float, t1: float) -> dict[str, _SideGeometry]:
    """The sides of a box in the slab's axes: (index of the coordinate along it, its position
    across, from, to, outward)."""
    return {
        "x-": (1, s0, t0, t1, (-1.0, 0.0)),
        "x+": (1, s1, t0, t1, (1.0, 0.0)),
        "y-": (0, t0, s0, s1, (0.0, -1.0)),
        "y+": (0, t1, s0, s1, (0.0, 1.0)),
    }


def _on_side(
    frame: PlanFrame,
    side: _SideGeometry,
    start: Sequence[float],
    end: Sequence[float],
    half: float,
    tolerance: float = 5.0,
) -> tuple[float, float] | None:
    """The part (from, to along it, mm) of a side a plan segment within ``half`` of its line
    covers (None: off its line, or less than ``tolerance`` of it)."""
    along, at, lo, hi, _ = side
    p, q = frame.local(start), frame.local(end)
    across = 1 - along
    if abs(p[across] - at) > half + tolerance or abs(q[across] - at) > half + tolerance:
        return None
    a, b = sorted((p[along], q[along]))
    a, b = max(a, lo), min(b, hi)
    return (a, b) if b - a > tolerance else None


@dataclass(frozen=True)
class NeighbourExtent:
    """A slab beyond a side that is not a coefficient panel (``reason``): its extent in the
    slab's axes (its box, centre lines, mm) and its box sides not supported along 95 % of their
    length (``free``; there it may cantilever)."""

    lx: float
    ly: float
    reason: str
    free: frozenset[str]

    def extent(self, direction: str) -> float:
        return self.lx if direction.lower() == "x" else self.ly

    def cantilevers(self, side: str) -> bool:
        """Whether this slab, beyond the side ``side`` ("x-" ...) of a panel, may cantilever
        from their shared support: its far side (the same name) and both its sides across it
        are unsupported. Held on a side across the shared edge it spans to that support
        instead (a slab on three edges does not cantilever)."""
        across = ("y-", "y+") if side[0] == "x" else ("x-", "x+")
        return side in self.free and all(name in self.free for name in across)


def neighbour_extent(
    outline: Sequence[Sequence[float]],
    axes: SlabAxes,
    supports: Sequence[LineSupport],
    reason: str,
) -> NeighbourExtent:
    """The :class:`NeighbourExtent` of a slab outline (plan, mm) that is not a panel."""
    frame = PlanFrame(axes)
    local = [frame.local(p) for p in outline]
    s0, s1 = min(p[0] for p in local), max(p[0] for p in local)
    t0, t1 = min(p[1] for p in local), max(p[1] for p in local)
    free = set()
    for name, side in _box_sides(s0, s1, t0, t1).items():
        pieces = [
            piece
            for support in supports
            if (piece := _on_side(frame, side, support.start, support.end, support.width / 2))
        ]
        if _union_length(pieces) < 0.95 * (side[3] - side[2]):
            free.add(name)
    return NeighbourExtent(s1 - s0, t1 - t0, reason, frozenset(free))


def coefficient_panel(
    boundary: Sequence[Sequence[float]],
    axes: SlabAxes,
    supports: Sequence[LineSupport],
    neighbours: Sequence[Sequence[Sequence[float]]] = (),
    beams: Sequence[EdgeBeam] = (),
) -> CoefficientPanel:
    """The panel a slab outline (plan, mm) makes for the coefficient methods. ``supports``:
    the beams and walls at its level (``LineSupport``; one within half its width of a side's
    line supports it; walls with kind "wall"); ``beams``: the beams with their stiffness and
    depth (``EdgeBeam``; collinear beams along a side count together); ``neighbours``: the
    other slabs' outlines at its level (a side with one beyond it is continuous).

    Raises ValueError (the reason) when the outline is not a rectangle in the slab's axes, a
    side is not supported along at least 95 % of its length, or a part of a side is on neither
    a known beam (``beams``) nor a "wall" support (its scope could not be checked)."""
    frame = PlanFrame(axes)
    local = [frame.local(p) for p in boundary]
    if len(local) < 4:
        raise ValueError("not a rectangular panel (fewer than 4 corners)")
    s0, s1 = min(p[0] for p in local), max(p[0] for p in local)
    t0, t1 = min(p[1] for p in local), max(p[1] for p in local)
    tolerance = 5.0
    box = (s1 - s0) * (t1 - t0)
    on_box = all(
        min(abs(s - s0), abs(s - s1)) <= tolerance or min(abs(t - t0), abs(t - t1)) <= tolerance
        for s, t in local
    )
    if box <= 0 or not on_box or abs(_polygon_area(local) - box) > 0.01 * box:
        raise ValueError(
            f"not a rectangular panel in the slab's axes ({short_clause('slab', 'rectangular')} cover "
            "rectangular panels): analyse the slabs as shells to design it"
        )
    ends = _box_sides(s0, s1, t0, t1)
    sides: dict[str, PanelSide] = {}
    for name, (along, at, lo, hi, out) in ends.items():
        length = hi - lo
        covered: list[tuple[float, float]] = []
        found: list[tuple[float, LineSupport]] = []
        walls: list[tuple[float, float]] = []
        for support in supports:
            piece = _on_side(frame, ends[name], support.start, support.end, support.width / 2)
            if piece is not None:
                covered.append(piece)
                found.append((piece[1] - piece[0], support))
                if support.kind == "wall":
                    walls.append(piece)
        if _union_length(covered) < 0.95 * length:
            raise ValueError(
                f"side {name} is not supported by beams or walls along its length (the "
                f"coefficient methods need supports on all edges, {short_clause('slab', 'supports')}): "
                "analyse the "
                "slabs as shells to design it"
            )
        support = max(found, key=lambda item: item[0])[1]
        # The beams along the side, together (a side may be two beams, e.g. split at a
        # cross-beam); a part not on a known beam must be on a wall.
        on: list[EdgeBeam] = []
        known = list(walls)
        for candidate in beams:
            piece = _on_side(frame, ends[name], candidate.start, candidate.end, candidate.width / 2)
            if piece is not None:
                on.append(candidate)
                known.append(piece)
        if _union_length(known) < 0.95 * length:
            raise ValueError(
                f"side {name} is supported by a beam whose stiffness and depth are not known "
                "(or a support not stated to be a wall): the coefficient methods' scope "
                f"({short_clause('slab', 'scope')}) cannot be checked; analyse the slabs as shells to design it"
            )
        beam = min(on, key=lambda item: item.ei) if on else None
        middle = (lo + hi) / 2
        mid = frame.plan(at, middle) if along == 1 else frame.plan(middle, at)
        outward = frame.ux * out[0] + frame.uy * out[1]
        probe = mid + outward * max(100.0, support.width / 2 + 50.0)
        neighbour = next((k for k, other in enumerate(neighbours) if _inside(probe, other)), None)
        sides[name] = PanelSide(
            name, length, support.id, support.width, bool(walls), beam, neighbour, tuple(on)
        )
    return CoefficientPanel(s0, s1, t0, t1, sides)


def two_way_case(long_continuous: int, short_continuous: int) -> int:
    """The case (1-9) of the default pack's BNBC Tables 6.6.8-6.6.11 for the number of continuous long edges
    (length lb, at the ends of the short span la) and continuous short edges."""
    cases = coefficient_table()["twoWay"]["cases"]
    for case, (n_long, n_short) in cases.items():
        if n_long == long_continuous and n_short == short_continuous:
            return int(case)
    raise ValueError(f"no case for {long_continuous} long and {short_continuous} short edges")


@dataclass(frozen=True)
class TwoWayCoefficients:
    """Coefficients of one case at m = la / lb: negative (None: that direction's edges are
    discontinuous), dead and live load positive, and the load shares Wa, Wb."""

    case: int
    m: float
    neg_a: float | None
    neg_b: float | None
    dead_a: float
    dead_b: float
    live_a: float
    live_b: float
    load_a: float
    load_b: float


def two_way_coefficients(m: float, case: int) -> TwoWayCoefficients:
    """The default pack's BNBC Tables 6.6.8-6.6.11 at ``m`` (0.5 <= m <= 1; linear between the tabulated
    ratios) for ``case``."""
    table = coefficient_table()["twoWay"]
    ratios = [float(r) for r in table["ratios"]]
    if not ratios[0] - 1e-9 <= m <= ratios[-1] + 1e-9:
        raise ValueError(f"m = {m:.3f} is outside the tables ({ratios[0]} to {ratios[-1]})")
    m = min(max(m, ratios[0]), ratios[-1])
    k = min(max(i for i, r in enumerate(ratios) if r <= m + 1e-12), len(ratios) - 2)
    f = (m - ratios[k]) / (ratios[k + 1] - ratios[k])
    column = case - 1

    def value(name: str) -> float | None:
        lo, hi = table[name][k][column], table[name][k + 1][column]
        if lo is None or hi is None:
            return None
        return float(lo) + (float(hi) - float(lo)) * f

    def given(name: str) -> float:
        result = value(name)
        if result is None:
            raise ValueError(f"no {name} coefficient for case {case}")
        return result

    return TwoWayCoefficients(
        case,
        m,
        value("negativeA"),
        value("negativeB"),
        given("deadA"),
        given("deadB"),
        given("liveA"),
        given("liveB"),
        given("loadA"),
        given("loadB"),
    )


@dataclass(frozen=True)
class OneWayEnd:
    """One end of a one-way span: its negative moment M = w ln² / ``divisor`` with the ``ln``
    it applies to [mm], the shear V = ``shear`` w ln / 2, and what it is."""

    side: str
    divisor: float
    ln: float
    shear: float
    what: str


@dataclass(frozen=True)
class OneWaySpan:
    """The coefficients of a one-way span (default pack BNBC 6.1.4.3): the positive moment w ln² /
    ``positive``, the two ends, and whether its limits held (else the bounds w l²/8)."""

    direction: str  # "X" or "Y"
    ln: float  # mm, clear span
    positive: float
    ends: tuple[OneWayEnd, OneWayEnd]
    within_limits: bool
    notes: tuple[str, ...]


def one_way_span(
    panel: CoefficientPanel,
    direction: str,
    neighbours: Sequence[CoefficientPanel | NeighbourExtent | None],
    dead: float,
    live: float,
) -> OneWaySpan:
    """The default pack's BNBC 6.1.4.3 coefficients of ``panel`` spanning along ``direction``. ``neighbours``:
    the other slabs (by the sides' neighbour index): their panels, or for one that is not a
    panel its :class:`NeighbourExtent` (the limits are then taken as not met, with its extent as
    its span, and where it may cantilever beyond that support the larger of the bound and w
    l²/2 over its extent); ``dead``, ``live``: the service loads (any one unit, for limit (d),
    L <= 3D).

    Limits (a) two or more spans, (b) adjacent spans within 20 % and (d) are checked; (c)
    uniform load and (e) prismatic hold for a slab of one thickness under area loads. Outside
    them the bounds are used: w ln²/8 positive (a simple span) and w ln,max²/8 at an interior
    support (a propped span's fixed end), with the exterior ends as within the limits.

    Raises ValueError when a continuous side's neighbour is not given (None)."""
    table = coefficient_table()["oneWay"]
    positive_of, negative_of = table["positive"], table["negative"]
    short = float(table["shortSpanMax"])
    d = direction.lower()
    ln = panel.clear(direction)
    sides = (panel.sides[f"{d}-"], panel.sides[f"{d}+"])
    continuous = [s.continuous for s in sides]
    notes: list[str] = []
    limits = True
    if not any(continuous):
        limits = False
        notes.append(f"a single span: {short_clause('slab', 'oneWay')} (a) needs two or more spans")
    if dead > 0 and live > float(table["liveToDeadMax"]) * dead:
        limits = False
        notes.append(
            f"live load {live:g} > 3 x dead load {dead:g} ({short_clause('slab', 'oneWay')} (d))"
        )
    others: dict[str, float] = {}
    cantilevers: dict[str, float] = {}
    for side in sides:
        if not side.continuous:
            continue
        other = neighbours[side.neighbour] if side.neighbour is not None else None
        if other is None:
            raise ValueError(f"the slab beyond {side.name} is not known")
        if isinstance(other, NeighbourExtent):
            limits = False
            other_ln = other.extent(direction)
            notes.append(
                f"the slab beyond {side.name} is not a coefficient panel ({other.reason}): "
                f"{short_clause('slab', 'oneWay')} taken as not met, its span taken as its extent {other_ln:.0f} mm"
            )
            if other.cantilevers(side.name):
                cantilevers[side.name] = other_ln
        else:
            other_ln = other.clear(direction)
        others[side.name] = other_ln
        if max(ln, other_ln) > float(table["spanRatioMax"]) * min(ln, other_ln):
            limits = False
            notes.append(
                f"spans {ln:.0f} and {other_ln:.0f} mm at {side.name} differ by more than 20 % "
                f"({short_clause('slab', 'oneWay')} (b))"
            )
    end_span = sum(continuous) == 1
    ends: list[OneWayEnd] = []
    for side in sides:
        if not side.continuous:
            divisor = float(negative_of["exteriorColumn" if side.wall else "exteriorSpandrel"])
            what = "discontinuous end on a " + ("wall" if side.wall else "spandrel beam")
            if ln <= short and limits:
                divisor, what = float(negative_of["shortSpans"]), what + f", span <= {short:g} mm"
            ends.append(OneWayEnd(side.name, divisor, ln, 1.0, what))
            continue
        other_ln = others[side.name]
        mean = (ln + other_ln) / 2
        shear = 1.0
        if end_span:
            other = neighbours[side.neighbour] if side.neighbour is not None else None
            far = None
            if isinstance(other, CoefficientPanel):
                far = other.sides[side.name]  # its side on the far end, the same way
            two = far is not None and not far.continuous
            key = "firstInteriorTwoSpans" if two else "firstInteriorMoreSpans"
            what = "exterior face of the first interior support, " + (
                "two spans" if two else "more than two spans"
            )
            shear = float(table["shearFirstInterior"])
        else:
            key, what = "otherInterior", "interior support"
        divisor = float(negative_of[key])
        if ln <= short and other_ln <= short:
            divisor, what = float(negative_of["shortSpans"]), what + f", spans <= {short:g} mm"
        if not limits:
            divisor, mean = 8.0, max(ln, other_ln)
            what += "; outside the limits: w ln,max²/8"
        lc = cantilevers.get(side.name)
        if lc is not None and lc**2 / 2 > mean**2 / divisor:
            divisor, mean = 2.0, lc
            what += "; the slab beyond may cantilever (a side of it unsupported): w l²/2 over it"
        ends.append(OneWayEnd(side.name, divisor, mean, shear, what))
    if not limits:
        positive = 8.0
        notes.append(
            f"outside {short_clause('slab', 'oneWay')}: bounds w ln²/8 used (analyse as shells "
            "for economy)"
        )
    else:
        positive = float(positive_of["interior" if all(continuous) else "endIntegral"])
    return OneWaySpan(direction, ln, positive, (ends[0], ends[1]), limits, tuple(notes))


@dataclass
class CoefficientDesign:
    """A slab on beams designed by the coefficient methods (:func:`coefficient_design`).

    ``method``: "twoWay" (default pack BNBC 6.5.8) or "oneWay" (6.1.4.3); ``envelope``: the design moment of
    each layer [N·m/m] and ``shear`` the one-way shear each layer's ρ resists [N/m], as (value,
    combination, where) like :attr:`SlabContext.shear`; ``span``: the one-way span direction;
    ``side_shares``: the load per metre [kN/m] each side hands to its support under 1 kN/m²
    (Table 6.6.11 shares, or half the one-way span), for reference."""

    method: str
    envelope: dict[str, tuple[float, str | None, str]]
    shear: dict[str, tuple[float, str | None, str]]
    span: str | None
    checks: list[dict[str, Any]]
    notes: list[str]
    case: int | None = None
    m: float | None = None
    side_shares: dict[str, float] = field(default_factory=dict)


def coefficient_design(
    system: str,
    h: float,
    reinforcement: PlanarReinforcement,
    fc: float,
    fy: float,
    es: float,
    dead: float,
    live: float,
    combinations: Sequence[GravityCombination],
    context: SlabContext,
    neighbours: Sequence[Sequence[Sequence[float]]] = (),
    beams: Sequence[EdgeBeam] = (),
    ec: float | None = None,
    brick_aggregate: bool | None = None,
) -> CoefficientDesign:
    """Design a slab on beams by the default pack's (BNBC) coefficient methods (:data:`COEFFICIENT_METHOD`).

    ``dead``, ``live``: its service loads [kN/m²] (self-weight + finishes + partitions; live,
    or roof live); ``combinations``: their factors (:func:`gravity_combinations`); ``context``:
    its outline, axes and supports (and its minimum thickness, reported as by
    :func:`slab_checks`; its ``shear`` and ``notes`` are filled); ``neighbours``: the other
    slabs' outlines at its level; ``beams``: the beams at its level with their stiffness and
    depth; ``ec``: the slab concrete's E [MPa] for αf (None: not checked);
    ``brick_aggregate``: whether the concrete has brick aggregate (None: the project's
    Construction > Concrete aggregate, B21).

    Raises ValueError (the reason) for a flat slab, a panel the methods do not cover, or no
    combination."""

    if system == "flat":
        raise ValueError("a flat slab is designed from shells (analysis slabs: shells)")
    if not combinations:
        raise ValueError("no gravity load combination")
    table = coefficient_table()
    panel = coefficient_panel(context.boundary, context.axes, context.supports, neighbours, beams)
    # The panels beyond the sides (for the one-way spans next to this one).
    others: list[CoefficientPanel | NeighbourExtent | None] = [None] * len(neighbours)
    for side in panel.sides.values():
        if side.neighbour is not None and others[side.neighbour] is None:
            outline = neighbours[side.neighbour]
            try:
                others[side.neighbour] = coefficient_panel(
                    outline, context.axes, context.supports, neighbours, beams
                )
            except ValueError as error:
                others[side.neighbour] = neighbour_extent(
                    outline, context.axes, context.supports, str(error).split(":")[0]
                )
    # Sides with a slab beyond that is not a panel (a balcony, a partly supported or irregular
    # slab): its moment at the shared support is not known.
    unknown = {
        name: other
        for name, side in panel.sides.items()
        if side.neighbour is not None
        and isinstance(other := others[side.neighbour], NeighbourExtent)
    }
    notes: list[str] = []
    lx, ly = panel.clear("X"), panel.clear("Y")
    if min(lx, ly) <= 0:
        raise ValueError("the supports leave no clear span")
    limits = table["twoWayLimits"]
    method = "oneWay" if system == "oneWay" else "twoWay"
    # The same test (and tolerance at exactly 2 : 1) as the slab's loads on its beams.
    from saengine.fem.slab_load_shapes import spans_one_way

    if method == "twoWay" and spans_one_way(
        max(panel.lx, panel.ly), min(panel.lx, panel.ly), float(limits["maxSpanRatio"])
    ):
        method = "oneWay"
        notes.append(
            f"centre-to-centre spans {max(panel.lx, panel.ly):.0f} x "
            f"{min(panel.lx, panel.ly):.0f} mm, more than 2 : 1 ({short_clause('slab', 'aspect')}): designed as "
            "a one-way slab"
        )
    if method == "twoWay":
        _two_way_scope(panel, h, ec, limits)

    w_d = [c.dead * dead * 1e3 for c in combinations]  # N/m²
    w_l = [c.live * live * 1e3 for c in combinations]
    w = [a + b for a, b in zip(w_d, w_l, strict=True)]
    envelope: dict[str, tuple[float, str | None, str]] = {n: (0.0, None, "") for n in LAYERS}
    demand_shear: dict[str, tuple[float, str | None, str]] = {}
    share = float(table["discontinuousEdgeShare"])

    def take(name: str, values: list[float], where: str) -> None:
        k = int(max(range(len(values)), key=lambda i: values[i]))
        if values[k] > envelope[name][0]:
            envelope[name] = (float(values[k]), combinations[k].name, where)

    def take_shear(name: str, values: list[float], where: str) -> None:
        k = int(max(range(len(values)), key=lambda i: values[i]))
        if name not in demand_shear or values[k] > demand_shear[name][0]:
            demand_shear[name] = (float(values[k]), combinations[k].name, where)

    side_shares: dict[str, float] = {}
    case: int | None = None
    m: float | None = None
    span: str | None = None
    if method == "twoWay":
        a = "X" if lx <= ly else "Y"
        b = "Y" if a == "X" else "X"
        la, lb = (lx, ly) if a == "X" else (ly, lx)
        long_sides = (panel.sides[f"{a.lower()}-"], panel.sides[f"{a.lower()}+"])
        short_sides = (panel.sides[f"{b.lower()}-"], panel.sides[f"{b.lower()}+"])
        # A side with an unknown slab beyond: discontinuous for the case (the larger positive
        # moments), and its top bars also for the negative coefficient as if continuous and,
        # where that slab may cantilever, w l²/2 over its extent.
        known = {
            name: side.continuous and name not in unknown for name, side in panel.sides.items()
        }
        case = two_way_case(
            sum(known[s.name] for s in long_sides), sum(known[s.name] for s in short_sides)
        )
        m = la / lb
        if m < 0.5:
            notes.append(f"clear spans la/lb = {m:.2f} below 0.5: the tables' 0.5 row is used")
            m = 0.5
        c = two_way_coefficients(m, case)
        c_as_continuous = c
        if unknown:
            c_as_continuous = two_way_coefficients(
                m,
                two_way_case(
                    sum(s.continuous for s in long_sides), sum(s.continuous for s in short_sides)
                ),
            )
            for name, other in unknown.items():
                notes.append(
                    f"the slab beyond {name} is not a coefficient panel ({other.reason}): that "
                    "edge taken as discontinuous for the case, its top bars also as continuous"
                    + (" and for the cantilever beyond" if other.cantilevers(name) else "")
                )
        geometry = f"case {case}, la = {la:.0f} mm ({a}), lb = {lb:.0f} mm, m = {m:.3f}"
        for direction, label, length, dl, ll, neg, load, sides_of, neg_cont in (
            (a, "a", la / 1e3, c.dead_a, c.live_a, c.neg_a, c.load_a, long_sides,
             c_as_continuous.neg_a),
            (b, "b", lb / 1e3, c.dead_b, c.live_b, c.neg_b, c.load_b, short_sides,
             c_as_continuous.neg_b),
        ):  # fmt: skip
            positive = [(dl * wd + ll * wl) * length**2 for wd, wl in zip(w_d, w_l, strict=True)]
            take(
                f"bottom{direction}",
                positive,
                f"M{label},pos = C{label},dl wD l{label}² + C{label},ll wL l{label}² (C = "
                f"{dl:.4f}, {ll:.4f}); {geometry}",
            )
            if neg is not None:
                edges = ", ".join(s.name for s in sides_of if known[s.name])
                take(
                    f"top{direction}",
                    [neg * x * length**2 for x in w],
                    f"M{label},neg = C{label},neg w l{label}² (C = {neg:.4f}) at {edges}; "
                    f"{geometry}",
                )
            if not all(known[s.name] for s in sides_of):
                edges = ", ".join(s.name for s in sides_of if not known[s.name])
                take(
                    f"top{direction}",
                    [share * p for p in positive],
                    f"discontinuous edge {edges}: {share:.2f} x M{label},pos (SAEngine practice, "
                    f"not a {short_name()} clause); {geometry}",
                )
            for s in sides_of:
                other = unknown.get(s.name)
                if other is not None:
                    if neg_cont is not None:
                        take(
                            f"top{direction}",
                            [neg_cont * x * length**2 for x in w],
                            f"M{label},neg = C{label},neg w l{label}² (C = {neg_cont:.4f}) at "
                            f"{s.name}, taken as continuous (the slab beyond is not a "
                            f"panel); {geometry}",
                        )
                    if other.cantilevers(s.name):
                        lc = other.extent(direction) / 1e3
                        take(
                            f"top{direction}",
                            [x * lc**2 / 2 for x in w],
                            f"w l²/2 at {s.name}: the slab beyond may cantilever (a side of it "
                            f"unsupported), l = {lc * 1e3:.0f} mm; {geometry}",
                        )
                side_shares[s.name] = load * length / 2
                take_shear(
                    f"{'top' if s.continuous else 'bottom'}{direction}",
                    [load * x * length / 2 for x in w],
                    f"V = W{label} w l{label} / 2 at {s.name} (W{label} = {load:.2f}, Table "
                    f"6.6.11); {geometry}",
                )
    else:
        direction = "X" if lx <= ly else "Y"
        span = direction
        result = one_way_span(panel, direction, others, dead, live)
        notes += list(result.notes)
        length = result.ln / 1e3
        geometry = f"one-way along {direction}, ln = {result.ln:.0f} mm"
        take(
            f"bottom{direction}",
            [x * length**2 / result.positive for x in w],
            f"w ln²/{result.positive:g} ({short_clause('slab', 'oneWay')}); {geometry}",
        )
        for end in result.ends:
            take(
                f"top{direction}",
                [x * (end.ln / 1e3) ** 2 / end.divisor for x in w],
                f"w ln²/{end.divisor:g} at {end.side} ({end.what}), ln = {end.ln:.0f} mm; "
                f"{geometry}",
            )
            continuous = panel.sides[end.side].continuous
            take_shear(
                f"{'top' if continuous else 'bottom'}{direction}",
                [end.shear * x * length / 2 for x in w],
                f"V = {end.shear:g} w ln / 2 at {end.side}; {geometry}",
            )
            side_shares[end.side] = end.shear * length / 2
        across = "y" if direction == "X" else "x"
        side_shares[f"{across}-"] = side_shares[f"{across}+"] = 0.0

    checks = _coefficient_checks(
        method, span, h, reinforcement, fc, fy, es, envelope, demand_shear, context,
        brick_aggregate, table["maxSpacing"],
    )  # fmt: skip
    if method == "twoWay":
        checks += _corner_checks(panel, h, ec, reinforcement, fc, fy, es, envelope)
    context.notes += notes
    return CoefficientDesign(
        method, envelope, dict(context.shear), span, checks, notes, case, m, side_shares
    )


def _corner_checks(
    panel: CoefficientPanel,
    h: float,
    ec: float | None,
    reinforcement: PlanarReinforcement,
    fc: float,
    fy: float,
    es: float,
    envelope: dict[str, tuple[float, str | None, str]],
) -> list[dict[str, Any]]:
    """B33: corner reinforcement of a two-way panel at an exterior corner, where two
    discontinuous sides meet that are on walls or on edge beams with αf above the pack's
    ``slabMethods.corner.alphaMin`` (:func:`saengine.design.slab_frames.corner_rows`)."""
    from saengine.design import slab_frames

    table = slab_frames.rules()
    corner = getattr(table, "corner", None) if table is not None else None
    if corner is None:
        return []

    def stiff(name: str) -> bool:
        side = panel.sides[name]
        if side.neighbour is not None:
            return False  # continuous: not an exterior edge
        if side.beam is None:
            return side.wall
        if not ec:
            return False
        # The slab beside an edge beam: half the panel across it (as _two_way_scope).
        width = (panel.lx if name[0] == "x" else panel.ly) / 2
        return side.beam.ei / (ec * width * h**3 / 12) > float(corner.alphaMin)

    exterior = [(a, b) for a in ("x-", "x+") for b in ("y-", "y+") if stiff(a) and stiff(b)]
    if not exterior:
        return []
    rows = slab_frames.corner_rows(
        envelope, layers_of(reinforcement, h), fc, fy, es, h, max(panel.lx, panel.ly)
    )
    corners = ", ".join(f"{a}/{b}" for a, b in exterior)
    for row in rows:
        row["note"] += f"; exterior corner(s) {corners}"
    return rows


def _two_way_scope(
    panel: CoefficientPanel, h: float, ec: float | None, limits: dict[str, Any]
) -> None:
    """The default pack's BNBC 6.5.8.2.1 (beams at least 3h deep; walls pass) and 6.5.8.2.3 (αf1 l2/l1 >= 1,
    αf of the beam's own section over the slab width to the panels' centre lines, the mean of
    the two sides along l1, each by its most flexible beam; a side on walls only counts as
    infinitely stiff). Raises ValueError."""
    for side in panel.sides.values():
        for beam in side.beams or ((side.beam,) if side.beam is not None else ()):
            if not beam.depth or beam.depth >= float(limits["beamDepthRatio"]) * h:
                continue
            raise ValueError(
                f"a beam at {side.name} ({side.support}) is {beam.depth:.0f} mm deep, less "
                f"than 3 x {h:g} mm ({short_clause('slab', 'supports')}): analyse the slabs as shells to design it"
            )
    if not ec:
        return
    for direction in ("x", "y"):
        across = "y" if direction == "x" else "x"
        l1 = panel.lx if direction == "x" else panel.ly
        l2 = panel.ly if direction == "x" else panel.lx
        alphas = []
        for name in (f"{across}-", f"{across}+"):  # the sides running along l1
            side = panel.sides[name]
            if side.beam is None:
                alphas.append(math.inf)
                continue
            width = l2 / 2 * (2 if side.continuous else 1)
            alphas.append(side.beam.ei / (ec * width * h**3 / 12))
        alpha = sum(alphas) / len(alphas)
        if alpha * l2 / l1 < float(limits["alphaRatioMin"]):
            raise ValueError(
                f"αf l2/l1 = {alpha * l2 / l1:.2f} < 1 for the beams along {direction.upper()} "
                f"({short_clause('slab', 'stiffness')}): analyse the slabs as shells to design it"
            )


def _coefficient_checks(
    method: str,
    span: str | None,
    h: float,
    reinforcement: PlanarReinforcement,
    fc: float,
    fy: float,
    es: float,
    envelope: dict[str, tuple[float, str | None, str]],
    demand_shear: dict[str, tuple[float, str | None, str]],
    context: SlabContext,
    brick_aggregate: bool | None,
    spacing: dict[str, Any],
    source: str | None = None,
) -> list[dict[str, Any]]:
    """The checks of a coefficient design, in the shape of :func:`slab_checks`'s. ``source``:
    the method named in the flexure rows (None: the coefficient methods)."""
    from saengine.design.check import _check

    layers = layers_of(reinforcement, h)
    capacities = {
        name: (layer_capacity(layer.area, layer.d, fc, fy, es) if layer is not None else None)
        for name, layer in layers.items()
    }
    checks: list[dict[str, Any]] = []
    method_name = source
    source = short_clause("slab", "twoWay" if method == "twoWay" else "oneWay")
    for name in LAYERS:
        face, direction = name[:-1], name[-1]
        demand, combination, where = envelope[name]
        capacity = capacities[name]
        label = f"Flexure {face} {direction} ({method_name or source + ' coefficients'})"
        if capacity is None:
            if demand <= NO_DEMAND:
                continue
            checks.append(
                _check(
                    label,
                    demand / 1e3,
                    0.0,
                    "kN·m/m",
                    combination,
                    f"no {face} {direction} bars for {demand / 1e3:.2f} kN·m/m; {where}",
                )
            )
            continue
        layer = layers[name]
        assert layer is not None
        note = (
            f"{_bars(layer)}: As = {capacity.area:.0f} mm²/m, d = {capacity.d:.0f} mm, "
            f"φ = {capacity.phi:.2f}; {where}"
        )
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
    # One-way shear: resisted with the ρ of the layer in tension at that edge (else the other
    # face's layer of the same direction).
    context.shear = {}
    worst_shear: tuple[float, float, float, str | None, str] | None = None
    for name, (vu, combination, where) in demand_shear.items():
        direction = name[-1]
        other = f"{'bottom' if name.startswith('top') else 'top'}{direction}"
        resisting = next((n for n in (name, other) if capacities[n] is not None), None)
        if resisting is None:
            continue
        capacity = capacities[resisting]
        assert capacity is not None
        phi_vc = one_way_shear(capacity.area / (1000 * capacity.d), capacity.d, fc)[0]
        seen = context.shear.get(resisting)
        if seen is None or vu > seen[0]:
            context.shear[resisting] = (vu, combination, where)
        ratio = vu / phi_vc if phi_vc > 0 else math.inf
        if worst_shear is None or ratio > worst_shear[0]:
            worst_shear = (ratio, vu, phi_vc, combination, f"ρ of {resisting}; {where}")
    if worst_shear is not None:
        ratio, vu, phi_vc, combination, where = worst_shear
        checks.append(
            _check(
                "One-way shear",
                vu / 1e3,
                phi_vc / 1e3,
                "kN/m",
                combination,
                f"φVc = 0.75 · 0.66 λs ρ^(1/3) √f'c b d (ACI 22.5.5.1 (c), no shear bars); {where}",
                utilisation=ratio,
            )
        )
    if present:
        checks.append(_coefficient_min_steel(h, fy, capacities, envelope, brick_aggregate, span))
        checks.append(_coefficient_spacing(h, layers, method, span, spacing))
    if context.thickness is not None:
        t = context.thickness
        checks.append(
            _check(f"Min. thickness (Table {t.table})", t.required, h, "mm", None, t.note, True)
        )
    return checks


def _coefficient_min_steel(
    h: float,
    fy: float,
    capacities: dict[str, LayerCapacity | None],
    envelope: dict[str, tuple[float, str | None, str]],
    brick_aggregate: bool | None,
    span: str | None,
) -> dict[str, Any]:
    """As,min of the default pack's BNBC 8.1.11.2 (by 6.5.8.6.1 two-way, 6.3.5.4 and 8.1.11.1 one-way) in both
    bottom layers (the span directions; across a one-way span the shrinkage and temperature
    bars) and in a top layer that resists a negative moment; x 1.5 with brick aggregate
    (8.1.11.2 (b))."""
    from saengine.design.check import _check
    from saengine.design.rc_detailing import shrinkage_ratio

    # None: the project's aggregate; True/False: brick aggregate or not (B21).
    aggregate = None if brick_aggregate is None else ("brick" if brick_aggregate else "")
    ratio, how = shrinkage_ratio(fy, aggregate)
    as_min = ratio * 1000 * h
    found: list[tuple[float, float, float, str]] = []
    for name in LAYERS:
        if not name.startswith("bottom") and envelope[name][0] <= NO_DEMAND:
            continue
        capacity = capacities[name]
        provided = capacity.area if capacity is not None else 0.0
        utilisation = as_min / provided if provided > 0 else math.inf
        found.append((utilisation, as_min, provided, name + ("" if capacity else " (no bars)")))
    utilisation, required, provided, what = max(found, key=lambda item: item[0])
    note = f"As,min = {ratio:.4f} Ag = {as_min:.0f} mm²/m ({how}); governing: {what}"
    if span is not None:
        note += f"; one-way slab spanning {span}" + _integrity_note()
    return _check(
        f"Min. reinforcement ({short_clause('slab', 'minimum')})",
        required,
        provided,
        "mm²/m",
        None,
        note,
        utilisation=utilisation,
    )


def _coefficient_spacing(
    h: float, layers: dict[str, Layer | None], method: str, span: str | None, limits: dict
) -> dict[str, Any]:
    """Largest bar spacing: two-way min(2h, 450 mm) (default pack BNBC 6.5.8.6.2, 8.1.6.6); one-way
    min(3h, 450 mm) along the span (8.1.6.5), min(5h, 450 mm) across it (8.1.6.7)."""
    from saengine.design.check import _check

    worst: tuple[float, Layer, float, str] | None = None
    for layer in layers.values():
        if layer is None:
            continue
        if method == "twoWay":
            key, clause = "twoWay", "6.5.8.6.2, 8.1.6.6"
        elif layer.name[-1] == span:
            key, clause = "oneWay", "8.1.6.5"
        else:
            key, clause = "temperature", "8.1.6.7"
        times, most = (float(v) for v in limits[key])
        limit = min(times * h, most)
        ratio = layer.spacing / limit
        if worst is None or ratio > worst[0]:
            worst = (ratio, layer, limit, f"{short_name()} {clause}: min({times:g}h, {most:g} mm)")
    assert worst is not None
    _, layer, limit, clause = worst
    return _check(
        "Max. spacing",
        layer.spacing,
        limit,
        "mm",
        None,
        f"{layer.name} at {layer.spacing:.0f} mm; {clause}",
    )


def _integrity_note() -> str:
    """B21: the continuous bottom bar of a one-way slab (the code pack's integrity clause): a
    slab type's bottom mesh runs the whole slab, so the As,min check's bottom bars in the span
    direction are continuous."""
    from saengine.design.rc_detailing import clause

    where = clause("detailing", "integritySlab")
    return f"; the bottom bars run the whole slab, continuous ({where})" if where else ""


def __getattr__(name: str) -> str:
    # The coefficient method text names the clauses of the pack in force: built when read.
    if name == "COEFFICIENT_METHOD":
        return _coefficient_method()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
