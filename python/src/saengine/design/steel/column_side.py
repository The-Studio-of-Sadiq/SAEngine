"""A steel column's web and flange under the concentrated flange forces of a beam, under the
limit state methods: the method a pack picks with ``steelLimitState.columnSide`` (alpha 9 C12).
:func:`saengine.design.steel_connections.column_side_checks` hands the column side to
:func:`checks` here when the pack chooses a method; without one it keeps the default pack's
rules (the column side of the flange forces, Sec 10.10.10).

- ``effectiveWidth`` (the Eurocodes pack, EN 1993-1-8 6.2.6.1-6.2.6.3 and 4.10): the column web
  in transverse compression ω kwc beff twc fy / γM0 and its buckling ω kwc ρ beff twc fy /
  γM1, beff = tfb + 2√2 ab + 5 (tfc + s), ω from the panel's transformation parameter (β = 1
  one-sided, β = 2 beams on both flanges bending the same way: conservative), kwc from the
  column's axial stress, ρ from λp = 0.932 √(beff dwc fy / (E twc²)); the web in transverse
  tension ω beff twc fy / γM0; the unstiffened column flange of a welded joint beff = twc + 2 s
  + 7 k tfc (k = tfc / tfb <= 1, the plate's fy taken as the column's) carrying beff tfb fy /
  γM0; the web panel in shear 0.9 fy Avc / (√3 γM0) (a supplementary web plate adds bs twc).
- ``dispersion`` (the IS pack, IS 800:2007 8.7.4, 8.7.3.1, 8.4): web bearing (b1 + n2) tw fyw /
  γm0, n2 = 2 × 2.5 (tf + r) through the flange and root; web buckling (b1 + n1) tw fcd, n1 = D
  (45° to mid-depth both ways), fcd of curve c at λ = 2.5 d / tw; the panel as web shear dc tw
  fy / (√3 γm0). IS 800 has no column flange bending rule: the default pack's flange local
  bending stays (named after it in the note).

The stiffeners: a stiffened column side is flagged as taken by the stiffeners; their own design
under these methods is not covered (stated).

Units: N, mm, MPa.
"""

from __future__ import annotations

import math
from typing import Any


def table() -> Any | None:
    """The pack's ``steelLimitState.columnSide``; None: the default pack's rules."""
    from saengine.design.steel.limit_state import rules

    t = rules()
    return getattr(t, "columnSide", None) if t is not None else None


def _cite(key: str) -> str:
    """The group's clause ``key`` (the full reference, the code's name included)."""
    t = table()
    return str(t.clauses.get(key, "")) if t is not None else ""


def shear_area(column: Any) -> float:
    """Avc of a rolled I column, A - 2 b tf + (tw + 2 r) tf (at least the web's h tw)."""
    tf, tw, r = column.tf, column.tw, column.r
    avc = column.A - 2 * column.b * tf + (tw + 2 * r) * tf
    return max(avc, (column.h - 2 * tf) * tw)


def omega(beff: float, tw: float, avc: float, double_sided: bool) -> tuple[float, str]:
    """ω of the web (EN 1993-1-8 Table 6.3): β = 1 → ω1, β = 2 → ω2."""
    x = beff * tw / avc if avc > 0 else 0.0
    if double_sided:
        return 1 / math.sqrt(1 + 5.2 * x**2), "ω2 (β = 2)"
    return 1 / math.sqrt(1 + 1.3 * x**2), "ω1 (β = 1)"


def rho(beff: float, dwc: float, tw: float, fy: float, e: float) -> tuple[float, float]:
    """(ρ, λp) of the web's plate buckling under transverse compression."""
    lam = 0.932 * math.sqrt(beff * dwc * fy / (e * tw**2))
    return (1.0 if lam <= 0.72 else (lam - 0.2) / lam**2), lam


def chi(lam: float, alpha: float) -> float:
    """χ of a buckling curve with imperfection factor ``alpha`` at λ̄ ``lam``."""
    if lam <= 0.2:
        return 1.0
    phi = 0.5 * (1 + alpha * (lam - 0.2) + lam**2)
    return min(1.0, 1 / (phi + math.sqrt(max(phi**2 - lam**2, 0.0))))


def checks(
    force: float,
    comb: str | None,
    column: Any,
    column_material: Any,
    bearing_length: float,
    stiffened: bool,
    *,
    delivering_thickness: float | None = None,
    double_sided: bool = False,
    axial_ratio: float = 0.0,
    doubler: float = 0.0,
    weld: float = 6.0,
    end_distance: float | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """The column side rows and notes of the pack's method (the format of
    :func:`saengine.design.steel_connections.column_side_checks`)."""
    from saengine.design.steel_connections import _check, flange_local_bending

    t = table()
    fy, e = float(column_material.fy), float(column_material.E)
    tf, tw, dc, r = column.tf, column.tw, column.h, column.r
    tfb = delivering_thickness or tf
    g0 = float(t.gamma)
    g1 = float(t.gammaBuckling or t.gamma)
    notes = [
        "column side: the beam flange forces on the column "
        + ("from beams on both flanges" if double_sided else "(one-sided joint)")
        + f", by {_cite('code') or 'the pack'}'s method"
    ]
    local: list[tuple[str, float, str]] = []
    v_panel = force * (2 if double_sided else 1)
    if t.method == "effectiveWidth":
        s = r
        ab = 0.707 * weld
        beff = tfb + 2 * math.sqrt(2) * ab + 5 * (tf + s)
        avc = shear_area(column)
        if doubler > 0:
            avc += (dc - 2 * (tf + r)) * tw
        w, w_note = omega(beff, tw, avc, double_sided)
        sigma = axial_ratio * fy
        limit = float(t.stressLimit or 0.7)
        kwc = 1.0 if sigma <= limit * fy else max(1.7 - sigma / fy, 0.0)
        dwc = dc - 2 * (tf + s)
        rh, lam = rho(beff, dwc, tw, fy, e)
        base = w * kwc * beff * tw * fy
        crush, buckle = base / g0, rh * base / g1
        how = (
            f"beff = tfb + 2√2 ab + 5 (tfc + s) = {beff:.0f} mm, {w_note} = {w:.3f}, kwc = "
            f"{kwc:.2f}, Avc = {avc:.0f} mm²"
        )
        local.append(
            ("column web in transverse compression", crush, f"{_cite('webCompression')}: {how}")
        )
        local.append(
            (
                "column web buckling (transverse compression)",
                buckle,
                f"{_cite('webCompression')}: ρ = {rh:.3f} at λp = {lam:.3f}, {how}",
            )
        )
        local.append(
            (
                "column web in transverse tension",
                w * beff * tw * fy / g0,
                f"{_cite('webTension')}: ω beff twc fy / γM0, {how}",
            )
        )
        k = min(tf / tfb, 1.0) if tfb > 0 else 1.0
        bfc = tw + 2 * s + float(t.flangeSpread or 7.0) * k * tf
        local.append(
            (
                "column flange (welded, unstiffened)",
                bfc * tfb * fy / g0,
                (
                    f"{_cite('flange')}: beff = twc + 2s + {float(t.flangeSpread or 7.0):g} k tfc = "
                    f"{bfc:.0f} mm, k = {k:.2f}, × tfb fy / γM0 (the plate's fy taken as the column's)"
                ),
            )
        )
        panel = float(t.panelShare or 0.9) * fy * avc / (math.sqrt(3) * g0)
        panel_note = (
            f"{_cite('panel')}: {float(t.panelShare or 0.9):g} fy Avc / (√3 γM0), Avc = {avc:.0f}"
            " mm²" + (" incl. bs twc of the supplementary web plate" if doubler > 0 else "")
        )
    else:
        slope = float(t.bearingSlope or 2.5)
        n2 = 2 * slope * (tf + r)
        b1 = bearing_length or tfb
        local.append(
            (
                "column web bearing",
                (b1 + n2) * tw * fy / g0,
                (
                    f"{_cite('webBearing')}: (b1 + n2) tw fyw / γm0, b1 = {b1:.0f} mm, n2 = 2 × "
                    f"{slope:g} (tf + r) = {n2:.0f} mm"
                ),
            )
        )
        d = dc - 2 * (tf + r)
        lam = float(t.webSlenderness or 2.5) * d / tw / math.pi * math.sqrt(fy / e)
        curve = t.bucklingCurve or "c"
        x = chi(lam, float(t.alpha.get(curve, 0.49)))
        fcd = x * fy / g0
        n1 = dc
        local.append(
            (
                "column web buckling",
                (b1 + n1) * tw * fcd,
                (
                    f"{_cite('webBuckling')}: (b1 + n1) tw fcd, n1 = D = {n1:.0f} mm, fcd = "
                    f"{fcd:.0f} MPa (curve {curve}, λ = {float(t.webSlenderness or 2.5):g} d / tw, "
                    f"λ̄ = {lam:.2f})"
                ),
            )
        )
        cap, note = flange_local_bending(tf, fy, end_distance)
        local.append(
            (
                "column flange local bending",
                cap,
                f"{note} (the default pack's rule: {_cite('code') or 'the pack'} gives none)",
            )
        )
        panel = dc * tw * fy / (math.sqrt(3) * g0)
        if doubler > 0:
            panel += (dc - 2 * (tf + r)) * doubler * fy / (math.sqrt(3) * g0)
        panel_note = f"{_cite('panel')}: the web in shear Av fyw / (√3 γm0), Av = dc tw" + (
            " plus the doubler plate" if doubler > 0 else ""
        )
    out = [
        _check(
            name,
            force / 1e3,
            cap / 1e3,
            "kN",
            comb,
            note + ("; taken by the stiffeners" if stiffened else ""),
            flag=stiffened,
        )
        for name, cap, note in local
    ]
    out.append(
        _check("column panel zone shear", v_panel / 1e3, panel / 1e3, "kN", comb, panel_note)
    )
    if stiffened:
        notes.append(
            "column stiffeners: taken to carry the flange forces; their design by this method "
            "is not covered (not checked)"
        )
    return out, notes
