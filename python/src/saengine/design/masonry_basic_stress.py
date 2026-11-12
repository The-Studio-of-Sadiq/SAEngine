"""Unreinforced masonry walls by permissible stresses from a basic compressive stress: the
``"basicStress"`` method of the code pack's ``masonry`` table (alpha 9 C9; IS 1905:1987 is the
first pack to choose it).

The forces are the wall piers' under the code pack's allowable stress (working) combinations
(the shell model's section cuts, :mod:`saengine.design.wall_design`). The permissible
compressive stress is fc = fb ks ka kp:

- fb, the basic compressive stress, by the units' compressive strength and the mortar (the
  pack's rows by mortar grade; the wall's mortar mix picks the grade with at least its sand
  per cement part, linear between the unit strengths);
- ks, the stress reduction factor, by the slenderness ratio SR = h_eff / t (h_eff the clear
  height × the pack's factor for walls supported top and bottom, twice the clear height with a
  free top) and the eccentricity ratio e/t (e = the out-of-plane moment / P), linear in both;
- ka, the area reduction factor of small sections (A below the pack's area), kp the units'
  shape factor.

Per pier, the governing combination of each check: the slenderness ratio, the axial stress P/A
≤ fc, the face stress P/A + M/Z ≤ the pack's increase × fc where e/t exceeds its limit, the net
flexural tension (normal to the bed joints out of plane, the larger in plane) against the
pack's permissible tension for mortars at least as rich as its limit (else none allowed), the
in-plane shear V/A ≤ a + fd/b ≤ c. The stresses are increased by the pack's factor in the
combinations with wind or earthquake. Bars of a reinforced wall type are not counted (the
method is for unreinforced masonry; stated in the notes).

Every number comes from ``masonry.basicStress``; the clauses from ``masonry.clauses``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from saengine.design import masonry as M
from saengine.design import masonry_dimensions as D
from saengine.design import walls as W
from saengine.design.ductile_members import _row
from saengine.design.rc import DesignError

#: The combinations this method checks: the code pack's allowable stress combinations.
COMBINATIONS = "allowable"


def rules() -> Any:
    found = getattr(M.table(), "basicStress", None)
    if found is None:
        raise DesignError("the code pack's masonry table has no basicStress values")
    return found


def method_text() -> list[str]:
    r = rules()
    return [
        (
            f"Masonry walls ({M.clause('chapter')}, permissible stresses): unreinforced walls of "
            "a masonry material, from the pier forces of the shell model under the code pack's "
            "working (allowable stress) combinations. The permissible compressive stress fc = fb "
            f"ks ka kp: fb by the unit strength and the mortar ({M.clause('basicStress')}), ks by "
            f"the slenderness ratio and e/t ({M.clause('stressReduction')}), ka of sections under "
            f"{float(r.areaBelow):g} m² ({M.clause('areaReduction')}), kp = "
            f"{float(r.shapeFactor):g} ({M.clause('shapeModification')}); effective height "
            f"{float(r.effectiveHeight):g} × the clear height ({M.clause('effectiveHeight')}), SR "
            f"≤ {float(r.slendernessMax):g} ({M.clause('slenderness')}); the face stress of "
            f"eccentric loads ≤ {float(r.eccentricityIncrease[1]):g} fc "
            f"({M.clause('eccentricity')}); flexural tension {float(r.tension[0]):g} / "
            f"{float(r.tension[1]):g} MPa ({M.clause('flexuralTension')}); shear "
            f"{float(r.shear[0]):g} + fd/{float(r.shear[1]):g} ≤ {float(r.shear[2]):g} MPa "
            f"({M.clause('shear')}); × {float(r.lateralIncrease):g} with wind or earthquake "
            f"({M.clause('lateralIncrease')})."
        )
    ]


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for k in range(1, len(xs)):
        if x <= xs[k]:
            f = (x - xs[k - 1]) / (xs[k] - xs[k - 1])
            return float(ys[k - 1] + f * (ys[k] - ys[k - 1]))
    return float(ys[-1])  # pragma: no cover


def mortar_row(m: M.Masonry) -> tuple[str, float, list[float]]:
    """(grade, sand per cement part, fb row) of the wall's mortar: the pack's grade whose sand
    is at least the mortar's (the mortar grades of the masonry table give the mix); the leanest
    row when the mortar is not known (on the safe side)."""
    r = rules()
    rows = sorted(r.mortars.items(), key=lambda kv: float(kv[1][0]))
    sand = None
    if m.mortar is not None and m.mortar in M.table().mortars:
        mix = M.table().mortars[m.mortar]
        sand = float(mix.sand) / float(mix.cement)
    if sand is None:
        grade, (s, row) = rows[-1]
        return grade, float(s), list(row)
    for grade, (s, row) in rows:
        if float(s) >= sand - 1e-9:
            return grade, float(s), list(row)
    grade, (s, row) = rows[-1]
    return grade, float(s), list(row)


def basic_stress(unit_strength: float, row: list[float]) -> float:
    """fb [MPa] at the unit strength, linear between the table's unit strengths (the ends
    outside them)."""
    return _interp([float(u) for u in rules().unitStrengths], row, unit_strength)


def stress_reduction(sr: float, e_t: float) -> float | None:
    """ks by SR and e/t, linear in both; None where the table does not permit the case."""
    r = rules()
    srs = [float(v) for v in r.slenderness]
    ecc = [float(v) for v in r.eccentricities]
    e_t = max(e_t, 0.0)
    if e_t > ecc[-1] + 1e-9 or sr > srs[-1] + 1e-9:
        return None

    def at_row(k: int) -> float | None:
        row = r.reduction[k]
        if sr <= srs[0]:
            return row[0]
        for j in range(1, len(srs)):
            if sr <= srs[j]:
                lo, hi = row[j - 1], row[j]
                if lo is None or hi is None:
                    return None
                f = (sr - srs[j - 1]) / (srs[j] - srs[j - 1])
                return lo + f * (hi - lo)
        return row[-1]

    for k in range(1, len(ecc)):
        if e_t <= ecc[k]:
            lo, hi = at_row(k - 1), at_row(k)
            if lo is None or hi is None:
                return None
            f = (e_t - ecc[k - 1]) / (ecc[k] - ecc[k - 1])
            return max(lo + f * (hi - lo), 0.0)
    return at_row(0)


def area_factor(area_m2: float) -> float:
    r = rules()
    if area_m2 < float(r.areaBelow):
        return min(float(r.areaBase) + float(r.areaSlope) * area_m2, 1.0)
    return 1.0


def _worst(rows: Iterable[dict[str, Any] | None]) -> dict[str, Any] | None:
    return max((r for r in rows if r), key=lambda r: r["utilisation"], default=None)


def wall_checks(
    geometry: W.WallGeometry,
    bars: W.WallBars | None,
    forces: list[W.PierForces],
    m: M.Masonry,
    fy: float = 420.0,
    lateral: Iterable[str] = (),
    storeys: int | None = None,
) -> M.MasonryDesign:
    """The permissible stress checks of an unreinforced masonry wall pier (see the module
    notes). ``forces``: working forces, compression positive [N, N·mm]."""
    r = rules()
    lateral = set(lateral)
    t, lw, h = geometry.thickness, geometry.length, geometry.clear_height
    area = t * lw
    z_out = lw * t**2 / 6.0
    z_in = t * lw**2 / 6.0
    notes: list[str] = list(m.notes)
    checks: list[dict[str, Any] | None] = []
    if bars is not None:
        notes.append(
            "the wall type has bars: the method is for unreinforced masonry, so the bars are not "
            "counted (checked as plain masonry)"
        )
    if m.unit_strength is None:
        raise DesignError(
            "the basic compressive stress needs the units' compressive strength: enter it on "
            "the masonry material (03 Materials)"
        )
    h_eff = float(r.effectiveHeight) * h if geometry.braced else D.effective_height(h, False)
    sr = h_eff / t
    checks.append(
        _row(
            f"Slenderness ratio SR ≤ {float(r.slendernessMax):g} ({M.clause('slenderness')})",
            sr,
            float(r.slendernessMax),
            "",
            note=f"h_eff = {h_eff:.0f} mm ({M.clause('effectiveHeight')})"
            + ("" if geometry.braced else ", free top"),
        )
    )
    grade, sand, row = mortar_row(m)
    fb = basic_stress(float(m.unit_strength), row)
    ka = area_factor(area / 1e6)
    kp = float(r.shapeFactor)
    notes.append(
        f"fb = {fb:.2f} MPa: units {float(m.unit_strength):g} MPa, mortar {m.mortar or 'unknown'} "
        f"as {grade} (1:{sand:g}){'' if m.mortar else ', the leanest row taken'}; ka = {ka:.2f}, "
        f"kp = {kp:g}"
    )
    if not forces:
        return M.MasonryDesign([c for c in checks if c], notes + ["no forces: not checked"], 0.0)
    tension_ok = sand <= float(r.tensionMix) + 1e-9
    e_limit, e_factor = float(r.eccentricityIncrease[0]), float(r.eccentricityIncrease[1])

    def increase(f: W.PierForces) -> float:
        return float(r.lateralIncrease) if (f.combination or "") in lateral else 1.0

    axial, face, tension, shear = [], [], [], []
    for f in forces:
        k = increase(f)
        tag = f"{f.where or ''}" + (f"; × {k:.3g} (wind or earthquake)" if k > 1 else "")
        p = max(f.P, 0.0)
        fd = p / area
        e_t = abs(f.M2) / p / t if p > 0 else math.inf
        ks = stress_reduction(sr, e_t if math.isfinite(e_t) else 0.0)
        if p > 0 and ks is None:
            axial.append(
                _row(
                    f"Axial stress ≤ fb ks ka kp ({M.clause('stressReduction')})",
                    fd,
                    0.0,
                    "MPa",
                    f.combination,
                    f"{tag}; SR = {sr:.1f}, e/t = {e_t:.3f}: outside the stress reduction table",
                )
            )
            continue
        fc = fb * (ks if ks is not None else 1.0) * ka * kp * k
        axial.append(
            _row(
                f"Axial stress ≤ fb ks ka kp ({M.clause('stressReduction')})",
                fd,
                fc,
                "MPa",
                f.combination,
                f"{tag}; SR = {sr:.1f}, e/t = {min(e_t, 9.99):.3f}, ks = {ks or 1.0:.3f}",
            )
        )
        bending = abs(f.M2) / z_out
        if p > 0 and e_t > e_limit:
            face.append(
                _row(
                    f"Face stress of eccentric load ≤ {e_factor:g} fc ({M.clause('eccentricity')})",
                    fd + bending,
                    e_factor * fc,
                    "MPa",
                    f.combination,
                    f"{tag}; P/A + M/Z with e/t = {min(e_t, 9.99):.3f} > {e_limit:.4g}",
                )
            )
        net_out = bending - fd
        net_in = abs(f.M3) / z_in - fd
        allowed = (
            max(float(r.tension[0]) * k, 1e-9) if tension_ok else 1e-9
        )  # none allowed with lean mortars
        tension.append(
            _row(
                f"Flexural tension ({M.clause('flexuralTension')})",
                max(net_out, 0.0),
                allowed,
                "MPa",
                f.combination,
                f"{tag}; normal to the bed joints (out of plane)"
                + ("" if tension_ok else f"; mortar leaner than 1:{float(r.tensionMix):g}: none"),
            )
        )
        if net_in > 0:
            tension.append(
                _row(
                    f"Flexural tension in plane ({M.clause('flexuralTension')})",
                    net_in,
                    max(float(r.tension[1]) * k, 1e-9) if tension_ok else 1e-9,
                    "MPa",
                    f.combination,
                    f"{tag}; parallel to the bed joints (in plane)",
                )
            )
        a, b, cap = (float(v) for v in r.shear)
        fs = min(a + fd / b, cap) * k
        shear.append(
            _row(
                f"In-plane shear ≤ {a:g} + fd/{b:g} ({M.clause('shear')})",
                abs(f.V2) / area,
                fs,
                "MPa",
                f.combination,
                f"{tag}; fd = {fd:.2f} MPa",
            )
        )
    for group in (axial, face, tension, shear):
        checks.append(_worst(group))
    found = [c for c in checks if c]
    strength = [c for c in found if not c["flag"]]
    utilisation = max((c["utilisation"] for c in strength), default=0.0)
    return M.MasonryDesign(found, notes, utilisation)
