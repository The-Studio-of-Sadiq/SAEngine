"""Serviceability of reinforced concrete by the pack's ``concreteMethods``: stress limits
(``serviceStress``), crack control by the direct calculation of the crack width (``cracking``
method ``directWidth``) and deflection by span/depth ratios (``deflection`` method
``spanDepthK``).

Units: mm, MPa, N, N·mm. Rectangular sections, cracked elastic analysis with αe = Es / Ecm
(short term) or Es / Ec,eff given by the caller.

- Stresses (:func:`stress_limits`): σc <= k1 fck under the characteristic combination in the
  exposure classes listed (``k1Exposures``), σc <= k2 fck under the quasi-permanent one (linear
  creep), σs <= k3 fyk (characteristic), k4 fyk for an imposed deformation.
- Least steel for crack control (:func:`min_crack_steel`): As,min σs = kc k fct,eff Act with
  σs = fyk, fct,eff = fctm, Act the tension zone before cracking (h/2 of a rectangle in
  bending, all of it in tension), k linear in h between ``thinDepth`` and ``thickDepth``.
- Crack width (:func:`crack_width`): wk = sr,max (εsm - εcm) with
  εsm - εcm = [σs - kt fct,eff / ρp,eff (1 + αe ρp,eff)] / Es >= ``strainFloor`` σs / Es,
  sr,max = k3 c + k1 k2 k4 φ / ρp,eff, ρp,eff = As / Ac,eff, Ac,eff = b hc,ef,
  hc,ef = min(share (h - d), (h - x) / 3, h / 2); bars more than ``wideSpacingLimit``
  (c + φ/2) apart: sr,max = ``wideSpacingFactor`` (h - x). wmax by exposure class.
- Span/depth (:func:`span_depth_limit`): ρ0 = c √fck; for ρ <= ρ0
  l/d = K [base + a √fck ρ0/ρ + b √fck (ρ0/ρ - 1)^1.5], else
  l/d = K [base + a √fck ρ0/(ρ - ρ') + e √fck √(ρ'/ρ0)]; × stressReference / σs with
  stressReference / σs = stressSteel / (fyk As,req / As,prov); × flangeFactor for beff/bw above flangeRatio; × longSpan
  / l beyond longSpan (longFlatSpan for flat slabs).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context
from saengine.design import design_strength


def _table() -> Any | None:
    pack = code_context.current()
    return pack.table("concreteMethods") if pack.has("concreteMethods") else None


def covered(group: str) -> bool:
    t = _table()
    return t is not None and getattr(t, group, None) is not None


@dataclass(frozen=True)
class CrackedSection:
    x: float  # neutral axis depth [mm]
    i_cr: float  # mm⁴
    sigma_c: float  # MPa, extreme fibre
    sigma_s: float  # MPa, tension bars


def cracked_section(b: float, d: float, a_s: float, moment: float, alpha_e: float,
                    a_s2: float = 0.0, d2: float = 0.0) -> CrackedSection:  # fmt: skip
    """Cracked elastic stresses of a rectangle b × (d ...) under ``moment`` [N·mm]."""
    a = b / 2
    bq = alpha_e * a_s + (alpha_e - 1) * a_s2
    c = -(alpha_e * a_s * d + (alpha_e - 1) * a_s2 * d2)
    x = (-bq + math.sqrt(bq * bq - 4 * a * c)) / (2 * a)
    i_cr = b * x**3 / 3 + alpha_e * a_s * (d - x) ** 2 + (alpha_e - 1) * a_s2 * (x - d2) ** 2
    sigma_c = moment * x / i_cr
    sigma_s = alpha_e * moment * (d - x) / i_cr
    return CrackedSection(x, i_cr, sigma_c, sigma_s)


def stress_limits(fck: float, fyk: float, exposure: str | None = None) -> dict[str, float]:
    """The stress limits [MPa]: concrete characteristic (None key absent when the exposure
    class does not ask for it), quasi-permanent, steel, imposed deformation."""
    s = _table().serviceStress
    out = {"concreteQuasiPermanent": s.k2 * fck, "steel": s.k3 * fyk, "steelImposed": s.k4 * fyk}
    if exposure in s.k1Exposures:
        out["concreteCharacteristic"] = s.k1 * fck
    return out


def depth_factor(h: float) -> float:
    c = _table().cracking
    if h <= c.thinDepth:
        return c.kThin
    if h >= c.thickDepth:
        return c.kThick
    return c.kThin + (c.kThick - c.kThin) * (h - c.thinDepth) / (c.thickDepth - c.thinDepth)


def min_crack_steel(b: float, h: float, fck: float, fyk: float, tension: bool = False,
                    sigma_s: float | None = None) -> float:  # fmt: skip
    """As,min [mm²] for crack control of a rectangle."""
    c = _table().cracking
    kc = c.kcTension if tension else c.kcBending
    act = b * h if tension else b * h / 2
    fct = design_strength.properties(fck).fctm
    return kc * depth_factor(h) * fct * act / (sigma_s or fyk)


@dataclass(frozen=True)
class CrackWidth:
    wk: float
    sr_max: float
    strain: float
    rho_eff: float
    sigma_s: float


def crack_width(
    b: float,
    h: float,
    d: float,
    a_s: float,
    bar: float,
    cover: float,
    moment: float,
    fck: float,
    es: float = 200000.0,
    spacing: float | None = None,
    long_term: bool = True,
    alpha_e: float | None = None,
) -> CrackWidth:
    """wk [mm] of a rectangle in bending under ``moment`` [N·mm] (quasi-permanent)."""
    c = _table().cracking
    p = design_strength.properties(fck)
    ae = alpha_e if alpha_e is not None else es / p.ecm
    sec = cracked_section(b, d, a_s, moment, ae)
    hc = min(c.effectiveDepthShare * (h - d), (h - sec.x) / 3, h / 2)
    rho = a_s / (b * hc)
    kt = c.ktLong if long_term else c.ktShort
    fct = p.fctm
    strain = (sec.sigma_s - kt * fct / rho * (1 + ae * rho)) / es
    strain = max(strain, c.strainFloor * sec.sigma_s / es)
    if spacing is not None and spacing > c.wideSpacingLimit * (cover + bar / 2):
        sr = c.wideSpacingFactor * (h - sec.x)
    else:
        sr = c.k3 * cover + c.k1Bond * c.k2Bending * c.k4 * bar / rho
    return CrackWidth(sr * strain, sr, strain, rho, sec.sigma_s)


def wmax(exposure: str) -> float | None:
    return _table().cracking.wmax.get(exposure)


def span_depth_limit(
    system: str,
    rho: float,
    rho_comp: float,
    fck: float,
    fyk: float | None = None,
    as_required: float | None = None,
    as_provided: float | None = None,
    span: float | None = None,
    flange_ratio: float = 1.0,
) -> float:
    """The limiting span/effective depth ratio."""
    t = _table().deflection
    k = t.k[system]
    root = math.sqrt(fck)
    rho0 = t.referenceRatioCoefficient * root
    if rho <= rho0:
        ratio = t.base + t.lowCoefficient * root * rho0 / rho
        ratio += t.lowPowerCoefficient * root * (rho0 / rho - 1) ** 1.5
    else:
        ratio = t.base + t.lowCoefficient * root * rho0 / max(rho - rho_comp, 1e-9)
        ratio += t.highCompressionShare * root * math.sqrt(max(rho_comp, 0.0) / rho0)
    ratio *= k
    if fyk and as_required and as_provided:
        sigma_s = fyk * as_required / as_provided * t.stressReference / t.stressSteel
        ratio *= t.stressReference / sigma_s
    if flange_ratio > t.flangeRatio:
        ratio *= t.flangeFactor
    if span is not None:
        limit = t.longFlatSpan if system == "flatSlab" else t.longSpan
        if system != "cantilever" and span > limit:
            ratio *= limit / span
    return ratio
