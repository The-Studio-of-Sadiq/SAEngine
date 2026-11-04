"""Welded hollow section truss joints by the chord face design resistances: the method
``chordFace`` a pack picks with ``steelLimitState.hssJoints`` (alpha 9 C12; the Eurocodes pack:
EN 1993-1-8 Section 7, Tables 7.1, 7.2, 7.8, 7.10-7.12). :func:`saengine.design.
steel_connections.check_hss_joint` hands the joint here when the pack chooses it.

- **CHS chords** (round branches): chord face failure of T/Y joints γ^0.2 kp fy0 t0² (2.8 +
  14.2 β²) / sinθ, X joints kp fy0 t0² 5.2 / ((1 - 0.81 β) sinθ), gapped K joints kg kp fy0
  t0² (1.8 + 10.2 d1/d0) / sinθ with kg of the gap; punching shear fy0 t0 π d1 (1 + sinθ) /
  (2 √3 sin²θ) when d1 <= d0 - 2 t0; all over γM5. kp = 1 - 0.3 np (1 + np) with np the chord's
  compression utilisation (the joint's ``chordUtilisation``: SAEngine reads it as np).
- **RHS chords** (rectangular branches): chord face failure (β <= 0.85) kn fy0 t0² (2η / sinθ
  + 4 √(1 - β)) / ((1 - β) sinθ) of T, Y and X joints, gapped K joints 8.9 kn fy0 t0² √γ (b1 +
  b2 + h1 + h2) / (4 b0 sinθ); brace failure fyi ti (2 hi - 4 ti + 2 beff) (K: bi + beff);
  punching shear when 0.85 <= β <= 1 - 1/γ. kn = 1.3 - 0.4 n / β <= 1 in compression.
- The limits of validity as checks; overlapped K joints and the chord side walls at β = 1 are
  not covered by this method (stated).

Units: N, mm, MPa.
"""

from __future__ import annotations

import math
from typing import Any


def table() -> Any | None:
    """The pack's ``steelLimitState.hssJoints``; None: the default pack's HSS joints."""
    from saengine.design.steel.limit_state import rules

    t = rules()
    return getattr(t, "hssJoints", None) if t is not None else None


def _cite(key: str) -> str:
    """The group's clause ``key`` (the full reference, the code's name included)."""
    t = table()
    return str(t.clauses.get(key, "")) if t is not None else ""


def kg(gamma: float, gap: float, t0: float, f: tuple[float, ...]) -> float:
    """kg = γ^0.2 (1 + a γ^b / (1 + exp(c g / t0 - d)))."""
    a, b, c, d = f
    return gamma**0.2 * (1 + a * gamma**b / (1 + math.exp(c * gap / t0 - d)))


def check(
    c: Any,
    branch: Any,
    branch_material: Any,
    chord: Any,
    chord_material: Any,
    axial: list[tuple[str | None, float]],
    overlapped: Any = None,
    overlapped_material: Any = None,
) -> dict[str, Any]:
    """The joint's checks (the format of :func:`saengine.design.steel_connections.
    check_hss_joint`)."""
    from saengine.design.steel_connections import _check, _governing, _limit, _result

    t = table()
    lim = t.limits
    cm = chord_material or branch_material
    fy0, fyi = float(cm.fy), float(branch_material.fy)
    t0, ti = chord.tw, branch.tw
    theta = math.radians(c.angle)
    sin = math.sin(theta)
    g5 = float(t.gamma)
    round_ = chord.shape == "circleHollow" and branch.shape == "circleHollow"
    rect = chord.shape == "rectangleHollow" and branch.shape == "rectangleHollow"
    if not (round_ or rect):
        raise ValueError(
            "HSS joints need a round branch on a round chord or rectangular on rectangular"
        )
    if c.joint == "KOverlap":
        raise ValueError(
            f"overlapped K joints: not covered by {_cite('code') or 'the pack'}'s method"
        )
    other = overlapped or branch
    n = float(c.chordUtilisation) if c.chordCompression else 0.0
    checks: list[dict[str, Any]] = []
    capacities: list[tuple[str, float, str]] = []
    ref = _cite("validity")
    if round_:
        d0, di = chord.h, branch.h
        beta = di / d0 if c.joint != "K" else (di + other.h) / (2 * d0)
        gamma = d0 / (2 * t0)
        kp = max(1 - float(t.kp) * n * (1 + n), 0.0) if n > 0 else 1.0
        checks.append(
            _limit("β = d1 / d0 (least)", beta, float(lim["chsBetaMin"]), ref, above=True)
        )
        checks.append(_limit("β = d1 / d0", beta, float(lim["chsBetaMax"]), ref))
        most = float(lim["chsRatioMaxX"] if c.joint == "X" else lim["chsRatioMax"])
        checks.append(_limit("chord d0 / t0", d0 / t0, most, ref))
        checks.append(_limit("brace d1 / t1", di / ti, float(lim["chsBraceMax"]), ref))
        base = fy0 * t0**2 / sin / g5
        if c.joint == "TY":
            a, b = t.chsT
            cap = gamma**0.2 * kp * base * (a + b * beta**2)
            note = f"{_cite('chs')}: γ^0.2 kp fy0 t0² ({a:g} + {b:g} β²) / sinθ / γM5"
        elif c.joint == "X":
            a, b = t.chsX
            cap = kp * base * a / (1 - b * beta)
            note = f"{_cite('chs')}: kp fy0 t0² {a:g} / ((1 - {b:g} β) sinθ) / γM5"
        else:
            checks.append(_limit("gap g", c.gap, ti + other.tw, f"{ref}: g >= t1 + t2", above=True))
            k_g = kg(gamma, c.gap, t0, tuple(float(x) for x in t.kgFactors))
            a, b = t.chsK
            cap = k_g * kp * base * (a + b * di / d0)
            note = (
                f"{_cite('chs')}: kg kp fy0 t0² ({a:g} + {b:g} d1/d0) / sinθ / γM5, kg = {k_g:.2f}"
            )
        capacities.append(("chord face failure", cap, f"{note}, kp = {kp:.2f}, β = {beta:.2f}"))
        if di <= d0 - 2 * t0:
            cap = fy0 * t0 * math.pi * di * (1 + sin) / (2 * math.sqrt(3) * sin**2 * g5)
            capacities.append(
                (
                    "chord punching shear",
                    cap,
                    f"{_cite('chs')}: fy0 t0 π d1 (1 + sinθ) / (2 √3 sin²θ γM5)",
                )
            )
    else:
        b0, h0 = chord.b, chord.h
        bi, hi = branch.b, branch.h
        beta = bi / b0 if c.joint != "K" else (bi + other.b + hi + other.h) / (4 * b0)
        gamma = b0 / (2 * t0)
        eta = hi / b0
        kn = min(float(t.kn[0]) - float(t.kn[1]) * n / beta, 1.0) if n > 0 else 1.0
        checks.append(_limit("chord b0 / t0", b0 / t0, float(lim["rhsRatioMax"]), ref))
        checks.append(_limit("chord h0 / t0", h0 / t0, float(lim["rhsRatioMax"]), ref))
        checks.append(_limit("brace bi / ti", bi / ti, float(lim["rhsBraceMax"]), ref))
        least = float(lim["rhsBetaMin"])
        if c.joint == "K":
            least = max(0.35, 0.1 + 0.01 * b0 / t0)
            checks.append(_limit("gap g", c.gap, ti + other.tw, f"{ref}: g >= t1 + t2", above=True))
        checks.append(_limit("β = bi / b0 (least)", bi / b0, least, ref, above=True))
        beff = min(float(t.effectiveWidth) / (b0 / t0) * fy0 * t0 / (fyi * ti) * bi, bi)
        if c.joint == "K":
            cap = (
                float(t.rhsK) * kn * fy0 * t0**2 * math.sqrt(gamma)
                * (bi + other.b + hi + other.h) / (4 * b0) / sin / g5
            )  # fmt: skip
            capacities.append(
                (
                    "chord face failure",
                    cap,
                    (
                        f"{_cite('rhs')}: {float(t.rhsK):g} kn fy0 t0² √γ (b1 + b2 + h1 + h2) / "
                        f"(4 b0) / sinθ / γM5, kn = {kn:.2f}"
                    ),
                )
            )
            capacities.append(
                (
                    "brace failure",
                    fyi * ti * (2 * hi - 4 * ti + bi + beff) / g5,
                    f"{_cite('rhs')}: fyi ti (2 hi - 4 ti + bi + beff) / γM5, beff = {beff:.0f} mm",
                )
            )
        else:
            if beta <= float(t.rhsFaceBeta):
                cap = (
                    kn * fy0 * t0**2 / ((1 - beta) * sin)
                    * (2 * eta / sin + 4 * math.sqrt(1 - beta)) / g5
                )  # fmt: skip
                capacities.append(
                    (
                        "chord face failure",
                        cap,
                        (
                            f"{_cite('rhs')}: kn fy0 t0² (2η / sinθ + 4 √(1 - β)) / ((1 - β) sinθ "
                            f"γM5), β = {beta:.2f}, η = {eta:.2f}, kn = {kn:.2f}"
                        ),
                    )
                )
            else:
                capacities.append(
                    (
                        "brace failure",
                        fyi * ti * (2 * hi - 4 * ti + 2 * beff) / g5,
                        f"{_cite('rhs')}: fyi ti (2 hi - 4 ti + 2 beff) / γM5, beff = {beff:.0f} mm",
                    )
                )
                if beta <= 1 - 1 / gamma:
                    bep = min(float(t.effectiveWidth) / (b0 / t0) * bi, bi)
                    cap = fy0 * t0 / (math.sqrt(3) * sin) * (2 * hi / sin + 2 * bep) / g5
                    capacities.append(
                        (
                            "chord punching shear",
                            cap,
                            f"{_cite('rhs')}: fy0 t0 (2 hi / sinθ + 2 be,p) / (√3 sinθ γM5)",
                        )
                    )
    for sign, label in ((1, "tension"), (-1, "compression")):
        comb, p = _governing(axial, sign)
        if p * sign <= 0:
            continue
        for name, cap, note in capacities:
            checks.append(_check(f"{name} ({label})", abs(p) / 1e3, cap / 1e3, "kN", comb, note))
    for row in checks:
        if row["unit"] == "":
            row["unit"] = "-"
    joint = {"TY": "T or Y", "X": "cross (X)", "K": "gapped K"}[c.joint]
    assumptions = [
        f"{'round' if round_ else 'rectangular'} {joint} joint, θ = {c.angle:g}°, chord {chord.name}",
        f"chord in compression, np = n = {n:g} (the joint's chord utilisation)"
        if n > 0
        else "chord in tension (kp = kn = 1)",
        "the welds develop the branch (not checked)",
    ]
    if rect and beta > float(t.rhsFaceBeta) and c.joint != "K":
        assumptions.append("chord side wall failure (β near 1): not covered by this method")
    return _result("hssJoint", checks, assumptions)
