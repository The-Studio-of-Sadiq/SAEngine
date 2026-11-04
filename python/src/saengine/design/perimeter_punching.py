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
