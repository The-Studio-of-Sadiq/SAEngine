"""Joints at the ends of timber members, with the code pack's ``timber`` table (with the bnbc2020
pack: BNBC 2020 Part 6 Sec 11.7, 11.9, 11.10, 11.18 and 11.5.3.2.3).

The joint of a member type (:class:`saengine.library.objects.TimberJoint`) is checked at both
ends of each member for the end forces of every allowable stress combination: the axial force
P along the grain and the shear V across it.

- Nails (double shear through splice or gusset plates): the table's permissible lateral
  strength of the species and nail size (lengthening, node or temporary joints; clenched points
  more), times the load duration factor K2; nails at least the minimum count, the diameter
  between the limits of the least member thickness, the main and splice thicknesses, and the
  end distance, spacing, edge distance and rows in multiples of the shank diameter.
- Bolts (wooden splice plates): per bolt P = fcp a λ1 along the grain, R = fcn a λ2 df across
  it and F = P R / (P sin²θ + R cos²θ) at the angle θ of the end force to the grain, a = t' d;
  half in single shear; times K2. Counts, member thicknesses, spacing, end and edge distances.
- Split-ring connectors: the member thicknesses and the loaded edge and end distances (the code
  gives no connector loads: their capacity is flagged as not covered).
- Disc-dowels: their size and clearances, and per dowel the lesser of the shear π d²/4 s and
  the bearing d t/2 c of the dowel timber, times K2 (to be confirmed by tests).
- Wood screws and nails in withdrawal: the code gives no design values (flagged when relevant).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from saengine.design.ductile_members import _row
from saengine.design.timber.members import (
    Section,
    Timber,
    TimberDesignError,
    _flag,
    _table,
    clause,
)


def _at_least(name: str, required: float, provided: float, unit: str = "mm", note: str = ""):
    return _row(name, required, provided, unit, note=note)


def _at_most(name: str, provided: float, limit: float, unit: str = "mm", note: str = ""):
    return _row(name, provided, limit, unit, note=note)


def _within(name: str, value: float, lo: float, hi: float, unit: str = "mm") -> dict[str, Any]:
    u = max(lo / value if value > 0 else math.inf, value / hi)
    return _row(
        name, value, hi if value > hi else lo, unit, note=f"{lo:g} to {hi:g}", utilisation=u
    )


def end_forces(stations: Sequence[Any]) -> list[tuple[str, str, float, float]]:
    """``(combination, "start" | "end", P [N, compression positive], V [N])`` of every
    combination at both member ends."""
    out = []
    for st in stations:
        if not len(st.s):
            continue
        for label, i in (("start", 0), ("end", -1)):
            p = float(np.asarray(st.P)[i])
            v = math.hypot(float(np.asarray(st.Vy)[i]), float(np.asarray(st.Vx)[i]))
            out.append((st.combination, label, p, v))
    return out


def lateral_nail_strength(size: str, species: str, joint: str, temporary: bool) -> float:
    """Permissible lateral strength of one nail in double shear [N] (before K2), or raises
    :class:`TimberDesignError` when the table has no value for the species."""
    sizes = _table().nails.sizes
    if size not in sizes:
        raise TimberDesignError(f"nail size {size} mm is not in the code's tables")
    row = sizes[size].strengths.get(species)
    if row is None:
        raise TimberDesignError(
            f"the code's nail tables give no strength of {size} mm nails in '{species}'"
        )
    if temporary:
        return float(row.temporary)
    return float(row.lengthening if joint == "lengthening" else row.node)


def bolt_factors(ratio: float) -> tuple[float | None, float]:
    """(λ1 along the grain, λ2 across it) [fractions] at t'/d3 = ``ratio``, interpolated; λ1
    None beyond the table's parallel column. Below the first row: the first row's."""
    rows = sorted(_table().bolts.bearing, key=lambda r: float(r.ratio))
    xs = [float(r.ratio) for r in rows]
    lam2 = float(np.interp(ratio, xs, [float(r.perpendicular) for r in rows])) / 100
    par = [(float(r.ratio), float(r.parallel)) for r in rows if r.parallel is not None]
    if ratio > par[-1][0] + 1e-9:
        lam1 = None
    else:
        lam1 = float(np.interp(ratio, [x for x, _ in par], [y for _, y in par])) / 100
    if ratio > xs[-1] + 1e-9:
        raise TimberDesignError(f"t'/d = {ratio:.1f} is beyond the code's bolt table")
    return lam1, lam2


def bolt_capacity(
    fc: float, fcn: float, t: float, d: float, theta: float, single: bool = False
) -> float:
    """Permissible load of one bolt [N] at ``theta`` [rad] to the grain (before K2): main member
    ``t`` thick, bolt ``d`` [mm], double shear (``single``: half)."""
    b = _table().bolts
    lam1, lam2 = bolt_factors(t / d)
    df = b.diameterFactor.get(f"{d:g}")
    if df is None:
        raise TimberDesignError(f"bolt diameter {d:g} mm has no diameter factor in the code")
    a = t * d
    r = fcn * a * lam2 * float(df)
    if theta > math.pi / 2 - 1e-9:
        load = r
    else:
        if lam1 is None:
            raise TimberDesignError(
                f"t'/d = {t / d:.1f}: the code's bolt table gives no value along the grain"
            )
        p = fc * a * lam1
        load = p * r / (p * math.sin(theta) ** 2 + r * math.cos(theta) ** 2)
    return load * (float(b.singleShear) if single else 1.0)


def dowel_capacity(d: float, t: float, s: float, c: float) -> float:
    """One disc-dowel [N]: the lesser of the shear π d²/4 s and the bearing d t/2 c."""
    return min(math.pi * d * d / 4 * s, d * t / 2 * c)


def _governing(
    forces: list[tuple[str, str, float, float]], capacity: Any, k2: dict[str, float]
) -> tuple[float, float, str, str, float]:
    """(demand, capacity, combination, end, θ) of the worst end: ``capacity(θ)`` the joint's
    capacity before K2."""
    best = (0.0, 1.0, "", "", 0.0)
    worst = -1.0
    for name, end, p, v in forces:
        f = math.hypot(p, v)
        if f <= 0:
            continue
        theta = math.atan2(v, abs(p))
        cap = float(k2.get(name, 1.0)) * capacity(theta)
        u = f / cap if cap > 0 else math.inf
        if u > worst:
            worst, best = u, (f, cap, name, end, theta)
    return best


def check_joint(
    joint: Any,
    section: Section,
    timber: Timber,
    stations: Sequence[Any],
    k2: dict[str, float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The check rows of a member's end joints and a summary for the report."""
    forces = end_forces(stations)
    tension = any(p < 0 for _, _, p, _ in forces)
    kind = getattr(joint, "type", None)
    if kind == "nails":
        rows, summary = _nails(joint, section, timber, forces, tension, k2)
    elif kind == "bolts":
        rows, summary = _bolts(joint, section, timber, forces, tension, k2)
    elif kind == "splitRing":
        rows, summary = _rings(joint, section)
    elif kind == "discDowel":
        rows, summary = _dowels(joint, section, timber, forces, tension, k2)
    else:
        raise TimberDesignError(f"unknown timber joint '{kind}'")
    return rows, summary


def _capacity_row(
    title: str, best: tuple[float, float, str, str, float], note: str
) -> dict[str, Any]:
    demand, cap, name, end, theta = best
    return _row(
        title,
        demand / 1e3,
        cap / 1e3,
        "kN",
        name or None,
        f"{end}: θ = {math.degrees(theta):.0f}° to the grain; {note}",
    )


def _nails(joint, section, timber, forces, tension, k2):
    nails = _table().nails
    size = nails.sizes.get(joint.size)
    if size is None:
        raise TimberDesignError(f"nail size {joint.size} mm is not in the code's tables")
    n = float(size.diameter)
    species = joint.species or timber.species
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"type": "nails", "size": joint.size, "count": joint.count}
    title = f"Joint: {joint.count} nails {joint.size} mm per end ({clause('nails')}; " + (
        f"{clause('fastenerDuration')})"
    )
    strength = None
    if species:
        try:
            strength = lateral_nail_strength(joint.size, species, joint.joint, joint.temporary)
        except TimberDesignError as error:
            rows.append(_flag(_row(title, 0.0, 1.0, "kN", note=f"not covered: {error}")))
    else:
        rows.append(
            _flag(
                _row(
                    title,
                    0.0,
                    1.0,
                    "kN",
                    note="not covered: the code's nail strengths are by species; give the "
                    "species of the material or the joint",
                )
            )
        )
    if strength is not None:
        if joint.clenched:
            strength *= float(nails.clenched)
        best = _governing(forces, lambda _t: joint.count * strength, k2)
        rows.append(
            _capacity_row(
                title,
                best,
                f"{strength / 1e3:.2f} kN per nail in double shear ({species})",
            )
        )
        summary["strength"] = strength
    least = min(section.b, float(joint.sideThickness))
    minimum = nails.minLengthening if joint.joint == "lengthening" else nails.minNode
    rule = clause("nailRules")
    rows += [
        _at_least(f"Nails per end ({rule})", float(minimum), float(joint.count), ""),
        _within(
            f"Nail diameter, least thickness / {float(nails.diameterMin):g} to / "
            f"{float(nails.diameterMax):g} ({rule})",
            n,
            least / float(nails.diameterMin),
            least / float(nails.diameterMax),
        ),
        _at_least(f"Main member thickness ({rule})", float(nails.minThickness), section.b),
    ]
    sp = nails.spacing
    space = clause("nailSpacing")
    end = float(sp.endTension if tension else sp.endCompression)
    along = float(sp.alongTension if tension else sp.alongCompression)
    which = "tension" if tension else "compression"
    rows += [
        _at_least(f"Nail end distance, {which} ({space})", end * n, float(joint.endDistance)),
        _at_least(
            f"Nail spacing along the grain, {which} ({space})", along * n, float(joint.spacing)
        ),
        _at_least(f"Nail edge distance ({space})", float(sp.edge) * n, float(joint.edgeDistance)),
        _at_least(
            f"Nail rows across the grain ({space})", float(sp.rows) * n, float(joint.rowSpacing)
        ),
    ]
    return rows, summary


def _bolts(joint, section, timber, forces, tension, k2):
    b = _table().bolts
    d = float(joint.diameter)
    t = float(joint.mainThickness or section.b)
    single = joint.shear == "single"
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"type": "bolts", "diameter": d, "count": joint.count}
    title = (
        f"Joint: {joint.count} bolts M{d:g} per end, {joint.shear} shear ({clause('bolts')}; "
        f"{clause('fastenerDuration')})"
    )
    try:
        best = _governing(
            forces,
            lambda theta: joint.count * bolt_capacity(timber.fc, timber.fcn, t, d, theta, single),
            k2,
        )
        rows.append(_capacity_row(title, best, f"t'/d = {t / d:.2f}"))
        governing_theta = best[4]
    except TimberDesignError as error:
        rows.append(_flag(_row(title, 0.0, 1.0, "kN", note=f"not covered: {error}")))
        governing_theta = 0.0
    rule = clause("boltRules")
    minimum = b.minLengthening if joint.joint == "lengthening" else b.minNode
    rows += [
        _at_least(f"Bolts per end ({rule})", float(minimum), float(joint.count), ""),
        _at_least(f"Main member thickness ({rule})", float(b.minMain), t),
        _at_least(
            f"Side member thickness ({rule})",
            max(float(b.minSide), float(b.sideShare) * t),
            float(joint.sideThickness),
        ),
    ]
    sp = b.spacing
    space = clause("boltSpacing")
    across = governing_theta > math.pi / 4
    rows.append(
        _at_least(f"Bolt spacing in a row ({space})", float(sp.inRow) * d, float(joint.spacing))
    )
    if joint.rows > 1:
        if across:
            ratio = min(max(t / d, float(sp.ratioLow)), float(sp.ratioHigh))
            need = float(
                np.interp(
                    ratio,
                    [float(sp.ratioLow), float(sp.ratioHigh)],
                    [float(sp.rowsPerpendicularLow), float(sp.rowsPerpendicularHigh)],
                )
            )
        else:
            need = float(sp.rowsParallel)
        rows.append(
            _at_least(f"Spacing between rows of bolts ({space})", need * d, float(joint.rowSpacing))
        )
    if tension:
        end = float(sp.endTensionHardwood if joint.hardwood else sp.endTensionSoftwood)
        which = "tension, " + ("hardwood" if joint.hardwood else "softwood")
    else:
        end, which = float(sp.endCompression), "compression"
    rows.append(
        _at_least(f"Bolt end distance, {which} ({space})", end * d, float(joint.endDistance))
    )
    edge = (
        float(sp.edgePerpendicular) * d
        if across
        else max(float(sp.edgeParallel) * d, float(joint.rowSpacing) / 2)
    )
    rows.append(_at_least(f"Bolt edge distance ({space})", edge, float(joint.edgeDistance)))
    return rows, summary


def _rings(joint, section):
    c = _table().connectors
    t = float(joint.mainThickness or section.b)
    d = float(joint.diameter)
    rule = clause("rings")
    rows = [
        _at_least(f"Split ring: main member thickness ({rule})", float(c.ringMinMain), t),
        _at_least(
            f"Split ring: side member thickness ({rule})",
            float(c.ringMinSide),
            float(joint.sideThickness),
        ),
        _at_least(
            f"Split ring: loaded edge distance ({rule})",
            float(c.ringEdge) * d,
            float(joint.edgeDistance),
        ),
        _at_least(
            f"Split ring: end distance ({rule})", float(c.ringEnd) * d, float(joint.endDistance)
        ),
        _flag(
            _row(
                f"Split ring connector load ({rule})",
                0.0,
                1.0,
                "kN",
                note="not covered: the code pack gives no connector loads",
            )
        ),
    ]
    return rows, {"type": "splitRing", "diameter": d, "count": joint.count}


def _dowels(joint, section, timber, forces, tension, k2):
    c = _table().connectors
    d, t = float(joint.diameter), float(joint.thickness)
    rule = clause("dowels")
    dowel = (
        Timber.of(timber.group, timber.location, species=joint.species) if joint.species else timber
    )
    per = dowel_capacity(d, t, dowel.fva, dowel.fc)
    best = _governing(forces, lambda _t: joint.count * per, k2)
    rows = [
        _capacity_row(
            f"Joint: {joint.count} disc-dowels {d:g} x {t:g} mm per end ({rule}; "
            f"{clause('fastenerDuration')})",
            best,
            f"{per / 1e3:.2f} kN per dowel, the lesser of π d²/4 s and d t/2 c; to be "
            "confirmed by sample tests",
        ),
        _within(f"Disc-dowel thickness ({rule})", t, *map(float, c.dowelThickness)),
        _within(f"Disc-dowel diameter ({rule})", d, *map(float, c.dowelDiameter)),
        _within(f"Disc-dowel diameter / thickness ({rule})", d / t, *map(float, c.dowelRatio), ""),
        _within(
            f"Disc-dowel edge clearance ({rule})",
            float(joint.edgeClearance),
            *map(float, c.dowelEdge),
        ),
        _at_least(
            f"Disc-dowel end clearance, {'tension' if tension else 'compression'} ({rule})",
            (float(c.dowelEndTension) if tension else float(c.dowelEndCompression)) * d,
            float(joint.endClearance),
        ),
    ]
    return rows, {"type": "discDowel", "diameter": d, "count": joint.count, "strength": per}
