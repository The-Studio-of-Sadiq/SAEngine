"""Shear of beams by the compression field method with β and θ (method ``compressionField`` of
the pack's ``concreteMethods.shear``; alpha 9 C17, the form of CSA A23.3-19 Clause 11.3).

Material resistance factors on each term (φc on the concrete, φs on the steel), the effective
shear depth dv = max(a d, b h):

- concrete: ``Vc = φc λ β √f'c bw dv`` with √f'c at most ``rootMax``;
- links: ``Vs = φs Av fy dv cot θ / s`` (fy at most ``fyMax``);
- ``Vr = Vc + Vs`` at most ``vrMaxShare`` φc f'c bw dv (the crushing of the web).

β and θ, the pack's ``variant``:

- ``simplified``: β = ``betaWithStirrups`` where the links reach Av,min = ``minCoefficient``
  √f'c bw s / fy, else a / (b + dv) (``betaNoStirrups``, the size effect of members without
  links); θ = ``thetaDeg``;
- ``general`` (where the forces at the section are known, :func:`general_terms`): the
  longitudinal strain at mid-depth εx = (Mf / dv + Vf + 0.5 Nf) / (2 Es As) within
  ``strainLimits`` (Mf at least Vf dv), β = g1 / (1 + g2 εx) × g3 / (g4 + sze) and
  θ = t1 + t2 εx [°], sze = ``stirrupSpacingParameter`` with Av,min, else
  c1 dv / (c2 + ag) at least c3 dv. The design run's beams have no simultaneous Mf at the
  shear's station, so it designs by the simplified variant and states it.

Links are needed (Av,min) where Vf exceeds Vc; their spacing is at most a dv and s mm, at most
``closeSpacing`` where Vf exceeds ``closeShare`` λ φc f'c bw dv.

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context

METHOD = "compressionField"


def rules() -> Any | None:
    """The pack's ``concreteMethods.shear`` when it is the compression field method, or None."""
    pack = code_context.current()
    if not pack.has("concreteMethods"):
        return None
    from saengine.codes.method_tables import chosen

    return chosen(pack.table("concreteMethods"), "shear", METHOD)


def shear_depth(d: float, h: float, r: Any) -> float:
    """dv = max(a d, b h) [mm]."""
    a, b = r.depthShares
    return max(a * d, b * h)


def min_links(fc: float, b: float, spacing: float, fy: float, r: Any) -> float:
    """Av,min [mm²] at ``spacing``."""
    return r.minCoefficient * math.sqrt(fc) * b * spacing / min(fy, r.fyMax)


def max_spacing(dv: float, vf: float, fc: float, b: float, r: Any, lam: float = 1.0) -> float:
    """The largest link spacing [mm] at the shear ``vf`` [N]."""
    share, cap = r.spacing
    if vf > r.closeShare * lam * r.phiC * fc * b * dv:
        share, cap = r.closeSpacing
    return min(share * dv, cap)


@dataclass(frozen=True)
class GeneralTerms:
    eps_x: float
    beta: float
    theta_deg: float
    sze: float


def general_terms(
    mf: float,
    vf: float,
    nf: float,
    dv: float,
    steel_area: float,
    with_min_links: bool,
    r: Any,
    es: float = 200000.0,
    aggregate: float | None = None,
) -> GeneralTerms:
    """β, θ of the general variant at the section's factored Mf [N·mm], Vf [N] and Nf [N]
    (tension positive) on the flexural tension steel ``steel_area`` [mm²] (see the module
    notes)."""
    g = r.general
    m = max(abs(mf), abs(vf) * dv)
    eps = (m / dv + abs(vf) + 0.5 * nf) / (2 * es * steel_area)
    lo, hi = r.strainLimits
    eps = min(max(eps, lo), hi)
    if with_min_links:
        sze = g.stirrupSpacingParameter
    else:
        c1, c2, c3 = g.crackSpacing
        ag = r.aggregate if aggregate is None else aggregate
        sze = max(c1 * dv / (c2 + ag), c3 * dv)
    g1, g2, g3, g4 = g.beta
    t1, t2 = g.theta
    beta = g1 / (1 + g2 * eps) * g3 / (g4 + sze)
    return GeneralTerms(eps, beta, t1 + t2 * eps, sze)


def beam_shear(
    section: Any,
    stirrup_dia: float | None,
    legs: int,
    spacing: float | None,
    lam: float = 1.0,
) -> Any:
    """The factored shear resistance of a rectangular section by the simplified variant
    (:class:`saengine.design.rc.Shear` with Vr in ``phi_vn``, Vc and Vs factored)."""
    from saengine.design.rc import DesignError, RectangleProfile, Shear, bar_area

    if not isinstance(section.profile, RectangleProfile):
        raise DesignError("shear is checked for rectangular beams only")
    r = rules()
    b = section.profile.xDim
    h = section.depth
    try:
        d = section.effective_depth(top=False)
    except DesignError:
        d = section.effective_depth(top=True)
    faces = [
        sum(bar.area for bar in section.bars if (bar.y > 0 if top else bar.y < 0))
        for top in (True, False)
    ]
    rho = min(a for a in faces if a > 0) / (b * d)
    fc = section.fc
    fy = min(section.fy, r.fyMax)
    dv = shear_depth(d, h, r)
    root = min(math.sqrt(fc), r.rootMax)
    av = legs * bar_area(stirrup_dia) if stirrup_dia and spacing else 0.0
    av_min = min_links(fc, b, spacing, section.fy, r) if av else 0.0
    with_min = av > 0 and av >= av_min
    if with_min:
        beta = r.betaWithStirrups
    else:
        a, c = r.betaNoStirrups
        beta = a / (c + dv)
    theta = math.radians(r.thetaDeg)
    vc = r.phiC * lam * beta * root * b * dv
    vs = r.phiS * av * fy * dv / (math.tan(theta) * spacing) if av else 0.0
    vr_max = r.vrMaxShare * r.phiC * fc * b * dv
    limited = vc + vs > vr_max
    vr = min(vc + vs, vr_max)
    if limited:
        vs = max(vr - vc, 0.0)
    cite = code_context.cite("concreteMethods", "shear")
    notes = [
        (
            f"Vc = φc λ β √f'c bw dv = {vc / 1e3:.1f} kN (β = {beta:.3f}, dv = {dv:.0f} mm, "
            f"φc = {r.phiC:g})"
        ),
        (
            f"Vs = φs Av fy dv cot θ / s = {vs / 1e3:.1f} kN (θ = {r.thetaDeg:g}°, φs = {r.phiS:g})"
            if av
            else "no stirrups"
        ),
    ]
    if limited:
        notes.append(f"Vr limited to {r.vrMaxShare:g} φc f'c bw dv = {vr_max / 1e3:.1f} kN")
    notes.append(
        "simplified β and θ (the design run has no simultaneous Mf at the shear's station)"
        + (f" ({cite})" if cite else "")
    )
    if section.fy > r.simplifiedFyMax:
        notes.append(
            f"fy = {section.fy:g} MPa above {r.simplifiedFyMax:g} MPa: the code asks for the "
            "general method (not made by the design run)"
        )
    if av and not with_min:
        notes.append(
            f"Av = {av:.0f} mm² below Av,min = {av_min:.0f} mm²"
            + code_context.cited("concreteMethods", "shearMinimum", sep=" ")
        )
    return Shear(
        vr,
        vc,
        vs,
        limited,
        d,
        av,
        av_min,
        rho,
        beta,
        with_min,
        vc,
        notes=tuple(notes),
        threshold=vc,
        cot_theta=1 / math.tan(theta),
    )


def method_line() -> str:
    """The report's line of the beams' shear by this method."""
    r = rules()
    return (
        f"shear by the compression field method, Vr = φc λ β √f'c bw dv + φs Av fy dv cot θ / s "
        f"<= {r.vrMaxShare:g} φc f'c bw dv with the simplified β ({r.betaWithStirrups:g} with "
        f"the least links) and θ = {r.thetaDeg:g}° ({code_context.cite('concreteMethods', 'shear')})"
    )
