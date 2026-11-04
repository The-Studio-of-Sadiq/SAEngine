"""Torsion of steel members by elastic stresses under partial factors: the method
``elasticStresses`` a pack picks with ``steelLimitState.torsion`` (alpha 9 C12; the Eurocodes
pack: EN 1993-1-1 6.2.7 with the yield criterion 6.2.1(5); the IS pack: the same method as
SAEngine practice, IS 800:2007 giving no torsion rule of its own).

The limit state steel members (:func:`saengine.design.steel.limit_state.check_member`) add these
rows when the analysis gives the member a torque:

- **Open sections** (I-shapes, channels, tees, angles, bars, rounds): the twist along the member
  from the internal torque by the warping torsion of thin-walled members (the solution of
  :func:`saengine.design.steel.torsion.solve_warping`, the ends free to warp unless the member's
  options restrain them), the St. Venant shear G t φ', the warping normal stress E Wn φ'' and the
  warping shear E Sw φ''' / t at the critical points.
- **Hollow sections**: St. Venant torsion only, Bredt's shear flow τt = T / (2 A0 t).

Checks: the yield criterion (σ / fd)² + 3 (τ / fd)² <= 1 with fd = fy / γ, σ the sum of the
axial, both bending and the warping normal stresses at the flange tip and τ the larger of the
flange and web shear (the shear forces' and the torsion's added); and the shear resistance
reduced for the torsional shear (I-shapes √(1 - τt / (1.25 fy / (√3 γ))), channels the same
less τw / (fy / (√3 γ)), hollow sections 1 - τt / (fy / (√3 γ))) against the shear force along
the depth. Torque below the pack's ``neglect`` share of the St. Venant resistance gives flagged
rows (torsion small).

Units: mm, N, N·mm, MPa.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.steel import torsion as tor


def table() -> Any | None:
    """The pack's ``steelLimitState.torsion`` (method ``elasticStresses``); None: not chosen."""
    from saengine.design.steel.limit_state import rules

    t = rules()
    found = getattr(t, "torsion", None) if t is not None else None
    if found is None or getattr(found, "method", None) != "elasticStresses":
        return None
    return found


def _cite(key: str) -> str:
    """The group's clause ``key`` (the full reference, the code's name included)."""
    t = table()
    return str(t.clauses.get(key, "")) if t is not None else ""


def shear_modulus(e: float) -> float:
    """G of the limit state method (its ``shearModulus``, else the member resistances'), else
    the pack's steel materials' G."""
    from saengine.design.steel.limit_state import member_resistance, rules

    for source in (rules(), member_resistance()):
        g = getattr(source, "shearModulus", None) if source is not None else None
        if g:
            return float(g)
    try:
        return float(code_context.table("materials").steelShearModulus)
    except Exception:  # noqa: BLE001 - a bare calculation: G = E / 2.6 (ν = 0.3)
        return e / 2.6


def hollow_area(shape: Any) -> float:
    """A0, the area inside the wall's centreline of an RHS or CHS [mm²]."""
    d = shape.dims
    t = d["t"]
    if shape.family == "chs":
        return math.pi * (d["D"] - t) ** 2 / 4
    return (d["B"] - t) * (d["H"] - t)


def _thickest(shape: Any) -> float:
    d = shape.dims
    if shape.family in ("I", "channel", "tee"):
        return max(d["tf"], d["tw"])
    if shape.family == "angle":
        return d["t"]
    if shape.family == "bar":
        return min(d["d"], d["b"])
    if shape.family == "round":
        return d["D"] / 2
    return d.get("t", 0.0)


def st_venant_resistance(shape: Any, fy: float, gamma: float, g: float) -> float:
    """The St. Venant torsional resistance [N·mm]: hollow 2 A0 t τd, open τd J / t_max, τd = fy /
    (√3 γ) (the torque at which the St. Venant shear reaches the shear strength)."""
    tau = fy / (math.sqrt(3) * gamma)
    if shape.family in ("rhs", "chs"):
        return 2 * hollow_area(shape) * shape.dims["t"] * tau
    t = _thickest(shape)
    return tau * shape.j / t if t > 0 else 0.0


def shear_reduction(family: str, tau_t: float, tau_w: float, fv: float, k: float) -> float:
    """Vpl,T / Vpl: I-shapes √(1 - τt / (k fv)), channels the same less τw / fv, hollow 1 - τt /
    fv (fv = fy / (√3 γ), ``k`` the pack's 1.25); other shapes as I-shapes."""
    if family in ("rhs", "chs"):
        return max(1 - tau_t / fv, 0.0)
    root = math.sqrt(max(1 - tau_t / (k * fv), 0.0))
    if family == "channel":
        return max(root - tau_w / fv, 0.0)
    return root


def rows(
    shape: Any,
    steel: Any,
    stations: Sequence[Any],
    options: Any,
    welded: bool = False,
) -> list[dict[str, Any]]:
    """The torsion rows of one member (none without the method or without torque)."""
    from saengine.design.steel.limit_state import shear_area
    from saengine.design.steel.members import _check, _ratio, _Worst

    t = table()
    if t is None or not any(tor.has_torsion(getattr(st, "T", None)) for st in stations):
        return []
    fy, e = float(steel.fy), float(steel.e)
    gamma = float(t.gamma)
    fd = fy / gamma
    fv = fy / (math.sqrt(3) * gamma)
    g = shear_modulus(e)
    hollow = shape.family in ("rhs", "chs")
    section = None if hollow else tor.section_torsion(shape)
    warping = getattr(options, "warping", "free") or "free"
    av, av_note = shear_area(shape, "y", welded)
    av_x, _ = shear_area(shape, "x", welded)
    vpl = av * fv
    t_sv = st_venant_resistance(shape, fy, gamma, g)
    criterion = float(t.criterion)
    worst_y, worst_v = _Worst(), _Worst()
    largest = 0.0
    for st in stations:
        torque = getattr(st, "T", None)
        if not tor.has_torsion(torque):
            continue
        largest = max(largest, float(np.max(np.abs(np.asarray(torque, dtype=float)))))
        if hollow:
            phi1 = phi2 = phi3 = None
        else:
            sol = tor.solve_warping(st.s, torque, g, e, shape.j, shape.cw, warping)
            phi1, phi2, phi3 = sol.phi1, sol.phi2, sol.phi3
        for k in range(len(st.s)):
            tk = abs(float(torque[k]))
            p, mx, my = abs(float(st.P[k])), abs(float(st.Mx[k])), abs(float(st.My[k]))
            vy, vx = abs(float(st.Vy[k])), abs(float(st.Vx[k]))
            normal = p / shape.area + mx / shape.sx + my / shape.sy
            if hollow:
                tau_t = tk / (2 * hollow_area(shape) * shape.dims["t"])
                tau_w = 0.0
                v_shear = (vy / av if av > 0 else 0.0) + (vx / av_x if av_x > 0 else 0.0)
                tau = v_shear + tau_t
                sigma_w = 0.0
                what = f"τt = T / (2 A0 t) = {tau_t:.1f} MPa"
            else:
                stress = tor.torsion_stresses(
                    section, g, e, float(phi1[k]), float(phi2[k]), float(phi3[k])
                )
                sigma_w = stress.normal
                v_flange, v_web = tor.shear_stresses(shape, vy, vx)
                tau = max(v_flange + stress.shear_flange, v_web + stress.shear_web)
                tau_t = g * section.t_web * abs(float(phi1[k]))
                tau_w = (
                    e * section.sw_flange * abs(float(phi3[k])) / section.t_flange
                    if section.t_flange
                    else 0.0
                )
                what = (
                    f"σw = {sigma_w:.1f}, τt = {tau_t:.1f}, τw = {tau_w:.1f} MPa (warping "
                    f"{warping} at the supports)"
                )
            sigma = normal + sigma_w
            ratio = (sigma / fd) ** 2 + criterion * (tau / fd) ** 2
            worst_y.offer(
                ratio,
                ratio,
                1.0,
                st.combination,
                f"σ = {sigma:.1f} MPa (N, M and warping at the flange tip), τ = {tau:.1f} MPa, "
                f"fy / γ = {fd:.0f} MPa; {what}; T = {tk / 1e6:.2f} kN·m; {st.where[k]}",
                _cite("criterion"),
            )
            share = shear_reduction(shape.family, tau_t, tau_w, fv, float(t.shearReductionOpen))
            cap = share * vpl
            worst_v.offer(
                _ratio(vy, cap),
                vy,
                cap,
                st.combination,
                f"Vpl,T = {share:.3f} Vpl, Vpl = Av fy / (√3 γ) = {vpl / 1e3:.0f} kN ({av_note}); "
                f"{st.where[k]}",
                _cite("shear"),
            )
    small = largest <= float(t.neglect) * t_sv
    out = [
        _check("Torsion: yield criterion (elastic stresses)", worst_y, "", 1.0, flag=small),
        _check("Torsion: shear with torsion (Vpl,T)", worst_v, "kN", 1e3, flag=small),
    ]
    if small:
        for row in out:
            row["note"] += (
                f"; T <= {float(t.neglect):g} × the St. Venant resistance "
                f"{t_sv / 1e6:.2f} kN·m: torsion small (flagged)"
            )
    return out


def method_line() -> str | None:
    """The design report's paragraph of the method (None: not chosen)."""
    t = table()
    if t is None:
        return None
    return (
        f"Torsion ({_cite('criterion')}; {_cite('shear')}): the elastic stresses of the twist "
        "along the member (open sections: St. Venant and warping torsion, the ends free to warp "
        "unless set; hollow sections: τt = T / (2 A0 t)) added to the stresses of N, M and V, "
        f"checked by (σ/fd)² + {float(t.criterion):g} (τ/fd)² <= 1 with fd = fy / "
        f"{float(t.gamma):g}; the shear resistance reduced to Vpl,T for the torsional shear."
    )
