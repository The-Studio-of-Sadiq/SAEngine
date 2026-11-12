"""Lattice telecom towers: wind on each panel by its faces' solidity, the antennas and feed lines,
the frame's member forces and the members' checks; a rooftop tower's wind on the building.

Geometry: :class:`saengine.library.shapes.TrussTower` (the 3D modeller's tower shape) from the
tower's height, widths, panels and bracing; its members are the object types of the legs,
bracing and horizontals (04 Objects), designed by the pack's steel member method
(:mod:`saengine.design.steel.pack_resistance`).

Wind, panel by panel (the code pack's ``latticeTowers``; a pack without it takes the trussed
tower coefficients of its wind table's open structures, as the building's special structures
do):

- solidity ε = Af / Ag of a face: its members' projected area (outer width × length) over the
  face's gross area (the trapezoid between the panel points);
- Cf of the face: ``quadratic`` a ε² + b ε + c by cross-section, with round members' area × the
  round factor (at most 1); ``annexB`` base C1 (1 - C2 ε + ε²); a square tower's wind on its
  diagonal × (base + k ε, at most the cap);
- F = qz G Cf (Af,flat + Rr Af,round) at the panel's mid-height (qz the pack's velocity pressure
  at the site, :func:`saengine.fem.loads.velocity_pressure`), shared equally by the panel's
  corner nodes at its two levels;
- antennas: F = qz G EPA (× the pack's shielding factor) at their elevation, on the corners of
  the nearest level; feed lines and ladders: their area per metre × Ca 1.2 (SAEngine practice).

Cases D (members, antennas, feed lines) and the wind normal to a face and on the diagonal
(square towers), combined by the pack's strength combinations with wind
(:func:`saengine.special.common.strength_pairs`). Each member is checked for |N| / NRd + |M| /
MRd by the pack's steel method (K L of the pack's ``lengths``). The base reactions are given for
the foundations (and, for a rooftop tower, as the loads on the roof).

Not covered: ice, the tower's dynamic response (gust factor for flexible towers), guyed masts,
twist and sway limits of the antennas, connections and anchor bolts. Units: m, kN.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from saengine.codes import context as code_context
from saengine.special import common
from saengine.special import frame as fr

#: Force coefficient of feed lines and ladders (SAEngine practice, round linear members).
LINEAR_CA = 1.2


def tower_shape(tower: Any) -> Any:
    from saengine.library.shapes import TrussTower

    return TrussTower(
        height=tower.height * 1000,
        baseWidth=tower.baseWidth * 1000,
        topWidth=tower.topWidth * 1000,
        section=tower.section,
        panels=tower.panels,
        bracing=tower.bracing,
        memberType=tower.legType,
        bracingType=tower.bracingType,
        horizontalType=tower.horizontalType,
        supports="pinned",
    )


class _Coefficients:
    """The face force coefficient of the pack in force."""

    def __init__(self) -> None:
        pack = code_context.current()
        self.code = code_context.code_name(pack)
        self.table = pack.table("latticeTowers") if pack.has("latticeTowers") else None
        self.wind = None
        if self.table is None:
            self.wind = (
                getattr(pack.table("wind"), "openStructures", None) if pack.has("wind") else None
            )
        if self.table is None and self.wind is None:
            raise ValueError(f"lattice towers: not covered by the code pack {self.code}")

    @property
    def gust(self) -> float:
        if self.table is not None:
            return float(self.table.gust)
        from saengine.fem.loads import wind_factor

        return float(wind_factor("gust"))

    def source(self) -> str:
        if self.table is not None:
            clause = (self.table.clauses or {}).get("cf", "")
            return f"{self.code} {clause}".strip()
        return f"{self.code} wind, trussed towers (open structures)"

    def cf(self, solidity: float, section: str, diagonal: bool) -> tuple[float, float]:
        """(Cf of the face for flat members, the round member factor Rr)."""
        e = min(max(solidity, 0.0), 1.0)
        if self.table is None:
            from saengine.fem.open_wind import tower_cf

            flat = tower_cf(self.wind, e, section, rounded=False, diagonal=diagonal)
            rounded = tower_cf(self.wind, e, section, rounded=True, diagonal=diagonal)
            return flat, (rounded / flat if flat else 1.0)
        t = self.table
        if t.method == "annexB":
            c1, c2 = t.annexB.square if section == "square" else t.annexB.triangular
            flat = t.annexB.base * c1 * (1 - c2 * e + e * e)
            rr = 1.0
        else:
            q = t.squareTower if section == "square" else t.triangularTower
            flat = q.a * e * e + q.b * e + q.c
            r = t.roundTower
            rr = min(1.0, r.a * e * e + r.b * e + r.c) if r is not None else 1.0
        if diagonal and section == "square":
            k, cap = t.diagonalFactor
            flat *= min(cap, t.diagonalBase + k * e)
        return float(flat), float(rr)

    def lengths(self) -> tuple[float, float]:
        if self.table is None:
            return 1.0, 1.0
        return float(self.table.lengths.legs), float(self.table.lengths.bracing)


def panel_winds(
    tower: Any,
    shape: Any,
    types: dict[str, common.MemberType],
    qz: Any,
    coefficients: Any,
    diagonal: bool,
) -> list[dict[str, Any]]:
    """Each panel's wind: ``z`` (mid-height above the ground), ε, Cf, Rr, the projected areas
    and the force F [kN]."""
    levels = [z / 1000 for z in shape.levels()]
    corners = [[np.array(c) / 1000 for c in shape.corners_at(z * 1000)] for z in levels]
    geometry = shape.local()
    out = []
    for k in range(len(levels) - 1):
        z0, z1 = levels[k], levels[k + 1]
        a, b = corners[k][0], corners[k][1]  # face 0 at its bottom
        c, d = corners[k + 1][1], corners[k + 1][0]
        face_normal = np.cross(b - a, d - a)
        face_normal /= np.linalg.norm(face_normal)
        gross = 0.5 * (np.linalg.norm(b - a) + np.linalg.norm(c - d)) * (z1 - z0)
        flat = rounded = 0.0
        for m in geometry.members:
            p, q = m.start / 1000, m.end / 1000
            if not (z0 - 1e-6 <= min(p[2], q[2]) and max(p[2], q[2]) <= z1 + 1e-6):
                continue
            # in face 0: both ends on its plane
            if abs(float((p - a) @ face_normal)) > 1e-3 or abs(float((q - a) @ face_normal)) > 1e-3:
                continue
            kind = types[m.type]
            area = kind.width * float(np.linalg.norm(q - p))
            if abs(p[2] - q[2]) < 1e-6 and abs(p[2] - z1) < 1e-6 and k < len(levels) - 2:
                area *= 0.5  # a horizontal at the panel's top is shared with the panel above
            if abs(p[2] - q[2]) < 1e-6 and abs(p[2] - z0) < 1e-6 and k > 0:
                area *= 0.5
            if kind.round:
                rounded += area
            else:
                flat += area
        solidity = (flat + rounded) / gross if gross > 0 else 0.0
        cf, rr = coefficients.cf(solidity, tower.section, diagonal)
        z = tower.baseElevation + (z0 + z1) / 2
        q_z = qz(z)
        linear = tower.linearArea * (z1 - z0) * LINEAR_CA
        force = q_z * coefficients.gust * (cf * (flat + rr * rounded) + linear)
        out.append(
            {
                "panel": k + 1,
                "z": round(z, 2),
                "solidity": round(solidity, 3),
                "Cf": round(cf, 3),
                "Rr": round(rr, 3),
                "Af": round(flat, 3),
                "Ar": round(rounded, 3),
                "qz": round(q_z, 3),
                "F": round(force, 2),
            }
        )
    return out


def antenna_forces(tower: Any, qz: Any, coefficients: Any) -> list[dict[str, Any]]:
    shielding = float(coefficients.table.antennaShielding) if coefficients.table else 1.0
    out = []
    for a in tower.antennas:
        z = tower.baseElevation + min(a.elevation, tower.height)
        force = qz(z) * coefficients.gust * a.area * shielding * a.count
        out.append(
            {
                "name": a.name,
                "z": round(z, 2),
                "F": round(force, 2),
                "weight": round(a.weight * a.count, 2),
                "elevation": a.elevation,
            }
        )
    return out


def tower_types(tower: Any, objects: Any, materials: Any) -> dict[str, common.MemberType]:
    ids = {tower.legType, tower.bracingType}
    if tower.horizontalType:
        ids.add(tower.horizontalType)
    return {i: common.member_type(i, objects, materials) for i in ids}


def rooftop_forces(settings: Any, objects: Any, materials: Any) -> Any:
    """For the building's analysis model: a function of (roof height [m], qz(z) [kN/m²]) giving
    the wind of the project's rooftop towers ``{"WX", "WY" [kN], "notes"}`` (the wind normal
    to a face, each way, the towers' bases on the roof); None without rooftop towers.
    ``objects`` and ``materials``: the libraries, or dicts of their entries by id."""
    towers = [t for t in settings.specialStructures.towers if t.onRoof]
    if not towers:
        return None

    def forces(roof: float, qz: Any) -> dict[str, Any]:
        total, notes = 0.0, []
        for tower in towers:
            try:
                types = tower_types(tower, objects, materials)
                force = tower_wind_total(tower, types, qz, roof)
            except (ValueError, KeyError) as error:
                notes.append(f"rooftop tower {tower.id}: no wind on the building ({error})")
                continue
            total += force
            notes.append(
                f"rooftop tower {tower.id}: {force:.1f} kN of wind added to the roof level "
                "(its weight is entered as joint loads; its base moment is not applied)"
            )
        return {"WX": total, "WY": total, "notes": notes}

    return forces


def tower_wind_total(
    tower: Any, types: dict[str, common.MemberType], qz: Any, base: float
) -> float:
    """The total wind force on a tower [kN] normal to a face, its base at ``base`` m."""
    coefficients = _Coefficients()
    shape = tower_shape(tower)
    placed = tower.model_copy(update={"baseElevation": base})
    panels = panel_winds(placed, shape, types, qz, coefficients, diagonal=False)
    antennas = antenna_forces(placed, qz, coefficients)
    return sum(p["F"] for p in panels) + sum(a["F"] for a in antennas)


def analyse_tower(tower: Any, settings: Any, objects: Any, materials: Any) -> dict[str, Any]:
    """The tower's wind, member checks and base reactions: ``{"panels", "antennas", "rows",
    "reactions", "notes"}``."""
    notes: list[str] = []
    coefficients = _Coefficients()
    qz, wind_notes = common.wind_pressure(settings)
    notes += wind_notes
    if qz is None:
        raise ValueError("lattice tower: the site has no wind speed")
    types = tower_types(tower, objects, materials)
    shape = tower_shape(tower)
    geometry = shape.local()
    frame = fr.Frame()
    kinds: list[str] = []
    roles: list[str] = []
    for m in geometry.members:
        frame.member(m.start / 1000, m.end / 1000, types[m.type].section)
        kinds.append(m.type)
        vertical = abs(m.start[0] - m.end[0]) + abs(m.start[1] - m.end[1]) < 0.5 * abs(
            m.start[2] - m.end[2]
        )
        roles.append(
            "leg"
            if m.type == tower.legType and vertical
            else ("horizontal" if abs(m.start[2] - m.end[2]) < 1e-6 else "bracing")
        )
    for s in geometry.supports:
        frame.support(s.at / 1000, (1, 1, 1, 0, 0, 0))
    levels = [z / 1000 for z in shape.levels()]
    corner_nodes = [
        [frame.node(np.array(c) / 1000) for c in shape.corners_at(z * 1000)] for z in levels
    ]
    dead = fr.self_weight(frame)
    for a in tower.antennas:
        level = int(np.argmin([abs(z - a.elevation) for z in levels]))
        for n in corner_nodes[level]:
            dead.add_nodal(n, [0, 0, -a.weight * a.count * 1000 / len(corner_nodes[level])])
    if tower.linearWeight:
        for k in range(len(levels) - 1):
            w = tower.linearWeight * (levels[k + 1] - levels[k]) * 1000
            for n in corner_nodes[k] + corner_nodes[k + 1]:
                dead.add_nodal(n, [0, 0, -w / (2 * len(corner_nodes[k]))])
    cases = {"D": dead}
    directions = [("W0", np.array([1.0, 0.0, 0.0]), False)]
    if tower.section == "square":
        directions.append(("W45", np.array([1.0, 1.0, 0.0]) / math.sqrt(2.0), True))
    summaries: dict[str, Any] = {}
    for name, direction, diagonal in directions:
        panels = panel_winds(tower, shape, types, qz, coefficients, diagonal)
        antennas = antenna_forces(tower, qz, coefficients)
        loads = fr.Loads()
        for k, p in enumerate(panels):
            nodes = corner_nodes[k] + corner_nodes[k + 1]
            for n in nodes:
                loads.add_nodal(n, direction * p["F"] * 1000 / len(nodes))
        for a in antennas:
            level = int(np.argmin([abs(z - a["elevation"]) for z in levels]))
            for n in corner_nodes[level]:
                loads.add_nodal(n, direction * a["F"] * 1000 / len(corner_nodes[level]))
        cases[name] = loads
        summaries[name] = {
            "panels": panels,
            "antennas": antennas,
            "total": round(sum(p["F"] for p in panels) + sum(a["F"] for a in antennas), 2),
        }
    results = fr.solve(frame, cases)
    pairs, how = common.strength_pairs(settings, code_context.current())
    notes.append(f"combinations: {how}")
    k_legs, k_bracing = coefficients.lengths()
    worst: dict[str, dict[str, Any]] = {}
    failing = 0
    for k in range(len(frame.members)):
        role = roles[k]
        kind = types[kinds[k]]
        length = frame.length(k)
        best: tuple[float, str, str, float] | None = None
        for combo, d, w in pairs:
            for name, _, _ in directions if w else [("W0", None, None)]:
                n = d * results["D"].axial(k) + (w * results[name].axial(k) if w else 0.0)
                m = d * results["D"].end_moments(k)[5]
                if w:
                    m += w * results[name].end_moments(k)[5]
                ratio, note = common.check_member(
                    kind, length, k_legs if role == "leg" else k_bracing, n, m
                )
                if best is None or ratio > best[0]:
                    best = (ratio, combo + (f", {name}" if w else ""), note, n)
        assert best is not None
        if best[0] > 1.0:
            failing += 1
        current = worst.get(role)
        if current is None or best[0] > current["ratio"]:
            worst[role] = {
                "role": role,
                "member": k + 1,
                "type": kind.id,
                "section": kind.label,
                "length": round(length, 3),
                "axial": round(best[3] / 1000, 2),
                "ratio": round(best[0], 3),
                "combination": best[1],
                "note": best[2],
            }
    reactions = _base_reactions(frame, results, pairs, directions)
    notes.append(
        f"wind: {coefficients.source()}, gust factor {coefficients.gust:g}; panels loaded at "
        "their corner nodes; members checked |N| / NRd + |M| / MRd by the pack's steel method"
    )
    if failing:
        notes.append(f"{failing} member(s) of {len(frame.members)} exceed their resistance")
    notes.append(
        "not covered: ice, the dynamic response of flexible towers, guyed masts, antenna twist "
        "and sway limits, connections and anchor bolts"
    )
    return {
        "panels": summaries["W0"]["panels"],
        "antennas": summaries["W0"]["antennas"],
        "windTotals": {k: v["total"] for k, v in summaries.items()},
        "rows": list(worst.values()),
        "reactions": reactions,
        "members": len(frame.members),
        "failing": failing,
        "notes": notes,
    }


def _base_reactions(
    frame: fr.Frame, results: dict[str, fr.FrameResult], pairs: list[Any], directions: list[Any]
) -> dict[str, Any]:
    """Service base shear [kN], overturning moment [kN·m], and the largest leg compression and
    uplift under the factored combinations [kN]."""
    supports = sorted(frame.supports)
    out: dict[str, Any] = {}
    dead = sum(results["D"].reactions[n][2] for n in supports) / 1000
    out["weight"] = round(dead, 2)
    for name, _, _ in directions:
        res = results[name]
        shear = (
            math.hypot(
                sum(res.reactions[n][0] for n in supports),
                sum(res.reactions[n][1] for n in supports),
            )
            / 1000
        )
        moment = 0.0
        for n in supports:
            p = frame.nodes[n]
            r = res.reactions[n]
            moment += math.hypot(p[1] * r[2], p[0] * r[2])
        out[name] = {"shear": round(shear, 2), "moment": round(moment / 1000 / 2, 2)}
    compression = uplift = 0.0
    for _, d, w in pairs:
        for name, _, _ in directions:
            for n in supports:
                rz = d * results["D"].reactions[n][2] + (
                    w * results[name].reactions[n][2] if w else 0
                )
                compression = max(compression, rz / 1000)
                uplift = min(uplift, rz / 1000)
    out["legCompression"] = round(compression, 2)
    out["legUplift"] = round(-uplift, 2)
    return out
