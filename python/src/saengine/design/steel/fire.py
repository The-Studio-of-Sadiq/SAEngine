"""Steel members in the standard fire by the simple method: the pack's ``steelFire`` table
(alpha 9 C12; the US pack: AISC 360-22 Appendix 4, the Eurocodes pack: EN 1993-1-2, the IS
pack: IS 800:2007 Section 16). The rating each member is checked for is the fire resistance
rating of its kind (Project Settings > Construction and > Fire resistance, the ratings of
:func:`saengine.design.fire_resistance.ratings_of`); a pack without the table leaves steel
members to the least-size rows of the fire resistance table (the default pack: unchanged).

Per steel beam or column with a rating:

- **Steel temperature** θa at the rating in the standard fire θg = 20 + 345 log10(8 t + 1) (t in
  minutes; the pack's ``heating.curve``) by the lumped heat capacity of the section: unprotected
  Δθa = ksh (Am/V) hnet Δt / (ca ρa), hnet = αc (θg - θa) + εm εf σ ((θg + 273)⁴ - (θa + 273)⁴);
  protected (the project's ``steelFire.protection``: dp, λp, cp, ρp) Δθa = λp (Ap/V) (θg - θa)
  Δt / (dp ca ρa (1 + φ/3)) - (e^(φ/10) - 1) Δθg, φ = cp ρp dp (Ap/V) / (ca ρa). Am/V of the
  member's exposure: columns on four sides, beams on three (the slab covers the top flange);
  ksh = 0.9 [Am/V]b / [Am/V] of unprotected I-sections where the pack takes the shadow effect.
- **Load ratio** μ0 = ηfi × the member's ambient utilisation (its governing strength row;
  ``loadRatio``; SAEngine practice: the ambient resistance stands for the resistance at 20 °C
  in fire, on the safe side where γM,fi < γM).
- **Critical temperature** θcr at μ0 (``critical``: the Eurocode formula, a linear limiting
  temperature, or the temperature where ky,θ = μ0) against θa: members without compression
  (and every member where the pack's ``compression`` is ``critical``).
- **Compression members**: the buckling resistance at θa, χfi A ky,θ fy / γM,fi with λ̄θ = λ̄
  √(ky,θ / kE,θ) and α = 0.65 √(235 / fy) (``eurocode``) or Fn(T) = 0.42^√(Fy(T)/Fe(T)) Fy(T) Ag
  (``aisc``), against ηfi × the ambient compression.

Units: °C, s, mm, N; Am/V in 1/m.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from typing import Any

from saengine.codes import context as code_context

TABLE = "steelFire"
SIGMA = 5.67e-8  # Stefan-Boltzmann [W/m²K⁴] (a physical constant)


def table() -> Any | None:
    """The pack's ``steelFire`` table; None when the pack in force has none."""
    try:
        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - a bare calculation without packs
        return None


def cite(key: str) -> str:
    return code_context.cite(TABLE, key)


# ───────────────────────────────────────── material ─────────────────────────────────────────


def retention(theta: float, t: Any) -> tuple[float, float]:
    """(ky,θ, kE,θ) at ``theta`` [°C]."""
    r = t.retention
    if r.method == "tabulated":
        pts = r.points
        if theta <= pts[0][0]:
            return float(pts[0][1]), float(pts[0][2])
        for (t0, y0, e0), (t1, y1, e1) in itertools.pairwise(pts):
            if theta <= t1:
                f = (theta - t0) / (t1 - t0)
                return y0 + f * (y1 - y0), e0 + f * (e1 - e0)
        return float(pts[-1][1]), float(pts[-1][2])
    if theta <= r.yieldFlat:
        ky = 1.0
    else:
        ky = max((r.yieldZero - theta) / r.yieldSpan, 0.0)
    if theta <= 0:
        ke = 1.0
    elif theta <= r.modulusSplit:
        ke = 1.0 + theta / (r.modulusA * math.log(theta / r.modulusB))
    else:
        ke = r.modulusC * (1 - theta / 1000) / (theta - r.modulusD)
    return min(ky, 1.0), min(max(ke, 0.0), 1.0)


def critical_temperature(mu0: float, t: Any) -> float:
    """θcr [°C] at the load ratio ``mu0``."""
    c = t.critical
    f = [float(x) for x in c.factors]
    mu = min(max(mu0, 1e-3), 1.0)
    if c.method == "eurocode":
        a, b, p, d = f[:4]
        inner = 1 / (b * mu**p) - 1
        theta = a * math.log(inner) + d if inner > 0 else c.floor
    elif c.method == "linear":
        theta = f[0] - f[1] * mu
    else:
        lo, hi = 20.0, 1200.0
        if retention(hi, t)[0] >= mu:
            return hi
        for _ in range(60):
            mid = (lo + hi) / 2
            if retention(mid, t)[0] > mu:
                lo = mid
            else:
                hi = mid
        theta = (lo + hi) / 2
    return min(max(theta, float(c.floor)), 1200.0)


# ───────────────────────────────────────── heating ─────────────────────────────────────────


def section_factor(shape: Any, kind: str, box: bool = False) -> tuple[float, float]:
    """(Am/V, [Am/V]b) [1/m] of ``shape`` exposed as a ``kind`` (columns 4 sides, beams 3);
    ``box``: the box value for both (boxed protection)."""
    d = shape.dims
    beam = kind == "beam"
    fam = shape.family
    if fam in ("I", "channel"):
        contour = 2 * d["d"] + 4 * d["bf"] - 2 * d["tw"] - (d["bf"] if beam else 0.0)
        boxed = 2 * d["d"] + d["bf"] * (1 if beam else 2)
    elif fam == "tee":
        contour = 2 * d["d"] + 2 * d["bf"] - (d["bf"] if beam else 0.0)
        boxed = 2 * d["d"] + d["bf"] * (1 if beam else 2)
    elif fam == "rhs":
        contour = boxed = 2 * d["H"] + d["B"] * (1 if beam else 2)
    elif fam in ("chs", "round"):
        contour = boxed = math.pi * d["D"]
    elif fam in ("angle", "bar"):
        contour = boxed = 2 * (d["d"] + d["b"])
    else:  # lipped channels and Z sections: the developed perimeter, both faces
        contour = 2 * (d["d"] + 2 * d["b"] + 2 * d["c"])
        boxed = 2 * d["d"] + d["b"] * (1 if beam else 2)
    a = shape.area
    am_v, box_v = contour / a * 1e3, boxed / a * 1e3
    return (box_v, box_v) if box else (am_v, box_v)


def gas(t_s: float, t: Any) -> float:
    a, b = (float(x) for x in t.heating.curve)
    return 20 + a * math.log10(b * t_s / 60 + 1)


def steel_temperature(hours: float, am_v: float, box_v: float, family: str, t: Any) -> float:
    """θa [°C] after ``hours`` of the standard fire (protected when the protection has a
    thickness)."""
    h = t.heating
    p = t.protection
    ca, rho = float(h.specificHeat), float(h.density)
    dt = float(h.step)
    steps = math.ceil(hours * 3600 / dt)
    theta = 20.0
    tg_prev = 20.0
    if p.thickness > 0:
        dp = p.thickness / 1e3
        ap_v = box_v if p.encasement == "box" else am_v
        phi = p.specificHeat * p.density * dp * ap_v / (ca * rho)
        for i in range(1, steps + 1):
            tg = gas(i * dt, t)
            rise = p.conductivity * ap_v / (dp * ca * rho) * (tg - theta) * dt / (1 + phi / 3) - (
                math.exp(phi / 10) - 1
            ) * (tg - tg_prev)
            if tg > tg_prev:
                rise = max(rise, 0.0)
            theta += rise
            tg_prev = tg
        return theta
    ksh = 1.0
    if h.shadow and family in ("I", "channel"):
        ksh = min(float(h.shadowFactor) * box_v / am_v, 1.0)
    eps = float(h.emissivity) * float(h.fireEmissivity)
    for i in range(1, steps + 1):
        tg = gas(i * dt, t)
        hnet = float(h.convection) * (tg - theta) + eps * SIGMA * (
            (tg + 273) ** 4 - (theta + 273) ** 4
        )
        theta += ksh * am_v * hnet * dt / (ca * rho)
    return theta


# ───────────────────────────────────────── checks ─────────────────────────────────────────


def chi(lam: float, alpha: float) -> float:
    phi = 0.5 * (1 + alpha * lam + lam**2)
    return min(1.0, 1 / (phi + math.sqrt(max(phi**2 - lam**2, 0.0))))


def ratings(settings: Any) -> dict[str, tuple[float, str]] | None:
    """The ratings by member kind when the pack has the table (None: no steel fire design)."""
    if table() is None or settings is None:
        return None
    from saengine.design.fire_resistance import ratings_of

    found = {k: v for k, v in ratings_of(settings).items() if v[0] > 0}
    return found or None


def _slenderness(shape: Any, lengths: Any) -> float:
    mid = float(lengths.length) / 2
    kx, lx, _ = lengths.effective("x", mid)
    ky, ly, _ = lengths.effective("y", mid)
    r_minor = shape.rz if shape.family in ("angle", "lippedZ") else shape.ry
    return max(kx * lx / shape.rx, ky * ly / r_minor)


def rows(
    shape: Any, steel: Any, lengths: Any, kind: str, checks: Sequence[dict[str, Any]], options: Any
) -> list[dict[str, Any]]:
    """The fire rows of one member ([] without the table or a rating for its kind)."""
    from saengine.design.steel.members import _check, _Worst

    t = table()
    found = getattr(options, "fire", None)
    if t is None or not found or kind not in found:
        return []
    hours, why = found[kind]
    if hours <= 0:
        return []
    strength = [c for c in checks if not c.get("flag") and not str(c["name"]).startswith("Fire")]
    if not strength:
        return []
    governing = max(strength, key=lambda c: c["utilisation"])
    mu0 = float(t.loadRatio) * float(governing["utilisation"])
    am_v, box_v = section_factor(shape, kind, t.protection.encasement == "box")
    theta = steel_temperature(hours, am_v, box_v, shape.family, t)
    ky, ke = retention(theta, t)
    protected = t.protection.thickness > 0
    exposure = (
        f"{t.protection.thickness:g} mm protection (λp {t.protection.conductivity:g} W/mK), "
        f"Ap/V = {box_v if t.protection.encasement == 'box' else am_v:.0f} 1/m"
        if protected
        else f"unprotected, Am/V = {am_v:.0f} 1/m"
    )
    head = f"{hours:g} h ({why}), {exposure}, θa = {theta:.0f} °C (ky = {ky:.3f}, kE = {ke:.3f})"
    out: list[dict[str, Any]] = []
    compression = [c for c in strength if str(c["name"]).startswith("Compression")]
    critical_rule = t.compression == "critical" or not compression
    if critical_rule:
        theta_cr = critical_temperature(mu0, t)
        w = _Worst()
        w.offer(
            theta / theta_cr,
            theta,
            theta_cr,
            governing.get("combination"),
            f"{head}; θcr = {theta_cr:.0f} °C at μ0 = {float(t.loadRatio):g} × "
            f"{float(governing['utilisation']):.3f} = {mu0:.3f} ({governing['name']})",
            cite("critical"),
        )
        out.append(_check("Fire: steel temperature against the critical temperature", w, "°C", 1))
    if compression and t.compression != "critical":
        row = max(compression, key=lambda c: c["utilisation"])
        n_fi = float(t.loadRatio) * float(row["demand"]) * 1e3  # kN -> N
        fy, e = float(steel.fy), float(steel.e)
        kl_r = _slenderness(shape, lengths)
        if t.compression == "eurocode":
            lam = kl_r / (math.pi * math.sqrt(e / fy))
            lam_t = lam * math.sqrt(ky / ke) if ke > 0 else math.inf
            alpha = float(t.alphaFactor) * math.sqrt(235 / fy)
            x = chi(lam_t, alpha)
            cap = x * shape.area * ky * fy / float(t.gammaFire)
            how = f"χfi = {x:.3f} at λ̄θ = {lam_t:.2f} (α = {alpha:.3f}), A ky fy / γM,fi"
        else:
            fy_t, e_t = ky * fy, ke * e
            fe_t = math.pi**2 * e_t / kl_r**2 if kl_r > 0 else math.inf
            fn = float(t.aiscBase) ** math.sqrt(fy_t / fe_t) * fy_t if fe_t > 0 else 0.0
            cap = fn * shape.area / float(t.gammaFire)
            how = f"Fn(T) = {float(t.aiscBase):g}^√(Fy(T)/Fe(T)) Fy(T) = {fn:.0f} MPa, KL/r = {kl_r:.0f}"
        w = _Worst()
        w.offer(
            n_fi / cap if cap > 0 else 99.0,
            n_fi,
            cap,
            row.get("combination"),
            f"{head}; Nfi = {float(t.loadRatio):g} × {float(row['demand']):.1f} kN; {how}",
            cite("compression"),
        )
        out.append(_check("Fire: buckling resistance at temperature", w, "kN", 1e3))
    return out


def method_line() -> str | None:
    """The report paragraph (None without the table)."""
    t = table()
    if t is None:
        return None
    p = t.protection
    protection = (
        f"protected by {p.thickness:g} mm (λp {p.conductivity:g} W/mK, {p.encasement})"
        if p.thickness > 0
        else "unprotected (no protection set in Code Values)"
    )
    return (
        f"Steel in fire ({cite('code')}): the steel temperature at each member's fire rating in "
        f"the standard fire by the lumped heat capacity ({cite('heating')}), {protection}; "
        f"ky,θ and kE,θ ({cite('retention')}); μ0 = {float(t.loadRatio):g} × the ambient "
        f"utilisation; the critical temperature ({cite('critical')}) and, for compression "
        f"members, the buckling resistance at temperature ({cite('compression')})."
    )
