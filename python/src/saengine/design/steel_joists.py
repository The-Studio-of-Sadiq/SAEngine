"""Open-web steel joists and joist girders (alpha 9 L7): a beam type with a ``joist``
(:class:`saengine.library.objects.SteelJoist`) is designed as a parallel-chord truss from the
member's moment and shear diagrams under the strength combinations.

**Every pack (the generic open-web truss).** The chords carry the moment as axial forces N =
M / d (d between the chords' centroids), the webs the shear as V / sin θ; each part is
checked by the code pack's own steel member method (:mod:`saengine.design.steel.
pack_resistance`): the top chord in compression over the panel length in the plane and the
bridging (or the deck's panel points) out of it, the bottom chord the same under reversed
moment, the webs in tension and in compression over their length. The deck's load between
panel points bends the top chord (M = w l² / 8 of a simple panel without the pack's rule;
joist girders carry their load at panel points: no panel moment); it is combined with the axial
force linearly. The deflection: the analysis carries the type's profile; the deflection rows
(the pack's serviceability limits, :func:`saengine.design.check._steel_deflection`) are scaled
by the profile's inertia over the truss's effective inertia, the chords' I reduced for the
webs' shear deformation by virtual work (:func:`effective_inertia`).

**A pack with the steelJoists table** adds the joist specification's rules: the slenderness
limits, the top chord's panel moments w l² / divisor (end and interior panels) with the
bilinear interaction, the webs' least shear as a share of the end reaction, K of compression
webs, the bridging rows the chords' slenderness needs, and the catalogue rating of a joist
with a ``designation`` in the pack's load tables (interpolated at the span).

Units: mm, MPa, N, N·mm; reported in kN, kN·m.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from saengine.codes import context as code_context

TABLE = "steelJoists"


class JoistDesignError(ValueError):
    """A joist that cannot be checked."""


def table() -> Any | None:
    try:
        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - no pack machinery
        return None


def _clause(key: str, fallback: str = "") -> str:
    t = table()
    if t is None:
        return fallback
    return str(t.clauses.get(key, "")) or fallback


def _pack_name() -> str:
    try:
        return str(code_context.current().name)
    except Exception:  # noqa: BLE001
        return "the code pack"


def part_shape(member: Any) -> Any:
    """The ShapeProperties of a chord or web (two back to back when ``double``)."""
    from saengine.design.steel.pack_resistance import doubled
    from saengine.design.steel.properties import shape_properties

    try:
        shape = shape_properties(member.profile, False)
    except ValueError as error:
        raise JoistDesignError(f"joist member: {error}") from error
    return doubled(shape) if member.double else shape


def geometry(joist: Any, span: float) -> dict[str, Any]:
    """The truss of a joist over ``span`` [mm]: chord shapes, d between the chords' centroids,
    the panels, the webs' length and sin θ."""
    from saengine.design.steel.pack_resistance import outer_distance

    top = part_shape(joist.topChord)
    bottom = part_shape(joist.bottomChord)
    web = part_shape(joist.webs)
    d = float(joist.depth) - outer_distance(top) - outer_distance(bottom)
    if d <= 0:
        raise JoistDesignError("the chords are deeper than the joist")
    panels = max(2, round(span / float(joist.panel)))
    p = span / panels
    run = p / 2 if joist.web == "warren" else p
    length = math.hypot(run, d)
    return {
        "top": top,
        "bottom": bottom,
        "web": web,
        "d": d,
        "panels": panels,
        "p": p,
        "run": run,
        "webLength": length,
        "sin": d / length,
        "vertical": d if joist.web == "pratt" else 0.0,
    }


def effective_inertia(g: dict[str, Any], span: float, e: float) -> tuple[float, float]:
    """(I of the chords, effective I) [mm⁴]: the chords' I about their common centroid,
    reduced for the webs' shear deformation under a uniform load by virtual work (each
    diagonal's F f L / (E A); the verticals of a Pratt truss likewise)."""
    at, ab = g["top"].area, g["bottom"].area
    d = g["d"]
    i_ch = at * ab * d**2 / (at + ab) + g["top"].ix + g["bottom"].ix
    w = 1.0  # N/mm: the ratio does not depend on it
    bending = 5 * w * span**4 / (384 * e * i_ch)
    a_w = g["web"].area
    shear = 0.0
    step = g["run"]
    x = step / 2
    while x < span:
        v = w * (span / 2 - x)  # shear under the uniform load
        unit = 0.5 if x < span / 2 else -0.5  # shear of a unit load at mid-span
        shear += v * unit * g["webLength"] / (e * a_w * g["sin"] ** 2)
        if g["vertical"] > 0:
            shear += v * unit * g["vertical"] / (e * a_w)
        x += step
    return i_ch, i_ch * bending / (bending + max(shear, 0.0))


def _rating(designation: str, span: float) -> tuple[float, str] | None:
    """The catalogue's total load capacity [N/mm] of ``designation`` at ``span`` [mm]
    (interpolated, None outside the row's spans or without the row)."""
    t = table()
    if t is None:
        return None
    row = next((r for r in t.loadTables if r.designation == designation), None)
    if row is None:
        return None
    pts = sorted((float(s.span) * 1e3, float(s.total)) for s in row.spans)
    if not pts[0][0] - 1 <= span <= pts[-1][0] + 1:
        return None
    xs, ys = zip(*pts, strict=True)
    return float(np.interp(span, xs, ys)), f"{designation}: {len(pts)} spans of the load table"


def check_joist(
    joist: Any, material: Any, stations: Sequence[Any], span: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The checks of one joist (``span`` [mm]) from the member's ``stations`` and its summary."""
    from saengine.design.steel import pack_resistance as pr
    from saengine.design.steel.members import Steel, SteelDesignError, _check, _ratio, _Worst

    try:
        steel = Steel.of(material)
    except SteelDesignError as error:
        raise JoistDesignError(str(error)) from error
    t = table()
    g = geometry(joist, span)
    top, bottom, web = g["top"], g["bottom"], g["web"]
    p, d = g["p"], g["d"]
    girder = joist.kind == "joistGirder"
    lbr = float(joist.bridging) if joist.bridging else span
    top_out = p if joist.deckBraced and not girder else lbr
    web_k = float(t.webK) if t is not None else 1.0
    lw = g["webLength"]
    generic = (
        "" if t is not None else f" (generic open-web truss: {_pack_name()} has no joist rules)"
    )

    # The parts' resistances (the pack's steel method).
    top_c, top_c_clause, top_c_note = pr.axial(top, steel, p, top_out, True)
    top_t, top_t_clause, _ = pr.axial(top, steel, p, top_out, False)
    bot_c, bot_c_clause, bot_c_note = pr.axial(bottom, steel, p, lbr, True)
    bot_t, bot_t_clause, _ = pr.axial(bottom, steel, p, lbr, False)
    web_c, web_c_clause, web_c_note = pr.axial(web, steel, web_k * lw, web_k * lw, True)
    web_t, web_t_clause, _ = pr.axial(web, steel, lw, lw, False)
    top_m, top_m_clause, top_m_note = pr.elastic_moment(top, steel)

    w = {k: _Worst() for k in ("tc", "tt", "bc", "bt", "wc", "wt", "ti")}
    for st in stations:
        s = np.asarray(st.s, dtype=float) * 1e3
        m = np.asarray(st.Mx, dtype=float)
        v = np.abs(np.asarray(st.Vy, dtype=float))
        if len(s) < 2:
            continue
        reaction = max(float(v[0]), float(v[-1]))
        load = (float(v[0]) + float(v[-1])) / max(span, 1.0)  # N/mm, the uniform equivalent
        for k in range(len(s)):
            # Mx > 0 stretches the top: the top chord in tension, the bottom in compression.
            n_top = float(m[k]) / d
            where = st.where[k]
            if n_top < 0:
                ncomp = -n_top
                end = s[k] < p or s[k] > span - p
                if girder:
                    m_panel = 0.0
                elif t is not None:
                    div = float(t.panelMoment.endPanel if end else t.panelMoment.interiorPanel)
                    m_panel = load * p**2 / div
                else:
                    m_panel = load * p**2 / 8
                w["tc"].offer(
                    _ratio(ncomp, top_c), ncomp, top_c, st.combination,
                    f"N = M / d, d = {d:.0f} mm; {top_c_note}; {where}", top_c_clause,
                )  # fmt: skip
                pc, mc = _ratio(ncomp, top_c), _ratio(m_panel, top_m)
                if t is not None and t.interaction == "bilinear":
                    r = pc + 8 / 9 * mc if pc >= 0.2 else pc / 2 + mc
                    form = "bilinear"
                else:
                    r = pc + mc
                    form = "linear"
                w["ti"].offer(
                    r, r, 1.0, st.combination,
                    f"panel moment {m_panel / 1e6:.2f} kN·m over l = {p:.0f} mm ({form}); "
                    f"{top_m_note}; {where}",
                    _clause("panelMoment", top_m_clause),
                )  # fmt: skip
                w["bt"].offer(
                    _ratio(ncomp, bot_t), ncomp, bot_t, st.combination, where, bot_t_clause
                )
            elif n_top > 0:
                w["tt"].offer(
                    _ratio(n_top, top_t), n_top, top_t, st.combination, where, top_t_clause
                )
                w["bc"].offer(
                    _ratio(n_top, bot_c), n_top, bot_c, st.combination,
                    f"reversed (uplift) moment; {bot_c_note}; {where}", bot_c_clause,
                )  # fmt: skip
            shear = float(v[k])
            if t is not None:
                shear = max(shear, float(t.leastWebShare) * reaction)
            f = shear / g["sin"]
            note = f"V / sin θ, θ = {math.degrees(math.asin(g['sin'])):.0f}°; {where}"
            w["wc"].offer(
                _ratio(f, web_c), f, web_c, st.combination, f"{note}; {web_c_note}", web_c_clause
            )
            w["wt"].offer(_ratio(f, web_t), f, web_t, st.combination, note, web_t_clause)
    checks: list[dict[str, Any]] = []
    for key, name in (
        ("tc", "Joist top chord: compression"),
        ("ti", "Joist top chord: axial force and panel moment"),
        ("tt", "Joist top chord: tension (reversed moment)"),
        ("bt", "Joist bottom chord: tension"),
        ("bc", "Joist bottom chord: compression (reversed moment)"),
        ("wc", "Joist webs: compression"),
        ("wt", "Joist webs: tension"),
    ):
        if w[key].combination is not None:
            row = _check(name, w[key], "" if key == "ti" else "kN", 1.0 if key == "ti" else 1e3)
            row["note"] += generic
            checks.append(row)
    checks += _rules(joist, g, span, lbr, top_out, web_k)
    if joist.designation:
        rated = _rating(joist.designation, span)
        demand = max(
            (
                8 * float(np.max(np.abs(np.asarray(st.Mx, dtype=float)))) / span**2
                for st in stations
                if len(st.s)
            ),
            default=0.0,
        )
        if rated is not None:
            u = _ratio(demand, rated[0])
            checks.append(
                {
                    "name": "Joist load table rating",
                    "demand": round(demand, 2),
                    "capacity": round(rated[0], 2),
                    "unit": "kN/m",
                    "utilisation": round(u, 3) if math.isfinite(u) else 99.0,
                    "combination": None,
                    "ok": bool(u <= 1.0),
                    "note": f"uniform equivalent w = 8 Mmax / L²; {rated[1]} "
                    f"({t.loadFormat if t is not None else ''} format)",
                    "flag": False,
                    "clause": _clause("loadTable"),
                }
            )
    for c in checks:
        if c["utilisation"] < 0:
            c.update(utilisation=0.0, ok=True, demand=0.0)
    i_ch, i_eff = effective_inertia(g, span, steel.e)
    summary = {
        "kind": joist.kind,
        "designation": joist.designation,
        "depth": float(joist.depth),
        "d": round(d, 1),
        "panels": g["panels"],
        "panel": round(p, 1),
        "topChord": top.label,
        "bottomChord": bottom.label,
        "webs": web.label,
        "Ichords": i_ch,
        "Ieff": i_eff,
        "mass": round(mass_per_metre(joist, material, span), 2),
        "bridging": _bridging(g, span) if t is not None and not joist.bridging else None,
        "generic": t is None,
    }
    return checks, summary


def _rules(joist: Any, g: dict[str, Any], span: float, lbr: float, top_out: float, k: float):
    """The specification's slenderness checks (none without the pack's table)."""
    t = table()
    if t is None:
        return []
    sl = t.slenderness
    top, bottom, web = g["top"], g["bottom"], g["web"]
    rows = []

    def row(name: str, ratio: float, limit: float, note: str) -> None:
        u = ratio / limit
        rows.append(
            {
                "name": name,
                "demand": round(ratio, 1),
                "capacity": round(float(limit), 1),
                "unit": "",
                "utilisation": round(u, 3),
                "combination": None,
                "ok": bool(u <= 1.0),
                "note": note,
                "flag": False,
                "clause": _clause("slenderness"),
            }
        )

    row(
        "Joist top chord: slenderness (interior panels)",
        g["p"] / top.rx,
        float(sl.topChordInterior),
        f"l / rx, l = {g['p']:.0f} mm",
    )
    row(
        "Joist top chord: slenderness out of the plane",
        top_out / top.ry,
        float(t.bridging.topChord),
        f"L / ry between bridging, L = {top_out:.0f} mm",
    )
    row(
        "Joist webs: slenderness (compression)",
        k * g["webLength"] / max(min(web.rx, web.ry, web.rz), 1e-9),
        float(sl.compressionWeb),
        f"K L / rmin, L = {g['webLength']:.0f} mm",
    )
    row(
        "Joist bottom chord: slenderness between bridging",
        lbr / bottom.ry,
        float(t.bridging.bottomChord),
        f"L / ry, L = {lbr:.0f} mm",
    )
    return rows


def _bridging(g: dict[str, Any], span: float) -> dict[str, Any]:
    """The rows of bridging the chords' slenderness limits need."""
    t = table()
    spacing = min(
        float(t.bridging.topChord) * g["top"].ry, float(t.bridging.bottomChord) * g["bottom"].ry
    )
    rows = max(0, math.ceil(span / spacing) - 1)
    return {"spacingMax": round(spacing), "rows": rows}


def mass_per_metre(joist: Any, material: Any, span: float) -> float:
    """The joist's steel mass [kg/m]: the chords along it and the webs' length per metre."""
    density = (material.mechanical.density if material is not None else None) or 7850.0
    try:
        g = geometry(joist, span)
    except JoistDesignError:
        return 0.0
    web_area = g["web"].area
    per_panel = web_area * (g["webLength"] * (2 if joist.web == "warren" else 1) + g["vertical"])
    area = g["top"].area + g["bottom"].area + per_panel / g["p"]
    return area * 1e-6 * density


def design_member(
    member_id: str,
    object_type: Any,
    material: Any,
    pieces: Sequence[Any],
    combinations: Sequence[str],
    turned: bool,
) -> dict[str, Any]:
    """The design entry of one joist (the steel member's format, kind "beam")."""
    from saengine.design.steel.lengths import positions
    from saengine.design.steel.members import member_stations

    if not pieces:
        raise JoistDesignError("not in the analysis results")
    s, _ = positions(pieces, 2)
    span = float(s[-1] - s[0]) * 1e3
    stations = member_stations(pieces, combinations, turned)
    checks, summary = check_joist(object_type.joist, material, stations, span)
    frame = frame_action(stations)
    if frame is not None:
        checks.append(frame)
        summary["frameAction"] = True
    try:
        from saengine.library.sections import section_properties

        i_profile = float(section_properties(object_type.profile).ixx)
    except Exception:  # noqa: BLE001 - a profile the section tool cannot read
        i_profile = 0.0
    summary["deflection"] = (
        {"stiffening": i_profile / summary["Ieff"], "Ieff": summary["Ieff"]}
        if i_profile > 0 and summary["Ieff"] > 0
        else None
    )
    strength = [c for c in checks if not c["flag"]]
    return {
        "id": member_id,
        "kind": "beam",
        "type": object_type.id,
        "members": [p.id for p in pieces],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "material": material.id,
        "joist": summary,
    }


#: End moments above this share of the joist's largest moment are frame action (W4C-25).
FRAME_ACTION_SHARE = 0.1


def frame_action(stations: Sequence[Any]) -> dict[str, Any] | None:
    """An information row when the joist's ends carry moments (W4C-25 of usability walk 4: a
    joist on a moment-frame line, rigid ends, failed on reversed moment with no hint): a joist
    is a simply supported truss; None when its end moments are small."""
    worst = (0.0, None)
    peak = 0.0
    for st in stations:
        m = np.abs(np.asarray(st.Mx, dtype=float))
        if not len(m):
            continue
        peak = max(peak, float(np.max(m)))
        end = max(float(m[0]), float(m[-1]))
        if end > worst[0]:
            worst = (end, st.combination)
    if peak <= 0 or worst[0] <= FRAME_ACTION_SHARE * peak:
        return None
    return {
        "name": "Frame action: end moments on a joist",
        "demand": round(worst[0] / 1e6, 2),
        "capacity": 0.0,
        "unit": "kN·m",
        "utilisation": 0.0,
        "combination": worst[1],
        "ok": True,
        "note": (
            f"the ends carry {worst[0] / 1e6:.1f} kN·m ({worst[0] / peak:.0%} of the largest "
            "moment): the joist is framed as a moment-frame beam (rigid ends), so it takes end "
            "moments and reversed moment it is not made for; give its type a simple connection "
            "(fin plate or shear end plate: pinned ends) or use a rolled beam on frame lines"
        ),
        "flag": True,
        "clause": "",
    }


def scale_profiles(entry: dict[str, Any], profiles: dict[str, np.ndarray]) -> dict[str, Any]:
    """A joist's displacements per load case: the analysis' (on the type's profile) × I of
    the profile / the truss's effective I. Unchanged for other members."""
    found = (entry.get("joist") or {}).get("deflection")
    if not found:
        return profiles
    k = float(found["stiffening"])
    return {case: moved * k for case, moved in profiles.items()}


def method_lines() -> list[str]:
    t = table()
    base = (
        "Open-web steel joists and joist girders as parallel-chord trusses: the chords carry "
        "M / d, the webs V / sin θ, each part checked by the code pack's steel member method "
        "(the top chord over the panel length in the plane and the bridging or deck out of it, "
        "with the deck's panel moment), the deflection on the chords' inertia reduced for the "
        "webs' shear deformation (virtual work)."
    )
    if t is None:
        return [base + " No joist specification in the code pack: the generic truss alone."]
    return [
        base + f" The joist rules of {_clause('code', 'the pack')}: slenderness "
        f"{float(t.slenderness.topChordInterior):g} / {float(t.slenderness.topChordEnd):g} "
        f"(top chord), {float(t.slenderness.compressionWeb):g} (compression webs), "
        f"{float(t.slenderness.tension):g} (tension); panel moments w l² / "
        f"{float(t.panelMoment.endPanel):g} (end) and / {float(t.panelMoment.interiorPanel):g}; "
        f"webs at least {float(t.leastWebShare):.0%} of the end reaction; bridging by the "
        f"chords' L / ry ≤ {float(t.bridging.topChord):g} / {float(t.bridging.bottomChord):g}."
    ]
