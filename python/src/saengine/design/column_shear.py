"""Shear of reinforced-concrete columns from the analysis forces, with the axial force's
effect on Vc: BNBC 2020 Part 6 Sec 6.4 (pp. 921-927). Units: N, mm, MPa.

This is the strength check of every column (gravity columns, ordinary frames, and the
analysis shear of the others); the capacity-design shear of special and intermediate moment
frames stays in :mod:`saengine.design.ductile_joints` (Sec 8.3.8, 8.3.10.3).

- φVn >= Vu, Vn = Vc + Vs (Eqs. 6.6.47, 6.6.48, p. 921), φ of the ``factors`` table.
- Vc with axial compression Nu: 0.17 (1 + Nu / (14 Ag)) λ √f'c bw d (Eq. 6.6.50, p. 923);
  with axial tension 0.17 (1 + 0.29 Nu / Ag) λ √f'c bw d, not below zero (Eq. 6.6.54, p. 923,
  Nu negative); Nu/Ag in MPa. √f'c <= 8.3 MPa (Sec 6.4.1.2).
- Vs = Av fyt d / s (Eq. 6.6.56, p. 925), fyt <= 420 MPa (``fytShearMax``, Sec 6.4.3.2),
  Vs <= 0.66 √f'c bw d (Sec 6.4.3.6.9, p. 926).
- Circular columns: bw = D, d = 0.8 D (Sec 6.4.2.3, p. 923); a circular tie, hoop or spiral
  counts as Av = 2 × the bar area (Sec 6.4.3.6.3, p. 925).
- Rectangular columns, each profile axis separately: bw the other dimension, d from the
  compression face to the centroid of the bars of the far half (:func:`shear_depth`, which
  the ductile path's ``_column_shear_depth`` should call); Av the tie legs running along
  the shear (``legs`` run along the profile's y, ``legsX`` along x).
- Where shear reinforcement is needed (Vu > φVc, Sec 6.4.3.6.1) the tie spacing must not exceed
  d/2 nor 600 mm, halved where Vs > 0.33 √f'c bw d (Sec 6.4.3.4.1, 6.4.3.4.3, p. 924).
- Minimum shear reinforcement: BNBC Sec 6.4.3.5.1 is written for flexural members. Where
  Vu > 0.5 φ Vc and the ties give less than Av,min (Eq. 6.6.55) a reported-only row (``flag``)
  says so (ACI 318-19 10.6.2.1 asks it of columns; from memory, to be checked).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np

from saengine.design.rc import DesignError, RcSection, bar_area
from saengine.library.objects import CircleProfile, RectangleProfile

#: √f'c used in shear is capped at this [MPa] (BNBC 2020 Part 6 Sec 6.4.1.2).
ROOT_FC_MAX = 8.3


def _check(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from saengine.design.check import _check as check

    return check(*args, **kwargs)


@dataclass(frozen=True)
class ShearAxis:
    """A column section for shear along one profile axis."""

    axis: str  # "x" or "y": the direction of the shear in the profile's axes
    bw: float  # mm
    d: float  # mm
    av: float  # mm², the transverse steel along the shear at one spacing (0: none)
    spacing: float | None  # mm


#: Bars nearer than this [mm] to the section's centre line count as on it (not in the far half).
ON_CENTRE = 1.0


def shear_depth(section: RcSection, angle: float) -> float:
    """d [mm] of a rectangular column for shear whose compression face is towards the plan
    angle ``angle`` [rad, in the profile's axes]: from that face to the centroid of the bars of
    the far half. Bars on the centre line (within :data:`ON_CENTRE`) are left out: cos(π/2) is
    not exactly 0, and counting them would pull d in by the rounding of the angle (with 3 bars a
    face of a 400 mm column, 305 mm instead of 340 mm). Without bars in the far half, 0.8 h."""
    if not isinstance(section.profile, RectangleProfile):
        raise DesignError("shear depth of a rectangular column only")
    u = (math.cos(angle), math.sin(angle))
    along = abs(section.profile.xDim * u[0]) + abs(section.profile.yDim * u[1])
    far = [(b.x * u[0] + b.y * u[1], b.area) for b in section.bars]
    far = [(s, a) for s, a in far if s < -ON_CENTRE]
    if not far:
        return 0.8 * along
    centroid = sum(s * a for s, a in far) / sum(a for _, a in far)
    return along / 2 - centroid


def shear_axes(section: RcSection, transverse: Any | None) -> list[ShearAxis]:
    """The column's two shear axes (one for a circle). ``transverse``: the member type's
    :class:`saengine.library.objects.Transverse` (``dia``, ``spacing``, ``legs``,
    ``legsX``; None without ties); the spacing outside the end zones is used."""
    dia = transverse.dia if transverse else 0.0
    spacing = transverse.spacing if transverse else None
    if isinstance(section.profile, CircleProfile):
        diameter = 2 * section.profile.radius
        av = 2 * bar_area(dia) if transverse else 0.0
        return [ShearAxis("x", diameter, 0.8 * diameter, av, spacing)]
    if not isinstance(section.profile, RectangleProfile):
        raise DesignError("column shear is checked for rectangular and circular columns only")
    legs = int(transverse.legs) if transverse else 0
    legs_x = int(transverse.legsX or legs) if transverse else 0
    axes = []
    profile = section.profile
    for axis, angle, bw, count in (
        ("y", math.pi / 2, profile.xDim, legs),
        ("x", 0.0, profile.yDim, legs_x),
    ):
        d = shear_depth(section, angle)
        axes.append(ShearAxis(axis, bw, d, count * bar_area(dia) if count else 0.0, spacing))
    return axes


@dataclass(frozen=True)
class ColumnShear:
    phi_vn: float  # N
    vc: float
    vs: float
    vs_limited: bool
    av_min: float  # mm² at the spacing (0 without ties)


def concrete_shear(nu: float, ag: float, bw: float, d: float, fc: float, lam: float = 1.0):
    """Vc [N] with the axial force ``nu`` [N, compression positive] (Eqs. 6.6.50, 6.6.54)."""
    root = min(math.sqrt(fc), ROOT_FC_MAX)
    if nu >= 0:
        factor = 1 + nu / (14 * ag)
    else:
        factor = max(0.0, 1 + 0.29 * nu / ag)
    return 0.17 * factor * lam * root * bw * d


def column_shear_strength(
    part: ShearAxis,
    nu: float,
    ag: float,
    fc: float,
    fyt: float,
    fyt_max: float,
    phi: float,
    lam: float = 1.0,
) -> ColumnShear:
    vc = concrete_shear(nu, ag, part.bw, part.d, fc, lam)
    fyt = min(fyt, fyt_max)
    vs = part.av * fyt * part.d / part.spacing if part.av and part.spacing else 0.0
    vs_max = 0.66 * math.sqrt(fc) * part.bw * part.d
    limited = vs > vs_max
    vs = min(vs, vs_max)
    root = min(math.sqrt(fc), ROOT_FC_MAX)
    av_min = max(0.062 * root, 0.35) * part.bw * part.spacing / fyt if part.spacing else 0.0
    return ColumnShear(phi * (vc + vs), vc, vs, limited, av_min)


@dataclass(frozen=True)
class ShearPoints:
    """A column's points on arrays: Pu [N, compression positive], Vx, Vy [N], and ``label(i)``
    the (combination, where) of point i, asked only of the points the checks report."""

    pu: np.ndarray
    vx: np.ndarray
    vy: np.ndarray
    label: Callable[[int], tuple[str | None, str]]


def column_shear_checks(
    section: RcSection,
    transverse: Any | None,
    points: Iterable[tuple[float, float, float, str | None, str]] | ShearPoints,
    lam: float = 1.0,
    phi: float | None = None,
    fyt_max: float | None = None,
) -> list[dict[str, Any]]:
    """Check rows of a column's shear: for each axis the governing point (highest Vu/φVn,
    since Vc changes with the simultaneous axial force), and the tie-spacing limit and the
    Av,min flag over every point where they apply (not only the governing one). ``points``: (Pu [N, compression
    positive], Vx [N, along the profile's x], Vy [N, along y], combination, where), as
    :func:`saengine.design.check._profile_forces` gives them per station (``P``, ``Vx``,
    ``Vy``), or the same as :class:`ShearPoints`. A circle checks the resultant √(Vx² + Vy²)."""
    from saengine.codes import context as code_context

    if phi is None:
        phi = float(code_context.table("factors").phi.shear)
    if fyt_max is None:
        fyt_max = float(code_context.table("concrete").fytShearMax)
    parts = shear_axes(section, transverse)
    circle = isinstance(section.profile, CircleProfile)
    ag = section.gross_area
    # Per axis: the point of the highest Vu/φVn; the point of the tightest tie-spacing limit
    # among those with Vu > φVc; the point of the highest Vu/(0.5 φVc) among those above
    # 0.5 φVc. Vc changes with the simultaneous axial force, so these can be different points.
    if not isinstance(points, ShearPoints):
        listed = list(points)
        points = ShearPoints(
            np.array([p[0] for p in listed], dtype=float),
            np.array([p[1] for p in listed], dtype=float),
            np.array([p[2] for p in listed], dtype=float),
            lambda i: (listed[i][3], listed[i][4]),
        )
    worst: dict[str, tuple[float, float, ColumnShear, float, str | None, str]] = {}
    spacing_worst: dict[str, tuple[float, bool, float, str | None, str]] = {}
    minimum_worst: dict[str, tuple[float, ColumnShear, str | None, str]] = {}
    root = math.sqrt(section.fc)
    pu = points.pu
    if len(pu):
        # Every point at once, the same arithmetic as column_shear_strength and in its order;
        # the first point of equals is kept, as one by one.
        fc_root = min(math.sqrt(section.fc), ROOT_FC_MAX)
        factor = np.where(pu >= 0, 1 + pu / (14 * ag), np.maximum(0.0, 1 + 0.29 * pu / ag))
        if circle:
            vu_all = np.array(
                [
                    math.hypot(x, y)
                    for x, y in zip(points.vx.tolist(), points.vy.tolist(), strict=True)
                ]
            )
        for part in parts:
            vu = vu_all if circle else np.abs(points.vy if part.axis == "y" else points.vx)
            fixed = column_shear_strength(part, 0.0, ag, section.fc, section.fy, fyt_max, phi, lam)
            vc = 0.17 * factor * lam * fc_root * part.bw * part.d
            phi_vn = phi * (vc + fixed.vs)
            positive = phi_vn > 0
            ratio = np.where(
                positive,
                vu / np.where(positive, phi_vn, 1.0),
                np.where(vu > 0, math.inf, 0.0),
            )

            def at(i: int, part: ShearAxis = part) -> ColumnShear:
                return column_shear_strength(
                    part, float(pu[i]), ag, section.fc, section.fy, fyt_max, phi, lam
                )

            i = int(np.argmax(ratio))
            worst[part.axis] = (
                float(ratio[i]),
                float(vu[i]),
                at(i),
                float(pu[i]),
                *points.label(i),
            )
            phi_vc = phi * vc
            if part.spacing:
                # Sec 6.4.3.4.1, 6.4.3.4.3: the spacing limit where shear reinforcement is
                # needed, halved where the Vs needed exceeds 0.33 √f'c bw d.
                needed = np.flatnonzero(vu > phi_vc)
                if len(needed):
                    tight = vu[needed] / phi - vc[needed] > 0.33 * root * part.bw * part.d
                    s_max = np.where(tight, min(part.d / 2, 600.0) / 2, min(part.d / 2, 600.0) / 1)
                    k = int(np.argmin(s_max))
                    j = int(needed[k])
                    spacing_worst[part.axis] = (
                        float(s_max[k]),
                        bool(tight[k]),
                        float(pu[j]),
                        *points.label(j),
                    )
            if part.av < fixed.av_min:
                above = np.flatnonzero(vu > 0.5 * phi_vc)
                if len(above):
                    half = 0.5 * phi_vc[above]
                    excess = np.where(half > 0, vu[above] / np.where(half > 0, half, 1.0), math.inf)
                    k = int(np.argmax(excess))
                    j = int(above[k])
                    minimum_worst[part.axis] = (float(excess[k]), at(j), *points.label(j))
    rows = []
    for part in parts:
        if part.axis not in worst:
            continue
        _, vu, strength, pu, combination, where = worst[part.axis]
        label = "Column shear" if circle else f"Column shear along {part.axis}"
        notes = [
            f"Pu = {pu / 1e3:.0f} kN",
            f"Vc = 0.17 (1 + Nu/14Ag) λ √f'c bw d = {strength.vc / 1e3:.1f} kN"
            if pu >= 0
            else f"Vc = 0.17 (1 + 0.29 Nu/Ag) λ √f'c bw d = {strength.vc / 1e3:.1f} kN (tension)",
            f"Vs = {strength.vs / 1e3:.1f} kN, bw = {part.bw:.0f} mm, d = {part.d:.0f} mm, φ = {phi:g}",
        ]
        if strength.vs_limited:
            notes.append("Vs limited to 0.66 √f'c bw d")
        if not part.av:
            notes.append("no ties")
        if where:
            notes.append(where)
        rows.append(
            _check(label, vu / 1e3, strength.phi_vn / 1e3, "kN", combination, "; ".join(notes))
        )
        if part.axis in spacing_worst:
            s_max, tight, pu_s, combination_s, where_s = spacing_worst[part.axis]
            rows.append(
                _check(
                    f"{label}: tie spacing (Sec 6.4.3.4)",
                    part.spacing,
                    s_max,
                    "mm",
                    combination_s,
                    ("d/4 and 300 mm: Vs > 0.33 √f'c bw d" if tight else "d/2 and 600 mm")
                    + f", Vu > φVc at Pu = {pu_s / 1e3:.0f} kN, d = {part.d:.0f} mm"
                    + (f"; {where_s}" if where_s else ""),
                )
            )
        if part.axis in minimum_worst:
            _, strength_m, combination_m, where_m = minimum_worst[part.axis]
            rows.append(
                _check(
                    f"{label}: minimum ties Av,min (Eq. 6.6.55)",
                    strength_m.av_min,
                    part.av,
                    "mm²",
                    combination_m,
                    "Vu above 0.5 φVc with Av below 0.062 √f'c bw s/fyt (≥ 0.35 bw s/fyt); "
                    "BNBC 6.4.3.5.1 names flexural members, ACI 318-19 10.6.2.1 columns too"
                    + (f"; {where_m}" if where_m else ""),
                    flag=True,
                )
            )
    return rows
