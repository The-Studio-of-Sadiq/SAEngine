"""Walls by the simplified method (method ``simplifiedWall``, the pack's
``concreteMethods.simplifiedWalls``; alpha 9 C18b, the form of AS 3600:2018 11.5 and 11.6).

- Axial strength per unit length, the resultant within the middle third of the thickness:
  ``φNu = φ (tw - a e - 2 ea) k f'c``, ``ea = Hwe² / (divisor tw)``, e at least
  ``minEccentricityShare`` tw, with Hwe = k Hw (``restrainedK`` for a wall braced and restrained
  at both ends, SAEngine's bracing factor otherwise) and Hwe / tw at most ``slendernessMax``.
  Informative, as the parent's empirical method: the P-M3-M2 surface of the wall governs.
- In-plane shear on the area ``share Lw tw``: Vu = Vuc + Vus at most ``shearMaxShare`` f'c ×
  the area, Vuc = (a - b Hw/Lw) √f'c × the area for Hw/Lw <= 1; above, the lesser of that and
  (a' + b' / (Hw/Lw - 1)) √f'c × the area, at least ``shearLeast`` √f'c × the area;
  Vus = ρw fsy × the area, ρw the lesser of the vertical and horizontal ratios for Hw/Lw <= 1,
  the horizontal one above; φ = ``phiShear``.

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from typing import Any

from saengine.codes import context as code_context

METHOD = "simplifiedWall"


def rules() -> Any | None:
    """The pack's ``concreteMethods.simplifiedWalls`` (None: not the pack's method)."""
    pack = code_context.current()
    if not pack.has("concreteMethods"):
        return None
    from saengine.codes.method_tables import chosen

    return chosen(pack.table("concreteMethods"), "simplifiedWalls", METHOD)


def _cite(key: str) -> str:
    found = code_context.cite("concreteMethods", key)
    return f" ({found})" if found else ""


def _row(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from saengine.design.check import _check

    return _check(*args, **kwargs)


def effective_height(clear_height: float, k: float, r: Any) -> float:
    """Hwe [mm]: ``restrainedK`` Hw for SAEngine's bracing factor 0.8 (braced and restrained
    against rotation), else k Hw."""
    return (r.restrainedK if k == 0.8 else k) * clear_height


def shear_strength(fc: float, height: float, length: float, r: Any) -> float:
    """Vuc / the shear area [MPa] by the aspect ratio Hw / Lw."""
    aw = height / length if length > 0 else 1.0
    root = math.sqrt(fc)
    a, b = r.squatShear
    squat = max(a - b * min(aw, a / b), 0.0) * root
    if aw <= 1.0:
        return squat
    c, e = r.slenderShear
    slender = (c + e / (aw - 1)) * root
    return max(min(squat, slender), r.shearLeast * root)


def axial_rows(geometry: Any, forces: list[Any], fc: float, k: float) -> list[dict[str, Any]]:
    """The slenderness row and, with every compressive force in the middle third, the axial
    strength row (informative)."""
    r = rules()
    t, lw = float(geometry.thickness), float(geometry.length)
    hwe = effective_height(float(geometry.clear_height), k, r)
    rows = [
        _row(
            f"Wall slenderness Hwe / tw{_cite('simplifiedWalls')}",
            hwe / t,
            r.slendernessMax,
            "",
            None,
            f"Hwe = {hwe:.0f} mm ({hwe / geometry.clear_height:.2f} of the clear height), "
            f"tw = {t:.0f} mm; the simplified method holds up to {r.slendernessMax:g}",
        )
    ]
    compressed = [f for f in forces if f.P > 0]
    if not compressed or not all(abs(f.M2) / f.P <= t / 6 for f in compressed):
        return rows
    ea = hwe**2 / (r.additionalDivisor * t)
    worst = None
    for f in compressed:
        e = max(abs(f.M2) / f.P, r.minEccentricityShare * t)
        phi_nu = r.phi * max(t - r.eccentricityFactor * e - 2 * ea, 0.0) * r.strengthShare * fc
        phi_nu *= lw
        ratio = f.P / phi_nu if phi_nu > 0 else math.inf
        if worst is None or ratio > worst[0]:
            worst = (ratio, f, e, phi_nu)
    assert worst is not None
    _, f, e, phi_nu = worst
    row = _row(
        f"Wall axial strength φNu, simplified method{_cite('simplifiedWallAxial')}",
        f.P / 1e3,
        phi_nu / 1e3,
        "kN",
        f.combination,
        f"φNu = {r.phi:g} (tw - {r.eccentricityFactor:g} e - 2 ea) {r.strengthShare:g} f'c Lw, "
        f"e = {e:.1f} mm (>= {r.minEccentricityShare:g} tw), ea = Hwe²/({r.additionalDivisor:g}"
        f" tw) = {ea:.1f} mm; resultant within the middle third; informative, the P-M3-M2 "
        "surface governs",
    )
    row["flag"] = True
    rows.append(row)
    return rows


def shear_row(
    vu: float, t: float, length: float, height: float, fc: float, fy: float, rho_v: float,
    rho_h: float, combination: Any,
) -> dict[str, Any]:  # fmt: skip
    """The in-plane shear row of a wall."""
    r = rules()
    area = r.shearDepthShare * length * t
    aw = height / length if length > 0 else 1.0
    vuc = shear_strength(fc, height, length, r) * area
    rho = min(rho_v, rho_h) if aw <= 1.0 else rho_h
    vus = rho * fy * area
    vmax = r.shearMaxShare * fc * area
    capacity = r.phiShear * min(vuc + vus, vmax)
    return _row(
        f"In-plane shear{_cite('simplifiedWallShear')}",
        vu / 1e3,
        capacity / 1e3,
        "kN",
        combination,
        f"Hw/Lw = {aw:.2f}, area {r.shearDepthShare:g} Lw tw = {area / 1e3:.0f}e3 mm², Vuc = "
        f"{vuc / 1e3:.1f} kN, Vus = ρw fsy × area = {vus / 1e3:.1f} kN (ρw = {rho:.4f}), at most "
        f"{r.shearMaxShare:g} f'c × area = {vmax / 1e3:.1f} kN, φ = {r.phiShear:g}",
    )
