"""Diaphragm chords, collectors and connections of the floors (the code pack's seismic rules).

Each floor of the building model is a horizontal beam that carries its seismic force to the
lines of vertical elements (frames and structural walls). Per level and direction:

- the diaphragm force Fpx = (Σ Fi / Σ wi) wpx over the levels at and above it, Fi the
  equivalent static storey forces of the analysis (EX, EY; BNBC Sec 2.5.7) and wi the seismic
  weights (the nodes' masses), at least 0.2 and at most 0.4 SDS I wpx with SDS = 2.5 (2/3) Z S.
  BNBC 2020 gives no diaphragm force of its own; this is ASCE 7-05 Sec 12.10.1.1, the standard
  BNBC Sec 2.5 follows (the pack's ``transfer.diaphragm``);
- the chords: the floor as a simple beam spanning the outermost lines across the force,
  M = Fpx L / 8, L the floor's extent across the force; the chord force T = M / D, D its
  extent along the force, carried by the edge beams along the span (their top and bottom
  bars, φ As fy with φ of tension). A simple span is on the safe side for floors with inner
  frames;
- the collectors: each structural wall along the force gathers its line's share of Fpx (the
  floor's force by tributary width between the lines of beams and walls along the force) over
  the floor's length on that line; beyond the wall's ends the beams on the line carry the part
  the wall does not touch, Fc = R (1 - lw / Lline). In Seismic Design Categories C and D the
  collectors take Ω0 Fc (Sec 2.5.5.6.3, p. 625);
- B12, the connections of irregular buildings (the pack's ``seismic.diaphragmConnections``,
  BNBC Sec 1.7.3.8(d)(i) and 2.5.5.6.2): in the categories and with the irregularities it
  names (:mod:`saengine.fem.irregularity`), the force of each floor-to-wall connection (the
  wall's line share R of Fpx) and the collectors not designed for Ω0 go up by
  ``transfer.diaphragm.irregularIncrease`` (+25 %). The connection force is reported per wall
  (kN and kN/m along it) for its design; the projecting wings of a plan with re-entrant
  corners (1.7.3.8(d)(ii)) get a note, unless the design uses the response spectrum on the 3D
  model (the exception).

Units: mm, N inside; reported in kN. Clause references from the pack (``seismic.clauses``).
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from saengine.codes import context as code_context

__all__ = ["CLAUSES", "diaphragm_forces", "diaphragms_of"]


class _PackClauses(dict):
    """``CLAUSES[key]``: the code pack's clause reference (``seismic.clauses``), read when used."""

    _KEYS: ClassVar[dict[str, str]] = {
        "collectors": "diaphragmCollectors",
        "irregular": "diaphragmConnections",
        "wings": "diaphragmWings",
        "force": "diaphragmForce",
        "phi": "diaphragmPhi",
    }

    def __getitem__(self, key: str) -> str:
        from saengine.fem.seismic_design import clauses

        return clauses().get(self._KEYS.get(key, key), "")


CLAUSES: dict[str, str] = _PackClauses()

G = 9.80665
_ON_LINE = 1.0  # mm


def diaphragm_forces(
    levels: list[float],
    storey_forces: list[float],
    weights: list[float],
    sds: float,
    importance: float,
) -> list[tuple[float, float, float]]:
    """Per level, bottom up: (Fpx, lower bound, upper bound) [N] from the storey forces Fi
    and weights wi [N] (ASCE 7-05 Eq. 12.10-1 with the pack's bounds)."""
    table = code_context.pack_table("transfer").diaphragm
    out = []
    for k in range(len(levels)):
        forces = sum(abs(f) for f in storey_forces[k:])
        weight = sum(weights[k:])
        wpx = weights[k]
        fpx = forces / weight * wpx if weight > 0 else 0.0
        low = table.forceMin * sds * importance * wpx
        high = table.forceMax * sds * importance * wpx
        out.append((min(max(fpx, low), high), low, high))
    return out


def _bars_area(object_type: Any) -> float:
    """Area [mm²] of a beam type's top and bottom bars."""
    reinforcement = getattr(object_type, "reinforcement", None)
    if reinforcement is None:
        return 0.0
    from saengine.design.rc import bar_area

    return sum(
        g.count * bar_area(g.dia)
        for g in reinforcement.longitudinal
        if g.position in ("top", "bottom")
    )


def _fy(object_type: Any, mats: dict[str, Any]) -> float:
    reinforcement = getattr(object_type, "reinforcement", None)
    bars = mats.get(reinforcement.material) if reinforcement else None
    return float(bars.steel.fy) if bars is not None and bars.steel is not None else 0.0


def diaphragms_of(
    project: dict[str, Any],
    building: Any,
    types: dict[str, Any],
    mats: dict[str, Any],
    settings: Any,
    irregular: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The diaphragm elements of the design report: ``{"elements", "skipped", "notes"}``, one
    element (``kind`` "diaphragm") per floor with its chord and collector checks and, under
    ``"connections"``, the design force of each floor-to-wall connection. ``irregular``: the
    building's irregularities (:func:`saengine.fem.irregularity.assess`), for the connection
    increase of irregular buildings."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union

    from saengine.design.check import _check
    from saengine.fem.seismic_design import (
        peak_ground_acceleration,
        seismic_design_category,
        static_storey_forces,
        zone_of,
    )
    from saengine.library.bim import BeamElement, SlabElement, WallElement
    from saengine.library.settings import derived

    found: dict[str, Any] = {"elements": [], "skipped": [], "notes": []}
    by_case = {axis: static_storey_forces(project, f"E{axis}") for axis in ("X", "Y")}
    if not any(by_case.values()):
        return found
    table = code_context.pack_table("transfer").diaphragm
    values = derived(settings)
    sds = table.plateau * peak_ground_acceleration(settings)
    importance = float(values.get("seismicImportance") or 1.0)
    omega = float(values.get("omega") or 1.0)
    category = seismic_design_category(
        zone_of(values.get("Z")), settings.site.siteClass, settings.occupancy.category
    )
    amplify = category in table.collectorCategories
    phi = float(code_context.table("factors").phi["tension"])
    # B12: +25 % on the connections (and the collectors not designed for Ω0) of irregular
    # buildings in the categories the pack names.
    connections = (irregular or {}).get("connections") or {}
    increase = float(connections.get("factor") or 1.0) if connections.get("applies") else 1.0
    because = (
        ", ".join(_irregularity_label(t) for t in connections.get("types", []))
        if increase > 1.0
        else ""
    )

    weights_at: dict[float, float] = {}
    for node in project.get("nodes", []):
        mass = node.get("mass") or [0.0]
        if mass and mass[0]:
            z = round(float(node["coords"][2]), 3)
            weights_at[z] = weights_at.get(z, 0.0) + float(mass[0]) * G
    stories = {round(float(s.elevation) / 1e3, 3): s for s in building.stories}

    slabs: dict[float, list[Any]] = {}
    beams: dict[float, list[tuple[Any, np.ndarray, np.ndarray]]] = {}
    walls: list[tuple[Any, np.ndarray, np.ndarray, float, float]] = []
    for e in building.elements:
        if isinstance(e, SlabElement):
            polygon = Polygon([(float(x), float(y)) for x, y in e.boundary])
            if polygon.is_valid and polygon.area > 0:
                slabs.setdefault(round(float(e.elevation) / 1e3, 3), []).append(polygon)
        elif isinstance(e, BeamElement):
            beams.setdefault(round(float(e.elevation) / 1e3, 3), []).append(
                (e, np.array(e.start, dtype=float), np.array(e.end, dtype=float))
            )
        elif isinstance(e, WallElement) and getattr(types.get(e.type), "structural", False):
            walls.append(
                (
                    e,
                    np.array(e.start, dtype=float),
                    np.array(e.end, dtype=float),
                    float(e.bottom),
                    float(e.top),
                )
            )

    for axis, case_levels in by_case.items():
        if not case_levels:
            continue
        levels = [lv["z"] for lv in case_levels]
        forces = [lv["force"] for lv in case_levels]
        weights = [weights_at.get(round(z, 3), 0.0) for z in levels]
        if not any(weights):
            found["notes"].append(
                f"diaphragms {axis}: the analysis model has no masses; chords and collectors "
                "not designed"
            )
            continue
        design = diaphragm_forces(levels, forces, weights, sds, importance)
        along = 0 if axis == "X" else 1  # the force's direction
        across = 1 - along
        for z, (fpx, low, high), wpx in zip(levels, design, weights, strict=False):
            key = round(z, 3)
            outline = slabs.get(key)
            if not outline or fpx <= 0:
                continue
            floor = unary_union(outline)
            x0, y0, x1, y1 = floor.bounds
            lo, hi = np.array([x0, y0]), np.array([x1, y1])
            depth = float(hi[along] - lo[along])  # D, along the force
            span = float(hi[across] - lo[across])  # L, across the force
            if depth <= 0 or span <= 0:
                continue
            story = stories.get(key)
            name = story.name if story is not None else f"{z:g} m"
            element = _element_for(found, name)
            element["forces"][axis] = {
                "Fpx_kN": round(fpx / 1e3, 1),
                "min_kN": round(low / 1e3, 1),
                "max_kN": round(high / 1e3, 1),
                "wpx_kN": round(wpx / 1e3, 1),
            }
            level_beams = beams.get(key, [])
            # ── chords ──
            moment = fpx * span / 8
            chord = moment / depth
            for edge, at in (("low", lo[along]), ("high", hi[along])):
                on_edge = [
                    (e, a, c)
                    for e, a, c in level_beams
                    if abs(a[along] - at) <= 1e3
                    and abs(c[along] - at) <= 1e3
                    and abs(c[across] - a[across]) > _ON_LINE
                ]
                capacity, weakest = _weakest(on_edge, types, mats, phi)
                side = f"{'-' if edge == 'low' else '+'}{'XY'[along]} edge"
                element["checks"].append(
                    _check(
                        f"Chord, force along {axis}, {side}",
                        chord / 1e3,
                        capacity / 1e3,
                        "kN",
                        f"E{axis}",
                        f"T = M / D, M = Fpx L / 8 = {moment / 1e6:.1f} kN·m, L = "
                        f"{span / 1e3:.2f} m, D = {depth / 1e3:.2f} m; Fpx = {fpx / 1e3:.1f} kN "
                        f"({CLAUSES['force']}); φ As fy of "
                        + (
                            f"the edge beams' top and bottom bars (weakest {weakest})"
                            if on_edge
                            else "no edge beam: provide chord bars along the slab edge"
                        )
                        + f", φ = {phi:g} ({CLAUSES['phi']})",
                    )
                )
            # ── collectors ──
            lines = sorted(
                {
                    round(float(a[across]), 0)
                    for e, a, c in level_beams
                    if abs(c[across] - a[across]) <= _ON_LINE
                }
                | {
                    round(float(w0[across]), 0)
                    for w, w0, w1, bottom, top in walls
                    if bottom < z * 1e3 - 1.0 <= top and abs(w1[across] - w0[across]) <= _ON_LINE
                }
            )
            for wall, w0, w1, bottom, top in walls:
                if not bottom < z * 1e3 - 1.0 <= top or abs(w1[across] - w0[across]) > _ON_LINE:
                    continue
                line_at = float(w0[across])
                line = LineString(
                    [
                        _point(lo[along] - 1, line_at, along),
                        _point(hi[along] + 1, line_at, along),
                    ]
                )
                length = float(floor.intersection(line).length)
                wall_length = float(np.linalg.norm(w1 - w0))
                share = _tributary(lines, line_at, float(lo[across]), float(hi[across])) / span
                reaction = fpx * share
                # B12: the floor-to-wall connection takes the line's share (increased for
                # irregular buildings), for its design.
                element.setdefault("connections", []).append(
                    {
                        "wall": wall.id,
                        "direction": axis,
                        "force_kN": round(increase * reaction / 1e3, 1),
                        "perMetre_kN_m": round(increase * reaction / max(wall_length, 1.0), 2),
                        "increase": increase,
                    }
                )
                # B21: shear friction across the wall's construction joint at the floor
                # (saengine.design.rc_detailing), the wall's vertical bars crossing it.
                joint = _wall_joint(wall, types, mats, increase * reaction, wall_length, axis)
                if joint is not None:
                    element["checks"].append(joint)
                if length <= wall_length + _ON_LINE:
                    continue  # the wall spans its whole line: no collector
                collector = reaction * (1 - wall_length / length)
                factor = omega if amplify else increase
                on_line = [
                    (e, a, c)
                    for e, a, c in level_beams
                    if abs(a[across] - line_at) <= _ON_LINE and abs(c[across] - line_at) <= _ON_LINE
                ]
                capacity, weakest = _weakest(on_line, types, mats, phi)
                element["checks"].append(
                    _check(
                        f"Collector at {wall.id}, force along {axis}",
                        factor * collector / 1e3,
                        capacity / 1e3,
                        "kN",
                        f"E{axis}",
                        f"Fc = R (1 - lw / Lline), R = {share:.2f} Fpx = {reaction / 1e3:.1f} kN "
                        f"by tributary width, lw = {wall_length / 1e3:.2f} m, Lline = "
                        f"{length / 1e3:.2f} m"
                        + (
                            f"; × Ω0 = {omega:g} (Category {category}, {CLAUSES['collectors']})"
                            if amplify
                            else f"; × {increase:g} for {because} ({CLAUSES['irregular']})"
                            if increase > 1.0
                            else f" (Category {category}: no Ω0, {CLAUSES['collectors']})"
                        )
                        + "; φ As fy of "
                        + (
                            f"the collector beams' top and bottom bars (weakest {weakest})"
                            if on_line
                            else "no beam on the wall's line: provide collector bars in the slab"
                        ),
                    )
                )
    for element in found["elements"]:
        checks = element["checks"]
        element["utilisation"] = max((c["utilisation"] for c in checks), default=0.0)
        element["ok"] = all(c["ok"] for c in checks)
    found["elements"] = [e for e in found["elements"] if e["checks"]]
    if found["elements"]:
        found["notes"].append(
            f"diaphragms: chords and collectors of {len(found['elements'])} floors by the "
            f"diaphragm force Fpx ({CLAUSES['force']}, SDS = {sds:.3f} g, I = {importance:g}); "
            "chords from a simple span between the outermost lines; collectors by tributary "
            f"width, with Ω0 in Categories {', '.join(table.collectorCategories)} "
            f"({CLAUSES['collectors']}); the floor-to-wall connection forces are listed per "
            "wall for their design"
        )
    if increase > 1.0:
        found["notes"].append(
            f"diaphragm connections: Category {category} with {because}: the connection forces "
            f"of the floors to the walls and collectors, and the collectors not designed for "
            f"Ω0, × {increase:g} ({CLAUSES['irregular']})"
        )
    if connections.get("wings"):
        if connections.get("wingsExempt"):
            found["notes"].append(
                "projecting wings (re-entrant corners): the forces come from the response "
                f"spectrum on the three-dimensional model, as the exception allows "
                f"({CLAUSES['wings']})"
            )
        else:
            found["notes"].append(
                "projecting wings (re-entrant corners): design the chords and collectors for "
                "the wings moving in the same and in opposite directions, or use the response "
                "spectrum design on the three-dimensional model, which satisfies it "
                f"({CLAUSES['wings']}); SAEngine does not work out the wings' own motion"
            )
    return found


def _wall_joint(
    wall: Any, types: dict[str, Any], mats: dict[str, Any], force: float, length: float, axis: str
) -> dict[str, Any] | None:
    """The shear-friction check of a floor-to-wall connection (B21), None for a wall type
    without concrete or vertical bars."""
    from saengine.design.rc_detailing import wall_joint_check

    wall_type = types.get(wall.type)
    concrete = mats.get(getattr(wall_type, "material", None))
    properties = getattr(concrete, "concrete", None)
    fy = _fy(wall_type, mats)
    if properties is None or fy <= 0:
        return None
    return wall_joint_check(
        f"Floor-to-wall joint at {wall.id}, force along {axis}",
        force,
        wall_type,
        length,
        float(properties.fc),
        fy,
        f"E{axis}",
    )


def _irregularity_label(kind: str) -> str:
    from saengine.fem.irregularity import label

    return label(kind)


def _point(a: float, b: float, along: int) -> tuple[float, float]:
    return (a, b) if along == 0 else (b, a)


def _tributary(lines: list[float], at: float, low: float, high: float) -> float:
    """Tributary width [mm] of the line at ``at`` among ``lines`` within [low, high]."""
    inside = sorted({min(max(v, low), high) for v in lines} | {min(max(at, low), high)})
    k = inside.index(min(max(at, low), high))
    below = low if k == 0 else (inside[k - 1] + inside[k]) / 2
    above = high if k == len(inside) - 1 else (inside[k] + inside[k + 1]) / 2
    return max(above - below, 0.0)


def _weakest(
    members: list[tuple[Any, np.ndarray, np.ndarray]],
    types: dict[str, Any],
    mats: dict[str, Any],
    phi: float,
) -> tuple[float, str]:
    """(φ As fy [N], beam id) of the weakest beam of ``members``; (0, "") without one."""
    best: tuple[float, str] | None = None
    for e, _, _ in members:
        object_type = types.get(e.type)
        value = phi * _bars_area(object_type) * _fy(object_type, mats)
        if best is None or value < best[0]:
            best = (value, e.id)
    return best if best is not None else (0.0, "")


def _element_for(found: dict[str, Any], name: str) -> dict[str, Any]:
    for element in found["elements"]:
        if element["story"] == name:
            return element
    element = {
        "id": f"Diaphragm {name}",
        "kind": "diaphragm",
        "type": None,
        "story": name,
        "members": [],
        "forces": {},
        "checks": [],
        "notes": [],
        "utilisation": 0.0,
        "ok": True,
    }
    found["elements"].append(element)
    return element
