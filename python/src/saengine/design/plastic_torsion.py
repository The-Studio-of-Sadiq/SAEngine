"""Torsion of beams on the plastic torsional modulus with the concrete's share reduced by βt
(alpha 9 C20b; the pack's ``concreteMethods.torsion`` method ``plasticModulus``, as GB
50010-2010 6.4.1-6.4.8 and 9.2.10 give them).

At every station with a torque (Tu, Vu, Mu of the combination):

- Wt = b² (3h - b) / 6 of the rectangle (b the shorter side), h0 the effective depth.
- Section: Vu/(b h0) + Tu/(sectionWtShare Wt) at most τc,max of the pack's shear group
  (0.25 βc fc there).
- No calculation where Vu/(b h0) + Tu/Wt <= plainLimit fctd: the least links only.
- βt = a / (1 + b Vu Wt / (Tu b h0)) within ``betaTRange``.
- The closed links: Ast1/s = (Tu - concreteShare βt fctd Wt) / (steelFactor √ζ fyv Acor)
  for the torque (one leg) plus Asv/s = (Vu - (shearBase - βt) shearConcrete fctd b h0) /
  (fyv h0) for the shear (all legs), against one leg of the provided link; ζ the pack's
  design value; Acor = bcor hcor, ucor = 2 (bcor + hcor) inside the links.
- The longitudinal torsion steel Astl = ζ fyv Ast1 ucor / (fy s), at least the least ratio
  a √(Tu/(Vu b)) fctd/fy b h: reported (flagged) in addition to the flexural steel, as the
  side bars SAEngine lays out are not split between bending and torsion.
- The least links Asv/(b s) >= minLinks fctd / fyv.

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.design.tabulated_shear import (
    TORSION_FLOOR,
    _group,
    _paren,
    stirrup_yield,
    tau_c_max,
)
from saengine.design.tabulated_shear import rules as shear_rules

METHOD = "plasticModulus"


def rules() -> Any | None:
    """The pack's ``concreteMethods.torsion`` of this method, or None."""
    return _group("torsion", METHOD)


def plastic_modulus(b: float, h: float) -> float:
    """Wt [mm³] = b² (3h - b) / 6 of a rectangle, b the shorter side."""
    x, y = min(b, h), max(b, h)
    return x * x * (3 * y - x) / 6


def beta_t(tu: float, vu: float, wt: float, b: float, h0: float, r: Any) -> float:
    """βt of the concrete's torsion share."""
    a, k = r.betaT
    lo, hi = r.betaTRange
    if tu <= 0:
        return hi
    value = a / (1 + k * vu * wt / (tu * b * h0)) if b * h0 > 0 else lo
    return min(max(value, lo), hi)


def _row(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from saengine.design.check import _check

    return _check(*args, **kwargs)


def torsion_rows(
    section: Any,
    cover: float,
    stirrups: tuple[float, int, float] | None,
    points: list[tuple[float, float, float, str, str]],
) -> list[dict[str, Any]]:
    """The torsion rows of a beam at its governing station (see the module notes).
    ``points``: (Tu [N·mm], Vu [N], Mu [N·mm], combination, where); ``stirrups``: (dia, legs,
    spacing) of the links. [] without the method or a torque."""
    from saengine.design import design_strength
    from saengine.design.rc import bar_area

    r = rules()
    sr = shear_rules()
    if r is None or sr is None or not points or max(abs(p[0]) for p in points) < TORSION_FLOOR:
        return []
    b, h, fc = float(section.width), float(section.depth), float(section.fc)
    try:
        h0 = float(section.effective_depth(top=False))
    except Exception:  # noqa: BLE001 - no bottom bars: the top's
        h0 = float(section.effective_depth(top=True))
    tdia = float(getattr(section, "transverse_dia", None) or (stirrups[0] if stirrups else 8.0))
    bcor = b - 2 * (cover + tdia)
    hcor = h - 2 * (cover + tdia)
    if bcor <= 0 or hcor <= 0:
        return [
            _row(
                f"Torsion{_paren('torsion')}", 0.0, 0.0, "kN·m", None, "not checked: no room",
                flag=True,
            )
        ]  # fmt: skip
    acor, ucor = bcor * hcor, 2 * (bcor + hcor)
    wt = plastic_modulus(b, h)
    ftd = design_strength.fctd(fc)
    fyv = stirrup_yield(section.fy, sr)
    fy = design_strength.fyd(section.fy)
    tmax = tau_c_max(fc, sr)
    zeta = min(max(r.zeta, r.zetaRange[0]), r.zetaRange[1])

    def section_stress(p: tuple[float, float, float, str, str]) -> float:
        return abs(p[1]) / (b * h0) + abs(p[0]) / (r.sectionWtShare * wt)

    def need(p: tuple[float, float, float, str, str]) -> tuple[float, float, float]:
        """(Ast1/s one leg for T, Asv/s all legs for V, βt)."""
        tu, vu = abs(p[0]), abs(p[1])
        bt = beta_t(tu, vu, wt, b, h0, r)
        torque = max(tu - r.concreteShare * bt * ftd * wt, 0.0)
        ast1 = torque / (r.steelFactor * math.sqrt(zeta) * fyv * acor)
        shear_part = max(vu - (r.shearBase - bt) * r.shearConcrete * ftd * b * h0, 0.0)
        asv = shear_part / (fyv * h0)
        return ast1, asv, bt

    legs = int(stirrups[1]) if stirrups else 2
    worst = max(points, key=section_stress)
    rows = [
        _row(
            f"Torsion: section{_paren('torsionSection')}",
            section_stress(worst),
            tmax,
            "MPa",
            worst[3],
            f"V/(b h0) + T/({r.sectionWtShare:g} Wt), Wt = b²(3h - b)/6 = {wt / 1e6:.2f}e6 mm³, "
            f"T = {abs(worst[0]) / 1e6:.2f} kN·m, V = {abs(worst[1]) / 1e3:.1f} kN; at most "
            f"τc,max = {tmax:.2f} MPa; {worst[4]}",
        )
    ]
    governing = max(points, key=lambda p: need(p)[0] + need(p)[1] / max(legs, 1))
    plain = abs(governing[1]) / (b * h0) + abs(governing[0]) / wt
    if plain <= r.plainLimit * ftd:
        rows.append(
            _row(
                f"Torsion: no calculation needed{_paren('torsion')}",
                plain,
                r.plainLimit * ftd,
                "MPa",
                governing[3],
                f"V/(b h0) + T/Wt <= {r.plainLimit:g} ft = {r.plainLimit * ftd:.2f} MPa: the "
                f"least links Asv/(b s) >= {r.minLinks:g} ft/fyv; {governing[4]}",
                flag=True,
            )
        )
    else:
        ast1, asv, bt = need(governing)
        per_leg = ast1 + asv / max(legs, 1)
        provided = bar_area(stirrups[0]) / stirrups[2] if stirrups and stirrups[2] else 0.0
        rows.append(
            _row(
                f"Torsion: closed links{_paren('torsionLinks')}",
                per_leg,
                provided,
                "mm²/mm",
                governing[3],
                f"one leg: Ast1/s = (T - {r.concreteShare:g} βt ft Wt) / ({r.steelFactor:g} √ζ "
                f"fyv Acor) = {ast1:.3f} + Asv/(n s) = {asv:.3f}/{legs} for V = (V - "
                f"({r.shearBase:g} - βt) {r.shearConcrete:g} ft b h0)/(fyv h0); βt = {bt:.2f}, "
                f"ζ = {zeta:g}, Acor = {acor / 1e3:.0f}e3 mm²; "
                + (
                    f"{stirrups[0]:g} mm links at {stirrups[2]:g} mm"
                    if stirrups
                    else "no closed links"
                )
                + f"; {governing[4]}",
            )
        )
        astl = zeta * fyv * ast1 * ucor / fy if fy > 0 else 0.0
        a, cap = r.minLongitudinal
        ratio = min(abs(governing[0]) / (abs(governing[1]) * b), cap) if governing[1] else cap
        least = a * math.sqrt(max(ratio, 0.0)) * ftd / fy * b * h if fy > 0 else 0.0
        rows.append(
            _row(
                f"Torsion: longitudinal steel{_paren('torsionLongitudinal')}",
                max(astl, least),
                max(astl, least),
                "mm²",
                governing[3],
                f"Astl = ζ fyv Ast1 ucor / (fy s) = {astl:.0f} mm², at least {a:g} √(T/(V b)) "
                f"ft/fy b h = {least:.0f} mm² (T/(V b) at most {cap:g}), round the perimeter in "
                "addition to the flexural steel (not split from the side bars: check the layout)",
                flag=True,
            )
        )
    if stirrups and stirrups[2]:
        total = legs * bar_area(stirrups[0]) / stirrups[2]
        rows.append(
            _row(
                f"Torsion: least links{_paren('torsionLinks')}",
                r.minLinks * ftd / fyv * b,
                total,
                "mm²/mm",
                None,
                f"Asv/(b s) >= {r.minLinks:g} ft/fyv",
            )
        )
    return rows


def method_line() -> str:
    """The report's line of the method."""
    r = rules()
    return (
        f"torsion on Wt = b²(3h - b)/6{_paren('torsion')}: the section V/(b h0) + T/"
        f"({r.sectionWtShare:g} Wt) <= τc,max, T <= {r.concreteShare:g} βt ft Wt + "
        f"{r.steelFactor:g} √ζ fyv Ast1 Acor/s with the shear's concrete share × ({r.shearBase:g}"
        f" - βt), the longitudinal Astl = ζ fyv Ast1 ucor/(fy s)"
    )
