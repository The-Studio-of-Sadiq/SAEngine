"""Torsion of steel members and its combination with axial force, flexure and shear (B31).

What the code pack's ``steel.members.torsion`` gives (BNBC 2020: Part 6 Sec 10.8.3, Eqs
6.10.150-158) and what is worked out here:

- Hollow sections (rectangular and round HSS): the design torsional strength φT Tn, Tn = Fcr C
  with the HSS torsional constant C and Fcr of torsional yielding and buckling
  (:func:`hss_torsion`). When the torque Tr exceeds the pack's ``neglect`` share of Tc, the
  interaction (Pr/Pc + Mr/Mc) + (Vr/Vc + Tr/Tc)² <= 1 is checked; below it torsion is
  neglected and the combined-force check of the member governs.
- Other members (I-shapes, channels, tees, angles, bars, rounds): the lowest of yielding under
  normal stress (Fn = Fy), shear yielding under shear stress (Fn = 0.6 Fy) and buckling (Fn =
  Fcr), on the stresses of the combined actions. The code asks for these stresses and for Fcr
  "as determined by analysis" without a method, so the pack names the methods
  (``methods.openSection``, ``methods.buckling``):

  - ``warping``: the torsion of thin-walled open members (:class:`WarpingSolution`): the twist
    φ along the member from GJ φ' - E Cw φ''' = T(s), the internal torque of the analysis,
    with the twist held at torsional supports and each end free to warp (φ'' = 0) or
    restrained against it (φ' = 0); then St. Venant shear G t φ', warping normal stress E Wn φ''
    and warping shear E Sw φ''' / t at the critical points of the section.
  - ``leastCritical``: Fcr of the buckling limit state is the least of the member's axial
    (compression) and lateral-torsional critical stresses at the station.

  A pack without a method leaves that check out (the member's notes say so).

Units: mm, N, N·mm, MPa; the stations' positions in m.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.codes import context as code_context

#: Torque below this [N·mm] (1 N·m) is numerical noise of the analysis, not torsion.
NOISE = 1e3


def members_data() -> Any:
    """The pack's ``steel.members`` data (None: the pack in force has none)."""
    try:
        return getattr(code_context.table("steel"), "members", None)
    except Exception:  # noqa: BLE001 - no pack at all
        return None


def clause(key: str, default: str = "") -> str:
    """The pack's clause string ``key`` of the member limit states ('' when it has none)."""
    data = members_data()
    return str(data.clauses.get(key, default)) if data is not None else default


# ─────────────────────────────────── HSS (Sec 10.8.3.1) ───────────────────────────────────


def hss_constant(shape: Any) -> float:
    """C, the torsional constant of a rectangular or round HSS [mm³] on the design wall t:
    round π (D - t)² t / 2; rectangular 2 (B - t)(H - t) t - 4.5 (4 - π) t³ (the thin-walled
    closed section with the corner radii, as the steel design references give it)."""
    d = shape.dims
    t = d["t"]
    if shape.family == "chs":
        return math.pi * (d["D"] - t) ** 2 * t / 2
    if shape.family == "rhs":
        return 2 * (d["B"] - t) * (d["H"] - t) * t - 4.5 * (4 - math.pi) * t**3
    raise ValueError(f"{shape.family} is not a hollow section")


@dataclass(frozen=True)
class TorsionCapacity:
    phi: float
    nominal: float  # Tn [N·mm]
    clause: str
    note: str

    @property
    def design(self) -> float:
        return self.phi * self.nominal


def hss_torsion(shape: Any, fy: float, e: float, length: float) -> TorsionCapacity | None:
    """φT Tn of a rectangular or round HSS of ``length`` [mm] (round HSS buckling depends on
    it); None when the pack has no torsion data."""
    data = members_data()
    if data is None:
        return None
    k = data.torsion
    d = shape.dims
    t = d["t"]
    c = hss_constant(shape)
    cap = k.shearYield * fy
    if shape.family == "chs":
        ratio = d["D"] / t
        long = k.roundLong * e / (math.sqrt(max(length, 1e-9) / d["D"]) * ratio**1.25)
        short = k.roundShort * e / ratio**1.5
        fcr = min(max(long, short), cap)
        note = f"round: D/t = {ratio:.1f}, L = {length:.0f} mm, Fcr = {fcr:.1f} MPa"
    else:
        # h: the flat width of the longer wall (the more slender one).
        h = max(d["b"], d["h"])
        ratio = h / t
        root = math.sqrt(e / fy)
        if ratio <= k.rectYield * root:
            fcr, regime = cap, "torsional yielding"
        elif ratio <= k.rectInelastic * root:
            fcr, regime = cap * (k.rectYield * root) / ratio, "inelastic buckling"
        else:
            if ratio > k.rectMaxRatio:
                return TorsionCapacity(
                    k.phi, 0.0, clause("torsionHss"), f"h/t = {ratio:.0f} > {k.rectMaxRatio:g}"
                )
            fcr, regime = k.rectElastic * math.pi**2 * e / ratio**2, "elastic buckling"
        note = f"rectangular: h/t = {ratio:.1f} ({regime}), Fcr = {fcr:.1f} MPa"
    return TorsionCapacity(
        k.phi, fcr * c, clause("torsionHss"), f"{note}, C = {c / 1e3:.1f}×10³ mm³"
    )


def hss_interaction(p: float, m: float, v: float, t: float) -> float:
    """(Pr/Pc + Mr/Mc) + (Vr/Vc + Tr/Tc)² from the ratios: ``p`` = Pr/Pc, ``m`` the sum of
    Mr/Mc about both axes, ``v`` the sum of Vr/Vc along both, ``t`` = Tr/Tc."""
    return p + m + (v + t) ** 2


# ─────────────────────────────── open sections (Sec 10.8.3.3) ───────────────────────────────


@dataclass(frozen=True)
class SectionTorsion:
    """What the stresses of torsion need of an open or solid section: ``wn`` the largest
    normalised unit warping |Wn| [mm²], ``sw_flange`` / ``sw_web`` the largest warping statical
    moments [mm⁴] of the flange and web, ``t_flange`` / ``t_web`` the plate thicknesses for the
    St. Venant shear G t φ' (solid sections: the thickness of Bredt's thin-plate formula)."""

    wn: float = 0.0
    sw_flange: float = 0.0
    sw_web: float = 0.0
    t_flange: float = 0.0
    t_web: float = 0.0


def section_torsion(shape: Any) -> SectionTorsion:
    """:class:`SectionTorsion` of an I-shape, channel, tee, angle, bar or round."""
    d = shape.dims
    match shape.family:
        case "I":
            ho, bf, tf = d["ho"], d["bf"], d["tf"]
            return SectionTorsion(bf * ho / 4, tf * bf**2 * ho / 16, 0.0, tf, d["tw"])
        case "channel":
            ho, bf, tf, tw = d["ho"], d["bf"], d["tf"], d["tw"]
            b1 = bf - tw / 2
            e0 = 3 * b1**2 * tf / (6 * b1 * tf + ho * tw)
            junction = tf * ho * b1 * (b1 - 2 * e0) / 4
            return SectionTorsion(
                ho / 2 * max(b1 - e0, e0),
                max(tf * ho * (b1 - e0) ** 2 / 4, abs(junction)),
                abs(junction - tw * e0 * ho**2 / 8),
                tf,
                tw,
            )
        case "tee":
            return SectionTorsion(0.0, 0.0, 0.0, d["tf"], d["tw"])
        case "angle":
            return SectionTorsion(0.0, 0.0, 0.0, d["t"], d["t"])
        case "bar":
            t = min(d["d"], d["b"])
            return SectionTorsion(0.0, 0.0, 0.0, t, t)
        case "round":
            return SectionTorsion(0.0, 0.0, 0.0, d["D"] / 2, d["D"] / 2)
    raise ValueError(f"{shape.family}: not an open or solid section")


@dataclass
class WarpingSolution:
    """The twist of one combination along a member at its stations: ``torque`` T [N·mm],
    ``phi1`` φ' [rad/mm], ``phi2`` φ'' [rad/mm²], ``phi3`` φ''' [rad/mm³]."""

    torque: np.ndarray
    phi1: np.ndarray
    phi2: np.ndarray
    phi3: np.ndarray


def _tridiagonal(lower: np.ndarray, diag: np.ndarray, upper: np.ndarray, rhs: np.ndarray):
    """Thomas algorithm (lower[0] and upper[-1] unused)."""
    n = len(diag)
    c = np.zeros(n)
    d = np.zeros(n)
    c[0] = upper[0] / diag[0]
    d[0] = rhs[0] / diag[0]
    for i in range(1, n):
        m = diag[i] - lower[i] * c[i - 1]
        c[i] = upper[i] / m if i < n - 1 else 0.0
        d[i] = (rhs[i] - lower[i] * d[i - 1]) / m
    x = np.zeros(n)
    x[-1] = d[-1]
    for i in range(n - 2, -1, -1):
        x[i] = d[i] - c[i] * x[i + 1]
    return x


def _theta(
    grid: np.ndarray, torque: np.ndarray, gj: float, ecw: float, fixed: tuple[bool, bool]
) -> np.ndarray:
    """θ = φ' on the uniform ``grid`` from E Cw θ'' - GJ θ = -T, θ = 0 at an end restrained
    against warping, θ' = 0 at a free one."""
    n = len(grid)
    h = grid[1] - grid[0]
    a = ecw / h**2
    lower = np.full(n, a)
    upper = np.full(n, a)
    diag = np.full(n, -2 * a - gj)
    rhs = -torque.astype(float).copy()
    for end, first in ((fixed[0], True), (fixed[1], False)):
        i = 0 if first else n - 1
        if end:
            lower[i], upper[i], diag[i], rhs[i] = 0.0, 0.0, 1.0, 0.0
        elif first:
            upper[0] = 2 * a  # ghost node θ[-1] = θ[1]
        else:
            lower[-1] = 2 * a
    return _tridiagonal(lower, diag, upper, rhs)


def solve_warping(
    s: np.ndarray,
    torque: np.ndarray,
    g: float,
    e: float,
    j: float,
    cw: float,
    warping: str = "free",
) -> WarpingSolution:
    """The twist of a member under the internal torque ``torque`` [N·mm] at the stations ``s``
    [m] (sorted). The analysis twisted the member's ends by ∫T/GJ relative to each other (it
    has no warping stiffness); the member keeps that relative twist, so with both ends carrying
    torque a constant torque is shifted between them until ∫φ' matches it, as the warping
    stiffness asks. An end without torque is free (and free to warp). ``warping``: "free"
    (φ'' = 0) or "fixed" (φ' = 0) at the ends that carry torque."""
    s_mm = np.asarray(s, dtype=float) * 1e3
    torque = np.asarray(torque, dtype=float)
    length = float(s_mm[-1] - s_mm[0]) if len(s_mm) > 1 else 0.0
    gj = g * j
    if length <= 0 or gj <= 0:
        zeros = np.zeros_like(torque)
        return WarpingSolution(torque, zeros, zeros, zeros)
    peak = float(np.max(np.abs(torque))) if len(torque) else 0.0
    supported = (
        abs(float(torque[0])) > 1e-3 * peak,
        abs(float(torque[-1])) > 1e-3 * peak,
    )
    if cw <= 0:
        phi1 = torque / gj
        phi2 = np.gradient(phi1, s_mm) if len(s_mm) > 1 else np.zeros_like(phi1)
        return WarpingSolution(torque, phi1, phi2, np.zeros_like(phi1))
    ecw = e * cw
    lam = math.sqrt(gj / ecw)
    # The boundary layer at a restrained end is about 1/λ long: at least 5 grid steps in it.
    n = int(min(4001, max(201, math.ceil(5 * lam * length) + 1)))
    grid = np.linspace(s_mm[0], s_mm[-1], n)
    t_grid = np.interp(grid, s_mm, torque)
    fixed = (warping == "fixed" and supported[0], warping == "fixed" and supported[1])
    theta = _theta(grid, t_grid, gj, ecw, fixed)
    if all(supported):
        target = float(np.trapezoid(t_grid, grid)) / gj
        unit = _theta(grid, np.ones(n), gj, ecw, fixed)
        shift = (target - float(np.trapezoid(theta, grid))) / float(np.trapezoid(unit, grid))
        theta = theta + shift * unit
        t_grid = t_grid + shift
    phi2 = np.gradient(theta, grid)
    phi3 = (gj * theta - t_grid) / ecw
    return WarpingSolution(
        np.interp(s_mm, grid, t_grid),
        np.interp(s_mm, grid, theta),
        np.interp(s_mm, grid, phi2),
        np.interp(s_mm, grid, phi3),
    )


@dataclass(frozen=True)
class TorsionStresses:
    """The stresses of torsion at a station [MPa]: ``normal`` the warping normal stress,
    ``shear_flange`` and ``shear_web`` St. Venant plus warping shear."""

    normal: float
    shear_flange: float
    shear_web: float


def torsion_stresses(
    section: SectionTorsion, g: float, e: float, phi1: float, phi2: float, phi3: float
) -> TorsionStresses:
    """The stresses of the twist (φ', φ'', φ''') at one station."""
    warping_flange = e * section.sw_flange * abs(phi3) / section.t_flange if section.t_flange else 0
    warping_web = e * section.sw_web * abs(phi3) / section.t_web if section.t_web else 0.0
    return TorsionStresses(
        e * section.wn * abs(phi2),
        g * section.t_flange * abs(phi1) + warping_flange,
        g * section.t_web * abs(phi1) + warping_web,
    )


def shear_stresses(shape: Any, vy: float, vx: float) -> tuple[float, float]:
    """The shear stresses [MPa] of the shear forces Vy (along the depth) and Vx at the flange
    and web points the torsional shear adds to: (flange, web). I-shapes and channels: web Vy
    / (d tw) (the web area of the shear strength), flanges 1.5 Vx / (n bf tf); tees: stem Vy
    / (d tw), flange 1.5 Vx / (bf tf); angles: V / (leg t) per leg; bars 1.5 V / A, rounds 4/3
    V / A (the peak of the elastic distribution)."""
    d = shape.dims
    vy, vx = abs(vy), abs(vx)
    match shape.family:
        case "I" | "channel":
            return 1.5 * vx / (2 * d["bf"] * d["tf"]), vy / (d["d"] * d["tw"])
        case "tee":
            return 1.5 * vx / (d["bf"] * d["tf"]), vy / (d["d"] * d["tw"])
        case "angle":
            return vx / (d["b"] * d["t"]), vy / (d["d"] * d["t"])
        case "bar":
            v = 1.5 * math.hypot(vx, vy) / shape.area
            return v, v
        case "round":
            v = 4 / 3 * math.hypot(vx, vy) / shape.area
            return v, v
    return 0.0, 0.0


def has_torsion(torque: np.ndarray | None) -> bool:
    """Whether the analysis gives the member any torque beyond numerical noise."""
    return torque is not None and len(torque) > 0 and float(np.max(np.abs(torque))) > NOISE


__all__ = [
    "NOISE",
    "SectionTorsion",
    "TorsionCapacity",
    "TorsionStresses",
    "WarpingSolution",
    "clause",
    "has_torsion",
    "hss_constant",
    "hss_interaction",
    "hss_torsion",
    "members_data",
    "section_torsion",
    "shear_stresses",
    "solve_warping",
    "torsion_stresses",
]
