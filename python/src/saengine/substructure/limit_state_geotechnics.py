"""Limit state geotechnical design by partial factor sets and design approaches (the pack's
``geotechnicalMethods``).

Units: kN, kPa, m, degrees.

- Factor sets: actions A (γG unfavourable / favourable, γQ), soil parameters M (γφ' on
  tan φ', γc', γcu, γqu, γγ), resistances R of spread foundations (bearing, sliding, earth)
  and of piles by kind (γb, γs, γt, γs,t). A design approach is a list of combinations of
  sets (:func:`combinations`); the pack names the one in force (``designApproach``), a project
  may override it.
- Bearing resistance (:func:`bearing_resistance`, method ``effectiveArea``) on the effective
  base B' = B - 2 eB, L' = L - 2 eL, with the design parameters of the set M:
  drained ``R/A' = c' Nc bc sc ic + q' Nq bq sq iq + ½ γ' B' Nγ bγ sγ iγ``,
  Nq = e^(π tan φ') tan²(45° + φ'/2), Nc = (Nq - 1) cot φ', Nγ = f (Nq - 1) tan φ';
  sq = 1 + (B'/L') sin φ', sγ = 1 - c B'/L', sc = (sq Nq - 1)/(Nq - 1);
  inclination with m = (2 + B'/L')/(1 + B'/L') (load along B'): iq = (1 - H/(V + A' c' cot
  φ'))^m, iγ = (...)^(m+1), ic = iq - (1 - iq)/(Nc tan φ'); base inclination α:
  bq = bγ = (1 - α tan φ')², bc = bq - (1 - bq)/(Nc tan φ');
  undrained ``R/A' = (π + 2) cu bc sc ic + q``, bc = 1 - 2α/(π + 2), sc = 1 + c B'/L',
  ic = ½ (1 + √(1 - H/(A' cu))). Rd = R / γR,v.
- Sliding (:func:`sliding_resistance`): drained Rd = V'd tan δd / γR,h with δd the pack's share
  of φ'cv,d (cast in place, precast); undrained Rd = A' cu,d / γR,h, at most ``undrainedShare``
  Vd where water or air can reach the interface.
- Piles (:func:`pile_resistance_from_tests`): Rc,k = min(Rc,m,mean / ξ1, Rc,m,min / ξ2) from
  static load tests, min(mean / ξ3, min / ξ4) from ground tests (ξ by the number of tests,
  interpolated linearly between the pack's rows; ÷ ``stiffDivisor`` for stiff structures, ξ1
  and ξ3 not below 1); Rc,d = Rc,k / γt (or the base and shaft parts by γb, γs).

Settlement: the code gives no method; SAEngine keeps its own (:mod:`saengine.soil.bearing`).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context


def rules() -> Any | None:
    """The pack's ``geotechnicalMethods``, or None when the pack designs foundations by
    allowable stresses (the default pack)."""
    pack = code_context.current()
    return pack.table("geotechnicalMethods") if pack.has("geotechnicalMethods") else None


def combinations(approach: str | None = None) -> list[Any]:
    r = rules()
    return list(r.approaches[approach or r.designApproach])


@dataclass(frozen=True)
class DesignParameters:
    phi: float  # degrees
    c: float
    cu: float | None
    gamma: float


def design_parameters(phi_k: float, c_k: float, cu_k: float | None, gamma_k: float,
                      material_set: str) -> DesignParameters:  # fmt: skip
    """The design parameters of the set M (φ'd = atan(tan φ'k / γφ'))."""
    m = rules().materials[material_set]
    phi = math.degrees(math.atan(math.tan(math.radians(phi_k)) / m.tanPhi))
    return DesignParameters(
        phi, c_k / m.cohesion, None if cu_k is None else cu_k / m.undrained, gamma_k / m.weight
    )


def design_actions(g: float, q: float, action_set: str, favourable: bool = False) -> float:
    """Vd of permanent g and variable q (q at 0 when favourable)."""
    a = rules().actions[action_set]
    if favourable:
        return a.permanentFavourable * g
    return a.permanentUnfavourable * g + a.variableUnfavourable * q


def bearing_factors(phi: float) -> tuple[float, float, float]:
    """(Nq, Nc, Nγ) drained."""
    b = rules().bearing
    t = math.tan(math.radians(phi))
    nq = math.exp(math.pi * t) * math.tan(math.radians(45 + phi / 2)) ** 2
    nc = (nq - 1) / t if t > 0 else math.pi + 2
    ng = b.nGammaFactor * (nq - 1) * t
    return nq, nc, ng


def bearing_resistance(
    b: float,
    l_: float,
    params: DesignParameters,
    q: float,
    gamma_eff: float | None = None,
    v: float = 0.0,
    h: float = 0.0,
    e_b: float = 0.0,
    e_l: float = 0.0,
    base_angle: float = 0.0,
    drained: bool = True,
) -> dict[str, float]:
    """R/A' [kPa], A' [m²] and R [kN] of a rectangular base (see the module notes)."""
    rb = rules().bearing
    bp, lp = max(b - 2 * e_b, 0.0), max(l_ - 2 * e_l, 0.0)
    if bp > lp:
        bp, lp = lp, bp
    area = bp * lp
    if area <= 0:
        return {"q": 0.0, "area": 0.0, "R": 0.0}
    ratio = bp / lp
    alpha = math.radians(base_angle)
    if not drained:
        cu = params.cu or 0.0
        bc = 1 - 2 * alpha / (math.pi + 2)
        sc = 1 + rb.undrainedShape * ratio
        ic = 0.5 * (1 + math.sqrt(max(0.0, 1 - h / (area * cu)))) if cu > 0 else 0.0
        resist = (math.pi + 2) * cu * bc * sc * ic + q
        return {
            "q": resist,
            "area": area,
            "R": resist * area,
            "Nc": math.pi + 2,
            "sc": sc,
            "ic": ic,
        }
    phi = params.phi
    tan = math.tan(math.radians(phi))
    nq, nc, ng = bearing_factors(phi)
    sq = 1 + ratio * math.sin(math.radians(phi))
    sg = 1 - rb.gammaShape * ratio
    sc = (sq * nq - 1) / (nq - 1)
    m = (2 + ratio) / (1 + ratio)
    denom = v + area * params.c * (1 / tan if tan > 0 else 0.0)
    base = 1 - h / denom if denom > 0 else 1.0
    base = max(base, 0.0)
    iq, ig = base**m, base ** (m + 1)
    ic = iq - (1 - iq) / (nc * tan) if tan > 0 else iq
    bq = (1 - alpha * tan) ** 2
    bc = bq - (1 - bq) / (nc * tan) if tan > 0 else bq
    g = params.gamma if gamma_eff is None else gamma_eff
    resist = params.c * nc * bc * sc * ic + q * nq * bq * sq * iq + 0.5 * g * bp * ng * bq * sg * ig
    return {"q": resist, "area": area, "R": resist * area, "Nq": nq, "Nc": nc, "Ngamma": ng,
            "sq": sq, "sgamma": sg, "sc": sc, "iq": iq, "igamma": ig, "ic": ic}  # fmt: skip


def bearing_design(r_k: float, resistance_set: str) -> float:
    return r_k / rules().spreadResistances[resistance_set].bearing


def sliding_resistance(
    vd: float,
    resistance_set: str,
    phi_cv: float | None = None,
    material_set: str = "M1",
    cast_in_place: bool = True,
    area: float | None = None,
    cu: float | None = None,
    water_at_interface: bool = False,
) -> float:
    """Rd [kN] against sliding (drained with φ'cv,k, else undrained with cu,k)."""
    r = rules()
    s = r.sliding
    gamma_h = r.spreadResistances[resistance_set].sliding
    m = r.materials[material_set]
    if phi_cv is not None:
        phi_d = math.atan(math.tan(math.radians(phi_cv)) / m.tanPhi)
        delta = (s.castInPlace if cast_in_place else s.precast) * phi_d
        return vd * math.tan(delta) / gamma_h
    rd = (area or 0.0) * (cu or 0.0) / m.undrained / gamma_h
    if water_at_interface:
        rd = min(rd, s.undrainedShare * vd)
    return rd


def _interpolate(rows: list[tuple[float, float, float]], n: int) -> tuple[float, float]:
    if n <= rows[0][0]:
        return rows[0][1], rows[0][2]
    for (n0, a0, b0), (n1, a1, b1) in itertools.pairwise(rows):
        if n <= n1:
            t = (n - n0) / (n1 - n0)
            return a0 + t * (a1 - a0), b0 + t * (b1 - b0)
    return rows[-1][1], rows[-1][2]


def correlation_factors(
    n: int, load_tests: bool = True, stiff: bool = False
) -> tuple[float, float]:
    """(ξ1, ξ2) or (ξ3, ξ4) for n tests or profiles."""
    c = rules().correlation
    a, b = _interpolate(c.loadTests if load_tests else c.groundTests, n)
    if stiff:
        a, b = max(1.0, a / c.stiffDivisor), b / c.stiffDivisor
    return a, b


def pile_resistance_from_tests(measured: list[float], load_tests: bool = True,
                               stiff: bool = False) -> float:  # fmt: skip
    """Rc,k [kN] from the measured (or calculated) resistances of n tests."""
    n = len(measured)
    if n == 0:
        return 0.0
    xa, xb = correlation_factors(n, load_tests, stiff)
    mean = sum(measured) / n
    return min(mean / xa, min(measured) / xb)


def pile_design_resistance(
    r_k: float, kind: str, resistance_set: str, part: str = "total"
) -> float:
    """Rd [kN] = Rk / γ of the set (``part``: total, base, shaft, tension)."""
    sets = rules().pileResistances
    table = sets.get(kind) or sets.get("bored")
    return r_k / getattr(table[resistance_set], part)


def pile_resistance_sets() -> list[tuple[str, str]]:
    """(combination label, R set of piles) of the design approach in force."""
    out = []
    r = rules()
    for k, combo in enumerate(combinations()):
        out.append((f"{r.designApproach}" + (f"-C{k + 1}" if len(r.approaches[r.designApproach]) > 1 else ""),
                    combo.pileResistances or combo.resistances))  # fmt: skip
    return out


def load_test_summary(results: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    """The characteristic and design compression resistance of a pile type from its initial
    static load tests' ultimate (failure) loads, by the design approach in force; None when
    the pack does not cover limit state geotechnics or no test reached a failure load."""
    r = rules()
    if r is None or r.correlation is None:
        return None
    measured = [x["ultimate"] for x in results
                if x.get("kind") == "compression" and not x.get("group") and x.get("ultimate")]  # fmt: skip
    if not measured:
        return None
    rk = pile_resistance_from_tests(measured, load_tests=True)
    xi1, xi2 = correlation_factors(len(measured), load_tests=True)
    design = {label: round(pile_design_resistance(rk, kind, rset), 1)
              for label, rset in pile_resistance_sets()}  # fmt: skip
    clause = code_context.cite("geotechnicalMethods", "pileLoadTests")
    return {
        "tests": len(measured),
        "xi1": round(xi1, 3),
        "xi2": round(xi2, 3),
        "Rck": round(rk, 1),
        "Rcd": design,
        "note": (
            f"Rc,k = min(mean/ξ1, min/ξ2) = {rk:.0f} kN from {len(measured)} test(s), "
            f"ξ1 = {xi1:.2f}, ξ2 = {xi2:.2f}; Rc,d = Rc,k/γt by "
            + ", ".join(f"{k} {v:.0f} kN" for k, v in design.items())
            + (f" ({clause})" if clause else "")
        ),
    }
