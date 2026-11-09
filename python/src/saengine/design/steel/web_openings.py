"""Castellated and cellular beams (alpha 9 L7): a steel I-beam type with ``webOpenings``
(:class:`saengine.library.objects.BeamWebOpenings`; its profile the finished, expanded
section) is checked at each opening and web post by the code pack's ``webOpenings`` table
(method ``teeChords``: AISC Design Guide 31 in the US pack, SCI P355 in the Eurocodes pack),
on top of the steel member's checks of the gross section (:func:`apply`, from
:func:`saengine.design.steel_design.design_member`).

At each opening (its centre's M and V of every strength combination):

- the tees carry the moment as N = M / d (d between the tees' centroids) and half the shear
  each, with the Vierendeel moment Mv = (V / 2) le / 2 over the opening's effective length le
  (the flat cut of a hexagon; ``circularLength`` × d0 of a circle); the tee's N and Mv combine
  linearly (or by the plastic form); the tee's stem carries its shear;
- the web post between two openings carries the horizontal shear Vh = V s / d on its narrowest
  width w0, and its moment Vh h0 / 2: buckling as a strut, or (circular openings, the
  ``ward`` method) by Ward's empirical moment capacity;
- the compression tee buckles out of the plane between the compression flange's restraints
  (the member's brace points): the lateral-torsional buckling of the tee chord, by the pack's
  steel member method (:mod:`saengine.design.steel.pack_resistance`);
- the geometry against the method's limits (opening depth, post width, tee stem, end post).

The deflection rows are scaled for the net section along the openings and the table's
Vierendeel and shear allowance. A pack without the table does not cover web openings: the
beam fails with a row that says so. Units: mm, MPa, N, N·mm (kN, kN·m reported).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from saengine.codes import context as code_context

TABLE = "webOpenings"
TAN60 = math.tan(math.radians(60.0))


def table() -> Any | None:
    try:
        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - no pack machinery
        return None


def _clause(key: str) -> str:
    t = table()
    return str(t.clauses.get(key, "")) if t is not None else ""


def _row(name: str, demand: float, capacity: float, unit: str, note: str, clause: str) -> dict:
    u = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else math.inf)
    u = round(u, 3) if math.isfinite(u) else 99.0
    return {
        "name": name,
        "demand": round(float(demand), 2),
        "capacity": round(float(capacity), 2),
        "unit": unit,
        "utilisation": u,
        "combination": None,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": False,
        "clause": clause,
    }


def geometry(openings: Any, shape: Any, length: float) -> dict[str, Any]:
    """The openings along a beam of ``length`` [mm]: their centres, the tee, d between the
    tees' centroids, the post width w0, the effective length le, the end post."""
    from saengine.design.steel.pack_resistance import outer_distance
    from saengine.design.steel.properties import tee

    d = shape.dims
    dg, bf, tf, tw = d["d"], d["bf"], d["tf"], d["tw"]
    h0, s = float(openings.depth), float(openings.spacing)
    if openings.shape == "circular":
        width = h0
        w0 = s - h0
        t = table()
        le = float(t.circularLength) * h0 if t is not None else h0
        mean = math.pi * h0 / 4
    else:
        cut = float(openings.cut) if openings.cut else h0 / math.sqrt(3)
        width = cut + h0 / TAN60
        w0 = s - width
        le = cut
        mean = cut + h0 / (2 * TAN60)
    if w0 <= 0:
        raise ValueError("the openings overlap (spacing less than the opening's width)")
    stem = (dg - h0) / 2
    if stem <= tf:
        raise ValueError("the openings cut into the flanges")
    t_shape = tee(stem, bf, tf, tw, label=f"T {stem:.0f}")
    lever = dg - 2 * outer_distance(t_shape)
    if openings.first:
        x0 = float(openings.first)
        n = max(0, int((length - x0 - width / 2) // s) + 1)
        centres = [x0 + i * s for i in range(n)]
    else:
        n = max(0, int((length - width) // s) + 1)
        centres = [length / 2 + (i - (n - 1) / 2) * s for i in range(n)]
    k = int(openings.filledEnds)
    checked = centres[k : len(centres) - k] if k else centres
    end_post = (centres[0] - width / 2) if centres else length / 2
    return {
        "dg": dg,
        "tw": tw,
        "h0": h0,
        "s": s,
        "width": width,
        "w0": w0,
        "le": le,
        "mean": mean,
        "stem": stem,
        "tee": t_shape,
        "lever": lever,
        "centres": centres,
        "checked": checked,
        "endPost": end_post,
    }


def _chi(lam: float, alpha: float, plateau: float) -> float:
    if lam <= plateau:
        return 1.0
    phi = 0.5 * (1 + alpha * (lam - plateau) + lam**2)
    return min(1.0, 1.0 / (phi + math.sqrt(max(phi**2 - lam**2, 0.0))))


def apply(
    entry: dict[str, Any],
    object_type: Any,
    material: Any,
    stations: Sequence[Any],
    lengths: Any,
) -> None:
    """Add the openings' checks of a beam type with ``webOpenings`` to its steel ``entry``;
    nothing for other members."""
    openings = getattr(object_type, "webOpenings", None)
    if openings is None or getattr(object_type, "kind", None) != "beam":
        return
    from saengine.design.steel import pack_resistance as pr
    from saengine.design.steel.members import Steel, _check, _ratio, _Worst
    from saengine.design.steel.properties import shape_properties

    t = table()
    checks: list[dict[str, Any]] = []
    try:
        shape = shape_properties(object_type.profile, False)
        if shape.family != "I":
            raise ValueError("web openings need an I profile")
        if t is None:
            raise ValueError(f"web openings are not covered by {code_context.current().name}")
        steel = Steel.of(material)
        length = float(lengths.length) * 1e3
        g = geometry(openings, shape, length)
    except Exception as error:  # noqa: BLE001 - reported on the member
        row = _row("Web openings", 1.0, 0.0, "", f"not designed: {error}", _clause("geometry"))
        entry["checks"].append(row)
        entry["webOpenings"] = {"covered": False, "problem": str(error)}
        _rescore(entry)
        return
    fy, e = steel.fy, steel.e
    f = t.factors
    tee_shape = g["tee"]
    tw, h0, s, w0, le, lever = g["tw"], g["h0"], g["s"], g["w0"], g["le"], g["lever"]
    n_rd = float(f.axial) * tee_shape.area * fy
    m_rd = float(f.flexure) * tee_shape.sx * fy
    v_rd = float(f.shear) * float(t.shearYield) * fy * tw * g["stem"]
    vh_rd = float(f.horizontalShear) * float(t.shearYield) * fy * tw * w0
    post_el = tw * w0**2 / 6
    rule = t.webPost
    if rule.method == "ward" and openings.shape == "circular" and len(rule.wardCoefficients) == 9:
        x = h0 / tw
        c = [
            rule.wardCoefficients[3 * i]
            + rule.wardCoefficients[3 * i + 1] * x
            + rule.wardCoefficients[3 * i + 2] * x**2
            for i in range(3)
        ]
        ratio = max(0.0, c[0] * (s / h0) - c[1] * (s / h0) ** 2 - c[2])
        post_rd = float(f.webPost) * min(ratio, 1.0) * post_el * fy
        post_note = f"Ward: Mmax / Me = {ratio:.3f} (s/d0 = {s / h0:.2f}, d0/tw = {x:.1f})"
    else:
        strut = float(rule.strutLength) * math.hypot(w0, h0)
        lam = (strut / (tw / math.sqrt(12))) / (math.pi * math.sqrt(e / fy))
        chi = _chi(lam, float(rule.strutAlpha), float(rule.strutPlateau))
        post_rd = float(f.webPost) * chi * post_el * fy
        post_note = f"strut: l = {strut:.0f} mm, λ̄ = {lam:.2f}, χ = {chi:.3f}"
    w = {k: _Worst() for k in ("tee", "v", "vh", "wp", "top", "bottom")}
    top_lb = float(lengths.ltb_top.longest()) * 1e3 or length
    bottom_lb = float(lengths.ltb_bottom.longest()) * 1e3 or length
    top_c, top_clause, top_note = pr.axial(tee_shape, steel, s, top_lb, True)
    bottom_c, _, bottom_note = pr.axial(tee_shape, steel, s, bottom_lb, True)
    for st in stations:
        xs = np.asarray(st.s, dtype=float) * 1e3
        if len(xs) < 2:
            continue
        m = np.asarray(st.Mx, dtype=float)
        v = np.asarray(st.Vy, dtype=float)
        for x in g["checked"]:
            mx = float(np.interp(x, xs, m))
            vv = abs(float(np.interp(x, xs, v)))
            where = f"opening at {x / 1e3:.2f} m"
            n_tee = abs(mx) / lever
            v_tee = vv / 2
            m_v = v_tee * le / 2
            a, b = _ratio(n_tee, n_rd), _ratio(m_v, m_rd)
            r = a**2 + b if t.interaction == "plastic" else a + b
            w["tee"].offer(
                r, r, 1.0, st.combination,
                f"N = {n_tee / 1e3:.0f} kN (M / d, d = {lever:.0f} mm), Mv = {m_v / 1e6:.2f} kN·m "
                f"(le = {le:.0f} mm), NRd {n_rd / 1e3:.0f} kN, MRd {m_rd / 1e6:.2f} kN·m; {where}",
                _clause("vierendeel"),
            )  # fmt: skip
            w["v"].offer(
                _ratio(v_tee, v_rd), v_tee, v_rd, st.combination,
                f"V / 2 on the tee's stem {g['stem']:.0f} × {tw:g} mm; {where}", _clause("shear"),
            )  # fmt: skip
            vh = vv * s / lever
            w["vh"].offer(
                _ratio(vh, vh_rd), vh, vh_rd, st.combination,
                f"Vh = V s / d on w0 = {w0:.0f} mm; {where}", _clause("horizontalShear"),
            )  # fmt: skip
            mwp = vh * h0 / 2
            w["wp"].offer(
                _ratio(mwp, post_rd), mwp, post_rd, st.combination,
                f"Mwp = Vh h0 / 2; {post_note}; {where}", _clause("webPost"),
            )  # fmt: skip
            # Mx > 0 stretches the top: the bottom tee in compression.
            if mx < 0:
                w["top"].offer(
                    _ratio(n_tee, top_c), n_tee, top_c, st.combination,
                    f"top tee over Lb = {top_lb:.0f} mm; {top_note}; {where}",
                    _clause("chordBuckling") or top_clause,
                )  # fmt: skip
            elif mx > 0:
                w["bottom"].offer(
                    _ratio(n_tee, bottom_c), n_tee, bottom_c, st.combination,
                    f"bottom tee over Lb = {bottom_lb:.0f} mm; {bottom_note}; {where}",
                    _clause("chordBuckling") or top_clause,
                )  # fmt: skip
    for key, name, unit, scale in (
        ("tee", "Openings: tee axial force and Vierendeel bending", "", 1.0),
        ("v", "Openings: tee shear", "kN", 1e3),
        ("vh", "Web posts: horizontal shear", "kN", 1e3),
        ("wp", "Web posts: buckling", "kN·m", 1e6),
        ("top", "Openings: top tee buckling (lateral-torsional)", "kN", 1e3),
        ("bottom", "Openings: bottom tee buckling (lateral-torsional)", "kN", 1e3),
    ):
        if w[key].combination is not None:
            checks.append(_check(name, w[key], unit, scale))
    geo = t.geometry
    clause = _clause("geometry")
    dg = g["dg"]
    checks.append(
        _row("Openings: depth d0 / dg (most)", h0 / dg, float(geo.openingDepthMax), "", "", clause)
    )
    checks.append(
        _row(
            "Openings: depth d0 / dg (least)",
            float(geo.openingDepthMin),
            h0 / dg,
            "",
            "the least ratio over the beam's",
            clause,
        )
    )
    checks.append(
        _row(
            "Web posts: width w0 / d0 (least)",
            float(geo.postWidthMin),
            w0 / h0,
            "",
            f"w0 = {w0:.0f} mm",
            clause,
        )
    )
    checks.append(
        _row(
            "Openings: tee stem (least)",
            float(geo.teeStemMin),
            g["stem"] - float(shape.dims["tf"]),
            "mm",
            "stem below the flange",
            clause,
        )
    )
    if g["centres"]:
        checks.append(
            _row(
                "Openings: end post (least)",
                float(geo.endPostMin) * h0,
                max(g["endPost"], 0.0),
                "mm",
                "beam end to the first opening's edge",
                clause,
            )
        )
    for c in checks:
        if c["utilisation"] < 0:
            c.update(utilisation=0.0, ok=True, demand=0.0)
    entry["checks"] += checks
    ig = shape.ix
    a_t, i_t = tee_shape.area, tee_shape.ix
    i_net = 2 * (i_t + a_t * (lever / 2) ** 2)
    share = min(1.0, g["mean"] / s) if g["centres"] else 0.0
    i_eff = 1 / ((1 - share) / ig + share / i_net)
    entry["webOpenings"] = {
        "covered": True,
        "shape": openings.shape,
        "openings": len(g["centres"]),
        "d0": h0,
        "spacing": s,
        "w0": round(w0, 1),
        "tee": tee_shape.label,
        "lever": round(lever, 1),
        "deflection": {
            "stiffening": ig / i_eff * (1 + float(t.vierendeelDeflection)),
            "Inet": i_net,
        },
    }
    _rescore(entry)


def _rescore(entry: dict[str, Any]) -> None:
    strength = [c for c in entry["checks"] if not c["flag"]]
    entry["utilisation"] = max((c["utilisation"] for c in strength), default=0.0)
    entry["ok"] = all(c["ok"] for c in strength)


def scale_profiles(entry: dict[str, Any], profiles: dict[str, np.ndarray]) -> dict[str, Any]:
    """A beam with web openings: its displacements per case × the net section's and the
    Vierendeel allowance's factor. Unchanged for other members."""
    found = (entry.get("webOpenings") or {}).get("deflection")
    if not found:
        return profiles
    k = float(found["stiffening"])
    return {case: moved * k for case, moved in profiles.items()}


def method_lines() -> list[str]:
    t = table()
    if t is None:
        return []
    how = "linearly" if t.interaction == "linear" else "plastically"
    return [
        (
            f"Castellated and cellular beams ({_clause('code')}): at each opening the tees carry "
            "M / d and half the shear with the Vierendeel moment over the effective length (le = "
            f"{float(t.circularLength):g} d0 of circular openings, the cut of hexagonal ones), "
            f"combined {how}; the web posts the horizontal shear V s / d and its "
            f"moment ({t.webPost.method} method); the compression tee buckles between the flange's "
            "restraints by the pack's steel member checks; the geometry limits; the deflection "
            f"increased for the net section and by {float(t.vierendeelDeflection):.0%}."
        )
    ]
