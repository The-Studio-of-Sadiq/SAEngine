"""Embedded walls of excavations: embedment, bending moment and prop force (alpha 9 P7).

The method and its values are the code pack's ``embeddedWalls`` table
(:class:`saengine.codes.practice_tables.EmbeddedWallsTable`); a pack without it does not
design embedded walls. The default pack's BNBC 2020 asks for retained excavation sides (Part 6
Sec 3.12) and gives no method: the method is SAEngine practice there, and the report says so.
The sheet, contiguous and secant pile sections, the walers, the struts and the ground anchors
of staged excavations are not designed here (the wall's bending capacity per metre is an
input).

Per metre run of wall, depths z [m] below the retained ground: the soil of the nearest
borehole (:func:`saengine.substructure.earth_pressure.soil_column`), the design dig level
the excavation's depth H plus the unplanned excavation ΔH = min(``overdigShare`` H,
``overdigMax``). Behind the wall the active pressure with the surcharge q (the largest of the
excavation's loads, else the pack's ``minimumSurcharge``) and the water; in front, below the
dig level, the passive pressure and the water (the front dewatered to the dig level). The
pressures are the earth pressure engine's (:class:`~saengine.substructure.earth_pressure.Soil`:
Rankine, c' and cu terms, no tension):

- ``factoredPassive``: the passive soil pressure divided by ``passiveFactor``;
- ``partialFactors``: tan φ', c' and cu divided by the pack's ``geotechnicalMethods``
  materials set, the surcharge × ``variableFactor``.

The net pressure p(z) = active + water behind - (passive + water in front). Then:

- **cantilever** (fixed earth support, Blum's simplification): d0 below the dig level where
  the moment of p about the toe vanishes, d = ``embedmentIncrease`` × d0;
- **propped, free earth support**: d0 where the moment of p about the prop vanishes, the prop
  force T = ∫ p, d = ``freeEarthIncrease`` × d0;
- **propped, fixed earth support** (Blum's equivalent beam): the beam from the prop to the
  point of zero net pressure z0 (a hinge) gives T and the reaction R at z0; below z0 the
  depth x where R and the net passive pressure balance about the toe, d0 = z0 - H' + x, d =
  ``embedmentIncrease`` × d0.

The largest bending moment is that of the beam over its length (the cantilever down to the
toe of d0; the propped wall with T), against the wall's moment capacity per metre where the
wall gives one; the embedment against the toe the wall gives. Units: m, kPa, kN/m, kN·m/m.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.substructure.earth_pressure import Soil

#: Step of the pressure diagram [m].
STEP = 0.02
#: Deepest embedment searched below the dig level, as a multiple of it (and at least) [m].
REACH = (4.0, 15.0)


def table() -> Any | None:
    """The pack's ``embeddedWalls`` table, or None when the pack does not cover it."""
    pack = code_context.current()
    return pack.table("embeddedWalls") if pack.has("embeddedWalls") else None


def clause(key: str) -> str:
    found = table()
    return str((found.clauses or {}).get(key) or found.source) if found is not None else ""


def factored_soil(soil: Soil, rules: Any) -> tuple[Soil, str]:
    """The soil with the pack's partial factors on its strengths (``partialFactors``), and
    how; the soil itself for ``factoredPassive``."""
    if rules.method != "partialFactors":
        return soil, ""
    pack = code_context.current()
    sets = pack.table("geotechnicalMethods").materials if pack.has("geotechnicalMethods") else {}
    m = sets.get(rules.materials)
    if m is None:
        return soil, f"no materials set {rules.materials}: the strengths unfactored"
    layers = []
    for lay in soil.layers:
        top, bottom, g, gs, phi, *rest = lay
        c = float(rest[0]) if rest and rest[0] else 0.0
        if phi is not None:
            phi_d = math.degrees(math.atan(math.tan(math.radians(phi)) / m.tanPhi))
            c_d = c / m.cohesion
        else:
            phi_d, c_d = None, c / m.undrained
        layers.append((top, bottom, g, gs, phi_d, c_d, *rest[1:]))
    out = Soil(layers, soil.water_table, soil.surcharge, soil.k0_cohesive, soil.source)
    return out, (
        f"set {rules.materials}: tan φ' / {m.tanPhi:g}, c' / {m.cohesion:g}, cu / {m.undrained:g}"
    )


def net_pressure(soil: Soil, dig: float, surcharge: float, rules: Any, bottom: float):
    """``(z, p)``: depths [m] and the net pressure [kPa] (active and water behind less the
    factored passive and water in front below ``dig``) down to ``bottom``."""
    behind = Soil(soil.layers, soil.water_table, surcharge, soil.k0_cohesive, soil.source)
    front = soil.below(dig)
    divide = rules.passiveFactor if rules.method == "factoredPassive" else 1.0
    zs = np.arange(0.0, bottom + STEP / 2, STEP)
    p = np.zeros_like(zs)
    for i, z in enumerate(zs):
        a = behind.pressure(max(z, 1e-6), "active")["total"]
        if z > dig:
            f = front.pressure(z - dig, "passive", surcharge=False)
            a -= f["soil"] / divide + f["water"]
        p[i] = a
    return zs, p


def _cumulative(zs: np.ndarray, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """F(z) = ∫0^z p and S(z) = ∫0^z p s ds (trapezoids)."""
    dz = np.diff(zs)
    f = np.concatenate([[0.0], np.cumsum((p[1:] + p[:-1]) / 2 * dz)])
    ps = p * zs
    s = np.concatenate([[0.0], np.cumsum((ps[1:] + ps[:-1]) / 2 * dz)])
    return f, s


def _first_root(values: np.ndarray, start: int) -> int | None:
    """The first index from ``start`` where ``values`` changes sign from positive."""
    for i in range(max(start, 1), len(values)):
        if values[i - 1] > 0 >= values[i]:
            return i
    return None


def _moments(zs: np.ndarray, f: np.ndarray, s: np.ndarray, prop: float | None, t: float):
    """M(z) = ∫0^z p (z - s) ds - T (z - zp) over the depths."""
    m = zs * f - s
    if prop is not None:
        m = m - t * np.clip(zs - prop, 0.0, None)
    return m


def design_wall(
    soil: Soil,
    height: float,
    kind: str,
    support: str,
    prop: float | None,
    surcharge: float | None,
) -> dict[str, Any]:
    """The embedded wall of an excavation ``height`` m deep (see the module notes): ``kind``
    cantilever / propped, ``support`` free / fixed (propped walls), ``prop`` its depth [m]
    below the retained ground, ``surcharge`` [kPa] (None: the pack's least). Returns ``{"ok",
    "dig", "d0", "d", "Mmax", "zM", "T", "q", "basis", "notes"}`` (``ok`` False with ``reason``
    when no embedment balances the wall)."""
    rules = table()
    if rules is None:
        return {"ok": False, "reason": "the code pack does not cover embedded walls"}
    notes: list[str] = []
    overdig = min(rules.overdigShare * height, rules.overdigMax)
    dig = height + overdig
    q = max(surcharge if surcharge is not None else 0.0, rules.minimumSurcharge)
    q *= rules.variableFactor
    used, how = factored_soil(soil, rules)
    if how:
        notes.append(how)
    reach = max(REACH[0] * dig, REACH[1])
    zs, p = net_pressure(used, dig, q, rules, dig + reach)
    f, s = _cumulative(zs, p)
    start = round(dig / STEP)
    t = 0.0
    if kind == "cantilever" or prop is None:
        if kind != "cantilever":
            notes.append("no prop level: designed as a cantilever")
        kind = "cantilever"
        # Moment about the toe at zt: zt F - S = 0.
        balance = zs * f - s
        i = _first_root(balance, start + 1)
        if i is None:
            return {"ok": False, "reason": "no embedment within reach balances the wall"}
        toe = float(zs[i])
        d0 = toe - dig
        d = rules.embedmentIncrease * d0
        increase = rules.embedmentIncrease
        m = _moments(zs[: i + 1], f[: i + 1], s[: i + 1], None, 0.0)
        reaction = -float(f[i])
    elif support == "free":
        # Moment about the prop: ∫ p (s - zp) = S - zp F = 0 at the toe.
        balance = s - prop * f
        i = _first_root(balance, start + 1)
        if i is None:
            return {"ok": False, "reason": "no embedment within reach balances the wall"}
        toe = float(zs[i])
        t = float(f[i])
        d0 = toe - dig
        d = rules.freeEarthIncrease * d0
        increase = rules.freeEarthIncrease
        m = _moments(zs[: i + 1], f[: i + 1], s[: i + 1], prop, t)
        reaction = 0.0
    else:
        zero = next((k for k in range(start + 1, len(zs)) if p[k] <= 0), None)
        if zero is None:
            return {"ok": False, "reason": "the net pressure stays positive within reach"}
        z0 = float(zs[zero])
        # Upper beam prop..z0, hinge at z0: T (z0 - zp) = ∫0^z0 p (z0 - s) ds.
        t = float((z0 * f[zero] - s[zero]) / max(z0 - prop, 1e-6))
        r = float(f[zero]) - t
        x = None
        for k in range(zero + 1, len(zs)):
            # About the toe zk: R (zk - z0) + ∫z0^zk p (zk - s) ds = 0.
            moment = r * (zs[k] - z0) + (zs[k] * (f[k] - f[zero]) - (s[k] - s[zero]))
            if moment <= 0:
                x = float(zs[k] - z0)
                break
        if x is None:
            return {"ok": False, "reason": "no embedment within reach fixes the wall"}
        d0 = z0 - dig + x
        d = rules.embedmentIncrease * d0
        increase = rules.embedmentIncrease
        m = _moments(zs[: zero + 1], f[: zero + 1], s[: zero + 1], prop, t)
        reaction = r
    peak = int(np.argmax(np.abs(m)))
    method = (
        f"passive / {rules.passiveFactor:g}"
        if rules.method == "factoredPassive"
        else f"factored strengths ({how or rules.materials}), q × {rules.variableFactor:g}"
    )
    names = {
        "cantilever": "cantilever, fixed earth support (Blum)",
        "free": "propped, free earth support",
        "fixed": "propped, fixed earth support (Blum's equivalent beam)",
    }
    basis = (
        f"{names['cantilever' if kind == 'cantilever' else support]}; dig {dig:.2f} m "
        f"(H {height:.2f} + overdig {overdig:.2f} m), q = {q:.1f} kPa, {method}; "
        f"d = {increase:g} × d0"
    )
    return {
        "ok": True,
        "kind": kind,
        "dig": dig,
        "d0": d0,
        "d": d,
        "Mmax": float(abs(m[peak])),
        "zM": float(zs[peak]),
        "T": t,
        "R": reaction,
        "q": q,
        "basis": basis,
        "notes": notes,
    }


def wall_checks(excavation: Any, ground: float, soil: Soil) -> tuple[list[dict], list[str]]:
    """The checks of an excavation's embedded wall (``excavation.wall``,
    :class:`saengine.library.substructure.EmbeddedWall`), levels in mm (project datum)."""
    from saengine.design.check import _check

    wall = getattr(excavation, "wall", None)
    if wall is None:
        return [], []
    rules = table()
    if rules is None:
        name = code_context.code_name()
        return [], [f"Embedded walls: not covered by the code pack {name}"]
    height = (ground - excavation.bottomLevel) / 1e3
    if height <= 0:
        return [], []
    prop = None if wall.propLevel is None else (ground - wall.propLevel) / 1e3
    loads = [float(x.pressure) for x in excavation.loads if x.pressure is not None]
    surcharge = wall.surcharge if wall.surcharge is not None else max(loads, default=None)
    found = design_wall(soil, height, wall.kind, wall.earthSupport, prop, surcharge)
    ref = clause("method")
    if not found["ok"]:
        return [
            _check("Embedded wall embedment", 1.0, 0.0, "", None, f"{found['reason']} ({ref})")
        ], []
    checks: list[dict[str, Any]] = []
    need = found["d"] * 1e3
    if wall.toeLevel is not None:
        given = excavation.bottomLevel - wall.toeLevel
        checks.append(
            _check(
                "Embedded wall embedment",
                need,
                given,
                "mm",
                None,
                f"d = {found['d']:.2f} m below the excavation (d0 = {found['d0']:.2f} m); "
                f"{found['basis']} ({ref})",
            )
        )
    else:
        checks.append(
            _check(
                "Embedded wall embedment",
                need,
                need,
                "mm",
                None,
                f"required d = {found['d']:.2f} m below the excavation, toe at "
                f"{(excavation.bottomLevel - need) / 1e3:.2f} m; no toe given; {found['basis']} "
                f"({ref})",
                flag=True,
            )
        )
    moment_note = f"Mmax = {found['Mmax']:.1f} kN·m/m at {found['zM']:.2f} m below the ground"
    if wall.momentCapacity:
        checks.append(
            _check(
                "Embedded wall bending",
                found["Mmax"],
                float(wall.momentCapacity),
                "kN·m/m",
                None,
                f"{moment_note}; against the wall's capacity per metre ({ref})",
            )
        )
    else:
        checks.append(
            _check(
                "Embedded wall bending",
                found["Mmax"],
                found["Mmax"],
                "kN·m/m",
                None,
                f"{moment_note}; no moment capacity given: reported only ({ref})",
                flag=True,
            )
        )
    if found["kind"] == "propped":
        spacing = wall.propSpacing
        per_prop = found["T"] * (spacing / 1e3 if spacing else 1.0)
        checks.append(
            _check(
                "Prop force",
                per_prop,
                per_prop,
                "kN" if spacing else "kN/m",
                None,
                f"T = {found['T']:.1f} kN/m"
                + (f" × {spacing / 1e3:.2f} m spacing" if spacing else "")
                + " at the prop; the struts, walers and anchors are designed separately",
                flag=True,
            )
        )
    return checks, [f"embedded wall: {n}" for n in found["notes"]]
