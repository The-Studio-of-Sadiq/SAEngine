"""The characteristic bearing value corrected for the footing's width and depth, and the
settlement by the layer-wise summation with an empirical factor (alpha 9 C20b; the pack's
``foundations.shallow.widthDepthCorrection`` and ``layerwiseSettlement``, as GB 50007-2011
5.2.4 and 5.3.5-5.3.8 give them).

- **Bearing** (:func:`corrected`): fa = fak + ηb γ (b - b0) + ηd γm (d - d0) with b within
  the pack's ``width`` (b0 its low end) [m], d the founding depth below the natural ground
  [m] (no depth term at d <= d0 = ``depthFrom``), (ηb, ηd) of the soil kind the pack (or the
  project's Code Value ``foundations.shallow.widthDepthCorrection.soil``) names, γ = γm the
  pack's ``unitWeight``. Applied to the qa a project gives without a soil report (Project
  Settings > Foundation, read as fak); the soil report's own qa is unchanged (it is computed
  for the footing's width and depth).
- **Settlement** (:func:`layerwise_settlement`): s = ψs Σ p0 / Esi (zi ᾱi - zi-1 ᾱi-1), ᾱ
  the mean vertical stress coefficient under the footing's centre from the surface to z
  (Boussinesq, four corner rectangles, integrated numerically), Esi = oedometricFactor × the
  layer's E (the log's modulus; the oedometric modulus where E is the drained Young's
  modulus: SAEngine practice), to zn = b (a - c ln b) or the log's bottom; ψs by Ēs = Σ Ai /
  Σ (Ai / Esi) from the pack's rows at p0 >= fak (the larger ψs: on the safe side).

Units: kPa, m, MPa (moduli).
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from saengine.codes import context as code_context


def _shallow() -> Any | None:
    try:
        return getattr(code_context.table("foundations"), "shallow", None)
    except Exception:  # noqa: BLE001 - a pack without the table
        return None


def correction_rule() -> Any | None:
    """The pack's ``foundations.shallow.widthDepthCorrection``, or None."""
    found = getattr(_shallow(), "widthDepthCorrection", None)
    return found if getattr(found, "method", None) == "widthDepthCorrection" else None


def settlement_rule() -> Any | None:
    """The pack's ``foundations.shallow.layerwiseSettlement``, or None."""
    found = getattr(_shallow(), "layerwiseSettlement", None)
    return found if getattr(found, "method", None) == "layerwiseSummation" else None


def _cite(key: str) -> str:
    found = code_context.cite("foundations", key)
    return f" ({found})" if found else ""


def corrected(fak: float, b: float, d: float) -> tuple[float, str] | None:
    """(fa [kPa], the note) of a characteristic value fak [kPa] for a footing b wide [m] at
    depth d below the natural ground [m]; None without the pack's rule."""
    r = correction_rule()
    if r is None:
        return None
    eta = r.factors.get(r.soil)
    if eta is None:
        return None
    eta_b, eta_d = (float(x) for x in eta)
    low, high = (float(x) for x in r.width)
    width = min(max(b, low), high)
    gamma = float(r.unitWeight)
    width_term = eta_b * gamma * (width - low)
    depth_term = eta_d * gamma * max(d - float(r.depthFrom), 0.0)
    fa = fak + width_term + depth_term
    note = (
        f"fa = fak + ηb γ (b - {low:g}) + ηd γm (d - {float(r.depthFrom):g}) = {fak:g} + "
        f"{width_term:.1f} + {depth_term:.1f} = {fa:.1f} kPa (soil '{r.soil}': ηb {eta_b:g}, "
        f"ηd {eta_d:g}; b = {width:.2f} m within {low:g}-{high:g} m, d = {d:.2f} m, γ = γm = "
        f"{gamma:g} kN/m³){_cite('widthDepthCorrection')}"
    )
    return fa, note


# ───────────────────────────────────────── settlement ─────────────────────────────────────────


def corner_coefficient(length: float, width: float, z: float) -> float:
    """σz / p under the corner of a uniformly loaded rectangle length × width at depth z
    (Boussinesq; 0.25 at the surface)."""
    if z <= 0:
        return 0.25
    m, n = length / width, z / width
    root = math.sqrt(1 + m * m + n * n)
    first = m * n / root * (1 / (m * m + n * n) + 1 / (1 + n * n))
    second = math.atan(m / (n * root))
    return (first + second) / (2 * math.pi)


def mean_coefficient(b: float, l_: float, z: float, steps: int = 200) -> float:
    """ᾱ: the mean of σz / p under the centre of a b × l footing from the surface to z
    (four corner rectangles b/2 × l/2), by Simpson's rule."""
    if z <= 0:
        return 1.0
    n = steps if steps % 2 == 0 else steps + 1
    h = z / n
    total = 0.0
    for k in range(n + 1):
        w = 1 if k in (0, n) else (4 if k % 2 else 2)
        total += w * 4 * corner_coefficient(l_ / 2, b / 2, k * h)
    return total * h / 3 / z


def _psi(rule: Any, es_bar: float) -> float:
    rows = sorted((float(e), float(a), float(c)) for e, a, c in rule.psi)
    if es_bar <= rows[0][0]:
        return rows[0][1]
    for (e0, a0, _), (e1, a1, _) in pairwise(rows):
        if es_bar <= e1:
            return a0 + (a1 - a0) * (es_bar - e0) / (e1 - e0) if e1 > e0 else a1
    return rows[-1][1]


def layerwise_settlement(
    profile: Any, b: float, l_: float, df: float, q: float, permissible: Any = None
) -> dict[str, Any]:
    """The settlement [mm] of a footing B × L [m] at Df [m] under the net pressure q [kPa]
    (see the module notes), in the shape of :func:`saengine.soil.settlement.settlement`'s
    result (the whole of it as ``immediate``: the code's single figure)."""
    r = settlement_rule()
    b, l_ = min(b, l_), max(b, l_)
    a_coef, c_coef = (float(x) for x in r.depthCoefficients)
    zn = b * (a_coef - c_coef * math.log(b)) if b > 0 else 0.0
    bottom = max(profile.bottom - df, 0.0)
    notes: list[str] = []
    if zn > bottom:
        notes.append(
            f"the depth zn = {zn:.1f} m reaches below the log ({bottom:.1f} m under the base): "
            "deeper soil is not included"
        )
        zn = bottom
    rows: list[dict[str, Any]] = []
    total_area = 0.0
    weighted = 0.0
    s_prime = 0.0
    for layer in profile.layers:
        top = max(layer.top - df, 0.0)
        low = min(layer.bottom - df, zn)
        if low <= top + 1e-9:
            continue
        if not layer.E:
            notes.append(
                f"layer {layer.index + 1}: no modulus (E or SPT), its settlement is left out"
            )
            continue
        es = float(r.oedometricFactor) * float(layer.E)
        z_top = top * mean_coefficient(b, l_, top) if top > 0 else 0.0
        z_low = low * mean_coefficient(b, l_, low)
        area = q * (z_low - z_top)  # p0 (zi ᾱi - zi-1 ᾱi-1) [kPa·m]
        ds = area / (es * 1e3) * 1e3  # kPa·m / kPa -> m -> mm
        s_prime += ds
        total_area += area
        weighted += area / es
        rows.append(
            {
                "index": layer.index,
                "soil": layer.soil_type,
                "top": round((df + top) * 1e3),
                "bottom": round((df + low) * 1e3),
                "immediate": round(ds, 2),
                "consolidation": 0.0,
                "total": round(ds, 2),
                "method": f"layer-wise, Es = {es:.1f} MPa",
            }
        )
    es_bar = total_area / weighted if weighted > 0 else 0.0
    psi = _psi(r, es_bar) if es_bar > 0 else 1.0
    total = psi * s_prime
    notes.append(
        f"s = ψs s' = {psi:.2f} × {s_prime:.1f} = {total:.1f} mm, Ēs = {es_bar:.1f} MPa, zn = "
        f"b ({a_coef:g} - {c_coef:g} ln b) = {zn:.1f} m, ᾱ under the centre (Boussinesq), Es = "
        f"{float(r.oedometricFactor):g} E of the log; ψs at p0 >= fak (on the safe side)"
        f"{_cite('layerwiseSettlement')}"
    )
    for row in rows:
        row["total"] = round(row["total"] * psi, 2)
        row["immediate"] = round(row["immediate"] * psi, 2)
    return {
        "B": round(b * 1e3),
        "L": round(l_ * 1e3),
        "Df": round(df * 1e3),
        "q": round(q, 1),
        "immediate": total,
        "consolidation": 0.0,
        "secondary": 0.0,
        "total": total,
        "C1": 1.0,
        "C2": 1.0,
        "Izp": 0.0,
        "psiS": psi,
        "depth": round(zn * 1e3),
        "layers": rows,
        "notes": notes,
        "consolidated": [],
        "estimated": [],
        "unknownConsolidation": [],
        "allowable": profile.design.allowableSettlement,
        "permissible": permissible,
    }
