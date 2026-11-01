"""Slabs on grade: ground-bearing floor slabs on the compacted ground (Part 9).

A slab on grade carries its floor load straight to the ground: a uniform load on a uniformly
supported slab bends it hardly at all, so the slab is checked for the largest concentrated
load (a post, rack leg or wheel on a square contact of side ``c``) by Westergaard's theory of
a plate on a dense liquid (Winkler) subgrade of modulus k, with the corrections of Ioannides,
Thompson and Barenberg (1985, "Westergaard solutions reconsidered", Transportation Research
Record 1043):

- radius of relative stiffness ``l = (E h³ / (12 (1 - ν²) k))^(1/4)``;
- the load on a circle of the same area, radius ``a = c / √π``, and Westergaard's equivalent
  radius ``b = √(1.6 a² + h²) - 0.675 h`` where a < 1.724 h (else b = a);
- interior: ``σi = 3 (1 + ν) P / (2π h²) (ln(l / b) + 0.6159)``;
- edge: ``σe = 3 (1 + ν) P / (π (3 + ν) h²) (ln(E h³ / (100 k a⁴)) + 1.84 - 4ν/3 + (1 - ν)/2
  + 1.18 (1 + 2ν) a / l)``;
- corner: ``σc = 3 P / h² (1 - (c / l)^0.72)``, c the side of the square contact;

each against the modulus of rupture over a factor of safety, ``fr / FS`` with ``fr = 0.62 λ
√f'c`` (ACI 318-19 19.2.3.1; the default pack's code takes the same value). Edge and corner
stresses assume no load transfer across the joints (on the safe side for dowelled joints).

The slab under the concentrated load is checked for punching as plain concrete: the factored
load ``γL P`` (γL the largest live load factor of the code pack's strength combinations: 1.6
in the default pack), with nothing taken off for
the ground under it, against ``φVn = 0.60 × 0.11 (1 + 2/β) λ √f'c b0 h ≤ 0.60 × 0.22 λ √f'c b0
h`` round the contact at h/2 (ACI 318-19 14.5.5.1 (b), φ of Table 21.2.1).

Reported only (guidance, not counted): the crack-control mesh against 0.0018 of the gross
section (ACI 318-19 24.4.3.2, the shrinkage and temperature ratio for fy 420) and, without a
mesh, the contraction joints at no more than 30 h apart (the usual range is 24 to 36 times the
thickness for plain slabs on grade).

Units: N, mm and MPa inside; reported in kN, kPa and MPa.
"""

from __future__ import annotations

import math
from typing import Any

#: Strength reduction factor of plain concrete (ACI 318-19 Table 21.2.1).
PHI_PLAIN = 0.60


def live_factor() -> tuple[float | None, str]:
    """The largest live load factor of the pack's strength combinations (the default pack: 1.6,
    1.2D + 1.6L) and the clause of that combination; (None, "") when the pack has none."""
    from saengine.codes import context as code_context

    best: tuple[float | None, str] = (None, "")
    for row in code_context.table("combinations").strength:
        factor = row.factors.get("L")
        if factor is not None and (best[0] is None or factor > best[0]):
            best = (float(factor), (row.source or "").split(",")[0].split(" (")[0])
    return best


def __getattr__(name: str) -> Any:
    if name == "LIVE_FACTOR":  # the former constant, with the pack in force
        return live_factor()[0]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


#: Contraction joints of a plain slab on grade at most this many thicknesses apart.
JOINT_SPACING = 30.0
#: Shrinkage and temperature ratio of the gross section (ACI 318-19 24.4.3.2, fy 420).
SHRINKAGE_RATIO = 0.0018

GROUND_SLAB_METHOD = [
    (
        "Slabs on grade: the largest concentrated load by Westergaard's plate on a Winkler "
        "subgrade with the corrections of Ioannides et al. (1985): interior, edge and corner "
        "flexural stresses against fr / FS, fr = 0.62 λ √f'c (ACI 318-19 19.2.3.1); "
        "punching of the plain slab round the contact under γL P (the code pack's largest live "
        "load factor; ACI 14.5.5.1 (b)); the "
        "uniform floor load needs no flexure on a uniformly supported slab. The crack-control "
        "mesh (0.0018 Ag) and the joint spacing (≤ 30 h without a mesh) are reported only."
    ),
]


def relative_stiffness(e: float, h: float, nu: float, k: float) -> float:
    """Radius of relative stiffness l [mm]: E [MPa], h [mm], k [N/mm³]."""
    return (e * h**3 / (12 * (1 - nu**2) * k)) ** 0.25


def equivalent_radius(a: float, h: float) -> float:
    """Westergaard's equivalent radius b [mm] of a load on a circle of radius a [mm]."""
    if a < 1.724 * h:
        return math.sqrt(1.6 * a**2 + h**2) - 0.675 * h
    return a


def westergaard(
    load: float, side: float, h: float, e: float, nu: float, k: float
) -> dict[str, float]:
    """The flexural stresses [MPa] under a concentrated ``load`` [N] on a square contact of
    ``side`` [mm] at the interior, an edge and a corner of a slab ``h`` [mm] thick (see the
    module notes), with ``l`` and ``a`` [mm]."""
    l_ = relative_stiffness(e, h, nu, k)
    a = side / math.sqrt(math.pi)
    b = equivalent_radius(a, h)
    interior = 3 * (1 + nu) * load / (2 * math.pi * h**2) * (math.log(l_ / b) + 0.6159)
    edge = (
        3
        * (1 + nu)
        * load
        / (math.pi * (3 + nu) * h**2)
        * (
            math.log(e * h**3 / (100 * k * a**4))
            + 1.84
            - 4 * nu / 3
            + (1 - nu) / 2
            + 1.18 * (1 + 2 * nu) * a / l_
        )
    )
    corner = 3 * load / h**2 * (1 - (side / l_) ** 0.72)
    return {"interior": interior, "edge": edge, "corner": corner, "l": l_, "a": a, "b": b}


def modulus_of_rupture(fc: float, lam: float = 1.0) -> float:
    """fr = 0.62 λ √f'c [MPa] (ACI 318-19 19.2.3.1)."""
    return 0.62 * lam * math.sqrt(fc)


def plain_punching(side: float, h: float, fc: float, lam: float = 1.0) -> tuple[float, float]:
    """φVn [N] of a plain slab round a square load of ``side`` [mm] (ACI 318-19 14.5.5.1 (b),
    the section at h/2, β = 1) and b0 [mm]."""
    b0 = 4 * (side + h)
    beta = 1.0
    vn = min(0.11 * (1 + 2 / beta), 0.22) * lam * math.sqrt(fc) * b0 * h
    return PHI_PLAIN * vn, b0


def ground_slab_checks(
    slab: Any, fc: float, e: float, nu: float, k: float, fy: float | None = None
) -> list[dict[str, Any]]:
    """The checks of a :class:`saengine.library.substructure.GroundSlab`: f'c, E [MPa], ν, k
    [kN/m³], fy of its mesh [MPa] (see the module notes)."""
    from saengine.design.check import _check

    h = float(slab.thickness)
    checks: list[dict[str, Any]] = []
    fr = modulus_of_rupture(fc)
    allowable = fr / slab.factorOfSafety
    if slab.pointLoad > 0:
        p = slab.pointLoad * 1e3
        side = float(slab.contactSide)
        stresses = westergaard(p, side, h, e, nu, k * 1e-6)
        basis = (
            f"P = {slab.pointLoad:g} kN on {side:.0f} × {side:.0f} mm, h = {h:.0f} mm, k = "
            f"{k:.0f} kN/m³, E = {e:.0f} MPa, ν = {nu:g}: l = {stresses['l']:.0f} mm; "
            f"fr = 0.62 √f'c = {fr:.2f} MPa / FS {slab.factorOfSafety:g}"
        )
        for where, text in (
            ("interior", "Westergaard interior, b = {b:.0f} mm"),
            ("edge", "Westergaard edge (Ioannides et al. 1985), a = {a:.0f} mm"),
            ("corner", "Ioannides et al. 1985 corner, no load transfer across the joints"),
        ):
            checks.append(
                _check(
                    f"Flexural stress, load at the {where}",
                    stresses[where],
                    allowable,
                    "MPa",
                    None,
                    text.format(**stresses) + f"; {basis}",
                )
            )
        capacity, b0 = plain_punching(side, h, fc)
        factor, clause = live_factor()
        if factor is not None:  # else design_ground_slab notes it
            checks.append(
                _check(
                    "Punching under the concentrated load",
                    factor * slab.pointLoad,
                    capacity / 1e3,
                    "kN",
                    None,
                    f"Pu = {factor:g} P ({clause}), plain concrete φVn = 0.60 × 0.22 √f'c b0 h "
                    f"(0.11 (1 + 2/β) ≤ 0.22, β = 1) with b0 = {b0:.0f} mm at h/2 (ACI 318-19 "
                    "14.5.5.1 (b)); the ground under the load is not taken off",
                )
            )
    mesh = slab.mesh
    required = SHRINKAGE_RATIO * h * 1000
    if mesh is not None:
        provided = math.pi * mesh.dia**2 / 4 * 1000 / mesh.spacing
        ratio = SHRINKAGE_RATIO * (420 / fy if fy and fy > 420 else 1.0)
        checks.append(
            _check(
                "Crack-control mesh",
                ratio * h * 1000,
                provided,
                "mm²/m",
                None,
                f"Ø{mesh.dia:g} @ {mesh.spacing:g} each way against {ratio:.4f} Ag (ACI 318-19 "
                "24.4.3.2); in the upper third of the slab. Guidance, reported only",
                flag=True,
            )
        )
    elif slab.jointSpacing is not None:
        checks.append(
            _check(
                "Contraction joint spacing",
                float(slab.jointSpacing),
                JOINT_SPACING * h,
                "mm",
                None,
                f"plain slab: joints at most {JOINT_SPACING:g} h apart (the usual 24 h to 36 h); "
                f"a mesh of {required:.0f} mm²/m allows wider bays. Guidance, reported only",
                flag=True,
            )
        )
    return checks


def design_ground_slab(ctx: Any, slab: Any) -> tuple[dict[str, Any], list[str]]:
    """The checks of a slab on grade of the substructure in the report's format, and notes;
    raises :class:`~saengine.substructure.context.Skip` when it cannot be checked."""
    from saengine.library.substructure import polygon_area
    from saengine.substructure.context import Skip

    concrete = ctx.concrete(slab.material, slab.id)
    fc = concrete.concrete.fc
    e = concrete.mechanical.E or 4700 * math.sqrt(fc)  # ACI 318-19 19.2.2.1 (b)
    nu = concrete.mechanical.nu or 0.2
    k = slab.subgradeModulus
    notes: list[str] = []
    if k is None:
        springs = ctx.substructure.design.springsFrom
        if springs == "soilReport":
            raise Skip(
                "enter the subgrade modulus k of its compacted sub-base (or a subgrade springs "
                "value in 9 Substructure → Design)"
            )
        k = float(springs)
        notes.append(f"{slab.id}: k = {k:.0f} kN/m³ from 9 Substructure → Design")
    fy = None
    if slab.mesh is not None:
        if slab.meshMaterial is None:
            raise Skip("its mesh needs a rebar material (03 Materials)")
        fy = ctx.rebar(slab.meshMaterial).steel.fy
    checks = ground_slab_checks(slab, fc, e, nu, k, fy)
    if slab.pointLoad > 0 and live_factor()[0] is None:
        notes.append(
            f"{slab.id}: punching under the concentrated load: not covered by the code pack "
            "(no live load factor in its strength combinations)"
        )
    if slab.pointLoad <= 0:
        notes.append(
            f"{slab.id}: no concentrated load: a uniform load on a uniformly supported slab on "
            "grade needs no flexural check"
        )
    counted = [c for c in checks if not c["flag"]]
    area = abs(polygon_area(slab.outline))
    return {
        "id": slab.id,
        "type": "groundSlab",
        "columns": [],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in counted), default=0.0),
        "ok": all(c["ok"] for c in counted),
        "sizes": {"thickness": slab.thickness, "area": round(area / 1e6, 2)},
    }, notes
