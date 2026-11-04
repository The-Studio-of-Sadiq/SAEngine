"""Shear, torsion and punching with a tabulated design shear strength of concrete (alpha 9 C8;
the pack's ``concreteMethods.shear`` method ``tabulatedStress``, ``torsion`` method
``equivalentShear``, ``punching`` method ``rootStress``, as IS 456:2000 gives them).

A pack that picks these methods (and designs with partial factors,
:mod:`saengine.design.design_strength`) checks:

- Beam shear: τv = Vu / (b d) against the design shear strength of concrete τc, read from the
  pack's table by the tension steel ratio pt = 100 As / (b d) and the grade (linear between
  rows and columns, the end values outside), the stirrups Vus = fyd Asv d / sv with fyd =
  fy / γs (fy at most ``fyMax``), the section limit τv <= τc,max by grade; the least stirrups
  Asv / (b sv) >= ``minStirrupStress`` / fyd where τv exceeds τc / 2 (the members of minor
  importance below that). The steel ratio is that of the face with the fewer bars (on the safe
  side, as the strength design does).
- Torsion: the equivalent shear Ve = Vu + shearFactor Tu / b against the same shear strength
  (τve <= τc,max; τc carries it alone up to τc), the equivalent moment Me1 = Mu + Tu (1 + D/b)
  / momentDivisor against the flexural capacity, and the closed links Asv = Tu sv / (b1 d1
  fyd) + Vu sv / (depthDivisor d1 fyd), at least (τve - τc) b sv / fyd.
- Punching: τv = Vu / (b0 d) on the perimeter perimeterDistance × d from the loaded area
  against ks τc with τc = coefficient √fck, ks = ratioBase + βc <= 1 (βc the short over the
  long side of the column).
- Walls (in-plane): τcw by the aspect ratio of the pack's ``walls`` group, τv <= shearMaxShare
  fck, the horizontal bars Vus = fyd Ah d / Sv with d = depthShare × Lw.

Units: mm, MPa, N, N·mm.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from saengine.codes import context as code_context

#: Torsion below this [N·mm] (0.1 kN·m) is the analysis's numerical noise: no torsion rows
#: (SAEngine practice, not a code value).
TORSION_FLOOR = 1e5


def _table() -> Any | None:
    pack = code_context.current()
    return pack.table("concreteMethods") if pack.has("concreteMethods") else None


def _group(name: str, method: str | None = None) -> Any | None:
    from saengine.codes.method_tables import chosen
    from saengine.design import design_strength

    if not design_strength.partial_factors():
        return None
    t = _table()
    if method is None:
        return getattr(t, name, None) if t is not None else None
    return chosen(t, name, method)


def rules() -> Any | None:
    """The pack's ``concreteMethods.shear`` of method ``tabulatedStress``, or None."""
    return _group("shear", "tabulatedStress")


def torsion_rules() -> Any | None:
    return _group("torsion", "equivalentShear")


def punching_rules() -> Any | None:
    return _group("punching", "rootStress")


def wall_rules() -> Any | None:
    return _group("walls")


def cite(key: str) -> str:
    """The pack's clause ``key`` of ``concreteMethods`` with the code's name ('' if none)."""
    return code_context.cite("concreteMethods", key)


def _paren(key: str) -> str:
    found = cite(key)
    return f" ({found})" if found else ""


def gamma_s() -> float:
    from saengine.design import design_strength

    return float(design_strength.rules().gammaS)


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:]), strict=False):
        if x0 <= x <= x1:
            return float(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return float(ys[-1])


def tau_c(fck: float, pt: float, r: Any | None = None, d: float | None = None) -> float:
    """τc [MPa] at steel ratio ``pt`` [%] and grade ``fck`` [MPa]; alpha 9 C10: times the
    pack's depth factor at the effective depth ``d`` [mm] where it gives one."""
    r = r or rules()
    by_grade = [
        _interp(pt, list(r.steelRatios), [row[g] for row in r.tauC]) for g in range(len(r.grades))
    ]
    return _interp(fck, list(r.grades), by_grade) * depth_factor(d, r)


def depth_factor(d: float | None, r: Any | None = None) -> float:
    """Alpha 9 C10: (reference / d)^exponent at least ``min`` of the pack's
    ``shear.depthFactor`` (BS 8110-1 Table 3.8, (400/d)^1/4 >= 1); 1 without it or ``d``."""
    r = r or rules()
    f = getattr(r, "depthFactor", None)
    if f is None or not d or d <= 0:
        return 1.0
    return max(float(f.min), (float(f.reference) / d) ** float(f.exponent))


def tau_c_max(fck: float, r: Any | None = None) -> float:
    """τc,max [MPa] of grade ``fck``."""
    r = r or rules()
    return _interp(fck, list(r.grades), list(r.maxStress))


def slab_factor(depth: float, r: Any | None = None) -> float:
    """k of solid slabs by their overall depth [mm] (1 without the pack's rows)."""
    r = r or rules()
    rows = sorted(r.slabDepths)
    if not rows:
        return 1.0
    return _interp(depth, [a for a, _ in rows], [k for _, k in rows])


def stirrup_yield(fy: float, r: Any | None = None) -> float:
    """fyd of stirrups [MPa]: min(fy, fyMax) / γs."""
    r = r or rules()
    return min(fy, r.fyMax) / gamma_s()


def least_stirrups(b: float, spacing: float, fy: float, r: Any | None = None) -> float:
    """The least Asv [mm²] at spacing ``spacing``."""
    r = r or rules()
    return r.minStirrupStress * b * spacing / stirrup_yield(fy, r)


def beam_shear(section: Any, stirrup_dia: float | None, legs: int, spacing: float | None) -> Any:
    """The shear resistance of a rectangular beam as :class:`saengine.design.rc.Shear` (see the
    module notes; ``phi_vn`` is the design resistance min(Vc + Vus, τc,max b d))."""
    from saengine.design.rc import DesignError, RectangleProfile, Shear, bar_area

    r = rules()
    if not isinstance(section.profile, RectangleProfile):
        raise DesignError("shear is checked for rectangular beams only")
    b = section.profile.xDim
    try:
        d = section.effective_depth(top=False)
    except DesignError:
        d = section.effective_depth(top=True)
    faces = [
        sum(bar.area for bar in section.bars if (bar.y > 0 if top else bar.y < 0))
        for top in (True, False)
    ]
    rho = min(a for a in faces if a > 0) / (b * d)
    pt = 100 * rho
    tc = tau_c(section.fc, pt, r, d)
    tmax = tau_c_max(section.fc, r)
    fyd = stirrup_yield(section.fy, r)
    av = legs * bar_area(stirrup_dia) if stirrup_dia and spacing else 0.0
    av_min = least_stirrups(b, spacing, section.fy, r) if av else 0.0
    vc = tc * b * d
    vus = fyd * av * d / spacing if av else 0.0
    vmax = tmax * b * d
    limited = vc + vus > vmax
    resistance = min(vc + vus, vmax)
    with_min = av > 0 and av >= av_min
    notes = [
        (
            f"Vc = τc b d = {vc / 1e3:.1f} kN (τc = {tc:.3f} MPa at pt = {pt:.2f} %, "
            f"fck {section.fc:g} MPa), Vus = fyd Asv d / sv = {vus / 1e3:.1f} kN "
            f"(fyd = {fyd:.0f} MPa){_paren('shear')}"
        )
    ]
    if limited:
        notes.append(f"limited to τc,max b d = {vmax / 1e3:.1f} kN (τc,max = {tmax:.2f} MPa)")
    if stirrup_dia is None or not spacing:
        notes.append("no stirrups")
    elif not with_min:
        notes.append(f"Asv = {av:.0f} mm² below the least {av_min:.0f} mm²{_paren('shearMinimum')}")
    return Shear(
        resistance,
        vc,
        min(vus, max(vmax - vc, 0.0)),
        limited,
        d,
        av,
        av_min,
        rho,
        1.0,
        with_min,
        vc,
        notes=tuple(notes),
        threshold=0.5 * vc,
    )


def axial_factor(pu: float, ag: float, fck: float, r: Any | None = None) -> float:
    """δ of τc in a member under the axial force ``pu`` [N, compression positive]:
    1 + axialFactor Pu / (Ag fck), at most ``axialMax`` (IS 456 40.2.2). Under net tension
    the same line downwards, not below 0 (SAEngine practice, on the safe side: IS 456 gives
    no tension rule). 1 without the pack's ``axialFactor``."""
    r = r or rules()
    if r.axialFactor is None or ag <= 0 or fck <= 0:
        return 1.0
    delta = 1.0 + r.axialFactor * pu / (ag * fck)
    if r.axialMax is not None:
        delta = min(delta, r.axialMax)
    return max(delta, 0.0)


def column_rows(section: Any, transverse: Any | None, points: Any) -> list[dict[str, Any]]:
    """Shear rows of a column by the tabulated design shear strength (alpha 9 C9b), one per
    axis of :func:`saengine.design.column_shear.shear_axes`: Vc = δ τc bw d with δ of
    :func:`axial_factor` at each point's axial force, τc at pt of the bars in the far half
    (a circle: half its bars), Vus = fyd Asv d / sv of the ties along the shear, at most
    τc,max bw d; the governing point per axis. Where ties are needed (Vu > Vc) their spacing
    at most min(share d, mm) of the pack's ``shear.spacing``. ``points``:
    :class:`saengine.design.column_shear.ShearPoints` or (Pu, Vx, Vy, combination, where)."""
    import numpy as np

    from saengine.design.column_shear import shear_axes

    r = rules()
    if hasattr(points, "pu"):
        pu = np.asarray(points.pu, dtype=float)
        vx = np.asarray(points.vx, dtype=float)
        vy = np.asarray(points.vy, dtype=float)
        label = points.label
    else:
        listed = list(points)
        pu = np.array([p[0] for p in listed], dtype=float)
        vx = np.array([p[1] for p in listed], dtype=float)
        vy = np.array([p[2] for p in listed], dtype=float)

        def label(i: int) -> tuple[Any, str]:
            return listed[i][3], listed[i][4]

    if not len(pu):
        return []
    fck, ag = section.fc, section.gross_area
    tmax = tau_c_max(fck, r)
    fyd = stirrup_yield(section.fy, r)
    axes = shear_axes(section, transverse)
    circle = len(axes) == 1
    delta = np.ones_like(pu)
    if r.axialFactor is not None and ag > 0:
        delta = 1.0 + r.axialFactor * pu / (ag * fck)
        if r.axialMax is not None:
            delta = np.minimum(delta, r.axialMax)
        delta = np.maximum(delta, 0.0)
    rows = []
    for part in axes:
        if circle:
            far = 0.5 * section.steel_area
            vu = np.hypot(vx, vy)
        else:
            coordinate = (lambda b: b.y) if part.axis == "y" else (lambda b: b.x)
            far = sum(b.area for b in section.bars if coordinate(b) < -1.0)
            vu = np.abs(vy if part.axis == "y" else vx)
        if far <= 0:
            far = 0.5 * section.steel_area
        pt = 100 * far / (part.bw * part.d)
        tc = tau_c(fck, pt, r, part.d)
        vus = fyd * part.av * part.d / part.spacing if part.av and part.spacing else 0.0
        vmax = tmax * part.bw * part.d
        vc = delta * tc * part.bw * part.d
        resistance = np.minimum(vc + vus, vmax)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(resistance > 0, vu / resistance, np.where(vu > 0, np.inf, 0.0))
        i = int(np.argmax(ratio))
        combination, where = label(i)
        name = "Column shear" if circle else f"Column shear along {part.axis}"
        note = (
            f"Pu = {pu[i] / 1e3:.0f} kN, δ = {delta[i]:.2f} (1 + {r.axialFactor or 0:g} Pu/(Ag "
            f"fck){_paren('columnShear')}), Vc = δ τc bw d = {vc[i] / 1e3:.1f} kN (τc = "
            f"{tc:.3f} MPa at pt = {pt:.2f} %), Vus = fyd Asv d / sv = {vus / 1e3:.1f} kN, bw = "
            f"{part.bw:.0f} mm, d = {part.d:.0f} mm; at most τc,max bw d = {vmax / 1e3:.1f} kN"
        )
        if not part.av:
            note += "; no ties"
        if where:
            note += f"; {where}"
        rows.append(
            _row(
                f"{name}{_paren('shear')}",
                vu[i] / 1e3,
                resistance[i] / 1e3,
                "kN",
                combination,
                note,
            )
        )
        needed = np.flatnonzero(vu > vc)
        if part.spacing and len(needed):
            share, most = r.spacing
            limit = min(share * part.d, most)
            j = int(needed[int(np.argmax(vu[needed] - vc[needed]))])
            combination_s, where_s = label(j)
            rows.append(
                _row(
                    f"{name}: tie spacing{_paren('shearSpacing')}",
                    part.spacing,
                    limit,
                    "mm",
                    combination_s,
                    f"Vu > Vc: ties for shear at most min({share:g} d, {most:g} mm), d = "
                    f"{part.d:.0f} mm" + (f"; {where_s}" if where_s else ""),
                )
            )
    return rows


def required_stirrups(vu: float, b: float, d: float, fck: float, fy: float, pt: float) -> float:
    """Asv / sv [mm²/mm] for Vu [N] (the larger of the shear's and the least)."""
    r = rules()
    fyd = stirrup_yield(fy, r)
    need = max(vu - tau_c(fck, pt, r, d) * b * d, 0.0) / (fyd * d)
    return max(need, r.minStirrupStress * b / fyd)


# ─────────────────────────────── torsion ───────────────────────────────


def _row(name: str, demand: float, capacity: float, unit: str, combination: Any, note: str):
    from saengine.design.check import _check

    return _check(name, demand, capacity, unit, combination, note)


def torsion_rows(
    section: Any,
    cover: float,
    stirrups: tuple[float, int, float] | None,
    points: list[tuple[float, float, float, str, str]],
    capacities: dict[bool, Any],
) -> list[dict[str, Any]]:
    """The equivalent shear, equivalent moment and transverse steel rows of a beam at its
    governing station. ``points``: (Tu, Vu, Mu [N, N·mm; Mu + hogging], combination, where);
    ``capacities``: the flexural capacities (False sagging, True hogging)."""
    from saengine.design.rc import bar_area

    t = torsion_rules()
    r = rules()
    if t is None or r is None or not points:
        return []
    if max(abs(p[0]) for p in points) < TORSION_FLOOR:
        return []  # numerical noise of the analysis, not a torsion
    b, depth = section.width, section.depth
    tdia = section.transverse_dia or (stirrups[0] if stirrups else 8.0)
    x1 = b - 2 * cover - tdia
    y1 = depth - 2 * cover - tdia
    d1 = y1
    try:
        d = section.effective_depth(top=False)
    except Exception:  # noqa: BLE001 - no bottom bars: the top's
        d = section.effective_depth(top=True)
    shear = beam_shear(section, *(stirrups if stirrups else (None, 0, None)))
    pt = 100 * shear.rho_w
    fyd = stirrup_yield(section.fy, r)
    tc = tau_c(section.fc, pt, r, d)
    tmax = tau_c_max(section.fc, r)

    def evaluate(point: tuple[float, float, float, str, str]) -> dict[str, float]:
        tu, vu, mu, _, _ = point
        ve = abs(vu) + t.shearFactor * abs(tu) / b
        mt = abs(tu) * (1 + depth / b) / t.momentDivisor
        need = abs(tu) / (x1 * d1 * fyd) + abs(vu) / (t.depthDivisor * d1 * fyd)
        least = max(ve / (b * d) - tc, 0.0) * b / fyd
        return {"ve": ve, "mt": mt, "me": abs(mu) + mt, "need": max(need, least)}

    worst = max(points, key=lambda p: evaluate(p)["ve"])
    found = evaluate(worst)
    rows = [
        _row(
            f"Torsion: equivalent shear{_paren('torsionShear')}",
            found["ve"] / 1e3,
            min(shear.phi_vn, tmax * b * d) / 1e3,
            "kN",
            worst[3],
            f"Ve = Vu + {t.shearFactor:g} Tu / b, Tu = {abs(worst[0]) / 1e6:.2f} kN·m, "
            f"Vu = {abs(worst[1]) / 1e3:.1f} kN, τve <= τc,max = {tmax:.2f} MPa; {worst[4]}",
        )
    ]
    by_moment = max(points, key=lambda p: evaluate(p)["me"])
    moment = evaluate(by_moment)
    capacity = capacities[by_moment[2] > 0]
    rows.append(
        _row(
            f"Torsion: equivalent moment{_paren('torsionMoment')}",
            moment["me"] / 1e6,
            capacity.phi_mn / 1e6,
            "kN·m",
            by_moment[3],
            f"Me1 = Mu + Tu (1 + D/b) / {t.momentDivisor:g}, Mt = {moment['mt'] / 1e6:.2f} kN·m"
            f"; {by_moment[4]}",
        )
    )
    if abs(worst[0]) > 0 and found["ve"] > tc * b * d:
        if stirrups is None:
            provided = 0.0
            spacing_note = "no closed links"
        else:
            dia, _legs, spacing = stirrups
            provided = 2 * bar_area(dia) / spacing  # two legs of the closed link per x1 y1
            spacing_note = f"{dia:g} mm closed links at {spacing:g} mm"
        rows.append(
            _row(
                f"Torsion: transverse steel{_paren('torsionLinks')}",
                found["need"],
                provided,
                "mm²/mm",
                worst[3],
                f"Asv/sv = Tu/(b1 d1 fyd) + Vu/({t.depthDivisor:g} d1 fyd) >= (τve - τc) b / fyd, "
                f"b1 = {x1:.0f} mm, d1 = {d1:.0f} mm; {spacing_note}",
            )
        )
        if stirrups is not None:
            limit = min(x1, (x1 + y1) / t.spacingDivisor, t.spacingMax)
            rows.append(
                _row(
                    f"Torsion: link spacing{_paren('torsionLinks')}",
                    stirrups[2],
                    limit,
                    "mm",
                    worst[3],
                    f"sv <= min(x1, (x1 + y1)/{t.spacingDivisor:g}, {t.spacingMax:g} mm)",
                )
            )
    return rows


@dataclass(frozen=True)
class TorsionNeed:
    """What Design Reinforcement sizes the closed links of a beam in torsion from (the fields
    of :class:`saengine.design.torsion.TorsionDesign` it reads): ``at_s`` the torsion's part of
    one leg [mm²/mm], ``al`` the added longitudinal steel (0: the equivalent moment carries
    it), ``s_max`` the link spacing limit [mm]."""

    at_s: float
    al: float
    s_max: float
    #: Marks the equivalent shear method's need (not the thin-walled tube's TorsionDesign).
    tabulated: bool = True
    #: Alpha 9 C9b, for the required-steel report: Tu, Vu [N·mm, N] of the governing station,
    #: the closed links' Asv/sv of both legs and its least [mm²/mm], and b1, d1 [mm].
    tu: float = 0.0
    vu: float = 0.0
    asv_s: float = 0.0
    asv_s_min: float = 0.0
    b1: float = 0.0
    d1: float = 0.0
    combination: str | None = None


def torsion_need(
    section: Any, cover: float, stirrups: tuple[float, int, float] | None,
    points: list[tuple[float, float, float, str, str]],
) -> TorsionNeed | None:  # fmt: skip
    """The torsion need of the governing station where τve exceeds τc (None below it).

    Alpha 9 C9b: Design Reinforcement sizes from this before the member's own bars are known
    (the first pass checks assumed bars), so τc here is the table's least (its first steel
    ratio): the links are then asked for wherever the bars chosen could leave τve above τc,
    and the closed links carry the whole Asv/sv of the equivalent shear method (``at_s`` is
    half of it per leg, the shear's own stirrups not added: see the proposal). SAEngine
    practice, on the safe side."""
    t, r = torsion_rules(), rules()
    if t is None or r is None or not points or max(abs(p[0]) for p in points) < TORSION_FLOOR:
        return None
    b, depth = section.width, section.depth
    tdia = section.transverse_dia or (stirrups[0] if stirrups else 8.0)
    x1, y1 = b - 2 * cover - tdia, depth - 2 * cover - tdia
    try:
        d = section.effective_depth(top=False)
    except Exception:  # noqa: BLE001
        d = section.effective_depth(top=True)
    tc = tau_c(section.fc, float(r.steelRatios[0]), r, d)
    fyd = stirrup_yield(section.fy, r)
    worst = max(points, key=lambda p: abs(p[1]) + t.shearFactor * abs(p[0]) / b)
    ve = abs(worst[1]) + t.shearFactor * abs(worst[0]) / b
    if ve <= tc * b * d:
        return None
    need = abs(worst[0]) / (x1 * y1 * fyd) + abs(worst[1]) / (t.depthDivisor * y1 * fyd)
    least = max(ve / (b * d) - tc, 0.0) * b / fyd
    total = max(need, least)
    return TorsionNeed(
        total / 2,
        0.0,
        link_spacing_limit(b, depth, cover, tdia, t),
        tu=abs(worst[0]),
        vu=abs(worst[1]),
        asv_s=total,
        asv_s_min=least,
        b1=x1,
        d1=y1,
        combination=worst[3],
    )


def link_spacing_limit(b: float, depth: float, cover: float, dia: float, t: Any | None = None):
    """The closed links' largest spacing [mm] of the equivalent shear method: min(x1, (x1 +
    y1) / spacingDivisor, spacingMax), x1 and y1 the link's sides at bar ``dia``."""
    t = t or torsion_rules()
    x1, y1 = b - 2 * cover - dia, depth - 2 * cover - dia
    return min(x1, (x1 + y1) / t.spacingDivisor, t.spacingMax)


# ─────────────────────────────── punching ───────────────────────────────


def punching_stress(fck: float, short: float, long: float) -> float:
    """ks τc [MPa] of the punching shear (no shear reinforcement)."""
    p = punching_rules()
    beta = short / long if long > 0 else 1.0
    ks = min(1.0, p.ratioBase + beta)
    return ks * p.coefficient * math.sqrt(fck)


def punching_row(
    vu: float,
    b0: float,
    d: float,
    fck: float,
    short: float,
    long: float,
    combination: Any,
    where: str,
    extra: float = 0.0,
) -> dict[str, Any]:
    """The punching row: τv = (Vu + extra) / (b0 d) [MPa] against ks τc. ``extra``: the share of
    an unbalanced moment as a shear [N] where the caller has it."""
    p = punching_rules()
    allowed = punching_stress(fck, short, long)
    tv = (vu + extra) / (b0 * d) if b0 > 0 and d > 0 else math.inf
    return _row(
        f"Punching shear{_paren('punching')}",
        tv,
        allowed,
        "MPa",
        combination,
        f"τv = Vu/(b0 d), b0 = {b0:.0f} mm at {p.perimeterDistance:g} d, d = {d:.0f} mm; "
        f"ks τc = (0.5 + βc <= 1) × {p.coefficient:g} √fck = {allowed:.3f} MPa; with shear "
        f"reinforcement τv <= {p.reinforcedMax:g} τc and the steel for Vu - "
        f"{p.concreteShare:g} Vc; {where}",
    )


# ─────────────────────────────── walls ───────────────────────────────


def wall_shear_strength(fck: float, height: float, length: float) -> float:
    """τcw [MPa] of a wall of height Hw and length Lw by its aspect ratio."""
    w = wall_rules()
    aw = height / length if length > 0 else 1.0
    first = (w.shearIntercept - min(aw, w.shearIntercept)) * w.shearK1 * math.sqrt(fck)
    if aw <= 1.0:
        return first
    second = w.shearK2 * fck * (aw + 1) / (aw - 1)
    return min(first, second)


def wall_effective_height(clear_height: float, k: float) -> float:
    """Hwe [mm] of a wall: k × the clear height with SAEngine's k of the wall's bracing
    (1.0 braced, 0.8 restrained against rotation, 2.0 unbraced), read as 0.75 for walls braced
    and restrained (the IS 456 32.2.4 type of effective height; SAEngine practice)."""
    return (0.75 if k == 0.8 else k) * clear_height


def wall_axial_rows(geometry: Any, forces: list[Any], fck: float, k: float) -> list[dict[str, Any]]:
    """The empirical wall rows (alpha 9 C9b, the pack's ``walls`` group): the slenderness
    Hwe / t at most ``slendernessMax``, and where every compressive force acts within the middle
    third of the thickness, Pu <= Puw = axialFactor (t - eccentricityFactor e - 2 ea) fck Lw,
    e = M2/P at least minEccentricityShare × t, ea = Hwe² / (additionalDivisor t) (informative:
    the P-M3-M2 surface governs, as for the parent's empirical method)."""
    w = wall_rules()
    t, lw = float(geometry.thickness), float(geometry.length)
    hwe = wall_effective_height(float(geometry.clear_height), k)
    rows = [
        _row(
            f"Wall slenderness Hwe / t{_paren('walls')}",
            hwe / t,
            w.slendernessMax,
            "",
            None,
            f"Hwe = {hwe:.0f} mm (k = {hwe / geometry.clear_height:.2f} of the clear height), "
            f"t = {t:.0f} mm",
        )
    ]
    compressed = [f for f in forces if f.P > 0]
    if not compressed or not all(abs(f.M2) / f.P <= t / 6 for f in compressed):
        return rows
    ea = hwe**2 / (w.additionalDivisor * t)
    worst = None
    for f in compressed:
        e = max(abs(f.M2) / f.P, w.minEccentricityShare * t)
        puw = w.axialFactor * max(t - w.eccentricityFactor * e - 2 * ea, 0.0) * fck * lw
        ratio = f.P / puw if puw > 0 else math.inf
        if worst is None or ratio > worst[0]:
            worst = (ratio, f, e, puw)
    _, f, e, puw = worst
    row = _row(
        f"Wall axial strength Puw{_paren('wallAxial')}",
        f.P / 1e3,
        puw / 1e3,
        "kN",
        f.combination,
        f"Puw = {w.axialFactor:g} (t - {w.eccentricityFactor:g} e - 2 ea) fck Lw, e = {e:.1f} "
        f"mm (>= {w.minEccentricityShare:g} t), ea = Hwe²/({w.additionalDivisor:g} t) = "
        f"{ea:.1f} mm; resultant within the middle third; the P-M3-M2 surface governs",
    )
    row["flag"] = True
    rows.append(row)
    return rows


def wall_shear_row(
    vu: float,
    t: float,
    length: float,
    height: float,
    fck: float,
    fy: float,
    ah_per_spacing: float,
    combination: Any,
) -> dict[str, Any]:
    """The in-plane shear row of a wall: Vu <= min((τcw t d + fyd Ah d / Sv), shearMaxShare fck
    t d)."""
    w = wall_rules()
    d = w.depthShare * length
    tcw = wall_shear_strength(fck, height, length)
    fyd = fy / gamma_s()
    vc = tcw * t * d
    vus = fyd * ah_per_spacing * d
    vmax = w.shearMaxShare * fck * t * d
    return _row(
        f"In-plane shear{_paren('wallShear')}",
        vu / 1e3,
        min(vc + vus, vmax) / 1e3,
        "kN",
        combination,
        f"τcw = {tcw:.3f} MPa (Hw/Lw = {height / length:.2f}), d = {w.depthShare:g} Lw = "
        f"{d:.0f} mm, Vc = {vc / 1e3:.1f} kN, Vus = fyd Ah d / Sv = {vus / 1e3:.1f} kN, at most "
        f"{w.shearMaxShare:g} fck t d = {vmax / 1e3:.1f} kN",
    )


# ─────────────────────────────── report ───────────────────────────────


def method_lines(code: str) -> list[str]:
    """The design report's method lines of the tabulated methods (in place of the strength
    design's lines on the basis, flexure, beams, torsion, deflection and columns)."""
    from saengine.design import design_strength

    u = design_strength.rules()
    r = rules()
    # Alpha 9 C10: the block's force and centroid from the pack's values (IS 456: 0.36 fck xu
    # at 0.42 xu; BS 8110: 0.405 fcu x at 0.45 x).
    rel = u.relations
    force = float(rel.eta.base) * u.alphaCC / u.gammaC * float(rel.lam.base)
    block = (
        f"the rectangular block equivalent to the parabola-rectangle ({force:.3g} fck xu at "
        f"{float(rel.lam.base) / 2:.3g} xu)"
        if u.stressBlock == "rectangular"
        else "the parabola-rectangle diagram (0.002, 0.0035)"
    )
    e_text = (
        "emin = "
        + (f"l/{u.eccentricityLengthDivisor:g} + " if u.eccentricityLengthDivisor else "")
        + f"D/{u.eccentricityDivisor:g}"
    )
    if u.eccentricityMin >= 1:
        e_text += f" >= {u.eccentricityMin:g} mm"
    if u.eccentricityMax is not None:
        e_text += f" <= {u.eccentricityMax:g} mm"
    from saengine.design import additional_moment

    col = additional_moment.rules()
    divisor = f"{col.slenderness.divisor:g}" if col is not None else "2000"
    biaxial = (
        "biaxial bending by the load contour (Mux/Mux1)^αn + (Muy/Muy1)^αn <= 1"
        f"{_paren('biaxial')}, Mux1 and Muy1 from the interaction surface at Pu"
        if col is None or col.biaxial.method == "loadContour"
        else f"biaxial bending by the interaction surface at Pu{_paren('biaxial')}"
    )
    torsion = (
        [
            (
                "Beam torsion by the equivalent shear Ve = Vu + 1.6 Tu/b and moment Me1 = Mu + "
                f"Tu (1 + D/b)/1.7 with closed links for Tu and Vu{_paren('torsion')} (the "
                "pack's factors)."
            )
        ]
        if torsion_rules() is not None
        else []
    )
    shares = u.axialShares
    cap = (
        f"Pu <= {shares[0]:g} fck Ac + {shares[1]:g} fy Asc"
        if shares
        else "NRd of the stress block"
    )
    return [
        (
            f"Limit state design to {code}: design strengths {u.alphaCC:g} fck / γm (γm = "
            f"{u.gammaC:g}) and fy / γs (γs = {u.gammaS:g}), no strength reduction factor"
            f"{_paren('designStrength')}."
        ),
        (
            f"Flexure and axial force by strain compatibility with {block}, the bars "
            f"elastic-perfectly plastic at fy / γs; the neutral axis of beams at most xu,max"
            f"{_paren('ultimate')}."
        ),
        (
            "Beams: sagging and hogging moments about the strong axis; shear τv = Vu/(b d) "
            f"against τc of the pack's table by pt and the grade, Vus = fyd Asv d / sv, τv <= "
            f"τc,max{_paren('shear')}; least stirrups Asv/(b sv) >= {r.minStirrupStress:g}/fyd "
            f"where τv > τc/2{_paren('shearMinimum')}; least and largest steel, side face steel, "
            f"cover by the exposure condition and the development and lap lengths by the design "
            f"bond stress{_paren('beamSteel')}."
        ),
        *torsion,
        (
            "Beam deflection: the span / effective depth ratio with the modification factors of "
            "the tension and compression steel and the flanges, and the deflection from the "
            "analysis scaled to Ieff with creep and shrinkage (final at most span/250, after the "
            f"partitions span/350 or 20 mm){_paren('deflection')}."
        ),
        (
            f"Columns: axial force with biaxial bending, {cap}, the moments at least Pu emin "
            f"about both axes at once ({e_text}{_paren('minimumEccentricity')}); "
            f"slender columns (lex/D above the limit) with the additional moments Pu D/{divisor} "
            f"(lex/D)² reduced by k = (Puz - Pu)/(Puz - Pb){_paren('slenderness')}; {biaxial}; "
            f"least and largest steel, bars, ties{_paren('columnSteel')}."
        ),
    ] + _remainder_lines(r)


def _remainder_lines(r: Any) -> list[str]:
    """Alpha 9 C9b: the method lines of the column shear, the sections near the supports, deep
    beams, corbels and walls, where the pack gives them."""
    t = _table()
    lines = []
    if r.axialFactor is not None:
        lines.append(
            f"Column shear by τc × δ, δ = 1 + {r.axialFactor:g} Pu/(Ag fck)"
            + (f" <= {r.axialMax:g}" if r.axialMax else "")
            + f" (net tension: the same line, not below 0){_paren('columnShear')}; the ties as "
            "stirrups along each axis."
        )
    if cite("nearSupport"):
        lines.append(
            "Beam shear at d from the support faces (the sections nearer carry the same steel); "
            f"the enhanced τc × {r.enhancement:g} d / av near a support is used for corbels only, "
            f"not for beams (on the safe side){_paren('nearSupport')}."
        )
    if getattr(t, "deepBeams", None) is not None:
        lines.append(
            "Deep beams (l/D below the pack's limits) by the lever arm z: the tension steel for "
            "the largest sagging moment, its zone at the soffit, the side face steel as walls"
            f"{_paren('deepBeams')}; the sectional shear rows stay the shear check."
        )
    if getattr(t, "corbels", None) is not None:
        lines.append(
            "Corbels (av < d) by the tie at the root for Vu av + Nuc (h - d) with the design "
            "strengths, shear at the face with the enhanced τc and the closed links, the links "
            f"at least half the main bars{_paren('corbels')}."
        )
    w = getattr(t, "walls", None)
    if w is not None:
        lines.append(
            f"Walls: the empirical axial strength Puw = {w.axialFactor:g} (t - "
            f"{w.eccentricityFactor:g} e - 2 ea) fck Lw where the load is within the middle third "
            f"(informative){_paren('wallAxial')}, the slenderness Hwe/t at most "
            f"{w.slendernessMax:g}{_paren('walls')}."
        )
    return lines
