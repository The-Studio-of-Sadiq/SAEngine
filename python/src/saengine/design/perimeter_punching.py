"""Punching shear on a control perimeter at a distance from the loaded area (method
``controlPerimeter`` of the pack's ``concreteMethods.punching``).

Units: mm, MPa, N. Rectangular columns c1 × c2 (c1 along the eccentricity) or circular ones.

- u0 is the column's perimeter (interior; edge and corner columns: the perimeter less the
  free sides, with the limits of the code taken as the column faces: SAEngine practice), u1
  the basic control perimeter at ``perimeterDistance`` d with rounded corners;
- vEd = β VEd / (ui d) with β of the column's position (the pack's simplified values);
- vRd,c = CRd,c k (100 ρl fck)^(1/3) + k1 σcp >= vmin + k1 σcp, ρl = √(ρly ρlz) at most
  ``rhoLMax``, d = (dy + dz)/2;
- vRd,max = ``vmaxShare`` ν fcd at u0 (ν of the pack's shear method, ``shear.nuCoefficient``
  and ``nuDivisor``);
- with punching reinforcement: vRd,cs = ``concreteShare`` vRd,c + coefficient (d / sr) Asw
  fywd,ef sin α / (u1 d), fywd,ef = base + slope d <= fywd; the outermost perimeter
  uout,ef = β VEd / (vRd,c d) and the reinforcement reaches ``outerDistance`` d inside it.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context
from saengine.design import design_strength, strut_shear


def rules() -> Any | None:
    pack = code_context.current()
    if not pack.has("concreteMethods"):
        return None
    from saengine.codes.method_tables import chosen  # C8: another method may hold the group

    return chosen(pack.table("concreteMethods"), "punching", "controlPerimeter")


def perimeter(c1: float, c2: float | None, distance: float, position: str = "interior") -> float:
    """The perimeter [mm] at ``distance`` from a rectangular (c2 given) or circular (diameter
    c1) column; edge columns lose one side (c2 side, the free edge), corner columns two."""
    if c2 is None:
        return math.pi * (c1 + 2 * distance)
    if position == "edge":
        return 2 * c1 + c2 + math.pi * distance
    if position == "corner":
        return c1 + c2 + math.pi * distance / 2
    return 2 * (c1 + c2) + 2 * math.pi * distance


@dataclass(frozen=True)
class Punching:
    v_ed: float  # MPa at u1
    v_ed0: float  # MPa at u0
    v_rdc: float
    v_rdmax: float
    v_rdcs: float | None
    u0: float
    u1: float
    beta: float
    u_out: float  # mm, the perimeter where no reinforcement is needed

    @property
    def utilisation(self) -> float:
        resist = self.v_rdcs if self.v_rdcs is not None else self.v_rdc
        return max(self.v_ed / resist, self.v_ed0 / self.v_rdmax)


def punching(
    ved: float,
    d: float,
    c1: float,
    c2: float | None,
    fck: float,
    rho_l: float,
    position: str = "interior",
    sigma_cp: float = 0.0,
    asw: float | None = None,
    sr: float | None = None,
    fywk: float | None = None,
    sin_alpha: float = 1.0,
) -> Punching:
    """The punching check of a column (see the module notes); ``asw`` the reinforcement on one
    perimeter around the column, ``sr`` the radial spacing of its perimeters."""
    r = rules()
    u = design_strength.rules()
    beta = r.beta[position]
    u0 = perimeter(c1, c2, 0.0, position)
    u1 = perimeter(c1, c2, r.perimeterDistance * d, position)
    k = min(r.sizeMax, 1 + math.sqrt(r.sizeReference / d))
    crdc = r.crdcCoefficient / u.gammaC
    vmin = r.vminCoefficient * k**1.5 * math.sqrt(fck)
    v_rdc = max(crdc * k * (100 * min(rho_l, r.rhoLMax) * fck) ** (1 / 3), vmin) + r.k1 * sigma_cp
    f_cd = design_strength.fcd(fck, u)
    nu = strut_shear.nu1(fck, strut_shear.rules())  # ν of the pack's shear method
    v_rdmax = r.vmaxShare * nu * f_cd
    v_rdcs = None
    if asw and sr and fywk:
        fywd_ef = min(r.fywdEfBase + r.fywdEfSlope * d, design_strength.fyd(fywk, u))
        v_rdcs = r.concreteShare * v_rdc + r.reinforcementCoefficient * (
            d / sr
        ) * asw * fywd_ef * sin_alpha / (u1 * d)
    v_ed = beta * ved / (u1 * d)
    v_ed0 = beta * ved / (u0 * d)
    u_out = beta * ved / (v_rdc * d)
    return Punching(v_ed, v_ed0, v_rdc, v_rdmax, v_rdcs, u0, u1, beta, u_out)


# ───────────── Alpha 9 C5c: footings and pile caps (method ``reducedPerimeter``) ─────────────


def footing_rules() -> Any | None:
    """The pack's ``footingPunching`` group when it is the method ``reducedPerimeter`` (and
    the pack designs concrete with partial factors and the control perimeter punching); None
    otherwise."""
    from saengine.design import method_selection

    if rules() is None or not method_selection.uses("footingPunching", "reducedPerimeter"):
        return None
    return code_context.table("concreteMethods").footingPunching


def moment_k(c1: float, c2: float) -> float:
    """k of the moment transferred by shear for c1 / c2, linear between the pack's points."""
    points = sorted(footing_rules().momentK)
    ratio = c1 / c2 if c2 > 0 else 1.0
    if ratio <= points[0][0]:
        return points[0][1]
    for (r0, k0), (r1, k1) in itertools.pairwise(points):
        if ratio <= r1:
            return k0 + (k1 - k0) * (ratio - r0) / (r1 - r0)
    return points[-1][1]


@dataclass(frozen=True)
class FootingPunching:
    a: float  # mm, the critical perimeter's distance from the column face
    u: float  # mm
    v_ed: float  # MPa at u(a)
    v_rd: float  # MPa at u(a)
    v_ed_red: float  # N, VEd less the reaction inside
    beta: float
    v_ed0: float  # MPa at u0
    v_rdmax: float

    @property
    def utilisation(self) -> float:
        own = self.v_ed / self.v_rd if self.v_rd > 0 else math.inf
        return max(own, self.v_ed0 / self.v_rdmax)


def footing_area(c1: float, c2: float, a: float) -> float:
    """The area [mm²] within the rounded perimeter at ``a`` from a c1 × c2 column."""
    return c1 * c2 + 2 * a * (c1 + c2) + math.pi * a * a


def footing_punching(
    ved: float,
    d: float,
    c1: float,
    c2: float,
    fck: float,
    rho_l: float,
    reaction_inside: Any,
    m1: float = 0.0,
    m2: float = 0.0,
    reach: float | None = None,
) -> FootingPunching | None:
    """Punching of a column base: the perimeters u(a) = 2 (c1 + c2) + 2 π a for a up to
    ``searchDistance`` d (and ``reach``, the room to the footing's edge), ``reaction_inside(a)``
    [N] the net upward pressure on the area within u(a); vEd = VEd,red / (u d) (1 + k1 M1 u /
    (VEd,red W1) + k2 M2 u / (VEd,red W2)), W of the perimeter at a, against vRd = vRd,c 2d / a
    (at least vmin 2d / a); and β VEd / (u0 d) against vRd,max at the column face. The worst
    perimeter; None when none fits. M1 [N·mm] bends about the axis across c1."""
    r = footing_rules()
    p = rules()
    u_rules = design_strength.rules()
    k = min(p.sizeMax, 1 + math.sqrt(p.sizeReference / d))
    crdc = p.crdcCoefficient / u_rules.gammaC
    vmin = p.vminCoefficient * k**1.5 * math.sqrt(fck)
    v_rdc = max(crdc * k * (100 * min(rho_l, p.rhoLMax) * fck) ** (1 / 3), vmin)
    nu = strut_shear.nu1(fck, strut_shear.rules())
    v_rdmax = p.vmaxShare * nu * design_strength.fcd(fck, u_rules)
    k1, k2 = moment_k(c1, c2), moment_k(c2, c1)
    largest = r.searchDistance * d
    if reach is not None:
        largest = min(largest, reach)
    u0 = 2 * (c1 + c2)
    worst: FootingPunching | None = None
    for i in range(1, r.steps + 1):
        a = largest * i / r.steps
        if a <= 0:
            continue
        u = u0 + 2 * math.pi * a
        reduced = max(ved - reaction_inside(a), 0.0)
        w1 = c1 * c1 / 2 + c1 * c2 + 2 * c2 * a + 4 * a * a + math.pi * a * c1
        w2 = c2 * c2 / 2 + c1 * c2 + 2 * c1 * a + 4 * a * a + math.pi * a * c2
        beta = 1.0
        if reduced > 0:
            beta += k1 * abs(m1) * u / (reduced * w1) + k2 * abs(m2) * u / (reduced * w2)
        v_ed = beta * reduced / (u * d)
        v_rd = v_rdc * 2 * d / a
        found = FootingPunching(a, u, v_ed, v_rd, reduced, beta, beta * ved / (u0 * d), v_rdmax)
        if worst is None or found.utilisation > worst.utilisation:
            worst = found
    return worst


def footing_note(found: FootingPunching, d: float) -> str:
    """The note of a footing's punching row."""
    return (
        f"critical perimeter at a = {found.a:.0f} mm ({found.a / d:.2f} d), u = {found.u:.0f} mm, "
        f"VEd,red = {found.v_ed_red / 1e3:.0f} kN, β = {found.beta:.2f}, vEd = {found.v_ed:.3f} "
        f"MPa, vRd = vRd,c 2d/a = {found.v_rd:.3f} MPa; at the column face vEd,0 = "
        f"{found.v_ed0:.3f} MPa against vRd,max = {found.v_rdmax:.3f} MPa; shown as v u d "
        f"({code_context.cite('concreteMethods', 'footingPunching')})"
    )
