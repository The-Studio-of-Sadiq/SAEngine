"""Aluminium beams, columns and braces by partial factors: the code pack's ``aluminium`` table
(alpha 9 C6; the Eurocodes pack: EN 1999-1-1). A pack without the table does not cover
aluminium: the members are listed as not designed.

The members are the steel members' shapes (:mod:`saengine.design.steel.properties`, the
nominal walls), their forces the ultimate combinations, their lengths the steel members'
bracing (:mod:`saengine.design.steel.lengths`). Per member, enveloped over the combinations
and stations:

- the alloy's f0 and fu (the pack's table by the material's alloy), the heat-affected zone's
  ρo,haz and ρu,haz over the whole section when the member is welded (on the safe side);
- the section class of each element by β = b/t (internal and outstand; webs in bending
  β = 0.4 b/t) against β1, β2, β3 in ε = √(250 / f0) of its buckling class (welded or not);
  class 4 elements by ρc = C1/(β/ε) - C2/(β/ε)² (Aeff, and Weff = ρc Wel of the least ρc:
  SAEngine practice);
- tension No,Rd = A f0 / γM1 and Nu,Rd = 0.9 Anet fu / γM2; compression Nc,Rd and flexural
  buckling χ of the buckling class (α, λ̄0); bending Mc,Rd = W f0 / γM1 (Wpl, Wel, Weff by the
  class); lateral-torsional buckling with Mcr of the C1 formula and αLT, λ̄0,LT by the class;
  shear Av f0 / (√3 γM1) of non-slender webs;
- combined: the section linearly, the member by the pack's exponents (the conservative ones
  of the code's interaction).

Units: mm, MPa, N, N·mm; reported in kN, kN·m.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from saengine.codes import context as code_context

TABLE = "aluminium"


class AluminiumDesignError(ValueError):
    """An aluminium member that cannot be checked."""


def table() -> Any | None:
    try:
        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - no pack machinery
        return None


def is_aluminium(material: Any) -> bool:
    category = getattr(getattr(material, "category", None), "value", None)
    return category == "aluminium" and getattr(material, "aluminium", None) is not None


def _clause(key: str) -> str:
    t = table()
    return str(t.clauses.get(key, "")) if t is not None else ""


def alloy_of(material: Any) -> tuple[str, Any]:
    t = table()
    name = material.aluminium.alloy
    key = name.strip()
    if key in t.alloys:
        return key, t.alloys[key]
    found = [(k, a) for k, a in t.alloys.items() if a.label.lower() == key.lower()]
    if not found:
        raise AluminiumDesignError(f"alloy '{name}' is not in the code pack's aluminium table")
    return found[0]


def _elements(shape: Any) -> list[tuple[str, str, float, float, float]]:
    """(name, kind, b, t, η of bending) of the shape's plate elements."""
    d = shape.dims
    fam = shape.family
    if fam in ("I", "channel"):
        out = [("web", "internal", d["h"], d["tw"], 0.4)]
        out.append(
            (
                "flange",
                "outstand",
                (d["bf"] - d["tw"]) / 2 if fam == "I" else d["bf"] - d["tw"],
                d["tf"],
                1.0,
            )
        )
        return out
    if fam == "rhs":
        return [
            ("flange", "internal", d["b"], d["t"], 1.0),
            ("web", "internal", d["h"], d["t"], 0.4),
        ]
    if fam == "chs":
        # β = 3 √(D/t) of round tubes (the code's form, taken with the internal limits)
        return [("wall", "internal", 3 * math.sqrt(d["D"] / d["t"]) * d["t"], d["t"], 1.0)]
    if fam == "tee":
        return [
            ("flange", "outstand", (d["bf"] - d["tw"]) / 2, d["tf"], 1.0),
            ("stem", "outstand", d["d"] - d["tf"], d["tw"], 1.0),
        ]
    if fam == "angle":
        return [("leg", "outstand", max(d["d"], d["b"]), d["t"], 1.0)]
    return []


def classify(shape: Any, f0: float, buckling_class: str, welded: bool, bending: bool):
    """(class, least ρc, descriptions) of the section."""
    t = table()
    eps = math.sqrt(float(t.classes.epsilonReference) / f0)
    key = f"{buckling_class}.welded" if welded else buckling_class
    worst, rho, notes = 1, 1.0, []
    for name, kind, b, th, eta in _elements(shape):
        beta = (eta if bending else 1.0) * b / th
        limits = (t.classes.internal if kind == "internal" else t.classes.outstand)[key]
        ratio = beta / eps
        cls = next((i + 1 for i, lim in enumerate(limits) if ratio <= lim + 1e-9), 4)
        if cls == 4:
            c1, c2 = (t.localBuckling.internal if kind == "internal" else t.localBuckling.outstand)[
                key
            ]
            rho = min(rho, max(0.0, min(1.0, c1 / ratio - c2 / ratio**2)))
        worst = max(worst, cls)
        notes.append(f"{name} β/ε = {ratio:.1f}: class {cls}")
    return worst, rho, notes


def _chi(lam: float, alpha: float, lam0: float) -> float:
    if lam <= lam0:
        return 1.0
    phi = 0.5 * (1 + alpha * (lam - lam0) + lam**2)
    return min(1.0, 1.0 / (phi + math.sqrt(max(phi**2 - lam**2, 0.0))))


def check_member(
    shape: Any, material: Any, stations: Sequence[Any], lengths: Any, kind: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The checks of one aluminium member and its summary."""
    from saengine.design.steel.buckling_curves import critical_moment
    from saengine.design.steel.lengths import cb_from_diagram
    from saengine.design.steel.members import _check, _ratio, _Worst

    t = table()
    key, alloy = alloy_of(material)
    welded = bool(material.aluminium.welded)
    f0, fu = float(alloy.f0), float(alloy.fu)
    if welded:
        f0, fu = f0 * float(alloy.rhoHazProof), fu * float(alloy.rhoHazUltimate)
    g1, g2 = float(t.gammaM1), float(t.gammaM2)
    e, g = float(t.modulus), float(t.shearModulus)
    bclass = alloy.bucklingClass
    cls_c, rho_c, notes_c = classify(shape, f0, bclass, welded, False)
    cls_b, rho_b, notes_b = classify(shape, f0, bclass, welded, True)
    a = shape.area
    a_eff = a * (rho_c if cls_c == 4 else 1.0)
    wy = {1: shape.zx, 2: shape.zx, 3: shape.sx}.get(cls_b, shape.sx * rho_b)
    wz = {1: shape.zy, 2: shape.zy, 3: shape.sy}.get(cls_b, shape.sy * rho_b)
    no_rd = a * f0 / g1
    nu_rd = float(t.netTension) * a * fu / g2
    nc_rd = a_eff * f0 / g1
    mcy, mcz = wy * f0 / g1, wz * f0 / g1
    d = shape.dims
    av = {
        "I": (d.get("d", 0) - 2 * d.get("tf", 0)) * d.get("tw", 0),
        "channel": (d.get("d", 0) - 2 * d.get("tf", 0)) * d.get("tw", 0),
        "rhs": a * d.get("H", 1) / (d.get("B", 1) + d.get("H", 1)),
        "chs": 2 * a / math.pi,
    }.get(shape.family, a / 2)
    v_rd = av * f0 / (math.sqrt(3) * g1)
    eps = math.sqrt(float(t.classes.epsilonReference) / f0)
    slender_web = (
        shape.family in ("I", "channel") and d["h"] / d["tw"] > float(t.shearSlenderness) * eps
    )
    alpha_f, lam0_f = t.buckling.flexural[bclass]
    lt_key = "12" if cls_b <= 2 else "34"
    alpha_lt, lam0_lt = t.buckling.lateralTorsional[lt_key]
    xi_y, xi_z, xi_m = t.buckling.interaction
    w = {k: _Worst() for k in ("t", "c", "b", "my", "mz", "lt", "v", "s", "i")}
    tens = comp = False
    for st in stations:
        s = np.asarray(st.s, dtype=float)
        mx_arr = np.asarray(st.Mx, dtype=float)
        for k in range(len(s)):
            p = float(st.P[k])
            mx, my = abs(float(st.Mx[k])), abs(float(st.My[k]))
            v = abs(float(st.Vy[k]))
            where = st.where[k]
            _, lx, _ = lengths.effective("x", float(s[k]))
            _, ly, _ = lengths.effective("y", float(s[k]))
            w["my"].offer(
                _ratio(mx, mcy),
                mx,
                mcy,
                st.combination,
                f"class {cls_b}; {where}",
                _clause("bending"),
            )
            w["mz"].offer(
                _ratio(my, mcz),
                my,
                mcz,
                st.combination,
                f"class {cls_b}; {where}",
                _clause("bending"),
            )
            w["v"].offer(
                _ratio(v, v_rd),
                v,
                v_rd,
                st.combination,
                f"Av = {av:.0f} mm²; {where}",
                _clause("shear"),
            )
            chi_lt = 1.0
            if mx > 0 and shape.family in ("I", "channel", "tee", "angle", "bar"):
                seg = (lengths.ltb_top if float(st.Mx[k]) < 0 else lengths.ltb_bottom).around(
                    float(s[k])
                )
                c1 = cb_from_diagram(s, mx_arr, seg[0], seg[1]) if not seg[2] else 1.0
                mcr = critical_moment(
                    shape, e, g, (seg[1] - seg[0]) * 1e3 * (2 if seg[2] else 1), c1
                )
                lam_lt = math.sqrt(wy * f0 / mcr) if math.isfinite(mcr) and mcr > 0 else 0.0
                chi_lt = _chi(lam_lt, float(alpha_lt), float(lam0_lt))
                mb = chi_lt * mcy
                w["lt"].offer(
                    _ratio(mx, mb), mx, mb, st.combination,
                    f"Mcr = {mcr / 1e6:.1f} kN·m, λ̄LT = {lam_lt:.2f}, χLT = {chi_lt:.3f}; {where}",
                    _clause("lateralTorsional"),
                )  # fmt: skip
            if p < 0:
                tens = True
                cap = min(no_rd, nu_rd)
                w["t"].offer(
                    _ratio(-p, cap),
                    -p,
                    cap,
                    st.combination,
                    f"No,Rd {no_rd / 1e3:.0f}, Nu,Rd {nu_rd / 1e3:.0f} kN; {where}",
                    _clause("tension"),
                )
            n_rd = nc_rd if p > 0 else min(no_rd, nu_rd)
            sec = _ratio(abs(p), n_rd) + _ratio(mx, mcy) + _ratio(my, mcz)
            w["s"].offer(sec, sec, 1.0, st.combination, f"linear; {where}", _clause("combined"))
            if p > 0:
                comp = True
                w["c"].offer(
                    _ratio(p, nc_rd),
                    p,
                    nc_rd,
                    st.combination,
                    f"class {cls_c}; {where}",
                    _clause("compression"),
                )
                ncr_y = math.pi**2 * e * shape.ix / lx**2 if lx > 0 else math.inf
                ncr_z = math.pi**2 * e * shape.iy / ly**2 if ly > 0 else math.inf
                nrk = a_eff * f0
                chis = [
                    _chi(math.sqrt(nrk / n), float(alpha_f), float(lam0_f))
                    if math.isfinite(n)
                    else 1.0
                    for n in (ncr_y, ncr_z)
                ]
                chi = min(chis)
                nb = chi * nc_rd
                w["b"].offer(
                    _ratio(p, nb), p, nb, st.combination,
                    f"buckling class {bclass}, χy = {chis[0]:.3f}, χz = {chis[1]:.3f}; {where}",
                    _clause("buckling"),
                )  # fmt: skip
                r1 = _ratio(p, chis[0] * nc_rd) ** float(xi_y) + _ratio(mx, chi_lt * mcy)
                r2 = (
                    _ratio(p, chis[1] * nc_rd) ** float(xi_z)
                    + _ratio(mx, chi_lt * mcy)
                    + _ratio(my, mcz) ** float(xi_m)
                )
                r = max(r1, r2)
                w["i"].offer(
                    r,
                    r,
                    1.0,
                    st.combination,
                    f"exponents {xi_y:g}, {xi_z:g}, {xi_m:g}; {where}",
                    _clause("interaction"),
                )
    checks = []
    if tens:
        checks.append(_check("Tension", w["t"], "kN", 1e3))
    if comp:
        checks.append(_check("Compression: cross-section", w["c"], "kN", 1e3))
        checks.append(_check("Compression: buckling", w["b"], "kN", 1e3))
    checks.append(_check("Flexure about x (major)", w["my"], "kN·m", 1e6))
    checks.append(_check("Flexure about y (minor)", w["mz"], "kN·m", 1e6))
    if w["lt"].combination is not None:
        checks.append(_check("Lateral-torsional buckling", w["lt"], "kN·m", 1e6))
    checks.append(_check("Shear along y (depth)", w["v"], "kN", 1e3))
    if slender_web:
        checks[-1]["note"] += "; slender web: its shear buckling is not covered (check by hand)"
        checks[-1]["ok"] = False
    checks.append(_check("Axial force and flexure (cross-section)", w["s"], "", 1.0))
    if comp:
        checks.append(_check("Axial force and flexure: member buckling", w["i"], "", 1.0))
    for c in checks:
        if c["utilisation"] < 0:
            c.update(utilisation=0.0, ok=True, demand=0.0)
    summary = {
        "alloy": key,
        "f0": f0,
        "fu": fu,
        "welded": welded,
        "class": cls_b,
        "elements": notes_c + notes_b,
    }
    return checks, summary


def design_member(
    member_id: str,
    kind: str,
    object_type: Any,
    material: Any,
    pieces: Sequence[Any],
    combinations: Sequence[str],
    turned: bool,
    project: dict[str, Any] | None,
) -> dict[str, Any]:
    """The design report entry of one aluminium member (the steel member's format)."""
    from saengine.design.steel.lengths import MemberLengths, member_lengths, positions
    from saengine.design.steel.members import member_stations
    from saengine.design.steel.properties import shape_properties

    if table() is None:
        raise AluminiumDesignError("aluminium is not covered by the code pack")
    if not pieces:
        raise AluminiumDesignError("not in the analysis results")
    try:
        shape = shape_properties(object_type.profile, False)
    except ValueError as error:
        raise AluminiumDesignError(str(error)) from error
    if project is not None:
        lengths = member_lengths(project, pieces, turned)
    else:
        s, _ = positions(pieces, 2)
        lengths = MemberLengths.simple(float(s[-1] - s[0]))
    stations = member_stations(pieces, combinations, turned)
    checks, summary = check_member(shape, material, stations, lengths, kind)
    strength = [c for c in checks if not c["flag"]]
    return {
        "id": member_id,
        "kind": kind,
        "type": object_type.id,
        "members": [p.id for p in pieces],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "material": material.id,
        "aluminium": {"label": shape.label, **summary},
    }


def method_lines() -> list[str]:
    t = table()
    if t is None:
        return []
    return [
        (
            f"Aluminium members by partial factors ({_clause('chapter')}): γM1 = {float(t.gammaM1):g}, "
            f"γM2 = {float(t.gammaM2):g}, f0 and fu of the alloy (the heat-affected zone's over the "
            "whole section of welded members), section classes by β/ε and the buckling class, "
            "class 4 by ρc; tension, compression with flexural buckling (α, λ̄0 of the buckling "
            "class), bending, lateral-torsional buckling with Mcr, shear of non-slender webs, the "
            "combined checks with the code's conservative exponents, under the ultimate "
            "combinations."
        )
    ]
