"""Capacity design of dissipative steel frames by the overstrength of the dissipative members:
the steel seismic method ``dissipativeZones`` a code pack picks with ``steelSeismic.
dissipative`` (alpha 9 C6; the Eurocodes pack: EN 1998-1 Section 6). It takes the place of the
default pack's moment and braced frame provisions (:mod:`saengine.design.steel.seismic`,
:mod:`saengine.design.steel.seismic_braced`) when the pack gives it; the member resistances
are the pack's partial-factor ones (:mod:`saengine.design.steel.buckling_curves`).

Per structural system in use the pack names the frame kind (moment resisting, concentrically
or eccentrically braced) and the ductility class. A system of the low ductility class (no
dissipative design) adds nothing. Otherwise:

- **Dissipative members** (the beams with moment connections of moment frames, the diagonals of
  braced frames, the beams of eccentrically braced frames, which hold the links): their section
  class at most the pack's limit for the ductility class.
- **Moment frames**: Ω = min Mpl,Rd,i / MEd,i over the dissipative beams; beams with NEd /
  Npl,Rd and (VEd,G + VEd,M) / Vpl,Rd within the pack's limits, VEd,M = 2 Mpl,Rd / L; columns
  checked by the member checks under NEd = NEd,G + 1.1 γov Ω NEd,E (and M, V likewise) and
  VEd / Vpl,Rd within the limit; ΣMRc >= 1.3 ΣMRb at the beam-column joints.
- **Concentric bracing**: the diagonals' λ̄ within the pack's range (the lower bound for X
  bracing, a flag, since the model does not say which bracing it is), Npl,Rd >= NEd;
  Ω = min Npl,Rd,i / NEd,i and Ωmax <= 1.25 Ωmin; beams and columns checked by the member
  checks under the capacity-design forces with Ω.
- **Eccentric bracing**: the beams' links taken as short (shear-yielding) links, Vp,link =
  (fy/√3) tw (d - tf), Ω = min 1.5 Vp,link / VEd (SAEngine practice: the link length is not
  identified in the model); columns and braces under the capacity-design forces.

The gravity and earthquake parts of the forces come from each earthquake combination and its
partner of the opposite sign ("... EX ..." and "... (-EX) ..."): G = (F+ + F-) / 2,
E = (F+ - F-) / 2. Checks are named "Seismic: ..." (the prefix of :mod:`saengine.design.steel.
seismic`).
"""

from __future__ import annotations

import math
import re
from dataclasses import replace
from typing import Any

import numpy as np

from saengine.design.steel.seismic import (
    PREFIX,
    _moment_connected,
    _rescore,
    _role,
    _systems_in_use,
)


def table() -> Any | None:
    """The pack's ``steelLimitState.seismic`` when it is this method (None: not this method)."""
    from saengine.design.steel.limit_state import rules

    t = rules()
    found = getattr(t, "seismic", None) if t is not None else None
    if found is None or getattr(found, "method", None) != "dissipativeZones":
        return None
    return found


def active() -> bool:
    return table() is not None


def _cite(key: str) -> str:
    t = table()
    return str((t.clauses if t is not None else {}).get(key, ""))


def systems(settings: Any) -> list[tuple[str, Any]]:
    """``(system id, frame)`` of the systems in use the pack lists, dissipative ones only."""
    t = table()
    if t is None:
        return []
    out = []
    for system, _ in _systems_in_use(settings):
        frame = t.systems.get(system)
        if frame is not None and frame.ductility != "DCL":
            out.append((system, frame))
    return out


def _row(
    name: str, demand: float, capacity: float, unit: str, ref: str, note: str = "",
    combination: str | None = None, flag: bool = False,
) -> dict[str, Any]:  # fmt: skip
    u = demand / capacity if capacity > 0 else (0.0 if demand <= 0 else 99.0)
    u = round(float(u), 3) if math.isfinite(u) else 99.0
    return {
        "name": PREFIX + name,
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


_MINUS = re.compile(r"\(-(E[XY][A-Za-z]*)\)")


def earthquake_pairs(combinations: list[str], earthquake: list[int]) -> list[tuple[int, int]]:
    """``(+E index, -E index)`` of the earthquake combinations and their partners of the
    opposite sign."""
    index = {name: i for i, name in enumerate(combinations)}
    out = []
    for i in earthquake:
        name = combinations[i]
        if name.startswith("Ω0: ") or not _MINUS.search(name):
            continue
        plus = _MINUS.sub(r"\1", name)
        j = index.get(plus)
        if j is not None and j in earthquake:
            out.append((j, i))
    return out


def _split(st_plus: Any, st_minus: Any, key: str) -> tuple[np.ndarray, np.ndarray]:
    a = np.asarray(getattr(st_plus, key), dtype=float)
    b = np.asarray(getattr(st_minus, key), dtype=float)
    return (a + b) / 2, (a - b) / 2


def amplified(stations: list[Any], pairs: list[tuple[int, int]], factor: float) -> list[Any]:
    """Stations of G ± factor E for every earthquake pair (G and E split from the pair)."""
    out = []
    for i, j in pairs:
        if i >= len(stations) or j >= len(stations):
            continue
        plus, minus = stations[i], stations[j]
        if len(plus.s) != len(minus.s):
            continue
        parts = {k: _split(plus, minus, k) for k in ("P", "Mx", "My", "Vy", "Vx")}
        for sign, label in ((1.0, "+"), (-1.0, "-")):
            values = {k: g + sign * factor * e for k, (g, e) in parts.items()}
            out.append(
                replace(
                    plus,
                    combination=f"{plus.combination} [G {label} {factor:.2f} E]",
                    T=None,
                    **values,
                )
            )
    return out


def _e_part(stations: list[Any], pairs: list[tuple[int, int]], key: str) -> float:
    """The largest |E part| of ``key`` over the pairs and stations."""
    best = 0.0
    for i, j in pairs:
        if i < len(stations) and j < len(stations) and len(stations[i].s) == len(stations[j].s):
            _, e = _split(stations[i], stations[j], key)
            if len(e):
                best = max(best, float(np.max(np.abs(e))))
    return best


def _g_part(stations: list[Any], pairs: list[tuple[int, int]], key: str) -> float:
    best = 0.0
    for i, j in pairs:
        if i < len(stations) and j < len(stations) and len(stations[i].s) == len(stations[j].s):
            g, _ = _split(stations[i], stations[j], key)
            if len(g):
                best = max(best, float(np.max(np.abs(g))))
    return best


def apply(
    project: dict[str, Any],
    building: Any,
    types: dict[str, Any],
    members: list[Any],
    combinations: list[str],
    earthquake: list[int],
    settings: Any,
) -> dict[str, Any]:
    """Adds the capacity design checks to the steel members' report entries and returns the
    summary ``{"applies", "systems", "omega", "members", "checks", "notes"}``."""
    from saengine.design.steel import buckling_curves as bc
    from saengine.design.steel import members as sm
    from saengine.design.steel.lengths import member_lengths
    from saengine.design.steel.properties import shape_properties

    t = table()
    out: dict[str, Any] = {
        "applies": False,
        "systems": [],
        "omega": {},
        "members": {},
        "checks": [],
        "notes": [],
    }
    found = systems(settings)
    if t is None or not found:
        out["notes"].append("no dissipative steel system is selected (or ductility class DCL)")
        return out
    if not bc.active():
        out["notes"].append(
            "steel capacity design: the code pack's member resistances are not by partial "
            "factors, the dissipative checks are not made"
        )
        return out
    out["applies"] = True
    out["systems"] = [s for s, _ in found]
    kinds = {f.kind for _, f in found}
    order = {"DCM": 1, "DCH": 2}
    governing = max((f for _, f in found), key=lambda f: order.get(f.ductility, 0))
    pairs = earthquake_pairs(combinations, earthquake)
    if not pairs:
        out["notes"].append(
            "steel capacity design: no earthquake combinations with both signs, not checked"
        )
        return out
    g0 = float(bc.table().gammaM0)
    info: dict[str, dict[str, Any]] = {}
    for m in members:
        try:
            shape = shape_properties(m.object.profile)
            steel = sm.Steel.of(m.material)
            sec = bc.Section.of(shape, steel.fy, steel.fu, True)
        except (ValueError, sm.SteelDesignError) as error:
            out["notes"].append(f"{m.id}: not checked for capacity design: {error}")
            continue
        stations = sm.member_stations(m.pieces, combinations, m.turned)
        lengths = member_lengths(project, m.pieces, m.turned) if project else None
        info[m.id] = {
            "shape": shape, "steel": steel, "sec": sec, "stations": stations, "lengths": lengths,
        }  # fmt: skip

    def dissipative(m: Any) -> bool:
        if m.kind == "brace":
            return bool(kinds & {"concentric"})
        if m.kind == "beam":
            role = _role(m)
            if "eccentric" in kinds:
                return role != "gravity"
            return "moment" in kinds and (
                role == "lateral" or (role is None and _moment_connected(m.object))
            )
        return False

    # Ω of the dissipative members
    omegas: dict[str, float] = {}
    for m in members:
        if m.id not in info or not dissipative(m):
            continue
        i = info[m.id]
        sec, st = i["sec"], i["stations"]
        if m.kind == "brace":
            demand = _e_part(st, pairs, "P") + _g_part(st, pairs, "P")
            cap = sec.shape.area * sec.fy / g0
        elif "eccentric" in kinds:
            d = sec.shape.dims
            demand = _e_part(st, pairs, "Vy") + _g_part(st, pairs, "Vy")
            vp = sec.fy / math.sqrt(3) * d.get("tw", 0.0) * (d.get("d", 0.0) - d.get("tf", 0.0))
            cap = 1.5 * vp
        else:
            demand = _e_part(st, pairs, "Mx") + _g_part(st, pairs, "Mx")
            cap = sec.shape.zx * sec.fy / g0
        if demand > 0:
            omegas[m.id] = cap / demand
    omega = min(omegas.values()) if omegas else 1.0
    out["omega"] = {"value": omega, "members": omegas}
    factor = float(t.capacityFactor) * float(t.gammaOv) * omega
    if omegas and "concentric" in kinds:
        spread = max(omegas.values()) / min(omegas.values())
        out["checks"].append(
            _row(
                "Brace overstrength spread Ωmax / Ωmin",
                spread,
                float(t.braceOmegaSpread),
                "",
                _cite("braceOmega"),
                f"Ω of {len(omegas)} diagonals: {min(omegas.values()):.2f} to "
                f"{max(omegas.values()):.2f}",
            )
        )
    out["notes"].append(
        f"steel capacity design ({governing.ductility}): Ω = {omega:.2f} over "
        f"{len(omegas)} dissipative members, the non-dissipative members under G + "
        f"{float(t.capacityFactor):g} γov Ω E = G + {factor:.2f} E (γov = {float(t.gammaOv):g})"
    )
    joints = _joints(building, types)
    for m in members:
        if m.id not in info:
            continue
        i = info[m.id]
        shape, steel, sec, st, lengths = (
            i["shape"], i["steel"], i["sec"], i["stations"], i["lengths"],
        )  # fmt: skip
        rows: list[dict[str, Any]] = []
        role = "dissipative" if dissipative(m) else "non-dissipative"
        out["members"][m.id] = {"role": role, "omega": omegas.get(m.id)}
        if role == "dissipative":
            state = "compression" if m.kind == "brace" else "bending"
            cls = bc.section_class(bc.classify(shape, sec.fy, state, "y"))
            limit = _class_limit(t, found, m.kind)
            rows.append(
                _row(
                    f"Section class of the dissipative member ({governing.ductility})",
                    cls,
                    limit,
                    "",
                    _cite("classes"),
                    f"class {cls} in {state}, at most class {limit}",
                )
            )
        if m.kind == "brace" and role == "dissipative":
            rows += _brace_rows(t, found, sec, lengths, st, pairs)
        elif m.kind == "beam" and role == "dissipative" and "moment" in kinds:
            rows += _mrf_beam_rows(t, sec, st, pairs, lengths)
        else:
            if lengths is not None:
                checks = bc.check_member(
                    shape, steel, amplified(st, pairs, factor), lengths, m.kind,
                    sm.SteelOptions(),
                )  # fmt: skip
                strength = [c for c in checks if not c["flag"]]
                if strength:
                    worst = max(strength, key=lambda c: c["utilisation"])
                    rows.append(
                        _row(
                            "Capacity design: member checks under G + 1.1 γov Ω E",
                            worst["utilisation"],
                            1.0,
                            "",
                            _cite("nonDissipative"),
                            f"governing: {worst['name']} ({worst['note']})",
                            worst["combination"],
                        )
                    )
            if m.kind == "column" and "moment" in kinds:
                v = max(
                    (float(np.max(np.abs(s.Vy))) for s in amplified(st, pairs, factor) if len(s.s)),
                    default=0.0,
                )
                vpl = sec.av["y"] * sec.fy / math.sqrt(3) / g0
                rows.append(
                    _row(
                        "Column shear VEd / Vpl,Rd",
                        v / max(vpl, 1.0),
                        float(t.columnShear),
                        "",
                        _cite("columns"),
                        f"VEd = {v / 1e3:.1f} kN (capacity design), Vpl,Rd = {vpl / 1e3:.1f} kN",
                    )
                )
        if rows:
            m.entry["checks"].extend(rows)
            _rescore(m.entry)
    if "moment" in kinds:
        out["checks"] += _strong_column_rows(t, joints, info, pairs)
    return out


def _class_limit(t: Any, found: list[tuple[str, Any]], kind: str) -> int:
    wanted = {"brace": "concentric"}.get(kind)
    limits = [f.classMax for _, f in found if wanted is None or f.kind == wanted]
    return min(limits or [f.classMax for _, f in found])


def _brace_rows(
    t: Any, found: list[tuple[str, Any]], sec: Any, lengths: Any, st: list[Any], pairs: list
) -> list[dict[str, Any]]:
    rows = []
    frame = next((f for _, f in found if f.kind == "concentric"), None)
    if frame is None or frame.braceSlenderness is None or lengths is None:
        return rows
    low, high = frame.braceSlenderness
    sh = sec.shape
    length = lengths.length * 1e3
    i_min = sh.iz if sh.family == "angle" and sh.iz > 0 else min(sh.ix, sh.iy)
    ncr = math.pi**2 * sec.e * i_min / length**2 if length > 0 else math.inf
    lam = math.sqrt(sh.area * sec.fy / ncr) if ncr > 0 else 0.0
    rows.append(
        _row(
            "Brace slenderness λ̄ (upper limit)", lam, high, "", _cite("braceSlenderness"),
            f"λ̄ = {lam:.2f} over L = {length:.0f} mm (least axis)",
        )
    )  # fmt: skip
    rows.append(
        _row(
            "Brace slenderness λ̄ (lower limit, X bracing)", low, max(lam, 1e-6), "",
            _cite("braceSlenderness"),
            f"λ̄ = {lam:.2f} > {low:g} for X bracing (not needed for V bracing)", flag=True,
        )
    )  # fmt: skip
    return rows


def _mrf_beam_rows(
    t: Any, sec: Any, st: list[Any], pairs: list, lengths: Any
) -> list[dict[str, Any]]:
    from saengine.design.steel import buckling_curves as bc

    g0 = float(bc.table().gammaM0)
    npl = sec.shape.area * sec.fy / g0
    vpl = sec.av["y"] * sec.fy / math.sqrt(3) / g0
    mpl = sec.shape.zx * sec.fy / g0
    n = _e_part(st, pairs, "P") + _g_part(st, pairs, "P")
    vg = _g_part(st, pairs, "Vy")
    if lengths is not None:
        length = lengths.length * 1e3
    else:
        length = max((float(np.max(s.s) - np.min(s.s)) * 1e3 for s in st if len(s.s)), default=0.0)
    vm = 2 * mpl / length if length > 0 else 0.0
    return [
        _row(
            "Beam axial force NEd / Npl,Rd", n / npl, float(t.beamAxial), "", _cite("beams"),
            f"NEd = {n / 1e3:.1f} kN, Npl,Rd = {npl / 1e3:.1f} kN",
        ),
        _row(
            "Beam shear (VEd,G + VEd,M) / Vpl,Rd", (vg + vm) / vpl, float(t.beamShear), "",
            _cite("beams"),
            f"VEd,G = {vg / 1e3:.1f} kN, VEd,M = 2 Mpl,Rd / L = {vm / 1e3:.1f} kN, Vpl,Rd = "
            f"{vpl / 1e3:.1f} kN",
        ),
    ]  # fmt: skip


def _joints(building: Any, types: dict[str, Any]) -> list[Any]:
    from saengine.design import ductile_joints as dj

    try:
        return dj.frame_joints(building, types) if building is not None else []
    except Exception:  # noqa: BLE001 - a model the joint search cannot read
        return []


def _strong_column_rows(
    t: Any, joints: list[Any], info: dict[str, dict[str, Any]], pairs: list
) -> list[dict[str, Any]]:
    from saengine.design.steel import buckling_curves as bc

    g0 = float(bc.table().gammaM0)
    rows = []
    for j in joints:
        cols = [c for c in (j.below, j.above) if c in info]
        beams = [b.id for b in j.beams if b.id in info]
        if not cols or not beams:
            continue
        mrb = sum(info[b]["sec"].shape.zx * info[b]["sec"].fy / g0 for b in beams)
        mrc = 0.0
        for c in cols:
            sec = info[c]["sec"]
            mpl_y = sec.shape.zx * sec.fy / g0
            mpl_z = sec.shape.zy * sec.fy / g0
            n = _g_part(info[c]["stations"], pairs, "P") + _e_part(info[c]["stations"], pairs, "P")
            mny = (
                bc._mn(sec, n, mpl_y, mpl_z)[0]
                if sec.shape.family in ("I", "rhs", "chs")
                else mpl_y
            )
            mrc += mny or mpl_y
        rows.append(
            _row(
                f"Strong column ΣMRc / ΣMRb at {'/'.join(cols)}",
                float(t.strongColumn),
                mrc / mrb if mrb > 0 else math.inf,
                "",
                _cite("strongColumn"),
                f"ΣMRc = {mrc / 1e6:.1f} kN·m (with NEd), ΣMRb = {mrb / 1e6:.1f} kN·m: ΣMRc >= "
                f"{float(t.strongColumn):g} ΣMRb",
            )
        )
    return rows


def method_lines() -> list[str]:
    t = table()
    if t is None:
        return []
    return [
        (
            f"Dissipative steel frames ({_cite('general')}): the section classes of the "
            "dissipative members by the ductility class, Ω of the dissipative members, the "
            f"non-dissipative members under G + {float(t.capacityFactor):g} γov Ω E with γov = "
            f"{float(t.gammaOv):g}; moment frames: beam axial force and shear, column shear and "
            f"ΣMRc >= {float(t.strongColumn):g} ΣMRb; concentric bracing: the brace slenderness "
            f"and Ωmax <= {float(t.braceOmegaSpread):g} Ωmin; eccentric bracing: short links "
            "(SAEngine practice). E and G from each earthquake combination and its partner of "
            "the opposite sign."
        )
    ]
