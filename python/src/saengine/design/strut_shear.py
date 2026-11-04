"""Shear and torsion by the variable strut inclination method (method ``variableStrut`` of the
pack's ``concreteMethods.shear``, ``thinWalledVariableStrut`` of ``concreteMethods.torsion``).

Units: mm, MPa, N, N·mm. fck is the section's ``fc``; the design strengths are those of
:mod:`saengine.design.design_strength`.

Shear (members with vertical links):

- without design shear reinforcement: ``VRd,c = [CRd,c k (100 ρl fck)^(1/3) + k1 σcp] bw d``,
  at least ``(vmin + k1 σcp) bw d``, with CRd,c = coefficient / γc, k = 1 + √(reference / d)
  at most ``sizeMax``, ρl = Asl / (bw d) at most ``rhoLMax``, vmin = c k^1.5 √fck and
  σcp = NEd / Ac (compression positive) at most ``sigmaCpShare`` fcd;
- with links: ``VRd,s = Asw / s · z · fywd · cot θ`` and ``VRd,max = αcw bw z ν1 fcd /
  (cot θ + tan θ)`` with z = share × d and ν1 = c (1 - fck / divisor). cot θ is chosen within
  the pack's range to give the largest resistance: where the two are equal,
  cot θ = √(1 / ω - 1) with ω = Asw fywd / (s bw ν1 fcd αcw), clipped to the range;
- the resistance is ``max(VRd,c, min(VRd,s, VRd,max))``: where VEd <= VRd,c no calculated
  shear reinforcement is needed. SAEngine practice reading of the clause, stated in the notes;
- the least ratio of links ρw,min = c √fck / fyk (beams always need it, so the minimum-link
  check of a beam below it fails whatever the shear: :attr:`saengine.design.rc.Shear.threshold`
  is 0).

Torsion (:func:`torsion`): the thin-walled closed section of thickness tef = A / u (at least
``coverShare`` × the distance from the face to the bar axis), Ak and uk on the centre line;
TRd,max = 2 ν αcw fcd Ak tef sin θ cos θ; the links needed Asw / s = TEd / (2 Ak fywd cot θ)
and the longitudinal bars ΣAsl = TEd uk cot θ / (2 Ak fyd); the interaction
TEd / TRd,max + VEd / VRd,max <= 1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context
from saengine.design import design_strength


def rules() -> Any | None:
    """The pack's ``concreteMethods.shear``, or None."""
    pack = code_context.current()
    if not pack.has("concreteMethods"):
        return None
    from saengine.codes.method_tables import chosen  # C8: another method may hold the group

    return chosen(pack.table("concreteMethods"), "shear", "variableStrut")


def torsion_rules() -> Any | None:
    pack = code_context.current()
    if not pack.has("concreteMethods"):
        return None
    from saengine.codes.method_tables import chosen  # C8: another method may hold the group

    return chosen(pack.table("concreteMethods"), "torsion", "thinWalledVariableStrut")


def size_factor(d: float, r: Any) -> float:
    return min(r.sizeMax, 1 + math.sqrt(r.sizeReference / d))


def nu1(fck: float, r: Any) -> float:
    return r.nuCoefficient * (1 - fck / r.nuDivisor)


def concrete_resistance(
    b: float, d: float, rho_l: float, fck: float, sigma_cp: float = 0.0, r: Any | None = None
) -> float:
    """VRd,c [N] of a member without design shear reinforcement."""
    r = r or rules()
    u = design_strength.rules()
    k = size_factor(d, r)
    sigma = min(max(sigma_cp, 0.0), r.sigmaCpShare * design_strength.fcd(fck, u))
    if sigma_cp < 0:
        sigma = sigma_cp  # tension lowers VRd,c (k1 σcp with σcp negative)
    crdc = r.crdcCoefficient / u.gammaC
    vmin = r.vminCoefficient * k**1.5 * math.sqrt(fck)
    v = max(crdc * k * (100 * min(rho_l, r.rhoLMax) * fck) ** (1 / 3), vmin) + r.k1 * sigma
    return max(v, 0.0) * b * d


@dataclass(frozen=True)
class LinkResistance:
    vrd_s: float
    vrd_max: float
    cot_theta: float
    z: float


def link_resistance(
    b: float, d: float, asw: float, spacing: float, fck: float, fywk: float, r: Any | None = None
) -> LinkResistance:
    """VRd,s and VRd,max [N] of vertical links at the cot θ that gives the largest of their
    lesser (see the module notes)."""
    r = r or rules()
    u = design_strength.rules()
    z = r.leverArmShare * d
    f_cd = design_strength.fcd(fck, u)
    f_ywd = design_strength.fyd(fywk, u)
    v1 = nu1(fck, r)
    lo, hi = r.cotTheta
    omega = asw * f_ywd / (spacing * b * v1 * f_cd * r.alphaCw)
    cot = math.sqrt(1 / omega - 1) if 0 < omega < 1 else lo
    cot = min(max(cot, lo), hi)
    vrd_s = asw / spacing * z * f_ywd * cot
    vrd_max = r.alphaCw * b * z * v1 * f_cd / (cot + 1 / cot)
    return LinkResistance(vrd_s, vrd_max, cot, z)


def min_link_ratio(fck: float, fyk: float, r: Any | None = None) -> float:
    """ρw,min."""
    r = r or rules()
    return r.rhoWMinCoefficient * math.sqrt(fck) / fyk


def max_link_spacing(d: float, r: Any | None = None) -> float:
    """sl,max [mm] of vertical links."""
    r = r or rules()
    return r.spacingShare * d


def beam_shear(
    section: Any,
    stirrup_dia: float | None,
    legs: int,
    spacing: float | None,
    sigma_cp: float = 0.0,
) -> Any:
    """The design shear resistance of a rectangular section (:class:`saengine.design.rc.Shear`
    with VRd in ``phi_vn``, VRd,c in ``vc`` and min(VRd,s, VRd,max) in ``vs``)."""
    from saengine.design.rc import DesignError, RectangleProfile, Shear, bar_area

    if not isinstance(section.profile, RectangleProfile):
        raise DesignError("shear is checked for rectangular beams only")
    r = rules()
    b = section.profile.xDim
    try:
        d = section.effective_depth(top=False)
    except DesignError:
        d = section.effective_depth(top=True)
    faces = [
        sum(bar.area for bar in section.bars if (bar.y > 0 if top else bar.y < 0))
        for top in (True, False)
    ]
    rho_l = min(a for a in faces if a > 0) / (b * d)
    fck, fyk = section.fc, section.fy
    vrd_c = concrete_resistance(b, d, rho_l, fck, sigma_cp, r)
    av = legs * bar_area(stirrup_dia) if stirrup_dia and spacing else 0.0
    av_min = min_link_ratio(fck, fyk, r) * spacing * b if av else 0.0
    notes = [f"VRd,c = {vrd_c / 1e3:.1f} kN (k = {size_factor(d, r):.2f}, ρl = {rho_l:.4f})"]
    vs = 0.0
    limited = False
    cot = None
    if av:
        links = link_resistance(b, d, av, spacing, fck, fyk, r)
        cot = links.cot_theta
        vs = min(links.vrd_s, links.vrd_max)
        limited = links.vrd_s > links.vrd_max
        notes.append(
            f"VRd,s = {links.vrd_s / 1e3:.1f} kN, VRd,max = {links.vrd_max / 1e3:.1f} kN at "
            f"cot θ = {cot:.2f}"
        )
    else:
        notes.append("no links")
    vrd = max(vrd_c, vs)
    notes.append(
        "VRd = max(VRd,c, min(VRd,s, VRd,max)): no calculated links where VEd <= VRd,c "
        "(SAEngine practice reading)"
    )
    clause = code_context.cite("concreteMethods", "shear")
    if clause:
        notes.append(clause)
    with_min = av > 0 and av >= av_min
    if av and not with_min:
        notes.append(
            f"Asw = {av:.0f} mm² below ρw,min s bw = {av_min:.0f} mm²"
            + code_context.cited("concreteMethods", "shearMinimum", sep=" ")
        )
    return Shear(
        vrd,
        vrd_c,
        vs,
        limited,
        d,
        av,
        av_min,
        rho_l,
        size_factor(d, r),
        with_min,
        vrd_c,
        notes=tuple(notes),
        threshold=0.0,
        cot_theta=cot,
    )


@dataclass(frozen=True)
class TorsionResistance:
    trd_max: float  # N·mm
    tef: float
    ak: float
    uk: float
    cot_theta: float
    links_per_spacing: float  # Asw / s [mm²/mm] of one leg needed for TEd (0 when TEd = 0)
    longitudinal: float  # ΣAsl [mm²] needed for TEd


def torsion(
    b: float,
    h: float,
    axis_distance: float,
    fck: float,
    fyk: float,
    ted: float = 0.0,
    cot_theta: float | None = None,
) -> TorsionResistance:
    """The torsional resistance of a solid rectangle b × h [mm] (see the module notes);
    ``axis_distance`` from the face to the longitudinal bars' axis; ``cot_theta`` that of the
    shear design (the least of the range when None)."""
    r = rules()
    u = design_strength.rules()
    t = torsion_rules()
    area, perimeter = b * h, 2 * (b + h)
    tef = max(area / perimeter, t.coverShare * axis_distance)
    tef = min(tef, min(b, h) / 2)
    ak = (b - tef) * (h - tef)
    uk = 2 * ((b - tef) + (h - tef))
    cot = cot_theta if cot_theta is not None else r.cotTheta[0]
    theta = math.atan(1 / cot)
    f_cd = design_strength.fcd(fck, u)
    trd_max = 2 * nu1(fck, r) * r.alphaCw * f_cd * ak * tef * math.sin(theta) * math.cos(theta)
    f_yd = design_strength.fyd(fyk, u)
    links = ted / (2 * ak * f_yd * cot) if ted > 0 else 0.0
    longitudinal = ted * uk * cot / (2 * ak * f_yd) if ted > 0 else 0.0
    return TorsionResistance(trd_max, tef, ak, uk, cot, links, longitudinal)


def torsion_interaction(ted: float, trd_max: float, ved: float, vrd_max: float) -> float:
    """TEd / TRd,max + VEd / VRd,max (at most 1)."""
    return ted / trd_max + (ved / vrd_max if vrd_max > 0 else 0.0)


def column_rows(section: Any, transverse: Any | None, points: Any) -> list[dict[str, Any]]:
    """Shear check rows of a column by the variable strut inclination method, one per axis
    (:func:`saengine.design.column_shear.shear_axes`): the governing station, with σcp =
    NEd / Ac of that station in VRd,c (compression positive, tension lowers it), ρl half the
    column's steel over bw d. ``points``: (Pu, Vx, Vy, combination, where) per station."""
    from saengine.design.check import _check
    from saengine.design.column_shear import shear_axes

    r = rules()
    if hasattr(points, "pu"):  # column_shear.ShearPoints
        listed = [
            (float(points.pu[i]), float(points.vx[i]), float(points.vy[i]), *points.label(i))
            for i in range(len(points.pu))
        ]
    else:
        listed = list(points)
    if not listed:
        return []
    fck, fyk, ag = section.fc, section.fy, section.gross_area
    clause = code_context.cite("concreteMethods", "shear")
    axes = shear_axes(section, transverse)
    circle = len(axes) == 1
    rows = []
    for part in axes:
        rho_l = min(r.rhoLMax, 0.5 * section.steel_area / (part.bw * part.d))
        links = None
        if part.av and part.spacing:
            links = link_resistance(part.bw, part.d, part.av, part.spacing, fck, fyk, r)
        best = None
        for pu, vx, vy, combination, where in listed:
            vu = math.hypot(vx, vy) if circle else abs(vy if part.axis == "y" else vx)
            vrd_c = concrete_resistance(part.bw, part.d, rho_l, fck, pu / ag, r)
            vrd = max(vrd_c, min(links.vrd_s, links.vrd_max)) if links else vrd_c
            ratio = vu / vrd if vrd > 0 else math.inf
            if best is None or ratio > best[0]:
                best = (ratio, vu, vrd, vrd_c, pu, combination, where)
        _ratio, vu, vrd, vrd_c, pu, combination, where = best
        note = f"VRd,c = {vrd_c / 1e3:.1f} kN with σcp = {pu / ag:.2f} MPa"
        if links:
            note += (
                f"; VRd,s = {links.vrd_s / 1e3:.1f} kN, VRd,max = {links.vrd_max / 1e3:.1f} kN"
                f" at cot θ = {links.cot_theta:.2f}"
            )
        note += f"; {where}" + (f" ({clause})" if clause else "")
        rows.append(
            _check(f"Shear along {part.axis}", vu / 1e3, vrd / 1e3, "kN", combination, note)
        )
    return rows
