"""Timber beams, columns and braces by limit state design with partial factors: the timber
method ``partialFactors`` a code pack picks with ``timber.method`` (alpha 9 C6; the Eurocodes
pack: EN 1995-1-1 with the strength classes of EN 338 and EN 14080). Every number is the pack's
``timber.limitState``.

The member's forces are the ultimate (design) combinations of the run. Per member, at every
station of every combination:

- design strengths fd = kmod kh fk / γM: fk of the material's strength class, kmod by the
  service class (from the material's location of use: inside 1, outside 2, wet 3; SAEngine
  practice) and the load-duration class of the shortest action in the combination (the
  pack's map of the analysis cases), kh of the member's depth (bending and tension), γM by the
  kind (solid or glued laminated timber);
- bending about both axes with km, shear τ = 1.5 V / (kcr b h) of rectangles, tension and
  compression along the grain, combined bending and axial tension or compression;
- columns by kc of the relative slenderness λrel = λ/π √(fc,0,k / E0,05) with βc, about both axes;
- beams by kcrit of the relative slenderness for bending λrel,m = √(fm,k / σm,crit), σm,crit
  = 0.78 b² E0,05 / (h lef), lef the member's length (simply supported, SAEngine practice), and
  with compression the combined check of the code.

Rectangular sections only (other shapes: an error the run lists). The deflection and the
joints are not checked by this method (said in the notes).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.design.timber.members import Section, TimberDesignError

METHOD_ID = "partialFactors"
#: Service class by the material's location of use (SAEngine practice).
SERVICE_CLASS = {"inside": "1", "outside": "2", "wet": "3"}


def table() -> Any | None:
    """The pack's ``timber.limitState`` when it picks the method, else None."""
    try:
        t = code_context.pack_table("timber")
    except Exception:  # noqa: BLE001 - a pack without timber: not this method
        return None
    if getattr(t, "method", "permissibleStress") != METHOD_ID:
        return None
    return getattr(t, "limitState", None)


def active() -> bool:
    return table() is not None


def _clause(key: str) -> str:
    t = table()
    text = str((t.clauses if t is not None else {}).get(key, ""))
    return text


def strength_class(material: Any) -> tuple[str, Any]:
    t = table()
    props = getattr(material, "timber", None)
    name = getattr(props, "strengthClass", None) or t.defaultClass
    if name not in t.classes:
        raise TimberDesignError(f"strength class '{name}' is not in the code pack's table")
    return name, t.classes[name]


def duration_of(factors: dict[str, float]) -> str:
    """The load-duration class of a combination: its shortest action's (the pack's map of the
    analysis cases; a case not listed: permanent)."""
    t = table()
    order = list(t.durationOrder)
    found = order[0]
    for case, value in (factors or {}).items():
        if not value:
            continue
        key = case
        for k in (case, case.rstrip("XY"), case[:1]):
            if k in t.durations:
                key = k
                break
        d = t.durations.get(key, order[0])
        if d in order and order.index(d) > order.index(found):
            found = d
    return found


def kmod(kind: str, service: str, duration: str) -> float:
    return float(table().kmod[kind][f"{service}.{duration}"])


def depth_factor(kind: str, h: float) -> float:
    ref, exponent, cap = table().depthFactor[kind]
    if h >= ref:
        return 1.0
    return min((ref / h) ** exponent, cap)


def column_factor(lam_rel: float, beta_c: float) -> float:
    """kc = 1 / (k + √(k² - λrel²)), k = 0.5 (1 + βc (λrel - 0.3) + λrel²)."""
    plateau = float(table().columnPlateau)
    if lam_rel <= plateau:
        return 1.0
    k = 0.5 * (1 + beta_c * (lam_rel - plateau) + lam_rel**2)
    return min(1.0, 1.0 / (k + math.sqrt(max(k * k - lam_rel**2, 0.0))))


def lateral_factor(lam_m: float) -> float:
    """kcrit of the relative slenderness for bending."""
    t = table()
    a, b, top = t.lateralTorsional
    if lam_m <= float(t.relativeSlenderness):
        return 1.0
    if lam_m <= top:
        return a - b * lam_m
    return 1.0 / lam_m**2


def _row(name: str, u: float, demand: float, capacity: float, unit: str, combination: Any,
         note: str, ref: str, flag: bool = False) -> dict[str, Any]:  # fmt: skip
    u = round(float(u), 3) if math.isfinite(u) else 99.0
    return {
        "name": name,
        "demand": round(float(demand), 3),
        "capacity": round(float(capacity), 3),
        "unit": unit,
        "utilisation": u,
        "combination": combination,
        "ok": bool(u <= 1.0),
        "note": note,
        "flag": flag,
        "clause": ref,
    }


def check_member(
    section: Section,
    material: Any,
    stations: Sequence[Any],
    length: float,
    factors: Sequence[dict[str, float]],
    kind: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The checks of one timber member and its summary; ``length`` [mm], ``factors`` each
    combination's ``{case: factor}`` (in the order of ``stations``)."""
    t = table()
    if section.shape != "rectangle":
        raise TimberDesignError(
            f"timber members by the code pack's limit state method are rectangular, not "
            f"'{section.shape}'"
        )
    name, sc = strength_class(material)
    kind_t = sc.kind
    props = getattr(material, "timber", None)
    service = SERVICE_CLASS.get(getattr(props, "location", "inside"), t.defaultServiceClass)
    gamma = float(t.gammaM[kind_t])
    b, h = section.b, section.d
    kh_y = depth_factor(kind_t, h)
    kh_z = depth_factor(kind_t, b)
    km = float(t.km)
    beta_c = float(t.betaC[kind_t])
    area = b * h
    wy, wz = b * h**2 / 6, h * b**2 / 6
    iy_r, iz_r = h / math.sqrt(12), b / math.sqrt(12)
    lam_y, lam_z = length / iy_r, length / iz_r
    root = math.sqrt(float(sc.fc0k) / float(sc.E005)) / math.pi
    kc_y = column_factor(lam_y * root, beta_c)
    kc_z = column_factor(lam_z * root, beta_c)
    sigma_crit = float(t.criticalBending) * b**2 * float(sc.E005) * 1e3 / (h * length)
    lam_m = math.sqrt(float(sc.fmk) / sigma_crit) if sigma_crit > 0 else 0.0
    kcrit = lateral_factor(lam_m) if kind == "beam" or h > b else 1.0
    kcr = float(t.kcr[kind_t])
    worst: dict[str, tuple[float, float, float, Any, str]] = {}

    def offer(key: str, u: float, demand: float, cap: float, comb: Any, note: str) -> None:
        if key not in worst or u > worst[key][0]:
            worst[key] = (u, demand, cap, comb, note)

    for c, st in enumerate(stations):
        f = factors[c] if c < len(factors) else {}
        duration = duration_of(f)
        k = kmod(kind_t, service, duration)
        fm_y = k * kh_y * float(sc.fmk) / gamma
        fm_z = k * kh_z * float(sc.fmk) / gamma
        ft = k * kh_y * float(sc.ft0k) / gamma
        fc = k * float(sc.fc0k) / gamma
        fv = k * float(sc.fvk) / gamma
        label = f"kmod = {k:g} ({duration}, service class {service}), γM = {gamma:g}"
        for i in range(len(st.s)):
            p = float(st.P[i])
            smy = abs(float(st.Mx[i])) / wy
            smz = abs(float(st.My[i])) / wz
            tau = 1.5 * max(abs(float(st.Vy[i])) / (kcr * b * h), abs(float(st.Vx[i])) / (kcr * b * h))
            where = st.where[i]
            bend = max(smy / fm_y + km * smz / fm_z, km * smy / fm_y + smz / fm_z)
            offer("m", bend, bend, 1.0, st.combination, f"fm,d = {fm_y:.2f} MPa, {label}; {where}")
            offer("v", tau / fv, tau, fv, st.combination, f"τd = 1.5 V / (kcr b h), kcr = {kcr:g}, {label}; {where}")
            if p < 0:
                st_ = -p / area
                offer("t", st_ / ft, st_, ft, st.combination, f"{label}; {where}")
                comb = st_ / ft + bend
                offer("tm", comb, comb, 1.0, st.combination, f"σt/ft + bending; {where}")
            elif p > 0:
                sc_ = p / area
                offer("c", sc_ / fc, sc_, fc, st.combination, f"{label}; {where}")
                comb = (sc_ / fc) ** 2 + bend
                offer("cm", comb, comb, 1.0, st.combination, f"(σc/fc)² + bending; {where}")
                col = max(
                    sc_ / (kc_y * fc) + smy / fm_y + km * smz / fm_z,
                    sc_ / (kc_z * fc) + km * smy / fm_y + smz / fm_z,
                )
                offer(
                    "kc", col, col, 1.0, st.combination,
                    f"kc,y = {kc_y:.3f}, kc,z = {kc_z:.3f} (λ = {lam_y:.0f} / {lam_z:.0f}); {where}",
                )  # fmt: skip
                if kcrit < 1.0 and smy > 0:
                    lt = (smy / (kcrit * fm_y)) ** 2 + sc_ / (kc_z * fc)
                    offer("ltc", lt, lt, 1.0, st.combination, f"kcrit = {kcrit:.3f}; {where}")
            if smy > 0:
                offer(
                    "lt", smy / (kcrit * fm_y), smy, kcrit * fm_y, st.combination,
                    f"σm,crit = {sigma_crit:.1f} MPa, λrel,m = {lam_m:.2f}, kcrit = {kcrit:.3f}, "
                    f"lef = {length:.0f} mm; {where}",
                )  # fmt: skip
    names = {
        "m": ("Bending", "", "bending"),
        "v": ("Shear", "MPa", "shear"),
        "t": ("Tension along the grain", "MPa", "tension"),
        "tm": ("Bending and axial tension", "", "combinedTension"),
        "c": ("Compression along the grain", "MPa", "compression"),
        "cm": ("Bending and axial compression", "", "combinedCompression"),
        "kc": ("Column buckling (kc)", "", "columns"),
        "lt": ("Lateral-torsional stability (kcrit)", "MPa", "lateralTorsional"),
        "ltc": ("Lateral-torsional stability with compression", "", "lateralTorsional"),
    }
    checks = [
        _row(names[k][0], w[0], w[1], w[2], names[k][1], w[3], w[4], _clause(names[k][2]))
        for k, w in worst.items()
    ]
    summary = {
        "strengthClass": name,
        "serviceClass": service,
        "gammaM": gamma,
        "kh": round(kh_y, 3),
        "kcY": round(kc_y, 3),
        "kcZ": round(kc_z, 3),
        "kcrit": round(kcrit, 3),
        "kdef": float(t.kdef[kind_t][service]),
    }
    return checks, summary


def design_member(
    member_id: str,
    kind: str,
    object_type: Any,
    material: Any,
    pieces: Sequence[Any],
    combinations: Sequence[str],
    factors: Sequence[dict[str, float]],
    turned: bool = False,
) -> dict[str, Any]:
    """The design report entry of one timber member by the method (the format of
    :func:`saengine.design.timber.members.design_timber_member`)."""
    from saengine.design.steel.lengths import positions
    from saengine.design.steel.members import member_stations

    if not pieces:
        raise TimberDesignError("not in the analysis results")
    section = Section.of(object_type.profile)
    s, _ = positions(pieces, 2)
    length = float(s[-1] - s[0]) * 1000.0
    stations = member_stations(pieces, combinations, turned)
    checks, summary = check_member(section, material, stations, length, factors, kind)
    strength = [c for c in checks if not c["flag"]]
    code = code_context.code_name()
    return {
        "id": member_id,
        "kind": kind,
        "type": object_type.id,
        "members": [p.id for p in pieces],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength), default=0.0),
        "ok": all(c["ok"] for c in strength),
        "material": material.id,
        "timber": {
            "label": f"{section.b:g} x {section.d:g} timber ({section.shape})",
            "strengthClass": summary["strengthClass"],
            "serviceClass": summary["serviceClass"],
            "factors": {k: v for k, v in summary.items() if isinstance(v, float)},
            "length": round(length, 0),
            "code": code,
            "basis": _clause("chapter"),
            "notes": [
                "deflection and joints: not checked by the code pack's limit state method",
            ],
        },
    }


def method_lines() -> list[str]:
    t = table()
    if t is None:
        return []
    return [
        (
            f"Timber members by limit state design ({_clause('chapter')}): fd = kmod kh fk / γM "
            "of the material's strength class under the ultimate combinations, kmod by the "
            "service class (inside 1, outside 2, wet 3) and the shortest action's load duration, "
            "bending with km, shear with kcr, tension, compression and their combinations with "
            f"bending ({_clause('combinedCompression')}), columns by kc and beams by kcrit "
            f"({_clause('columns')}); lef the member's length. Rectangular sections; the "
            "deflection and the joints are not checked by this method."
        )
    ]


def strength_combination_factors(extra_factors: Any, count: int) -> list[dict[str, float]]:
    """Each combination's ``{case: factor}`` from the run's demand data (``extra["factors"]``),
    empty for those it lacks (their load duration is then permanent: the safe side)."""
    out = []
    for c in range(count):
        f = extra_factors[c] if extra_factors and c < len(extra_factors) else {}
        out.append({k: float(v) for k, v in (f or {}).items() if isinstance(v, (int, float))})
    return out


__all__ = ["active", "design_member", "method_lines", "np"]
