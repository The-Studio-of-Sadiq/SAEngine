"""The links of eccentrically braced dissipative frames: the group ``links`` of the steel
seismic method ``dissipativeZones`` (``steelLimitState.seismic.links``; alpha 9 C12, the
Eurocodes pack: EN 1998-1 6.8.2 and 6.8.3). :mod:`saengine.design.steel.seismic_dissipative`
asks :func:`find` for the links of the frame's beams when the pack gives the group; without it
the links stay short links (C6).

The links are found as the default pack's EBF provisions find them
(:func:`saengine.design.steel.seismic_braced.link_spans`: the beam between the brace ends on a
beam line, less half the column depth at a column). Per link:

- Vp,link = (fy / √3) tw (d - tf), Mp,link = fy bf tf (d - tf); with NEd / Npl,Rd above the
  pack's limit the reduced Vp,link,r = Vp,link √(1 - (NEd/Npl)²), Mp,link,r = Mp,link (1 -
  NEd/Npl) and the length limit e <= 1.6 Mp/Vp (R < 0.3) or (1.15 - 0.5 R) 1.6 Mp/Vp, R = NEd
  tw (d - 2 tf) / (VEd A);
- the class: short (e < 1.6 Mp/Vp), long (e > 3.0 Mp/Vp) or intermediate;
- VEd <= Vp,link and MEd <= Mp,link under the earthquake combinations (G + E);
- the rotation θp = (L / e) Δ / h at the project's drift limit (the whole drift taken as plastic:
  conservative) at most 0.08 rad (short) to 0.02 rad (long), linear between;
- Ωi = 1.5 Vp,link / VEd (short) or 1.5 Mp,link / MEd (intermediate, long) for the capacity
  design of the other members, and Ωmax <= 1.25 Ωmin over the links.

Units: N, mm, MPa.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def table() -> Any | None:
    """The ``links`` group of the dissipative seismic method; None: links taken as short."""
    from saengine.design.steel.seismic_dissipative import table as dissipative

    t = dissipative()
    return getattr(t, "links", None) if t is not None else None


def _cite(key: str) -> str:
    t = table()
    return str((t.clauses if t is not None else {}).get(key, ""))


def strength(shape: Any, fy: float, n_ed: float, v_ed: float, t: Any) -> dict[str, float]:
    """Vp,link, Mp,link (reduced with axial force) and the length limit of an I-shape link."""
    d = shape.dims
    dd, tf, tw, bf = d["d"], d["tf"], d["tw"], d["bf"]
    vp = fy / math.sqrt(3) * tw * (dd - tf)
    mp = fy * bf * tf * (dd - tf)
    npl = shape.area * fy
    out = {"Vp": vp, "Mp": mp, "Npl": npl, "reduced": 0.0, "lengthMax": math.inf}
    ratio = n_ed / npl if npl > 0 else 0.0
    if ratio > float(t.axialLimit):
        r = min(ratio, 1.0)
        out.update(reduced=1.0, Vp=vp * math.sqrt(max(1 - r**2, 0.0)), Mp=mp * (1 - r))
        big_r = n_ed * tw * (dd - 2 * tf) / (v_ed * shape.area) if v_ed > 0 else math.inf
        base = float(t.short) * mp / vp
        out["R"] = big_r
        out["lengthMax"] = (
            (float(t.lengthA) - float(t.lengthB) * big_r) * base
            if big_r >= float(t.lengthRatio)
            else base
        )
    out["VpFull"], out["MpFull"] = vp, mp
    return out


def classify(e: float, mp: float, vp: float, t: Any) -> str:
    """short, intermediate or long by e against Mp,link / Vp,link."""
    if e < float(t.short) * mp / vp:
        return "short"
    if e > float(t.long) * mp / vp:
        return "long"
    return "intermediate"


def rotation_limit(e: float, mp: float, vp: float, t: Any) -> float:
    """θp of the class, linear between the short and long limits."""
    lo, hi = float(t.short) * mp / vp, float(t.long) * mp / vp
    if e <= lo:
        return float(t.rotationShort)
    if e >= hi:
        return float(t.rotationLong)
    f = (e - lo) / (hi - lo)
    return float(t.rotationShort) + f * (float(t.rotationLong) - float(t.rotationShort))


def find(
    building: Any,
    types: dict[str, Any],
    members: list[Any],
    info: dict[str, dict[str, Any]],
    pairs: list[tuple[int, int]],
    drift_ratio: float | None,
    notes: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Per beam id its links: ``{"e", "class", "omega", "rows"}`` (the rows in the format of
    :func:`saengine.design.steel.seismic_dissipative._row`)."""
    from saengine.design.steel import seismic_braced as sb
    from saengine.design.steel.seismic import _role
    from saengine.design.steel.seismic_dissipative import _row

    t = table()
    if t is None or building is None:
        return {}
    by_id = {m.id: m for m in members}
    braces = [m for m in members if m.kind == "brace" and m.id in info and _role(m) != "gravity"]
    geometry = {m.id: g for m in braces if (g := sb._ends(m.element)) is not None}
    try:
        lines = sb.beam_lines(building, geometry, types)
    except Exception as error:  # noqa: BLE001 - a model the line search cannot read
        notes.append(f"EBF links: the beam lines could not be found: {error}")
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        for panel in sb.panels(line):
            single = len(panel.clusters) == 1
            if single and len({p[1] for p in panel.clusters[0]}) >= 2:
                continue  # a V (chevron) meeting: not a link
            for beam, a, b, _at_column, e_len, _braces, _angle, _height in sb.link_spans(
                line, panel, geometry, info, by_id, notes
            ):
                i = info[beam.id]
                shape, fy, st = i["shape"], float(i["sec"].fy), i["stations"]
                s0, s1 = sorted((sb._local(beam, a), sb._local(beam, b)))
                v_ed = m_ed = n_ed = 0.0
                combo = None
                for pi, pj in pairs:
                    for c in (pi, pj):
                        if c >= len(st) or not len(st[c].s):
                            continue
                        s = np.asarray(st[c].s) * 1e3
                        inside = (s >= s0 - sb.TOL) & (s <= s1 + sb.TOL)
                        if not inside.any():
                            inside = np.ones_like(s, dtype=bool)
                        v = float(np.max(np.abs(np.asarray(st[c].Vy)[inside])))
                        if v > v_ed:
                            v_ed, combo = v, st[c].combination
                        m_ed = max(m_ed, float(np.max(np.abs(np.asarray(st[c].Mx)[inside]))))
                        n_ed = max(n_ed, float(np.max(np.abs(np.asarray(st[c].P)[inside]))))
                k = strength(shape, fy, n_ed, v_ed, t)
                vp, mp = k["Vp"], k["Mp"]
                kind = classify(e_len, k["MpFull"], k["VpFull"], t)
                lim = rotation_limit(e_len, k["MpFull"], k["VpFull"], t)
                where = f"link of {beam.id}, e = {e_len:.0f} mm ({kind})"
                rows = [
                    _row(
                        "EBF link shear VEd / Vp,link", v_ed / 1e3, vp / 1e3, "kN",
                        _cite("strength"),
                        f"{where}: Vp,link = (fy/√3) tw (d - tf)"
                        + (" reduced for NEd" if k["reduced"] else "")
                        + f" = {vp / 1e3:.0f} kN",
                        combo,
                    ),
                    _row(
                        "EBF link moment MEd / Mp,link", m_ed / 1e6, mp / 1e6, "kN·m",
                        _cite("strength"),
                        f"{where}: Mp,link = fy b tf (d - tf)"
                        + (" reduced for NEd" if k["reduced"] else "")
                        + f" = {mp / 1e6:.0f} kN·m",
                        combo,
                    ),
                ]  # fmt: skip
                if math.isfinite(k["lengthMax"]):
                    rows.append(
                        _row(
                            "EBF link length with axial force", e_len, k["lengthMax"], "mm",
                            _cite("axial"),
                            f"{where}: NEd = {n_ed / 1e3:.0f} kN > {float(t.axialLimit):g} "
                            f"Npl, R = {k.get('R', 0.0):.2f}",
                        )
                    )  # fmt: skip
                span = panel.tb - panel.ta
                if drift_ratio is not None and span > 0:
                    theta = span / e_len * drift_ratio
                    rows.append(
                        _row(
                            "EBF link rotation θp", theta, lim, "rad", _cite("rotation"),
                            f"{where}: θp = (L / e) Δ / h = ({span:.0f} / {e_len:.0f}) × "
                            f"{drift_ratio:.4f} at the drift limit (the whole drift taken as "
                            "plastic: conservative)",
                        )
                    )  # fmt: skip
                if kind == "short":
                    omega = float(t.omegaFactor) * k["VpFull"] / v_ed if v_ed > 0 else None
                else:
                    omega = float(t.omegaFactor) * k["MpFull"] / m_ed if m_ed > 0 else None
                out.setdefault(beam.id, []).append(
                    {"e": e_len, "class": kind, "omega": omega, "rows": rows}
                )
    return out


def spread_row(found: dict[str, list[dict[str, Any]]], limit: float) -> list[dict[str, Any]]:
    """Ωmax <= ``limit`` Ωmin over the links (none with fewer than two)."""
    from saengine.design.steel.seismic_dissipative import _row

    omegas = [lk["omega"] for links in found.values() for lk in links if lk["omega"]]
    if len(omegas) < 2:
        return []
    return [
        _row(
            "EBF link overstrength spread Ωmax / Ωmin",
            max(omegas) / min(omegas),
            limit,
            "",
            _cite("omega"),
            f"Ω of {len(omegas)} links: {min(omegas):.2f} to {max(omegas):.2f}",
        )
    ]
