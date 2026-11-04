"""Design strengths of concrete and reinforcement by partial factors, and the concrete's
properties from its strength class (method ``partialFactors`` of the pack's
``concreteMethods.ultimate``).

A pack that chooses this method designs sections with the design strengths
``fcd = αcc fck / γc`` and ``fyd = fyk / γs`` and no strength reduction factor (φ = 1); a pack
without it (the default pack) keeps the strength design with φ of :mod:`saengine.design.rc`
unchanged.

- Concrete properties from fck by the strength-class relations whose coefficients the pack
  gives (``relations``): fcm = fck + increment; fctm = a fck^b up to ``highFrom``, above it
  c ln(1 + fcm / divisor); fctk,0.05 and fctk,0.95 as shares of fctm; Ecm = a (fcm / divisor)^b;
  the strains εc2, εcu2, εc3, εcu3 [per mille], the exponent n, and the stress block's η and λ:
  ``base`` up to ``highFrom``; above it ``highBase + highCoefficient × term^highExponent`` with
  term = (top - fck) / 100 when ``top`` is given, (fck - highFrom) / divisor when ``divisor``
  is given, else (fck - highFrom).
- Stress block: ``rectangular`` (η fcd over λ x, strain εcu3 at the extreme fibre) or
  ``parabolaRectangle`` (εc2, εcu2, n). The rectangular block keeps the sections' closed-form
  integration (:mod:`saengine.design.fast_ultimate`); the parabola-rectangle is integrated by
  concreteproperties over its mesh (slower).
- Reinforcement: elastic-perfectly plastic at fyd (the horizontal top branch, no strain limit).
- Axial compression: NRd = η fcd (Ac - As) + σs As with σs = min(fyd, Es εc2) (the strain of a
  section in pure compression), and the moments at least NEd e0 with e0 = h / divisor, at
  least ``eccentricityMin`` (:func:`minimum_moment`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context

#: (pack, rules) of the pack last read.
_memo: tuple[Any, Any] | None = None


def rules() -> Any | None:
    """The pack's ``concreteMethods.ultimate`` (method ``partialFactors``), or None when the
    pack in force designs with φ (the default pack)."""
    global _memo
    pack = code_context.current()
    memo = _memo
    if memo is None or memo[0] is not pack:
        found = None
        if pack.has("concreteMethods"):
            found = getattr(pack.table("concreteMethods"), "ultimate", None)
        memo = _memo = (pack, found)
    return memo[1]


def partial_factors() -> bool:
    """True when the pack in force designs with partial factors on the materials."""
    return rules() is not None


def _relation(rel: Any, fck: float, high_from: float) -> float:
    if fck <= high_from or rel.highBase is None:
        return float(rel.base)
    if rel.top is not None:
        term = max(0.0, (rel.top - fck) / 100.0) ** rel.highExponent
    elif rel.divisor is not None:
        term = (fck - high_from) / rel.divisor
    else:
        term = (fck - high_from) ** rel.highExponent
    return float(rel.highBase + rel.highCoefficient * term)


@dataclass(frozen=True)
class ConcreteProperties:
    """Strength and deformation properties of concrete of characteristic strength fck [MPa]."""

    fck: float
    fcm: float
    fctm: float
    fctk005: float
    fctk095: float
    ecm: float  # MPa
    eps_c2: float  # strains (not per mille)
    eps_cu2: float
    n: float
    eps_c3: float
    eps_cu3: float
    eta: float
    lam: float


def properties(fck: float, found: Any | None = None) -> ConcreteProperties:
    """The properties of concrete fck by the pack's relations (see the module notes)."""
    r = (found or rules()).relations
    fcm = fck + r.fcmIncrement
    if fck <= r.highFrom:
        fctm = r.fctmCoefficient * fck**r.fctmExponent
    else:
        fctm = r.fctmHighCoefficient * math.log(1 + fcm / r.fctmHighDivisor)
    lo, hi = r.fctkShares
    h = r.highFrom
    return ConcreteProperties(
        fck=fck,
        fcm=fcm,
        fctm=fctm,
        fctk005=lo * fctm,
        fctk095=hi * fctm,
        ecm=r.ecmCoefficient * (fcm / r.ecmDivisor) ** r.ecmExponent,
        eps_c2=_relation(r.epsC2, fck, h) / 1e3,
        eps_cu2=_relation(r.epsCu2, fck, h) / 1e3,
        n=_relation(r.n, fck, h),
        eps_c3=_relation(r.epsC3, fck, h) / 1e3,
        eps_cu3=_relation(r.epsCu3, fck, h) / 1e3,
        eta=_relation(r.eta, fck, h),
        lam=_relation(r.lam, fck, h),
    )


def fcd(fck: float, found: Any | None = None, accidental: bool = False) -> float:
    """Design compressive strength αcc fck / γc [MPa]."""
    r = found or rules()
    gamma = (r.gammaCAccidental or r.gammaC) if accidental else r.gammaC
    return r.alphaCC * fck / gamma


def fctd(fck: float, found: Any | None = None) -> float:
    """Design tensile strength αct fctk,0.05 / γc [MPa]."""
    r = found or rules()
    return r.alphaCT * properties(fck, r).fctk005 / r.gammaC


def fyd(fyk: float, found: Any | None = None, accidental: bool = False) -> float:
    """Design yield strength fyk / γs [MPa]."""
    r = found or rules()
    gamma = (r.gammaSAccidental or r.gammaS) if accidental else r.gammaS
    return fyk / gamma


def ultimate_strain(fck: float) -> float:
    """The concrete strain at the extreme compression fibre at the ultimate limit state: the
    stress block's (εcu3 rectangular, εcu2 parabola-rectangle)."""
    r = rules()
    p = properties(fck, r)
    return p.eps_cu3 if r.stressBlock == "rectangular" else p.eps_cu2


def steel_yield(fyk: float) -> float:
    """The bars' yield stress in the section analysis: fyd with partial factors, else fy."""
    return fyd(fyk) if partial_factors() else fyk


def concrete_profile(fck: float) -> Any:
    """The concreteproperties ultimate profile of the pack's stress block."""
    from concreteproperties.stress_strain_profile import (
        EurocodeParabolicUltimate,
        RectangularStressBlock,
    )

    r = rules()
    p = properties(fck, r)
    f = fcd(fck, r)
    if r.stressBlock == "parabolaRectangle":
        return EurocodeParabolicUltimate(
            compressive_strength=f, compressive_strain=p.eps_c2, ultimate_strain=p.eps_cu2, n=p.n
        )
    return RectangularStressBlock(
        compressive_strength=f, alpha=p.eta, gamma=p.lam, ultimate_strain=p.eps_cu3
    )


def axial_resistance(
    fck: float, fyk: float, es: float, concrete_area: float, steel: float
) -> float:
    """NRd [N] of a section in pure compression (see the module notes); ``concrete_area`` net
    of the bars."""
    r = rules()
    p = properties(fck, r)
    strain = p.eps_c2 if r.pureCompressionStrain == "epsC2" else p.eps_c3
    sigma_s = min(fyd(fyk, r), es * strain)
    eta = p.eta if r.stressBlock == "rectangular" else 1.0
    return eta * fcd(fck, r) * concrete_area + sigma_s * steel


def eccentricity(depth: float) -> float:
    """e0 [mm] of a member of depth ``depth`` [mm] in the direction considered."""
    r = rules()
    return max(depth / r.eccentricityDivisor, r.eccentricityMin)


def minimum_moment(pu: float, depth: float) -> float:
    """NEd e0 [N·mm] (0 without partial factors or in tension)."""
    if not partial_factors() or pu <= 0:
        return 0.0
    return pu * eccentricity(depth)


def strength_class(fck: float) -> str:
    """The class name of fck, "C30/37" (the nearest class at or below fck), or "fck = x MPa"."""
    r = rules()
    best = None
    for cyl, cube in r.strengthClasses:
        if cyl <= fck + 1e-9:
            best = (cyl, cube)
    if best is None or abs(best[0] - fck) > 1e-9:
        return f"fck = {fck:g} MPa"
    return f"C{best[0]:g}/{best[1]:g}"


def method_lines(code: str) -> list[str]:
    """The design report's method lines of the members designed with partial factors (they
    take the place of the strength design's lines on the basis, flexure, beams and columns)."""
    r = rules()
    cite = code_context.cite
    block = (
        "the rectangular stress block η fcd over λ x, εcu3 at the extreme fibre"
        if r.stressBlock == "rectangular"
        else "the parabola-rectangle diagram (εc2, εcu2, n)"
    )
    shear = cite("concreteMethods", "shear")
    members = cite("concreteMethods", "beamSteel")
    lines = [
        (
            f"Limit state design to {code} with partial factors on the materials: fcd = αcc fck / γc "
            f"(αcc = {r.alphaCC:g}, γc = {r.gammaC:g}), fyd = fyk / γs (γs = {r.gammaS:g}), no "
            f"strength reduction factor ({cite('concreteMethods', 'designStrength')})."
        ),
        (
            f"Flexure and axial force by strain compatibility with {block} (concreteproperties), "
            f"the bars elastic-perfectly plastic at fyd ({cite('concreteMethods', 'ultimate')})."
        ),
        (
            "Beams: sagging and hogging moments about the strong axis; shear by the variable strut "
            "inclination method, VRd = max(VRd,c, min(VRd,s, VRd,max)) with cot θ chosen in the "
            f"pack's range for the largest resistance ({shear}); least links ρw,min, link spacing, "
            f"least and largest longitudinal steel ({members})."
        ),
        (
            "Columns: axial force with biaxial bending from the interaction surface on the design "
            "strengths, NRd = η fcd (Ac - As) + min(fyd, Es εc2) As, the moments at least NEd e0 "
            f"about both axes at once (on the safe side; {cite('concreteMethods', 'minimumEccentricity')}); "
            f"shear by the variable strut method with σcp of the simultaneous axial force ({shear}); "
            f"least and largest steel, bar and link sizes and link spacing "
            f"({cite('concreteMethods', 'columnSteel')}, {cite('concreteMethods', 'columnLinks')})."
        ),
    ]
    # Alpha 9 C5b: the other areas by the pack's methods (saengine.design.limit_state_rows), and
    # what still takes the parent pack's method.
    from saengine.design import limit_state_rows, method_selection

    lines += limit_state_rows.method_lines()
    chosen = method_selection.summary()
    parent = [
        name
        for area, name in (
            ("torsion", "beam torsion"),
            ("deflection", "beam deflection"),
            ("slenderness", "column slenderness"),
            ("punching", "punching"),
            ("seismic", "the seismic detailing"),
        )
        if not chosen.get(area)
    ]
    parent += ["deep beams and corbels (strut-and-tie)", "the deflection of slabs and stairs"]
    lines.append(
        "By the parent pack's method and values (stated in its lines): " + ", ".join(parent) + "."
    )
    return lines


def basis_note(fck: float, fyk: float) -> str:
    """One line of the design strengths of a section, for check notes."""
    r = rules()
    p = properties(fck, r)
    block = (
        f"η = {p.eta:.2f}, λ = {p.lam:.2f}, εcu3 = {1e3 * p.eps_cu3:.2f} ‰"
        if r.stressBlock == "rectangular"
        else f"parabola-rectangle, εc2 = {1e3 * p.eps_c2:.2f} ‰, εcu2 = {1e3 * p.eps_cu2:.2f} ‰"
    )
    clause = code_context.cite("concreteMethods", "designStrength")
    return f"fcd = {fcd(fck, r):.1f} MPa, fyd = {fyd(fyk, r):.0f} MPa ({block})" + (
        f" ({clause})" if clause else ""
    )
