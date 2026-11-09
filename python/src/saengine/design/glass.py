"""Structural glass (alpha 9 L7): panels, walk-on floors, balustrades and fins by the code
pack's ``glass`` table. A wall or slab type made of glass with a ``glass`` panel, or a beam or
column type made of glass with a ``glassFin``, is designed once per type from its own size and
actions (:func:`design_types`); a pack without the table does not cover glass.

**Laminated glass** (:func:`effective_thickness`): the Wölfel-Bennison shear transfer
coefficient ω = 1 / (1 + 9.6 E Is hv / (G hs² a²)) of the interlayer's shear modulus G (the
pack's by the action's duration, or the panel's own) and the panel's span a; the deflection
thickness hef,w = (Σ hi³ + 12 ω Is)^(1/3) and each ply's stress thickness hi,ef,σ = √(hef,w³ /
(hi + 2 ω zi)), Is = Σ hi zi² about the package's centroid (two plies: the published form;
more plies: SAEngine's generalisation with hs between the outer plies).

**Stresses and deflections** on linear plate theory, on the safe side of the large-deflection
membrane action: four edges σ = β q a² / h², w = α q a⁴ / (E h³) (β, α of the aspect ratio:
Timoshenko and Woinowsky-Krieger's simply supported plate, ν = 0.3); two edges a one-way strip;
balustrades a cantilever strip under the wind and the pack's barrier line load at its height.
The ``loadResistance`` method takes the four-edge deflection by the code's formula when the pack
gives it.

**Strength**: ``partialFactors``: fg;d = kmod ksp fg;k / γM;A + kv (fb;k - fg;k) / γM;v by the
action's kmod, the actions of different durations summed as σ/fg;d ratios; ``loadResistance``:
the allowable 3 s surface stress of annealed glass × the glass type factor (short or long
duration) × the load duration factor (3 / d)^(1/n) of annealed glass. **Fins**: the bending
stress of the plies acting together in their plane, the lateral-torsional buckling Mcr = C1 (π
/ L) √(E Iz G It) (C1 = 1.13 of a uniform load) on the effective thickness, the deflection.

Units: mm, MPa (N/mm²), N; actions in kPa, reported in MPa and mm.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.codes import context as code_context

TABLE = "glass"
KPA = 1e-3  # N/mm² per kPa
GRAVITY = 9.80665

#: Simply supported rectangular plate under a uniform load (ν = 0.3; Timoshenko and
#: Woinowsky-Krieger, Theory of Plates and Shells, Table 8): b/a, β of the largest stress
#: σ = β q a² / h², α of the centre deflection w = α q a⁴ / (E h³). Plate theory, not code values.
PLATE = (
    (1.0, 0.2874, 0.0444),
    (1.2, 0.3762, 0.0616),
    (1.4, 0.4530, 0.0770),
    (1.6, 0.5172, 0.0906),
    (1.8, 0.5688, 0.1017),
    (2.0, 0.6102, 0.1110),
    (3.0, 0.7134, 0.1335),
    (4.0, 0.7410, 0.1400),
    (5.0, 0.7476, 0.1417),
)
#: The infinitely long plate (a strip in one-way bending): β = 6/8, α = 12 (1 - ν²) 5/384.
PLATE_LONG = (0.7500, 0.1421)


class GlassDesignError(ValueError):
    """A glass type that cannot be checked."""


def table() -> Any | None:
    try:
        pack = code_context.current()
        return pack.table(TABLE) if pack.has(TABLE) else None
    except Exception:  # noqa: BLE001 - no pack machinery
        return None


def _clause(key: str) -> str:
    t = table()
    return str(t.clauses.get(key, "")) if t is not None else ""


def is_glass(material: Any) -> bool:
    category = getattr(getattr(material, "category", None), "value", None)
    return category == "glass" and getattr(material, "glass", None) is not None


def plate_coefficients(ratio: float) -> tuple[float, float]:
    """(β, α) of a four-edge plate of aspect ratio b/a ≥ 1: interpolated in the table, and
    beyond its last row the gap to the long strip closes exponentially at the rate of the last
    two rows (the Lévy series' end-edge terms decay as 1/cosh(mπb/2a)); a straight line to the
    strip at b/a = ∞ would keep the b/a = 5 values for any longer plate."""
    r = max(1.0, ratio)
    xs = [p[0] for p in PLATE]
    if r <= xs[-1]:
        return float(np.interp(r, xs, [p[1] for p in PLATE])), float(
            np.interp(r, xs, [p[2] for p in PLATE])
        )
    (x4, *last4), (x5, *last5) = PLATE[-2], PLATE[-1]
    out = []
    for k, long in enumerate(PLATE_LONG):
        gap4, gap5 = long - last4[k], long - last5[k]
        rate = gap5 / gap4 if gap4 > 0 else 0.0
        out.append(long - gap5 * rate ** ((r - x5) / (x5 - x4)))
    return float(out[0]), float(out[1])


def effective_thickness(
    plies: list[float], interlayer: float, g: float, e: float, span: float
) -> dict[str, float]:
    """The laminate's ω, hef,w and least hi,ef,σ [mm] (a single ply: its thickness)."""
    h = [float(x) for x in plies]
    if len(h) == 1:
        return {"omega": 1.0, "deflection": h[0], "stress": h[0], "Is": 0.0}
    # ply centres from the first ply's outer face
    centres, z = [], 0.0
    for k, hi in enumerate(h):
        centres.append(z + hi / 2)
        z += hi + (interlayer if k < len(h) - 1 else 0.0)
    total = sum(h)
    centroid = sum(hi * c for hi, c in zip(h, centres, strict=True)) / total
    dist = [abs(c - centroid) for c in centres]
    i_s = sum(hi * d**2 for hi, d in zip(h, dist, strict=True))
    hs = centres[-1] - centres[0]
    hv = interlayer
    omega = 1.0 / (1.0 + 9.6 * e * i_s * hv / (g * hs**2 * span**2)) if g > 0 else 0.0
    omega = min(max(omega, 0.0), 1.0)
    hw = (sum(hi**3 for hi in h) + 12 * omega * i_s) ** (1 / 3)
    hs_min = min(math.sqrt(hw**3 / (hi + 2 * omega * d)) for hi, d in zip(h, dist, strict=True))
    return {"omega": omega, "deflection": hw, "stress": hs_min, "Is": i_s}


def strength(kind: str, surface: str, action: str) -> tuple[float, str]:
    """The design (or allowable) surface stress [MPa] of the glass for ``action``."""
    t = table()
    if t.method == "partialFactors":
        pf = t.partialFactors
        kmod = float(pf.kmod[action])
        ksp = float(pf.ksp.get(surface, 1.0))
        fgk = float(pf.annealed)
        f = kmod * ksp * fgk / float(pf.gammaA)
        note = f"kmod {kmod:g}, ksp {ksp:g}, fg;k {fgk:g} / γM;A {float(pf.gammaA):g}"
        if kind != "annealed":
            fbk = float(pf.prestressed[kind])
            f += float(pf.kv) * (fbk - fgk) / float(pf.gammaV)
            note += f" + kv (fb;k {fbk:g} - fg;k) / γM;v {float(pf.gammaV):g}"
        return f, note
    lr = t.loadResistance
    long = action in t.longActions
    gtf = float((lr.typeLong if long else lr.typeShort)[kind])
    f = float(lr.annealed3s) * gtf
    note = f"{float(lr.annealed3s):g} MPa × GTF {gtf:g} ({'long' if long else 'short'})"
    if kind == "annealed":
        ldf = (3.0 / float(lr.durations[action])) ** (1 / float(lr.durationExponent))
        f *= ldf
        note += f" × LDF {ldf:.3f}"
    return f, note


def _row(name: str, demand: float, capacity: float, unit: str, note: str, key: str) -> dict:
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
        "clause": _clause(key),
    }


def _barrier_load(row_id: str | None) -> tuple[float, str]:
    """The pack's barrier line load [N/mm] (its row ``row_id``, else the first in kN/m)."""
    try:
        barriers = code_context.current().table("areaLoads").barriers
    except Exception:  # noqa: BLE001 - no areaLoads table
        barriers = None
    rows = [r for r in (barriers.rows if barriers is not None else []) if r.unit == "kN/m"]
    if not rows:
        raise GlassDesignError("the code pack gives no barrier line load")
    found = next((r for r in rows if r.id == row_id), None) if row_id else rows[0]
    if found is None:
        raise GlassDesignError(f"barrier load row '{row_id}' is not in the code pack")
    return float(found.load), f"{found.id}: {found.name}"


def _response(panel: Any, q: float, line: float, h: float, e: float) -> tuple[float, float]:
    """(largest stress [MPa] on thickness h, largest deflection [mm] on thickness h) of the
    panel under a pressure q [N/mm²] and (balustrades) a line load [N/mm] at its height."""
    a, b = sorted((float(panel.width), float(panel.height)))
    if panel.support == "fourEdges":
        beta, alpha = plate_coefficients(b / a)
        return beta * q * a**2 / h**2, alpha * q * a**4 / (e * h**3)
    if panel.support == "twoEdges":
        span = float(panel.height)
        return 0.75 * q * span**2 / h**2, 5 * q * span**4 / (32 * e * h**3)
    height = float(panel.height)
    hb = min(float(panel.barrierHeight), height)
    m = q * height**2 / 2 + line * hb  # per mm width
    inertia = h**3 / 12
    w = q * height**4 / (8 * e * inertia) + line * hb**2 * (3 * height - hb) / (6 * e * inertia)
    return 6 * m / h**2, w


def _e1300_deflection(panel: Any, q: float, h: float, e: float) -> float | None:
    """The code's four-edge centre deflection [mm] (None when outside its form)."""
    lr = table().loadResistance
    if not lr.deflection or panel.support != "fourEdges":
        return None
    a, b = sorted((float(panel.width), float(panel.height)))
    ar = b / a
    r = [sum(c * ar**k for k, c in enumerate(coeffs)) for coeffs in lr.deflection]
    inner = q * (a * b) ** 2 / (e * h**4)
    if inner <= math.e:
        return None
    x = math.log(math.log(inner))
    return h * math.exp(r[0] + r[1] * x + r[2] * x**2)


def check_panel(type_id: str, panel: Any, material: Any, horizontal: bool) -> dict[str, Any]:
    """The design entry of a glass panel type."""
    t = table()
    e = float(material.mechanical.E or t.modulus)
    kind, surface = material.glass.kind, material.glass.surface
    span = min(float(panel.width), float(panel.height))
    if panel.support == "twoEdges":
        span = float(panel.height)
    if panel.support == "cantilever":
        span = float(panel.height)
    actions: list[tuple[str, float, float]] = []  # (action, pressure N/mm², line N/mm)
    if panel.windPressure:
        actions.append(("wind", float(panel.windPressure) * KPA, 0.0))
    if panel.snow:
        actions.append(("snow", float(panel.snow) * KPA, 0.0))
    if panel.live:
        actions.append(("live", float(panel.live) * KPA, 0.0))
    notes: list[str] = []
    if panel.use == "balustrade":
        load, which = _barrier_load(panel.barrier)
        actions.append(("barrier", 0.0, load))
        notes.append(f"barrier line load {load:g} kN/m ({which})")
    total = sum(float(x) for x in panel.plies)
    if horizontal:
        actions.append(("permanent", float(t.density) * GRAVITY * total * 1e-9, 0.0))
    if not actions:
        raise GlassDesignError("no actions given (wind, snow, live load or a balustrade)")
    checks: list[dict[str, Any]] = []
    permanent = next((a for a in actions if a[0] == "permanent"), None)
    il = t.interlayers.get(panel.interlayer)
    for action, q, line in actions:
        long = action in t.longActions
        if panel.shearModulus:
            g = float(panel.shearModulus)
        else:
            g = float(il.long if long else il.short) if il is not None else 0.0
        th = effective_thickness(panel.plies, float(panel.interlayerThickness), g, e, span)
        gamma = float(t.actionFactors[action])
        sigma, _ = _response(panel, gamma * q, gamma * line, th["stress"], e)
        f, f_note = strength(kind, surface, action)
        ratio = sigma / f
        note = (
            f"σ = {sigma:.1f} MPa on hef,σ = {th['stress']:.2f} mm (ω = {th['omega']:.2f}), "
            f"factor {gamma:g}; f = {f:.1f} MPa ({f_note})"
        )
        if permanent is not None and action != "permanent":
            gp = float(t.actionFactors["permanent"])
            sp, _ = _response(panel, gp * permanent[1], 0.0, th["stress"], e)
            fp, _ = strength(kind, surface, "permanent")
            ratio += sp / fp
            note += f"; + self weight σ {sp:.1f} / {fp:.1f} MPa"
        checks.append(_row(f"Glass strength: {action}", ratio, 1.0, "", note, "strength"))
        if action == "permanent":
            continue
        # deflection under the characteristic action
        _, defl = _response(panel, q, line, th["deflection"], e)
        if t.method == "loadResistance" and line == 0:
            found = _e1300_deflection(panel, q, th["deflection"], e)
            if found is not None:
                defl = found
        divisor = float(getattr(t.deflection, panel.support))
        limit = span / divisor
        if float(t.deflection.absolute) > 0:
            limit = min(limit, float(t.deflection.absolute))
        checks.append(
            _row(
                f"Glass deflection: {action}",
                defl,
                limit,
                "mm",
                f"hef,w = {th['deflection']:.2f} mm; limit span / {divisor:g}",
                "deflectionLimit",
            )
        )
    strength_rows = [c for c in checks if not c["flag"]]
    return {
        "id": type_id,
        "kind": "glassPanel",
        "type": type_id,
        "members": [],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength_rows), default=0.0),
        "ok": all(c["ok"] for c in strength_rows),
        "material": material.id,
        "glass": {
            "use": panel.use,
            "support": panel.support,
            "plies": list(panel.plies),
            "kind": kind,
            "notes": notes,
        },
    }


def check_fin(type_id: str, fin: Any, profile: Any, material: Any) -> dict[str, Any]:
    """The design entry of a glass fin type (its profile a rectangle: yDim the fin's depth)."""
    t = table()
    if getattr(profile, "shape", None) != "rectangle":
        raise GlassDesignError("a glass fin needs a rectangular profile")
    e = float(material.mechanical.E or t.modulus)
    nu = float(material.mechanical.nu or t.poisson)
    depth = float(profile.yDim)
    plies = [float(x) for x in fin.plies]
    total = sum(plies)
    span = float(fin.span)
    q = float(fin.windPressure) * KPA * float(fin.tributary)  # N/mm
    gamma = float(t.actionFactors["wind"])
    m = gamma * q * span**2 / 8
    sigma = 6 * m / (total * depth**2)
    f, f_note = strength(material.glass.kind, material.glass.surface, "wind")
    checks = [
        _row(
            "Glass fin: bending stress",
            sigma,
            f,
            "MPa",
            f"M = {m / 1e6:.2f} kN·m (factor {gamma:g}) on {total:g} × {depth:g} mm; {f_note}",
            "strength",
        )
    ]
    il = t.interlayers.get(fin.interlayer)
    g_il = float(il.short) if il else 0.0
    th = effective_thickness(plies, float(fin.interlayerThickness), g_il, e, span)
    if not fin.restrained:
        hef = th["deflection"]
        iz = depth * hef**3 / 12
        it = depth * hef**3 / 3
        g = e / (2 * (1 + nu))
        mcr = 1.13 * math.pi / span * math.sqrt(e * iz * g * it)
        k = float(t.finBuckling)
        checks.append(
            _row(
                "Glass fin: lateral-torsional buckling",
                k * m,
                mcr,
                "N·mm",
                f"Mcr = C1 π/L √(E Iz G It) = {mcr / 1e6:.2f} kN·m on hef = {hef:.2f} mm "
                f"(ω = {th['omega']:.2f}); design moment × {k:g}",
                "fin",
            )
        )
        checks[-1]["unit"] = "kN·m"
        checks[-1]["demand"] = round(k * m / 1e6, 2)
        checks[-1]["capacity"] = round(mcr / 1e6, 2)
    inertia = total * depth**3 / 12
    defl = 5 * q * span**4 / (384 * e * inertia)
    divisor = float(t.deflection.twoEdges)
    limit = span / divisor
    if float(t.deflection.absolute) > 0:
        limit = min(limit, float(t.deflection.absolute))
    checks.append(
        _row("Glass fin: deflection", defl, limit, "mm", f"span / {divisor:g}", "deflectionLimit")
    )
    strength_rows = [c for c in checks if not c["flag"]]
    return {
        "id": type_id,
        "kind": "glassFin",
        "type": type_id,
        "members": [],
        "checks": checks,
        "utilisation": max((c["utilisation"] for c in strength_rows), default=0.0),
        "ok": all(c["ok"] for c in strength_rows),
        "material": material.id,
        "glass": {"plies": plies, "kind": material.glass.kind, "depth": depth},
    }


def design_types(types: dict[str, Any], mats: dict[str, Any]) -> tuple[list, list, list[str]]:
    """The glass types of 04 Objects designed: (entries, skipped, notes)."""
    entries: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    found = []
    for type_id, o in types.items():
        material = mats.get(getattr(o, "material", None))
        if not is_glass(material):
            continue
        panel, fin = getattr(o, "glass", None), getattr(o, "glassFin", None)
        if panel is None and fin is None:
            continue
        found.append((type_id, o, material, panel, fin))
    if not found:
        return [], [], []
    if table() is None:
        for type_id, o, *_ in found:
            skipped.append(
                {
                    "id": type_id,
                    "kind": o.kind,
                    "type": type_id,
                    "reason": "structural glass is not covered by the code pack",
                }
            )
        return [], skipped, []
    for type_id, o, material, panel, fin in found:
        try:
            if panel is not None:
                entries.append(check_panel(type_id, panel, material, o.kind == "slab"))
            if fin is not None:
                entries.append(check_fin(type_id, fin, o.profile, material))
        except (GlassDesignError, KeyError, ValueError, ZeroDivisionError) as error:
            skipped.append({"id": type_id, "kind": o.kind, "type": type_id, "reason": str(error)})
    return entries, skipped, []


def method_lines() -> list[str]:
    t = table()
    if t is None:
        return []
    how = (
        "partial factors fg;d = kmod ksp fg;k / γM;A + kv (fb;k - fg;k) / γM;v"
        if t.method == "partialFactors"
        else "load resistance: the allowable 3 s stress × the glass type and load duration "
        "factors (the load charts approximated)"
    )
    return [
        (
            f"Structural glass ({_clause('code')}): {how}; laminated glass by the effective "
            "thickness with the Wölfel-Bennison ω of the interlayer's shear modulus; stresses and "
            "deflections on linear plate theory (on the safe side), balustrades with the pack's "
            "barrier line load; fins with their lateral-torsional buckling."
        )
    ]
